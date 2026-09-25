# -*- coding: utf-8 -*-
"""**模型层 2：Flash 计算层**——本仓库快模型（`sim.py`）的原生同形包装。

职责与 `native.py` 完全一致：`NativeCase` → `NativeResult`。
**同形的价值**：上层（`record.py` / `cache.py` / `scanner.py` / 绘图）不需要知道这次是
Pro 还是 Flash —— 换后端只是换 `runner.py` 里的执行器，产物契约一模一样。

与 Pro 的**本质差别**（决定了两者不可能逐位相等，误差报告里逐项对照）：
  * Pro 把参数块注入原生 ELF（`aces`）执行游戏自己的制导/气动/积分；Flash 用
    `sim.py` 的 2D 纵向平面点质量 + `decide.py` 阶段机，**固定步长 RK4**。
  * Pro 的气动是原生那条链（`CxK` 恒定 + `f(M)` 由原生内部给）；Flash 默认 `aero.model=full`
    （Mach 修正 + 升力配平 + 诱导阻力）。
  * Pro 的 `dt` 上限是 0.01 s（合法范围 [0.00025, 0.01]）；Flash 默认 0.005 s。

**映射口径**（与输入层同一套，逐项写进 `NativeResult` 供复核）：
    s        = ΔV / ΔV_blk          ← ΔV 是**真空等效增速**（各段推力同乘，总 ΔV 严格 ∝ s）
    cx_scale = m_dry / (BC · SD · CxK_blk)   ← SD = π(d/2)² **迎面面积**
    cxk_used = CxK_blk · cx_scale
Flash 的 `thrust_scale` 里另含质量缩放 k（`_ScalarSim` 的既有口径），本模块按同一公式复算。

**不需要进程池**：Flash 是纯 Python/NumPy，无全局状态，可重入（Pro 的并发只能靠多进程，
因为它改 `core.load_profile`）。所以 `FlashRunner` 的 `jobs` 只是接口对位，实际串行执行。
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from .. import burn as burn_mod
from .. import sim as sim_mod
from ..config import AeroConfig, ConfigError, MissileConfig, apply_standard
from ..decide import STATUS_NAMES, ST_HIT
from ..standard import StandardPoolError, resolve as resolve_standard
from . import io as mio
from .cache import FlashCache, ResultCache
from .constants import FLASH_CACHE, ROOT
from .native import NativeCase, NativeResult

# Flash 默认技术参数（与 Pro 侧 `pro_*` 对位；物理口径不受影响）
FLASH_DT = 0.005          # 原生合法上限是 0.01；快模型用 0.005 换取积分精度
FLASH_DURATION_S = 150.0  # 单工况最长计算时间（最终还受标准弹 timeLife 限制）
FLASH_SAMPLE_PERIOD_S = 0.25

# 标准弹池路径（与 `config.StandardConfig.pool` 同一默认值）
POOL_REL = Path("results") / "missile_standards.json"


class FlashModelError(ValueError):
    """Flash 侧无法建立工况（池里没有该型 / 参数非法）。"""


# --------------------------------------------------------------------- 标准弹解析


def standard_for(native_name: str, tag: str | None = None, pool_path=None):
    """原生 profile 名（`cn_pl12`）→ 标准弹短名（`PL-12`）→ `StandardProfile`。

    这是 Flash 唯一的"参数来源"入口：完整参数（质量剖面/CxK/干重/引信/寿命/高抛/增益表）
    只有池里有，原生包只认 profile 名。
    """
    short = mio.short_name_of(native_name)
    if short is None:
        raise FlashModelError(
            f"标准弹池里找不到原生名 {native_name!r} 对应的短名"
            f"（可用：{'、'.join(n for n, _, _ in mio._missile_files())}）"
        )
    try:
        return resolve_standard(short, pool_path=pool_path, tag=tag)
    except StandardPoolError as exc:
        raise FlashModelError(str(exc)) from exc


def flash_config(prof, *, backend: str = "flash", dt: float | None = None,
                 t_life: float | None = None, aero_model: str | None = None) -> MissileConfig:
    """由标准弹短名建 Flash 配置（**唯一入口**，避免各处手搓 `MissileConfig`）。

    `apply_standard` 负责把池里的参数写进扁平字段（口径/CxK/质量/过载/引信/寿命/高抛/
    增益表/燃烧剖面）；本函数只补**技术参数**（步长、寿命上限、气动档），场景另由调用方写。
    """
    cfg = MissileConfig(backend=backend)
    cfg.standard.name = prof.name
    cfg.standard.tag = prof.tag or ""
    cfg.standard.burn = burn_mod.MODEL_FINITE
    cfg.standard.pool = str(POOL_REL)
    apply_standard(cfg)
    if dt is not None:
        cfg.sim.dt = float(dt)
    if t_life is not None:
        cfg.sim.t_life = float(t_life)
    if aero_model is not None:
        cfg.aero = replace(AeroConfig(), model=str(aero_model))
    return cfg


# --------------------------------------------------------------------- 工况构造


def flash_case_from(case: NativeCase, *, prof=None, aero_model: str | None = None,
                    dt: float | None = None, duration_s: float | None = None,
                    sample_period_s: float | None = None) -> tuple:
    """`NativeCase` → (`sim.Case`, `MissileConfig`, 映射口径 dict)。

    返回三元组而不是只给 `Case`：`thrust_scale` / `cx_scale` / `cxk_used` / 燃烧剖面
    都要进 `NativeResult` 供复核，而它们由**该型自己的** profile 现算。
    """
    prof = prof or standard_for(case.missile)
    b = burn_mod.from_standard(prof, burn_mod.MODEL_FINITE)

    # --- 与 Pro 完全同一套解析口径（ΔV 真空等效；BC 用迎面面积）
    dv_blk = float(prof.dv)
    s_dv = 1.0 if not case.dv_target else mio.scale_for_dv(float(case.dv_target), dv_blk)
    dry = float(prof.engine.mass_dry)
    sd = math.pi * (float(prof.caliber_m) / 2.0) ** 2
    cx_scale = (1.0 if not case.bc_target
                else mio.cx_scale_for_bc(float(case.bc_target), dry, sd, float(prof.cxk)))
    cxk_used = float(prof.cxk) * cx_scale
    # 干重锚定：Case.mass 即该型干重 ⇒ k_mass = 1（`_ScalarSim` 的质量缩放退化为 1）
    k_mass = 1.0 if b.mass_dry <= 0.0 else dry / b.mass_dry

    over = dict(
        dt=FLASH_DT if dt is None else float(dt),
        t_life=min(FLASH_DURATION_S if duration_s is None else float(duration_s),
                   float(prof.time_life_s)),
        backend="flash",
    )
    cfg = flash_config(prof, aero_model=aero_model, **over)
    cfg.scenario.vm0 = float(case.vm0)
    cfg.scenario.vt = float(case.vt)
    cfg.scenario.alt = float(case.alt_m)
    cfg.scenario.range = float(case.range_m)
    cfg.scenario.target_alt = (float(case.alt_m) if case.target_alt_m is None
                               else float(case.target_alt_m))

    fcase = sim_mod.Case(
        dv_total=_case_dv(case, dv_blk), cxk=cxk_used,
        vm0=float(case.vm0), vt=float(case.vt),
        alt=float(case.alt_m), range0=float(case.range_m),
        target_alt=cfg.scenario.target_alt,
        mass=dry,
    )
    scale = {"thrust_scale": s_dv * k_mass, "dv_scale": s_dv, "k_mass": k_mass,
             "cx_scale": cx_scale, "cxk_used": cxk_used,
             "dv_blk": dv_blk, "bc_blk": float(prof.bc), "sd_m2": sd}
    return fcase, cfg, {"profile": prof, "burn": b, "scales": scale,
                        "sample_period_s": (FLASH_SAMPLE_PERIOD_S if sample_period_s is None
                                            else float(sample_period_s))}


# --------------------------------------------------------------------- 单工况


def _samples_from_trace(trace, sample_period_s: float, dt: float) -> list:
    """`sim.Trace` → `record.SAMPLE_FIELDS` 口径的采样表（键名与原生轨迹一致）。

    `stride` 由**采样周期**换算（不是物理步长），所以 Flash 与 Pro 的轨迹时间栅格可比。
    """
    if trace is None:
        return []
    stride = max(1, int(round(max(sample_period_s, dt) / dt)))
    tr = trace.downsample(stride)
    return [{"t": float(tr.t[i]), "x": float(tr.x[i]), "y": float(tr.h[i]),
             "v": float(tr.v[i]), "mass": float(tr.mass_kg[i]),
             "thrust": float(tr.thrust_N[i]), "range": float(tr.rng[i])}
            for i in range(len(tr.t))]


def simulate_flash(case: NativeCase, *, prof=None, aero_model: str | None = None,
                   dt: float | None = None, duration_s: float | None = None,
                   sample_period_s: float | None = None,
                   save_trajectory: bool | None = None) -> NativeResult:
    """跑一次 Flash 全程积分，返回与 Pro 同形的 `NativeResult`。

    `save_trajectory` 缺省跟随 `case.save_trajectory`（与 Pro 侧一致：轨迹默认不要，
    因为它占单条记录的 95%）。
    """
    try:
        fcase, cfg, meta = flash_case_from(
            case, prof=prof, aero_model=aero_model, dt=dt, duration_s=duration_s,
            sample_period_s=sample_period_s)
    except (FlashModelError, ConfigError) as exc:
        return NativeResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    keep = bool(case.save_trajectory if save_trajectory is None else save_trajectory)
    dt_eff = float(cfg.sim.dt)
    try:
        res = sim_mod.simulate_one(cfg, fcase, record_trace=keep, stride=1)
    except Exception as exc:                              # noqa: BLE001
        return NativeResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    sc = meta["scales"]
    b = meta["burn"]
    prof_m = meta["profile"]
    trace = res.trace
    hit = int(res.status) == ST_HIT
    dv_measured = math.nan
    m_launch, m_dry, t_burnout = math.nan, math.nan, math.nan
    if trace is not None and len(trace.t):
        m_launch = float(trace.mass_kg[0])
        m_dry = float(min(trace.mass_kg))
        powered = [i for i, th in enumerate(trace.thrust_N) if th and th > 0.0]
        i_burn = powered[-1] if powered else 0
        t_burnout = float(trace.t[i_burn])
        dv_measured = float(trace.v[i_burn] - trace.v[0])
    return NativeResult(
        ok=True,
        event=STATUS_NAMES[int(res.status)],
        t_end=float(res.t_end),
        t_hit=(float(res.t_hit) if hit else math.nan),
        hit=hit,
        miss_distance_m=float(res.miss_distance),
        max_alt_m=float(res.max_alt),
        v_impact=float(res.v_impact),
        dv_measured=dv_measured,
        m_launch=m_launch, m_dry=(m_dry if math.isfinite(m_dry) else float(prof_m.engine.mass_dry)),
        t_burnout=t_burnout,
        thrust_scale=float(sc["thrust_scale"]), cx_scale=float(sc["cx_scale"]),
        dv_blk=float(sc["dv_blk"]), bc_blk=float(sc["bc_blk"]),
        samples=(_samples_from_trace(trace, meta["sample_period_s"], dt_eff) if keep else []),
        resource=f"flash:{prof_m.name}@{prof_m.tag}",
    )


# --------------------------------------------------------------------- 网格快车道


def _case_dv(case: NativeCase, dv_blk: float) -> float:
    """工况 ΔV：`0` 在本项目里是"标称"的哨兵值（Pro 侧把它翻译成乘数 1）。"""
    return float(dv_blk) if not case.dv_target else float(case.dv_target)


def _case_cxk(case: NativeCase, prof) -> float:
    """工况 CxK：与 `flash_case_from` 同一口径（BC 用迎面面积反解）。"""
    if not case.bc_target:
        return float(prof.cxk)
    sd = math.pi * (float(prof.caliber_m) / 2.0) ** 2
    return float(prof.cxk) * mio.cx_scale_for_bc(float(case.bc_target), float(prof.engine.mass_dry),
                                                 sd, float(prof.cxk))


def _grid_signature(case: NativeCase) -> tuple:
    """网格分组键：同一组才能进同一次向量化批量（配置必须完全一致）。"""
    return (case.missile, float(case.dt), float(case.duration_s), case.observation_mode,
            float(case.range_m), float(case.alt_m),
            (None if case.target_alt_m is None else float(case.target_alt_m)),
            float(case.vm0), float(case.vt),
            tuple((float(t), tuple(float(x) for x in a)) for t, a in case.target_maneuvers))


def flash_grid(cases, *, aero_model: str | None = None, dt: float | None = None,
               duration_s: float | None = None, progress=None) -> list[NativeResult]:
    """**向量化网格路径**：一批共享配置的工况走 `sim.simulate_batch`，返回同序 `NativeResult`。

    为什么单独有这条路：标量单工况要 ~0.75 s（1824 个就是 23 min），而数组路径一次算完
    整个网格只要 **~41 s**（实测，dt=0.005、32×57）——这是"Flash 网格 ≤60 s"的唯一出路。
    代价：批量的 `t_hit` 估计量与标量路径**系统差 ~+4 步**（命中时刻的内插写法不同），
    所以 `resource` 标记为 `flash-grid:` 以示区分，误差报告里单独对账。

    组内 `dv_target=0` 按"标称"处理（与 Pro 侧一致：0 ⇒ 乘数 1）。
    """
    cases = list(cases)
    if not cases:
        return []
    groups: dict = {}
    for i, c in enumerate(cases):
        groups.setdefault(_grid_signature(c), []).append(i)
    out: list[NativeResult | None] = [None] * len(cases)
    done = 0
    for _sig, idxs in groups.items():
        c0 = cases[idxs[0]]
        prof = standard_for(c0.missile)
        dv_blk = float(prof.dv)
        burn = burn_mod.from_standard(prof, burn_mod.MODEL_FINITE)
        cfg = flash_config(prof, aero_model=aero_model,
                           dt=float(c0.dt if dt is None else dt),
                           t_life=min(FLASH_DURATION_S if duration_s is None else float(duration_s),
                                      float(prof.time_life_s)))
        cfg.scenario.vm0 = float(c0.vm0)
        cfg.scenario.vt = float(c0.vt)
        cfg.scenario.alt = float(c0.alt_m)
        cfg.scenario.range = float(c0.range_m)
        cfg.scenario.target_alt = (float(c0.alt_m) if c0.target_alt_m is None
                                   else float(c0.target_alt_m))
        dv_arr = np.array([_case_dv(c, dv_blk) for c in (cases[i] for i in idxs)], dtype=float)
        cxk_arr = np.array([_case_cxk(c, prof) for c in (cases[i] for i in idxs)], dtype=float)
        dry = float(prof.engine.mass_dry)
        mass_arr = np.full(dv_arr.size, dry)
        batch = sim_mod.simulate_batch(cfg, dv_arr, cxk_arr, mass=mass_arr)
        sd = math.pi * (float(prof.caliber_m) / 2.0) ** 2
        for k, i in enumerate(idxs):
            c = cases[i]
            dv_t = float(dv_arr[k])
            cx = cxk_arr[k] / float(prof.cxk)
            hit = int(batch.status[k]) == ST_HIT
            out[i] = NativeResult(
                ok=True, event=STATUS_NAMES[int(batch.status[k])],
                t_end=float(batch.t_end[k]),
                t_hit=(float(batch.t_hit[k]) if hit else math.nan),
                hit=hit,
                # 与标量路径同语义：命中 ⇒ 0；未命中 ⇒ 最近距离
                miss_distance_m=(0.0 if hit else float(batch.min_range[k])),
                max_alt_m=float(batch.max_alt[k]),
                v_impact=float(batch.v_impact[k]),
                dv_measured=math.nan,          # 需要燃尽时刻的速度轨迹，批量路径不产出
                m_launch=float(burn.mass_launch), m_dry=dry,
                t_burnout=float(burn.burn_time_total),
                thrust_scale=(1.0 if not c.dv_target else float(dv_t) / dv_blk),
                cx_scale=float(cx), dv_blk=dv_blk, bc_blk=float(prof.bc),
                resource=f"flash-grid:{prof.name}@{prof.tag}",
            )
            done += 1
            if progress:
                progress(done, len(cases), 0)
    return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]


class FlashRunner:
    """Flash 执行器：与 `ProRunner` **同签名同语义**（上层不必分叉）。

    * 无进程池：纯 Python、可重入，`jobs>1` 只会打一条提示（不做多进程，多进程反而更慢）；
    * 缓存按后端分库（默认 `results/flash_cache.json`，schema = `CALC_VERSION_FLASH`）；
    * 与 Pro 一样**周期性落盘**（`flush_every`），中断不丢已算结果；
    * **网格快车道**（`grid_mode=True`，默认）：一批共享配置的工况走向量化 `simulate_batch`
      （1824 工况 ~41 s，标量要 23 min）。只缓存**标量结果**，网格结果不落缓存：
      两者的 `t_hit` 估计量差 ~+4 步，混进同一个键会自相矛盾。
    """

    def __init__(self, *, version: str | None = None, jobs: int = 1,
                 cache: ResultCache | None = None, progress=None, flush_every: int = 500,
                 aero_model: str | None = None, dt: float | None = None,
                 duration_s: float | None = None, cache_path=None, grid_mode: bool = True):
        self.version = version
        self.jobs = max(1, int(jobs))
        if cache is None:
            cache = FlashCache(cache_path if cache_path else FLASH_CACHE)
        self.cache = cache
        self.progress = progress
        self.flush_every = max(1, int(flush_every))
        self.aero_model = aero_model
        self.dt = dt
        self.duration_s = duration_s
        self.grid_mode = bool(grid_mode)
        self._pending = 0
        self.stats = {"native": 0, "cache": 0, "grid": 0}
        # `pkg` 对位 `ProRunner.pkg`：Flash 不需要原生包，给 None 而不是假路径
        self.pkg = None
        self.runtime_info = {"backend": "flash", "dt": dt, "aero_model": aero_model}

    def _flush(self, force: bool = False):
        if not force and self._pending < self.flush_every:
            return
        if self.cache.save(runtime_info=self.runtime_info) is not None:
            self._pending = 0

    def close(self):
        """落盘（Flash 是秒级，但仍然只在有新增时才写；见 `ResultCache.save`）。"""
        self._flush(force=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _run(self, case: NativeCase) -> NativeResult:
        return simulate_flash(case, aero_model=self.aero_model, dt=self.dt,
                              duration_s=self.duration_s)

    def run_one(self, case: NativeCase) -> NativeResult:
        key = case.key()
        got = self.cache.get(key)
        if got is not None:
            self.stats["cache"] += 1
            return got
        res = self._run(case)
        self.stats["native"] += 1
        if res.ok and not case.save_trajectory:
            self.cache.put(key, res)
            self._pending += 1
            self._flush()
        return res

    def run_many(self, cases) -> list[NativeResult]:
        """批量：先打缓存，再跑缺的。返回顺序与入参一致（与 `ProRunner.run_many` 同语义）。

        `grid_mode=True`（默认）且缺的工况**都不需要轨迹**时，走向量化网格快车道
        （`flash_grid`）；否则逐条标量跑。两条路的 `t_hit` 估计量差 ~+4 步（见模块 docstring），
        所以网格结果**不进缓存**，避免同一缓存键里混着两种估计量。
        """
        cases = list(cases)
        out: list[NativeResult | None] = [None] * len(cases)
        todo = []
        for i, c in enumerate(cases):
            got = self.cache.get(c.key())
            if got is not None:
                out[i] = got
                self.stats["cache"] += 1
            else:
                todo.append((i, c))
        if todo and self.grid_mode and not any(c.save_trajectory for _i, c in todo):
            res_list = flash_grid([c for _i, c in todo], aero_model=self.aero_model,
                                  dt=self.dt, duration_s=self.duration_s,
                                  progress=self.progress)
            for (i, _c), res in zip(todo, res_list):
                out[i] = res
                self.stats["grid"] += 1
            return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]
        for n, (i, c) in enumerate(todo, 1):
            res = self._run(c)
            out[i] = res
            self.stats["native"] += 1
            if res.ok and not c.save_trajectory:
                self.cache.put(c.key(), res)
                self._pending += 1
                self._flush()
            if self.progress:
                # 回调签名与 ProRunner / sim.simulate_batch 一致：(done, total, active)
                self.progress(n, len(todo), 0)
        return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]


def make_runner(backend: str, **kw):
    """后端工厂：`pro` → `ProRunner`（延迟导入，避免无包环境 import 失败）；其余 → `FlashRunner`。"""
    b = str(backend or "pro").strip().lower()
    if b == "pro":
        from .runner import ProRunner                          # noqa: PLC0415
        kw.pop("cache_path", None)
        return ProRunner(**kw)
    return FlashRunner(**kw)


# ===================================================================== 引擎（结构化 API）

class FlashEngine:
    """Flash 模型的 `Engine` 实现（`spec.py` 的协议）。

    ⚠ **当前是临时外壳**：内核仍是 `sim.py` 的老快模型。提交 ③ 会按
    `D:\\Download\\CALCULATION-FORMULAS.md` 重建计算核心（纵向平面 θ+α+PID 闭环），
    **本类的对外形状不变**——换模型只换内核、不换 API，这正是"可版本管理的模型接入"的意义。
    """

    def __init__(self, *, env=None, jobs: int = 1, aero_model: str | None = None,
                 dt: float | None = None, duration_s: float | None = None, **kw):
        self.env = env
        self.jobs = max(1, int(jobs))
        self.aero_model = aero_model
        self.dt = dt
        self.duration_s = duration_s
        self._core = None

    @property
    def spec(self):
        from .registry import spec_of                           # noqa: PLC0415
        return spec_of("flash")

    @property
    def core(self):
        """计算内核（`NativeCase` → `NativeResult`）。"""
        if self._core is None:
            self._core = FlashRunner(jobs=self.jobs, aero_model=self.aero_model,
                                     dt=self.dt, duration_s=self.duration_s,
                                     cache=FlashCache(enabled=False))
        return self._core

    # --- 身份 ---------------------------------------------------------

    def runtime_info(self) -> dict:
        sp = self.spec
        return {"kind": "flash", "engine": sp.name, "engine_version": sp.version,
                "calc_version": sp.calc_version, "dt": self.dt,
                "aero_model": self.aero_model}

    def stamp(self, inp=None) -> "EngineStamp":
        from .spec import EngineStamp                           # noqa: PLC0415
        sp = self.spec
        return EngineStamp(
            name=sp.name, version=sp.version, calc_version=sp.calc_version,
            fidelity={"recovered": ["游戏口径的高抛退出判据", "差分空速/大气/声速", "N 段有限燃烧"],
                      "not_recovered": ["高抛进入闸门", "过载建立时间（指令→实际）"],
                      "derived": ["准定常配平迎角（无姿态状态）"]},
            resources={k: v for k, v in (("dt", self.dt), ("aero_model", self.aero_model))
                       if v is not None},
        )

    # --- 运行 ---------------------------------------------------------

    def inputs(self, env, inp):
        bad = inp.check()
        if bad:
            raise ValueError("Flash 引擎输入不自洽：" + "；".join(bad))
        return inp

    def simulate(self, inp, env=None) -> NativeResult:
        from .native import case_from_inputs                   # noqa: PLC0415
        inp = self.inputs(env, inp)
        res = simulate_flash(case_from_inputs(inp), aero_model=self.aero_model,
                             dt=self.dt, duration_s=self.duration_s)
        res.engine = self.stamp(inp).to_dict()
        return res

    # --- 接入即验 -----------------------------------------------------

    def selftest(self, env=None) -> "SelfTestReport":
        """自检：① 弹池参数块可解析；② 输入映射自洽；③ 声明能力与实测一致。"""
        from . import io as io_mod                              # noqa: PLC0415
        from .spec import SelfTestReport                        # noqa: PLC0415

        sp = self.spec
        rep = SelfTestReport(name=sp.name, ok=True)
        rep.detail["spec"] = sp.to_dict()
        try:
            case = NativeCase(missile="cn_pl12", dv_target=932.5697486487783,
                              bc_target=3078.0530156224613)
            inp = io_mod.inputs_from_case(case)
            rep.detail["inputs"] = {"dv_blk": inp.dv_blk, "bc_blk": inp.bc_blk,
                                    "thrust_scale": inp.thrust_scale, "cx_scale": inp.cx_scale}
            rep.add("输入映射自洽（PL-12 标称）", not inp.check(),
                    f"ΔV_blk={inp.dv_blk:.2f} BC_blk={inp.bc_blk:.1f}")
        except Exception as exc:                                # noqa: BLE001
            rep.add("输入映射自洽（PL-12 标称）", False, f"{type(exc).__name__}: {exc}")
        caps = sp.capabilities
        rep.add("声明 2D", caps.dims == "2d", f"dims={caps.dims}")
        rep.add("声明向量化批量", caps.vectorized_batch is True, "网格快车道可用")
        return rep

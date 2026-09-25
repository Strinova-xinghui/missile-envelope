# -*- coding: utf-8 -*-
"""Pro 后端：调用信源包里的**原生仿真器**（Unicorn 执行游戏 2.59.0.28 的机器码）。

设计原则（见 AERO_PLAN §18/§20/§21）：

* **包体永不入库**。运行时（约 186 MB，含 ELF）只在 `WT_NATIVE_PKG` 指向的目录里，
  仓库只记录路径、ELF SHA-256 与参数指纹。找不到包时**明确报错**，不退回近似模型。
* **一次工况 = 一次原生全程积分**，所以有 `Cache`：键 = (版本, 弹型, 推力乘数, CxK 乘数, 场景)。
  同参数重复跑直接读缓存（一次性穷举后所有迭代都是秒级）。
* **(ΔV, BC) → (推力乘数 s, CxK 乘数) 的映射**见 `sweep.py`：BC 是解析反解，
  ΔV 需要标定（原生侧"实际速度增量 ≠ 真空 ΔV"，有阻力/重力损失）。

本模块**不 import** `missile_sim` 之外的任何原生依赖；原生包在子进程里才 import，
因此仓库单独克隆（无包）时其它模块仍可正常导入与自检。
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "results" / "pro_cache.json"

# 信源包默认位置（可用 WT_NATIVE_PKG 覆盖）；只放路径，不放内容
DEFAULT_PKG = r"E:\WT\wt-missile-backend-runtime-1.0.1"
ENV_PKG = "WT_NATIVE_PKG"

VERSION_28 = "2.59.0.28"
ELF_SHA256_28 = "94de54548da8eb616f391d04e117ca11c8cf7143e7c6be6dfb9468c40512591a"
ELF_REL = Path("inputs") / "elf" / ELF_SHA256_28 / "aces"

# 原生包支持的 profile（= blkx 文件名去后缀）；不含 Derby / R-Darter
NATIVE_PROFILES = {
    VERSION_28: ("us_aim_120a", "us_aim_120c_5", "us_aim_120d", "jp_aam4", "fr_mica_em",
                 "cn_pl12", "cn_pl12a", "su_r_77", "su_r_77_1", "su_r_73", "su_rvv_ae"),
}

# 外部输入容差与默认值
DT_DEFAULT = 0.01          # 原生合法上限，速度优先（AERO_PLAN §20.4）
DT_RANGE = (0.00025, 0.01)
HIT_EVENTS = ("contact", "proximity_fuse")


class ProRuntimeError(RuntimeError):
    """找不到/校验不过原生运行包（**不退回近似模型**）。"""


# --------------------------------------------------------------------- 运行时定位与校验


def resolve_pkg(pkg=None) -> Path:
    """定位原生运行包根目录。优先级：显式入参 > WT_NATIVE_PKG > 默认位置。"""
    raw = pkg or os.environ.get(ENV_PKG, "").strip() or DEFAULT_PKG
    p = Path(raw)
    if not p.is_dir():
        raise ProRuntimeError(
            f"找不到原生运行包：{p}\n"
            f"请设置 ${ENV_PKG}（解压后的 wt-missile-backend 目录），或放到 {DEFAULT_PKG}。\n"
            "包体不入库（见 AERO_PLAN §10.7）。"
        )
    core = p / "tools" / "simulator" / "core.py"
    if not core.exists():
        raise ProRuntimeError(f"{p} 不是有效的包根（找不到 tools/simulator/core.py）")
    return p


def verify_elf(pkg: Path, version: str = VERSION_28) -> dict:
    """校验 ELF 存在且 SHA-256 与版本匹配。返回身份块（供 provenance 用）。"""
    want = {VERSION_28: ELF_SHA256_28}.get(version)
    if want is None:
        raise ProRuntimeError(f"没有登记的 ELF 身份：version={version}")
    elf = Path(pkg) / ELF_REL
    if not elf.exists():
        raise ProRuntimeError(
            f"缺少 ELF：{elf}\n（包不完整，或包根指错了：{pkg}）"
        )
    h = hashlib.sha256()
    with open(elf, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != want:
        raise ProRuntimeError(f"ELF SHA-256 不符：期望 {want}，实际 {got}（{elf}）")
    return {"version": version, "elf_sha256": got, "elf_bytes": elf.stat().st_size}


def check_unicorn():
    """原生执行依赖 unicorn；缺失时给出可执行的修复命令。"""
    try:
        import unicorn  # noqa: F401
    except ImportError as exc:                          # pragma: no cover
        raise ProRuntimeError(
            "缺少 unicorn（原生机器码模拟器）。安装：pip install --user unicorn pyelftools"
        ) from exc


def runtime(pkg=None, version: str = VERSION_28, *, deep: bool = False) -> dict:
    """一次性把运行时信息收齐（路径 / ELF 身份 / 依赖）。`deep=True` 才做 ELF 全量哈希。"""
    p = resolve_pkg(pkg)
    check_unicorn()
    ident = verify_elf(p, version) if deep else {"version": version, "elf_sha256": ELF_SHA256_28}
    return {"pkg": str(p), **ident}


# --------------------------------------------------------------------- 单工况


@dataclass(frozen=True)
class NativeCase:
    """原生单工况输入（SI，全部外部可见）。"""

    missile: str                       # 原生 profile 名，如 cn_pl12
    version: str = VERSION_28
    range_m: float = 50000.0
    alt_m: float = 10000.0
    target_alt_m: float | None = None  # None ⇒ 同高
    vm0: float = 300.0
    vt: float = -300.0
    thrust_scale: float = 1.0
    cx_scale: float = 1.0
    dt: float = DT_DEFAULT
    duration_s: float = 200.0
    sample_period_s: float = 0.05
    observation_mode: str = "ideal"    # ideal = 与 Flash 同假设；locked = 带滤波/多径
    hit_radius_m: float = 0.0          # 0 ⇒ 只用原生近炸判定
    proximity_fuse: bool = True
    wind_m_s: tuple = (0.0, 0.0, 0.0)
    ground_height_m: float = 0.0
    target_maneuvers: tuple = ()       # ((time_s, (ax,ay,az)), ...)

    @property
    def target_alt(self) -> float:
        return self.alt_m if self.target_alt_m is None else self.target_alt_m

    def key(self) -> str:
        """缓存键（不含与物理无关的采样设置）。"""
        blob = json.dumps([
            self.version, self.missile,
            round(self.thrust_scale, 9), round(self.cx_scale, 9),
            self.range_m, self.alt_m, self.target_alt, self.vm0, self.vt,
            self.dt, self.observation_mode, self.hit_radius_m, self.proximity_fuse,
            list(self.wind_m_s), self.ground_height_m, [list(m) for m in self.target_maneuvers],
        ], sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


@dataclass
class NativeResult:
    """原生单工况结果（已归一成与 Flash 可比的口径）。"""

    ok: bool
    event: str = ""
    t_end: float = math.nan
    t_hit: float = math.nan
    hit: bool = False
    miss_distance_m: float = math.nan
    max_alt_m: float = math.nan
    v_impact: float = math.nan
    dv_measured: float = math.nan     # 燃尽时刻速度 − 初速（原生侧的"实际速度增量"）
    m_launch: float = math.nan
    m_dry: float = math.nan
    t_burnout: float = math.nan
    resource: str = ""                # "native" 或 "INJECTED il_derby.blkx"（注入须可追溯）
    error: str = ""
    cache_hit: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "NativeResult":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def to_dict(self) -> dict:
        return asdict(self)


def _import_native(pkg: Path):
    """在**当前进程**里把原生包挂上 sys.path 并 import。子进程专用。"""
    for p in (str(pkg / "tools"), str(pkg)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import simulator.core as core                      # noqa: PLC0415
    import simulator.resources as resources            # noqa: PLC0415
    return core, resources


# --- blk 注入：包内只有 9 型，缺的（Derby / R-Darter）用我们自己的 blkx 补 ---------
#
# 依据（见 results/native_injection_probe.json，已实证）：
#   * 原生参数全经内存块注入 ELF（CFG/GCFG/CTL/PROP/ENGINE），ELF 是 (状态, 参数块) 的纯函数；
#   * 唯一闸门是 `resources.load_profile` 的 manifest/SHA-256 校验，`scenario.validate` 不校验型号；
#   * 我们的 blkx 与原生 parse_blk 的叶子路径集合**完全相同（423/423）**，
#     共有 9 型在两者之间**逐值 0 差异** ⇒ Derby / R-Darter 的文件对 .28 ELF 结构完整。
# 注入**不改包内文件、不动 manifest**，且结果里必须记 `resource="INJECTED ..."`。

_EXTERNAL_PROFILES: dict = {}


def _external_profile(native_name: str) -> dict | None:
    """用本仓库的权威 blkx（`E:\\WT\\War-Thunder-Datamine`）解析出原生 profile dict。"""
    if native_name in _EXTERNAL_PROFILES:
        return _EXTERNAL_PROFILES[native_name]
    try:
        import sys as _sys
        scripts = str(ROOT / "scripts")
        if scripts not in _sys.path:
            _sys.path.insert(0, scripts)
        import missile_metrics as mm                    # noqa: PLC0415
        fname = None
        for short, fn, _label in mm.MISSILE_FILES:
            if fn.replace(".blkx", "") == native_name:
                fname = fn
                break
        if fname is None:
            return None
        rk = mm.load_rocket(mm.WORK, fname)
        if not rk:
            return None
        _EXTERNAL_PROFILES[native_name] = rk
        return rk
    except Exception:                                   # noqa: BLE001
        return None


def _patch_profile(p, updates: dict):
    """按 key 名就地改写 profile（原生 profile 是嵌套 dict；取第一个标量命中处）。"""
    if not updates:
        return p

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in updates and not isinstance(v, dict):
                    node[k] = updates[k]
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(p)
    return p


def _build_scenario(case: NativeCase, resources) -> dict:
    raw = {
        "schema_version": 1, "label": f"pro/{case.missile}",
        "missile": case.missile, "version": case.version,
        "duration_s": float(case.duration_s), "dt_s": float(case.dt),
        "sample_period_s": float(max(case.sample_period_s, case.dt)),
        "observation": {"mode": case.observation_mode},
        "launch": {"position_m": [0.0, case.alt_m, 0.0],
                   "velocity_m_s": [case.vm0, 0.0, 0.0]},
        "target": {"position_m": [case.range_m, case.target_alt, 0.0],
                   "velocity_m_s": [case.vt, 0.0, 0.0],
                   "collision_radius_m": 0.0},
        "wind_m_s": list(case.wind_m_s),
        "ground_height_m": float(case.ground_height_m),
        "proximity_fuse": bool(case.proximity_fuse),
    }
    if case.target_maneuvers:
        raw["target"]["maneuvers"] = [
            {"time_s": float(t), "acceleration_m_s2": [float(x) for x in a]}
            for t, a in case.target_maneuvers
        ]
    return raw


def simulate_native(case: NativeCase, pkg=None) -> NativeResult:
    """跑一次原生全程积分。**必须在能 import 原生包的进程里调用**（见 `ProRunner`）。"""
    p = resolve_pkg(pkg)
    if not (DT_RANGE[0] - 1e-12 <= case.dt <= DT_RANGE[1] + 1e-12):
        return NativeResult(ok=False, error=f"dt={case.dt} 超出原生合法范围 {DT_RANGE}")
    core, resources = _import_native(p)
    if case.version != resources.VERSION:
        return NativeResult(ok=False, error=f"包版本 {resources.VERSION} ≠ 请求 {case.version}")
    raw = _build_scenario(case, resources)
    orig = core.load_profile
    injected = {"name": None}

    def _apply(prof: dict) -> dict:
        """把 (推力乘数, CxK 乘数) 施加到 profile 上。"""
        upd = {}
        if case.thrust_scale != 1.0:
            for k in ("force", "force1"):
                v = prof.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    upd[k] = v * case.thrust_scale
        if case.cx_scale != 1.0 and isinstance(prof.get("CxK"), (int, float)):
            upd["CxK"] = prof["CxK"] * case.cx_scale
        return _patch_profile(prof, upd)

    def complete(name, version=resources.VERSION):
        """包内没有该型时，回落到我们的权威 blkx（注入）；有则照常。"""
        try:
            prof, ident = orig(name, version)
            return _apply(prof), ident
        except Exception:                               # noqa: BLE001  包内不支持该型
            ext = _external_profile(name)
            if ext is None:
                raise
            injected["name"] = name
            return (_apply(copy.deepcopy(ext)),
                    {"missile": name, "version": version,
                     "resource": f"INJECTED {name}.blkx"})

    core.load_profile = complete
    try:
        _scen, summary, samples = core.simulate(raw)
    except Exception as exc:                            # noqa: BLE001
        return NativeResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        core.load_profile = orig

    thrusts = [s["thrust_N"] for s in samples]
    speeds = [s["speed_m_s"] for s in samples]
    masses = [s["mass_kg"] for s in samples]
    powered = [i for i, t in enumerate(thrusts) if t and t > 0.0]
    i_burn = powered[-1] if powered else 0
    event = str(summary.get("terminal_event", ""))
    hit = event in HIT_EVENTS
    min_sep = float(summary.get("minimum_separation_until_event_m", math.nan))
    if hit and case.hit_radius_m > 0.0 and min_sep > case.hit_radius_m:
        hit = False                                     # 近炸半径外不算命中
    t_end = float(summary.get("time_s", math.nan))
    return NativeResult(
        ok=True, event=event, t_end=t_end, t_hit=(t_end if hit else math.nan), hit=hit,
        miss_distance_m=min_sep,
        max_alt_m=max(s["missile_y_m"] for s in samples) if samples else math.nan,
        v_impact=float(summary.get("final_speed_m_s", math.nan)),
        dv_measured=float(speeds[i_burn] - speeds[0]),
        m_launch=float(masses[0]), m_dry=float(min(masses)),
        t_burnout=float(samples[i_burn]["time_s"]),
        resource=(f"INJECTED {injected['name']}.blkx" if injected["name"] else "native"),
    )


# --------------------------------------------------------------------- 缓存


class ProCache:
    """原生结果的磁盘缓存：`results/pro_cache.json`。

    一次穷举是小时级，之后所有迭代都应该读缓存（这是"只做一次"的前提）。
    键 = `NativeCase.key()`（含版本/弹型/推力乘数/CxK 乘数/场景/dt/观测模式）。
    """

    def __init__(self, path=None, *, enabled: bool = True):
        self.path = Path(path) if path else DEFAULT_CACHE
        self.enabled = bool(enabled)
        self.data: dict = {}
        self.dirty = False
        if self.enabled and self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = dict(doc.get("entries") or {})
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def get(self, key: str) -> NativeResult | None:
        if not self.enabled:
            return None
        d = self.data.get(key)
        if not d:
            return None
        r = NativeResult.from_dict(d)
        r.cache_hit = True
        return r

    def put(self, key: str, result: NativeResult):
        if not self.enabled:
            return
        self.data[key] = result.to_dict()
        self.dirty = True

    def save(self, *, runtime_info: dict | None = None) -> Path | None:
        if not self.enabled or not self.dirty:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema": 1,
            "note": "Pro 后端原生结果缓存（键 = NativeCase.key()）；可安全删除，重跑会重建",
            "runtime": runtime_info or {},
            "n_entries": len(self.data),
            "entries": self.data,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False
        return self.path


# --------------------------------------------------------------------- 子进程与运行器


def _worker_init(pkg_str: str):
    """子进程初始化：切到包根（原生 resources 用**相对** ROOT 找 inputs/），并挂 sys.path。"""
    import os as _os
    _os.chdir(pkg_str)
    for p in (str(Path(pkg_str) / "tools"), pkg_str):
        if p not in sys.path:
            sys.path.insert(0, p)


def _worker_run(payload) -> dict:
    case_dict, pkg_str = payload
    fields = NativeCase.__dataclass_fields__
    case = NativeCase(**{k: v for k, v in case_dict.items() if k in fields})
    if isinstance(case.wind_m_s, list):
        object.__setattr__(case, "wind_m_s", tuple(case.wind_m_s))
    if isinstance(case.target_maneuvers, list):
        object.__setattr__(case, "target_maneuvers",
                           tuple((m[0], tuple(m[1])) for m in case.target_maneuvers))
    return simulate_native(case, pkg_str).to_dict()


class ProRunner:
    """原生运行器：进程池 + 缓存。

    单进程只能串行（`simulate_native` 不可重入——它改 `core.load_profile`），
    所以并发靠**多进程**：每个子进程独立 import 原生包、独立 Unicorn 实例。
    """

    def __init__(self, *, pkg=None, version: str = VERSION_28, jobs: int = 8,
                 cache: ProCache | None = None, progress=None):
        self.pkg = resolve_pkg(pkg)
        self.version = version
        self.jobs = max(1, int(jobs))
        self.cache = cache if cache is not None else ProCache()
        self.progress = progress
        self._pool = None
        self.stats = {"native": 0, "cache": 0}

    # --- 池管理 -------------------------------------------------------

    def _ensure_pool(self):
        if self._pool is None and self.jobs > 1:
            from concurrent.futures import ProcessPoolExecutor
            self._pool = ProcessPoolExecutor(
                max_workers=self.jobs, initializer=_worker_init, initargs=(str(self.pkg),))
        return self._pool

    def close(self):
        """关闭池并**持久化缓存**。

        缓存保存必须放在 `finally` 里：原生跑一轮是小时级，任何中途异常（回调签名、
        键盘中断、原生失败）都不能把已经跑出来的结果丢掉。
        """
        try:
            if self._pool is not None:
                self._pool.shutdown(wait=True)
        finally:
            self._pool = None
            self.cache.save(runtime_info={"pkg": str(self.pkg), "version": self.version})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- 运行 ---------------------------------------------------------

    def run_one(self, case: NativeCase) -> NativeResult:
        key = case.key()
        hit = self.cache.get(key)
        if hit is not None:
            self.stats["cache"] += 1
            return hit
        if self.jobs > 1:
            ex = self._ensure_pool()
            res = NativeResult.from_dict(ex.submit(_worker_run, (asdict(case), str(self.pkg))).result())
        else:
            res = simulate_native(case, self.pkg)
        self.stats["native"] += 1
        if res.ok:
            self.cache.put(key, res)
        return res

    def run_many(self, cases) -> list[NativeResult]:
        """批量：先打缓存，再一次性并发跑缺的。返回顺序与入参一致。"""
        cases = list(cases)
        out: list[NativeResult | None] = [None] * len(cases)
        todo = []
        for i, c in enumerate(cases):
            key = c.key()
            got = self.cache.get(key)
            if got is not None:
                out[i] = got
                self.stats["cache"] += 1
            else:
                todo.append((i, c))
        if todo:
            if self.jobs > 1:
                ex = self._ensure_pool()
                futs = {ex.submit(_worker_run, (asdict(c), str(self.pkg))): i for i, c in todo}
                from concurrent.futures import as_completed
                done = 0
                for fut in as_completed(futs):
                    i = futs[fut]
                    res = NativeResult.from_dict(fut.result())
                    out[i] = res
                    self.stats["native"] += 1
                    if res.ok:
                        self.cache.put(cases[i].key(), res)
                    done += 1
                    if self.progress:
                        # 回调签名与 sim.simulate_batch 一致：(step, total, active)
                        self.progress(done, len(todo), 0)
            else:
                for n, (i, c) in enumerate(todo, 1):
                    res = simulate_native(c, self.pkg)
                    out[i] = res
                    self.stats["native"] += 1
                    if res.ok:
                        self.cache.put(c.key(), res)
                    if self.progress:
                        self.progress(n, len(todo), 0)
        return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]


# --------------------------------------------------------------------- ΔV → 推力乘数（解析）
#
# **口径（用户 2026-09-25 明确）**：扫描变量 ΔV 就是**真空等效增速**，不是实际增速。
# 所以推力乘数是**纯理论解析值**，不需要考虑阻力/重力损失、也不需要迭代标定：
#
#     s = ΔV / ΔV_blk        （各段 force 同乘 s；燃料质量与燃烧时间不变 ⇒ 只改等效比冲）
#
# 参考：PL-12 ΔV_blk = 932.57 m/s。原生侧实跑的"燃尽速度增量"在本工况约 795 m/s
# （扣掉阻力/重力损失后的实际值）——**那是另一回事**，不参与本映射，
# 只作为诊断量记录，用来回答"这个 ΔV 在该工况下实际能打出多少速度"。


def cx_scale_for_bc(bc_target: float, dry_mass: float, s_ref: float, cxk_blk: float) -> float:
    """目标 BC → CxK 乘数（精确解析，无迭代）。

    BC = m_dry / (CxK · S_ref)  ⇒  CxK_used = m_dry / (BC · S_ref)
    故 CxK 乘数 = CxK_used / CxK_blk。
    """
    if bc_target <= 0 or s_ref <= 0 or cxk_blk <= 0 or dry_mass <= 0:
        raise ValueError("BC 反解参数非法")
    return dry_mass / (bc_target * s_ref * cxk_blk)


def scale_for_dv(dv_target: float, dv_blk: float) -> float:
    """ΔV（真空等效增速）→ 推力乘数。`s = ΔV / ΔV_blk`，解析、无迭代。"""
    if dv_blk <= 0:
        raise ValueError("标准弹 ΔV_blk 非法")
    return dv_target / dv_blk


def vacuum_dv(stages, scale: float = 1.0) -> float:
    """齐奥尔科夫斯基真空 ΔV（任一段数），用于校核"原生是否按 s 线性给出 ΔV"。

    stages: [(m_start, m_end, force, time_fire), ...]（见 standard.EngineSpec.stages()）
    """
    total = 0.0
    for m_start, m_end, force, time_fire in stages:
        dm = float(m_start) - float(m_end)
        if dm <= 0 or time_fire <= 0 or force <= 0:
            continue
        ve = float(force) * float(scale) * float(time_fire) / dm
        total += ve * math.log(float(m_start) / float(m_end))
    return total


def native_case_from_config(cfg, *, missile: str | None = None, **over) -> NativeCase:
    """由 `MissileConfig` + 标准弹构造原生工况（唯一入口，避免各处各写一遍）。

    ΔV/BC → 原生参数的映射（解析）：
      thrust_scale = ΔV / ΔV_blk        （ΔV 是**真空等效增速**）
      cx_scale     = m_dry / (BC · S_ref · CxK_blk)
    """
    from .config import s_ref as _s_ref                     # 局部 import 避免环
    prof = getattr(cfg, "profile", None)
    missiles = NATIVE_PROFILES[VERSION_28]
    name = missile
    if name is None:
        f = str(getattr(prof, "file", "") or "")
        for suffix in (".blkx", ".blk"):
            if f.endswith(suffix):
                f = f[: -len(suffix)]
        name = f
    if name not in missiles:
        raise ValueError(
            f"原生包不支持 {name!r}；它只含 {'、'.join(missiles)}（Derby / R-Darter 无原生对照）")
    scen = cfg.scenario
    kw = dict(
        missile=name, version=VERSION_28,
        range_m=float(scen.range), alt_m=float(scen.alt),
        target_alt_m=(None if scen.target_alt is None else float(scen.target_alt)),
        vm0=float(scen.vm0), vt=float(scen.vt),
        dt=float(getattr(cfg, "pro_dt", DT_DEFAULT)),
        duration_s=float(getattr(cfg, "pro_duration_s", 150.0)),
        observation_mode=str(getattr(cfg, "pro_observation", "ideal")),
    )
    kw.update(over)
    return NativeCase(**kw)


def scales_for(case_dv: float, case_bc: float, prof, s_ref_m2: float) -> tuple:
    """(ΔV, BC) → (thrust_scale, cx_scale)。解析，无迭代。"""
    return (scale_for_dv(case_dv, prof.dv),
            cx_scale_for_bc(case_bc, prof.dry_mass, s_ref_m2, prof.cxk))


def scale_tag(case_dv: float, case_bc: float, prof, s_ref_m2: float) -> dict:
    """把"外部的 (ΔV, BC)"与"原生的 (推力乘数, CxK 乘数)"一起记进产物，便于复核。"""
    ts, cs = scales_for(case_dv, case_bc, prof, s_ref_m2)
    return {"dv_target": float(case_dv), "bc_target": float(case_bc),
            "dv_blk": float(prof.dv), "bc_blk": float(prof.bc),
            "thrust_scale": float(ts), "cx_scale": float(cs),
            "cxk_used": float(prof.cxk * cs)}


@dataclass
class CellSolution:
    """一个 (ΔV, BC) 格点的求解记录。

    `scale` 是解析给出的推力乘数；`dv_measured` 是原生实跑的燃尽速度增量（**诊断量**，
    与 `dv_target` 的差 = 该工况的阻力/重力损失，不影响映射本身）。
    """

    dv_target: float
    bc: float
    scale: float
    dv_measured: float
    ok: bool
    iters: int = 1
    result: NativeResult | None = None

    @property
    def error(self) -> float:
        return self.dv_measured - self.dv_target

    @property
    def loss_pct(self) -> float:
        """该工况的损失率 [%]（诊断；0% 表示无损失）。"""
        if not math.isfinite(self.dv_measured) or self.dv_target <= 0:
            return math.nan
        return (1.0 - self.dv_measured / self.dv_target) * 100.0


def _replace(case: NativeCase, **kw) -> NativeCase:
    return NativeCase(**{**asdict(case), **kw})


@dataclass
class GridOutcome:
    """整张 (ΔV, BC) 网格的原生结果 + 诊断。"""

    dv: tuple
    bc: tuple
    solutions: list          # 行优先，形状 (len(dv), len(bc))
    stats: dict = field(default_factory=dict)

    @property
    def shape(self):
        return (len(self.dv), len(self.bc))

    def matrix(self, attr: str):
        import numpy as _np
        vals = [getattr(s, attr) for s in self.solutions]
        return _np.array(vals, dtype=float).reshape(self.shape)


def run_grid(runner: ProRunner, base: NativeCase, dv_values, bc_values, *,
             dv_blk: float, dry_mass: float, s_ref: float, cxk_blk: float,
             progress=None) -> GridOutcome:
    """整张网格：**每个格点一次原生运行**（乘数解析给出，无迭代）。

    360 格点（15×24）；实测单次 ~9.6 s（含 4 s ELF 装载 ⇒ 并发下摊销），
    8 并发约 8 min；跑完落缓存，之后所有迭代读缓存。
    """
    dv_values = [float(x) for x in dv_values]
    bc_values = [float(x) for x in bc_values]
    cases, keys = [], []
    for i, dv_t in enumerate(dv_values):
        s = scale_for_dv(dv_t, dv_blk)
        for j, bc in enumerate(bc_values):
            cx = cx_scale_for_bc(bc, dry_mass, s_ref, cxk_blk)
            cases.append(_replace(base, thrust_scale=s, cx_scale=cx))
            keys.append((i, j, dv_t, bc, s))
    results = runner.run_many(cases)
    solutions: list = [None] * len(cases)
    for (i, j, dv_t, bc, s), res in zip(keys, results):
        solutions[i * len(bc_values) + j] = CellSolution(
            dv_target=dv_t, bc=bc, scale=s,
            dv_measured=res.dv_measured if res.ok else math.nan,
            ok=bool(res.ok), iters=1, result=res)
    ok = sum(1 for x in solutions if x.ok)
    return GridOutcome(dv=tuple(dv_values), bc=tuple(bc_values), solutions=solutions,
                       stats={"n_cells": len(solutions), "n_converged": ok,
                              "n_native": runner.stats["native"], "n_cache": runner.stats["cache"]})

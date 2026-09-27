# -*- coding: utf-8 -*-
"""后端无关的"跑一条弹道"统一入口（默认 standard / fast；旧 pro / flash 保留）。

**为什么要有它**：`workflow.py` 有 7 处需要"跑一条弹道"（逐弹评估、距离扫描、弹道剖面、
基准线……）。以前每处直接调 `sim.simulate_one`（Flash-only），一旦换后端，
这些调用点就会各自算出一套不一致的数字。这里把差异收进一个类：

    runner = TrajectoryRunner(mcfg, jobs=8)
    r = runner.run(dv=930.0, bc=3000.0)          # 档位由 mcfg.backend 决定
    r2 = runner.run(dv=930.0, bc=3000.0, range_m=30000.0)
    r3 = runner.run(dv=930.0, bc=3000.0, record_trace=True)   # 要弹道剖面时

(ΔV, BC) → 引擎参数的映射**只有一处**（`model.io.build_case`）：
  * 引擎路径（standard / fast / 第三方模型）：thrust_scale = ΔV/ΔV_blk、
    cx_scale = m_dry/(BC·S_ref·CxK_blk)，由 `build_case` 现算并随 `EngineInputs` 传下去；
  * 旧 Flash：ΔV 与 CxK（由 BC 反解）直接是 `sim.simulate_one` 的入参。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from missile_sim.config import apply_standard, cxk_for_bc, s_ref
from missile_sim.sim import Case, simulate_one


@dataclass
class SampleTrace:
    """`plot_trajectories` 认的**最小**轨迹形状（引擎档位给的是逐采样 dict）。

    `sim.Trace` 有 20 来个字段，其中大半是 Flash 制导回路的内量（`tgo`/`k_go`/`los`……），
    引擎档位不产出；这里只补弹道图真正读的五条曲线。

    `gamma` 由相邻采样的 `(x, h)` 对 **t** 求中心差分反算（`atan2(dh/dt, dx/dt)`）。
    采样是 1/48 s 的物理步，反算与真实航向角的差别在小数点后 4 位；第三个面板本来
    就是看趋势。要精确航向角得让采样层带上 `missile_v[xy]_m_s`，那是另一件事。
    """

    t: np.ndarray
    x: np.ndarray
    h: np.ndarray
    v: np.ndarray
    gamma: np.ndarray

    def __len__(self) -> int:
        return int(self.t.size)


def _sample_col(samples: list, key: str) -> np.ndarray:
    """逐采样取一列；缺列/非数 → NaN（让调用方一处判掉，不用满地 try）。"""
    out = np.full(len(samples), np.nan, dtype=float)
    for i, s in enumerate(samples):
        v = s.get(key)
        if v is None:
            continue
        try:
            out[i] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def trace_from_samples(samples, *, stride: int = 1) -> SampleTrace | None:
    """引擎档位的 `NativeResult.samples` → `SampleTrace`。

    `stride` 抽稀（与旧 Flash 的 `--stride` 同义，只为出图省事）：采样本来就是 1/48 s 的
    物理步，一条 60 s 弹道有近 3000 点，画图用不着全画。

    不足两点、或 `t`/`x`/`h` 有非有限值（求解器返回半截轨迹）时返回 `None`
    —— 让调用方跳过画图，而不是画出一张坐标轴全是 NaN 的空图。
    """
    rows = list(samples or [])
    step = max(1, int(stride or 1))
    if step > 1 and rows:
        picked = rows[::step]
        if picked[-1] is not rows[-1]:
            picked.append(rows[-1])          # 末点必须留着（看终速/终距）
        rows = picked
    if len(rows) < 2:
        return None
    t = _sample_col(rows, "t")
    x = _sample_col(rows, "x")
    h = _sample_col(rows, "y")
    v = _sample_col(rows, "v")
    if not (np.isfinite(t).all() and np.isfinite(x).all() and np.isfinite(h).all()):
        return None
    gamma = np.arctan2(np.gradient(h, t), np.gradient(x, t))
    return SampleTrace(t=t, x=x, h=h, v=v, gamma=gamma)


@dataclass
class FlightResult:
    """一条弹道的结果（两种后端同形）。"""

    ok: bool
    status: str
    hit: bool
    t_hit: float | None
    t_end: float
    v_impact: float
    max_alt: float
    min_range: float
    min_range_linear: float
    t_loft_end: float
    event: str = ""
    dv: float = 0.0
    bc: float = 0.0
    cxk: float = 0.0
    thrust_scale: float | None = None
    cx_scale: float | None = None
    profile_hash: str | None = None
    hit_radius_m: float = 0.0
    t_life_s: float = 0.0
    error: str = ""
    trace: Any = None                 # Flash: sim.Trace；Pro/两档: None
    samples: list = field(default_factory=list)   # 引擎档位: 逐采样记录
    status_label: str = ""            # 中文状态（与 decide.STATUS_LABELS 同口径）
    # Flash 制导回路的内量诊断；引擎档位**不产出**，所以是 None 而不是 0.0
    n_eff_at_min_range: float | None = None
    terminal_gamma_error_deg: float | None = None

    @property
    def display_trace(self) -> SampleTrace | None:
        """弹道图用的轨迹：Flash 有真 `trace`，引擎档位从 `samples` 现搭（全采样）。"""
        if self.trace is not None:
            return self.trace
        return trace_from_samples(self.samples)


def flash_flight(mcfg, *, dv: float, bc: float, trace: bool = False) -> FlightResult:
    """Flash 路径：把 `sim.simulate_one` 的结果归一成 `FlightResult`。"""
    cx = float(cxk_for_bc(bc, mcfg))
    r = simulate_one(mcfg, Case(dv_total=float(dv), cxk=cx), record_trace=trace,
                     stride=20 if trace else 20)
    return FlightResult(
        ok=True, status=r.status_name, hit=bool(r.hit),
        t_hit=(float(r.t_hit) if r.hit else None), t_end=float(r.t_end),
        v_impact=float(r.v_impact), max_alt=float(r.max_alt),
        min_range=float(r.min_range), min_range_linear=float(r.min_range_linear),
        t_loft_end=float(r.t_loft_end),
        dv=float(dv), bc=float(bc), cxk=cx,
        profile_hash=(mcfg.profile.profile_hash() if getattr(mcfg, "profile", None) else None),
        hit_radius_m=float(mcfg.sim.hit_radius), t_life_s=float(mcfg.sim.t_life),
        trace=r.trace, status_label=str(r.status_label),
        n_eff_at_min_range=float(r.n_eff_at_min_range),
        terminal_gamma_error_deg=float(r.terminal_gamma_error_at_min_range_deg),
    )


def engine_flight(runner, mcfg, *, dv: float, bc: float, range_m=None, target_alt_m=None,
                  missile: str | None = None, tag: str = "engine",
                  record_trace: bool = False) -> FlightResult:
    """**引擎路径**：一次全程积分（standard / fast / 第三方模型）。

    `mcfg` 必须是**已 apply 过标准弹**的配置。乘数由 `model.io.build_case` 现算（唯一算法），
    执行器（`EngineRunner`）负责进程池与缓存；结果与旧引擎路径逐字段同形。

    `record_trace=True` 会带上逐采样轨迹（`save_trajectory`）。**这会让该工况不走缓存**
    （执行器只在无轨迹时写缓存）：轨迹本来就占单条记录的 95%，缓存它没意义。
    `save_trajectory` 不进缓存键，所以"要过轨迹"与"没要过"共用同一条缓存记录。
    """
    from missile_sim.model import io as mio

    prof = mcfg.profile
    over = {}
    if range_m is not None:
        over["range_m"] = float(range_m)
    if target_alt_m is not None:
        over["target_alt_m"] = float(target_alt_m)
    case = mio.build_case(mcfg, missile=missile, dv=float(dv), bc=float(bc),
                          save_trajectory=bool(record_trace), **over)
    r = runner.run_one(case)
    if not r.ok:
        return FlightResult(
            ok=False, status=f"{tag}_failed", hit=False, t_hit=None, t_end=float("nan"),
            v_impact=float("nan"), max_alt=float("nan"), min_range=float("nan"),
            min_range_linear=float("nan"), t_loft_end=float("nan"),
            dv=float(dv), bc=float(bc), cxk=float("nan"),
            thrust_scale=float("nan"), cx_scale=float("nan"), error=r.error,
            status_label="执行失败",
            profile_hash=prof.profile_hash(),
            hit_radius_m=float(mcfg.sim.hit_radius), t_life_s=float(mcfg.sim.t_life))
    hit = bool(r.hit)
    return FlightResult(
        ok=True,
        status="hit" if hit else f"no_hit_{r.event or 'unknown'}",
        hit=hit, t_hit=(r.t_hit if hit else None), t_end=float(r.t_end),
        v_impact=float(r.v_impact), max_alt=float(r.max_alt_m),
        min_range=float(r.miss_distance_m), min_range_linear=float("nan"),
        t_loft_end=float("nan"), event=str(r.event),
        dv=float(dv), bc=float(bc), cxk=float(prof.cxk * r.cx_scale),
        thrust_scale=float(r.thrust_scale), cx_scale=float(r.cx_scale),
        status_label=("命中" if hit else f"未命中·{r.event or 'unknown'}"),
        profile_hash=prof.profile_hash(),
        hit_radius_m=float(mcfg.sim.hit_radius), t_life_s=float(mcfg.sim.t_life),
        samples=list(getattr(r, "samples", []) or []),
    )


def pro_flight(runner, mcfg, *, dv: float, bc: float, range_m=None, target_alt_m=None,
               missile: str | None = None, record_trace: bool = False) -> FlightResult:
    """旧 Pro 路径（保留名）：与 `engine_flight` 同一实现，只是失败状态名叫 `pro_failed`。"""
    return engine_flight(runner, mcfg, dv=dv, bc=bc, range_m=range_m,
                         target_alt_m=target_alt_m, missile=missile, tag="pro",
                         record_trace=record_trace)


class TrajectoryRunner:
    """统一入口：按 `mcfg.backend` 分派，并持有执行器的进程池/缓存（跨调用复用）。"""

    def __init__(self, mcfg, *, jobs: int | None = None, progress=None):
        self.cfg = mcfg
        self.backend = str(getattr(mcfg, "backend", "standard")).lower()
        self.jobs = jobs if jobs is not None else getattr(mcfg, "pro_jobs", None)
        self.progress = progress
        self._runner = None
        self.stats = {"standard": 0, "fast": 0, "pro": 0, "flash": 0}

    # --- 执行器（懒建，用完必须 close） --------------------------------

    def _runner_for(self):
        """按 `mcfg.backend` 从注册表建/复用执行器（进程池 + 缓存）。

        `standard` / `fast`（当前正式档位）与第三方模型走 `EngineRunner`；旧 `pro` 保留它
        自己的 `ProRunner`（需要包路径与 chdir）。**缓存只按档位名**落
        `results/cache/<档位>.json`，不受 `cfg.pro_cache` 影响 —— 否则会写进 Pro 那 1824 条
        的资产文件（44 min）。
        """
        if self._runner is None:
            from missile_sim.model import registry as reg
            from missile_sim.model.cache import backend_cache
            from missile_sim.model.env import build_env

            name = self.backend
            jobs = int(self.jobs if self.jobs is not None
                       else getattr(self.cfg, "pro_jobs", 8))
            spec = reg.spec_of(name)
            env = build_env(spec, self.cfg, jobs=jobs)
            if name == "pro":
                from missile_sim import pro as pro_mod
                cp = str(getattr(self.cfg, "pro_cache", "") or "")
                cache = pro_mod.ProCache(cp or None, enabled=bool(cp))
                self._runner = pro_mod.ProRunner(jobs=jobs, cache=cache, progress=self.progress)
            else:
                from missile_sim.model.runner import EngineRunner
                engine = reg.load_engine(name, env=env)
                cache = backend_cache(name, None, enabled=True)
                self._runner = EngineRunner(engine, env=env, cache=cache, jobs=jobs,
                                            progress=self.progress)
        return self._runner

    def with_config(self, mcfg) -> "TrajectoryRunner":
        """派生一个用**另一份已 apply 的配置**（如逐弹切换标准弹）的运行器，
        **共用同一个原生进程池与缓存**——否则 11 型会各自建 8 个进程。"""
        child = TrajectoryRunner(mcfg, jobs=self.jobs, progress=self.progress)
        child._runner = self._runner
        return child

    def close(self):
        if self._runner is not None:
            self._runner.close()
            self._runner = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- 主入口 -------------------------------------------------------

    def run(self, *, dv: float, bc: float, range_m=None, target_alt_m=None,
            missile: str | None = None, record_trace: bool = False,
            standard: str | None = None, standard_applied: bool = False) -> FlightResult:
        """跑一条弹道。

        `standard` 给出且未 `standard_applied` 时**会重新解析标准弹**；
        逐弹评估请改用 `with_config(已apply的cfg)`，避免重复 apply。
        """
        c = self._with_standard(standard) if (standard and not standard_applied) else self.cfg
        name = self.backend
        if name == "flash":
            # 旧 Flash（本仓库公式引擎）：保留可回退，但已不再注册，故不是默认路径
            self.stats["flash"] = self.stats.get("flash", 0) + 1
            if range_m is not None:
                c = copy.deepcopy(c)
                c.scenario.range = float(range_m)
            if target_alt_m is not None:
                c = copy.deepcopy(c)
                c.scenario.target_alt = float(target_alt_m)
            return flash_flight(c, dv=dv, bc=bc, trace=record_trace)
        # standard / fast / 第三方模型：与旧 Pro 同形的引擎路径
        self.stats[name] = self.stats.get(name, 0) + 1
        return engine_flight(self._runner_for(), c, dv=dv, bc=bc, range_m=range_m,
                             target_alt_m=target_alt_m, missile=missile, tag=name,
                             record_trace=record_trace)

    def _with_standard(self, standard: str):
        c = copy.deepcopy(self.cfg)
        c.standard.name = standard
        apply_standard(c)
        return c
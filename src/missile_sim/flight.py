# -*- coding: utf-8 -*-
"""后端无关的"跑一条弹道"统一入口（Pro 原生 / Flash 快模型）。

**为什么要有它**：`workflow.py` 有 7 处需要"跑一条弹道"（逐弹评估、距离扫描、弹道剖面、
基准线……）。以前每处直接调 `sim.simulate_one`（Flash-only），一旦 Pro 成为正式后端，
这些调用点就会各自算出一套不一致的数字。这里把差异收进一个类：

    runner = TrajectoryRunner(mcfg, jobs=8)
    r = runner.run(dv=930.0, bc=3000.0)          # 后端由 mcfg.backend 决定
    r2 = runner.run(dv=930.0, bc=3000.0, range_m=30000.0)
    r3 = runner.run(dv=930.0, bc=3000.0, record_trace=True)   # 要弹道剖面时

(ΔV, BC) → 后端参数的映射：
  * Flash：ΔV 与 CxK（由 BC 反解）直接是入参；
  * Pro  ：thrust_scale = ΔV/ΔV_blk、cx_scale = m_dry/(BC·S_ref·CxK_blk)（解析，见 pro.py）。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from missile_sim.config import apply_standard, cxk_for_bc, s_ref
from missile_sim.sim import Case, simulate_one


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
    trace: Any = None                 # Flash: sim.Trace；Pro: None
    samples: list = field(default_factory=list)   # Pro: 原生逐采样记录


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
        trace=r.trace,
    )


def pro_flight(runner, mcfg, *, dv: float, bc: float, range_m=None, target_alt_m=None,
               missile: str | None = None) -> FlightResult:
    """Pro 路径：一次原生全程积分（`mcfg` 必须是**已 apply 过标准弹**的配置）。"""
    from missile_sim import pro as pro_mod

    prof = mcfg.profile
    over = {}
    if range_m is not None:
        over["range_m"] = float(range_m)
    if target_alt_m is not None:
        over["target_alt_m"] = float(target_alt_m)
    case = pro_mod.build_case(mcfg, missile=missile, dv=float(dv), bc=float(bc), **over)
    r = runner.run_one(case)
    if not r.ok:
        return FlightResult(
            ok=False, status="pro_failed", hit=False, t_hit=None, t_end=float("nan"),
            v_impact=float("nan"), max_alt=float("nan"), min_range=float("nan"),
            min_range_linear=float("nan"), t_loft_end=float("nan"),
            dv=float(dv), bc=float(bc), cxk=float("nan"),
            thrust_scale=float("nan"), cx_scale=float("nan"), error=r.error,
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
        profile_hash=prof.profile_hash(),
        hit_radius_m=float(mcfg.sim.hit_radius), t_life_s=float(mcfg.sim.t_life),
    )


class TrajectoryRunner:
    """统一入口：按 `mcfg.backend` 分派，并持有 Pro 的进程池/缓存（跨调用复用）。"""

    def __init__(self, mcfg, *, jobs: int | None = None, progress=None):
        self.cfg = mcfg
        self.backend = str(getattr(mcfg, "backend", "pro")).lower()
        self.jobs = jobs if jobs is not None else getattr(mcfg, "pro_jobs", None)
        self.progress = progress
        self._runner = None
        self.stats = {"pro": 0, "flash": 0}

    # --- Pro 运行器（懒建，用完必须 close） ----------------------------

    def _pro(self):
        if self._runner is None:
            from missile_sim import pro as pro_mod
            cp = str(getattr(self.cfg, "pro_cache", "") or "")
            cache = pro_mod.ProCache(cp or None, enabled=bool(cp))
            self._runner = pro_mod.ProRunner(
                jobs=int(self.jobs if self.jobs is not None
                         else getattr(self.cfg, "pro_jobs", 8)),
                cache=cache, progress=self.progress)
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
        if self.backend == "pro":
            self.stats["pro"] += 1
            return pro_flight(self._pro(), c, dv=dv, bc=bc, range_m=range_m,
                              target_alt_m=target_alt_m, missile=missile)
        self.stats["flash"] += 1
        if range_m is not None:
            c = copy.deepcopy(c)
            c.scenario.range = float(range_m)
        if target_alt_m is not None:
            c = copy.deepcopy(c)
            c.scenario.target_alt = float(target_alt_m)
        return flash_flight(c, dv=dv, bc=bc, trace=record_trace)

    def _with_standard(self, standard: str):
        c = copy.deepcopy(self.cfg)
        c.standard.name = standard
        apply_standard(c)
        return c
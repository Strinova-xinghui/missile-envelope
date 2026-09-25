# -*- coding: utf-8 -*-
"""**扫描器的执行内核**：(ΔV, BC) 网格 → 逐格点原生运行 → `GridOutcome`。

每个格点 = 一次原生全程积分；乘数由模型层按该型 profile 现算（无迭代）。
360 格点（15×24）8 并发约 8~9 min；跑完落缓存，之后迭代读缓存。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .native import NativeCase, NativeResult
from .runner import ProRunner

@dataclass
class CellSolution:
    """一个 (ΔV, BC) 格点的求解记录。

    乘数由原生侧按该型 profile 现算（见 `NativeResult.thrust_scale/cx_scale`）；
    `dv_measured` 是原生实跑的燃尽速度增量（**诊断量**，与 `dv_target` 的差 =
    该工况的阻力/重力损失，不影响映射本身）。
    """

    dv_target: float
    bc: float
    scale: float
    dv_measured: float
    ok: bool
    iters: int = 1
    result: NativeResult | None = None

    @property
    def cx_scale(self) -> float:
        return self.result.cx_scale if self.result is not None else math.nan

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
             progress=None) -> GridOutcome:
    """整张网格：**每个格点一次原生运行**（乘数由原生侧按该型 profile 现算，无迭代）。

    360 格点（15×24）；实测单次 ~1.4 s（8 并发，含 ELF 装载摊销）⇒ 约 8~9 min；跑完落缓存。
    """
    dv_values = [float(x) for x in dv_values]
    bc_values = [float(x) for x in bc_values]
    cases, keys = [], []
    for i, dv_t in enumerate(dv_values):
        for j, bc in enumerate(bc_values):
            cases.append(_replace(base, dv_target=dv_t, bc_target=bc))
            keys.append((i, j, dv_t, bc))
    results = runner.run_many(cases)
    solutions: list = [None] * len(cases)
    for (i, j, dv_t, bc), res in zip(keys, results):
        solutions[i * len(bc_values) + j] = CellSolution(
            dv_target=dv_t, bc=bc, scale=(res.thrust_scale if res.ok else math.nan),
            dv_measured=res.dv_measured if res.ok else math.nan,
            ok=bool(res.ok), iters=1, result=res)
    ok = sum(1 for x in solutions if x.ok)
    return GridOutcome(dv=tuple(dv_values), bc=tuple(bc_values), solutions=solutions,
                       stats={"n_cells": len(solutions), "n_converged": ok,
                              "n_native": runner.stats["native"], "n_cache": runner.stats["cache"]})

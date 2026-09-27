# -*- coding: utf-8 -*-
"""导弹 (ΔV, BC) 包线图外壳 —— 以 `vendor/wt-missile/` 为唯一求解器内核。

分层（换任何一层都不动别的层）：

    spec.py      契约：Scene / Scaling / Shot / MissilePoint / AxisSpec（纯数据结构）
    solver.py    与 vendor 的唯一接触面（换求解器只改它）
    mapping.py   (ΔV, BC) ↔ (thrust_scale, cx_scale) 的唯一算法
    pool.py      11 弹池：短名 ↔ vendor 预设名，ΔV/BC 从 blk 现算
    engine.py    执行层：进程池 + 结果缓存
    grid.py      (ΔV, BC) 网格 → t_hit 矩阵 → 等时线
    figures.py   唯一出图处（自适应轴散点 + 等时线）
    record.py    产物落盘 / manifest / 出处
    workflow.py  端到端编排
    cli.py       命令行（`python -m missile_sim`）

规范文档见 `docs/SOLVER-API.md`。
"""

from __future__ import annotations

import importlib

from .spec import (DEFAULT_MISSILE, SOLVER_DT, VERSION_28, AxisSpec, IsoGrid,
                   MissilePoint, PlaneGrid, Provenance, Scaling, Scene, Shot)

_SUBMODULES = ("solver", "mapping", "pool", "engine", "grid",
               "figures", "record", "workflow", "cli")

__all__ = [
    "Scene", "Scaling", "Shot", "MissilePoint", "AxisSpec", "PlaneGrid",
    "IsoGrid", "Provenance", "SOLVER_DT", "VERSION_28", "DEFAULT_MISSILE",
    *_SUBMODULES,
]

__version__ = "2.0.0"


def __getattr__(name):
    """子模块按需导入 —— 让 `import missile_sim` 不必拉起 numpy / matplotlib。"""
    if name in _SUBMODULES:
        mod = importlib.import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_SUBMODULES))

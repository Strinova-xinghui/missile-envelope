# -*- coding: utf-8 -*-
"""网格与等时线：**(ΔV, BC) 网格 → t_hit 矩阵 → 等值线**。

约定（与出图、产物一致，改动要三处同步）：

    * 网格范围**等于坐标轴范围**（自适应轴给出），按步长对齐取整；
    * `t_hit` 矩阵形状 `(n_dv, n_bc)`，**行优先（ΔV 主序）**，未命中处为 `nan`；
    * matplotlib 的 `contour(X, Y, Z)` 要 `Z.shape == (len(Y), len(X))`，
      所以传入的是 `t_grid.T`（这一步错了图会转置，且不会报错）。
"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402

from .spec import PlaneGrid             # noqa: E402


def arange_inclusive(lo: float, hi: float, step: float) -> tuple:
    """闭区间等差序列（含端点补足），照 `scanner.arange_inclusive` 的口径。"""
    if step <= 0:
        raise ValueError("步长必须为正")
    n = int(math.floor((float(hi) - float(lo)) / float(step) + 1e-9)) + 1
    vals = [float(lo) + float(step) * i for i in range(max(n, 1))]
    if vals[-1] < float(hi) - 1e-9:
        vals.append(float(hi))
    return tuple(round(v, 10) for v in vals)


def make_grid(xlim, ylim, *, dv_step: float = 10.0, bc_step: float = 25.0) -> PlaneGrid:
    """轴范围 → 扫描网格。范围按步长**向内对齐**，保证等时线能铺满整幅轴。"""
    lo_dv, hi_dv = float(xlim[0]), float(xlim[1])
    lo_bc, hi_bc = float(ylim[0]), float(ylim[1])
    dv0 = math.ceil(lo_dv / dv_step - 1e-9) * dv_step
    bc0 = math.ceil(lo_bc / bc_step - 1e-9) * bc_step
    return PlaneGrid(dv=arange_inclusive(dv0, hi_dv, dv_step),
                     bc=arange_inclusive(bc0, hi_bc, bc_step),
                     dv_step=float(dv_step), bc_step=float(bc_step))


def t_hit_matrix(shots, grid: PlaneGrid) -> np.ndarray:
    """逐格点结果 → `t_hit` 矩阵。未命中与非有限值一律 `nan`（**不要用 0 代替**）。"""
    a = np.full(grid.shape, np.nan, dtype=float)
    n_bc = len(grid.bc)
    for k, shot in enumerate(shots):
        if shot is None or not shot.ok or not shot.hit:
            continue
        i, j = divmod(k, n_bc)
        v = float(shot.t_hit)
        if math.isfinite(v):
            a[i, j] = v
    return a


def n_hit_matrix(shots, grid: PlaneGrid) -> np.ndarray:
    """命中掩码（1 = 命中），用于命中率统计与"哪块没打中"的图。"""
    a = np.zeros(grid.shape, dtype=int)
    n_bc = len(grid.bc)
    for k, shot in enumerate(shots):
        if shot is None or not shot.ok or not shot.hit:
            continue
        i, j = divmod(k, n_bc)
        a[i, j] = 1
    return a


def iso_levels(t_grid, step: float) -> list:
    """等时线层级：只取落在数据范围内的整步长值（默认 1 s）。"""
    finite = np.asarray(t_grid, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return []
    lo, hi = float(finite.min()), float(finite.max())
    first = math.ceil((lo - 1e-9) / float(step)) * float(step)
    levels, x = [], first
    while x <= hi + 1e-9:
        levels.append(round(x, 6))
        x += float(step)
    return levels


def _contour_segments(dv, bc, t_grid, levels):
    """用一次性的 Agg figure 取等值线段（不显示、不落盘）。

    返回 `contour` 句柄的副本信息：`levels` + 每层的段列表 `[(dv, bc), …]`。
    """
    fig = plt.figure()
    try:
        ax = fig.add_subplot(111)
        cs = ax.contour(np.asarray(dv, dtype=float), np.asarray(bc, dtype=float),
                        np.asarray(t_grid, dtype=float).T, levels=list(levels))
        out = []
        for i, lv in enumerate(cs.levels):
            segs = [seg for seg in cs.allsegs[i] if seg is not None and len(seg) >= 2]
            out.append((float(lv), segs))
    finally:
        plt.close(fig)
    return out


def extract_isolines(t_grid, grid: PlaneGrid, *, step: float = 1.0) -> list:
    """提等时线：`[{"level": t, "points": [(dv, bc), …], "closed": bool}, …]`。

    `step` 默认 **1 s**（``--iso-step`` 的默认值）；层级为空时返回 `[]`（不抛错）。
    """
    levels = iso_levels(t_grid, step)
    if not levels:
        return []
    out = []
    for lv, segs in _contour_segments(grid.dv, grid.bc, t_grid, levels):
        pts = []
        for seg in segs:
            pts.extend((float(x), float(y)) for x, y in seg)
        if not pts:
            continue
        closed = False
        for seg in segs:
            if len(seg) >= 3:
                x0, y0 = seg[0]
                x1, y1 = seg[-1]
                if abs(x0 - x1) < 1e-9 and abs(y0 - y1) < 1e-9:
                    closed = True
                    break
        out.append({"level": lv, "points": pts, "closed": closed})
    return out


def monotonic_report(t_grid, grid: PlaneGrid, *, axis: int = 1,
                     expect: str = "decrease") -> dict:
    """等值线成立的前提自检。返回非单调的格点计数与最大违背量；不抛错。

    * 图1（ΔV×BC）：沿 `axis=1`（BC）**期望递减** —— BC 越大阻力越小、飞得越快。
    * 图2（β×γ）：β 在 `axis=0` 上期望**递减**，γ 在 `axis=1` 上期望**递增**
      （γ 就是转向损失），所以要分别调用两次。

    它只是"这张图可不可信"的旁证，不是判定 —— 所以永不抛错。
    """
    a = np.asarray(t_grid, dtype=float)
    if int(axis) == 0:
        a = a.T                                   # 统一成"沿最后一维扫"的写法
    bad, worst = 0, 0.0
    for i in range(a.shape[0] if a.ndim == 2 else 0):
        row = a[i]
        for j in range(1, row.shape[0]):
            if not (math.isfinite(row[j]) and math.isfinite(row[j - 1])):
                continue
            d = row[j] - row[j - 1]
            worse = (d > 0) if str(expect) == "decrease" else (d < 0)
            if worse:
                bad += 1
                worst = max(worst, abs(d))
    return {"n_columns": int(a.shape[0] if a.ndim == 2 else 0),
            "n_non_monotonic": bad, "max_increase_s": worst}

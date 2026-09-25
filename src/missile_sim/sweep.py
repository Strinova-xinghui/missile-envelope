"""参数扫描（ΔV × 弹道系数 BC）与等命中时间线提取。

流程：
  1. 生成网格：ΔV ∈ [dv_min, dv_max] 步长 dv_step；BC ∈ [bc_min, bc_max] 步长 bc_step；
  2. 由 BC 反解 CxK = m_bound / (BC * S_ref)，交给向量化批量仿真；
  3. 输出 cases_*.csv（逐工况，含状态码/命中时间/终端量）；
  4. 在 t_hit(ΔV, BC) 网格上做等值线提取 → isolines_*.csv（每条等时线的折线顶点）；
  5. 校验：任一 ΔV 列内 t_hit 必须随 BC 单调（这是"等命中时间线"成立的前提）。

未命中工况 t_hit = NaN，等值线自动断开，不会被插值掩盖。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .config import (
    MissileConfig,
    ballistic_coefficient,
    config_to_dict,
    cxk_for_bc,
    delta_v_equiv,
    isp_equiv,
    mass_ratio_for_dv,
    s_ref,
)
from .decide import STATUS_LABELS, STATUS_NAMES, ST_HIT
from .sim import BatchResult, simulate_batch

RESULT_DIR = Path(__file__).resolve().parents[2] / "results"


@dataclass
class SweepGrid:
    dv: np.ndarray  # (n_dv,)
    bc: np.ndarray  # (n_bc,)
    dv_step: float
    bc_step: float

    @property
    def shape(self):
        return (len(self.dv), len(self.bc))


def build_grid(cfg: MissileConfig, dv_step: float | None = None, bc_step: float | None = None) -> SweepGrid:
    s = cfg.sweep
    dvs = _arange_inclusive(s.dv_min, s.dv_max, s.dv_step if dv_step is None else dv_step)
    bcs = _arange_inclusive(s.bc_min, s.bc_max, s.bc_step if bc_step is None else bc_step)
    return SweepGrid(dv=dvs, bc=bcs, dv_step=s.dv_step if dv_step is None else dv_step,
                     bc_step=s.bc_step if bc_step is None else bc_step)


def _arange_inclusive(lo: float, hi: float, step: float) -> np.ndarray:
    if step <= 0.0:
        raise ValueError("步长必须为正")
    n = int(np.floor((hi - lo) / step + 1e-9)) + 1
    vals = lo + step * np.arange(n)
    if vals[-1] < hi - 1e-9:
        vals = np.append(vals, hi)
    return np.round(vals, 10)


def grid_cases(grid: SweepGrid, cfg: MissileConfig, theta_loft_deg: float | None = None):
    """构造批量仿真的 (dv, cxk) 二维网格（形状 = (n_dv, n_bc)）。"""
    dv2d, bc2d = np.meshgrid(grid.dv, grid.bc, indexing="ij")
    cxk2d = cxk_for_bc(bc2d, cfg)
    return dv2d, cxk2d, bc2d


def run_sweep(
    cfg: MissileConfig,
    grid: SweepGrid | None = None,
    *,
    theta_loft_deg: float | None = None,
    mass=None,
    progress=None,
) -> tuple[BatchResult, SweepGrid, np.ndarray]:
    """执行扫描，返回 (batch_result, grid, t_hit 二维网格)。"""
    grid = build_grid(cfg) if grid is None else grid
    dv2d, cxk2d, _ = grid_cases(grid, cfg, theta_loft_deg)
    res = simulate_batch(
        cfg,
        dv2d.ravel(),
        cxk2d.ravel(),
        theta_loft_deg=theta_loft_deg,
        target_alt=(cfg.scenario.target_alt if cfg.scenario.target_alt is not None else cfg.scenario.alt),
        mass=mass,
        progress=progress,
    )
    t_grid = res.t_hit.reshape(grid.shape)
    return res, grid, t_grid


# --------------------------------------------------------------------------- 校验


def monotonic_report(t_grid: np.ndarray, grid: SweepGrid):
    """检查每个 ΔV 列内 t_hit 随 BC 单调性；返回违规明细列表。

    物理预期：同一 ΔV 下 BC 越大（阻力越小）→ 越早命中/越能命中。容许浮点抖动。
    """
    tol = 1e-6
    issues = []
    for i in range(t_grid.shape[0]):
        col = t_grid[i, :]
        for j in range(t_grid.shape[1] - 1):
            a, b = col[j], col[j + 1]
            if np.isnan(a) and np.isnan(b):
                continue
            if np.isnan(a) and not np.isnan(b):
                issues.append((grid.dv[i], grid.bc[j], grid.bc[j + 1], "NaN→命中", a, b))
            elif not np.isnan(a) and not np.isnan(b) and b > a + tol:
                issues.append((grid.dv[i], grid.bc[j], grid.bc[j + 1], "Δt 增大", a, b))
    return issues


# --------------------------------------------------------------------------- 输出


def write_cases_csv(res: BatchResult, path: Path) -> Path:
    """逐工况 CSV：ΔV / BC / CxK / 等效比冲 / 命中时间 / 状态 / 终端量。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "dv_total", "bc", "cxk", "isp_equiv_s", "mass_ratio_nominal",
        "status", "status_name", "t_hit_s", "t_end_s", "miss_distance_m",
        "min_range_m", "min_range_linear_m", "max_alt_m", "v_impact_ms",
        "terminal_gamma_err_deg", "t_loft_end_s",
    ]
    status_name = np.array([STATUS_NAMES[int(s)] for s in res.status], dtype=object)
    data = {
        "dv_total": res.dv_total,
        "bc": res.bc,
        "cxk": res.cxk,
        "isp_equiv_s": res.isp_equiv,
        "mass_ratio_nominal": res.mass_ratio,
        "status": res.status,
        "status_name": status_name,
        "t_hit_s": res.t_hit,
        "t_end_s": res.t_end,
        "miss_distance_m": res.miss_distance,
        "min_range_m": res.min_range,
        "min_range_linear_m": res.min_range_linear,
        "max_alt_m": res.max_alt,
        "v_impact_ms": res.v_impact,
        "terminal_gamma_err_deg": res.terminal_gamma_error_deg,
        "t_loft_end_s": res.t_loft_end,
    }
    header = ",".join(cols)
    lines = [header]
    for k in range(len(res.dv_total)):
        row = []
        for c in cols:
            v = data[c][k]
            if isinstance(v, str):
                row.append(v)
            elif c in ("status",):
                row.append(str(int(v)))
            elif np.isnan(v):
                row.append("nan")
            else:
                row.append(f"{float(v):.6g}")
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _iso_levels(finite: np.ndarray, step: float, extra_levels=None):
    """给定有限值集合与步长，生成等值线层级（含端点兜底，避免常量场退化）。"""
    lo = float(np.floor(finite.min() / step) * step)
    hi = float(np.ceil(finite.max() / step) * step)
    levels = list(np.arange(max(step, lo), hi + step * 0.5, step))
    if extra_levels is not None:
        levels.extend(float(x) for x in np.atleast_1d(extra_levels))
    if not levels:
        levels = [float(finite.mean())]
    vmin, vmax = float(finite.min()), float(finite.max())
    return sorted(lv for lv in levels if vmin - 1e-9 <= lv <= vmax + 1e-9)


def extract_isolines(
    t_grid: np.ndarray,
    grid: SweepGrid,
    levels=None,
    step: float = 2.0,
) -> list[dict]:
    """在 t_hit(BC, ΔV) 网格上提取等命中时间线（marching squares，NaN 自动断开）。

    返回 [{level, points:[(bc, dv, t), ...], closed}, ...]
    """
    finite = t_grid[np.isfinite(t_grid)]
    if finite.size == 0:
        return []
    if levels is None:
        levels = _iso_levels(finite, step)
    vmin, vmax = float(finite.min()), float(finite.max())
    levels = np.asarray([lv for lv in np.atleast_1d(levels) if vmin - 1e-9 <= lv <= vmax + 1e-9])
    if levels.size == 0:
        return []

    # contour 需要 X 形状 (n_bc,)、Y 形状 (n_dv,)、Z 形状 (n_dv, n_bc)
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots()
    try:
        cs = ax.contour(grid.bc, grid.dv, t_grid, levels=levels)
        segs = cs.allsegs
    finally:
        plt.close(fig)

    out = []
    for lv, group in zip(levels, segs):
        for seg in group:
            if seg is None or len(seg) < 2:
                continue
            pts = [(float(p[0]), float(p[1]), float(lv)) for p in seg]
            closed = bool(np.allclose(seg[0], seg[-1]))
            out.append({"level": float(lv), "points": pts, "closed": closed})
    return out


def write_isolines_csv(lines: list[dict], path: Path, cfg: MissileConfig) -> Path:
    """等时线 CSV（含由 BC 反解的 CxK），便于外部复核。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["t_hit_level_s,bc,cxk,dv_total,segment_index"]
    for idx, seg in enumerate(lines):
        for bc, dv, lv in seg["points"]:
            rows.append(f"{lv:.6g},{bc:.6g},{cxk_for_bc(bc, cfg):.6g},{dv:.6g},{idx}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def summary_dict(
    cfg: MissileConfig,
    res: BatchResult,
    grid: SweepGrid,
    t_grid: np.ndarray,
    lines: list[dict],
    *,
    extra: dict | None = None,
) -> dict:
    hit = res.status == ST_HIT
    per_status = {STATUS_NAMES[int(c)]: int(np.sum(res.status == c)) for c in np.unique(res.status)}
    out = {
        "config": config_to_dict(cfg),
        "derived": {
            "s_ref_m2": s_ref(cfg),
            "cxk_baseline": cfg.drag.cxk,
            "bc_baseline": ballistic_coefficient(cfg.drag.cxk, cfg),
            "dv_baseline_rocket_eq": delta_v_equiv(cfg),
            "isp_equiv_baseline_s": isp_equiv(delta_v_equiv(cfg)),
        },
        "scenario": {
            "vm0": res.vm0,
            "vt": res.vt,
            "alt": res.alt,
            "target_alt": res.target_alt,
            "range": res.range0,
            "theta_loft_deg": res.theta_loft_deg,
        },
        "grid": {
            "n_dv": int(len(grid.dv)),
            "n_bc": int(len(grid.bc)),
            "n_cases": int(res.dv_total.size),
            "dv": [float(x) for x in grid.dv],
            "bc": [float(x) for x in grid.bc],
            "dv_step": grid.dv_step,
            "bc_step": grid.bc_step,
        },
        "results": {
            "n_hit": int(np.sum(hit)),
            "hit_rate": float(np.mean(hit)),
            "status_counts": per_status,
            "t_hit_min_s": _nanmin(res.t_hit),
            "t_hit_max_s": _nanmax(res.t_hit),
            "isolines": sorted({seg["level"] for seg in lines}),
            "n_isolines": len(lines),
        },
    }
    if extra:
        out.update(extra)
    return out


def _nanmin(a):
    a = a[np.isfinite(a)]
    return float(a.min()) if a.size else None


def _nanmax(a):
    a = a[np.isfinite(a)]
    return float(a.max()) if a.size else None


def write_summary(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

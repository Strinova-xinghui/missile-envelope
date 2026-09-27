# -*- coding: utf-8 -*-
"""产物层：逐格点表 / 等时线表 / 摘要 / manifest，以及**出处块**（谁算的、用什么算的）。

产物一律 UTF-8、`indent=2`；CSV 用 `csv.writer`（Windows 上 `\n` 会被 `newline=""` 留住，
与旧产物同款，不影响 diff 稳定性）。
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .spec import PlaneGrid, Provenance, Scene

CSV_CASES = ("dv_target", "bc_target", "thrust_scale", "cx_scale", "event", "hit",
             "t_hit_s", "t_end_s", "miss_distance_m", "max_alt_m", "v_impact_ms",
             "dv_measured_ms", "t_burnout_s", "backend", "error")


def _num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return "" if not math.isfinite(f) else f"{f:.6g}"


def write_cases_csv(shots, grid: PlaneGrid, path, *, scaling_for=None) -> Path:
    """逐格点结果。顺序与 `grid.cells`（ΔV 主序）一致；未命中行的 `t_hit_s` 留空。

    `scaling_for(dv, bc) -> Scaling` 由调用方给（本模块不重复乘数算法）；
    省略时两列乘数留空，其余列照写。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_CASES)
        for (dv, bc), shot in zip(grid.cells, shots):
            ts = cs = ""
            if scaling_for is not None:
                sc = scaling_for(dv, bc)
                ts, cs = _num(sc.thrust_scale), _num(sc.cx_scale)
            w.writerow([
                _num(dv), _num(bc), ts, cs,
                (shot.event if shot else ""), int(bool(shot and shot.hit)),
                _num(shot.t_hit if shot else None), _num(shot.t_end if shot else None),
                _num(shot.miss_m if shot else None), _num(shot.max_alt_m if shot else None),
                _num(shot.v_impact if shot else None),
                _num(shot.dv_measured if shot else None),
                _num(shot.t_burnout if shot else None),
                (shot.backend if shot else ""), (shot.error if shot else ""),
            ])
    return path


def write_isolines_csv(lines, path) -> Path:
    """等时线顶点：每级一条 `segment_index` 递增的折线。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("t_hit_level_s", "dv_target", "bc", "closed"))
        for item in lines or ():
            for dv, bc in item["points"]:
                w.writerow((_num(item["level"]), _num(dv), _num(bc), int(bool(item["closed"]))))
    return path


def write_json(path, data) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def provenance_lines(prov: Provenance) -> list:
    """图上脚注的三行：算的是什么 / ΔV·BC 的定义 / 谁算的。"""
    solver = dict(prov.solver or {})
    tier = prov.tier or "?"
    backend = prov.backend or "?"
    ver = solver.get("version") or "?"
    sha = str(solver.get("sha256") or "")[:8]
    lines = [
        f"等时线 = {solver.get('solver', 'wt-missile')} {ver} 在 ΔV×BC 网格上算出的命中时间；"
        f"档位 {tier}（{backend}）· 求解器 sha256 {sha}…",
        "ΔV 为真空等效增速（不考虑衰减）：thrust_scale = ΔV/ΔV_blk；"
        "BC = 干重/(CxK·SD)，SD = π(d/2)² 迎面面积。扫描只改推力与阻力系数，"
        f"基准弹 {prov.standard or '?'} 的其余量全部不动。",
    ]
    scene = dict(prov.scene or {})
    if scene:
        lines.append(
            f"环境：{scene.get('range_m', 0) / 1000:.0f} km · 高度 {scene.get('alt_m', 0):.0f} m"
            f" → {scene.get('target_alt', 0):.0f} m · {scene.get('vm0', 0):.0f} 对 "
            f"{scene.get('vt', 0):.0f} m/s · 观测 {scene.get('observation', '?')} · "
            f"步长 {scene.get('dt_s', 0):.6g} s")
    return lines


def make_manifest(*, scene: Scene, standard: str, tier: str, solver_identity: dict,
                  backend: str, points, axis, grid: PlaneGrid, iso_step: float,
                  n_hit: int, elapsed_s: float, tag: str) -> dict:
    """run 级清单：**只看它就能复现这张图**。"""
    return {
        "schema": 2,
        "tag": tag,
        "scene": scene.as_dict(),
        "standard": standard,
        "tier": tier,
        "backend": backend,
        "solver": dict(solver_identity or {}),
        "points": [p.as_dict() for p in (points or ())],
        "axis": axis.as_dict(),
        "grid": grid.as_dict(),
        "iso_step_s": float(iso_step),
        "n_hit": int(n_hit),
        "hit_rate": (float(n_hit) / grid.n_cases) if grid.n_cases else 0.0,
        "elapsed_s": round(float(elapsed_s), 3),
    }

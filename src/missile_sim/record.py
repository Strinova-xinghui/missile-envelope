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
        # 措辞复用 `Scene.describe()`：坐标口径（标量 + 航向 + 俯仰）只能有一个出处，
        # 脚注与图副标题必须是同一套说法，否则看图的人会以为两处在描述不同的工况。
        # ⚠ 旧实现这里读 `scene['vt']` —— `Scene` 早就没有这个键了（拆成了 target_speed_ms
        # + target_heading_deg），于是"对 xxx m/s"那一项**永远打 0**，而且不报错。
        try:
            text = Scene.from_dict(scene).describe()
        except Exception:                      # 旧产物 / 缺键 / 类型不对：脚注不该让出图失败
            text = "（场景字段无法解析）"
        # 不要再补 `observation` —— `Scene.describe()` 末尾已经带了它，补了会重复成 "ideal · 观测 ideal"。
        lines.append(f"环境：{text} · 步长 {float(scene.get('dt_s') or 0):.6g} s")
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


# --------------------------------------------------------------------- 图2 产物


def write_bg_points_csv(rows_, path) -> Path:
    """β–γ 图的散点表：固有量 + 参考工况下的派生指标，**逐型一行**。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("key", "label", "beta", "gamma", "dv", "q_sens", "n_star",
                    "ratio", "beta_eff"))
        for r in rows_ or ():
            w.writerow([r.key, r.label, _num(r.beta), _num(r.gamma), _num(r.dv),
                        _num(r.q_sens), _num(r.n_star), _num(r.ratio), _num(r.beta_eff)])
    return path


def write_bg_cases_csv(shots, grid: PlaneGrid, path, *, scaling_of=None) -> Path:
    """β–γ 扫描的逐格点表。**列名写 β/γ，不留 `dv/bc`** —— 这个网格上横轴是 γ 不是 BC，
    沿用旧列名会让人以为扫的是第一张图的量。

    尾部各列与 `write_cases_csv` 完全一致（同一套 `Shot` 字段）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("beta_target", "gamma_target", "thrust_scale", "cx_scale",
                    "cxaoa_scale") + CSV_CASES[4:])
        for (beta, gamma), shot in zip(grid.cells, shots):
            ts = cs = aoa = ""
            if scaling_of is not None:
                sc = scaling_of(beta, gamma)
                ts, cs, aoa = (_num(sc.thrust_scale), _num(sc.cx_scale),
                               _num(sc.cxaoa_scale))
            w.writerow([
                _num(beta), _num(gamma), ts, cs, aoa,
                (shot.event if shot else ""), int(bool(shot and shot.hit)),
                _num(shot.t_hit if shot else None), _num(shot.t_end if shot else None),
                _num(shot.miss_m if shot else None), _num(shot.max_alt_m if shot else None),
                _num(shot.v_impact if shot else None),
                _num(shot.dv_measured if shot else None),
                _num(shot.t_burnout if shot else None),
                (shot.backend if shot else ""), (shot.error if shot else ""),
            ])
    return path


def write_bg_isolines_csv(lines, path) -> Path:
    """β–γ 仿真等时线顶点（列名同样是 β/γ）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("t_hit_level_s", "beta", "gamma", "closed"))
        for item in lines or ():
            for beta, gamma in item["points"]:
                w.writerow((_num(item["level"]), _num(beta), _num(gamma),
                            int(bool(item["closed"]))))
    return path


def make_bg_manifest(*, scene: Scene, standard: str, standard_native: str, tier: str,
                     solver_identity: dict, backend: str, rows_, reference, n: float,
                     beta_step: float, gamma_step: float, iso_step: float, dv_pin: float,
                     grid, n_hit: int, elapsed_s: float, tag: str) -> dict:
    """图2 的 run 级清单。**列名写 β/γ**，并显式记下固定住的 ΔV 与参考工况 ——
    这两样是第二张图独有、且"不写就没法复现"的量。"""
    ref = reference
    return {
        "schema": 1,
        "figure": "beta-gamma",
        "tag": tag,
        "scene": scene.as_dict(),
        "standard": standard,
        "standard_native": standard_native,
        "tier": tier,
        "backend": backend,
        "solver": dict(solver_identity or {}),
        "points": [r.as_dict() for r in (rows_ or ())],
        "reference": {
            "alt_m": ref.alt_m, "speed_ms": ref.speed_ms, "mach": ref.mach,
            "q_pa": ref.q_pa, "f_mach": ref.f_mach, "cap_f": ref.cap_f,
            "cap_over_f": ref.cap_f / ref.f_mach,
        },
        "n_ref_g": float(n),
        "scan": None if grid is None else {
            "dv_pin_ms": float(dv_pin),
            "beta_step": float(beta_step),
            "gamma_step": float(gamma_step),
            "beta_cells": len(grid.dv),
            "gamma_cells": len(grid.bc),
            "n_cases": int(grid.n_cases),
            "n_hit": int(n_hit),
            "hit_rate": (float(n_hit) / grid.n_cases) if grid.n_cases else 0.0,
        },
        "iso_step_s": float(iso_step),
        "elapsed_s": round(float(elapsed_s), 3),
    }

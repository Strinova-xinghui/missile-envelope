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

#: 逐格点 CSV 的列。**三个"距离"列各是各的语义**（A5 修复，别再合成一个 `miss_distance_m`）：
#:
#: * `min_separation_m` —— 内核 `minimum_separation_until_event_m`：**终止事件之前**的最小弹目
#:   距离。⚠ **命中时它等于引信半径**（默认 10 m）—— 引信一进半径就触发，后面的弹道不走。
#: * `cpa_m` —— **真最近接近距离**。命中时要多跑一次关引信的虚警解算才拿得到；网格路径
#:   （`engine.Engine`，`want_cpa=False`）**不量**，所以这一列在扫描产物里通常是空的。
#:   未命中工况它就是 `min_separation_m`（不用复跑）。
#: * `fuse_radius_m` —— 内核自报的引信半径；0 = 没引信或本次关了引信。
#:
#: 旧列名 `miss_distance_m` 已删除：那个名字会把命中时的 10.0 m 说成"脱靶量"。
CSV_CASES = ("dv_target", "bc_target", "thrust_scale", "cx_scale", "event", "hit",
             "t_hit_s", "t_end_s", "min_separation_m", "cpa_m", "fuse_radius_m",
             "max_alt_m", "v_impact_ms",
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
                _num(shot.min_separation_m if shot else None),
                _num(shot.cpa_m if shot else None),
                _num(shot.fuse_radius_m if shot else None),
                _num(shot.max_alt_m if shot else None),
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
                _num(shot.min_separation_m if shot else None),
                _num(shot.cpa_m if shot else None),
                _num(shot.fuse_radius_m if shot else None),
                _num(shot.max_alt_m if shot else None),
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


# --------------------------------------------------------------------- 图3 产物


def write_traj_track_csv(rows, path, *, who: str = "missile") -> Path:
    """图3 的单条航迹表（弹、目标各出一张）。

    ⚠ 坐标系原义照抄精简行：**水平面是 `(x, z)`、`y` 是高度**（`heading 0 = +x`、
    `90 = +z`）。把这个约定写进列名（`x_m`/`z_m` 并排），免得有人以为 `y` 是水平面。
    目标那组只有位置（内核行里目标的速度没进精简行）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target = str(who) == "target"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if target:
            w.writerow(("t_s", "x_m", "y_m", "z_m"))
        else:
            w.writerow(("t_s", "x_m", "y_m", "z_m", "v_ms", "mass_kg",
                        "thrust_N", "range_m"))
        for r in rows or ():
            if target:
                w.writerow((_num(r.get("t")), _num(r.get("tx")), _num(r.get("ty")),
                            _num(r.get("tz"))))
            else:
                w.writerow((_num(r.get("t")), _num(r.get("x")), _num(r.get("y")),
                            _num(r.get("z")), _num(r.get("v")), _num(r.get("mass")),
                            _num(r.get("thrust")), _num(r.get("range"))))
    return path


def write_traj_segments_csv(segments, path) -> Path:
    """分段表：图上每一段颜色的**数值依据**（画出来的那条图不可能比它更准）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("t0_s", "t1_s", "kind", "label", "phase", "heading0_deg",
                    "heading1_deg", "color_key", "truncated"))
        for s in segments or ():
            w.writerow((_num(s.t0_s), _num(s.t1_s), s.kind, s.label, s.phase,
                        _num(s.heading0_deg), _num(s.heading1_deg), s.color_key,
                        int(bool(s.truncated))))
    return path


def make_traj_manifest(*, run, scene: Scene, tier: str, solver_identity: dict,
                       backend: str, request: dict, elapsed_s: float, tag: str) -> dict:
    """图3 的 run 级清单。

    与图1/图2 最大的差别：这里一次只跑**一枚**弹、**两遍**（先反求开机时刻、
    再加 39 腿正式跑），所以除了 `request`（全部输入）还要显式记下**两遍的结局**
    —— 第二遍的 `hit` 才是结论，第一遍只用来定锚点。
    """
    return {
        "schema": 1,
        "figure": "traj",
        "tag": tag,
        "scene": scene.as_dict(),
        "run": run.as_dict(),
        "solver": dict(solver_identity or {}),
        "tier": tier,
        "backend": backend,
        "request": dict(request or {}),
        "elapsed_s": round(float(elapsed_s), 3),
    }


# --------------------------------------------------------------------- 图4 产物

#: 图4 逐工况表的列（顺序即写出顺序）。
#: * 前四列是**坐标本身**（哪枚弹 + 三根轴上的位置），所以列名写 `*_target`，
#:   与图2 的 `beta_target` / `gamma_target` 同一套写法；
#: * 三个乘数是"这个格点落进求解器时到底改了什么"，出问题时先看它；
#: * `n_star_g` / `R_ref` / `induced_dominated` 是**判别量**（答案不是从 t_hit 反推的）：
#:   R = (n_ref/n*)^2 ≥ 1 ⇒ 诱导阻力项压过基础阻力项。它只随 (β, γ) 变，同一根竖线上 5 个
#:   ΔV 点同值 —— 别把它读成"这一炮打没打中"；
#: * 尾部各列与 `write_cases_csv` 完全一致（同一套 `Shot` 字段），`t_hit_s` 未命中留空。
FIG4_CASES = ("missile", "beta_target", "gamma_target", "dv_target",
              "thrust_scale", "cx_scale", "cxaoa_scale",
              "n_star_g", "R_ref", "induced_dominated") + CSV_CASES[4:]


def write_fig4_cases_csv(rows, path) -> Path:
    """图4 的逐工况表：**每工况一行**（11 弹 × 245 格点 = 2695 行）。

    行由 `fig4scan.case_rows()` 给（那里才知道 β/γ/ΔV 与 `Shot` 的对应），本函数只负责
    "列名 + 数字格式"这一层 —— 与 `write_bg_cases_csv` 的分工一致。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIG4_CASES)
        for r in rows or ():
            w.writerow([
                str(r.get("missile") or ""),
                _num(r.get("beta_target")), _num(r.get("gamma_target")), _num(r.get("dv_target")),
                _num(r.get("thrust_scale")), _num(r.get("cx_scale")), _num(r.get("cxaoa_scale")),
                _num(r.get("n_star_g")), _num(r.get("R_ref")),
                int(bool(r.get("induced_dominated"))),
                str(r.get("event") or ""), int(bool(r.get("hit"))),
                _num(r.get("t_hit_s")), _num(r.get("t_end_s")), _num(r.get("miss_distance_m")),
                _num(r.get("max_alt_m")), _num(r.get("v_impact_ms")),
                _num(r.get("dv_measured_ms")), _num(r.get("t_burnout_s")),
                str(r.get("backend") or ""), str(r.get("error") or ""),
            ])
    return path

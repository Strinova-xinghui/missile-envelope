# -*- coding: utf-8 -*-
"""图4 的**算核**：11 枚弹 × 同一套 (β,γ,ΔV) 网格 → 落盘产物（`results/fig4_<tag>.json` + `_cases.csv`）。

## 复用而不重造

* 网格 / 立方体 / 三轴 → `Scaling` 的映射：`bg3d.Bg3Grid` / `bg3d.scaling3_for`；
* 进程池 + 分档缓存：`engine.Engine`（**一个字没改**，缓存键仍然吃整块 `Scaling`）；
* β、γ 的域：`figures.bg_axis()`（= 图2 的自适应域），所以图4 的立方体**罩得住 11 弹**；
* 拟合 / 残差 / 曲率的**口径**：`fig4.fit_columns()` / `fig4.plane_fit()`（数据层与算核共用一套定义，
  否则"图上画的"与"文档写的"会各算一遍）；
* 产物层：`record.write_fig4_cases_csv()` + `record.write_json()`。

⚠ **本模块与 `bg3d.scan3()` 是两条独立代码路径**（这里是"弹在外层、ΔV 在内层"，`scan3` 是单弹），
`tests/test_fig4.py` 会在同一个 (β,γ,ΔV) 上把两条路径各算一次对拍 —— 轴序或乘数接错了，
两条路径必然对不上（这类错误在图上只表现为"颜色有点花"）。

## 三根轴的口径（与图1/图2 一致，别发明第四套）

    ΔV → thrust_scale = ΔV / ΔV_blk      （严格只动这一项）
    β  → cx_scale     = β_blk / β
    γ  → cx_scale·cxaoa_scale = γ / γ_blk（改 β 时 cxaoa_scale 按 1/cx_scale 联动，γ 被顶住）

11 枚弹各自用自己的 `(β_blk, γ_blk, ΔV_blk)` 做上面这条反解 —— 所以**同一个格点在不同弹上
是不同的乘数**，而轴上的坐标（物理量）是同一个：这正是"11 朵点云可横向比较"的前提。
"""

from __future__ import annotations

import math
import time

import numpy as np

from . import bg, bg3d, fig4, figures, pool, record, solver
from .engine import Engine
from .spec import RESULT_DIR, Scene

#: 默认（= 用户拍板）网格：β、γ 各 7 点取图2 的域，ΔV 5 点取 `dv_factors × dv_pin`。
DEFAULT_N_BETA = fig4.N_BETA
DEFAULT_N_GAMMA = fig4.N_GAMMA
DEFAULT_DV_FACTORS = fig4.DV_FACTORS


def default_grid(rows_, *, dv_pin: float, n_beta: int = DEFAULT_N_BETA,
                 n_gamma: int = DEFAULT_N_GAMMA, dv_factors=DEFAULT_DV_FACTORS,
                 beta_step: float | None = None, gamma_step: float | None = None) -> bg3d.Bg3Grid:
    """默认三维网格：**β、γ 覆盖图2 的域（含端点），ΔV = 倍数 × dv_pin（含 dv_pin 本身）**。

    ⚠ 为什么这里**不**用 `bg3d.make_grid3()` 的"向内对齐到整步长"：7 个点落不到整步长上，
    向内对齐会把 β 的下限抬到 2600，把 R-77（2568.8）与 Derby（2567.0）挤出立方体 ——
    "图上没有它"会被读成"它不行"（`docs/FIG-BG3D-FEASIBILITY.md` §3 记过这个坑）。
    所以这里**显式等分**（端点 = 图2 的域端点），`*_step` 只是"相邻点间距"，用于记录与显示。

    给了 `beta_step` / `gamma_step` 时改用"向内对齐"的等步长网格（试轴用，同 `bg3d.make_grid3`）。
    """
    if float(dv_pin) <= 0:
        raise ValueError(f"ΔV 钉值必须为正，收到 {dv_pin!r}")
    if int(n_beta) < 2 or int(n_gamma) < 2:
        raise ValueError("β、γ 至少各要 2 个点")
    if len(tuple(dv_factors)) < 2:
        raise ValueError("ΔV 至少要有 2 个点")
    axis = figures.bg_axis(rows_)                        # 图2 的域（含它自己的 pad 规则）
    beta = _lin(axis.xlim[0], axis.xlim[1], int(n_beta))
    gamma = _lin(axis.ylim[0], axis.ylim[1], int(n_gamma))
    dv = tuple(round(float(dv_pin) * float(f), 4) for f in dv_factors)
    if beta_step or gamma_step:
        lim = bg3d.box_limits(rows_, dv_lim=(dv[0], dv[-1]))
        return bg3d.make_grid3(lim["beta"], lim["gamma"], lim["dv"],
                               beta_step=float(beta_step or 100.0),
                               gamma_step=float(gamma_step or 4.0),
                               dv_step=float(dv[1] - dv[0]))
    return bg3d.Bg3Grid(beta=beta, gamma=gamma, dv=dv,
                        beta_step=_step(beta), gamma_step=_step(gamma),
                        dv_step=_step(dv))


def _lin(lo, hi, n: int) -> tuple:
    return tuple(round(float(lo) + (float(hi) - float(lo)) * i / (n - 1), 4) for i in range(n))


def _step(vals) -> float:
    vals = [float(v) for v in vals]
    return (vals[-1] - vals[0]) / (len(vals) - 1) if len(vals) > 1 else 0.0


# --------------------------------------------------------------------- 扫描


def _column_stats(entry_key: str, metrics, point, grid, *, n_ref: float,
                  ref_alt_m, ref_speed_ms) -> dict:
    """逐 (β,γ) 列的**判别量**：`n*`（临界过载）与 `R = (n_ref/n*)²`。

    `n* = q/(Q·g0)`、`Q = sqrt(β·γ·F/f)` —— 口径与图2 的等 `n*` 线**同一套**（`bg.evaluate`）。
    参考工况（默认 10 km / 800 m/s）与图2 一致，所以两张图的 `n*` 可以直接对着看。
    R ≥ 1 = "诱导阻力项压过基础阻力项" = 用户说的"诱导阻力主导的场合"。
    """
    del metrics, point, entry_key                      # 只为了让签名说清"这里不需要弹的标称值"
    rows = []
    for beta, gamma in grid.plane_cells():
        ref = bg.evaluate(beta, gamma, alt_m=ref_alt_m, speed_ms=ref_speed_ms, n=n_ref)
        rows.append({"beta": beta, "gamma": gamma, "n_star_g": ref.n_star,
                     "R_ref": ref.ratio, "q_sens": ref.q_sens,
                     "induced": bool(ref.ratio >= 1.0)})
    return {"n_star_g": [r["n_star_g"] for r in rows],
            "R_ref": [r["R_ref"] for r in rows],
            "q_sens": [r["q_sens"] for r in rows],
            "induced": [1 if r["induced"] else 0 for r in rows]}


def scan_missile(scene: Scene, entry, grid: bg3d.Bg3Grid, *, tier: str = "fast", jobs: int = 8,
                 cache: bool = True, progress=None, log=None) -> dict:
    """**一枚弹**的立方体扫描（`Engine` 外层循环 ΔV，与 `bg3d.scan3` 同款）。"""
    say = log or (lambda _m: None)
    point = bg.point_of(entry)
    metrics = pool.metrics_of(entry)
    shape = grid.shape
    t_hit = np.full(shape, np.nan, dtype=float)
    hit = np.zeros(shape, dtype=bool)
    dv_measured = np.full(shape, np.nan, dtype=float)
    shots_all: list = []
    n_ok = n_hit = n_run = n_cached = 0
    backend = "not-run"
    plane_cells = grid.plane_cells()
    n_beta = len(grid.beta)
    holder = {"dv": float(grid.dv[0])}
    t0 = time.perf_counter()
    eng = Engine(scene, missile=entry.native, tier=tier, jobs=jobs, cache=cache, metrics=metrics,
                 scaling_of=lambda b, g: bg3d.scaling3_for(point, metrics, beta=b, gamma=g,
                                                           dv=holder["dv"]))
    try:
        for i, dv in enumerate(grid.dv):
            holder["dv"] = float(dv)
            shots = eng.many(plane_cells)
            shots_all.extend(shots)
            layer_hit = 0
            for k, shot in enumerate(shots):
                j, m = divmod(k, n_beta)                    # γ 外层、β 内层
                if shot is None:
                    continue
                backend = shot.backend or backend
                if getattr(shot, "cache_hit", False):
                    n_cached += 1
                else:
                    n_run += 1
                if shot.ok:
                    n_ok += 1
                    dv_measured[i, j, m] = float(shot.dv_measured)
                    if shot.hit and math.isfinite(float(shot.t_hit)):
                        t_hit[i, j, m] = float(shot.t_hit)
                        hit[i, j, m] = True
                        n_hit += 1
                        layer_hit += 1
            say(f"  {entry.key} ΔV={dv:.1f} m/s：命中 {layer_hit}/{len(plane_cells)}"
                f"（累计 {n_hit}/{grid.n_cases}）")
    finally:
        stats = dict(eng.stats)
        eng.close()
    elapsed = time.perf_counter() - t0
    return {"entry": entry, "point": point, "metrics": metrics, "t_hit": t_hit, "hit": hit,
            "dv_measured": dv_measured, "shots": shots_all, "backend": backend,
            "elapsed_s": elapsed, "stats": stats, "n_ok": n_ok, "n_hit": n_hit,
            "n_run": n_run, "n_cached": n_cached}


def scan_all(scene: Scene, *, entries, grid: bg3d.Bg3Grid, tier: str = "fast", jobs: int = 8,
             cache: bool = True, n_ref: float = 20.0, ref_alt_m=None, ref_speed_ms=None,
             progress=None, log=None) -> dict:
    """11 枚弹（`entries` 的顺序即产物顺序）在同一套网格上扫一遍。"""
    say = log or (lambda _m: None)
    t0 = time.perf_counter()
    out = []
    for n, entry in enumerate(entries, start=1):
        say(f"[{n}/{len(entries)}] {entry.key}（{entry.native}）")
        res = scan_missile(scene, entry, grid, tier=tier, jobs=jobs, cache=cache,
                           progress=progress, log=say)
        res["columns"] = _column_stats(entry.key, res["metrics"], res["point"], grid,
                                       n_ref=n_ref, ref_alt_m=ref_alt_m,
                                       ref_speed_ms=ref_speed_ms)
        res["fit"] = fig4.fit_columns(res["t_hit"], grid.dv)
        res["plane"] = fig4.plane_fit(res["t_hit"], grid.beta, grid.gamma, grid.dv)
        out.append(res)
    return {"grid": grid, "scene": scene, "tier": tier, "missiles": out,
            "elapsed_s": time.perf_counter() - t0,
            "n_ref": float(n_ref), "ref_alt_m": ref_alt_m, "ref_speed_ms": ref_speed_ms}


# --------------------------------------------------------------------- 产物


def case_rows(scan: dict) -> list:
    """逐工况一行（顺序 = `fig4.flat_cells()`，ΔV 最外层、γ、β）。

    ⚠ `induced_dominated` 只看 `(β, γ)` 那一列（同一根竖线上 5 个 ΔV 点同值）——
    它不是"这一炮打没打中"的标签，是"这个格点落在诱导阻力主导区没有"的标签。
    """
    grid = scan["grid"]
    n_beta, n_gamma = len(grid.beta), len(grid.gamma)
    span = n_gamma * n_beta
    rows = []
    for m in scan["missiles"]:
        point, metrics, entry = m["point"], m["metrics"], m["entry"]
        cols = m["columns"]
        for k, shot in enumerate(m["shots"]):
            # `m["shots"]` 是**逐层拼接**的（ΔV 外层、γ、β），所以层内下标 = `k % span`
            # 就是那一根 (β,γ) 竖线的列号 —— 与 `fig4.column_index()` 同一条关系。
            i, rest = divmod(k, span)
            j, b = divmod(rest, n_beta)
            beta = float(grid.beta[b])
            gamma = float(grid.gamma[j])
            dv = float(grid.dv[i])
            sc = bg3d.scaling3_for(point, metrics, beta=beta, gamma=gamma, dv=dv)
            rows.append({
                "missile": entry.key, "beta_target": beta, "gamma_target": gamma,
                "dv_target": dv, "thrust_scale": sc.thrust_scale, "cx_scale": sc.cx_scale,
                "cxaoa_scale": sc.cxaoa_scale, "n_star_g": cols["n_star_g"][rest],
                "R_ref": cols["R_ref"][rest],
                "induced_dominated": cols["induced"][rest],
                "event": (shot.event if shot else ""), "hit": int(bool(shot and shot.hit)),
                "t_hit_s": (shot.t_hit if shot else None),
                "t_end_s": (shot.t_end if shot else None),
                "miss_distance_m": (shot.miss_m if shot else None),
                "max_alt_m": (shot.max_alt_m if shot else None),
                "v_impact_ms": (shot.v_impact if shot else None),
                "dv_measured_ms": (shot.dv_measured if shot else None),
                "t_burnout_s": (shot.t_burnout if shot else None),
                "backend": (shot.backend if shot else ""), "error": (shot.error if shot else ""),
            })
    return rows


def build_record(scan: dict, *, tag: str, standard) -> dict:
    """扫描结果 → `results/fig4_<tag>.json` 的内容。"""
    grid = scan["grid"]
    missiles = []
    for m in scan["missiles"]:
        fit = m["fit"]
        missiles.append({
            "key": m["entry"].key, "label": m["entry"].label, "native": m["entry"].native,
            "full_name": m["entry"].full_name,
            "beta": float(m["point"].beta), "gamma": float(m["point"].gamma),
            "dv": float(m["metrics"].dv),
            "q_sens": float(m["columns"]["q_sens"][0]) if m["columns"]["q_sens"] else None,
            "n_star_g": float(m["columns"]["n_star_g"][len(m["columns"]["n_star_g"]) // 2])
            if m["columns"]["n_star_g"] else None,
            "R_ref": float(m["columns"]["R_ref"][len(m["columns"]["R_ref"]) // 2])
            if m["columns"]["R_ref"] else None,
            "columns": {"n_star_g": list(m["columns"]["n_star_g"]),
                        "R_ref": list(m["columns"]["R_ref"]),
                        "induced": list(m["columns"]["induced"])},
            "hit": [[[int(v) for v in row] for row in plane] for plane in m["hit"]],
            "t_hit": _grid_json(m["t_hit"]),
            "dv_measured": _grid_json(m["dv_measured"]),
            "fit": {
                "slope": _list_json(fit["slope"]), "intercept": _list_json(fit["intercept"]),
                "quad": _list_json(fit["quad"]),
                "rms_lin": _list_json(fit["rms_lin"]), "rms_quad": _list_json(fit["rms_quad"]),
                "curv_span": _list_json(fit["curv_span"]),
                "curv_frac": _list_json(fit["curv_frac"]),
                "resid_lin": _list_json(np.asarray(fit["resid_lin"]).T.reshape(-1)),
                "quad_term": _list_json(np.asarray(fit["quad_term"]).T.reshape(-1)),
                "n_col": int(fit["n_col"]), "n_dv": int(fit["n_dv"]),
            },
            "plane": m["plane"],
            "n_cases": int(grid.n_cases), "n_hit": int(m["n_hit"]), "n_ok": int(m["n_ok"]),
            "hit_rate": float(m["n_hit"]) / float(grid.n_cases) if grid.n_cases else 0.0,
            "n_run": int(m["n_run"]), "n_cached": int(m["n_cached"]),
            "backend": m["backend"], "elapsed_s": round(float(m["elapsed_s"]), 3),
            "stats": dict(m["stats"]),
        })
    dv_pin_used = float(grid.dv[len(grid.dv) // 2])
    return {
        "schema": fig4.SCHEMA, "figure": "fig4", "kind": figures.FIG4_KIND, "tag": tag,
        "scene": scan["scene"].as_dict(),
        "standard": str(getattr(standard, "key", standard)),
        "standard_native": str(getattr(standard, "native", "")),
        "tier": scan["tier"], "backend": scan["missiles"][0]["backend"] if scan["missiles"] else "",
        "solver": dict(solver.identity()),
        "n_ref": float(scan["n_ref"]),
        "ref_condition": _ref_block(scan),
        "grid": dict(grid.as_dict(), limits=grid.limits(),
                     dv_pin_ms=dv_pin_used,
                     dv_factors=[round(float(v) / dv_pin_used, 6) for v in grid.dv]),
        "missiles": missiles,
        "summary": {"n_missiles": len(missiles), "n_cases": int(grid.n_cases),
                    "n_total": int(grid.n_cases) * len(missiles),
                    "shape": list(grid.shape),
                    "flat_order": fig4.FLAT_ORDER,
                    "n_hit": int(sum(m["n_hit"] for m in missiles)),
                    "elapsed_s": round(float(scan["elapsed_s"]), 3),
                    "n_run": int(sum(m["n_run"] for m in missiles)),
                    "n_cached": int(sum(m["n_cached"] for m in missiles))},
        "ref_note": ("诱导阻力主导 = R = (n_ref/n*)² ≥ 1；"
                     "n* = q/(Q·g0)、Q = sqrt(β·γ·F/f)，口径与图2 的等 n* 线同一套。"),
    }


def _ref_block(scan: dict) -> dict:
    q_pa, f_mach, cap_f, ratio = bg.levels(alt_m=scan["ref_alt_m"], speed_ms=scan["ref_speed_ms"])
    return {"alt_m": 10000.0 if scan["ref_alt_m"] is None else float(scan["ref_alt_m"]),
            "speed_ms": 800.0 if scan["ref_speed_ms"] is None else float(scan["ref_speed_ms"]),
            "q_pa": float(q_pa), "f_mach": float(f_mach), "cap_f": float(cap_f),
            "F_over_f": float(ratio)}


def _grid_json(arr) -> list:
    return [[[None if not np.isfinite(v) else round(float(v), 6) for v in row] for row in plane]
            for plane in np.asarray(arr, dtype=float)]


def _list_json(arr) -> list:
    return [None if not np.isfinite(float(v)) else round(float(v), 8)
            for v in np.asarray(arr, dtype=float).reshape(-1)]


def write_products(rec: dict, rows: list, *, tag: str, result_dir=None) -> dict:
    """落盘：`fig4_<tag>.json` + `fig4_<tag>_cases.csv`（返回路径表）。"""
    res_dir = RESULT_DIR if result_dir is None else result_dir
    paths = {"record": str(record.write_json(res_dir / f"fig4_{tag}.json", rec)),
             "cases": str(record.write_fig4_cases_csv(rows, res_dir / f"fig4_{tag}_cases.csv"))}
    return paths


def run_scan(scene: Scene, *, entries, tag: str, standard=None, tier: str = "fast", jobs: int = 8,
             cache: bool = True, n_beta: int = DEFAULT_N_BETA,
             n_gamma: int = DEFAULT_N_GAMMA, dv_factors=DEFAULT_DV_FACTORS,
             dv_pin: float | None = None, n_ref: float = 20.0, ref_alt_m=None,
             ref_speed_ms=None, result_dir=None, progress=None, log=None) -> dict:
    """一条命令的重出路径（CLI `--figure fig4` 与测试都走它）。

    返回 `{"scan":…, "record":…, "rows":…, "paths":…, "grid":…, "elapsed_s":…}`。
    """
    say = log or (lambda _m: None)
    rows_ = bg.rows(entries or None)                    # 图2 的域由弹池定；顺带拿 11 型的 β/γ
    std_entry = pool.standard_entry(standard)
    pin = float(dv_pin) if dv_pin else float(pool.metrics_of(std_entry).dv)
    grid = default_grid(rows_, dv_pin=pin, n_beta=n_beta, n_gamma=n_gamma,
                        dv_factors=dv_factors)
    say(f"网格 (ΔV,γ,β) = {grid.shape} = {grid.n_cases} 工况 × {len(entries)} 弹 "
        f"= {grid.n_cases * len(entries)}；ΔV 钉值 {pin:.4f} m/s"
        f"（{'用户指定' if dv_pin else '基准弹 ' + std_entry.key + ' 标称'}）")
    say(f"β {grid.beta[0]:.2f}~{grid.beta[-1]:.2f}（{len(grid.beta)} 点）· "
        f"γ {grid.gamma[0]:.3f}~{grid.gamma[-1]:.3f}（{len(grid.gamma)} 点）· "
        f"ΔV {grid.dv[0]:.2f}~{grid.dv[-1]:.2f}（{len(grid.dv)} 点）")
    scan = scan_all(scene, entries=entries, grid=grid, tier=tier, jobs=jobs, cache=cache,
                    n_ref=n_ref, ref_alt_m=ref_alt_m, ref_speed_ms=ref_speed_ms,
                    progress=progress, log=say)
    rec = build_record(scan, tag=tag, standard=std_entry)
    rows = case_rows(scan)
    paths = write_products(rec, rows, tag=tag, result_dir=result_dir)
    say(f"总计 {rec['summary']['n_total']} 工况（真解算 {rec['summary']['n_run']} · "
        f"命中缓存 {rec['summary']['n_cached']}）· 命中 {rec['summary']['n_hit']} · "
        f"耗时 {scan['elapsed_s']:.1f} s")
    return {"scan": scan, "record": rec, "rows": rows, "paths": paths, "grid": grid,
            "elapsed_s": scan["elapsed_s"], "dv_pin": pin, "standard": std_entry}

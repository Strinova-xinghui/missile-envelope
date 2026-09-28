# -*- coding: utf-8 -*-
"""端到端：**一次调用把散点 + 等时线 + 产物全部落地**。

    points(弹池现算) ─► adaptive_axis ─► make_grid ─► Engine.many ─► t_hit 矩阵
                                                                        │
                            figures.plot_plane ◄── IsoGrid ◄── extract_isolines
                                     │
                        figures/*.png|pdf|svg + results/plane_*.{csv,json}

`--no-iso` 时跳过扫描，只出散点（秒级），用来先看轴与弹池选得对不对。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import figures, grid as grid_mod, mapping, pool, record, solver
from .engine import Engine
from .spec import FIG_DIR, RESULT_DIR, AxisSpec, IsoGrid, Provenance, Scene


@dataclass
class PlaneRequest:
    """一次出图的全部输入。**字段名即 CLI 参数名**（见 `cli.py`）。

    ⚠ 每个字段**都必须有类型注解** —— 少写一个，dataclass 就不把它当字段，
    CLI 传进来的值会被 `dataclasses.replace()` 静默丢掉（曾因此让 `--missiles` 失效）。
    """

    scene: Scene = field(default_factory=Scene)
    standard: str = "PL-12"                  # 基准弹（池内短名）
    missiles: tuple | list | None = None     # None ⇒ 全池；否则短名序列
    tier: str = "fast"
    iso_step: float = 1.0
    dv_step: float = 10.0
    bc_step: float = 25.0
    jobs: int = 8
    cache: bool = True
    with_iso: bool = True
    xlim: tuple | None = None                # 显式给就覆盖自适应
    ylim: tuple | None = None
    tag: str = "default"
    formats: tuple = ("png", "pdf", "svg")
    colorbar: bool = True
    figure_dir: Path | None = None
    result_dir: Path | None = None

    def check(self) -> list:
        bad = list(self.scene.check())
        if self.tier not in ("standard", "fast"):
            bad.append(f"tier 只能是 standard / fast，收到 {self.tier!r}")
        if self.iso_step <= 0:
            bad.append("iso_step 必须为正")
        if self.dv_step <= 0 or self.bc_step <= 0:
            bad.append("网格步长必须为正")
        return bad


def run_plane(req: PlaneRequest, *, progress=None, log=None) -> dict:
    """跑完整条链路，返回带 `_paths` 的汇总 dict（产物路径都在里面）。"""
    bad = req.check()
    if bad:
        raise ValueError("输入不自洽：" + "；".join(bad))
    say = log or (lambda _m: None)
    t0 = time.perf_counter()

    # ---- ① 弹池（散点）与基准弹 --------------------------------------
    pts = pool.points(req.missiles)
    std_entry = pool.standard_entry(req.standard)
    std_metrics = pool.metrics_of(std_entry)
    say(f"弹池 {len(pts)} 型；基准弹 {std_entry.key}（{std_entry.native}）"
        f"ΔV_blk={std_metrics.dv:.2f} BC_blk={std_metrics.bc:.1f}")

    # ---- ② 自适应轴 ---------------------------------------------------
    axis = figures.adaptive_axis(pts)
    if req.xlim is not None or req.ylim is not None:
        axis = replace(axis,
                       xlim=tuple(req.xlim) if req.xlim else axis.xlim,
                       ylim=tuple(req.ylim) if req.ylim else axis.ylim)
    say(f"坐标轴 ΔV {axis.xlim[0]:.0f}~{axis.xlim[1]:.0f}（主 {axis.x_major:g}）"
        f" · BC {axis.ylim[0]:.0f}~{axis.ylim[1]:.0f}（主 {axis.y_major:g}）")

    # ---- ③ 扫描（可选）------------------------------------------------
    g = grid_mod.make_grid(axis.xlim, axis.ylim, dv_step=req.dv_step, bc_step=req.bc_step)
    shots, t_grid, lines = [], None, []
    n_hit = 0
    if req.with_iso:
        say(f"网格 {g.shape[0]}×{g.shape[1]} = {g.n_cases} 工况"
            f"（ΔV 步长 {req.dv_step:g} / BC 步长 {req.bc_step:g}，档位 {req.tier}）")
        eng = Engine(req.scene, missile=std_entry.native, tier=req.tier, jobs=req.jobs,
                     cache=req.cache, metrics=std_metrics, progress=progress)
        try:
            shots = eng.many(g.cells)
        finally:
            eng.close()
        t_grid = grid_mod.t_hit_matrix(shots, g)
        import numpy as np

        n_hit = int(np.isfinite(t_grid).sum())
        lines = grid_mod.extract_isolines(t_grid, g, step=req.iso_step)
        say(f"命中 {n_hit}/{g.n_cases}（{100.0 * n_hit / max(g.n_cases, 1):.0f}%）；"
            f"等时线 {len(lines)} 层 · 缓存命中 {eng.stats['cache']} 次 · "
            f"耗时 {time.perf_counter() - t0:.1f} s")
    else:
        say("--no-iso：只出散点，不扫描")

    # ---- ④ 出图 -------------------------------------------------------
    fig_dir = req.figure_dir or FIG_DIR
    res_dir = req.result_dir or RESULT_DIR
    backend = _backend_of(shots, req.tier)
    prov = Provenance(tier=req.tier, backend=backend, solver=solver.identity(),
                      standard=f"{std_entry.key}", scene=req.scene.as_dict())
    fig_paths = []
    if req.with_iso and lines:
        iso = IsoGrid(dv=g.dv, bc=g.bc, t_grid=t_grid)
        fig_paths = figures.plot_plane(
            points=pts, iso=iso, axis=axis,
            out_base=fig_dir / f"fig_isotime_plane_{req.tag}",
            title=figures.plane_title(with_iso=True),
            subtitle=figures.plane_subtitle(req.scene, standard=std_entry.key),
            footnotes=record.provenance_lines(prov) + [
                f"等时线步长 {req.iso_step:g} s；网格 {g.shape[0]}×{g.shape[1]}="
                f"{g.n_cases} 工况，命中 {n_hit}/{g.n_cases}。"
                f"点 = 池内 {len(pts)} 型从 vendor/wt-missile 的 blk 现算的权威 ΔV/BC。"],
            iso_step=req.iso_step, colorbar=req.colorbar, formats=req.formats,
            highlight=pool.point_of(std_entry), highlight_label=f"基准弹 {std_entry.key}")
    else:
        fig_paths = figures.plot_plane(
            points=pts, iso=None, axis=axis,
            out_base=fig_dir / f"fig_isotime_plane_{req.tag}",
            title=figures.plane_title(with_iso=False),
            subtitle=figures.plane_subtitle(req.scene, standard=std_entry.key),
            footnotes=[f"点 = 池内 {len(pts)} 型从 vendor/wt-missile 的 blk 现算的权威 ΔV/BC"
                       "（ΔV 为真空等效增速，BC = 干重/(CxK·SD)）。"],
            iso_step=req.iso_step, colorbar=False, formats=req.formats,
            highlight=pool.point_of(std_entry), highlight_label=f"基准弹 {std_entry.key}")

    # ---- ⑤ 产物 -------------------------------------------------------
    paths = {"figures": [str(p) for p in fig_paths]}
    if req.with_iso:
        paths["cases"] = str(record.write_cases_csv(
            shots, g, res_dir / f"plane_{req.tag}_cases.csv",
            scaling_for=lambda dv, bc: mapping.scaling_for(dv, bc, std_metrics)))
        paths["isolines"] = str(record.write_isolines_csv(
            lines, res_dir / f"plane_{req.tag}_isolines.csv"))
    manifest = record.make_manifest(
        scene=req.scene, standard=std_entry.key, tier=req.tier,
        solver_identity=solver.identity(), backend=backend, points=pts, axis=axis, grid=g,
        iso_step=req.iso_step, n_hit=n_hit, elapsed_s=time.perf_counter() - t0, tag=req.tag)
    manifest["with_iso"] = bool(req.with_iso)
    manifest["iso_levels"] = [item["level"] for item in lines]
    manifest["missiles"] = [p.key for p in pts]
    if t_grid is not None:
        manifest["t_hit_range_s"] = _range_of(t_grid)
        manifest["monotonic"] = grid_mod.monotonic_report(t_grid, g)
    paths["manifest"] = str(record.write_json(res_dir / f"plane_{req.tag}.json", manifest))

    return {"points": pts, "axis": axis, "grid": g, "shots": shots, "t_grid": t_grid,
            "isolines": lines, "n_hit": n_hit, "manifest": manifest, "provenance": prov,
            "backend": backend, "standard": std_entry, "elapsed_s": manifest["elapsed_s"],
            "_paths": paths}


def _backend_of(shots, tier: str) -> str:
    for s in shots or ():
        if s is not None and s.backend:
            return str(s.backend)
    return "python-standard" if tier == "standard" else "unreported"


def _range_of(t_grid):
    import numpy as np

    a = np.asarray(t_grid, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return None
    return [float(finite.min()), float(finite.max())]


# ===================================================================== 图2：β–γ 平面


@dataclass
class BgRequest:
    """第二张图（β–γ 能力平面）的全部输入。**字段名即 CLI 参数名**。

    与 `PlaneRequest` 的两处根本差别：

    * **固定 ΔV**（`dv_pin`，默认取基准弹的权威 ΔV），扫的是 (β, γ)；
      第一张图固定别的一切、扫 (ΔV, BC)。
    * 参考工况（`alt_m` / `speed_ms`）**只影响等 n* 线与派生指标**，
      β、γ 本身是弹的固有量 —— 所以改它不会移动任何一个散点，只会移动那族双曲线。
    """

    scene: Scene = field(default_factory=Scene)
    standard: str = "PL-12"
    missiles: tuple | list | None = None
    tier: str = "fast"
    jobs: int = 8
    cache: bool = True
    with_scan: bool = True
    beta_step: float = 30.0
    gamma_step: float = 2.0
    iso_step: float = 1.0
    dv_pin: float | None = None              # None ⇒ 基准弹标称 ΔV
    n_ref: float = 20.0                      # R / β_eff 的参考过载
    alt_m: float | None = None               # None ⇒ 10 km（参考图口径）
    speed_ms: float | None = None            # None ⇒ 800 m/s
    xlim: tuple | None = None
    ylim: tuple | None = None
    tag: str = "default"
    formats: tuple = ("png", "pdf", "svg")
    figure_dir: Path | None = None
    result_dir: Path | None = None

    def check(self) -> list:
        bad = list(self.scene.check())
        if self.tier not in ("standard", "fast"):
            bad.append(f"tier 只能是 standard / fast，收到 {self.tier!r}")
        if self.beta_step <= 0 or self.gamma_step <= 0:
            bad.append("β/γ 网格步长必须为正")
        if self.iso_step <= 0:
            bad.append("iso_step 必须为正")
        if self.n_ref <= 0:
            bad.append("参考过载必须为正")
        if self.dv_pin is not None and self.dv_pin <= 0:
            bad.append("固定 ΔV 必须为正")
        return bad


def run_bg(req: BgRequest, *, progress=None, log=None) -> dict:
    """跑第二张图的链路：β–γ 固有量 → （可选）(β, γ) 扫描 → 出图 → 产物。"""
    from . import bg

    bad = req.check()
    if bad:
        raise ValueError("输入不自洽：" + "；".join(bad))
    say = log or (lambda _m: None)
    t0 = time.perf_counter()

    # ---- ① 固有量（不跑求解器）----------------------------------------
    std_entry = pool.standard_entry(req.standard)
    std_point = bg.point_of(std_entry)
    std_metrics = pool.metrics_of(std_entry)
    rows_ = bg.rows(req.missiles, alt_m=req.alt_m, speed_ms=req.speed_ms, n=req.n_ref)
    ref = bg.evaluate_point(std_point, alt_m=req.alt_m, speed_ms=req.speed_ms, n=req.n_ref)
    dv_pin = float(req.dv_pin if req.dv_pin else std_metrics.dv)
    say(f"弹池 {len(rows_)} 型；基准弹 {std_entry.key}（{std_entry.native}）"
        f"β={std_point.beta:.1f} γ={std_point.gamma:.2f} · 固定 ΔV={dv_pin:.2f} m/s")
    say(f"参考工况 {ref.alt_m / 1000:g} km / {ref.speed_ms:g} m/s → Ma {ref.mach:.3f}"
        f" · q={ref.q_pa:.1f} Pa · f={ref.f_mach:.5f} F={ref.cap_f:.5f}")

    # ---- ② 自适应轴（β 横轴 / γ 纵轴）---------------------------------
    axis = figures.bg_axis(rows_)
    if req.xlim is not None or req.ylim is not None:
        axis = replace(axis,
                       xlim=tuple(req.xlim) if req.xlim else axis.xlim,
                       ylim=tuple(req.ylim) if req.ylim else axis.ylim)
    say(f"坐标轴 β {axis.xlim[0]:.0f}~{axis.xlim[1]:.0f}（主 {axis.x_major:g}）"
        f" · γ {axis.ylim[0]:.2f}~{axis.ylim[1]:.2f}（主 {axis.y_major:g}）")

    # ---- ③ 扫描（可选）------------------------------------------------
    g = grid_mod.make_grid(axis.xlim, axis.ylim,
                           dv_step=req.beta_step, bc_step=req.gamma_step)
    shots, t_grid, lines, n_hit = [], None, [], 0
    backend = "not-run"
    if req.with_scan:
        say(f"网格 {g.shape[0]}×{g.shape[1]} = {g.n_cases} 工况"
            f"（β 步长 {req.beta_step:g} / γ 步长 {req.gamma_step:g}，档位 {req.tier}）")
        eng = Engine(req.scene, missile=std_entry.native, tier=req.tier, jobs=req.jobs,
                     cache=req.cache, metrics=std_metrics, progress=progress,
                     scaling_of=lambda b, g_: bg.scaling_for(
                         std_point, std_metrics, beta=b, gamma=g_, dv=dv_pin))
        try:
            shots = eng.many(g.cells)
        finally:
            eng.close()
        t_grid = grid_mod.t_hit_matrix(shots, g)
        import numpy as np

        n_hit = int(np.isfinite(t_grid).sum())
        lines = grid_mod.extract_isolines(t_grid, g, step=req.iso_step)
        backend = _backend_of(shots, req.tier)
        say(f"命中 {n_hit}/{g.n_cases}（{100.0 * n_hit / max(g.n_cases, 1):.0f}%）；"
            f"等时线 {len(lines)} 层 · 缓存命中 {eng.stats['cache']} 次 · "
            f"耗时 {time.perf_counter() - t0:.1f} s")
    else:
        say("--bg-no-scan：只出参考图那一套（散点 + 等 n* 线）")

    # ---- ④ 出图 -------------------------------------------------------
    fig_dir = req.figure_dir or FIG_DIR
    res_dir = req.result_dir or RESULT_DIR
    prov = Provenance(tier=req.tier, backend=backend, solver=solver.identity(),
                      standard=f"{std_entry.key}", scene=req.scene.as_dict())
    extra = [f"仿真层：固定 ΔV={dv_pin:.2f} m/s（{'用户指定' if req.dv_pin else '基准弹标称'}），"
             f"在 β×γ 网格上只改 CxK 与 CxAoA，其余量全不动；"]
    if req.with_scan:
        extra.append(f"网格 {g.shape[0]}×{g.shape[1]}={g.n_cases} 工况，命中 {n_hit}/{g.n_cases}，"
                     f"等时线步长 {req.iso_step:g} s。β 步长 {req.beta_step:g}、"
                     f"γ 步长 {req.gamma_step:g}。")
        extra.append(
            "读法：迎头直飞这类**几乎不机动**的工况下，等时线近乎竖直 —— 命中时间几乎只由 β 决定。"
            "这不是画错：按 a_loss = q·f/β + γ·F·(n·g0)²/q，低过载时基础项主导，"
            "γ 要等到需要大过载转弯（离轴、机动目标）才显出来。")
    else:
        extra.append("本次未跑仿真层（--bg-no-scan）。")
    fig_paths = figures.plot_bg_plane(
        rows=rows_, axis=axis, out_base=fig_dir / f"fig_bg_plane_{req.tag}",
        highlight=std_entry.key, n=req.n_ref, alt_m=req.alt_m, speed_ms=req.speed_ms,
        scan=(g.dv, g.bc, t_grid) if (req.with_scan and t_grid is not None) else None,
        footnotes=figures.BG_FOOTNOTES + tuple(extra) + tuple(record.provenance_lines(prov)),
        formats=req.formats)

    # ---- ⑤ 产物 -------------------------------------------------------
    paths = {"figures": [str(p) for p in fig_paths],
             "points": str(record.write_bg_points_csv(rows_, res_dir / f"bg_{req.tag}_points.csv"))}
    if req.with_scan:
        paths["cases"] = str(record.write_bg_cases_csv(
            shots, g, res_dir / f"bg_{req.tag}_cases.csv",
            scaling_of=lambda b, g_: bg.scaling_for(
                std_point, std_metrics, beta=b, gamma=g_, dv=dv_pin)))
        paths["isolines"] = str(record.write_bg_isolines_csv(
            lines, res_dir / f"bg_{req.tag}_isolines.csv"))
    manifest = record.make_bg_manifest(
        scene=req.scene, standard=std_entry.key, standard_native=std_entry.native,
        tier=req.tier, solver_identity=solver.identity(), backend=backend,
        rows_=rows_, reference=ref, n=req.n_ref, beta_step=req.beta_step,
        gamma_step=req.gamma_step, iso_step=req.iso_step, dv_pin=dv_pin,
        grid=g if req.with_scan else None, n_hit=n_hit,
        elapsed_s=time.perf_counter() - t0, tag=req.tag)
    manifest["with_scan"] = bool(req.with_scan)
    manifest["iso_levels"] = [item["level"] for item in lines]
    manifest["missiles"] = [r.key for r in rows_]
    if t_grid is not None:
        manifest["t_hit_range_s"] = _range_of(t_grid)
        # β 是"越大越省"，γ 是"越大越费"：两个方向的单调期望正好相反，
        # 所以这里分别报，不要用同一个 expect。
        manifest["monotonic_beta"] = grid_mod.monotonic_report(
            t_grid, g, axis=0, expect="decrease")
        manifest["monotonic_gamma"] = grid_mod.monotonic_report(
            t_grid, g, axis=1, expect="increase")
    paths["manifest"] = str(record.write_json(res_dir / f"bg_{req.tag}.json", manifest))

    return {"rows": rows_, "axis": axis, "grid": g, "shots": shots, "t_grid": t_grid,
            "isolines": lines, "n_hit": n_hit, "manifest": manifest, "provenance": prov,
            "backend": backend, "standard": std_entry, "dv_pin": dv_pin,
            "reference": ref, "elapsed_s": manifest["elapsed_s"], "_paths": paths}

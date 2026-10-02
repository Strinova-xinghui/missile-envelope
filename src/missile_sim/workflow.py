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

import math
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
            "读法：迎头直飞这类几乎不机动的工况下，等时线近乎竖直 —— 命中时间几乎只由 β 决定。"
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


# ===================================================================== 图3：机动想定

#: 只为**取出 crank 腿**而用的占位开机时刻：只要 > `t_crank`，`crank_beam()` 就会给出
#: `[crank, beam]` 两条腿，筛掉 beam 腿后剩下的正是"正式工况去掉 39 腿"的那条调度。
#: 这个值本身**不参与任何计算**（不落盘、不进图、不进 `maneuvers`）。
_T_BEAM_PLACEHOLDER = 1.0e9


def _lock_distance_of(entry) -> float:
    """基准弹的 `guidance.lockDistance` —— 外壳口径的"导引头开机距离"。

    内核 grep 这个字段**零命中**（它用 `permanent_lock` + `unlimited_acquisition`，
    没有"开机/pitbull"事件），所以"开机"只能由外壳定义；用 blk 里这个值最自然：
    120 系列 / MICA / Derby / AAM-4 / R-Darter = 20 km，PL-12 / R-77 系列 = 16 km。
    """
    prof = solver.profile(entry.native) or {}
    raw = (prof.get("guidance") or {}).get("lockDistance")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = math.nan
    if not math.isfinite(val) or val <= 0.0:
        raise ValueError(f"{entry.key} 的 guidance.lockDistance 取不到（{raw!r}），"
                         f"请显式给 lock_distance_m")
    return val


@dataclass
class TrajRequest:
    """第三张图（一个机动想定的完整轨迹）的全部输入。**字段名即 CLI 参数名**。

    与图1/图2 的三处根本差别：

    * **只跑一枚弹**（全局基准弹 `standard`，默认 PL-12），不扫任何平面；
    * **要跑两遍**：第一遍**不含 39 腿**，只为反求"导引头开机"时刻（一遍法，见
      `traj.ANCHOR_MODE`）；第二遍才是正式工况。所以耗时是单次求解的两倍；
    * `scene.maneuvers` 必须留空 —— 目标运动由本请求编译，在 `Scene` 上另给一份
      会被**静默覆盖**（同一族的坑，见 `AGENTS.md`），所以 `check()` 直接拒收。

    没有 `jobs` / `cache`：只跑 1~2 个工况，进程池没有意义；而且轨迹要逐采样行，
    `Engine` 的缓存**只存不带行的 `Shot`**（`want_rows=True` 一律绕开缓存），
    留着只会让人以为缓存生效了。
    """

    scene: Scene = field(default_factory=Scene)
    standard: str = "PL-12"
    tier: str = "fast"
    t_crank: float = 8.0                     # 发射后多久开始 crank [s]
    crank_deg: float = 70.0                  # crank 离轴角 [°]（朝威胁外侧转这么多）
    crank_g: float = 9.0                     # crank 段转向过载 [G]
    beam_deg: float = 90.0                   # 39 位离轴角 [°]（90 = 正侧方）
    beam_g: float = 9.0                      # 转 39 段转向过载 [G]
    lock_distance_m: float | None = None     # None ⇒ 基准弹 blk 的 guidance.lockDistance
    react_delay_s: float = 1.0               # 看到 RWR 告警后的反应时间 [s]
    weave: bool = False                      # 俯仰震荡（默认关：用户经验值待提供）
    weave_amp_deg: float = 4.0
    weave_hz: float = 0.1
    t_beam_s: float | None = None            # 显式钉住开机时刻（复现/预览用；None ⇒ 反求）
    preview: bool = False                    # True ⇒ 只出目标航迹 3D 预览，不跑求解器
    tag: str = "default"
    formats: tuple = ("png", "pdf", "svg")
    figure_dir: Path | None = None
    result_dir: Path | None = None

    def check(self) -> list:
        from . import flightpath

        bad = list(self.scene.check())
        if self.scene.maneuvers:
            bad.append("图3 的目标运动由本请求编译，scene.maneuvers 必须留空"
                       "（在 Scene 上另给一份会被静默覆盖）")
        if self.tier not in ("standard", "fast"):
            bad.append(f"tier 只能是 standard / fast，收到 {self.tier!r}")
        if not math.isfinite(self.t_crank) or self.t_crank < 0:
            bad.append("crank 时刻必须是非负有限数")
        if not 0.0 < self.crank_deg < 180.0:
            bad.append("crank 离轴角要在 (0, 180)° 内")
        if not 0.0 < self.beam_deg < 180.0:
            bad.append("39 位离轴角要在 (0, 180)° 内")
        if not (self.crank_g > 0 and self.beam_g > 0):
            bad.append("转向过载必须为正（0 转不动，等于没有这条腿）")
        if self.lock_distance_m is not None and not (
                math.isfinite(self.lock_distance_m) and self.lock_distance_m > 0):
            bad.append("开机距离必须是正的有限数")
        if not math.isfinite(self.react_delay_s) or self.react_delay_s < 0:
            bad.append("反应延迟必须是非负有限数")
        if self.t_beam_s is not None and not (
                math.isfinite(self.t_beam_s) and self.t_beam_s >= 0):
            bad.append("显式给的 t_beam_s 必须是非负有限数")
        if self.weave:
            try:
                flightpath.WeaveLeg(0.0, self.weave_amp_deg, self.weave_hz).check()
            except ValueError as exc:
                bad.append(str(exc))
        return bad

    def as_dict(self) -> dict:
        """落盘用的输入快照（**不含** `figure_dir` / `result_dir` 这类路径）。"""
        return {
            "standard": self.standard, "tier": self.tier,
            "t_crank": self.t_crank, "crank_deg": self.crank_deg,
            "crank_g": self.crank_g, "beam_deg": self.beam_deg, "beam_g": self.beam_g,
            "lock_distance_m": self.lock_distance_m, "react_delay_s": self.react_delay_s,
            "weave": ({"amp_deg": self.weave_amp_deg, "hz": self.weave_hz}
                      if self.weave else None),
            "t_beam_s": self.t_beam_s, "tag": self.tag,
            "formats": list(self.formats),
        }


def _traj_schedule(req: TrajRequest, *, t_beam: float, speed_ms: float,
                   weave_start_s: float | None):
    """把想定编译成 `PathSchedule`（**唯一**一处调 `crank_beam()` 的地方）。"""
    from . import flightpath

    weave = (flightpath.WeaveLeg(weave_start_s, req.weave_amp_deg, req.weave_hz)
             if (req.weave and weave_start_s is not None) else None)
    return flightpath.crank_beam(req.t_crank, req.crank_deg, t_beam,
                                 beam_deg=req.beam_deg, speed_ms=speed_ms,
                                 g_crank=req.crank_g, g_beam=req.beam_g,
                                 react_delay_s=req.react_delay_s, weave=weave)


def _traj_without_beam(req: TrajRequest, *, speed_ms: float):
    """第一遍要用的调度：**正式工况去掉 39 腿**（一遍法，见 `traj.ANCHOR_MODE`）。

    ⚠ 不能拿"已经加了 39 腿"的调度去迭代求开机时刻 —— 那是自指条件。而
    `t_beam < t_react` 恒成立（延迟非负），39 腿最早也在 `t_react` 才起作用，
    所以这条去掉 39 腿的轨迹在 `t_beam` 那一刻与正式轨迹**完全相同**（精确，不是近似）。
    """
    from . import flightpath

    probe = _traj_schedule(req, t_beam=_T_BEAM_PLACEHOLDER, speed_ms=speed_ms,
                           weave_start_s=None)
    legs = tuple(leg for leg in probe.legs if leg.phase != "beam")
    return flightpath.PathSchedule(speed_ms=speed_ms,
                                   start_heading_deg=probe.start_heading_deg,
                                   legs=legs, weave=None)


def run_traj(req: TrajRequest, *, progress=None, log=None) -> dict:
    """跑图3 的链路：反求开机 → 正式一遍 → 出图 → 产物。

    `req.preview=True` 时**不解算**（`solver.run` 零调用；只读一次 blk 取 `guidance.lockDistance`），
    只按运动学画出目标航迹 3D，给输入阶段"改参数即时看"用
    （`docs/PLAN-FIG3-TRAJECTORY.md` §6）。耗时实测：不出图 0.08~0.10 s、
    只出 png ≈0.75 s、三格式 1.9~2.6 s（都是本函数的 `elapsed_s`，不含解释器与 matplotlib 启动）。

    返回到 `anchor` 里有一个 **`react_after_pass1_hit`** 布尔量：为真表示**39 指令落在第一遍命中之后**
    （开机距离被人为调小才会出现），此时 39 腿没有物理意义，脚注里会明写。
    """
    from . import bg, flightpath, traj

    bad = req.check()
    if bad:
        raise ValueError("输入不自洽：" + "；".join(bad))
    say = log or (lambda _m: None)
    t0 = time.perf_counter()

    # ---- ① 基准弹 / 开机距离 / 想定几何 --------------------------------
    entry = pool.standard_entry(req.standard)
    point = bg.point_of(entry)
    v_t = float(req.scene.target_speed_ms)
    dur = float(req.scene.duration_s)
    lock_user = req.lock_distance_m is not None
    lock = float(req.lock_distance_m) if lock_user else _lock_distance_of(entry)
    say(f"基准弹 {entry.key}（{entry.native}）β={point.beta:.1f} γ={point.gamma:.2f}"
        f" · 开机距离 {lock / 1000:g} km（{'用户指定' if lock_user else 'blk guidance.lockDistance'}）")

    # ---- ② 预览：只画目标航迹，不跑求解器 ------------------------------
    if req.preview:
        t_beam = req.t_beam_s
        if t_beam is not None:
            sch = _traj_schedule(req, t_beam=float(t_beam), speed_ms=v_t,
                                 weave_start_s=float(t_beam) + float(req.react_delay_s))
        else:
            # 没给开机时刻就不可能有 39 腿 —— 那正是要解算的量。只画 crank 那一段，
            # 震荡按 t_crank 起算（图上会写明这是预览口径）。
            sch = _traj_without_beam(req, speed_ms=v_t)
            if req.weave:
                sch = replace(sch, weave=flightpath.WeaveLeg(
                    req.t_crank, req.weave_amp_deg, req.weave_hz))
        extra = [
            "输入阶段预览：不解算（solver.run 零调用，只读一次 blk 取开机距离），"
            "按运动学画目标航迹 —— 不出图时约 0.1 s，改参数即可重画。",
            (f"39 腿按用户钉住的 t_beam = {t_beam:g} s 画。"
             if t_beam is not None else
             "本图不含 39 腿 —— 导弹开机时刻要解算后才反求得到，"
             "去掉 --traj-preview 的正式出图才有它。"),
            ("未开启震荡。" if not req.weave else
             f"震荡 ±{req.weave_amp_deg:g}° / {req.weave_hz:g} Hz 在高度方向"
             f"（俯视图只能看到它带来的水平偏离；本图是 3D，竖向摆动直接可见）。"),
        ]
        fig_dir = req.figure_dir or FIG_DIR
        fig_paths = figures.plot_traj_preview_3d(
            sch, p0=req.scene.target_position_m, duration_s=dur,
            out_base=fig_dir / f"fig_traj_preview_{req.tag}", formats=req.formats,
            footnotes=tuple(extra))
        say(f"预览：目标航迹 {dur:g} s · 耗时 {time.perf_counter() - t0:.2f} s")
        return {"schedule": sch, "request": req.as_dict(), "t_beam_s": t_beam,
                "preview": True, "elapsed_s": time.perf_counter() - t0,
                "_paths": {"figures": [str(p) for p in fig_paths]}}

    # ---- ③ 第一遍：不含 39 腿，反求开机时刻 ----------------------------
    pre = _traj_without_beam(req, speed_ms=v_t)
    anchor = None
    shot1 = None
    if req.t_beam_s is not None:                      # 复现：用户钉死开机时刻
        t_beam = float(req.t_beam_s)
        anchor = {"mode": "用户指定（t_beam_s）", "lock_distance_m": lock,
                  "t_beam_s": t_beam, "range_at_beam_m": None}
        say(f"第一遍跳过：开机时刻由用户钉死 t_beam = {t_beam:g} s")
    else:
        say(f"第一遍（不含 39 腿，用于反求开机时刻）· 档位 {req.tier}")
        shot1 = solver.run(replace(req.scene, maneuvers=pre.maneuvers(duration_s=dur, dt=0.1)),
                           missile=entry.native, tier=req.tier, want_rows=True)
        if not shot1.ok:
            raise ValueError(f"第一遍求解失败：{shot1.error}")
        anchor = traj.find_anchor(shot1.rows, lock_distance_m=lock)
        if anchor["t_beam_s"] is None:
            near = min((r["range"] for r in shot1.rows if r["range"] is not None),
                       default=math.inf)
            raise ValueError(
                f"{entry.key} 在这条想定里始终没进过开机距离 {lock / 1000:g} km"
                f"（全程最近 {near / 1000:.1f} km），反求不到开机时刻："
                f"请加大 --duration 或改几何/基准弹")
        t_beam = float(anchor["t_beam_s"])
        say(f"开机（首次 range ≤ {lock / 1000:g} km）t_beam = {t_beam:.2f} s"
            f"（第一遍结局：{'命中 ' + format(shot1.t_hit, '.3f') + ' s' if shot1.hit else '未命中'}）")

    t_react = t_beam + float(req.react_delay_s)
    sch = _traj_schedule(req, t_beam=t_beam, speed_ms=v_t, weave_start_s=t_react)

    # ---- ④ 第二遍：正式工况 -------------------------------------------
    say(f"第二遍（正式工况）· 档位 {req.tier} · 39 指令 {t_react:.2f} s"
        f"（= 开机 {t_beam:.2f} + 反应 {req.react_delay_s:g}）")
    shot = solver.run(replace(req.scene, maneuvers=sch.maneuvers(duration_s=dur, dt=0.1)),
                      missile=entry.native, tier=req.tier, want_rows=True)
    if not shot.ok:
        raise ValueError(f"第二遍求解失败：{shot.error}")

    # ---- ⑤ 分段 / 节点 / "是否转完" ------------------------------------
    segments = sch.segments(duration_s=float(shot.t_end))
    crank_leg = traj.leg_at(sch, "crank")
    crank_turn = next((s for s in pre.segments() if s.phase == "crank" and s.kind == "turn"),
                      None)
    completed = (None if crank_leg is None or crank_turn is None
                 else bool(t_beam >= crank_turn.t1_s))
    heading_at_beam = math.degrees(sch.heading_at(t_beam)[0]) % 360.0
    # ⚠ 「39 指令落在命中之后」要**当输出量报出来**，不能静默出一张看起来正常的图：
    # 开机距离被人为调小时（例如 `--traj-lock-m 100`），第一遍早就命中了，
    # 第二遍的 39 腿因此**起于命中之后**——那不是"目标做了 39 仍被击落"，
    # 而是"目标还没收到告警就已经死了"。图能出，但必须明写（`anchor` 里也留一个布尔量，给外壳/测试用）。
    react_after_hit = bool(shot1 is not None and shot1.hit and t_react >= float(shot1.t_hit))
    anchor.update({"completed": completed, "heading_at_beam_deg": heading_at_beam,
                   "t_react_s": t_react, "react_delay_s": float(req.react_delay_s),
                   "t_crank_turn_end_s": (crank_turn.t1_s if crank_turn else None),
                   "pass1_hit": (None if shot1 is None else bool(shot1.hit)),
                   "pass1_t_hit_s": (None if shot1 is None or not shot1.hit
                                     else float(shot1.t_hit)),
                   "react_after_pass1_hit": react_after_hit})
    if completed is None:
        note = "没有 crank 腿：告警早于 crank，直接进 39（预规避无从谈起）"
    elif completed:
        note = (f"crank 在开机前已转完（{crank_turn.t1_s:.2f} s 到位）；"
                f"开机时航向 {heading_at_beam:.1f}°")
    else:
        note = (f"没转完：开机（{t_beam:.2f} s）时 crank 只到 {heading_at_beam:.1f}°，"
                f"要到 {crank_turn.t1_s:.2f} s 才到位")
    say(f"{note}；39 指令 {t_react:.2f} s；"
        f"结局：{'命中 ' + format(shot.t_hit, '.3f') + ' s' if shot.hit else '未命中 ' + format(shot.miss_m, '.0f') + ' m'}"
        f" · 耗时 {time.perf_counter() - t0:.1f} s")

    run = traj.TrajRun(scene=req.scene, schedule=sch, shot=shot, segments=segments,
                       marks=traj.build_marks(schedule=sch, segments=segments,
                                              anchor=anchor, shot=shot),
                       anchor=anchor, missile=entry.key, beta=point.beta,
                       gamma=point.gamma, rows=list(shot.rows), note=note)

    # ---- ⑥ 出图 -------------------------------------------------------
    fig_dir = req.figure_dir or FIG_DIR
    res_dir = req.result_dir or RESULT_DIR
    backend = shot.backend
    prov = Provenance(tier=req.tier, backend=backend, solver=solver.identity(),
                      standard=entry.key, scene=req.scene.as_dict())
    extra = [
        f"只跑基准弹 {entry.key} 一枚（β={point.beta:.1f}、γ={point.gamma:.2f}），"
        f"开机距离 {lock / 1000:g} km（{'用户指定' if lock_user else 'blk guidance.lockDistance'}）。",
        f"开机时刻用一遍法反求（不含 39 腿的轨迹上首个 range ≤ 开机距离）："
        f"t_beam = {t_beam:.2f} s，39 指令 t_react = {t_react:.2f} s"
        f"（反应延迟 {req.react_delay_s:g} s）。",
        note + "。",
    ]
    if req.weave:
        extra.append(f"目标俯仰震荡 ±{req.weave_amp_deg:g}° / {req.weave_hz:g} Hz，"
                     f"起于 {t_react:.2f} s（3D 主视图里竖向摆动直接可见；"
                     f"竖直方向按显示长度放大过，绝对高度读右侧高度–时间面板）。")
    else:
        extra.append("未开启震荡（用户经验默认值待提供，见 docs/MANEUVER-TARGETS.md §8.5）。")
    if react_after_hit:
        extra.append(
            f"※ 39 指令（{t_react:.2f} s）晚于第一遍命中（{float(shot1.t_hit):.2f} s）："
            f"目标是被击落之后才转 39 的，这一腿没有物理意义，"
            f"结局也不能读成「做了 39 仍被击落」——请把开机距离调大（默认取 blk 的 "
            f"guidance.lockDistance）或把反应延迟调小。")
    fig_paths = figures.plot_traj(
        run, out_base=fig_dir / f"fig_traj_{req.tag}", formats=req.formats,
        footnotes=tuple(extra) + tuple(record.provenance_lines(prov)))

    # ---- ⑦ 产物 -------------------------------------------------------
    paths = {"figures": [str(p) for p in fig_paths],
             "missile": str(record.write_traj_track_csv(shot.rows,
                            res_dir / f"traj_{req.tag}_missile.csv", who="missile")),
             "target": str(record.write_traj_track_csv(shot.rows,
                           res_dir / f"traj_{req.tag}_target.csv", who="target")),
             "segments": str(record.write_traj_segments_csv(
                 segments, res_dir / f"traj_{req.tag}_segments.csv"))}
    manifest = record.make_traj_manifest(
        run=run, scene=req.scene, tier=req.tier, solver_identity=solver.identity(),
        backend=backend, request=req.as_dict(), elapsed_s=time.perf_counter() - t0,
        tag=req.tag)
    paths["manifest"] = str(record.write_json(res_dir / f"traj_{req.tag}.json", manifest))

    return {"run": run, "schedule": sch, "shot": shot, "shot_pass1": shot1,
            "anchor": anchor, "segments": segments, "marks": run.marks,
            "manifest": manifest, "provenance": prov, "backend": backend,
            "standard": entry, "beta": point.beta, "gamma": point.gamma,
            "lock_distance_m": lock, "t_beam_s": t_beam, "t_react_s": t_react,
            "elapsed_s": manifest["elapsed_s"], "_paths": paths}


# ===================================================================== 图4：β–γ–ΔV 三维散点


@dataclass
class Fig4Request:
    """第四张图（β–γ–ΔV 交互式三维散点）的全部输入。**字段名即 CLI / JSON 的键**。

    与前三张图的根本差别：**图4 不出静态图**（它是一页手写 WebGL，见 `webui_static/fig4.*`），
    所以这里没有 `formats` / `figure_dir`；产物只有两份 —— `results/fig4_<tag>.json`
    （立方体 + 逐列拟合 + 判别量）与 `fig4_<tag>_cases.csv`（每工况一行）。

    网格有三组默认（用户拍板，别再改语义）：

    * `n_beta` / `n_gamma` = 7：β、γ **覆盖图2 的域**（`figures.bg_axis`，含端点）；
    * `dv_factors` = 0.6 / 0.8 / 1.0 / 1.2 / 1.4：ΔV 轴 5 点，1.0 那一点正好是 `dv_pin`；
    * `dv_pin` = 基准弹标称 ΔV（PL-12 = 932.5697 m/s）。

    ⚠ `ref_alt_m` / `ref_speed_ms` 是**判别量**（`n*` / `R`）的参考工况，不是发射高度：
    它们沿用图2 的口径（默认 10 km / 800 m/s），所以两张图的等 `n*` 线可以对着看。
    名字上刻意与 `scene.alt_m` 不同 —— 撞名的后果是"改参考高度顺手改掉发射高度"（见 AGENTS.md）。
    """

    scene: Scene = field(default_factory=Scene)
    standard: str = "PL-12"
    missiles: tuple | list | None = None
    tier: str = "fast"
    jobs: int = 8
    cache: bool = True
    n_beta: int = 7
    n_gamma: int = 7
    dv_factors: tuple = (0.6, 0.8, 1.0, 1.2, 1.4)
    dv_pin: float | None = None
    n_ref: float = 20.0
    ref_alt_m: float | None = None
    ref_speed_ms: float | None = None
    tag: str = "default"
    result_dir: Path | None = None

    def check(self) -> list:
        bad = list(self.scene.check())
        if self.tier not in ("standard", "fast"):
            bad.append(f"tier 只能是 standard / fast，收到 {self.tier!r}")
        if int(self.n_beta) < 2 or int(self.n_gamma) < 2:
            bad.append("β、γ 每根轴至少 2 个点")
        try:
            if len(tuple(self.dv_factors)) < 2:
                bad.append("ΔV 至少 2 个点")
        except TypeError:
            bad.append(f"dv_factors 必须是序列，收到 {self.dv_factors!r}")
        if self.dv_pin is not None and self.dv_pin <= 0:
            bad.append("ΔV 钉值必须为正")
        if self.n_ref <= 0:
            bad.append("参考过载 n_ref 必须为正")
        return bad


def run_fig4(req: Fig4Request, *, progress=None, log=None) -> dict:
    """跑图4 的算核：11 弹 × (β,γ,ΔV) 网格 → 立方体 + 拟合 + 判别量 → 两份产物。

    返回里带 `figure="fig4"` 与 `_paths` —— 查看器数据层（`fig4.paths_of()`）就靠这两个键
    认领自己的产物，与图3 的约定一致。
    """
    from . import fig4scan

    bad = req.check()
    if bad:
        raise ValueError("输入不自洽：" + "；".join(bad))
    say = log or (lambda _m: None)
    entries = pool.resolve_many(req.missiles)
    out = fig4scan.run_scan(req.scene, entries=entries, tag=req.tag, standard=req.standard,
                            tier=req.tier, jobs=req.jobs, cache=req.cache,
                            n_beta=req.n_beta, n_gamma=req.n_gamma,
                            dv_factors=req.dv_factors, dv_pin=req.dv_pin,
                            n_ref=req.n_ref, ref_alt_m=req.ref_alt_m,
                            ref_speed_ms=req.ref_speed_ms, result_dir=req.result_dir,
                            progress=progress, log=say)
    rec = out["record"]
    say(f"产物：{out['paths']['record']}")
    say(f"产物：{out['paths']['cases']}")
    return {"figure": "fig4", "tag": req.tag, "tier": req.tier,
            "grid": out["grid"], "record": rec, "rows": out["rows"],
            "standard": out["standard"], "dv_pin": out["dv_pin"],
            "n_missiles": len(entries), "n_total": rec["summary"]["n_total"],
            "n_hit": rec["summary"]["n_hit"], "n_run": rec["summary"]["n_run"],
            "n_cached": rec["summary"]["n_cached"],
            "elapsed_s": out["elapsed_s"], "_paths": out["paths"]}

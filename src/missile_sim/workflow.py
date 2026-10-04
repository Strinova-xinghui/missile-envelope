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
    env_preset: str = "default"              # 共享**环境**预设名（见 presets.py；与 targets 的"预置想定"无关）
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
    #: **画法开关**（用户 2026-10-04 口径）：`False` ⇒ 不画绿色基准弹（点/标签/图例项全去），
    #: 副标题里也不出现「基准弹 …」。首页无输入时贴的 `_static` 形态用它；给定工况的
    #: `_default` 保持 `True`。
    #: ⚠ **绝不能进 `engine.cache_key()`** —— 它是"怎么画"，不是"算什么"，同一工况两种画法
    #: 必须命中同一条缓存。
    show_baseline: bool = True
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
    # 画法开关：不画基准弹时，绿色点/标签/图例项与副标题里的「基准弹 …」一起消失。
    # ⚠ 「不传 `standard=`」是刻意的：`plane_subtitle()` 只有在收到非空 `standard` 时才追加它。
    hl_point = pool.point_of(std_entry) if req.show_baseline else None
    hl_label = f"基准弹 {std_entry.key}" if req.show_baseline else ""
    sub = (figures.plane_subtitle(req.scene, standard=std_entry.key) if req.show_baseline
           else figures.plane_subtitle(req.scene))
    if req.with_iso and lines:
        iso = IsoGrid(dv=g.dv, bc=g.bc, t_grid=t_grid)
        fig_paths = figures.plot_plane(
            points=pts, iso=iso, axis=axis,
            out_base=fig_dir / f"fig_isotime_plane_{req.tag}",
            title=figures.plane_title(with_iso=True),
            subtitle=sub,
            # ⚠ 用户 2026-10-04：坐标轴下方的批注**全部移出图外** ⇒ 这里不传 `footnotes=`
            # （文本出处见 `figures.plane_notes()`，供页面渲染）。
            iso_step=req.iso_step, colorbar=req.colorbar, formats=req.formats,
            highlight=hl_point, highlight_label=hl_label)
    else:
        fig_paths = figures.plot_plane(
            points=pts, iso=None, axis=axis,
            out_base=fig_dir / f"fig_isotime_plane_{req.tag}",
            title=figures.plane_title(with_iso=False),
            subtitle=sub,
            iso_step=req.iso_step, colorbar=False, formats=req.formats,
            highlight=hl_point, highlight_label=hl_label)
    if not req.show_baseline:
        say("--no-baseline：不画绿色基准弹（11 枚全红），副标题也不写基准弹")

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
    """第二张图（β–ginv = 1/γ 能力平面）的全部输入。**字段名即 CLI 参数名**。

    与 `PlaneRequest` 的两处根本差别：

    * **固定 ΔV**（`dv_pin`，默认取基准弹的权威 ΔV），扫的是 (β, ginv)；
      第一张图固定别的一切、扫 (ΔV, BC)。
    * 参考工况（`alt_m` / `speed_ms`）**只影响等 n* 线与派生指标**，
      β、ginv 本身是弹的固有量 —— 所以改它不会移动任何一个散点，只会移动那族直线。

    ⚠ 纵轴是 **ginv = 1/γ [m²/kg]**（用户 2026-10-04 口径）：两根轴同为"向上＝更好"。
    所以 `ginv_step` 是 1e-4 量级，不是旧 γ 步长的 1.0 量级；换算只在 `bg.ginv_of/gamma_of`。
    """

    scene: Scene = field(default_factory=Scene)
    env_preset: str = "default"              # 共享**环境**预设名（v4：环境/基准弹/参考工况的唯一来源）
    standard: str = "PL-12"
    missiles: tuple | list | None = None
    tier: str = "fast"
    jobs: int = 8
    cache: bool = True
    with_scan: bool = True
    beta_step: float = 30.0
    ginv_step: float = 0.0004                 # m²/kg；≈ 旧 γ 步长 2.0 kg/m²（在 γ≈70 处等价）
    iso_step: float = 1.0
    dv_pin: float | None = None              # None ⇒ 基准弹标称 ΔV
    n_ref: float = 20.0                      # R / β_eff 的参考过载
    alt_m: float | None = None               # None ⇒ 10 km（参考图口径）
    speed_ms: float | None = None            # None ⇒ 800 m/s
    xlim: tuple | None = None
    ylim: tuple | None = None
    tag: str = "default"
    formats: tuple = ("png", "pdf", "svg")
    #: **画法开关**，含义同 `PlaneRequest.show_baseline`：`False` ⇒ 11 枚全红、图例里没有
    #: 「基准弹 …」那一条。首页那份 `_static` 用它（"刚打开、没输入"时本来就没有基准弹可言）。
    #: ⚠ **绝不能进 `engine.cache_key()`**（画法不影响物理；扫描仍是同一条缓存）。
    show_baseline: bool = True
    figure_dir: Path | None = None
    result_dir: Path | None = None

    def check(self) -> list:
        bad = list(self.scene.check())
        if self.tier not in ("standard", "fast"):
            bad.append(f"tier 只能是 standard / fast，收到 {self.tier!r}")
        if self.beta_step <= 0 or self.ginv_step <= 0:
            bad.append("β/ginv 网格步长必须为正")
        if self.iso_step <= 0:
            bad.append("iso_step 必须为正")
        if self.n_ref <= 0:
            bad.append("参考过载必须为正")
        if self.dv_pin is not None and self.dv_pin <= 0:
            bad.append("固定 ΔV 必须为正")
        return bad


def run_bg(req: BgRequest, *, progress=None, log=None) -> dict:
    """跑第二张图的链路：β–ginv 固有量 → （可选）(β, ginv) 扫描 → 出图 → 产物。"""
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
        f"β={std_point.beta:.1f} ginv={std_point.ginv:.6f}（γ={std_point.gamma:.2f} kg/m²）"
        f" · 固定 ΔV={dv_pin:.2f} m/s")
    say(f"参考工况 {ref.alt_m / 1000:g} km / {ref.speed_ms:g} m/s → Ma {ref.mach:.3f}"
        f" · q={ref.q_pa:.1f} Pa · f={ref.f_mach:.5f} F={ref.cap_f:.5f}")

    # ---- ② 自适应轴（β 横轴 / ginv = 1/γ 纵轴）-------------------------
    # ⚠ 覆盖范围要**在算刻度之前**给进去：刻度必须跟着实际画的范围走（见 `figures.bg_axis`）。
    axis = figures.bg_axis(rows_, xlim=req.xlim, ylim=req.ylim)
    say(f"坐标轴 β {axis.xlim[0]:.0f}~{axis.xlim[1]:.0f}（主 {axis.x_major:g}）"
        f" · ginv {axis.ylim[0]:.4f}~{axis.ylim[1]:.4f}（主 {axis.y_major:g}）")

    # ---- ③ 扫描（可选）------------------------------------------------
    g = grid_mod.make_grid(axis.xlim, axis.ylim,
                           dv_step=req.beta_step, bc_step=req.ginv_step)
    shots, t_grid, lines, n_hit = [], None, [], 0
    backend = "not-run"
    if req.with_scan:
        say(f"网格 {g.shape[0]}×{g.shape[1]} = {g.n_cases} 工况"
            f"（β 步长 {req.beta_step:g} / ginv 步长 {req.ginv_step:g}，档位 {req.tier}）")
        eng = Engine(req.scene, missile=std_entry.native, tier=req.tier, jobs=req.jobs,
                     cache=req.cache, metrics=std_metrics, progress=progress,
                     scaling_of=lambda b, g_: bg.scaling_for(
                         std_point, std_metrics, beta=b, ginv=g_, dv=dv_pin))
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
    # 图内批注已按用户 2026-10-04 口径**全部移出图外** ⇒ 这里只组装文本，
    # 不再交给 `plot_bg_plane(footnotes=…)`。文本的**单一出处**在 `figures`：
    # `BG_FOOTNOTES`（口径）/ `BG_READ_NOTE`（读法）/ `bg_scan_def()`（仿真层是什么）/
    # `bg_scan_note()`（这一版跑没跑），页面直接取用；这里额外打印一遍免得信息丢在代码里。
    extra = [figures.bg_scan_def(dv_pin, user=bool(req.dv_pin))]
    if req.with_scan:
        extra.append(f"网格 {g.shape[0]}×{g.shape[1]}={g.n_cases} 工况，命中 {n_hit}/{g.n_cases}，"
                     f"等时线步长 {req.iso_step:g} s。β 步长 {req.beta_step:g}、"
                     f"ginv 步长 {req.ginv_step:g} m²/kg。")
        extra.append(figures.BG_READ_NOTE)
    else:
        extra.append(figures.bg_scan_note(False))
    for line in extra:
        say("（图外文本）" + line)
    fig_paths = figures.plot_bg_plane(
        rows=rows_, axis=axis, out_base=fig_dir / f"fig_bg_plane_{req.tag}",
        # `show_baseline=False` ⇒ 不传 highlight：11 枚全红、图例里没有「基准弹 …」
        highlight=std_entry.key if req.show_baseline else "",
        alt_m=req.alt_m, speed_ms=req.speed_ms,
        scan=(g.dv, g.bc, t_grid) if (req.with_scan and t_grid is not None) else None,
        formats=req.formats)

    # ---- ⑤ 产物 -------------------------------------------------------
    paths = {"figures": [str(p) for p in fig_paths],
             "points": str(record.write_bg_points_csv(rows_, res_dir / f"bg_{req.tag}_points.csv"))}
    if req.with_scan:
        paths["cases"] = str(record.write_bg_cases_csv(
            shots, g, res_dir / f"bg_{req.tag}_cases.csv",
            scaling_of=lambda b, g_: bg.scaling_for(
                std_point, std_metrics, beta=b, ginv=g_, dv=dv_pin)))
        paths["isolines"] = str(record.write_bg_isolines_csv(
            lines, res_dir / f"bg_{req.tag}_isolines.csv"))
    manifest = record.make_bg_manifest(
        scene=req.scene, standard=std_entry.key, standard_native=std_entry.native,
        tier=req.tier, solver_identity=solver.identity(), backend=backend,
        rows_=rows_, reference=ref, n=req.n_ref, beta_step=req.beta_step,
        ginv_step=req.ginv_step, iso_step=req.iso_step, dv_pin=dv_pin,
        grid=g if req.with_scan else None, n_hit=n_hit,
        elapsed_s=time.perf_counter() - t0, tag=req.tag)
    manifest["with_scan"] = bool(req.with_scan)
    manifest["iso_levels"] = [item["level"] for item in lines]
    manifest["missiles"] = [r.key for r in rows_]
    if t_grid is not None:
        manifest["t_hit_range_s"] = _range_of(t_grid)
        # 用户 2026-10-04 的口径落地处：β 与 ginv **都是"越大越好"**，所以两个方向的单调
        # 期望**一致**（都 decrease：横轴越大 ⇒ 越省 ⇒ 命中越早、t_hit 越小）。
        # 旧口径纵轴是 γ（越大越费），这里必须写 expect="increase" —— 反向演练就是把它改回去。
        manifest["monotonic_beta"] = grid_mod.monotonic_report(
            t_grid, g, axis=0, expect="decrease")
        manifest["monotonic_ginv"] = grid_mod.monotonic_report(
            t_grid, g, axis=1, expect="decrease")
    paths["manifest"] = str(record.write_json(res_dir / f"bg_{req.tag}.json", manifest))

    return {"rows": rows_, "axis": axis, "grid": g, "shots": shots, "t_grid": t_grid,
            "isolines": lines, "n_hit": n_hit, "manifest": manifest, "provenance": prov,
            "backend": backend, "standard": std_entry, "dv_pin": dv_pin,
            "reference": ref, "elapsed_s": manifest["elapsed_s"], "_paths": paths}


# ===================================================================== 图4：机动想定

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
    env_preset: str = "default"              # 共享**环境**预设名（v4：环境/基准弹/参考工况的唯一来源）
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
    t_beam_s: float | None = None            # 显式钉住开机时刻（复现用；None ⇒ 反求）
    tag: str = "default"
    formats: tuple = ("png", "pdf", "svg")
    figure_dir: Path | None = None
    result_dir: Path | None = None

    def check(self) -> list:
        from . import flightpath

        bad = list(self.scene.check())
        if self.scene.maneuvers:
            bad.append("图4 的目标运动由本请求编译，scene.maneuvers 必须留空"
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
            "standard": self.standard, "tier": self.tier, "env_preset": self.env_preset,
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
    """跑图4 沙盒的链路：反求开机 → 正式一遍 → 产物（**不出静态图**）。

    ⚠ 2026-10-03：输入阶段的"静态 3D 预览"（`preview=True` 那条捷径）**已删除** ——
    用户口径是"图4 的静态 3D 图不出了，只保留可交互沙盒即可"（`docs/UX-TARGET.md` §1）。
    现在本函数**只有一条路**：不解算就没有任何东西可看，想看航迹请走 `/fig4` 沙盒回放。

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
    say(f"基准弹 {entry.key}（{entry.native}）β={point.beta:.1f} ginv={point.ginv:.6f}"
        f"（γ={point.gamma:.2f} kg/m²）"
        f" · 开机距离 {lock / 1000:g} km（{'用户指定' if lock_user else 'blk guidance.lockDistance'}）")

    # ---- ② 第一遍：不含 39 腿，反求开机时刻 ----------------------------
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

    # ---- ③ 第二遍：正式工况 -------------------------------------------
    say(f"第二遍（正式工况）· 档位 {req.tier} · 39 指令 {t_react:.2f} s"
        f"（= 开机 {t_beam:.2f} + 反应 {req.react_delay_s:g}）")
    # `want_cpa` 默认开：命中工况会**多跑一次关引信的虚警解算**量真最近接近距离。
    # 不量的话 `min_separation_m` 恒等于引信半径（10 m），报出去会被读成"差 10 m 打中"（A5）。
    shot = solver.run(replace(req.scene, maneuvers=sch.maneuvers(duration_s=dur, dt=0.1)),
                      missile=entry.native, tier=req.tier, want_rows=True, want_cpa=True)
    if not shot.ok:
        raise ValueError(f"第二遍求解失败：{shot.error}")

    # ---- ④ 分段 / 节点 / "是否转完" ------------------------------------
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
    # 结局文案：命中报**真最近接近距离**（`cpa_m`，关引信复跑量的），未命中的
    # `min_separation_m` 本来就是脱靶量。命中时 `min_separation_m` 是引信半径，**不要报**。
    if shot.hit:
        cpa = shot.cpa_m
        # ⚠ 4 位小数：真 CPA 常在 1e-4~1e-3 m 量级，`:.2f`/`:.3f` 会把它抹成 "0.00 m"
        end = (f"命中 {shot.t_hit:.3f} s · 最近接近 {cpa:.4f} m" if math.isfinite(cpa)
               else f"命中 {shot.t_hit:.3f} s · 最近接近未量")
    else:
        end = f"未命中 {shot.min_separation_m:.0f} m"
    say(f"{note}；39 指令 {t_react:.2f} s；结局：{end}"
        f" · 耗时 {time.perf_counter() - t0:.1f} s")

    run = traj.TrajRun(scene=req.scene, schedule=sch, shot=shot, segments=segments,
                       marks=traj.build_marks(schedule=sch, segments=segments,
                                              anchor=anchor, shot=shot),
                       anchor=anchor, missile=entry.key, beta=point.beta,
                       gamma=point.gamma, rows=list(shot.rows), note=note)

    # ---- ⑤ 产物 -------------------------------------------------------
    # 图4 的静态成品图（`figures/fig_traj_default.*`）与输入阶段的 3D 预览
    # （`figures/fig_traj_preview_default.*`）**都已删**（用户口径 2026-10-03："图4 的静态 3D 图
    # 不出了，只保留可交互沙盒即可"）—— 所以这里既不出图、也不再拼那批"图上的脚注"：
    # 本函数只负责解算 + 落 `results/traj_<tag>_*.csv|json`（沙盒 `/fig4` 的数据源）。
    # `_paths["figures"]` 这个键**保留为空表**：页面/测试都按它取图，
    # 删键会让"没有图"与"字段忘了写"分不开。
    fig_paths = []
    res_dir = req.result_dir or RESULT_DIR
    backend = shot.backend
    prov = Provenance(tier=req.tier, backend=backend, solver=solver.identity(),
                      standard=entry.key, scene=req.scene.as_dict())

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
    # 图4 也把轴量带上（**保留** manifest 里的物理 `gamma`，两个都给）：沙盒页面显示
    # ginv，而出处链仍然是内核口径的 γ。换算是 `bg.ginv_of()`，不是页面/前端自己算。
    manifest["ginv"] = float(point.ginv)
    record.write_json(res_dir / f"traj_{req.tag}.json", manifest)

    return {"run": run, "schedule": sch, "shot": shot, "shot_pass1": shot1,
            "anchor": anchor, "segments": segments, "marks": run.marks,
            "manifest": manifest, "provenance": prov, "backend": backend,
            "standard": entry, "beta": point.beta, "gamma": point.gamma,
            "ginv": point.ginv,
            "lock_distance_m": lock, "t_beam_s": t_beam, "t_react_s": t_react,
            "elapsed_s": manifest["elapsed_s"], "_paths": paths}


# ===================================================================== 图3：β–γ–ΔV 三维散点


@dataclass
class Fig3Request:
    """第四张图（β–ginv–ΔV 交互式三维散点）的全部输入。**字段名即 CLI / JSON 的键**。

    与前三张图的根本差别：**图3 不出静态图**（它是一页手写 WebGL，见 `webui_static/fig3.*`），
    所以这里没有 `formats` / `figure_dir`；产物只有两份 —— `results/fig3_<tag>.json`
    （立方体 + 逐列拟合 + 判别量）与 `fig3_<tag>_cases.csv`（每工况一行）。

    网格默认（v4，**别再改语义**；纵轴自 2026-10-04 起是 ginv = 1/γ）：

    * `n_beta` / `n_ginv` = 7：β(=BC)、ginv **覆盖图2 的域**（`figures.bg_axis`，含端点）
      ⇒ ginv 因此**只在弹池内**（实测 0.010066~0.019594，弹池 0.010966~0.018694，
      对应 γ 51.04~99.35 / 53.49~91.19）；
    * `dv_lim` = **None（默认）⇒ 自适应**：ΔV 的区间由 `figures.fig3_axes()` 按当前弹池现算
      （与图1 的 `adaptive_axis()` 同口径；11 弹池 = 803.73~1116.28 m/s，只选一枚弹时收紧到
      该弹 ±12 m/s）。**不再有写死的 `[700, 1700]`**（用户 2026-10-04 口径：三根轴都要自适应）。
      要给绝对区间（复现旧图 / 试轴）就显式传 `dv_lim=(lo, hi)`；
    * `n_dv` = 11：ΔV 轴的点数（与 β/ginv 的 7 点一起决定按需立方体的 11×7×7 = 539 工况）；
    * `dv_pin` = 基准弹标称 ΔV（PL-12 = 932.5697 m/s）—— v4 起只作**参考标记**，不决定轴的位置。

    ⚠ `ref_alt_m` / `ref_speed_ms` 是**判别量**（`n*` / `R`）的参考工况，不是发射高度：
    它们沿用图2 的口径（默认 10 km / 800 m/s），所以两张图的等 `n*` 线可以对着看。
    名字上刻意与 `scene.alt_m` 不同 —— 撞名的后果是"改参考高度顺手改掉发射高度"（见 AGENTS.md）。

    ## 想定（工况）：默认就是图4 那套，但 **39 指令时刻固定**

    这些字段与 `TrajRequest` **同名同义**（CLI 上也复用 `--traj-*` 那组外部名），
    编译走 `workflow._traj_schedule()` —— 仓库里**唯一**一处调 `flightpath.crank_beam()` 的地方。
    唯一的差别：图4 是**每枚弹**按自己的导引头开机时刻 + 反应延迟反求 39 时刻，
    图3 要跨 11 枚弹比、必须有**共用工况**，所以 `t_react_s` 是**输入的固定值**（默认 35.0 s），
    它进产物、进界面文案、也进缓存键（通过 `scene.maneuvers`）。
    """

    scene: Scene = field(default_factory=Scene)
    env_preset: str = "default"              # 共享**环境**预设名（v4：环境/基准弹/参考工况的唯一来源）
    standard: str = "PL-12"
    missiles: tuple | list | None = None
    tier: str = "fast"
    jobs: int = 8
    cache: bool = True
    n_beta: int = 7
    n_ginv: int = 7
    dv_lim: tuple | None = None              # None ⇒ 三根轴全自适应（`figures.fig3_axes`）
    n_dv: int = 11
    dv_pin: float | None = None
    n_ref: float = 20.0
    ref_alt_m: float | None = None
    ref_speed_ms: float | None = None
    iso_step: float = 1.0                    # 等时面/等时线的层步长（整秒；与图1/图2 同一套定义）
    # ---- 想定（与 TrajRequest 同名；默认值也一致）----
    t_crank: float = 8.0
    crank_deg: float = 70.0
    crank_g: float = 9.0
    beam_deg: float = 90.0
    beam_g: float = 9.0
    react_delay_s: float = 1.0
    weave: bool = False
    weave_amp_deg: float = 4.0
    weave_hz: float = 0.1
    t_react_s: float = 35.0                  # ⚠ **固定**的 39 指令时刻（共用工况；图4 是每弹反求）
    tag: str = "default"
    result_dir: Path | None = None

    def check(self) -> list:
        bad = list(self.scene.check())
        if self.scene.maneuvers:
            bad.append("图3 的目标运动由本请求编译（crank→39），scene.maneuvers 必须留空")
        if self.tier not in ("standard", "fast"):
            bad.append(f"tier 只能是 standard / fast，收到 {self.tier!r}")
        if int(self.n_beta) < 2 or int(self.n_ginv) < 2:
            bad.append("β、γ 每根轴至少 2 个点")
        try:
            lo, hi = (float(self.dv_lim[0]), float(self.dv_lim[1]))
        except (TypeError, ValueError, IndexError):
            if self.dv_lim is not None:
                bad.append(f"dv_lim 必须是两个数或 None（自适应），收到 {self.dv_lim!r}")
        else:
            if not (hi > lo):
                bad.append(f"dv_lim 必须递增，收到 {self.dv_lim!r}")
        if int(self.n_dv) < 2:
            bad.append("ΔV 至少 2 个点")
        if self.dv_pin is not None and self.dv_pin <= 0:
            bad.append("ΔV 钉值必须为正")
        if self.n_ref <= 0:
            bad.append("参考过载 n_ref 必须为正")
        if not (float(self.iso_step) > 0):
            bad.append("等时面层步长 iso_step 必须为正")
        if not (float(self.t_react_s) > 0):
            bad.append("39 指令时刻 t_react_s 必须为正")
        from . import flightpath as _fp

        try:
            _fp.WeaveLeg(0.0, self.weave_amp_deg, self.weave_hz).check()
        except ValueError as exc:
            bad.append(str(exc))
        return bad

    def as_dict(self) -> dict:
        """落盘用的输入快照（**不含**路径）。"""
        return {
            "env_preset": self.env_preset, "standard": self.standard, "tier": self.tier,
            "n_beta": int(self.n_beta), "n_ginv": int(self.n_ginv),
            "dv_lim": ([float(self.dv_lim[0]), float(self.dv_lim[1])]
                       if self.dv_lim else None), "n_dv": int(self.n_dv),
            "dv_pin": self.dv_pin, "n_ref": self.n_ref,
            "ref_alt_m": self.ref_alt_m, "ref_speed_ms": self.ref_speed_ms,
            "iso_step": float(self.iso_step),
            "t_crank": self.t_crank, "crank_deg": self.crank_deg, "crank_g": self.crank_g,
            "beam_deg": self.beam_deg, "beam_g": self.beam_g,
            "react_delay_s": self.react_delay_s,
            "weave": ({"amp_deg": self.weave_amp_deg, "hz": self.weave_hz}
                      if self.weave else None),
            "t_react_s": float(self.t_react_s), "tag": self.tag,
        }


#: `--figure` / `figure=` 的别名表：**一个叫 `all` 的开关必须真的 all**（Lead 2026-10-03 裁决）。
#: `all` 曾经 = 图1+图2+图4（**不含图3**）—— 名字骗人：验收时用 `all` 会以为出了四块。
#: 现在它只是 `four` 的别名；CLI 与 WebUI 都走 `normalize_figure()`，不各自折叠一次。
FIGURE_ALIASES = {"all": "four"}


def normalize_figure(which: str | None) -> str:
    """`figure` 取值 → 真正要跑的那一个（别名只在这一处折叠）。留空 = 图1。"""
    name = str(which or "plane").strip().lower()
    return FIGURE_ALIASES.get(name, name)


def fig3_scene(req: Fig3Request) -> Scene:
    """`Fig3Request` → 内核要的 `Scene`（目标运动 = crank→39，**39 时刻固定**）。

    复用图4 的编译器（`_traj_schedule()`，唯一一处 `crank_beam()`）：把 `t_react_s` 折成
    `t_beam = t_react_s − react_delay_s` 再交给它，于是 `crank_beam()` 内部的
    `t_react = t_beam + react_delay_s` 正好还原成我们钉死的那个值。
    """
    t_req = TrajRequest(scene=req.scene, env_preset=req.env_preset, standard=req.standard,
                        tier=req.tier,
                        t_crank=req.t_crank, crank_deg=req.crank_deg, crank_g=req.crank_g,
                        beam_deg=req.beam_deg, beam_g=req.beam_g,
                        react_delay_s=req.react_delay_s, weave=req.weave,
                        weave_amp_deg=req.weave_amp_deg, weave_hz=req.weave_hz,
                        tag=req.tag)
    t_beam = float(req.t_react_s) - float(req.react_delay_s)
    if t_beam <= 0:
        raise ValueError("t_react_s 必须大于 react_delay_s（否则相当于让目标在发射前就转 39）")
    sch = _traj_schedule(t_req, t_beam=t_beam, speed_ms=float(req.scene.target_speed_ms),
                         weave_start_s=float(req.t_react_s))
    dur = float(req.scene.duration_s)
    return replace(req.scene, maneuvers=sch.maneuvers(duration_s=dur, dt=0.1))


def fig3_scene_text(req: Fig3Request, scene: Scene) -> str:
    """一行工况文案（进产物与页面）：**必须带"39 固定"那句**，免得被当成图4 的口径。"""
    n_legs = len(scene.maneuvers or ())
    first = float(scene.maneuvers[0][0]) if n_legs else 0.0
    return (f"工况：crank→39 · 39 @ {float(req.t_react_s):g} s（固定，共用工况；"
            f"图4 是按每枚弹的导引头开机 + 反应延迟反求）· "
            f"crank {req.t_crank:g} s / {req.crank_deg:g}° @ {req.crank_g:g}G · "
            f"转 39 {req.beam_deg:g}° @ {req.beam_g:g}G · 反应延迟 {req.react_delay_s:g} s · "
            f"{req.scene.range_m / 1000:g} km 迎头 · {req.scene.alt_m / 1000:g} km · "
            f"载机 {req.scene.vm0:g} m/s · 目标 {req.scene.target_speed_ms:g} m/s · "
            f"maneuvers {n_legs} 段（起于 t={first:g} s）")


def run_fig3(req: Fig3Request, *, progress=None, log=None) -> dict:
    """跑图3 的算核：11 弹 × (β,γ,ΔV) 网格 → 立方体 + 拟合 + 判别量 → 两份产物。

    返回里带 `figure="fig3"` 与 `_paths` —— 查看器数据层（`fig3.paths_of()`）就靠这两个键
    认领自己的产物，与图4 的约定一致。
    """
    from . import fig3scan

    bad = req.check()
    if bad:
        raise ValueError("输入不自洽：" + "；".join(bad))
    say = log or (lambda _m: None)
    entries = pool.resolve_many(req.missiles)
    scene = fig3_scene(req)                      # 想定在这里编译（39 固定），不是直接吃 req.scene
    say(fig3_scene_text(req, scene))
    say("数据源 = 每枚弹的标称三参数点（**只解 11 个工况**，不解任何立方体）")
    out = fig3scan.run_nominal(scene, entries=entries, tag=req.tag, standard=req.standard,
                               tier=req.tier, jobs=req.jobs, cache=req.cache,
                               n_beta=req.n_beta, n_ginv=req.n_ginv,
                               dv_lim=req.dv_lim, n_dv=req.n_dv, dv_pin=req.dv_pin,
                               iso_step=req.iso_step,
                               t_react_s=req.t_react_s,
                               t_react_note="39 @ %.1f s（固定，共用工况）" % float(req.t_react_s),
                               scene_text=fig3_scene_text(req, scene),
                               result_dir=req.result_dir,
                               progress=progress, log=say)
    rec = out["record"]
    say(f"产物：{out['paths']['record']}")
    say(f"产物：{out['paths']['cases']}")
    return {"figure": "fig3", "tag": req.tag, "tier": req.tier,
            "grid": out["grid"], "record": rec, "rows": out["rows"],
            "standard": out["standard"], "dv_pin": out["dv_pin"],
            "n_missiles": len(entries), "n_points": len(entries),
            "n_hit": rec["summary"]["n_hit"], "n_miss": rec["summary"]["n_miss"],
            "n_run": rec["summary"]["n_run"], "n_cached": rec["summary"]["n_cached"],
            "elapsed_s": out["elapsed_s"], "_paths": out["paths"]}


def fig3_context(req: Fig3Request):
    """按需立方体要的三件东西：`(scene, grid, standard_entry, entries)`（**唯一一处**）。

    CLI 的 `--fig3-cube`、WebUI 的后台扫描任务都走它 —— 两边的网格与想定必须逐位相同，
    否则缓存指纹会对不上（这对**是好事**：对不上就重算，而不是拿错立方体画面）。
    """
    from . import bg, fig3scan

    entries = pool.resolve_many(req.missiles)
    rows_ = bg.rows(entries or None)
    std_entry = pool.standard_entry(req.standard)
    scene = fig3_scene(req)
    pin = float(req.dv_pin) if req.dv_pin else float(pool.metrics_of(std_entry).dv)
    grid = fig3scan.grid_of(rows_, dv_pin=pin, n_beta=req.n_beta, n_ginv=req.n_ginv,
                            dv_lim=req.dv_lim, n_dv=req.n_dv)
    return scene, grid, std_entry, entries


def scan_fig3_cube(req: Fig3Request, missile: str, *, force: bool = False,
                   progress=None, log=None) -> dict:
    """**按需**扫一枚弹的立方体：命中缓存就直接返回，否则扫完写缓存。

    返回里 `read_hit=False` 表示这次**真扫了**（判据用它钉"第二次不再重算"）。
    """
    from . import fig3, fig3scan

    say = log or (lambda _m: None)
    scene, grid, std_entry, _entries = fig3_context(req)
    entry = pool.resolve(missile)
    if not force:
        blob = fig3scan.read_cube_or_none(scene, entry, grid=grid, tier=req.tier,
                                         result_dir=req.result_dir)
        if blob is not None:
            say(f"命中立方体缓存：{blob['_path']}（{blob['summary']['n_cases']} 工况 · "
                f"命中 {blob['summary']['n_hit']}）")
            return {"missile": entry.key, "cube": blob["_path"],
                    "cube_key": blob["cube_key"], "read_hit": True,
                    "n_hit": int(blob["summary"]["n_hit"]),
                    "n_cases": int(blob["summary"]["n_cases"]),
                    "elapsed_s": 0.0}
    layer = {"n_levels": int(fig3.LAYER_COUNT), "iso_step": float(req.iso_step),
             "min_cells": int(fig3.LAYER_MIN_CELLS), "min_tri": int(fig3.LAYER_MIN_TRI)}
    out = fig3scan.run_cube(scene, entry, grid=grid, tier=req.tier, jobs=req.jobs,
                            cache=req.cache, layer=layer, standard=std_entry,
                            result_dir=req.result_dir, log=say, progress=progress,
                            force=bool(force))
    return {"missile": entry.key, "cube": out["cube"], "cube_key": out["cube_key"],
            "read_hit": False, "n_hit": int(out["n_hit"]), "n_cases": int(out["n_cases"]),
            "elapsed_s": float(out["elapsed_s"])}

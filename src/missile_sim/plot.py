"""出图：散点（按命中时间着色）+ 2 s 步长等命中时间线、弹道对比、基准曲线。

字体：优先中文黑体，缺失时回退 DejaVu Sans（中文会显示为方框，但不会报错）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .config import (  # noqa: E402
    MissileConfig,
    ballistic_coefficient,
    cxk_for_bc,
    delta_v_equiv,
)
from .decide import STATUS_LABELS, STATUS_NAMES, ST_HIT  # noqa: E402
from .sim import BatchResult  # noqa: E402
from .sweep import SweepGrid  # noqa: E402

FIG_DIR = Path(__file__).resolve().parents[2] / "figures"

_CN_FONTS = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC", "DejaVu Sans"]


# --------------------------------------------------------------------- 共用视觉规格
# 交叉图（make_missile_bc_overlay.py）与工作流主图共用同一组轴范围/刻度与出图元数据，
# 保证两张图同规格、且同一份数据重跑字节一致（否则 git 里每次都是假 diff）。

CROSSPLOT_SPEC = {
    "xlim": (800.0, 1110.0),      # 总增速 ΔV [m/s]
    "ylim": (2450.0, 3850.0),     # 弹道系数 BC
    "x_major": 30.0, "x_minor": 10.0,
    "y_major": 100.0, "y_minor": 50.0,
}
SAVE_DPI = 300
SAVE_META = {
    "png": {"Software": None},
    "pdf": {"CreationDate": None, "ModDate": None},
    "svg": {"Date": None},
}


def apply_crossplot_spec(ax, *, xlim=None, ylim=None) -> None:
    """给坐标轴套上共用刻度规格；`xlim`/`ylim` 传 None 表示只在数据落在规格内时才收紧范围。"""
    from matplotlib.ticker import MultipleLocator

    s = CROSSPLOT_SPEC
    ax.xaxis.set_major_locator(MultipleLocator(s["x_major"]))
    ax.xaxis.set_minor_locator(MultipleLocator(s["x_minor"]))
    ax.yaxis.set_major_locator(MultipleLocator(s["y_major"]))
    ax.yaxis.set_minor_locator(MultipleLocator(s["y_minor"]))
    lo, hi = s["xlim"]
    if (xlim or (lo, hi)) == (lo, hi):
        cur = ax.get_xlim()
        if cur[0] >= lo - 1e-9 and cur[1] <= hi + 1e-9:
            ax.set_xlim(*s["xlim"])
    lo, hi = s["ylim"]
    if (ylim or (lo, hi)) == (lo, hi):
        cur = ax.get_ylim()
        if cur[0] >= lo - 1e-9 and cur[1] <= hi + 1e-9:
            ax.set_ylim(*s["ylim"])


def setup_style():
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = _CN_FONTS
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 160
    plt.rcParams["savefig.bbox"] = "tight"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.25


def _ensure_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def plot_sweep(
    res: BatchResult,
    grid: SweepGrid,
    t_grid: np.ndarray,
    cfg: MissileConfig,
    *,
    out: Path | None = None,
    show_cxk_axis: bool = True,
    iso_step: float = 2.0,
    title: str | None = None,
) -> Path:
    """主图：BC(ΔV) 散点按 t_hit 着色 + 等命中时间线。

    X 轴 = 弹道系数 BC（上行副轴给出等价的 CxK），Y 轴 = 总增速 ΔV。
    """
    setup_style()
    out = _ensure_dir(out or FIG_DIR / "fig_sweep_isotime.png")
    bc2d = np.meshgrid(grid.dv, grid.bc, indexing="ij")[1]
    bc_flat = bc2d.ravel()
    dv_flat = np.meshgrid(grid.dv, grid.bc, indexing="ij")[0].ravel()
    t_flat = t_grid.ravel()

    hit = res.status == ST_HIT
    fig, ax = plt.subplots(figsize=(9.6, 7.0))

    # --- 等时线（先画线，散点压在上面）
    finite = t_grid[np.isfinite(t_grid)]
    levels = []
    if finite.size:
        from .sweep import _iso_levels

        levels = _iso_levels(finite, iso_step)
        if levels:
            cs = ax.contour(grid.bc, grid.dv, t_grid, levels=levels, colors="k", linewidths=0.9, alpha=0.65)
            ax.clabel(cs, fmt="%.0f", fontsize=8, inline=True)

    # --- 散点
    sc = ax.scatter(
        bc_flat[hit],
        dv_flat[hit],
        c=t_flat[hit],
        s=46,
        cmap="viridis",
        edgecolors="white",
        linewidths=0.5,
        zorder=3,
        label="命中",
    )
    cbar = fig.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label("命中时间 t_hit [s]")

    # --- 未命中：灰色 X（不参与插值）
    miss = ~hit
    if miss.any():
        ax.scatter(
            bc_flat[miss],
            dv_flat[miss],
            marker="x",
            c="#9a9a9a",
            s=34,
            linewidths=1.1,
            zorder=4,
            label="未命中/超时",
        )

    # --- 基准点（AIM-120C5 原始数据：CxK=1.225）
    bc0 = ballistic_coefficient(cfg.drag.cxk, cfg)
    dv0 = delta_v_equiv(cfg)
    if grid.bc.min() <= bc0 <= grid.bc.max() and grid.dv.min() <= dv0 <= grid.dv.max():
        ax.scatter([bc0], [dv0], marker="*", s=260, c="red", edgecolors="white", linewidths=0.8,
                   zorder=5, label=f"AIM-120C5 原始参数\n(BC={bc0:.0f}, ΔV={dv0:.0f})")

    ax.set_xlabel("弹道系数 BC = m_end / (CxK · S_ref)   [kg/m²]")
    ax.set_ylabel("瞬时总增速 ΔV_total [m/s]")
    scen = (
        f"发射 {res.vm0:.0f} m/s，目标 {res.vt:.0f} m/s（{'迎头' if res.vt < 0 else ('尾追' if res.vt > 0 else '静止')}）"
        f"，高度 {res.alt / 1000:.1f} km"
        + (f"（目标 {res.target_alt / 1000:.1f} km）" if abs(res.target_alt - res.alt) > 1.0 else "")
        + f"，距离 {res.range0 / 1000:.0f} km，高抛 {res.theta_loft_deg:.0f}°，引信 {cfg.sim.hit_radius:.0f} m"
    )
    ax.set_title(
        (title + "\n" if title else "")
        + f"等命中时间线（步长 {iso_step:g} s）  |  {scen}",
        fontsize=10.5,
    )
    ax.legend(loc="upper right", fontsize=8.5, framealpha=0.9)

    if show_cxk_axis:
        def _bc_of_cxk(cx):
            cx = np.maximum(np.asarray(cx, dtype=float), 1e-6)
            return np.asarray(ballistic_coefficient(cx, cfg), dtype=float)

        def _cxk_of_bc(bc):
            bc = np.maximum(np.asarray(bc, dtype=float), 1e-3)
            return np.asarray(cxk_for_bc(bc, cfg), dtype=float)

        sec = ax.secondary_xaxis("top", functions=(_cxk_of_bc, _bc_of_cxk))
        sec.set_xlabel("等价零升阻力系数 CxK（BC 反解）")

    fig.text(
        0.01, -0.02,
        f"命中率 {hit.mean() * 100:.1f}%（{int(hit.sum())}/{len(res.status)}）；"
        "未命中点数以灰色 X 表示，等时线在未命中区域自动断开。"
        f"基准点：BC={bc0:.0f}（CxK={cfg.drag.cxk:.3f}）、ΔV={dv0:.0f} m/s。",
        fontsize=8.5, color="#444444",
    )
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_baseline_curve(
    res: BatchResult,
    cfg: MissileConfig,
    *,
    out: Path | None = None,
) -> Path:
    """固定基准 BC（CxK=1.225）时 t_hit 随 ΔV 的变化。"""
    setup_style()
    out = _ensure_dir(out or FIG_DIR / "fig_baseline_time.png")
    bc0 = ballistic_coefficient(cfg.drag.cxk, cfg)
    sel = np.isclose(res.bc, bc0, rtol=1e-6)
    if not sel.any():
        sel = np.isclose(res.bc, res.bc[np.argmin(np.abs(res.bc - bc0))])
    dv = res.dv_total[sel]
    th = res.t_hit[sel]
    order = np.argsort(dv)
    dv, th = dv[order], th[order]
    vimp = res.v_impact[sel][order]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.4))
    ax1.plot(dv, th, "o-", color="#1f77b4")
    for x, y in zip(dv, th):
        if np.isfinite(y):
            ax1.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, 6), fontsize=8, ha="center")
    ax1.plot([dv.min(), dv.max()], [0, 0], alpha=0)
    ax1.set_xlabel("ΔV_total [m/s]")
    ax1.set_ylabel("命中时间 t_hit [s]")
    ax1.set_title(f"命中时间 vs 总增速（BC={bc0:.0f}，CxK={cfg.drag.cxk:.3f}）")
    if not np.isfinite(th).all():
        nan_dv = dv[~np.isfinite(th)]
        ax1.axvspan(nan_dv.min(), nan_dv.max(), color="0.85", alpha=0.5, label="未命中")
        ax1.legend(fontsize=8.5)

    ax2.plot(dv, vimp, "s-", color="#d62728")
    ax2.set_xlabel("ΔV_total [m/s]")
    ax2.set_ylabel("命中点速度 [m/s]")
    ax2.set_title("命中点存速 vs 总增速")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_trajectories(
    traces: list,
    labels: list[str],
    cfg: MissileConfig,
    *,
    out: Path | None = None,
    title: str | None = None,
) -> Path:
    """弹道对比：h(x) 剖面 + V(t) + gamma(t)。"""
    setup_style()
    out = _ensure_dir(out or FIG_DIR / "fig_traj_compare.png")
    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.4))
    for tr, lab in zip(traces, labels):
        if tr is None or len(tr.t) == 0:
            continue
        axes[0].plot(tr.x / 1000.0, tr.h / 1000.0, label=lab, lw=1.4)
        axes[0].scatter([tr.x[0] / 1000.0], [tr.h[0] / 1000.0], s=14, marker="o")
        axes[1].plot(tr.t, tr.v, label=lab, lw=1.4)
        axes[2].plot(tr.t, np.degrees(tr.gamma), label=lab, lw=1.4)
    axes[0].set_xlabel("水平距离 x [km]")
    axes[0].set_ylabel("高度 h [km]")
    axes[0].set_title("弹道剖面")
    axes[1].set_xlabel("t [s]")
    axes[1].set_ylabel("速度 V [m/s]")
    axes[1].set_title("速度衰减")
    axes[2].set_xlabel("t [s]")
    axes[2].set_ylabel("速度方向角 γ [°]")
    axes[2].set_title("航向角（含高抛段）")
    for ax in axes:
        ax.legend(fontsize=8.5)
        ax.grid(alpha=0.25)
    scen = (
        f"发射 {cfg.scenario.vm0:.0f} m/s，目标 {cfg.scenario.vt:.0f} m/s，"
        f"高度 {cfg.scenario.alt / 1000:.0f} km，距离 {cfg.scenario.range / 1000:.0f} km"
    )
    fig.suptitle((title + "  |  " if title else "") + scen, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_loft_family(
    results_by_loft: dict,
    cfg: MissileConfig,
    *,
    out: Path | None = None,
) -> Path:
    """不同高抛角下的弹道对比（一图看懂高抛的作用）。"""
    setup_style()
    out = _ensure_dir(out or FIG_DIR / "fig_loft_family.png")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.0, 4.6))
    for loft, res in sorted(results_by_loft.items()):
        tr = res.trace
        if tr is None or len(tr.t) == 0:
            continue
        tag = f"高抛 {loft:g}°" + (f"  t_hit={res.t_hit:.1f}s" if res.hit else f"  {STATUS_NAMES[res.status]}")
        ax1.plot(tr.x / 1000.0, tr.h / 1000.0, lw=1.4, label=tag)
        ax2.plot(tr.t, tr.v, lw=1.4, label=tag)
    ax1.set_xlabel("水平距离 x [km]")
    ax1.set_ylabel("高度 h [km]")
    ax1.set_title("高抛角对弹道剖面的影响")
    ax2.set_xlabel("t [s]")
    ax2.set_ylabel("速度 V [m/s]")
    ax2.set_title("高抛角对存速的影响")
    for ax in (ax1, ax2):
        ax.legend(fontsize=8.5)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out

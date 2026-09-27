# -*- coding: utf-8 -*-
"""三段式架构第三部分：**绘图**——`aam_fit` 散点图 + 等时线叠加。

视觉规格的权威来源是 `E:\\WT\\War-Thunder-Datamine\\自动化分析\\aam_plot.py`
（它产出 `aam_fit.png`）与同目录 `skills/wt-aam-analysis/references/charts.md`：

    画布 12×6.8 @110dpi；PNG 另存 dpi=300；PDF/SVG 关时间戳
    轴范围 横 800~1110、纵 2450~3850（charts.md 的**收紧版**，与参考图一致）
    刻度 主 30/100、次 10/50；主网格 alpha .35 lw .8、次 alpha .18 lw .5、set_axisbelow
    点   #D32F2F 实心 s=70 白边 lw=0.9 zorder=4
    标签 #C62828 fontsize 9.5 bold + 灰细引线（点少时用固定偏移字典，不用 adjustText）

**唯一有意的偏离**：`aam_fit` 的线性拟合线 + R² 框 → 换成等时线 + 出处面板。
要保留拟合线用 `with_fit=True`。

三层分开导出（`axes/points/isotime`），每层可单独调用与单测；`plot_crossplot` 串起来。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402

from .plot import (  # noqa: E402
    CROSSPLOT_SPEC,
    LBL_COLOR,
    LBL_FONTSIZE,
    LBL_LEADER,
    MISSILE_LBL_OFFSETS,
    SAVE_DPI,
    SAVE_META,
    setup_style,
)
from .sweep import extract_isolines  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "figures"

# ---------------------------------------------------------------- 版式规格（勿随意改）
FIG_SIZE = (12.0, 6.8)
FIG_DPI = 110
AX_RECT = (0.075, 0.175, 0.822, 0.700)        # left, bottom, width, height（figure 坐标）
CAX_RECT = (0.905, AX_RECT[1], 0.013, AX_RECT[3])
AX_PX = (AX_RECT[2] * FIG_SIZE[0] * FIG_DPI, AX_RECT[3] * FIG_SIZE[1] * FIG_DPI)

BLUE = "#1F77B4"
GRAY = "#555555"
POINT_COLOR = "#D32F2F"
POINT_SIZE = 70.0
ISO_CMAP = LinearSegmentedColormap.from_list(
    "iso_time", ["#0A2A48", "#134E80", "#2472A4", "#3E93BE", "#5FB0CE"])
ISO_LW = 1.15
ISO_ALPHA = 0.95

# 脚注：行距固定，**起点由 x 轴标题的实际位置反推**（见 `xlabel_bottom_fig`），不写死坐标。
FOOTNOTE_DY = 0.036
FOOTNOTE_GAP = 0.030        # 第一行脚注顶部与 x 轴标题底边之间留的余量

DEFAULT_XLIM = CROSSPLOT_SPEC["xlim"]
DEFAULT_YLIM = CROSSPLOT_SPEC["ylim"]


# ---------------------------------------------------------------- 数据结构


@dataclass
class MissilePoint:
    """图上的一个弹点（真实型号，用 blkx 的权威 ΔV/BC）。"""

    label: str
    dv: float
    bc: float
    name: str = ""
    t_hit: float | None = None       # 本工况下该型的命中时间（要点标签带 t_hit 时用）
    hit: bool | None = None
    highlighted: bool = False        # 画一个空心环（如"当前基准"）
    meta: dict = field(default_factory=dict)


@dataclass
class IsoGrid:
    """等时线网格（ΔV × BC → t_hit）。"""

    dv: np.ndarray
    bc: np.ndarray
    t_grid: np.ndarray               # 形状 (len(dv), len(bc))

    @property
    def shape(self) -> tuple:
        return (len(self.dv), len(self.bc))

    def as_dict(self) -> dict:
        return {"dv_step": float(self.dv[1] - self.dv[0]) if len(self.dv) > 1 else None,
                "bc_step": float(self.bc[1] - self.bc[0]) if len(self.bc) > 1 else None,
                "n_dv": len(self.dv), "n_bc": len(self.bc)}


# ---------------------------------------------------------------- 轴（aam_fit 规格）


def make_figure(*, xlim=DEFAULT_XLIM, ylim=DEFAULT_YLIM, colorbar: bool = True):
    """建画布与主轴/色标轴（版式与 `aam_plot.py` 一致）。"""
    setup_style()
    fig = plt.figure(figsize=FIG_SIZE, dpi=FIG_DPI)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes(list(AX_RECT))
    cax = fig.add_axes(list(CAX_RECT)) if colorbar else None
    ax.set_xlabel(r"总增速 $\Delta V$  (m/s)", fontsize=12)
    ax.set_ylabel("简化弹道系数 (BC)", fontsize=12)
    ax.xaxis.set_major_locator(MultipleLocator(CROSSPLOT_SPEC["x_major"]))
    ax.xaxis.set_minor_locator(MultipleLocator(CROSSPLOT_SPEC["x_minor"]))
    ax.yaxis.set_major_locator(MultipleLocator(CROSSPLOT_SPEC["y_major"]))
    ax.yaxis.set_minor_locator(MultipleLocator(CROSSPLOT_SPEC["y_minor"]))
    ax.grid(True, which="major", alpha=0.35, linewidth=0.8)
    ax.grid(True, which="minor", alpha=0.18, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=9)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    return fig, ax, cax


def ax_size_px(ax) -> tuple:
    """主轴像素尺寸（线名沿边框回退定位要用）。"""
    bbox = ax.get_window_extent()
    return (bbox.width, bbox.height)


# ---------------------------------------------------------------- 点层


def plot_points(ax, points, *, offsets=None, with_leader: bool = True,
                fontsize: float = LBL_FONTSIZE, color: str = LBL_COLOR):
    """画弹点 + 标签 + 细引线。返回 (散点句柄, 标签列表)。

    点少（≤12）时刻意用**固定偏移字典**而不是 adjustText——后者力参数不稳会把标签推飞。
    `offsets=None` 时用 `plot.MISSILE_LBL_OFFSETS`。
    """
    pts = list(points)
    if not pts:
        return None, []
    offs = MISSILE_LBL_OFFSETS if offsets is None else offsets
    xs = [p.dv for p in pts]
    ys = [p.bc for p in pts]
    sc = ax.scatter(xs, ys, s=POINT_SIZE, c=POINT_COLOR, edgecolors="white",
                    linewidths=0.9, zorder=4)
    texts = []
    for p in pts:
        dx, dy = offs.get(p.label, (10, 10))
        ha = "right" if dx < -8 else ("left" if dx > 8 else "center")
        t = ax.annotate(p.label, xy=(p.dv, p.bc), xytext=(dx, dy),
                        textcoords="offset points", ha=ha, va="center",
                        fontsize=fontsize, color=color, fontweight="bold", zorder=6,
                        arrowprops=(dict(LBL_LEADER) if with_leader else None))
        texts.append(t)
    for p in pts:
        if p.highlighted:
            ax.scatter([p.dv], [p.bc], s=POINT_SIZE * 4.2, facecolors="none",
                       edgecolors=POINT_COLOR, linewidths=1.6, zorder=5)
    return sc, texts


# ---------------------------------------------------------------- 等时线层


def iso_levels(t_grid: np.ndarray, step: float) -> list:
    """等时线层级（只取落入数据范围的整步长值）。"""
    finite = np.asarray(t_grid)[np.isfinite(t_grid)]
    if finite.size == 0:
        return []
    lo, hi = float(finite.min()), float(finite.max())
    first = math.ceil((lo - 1e-9) / step) * step
    levels, x = [], first
    while x <= hi + 1e-9:
        levels.append(round(x, 6))
        x += step
    return levels


def _backoff_label_points(cs, keep, xlim, ylim, *, back_px: float = 54.0):
    """线名落点：从线段**出口端沿折线回退** `back_px` 像素。

    ⚠ 每层**必须**返回一个点：返回长度少于 `keep` 会让调用方的 `zip` 静默少标几条线
    （曾因此丢了一个线名）。退化线段（<2 点）就退回该层第一个可用点。
    """
    sx = (xlim[1] - xlim[0]) / AX_PX[0]
    sy = (ylim[1] - ylim[0]) / AX_PX[1]
    out = []
    for lv in keep:
        i = list(cs.levels).index(lv)
        segs = [s for s in cs.allsegs[i] if s is not None and len(s) >= 2]
        if not segs:
            out.append(None)
            continue
        seg = max(segs, key=len)
        acc, pt = 0.0, None
        for j in range(len(seg) - 1, 0, -1):
            x1, y1 = seg[j]
            x0, y0 = seg[j - 1]
            acc += math.hypot((x1 - x0) / sx, (y1 - y0) / sy)
            if acc >= back_px:
                pt = (float(x1), float(y1))
                break
        out.append(pt or (float(seg[0][0]), float(seg[0][1])))
    return out


def plot_isotime(ax, iso: IsoGrid, *, step: float = 1.0, cax=None,
                 colorbar: bool = True, label_every: float = 0.0,
                 label_fontsize: float = 9.0, levels=None):
    """画等时线（按命中时间着色）+ 色标 + 线名。返回 (contour 句柄, levels, 线名列表)。

    `label_every<=0` 时自动：线数 ≤24 每条都标，否则按步长的整数倍抽稀。
    """
    levels = list(levels) if levels is not None else iso_levels(iso.t_grid, step)
    if not levels:
        return None, [], []
    norm = Normalize(vmin=levels[0], vmax=levels[-1]) if len(levels) > 1 else None
    use_cbar = bool(colorbar and norm is not None and cax is not None)
    colors = [ISO_CMAP(norm(v)) for v in levels] if use_cbar else BLUE
    cs = ax.contour(iso.dv, iso.bc, np.asarray(iso.t_grid).T, levels=levels,
                    colors=colors, linewidths=ISO_LW, alpha=ISO_ALPHA, zorder=2)
    if use_cbar:
        sm = plt.cm.ScalarMappable(norm=norm, cmap=ISO_CMAP)
        sm.set_array([])
        cb = ax.figure.colorbar(sm, cax=cax)
        cb.set_label("命中时间 $t_{hit}$ [s]", fontsize=9.5, color=GRAY)
        cb.ax.yaxis.set_major_locator(MultipleLocator(5))
        cb.ax.yaxis.set_major_formatter(lambda v, _p: f"{v:g}")
        cb.ax.tick_params(labelsize=8.5)
        cb.outline.set_edgecolor("#BBBBBB")
    elif cax is not None:
        cax.set_visible(False)

    every = label_every
    if every <= 0:
        every = step if len(levels) <= 24 else step * math.ceil(len(levels) / 24.0)
    keep = [lv for lv in levels if abs(lv / every - round(lv / every)) < 1e-9] if every > 0 else []
    labels = []
    if keep:
        pts = _backoff_label_points(cs, keep, ax.get_xlim(), ax.get_ylim())
        for lv, pt in zip(keep, pts):
            if pt is None:            # 该层只擦到网格角点、形不成线段 ⇒ 宁可不标
                continue
            labels.append(ax.annotate(f"{lv:g} s", xy=pt, fontsize=label_fontsize,
                                      color=GRAY, ha="center", va="center",
                                      rotation=-36, zorder=7,
                                      bbox=dict(boxstyle="round,pad=0.12",
                                                facecolor="white", edgecolor="none",
                                                alpha=0.72)))
    return cs, levels, labels


# ---------------------------------------------------------------- 出处面板 / 脚注


def provenance_lines(prov: dict) -> list:
    """把 provenance 块压成图上要写的几行（**产物自描述**：谁算的 / 哪型弹 / 什么参数）。

    兼容两种输入：
      * `provenance.provenance()` 的完整块（有 `backend`/`standard`/`pro`）；
      * 扫描 manifest 本身（有 `calculator`/`standard`，没有 `backend` 字段）——
        档位名取 `calculator.model`；旧 manifest 没这个键，再退回"有 `elf_sha256` ⇒ pro"。

    ⚠ **步长必须按档位选**：新两档（standard / fast）跑的是引擎外层步长 `pro.dt`
    （求解器的客户端对象时钟 1/48 s）；`prov["dt"]` 是旧 Flash 的 `sim.dt`，两档根本不用它。
    写错这一格等于在图上报一个假步长 —— 而这张图存在的意义就是"谁算的、什么参数"。
    """
    if "backend" not in prov and "calculator" in prov:
        calc = prov.get("calculator") or {}
        kind = str(calc.get("kind") or calc.get("model") or "").strip().lower()
        if not kind:
            kind = "pro" if calc.get("elf_sha256") else "flash"
        prov = {"backend": kind, "standard": prov.get("standard") or {},
                "pro": calc, "dt": calc.get("dt")}
    std = prov.get("standard") or {}
    pro = prov.get("pro") or {}
    backend = str(prov.get("backend") or "?")
    name = std.get("name") or "无标准弹"
    hash_ = std.get("profile_hash")
    parts = [f"后端 {backend}", f"基准弹 {name}" + (f"#{hash_}" if hash_ else "")]
    if backend == "pro":
        dt = pro.get("dt", prov.get("dt_pro_s"))
        parts.append(f"原生步长 {dt:g} s" if isinstance(dt, (int, float)) else "原生")
    elif pro.get("dt") is not None:
        dt = pro["dt"]
        parts.append(f"步长 {dt:g} s" if isinstance(dt, (int, float)) else f"步长 {dt}")
    elif prov.get("dt") is not None:
        parts.append(f"dt {prov.get('dt')} s")
    if pro.get("observation_mode"):
        parts.append(f"观测 {pro['observation_mode']}")
    if backend == "pro" and pro.get("elf_sha256"):
        parts.append(f"ELF {str(pro['elf_sha256'])[:8]}")
    return [" · ".join(parts)]


def add_header(fig, *, title: str, subtitle: str = "", iso_step: float = 1.0,
               n_points: int = 0, extra: str = ""):
    """标题 / 副标题 / 图例三段式页眉。

    ⚠ 版式坑：标题若用 `ax.set_title(pad=…)`，会和副标题、图例抢同一块区域。
    这里统一用 figure 坐标手工排布（自上而下 **标题 → 副标题 → 图例**），互不重叠。
    """
    fig.text(0.5, 0.982, title, ha="center", va="top", fontsize=14, fontweight="bold")
    if subtitle:
        fig.text(0.5, 0.936, subtitle, ha="center", va="top", fontsize=10.5, color=GRAY)
    handles = [Line2D([], [], color=BLUE, lw=2.6, label=f"等命中时间线（步长 {iso_step:g} s）"),
               Line2D([], [], marker="o", linestyle="none", markersize=7.5,
                      markerfacecolor=POINT_COLOR, markeredgecolor="white",
                      label=f"最新版 blkx 弹值（{n_points} 型）")]
    if extra:
        handles.append(Line2D([], [], marker="o", linestyle="none", markersize=11,
                              markerfacecolor="none", markeredgecolor=POINT_COLOR,
                              markeredgewidth=1.6, label=extra))
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), frameon=False,
               fontsize=9.5, bbox_to_anchor=(0.5, 0.918), borderaxespad=0.0)


def add_legend(fig, *, iso_step: float, n_points: int, extra: str = ""):
    """兼容旧调用：只加图例（新代码请用 `add_header`）。"""
    add_header(fig, title="", subtitle="", iso_step=iso_step, n_points=n_points, extra=extra)


def xlabel_bottom_fig(ax, fig=None) -> float:
    """x 轴标题**底边**的 figure 坐标 y。

    手工排版时不要猜坐标：脚注起点必须由实际渲染结果反推，
    否则不同字号/填充下会压住标题（本项目踩过两次）。
    """
    fig = fig or ax.figure
    fig.canvas.draw()                                   # 让标题拿到真实包围盒
    bb = ax.xaxis.label.get_window_extent()
    return float(fig.transFigure.inverted().transform((bb.x0, bb.y0))[1])


def add_footnotes(fig, lines, *, y0: float, dy: float = FOOTNOTE_DY):
    """底部脚注（自上而下，`va='top'`）。`y0` 必须由 `xlabel_bottom_fig()` 反推。"""
    for i, line in enumerate(lines):
        fig.text(0.012, y0 - i * dy, line, fontsize=8.3, color="#444444", va="top")


def wrap_lines(text: str, *, width: int = 150) -> list:
    """按显示宽度粗切（中文字符算 2）——脚注太长会顶出画布。"""
    out, cur, w = [], "", 0
    for ch in str(text):
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > width:
            out.append(cur)
            cur, w = "", 0
        cur += ch
        w += cw
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- 顶层


def plot_crossplot(*, points, iso: IsoGrid, out_base, title: str,
                   subtitle: str = "", prov: dict | None = None,
                   iso_step: float = 1.0, iso_label_every: float = 0.0,
                   colorbar: bool = True, formats=("png", "pdf", "svg"),
                   footnotes=None, highlight_label: str = "",
                   with_fit: bool = False, fit_text: str = "") -> list:
    """出一张"aam_fit 版式 + 等时线"的图，写到 `out_base.<ext>`。返回落地路径列表。

    `with_fit=True` 时额外画线性拟合线（默认关：等时线才是主角）。
    """
    fig, ax, cax = make_figure(colorbar=colorbar)
    add_header(fig, title=title, subtitle=subtitle, iso_step=iso_step,
               n_points=len(points), extra=highlight_label)

    plot_isotime(ax, iso, step=iso_step, cax=cax, colorbar=colorbar,
                 label_every=iso_label_every)
    if with_fit and points:
        xs = np.array([p.dv for p in points], dtype=float)
        ys = np.array([p.bc for p in points], dtype=float)
        if len(xs) >= 2 and np.ptp(xs) > 0:
            coef = np.polyfit(xs, ys, 1)
            xf = np.linspace(xs.min() - 8, xs.max() + 8, 200)
            ax.plot(xf, np.polyval(coef, xf), "-", color=BLUE, lw=1.7, alpha=0.9, zorder=3)
            if fit_text:
                ax.text(0.975, 0.845, fit_text, transform=ax.transAxes, fontsize=10.5,
                        color=BLUE, ha="right", va="top", zorder=6)
    plot_points(ax, points, with_leader=True)
    # 脚注：从 x 轴标题实际底边往上留一段余量开始，逐行向下（不再写死坐标）
    top = xlabel_bottom_fig(ax, fig) - FOOTNOTE_GAP
    lines = []
    for ln in (footnotes or []):
        lines.extend(wrap_lines(ln))
    if prov:
        for ln in provenance_lines(prov):
            lines.extend(wrap_lines(ln))
    if lines:
        add_footnotes(fig, lines, y0=top)

    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in formats:
        ext = ext.strip().lower()
        if not ext:
            continue
        p = out_base.with_suffix("." + ext)
        fig.savefig(p, bbox_inches="tight", pad_inches=0.25,
                    dpi=(SAVE_DPI if ext == "png" else None),
                    metadata=SAVE_META.get(ext))
        if ext == "svg":
            from .plot import normalize_svg_ids
            normalize_svg_ids(p)
        paths.append(p)
    plt.close(fig)
    return paths


def isolated_curve(iso: IsoGrid, t_hit_level: float):
    """取某个命中时间等级的折线（诊断图/单测用）。返回 [(dv, bc), ...]。"""
    segs = extract_isolines(np.asarray(iso.t_grid), _GridAdapter(iso), levels=[t_hit_level])
    if not segs:
        return []
    return [(p[1], p[0]) for p in segs[0]["points"]]      # 内部是 (bc, dv, t) → (dv, bc)


class _GridAdapter:
    """`sweep.extract_isolines` 需要 `.dv/.bc` 属性，这里做最小适配。"""

    def __init__(self, iso: IsoGrid):
        self.dv = iso.dv
        self.bc = iso.bc

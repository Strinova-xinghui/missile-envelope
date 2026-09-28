# -*- coding: utf-8 -*-
"""**唯一出图处**：自适应轴的 (ΔV, BC) 散点 + 等命中时间线。

版式常量**照旧**（画布 12×6.8 @110 dpi、PNG 另存 300 dpi、`AX_RECT`、色标位置、字号、
网格、图例与脚注排版）。相对旧外壳改了两件事：

1. **轴范围由散点自适应**，不再写死 `800~1110 / 2450~3850`；跨度小时主刻度按 nice 序列
   下调，保证自选 1~2 型时轴仍然可读。
2. **图的全部文字都在本模块**（`plane_title()` / `plane_subtitle()` / `xlabel` / `ylabel` /
   图例 / 色标名）—— 编排层（`workflow.py`）只传数据，不再持有中文串。标题与副标题的
   `plot_plane(title=None, subtitle=None)` 缺省就是这两个 builder 的输出。

三格式（PNG/PDF/SVG）**字节可复现**：`SAVE_META` 关掉时间戳，`normalize_svg_ids()` 把
matplotlib 用内存地址生成的 SVG 元素 id 顺序化（否则每次重跑 git 里都是假 diff）。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402
import numpy as np                                                # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.lines import Line2D                               # noqa: E402
from matplotlib.ticker import MultipleLocator                     # noqa: E402

from .spec import AxisSpec, MissilePoint, Scene            # noqa: E402

# --------------------------------------------------------------------- 规范文案

#: 图标题（`with_iso` = 有没有等时线）。参考图的口径：**主动弹**、**总增速-弹道系数**。
TITLE_ISO = "主动弹 总增速-弹道系数 与 等命中时间线"
TITLE_POINTS = "主动弹 总增速-弹道系数 散点图"

#: 图例 / 轴 / 色标的固定文案（改文案只改这里，改版式才动下面的常量）。
LEGEND_ISO = "等命中时间线（步长 {step:g} s）"
LEGEND_POINTS = "最新版 blkx 弹值（{n} 型）"
XLABEL = "总增速 $\\Delta V$（m/s）"
YLABEL = "简化弹道系数（$BC$）"
CBAR_LABEL = "命中时间 $t_{hit}$ [s]"

# --------------------------------------------------------------------- 版式（照旧）

FIG_SIZE = (12.0, 6.8)
FIG_DPI = 110
SAVE_DPI = 300
AX_RECT = (0.075, 0.175, 0.822, 0.700)      # left, bottom, width, height（figure 坐标）
CAX_RECT = (0.905, 0.175, 0.013, 0.700)
AX_PX = (AX_RECT[2] * FIG_SIZE[0] * FIG_DPI, AX_RECT[3] * FIG_SIZE[1] * FIG_DPI)

BLUE = "#1F77B4"
GRAY = "#555555"
POINT_COLOR = "#D32F2F"
POINT_SIZE = 70.0
ISO_CMAP = LinearSegmentedColormap.from_list(
    "iso", ["#0A2A48", "#134E80", "#2472A4", "#3E93BE", "#5FB0CE"])
ISO_LW = 1.15
ISO_ALPHA = 0.95
FOOTNOTE_DY = 0.036
FOOTNOTE_GAP = 0.030
LABEL_ROTATION = -36.0
LABEL_BACK_PX = 54.0
MAX_LABELLED_LINES = 24

SAVE_META = {
    "png": {"Software": None},
    "pdf": {"CreationDate": None, "ModDate": None},
    "svg": {"Date": None},
}

_CN_FONTS = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC", "DejaVu Sans"]

# 11 型弹的点标签偏移（短名 → (dx, dy) 像素）。点少且要位置完全可控 ⇒ 固定偏移字典，
# **不用 adjustText**（力参数不稳时会把标签推飞）。
# ⚠ `120A` 是 ΔV 最小的一型，默认轴范围下它距左边界只有约 58 px；标签宽约 30 px，
# 原来的 (-34, -4) 会把左边缘推到轴外被裁掉（图上只剩 "600A"）。它右边到下一型有约 267 px，
# 所以放到右侧。改这张表后**必须重新出图并肉眼确认没有标签被轴裁**。
MISSILE_LBL_OFFSETS = {
    "AAM-4": (-6, 13), "120A": (14, -4), "120C": (10, -16), "120D": (-8, 15),
    "MICA": (0, 18), "PL-12": (-44, 0), "PL-12A": (10, -18),
    "R-Darter": (-16, 12), "Derby": (-40, -8), "R-77": (-34, -10), "R-77-1": (-72, 14),
}
LBL_COLOR = "#C62828"
LBL_FONTSIZE = 9.5
LBL_LEADER = dict(arrowstyle="-", color="#BBBBBB", lw=0.6, shrinkA=1, shrinkB=5)


def setup_style() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = _CN_FONTS
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 160
    plt.rcParams["savefig.bbox"] = "tight"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.25


# ---------------------------------------------------------------- 自适应轴


DEFAULT_XLIM = (800.0, 1110.0)
DEFAULT_YLIM = (2450.0, 3850.0)
DEFAULT_TICKS = {"x": (30.0, 10.0), "y": (100.0, 50.0)}
PAD_FRAC = 0.06
MIN_PAD = {"x": 12.0, "y": 60.0}


def _nice_tick(span: float, target: int = 6) -> float:
    """落在 [首选, 次选, …] × 10^k 上的"整"刻度，使主刻度条数接近 `target`。"""
    raw = max(float(span), 1e-9) / max(int(target), 1)
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= m * mag * (1 + 1e-9):
            return m * mag
    return 10.0 * mag


def _minor_for(major: float) -> float:
    return major / 5.0 if major / 5.0 >= 5e-3 else major / 2.0


def _one_axis(vals, axis: str) -> tuple:
    """一条轴：范围 + 主/次刻度。跨度够大就**照旧**用默认刻度，否则按 nice 下调。"""
    lo, hi = float(min(vals)), float(max(vals))
    pad = max((hi - lo) * PAD_FRAC, MIN_PAD[axis])
    a, b = lo - pad, hi + pad
    d_major, d_minor = DEFAULT_TICKS[axis]
    default_span = (DEFAULT_XLIM if axis == "x" else DEFAULT_YLIM)
    span0 = default_span[1] - default_span[0]
    if (b - a) >= 0.5 * span0:
        return (a, b), d_major, d_minor              # 与参考图同刻度：分辨率照旧
    major = _nice_tick(b - a, 6)
    return (a, b), major, _minor_for(major)


def adaptive_axis(points) -> AxisSpec:
    """散点 → 坐标轴。**范围由数据决定**（固定比例外扩），刻度必要时才下调。

    11 型默认算出 `xlim ≈ (804, 1116)` / `ylim ≈ (2500, 3751)`，主刻度仍是 30 / 100 ——
    与既有参考图一致；只选一型时轴会收紧到该点附近，刻度自动变细。
    """
    pts = list(points or ())
    if not pts:
        raise ValueError("自适应轴至少需要一个点")
    (x0, x1), xmaj, xmin = _one_axis([p.dv for p in pts], "x")
    (y0, y1), ymaj, ymin = _one_axis([p.bc for p in pts], "y")
    return AxisSpec(xlim=(round(x0, 3), round(x1, 3)), ylim=(round(y0, 3), round(y1, 3)),
                    x_major=xmaj, x_minor=xmin, y_major=ymaj, y_minor=ymin)


# ---------------------------------------------------------------- 画布


def make_figure(axis: AxisSpec, *, colorbar: bool = True):
    """建画布并套上轴规格。返回 `(fig, ax, cax)`；`cax` 在不带色标时为 None。"""
    fig = plt.figure(figsize=FIG_SIZE, dpi=FIG_DPI)
    ax = fig.add_axes(list(AX_RECT))
    cax = fig.add_axes(list(CAX_RECT)) if colorbar else None

    ax.set_xlim(*axis.xlim)
    ax.set_ylim(*axis.ylim)
    ax.xaxis.set_major_locator(MultipleLocator(axis.x_major))
    ax.xaxis.set_minor_locator(MultipleLocator(axis.x_minor))
    ax.yaxis.set_major_locator(MultipleLocator(axis.y_major))
    ax.yaxis.set_minor_locator(MultipleLocator(axis.y_minor))
    ax.set_axisbelow(True)
    ax.grid(which="major", alpha=0.35, lw=0.8)
    ax.grid(which="minor", alpha=0.18, lw=0.5)
    ax.set_xlabel(XLABEL, fontsize=12)
    ax.set_ylabel(YLABEL, fontsize=12)
    ax.tick_params(labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return fig, ax, cax


def ax_size_px(ax) -> tuple:
    bb = ax.get_window_extent()
    return (float(bb.width), float(bb.height))


# ---------------------------------------------------------------- 散点


def plot_points(ax, points, *, offsets: dict | None = None, with_leader: bool = True,
                fontsize: float = LBL_FONTSIZE, color: str = LBL_COLOR):
    """画弹点 + 标签（带细引线）。返回 `(scatter, texts)`。"""
    offs = dict(MISSILE_LBL_OFFSETS)
    if offsets:
        offs.update(offsets)
    pts = list(points or ())
    if not pts:
        return None, []
    sc = ax.scatter([p.dv for p in pts], [p.bc for p in pts], s=POINT_SIZE,
                    c=POINT_COLOR, edgecolors="white", linewidths=0.9, zorder=4)
    texts = []
    for p in pts:
        dx, dy = offs.get(p.key, offs.get(p.label, (10, 10)))
        ha = "right" if dx < -8 else ("left" if dx > 8 else "center")
        texts.append(ax.annotate(
            p.label, xy=(p.dv, p.bc), xytext=(dx, dy), textcoords="offset points",
            fontsize=fontsize, color=color, fontweight="bold", ha=ha, va="center",
            zorder=6, arrowprops=(LBL_LEADER if with_leader else None)))
    return sc, texts


def mark_highlight(ax, point, *, label: str = ""):
    """给某一型加空心环（默认用来标出**基准弹**）。没给 `label` 就用点自己的短名。"""
    if point is None:
        return None
    return ax.scatter([point.dv], [point.bc], s=POINT_SIZE * 4.2, facecolors="none",
                      edgecolors=GRAY, linewidths=1.6, zorder=5,
                      label=(label or point.label or None))


# ---------------------------------------------------------------- 等时线


def _backoff_label_points(cs, keep, xlim, ylim, *, back_px: float = LABEL_BACK_PX,
                          ax_px=AX_PX):
    """线名落点：从线段**出口端沿折线回退** `back_px` 像素。

    ⚠ 每层**必须**返回一个元素（`None` 表示该层退化）：少返回会让调用方的 `zip` 静默
    少标几条线 —— 旧实现曾因此丢过一个线名。
    """
    sx = (xlim[1] - xlim[0]) / ax_px[0]
    sy = (ylim[1] - ylim[0]) / ax_px[1]
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


def plot_isotime(ax, iso, *, step: float = 1.0, cax=None, colorbar: bool = True,
                 label_every: float = 0.0, label_fontsize: float = 9.0, levels=None):
    """画等时线（按命中时间着色）+ 色标 + 线名。返回 `(contour, levels, labels)`。"""
    from .grid import iso_levels as _levels

    lv = list(levels) if levels is not None else _levels(iso.t_grid, step)
    if not lv:
        return None, [], []
    norm = Normalize(vmin=lv[0], vmax=lv[-1]) if len(lv) > 1 else None
    use_cbar = bool(colorbar and norm is not None and cax is not None)
    colors = [ISO_CMAP(norm(v)) for v in lv] if use_cbar else BLUE
    cs = ax.contour(np.asarray(iso.dv, dtype=float), np.asarray(iso.bc, dtype=float),
                    np.asarray(iso.t_grid, dtype=float).T, levels=lv,
                    colors=colors, linewidths=ISO_LW, alpha=ISO_ALPHA, zorder=2)
    if use_cbar:
        sm = plt.cm.ScalarMappable(norm=norm, cmap=ISO_CMAP)
        sm.set_array([])
        cb = ax.figure.colorbar(sm, cax=cax)
        cb.set_label(CBAR_LABEL, fontsize=9.5, color=GRAY)
        cb.ax.yaxis.set_major_locator(MultipleLocator(5))
        cb.ax.yaxis.set_major_formatter(lambda v, _p: f"{v:g}")
        cb.ax.tick_params(labelsize=8.5)
        cb.outline.set_edgecolor("#BBBBBB")
    elif cax is not None:
        cax.set_visible(False)

    every = float(label_every)
    if every <= 0:
        every = float(step) if len(lv) <= MAX_LABELLED_LINES else \
            float(step) * math.ceil(len(lv) / float(MAX_LABELLED_LINES))
    keep = [v for v in lv if abs(v / every - round(v / every)) < 1e-9] if every > 0 else []
    labels = []
    if keep:
        pts = _backoff_label_points(cs, keep, ax.get_xlim(), ax.get_ylim(),
                                    ax_px=ax_size_px(ax))
        for v, pt in zip(keep, pts):
            if pt is None:
                continue
            labels.append(ax.annotate(
                f"{v:g} s", xy=pt, fontsize=label_fontsize, color=GRAY,
                ha="center", va="center", rotation=LABEL_ROTATION, zorder=7,
                bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                          edgecolor="none", alpha=0.72)))
    return cs, lv, labels


# ---------------------------------------------------------------- 题头 / 脚注


def plane_title(with_iso: bool = True) -> str:
    """图标题。`with_iso=False`（`--no-iso` 只出散点）时**不出现**「等命中时间线」。"""
    return TITLE_ISO if with_iso else TITLE_POINTS


def plane_subtitle(scene: Scene, *, standard: str = "", tier: str = "") -> str:
    """副标题：`场景 · 载机 · 敌机 · 基准弹 · 档位`，速度**一律写成"标量 + 航向"**。

    形如「50 km 迎头 · 高度 10.0 km · 载机 300 m/s 航向 0° · 敌机 300 m/s 航向 180°
    · 基准弹 PL-12」—— 措辞风格与 `Scene.describe()` 一致（同一个 `head_on` 判据、
    同一套"标量 + 航向/俯仰"写法），但**不重复斜距与 observation**（脚注里已有），
    俯仰只在非 0 时才写出来，免得默认工况的副标题被两个 `俯仰 0°` 撑长。

    ⚠ 不要退回旧口径的"带符号速度"（`300 / -300 m/s`）：新 `Scene` 里速度是标量，
    方向由航向/俯仰承载，符号写法既写不出 3D，也会被读成"敌机在倒着飞"。
    """
    kind = "迎头" if scene.head_on else "尾追/侧向"
    if abs(scene.target_bearing_deg) > 1e-9:
        # 方位不写出来，"50 km 迎头"会被读成"敌机就在正前方" —— 45° 时那明明是侧前方。
        kind = f"方位 {scene.target_bearing_deg:g}° {kind}"
    alt = f"{scene.alt_m / 1000:.1f} km"
    if abs(scene.target_alt - scene.alt_m) > 1e-9:
        alt += f" → {scene.target_alt / 1000:.1f} km"
    launch = f"载机 {scene.vm0:g} m/s 航向 {scene.launch_heading_deg:g}°"
    if abs(scene.launch_pitch_deg) > 1e-9:
        launch += f" 俯仰 {scene.launch_pitch_deg:g}°"
    target = (f"敌机 {scene.target_speed_ms:g} m/s "
              f"航向 {scene.target_heading_deg:g}°")
    if abs(scene.target_pitch_deg) > 1e-9:
        target += f" 俯仰 {scene.target_pitch_deg:g}°"
    parts = [f"{scene.range_m / 1000:g} km {kind}", f"高度 {alt}", launch, target]
    if standard:
        parts.append(f"基准弹 {standard}")
    if tier:
        parts.append(f"{tier} 档")
    return " · ".join(parts)


def add_header(fig, *, title: str, subtitle: str = "", iso_step: float = 1.0,
               n_points: int = 0, extra: str = "", highlight: str = "",
               with_iso: bool = True):
    handles = []
    if with_iso:
        handles.append(Line2D([], [], color=BLUE, lw=2.6,
                              label=LEGEND_ISO.format(step=iso_step)))
    handles.append(Line2D([], [], marker="o", color="none", markerfacecolor=POINT_COLOR,
                          markeredgecolor="white", markersize=7,
                          label=LEGEND_POINTS.format(n=n_points)))
    if highlight:
        handles.append(Line2D([], [], marker="o", color="none", markerfacecolor="none",
                              markeredgecolor=GRAY, markersize=9, markeredgewidth=1.6,
                              label=highlight))
    fig.text(0.5, 0.982, title, ha="center", va="top", fontsize=14, fontweight="bold")
    if subtitle:
        fig.text(0.5, 0.936, subtitle, ha="center", va="top", fontsize=10.5, color=GRAY)
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), frameon=False,
               fontsize=9.5, bbox_to_anchor=(0.5, 0.918), borderaxespad=0.0)
    if extra:
        fig.text(0.988, 0.918, extra, ha="right", va="center", fontsize=9, color=GRAY)


def xlabel_bottom_fig(ax, fig=None) -> float:
    """x 轴标题的底边（figure 坐标）—— 脚注从它往上推，不再猜坐标。"""
    fig = fig or ax.figure
    fig.canvas.draw()
    bb = ax.xaxis.label.get_window_extent()
    return float(bb.y0) / float(fig.bbox.height)


def wrap_lines(text: str, *, width: int = 150) -> list:
    """按显示宽度折行（中文算 2 列）。"""
    out, cur, cur_w = [], [], 0
    for ch in str(text):
        w = 2 if ord(ch) > 0x2E80 else 1
        if cur_w + w > width and cur:
            out.append("".join(cur))
            cur, cur_w = [], 0
        cur.append(ch)
        cur_w += w
    if cur:
        out.append("".join(cur))
    return out


def add_footnotes(fig, lines, *, y0: float, dy: float = FOOTNOTE_DY):
    y = float(y0)
    for i, line in enumerate(lines or ()):
        fig.text(0.012, y - i * dy, line, ha="left", va="top",
                 fontsize=8.3, color="#444444")


# ---------------------------------------------------------------- 可复现保存


def normalize_svg_ids(path) -> None:
    """把 matplotlib 写进 SVG 的随机元素 id 改成顺序 id（`m2cdfbf5598` → `id_00000`）。

    matplotlib 的 SVG 后端用 `id(obj)`（内存地址）当元素 id，前缀有 `m`（标记/路径）、
    `p`（裁剪路径）、`image`（内嵌位图）等，几何完全相同也会整篇变。
    正则写成"字母 + ≥5 位十六进制"，所以 `figure_1`/`line2d_1` 这类稳定 id 与颜色
    十六进制串都不会被误伤。写回时保持原行尾（`newline=""`）。
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    ids: list = []
    for m in re.finditer(r'\bid="([A-Za-z]+[0-9a-f]{5,})"', text):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    if not ids:
        return
    mapping = {old: f"id_{i:05d}" for i, old in enumerate(ids)}
    pat = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in ids) + r")\b")
    p.write_text(pat.sub(lambda m: mapping[m.group(0)], text), encoding="utf-8", newline="")


def save_formats(fig, out_base, *, formats=("png", "pdf", "svg")) -> list:
    """落盘三格式：PNG 用 300 dpi，PDF/SVG 关时间戳；SVG 之后顺序化元素 id。"""
    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for ext in formats:
        ext = str(ext).lower().lstrip(".")
        path = out_base.with_suffix("." + ext)
        fig.savefig(path, dpi=(SAVE_DPI if ext == "png" else None),
                    metadata=SAVE_META.get(ext), bbox_inches="tight",
                    pad_inches=0.25, facecolor="white")
        if ext == "svg":
            normalize_svg_ids(path)
        written.append(path)
    return written


# ---------------------------------------------------------------- 主入口


def plot_plane(*, points, iso, axis: AxisSpec, out_base, title: str | None = None,
               subtitle: str | None = None, scene: Scene | None = None,
               standard: str = "", tier: str = "", footnotes=(), iso_step: float = 1.0,
               colorbar: bool = True, formats=("png", "pdf", "svg"), highlight=None,
               highlight_label: str = "", iso_label_every: float = 0.0) -> list:
    """出图主入口：等时线（底）+ 散点（上）+ 题头 + 脚注，三格式字节可复现。

    `title` / `subtitle` 给 None 就用本模块的规范文案：标题回落到 `plane_title()`；
    副标题在给了 `scene` 时回落到 `plane_subtitle(scene, standard=…, tier=…)`。
    编排层因此只需要传**数据**（scene / 基准弹 / 档位），中文串只有本模块一处。
    """
    setup_style()
    with_iso = iso is not None
    head = str(title) if title else plane_title(with_iso=with_iso)
    sub = str(subtitle) if subtitle else (
        plane_subtitle(scene, standard=standard, tier=tier) if scene is not None else "")
    hl = str(highlight_label or "") or str(getattr(highlight, "label", "") or "")
    fig, ax, cax = make_figure(axis, colorbar=colorbar)
    try:
        if with_iso:
            plot_isotime(ax, iso, step=iso_step, cax=cax, colorbar=colorbar,
                         label_every=iso_label_every)
        plot_points(ax, points)
        if highlight is not None:
            mark_highlight(ax, highlight, label=hl)
        add_header(fig, title=head, subtitle=sub, iso_step=iso_step,
                   n_points=len(list(points or ())), highlight=hl, with_iso=with_iso)
        lines = []
        for line in (footnotes or ()):
            lines.extend(wrap_lines(line))
        if lines:
            y0 = xlabel_bottom_fig(ax, fig) - FOOTNOTE_GAP
            add_footnotes(fig, lines, y0=y0)
        return save_formats(fig, out_base, formats=formats)
    finally:
        plt.close(fig)


# --------------------------------------------------------------------- 图2：β–γ 能力平面

#: 象限阈值。照 `_recon/make_fig2_turn_energy.py` 的取法（那是对着 11 弹池目测定出来的）：
#: β ≥ 3250 且 γ ≤ 70 ⇒ 双优；β ≤ 3000 且 γ ≥ 85 ⇒ 双差。
#: ⚠ 换池子（比如只画一个子集）时这两个阈值不一定还合适，届时按新池重定。
BG_GOOD_BETA, BG_GOOD_GAMMA = 3250.0, 70.0
BG_BAD_BETA, BG_BAD_GAMMA = 3000.0, 85.0
BG_GOOD_FILL, BG_GOOD_EDGE = "#E8F5E9", "#2E7D32"
BG_BAD_FILL, BG_BAD_EDGE = "#FDECEA", "#C62828"
BG_GOOD_TEXT = "双优区（β 大 · γ 小）"
BG_BAD_TEXT = "双差区（β 小 · γ 大）"

#: 等 `n*` 线的默认图层（G）与线条样式。
BG_NSTAR_LEVELS = (14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0)
BG_NSTAR_COLOR = "#90A4AE"
BG_NSTAR_LS = (0, (5, 3))

#: 气泡面积范围（points²）。参考图用半径 6~14 px 线性映射到 ΔV 极值，这里等价地给面积。
BG_BUBBLE = (70.0, 470.0)

TITLE_BG = "两类存能能力平面：β（直飞保能） vs γ（转向损失）"
XLABEL_BG = "β　[kg/m²]　直飞保能 →（越大越好）"
YLABEL_BG = "γ　[kg/m²]　转向损失 →（越小越好）"
LEGEND_BG_NSTAR = "等 $n^*$ 线（{lo:g}~{hi:g} G，共 {n} 条）"
LEGEND_BG_BUBBLE = "气泡大小 ∝ 理想 ΔV"
LEGEND_BG_SCAN = "仿真等时线（固定 ΔV，扫 β×γ）"
CBAR_LABEL_BG = "命中时间 [s]"

#: ⚠ 脚注**不要写 `$...$`**：`wrap_lines()` 按显示宽度切行，会把一对 `$` 拆到两行，
#: mathtext 只见到落单的 `$` 就原样输出（第一版就是这么把公式打成了字面量）。
#: 图例里的数学可以留 —— 它短，不会被折行。
BG_FOOTNOTES = (
    "β = m燃尽/(SD·CxK)，SD = πd²/4 —— 与既有 BC 是同一个数，横轴即第一张图的纵轴。"
    "γ = m燃尽·SD·CxK·CxAoA/(SL²·CyK²)，SL = 0.3·d·L·wingAreaMult；SD/SL 直接取内核的 "
    "drag_area / lift_area，没有另造面积口径。",
    "等 n* 线：n* = q/(Q·g0)，Q = sqrt(β·γ·F(M)/f(M)) —— 机动损失恰好等于基础阻力损失的"
    "那个过载，数字越小机动越贵；因 γ ∝ 1/β，这族线是双曲线（不是直线）。",
    "F(M) = 3.247·[0.308+0.75·(f(M)−0.308)]，f(M) 为内核的零升阻力马赫修正；"
    "CxAoA / CyK 在 11 型 blk 里都没有，取内核兜底 9.0 / 2.2。",
)

#: 图2 的点标签偏移（与图1 的 `MISSILE_LBL_OFFSETS` 是两套 —— 两图的点分布完全不同）。
#: ⚠ 改这张表后必须重新出图，肉眼确认：没有标签撞象限角标、没有被轴裁掉。
BG_LBL_OFFSETS = {
    "AAM-4": (-56, 10), "120A": (-14, 15), "120C": (-50, 6), "120D": (11, 10),
    "MICA": (14, 2), "PL-12": (-48, -2), "PL-12A": (14, 6),
    "R-Darter": (14, 6), "Derby": (-12, -17), "R-77": (4, -19), "R-77-1": (13, 4),
}


def bg_axis(rows_, *, pad: float = 0.06) -> AxisSpec:
    """β–γ 的自适应轴。范围由数据定，刻度按 nice 序列下调。"""
    bs = [float(r.beta) for r in rows_]
    gs = [float(r.gamma) for r in rows_]
    if not bs or not gs:
        raise ValueError("bg_axis 需要至少一行数据")
    b0, b1, g0, g1 = min(bs), max(bs), min(gs), max(gs)
    # 边距给足：气泡最大半径不小，且左上/右下角各有一段象限角标文字要避开数据点。
    bp = max((b1 - b0) * pad, 60.0)
    gp = max((g1 - g0) * pad, 4.5)
    xlim, ylim = (b0 - bp, b1 + bp), (g0 - gp, g1 + gp)
    xmaj = _nice_tick(xlim[1] - xlim[0], target=5)
    ymaj = _nice_tick(ylim[1] - ylim[0], target=4)
    return AxisSpec(xlim=xlim, ylim=ylim, x_major=xmaj, x_minor=_minor_for(xmaj),
                    y_major=ymaj, y_minor=_minor_for(ymaj))


def bg_subtitle(*, alt_m: float, speed_ms: float, mach: float, q_pa: float,
                f_mach: float, cap_f: float, n: float) -> str:
    """图2 的副标题：**必须把参考工况写出来** —— `n*` 依赖动压，不写就没法比。"""
    return (f"参考工况 {alt_m / 1000:g} km / {speed_ms:g} m/s（Ma {mach:.2f}，"
            f"q {q_pa / 1000:.1f} kPa，f {f_mach:.4f}，F {cap_f:.4f}）"
            f" · 机动惩罚比 R 取 n = {n:g}G")


def _bg_quadrants(ax, axis: AxisSpec) -> None:
    """四象限底色。右下 = 双优，左上 = 双差。

    ⚠ **不在图内写角标文字**：左上角正好是等 `n*` 线族的标签落点（`n*=16` 就在那儿），
    图内文字必然打架。象限含义改由图例的两块色标承担（见 `add_bg_header`）。
    """
    from matplotlib.patches import Rectangle

    (x0, x1), (y0, y1) = axis.xlim, axis.ylim
    gx0, gy1 = max(BG_GOOD_BETA, x0), min(BG_GOOD_GAMMA, y1)
    if gx0 < x1 and gy1 > y0:
        ax.add_patch(Rectangle((gx0, y0), x1 - gx0, gy1 - y0, facecolor=BG_GOOD_FILL,
                               edgecolor="none", zorder=0))
    bx1, by0 = min(BG_BAD_BETA, x1), max(BG_BAD_GAMMA, y0)
    if x0 < bx1 and by0 < y1:
        ax.add_patch(Rectangle((x0, by0), bx1 - x0, y1 - by0, facecolor=BG_BAD_FILL,
                               edgecolor="none", zorder=0))


def _bg_nstar_lines(ax, axis: AxisSpec, levels, q_pa: float, f_mach: float,
                    cap_f: float) -> None:
    """等 `n*` 线族：`γ = (q/(n*·g0))²·(f/F)/β`，是双曲线。"""
    from . import bg as bgmod

    (x0, x1), (y0, y1) = axis.xlim, axis.ylim
    xs = np.linspace(x0, x1, 512)
    for nst in levels:
        k = (q_pa / (float(nst) * bgmod.G0)) ** 2 * (f_mach / cap_f)
        ax.plot(xs, k / xs, color=BG_NSTAR_COLOR, lw=1.0, ls=BG_NSTAR_LS, zorder=2)
        # 标签：曲线单调下降，从左边界或上边界进入，挑在范围内的那个锚点
        y_left = k / x0
        if y_left > y1:
            x_top = k / y1
            if x0 <= x_top <= x1:
                ax.text(x_top + (x1 - x0) * 0.006, y1 - (y1 - y0) * 0.022,
                        f"$n^*$={nst:g}", fontsize=9, color="#607D8B",
                        ha="left", va="top", zorder=3)
        elif y_left >= y0:
            ax.text(x0 + (x1 - x0) * 0.006, y_left + (y1 - y0) * 0.008,
                    f"$n^*$={nst:g}", fontsize=9, color="#607D8B",
                    ha="left", va="bottom", zorder=3)


def _bg_bubbles(ax, rows_, *, highlight: str = "") -> None:
    """散点 + 气泡（面积 ∝ ΔV）+ 标签引线 + 基准弹空心环。"""
    dvs = [float(r.dv) for r in rows_]
    d0, d1 = min(dvs), max(dvs)
    span = (d1 - d0) or 1.0
    lo, hi = BG_BUBBLE
    sizes = [lo + (float(r.dv) - d0) / span * (hi - lo) for r in rows_]
    ax.scatter([r.beta for r in rows_], [r.gamma for r in rows_], s=sizes, c=POINT_COLOR,
               alpha=0.75, edgecolors="white", linewidths=1.2, zorder=4)
    for r in rows_:
        dx, dy = BG_LBL_OFFSETS.get(r.key, (13, 4))
        ha = "right" if dx < -8 else ("left" if dx > 8 else "center")
        ax.annotate(r.label, xy=(r.beta, r.gamma), xytext=(dx, dy),
                    textcoords="offset points", fontsize=LBL_FONTSIZE, color=LBL_COLOR,
                    fontweight="bold", ha=ha, va="center", zorder=6,
                    arrowprops=LBL_LEADER)
    if highlight:
        hit = next((x for x in rows_ if x.key == highlight), None)
        if hit is not None:
            ax.scatter([hit.beta], [hit.gamma], s=BG_BUBBLE[1] * 1.45, facecolors="none",
                       edgecolors=GRAY, linewidths=1.6, zorder=5)


def add_bg_header(fig, *, title: str, subtitle: str = "", levels=BG_NSTAR_LEVELS,
                  highlight: str = "", with_scan: bool = False) -> None:
    """图2 的题头。图例条目与图1 不同（等 n* 线 + 气泡 + 象限色标），不复用 `add_header`。"""
    from matplotlib.patches import Patch

    lv = list(levels or ())
    handles = []
    if with_scan:
        handles.append(Line2D([], [], color=ISO_CMAP(0.75), lw=ISO_LW + 0.35,
                              label=LEGEND_BG_SCAN))
    handles.extend([
        Line2D([], [], color=BG_NSTAR_COLOR, lw=1.4, ls=BG_NSTAR_LS,
               label=LEGEND_BG_NSTAR.format(lo=min(lv), hi=max(lv), n=len(lv)) if lv
               else "等 $n^*$ 线"),
        Line2D([], [], marker="o", color="none", markerfacecolor=POINT_COLOR,
               markeredgecolor="white", markersize=7, label=LEGEND_BG_BUBBLE),
        Patch(facecolor=BG_GOOD_FILL, edgecolor=BG_GOOD_EDGE, lw=1.0, label=BG_GOOD_TEXT),
        Patch(facecolor=BG_BAD_FILL, edgecolor=BG_BAD_EDGE, lw=1.0, label=BG_BAD_TEXT),
    ])
    if highlight:
        handles.append(Line2D([], [], marker="o", color="none", markerfacecolor="none",
                              markeredgecolor=GRAY, markersize=9, markeredgewidth=1.6,
                              label=highlight))
    fig.text(0.5, 0.982, title, ha="center", va="top", fontsize=14, fontweight="bold")
    if subtitle:
        fig.text(0.5, 0.936, subtitle, ha="center", va="top", fontsize=10.5, color=GRAY)
    # 四条以上就分两行，免得横着挤出画布
    ncol = len(handles) if len(handles) <= 3 else 3
    fig.legend(handles=handles, loc="upper center", ncol=ncol, frameon=False,
               fontsize=9.5, bbox_to_anchor=(0.5, 0.918), borderaxespad=0.0,
               columnspacing=1.6, handletextpad=0.5)


def plot_bg_scan(ax, betas, gammas, t_grid, *, step: float = 1.0, cax=None,
                 colorbar: bool = True, levels=None) -> tuple:
    """**仿真层**：把基准弹的 ΔV 固定住，在 β–γ 网格上扫出来的命中时间等值线。

    与图1 的 `plot_isotime()` 同一个机制（同一套 `ISO_CMAP` / 线名回退标注），只是
    横纵坐标换成了 β/γ。返回 `(contour, levels, labels)`。
    """
    from .grid import iso_levels as _levels

    lv = list(levels) if levels is not None else _levels(t_grid, step)
    if not lv:
        return None, [], []
    norm = Normalize(vmin=lv[0], vmax=lv[-1]) if len(lv) > 1 else None
    use_cbar = bool(colorbar and norm is not None and cax is not None)
    colors = [ISO_CMAP(norm(v)) for v in lv] if use_cbar else BLUE
    cs = ax.contour(np.asarray(betas, dtype=float), np.asarray(gammas, dtype=float),
                    np.asarray(t_grid, dtype=float).T, levels=lv,
                    colors=colors, linewidths=ISO_LW + 0.35, alpha=ISO_ALPHA, zorder=2)
    if use_cbar:
        sm = plt.cm.ScalarMappable(norm=norm, cmap=ISO_CMAP)
        sm.set_array([])
        cb = ax.figure.colorbar(sm, cax=cax)
        cb.set_label(CBAR_LABEL_BG, fontsize=9.5, color=GRAY)
        cb.ax.yaxis.set_major_locator(MultipleLocator(1))
        cb.ax.yaxis.set_major_formatter(lambda v, _p: f"{v:g}")
        cb.ax.tick_params(labelsize=8.5)
        cb.outline.set_edgecolor("#BBBBBB")
    elif cax is not None:
        cax.set_visible(False)

    keep = [v for v in lv if abs(v / float(step) - round(v / float(step))) < 1e-9] \
        if step and step > 0 else list(lv)
    if len(keep) > MAX_LABELLED_LINES:
        keep = keep[::int(math.ceil(len(keep) / float(MAX_LABELLED_LINES)))]
    labels = []
    if keep:
        pts = _backoff_label_points(cs, keep, ax.get_xlim(), ax.get_ylim(),
                                   ax_px=ax_size_px(ax))
        for v, pt in zip(keep, pts):
            if pt is None:
                continue
            labels.append(ax.annotate(
                f"{v:g} s", xy=pt, fontsize=9.0, color="#0A2A48",
                ha="center", va="center", rotation=LABEL_ROTATION, zorder=7,
                bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                          edgecolor="none", alpha=0.72)))
    return cs, lv, labels


def plot_bg_plane(*, rows, out_base, axis: AxisSpec | None = None,
                  title: str | None = None, subtitle: str | None = None,
                  nstar_levels=BG_NSTAR_LEVELS, highlight: str = "",
                  footnotes=BG_FOOTNOTES, formats=("png", "pdf", "svg"),
                  alt_m=None, speed_ms=None, n: float = 20.0,
                  scan=None) -> list:
    """图2 主入口：四象限底 + 等 `n*` 线 + （可选）仿真等时线 + 气泡散点 + 题头 + 脚注。

    `rows` 是 `bg.BgRow` 序列（见 `bg.rows()`）。参考工况只在这里用于**画等值线**与写图注；
    β、γ 本身是弹的固有量，不随工况变。

    `scan` 给 `(betas, gammas, t_grid)` 时叠一层**仿真层**；不给就只有参考图那一套。
    """
    from . import bg as bgmod

    setup_style()
    rows_ = list(rows or ())
    if not rows_:
        raise ValueError("plot_bg_plane 需要至少一行数据")
    ax_spec = axis if axis is not None else bg_axis(rows_)
    alt, speed, mach, q_pa, f_mach, cap_f = bgmod.reference(alt_m, speed_ms)
    head = str(title) if title else TITLE_BG
    sub = str(subtitle) if subtitle else bg_subtitle(
        alt_m=alt, speed_ms=speed, mach=mach, q_pa=q_pa, f_mach=f_mach, cap_f=cap_f, n=n)
    fig, ax, cax = make_figure(ax_spec, colorbar=scan is not None)
    try:
        ax.set_xlabel(XLABEL_BG, fontsize=11.5)
        ax.set_ylabel(YLABEL_BG, fontsize=11.5)
        _bg_quadrants(ax, ax_spec)
        if scan is not None:
            betas, gammas, t_grid = scan
            plot_bg_scan(ax, betas, gammas, t_grid, cax=cax, colorbar=True)
        _bg_nstar_lines(ax, ax_spec, nstar_levels, q_pa, f_mach, cap_f)
        _bg_bubbles(ax, rows_, highlight=highlight)
        add_bg_header(fig, title=head, subtitle=sub, levels=nstar_levels,
                      highlight=highlight, with_scan=scan is not None)
        lines = []
        for line in (footnotes or ()):
            lines.extend(wrap_lines(line))
        if lines:
            y0 = xlabel_bottom_fig(ax, fig) - FOOTNOTE_GAP
            add_footnotes(fig, lines, y0=y0)
        return save_formats(fig, out_base, formats=formats)
    finally:
        plt.close(fig)

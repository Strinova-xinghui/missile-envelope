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
#: ⚠ 改这张表后必须重新出图，肉眼确认：没有标签互相压、没有被轴裁掉。
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
    # 边距给足：气泡最大半径不小，标签也往外伸，贴边会顶到轴线。
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
    """图2 的题头。图例条目与图1 不同（等 n* 线 + 气泡），不复用 `add_header`。"""
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
    """图2 主入口：等 `n*` 线 + （可选）仿真等时线 + 气泡散点 + 题头 + 脚注。

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


# ===================================================================== 图3：机动想定的轨迹
#
# 图1 / 图2 的**一个字节都不动**：这一段只**追加**新函数与新常量，不改上面任何行为。
# 节内的 import 放在这里也是同一个理由 —— 3D 与刻度定位器只有图3 用得上。

import matplotlib.patches as mpatches                       # noqa: E402
import matplotlib.ticker as mticker                         # noqa: E402
from mpl_toolkits.mplot3d import Axes3D                     # noqa: E402,F401

#: 版式。⚠ 俯视面板的位置与高度**不能写死**：等比例（`set_aspect("equal")`）下框的形状
#: 由 x/z 跨度之比决定，而这个比值很野 —— 纯直飞想定几乎是一条 x 方向的线（≈5:1），
#: 侧向拉开后回到 1:1 附近。写死矩形会让绘图区忽大忽小、图例与脚注跟着撞车。
#:
#: 两块面板**上下排**（俯视在上、高度–时间在下），两块都吃满画布宽度：
#: * 俯视框由 `_fit_box()` 现算，**上沿钉在 `TRAJ_TOP_H`**、从那里往下长，所以框顶永远
#:   ≤ `TRAJ_TOP_H` —— 图例挂在上面的固定高度就永远不会撞到框；
#: * 高度–时间面板在下、同样吃满宽度。侧置会跟俯视的 z 轴标题抢位置：俯视框的收缩方向
#:   随数据变，侧置面板在"扁框"工况（`trunc`）下会横跨进俯视区，而这是**静默**的
#:   （图上只是两层刻度叠在一起）。上下排没有这个问题。
TRAJ_FIG_SIZE = (12.6, 9.2)
TRAJ_FIG_DPI = 110
TRAJ_FIG_LEFT, TRAJ_FIG_RIGHT = 0.055, 0.985
TRAJ_TOP_H = 0.800                 # 俯视框的上沿，也是题头区（标题/副标题/图例）的下界
TRAJ_MAIN_BOTTOM = 0.415           # 俯视框下沿的下限：下面要放 x 轴标题
TRAJ_ALT_H = 0.205                 # 高度–时间面板高度
TRAJ_ALT_BOTTOM = 0.145            # 高度–时间面板下沿（下面留给刻度、轴标题、脚注）
TRAJ_INSET_MAX_H = 0.34            # 放大 inset 的高度上限（figure 坐标，约 3.1 in）——
                                   # 再高就顶到面板上沿；宽度由数据长宽比跟着定
TRAJ_INSET_MIN_W = 0.20            # 宽度下限：再窄放不下刻度与注记，画了也读不出来
TRAJ_INSET_MAX_W = 0.44            # 宽度上限：超过就快占满半个面板了
#: inset 数据窗口的外扩比例与"最小可读像素"（@`SAVE_DPI`）。
#: ⚠ `TRAJ_INSET_MIN_PX` 是**硬闸门**：最终框宽或框高低于它就把 inset 连同那一格图例一起撤掉
#: —— 图例不许承诺一个看不见的图元（旧版那根 6.9 px 宽的紫竖线正是这么留下来的）。
TRAJ_INSET_PAD_FRAC = 0.10
TRAJ_INSET_MIN_PX = 20.0
#: inset 标题的字号 / 与框顶的间距 / 占位矩形往外扩的余量（父轴 fraction）。
#: ⚠ 标题画在框**上方**，那块地方仍归主轴排版用 —— 占位矩形必须把"框 + 标题带"整块占掉，
#: 否则注记会紧贴框顶落下、正好压在标题上（实测 153.4 px²，而当时的断言全绿）。
TRAJ_INSET_TITLE_FONTSIZE = 8.2
TRAJ_INSET_TITLE_PAD_PT = 2.5
TRAJ_INSET_PAD_AX = 0.006
#: 放大框里刻度文字的字号与"一个刻度标签大概几个字符"（`44.2k` = 5 个）。
#: ⚠ 放大框在 300 dpi 上只有 137~163 px 宽（= 33~39 pt），**五个** 7 pt 的 `44.2k`
#: 就有 100 pt 宽 —— 实测互相压 11.9 display px（成品图上是 `44.144.244.3k` 一团糊）。
#: matplotlib 自己的 `get_tick_space()` 在这里给出 5 个，靠不住，得按框宽反算（看图才发现）。
TRAJ_INSET_TICK_FONTSIZE = 7.0
TRAJ_INSET_LABEL_CHARS = 5.0

TRAJ_TITLE = "机动目标想定轨迹：俯视 x–z + 高度–时间"
TRAJ_XLABEL = "x　[m]（航向 0° = +x）"
TRAJ_ZLABEL = "z　[m]（航向 90° = +z）"
TRAJ_ALT_XLABEL = "时间　t　[s]"
TRAJ_ALT_YLABEL = "高度 y　[m]"

#: `Segment.color_key` → 颜色。分段色直接取 `PathSchedule.segments()` 的 `color_key`，
#: 出图这一层**不另做时间算术** —— 两套口径必然漂移（计划 §3.2）。
TRAJ_COLORS = {
    "grey": "#7f7f7f",        # 直飞（迎头）
    "orange": "#ff7f0e",      # 转入 crank
    "red": "#d62728",         # crank 保持
    "teal": "#17becf",        # 转入 39
    "blue": "#1f77b4",        # 39 保持
}
TRAJ_FALLBACK_COLOR = "#333333"
TRAJ_MISSILE_COLOR = "#4d4d4d"
TRAJ_GUIDE_COLOR = "#2e7d32"
TRAJ_HIT_COLOR = "#d62728"
TRAJ_MISS_COLOR = "#8c564b"
TRAJ_ZOOM_COLOR = "#8e44ad"
TRAJ_SEG_LW = 2.3
TRAJ_MISSILE_LW = 1.05
TRAJ_MISSILE_LS = (0, (5, 3))
TRAJ_TRUNC_LS = (0, (4, 2))
TRAJ_MARK_COLOR = "#333333"
TRAJ_MARK_MS = 5.4

LEGEND_TRAJ_MISSILE = "导弹航迹"
LEGEND_TRAJ_GUIDE = "110° / 90° 参考方向"
#: ⚠ 文案必须与**画法**一致：被截断的段现在按 `TRAJ_TRUNC_LS` 画成虚线（见
#: `plot_traj_segments`），所以这里说"被下一条指令截断"；旧文案说"被压成一条弧"
#: 却配了一根实线 —— 图例与图是两套话。
LEGEND_TRAJ_TRUNC = "crank 没转完（被下一条指令截断）"
LEGEND_TRAJ_ZOOM = "放大：开机 → 转入 39"

#: 节点名 → 图例文案。**字典顺序即图例顺序**（同名节点只占一格）。
TRAJ_MARK_LABELS = {
    "launch": "发射",
    "crank_start": "开始 crank",
    "crank_done": "crank 转完",
    "seeker_on": "导引头开机",
    "beam_start": "开始转入 39",
    "end": "命中 / 结束",
}

#: 三个**特定**方位角的预设视角（预览要一眼看清"朝哪边转、在哪个平面摆"）。
AZIMUTH_PRESETS = {
    30.0: (24.0, -60.0),        # 斜视：默认
    0.0: (89.0, -90.0),         # 正俯视：与图3 主面板同视角
    180.0: (6.0, -90.0),        # 侧视：看 180° → 90° 的转向与高度
}


def _finite_xy(row, kx: str, kz: str):
    """取一行的 `(水平 x, 水平 z)`；缺值/非有限 ⇒ `None`（**不把 None 塞进 plot**）。"""
    x, z = row.get(kx), row.get(kz)
    if x is None or z is None:
        return None
    fx, fz = float(x), float(z)
    return (fx, fz) if math.isfinite(fx) and math.isfinite(fz) else None


def _target_xy(run) -> list:
    """目标航迹 `[(t, x, z)]`（按时间排序）。"""
    out = []
    for r in run.rows or ():
        t = r.get("t")
        if t is None:
            continue
        p = _finite_xy(r, "tx", "tz")
        if p is not None:
            out.append((float(t), p[0], p[1]))
    out.sort(key=lambda e: e[0])
    return out


def _missile_xy(run, *, t_end: float) -> list:
    """导弹航迹 `[(t, x, z)]`，**只取到 `t_end`**。

    ⚠ 命中点的位置**不走这里**（见 `plot_traj`）：`t_hit` 是**事件时刻**，
    可能落在时间栅格的两行之间，拿最近一行的位置顶上会静默偏几十米。
    """
    out = []
    for r in run.rows or ():
        t = r.get("t")
        if t is None:
            continue
        ft = float(t)
        if ft > t_end + 1e-9:
            continue
        p = _finite_xy(r, "x", "z")
        if p is not None:
            out.append((ft, p[0], p[1]))
    out.sort(key=lambda e: e[0])
    return out


def _span(lo: float, hi: float, *, frac: float = 0.08, floor: float) -> tuple:
    """一维外扩：按跨度取比例边距，但**至少** `floor` —— 退化成一条线时轴不能零宽。"""
    d = float(hi) - float(lo)
    pad = max(d * float(frac), float(floor))
    return (float(lo) - pad, float(hi) + pad)


def _heading_deg_at(rows, t_s: float):
    """目标在 `t_s` 时刻的**实际**航向（由轨迹位置差分现算：`atan2(dz, dx)`）。

    为什么从轨迹反算、而不查 `PathSchedule.heading_at()`：图上标的是"这一刻目标真的朝哪飞"，
    它必须与画出来的那条线**同源**（同一份行表）；查调度表拿到的是"指令"，
    在被下一条指令截断的转弯段上两者本来就不是同一个数。
    """
    before = after = None
    for r in rows:
        t = r.get("t")
        if t is None:
            continue
        ft = float(t)
        if ft <= t_s + 1e-9:
            before = (ft, _finite_xy(r, "tx", "tz"))
        else:
            after = (ft, _finite_xy(r, "tx", "tz"))
            break
    if not (before and after and before[1] and after[1]):
        return None
    dx = after[1][0] - before[1][0]
    dz = after[1][1] - before[1][1]
    if math.hypot(dx, dz) < 1e-9:
        return None
    return math.degrees(math.atan2(dz, dx)) % 360.0


def _angle_gap(a_deg: float, b_deg: float) -> float:
    """两个航向之间的夹角（0~180°，走最短路径 —— 与 `TurnLeg.delta_rad()` 同一口径）。"""
    return abs((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)


def _alt_series(run, key: str) -> list:
    """`(t, 高度)` 序列：`key="ty"` 是目标、`"y"` 是导弹。"""
    out = []
    for r in run.rows or ():
        t, y = r.get("t"), r.get(key)
        if t is None or y is None:
            continue
        fy = float(y)
        if math.isfinite(fy):
            out.append((float(t), fy))
    out.sort(key=lambda e: e[0])
    return out


def _target_at(track, t_s: float):
    """目标航迹上最接近 `t_s` 的点 `(x, z)`（就近取、不插值 —— 与"落在哪一行"同口径）。"""
    if not track:
        return None
    e = min(track, key=lambda r: abs(r[0] - t_s))
    return (e[1], e[2])


def _clock_label(deg: float) -> str:
    """航向的"点钟"读法（用户口径）：90° = 3 点、110° = 侧前方偏 20°。"""
    return f"{deg / 10.0:g} 点钟"


def _visible_marks(run) -> list:
    """只留 `t_s` 落在 `[0, t_end]` 内、时刻有限的节点（计划 §3.1）。"""
    t_end = float(run.t_end_s)
    out = []
    for m in run.marks or ():
        t = getattr(m, "t_s", None)
        if t is None:
            continue
        ft = float(t)
        if not math.isfinite(ft) or ft < -1e-9 or ft > t_end + 1e-9:
            continue
        out.append(m)
    return out


# ------------------------------------------------- 文字口径（节点名 / markdown / 宽度）

#: markdown 强调标记。matplotlib **不解析** markdown，`**x**` 会把星号原样打在图上。
_MD_MARKS = ("**", "__")


def _plain(text) -> str:
    """去掉 markdown 强调标记（不是解析）：`**一遍法**` → `一遍法`。

    ⚠ 为什么在**出图层**清洗、而不是去改 `workflow.py` 的文案：`run_traj` 注入的 note
    与 `footnotes=` 是**数据**，出图层不能假设它永远不带 markdown（第一版就是
    `_traj_footnotes()` 的 docstring 写着"不要写 `**`"，而调用方正好写了，图上就多出星号）。
    ⚠ 图1/图2 的脚注**故意不走这里** —— 它们的字节是已交付产物，且与图3 无关。
    """
    s = str(text or "")
    for mark in _MD_MARKS:
        s = s.replace(mark, "")
    return s


def _disp_width(text: str) -> int:
    """一行文字的显示宽度（中文/全角算 2 列）—— 与 `wrap_lines()` 同一口径。

    竖排（`rotation=90`）之后文字的**纵向**长度就靠这个量估：横向厚度只有约
    `1.3 × fontsize` 点，纵向却是"显示宽度 × 半个字号"，两者差一个数量级。
    """
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _mark_label(m, *, hit: bool | None = None) -> str:
    """节点在**图上**的文案。字典里的「命中 / 结束」只是图例名（一格管两种结局）。

    实际标注必须按结局二选一 —— 脱靶工况的注记写成「命中 / 结束」，读起来就是
    "命中了又结束"，是**误导**（verifier 的 D8）。
    """
    if getattr(m, "name", "") == "end" and hit is not None:
        return "命中" if hit else "结束"
    return TRAJ_MARK_LABELS.get(getattr(m, "name", ""), getattr(m, "name", ""))


def _mark_text(m, *, extra: str = "", hit: bool | None = None) -> str:
    """节点标注的**完整文案**：节点名只出现一次，`t=` 钉在节点名那一小段后面。

    `traj.build_marks()` 的 note 往往本身就以节点名开头（`开始 crank 至 110°（9G）`），
    旧版把图例前缀再拼一遍，同一句里节点名就出现两次（verifier 的 D3：
    `开始 crank t=8.00 s · 开始 crank 至 110°（9G）`）。口径：
    note 自带节点名 ⇒ 用 note 当主句、把 `t=` 插进去；否则才用图例名当主句。
    """
    lab = _mark_label(m, hit=hit)
    t = float(m.t_s)
    note = _plain(str(getattr(m, "note", "") or "")).strip()
    if note == lab:
        note = ""
    elif note.startswith(lab):
        head, sep, rest = note.partition(" · ")
        tail = f" · {rest}" if sep else ""
        if extra:
            tail += f" · {extra.lstrip(' ·')}"
        return f"{head} t={t:.2f} s{tail}"
    parts = [f"{lab} t={t:.2f} s"]
    if note:
        parts.append(note)
    if extra:
        parts.append(extra.lstrip(" ·"))
    return " · ".join(parts)


def plot_traj_segments(ax, run, *, t_window: tuple | None = None) -> list:
    """按 `Segment` 分段给**目标航迹**上色（图例用 `Segment.label`）。返回画过的段。

    ⚠ 分段只用 `run.segments` 的**时间区间**去切同一份行表 —— 绝不重新积分目标运动。
    自己积分出来的那条目标轨迹与求解器真正拦的那条不是同一条（见 `solver.trajectory()`），
    图上就会出现"目标明明躲开了却判命中"这种没法解释的偏差。

    ⚠ `truncated=True` 的段**必须画成 `TRAJ_TRUNC_LS` 虚线**：图例里那一格用的就是这个
    线型，而旧版只设 color/lw、段还是实线 —— 图例与图是两套话（verifier 的 D4）。
    """
    track = _target_xy(run)
    if not track:
        return []
    lo, hi = t_window if t_window else (track[0][0], track[-1][0])
    drawn, seen = [], set()
    for seg in run.segments or ():
        label = getattr(seg, "label", "") or ""
        if label in seen:
            continue
        t0, t1 = max(float(seg.t0_s), lo), min(float(seg.t1_s), hi)
        if t1 - t0 <= 1e-9:
            continue
        pts = [(e[1], e[2]) for e in track if t0 - 1e-9 <= e[0] <= t1 + 1e-9]
        if len(pts) < 2:
            continue
        ax.plot([p[0] for p in pts], [p[1] for p in pts],
                color=TRAJ_COLORS.get(getattr(seg, "color_key", ""), TRAJ_FALLBACK_COLOR),
                lw=TRAJ_SEG_LW, solid_capstyle="round", zorder=3, label=label,
                ls=(TRAJ_TRUNC_LS if getattr(seg, "truncated", False) else "-"))
        drawn.append(seg)
        seen.add(label)
    return drawn


def add_traj_header(fig, *, title: str, subtitle: str = "", segments=(), marks=(),
                    truncated: bool = False, zoom: bool = False, y: float = 0.888,
                    trunc_color: str | None = None) -> None:
    """图3 的题头。图例按**这张图真正画了什么**生成（没画的段不进图例）。

    `y` 由 `plot_traj` 现算：俯视框的高度随 x/z 跨度之比变，图例不能钉在一个固定高度上，
    否则扁框（纯直飞那种）会跟框顶撞在一起。
    `trunc_color` 是**真被截断那一段**的颜色：写死橙色的话，截断段换成别的阶段
    （例如 39 段被截）时图例的把手颜色就和图不一致了。
    """
    handles, seen = [], set()
    for s in segments:
        if s.label in seen:
            continue
        seen.add(s.label)
        if getattr(s, "truncated", False):
            # ⚠ 被截断的段在图上是**虚线**，那层意思由下面那格 `LEGEND_TRAJ_TRUNC` 专门解释；
            #   再给它挂一格**实线**代理就是"广告了图上不存在的图元"（复验 task-7 缺陷 A：
            #   `t_crank=28` 时图例有实线「转入crank」，而主轴唯一那段 crank 是橙虚线）。
            #   `plot_traj_segments` 同样按"label 首次出现"取线型，所以两边的取舍一致。
            continue
        handles.append(Line2D([], [], color=TRAJ_COLORS.get(s.color_key, TRAJ_FALLBACK_COLOR),
                              lw=TRAJ_SEG_LW, label=s.label))
    handles.append(Line2D([], [], color=TRAJ_GUIDE_COLOR, lw=0.9, ls=(0, (6, 4)),
                          label=LEGEND_TRAJ_GUIDE))
    handles.append(Line2D([], [], color=TRAJ_MISSILE_COLOR, lw=TRAJ_MISSILE_LW,
                          ls=TRAJ_MISSILE_LS, label=LEGEND_TRAJ_MISSILE))
    used = {getattr(m, "name", "") for m in marks}
    for nm, lab in TRAJ_MARK_LABELS.items():
        if nm in used:
            handles.append(Line2D([], [], color="none", marker="o", markersize=6,
                                  markerfacecolor=TRAJ_MARK_COLOR, markeredgecolor="white",
                                  label=lab))
    if zoom:
        handles.append(Line2D([], [], color="none", marker="s", markersize=6,
                              markerfacecolor="none", markeredgecolor=TRAJ_ZOOM_COLOR,
                              label=LEGEND_TRAJ_ZOOM))
    if truncated:                    # ⚠ 单列一格：它不是错误输入，是这个想定的结局
        handles.append(Line2D([], [], color=trunc_color or TRAJ_COLORS["orange"],
                              lw=TRAJ_SEG_LW, ls=TRAJ_TRUNC_LS, label=LEGEND_TRAJ_TRUNC))
    fig.text(0.5, 0.985, title, ha="center", va="top", fontsize=14, fontweight="bold")
    if subtitle:
        fig.text(0.5, 0.941, subtitle, ha="center", va="top", fontsize=10.0, color=GRAY)
    fig.legend(handles=handles, loc="upper center", ncol=min(5, max(1, len(handles))),
               frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, y),
               borderaxespad=0.0, columnspacing=1.1, handletextpad=0.4)


def _traj_subtitle(run) -> str:
    """图3 副标题：工况（range/alt/速度/航向）+ 该弹 (β, γ)。**必须两行给全**。"""
    sc = run.scene
    line1 = (f"工况 {sc.range_m / 1000:g} km · 高度 {sc.alt_m / 1000:.1f} km "
             f"· 载机 {sc.vm0:g} m/s 航向 {sc.launch_heading_deg:g}° "
             f"· 敌机 {sc.target_speed_ms:g} m/s 航向 {sc.target_heading_deg:g}°")
    line2 = f"{run.missile or '基准弹'} β = {run.beta:.0f} / γ = {run.gamma:.1f} kg/m²"
    wp = getattr(run.schedule, "weave", None)
    if wp is not None:
        line2 += f" · 震荡 ±{wp.amp_deg:g}° @ {wp.hz:g} Hz（{wp.start_s:g} s 起）"
    else:
        line2 += " · 震荡未开启"
    return line1 + "\n" + line2


def _react_delay_text(run) -> str:
    """把 `react_delay_s` 写成脚注里的一句话（它是可复核的输入量，不能只活在代码里）。"""
    legs = {leg.phase: leg for leg in (run.schedule.legs or ())}
    beam, t_beam = legs.get("beam"), (run.anchor or {}).get("t_beam_s")
    if beam is None or t_beam is None:
        return "不适用（没有 39 指令，或没反求出开机时刻）"
    d = float(beam.at_s) - float(t_beam)
    return f"{'+' if d >= 0 else '−'}{abs(d):g} s"


def _traj_footnotes(run, *, truncated: bool, extend_to: float, t_hit) -> list:
    """图3 的脚注（讲**为什么这样画**，不复述参数）；`footnotes=` 的行接在后面。

    ⚠ 刻意写短：扁框（纯直飞那种）留给脚注的竖向空间反而不多，长段落会顶出画布 ——
    `bbox_inches="tight"` 时看不出来，页面上就是字被切掉。
    ⚠ 也**不要写 `**`**：matplotlib 不解析 markdown，它会把星号原样打出来（图1/图2 的脚注
    同样只用「」和中文标点做强调）。⚠ 强调符号只用 `※`（U+203B）：`⚠`(U+26A0) 在
    Microsoft YaHei 里**没有字形**，出图时会刷 `Glyph 9888 missing from font` 并在
    PNG 上留一个豆腐块（实测 1 条 warning）；`※` 实测 0 条。
    """
    cmd = "；".join(f"{float(leg.at_s):g} s → 航向 {leg.heading_deg:g}°"
                    f"（{leg.turn_g:g}G，{leg.turn}）" for leg in (run.schedule.legs or ()))
    out = [f"航向指令：{cmd or '无（全程直飞）'}；分段直接折自 PathSchedule.table() 的常值 ω 表，"
           "出图这一层不另做时间算术。"]
    if truncated:
        out.append("※ 有一段转弯没转完就被下一条指令截断（图中那条橙色虚线）—— 那是"
                   "「实战中没做成 39 干扰」的结局，不是错误输入：它让 crank 角取 "
                   "60°/70°/80° 给出完全相同的结果。")
    out.append("俯视面板必须等比例：不等比例时 110° 与 90° 看起来一样，"
               "「crank 比 39 偏 20°」这个结论就错了。震荡是俯仰方向的（y 向），"
               "俯视图只看得见它带来的水平摆动，竖向幅度要在下方高度–时间面板上读。")
    out.append(f"「开始转入 39」相对「导引头开机」滞后 {_react_delay_text(run)}"
               "（RWR 告警 → 人的反应时间），所以两个节点必须分开标："
               "延迟期间目标仍按当时的航向飞。")
    if t_hit is not None:
        out.append(f"命中点取 t_hit = {float(t_hit):.3f} s 那一行的位置：事件时刻未必落在"
                   "时间栅格上，拿最近栅格点顶上会静默偏几十米。")
    elif extend_to > 0:
        out.append(f"未命中：轨迹一直画到求解器给的 t_end = {extend_to:.3f} s（脱靶 / lifetime），"
                   "坐标范围按实际画出的数据裁，不是按想定时长。")
    return out


def _zoom_window(run, *, t_end: float):
    """「开机 → 转入 39 那一下」的时间窗。

    ⚠ 窗口要卡住**真正转向**的那一段。转弯在时间轴上的位置取决于 `t_beam` 与 crank 排期谁先到
    （`t_react > t_crank` 时 crank 被截断），按"开机后 x 秒"拍脑袋很容易只框到一条直飞段，
    于是放大图里什么都看不出来 —— 而 inset 照样画、标题照样写时间，**是静默的**。
    这里的口径：从开机前一点起，盖住 beam 相位的那条**转弯段**；段边界由 `segments()` 给
    （它按 `t_react` 截断过，比拿 `TurnLeg` 重新算时长可靠），取不到再退回 `TurnLeg` 现算。
    """
    rows = [r for r in (run.rows or ()) if r.get("t") is not None]
    legs = {leg.phase: leg for leg in (run.schedule.legs or ())}
    beam, t_beam = legs.get("beam"), (run.anchor or {}).get("t_beam_s")
    if beam is None or t_beam is None or not math.isfinite(float(t_beam)):
        return None
    t_beam = float(t_beam)
    t0 = max(0.0, t_beam - 1.0)
    t1 = None
    for seg in (run.segments or ()):
        if seg.phase != "beam" or not math.isfinite(float(seg.t1_s)):
            continue
        if float(seg.t0_s) - 1e-6 <= t_beam <= float(seg.t1_s) + 1e-6:
            t1 = float(seg.t1_s)          # 这条段就是"转入 39"那一段
            break
    if t1 is None:
        # 段表给不出（调度的 t1 是 inf / 相位缺失）：用转弯指令自己算耗时，ω = n·g0/v
        speed = max(float(getattr(run.schedule, "speed_ms", 0.0) or 0.0), 1e-6)
        omega = max(float(beam.turn_g) * 9.80665 / speed, 1e-9)
        h0 = _heading_deg_at(rows, t_beam)
        gap = _angle_gap(h0, float(beam.heading_deg)) if h0 is not None else 20.0
        t1 = min(float(t_end), t_beam + gap / math.degrees(omega))
    t1 = min(float(t_end), t1 + 0.2 * max(t1 - t0, 0.5))   # 尾巴留一点，看得到转入之后
    return (t0, t1) if t1 - t0 > 0.4 else None


def _aspect_box(ax, rect) -> tuple:
    """等比例面板**真正**落在哪儿（figure 坐标）。

    `set_aspect("equal", adjustable="box")` 会把 axes 收缩成数据跨度比那个形状，
    收缩方向随数据变（纯直飞是横向的、拉起后接近正方）。旁边那条高度–时间面板必须挂在
    **实际**框的右侧：按名义矩形算的话，扁框时它会横跨进俯视区（`trunc` 那种工况，
    连高度轴标题都被压在俯视图上），而这是**静默**的 —— 图上只是"两层刻度叠在一起"。

    ⚠ 必须自己调 `apply_aspect()`：matplotlib 为了省事把这一步**推迟到渲染时**，
    在那之前 `get_position()` 返回的还是设定值（`draw()` 也不会提前结算它）——
    照那个值排版就是上面那个静默错。
    """
    ax.apply_aspect()
    return ax.get_position().bounds


def _fit_box(xlim, zlim, *, max_w: float, top: float, bottom: float,
             fig_w: float, fig_h: float) -> tuple:
    """等比例俯视框的 `(left, bottom, width, height)`（figure 坐标），由数据跨度现算。

    ⚠ 为什么不能写死：`set_aspect("equal")` 会把两个方向按**数据跨度比**一起缩放，
    写死的矩形于是被改成"居中留白"的样子 —— 面板看着还行，fig 层面的图例/脚注/副面板
    却按原矩形排，必然撞车。先把框算对，后面所有定位都以它为准。

    框**上沿钉在 `top`**、从那里往下长，高度不超过 `top - bottom`：
    扁框（纯直飞那种）于是贴着上沿，图例挂在上面的固定高度就永远不会撞到框；
    而"最胖"的框也不会长到副面板头上（`_fit_box` 一开始漏了这条下限，
    结果俯视框直接盖住高度–时间面板 —— 图上只是两层坐标轴叠在一起）。
    """
    span_x = max(float(xlim[1]) - float(xlim[0]), 1e-9)
    span_z = max(float(zlim[1]) - float(zlim[0]), 1e-9)
    box_h = min(float(top) - float(bottom), float(max_w) * fig_w * span_z / (span_x * fig_h))
    box_w = box_h * fig_h * span_x / (span_z * fig_w)
    return (float(TRAJ_FIG_LEFT), float(top) - box_h, box_w, box_h)


def _overlap(a, b) -> float:
    """两个 fraction 矩形的重叠面积（0 = 不重叠）。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


#: 注记尺寸的相对误差与"pt → 英寸"换算（figure 的 1 pt = 1/72 英寸）。
#: 实际文字比 `len × fontsize` 略宽（中英混排、字距），留 15% 余量；偏保守只会让候选
#: 更容易被判成"出框"，不会漏判。
TRAJ_LABEL_SLACK = 1.15
PT_PER_INCH = 72.0

#: 注记相对锚点的纵向候选 [pt]（`va="bottom"`）。先排**上侧**六档，再排**下侧**三档：
#: 命中点常常正好落在面板顶边上（俯视框的上沿就是数据上沿），只给上侧候选的话，
#: 那条结局注记**必然**被顶到框外（实测 trunc 工况出顶边 15.0 display px）——
#: 宁可让它落到点下方、与航迹同高，也不要飘在面板外面。
TRAJ_LABEL_DY_PTS = (10.0, 26.0, 42.0, 58.0, 74.0, 90.0, -20.0, -36.0, -52.0)


def _data_in(ax):
    """轴里 **1 英寸** 对应多少数据单位：`(每英寸多少 x, 每英寸多少 z)`。

    ⚠ 注释定位必须在**英寸**口径里算。`xytext` 的单位是 point，跨过 `bbox_inches="tight"`
    与 PNG 的 300 dpi 之后再回到数据坐标，跟"按轴高度猜一个像素数"差得很远 ——
    第一版就是拿 `(1000, 500)` 当分辨率，结果节点文字被推到俯视图外面，
    **成品图上只剩半行**（出框的字被 `tight` 带进图里，看起来像页面被撑歪）。
    """
    box = ax.get_position()                       # figure 坐标
    fw, fh = ax.figure.get_size_inches()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    return ((x1 - x0) / max(box.width * fw, 1e-9), (y1 - y0) / max(box.height * fh, 1e-9))


def _place_label(ax, text, xy, *, occupied=(), fontsize: float = 8.3,
                 color: str = "#333333"):
    """把节点文字放在**数据/inset 没占住**的那一侧，返回这次占用的 fraction 矩形。

    节点挤在 1~2 km 的小块里，而 50 km 量级的俯视图上一条 15 字的注记就有 2~3 km 宽 ——
    固定偏移必然互相压。这里给"左/右 × 六档高度"十二个候选，打分**先看重叠**：
    只要存在一个与已知矩形**零重叠**的候选，就一定选它（旧版把重叠按 100 倍面积加权，
    0.006 的重叠才折合 0.6 分，会输给"候选序号"那 0.04 分 —— 于是留了 1421 px² 的实叠）。
    出框罚在零重叠之后再看：`clip_on=True` 时出框的字是被**裁掉**的，比叠一点更糟。
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    per_in_x, per_in_z = _data_in(ax)             # 1 英寸 = 多少米
    inv_x, inv_z = 1.0 / (x1 - x0), 1.0 / (y1 - y0)
    w = _disp_width(text) * 0.5 * fontsize * TRAJ_LABEL_SLACK / PT_PER_INCH * per_in_x
    h = (fontsize + 6.0) / PT_PER_INCH * per_in_z
    best, best_rect, best_score = None, None, None
    for i in range(2 * len(TRAJ_LABEL_DY_PTS)):
        side = "left" if i < len(TRAJ_LABEL_DY_PTS) else "right"
        dx = 8.0 if side == "left" else -8.0
        dy = TRAJ_LABEL_DY_PTS[i % len(TRAJ_LABEL_DY_PTS)]
        tx = xy[0] + dx / PT_PER_INCH * per_in_x
        ty = xy[1] + dy / PT_PER_INCH * per_in_z
        xa, xb = (tx, tx + w) if side == "left" else (tx - w, tx)
        r = ((xa - x0) * inv_x, (ty - y0) * inv_z, (xb - x0) * inv_x, (ty + h - y0) * inv_z)
        ov = sum(_overlap(r, o) for o in occupied if o)
        oob = (max(0.0, -r[0]) + max(0.0, r[2] - 1.0)          # 出框：成品图上那行字是断的
               + max(0.0, -r[1]) + max(0.0, r[3] - 1.0))
        score = ((1.0e6 if ov > 1e-12 else 0.0) + 1.0e3 * oob + ov * 100.0 + 0.04 * i)
        if best_score is None or score < best_score:
            best, best_rect, best_score = (side, dx, dy), r, score
    side, dx, dy = best
    ax.annotate(text, xy=xy, xytext=(dx, dy), textcoords="offset points", fontsize=fontsize,
                color=color, ha=side, va="bottom", zorder=8, clip_on=True,
                bbox=dict(boxstyle="round,pad=0.16", facecolor="white", edgecolor="none",
                          alpha=0.72))
    return best_rect


#: 高度–时间面板里竖排节点标签的候选：横向偏移 [pt] × 纵向档位 [pt]。
#: ⚠ 竖排（`rotation=90`）文字的"厚度"朝 +x，所以钉在面板右边界上**必然出框**
#: （verifier 实测 5 个工况一致、都是 17.0 px）；而两个节点落在**同一时刻**时，
#: 纵向错开 10 pt 也躲不掉（实测重叠 578.8 px²）—— 候选必须**横向**分层。
TRAJ_ALT_DX_PTS = (2.0, -12.0, -26.0, -40.0)
TRAJ_ALT_DY_PTS = (-3.0, -14.0)
TRAJ_ALT_FONTSIZE = 7.6


def _place_alt_labels(ax, items, *, fontsize: float = TRAJ_ALT_FONTSIZE) -> list:
    """高度–时间面板的竖排节点标签：**不出面板、两两不重叠**。

    `items` = `[(t_s, label)]`；返回放好的矩形（display px，`(x0, y0, x1, y1)`）。
    候选按"越贴轴线越优先"排序，取第一个既不重叠也不出框的；一个都没有就取重叠最小的
    （并在返回值里如实给出矩形，方便自检 —— 这个避让是**估算**，必须由测试用真实
    bbox 复核）。
    """
    fig = ax.figure
    dpi = float(fig.dpi)
    box = ax.get_window_extent()
    lo, hi = (float(v) for v in ax.get_xlim())
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return []
    pt = dpi / PT_PER_INCH
    thick = 1.30 * fontsize * pt
    placed, out = [], []
    for t, lab in items:
        lab = str(lab)
        high = _disp_width(lab) * 0.5 * fontsize * 1.15 * pt
        xa = box.x0 + (float(t) - lo) / (hi - lo) * box.width
        best, best_rect, best_score = None, None, None
        for k, dx in enumerate(TRAJ_ALT_DX_PTS):
            for j, dy in enumerate(TRAJ_ALT_DY_PTS):
                rx0 = xa + dx * pt
                ry1 = box.y1 + dy * pt
                r = (rx0, ry1 - high, rx0 + thick, ry1)
                ov = sum(_overlap(r, q) for q in placed)
                oob = (max(0.0, box.x0 - r[0]) + max(0.0, r[2] - box.x1)
                       + max(0.0, box.y0 - r[1]) + max(0.0, r[3] - box.y1))
                score = ((1.0e6 if ov > 1e-9 else 0.0) + 1.0e3 * oob + ov * 10.0
                         + 0.5 * k + 0.2 * j)
                if best_score is None or score < best_score:
                    best, best_rect, best_score = (dx, dy), r, score
        if best is None:
            continue
        dx, dy = best
        out.append(best_rect)
        placed.append(best_rect)
        ax.annotate(lab, xy=(t, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(dx, dy), textcoords="offset points", fontsize=fontsize,
                    color="#666666", rotation=90, ha="left", va="top", zorder=6)
    return out


def _inset_slot(xlim, zlim, rect, zoom, pts, *, fig_w: float, fig_h: float):
    """挑一个**真的空**的角放放大 inset；返回 `(slot, xlim, zlim)`。

    俯视框的形状随数据变，inset 不能钉在固定角落：候选四角，按"与数据点的重叠面积"
    **再乘上"这个角放不放得下放大窗口那个长宽比"**打分取最优的一角 —— 只按空白挑的话，
    一个横向的窗口会被塞进竖着的角里，白占一大块地方。

    ⚠ **两条静默失败都要挡住**（verifier 的 D1，两版各踩了一条）：

    1. *框窄成一根线*：`set_aspect("equal", adjustable="box")` 会按"框的物理长宽比 vs
       数据长宽比"把 axes **再缩一次**，而且 `get_position()` 在 `apply_aspect()` 之前
       返回的还是设定值 —— 于是图上是"6.9 px 宽的紫竖线 + 面板左边游离的 8 个 y 刻度"，
       代码里一个数都不报错。本版的框**自己就是等比例的**：框的英寸比 = 窗口数据跨度比
       （`h_in/w_in = span_z/span_x`），所以根本不需要 `set_aspect`，也就没有二次收缩。
    2. *显示范围被撑大、放大倍率归零*：另一种"让数据填满框"的写法是先定框、再反解
       `need_z = box_h / rect[3] * (z1 - z0)`。那个式子的含义是**沿用俯视面板的米/英寸**，
       于是 inset 里 1 km 的窗口被画进 17 km 的显示范围 —— 框很大、框里一条几乎不动的
       线，而图例写着"放大"。本版窗口**只由数据定**（外扩 `TRAJ_INSET_PAD_FRAC`）。
    """
    x0, x1 = xlim
    z0, z1 = zlim
    if not pts:
        return None
    win_x = _span(min(p[0] for p in pts), max(p[0] for p in pts),
                  frac=TRAJ_INSET_PAD_FRAC, floor=40.0)
    win_z = _span(min(p[1] for p in pts), max(p[1] for p in pts),
                  frac=TRAJ_INSET_PAD_FRAC, floor=40.0)
    span_x = win_x[1] - win_x[0]
    span_z = win_z[1] - win_z[0]
    if not (math.isfinite(span_x) and math.isfinite(span_z)) or span_x <= 0 or span_z <= 0:
        return None
    ratio = span_x / span_z                            # 框的 宽/高（英寸比）
    # 面板能给的最大英寸尺寸：上限写成"面板 fraction"，乘回英寸
    avail_w = TRAJ_INSET_MAX_W * rect[2] * fig_w
    avail_h = TRAJ_INSET_MAX_H * rect[3] * fig_h
    h_in = min(avail_h, avail_w / ratio)
    w_in = h_in * ratio
    if not (math.isfinite(w_in) and math.isfinite(h_in)) or w_in <= 0 or h_in <= 0:
        return None
    box_w = w_in / (rect[2] * fig_w)                   # 面板 fraction（= inset_axes 的槽位）
    box_h = h_in / (rect[3] * fig_h)
    if box_w > 1.0 or box_h > 1.0:                     # 兜底：绝不许伸出面板
        k = min(1.0 / box_w, 1.0 / box_h)
        box_w, box_h = box_w * k, box_h * k
    grid = set()                        # 数据点的 12×12 粗格占用（逐点建矩形太贵）
    for px, pz in pts:
        gx = int((px - x0) / (x1 - x0) * 12)
        gz = int((pz - z0) / (z1 - z0) * 12)
        grid.add((min(11, max(0, gx)), min(11, max(0, gz))))
    best, best_score = None, None
    for i, (ax0, ay0) in enumerate(((0.06, 0.02), (0.06, 0.96 - box_h), (0.94 - box_w, 0.02),
                                    (0.94 - box_w, 0.96 - box_h))):
        if ax0 < 0.0 or ay0 < 0.0 or ax0 + box_w > 1.0 or ay0 + box_h > 1.0:
            continue
        r = (ax0, ay0, ax0 + box_w, ay0 + box_h)
        score = 0.0
        for gx in range(12):
            for gz in range(12):
                if (gx, gz) not in grid:
                    continue
                score += _overlap(r, (gx / 12.0, gz / 12.0, (gx + 1) / 12.0,
                                      (gz + 1) / 12.0)) * 10.0
        score += 0.10 * i
        if best_score is None or score < best_score:
            best, best_score = r, score
    if best is None:
        return None
    # ⚠ 返回 **`inset_axes()` 要的 `(x0, y0, 宽, 高)`**，不是四角：
    #   旧版把 `(ax0, ay0, ax0+box_w, ay0+box_h)` 直接喂给 `inset_axes()`，于是"宽/高"被当成
    #   远端角点 —— 右下角那两个候选会得到 0.94 / 0.96（亚满整个面板），
    #   高度也系统性多出 `ay0`（实测 0.36 vs 设计 0.34）。**不报错**，只是框比设计的更大。
    #   框的英寸比 = 窗口数据跨度比 ⇒ 两个方向"米/英寸"相等，窗口里那 20° 的角差才是真的。
    slot = (best[0], best[1], best[2] - best[0], best[3] - best[1])
    return slot, win_x, win_z


def _inset_px(slot, rect, *, fig_w: float, fig_h: float) -> tuple:
    """inset 槽位 → **保存图上**的像素尺寸 `(宽, 高)`（PNG 用 `SAVE_DPI`）。

    ⚠ `slot` 是 `inset_axes()` 的坐标 `(x0, y0, 宽, 高)`（**父轴 fraction**，不是 figure
    fraction）：换算必须再乘父轴的 `rect[2]` / `rect[3]` 与画布英寸数 —— 少乘一次就会把
    "可见"和"不可见"判反（旧版那根 6.9 px 的线就是这么留下来的）。
    """
    return (abs(float(slot[2])) * rect[2] * fig_w * SAVE_DPI,
            abs(float(slot[3])) * rect[3] * fig_h * SAVE_DPI)


def _inset_xtick_count(width_in: float, *,
                       fontsize: float = TRAJ_INSET_TICK_FONTSIZE) -> int:
    """放大框的 x 轴最多放几个刻度标签 —— 按"一个标签要占多宽"从**框宽**反算。

    y 轴不用管：标签竖着排，天然不撞。x 轴必须管：框宽是英寸级（0.46~0.55 in），
    而 `44.2k` 这种 5 字符标签在 7 pt 上就有 0.28 in 宽。
    `n` 个标签**等分**窗口时相邻间距 = 框宽/(n-1)，只要 `框宽 ≥ n × 标签宽`，
    间距就 ≥ 标签宽（首尾两个标签各有一半探出框外，那是允许的 —— 它们下面没有别的东西）。

    ⚠ 别指望 matplotlib 的 `get_tick_space()`：它在 50 display px 宽的框上仍给出 5 个刻度，
    实测 `44.0k 44.1k 44.2k 44.3k 44.4k` 互相压 11.9 px（成品图上是 `44.144.244.3k` 一团糊）。
    """
    per_label_in = (TRAJ_INSET_LABEL_CHARS * 0.5 * fontsize * TRAJ_LABEL_SLACK
                    / PT_PER_INCH)
    if per_label_in <= 0 or width_in <= 0:
        return 1
    return max(1, min(4, 1 + int(width_in / per_label_in)))


def _inset_xtick_locs(lo: float, hi: float, n: int) -> list:
    """把 `n` 个刻度**等分**放在窗口 `[lo, hi]` 上（相邻间距 = 跨度/(n-1)）。"""
    if n <= 1 or not (hi > lo):
        return [(lo + hi) / 2.0]
    step = (hi - lo) / (n - 1)
    return [lo + i * step for i in range(n)]


def _compact_m(v, _pos=None) -> str:
    """刻度压成 `10.2k`：高度–时间面板与放大 inset 的 y 轴都吃它 ——
    两块面板的左边界与 inset 的框都很窄，四位数刻度会挤出去。"""
    return f"{v / 1000:.1f}k" if abs(v) >= 1000 else f"{v:g}"


def plot_traj(run, *, out_base, formats=("png", "pdf", "svg"), dpi=160, footnotes=()) -> list:
    """图3 主入口：俯视（等比例）+ 高度–时间 + 「开机→转39」放大 inset + 题头 + 脚注。

    `run` 是 `traj.TrajRun`。三格式沿用 `save_formats()`（PNG 300 dpi、PDF/SVG 去时间戳）
    与 `normalize_svg_ids()`，所以同参数连画两次逐字节一致。

    版面与口径（计划 §3 / §8）：

    * 主面板是**俯视**：水平面 = `(x, z)`，`y` 是高度（内核口径：`heading 0 = +x`、
      `90 = +z`）；导弹航迹取 `x`/`z`、目标航迹取 `tx`/`tz`。
    * **命中点取 `run.rows_at(t_hit)` 那一行** —— `t_hit` 是事件时刻，可能不在时间栅格上，
      而图上的星标必须是"撞上那一刻的真实位置"。
    * 脱靶 / `lifetime` 的轨迹一直画到 `t_end`，坐标范围按实际画出的数据裁、脚注写明。
    * 震荡只在高度–时间面板上可见 —— 俯视图天然丢这一维，脚注必须点破，
      否则读者会以为震荡没生效。
    """
    setup_style()
    rows = [r for r in (run.rows or ()) if r.get("t") is not None]
    track = _target_xy(run)
    if not track or not rows:
        raise ValueError("plot_traj 需要带 t/tx/tz 的轨迹行（run.rows 为空）")
    t_end = float(run.t_end_s)
    if not math.isfinite(t_end) or t_end <= 0:
        t_end = max(e[0] for e in track)
    trunc = [s for s in (run.segments or ()) if getattr(s, "truncated", False)]
    t_hit = float(run.shot.t_hit) if (run.hit and math.isfinite(float(run.shot.t_hit))) else None
    mtrack = _missile_xy(run, t_end=t_end)
    marks = _visible_marks(run)
    zoom = _zoom_window(run, t_end=t_end)

    # ---- 轴范围：按**实际画出的数据**裁（脱靶时轨迹拖到 t_end，范围会大得多）----
    pts = [(e[1], e[2]) for e in track] + [(e[1], e[2]) for e in mtrack] + [(0.0, 0.0)]
    xlim = _span(min(p[0] for p in pts), max(p[0] for p in pts), floor=400.0)
    zlim = _span(min(p[1] for p in pts), max(p[1] for p in pts), floor=400.0)
    fig_w, fig_h = TRAJ_FIG_SIZE
    rect = _fit_box(xlim, zlim, max_w=TRAJ_FIG_RIGHT - TRAJ_FIG_LEFT, top=TRAJ_TOP_H,
                    bottom=TRAJ_MAIN_BOTTOM, fig_w=fig_w, fig_h=fig_h)
    legend_y = TRAJ_TOP_H + 0.062

    fig = plt.figure(figsize=TRAJ_FIG_SIZE, dpi=TRAJ_FIG_DPI)
    ax = fig.add_axes(list(rect))
    # 高度–时间：**在俯视下面**，宽度吃满。框顶 ≤ TRAJ_MAIN_BOTTOM 之上，题头区与副面板
    # 都碰不到它；脚注按两块面板里**最低**的那条排。
    ax_alt = fig.add_axes([rect[0], TRAJ_ALT_BOTTOM, rect[2], TRAJ_ALT_H])
    try:
        for a in (ax, ax_alt):
            a.set_axisbelow(True)
            a.grid(which="major", alpha=0.35, lw=0.8)
            a.tick_params(labelsize=9)
            for side in ("top", "right"):
                a.spines[side].set_visible(False)

        # ---- 主面板：俯视（等比例）----
        ax.set_xlim(*xlim)
        ax.set_ylim(*zlim)
        xmaj = _nice_tick(xlim[1] - xlim[0], 6)
        zmaj = _nice_tick(zlim[1] - zlim[0], 6)
        ax.xaxis.set_major_locator(mticker.MultipleLocator(xmaj))
        ax.xaxis.set_minor_locator(mticker.MultipleLocator(_minor_for(xmaj)))
        ax.yaxis.set_major_locator(mticker.MultipleLocator(zmaj))
        ax.yaxis.set_minor_locator(mticker.MultipleLocator(_minor_for(zmaj)))
        ax.grid(which="minor", alpha=0.18, lw=0.5)
        ax.set_xlabel(TRAJ_XLABEL, fontsize=11)
        ax.set_ylabel(TRAJ_ZLABEL, fontsize=11)
        ax.set_aspect("equal", adjustable="box")

        occupied = []
        # ---- 放大 inset：**先**占位 ----
        # ⚠ 顺序有讲究：inset 的槽位必须在**所有注记之前**算出来并进 `occupied`。
        #   旧顺序是先放「110° / 90° 参考方向」两条注记、再挑 inset 的角 —— 那两条射线
        #   正好指向左上方（与 inset 抢同一块地方），于是它们的文字**压在放大框里**
        #   （实测：`110° 参考方向` / `90° 参考方向` 的 bbox 与紫框相交）。
        #   注记是"可移动"的一方，所以让它们先知道 inset 占哪儿。
        slot = inset_xlim = inset_ylim = None
        slot_occupied_idx = None
        if zoom is not None:
            got = _inset_slot(xlim, zlim, rect, zoom,
                              [(e[1], e[2]) for e in track
                               if zoom[0] - 1e-9 <= e[0] <= zoom[1] + 1e-9],
                              fig_w=fig_w, fig_h=fig_h)
            if got is not None:
                slot, inset_xlim, inset_ylim = got
                slot_occupied_idx = len(occupied)
                # `occupied` 里一律是**四角**形式（`_overlap` 的口径），
                # 而 `slot` 是 `inset_axes` 要的 (x0, y0, 宽, 高)。
                # ⚠ 占位要**连标题那条带一起占**：inset 的标题画在框上方，仍在主轴的版图里，
                #   只占框本身的话注记会贴着框顶放，正好把标题压掉（实测 153.4 px²）。
                band = (TRAJ_INSET_TITLE_FONTSIZE + 6.0 + TRAJ_INSET_TITLE_PAD_PT) / PT_PER_INCH \
                    / (rect[3] * fig_h)
                occupied.append((slot[0] - TRAJ_INSET_PAD_AX, slot[1] - TRAJ_INSET_PAD_AX,
                                 slot[0] + slot[2] + TRAJ_INSET_PAD_AX,
                                 slot[1] + slot[3] + band + TRAJ_INSET_PAD_AX))

        # 110° / 90° 的参考方向：等比例时那 20° 的偏角一眼可辨（不等比例就重合了）。
        # 刻意只画**很短**的一段（而不是画到轴边）：长射线会横扫整张图，把注记逼到墙角。
        ray_x = 0.17 * (xlim[1] - xlim[0])
        ray_z = 0.17 * (zlim[1] - zlim[0])
        for deg, lab in ((110.0, "110°"), (90.0, "90°")):
            r = math.radians(deg)
            ex, ez = ray_x * math.cos(r), ray_z * math.sin(r)
            ax.plot([0.0, ex], [0.0, ez], color=TRAJ_GUIDE_COLOR, lw=0.9, ls=(0, (6, 4)),
                    alpha=0.6, zorder=1)
            occupied.append(_place_label(ax, f"{lab} 参考方向", (ex, ez), occupied=occupied,
                                         fontsize=8.3, color=TRAJ_GUIDE_COLOR))

        drawn_segs = plot_traj_segments(ax, run)
        if mtrack:
            ax.plot([e[1] for e in mtrack], [e[2] for e in mtrack], color=TRAJ_MISSILE_COLOR,
                    lw=TRAJ_MISSILE_LW, ls=TRAJ_MISSILE_LS, zorder=2)
        ax.plot([track[0][1]], [track[0][2]], marker="o", ms=5.0, color=TRAJ_MARK_COLOR,
                mfc="white", mew=1.2, ls="none", zorder=6)

        # ---- 节点：目标航迹上的点 + **躲开 inset 与彼此**的文字 ----
        # ⚠ `end` 节点**不在这里**加注记：命中/脱靶那条结局注记就是它的唯一文案（见下）。
        #   两条都画会在同一个位置叠 1421 px²（命中）/ 4.5 px²（脱靶），而且脱靶工况的
        #   文案写着「命中 / 结束」是**误导**。标记点（白圈）照画，图例那一格才有图元。
        for m in marks:
            p = _target_at(track, float(m.t_s))
            if p is None:
                continue
            # 白圈垫底再点实心点：节点文字带半透明白底，压上来时节点还看得见
            ax.add_patch(mpatches.Circle(p, 0.010 * (xlim[1] - xlim[0]), facecolor="white",
                                         edgecolor="none", zorder=5))
            ax.plot([p[0]], [p[1]], marker="o", ms=TRAJ_MARK_MS, color=TRAJ_MARK_COLOR,
                    mfc="white", mew=1.3, ls="none", zorder=7)
            if m.name == "end":
                continue
            extra = ""
            if m.name == "beam_start":
                h = _heading_deg_at(rows, float(m.t_s))
                if h is not None:
                    extra = f"实际航向 {h:.1f}°（{_clock_label(h)}）"
            occupied.append(_place_label(ax, _mark_text(m, extra=extra), p, occupied=occupied))

        # ---- 命中 / 脱靶：结束节点的**唯一**注记（节点名按结局二选一）----
        end_p = _target_at(track, t_end)
        if t_hit is not None:
            row = run.rows_at(t_hit)          # ⚠ 事件时刻的位置单独取那一行
            p = _finite_xy(row, "x", "z") if row else None
            if p is not None:
                ax.plot([p[0]], [p[1]], marker="*", ms=17.0, color=TRAJ_HIT_COLOR,
                        mec="white", mew=0.8, ls="none", zorder=9)
                # 比节点那行多一位小数：命中时刻是**事件**时刻，69.17 与 69.172 是两回事
                occupied.append(_place_label(ax, f"命中 t={t_hit:.3f} s", p, occupied=occupied,
                                             fontsize=9.0, color=TRAJ_HIT_COLOR))
        else:
            row = run.rows_at(t_end)
            p = _finite_xy(row, "x", "z") if row else None
            if p is None:                      # 连终点位置都取不到 ⇒ 退回节点自己的位置
                p = end_p
            if p is not None:
                if end_p is not None and (end_p[0] != p[0] or end_p[1] != p[1]):
                    ax.plot([p[0], end_p[0]], [p[1], end_p[1]], color=TRAJ_MISS_COLOR, lw=1.0,
                            ls=(0, (2, 2)), zorder=8)     # 末段弹目距离：让"差多少"看得见
                ax.plot([p[0]], [p[1]], marker="X", ms=12.0, color=TRAJ_MISS_COLOR,
                        mec="white", mew=0.8, ls="none", zorder=9)
                miss = float(run.shot.miss_m)
                lab = f"脱靶 {miss:.0f} m" if math.isfinite(miss) else "未命中（最近点）"
                # 节点名 + 结局 + 时刻**一条说完**：旧版是「命中 / 结束 … · 脱靶 …」加
                # 「脱靶 … · 末段最近点 …」两条，同一个点上紧贴 4.5 px² 且自相矛盾（D8）。
                occupied.append(_place_label(ax, f"结束（未命中） t={t_end:.2f} s · {lab}", p,
                                             occupied=occupied, fontsize=9.0,
                                             color=TRAJ_MISS_COLOR))

        # ---- 放大 inset 本体（位置已在上面占好）----
        if slot is not None:
            axi = ax.inset_axes(list(slot))
            plot_traj_segments(axi, run, t_window=zoom)
            for m in marks:
                if not (zoom[0] - 1e-9 <= float(m.t_s) <= zoom[1] + 1e-9):
                    continue
                p = _target_at(track, float(m.t_s))
                if p is None:
                    continue
                axi.plot([p[0]], [p[1]], marker="o", ms=4.6, color=TRAJ_MARK_COLOR,
                         mfc="white", mew=1.1, ls="none", zorder=7)
                h = _heading_deg_at(rows, float(m.t_s))
                if h is not None:
                    axi.annotate(f"{h:.0f}°", xy=p, xytext=(5, 4), textcoords="offset points",
                                 fontsize=8.0, color=TRAJ_MARK_COLOR, zorder=8)
            # 显示范围直接吃 `_inset_slot` 算好的**数据窗口**（它已经保证
            # "框的英寸比 = 窗口数据跨度比"），所以这里**不能**再叠一层 `_span()` 自适应：
            # 那会把放大倍率抹掉，让框里只剩一条几乎不动的线（静默）。
            if inset_xlim is not None:
                axi.set_xlim(*inset_xlim)
            if inset_ylim is not None:
                axi.set_ylim(*inset_ylim)
            # ⚠ 刻意**不**调 `set_aspect("equal", adjustable="box")`：槽位的英寸比已经等于
            #   窗口的数据跨度比，两个方向本来就是同一个"米/英寸"（等比例）。再让 matplotlib
            #   收缩一次只会把框压细 —— 而那个退化要到 `draw()` 里的 `apply_aspect()` 才现形，
            #   于是"6.9 px 宽的竖线"在代码里一个数都不报（D1）。
            axi.tick_params(labelsize=TRAJ_INSET_TICK_FONTSIZE)
            # x 刻度按框宽限量、并**等分**放：不限量的话窄框里会挤成一团（实测 5 个互压
            # 11.9 px）；用"好看的整数"定位器也不行 —— 它可能挑出两个只隔 23 px 的刻度，
            # 而一个标签就有 27 px 宽（miss 工况实测互压 4.4 px）。
            axi.xaxis.set_major_locator(mticker.FixedLocator(_inset_xtick_locs(
                float(inset_xlim[0]), float(inset_xlim[1]),
                _inset_xtick_count(slot[2] * rect[2] * fig_w))))
            axi.xaxis.set_major_formatter(mticker.FuncFormatter(_compact_m))
            # 刻度文字**从刻度往右排**（默认居中）：居中时最左边那个标签有一半探到框外，
            # 正好压住同一角的 y 刻度（实测 9.7~25.0 px²）；`ha="left"` 后它从框左沿起排，
            # 最后一个往右探出去 —— 那边是空地，不会撞任何东西。
            for _lab in axi.get_xticklabels():
                _lab.set_ha("left")
            axi.yaxis.set_major_formatter(mticker.FuncFormatter(_compact_m))
            axi.grid(alpha=0.30, lw=0.6)
            axi.set_axisbelow(True)
            for sp in axi.spines.values():
                sp.set_edgecolor(TRAJ_ZOOM_COLOR)
                sp.set_linewidth(1.0)
            axi.set_title(f"放大 {zoom[0]:g}–{zoom[1]:g} s", fontsize=TRAJ_INSET_TITLE_FONTSIZE,
                          color=TRAJ_ZOOM_COLOR, pad=TRAJ_INSET_TITLE_PAD_PT)
            # 硬闸门：算出来的框在 **300 dpi 成品图**上宽或高 < 20 px ⇒ 连 inset 一起撤掉
            # （`occupied` 里那一格也撤），图例就不许出现"放大"那一格。
            ipx_w, ipx_h = _inset_px(slot, rect, fig_w=fig_w, fig_h=fig_h)
            if ipx_w < TRAJ_INSET_MIN_PX or ipx_h < TRAJ_INSET_MIN_PX:
                axi.remove()
                if slot_occupied_idx is not None:
                    del occupied[slot_occupied_idx]
                slot = None

        # ---- 副面板：高度–时间（与主面板共用同一批节点时刻）----
        ax_alt.set_xlabel(TRAJ_ALT_XLABEL, fontsize=11)
        ax_alt.set_ylabel(TRAJ_ALT_YLABEL, fontsize=10)
        ax_alt.yaxis.set_major_formatter(mticker.FuncFormatter(_compact_m))
        tgt_alt = _alt_series(run, "ty")
        mis_alt = [e for e in _alt_series(run, "y") if e[0] <= t_end + 1e-9]
        if tgt_alt:
            ax_alt.plot([e[0] for e in tgt_alt], [e[1] for e in tgt_alt], color=TRAJ_MARK_COLOR,
                        lw=1.6, zorder=4)
        if mis_alt:
            ax_alt.plot([e[0] for e in mis_alt], [e[1] for e in mis_alt],
                        color=TRAJ_MISSILE_COLOR, lw=TRAJ_MISSILE_LW, ls=TRAJ_MISSILE_LS,
                        zorder=3)
        alts = [e[1] for e in tgt_alt] + [e[1] for e in mis_alt] or [0.0, 1.0]
        ax_alt.set_xlim(0.0, max(t_end, 1e-6))
        ax_alt.set_ylim(*_span(min(alts), max(alts), frac=0.16, floor=250.0))
        for m in marks:
            ax_alt.axvline(float(m.t_s), color="#999999", lw=0.8, ls=(0, (3, 3)), zorder=1)
        # 竖排标签：`end` 按结局取名（「命中」/「结束」），并且**横向分层**避让 ——
        # 竖排文字的厚度朝 +x，钉在面板右边界上必然出框（实测 17.0 px），
        # 两个节点同刻时纵向错 10 pt 也躲不掉（实测重叠 578.8 px²）（D7）。
        _place_alt_labels(ax_alt, [(float(m.t_s), _mark_label(m, hit=bool(run.hit)))
                                   for m in marks])
        if t_hit is not None:
            ax_alt.axvline(t_hit, color=TRAJ_HIT_COLOR, lw=1.0, ls=(0, (2, 2)), zorder=2)

        # ---- 题头 / 脚注 ----
        trunc_color = (TRAJ_COLORS.get(getattr(trunc[0], "color_key", ""), TRAJ_FALLBACK_COLOR)
                       if trunc else None)
        add_traj_header(fig, title=TRAJ_TITLE, subtitle=_traj_subtitle(run),
                        segments=drawn_segs, marks=marks, truncated=bool(trunc),
                        zoom=slot is not None, y=legend_y, trunc_color=trunc_color)
        lines = []
        for line in _traj_footnotes(run, truncated=bool(trunc), extend_to=t_end, t_hit=t_hit):
            lines.extend(wrap_lines(_plain(line), width=250))
        for line in (footnotes or ()):        # 调用方传进来的行**接在**本模块说明的后面
            # ⚠ 调用方的行也要过 `_plain()`：`run_traj` 注入的 note 里可能带 markdown
            lines.extend(wrap_lines(_plain(line), width=250))
        if lines:
            # 两块面板的下沿都在同一高度：按**最低**那条（含 x 轴标题）留一点余量即可
            y0 = min(xlabel_bottom_fig(ax, fig), xlabel_bottom_fig(ax_alt, fig)) - FOOTNOTE_GAP
            add_footnotes(fig, lines, y0=y0)
        return save_formats(fig, out_base, formats=formats)
    finally:
        plt.close(fig)


def plot_traj_preview_3d(schedule, *, p0, duration_s, out_base, formats=("png",),
                         azimuths=(30.0,), footnotes=(), dpi=160) -> list:
    """图3 的**输入阶段**预览：目标航迹 3D 曲线 + 分段色 + 节点。**不跑求解器**。

    `schedule` 是 `flightpath.PathSchedule`（只吃它的 `samples()` —— 纯运动学、毫秒级）；
    `p0` 是目标**起始位置** `(x, y, z)` 米，**`y` 是高度**（与内核坐标同口径）；
    `duration_s` 画多久；`azimuths` 给多个方位角时出一张分格拼图（计划 §7 的低成本中间态）。

    三轴用 `set_box_aspect(真实跨度之比)`，所以几何不失真 ——
    "70° 朝哪边转、crank 段多长、震荡在哪个平面里摆"在解算之前就看得见。
    """
    setup_style()
    azs = [float(a) for a in (azimuths or (30.0,))]
    if not azs:
        raise ValueError("plot_traj_preview_3d 至少需要一个方位角")
    if float(duration_s) <= 0:
        raise ValueError("duration_s 必须为正")
    samples = schedule.samples(p0=p0, duration_s=float(duration_s), dt=0.05)
    segs = schedule.segments(duration_s=float(duration_s))
    ts = [float(s["time_s"]) for s in samples]
    xs = [float(s["position_m"][0]) for s in samples]
    ys = [float(s["position_m"][1]) for s in samples]
    zs = [float(s["position_m"][2]) for s in samples]

    n = len(azs)
    nrow = 1 if n <= 2 else 2
    ncol = n if n <= 2 else int(math.ceil(n / 2.0))
    fig = plt.figure(figsize=(5.6 * ncol, 4.6 * nrow), dpi=TRAJ_FIG_DPI)
    try:
        for i, az in enumerate(azs):
            ax = fig.add_subplot(nrow, ncol, i + 1, projection="3d")
            for j, seg in enumerate(segs):
                # mplot3d 的三个实参映射到物理轴是 (x 水平, z 水平, 高度 y)
                idx = [k for k, t in enumerate(ts)
                       if float(seg.t0_s) - 1e-9 <= t <= float(seg.t1_s) + 1e-9]
                if len(idx) < 2:
                    continue
                dup = any(seg.label == s.label for s in segs[:j])
                ax.plot([xs[k] for k in idx], [zs[k] for k in idx], [ys[k] for k in idx],
                        color=TRAJ_COLORS.get(seg.color_key, TRAJ_FALLBACK_COLOR), lw=2.0,
                        solid_capstyle="round", label=(None if dup else seg.label))
            ax.plot([xs[0]], [zs[0]], [ys[0]], marker="o", ms=5.0, mfc="white",
                    mec=TRAJ_MARK_COLOR, ls="none")
            seen_t = set()
            for leg in (schedule.legs or ()):   # 预览阶段没有求解结果，只有"指令"这个节点
                t_leg = float(leg.at_s)
                if t_leg in seen_t or t_leg > float(duration_s) + 1e-9:
                    continue
                seen_t.add(t_leg)
                k = min(range(len(ts)), key=lambda j: abs(ts[j] - t_leg))
                ax.plot([xs[k]], [zs[k]], [ys[k]], marker="o", ms=5.0, color=TRAJ_MARK_COLOR,
                        mfc="white", mew=1.2, ls="none")
                ax.text(xs[k], zs[k], ys[k], f" 指令 → {leg.heading_deg:g}°  t={t_leg:g} s",
                        fontsize=8.0, color=TRAJ_MARK_COLOR)
            ax.set_box_aspect(_box_aspect(xs, ys, zs))
            # 3D 里轴标题与相邻轴的刻度标签几乎贴着：labelpad 给足才不会压字
            ax.set_xlabel("x [m]", fontsize=9, labelpad=6)
            ax.set_ylabel("z [m]", fontsize=9, labelpad=8)
            ax.set_zlabel("高度 y [m]", fontsize=9, labelpad=8)
            ax.tick_params(labelsize=7.5)
            # ⚠ 3D 轴的刻度标签极易互相压：实测水平两轴给出 "35000 40000 45000…" 糊成一团、
            #   高度轴的标签还压住轴标题。宁可少给几个数字，也要能读。
            ax.xaxis.set_major_locator(mticker.MaxNLocator(4))
            ax.yaxis.set_major_locator(mticker.MaxNLocator(4))
            # 高度跨度比水平跨度小得多时，高度轴在投影里被压得几乎看不见 —— 给两个数就会
            # 互相压成一团（实测 "13000" 与 "10000" 叠印）。这种情况只标一个数，读数交给
            # 图3 主图的高度–时间面板。
            span_h = max(ys) - min(ys)
            flat = span_h < 0.15 * max(max(xs) - min(xs), max(zs) - min(zs), 1.0)
            if flat:
                # 只留**一个**刻度（MaxNLocator(1) 仍可能给两个 ⇒ 用它就会继续叠印）
                ax.zaxis.set_major_locator(mticker.FixedLocator(
                    [round((min(ys) + max(ys)) / 2.0, -2)]))
            else:
                ax.zaxis.set_major_locator(mticker.MaxNLocator(3))
            ax.set_title(f"方位角 {az:g}°", fontsize=10)
            elev, azim = AZIMUTH_PRESETS.get(az, (24.0, -90.0 + az))
            ax.view_init(elev=elev, azim=azim)
            if i == 0:                          # 图例只从第一格取（各格内容相同）
                handles, labels = ax.get_legend_handles_labels()
                if handles:
                    fig.legend(handles, labels, loc="upper center",
                               ncol=min(5, len(handles)), frameon=False, fontsize=9.0,
                               bbox_to_anchor=(0.5, 0.898))
        fig.text(0.5, 0.988, "目标航迹 3D 预览（不解算）", ha="center", va="top",
                 fontsize=14, fontweight="bold")
        # ⚠ 副标题要离标题至少一个**标题行高**：0.033 图高 × 4.4 in ≈ 10.5 pt < 14 pt ⇒ 会压字
        #   （实测就是这么压上的）。0.930 给到 ≈ 19 pt 的净空。
        fig.text(0.5, 0.930, _preview_subtitle(schedule, p0, duration_s),
                 ha="center", va="top", fontsize=10.0, color=GRAY)
        lines = ["图上没有导弹航迹 —— 那要等解算完才画得出来。",
                 "三轴按真实跨度设比例（set_box_aspect），所以几何不失真；"
                 "分段颜色与图3 主图共用同一套 Segment.color_key。"]
        # ⚠ 调用方传进来的行也必须过 `_plain()`：出图层不能假设 `footnotes=` 不带 markdown
        #   （原文那句就写着 `**不需要跑求解器**`，matplotlib 不解析 markdown ⇒ SVG 里是
        #   字面星号，D5）。图1/图2 的脚注**不走这里** —— 它们的字节是已交付产物。
        lines = [_plain(line) for line in lines + list(footnotes or ())]
        wrapped = []
        for line in lines:
            wrapped.extend(wrap_lines(line, width=200))
        # 3D 盒子的形状由数据跨度比定，会留白；把轴区放宽、脚注区留住，别让盒子缩在中间
        fig.subplots_adjust(left=0.02, right=0.98, bottom=0.16, top=0.76)
        add_footnotes(fig, wrapped, y0=0.085)
        if int(dpi) > 0:
            fig.set_dpi(int(dpi))
        return save_formats(fig, out_base, formats=formats)
    finally:
        plt.close(fig)


def _box_aspect(xs, ys, zs) -> tuple:
    """3D 三轴的**相对长度** = 数据真实跨度之比（退化维兜底 1.0，不能零长）。"""
    def _r(v):
        d = float(max(v)) - float(min(v))
        return d if d > 1e-9 else 1.0
    return (_r(xs), _r(zs), _r(ys))      # mplot3d 的三元组顺序是 (x, y, z) = (x, z, 高度)


def _preview_subtitle(schedule, p0, duration_s) -> str:
    parts = [f"起点 ({float(p0[0]):g}, {float(p0[1]):g}, {float(p0[2]):g}) m",
             f"目标 {schedule.speed_ms:g} m/s 起始航向 {schedule.start_heading_deg:g}°",
             f"时长 {float(duration_s):g} s"]
    wp = schedule.weave
    if wp is not None:
        parts.append(f"震荡 ±{wp.amp_deg:g}° @ {wp.hz:g} Hz（{wp.start_s:g} s 起）")
    return " · ".join(parts)



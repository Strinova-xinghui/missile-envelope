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
#: **选中态（基准弹）** 的颜色 = 红的反色绿。取 Material Green 700 `#388E3C` —— 与 `POINT_COLOR`
#: 的 Red 700（`#D32F2F`）同明度同族，白底上对比也够。⚠ 图1 与图2 **共用这一个常量**，别各写一份，
#: 否则"两图的基准弹颜色"迟早会分叉。
BASE_COLOR = "#388E3C"
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


#: SVG 元素 id 的**盐**：matplotlib 的 `_make_id()` 默认拿 `uuid4()` 当盐，所以同一张图
#: 连跑两次 id 全变（**同一个进程里也变**）。旧版图2 恰好没走到那条路径才一直没暴露；
#: 2026-10-01 把图2 的气泡点径统一成 `POINT_SIZE` 之后，散点标记被后端折叠成**一条共享
#: `<defs>` 路径**，id 形如 `C0_0_<sha256 前 10 位>` —— `normalize_svg_ids()` 的旧正则
#: 匹配不到中间的 `_`，SVG 当场不可复现（`tests/test_figures_bg.py` 抓到）。
#: 钉死盐值后这类 id 只由内容决定，再交给 `normalize_svg_ids()` 顺序化，两层都留着。
SVG_HASH_SALT = "missile-sim"


def setup_style() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = _CN_FONTS
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 160
    plt.rcParams["savefig.bbox"] = "tight"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.25
    plt.rcParams["svg.hashsalt"] = SVG_HASH_SALT


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


def _pick_color(key: str, highlight: str, normal: str) -> str:
    """选中态（基准弹）涂成绿，其余用 `normal` —— 图1 的点/标签与图2 的点/标签**共用这条规则**。

    ⚠ 2026-10-01 用户口径：选中态**只用颜色**表达（空心环已删），而且**点与标签同色**。
    """
    return BASE_COLOR if (highlight and key == highlight) else normal


def _green_legend_text(leg, highlight: str) -> None:
    """图例里"基准弹"那一条的**文字**也涂绿 —— 与图上标签同色（用户 2026-10-01 追加要求）。"""
    if not highlight:
        return
    for t in leg.get_texts():
        if t.get_text() == highlight:
            t.set_color(BASE_COLOR)


def plot_points(ax, points, *, offsets: dict | None = None, with_leader: bool = True,
                fontsize: float = LBL_FONTSIZE, color: str = LBL_COLOR,
                highlight: str = ""):
    """画弹点 + 标签（带细引线）。返回 `(scatter, texts)`。

    `highlight` 给**基准弹的 key**：那一型的**点与标签**都涂 `BASE_COLOR`（绿），其余红点/红字。
    ⚠ 2026-10-01 用户拍板：选中态**只用颜色**表达 —— 外面那圈空心环已去掉（`mark_highlight` 已删）。
    """
    offs = dict(MISSILE_LBL_OFFSETS)
    if offsets:
        offs.update(offsets)
    pts = list(points or ())
    if not pts:
        return None, []
    sc = ax.scatter([p.dv for p in pts], [p.bc for p in pts], s=POINT_SIZE,
                    c=[_pick_color(p.key, highlight, POINT_COLOR) for p in pts],
                    edgecolors="white", linewidths=0.9, zorder=4)
    texts = []
    for p in pts:
        dx, dy = offs.get(p.key, offs.get(p.label, (10, 10)))
        ha = "right" if dx < -8 else ("left" if dx > 8 else "center")
        texts.append(ax.annotate(
            p.label, xy=(p.dv, p.bc), xytext=(dx, dy), textcoords="offset points",
            fontsize=fontsize, color=_pick_color(p.key, highlight, color),
            fontweight="bold", ha=ha, va="center",
            zorder=6, arrowprops=(LBL_LEADER if with_leader else None)))
    return sc, texts


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
        # 基准弹：与图上完全一致 = **绿色实心点**（外面那圈空心环 2026-10-01 按用户要求去掉）
        handles.append(Line2D([], [], marker="o", color="none", markerfacecolor=BASE_COLOR,
                              markeredgecolor="white", markersize=7,
                              label=highlight))
    fig.text(0.5, 0.982, title, ha="center", va="top", fontsize=14, fontweight="bold")
    if subtitle:
        fig.text(0.5, 0.936, subtitle, ha="center", va="top", fontsize=10.5, color=GRAY)
    leg = fig.legend(handles=handles, loc="upper center", ncol=len(handles), frameon=False,
                     fontsize=9.5, bbox_to_anchor=(0.5, 0.918), borderaxespad=0.0)
    _green_legend_text(leg, highlight)
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

    matplotlib 的 SVG 后端用 `_make_id()` 造元素 id —— **盐是 `svg.hashsalt`**（默认 `uuid4()`，
    已由 `setup_style()` 钉死），所以几何完全相同也会整篇变。前缀有 `m`（标记/路径）、
    `p`（裁剪路径）、`image`（内嵌位图），另外**散点标记**还有
    `C<集合下标>_<路径下标>_<哈希>` 这种**带下划线**的形式：点径一致时后端会把标记折叠成
    **一条共享 `<defs>` 路径**（旧版图2 气泡尺寸各异 ⇒ 走的是别的路径，所以这个坑一直没露头）。
    正则因此写成"字母 + （可选 `_十六进制` 段）+ ≥5 位十六进制"，`figure_1`/`line2d_1` 这类
    稳定 id 与颜色十六进制串都不会被误伤。写回时保持原行尾（`newline=""`）。
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    ids: list = []
    for m in re.finditer(r'\bid="([A-Za-z]+(?:[0-9a-f]*_[0-9a-f]+)*[0-9a-f]{5,})"', text):
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
        plot_points(ax, points, highlight=str(getattr(highlight, "key", "") or ""))
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


# ------------------------------------------------------------------- 图2：β–ginv 能力平面

#: 等 `n*` 线的默认图层（G）与线条样式。
BG_NSTAR_LEVELS = (14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0)
BG_NSTAR_COLOR = "#90A4AE"
BG_NSTAR_LS = (0, (5, 3))

#: 点大小：**与图1 同一个 `POINT_SIZE`**。2026-10-01 用户拍板：不再按 ΔV 缩放气泡
#: （旧 `BG_BUBBLE = (70, 470)` 让最大点直径到 24.5 pt，而标签只有 9.5 pt，与图1 的
#: 统一点径 9.4 pt 不一致）；基准弹改用 `BASE_COLOR` 标出，**外面那圈空心环已去掉**。

TITLE_BG = "两类存能能力平面：β（直飞保能） vs ginv = 1/γ（转向能力）"
XLABEL_BG = "β　[kg/m²]　直飞保能 →（越大越好）"
YLABEL_BG = "ginv = 1/γ　[m²/kg]　转向能力 →（越大越好）"
#: ⚠ **产物口径闸门的唯一出处**（`tests/test_page_assets.py` 与 `scripts/refresh_products.py`
#: 都从这里取，不许各写一份）：出图后的 SVG 里轴标签会以注释形式原样出现（matplotlib 把字画成
#: 路径，文字留在 `<!-- -->` 里），所以"这份图是不是新纵轴口径"可以用**文本**判 ——
#: 必须出现 `BG_AXIS_MARK`，不许出现 `BG_OLD_AXIS_MARKS` 里的任何一条（换轴前的轴注记）。
#: ⚠ 判据**不**拿「双曲线」当红线：新图的脚注里合法地留着它（讲旧口径那一段）。
BG_AXIS_MARK = "ginv = 1/γ"
BG_OLD_AXIS_MARKS = ("γ [kg/m²] 转向损失", "转向损失 →（越小越好）")
#: 图1（ΔV–BC 平面）的口径闸门：轴是 `BC`，而且**不该出现 γ/ginv 任何字样** ——
#: 它跟换轴这件事无关；一旦出现，说明两张图的轴注记被串了。
PLANE_AXIS_MARK = "简化弹道系数"
PLANE_FORBIDDEN = ("γ", "ginv")
#: 轴注记的通用特征：`→（…越好）`。同一张图的两个形态靠它逐条互比（成对闸门）。
AXIS_NOTE_MARK = "→（"
LEGEND_BG_NSTAR = "等 $n^*$ 线（{lo:g}~{hi:g} G，共 {n} 条）"
LEGEND_BG_POINTS = "弹池 {n} 型"
LEGEND_BG_SCAN = "仿真等时线（固定 ΔV，扫 β×ginv）"
CBAR_LABEL_BG = "命中时间 [s]"

#: ⚠ 脚注**不要写 `$...$`**：`wrap_lines()` 按显示宽度切行，会把一对 `$` 拆到两行，
#: mathtext 只见到落单的 `$` 就原样输出（第一版就是这么把公式打成了字面量）。
#: 图例里的数学可以留 —— 它短，不会被折行。
BG_FOOTNOTES = (
    "β = m燃尽/(SD·CxK)，SD = πd²/4 —— 与既有 BC 是同一个数，横轴即第一张图的纵轴。"
    "γ = m燃尽·SD·CxK·CxAoA/(SL²·CyK²)，SL = 0.3·d·L·wingAreaMult；SD/SL 直接取内核的 "
    "drag_area / lift_area，没有另造面积口径。",
    "纵轴是 γ 的倒数：ginv = 1/γ [m²/kg]（用户 2026-10-04 口径）。两根轴同为「向上＝更好」，"
    "所以「越大越好」这件事在整张图上是一个方向，不用再看符号。γ 仍是内核口径的转向损失，"
    "公式一个字没改；ginv 只影响画法与读法（换算只在本仓库 bg.py 一处）。",
    "等 n* 线：n* = q/(Q·g0)，Q = sqrt(β·F(M)/(f(M)·ginv)) —— 机动损失恰好等于基础阻力损失的"
    "那个过载，数字越小机动越贵；因 ginv ∝ β，这族线是过原点的直线"
    "（纵轴用 γ 时才是双曲线）。",
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


def bg_axis(rows_, *, pad: float = 0.06, xlim=None, ylim=None) -> AxisSpec:
    """β–ginv 的自适应轴（纵轴是**轴量** `ginv = 1/γ`）。范围由数据定，刻度按 nice 序列下调。

    ⚠ 纵轴的量级是 `1e-2`（γ ≈ 50~90 kg/m² ⇒ ginv ≈ 0.011~0.019），所以两处常量要跟着改：
    ① 边距下限从 γ 的 `4.5` 换成 ginv 的 `9e-4`（都约为跨度的 12%）；
    ② 次刻度**不能**走 `_minor_for()` —— 它里头的 `5e-3` 下限是按 ΔV/BC 的量级定的，
    拿到 ginv 上会把"5 等分"降成"2 等分"。这里直接给 5 等分。

    `xlim` / `ylim` 给了就**覆盖范围**，但刻度**始终按最终范围现算** —— 这是 2026-10-04 修掉的
    一个真缺陷：调用方用 `dataclasses.replace()` 换范围时会把"按弹池跨度算出来的 ginv 刻度"
    （`y_major = 0.0025`）留在一个 3000~3300 的范围上，matplotlib 的 `Locator` 会去生成
    12 万 / 60 万个刻度位（实测直接 `MemoryError: 536 GiB`）。**刻度必须跟着它实际画的范围走。**
    """
    bs = [float(r.beta) for r in rows_]
    gs = [float(r.ginv) for r in rows_]
    if not bs or not gs:
        raise ValueError("bg_axis 需要至少一行数据")
    b0, b1, g0, g1 = min(bs), max(bs), min(gs), max(gs)
    # 边距给足：标签往外伸，贴边会顶到轴线。
    bp = max((b1 - b0) * pad, 60.0)
    gp = max((g1 - g0) * pad, 9e-4)
    xlim = tuple(float(v) for v in xlim) if xlim else (b0 - bp, b1 + bp)
    ylim = tuple(float(v) for v in ylim) if ylim else (g0 - gp, g1 + gp)
    if not (xlim[1] > xlim[0]) or not (ylim[1] > ylim[0]):
        raise ValueError(f"坐标轴范围必须是递增的两个数：xlim={xlim!r} ylim={ylim!r}")
    xmaj = _nice_tick(xlim[1] - xlim[0], target=5)
    ymaj = _nice_tick(ylim[1] - ylim[0], target=4)
    return AxisSpec(xlim=(round(xlim[0], 6), round(xlim[1], 6)),
                    ylim=(round(ylim[0], 6), round(ylim[1], 6)),
                    x_major=xmaj, x_minor=_minor_for(xmaj),
                    y_major=ymaj, y_minor=ymaj / 5.0)


# ---------------------------------------------------------------- 图3 的三根轴


def fig3_dv_lim(dvs) -> tuple:
    """图3 的 ΔV 轴（**横轴**）：与图1 的 `adaptive_axis()` **同一条口径**（`_one_axis(..., "x")`）。

    ⚠ **不许写死区间**（用户 2026-10-04 口径：三根轴都要像图1/图2 那样自适应）：
    11 弹池算出 `(803.8, 1116.2)`；只选一枚弹时收紧到该弹 ±12 m/s（`MIN_PAD["x"]`）。
    写死 `[700, 1700]` 的后果不是"图错"，而是"横轴的跨度与另外两根不是一个池子的"——
    读图的人会以为 700 m/s 那种弹真的存在。
    """
    vals = [float(v) for v in dvs]
    if not vals:
        raise ValueError("fig3_dv_lim 至少需要一个 ΔV 值")
    (lo, hi), _major, _minor = _one_axis(vals, "x")
    return (round(lo, 3), round(hi, 3))


def fig3_axes(rows_) -> dict:
    """图3 **三根轴的自适应域**（唯一出处）：ΔV 走图1 的口径，β/ginv 走图2 的 `bg_axis`。

    返回 `{"dv": (lo, hi), "beta": (lo, hi), "ginv": (lo, hi)}`；键与 `FIG3_AXIS_ORDER` 同源。
    ⚠ 调用方**不许**再自己拼一遍边距：网格（`fig3scan.default_grid`）与页面（`fig3._axes`）
    都从这里取，否则"按需立方体扫的范围"与"屏幕上画的范围"会悄悄分叉。
    """
    rows_ = list(rows_ or ())
    if not rows_:
        raise ValueError("fig3_axes 至少需要一行数据")
    ax = bg_axis(rows_)                       # 图2 的口径（β 的 60.0 / ginv 的 9e-4 下限都在里面）
    return {"dv": fig3_dv_lim([r.dv for r in rows_]),
            "beta": (float(ax.xlim[0]), float(ax.xlim[1])),
            "ginv": (float(ax.ylim[0]), float(ax.ylim[1]))}


def bg_subtitle(*, alt_m: float, speed_ms: float, mach: float, q_pa: float,
                f_mach: float, cap_f: float, n: float) -> str:
    """图2 的副标题：**必须把参考工况写出来** —— `n*` 依赖动压，不写就没法比。"""
    return (f"参考工况 {alt_m / 1000:g} km / {speed_ms:g} m/s（Ma {mach:.2f}，"
            f"q {q_pa / 1000:.1f} kPa，f {f_mach:.4f}，F {cap_f:.4f}）"
            f" · 机动惩罚比 R 取 n = {n:g}G")


def _nstar_label_x(x0: float, m: float, cloud, axis: AxisSpec,
                   *, clear=(0.11, 0.035)) -> float:
    """在 `ginv = m·β` 这条直线上挑一个**不压散点**的 β 当标签锚点。

    从"进入轴框"的那一端往右走，取第一个离**所有**散点都足够远的位置
    （`clear` 是按轴跨度归一的门限：横向 0.11 个轴宽 ≈ 标签自身的宽度）。
    找不到就退回入口 +5%。纯确定性、无随机 —— 图上每次都在同一处。

    为什么需要它：直线从左边界进入时，`n*` 大一点的几条会正好穿过左边的
    Derby / R-77 那一带，直接按入口写就会把标签压在点上（实测就是这么压上的）。
    """
    bx = float(axis.xlim[1] - axis.xlim[0]) or 1.0
    by = float(axis.ylim[1] - axis.ylim[0]) or 1.0
    y0, y1 = float(axis.ylim[0]), float(axis.ylim[1])
    pts = list(cloud or ())
    best = None
    for i in range(0, 91):
        frac = i / 100.0
        x = x0 + frac * bx
        y = m * x
        if not (y0 + 0.012 * by <= y <= y1 - 0.012 * by):
            continue
        if best is None:
            best = x
        if all(abs(x - px) / bx > clear[0] or abs(y - py) / by > clear[1]
               for px, py in pts):
            return x
    return best if best is not None else x0 + 0.05 * bx


def _bg_nstar_lines(ax, axis: AxisSpec, levels, q_pa: float, f_mach: float,
                    cap_f: float, cloud=None) -> None:
    """等 `n*` 线族：`ginv = m·β`，`m = (n*·g0/q)²·(F/f)` —— **过原点的直线**。

    旧口径（纵轴是 γ）是双曲线 `γ = C/β`；取倒数把它拉直了，这正是"两轴单调性一致"
    的几何表现：`n*` 越大线越陡（同样的门限下转向能力更强）。

    标签贴在直线**进入轴框**的那一端（陡的从左边界进、缓的从下边界进）：
    右上一带是"双优区"，11 型弹的散点与标签都挤在那儿，往那儿写会互相压
    （第一版就是这么让 `n*=18` 骑到 `120A` 上的）。左/下两端是空的，而且参考图
    `_recon/fig2_turn_energy.svg` 的 `n*=` 标注也贴在左边界 —— 两图对得上。
    入口那一带仍可能有弹（Derby/R-77 就贴着左边界），所以再沿直线往右找一个
    不压散点的位置（`_nstar_label_x`，纯确定性）。
    """
    from . import bg as bgmod

    (x0, x1), (y0, y1) = axis.xlim, axis.ylim
    xs = np.linspace(x0, x1, 512)
    dx, dy = (x1 - x0) * 0.008, (y1 - y0) * 0.022
    for nst in levels:
        m = (float(nst) * bgmod.G0 / q_pa) ** 2 * (cap_f / f_mach)
        ax.plot(xs, m * xs, color=BG_NSTAR_COLOR, lw=1.0, ls=BG_NSTAR_LS, zorder=2)
        if m * x0 >= y0:                   # 从左边界进入
            bx = _nstar_label_x(x0, m, cloud, axis)
            by = m * bx + dy
        elif m * x1 > y0:                  # 从下边界进入
            bx = max(y0 / m, x0) + dx
            by = m * bx + dy
        else:
            continue                       # 整条线都在框下方（不该发生，兜一下）
        if by > y1 - 0.01 * (y1 - y0):
            by = y1 - 0.01 * (y1 - y0)     # 别把标签顶出上边框
        ax.text(bx, by, f"$n^*$={nst:g}", fontsize=9,
                color="#607D8B", ha="left", va="bottom", zorder=3)


def _bg_bubbles(ax, rows_, *, highlight: str = "") -> None:
    """散点 + 标签引线。点径 = 图1 的 `POINT_SIZE`；基准弹的**点与标签**都涂 `BASE_COLOR`（绿）。

    ⚠ 2026-10-01 用户拍板两点：① 点大小不再按 ΔV 缩放 —— 与图1 统一后"点的大小/字的大小"
    在两图里才一致；② 选中态只用**颜色**表达（点与标签同色），旧的基准弹空心环去掉。
    """
    ax.scatter([r.beta for r in rows_], [r.ginv for r in rows_], s=POINT_SIZE,
               c=[_pick_color(r.key, highlight, POINT_COLOR) for r in rows_],
               alpha=0.75, edgecolors="white", linewidths=1.2, zorder=4)
    for r in rows_:
        dx, dy = BG_LBL_OFFSETS.get(r.key, (13, 4))
        ha = "right" if dx < -8 else ("left" if dx > 8 else "center")
        ax.annotate(r.label, xy=(r.beta, r.ginv), xytext=(dx, dy),
                    textcoords="offset points", fontsize=LBL_FONTSIZE,
                    color=_pick_color(r.key, highlight, LBL_COLOR),
                    fontweight="bold", ha=ha, va="center", zorder=6,
                    arrowprops=LBL_LEADER)


def add_bg_header(fig, *, title: str, subtitle: str = "", levels=BG_NSTAR_LEVELS,
                  highlight: str = "", with_scan: bool = False,
                  n_points: int = 0) -> None:
    """图2 的题头。图例条目与图1 不同（等 n* 线 + 散点），不复用 `add_header`。"""
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
               markeredgecolor="white", markersize=7,
               label=LEGEND_BG_POINTS.format(n=n_points) if n_points else "弹池各型"),
    ])
    if highlight:
        # 基准弹：与图上完全一致 = **绿色实心点**（外面那圈空心环 2026-10-01 按用户要求去掉）
        handles.append(Line2D([], [], marker="o", color="none", markerfacecolor=BASE_COLOR,
                              markeredgecolor="white", markersize=7,
                              label=highlight))
    fig.text(0.5, 0.982, title, ha="center", va="top", fontsize=14, fontweight="bold")
    if subtitle:
        fig.text(0.5, 0.936, subtitle, ha="center", va="top", fontsize=10.5, color=GRAY)
    # 四条以上就分两行，免得横着挤出画布
    ncol = len(handles) if len(handles) <= 3 else 3
    leg = fig.legend(handles=handles, loc="upper center", ncol=ncol, frameon=False,
                     fontsize=9.5, bbox_to_anchor=(0.5, 0.918), borderaxespad=0.0,
                     columnspacing=1.6, handletextpad=0.5)
    _green_legend_text(leg, highlight)


def plot_bg_scan(ax, betas, ginvs, t_grid, *, step: float = 1.0, cax=None,
                 colorbar: bool = True, levels=None) -> tuple:
    """**仿真层**：把基准弹的 ΔV 固定住，在 β–ginv 网格上扫出来的命中时间等值线。

    与图1 的 `plot_isotime()` 同一个机制（同一套 `ISO_CMAP` / 线名回退标注），只是
    横纵坐标换成了 β/ginv（纵轴是 `1/γ`，见 `bg.ginv_of`）。返回 `(contour, levels, labels)`。
    """
    from .grid import iso_levels as _levels

    lv = list(levels) if levels is not None else _levels(t_grid, step)
    if not lv:
        return None, [], []
    norm = Normalize(vmin=lv[0], vmax=lv[-1]) if len(lv) > 1 else None
    use_cbar = bool(colorbar and norm is not None and cax is not None)
    colors = [ISO_CMAP(norm(v)) for v in lv] if use_cbar else BLUE
    cs = ax.contour(np.asarray(betas, dtype=float), np.asarray(ginvs, dtype=float),
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
    β、ginv 本身是弹的固有量，不随工况变。

    `scan` 给 `(betas, ginvs, t_grid)` 时叠一层**仿真层**；不给就只有参考图那一套。
    ⚠ 纵轴是 **ginv = 1/γ**（`bg.ginv_of`），不是 γ；`t_grid` 的行序跟着 ginv 走。
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
        # ⚠ 纵轴量级是 1e-2：默认刻度格式会给出 "0.0125" 这种四位小数，明文写死更稳
        # （也顺手挡住 matplotlib 自己改成 offset/sci 记法 —— 那会让"刻度是 0.0125"看不出来）。
        ax.yaxis.set_major_formatter(lambda v, _p: f"{v:.4f}")
        if scan is not None:
            betas, ginvs, t_grid = scan
            plot_bg_scan(ax, betas, ginvs, t_grid, cax=cax, colorbar=True)
        # 把散点交给标签避让：`n*` 线是从左下往右上走的，标签必须躲开弹池那一带
        _bg_nstar_lines(ax, ax_spec, nstar_levels, q_pa, f_mach, cap_f,
                        cloud=[(r.beta, r.ginv) for r in rows_])
        _bg_bubbles(ax, rows_, highlight=highlight)
        add_bg_header(fig, title=head, subtitle=sub, levels=nstar_levels,
                      highlight=highlight, with_scan=scan is not None,
                      n_points=len(rows_))
        lines = []
        for line in (footnotes or ()):
            lines.extend(wrap_lines(line))
        if lines:
            y0 = xlabel_bottom_fig(ax, fig) - FOOTNOTE_GAP
            add_footnotes(fig, lines, y0=y0)
        return save_formats(fig, out_base, formats=formats)
    finally:
        plt.close(fig)


# ===================================================================== 图4：机动想定的轨迹
#
# 图1 / 图2 的**一个字节都不动**：这一段只**追加**新函数与新常量，不改上面任何行为。
# 节内的 import 放在这里也是同一个理由 —— 3D 与刻度定位器只有图4 用得上。

import matplotlib.patches as mpatches                       # noqa: E402
import matplotlib.text as mtext                              # noqa: E402
import matplotlib.ticker as mticker                         # noqa: E402
from mpl_toolkits.mplot3d import Axes3D, proj3d             # noqa: E402,F401

#: 版式。主视图是 **3D 斜视角**（mplot3d），高度–时间面板在**它右侧**。
#:
#: ⚠ **mplot3d 的 axes 永远是物理正方形**：`Axes3D.apply_aspect()` 里写死
#: `shrunk_to_aspect(1, ...)`（与 `set_box_aspect` **无关** —— 那个只改盒子**里面**
#: 三轴的长度比例）。所以给一个"宽 > 高"的矩形时，真正落下的是 `min(宽,高)` 的正方形、
#: 水平居中。版面必须按这个事实排；按名义矩形算会得到"图例挂在空白里"或"撞上 3D 盒"。
#:
#: 为什么高度–时间面板**侧置**（而不是像 2D 版那样上下排）：3D 盒是正方形，上下排会
#: 在左右各留 3~4 in 的空白（画布宽 12.6 in），图会缩在中间一小块。侧置之后两块都吃得满。
TRAJ_FIG_SIZE = (12.6, 9.2)
TRAJ_FIG_LEFT, TRAJ_FIG_RIGHT = 0.045, 0.985
TRAJ_VIEW_RECT = (0.040, 0.355, 0.360, 0.490)   # 3D 主视图（会被收缩成正方形、居中）
TRAJ_ALT_RECT = (0.520, 0.470, 0.460, 0.320)    # 高度–时间（3D 盒右侧）
TRAJ_VIEW_ELEV = 24.0                            # 斜视角的仰角/方位角（与预览默认同族）
TRAJ_VIEW_AZIM = -60.0
#: ⚠ 竖直轴**放大系数**（这是这张图唯一一处"不按真实比例"的画法，脚注必须写明）。
#: 真按三轴真实跨度画，这张想定的盒子是 52 km × 18 km × 3.6 km —— 高度只占 x 的 7%，
#: 画出来是一片**几乎看不出高度的薄板**，而"3D 化"的全部意义就是看见高度那一维。
#: 这里把它放大到 x 显示长度的 0.45：水平两轴**仍是真实比例**，所以水平面里的 110°/90°
#: 偏角、命中点相对发射点的位置都不失真；只有竖直方向被拉伸，绝对高度读右侧副面板。
TRAJ_VIEW_ALT_GAIN = 0.45
TRAJ_LEGEND_Y = 0.862                            # 图例（题头区下沿）

TRAJ_TITLE = "机动目标想定轨迹：三维 x–z–y + 高度–时间"
TRAJ_XLABEL = "x　[m]（航向 0° = +x）"
TRAJ_ZLABEL = "z　[m]（航向 90° = +z）"
TRAJ_ALT_YLABEL = "高度 y　[m]"
TRAJ_ALT_XLABEL = "时间　t　[s]"
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
#: 导弹航迹的**两种颜色**：以导引头开机时刻 `t_beam` 为界换色（用户 2026-10-01 的要求）。
#: * `TRAJ_MISSILE_COLOR`  = 开机**前**（沿用这张图一直以来的深灰）；
#: * `TRAJ_MISSILE2_COLOR` = 开机**后**（紫色：与目标的灰/橙/红/青/蓝**五个色相都不撞**，
#:   也和发射点/节点的 `#333333` 分得开）。
#: ⚠ 只换色、**不换线型**：两段都是虚线，读者一眼就知道"这还是同一枚弹"，
#:   颜色只承担"开机前后"这一层信息。要连线型一起区分是另一条口径，改 `_missile_styles()`。
TRAJ_MISSILE_COLOR = "#4d4d4d"
TRAJ_MISSILE2_COLOR = "#8e44ad"
TRAJ_GUIDE_COLOR = "#2e7d32"
TRAJ_HIT_COLOR = "#d62728"
TRAJ_MISS_COLOR = "#8c564b"
TRAJ_SEG_LW = 2.3
TRAJ_MISSILE_LW = 1.05
TRAJ_MISSILE_LS = (0, (5, 3))
TRAJ_TRUNC_LS = (0, (4, 2))
TRAJ_MARK_COLOR = "#333333"
TRAJ_MARK_MS = 5.4

LEGEND_TRAJ_MISSILE = "导弹航迹"
LEGEND_TRAJ_MISSILE_BEFORE = "导弹航迹（导引头开机前）"
LEGEND_TRAJ_MISSILE_AFTER = "导弹航迹（开机后换色）"
LEGEND_TRAJ_GUIDE = "110° / 90° 参考方向"
#: ⚠ 文案必须与**画法**一致：被截断的段现在按 `TRAJ_TRUNC_LS` 画成虚线（见
#: `plot_traj_segments`），所以这里说"被下一条指令截断"；旧文案说"被压成一条弧"
#: 却配了一根实线 —— 图例与图是两套话。
LEGEND_TRAJ_TRUNC = "crank 没转完（被下一条指令截断）"

#: 节点名 → 图例文案。**字典顺序即图例顺序**（同名节点只占一格）。
TRAJ_MARK_LABELS = {
    "launch": "发射",
    "crank_start": "开始 crank",
    "crank_done": "crank 转完",
    "seeker_on": "导引头开机",
    "beam_start": "开始转入 39",
    "end": "命中 / 结束",
}

def _finite_xyz(row, kx: str, kz: str, ky: str):
    """取一行的 `(水平 x, 水平 z, 高度 y)`；缺值/非有限 ⇒ `None`（**不把 None 塞进 plot**）。

    ⚠ 高度这一维也必须在这里取：旧版只取 `(x, z)`，进 3D 之后那条目标航迹就会
    整条躺在高度 0 的平面上 —— 而目标是 10 km 同高飞行的，图上会差出 10 km 且**不报错**。
    """
    x, z, y = row.get(kx), row.get(kz), row.get(ky)
    if x is None or z is None or y is None:
        return None
    fx, fz, fy = float(x), float(z), float(y)
    if not (math.isfinite(fx) and math.isfinite(fz) and math.isfinite(fy)):
        return None
    return (fx, fz, fy)


def _target_xyz(run) -> list:
    """目标航迹 `[(t, x, z, y)]`（按时间排序）。"""
    out = []
    for r in run.rows or ():
        t = r.get("t")
        if t is None:
            continue
        p = _finite_xyz(r, "tx", "tz", "ty")
        if p is not None:
            out.append((float(t), p[0], p[1], p[2]))
    out.sort(key=lambda e: e[0])
    return out


def _missile_xyz(run, *, t_end: float) -> list:
    """导弹航迹 `[(t, x, z, y)]`，**只取到 `t_end`**。

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
        p = _finite_xyz(r, "x", "z", "y")
        if p is not None:
            out.append((ft, p[0], p[1], p[2]))
    out.sort(key=lambda e: e[0])
    return out


def _beam_split(run, *, t_end: float):
    """导弹航迹换色用的切分时刻 `t_beam`（取不到、或落在航迹之外 ⇒ `None`）。

    「开机」= 轨迹上**首次** `range ≤ guidance.lockDistance`（`traj.find_anchor`，一遍法反求），
    与 `results/traj_*.json` 里那个 `anchor.t_beam_s` 是同一个数 —— 图上换色的位置与产物里
    记录的 `t_beam` 必须同源，不能各算一遍。
    """
    t_beam = (run.anchor or {}).get("t_beam_s")
    if t_beam is None:
        return None
    t_beam = float(t_beam)
    if not math.isfinite(t_beam) or not (0.0 <= t_beam <= t_end + 1e-9):
        return None
    return t_beam


def _split_by_time(series, t_split):
    """把 `[(t, …)]` 序列按时刻切成 `(前, 后)`；`t_split=None` 或切了没意义 ⇒ `(全部, [])`。

    导弹航迹（主视图的 3D 点列、副面板的 `(t, 高度)` 序列）**两处都用它切**，
    口径必须一致，否则两张面板的换色点会落在不同时刻上。

    ⚠ **不插值**：切点取"最后一个 `t ≤ t_split` 的样点"，两段**共用**这个点 ⇒ 画出来接得
    上、不留空档。这与"命中点的位置取 `t_hit` 那一行"是同一条口径（出图这一层不另做时间
    算术）。时间栅格是 0.1 s 量级，所以换色位置与 `t_beam` 的差 ≤ 一个样点。
    ⚠ `(全部, [])` 这个兜底是给"`t_split` 落在第一个样点之前、或最后一个之后"用的：
    那时画两段只会得到一条 1 个点的退化线（或空线），而图例却会承诺第二种颜色。
    """
    if t_split is None or len(series) < 3:
        return (list(series), [])
    k = max((i for i, e in enumerate(series) if e[0] <= t_split + 1e-9), default=None)
    if k is None or k < 1 or k >= len(series) - 1:
        return (list(series), [])
    return (list(series[:k + 1]), list(series[k:]))


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
            before = (ft, _finite_xyz(r, "tx", "tz", "ty"))
        else:
            after = (ft, _finite_xyz(r, "tx", "tz", "ty"))
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
    """目标航迹上最接近 `t_s` 的点 `(x, z, y)`（就近取、不插值 —— 与"落在哪一行"同口径）。"""
    if not track:
        return None
    return _target_at_full(min(track, key=lambda r: abs(r[0] - t_s)))


def _target_at_full(entry):
    """`_target_xyz()` 的 4 元组 → 3 元组点（去掉时间）。"""
    return (entry[1], entry[2], entry[3]) if entry is not None else None


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
    ⚠ 图1/图2 的脚注**故意不走这里** —— 它们的字节是已交付产物，且与图4 无关。
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

    `ax` 是 3D 还是 2D 都吃（按 `ax.name == "3d"` 分派）：图4 主视图已改成三维斜视角，
    这条目标航迹必须画在**它真正的高度**上（`ty`），否则整条线会躺在高度 0 的平面上。
    """
    track = _target_xyz(run)
    if not track:
        return []
    is3d = getattr(ax, "name", "") == "3d"
    lo, hi = t_window if t_window else (track[0][0], track[-1][0])
    drawn, seen = [], set()
    for seg in run.segments or ():
        label = getattr(seg, "label", "") or ""
        if label in seen:
            continue
        t0, t1 = max(float(seg.t0_s), lo), min(float(seg.t1_s), hi)
        if t1 - t0 <= 1e-9:
            continue
        pts = [(e[1], e[2], e[3]) for e in track if t0 - 1e-9 <= e[0] <= t1 + 1e-9]
        if len(pts) < 2:
            continue
        kw = dict(color=TRAJ_COLORS.get(getattr(seg, "color_key", ""), TRAJ_FALLBACK_COLOR),
                  lw=TRAJ_SEG_LW, solid_capstyle="round", zorder=3, label=label,
                  ls=(TRAJ_TRUNC_LS if getattr(seg, "truncated", False) else "-"))
        px, pz, py = ([p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts])
        # mplot3d 的三个实参按 (x, z, 高度 y) 给 —— 内核的水平面就是 (x, z)
        if is3d:
            ax.plot(px, pz, py, **kw)
        else:
            ax.plot(px, pz, **kw)
        drawn.append(seg)
        seen.add(label)
    return drawn


def add_traj_header(fig, *, title: str, subtitle: str = "", segments=(), marks=(),
                    truncated: bool = False, missile_split: bool = False, y: float = 0.888,
                    trunc_color: str | None = None) -> None:
    """图4 的题头。图例按**这张图真正画了什么**生成（没画的段不进图例）。

    `y` 由调用方给（`TRAJ_LEGEND_Y`）：图例挂在题头区下沿的固定高度上，3D 盒是正方形、
    永远长不到那里去。
    `trunc_color` 是**真被截断那一段**的颜色：写死橙色的话，截断段换成别的阶段
    （例如 39 段被截）时图例的把手颜色就和图不一致了。
    `missile_split=True` 时导弹航迹在图上被切成**两种颜色**（导引头开机前后），
    图例就给**两格**；否则只给一格。图例不许比图多一格或少一格。
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
    if missile_split:
        handles.append(Line2D([], [], color=TRAJ_MISSILE_COLOR, lw=TRAJ_MISSILE_LW,
                              ls=TRAJ_MISSILE_LS, label=LEGEND_TRAJ_MISSILE_BEFORE))
        handles.append(Line2D([], [], color=TRAJ_MISSILE2_COLOR, lw=TRAJ_MISSILE_LW,
                              ls=TRAJ_MISSILE_LS, label=LEGEND_TRAJ_MISSILE_AFTER))
    else:
        handles.append(Line2D([], [], color=TRAJ_MISSILE_COLOR, lw=TRAJ_MISSILE_LW,
                              ls=TRAJ_MISSILE_LS, label=LEGEND_TRAJ_MISSILE))
    used = {getattr(m, "name", "") for m in marks}
    for nm, lab in TRAJ_MARK_LABELS.items():
        if nm in used:
            handles.append(Line2D([], [], color="none", marker="o", markersize=6,
                                  markerfacecolor=TRAJ_MARK_COLOR, markeredgecolor="white",
                                  label=lab))
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
    """图4 副标题：工况（range/alt/速度/航向）+ 该弹 (β, ginv)。**必须两行给全**。

    ⚠ 这里给的纵轴量同样走 `ginv = 1/γ`（用户 2026-10-04 口径，全仓一个口径）——
    换算只用 `bg.ginv_of()`，本模块不写 `1/γ`。物理 γ 仍完整记在产物 `traj_*.json` 里。
    """
    from . import bg as bgmod

    sc = run.scene
    line1 = (f"工况 {sc.range_m / 1000:g} km · 高度 {sc.alt_m / 1000:.1f} km "
             f"· 载机 {sc.vm0:g} m/s 航向 {sc.launch_heading_deg:g}° "
             f"· 敌机 {sc.target_speed_ms:g} m/s 航向 {sc.target_heading_deg:g}°")
    line2 = (f"{run.missile or '基准弹'} β = {run.beta:.0f} kg/m² "
             f"/ ginv = {bgmod.ginv_of(run.gamma):.6f} m²/kg")
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


def _traj_footnotes(run, *, truncated: bool, extend_to: float, t_hit,
                    beam_split: float | None = None, alt_true: float | None = None) -> list:
    """图4 的脚注（讲**为什么这样画**，不复述参数）；`footnotes=` 的行接在后面。

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
    out.append("三维主视图的水平两轴按真实跨度设比例（`set_box_aspect`），两轴米/英寸相同，"
               "所以几何不失真：110° 与 90° 之间那 20° 偏角、命中点相对发射点的位置都是真的。")
    if alt_true is not None and alt_true > 0:
        out.append(f"※ 竖直轴的显示长度按 x 轴的 {TRAJ_VIEW_ALT_GAIN:g} 倍画，而真实跨度比只有 "
                   f"{alt_true:.3f} —— 也就是竖向放大了约 "
                   f"{TRAJ_VIEW_ALT_GAIN / alt_true:.1f} 倍（不放大整条航迹在斜视角下就是"
                   "一薄片）；所以绝对高度一律读右侧高度–时间面板。")
    out.append("水平两轴沿用内核口径：x 对应航向 0°、z 对应航向 90°，竖直轴是高度 y。")
    if beam_split is not None:
        out.append(f"导弹航迹在导引头开机时刻 t_beam = {beam_split:.2f} s 处换色：开机前深灰、"
                   "开机后紫色 —— 两段都是虚线，因为这是同一枚弹，颜色只标阶段。")
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


def _overlap(a, b) -> float:
    """两个矩形的重叠面积（0 = 不重叠）。两个矩形要在**同一个**坐标系里（同一个口径）。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


#: "pt → 英寸"换算（figure 的 1 pt = 1/72 英寸）。
PT_PER_INCH = 72.0

#: 注记相对锚点的候选偏移 [pt]：横向四档 × 纵向十二档 = 48 个候选。
#: ⚠ 3D 盒只有 ~4.5 in（`min(rect 宽, rect 高)` 死死限住），而 9 条注记的锚点全挤在盒子
#: 的一角 —— 只给「右/左 × 六档高度」18 个候选**真的找不到空位**（实测仍有 5 条压在刻度
#: 数字与轴标题上）。横向给到 ±40 pt、纵向给到 ±122 pt 之后才有零重叠解。
TRAJ_LABEL_DX_PTS = (9.0, -9.0, 40.0, -40.0)
TRAJ_LABEL_DY_PTS = (10.0, 26.0, 42.0, 58.0, 74.0, 90.0, 106.0, 122.0,
                     -20.0, -36.0, -52.0, -68.0)
#: 注记离 3D 盒边界至少留多少（display px）：贴着边界会被盒面/刻度压住，
#: 出了盒就会飘到右边的高度–时间面板上去 —— 两个都不许。
TRAJ_LABEL_EDGE_SLACK = 2.0
#: 注记文字的最大宽度 = **3D 盒宽**的这个比例，超了就折行。
#: ⚠ 不折行不行：3D 盒的边长就是 `min(rect 宽, rect 高)`，12.6×9.2 的页面上只有 ~4.5 in，
#: 而最长的那条节点注记（含"实际航向 110.3°（11.0343 点钟）"）在 8.3 pt 下有 3.9 in ——
#: 97% 的盒宽，横向哪个方向都放不下（实测：出框 314 px，压到右边高度–时间面板的
#: y 轴标题上）。折成两行后单行 ≤ 70% 盒宽，才有得摆。
TRAJ_LABEL_WRAP_FRAC = 0.70


def _proj_frac(ax, p3):
    """三维点 `(x, z, 高度 y)` → **figure fraction** 屏幕位置。

    ⚠ `Axes3D.transData` 认的是**已经投影过**的二维坐标：三维点必须先过
    `proj3d.proj_transform(..., ax.get_proj())`。直接 `transData.transform((x, z, y))`
    会给出一个不报错、但完全不对的位置（实测三个点全部落在 (1809, 1703) 之外的鬼地方）。
    ⚠ 锚点用 fraction 而**不是** `figure pixels`：fraction 与 dpi 无关 —— 160 dpi 的画布上
    摆好之后，`save_formats` 出的 300 dpi 成品图上还是同一个位置（两条路径都实测过）。
    ⚠ `ax.get_proj()` 吃**当前**的视角与轴范围，所以调用前必须已经 `view_init()` /
    `set_box_aspect()` / `set_*lim()`，并且画布至少画过一次：`apply_aspect()` 才会把 axes
    收缩成正方形、`_unstale_viewLim()` 才会把轴范围定下来。`plot_traj` 里是先
    `fig.canvas.draw()` 再摆注记的。
    """
    u, w, _ = proj3d.proj_transform(p3[0], p3[1], p3[2], ax.get_proj())
    return tuple(ax.figure.transFigure.inverted().transform(ax.transData.transform((u, w))))


def _wrap_text_px(lab, text: str, *, max_w: float, renderer) -> str:
    """按**实测像素宽**折行：先按空格断词，单个词还是超宽再按字符拆。

    ⚠ 只按字符贪心会在**数字里面**断（实测把 "110.3°（11.0343" 断成 "11" / ".0343"），
      而注记里全是时刻与航向 —— 断在数字里比断在别处难读得多。所以先按空格断词。
    ⚠ 断点用**实测**宽，不是"字数 × 字号"估：中英混排下估宽能差 30%（同一句中文 8.3 pt：
      按字数估 300 pt、实测 231 pt），估过头会把本该两行的硬折成三行。
    ⚠ 不按词折的旧 `wrap_lines()` 那种"按显示宽度 250 列"是给**脚注**用的（整幅画布宽），
      拿来折 4.5 in 的 3D 面板上的注记会折得太宽。
    """
    if not text:
        return text

    def _w(s: str) -> float:
        lab.set_text(s)
        b = _text_bbox_px(lab, renderer)     # ⚠ 不能走 `Annotation.get_window_extent()`：含引线
        return b[2] - b[0]

    lines, cur = [], ""
    for word in text.split(" "):
        cand = f"{cur} {word}" if cur else word
        if cur and _w(cand) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
        while len(cur) > 1 and _w(cur) > max_w:      # 单个词也超宽 ⇒ 只拆这一段
            cut = len(cur) - 1
            while cut > 1 and _w(cur[:cut]) > max_w:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _axes_ink(ax, renderer) -> list:
    """轴**自己**画出来的东西的屏幕框：三个轴标题 + 所有非空刻度标签。

    ⚠ 注记必须避开它们，不能只避开坐标轴盒子：3D 的刻度标签与轴标题是画在盒子**里面**的
      （`x [m]` 实测落在盒子下缘内侧），只按盒子避让的话注记会直接压在那串数字上
      （实测 `开始 crank 至 110°（9G） t=8.00 s` 压在 "45000" 与 `x [m]` 上）。
    """
    out = []
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        for t in [axis.label, *axis.get_ticklabels()]:
            try:
                if t.get_text() in ("", None) or not t.get_visible():
                    continue
                b = t.get_window_extent(renderer=renderer)
            except Exception:                      # 某个标签还没定位 ⇒ 跳过，别把出图拖挂
                continue
            if b.width > 0 and b.height > 0:
                out.append((float(b.x0), float(b.y0), float(b.x1), float(b.y1)))
    return out


def _text_bbox_px(lab, renderer):
    """注记里**纯文字**的屏幕框 `(x0, y0, x1, y1)`（**不含引线**）。

    ⚠ `Annotation.get_window_extent()` 会把**引线**一起算进去 —— 框从文字一直拉到锚点，
      一笔 6000 px² 的巨框。拿它做避让就等于"每条注记都先给自己圈一大片禁区"，
      实测把 8 条注记摆成 5 对重叠。
    ⚠ 但也不能直接调 `Text.get_window_extent(self)` 就完事：`Annotation.get_window_extent()`
      里在量文字**之前**还有一步 `self.update_positions(renderer)`，那一步才把 `xytext`
      偏移写进文字的位置。少了它，量到的是**上一次**的位置 —— 每个候选量出来都一样，
      于是"18 个候选"退化成"永远选第一个"（实测 8 条注记全叠在 (497, 693)）。
    """
    lab.update_positions(renderer)
    bb = mtext.Text.get_window_extent(lab, renderer=renderer)
    return (float(bb.x0), float(bb.y0), float(bb.x1), float(bb.y1))


def _place_label3d(ax, text, p3, *, occupied=(), fontsize: float = 8.3,
                   color: str | None = None):
    """把注记摆到三维点 `p3` 旁，**按屏幕像素**避让 `occupied`，返回它占的 display 矩形。

    避让是**链式**的：调用方把上一次的返回值接着传进下一次调用的 `occupied`，
    于是"后放的躲开先放的"。

    ⚠ 为什么按屏幕量，而不是像旧版那样"用数据空间反算矩形"（`_data_in()` 那一套）：
    3D 轴里数据空间 → 屏幕是**投影**，两个在数据空间互不重叠的矩形投影之后完全可能叠在
    一起（点在"深"处会被压到"浅"处的旁边）—— 拿数据空间的罚分去避让，对此**完全瞎**。
    ⚠ 量的是 `Annotation.get_window_extent()`：它在 3D 轴里给**真**屏幕框（与 `proj3d` 的
    点投影逐点一致）。`Text3D.get_window_extent()` **不可信**：把它摆在盒子中心
    (0.5, 0.5, 0.5) 上，它报 (1809.57, 1703.23)，而画布只有 800×600（实测）。
    ⚠ 打分**先看重叠**：只要有一个候选与已知矩形零重叠就一定选它。旧版把重叠乘 100 倍加权，
    于是一个 0.006 的重叠（0.6 分）会输给"候选序号"那 0.04 分 —— 结果留了 1421 px² 的实叠。
    ⚠ 太长的注记**先折行**再看候选（`TRAJ_LABEL_WRAP_FRAC`）：不折的话最长那条有 97% 的盒宽，
      横向哪个方向都放不下，必然压到盒子外面去。
    """
    fig = ax.figure
    ren = fig.canvas.get_renderer()
    anchor = fig.transFigure.transform(_proj_frac(ax, p3))
    box = ax.get_window_extent(renderer=ren)
    lab = ax.annotate(text, xy=_proj_frac(ax, p3), xycoords="figure fraction",
                      xytext=(0.0, 0.0), textcoords="offset points", fontsize=fontsize,
                      color=color or TRAJ_MARK_COLOR, ha="left", va="bottom", zorder=8,
                      clip_on=False, annotation_clip=False,
                      # ⚠ 必须给**引线**：候选里最远的一档离锚点 122 pt（≈187 px），注记又统一
                      #   白底，没有引线就完全看不出它在说哪个节点（第一版就是这样：8 条注记
                      #   整整齐齐地堆在盒子中间，节点在右下角）。
                      arrowprops=dict(arrowstyle="-", color=color or TRAJ_MARK_COLOR,
                                      lw=0.6, alpha=0.75, shrinkA=1.0, shrinkB=2.0),
                      bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                edgecolor="none", alpha=0.72))
    lab.set_text(_wrap_text_px(lab, text, max_w=TRAJ_LABEL_WRAP_FRAC * float(box.width),
                               renderer=ren))
    best, best_cost = (TRAJ_LABEL_DX_PTS[0], 0.0), None
    for i, dy in enumerate(TRAJ_LABEL_DY_PTS):
        for dx in TRAJ_LABEL_DX_PTS:
            # `dx < 0` 时右对齐，文字从锚点**向左**长：目标航迹全在盒子的右半侧，
            # 只给"向右长"这一种画法的话每条注记都只能往右溢出。
            lab.set_ha("left" if dx > 0 else "right")
            # 每个候选都**实测**一次：pt → px 的换算（dpi/72）交给 matplotlib，自己乘容易差
            # 一个 1.53 倍的系数（160 dpi 下）。文字排版结果被缓存，重复量很便宜。
            lab.set_position((dx, dy))
            r = _text_bbox_px(lab, ren)
            ov = sum(_overlap(r, o) for o in occupied if o)
            oob = (max(0.0, box.x0 + TRAJ_LABEL_EDGE_SLACK - r[0])
                   + max(0.0, r[2] - (box.x1 - TRAJ_LABEL_EDGE_SLACK))
                   + max(0.0, box.y0 + TRAJ_LABEL_EDGE_SLACK - r[1])
                   + max(0.0, r[3] - (box.y1 - TRAJ_LABEL_EDGE_SLACK)))
            # 出框罚用**平方**：宁可叠一点点（还能读），也不要被画布/盒边裁成半行。
            cost = (1.0e6 if ov > 1e-9 else 0.0) + 1.0e3 * oob * oob + ov + 0.04 * i
            if best_cost is None or cost < best_cost:
                best, best_cost = (dx, dy), cost
    lab.set_ha("left" if best[0] > 0 else "right")
    lab.set_position(best)
    return _text_bbox_px(lab, ren)       # 以最终位置实测为准，回给调用方去避让


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


def _compact_m(v, _pos=None) -> str:
    """刻度压成 `10.2k`（四位数的刻度会把很窄的轴边界挤出去）。"""
    return f"{v / 1000:.1f}k" if abs(v) >= 1000 else f"{v:g}"


# ----------------------------------------------------------------- 图3：β–ginv–ΔV 交互式三维散点
#
# 图3 **不出静态 PNG**（它是一页手写 WebGL，见 `webui_static/fig3.*`），但它是第 4 张交付图，
# 所以它同样受"配色只有一个出处"这条约束：前端 `fig3.js` 里**一个颜色字面量都不许有**，
# 全部由 `fig3.palette()` 从下面这一块现取（与 `traj3d.palette()` 同一套做法）。
#
# ⚠ 三张连续色标各有各的口径，别混用：
#   * `FIG3_CMAP_T_HIT`  —— **顺序**色标，映射 `t_hit`（秒），只用于命中点；
#   * `FIG3_CMAP_RESID`  —— **发散**色标，围绕 0 对称（蓝 = 负、红 = 正），用于一次拟合残差；
#   * `FIG3_CMAP_CURV`   —— **顺序**色标（非负），用于二次项贡献 `c·(ΔV−ΔV̄)²`。
# 每根的**首末必须不同色相**（否则"值变了颜色没变"，图上完全看不出来 —— 判据在
# `tests/test_fig3.py` 里逐条钉着）。

FIG3_TITLE = ("图3 交互式三维散点：ΔV / BC（≡ β）/ ginv = 1/γ 三轴，颜色 = 命中时间 t_hit；"
              "选中弹种与工况后可出单层等时面")
FIG3_KIND = "interactive-3d-scatter"

#: 三根真实轴的标题（前端零字面量：连轴名都从这儿取）。
#: ⚠ 第二根轴标成「BC（≡ β）」：本仓库里 **β 与 BC 是同一个量**
#: （`m燃尽/(SD·CxK)`，见 `docs/BETA-GAMMA.md` §2.1），Lead 2026-10-02 的口径是
#: 「轴写 (ΔV, BC, γ)，并注明 BC ≡ β」——两种写法指的是**同一个三维空间**，不是两根轴。
#: 把 BC 与 β 当两根轴会让参数化退化（两轴共线），所以标签只能有一个名字 + 一条等价说明。
#: ⚠ 第三根轴自 2026-10-04 起是 **ginv = 1/γ [m²/kg]**（用户口径：与 β 同为"向上＝更好"），
#: 不再是 γ —— 与图2 的纵轴同一个量、同一处换算（`bg.ginv_of`）。
FIG3_AXIS_LABELS = {
    "beta": "BC（≡ β）　[kg/m²]　直飞保能 →（越大越好）",
    "ginv": "ginv = 1/γ　[m²/kg]　转向能力 →（越大越好）",
    "dv": "ΔV　[m/s]　理想（真空等效）总增速（越大越好）",
}
#: 三根轴在**三维盒子**里的方位（前端把归一化后的轴朝这三个方向摆）。
#: ⚠ 用户 2026-10-04 的口径（**本表就是那份口径的唯一出处**）：
#: ① **横轴 = ΔV** ② **纵轴 = β** ③ **1/γ 摆在"正视图里看不见的那条底面轴"上**。
#: 所以第 i 项 → 第 i 个世界轴 (x, y, z)：`dv→x` / `beta→y` / `ginv→z`。
#: 前端**不写死轴名**：它按响应里每个轴的 `role`（x/y/z）摆刻度与坐标。
FIG3_AXIS_ORDER = ("dv", "beta", "ginv")
#: `FIG3_AXIS_ORDER` 的第 i 项对应的世界轴名（前端 `role` 字段取的就是它）。
FIG3_AXIS_ROLES = ("x", "y", "z")
#: 每根轴的刻度画在哪条盒子棱上（世界坐标，盒子 = [-0.5, 0.5]³；**前端按 role 摆**）。
#: 这份描述进响应、也进脚注 —— 免得"刻度贴在哪条边"变成只有代码知道的事。
FIG3_AXIS_EDGES = {
    "dv": "前下缘（y=-0.5, z=-0.5）",
    "beta": "左竖棱（x=-0.5, z=-0.5）",
    "ginv": "底面右缘（x=+0.5, y=-0.5）",
}
#: 每根轴"往哪边是更好"。三根都是**越大越好**（用户口径）⇒ 好角 = 三轴最大角、差角 = 三轴最小角。
#: ⚠ 角部光晕的红/绿**就是从这里推出来的**（不是写死"红在下、绿在上"）：把某项改成 `"low"`，
#: 光晕的两个角会跟着换 —— 判据 `..::test_fig3_halo_corners_follow_the_axis_semantics` 有牙。
FIG3_AXIS_BETTER = {"dv": "high", "beta": "high", "ginv": "high"}
FIG3_AXIS_COLORS = {"beta": "#2661d9", "dv": "#cc3322", "ginv": "#227855"}

#: 默认相机（**唯一出处**：这里给数 → `fig3.py` 写进响应 `view` → 前端只读响应，不写死）。
#: 口径（用户 2026-10-04）："正视图"里 ΔV 读作**横向**、β 读作**竖直**、ginv 是**纵深**
#: （投影最短 ⇒ 正是"正视图里看不见的那条轴"）。视线略偏 +x/抬高，好让三根轴都看得见、
#: 且三块背面（x=-0.5 后壁 / z=+0.5 后壁 / y=-0.5 底面）朝向相机。
FIG3_VIEW_AZ = -1.25
FIG3_VIEW_EL = 0.34

#: ---- 角部光晕的常量在 `FIG3_BG_COLOR` 之后（"向白衰减"的白 = 页面底色，得先有那个常量）---

#: 命中时间：顺序色标（冷 → 暖 = 命中更快 → 更慢）。**唯一**一套点色（v4：残差/曲率不画了）。
FIG3_CMAP_T_HIT = ("#2c3e8f", "#2a7fb8", "#29a07a", "#86b93a", "#f2c230", "#e06a2b")

FIG3_BG_COLOR = "#f7f8f9"
FIG3_TEXT_COLOR = "#1f2933"
FIG3_MUTED_COLOR = "#52606d"
FIG3_BOX_COLOR = "#c9d1d9"
FIG3_MISS_COLOR = "#8c564b"
#: 等时面的半透明度（面与散点同屏时散点会被淡显）。
FIG3_LAYER_ALPHA = 0.55
#: 命中点的"图例代表色"= t_hit 色标的**中间那一档**。
#: ⚠ **不要**把它当成"命中 = 这个颜色"：命中点的颜色是连续的 t_hit，这里只是图例色块的取样。
#: 真正要守住的关系是 `FIG3_MISS_COLOR` **不在** `FIG3_CMAP_T_HIT` 里 —— 否则脱靶色会被
#: 读成"某一个 t_hit 值"，而两张色标看上去都正常。
FIG3_HIT_COLOR = FIG3_CMAP_T_HIT[2]

#: ---- 角部光晕（"四分之一球"）--------------------------------------------------
#: 好角 = 三轴**最大**角（绿）、差角 = 三轴**最小**角（红）——由 `FIG3_AXIS_BETTER` 推出，
#: 不是"红永远在下、绿永远在上"。
#: 实现口径：片元颜色 = 白底 → 红（离差角越近越浓）→ 绿（离好角越近越浓），
#: 距离用**世界坐标的三维距离** ⇒ 等色线在面上是圆弧（四分之一球的切片），不是分区涂色。
#: 三块面只画在**背对相机**的那三块（后壁 ×2 + 底面），低不透明度，且**最先画、不写深度**
#: ⇒ 永远压在散点与等时面之下（绝不挡点）。
FIG3_HALO_GOOD_COLOR = "#1f7a4d"
FIG3_HALO_BAD_COLOR = "#c0392b"
#: "向白衰减"里的那个白 = 页面底色（不是再发明一个颜色）。
FIG3_HALO_BASE_COLOR = FIG3_BG_COLOR
FIG3_HALO_ALPHA = 0.42
#: 衰减半径（**归一化盒单位**：盒棱长 1.0、体对角线 ≈ 1.732）。取 0.92 ⇒ 两个角斑几乎铺满
#: 三块面、在中间各自衰减到看不见，但不会把整块面糊成灰。
FIG3_HALO_RADIUS = 0.92
#: 衰减指数（越大越集中在角上）。
FIG3_HALO_POWER = 1.6
FIG3_HALO_NOTE = ("角部光晕：红 = 三轴最小角（差角），绿 = 三轴最大角（好角）——"
                  "三根轴都是越大越好，所以颜色由角部向中间衰减到白底。")

FIG3_LEGEND_HIT = "命中（填色 = t_hit）"
FIG3_LEGEND_MISS = "脱靶（空心标记，没有 t_hit）"
FIG3_LEGEND_INDUCED = "诱导阻力主导（R ≥ 1）"

#: 颜色模式（v4 只剩一种 —— 用户明确"残差不需要了"，不再有拟合平面/残差/曲率/热力图）。
#: `unit` 与 `note` 会**原样进图例**，所以口径必须写在这儿（前端不自己编）。
FIG3_MODES = (
    {"id": "t_hit", "label": "命中时间 t_hit", "unit": "s",
     "note": "逐点实测命中时间；脱靶点没有这个量，一律画成空心标记。"},
)

#: 口径脚注（前端 HUD 直接显示，避免"看图的人以为轴是别的量"）。
#: ⚠ 这里的文本会**原样进页面**（`fig3.py` → JSON → `fig3.js`），所以不许出现 markdown 星号
#: —— `-k printed_text` 与 `-k fig3` 都扫这一块（页面侧星号只有源码判据能兜住）。
FIG3_FOOTNOTES = (
    "三根轴 = ΔV / BC（≡ β）/ ginv = 1/γ，单位 [m/s] / [kg/m²] / [m²/kg]，颜色 = t_hit [s]；"
    "ΔV 是理想（真空等效）总增速，只改推力乘数 thrust_scale = ΔV/ΔV_blk。",
    "BC 与 β 恒等（都是 m燃尽/(SD·CxK)）⇒ 轴写 (ΔV, BC, ginv) 与 (ΔV, β, ginv) 是同一个空间；"
    "写成 (ΔV, BC, β) 会让两轴共线、参数化退化。",
    "第三根轴 ginv = 1/γ 是 γ 的倒数（用户 2026-10-04 口径）：两根「越大越好」的量画在一起，"
    "所以「向外」一律是更好。γ 仍是内核口径的转向损失 [kg/m²]、公式一字未改，"
    "注入内核前由 bg.gamma_of() 落回 γ。",
    "三维摆位（用户 2026-10-04 口径）：横轴 = ΔV、纵轴 = BC（≡ β）、1/γ 摆在「正视图里看不见的"
    "那条底面轴」上；三根轴的范围各自按当前弹池自适应（ΔV 与图1 同口径、β/ginv 与图2 同口径，"
    "只选一枚弹时轴会收紧），所以轴上不会出现写死的固定区间。",
    "角部光晕（用户 2026-10-04 口径）：红 = 三轴最小角（差角）、绿 = 三轴最大角（好角）——"
    "三根轴都是越大越好，光晕由角部按三维距离向中间衰减到白底（等色线是圆弧，不是分区涂色）。",
    "等时面 = t_hit(ΔV, BC, ginv) = 该层值的等值面（marching tetrahedra，与图1/图2 的等时线同一套"
    "层定义 grid.iso_levels）。脱靶格子会让面被截断 ⇒ 开口是常态，界面上如实标出闭合与否。",
    "11 枚弹共用同一套 (β,ginv,ΔV) 网格与同一条色标范围（切换弹种只换点云与统计，不跳色标），"
    "所以横向比较是同一把尺子。",
    "ginv 与 cx_aoa 反向 ∝（ginv 越大 ⇒ 诱导阻力/攻角阻力那一支越弱）；"
    "「诱导阻力主导」判定 = R = (n_ref/n*)² ≥ 1，n* = q/(Q·g0)、Q = sqrt(β·F/(f·ginv))。",
    "工况默认是图4 那套（直飞 → crank → 39），但 39 指令时刻「固定」在 35.0 s（共用工况）："
    "图4 是每枚弹按自己的导引头开机时刻 + 反应延迟反求，图3 要跨 11 枚弹比，必须共用同一个想定。",
)


def iso_label(level) -> str:
    """`t` 层的**唯一**文案格式（图3 的滑块刻度 / 面角标 / HUD 都用它）。

    ⚠ 图1/图2 的等时线标签是 matplotlib 的 `clabel`（默认只打数字），这里**不动它们**——
    动一下两张图的 SVG 就变了、字节复现判据会红。"同源"落在**层定义**上
    （`grid.iso_levels()`，三条链路共用），不落在标签文本上。
    """
    return f"t = {float(level):g} s"



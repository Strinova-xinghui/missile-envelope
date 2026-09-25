# -*- coding: utf-8 -*-
"""交叉图：主动弹「总增速—弹道系数」散点 + 仿真等命中时间线（本阶段唯一主图）。

横轴 = 总增速 ΔV [m/s]，纵轴 = 简化弹道系数 BC，
散点 = 各型主动弹按 blkx 原始参数算出的 (ΔV, BC)（口径见 scripts/missile_metrics.py），
曲线 = 本仿真器在 ΔV×BC 网格上给出的等命中时间线。

视觉规格**复用** `E:\\WT\\War-Thunder-Datamine\\自动化分析` 工作流
（`skills/wt-aam-analysis/references/charts.md` §一 共用规格，勿自行发明）：
    画布 figsize=(12, 6.8) dpi=110，白底
    横轴 800~1110（主刻度 30 / 次刻度 10）
    纵轴 2450~3850（主刻度 100 / 次刻度 50）
    主网格 alpha .35 lw .8；次网格 alpha .18 lw .5；网格压在数据下方
    导出 PNG(300 dpi) / PDF / SVG，bbox_inches='tight' pad_inches=0.25

线性拟合（y = kx + b、R²）**已移除**：等命中时间线取代了它的功能，不再计算。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402

from missile_sim import aero  # noqa: E402
from missile_sim.config import cxk_for_bc, load_config  # noqa: E402
from missile_sim.plot import setup_style  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = ROOT / "figures"
RES_DIR = ROOT / "results"
MISSILE_JSON = RES_DIR / "missile_points.json"

# 当前基准（AIM-120C5，最新版口径）
CURRENT = "120C"

# ---------------------------------------------------------------- 视觉规格（冻结）
# 来源：自动化分析/skills/wt-aam-analysis/references/charts.md
FIG_SIZE = (12.0, 6.8)
FIG_DPI = 110
SAVE_DPI = 300
XLIM = (800.0, 1110.0)          # aam_fit（仅当前版本）收紧规格
YLIM = (2450.0, 3850.0)
X_MAJOR, X_MINOR = 30.0, 10.0
Y_MAJOR, Y_MINOR = 100.0, 50.0
RED = "#D32F2F"                 # 数据点
RED_DARK = "#B71C1C"            # 当前基准 / 点标签
BLUE = "#1F77B4"                # 工作流里的"线"色
GRAY = "#555555"
# 等时线配色：深 = 命中时间短（性能好），浅 = 命中时间长（浅端不取太淡，保证白底可见）
ISO_CMAP = LinearSegmentedColormap.from_list(
    "iso_time", ["#0A2A48", "#134E80", "#2472A4", "#3E93BE", "#5FB0CE"])

# 画布内边距（供像素换算：等时线线名要按像素退让，避免压边框）
AX_RECT = (0.075, 0.175, 0.822, 0.700)   # left, bottom, width, height（figure 坐标）
AX_PX = (AX_RECT[2] * FIG_SIZE[0] * FIG_DPI, AX_RECT[3] * FIG_SIZE[1] * FIG_DPI)

# 出图元数据：三种格式都不写创建时间，保证同一份数据每次重跑字节一致
# （否则 git 里每次都是一片假 diff；SVG 还另有随机 id，见 normalize_svg_ids）
SAVE_META = {
    "png": {"Software": None},
    "pdf": {"CreationDate": None, "ModDate": None},
    "svg": {"Date": None},
}

# 点标签偏移（原图短名 -> (dx, dy)），照抄参考图排布，避免压线
LBL_OFFSETS = {
    "AAM-4": (-6, 13), "120A": (-34, -4), "120C": (10, -16), "120D": (-8, 15),
    "MICA": (-12, -20), "PL-12": (-44, 0), "PL-12A": (10, -18),
    "R-Darter": (-16, 12), "Derby": (-40, -14), "R-77": (-34, -16), "R-77-1": (-72, 14),
}


def load_missiles_for(source: str):
    """按口径取弹值（默认 latest = 最新版工作区 blkx，权威公式见 missile_metrics.py）。

    latest  最新版（工作区 blkx = 实机 2.59.0.11）——出图默认
    base257 2.57.1.132 基线（= 参考图那一版）
    figure  参考图像素读出的点
    """
    import missile_sources

    try:
        rows = missile_sources.load_source(source)
    except FileNotFoundError as exc:
        raise SystemExit(f"{exc}（先运行 scripts\\build_missile_sources.py）") from exc
    if not rows:
        raise SystemExit(f"口径 {source} 未取到任何弹")
    return rows


def parse_pair(text: str, name: str) -> tuple[float, float]:
    parts = str(text).split(",")
    if len(parts) != 2:
        raise SystemExit(f"--{name} 需形如 a,b（例如 --{name} 800,1110）")
    lo, hi = float(parts[0]), float(parts[1])
    if not hi > lo:
        raise SystemExit(f"--{name} 上界必须大于下界")
    return lo, hi


def iso_levels(t_grid: np.ndarray, step: float) -> list[float]:
    """网格内的等时线等级（只取 t 实际覆盖到的整数，避免空等级）。"""
    finite = t_grid[np.isfinite(t_grid)]
    if not finite.size or step <= 0:
        return []
    lo = math.ceil(finite.min() / step - 1e-9) * step
    hi = math.floor(finite.max() / step + 1e-9) * step
    if hi < lo:
        return []
    n = int(round((hi - lo) / step)) + 1
    return [float(lo + i * step) for i in range(n)]


def border_label_points(cs, keep: list[float], xlim, ylim, *, back_px: float = 54.0):
    """给 clabel(manual=...) 生成落点：贴着**出口边框**内侧，沿折线回退 back_px 像素。

    每条等时线都是从左上（顶边或左边）进来、往右下（右边或下边）出去，
    所以把线名统一放在出口附近，既不压中部的弹型标签区，也不会互相叠。
    回退量按像素算（横纵坐标量纲差 10 倍，不能用同一个数据单位）。
    """
    sx = (xlim[1] - xlim[0]) / AX_PX[0]       # 横轴 [m/s]/px
    sy = (ylim[1] - ylim[0]) / AX_PX[1]       # 纵轴 [BC]/px
    pts = []
    for lv in keep:
        try:
            idx = list(cs.levels).index(lv)
        except ValueError:
            continue
        segs = [s for s in cs.allsegs[idx] if s is not None and len(s) >= 2]
        if not segs:
            continue
        seg = max(segs, key=len)
        if seg[0][0] > seg[-1][0]:            # 统一成"左 -> 右"
            seg = seg[::-1]
        j = len(seg) - 1                      # 出口端
        dist = 0.0
        while j > 0 and dist < back_px:
            dist += math.hypot((seg[j][0] - seg[j - 1][0]) / sx,
                               (seg[j][1] - seg[j - 1][1]) / sy)
            j -= 1
        pts.append((float(seg[j][0]), float(seg[j][1])))
    return pts


def normalize_svg_ids(path: Path) -> None:
    """把 matplotlib 写进 SVG 的随机元素 id 改成顺序 id（`m2cdfbf5598` -> `id_00000`）。

    matplotlib 的 SVG 后端用 `id(obj)`（内存地址）当元素 id，前缀有 `m`（标记/路径）、
    `p`（裁剪路径）、`image`（内嵌位图）等，几何完全相同也会整篇变，git 里看不出真实差异。
    这里只替换"确实出现在 `id="..."` 里的"随机形状 token（字母 + ≥5 位十六进制），
    因此 `figure_1` / `line2d_1` 这类稳定 id 与颜色等十六进制串都不会被误伤。
    """
    text = path.read_text(encoding="utf-8")
    ids: list[str] = []
    for m in re.finditer(r'\bid="([A-Za-z]+[0-9a-f]{5,})"', text):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    if not ids:
        return
    mapping = {old: f"id_{i:05d}" for i, old in enumerate(ids)}
    pat = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in ids) + r")\b")
    text = pat.sub(lambda m: mapping[m.group(0)], text)
    path.write_text(text, encoding="utf-8", newline="")   # 保持原行尾，不做 \n -> \r\n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="主动弹 总增速—弹道系数 散点 + 等命中时间线（视觉规格复用自动化分析工作流）")
    ap.add_argument("--vm0", type=float, default=None)
    ap.add_argument("--vt", type=float, default=None)
    ap.add_argument("--alt", type=float, default=None)
    ap.add_argument("--target-alt", type=float, default=None)
    ap.add_argument("--range", type=float, default=None)
    ap.add_argument("--loft", type=float, default=None)
    # 坐标轴规格（默认 = 自动化分析工作流 aam_fit 当前版规格）
    ap.add_argument("--xlim", type=str, default="800,1110", help="横轴范围 如 800,1110")
    ap.add_argument("--ylim", type=str, default="2450,3850", help="纵轴范围 如 2450,3850")
    # 等时线网格（与 1 s 步长相匹配：横 1 s≈39 m/s、纵 1 s≈110 BC）
    ap.add_argument("--dv-min", type=float, default=None)
    ap.add_argument("--dv-max", type=float, default=None)
    ap.add_argument("--dv-step", type=float, default=10.0)
    ap.add_argument("--bc-min", type=float, default=None)
    ap.add_argument("--bc-max", type=float, default=None)
    ap.add_argument("--bc-step", type=float, default=25.0)
    ap.add_argument("--iso-step", type=float, default=1.0, help="等时线步长 [s]（默认 1）")
    ap.add_argument("--iso-label-every", type=float, default=0.0,
                    help="每隔多少秒标注一次线名（0 = 自动：线数 ≤24 时每条都标；1/5 = 固定间隔）")
    ap.add_argument("--colorbar", action=argparse.BooleanOptionalAction, default=True,
                    help="等时线按命中时间着色并配色标（--no-colorbar = 单色蓝线）")
    ap.add_argument("--aero", choices=["legacy", "mach", "full"], default=None,
                    help="气动模型（默认取配置）：legacy=旧口径；mach=+f(M)；full=+升力/诱导阻力")
    ap.add_argument("--source", choices=["latest", "base257", "figure"], default="latest",
                    help="弹值口径：latest=最新版工作区 blkx（默认）；base257=参考图那一版；figure=图像素点")
    ap.add_argument("--formats", type=str, default="png,pdf,svg",
                    help="导出格式，逗号分隔（默认与自动化分析工作流一致：png,pdf,svg）")
    ap.add_argument("--tag", type=str, default="crossplot")
    args = ap.parse_args(argv)

    cfg = load_config()
    # 口径：默认最新版（工作区 blkx，权威公式见 scripts/missile_metrics.py）
    missiles = load_missiles_for(args.source)
    dv_pts = [m["dv"] for m in missiles]
    bc_pts = [m["bc"] for m in missiles]

    if args.vm0 is not None:
        cfg.scenario.vm0 = args.vm0
    if args.vt is not None:
        cfg.scenario.vt = args.vt
    if args.alt is not None:
        cfg.scenario.alt = args.alt
    if args.target_alt is not None:
        cfg.scenario.target_alt = args.target_alt
    if args.range is not None:
        cfg.scenario.range = args.range
    if args.loft is not None:
        cfg.sim.theta_loft_deg = args.loft
    if not (0.0 <= cfg.sim.theta_loft_deg < 40.0):
        print("错误：高抛角必须在 [0, 40) 度范围内", file=sys.stderr)
        return 2
    if args.aero is not None:
        cfg.aero.model = args.aero

    xlim = parse_pair(args.xlim, "xlim")
    ylim = parse_pair(args.ylim, "ylim")
    # 等时线网格默认铺满坐标轴范围，等时线才会画到边框
    cfg.sweep.dv_min = args.dv_min if args.dv_min is not None else xlim[0]
    cfg.sweep.dv_max = args.dv_max if args.dv_max is not None else xlim[1]
    cfg.sweep.dv_step = args.dv_step
    cfg.sweep.bc_min = args.bc_min if args.bc_min is not None else ylim[0]
    cfg.sweep.bc_max = args.bc_max if args.bc_max is not None else ylim[1]
    cfg.sweep.bc_step = args.bc_step

    out_of_box = [m["label"] for m in missiles
                  if not (xlim[0] <= m["dv"] <= xlim[1] and ylim[0] <= m["bc"] <= ylim[1])]
    if out_of_box:
        print(f"提示：{len(out_of_box)} 型落在坐标轴范围外，图中会被裁掉：{'、'.join(out_of_box)}")

    from missile_sim.sweep import build_grid, run_sweep

    grid = build_grid(cfg)
    n_case = int(grid.shape[0] * grid.shape[1])
    print(
        f"坐标轴 横 {xlim[0]:.0f}~{xlim[1]:.0f}（主 {X_MAJOR:g}/次 {X_MINOR:g}），"
        f"纵 {ylim[0]:.0f}~{ylim[1]:.0f}（主 {Y_MAJOR:g}/次 {Y_MINOR:g}）"
    )
    print(
        f"等时线网格 {grid.shape[0]}×{grid.shape[1]} = {n_case} 工况："
        f"ΔV {grid.dv.min():.0f}~{grid.dv.max():.0f} /{grid.dv_step:g}，"
        f"BC {grid.bc.min():.0f}~{grid.bc.max():.0f} /{grid.bc_step:g}，步长 {args.iso_step:g} s"
    )
    print(
        f"工况：vm0={cfg.scenario.vm0:.0f}, vt={cfg.scenario.vt:.0f}, "
        f"alt={cfg.scenario.alt:.0f}, R0={cfg.scenario.range:.0f}, "
        f"loft={cfg.sim.theta_loft_deg:.1f}°, 引信={cfg.sim.hit_radius:.0f} m"
    )
    aero_label = aero.MODEL_LABELS[aero.params_from_config(cfg).model]
    print(f"气动模型：{aero_label}")
    t0 = time.perf_counter()
    res, grid, t_grid = run_sweep(cfg, grid, theta_loft_deg=cfg.sim.theta_loft_deg)
    wall = time.perf_counter() - t0
    hit = res.status == 1
    print(f"仿真 {wall:.1f} s，命中 {int(hit.sum())}/{hit.size}（{hit.mean() * 100:.0f}%）")

    # ---------------------------------------------------------------- 出图
    setup_style()
    fig = plt.figure(figsize=FIG_SIZE, dpi=FIG_DPI)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes(list(AX_RECT))
    cax = fig.add_axes([0.905, AX_RECT[1], 0.013, AX_RECT[3]])

    levels = iso_levels(t_grid, args.iso_step)
    norm = Normalize(vmin=levels[0], vmax=levels[-1]) if len(levels) > 1 else None
    use_cbar = args.colorbar and norm is not None
    cs = None
    if levels:
        if use_cbar:
            colors = [ISO_CMAP(norm(v)) for v in levels]
        else:
            colors = BLUE
        cs = ax.contour(grid.dv, grid.bc, t_grid.T, levels=levels, colors=colors,
                        linewidths=1.15, alpha=0.95, zorder=2)
        if use_cbar:
            sm = plt.cm.ScalarMappable(norm=norm, cmap=ISO_CMAP)
            sm.set_array([])
            cb = fig.colorbar(sm, cax=cax)
            cb.set_label("命中时间 $t_{hit}$ [s]", fontsize=9.5, color=GRAY)
            cb.ax.yaxis.set_major_locator(MultipleLocator(5))
            cb.ax.yaxis.set_major_formatter(lambda v, _p: f"{v:g}")
            cb.ax.tick_params(labelsize=8.5)
            cb.outline.set_edgecolor("#BBBBBB")
        else:
            cax.set_visible(False)
        # 线名：贴着出口边框排（线越多间隔越大，密了也不打架）
        label_every = args.iso_label_every
        if label_every <= 0 and levels:
            label_every = args.iso_step if len(levels) <= 24 else \
                args.iso_step * math.ceil(len(levels) / 24.0)
        if label_every > 0:
            keep = [lv for lv in levels
                    if abs(lv / label_every - round(lv / label_every)) < 1e-9]
            pts = border_label_points(cs, keep, xlim, ylim)
            if pts:
                texts = ax.clabel(cs, levels=keep, manual=pts, inline=True,
                                  inline_spacing=4, fontsize=8.3,
                                  fmt=lambda v: f"{v:g} s")
                for t_ in texts:
                    t_.set_zorder(3)
                    t_.set_color(ISO_CMAP(0.0) if use_cbar else "#123B5E")
                    t_.set_fontweight("normal")
    else:
        cax.set_visible(False)

    # ---- 主图层：所选口径（默认最新版工作区 blkx） ----
    src_txt = missiles[0].get("source", "弹值")
    src_short = "最新版 blkx 弹值" if "WORK" in src_txt else f"{src_txt} 弹值"
    ax.scatter(dv_pts, bc_pts, s=72, c=RED, edgecolors="white", linewidths=0.9,
               zorder=4, label=f"{src_short}（{len(missiles)} 型）")
    # 基准弹（120C）加一圈环，便于一眼定位
    for m in missiles:
        if (m.get("label") or m["name"]) == CURRENT:
            ax.scatter([m["dv"]], [m["bc"]], s=210, facecolors="none",
                       edgecolors=RED_DARK, linewidths=1.4, zorder=5,
                       label=f"基准 {CURRENT}（高抛 {cfg.sim.theta_loft_deg:.0f}° 参考）")
            break

    for m in missiles:
        label = m.get("label") or m["name"]
        dx, dy = LBL_OFFSETS.get(label, (7, 8))
        is_cur = label == CURRENT
        ax.annotate(label, (m["dv"], m["bc"]), textcoords="offset points", xytext=(dx, dy),
                    fontsize=9.5, color=RED_DARK if is_cur else "#C62828",
                    fontweight="bold" if is_cur else "normal", zorder=6)

    # ---- 坐标轴 / 网格：照 charts.md 共用规格 ----
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.xaxis.set_major_locator(MultipleLocator(X_MAJOR))
    ax.xaxis.set_minor_locator(MultipleLocator(X_MINOR))
    ax.yaxis.set_major_locator(MultipleLocator(Y_MAJOR))
    ax.yaxis.set_minor_locator(MultipleLocator(Y_MINOR))
    ax.grid(True, which="major", alpha=0.35, linewidth=0.8)
    ax.grid(True, which="minor", alpha=0.18, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_color("#888888")
        ax.spines[side].set_linewidth(0.8)
    ax.set_xlabel(r"总增速 $\Delta V$  (m/s)", fontsize=11.5)
    ax.set_ylabel("简化弹道系数 (BC)", fontsize=11.5)

    # ---- 标题（主标题 + 副标题） ----
    fig.suptitle("主动弹 总增速–弹道系数 与 等命中时间线",
                 fontsize=14, fontweight="bold", color="#1A1A1A", y=0.985)
    scen = (f"{cfg.scenario.range / 1000:.0f} km "
            f"{'迎头' if cfg.scenario.vt < 0 else ('尾追' if cfg.scenario.vt > 0 else '静止')}"
            f"（{cfg.scenario.vm0:.0f} / {cfg.scenario.vt:.0f} m/s）· "
            f"高度 {cfg.scenario.alt / 1000:.1f} km")
    if cfg.scenario.target_alt is not None and abs(cfg.scenario.target_alt - cfg.scenario.alt) > 1.0:
        scen += f"（目标 {cfg.scenario.target_alt / 1000:.1f} km）"
    scen += (f" · 高抛 {cfg.sim.theta_loft_deg:.0f}° · 引信 {cfg.sim.hit_radius:.0f} m"
             f" · 等时线步长 {args.iso_step:g} s")
    ax.set_title(scen, fontsize=10.2, color=GRAY, pad=24)

    # ---- 图例：搬到坐标区**上方**（图内左下角会压住 72/73 s 两条线名） ----
    handles, labels = ax.get_legend_handles_labels()
    if cs is not None:
        mid = BLUE if not use_cbar else ISO_CMAP(norm(levels[len(levels) // 2]))
        handles = [Line2D([], [], color=mid, lw=1.6, label="等命中时间线")] + handles
    leg = ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0),
                    ncol=3, frameon=False, fontsize=8.6, handlelength=1.5,
                    handletextpad=0.55, columnspacing=1.7, borderaxespad=0.3)
    leg.set_zorder(7)

    # ---- 脚注：数据口径与命中率（不写拟合式，拟合已移除） ----
    aero_short = aero.MODEL_NAMES[aero.params_from_config(cfg).model]
    foot1 = (f"等时线 = 本仿真器在 ΔV×BC 网格（{grid.shape[0]}×{grid.shape[1]} = {n_case} 工况）上算出的"
             f"命中时间，步长 {args.iso_step:g} s；命中率 {hit.mean() * 100:.0f}%"
             f"（{int(hit.sum())}/{hit.size}），未命中处曲线自动断开；"
             f"气动模型 = {aero_short}（--aero legacy 可复现旧口径）。")
    foot2 = (f"红点 = {src_txt}（11 型主动弹，WORK = 实机 2.59.0.11），ΔV/BC 口径："
             "自动化分析/skills/wt-aam-analysis/scripts/plot_version_compare.py :: metrics()；"
             "坐标轴与网格规格同该工作流 charts.md。")
    fig.text(0.012, 0.088, foot1, fontsize=8.3, color="#444444")
    fig.text(0.012, 0.040, foot2, fontsize=8.3, color="#444444")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fmts = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    outs = []
    for ext in fmts:
        out = FIG_DIR / f"fig_missile_bc_overlay_{args.tag}.{ext}"
        fig.savefig(out, bbox_inches="tight", pad_inches=0.25,
                    dpi=SAVE_DPI if ext == "png" else None,
                    metadata=SAVE_META.get(ext))
        if ext == "svg":
            normalize_svg_ids(out)
        outs.append(out)
    plt.close(fig)
    for out in outs:
        print(f"交叉图：{out}")

    # ---------------------------------------------------------------- 逐条结果
    print(f"\n各型弹在本次弹道下的结果（{src_txt}）：")
    print(f"{'弹':<10} {'ΔV':>7} {'BC':>7} {'两级':>5} {'状态':>10} {'t_hit':>7} {'V命中':>7} {'Hmax':>8}")
    rows = []
    for m in missiles:
        cx = float(cxk_for_bc(m["bc"], cfg))
        r = simulate_one(cfg, Case(dv_total=m["dv"], cxk=cx), record_trace=False)
        label = m.get("label") or m["name"]
        print(f"{label:<10} {m['dv']:7.1f} {m['bc']:7.1f} "
              f"{'是' if m.get('two_stage') else '否':>5} {r.status_name:>10} "
              f"{(r.t_hit if r.hit else float('nan')):7.2f} {r.v_impact:7.1f} {r.max_alt:8.0f}")
        rows.append({"name": m["name"], "label": label,
                     "dv": m["dv"], "bc": m["bc"], "cxk": cx,
                     "two_stage": m.get("two_stage"), "dry_kg": m.get("dry"),
                     "k": m.get("k"), "d_mm": m.get("d_mm"),
                     "status": r.status_name, "t_hit": None if not r.hit else r.t_hit,
                     "v_impact": r.v_impact, "max_alt": r.max_alt})
    (RES_DIR / f"missile_shot_{args.tag}.json").write_text(
        json.dumps({"source": src_txt,
                    "formula": ("自动化分析/skills/wt-aam-analysis/scripts/"
                                "plot_version_compare.py :: metrics()"),
                    "axis_spec": {"xlim": list(xlim), "ylim": list(ylim),
                                  "x_major": X_MAJOR, "x_minor": X_MINOR,
                                  "y_major": Y_MAJOR, "y_minor": Y_MINOR,
                                  "source": "自动化分析/skills/wt-aam-analysis/references/charts.md"},
                    "scenario": {"vm0": cfg.scenario.vm0, "vt": cfg.scenario.vt,
                                 "alt": cfg.scenario.alt, "range": cfg.scenario.range,
                                 "target_alt": cfg.scenario.target_alt,
                                 "theta_loft_deg": cfg.sim.theta_loft_deg},
                    "isoline": {"step_s": args.iso_step, "levels": levels,
                                "grid_shape": list(grid.shape), "cases": n_case,
                                "dv_step": args.dv_step, "bc_step": args.bc_step,
                                "colored": bool(use_cbar), "wall_s": wall,
                                "hit_rate": float(hit.mean())},
                    "figure": {"file": f"figures/fig_missile_bc_overlay_{args.tag}.png",
                               "formats": fmts, "dpi": SAVE_DPI,
                               "figsize": list(FIG_SIZE), "no_linear_fit": True},
                    "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n逐条结果 JSON：{RES_DIR / f'missile_shot_{args.tag}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

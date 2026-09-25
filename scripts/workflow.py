"""端到端工作流：用户自定义输入 → 仿真 → 出对比图。

一个输入文件（JSON）或一组 `--set 键=值` 覆盖，产出：

    figures/workflow_<tag>_main.png      主对比图（等时线 + 弹值散点 + 出处面板 + 逐弹结果表）
    figures/workflow_<tag>_detail.png    细节图（t_hit–BC 切面、初始距离影响、弹道对比）
    results/workflow_<tag>.csv           网格逐工况结果
    results/workflow_<tag>_isolines.csv  等时线折线顶点
    results/workflow_<tag>.json          汇总（含输入、派生量、逐弹结果、命中率）

可从代码调用（`run_workflow(cfg_dict)`），也可命令行：
    python scripts/workflow.py run --config configs/workflow_example.json
    python scripts/workflow.py run --set scenario.range=70000 --set sim.theta_loft_deg=30
    python scripts/workflow.py web            # 本地网页表单（不依赖第三方库）
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from missile_sim.config import (  # noqa: E402
    PRO_BACKEND_HINT,
    apply_standard,
    ballistic_coefficient,
    cxk_for_bc,
    delta_v_equiv,
    load_config,
    s_ref,
    validate,
)
from missile_sim.plot import (  # noqa: E402
    LBL_COLOR,
    LBL_FONTSIZE,
    MISSILE_LBL_OFFSETS,
    SAVE_META,
    apply_crossplot_spec,
    setup_style,
)
from missile_sim.provenance import provenance, summary_line  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402
from missile_sim.sweep import (  # noqa: E402
    SweepGrid,
    build_grid,
    extract_isolines,
    monotonic_report,
    run_sweep,
    write_isolines_csv,
)

ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = ROOT / "figures"
RES_DIR = ROOT / "results"
SAVE_DPI_FIG = 300          # 工作流图此前用默认 dpi；固定下来以保证字节可复现

DEFAULT_CONFIG = ROOT / "configs" / "workflow_example.json"
MISSILE_JSON = RES_DIR / "missile_points.json"
REFERENCE_JSON = RES_DIR / "reference_points.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 弹名 → 图上的短标签
FIGURE_LABELS = {
    "AIM-120A (2.58.0.27)": "120A", "AIM-120C-5 (2.58.0.27)": "120C",
    "AIM-120D (2.58.0.27)": "120D", "AAM-4": "AAM-4", "MICA EM (new)": "MICA",
    "PL-12": "PL-12", "PL-12A": "PL-12A", "R-Darter": "R-Darter",
    "Derby": "Derby", "R-77": "R-77", "R-77-1": "R-77-1",
}
REFERENCE_BASE_NAME = "120C"

# 表内短名（与交叉图 / 图上标签一致）
SHORT_NAMES = {
    "AIM-120A/B": "120A", "AIM-120C-5/7": "120C", "AIM-120D": "120D",
    "AAM-4": "AAM-4", "MICA-EM": "MICA", "PL-12": "PL-12", "PL-12A": "PL-12A",
    "R-77/RVV-AE": "R-77", "R-77-1/RVV-SD": "R-77-1",
    "Derby": "Derby", "R-Darter": "R-Darter",
}


def load_wt_missiles():
    """弹值口径：**最新版**（工作区 blkx，公式见 scripts/missile_metrics.py）。

    等同 missile_sources.load_source("latest")；数据由 scripts/build_missile_sources.py 生成。
    """
    import missile_sources

    return missile_sources.load_source("latest")


# --------------------------------------------------------------------------- 配置


def merge_config(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for section, values in (override or {}).items():
        if isinstance(values, dict) and isinstance(out.get(section), dict):
            out[section].update(values)
        else:
            out[section] = values
    return out


def apply_set_overrides(cfg: dict, pairs) -> dict:
    """`--set a.b=1` 形式覆盖，支持点路径与 JSON 字面量。"""
    out = copy.deepcopy(cfg)
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--set 需要 键=值 形式，收到：{item}")
        key, raw = item.split("=", 1)
        node = out
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        node[parts[-1]] = value
    return out


def build_sim_config(cfg: dict):
    """把工作流输入映射到仿真器配置对象。

    **覆盖顺序固定为：后端 → 标准弹（apply_standard）→ 气动 → sim → scenario**。
    标准弹会覆写 `caliber/length/wing_area_mult/mass/cxk/hit_radius/t_life/theta_loft_deg/
    a_lat_max_g/n_base`，所以**显式覆盖必须排在它之后**（写反了会被标准弹悄悄冲掉）。
    `sim.theta_loft_deg` / `hit_radius` / `t_life` 只有输入里**显式给了**才覆盖。
    """
    mcfg = load_config()
    be = cfg.get("backend", {})
    mcfg.backend = str(be.get("name", "flash") if isinstance(be, dict) else be).strip().lower()
    if mcfg.backend == "pro":
        raise SystemExit(f"错误：{PRO_BACKEND_HINT}")

    std = cfg.get("standard", {}) or {}
    if "name" in std:
        mcfg.standard.name = str(std["name"])
    if "burn" in std:
        mcfg.standard.burn = str(std["burn"])
    if "tag" in std:
        mcfg.standard.tag = str(std["tag"])
    apply_standard(mcfg)

    if "model" in (cfg.get("aero") or {}):
        mcfg.aero.model = str(cfg["aero"]["model"])
    sim = cfg.get("sim", {}) or {}
    if "loft_rule" in sim:
        mcfg.sim.loft_rule = str(sim["loft_rule"])
    if "theta_loft_deg" in sim:
        mcfg.sim.theta_loft_deg = float(sim["theta_loft_deg"])
    if "hit_radius" in sim:
        mcfg.sim.hit_radius = float(sim["hit_radius"])
    if "dt" in sim:
        mcfg.sim.dt = float(sim["dt"])
    if "t_life" in sim:
        mcfg.sim.t_life = float(sim["t_life"])

    scen = cfg.get("scenario", {}) or {}
    for key, attr in (("vm0", "vm0"), ("vt", "vt"), ("alt", "alt")):
        if key in scen:
            setattr(mcfg.scenario, attr, float(scen[key]))
    if "range" in scen:
        mcfg.scenario.range = float(scen["range"])
    if "target_alt" in scen and scen["target_alt"] is not None:
        mcfg.scenario.target_alt = float(scen["target_alt"])

    validate(mcfg)
    if not (0.0 <= mcfg.sim.theta_loft_deg < 40.0):
        raise SystemExit(f"高抛角必须在 [0, 40) 度范围内，收到 {mcfg.sim.theta_loft_deg}")
    return mcfg


def iso_grid_from_config(cfg: dict, mcfg) -> SweepGrid:
    s = cfg.get("sweep", {})
    mcfg.sweep.dv_min = float(s.get("dv_min", 810.0))
    mcfg.sweep.dv_max = float(s.get("dv_max", 1110.0))
    mcfg.sweep.dv_step = float(s.get("dv_step", 20.0))
    mcfg.sweep.bc_min = float(s.get("bc_min", 2450.0))
    mcfg.sweep.bc_max = float(s.get("bc_max", 3800.0))
    mcfg.sweep.bc_step = float(s.get("bc_step", 50.0))
    return build_grid(mcfg)


# --------------------------------------------------------------------------- 逐弹评估


def load_blkx_missiles():
    """保留 blkx 复算口径（scripts/extract_missile_points.py 的产物），仅作对照。"""
    if not MISSILE_JSON.exists():
        return []
    return json.loads(MISSILE_JSON.read_text(encoding="utf-8"))


def evaluate_missiles(mcfg, missiles, dv_override=None, bc_override=None) -> list:
    """把每个弹的 (ΔV, BC) 送进同一条弹道，返回逐条结果。

    **逐弹切换标准弹**：该型自己的几何/质量/推力剖面/引信半径/寿命/过载上限都生效
    （与交叉图、`native_compare.py` 的口径一致）。某型不在池里时退回传入的 `mcfg` 并在行内标注。
    """
    rows = []
    for m in missiles:
        label = m.get("label") or SHORT_NAMES.get(m.get("name", ""), m.get("name", ""))
        c = copy.deepcopy(mcfg)
        c.standard.name = label
        err = None
        try:
            apply_standard(c)
        except Exception as exc:                       # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        dv = float(dv_override) if dv_override is not None else float(m["dv"])
        bc = float(bc_override) if bc_override is not None else float(m["bc"])
        cx = float(cxk_for_bc(bc, c))
        r = simulate_one(c, Case(dv_total=dv, cxk=cx), record_trace=False)
        rows.append({
            "name": m["name"],
            "label": label,
            "standard": label if err is None else None,
            "standard_error": err,
            "profile_hash": c.profile.profile_hash() if c.profile else None,
            "dv": dv,
            "bc": bc,
            "cxk": cx,
            "status": r.status_name,
            "hit": bool(r.hit),
            "t_hit": None if not r.hit else float(r.t_hit),
            "v_impact": float(r.v_impact),
            "max_alt": float(r.max_alt),
            "min_range": float(r.min_range),
            "min_range_linear": float(r.min_range_linear),
            "t_loft_end": float(r.t_loft_end),
            "hit_radius_m": float(c.sim.hit_radius),
            "t_life_s": float(c.sim.t_life),
        })
    return rows


# --------------------------------------------------------------------------- 出图


def _colors():
    return {
        "reference_dot": "#c62828",
        "reference_fit": "#2b7bba",
        "blkx_dot": "#1b5e20",
        "iso": "#1f4e79",
        "base": "#7b1fa2",
    }


def plot_main(cfg, mcfg, grid, t_grid, blkx_rows, *, out: Path, iso_step: float,
              title: str, traj_note: str, prov_block: dict | None = None) -> Path:
    setup_style()
    iso = cfg.get("compare", {})
    col = _colors()
    fig = plt.figure(figsize=(13.2, 7.6))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.55, 1.0], height_ratios=[1.0, 0.62], wspace=0.22, hspace=0.32)
    ax = fig.add_subplot(gs[:, 0])
    ax_fit = fig.add_subplot(gs[0, 1])
    ax_tab = fig.add_subplot(gs[1, 1])
    ax_tab.axis("off")

    # --- 等时线
    finite = t_grid[np.isfinite(t_grid)]
    levels = []
    if finite.size:
        lo = np.floor(finite.min() / iso_step) * iso_step
        hi = np.ceil(finite.max() / iso_step) * iso_step
        levels = list(np.arange(max(iso_step, lo), hi + iso_step * 0.5, iso_step))
    if levels:
        cs = ax.contour(grid.dv, grid.bc, t_grid.T, levels=levels, colors=col["iso"],
                        linewidths=1.1, alpha=0.9)
        iso_proxy = plt.Line2D([], [], color=col["iso"], lw=1.3, label="等命中时间线 [s]")
        for seg_list, lv in zip(cs.allsegs, cs.levels):
            for seg in seg_list:
                if seg is None or len(seg) < 2:
                    continue
                mid = seg[len(seg) // 2]
                ax.annotate(f"{lv:.0f}", (mid[0], mid[1]), textcoords="offset points", xytext=(2, 3),
                            fontsize=8, color=col["iso"], zorder=6)
                break
    else:
        iso_proxy = None

    # --- 弹点（最新版口径：工作区 blkx，公式见 scripts/missile_metrics.py）
    if blkx_rows:
        dv_b = [r["dv"] for r in blkx_rows]
        bc_b = [r["bc"] for r in blkx_rows]
        ax.scatter(dv_b, bc_b, s=46, c=col["reference_dot"], zorder=4,
                   label=f"最新版弹值（{len(blkx_rows)} 型）")
        # 逐点型号标签：与交叉图共用固定偏移与样式（charts.md §二/§四）
        for r in blkx_rows:
            lbl = r.get("label") or SHORT_NAMES.get(r["name"], r["name"])
            dx, dy = MISSILE_LBL_OFFSETS.get(lbl, (7, 8))
            ax.annotate(lbl, (r["dv"], r["bc"]), textcoords="offset points", xytext=(dx, dy),
                        fontsize=LBL_FONTSIZE, color=LBL_COLOR, fontweight="bold", zorder=6)

    # --- 当前基准点
    dv0 = delta_v_equiv(mcfg)
    bc0 = ballistic_coefficient(mcfg.drag.cxk, mcfg)
    if grid.dv.min() <= dv0 <= grid.dv.max() and grid.bc.min() <= bc0 <= grid.bc.max():
        ax.scatter([dv0], [bc0], marker="*", s=240, c=col["base"], edgecolors="white",
                   linewidths=0.8, zorder=7, label=f"当前基准 (ΔV={dv0:.0f}, BC={bc0:.0f})")

    ax.set_xlabel("总增速 ΔV_total [m/s]")
    ax.set_ylabel("简化弹道系数 BC   [kg/m²]")
    scen = (f"发射 {mcfg.scenario.vm0:.0f} m/s，目标 {mcfg.scenario.vt:.0f} m/s"
            f"（{'迎头' if mcfg.scenario.vt < 0 else ('尾追' if mcfg.scenario.vt > 0 else '静止')}），"
            f"高度 {mcfg.scenario.alt / 1000:.1f} km")
    if mcfg.scenario.target_alt is not None and abs(mcfg.scenario.target_alt - mcfg.scenario.alt) > 1.0:
        scen += f"（目标 {mcfg.scenario.target_alt / 1000:.1f} km）"
    scen += (f"，水平距离 {mcfg.scenario.range / 1000:.0f} km，"
             f"高抛 {mcfg.sim.theta_loft_deg:.0f}°，引信 {mcfg.sim.hit_radius:.0f} m")
    std_name = (prov_block or {}).get("standard", {}).get("name")
    std_note = f"标准弹 {std_name}   |   " if std_name else ""
    ax.set_title(f"{title}\n{scen}   |   {std_note}等时线步长 {iso_step:g} s", fontsize=11, pad=26)
    ax.grid(alpha=0.28)
    handles, labels = ax.get_legend_handles_labels()
    if iso_proxy is not None:
        handles = [iso_proxy] + handles
    apply_crossplot_spec(ax)
    # 图例移到轴外、横向一行（与交叉图/参考图同做法）：轴内的左下图例会压住
    # Derby / MICA / R-77 这簇点的标签
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.004), ncol=3,
              frameon=False, fontsize=8.6, handlelength=1.6, handletextpad=0.55,
              columnspacing=1.8, borderaxespad=0.2)

    # --- 右上：出处面板（后端 / 标准弹 / 燃烧 / 高抛 / 气动 —— 替代原"ΔV–BC 拟合关系"，
    #     拟合已由等时线取代，见 README §4 与 AERO_PLAN §17.5 的决定）
    ax_fit.set_title("本图出处（provenance）", fontsize=10)
    ax_fit.axis("off")
    prov = prov_block or {}
    std = prov.get("standard") or {}
    burn = prov.get("burn") or {}
    loft = prov.get("loft") or {}
    lines = [
        ("后端", str(prov.get("backend", "flash"))),
        ("标准弹", f"{std.get('name') or '（未启用）'} @ {std.get('tag') or '—'}"),
        ("参数指纹", str(std.get("profile_hash") or "—")),
        ("ΔV / BC / 干重", f"{std.get('dv', float('nan')):.1f} m/s / "
                            f"{std.get('bc', float('nan')):.0f} / {std.get('dry_mass', float('nan')):.1f} kg"),
        ("燃烧", (f"{burn.get('model')} · " + " + ".join(
            f"{t_:.0f}N/{d_:g}s" for t_, d_ in (burn.get("stages_thrust_n_s") or [])))
            if burn.get("stages_thrust_n_s") else str(burn.get("model"))),
        ("高抛", f"规则 {loft.get('rule')} · 目标 {loft.get('elevation_deg')}° · "
                 f"退出 |dLOS/dt|≥{loft.get('target_omega_max_dps')}°/s 或 LOS≤{loft.get('target_elevation_deg')}°"),
        ("气动 / dt", f"{prov.get('aero_model')} / {prov.get('dt')} s"),
        ("引信 / 寿命", f"{prov.get('hit_radius_m')} m / {prov.get('t_life_s')} s"),
        ("网格 / 命中率", f"{grid.shape[0]}×{grid.shape[1]} · "
                           f"{np.isfinite(t_grid).sum()}/{t_grid.size} 有解"),
    ]
    for i, (k, v) in enumerate(lines):
        y = 0.93 - i * 0.098
        ax_fit.text(0.02, y, k, fontsize=8.6, color="#444444", va="top", transform=ax_fit.transAxes)
        ax_fit.text(0.30, y, v, fontsize=8.6, color="#111111", va="top", transform=ax_fit.transAxes)
    if std.get("fallbacks"):
        ax_fit.text(0.02, 0.02, f"[!] 全局回退：{'、'.join(std['fallbacks'])}",
                    fontsize=8.0, color="#a04000", va="bottom", transform=ax_fit.transAxes)

    # --- 右下：逐弹结果表（表内用短名）
    rows = [("弹", "ΔV", "BC", "t_hit[s]", "V命中")]
    for r in blkx_rows:
        label = r.get("label") or SHORT_NAMES.get(r["name"], r["name"])
        rows.append((label, f"{r['dv']:.0f}", f"{r['bc']:.0f}",
                     f"{r['t_hit']:.1f}" if r["t_hit"] else "—", f"{r['v_impact']:.0f}"))
    ax_tab.set_title("各型弹在本次弹道下的结果（最新版弹值）", fontsize=10, pad=2)
    table = ax_tab.table(cellText=rows[1:], colLabels=rows[0], loc="lower center",
                         colWidths=[0.26, 0.16, 0.16, 0.20, 0.20], cellLoc="center",
                         bbox=[0.0, 0.0, 1.0, 0.86])
    table.auto_set_font_size(False)
    table.set_fontsize(8.0)
    for j in range(len(rows[0])):
        table[0, j].set_facecolor("#eef2f7")
        table[0, j].set_text_props(fontweight="bold")
        table[0, j].set_height(0.10)

    fig.text(0.01, -0.02, traj_note, fontsize=8.5, color="#444444")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=SAVE_DPI_FIG, metadata=SAVE_META.get("png"))
    plt.close(fig)
    return out


def plot_detail(cfg, mcfg, grid, t_grid, blkx_rows, *, out: Path, ranges, iso_step: float) -> Path:
    setup_style()
    col = _colors()
    fig, axes = plt.subplots(1, 3, figsize=(16.0, 4.6))

    # 1) 同一 ΔV 下 t_hit 随 BC 变化
    ax = axes[0]
    dv_pick = [grid.dv[0], grid.dv[len(grid.dv) // 2], grid.dv[-1]]
    for dv in dv_pick:
        i = int(np.argmin(np.abs(grid.dv - dv)))
        ax.plot(grid.bc, t_grid[i, :], lw=1.5, label=f"ΔV={grid.dv[i]:.0f} m/s")
    ax.set_xlabel("弹道系数 BC [kg/m²]")
    ax.set_ylabel("命中时间 [s]")
    ax.set_title("同 ΔV 下 命中时间 随 BC", fontsize=10)
    ax.grid(alpha=0.28)
    ax.legend(fontsize=8.5)

    # 2) 命中时间随初始距离
    ax = axes[1]
    for dv in dv_pick[:2]:
        th = []
        rr = []
        for r0 in ranges:
            c2 = copy.deepcopy(mcfg)
            c2.scenario.range = float(r0)
            res = simulate_one(c2, Case(dv_total=float(dv), cxk=float(cxk_for_bc(3300.0, c2))),
                               record_trace=False)
            rr.append(r0 / 1000.0)
            th.append(res.t_hit if res.hit else np.nan)
        ax.plot(rr, th, "o-", lw=1.4, label=f"ΔV={dv:.0f} m/s, BC=3300")
    ax.set_xlabel("初始距离 [km]")
    ax.set_ylabel("命中时间 [s]")
    ax.set_title("命中时间 随初始距离（空缺点=未命中）", fontsize=10)
    ax.grid(alpha=0.28)
    ax.legend(fontsize=8.5)

    # 3) 弹道剖面对比（最新版里 ΔV 最高/最低两型）
    ax = axes[2]
    if blkx_rows:
        ordered = sorted(blkx_rows, key=lambda r: r["dv"])
        picks = [ordered[0], ordered[-1]]
        for r in picks:
            cx = float(cxk_for_bc(r["bc"], mcfg))
            res = simulate_one(mcfg, Case(dv_total=r["dv"], cxk=cx), record_trace=True, stride=20)
            if res.trace is not None and len(res.trace.t):
                tr = res.trace
                ax.plot(tr.x / 1000.0, tr.h / 1000.0, lw=1.5,
                        label=f"{r['name']} (ΔV={r['dv']:.0f}, BC={r['bc']:.0f})")
    ax.set_xlabel("水平距离 [km]")
    ax.set_ylabel("高度 [km]")
    ax.set_title("弹道剖面（ΔV 最低/最高的两型）", fontsize=10)
    ax.grid(alpha=0.28)
    ax.legend(fontsize=8.5)

    fig.suptitle(f"细节：ΔV–BC 网格（{grid.shape[0]}×{grid.shape[1]}）、距离扫描、弹道剖面", fontsize=11)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=SAVE_DPI_FIG, metadata=SAVE_META.get("png"))
    plt.close(fig)
    return out


def _baseline_t_hit(mcfg) -> float | None:
    """当前基准（标准弹自带 ΔV/BC）的单工况命中时间，供 summary 对照。"""
    r = simulate_one(mcfg, Case(dv_total=delta_v_equiv(mcfg), cxk=mcfg.drag.cxk),
                     record_trace=False)
    return float(r.t_hit) if r.hit else None


# --------------------------------------------------------------------------- 主流程


def run_workflow(user_cfg: dict, *, verbose: bool = True) -> dict:
    """执行完整工作流：扫描 → 逐弹评估 → 出图 → 落盘，返回汇总字典。"""
    cfg = merge_config(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")), user_cfg or {})
    mcfg = build_sim_config(cfg)
    grid = iso_grid_from_config(cfg, mcfg)
    comp = cfg.get("compare", {})
    iso_step = float(comp.get("iso_step", 10.0))
    tag = str(comp.get("tag", "workflow"))
    title = str(comp.get("title", "主动弹总增速—弹道系数 上的等命中时间线"))

    if verbose:
        print(f"[0/5] {summary_line(provenance(mcfg))}")
        print(f"[1/5] 网格 {grid.shape[0]}×{grid.shape[1]} = {grid.shape[0] * grid.shape[1]} 工况"
              f"（ΔV {grid.dv.min():.0f}~{grid.dv.max():.0f}/{grid.dv_step:g}，"
              f"BC {grid.bc.min():.0f}~{grid.bc.max():.0f}/{grid.bc_step:g}）")
        print(f"      工况：vm0={mcfg.scenario.vm0:.0f}, vt={mcfg.scenario.vt:.0f}, "
              f"alt={mcfg.scenario.alt:.0f}, R0={mcfg.scenario.range:.0f}, "
              f"loft={mcfg.sim.theta_loft_deg:.1f}°, 引信={mcfg.sim.hit_radius:.0f} m")

    t0 = time.perf_counter()
    res, grid, t_grid = run_sweep(mcfg, grid, theta_loft_deg=mcfg.sim.theta_loft_deg)
    wall_sweep = time.perf_counter() - t0
    hit = res.status == 1
    issues = monotonic_report(t_grid, grid)
    if verbose:
        print(f"[2/5] 扫描完成 {wall_sweep:.1f} s：命中 {int(hit.sum())}/{hit.size}"
              f"（{hit.mean() * 100:.0f}%），单调性违例 {len(issues)}")

    # 逐弹：原图口径 + blkx 复算口径
    # 弹值口径：最新版（工作区 blkx，公式见 scripts/missile_metrics.py）
    wt_missiles = [dict(m) for m in load_wt_missiles()]
    blkx_rows = evaluate_missiles(mcfg, wt_missiles) if wt_missiles else []
    if verbose:
        print(f"[3/5] 逐弹评估：最新版 {len(blkx_rows)} 型，"
              f"命中 {sum(1 for r in blkx_rows if r['hit'])}/{len(blkx_rows)}")

    # 出图
    iso_lines = extract_isolines(t_grid, grid, step=iso_step)
    if not iso_lines:
        lo, hi = _nanmin(res.t_hit), _nanmax(res.t_hit)
        print(f"[!] 警告：等时线步长 {iso_step:g} s 在本次网格上抽不出任何等时线"
              f"（命中时间 {lo}~{hi} s）——请调小 compare.iso_step（默认 1 s）")
    traj_note = (f"网格命中率 {hit.mean() * 100:.1f}%（{int(hit.sum())}/{hit.size}）；"
                 f"等时线 {len({s['level'] for s in iso_lines})} 层；"
                 f"散点=最新版弹值（工作区 blkx，权威公式）；★=当前基准 "
                 f"(ΔV={delta_v_equiv(mcfg):.0f}, BC={ballistic_coefficient(mcfg.drag.cxk, mcfg):.0f})")
    prov = provenance(mcfg)
    main_png = plot_main(cfg, mcfg, grid, t_grid, blkx_rows,
                         out=FIG_DIR / f"workflow_{tag}_main.png", iso_step=iso_step,
                         title=title, traj_note=traj_note, prov_block=prov)
    ranges = [mcfg.scenario.range * f for f in (0.4, 0.7, 1.0, 1.4)]
    detail_png = plot_detail(cfg, mcfg, grid, t_grid, blkx_rows,
                             out=FIG_DIR / f"workflow_{tag}_detail.png", ranges=ranges, iso_step=iso_step)
    if verbose:
        print(f"[4/5] 出图：{main_png.name} / {detail_png.name}")

    # 落盘
    RES_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RES_DIR / f"workflow_{tag}.csv"
    _write_csv(res, grid, t_grid, csv_path)
    iso_csv = write_isolines_csv(iso_lines, RES_DIR / f"workflow_{tag}_isolines.csv", mcfg)
    summary = {
        "input": cfg,
        # 产物自描述：哪个后端 / 哪型标准弹（含指纹）/ 燃烧与高抛档位 —— 三处产物共用同一实现
        "provenance": prov,
        "provenance_line": summary_line(prov),
        "derived": {
            "s_ref_m2": s_ref(mcfg),
            "m_end_kg": mcfg.mass.mass_end,
            "m_launch_kg": mcfg.mass.mass_launch,
            "dv_baseline": delta_v_equiv(mcfg),
            "bc_baseline": ballistic_coefficient(mcfg.drag.cxk, mcfg),
            "cxk_baseline": mcfg.drag.cxk,
            "t_hit_baseline_s": _baseline_t_hit(mcfg),
        },
        "grid": {"n_dv": int(grid.shape[0]), "n_bc": int(grid.shape[1]),
                 "n_cases": int(grid.shape[0] * grid.shape[1]),
                 "dv_step": grid.dv_step, "bc_step": grid.bc_step},
        "results": {
            "n_hit": int(hit.sum()), "hit_rate": float(hit.mean()),
            "t_hit_min": _nanmin(res.t_hit), "t_hit_max": _nanmax(res.t_hit),
            "monotonic_issues": len(issues),
            "iso_levels": sorted({s["level"] for s in iso_lines}),
        },
        "missiles": blkx_rows,
        # 兼容旧读者：下面两个键是 `missiles` 的别名（历史上误写成同一份数据的两份）
        "missiles_blkx": blkx_rows,
        "missiles_wt": blkx_rows,
        "figures": [str(main_png.relative_to(ROOT)), str(detail_png.relative_to(ROOT))],
        "artifacts": [str(csv_path.relative_to(ROOT)), str(iso_csv.relative_to(ROOT))],
        "wall_time_s": wall_sweep,
    }
    json_path = RES_DIR / f"workflow_{tag}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if verbose:
        print(f"[5/5] 落盘：{csv_path.name} / {iso_csv.name} / {json_path.name}")
    summary["_paths"] = {"main_png": str(main_png), "detail_png": str(detail_png),
                         "csv": str(csv_path), "json": str(json_path)}
    return summary


def _write_csv(res, grid, t_grid, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["dv_total", "bc", "cxk", "status_name", "t_hit_s", "min_range_linear_m",
            "max_alt_m", "v_impact_ms", "t_loft_end_s"]
    status_name = np.array([res.status_name(i) for i in range(res.status.size)], dtype=object)
    data = {
        "dv_total": res.dv_total, "bc": res.bc, "cxk": res.cxk, "status_name": status_name,
        "t_hit_s": res.t_hit, "min_range_linear_m": res.min_range_linear,
        "max_alt_m": res.max_alt, "v_impact_ms": res.v_impact, "t_loft_end_s": res.t_loft_end,
    }
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for k in range(res.status.size):
            row = []
            for c in cols:
                v = data[c][k]
                if isinstance(v, str):
                    row.append(v)
                elif v is None or (isinstance(v, float) and np.isnan(v)):
                    row.append("nan")
                else:
                    row.append(f"{float(v):.6g}")
            w.writerow(row)
    return path


def _nanmin(a):
    a = np.asarray(a)[np.isfinite(a)]
    return float(a.min()) if a.size else None


def _nanmax(a):
    a = np.asarray(a)[np.isfinite(a)]
    return float(a.max()) if a.size else None


# --------------------------------------------------------------------------- CLI


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导弹弹道工作流：自定义输入 → 仿真 → 对比图")
    sub = ap.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="执行完整工作流")
    p_run.add_argument("--config", default=None, help="输入 JSON（默认 configs/workflow_example.json）")
    p_run.add_argument("--set", action="append", default=[], help="点路径覆盖，如 --set scenario.range=70000")
    p_run.add_argument("--tag", default=None, help="产物文件名后缀")
    p_run.add_argument("--quiet", action="store_true")

    sub.add_parser("web", help="启动本地网页表单（标准库实现）")

    args = ap.parse_args(argv)
    if args.cmd in (None, "run"):
        base = json.loads(Path(args.config or DEFAULT_CONFIG).read_text(encoding="utf-8")) \
            if (args.cmd == "run") else json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        cfg = apply_set_overrides(base, getattr(args, "set", []))
        if getattr(args, "tag", None):
            cfg.setdefault("compare", {})["tag"] = args.tag
        summary = run_workflow(cfg, verbose=not getattr(args, "quiet", False))
        print("\n产物：")
        for key, val in summary["_paths"].items():
            print(f"  {key:12s} {val}")
        return 0
    if args.cmd == "web":
        from workflow_web import serve

        return serve()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

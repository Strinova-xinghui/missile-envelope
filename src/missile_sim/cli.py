"""命令行入口：

    python -m missile_sim                       # 用 configs/baseline.json 跑单工况
    python -m missile_sim --vm0 300 --vt -300 --alt 10000 --range 50000 --loft 22
    python -m missile_sim --sweep               # 跑 ΔV × BC 扫描 + 等命中时间线出图
    python -m missile_sim --sweep --bc-step 50 --dv-step 25

输入约定：--vt 为负表示迎头（距离闭合），为正表示尾追（距离拉开）。
高抛角 --loft 必须在 [0, 40) 度。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import burn as burn_mod
from . import provenance as prov_mod
from . import standard as standard_mod
from .config import (
    BACKENDS,
    PRO_BACKEND_HINT,
    MissileConfig,
    apply_standard,
    ballistic_coefficient,
    cxk_for_bc,
    delta_v_equiv,
    isp_equiv,
    load_config,
    s_ref,
    summary_lines,
    validate,
)
from .decide import STATUS_LABELS, STATUS_NAMES, ST_HIT
from .plot import plot_baseline_curve, plot_loft_family, plot_sweep, plot_trajectories
from .sim import Case, simulate_one
from .sweep import (
    RESULT_DIR,
    build_grid,
    extract_isolines,
    monotonic_report,
    run_sweep,
    summary_dict,
    write_cases_csv,
    write_isolines_csv,
    write_summary,
)

FIG_DIR = Path(__file__).resolve().parents[2] / "figures"


def _apply_overrides(cfg: MissileConfig, args) -> MissileConfig:
    """施加 CLI 覆盖。**标准弹/燃烧档必须最先处理**，否则会被标准弹解析覆盖掉。"""
    if getattr(args, "backend", None) is not None:
        cfg.backend = args.backend
    if getattr(args, "standard", None) is not None or getattr(args, "burn", None) is not None:
        if args.standard is not None:
            cfg.standard.name = args.standard
        if args.burn is not None:
            cfg.standard.burn = args.burn
        apply_standard(cfg)
    if getattr(args, "ve_equiv", None) is not None:
        cfg.impulse.ve_equiv_override = args.ve_equiv
    if args.vm0 is not None:
        cfg.scenario.vm0 = args.vm0
    if args.vt is not None:
        cfg.scenario.vt = args.vt
    if args.alt is not None:
        cfg.scenario.alt = args.alt
    if args.range is not None:
        cfg.scenario.range = args.range
    if args.target_alt is not None:
        cfg.scenario.target_alt = args.target_alt
    if args.loft is not None:
        cfg.sim.theta_loft_deg = args.loft
    if getattr(args, "loft_rule", None) is not None:
        cfg.sim.loft_rule = args.loft_rule
    if args.dv is not None:
        cfg.sweep.dv_min = cfg.sweep.dv_max = args.dv
    if args.dv_min is not None:
        cfg.sweep.dv_min = args.dv_min
    if args.dv_max is not None:
        cfg.sweep.dv_max = args.dv_max
    if args.dv_step is not None:
        cfg.sweep.dv_step = args.dv_step
    if args.bc is not None:
        cfg.sweep.bc_min = cfg.sweep.bc_max = args.bc
    if args.bc_min is not None:
        cfg.sweep.bc_min = args.bc_min
    if args.bc_max is not None:
        cfg.sweep.bc_max = args.bc_max
    if args.bc_step is not None:
        cfg.sweep.bc_step = args.bc_step
    if args.drag_base is not None:
        cfg.drag.drag_base = args.drag_base
    if args.hit_radius is not None:
        cfg.sim.hit_radius = args.hit_radius
    if getattr(args, "t_life", None) is not None:
        cfg.sim.t_life = args.t_life
    if args.bc_anchor is not None:
        cfg.mass.mass_anchor = "m_end" if args.bc_anchor == "dry" else "m_launch"
    if args.aero is not None:
        cfg.aero.model = args.aero
    if args.clip_lift_peak is not None:
        cfg.aero.clip_lift_peak = args.clip_lift_peak
    validate(cfg)
    return cfg


def _run_single(cfg: MissileConfig, args) -> int:
    dv = args.dv if args.dv is not None else delta_v_equiv(cfg)
    bc = args.bc if args.bc is not None else ballistic_coefficient(cfg.drag.cxk, cfg)
    cxk = cxk_for_bc(bc, cfg)
    mass = args.mass
    print("—— 基准参数 ——")
    for line in summary_lines(cfg):
        print("  " + line)
    print("  " + prov_mod.summary_line(prov_mod.provenance(cfg)))
    print(f"  本次工况：ΔV={dv:.1f} m/s, BC={bc:.1f} -> CxK={cxk:.5f}, 等效比冲={isp_equiv(dv):.1f} s"
          + (f", 弹体质量={mass:.3f} kg" if mass else ""))
    print(
        f"  发射 {cfg.scenario.vm0:.0f} m/s，目标 {cfg.scenario.vt:.0f} m/s"
        f"（{'迎头' if cfg.scenario.vt < 0 else ('尾追' if cfg.scenario.vt > 0 else '静止')}），"
        f"高度 {cfg.scenario.alt:.0f} m"
        + (f"（目标 {cfg.scenario.target_alt:.0f} m）" if cfg.scenario.target_alt is not None else "")
        + f"，距离 {cfg.scenario.range:.0f} m，高抛 {cfg.sim.theta_loft_deg:.1f}°"
    )

    t0 = time.perf_counter()
    res = simulate_one(cfg, Case(dv_total=dv, cxk=cxk, mass=mass), record_trace=True, stride=args.stride)
    wall = time.perf_counter() - t0

    print("\n—— 结果 ——")
    print(f"  状态          : {res.status_name} ({res.status_label})")
    if res.hit:
        print(f"  命中时间      : {res.t_hit:.3f} s")
    print(f"  最小距离      : {res.min_range:.3f} m")
    print(f"  飞行终止时刻  : {res.t_end:.3f} s")
    print(f"  高抛结束时刻  : {res.t_loft_end:.3f} s" if res.t_loft_end >= 0 else "  高抛结束时刻  : 未退出（一直处于高抛段）")
    print(f"  最大高度      : {res.max_alt:.1f} m")
    print(f"  终止速度      : {res.v_impact:.1f} m/s")
    print(f"  最小距离处导引比 N_eff : {res.n_eff_at_min_range:.3f}")
    print(f"  终端航向误差  : {res.terminal_gamma_error_at_min_range_deg:.3f} °")
    print(f"  单工况耗时    : {wall * 1000:.0f} ms")

    if res.trace is not None and args.figure:
        out = plot_trajectories(
            [res.trace],
            [f"ΔV={dv:.0f} m/s, BC={bc:.0f}"],
            cfg,
            out=Path(args.figure),
        )
        print(f"  弹道图        : {out}")

    if args.json:
        payload = {
            "scenario": {
                "vm0": cfg.scenario.vm0, "vt": cfg.scenario.vt,
                "alt": cfg.scenario.alt, "range": cfg.scenario.range,
                "theta_loft_deg": cfg.sim.theta_loft_deg,
            },
            "case": {"dv_total": dv, "bc": bc, "cxk": cxk},
            "result": {
                "status": res.status_name,
                "t_hit_s": None if not res.hit else res.t_hit,
                "min_range_m": res.min_range,
                "t_end_s": res.t_end,
                "t_loft_end_s": res.t_loft_end,
                "max_alt_m": res.max_alt,
                "v_impact_ms": res.v_impact,
                "n_eff_at_min_range": res.n_eff_at_min_range,
                "terminal_gamma_error_deg": res.terminal_gamma_error_at_min_range_deg,
            },
        }
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  结果 JSON     : {args.json}")
    return 0


def _run_sweep(cfg: MissileConfig, args) -> int:
    grid = build_grid(cfg, dv_step=args.dv_step, bc_step=args.bc_step)
    mass_arr = None if args.mass is None else np.full(grid.shape[0] * grid.shape[1], float(args.mass))
    print(
        f"—— 扫描 ——\n  网格 {grid.shape[0]} × {grid.shape[1]} = {grid.shape[0] * grid.shape[1]} 工况\n"
        f"  ΔV {grid.dv.min():.0f}~{grid.dv.max():.0f} 步长 {grid.dv_step:g} m/s\n"
        f"  BC {grid.bc.min():.0f}~{grid.bc.max():.0f} 步长 {grid.bc_step:g}\n"
        f"  CxK {cxk_for_bc(grid.bc.max(), cfg):.4f}~{cxk_for_bc(grid.bc.min(), cfg):.4f}（由 BC 反解，锚定 {cfg.mass.mass_anchor}）\n"
        f"  工况：vm0={cfg.scenario.vm0:.0f}, vt={cfg.scenario.vt:.0f}, alt={cfg.scenario.alt:.0f}, "
        f"R0={cfg.scenario.range:.0f}, loft={cfg.sim.theta_loft_deg:.1f}°, hit_radius={cfg.sim.hit_radius:.0f} m"
        + (f", 弹体质量={args.mass:.1f} kg" if args.mass else "")
    )

    t0 = time.perf_counter()

    def progress(step, total, active):
        print(f"    step {step}/{total} 活跃 {active}", end="\r", flush=True)

    res, grid, t_grid = run_sweep(cfg, grid, theta_loft_deg=cfg.sim.theta_loft_deg, mass=mass_arr, progress=progress)
    wall = time.perf_counter() - t0
    print(f"\n  仿真耗时 {wall:.1f} s（{wall / max(1, res.dv_total.size) * 1000:.0f} ms/工况）")

    hit = res.status == ST_HIT
    print(f"  命中 {int(hit.sum())}/{hit.size}（{hit.mean() * 100:.1f}%）")
    tvals = res.t_hit[np.isfinite(res.t_hit)]
    if tvals.size:
        print(f"  命中时间范围 {tvals.min():.2f} ~ {tvals.max():.2f} s")
    for code, name in STATUS_NAMES.items():
        n = int(np.sum(res.status == code))
        if n:
            print(f"    {STATUS_LABELS[code]:<16} {n}")

    # 单调性校验：等时线成立的前提
    issues = monotonic_report(t_grid, grid)
    if issues:
        print(f"\n  ⚠ 单调性异常 {len(issues)} 处（前 5 条）：")
        for dv, bc_a, bc_b, kind, a, b in issues[:5]:
            print(f"    ΔV={dv:.0f}: BC {bc_a:.0f}->{bc_b:.0f} {kind} ({a:.3f} -> {b:.3f})")
    else:
        print("\n  单调性校验通过：每个 ΔV 列内 t_hit 随 BC 单调（等时线成立前提）")

    # 等时线
    lines = extract_isolines(t_grid, grid, step=args.iso_step)
    lv = sorted({seg["level"] for seg in lines})
    print(f"  等时线 {len(lines)} 段，时间层级 {[f'{x:g}' for x in lv]}")

    # 输出
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    tag = args.tag or time.strftime("%Y%m%d_%H%M%S")
    cases_csv = write_cases_csv(res, RESULT_DIR / f"cases_{tag}.csv")
    iso_csv = write_isolines_csv(lines, RESULT_DIR / f"isolines_{tag}.csv", cfg)
    summary = summary_dict(cfg, res, grid, t_grid, lines, extra={"wall_time_s": wall, "monotonic_issues": len(issues)})
    summary_path = write_summary(RESULT_DIR / f"summary_{tag}.json", summary)
    print(f"\n  逐工况 CSV : {cases_csv}")
    print(f"  等时线 CSV : {iso_csv}")
    print(f"  摘要 JSON  : {summary_path}")

    fig = plot_sweep(res, grid, t_grid, cfg, out=FIG_DIR / f"fig_sweep_isotime_{tag}.png", iso_step=args.iso_step)
    print(f"  主图       : {fig}")
    fig2 = plot_baseline_curve(res, cfg, out=FIG_DIR / f"fig_baseline_time_{tag}.png")
    print(f"  基准曲线   : {fig2}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="missile_sim", description="简化模型导弹弹道仿真器（2D 纵向平面）")
    ap.add_argument("--config", type=str, default=None, help="配置 JSON 路径（默认 configs/baseline.json）")
    ap.add_argument("--backend", choices=list(BACKENDS), default=None,
                    help="计算后端：flash=本仓库快模型（默认）；pro=原生仿真器（下一阶段，未接入）")
    ap.add_argument("--standard", type=str, default=None,
                    help="标准弹（11 弹池里的短名，如 PL-12 / 120C / R-77-1；默认取配置）")
    ap.add_argument("--burn", choices=list(burn_mod.BURN_MODELS), default=None,
                    help="燃烧档：finite=N 段有限燃烧（默认）；instant=瞬时燃烧（旧口径，可逐位复现升级前）")
    ap.add_argument("--ve-equiv", type=float, default=None,
                    help="强制等效排气速度 [m/s]（旧口径复现用；默认由标准弹导出）")
    ap.add_argument("--t-life", type=float, default=None, help="飞行寿命上限 [s]（默认取标准弹的 timeLife）")
    ap.add_argument("--list-standards", action="store_true", help="列出弹池里可选的标准弹后退出")
    ap.add_argument("--vm0", type=float, help="发射方速度 [m/s]")
    ap.add_argument("--vt", type=float, help="目标速度 [m/s]，负=迎头（距离闭合），正=尾追")
    ap.add_argument("--alt", type=float, help="双方高度（同高）[m]")
    ap.add_argument("--range", type=float, help="初始水平距离 [m]")
    ap.add_argument("--target-alt", type=float, help="目标高度 [m]（默认与发射方同高）")
    ap.add_argument("--loft", type=float, help="高抛角 [度]，必须 < 40")
    ap.add_argument("--loft-rule", choices=["game", "heuristic"], default=None,
                    help="高抛退出判据：game=游戏判据（|λ̇|≥omegaMax 或 λ≤targetElevation，默认）；"
                         "heuristic=本仓库旧启发式（复现升级前产物时需要）")
    ap.add_argument("--dv", type=float, help="单工况总增速 ΔV [m/s]（默认取 AIM-120C5 火箭方程值）")
    ap.add_argument("--bc", type=float, help="单工况弹道系数（默认取 CxK=1.225 对应值）")
    ap.add_argument("--dv-min", type=float, help="扫描 ΔV 下限")
    ap.add_argument("--dv-max", type=float, help="扫描 ΔV 上限")
    ap.add_argument("--dv-step", type=float, help="扫描 ΔV 步长（默认 50）")
    ap.add_argument("--bc-min", type=float, help="扫描 BC 下限")
    ap.add_argument("--bc-max", type=float, help="扫描 BC 上限")
    ap.add_argument("--bc-step", type=float, help="扫描 BC 步长（默认 100）")
    ap.add_argument("--drag-base", type=float, help="有效阻力系数标定旋钮（默认 1.0，见 README）")
    ap.add_argument("--aero", choices=["legacy", "mach", "full"], default=None,
                    help="气动模型：legacy=恒定系数（旧口径，可复现 60.82 s）；"
                         "mach=+f(M) 基础阻力；full=+升力配平与诱导阻力（配置默认）")
    ap.add_argument("--clip-lift-peak", action="store_true", default=None,
                    help="在气动层把可达法向过载截到升力峰值（会改变弹道，默认关）")
    ap.add_argument("--hit-radius", type=float, help="命中半径 [m]（默认取标准弹的 proximityFuse.radius）")
    ap.add_argument(
        "--bc-anchor",
        choices=["dry", "launch", "mass"],
        default=None,
        help="BC↔CxK 反解的质量口径：dry=干重（默认）、launch=发射质量（对应 AGENTS.md 的 BC 公式族）",
    )
    ap.add_argument("--mass", type=float, default=None, help="把整张图的弹体质量设为该值 [kg]（单工况时同时作为弹体质量）")
    ap.add_argument("--sweep", action="store_true", help="执行参数扫描并输出等命中时间线")
    ap.add_argument("--iso-step", type=float, default=2.0, help="等命中时间线步长 [s]（默认 2）")
    ap.add_argument("--stride", type=int, default=20, help="单工况弹道记录抽样间隔（默认 20 步）")
    ap.add_argument("--figure", type=str, default=None, help="单工况弹道图输出路径")
    ap.add_argument("--json", type=str, default=None, help="单工况结果 JSON 输出路径")
    ap.add_argument("--tag", type=str, default=None, help="扫描输出文件名后缀（默认时间戳）")
    args = ap.parse_args(argv)

    if args.list_standards:
        try:
            doc = standard_mod.load_pool()
        except standard_mod.StandardPoolError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        print(f"标准弹池（默认 {doc.get('default')}）：")
        for name, m in doc["missiles"].items():
            eng = m["engine"]
            print(f"  {name:<9} ΔV={m['impulse']['dv']:7.1f}  BC={m['impulse']['bc']:7.1f}  "
                  f"口径={m['geometry']['caliber_m'] * 1000:5.1f}mm  "
                  f"燃={eng['time_fire']:g}"
                  f"{'+' + format(eng['time_fire1'], 'g') if eng.get('time_fire1') else ''}s  "
                  f"引信={m['fuse']['radius_m']:g}m  寿命={m['limits']['time_life_s']:g}s  "
                  f"过载={m['limits']['req_accel_max_g']:g}g")
        return 0

    try:
        cfg = load_config(args.config)
        cfg = _apply_overrides(cfg, args)
    except ConfigError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if cfg.backend == "pro":
        print(f"错误：{PRO_BACKEND_HINT}", file=sys.stderr)
        return 2
    if not (0.0 <= cfg.sim.theta_loft_deg < 40.0):
        print(f"错误：高抛角必须在 [0, 40) 度范围内，收到 {cfg.sim.theta_loft_deg}", file=sys.stderr)
        return 2
    return _run_sweep(cfg, args) if args.sweep else _run_single(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())

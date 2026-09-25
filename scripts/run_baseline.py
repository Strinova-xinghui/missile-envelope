"""单工况入口：跑一条弹道并出图。

用法：
    python scripts/run_baseline.py                        # 基准工况（AIM-120C5 原始参数）
    python scripts/run_baseline.py --vt -450 --range 90000 --loft 30
    python scripts/run_baseline.py --loft-family          # 额外输出不同高抛角的对比图
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from missile_sim.config import (  # noqa: E402
    ballistic_coefficient,
    config_to_dict,
    cxk_for_bc,
    delta_v_equiv,
    isp_equiv,
    load_config,
    summary_lines,
)
from missile_sim.plot import plot_loft_family, plot_trajectories  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402

FIG_DIR = Path(__file__).resolve().parents[1] / "figures"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm0", type=float, default=None, help="发射方速度 [m/s]")
    ap.add_argument("--vt", type=float, default=None, help="目标速度 [m/s]，负=迎头，正=尾追")
    ap.add_argument("--alt", type=float, default=None, help="高度 [m]")
    ap.add_argument("--range", type=float, default=None, help="初始距离 [m]")
    ap.add_argument("--target-alt", type=float, default=None, help="目标高度 [m]（默认与发射方同高）")
    ap.add_argument("--loft", type=float, default=None, help="高抛角 [度]，<40")
    ap.add_argument("--dv", type=float, default=None, help="总增速 ΔV [m/s]（默认 AIM-120C5 火箭方程值）")
    ap.add_argument("--bc", type=float, default=None, help="弹道系数（默认 CxK=1.225 对应值）")
    ap.add_argument("--loft-family", action="store_true", help="同时输出不同高抛角对比图")
    ap.add_argument("--tag", type=str, default="baseline")
    args = ap.parse_args(argv)

    cfg = load_config()
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
    if not (0.0 <= cfg.sim.theta_loft_deg < 40.0):
        print(f"错误：高抛角必须在 [0, 40) 度范围内，收到 {cfg.sim.theta_loft_deg}", file=sys.stderr)
        return 2

    dv = delta_v_equiv(cfg) if args.dv is None else args.dv
    bc = ballistic_coefficient(cfg.drag.cxk, cfg) if args.bc is None else args.bc
    cxk = cxk_for_bc(bc, cfg)

    print("—— 基准参数 ——")
    for line in summary_lines(cfg):
        print("  " + line)
    print(f"  本次工况：ΔV={dv:.1f} m/s，BC={bc:.0f} -> CxK={cxk:.5f}，等效比冲={isp_equiv(dv):.1f} s")
    print(
        f"  发射 {cfg.scenario.vm0:.0f} m/s，目标 {cfg.scenario.vt:.0f} m/s"
        f"（{'迎头' if cfg.scenario.vt < 0 else ('尾追' if cfg.scenario.vt > 0 else '静止')}），"
        f"发射高度 {cfg.scenario.alt:.0f} m"
        + (f"，目标高度 {cfg.scenario.target_alt:.0f} m" if cfg.scenario.target_alt is not None else "")
        + f"，距离 {cfg.scenario.range / 1000:.1f} km，高抛 {cfg.sim.theta_loft_deg:.1f}°"
    )

    res = simulate_one(cfg, Case(dv_total=dv, cxk=cxk), record_trace=True, stride=20)
    print("\n—— 结果 ——")
    print(f"  状态            : {res.status_name} ({res.status_label})")
    print(f"  命中时间        : {res.t_hit:.3f} s" if res.hit else "  命中时间        : —（未命中）")
    print(f"  最小距离        : {res.min_range:.2f} m（离散采样）；步内最接近 {res.min_range_linear:.2f} m")
    print(f"  引信半径        : {cfg.sim.hit_radius:.0f} m")
    print(f"  高抛结束时刻    : {res.t_loft_end:.2f} s" if res.t_loft_end >= 0 else "  高抛结束时刻    : 未退出")
    print(f"  最大高度        : {res.max_alt:.0f} m（相对发射高度 {res.max_alt - cfg.scenario.alt:+.0f} m）")
    print(f"  命中点速度      : {res.v_impact:.1f} m/s")
    print(f"  终端航向误差    : {res.terminal_gamma_error_at_min_range_deg:.2f} °")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    traj_png = plot_trajectories(
        [res.trace],
        [f"ΔV={dv:.0f} m/s，BC={bc:.0f}，高抛 {cfg.sim.theta_loft_deg:.0f}°"],
        cfg,
        out=FIG_DIR / f"fig_traj_{args.tag}.png",
        title=f"单工况弹道（{res.status_label}）",
    )
    print(f"\n  弹道图        : {traj_png}")

    if args.loft_family:
        family = {}
        base_loft = cfg.sim.theta_loft_deg
        for loft in (0.0, 10.0, 22.0, 30.0, 39.0):
            c = load_config()
            c.scenario.vm0 = cfg.scenario.vm0
            c.scenario.vt = cfg.scenario.vt
            c.scenario.alt = cfg.scenario.alt
            c.scenario.range = cfg.scenario.range
            c.sim.theta_loft_deg = loft
            family[loft] = simulate_one(c, Case(dv_total=dv, cxk=cxk), record_trace=True, stride=20)
        png = plot_loft_family(family, cfg, out=FIG_DIR / f"fig_loft_family_{args.tag}.png")
        print(f"  高抛族对比图  : {png}")
        for loft, r in sorted(family.items()):
            tag = f"t_hit={r.t_hit:.2f} s，V命中={r.v_impact:.0f} m/s，Hmax={r.max_alt:.0f} m" if r.hit else f"{r.status_name}，Hmax={r.max_alt:.0f} m"
            print(f"    高抛 {loft:4.1f}° -> {tag}")
        cfg.sim.theta_loft_deg = base_loft

    print(f"\n  配置快照      : {config_to_dict(cfg)['sim']['theta_loft_deg']}°（完整配置见 configs/baseline.json）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

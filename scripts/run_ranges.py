"""多距离/多目标速度对比：无高抛 vs 有高抛，输出表格与汇总图。

用途：展示"高抛"这一设计选择在不同交战几何下的收益（存速/命中时间/最大射程）。
用法：
    python scripts/run_ranges.py                 # 默认 20/35/50/70/90 km
    python scripts/run_ranges.py --ranges 30 60 80 --vt -450
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from missile_sim.config import delta_v_equiv, load_config  # noqa: E402
from missile_sim.plot import setup_style  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402

FIG_DIR = Path(__file__).resolve().parents[1] / "figures"


def run(loft: float, range0: float, **over):
    cfg = load_config()
    cfg.sim.theta_loft_deg = loft
    for key in ("vm0", "vt", "alt", "range"):
        if key in over and over[key] is not None:
            setattr(cfg.scenario, key, over[key])
    cfg.scenario.range = range0
    return simulate_one(cfg, Case(dv_total=delta_v_equiv(cfg), cxk=cfg.drag.cxk), record_trace=False), cfg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranges", type=float, nargs="+", default=[20000.0, 35000.0, 50000.0, 70000.0, 90000.0])
    ap.add_argument("--vm0", type=float, default=None)
    ap.add_argument("--vt", type=float, default=None)
    ap.add_argument("--alt", type=float, default=None)
    ap.add_argument("--lofts", type=float, nargs="+", default=[0.0, 22.0])
    args = ap.parse_args(argv)

    setup_style()
    print(f"{'R0[km]':>8} {'高抛':>6} {'状态':>18} {'t_hit[s]':>9} {'V命中[m/s]':>10} {'Hmax[m]':>9} {'t_loft[s]':>9} {'Rmin[m]':>9}")
    rows = []
    for r0 in args.ranges:
        for loft in args.lofts:
            res, cfg = run(loft, r0, vm0=args.vm0, vt=args.vt, alt=args.alt)
            print(
                f"{r0 / 1000:8.0f} {loft:6.0f} {res.status_name:>18} "
                f"{(res.t_hit if res.hit else float('nan')):9.2f} {res.v_impact:10.1f} "
                f"{res.max_alt:9.0f} {res.t_loft_end:9.2f} {res.min_range:9.2f}"
            )
            rows.append((r0, loft, res, cfg))

        print()
    # 汇总图：命中时间与命中点存速随距离的变化
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))
    for loft in args.lofts:
        sel = [r for r in rows if r[1] == loft]
        xs = [r[0] / 1000.0 for r in sel]
        th = [r[2].t_hit if r[2].hit else np.nan for r in sel]
        vv = [r[2].v_impact if r[2].hit else np.nan for r in sel]
        ax1.plot(xs, th, "o-", label=f"高抛 {loft:.0f}°")
        ax2.plot(xs, vv, "s-", label=f"高抛 {loft:.0f}°")
    ax1.set_xlabel("初始距离 R0 [km]")
    ax1.set_ylabel("命中时间 [s]")
    ax1.set_title("命中时间 vs 初始距离（未命中为空缺）")
    ax2.set_xlabel("初始距离 R0 [km]")
    ax2.set_ylabel("命中点速度 [m/s]")
    ax2.set_title("命中点存速 vs 初始距离")
    for ax in (ax1, ax2):
        ax.legend(fontsize=9)
        ax.grid(alpha=0.25)
    ref = rows[0][3]
    fig.suptitle(
        f"发射 {ref.scenario.vm0:.0f} m/s，目标 {ref.scenario.vt:.0f} m/s，高度 {ref.scenario.alt / 1000:.0f} km"
        f"（ΔV={delta_v_equiv(ref):.0f} m/s，BC=3624）",
        fontsize=10.5,
    )
    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / "fig_range_sweep.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"汇总图：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

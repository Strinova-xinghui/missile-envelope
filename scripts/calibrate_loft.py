"""高抛段设计参数扫描：退出下沉角阈值 / 高度增量上限 / 时间上限 × 3 km 高度增量。

目标：找到一组默认参数，使 ΔV×BC 网格上命中率合理（终端脱靶量远小于引信半径 12 m）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from missile_sim.config import cxk_for_bc, delta_v_equiv, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_batch, simulate_one  # noqa: E402

DVS = np.arange(800.0, 1501.0, 50.0)


def grid_stats(cfg, bcs=None):
    bcs = np.arange(1700.0, 4001.0, 100.0) if bcs is None else np.asarray(bcs)
    D, B = np.meshgrid(DVS, bcs, indexing="ij")
    C = cxk_for_bc(B, cfg)
    res = simulate_batch(cfg, D.ravel(), C.ravel())
    hit = res.status == 1
    finite = np.isfinite(res.t_hit)
    return {
        "n": res.status.size,
        "hit": int(hit.sum()),
        "rate": float(hit.mean()),
        "tmin": float(res.t_hit[finite].min()) if finite.any() else float("nan"),
        "tmax": float(res.t_hit[finite].max()) if finite.any() else float("nan"),
        "miss_med": float(np.median(res.min_range[~hit])) if (~hit).any() else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whole", action="store_true", help="同时扫描 3 km 高度增量的场景")
    args = ap.parse_args()

    base = load_config()
    dv0 = delta_v_equiv(base)
    print(f"基准 ΔV={dv0:.1f} m/s, 引信半径={base.sim.hit_radius:.0f} m, loft={base.sim.theta_loft_deg:.0f}°")
    print("基准单工况：")
    r = simulate_one(base, Case(dv_total=dv0, cxk=base.drag.cxk), record_trace=False)
    print(f"  {r.status_name} t={r.t_hit:.2f} Rmin={r.min_range:.2f} t_loft={r.t_loft_end:.2f} Hmax={r.max_alt:.0f}")
    print("  网格:", grid_stats(base))

    print("\n[A] 退出下沉角阈值扫描（dh 上限设很大，让阈值 A 主导）")
    for margin in (5.0, 8.0, 10.0, 12.0, 15.0, 18.0, 22.0):
        cfg = load_config()
        cfg.sim.loft_exit_margin_deg = margin
        cfg.sim.loft_dh_gain_max = 1e9
        cfg.sim.loft_time_max = 60.0
        r = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk), record_trace=False)
        st = grid_stats(cfg)
        print(f"  margin={margin:5.1f}°: 基准 {r.status_name:15s} Rmin={r.min_range:7.2f} V={r.v_impact:6.1f} "
              f"t_loft={r.t_loft_end:6.2f} Hmax={r.max_alt:7.0f} | 网格命中 {st['hit']:3d}/{st['n']} ({st['rate'] * 100:.0f}%) "
              f"t {st['tmin']:.0f}~{st['tmax']:.0f}s 未命中中位 R={st['miss_med']:.0f}m")

    print("\n[B] 时间上限扫描（dh 上限很大、阈值 A 关闭）")
    for tmax in (4.0, 6.0, 8.0, 10.0, 12.0, 15.0):
        cfg = load_config()
        cfg.sim.loft_exit_margin_deg = 89.0
        cfg.sim.loft_dh_gain_max = 1e9
        cfg.sim.loft_time_max = tmax
        r = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk), record_trace=False)
        st = grid_stats(cfg)
        print(f"  tmax={tmax:5.1f}s: 基准 {r.status_name:15s} Rmin={r.min_range:7.2f} V={r.v_impact:6.1f} "
              f"t_loft={r.t_loft_end:6.2f} Hmax={r.max_alt:7.0f} | 网格命中 {st['hit']:3d}/{st['n']} ({st['rate'] * 100:.0f}%) "
              f"t {st['tmin']:.0f}~{st['tmax']:.0f}s")

    print("\n[C] 高度增量上限扫描（阈值 A 关闭、时间上限很大）")
    for dh in (500.0, 1000.0, 2000.0, 3000.0, 4000.0, 6000.0):
        cfg = load_config()
        cfg.sim.loft_exit_margin_deg = 89.0
        cfg.sim.loft_dh_gain_max = dh
        cfg.sim.loft_time_max = 60.0
        r = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk), record_trace=False)
        st = grid_stats(cfg)
        print(f"  dh={dh:6.0f}m: 基准 {r.status_name:15s} Rmin={r.min_range:7.2f} V={r.v_impact:6.1f} "
              f"t_loft={r.t_loft_end:6.2f} Hmax={r.max_alt:7.0f} | 网格命中 {st['hit']:3d}/{st['n']} ({st['rate'] * 100:.0f}%) "
              f"t {st['tmin']:.0f}~{st['tmax']:.0f}s")

    if args.whole:
        print("\n[D] 目标高度差扫描（vm0=300, vt=-300, 发射 10 km, R0=50 km, 高抛 22°）")
        for dh in (-4000.0, 0.0, 3000.0, 6000.0):
            cfg = load_config()
            cfg.scenario.target_alt = cfg.scenario.alt + dh
            r = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk), record_trace=False)
            tag = (
                f"命中 t={r.t_hit:7.2f}s V={r.v_impact:6.1f} Hmax={r.max_alt:7.0f} t_loft={r.t_loft_end:6.2f}"
                if r.hit
                else f"{r.status_name:16s} Rmin={r.min_range:9.2f} Hmax={r.max_alt:7.0f}"
            )
            print(f"  目标高度差 {dh:+7.0f} m -> {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

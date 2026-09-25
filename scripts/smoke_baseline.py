"""单工况冒烟测试：打印参数对照表与默认工况结果（含少量诊断量）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from missile_sim.config import (  # noqa: E402
    a_drag_coeff,
    ballistic_coefficient,
    cxk_for_bc,
    delta_v_equiv,
    isp_equiv,
    load_config,
    s_ref,
    summary_lines,
)
from missile_sim.sim import Case, simulate_one  # noqa: E402


def main() -> int:
    cfg = load_config()
    for line in summary_lines(cfg):
        print(line)
    bc0 = ballistic_coefficient(cfg.drag.cxk, cfg)
    dv0 = delta_v_equiv(cfg)
    print(f"基准锚点：ΔV={dv0:.1f} m/s, BC={bc0:.1f}, CxK={cfg.drag.cxk:.4f}, Isp_eq={isp_equiv(dv0):.1f} s")

    scen = cfg.scenario
    print(
        f"\n工况：vm0={scen.vm0:.0f} m/s, vt={scen.vt:.0f} m/s (负=迎头), alt={scen.alt:.0f} m, "
        f"R0={scen.range / 1000:.1f} km, loft={cfg.sim.theta_loft_deg:.1f} deg"
    )
    case = Case(dv_total=dv0, cxk=cfg.drag.cxk)
    t0 = time.perf_counter()
    res = simulate_one(cfg, case)
    dt_wall = time.perf_counter() - t0
    print(f"状态        = {res.status_name} ({res.status_label})")
    print(f"命中时间    = {res.t_hit:.3f} s" if res.hit else f"命中时间    = 未命中 (min_range={res.min_range:.2f} m)")
    print(f"飞行结束    = {res.t_end:.3f} s")
    print(f"最小距离    = {res.min_range:.3f} m")
    print(f"最大高度    = {res.max_alt:.1f} m (爬升 {res.max_alt - scen.alt:.1f} m)")
    print(f"命中点速度  = {res.v_impact:.1f} m/s")
    print(f"高抛结束时刻= {res.t_loft_end:.3f} s")
    print(f"最小距离处导引比 N_eff = {res.n_eff_at_min_range:.3f}")
    print(f"终端航向误差= {res.terminal_gamma_error_at_min_range_deg:.3f} deg")
    print(f"单工况耗时  = {dt_wall * 1000:.1f} ms")
    if res.trace is not None:
        tr = res.trace
        print(f"记录点数    = {len(tr.t)} (stride 抽样)")
        print(f"高度范围    = {tr.h.min():.1f} ~ {tr.h.max():.1f} m")
        print(f"速度范围    = {tr.v.min():.1f} ~ {tr.v.max():.1f} m/s")
        print(f"gamma范围   = {np.degrees(tr.gamma.min()):.2f} ~ {np.degrees(tr.gamma.max()):.2f} deg")
    print(f"阻力系数    = {a_drag_coeff(cfg):.6e} 1/m, S_ref={s_ref(cfg):.6f} m^2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

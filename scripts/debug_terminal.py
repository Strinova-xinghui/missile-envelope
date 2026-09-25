"""终端导引诊断：打印最后若干秒的视线几何与指令，检查脱靶成因。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from missile_sim.config import delta_v_equiv, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402


def main(n_last: int = 60) -> int:
    cfg = load_config()
    dv = delta_v_equiv(cfg)
    res = simulate_one(cfg, Case(dv_total=dv, cxk=cfg.drag.cxk), record_trace=True, stride=1)
    tr = res.trace
    print(f"status={res.status_name} t_hit={res.t_hit:.4f} minR={res.min_range:.3f} t_loft_end={res.t_loft_end:.3f}")
    # 目标位置（网格推算，与仿真一致）
    vt = cfg.scenario.vt
    r0 = cfg.scenario.range
    header = ("t", "x", "h", "V", "gamma", "los", "R", "vc", "N", "a_perp", "tgo", "ph", "lam_dot", "a_pn_calc")
    print("{:>7} {:>9} {:>9} {:>7} {:>8} {:>8} {:>9} {:>8} {:>5} {:>8} {:>7} {:>3} {:>10} {:>10}".format(*header))
    stop = len(tr.t)
    for i in range(max(0, stop - n_last), stop):
        a_calc = tr.n_eff[i] * tr.vc[i] * tr.lam_dot[i]
        print(
            "{:7.3f} {:9.1f} {:9.1f} {:7.1f} {:8.3f} {:8.3f} {:9.3f} {:8.2f} {:5.2f} {:8.2f} {:7.3f} {:3d} "
            "{:10.3e} {:10.2f}".format(
                tr.t[i], tr.x[i], tr.h[i], tr.v[i], math.degrees(tr.gamma[i]), math.degrees(tr.los[i]),
                tr.rng[i], tr.vc[i], tr.n_eff[i], tr.a_perp[i], tr.tgo[i], int(tr.phase[i]),
                tr.lam_dot[i], a_calc,
            )
        )
    i_min = int(np.argmin(tr.rng))
    print(f"\n最小距离 {tr.rng[i_min]:.3f} m 出现在 t={tr.t[i_min]:.3f} s（记录点 {i_min}/{len(tr.t)}）")
    tx = r0 + vt * tr.t[i_min]
    th = cfg.scenario.alt
    print(f"  该时刻 导弹({tr.x[i_min]:.1f}, {tr.h[i_min]:.1f}) 目标({tx:.1f}, {th:.1f}) "
          f"dx={tx - tr.x[i_min]:.1f} dh={th - tr.h[i_min]:.1f} "
          f"视线角={math.degrees(math.atan2(th - tr.h[i_min], tx - tr.x[i_min])):.3f}° "
          f"航向角={math.degrees(tr.gamma[i_min]):.3f}°")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

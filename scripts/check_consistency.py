"""校验标量路径与数组批量路径在各 dt 下是否给出一致的命中判定。

若某些工况在命中/脱靶边界上对 dt 敏感（末段擦碰），说明该工况本身处于判定边界，
需要在 README 中说明；若系统性不一致，则是实现缺陷。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from missile_sim.config import cxk_for_bc, delta_v_equiv, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_batch, simulate_one  # noqa: E402


def main() -> int:
    base = load_config()
    dv0 = delta_v_equiv(base)
    print(f"基准 ΔV={dv0:.1f} m/s")
    bcs = [1700.0, 2500.0, 3000.0, 3624.0, 4000.0]
    dvs = [850.0, 1000.0, 1114.0, 1300.0, 1500.0]
    for dt in (0.005, 0.0025, 0.001):
        cfg = load_config()
        cfg.sim.dt = dt
        same = 0
        total = 0
        diffs = []
        for dvv in dvs:
            for bc in bcs:
                cx = float(cxk_for_bc(bc, cfg))
                a = simulate_one(cfg, Case(dv_total=dvv, cxk=cx), record_trace=False)
                b = simulate_batch(cfg, np.array([dvv]), np.array([cx]))
                total += 1
                ok = a.status == b.status[0]
                same += int(ok)
                if not ok:
                    diffs.append((dvv, bc, a.status_name, a.min_range, b.status_name(0), float(b.min_range[0])))
        print(f"\n--- dt={dt}: 一致 {same}/{total} ---")
        for d in diffs:
            print(f"  ΔV={d[0]:6.0f} BC={d[1]:6.0f} | scalar {d[2]:15s} R={d[3]:9.3f} | batch {d[4]:15s} R={d[5]:9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

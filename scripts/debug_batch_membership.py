"""对比：同一工况在"批量单独跑"与"整网格批量跑"下的结果是否一致（排查批处理自身缺陷）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from missile_sim.config import cxk_for_bc, load_config  # noqa: E402
from missile_sim.decide import STATUS_NAMES  # noqa: E402
from missile_sim.sim import Case, simulate_batch, simulate_one  # noqa: E402


def show(tag, res, k, cfg):
    print(
        f"  {tag:22s} {STATUS_NAMES[int(res.status[k])]:16s} t_hit={float(res.t_hit[k]):9.4f} "
        f"Rmin={float(res.min_range[k]):9.4f} t_end={float(res.t_end[k]):8.3f} V={float(res.v_impact[k]):7.1f} "
        f"t_loft={float(res.t_loft_end[k]):7.3f} Hmax={float(res.max_alt[k]):8.1f}"
    )


def main() -> int:
    cfg = load_config()
    cases = [(1114.0, 3624.0), (800.0, 1700.0), (1500.0, 4000.0)]
    for dv0, bc0 in cases:
        cx = float(cxk_for_bc(bc0, cfg))
        print(f"\n=== ΔV={dv0} BC={bc0} CxK={cx:.4f} ===")
        single = simulate_batch(cfg, np.array([dv0]), np.array([cx]))
        show("batch 单独跑", single, 0, cfg)
        r1 = simulate_one(cfg, Case(dv_total=dv0, cxk=cx), record_trace=False)
        print(
            f"  {'标量单工况':22s} {r1.status_name:16s} t_hit={r1.t_hit:9.4f} "
            f"Rmin={r1.min_range:9.4f} t_end={r1.t_end:8.3f} V={r1.v_impact:7.1f} "
            f"t_loft={r1.t_loft_end:7.3f} Hmax={r1.max_alt:8.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

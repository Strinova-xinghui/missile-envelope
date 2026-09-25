"""标定/敏感性分析：只在控制台输出，不改动配置文件。

用法：
    python scripts/calibrate.py              # 总览
    python scripts/calibrate.py --scenario   # 多距离交叉检查

说明：这是"简化模型自洽性"扫描，不是对真实武器的验证。默认参数与理由记录在 README。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from missile_sim.config import delta_v_equiv, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402


_SCEN_KEYS = {"vm0", "vt", "alt", "range"}


def one(drag_base=None, range0=None, **over):
    """按参数名自动分派到 cfg.scenario / cfg.sim。"""
    cfg = load_config()
    if drag_base is not None:
        cfg.drag.drag_base = drag_base
    if range0 is not None:
        cfg.scenario.range = range0
    for k, v in over.items():
        if k in _SCEN_KEYS:
            setattr(cfg.scenario, k, v)
        else:
            setattr(cfg.sim, k, v)
    dv = delta_v_equiv(cfg)
    return simulate_one(cfg, Case(dv_total=dv, cxk=cfg.drag.cxk)), cfg


def brief(res) -> str:
    if res.hit:
        return f"命中 t={res.t_hit:7.2f}s V={res.v_impact:6.1f} Hmax={res.max_alt:8.0f} t_loft={res.t_loft_end:6.2f}"
    return f"{res.status_name:16s} minR={res.min_range:9.2f} V={res.v_impact:6.1f} Hmax={res.max_alt:8.0f} t_loft={res.t_loft_end:6.2f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="store_true")
    args = ap.parse_args()

    cfg0 = load_config()
    dv = delta_v_equiv(cfg0)
    print(
        f"基准 ΔV={dv:.1f} m/s, CxK={cfg0.drag.cxk:.4f}, loft={cfg0.sim.theta_loft_deg:.0f} deg, "
        f"hit_radius={cfg0.sim.hit_radius:.0f} m"
    )
    print(
        f"工况：vm0={cfg0.scenario.vm0:.0f}, vt={cfg0.scenario.vt:.0f}, alt={cfg0.scenario.alt:.0f}, "
        f"R0={cfg0.scenario.range / 1000:.0f} km"
    )

    print("\n[1] 默认配置（含高抛）")
    res, _ = one()
    print(f"  {brief(res)}")

    print("\n[2] 高抛退出参数：高度增量上限 × 最长高抛时间（默认下沉角闸门 60° 不触发）")
    for dh in (2000.0, 4000.0, 6000.0):
        for tmax in (10.0, 20.0, 30.0):
            res, _ = one(loft_dh_gain_max=dh, loft_time_max=tmax)
            print(f"  dh={dh:6.0f} tmax={tmax:5.1f} -> {brief(res)}")

    print("\n[3] 高抛角影响（默认其它参数）")
    for loft in (0.0, 10.0, 22.0, 30.0, 39.0):
        res, _ = one(theta_loft_deg=loft)
        print(f"  loft={loft:5.1f} deg -> {brief(res)}")

    print("\n[4] drag_base 影响（校正阻力标定旋钮）")
    for db in (0.25, 0.5, 0.75, 1.0, 1.25):
        res, _ = one(drag_base=db)
        print(f"  drag_base={db:5.2f} -> {brief(res)}")

    if args.scenario:
        print("\n[5] 初始距离交叉检查（无高抛 vs 有高抛）")
        for r0 in (20000.0, 35000.0, 50000.0, 70000.0, 90000.0):
            a, _ = one(range0=r0, theta_loft_deg=0.0)
            b, _ = one(range0=r0)
            print(f"  R0={r0 / 1000:5.0f} km 无高抛: {brief(a)}")
            print(f"  R0={r0 / 1000:5.0f} km  有高抛: {brief(b)}")

        print("\n[6] 目标速度符号检查（负=迎头 / 正=尾追，R0=40 km）")
        for vt in (-450.0, -300.0, -150.0, 0.0, 150.0, 300.0):
            res, _ = one(vt=vt, range0=40000.0)
            print(f"  vt={vt:6.0f} m/s -> {brief(res)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

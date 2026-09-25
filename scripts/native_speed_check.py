# -*- coding: utf-8 -*-
"""A2 验证：有限燃烧下 Flash 的速度历程与 Pro（原生仿真器）对拍。

同一场景（默认 50 km 迎头、10 km、300/−300 m/s）分别跑：
  * Pro   —— 直接执行游戏原生代码（`WT_NATIVE_PKG` 指路，包体不入库）
  * Flash —— 本仓库（标准弹 + 有限燃烧）
然后并排打印速度/质量/推力时间历程。升级前瞬时燃烧在 t=0.5 s 就领先 Pro +801 m/s，
本脚本就是用来确认这个偏差消失的。

    $env:WT_NATIVE_PKG = "<解压后的 wt-missile-backend>"
    python scripts\\native_speed_check.py
    python scripts\\native_speed_check.py --standard PL-12 --missile cn_pl12 --range 50000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RES_DIR = ROOT / "results"
# Flash 侧标准弹短名 → Pro 侧 profile 名
NATIVE_NAME = {
    "120A": "us_aim_120a", "120C": "us_aim_120c_5", "120D": "us_aim_120d",
    "MICA": "fr_mica_em", "AAM-4": "jp_aam4", "PL-12": "cn_pl12", "PL-12A": "cn_pl12a",
    "R-77": "su_r_77", "R-77-1": "su_r_77_1", "Derby": "il_derby", "R-Darter": "r_darter",
}


def native_worker(payload):
    """子进程：跑一次 Pro，回传 samples 里的速度/时间序列。"""
    pkg, missile, rng, alt, vm0, vt, dt, sample, version = payload
    pkg = Path(pkg)
    sys.path.insert(0, str(pkg))
    sys.path.insert(0, str(pkg / "tools"))
    import simulator.core as core                      # noqa: PLC0415
    import simulator.resources as resources            # noqa: PLC0415

    raw = {
        "schema_version": 1, "label": f"speed-check {missile}", "missile": missile,
        "version": version, "duration_s": 150.0, "dt_s": dt, "sample_period_s": sample,
        "observation": {"mode": "ideal"},
        "launch": {"position_m": [0.0, alt, 0.0], "velocity_m_s": [vm0, 0.0, 0.0]},
        "target": {"position_m": [rng, alt, 0.0], "velocity_m_s": [vt, 0.0, 0.0],
                   "collision_radius_m": 3.0},
    }
    _s, summary, samples = core.simulate(raw)
    return {
        "missile": missile, "resource": summary["identity"].get("resource"),
        "t_hit": summary["time_s"], "terminal_event": summary["terminal_event"],
        "v_impact": summary["final_speed_m_s"], "dt_s": dt,
        "series": [{"t": sm["time_s"], "v": sm["speed_m_s"], "h": sm["missile_y_m"],
                    "mass": sm["mass_kg"], "thrust": sm["thrust_N"]} for sm in samples],
    }


def flash_run(standard: str, rng: float, alt: float, vm0: float, vt: float, burn: str):
    from missile_sim.config import apply_standard, delta_v_equiv, load_config
    from missile_sim.sim import Case, simulate_one

    cfg = load_config()
    cfg.standard.name = standard
    cfg.standard.burn = burn
    apply_standard(cfg)
    cfg.scenario.range = rng
    cfg.scenario.alt = alt
    cfg.scenario.vm0 = vm0
    cfg.scenario.vt = vt
    r = simulate_one(cfg, Case(dv_total=delta_v_equiv(cfg), cxk=cfg.drag.cxk),
                     record_trace=True, stride=1)
    tr = r.trace
    return {
        "standard": standard, "burn": burn, "dv": delta_v_equiv(cfg),
        "t_hit": r.t_hit, "v_impact": r.v_impact, "status": r.status_name,
        "series": [{"t": float(tr.t[i]), "v": float(tr.v[i]), "h": float(tr.h[i]),
                    "mass": float(tr.mass_kg[i]), "thrust": float(tr.thrust_N[i])}
                   for i in range(len(tr.t))],
    }


def _at(series, t):
    """取最接近 t 的一条。"""
    return min(series, key=lambda s: abs(s["t"] - t))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="有限燃烧 Flash vs Pro 速度历程对拍")
    ap.add_argument("--standard", default="PL-12", help="Flash 侧标准弹短名")
    ap.add_argument("--missile", default=None, help="Pro 侧 profile 名（默认由标准弹映射）")
    ap.add_argument("--range", type=float, default=50000.0)
    ap.add_argument("--alt", type=float, default=10000.0)
    ap.add_argument("--vm0", type=float, default=300.0)
    ap.add_argument("--vt", type=float, default=-300.0)
    ap.add_argument("--dt", type=float, default=0.01, help="Pro 侧步长（上限 0.01）")
    ap.add_argument("--sample", type=float, default=0.02)
    ap.add_argument("--version", default="2.59.0.28")
    ap.add_argument("--times", nargs="+", type=float,
                    default=[0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 20.0])
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    missile = args.missile or NATIVE_NAME.get(args.standard)
    pkg = os.environ.get("WT_NATIVE_PKG", "").strip()
    if not pkg or not (Path(pkg) / "tools" / "simulator" / "core.py").exists():
        print("需要 WT_NATIVE_PKG 指向解压后的 wt-missile-backend（包体不入库）", file=sys.stderr)
        return 2
    if missile is None:
        print(f"未知标准弹 {args.standard}；用 --missile 显式指定 Pro 侧 profile", file=sys.stderr)
        return 2

    flash = flash_run(args.standard, args.range, args.alt, args.vm0, args.vt, "finite")
    print(f"Flash（标准弹 {args.standard}，有限燃烧，ΔV={flash['dv']:.1f}）跑完："
          f"{flash['status']} t_hit={flash['t_hit']:.3f} s")

    nat = native_worker((pkg, missile, args.range, args.alt, args.vm0, args.vt,
                         args.dt, args.sample, args.version))
    print(f"Pro（{missile} @ {args.version}）跑完：{nat['terminal_event']} "
          f"t_hit={nat['t_hit']:.3f} s，采样 {len(nat['series'])} 点\n")

    rows = []
    print(f"{'t[s]':>6} | {'Pro v':>8}{'Flash v':>9}{'Δv':>8} | "
          f"{'Pro m':>8}{'Flash m':>9} | {'Pro F':>8}{'Flash F':>9} | {'Pro h':>8}{'Flash h':>9}")
    for t in args.times:
        n, f = _at(nat["series"], t), _at(flash["series"], t)
        rows.append({"t": t, "v_pro": n["v"], "v_flash": f["v"], "dv": f["v"] - n["v"],
                     "m_pro": n["mass"], "m_flash": f["mass"],
                     "F_pro": n["thrust"], "F_flash": f["thrust"],
                     "h_pro": n["h"], "h_flash": f["h"]})
        print(f"{t:6.1f} | {n['v']:8.1f}{f['v']:9.1f}{f['v'] - n['v']:+8.1f} | "
              f"{n['mass']:8.1f}{f['mass']:9.1f} | {n['thrust']:8.0f}{f['thrust']:9.0f} | "
              f"{n['h']:8.0f}{f['h']:9.0f}")

    burn_rows = [r for r in rows if r["t"] <= 8.0]
    worst = max(abs(r["dv"]) for r in burn_rows) if burn_rows else float("nan")
    print(f"\n燃烧段（t ≤ 8 s）|Δv| 最大 = {worst:.1f} m/s"
          f"（改造前瞬时燃烧在 t=0.5 s 就领先 +801 m/s）")
    print(f"全程命中时间：Pro {nat['t_hit']:.3f} s vs Flash {flash['t_hit']:.3f} s "
          f"（Δ {flash['t_hit'] - nat['t_hit']:+.3f} s）")

    tag = args.tag or f"native_speed_check_{args.standard}"
    RES_DIR.mkdir(parents=True, exist_ok=True)
    out = RES_DIR / f"{tag}.json"
    out.write_text(json.dumps({"scenario": {"range_m": args.range, "alt_m": args.alt,
                                            "vm0": args.vm0, "vt": args.vt,
                                            "pro_dt_s": args.dt, "version": args.version},
                               "flash": {k: v for k, v in flash.items() if k != "series"},
                               "native": {k: v for k, v in nat.items() if k != "series"},
                               "rows": rows, "burn_phase_max_dv": worst},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"JSON：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

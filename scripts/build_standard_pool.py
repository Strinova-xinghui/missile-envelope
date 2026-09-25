# -*- coding: utf-8 -*-
"""构建"11 弹池"：`results/missile_standards.json`。

池里每一型都是**标准弹的完整参数快照**——几何、气动、质量/推力剖面、限幅、高抛、
引信、制导增益。仿真器只读这个池，不直接碰 `E:\\WT`（保证仓库自包含、图可复现）。

    python scripts\\build_standard_pool.py            # 默认 WORK（= 实机 2.59.0.11）
    python scripts\\build_standard_pool.py --tag 2.58.0.35

引擎量与 ΔV/BC 复用 `missile_metrics.metrics()`（权威口径，勿在此另写公式）；
本脚本只负责把**其余**参数按固定路径取出来（键名在子块里会重复，必须按路径取，
例如 `proximityFuse.radius` 不能靠递归搜 `radius`）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import missile_metrics as mm                            # noqa: E402

OUT = ROOT / "results" / "missile_standards.json"
DEFAULT_STANDARD = "PL-12"

# guidance.guidanceAutopilot 里的键
AUTOPILOT = {
    "loft_enabled": "loftEnabled",
    "loft_elevation_deg": "loftElevation",
    "loft_target_elevation_deg": "loftTargetElevation",
    "loft_target_omega_max_dps": "loftTargetOmegaMax",
    "loft_angle_to_accel_mult": "loftAngleToAccelMult",
    "prop_nav_mult": "propNavMult",
    "req_accel_max_g": "reqAccelMax",
}
# rocket 顶层键
TOP = {
    "length_m": "length",
    "wing_area_mult": "wingAreaMult",
    "cxk": "CxK",
    "load_factor_max_g": "loadFactorMax",
    "fins_aoa_hor": "finsAoaHor",
    "fins_aoa_ver": "finsAoaVer",
    "fins_lat_accel_g": "finsLatAccel",
    "max_distance_m": "maxDistance",
    "time_life_s": "timeLife",
    "mach_max": "machMax",
}


def num(section, key, default=None, cast=float):
    """按路径取值；缺失返回 default。"""
    if not isinstance(section, dict):
        return default
    v = section.get(key, None)
    if v is None:
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def pair(ap: dict, key: str):
    """`timeToHitToGain0 = [10.0, 1.0]` -> (10.0, 1.0)"""
    v = ap.get(key)
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return (float(v[0]), float(v[1]))
        except (TypeError, ValueError):
            return None
    return None


def build_one(short: str, fname: str, label: str, tag: str) -> dict:
    rk = mm.load_rocket(tag, fname)
    if not rk:
        raise SystemExit(f"{short}: 读不到 {fname}（tag={tag}）")
    mt = mm.metrics(rk)
    if not mt:
        raise SystemExit(f"{short}: metrics() 字段不全")

    ap = (rk.get("guidance") or {}).get("guidanceAutopilot") or {}
    pf = rk.get("proximityFuse") or {}
    fallbacks = []

    # 升力/诱导阻力：全库无 CyK、CxAoA 键
    cyk = num(rk, "CyK")
    if cyk is None:
        cyk = 2.2
        fallbacks.append("cyk")
    cx_aoa = num(rk, "CxAoA")
    if cx_aoa is None:
        cx_aoa = 9.0
        fallbacks.append("cx_aoa")
    cy_peak = num(rk, "CyMaxAoA")
    if cy_peak is None:
        cy_peak = 1.0
        fallbacks.append("cy_max_aoa")
    req_g = num(ap, AUTOPILOT["req_accel_max_g"])
    if req_g is None:
        req_g = 35.0
        fallbacks.append("req_accel_max_g")

    # 增益表：优先命中前解锁表 timeToHitToGain{0,1,2}，否则退回发射后 ramp timeToGain{0,1}
    impact = [pair(ap, f"timeToHitToGain{i}") for i in range(3)]
    launch = [pair(ap, f"timeToGain{i}") for i in range(2)]
    impact = [p for p in impact if p]
    launch = [p for p in launch if p]
    if impact:
        used, src = impact, "timeToHitToGain"
    elif launch:
        used, src = launch, "timeToGain"
    else:
        used, src = [(10.0, 1.0), (25.0, 0.8), (50.0, 0.5)], "default"
        fallbacks.append("gain_schedule")

    return {
        "name": short,
        "label": label,
        "file": fname,
        "tag": tag,
        "geometry": {
            "caliber_m": mt["caliber_m"],
            "length_m": num(rk, TOP["length_m"]),
            "wing_area_mult": num(rk, TOP["wing_area_mult"]),
        },
        "aero": {
            "cxk": mt["CxK"],
            "cyk": cyk, "cy_max_aoa": cy_peak, "cx_aoa": cx_aoa,
        },
        "mass": {
            "launch": mt["mass"],
            "mid": mt["massEnd"] if mt["two_stage"] else mt["dry"],
            "dry": mt["dry"],
            "two_stage": bool(mt["two_stage"]),
        },
        "engine": {
            "force": mt["force"], "time_fire": mt["timeFire"],
            "force1": mt["force1"] if mt["two_stage"] else None,
            "time_fire1": mt["timeFire1"] if mt["two_stage"] else None,
        },
        "impulse": {
            "dv": mt["dv"], "bc": mt["bc"], "isp1": mt["isp1"], "isp2": mt["isp2"],
            "ve_equiv": mt["dv"] / __import__("math").log(mt["mass"] / mt["dry"]),
        },
        "limits": {
            "req_accel_max_g": req_g,
            "load_factor_max_g": num(rk, TOP["load_factor_max_g"]),
            "fins_lat_accel_g": num(rk, TOP["fins_lat_accel_g"]),
            "fins_aoa_hor": num(rk, TOP["fins_aoa_hor"]),
            "fins_aoa_ver": num(rk, TOP["fins_aoa_ver"]),
            "prop_nav_mult": num(ap, AUTOPILOT["prop_nav_mult"]),
            "max_distance_m": num(rk, TOP["max_distance_m"]),
            "time_life_s": num(rk, TOP["time_life_s"]),
            "mach_max": num(rk, TOP["mach_max"]),
        },
        "loft": {
            "enabled": bool(ap.get("loftEnabled", False)),
            "elevation_deg": num(ap, AUTOPILOT["loft_elevation_deg"]),
            "target_elevation_deg": num(ap, AUTOPILOT["loft_target_elevation_deg"]),
            "target_omega_max_dps": num(ap, AUTOPILOT["loft_target_omega_max_dps"]),
            "angle_to_accel_mult": num(ap, AUTOPILOT["loft_angle_to_accel_mult"]),
        },
        "fuse": {
            "has_proximity_fuse": bool(rk.get("hasProximityFuse", False)),
            "radius_m": num(pf, "radius"),
            "time_out_s": num(pf, "timeOut"),
        },
        "gains": {
            "impact_schedule": [[t, g] for t, g in used],
            "impact_source": src,
            "launch_schedule": [[t, g] for t, g in launch],
        },
        "fallbacks": fallbacks,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="构建 11 弹池 results/missile_standards.json")
    ap.add_argument("--tag", default=mm.WORK, help="数据源版本（默认 WORK 工作区）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    missiles = {}
    print(f"{'弹':<8}{'口径':>7}{'m0':>7}{'中段':>7}{'干重':>7}{'两段':>5}"
          f"{'燃1':>6}{'燃2':>6}{'CxK':>7}{'ΔV':>8}{'BC':>8}{'reqG':>6}"
          f"{'引信':>6}{'寿命':>6}{'高抛':>10}  回退")
    for short, fname, label in mm.MISSILE_FILES:
        p = build_one(short, fname, label, args.tag)
        missiles[short] = p
        print(f"{short:<8}{p['geometry']['caliber_m']:7.3f}{p['mass']['launch']:7.0f}"
              f"{p['mass']['mid']:7.1f}{p['mass']['dry']:7.1f}"
              f"{'是' if p['mass']['two_stage'] else '否':>5}"
              f"{p['engine']['time_fire']:6.1f}{(p['engine']['time_fire1'] or 0):6.1f}"
              f"{p['aero']['cxk']:7.3f}{p['impulse']['dv']:8.1f}{p['impulse']['bc']:8.1f}"
              f"{p['limits']['req_accel_max_g']:6.0f}{p['fuse']['radius_m']:6.1f}"
              f"{p['limits']['time_life_s']:6.0f}"
              f"{str(p['loft']['elevation_deg']) + '/' + str(p['loft']['target_elevation_deg']):>10}"
              f"  {'、'.join(p['fallbacks']) or '—'}")

    doc = {
        "schema": 1,
        "tag": args.tag,
        "source": f"War-Thunder-Datamine rocketguns（tag={args.tag}）；"
                  f"ΔV/BC 与引擎量来自 missile_metrics.metrics()（权威口径）",
        "default": DEFAULT_STANDARD,
        "missiles": missiles,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n默认标准弹：{DEFAULT_STANDARD}；共 {len(missiles)} 型")
    print(f"池：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

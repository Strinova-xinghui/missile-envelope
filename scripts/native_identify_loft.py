# -*- coding: utf-8 -*-
"""从 Pro（原生仿真器）的采样里**辨识高抛退出判据**，用于重构本仓库快模型的高抛逻辑。

背景：本模型的高抛用启发式（下沉角/高度增量/时长），近距下比游戏多爬约 2 s，
是 Flash 与 Pro 在 ≤25 km 误差的主因（见 AERO_PLAN §11.3）。
本脚本用原生的完整状态（四元数、角速度、速度、目标位置）反推游戏真实的退出条件。

用法：
    $env:WT_NATIVE_PKG = "<解压后的 wt-missile-backend 目录>"
    python scripts\\native_identify_loft.py
    python scripts\\native_identify_loft.py --ranges 15 30 50 70 --jobs 4

输出：results/loft_identify_native.json（退出表 + 退出前后全分辨率证据窗口 + 全程抽稀序列）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RES_DIR = ROOT / "results"

# 高抛四参数从标准弹的 blk 自动读取（默认 AIM-120C5）；下面的值是回退默认
FALLBACK = {"loftElevation": 22.0, "loftTargetElevation": -3.5,
            "loftTargetOmegaMax": 0.95, "loftAngleToAccelMult": 5.0,
            "timeFire": 7.75, "force": 15542.0, "mass": 161.4789, "massEnd": 110.223}


def read_blk_params(pkg: Path, missile: str, version: str) -> dict:
    """从原生包自带的 blk 里取高抛/发动机参数。

    blk 里同名键会重复（`mass` 在战斗部等子块里也有），所以**同名取第一个**——
    顶层 `rocket {` 块里的那一份才是发动机参数。
    """
    import re                                          # noqa: PLC0415
    p = (Path(pkg) / "inputs" / "resources" / version
         / f"gamedata__weapons__rocketguns__{missile}.blk")
    got = dict(FALLBACK)
    if not p.exists():
        return got
    seen: set[str] = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.fullmatch(r"\s*(\w+):(\w+)\s*=\s*(.*?)\s*", line)
        if not (m and m.group(1) in got and m.group(1) not in seen):
            continue
        kind, v = m.group(2), m.group(3)
        if kind == "r":
            got[m.group(1)] = float(v)
        elif kind == "i":
            got[m.group(1)] = float(int(v))
        else:
            continue
        seen.add(m.group(1))
    return got


def _worker(payload):
    pkg, rng, alt, vm0, vt, dt, sample, missile = payload
    pkg = Path(pkg)
    sys.path.insert(0, str(pkg))
    sys.path.insert(0, str(pkg / "tools"))
    import simulator.core as core                      # noqa: PLC0415
    import simulator.resources as resources            # noqa: PLC0415

    raw = {
        "schema_version": 1, "label": f"loft-ident {rng / 1000:.0f}km", "missile": missile,
        "version": resources.VERSION, "duration_s": 150.0, "dt_s": dt, "sample_period_s": sample,
        "observation": {"mode": "ideal"},
        "launch": {"position_m": [0.0, alt, 0.0], "velocity_m_s": [vm0, 0.0, 0.0]},
        "target": {"position_m": [rng, alt, 0.0], "velocity_m_s": [vt, 0.0, 0.0],
                   "collision_radius_m": 3.0},
    }
    _s, summary, samples = core.simulate(raw)
    return f"{rng / 1000:.0f}km", summary, samples


def derive(samples, sample_dt):
    """把原生状态序列换成几何量序列（2D 纵向平面）。"""
    rows, prev_lam = [], None
    for sm in samples:
        x, y = sm["missile_x_m"], sm["missile_y_m"]
        vx, vy = sm["missile_vx_m_s"], sm["missile_vy_m_s"]
        gamma = math.atan2(vy, vx)
        theta = 2.0 * math.atan2(sm["qz"], sm["qw"])       # 绕 z 轴的俯仰姿态
        lam = math.atan2(sm["target_y_m"] - y, sm["target_x_m"] - x)
        lam_dot = None if prev_lam is None else (lam - prev_lam) / sample_dt
        prev_lam = lam
        rows.append({"t": sm["time_s"],
                     "gamma_deg": math.degrees(gamma), "theta_deg": math.degrees(theta),
                     "alpha_deg": math.degrees(theta - gamma),
                     "lam_deg": math.degrees(lam), "lam_dot_deg_s": None if lam_dot is None
                     else math.degrees(lam_dot),
                     "v": sm["speed_m_s"], "range_m": sm["range_m"],
                     "req_g": sm["requested_g"], "thrust_N": sm["thrust_N"]})
    return rows


def identify(rows, omega_max: float, elev_deg: float):
    """按两个候选条件定位退出时刻（谁先满足算谁）。"""
    om = next((r for r in rows if r["lam_dot_deg_s"] is not None
               and abs(r["lam_dot_deg_s"]) >= omega_max), None)
    el = next((r for r in rows if r["lam_deg"] <= elev_deg), None)
    cands = [x for x in ((om, "loftTargetOmegaMax"), (el, "loftTargetElevation")) if x[0]]
    if not cands:
        return None, None, om, el
    row, trigger = min(cands, key=lambda x: x[0]["t"])
    return row, trigger, om, el


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从原生采样辨识高抛退出判据")
    ap.add_argument("--ranges", nargs="+", type=float, default=[15000.0, 30000.0, 50000.0, 70000.0],
                    help="射程 [m]")
    ap.add_argument("--alt", type=float, default=10000.0)
    ap.add_argument("--vm0", type=float, default=300.0)
    ap.add_argument("--vt", type=float, default=-300.0)
    ap.add_argument("--dt", type=float, default=0.01)
    ap.add_argument("--sample", type=float, default=0.02)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--missile", default="us_aim_120c_5",
                    help="标准弹（原生 profile 名，如 cn_pl12 / us_aim_120c_5）")
    ap.add_argument("--version", default="2.59.0.28")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    pkg = os.environ.get("WT_NATIVE_PKG", "").strip()
    if not pkg or not (Path(pkg) / "tools" / "simulator" / "core.py").exists():
        print("需要 WT_NATIVE_PKG 指向解压后的 wt-missile-backend（包体不入库）", file=sys.stderr)
        return 2

    blk = read_blk_params(pkg, args.missile, args.version)
    om_max = blk["loftTargetOmegaMax"]
    elev = blk["loftTargetElevation"]
    print(f"标准弹 {args.missile} @ {args.version} 的 blk 高抛参数：")
    print(f"  loftElevation={blk['loftElevation']:g}°  loftTargetElevation={elev:g}°  "
          f"loftTargetOmegaMax={om_max:g}°/s  loftAngleToAccelMult={blk['loftAngleToAccelMult']:g}")
    print(f"  发动机：mass {blk['mass']:g} → massEnd {blk['massEnd']:g} kg，"
          f"force {blk['force']:g} N，timeFire {blk['timeFire']:g} s\n")

    payloads = [(pkg, r, args.alt, args.vm0, args.vt, args.dt, args.sample, args.missile)
                for r in args.ranges]
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(_worker, payloads))

    tag = args.tag or f"loft_identify_{args.missile}"
    out = {"source": f"native {args.missile} @ {args.version}, ideal mode, alt={args.alt:g}, "
                     f"vm0={args.vm0:g}, vt={args.vt:g}, dt={args.dt:g}, sample={args.sample:g}",
           "blk_loft_params": {"loftElevation_deg": blk["loftElevation"],
                               "loftTargetElevation_deg": elev,
                               "loftTargetOmegaMax_deg_s": om_max,
                               "loftAngleToAccelMult": blk["loftAngleToAccelMult"]},
           "cases": {}}
    print(f"{'射程':<7}{'退出 t[s]':>10}{'触发源':>24}{f'|λ̇|首次≥{om_max:g}':>16}"
          f"{f'λ首次≤{elev:g}':>14}{'退出时 γ':>10}{'θ':>8}{'α':>8}{'λ':>8}{'λ̇':>9}")
    for name, summary, samples in results:
        rows = derive(samples, args.sample)
        row, trigger, om, el = identify(rows, om_max, elev)
        keep = set(range(0, len(rows), 25))            # 全程抽稀（0.5 s）
        if row is not None:
            i = rows.index(row)
            keep |= set(range(max(0, i - 60), min(len(rows), i + 25)))   # 退出前后全分辨率
        out["cases"][name] = {
            "summary": {k: summary[k] for k in ("time_s", "final_speed_m_s", "terminal_event", "steps")},
            "exit_t_s": None if row is None else row["t"], "trigger": trigger,
            "lam_dot_first_t_s": None if om is None else om["t"],
            "lam_le_elev_first_t_s": None if el is None else el["t"],
            "exit_row": row, "samples": [rows[i] for i in sorted(keep)]}
        if row is None:
            print(f"{name:<7}{'—':>10}{'未触发（两个条件都没满足）':>24}")
            continue
        om_t = "—" if om is None else f"{om['t']:.2f}"
        el_t = "—" if el is None else f"{el['t']:.2f}"
        print(f"{name:<7}{row['t']:10.2f}{trigger:>24}{om_t:>16}{el_t:>14}"
              f"{row['gamma_deg']:10.2f}{row['theta_deg']:8.2f}{row['alpha_deg']:8.2f}"
              f"{row['lam_deg']:8.2f}{row['lam_dot_deg_s']:9.3f}")

    RES_DIR.mkdir(parents=True, exist_ok=True)
    p = RES_DIR / f"{tag}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结论：退出条件 = 「|λ̇| ≥ loftTargetOmegaMax({om_max:g} °/s)」 或 "
          f"「λ ≤ loftTargetElevation({elev:g}°)」，先满足者生效。\nJSON：{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

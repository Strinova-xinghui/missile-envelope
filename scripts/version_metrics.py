"""按自动化分析工作流的权威口径复算各版本主动弹 (ΔV, BC)，并与参考图核对。

权威口径（来自 E:\\WT\\War-Thunder-Datamine\\自动化分析\\skills\\wt-aam-analysis\\scripts\\plot_version_compare.py 的 metrics()）：

    cal   = rk["caliber"]                     # 注意：blkx 里已经是【米】
    fu1   = mass - massEnd                    # 一级装药
    fu2   = massEnd - massEnd1                # 二级装药（存在 massEnd1 时）
    Isp1  = force·timeFire /(9.81·fu1)        # 一级
    ΔV1   = Isp1·9.81·ln(mass/(mass-fu1))
    Isp2  = force1·timeFire1/(9.81·fu2)       # 二级
    ΔV2   = Isp2·9.81·ln((mass-fu1)/(mass-fu1-fu2))
    ΔV    = ΔV1 + ΔV2（无二级取 ΔV1）
    dry   = mass - fu1 - fu2                  # = massEnd1（干重）
    BC    = dry / (CxK · (cal/2)² · π)        # cal 已是米，故等价于 (d/2000)² 用 d[mm]

取数来源：
    WORK / 当前 = 工作区 checkout（= 实机 2.59.0.11 的解包数据）
    其它 tag    = git show <tag>:<path>（datamine 仓库，tags 2.57.1.132 / 2.58.0.35 / 2.58.0.27）

输出：results/version_metrics.json（含各版本值、与参考图像素点的对照）
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "version_metrics.json"
REPO = Path(r"E:\WT\War-Thunder-Datamine")
REL = "aces.vromfs.bin_u/gamedata/weapons/rocketguns"
G = 9.81

# 工作流配置里的 11 型（短名 → blkx 文件）
MISSILES = [
    ("120A", "us_aim_120a.blkx"), ("120C", "us_aim_120c_5.blkx"), ("120D", "us_aim_120d.blkx"),
    ("MICA", "fr_mica_em.blkx"), ("AAM-4", "jp_aam4.blkx"), ("PL-12", "cn_pl12.blkx"),
    ("PL-12A", "cn_pl12a.blkx"), ("R-77", "su_r_77.blkx"), ("R-77-1", "su_r_77_1.blkx"),
    ("Derby", "il_derby.blkx"), ("R-Darter", "r_darter.blkx"),
]
TAGS = ["2.57.1.132", "2.58.0.35", "2.58.0.27", "WORK"]

# 参考图像素读出的点（results/reference_points.json）
FIGURE = {
    "R-77": (816.4, 2581.2), "MICA": (829.6, 3108.0), "120A": (829.8, 3616.2),
    "AAM-4": (834.9, 3687.8), "120D": (898.3, 3659.3), "120C": (904.2, 3630.3),
    "PL-12": (920.1, 2674.1), "Derby": (938.2, 3104.3), "R-Darter": (938.4, 2612.5),
    "R-77-1": (970.2, 2613.9), "PL-12A": (992.9, 3266.4),
}


def load_rocket(tag: str, fname: str):
    path = f"{REL}/{fname}"
    if tag.upper() == "WORK":
        p = REPO / REL.replace("/", "\\") / fname
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8", errors="replace")).get("rocket")
    r = subprocess.run(["git", "-C", str(REPO), "show", f"{tag}:{path}"],
                       capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace")).get("rocket")
    except json.JSONDecodeError:
        return None


def metrics(rk):
    """工作流 plot_version_compare.py 里的同款实现（逐行照抄）。"""
    if not rk:
        return None
    m, me, me1 = rk.get("mass"), rk.get("massEnd"), rk.get("massEnd1")
    f0, t0, f1, t1 = rk.get("force"), rk.get("timeFire"), rk.get("force1"), rk.get("timeFire1")
    cxk, cal = rk.get("CxK"), rk.get("caliber")
    if not all([m, me, f0, t0, cxk, cal]):
        return None
    fu1 = m - me
    isp1 = f0 * t0 / (G * fu1)
    dv1 = isp1 * G * math.log(m / (m - fu1))
    two = me1 is not None and f1 and t1
    fu2 = (me - me1) if two else 0
    dv2 = None
    isp2 = None
    if two and fu2 > 0:
        isp2 = f1 * t1 / (G * fu2)
        dv2 = isp2 * G * math.log((m - fu1) / (m - fu1 - fu2))
    tot = dv1 + dv2 if dv2 else dv1
    dry = m - fu1 - (fu2 or 0)
    return {"dv": tot, "bc": dry / (cxk * (cal / 2) ** 2 * math.pi),
            "fu1": fu1, "fu2": fu2, "dry": dry, "two_stage": bool(two),
            "isp1": isp1, "isp2": isp2, "mass": m, "massEnd": me, "massEnd1": me1,
            "force": f0, "timeFire": t0, "force1": f1, "timeFire1": t1,
            "CxK": cxk, "caliber": cal}


def main() -> int:
    data = {}
    for short, fname in MISSILES:
        data[short] = {}
        for tag in TAGS:
            data[short][tag] = metrics(load_rocket(tag, fname))

    # 对照表：2.57 基线 vs 参考图像素点
    print("=== 2.57.1.132 基线（应为参考图上的点）与像素点对照 ===")
    print(f"{'弹':<8} {'基线 ΔV':>9} {'基线 BC':>9} {'图 ΔV':>8} {'图 BC':>8} {'ΔΔV':>7} {'ΔBC':>8}")
    base_match = []
    for short, _ in MISSILES:
        o = data[short].get("2.57.1.132")
        f = FIGURE.get(short)
        if not o or not f:
            print(f"{short:<8} {'—':>9}")
            continue
        d_dv, d_bc = f[0] - o["dv"], f[1] - o["bc"]
        ok = abs(d_dv) < 25 and abs(d_bc) < 150
        base_match.append(short if ok else None)
        print(f"{short:<8} {o['dv']:9.1f} {o['bc']:9.1f} {f[0]:8.1f} {f[1]:8.1f} {d_dv:7.1f} {d_bc:8.1f}"
              + ("   ✓" if ok else ""))
    print(f"\n基线对上的：{[x for x in base_match if x]}")

    # 版本漂移：当前(WORK) vs 基线
    print("\n=== 版本漂移：当前（WORK = 2.59.0.11 实机）相对 2.57 基线 ===")
    print(f"{'弹':<8} {'旧 ΔV':>8} {'新 ΔV':>8} {'ΔΔV':>7} | {'旧 BC':>8} {'新 BC':>8} {'ΔBC':>8} | 两级?")
    drift = []
    for short, _ in MISSILES:
        o = data[short].get("2.57.1.132")
        n = data[short].get("WORK")
        if not o or not n:
            print(f"{short:<8} 数据缺失")
            continue
        print(f"{short:<8} {o['dv']:8.1f} {n['dv']:8.1f} {n['dv'] - o['dv']:+7.1f} | "
              f"{o['bc']:8.1f} {n['bc']:8.1f} {n['bc'] - o['bc']:+8.1f} | "
              f"{'是' if n['two_stage'] else '否'}")
        drift.append({"short": short, "d_dv": n["dv"] - o["dv"], "d_bc": n["bc"] - o["bc"]})

    payload = {
        "formula_source": "自动化分析/skills/wt-aam-analysis/scripts/plot_version_compare.py :: metrics()",
        "repo": str(REPO), "rel": REL, "tags": TAGS,
        "figure_points": FIGURE,
        "metrics": data,
        "drift_current_vs_baseline": drift,
        "baseline_matches_figure": [x for x in base_match if x],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已写出 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

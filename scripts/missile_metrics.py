"""导弹 ΔV / BC 的权威口径实现（唯一来源，勿在别处另写一份公式）。

公式逐行照抄 `E:\\WT\\War-Thunder-Datamine\\自动化分析\\skills\\wt-aam-analysis\\scripts\\plot_version_compare.py`
里的 `metrics()`：

    fu1 = mass - massEnd                      # 一级装药
    fu2 = massEnd - massEnd1                  # 二级装药（无 massEnd1 时为 0）
    Isp1 = force  * timeFire  / (9.81 * fu1)
    dV1  = Isp1 * 9.81 * ln(mass / (mass - fu1))
    Isp2 = force1 * timeFire1 / (9.81 * fu2)  # 仅两级弹
    dV2  = Isp2 * 9.81 * ln((mass - fu1) / (mass - fu1 - fu2))
    Total dV = dV1 + dV2 或 dV1
    dry  = mass - fu1 - fu2                   # = massEnd1
    BC   = dry / (CxK * (caliber / 2)^2 * pi) # caliber 已是【米】

数据源：工作区 checkout（= 实机 2.59.0.11）；历史版本用 `git show <tag>:<path>`。
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

G = 9.81
REPO = Path(r"E:\WT\War-Thunder-Datamine")
REL = "aces.vromfs.bin_u/gamedata/weapons/rocketguns"
WORK = "WORK"

# 自动化分析工作流 aam_config.json 里的导弹清单（短名 → blkx 文件 / 图上标签）
MISSILE_FILES = [
    ("120A", "us_aim_120a.blkx", "AIM-120A/B"),
    ("120C", "us_aim_120c_5.blkx", "AIM-120C-5/7"),
    ("120D", "us_aim_120d.blkx", "AIM-120D"),
    ("MICA", "fr_mica_em.blkx", "MICA-EM"),
    ("AAM-4", "jp_aam4.blkx", "AAM-4"),
    ("PL-12", "cn_pl12.blkx", "PL-12"),
    ("PL-12A", "cn_pl12a.blkx", "PL-12A"),
    ("R-77", "su_r_77.blkx", "R-77/RVV-AE"),
    ("R-77-1", "su_r_77_1.blkx", "R-77-1/RVV-SD"),
    ("Derby", "il_derby.blkx", "Derby"),
    ("R-Darter", "r_darter.blkx", "R-Darter"),
]


def load_rocket(tag: str, fname: str):
    """取某版本的 `rocket` 块；tag=WORK 用工作区文件，其余走 git show。"""
    if str(tag).upper() == WORK:
        p = REPO / REL.replace("/", "\\") / fname
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8", errors="replace")).get("rocket")
    r = subprocess.run(["git", "-C", str(REPO), "show", f"{tag}:{REL}/{fname}"], capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace")).get("rocket")
    except json.JSONDecodeError:
        return None


def metrics(rk):
    """权威口径；返回 None 表示字段不全。"""
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
            "two_stage": bool(two), "fu1": fu1, "fu2": fu2, "dry": dry,
            "isp1": isp1, "isp2": isp2, "mass": m, "massEnd": me, "massEnd1": me1,
            "force": f0, "timeFire": t0, "force1": f1, "timeFire1": t1,
            "CxK": cxk, "caliber_m": cal, "caliber_mm": (cal * 1000.0 if cal else None)}


def all_versions(tags) -> dict:
    """返回 {短名: {tag: metrics}}。"""
    out = {}
    for short, fname, _key in MISSILE_FILES:
        out[short] = {tag: metrics(load_rocket(tag, fname)) for tag in tags}
    return out


def current_missiles(tag: str = WORK) -> list:
    """最新口径（默认工作区 = 实机 2.59.0.11）的弹列表，供出图使用。"""
    rows = []
    for short, fname, key in MISSILE_FILES:
        got = metrics(load_rocket(tag, fname))
        if not got:
            continue
        rows.append({
            "name": key, "label": short, "file": fname,
            "dv": got["dv"], "bc": got["bc"],
            "k": got["CxK"], "d_mm": got["caliber_mm"],
            "two_stage": got["two_stage"], "dry": got["dry"],
            "source": f"blkx {tag}（权威口径）",
        })
    return rows


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"{'弹':<8} {'ΔV':>8} {'BC':>9} {'两级':>5} {'干重':>8} {'CxK':>7} {'口径mm':>7}")
    for r in current_missiles():
        print(f"{r['label']:<8} {r['dv']:8.1f} {r['bc']:9.1f} "
              f"{'是' if r['two_stage'] else '否':>5} {r['dry']:8.2f} {r['k']:7.3f} {r['d_mm']:7.1f}")

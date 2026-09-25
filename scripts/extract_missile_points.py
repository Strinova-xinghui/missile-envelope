"""从 War Thunder 解包数据提取主动弹的 (ΔV, BC) 并复算线性拟合，用于与既有散点图核对。

ΔV、BC 采用与 AGENTS.md 完全一致的口径：
    Isp = t·F / (9.81·m_fuel)
    ΔV  = Isp·9.81·ln(m0 / (m0 − m_fuel))
    BC  = (m0 − m_fuel) / (k · (d/2000)² · π)
两处都做了多级（m1/m2）与单级兼容处理。
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROCKETS = Path(r"E:\WT\War-Thunder-Datamine\aces.vromfs.bin_u\gamedata\weapons\rocketguns")

# 图中出现的弹（对应 blkx）
MISSILES = [
    ("AAM-4", "jp_aam4.blkx"),
    ("120A", "us_aim_120a.blkx"),
    ("120C", "us_aim_120c_5.blkx"),
    ("120D", "us_aim_120d.blkx"),
    ("MICA", "fr_mica_em.blkx"),
    ("PL-12", "cn_pl12.blkx"),
    ("PL-12A", "cn_pl12a.blkx"),
    ("R-Darter", "r_darter.blkx"),
    ("Derby", "il_derby.blkx"),
    ("R-77", "su_r_77.blkx"),
    ("R-77-1", "su_r_77_1.blkx"),
]

NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def field(text: str, key: str):
    m = re.search(rf'"{key}"\s*:\s*({NUM})', text)
    return float(m.group(1)) if m else None


def stages_from_blkx_text(text: str):
    """返回 (m0, mass_end, stages=[(F,t)], k, d)。"""
    m0 = field(text, "mass")
    mass_end = field(text, "massEnd")
    k = field(text, "CxK")
    d = field(text, "caliber")
    if d is not None and d < 1.0:  # blkx 里 caliber 是米
        d = d * 1000.0
    # 单级：force/timeFire；多级：force1/timeFire1 ... 或每级独立 rocket 段（本表用不到）
    force = field(text, "force")
    time_fire = field(text, "timeFire")
    stages = []
    if force and time_fire:
        stages.append((force, time_fire))
    i = 1
    while True:
        f = field(text, f"force{i}")
        t = field(text, f"timeFire{i}")
        if not f or not t:
            break
        stages.append((f, t))
        i += 1
    return m0, mass_end, stages, k, d


def compute(m0, mass_end, stages, k, d):
    # 与 AGENTS.md 的 Isp/dV 公式等价：这里直接用总装药与总冲，多级按顺序累加
    m_fuel_total = (m0 - mass_end) if (m0 and mass_end) else None
    total_impulse = sum(f * t for f, t in stages)
    if not (m0 and m_fuel_total and total_impulse):
        return None
    isp = total_impulse / (9.81 * m_fuel_total)
    dv = isp * 9.81 * math.log(m0 / (m0 - m_fuel_total))
    bc = (m0 - m_fuel_total) / (k * (d / 2000.0) ** 2 * math.pi)
    return dv, bc, isp, m_fuel_total, total_impulse


def main() -> int:
    rows = []
    print(f"{'弹':<10} {'m0':>9} {'装药':>8} {'总冲':>10} {'Isp':>7} {'ΔV':>8} {'BC':>8}")
    for name, fname in MISSILES:
        path = ROCKETS / fname
        if not path.exists():
            print(f"{name:<10} 缺少文件 {fname}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m0, mass_end, stages, k, d = stages_from_blkx_text(text)
        got = compute(m0, mass_end, stages, k, d)
        if not got:
            print(f"{name:<10} 参数不全：m0={m0} massEnd={mass_end} stages={stages}")
            continue
        dv, bc, isp, fuel, imp = got
        rows.append({"name": name, "file": fname, "dv": dv, "bc": bc, "isp": isp,
                     "m0": m0, "fuel": fuel, "impulse": imp, "k": k, "d": d, "mass_end": mass_end})
        print(f"{name:<10} {m0:9.3f} {fuel:8.3f} {imp:10.1f} {isp:7.1f} {dv:8.1f} {bc:8.1f}")

    if len(rows) >= 2:
        xs = [r["dv"] for r in rows]
        ys = [r["bc"] for r in rows]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in ys)
        slope = sxy / sxx
        intercept = my - slope * mx
        r2 = (sxy ** 2) / (sxx * syy)
        print(f"\n线性拟合 y = {slope:.4f} x + {intercept:.1f},  R² = {r2:.4f},  n = {n}")
    out = Path(__file__).resolve().parents[1] / "results" / "missile_points.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

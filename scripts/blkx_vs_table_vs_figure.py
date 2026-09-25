"""最终口径对照：当前解包 blkx（完整两段推力）复算值 vs WT.xlsx 表缓存值 vs 参考图像素点。

背景：AAM/PL-12 等在 blkx 里是"两段"结构：
    "force": F_a, "timeFire": t_a    ← 第一段（助推）
    "force1": F_b, "timeFire1": t_b  ← 第二段（主发动机，字段名带下标 1）
早期脚本只读了 `force`/`timeFire`，漏掉第二段，导致 ΔV 被严重低估（PL-12 只有 490 而不是 932）。

本脚本按完整两段公式复算，并与表内公式复算值、表内缓存值、参考图像素值逐列对照：
    Isp_i = t_i·F_i/(9.81·m_i)
    ΔV_i  = Isp_i·9.81·ln(m_before/(m_before − m_i))
    BC    = (m0 − m1 − m2)/(k·(d/2000)²·π)
其中 blkx 口径下 m1 = mass − massEnd 全部按第一段处理（blkx 未分列两级装药），
第二段推力按 blkx 的 `force1/timeFire1` 计入。
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import wt_missiles  # noqa: E402

ROCKETS = Path(r"E:\WT\War-Thunder-Datamine\aces.vromfs.bin_u\gamedata\weapons\rocketguns")
OUT = Path(__file__).resolve().parents[1] / "results" / "blkx_vs_table_vs_figure.json"
NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"

FILE_MAP = {
    "AIM-120A (2.58.0.27)": "us_aim_120a.blkx",
    "AIM-120C-5 (2.58.0.27)": "us_aim_120c_5.blkx",
    "AIM-120D (2.58.0.27)": "us_aim_120d.blkx",
    "AAM-4": "jp_aam4.blkx",
    "Derby": "il_derby.blkx",
    "R-Darter": "r_darter.blkx",
    "MICA EM (new)": "fr_mica_em.blkx",
    "PL-12": "cn_pl12.blkx",
    "PL-12A": "cn_pl12a.blkx",
    "R-77": "su_r_77.blkx",
    "R-77-1": "su_r_77_1.blkx",
}
SHORT = {
    "AIM-120A (2.58.0.27)": "120A", "AIM-120C-5 (2.58.0.27)": "120C",
    "AIM-120D (2.58.0.27)": "120D", "AAM-4": "AAM-4", "MICA EM (new)": "MICA",
    "PL-12": "PL-12", "PL-12A": "PL-12A", "R-Darter": "R-Darter",
    "Derby": "Derby", "R-77": "R-77", "R-77-1": "R-77-1",
}
# 参考图像素点（scripts/extract_reference_points.py 解出）
FIGURE = {
    "120A": (829.8, 3616.2), "120C": (904.2, 3630.3), "120D": (898.3, 3659.3),
    "AAM-4": (834.9, 3687.8), "MICA": (829.6, 3108.0), "PL-12": (920.1, 2674.1),
    "PL-12A": (992.9, 3266.4), "R-Darter": (938.4, 2612.5), "Derby": (938.2, 3104.3),
    "R-77": (816.4, 2581.2), "R-77-1": (970.2, 2613.9),
}


def field(text: str, key: str):
    m = re.search(rf'"{key}"\s*:\s*({NUM})', text)
    return float(m.group(1)) if m else None


def read_blkx_full(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    i = text.find('"rocket"')
    blk = text[i:] if i >= 0 else text
    d = field(blk, "caliber")
    if d and d < 1.0:
        d *= 1000.0
    return {
        "file": path.name,
        "m0": field(blk, "mass"),
        "mass_end": field(blk, "massEnd"),
        "k": field(blk, "CxK"),
        "d_mm": d,
        "force": field(blk, "force"),
        "time": field(blk, "timeFire"),
        "force1": field(blk, "force1"),      # 第二段
        "time1": field(blk, "timeFire1"),
        "delay1": field(blk, "fireDelay1") or field(blk, "startDelay1"),
    }


def compute_two_stage(rec):
    """按完整两段复算：第一段用全部装药，第二段推力按 blkx 的 force1/timeFire1 计入。

    这是"blkx 口径"的复算（blkx 未分列两级装药，只能这么算）：
        ΔV_total = Isp1·g·ln(m0/(m0−m_fuel)) + Isp2·g·ln(1)  —— 第二段无独立装药时只贡献推力时间
    为可比较，第二段按"同一份装药、额外推力时间"处理：Isp_eff = (t_a·F_a + t_b·F_b)/(9.81·m_fuel)
    """
    m0, me, k, d = rec["m0"], rec["mass_end"], rec["k"], rec["d_mm"]
    if not (m0 and me and k and d):
        return None
    fuel = m0 - me
    impulse = 0.0
    if rec["force"] and rec["time"]:
        impulse += rec["force"] * rec["time"]
    if rec["force1"] and rec["time1"]:
        impulse += rec["force1"] * rec["time1"]
    if impulse <= 0 or fuel <= 0:
        return None
    isp_eff = impulse / (9.81 * fuel)
    dv = isp_eff * 9.81 * math.log(m0 / (m0 - fuel))
    bc = (m0 - fuel) / (k * (d / 2000.0) ** 2 * math.pi)
    return {"isp_eff": isp_eff, "dv": dv, "bc": bc, "fuel": fuel,
            "impulse": impulse, "two_stage": bool(rec["force1"] and rec["time1"])}


def main() -> int:
    table = wt_missiles.read_sheet()
    print(f"{'弹':<8} {'blkx ΔV':>8} {'blkx BC':>8} | {'表 ΔV':>8} {'表 BC':>8} | "
          f"{'图 ΔV':>8} {'图 BC':>8} | {'两段?':>5} {'表缓存 ΔV':>9}")
    rows = []
    for name, fname in FILE_MAP.items():
        path = ROCKETS / fname
        blk = read_blkx_full(path)
        blk_calc = compute_two_stage(blk)
        rec = table.get(name) or {}
        comp = rec.get("computed") or {}
        tab_calc_dv, tab_calc_bc = comp.get("dv"), comp.get("bc")
        tab_ca_dv, tab_ca_bc = rec.get("dv_cached"), rec.get("bc_cached")
        label = SHORT[name]
        f_dv, f_bc = FIGURE.get(label, (float("nan"), float("nan")))
        print(f"{label:<8} {blk_calc['dv']:8.1f} {blk_calc['bc']:8.1f} | "
              f"{tab_calc_dv:8.1f} {tab_calc_bc:8.1f} | {f_dv:8.1f} {f_bc:8.1f} | "
              f"{'是' if blk_calc['two_stage'] else '否':>5} {(tab_ca_dv if tab_ca_dv else float('nan')):9.1f}")
        rows.append({"label": label, "table_name": name, "file": fname,
                     "blkx_calc": blk_calc, "blkx_raw": blk,
                     "table_calc": {"dv": tab_calc_dv, "bc": tab_calc_bc},
                     "table_cached": {"dv": tab_ca_dv, "bc": tab_ca_bc},
                     "figure": {"dv": f_dv, "bc": f_bc}})

    print("\n差异小结：")
    agree_blkx_tab, agree_tab_fig, agree_blkx_fig = [], [], []
    for r in rows:
        a = r["blkx_calc"]["dv"] - r["table_calc"]["dv"]
        b = r["table_calc"]["dv"] - r["figure"]["dv"]
        c = r["blkx_calc"]["dv"] - r["figure"]["dv"]
        (agree_blkx_tab if abs(a) < 1.0 else []).append(r["label"])
        (agree_tab_fig if abs(b) < 25.0 else []).append(r["label"])
        (agree_blkx_fig if abs(c) < 25.0 else []).append(r["label"])
    print(f"  blkx 复算 ≈ 表内复算（<1 m/s）：{agree_blkx_tab or '无'}")
    print(f"  表值 ≈ 参考图（<25 m/s）：{agree_tab_fig or '无'}")
    print(f"  blkx 值 ≈ 参考图（<25 m/s）：{agree_blkx_fig or '无'}")
    print("  → 表内复算与 blkx 一致说明参数同源；表内缓存值与图一致说明缓存值是当时口径；")
    print("    blkx 与图不一致的弹（如 R-77/MICA）说明该弹在 2.58→2.59 之间被改过。")

    OUT.write_text(json.dumps({"rocketguns": str(ROCKETS), "rows": rows},
                              ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已写出 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

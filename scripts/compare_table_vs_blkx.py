"""三方对照：WT.xlsx 表值 / 当前 rocketguns blkx 原始字段 / 参考图像素点。

目的：判定 WT.xlsx（列名 2.58.0.27）与当前解包版本（2.59.0.11）之间是否发生了数据变动，
以及原图（2.58.0.35）的点更接近哪一边。

口径说明：
  表值 = 表内公式复算（scripts/wt_missiles.py）
  blkx 值 = 取 `rocket` 块字段后套同一套公式：
      m1 = mass - massEnd（单级）；若存在 force1/timeFire1 则按两级累加
      Isp = t·F/(9.81·m_fuel)；ΔV = Isp·9.81·ln(m0/(m0-m_fuel))
      BC = (m0 - m_fuel)/(k·(d/2000)²·π)
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
DATAMINE_VERSION = Path(r"E:\WT\War-Thunder-Datamine\version")

# 表内列名 → blkx 文件（按机翻名/通用名匹配）
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
NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def field(text: str, key: str):
    m = re.search(rf'"{key}"\s*:\s*({NUM})', text)
    return float(m.group(1)) if m else None


def rocket_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    i = text.find('"rocket"')
    return text[i:] if i >= 0 else text


def read_blkx(path: Path):
    blk = rocket_block(path)
    m0 = field(blk, "mass")
    mass_end = field(blk, "massEnd")
    k = field(blk, "CxK")
    d = field(blk, "caliber")
    if d is not None and d < 1.0:
        d *= 1000.0
    stages = []
    f1, t1 = field(blk, "force"), field(blk, "timeFire")
    if f1 and t1:
        stages.append((f1, t1))
    i = 1
    while True:
        f = field(blk, f"force{i}")
        t = field(blk, f"timeFire{i}")
        if not (f and t):
            break
        stages.append((f, t))
        i += 1
    return {"file": path.name, "m0": m0, "mass_end": mass_end, "k": k, "d_mm": d,
            "stages": stages, "n_stage": len(stages)}


def compute_blkx(rec):
    """按 blkx 单级口径算（blkx 没有二级装药分列的字段）。"""
    m0, me, k, d = rec["m0"], rec["mass_end"], rec["k"], rec["d_mm"]
    if not (m0 and me and k and d):
        return None
    fuel = m0 - me
    if fuel <= 0:
        return None
    f, t = rec["stages"][0] if rec["stages"] else (None, None)
    if not (f and t):
        return None
    isp = t * f / (9.81 * fuel)
    dv = isp * 9.81 * math.log(m0 / (m0 - fuel))
    bc = (m0 - fuel) / (k * (d / 2000.0) ** 2 * math.pi)
    return {"isp": isp, "dv": dv, "bc": bc, "fuel": fuel,
            "force": f, "time": t}


def main() -> int:
    ver = DATAMINE_VERSION.read_text(encoding="utf-8", errors="replace").strip() if DATAMINE_VERSION.exists() else "?"
    print(f"解包数据版本（War-Thunder-Datamine/version）= {ver}")
    print(f"rocketguns 目录 mtime = {ROCKETS.stat().st_mtime}")
    table = wt_missiles.read_sheet()

    print(f"\n{'表内列名':<22} {'表 ΔV':>7} {'表 BC':>7} {'blkx ΔV':>7} {'blkx BC':>7} "
          f"{'ΔΔV':>7} {'ΔBC':>7}  {'blkx 单级参数 (m0/massEnd/F/t/k/d)'}")
    rows = []
    for name, fname in FILE_MAP.items():
        path = ROCKETS / fname
        rec_blk = read_blkx(path) if path.exists() else None
        got = compute_blkx(rec_blk) if rec_blk else None
        rec_tab = table.get(name) or {}
        comp = rec_tab.get("computed") or {}
        t_dv, t_bc = comp.get("dv"), comp.get("bc")
        if got:
            d_dv, d_bc = t_dv - got["dv"], t_bc - got["bc"]
            params = (f"{rec_blk['m0']:.2f}/{rec_blk['mass_end']:.2f}/{got['force']:.0f}/{got['time']:.2f}"
                      f"/{rec_blk['k']:.3f}/{rec_blk['d_mm']:.1f}")
            print(f"{name:<22} {t_dv:7.1f} {t_bc:7.1f} {got['dv']:7.1f} {got['bc']:7.1f} "
                  f"{d_dv:7.1f} {d_bc:7.1f}  {params}")
            rows.append({"name": name, "file": fname, "table_dv": t_dv, "table_bc": t_bc,
                         "blkx_dv": got["dv"], "blkx_bc": got["bc"], "d_dv": d_dv, "d_bc": d_bc,
                         "blkx": rec_blk,
                         "table": {"m0": rec_tab.get("m0"), "m1": rec_tab.get("m1"),
                                   "m2": rec_tab.get("m2"), "f1": rec_tab.get("f1"),
                                   "t1": rec_tab.get("t1"), "f2": rec_tab.get("f2"),
                                   "t2": rec_tab.get("t2"), "k": rec_tab.get("k"),
                                   "d_mm": rec_tab.get("d_mm")}})
        else:
            print(f"{name:<22} {str(t_dv):>7} {str(t_bc):>7} {'—':>7} {'—':>7}  参数不全（{fname}）")

    out = Path(__file__).resolve().parents[1] / "results" / "table_vs_blkx.json"
    out.write_text(json.dumps({"datamine_version": ver, "rocketguns_dir": str(ROCKETS),
                               "rows": rows}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

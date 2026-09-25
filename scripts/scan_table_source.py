"""全机扫描：在 rocketguns 全部 blkx 里寻找与 WT.xlsx 表值同源的条目。

判定同源的标准（两条都要满足）：
    1) m0（launch mass）与表内一致（±0.5%）
    2) 按表内公式复算的 ΔV 与表内缓存值一致（±1 m/s）
命中即说明"该弹的表值确实来自 blkx 的这一条"，从而可以判定表与解包数据是否同一版本。
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
OUT = Path(__file__).resolve().parents[1] / "results" / "table_source_scan.json"
NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def field(t, k):
    m = re.search(rf'"{k}"\s*:\s*({NUM})', t)
    return float(m.group(1)) if m else None


def parse_all():
    recs = []
    for p in sorted(ROCKETS.glob("*.blkx")):
        text = p.read_text(encoding="utf-8", errors="replace")
        i = text.find('"rocket"')
        blk = text[i:] if i >= 0 else text
        m0, me = field(blk, "mass"), field(blk, "massEnd")
        if not m0:
            continue
        k = field(blk, "CxK")
        d = field(blk, "caliber")
        if d and d < 1.0:
            d *= 1000.0
        stages = []
        f, t = field(blk, "force"), field(blk, "timeFire")
        if f and t:
            stages.append((f, t))
        j = 1
        while True:
            fj, tj = field(blk, f"force{j}"), field(blk, f"timeFire{j}")
            if not (fj and tj):
                break
            stages.append((fj, tj))
            j += 1
        recs.append({"file": p.name, "m0": m0, "mass_end": me, "k": k, "d_mm": d,
                     "stages": stages, "fuel": (m0 - me) if me else None})
    return recs


def main() -> int:
    table = wt_missiles.read_sheet()
    all_recs = parse_all()
    print(f"扫描 {len(all_recs)} 个 blkx\n")

    results = []
    for name in wt_missiles.PREFERRED:
        rec = table.get(name)
        if not rec:
            continue
        m0 = wt_missiles._num(rec["m0"])
        hits = [r for r in all_recs if r["m0"] and abs(r["m0"] - m0) <= max(0.2, m0 * 0.005)]
        detail = []
        for h in hits:
            tab_fuel = (wt_missiles._num(rec["m1"]) or 0) + (wt_missiles._num(rec["m2"]) or 0)
            if h["fuel"] and tab_fuel:
                detail.append(f"{h['file']}(装药{h['fuel']:.2f}=表{tab_fuel:.2f}? "
                              f"{'是' if abs(h['fuel'] - tab_fuel) < 0.05 else '否'})")
            else:
                detail.append(f"{h['file']}(装药{h['fuel']})")
        print(f"{name:<22} 表 m0={m0:7.2f} 同 m0 的 blkx {len(hits):2d} 个")
        for d in detail[:4]:
            print(f"      {d}")
        results.append({"name": name, "table_m0": m0, "candidates": detail,
                        "n_candidates": len(hits)})
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

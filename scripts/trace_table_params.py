"""反查：WT.xlsx 表里每个弹的参数（m0 / m1 / m2 / F1 / t1 / F2 / t2 / CxK / 口径）
是否能在当前 rocketguns 目录的某个 blkx 里找到对应来源。

表里的"单级"参数（mass/massEnd/force/timeFire）与 blkx 一致时，说明表的数值确实源自 blkx；
表里把总装药拆成 m1 + m2 时，只有该弹的 blkx 是两级结构（force1/force2）才可能直接对应。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import wt_missiles  # noqa: E402

ROCKETS = Path(r"E:\WT\War-Thunder-Datamine\aces.vromfs.bin_u\gamedata\weapons\rocketguns")
NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def field(text: str, key: str):
    m = re.search(rf'"{key}"\s*:\s*({NUM})', text)
    return float(m.group(1)) if m else None


def rocket_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    i = text.find('"rocket"')
    return text[i:] if i >= 0 else text


def read_all():
    out = {}
    for p in sorted(ROCKETS.glob("*.blkx")):
        blk = rocket_block(p)
        m0, me = field(blk, "mass"), field(blk, "massEnd")
        if not m0:
            continue
        k = field(blk, "CxK")
        d = field(blk, "caliber")
        if d and d < 1.0:
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
        out[p.name] = {"m0": m0, "mass_end": me, "k": k, "d_mm": d, "stages": stages}
    return out


def close(a, b, tol=0.02):
    if a is None or b is None:
        return abs((a or 0) - (b or 0)) < 1e-6
    return abs(a - b) <= max(tol, abs(b) * 2e-3)


def main() -> int:
    table = wt_missiles.read_sheet()
    allblkx = read_all()
    print(f"rocketguns 内可解析 blkx：{len(allblkx)} 个\n")

    wanted = wt_missiles.PREFERRED
    print(f"{'表内列名':<22} {'表 m0':>8} {'表总装药':>9} {'表 CxK':>7} {'表 d':>6} | 匹配的 blkx 文件（m0/massEnd 一致 && CxK 一致）")
    report = []
    for name in wanted:
        rec = table.get(name)
        if not rec:
            continue
        m0 = wt_missiles._num(rec["m0"])
        m1 = wt_missiles._num(rec["m1"]) or 0.0
        m2 = wt_missiles._num(rec["m2"]) or 0.0
        fuel = m1 + m2
        k = wt_missiles._num(rec["k"])
        d = wt_missiles._num(rec["d_mm"])
        hits = []
        for fn, b in allblkx.items():
            if close(b["m0"], m0) and close(b["d_mm"], d) and close(b["k"], k):
                stage_fuel = (b["m0"] - b["mass_end"]) if b["mass_end"] else None
                hits.append((fn, b, stage_fuel))
        shown = ", ".join(f"{fn}(装药{sf:.2f})" if sf else fn for fn, b, sf in hits[:3]) or "— 无精确匹配"
        print(f"{name:<22} {m0:8.2f} {fuel:9.2f} {k:7.3f} {d:6.1f} | {shown}")
        report.append({"name": name, "table": {"m0": m0, "fuel": fuel, "k": k, "d_mm": d},
                       "blkx_matches": [{"file": fn, "m0": b["m0"], "mass_end": b["mass_end"],
                                         "stages": b["stages"]} for fn, b, _ in hits]})
    out = Path(__file__).resolve().parents[1] / "results" / "table_param_provenance.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

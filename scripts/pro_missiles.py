# -*- coding: utf-8 -*-
"""11 弹原生（Pro）仿真：每型用它自己的 (ΔV, BC) 跑一次全程积分，输出命中时间与终端量。

    $env:WT_NATIVE_PKG = "E:\\WT\\wt-missile-backend-runtime-1.0.1"
    python scripts\\pro_missiles.py                 # 默认 50 km 迎头 / 10 km / 300 对 -300
    python scripts\\pro_missiles.py --range 30000 --jobs 8
    python scripts\\pro_missiles.py --out results/pro_missiles_30km.json

口径（AERO_PLAN §20/§21）：
  * 每型按**自己的** (ΔV, BC) 跑 ⇒ 推力乘数 = ΔV/ΔV_blk、CxK 乘数 = m_dry/(BC·S_ref·CxK_blk)，都是解析值；
  * 原生 profile 取包内；包内没有的（Derby / R-Darter）用我们的权威 blkx **注入**，
    结果里会记 `resource="INJECTED ..."`；
  * `dv_measured` = 燃尽时刻速度 − 初速（**实测**速度增量，扣掉阻力/重力损失），
    与 `dv`（真空等效增速）不是同一个量，表里都列出来。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import missile_metrics as mm                            # noqa: E402
from missile_sim import pro                             # noqa: E402
from missile_sim.config import apply_standard, load_config, s_ref  # noqa: E402

POINTS = ROOT / "results" / "missile_points.json"


def native_name_of(blkx_file: str) -> str:
    f = str(blkx_file)
    for suffix in (".blkx", ".blk"):
        if f.endswith(suffix):
            f = f[: -len(suffix)]
    return f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="11 弹原生仿真（Pro）")
    ap.add_argument("--range", type=float, default=50000.0, help="初始水平距离 [m]")
    ap.add_argument("--alt", type=float, default=10000.0, help="双方高度 [m]")
    ap.add_argument("--vm0", type=float, default=300.0)
    ap.add_argument("--vt", type=float, default=-300.0)
    ap.add_argument("--dt", type=float, default=pro.DT_DEFAULT)
    ap.add_argument("--duration", type=float, default=150.0)
    ap.add_argument("--observation", choices=["ideal", "locked"], default="ideal")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--standard", default="PL-12",
                    help="基准弹（决定未列出的默认几何/引信回退；逐弹仍用自己的参数）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    points = json.loads(POINTS.read_text(encoding="utf-8"))
    rows_in = points["missiles"] if isinstance(points, dict) and "missiles" in points else points
    print(f"11 弹池：{len(rows_in)} 型；工况 R0={args.range:.0f} m, alt={args.alt:.0f} m, "
          f"vm0={args.vm0:.0f}, vt={args.vt:.0f}, dt={args.dt:g} s, 观测={args.observation}")

    base_cfg = load_config()
    base_cfg.standard.name = args.standard
    apply_standard(base_cfg)
    sr = s_ref(base_cfg)

    cases, meta = [], []
    for m in rows_in:
        name = native_name_of(m["file"])
        cfg = load_config()
        cfg.standard.name = m["label"]
        try:
            apply_standard(cfg)
            prof = cfg.profile
        except Exception:                               # noqa: BLE001
            prof = base_cfg.profile
        ts, cs = pro.scales_for(m["dv"], m["bc"], prof, sr)
        cases.append(pro.NativeCase(
            missile=name, range_m=args.range, alt_m=args.alt, vm0=args.vm0, vt=args.vt,
            dt=args.dt, duration_s=args.duration, observation_mode=args.observation,
            thrust_scale=ts, cx_scale=cs))
        meta.append({"name": m["name"], "label": m["label"], "file": m["file"],
                     "dv": m["dv"], "bc": m["bc"], "dry": m.get("dry"),
                     "thrust_scale": ts, "cx_scale": cs})

    t0 = time.perf_counter()
    with pro.ProRunner(jobs=args.jobs) as runner:
        results = runner.run_many(cases)
        stats = dict(runner.stats)
    wall = time.perf_counter() - t0

    rows = []
    print()
    print(f"{'弹':<12}{'ΔV':>7}{'BC':>7}{'t_hit':>8}{'末速':>7}{'最大高':>8}"
          f"{'实测ΔV':>8}{'损失%':>7}{'全程':>7}  事件/来源")
    for m, r in zip(meta, results):
        loss = (1 - r.dv_measured / m["dv"]) * 100 if r.ok and m["dv"] else float("nan")
        rows.append({**m, **r.to_dict(), "loss_pct": loss})
        print(f"{m['label']:<12}{m['dv']:7.0f}{m['bc']:7.0f}"
              f"{(r.t_hit if r.hit else float('nan')):8.3f}"
              f"{r.v_impact:7.1f}{r.max_alt_m:8.0f}{r.dv_measured:8.1f}{loss:7.2f}"
              f"{r.t_end:7.2f}  {r.event}"
              f"{'' if r.resource == 'native' else '  [' + r.resource + ']'}")
    ok = [r for r in rows if r["ok"]]
    hit = [r for r in ok if r["hit"]]
    print()
    print(f"成功 {len(ok)}/{len(rows)}，命中 {len(hit)}/{len(ok)}；"
          f"t_hit {min((r['t_hit'] for r in hit), default=float('nan')):.2f}"
          f"~{max((r['t_hit'] for r in hit), default=float('nan')):.2f} s；"
          f"末速 {min((r['v_impact'] for r in hit), default=float('nan')):.0f}"
          f"~{max((r['v_impact'] for r in hit), default=float('nan')):.0f} m/s")
    print(f"原生运行 {stats['native']} 次（缓存命中 {stats['cache']}），用时 {wall:.1f} s")

    tag = args.tag or f"{args.range / 1000:.0f}km"
    out = Path(args.out) if args.out else ROOT / "results" / f"pro_missiles_{tag}.json"
    doc = {
        "schema": 1,
        "note": "11 弹原生（Pro）单工况结果；每型用自己的 (ΔV,BC) 解析出推力/CxK 乘数",
        "scenario": {"range_m": args.range, "alt_m": args.alt, "vm0": args.vm0,
                     "vt": args.vt, "dt_s": args.dt, "duration_s": args.duration,
                     "observation_mode": args.observation},
        "runtime": {"version": pro.VERSION_28, "elf_sha256": pro.ELF_SHA256_28,
                    "pkg": str(pro.resolve_pkg()),
                    "n_native": stats["native"], "n_cache": stats["cache"],
                    "wall_time_s": round(wall, 2)},
        "missiles": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

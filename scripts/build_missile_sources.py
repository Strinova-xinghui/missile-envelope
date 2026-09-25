"""重建三套弹值数据（口径固定为最新版 = 工作区 blkx，权威公式见 missile_metrics.py）。

产物：
  results/missile_points.json       最新版（工作区 blkx）弹值 —— 出图默认口径
  results/blkx_missiles.json        同上（历史文件名，供 missile_sources.load_source("blkx")）
  results/base257_missiles.json     2.57.1.132 基线值（仅作"参考图那一版"对照）
  results/missile_sources_all.json  三套口径合并快照 + 拟合结果
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import missile_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
BASE_TAG = "2.57.1.132"


def fit(rows, key_dv="dv", key_bc="bc"):
    xs = [r[key_dv] for r in rows]
    ys = [r[key_bc] for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx
    intercept = my - slope * mx
    return {"slope": slope, "intercept": intercept, "r2": (sxy ** 2) / (sxx * syy)}


def main() -> int:
    latest = missile_metrics.current_missiles(missile_metrics.WORK)
    versions = missile_metrics.all_versions([missile_metrics.WORK, BASE_TAG])
    base = []
    for short, _f, key in missile_metrics.MISSILE_FILES:
        got = versions.get(short, {}).get(BASE_TAG)
        if not got:
            continue
        base.append({"name": key, "label": short, "dv": got["dv"], "bc": got["bc"],
                     "k": got["CxK"], "d_mm": got["caliber_mm"],
                     "source": f"blkx {BASE_TAG}（权威口径）"})

    print(f"最新版（{missile_metrics.WORK}）：{len(latest)} 型；{BASE_TAG} 基线：{len(base)} 型")
    print(f"最新版拟合：BC = {fit(latest)['slope']:.4f}·ΔV + {fit(latest)['intercept']:.1f} "
          f"(R² = {fit(latest)['r2']:.3f})")
    print(f"基线拟合：  BC = {fit(base)['slope']:.4f}·ΔV + {fit(base)['intercept']:.1f} "
          f"(R² = {fit(base)['r2']:.3f})")

    RES.mkdir(parents=True, exist_ok=True)
    for fname, rows, src in (
        ("missile_points.json", latest, f"War-Thunder-Datamine {missile_metrics.WORK} rocketguns"),
        ("blkx_missiles.json", latest, f"War-Thunder-Datamine {missile_metrics.WORK} rocketguns"),
        ("base257_missiles.json", base, f"War-Thunder-Datamine tag {BASE_TAG}"),
    ):
        (RES / fname).write_text(
            json.dumps({"source": src, "missiles": rows, "fit": fit(rows)},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  写出 {fname}（{len(rows)} 型）")

    (RES / "missile_sources_all.json").write_text(
        json.dumps({"latest_tag": missile_metrics.WORK, "base_tag": BASE_TAG,
                    "latest": latest, "base": base,
                    "fit_latest": fit(latest), "fit_base": fit(base),
                    "formula": "自动化分析/skills/wt-aam-analysis/scripts/plot_version_compare.py :: metrics()"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("  写出 missile_sources_all.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""对照表：WT.xlsx 的 AAM (ARH) 权威值 vs 原图像素读出的弹点，并给出映射方案。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
WT = ROOT / "results" / "wt_table_aam_arh.json"
REF = ROOT / "results" / "reference_points.json"

# 图中标注 → WT.xlsx 列名（同名或有版本后缀的取 2.58.0.27 / (new) 优先）
NAME_MAP = {
    "AAM-4": "AAM-4",
    "120A": "AIM-120A (2.58.0.27)",
    "120C": "AIM-120C-5 (2.58.0.27)",
    "120D": "AIM-120D (2.58.0.27)",
    "MICA": "MICA EM (new)",
    "PL-12": "PL-12",
    "PL-12A": "PL-12A",
    "R-Darter": "R-Darter",
    "Derby": "Derby",
    "R-77": "R-77",
    "R-77-1": "R-77-1",
}

# 原图 11 个点（像素解出）与其标签
FIG_POINTS = [
    ("AAM-4", 834.9, 3687.8), ("120A", 829.8, 3616.2), ("120C", 904.2, 3630.3),
    ("120D", 898.3, 3659.3), ("MICA", 829.6, 3108.0), ("PL-12", 938.4, 2612.5),
    ("PL-12A", 992.9, 3266.4), ("R-Darter", 920.1, 2674.1), ("Derby", 938.2, 3104.3),
    ("R-77", 816.4, 2581.2), ("R-77-1", 970.2, 2613.9),
]


def main() -> int:
    wt = json.loads(WT.read_text(encoding="utf-8"))["rows"]
    by_name = {}
    for r in wt:
        by_name.setdefault(r["name"], r)

    print(f"{'弹':<9} {'WT表 ΔV':>9} {'WT表 BC':>9} | {'原图 ΔV':>8} {'原图 BC':>8} | "
          f"{'ΔΔV':>7} {'ΔBC':>8}")
    rows = []
    for label, fig_dv, fig_bc in FIG_POINTS:
        col_name = NAME_MAP.get(label)
        rec = by_name.get(col_name) if col_name else None
        comp = (rec or {}).get("computed") or {}
        wt_dv = comp.get("dv_total")
        wt_bc = comp.get("bc")
        d_dv = None if wt_dv is None else fig_dv - wt_dv
        d_bc = None if wt_bc is None else fig_bc - wt_bc
        print(f"{label:<9} {wt_dv:9.1f} {wt_bc:9.1f} | {fig_dv:8.1f} {fig_bc:8.1f} | "
              f"{d_dv:7.1f} {d_bc:8.1f}")
        rows.append({"label": label, "wt_col": col_name, "wt_dv": wt_dv, "wt_bc": wt_bc,
                     "fig_dv": fig_dv, "fig_bc": fig_bc, "d_dv": d_dv, "d_bc": d_bc,
                     "m0": (rec or {}).get("m0"), "m1": (rec or {}).get("m1"),
                     "m2": (rec or {}).get("m2"), "k": (rec or {}).get("k"),
                     "d_mm": (rec or {}).get("d_mm"),
                     "f1": (rec or {}).get("f1"), "t1": (rec or {}).get("t1"),
                     "f2": (rec or {}).get("f2"), "t2": (rec or {}).get("t2")})

    # 拟合对照
    def fit(pts, ix, iy):
        xs = [p[ix] for p in pts]
        ys = [p[iy] for p in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        syy = sum((y - my) ** 2 for y in ys)
        k = sxy / sxx
        b = my - k * mx
        return k, b, (sxy ** 2) / (sxx * syy)

    wt_pts = [(r["wt_dv"], r["wt_bc"]) for r in rows if r["wt_dv"] and r["wt_bc"]]
    fig_pts = [(r["fig_dv"], r["fig_bc"]) for r in rows]
    k1, b1, r21 = fit(wt_pts, 0, 1)
    k2, b2, r22 = fit(fig_pts, 0, 1)
    print(f"\n拟合（WT 表值） y = {k1:.4f}x + {b1:.1f}, R² = {r21:.3f}")
    print(f"拟合（原图读出）y = {k2:.4f}x + {b2:.1f}, R² = {r22:.3f}")

    out = ROOT / "results" / "wt_vs_figure.json"
    out.write_text(json.dumps({"mapping": NAME_MAP, "rows": rows,
                               "fit_wt": [k1, b1, r21], "fit_fig": [k2, b2, r22]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

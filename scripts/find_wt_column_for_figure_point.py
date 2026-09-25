"""在 WT.xlsx 的 AAM (ARH) 全表里查找与参考图某点最接近的列（用于判定原图点来自哪一列）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import wt_missiles  # noqa: E402

# 参考图像素读出的点（标签, ΔV, BC）
TARGETS = [
    ("R-77(图上)", 816.4, 2581.2),
    ("R-77-1(图上)", 970.2, 2613.9),
    ("AAM-4(图上)", 834.9, 3687.8),
    ("Derby(图上)", 938.2, 3104.3),
]


def main() -> int:
    rows = wt_missiles.load_all_columns()
    print(f"表内可用列 {len(rows)} 个\n")
    for label, dv, bc in TARGETS:
        scored = sorted(rows, key=lambda r: ((r["dv"] - dv) / 30.0) ** 2 + ((r["bc"] - bc) / 150.0) ** 2)
        print(f"{label}: ΔV={dv:.1f} BC={bc:.1f} → 最接近的三列")
        for r in scored[:3]:
            print(f"    {r['name']:<28} {r['col']:>3} ΔV={r['dv']:7.1f} (Δ{r['dv'] - dv:+7.1f}) "
                  f"BC={r['bc']:7.1f} (Δ{r['bc'] - bc:+7.1f})")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

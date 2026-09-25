"""从参考图（results/reference_fig.png）中自动提取弹点坐标。

原理：图中弹点是暗红色实心圆（RGB≈C00000/8B0000），背景白、网格浅灰、文字同色但笔画细。
做法：扫描像素，取"红点色"像素做连通域标记；按面积与圆度过滤掉文字笔画；用坐标轴框线定标。

输出：results/reference_points.json（含像素→数据坐标映射与每个点）。
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "results" / "reference_fig.png"
OUT = ROOT / "results" / "reference_points.json"


def load_pixels(path: Path):
    from PIL import Image

    im = Image.open(path).convert("RGB")
    w, h = im.size
    return list(im.getdata()), w, h


def is_red(px):
    r, g, b = px
    return r > 110 and g < 90 and b < 90 and (r - g) > 60 and (r - b) > 60


def is_dark_blue(px):
    r, g, b = px
    return b > 90 and (b - r) > 30 and (b - g) > 10 and r < 130


def components(pixels, w, h, pred, min_area=25):
    seen = bytearray(w * h)
    out = []
    for idx in range(w * h):
        if seen[idx] or not pred(pixels[idx]):
            continue
        q = deque([idx])
        seen[idx] = 1
        xs, ys, n = 0, 0, 0
        minx = maxx = idx % w
        miny = maxy = idx // w
        while q:
            cur = q.popleft()
            cx, cy = cur % w, cur // w
            xs += cx
            ys += cy
            n += 1
            minx, maxx = min(minx, cx), max(maxx, cx)
            miny, maxy = min(miny, cy), max(maxy, cy)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < w and 0 <= ny < h:
                    ni = ny * w + nx
                    if not seen[ni] and pred(pixels[ni]):
                        seen[ni] = 1
                        q.append(ni)
        if n >= min_area:
            out.append({"cx": xs / n, "cy": ys / n, "n": n, "bbox": (minx, miny, maxx, maxy)})
    return out


def find_axis_frame(pixels, w, h):
    """找坐标轴框（深灰细线）。返回 (x_left, x_right, y_top, y_bottom) 的像素位置。"""
    def darkish(px):
        r, g, b = px
        return abs(r - g) < 12 and abs(g - b) < 12 and r < 150

    # 竖线：某一列在绘图区高度内大量连续暗像素
    col_score = [sum(1 for y in range(h) if darkish(pixels[y * w + x])) for x in range(w)]
    row_score = [sum(1 for x in range(w) if darkish(pixels[y * w + x])) for y in range(h)]
    cols = [x for x, s in enumerate(col_score) if s > h * 0.45]
    rows = [y for y, s in enumerate(row_score) if s > w * 0.45]
    if not cols or not rows:
        raise SystemExit("未能识别坐标轴框线")
    return min(cols), max(cols), min(rows), max(rows)


def main() -> int:
    if not IMG.exists():
        raise SystemExit(f"缺少参考图 {IMG}")
    pixels, w, h = load_pixels(IMG)
    print(f"图像 {w}×{h}")

    # 先定位坐标轴框：取最外圈的框线
    x0, x1, y0, y1 = find_axis_frame(pixels, w, h)
    print(f"坐标轴框像素：x {x0}..{x1}, y {y0}..{y1}")

    reds = components(pixels, w, h, is_red, min_area=40)
    # 圆点 vs 文字：圆点周长小、外接框近正方形且填充率高（π/4≈0.785），文字笔画细长且填充率低
    dots = []
    for c in reds:
        bx0, by0, bx1, by1 = c["bbox"]
        bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
        fill = c["n"] / max(1, bw * bh)
        is_square = 0.72 <= bw / bh <= 1.38
        is_dot_size = 9 <= bw <= 16 and 9 <= bh <= 16
        # 只保留绘图区内的（排除标题文字的个别像素块）
        inside = bx0 >= x0 - 2 and bx1 <= x1 + 2 and by0 >= y0 - 2 and by1 <= y1 + 2
        if is_square and is_dot_size and fill >= 0.62 and inside:
            dots.append(c)
    print(f"候选圆点 {len(dots)} 个（红像素连通域共 {len(reds)} 个）")

    # 参考图坐标映射（图中标注的轴范围）：ΔV 810~1110、BC 2500~3800
    DV_LO, DV_HI = 810.0, 1110.0
    BC_LO, BC_HI = 2500.0, 3800.0
    pts = []
    for c in dots:
        dv = DV_LO + (c["cx"] - x0) / (x1 - x0) * (DV_HI - DV_LO)
        bc = BC_HI - (c["cy"] - y0) / (y1 - y0) * (BC_HI - BC_LO)
        pts.append({"px": round(c["cx"], 2), "py": round(c["cy"], 2), "area": c["n"],
                    "dv": round(dv, 1), "bc": round(bc, 1)})
    pts.sort(key=lambda p: p["dv"])
    for p in pts:
        print(f"  px=({p['px']:7.2f},{p['py']:6.2f}) area={p['area']:4d} -> ΔV={p['dv']:7.1f}  BC={p['bc']:7.1f}")
    pts.sort(key=lambda p: p["dv"])
    for p in pts:
        print(f"  px=({p['px']:7.2f},{p['py']:6.2f}) area={p['area']:4d} -> ΔV={p['dv']:7.1f}  BC={p['bc']:7.1f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": IMG.name,
        "image_size": [w, h],
        "axis_px": {"x0": x0, "x1": x1, "y0": y0, "y1": y1},
        "axis_range": {"dv": [DV_LO, DV_HI], "bc": [BC_LO, BC_HI]},
        "points": pts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

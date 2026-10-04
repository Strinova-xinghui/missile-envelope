#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把参考图 `fig2_turn_energy.svg` 的等 `n*` 曲线**矢量解析**进仓库（一次性工具）。

背景：2026-10-04 用户拍板纵轴改用 `ginv = 1/γ`。要证明"等 `n*` 线换轴后是**过原点的直线**"，
最硬的证据是**参考图本身**（`E:\\War Thunder\\_recon\\fig2_turn_energy.svg`）—— 它是矢量的，
14 条 `<line>` 是网格线/轴线、7 条虚线 `<polyline>` 就是等 `n*` 线。

⚠ 这个脚本是**上游工具**：判据（`tests/test_bg_reference_curves.py`）只读它写出来的
`results/bg_ref_curves.json`，**绝不**在测试期去碰 `E:\\War Thunder\\` 下的任何文件
（那台机器之外的文件不该决定本仓库的判据）。曲线分不开时**宁可写 `unresolved`**，
也不许手写坐标冒充 —— 手抄的数字没有任何证据链。

标定从 SVG 自己推：两条 `#333` 轴线给出绘图区（x 100→770、y 600→70），
再按生成脚本 `_recon/make_fig2_turn_energy.py` 写明的量程 `β ∈ [2450, 3800]`、
`γ ∈ [45, 100]` 做线性映射；算完与记录在案的老标定式对一遍（相对差 ≤ 1e-3）。

用法：
    python scripts\\extract_bg_reference_curves.py                     # 默认路径
    python scripts\\extract_bg_reference_curves.py --svg <path> --out results\\bg_ref_curves.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SVG = Path(r"E:\War Thunder\_recon\fig2_turn_energy.svg")
DEFAULT_OUT = Path("results/bg_ref_curves.json")

#: 生成脚本 `make_fig2_turn_energy.py` 里写死的量程（绘图区四边对应的物理值）。
BETA_LIM = (2450.0, 3800.0)
GAMMA_LIM = (45.0, 100.0)
#: 记录在案的旧标定式（`px → 物理值`），用来交叉核对本脚本从盒子推出来的标定。
KNOWN_BETA = (2500.0, 124.8, 2.01417)          # β = β0 + (px − px0) · k
KNOWN_GAMMA = (50.0, 551.8, 0.103734)          # γ = γ0 + (py0 − py) · k
#: 期望的等 `n*` 层（`LEGEND`）；参考图上只标了 5 个，14/15 按几何次序补。
EXPECTED_LEVELS = (14, 15, 16, 17, 18, 19, 20)


def _attrs(raw: str) -> dict:
    return dict(re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', raw))


def _nums(text: str) -> list:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text or "")]


def parse_svg(text: str) -> dict:
    """只认几何，不做任何"理解"：列出轴线盒、网格线、虚线折线、文字标签。"""
    box, grid = [], []
    for m in re.finditer(r"<line\b([^>]*?)/?>", text, re.S):
        at = _attrs(m.group(1))
        x1, y1, x2, y2 = (_nums(at.get(k, "")) for k in ("x1", "y1", "x2", "y2"))
        x1, y1, x2, y2 = (v[0] if v else float("nan") for v in (x1, y1, x2, y2))
        rec = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "stroke": at.get("stroke", "")}
        if at.get("stroke", "").lower() in ("#333", "#333333"):
            box.append(rec)
        else:
            grid.append(rec)
    polys = []
    for m in re.finditer(r"<polyline\b([^>]*?)/?>", text, re.S):
        at = _attrs(m.group(1))
        flat = _nums(at.get("points", ""))
        pts = list(zip(flat[0::2], flat[1::2]))
        polys.append({"stroke": at.get("stroke", ""), "dash": at.get("stroke-dasharray", ""),
                      "n_points": len(pts), "points": pts})
    labels = []
    for m in re.finditer(r"<text\b([^>]*)>(.*?)</text>", text, re.S):
        at = _attrs(m.group(1))
        body = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        xs, ys = _nums(at.get("x", "")), _nums(at.get("y", ""))
        labels.append({"x": xs[0] if xs else float("nan"),
                       "y": ys[0] if ys else float("nan"),
                       "fill": at.get("fill", ""), "text": body})
    return {"box": box, "grid": grid, "polylines": polys, "texts": labels}


def calibration(parsed: dict) -> dict:
    """从轴线盒 + 记录在案的量程推线性标定，并与已知标定式交叉核对。"""
    vert = [l for l in parsed["box"] if abs(l["x1"] - l["x2"]) < 1e-6]
    horz = [l for l in parsed["box"] if abs(l["y1"] - l["y2"]) < 1e-6]
    if len(vert) != 1 or len(horz) != 1:
        raise SystemExit(f"轴线盒认不出来（竖 {len(vert)} 条 / 横 {len(horz)} 条）")
    # 竖轴线给 y 的范围，横轴线给 x 的范围（各自另一个方向是一个点）
    x_lo, x_hi = sorted((horz[0]["x1"], horz[0]["x2"]))
    y_lo, y_hi = sorted((vert[0]["y1"], vert[0]["y2"]))     # y 向下 ⇒ y_lo 是上边
    bx = (BETA_LIM[1] - BETA_LIM[0]) / (x_hi - x_lo)
    gy = (GAMMA_LIM[1] - GAMMA_LIM[0]) / (y_hi - y_lo)      # 向上为正 ⇒ 取负号在用的时候

    def beta_of(px: float) -> float:
        return BETA_LIM[0] + (px - x_lo) * bx

    def gamma_of(py: float) -> float:
        return GAMMA_LIM[1] - (py - y_lo) * gy

    def rel(a: float, b: float) -> float:
        return abs(a - b) / max(abs(b), 1e-9)

    drift = {}
    for key, known in (("beta", KNOWN_BETA), ("gamma", KNOWN_GAMMA)):
        k0, p0, k = known
        px = x_lo + (k0 - BETA_LIM[0]) / bx if key == "beta" else \
            y_lo + (GAMMA_LIM[1] - k0) / gy
        drift[key] = {"known_slope": k, "box_slope": bx if key == "beta" else gy,
                      "known_anchor_px": p0, "anchor_from_box": round(px, 4),
                      "rel_slope": round(rel(bx if key == "beta" else gy, k), 9),
                      "rel_anchor": round(rel(px, p0), 9)}
        if drift[key]["rel_slope"] > 1e-3 or drift[key]["rel_anchor"] > 3e-3:
            raise SystemExit(f"标定对不上记录值：{key} {drift[key]}")
    return {"box_px": {"x": [x_lo, x_hi], "y": [y_lo, y_hi]},
            "limits": {"beta": list(BETA_LIM), "gamma": list(GAMMA_LIM)},
            "beta": {"formula": "beta = %.4f + (px - %.4f) * %.9f" % (BETA_LIM[0], x_lo, bx),
                     "k": bx, "x0": x_lo, "b0": BETA_LIM[0]},
            "gamma": {"formula": "gamma = %.4f - (py - %.4f) * %.9f" % (GAMMA_LIM[1], y_lo, gy),
                      "k": gy, "y0": y_lo, "g_top": GAMMA_LIM[1]},
            "cross_check": drift}


def _fit_through_origin(betas, ginvs) -> dict:
    """过原点最小二乘 `ginv = m·β`：`m = Σ(β·g)/Σ(β²)`，残差按 ginv 幅值归一。"""
    s_bb = sum(b * b for b in betas)
    s_bg = sum(b * g for b, g in zip(betas, ginvs))
    m = s_bg / s_bb
    resid = [g - m * b for b, g in zip(betas, ginvs)]
    span = max(ginvs) - min(ginvs)
    return {"m": m, "intercept_fixed_at": 0.0,
            "max_abs_resid": max(abs(r) for r in resid),
            "rel_resid": max(abs(r) for r in resid) / span if span else float("nan"),
            "rms_resid": math.sqrt(sum(r * r for r in resid) / len(resid))}


def extract(parsed: dict, cal: dict) -> list:
    """7 条折线 → (β, γ, ginv) + 过原点拟合；层号按标签 + 几何次序定，并互相校验。"""
    def beta_of(px):
        return cal["beta"]["b0"] + (px - cal["beta"]["x0"]) * cal["beta"]["k"]

    def gamma_of(py):
        return cal["gamma"]["g_top"] - (py - cal["gamma"]["y0"]) * cal["gamma"]["k"]

    polylines = [p for p in parsed["polylines"] if p["dash"]]
    if len(polylines) != 7:
        raise SystemExit(f"虚线折线应为 7 条，实测 {len(polylines)} 条 ⇒ 分不开，别硬凑")

    curves = []
    for i, p in enumerate(polylines):
        betas = [beta_of(px) for px, _py in p["points"]]
        gammas = [gamma_of(py) for _px, py in p["points"]]
        ginvs = [1.0 / g for g in gammas]
        fit = _fit_through_origin(betas, ginvs)
        curves.append({"svg_index": i, "stroke": p["stroke"], "dash": p["dash"],
                       "n_points": p["n_points"], "entry_px": list(p["points"][0]),
                       "beta": betas, "gamma": gammas, "ginv": ginvs, "fit": fit})

    # 标签：文本形如 "n*=18"；位置贴在曲线进图处（x 靠左）
    label_re = re.compile(r"n\s*\*?\s*=\s*(\d+(?:\.\d+)?)")
    tagged = []
    for t in parsed["texts"]:
        m = label_re.search(t["text"] or "")
        if not m:
            continue
        y, x = t["y"], t["x"]
        # 找"进图点最接近该标签 y"的那条曲线
        best, best_d = None, None
        for c in curves:
            px, py = c["entry_px"]
            d = abs(py - y) + 0.02 * abs(px - x)
            if best is None or d < best_d:
                best, best_d = c, d
        tagged.append({"text": t["text"], "n_star": float(m.group(1)),
                       "svg_index": best["svg_index"], "dy_px": round(y - best["entry_px"][1], 3)})
    for c in curves:
        c["label"] = next((t["n_star"] for t in tagged if t["svg_index"] == c["svg_index"]), None)

    # 几何次序：`ginv = m·β` 的斜率随 n* 单调增（n* 越大 ⇒ 同一 β 下转向能力越强）
    order = sorted(curves, key=lambda c: c["fit"]["m"], reverse=True)
    labelled = [c for c in order if c["label"] is not None]
    if len(labelled) != 5:
        raise SystemExit(f"应认出 5 个标签，实测 {len(labelled)} 个 ⇒ 分不开，别硬凑")
    if [c["label"] for c in labelled] != sorted((c["label"] for c in labelled), reverse=True):
        raise SystemExit("标签值与几何次序矛盾（斜率大的反而 n* 小）⇒ 不硬凑，请人工看")
    free = [n for n in EXPECTED_LEVELS if n not in {c["label"] for c in labelled}]
    if len(free) != 2:
        raise SystemExit(f"未标注的层应恰好 2 个（14/15），算出 {free}")
    # ⚠ 次序别搞反：`order` 是**斜率从大到小**，对应的 n* 也是从大到小 ⇒ 先取最大的那个。
    #   反过来会把 15 号曲线标成 14（实测踩过：`m/n*²` 从 1.7027e-08 变成 1.95e-08/1.48e-08，
    #   一眼就看出来不对 —— 这个不变式在 main() 里会打印出来）。
    for c in order:
        if c["label"] is None:
            c["label"] = float(free.pop())
            c["label_source"] = "geometry"
        else:
            c["label_source"] = "svg_text"

    out = []
    for c in sorted(order, key=lambda c: c["label"]):
        out.append({
            "n_star": c["label"], "label_source": c["label_source"],
            "svg_index": c["svg_index"], "n_points": c["n_points"],
            "beta_range": [min(c["beta"]), max(c["beta"])],
            "gamma_range": [min(c["gamma"]), max(c["gamma"])],
            "ginv_range": [min(c["ginv"]), max(c["ginv"])],
            "fit": {k: (round(v, 12) if isinstance(v, float) else v)
                    for k, v in c["fit"].items()},
            "points": [[round(b, 2), round(g, 4), round(gi, 9)]
                       for b, g, gi in zip(c["beta"], c["gamma"], c["ginv"])],
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="参考图等 n* 曲线 → results/bg_ref_curves.json")
    ap.add_argument("--svg", default=str(DEFAULT_SVG))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    src = Path(args.svg)
    if not src.is_file():
        print(f"找不到参考图：{src}", file=sys.stderr)
        return 2
    raw = src.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    parsed = parse_svg(text)
    cal = calibration(parsed)
    curves = extract(parsed, cal)

    gen = src.with_name("make_fig2_turn_energy.py")
    payload = {
        "schema": 1,
        "kind": "bg-reference-curves",
        "note": ("参考图等 n* 线的矢量重解析。纵轴量是 ginv = 1/gamma [m²/kg]；"
                 "曲线在 (β, ginv) 平面上是过原点的直线（过原点拟合见 fit）。"
                 "本文件是入库快照，判据只读它，不去读源 SVG。"
                 "⚠ 这里不许出现 markdown 星号（判据会扫产物里的星号对），加粗请用「」。"),
        "source": {"path": str(src), "bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest(),
                   "generator": (str(gen) if gen.is_file() else ""),
                   "generator_sha256": (hashlib.sha256(gen.read_bytes()).hexdigest()
                                        if gen.is_file() else "")},
        "extracted_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "calibration": cal,
        "levels": [c["n_star"] for c in curves],
        "curves": curves,
        "counts": {"n_curves": len(curves),
                   "n_points": sum(c["n_points"] for c in curves),
                   "n_lines": len(parsed["grid"]) + len(parsed["box"]),
                   "n_texts": len(parsed["texts"])},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # ⚠ `results/*.json` 的老习惯是 CRLF（Windows 上 `write_text()` 自己翻），这里显式给，
    #   免得新文件成为全仓唯一的 LF JSON。
    io.open(out, "w", encoding="utf-8", newline="\r\n").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    print("源：%s（%d 字节，sha256 %s…）" % (src, len(raw), payload["source"]["sha256"][:12]))
    print("标定：%s ／ %s" % (cal["beta"]["formula"], cal["gamma"]["formula"]))
    print("与记录在案的标定式相对差（斜率/锚点）：β %.2e/%.2e，γ %.2e/%.2e"
          % (cal["cross_check"]["beta"]["rel_slope"], cal["cross_check"]["beta"]["rel_anchor"],
             cal["cross_check"]["gamma"]["rel_slope"], cal["cross_check"]["gamma"]["rel_anchor"]))
    print("绘图区 px：x %s、y %s（y 向下）" % (cal["box_px"]["x"], cal["box_px"]["y"]))
    print("层 | 来源   | 点数 | ginv 过原点拟合 m         | 相对残差")
    for c in curves:
        print("%2d | %-6s | %4d | %.9e | %.3e"
              % (c["n_star"], c["label_source"], c["n_points"], c["fit"]["m"],
                 c["fit"]["rel_resid"]))
    ms = [c["fit"]["m"] for c in curves]
    print("m 单调递增（随 n*）：%s" % all(b > a for a, b in zip(ms, ms[1:])))
    print("m ∝ n*² 检验：%s" % [
        round(m / (c["n_star"] ** 2), 12) for m, c in zip(ms, curves)])
    print("写出：%s（%d 字节）" % (out, out.stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

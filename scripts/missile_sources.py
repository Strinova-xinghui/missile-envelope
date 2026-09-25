"""口径加载：给交叉图与工作流提供统一的弹值数据。

默认口径 = **最新版**（工作区 blkx = 实机 2.59.0.11），公式见 missile_metrics.py。
另留两个对照口径：`base257`（参考图那一版）与 `figure`（参考图像素读出的点）。

    latest   results/missile_points.json     ← 默认
    base257  results/base257_missiles.json
    figure   results/reference_points.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"

PATHS = {
    "latest": (RES / "missile_points.json", "最新版（工作区 blkx）"),
    "base257": (RES / "base257_missiles.json", "2.57.1.132 基线"),
    "figure": (RES / "reference_points.json", "参考图像素读出"),
}

# 图上短标签
SHORT_BY_LABEL = {
    "120A": "120A", "120C": "120C", "120D": "120D", "AAM-4": "AAM-4",
    "MICA": "MICA", "PL-12": "PL-12", "PL-12A": "PL-12A",
    "R-Darter": "R-Darter", "Derby": "Derby", "R-77": "R-77", "R-77-1": "R-77-1",
}
SHORT_BY_NAME = {
    "AIM-120A/B": "120A", "AIM-120C-5/7": "120C", "AIM-120D": "120D",
    "AAM-4": "AAM-4", "MICA-EM": "MICA", "PL-12": "PL-12", "PL-12A": "PL-12A",
    "R-Darter": "R-Darter", "Derby": "Derby", "R-77/RVV-AE": "R-77",
    "R-77-1/RVV-SD": "R-77-1",
}


def available() -> list:
    return [k for k, (p, _) in PATHS.items() if p.exists()]


def load_source(kind: str = "latest") -> list:
    """返回 [{name, label, dv, bc, source}]。"""
    if kind not in PATHS:
        raise SystemExit(f"未知口径：{kind}（可选 {list(PATHS)}）")
    path, desc = PATHS[kind]
    if not path.exists():
        raise FileNotFoundError(f"缺少 {path}，请先运行 scripts\\build_missile_sources.py")
    data = json.loads(path.read_text(encoding="utf-8"))
    if kind == "figure":
        out = []
        for p in data.get("points", []):
            label = p.get("label")
            if not label:
                continue
            out.append({"name": label, "label": label, "dv": float(p["dv"]),
                        "bc": float(p["bc"]), "source": desc})
        return out
    out = []
    for r in data.get("missiles", []):
        name = r.get("name", "")
        out.append({"name": name, "label": r.get("label") or SHORT_BY_NAME.get(name, name),
                    "dv": float(r["dv"]), "bc": float(r["bc"]),
                    "k": r.get("k"), "d_mm": r.get("d_mm"),
                    "two_stage": r.get("two_stage"), "source": data.get("source", desc)})
    return out


if __name__ == "__main__":
    for kind in available():
        rows = load_source(kind)
        print(f"\n{kind}: {len(rows)} 型  ({rows[0]['source'] if rows else '—'})")
        for r in rows:
            print(f"    {r['label']:<8} ΔV={r['dv']:7.1f} BC={r['bc']:7.1f}")

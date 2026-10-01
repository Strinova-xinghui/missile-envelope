# -*- coding: utf-8 -*-
"""spike (c) 的**数据通路**实验：把一场想定压成前端要吃的 JSON，量它有多大。

两种形状：
1. `full`   —— 每一行轨迹都留着（时间动画/高保真），量它的字节数；
2. `slim`   —— 对前端渲染够用的字段 + 抽稀到 N 点，量它降到多少。

跑法::

    $env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
    python spikes\\fig3d\\make_viewer_data.py            # 写 out/c/data.full.json 与 data.slim.json

**不解算**：源数据是已交付的 `results/traj_default_{missile,target}.csv` 与
`results/traj_default_segments.csv`。所以本脚本毫秒级、可重跑。
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "spikes" / "fig3d" / "out" / "c"

#: 渲染用逐顶点颜色（与 `figures.TRAJ_COLORS` 同义；前端不该依赖 Python 模块）
SEG_COLORS = {
    "grey": [0.62, 0.62, 0.62], "orange": [0.93, 0.55, 0.13],
    "red": [0.83, 0.20, 0.18], "teal": [0.13, 0.63, 0.63],
    "blue": [0.16, 0.36, 0.72],
}


def _rows(path: Path) -> list:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _decimate(xs, ys, zs, ts, n_max: int):
    """等间隔抽稀到 ≤ n_max 点（含首末点）。"""
    ln = len(xs)
    if ln <= n_max:
        return list(range(ln))
    idx = [round(i * (ln - 1) / (n_max - 1)) for i in range(n_max)]
    return sorted(set(int(i) for i in idx))


def build(n_max: int = 320):
    mis = _rows(ROOT / "results" / "traj_default_missile.csv")
    tgt = _rows(ROOT / "results" / "traj_default_target.csv")
    segs = _rows(ROOT / "results" / "traj_default_segments.csv")
    meta = json.loads((ROOT / "results" / "traj_default.json").read_text(encoding="utf-8"))
    run = meta["run"]

    # 逐行 → 分段色标（段是半开区间 [t0, t1)，最后一段闭合）
    def color_at(t: float):
        for i, s in enumerate(segs):
            t0, t1 = float(s["t0_s"]), float(s["t1_s"])
            last = (i == len(segs) - 1)
            if (t0 - 1e-9 <= t < t1 - 1e-9) or (last and t <= t1 + 1e-9):
                return SEG_COLORS.get(s["color_key"], SEG_COLORS["grey"])
        return SEG_COLORS["grey"]

    mt = [float(r["t_s"]) for r in mis]
    mx = [float(r["x_m"]) for r in mis]
    my = [float(r["y_m"]) for r in mis]
    mz = [float(r["z_m"]) for r in mis]
    tt = [float(r["t_s"]) for r in tgt]
    tx = [float(r["x_m"]) for r in tgt]
    ty = [float(r["y_m"]) for r in tgt]
    tz = [float(r["z_m"]) for r in tgt]

    full = {
        "tag": "default", "missile_name": run["missile"], "hit": run["hit"],
        "t_hit_s": run["t_hit_s"], "miss_m": run["miss_m"],
        "launch": [float(v) for v in meta["scene"]["launch_position_m"]],
        "target0": [float(v) for v in meta["scene"]["target_position_m"]],
        "missile": {"t": mt, "p": [[mx[i], my[i], mz[i]] for i in range(len(mt))],
                    "c": [color_at(mt[i]) for i in range(len(mt))]},
        "target": {"t": tt, "p": [[tx[i], ty[i], tz[i]] for i in range(len(tt))]},
        "segments": [
            {"t0": float(s["t0_s"]), "t1": float(s["t1_s"]), "label": s["label"],
             "color_key": s["color_key"], "phase": s.get("phase", ""),
             "heading0": float(s["heading0_deg"]), "heading1": float(s["heading1_deg"])}
            for s in segs],
        "marks": run.get("marks", ()),
        "anchor": run.get("anchor", {}),
    }

    # slim：只保留渲染必需字段 + 抽稀
    im = _decimate(mx, my, mz, mt, n_max)
    it = _decimate(tx, ty, tz, tt, n_max)
    slim = {
        "tag": "default", "missile_name": run["missile"], "hit": run["hit"],
        "t_hit_s": run["t_hit_s"], "miss_m": run["miss_m"],
        "launch": [float(v) for v in meta["scene"]["launch_position_m"]],
        "target0": [float(v) for v in meta["scene"]["target_position_m"]],
        "missile": {"t": [round(mt[i], 3) for i in im],
                    "p": [[round(mx[i], 1), round(my[i], 1), round(mz[i], 1)] for i in im],
                    "c": [color_at(mt[i]) for i in im]},
        "target": {"t": [round(tt[i], 3) for i in it],
                   "p": [[round(tx[i], 1), round(ty[i], 1), round(tz[i], 1)] for i in it]},
        "segments": full["segments"],
        "marks": run.get("marks", ()),
        "anchor": {k: run.get("anchor", {}).get(k) for k in
                   ("lock_distance_m", "t_beam_s", "t_react_s", "completed")},
    }
    return full, slim


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="spike(c) 前端数据通路：量 JSON 体积")
    ap.add_argument("--inline", action="store_true",
                    help="同时生成**单文件**版本 fig3d_viewer_offline.html（数据内联，真·零请求）")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    full, slim = build()
    f1 = OUT / "data.full.json"
    f2 = OUT / "data.slim.json"
    f1.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    f2.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    print(f"{'shape':<8}{'rows(弹/目标)':>16}{'bytes':>12}{'kB':>9}{'sha256[:12]':>15}")
    for name, d, p in (("full", full, f1), ("slim", slim, f2)):
        n = (len(d["missile"]["t"]), len(d["target"]["t"]))
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        print(f"{name:<8}{str(n):>16}{p.stat().st_size:>12}{p.stat().st_size / 1024:>9.1f}{h:>15}")

    if args.inline:
        tpl = (ROOT / "spikes" / "fig3d" / "fig3d_viewer.html").read_text(encoding="utf-8")
        blob = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
        marker = "const EMBEDDED = window.__TRAJ_DATA__ || null;"
        assert marker in tpl, "查看器模板的锚点没了，--inline 需要同步更新"
        out = tpl.replace(
            'window.__TRAJ_DATA__ || null',
            f'window.__TRAJ_DATA__ || {blob}')
        p = OUT / "fig3d_viewer_offline.html"
        p.write_text(out, encoding="utf-8", newline="")
        b = p.stat().st_size
        print(f"\n单文件版 out/c/fig3d_viewer_offline.html：{b} 字节（{b / 1024:.1f} kB）"
              f" = 模板 {len(tpl.encode('utf-8'))} B + 数据 {len(blob.encode('utf-8'))} B")
        print("打开方式：直接双击（file://），**零网络请求**。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

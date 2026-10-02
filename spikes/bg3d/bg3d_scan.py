# -*- coding: utf-8 -*-
"""spike：**把 ΔV 解开成第三根轴**，做三维扫描 `t_hit(β, γ, ΔV)`。

跑法（在 worktree 根）::

    $env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
    python spikes\\bg3d\\bg3d_scan.py --grid coarse        # ~1.5 min（924 工况）
    python spikes\\bg3d\\bg3d_scan.py --grid fine          # ~7 min（5049 工况，会进缓存）
    python spikes\\bg3d\\bg3d_scan.py --grid both

产物（`spikes/bg3d/out/`）：`scan_coarse.json` / `scan_fine.json`（网格 + 立方体 + 命中掩码 +
dv_measured + 摘要）与 `cases_fine.csv`（逐工况一行）。

**与已有产物零冲突**：`results/` 一个字节都不动（新产物全部落在 `spikes/bg3d/out/`），
缓存走仓库既有的 `results/cache/<tier>.json`（gitignore，是正常的扫描副作用）。

三轴范围**显式对齐到整步长**，并**断言弹池 11 型全部落在立方体内** —— 2D 层的
`make_grid` 是"向内对齐"，粗步长下会把 β 下限抬到 2600、把 R-77（β=2568.8）挤出立方体。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from missile_sim import bg, bg3d, figures            # noqa: E402
from missile_sim.spec import Scene                   # noqa: E402

OUT = ROOT / "spikes" / "bg3d" / "out"

#: 三个轴的**对齐后的**范围（都能被步长整除 ⇒ `make_grid3` 的向内对齐不改变端点）。
LIMITS = {"beta": (2500.0, 3750.0), "gamma": (44.0, 96.0), "dv": (600.0, 1100.0)}

GRIDS = {
    # name: (β 步长, γ 步长, ΔV 步长)
    "quick": (250.0, 8.0, 250.0),
    "coarse": (125.0, 4.0, 100.0),
    "fine": (75.0, 2.0, 50.0),
}


def build(name: str) -> bg3d.Bg3Grid:
    bs, gs, ds = GRIDS[name]
    return bg3d.make_grid3(LIMITS["beta"], LIMITS["gamma"], LIMITS["dv"],
                           beta_step=bs, gamma_step=gs, dv_step=ds)


def check_pool_inside(grid: bg3d.Bg3Grid, rows_) -> list:
    """弹池散点必须全在立方体里，否则"图上没有这型弹"会被误当成"这型弹不行"。"""
    outside = []
    for r in rows_:
        ok = (grid.beta[0] <= r.beta <= grid.beta[-1]
              and grid.gamma[0] <= r.gamma <= grid.gamma[-1]
              and grid.dv[0] <= r.dv <= grid.dv[-1])
        if not ok:
            outside.append((r.key, r.beta, r.gamma, r.dv))
    return outside


def write_cases_csv(scan: bg3d.Bg3Scan, path: Path) -> Path:
    """逐工况一行（`bg_default_cases.csv` 的 3D 版：**ΔV 是输入列**，dv_measured 才是结果）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["beta_target", "gamma_target", "dv_target_ms", "hit", "t_hit_s",
                    "dv_measured_ms", "backend", "tier"])
        for i, dv in enumerate(scan.grid.dv):
            for j, g in enumerate(scan.grid.gamma):
                for k, b in enumerate(scan.grid.beta):
                    t = scan.t_hit[i, j, k]
                    w.writerow([f"{b:.6f}", f"{g:.6f}", f"{dv:.6f}",
                                int(scan.hit[i, j, k]),
                                "" if not np.isfinite(t) else f"{t:.6f}",
                                "" if not np.isfinite(scan.dv_measured[i, j, k])
                                else f"{scan.dv_measured[i, j, k]:.6f}",
                                scan.backend, scan.tier])
    return path


def run_one(name: str, *, tier: str, jobs: int, cache: bool, live: bool) -> dict:
    grid = build(name)
    rows_ = bg.rows(None)
    outside = check_pool_inside(grid, rows_)
    print(f"[{name}] 网格 β{len(grid.beta)}×γ{len(grid.gamma)}×ΔV{len(grid.dv)} = "
          f"{grid.n_cases} 工况；β {grid.beta[0]:.0f}..{grid.beta[-1]:.0f}、"
          f"γ {grid.gamma[0]:.0f}..{grid.gamma[-1]:.0f}、ΔV {grid.dv[0]:.0f}..{grid.dv[-1]:.0f}"
          f"；档位 {tier}；jobs {jobs}；缓存 {'开' if cache else '关'}")
    if outside:
        raise SystemExit(f"弹池有 {len(outside)} 型落在立方体外：{outside}")
    print(f"[{name}] 弹池 11 型全部在立方体内 ✓；单元格数 "
          f"{grid.n_cells[0]}×{grid.n_cells[1]}×{grid.n_cells[2]}")

    scan = bg3d.scan3(Scene(), grid=grid, tier=tier, jobs=jobs, cache=cache,
                      log=(lambda m: print(m, flush=True)) if live else None)
    s = scan.summary()
    print(f"[{name}] 命中 {s['n_hit']}/{s['n_cases']}（{100 * s['hit_rate']:.1f}%），"
          f"ok {s['n_ok']}，耗时 {s['elapsed_s']:.1f} s ⇒ {s['ms_per_case']:.1f} ms/工况"
          f"（{jobs} 并发），backend={s['backend']}")
    print(f"[{name}] t_hit ∈ [{s['t_hit_range_s'][0]:.3f}, {s['t_hit_range_s'][1]:.3f}] s，"
          f"engine 统计={scan.stats}")

    rec = scan.record()
    rec["kind"] = "bg3d-scan"
    rec["schema"] = 1
    rec["grid_name"] = name
    rec["limits"] = {"beta": list(LIMITS["beta"]), "gamma": list(LIMITS["gamma"]),
                     "dv": list(LIMITS["dv"])}
    rec["steps"] = {"beta": grid.beta_step, "gamma": grid.gamma_step, "dv": grid.dv_step}
    rec["pool_inside"] = True
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"scan_{name}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    print(f"[{name}] 记录 → {path.relative_to(ROOT)}（{path.stat().st_size} B）")
    return rec


def dv_axis_report(rec: dict) -> None:
    """ΔV 轴的口径报告：输入的"理想 ΔV"与仿真量到的 ΔV 差多少（这是**必须写进报告**的口径）。"""
    grid = rec["grid"]
    cube = rec["dv_measured"]
    ratios = []
    for i, dv in enumerate(grid["dv"]):
        for j in range(len(grid["gamma"])):
            for k in range(len(grid["beta"])):
                v = cube[i][j][k]
                if v is not None:
                    ratios.append(v / dv)
    a = np.asarray(ratios)
    print(f"[口径] dv_measured/dv_target：n={a.size}，min {a.min():.4f}、"
          f"中位 {np.median(a):.4f}、max {a.max():.4f}，相对散布 {(a.max() - a.min()) / np.median(a):.2%}")
    print("        ⇒ 第三根轴是「理想（真空等效）ΔV」（与图1/图2 的 ΔV 同口径，只改 thrust_scale）；"
          "仿真量到的 ΔV 系统性更低（阻力/重力损失），两者差一个近似常数因子。")


def main() -> int:
    ap = argparse.ArgumentParser(description="β–γ–ΔV 三维扫描 spike")
    ap.add_argument("--grid", default="both", choices=sorted(GRIDS) + ["both"],
                    help="网格档位；⚠ both 按 quick→coarse→fine 跑，后面的档会继承前面档的"
                         "缓存命中，所以「重跑」时墙钟会接近 0（记录的 n_run/n_cached 能看出来）。"
                         "要冷跑数字：先删 results/cache/<tier>.json 再分开调用")
    ap.add_argument("--tier", default="fast", choices=("fast", "standard"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="不逐层打印进度")
    args = ap.parse_args()

    figures.setup_style()
    names = sorted(GRIDS) if args.grid == "both" else [args.grid]
    names = [n for n in ["quick", "coarse", "fine"] if n in names]
    t0 = time.perf_counter()
    last = None
    for name in names:
        last = run_one(name, tier=args.tier, jobs=args.jobs, cache=not args.no_cache,
                       live=not args.quiet)
    if last is not None:
        dv_axis_report(last)
    print(f"总计 {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

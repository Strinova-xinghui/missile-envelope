# -*- coding: utf-8 -*-
"""图3 的**算核**：两条互不相同的路径 —— "11 个标称点"（默认产物）与"单弹立方体"（按需）。

用户 2026-10-02 的口径："**命中点不用，只出各弹三参数点即可**"。所以：

| 路径 | 算什么 | 花多少 | 落在哪 |
| --- | --- | --- | --- |
| **标称点**（默认） | 每枚弹**一个**工况：用**它自己的**标称 `(ΔV, β, γ)` 解一次 | **11 次求解**（秒级） | `results/fig3_<tag>.json` + `_cases.csv` |
| **立方体**（按需） | 那枚弹 11 ΔV × 7 β × 7 γ = **539 工况** | 实测冷跑 ~22 s（fast / 8 并发） | `results/fig3_cube_<弹名>_<指纹8位>.json` |

⚠ **默认产物里永远不许扫立方体** —— 这是判据（`solver.run` 调用次数 ≈ 11，不是 5929）。

## 复用而不重造

* 网格 / 三轴 → `Scaling` 的映射：`bg3d.Bg3Grid` / `bg3d.scaling3_for`（**一个字没改**）；
* 进程池 + 分档缓存：`engine.Engine`；
* β、γ 的域：`figures.bg_axis()`（= 图2 的自适应域），所以按需立方体**罩得住 11 弹**；
* 想定编译：`workflow.fig3_scene()`（复用图3 那个唯一的 `crank_beam()` 调用点）；
* 产物的 JSON 写入：`record.write_json()`（CRLF + 无 BOM，与仓库其余产物一致）。

## 三根轴的口径（与图1/图2 一致，别发明第四套）

    ΔV → thrust_scale = ΔV / ΔV_blk      （严格只动这一项）
    β  → cx_scale     = β_blk / β
    γ  → cx_scale·cxaoa_scale = γ / γ_blk（改 β 时 cxaoa_scale 按 1/cx_scale 联动，γ 被顶住）

**标称点**就是"把三个乘数都取成该弹自己的值"（于是 `thrust/cx/cxaoa = 1`，产物里逐弹记下来
供对账）：`ΔV_blk = metrics_of(e).dv`、`β_blk = bg.point_of(e).beta`、`γ_blk = bg.point_of(e).gamma`。
"""

from __future__ import annotations

import csv
import math
import time

import numpy as np

from . import bg, bg3d, fig3, figures, pool, record, solver
from .engine import Engine
from .spec import RESULT_DIR, Scene

#: 默认（按需立方体用）网格：β、γ 各 7 点取图2 的域，ΔV = [700,1700] 等分 11 点
#: （S0 探测的实测依据见 `docs/FIG3.md`：crank→39 下 ΔV ≤ 1000 是能力边界带）。
DEFAULT_N_BETA = fig3.N_BETA
DEFAULT_N_GAMMA = fig3.N_GAMMA
DEFAULT_DV_LIM = fig3.DV_LIM
DEFAULT_N_DV = fig3.N_DV

#: 标称点那张表（`fig3_<tag>_cases.csv`）的列 —— **一行一枚弹**。
#: ⚠ v3 去掉了 `n_star_g` / `R_ref` / `induced_dominated`：那三个是"只对格点有意义"的判别量，
#: 标称点上传不出来（`record.FIG3_CASES` 是给格点表用的，这里不再走它）。
NOMINAL_CASES = ("missile", "dv", "beta", "gamma",
                 "thrust_scale", "cx_scale", "cxaoa_scale",
                 "hit", "event", "t_hit_s", "t_end_s",
                 "min_separation_m", "cpa_m", "fuse_radius_m",
                 "max_alt_m", "v_impact_ms", "dv_measured_ms", "t_burnout_s",
                 "backend", "cache_hit", "error")


def default_grid(rows_, *, dv_pin: float, n_beta: int = DEFAULT_N_BETA,
                 n_gamma: int = DEFAULT_N_GAMMA, dv_lim=DEFAULT_DV_LIM,
                 n_dv: int = DEFAULT_N_DV,
                 beta_step: float | None = None, gamma_step: float | None = None) -> bg3d.Bg3Grid:
    """按需立方体的三维网格：**β、γ 覆盖图2 的域（含端点），ΔV 是绝对区间等分 `n_dv` 点**。

    `dv_pin` 只作为**参考标记**（基准弹标称 ΔV）落进产物，不决定轴的位置。

    ⚠ 为什么这里**不**用 `bg3d.make_grid3()` 的"向内对齐到整步长"：7 个点落不到整步长上，
    向内对齐会把 β 的下限抬到 2600，把 R-77（2568.8）与 Derby（2567.0）挤出立方体 ——
    "图上没有它"会被读成"它不行"（`docs/FIG-BG3D-FEASIBILITY.md` §3 记过这个坑）。
    所以这里**显式等分**（端点 = 图2 的域端点），`*_step` 只是"相邻点间距"，用于记录与显示。

    给了 `beta_step` / `gamma_step` 时改用"向内对齐"的等步长网格（试轴用，同 `bg3d.make_grid3`）。
    """
    if float(dv_pin) <= 0:
        raise ValueError(f"ΔV 钉值必须为正，收到 {dv_pin!r}")
    if int(n_beta) < 2 or int(n_gamma) < 2:
        raise ValueError("β、γ 至少各要 2 个点")
    if int(n_dv) < 2:
        raise ValueError("ΔV 至少要有 2 个点")
    dv_lo, dv_hi = (float(dv_lim[0]), float(dv_lim[1]))
    if not (dv_hi > dv_lo):
        raise ValueError(f"ΔV 区间必须递增，收到 {dv_lim!r}")
    axis = figures.bg_axis(rows_)                        # 图2 的域（含它自己的 pad 规则）
    beta = _lin(axis.xlim[0], axis.xlim[1], int(n_beta))
    gamma = _lin(axis.ylim[0], axis.ylim[1], int(n_gamma))
    dv = _lin(dv_lo, dv_hi, int(n_dv))
    if beta_step or gamma_step:
        lim = bg3d.box_limits(rows_, dv_lim=(dv[0], dv[-1]))
        return bg3d.make_grid3(lim["beta"], lim["gamma"], lim["dv"],
                               beta_step=float(beta_step or 100.0),
                               gamma_step=float(gamma_step or 4.0),
                               dv_step=float(dv[1] - dv[0]))
    return bg3d.Bg3Grid(beta=beta, gamma=gamma, dv=dv,
                        beta_step=_step(beta), gamma_step=_step(gamma),
                        dv_step=_step(dv))


def _lin(lo, hi, n: int) -> tuple:
    return tuple(round(float(lo) + (float(hi) - float(lo)) * i / (n - 1), 4) for i in range(n))


def _step(vals) -> float:
    vals = [float(v) for v in vals]
    return (vals[-1] - vals[0]) / (len(vals) - 1) if len(vals) > 1 else 0.0


def grid_of(rows_, *, dv_pin: float, n_beta: int = DEFAULT_N_BETA,
            n_gamma: int = DEFAULT_N_GAMMA, dv_lim=DEFAULT_DV_LIM,
            n_dv: int = DEFAULT_N_DV) -> bg3d.Bg3Grid:
    """`default_grid()` 的薄封装（产物与按需扫描都从这里取网格，**只有一个出处**）。"""
    return default_grid(rows_, dv_pin=dv_pin, n_beta=n_beta, n_gamma=n_gamma,
                        dv_lim=dv_lim, n_dv=n_dv)


# --------------------------------------------------------------------- ① 标称点


def nominal_cells(entries) -> list:
    """11 枚弹的**标称三参数**（唯一口径，见模块 docstring）→ 一列 (`entry`, 元数据)。

    每个元素的 `scaling` 是"该弹自己"的乘数（应当恰好 = 1.0 / 1.0 / 1.0），
    由 `bg3d.scaling3_for()` 在标称坐标上现算 —— 所以**不是**手写的 1，而是算出来的。
    """
    out = []
    for e in entries:
        point = bg.point_of(e)
        metrics = pool.metrics_of(e)
        beta, gamma, dv = float(point.beta), float(point.gamma), float(metrics.dv)
        out.append({"entry": e, "point": point, "metrics": metrics,
                    "beta": beta, "gamma": gamma, "dv": dv,
                    "native": e.native})
    return out


def scan_nominal(scene: Scene, *, entries, tier: str = "fast", jobs: int = 8,
                 cache: bool = True, log=None) -> dict:
    """**默认路径**：每枚弹只解它自己的标称点这一工况（11 次求解）。

    走的是与立方体**完全相同**的代码路径（`Engine` + `bg3d.scaling3_for`），
    只是每枚弹的格点表只有一项 —— 所以"标称点"与"立方体里那个格点"逐位一致
    （`test_fig3_scan_one_case_matches_a_direct_engine_run` 会重新对拍一遍）。
    """
    say = log or (lambda _m: None)
    cells = nominal_cells(entries)
    shots, t0 = [], time.perf_counter()
    n_run = n_cached = n_hit = 0
    backend = "not-run"
    for i, cell in enumerate(cells, start=1):
        e, point, metrics = cell["entry"], cell["point"], cell["metrics"]
        dv, beta, gamma = cell["dv"], cell["beta"], cell["gamma"]
        say(f"[{i}/{len(cells)}] {e.key}（{e.native}）ΔV={dv:.1f} β={beta:.1f} γ={gamma:.2f}")
        eng = Engine(scene, missile=e.native, tier=tier, jobs=jobs, cache=cache, metrics=metrics,
                     scaling_of=lambda b, g, _p=point, _m=metrics, _d=dv:
                     bg3d.scaling3_for(_p, _m, beta=b, gamma=g, dv=_d))
        try:
            got = eng.many([(beta, gamma)])
        finally:
            stats = dict(eng.stats)
            eng.close()
        shot = got[0] if got else None
        cell["shot"] = shot
        cell["stats"] = stats
        cell["scaling"] = bg3d.scaling3_for(point, metrics, beta=beta, gamma=gamma, dv=dv)
        if shot is not None:
            backend = shot.backend or backend
            if getattr(shot, "cache_hit", False):
                n_cached += 1
            else:
                n_run += 1
            if shot.ok:
                say(f"    {e.key}: {'命中 ' + format(float(shot.t_hit), '.3f') + ' s' if shot.hit else '未命中'}"
                    f"（{shot.event}）")
            if shot.ok and shot.hit and math.isfinite(float(shot.t_hit)):
                n_hit += 1
        shots.append(shot)
    return {"cells": cells, "shots": shots, "scene": scene, "tier": tier,
            "elapsed_s": time.perf_counter() - t0, "backend": backend,
            "n_run": n_run, "n_cached": n_cached, "n_hit": n_hit,
            "n_missiles": len(cells)}


def build_nominal_record(scan: dict, *, tag: str, standard, grid: bg3d.Bg3Grid,
                         layer: dict) -> dict:
    """标称点扫描 → `results/fig3_<tag>.json` 的内容（**schema 3**）。"""
    missiles = []
    for cell in scan["cells"]:
        e, shot = cell["entry"], cell.get("shot")
        sc = cell["scaling"]
        hit = bool(shot is not None and shot.ok and shot.hit
                   and math.isfinite(float(shot.t_hit or math.nan)))
        missiles.append({
            "key": e.key, "label": e.label, "native": e.native,
            "full_name": getattr(e, "full_name", e.label),
            # 标称三参数（权威口径）
            "dv": float(cell["dv"]), "beta": float(cell["beta"]),
            "gamma": float(cell["gamma"]),
            "scaling": {"thrust_scale": sc.thrust_scale, "cx_scale": sc.cx_scale,
                        "cxaoa_scale": sc.cxaoa_scale},
            # 结局：命中 ⇒ t_hit；未命中 ⇒ None（**绝不用 t_end / lifetime 冒充**）
            "hit": hit,
            "t_hit_s": (float(shot.t_hit) if hit else None),
            "event": (shot.event if shot is not None else ""),
            "t_end_s": _f(shot, "t_end"), "min_separation_m": _f(shot, "min_separation_m"),
            "fuse_radius_m": _f(shot, "fuse_radius_m"), "max_alt_m": _f(shot, "max_alt_m"),
            "v_impact_ms": _f(shot, "v_impact"), "dv_measured_ms": _f(shot, "dv_measured"),
            "t_burnout_s": _f(shot, "t_burnout"),
            "backend": (shot.backend if shot is not None else ""),
            "cache_hit": bool(shot is not None and getattr(shot, "cache_hit", False)),
            "error": (shot.error if shot is not None else "没有结果"),
            "n_ok": int(bool(shot is not None and shot.ok)),
        })
    n_hit = sum(1 for m in missiles if m["hit"])
    dv_pin_used = _dv_pin_of(scan, grid)
    return {
        "schema": fig3.SCHEMA, "figure": "fig3", "kind": figures.FIG3_KIND, "tag": tag,
        "scene": scan["scene"].as_dict(),
        "standard": str(getattr(standard, "key", standard)),
        "standard_native": str(getattr(standard, "native", "")),
        "tier": scan["tier"], "backend": scan["backend"],
        "solver": dict(solver.identity()),
        # 按需立方体的**网格契约**（默认产物里没有立方体，这组数决定"扫多大"）
        "grid": dict(grid.as_dict(), limits=grid.limits(), dv_pin_ms=dv_pin_used,
                     dv_lim=[float(grid.dv[0]), float(grid.dv[-1])]),
        "layer": dict(layer),
        "t_react_s": scan.get("t_react_s"),
        "t_react_note": str(scan.get("t_react_note") or ""),
        "scene_text": str(scan.get("scene_text") or ""),
        "missiles": missiles,
        "summary": {"n_missiles": len(missiles), "n_hit": n_hit,
                    "n_miss": len(missiles) - n_hit,
                    "shape": list(grid.shape), "cube_cases": int(grid.n_cases),
                    "n_run": int(scan["n_run"]), "n_cached": int(scan["n_cached"]),
                    "elapsed_s": round(float(scan["elapsed_s"]), 3),
                    "data_source": "每枚弹的标称三参数点（11 个点，无格点云）"},
    }


def _f(shot, name):
    """`Shot` 的某个字段 → 有限浮点或 `None`（非有限一律折成 None，别写进 JSON）。"""
    if shot is None:
        return None
    v = getattr(shot, name, None)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _dv_pin_of(scan: dict, grid: bg3d.Bg3Grid) -> float:
    """`dv_pin_ms` = **基准弹**的权威 ΔV（不是"轴中间那个格点"）。"""
    return float(scan.get("dv_pin") or fig3.DV_PIN_MS)


def nominal_rows(scan: dict) -> list:
    """标称点产物 → CSV 行（**一行一枚弹**，列见 `NOMINAL_CASES`）。"""
    rows = []
    for cell in scan["cells"]:
        e, shot = cell["entry"], cell.get("shot")
        sc = cell["scaling"]
        hit = bool(shot is not None and shot.ok and shot.hit
                   and math.isfinite(float(shot.t_hit or math.nan)))
        rows.append({
            "missile": e.key, "dv": cell["dv"], "beta": cell["beta"], "gamma": cell["gamma"],
            "thrust_scale": sc.thrust_scale, "cx_scale": sc.cx_scale,
            "cxaoa_scale": sc.cxaoa_scale,
            "hit": 1 if hit else 0, "event": (shot.event if shot is not None else ""),
            "t_hit_s": (float(shot.t_hit) if hit else None), "t_end_s": _f(shot, "t_end"),
            "min_separation_m": _f(shot, "min_separation_m"),
            "cpa_m": None, "fuse_radius_m": _f(shot, "fuse_radius_m"),
            "max_alt_m": _f(shot, "max_alt_m"), "v_impact_ms": _f(shot, "v_impact"),
            "dv_measured_ms": _f(shot, "dv_measured"), "t_burnout_s": _f(shot, "t_burnout"),
            "backend": (shot.backend if shot is not None else ""),
            "cache_hit": 1 if (shot is not None and getattr(shot, "cache_hit", False)) else 0,
            "error": (shot.error if shot is not None else "没有结果"),
        })
    return rows


# --------------------------------------------------------------------- ② 单弹立方体


def scan_cube(scene: Scene, entry, grid: bg3d.Bg3Grid, *, tier: str = "fast", jobs: int = 8,
              cache: bool = True, log=None, progress=None) -> dict:
    """**按需路径**：一枚弹的立方体（`Engine` 外层循环 ΔV，与 `bg3d.scan3` 同款）。"""
    say = log or (lambda _m: None)
    point = bg.point_of(entry)
    metrics = pool.metrics_of(entry)
    shape = grid.shape
    t_hit = np.full(shape, np.nan, dtype=float)
    hit = np.zeros(shape, dtype=bool)
    dv_measured = np.full(shape, np.nan, dtype=float)
    shots_all: list = []
    n_ok = n_hit = n_run = n_cached = 0
    backend = "not-run"
    plane_cells = grid.plane_cells()
    n_beta = len(grid.beta)
    holder = {"dv": float(grid.dv[0])}
    t0 = time.perf_counter()
    eng = Engine(scene, missile=entry.native, tier=tier, jobs=jobs, cache=cache, metrics=metrics,
                 scaling_of=lambda b, g: bg3d.scaling3_for(point, metrics, beta=b, gamma=g,
                                                           dv=holder["dv"]))
    try:
        for i, dv in enumerate(grid.dv):
            holder["dv"] = float(dv)
            shots = eng.many(plane_cells)
            shots_all.extend(shots)
            layer_hit = 0
            for k, shot in enumerate(shots):
                j, m = divmod(k, n_beta)                    # γ 外层、β 内层
                if shot is None:
                    continue
                backend = shot.backend or backend
                if getattr(shot, "cache_hit", False):
                    n_cached += 1
                else:
                    n_run += 1
                if shot.ok:
                    n_ok += 1
                    dv_measured[i, j, m] = float(shot.dv_measured)
                    if shot.hit and math.isfinite(float(shot.t_hit)):
                        t_hit[i, j, m] = float(shot.t_hit)
                        hit[i, j, m] = True
                        n_hit += 1
                        layer_hit += 1
            say(f"  {entry.key} ΔV={dv:.1f} m/s：命中 {layer_hit}/{len(plane_cells)}"
                f"（累计 {n_hit}/{grid.n_cases}）")
            if progress is not None:                     # 页面那条进度条（逐 ΔV 层报一次）
                try:
                    progress((i + 1) * len(plane_cells), grid.n_cases)
                except Exception:                        # noqa: BLE001  进度回调不许影响扫描
                    pass
    finally:
        stats = dict(eng.stats)
        eng.close()
    elapsed = time.perf_counter() - t0
    return {"entry": entry, "point": point, "metrics": metrics, "t_hit": t_hit, "hit": hit,
            "dv_measured": dv_measured, "shots": shots_all, "backend": backend,
            "elapsed_s": elapsed, "stats": stats, "n_ok": n_ok, "n_hit": n_hit,
            "n_run": n_run, "n_cached": n_cached}


def build_cube_record(scan: dict, *, scene: Scene, tier: str, grid: bg3d.Bg3Grid,
                      layer: dict, cube_key: str, standard=None) -> dict:
    """单弹立方体 → `results/fig3_cube_<弹名>_<指纹8位>.json` 的内容。"""
    return {
        "schema": fig3.CUBE_SCHEMA, "kind": "fig3-cube", "cube_key": str(cube_key),
        "missile": scan["entry"].key, "native": scan["entry"].native,
        "tier": str(tier), "standard": str(getattr(standard, "key", standard or "")),
        "scene": scene.as_dict(), "grid": dict(grid.as_dict(), limits=grid.limits()),
        "layer": dict(layer),
        "solver": dict(solver.identity()),
        "t_hit": _grid_json(scan["t_hit"]), "hit": _int_grid(scan["hit"]),
        "dv_measured": _grid_json(scan["dv_measured"]),
        # ⚠ 这里**只放与"这次运行"无关的量**：`elapsed_s` / `n_run` / `n_cached` 会随
        #   "冷跑还是命中引擎缓存"变，写进文件就意味着"同一条命令重出产物不再逐字节一致"，
        #   而且**每读一次页面就可能回写一次**（Lead 2026-10-02 验收抓到的正是这个）。
        #   本次运行的耗时/命中数走日志与后台任务消息，不进产物。
        "summary": {"n_cases": int(grid.n_cases), "n_hit": int(scan["n_hit"]),
                    "n_ok": int(scan["n_ok"]), "backend": scan["backend"]},
    }


def run_cube(scene: Scene, entry, *, grid: bg3d.Bg3Grid, tier: str = "fast", jobs: int = 8,
             cache: bool = True, layer: dict | None = None, standard=None,
             result_dir=None, log=None, progress=None, force: bool = False) -> dict:
    """按需扫一枚弹的立方体。

    **写不写盘由"是不是真的算过"决定**（Lead 2026-10-02 的验收缺陷）：

    `force=True` 时忽略缓存、强制重扫（`--fig3-cube-force` 走这条）。
    * 已经有一份**指纹对得上**的缓存 ⇒ 直接返回它（`read_hit=True`），**一个字节都不动**；
    * 否则扫一遍：只有 `n_run > 0`（真解过算）才落盘；全是引擎缓存命中（`n_run == 0`）时，
      内容与已有缓存等价 ⇒ **不写**（写回去只会让 `git status` 变脏、并让"重出产物逐字节一致"
      变成假象）。
    """
    from pathlib import Path as _Path

    say = log or (lambda _m: None)
    sha = str((solver.identity() or {}).get("sha256") or "")
    paths = fig3.cube_path(entry.key, scene=scene.as_dict(), tier=tier,
                           grid=grid.as_dict(), result_dir=result_dir, solver_sha=sha)
    hit = None if force else read_cube_or_none(scene, entry, grid=grid, tier=tier,
                                               result_dir=result_dir)
    if hit is not None:
        say(f"命中立方体缓存（只读，不回写）：{hit['_path']}"
            f"（{hit['summary']['n_cases']} 工况 · 命中 {hit['summary']['n_hit']}）")
        return {"cube": hit["_path"], "cube_key": hit["cube_key"], "read_hit": True,
                "record": hit, "scan": None, "n_hit": int(hit["summary"]["n_hit"]),
                "n_cases": int(hit["summary"]["n_cases"]), "elapsed_s": 0.0}
    scan = scan_cube(scene, entry, grid, tier=tier, jobs=jobs, cache=cache,
                     log=say, progress=progress)
    rec = build_cube_record(scan, scene=scene, tier=tier, grid=grid,
                            layer=dict(layer or {}), cube_key=paths["cube_key"],
                            standard=standard)
    written = False
    if int(scan["n_run"]) > 0 or not _Path(paths["cube"]).is_file():
        fig3.write_cube(paths["cube"], rec)
        written = True
    else:
        say("全命中引擎缓存（n_run=0）：结果与已有缓存等价，**不回写**")
    say(f"立方体{"缓存：" if written else "（未写盘）："}{paths['cube']}"
        f"（{rec['summary']['n_cases']} 工况 · 命中 {rec['summary']['n_hit']} · "
        f"{scan['elapsed_s']:.1f} s）")
    return {"cube": paths["cube"], "cube_key": paths["cube_key"], "read_hit": False,
            "record": rec, "scan": scan, "n_hit": int(scan["n_hit"]),
            "n_cases": int(grid.n_cases), "elapsed_s": float(scan["elapsed_s"]),
            "written": written}


def read_cube_or_none(scene: Scene, entry, *, grid: bg3d.Bg3Grid, tier: str,
                      result_dir=None) -> dict | None:
    """缓存里有（且指纹对得上）就返回，否则 `None`。**读成功也算一次"命中缓存"**。"""
    import os
    from pathlib import Path

    sha = str((solver.identity() or {}).get("sha256") or "")
    paths = fig3.cube_path(entry.key, scene=scene.as_dict(), tier=tier,
                           grid=grid.as_dict(), result_dir=result_dir, solver_sha=sha)
    if not Path(paths["cube"]).is_file():
        return None
    try:
        blob = fig3.read_cube(paths["cube"], missile=entry.key, scene=scene.as_dict(),
                              tier=tier, grid=grid.as_dict(), solver_sha=sha)
    except (ValueError, OSError):
        return None
    blob["cache_read_hit"] = True
    blob["_path"] = paths["cube"]
    blob["_mtime"] = os.path.getmtime(paths["cube"])
    return blob


# --------------------------------------------------------------------- 产物


def write_nominal_csv(rows, path) -> str:
    """标称点表（一行一枚弹）。列名 = `NOMINAL_CASES`（**唯一出处**）。"""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(NOMINAL_CASES)
        for r in rows or ():
            w.writerow([
                str(r.get("missile") or ""),
                _csv_num(r.get("dv"), 4), _csv_num(r.get("beta"), 4),
                _csv_num(r.get("gamma"), 4),
                _csv_num(r.get("thrust_scale")), _csv_num(r.get("cx_scale")),
                _csv_num(r.get("cxaoa_scale")),
                int(bool(r.get("hit"))), str(r.get("event") or ""),
                _csv_num(r.get("t_hit_s"), 4), _csv_num(r.get("t_end_s"), 4),
                _csv_num(r.get("min_separation_m"), 2), _csv_num(r.get("cpa_m"), 2),
                _csv_num(r.get("fuse_radius_m"), 2), _csv_num(r.get("max_alt_m"), 2),
                _csv_num(r.get("v_impact_ms"), 2), _csv_num(r.get("dv_measured_ms"), 2),
                _csv_num(r.get("t_burnout_s"), 4), str(r.get("backend") or ""),
                int(bool(r.get("cache_hit"))), str(r.get("error") or ""),
            ])
    return str(p)


def _csv_num(v, digits: int = 6) -> str:
    """数字 → 文本；`None` / 非有限 ⇒ **空串**（`NaN` 会让下游当成"有个数"）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(f):
        return ""
    txt = f"{f:.{digits}f}".rstrip("0").rstrip(".")
    return txt if txt not in ("", "-0") else ("0" if txt == "-0" else txt)


def _grid_json(arr) -> list:
    return [[[None if not np.isfinite(v) else round(float(v), 6) for v in row]
             for row in plane] for plane in np.asarray(arr, dtype=float)]


def _int_grid(arr) -> list:
    return [[[int(v) for v in row] for row in plane]
            for plane in np.asarray(arr, dtype=bool)]


def write_products(rec: dict, rows: list, *, tag: str, result_dir=None) -> dict:
    """落盘：`fig3_<tag>.json` + `fig3_<tag>_cases.csv`（返回路径表）。"""
    res_dir = RESULT_DIR if result_dir is None else result_dir
    return {"record": str(record.write_json(res_dir / f"fig3_{tag}.json", rec)),
            "cases": write_nominal_csv(rows, res_dir / f"fig3_{tag}_cases.csv")}


def run_nominal(scene: Scene, *, entries, tag: str, standard=None, tier: str = "fast",
                jobs: int = 8, cache: bool = True, n_beta: int = DEFAULT_N_BETA,
                n_gamma: int = DEFAULT_N_GAMMA, dv_lim=DEFAULT_DV_LIM,
                n_dv: int = DEFAULT_N_DV, dv_pin: float | None = None,
                iso_step: float = 1.0, t_react_s: float | None = None,
                t_react_note: str = "", scene_text: str = "",
                result_dir=None, progress=None, log=None) -> dict:
    """**默认路径**一条命令重出：11 个标称点（不解任何立方体）。"""
    say = log or (lambda _m: None)
    rows_ = bg.rows(entries or None)
    std_entry = pool.standard_entry(standard)
    pin = float(dv_pin) if dv_pin else float(pool.metrics_of(std_entry).dv)
    grid = grid_of(rows_, dv_pin=pin, n_beta=n_beta, n_gamma=n_gamma,
                   dv_lim=dv_lim, n_dv=n_dv)
    say(f"标称点：{len(entries)} 枚弹 × 1 工况 = {len(entries)} 次求解"
        f"（ΔV 钉值 {pin:.4f} m/s，只作参考标记）")
    say(f"按需立方体的网格 (ΔV,γ,β) = {grid.shape} = {grid.n_cases} 工况 × 每枚弹 "
        f"· ΔV {grid.dv[0]:.0f}~{grid.dv[-1]:.0f} · β {grid.beta[0]:.2f}~{grid.beta[-1]:.2f}"
        f" · γ {grid.gamma[0]:.3f}~{grid.gamma[-1]:.3f}")
    scan = scan_nominal(scene, entries=entries, tier=tier, jobs=jobs, cache=cache, log=say)
    scan["dv_pin"] = pin
    scan["t_react_s"] = None if t_react_s is None else float(t_react_s)
    scan["t_react_note"] = str(t_react_note)
    scan["scene_text"] = str(scene_text)
    layer = {"n_levels": int(fig3.LAYER_COUNT), "iso_step": float(iso_step),
             "min_cells": int(fig3.LAYER_MIN_CELLS), "min_tri": int(fig3.LAYER_MIN_TRI)}
    rec = build_nominal_record(scan, tag=tag, standard=std_entry, grid=grid, layer=layer)
    rows = nominal_rows(scan)
    paths = write_products(rec, rows, tag=tag, result_dir=result_dir)
    say(f"总计 {rec['summary']['n_missiles']} 枚弹（真解算 {rec['summary']['n_run']} · "
        f"命中缓存 {rec['summary']['n_cached']}）· 命中 {rec['summary']['n_hit']} / "
        f"未命中 {rec['summary']['n_miss']} · 耗时 {scan['elapsed_s']:.2f} s")
    return {"scan": scan, "record": rec, "rows": rows, "paths": paths, "grid": grid,
            "elapsed_s": scan["elapsed_s"], "dv_pin": pin, "standard": std_entry,
            "iso_step": float(iso_step), "t_react_s": t_react_s}

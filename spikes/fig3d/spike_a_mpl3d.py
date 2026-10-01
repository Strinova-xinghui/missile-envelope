# -*- coding: utf-8 -*-
"""spike (a)：matplotlib mplot3d 静态 3D —— **零新依赖**路线，只量能不能用。

跑法（在仓库根）::

    $env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
    python spikes\\fig3d\\spike_a_mpl3d.py            # 出样例产物 + 打印数字表

产出（默认写到 `spikes/fig3d/out/a/`）：
  每个变体三格式 `png/pdf/svg`；**同进程连出两次**，比 sha256（SVG 走
  `figures.normalize_svg_ids()`，与 `-k figures_repro` 同款判据）。

数据来源（**不解算**）：`results/traj_default_{target,missile}.csv` +
`results/plane_default_cases.csv`（1632 行 t_hit 网格）+ `results/bg_default_cases.csv`。
所以本脚本秒级可重跑，且不碰 `figures/` 与 `results/`。
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib                                       # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                         # noqa: E402
import matplotlib.ticker as mticker                     # noqa: E402
import numpy as np                                      # noqa: E402

from missile_sim import figures                         # noqa: E402

OUT_DATA = ROOT / "spikes" / "fig3d" / "out"            # 记录文件（a_report.json / crossA|B.json）
OUT = OUT_DATA / "a"                                    # 变体产物默认落这里
FORMATS = ("png", "pdf", "svg")


# ------------------------------------------------------------------ 数据装载


def _rows(path: Path) -> list:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_traj():
    """图3 的弹/目标三维轨迹（**从已交付 CSV 读，不解算**）。"""
    tgt = _rows(ROOT / "results" / "traj_default_target.csv")
    mis = _rows(ROOT / "results" / "traj_default_missile.csv")
    t1 = [float(r["t_s"]) for r in tgt]
    tx = [float(r["x_m"]) for r in tgt]
    ty = [float(r["y_m"]) for r in tgt]
    tz = [float(r["z_m"]) for r in tgt]
    t2 = [float(r["t_s"]) for r in mis]
    mx = [float(r["x_m"]) for r in mis]
    my = [float(r["y_m"]) for r in mis]
    mz = [float(r["z_m"]) for r in mis]
    meta = json.loads((ROOT / "results" / "traj_default.json").read_text(encoding="utf-8"))
    return {
        "t_tgt": t1, "tx": tx, "ty": ty, "tz": tz,
        "t_mis": t2, "mx": mx, "my": my, "mz": mz,
        "t_hit": float(meta["run"]["t_hit_s"]),
        "hit": bool(meta["run"]["hit"]),
    }


def load_plane_grid():
    """图1 的 t_hit 网格 → `(dv 轴, bc 轴, T[bc, dv] 矩阵)`（缺失 = nan）。"""
    rs = _rows(ROOT / "results" / "plane_default_cases.csv")
    dv = sorted({round(float(r["dv_target"]), 6) for r in rs})
    bc = sorted({round(float(r["bc_target"]), 6) for r in rs})
    di = {v: i for i, v in enumerate(dv)}
    bi = {v: i for i, v in enumerate(bc)}
    T = np.full((len(bc), len(dv)), np.nan)
    for r in rs:
        if str(r.get("hit", "")).strip() not in ("1", "True", "true"):
            continue
        th = str(r.get("t_hit_s", "")).strip()
        if not th:
            continue
        T[bi[round(float(r["bc_target"]), 6)], di[round(float(r["dv_target"]), 6)]] = float(th)
    return np.array(dv), np.array(bc), T


def load_bg_grid():
    """图2 的 β–γ t_hit 网格。"""
    rs = _rows(ROOT / "results" / "bg_default_cases.csv")
    if not rs:
        return None
    cols = set(rs[0])
    kx = "beta" if "beta" in cols else ("beta_target" if "beta_target" in cols else None)
    ky = "gamma" if "gamma" in cols else ("gamma_target" if "gamma_target" in cols else None)
    if kx is None or ky is None:
        return None
    be = sorted({round(float(r[kx]), 6) for r in rs})
    ga = sorted({round(float(r[ky]), 6) for r in rs})
    xi = {v: i for i, v in enumerate(be)}
    yi = {v: i for i, v in enumerate(ga)}
    T = np.full((len(ga), len(be)), np.nan)
    for r in rs:
        if str(r.get("hit", "")).strip() not in ("1", "True", "true"):
            continue
        th = str(r.get("t_hit_s", "")).strip()
        if not th:
            continue
        T[yi[round(float(r[ky]), 6)], xi[round(float(r[kx]), 6)]] = float(th)
    return np.array(be), np.array(ga), T


# ------------------------------------------------------------------ 出图体


def _save(fig, base: Path, formats=FORMATS):
    paths = figures.save_formats(fig, base, formats=formats)
    plt.close(fig)
    return paths


def v1_traj_plan_2d(d, base):
    """基准：现有图3 的**俯视弹道**（平面）—— 对照组的"2D 版"。"""
    fig, ax = plt.subplots(figsize=(8.6, 5.4))
    try:
        ax.plot(d["tx"], d["tz"], lw=1.8, color="#c0392b", label="目标")
        ax.plot(d["mx"], d["mz"], lw=2.0, color="#1f4e9c", label="导弹")
        ax.plot([d["mx"][-1]], [d["mz"][-1]], "o", ms=7, mfc="white", mec="black")
        ax.set_xlabel("x [m]")
        ax.set_ylabel("z [m]")
        ax.set_title("图3 俯视（2D 基准）")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.25)
        return _save(fig, base)
    finally:
        plt.close(fig)


def _traj_3d_axes(ax, d):
    ax.plot(d["mx"], d["mz"], d["my"], lw=2.0, color="#1f4e9c", label="导弹")
    ax.plot(d["tx"], d["tz"], d["ty"], lw=1.8, color="#c0392b", label="目标")
    # 命中点
    ax.plot([d["mx"][-1]], [d["mz"][-1]], [d["my"][-1]], "o", ms=6,
            mfc="white", mec="black", label="命中点")
    ax.set_xlabel("x [m]", labelpad=6)
    ax.set_ylabel("z [m]", labelpad=6)
    ax.set_zlabel("高度 y [m]", labelpad=6)
    ax.legend(fontsize=8.5)


def v2_traj_3d(d, base):
    """图3 的三维轨迹：弹 + 目标 + 命中点。**无地面投影**。"""
    fig = plt.figure(figsize=(9.0, 6.4))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _traj_3d_axes(ax, d)
        ax.set_box_aspect(figures._box_aspect(d["mx"], d["my"], d["mz"]))
        ax.view_init(elev=22, azim=-60)
        ax.set_title("图3 三维轨迹（弹/目标/命中点）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v3_traj_3d_proj(d, base):
    """图3 三维 + 地面投影（高度 0 的虚线）+ 投影垂线。"""
    fig = plt.figure(figsize=(9.4, 6.6))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _traj_3d_axes(ax, d)
        z0 = 0.0
        ax.plot(d["mx"], d["mz"], [z0] * len(d["mx"]), lw=0.9, ls=":",
                color="#1f4e9c", alpha=0.75, label="导弹地面投影")
        ax.plot(d["tx"], d["tz"], [z0] * len(d["tx"]), lw=0.9, ls=":",
                color="#c0392b", alpha=0.75, label="目标地面投影")
        # 只在几个时刻画垂线，多了会糊成一片
        n = len(d["mx"])
        for k in range(0, n, max(1, n // 8)):
            ax.plot([d["mx"][k]] * 2, [d["mz"][k]] * 2, [z0, d["my"][k]],
                    lw=0.6, color="#888888", alpha=0.6)
        ax.set_box_aspect(figures._box_aspect(d["mx"], d["my"], d["mz"]))
        ax.view_init(elev=22, azim=-60)
        ax.set_title("图3 三维轨迹 + 地面投影")
        ax.legend(fontsize=8)
        return _save(fig, base)
    finally:
        plt.close(fig)


def v4_traj_3d_color_t(d, base):
    """图3 三维 + 按时间着色（第三维信息塞进颜色，而不是换个视角）。"""
    fig = plt.figure(figsize=(9.4, 6.6))
    try:
        ax = fig.add_subplot(111, projection="3d")
        t = np.asarray(d["mx"]) * 0 + np.linspace(0.0, d["t_hit"], len(d["mx"]))
        p = ax.scatter(d["mx"], d["mz"], d["my"], c=t, cmap="viridis", s=6)
        ax.plot(d["tx"], d["tz"], d["ty"], lw=1.4, color="#c0392b", label="目标")
        fig.colorbar(p, ax=ax, shrink=0.6, pad=0.09, label="t [s]")
        ax.set_xlabel("x [m]")
        ax.set_ylabel("z [m]")
        ax.set_zlabel("高度 y [m]")
        ax.set_box_aspect(figures._box_aspect(d["mx"], d["my"], d["mz"]))
        ax.view_init(elev=22, azim=-60)
        ax.set_title("图3 三维轨迹按时间着色")
        ax.legend(fontsize=8)
        return _save(fig, base)
    finally:
        plt.close(fig)


def v5_traj_3d_multi_azim(d, base):
    """图3 三维 + 两个方位角分格（同一份数据两个视角）。"""
    fig = plt.figure(figsize=(12.4, 5.8))
    try:
        for i, (elev, azim) in enumerate(((22.0, -60.0), (12.0, -120.0))):
            ax = fig.add_subplot(1, 2, i + 1, projection="3d")
            _traj_3d_axes(ax, d)
            ax.set_box_aspect(figures._box_aspect(d["mx"], d["my"], d["mz"]))
            ax.view_init(elev=elev, azim=azim)
            ax.set_title(f"elev={elev:g}° azim={azim:g}°", fontsize=10)
        fig.suptitle("图3 三维轨迹（双视角）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v6_traj_alt_2d(d, base):
    """图3 的**高度–时间**曲线（2D）—— 与三维争同一个信息的对照组。"""
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    try:
        ax.plot(d["t_mis"], d["my"], lw=2.0, color="#1f4e9c", label="导弹高度")
        ax.plot(d["t_tgt"], d["ty"], lw=1.8, color="#c0392b", label="目标高度")
        ax.axvline(d["t_hit"], ls="--", lw=1.0, color="black")
        ax.set_xlabel("t [s]")
        ax.set_ylabel("高度 y [m]")
        ax.set_title("图3 高度–时间（2D 基准）")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.25)
        return _save(fig, base)
    finally:
        plt.close(fig)


def v7_plane_2d(dv, bc, T, base):
    """基准：图1 的 ΔV–BC 平面（2D 等时线）。"""
    fig, ax = plt.subplots(figsize=(8.8, 5.6))
    try:
        levels = np.arange(np.nanmin(T), np.nanmax(T) + 1.0, 1.0)
        cs = ax.contourf(dv, bc, T, levels=levels, cmap="RdYlBu_r", extend="both")
        ax.contour(dv, bc, T, levels=levels[::2], colors="k", linewidths=0.4)
        fig.colorbar(cs, ax=ax, label="t_hit [s]")
        ax.set_xlabel("ΔV [m/s]")
        ax.set_ylabel("BC")
        ax.set_title("图1 ΔV–BC 平面（2D 基准）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v8_plane_3d_surface(dv, bc, T, base):
    """图1 的第三维 t_hit → 3D 曲面（Z = t_hit）。"""
    fig = plt.figure(figsize=(9.6, 6.8))
    try:
        ax = fig.add_subplot(111, projection="3d")
        Z = np.nan_to_num(T, nan=float(np.nanmean(T)))
        sf = ax.plot_surface(dv[None, :].repeat(len(bc), 0),
                             bc[:, None].repeat(len(dv), 1), Z,
                             cmap="RdYlBu_r", rstride=2, cstride=2,
                             linewidth=0.1, antialiased=True, alpha=0.95)
        fig.colorbar(sf, ax=ax, shrink=0.6, pad=0.09, label="t_hit [s]")
        ax.set_xlabel("ΔV [m/s]")
        ax.set_ylabel("BC")
        ax.set_zlabel("t_hit [s]")
        ax.view_init(elev=26, azim=-58)
        ax.set_title("图1 三维：ΔV–BC–t_hit 曲面")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v9_plane_3d_scatter(dv, bc, T, pts, base):
    """图1 的第三维 t_hit → 3D 散点（11 弹落点 + 曲面网格淡化）。"""
    fig = plt.figure(figsize=(9.6, 6.8))
    try:
        ax = fig.add_subplot(111, projection="3d")
        B, D = np.meshgrid(bc, dv, indexing="ij")
        ax.plot_wireframe(D[::4, ::4], B[::4, ::4], np.nan_to_num(T, nan=np.nanmean(T))[::4, ::4],
                          color="#999999", linewidth=0.4, alpha=0.5)
        if pts:
            px = [float(p["dv"]) for p in pts]
            py = [float(p["bc"]) for p in pts]
            pz = [float(p.get("t_hit", np.nan)) for p in pts]
            ok = [i for i, v in enumerate(pz) if np.isfinite(v)]
            ax.scatter([px[i] for i in ok], [py[i] for i in ok], [pz[i] for i in ok],
                       s=52, c="#1f4e9c", depthshade=False)
            for i in ok:
                ax.text(px[i], py[i], pz[i], f"  {pts[i]['label']}", fontsize=7.5)
        ax.set_xlabel("ΔV [m/s]")
        ax.set_ylabel("BC")
        ax.set_zlabel("t_hit [s]")
        ax.view_init(elev=26, azim=-58)
        ax.set_title("图1 三维：11 弹落点 + t_hit 曲面")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v10_plane_3d_2panel(dv, bc, T, pts, base):
    """图1 三维 + 同数据 2D 对照并排（评估"3D 是否真的更好"的直接材料）。"""
    fig = plt.figure(figsize=(13.6, 6.0))
    try:
        ax2 = fig.add_subplot(1, 2, 1)
        levels = np.arange(np.nanmin(T), np.nanmax(T) + 1.0, 1.0)
        cs = ax2.contourf(dv, bc, T, levels=levels, cmap="RdYlBu_r", extend="both")
        fig.colorbar(cs, ax=ax2, label="t_hit [s]")
        ax2.set_xlabel("ΔV [m/s]")
        ax2.set_ylabel("BC")
        ax2.set_title("2D 等时线", fontsize=11)
        ax3 = fig.add_subplot(1, 2, 2, projection="3d")
        Z = np.nan_to_num(T, nan=float(np.nanmean(T)))
        ax3.plot_surface(dv[None, :].repeat(len(bc), 0),
                         bc[:, None].repeat(len(dv), 1), Z,
                         cmap="RdYlBu_r", rstride=3, cstride=3, linewidth=0.05)
        ax3.set_xlabel("ΔV [m/s]")
        ax3.set_ylabel("BC")
        ax3.set_zlabel("t_hit [s]")
        ax3.view_init(elev=26, azim=-58)
        ax3.set_title("3D 曲面", fontsize=11)
        fig.suptitle("图1：2D vs 3D 并排")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v13_traj_preview_existing(d, base):
    """现有的 `figures.plot_traj_preview_3d`（真实目标航迹，**图3 的输入阶段预览**）。

    与 v02~v05 的差别：这是**仓库里已经在用的** 3D 函数，输入是 `PathSchedule`
    （运动学），坐标口径 `(x, z, 高度 y)`，还带多方位角分格能力。量它就是为了知道
    "已有 3D 路径的复现性与成本"，而不是另起炉灶。
    """
    from missile_sim import flightpath
    sch = flightpath.crank_beam(
        8.0, 70.0, 34.45833436027169, 90.0, speed_ms=300.0,
        g_crank=9.0, g_beam=9.0, react_delay_s=1.0)
    return figures.plot_traj_preview_3d(
        sch, p0=(50000.0, 10000.0, 0.0), duration_s=d["t_hit"],
        out_base=base, formats=FORMATS, azimuths=(30.0, 120.0), dpi=160)


def v11_bg_2d(be, ga, T, base):
    """基准：图2 的 β–γ 平面（2D）。"""
    fig, ax = plt.subplots(figsize=(8.8, 5.6))
    try:
        levels = np.arange(np.nanmin(T), np.nanmax(T) + 1.0, 1.0)
        cs = ax.contourf(be, ga, T, levels=levels, cmap="RdYlBu_r", extend="both")
        fig.colorbar(cs, ax=ax, label="t_hit [s]")
        ax.set_xlabel("β")
        ax.set_ylabel("γ")
        ax.set_title("图2 β–γ 平面（2D 基准）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v12_bg_3d_surface(be, ga, T, base):
    """图2 的第三维 t_hit → 3D 曲面。"""
    fig = plt.figure(figsize=(9.6, 6.8))
    try:
        ax = fig.add_subplot(111, projection="3d")
        # β–γ 的真实跨度可差 1~2 个量级：用真实跨度做 box_aspect，几何才不失真
        asp = figures._box_aspect(be, T.ravel(), ga)
        ax.plot_surface(be[None, :].repeat(len(ga), 0),
                        ga[:, None].repeat(len(be), 1),
                        np.nan_to_num(T, nan=float(np.nanmean(T))),
                        cmap="RdYlBu_r", rstride=2, cstride=2, linewidth=0.1)
        ax.set_box_aspect(asp)
        ax.set_xlabel("β")
        ax.set_ylabel("γ")
        ax.set_zlabel("t_hit [s]")
        ax.view_init(elev=26, azim=-58)
        ax.set_title("图2 三维：β–γ–t_hit 曲面")
        return _save(fig, base)
    finally:
        plt.close(fig)


# ------------------------------------------------------------------ 量测循环


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _variant_dir(arg: Path | None, env: str, default: Path) -> Path:
    """变体产物目录：**函数实参 > 环境变量 > 默认**。

    ⚠ 这里刻意不接受"模块级常量已经带了 `a/` 前缀"这种隐式约定（第一版
    `run_all(OUT / "a")` 就是这么写错的，产物落到 `out/a/a/`）。调用方给什么就是什么。
    """
    if arg is not None:
        return Path(arg)
    return Path(env) if env.strip() else Path(default)


def run_all(out_dir: Path | None = None) -> list:
    """跑全部变体，返回量测记录。

    产物目录只看 `MSIM_SPIKE_OUT`（`--cross` 的子进程用它换目录），否则默认 `OUT`。
    主进程要控制落点时**显式**传 `out_dir`。
    """
    import os as _os
    out_dir = _variant_dir(out_dir, _os.environ.get("MSIM_SPIKE_OUT", ""), OUT)
    figures.setup_style()
    out_dir.mkdir(parents=True, exist_ok=True)
    d = load_traj()
    dv, bc, T1 = load_plane_grid()
    pts = []
    live = json.loads((ROOT / "results" / "plane_default.json").read_text(encoding="utf-8"))
    for p in live.get("points", ()):
        bck = str(p["key"])
        row = [r for r in _rows(ROOT / "results" / "plane_default_cases.csv")
               if abs(float(r["dv_target"]) - float(p["dv"])) < 8.0]
        # 弹的真实 t_hit 不在 cases.csv 里（那是网格工况），这里用网格上最近格点的值标注
        if row:
            near = min(row, key=lambda r: abs(float(r["bc_target"]) - float(p["bc"])))
            th = str(near.get("t_hit_s", "")).strip()
            if th:
                pts.append({"label": p["label"], "dv": float(p["dv"]),
                            "bc": float(p["bc"]), "t_hit": float(th)})
    bg = load_bg_grid()

    cases = [
        ("v01_traj_plan_2d", lambda b: v1_traj_plan_2d(d, b)),
        ("v02_traj_3d", lambda b: v2_traj_3d(d, b)),
        ("v03_traj_3d_proj", lambda b: v3_traj_3d_proj(d, b)),
        ("v04_traj_3d_color_t", lambda b: v4_traj_3d_color_t(d, b)),
        ("v05_traj_3d_multi_azim", lambda b: v5_traj_3d_multi_azim(d, b)),
        ("v06_traj_alt_2d", lambda b: v6_traj_alt_2d(d, b)),
        ("v07_plane_2d", lambda b: v7_plane_2d(dv, bc, T1, b)),
        ("v08_plane_3d_surface", lambda b: v8_plane_3d_surface(dv, bc, T1, b)),
        ("v09_plane_3d_scatter", lambda b: v9_plane_3d_scatter(dv, bc, T1, pts, b)),
        ("v10_plane_3d_2panel", lambda b: v10_plane_3d_2panel(dv, bc, T1, pts, b)),
        ("v13_traj_preview_existing", lambda b: v13_traj_preview_existing(d, b)),
    ]
    if bg is not None:
        be, ga, T2 = bg
        cases.append(("v11_bg_2d", lambda b: v11_bg_2d(be, ga, T2, b)))
        cases.append(("v12_bg_3d_surface", lambda b: v12_bg_3d_surface(be, ga, T2, b)))

    results = []
    for name, fn in cases:
        base = out_dir / name
        t0 = time.perf_counter()
        paths1 = fn(base)
        dt1 = time.perf_counter() - t0
        h1 = {p.name: sha256(p) for p in paths1}
        t0 = time.perf_counter()
        paths2 = fn(base)                      # 同进程、同参数，**连出第二次**
        dt2 = time.perf_counter() - t0
        h2 = {p.name: sha256(p) for p in paths2}
        diff = [k for k in sorted(set(h1) | set(h2)) if h1.get(k) != h2.get(k)]
        results.append({
            "variant": name,
            "t_run1_s": round(dt1, 3),
            "t_run2_s": round(dt2, 3),
            "bytes": {k: (Path(base).with_name(k)).stat().st_size for k in sorted(h1)},
            "sha_run1": h1, "sha_run2": h2,
            "reproducible": not diff,
            "diff_formats": diff,
        })
    return results


def main() -> int:
    import argparse
    import os
    ap = argparse.ArgumentParser(description="matplotlib mplot3d 静态 3D 可行性 spike")
    ap.add_argument("--cross", action="store_true",
                    help="跨进程复现：两个子进程（PYTHONHASHSEED 不同；间隔 >1 s）各出一次并比对")
    ap.add_argument("--cross-dir", default="",
                    help="跨进程复现的落盘目录（给了就保留 crossA/crossB.json 当证据）")
    ap.add_argument("--json", default="", help="（内部用）把量测结果写到 JSON，不打印表")
    args = ap.parse_args()

    if args.json:
        res = run_all()
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return 0

    # 非 --json 的主进程：变体产物落 `OUT`（= out/a/），记录文件落 OUT_DATA
    res = run_all()
    print(f"{'variant':<28}{'t1[s]':>8}{'t2[s]':>8}{'png[kB]':>9}{'pdf[kB]':>9}{'svg[kB]':>9}{'repro':>7}")
    bad = 0
    for r in res:
        b = r["bytes"]
        k = lambda e: b.get(f"{r['variant']}.{e}", 0) / 1024.0            # noqa: E731
        print(f"{r['variant']:<28}{r['t_run1_s']:>8.2f}{r['t_run2_s']:>8.2f}"
              f"{k('png'):>9.1f}{k('pdf'):>9.1f}{k('svg'):>9.1f}"
              f"{'OK' if r['reproducible'] else 'DIFF':>7}")
        if not r["reproducible"]:
            bad += 1
            print(f"    !! 同进程不可复现格式：{r['diff_formats']}")
    total = sum(f.stat().st_size for f in OUT.glob("*") if f.is_file())
    print(f"\n样例产物总字节：{total / 1024.0 / 1024.0:.2f} MB（{len(res)} 变体 × {len(FORMATS)} 格式）")
    print(f"同进程不可复现变体数：{bad}/{len(res)}")
    (OUT_DATA / "a_report.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.cross:
        print("\n=== 跨进程复现（子进程 A 用当前 PYTHONHASHSEED；子进程 B 用 PYTHONHASHSEED=1）===")
        import shutil
        import subprocess
        import uuid
        tmp = args.cross_dir or (OUT.parent / f"cross_{uuid.uuid4().hex[:8]}")
        tmp = Path(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        for i, seed in enumerate(("random", "1")):
            env = dict(os.environ)
            if seed != "random":
                env["PYTHONHASHSEED"] = seed
            env["MSIM_SPIKE_OUT"] = str(tmp / f"run{i}_files")
            subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--json", str(tmp / f"cross{'A' if i == 0 else 'B'}.json")],
                           cwd=str(ROOT), env=env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            time.sleep(1.2)                     # 间隔 >1 s：防"因为太快才相同"的假象
        a = json.loads((tmp / "crossA.json").read_text(encoding="utf-8"))
        b = json.loads((tmp / "crossB.json").read_text(encoding="utf-8"))
        cross_bad = 0
        for ra, rb in zip(a, b):
            diff = [k for k in sorted(set(ra["sha_run1"]) | set(rb["sha_run1"]))
                    if ra["sha_run1"].get(k) != rb["sha_run1"].get(k)]
            print(f"{ra['variant']:<28}{'OK' if not diff else 'DIFF':>7}"
                  + ("" if not diff else f"   差异格式：{diff}"))
            if diff:
                cross_bad += 1
        print(f"跨进程不一致变体数：{cross_bad}/{len(a)}（差异说明 mplot3d 的 z 排序/图元顺序不稳）")
        if args.cross_dir:
            # 两个子进程的**整份产物**在这个目录下也是完整的；只留 sha256 记录，产物删掉
            for i in range(2):
                shutil.rmtree(tmp / f"run{i}_files", ignore_errors=True)
            print(f"两个子进程的 sha256 记录留在 {tmp}（{len(a)} 变体 × 3 格式）")
        else:
            print(f"子进程产物目录（已删）：{tmp}")
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

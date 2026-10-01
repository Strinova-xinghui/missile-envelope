# -*- coding: utf-8 -*-
"""spike：从三维标量场提等值面 + mplot3d 出图 + 字节可复现 + 可读性量测。

跑法（在 worktree 根）::

    $env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
    python spikes\\bg3d\\bg3d_iso.py                    # 提面 + 出图 + 打数字表
    python spikes\\bg3d\\bg3d_iso.py --cross --cross-dir spikes\\bg3d\\out   # 另起进程再出一次，比 sha256

产物（`spikes/bg3d/out/iso/`）：
  `iso_surfaces.json`（几何：顶点/三角形，供交互前端与取证）、
  `iso_report.json`（每个层级的三角形数/面积/面上 t_hit 散布/提取耗时）、
  `v*/` 变体图（PNG/PDF/SVG）。

口径两件事在这里**同时量**：
  (a) 真等值面 `marching_tetrahedra`：面上 t_hit 散布 ≈ 插值误差；
  (b) 把 ΔV 钉死那一层的二维等时线**沿 ΔV 拉成柱面**：面上 t_hit 散布与场跨度同量级。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib                                     # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
import numpy as np                                    # noqa: E402
from mpl_toolkits.mplot3d import proj3d               # noqa: E402

from missile_sim import bg, bg3d, figures, grid as grid_mod   # noqa: E402

OUT = ROOT / "spikes" / "bg3d" / "out"
ISO = OUT / "iso"
FORMATS = ("png", "pdf", "svg")

#: 要提的等时面层级（s）。选在三维场的跨度内，且**跨过**"低 ΔV 才算得出"的边界。
LEVELS = (42.0, 44.0, 46.0, 48.0, 50.0, 52.0)

#: 每张面的颜色（红→蓝，越靠后 t_hit 越大）。
COLORS = ((0.85, 0.30, 0.10), (0.93, 0.62, 0.05), (0.35, 0.65, 0.25),
          (0.10, 0.55, 0.65), (0.15, 0.35, 0.80), (0.45, 0.25, 0.65))

#: PL-12 的权威 ΔV（= 图2 钉死的那个值），用来当"口径 2"的基准层。
DV_PIN = 932.5697486487783


def load_scan(name: str = "fine") -> bg3d.Bg3Scan:
    path = OUT / f"scan_{name}.json"
    if not path.is_file():
        raise SystemExit(f"缺 {path.relative_to(ROOT)}；先跑 spikes\\bg3d\\bg3d_scan.py --grid {name}")
    rec = json.loads(path.read_text(encoding="utf-8"))
    return bg3d.scan_from_record(rec)


# ------------------------------------------------------------------ 提面


def extract(scan: bg3d.Bg3Scan, levels=LEVELS, *, orient: bool = True) -> dict:
    """真等值面 + 口径 2 的柱面，外加每个面的量测。

    口径 2 的层级**只能从"被钉死那一层"里取**（那一层的 t_hit 只覆盖 43~47 s），
    所以两边取**交集**再比 —— 拿一个那层根本没有的层级去拉，只会得到"最接近的另一条线"，
    图上看着一样、语义已经换了。
    """
    g = scan.grid
    i0 = int(np.argmin(np.abs(np.asarray(g.dv) - DV_PIN)))
    base_dv = float(g.dv[i0])
    base_levels = grid_mod.iso_levels(scan.t_hit[i0], 1.0)
    t0 = time.perf_counter()
    surfaces = bg3d.marching_tetrahedra(scan.t_hit, levels, grid=g, orient=orient)
    dt = time.perf_counter() - t0
    for i, s in enumerate(surfaces):
        s.color = COLORS[i % len(COLORS)]
    used, cyls = [], []
    t1 = time.perf_counter()
    for lev in levels:
        hit = [lv for lv in base_levels if abs(lv - float(lev)) < 0.5]
        if not hit:
            continue
        try:
            c = bg3d.extrude_layer(scan, level=hit[0], base_dv=base_dv)
        except ValueError:
            continue
        c.color = COLORS[len(cyls) % len(COLORS)]
        cyls.append(c)
        used.append({"req": float(lev), "actual": float(c.level), "n_seg": c.n_seg})
    dt_cyl = time.perf_counter() - t1
    return {"iso": surfaces, "cyl": cyls, "base_dv": base_dv, "base_levels": base_levels,
            "cyl_used": used,
            "timing": {"iso_s": dt, "cyl_s": dt_cyl, "n_iso": len(surfaces),
                       "n_cyl": len(cyls)}}


def report(scan: bg3d.Bg3Scan, surfaces: list, timing: dict, extra: dict | None = None) -> dict:
    rows = []
    for s in surfaces:
        sp = bg3d.iso_spread(scan, s)
        rows.append({"kind": s.kind, "level": s.level, "n_tri": s.n_tri,
                     "area": bg3d.surface_area(s.vertices, s.triangles),
                     "n_vert": int(len(s.vertices)), "n_seg": s.n_seg,
                     "t_min": sp.get("t_min"), "t_max": sp.get("t_max"),
                     "spread": sp.get("spread"), "spread_rel": sp.get("spread_rel"),
                     "field_span": sp.get("field_span"), "bias": sp.get("bias"),
                     "base_dv": s.base_dv})
    # 固定 (β, γ) 时 t_hit 对 ΔV 的依赖（柱面为什么不是等值面）
    dep = [bg3d.dv_dependence(scan, beta=r.beta, gamma=r.gamma)
           for r in (bg.rows(["PL-12"])[0], bg.rows(["R-77"])[0])]
    out = {"scan": scan.summary(), "timing": timing, "surfaces": rows,
           "dv_dependence": dep, "levels": list(LEVELS),
           "dv_linearity": bg3d.dv_linearity(scan), "dv_pin": DV_PIN}
    out.update(extra or {})
    return out


# ------------------------------------------------------------------ 出图


def _save(fig, base: Path, formats=None) -> list:
    """`formats` 不给就按**变体名**（= `base.name`）查 `VARIANT_FORMATS`。"""
    if formats is None:
        formats = VARIANT_FORMATS.get(base.name, ("png",))
    paths = figures.save_formats(fig, base, formats=formats)
    plt.close(fig)
    return paths


def _box(ax, scan: bg3d.Bg3Scan, *, aspect: str = "true") -> None:
    """坐标轴与外框。

    `aspect="true"`：按**三轴真实跨度**给相对长度 —— β 1200 kg/m²、γ 52 kg/m²、ΔV 500 m/s
    量纲互不相同，于是盒子被压成一张**薄饼**，六张近似平行的等值面会叠成一块板
    （`v3_six` 就是这个下场）。`aspect="cube"` 把三根轴画成等长（刻度仍是真值），
    这是量纲不同轴的标准做法，也是这一族面唯一能看清楚的画法。
    """
    g = scan.grid
    ax.set_xlim(g.beta[0], g.beta[-1])
    ax.set_ylim(g.gamma[0], g.gamma[-1])
    ax.set_zlim(g.dv[0], g.dv[-1])
    if aspect == "cube":
        ax.set_box_aspect((1.0, 1.0, 1.0))
    else:
        ax.set_box_aspect(figures._box_aspect(np.array(g.beta), np.array(g.gamma),
                                              np.array(g.dv)))
    ax.set_xlabel("β [kg/m²]")
    ax.set_ylabel("γ [kg/m²]")
    ax.set_zlabel("ΔV [m/s]")


def _mesh(ax, s: bg3d.Surface, *, alpha: float = 1.0, shade: bool = True):
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    tris = s.vertices[s.triangles]
    # matplotlib 3.11 起 `shade=True` 必须给 `facecolors=`（复数）；而 `edgecolors="none"`
    # 会被 `_shade_colors` 解析成空数组（(0,4) 广播失败），所以靠 `linewidth=0` 去边。
    col = Poly3DCollection(tris, alpha=alpha, facecolors=[s.color or (0.5, 0.5, 0.5)],
                           linewidth=0.0, shade=shade)
    ax.add_collection3d(col)
    return col


def _pin_layer(ax, scan: bg3d.Bg3Scan, *, alpha=0.35):
    """把"图2 钉死的那一层"画成半透明薄片，直观说明 ΔV 是**新加**的那根轴。"""
    i = int(np.argmin(np.abs(np.asarray(scan.grid.dv) - DV_PIN)))
    dv = scan.grid.dv[i]
    B, G = np.meshgrid(np.asarray(scan.grid.beta), np.asarray(scan.grid.gamma))
    Z = np.full_like(B, dv)
    ax.plot_surface(B, G, Z, color="#9aa5b1", alpha=alpha, rstride=1, cstride=1,
                    linewidth=0, antialiased=False)
    return dv


def v1_one(scan, surfaces, base):
    """1 张面（不透明）—— "最少要几张"的下界。"""
    fig = plt.figure(figsize=(9.4, 6.6))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan)
        _mesh(ax, surfaces[0])
        ax.view_init(elev=24, azim=-62)
        ax.set_title(f"图2+ΔV 三维：t_hit = {surfaces[0].level:g} s 等值面（1 张）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v2_three(scan, surfaces, base, *, alpha=1.0, n=3, title=None):
    fig = plt.figure(figsize=(9.4, 6.6))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan)
        for s in surfaces[:n]:
            _mesh(ax, s, alpha=alpha)
        ax.view_init(elev=24, azim=-62)
        ax.set_title(title or f"{n} 张等值面（{'半透明' if alpha < 1 else '不透明'}）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v3_six(scan, surfaces, base):
    return v2_three(scan, surfaces, base, n=6,
                    title="6 张等值面（不透明）—— 糊不糊看这张")


def v4_two_flavors(scan, surfaces, cyLs, base):
    """口径对比：左 = 真等值面，右 = 同层级的"等时线立起来"的柱面（各取前 2 张）。"""
    fig = plt.figure(figsize=(13.4, 6.4))
    try:
        for k, (title, group) in enumerate((("(a) 真等值面：t_hit 的等值面", surfaces),
                                            ("(b) 口径 2：把二维等时线沿 ΔV 拉成柱面",
                                             cyLs))):
            ax = fig.add_subplot(1, 2, k + 1, projection="3d")
            _box(ax, scan)
            for s in group[:2]:
                _mesh(ax, s, alpha=0.85)
            ax.view_init(elev=24, azim=-62)
            ax.set_title(title)
        fig.suptitle("两种「等时面」口径长得很像，但 (b) 不是 t_hit 的等值面")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v5_layers_and_pin(scan, surfaces, base):
    """3 张真等值面 + 图2 钉死的那一层薄片 + 弹池散点。"""
    fig = plt.figure(figsize=(9.6, 6.8))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan)
        dv = _pin_layer(ax, scan)
        for s in surfaces[:3]:
            _mesh(ax, s, alpha=0.9)
        rows_ = bg.rows(None)
        ax.scatter([r.beta for r in rows_], [r.gamma for r in rows_], [r.dv for r in rows_],
                   s=26, c="#111827", depthshade=False, label="弹池 11 型")
        ax.legend(fontsize=8, loc="upper left")
        ax.view_init(elev=24, azim=-62)
        ax.set_title(f"3 张等值面 + 图2 钉死的那一层（ΔV={dv:.0f} m/s 薄片）+ 弹池")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v6_slices(scan, surfaces, base):
    """剖视：一张真等值面 + 三个 ΔV 切片上的 t_hit 云图（看 ΔV 依赖有多大）。"""
    fig = plt.figure(figsize=(10.4, 6.6))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan, aspect="cube")
        g = scan.grid
        B, G = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma))
        idx = [0, len(g.dv) // 2, len(g.dv) - 1]
        lo = float(np.nanmin(scan.t_hit))
        hi = float(np.nanmax(scan.t_hit))
        for i in idx:
            Z = scan.t_hit[i]
            fc = (Z - lo) / (hi - lo)
            ax.plot_surface(B, G, np.full_like(B, g.dv[i]), facecolors=plt.cm.RdYlBu_r(fc),
                            rstride=1, cstride=1, linewidth=0, antialiased=False,
                            alpha=0.95)
        _mesh(ax, surfaces[0], alpha=0.9)
        ax.view_init(elev=22, azim=-64)
        ax.set_title(f"ΔV 切片 ΔV={g.dv[idx[0]]:.0f}/{g.dv[idx[1]]:.0f}/{g.dv[idx[2]]:.0f} m/s"
                     f"（颜色 = t_hit {lo:.1f}~{hi:.1f} s）+ 1 张真等值面")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v7_2panel(scan, surfaces, base):
    """左：ΔV=钉死层的 2D 等时线（既有口径）；右：三维 3 张面。"""
    fig = plt.figure(figsize=(13.0, 5.8))
    try:
        g = scan.grid
        ax = fig.add_subplot(1, 2, 1)
        i = int(np.argmin(np.abs(np.asarray(g.dv) - DV_PIN)))
        t2 = scan.t_hit[i]
        lv = np.arange(np.nanmin(t2), np.nanmax(t2) + 0.5, 1.0)
        cs = ax.contourf(np.asarray(g.beta), np.asarray(g.gamma), t2, levels=lv,
                         cmap="RdYlBu_r", extend="both")
        ax.contour(np.asarray(g.beta), np.asarray(g.gamma), t2, levels=lv[::2],
                   colors="#1f2933", linewidths=0.7)
        fig.colorbar(cs, ax=ax, label="t_hit [s]")
        ax.set_xlabel("β [kg/m²]")
        ax.set_ylabel("γ [kg/m²]")
        ax.set_title(f"既有口径：ΔV 钉死在 {g.dv[i]:.0f} m/s 的 β–γ 平面")
        ax.grid(alpha=0.2)

        ax3 = fig.add_subplot(1, 2, 2, projection="3d")
        _box(ax3, scan)
        for s in surfaces[:3]:
            _mesh(ax3, s, alpha=0.9)
        ax3.view_init(elev=24, azim=-62)
        ax3.set_title("新口径：ΔV 解开的 3 张等值面")
        fig.suptitle("同一份扫描数据的两种看法")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v8_cube_six(scan, surfaces, base, *, alpha=0.45, n=6, elev=26.0, azim=-58.0):
    """**推荐画法**：等长三轴的立方体 + 半透明，看这一族面到底叠成什么样。"""
    fig = plt.figure(figsize=(9.8, 7.0))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan, aspect="cube")
        for s in surfaces[:n]:
            _mesh(ax, s, alpha=alpha)
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(f"{n} 张等值面 · 等长三轴 · 半透明 α={alpha}"
                     "（同一族面近似平行，靠 ΔV 分层）")
        return _save(fig, base)
    finally:
        plt.close(fig)


def v9_cube_cutaway(scan, surfaces, base, *, alpha=0.5):
    """立方体 + 剖切：只留 ΔV 靠上的一半，切面正好露出"等值面在 ΔV 上怎么倾斜"。"""
    fig = plt.figure(figsize=(9.8, 7.0))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan, aspect="cube")
        for s in surfaces[:4]:
            _mesh(ax, s, alpha=alpha)
        g = scan.grid
        i = int(np.argmin(np.abs(np.asarray(g.dv) - DV_PIN)))
        B, G = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma))
        ax.plot_surface(B, G, np.full_like(B, g.dv[i]), color="#7b8794", alpha=0.28,
                        rstride=1, cstride=1, linewidth=0, antialiased=False)
        ax.view_init(elev=26, azim=-58)
        ax.set_title(f"4 张等值面 + ΔV={g.dv[i]:.0f} m/s 剖切面（图2 钉死的那一层）")
        return _save(fig, base)
    finally:
        plt.close(fig)


VARIANTS = {"v1_one": (v1_one, 1), "v2_three": (v2_three, 3), "v3_six": (v3_six, 6),
            "v4_two_flavors": (v4_two_flavors, 2), "v5_layers_and_pin": (v5_layers_and_pin, 3),
            "v6_slices": (v6_slices, 1), "v7_2panel": (v7_2panel, 3),
            "v8_cube_six": (v8_cube_six, 6), "v9_cube_cutaway": (v9_cube_cutaway, 4)}

#: 每个变体出哪些格式。**等值面网格的 SVG 会爆炸**（几千个面片逐个写成 path），
#: 所以只有"面少"的那几个出三格式（它们的 sha256 就是字节可复现的取证口径），
#: 其余只出 PNG（可读性取证用 160 dpi 的位图就够）。
VARIANT_FORMATS = {
    "v1_one": ("png", "pdf", "svg"),
    "v2_three": ("png", "pdf", "svg"),
    "v3_six": ("png", "svg"),
    "v4_two_flavors": ("png",),
    "v5_layers_and_pin": ("png",),
    "v6_slices": ("png",),
    "v7_2panel": ("png", "svg"),
    "v8_cube_six": ("png", "pdf", "svg"),
    "v9_cube_cutaway": ("png",),
}


# ------------------------------------------------------------------ 可读性量测


def occlusion(scan, surfaces, *, elev=24.0, azim=-62.0, res=(220, 170)) -> dict:
    """把每张面采样投影到屏幕，用 z-buffer 数"谁看得见谁" —— "糊成一团"的可判定代理。

    * `cover`：面能看见的格子数 / 该面自己的采样格子数（1.0 = 一点没被挡）；
    * `overlap_frac`：≥2 张面落在同一格的格子占比（越大越糊）。

    深度的正负号**当场标定**：mplot3d 的 `proj_transform` 给出的 `tz` 哪个方向是"靠前"
    取决于视角，写死会把"谁挡谁"判反（而图看起来一样）。
    """
    fig = plt.figure(figsize=(9.4, 6.6))
    try:
        ax = fig.add_subplot(111, projection="3d")
        _box(ax, scan)
        ax.view_init(elev=elev, azim=azim)
        fig.canvas.draw()
        M = ax.get_proj()
        # 标定：沿 +x 挪一点，看 tz 变大还是变小 —— 相机方位的 x 分量恒为正
        far = proj3d.proj_transform(0.0, 0.0, 0.0, M)[2]
        near = proj3d.proj_transform(1.0, 0.0, 0.0, M)[2]
        sign = 1.0 if near >= far else -1.0
        pts = []
        for s in surfaces:
            V = s.vertices
            cen = V[s.triangles].mean(axis=1)
            sample = np.concatenate([V, cen], axis=0)
            tx, ty, tz = proj3d.proj_transform(sample[:, 0], sample[:, 1], sample[:, 2], M)
            pts.append((np.column_stack([tx, ty, sign * tz]), sample))
        allpts = np.concatenate([p[0] for p in pts], axis=0)
        u0, u1 = float(allpts[:, 0].min()), float(allpts[:, 0].max())
        v0, v1 = float(allpts[:, 1].min()), float(allpts[:, 1].max())
        du = max(u1 - u0, 1e-12)
        dv = max(v1 - v0, 1e-12)
        w, h = res
        depth = np.full((h, w), -np.inf)
        for P, _s in pts:
            iu = np.clip(((P[:, 0] - u0) / du * (w - 1)).astype(int), 0, w - 1)
            iv = np.clip(((P[:, 1] - v0) / dv * (h - 1)).astype(int), 0, h - 1)
            np.maximum.at(depth, (iv, iu), P[:, 2])
        seen = np.zeros((len(surfaces), h, w), dtype=bool)
        owner = np.full((h, w), -1, dtype=int)
        for n, (P, _s) in enumerate(pts):
            iu = np.clip(((P[:, 0] - u0) / du * (w - 1)).astype(int), 0, w - 1)
            iv = np.clip(((P[:, 1] - v0) / dv * (h - 1)).astype(int), 0, h - 1)
            seen[n][iv, iu] = True
            win = P[:, 2] >= depth[iv, iu] - 1e-12
            owner[iv[win], iu[win]] = n
        out = {}
        for n in range(len(surfaces)):
            cells = int(seen[n].sum())
            vis = int((owner == n).sum())
            out[n] = {"cells": cells, "visible": vis,
                      "cover": (vis / cells) if cells else float("nan")}
        total_cells = int((owner >= 0).sum())
        multi = int(((seen.sum(axis=0) >= 2) & (owner >= 0)).sum())
        return {"res": [w, h], "cover": out, "n_cells": total_cells,
                "overlap_cells": multi, "depth_sign": sign,
                "overlap_frac": (multi / total_cells) if total_cells else float("nan"),
                "elev": elev, "azim": azim}
    finally:
        plt.close(fig)


# ------------------------------------------------------------------ 主

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(p) -> str:
    """相对仓库根的路径（跨进程比对会写到临时目录，那时只能给绝对路径）。"""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(Path(p).resolve())


def run_all(out_dir: Path, *, scan_name: str = "fine", twice: bool = False) -> dict:
    out_dir = Path(out_dir).resolve()
    scan = load_scan(scan_name)
    got = extract(scan)
    iso, cyl = got["iso"], got["cyl"]
    rep = report(scan, iso + cyl, got["timing"],
                 {"base_dv": got["base_dv"], "base_levels": got["base_levels"],
                  "cyl_used": got["cyl_used"]})
    ISO.mkdir(parents=True, exist_ok=True)
    # 几何（给交互前端与取证）：只存两三张面，控制体积
    payload = {"schema": 1, "kind": "bg3d-iso", "axes": {"beta": list(scan.grid.beta),
               "gamma": list(scan.grid.gamma), "dv": list(scan.grid.dv)},
               "ranges": {"beta": [scan.grid.beta[0], scan.grid.beta[-1]],
                          "gamma": [scan.grid.gamma[0], scan.grid.gamma[-1]],
                          "dv": [scan.grid.dv[0], scan.grid.dv[-1]]},
               "levels": list(LEVELS), "base_dv": got["base_dv"],
               "surfaces": [s.as_dict(digits=4) for s in iso],
               "cylinders": [s.as_dict(digits=4) for s in cyl],
               "meta": dict(scan.summary(), grid=list(scan.grid.shape),
                            hit_rate=scan.hit_rate, dv_pin=DV_PIN)}
    (out_dir / "iso_surfaces.json").write_text(json.dumps(payload, ensure_ascii=False),
                                               encoding="utf-8")
    # **入库的那个小样**：1 张面 + 1 张柱面、3 位小数（≈0.29 MB）—— 全量 payload 2.1 MB 不入库，
    # 它由本脚本 1 秒重出（`spikes/fig3d` 的 `data.slim.json` 也是这个路数）。
    (out_dir / "iso_surfaces_sample.json").write_text(json.dumps(
        {"schema": 1, "kind": "bg3d-iso-sample", "axes": payload["axes"],
         "ranges": payload["ranges"], "levels": list(LEVELS), "base_dv": got["base_dv"],
         "surfaces": [iso[0].as_dict(digits=3)] if iso else [],
         "cylinders": [cyl[0].as_dict(digits=3)] if cyl else [],
         "full": "iso_surfaces.json（全量，未入库）由 spikes/bg3d/bg3d_iso.py 重出"},
        ensure_ascii=False), encoding="utf-8")

    variants = {}
    for name, (fn, _n) in VARIANTS.items():
        base = out_dir / name
        t0 = time.perf_counter()
        paths = fn(scan, iso, cyl, base) if name == "v4_two_flavors" else fn(scan, iso, base)
        dt = time.perf_counter() - t0
        variants[name] = {"s": dt, "bytes": {p.suffix.lstrip("."): p.stat().st_size
                                             for p in paths},
                          "sha": {p.suffix.lstrip("."): sha256(p) for p in paths},
                          "paths": [_rel(p) for p in paths]}
    if twice:
        # **同进程连出两次**：matplotlib 的 id 盐若没钉死，这里第一个就会红
        again = {}
        for name, (fn, _n) in VARIANTS.items():
            base = out_dir / name
            first = variants[name]["sha"]
            paths = fn(scan, iso, cyl, base) if name == "v4_two_flavors" else fn(scan, iso, base)
            again[name] = {"sha": {p.suffix.lstrip("."): sha256(p) for p in paths},
                           "first": first}
        rep["same_process"] = {n: bool(again[n]["sha"] == variants[n]["sha"])
                               for n in VARIANTS}
        rep["same_process_sha2"] = {n: again[n]["sha"] for n in VARIANTS}
        variants = {n: {**v, "bytes": {e: (out_dir / f"{n}.{e}").stat().st_size
                                       for e in v["bytes"]}}
                    for n, v in variants.items()}
        rep["variants"] = variants
    counts = {}
    for n, (_fn, k) in VARIANTS.items():
        counts[n] = occlusion(scan, iso[:max(k, 1)])
    rep["variants"] = variants
    rep["occlusion"] = counts
    rep["iso_payload_bytes"] = (out_dir / "iso_surfaces.json").stat().st_size
    rep["out_dir"] = _rel(out_dir)
    # ⚠ 写**本次运行的目录**，不是固定的 `out/iso`：跨进程比对那次跑在临时目录里，
    # 若固定写 `out/iso`，入库的那份报告会被"路径指向 .tmp_test、耗时也换成那次"的版本覆盖。
    (out_dir / "iso_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="β–γ–ΔV 等值面 spike")
    ap.add_argument("--out", default=None)
    ap.add_argument("--scan", default="fine", choices=("quick", "coarse", "fine"))
    ap.add_argument("--cross", action="store_true", help="只出变体并打印 sha256（给跨进程比对）")
    ap.add_argument("--cross-dir", default=None, help="跨进程比对时写哪个目录")
    ap.add_argument("--same-process", action="store_true",
                    help="同进程把每个变体连出两次并比对 sha256（钉死 ID 盐/元数据时间戳）")
    ap.add_argument("--json", default=None, help="把本进程的记录写到这个文件")
    args = ap.parse_args()

    figures.setup_style()
    out_dir = Path(args.cross_dir) if args.cross_dir else (
        Path(args.out) if args.out else (OUT / "iso"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = run_all(out_dir, scan_name=args.scan, twice=args.same_process)
    if args.json:
        Path(args.json).write_text(json.dumps(
            [{"variant": k, "sha": v["sha"], "bytes": v["bytes"], "s": v["s"]}
             for k, v in rep["variants"].items()], ensure_ascii=False), encoding="utf-8")
    if args.same_process:
        print("=== 同进程连出两次 ===")
        for k, ok in rep["same_process"].items():
            print(f"  {k:18s} {'一致 ✓' if ok else '不一致 ✗'}  "
                  + " ".join(f"{e}:{h[:12]}" for e, h in sorted(rep["variants"][k]["sha"].items())))
    print("=== 提取 ===")
    print(f"网格 {rep['scan']['shape']} = {rep['scan']['n_cases']} 工况，"
          f"命中 {rep['scan']['n_hit']}（{100 * rep['scan']['hit_rate']:.1f}%）；"
          f"提面 {rep['timing']['iso_s'] * 1000:.1f} ms（{rep['timing']['n_iso']} 张）、"
          f"柱面 {rep['timing']['cyl_s'] * 1000:.1f} ms（{rep['timing']['n_cyl']} 张）")
    print(f"口径 2 的基准层：ΔV={rep['base_dv']:.0f} m/s（PL-12 权威 ΔV={rep['dv_pin']:.1f} 的最近格点），"
          f"该层自带层级 {rep['base_levels']}；取交集后用了 "
          f"{[(u['req'], u['actual']) for u in rep['cyl_used']]}")
    print("=== 面 ===")
    for r in rep["surfaces"]:
        print(f"  {r['kind']:8s} level={r['level']:5.1f} n_tri={r['n_tri']:6d} "
              f"area={r['area']:12.3f} t∈[{r['t_min']:.3f},{r['t_max']:.3f}] "
              f"spread={r['spread']:.4f} ({100 * (r['spread_rel'] or 0):.3f}% of span)")
    print("=== ΔV 线性体检（t_hit ≈ a(β,γ) + b·ΔV）===")
    lin = rep["dv_linearity"]
    print(f"  {lin['n_col']} 列：斜率 {lin['slope_mean']:.5f} ± {lin['slope_std']:.5f} s/(m/s)"
          f"（相对散布 {100 * lin['slope_rel_spread']:.1f}%），"
          f"R² 中位 {lin['r2_median']:.4f}（最小 {lin['r2_min']:.4f}），"
          f"残差 RMS {lin['rms_resid_s']:.3f} s（跨度 {lin['t_range_s'][1] - lin['t_range_s'][0]:.1f} s）")
    print("=== ΔV 依赖（固定 β、γ）===")
    for d in rep["dv_dependence"]:
        print(f"  β={d['beta']:.0f} γ={d['gamma']:.1f}: t {d['t_low']:.2f}→{d['t_high']:.2f} s "
              f"跨度 {d['span']:.2f} s，斜率 {d['slope_s_per_ms']:.4f} s/(m/s)")
    print("=== 变体（时间 / 字节）===")
    for k, v in rep["variants"].items():
        print(f"  {k:18s} {v['s']:5.2f} s  " +
              "  ".join(f"{e}:{b}B" for e, b in v["bytes"].items()))
    print("=== 可读性（投影 z-buffer，1.0 = 完全没被挡）===")
    for k, oc in rep["occlusion"].items():
        covs = ", ".join(f"{v['cover']:.2f}" for _n, v in sorted(oc["cover"].items()))
        print(f"  {k:18s} 面覆盖 [{covs}]  互相遮挡格占比 {oc['overlap_frac']:.3f}"
              f"（{oc['n_cells']} 格）")
    print(f"几何 payload: {rep['iso_payload_bytes']} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

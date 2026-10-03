# -*- coding: utf-8 -*-
"""β–γ–ΔV 三维标量场：三轴扫描 + **自己写的** marching tetrahedra 等值面。

## 为什么要这一层

图2 把 **ΔV 钉死**（`results/bg_default.json` → `scan.dv_pin_ms = 932.5697`，即 PL-12 的
权威 ΔV），只扫 (β, γ)，靠 `cx_scale` / `cxaoa_scale` 去命中目标 —— 所以那张图上
`dv_measured_ms` 是**结果**，不是输入轴。要让 ΔV 成为第三根轴，必须把它**解开**，
再从一个三维标量场 `t_hit(β, γ, ΔV)` 里提**真等值面**。

三根轴在 `Scaling` 上是**可逆参数化**（推导见 `bg.cxaoa_scale_for()` 与 `docs/BETA-GAMMA.md` §4.1）：

    ΔV  → `thrust_scale` = ΔV / ΔV_blk                … **严格只动这一项**
    β   → `cx_scale`     = β_blk / β                  … β 变小 ⇒ 阻力系数变大
    γ   → `cx_scale · cxaoa_scale` = γ / γ_blk        … 改 β 时 `cxaoa_scale` 按 1/cx_scale
                                                       联动，把 γ 顶住（两轴由此解耦）

也就是说 `(thrust_scale, cx_scale, cx_scale·cxaoa_scale) ↔ (ΔV, β, γ)` 一一对应：
(β, γ) 的那一面（ΔV = 某一层）就是图2 的定义域，ΔV 是第三根**真正独立**的轴。
`axis_effects()` 把这三条不变量量出来，`tests/test_bg3d_spike.py` 钉住 —— 串轴会让
"等值面"不再是任何单一物理量的等值面，而图看起来完全正常。

`bg.scaling_for(point, metrics, beta=…, gamma=…, dv=…)` 本来就收这三个关键字，
本模块只是给它们配上网格、扫描与几何提取。**`engine.py` / `bg.py` / `solver.py` 一个字没改。**

## 零新依赖（这条是硬的）

等值面提取**不用 scipy / scikit-image**：`marching_cubes` 在 skimage 里，而本仓库连
`pyproject.toml` 都没有、分发是"免安装压缩包"（`make_dist.py`），多一个二进制依赖
（scipy 在本机 wheel ≈ 40 MB，还带 BLAS/OpenMP 运行时）会直接改变分发形态。
所以这里手写 **marching tetrahedra**：一个立方体沿主对角线 0–7 拆成 6 个四面体
（Kuhn 分解），四面体只有 16 种符号组合，三/四个交点**一定共面**，不存在 marching cubes
那 256 项表上的鞍点歧义。代价是三角形更多，收益是每个三角面的三个顶点都在同一条
线性插值边上、面片不会互相穿插（`_order_quad` 保证四边形沿环序拆）。

⚠ 本模块**不许**出现 `import scipy` / `import skimage`（`tests/test_bg3d_spike.py` 会扫源文本）。

## 与 2D 层的口径一致性

* 网格沿**向内对齐**的步长取（复用 `grid.arange_inclusive`），与 `grid.make_grid` 同款；
* `t_hit` 立方体形状 `(n_dv, n_gamma, n_beta)`，**未命中 = `nan`**（不许用 0 代）；
* 每层 (β, γ) 的子网格顺序 = `[(β, γ) for γ in gammas for β in betas]`，
  即 `divmod(k, len(beta)) → (i_gamma, i_beta)`，与 `grid.t_hit_matrix` 完全一致。

## 两种"等时面"口径（**语义不同，别混**）

1. `marching_tetrahedra()`：真等值面 —— `t_hit = const` 的等值面，面上每点 t_hit ≈ const
   （差别只剩线性插值误差；实测相对场跨度 < 1%）。
2. `extrude_isolines()`：把 **ΔV 被钉死那一层**的二维等时线沿 ΔV 拉成柱面。生成成本几乎为零，
   但**不表示** t_hit 对 ΔV 的依赖：同一根 (β, γ) 柱线上 ΔV 从 600 走到 1100 时
   t_hit 会变好几秒，也就是柱面**不是**等值面。`iso_spread()` / `dv_dependence()`
   就是把这个差别量出来的口径。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from . import bg, grid as grid_mod, pool
from .engine import Engine
from .spec import PlaneGrid, Scene, Scaling

#: 立方体 8 个角的局部编号：`bit0 = β, bit1 = γ, bit2 = ΔV`。
_CORNERS = tuple((i & 1, (i >> 1) & 1, (i >> 2) & 1) for i in range(8))

#: Kuhn 六四面体分解（都共用主对角线 0–7）；每个四面体体积都是 1/6 立方体。
_TETS = ((0, 1, 3, 7), (0, 1, 5, 7), (0, 4, 5, 7),
         (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 6, 7))

#: 四面体的 6 条棱（局部角编号对，恒 `a < b`）。
_TET_EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _order_quad(cut: tuple, mask: int) -> tuple:
    """4 个交点 → **环序**（沿四面体棱的相邻关系走一圈）。

    只按 `_TET_EDGES` 里的先后放下 4 个点会拼出"蝴蝶结"（两个三角形互相穿插、
    总面积虚高）。这里的排序是：从一条棱的"内侧"端点出发，沿着共享顶点一路走回起点。
    """
    start = None
    for i, (a, b) in enumerate(cut):
        if (mask >> a) & 1:
            start, cur = i, b
            break
        if (mask >> b) & 1:
            start, cur = i, a
            break
    if start is None:                                 # 全在外侧 ⇒ 不可能有 4 个交点
        raise AssertionError("四面体切面的 4 条棱没有内侧端点")
    order = [start]
    remaining = set(range(len(cut))) - {start}
    while remaining:
        for j in sorted(remaining):
            u, v = cut[j]
            if u == cur:
                order.append(j)
                remaining.discard(j)
                cur = v
                break
            if v == cur:
                order.append(j)
                remaining.discard(j)
                cur = u
                break
        else:
            raise AssertionError(f"四面体切面不构成环：cut={cut} mask={mask}")
    return tuple(order)


def _tet_tri_table() -> tuple:
    """16 种符号组合 → 三角形；元素是**交点编号三元组**（编号 = `cut` 里的位置）。

    不抄现成的 marching tetrahedra 表，直接由"哪些棱被切"推出来，所以表本身可被测试验证：
    3 个交点 ⇒ 一个三角形；4 个交点 ⇒ 沿 `_order_quad` 的环序拆两个三角形。
    """
    table = []
    for mask in range(16):
        cut = tuple(e for e in _TET_EDGES if ((mask >> e[0]) & 1) != ((mask >> e[1]) & 1))
        if len(cut) == 3:
            table.append(((0, 1, 2),))
        elif len(cut) == 4:
            q = _order_quad(cut, mask)
            table.append(((q[0], q[1], q[2]), (q[0], q[2], q[3])))
        else:
            table.append(())                          # 0 / 2 个交点：没面
    return tuple(table)


_TET_TRIS = _tet_tri_table()


# ===================================================================== 网格


@dataclass(frozen=True)
class Bg3Grid:
    """三轴网格。`t_hit` 立方体形状 = `(n_dv, n_gamma, n_beta)`。"""

    beta: tuple
    gamma: tuple
    dv: tuple
    beta_step: float
    gamma_step: float
    dv_step: float

    @property
    def shape(self) -> tuple:
        return (len(self.dv), len(self.gamma), len(self.beta))

    @property
    def n_cases(self) -> int:
        return int(len(self.dv) * len(self.gamma) * len(self.beta))

    @property
    def n_cells(self) -> tuple:
        return (max(len(self.dv) - 1, 0), max(len(self.gamma) - 1, 0),
                max(len(self.beta) - 1, 0))

    def as_dict(self) -> dict:
        return {"beta": list(self.beta), "gamma": list(self.gamma), "dv": list(self.dv),
                "beta_step": self.beta_step, "gamma_step": self.gamma_step,
                "dv_step": self.dv_step, "shape": list(self.shape),
                "n_cases": self.n_cases, "n_cells": list(self.n_cells)}

    def limits(self) -> dict:
        return {"beta": [self.beta[0], self.beta[-1]], "gamma": [self.gamma[0], self.gamma[-1]],
                "dv": [self.dv[0], self.dv[-1]]}

    def plane_cells(self) -> list:
        """单层 (β, γ) 的格点顺序：**γ 外层、β 内层**（与 `grid.t_hit_matrix` 同序）。"""
        return [(b, g) for g in self.gamma for b in self.beta]

    def cells(self) -> list:
        """全部格点，ΔV 最外层 —— 与立方体 `(i_dv, j_gamma, k_beta)` 的填法一致。"""
        return [(dv, b, g) for dv in self.dv for g in self.gamma for b in self.beta]

    def coords(self) -> tuple:
        """三个方向的坐标向量 `(β, γ, ΔV)`。"""
        return (np.asarray(self.beta, dtype=float), np.asarray(self.gamma, dtype=float),
                np.asarray(self.dv, dtype=float))


def make_grid3(beta_lim, gamma_lim, dv_lim, *, beta_step: float = 100.0,
               gamma_step: float = 5.0, dv_step: float = 50.0) -> Bg3Grid:
    """三轴范围 + 步长 → 三维网格；范围按步长**向内对齐**（与 `grid.make_grid` 同款）。

    第一格取 `ceil(lo/step)*step`，格点永远落在"整步长"上 ⇒ 跨图、跨次扫描可比。
    """
    for name, step in (("beta_step", beta_step), ("gamma_step", gamma_step),
                       ("dv_step", dv_step)):
        if not (float(step) > 0):
            raise ValueError(f"{name} 必须为正，收到 {step!r}")

    def _axis(lim, step):
        lo, hi = float(lim[0]), float(lim[1])
        if not (hi > lo):
            raise ValueError(f"轴范围必须递增，收到 {lim!r}")
        first = math.ceil(lo / float(step) - 1e-9) * float(step)
        return grid_mod.arange_inclusive(first, hi, float(step))

    return Bg3Grid(beta=_axis(beta_lim, beta_step), gamma=_axis(gamma_lim, gamma_step),
                   dv=_axis(dv_lim, dv_step), beta_step=float(beta_step),
                   gamma_step=float(gamma_step), dv_step=float(dv_step))


def box_limits(rows_, *, dv_lim, pad: float = 0.04) -> dict:
    """弹池散点 → 建议的三轴范围（β/γ 与图2 同源，外扩 `pad` 相对量）。

    ΔV 由调用方给：池内 11 型弹的权威 ΔV 落在 **820.5 ~ 1099.5 m/s**，
    所以建议 `[600, 1100]`（下方留 ~27% 余量，让"更差的弹"也在场内）。
    """
    betas = [float(p.beta) for p in rows_]
    gammas = [float(p.gamma) for p in rows_]
    b0, b1 = min(betas), max(betas)
    g0, g1 = min(gammas), max(gammas)
    db, dg = (b1 - b0) * float(pad), (g1 - g0) * float(pad)
    return {"beta": [b0 - db, b1 + db], "gamma": [g0 - dg, g1 + dg],
            "dv": [float(dv_lim[0]), float(dv_lim[1])]}


# ===================================================================== 三轴 → Scaling


def scaling3_for(point: bg.BgPoint, metrics, *, beta: float, gamma: float,
                 dv: float) -> Scaling:
    """三维格点 → `Scaling`。**只是 `bg.scaling_for` 的显式三参调用**，不另立公式。"""
    return bg.scaling_for(point, metrics, beta=float(beta), gamma=float(gamma),
                          dv=float(dv))


def axis_effects(point: bg.BgPoint, metrics, *, beta: float, gamma: float,
                 dv: float) -> dict:
    """三根轴**各自**动了 `Scaling` 的哪几项（相对标称点，标称点 = 1.0）。

    这是"ΔV 真的成了第三根轴"的可判定证据：

    * `dv` 必须**只**动 `thrust_scale`（`cx_scale` 与 `cxaoa_scale` 都是 1.0）；
    * `beta` 只动 `cx_scale`，而 `cx_scale·cxaoa_scale` 保持 1.0（γ 没被带跑）；
    * `gamma` 只动 `cxaoa_scale`（`cx_scale` 由 β 定死），`cx_scale·cxaoa_scale` = γ 的比值。

    任一条件破了，三维图上的"等值面"就不再是任何单一物理量的等值面 —— 而图看起来正常。
    """
    base = scaling3_for(point, metrics, beta=point.beta, gamma=point.gamma, dv=metrics.dv)
    out = {}
    for name, kw in (("beta", {"beta": float(beta)}), ("gamma", {"gamma": float(gamma)}),
                     ("dv", {"dv": float(dv)})):
        keys = {"beta": point.beta, "gamma": point.gamma, "dv": metrics.dv}
        keys.update(kw)
        s = scaling3_for(point, metrics, beta=keys["beta"], gamma=keys["gamma"],
                         dv=keys["dv"])
        out[name] = {"thrust_scale": s.thrust_scale / base.thrust_scale,
                     "cx_scale": s.cx_scale / base.cx_scale,
                     "cxaoa_scale": s.cxaoa_scale / base.cxaoa_scale}
    return out


# ===================================================================== 三维扫描


@dataclass
class Bg3Scan:
    """一次三维扫描的结果。三个数组形状一律 `(n_dv, n_gamma, n_beta)`。"""

    grid: Bg3Grid
    t_hit: np.ndarray
    hit: np.ndarray
    dv_measured: np.ndarray
    scene: Scene
    standard: str
    native: str
    tier: str
    backend: str
    elapsed_s: float
    stats: dict
    n_ok: int = 0
    n_hit: int = 0
    # ⚠ `None` = **这份记录里没有这个数**（旧记录、合成对象），它与"真跑了 0 个工况"不是一回事。
    # 落盘记录必须满足 `n_run + n_cached == n_cases`；用 0 兜底会把这条判据变成谎话
    # （b8a874e 就是这么栽的：`scan_from_record()` 漏带这两个字段 ⇒ 入库报告里 0 + 0 ≠ 5049）。
    n_run: int | None = None
    n_cached: int | None = None

    @property
    def hit_rate(self) -> float:
        return float(self.n_hit) / float(self.grid.n_cases) if self.grid.n_cases else 0.0

    def sample(self, beta: float, gamma: float, dv: float) -> float:
        """三线性插值取 t_hit；出网格或沾到未命中格子 ⇒ `nan`。"""
        return float(sample_cube(self.t_hit, self.grid, [(beta, gamma, dv)])[0])

    def summary(self) -> dict:
        fin = self.t_hit[np.isfinite(self.t_hit)]
        return {"shape": list(self.grid.shape), "n_cases": self.grid.n_cases,
                "n_ok": int(self.n_ok), "n_hit": int(self.n_hit), "hit_rate": self.hit_rate,
                "t_hit_range_s": [float(fin.min()), float(fin.max())] if fin.size else None,
                "elapsed_s": float(self.elapsed_s), "ms_per_case": (
                    float(self.elapsed_s) * 1000.0 / self.grid.n_cases
                    if self.grid.n_cases else None),
                # ⚠ `elapsed_s` 是**本次运行的墙钟**：有热缓存时它会小到"看起来不用算"。
                # 这两个计数是"这次到底真解算了几个工况"的机器判据，别只看墙钟就下结论。
                # 未知就是 `null`（不是 0）⇒ 读者不会把"没记"读成"跑了 0 个"。
                "n_run": None if self.n_run is None else int(self.n_run),
                "n_cached": None if self.n_cached is None else int(self.n_cached),
                "backend": self.backend, "tier": self.tier, "standard": self.standard,
                "stats": dict(self.stats), "limits": self.grid.limits()}

    def record(self, *, digits: int = 4) -> dict:
        """可落盘的完整记录：网格 + 立方体 + 命中掩码 + 摘要（JSON 用）。"""

        def _grid(a):
            return [[[None if not np.isfinite(v) else round(float(v), digits) for v in row]
                     for row in plane] for plane in a]

        return {"summary": self.summary(), "grid": self.grid.as_dict(),
                "t_hit": _grid(self.t_hit),
                "hit": [[[int(v) for v in row] for row in plane] for plane in self.hit],
                "dv_measured": _grid(self.dv_measured)}


def scan3(scene: Scene, *, standard: str = "PL-12", grid: Bg3Grid, tier: str = "fast",
          jobs: int = 8, cache: bool = True, log=None) -> Bg3Scan:
    """三维扫描 `t_hit(β, γ, ΔV)`。

    实现上**只用一个 `Engine`**：外层循环 ΔV，每次改一个宿主字典里的值，
    进程池与结果缓存都复用（`engine.py` 一个字没改）。单层格点顺序 = `grid.plane_cells()`，
    与 `grid.t_hit_matrix` 的 `divmod(k, n_beta)` 完全一致。
    """
    say = log or (lambda _m: None)
    std_entry = pool.standard_entry(standard)
    point = bg.point_of(std_entry)
    metrics = pool.metrics_of(std_entry)

    t_hit = np.full(grid.shape, np.nan, dtype=float)
    hit = np.zeros(grid.shape, dtype=bool)
    dv_measured = np.full(grid.shape, np.nan, dtype=float)
    n_ok = n_hit = 0
    n_run = n_cached = 0
    backend = "not-run"
    plane_cells = grid.plane_cells()
    n_beta = len(grid.beta)

    holder = {"dv": float(grid.dv[0])}
    t0 = time.perf_counter()
    eng = Engine(scene, missile=std_entry.native, tier=tier, jobs=jobs, cache=cache,
                 metrics=metrics,
                 scaling_of=lambda b, g: scaling3_for(point, metrics, beta=b, gamma=g,
                                                      dv=holder["dv"]))
    try:
        for i, dv in enumerate(grid.dv):
            holder["dv"] = float(dv)
            shots = eng.many(plane_cells)
            layer_hit = 0
            for k, shot in enumerate(shots):
                j, m = divmod(k, n_beta)                  # γ 外层、β 内层
                if shot is None:
                    continue
                backend = shot.backend or backend
                if getattr(shot, "cache_hit", False):     # 命中缓存 ⇒ 这次没真解算
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
            say(f"  ΔV={dv:.1f} m/s：命中 {layer_hit}/{len(plane_cells)}"
                f"（累计 {n_hit}/{grid.n_cases}）")
    finally:
        stats = dict(eng.stats)
        eng.close()
    elapsed = time.perf_counter() - t0

    return Bg3Scan(grid=grid, t_hit=t_hit, hit=hit, dv_measured=dv_measured, scene=scene,
                   standard=std_entry.key, native=std_entry.native, tier=tier,
                   backend=backend, elapsed_s=elapsed, stats=stats, n_ok=n_ok, n_hit=n_hit,
                   n_run=n_run, n_cached=n_cached)


def scan_from_record(rec: dict, *, scene: Scene | None = None) -> Bg3Scan:
    """`Bg3Scan.record()` 的逆运算（JSON 里 `nan` 落成 `null`）。

    存在的意义：取证脚本、测试与交互前端都读**同一份落盘记录**，不再各自解算一遍 ——
    而且"落盘 → 读回"必须逐点一致（`tests/test_bg3d_spike.py` 钉住这个往返）。

    ⚠ **往返必须带上"这次真解算了几个工况"**（`n_run` / `n_cached`）：漏带的话重建对象会退回
    默认值，`summary()` 就会写出与同一块 `stats` / `n_cases` 直接矛盾的数（b8a874e 的
    `iso_report.json` 里 `n_run = n_cached = 0` 而 `stats.runs = 4699`、`n_cases = 5049`）。
    记录里没有这两个字段时给 `None`（= 不知道），**不要**兜成 0。
    """
    g = rec["grid"]
    grid = Bg3Grid(beta=tuple(g["beta"]), gamma=tuple(g["gamma"]), dv=tuple(g["dv"]),
                   beta_step=float(g["beta_step"]), gamma_step=float(g["gamma_step"]),
                   dv_step=float(g["dv_step"]))

    def _arr(nested):
        a = np.full(grid.shape, np.nan, dtype=float)
        for i, plane in enumerate(nested):
            for j, row in enumerate(plane):
                for k, v in enumerate(row):
                    if v is not None:
                        a[i, j, k] = float(v)
        return a

    t_hit = _arr(rec["t_hit"])
    hit = np.zeros(grid.shape, dtype=bool)
    for i, plane in enumerate(rec["hit"]):
        for j, row in enumerate(plane):
            for k, v in enumerate(row):
                hit[i, j, k] = bool(v)
    s = rec.get("summary", {})
    return Bg3Scan(grid=grid, t_hit=t_hit, hit=hit, dv_measured=_arr(rec["dv_measured"]),
                   scene=scene if scene is not None else Scene(), standard=s.get("standard", ""),
                   native="", tier=s.get("tier", ""), backend=s.get("backend", ""),
                   elapsed_s=float(s.get("elapsed_s", 0.0)), stats=dict(s.get("stats") or {}),
                   n_ok=int(s.get("n_ok", 0)), n_hit=int(s.get("n_hit", 0)),
                   # 缺失 ⇒ None（"没记"），不是 0（"真跑了 0 个"）
                   n_run=s.get("n_run"), n_cached=s.get("n_cached"))


# ===================================================================== 三线性插值
# 口径：`arr[k, j, i]` 轴序 = (ΔV, γ, β)；返回的点一律按 `(β, γ, ΔV)` 给。


def _cells_vec(axis: np.ndarray, vals: np.ndarray):
    """向量化版"落在第几个格子"：返回 `(下标, 格内相对位置, 是否在域内)`。

    ⚠ **边界面算在域内**（与 `sample_cube` 同一口径）：`ΔV = dv[-1]` 属于最后一个格子、相对位置 1.0。
    """
    axis = np.asarray(axis, dtype=float)
    n = len(axis)
    i = np.clip(np.searchsorted(axis, vals, side="right") - 1, 0, n - 2)
    f = (vals - axis[i]) / (axis[i + 1] - axis[i])
    ok = (f >= -1e-9) & (f <= 1.0 + 1e-9)
    return i, np.clip(f, 0.0, 1.0), ok


def _cubes_vec(arr: np.ndarray, i, j, k) -> np.ndarray:
    """一次把 n 个 2×2×2 子块取出来：`arr[k, j, i]`（轴序 ΔV, γ, β）→ `(n, 2, 2, 2)`。"""
    z = np.arange(2)
    return arr[k[:, None, None, None] + z[None, :, None, None],
               j[:, None, None, None] + z[None, None, :, None],
               i[:, None, None, None] + z[None, None, None, :]]


def _interp_vec(cube: np.ndarray, tb, tg, td) -> np.ndarray:
    """`_interp` 的向量版；权重轴序与 `cube[k, j, i]` 对齐：0=ΔV(·td)、1=γ(·tg)、2=β(·tb)。"""
    w = ((np.stack([1.0 - td, td], axis=1)[:, :, None, None]
          * np.stack([1.0 - tg, tg], axis=1)[:, None, :, None])
         * np.stack([1.0 - tb, tb], axis=1)[:, None, None, :])
    return (cube * w).sum(axis=(1, 2, 3))


def sample_cube(values: np.ndarray, grid: Bg3Grid, points) -> np.ndarray:
    """三线性插值：`points = [(β, γ, ΔV), …]` → `t_hit`；出网格或沾到 `nan` 格子 ⇒ `nan`。

    不假设等距：按"落在第几个格子 + 格子内的相对位置"取，所以非等距网格也能用。

    ⚠ **边界面算在域内**：`ΔV = dv[-1]` 这种正好压在盒子外表面上的点，属于**最后一个格子**
    （格内相对位置 = 1.0），必须插得出值。第一版把"落在最后一个格子之后"直接当域外丢掉，
    于是**凡是被立方体外表面切出来的面（真等值面、拉出来的柱面都有）都只量到内部那部分顶点**，
    数字还看着挺合理 —— 这是"图上一样、量出来假"的那类坑。
    """
    vals = np.asarray(values, dtype=float)
    if vals.ndim != 3:
        raise ValueError(f"values 必须是三维立方体，收到 shape={vals.shape}")
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    out = np.full(len(pts), np.nan, dtype=float)
    if not len(pts):
        return out
    bx, gy, dz = (np.asarray(a, dtype=float) for a in grid.coords())
    i, tb, ok_i = _cells_vec(bx, pts[:, 0])
    j, tg, ok_j = _cells_vec(gy, pts[:, 1])
    k, td, ok_k = _cells_vec(dz, pts[:, 2])
    idx = np.flatnonzero(ok_i & ok_j & ok_k)
    if idx.size:
        cube = _cubes_vec(vals, i[idx], j[idx], k[idx])
        good = np.all(np.isfinite(cube), axis=(1, 2, 3))       # 沾到未命中格子就不插值
        if good.any():
            sel = idx[good]
            out[sel] = _interp_vec(cube[good], tb[sel], tg[sel], td[sel])
    return out


# ===================================================================== 等值面


@dataclass
class Surface:
    """一张三角网格面。`vertices` 是**数据坐标** `(n, 3) = (β, γ, ΔV)`。"""

    level: float
    vertices: np.ndarray
    triangles: np.ndarray
    kind: str = "iso"                    # iso | cylinder
    color: tuple | None = None
    base_dv: float | None = None
    n_seg: int = 0                       # cylinder：参与拉伸的等时线段数（0 = 不适用）

    @property
    def n_tri(self) -> int:
        return int(len(self.triangles))

    def as_dict(self, *, digits: int = 6) -> dict:
        return {"level": float(self.level), "kind": self.kind,
                "color": list(self.color) if self.color else None,
                "base_dv": None if self.base_dv is None else float(self.base_dv),
                "n_seg": int(self.n_seg),
                "vertices": [[round(float(v), digits) for v in row] for row in self.vertices],
                "triangles": [[int(a), int(b), int(c)] for a, b, c in self.triangles],
                "n_tri": self.n_tri,
                "area": surface_area(self.vertices, self.triangles)}


def _corner_slice(values: np.ndarray, off: tuple) -> np.ndarray:
    """取某个角在全部格子上的视图；`off = (dβ, dγ, dΔV)`，形状 `(nd-1, ng-1, nb-1)`。"""
    nd, ng, nb = values.shape
    db, dg, dd = off
    return values[dd:dd + nd - 1, dg:dg + ng - 1, db:db + nb - 1]


def _corner_point(off: tuple, sel: tuple, bx, gy, dz) -> np.ndarray:
    """某个角在 `sel` 选出的格子上的**数据坐标** `(n, 3) = (β, γ, ΔV)`。"""
    ks, js, is_ = sel
    db, dg, dd = off
    return np.stack([bx[is_ + db], gy[js + dg], dz[ks + dd]], axis=1)


def marching_tetrahedra(values: np.ndarray, levels, *, grid: Bg3Grid,
                        orient: bool = True) -> list:
    """三维标量场 → 真等值面（每个 level 一个 `Surface`）。

    `values` 轴序 `(ΔV, γ, β)`，必须与 `grid.shape` 一致。**未命中（`nan`）格子整格跳过**：
    一个立方体只要有任一角是 `nan`，半真半假的插值点会造出根本不存在的面。
    """
    vals = np.asarray(values, dtype=float)
    if vals.shape != grid.shape:
        raise ValueError(f"values.shape={vals.shape} 与 grid.shape={grid.shape} 不一致")
    bx, gy, dz = grid.coords()
    nd, ng, nb = vals.shape
    if nd < 2 or ng < 2 or nb < 2:
        return []
    grad = np.gradient(vals, dz, gy, bx, edge_order=1) if orient else None

    out = []
    for lev in levels:
        lev = float(lev)
        v = vals - lev
        corners = [_corner_slice(v, _CORNERS[c]) for c in range(8)]
        verts, tris = [], []
        n_vert = 0                                         # 已累积的**顶点数**（不是块数）
        for tet in _TETS:
            cv = [corners[c] for c in tet]                 # 4 个格点值数组
            stacked = np.stack(cv, axis=0)
            mask = np.zeros(cv[0].shape, dtype=np.int8)
            for t in range(4):
                mask |= (cv[t] < 0).astype(np.int8) << t
            mask[~np.all(np.isfinite(stacked), axis=0)] = 15   # nan 格子：不出面
            for m in range(1, 15):
                tris_local = _TET_TRIS[m]
                if not tris_local:
                    continue
                sel = np.nonzero(mask == m)
                if sel[0].size == 0:
                    continue
                cut = [e for e in _TET_EDGES
                       if ((m >> e[0]) & 1) != ((m >> e[1]) & 1)]
                base = n_vert
                pts = []
                for a, b in cut:
                    ca, cb = cv[a][sel], cv[b][sel]
                    t_ = (ca / (ca - cb))[:, None]         # 线性插值参数
                    pa = _corner_point(_CORNERS[tet[a]], sel, bx, gy, dz)
                    pb = _corner_point(_CORNERS[tet[b]], sel, bx, gy, dz)
                    pts.append(pa + (pb - pa) * t_)
                block = np.stack(pts, axis=1).reshape(-1, 3)   # 格点优先，交点连续
                verts.append(block)
                n_vert += len(block)
                ncell = sel[0].size
                off = (np.arange(ncell)[:, None] * len(cut))
                for tri in tris_local:
                    idx = off + np.asarray(tri)[None, :]
                    tris.append((idx + base).astype(np.int64))
        if verts:
            V = np.concatenate(verts, axis=0)
            T = np.concatenate(tris, axis=0)
            if orient and grad is not None:
                T = _orient(V, T, grad, grid)
            out.append(Surface(level=lev, vertices=V, triangles=T, kind="iso"))
    return out


#: 「这一层出不出得了面」的默认门槛：**跨过该层的格子数**（8 角全有限且 min ≤ L ≤ max）。
#: 4 = 至少 2×2×1 的一小片，比"1 个格子"稳，又不会把真的小面掐掉（图3 的 7×7×11 网格上
#: 实测每一档都远超它，门槛只在**退化**那一侧起作用）。
DEFAULT_MIN_CELLS = 4
#: 面至少要这么多三角形（0 或 1~3 个三角形只可能是角落碎片）。
DEFAULT_MIN_TRI = 4


def straddling_cells(values: np.ndarray, level: float) -> int:
    """**跨过 `level` 的格子数**：8 个角全有限、且 `min ≤ level ≤ max`。

    这是"这一层有没有东西可出"的唯一判据原料（`iso_surfaces()` 与判据共用）。
    `nan` 格子直接不算 —— 与 `marching_tetrahedra()` 里"任一角是 `nan` 整格跳过"同一口径。
    """
    v = np.asarray(values, dtype=float) - float(level)
    if v.ndim != 3:
        raise ValueError(f"values 必须是三维立方体 (n_dv, n_gamma, n_beta)，收到 {v.shape}")
    nd, ng, nb = v.shape
    if min(nd, ng, nb) < 2:
        return 0
    corners = [v[d:d + nd - 1, g:g + ng - 1, b:b + nb - 1]
               for d in (0, 1) for g in (0, 1) for b in (0, 1)]
    stack = np.stack(corners, axis=0)
    finite = np.all(np.isfinite(stack), axis=0)
    return int(np.count_nonzero(finite & np.any(stack < 0.0, axis=0)
                                & np.any(stack > 0.0, axis=0)))


def boundary_edges(vertices: np.ndarray, triangles: np.ndarray, *, digits: int = 6) -> tuple:
    """`(只用了一次的边数, 用了三次以上的边数)` —— **几何**去重之后数的。

    ⚠ `marching_tetrahedra()` 的顶点是**按格子分别生成**的（同一个几何点会被相邻格子
    各发一次），所以不能直接拿顶点下标数边的使用次数 —— 那样任何面都会被判成"全是一次边"。
    先把坐标四舍五入到 `digits` 位做规范化，再数。
    闭合三角面（流形）每条边**正好用两次** ⇒ 另外两项都为 0。
    """
    V = np.asarray(vertices, dtype=float)
    T = np.asarray(triangles, dtype=int)
    if T.size == 0:
        return 0, 0
    _, inv = np.unique(np.round(V, int(digits)), axis=0, return_inverse=True)
    tri = inv.reshape(-1)[T]
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], axis=0)
    e = np.sort(e, axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return int(np.count_nonzero(counts == 1)), int(np.count_nonzero(counts > 2))


def iso_surfaces(values: np.ndarray, *, grid: Bg3Grid, levels,
                 min_cells: int = DEFAULT_MIN_CELLS,
                 min_tri: int = DEFAULT_MIN_TRI, orient: bool = True) -> list:
    """三维标量场 → 每个 level 一条记录（含"能不能出面"的判定与原因）。

    这是图3 等时面的**唯一**入口（内部就是 `marching_tetrahedra()`，不重造几何）。

    | 键 | 含义 |
    | --- | --- |
    | `level` | 这一层的 t 值 [s] |
    | `ok` | **能不能出面**：`n_cells ≥ min_cells` 且 `n_tri ≥ min_tri` |
    | `reason` | 不能出面时说清是"跨的格子太少"还是"没有有限值"（UI 直接显示这句话） |
    | `n_cells` / `n_tri` / `n_vert` / `area` | 诊断量（`area` 只在 `ok` 时有意义） |
    | `closed` / `n_boundary` | 面是否闭合（`n_boundary` = 只用了一次的边数；NaN 截断处必然 > 0） |
    | `vertices` / `triangles` | 数据坐标 `(β, γ, ΔV)` 的三角网格（`ok` 为假时是空数组） |

    ⚠ **开口是常态，不是缺陷**：立方体里只要有 `nan`（脱靶）格子，面就会被截断在那儿。
    这里如实报 `closed=False` + `area`，**不**谎称闭合。
    """
    vals = np.asarray(values, dtype=float)
    if vals.shape != grid.shape:
        raise ValueError(f"values.shape={vals.shape} 与 grid.shape={grid.shape} 不一致")
    lv = [float(x) for x in levels]
    surfs = marching_tetrahedra(vals, lv, grid=grid, orient=orient) if lv else []
    by_level = {round(float(s.level), 9): s for s in surfs}
    n_finite = int(np.count_nonzero(np.isfinite(vals)))
    out = []
    for level in lv:
        n_cells = straddling_cells(vals, level)
        s = by_level.get(round(level, 9))
        n_tri = 0 if s is None else int(s.n_tri)
        n_vert = 0 if s is None else int(len(s.vertices))
        area = 0.0 if s is None else surface_area(s.vertices, s.triangles)
        nb = nm = 0
        if s is not None and n_tri:
            nb, nm = boundary_edges(s.vertices, s.triangles)
        ok = bool(n_cells >= int(min_cells) and n_tri >= int(min_tri))
        if ok:
            reason = ""
        elif n_finite == 0:
            reason = "这一层没有可用的命中点（该弹在此工况下没有一个点命中）"
        elif n_cells < int(min_cells):
            reason = (f"这一层只跨过 {n_cells} 个格子（少于 {int(min_cells)} 个），"
                      "出不了面 —— 该 t 落在命中区之外")
        else:
            reason = f"这一层只提到 {n_tri} 个三角形（少于 {int(min_tri)}），是角落碎片"
        out.append({
            "level": float(level), "ok": ok, "reason": reason,
            "n_cells": int(n_cells), "n_tri": n_tri, "n_vert": n_vert,
            "area": float(area), "n_boundary": int(nb), "n_nonmanifold": int(nm),
            "closed": bool(ok and nb == 0 and nm == 0),
            # ⚠ `ok=False` 时**不发几何**（`vertices` / `triangles` 空），但 `n_tri` /
            #   `n_cells` / `area` **照报** —— 那些是"查到了什么"的诊断量。
            #   这样前端只有一条规则："`ok` 为假就什么都不画"，不可能画出碎片。
            "vertices": (np.asarray(s.vertices, dtype=float) if (ok and s is not None)
                         else np.zeros((0, 3))),
            "triangles": (np.asarray(s.triangles, dtype=int) if (ok and s is not None)
                          else np.zeros((0, 3), dtype=int)),
        })
    return out


def extrude_isolines(t_plane: np.ndarray, *, beta, gamma, level: float, dv_lo: float,
                     dv_hi: float, base_dv: float, step: float = 1.0) -> Surface:
    """**ΔV 被钉死那一层**的二维等时线沿 ΔV 拉成柱面（口径 2）。

    `t_plane` 必须是 `scan.t_hit[i0]` 那样的 **(n_gamma, n_beta)** 立方体切片（行 = γ、列 = β）；
    形状不对就**当场报错** —— 转置过的等时线在图上看起来同样"正常"，只是 β 与 γ 换了位置。

    为什么用 `grid._contour_segments` 而不是公开的 `grid.extract_isolines`：
    `extract_isolines` 把**同一层的多段等时线揉成一袋点**（它给 JSON 记录用），照它 `zip` 相邻点
    会在段与段之间拉出**并不存在的墙**。拉伸需要**分段**结构，而仓库里真正带分段结构的就是
    `_contour_segments` —— 也正是 `figures.plot_isotime` 画等时线时用的那条路（`cs.allsegs`）。
    它不在了就明确报错，绝不退回"看起来也对"的揉点版本。

    顶点布局：每小段 4 个点（a@lo, b@lo, a@hi, b@hi），侧面 2 个三角形，不做端盖。
    `Surface.kind == "cylinder"`、`n_seg` = 参与拉伸的段数（1 段闭环 ⇒ 一支闭环柱面）。
    **它不是等值面**：`iso_spread()` 会把这件事量出来。
    """
    arr = np.asarray(t_plane, dtype=float)
    shape = (len(gamma), len(beta))
    if arr.shape != shape:
        raise ValueError(f"t_plane.shape={arr.shape} 与 (n_gamma, n_beta)={shape} 不一致"
                         "（立方体切片是行 = γ、列 = β；转置过的等时线在图上同样'正常'）")
    if not hasattr(grid_mod, "_contour_segments"):
        raise RuntimeError("grid._contour_segments 不见了：拉伸必须按**分段**做，"
                           "否则段与段之间会拉出不存在的墙")
    levels = grid_mod.iso_levels(arr, step)
    if not levels:
        raise ValueError("这一层全是 nan，没有可提的层级")
    # `_contour_segments(dv, bc, t_grid)` 内部再 `.T` 一次，所以这里要给 `arr.T`（行 = β、列 = γ）
    got = grid_mod._contour_segments(tuple(float(v) for v in beta),
                                     tuple(float(v) for v in gamma), arr.T, levels)
    want_lv, want_segs = min(got, key=lambda item: abs(float(item[0]) - float(level)))
    segs = [np.asarray(s, dtype=float) for s in want_segs if len(s) >= 2]
    if not segs:
        raise ValueError(f"level≈{want_lv:g} 在这一层提不出任何段")
    verts, tris = [], []
    for seg in segs:
        for a, b in zip(seg[:-1], seg[1:]):
            base = len(verts)
            verts.append(np.array([[a[0], a[1], dv_lo], [b[0], b[1], dv_lo],
                                   [a[0], a[1], dv_hi], [b[0], b[1], dv_hi]], dtype=float))
            tris.append(np.array([[base, base + 1, base + 3], [base, base + 3, base + 2]],
                                 dtype=np.int64))
    return Surface(level=float(want_lv), vertices=np.concatenate(verts, axis=0),
                   triangles=np.concatenate(tris, axis=0), kind="cylinder",
                   base_dv=float(base_dv), n_seg=len(segs))


def extrude_layer(scan: Bg3Scan, *, level: float, base_dv: float, step: float = 1.0,
                  dv_lo: float | None = None, dv_hi: float | None = None) -> Surface:
    """`extrude_isolines` 的顺手版：取 `scan` 里 ΔV 最接近 `base_dv` 的那一层当基准。"""
    i = int(np.argmin(np.abs(np.asarray(scan.grid.dv) - float(base_dv))))
    return extrude_isolines(scan.t_hit[i], beta=scan.grid.beta, gamma=scan.grid.gamma,
                            level=level, dv_lo=scan.grid.dv[0] if dv_lo is None else dv_lo,
                            dv_hi=scan.grid.dv[-1] if dv_hi is None else dv_hi,
                            base_dv=scan.grid.dv[i], step=step)


def _orient(vertices: np.ndarray, triangles: np.ndarray, grad: tuple, grid: Bg3Grid):
    """统一三角形绕向：法向指向 `t_hit` **增大**的一侧（光照与有向体积都要它）。

    对角线缩放不改变 `n·∇f` 的符号（`(D⁻ᵀn)·(D∇f) = n·∇f`），所以三轴量纲不同也没关系。
    """
    V, T = vertices, triangles
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(p1 - p0, p2 - p0)
    g = _sample_grad(grad, grid, (p0 + p1 + p2) / 3.0)
    flip = np.einsum("ij,ij->i", n, g) < 0
    if bool(flip.any()):
        T = T.copy()
        T[flip, 1], T[flip, 2] = T[flip, 2].copy(), T[flip, 1].copy()
    return T


def _sample_grad(grad: tuple, grid: Bg3Grid, points: np.ndarray) -> np.ndarray:
    """三线性插值梯度（向量化）；`grad` 由 `np.gradient(vals, dz, gy, bx)` 给出，输出分量序 (β, γ, ΔV)。

    ⚠ 三个分量**用的是同一个点** `(ΔV, γ, β)`（`_cubes_vec` 的口径）—— 第一版把"该分量的坐标"
    当成 `z` 递了进去（β 分量拿到 `(β, γ, β)`），于是 β 导数恒为 `0.0`（越界兜底），
    `n·∇f` 恒等于 0、**绕向永远不会被修正**。球面之所以看起来没事，纯属巧合：球面的三根轴
    恰好都是 −2…2，`(β, γ, β)` 那次查找照样落在范围内。
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    out = np.full((len(pts), 3), np.nan, dtype=float)
    if not len(pts):
        return out
    bx, gy, dz = (np.asarray(a, dtype=float) for a in grid.coords())
    i, tb, ok_i = _cells_vec(bx, pts[:, 0])
    j, tg, ok_j = _cells_vec(gy, pts[:, 1])
    k, td, ok_k = _cells_vec(dz, pts[:, 2])
    idx = np.flatnonzero(ok_i & ok_j & ok_k)
    if not idx.size:
        return out
    for axis, arr in enumerate((grad[2], grad[1], grad[0])):      # β, γ, ΔV 三个分量
        cube = _cubes_vec(arr, i[idx], j[idx], k[idx])
        good = np.all(np.isfinite(cube), axis=(1, 2, 3))
        if good.any():
            sel = idx[good]
            out[sel, axis] = _interp_vec(cube[good], tb[sel], tg[sel], td[sel])
    return out


# ===================================================================== 面的度量


def triangle_areas(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """每个三角形的面积（数据坐标下的欧氏面积；三轴量纲不同，见 `surface_area`）。"""
    V, T = np.asarray(vertices, float), np.asarray(triangles, int)
    if T.size == 0:
        return np.zeros(0, dtype=float)
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)


def surface_area(vertices: np.ndarray, triangles: np.ndarray) -> float:
    """三角形面积之和。⚠ 三轴量纲不同（β: kg/m²、γ: kg/m²、ΔV: m/s），
    所以这只是**同一套轴范围下的几何量**，不是物理面积，只用于自检与两口径对比。"""
    return float(triangle_areas(vertices, triangles).sum())


def iso_spread(scan: Bg3Scan, surface: Surface) -> dict:
    """把面上每个顶点代回标量场，看 t_hit 的**散布** —— 两种口径的判据就在这里。

    真等值面：spread 只剩插值误差（相对场跨度通常 << 1%）；
    拉伸柱面：spread 与"ΔV 从 600 到 1100 时 t_hit 的变化"同量级。
    """
    if len(surface.vertices) == 0:
        return {"n": 0, "spread": math.nan, "level": float(surface.level)}
    t = sample_cube(scan.t_hit, scan.grid, surface.vertices)
    good = t[np.isfinite(t)]
    fin = scan.t_hit[np.isfinite(scan.t_hit)]
    span = float(fin.max() - fin.min()) if fin.size else math.nan
    if good.size == 0:
        return {"n": 0, "spread": math.nan, "level": float(surface.level), "field_span": span}
    spread = float(good.max() - good.min())
    return {"n": int(good.size), "level": float(surface.level), "t_min": float(good.min()),
            "t_max": float(good.max()), "spread": spread, "mean": float(good.mean()),
            "field_span": span, "spread_rel": (spread / span) if span else math.nan,
            "bias": float(good.mean() - surface.level)}


def enclosed_volume(vertices: np.ndarray, triangles: np.ndarray) -> float:
    """闭合面的有向体积（散度定理）。**不闭合**的面给出偏小的值，可用于自检。"""
    V, T = np.asarray(vertices, float), np.asarray(triangles, int)
    if T.size == 0:
        return 0.0
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    return float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum() / 6.0)


def dv_dependence(scan: Bg3Scan, *, beta: float, gamma: float) -> dict:
    """固定 (β, γ) 时 t_hit 随 ΔV 的变化 —— "柱面不是等值面"的定量根据。"""
    bx, gy, _ = scan.grid.coords()
    i = int(np.argmin(np.abs(bx - beta)))
    j = int(np.argmin(np.abs(gy - gamma)))
    col = scan.t_hit[:, j, i]
    good = np.isfinite(col)
    if good.sum() < 2:
        return {"n": int(good.sum()), "span": math.nan, "beta": float(bx[i]),
                "gamma": float(gy[j])}
    dvs = np.asarray(scan.grid.dv)[good]
    vals = col[good]
    slope = float(np.polyfit(dvs, vals, 1)[0])
    return {"n": int(good.sum()), "beta": float(bx[i]), "gamma": float(gy[j]),
            "t_low": float(vals[0]), "t_high": float(vals[-1]),
            "span": float(vals.max() - vals.min()), "slope_s_per_ms": slope}


def dv_linearity(scan: Bg3Scan) -> dict:
    """**ΔV 轴到底带来多少独立信息**：逐 (β, γ) 列对 ΔV 做最小二乘直线拟合。

    如果斜率在所有 (β, γ) 上几乎一样、且残差远小于 t_hit 的跨度，那这一族等值面就是
    **一族近似平行的板**（t_hit ≈ a(β, γ) + b·ΔV）—— 图上看着是三维，独立信息量只有
    `b` 一个数。这是"要不要把 ΔV 立成第三根轴"最该先看的一张体检表。
    """
    t = np.asarray(scan.t_hit, dtype=float)
    n_dv = t.shape[0]
    dv = np.asarray(scan.grid.dv, dtype=float)
    Y = t.reshape(n_dv, -1)
    ok = np.isfinite(Y).all(axis=0)
    if int(ok.sum()) < 2:
        return {"n_col": int(ok.sum())}
    Y = Y[:, ok]
    A = np.column_stack([np.ones(n_dv), dv])
    coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
    resid = Y - A @ coef
    ss = ((Y - Y.mean(axis=0)) ** 2).sum(axis=0)
    r2 = 1.0 - (resid ** 2).sum(axis=0) / np.where(ss > 0, ss, np.nan)
    slope = coef[1]                                # `A = [1, ΔV]` ⇒ 第 0 行是截距、第 1 行是斜率
    mean = float(slope.mean())
    return {"n_col": int(ok.sum()), "slope_mean": mean, "slope_std": float(slope.std()),
            "slope_min": float(slope.min()), "slope_max": float(slope.max()),
            "slope_rel_spread": (float(slope.std() / abs(mean)) if mean else None),
            "r2_min": float(np.nanmin(r2)), "r2_median": float(np.nanmedian(r2)),
            "rms_resid_s": float(np.sqrt((resid ** 2).mean())),
            "t_range_s": [float(np.nanmin(t)), float(np.nanmax(t))]}


def dv_quadratic(scan: Bg3Scan) -> dict:
    """**一阶够不够**：逐 (β, γ) 列再加二次项拟合 `t_hit = a + b·ΔV + c·ΔV²`。

    存在的意义：`dv_linearity` 的 `R² 0.989` 很容易被读成"ΔV 轴只有一个斜率"，
    但残差 0.55 s 到底是不是噪声/曲率，必须再加一项才知道。这里报三件事：
      * `rms_resid_s`：二次拟合的残差（与一次拟合的那个对比，掉了多少一目了然）；
      * `curv_span_s`：曲率在该列 ΔV 区间两端相对中点的抬升量 `|c|·(ΔV 跨度)²/4`
        —— 这是"抛物线有多弯"的物理量，可直接和该列的 ΔV 效应（跨度）比；
      * `curv_frac_median`：`curv_span_s / 该列 ΔV 效应跨度` 的中位数。
    `curv_smooth_frac` 是 459 列里 `c` 为正（同一朝向）的占比：若正负各半，那多半是噪声。
    """
    t = np.asarray(scan.t_hit, dtype=float)
    n_dv = t.shape[0]
    dv = np.asarray(scan.grid.dv, dtype=float)
    Y = t.reshape(n_dv, -1)
    ok = np.isfinite(Y).all(axis=0)
    if int(ok.sum()) < 3:
        return {"n_col": int(ok.sum())}
    Y = Y[:, ok]

    def _fit(cols):
        A = np.column_stack(cols)
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        resid = Y - A @ coef
        return coef, float(np.sqrt((resid ** 2).mean()))     # 注意：RMS 是 sqrt(mean(resid²))

    _c1, rms_lin = _fit([np.ones(n_dv), dv])
    coef, rms_quad = _fit([np.ones(n_dv), dv, dv * dv])
    c = coef[2]
    span_dv = float(dv.max() - dv.min())
    curv = np.abs(c) * span_dv ** 2 / 4.0                 # 端点相对中点的抬升
    eff = np.ptp(Y, axis=0)                                # 该列 ΔV 实际造成的 t_hit 跨度
    frac = curv / np.where(eff > 0, eff, np.nan)
    return {"n_col": int(ok.sum()), "rms_resid_s": rms_quad, "rms_resid_lin_s": rms_lin,
            "curv_span_median_s": float(np.median(curv)),
            "curv_frac_median": float(np.nanmedian(frac)),
            "curv_smooth_frac": float((c > 0).mean()),
            "c_abs_median": float(np.median(np.abs(c))),
            "span_dv": span_dv}

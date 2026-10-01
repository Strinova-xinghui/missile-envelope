# -*- coding: utf-8 -*-
"""β–γ–ΔV 三维图 spike 的判据：`python tests\\run_tests.py -k bg3d_spike`。

**不跑长扫描、不碰 `results/`**：这里只有三类东西 ——

1. `marching_tetrahedra` 的**解析真值**（平面面积、球体积、朝向、退化与 `nan` 格子）；
2. **三轴不变量**（ΔV 只动 `thrust_scale`；β/γ 的不变量是 `cx_scale·cxaoa_scale`）与网格/弹池包含性；
3. **落盘证据自洽**（`spikes/bg3d/out/scan_*.json` 的形状与"ΔV 真的是有效轴"、
   `out/iso/iso_report.json` 里"真等值面 vs 拉伸柱面"的散布差、跨进程 sha256）——
   文件不在就 `skip`，因为那是取证脚本的产物，不该由测试套件现场跑出来。

⚠ 文件名含 `bg3d`，所以既有的 `-k bg` 也会收集到本文件（都是纯函数，秒级）。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from missile_sim import bg, bg3d, pool                     # noqa: E402
from missile_sim.spec import Scene                          # noqa: E402

SPIKE = ROOT / "spikes" / "bg3d"
OUT = SPIKE / "out"
ISO = OUT / "iso"


# ------------------------------------------------------------------ 工具


def _need(path: Path, hint: str) -> None:
    """证据文件缺失就**硬失败**并提示怎么重建。

    ⚠ 这里不能用 `pytest.skip`：本项目的 `tests/_pytest_shim.py` 里 `skip()` 是个
    "本项目未使用"的桩，只会 `raise RuntimeError` 被记成**失败**。而这些产物是入库的，
    缺了就是树坏了 —— 明确失败比"静默绿"更对。
    """
    assert path.is_file(), f"缺 {path.relative_to(ROOT)}：先跑 {hint}"


def _load_spike(name: str):
    """按路径加载 `spikes/bg3d/*.py`（它不是包，只能这么拿它的配置）。"""
    path = SPIKE / name
    _need(path, f"python spikes\\\\bg3d\\\\{name}")
    spec = importlib.util.spec_from_file_location(f"bg3d_spike_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_scan(grid: bg3d.Bg3Grid, values: np.ndarray) -> bg3d.Bg3Scan:
    """合成一次"扫描结果"：只为把纯几何/口径判据跑起来，不解算任何东西。"""
    fin = np.isfinite(values)
    return bg3d.Bg3Scan(grid=grid, t_hit=values, hit=fin,
                        dv_measured=np.full(grid.shape, np.nan), scene=Scene(),
                        standard="synthetic", native="", tier="fast", backend="none",
                        elapsed_s=0.0, stats={}, n_ok=int(fin.sum()), n_hit=int(fin.sum()))


def _linear_field(grid: bg3d.Bg3Grid, *, k_beta: float, k_gamma: float,
                  k_dv: float, ref) -> np.ndarray:
    """`t = 50 + k_beta·(β-β0) + k_gamma·(γ-γ0) + k_dv·(ΔV-ΔV0)` 的立方体（轴序 ΔV, γ, β）。"""
    b0, g0, d0 = ref
    B, G, D = np.meshgrid(np.asarray(grid.beta) - b0, np.asarray(grid.gamma) - g0,
                          np.asarray(grid.dv) - d0, indexing="ij")
    cube = 50.0 + k_beta * B + k_gamma * G + k_dv * D
    return np.transpose(cube, (2, 1, 0))


# ================================================================== 1. 提面：解析真值


def test_tet_table_triangle_count_follows_popcount():
    """16 种符号组合的面数：1/3 个内侧角 ⇒ 3 条棱 ⇒ 1 个三角；2 个 ⇒ 4 条棱 ⇒ 2 个。"""
    for m in range(16):
        pop = bin(m).count("1")
        want = 0 if pop in (0, 4) else (2 if pop == 2 else 1)
        assert len(bg3d._TET_TRIS[m]) == want, (m, bg3d._TET_TRIS[m])


def test_six_tets_tile_the_cube():
    """Kuhn 分解必须**恰好**铺满立方体：随机撒点，每点只能落在其中一个四面体内。"""
    verts = np.array(bg3d._CORNERS, dtype=float)
    rng = np.random.default_rng(20261001)
    pts = rng.random((4000, 3))

    def inside(tet, p):
        a, b, c, d = (verts[i] for i in tet)
        m = np.column_stack([b - a, c - a, d - a])

        def bary(q):
            try:
                return np.linalg.solve(m, q - a)
            except np.linalg.LinAlgError:
                return None

        w = bary(p)
        if w is None:
            return False
        return bool(np.all(w >= -1e-12) and w.sum() <= 1 + 1e-12)

    counts = [sum(inside(t, p) for t in bg3d._TETS) for p in pts]
    assert set(counts) == {1}, f"有 {len([c for c in counts if c != 1])} 个点不在恰好 1 个四面体内"


def test_plane_isosurface_area_is_exact():
    """`f = β` 的等值面是一个矩形：所有顶点 β 相同，面积 = γ跨度 × ΔV跨度（精确）。"""
    g = bg3d.make_grid3([0, 10], [0, 4], [0, 2], beta_step=1, gamma_step=1, dv_step=1)
    cube = _linear_field(g, k_beta=1.0, k_gamma=0.0, k_dv=0.0, ref=(0.0, 0.0, 0.0))
    surfs = bg3d.marching_tetrahedra(cube, [55.5], grid=g)
    assert len(surfs) == 1
    s = surfs[0]
    assert np.abs(s.vertices[:, 0] - 5.5).max() < 1e-12
    area = bg3d.surface_area(s.vertices, s.triangles)
    assert abs(area - 4.0 * 2.0) < 1e-12, area
    assert s.n_tri == 8 * 8, s.n_tri               # 8 个格子 × 每格 8 个三角形


def test_oblique_plane_vertices_lie_on_the_level_set():
    """斜平面 `f = β + 2γ + 3ΔV`：线性场里插值是精确的，顶点必须严格落在等值面上。"""
    g = bg3d.make_grid3([0, 10], [0, 4], [0, 2], beta_step=1, gamma_step=1, dv_step=1)
    B, G, D = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma), np.asarray(g.dv),
                          indexing="ij")
    cube = np.transpose(B + 2 * G + 3 * D, (2, 1, 0))
    surfs = bg3d.marching_tetrahedra(cube, [12.5, 20.0], grid=g)
    assert len(surfs) == 2
    for s in surfs:
        val = s.vertices @ np.array([1.0, 2.0, 3.0])
        assert np.abs(val - s.level).max() < 1e-12


def test_closed_surface_volume_matches_analytic_sphere():
    """闭合性 + 朝向一致性 + **收敛性**：球面的有向体积随网格变细收敛到 4πr³/3。

    实测（同一份代码）：31³ → 1.328%、41³ → 0.750%、51³ → 0.479%（`max|r−1|` 0.00666 /
    0.00375 / 0.00240，是 O(h²) 的离散误差，不是朝向误差）；朝向若混了，有向体积会掉到 0 附近。
    """
    def sphere_scan(n):
        ax = np.linspace(-2, 2, n)
        g = bg3d.Bg3Grid(beta=tuple(ax), gamma=tuple(ax), dv=tuple(ax), beta_step=0.1,
                         gamma_step=0.1, dv_step=0.1)
        B, G, D = np.meshgrid(ax, ax, ax, indexing="ij")
        cube = np.transpose(-(B ** 2 + G ** 2 + D ** 2), (2, 1, 0))
        return g, bg3d.marching_tetrahedra(cube, [-1.0], grid=g)[0]

    exact = 4.0 / 3.0 * np.pi
    err = {}
    for n in (31, 41):
        _g, s = sphere_scan(n)
        vol = bg3d.enclosed_volume(s.vertices, s.triangles)
        assert vol < 0, "朝向约定变了：法向应指向标量增大的一侧"
        err[n] = abs(abs(vol) - exact) / exact
        r = np.linalg.norm(s.vertices, axis=1)
        assert np.abs(r - 1.0).max() < 0.01, (n, float(np.abs(r - 1).max()))
    assert err[31] < 0.02 and err[41] < err[31], err
    assert err[41] < 0.01, err


def test_orientation_survives_unequal_axis_ranges():
    """**三根轴跨度不同**的椭球面也必须朝向一致 —— 这是 `_sample_grad` 的回归判据。

    第一版把"该分量的坐标"当 `z` 递进了 `_trilin`，β 导数恒为 0（越界兜底 0.0），
    绕向永远不会被修正。球面之所以照过，是因为它三根轴恰好都是 −2…2；
    换成 6×2×4 的椭球，`n·∇f` 才有机会把这件事暴露出来（混向会让有向体积掉到 0 附近）。
    """
    g = bg3d.Bg3Grid(beta=tuple(np.linspace(-3, 3, 37)), gamma=tuple(np.linspace(-1, 1, 17)),
                     dv=tuple(np.linspace(-2, 2, 25)), beta_step=0.1, gamma_step=0.1,
                     dv_step=0.1)
    B, G, D = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma), np.asarray(g.dv),
                          indexing="ij")
    cube = np.transpose(-((B / 3) ** 2 + (G / 1) ** 2 + (D / 2) ** 2), (2, 1, 0))
    s = bg3d.marching_tetrahedra(cube, [-1.0], grid=g)[0]
    vol = bg3d.enclosed_volume(s.vertices, s.triangles)
    exact = 4.0 / 3.0 * np.pi * 3.0 * 1.0 * 2.0
    assert vol < 0
    assert abs(abs(vol) - exact) / exact < 0.01, (vol, exact)


def test_triangle_normals_point_toward_increasing_field():
    """`f = β` 的面，法向的 β 分量必须全为正（否则 mplot3d 的光照/半透明会花）。"""
    g = bg3d.make_grid3([0, 10], [0, 4], [0, 2], beta_step=1, gamma_step=1, dv_step=1)
    cube = _linear_field(g, k_beta=1.0, k_gamma=0.0, k_dv=0.0, ref=(0.0, 0.0, 0.0))
    s = bg3d.marching_tetrahedra(cube, [55.5], grid=g)[0]
    V, T = s.vertices, s.triangles
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    assert (n[:, 0] > 0).all(), f"有 {int((n[:, 0] <= 0).sum())} 个法向指反了"
    # 同一张面在非等长轴上也要一致（平面场 → 法向只有 β 分量）
    assert abs(bg3d.surface_area(V, T) - 4.0 * 2.0) < 1e-12


def test_level_outside_range_and_thin_grid_return_empty():
    g = bg3d.make_grid3([0, 10], [0, 4], [0, 2], beta_step=1, gamma_step=1, dv_step=1)
    cube = _linear_field(g, k_beta=1.0, k_gamma=0.0, k_dv=0.0, ref=(0.0, 0.0, 0.0))
    assert bg3d.marching_tetrahedra(cube, [1000.0], grid=g) == []
    thin = bg3d.Bg3Grid(beta=(0.0, 1.0), gamma=(0.0, 1.0), dv=(0.0,), beta_step=1.0,
                        gamma_step=1.0, dv_step=1.0)
    assert bg3d.marching_tetrahedra(np.zeros((1, 2, 2)), [0.5], grid=thin) == []
    with pytest.raises(ValueError):
        bg3d.marching_tetrahedra(cube, [50.0], grid=bg3d.Bg3Grid(
            beta=(0.0, 1.0), gamma=(0.0, 1.0), dv=(0.0, 1.0, 2.0), beta_step=1.0,
            gamma_step=1.0, dv_step=1.0))


def test_nan_cells_are_skipped_entirely():
    """未命中的格子（`nan`）整格跳过：不许在它附近造出"半真半假"的面。

    场取 `f = β + 0.5ΔV`（与 γ 无关，好算），层级 6 ⇒ 面在 β∈[5,6]、ΔV∈[0,2]；
    把**整层 γ=2** 挖成 `nan`，于是面必须只出现在 γ∈{0,1,3,4} 上。
    """
    g = bg3d.make_grid3([0, 10], [0, 4], [0, 2], beta_step=1, gamma_step=1, dv_step=1)
    B, G, D = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma), np.asarray(g.dv),
                          indexing="ij")
    cube = np.transpose(B + 0.5 * D + 0.0 * G, (2, 1, 0))
    hole = cube.copy()
    hole[:, 2, :] = np.nan                          # γ = 2 整层挖空
    surfs = bg3d.marching_tetrahedra(hole, [6.0], grid=g)
    assert len(surfs) == 1, len(surfs)
    s = surfs[0]
    assert s.n_tri > 0
    gy = np.unique(np.round(s.vertices[:, 1], 9))
    assert 2.0 not in gy, f"挖空的 γ=2 上出现了顶点：{gy}"
    assert gy.min() >= 0.0 and gy.max() <= 4.0 and gy.size >= 4, gy
    # 对照组：不挖空时有顶点落在 γ=2 上（否则上面那条判据是空转的）
    full = bg3d.marching_tetrahedra(cube, [6.0], grid=g)[0]
    assert 2.0 in np.unique(np.round(full.vertices[:, 1], 9))


# ================================================================== 2. 网格与三轴


def test_make_grid3_aligns_inward_and_validates():
    g = bg3d.make_grid3([2500.0, 3750.0], [44.0, 96.0], [600.0, 1100.0], beta_step=125.0,
                        gamma_step=2.0, dv_step=50.0)
    assert g.beta == tuple(np.arange(2500.0, 3751.0, 125.0))
    assert g.gamma[0] == 44.0 and g.gamma[-1] == 96.0
    assert g.dv[0] == 600.0 and g.dv[-1] == 1100.0
    assert g.shape == (11, 27, 11) and g.n_cases == 11 * 27 * 11
    assert g.n_cells == (10, 26, 10)
    assert len(g.cells()) == g.n_cases and len(g.plane_cells()) == 11 * 27
    assert g.plane_cells()[0] == (2500.0, 44.0)     # γ 外层、β 内层
    with pytest.raises(ValueError):
        bg3d.make_grid3([2500.0, 3750.0], [44.0, 96.0], [600.0, 1100.0], beta_step=0.0)
    with pytest.raises(ValueError):
        bg3d.make_grid3([2500.0, 3750.0], [96.0, 44.0], [600.0, 1100.0], gamma_step=2.0)


def test_axis_invariants_are_the_contract():
    """三轴不变量（这是"等值面有意义"的前提，破了就是串轴、且图看起来正常）。"""
    p = bg.point_of(pool.standard_entry("PL-12"))
    m = pool.metrics_of(pool.standard_entry("PL-12"))
    eff = bg3d.axis_effects(p, m, beta=2600.0, gamma=90.0, dv=1100.0)
    # ΔV 是**真正独立**的第三根轴：只动 thrust_scale
    assert abs(eff["dv"]["thrust_scale"] - 1100.0 / m.dv) < 1e-12
    assert abs(eff["dv"]["cx_scale"] - 1.0) < 1e-12
    assert abs(eff["dv"]["cxaoa_scale"] - 1.0) < 1e-12
    # β 只动 cx_scale，γ 由不变量顶住
    assert abs(eff["beta"]["thrust_scale"] - 1.0) < 1e-12
    assert abs(eff["beta"]["cx_scale"] * eff["beta"]["cxaoa_scale"] - 1.0) < 1e-12
    # γ 只动 cxaoa_scale，且不变量正好等于 γ 的比值
    assert abs(eff["gamma"]["thrust_scale"] - 1.0) < 1e-12
    assert abs(eff["gamma"]["cx_scale"] - 1.0) < 1e-12
    assert abs(eff["gamma"]["cx_scale"] * eff["gamma"]["cxaoa_scale"]
               - 90.0 / p.gamma) < 1e-12


def test_scan_grids_contain_every_missile_in_the_pool():
    """粗/细两档网格必须**装得下全部 11 型弹**（否则"图上没有它"会被误读成"它不行"）。"""
    mod = _load_spike("bg3d_scan.py")
    rows_ = bg.rows(None)
    assert len(rows_) == 11
    for name in ("quick", "coarse", "fine"):
        g = mod.build(name)
        outside = mod.check_pool_inside(g, rows_)
        assert not outside, (name, outside)
        assert g.n_cases >= 84


def test_extrude_rejects_a_transposed_layer():
    """立方体切片是"行 = γ、列 = β"；转置过的等时线在图上同样像模像样，必须当场报错。"""
    betas = np.linspace(2500.0, 3000.0, 11)
    gammas = np.linspace(40.0, 100.0, 9)
    t2 = np.add.outer((gammas - 40.0) / 10.0, (betas - 2500.0) / 100.0) + 45.0
    s = bg3d.extrude_isolines(t2, beta=betas, gamma=gammas, level=46.0, dv_lo=600.0,
                              dv_hi=1100.0, base_dv=932.57)
    assert s.kind == "cylinder" and s.n_tri >= 2 and s.n_seg >= 1
    assert set(np.round(np.unique(s.vertices[:, 2]), 6)) <= {600.0, 1100.0}
    with pytest.raises(ValueError):
        bg3d.extrude_isolines(t2.T, beta=betas, gamma=gammas, level=46.0, dv_lo=600.0,
                              dv_hi=1100.0, base_dv=932.57)


# ================================================================== 3. 两种口径


def test_true_isosurface_spread_is_interpolation_error_only():
    """真等值面上 t_hit 的散布只剩插值误差（相对场跨度 < 1%）。"""
    g = bg3d.make_grid3([2000, 3000], [40, 90], [600, 1100], beta_step=100.0,
                        gamma_step=10.0, dv_step=100.0)
    cube = _linear_field(g, k_beta=0.001, k_gamma=0.03, k_dv=0.02, ref=(2500, 65, 900))
    scan = _fake_scan(g, cube)
    s = bg3d.marching_tetrahedra(cube, [50.0], grid=g)[0]
    sp = bg3d.iso_spread(scan, s)
    assert sp["spread_rel"] < 0.01, sp
    assert abs(sp["bias"]) < 0.01 * sp["field_span"], sp


def test_extruded_cylinder_is_not_an_isosurface():
    """把某一层的等时线沿 ΔV 拉成柱面 ⇒ 面上的 t_hit 散布与"ΔV 走完全程的变化"同量级。"""
    g = bg3d.make_grid3([2000, 3000], [40, 90], [600, 1100], beta_step=100.0,
                        gamma_step=10.0, dv_step=100.0)
    cube = _linear_field(g, k_beta=0.001, k_gamma=0.03, k_dv=0.02, ref=(2500, 65, 900))
    scan = _fake_scan(g, cube)
    cyl = bg3d.extrude_layer(scan, level=50.0, base_dv=900.0)
    sp = bg3d.iso_spread(scan, cyl)
    assert sp["spread_rel"] > 0.3, sp                 # 场跨度 ~11 s，柱面散布 ~10 s
    dep = bg3d.dv_dependence(scan, beta=2500.0, gamma=65.0)
    assert dep["span"] > 5.0 and dep["slope_s_per_ms"] > 0, dep


# ================================================================== 4. 依赖纪律


def test_module_has_no_heavy_third_party_dependency():
    """等值面必须自己算：源码里**真的**不许 import scipy / skimage / vtk …
    （文档里出现这些名字是允许的 —— 那正是在解释为什么不用它们；所以只看 AST 的 import。）"""
    src = (SRC / "missile_sim" / "bg3d.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.append("." * (node.level or 0) + (node.module or ""))
    heavy = [m for m in mods if m.split(".")[0] in
             {"scipy", "skimage", "sklearn", "trimesh", "pyvista", "vtk", "plotly", "pandas"}]
    assert not heavy, f"bg3d.py 引入了重依赖：{heavy}"
    allowed = {"__future__", "math", "time", "dataclasses", "typing", "numpy", "sys"}
    extra = sorted({m for m in mods if not m.startswith(".") and m.split(".")[0] not in allowed})
    assert not extra, f"bg3d.py 多了第三方依赖：{extra}"


# ================================================================== 5. 落盘证据


def _record(name: str):
    path = OUT / f"scan_{name}.json"
    _need(path, f"python spikes\\bg3d\\bg3d_scan.py --grid {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_saved_records_are_self_consistent():
    for name in ("coarse", "fine"):
        rec = _record(name)
        g = rec["grid"]
        shape = (len(g["dv"]), len(g["gamma"]), len(g["beta"]))
        assert tuple(g["shape"]) == shape, (name, g["shape"], shape)
        assert g["n_cases"] == shape[0] * shape[1] * shape[2]
        assert len(rec["t_hit"]) == shape[0]
        assert len(rec["t_hit"][0]) == shape[1] and len(rec["t_hit"][0][0]) == shape[2]
        # ΔV 是**输入列**，必须真的按步长铺开，而不是被钉死成一个值
        assert len(g["dv"]) >= 6 and len(set(g["dv"])) == len(g["dv"])
        assert min(g["dv"]) <= 600.0 and max(g["dv"]) >= 1100.0
        s = rec["summary"]
        assert s["tier"] == "fast"
        assert isinstance(s["backend"], str) and s["backend"]
        assert 0.9 <= s["hit_rate"] <= 1.0, s
        assert s["t_hit_range_s"][1] - s["t_hit_range_s"][0] > 8.0, s


def test_dv_axis_actually_changes_the_answer():
    """ΔV 轴的物理有效性：固定 (β, γ)，ΔV 越大 t_hit 越小，且跨度是秒级不是噪声级。"""
    rec = _record("fine")
    scan = bg3d.scan_from_record(rec)
    cube = scan.t_hit
    spans, decreasing = [], 0
    for j in range(cube.shape[1]):
        for k in range(cube.shape[2]):
            col = cube[:, j, k]
            if not np.isfinite(col).all():
                continue
            spans.append(col[0] - col[-1])
            if col[0] > col[-1] + 1.0:
                decreasing += 1
    assert len(spans) >= 200, len(spans)
    assert decreasing / len(spans) > 0.9, decreasing / len(spans)
    med = float(np.median(spans))
    assert med > 5.0, med                             # 与 dv_dependence 的量级一致


def test_record_round_trip_is_lossless():
    rec = _record("coarse")
    scan = bg3d.scan_from_record(rec)
    again = scan.record()
    assert again["t_hit"] == rec["t_hit"]
    assert again["hit"] == rec["hit"]
    assert again["grid"]["shape"] == rec["grid"]["shape"]


def test_saved_iso_report_proves_the_two_flavors_differ():
    path = ISO / "iso_report.json"
    _need(path, "python spikes\\bg3d\\bg3d_iso.py")
    rep = json.loads(path.read_text(encoding="utf-8"))
    iso = [r for r in rep["surfaces"] if r["kind"] == "iso"]
    cyl = [r for r in rep["surfaces"] if r["kind"] == "cylinder"]
    assert iso and cyl
    for r in iso:
        assert r["spread_rel"] < 0.02, r
    for r in cyl:
        assert r["spread_rel"] > 0.05, r
    assert rep["dv_dependence"][0]["span"] > 5.0, rep["dv_dependence"]
    for r in rep["surfaces"]:
        assert r["n_tri"] > 0 and r["area"] > 0


def test_vectorized_sampling_matches_scalar_reference():
    """向量化的 `sample_cube` 必须与**照着定义手写的标量版**逐点一致（含域外与 nan 格子）。

    向量化是为了性能（`_orient` 每张面上千个三角形），改错了只会让图"看着正常"：
    这里的参考实现是独立写的 8 项权重和，不复用被测代码里的任何插值函数。
    """
    rng = np.random.default_rng(20261001)
    g = bg3d.make_grid3([100.0, 160.0], [20.0, 44.0], [600.0, 800.0],
                        beta_step=10.0, gamma_step=4.0, dv_step=50.0)
    B, G, D = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma), np.asarray(g.dv),
                          indexing="ij")
    vals = np.transpose(7.0 + 0.02 * B + 0.3 * G - 0.01 * D, (2, 1, 0))   # (ΔV, γ, β)
    vals[1, 2, 1] = np.nan                                               # 挖一个未命中格子
    bx, gy, dz = (np.asarray(a, float) for a in g.coords())
    pts = np.column_stack([rng.uniform(90, 170, 600), rng.uniform(18, 46, 600),
                           rng.uniform(590, 810, 600)])

    def scalar_reference(b, gg, d):
        def cell(axis, v):
            n = len(axis)
            i = min(max(int(np.searchsorted(axis, v, side="right") - 1), 0), n - 2)
            f = (v - axis[i]) / (axis[i + 1] - axis[i])
            return (None, None) if (f < -1e-9 or f > 1.0 + 1e-9) else (i, min(max(f, 0.0), 1.0))

        i, tb = cell(bx, b)
        j, tg = cell(gy, gg)
        k, td = cell(dz, d)
        if i is None or j is None or k is None:
            return np.nan
        c = vals[k:k + 2, j:j + 2, i:i + 2]
        if not np.all(np.isfinite(c)):
            return np.nan
        w = np.array([(1 - tb) * (1 - tg) * (1 - td), tb * (1 - tg) * (1 - td),
                      (1 - tb) * tg * (1 - td), tb * tg * (1 - td),
                      (1 - tb) * (1 - tg) * td, tb * (1 - tg) * td,
                      (1 - tb) * tg * td, tb * tg * td])
        flat = np.array([c[0, 0, 0], c[0, 0, 1], c[0, 1, 0], c[0, 1, 1],
                         c[1, 0, 0], c[1, 0, 1], c[1, 1, 0], c[1, 1, 1]], float)
        return float(flat @ w)

    got = bg3d.sample_cube(vals, g, pts)
    want = np.array([scalar_reference(*p) for p in pts])
    both_nan = np.isnan(got) & np.isnan(want)
    assert both_nan.sum() > 0, "样本里应当既有域外点、也有落在挖空格子上的点"
    assert np.array_equal(np.isnan(got), np.isnan(want)), "域内/域外的判定不一致"
    m = ~np.isnan(want)
    assert np.abs(got[m] - want[m]).max() < 1e-12, np.abs(got[m] - want[m]).max()
    # 边界面属于域内（这是修过的那个坑）：ΔV = 上限、β = 下限都要插得出值
    edge = np.array([[bx[0], gy[0], dz[-1]], [bx[-1], gy[-1], dz[-1]]])
    assert np.isfinite(bg3d.sample_cube(vals, g, edge)).all()
    assert np.isnan(bg3d.sample_cube(vals, g, np.array([[bx[0] - 5.0, gy[0], dz[0]]]))).all()


def test_dv_quadratic_recovers_known_curvature():
    """二次项体检：**已知**抛物线场要把 `c` 还原出来，纯线性场要给出 0。

    这一条是"别把 `R² 0.989` 读成'ΔV 轴只有一个斜率'"的判据 —— 它必须能区分两者。
    """
    g = bg3d.make_grid3([100.0, 160.0], [20.0, 30.0], [600.0, 1100.0],
                        beta_step=60.0, gamma_step=10.0, dv_step=125.0)
    B, G, D = np.meshgrid(np.asarray(g.beta), np.asarray(g.gamma), np.asarray(g.dv),
                          indexing="ij")
    c_true = 2.0e-05
    span = float(np.asarray(g.dv).max() - np.asarray(g.dv).min())
    quad = np.transpose(5.0 + 0.01 * B + 0.2 * G - 0.03 * D + c_true * (D - 850.0) ** 2,
                        (2, 1, 0))
    q = bg3d.dv_quadratic(_fake_scan(g, quad))
    assert abs(q["c_abs_median"] / c_true - 1.0) < 1e-6, q["c_abs_median"]
    assert abs(q["curv_span_median_s"] - c_true * span ** 2 / 4.0) < 1e-9
    assert q["span_dv"] == span
    lin = np.transpose(5.0 + 0.01 * B + 0.2 * G - 0.03 * D, (2, 1, 0))
    q0 = bg3d.dv_quadratic(_fake_scan(g, lin))
    assert q0["c_abs_median"] < 1e-15, q0["c_abs_median"]
    assert q0["curv_span_median_s"] < 1e-12


def test_dv_axis_is_linear_but_with_measurable_curvature():
    """真实细网格记录上的口径：**一阶近乎线性（残差 0.55 s），但存在可测曲率**。

    实测（本机、本记录）：一次残差 RMS **0.5519 s** → 二次 **0.0582 s**（掉约 9.5 倍）；
    曲率在 ΔV 区间端点相对中点的抬升中位 **1.5449 s ≈ 该列 ΔV 效应的 9.2%**，
    且 459/459 列同号（不是正负各半的噪声）。所以"ΔV 轴只有一个斜率"这种说法**偏强**。
    """
    rec = _record("fine")
    scan = bg3d.scan_from_record(rec)
    lin, q = bg3d.dv_linearity(scan), bg3d.dv_quadratic(scan)
    assert abs(q["rms_resid_lin_s"] - lin["rms_resid_s"]) < 1e-12, "一次项口径必须与 dv_linearity 一致"
    assert q["n_col"] == lin["n_col"] == 459
    assert q["rms_resid_lin_s"] > 0.4 and q["rms_resid_s"] < 0.1, q
    assert q["rms_resid_lin_s"] / q["rms_resid_s"] > 5.0, "二次项应当把残差明显压下去"
    assert 0.05 < q["curv_frac_median"] < 0.20, q["curv_frac_median"]
    assert abs(q["curv_span_median_s"] - 1.5449) < 0.01, q["curv_span_median_s"]
    assert q["curv_smooth_frac"] == 1.0, "曲率符号必须一致（是系统性弯曲，不是噪声）"


def test_record_carries_run_and_cache_counts():
    """记录里必须能看出"这次到底真解算了几个工况"（热缓存的墙钟会骗人）。"""
    s = _record("fine")["summary"]
    assert s["n_cases"] == 5049 and s["n_run"] + s["n_cached"] == s["n_cases"], s
    assert s["n_cached"] >= 0 and s["n_run"] > 0
    assert isinstance(s["stats"], dict)


def test_geometry_indices_are_in_range_and_sample_is_committed():
    """几何自洽：索引不越界、`n_tri` 与三角形数一致。

    主判据**在内存里**对同一份落盘记录重提一次面（约 1.2 s），所以不依赖入库的几何文件；
    另外查一眼入库的小样（1 面 + 1 柱面）格式是否还能读。
    """
    mod = _load_spike("bg3d_iso.py")
    scan = bg3d.scan_from_record(_record("fine"))
    got = mod.extract(scan)
    groups = {"surfaces": got["iso"], "cylinders": got["cyl"]}
    assert groups["surfaces"] and groups["cylinders"]
    for name, items in groups.items():
        for s in items:
            V, T = np.asarray(s.vertices), np.asarray(s.triangles, dtype=int)
            assert T.size and T.min() >= 0 and T.max() < len(V), (name, s.level)
            assert s.n_tri == len(T)
            assert bg3d.surface_area(V, T) > 0
    sample = ISO / "iso_surfaces_sample.json"
    _need(sample, "python spikes\\bg3d\\bg3d_iso.py")
    pl = json.loads(sample.read_text(encoding="utf-8"))
    assert pl["kind"] == "bg3d-iso-sample" and pl["levels"]
    for group in ("surfaces", "cylinders"):
        assert pl[group], group
        for s in pl[group]:
            tri = np.asarray(s["triangles"], dtype=int)
            assert tri.size and tri.min() >= 0 and tri.max() < len(s["vertices"])
            assert s["n_tri"] == len(tri)


def test_cross_process_outputs_are_byte_identical():
    """渲染字节可复现：同进程两次 + 跨进程一次，三格式 sha256 必须逐键相同。"""
    a, b = OUT / "crossA.json", OUT / "crossB.json"
    _need(a, "python spikes\\bg3d\\bg3d_iso.py --cross --cross-dir spikes\\bg3d\\out")
    _need(b, "同样的命令再跑一次（另一个进程）")
    ra = json.loads(a.read_text(encoding="utf-8"))
    rb = json.loads(b.read_text(encoding="utf-8"))
    assert ra and len(ra) == len(rb)
    bad = []
    for x, y in zip(ra, rb):
        assert x["variant"] == y["variant"]
        diff = [k for k in x["sha"] if x["sha"].get(k) != y["sha"].get(k)]
        if diff:
            bad.append((x["variant"], diff))
    assert not bad, f"跨进程不一致（mplot3d 的深度排序不稳）：{bad}"

# -*- coding: utf-8 -*-
"""图3（task-24）的判据：**每枚弹一个标称三参数点**，等时面按需扫单弹立方体。

规格来源：task-24（Lead 2026-10-02 的裁决）。判据按"关系优先"写 ——
凡能从权威口径（`pool.metrics_of()` / `bg.point_of()`）现算出来的，就不写死常数。

| 层 | 判据 |
| --- | --- |
| 数据层 | 只读产物、不 import 求解器与 workflow；11 个点、顺序 = 弹池、坐标逐值等于权威口径 |
| 颜色/空心 | 有 t_hit ⇔ 实心且落在共享色标里；未命中 ⇔ 空心且 `t_hit_s is None` |
| 默认构建 | `solver.run` 调用次数 = **11**（不是 5929）；产物里**不存在** 539 长的格点数组 |
| 等时面 | 13 档契约；档位来自 `grid.iso_levels`（与图1/图2 同一套）；可出面判据 + 退化保护 |
| 立方体缓存 | 指纹覆盖 scene/tier/grid/弹名（改任一样 ⇒ 换 key）；命中缓存就不再重算 |
| 几何 | 解析平面上每个点的几何偏差 < 1e-6；椭球 level=1 必须闭合；0 命中层不出面 |
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import bg, bg3d, fig3, fig3scan, figures, pool, solver, workflow  # noqa: E402
from missile_sim.spec import Scene  # noqa: E402

PRODUCTS = fig3.default_paths("default")
N_MISSILES = 11
#: 按需立方体的工况数（11 ΔV × 7 β × 7 γ）—— 只作**契约**断言，不当"产物里有"来用。
CUBE_CASES = 539


def _products_exist() -> bool:
    return all(Path(p).is_file() for p in PRODUCTS.values())


pytestmark = pytest.mark.skipif(not _products_exist(),
                                reason="results/fig3_default.* 不在（先跑 --figure fig3）")


# ============================================================ 1. 数据层：11 个标称点


def test_fig3_data_layer_imports_no_solver_and_no_workflow():
    """数据层只能读产物：**不 import 求解器 / workflow**（这两个一进来就意味着会解算）。"""
    src = (ROOT / "src" / "missile_sim" / "fig3.py").read_text(encoding="utf-8")
    # 只看**真的 import 语句**：docstring/注释里提到 `solver.run` 是解释性的，不算违规
    for bad in ("from .solver", "from .engine", "from .workflow", "import solver",
                "import workflow", "import engine"):
        assert bad not in src, f"fig3.py 里出现了 {bad!r}"


def test_fig3_payload_is_eleven_nominal_points():
    """**11 个点**、顺序 = 弹池顺序、坐标逐值等于权威口径（关系判据，不写死常数）。"""
    d = fig3.build(dict(PRODUCTS), job="demo", tag="default")
    assert d["ok"] is True and d["figure"] == "fig3" and d["schema"] == fig3.SCHEMA == 3
    assert d["kind"] == figures.FIG3_KIND
    pts = d["points"]
    assert len(pts) == N_MISSILES == len(pool.names())
    assert [p["key"] for p in pts] == list(pool.names()), "顺序必须与弹池一致"
    for p in pts:
        entry = pool.resolve(p["key"])
        metrics = pool.metrics_of(entry)
        point = bg.point_of(entry)
        assert p["dv"] == pytest.approx(metrics.dv, abs=1e-3), p["key"]
        assert p["beta"] == pytest.approx(point.beta, abs=1e-3), p["key"]
        assert p["gamma"] == pytest.approx(point.gamma, abs=1e-3), p["key"]
        # 轴量与物理量**同时**入产物：`ginv` 是纵轴读数，`gamma` 是内核口径。
        # ⚠ 容差按**产物自己的位数**给（payload 里 ginv 6 位、gamma 3 位）：
        #   0.018694 × 53.494 = 1.0000383（相对 3.8e-5），拿两个**已四舍五入**的
        #   数去要求 1e-9 的乘积恒等是判据写错了，不是产物错了。
        assert p["ginv"] == pytest.approx(point.ginv, abs=5e-7), p["key"]
        assert p["ginv"] * p["gamma"] == pytest.approx(1.0, rel=1e-4), p["key"]
        # BC ≡ β（图1 的 BC 与图2 的 β 是同一个量）
        assert abs(metrics.bc - point.beta) < 1e-6, p["key"]
        # 标称点就是"三个乘数都取该弹自己" ⇒ 1/1/1（由 scaling3_for 现算，不是手写）
        sc = p["scaling"]
        assert sc["thrust_scale"] == pytest.approx(1.0, abs=1e-9), p["key"]
        assert sc["cx_scale"] == pytest.approx(1.0, abs=1e-9), p["key"]
        assert sc["cxaoa_scale"] == pytest.approx(1.0, abs=1e-9), p["key"]
    # 色标范围只在这 11 个**命中值**上共享
    hits = [p["t_hit_s"] for p in pts if p["hit"]]
    rng = d["shared"]["ranges"]["t_hit"]
    assert len(hits) == d["shared"]["n_hit"] == 7, f"默认工况应当是 7 命中 / 4 未命中：{hits}"
    assert d["shared"]["n_miss"] == 4
    assert rng[0] == pytest.approx(min(hits), abs=1e-4)
    assert rng[1] == pytest.approx(max(hits), abs=1e-4)
    # 11 个弹名常显（契约里给全）
    assert d["labels"]["always"] is True
    assert d["labels"]["names"] == [p["key"] for p in pts]
    assert len(d["labels"]["names"]) == N_MISSILES


def test_fig3_solid_iff_has_t_hit():
    """**关系判据**：`hit=True ⇔ t_hit_s 有值`；未命中一律 `None`（绝不拿 t_end 冒充）。"""
    d = fig3.build(dict(PRODUCTS))
    for p in d["points"]:
        assert p["hit"] is (p["t_hit_s"] is not None), p["key"]
        if not p["hit"]:
            assert p["t_hit_s"] is None and p["event"], p["key"]
            assert p["t_end_s"] is not None, f"{p['key']}：未命中也要有终止时刻"
    # 命中/脱靶的两套标记语义务必还在
    assert d["markers"]["hit"] == "dot" and d["markers"]["miss"] == "hollow"
    assert d["legend"]["hit"] == figures.FIG3_LEGEND_HIT
    assert d["legend"]["miss"] == figures.FIG3_LEGEND_MISS
    assert d["colors"]["miss"] == figures.FIG3_MISS_COLOR
    assert d["colors"]["miss"] not in d["colors"]["cmap"]["t_hit"]


def test_fig3_product_has_no_grid_cloud_and_no_fits():
    """**反向判据**：默认产物里不许有格点云、判别量、逐列拟合（防"删不干净"）。"""
    rec = fig3.read_record(PRODUCTS["record"])
    assert rec["schema"] == 3 and rec["summary"]["data_source"].startswith("每枚弹的标称三参数点")
    assert rec["summary"]["n_missiles"] == N_MISSILES
    for m in rec["missiles"]:
        for gone in ("t_hit", "hit_rate", "columns", "fit", "plane", "R_ref", "n_star_g",
                     "q_sens", "n_cases"):
            assert gone not in m, f"{m['key']} 里还留着格点时代的 {gone!r}"
        for key in ("dv", "beta", "ginv", "hit", "t_hit_s", "event"):
            assert key in m, f"{m['key']} 缺 {key!r}"
    # 默认网格契约仍然在（按需扫描要用），但**没有任何 539 长的数组**
    assert rec["grid"]["shape"] == [11, 7, 7] and rec["grid"]["n_cases"] == CUBE_CASES
    assert rec["layer"]["n_levels"] == fig3.LAYER_COUNT == 13
    blob = json.dumps(rec, ensure_ascii=False)
    assert '"t_hit": [[' not in blob, "默认产物里出现了立方体数组"
    d = fig3.build(dict(PRODUCTS))
    for gone in ("clouds", "fit", "heatmap", "induced", "ref_condition"):
        assert gone not in d, f"payload 里还留着 {gone!r}"


def test_fig3_cases_csv_is_one_row_per_missile():
    """标称点表：**一行一枚弹**、列名 = `fig3scan.NOMINAL_CASES`、`cpa_m` 留空。"""
    rows = fig3.read_csv_rows(PRODUCTS["cases"])
    assert tuple(rows[0].keys()) == fig3scan.NOMINAL_CASES
    assert len(rows) == N_MISSILES
    assert [r["missile"] for r in rows] == list(pool.names())
    for r in rows:
        assert r["hit"] in ("0", "1")
        if r["hit"] == "0":
            assert r["t_hit_s"] == "", "未命中不许写 0（那会被读成'瞬间命中'）"
            assert r["t_end_s"] != ""
        assert r["cpa_m"] == "", "cpa 在扫描路径上不量（A5：那是交会距离，不是脱靶量）"
        assert abs(float(r["thrust_scale"]) - 1.0) < 1e-9
        assert r["backend"] and r["backend"] != "not-run"


def test_fig3_default_build_solves_only_the_nominal_points():
    """**默认构建里不许扫立方体**：`solver.run` 调用次数 = 11（不是 5929）。"""
    calls = {"n": 0}
    orig = solver.run

    def spy(*args, **kw):                      # `solver.run(scene, *, missile, scaling, ...)`
        calls["n"] += 1
        return orig(*args, **kw)

    req = workflow.Fig3Request(tag="nominal_probe", cache=False)   # 关缓存：11 次都是真解算
    solver.run = spy
    out = None
    try:
        out = workflow.run_fig3(req)
    finally:
        solver.run = orig
        for p in ((out or {}).get("_paths") or {}).values():
            Path(str(p)).unlink(missing_ok=True)
    assert calls["n"] == N_MISSILES, f"默认构建解了 {calls['n']} 次（应当 {N_MISSILES} 次）"
    assert out["n_run"] + out["n_cached"] == N_MISSILES
    assert out["n_hit"] == 7 and out["n_miss"] == 4
    rec = fig3.read_record(PRODUCTS["record"])
    assert "t_hit" not in rec["missiles"][0]


def test_fig3_nominal_matches_a_direct_engine_run():
    """数值一致性：标称点的 `t_hit` 与"手工起一次 `Engine` 解同一个工况"逐位一致。"""
    from missile_sim.engine import Engine

    entry = pool.resolve("PL-12")
    metrics = pool.metrics_of(entry)
    point = bg.point_of(entry)
    scene = workflow.fig3_scene(workflow.Fig3Request())
    eng = Engine(scene, missile=entry.native, tier="fast", jobs=1, cache=True, metrics=metrics,
                 scaling_of=lambda b, g: bg3d.scaling3_for(point, metrics, beta=b, ginv=g,
                                                           dv=metrics.dv))
    try:
        shot = eng.many([(point.beta, point.ginv)])[0]
    finally:
        eng.close()
    rec = fig3.read_record(PRODUCTS["record"])
    want = [m for m in rec["missiles"] if m["key"] == "PL-12"][0]
    assert bool(shot.hit) is bool(want["hit"])
    if want["hit"]:
        assert float(shot.t_hit) == pytest.approx(float(want["t_hit_s"]), abs=1e-6)


# ============================================================ 2. 立方体缓存指纹


def _cube_args(**over):
    base = {"scene": Scene().as_dict(), "tier": "fast",
            "grid": {"beta": (2500.0, 3000.0, 3500.0), "ginv": (0.011, 0.014, 0.020),
                     "dv": (700.0, 1000.0, 1300.0), "beta_step": 500.0,
                     "ginv_step": 0.003, "dv_step": 300.0},
            "missile": "PL-12"}
    base.update(over)
    return base


def test_fig3_cube_key_covers_scene_tier_grid_and_missile():
    """指纹**至少**覆盖四样：工况 / 档位 / 网格 / 弹名（改任一样 ⇒ 换 key）。"""
    a = _cube_args()
    k0 = fig3.cube_key(a["scene"], a["tier"], a["grid"], a["missile"])
    assert len(k0) == 8 and all(c in "0123456789abcdef" for c in k0)
    assert fig3.cube_key(a["scene"], a["tier"], a["grid"], a["missile"]) == k0, "同输入必须同 key"
    # ① 工况（含 maneuvers）
    assert fig3.cube_key(dict(a["scene"], range_m=60000.0), a["tier"], a["grid"],
                         a["missile"]) != k0
    man = dict(a["scene"], maneuvers=[[0.0, [0.0, 0.0, -9.8]], [5.0, [0.0, 0.0, 0.0]]])
    assert fig3.cube_key(man, a["tier"], a["grid"], a["missile"]) != k0, "maneuvers 也要进 key"
    # ② 档位
    assert fig3.cube_key(a["scene"], "standard", a["grid"], a["missile"]) != k0
    # ③ 网格（同区间、点数不同）
    g2 = dict(a["grid"], dv=(700.0, 1000.0))
    assert fig3.cube_key(a["scene"], a["tier"], g2, a["missile"]) != k0
    # ④ 弹名
    assert fig3.cube_key(a["scene"], a["tier"], a["grid"], "R-77") != k0


def test_fig3_cube_round_trip_and_fingerprint_check(tmp_path):
    """写→读一遍：指纹对得上才认；工况/档位一改就当没有（**宁可重算，不许撒谎**）。"""
    a = _cube_args()
    paths = fig3.cube_path(a["missile"], scene=a["scene"], tier=a["tier"], grid=a["grid"],
                           result_dir=tmp_path)
    assert Path(paths["cube"]).name.startswith("fig3_cube_PL-12_")
    blob = {"schema": fig3.CUBE_SCHEMA, "kind": "fig3-cube", "cube_key": paths["cube_key"],
            "missile": "PL-12", "tier": "fast", "scene": a["scene"], "grid": a["grid"],
            "t_hit": [[[None, None], [None, None]], [[None, None], [None, None]]]}
    fig3.write_cube(paths["cube"], blob)
    got = fig3.read_cube(paths["cube"], missile="PL-12", scene=a["scene"], tier=a["tier"],
                         grid=a["grid"])
    assert got["cube_key"] == paths["cube_key"]
    with pytest.raises(ValueError, match="指纹对不上"):
        fig3.read_cube(paths["cube"], missile="PL-12",
                       scene=dict(a["scene"], range_m=1.0), tier=a["tier"], grid=a["grid"])
    with pytest.raises(ValueError, match="指纹对不上"):
        fig3.read_cube(paths["cube"], missile="PL-12", scene=a["scene"], tier="standard",
                       grid=a["grid"])


# ============================================================ 3. 等时面（几何 + 退化）


def _synth_grid(nb=7, ng=7, nd=11):
    """合成网格（**与真实弹池无关**，只用来验几何）。

    ⚠ 纵轴自 2026-10-04 起是 `ginv = 1/γ [m²/kg]`：γ 49~96 对应的 ginv 是
    0.0104~0.0204，所以这里直接给 ginv 的干净数（`b`/`c` 那类系数也要跟着改量级）。
    """
    beta = tuple(np.linspace(2500.0, 3760.0, nb))
    ginv = tuple(np.linspace(0.0104, 0.0204, ng))
    dv = tuple(np.linspace(700.0, 1700.0, nd))
    return bg3d.Bg3Grid(beta=beta, ginv=ginv, dv=dv, beta_step=beta[1] - beta[0],
                        ginv_step=ginv[1] - ginv[0], dv_step=dv[1] - dv[0])


def test_fig3_iso_surface_matches_an_analytic_plane():
    """**几何判据**：合成解析平面上每个点的场残差 ≤ 1e-6（实测 ~1e-14）；椭球必须闭合。"""
    grid = _synth_grid()
    B = np.asarray(grid.beta)[None, None, :]
    G = np.asarray(grid.ginv)[None, :, None]
    D = np.asarray(grid.dv)[:, None, None]
    # ⚠ `b` 是**纵轴的量级系数**：纵轴从 γ(49~96) 换成 ginv(0.0104~0.0204) 后，
    #   要保住同一份几何（G 项贡献 2.45~4.8），`b` 必须从 0.05 放大到 ~240。
    #   不改的话 G 项被压成噪声、等值面退化成"斜切盒子"，闭合性判据当场变红。
    a, b, c, t0 = -0.004, 240.0, -0.02, 60.0
    field = a * B + b * G + c * D + t0
    lo, hi = float(field.min()), float(field.max())
    levels = [lo + (hi - lo) * q for q in (0.25, 0.5, 0.75)]
    grad = (a * a + b * b + c * c) ** 0.5
    for r in bg3d.iso_surfaces(field, grid=grid, levels=levels):
        assert r["ok"], r["reason"]
        V = np.asarray(r["vertices"], dtype=float)
        resid = np.abs(a * V[:, 0] + b * V[:, 1] + c * V[:, 2] + t0 - r["level"])
        assert float(resid.max()) < 1e-6, (r["level"], float(resid.max()))
        assert float(resid.max()) / grad < 1e-6
        assert r["closed"] is False and r["n_boundary"] > 0      # 一张切成两半的平面
    A2, B2, C2 = 400.0, 12.0, 250.0
    # 椭球中心/半径同样换算到 ginv：γ 中心 72 → ginv 1/72 = 0.013889；
    # 半径按跨度等比缩放（γ 半径 12/跨度 47 ≈ 25.5% ⇒ ginv 0.0026/跨度 0.010）
    ell = ((B - 3100.0) / A2) ** 2 + ((G - 0.013889) / 0.0026) ** 2 + ((D - 1200.0) / C2) ** 2
    r = bg3d.iso_surfaces(ell, grid=grid, levels=[1.0])[0]
    assert r["ok"] and r["closed"] is True and r["n_boundary"] == 0


def test_fig3_degenerate_layers_are_not_produced():
    """**退化保护**：全 NaN / 层在命中区外 / 角落碎片 ⇒ `ok=False` + 一句能显示的理由。"""
    grid = _synth_grid()
    r = bg3d.iso_surfaces(np.full(grid.shape, np.nan), grid=grid, levels=[45.0])[0]
    assert r["ok"] is False and len(r["triangles"]) == 0 and "命中" in r["reason"]
    r = bg3d.iso_surfaces(np.full(grid.shape, 50.0), grid=grid, levels=[1000.0])[0]
    assert r["ok"] is False and r["n_cells"] == 0 and "出不了面" in r["reason"]
    v = np.full(grid.shape, 10.0)
    v[0, 0, 0] = 100.0
    r = bg3d.iso_surfaces(v, grid=grid, levels=[50.0])[0]
    assert r["ok"] is False and r["n_cells"] <= 2
    r2 = bg3d.iso_surfaces(np.full(grid.shape, 50.0), grid=grid, levels=[50.0],
                           min_cells=10 ** 6)[0]
    assert r2["ok"] is False and r2["reason"]


def test_fig3_layer_levels_come_from_the_shared_iso_levels():
    """档位不是另写一套：`layer_levels()` 是 `grid.iso_levels()` 的等距子集（打桩数调用）。"""
    import missile_sim.grid as grid_mod
    cube = np.full((11, 7, 7), np.nan)
    cube[3:, :, :] = np.linspace(40.0, 60.0, 8 * 7 * 7).reshape(8, 7, 7)
    calls = []
    orig = grid_mod.iso_levels

    def spy(values, step):
        out = orig(values, step)
        calls.append((len(out), float(step)))
        return out

    grid_mod.iso_levels = spy
    try:
        levels = fig3.layer_levels(cube, step=1.0, count=13)
    finally:
        grid_mod.iso_levels = orig
    assert calls == [(21, 1.0)], calls
    assert len(levels) == 13 and levels == sorted(set(levels))
    all_levels = orig(cube, 1.0)
    assert set(levels) <= set(all_levels) and levels[0] == min(all_levels)
    assert levels[-1] == max(all_levels)


def test_fig3_layers_from_a_cube_fixture(tmp_path):
    """有立方体时：一次给全 N 层（含 `ok/reason/closed`），顶层索引不越界；没立方体抛 `CubeMissing`。"""
    rec = fig3.read_record(PRODUCTS["record"])
    entry = pool.resolve("PL-12")
    scene = workflow.fig3_scene(workflow.Fig3Request())
    grid = bg3d.Bg3Grid(beta=tuple(rec["grid"]["beta"]), ginv=tuple(rec["grid"]["ginv"]),
                        dv=tuple(rec["grid"]["dv"]), beta_step=rec["grid"]["beta_step"],
                        ginv_step=rec["grid"]["ginv_step"], dv_step=rec["grid"]["dv_step"])
    out = fig3scan.run_cube(scene, entry, grid=grid, tier="fast", jobs=1, cache=True,
                            layer=dict(rec["layer"]), standard=rec["standard"],
                            result_dir=tmp_path)
    # 走**生产入口**读回来（它会把产物里的 solver 指纹带上，指纹才对得上）
    cube = fig3scan.read_cube_or_none(scene, entry, grid=grid, tier="fast",
                                      result_dir=tmp_path)
    assert cube is not None and cube["cache_read_hit"] is True
    assert Path(cube["_path"]) == Path(out["cube"])
    blob = fig3.layers_payload(dict(PRODUCTS), missile="PL-12", cube=cube)
    lay, surfs = blob["layers"], blob["surfaces"]
    assert lay["n_levels"] == fig3.LAYER_COUNT == len(surfs)
    assert [s["level"] for s in surfs] == lay["levels"]
    assert [s["label"] for s in surfs] == lay["labels"]
    assert len(set(lay["levels"])) == len(lay["levels"])
    assert len([s for s in surfs if s["ok"]]) >= 6
    for s in surfs:
        if s["ok"]:
            assert len(s["vertices"]) == s["n_vert"] * 3
            assert len(s["triangles"]) == s["n_tri"] * 3
            assert max(s["triangles"] or [0]) < s["n_vert"]
        else:
            assert s["reason"] and s["triangles"] == [] and s["vertices"] == []
    with pytest.raises(KeyError):
        fig3.layers_payload(dict(PRODUCTS), missile="NOPE", cube=cube)
    with pytest.raises(fig3.CubeMissing):
        fig3.layers_payload(dict(PRODUCTS), missile="PL-12", cube=None)


# ============================================================ 4. CLI 端到端


def test_fig3_cli_regenerates_nominal_products_end_to_end():
    """`--figure fig3` 一条命令重出标称点产物（**不扫立方体**，秒级）。"""
    tag = "cli_unittest"
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(ROOT / "src")})
    proc = subprocess.run(
        [sys.executable, "-m", "missile_sim", "--figure", "fig3", "--tag", tag,
         "--missiles", "PL-12,R-77", "--fig3-t-react", "35", "--jobs", "1", "--quiet"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    paths = fig3.default_paths(tag)
    try:
        rec = fig3.read_record(paths["record"])
        assert rec["schema"] == 3 and rec["tag"] == tag
        assert rec["summary"]["n_missiles"] == 2
        assert rec["summary"]["n_run"] + rec["summary"]["n_cached"] == 2, "只解 2 次"
        assert not list(Path(ROOT / "results").glob(f"fig3_cube_*_{tag}*")), "默认构建不许扫立方体"
        rows = fig3.read_csv_rows(paths["cases"])
        assert len(rows) == 2 and {r["missile"] for r in rows} == {"PL-12", "R-77"}
        d = fig3.build(paths, tag=tag)
        assert len(d["points"]) == 2 and d["grid"]["n_cases"] == CUBE_CASES
        assert d["shared"]["ranges"]["t_hit"] is not None
    finally:
        for p in paths.values():
            Path(p).unlink(missing_ok=True)


def test_fig3_payload_is_strict_json():
    """响应必须是**严格 JSON**（裸 `NaN` 会让 `JSON.parse` 抛错、页面白屏）。"""
    d = fig3.build(dict(PRODUCTS))
    blob = json.dumps(d, ensure_ascii=False, allow_nan=False)
    assert "NaN" not in blob and "Infinity" not in blob
    assert json.loads(blob)["figure"] == "fig3"
    assert any(p["t_hit_s"] is None for p in d["points"]), "这一份里必须有未命中的点"

# ============================================================ 5. 补：等价判据（不跑重活）


def test_fig3_nominal_cells_are_the_pool_nominals():
    """`fig3scan.nominal_cells()` 就是弹池的标称三参数（数据层与算核**同一个口径**）。"""
    cells = fig3scan.nominal_cells(pool.resolve_many(None))
    assert [c["entry"].key for c in cells] == list(pool.names())
    for c in cells:
        assert c["dv"] == pytest.approx(pool.metrics_of(c["entry"]).dv, abs=1e-9)
        assert c["beta"] == pytest.approx(bg.point_of(c["entry"]).beta, abs=1e-9)
        assert c["gamma"] == pytest.approx(bg.point_of(c["entry"]).gamma, abs=1e-9)
        assert c["ginv"] == pytest.approx(bg.point_of(c["entry"]).ginv, abs=1e-12)
        assert c["native"] == c["entry"].native


def test_fig3_grid_contract_round_trips_the_scan_grid():
    """`fig3scan.grid_of()` 造的网格 → 产物里的 `grid` 块 → `grid_contract()` 逐值回来。"""
    rows = bg.rows(pool.resolve_many(None))
    g = fig3scan.grid_of(rows, dv_pin=fig3.DV_PIN_MS, n_beta=7, n_ginv=7,
                         dv_lim=fig3.DV_LIM, n_dv=fig3.N_DV)
    got = fig3.grid_contract(dict(g.as_dict(), limits=g.limits()))
    assert got["shape"] == [fig3.N_DV, fig3.N_GINV, fig3.N_BETA] == list(g.shape)
    assert got["n_cases"] == g.n_cases == CUBE_CASES
    assert got["beta"] == pytest.approx(list(g.beta), abs=1e-9)
    assert got["ginv"] == pytest.approx(list(g.ginv), abs=1e-9)
    assert got["dv"] == pytest.approx(list(g.dv), abs=1e-9)
    assert got["dv"][0] == fig3.DV_LIM[0] and got["dv"][-1] == fig3.DV_LIM[1]
    # β、γ 必须罩住 11 弹的标称值（否则点会掉出盒子）
    for p in fig3.build(dict(PRODUCTS))["points"]:
        assert got["beta"][0] <= p["beta"] <= got["beta"][-1], p["key"]
        assert got["ginv"][0] <= p["ginv"] <= got["ginv"][-1], p["key"]


def test_fig3_flat_order_matches_bg3d_cells():
    """展平顺序 = `bg3d.Bg3Grid.cells()` 的顺序（ΔV 外层 → γ → β），前后端只能有这一套。"""
    g = fig3scan.grid_of(bg.rows(pool.resolve_many(None)), dv_pin=fig3.DV_PIN_MS,
                         n_beta=3, n_ginv=4, dv_lim=fig3.DV_LIM, n_dv=5)
    mine = fig3.flat_cells(g.beta, g.ginv, g.dv)
    assert mine == [(float(d), float(b), float(gm)) for d, b, gm in g.cells()]
    assert fig3.column_cells(g.beta, g.ginv) == [(float(b), float(gm))
                                                 for gm in g.ginv for b in g.beta]
    assert fig3.FLAT_ORDER.startswith("ΔV 外层")
    assert fig3.build(dict(PRODUCTS))["grid"]["flat_order"] == fig3.FLAT_ORDER


def test_fig3_layer_contract_declares_the_cube_endpoint():
    """层契约把"按需立方体"这套讲清楚：档数 / 步长 / 门槛 / 接口 / 缓存位置 / 工况数。"""
    lay = fig3.build(dict(PRODUCTS))["layers"]
    assert lay["n_levels"] == fig3.LAYER_COUNT and lay["iso_step"] == 1.0
    assert lay["min_cells"] == fig3.LAYER_MIN_CELLS and lay["min_tri"] == fig3.LAYER_MIN_TRI
    assert lay["endpoint"] == "/api/fig3/<id>/layers?missile="
    assert lay["cube"]["cases"] == CUBE_CASES
    assert "fig3_cube_" in lay["cube"]["cache"]
    assert "iso_levels" in lay["source"], "层定义必须指向图1/图2 用的那个函数"


def test_fig3_cases_csv_has_no_grid_discriminators():
    """标称点表**没有**格点时代的判别量列（`n_star_g` / `R_ref` / `induced_dominated`）。"""
    head = tuple(fig3.read_csv_rows(PRODUCTS["cases"])[0].keys())
    for gone in ("n_star_g", "R_ref", "induced_dominated", "resid_lin", "rms_lin", "curv_frac"):
        assert gone not in head, gone
    for need in ("missile", "dv", "beta", "ginv", "gamma", "hit", "t_hit_s",
                 "thrust_scale"):
        assert need in head, need
    assert head == fig3scan.NOMINAL_CASES


def test_fig3_axes_are_the_scan_grid_endpoints():
    """三根轴的刻度 = 扫描网格的值，轴名/轴色现取 `figures`（前端不写死）。"""
    d = fig3.build(dict(PRODUCTS))
    axes = {a["id"]: a for a in d["axes"]}
    assert set(axes) == {"beta", "dv", "ginv"}
    assert axes["beta"]["limits"] == [d["grid"]["beta"][0], d["grid"]["beta"][-1]]
    assert axes["dv"]["limits"] == [700.0, 1700.0]
    assert len(axes["beta"]["ticks"]) == fig3.N_BETA
    assert len(axes["dv"]["ticks"]) == fig3.N_DV
    for a in axes.values():
        assert a["label"] == figures.FIG3_AXIS_LABELS[a["id"]]
        assert a["color"] == figures.FIG3_AXIS_COLORS[a["id"]]


def test_fig3_palette_legend_modes_come_from_figures_key_by_key():
    """配色 / 图例 / 颜色模式**逐键**等于 `figures` 里的那一份（前端零颜色字面量的前提）。"""
    pal = fig3.palette()
    assert pal["hit"] == figures.FIG3_HIT_COLOR and pal["miss"] == figures.FIG3_MISS_COLOR
    assert pal["bg"] == figures.FIG3_BG_COLOR and pal["text"] == figures.FIG3_TEXT_COLOR
    assert pal["box"] == figures.FIG3_BOX_COLOR and pal["muted"] == figures.FIG3_MUTED_COLOR
    assert pal["cmap"]["t_hit"] == list(figures.FIG3_CMAP_T_HIT)
    assert pal["axis"] == dict(figures.FIG3_AXIS_COLORS)
    assert pal["layer_alpha"] == figures.FIG3_LAYER_ALPHA
    assert [m["id"] for m in fig3.modes()] == [m["id"] for m in figures.FIG3_MODES]
    assert fig3.legend()["hit"] == figures.FIG3_LEGEND_HIT
    assert fig3.legend()["miss"] == figures.FIG3_LEGEND_MISS
    assert fig3.hex_to_rgb("#ffffff") == [1.0, 1.0, 1.0]
    with pytest.raises(ValueError):
        fig3.hex_to_rgb("#fff")


def test_fig3_reading_the_cube_never_rewrites_it(tmp_path):
    """**读缓存不许回写**（Lead 2026-10-02 验收的缺陷）：连读两次，sha256 与 mtime 都不变。

    这条比"能命中缓存"更重要：命中却回写会让**每看一次页面就把仓库弄脏**
    （`M results/fig3_cube_*.json`，差异只有 `elapsed_s`），并且让"重出产物逐字节一致"变成假话。
    """
    import hashlib
    import time as _time

    entry = pool.resolve("PL-12")
    scene = workflow.fig3_scene(workflow.Fig3Request())
    g = bg3d.Bg3Grid(beta=(2560.0, 2700.0), ginv=(0.010, 0.011), dv=(700.0, 800.0),
                     beta_step=140.0, ginv_step=0.001, dv_step=100.0)
    # 先**手写**一份缓存（模拟仓库里那份预扫好的），再走所有"读"路径
    blob = {"schema": fig3.CUBE_SCHEMA, "kind": "fig3-cube", "missile": "PL-12", "tier": "fast",
            "scene": scene.as_dict(), "grid": g.as_dict(), "solver": dict(solver.identity()),
            "t_hit": [[[None, None], [None, None]], [[None, None], [None, None]]],
            "summary": {"n_cases": 8, "n_hit": 0, "n_ok": 8, "backend": "compiled-c"}}
    paths = fig3.cube_path("PL-12", scene=scene.as_dict(), tier="fast", grid=g.as_dict(),
                           result_dir=tmp_path, solver_sha=str(solver.identity()["sha256"]))
    blob["cube_key"] = paths["cube_key"]
    fig3.write_cube(paths["cube"], blob)
    p = Path(paths["cube"])
    before = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    # ① 直接读两次
    for _ in range(2):
        got = fig3scan.read_cube_or_none(scene, entry, grid=g, tier="fast", result_dir=tmp_path)
        assert got is not None and got["cache_read_hit"] is True
    # ② `run_cube()`（"按需扫"的入口）也不该写
    out = fig3scan.run_cube(scene, entry, grid=g, tier="fast", jobs=1, cache=True,
                            layer={}, standard="PL-12", result_dir=tmp_path)
    assert out["read_hit"] is True and out.get("written") is not True
    # ③ `scan_fig3_cube(force=False)` 同样
    _time.sleep(0.01)
    after = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    assert after == before, f"读路径把缓存改写了：{before} → {after}"


def test_fig3_cube_file_has_no_run_metadata(tmp_path):
    """缓存文件里**没有**"本次运行"的元数据（`elapsed_s` / `n_run` / `n_cached`）。

    它们随"冷跑还是命中引擎缓存"变 ⇒ 写进文件就等于放弃"重出产物逐字节一致"。
    """
    entry = pool.resolve("PL-12")
    scene = workflow.fig3_scene(workflow.Fig3Request())
    rec = fig3.read_record(PRODUCTS["record"])
    g = bg3d.Bg3Grid(beta=(2560.0, 2700.0), ginv=(0.010, 0.011), dv=(700.0, 800.0),
                     beta_step=140.0, ginv_step=0.001, dv_step=100.0)
    out = fig3scan.run_cube(scene, entry, grid=g, tier="fast", jobs=1, cache=True,
                            layer=dict(rec["layer"]), standard=rec["standard"],
                            result_dir=tmp_path)
    blob = json.loads(Path(out["cube"]).read_text(encoding="utf-8-sig"))
    assert set(blob["summary"]) == {"n_cases", "n_hit", "n_ok", "backend"}, blob["summary"]
    assert "elapsed_s" not in json.dumps(blob)
    assert blob["summary"]["n_cases"] == 8


def test_fig3_cube_read_hit_means_no_rescan(tmp_path):
    """**缓存命中 ⇒ 不再重算**：小网格真扫一次，第二次 `read_cube_or_none` 直接命中。"""
    entry = pool.resolve("PL-12")
    scene = workflow.fig3_scene(workflow.Fig3Request())
    rec = fig3.read_record(PRODUCTS["record"])
    g = bg3d.Bg3Grid(beta=(2560.0, 2700.0), ginv=(0.010, 0.011), dv=(700.0, 800.0),
                     beta_step=140.0, ginv_step=0.001, dv_step=100.0)
    first = fig3scan.run_cube(scene, entry, grid=g, tier="fast", jobs=1, cache=True,
                              layer=dict(rec["layer"]), standard=rec["standard"],
                              result_dir=tmp_path)
    assert first["read_hit"] is False and Path(first["cube"]).is_file()
    again = fig3scan.read_cube_or_none(scene, entry, grid=g, tier="fast", result_dir=tmp_path)
    assert again is not None, "第二次必须命中缓存"
    assert again["cache_read_hit"] is True and again["cube_key"] == first["cube_key"]
    assert again["summary"]["n_cases"] == 8          # 2 β × 2 γ × 2 ΔV

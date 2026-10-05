# -*- coding: utf-8 -*-
"""阶段 C · W2 判据：`workflow.overlay_plane()` / `overlay_bg()` **只产 JSON**。

四条（对应计划文档 `docs/STATIC-LAYER-REALTIME.md` §阶段 C 的第一条）：

1. **形状**：顶层六个键齐（`kind`/`keys`/`axis`/`iso_lines`/`notes`/`identity`）、`iso_lines` 每级
   `points` 是 `[[x, y], …]`、坐标落在 `axis` 内（容差见 `_INSIDE_TOL`）、可 `json.dumps`；
2. **同源**：`iso_lines` 与 matplotlib 那条算路（`figures.adaptive_axis`/`bg_axis` →
   `grid.make_grid` → `Engine.many` → `grid.t_hit_matrix` → `grid.extract_isolines`）**逐级逐点同值**
   —— 这一层没有自己的物理与几何；
3. **只产数据**：跑完不落图（`figures/` 一个文件都不变）、不留打开的 figure、产物是纯 JSON；
4. **反证**：把轴换成硬编码范围 ⇒ 轴口径判据必须红（否则"轴必须来自 oracle"这条没牙）。

⚠ 关于"不 import matplotlib"（计划里原本的 ③）：**现状做不到**，而且不是本层能决定的 ——
`grid.py` 与 `figures.py` 都在模块顶层 `import matplotlib`（`grid._contour_segments` 用 Agg 的
一次性 figure 取等值段），而本层的轴与等时线**必须**走它们才谈得上"与成品同值"。
所以这条判据写成"**不落图 + 不留 figure + 不写文件**"（真需求），并把依赖现状记在
`workflow.py` 的注释里；要零 matplotlib 就得另写一套纯 marching squares + 纯轴实现，
那时与成品的比对只能按容差 —— 那是一个独立决定（见回报）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import matplotlib.pyplot as plt                                  # noqa: E402
import pytest                                                    # noqa: E402

from missile_sim import figures, grid as grid_mod, pool, workflow    # noqa: E402
from missile_sim.engine import Engine                            # noqa: E402
from missile_sim.spec import FIG_DIR, AxisSpec, Scene            # noqa: E402

#: 坐标"在轴内"的容差：等值线端点是格点上的线性插值，实测有 `3e-13` 量级的浮点出界，
#: 那是数值噪声而不是口径问题（真正画错会差出几十上百个单位）。
_INSIDE_TOL = 1e-6

#: 判据用的弹子集与网格步长：**故意很小**（2 型 × 十几格），保证这一组秒级跑完。
KEYS = ("PL-12", "MICA")
PLANE_KW = dict(dv_step=10.0, bc_step=200.0, iso_step=5.0)
BG_KW = dict(beta_step=300.0, ginv_step=0.002, iso_step=5.0)


def _inside(points, axis) -> list:
    """返回越界的点（超出 `_INSIDE_TOL` 才算）。"""
    (x0, x1), (y0, y1) = axis["xlim"], axis["ylim"]
    return [p for p in points
            if not (x0 - _INSIDE_TOL <= p[0] <= x1 + _INSIDE_TOL
                    and y0 - _INSIDE_TOL <= p[1] <= y1 + _INSIDE_TOL)]


def _matplotlib_lines_plane(**kw) -> tuple:
    """**不落图**地把 matplotlib 那条算路自己走一遍（用于②同源判据）。

    刻意不调 `run_plane()`：那会出图落盘（本判据要证明 overlay 与它的**数值**一致，
    不是再出一遍图）。产物链路本身（`run_plane` → `plot_plane`）由 `-k grid_axis` /
    `-k figures_repro` 那两组覆盖。
    """
    req = workflow.PlaneRequest(missiles=KEYS, with_iso=True, **kw)
    pts = pool.points(req.missiles)
    std = pool.standard_entry(req.standard)
    axis = figures.adaptive_axis(pts)
    g = grid_mod.make_grid(axis.xlim, axis.ylim, dv_step=req.dv_step, bc_step=req.bc_step)
    eng = Engine(req.scene, missile=std.native, tier=req.tier, jobs=req.jobs,
                 cache=req.cache, metrics=pool.metrics_of(std))
    try:
        shots = eng.many(g.cells)
    finally:
        eng.close()
    t_grid = grid_mod.t_hit_matrix(shots, g)
    return axis, grid_mod.extract_isolines(t_grid, g, step=req.iso_step)


def _matplotlib_lines_bg(**kw) -> tuple:
    """图2 的同源对照（同一套 `bg.scaling_for` 折算）。"""
    from missile_sim import bg as bg_mod

    req = workflow.BgRequest(missiles=KEYS, with_scan=True, **kw)
    std = pool.standard_entry(req.standard)
    std_point, std_metrics = bg_mod.point_of(std), pool.metrics_of(std)
    rows = bg_mod.rows(req.missiles, alt_m=req.alt_m, speed_ms=req.speed_ms, n=req.n_ref)
    dv_pin = float(req.dv_pin if req.dv_pin else std_metrics.dv)
    axis = figures.bg_axis(rows, xlim=req.xlim, ylim=req.ylim)
    g = grid_mod.make_grid(axis.xlim, axis.ylim,
                           dv_step=req.beta_step, bc_step=req.ginv_step)
    eng = Engine(req.scene, missile=std.native, tier=req.tier, jobs=req.jobs,
                 cache=req.cache, metrics=std_metrics,
                 scaling_of=lambda b, gi: bg_mod.scaling_for(
                     std_point, std_metrics, beta=b, ginv=gi, dv=dv_pin))
    try:
        shots = eng.many(g.cells)
    finally:
        eng.close()
    t_grid = grid_mod.t_hit_matrix(shots, g)
    return axis, grid_mod.extract_isolines(t_grid, g, step=req.iso_step)


# --------------------------------------------------------------------- ① 形状


def test_overlay_plane_json_shape():
    got = workflow.overlay_plane(missiles=KEYS, tier="standard", **PLANE_KW)
    assert list(got) == list(workflow.OVERLAY_KEYS), list(got)
    assert got["kind"] == "plane"
    assert got["keys"] == list(KEYS), got["keys"]
    assert len(got["axis"]["xlim"]) == 2 and len(got["axis"]["ylim"]) == 2
    assert got["iso_lines"], "这一组参数应当至少有一层等时线"
    for line in got["iso_lines"]:
        assert isinstance(line["level"], float)
        assert line["points"], (line["level"], "空等时线")
        for p in line["points"]:
            assert isinstance(p, list) and len(p) == 2, p
            assert all(isinstance(v, float) for v in p), p
        assert not _inside(line["points"], got["axis"]), \
            (line["level"], _inside(line["points"], got["axis"])[:3])
    assert got["notes"] and all(isinstance(n, str) for n in got["notes"])
    json.dumps(got, ensure_ascii=False)               # 必须是纯 JSON（可转手给后端）
    assert set(got["identity"]) == {"solver_sha256", "resource_sha256", "tier", "backend",
                                    "cached", "elapsed_ms"}
    assert got["identity"]["solver_sha256"] == workflow.solver.SOLVER_SHA256
    assert got["identity"]["resource_sha256"], "基准弹 blk 的哈希不该为空"
    assert got["identity"]["tier"] == "standard"
    assert isinstance(got["identity"]["cached"], bool)
    assert got["identity"]["elapsed_ms"] >= 0


def test_overlay_bg_json_shape():
    got = workflow.overlay_bg(missiles=KEYS, tier="standard", **BG_KW)
    assert list(got) == list(workflow.OVERLAY_KEYS), list(got)
    assert got["kind"] == "bg"
    assert got["keys"] == list(KEYS), got["keys"]
    assert got["iso_lines"], "这一组参数应当至少有一层等时线"
    for line in got["iso_lines"]:
        assert not _inside(line["points"], got["axis"]), \
            (line["level"], _inside(line["points"], got["axis"])[:3])
    json.dumps(got, ensure_ascii=False)
    assert got["identity"]["backend"] in ("python-standard", "compiled-c", "python-legacy")


# --------------------------------------------------------------------- ② 同源


def test_overlay_plane_isolines_match_the_matplotlib_path():
    """逐级逐点**同值**（不是"差不多"）：同一 `t_grid` + 同一 `extract_isolines`。"""
    axis, lines = _matplotlib_lines_plane(tier="standard", **PLANE_KW)
    got = workflow.overlay_plane(missiles=KEYS, tier="standard", **PLANE_KW)

    # ① 与**产物路径** `run_plane()` 同值：它的图写进临时目录，`figures/` 一个字节都不动
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = workflow.run_plane(workflow.PlaneRequest(
            missiles=KEYS, tier="standard", tag="overlaycheck", formats=("png",),
            figure_dir=Path(tmp), result_dir=Path(tmp), **PLANE_KW), log=None)
    assert [l["level"] for l in out["isolines"]] == [l["level"] for l in got["iso_lines"]]
    for ref, mine in zip(out["isolines"], got["iso_lines"]):
        assert [[float(x), float(y)] for x, y in ref["points"]] == mine["points"], mine["level"]

    # ② 与判据里自己走的同一条算路同值
    assert [l["level"] for l in got["iso_lines"]] == [float(l["level"]) for l in lines]
    for mine, ref in zip(got["iso_lines"], lines):
        assert mine["points"] == [[float(x), float(y)] for x, y in ref["points"]], mine["level"]
    # ③ 轴逐值相等（`overlay` 只是把 `adaptive_axis` 的结果搬出来）
    assert got["axis"]["xlim"] == [float(axis.xlim[0]), float(axis.xlim[1])]
    assert got["axis"]["ylim"] == [float(axis.ylim[0]), float(axis.ylim[1])]


def test_overlay_bg_isolines_match_the_matplotlib_path():
    axis, lines = _matplotlib_lines_bg(tier="standard", **BG_KW)
    got = workflow.overlay_bg(missiles=KEYS, tier="standard", **BG_KW)
    assert [l["level"] for l in got["iso_lines"]] == [float(l["level"]) for l in lines]
    for mine, ref in zip(got["iso_lines"], lines):
        assert mine["points"] == [[float(x), float(y)] for x, y in ref["points"]], mine["level"]
    assert got["axis"]["xlim"] == [float(axis.xlim[0]), float(axis.xlim[1])]
    assert got["axis"]["ylim"] == [float(axis.ylim[0]), float(axis.ylim[1])]


def test_overlay_axis_matches_the_axes_oracle():
    """轴口径：必须与 `--axes` oracle（`catalog.axis_payload`）里的那两个范围同值。"""
    from missile_sim import catalog

    got = workflow.overlay_plane(missiles=KEYS, tier="standard", **PLANE_KW)
    ref = catalog.axis_payload("plane", ",".join(KEYS))
    assert got["axis"]["xlim"] == [float(v) for v in ref["xlim"]]
    assert got["axis"]["ylim"] == [float(v) for v in ref["ylim"]]


# --------------------------------------------------------------------- ③ 只产数据


def test_overlay_writes_no_figures_and_leaves_no_open_figure():
    """"只产 JSON"的硬证据：`figures/` 一个文件都不变、跑完没有新开的 figure。"""
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
              for p in FIG_DIR.glob("*") if p.is_file()}
    figs_before = len(plt.get_fignums())
    workflow.overlay_plane(missiles=KEYS, tier="standard", **PLANE_KW)
    workflow.overlay_bg(missiles=KEYS, tier="standard", **BG_KW)
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
             for p in FIG_DIR.glob("*") if p.is_file()}
    assert after == before, "overlay_* 动了 figures/（它不该落图）"
    assert len(plt.get_fignums()) == figs_before, "overlay_* 留下了打开的 figure"


# --------------------------------------------------------------------- ④ 反证


def _axis_checker(got: dict, *, oracle: tuple) -> None:
    """"轴必须来自 oracle"这条判据的**可复用形态**（④ 用它证明这条有牙）。

    `oracle` 用 tuple，产物里是 JSON 形状的 list ⇒ 比之前统一成 tuple。
    """
    mine = (tuple(got["axis"]["xlim"]), tuple(got["axis"]["ylim"]))
    assert mine == oracle, (mine, oracle)


def test_hardcoded_axis_must_turn_the_axis_criterion_red():
    """反证：把 `figures.adaptive_axis` 换成硬编码范围 ⇒ 轴口径判据**必须**红。

    红 = `_axis_checker` 抛 AssertionError（说明"轴 == oracle"这条判据真在看值，不是橡皮图章）。
    同时确认换成硬编码范围后**产物形状仍然合法**（坐标还在它自己的轴内）——
    否则这条反证只是在测别的东西崩了。

    ⚠ 硬编码范围要挑得**离真 oracle 近**（差几十个单位）：差太远会让网格步数炸开、
    这条反证就从"判据有没有牙"变成"跑得跑不完"。
    """
    from unittest import mock

    ref = workflow.overlay_plane(missiles=KEYS, tier="standard", **PLANE_KW)
    oracle = (tuple(ref["axis"]["xlim"]), tuple(ref["axis"]["ylim"]))
    _axis_checker(ref, oracle=oracle)                       # 正常路径：绿

    hard = AxisSpec(xlim=(910.0, 960.0), ylim=(2600.0, 3150.0),
                    x_major=10.0, x_minor=5.0, y_major=100.0, y_minor=50.0)
    assert (hard.xlim, hard.ylim) != oracle, "硬编码范围与真 oracle 撞了，重挑范围"
    with mock.patch.object(figures, "adaptive_axis", lambda pts: hard):
        got = workflow.overlay_plane(missiles=KEYS, tier="standard", **PLANE_KW)
    assert got["axis"] == {"xlim": [910.0, 960.0], "ylim": [2600.0, 3150.0]}
    assert not _inside([p for l in got["iso_lines"] for p in l["points"]], got["axis"])
    with pytest.raises(AssertionError):                     # 硬编码路径：必须红
        _axis_checker(got, oracle=oracle)

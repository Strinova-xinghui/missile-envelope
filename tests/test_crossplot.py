# -*- coding: utf-8 -*-
"""绘图段自检：`aam_fit` 版式规格对齐、层可独立调用、出图字节可复现。

视觉规格的权威来源是 `E:\\WT\\War-Thunder-Datamine\\自动化分析\\aam_plot.py`（产出 aam_fit.png）
与 `skills/wt-aam-analysis/references/charts.md`；本文件把关键量**写死核对**，
以免将来有人"顺手调一下"却让图与参考图漂移。
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pytest

from missile_sim import crossplot as cp
from missile_sim.plot import CROSSPLOT_SPEC, MISSILE_LBL_OFFSETS

ROOT = Path(__file__).resolve().parents[1]

# ---- 与 aam_plot.py 逐项对齐的"冻结"值（改这些等于改图与参考图的一致性）
EXPECT_FIG_SIZE = (12.0, 6.8)
EXPECT_FIG_DPI = 110
EXPECT_XLIM = (800.0, 1110.0)
EXPECT_YLIM = (2450.0, 3850.0)
EXPECT_MAJOR = (30.0, 100.0)
EXPECT_MINOR = (10.0, 50.0)
EXPECT_POINT_COLOR = "#D32F2F"
EXPECT_AX_RECT = (0.075, 0.175, 0.822, 0.700)


def _iso():
    dv = np.arange(800.0, 1110.0 + 1e-9, 10.0)
    bc = np.arange(2450.0, 3850.0 + 1e-9, 25.0)
    d2, b2 = np.meshgrid(dv, bc, indexing="ij")
    t = 60.0 - 0.1 * (d2 - 800.0) - 0.005 * (b2 - 2450.0)
    return cp.IsoGrid(dv=dv, bc=bc, t_grid=t)


def _points(n=11):
    data = [("120A", 820.5, 3609.0), ("120C", 897.4, 3624.0), ("120D", 891.3, 3653.8),
            ("MICA", 947.0, 2636.0), ("AAM-4", 826.3, 3683.9), ("PL-12", 932.6, 3078.1),
            ("PL-12A", 989.1, 3245.9), ("R-77", 965.7, 2568.8), ("R-77-1", 1099.5, 2705.6),
            ("Derby", 932.8, 2567.0), ("R-Darter", 913.9, 2631.2)]
    return [cp.MissilePoint(label=lab, dv=d, bc=b) for lab, d, b in data[:n]]


# --------------------------------------------------------------------- 规格

def test_frozen_layout_matches_aam_plot():
    assert cp.FIG_SIZE == EXPECT_FIG_SIZE
    assert cp.FIG_DPI == EXPECT_FIG_DPI
    assert cp.AX_RECT == EXPECT_AX_RECT
    assert cp.DEFAULT_XLIM == EXPECT_XLIM
    assert cp.DEFAULT_YLIM == EXPECT_YLIM
    assert cp.POINT_COLOR == EXPECT_POINT_COLOR


def test_axis_spec_shared_with_crossplot_spec():
    """`plot.CROSSPLOT_SPEC` 是共用规格，绘图段必须就用它（两处写死会漂移）。"""
    assert tuple(CROSSPLOT_SPEC["xlim"]) == EXPECT_XLIM
    assert tuple(CROSSPLOT_SPEC["ylim"]) == EXPECT_YLIM
    assert (CROSSPLOT_SPEC["x_major"], CROSSPLOT_SPEC["y_major"]) == EXPECT_MAJOR
    assert (CROSSPLOT_SPEC["x_minor"], CROSSPLOT_SPEC["y_minor"]) == EXPECT_MINOR


def test_make_figure_applies_locators_and_limits():
    fig, ax, cax = cp.make_figure()
    try:
        assert ax.get_xlim() == pytest.approx(EXPECT_XLIM)
        assert ax.get_ylim() == pytest.approx(EXPECT_YLIM)
        # 刻度间隔用相邻 tick 的差验证（MultipleLocator 会向外扩，别断言首值）
        def steps(loc, lo, hi, n=5):
            return np.diff(np.asarray(loc.tick_values(lo, hi), dtype=float))[:n - 1]

        for loc, lo, hi, want in ((ax.xaxis.get_major_locator(), 800, 1110, EXPECT_MAJOR[0]),
                                  (ax.xaxis.get_minor_locator(), 790, 850, EXPECT_MINOR[0]),
                                  (ax.yaxis.get_major_locator(), 2450, 2900, EXPECT_MAJOR[1]),
                                  (ax.yaxis.get_minor_locator(), 2450, 2700, EXPECT_MINOR[1])):
            got = steps(loc, lo, hi)
            assert got.size > 0, f"locator 在该区间没有刻度：{want}"
            bad = [float(g) for g in got if abs(float(g) - want) > 1e-9]
            assert not bad, f"刻度间隔应为 {want}，实际 {list(got)}"
        assert cax is not None
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


def test_make_figure_without_colorbar_has_no_cax():
    fig, ax, cax = cp.make_figure(colorbar=False)
    try:
        assert cax is None
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


# --------------------------------------------------------------------- 轴范围之外的弹点

def test_all_11_missiles_fall_inside_axis_window():
    """11 型弹点必须都落在轴范围内（否则会被裁掉，图就少点）。"""
    out = [p.label for p in _points()
           if not (EXPECT_XLIM[0] <= p.dv <= EXPECT_XLIM[1]
                   and EXPECT_YLIM[0] <= p.bc <= EXPECT_YLIM[1])]
    assert out == [], f"落在框外的型号：{out}"


def test_label_offsets_cover_all_11():
    for p in _points():
        assert p.label in MISSILE_LBL_OFFSETS, f"{p.label} 没有固定偏移"


# --------------------------------------------------------------------- 层独立调用

def test_plot_points_layer_alone():
    import matplotlib.pyplot as plt
    fig, ax, _ = cp.make_figure(colorbar=False)
    try:
        sc, texts = cp.plot_points(ax, _points())
        assert sc is not None
        assert len(texts) == 11
        assert {t.get_text() for t in texts} == {p.label for p in _points()}
    finally:
        plt.close(fig)


def test_plot_points_empty_is_noop():
    import matplotlib.pyplot as plt
    fig, ax, _ = cp.make_figure(colorbar=False)
    try:
        sc, texts = cp.plot_points(ax, [])
        assert sc is None and texts == []
    finally:
        plt.close(fig)


def test_plot_points_highlight_draws_extra_ring():
    import matplotlib.pyplot as plt
    fig, ax, _ = cp.make_figure(colorbar=False)
    try:
        pts = _points(2)
        pts[0].highlighted = True
        n0 = len(ax.collections)
        cp.plot_points(ax, pts)
        assert len(ax.collections) == n0 + 2      # 散点 + 环
    finally:
        plt.close(fig)


def test_plot_isotime_layer_alone():
    import matplotlib.pyplot as plt
    fig, ax, cax = cp.make_figure()
    try:
        cs, levels, labels = cp.plot_isotime(ax, _iso(), step=2.0, cax=cax)
        assert cs is not None and len(levels) > 0
        assert all(abs(lv % 2.0) < 1e-9 for lv in levels)
        # 线数 ≤24 时每条都该标名；只有"仅擦到网格角点、形不成线段"的层允许缺（如最高层）
        assert len(labels) >= len(levels) - 1, f"{len(labels)} 个线名 / {len(levels)} 层"
        assert {float(l.get_text().split()[0]) for l in labels} <= set(levels)
    finally:
        plt.close(fig)


def test_iso_label_count_matches_levels_when_all_layers_have_segments():
    """数据范围**严格**含在网格内时，每一层都有线段 ⇒ 线名数必须等于层数（不丢名）。"""
    import matplotlib.pyplot as plt
    dv = np.arange(800.0, 1110.0 + 1e-9, 10.0)
    bc = np.arange(2450.0, 3850.0 + 1e-9, 25.0)
    d2, b2 = np.meshgrid(dv, bc, indexing="ij")
    t = 55.0 - 0.05 * (d2 - 800.0) - 0.003 * (b2 - 2450.0)      # 27~55 s，不与网格边界重合
    iso = cp.IsoGrid(dv=dv, bc=bc, t_grid=t)
    fig, ax, cax = cp.make_figure()
    try:
        cs, levels, labels = cp.plot_isotime(ax, iso, step=2.0, cax=cax)
        assert len(labels) == len(levels), f"{len(labels)} 个线名 / {len(levels)} 层"
    finally:
        plt.close(fig)


def test_plot_isotime_without_colorbar_uses_single_color():
    import matplotlib.pyplot as plt
    fig, ax, cax = cp.make_figure(colorbar=False)
    try:
        cs, levels, _ = cp.plot_isotime(ax, _iso(), step=5.0, cax=None, colorbar=False)
        assert cs is not None and levels
    finally:
        plt.close(fig)


def test_plot_isotime_empty_grid_is_noop():
    import matplotlib.pyplot as plt
    fig, ax, cax = cp.make_figure()
    try:
        empty = cp.IsoGrid(dv=np.array([900.0]), bc=np.array([3000.0]),
                           t_grid=np.full((1, 1), np.nan))
        cs, levels, labels = cp.plot_isotime(ax, empty, step=1.0, cax=cax)
        assert cs is None and levels == [] and labels == []
    finally:
        plt.close(fig)


# --------------------------------------------------------------------- 等时线层级

def test_iso_levels_are_multiples_of_step_inside_range():
    tg = np.linspace(31.9, 60.6, 60).reshape(10, 6)
    lv = cp.iso_levels(tg, 2.0)
    assert lv[0] == pytest.approx(32.0)
    assert lv[-1] == pytest.approx(60.0)
    assert all(abs(x % 2.0) < 1e-9 for x in lv)


def test_iso_levels_handles_all_nan():
    assert cp.iso_levels(np.full((3, 3), np.nan), 1.0) == []


def test_iso_levels_single_value():
    assert cp.iso_levels(np.full((3, 3), 45.0), 1.0) == [45.0]


# --------------------------------------------------------------------- 出处与脚注

def test_provenance_lines_for_pro_backend():
    prov = {"backend": "pro", "standard": {"name": "PL-12", "profile_hash": "11c528f6f2d828d1"},
            "pro": {"dt": 0.01, "observation_mode": "ideal", "elf_sha256": "94de5454" + "0" * 56}}
    line = cp.provenance_lines(prov)[0]
    assert "pro" in line and "PL-12" in line and "0.01" in line and "94de5454" in line


def test_provenance_lines_for_flash_backend():
    prov = {"backend": "flash", "standard": {"name": "PL-12"}, "dt": 0.005}
    line = cp.provenance_lines(prov)[0]
    assert "flash" in line and "0.005" in line


def test_provenance_lines_tolerate_empty_standard():
    line = cp.provenance_lines({"backend": "pro", "pro": {}})[0]
    assert "无标准弹" in line


def test_provenance_lines_for_standard_tier_uses_engine_step():
    """新两档报的必须是**引擎外层步长**（`pro.dt`），不是旧 Flash 的 `sim.dt`。

    回归：这条曾按 `prov["dt"]`（= `cfg.sim.dt`）写，而 standard/fast 根本不用 `sim.dt`
    —— 图上会印一个假步长。诊断量（观测模式）也必须带上，否则"谁算的"答不全。
    """
    prov = {"backend": "standard",
            "standard": {"name": "PL-12", "profile_hash": "11c528f6f2d828d1"},
            "aero_model": "full", "dt": 0.01,              # sim.dt：两档不用它
            "pro": {"dt": 0.02083333395421505, "observation_mode": "ideal"}}
    line = cp.provenance_lines(prov)[0]
    assert "standard" in line and "PL-12" in line
    assert "0.020833" in line, line
    assert "0.01 s" not in line, f"报成了旧 Flash 的 sim.dt：{line}"
    assert "观测 ideal" in line


def test_provenance_lines_accepts_new_tier_scan_manifest():
    """扫描 manifest 没有 `backend` 字段：档位名要从 `calculator.model` 取。

    旧 manifest 只有 `calc_version`（pro 另带 `elf_sha256`），所以还得留一条退化路径。
    """
    line = cp.provenance_lines({
        "standard": {"name": "PL-12"},
        "calculator": {"calc_version": 1, "model": "fast",
                       "dt": 0.02083333395421505, "observation_mode": "ideal"},
    })[0]
    assert "后端 fast" in line and "0.020833" in line, line

    legacy = cp.provenance_lines({
        "standard": {"name": "PL-12"},
        "calculator": {"calc_version": 5, "elf_sha256": "94de5454" + "0" * 56, "dt": 0.01},
    })[0]
    assert "后端 pro" in legacy and "原生步长 0.01" in legacy, legacy


def test_wrap_lines_splits_long_text():
    out = cp.wrap_lines("等时线" * 80, width=60)
    assert len(out) > 1
    assert all(o for o in out)


def test_wrap_lines_keeps_short_text():
    assert cp.wrap_lines("短", width=60) == ["短"]


# --------------------------------------------------------------------- 出图与可复现

def _render(tmp: Path, name: str, **over):
    kw = dict(points=_points(), iso=_iso(), out_base=tmp / name,
              title="主动弹 总增速–弹道系数 与 等命中时间线",
              subtitle="50 km 迎头 · 高度 10.0 km",
              prov={"backend": "pro", "standard": {"name": "PL-12", "profile_hash": "abc"},
                    "pro": {"dt": 0.01, "observation_mode": "ideal"}},
              iso_step=2.0, footnotes=["脚注一", "脚注二"])
    kw.update(over)
    return cp.plot_crossplot(**kw)


def test_plot_crossplot_writes_all_formats():
    import tempfile
    d = Path(tempfile.mkdtemp())
    paths = _render(d, "fig")
    assert [p.suffix for p in paths] == [".png", ".pdf", ".svg"]
    assert all(p.exists() and p.stat().st_size > 1000 for p in paths)


def test_plot_crossplot_is_byte_reproducible():
    """同一份数据重跑三个格式必须逐字节一致（否则 git 里每次都是假 diff）。"""
    import tempfile
    d = Path(tempfile.mkdtemp())
    a = _render(d / "a", "fig")
    b = _render(d / "b", "fig")
    for pa, pb in zip(a, b):
        ha = hashlib.sha256(pa.read_bytes()).hexdigest()
        hb = hashlib.sha256(pb.read_bytes()).hexdigest()
        assert ha == hb, f"{pa.suffix} 不可复现"


def test_plot_crossplot_with_fit_is_optional():
    import tempfile
    import matplotlib.pyplot as plt
    d = Path(tempfile.mkdtemp())
    p1 = _render(d, "nofit")[0]
    p2 = _render(d, "fit", with_fit=True, fit_text="y = -3.94x + 6752.4")[0]
    assert p1.exists() and p2.exists()
    assert p1.read_bytes() != p2.read_bytes(), "带拟合线的图应当与不带的不同"


def test_plot_crossplot_without_colorbar():
    import tempfile
    d = Path(tempfile.mkdtemp())
    paths = _render(d, "nocolor", colorbar=False)
    assert paths and paths[0].exists()

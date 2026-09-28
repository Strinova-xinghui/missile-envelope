# -*- coding: utf-8 -*-
"""图2（β–γ 能力平面）的出图契约：字节可复现、自适应轴、图注齐备。

与 `test_figures_repro.py` 平行的另一套 —— 图1 与图2 的版式元素不同（图2 有等 `n*` 线族、
象限底色、气泡大小），所以各自钉自己的契约。
"""

import hashlib
from pathlib import Path

import pytest

from missile_sim import bg, figures, pool, spec

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp_test" / "figures_bg"


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def rows():
    return bg.rows()


def test_bg_axis_is_adaptive_and_contains_all_points(rows):
    """轴范围必须把全部点包住并留出边距（气泡与象限角标要地方）。"""
    ax = figures.bg_axis(rows)
    x0, x1 = ax.xlim
    y0, y1 = ax.ylim
    assert x0 < min(r.beta for r in rows) < x1
    assert y0 < min(r.gamma for r in rows) < y1
    assert x0 < max(r.beta for r in rows) < x1
    assert y0 < max(r.gamma for r in rows) < y1
    # 上边距要够：最上面的点（R-77, γ≈91.2）不能贴着框
    assert y1 - max(r.gamma for r in rows) > 3.0
    assert ax.x_major > 0 and ax.x_minor > 0 and ax.y_major > 0 and ax.y_minor > 0
    assert ax.x_minor < ax.x_major and ax.y_minor < ax.y_major


def test_bg_axis_rejects_empty():
    with pytest.raises(ValueError):
        figures.bg_axis([])


def test_bg_axis_handles_a_single_missile():
    """只画一型时范围塌成一点 —— 必须靠最小值兜住，不能出现零宽度轴。"""
    ax = figures.bg_axis(bg.rows(["PL-12"]))
    assert ax.xlim[1] > ax.xlim[0] and ax.ylim[1] > ax.ylim[0]


def test_bg_subtitle_states_the_reference_condition():
    """`n*` 依赖动压，副标题**必须**写明参考工况，否则两张图不可比。"""
    _a, _s, mach, q_pa, f_mach, cap_f = bg.reference()
    text = figures.bg_subtitle(alt_m=10_000.0, speed_ms=800.0, mach=mach,
                               q_pa=q_pa, f_mach=f_mach, cap_f=cap_f, n=20.0)
    for token in ("10 km", "800 m/s", "Ma 2.66", "132.4 kPa", "0.3762", "1.1663", "20G"):
        assert token in text, f"副标题少了 {token!r}：{text}"


def test_label_offsets_cover_the_whole_pool():
    """标签偏移必须覆盖池里每一型 —— 漏了会静默用默认偏移，可能压在别的点上。"""
    missing = [k for k in pool.names() if k not in figures.BG_LBL_OFFSETS]
    assert not missing, f"这些型号没有标签偏移：{missing}"


def test_nstar_levels_are_ordered_and_inside_the_reference_figure_range():
    lv = figures.BG_NSTAR_LEVELS
    assert list(lv) == sorted(lv) and len(set(lv)) == len(lv)
    assert 14.0 in lv and 20.0 in lv


def test_quadrant_thresholds_match_the_reference_figure():
    """象限阈值照参考图取：β≥3250 且 γ≤70 为双优；β≤3000 且 γ≥85 为双差。"""
    assert (figures.BG_GOOD_BETA, figures.BG_GOOD_GAMMA) == (3250.0, 70.0)
    assert (figures.BG_BAD_BETA, figures.BG_BAD_GAMMA) == (3000.0, 85.0)
    # 池里必须真的有人落在双优区，否则底色是空的、图会误导
    rows = bg.rows()
    assert any(r.beta >= figures.BG_GOOD_BETA and r.gamma <= figures.BG_GOOD_GAMMA
               for r in rows), "没有弹落在双优区"


def test_footnotes_avoid_mathtext_delimiters():
    """`wrap_lines()` 会把一对 `$` 拆到两行，mathtext 见到落单的 `$` 就原样输出。"""
    for line in figures.BG_FOOTNOTES:
        assert line.count("$") == 0, f"图2 脚注不能写 $…$：{line[:40]}"
    # 图例那几条短，不会被折行，允许用数学
    assert "$n^*$" in figures.LEGEND_BG_NSTAR


def test_plot_bg_plane_needs_data():
    with pytest.raises(ValueError):
        figures.plot_bg_plane(rows=[], out_base=TMP / "empty")


def test_plot_bg_plane_is_byte_reproducible_in_three_formats(rows, tmp_path):
    """两遍出图，png / pdf / svg 都必须逐字节一致（时间戳与 SVG id 已归一）。"""
    a = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "a", highlight="PL-12")
    b = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "b", highlight="PL-12")
    assert len(a) == 3 and len(b) == 3
    for x, y in zip(sorted(a), sorted(b)):
        assert Path(x).suffix == Path(y).suffix
        assert _sha(x) == _sha(y), f"{Path(x).suffix} 不可复现"
        assert Path(x).stat().st_size > 5_000


def test_plot_bg_plane_defaults_build_a_real_figure(rows, tmp_path):
    """默认参数（无 title/subtitle/axis）必须能自己撑起来 —— 编排层只传数据。"""
    out = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "d", formats=("png",))
    assert len(out) == 1 and Path(out[0]).suffix == ".png"
    assert Path(out[0]).stat().st_size > 50_000


def test_plot_bg_plane_accepts_an_explicit_axis(rows, tmp_path):
    ax = spec.AxisSpec(xlim=(2400.0, 3900.0), ylim=(40.0, 110.0),
                       x_major=500.0, x_minor=100.0, y_major=20.0, y_minor=4.0)
    out = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "x", axis=ax,
                                formats=("png",))
    assert len(out) == 1

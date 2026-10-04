# -*- coding: utf-8 -*-
"""图2（β–γ 能力平面）的出图契约：字节可复现、自适应轴、图注齐备。

与 `test_figures_repro.py` 平行的另一套 —— 图1 与图2 的版式元素不同（图2 有等 `n*` 线族、
象限底色、散点配色），所以各自钉自己的契约。
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
    """轴范围必须把全部点包住并留出边距（散点与象限角标要地方）。"""
    ax = figures.bg_axis(rows)
    x0, x1 = ax.xlim
    y0, y1 = ax.ylim
    assert x0 < min(r.beta for r in rows) < x1
    assert y0 < min(r.ginv for r in rows) < y1
    assert x0 < max(r.beta for r in rows) < x1
    assert y0 < max(r.ginv for r in rows) < y1
    # 上边距要够：最上面的点（120A, ginv≈0.01869）不能贴着框
    span = max(r.ginv for r in rows) - min(r.ginv for r in rows)
    assert y1 - max(r.ginv for r in rows) > 0.05 * span
    assert ax.x_major > 0 and ax.x_minor > 0 and ax.y_major > 0 and ax.y_minor > 0
    assert ax.x_minor < ax.x_major and ax.y_minor < ax.y_major


def test_bg_axis_rejects_empty():
    with pytest.raises(ValueError):
        figures.bg_axis([])


def test_bg_axis_handles_a_single_missile():
    """只画一型时范围塌成一点 —— 必须靠最小值兜住，不能出现零宽度轴。"""
    ax = figures.bg_axis(bg.rows(["PL-12"]))
    assert ax.xlim[1] > ax.xlim[0] and ax.ylim[1] > ax.ylim[0]


def test_bg_axis_ticks_follow_the_overridden_range(rows):
    """覆盖范围后，**刻度必须按最终范围现算**（不是沿用弹池跨度算出来的那个）。

    回归判据（2026-10-04 真事故）：`ginv` 的刻度是按弹池跨度（0.0095）算的
    `y_major = 0.0025`，一旦范围被覆盖成 `3000~3300`，matplotlib 生成
    `300/0.0025 = 12 万`个主刻度位、次刻度 60 万个 ⇒ `MemoryError: 536 GiB`。
    """
    ax = figures.bg_axis(rows, ylim=(3000.0, 3300.0))
    assert ax.ylim == (3000.0, 3300.0)
    n_major = (ax.ylim[1] - ax.ylim[0]) / ax.y_major
    assert 2.0 <= n_major <= 20.0, f"刻度位 {n_major:.0f} 个（步长 {ax.y_major:g}），量级不对"
    ax2 = figures.bg_axis(rows, xlim=(2000.0, 4000.0), ylim=(0.008, 0.022))
    assert ax2.xlim == (2000.0, 4000.0) and ax2.ylim == (0.008, 0.022)
    assert (ax2.ylim[1] - ax2.ylim[0]) / ax2.y_minor <= 100.0
    with pytest.raises(ValueError):
        figures.bg_axis(rows, ylim=(3300.0, 3000.0))       # 反了就当场炸，不画空图


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


def test_no_quadrant_shading_anymore(tmp_path):
    """用户否掉了四象限底色（红区绿区）：阈值常量、填充函数、图例色标全删。

    只留等 `n*` 线 + 散点 —— 那两个阈值是"对着 11 弹池目测定的"，换个池子就失去意义，
    留在图上反而会被当成有物理含义的分界。

    断言直接落在**产物**上：底色若钻回来，SVG 里必然出现那两个填充色；
    "双优/双差"两个图例词也必然出现在文字里。
    """
    for name in ("BG_GOOD_BETA", "BG_GOOD_GAMMA", "BG_BAD_BETA", "BG_BAD_GAMMA",
                 "BG_GOOD_FILL", "BG_GOOD_EDGE", "BG_BAD_FILL", "BG_BAD_EDGE",
                 "BG_GOOD_TEXT", "BG_BAD_TEXT"):
        assert not hasattr(figures, name), f"象限底色应该已经删掉，还剩 {name}"
    assert not hasattr(figures, "_bg_quadrants"), "填充函数应该已经删掉"

    out = figures.plot_bg_plane(rows=bg.rows(), out_base=tmp_path / "noquad",
                                formats=("png", "pdf", "svg"))
    assert len(out) == 3, out
    svg = next(p for p in out if p.suffix == ".svg").read_text(encoding="utf-8")
    for color in ("#E8F5E9", "#FDECEA", "#2E7D32", "#C62828",
                  "e8f5e9", "fdecea"):
        assert color not in svg, f"底色又回来了：出现 {color}"
    for word in ("双优", "双差"):
        assert word not in svg, f"象限图例又回来了：出现 {word!r}"
    # 该留的还在
    assert "n^*" in svg or "n*" in svg
    assert "弹池 11 型" in svg, "图例应当报弹池规模"
    assert "气泡大小" not in svg, "气泡大小编码已按用户口径取消（点径与图1 统一）"


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


def test_bg_points_are_uniform_and_the_baseline_is_green(rows):
    """图2 的点径 = 图1 的 `POINT_SIZE`（不再按 ΔV 缩放）；基准弹的**点与标签**都绿；**无空心环**。

    2026-10-01 用户口径：① 旧 `BG_BUBBLE` 让最大的"红气泡"直径到 24.5 pt，而标签只有 9.5 pt，
    与图1（统一点径 9.44 pt）不一致 ⇒ 点大小统一；② 选中态只用**颜色**表达（点与标签同色）
    ⇒ 空心环去掉。

    判据落在 **artist** 上（不看像素）：只有一个散点集合、尺寸集合只有 `POINT_SIZE`、
    点与标签的颜色都恰好一处绿。
    """
    from matplotlib.colors import to_rgba
    import matplotlib.pyplot as plt

    i_base = [r.key for r in rows].index("PL-12")
    red = to_rgba(figures.POINT_COLOR)[:3]
    red_lbl = to_rgba(figures.LBL_COLOR)[:3]
    green = to_rgba(figures.BASE_COLOR)[:3]

    fig = plt.figure()
    ax = fig.add_subplot(111)
    try:
        figures._bg_bubbles(ax, rows, highlight="PL-12")
        assert len(ax.collections) == 1, f"空心环应该已经删掉，还剩 {ax.collections}"
        sc = ax.collections[0]
        assert set(sc.get_sizes()) == {figures.POINT_SIZE}, set(sc.get_sizes())
        faces = [to_rgba(c)[:3] for c in sc.get_facecolors()]
        assert len(faces) == len(rows)
        assert faces[i_base] == green, f"基准弹的点必须涂绿，实际 {faces[i_base]}"
        assert all(c == red for i, c in enumerate(faces) if i != i_base), faces
        tcol = [to_rgba(t.get_color())[:3] for t in ax.texts]
        assert len(tcol) == len(rows), (len(tcol), len(rows))
        assert tcol[i_base] == green, f"基准弹的标签也要绿，实际 {tcol[i_base]}"
        assert all(c == red_lbl for i, c in enumerate(tcol) if i != i_base), tcol
    finally:
        plt.close(fig)
    assert "气泡" not in figures.LEGEND_BG_POINTS
    assert "气泡" not in figures.BG_FOOTNOTES[0]


def test_legend_text_of_the_baseline_is_green_too():
    """图例里"基准弹"那一条的**文字**也涂绿（用户 2026-10-01 追加"标签也绿"）。"""
    from matplotlib.colors import to_rgba
    import matplotlib.pyplot as plt

    green = to_rgba(figures.BASE_COLOR)[:3]
    fig = plt.figure()
    try:
        figures.add_bg_header(fig, title="t", highlight="PL-12", n_points=11)
        cols = {t.get_text(): to_rgba(t.get_color())[:3] for t in fig.legends[0].get_texts()}
        assert cols["PL-12"] == green, cols
        assert all(c != green for txt, c in cols.items() if txt != "PL-12"), cols
    finally:
        plt.close(fig)

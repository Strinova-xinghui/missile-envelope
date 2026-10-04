# -*- coding: utf-8 -*-
"""网格、等时线提取与自适应轴。

网格与 t_hit 矩阵用**鸭子类型的假 shot**（`SimpleNamespace`）喂进去，所以这一层不跑求解器；
只有自适应轴那一组要真实的 `MissilePoint`（从 blk 现算，约 1~2 s）。

`t_hit_matrix` 的行主序是**出图正确性的地基**：`contour(X, Y, Z)` 要 `Z.shape == (len(Y), len(X))`，
所以矩阵按 `(n_dv, n_bc)` 存、画时转置。搞反了等时线会整体镜像 —— 这类错误肉眼很难看出来。
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from missile_sim import figures, grid, pool
from missile_sim.spec import PlaneGrid

GRID11 = None


@pytest.fixture(scope="module")
def pool_points():
    return pool.points()


def _shot(t_hit=None, *, ok=True, hit=None):
    """最小假 shot：`t_hit_matrix` / `n_hit_matrix` 只读 ok / hit / t_hit 三个属性。

    `hit` 缺省按"`t_hit` 是不是有限值"推 —— 真求解器里 `hit=True` 必然伴随有限的 `t_hit`，
    假 shot 也得守这条，否则掩码测试会测出一个现实中不存在的组合。
    """
    if hit is None:
        hit = t_hit is not None
    return SimpleNamespace(ok=ok, hit=bool(hit),
                           t_hit=(math.nan if t_hit is None else float(t_hit)))


# --------------------------------------------------------------- arange


def test_arange_inclusive_covers_endpoints():
    assert grid.arange_inclusive(0.0, 10.0, 5.0) == (0.0, 5.0, 10.0)
    assert grid.arange_inclusive(0.0, 10.0, 3.0) == (0.0, 3.0, 6.0, 9.0, 10.0)
    assert grid.arange_inclusive(2.0, 2.0, 5.0) == (2.0,)


def test_arange_rejects_nonpositive_step():
    with pytest.raises(ValueError):
        grid.arange_inclusive(0.0, 1.0, 0.0)


# --------------------------------------------------------------- 网格


def test_make_grid_aligns_inward_to_step():
    g = grid.make_grid((803.731, 1116.277), (2500.003, 3750.9))
    assert g.dv[0] == pytest.approx(810.0), "下界要向上对齐到步长"
    assert g.bc[0] == pytest.approx(2525.0)
    for v in g.dv[:-1]:
        assert v % 10.0 == pytest.approx(0.0, abs=1e-9), "ΔV 必须落在步长格点上"
    for v in g.bc[:-1]:
        assert v % 25.0 == pytest.approx(0.0, abs=1e-9)
    # `arange_inclusive` 会补一个**贴到轴边界**的端点（照旧 `scanner.arange_inclusive` 的口径），
    # 所以最后一个值不是格点值，而是轴的 hi —— 这是刻意的，好让等时线铺满整幅轴。
    assert g.dv[-1] == pytest.approx(1116.277)
    assert g.bc[-1] == pytest.approx(3750.9)
    assert g.dv[-2] == pytest.approx(1110.0)
    assert g.bc[-2] == pytest.approx(3750.0)


def test_default_grid_is_32x51():
    """默认 11 弹的轴 → 32×51 = 1632 工况（这是文档里引用的那个数）。"""
    g = grid.make_grid((803.731, 1116.277), (2500.003, 3750.9))
    assert g.shape == (32, 51)
    assert g.n_cases == 1632


def test_cells_are_row_major_dv_first():
    g = PlaneGrid(dv=(10.0, 20.0), bc=(1.0, 2.0, 3.0), dv_step=10.0, bc_step=1.0)
    got = list(g.cells)
    assert got == [(10.0, 1.0), (10.0, 2.0), (10.0, 3.0),
                   (20.0, 1.0), (20.0, 2.0), (20.0, 3.0)], "ΔV 是主序"


# --------------------------------------------------------------- t_hit 矩阵


def test_t_hit_matrix_shape_and_row_major():
    g = PlaneGrid(dv=(10.0, 20.0), bc=(1.0, 2.0, 3.0), dv_step=10.0, bc_step=1.0)
    shots = [_shot(1.0), _shot(2.0), _shot(3.0), _shot(4.0), _shot(5.0), _shot(6.0)]
    m = grid.t_hit_matrix(shots, g)
    assert m.shape == (2, 3)
    assert m[0].tolist() == [1.0, 2.0, 3.0]
    assert m[1].tolist() == [4.0, 5.0, 6.0]


def test_misses_become_nan_not_zero():
    g = PlaneGrid(dv=(10.0,), bc=(1.0, 2.0), dv_step=10.0, bc_step=1.0)
    m = grid.t_hit_matrix([_shot(None), _shot(9.0)], g)
    assert math.isnan(m[0, 0])
    assert m[0, 1] == 9.0
    assert np.isnan(m).sum() == 1


def test_failed_and_short_shots_are_nan():
    g = PlaneGrid(dv=(10.0, 20.0), bc=(1.0,), dv_step=10.0, bc_step=1.0)
    m = grid.t_hit_matrix([_shot(None, ok=False), _shot(None, hit=False)], g)
    assert np.isnan(m).all(), "求解失败与非命中都必须留空"


def test_n_hit_matrix_is_binary_mask():
    g = PlaneGrid(dv=(10.0, 20.0), bc=(1.0, 2.0), dv_step=10.0, bc_step=1.0)
    m = grid.n_hit_matrix([_shot(1.0), _shot(None), _shot(2.0), _shot(3.0)], g)
    assert m.tolist() == [[1, 0], [1, 1]]


# --------------------------------------------------------------- 等时线


def test_iso_levels_are_integral_and_bounded():
    m = np.full((4, 4), math.nan)
    m[0, 0], m[3, 3] = 42.3, 46.8
    lv = grid.iso_levels(m, 1.0)
    assert lv == [43.0, 44.0, 45.0, 46.0]
    assert all(float(x).is_integer() for x in lv)


def test_iso_levels_empty_when_all_missed():
    assert grid.iso_levels(np.full((3, 3), math.nan), 1.0) == []


def test_iso_levels_respects_step():
    m = np.array([[40.0, 50.0]])
    assert grid.iso_levels(m, 5.0) == [40.0, 45.0, 50.0]


def test_extract_isolines_on_plane_returns_points():
    """一个线性平面场：等时线必须是直线段，且点数够画。"""
    dv = tuple(float(x) for x in range(800, 1000, 10))
    bc = tuple(float(y) for y in range(2500, 3000, 25))
    dvm, bcm = np.meshgrid(np.asarray(dv), np.asarray(bc), indexing="ij")
    t = 40.0 + (dvm - 800.0) / 100.0 + (bcm - 2500.0) / 500.0
    g = PlaneGrid(dv=dv, bc=bc, dv_step=10.0, bc_step=25.0)
    iso = grid.extract_isolines(t, g, step=1.0)
    assert iso, "线性场应该有等时线"
    lv = [i["level"] for i in iso]
    assert lv == sorted(lv)
    assert all(float(x).is_integer() for x in lv)
    for item in iso:
        assert len(item["points"]) >= 2, "一段线至少两个点"
        for x, y in item["points"]:
            assert 800.0 <= x <= 1000.0 and 2500.0 <= y <= 3000.0, "点必须落在网格范围内"


def test_extract_isolines_on_empty_returns_empty():
    g = PlaneGrid(dv=(10.0, 20.0), bc=(1.0, 2.0), dv_step=10.0, bc_step=1.0)
    assert grid.extract_isolines(np.full((2, 2), math.nan), g, step=1.0) == []


# --------------------------------------------------------------- 自适应轴


def test_axis_covers_all_points(pool_points):
    ax = figures.adaptive_axis(pool_points)
    for p in pool_points:
        assert ax.xlim[0] < p.dv < ax.xlim[1], f"{p.key} 的 ΔV 落在轴外"
        assert ax.ylim[0] < p.bc < ax.ylim[1], f"{p.key} 的 BC 落在轴外"


def test_axis_keeps_legacy_ticks_for_full_pool(pool_points):
    """11 弹时范围够大 ⇒ 刻度必须还是照旧的 30/10 与 100/50。"""
    ax = figures.adaptive_axis(pool_points)
    assert (ax.x_major, ax.x_minor) == (30.0, 10.0)
    assert (ax.y_major, ax.y_minor) == (100.0, 50.0)


def test_axis_shrinks_and_downsizes_ticks_for_single_missile(pool_points):
    """只选一型时轴要收紧，主刻度按 nice 序列下调 —— 否则一个点占满全图。"""
    one = [p for p in pool_points if p.key == "PL-12"]
    ax = figures.adaptive_axis(one)
    full = figures.adaptive_axis(pool_points)
    assert ax.xlim[1] - ax.xlim[0] < (full.xlim[1] - full.xlim[0]) / 5.0
    assert (ax.x_major, ax.x_minor) == (5.0, 1.0)
    assert (ax.y_major, ax.y_minor) == (20.0, 4.0)


def test_axis_has_minimum_padding(pool_points):
    """单点不能贴着轴边框（`MIN_PAD` 兜底）。

    容差要比 `MIN_PAD` 松一点：轴范围会被归整到 2 位小数（为了出图好看），
    实测 PL-12 的左边距是 11.99975 而不是正好 12。
    """
    one = [p for p in pool_points if p.key == "PL-12"]
    ax = figures.adaptive_axis(one)
    p = one[0]
    assert p.dv - ax.xlim[0] >= 12.0 - 0.01, f"ΔV 左边距只有 {p.dv - ax.xlim[0]}"
    assert ax.xlim[1] - p.dv >= 12.0 - 0.01
    assert p.bc - ax.ylim[0] >= 60.0 - 0.01, f"BC 下边距只有 {p.bc - ax.ylim[0]}"
    assert ax.ylim[1] - p.bc >= 60.0 - 0.01


def test_axis_accepts_two_missiles_and_keeps_default_ticks(pool_points):
    two = [p for p in pool_points if p.key in ("120A", "R-77-1")]
    ax = figures.adaptive_axis(two)
    for p in two:
        assert ax.xlim[0] < p.dv < ax.xlim[1]
        assert ax.ylim[0] < p.bc < ax.ylim[1]
    assert ax.x_major % ax.x_minor == pytest.approx(0.0), "次刻度要整除主刻度"
    assert ax.y_major % ax.y_minor == pytest.approx(0.0)


def test_axis_spec_serializes():
    d = figures.adaptive_axis(pool.points("PL-12,120C")).as_dict()
    for k in ("xlim", "ylim", "x_major", "x_minor", "y_major", "y_minor"):
        assert k in d

def test_plane_grid_axis_aliases_match_the_legacy_field_names():
    """`PlaneGrid.dv ≡ β`、`PlaneGrid.bc ≡ ginv` 这条**命名陷阱**要有判据钉住。

    `dv`/`bc` 是图1（ΔV–BC 平面）的老名字，图2 里装的却是 β 与 ginv —— 这是全仓最容易
    把两轴读反的地方（`results/bg_default.json` 的 `scan` 块就是按这个语义写的）。
    别名 `beta`/`ginv` 是给新代码用的：读 `grid.ginv` 一眼就知道是"轴量"，不用去猜 `bc`。
    """
    g = PlaneGrid(dv=(2500.0, 3000.0), bc=(0.01, 0.02),
                  dv_step=500.0, bc_step=0.01)
    assert g.beta == g.dv and g.beta is g.dv            # 同一个元组对象，不是拷贝
    assert g.ginv == g.bc and g.ginv is g.bc
    # 名字很容易被"顺手改回去"：这里显式钉住字段名，改名就会红
    assert (g.dv[0], g.dv[-1]) == (2500.0, 3000.0)      # dv 装 β
    assert (g.bc[0], g.bc[-1]) == (0.01, 0.02)          # bc 装 ginv（不是 γ！）
    # `cells` 的行主序语义：外层 dv(β)、内层 bc(ginv)，与 t_hit 矩阵 reshape 一致
    assert list(g.cells) == [(2500.0, 0.01), (2500.0, 0.02),
                             (3000.0, 0.01), (3000.0, 0.02)]
    assert g.shape == (2, 2) and g.n_cases == 4

# -*- coding: utf-8 -*-
"""弹池与映射层回归：ΔV/BC 黄金值、输入解析、ΔV·BC ↔ 乘数往返。

**这一层不跑求解器**，所以可以放心地把 11 型全量核对一遍（约 1~2 s）。
散点用的 ΔV/BC 如果和求解器物理不同源，整张图就是错的 —— 所以这里是硬门槛。
"""

from __future__ import annotations

import math

import pytest

from missile_sim import mapping, pool
from missile_sim.spec import velocity_vector

#: 黄金值：`results/missile_standards.json` 的 `impulse.dv/bc`（2026-09-27 核对**逐值一致**）。
#: 改这里之前先问自己：是 vendor 的 blk 变了，还是公式变了？
GOLD = {
    "120A": (820.47, 3609.0),
    "120C": (897.39, 3624.0),
    "120D": (891.29, 3653.8),
    "MICA": (946.99, 2636.0),
    "AAM-4": (826.28, 3683.9),
    "PL-12": (932.57, 3078.1),
    "PL-12A": (989.08, 3245.9),
    "R-77": (965.66, 2568.8),
    "R-77-1": (1099.53, 2705.6),
    "Derby": (932.81, 2567.0),
    "R-Darter": (913.89, 2631.2),
}

#: 11 型现算一次就够（每次都要读 blk + 套公式）。
_POINTS = {}


@pytest.fixture(scope="module")
def points():
    if not _POINTS:
        for p in pool.points():
            _POINTS[p.key] = p
    return _POINTS


# --------------------------------------------------------------- 弹池结构


def test_pool_has_eleven_unique_entries():
    assert len(pool.POOL) == 11
    keys = pool.names()
    assert len(set(keys)) == 11
    natives = [e.native for e in pool.POOL]
    assert len(set(natives)) == 11, "vendor 预设名不能重复"


def test_default_standard_is_pl12():
    assert pool.standard_entry().key == "PL-12"
    assert pool.standard_entry("R-77-1").native == "su_r_77_1"


def test_resolve_is_case_and_separator_insensitive():
    assert pool.resolve("pl-12").key == "PL-12"
    assert pool.resolve("PL_12").key == "PL-12"
    assert pool.resolve(" r-77-1 ").key == "R-77-1"
    assert pool.resolve("mica").key == "MICA"


def test_resolve_unknown_raises_and_suggests():
    with pytest.raises(pool.PoolError):
        pool.resolve("AIM-9X")
    try:
        pool.resolve("PL-12B")
    except pool.PoolError as exc:
        assert "PL-12" in str(exc), "应该给出最接近的建议"


def test_resolve_many_accepts_string_and_dedupes_keeping_order():
    got = pool.resolve_many("R-77-1, 120A,R-77-1")
    assert [e.key for e in got] == ["R-77-1", "120A"]
    assert [e.key for e in pool.resolve_many(None)] == pool.names()
    assert [e.key for e in pool.resolve_many("")] == pool.names()
    with pytest.raises(pool.PoolError):
        pool.resolve_many("  ")


def test_points_follows_user_order(points):
    got = [p.key for p in pool.points("R-77-1,120A")]
    assert got == ["R-77-1", "120A"]


# --------------------------------------------------------------- 黄金值


def test_every_pool_missile_matches_authoritative_table(points):
    """现算值 vs 权威表 —— 这是"散点与求解器同源"的证据。"""
    assert set(points) == set(GOLD), "弹池成员与黄金表不一致"
    bad = []
    for key, (dv, bc) in GOLD.items():
        p = points[key]
        if not math.isclose(p.dv, dv, rel_tol=1e-4) or not math.isclose(p.bc, bc, rel_tol=1e-4):
            bad.append(f"{key}: 现算 {p.dv:.2f}/{p.bc:.1f} vs 权威 {dv}/{bc}")
    assert not bad, "ΔV/BC 与权威表不一致：\n  " + "\n  ".join(bad)


def test_two_stage_flags(points):
    """二阶装药的型号必须被识别出来（`massEnd1` 存在）—— 这是曾算错的那个坑。"""
    two = {k for k, p in points.items() if p.two_stage}
    assert two, "至少要有一型是两级的，否则说明 staging 判定失效"
    assert "120A" in two or "PL-12" in two


def test_caliber_is_metres_not_millimetres(points):
    """口径必须是米（0.17~0.23），不是毫米（170~230）。"""
    for key, p in points.items():
        assert 0.10 < p.caliber_m < 0.30, f"{key} 口径 {p.caliber_m} 不像米制"


def test_pool_table_columns():
    rows = pool.pool_table("PL-12,120C")
    assert len(rows) == 2
    for r in rows:
        for col in ("key", "label", "full_name", "native", "dv", "bc",
                    "dry_kg", "cxk", "caliber_m", "two_stage"):
            assert col in r, f"pool_table 缺列 {col}"


# --------------------------------------------------------------- 映射往返


def test_surface_area_matches_formula():
    assert mapping.surface_area_m2(0.2) == pytest.approx(math.pi * 0.1 ** 2, rel=1e-12)


def test_scaling_roundtrip_recovers_target(points):
    """乘数必须能反推回目标 (ΔV, BC) —— 不能反推的乘数就是错的乘数。"""
    m = pool.metrics_of(pool.resolve("PL-12"))
    sc = mapping.scaling_for(800.0, 3000.0, m)
    assert sc.thrust_scale == pytest.approx(800.0 / m.dv, rel=1e-9)
    sd = mapping.surface_area_m2(m.caliber_m)
    bc_back = m.dry_kg / (m.cxk * sc.cx_scale * sd)
    assert bc_back == pytest.approx(3000.0, rel=1e-9)


def test_scaling_at_nominal_is_one(points):
    """按标称值要乘数，乘数必须是 1 —— 否则金标工况会被悄悄改掉。"""
    m = pool.metrics_of(pool.resolve("R-77-1"))
    sc = mapping.scaling_for(m.dv, m.bc, m)
    assert sc.thrust_scale == pytest.approx(1.0, rel=1e-9)
    assert sc.cx_scale == pytest.approx(1.0, rel=1e-9)


def test_scaling_accepts_none(points):
    sc = mapping.scaling_for(None, None, pool.metrics_of(pool.resolve("PL-12")))
    assert sc.thrust_scale == 1.0 and sc.cx_scale == 1.0


def test_dv_scales_linearly_and_bc_inversely(points):
    m = pool.metrics_of(pool.resolve("PL-12"))
    a = mapping.scaling_for(m.dv * 2.0, m.bc, m)
    b = mapping.scaling_for(m.dv, m.bc * 2.0, m)
    assert a.thrust_scale == pytest.approx(2.0, rel=1e-12)
    assert b.cx_scale == pytest.approx(0.5, rel=1e-12), "BC 翻倍 ⇒ 阻力系数减半"


# --------------------------------------------------------------- 坐标系


def test_velocity_vector_directions():
    """零航向 +x、正航向 → +z、俯仰抬头为 +y，且 |v| 恒等于标量。"""
    cases = [
        ((100.0, 0.0, 0.0), (100.0, 0.0, 0.0)),
        ((100.0, 90.0, 0.0), (0.0, 0.0, 100.0)),
        ((100.0, 180.0, 0.0), (-100.0, 0.0, 0.0)),
        ((100.0, 0.0, 90.0), (0.0, 100.0, 0.0)),
        ((100.0, 0.0, -90.0), (0.0, -100.0, 0.0)),
    ]
    for args, want in cases:
        got = velocity_vector(*args)
        for g, w in zip(got, want):
            assert g == pytest.approx(w, abs=1e-9), f"{args} → {got}，期望 {want}"


def test_velocity_vector_preserves_magnitude():
    for speed in (0.0, 1.0, 300.0, 1200.0):
        for heading in (0.0, 37.0, 180.0, 359.0):
            for pitch in (-80.0, -10.0, 0.0, 45.0, 89.0):
                v = velocity_vector(speed, heading, pitch)
                assert math.sqrt(sum(x * x for x in v)) == pytest.approx(speed, abs=1e-9)

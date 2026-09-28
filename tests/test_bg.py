# -*- coding: utf-8 -*-
"""`bg.py`（β–γ 能力平面）的黄金值回归。

黄金值来自 `E:\\War Thunder\\_recon` 的既有研究，**不是本模块自己算出来再抄回去的**：
`βeff与诱导阻力量化_推导与解释.md` §8 的表给定了 h=10 km / V=800 m/s 下 9 型的
β / γ / Q / n*，`弹道系数BC与含诱导阻力存能指标_分析与方案.md` §2.1 给定了参考工况的
q / f / F。本文件把它们钉住 —— 换内核或改口径时，这里会先红。
"""

import math

import pytest

from missile_sim import bg, mapping, pool, solver

#: 参考工况（`_recon` 文档 §2.1）：h=10 km, V=800 m/s → q=132364 Pa, f=0.37624, F=1.16626
DOC_Q_PA = 132363.7
DOC_F = 0.37624
DOC_F_CAP = 1.16626
DOC_F_RATIO = 3.0998

#: 文档 §8 的 9 型：(β, γ, Q, n*)
DOC_TABLE = {
    "MICA":   (2636.0, 64.43, 725.6, 18.60),
    "PL-12":  (3078.1, 56.60, 734.9, 18.36),
    "120A":   (3609.0, 53.49, 773.6, 17.44),
    "PL-12A": (3245.9, 59.69, 775.0, 17.41),
    "120C":   (3624.0, 56.60, 797.4, 16.92),
    "120D":   (3653.8, 57.06, 803.9, 16.78),
    "R-77":   (2568.8, 91.19, 852.1, 15.83),
    "R-77-1": (2705.6, 87.29, 855.6, 15.77),
    "AAM-4":  (3683.9, 89.32, 1009.9, 13.36),
}

#: 文档 §8 的 R(20G)
DOC_R20 = {"MICA": 1.157, "PL-12": 1.187, "120A": 1.315, "AAM-4": 2.241}

#: 文档 §8 的 β_eff(20G)
DOC_BEFF20 = {"MICA": 1222.2, "PL-12": 1407.7, "120A": 1559.1, "120C": 1511.9,
              "120D": 1509.8, "R-77": 989.7, "R-77-1": 1037.2, "AAM-4": 1136.7,
              "PL-12A": 1399.4}


def test_reference_condition_matches_document():
    """参考工况必须与文档逐值一致 —— 等值线依赖它，偏一点整族线就错位。"""
    alt, speed, mach, q_pa, f_mach, cap_f = bg.reference()
    assert (alt, speed) == (bg.REF_ALT_M, bg.REF_SPEED_MS)
    assert mach == pytest.approx(2.6604, abs=1e-3)
    assert q_pa == pytest.approx(DOC_Q_PA, abs=0.5)
    assert f_mach == pytest.approx(DOC_F, abs=1e-5)
    assert cap_f == pytest.approx(DOC_F_CAP, abs=1e-5)
    assert cap_f / f_mach == pytest.approx(DOC_F_RATIO, abs=1e-4)


def test_beta_equals_the_shells_own_bc():
    """β 与既有 BC 必须是同一个数（11/11）—— 第二张图的横轴就是第一张图的纵轴。"""
    for p in bg.points():
        bc = mapping.blk_metrics(solver.profile(pool.resolve(p.key).native)).bc
        assert p.beta == pytest.approx(bc, rel=1e-12), p.key


@pytest.mark.parametrize("key", sorted(DOC_TABLE))
def test_golden_beta_gamma_q_nstar(key):
    """文档 §8 的 9 型黄金值。"""
    want_b, want_g, want_q, want_n = DOC_TABLE[key]
    p = next(x for x in bg.points() if x.key == key)
    ref = bg.evaluate_point(p, n=20.0)
    assert p.beta == pytest.approx(want_b, abs=0.15), key
    assert p.gamma == pytest.approx(want_g, abs=0.15), key
    assert ref.q_sens == pytest.approx(want_q, abs=0.15), key
    assert ref.n_star == pytest.approx(want_n, abs=0.02), key


@pytest.mark.parametrize("key", sorted(DOC_R20))
def test_golden_ratio_at_20g(key):
    """文档 §8 的 R(20G)。"""
    p = next(x for x in bg.points() if x.key == key)
    assert bg.evaluate_point(p, n=20.0).ratio == pytest.approx(DOC_R20[key], abs=0.002)


@pytest.mark.parametrize("key", sorted(DOC_BEFF20))
def test_golden_beta_eff_at_20g(key):
    """文档 §8 的 β_eff(20G)。"""
    assert bg.row_of(key).beta_eff == pytest.approx(DOC_BEFF20[key], abs=0.15), key


def test_rows_shape_and_order():
    """`rows()` 的规模、顺序与值域 —— 出图模块只吃这一种输入。"""
    rs = bg.rows()
    assert len(rs) == 11
    assert [r.key for r in rs] == pool.names()
    for r in rs:
        assert r.beta > 0 and r.gamma > 0 and r.dv > 0 and r.n_star > 0
        assert r.beta_eff < r.beta          # 有参考过载 ⇒ 等效系数必然小于 β
        assert r.q_sens > 0 and r.ratio > 1.0   # 参考工况 20G 下全部处于机动主导区
    assert [r.key for r in bg.rows(["PL-12", "R-77-1"])] == ["PL-12", "R-77-1"]
    assert bg.row_of("PL-12").beta == pytest.approx(3078.05, abs=0.01)


def test_ratio_identity_r_equals_n_over_nstar_squared():
    """`R = (n/n*)²` —— 文档 §5 的两个等价形式必须一致到机器精度。"""
    for p in bg.points():
        ref = bg.evaluate_point(p, n=20.0)
        assert ref.ratio == pytest.approx((20.0 / ref.n_star) ** 2, rel=1e-12), p.key


def test_beta_eff_shrinks_as_load_grows():
    """`β_eff = β/(1+R)`：过载越大掉得越多，n→0 时退化为 β。"""
    p = next(x for x in bg.points() if x.key == "AAM-4")
    prev = math.inf
    for n in (5.0, 10.0, 20.0, 30.0):
        be = bg.evaluate_point(p, n=n).beta_eff
        assert be < prev
        assert be < p.beta
        prev = be
    assert bg.evaluate_point(p, n=1e-9).beta_eff == pytest.approx(p.beta, rel=1e-6)


def test_nstar_curve_is_a_hyperbola_and_round_trips():
    """等 n* 线 `γ ∝ 1/β`（双曲线），代回去必须还原同一个 n*。"""
    betas = [2600.0, 3000.0, 3400.0, 3800.0]
    for nst in (14.0, 16.0, 18.0, 20.0):
        gammas = bg.nstar_curve(nst, betas)
        assert all(g > 0 for g in gammas)
        # γ 随 β 单调下降 ⇒ 确实是 1/β 形状
        assert all(gammas[i] > gammas[i + 1] for i in range(len(gammas) - 1))
        for b, g in zip(betas, gammas):
            assert bg.evaluate(b, g, n=20.0).n_star == pytest.approx(nst, rel=1e-12)


def test_gamma_uses_kernel_defaults_not_our_own_constants():
    """`CxAoA`/`CyK` 必须取自内核（blk 里没有这两个键，内核兜底 9.0 / 2.2）。"""
    for p in bg.points():
        cx_aoa, cyk = solver.body_aero(pool.resolve(p.key).native)
        assert p.cx_aoa == pytest.approx(cx_aoa, rel=1e-12), p.key
        assert p.cyk == pytest.approx(cyk, rel=1e-12), p.key
    # 11 型都落到同一个默认值上 —— 这是本项目的已知数据事实（见 docs/BETA-GAMMA.md §2.2）
    assert {p.cx_aoa for p in bg.points()} == {9.0}
    assert {p.cyk for p in bg.points()} == {2.2}


def test_the_two_axes_are_not_collinear():
    """两轴不能退化：若 γ 是 β 的纯函数，这张图就没有二维信息。"""
    ps = bg.points()
    bs = [p.beta for p in ps]
    gs = [p.gamma for p in ps]
    mb, mg = sum(bs) / len(bs), sum(gs) / len(gs)
    num = sum((b - mb) * (g - mg) for b, g in zip(bs, gs))
    den = math.sqrt(sum((b - mb) ** 2 for b in bs) * sum((g - mg) ** 2 for g in gs))
    r = num / den
    assert abs(r) < 0.9, f"β 与 γ 近乎共线（r={r:.3f}），二维平面失去意义"


def test_bad_inputs_are_rejected():
    with pytest.raises(ValueError):
        bg.evaluate(0.0, 50.0)
    with pytest.raises(ValueError):
        bg.evaluate(3000.0, -1.0)
    with pytest.raises(ValueError):
        bg.nstar_curve(0.0, [3000.0])
    with pytest.raises(ValueError):
        bg.reference(speed_ms=0.0)


def test_point_serialises_for_the_manifest():
    """产物要落盘，`as_dict()` 的键必须稳定。"""
    p = bg.points(["PL-12"])[0]
    d = p.as_dict()
    assert set(d) == {"key", "beta", "gamma", "dry_kg", "sd_m2", "sl_m2", "cxk",
                      "cx_aoa", "cyk", "caliber_m", "length_m", "wing_area_mult"}
    r = bg.evaluate_point(p, n=20.0).as_dict()
    assert set(r) == {"alt_m", "speed_ms", "mach", "q_pa", "f_mach", "cap_f",
                      "beta", "gamma", "q_sens", "n_star", "n", "ratio", "beta_eff"}

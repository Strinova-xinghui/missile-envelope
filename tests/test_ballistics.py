"""弹道/制导纯函数与参数换算测试。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from missile_sim import ballistics  # noqa: E402
from missile_sim.config import (  # noqa: E402
    ConfigError,
    a_drag_coeff,
    ballistic_coefficient,
    cxk_for_bc,
    delta_v_equiv,
    load_config,
    s_ref,
)


# --------------------------------------------------------------------- 参数换算


def test_s_ref_from_caliber():
    cfg = load_config()
    assert abs(s_ref(cfg) - math.pi * (cfg.drag.caliber_m / 2.0) ** 2) < 1e-15


def test_bc_cxk_roundtrip():
    cfg = load_config()
    for bc in (1700.0, 2500.0, 3078.0, 3624.0, 4000.0):
        cx = cxk_for_bc(bc, cfg)
        assert abs(ballistic_coefficient(cx, cfg) - bc) < 1e-9
    # 基准点自洽：配置里的 CxK 对应标准弹自己的 BC（默认 PL-12：1.325 ↔ 3078.1）
    assert cfg.profile is not None
    assert abs(ballistic_coefficient(cfg.drag.cxk, cfg) - cfg.profile.bc) < 0.1


def test_bc_rejects_non_positive():
    cfg = load_config()
    with pytest.raises(ConfigError):
        cxk_for_bc(0.0, cfg)
    with pytest.raises(ConfigError):
        cxk_for_bc(-100.0, cfg)


def test_delta_v_matches_rocket_equation():
    """ΔV = ve_eff · ln(m0/m_dry)；ve_eff 现在是**标准弹导出值**（不再是硬编码 2266）。"""
    from missile_sim.config import effective_ve_equiv

    cfg = load_config()
    m0, m1 = cfg.mass.mass_launch, cfg.mass.mass_end
    ve = effective_ve_equiv(cfg)
    assert abs(delta_v_equiv(cfg) - ve * math.log(m0 / m1)) < 1e-9
    # 默认 PL-12：ve_eff = ΔV/ln(m0/dry) ⇒ ΔV 应等于标准弹自带值 932.6
    assert cfg.profile is not None
    assert delta_v_equiv(cfg) == pytest.approx(cfg.profile.dv, rel=1e-9)
    assert cfg.profile.dv == pytest.approx(932.6, abs=0.1)
    # 显式覆盖优先（旧口径复现路径）：ΔV 变成 override × 当前质量比
    cfg.impulse.ve_equiv_override = 2266.0
    assert delta_v_equiv(cfg) == pytest.approx(2266.0 * math.log(m0 / m1), rel=1e-12)
    # 换成 120C 标准弹时，同一 override 才给出升级前的 865.31
    c120 = load_config(str(Path(__file__).resolve().parents[1] / "configs" / "standard_120c5.json"))
    c120.impulse.ve_equiv_override = 2266.0
    assert delta_v_equiv(c120) == pytest.approx(865.31, abs=0.02)


def test_drag_coefficient_matches_formula():
    cfg = load_config()
    expect = 0.5 * cfg.drag.cxk * cfg.drag.drag_base * s_ref(cfg) / cfg.mass.mass_end
    assert abs(a_drag_coeff(cfg) - expect) < 1e-18
    # 量级：PL-12 干重 132 kg、口径 0.203 ⇒ ≈1.62e-4 1/m
    assert 1.0e-4 < a_drag_coeff(cfg) < 3.0e-4


def test_drag_k_is_mass_free():
    """`drag_k` 是有限燃烧用的质量无关系数：drag_k = a_drag_coeff × m。"""
    from missile_sim.config import drag_k

    cfg = load_config()
    assert drag_k(cfg) == pytest.approx(a_drag_coeff(cfg) * cfg.mass.mass_end, rel=1e-15)
    assert drag_k(cfg) == pytest.approx(0.5 * cfg.drag.cxk * cfg.drag.drag_base * s_ref(cfg), rel=1e-15)


def test_loft_angle_must_be_below_40_deg():
    cfg = load_config()
    cfg.sim.theta_loft_deg = 40.0
    from missile_sim.config import validate

    with pytest.raises(ConfigError):
        validate(cfg)


# --------------------------------------------------------------------- 视线几何


def test_los_rate_zero_on_collision_course():
    """正对目标、相对速度沿视线方向时，视线角速率必须为 0。"""
    dx, dh = 10000.0, 0.0
    dvx, dvh = -500.0, 0.0
    assert abs(float(ballistics.los_rate(dx, dh, dvx, dvh))) < 1e-12
    assert abs(float(ballistics.closing_speed(dx, dh, dvx, dvh)) - 500.0) < 1e-12


def test_los_rate_matches_finite_difference():
    dx, dh = 8000.0, 1500.0
    dvx, dvh = -400.0, 30.0
    lam_dot = float(ballistics.los_rate(dx, dh, dvx, dvh))
    eps = 1e-3
    lam1 = math.atan2(dh + eps * dvh, dx + eps * dvx)
    lam0 = math.atan2(dh, dx)
    assert abs((lam1 - lam0) / eps - lam_dot) < 1e-6


def test_closing_speed_sign():
    assert float(ballistics.closing_speed(1000.0, 0.0, -100.0, 0.0)) > 0.0   # 接近
    assert float(ballistics.closing_speed(1000.0, 0.0, 100.0, 0.0)) < 0.0    # 远离


def test_scalar_and_array_paths_agree():
    """标量与数组实现必须给出相同结果（两条仿真路径共用的前提）。"""
    for (mx, mh, tx, th) in [(0.0, 10000.0, 50000.0, 10000.0), (100.0, 9000.0, 20000.0, 11000.0)]:
        r_s, l_s = ballistics.range_and_los_s(mx, mh, tx, th)
        r_a, l_a = ballistics.range_and_los(np.array([mx]), np.array([mh]), np.array([tx]), np.array([th]))
        assert abs(r_s - float(r_a[0])) < 1e-9
        assert abs(l_s - float(l_a[0])) < 1e-12
        dx, dh = tx - mx, th - mh
        dvx, dvh = -300.0, 15.0
        assert abs(ballistics.los_rate_s(dx, dh, dvx, dvh) - float(ballistics.los_rate(dx, dh, dvx, dvh))) < 1e-15
        assert abs(ballistics.closing_speed_s(dx, dh, dvx, dvh) - float(ballistics.closing_speed(dx, dh, dvx, dvh))) < 1e-12


# --------------------------------------------------------------------- 动态解锁导引比


def test_gain_schedule_piecewise_values():
    assert abs(ballistics.gain_schedule_s(5.0) - 1.0) < 1e-12
    assert abs(ballistics.gain_schedule_s(10.0) - 1.0) < 1e-12
    assert abs(ballistics.gain_schedule_s(17.5) - 0.9) < 1e-12
    assert abs(ballistics.gain_schedule_s(25.0) - 0.8) < 1e-12
    assert abs(ballistics.gain_schedule_s(50.0) - 0.5) < 1e-12


def test_gain_schedule_clamps_outside_range():
    for t in (0.0, 1.0, 50.0, 100.0, 1e6):
        g = ballistics.gain_schedule_s(t)
        assert 0.5 - 1e-12 <= g <= 1.0 + 1e-12


def test_gain_schedule_array_equals_scalar():
    ts = np.linspace(0.0, 80.0, 161)
    arr = ballistics.gain_schedule(ts)
    for t, expected in zip(ts, arr):
        assert abs(ballistics.gain_schedule_s(float(t)) - float(expected)) < 1e-12


def test_turn_rate_uses_speed():
    assert abs(float(ballistics.turn_rate(350.0, 700.0)) - 0.5) < 1e-12


# --------------------------------------------------------------------- 高抛退出判据


def test_loft_exit_triggers_on_any_criterion():
    kw = dict(margin_rad=math.radians(60.0), dh_gain_max=4000.0, t_loft_max=20.0)
    # 都不满足
    ok, crits = ballistics.loft_exit_condition(math.radians(20.0), math.radians(0.0), 100.0,
                                               1000.0, 2.0, **kw)
    assert not ok
    # 高度增量满足
    ok, crits = ballistics.loft_exit_condition(math.radians(20.0), math.radians(0.0), 100.0,
                                               4200.0, 2.0, **kw)
    assert ok and crits[1]
    # 时间满足
    ok, crits = ballistics.loft_exit_condition(math.radians(20.0), math.radians(0.0), 100.0,
                                               1000.0, 21.0, **kw)
    assert ok and crits[2]
    # 下沉角满足
    ok, crits = ballistics.loft_exit_condition(math.radians(-10.0), math.radians(-80.0), 50.0,
                                               1000.0, 2.0, **kw)
    assert ok and crits[0]
    # 竖直速度非正
    ok, crits = ballistics.loft_exit_condition(math.radians(20.0), math.radians(0.0), -1.0,
                                               1000.0, 2.0, **kw)
    assert ok and crits[3]


def test_loft_exit_array_matches_scalar():
    kwargs = dict(margin_rad=math.radians(60.0), dh_gain_max=4000.0, t_loft_max=20.0)
    gammas = np.radians(np.array([-10.0, 5.0, 20.0, 30.0]))
    los = np.radians(np.array([-80.0, 0.0, 0.0, 10.0]))
    vhs = np.array([50.0, -1.0, 100.0, 100.0])
    dhg = np.array([100.0, 100.0, 4200.0, 100.0])
    tl = np.array([2.0, 2.0, 2.0, 25.0])
    ok_arr, _ = ballistics.loft_exit_condition(gammas, los, vhs, dhg, tl, **kwargs)
    for i in range(4):
        ok_s, _ = ballistics.loft_exit_condition(float(gammas[i]), float(los[i]), float(vhs[i]),
                                                 float(dhg[i]), float(tl[i]), **kwargs)
        assert bool(ok_arr[i]) == bool(ok_s)

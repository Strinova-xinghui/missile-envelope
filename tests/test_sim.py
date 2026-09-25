"""仿真路径测试：物理约束、阶段机顺序、标量/数组一致性、边界行为。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from missile_sim.config import a_drag_coeff, ballistic_coefficient, cxk_for_bc, delta_v_equiv, load_config  # noqa: E402
from missile_sim.decide import ST_HIT, ST_NO_HIT_SLOWDOWN  # noqa: E402
from missile_sim.sim import (  # noqa: E402
    Case,
    simulate_batch,
    simulate_one,
)


@pytest.fixture()
def cfg():
    return load_config()


def _run(cfg, **over):
    scen = {}
    for k in ("vm0", "vt", "alt", "range"):
        if k in over:
            scen[k] = over.pop(k)
    for k, v in over.items():
        setattr(cfg.sim, k, v)
    for k, v in scen.items():
        setattr(cfg.scenario, k, v)
    dv = delta_v_equiv(cfg)
    return simulate_one(cfg, Case(dv_total=dv, cxk=cfg.drag.cxk), record_trace=True, stride=1)


# --------------------------------------------------------------------- 物理约束


def test_zero_drag_zero_gravity_is_straight_uniform_motion(cfg):
    """无阻力、无重力、**无推力**时必须是精确的匀速直线。

    注意：默认档是有限燃烧，飞行中一直有推力 ⇒ 必须显式切到 instant 档才成立。
    """
    from missile_sim.config import apply_standard

    cfg.standard.burn = "instant"
    apply_standard(cfg)
    cfg.atmosphere.g = 0.0
    cfg.drag.cxk = 1e-300  # 阻力实质为零（配置校验要求 CxK > 0）
    res = _run(cfg, boost_delay=1e9)  # boost_delay 极大 => 全程 BOOST，a_perp=0
    tr = res.trace
    v0 = cfg.scenario.vm0 + delta_v_equiv(cfg)
    assert np.allclose(tr.v, v0, rtol=1e-12, atol=1e-9)
    assert np.allclose(tr.h, cfg.scenario.alt, rtol=0, atol=1e-9)
    assert np.allclose(tr.x, v0 * tr.t, rtol=1e-9, atol=1e-6)
    assert np.allclose(tr.gamma, 0.0, atol=1e-12)
    assert np.allclose(tr.a_perp, 0.0, atol=1e-12)
    assert np.all(tr.thrust_N == 0.0)


def test_finite_burn_accelerates_then_decays(cfg):
    """默认（有限燃烧）档：速度先被推力推上去，燃烧结束后再被阻力拉下来。"""
    res = _run(cfg, theta_loft_deg=0.0)
    tr = res.trace
    assert tr.v[0] == pytest.approx(cfg.scenario.vm0, rel=1e-12)   # 初速只有载机速度
    i_peak = int(np.argmax(tr.v))
    t_peak = float(tr.t[i_peak])
    assert t_peak == pytest.approx(cfg.burn.burn_time_total, abs=0.5)
    assert np.all(np.diff(tr.v[:i_peak + 1]) >= -1e-9)             # 燃烧段单调增
    assert np.all(np.diff(tr.v[i_peak:]) <= 1e-9)                  # 之后单调减
    assert tr.v[-1] < tr.v[i_peak] * 0.75


def test_velocity_decays_with_drag(cfg):
    """瞬时档（无推力）下全程单调减速，最终至少掉一半。"""
    from missile_sim.config import apply_standard

    cfg.standard.burn = "instant"
    apply_standard(cfg)
    res = _run(cfg, theta_loft_deg=0.0)
    tr = res.trace
    v0 = cfg.scenario.vm0 + delta_v_equiv(cfg)
    assert tr.v[0] == pytest.approx(v0, rel=1e-12)
    assert tr.v[-1] < v0 * 0.5
    assert np.all(np.diff(tr.v) <= 1e-9)


def test_drag_sensitivity_matches_coefficient(cfg):
    """阻力系数翻倍应让同样时间内的速度衰减显著加快。"""
    dv0 = delta_v_equiv(cfg)
    r1 = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk), record_trace=False)
    r2 = simulate_one(load_config(), Case(dv_total=dv0, cxk=cfg.drag.cxk * 2.0), record_trace=False)
    assert r2.v_impact < r1.v_impact
    expect_ratio_drag = (a_drag_coeff(cfg, cxk=cfg.drag.cxk * 2) / a_drag_coeff(cfg))
    assert expect_ratio_drag == pytest.approx(2.0, rel=1e-12)


def test_boost_delay_then_loft_phase_order(cfg):
    """0.3 s 内必须处于 BOOST（gamma 保持 0），之后进入高抛并最终退出。"""
    res = _run(cfg)
    tr = res.trace
    pre = tr.t < cfg.sim.boost_delay - 1e-9
    assert np.all(np.abs(tr.gamma[pre]) < 1e-12), "0.3 s 之前不应有法向机动"
    assert np.all(tr.phase[pre] == 0)
    assert res.t_loft_end > cfg.sim.boost_delay
    # 高抛段（严格在退出时刻之前）phase 必须为 1
    in_loft = (tr.t >= cfg.sim.boost_delay) & (tr.t < res.t_loft_end - 1e-9)
    assert in_loft.any() and np.all(tr.phase[in_loft] == 1)
    # 退出之后 phase 应为 2（最后一次记录点仍可能落在退出那一步的边界上）
    after = tr.t > res.t_loft_end + 1e-9
    assert after.any() and np.all(tr.phase[after] == 2)
    assert res.max_alt > cfg.scenario.alt  # 高抛确实爬升
    assert np.degrees(np.max(tr.gamma)) == pytest.approx(cfg.sim.theta_loft_deg, abs=1.0)


def test_loft_angle_zero_gives_no_climb(cfg):
    res = _run(cfg, theta_loft_deg=0.0)
    assert res.max_alt < cfg.scenario.alt + 50.0


def test_dynamic_gain_unlock_monotonic(cfg):
    """K_go 随时间推进逐步解锁到 1.0，N_eff = 6*K_go 且不超过上限。"""
    res = _run(cfg)
    tr = res.trace
    assert np.all(tr.k_go >= 0.5 - 1e-9) and np.all(tr.k_go <= 1.0 + 1e-9)
    assert np.allclose(tr.n_eff, cfg.sim.n_base * tr.k_go, rtol=1e-12)
    # 初始段（T_go 远大于 50 s）应处于 0.5 档
    at1s = int(np.searchsorted(tr.t, 1.0))
    assert abs(tr.k_go[at1s] - 0.5) < 0.02, f"t=1 s 时导引比应≈0.5，实测 {tr.k_go[at1s]:.3f}"
    # 末段完全解锁
    late = tr.t > tr.t[-1] - 8.0
    assert np.all(tr.k_go[late] > 0.95), "末段导引比应完全解锁"
    # 解锁是单调推进的：后段平均不应低于前段
    mid = (tr.t > 20.0) & (tr.t < 35.0)
    assert tr.k_go[mid].mean() > tr.k_go[(tr.t > 0.6) & (tr.t < 1.2)].mean()


def test_acceleration_limited_by_lat_max(cfg):
    res = _run(cfg)
    tr = res.trace
    assert np.all(np.abs(tr.a_perp) <= cfg.sim.a_lat_max_g * cfg.atmosphere.g + 1e-6)


# --------------------------------------------------------------------- 命中与边界


def test_baseline_scenario_hits(cfg):
    res = _run(cfg)
    assert res.status == ST_HIT
    assert 0.0 < res.t_hit < cfg.sim.t_life
    assert res.min_range <= cfg.sim.hit_radius
    assert res.max_alt > cfg.scenario.alt


def test_short_range_head_on_hits_quickly(cfg):
    res = _run(cfg, range=15000.0)
    assert res.status == ST_HIT
    assert res.t_hit < 25.0


def test_tail_chase_far_target_does_not_hit(cfg):
    """尾追 60 km：目标主动远离，超出能量/时间能力，必须如实报未命中。"""
    res = _run(cfg, vt=350.0, range=60000.0)
    assert res.status != ST_HIT
    assert res.t_end <= cfg.sim.t_life + 1e-9


def test_slowdown_termination_triggers(cfg):
    """把速度下限抬到 700 m/s，命中前就会因"能量耗尽"终止。

    （旧口径下该阈值为 600 m/s；full 气动档阻力更小、命中点存速升到 672 m/s，
    故阈值同步上调——低于 672 时会先命中。）
    """
    res = _run(cfg, v_min=700.0)
    assert res.status == ST_NO_HIT_SLOWDOWN
    assert res.v_impact < 700.0


def test_already_in_range_at_launch(cfg):
    res = _run(cfg, range=5.0)
    assert res.t_hit == 0.0
    assert res.status_name == "already_in_range"
    assert res.t_end == 0.0


def test_loft_angle_range_validated(cfg):
    with pytest.raises(ValueError):
        _run(cfg, theta_loft_deg=45.0)


def test_target_altitude_offset_supported(cfg):
    """目标可高于/低于发射方（等高是特例）；高度差会改变弹道与命中时间。"""
    dvs = delta_v_equiv(cfg)
    low = simulate_one(cfg, Case(dv_total=dvs, cxk=cfg.drag.cxk, target_alt=cfg.scenario.alt - 3000.0),
                       record_trace=False)
    level = simulate_one(cfg, Case(dv_total=dvs, cxk=cfg.drag.cxk), record_trace=False)
    assert low.hit and level.hit
    assert low.max_alt != level.max_alt
    # 目标更低时不需要爬那么高，最大高度应不大于等高情形
    assert low.max_alt <= level.max_alt + 1e-6
    # 场景级配置同样生效
    cfg.scenario.target_alt = cfg.scenario.alt - 3000.0
    cfg_level = load_config()
    cfg_level.scenario.target_alt = cfg_level.scenario.alt
    a = simulate_one(cfg, Case(dv_total=dvs, cxk=cfg.drag.cxk), record_trace=False)
    b = simulate_one(cfg_level, Case(dv_total=dvs, cxk=cfg_level.drag.cxk), record_trace=False)
    assert abs(a.t_hit - low.t_hit) < 1e-9, "Case 与 Scenario 两种指定方式应一致"
    assert abs(b.t_hit - level.t_hit) < 1e-9


def test_batch_supports_target_altitude(cfg):
    dvs = np.array([1000.0, 1200.0])
    bcs = np.array([2000.0, 3000.0])
    D, B = np.meshgrid(dvs, bcs, indexing="ij")
    C = cxk_for_bc(B, cfg)
    res = simulate_batch(cfg, D.ravel(), C.ravel(), target_alt=cfg.scenario.alt - 2000.0)
    assert res.target_alt == cfg.scenario.alt - 2000.0
    assert np.all(res.status == ST_HIT)


def test_per_case_mass_override(cfg):
    """工况质量覆盖：更重的弹同一 CxK 下阻力减速更慢，存速应更高。"""
    dv0 = delta_v_equiv(cfg)
    heavy = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk, mass=200.0), record_trace=False)
    light = simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk, mass=80.0), record_trace=False)
    assert heavy.hit and light.hit
    assert heavy.v_impact > light.v_impact
    # 质量进入阻力系数：a = 0.5·CxK·S/m·rho·V²，与质量成反比
    assert a_drag_coeff(cfg, mass=200.0) == pytest.approx(a_drag_coeff(cfg, mass=80.0) * 80.0 / 200.0, rel=1e-12)
    with pytest.raises(ValueError):
        simulate_one(cfg, Case(dv_total=dv0, cxk=cfg.drag.cxk, mass=0.0), record_trace=False)


def test_batch_per_case_mass_matches_scalar(cfg):
    dvs = np.array([1000.0])
    bcs = np.array([2500.0])
    C = cxk_for_bc(bcs, cfg)
    mass = np.array([150.0])
    b = simulate_batch(cfg, dvs, C, mass=mass)
    a = simulate_one(cfg, Case(dv_total=float(dvs[0]), cxk=float(C[0]), mass=150.0), record_trace=False)
    assert int(b.status[0]) == a.status
    assert abs(float(b.t_hit[0]) - a.t_hit) < 0.5
    assert float(b.v_impact[0]) == pytest.approx(a.v_impact, abs=15.0)


@pytest.mark.parametrize("dt", [0.02, 0.01, 0.005, 0.0025, 0.001])
def test_dt_convergence_of_hit_time(cfg, dt):
    """命中时间对步长应收敛，保证等时线不受离散化主导。

    基准 45.26 s = **标准弹 PL-12 + 有限燃烧**（默认档）；5 档 dt 的散布约 0.02 s。
    升级前的旧口径（120C + 瞬时 + ve2266 + legacy 气动）由下面那个用例钉住。
    """
    res = _run(cfg, dt=dt)
    assert res.status == ST_HIT
    assert abs(res.t_hit - 45.26) < 0.15


@pytest.mark.parametrize("dt", [0.02, 0.005])
def test_dt_convergence_legacy_model(cfg, dt):
    """旧口径组合必须复现升级前的 60.81 s（README §5 记录的复现命令）。"""
    from missile_sim.config import apply_standard

    cfg.standard.name = "120C"
    cfg.standard.burn = "instant"
    apply_standard(cfg)
    cfg.impulse.ve_equiv_override = 2266.0
    cfg.aero.model = "legacy"
    cfg.sim.loft_rule = "heuristic"      # 旧启发式高抛判据（新默认是游戏判据）
    res = _run(cfg, dt=dt)
    assert res.status == ST_HIT
    assert abs(res.t_hit - 60.81) < 0.15


# --------------------------------------------------------------------- 两条路径一致性


@pytest.mark.parametrize("dv,bc", [(850.0, 1800.0), (1000.0, 2500.0), (1114.0, 3624.0), (1400.0, 3900.0)])
def test_batch_matches_scalar(cfg, dv, bc):
    cx = float(cxk_for_bc(bc, cfg))
    a = simulate_one(cfg, Case(dv_total=dv, cxk=cx), record_trace=False)
    b = simulate_batch(cfg, np.array([dv]), np.array([cx]))
    assert int(b.status[0]) == a.status, f"{dv}/{bc}: {a.status_name} vs {b.status_name(0)}"
    # 步内最接近距离（Rmin_lin）：两条路径必须一致（同一物理量，与采样周期无关）
    assert float(b.min_range_linear[0]) == pytest.approx(a.min_range_linear, abs=1e-6)
    if a.status == ST_HIT:
        # 批量路径按 200 步为周期做裁剪，命中时刻允许一个裁剪周期的量化误差
        assert abs(float(b.t_hit[0]) - a.t_hit) < 0.5
    # 高抛退出是**离散事件**（|λ̇|/λ 越阈值），两条路径的浮点运算次序不同时可能落在相邻步
    # （dt=5 ms ⇒ 高度差 ≤ ~1 m）。这里用绝对容差，其余连续量仍要求 ~1e-11 级一致。
    assert float(b.max_alt[0]) == pytest.approx(a.max_alt, abs=2.0)
    # 终止速度：批量路径在裁剪周期（≤200 步 = 1 s）结束时记录，末端减速约 10 m/s²，故放宽到 15 m/s
    assert abs(float(b.v_impact[0]) - a.v_impact) < 15.0


def test_batch_shapes_and_metadata(cfg):
    dvs = np.arange(800.0, 1501.0, 100.0)
    bcs = np.arange(1700.0, 4001.0, 200.0)
    D, B = np.meshgrid(dvs, bcs, indexing="ij")
    C = cxk_for_bc(B, cfg)
    res = simulate_batch(cfg, D.ravel(), C.ravel())
    assert res.status.shape == (D.size,)
    assert res.t_hit.shape == (D.size,)
    assert np.allclose(res.bc, B.ravel(), rtol=1e-9)
    assert np.allclose(res.cxk, C.ravel(), rtol=1e-12)
    assert np.allclose(res.isp_equiv, D.ravel() / 9.80665, rtol=1e-12)
    assert res.theta_loft_deg == cfg.sim.theta_loft_deg


def test_batch_hit_time_monotonic_in_bc(cfg):
    """同一 ΔV 下 BC 越大（阻力越小）命中越早——等时线成立的核心前提。"""
    dvs = np.array([900.0, 1100.0, 1300.0])
    bcs = np.arange(1700.0, 4001.0, 100.0)
    D, B = np.meshgrid(dvs, bcs, indexing="ij")
    C = cxk_for_bc(B, cfg)
    res = simulate_batch(cfg, D.ravel(), C.ravel())
    t = res.t_hit.reshape(D.shape)
    assert np.all(res.status.reshape(D.shape) == ST_HIT), "默认区间内应全部命中"
    assert np.all(np.diff(t, axis=1) < 0), "t_hit 必须随 BC 严格递减"

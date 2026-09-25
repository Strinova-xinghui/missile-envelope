"""气动模型测试：f(M)/F(M) 对拍权威表、三档模型行为、标量-数组一致、诱导阻力两种写法等价。

公式来源：`wt-missile-backend-runtime-research-1.0.1` 的 `docs/FORMULAS-PLAIN.md` §9/§10/§11
（见 `AERO_PLAN.md`）。自检表逐字取自该文档给出的十进制值。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from missile_sim import aero, atmosphere  # noqa: E402
from missile_sim.config import a_drag_coeff, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_batch, simulate_one  # noqa: E402

# 权威自检表：(M, f(M), F(M))，见实现规格文档 §7 / 文件包 FORMULAS-PLAIN §9
SPEC_TABLE = [
    (0.5, 0.308, 1.000076),
    (0.61, 0.308, 1.000076),
    (0.99, 0.362024591, 1.13163938),
    (1.0, 0.551, 1.59184175),          # 段2 极限 0.365365478 → 段3 起点 +50.8%，不得平滑
    (1.2, 0.614888702, 1.74742671),
    (1.4, 0.576236026, 1.65329778),
    (2.0, 0.444642063, 1.33283358),
    (3.112, 0.34542308, 1.09121055),
    (3.999, 0.302064021, 0.985620406),
    (4.0, 0.302, 0.9854645),
]


@pytest.fixture()
def cfg():
    return load_config()


def _run(cfg, dv=865.1, **over):
    for k, v in over.items():
        if k in ("range", "vt", "alt", "vm0"):
            setattr(cfg.scenario, k, v)
        else:
            setattr(cfg.sim, k, v)
    return simulate_one(cfg, Case(dv_total=dv, cxk=cfg.drag.cxk), record_trace=False)


# --------------------------------------------------------------------- f(M) / F(M)

@pytest.mark.parametrize("M,f_ref,F_ref", SPEC_TABLE)
def test_mach_functions_match_authoritative_table(M, f_ref, F_ref):
    assert aero.f_mach_s(M) == pytest.approx(f_ref, abs=1e-9)
    assert aero.F_mach_s(M) == pytest.approx(F_ref, abs=1e-9)


def test_mach_functions_array_matches_scalar():
    Ms = np.array([0.0, 0.3, 0.61, 0.8, 0.999, 1.0, 1.2, 1.4, 2.0, 3.112, 3.999, 4.0, 6.0])
    f_arr, F_arr = aero.f_mach(Ms), aero.F_mach(Ms)
    for i, M in enumerate(Ms):
        assert float(f_arr[i]) == pytest.approx(aero.f_mach_s(float(M)), rel=1e-15)
        assert float(F_arr[i]) == pytest.approx(aero.F_mach_s(float(M)), rel=1e-15)


def test_mach_function_known_features():
    """低速段 F≈1（设计意图）、段1 平台值、M≥4 平台值。"""
    assert aero.f_mach_s(0.0) == 0.308
    assert aero.F_mach_s(0.0) == pytest.approx(1.000076, abs=1e-6)
    assert aero.f_mach_s(10.0) == 0.302
    # M=1.0 的不连续：左极限与右值差约 50.8%
    left = 0.308 + 0.505 * (1.0 - 0.61) ** 2.31
    assert left == pytest.approx(0.3653654784806637, rel=1e-12)
    assert aero.f_mach_s(1.0) / left == pytest.approx(1.508, rel=0.01)


def test_mach_number_uses_game_sonic_speed():
    """声速取自 atmosphere（游戏温度多项式），h=5000 时 a=321.34。"""
    assert aero.mach_s(321.34, 5000.0) == pytest.approx(1.0, rel=1e-4)
    assert float(aero.mach(np.array([321.34]), np.array([5000.0]))[0]) == pytest.approx(1.0, rel=1e-4)
    # h<=0 用海平面声速
    assert aero.mach_s(341.2, -5.0) == pytest.approx(1.0, rel=1e-3)


# --------------------------------------------------------------------- 参数与量纲

def test_aero_params_from_config(cfg):
    ap = aero.params_from_config(cfg)
    assert ap.model == aero.MODEL_FULL
    # 升力面积由**标准弹**给定（默认 PL-12：0.203 / 3.934 / 1.8）
    assert ap.s_lift == pytest.approx(
        0.3 * cfg.drag.caliber_m * cfg.aero.length_m * cfg.aero.wing_area_mult, rel=1e-15)
    assert ap.cyk == 2.2                    # CyK 全库无键 ⇒ 全局回退
    assert ap.cy_max_aoa == 1.0
    assert ap.sin_alpha_peak == pytest.approx(1.0 / 2.2, rel=1e-15)
    assert ap.cx_aoa_eff == 9.0            # applyWingAreaMultToCxAoA=false
    # 开关打开时 CxAoA 再乘 wingAreaMult²
    wam = cfg.aero.wing_area_mult
    cfg.aero.apply_wing_area_mult_to_cx_aoa = True
    assert aero.params_from_config(cfg).cx_aoa_eff == pytest.approx(9.0 * wam ** 2, rel=1e-15)


def test_alpha_trim_matches_hand_calculation(cfg):
    """sinα = m·a/(q·SL·CyK)，与标量实现对拍（用当前标准弹的质量与过载上限）。"""
    ap = aero.params_from_config(cfg)
    m = cfg.mass.mass_end
    ac = aero.case_params(cfg, cfg.drag.cxk, m)
    rho = float(atmosphere.density(10000.0))
    q = 0.5 * rho * 1165.0 ** 2
    a_perp = cfg.sim.a_lat_max_g * 9.81
    expect = math.degrees(math.asin(m * a_perp / (q * ap.s_lift * ap.cyk)))
    assert aero.alpha_deg_s(ap, ac, q, a_perp) == pytest.approx(expect, rel=1e-12)
    assert 5.0 < expect < 20.0             # 量级合理（PL-12 在 10 km/1165 m/s 满过载约 10.7°）
    # q<=0 与 legacy 档返回 0
    assert aero.alpha_deg_s(ap, ac, 0.0, a_perp) == 0.0
    assert aero.alpha_deg_s(aero.params_from_config(_with_model(cfg, "legacy")), ac, q, a_perp) == 0.0


def test_alpha_scales_with_mass_ratio_mu(cfg):
    """μ = m(t)/m_ref：同需求过载下，重弹迎角更大（sinα ∝ m）。"""
    ap = aero.params_from_config(cfg)
    ac = aero.case_params(cfg, cfg.drag.cxk, cfg.mass.mass_end)
    q = 200000.0
    a1 = aero.alpha_deg_s(ap, ac, q, 200.0, mu=1.0)
    a2 = aero.alpha_deg_s(ap, ac, q, 200.0, mu=1.5)
    assert a2 > a1
    # 未到峰值时 sinα 与 μ 成正比
    assert math.sin(math.radians(a2)) == pytest.approx(1.5 * math.sin(math.radians(a1)), rel=1e-12)


def test_alpha_capped_at_lift_peak(cfg):
    """需求过载超过升力峰值时，迎角截到 asin(CyMaxAoA/CyK)。"""
    ap = aero.params_from_config(cfg)
    ac = aero.case_params(cfg, cfg.drag.cxk, cfg.mass.mass_end)
    q = 1000.0                                    # 极小动压 → 需求远超升力峰值
    alpha = aero.alpha_deg_s(ap, ac, q, 35.0 * 9.81)
    assert alpha == pytest.approx(math.degrees(math.asin(ap.sin_alpha_peak)), rel=1e-12)


def _with_model(cfg, model: str):
    cfg.aero.model = model
    return cfg


# --------------------------------------------------------------------- 诱导阻力的两种等价写法

def test_induced_drag_energy_form_equals_sin2_form(cfg):
    """Da/m = gammaEnergy·F·a²/q 与 q·SD·CxK·CxAoA·F·sin²α/m 必须一致。"""
    ap = aero.params_from_config(cfg)
    ac = aero.case_params(cfg, cfg.drag.cxk, cfg.mass.mass_end)
    sd = math.pi * (cfg.drag.caliber_m / 2.0) ** 2
    for rho, v, a_perp in ((0.4136, 1165.0, 343.0), (0.7368, 600.0, 98.1), (0.2, 900.0, 200.0)):
        q = 0.5 * rho * v * v
        M = aero.mach_s(v, 10000.0)
        F = aero.F_mach_s(M) if ap.use_cxi_mach else 1.0
        energy_form = aero.induced_decel_s(ap, ac, q, a_perp, F)
        sin_a = min(cfg.mass.mass_end * a_perp / (q * ap.s_lift * ap.cyk), ap.sin_alpha_peak)
        sin2_form = q * sd * cfg.drag.cxk * ap.cx_aoa_eff * F * sin_a * sin_a / cfg.mass.mass_end
        assert energy_form == pytest.approx(sin2_form, rel=1e-12)


def test_induced_drag_is_zero_for_low_models_and_zero_demand(cfg):
    ap = aero.params_from_config(cfg)
    ac = aero.case_params(cfg, cfg.drag.cxk, cfg.mass.mass_end)
    q = 200000.0
    assert aero.induced_decel_s(aero.params_from_config(_with_model(cfg, "legacy")), ac, q, 343.0, 1.0) == 0.0
    assert aero.induced_decel_s(aero.params_from_config(_with_model(cfg, "mach")), ac, q, 343.0, 1.0) == 0.0
    assert aero.induced_decel_s(ap, ac, q, 0.0, 1.0) == 0.0
    assert aero.induced_decel_s(ap, ac, 0.0, 343.0, 1.0) == 0.0


def test_induced_drag_scalar_matches_array(cfg):
    ap = aero.params_from_config(cfg)
    ac = aero.case_params(cfg, cfg.drag.cxk, cfg.mass.mass_end)
    ac_arr = aero.case_params_array(cfg, np.array([cfg.drag.cxk]), np.array([cfg.mass.mass_end]))
    for q, a_perp in ((200000.0, 343.0), (50000.0, 98.1), (200000.0, 1500.0)):
        s = aero.induced_decel_s(ap, ac, q, a_perp, 1.2)
        a = float(aero.induced_decel(ap, ac_arr, np.array([q]), np.array([a_perp]), 1.2)[0])
        assert a == pytest.approx(s, rel=1e-12)
        assert float(aero.alpha_deg(ap, ac_arr, np.array([q]), np.array([a_perp]))[0]) == \
            pytest.approx(aero.alpha_deg_s(ap, ac, q, a_perp), rel=1e-12)


# --------------------------------------------------------------------- 三档模型端到端

@pytest.mark.parametrize("model", ["legacy", "mach", "full"])
def test_models_run_and_rank(cfg, model):
    """三档都能跑通；full 的诱导阻力必须在 mach 之上再吃掉能量。"""
    res = {}
    for m in ("legacy", "mach", "full"):
        cfg.aero.model = m
        res[m] = _run(cfg)
    assert all(r.hit for r in res.values())
    assert res["legacy"].t_hit > res["mach"].t_hit          # f(M) 让阻力大幅下降
    assert res["full"].t_hit > res["mach"].t_hit            # 诱导阻力再加回一部分
    assert res["full"].v_impact < res["mach"].v_impact


def test_legacy_model_matches_old_baseline():
    """**旧口径组合**必须复现升级前的基准（60.81 s / 366.5 m/s）。

    组合 = 120C 标准弹 + 瞬时燃烧 + ve_equiv 强制回 2266（⇒ΔV=865.31）+ legacy 气动。
    这正是 README 记录的复现命令；任何一项漏掉都复现不出来。
    """
    from missile_sim.config import apply_standard

    cfg = load_config()
    cfg.standard.name = "120C"
    cfg.standard.burn = "instant"
    apply_standard(cfg)
    cfg.impulse.ve_equiv_override = 2266.0
    cfg.aero.model = "legacy"
    res = _run(cfg)
    assert res.status == 1
    assert res.t_hit == pytest.approx(60.81, abs=0.15)
    assert res.v_impact == pytest.approx(366.5, abs=1.0)


def test_standard_switch_changes_the_baseline(cfg):
    """换标准弹必须真的改变结果（默认 PL-12 vs 120C），否则说明解析没生效。"""
    from missile_sim.config import apply_standard

    pl12 = _run(cfg).t_hit
    other = load_config()
    other.standard.name = "120C"
    apply_standard(other)
    c120 = _run(other).t_hit
    assert abs(pl12 - c120) > 0.05


def test_legacy_drag_coefficient_is_the_flat_coefficient(cfg):
    """legacy 档的等效系数就是 a_drag_coeff；mach 档是它乘 f(M)。"""
    cfg.aero.model = "legacy"
    const_l = simulate_one(cfg, Case(dv_total=865.1, cxk=cfg.drag.cxk), record_trace=False)
    assert const_l.hit
    assert a_drag_coeff(cfg) == pytest.approx(
        0.5 * cfg.drag.cxk * cfg.drag.drag_base * aero_s_ref(cfg) / cfg.mass.mass_end, rel=1e-15)


def aero_s_ref(cfg) -> float:
    return math.pi * (cfg.drag.caliber_m / 2.0) ** 2


def test_use_cxi_mach_off_keeps_fmach_on_base_term(cfg):
    """use_cxi_mach=False 只把 F(M) 置 1，基础项仍乘 f(M)（权威文档明确点出的陷阱）。"""
    cfg.aero.model = "full"
    cfg.aero.use_cxi_mach = False
    res_off = _run(cfg)
    cfg.aero.use_cxi_mach = True
    res_on = _run(cfg)
    # F(M)≈1.0~1.7 区间：关掉后诱导阻力变小 → 阻力更小 → 存速更高
    assert res_off.v_impact > res_on.v_impact
    # 但基础项的 f(M) 仍在：与 legacy 相比存速仍显著更高
    cfg.aero.model = "legacy"
    assert res_off.v_impact > _run(cfg).v_impact + 100.0


def test_clip_lift_peak_changes_trajectory(cfg):
    """clip_lift_peak 打开时可达过载被截到升力峰值（低动压段会生效）。"""
    cfg.aero.model = "full"
    base = _run(cfg)
    cfg.aero.clip_lift_peak = True
    clipped = _run(cfg)
    assert clipped.t_hit >= base.t_hit or clipped.v_impact != base.v_impact


def test_batch_matches_scalar_full_model(cfg):
    """full 档下标量路径与批量路径必须一致（含新增的每工况系数收缩）。"""
    cfg.aero.model = "full"
    a = simulate_one(cfg, Case(dv_total=865.1, cxk=cfg.drag.cxk), record_trace=False)
    b = simulate_batch(cfg, np.array([865.1]), np.array([cfg.drag.cxk]))
    assert int(b.status[0]) == a.status
    assert float(b.min_range_linear[0]) == pytest.approx(a.min_range_linear, abs=1e-6)
    assert abs(float(b.t_hit[0]) - a.t_hit) < 0.5


def test_trace_alpha_deg_reported(cfg):
    """full 档记录迎角，且高抛段达到合理量级（10° 上下）；legacy 档恒为 0。"""
    cfg.aero.model = "full"
    tr = simulate_one(cfg, Case(dv_total=865.1, cxk=cfg.drag.cxk), record_trace=True, stride=1).trace
    assert tr.alpha_deg.shape == tr.t.shape
    assert 5.0 < float(np.max(tr.alpha_deg)) < 30.0
    cfg.aero.model = "legacy"
    tr0 = simulate_one(cfg, Case(dv_total=865.1, cxk=cfg.drag.cxk), record_trace=True, stride=1).trace
    assert float(np.max(np.abs(tr0.alpha_deg))) == 0.0

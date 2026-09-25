"""有限燃烧（N 段）测试：ΔV 守恒、质量/推力时序、缩放规律、标量-批量一致、瞬时档逐位兼容。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from missile_sim import burn  # noqa: E402
from missile_sim.config import apply_standard, delta_v_equiv, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_batch, simulate_one  # noqa: E402

VM0 = 300.0


@pytest.fixture()
def cfg():
    return load_config()


def _vacuum(standard: str, model: str = "finite", t_life: float = 15.0):
    """真空构型：g=0、阻力≈0、legacy 气动 —— 只考察推进与质量。"""
    c = load_config()
    c.standard.name = standard
    c.standard.burn = model
    apply_standard(c)
    c.atmosphere.g = 0.0
    c.drag.drag_base = 1e-12
    c.aero.model = "legacy"
    c.sim.t_life = t_life
    return c


def _run(c, dv, stride=1):
    return simulate_one(c, Case(dv_total=dv, cxk=c.drag.cxk), record_trace=True, stride=stride)


# --------------------------------------------------------------------- ΔV 守恒

@pytest.mark.parametrize("standard", ["PL-12", "120C", "AAM-4", "MICA", "R-77-1"])
def test_vacuum_delta_v_is_delivered(standard):
    """真空下实际速度增量必须等于目标 ΔV（两段弹同样成立）⇒ 推力缩放 s 正确。"""
    dv = 900.0
    tr = _run(_vacuum(standard), dv).trace
    err = float(tr.v.max()) - (VM0 + dv)
    assert abs(err) / dv < 2e-3, f"{standard} 真空 ΔV 误差 {err:+.4f} m/s"


def test_vacuum_delta_v_is_linear_in_target():
    """ΔV ↔ 推力缩放是严格线性的（s = ΔV/ΔV_blk）。"""
    c = _vacuum("PL-12")
    for dv in (700.0, 900.0, 1100.0):
        tr = _run(c, dv).trace
        assert float(tr.v.max()) == pytest.approx(VM0 + dv, rel=2e-3)


def test_instant_burn_is_bit_exact():
    """瞬时档：t=0 就是 vm0+ΔV，且真空下全程不变（旧口径逐位兼容）。"""
    dv = 900.0
    tr = _run(_vacuum("PL-12", "instant"), dv).trace
    assert float(tr.v[0]) == VM0 + dv
    assert float(tr.v.max()) == VM0 + dv
    assert float(tr.thrust_N.max()) == 0.0


def test_finite_burn_needs_time_to_reach_peak():
    """有限燃烧的关键行为：初速只有载机速度，峰值出现在燃烧结束附近（而不是 t=0）。"""
    c = _vacuum("PL-12")
    tr = _run(c, 900.0).trace
    assert float(tr.v[0]) == pytest.approx(VM0, abs=1e-9)
    assert float(tr.v.max()) > float(tr.v[0]) + 800.0
    t_peak = float(tr.t[int(np.argmax(tr.v))])
    assert t_peak == pytest.approx(c.burn.burn_time_total, abs=0.3)


# --------------------------------------------------------------------- 质量/推力时序

def test_trace_mass_and_thrust_timeline_two_stage():
    c = load_config()                     # PL-12：198 → 160 → 132 kg，2.5 s + 5.0 s
    tr = _run(c, delta_v_equiv(c)).trace   # ΔV = 标称值 ⇒ 推力缩放 s=1，可直接对 blk
    m0, mid, dry = 198.0, 160.0, 132.0
    assert float(tr.mass_kg[0]) == pytest.approx(m0)
    assert float(tr.mass_kg[-1]) == pytest.approx(dry)
    # 单调不增
    assert np.all(np.diff(tr.mass_kg) <= 1e-9)
    # 级间切换：t=2.5 s 附近质量应为 mid
    i = int(np.argmin(np.abs(tr.t - 2.5)))
    assert float(tr.mass_kg[i]) == pytest.approx(mid, abs=2.0)
    # 推力两段
    assert float(tr.thrust_N[0]) == pytest.approx(34960.0)
    j = int(np.argmin(np.abs(tr.t - 5.0)))
    assert float(tr.thrust_N[j]) == pytest.approx(12880.0)
    assert float(tr.thrust_N[-1]) == 0.0


def test_trace_mass_and_thrust_timeline_single_stage():
    c = load_config()
    c.standard.name = "120C"
    apply_standard(c)
    tr = _run(c, delta_v_equiv(c)).trace
    assert float(tr.mass_kg[0]) == pytest.approx(161.4789)
    assert float(tr.mass_kg[-1]) == pytest.approx(110.223)
    assert float(tr.thrust_N[0]) == pytest.approx(15542.0)
    # 单段弹不存在第二级：7.75 s 之后推力为 0，且中途不出现 12880 之类的第二级值
    assert float(tr.thrust_N[-1]) == 0.0
    assert c.burn.two_stage is False


def test_burnout_mass_matches_standard_for_all_pool_missiles():
    from missile_sim import standard as standard_mod
    for name in standard_mod.pool_names():
        c = load_config()
        c.standard.name = name
        apply_standard(c)
        tr = _run(c, 900.0, stride=20).trace
        assert float(tr.mass_kg[-1]) == pytest.approx(c.profile.dry_mass, rel=1e-9), name


# --------------------------------------------------------------------- 工况缩放

def test_case_mass_scales_whole_profile_and_keeps_delta_v():
    """`Case.mass` 语义 = 干重锚定值；整条剖面等比缩放，真空 ΔV 不变。"""
    c = _vacuum("PL-12")
    light = _run(c, 900.0)
    heavy = simulate_one(c, Case(dv_total=900.0, cxk=c.drag.cxk, mass=c.profile.dry_mass * 2.0),
                         record_trace=True, stride=1)
    assert float(heavy.trace.mass_kg[0]) == pytest.approx(198.0 * 2.0, rel=1e-9)
    assert float(heavy.trace.mass_kg[-1]) == pytest.approx(132.0 * 2.0, rel=1e-9)
    assert float(heavy.trace.v.max()) == pytest.approx(float(light.trace.v.max()), rel=2e-3)


def test_finite_burn_reduces_peak_speed_versus_instant():
    """同样 ΔV：瞬时档 t=0 就到峰值；有限档峰值更低（燃烧期间被阻力吃掉一部分）。"""
    dv = delta_v_equiv(load_config())
    c_f = load_config()
    c_i = load_config()
    c_i.standard.burn = "instant"
    apply_standard(c_i)
    vf = float(_run(c_f, dv).trace.v.max())
    vi = float(_run(c_i, dv).trace.v.max())
    assert vf < vi


# --------------------------------------------------------------------- 两路径一致

def test_batch_matches_scalar_under_finite_burn():
    c = load_config()
    dv = delta_v_equiv(c)
    a = simulate_one(c, Case(dv_total=dv, cxk=c.drag.cxk), record_trace=False)
    b = simulate_batch(c, np.array([dv]), np.array([c.drag.cxk]))
    assert int(b.status[0]) == a.status
    assert float(b.min_range_linear[0]) == pytest.approx(a.min_range_linear, abs=1e-6)
    assert abs(float(b.t_hit[0]) - a.t_hit) < 0.5


def test_batch_matches_scalar_on_a_small_grid_finite():
    """小网格逐点核对（含不同 ΔV 与 BC ⇒ 不同 k/s）。"""
    c = load_config()
    dvs = np.array([850.0, 950.0, 1050.0])
    bcs = np.array([2800.0, 3100.0, 3400.0])
    from missile_sim.config import cxk_for_bc
    cxk = np.asarray(cxk_for_bc(bcs, c), dtype=float)
    batch = simulate_batch(c, np.repeat(dvs, 3), np.tile(cxk, 3))
    for i, (dv, cx) in enumerate(zip(np.repeat(dvs, 3), np.tile(cxk, 3))):
        one = simulate_one(c, Case(dv_total=float(dv), cxk=float(cx)), record_trace=False)
        assert int(batch.status[i]) == one.status, (dv, float(cx))
        assert float(batch.min_range_linear[i]) == pytest.approx(one.min_range_linear, abs=1e-6)


# --------------------------------------------------------------------- 收敛性

@pytest.mark.parametrize("dt", [0.01, 0.005, 0.0025])
def test_finite_burn_dt_convergence(cfg, dt):
    """有限燃烧下命中时间对步长仍应收敛（级间切换被 RK4 取时抹平）。"""
    cfg.sim.dt = dt
    t_hit = simulate_one(cfg, Case(dv_total=delta_v_equiv(cfg), cxk=cfg.drag.cxk),
                         record_trace=False).t_hit
    assert abs(t_hit - 45.25) < 0.15


def test_stage_boundary_smearing_is_small():
    """级间切换不切步，误差应远小于 1%（CI 上界 0.5%）。"""
    dv = 900.0
    for std in ("PL-12", "120C"):
        tr = _run(_vacuum(std), dv).trace
        assert abs(float(tr.v.max()) - (VM0 + dv)) / dv < 5e-3


# --------------------------------------------------------------------- 纯函数层

def test_burn_scaling_helpers():
    b = burn.from_standard(load_config().profile)
    assert b.scale_for_dv(b.dv_blk) == pytest.approx(1.0)
    assert burn.mass_ratio_at(0.0, b) == pytest.approx(198.0 / 132.0)
    assert burn.mass_ratio_at(100.0, b) == pytest.approx(1.0)


def test_instant_profile_leaves_mass_ratio_at_one():
    b = burn.instant_profile(dv_blk=932.6)
    assert burn.mass_ratio_at(0.0, b) == 1.0
    assert burn.mass_ratio_at(3.0, b) == 1.0

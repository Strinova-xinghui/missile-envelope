"""大气模型测试：与 AGENTS.md 记录的 War Thunder 公式/常量对照。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from missile_sim import atmosphere  # noqa: E402


def test_poly_horner():
    assert abs(atmosphere.poly([1.0, 2.0, 3.0], 2.0) - 17.0) < 1e-12


def test_sea_level_density_is_standard():
    assert abs(float(atmosphere.density(0.0)) - 1.225) < 1e-9


def test_density_monotonic_decreasing():
    h = np.linspace(0.0, 30000.0, 200)
    d = atmosphere.density(h)
    assert np.all(np.diff(d) <= 1e-12)


def test_density_polynomial_values():
    # 与多项式手算一致（1000 m）
    expect = 1.225 * atmosphere.poly(atmosphere.DENSITY_COEFFS, 1000.0)
    assert abs(float(atmosphere.density(1000.0)) - expect) < 1e-12
    # 10 km 量级检查（标准大气约 0.41 kg/m^3）
    assert 0.40 < float(atmosphere.density(10000.0)) < 0.42


def test_above_h_max_decays_as_inverse_height():
    h_max = atmosphere.H_MAX
    d_at_max = float(atmosphere.density(h_max))
    for factor in (2.0, 5.0, 100.0):
        h = h_max * factor
        expect = d_at_max / factor
        assert abs(float(atmosphere.density(h)) - expect) < 1e-12 * max(1.0, expect)


def test_density_never_negative():
    h = np.array([-100.0, 0.0, 18300.0, 60000.0, 200000.0])
    assert np.all(atmosphere.density(h) >= 0.0)


def test_calibrated_rho0_default_and_rescale():
    assert abs(atmosphere.calibrated_rho0() - 1.225) < 1e-12
    # 气压降低 10% 时密度等比下降
    assert abs(atmosphere.calibrated_rho0(101300.0 * 0.9, 288.16) - 1.225 * 0.9) < 1e-12


def test_speed_of_sound_reasonable():
    a0 = float(atmosphere.speed_of_sound(0.0))
    assert 330.0 < a0 < 345.0
    assert abs(float(atmosphere.mach_from_speed(a0, 0.0)) - 1.0) < 1e-9
    # 高空声速低于海平面
    assert float(atmosphere.speed_of_sound(11000.0)) < a0


def test_temperature_and_sonic_match_game_source():
    """照 atmosphere.cpp/.h 逐值对拍（T0*poly(TEMPERATURE_COEFFS)、20.1*sqrt(T)）。

    另对拍 `升力与诱导阻力_实现规格.md` §4.2 的参考工况：h=5000 m → T=255.58 K、a=321.3 m/s。
    """
    assert abs(float(atmosphere.air_temperature(0.0)) - 288.16) < 1e-9
    ref = {0.0: 341.20, 5000.0: 321.34, 10000.0: 300.71, 15000.0: 288.69}
    for h, a_ref in ref.items():
        assert abs(float(atmosphere.speed_of_sound(h)) - a_ref) < 0.01, h
    # 信源给的参考值（注意不是 ISA：15 km 处 ISA 会高 2.2%）
    assert abs(float(atmosphere.air_temperature(5000.0)) - 255.58) < 0.01
    assert abs(float(atmosphere.speed_of_sound(5000.0)) - 321.3) < 0.05
    # 温度剖面在 15 km 附近触底后回升，且 hMax 之上冻结
    assert float(atmosphere.air_temperature(15000.0)) < float(atmosphere.air_temperature(18000.0))
    assert abs(float(atmosphere.air_temperature(18300.0)) - float(atmosphere.air_temperature(30000.0))) < 1e-9

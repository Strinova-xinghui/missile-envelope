"""War Thunder 大气密度模型（见 AGENTS.md「Atmospheric Density」）。

来源：E:\\WT\\DagorEngine\\prog\\gameLibs\\gamePhys\\props\\atmosphere.cpp
      E:\\WT\\DagorEngine\\prog\\gameLibs\\publicInclude\\gamePhys\\props\\atmosphere.h

rho(h) = rho0 * poly(c, min(h, hMax)) * (hMax / max(hMax, h))
rho0   = 1.225 * (P0 / 101300) * (288.16 / T0)      # 海平面重标定

单位统一为 SI（kg/m^3）。源码注释写作 kg*sec2/m4，但常量与 API 实际为 kg/m^3，
此处按 kg/m^3 使用，并在 README 记录该差异。
"""

from __future__ import annotations

import numpy as np

# DENSITY_COEFFS from atmosphere.cpp
DENSITY_COEFFS = (1.0, -9.59387e-5, 3.53118e-9, -5.83556e-14, 2.28719e-19)

H_MAX = 18300.0
RHO0_STD = 1.225
P0_STD = 101300.0
T0_STD = 288.16


def poly(coeffs, x):
    """多项式求值（Horner）。coeffs[i] 对应 x**i。"""
    out = 0.0
    for c in reversed(tuple(coeffs)):
        out = out * x + c
    return out


def calibrated_rho0(P0: float = P0_STD, T0: float = T0_STD) -> float:
    """海平面密度重标定，等价于 atmosphere.cpp 的 setSeaLevelDensityFor(P0, T0)。"""
    return RHO0_STD * (P0 / P0_STD) * (T0_STD / T0)


def density(h, rho0: float = RHO0_STD, h_max: float = H_MAX):
    """标准大气密度 [kg/m^3]，支持标量或 ndarray。"""
    h = np.asarray(h, dtype=float)
    hc = np.minimum(h, h_max)
    d = rho0 * poly(DENSITY_COEFFS, hc)
    d = d * (h_max / np.maximum(h_max, h))
    return np.maximum(d, 0.0)


def air_temperature(h, T0: float = T0_STD):
    """ISA 温度 [K]，仅用于把速度换算成马赫数做输出标注，不参与动力学。"""
    h = np.asarray(h, dtype=float)
    lapse = np.where(h <= 11000.0, T0 - 0.0065 * h, 216.65 + 0.0 * h)
    return np.maximum(lapse, 1.0)


def speed_of_sound(h, T0: float = T0_STD):
    """声速 [m/s]，仅诊断用。"""
    gamma_air, R_air = 1.4, 287.05287
    return np.sqrt(gamma_air * R_air * air_temperature(h, T0))


def mach_from_speed(v, h, T0: float = T0_STD):
    """马赫数（诊断输出用）。"""
    return np.asarray(v, dtype=float) / speed_of_sound(h, T0)

"""War Thunder 大气模型（密度 + 温度 + 声速），全部照抄 atmosphere.cpp/.h。

来源：E:\\WT\\DagorEngine\\prog\\gameLibs\\gamePhys\\props\\atmosphere.cpp
      E:\\WT\\DagorEngine\\prog\\gameLibs\\publicInclude\\gamePhys\\props\\atmosphere.h

  rho(h) = rho0 * poly(DENSITY_COEFFS,     min(h, hMax)) * (hMax / max(hMax, h))
  T(h)   = T0   * poly(TEMPERATURE_COEFFS, min(h, hMax))
  a(h)   = 20.1 * sqrt(T(h))                       # 源码写法，20.1 = sqrt(gamma*R) 的取整
  rho0   = 1.225 * (P0 / 101300) * (288.16 / T0)   # 海平面重标定

**注意 T(h) 不是 ISA 温降**：game 用 5 次多项式，最低点在 ~15 km（206 K）后回升，
到 hMax=18300 m 为 214.6 K，之上冻结。用 ISA 线性温降算声速在 15 km 处会差 **−2.2%**
（ISA 295.07 vs 游戏 288.69 m/s），进而影响马赫数与 `f(M)`。

单位统一为 SI（kg/m^3）。源码注释写作 kg*sec2/m4，但常量与 API 实际为 kg/m^3，
此处按 kg/m^3 使用，并在 README 记录该差异。
"""

from __future__ import annotations

import numpy as np

# atmosphere.h
DENSITY_COEFFS = (1.0, -9.59387e-5, 3.53118e-9, -5.83556e-14, 2.28719e-19)
TEMPERATURE_COEFFS = (1.0, -2.27712e-5, 2.18069e-10, -5.71104e-14, 3.97306e-18)
SONIC_SPEED_COEFF = 20.1          # atmosphere.cpp: sonicSpeed() = 20.1f * sqrtf(T)

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
    """游戏温度剖面 [K]：`T0 * poly(TEMPERATURE_COEFFS, min(h, hMax))`（非 ISA）。

    仅用于把速度换算成马赫数（`f(M)`、诊断输出），不参与动力学。
    """
    h = np.asarray(h, dtype=float)
    hc = np.minimum(h, H_MAX)
    return np.maximum(T0 * poly(TEMPERATURE_COEFFS, hc), 1.0)


def speed_of_sound(h, T0: float = T0_STD):
    """游戏声速 [m/s]：`20.1 * sqrt(T(h))`（atmosphere.cpp `sonicSpeed()`）。

    参考值：a(0) = 341.2、a(5000) = 321.34、a(10000) = 300.71、a(15000) = 288.69。
    """
    return SONIC_SPEED_COEFF * np.sqrt(air_temperature(h, T0))


def mach_from_speed(v, h, T0: float = T0_STD):
    """马赫数（诊断输出用）。"""
    return np.asarray(v, dtype=float) / speed_of_sound(h, T0)

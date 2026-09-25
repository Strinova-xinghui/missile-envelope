"""气动模型：基础阻力马赫修正 f(M)、升力配平、诱导阻力（迎角附加阻力）。

**公式唯一来源**：`wt-missile-backend-runtime-research-1.0.1`（信源交付的文件包，
Unicorn 执行游戏原生机器码所得），见 `docs/FORMULAS-PLAIN.md` §9/§10/§11。
推导、证据与冲突裁决见仓库根目录 `AERO_PLAN.md`。

三档模型（`model`）：

    legacy : D = q·SD·CxK·drag_base                          本仓库旧口径，逐位复现
    mach   : D = q·SD·CxK·drag_base·f(M)                     只补马赫修正（诊断档）
    full   : D = q·SD·CxK·drag_base·f(M) + Da                默认
             Da = F(M)·q·(SD·CxK·drag_base·CxAoA_eff/m)·sin²α

    SD = π·caliber²/4                        正面面积（= config.s_ref）
    SL = 0.3·caliber·length·wingAreaMult     升力参考面积
    sinα = min( m·|a_perp| / (q·SL·CyK),  CyMaxAoA/CyK )   （升力上升支路，准定常配平）
    CxAoA_eff = CxAoA × (applyWingAreaMultToCxAoA ? wingAreaMult² : 1)

**注意**：`f(M)` 在 M=1.0 处有 +50.8% 跳变（段2 极限 0.365 与段3 起点 0.551），
这是原函数的固有性质，**不得平滑**。`use_cxi_mach=False` 只把 `F(M)` 置 1，
基础项仍然乘 `f(M)`。

标量路径用 `*_s` 后缀的纯 `math` 实现，数组路径用 numpy 实现（与 `ballistics.gain_schedule`
的双实现惯例一致）；两者必须给出相同结果，`tests/test_aero.py` 有对拍。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import atmosphere

MODEL_LEGACY, MODEL_MACH, MODEL_FULL = 0, 1, 2
MODEL_NAMES = {MODEL_LEGACY: "legacy", MODEL_MACH: "mach", MODEL_FULL: "full"}
MODEL_CHOICES = ("legacy", "mach", "full")
MODEL_LABELS = {
    MODEL_LEGACY: "legacy（仅零升阻力，恒定系数）",
    MODEL_MACH: "mach（+f(M) 基础阻力）",
    MODEL_FULL: "full（f(M) + 升力配平 + 诱导阻力）",
}

# 海平面声速：h<=0 时使用（游戏温度多项式在 h=0 取 T0）
_SEA_LEVEL_SOS = float(atmosphere.speed_of_sound(0.0))
_Q_FLOOR = 1e-12


def model_from_str(name: str) -> int:
    """把配置里的字符串档位转成常量；非法值抛 ValueError。"""
    try:
        return MODEL_CHOICES.index(str(name).strip().lower())
    except ValueError as exc:
        raise ValueError(f"气动模型必须是 {MODEL_CHOICES} 之一，收到 {name!r}") from exc


def model_name(model: int) -> str:
    return MODEL_NAMES.get(int(model), f"?{model}")


# --------------------------------------------------------------------- 马赫函数（文档 §9/§10）

def f_mach_s(M: float) -> float:
    """基础阻力马赫修正 f(M)，五段式（标量）。"""
    if M < 0.61:
        return 0.308
    if M < 1.0:
        return 0.308 + 0.505 * (M - 0.61) ** 2.31
    if M < 1.4:
        d = M - 1.0
        return 0.551 + 0.4485 * (d ** 0.505) * math.exp(-5.68 * d)
    if M < 4.0:
        return M / ((0.356 * M + 2.237) * M - 1.4)
    return 0.302


def F_mach_s(M: float) -> float:
    """迎角附加阻力的马赫系数 F(M) = 3.247·[0.308 + 0.75·(f(M) − 0.308)]（标量）。"""
    return 3.247 * (0.308 + 0.75 * (f_mach_s(M) - 0.308))


def f_mach(M):
    """基础阻力马赫修正 f(M)，五段式（数组）。"""
    m = np.asarray(M, dtype=float)
    seg2 = np.clip(m, 0.61, 1.0)                      # 夹住底数，避免负数的分数次幂
    f2 = 0.308 + 0.505 * np.power(seg2 - 0.61, 2.31)
    d = np.clip(m, 1.0, 1.4) - 1.0
    f3 = 0.551 + 0.4485 * np.power(d, 0.505) * np.exp(-5.68 * d)
    seg4 = np.clip(m, 1.4, 4.0)
    f4 = seg4 / ((0.356 * seg4 + 2.237) * seg4 - 1.4)
    return np.select([m < 0.61, m < 1.0, m < 1.4, m < 4.0],
                     [0.308, f2, f3, f4], default=0.302).astype(float)


def F_mach(M):
    """F(M)（数组）。"""
    return 3.247 * (0.308 + 0.75 * (f_mach(M) - 0.308))


def mach_s(v: float, h: float) -> float:
    """马赫数（标量）。h<=0 用海平面声速。"""
    sos = float(atmosphere.speed_of_sound(h)) if h > 0.0 else _SEA_LEVEL_SOS
    return v / sos


def mach(v, h):
    """马赫数（数组）。"""
    hh = np.maximum(np.asarray(h, dtype=float), 0.0)
    return np.asarray(v, dtype=float) / atmosphere.speed_of_sound(hh)


# --------------------------------------------------------------------- 每配置 / 每工况参数

@dataclass(frozen=True)
class AeroParams:
    """只依赖配置的气动常量（每工况共用）。"""

    model: int
    use_cxi_mach: bool
    clip_lift_peak: bool
    s_lift: float          # SL = 0.3·caliber·length·wingAreaMult
    cyk: float             # 升力系数斜率（全库默认 2.2）
    cy_max_aoa: float      # 升力系数峰值（全库默认 1.0）
    sin_alpha_peak: float  # min(1, CyMaxAoA/CyK)，升力上升支路的迎角上限
    cx_aoa_eff: float      # CxAoA × (applyWingAreaMultToCxAoA ? wingAreaMult² : 1)


@dataclass(frozen=True)
class AeroCase:
    """依赖每工况（CxK、质量）的系数。"""

    gamma_energy: float    # m·SD·CxK·drag_base·CxAoA_eff/(SL²·CyK²)
    a_peak_per_q: float    # SL·CyMaxAoA/m  → 可达升力峰值加速度 a_peak = q·a_peak_per_q
    k_alpha: float         # m/(SL·CyK)     → sinα = k_alpha·|a_perp|/q


@dataclass(frozen=True)
class AeroCaseArrays:
    """`AeroCase` 的批量版本（字段名必须与 `AeroCase` 一致）。"""

    gamma_energy: np.ndarray
    a_peak_per_q: np.ndarray
    k_alpha: np.ndarray


def params_from_config(cfg) -> AeroParams:
    """从配置构造 `AeroParams`（鸭子类型取字段，避免 config↔aero 循环导入）。"""
    a = cfg.aero
    model = model_from_str(a.model) if isinstance(a.model, str) else int(a.model)
    cyk = float(a.cyk)
    cy_max = float(a.cy_max_aoa)
    wm = float(a.wing_area_mult)
    cx_aoa_eff = float(a.cx_aoa) * (wm * wm if a.apply_wing_area_mult_to_cx_aoa else 1.0)
    return AeroParams(
        model=model,
        use_cxi_mach=bool(a.use_cxi_mach),
        clip_lift_peak=bool(a.clip_lift_peak),
        s_lift=s_lift_area(cfg),
        cyk=cyk,
        cy_max_aoa=cy_max,
        sin_alpha_peak=min(1.0, cy_max / cyk) if cyk > 0.0 else 1.0,
        cx_aoa_eff=cx_aoa_eff,
    )


def s_lift_area(cfg) -> float:
    """升力参考面积 SL = 0.3 · caliber · length · wingAreaMult [m²]。"""
    return 0.3 * float(cfg.drag.caliber_m) * float(cfg.aero.length_m) * float(cfg.aero.wing_area_mult)


def case_params(cfg, cxk: float, mass: float) -> AeroCase:
    """每工况系数（标量）。`cxk` 已含 drag_base 缩放。"""
    sd = math.pi * (float(cfg.drag.caliber_m) / 2.0) ** 2
    sl = s_lift_area(cfg)
    cyk = float(cfg.aero.cyk)
    cx_aoa_eff = float(cfg.aero.cx_aoa) * (
        float(cfg.aero.wing_area_mult) ** 2 if cfg.aero.apply_wing_area_mult_to_cx_aoa else 1.0)
    gamma_energy = mass * sd * cxk * cx_aoa_eff / (sl * sl * cyk * cyk)
    a_peak_per_q = sl * float(cfg.aero.cy_max_aoa) / mass
    return AeroCase(gamma_energy=gamma_energy, a_peak_per_q=a_peak_per_q,
                    k_alpha=mass / (sl * cyk))


def case_params_array(cfg, cxk, mass) -> AeroCaseArrays:
    """每工况系数（数组，与 `case_params` 同式）。"""
    sd = math.pi * (float(cfg.drag.caliber_m) / 2.0) ** 2
    sl = s_lift_area(cfg)
    cyk = float(cfg.aero.cyk)
    cx_aoa_eff = float(cfg.aero.cx_aoa) * (
        float(cfg.aero.wing_area_mult) ** 2 if cfg.aero.apply_wing_area_mult_to_cx_aoa else 1.0)
    kk = np.asarray(cxk, dtype=float)
    mm = np.asarray(mass, dtype=float)
    return AeroCaseArrays(
        gamma_energy=mm * sd * kk * cx_aoa_eff / (sl * sl * cyk * cyk),
        a_peak_per_q=sl * float(cfg.aero.cy_max_aoa) / mm,
        k_alpha=mm / (sl * cyk),
    )


# --------------------------------------------------------------------- 诱导阻力
#
# `mu` = m(t)/m_ref（本步质量 / 参考干重）。有限燃烧时质量随时间变，而三个每工况系数
# 都只是质量的幂次：gamma_energy ∝ m、k_alpha ∝ m、a_peak_per_q ∝ 1/m，
# 所以以干重为参考建 `AeroCase`，调用处乘一次 mu 即可，无需每步重建。

def induced_decel_s(a: AeroParams, ac: AeroCase, q: float, a_perp: float, F: float,
                    mu: float = 1.0) -> float:
    """诱导阻力减速度 [m/s²]，标量。

    Da/m = gammaEnergy · F(M) · a_eff² / q，其中 a_eff 截到升力峰值 q·SL·CyMaxAoA/m。
    与文档 §10 的 `q·SD·CxK·CxAoA·F·sin²α/m` 在 sinα 由配平反解时代数等价。
    """
    if a.model < MODEL_FULL or q <= 0.0:
        return 0.0
    cap = q * ac.a_peak_per_q / mu
    a_eff = abs(a_perp)
    if a_eff > cap:
        a_eff = cap
    return ac.gamma_energy * mu * F * a_eff * a_eff / q


def induced_decel(a: AeroParams, ac: AeroCaseArrays, q, a_perp, F, mu=1.0):
    """诱导阻力减速度 [m/s²]，数组（与 `induced_decel_s` 同式）。"""
    if a.model < MODEL_FULL:
        return np.zeros_like(np.asarray(q, dtype=float))
    qs = np.maximum(q, _Q_FLOOR)
    a_eff = np.minimum(np.abs(a_perp), qs * ac.a_peak_per_q / mu)
    return ac.gamma_energy * mu * F * a_eff * a_eff / qs


def alpha_deg_s(a: AeroParams, ac: AeroCase, q: float, a_perp: float, mu: float = 1.0) -> float:
    """记录用迎角 [度]（标量）：sinα = k_alpha·|a_perp|/q = m·|a_perp|/(q·SL·CyK)，截到峰值。"""
    if a.model < MODEL_FULL or q <= 0.0:
        return 0.0
    a_eff = min(abs(a_perp), q * ac.a_peak_per_q / mu)
    sin_a = min(ac.k_alpha * mu * a_eff / q, a.sin_alpha_peak)
    return math.degrees(math.asin(sin_a))


def alpha_deg(a: AeroParams, ac: AeroCaseArrays, q, a_perp, mu=1.0):
    """记录用迎角 [度]（数组，与 `alpha_deg_s` 同式）。"""
    qs = np.maximum(np.asarray(q, dtype=float), _Q_FLOOR)
    a_eff = np.minimum(np.abs(a_perp), qs * ac.a_peak_per_q / mu)
    sin_a = np.minimum(ac.k_alpha * mu * a_eff / qs, a.sin_alpha_peak)
    return np.degrees(np.arcsin(np.clip(sin_a, 0.0, 1.0)))

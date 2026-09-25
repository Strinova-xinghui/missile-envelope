"""配置、单位约定与派生量。

关键约定（用户确认，见 README「模型约定」）：
  * 总增速 ΔV 在 T=0+ 瞬时完成；ΔV 只改变等效比冲，不改变质量（反现实但为设计选择）。
    因此扫 ΔV 时 m0 = m_end = 干重锚定值，Isp_equiv = ΔV / (g0 * ln(m0/m_end))；
    基准值 ve_equiv = 2266 m/s (Isp≈231 s) 仅用于把 ΔV 换成"标称质量比"做对照输出。
  * 弹道系数 BC 作为扫描变量，反解 CxK：BC = m_end / (k * S_ref)
    → k = m_end / (BC * S_ref)，与 AGENTS.md 的 BC 公式一致。

参考面积：S_ref = pi * (d/2000)^2，d 为口径 [mm]（blkx 里 caliber 是米，caliber_m=0.1778）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from math import log, pi
from pathlib import Path

import numpy as np

G0 = 9.80665

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "baseline_aim120c5.json"


class ConfigError(ValueError):
    """配置非法（例如高抛角超出 [0, 40) ）。"""


@dataclass
class AtmosphereConfig:
    rho0: float = 1.225
    P0: float = 101300.0
    T0: float = 288.16
    h_max: float = 18300.0
    g: float = 9.81


@dataclass
class DragConfig:
    cxk: float = 1.225
    drag_base: float = 1.0
    caliber_m: float = 0.1778


@dataclass
class MassConfig:
    mass_launch: float = 161.4789
    mass_end: float = 110.223
    # BC↔CxK 反解与仿真使用的质量锚定项：
    #   'm_end'   —— 用干重（默认；BC = m_end/(CxK·S_ref)，与简化的"末段存速"口径一致）
    #   'm_launch'—— 用发射质量（BC = m0/(CxK·S_ref)，数值更大）
    # 每个工况可用 Case.mass 覆盖（用于把各型弹按各自真实质量送进同一条弹道）
    mass_anchor: str = "m_end"


@dataclass
class ImpulseConfig:
    ve_equiv: float = 2266.0


@dataclass
class SimConfig:
    dt: float = 0.005
    t_life: float = 120.0
    # 命中半径取 blkx proximityFuse.radius = 12.0 m（AIM-120C5 近炸引信作用半径）
    hit_radius: float = 12.0
    boost_delay: float = 0.3
    theta_loft_deg: float = 22.0
    k_loft: float = 1.5
    loft_min_time: float = 2.0
    loft_exit_margin_deg: float = 60.0
    loft_dh_gain_max: float = 4000.0
    loft_time_max: float = 20.0
    loft_confirm_steps: int = 2
    v_min: float = 150.0
    overshoot_range: float = 5.0
    max_heading_error_deg: float = 70.0
    tau_tgo: float = 0.5
    tgo_closing_floor: float = 100.0
    min_closing: float = 1.0
    n_base: float = 6.0
    a_lat_max_g: float = 35.0


@dataclass
class ScenarioConfig:
    vm0: float = 300.0
    vt: float = -300.0
    alt: float = 10000.0
    range: float = 50000.0
    # 目标高度 [m]；为 None 时等于 alt（双方同高）。用于研究高度差对弹道/命中时间的影响。
    target_alt: float | None = None


@dataclass
class SweepConfig:
    dv_min: float = 800.0
    dv_max: float = 1500.0
    dv_step: float = 50.0
    bc_min: float = 1700.0
    bc_max: float = 4000.0
    bc_step: float = 100.0


@dataclass
class MissileConfig:
    atmosphere: AtmosphereConfig = field(default_factory=AtmosphereConfig)
    drag: DragConfig = field(default_factory=DragConfig)
    mass: MassConfig = field(default_factory=MassConfig)
    impulse: ImpulseConfig = field(default_factory=ImpulseConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    scenario: ScenarioConfig = field(default_factory=ScenarioConfig)
    sweep: SweepConfig = field(default_factory=SweepConfig)


# ----------------------------------------------------------------------------- 载入/写出


def _build(cls, data: dict):
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        if is_dataclass(f.type) or (isinstance(val, dict) and hasattr(f.type, "__dataclass_fields__")):
            kwargs[f.name] = _build(f.type, val)
        else:
            kwargs[f.name] = val
    return cls(**kwargs)


def config_from_dict(data: dict) -> MissileConfig:
    cfg = MissileConfig()
    for key in ("atmosphere", "drag", "mass", "impulse", "sim", "scenario", "sweep"):
        if key in data:
            setattr(cfg, key, _build(type(getattr(cfg, key)), data[key]))
    validate(cfg)
    return cfg


def load_config(path=None) -> MissileConfig:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return config_from_dict(data)


def config_to_dict(cfg: MissileConfig) -> dict:
    out = {}
    for key in ("atmosphere", "drag", "mass", "impulse", "sim", "scenario", "sweep"):
        sub = getattr(cfg, key)
        out[key] = {f.name: getattr(sub, f.name) for f in fields(sub)}
    return out


def validate(cfg: MissileConfig) -> None:
    s = cfg.sim
    if not (0.0 <= s.theta_loft_deg < 40.0):
        raise ConfigError(
            f"高抛角必须在 [0, 40) 度范围内，收到 {s.theta_loft_deg} 度"
        )
    if s.dt <= 0.0:
        raise ConfigError("dt 必须为正")
    if s.boost_delay < 0.0:
        raise ConfigError("boost_delay 不能为负")
    if cfg.mass.mass_end <= 0 or cfg.mass.mass_launch < cfg.mass.mass_end:
        raise ConfigError("质量参数非法：需 0 < mass_end <= mass_launch")
    if cfg.drag.cxk <= 0.0 or cfg.drag.drag_base <= 0.0:
        raise ConfigError("CxK / drag_base 必须为正")
    if cfg.drag.caliber_m <= 0.0:
        raise ConfigError("口径必须为正")


# ----------------------------------------------------------------------------- 派生量


def s_ref(cfg: MissileConfig) -> float:
    """气动参考面积 [m^2]：S_ref = pi * (d/2)^2。"""
    d = cfg.drag.caliber_m
    return pi * (d / 2.0) ** 2


def m_bound(cfg: MissileConfig) -> float:
    """用于 BC 反解的质量锚定值 [kg]。"""
    return cfg.mass.mass_end if cfg.mass.mass_anchor == "m_end" else cfg.mass.mass_launch


def ballistic_coefficient(cxk: float, cfg: MissileConfig) -> float:
    """BC = m_bound / (CxK * S_ref)，与 AGENTS.md 的公式等价。"""
    return m_bound(cfg) / (cxk * s_ref(cfg))


def cxk_for_bc(bc, cfg: MissileConfig):
    """反解 CxK = m_bound / (BC * S_ref)。支持标量与 ndarray。"""
    arr = np.asarray(bc, dtype=float)
    if np.any(arr <= 0.0):
        raise ConfigError("弹道系数必须为正")
    out = m_bound(cfg) / (arr * s_ref(cfg))
    return float(out) if out.ndim == 0 else out


def delta_v_equiv(cfg: MissileConfig) -> float:
    """基准构型按火箭方程的等效总增速 [m/s]（AIM-120C5 ≈ 1114）。"""
    m0, m1 = cfg.mass.mass_launch, cfg.mass.mass_end
    if m0 <= m1:
        return 0.0
    return cfg.impulse.ve_equiv * log(m0 / m1)


def isp_equiv(dv_total: float) -> float:
    """质量固定时，"ΔV = Isp*g0" 意义上的等效比冲 [s]（仅作对照输出）。"""
    return dv_total / G0


def mass_ratio_for_dv(dv_total: float, ve_equiv: float) -> float:
    """若真按火箭方程提供该 ΔV 所需的质量比 m0/m_end（对照输出，不参与动力学）。"""
    return float(np.exp(dv_total / ve_equiv))


def a_drag_coeff(cfg: MissileConfig, cxk: float | None = None, drag_base: float | None = None,
                 mass: float | None = None) -> float:
    """阻力加速度系数 a = -(coeff * rho * V^2)，coeff = 0.5*k*S_ref*drag_base/m。

    mass 用于按工况指定弹体质量（None 取配置的 mass_end）。
    """
    k = cfg.drag.cxk if cxk is None else cxk
    db = cfg.drag.drag_base if drag_base is None else drag_base
    m = cfg.mass.mass_end if mass is None else mass
    return 0.5 * k * db * s_ref(cfg) / m


def summary_lines(cfg: MissileConfig) -> list:
    """参数对照表（命令行打印用）。"""
    bc0 = ballistic_coefficient(cfg.drag.cxk, cfg)
    dv0 = delta_v_equiv(cfg)
    return [
        f"口径 d              = {cfg.drag.caliber_m * 1000:.1f} mm",
        f"参考面积 S_ref       = {s_ref(cfg):.6f} m^2",
        f"干重锚定 m_bound     = {m_bound(cfg):.4f} kg (anchor={cfg.mass.mass_anchor})",
        f"基准 CxK             = {cfg.drag.cxk:.6f}",
        f"基准 BC              = {bc0:.1f}",
        f"基准 ΔV (火箭方程)   = {dv0:.1f} m/s  (ve_equiv={cfg.impulse.ve_equiv:.1f} m/s, Isp≈{dv0 / G0:.1f} s)",
        f"阻力系数 0.5*k*S/m   = {a_drag_coeff(cfg):.8e} 1/m",
        f"侧向过载上限         = {cfg.sim.a_lat_max_g:.1f} g",
        f"高抛角               = {cfg.sim.theta_loft_deg:.1f} deg",
    ]

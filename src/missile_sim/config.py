"""配置、单位约定与派生量。

关键约定（用户确认，见 README「模型约定」）：
  * **标准弹**：等时线在 (ΔV, BC) 平面上扫描，但"ΔV 换成多少推力、质量怎么掉、
    几何/引信/高抛取值多少"都由**某一型真实弹**给定（默认 PL-12，可在 11 弹池里选）。
    池见 `results/missile_standards.json`，解析见 `standard.py`。
  * **ΔV 的定义（两种燃烧档都成立）**：`ΔV` 只改变等效比冲、不改变质量与燃烧时间。
      - `burn=finite`（默认）：各段推力同乘 `s = ΔV/ΔV_blk`，故 ΔV 严格 ∝ s；
        质量按标准弹剖面前后变化，取值为**真空等效总增速**，实际速度增量还需扣除阻力。
      - `burn=instant`（旧口径）：ΔV 在 T=0+ 瞬时给出，质量恒为干重 ⇒ 可逐位复现升级前的数字。
  * 弹道系数 BC 作为扫描变量，反解 CxK：BC = m_dry / (k * S_ref)
    → k = m_dry / (BC * S_ref)，与 AGENTS.md 的 BC 公式一致。

参考面积：S_ref = pi * (d/2000)^2，d 为口径 [mm]（blkx 里 caliber 是米，caliber_m=0.1778）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from math import asin, degrees, log, pi
from pathlib import Path

import numpy as np

from . import burn as burn_mod
from . import standard as standard_mod

G0 = 9.80665

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "configs" / "baseline.json"

# 会随标准弹走的扁平字段（用于文档与 `summary_lines` 标注来源）
STANDARD_MANAGED = (
    "drag.caliber_m", "drag.cxk",
    "aero.length_m", "aero.wing_area_mult", "aero.cy_max_aoa", "aero.cyk", "aero.cx_aoa",
    "mass.mass_launch", "mass.mass_end",
    "sim.a_lat_max_g", "sim.n_base", "sim.theta_loft_deg", "sim.hit_radius", "sim.t_life",
)


class ConfigError(ValueError):
    """配置非法（例如高抛角超出 [0, 40) ）。"""


@dataclass
class StandardConfig:
    """标准弹选型（11 弹池自选；默认 PL-12）。

    name 为空 ⇒ 不解析池，直接用配置里各段的字面值（等价于旧口径的"无标准弹"模式，
    配合 burn=instant + ve_equiv_override 可逐位复现升级前的产物）。
    """

    name: str = "PL-12"
    burn: str = "finite"          # finite（默认，N 段有限燃烧）| instant（旧口径）
    tag: str = "WORK"             # 池的数据源版本；空串表示不校验
    pool: str = "results/missile_standards.json"



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
class AeroConfig:
    """气动模型档位与升力参数（公式来源见 aero.py 与 AERO_PLAN.md）。

    model:
      legacy —— D = q·SD·CxK·drag_base（本仓库旧口径，可逐位复现）
      mach   —— 再加 f(M) 基础阻力（诊断档，近距会有能量过剩伪影）
      full   —— 再加升力配平与诱导阻力（默认）
    """

    model: str = "full"
    use_cxi_mach: bool = True              # 游戏 useCxiMach：false 时 F(M)=1，但基础项仍乘 f(M)
    clip_lift_peak: bool = False           # true 时在气动层把可达 a_perp 截到升力峰值（会改弹道）
    cyk: float = 2.2                       # 升力系数斜率；11 型主动弹 blkx 均无该键，用全局默认
    # 升力系数峰值；逐弹从池读（MICA 1.35、R-77/R-77-1 1.3，其余 7 型 blk 无该键 ⇒ 1.0）
    cy_max_aoa: float = 1.0
    cx_aoa: float = 9.0                    # gameparams.blkx shellBallisticsParams.props.CxAoA
    length_m: float = 3.66                 # 弹长（AIM-120C5）
    wing_area_mult: float = 1.7            # blkx wingAreaMult（AIM-120C5）
    apply_wing_area_mult_to_cx_aoa: bool = False   # 游戏开关当前为 false ⇒ CxAoA_eff = CxAoA


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
    # 旧口径的等效排气速度 [m/s]。**当 standard.name 非空时被标准弹覆盖**；
    # ve_equiv_override 用于刻意压回旧值（复现升级前的产物）。
    ve_equiv: float = 2266.0
    ve_equiv_override: float | None = None


@dataclass
class SimConfig:
    dt: float = 0.005
    t_life: float = 120.0
    # 命中半径取 blkx proximityFuse.radius = 12.0 m（AIM-120C5 近炸引信作用半径）
    hit_radius: float = 12.0
    boost_delay: float = 0.3
    theta_loft_deg: float = 20.0
    # 高抛退出规则：game = 游戏判据（|λ̇|≥omegaMax 或 λ≤targetElevation，逐弹从 blk 读）；
    #               heuristic = 本仓库旧启发式（下沉角/高度增量/时长/下压），仅用于复现旧产物
    loft_rule: str = "game"
    loft_target_elevation_deg: float = -2.25
    loft_target_omega_max_dps: float = 0.5
    k_loft: float = 1.5
    # 最短高抛时间：游戏本身没有这道闸门，这里只用于挡住"第一步就退出"的退化情形
    loft_min_time: float = 0.5
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
    aero: AeroConfig = field(default_factory=AeroConfig)
    mass: MassConfig = field(default_factory=MassConfig)
    impulse: ImpulseConfig = field(default_factory=ImpulseConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    scenario: ScenarioConfig = field(default_factory=ScenarioConfig)
    sweep: SweepConfig = field(default_factory=SweepConfig)
    standard: StandardConfig = field(default_factory=StandardConfig)
    # 后端（用户 2026-09-25 定案）：**pro = 原生仿真器（默认、唯一正式口径）**；
    # flash = 本仓库快模型（保留为可迭代的近似档，用于探索与无包环境）
    backend: str = "pro"
    # Pro 后端运行参数（不随标准弹走）
    pro_jobs: int = 8              # 子进程数（每个进程一个独立 Unicorn 实例）
    pro_dt: float = 0.01           # 原生外层步长 [s]，合法范围 [0.00025, 0.01]
    pro_duration_s: float = 150.0  # 单工况最长计算时间 [s]（最终还受 blk timeLife 限制）
    pro_observation: str = "ideal"  # ideal = 与快模型同假设；locked = 带原生滤波/多径
    pro_cache: str = "results/pro_cache.json"   # 原生结果缓存（空串 = 不缓存）
    # 运行时对象（由 apply_standard 填充；不参与序列化）
    profile: object | None = field(default=None, repr=False, compare=False)
    burn: object | None = field(default=None, repr=False, compare=False)


SECTIONS = ("atmosphere", "drag", "aero", "mass", "impulse", "sim", "scenario", "sweep", "standard")

# Pro 后端的**运行连接参数**：与物理无关、依机器而变，所以不写进 configs/*.json 的默认快照
# （`config_to_dict` 仍会写出，便于产物自描述；读回时也接受）。
PRO_FIELDS = ("pro_jobs", "pro_dt", "pro_duration_s", "pro_observation", "pro_cache")

# 后端：pro = 原生仿真器（默认、正式口径）；flash = 本仓库快模型（近似档）
BACKENDS = ("pro", "flash")
PRO_BACKEND_HINT = ("Pro 后端需要信源的原生运行包（包体不入库）：设置 WT_NATIVE_PKG 指向解压后的 "
                    "wt-missile-backend 目录，或放到默认位置 "
                    r"E:\WT\wt-missile-backend-runtime-1.0.1；"
                    "只想快速看个大概可用 --backend flash")


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
    if "backend" in data:
        b = data["backend"]
        cfg.backend = str(b.get("name", "pro") if isinstance(b, dict) else b).strip().lower()
    # Pro 运行参数：兼容顶层扁平写法和 `pro: {...}` 分组写法
    flat = {k: data[k] for k in PRO_FIELDS if k in data}
    if isinstance(data.get("pro"), dict):
        flat = {**{k: v for k, v in data["pro"].items() if k in PRO_FIELDS}, **flat}
    for k, v in flat.items():
        setattr(cfg, k, v)
    for key in SECTIONS:
        if key in data:
            setattr(cfg, key, _build(type(getattr(cfg, key)), data[key]))
    apply_standard(cfg)
    validate(cfg)
    return cfg


def load_config(path=None) -> MissileConfig:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return config_from_dict(data)


def config_to_dict(cfg: MissileConfig) -> dict:
    out = {"backend": cfg.backend, **{k: getattr(cfg, k) for k in PRO_FIELDS}}
    for key in SECTIONS:
        sub = getattr(cfg, key)
        out[key] = {f.name: getattr(sub, f.name) for f in fields(sub)}
    return out


def resolve_pool_path(cfg: MissileConfig) -> Path:
    p = Path(cfg.standard.pool)
    return p if p.is_absolute() else (ROOT / p)


def apply_standard(cfg: MissileConfig) -> MissileConfig:
    """按 `cfg.standard.name` 从池里解析标准弹，并写入既有的扁平字段。

    幂等：可重复调用（CLI 先改 `cfg.standard.name` 再调一次即可切换标准弹）。
    覆盖顺序是 **CLI/显式改动 > 标准弹 > 配置文件字面值**——因此本函数之后再施加 CLI 覆盖。
    `standard.name` 为空 ⇒ 不解析（`cfg.profile = None`，`cfg.burn` 退化为 instant）。
    """
    if not cfg.standard.name:
        cfg.profile = None
        cfg.burn = burn_mod.instant_profile()
        return cfg

    try:
        prof = standard_mod.resolve(
            cfg.standard.name, pool_path=resolve_pool_path(cfg),
            tag=(cfg.standard.tag or None),
        )
    except standard_mod.StandardPoolError as exc:
        raise ConfigError(str(exc)) from exc

    cfg.profile = prof
    cfg.drag.caliber_m = prof.caliber_m
    cfg.drag.cxk = prof.cxk
    cfg.aero.length_m = prof.length_m
    cfg.aero.wing_area_mult = prof.wing_area_mult
    cfg.aero.cy_max_aoa = prof.cy_max_aoa
    cfg.aero.cyk = prof.cyk
    cfg.aero.cx_aoa = prof.cx_aoa
    cfg.mass.mass_launch = prof.engine.mass_launch
    cfg.mass.mass_end = prof.engine.mass_dry
    cfg.mass.mass_anchor = "m_end"
    cfg.sim.a_lat_max_g = prof.req_accel_max_g
    cfg.sim.n_base = prof.prop_nav_mult
    if prof.loft.enabled and prof.loft.elevation_deg is not None:
        cfg.sim.theta_loft_deg = prof.loft.elevation_deg
    if prof.loft.target_elevation_deg is not None:
        cfg.sim.loft_target_elevation_deg = prof.loft.target_elevation_deg
    if prof.loft.target_omega_max_dps is not None:
        cfg.sim.loft_target_omega_max_dps = prof.loft.target_omega_max_dps
    cfg.sim.hit_radius = prof.fuse_radius_m
    cfg.sim.t_life = prof.time_life_s
    # 把等效排气速度也写回字面字段，避免遗留读者直接读 cfg.impulse.ve_equiv 时拿到陈旧值；
    # 真正的优先级由 effective_ve_equiv() 决定（override > 本值）。
    cfg.impulse.ve_equiv = prof.ve_equiv
    cfg.burn = burn_mod.from_standard(prof, cfg.standard.burn)
    return cfg


def validate(cfg: MissileConfig) -> None:
    s = cfg.sim
    st = cfg.standard
    if str(cfg.backend).strip().lower() not in BACKENDS:
        raise ConfigError(
            f"backend 必须是 {'/'.join(BACKENDS)} 之一，收到 {cfg.backend!r}"
            "（pro 后端尚未接入，见 AERO_PLAN §18）")
    if str(st.burn).strip().lower() not in burn_mod.BURN_MODELS:
        raise ConfigError(
            f"standard.burn 必须是 {'/'.join(burn_mod.BURN_MODELS)} 之一，收到 {st.burn!r}"
        )
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
    a = cfg.aero
    if str(a.model).strip().lower() not in ("legacy", "mach", "full"):
        raise ConfigError(f"aero.model 必须是 legacy/mach/full 之一，收到 {a.model!r}")
    if a.cyk <= 0.0:
        raise ConfigError("aero.cyk（升力系数斜率）必须为正")
    if a.cy_max_aoa <= 0.0:
        raise ConfigError("aero.cy_max_aoa（升力系数峰值）必须为正")
    if a.cx_aoa < 0.0:
        raise ConfigError("aero.cx_aoa 不能为负")
    if a.length_m <= 0.0:
        raise ConfigError("aero.length_m 必须为正")
    if a.wing_area_mult <= 0.0:
        raise ConfigError("aero.wing_area_mult 必须为正")
    if str(s.loft_rule).strip().lower() not in ("game", "heuristic"):
        raise ConfigError(f"sim.loft_rule 必须是 game/heuristic 之一，收到 {s.loft_rule!r}")
    if s.loft_rule == "game" and s.loft_target_omega_max_dps <= 0.0:
        raise ConfigError("sim.loft_target_omega_max_dps 必须为正")
    if s.t_life <= 0.0:
        raise ConfigError("t_life 必须为正")
    if s.hit_radius <= 0.0:
        raise ConfigError("hit_radius 必须为正")
    if cfg.impulse.ve_equiv_override is not None and cfg.impulse.ve_equiv_override <= 0.0:
        raise ConfigError("impulse.ve_equiv_override 必须为正（或留空）")
    # 燃烧剖面自洽性（有限燃烧档）
    b = cfg.burn
    if b is not None and b.model == burn_mod.MODEL_FINITE:
        if b.mass_launch < b.mass_mid or b.mass_mid < b.mass_dry or b.mass_dry <= 0.0:
            raise ConfigError(
                f"燃烧质量剖面非法：{b.mass_launch}/{b.mass_mid}/{b.mass_dry}"
            )
        if b.force <= 0.0 or b.time_fire <= 0.0:
            raise ConfigError("一级推力/燃烧时间必须为正")
        if b.two_stage and (b.force1 <= 0.0 or b.time_fire1 <= 0.0):
            raise ConfigError("两级弹的第二级推力/燃烧时间必须为正")


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


def effective_ve_equiv(cfg: MissileConfig) -> float:
    """当前生效的等效排气速度 [m/s]。

    优先级：显式覆盖 > 标准弹 > 配置文件字面值。
    """
    if cfg.impulse.ve_equiv_override is not None:
        return float(cfg.impulse.ve_equiv_override)
    if cfg.standard.name and cfg.profile is not None:
        return float(cfg.profile.ve_equiv)
    return float(cfg.impulse.ve_equiv)


def delta_v_equiv(cfg: MissileConfig) -> float:
    """标准构型按火箭方程的等效总增速 [m/s]（默认标准弹 PL-12 ≈ 932.6）。"""
    m0, m1 = cfg.mass.mass_launch, cfg.mass.mass_end
    if m0 <= m1:
        return 0.0
    return effective_ve_equiv(cfg) * log(m0 / m1)


def isp_equiv(dv_total: float) -> float:
    """质量固定时，"ΔV = Isp*g0" 意义上的等效比冲 [s]（仅作对照输出）。"""
    return dv_total / G0


def mass_ratio_for_dv(dv_total: float, ve_equiv: float) -> float:
    """若真按火箭方程提供该 ΔV 所需的质量比 m0/m_end（对照输出，不参与动力学）。"""
    return float(np.exp(dv_total / ve_equiv))


def a_drag_coeff(cfg: MissileConfig, cxk: float | None = None, drag_base: float | None = None,
                 mass: float | None = None) -> float:
    """基础阻力加速度系数 a = -(coeff * rho * V^2)，coeff = 0.5*k*S_ref*drag_base/m。

    这是 `legacy` 档的全部阻力；`mach`/`full` 档在此基础上再乘 f(M) 并叠加诱导阻力
    （见 `aero.py`）。mass 用于按工况指定弹体质量（None 取配置的 mass_end）。
    **质量时变的有限燃烧路径请用 `drag_k` 而不是本函数。**
    """
    k = cfg.drag.cxk if cxk is None else cxk
    db = cfg.drag.drag_base if drag_base is None else drag_base
    m = cfg.mass.mass_end if mass is None else mass
    return 0.5 * k * db * s_ref(cfg) / m


def drag_k(cfg: MissileConfig, cxk: float | None = None, drag_base: float | None = None) -> float:
    """**质量无关**的基础阻力系数 [m^2]：`a_drag = -(drag_k / m(t)) * rho * V^2`。

    有限燃烧时质量随时间变，故把质量从系数里拿出来，逐步用 m(t) 除。
    """
    k = cfg.drag.cxk if cxk is None else cxk
    db = cfg.drag.drag_base if drag_base is None else drag_base
    return 0.5 * k * db * s_ref(cfg)


def summary_lines(cfg: MissileConfig) -> list:
    """参数对照表（命令行打印用）。"""
    from . import aero as aero_mod

    bc0 = ballistic_coefficient(cfg.drag.cxk, cfg)
    dv0 = delta_v_equiv(cfg)
    ap = aero_mod.params_from_config(cfg)
    prof = cfg.profile
    if prof is not None:
        head = [
            f"标准弹               = {prof.name}（{prof.label}，tag={prof.tag}）",
            f"  来源               = {prof.file}；ΔV={prof.dv:.1f} m/s，BC={prof.bc:.1f}，"
            f"干重={prof.dry_mass:.3f} kg",
            f"  指纹               = {prof.profile_hash()}",
            f"  引信/寿命/过载上限 = {prof.fuse_radius_m:g} m / {prof.time_life_s:g} s / "
            f"{prof.req_accel_max_g:g} g",
            f"  高抛 blk 参数      = elev={prof.loft.elevation_deg:g}°, "
            f"targetElev={prof.loft.target_elevation_deg:g}°, "
            f"omegaMax={prof.loft.target_omega_max_dps:g}°/s, "
            f"拉杆×{prof.loft.angle_to_accel_mult:g}",
            f"  制导增益表         = {prof.gain_source} "
            f"{[(t, g) for t, g in prof.gain_schedule]}",
        ]
        if prof.fallbacks:
            head.append(f"  ⚠ 全局回退字段      = {'、'.join(prof.fallbacks)}")
    else:
        head = ["标准弹               = （未启用，用配置字面值）"]
    if cfg.burn is not None:
        head += burn_mod.describe(cfg.burn)
    return head + [
        f"口径 d              = {cfg.drag.caliber_m * 1000:.1f} mm",
        f"参考面积 S_ref       = {s_ref(cfg):.6f} m^2",
        f"升力面积 S_lift      = {ap.s_lift:.6f} m^2 "
        f"(0.3·d·{cfg.aero.length_m:g}·{cfg.aero.wing_area_mult:g})",
        f"干重锚定 m_bound     = {m_bound(cfg):.4f} kg (anchor={cfg.mass.mass_anchor})",
        f"发射质量 m0          = {cfg.mass.mass_launch:.4f} kg",
        f"基准 CxK             = {cfg.drag.cxk:.6f}",
        f"基准 BC              = {bc0:.1f}",
        f"基准 ΔV (火箭方程)   = {dv0:.1f} m/s  (ve_equiv={effective_ve_equiv(cfg):.1f} m/s, Isp≈{dv0 / G0:.1f} s)",
        f"阻力系数 0.5*k*S/m   = {a_drag_coeff(cfg):.8e} 1/m（干重口径）",
        f"气动模型             = {aero_mod.MODEL_LABELS[ap.model]}"
        f"{'' if ap.use_cxi_mach else '（useCxiMach=false）'}",
        f"升力参数             = CyK={ap.cyk:g}, CyMaxAoA={ap.cy_max_aoa:g} "
        f"(迎角上限 {degrees(asin(ap.sin_alpha_peak)):.2f}°), CxAoA_eff={ap.cx_aoa_eff:g}",
        f"侧向过载上限         = {cfg.sim.a_lat_max_g:.1f} g",
        f"高抛角               = {cfg.sim.theta_loft_deg:.1f} deg",
        f"命中半径 / 寿命      = {cfg.sim.hit_radius:.1f} m / {cfg.sim.t_life:.1f} s",
    ]

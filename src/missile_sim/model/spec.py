# -*- coding: utf-8 -*-
"""**模型接入的结构化 API**——引擎只认这三样：结构化输入、结构化输出、运行环境。

为什么要有这一层（用户 2026-09-25 定案）：后续会从开源拿到**更新的模型**（换一个引擎实现，
甚至换一套公式），必须能像换零件一样接进来，并保持版本管理闭环。因此：

    ┌ 上游（输入层 io.py）──► EngineInputs ──┐
    │                                          ├──► Engine.simulate ──► EngineResult ──► 输出层
    └ 运行环境（env.py）  ──► EngineEnv  ─────┘

三条纪律（本项目已踩过对应的坑）：

1. **ΔV/BC → 引擎参数的映射只有一处**（`io.build_inputs`）。引擎**不得**再自己算
   `dv_blk`/`bc_blk`/`thrust_scale`/`cx_scale`——今天 `native.py` 与 `flash.py` 各算一遍，
   口径一旦分叉就是静默数值错误（踩过：`dv_blk=536.9`、BC 误用升力面积）。
2. **引擎身份必须自报**（`EngineStamp`）：名字、语义版本、缓存 schema 号、保真度清单。
   产物里没有它，图就会被误读成"游戏实测"。
3. **缓存按模型分版本**：`ModelSpec.calc_version` 是该模型缓存的唯一失效开关；
   换模型/改数值只动它，不动别的模型的缓存（Pro 一轮 44 min，不能陪跑）。

引擎协议（`Engine`）是 `typing.Protocol`：**结构化子类型**，第三方模型不需要继承任何基类，
只要提供同名方法即可（`isinstance` 检查用 `runtime_checkable`，仅供诊断）。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Protocol, runtime_checkable

# 观测模式：ideal = 理想真值（与 Flash 同假设）；locked = 原生滤波/多径
OBSERVATION_MODES = ("ideal", "locked")

# 结果明细的可选键（不同引擎能给的粒度不同，缺的留空而不是编造）
FIDELITY_KEYS = ("recovered", "not_recovered", "derived")


def _round(x, nd=6):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return x
    return round(v, nd) if math.isfinite(v) else None


# ===================================================================== 参数块


@dataclass(frozen=True)
class MassProfile:
    """质量与推力剖面（权威 blkx `rocket` 块）。`two_stage=False` 时二级段忽略。"""

    launch: float
    mid: float
    dry: float
    force: float
    time_fire: float
    force1: float = 0.0
    time_fire1: float = 0.0
    fire_delay: float = 0.0
    two_stage: bool = False

    @property
    def burn_time_total(self) -> float:
        return self.time_fire + (self.time_fire1 if self.two_stage else 0.0)

    def stages(self) -> tuple:
        """[(m_start, m_end, force, time_fire), ...]（逐级；漏级会让 ΔV_blk 偏小）。"""
        out = [(self.launch, self.mid, self.force, self.time_fire)]
        if self.two_stage and self.mid > self.dry and self.time_fire1 > 0.0:
            out.append((self.mid, self.dry, self.force1, self.time_fire1))
        return tuple(out)


@dataclass(frozen=True)
class Geometry:
    """几何（权威 blkx）；两个参考面积由此派生，**不可混用**。"""

    caliber_m: float
    length_m: float
    wing_area_mult: float
    dist_from_cm_to_stab: float = 0.0
    inertia_scale: float = 1.0

    @property
    def sd_m2(self) -> float:
        """迎面面积 π(d/2)²：**阻力与 BC 用它**。"""
        return math.pi * (self.caliber_m / 2.0) ** 2

    @property
    def sl_m2(self) -> float:
        """升力面积 0.3·d·L·wingAreaMult：**升力用它**。"""
        return 0.3 * self.caliber_m * self.length_m * self.wing_area_mult

    @property
    def lever_m(self) -> float:
        """气动力臂（原生 `configure_properties` 口径）：distFromCmToStab / wingAreaMult。"""
        if self.wing_area_mult <= 0.0:
            return 0.0
        return self.dist_from_cm_to_stab / self.wing_area_mult


@dataclass(frozen=True)
class AeroCoeffs:
    """气动系数（权威 blkx + gameparams 回退）。"""

    cxk: float
    cyk: float = 2.2
    cy_max_aoa: float = 1.0
    cx_aoa: float = 9.0
    use_cxi_mach: bool = True                       # gameparams 开关
    apply_wing_area_mult_to_cx_aoa: bool = False    # gameparams 开关（false ⇒ CxAoA 不再乘 w²）

    @property
    def cx_aoa_eff(self) -> float:
        return self.cx_aoa * (1.0,) [0] if not self.apply_wing_area_mult_to_cx_aoa else self.cx_aoa


@dataclass(frozen=True)
class PidRow:
    """PID 时间表的一行（弹龄 time 之后生效；区间外取端点）。"""

    time: float
    prop: float
    intg: float
    diff: float
    intg_lim: float = 1.0


@dataclass(frozen=True)
class Autopilot:
    """飞控与制导外环参数（权威 blkx `guidance.guidanceAutopilot`）。

    PID 有**两种形态**，两者必居其一（本项目 11 型已全部覆盖）：
      * `pid_rows` 非空 —— 120A/C/D 的 `pid0…N`
      * 否则用扁平 `kp/ki/kd/i_limit` —— 其余 8 型（含 PL-12）的 `accelControl*`
    """

    req_accel_max_g: float = 35.0
    fins_lat_accel_g: float | None = None
    fins_aoa_hor: float | None = None
    fins_aoa_ver: float | None = None
    base_ind_speed: float = 1800.0
    prop_nav_mult: float = 4.0
    vel_frame_reference: bool = True
    limit_aoa: bool = False
    aoa_max_deg: float = 0.0
    time_out_s: float | None = None
    pid_rows: tuple = ()
    kp: float | None = None
    ki: float | None = None
    kd: float | None = None
    i_limit: float | None = None

    def pid_at(self, age: float) -> tuple:
        """弹龄 → (Kp, Ki, Kd, Ilimit)。时间表按弹龄**分段线性**、区间外取端点。"""
        if not self.pid_rows:
            return (self.kp, self.ki, self.kd, self.i_limit)

        def interp(key):
            xs = [r.time for r in self.pid_rows]
            ys = [getattr(r, key) for r in self.pid_rows]
            if age <= xs[0]:
                return ys[0]
            if age >= xs[-1]:
                return ys[-1]
            for i in range(len(xs) - 1):
                if xs[i] <= age <= xs[i + 1]:
                    span = xs[i + 1] - xs[i]
                    t = 0.0 if span <= 0.0 else (age - xs[i]) / span
                    return ys[i] + t * (ys[i + 1] - ys[i])
            return ys[-1]

        return (interp("prop"), interp("intg"), interp("diff"), interp("intg_lim"))


@dataclass(frozen=True)
class LoftConfig:
    """自动高抛（权威 blkx `guidanceAutopilot` 的 loft* 字段）。"""

    enabled: bool = False
    elevation_deg: float = 0.0                    # loftElevation：固定目标角
    target_elevation_deg: float = -89.9           # loftTargetElevation：退出仰角
    target_omega_max_dps: float = 0.0             # loftTargetOmegaMax：退出角速度
    angle_to_accel_mult: float = 0.0              # loftAngleToAccelMult：k_loft
    range_to_loft_elevation: tuple = ()           # (R1, θ1, R2, θ2)；空 ⇒ 用 elevation_deg

    def desired_elevation_deg(self, rng: float) -> float:
        """§4：按距离平方插值（区间外取端点）；无表则恒为 `elevation_deg`。"""
        t = self.range_to_loft_elevation
        if len(t) != 4:
            return self.elevation_deg
        r1, th1, r2, th2 = (float(x) for x in t)
        lo, hi = min(r1, r2), max(r1, r2)
        if hi <= lo:
            return th1
        lam = (rng * rng - lo * lo) / (hi * hi - lo * lo)
        lam = 0.0 if lam < 0.0 else (1.0 if lam > 1.0 else lam)
        a, b = (th1, th2) if r1 <= r2 else (th2, th1)
        return a + lam * (b - a)


@dataclass(frozen=True)
class GainTables:
    """制导增益表：时间增益（按弹龄）与预计命中时间增益（按 T_go）。

    `G = Gtime(age) × Ghit(Tgo)`（CALCULATION-FORMULAS §3）。两条 ramp 的断点不重叠时
    乘积与取 min 等价，但**不能拿 min 当定义**。
    """

    time_gain: tuple = ()        # ((age_s, gain), ...)
    hit_gain: tuple = ()         # ((tgo_s, gain), ...)
    source: str = "default"

    def g_time(self, age: float) -> float:
        return _table_value(age, self.time_gain, default=1.0)

    def g_hit(self, tgo: float) -> float:
        return _table_value(tgo, self.hit_gain, default=1.0)


@dataclass(frozen=True)
class Limits:
    """寿命与包线限制（权威 blkx）。"""

    time_life_s: float = 120.0
    max_distance_m: float | None = None
    mach_max: float | None = None
    load_factor_max_g: float | None = None


@dataclass(frozen=True)
class Fuse:
    """引信（权威 blkx `proximityFuse`）。"""

    has_proximity_fuse: bool = False
    radius_m: float = 0.0
    time_out_s: float | None = None


def _table_value(x: float, table, default: float = 1.0) -> float:
    """分段线性查表（区间外取端点；空表给 default）。"""
    if not table:
        return default
    xs = [float(a) for a, _ in table]
    ys = [float(b) for _, b in table]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            span = xs[i + 1] - xs[i]
            t = 0.0 if span <= 0.0 else (x - xs[i]) / span
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


# ===================================================================== 输入


@dataclass(frozen=True)
class EngineInputs:
    """**引擎唯一接受的输入**（结构化的"原材料"）。

    上游（`io.build_inputs`）负责：读权威 blkx、算 ΔV/BC 映射、按标准弹覆盖几何/气动/飞控。
    引擎负责：只按这些数跑，**不再解析 blk、不再算乘数**。
    """

    # —— 身份（进缓存键与产物）——
    missile: str
    version: str
    standard: str = ""
    tag: str = ""
    profile_hash: str = ""
    # —— 弹体 ——
    mass: MassProfile | None = None
    geometry: Geometry | None = None
    aero: AeroCoeffs | None = None
    autopilot: Autopilot = field(default_factory=Autopilot)
    loft: LoftConfig = field(default_factory=LoftConfig)
    gains: GainTables = field(default_factory=GainTables)
    limits: Limits = field(default_factory=Limits)
    fuse: Fuse = field(default_factory=Fuse)
    # —— (ΔV, BC) → 引擎参数的**唯一**映射结果 ——
    dv_target: float = 0.0
    bc_target: float = 0.0
    dv_blk: float = math.nan
    bc_blk: float = math.nan
    thrust_scale: float = 1.0
    cx_scale: float = 1.0
    cxk_used: float = math.nan
    # —— 场景 ——
    range_m: float = 50000.0
    alt_m: float = 10000.0
    target_alt_m: float | None = None
    vm0: float = 300.0
    vt: float = -300.0
    wind_m_s: tuple = (0.0, 0.0, 0.0)
    ground_height_m: float = 0.0
    target_maneuvers: tuple = ()          # ((time_s, (ax, ay, az)), ...)
    # —— 技术参数（与物理无关）——
    dt: float = 0.01
    duration_s: float = 150.0
    sample_period_s: float = 0.25
    observation_mode: str = "ideal"
    hit_radius_m: float = 0.0             # 0 ⇒ 只用引擎自己的近炸判定
    proximity_fuse: bool = True
    save_trajectory: bool = False         # 轨迹占单条记录 95%：默认不要，且**不参与缓存键**

    # ---------------------------------------------------------------- 派生

    @property
    def target_alt(self) -> float:
        return self.alt_m if self.target_alt_m is None else self.target_alt_m

    @property
    def target_velocity(self) -> tuple:
        """目标速度向量（+x 迎面）。目标机动是加速度，不在这里。"""
        return (float(self.vt), 0.0, 0.0)

    @property
    def launch_velocity(self) -> tuple:
        return (float(self.vm0), 0.0, 0.0)

    def missil(self) -> str:                       # pragma: no cover - 笔误保护
        raise AttributeError("字段名是 missile")

    # ---------------------------------------------------------------- 缓存键

    def cache_key(self) -> str:
        """缓存键。**逐字段与旧 `NativeCase.key()` 对齐**，否则 44 min 的 Pro 缓存会全部作废。

        不含：轨迹要不要存（`save_trajectory`）、弹池短名/指纹、派生量。
        """
        blob = json.dumps([
            self.version, self.missile,
            round(float(self.dv_target), 6), round(float(self.bc_target), 6),
            self.range_m, self.alt_m, self.target_alt, self.vm0, self.vt,
            self.dt, self.observation_mode, self.hit_radius_m, self.proximity_fuse,
            list(self.wind_m_s), self.ground_height_m,
            [list(m) for m in self.target_maneuvers],
        ], sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]

    # ---------------------------------------------------------------- 自检

    def check(self) -> list:
        """结构自检：返回问题列表（空 = 通过）。引擎开工前先跑这个。"""
        bad = []
        if not self.missile:
            bad.append("missile 为空")
        if self.mass is None:
            bad.append("缺 mass 剖面")
        else:
            if self.mass.dry <= 0.0 or self.mass.launch < self.mass.mid:
                bad.append(f"质量剖面非法：{self.mass.launch}/{self.mass.mid}/{self.mass.dry}")
        if self.geometry is None:
            bad.append("缺 geometry（口径/弹长/翼面积倍率）")
        elif self.geometry.sd_m2 <= 0.0:
            bad.append("迎面面积非正（口径非法）")
        if self.aero is None:
            bad.append("缺气动系数（CxK）")
        elif self.aero.cxk <= 0.0:
            bad.append("CxK 非正")
        if self.dt <= 0.0:
            bad.append("dt 必须为正")
        if self.duration_s <= 0.0:
            bad.append("duration_s 必须为正")
        if str(self.observation_mode) not in OBSERVATION_MODES:
            bad.append(f"未知观测模式 {self.observation_mode!r}")
        if not (math.isfinite(self.dv_blk) and self.dv_blk > 0.0):
            bad.append("dv_blk 非正（ΔV 映射未做或做错）")
        if self.dv_target and not math.isfinite(self.thrust_scale):
            bad.append("thrust_scale 非有限")
        if self.bc_target and not math.isfinite(self.cx_scale):
            bad.append("cx_scale 非有限")
        # 映射自洽：外部给 ΔV/BC 时，乘数必须与参照量一致（防两处重算分叉）
        if self.dv_target and abs(self.thrust_scale - self.dv_target / self.dv_blk) > 1e-9:
            bad.append(f"thrust_scale={self.thrust_scale} 与 dv_target/dv_blk 不一致")
        if self.bc_target and self.geometry is not None and self.aero is not None:
            want = self.mass.dry / (self.bc_target * self.geometry.sd_m2 * self.aero.cxk)
            if abs(self.cx_scale - want) > 1e-9:
                bad.append(f"cx_scale={self.cx_scale} 与 BC 反解不一致（期望 {want}）")
        return bad


# ===================================================================== 输出


@dataclass(frozen=True)
class EngineStamp:
    """引擎身份（进 `CaseRecord.model` 与 run manifest）：产物必须自报是谁算的。"""

    name: str
    version: str
    calc_version: int
    fidelity: dict = field(default_factory=dict)   # recovered / not_recovered / derived
    resources: dict = field(default_factory=dict)  # pkg/elf/dt/dt_inner/... 引擎自定

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SelfTestReport:
    """接入即验的结果（`pipeline.py models --check`）。"""

    name: str
    ok: bool
    checks: list = field(default_factory=list)     # [(项目, 通过?, 说明)]
    detail: dict = field(default_factory=dict)
    error: str = ""

    def add(self, item: str, ok: bool, note: str = "") -> "SelfTestReport":
        self.checks.append({"item": item, "ok": bool(ok), "note": note})
        self.ok = self.ok and bool(ok)
        return self

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Capability:
    """模型能力声明。调用方**先查后调**，不许靠 try/except 探。"""

    dims: str = "2d"                    # "2d" | "3d"
    target_maneuvers: bool = False
    vectorized_batch: bool = False      # 有 simulate_many ⇒ 网格快车道可用
    trajectory: bool = True
    observation_modes: tuple = ("ideal",)
    wind: bool = False
    tvc: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["observation_modes"] = list(self.observation_modes)
        return d


# ===================================================================== 规格


@dataclass(frozen=True)
class ModelSpec:
    """模型的注册信息 = **版本管理的落点**。

    `calc_version` 是该模型缓存的唯一失效开关：任何影响"输入→结果"数值的改动都必须 +1，
    否则旧缓存会被当成新结果复用（踩过：410 条 `dv_blk=536.9` 的坏条目让 t_hit 从 45.1 变 25.6）。
    """

    name: str
    label: str
    version: str
    calc_version: int
    entry: str                          # "missile_sim.model.native:ProEngine"
    source: str = "builtin"
    capabilities: Capability = field(default_factory=Capability)
    requirements: dict = field(default_factory=dict)   # {"native_pkg": True, "datamine": True}
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "version": self.version,
                "calc_version": int(self.calc_version), "entry": self.entry,
                "source": self.source, "capabilities": self.capabilities.to_dict(),
                "requirements": dict(self.requirements), "note": self.note}


# ===================================================================== 环境


@dataclass
class EngineEnv:
    """**显式运行环境**——替掉隐式的全局依赖（原生包路径、chdir、步长、并发数）。

    以前这些散在 `ProRunner.__init__` / `_worker_init` / `FlashRunner.__init__` 里，
    第三方模型无从得知该去哪儿找 ELF、工作目录该切到哪。
    """

    pkg: str | None = None          # 原生运行包根（Pro 用；第三方模型可忽略）
    version: str = ""               # 数据源版本（原生包版本 / 公式文档日期）
    workdir: str | None = None      # 子进程需要 chdir 到的地方（原生 resources 用相对路径）
    dt: float | None = None         # 引擎外层步长（None ⇒ 用模型默认）
    dt_inner: float | None = None   # 内层子步（纯 Python 引擎用）
    pool_jobs: int = 8
    datamine_root: str | None = None
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def get(self, key: str, default=None):
        return self.options.get(key, default)


# ===================================================================== 协议


@runtime_checkable
class Engine(Protocol):
    """引擎协议（结构化子类型：不要求继承）。

    必实现：`spec` / `simulate` / `selftest` / `runtime_info`。
    可选（用 `spec.capabilities` 先声明再调用）：`simulate_many` / `trace` / `close`。
    """

    spec: ModelSpec

    def inputs(self, env: EngineEnv, inp: EngineInputs) -> EngineInputs:
        """可选钩子：引擎把外部输入补成自己需要的样子（默认原样返回）。"""

    def simulate(self, inp: EngineInputs, env: EngineEnv):
        """跑一个工况 → `NativeResult`（含 `engine: EngineStamp`）。"""

    def selftest(self, env: EngineEnv) -> SelfTestReport:
        """接入即验：最小工况 + 身份/版本/映射自洽 + 声明能力与实测一致。"""

    def runtime_info(self) -> dict:
        """身份块（进 manifest/记录）。"""


def digest_of_inputs(inp: EngineInputs) -> str:
    """输入指纹（诊断/比对用；与 run 级 `inputs_digest` 不同，后者只含物理输入）。"""
    blob = json.dumps(_jsonable(inp), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _jsonable(obj) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return str(obj)

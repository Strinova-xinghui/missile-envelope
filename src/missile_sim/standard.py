# -*- coding: utf-8 -*-
"""标准弹：从"11 弹池"（`results/missile_standards.json`）解析出的参数快照。

**为什么要有这一层**：等时线图是在 (ΔV, BC) 平面上扫描的，但"ΔV 换成多少推力、
质量怎么掉、几何与引信多大、高抛怎么拉"这些都得由**某一型真实弹**给定。
本模块把那份"标准弹"的完整参数做成不可变对象，仿真器只读池、不碰 `E:\\WT`。

池由 `scripts/build_standard_pool.py` 生成并入库（纯数值，可自包含复现）。

回退规则（池里 `fallbacks` 字段会逐项记录，便于在输出里暴露看不见的假设）：
  * `CyK`  —— 全库 11 型都没有该键 ⇒ 全局 2.2
  * `CxAoA`—— 同上 ⇒ gameparams 的 9.0
  * `CyMaxAoA` —— 仅部分弹有 ⇒ 缺省 1.0
  * 增益表 —— 优先 `timeToHitToGain{0,1,2}`；没有则用 `timeToGain{0,1}`。
    对 11 型这**等价于游戏的"两条 ramp 取 min"**：所有 `timeToGain` 的断点都 ≤0.31 s，
    而 `timeToHitToGain` 的断点都 ≥10 s，故 0.31 s 之后 min 恒等于命中前解锁表。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_POOL = Path(__file__).resolve().parents[2] / "results" / "missile_standards.json"

# 全局回退值（与池里的记录一致）
CYK_DEFAULT = 2.2
CX_AOA_DEFAULT = 9.0
CY_MAX_AOA_DEFAULT = 1.0
REQ_ACCEL_DEFAULT_G = 35.0
GAIN_FALLBACK = ((10.0, 1.0), (25.0, 0.8), (50.0, 0.5))


class StandardPoolError(ValueError):
    """池文件缺失/型号不存在/schema 不合法。"""


@dataclass(frozen=True)
class LoftSpec:
    enabled: bool
    elevation_deg: float
    target_elevation_deg: float
    target_omega_max_dps: float
    angle_to_accel_mult: float


@dataclass(frozen=True)
class EngineSpec:
    """N 段燃烧剖面（单段 = `two_stage=False`，第二段推力为 0）。"""

    mass_launch: float
    mass_mid: float
    mass_dry: float
    force: float
    time_fire: float
    force1: float
    time_fire1: float
    two_stage: bool

    @property
    def burn_time_total(self) -> float:
        return self.time_fire + (self.time_fire1 if self.two_stage else 0.0)

    def stages(self) -> tuple:
        """[(m_start, m_end, thrust, duration), ...]（已按需去掉零燃料段）。"""
        out = [(self.mass_launch, self.mass_mid, self.force, self.time_fire)]
        if self.two_stage and self.mass_mid > self.mass_dry and self.time_fire1 > 0.0:
            out.append((self.mass_mid, self.mass_dry, self.force1, self.time_fire1))
        return tuple(out)


@dataclass(frozen=True)
class StandardProfile:
    """一型标准弹的完整参数快照（不可变，可作缓存键）。"""

    name: str
    label: str
    file: str
    tag: str
    source: str
    caliber_m: float
    length_m: float
    wing_area_mult: float
    cxk: float
    cyk: float
    cy_max_aoa: float
    cx_aoa: float
    engine: EngineSpec
    dv: float
    bc: float
    isp1: float
    isp2: float | None
    ve_equiv: float
    req_accel_max_g: float
    load_factor_max_g: float | None
    fins_lat_accel_g: float | None
    fins_aoa_hor: float | None
    fins_aoa_ver: float | None
    prop_nav_mult: float
    max_distance_m: float | None
    time_life_s: float
    mach_max: float | None
    fuse_radius_m: float
    fuse_time_out_s: float | None
    has_proximity_fuse: bool
    loft: LoftSpec
    gain_schedule: tuple            # ((t_go, gain), ...) 实际使用的那张
    gain_source: str                # timeToHitToGain | timeToGain | default
    launch_schedule: tuple          # 发射后 ramp（仅记录，本轮不参与制导）
    fallbacks: tuple = field(default=())

    @property
    def dry_mass(self) -> float:
        return self.engine.mass_dry

    def profile_hash(self) -> str:
        """参数指纹（缓存键/结果追溯用；不含来源路径）。"""
        blob = json.dumps({
            "name": self.name, "tag": self.tag, "caliber": self.caliber_m,
            "length": self.length_m, "wam": self.wing_area_mult,
            "cxk": self.cxk, "cyk": self.cyk, "cy_max_aoa": self.cy_max_aoa,
            "cx_aoa": self.cx_aoa,
            "engine": [self.engine.mass_launch, self.engine.mass_mid, self.engine.mass_dry,
                       self.engine.force, self.engine.time_fire,
                       self.engine.force1, self.engine.time_fire1,
                       self.engine.two_stage],
            "req_g": self.req_accel_max_g, "prop_nav": self.prop_nav_mult,
            "life": self.time_life_s, "fuse": self.fuse_radius_m,
            "loft": [self.loft.enabled, self.loft.elevation_deg,
                     self.loft.target_elevation_deg, self.loft.target_omega_max_dps,
                     self.loft.angle_to_accel_mult],
            "gains": [list(p) for p in self.gain_schedule], "gain_src": self.gain_source,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 池读取


def load_pool(pool_path=None) -> dict:
    p = Path(pool_path) if pool_path else DEFAULT_POOL
    if not p.exists():
        raise StandardPoolError(
            f"找不到标准弹池 {p}；请先运行：python scripts\\build_standard_pool.py"
        )
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StandardPoolError(f"标准弹池不是合法 JSON：{p}（{exc}）") from exc
    if not isinstance(doc.get("missiles"), dict) or not doc["missiles"]:
        raise StandardPoolError(f"标准弹池缺少 missiles 段：{p}")
    return doc


def pool_names(pool_path=None) -> list:
    """池内型号短名（保持文件顺序）。"""
    return list(load_pool(pool_path)["missiles"].keys())


def default_name(pool_path=None) -> str:
    doc = load_pool(pool_path)
    return doc.get("default") or next(iter(doc["missiles"]))


def _need(d: dict, key: str, where: str):
    if key not in d or d[key] is None:
        raise StandardPoolError(f"标准弹池 schema 不完整：{where}.{key} 缺失")
    return d[key]


def _f(d: dict, key: str, where: str, default=None):
    v = d.get(key, None)
    if v is None:
        return default
    return float(v)


def resolve(name: str, pool_path=None, tag: str | None = None) -> StandardProfile:
    """按短名（如 "PL-12"）解析出标准弹参数快照。"""
    doc = load_pool(pool_path)
    missiles = doc["missiles"]
    if name not in missiles:
        raise StandardPoolError(
            f"标准弹池里没有 {name!r}；可用：{'、'.join(missiles.keys())}"
        )
    m = missiles[name]
    if tag is not None and m.get("tag") not in (None, tag):
        raise StandardPoolError(
            f"标准弹 {name} 来自 tag={m.get('tag')}，与请求的 tag={tag} 不符"
        )

    geo = m.get("geometry") or {}
    aero = m.get("aero") or {}
    mass = m.get("mass") or {}
    eng = m.get("engine") or {}
    lim = m.get("limits") or {}
    loft = m.get("loft") or {}
    fuse = m.get("fuse") or {}
    gains = m.get("gains") or {}

    two = bool(mass.get("two_stage", False))
    engine = EngineSpec(
        mass_launch=_f(mass, "launch", "mass"),
        mass_mid=_f(mass, "mid", "mass", _f(mass, "dry", "mass")),
        mass_dry=_f(mass, "dry", "mass"),
        force=_f(eng, "force", "engine"),
        time_fire=_f(eng, "time_fire", "engine"),
        force1=_f(eng, "force1", "engine", 0.0),
        time_fire1=_f(eng, "time_fire1", "engine", 0.0),
        two_stage=two,
    )
    if engine.mass_dry <= 0 or engine.mass_launch < engine.mass_mid or engine.mass_mid < engine.mass_dry:
        raise StandardPoolError(
            f"标准弹 {name} 质量剖面非法：{engine.mass_launch}/{engine.mass_mid}/{engine.mass_dry}"
        )
    if two and (engine.force1 <= 0.0 or engine.time_fire1 <= 0.0):
        raise StandardPoolError(f"标准弹 {name} 标为两段但第二段参数缺失")

    sch = tuple((float(a), float(b)) for a, b in (gains.get("impact_schedule") or GAIN_FALLBACK))
    if len(sch) < 2:
        sch = GAIN_FALLBACK
    launch = tuple((float(a), float(b)) for a, b in (gains.get("launch_schedule") or ()))

    return StandardProfile(
        name=name,
        label=m.get("label") or name,
        file=m.get("file") or "",
        tag=m.get("tag") or doc.get("tag") or "",
        source=doc.get("source", ""),
        caliber_m=_f(geo, "caliber_m", "geometry"),
        length_m=_f(geo, "length_m", "geometry"),
        wing_area_mult=_f(geo, "wing_area_mult", "geometry"),
        cxk=_f(aero, "cxk", "aero"),
        cyk=_f(aero, "cyk", "aero", CYK_DEFAULT),
        cy_max_aoa=_f(aero, "cy_max_aoa", "aero", CY_MAX_AOA_DEFAULT),
        cx_aoa=_f(aero, "cx_aoa", "aero", CX_AOA_DEFAULT),
        engine=engine,
        dv=_f(m.get("impulse") or {}, "dv", "impulse"),
        bc=_f(m.get("impulse") or {}, "bc", "impulse"),
        isp1=_f(m.get("impulse") or {}, "isp1", "impulse"),
        isp2=_f(m.get("impulse") or {}, "isp2", "impulse"),
        ve_equiv=_f(m.get("impulse") or {}, "ve_equiv", "impulse"),
        req_accel_max_g=_f(lim, "req_accel_max_g", "limits", REQ_ACCEL_DEFAULT_G),
        load_factor_max_g=_f(lim, "load_factor_max_g", "limits"),
        fins_lat_accel_g=_f(lim, "fins_lat_accel_g", "limits"),
        fins_aoa_hor=_f(lim, "fins_aoa_hor", "limits"),
        fins_aoa_ver=_f(lim, "fins_aoa_ver", "limits"),
        prop_nav_mult=_f(lim, "prop_nav_mult", "limits", 6.0),
        max_distance_m=_f(lim, "max_distance_m", "limits"),
        time_life_s=_f(lim, "time_life_s", "limits", 120.0),
        mach_max=_f(lim, "mach_max", "limits"),
        fuse_radius_m=_f(fuse, "radius_m", "fuse", 12.0),
        fuse_time_out_s=_f(fuse, "time_out_s", "fuse"),
        has_proximity_fuse=bool(fuse.get("has_proximity_fuse", False)),
        loft=LoftSpec(
            enabled=bool(loft.get("enabled", False)),
            elevation_deg=_f(loft, "elevation_deg", "loft"),
            target_elevation_deg=_f(loft, "target_elevation_deg", "loft"),
            target_omega_max_dps=_f(loft, "target_omega_max_dps", "loft"),
            angle_to_accel_mult=_f(loft, "angle_to_accel_mult", "loft"),
        ),
        gain_schedule=sch,
        gain_source=str(gains.get("impact_source") or "default"),
        launch_schedule=launch,
        fallbacks=tuple(m.get("fallbacks") or ()),
    )

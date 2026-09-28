# -*- coding: utf-8 -*-
"""β–γ 能力平面：两种存能能力，以及由它们派生的机动指标。

**两个坐标轴**（都是弹的固有属性，单位 `kg/m²`）：

    β = m燃尽 / (SD · CxK)                          直飞保能，越大越好
    γ = m燃尽 · SD · CxK · CxAoA / (SL² · CyK²)     转向损失，越小越好

    SD = π·d²/4                      = 内核 drag_area（wt_missile.py:758）
    SL = 0.3·d·L·wingAreaMult        = 内核 lift_area （wt_missile.py:757）

**为什么是两个独立维度**：β 的分母只有口径与 `CxK`；γ 的分母还含升力面积平方与 `CyK²`，
数学上互不包含（β 甚至不含 `wingAreaMult`）。内核把两者放在同一个阻力式里
（`wt_missile.py:810`）：

    D = q·SD·CxK·[ f(M) + CxAoA·F(M)·sin²α ]

把 `sinα` 换成过载（`L = q·SL·CyK·sinα`，`n ≡ L/(m·g0)`）再除质量：

    a_loss = q·f(M)/β  +  γ·F(M)·(n·g0)²/q
             └基础项┘     └── 诱导阻力项 ──┘

两项对动压的依赖**方向相反**（∝q 与 ∝1/q）—— 这就是"高空高速看 β、低空缠斗看 γ"的根源。

**派生指标**（含 `q`，所以要给定参考工况）：

    Q     = √(β·γ·F(M)/f(M))      机动敏感度 [kg/m²]。`F/f` 在 Ma 上只波动 ±6%，
                                  所以 Q 近似是弹的固有量，最适合当坐标轴
    n*    = q/(Q·g0)              临界过载 [G]：机动损失恰好等于基础损失。越小越"贵"
    R     = (n/n*)²               机动惩罚比；R=1 时两项等量
    β_eff = β/(1+R)               等效弹道系数（把机动折回成 BC 的口径）

⚠ **口径**：β、γ 都用**标称**值（不含马赫修正 `f`、`F`）。含进去它们就随马赫变 2 倍，
不再是定值、没法当坐标轴。这与第一张图把 `BC` 定义成不含 `f` 的做法一致。

⚠ **适用边界**：仅升力线性段（`CyK·sinα ≤ CyMaxAoA`）、准平衡无角速度、`n` 是实际气动
过载。详见 `docs/BETA-GAMMA.md`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import mapping, solver

#: β–γ 的默认参考工况。与 `_recon/make_fig2_turn_energy.py` 一致（10 km / 800 m/s），
#: 这样新图与既有参考图的等 `n*` 线可以直接对照。
REF_ALT_M = 10_000.0
REF_SPEED_MS = 800.0

#: 等 `n*` 线的默认层（G）。取自参考图的 14~20。
REF_NSTAR_LEVELS = (14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0)

G0 = 9.81


@dataclass(frozen=True)
class BgPoint:
    """一型弹在 β–γ 平面上的固有位置（不含参考工况）。"""

    key: str
    beta: float          # kg/m²  直飞保能
    gamma: float         # kg/m²  转向损失
    dry_kg: float        # 燃尽质量（β/γ 的分子）
    sd_m2: float         # 迎风面积 πd²/4
    sl_m2: float         # 升力面积 0.3·d·L·w
    cxk: float
    cx_aoa: float        # 内核实际值（blk 缺失时为内核兜底 9.0，含 w² 修正）
    cyk: float           # 同上（兜底 2.2）
    caliber_m: float
    length_m: float
    wing_area_mult: float

    def as_dict(self) -> dict:
        return {"key": self.key, "beta": self.beta, "gamma": self.gamma,
                "dry_kg": self.dry_kg, "sd_m2": self.sd_m2, "sl_m2": self.sl_m2,
                "cxk": self.cxk, "cx_aoa": self.cx_aoa, "cyk": self.cyk,
                "caliber_m": self.caliber_m, "length_m": self.length_m,
                "wing_area_mult": self.wing_area_mult}


@dataclass(frozen=True)
class BgReference:
    """给定参考工况后，某一点/某一弹的机动指标。"""

    alt_m: float
    speed_ms: float
    mach: float
    q_pa: float          # 动压
    f_mach: float        # 内核的 f(M)：零升阻力马赫修正
    cap_f: float         # 内核的 F(M) = 3.247·[0.308+0.75(f-0.308)]
    beta: float
    gamma: float
    q_sens: float        # Q  = √(β·γ·F/f)
    n_star: float        # 临界过载 [G]
    n: float             # 本次评估用的过载
    ratio: float         # R  = (n/n*)²
    beta_eff: float      # β/(1+R)

    def as_dict(self) -> dict:
        return {"alt_m": self.alt_m, "speed_ms": self.speed_ms, "mach": self.mach,
                "q_pa": self.q_pa, "f_mach": self.f_mach, "cap_f": self.cap_f,
                "beta": self.beta, "gamma": self.gamma, "q_sens": self.q_sens,
                "n_star": self.n_star, "n": self.n, "ratio": self.ratio,
                "beta_eff": self.beta_eff}


# --------------------------------------------------------------------- 固有量


def point_of(entry, version: str | None = None) -> BgPoint:
    """池项 → β–γ 坐标。`entry` 是 `pool.PoolEntry`（或任何有 `.key`/`.native` 的对象）。"""
    params = solver.profile(entry.native, version)
    cx_aoa, cyk = solver.body_aero(entry.native, version)
    m_dry = mapping.blk_metrics(params).dry_kg
    return _point(entry.key, params, m_dry, cx_aoa, cyk)


def _point(key, params, m_dry, cx_aoa, cyk) -> BgPoint:
    d = float(params["caliber"])
    length = float(params["length"])
    w = float(params.get("wingAreaMult", 1.0))
    cxk = float(params["CxK"])
    sd = math.pi * d * d / 4.0
    sl = 0.3 * d * length * w
    if m_dry <= 0 or sd <= 0 or sl <= 0 or cxk <= 0 or cx_aoa <= 0 or cyk <= 0:
        raise ValueError(f"{key}: β/γ 的分母出现非正量（m={m_dry} SD={sd} SL={sl} "
                         f"CxK={cxk} CxAoA={cx_aoa} CyK={cyk}）")
    return BgPoint(key=str(key), beta=m_dry / (sd * cxk),
                   gamma=m_dry * sd * cxk * cx_aoa / (sl * sl * cyk * cyk),
                   dry_kg=m_dry, sd_m2=sd, sl_m2=sl, cxk=cxk, cx_aoa=cx_aoa,
                   cyk=cyk, caliber_m=d, length_m=length, wing_area_mult=w)


def points(keys=None, *, version: str | None = None) -> list:
    """散点数据集。`keys=None` ⇒ 全池；顺序照 `pool`。"""
    from . import pool                                   # 循环导入：只在调用时取
    return [point_of(e, version) for e in pool.resolve_many(keys)]


# --------------------------------------------------------------------- 参考工况


def reference(alt_m: float | None = None, speed_ms: float | None = None) -> tuple:
    """参考工况 → `(alt_m, speed_ms, mach, q_pa, f_mach, cap_f)`。

    `q = ½ρv²`、`M = v/a`、`f = 内核 _mach_function(M)`、
    `F = 3.247·[0.308 + 0.75·(f − 0.308)]`（内核 `induced/cx_aoa` 的那个因子）。
    """
    alt = float(REF_ALT_M if alt_m is None else alt_m)
    speed = float(REF_SPEED_MS if speed_ms is None else speed_ms)
    if speed <= 0:
        raise ValueError("参考速度必须为正")
    rho, sound = solver.atmosphere(alt)
    if sound <= 0:
        raise ValueError("该高度的声速非正，参考工况无效")
    mach = speed / sound
    f_mach = solver.mach_function(mach)
    cap_f = 3.247 * (0.308 + 0.75 * (f_mach - 0.308))
    return alt, speed, mach, 0.5 * rho * speed * speed, f_mach, cap_f


def q_sens(beta: float, gamma: float, cap_f: float, f_mach: float) -> float:
    """`Q = √(β·γ·F/f)` —— 机动敏感度 [kg/m²]。"""
    if beta <= 0 or gamma <= 0:
        raise ValueError("β、γ 必须为正")
    return math.sqrt(beta * gamma * cap_f / f_mach)


def n_star_of(q_pa: float, q_value: float) -> float:
    """临界过载 `n* = q/(Q·g0)` [G]：机动损失恰好等于基础损失的那个过载。"""
    if q_value <= 0:
        raise ValueError("Q 必须为正")
    return float(q_pa) / (float(q_value) * G0)


def evaluate(beta: float, gamma: float, *, alt_m: float | None = None,
             speed_ms: float | None = None, n: float = 20.0) -> BgReference:
    """在参考工况下评估一对 `(β, γ)`。

    `R = (n/n*)²` 是机动惩罚比；`β_eff = β/(1+R)` 是把机动折回 BC 口径的等效值。
    """
    alt, speed, mach, q_pa, f_mach, cap_f = reference(alt_m, speed_ms)
    qv = q_sens(beta, gamma, cap_f, f_mach)
    ns = n_star_of(q_pa, qv)
    nn = float(n)
    ratio = (nn / ns) ** 2 if ns > 0 else math.inf
    return BgReference(alt_m=alt, speed_ms=speed, mach=mach, q_pa=q_pa, f_mach=f_mach,
                       cap_f=cap_f, beta=float(beta), gamma=float(gamma), q_sens=qv,
                       n_star=ns, n=nn, ratio=ratio, beta_eff=float(beta) / (1.0 + ratio))


def evaluate_point(p: BgPoint, *, alt_m: float | None = None,
                   speed_ms: float | None = None, n: float = 20.0) -> BgReference:
    """`point_of()` 的结果 → 参考工况下的机动指标。"""
    return evaluate(p.beta, p.gamma, alt_m=alt_m, speed_ms=speed_ms, n=n)


# --------------------------------------------------------------------- 等 n* 线


def nstar_curve(n_star: float, betas, *, alt_m: float | None = None,
                speed_ms: float | None = None) -> list:
    """等 `n*` 线：给定 β 序列返回对应的 γ。

    由 `n* = q/(Q·g0)` 与 `Q = √(βγF/f)` 反解：

        γ = (q / (n*·g0))² · (f/F) / β

    所以等 `n*` 线是**双曲线** `γ ∝ 1/β`（参考图里那条虚线族）。
    """
    _alt, _speed, _mach, q_pa, f_mach, cap_f = reference(alt_m, speed_ms)
    if n_star <= 0:
        raise ValueError("n* 必须为正")
    k = (q_pa / (n_star * G0)) ** 2 * (f_mach / cap_f)
    out = []
    for b in betas:
        b = float(b)
        out.append(k / b if b > 0 else math.nan)
    return out


def levels(*, alt_m: float | None = None, speed_ms: float | None = None) -> tuple:
    """参考工况下的 `(q_pa, f_mach, cap_f, F/f)`，供图上标注口径用。"""
    _alt, _speed, _mach, q_pa, f_mach, cap_f = reference(alt_m, speed_ms)
    return q_pa, f_mach, cap_f, cap_f / f_mach

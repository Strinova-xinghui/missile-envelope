# -*- coding: utf-8 -*-
"""燃烧剖面：质量与推力作为**时间 t 的纯函数**（不新增 ODE 状态）。

设计要点：
  * 有限燃烧不改变 RK4 结构——`m(t)`、`thrust(t)` 只依赖时间，故在四个取时上直接求值即可；
  * **未缩放**的剖面来自标准弹；逐工况只乘两个标量：
      `k = 本工况质量锚定 / 标准弹干重`（整条质量剖面等比缩放，保持装药比例与比冲）
      `s = 目标 ΔV / 标准弹 ΔV`（各段推力同乘，只改比冲 ⇒ 总 ΔV 严格 ∝ s）
  * 单段弹是退化情形：`two_stage=False` 时第二段不存在。
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_FINITE = "finite"
MODEL_INSTANT = "instant"
MODEL_LABELS = {MODEL_FINITE: "有限燃烧（N 段）", MODEL_INSTANT: "瞬时燃烧（旧口径）"}

BURN_MODELS = (MODEL_FINITE, MODEL_INSTANT)


@dataclass(frozen=True)
class BurnProfile:
    """标准弹的燃烧剖面（未缩放）。`model="instant"` 时动力学退回旧口径。"""

    model: str
    mass_launch: float
    mass_mid: float
    mass_dry: float
    force: float
    time_fire: float
    force1: float
    time_fire1: float
    two_stage: bool
    dv_blk: float

    # ---------------------------------------------------------------- 标量
    def mass_at(self, t: float) -> float:
        """未缩放质量 [kg]。"""
        if t < self.time_fire:
            frac = 0.0 if self.time_fire <= 0.0 else t / self.time_fire
            return self.mass_launch + (self.mass_mid - self.mass_launch) * frac
        if self.two_stage and t < self.time_fire + self.time_fire1:
            frac = (t - self.time_fire) / self.time_fire1
            return self.mass_mid + (self.mass_dry - self.mass_mid) * frac
        return self.mass_dry

    def thrust_at(self, t: float) -> float:
        """未缩放推力 [N]。"""
        if t < self.time_fire:
            return self.force
        if self.two_stage and t < self.time_fire + self.time_fire1:
            return self.force1
        return 0.0

    # ---------------------------------------------------------------- 派生
    @property
    def burn_time_total(self) -> float:
        return self.time_fire + (self.time_fire1 if self.two_stage else 0.0)

    @property
    def has_thrust(self) -> bool:
        return self.model == MODEL_FINITE and self.force > 0.0 and self.time_fire > 0.0

    def scale_for_dv(self, dv_target: float) -> float:
        """把各段推力同乘的系数，使真空总 ΔV = dv_target。"""
        if self.dv_blk <= 0.0:
            return 1.0
        return float(dv_target) / self.dv_blk


def instant_profile(dv_blk: float = 0.0) -> BurnProfile:
    """旧口径：无推力、质量为常数（由调用方给干重）。"""
    return BurnProfile(model=MODEL_INSTANT, mass_launch=0.0, mass_mid=0.0, mass_dry=0.0,
                       force=0.0, time_fire=0.0, force1=0.0, time_fire1=0.0,
                       two_stage=False, dv_blk=dv_blk)


def from_standard(prof, model: str = MODEL_FINITE) -> BurnProfile:
    """由 `standard.StandardProfile` 造燃烧剖面。"""
    if model not in BURN_MODELS:
        raise ValueError(f"burn model 必须是 {BURN_MODELS} 之一，收到 {model!r}")
    e = prof.engine
    return BurnProfile(
        model=model,
        mass_launch=e.mass_launch, mass_mid=e.mass_mid, mass_dry=e.mass_dry,
        force=e.force, time_fire=e.time_fire,
        force1=e.force1, time_fire1=e.time_fire1,
        two_stage=bool(e.two_stage), dv_blk=float(prof.dv),
    )


def mass_ratio_at(t: float, burn: BurnProfile | None, k: float = 1.0) -> float:
    """`m(t)/m_dry`（aero 的质量比 μ）。instant 或无剖面时恒为 1。"""
    if burn is None or burn.model != MODEL_FINITE or burn.mass_dry <= 0.0:
        return 1.0
    return float(k) * burn.mass_at(t) / burn.mass_dry


def describe(burn: BurnProfile | None) -> list:
    """给 `summary_lines` 用的可读描述。"""
    if burn is None:
        return ["燃烧剖面             = （无）"]
    if burn.model == MODEL_INSTANT:
        return [f"燃烧剖面             = {MODEL_LABELS[MODEL_INSTANT]}（ΔV 在 t=0 一次给出）"]
    out = [f"燃烧剖面             = {MODEL_LABELS[MODEL_FINITE]}："
           f"{burn.mass_launch:.2f} → {burn.mass_mid:.2f}"
           + (f" → {burn.mass_dry:.2f}" if burn.two_stage else "")
           + f" kg，共 {burn.burn_time_total:.2f} s"]
    out.append(f"  一级               = {burn.force:.0f} N / {burn.time_fire:g} s"
               f"（Isp≈{burn.force * burn.time_fire / (9.81 * (burn.mass_launch - burn.mass_mid)):.1f} s）"
               if burn.mass_launch > burn.mass_mid else "  一级               = —")
    if burn.two_stage:
        out.append(f"  二级               = {burn.force1:.0f} N / {burn.time_fire1:g} s"
                   f"（Isp≈{burn.force1 * burn.time_fire1 / (9.81 * (burn.mass_mid - burn.mass_dry)):.1f} s）")
    return out

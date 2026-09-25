"""阶段机与终止判定的共享决策核心。

标量路径（_ScalarSim）与数组路径（_VectorSim）都只调用这里的函数，
保证两条路径的物理/逻辑完全一致。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import aero, ballistics, burn

PHASE_BOOST, PHASE_LOFT, PHASE_PN = 0, 1, 2

ST_FLYING = 0
ST_HIT = 1
ST_NO_HIT_TIMEOUT = 2
ST_NO_HIT_SLOWDOWN = 3
ST_MISS_OVERSHOOT = 4
ST_MISS_RECEDE = 5
ST_ALREADY_IN_RANGE = 6

STATUS_NAMES = {
    ST_FLYING: "flying",
    ST_HIT: "hit",
    ST_NO_HIT_TIMEOUT: "no_hit_timeout",
    ST_NO_HIT_SLOWDOWN: "no_hit_slowdown",
    ST_MISS_OVERSHOOT: "miss_overshoot",
    ST_MISS_RECEDE: "miss_recede",
    ST_ALREADY_IN_RANGE: "already_in_range",
}

STATUS_LABELS = {
    ST_HIT: "命中",
    ST_NO_HIT_TIMEOUT: "未命中·超时(120s)",
    ST_NO_HIT_SLOWDOWN: "未命中·能量耗尽",
    ST_MISS_OVERSHOOT: "脱靶·飞越目标",
    ST_MISS_RECEDE: "未命中·全程未接近",
    ST_ALREADY_IN_RANGE: "起始即在命中半径内",
    ST_FLYING: "仍在飞行",
}

STATUS_CODES = (
    ST_HIT,
    ST_NO_HIT_TIMEOUT,
    ST_NO_HIT_SLOWDOWN,
    ST_MISS_OVERSHOOT,
    ST_MISS_RECEDE,
    ST_ALREADY_IN_RANGE,
)


@dataclass
class GuidanceConstants:
    """从配置里抽出的数值常量（避免每条路径各算一遍派生指标）。"""

    boost_delay: float
    theta_loft: float
    k_loft: float
    loft_min_time: float
    loft_rule: str
    loft_target_elevation_deg: float
    loft_target_omega_max_dps: float
    loft_exit_margin: float
    loft_dh_gain_max: float
    loft_time_max: float
    loft_confirm_steps: int
    a_lat_max: float
    tau_tgo: float
    tgo_closing_floor: float
    n_base: float
    hit_radius: float
    overshoot_range: float
    min_closing: float
    v_min: float
    t_life: float
    g: float
    drag_coeff: float  # 0.5 * CxK * drag_base * S_ref / m（legacy 档与瞬时档的全部阻力）
    drag_k: float      # 0.5 * CxK * drag_base * S_ref（质量无关；有限燃烧用它 /m(t)）
    rho0: float
    h_max: float
    # 气动模型（见 aero.py）：aero 只依赖配置，aero_case 依赖本工况的 CxK 与质量
    aero: "aero.AeroParams | None" = None
    aero_case: "aero.AeroCase | None" = None
    # 标准弹的燃烧剖面（burn.py）；None 或 model=="instant" 即旧口径
    burn: "burn.BurnProfile | None" = None
    # 标准弹的制导增益表 ((t_go, gain), ...)；None 即用 ballistics 里的 120C5 默认表
    gain_schedule: tuple | None = None


def _gain_schedule(const: GuidanceConstants):
    return const.gain_schedule if const.gain_schedule else ballistics.GAIN_SCHEDULE_DEFAULT


def update_phase(t, t_loft_end, loft_counter, crit_ok, const: GuidanceConstants):
    """阶段机（纯函数，标量/数组同构）。

    t_loft_end 采用 -1.0 表示"高抛尚未结束"（高抛在 t >= boost_delay 才开始，无歧义）。
    高抛退出的两条闸门：
      1) 已进入高抛且持续至少 loft_min_time（防止 t=boost_delay 时 gamma≈0<=LOS≈0 立即退出）；
      2) 刹车转弯判据成立（见 ballistics.loft_exit_condition），且连续满足 loft_confirm_steps 步。

    返回 (phase, loft_counter_new, t_loft_end_new)
    """
    # 仅当入参是"真正的 Python 标量"时才走标量快路径；numpy 标量（np.float64 是 float 的子类）
    # 一律走数组分支，避免与长度为 1 的状态数组混用而退化为标量返回。
    plain_scalar = isinstance(t, (float, int)) and not isinstance(t, (np.floating, np.integer))
    if not plain_scalar:
        t = np.asarray(t, dtype=np.float64)
        t_loft_end = np.asarray(t_loft_end, dtype=np.float64)
        loft_zone = (t >= const.boost_delay) & (t_loft_end < 0.0)
        mature = loft_zone & (t >= const.boost_delay + const.loft_min_time)
        counter = np.where(mature & crit_ok, np.asarray(loft_counter) + 1, 0).astype(np.int16)
        exited = mature & (counter >= const.loft_confirm_steps)
        t_loft_end_new = np.where(exited, t, t_loft_end)
        phase = np.where(t < const.boost_delay, PHASE_BOOST, PHASE_LOFT).astype(np.int8)
        phase = np.where(t_loft_end_new >= 0.0, PHASE_PN, phase).astype(np.int8)
        return phase, counter, t_loft_end_new

    # --- 纯 Python 标量快路径
    loft_zone = (t >= const.boost_delay) and (t_loft_end < 0.0)
    mature = loft_zone and (t >= const.boost_delay + const.loft_min_time)
    counter = (loft_counter + 1) if (mature and crit_ok) else 0
    if mature and counter >= const.loft_confirm_steps:
        t_loft_end = t
    if t < const.boost_delay:
        phase = PHASE_BOOST
    elif t_loft_end < 0.0:
        phase = PHASE_LOFT
    else:
        phase = PHASE_PN
    return phase, counter, t_loft_end


def guidance_command_scalar(phase, gamma, v, rng, vc, lam_dot, tgo_prev, const: GuidanceConstants,
                            dt: float):
    """标量制导指令，返回 (a_perp, tgo, k_go, n_eff)。

    ⚠ 已知残差：游戏的高抛目标是**弹体俯仰 θ = loftElevation**，而这里把**航迹角 γ** 顶到 θ_loft，
    θ 反而冲到 θ_loft+α。朴素地改成 `θ_loft − α` 会不稳定（`k_loft·v` 与 α 的反馈回路增益 >1，
    实测 α 在 0.3°~27° 之间振荡）；正确的修法是隐式解
    `a = k_loft·Δθ·v / (1 + k_loft·(k_alpha·μ/q)·v)`，留待下一阶段（AERO_PLAN §17.5）。
    """
    tgo_raw = ballistics.tgo_from_range_s(rng, vc, const.tgo_closing_floor)
    alpha = dt / (dt + const.tau_tgo)
    tgo = alpha * tgo_raw + (1.0 - alpha) * tgo_prev
    k_go = ballistics.gain_schedule_s(tgo, _gain_schedule(const))
    n_eff = const.n_base * k_go
    a_pn = n_eff * max(vc, 0.0) * lam_dot
    a_pn = min(max(a_pn, -const.a_lat_max), const.a_lat_max)
    if phase == PHASE_LOFT:
        cmd = const.k_loft * (const.theta_loft - gamma) * v
        a_perp = min(max(cmd, -const.a_lat_max), const.a_lat_max)
    else:
        a_perp = a_pn
    return a_perp, tgo, k_go, n_eff


def guidance_command_array(phase, gamma, v, rng, vc, lam_dot, tgo_prev, const: GuidanceConstants,
                           dt: float):
    """数组制导指令，返回 (a_perp, tgo, k_go, n_eff)（与标量版同式，含 θ 目标修正）。"""
    tgo_raw = ballistics.tgo_from_range(rng, vc, const.tgo_closing_floor)
    alpha = dt / (dt + const.tau_tgo)
    tgo = alpha * tgo_raw + (1.0 - alpha) * tgo_prev
    k_go = ballistics.gain_schedule(tgo, _gain_schedule(const))
    n_eff = const.n_base * k_go
    a_pn = ballistics.pn_command(n_eff, np.maximum(vc, 0.0), lam_dot, const.a_lat_max)
    cmd = const.k_loft * (const.theta_loft - gamma) * v
    a_loft = np.clip(cmd, -const.a_lat_max, const.a_lat_max)
    a_perp = np.where(phase == PHASE_LOFT, a_loft, a_pn)
    return a_perp, tgo, k_go, n_eff


def evaluate_termination(
    *,
    hit_now: bool,
    t_next: float,
    v: float,
    rng: float,
    vc: float,
    vc_ever_pos: bool,
    const: GuidanceConstants,
) -> int:
    """终止判定（纯函数）：返回 ST_*；仍在飞返回 ST_FLYING。

    优先级：命中 > 超时 > 能量耗尽 > 全程未接近 > 飞越脱靶。
    """
    if hit_now:
        return ST_HIT
    if t_next >= const.t_life:
        return ST_NO_HIT_TIMEOUT
    if v < const.v_min:
        return ST_NO_HIT_SLOWDOWN
    if not vc_ever_pos:
        return ST_MISS_RECEDE
    if vc < 0.0 and rng > const.overshoot_range:
        return ST_MISS_OVERSHOOT
    return ST_FLYING

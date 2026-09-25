"""弹道与制导纯函数集合（单工况标量路径与批量数组路径共用，避免两套物理逻辑）。

约定：全部 SI；角度内部用弧度，仅在输入/输出层转度。
x 轴指向目标初始方向为正，h 轴向上为正；速度方向角 gamma 抬头为正，法向 n = (-sin g, cos g)。

本模块提供两组同语义实现：
  * 数组版（np）：range_and_los / los_rate / closing_speed / gain_schedule / pn_command ...
  * 标量版（math，无 numpy 开销）：range_and_los_s / los_rate_s / closing_speed_s ...
两者必须保持一致，并由 tests/test_ballistics.py 做等价性校验。
"""

from __future__ import annotations

import math

import numpy as np

# --------------------------------------------------------------------------- 视线几何（数组版）


def range_and_los(mx, mh, tx, th):
    """相对位置 → (视线距离 range, 视线角 lambda)。lambda = atan2(th-mh, tx-mx)。"""
    dx = tx - mx
    dh = th - mh
    rng = np.sqrt(dx * dx + dh * dh)
    lam = np.arctan2(dh, dx)
    return rng, lam


def los_rate(dx, dh, dvx, dvh, eps: float = 1e-6):
    """视线角速率解析式 lambda_dot = (dx*dvh - dh*dvx) / (dx^2 + dh^2)。

    分母下限 eps 防止 range→0 时发散。
    """
    dx = np.asarray(dx, dtype=float)
    dh = np.asarray(dh, dtype=float)
    num = dx * np.asarray(dvh, dtype=float) - dh * np.asarray(dvx, dtype=float)
    den = np.maximum(dx * dx + dh * dh, eps)
    return num / den


def closing_speed(dx, dh, dvx, dvh):
    """接近速度 Vc = -d(range)/dt = -(r_hat · v_rel)，>0 表示正在接近。"""
    rng = np.sqrt(dx * dx + dh * dh)
    return -(dx * dvx + dh * dvh) / np.maximum(rng, 1e-6)


# --------------------------------------------------------------------------- 视线几何（标量版）


def range_and_los_s(mx, mh, tx, th):
    dx = tx - mx
    dh = th - mh
    return math.sqrt(dx * dx + dh * dh), math.atan2(dh, dx)


def los_rate_s(dx, dh, dvx, dvh, eps: float = 1e-6):
    den = dx * dx + dh * dh
    if den < eps:
        den = eps
    return (dx * dvh - dh * dvx) / den


def closing_speed_s(dx, dh, dvx, dvh):
    rng = math.sqrt(dx * dx + dh * dh)
    if rng < 1e-6:
        rng = 1e-6
    return -(dx * dvx + dh * dvh) / rng


# --------------------------------------------------------------------------- 导引比动态解锁

# AIM-120C5 guidanceAutopilot 的 timeToHitToGain{0,1,2}（us_aim_120c_5.blkx）
GAIN_SCHEDULE_DEFAULT = ((10.0, 1.0), (25.0, 0.8), (50.0, 0.5))


def gain_schedule(time_to_go, schedule=GAIN_SCHEDULE_DEFAULT):
    """按剩余命中时间 T_go 分段线性给出增益 K_go ∈ [0.5, 1.0]。

    10 s 以下恒 1.0（末段完全解锁）；10→25 s 线性 1.0→0.8；25→50 s 线性 0.8→0.5；
    50 s 以上保持 0.5（不外推，避免非正增益）。
    数组版与标量版共用同一条分段线性规则。
    """
    ts = [p[0] for p in schedule]
    gs = [p[1] for p in schedule]
    t = np.asarray(time_to_go, dtype=float)
    return np.interp(t, ts, gs)


def gain_schedule_s(time_to_go, schedule=GAIN_SCHEDULE_DEFAULT):
    t = float(time_to_go)
    ts = [p[0] for p in schedule]
    gs = [p[1] for p in schedule]
    if t <= ts[0]:
        return gs[0]
    if t >= ts[-1]:
        return gs[-1]
    for i in range(len(ts) - 1):
        if t <= ts[i + 1]:
            w = (t - ts[i]) / (ts[i + 1] - ts[i])
            return gs[i] + w * (gs[i + 1] - gs[i])
    return gs[-1]


def tgo_from_range(rng, vc, closing_floor: float = 100.0):
    """T_go 估计：range / max(closing, floor)；closing 非正时用 floor 兜底（给出大 T_go）。"""
    return np.asarray(rng, dtype=float) / np.maximum(np.asarray(vc, dtype=float), closing_floor)


def tgo_from_range_s(rng, vc, closing_floor: float = 100.0):
    return rng / max(vc, closing_floor)


def tgo_analytic(rng, vc, lam_dot):
    """T_go = r / sqrt(Vc^2 + r^2 lambda_dot^2)，用于自洽性对照输出。"""
    rng = np.asarray(rng, dtype=float)
    vc = np.asarray(vc, dtype=float)
    lam_dot = np.asarray(lam_dot, dtype=float)
    return rng / np.sqrt(vc * vc + rng * rng * lam_dot * lam_dot)


def pn_command(n_eff, vc, lam_dot, a_lat_max):
    """比例导引法向加速度指令：a_perp = N_eff * Vc * lambda_dot（含限幅）。"""
    a = np.asarray(n_eff, dtype=float) * np.asarray(vc, dtype=float) * np.asarray(lam_dot, dtype=float)
    return np.clip(a, -a_lat_max, a_lat_max)


def turn_rate(a_perp, v):
    """dgamma/dt = a_perp / V。"""
    return np.asarray(a_perp, dtype=float) / np.maximum(np.asarray(v, dtype=float), 1.0)


def wrap_pi(angle):
    """角度规整到 (-pi, pi]。"""
    return (np.asarray(angle, dtype=float) + np.pi) % (2.0 * np.pi) - np.pi


def wrap_pi_s(angle: float) -> float:
    a = (angle + math.pi) % (2.0 * math.pi) - math.pi
    return a


def loft_exit_game(lam, lam_dot, *, target_elev_deg, omega_max_dps):
    """**游戏的高抛退出判据**（已从原生采样辨识，见 AERO_PLAN §12.3/§14.1）：

        退出 ⇔ |λ̇| ≥ loftTargetOmegaMax[°/s]   或   λ ≤ loftTargetElevation[°]     （先满足者生效）

    λ 是视线仰角（我们模型里为弧度），λ̇ 为视线角速度 [rad/s]。
    PL-12 的阈值 0.5 °/s / −2.25°、120C5 为 0.95 °/s / −3.5°，逐弹从 blk 读。

    与 `loft_exit_condition`（本仓库旧启发式：下沉角/高度增量/时长/下压）互为替代，
    由 `sim.loft_rule` 选择。返回 (是否满足, (判据_ω, 判据_仰角))。
    """
    array_mode = np.ndim(lam) > 0
    lam_deg = np.degrees(lam)
    lam_dot_dps = np.degrees(lam_dot)
    crit_omega = np.abs(lam_dot_dps) >= omega_max_dps
    crit_elev = lam_deg <= target_elev_deg
    if array_mode:
        return crit_omega | crit_elev, (crit_omega, crit_elev)
    return bool(crit_omega or crit_elev), (bool(crit_omega), bool(crit_elev))


def loft_exit_condition(gamma, theta_los, vh, dh_gain, t_loft, *, margin_rad, dh_gain_max, t_loft_max):
    """高抛段的"刹车转弯（bracket over）"判据（任一命中即退出，标量/数组同构）。

    高抛段的速度矢量角被主动恒定保持在 +theta_loft，因此 `gamma` 自身不会下降到视线角，
    必须用"目标已经沉到弹道下方多少 / 已经爬了多高 / 爬了多久"来决定何时压弹体：
      A 目标下沉角： `gamma - theta_los >= margin_rad`（相对视线的额外抬头量超过阈值）
      B 高度增量：   `dh_gain >= dh_gain_max`（爬升已足够）
      C 高抛时长：   `t_loft >= t_loft_max`（防止一直爬升到能量耗尽）
      D 下压兜底：   `vh <= 0`（已经不再爬升）
    并由 decide.update_phase 附加"最短高抛时长"闸门（避免发射瞬间 gamma≈LOS 立即退出）。

    返回 (是否满足, (判据A, B, C, D))。
    """
    array_mode = np.ndim(gamma) > 0
    crit_a = wrap_pi(gamma - theta_los) >= margin_rad
    crit_b = np.asarray(dh_gain) >= dh_gain_max
    crit_c = np.asarray(t_loft) >= t_loft_max
    crit_d = np.asarray(vh) <= 0.0
    if array_mode:
        crits = (crit_a, crit_b, crit_c, crit_d)
        return crit_a | crit_b | crit_c | crit_d, crits
    crits = (bool(crit_a), bool(crit_b), bool(crit_c), bool(crit_d))
    return any(crits), crits

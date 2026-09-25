"""2D 纵向平面点质量弹道仿真（简化模型）。

阶段机（严格按需求）：
  0 BOOST  t ∈ [0, boost_delay)    —— T=0+ 已完成瞬时燃烧，此区间纯弹道滑行（无额外推力）
  1 LOFT   t >= boost_delay        —— 有界速率控制器把速度方向角拉向 +theta_loft
  2 PN     高抛退出之后             —— 比例导引（导引比按 T_go 动态解锁）

动力学（仅零升阻力与重力导致的减速，外加制导带来的法向加速度）：
  dV/dt     = -(0.5*CxK*drag_base*S_ref/m) * rho(h) * V^2 - g*sin(gamma)
  dgamma/dt = a_perp / V ,  |a_perp| <= a_lat_max
总增速 ΔV 已在 T=0+ 一次性加入弹速，之后没有推力项。

不使用诱导阻力、不做升力配平；转弯由法向加速度指令直接给出（阻力不受 a_perp 影响）。

本模块提供两条同构路径，二者共用 decide.py 的阶段机/制导/终止判定：
  * simulate_one：单工况，标量 float 快路径（保留完整弹道记录）
  * simulate_batch：全网格 numpy 数组路径（只保留终止量，便于数千工况扫描）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import atmosphere, ballistics, decide
from .config import MissileConfig, a_drag_coeff, effective_ve_equiv, validate
from . import aero
from .decide import (
    PHASE_BOOST,
    PHASE_LOFT,
    PHASE_PN,
    ST_ALREADY_IN_RANGE,
    ST_FLYING,
    ST_HIT,
    STATUS_LABELS,
    STATUS_NAMES,
    GuidanceConstants,
)

TRACE_FIELDS = ("x", "h", "v", "gamma", "vh", "a_perp", "tgo", "k_go", "n_eff", "rng", "vc", "los", "phase",
                "lam_dot", "alpha_deg")


@dataclass
class Case:
    """单次工况（可覆盖配置中的高抛角/速度/高度/距离/质量）。"""

    dv_total: float
    cxk: float
    theta_loft_deg: float | None = None
    vm0: float | None = None
    vt: float | None = None
    alt: float | None = None
    range0: float | None = None
    target_alt: float | None = None
    # 该工况的弹体质量 [kg]（None = 用配置里的 mass_end）。用于把不同弹按各自真实质量送进同一条弹道。
    mass: float | None = None


@dataclass
class Trace:
    """单工况完整弹道记录（已按 stride 抽样）。"""

    t: np.ndarray
    x: np.ndarray
    h: np.ndarray
    v: np.ndarray
    gamma: np.ndarray
    vh: np.ndarray
    phase: np.ndarray
    a_perp: np.ndarray
    tgo: np.ndarray
    k_go: np.ndarray
    n_eff: np.ndarray
    rng: np.ndarray
    vc: np.ndarray
    los: np.ndarray
    lam_dot: np.ndarray
    # 准定常配平迎角 [度]（由本步 a_perp 反解，截到升力峰值）；legacy/mach 档恒为 0
    alpha_deg: np.ndarray

    def downsample(self, stride: int):
        if stride <= 1:
            return self
        return Trace(**{k: getattr(self, k)[::stride] for k in ("t",) + TRACE_FIELDS})


@dataclass
class SimResult:
    """单工况结果。"""

    case: Case
    status: int
    t_hit: float
    t_end: float
    miss_distance: float
    max_alt: float
    v_impact: float
    terminal_gamma_error_deg: float
    terminal_gamma_error_at_min_range_deg: float
    min_range: float
    min_range_linear: float
    t_loft_end: float
    n_eff_at_min_range: float
    trace: Trace | None = None
    extras: dict = field(default_factory=dict)

    @property
    def status_name(self) -> str:
        return STATUS_NAMES[self.status]

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def hit(self) -> bool:
        return self.status == ST_HIT


# --------------------------------------------------------------------------- 公共初始化


def build_constants(cfg: MissileConfig, cxk: float, theta_loft_deg: float | None = None,
                    mass: float | None = None) -> GuidanceConstants:
    s = cfg.sim
    m_case = cfg.mass.mass_end if mass is None else float(mass)
    return GuidanceConstants(
        boost_delay=s.boost_delay,
        theta_loft=math.radians(s.theta_loft_deg if theta_loft_deg is None else theta_loft_deg),
        k_loft=s.k_loft,
        loft_min_time=s.loft_min_time,
        loft_exit_margin=math.radians(s.loft_exit_margin_deg),
        loft_dh_gain_max=s.loft_dh_gain_max,
        loft_time_max=s.loft_time_max,
        loft_confirm_steps=int(s.loft_confirm_steps),
        a_lat_max=s.a_lat_max_g * cfg.atmosphere.g,
        tau_tgo=s.tau_tgo,
        tgo_closing_floor=s.tgo_closing_floor,
        n_base=s.n_base,
        hit_radius=s.hit_radius,
        overshoot_range=s.overshoot_range,
        min_closing=s.min_closing,
        v_min=s.v_min,
        t_life=s.t_life,
        g=cfg.atmosphere.g,
        drag_coeff=a_drag_coeff(cfg, cxk=cxk, mass=mass),
        rho0=atmosphere.calibrated_rho0(cfg.atmosphere.P0, cfg.atmosphere.T0),
        h_max=cfg.atmosphere.h_max,
        aero=aero.params_from_config(cfg),
        # 注意：批量路径用 build_constants(cfg, 0.0) 构造，此处的 aero_case 在批量里不用
        # （批量按工况另建数组，见 simulate_batch）——改这里不会影响批量结果。
        aero_case=aero.case_params(cfg, cxk, m_case),
    )


def _validate_loft(cfg: MissileConfig, theta_loft_deg: float | None) -> None:
    if theta_loft_deg is not None and not (0.0 <= theta_loft_deg < 40.0):
        raise ValueError(f"高抛角必须在 [0, 40) 度范围内，收到 {theta_loft_deg}")


# --------------------------------------------------------------------------- 标量快路径


class _ScalarSim:
    """单工况标量仿真（纯 float 运算，避免 numpy 长度-1 数组的开销）。"""

    def __init__(self, cfg: MissileConfig, case: Case, record_trace: bool = True, stride: int = 20):
        validate(cfg)
        _validate_loft(cfg, case.theta_loft_deg)
        scen = cfg.scenario
        self.cfg = cfg
        self.case = case
        self.mass = cfg.mass.mass_end if case.mass is None else float(case.mass)
        if self.mass <= 0.0:
            raise ValueError("工况质量必须为正")
        self.const = build_constants(cfg, case.cxk, case.theta_loft_deg, mass=self.mass)
        self.dt = cfg.sim.dt
        self.record = record_trace
        self.stride = max(1, int(stride))

        self.vt = scen.vt if case.vt is None else case.vt
        self.alt = scen.alt if case.alt is None else case.alt
        self.range0 = scen.range if case.range0 is None else case.range0
        if case.target_alt is not None:
            self.target_alt = case.target_alt
        elif scen.target_alt is not None:
            self.target_alt = scen.target_alt
        else:
            self.target_alt = self.alt
        vm0 = scen.vm0 if case.vm0 is None else case.vm0

        self.t = 0.0
        self.x = 0.0
        self.h = self.alt
        self.v = vm0 + case.dv_total
        self.gamma = 0.0
        self.prev_gamma = 0.0
        self.tx0 = self.range0
        self.th = self.target_alt
        self.tx = self.tx0

        c = self.const
        self.rng, self.los = ballistics.range_and_los_s(self.x, self.h, self.tx, self.th)
        self.vc = 0.0
        self.vc_ever_pos = False
        self.lam_dot = 0.0
        self.tgo = self.rng / max(c.tgo_closing_floor, 1e-9)
        self.k_go = 1.0
        self.n_eff = c.n_base
        self.a_perp = 0.0
        self.alpha_deg = 0.0
        self.vh = 0.0
        self.max_alt = self.h
        self.min_range = self.rng
        self.min_range_lin = self.rng
        self.term_gamma_err = 0.0
        self.term_gamma_err_at_min = 0.0
        self.n_at_min_range = c.n_base
        self.phase = PHASE_BOOST
        self.loft_cnt = 0
        self.t_loft_end = -1.0
        self.t_hit = float("nan")
        self.t_end = 0.0
        self.status = ST_FLYING if self.rng > c.hit_radius else ST_ALREADY_IN_RANGE
        if self.status == ST_ALREADY_IN_RANGE:
            self.t_hit = 0.0
        self.rec = {k: [] for k in ("t",) + TRACE_FIELDS} if record_trace else None

    # -------------------------------------------------------------- 物理
    def _accel(self, h, v, gamma):
        """纵向加速度 (dV/dt, dgamma/dt)。阻力按 aero 档位展开（见 aero.py）。

        legacy 档：D = q·S_ref·CxK·drag_base（与旧口径逐位相同）。
        mach/full：再乘 f(M)；full 另加诱导阻力 Da。
        """
        c = self.const
        a = c.aero
        rho = float(atmosphere.density(h, c.rho0, c.h_max)) if h > 0.0 else c.rho0
        v2 = v * v
        a_perp = self.a_perp
        if a.model == aero.MODEL_LEGACY:
            decel = c.drag_coeff * rho * v2
        else:
            q = 0.5 * rho * v2
            M = aero.mach_s(v, h)
            decel = c.drag_coeff * aero.f_mach_s(M) * rho * v2
            if a.model == aero.MODEL_FULL:
                if a.clip_lift_peak:
                    cap = q * c.aero_case.a_peak_per_q
                    if a_perp > cap:
                        a_perp = cap
                    elif a_perp < -cap:
                        a_perp = -cap
                f_coef = aero.F_mach_s(M) if a.use_cxi_mach else 1.0
                decel += aero.induced_decel_s(a, c.aero_case, q, a_perp, f_coef)
        return -decel - c.g * math.sin(gamma), a_perp / max(v, 1.0)

    def _alpha_deg(self) -> float:
        """本步准定常配平迎角 [度]（记录用）。"""
        a = self.const.aero
        if a is None or a.model < aero.MODEL_FULL:
            return 0.0
        c = self.const
        rho = float(atmosphere.density(self.h, c.rho0, c.h_max)) if self.h > 0.0 else c.rho0
        return aero.alpha_deg_s(a, c.aero_case, 0.5 * rho * self.v * self.v, self.a_perp)

    def _rk4(self):
        dt = self.dt
        x, h, v, gm = self.x, self.h, self.v, self.gamma
        k1v, k1g = self._accel(h, v, gm)

        x2 = x + 0.5 * dt * v * math.cos(gm)
        h2 = h + 0.5 * dt * v * math.sin(gm)
        v2 = v + 0.5 * dt * k1v
        g2 = gm + 0.5 * dt * k1g
        k2v, k2g = self._accel(h2, v2, g2)

        x3 = x + 0.5 * dt * v2 * math.cos(g2)
        h3 = h + 0.5 * dt * v2 * math.sin(g2)
        v3 = v + 0.5 * dt * k2v
        g3 = gm + 0.5 * dt * k2g
        k3v, k3g = self._accel(h3, v3, g3)

        x4 = x + dt * v3 * math.cos(g3)
        h4 = h + dt * v3 * math.sin(g3)
        v4 = v + dt * k3v
        g4 = gm + dt * k3g
        k4v, k4g = self._accel(h4, v4, g4)

        self.x = x + dt / 6.0 * (
            v * math.cos(gm) + 2.0 * v2 * math.cos(g2) + 2.0 * v3 * math.cos(g3) + v4 * math.cos(g4)
        )
        self.h = h + dt / 6.0 * (
            v * math.sin(gm) + 2.0 * v2 * math.sin(g2) + 2.0 * v3 * math.sin(g3) + v4 * math.sin(g4)
        )
        self.v = max(v + dt / 6.0 * (k1v + 2.0 * k2v + 2.0 * k3v + k4v), 1.0)
        self.gamma = gm + dt / 6.0 * (k1g + 2.0 * k2g + 2.0 * k3g + k4g)

    # -------------------------------------------------------------- 主循环
    def run(self) -> SimResult:
        dt = self.dt
        c = self.const
        dec = decide

        for _ in range(int(math.ceil(c.t_life / dt))):
            if self.status != ST_FLYING:
                break
            t = self.t

            # 阶段机（用上一步积分得到的 vh 判定高抛退出）
            _, theta_los = ballistics.range_and_los_s(self.x, self.h, self.tx, self.th)
            crit_ok, _ = ballistics.loft_exit_condition(
                self.gamma,
                theta_los,
                self.vh,
                self.h - self.alt,
                (t - c.boost_delay) if self.phase == PHASE_LOFT else 0.0,
                margin_rad=c.loft_exit_margin,
                dh_gain_max=c.loft_dh_gain_max,
                t_loft_max=c.loft_time_max,
            )
            self.phase, self.loft_cnt, self.t_loft_end = dec.update_phase(
                t, self.t_loft_end, self.loft_cnt, crit_ok, c
            )

            if self.rec is not None:
                self._record(t)

            # 制导
            self.a_perp, self.tgo, self.k_go, self.n_eff = dec.guidance_command_scalar(
                self.phase, self.gamma, self.v, self.rng, self.vc, self.lam_dot, self.tgo, c, dt
            )

            # 积分
            prev_rng = self.rng
            prev_los = self.los
            self.prev_gamma = self.gamma
            self._rk4()
            t_next = t + dt

            # 目标推进与几何量（积分后用新状态评估）
            self.tx = self.tx0 + self.vt * t_next
            self.rng, self.los = ballistics.range_and_los_s(self.x, self.h, self.tx, self.th)
            dx = self.tx - self.x
            dh = self.th - self.h
            dvx = self.vt - self.v * math.cos(self.gamma)
            dvh = -self.v * math.sin(self.gamma)
            self.lam_dot = ballistics.los_rate_s(dx, dh, dvx, dvh)
            self.vc = ballistics.closing_speed_s(dx, dh, dvx, dvh)
            if self.vc > c.min_closing:
                self.vc_ever_pos = True

            self.vh = 0.0 if self.phase == PHASE_BOOST else self.v * math.sin(self.gamma)
            if self.h > self.max_alt:
                self.max_alt = self.h

            hit_now = self.rng <= c.hit_radius
            if hit_now:
                span = prev_rng - self.rng
                frac = (prev_rng - c.hit_radius) / span if span > 1e-12 else 0.0
                self.t_hit = t + min(max(frac, 0.0), 1.0) * dt
            if self.rng < self.min_range:
                self.min_range = self.rng
                self.term_gamma_err_at_min = _heading_error(self.gamma, self.los)
                self.n_at_min_range = self.n_eff
            # 步内最接近距离（线性近似）：min(r_prev, r_now, 顶点)；对匀接近运动是精确值
            r_perp = None
            span = prev_rng - self.rng
            if span > 1e-9:
                r_perp = abs(prev_rng * self.rng * math.sin(self.los - prev_los)) / span
                r_min_step = min(prev_rng, self.rng, r_perp)
                if r_min_step < self.min_range_lin:
                    self.min_range_lin = r_min_step
                    # 最近点处的航向误差：按到最近点的距离比例在两步之间插值
                    frac = (prev_rng - r_min_step) / span if span > 1e-9 else 0.0
                    frac = min(max(frac, 0.0), 1.0)
                    lam_at_min = prev_los + frac * (self.los - prev_los)
                    gam_at_min = self.prev_gamma + frac * (self.gamma - self.prev_gamma)
                    self.term_gamma_err_at_min = _heading_error(gam_at_min, lam_at_min)
            else:
                if self.rng < self.min_range_lin:
                    self.min_range_lin = self.rng
                    self.term_gamma_err_at_min = _heading_error(self.gamma, self.los)

            self.term_gamma_err = _heading_error(self.gamma, self.los)
            self.status = dec.evaluate_termination(
                hit_now=hit_now,
                t_next=t_next,
                v=self.v,
                rng=self.rng,
                vc=self.vc,
                vc_ever_pos=self.vc_ever_pos,
                const=c,
            )
            self.t = t_next
            self.t_end = t_next

        # 兜底：正常应在上一步判为超时，这里防止因浮点边界留下 ST_FLYING
        if self.status == ST_FLYING:
            self.status = decide.ST_NO_HIT_TIMEOUT
            self.t_end = min(self.t, c.t_life)

        trace = None
        if self.rec is not None:
            trace = Trace(**{k: np.asarray(v, dtype=float) for k, v in self.rec.items()})
            trace.phase = trace.phase.astype(int)
            if self.stride > 1:
                trace = trace.downsample(self.stride)
        st = self.status
        if st == ST_HIT:
            t_hit, miss = self.t_hit, 0.0
        elif st == ST_ALREADY_IN_RANGE:
            t_hit, miss = 0.0, self.min_range
        else:
            t_hit, miss = float("nan"), self.min_range
        return SimResult(
            case=self.case,
            status=st,
            t_hit=t_hit,
            t_end=self.t_end,
            miss_distance=miss,
            max_alt=self.max_alt,
            v_impact=self.v,
            terminal_gamma_error_deg=math.degrees(self.term_gamma_err),
            terminal_gamma_error_at_min_range_deg=math.degrees(self.term_gamma_err_at_min),
            min_range=self.min_range,
            min_range_linear=self.min_range_lin,
            t_loft_end=self.t_loft_end,
            n_eff_at_min_range=self.n_at_min_range,
            trace=trace,
        )

    def _record(self, t: float):
        self.alpha_deg = self._alpha_deg()
        self.rec["t"].append(t)
        for k in TRACE_FIELDS:
            self.rec[k].append(getattr(self, k))


def _heading_error(gamma: float, los: float) -> float:
    return ballistics.wrap_pi_s(gamma - los)


def simulate_one(cfg: MissileConfig, case: Case, record_trace: bool = True, stride: int = 20) -> SimResult:
    """单工况仿真（标量路径）。"""
    return _ScalarSim(cfg, case, record_trace=record_trace, stride=stride).run()


# --------------------------------------------------------------------------- 数组批量路径


@dataclass
class BatchResult:
    """全网格批量仿真结果（扁平数组，形状 = 工况数）。"""

    dv_total: np.ndarray
    cxk: np.ndarray
    bc: np.ndarray
    theta_loft_deg: float
    vm0: float
    vt: float
    alt: float
    target_alt: float
    range0: float
    status: np.ndarray
    t_hit: np.ndarray
    t_end: np.ndarray
    miss_distance: np.ndarray
    max_alt: np.ndarray
    v_impact: np.ndarray
    terminal_gamma_error_deg: np.ndarray
    min_range: np.ndarray
    min_range_linear: np.ndarray
    t_loft_end: np.ndarray
    isp_equiv: np.ndarray
    mass_ratio: np.ndarray

    @property
    def hit(self) -> np.ndarray:
        return self.status == ST_HIT

    def status_name(self, i: int) -> str:
        return STATUS_NAMES[int(self.status[i])]


def simulate_batch(
    cfg: MissileConfig,
    dv_total,
    cxk,
    theta_loft_deg: float | None = None,
    *,
    vm0: float | None = None,
    vt: float | None = None,
    alt: float | None = None,
    range0: float | None = None,
    target_alt: float | None = None,
    mass=None,
    progress=None,
) -> BatchResult:
    """全网格向量化仿真（同一阶段机/制导/终止判定，见 decide.py）。

    mass：可选的逐工况弹体质量（标量或与 dv_total 同形状的数组）；
          None 时用配置的 mass_end。用于把不同弹按各自真实质量送进同一张图。
    """
    validate(cfg)
    _validate_loft(cfg, theta_loft_deg)
    scen = cfg.scenario
    vm0 = scen.vm0 if vm0 is None else vm0
    vt = scen.vt if vt is None else vt
    alt = scen.alt if alt is None else alt
    range0 = scen.range if range0 is None else range0
    if target_alt is None:
        target_alt = scen.target_alt if scen.target_alt is not None else alt

    dv = np.atleast_1d(np.asarray(dv_total, dtype=float))
    kk = np.atleast_1d(np.asarray(cxk, dtype=float))
    dv, kk = np.broadcast_arrays(dv, kk)
    dv = np.ascontiguousarray(dv, dtype=float).ravel()
    kk = np.ascontiguousarray(kk, dtype=float).ravel()
    n = dv.size
    if mass is None:
        mass_arr = np.full(n, float(cfg.mass.mass_end))
    else:
        mass_arr = np.broadcast_to(np.asarray(mass, dtype=float).ravel(), (n,)).astype(float).copy()
        if np.any(mass_arr <= 0.0):
            raise ValueError("工况质量必须为正")
    const = build_constants(cfg, 0.0, theta_loft_deg)
    dt = float(cfg.sim.dt)
    n_steps = int(math.ceil(const.t_life / dt))
    dec = decide

    # 每个工况的基础阻力系数项 0.5*CxK*drag_base*S_ref/m（与 config.a_drag_coeff 同式，向量化）
    drag_coeff_all = a_drag_coeff(cfg, cxk=kk, mass=mass_arr)
    # 每个工况的诱导阻力系数（仅 full 档使用）
    ac_all = aero.case_params_array(cfg, kk, mass_arr)

    # ---- 全局输出数组
    status_all = np.full(n, ST_FLYING, dtype=np.int8)
    t_hit_all = np.full(n, np.nan)
    t_end_all = np.zeros(n)
    min_range_all = np.full(n, np.inf)
    min_range_lin_all = np.full(n, np.inf)
    max_alt_all = np.zeros(n)
    v_impact_all = np.zeros(n)
    gamma_err_all = np.zeros(n)
    gamma_err_at_min_all = np.zeros(n)
    t_loft_end_all = np.full(n, -1.0)
    n_at_min_all = np.full(n, const.n_base)

    # 初始即在命中半径内的工况直接判 already_in_range（t_hit=0）
    start_rng = np.abs(np.full(n, float(range0)))
    already = start_rng <= const.hit_radius
    status_all[already] = ST_ALREADY_IN_RANGE
    t_hit_all[already] = 0.0

    act_idx = np.nonzero(~already)[0]
    m = act_idx.size
    t = 0.0
    t_next = 0.0

    def _write(jj, st, th, te, mr, ma, vv, ge, tle, nam, mrl, gmin):
        """把（子集）结果写回全局输出数组（闭包捕获上面的 *_all 数组）。"""
        status_all[jj] = st
        t_hit_all[jj] = th
        t_end_all[jj] = te
        min_range_all[jj] = mr
        min_range_lin_all[jj] = mrl
        max_alt_all[jj] = ma
        v_impact_all[jj] = vv
        gamma_err_all[jj] = ge
        t_loft_end_all[jj] = tle
        n_at_min_all[jj] = nam
        gamma_err_at_min_all[jj] = gmin

    if m:
        # ---- 活跃工况的局部状态（长度 m，随淘汰收缩）
        dv_a = dv[act_idx]
        dc_a = drag_coeff_all[act_idx]
        ac_a = aero.AeroCaseArrays(gamma_energy=ac_all.gamma_energy[act_idx],
                                   a_peak_per_q=ac_all.a_peak_per_q[act_idx],
                                   k_alpha=ac_all.k_alpha[act_idx])
        tx0_a = np.full(m, float(range0))
        th_a = np.full(m, float(target_alt))
        x = np.zeros(m)
        h = np.full(m, float(alt))
        v = vm0 + dv_a
        gamma = np.zeros(m)
        rng = np.full(m, float(range0))
        los = np.zeros(m)
        vc = np.zeros(m)
        vc_ever_pos = np.zeros(m, dtype=bool)
        lam_dot = np.zeros(m)
        tgo = rng / max(const.tgo_closing_floor, 1e-9)
        k_go = np.ones(m)
        n_eff = np.full(m, const.n_base)
        a_perp = np.zeros(m)
        vh = np.zeros(m)
        max_alt = h.copy()
        min_range = rng.copy()
        min_range_lin = rng.copy()
        term_gamma_err = np.zeros(m)
        gamma_err_at_min = np.zeros(m)
        n_at_min_range = np.full(m, const.n_base)
        phase = np.full(m, PHASE_BOOST, dtype=np.int8)
        loft_cnt = np.zeros(m, dtype=np.int16)
        t_loft_end = np.full(m, -1.0)
        st = np.full(m, ST_FLYING, dtype=np.int8)
        st_prev = st.copy()
        finished = np.zeros(m, dtype=bool)
        t_terminal = np.zeros(m)
        t_hit = np.full(m, np.nan)
        tx = tx0_a.copy()
        theta_los = np.zeros(m)
        t_since_loft = np.zeros(m)
        prev_los = np.zeros(m)
        prev_gamma = np.zeros(m)
        first_step = np.ones(m, dtype=bool)

        # 需要随淘汰同步收缩的数组（都用 np.asarray 兜住"退化为标量"的情况）
        def _shrink(keep):
            nonlocal dv_a, dc_a, ac_a, tx0_a, th_a, x, h, v, gamma, rng, los, vc, vc_ever_pos
            nonlocal lam_dot, tgo, k_go, n_eff, a_perp, vh, max_alt, min_range, min_range_lin
            nonlocal term_gamma_err, n_at_min_range, phase, loft_cnt, t_loft_end, st, t_hit, tx
            nonlocal gamma_err_at_min
            nonlocal theta_los, t_since_loft, st_prev, finished, t_terminal, prev_los, prev_gamma, first_step
            arr = lambda a: np.asarray(a, dtype=np.float64).reshape(-1)[keep]
            iarr = lambda a: np.asarray(a).reshape(-1)[keep]
            dv_a, dc_a, tx0_a, th_a = arr(dv_a), arr(dc_a), arr(tx0_a), arr(th_a)
            ac_a = aero.AeroCaseArrays(gamma_energy=np.asarray(ac_a.gamma_energy, dtype=np.float64).reshape(-1)[keep],
                                       a_peak_per_q=np.asarray(ac_a.a_peak_per_q, dtype=np.float64).reshape(-1)[keep],
                                       k_alpha=np.asarray(ac_a.k_alpha, dtype=np.float64).reshape(-1)[keep])
            x, h, v, gamma = arr(x), arr(h), arr(v), arr(gamma)
            rng, los, vc, lam_dot = arr(rng), arr(los), arr(vc), arr(lam_dot)
            vc_ever_pos = np.asarray(vc_ever_pos).reshape(-1)[keep]
            tgo, k_go, n_eff, a_perp = arr(tgo), arr(k_go), arr(n_eff), arr(a_perp)
            vh, max_alt, min_range = arr(vh), arr(max_alt), arr(min_range)
            min_range_lin = arr(min_range_lin)
            term_gamma_err, n_at_min_range = arr(term_gamma_err), arr(n_at_min_range)
            gamma_err_at_min = arr(gamma_err_at_min)
            phase, loft_cnt, t_loft_end = iarr(phase), iarr(loft_cnt), arr(t_loft_end)
            st, t_hit, tx = iarr(st), arr(t_hit), arr(tx)
            st_prev, finished = iarr(st_prev), np.asarray(finished).reshape(-1)[keep]
            t_terminal = arr(t_terminal)
            theta_los, t_since_loft = arr(theta_los), arr(t_since_loft)
            prev_los, prev_gamma = arr(prev_los), arr(prev_gamma)
            first_step = np.asarray(first_step).reshape(-1)[keep]

        prune_every = 200
        for step in range(n_steps):
            if m == 0:
                break
            t = step * dt
            t_next = t + dt

            # ---- 制导（用上一步积分得到的几何量；阶段机在本步末尾更新）
            a_perp, tgo, k_go, n_eff = dec.guidance_command_array(
                phase, gamma, v, rng, vc, lam_dot, tgo, const, dt
            )

            # ---- RK4（与标量路径同构）
            k1v, k1g = _accel_arr(h, v, gamma, a_perp, dc_a, ac_a, const)
            x2 = x + 0.5 * dt * v * np.cos(gamma)
            h2 = h + 0.5 * dt * v * np.sin(gamma)
            v2 = v + 0.5 * dt * k1v
            g2 = gamma + 0.5 * dt * k1g
            k2v, k2g = _accel_arr(h2, v2, g2, a_perp, dc_a, ac_a, const)
            x3 = x + 0.5 * dt * v2 * np.cos(g2)
            h3 = h + 0.5 * dt * v2 * np.sin(g2)
            v3 = v + 0.5 * dt * k2v
            g3 = gamma + 0.5 * dt * k2g
            k3v, k3g = _accel_arr(h3, v3, g3, a_perp, dc_a, ac_a, const)
            x4 = x + dt * v3 * np.cos(g3)
            h4 = h + dt * v3 * np.sin(g3)
            v4 = v + dt * k3v
            g4 = gamma + dt * k3g
            k4v, k4g = _accel_arr(h4, v4, g4, a_perp, dc_a, ac_a, const)

            x = x + dt / 6.0 * (v * np.cos(gamma) + 2 * v2 * np.cos(g2) + 2 * v3 * np.cos(g3) + v4 * np.cos(g4))
            h = h + dt / 6.0 * (v * np.sin(gamma) + 2 * v2 * np.sin(g2) + 2 * v3 * np.sin(g3) + v4 * np.sin(g4))
            v = np.maximum(v + dt / 6.0 * (k1v + 2 * k2v + 2 * k3v + k4v), 1.0)
            gamma = gamma + dt / 6.0 * (k1g + 2 * k2g + 2 * k3g + k4g)

            # ---- 位置/几何更新（积分后用新状态评估）
            prev_rng = rng.copy()
            prev_los = los.copy()
            prev_gamma = gamma.copy()
            first_step = np.zeros_like(first_step)
            tx = tx0_a + vt * t_next
            dx = tx - x
            dh = th_a - h
            rng = np.sqrt(dx * dx + dh * dh)
            los = np.arctan2(dh, dx)
            dvx = vt - v * np.cos(gamma)
            dvh = -v * np.sin(gamma)
            lam_dot = ballistics.los_rate(dx, dh, dvx, dvh)
            vc = ballistics.closing_speed(dx, dh, dvx, dvh)
            vc_ever_pos = vc_ever_pos | (vc > const.min_closing)

            vh = np.where(np.asarray(phase) == PHASE_BOOST, 0.0, v * np.sin(gamma))
            max_alt = np.maximum(max_alt, h)

            # ---- 命中 / 脱靶 / 终止
            # 命中时刻：步首距离 r_prev、步末距离 r_now，穿越引信半径 r_hit 的时刻按比例内插。
            # 等价于 t + frac*dt，其中 frac = (r_prev - r_hit)/(r_prev - r_now) = (r_prev - r_hit)/span，
            # 用 t_next - (r_now - r_hit)/span*dt 写成更稳定的形式。
            hit_now = rng <= const.hit_radius
            span = prev_rng - rng
            frac = np.where(span > 1e-12, (prev_rng - const.hit_radius) / np.maximum(span, 1e-12), 1.0)
            frac = np.clip(frac, 0.0, 1.0)
            t_hit = np.where(hit_now, t + frac * dt, t_hit)
            term_gamma_err = ballistics.wrap_pi(gamma - los)            # t_hit 只在真正穿越引信半径的那一步写入（命中时刻由该步内插得到）
            t_hit = np.where(hit_now, t + frac * dt, t_hit)
            term_gamma_err = ballistics.wrap_pi(gamma - los)
            n_at_min_range = np.where(rng < min_range, n_eff, n_at_min_range)
            min_range = np.minimum(min_range, rng)
            # 步内最接近距离（线性近似，对匀接近运动精确）+ 该点处的航向误差
            # 第一步用步首真实距离 rng0；不能沿用初始化的 rng（那是 t=0 之前的值，会让 span<=0）
            r_prev_eff = np.where(first_step, float(range0), prev_rng)
            span = r_prev_eff - rng
            r_perp = np.where(span > 1e-9, np.abs(r_prev_eff * rng * np.sin(los - prev_los)) / np.maximum(span, 1e-12), np.inf)
            r_min_step = np.minimum(np.minimum(r_prev_eff, rng), r_perp)
            better = r_min_step < min_range_lin
            frac_at_min = np.clip((r_prev_eff - r_min_step) / np.maximum(span, 1e-12), 0.0, 1.0)
            lam_at_min = np.where(span > 1e-9, prev_los + frac_at_min * (los - prev_los), los)
            gam_at_min = np.where(span > 1e-9, prev_gamma + frac_at_min * (gamma - prev_gamma), gamma)
            gamma_err_at_min = np.where(better, ballistics.wrap_pi(gam_at_min - lam_at_min), gamma_err_at_min)
            min_range_lin = np.minimum(min_range_lin, r_min_step)
            first_step = np.zeros_like(first_step)

            st = np.full(m, ST_FLYING, dtype=np.int8)
            st = np.where(t_next >= const.t_life, dec.ST_NO_HIT_TIMEOUT, st)
            st = np.where(v < const.v_min, dec.ST_NO_HIT_SLOWDOWN, st)
            st = np.where(~vc_ever_pos, dec.ST_MISS_RECEDE, st)
            st = np.where((vc < 0.0) & (rng > const.overshoot_range), dec.ST_MISS_OVERSHOOT, st)
            # 命中优先级最高（与 decide.evaluate_termination 的早退顺序一致）
            st = np.where(hit_now, ST_HIT, st)
            # 终止状态一经写入即冻结：与标量路径"判到即 break"语义一致，
            # 否则命中之后的后续步会把状态覆盖成 miss_overshoot。
            st = np.where(finished, st_prev, st)
            t_terminal = np.where((st != ST_FLYING) & (~finished), t_next, t_terminal)
            st_prev = st
            finished = finished | (st != ST_FLYING)

            # ---- 阶段机（用本步积分得到的 vh 判定高抛退出）
            theta_los = np.arctan2(th_a - h, tx - x)
            t_since_loft = np.where(np.asarray(phase) == PHASE_LOFT, t_next - const.boost_delay, 0.0)
            crit, _ = ballistics.loft_exit_condition(
                gamma, theta_los, vh, h - alt, t_since_loft,
                margin_rad=const.loft_exit_margin,
                dh_gain_max=const.loft_dh_gain_max,
                t_loft_max=const.loft_time_max,
            )
            phase, loft_cnt, t_loft_end = dec.update_phase(
                np.float64(t_next), t_loft_end, loft_cnt, crit, const
            )

            # ---- 定期淘汰已终止工况（同时把结果写回全局数组）
            if step % prune_every == prune_every - 1:
                done_mask = np.asarray(st).reshape(-1) != ST_FLYING
                if done_mask.any():
                    jj = act_idx[done_mask]
                    flat = lambda a: np.asarray(a, dtype=np.float64).reshape(-1)
                    _write(jj, np.asarray(st).reshape(-1)[done_mask], flat(t_hit)[done_mask],
                           flat(t_terminal)[done_mask], flat(min_range)[done_mask],
                           flat(max_alt)[done_mask], flat(v)[done_mask], flat(term_gamma_err)[done_mask],
                           flat(t_loft_end)[done_mask], flat(n_at_min_range)[done_mask],
                           flat(min_range_lin)[done_mask], flat(gamma_err_at_min)[done_mask])
                    keep = ~done_mask
                    act_idx = act_idx[keep]
                    _shrink(keep)
                    m = act_idx.size
                    if progress is not None:
                        progress(step, n_steps, int(m))

        # ---- 收尾：仍在飞的（只可能是到达 t_life 上限）按超时写回
        if m:
            _write(act_idx, np.full(m, dec.ST_NO_HIT_TIMEOUT, dtype=np.int8), np.asarray(t_hit).reshape(-1),
                   np.full(m, min(t_next, const.t_life)), np.asarray(min_range).reshape(-1),
                   np.asarray(max_alt).reshape(-1), np.asarray(v).reshape(-1),
                   np.asarray(term_gamma_err).reshape(-1), np.asarray(t_loft_end).reshape(-1),
                   np.asarray(n_at_min_range).reshape(-1), np.asarray(min_range_lin).reshape(-1),
                   np.asarray(gamma_err_at_min).reshape(-1))
    return BatchResult(
        dv_total=dv,
        cxk=kk,
        bc=bc_from_cxk(cfg, kk),
        theta_loft_deg=cfg.sim.theta_loft_deg if theta_loft_deg is None else theta_loft_deg,
        vm0=float(vm0),
        vt=float(vt),
        alt=float(alt),
        target_alt=float(target_alt),
        range0=float(range0),
        status=status_all,
        t_hit=t_hit_all,
        t_end=t_end_all,
        miss_distance=np.where(status_all == ST_HIT, 0.0, min_range_all),
        max_alt=max_alt_all,
        v_impact=v_impact_all,
        terminal_gamma_error_deg=np.degrees(gamma_err_at_min_all),
        min_range=min_range_all,
        min_range_linear=min_range_lin_all,
        t_loft_end=t_loft_end_all,
        isp_equiv=dv / 9.80665,
        mass_ratio=np.exp(dv / effective_ve_equiv(cfg)),
    )


def _accel_arr(h, v, gamma, a_perp, drag_coeff, ac, const: GuidanceConstants):
    """数组路径的加速度（与 `_ScalarSim._accel` 同式）。

    `drag_coeff` 与 `ac`（AeroCaseArrays，两条长度 m 的数组）都是每工况量，已按活跃集裁剪。
    """
    a = const.aero
    rho = atmosphere.density(h, const.rho0, const.h_max)
    v2 = v * v
    if a.model == aero.MODEL_LEGACY:
        decel = drag_coeff * rho * v2
    else:
        q = 0.5 * rho * v2
        M = aero.mach(v, h)
        decel = drag_coeff * aero.f_mach(M) * rho * v2
        if a.model == aero.MODEL_FULL:
            if a.clip_lift_peak:
                cap = q * ac.a_peak_per_q
                a_perp = np.clip(a_perp, -cap, cap)
            f_coef = aero.F_mach(M) if a.use_cxi_mach else 1.0
            decel = decel + aero.induced_decel(a, ac, q, a_perp, f_coef)
    dv = -decel - const.g * np.sin(gamma)
    dg = a_perp / np.maximum(v, 1.0)
    return dv, dg


def bc_from_cxk(cfg: MissileConfig, cxk):
    """CxK → 弹道系数 BC（与 config.ballistic_coefficient 同一定义）。"""
    from .config import ballistic_coefficient

    return ballistic_coefficient(cxk, cfg)

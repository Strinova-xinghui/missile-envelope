"""对比标量单工况路径与数组批量路径（应完全一致，用于定位两套实现的偏差）。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from missile_sim import ballistics, decide  # noqa: E402
from missile_sim.config import delta_v_equiv, load_config  # noqa: E402
from missile_sim.sim import Case, _ScalarSim  # noqa: E402


def run_scalar(cfg, steps):
    sim = _ScalarSim(cfg, Case(dv_total=delta_v_equiv(cfg), cxk=cfg.drag.cxk), record_trace=False)
    c = sim.const
    dt = sim.dt
    rows = []
    for step in range(steps):
        if sim.status != 0:
            rows.append((sim.t, sim.x, sim.h, sim.v, sim.gamma, sim.rng, sim.min_range, sim.status, "STOP"))
            break
        t = sim.t
        _, theta_los = ballistics.range_and_los_s(sim.x, sim.h, sim.tx, sim.th)
        crit_ok, _ = ballistics.loft_exit_condition(
            sim.gamma, theta_los, sim.vh, sim.h - sim.alt, (t - c.boost_delay) if sim.phase == 1 else 0.0,
            margin_rad=c.loft_exit_margin, dh_gain_max=c.loft_dh_gain_max, t_loft_max=c.loft_time_max)
        sim.phase, sim.loft_cnt, sim.t_loft_end = decide.update_phase(t, sim.t_loft_end, sim.loft_cnt, crit_ok, c)
        sim.a_perp, sim.tgo, sim.k_go, sim.n_eff = decide.guidance_command_scalar(
            sim.phase, sim.gamma, sim.v, sim.rng, sim.vc, sim.lam_dot, sim.tgo, c, dt)
        prev_rng = sim.rng
        sim._rk4()
        t_next = t + dt
        sim.tx = sim.tx0 + sim.vt * t_next
        sim.rng, sim.los = ballistics.range_and_los_s(sim.x, sim.h, sim.tx, sim.th)
        dx, dh = sim.tx - sim.x, sim.th - sim.h
        dvx = sim.vt - sim.v * math.cos(sim.gamma)
        dvh = -sim.v * math.sin(sim.gamma)
        sim.lam_dot = ballistics.los_rate_s(dx, dh, dvx, dvh)
        sim.vc = ballistics.closing_speed_s(dx, dh, dvx, dvh)
        if sim.vc > c.min_closing:
            sim.vc_ever_pos = True
        sim.vh = 0.0 if sim.phase == 0 else sim.v * math.sin(sim.gamma)
        sim.max_alt = max(sim.max_alt, sim.h)
        hit = sim.rng <= c.hit_radius
        if hit:
            span = prev_rng - sim.rng
            frac = (prev_rng - c.hit_radius) / span if span > 1e-12 else 0.0
            sim.t_hit = t + min(max(frac, 0.0), 1.0) * dt
        if sim.rng < sim.min_range:
            sim.min_range = sim.rng
        sim.status = decide.evaluate_termination(
            hit_now=hit, t_next=t_next, v=sim.v, rng=sim.rng, vc=sim.vc,
            vc_ever_pos=sim.vc_ever_pos, const=c)
        sim.t = t_next
        sim.t_end = t_next
        rows.append((t_next, sim.x, sim.h, sim.v, sim.gamma, sim.rng, sim.min_range, sim.status, ""))
    return rows


def run_vector(cfg, steps):
    """逐步骤重现批量路径（m=1），用于逐项对照。"""
    c = None
    from missile_sim.sim import build_constants

    c = build_constants(cfg, cfg.drag.cxk)
    dt = cfg.sim.dt
    dc = 0.5 * cfg.drag.cxk * cfg.drag.drag_base * (math.pi * (cfg.drag.caliber_m / 2) ** 2) / cfg.mass.mass_end
    m = 1
    alt = cfg.scenario.alt
    vm0 = cfg.scenario.vm0
    vt = cfg.scenario.vt
    r0 = cfg.scenario.range
    dv = delta_v_equiv(cfg)
    x = np.zeros(m); h = np.full(m, alt); v = np.array([vm0 + dv]); gamma = np.zeros(m)
    tx0 = np.full(m, r0); th = np.full(m, alt); tx = tx0.copy()
    rng = np.full(m, r0); los = np.zeros(m); vc = np.zeros(m); vc_ever_pos = np.zeros(m, bool)
    lam_dot = np.zeros(m); tgo = rng / 100.0; n_eff = np.full(m, c.n_base); a_perp = np.zeros(m)
    vh = np.zeros(m); max_alt = h.copy(); min_range = rng.copy(); tge = np.zeros(m); nam = np.full(m, c.n_base)
    phase = np.full(m, 0, np.int8); loft_cnt = np.zeros(m, np.int16); t_loft_end = np.full(m, -1.0)
    st = np.full(m, 0, np.int8); t_hit = np.full(m, np.nan); status = 0
    from missile_sim.sim import _accel_arr

    rows = []
    for step in range(steps):
        if status != 0:
            rows.append((step * dt, float(x[0]), float(h[0]), float(v[0]), float(gamma[0]), float(rng[0]), float(min_range[0]), int(status), "STOP"))
            break
        t = step * dt; t_next = t + dt
        a_perp, tgo, k_go, n_eff = decide.guidance_command_array(phase, gamma, v, rng, vc, lam_dot, tgo, c, dt)
        k1v, k1g = _accel_arr(h, v, gamma, a_perp, dc, c)
        x2 = x + 0.5 * dt * v * np.cos(gamma); h2 = h + 0.5 * dt * v * np.sin(gamma)
        v2 = v + 0.5 * dt * k1v; g2 = gamma + 0.5 * dt * k1g
        k2v, k2g = _accel_arr(h2, v2, g2, a_perp, dc, c)
        x3 = x + 0.5 * dt * v2 * np.cos(g2); h3 = h + 0.5 * dt * v2 * np.sin(g2)
        v3 = v + 0.5 * dt * k2v; g3 = gamma + 0.5 * dt * k2g
        k3v, k3g = _accel_arr(h3, v3, g3, a_perp, dc, c)
        x4 = x + dt * v3 * np.cos(g3); h4 = h + dt * v3 * np.sin(g3)
        v4 = v + dt * k3v; g4 = gamma + dt * k3g
        k4v, k4g = _accel_arr(h4, v4, g4, a_perp, dc, c)
        x = x + dt / 6.0 * (v * np.cos(gamma) + 2 * v2 * np.cos(g2) + 2 * v3 * np.cos(g3) + v4 * np.cos(g4))
        h = h + dt / 6.0 * (v * np.sin(gamma) + 2 * v2 * np.sin(g2) + 2 * v3 * np.sin(g3) + v4 * np.sin(g4))
        v = np.maximum(v + dt / 6.0 * (k1v + 2 * k2v + 2 * k3v + k4v), 1.0)
        gamma = gamma + dt / 6.0 * (k1g + 2 * k2g + 2 * k3g + k4g)
        prev_rng = rng
        tx = tx0 + vt * t_next
        dx = tx - x; dh = th - h
        rng = np.sqrt(dx * dx + dh * dh)
        los = np.arctan2(dh, dx)
        dvx = vt - v * np.cos(gamma); dvh = -v * np.sin(gamma)
        lam_dot = ballistics.los_rate(dx, dh, dvx, dvh)
        vc = ballistics.closing_speed(dx, dh, dvx, dvh)
        vc_ever_pos = vc_ever_pos | (vc > c.min_closing)
        vh = np.where(phase == 0, 0.0, v * np.sin(gamma))
        max_alt = np.maximum(max_alt, h)
        hit_now = rng <= c.hit_radius
        span = prev_rng - rng
        frac = np.where(span > 1e-12, (prev_rng - c.hit_radius) / np.maximum(span, 1e-12), 0.0)
        t_hit = np.where(hit_now, t + np.clip(frac, 0, 1) * dt, np.nan)
        tge = ballistics.wrap_pi(gamma - los)
        nam = np.where(rng < min_range, n_eff, nam)
        min_range = np.minimum(min_range, rng)
        st = np.where(hit_now, 1, np.full(m, 0, np.int8))
        st = np.where(t_next >= c.t_life, 2, st)
        st = np.where(v < c.v_min, 3, st)
        st = np.where(~vc_ever_pos, 5, st)
        st = np.where((vc < 0.0) & (rng > c.overshoot_range), 4, st)
        theta_los = np.arctan2(th - h, tx - x)
        t_since_loft = np.where(phase == 1, t_next - c.boost_delay, 0.0)
        crit, _ = ballistics.loft_exit_condition(gamma, theta_los, vh, h - alt, t_since_loft,
                                                 margin_rad=c.loft_exit_margin,
                                                 dh_gain_max=c.loft_dh_gain_max, t_loft_max=c.loft_time_max)
        phase, loft_cnt, t_loft_end = decide.update_phase(t_next, t_loft_end, loft_cnt, crit, c)
        status = int(st[0]) if not hit_now[0] else 1
        rows.append((t_next, float(x[0]), float(h[0]), float(v[0]), float(gamma[0]), float(rng[0]), float(min_range[0]), status, ""))
    return rows


def main():
    cfg = load_config()
    steps = int(70.0 / cfg.sim.dt)
    a = run_scalar(cfg, steps)
    b = run_vector(cfg, steps)
    n = min(len(a), len(b))
    print(f"scalar rows={len(a)} vector rows={len(b)}")
    print(f"{'t':>8} {'x_s':>10} {'x_v':>10} {'h_s':>9} {'h_v':>9} {'v_s':>8} {'v_v':>8} {'g_s':>8} {'g_v':>8} {'R_s':>9} {'R_v':>9} {'st_s':>5} {'st_v':>5}")
    worst = (0.0, None)
    for i in range(0, n, max(1, n // 40)):
        rs, rv = a[i], b[i]
        print(f"{rs[0]:8.2f} {rs[1]:10.1f} {rv[1]:10.1f} {rs[2]:9.1f} {rv[2]:9.1f} {rs[3]:8.1f} {rv[3]:8.1f} "
              f"{math.degrees(rs[4]):8.3f} {math.degrees(rv[4]):8.3f} {rs[5]:9.2f} {rv[5]:9.2f} {rs[7]:5d} {rv[7]:5d}")
    for i in range(n):
        d = abs(a[i][5] - b[i][5])
        if d > worst[0]:
            worst = (d, i)
    print(f"最大距离差 {worst[0]:.4f} m @ step {worst[1]} (t={a[worst[1]][0]:.3f}s)")
    for i in range(n):
        if abs(a[i][1] - b[i][1]) > 1e-6:
            print(f"首次状态偏差 step={i} t={a[i][0]:.3f}: x_s={a[i][1]:.6f} x_v={b[i][1]:.6f}")
            break


if __name__ == "__main__":
    main()

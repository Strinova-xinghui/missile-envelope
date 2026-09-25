"""在批量路径里打点：确认命中是否被检测、是否被后续状态覆盖。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import math  # noqa: E402

import numpy as np  # noqa: E402

from missile_sim import ballistics, decide  # noqa: E402
from missile_sim.config import cxk_for_bc, load_config  # noqa: E402
from missile_sim.sim import PHASE_BOOST, PHASE_LOFT, ST_FLYING, ST_HIT, _accel_arr, build_constants  # noqa: E402


def main() -> int:
    cfg = load_config()
    c = build_constants(cfg, 0.0)
    dt = float(cfg.sim.dt)
    alt = cfg.scenario.alt
    vm0 = cfg.scenario.vm0
    vt = cfg.scenario.vt
    r0 = cfg.scenario.range
    dv = 1114.0
    cx = float(cxk_for_bc(3624.0, cfg))
    dc = np.array([0.5 * cx * cfg.drag.drag_base * math.pi * (cfg.drag.caliber_m / 2) ** 2 / cfg.mass.mass_end])

    m = 1
    x = np.zeros(m); h = np.full(m, alt); v = np.array([vm0 + dv]); gamma = np.zeros(m)
    tx0 = np.full(m, r0); th = np.full(m, alt); tx = tx0.copy()
    rng = np.full(m, r0); los = np.zeros(m); vc = np.zeros(m); vc_ever_pos = np.zeros(m, bool)
    lam_dot = np.zeros(m); tgo = rng / 100.0; n_eff = np.full(m, c.n_base); a_perp = np.zeros(m)
    vh = np.zeros(m); min_range = rng.copy()
    phase = np.full(m, PHASE_BOOST, dtype=np.int8); loft_cnt = np.zeros(m, dtype=np.int16)
    t_loft_end = np.full(m, -1.0)

    print(f"{'t':>8} {'R':>10} {'Rmin':>9} {'vc':>9} {'gamma':>8} {'st':>3} {'note':>20}")
    for step in range(int(60.0 / dt)):
        t = step * dt
        t_next = t + dt
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
        vh = np.where(phase == PHASE_BOOST, 0.0, v * np.sin(gamma))
        hit_now = rng <= c.hit_radius
        min_range = np.minimum(min_range, rng)
        st = np.full(m, ST_FLYING, dtype=np.int8)
        st = np.where(t_next >= c.t_life, decide.ST_NO_HIT_TIMEOUT, st)
        st = np.where(v < c.v_min, decide.ST_NO_HIT_SLOWDOWN, st)
        st = np.where(~vc_ever_pos, decide.ST_MISS_RECEDE, st)
        st = np.where((vc < 0.0) & (rng > c.overshoot_range), decide.ST_MISS_OVERSHOOT, st)
        st = np.where(hit_now, ST_HIT, st)
        note = ""
        if hit_now[0]:
            note = "HIT_NOW"
        if t > 54.0 and t < 55.5:
            print(f"{t:8.3f} {rng[0]:10.3f} {min_range[0]:9.3f} {vc[0]:9.3f} {math.degrees(gamma[0]):8.3f} "
                  f"{int(st[0]):3d} {note:>20s}")
        if st[0] != ST_FLYING:
            print(f"  -> 结束: t={t_next:.3f} st={int(st[0])} Rmin={min_range[0]:.3f}")
            break
        theta_los = np.arctan2(th - h, tx - x)
        t_since_loft = np.where(phase == PHASE_LOFT, t_next - c.boost_delay, 0.0)
        crit, _ = ballistics.loft_exit_condition(gamma, theta_los, vh, h - alt, t_since_loft,
                                                 margin_rad=c.loft_exit_margin,
                                                 dh_gain_max=c.loft_dh_gain_max, t_loft_max=c.loft_time_max)
        phase, loft_cnt, t_loft_end = decide.update_phase(np.float64(t_next), t_loft_end, loft_cnt, crit, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

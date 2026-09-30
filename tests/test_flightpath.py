# -*- coding: utf-8 -*-
"""目标航路调度的回归测试 —— 每个用例都对应一个**已经真踩过**的坑。

不用求解器（秒级）：这里锁的是"编译出来的东西对不对"，端到端数值在
`docs/MANEUVER-TARGETS.md` §8 有实测记录。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest                                                     # noqa: E402

from missile_sim.flightpath import (G0, PathSchedule, TurnLeg,    # noqa: E402
                                    WeaveLeg, crank_beam)


def integrate_heading(sch, duration_s, dt=0.001):
    """按编译出来的角速度**积分**航向 —— 模拟内核做的事（内核只吃加速度，不认识航向）。"""
    h = math.radians(sch.start_heading_deg)
    t = 0.0
    while t < duration_s:
        _hh, omega = sch.heading_at(t + dt / 2)
        h += omega * dt
        t += dt
    return math.degrees(h) % 360.0


def integrate_accel_heading(sch, duration_s, dt=0.001):
    """按 `maneuvers` 里的**加速度**积分速度方向再取航向 —— 端到端的等价物。"""
    vx, vz = sch.state_at(0.0)[0][0], sch.state_at(0.0)[0][2]
    t = 0.0
    while t < duration_s:
        _v, a = sch.state_at(t + dt / 2)
        vx += a[0] * dt
        vz += a[2] * dt
        t += dt
    return math.degrees(math.atan2(vz, vx)) % 360.0


# ---------------------------------------------------------------- 基本形状

def test_straight_flight_has_no_acceleration():
    sch = PathSchedule(speed_ms=300.0)
    _v, a = sch.state_at(10.0)
    assert max(abs(x) for x in a) == 0.0
    v, _a = sch.state_at(10.0)
    assert v[0] == pytest.approx(-300.0, abs=1e-9)      # heading 180 = 迎面
    assert v[1] == pytest.approx(0.0, abs=1e-9)
    assert v[2] == pytest.approx(0.0, abs=1e-9)


def test_single_turn_reaches_the_commanded_heading():
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(0.0, 110.0, 5.0, "cw"),))
    # 70° @ 5G @ 300 m/s = 1.2217 / 0.16344 = 7.477 s
    assert integrate_heading(sch, 20.0) == pytest.approx(110.0, abs=0.05)
    assert integrate_accel_heading(sch, 20.0) == pytest.approx(110.0, abs=0.05)
    h, w = sch.heading_at(3.0)
    assert w == pytest.approx(-5.0 * G0 / 300.0, rel=1e-12)
    assert math.degrees(h) == pytest.approx(180.0 - 3.0 * w * 180 / math.pi * -1, abs=1e-6)


def test_turn_rate_follows_the_commanded_load_factor():
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(0.0, 90.0, 6.0, "cw"),))
    _v, a = sch.state_at(2.0)
    assert math.hypot(*a) == pytest.approx(6.0 * G0, rel=1e-9)


# ------------------------------------------- 坑 1：腿重叠必须"截断"而不是"叠加"

def test_overlapping_command_truncates_the_previous_turn():
    """crank 还没转完就下达正侧方 —— 实测过的错法是叠加：总转角只剩 70°。

    正确读法：后一条指令在下达时刻切断前一条，然后从当时的航向继续转到新目标。
    这里是 180° → 110°（未完成）→ 90°，总转角 90°。
    """
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(25.0, 110.0, 5.0, "cw"),
                                            TurnLeg(30.23, 90.0, 5.0, "cw")))
    end = integrate_heading(sch, 60.0)
    assert end == pytest.approx(90.0, abs=0.05), f"重叠指令叠加了：航向停在 {end:.2f}° 而不是 90°"
    assert math.degrees(sch.heading_at(30.23 - 1e-9)[0]) < 180.0
    # 截断点之前必须是**同一条**弧（角速度不变），否则就是"跳航向"
    _h1, w1 = sch.heading_at(29.0)
    _h2, w2 = sch.heading_at(29.9)
    assert w1 == w2 == pytest.approx(-5.0 * G0 / 300.0, rel=1e-12)


def test_total_turn_impulse_matches_the_command():
    """角速度积分 = 指令转角，这是"没有把时间算两遍"的判据。"""
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(25.0, 110.0, 5.0, "cw"),
                                            TurnLeg(30.23, 90.0, 5.0, "cw")))
    impulse = 0.0
    for t0, t1, omega, _h0 in sch.table():
        if t1 == float("inf"):
            continue
        impulse += omega * (t1 - t0)
    assert abs(math.degrees(impulse)) == pytest.approx(90.0, abs=0.01)


def test_second_command_after_the_first_completed_is_a_straight_then_turn():
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(0.0, 110.0, 5.0, "cw"),
                                            TurnLeg(20.0, 90.0, 5.0, "cw")))
    assert integrate_heading(sch, 60.0) == pytest.approx(90.0, abs=0.05)
    # 7.477 s 转完，之后到 20 s 是直飞
    assert sch.heading_at(15.0)[1] == 0.0
    assert sch.heading_at(15.0)[0] == pytest.approx(math.radians(110.0), abs=1e-9)


# ------------------------------------------- 坑 2：指令必须按时序

def test_out_of_order_commands_are_rejected():
    with pytest.raises(ValueError, match="按时序"):
        PathSchedule(speed_ms=300.0, legs=(TurnLeg(30.0, 110.0), TurnLeg(10.0, 90.0)))


def test_negative_command_time_is_rejected():
    with pytest.raises(ValueError, match="不能为负"):
        PathSchedule(speed_ms=300.0, legs=(TurnLeg(-1.0, 110.0),))


def test_bad_turn_direction_is_rejected():
    with pytest.raises(ValueError, match="ccw"):
        PathSchedule(speed_ms=300.0, legs=(TurnLeg(0.0, 110.0, turn="left"),)).table()


def test_non_positive_speed_is_rejected():
    with pytest.raises(ValueError, match="速度必须为正"):
        PathSchedule(speed_ms=0.0)


# ------------------------------------------- 坑 3：samples 必须逐字覆盖到 duration_s

def test_samples_cover_duration_exactly():
    sch = PathSchedule(speed_ms=300.0)
    smp = sch.samples(p0=(0.0, 0.0, 0.0), duration_s=150.0, dt=0.05)
    assert smp[0]["time_s"] == 0.0
    assert smp[-1]["time_s"] >= 150.0, "内核会拒收：‘must cover time zero through duration_s’"
    # 时间严格递增（内核按顺序查表）
    times = [s["time_s"] for s in smp]
    assert all(b > a for a, b in zip(times, times[1:]))


def test_samples_odd_duration_is_covered_too():
    for dur in (7.0, 12.345, 97.3):
        smp = PathSchedule(speed_ms=300.0).samples(p0=(0.0, 0.0, 0.0),
                                                   duration_s=dur, dt=0.1)
        assert smp[-1]["time_s"] >= dur
        assert smp[-1]["time_s"] == pytest.approx(dur, abs=1e-9)


def test_samples_velocity_matches_the_schedule():
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(0.0, 90.0, 5.0, "cw"),))
    smp = sch.samples(p0=(0.0, 0.0, 0.0), duration_s=30.0, dt=0.05)
    last = smp[-1]
    v_ref = sch.state_at(last["time_s"])[0]
    for got, want in zip(last["velocity_m_s"], v_ref):
        assert got == pytest.approx(want, abs=1e-9)
    # 航向确实到 90°（+z），速度沿 +z
    assert last["velocity_m_s"][2] == pytest.approx(300.0, abs=0.2)


# ---------------------------------------------------------------- 震荡

def test_weave_lateral_accel_formula():
    """横向过载 = v·amp·2πf —— 文档里那个"幅度×频率"口径。"""
    amp, hz = 6.0, 0.3
    sch = PathSchedule(speed_ms=300.0, weave=WeaveLeg(start_s=0.0, amp_deg=amp, hz=hz))
    peak = max(math.hypot(*sch.state_at(t)[1]) for t in
               [i * 0.005 for i in range(2000)])
    assert peak == pytest.approx(300.0 * math.radians(amp) * 2 * math.pi * hz, rel=1e-3)


def test_weave_displacement_amplitude_formula():
    """位移幅度 = v·amp/(2πf)：低频大位移才是真正拉开几何的那种。

    这是**线性（小角）**口径：`y(t) = v∫sin(A·sin ωt)dt ≈ v·(−A/ω)cos ωt`。
    幅度一大就偏小 —— 30° 时精确值比线性式低约 3%，所以下面分两档给容差。
    """
    def half_swing(amp, hz):
        sch = PathSchedule(speed_ms=300.0, weave=WeaveLeg(start_s=0.0, amp_deg=amp, hz=hz))
        ys, p, t, dt = [], 0.0, 0.0, 0.002
        while t < 1.0 / hz:
            p += sch.state_at(t + dt / 2)[0][1] * dt
            ys.append(p)
            t += dt
        return (max(ys) - min(ys)) / 2

    for amp, rel in ((10.0, 0.005), (30.0, 0.05)):
        want = 300.0 * math.radians(amp) / (2 * math.pi * 0.1)
        assert half_swing(amp, 0.1) == pytest.approx(want, rel=rel)


def test_weave_starts_at_its_start_time():
    sch = PathSchedule(speed_ms=300.0, weave=WeaveLeg(start_s=5.0, amp_deg=10.0, hz=0.2))
    assert sch.pitch_at(4.9) == (0.0, 0.0)
    assert sch.pitch_at(5.0)[0] == pytest.approx(0.0, abs=1e-12)


def test_bad_weave_is_rejected():
    with pytest.raises(ValueError, match="频率必须为正"):
        PathSchedule(speed_ms=300.0, weave=WeaveLeg(start_s=0.0, hz=0.0))
    with pytest.raises(ValueError, match="幅度"):
        PathSchedule(speed_ms=300.0, weave=WeaveLeg(start_s=0.0, amp_deg=95.0))


# ---------------------------------------------------------------- maneuvers 形状

def test_maneuvers_shape_and_ordering():
    sch = PathSchedule(speed_ms=300.0, legs=(TurnLeg(2.0, 120.0, 5.0, "cw"),))
    man = sch.maneuvers(duration_s=10.0, dt=0.1)
    assert man[0] == (0.0, (0.0, 0.0, 0.0))
    times = [t for t, _a in man]
    assert all(b > a for a, b in zip(times, times[1:]))
    assert times[-1] <= 10.0
    assert all(len(a) == 3 for _t, a in man)


def test_maneuvers_bad_dt_is_rejected():
    with pytest.raises(ValueError, match="必须为正"):
        PathSchedule(speed_ms=300.0).maneuvers(duration_s=10.0, dt=0.0)


# ---------------------------------------------------------------- 想定形状

def test_crank_beam_shape():
    sch = crank_beam(t_crank=8.0, crank_deg=70.0, t_beam=35.13, react_delay_s=0.0)
    assert [leg.at_s for leg in sch.legs] == [8.0, 35.13]
    assert integrate_heading(sch, 60.0) == pytest.approx(90.0, abs=0.05)
    assert math.degrees(sch.heading_at(20.0)[0]) == pytest.approx(110.0, abs=0.05)
    assert integrate_accel_heading(sch, 60.0) == pytest.approx(90.0, abs=0.05)


def test_crank_only_never_returns_to_the_threat_axis():
    sch = crank_beam(t_crank=8.0, crank_deg=70.0, t_beam=10_000.0, react_delay_s=0.0)
    assert integrate_heading(sch, 60.0) == pytest.approx(110.0, abs=0.05)


# ---------------------------------------------------- 反应延迟（"看到告警才转 39"）

def test_react_delay_default_is_one_second():
    """默认 1.0 s 是**契约**（人的反应时间量级），文档与代码只能有一个来源。"""
    sch = crank_beam(t_crank=8.0, crank_deg=70.0, t_beam=35.13)
    assert len(sch.legs) == 2
    assert sch.legs[0].at_s == 8.0
    assert sch.legs[1].at_s == pytest.approx(36.13, abs=1e-12)


def test_react_delay_shifts_the_beam_command():
    """延迟窗口内目标仍按 crank 航向飞 —— 这就是「开机」与「开始转 39」两个节点的差。"""
    t_beam, delay = 35.13, 0.9
    sch = crank_beam(t_crank=8.0, crank_deg=70.0, t_beam=t_beam, react_delay_s=delay)
    assert [leg.at_s for leg in sch.legs] == [8.0, t_beam + delay]
    h, w = sch.heading_at(t_beam + delay - 1e-6)          # 延迟还没走完：110°、不转
    assert math.degrees(h) == pytest.approx(110.0, abs=1e-6)
    assert w == 0.0
    assert sch.heading_at(t_beam + delay + 1e-9)[1] == pytest.approx(-5.0 * G0 / 300.0, rel=1e-6)
    assert integrate_heading(sch, 60.0) == pytest.approx(90.0, abs=0.05)


def test_beam_command_before_crank_drops_the_crank_leg():
    """告警早于 crank：crank 无从谈起（丢弃那条腿），从「开机 + 延迟」直接转 39。"""
    sch = crank_beam(t_crank=26.0, crank_deg=70.0, t_beam=25.48,
                     react_delay_s=0.0, g_crank=9.0, g_beam=9.0)
    assert [leg.at_s for leg in sch.legs] == [25.48]       # 旧规则给的是 [26.0, 26.0]
    assert len(sch.table()) == 3                           # 直飞 + 转入39 + 保持（没有空段）
    assert integrate_heading(sch, 25.48) == pytest.approx(180.0, abs=1e-9)
    # 转的是一条 90° 的弧（从 180° 直接到 90°），不是"先 crank 再正侧方"
    assert sch.heading_at(25.48 + 1e-9)[1] == pytest.approx(-9.0 * G0 / 300.0, rel=1e-6)
    assert integrate_heading(sch, 60.0) == pytest.approx(90.0, abs=0.05)


def test_delay_applies_when_beam_command_precedes_crank():
    """用户口径：`t_react` 早于 crank 时**延迟照给**（不是从开机时刻起转，也不夹到 crank）。"""
    sch = crank_beam(t_crank=26.0, crank_deg=70.0, t_beam=20.0,
                     react_delay_s=1.0, g_crank=9.0, g_beam=9.0)
    assert [leg.at_s for leg in sch.legs] == [21.0]        # 20.0（不给延迟）/ 26.0（夹到 crank）都错
    h, w = sch.heading_at(21.0 - 1e-6)
    assert math.degrees(h) == pytest.approx(180.0, abs=1e-6)
    assert w == 0.0
    assert integrate_heading(sch, 60.0) == pytest.approx(90.0, abs=0.05)


def test_beam_command_equal_to_crank_drops_the_crank_leg():
    """`t_react == t_crank` 落在丢弃那一侧（两种读法轨迹等价，取值钉死以免漂移）。"""
    sch = crank_beam(t_crank=26.0, crank_deg=70.0, t_beam=25.0,
                     react_delay_s=1.0, g_crank=9.0, g_beam=9.0)
    assert [leg.at_s for leg in sch.legs] == [26.0]
    assert len(sch.table()) == 3


def test_bad_react_delay_is_rejected():
    for bad in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="反应延迟"):
            crank_beam(t_crank=8.0, crank_deg=70.0, t_beam=35.13, react_delay_s=bad)

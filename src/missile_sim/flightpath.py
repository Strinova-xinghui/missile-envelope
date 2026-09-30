# -*- coding: utf-8 -*-
"""目标航路调度：把"什么时刻转到多少度 / 用几 G / 要不要上下震荡"编译成内核输入。

**为什么需要这一层**：内核 `target` 只认三样东西（三选一互斥，见
`docs/MANEUVER-TARGETS.md` §2）——`maneuvers`（世界系分段常值加速度）、
`turn_rate_rad_s`（全程等速盘旋）、`samples`（录制轨迹）。而用户想的是
**航向指令**："发射后 8 s 转到 70° 做 crank，导弹开机后转正侧方 90°，
再用固定频率和振幅上下震荡"。两者之间差一个编译器，本模块就是它。

**编译是解析的，不做数值积分**（所以没有累积误差）：

    u(ψ, θ) = (cosθ·cosψ, sinθ, cosθ·sinψ)          单位速度方向
    a = v · (ψ̇·∂u/∂ψ + θ̇·∂u/∂θ)
    ∂u/∂ψ = (−cosθ·sinψ, 0, cosθ·cosψ)
    ∂u/∂θ = (−sinθ·cosψ, cosθ, −sinθ·sinψ)

航向角与内核同口径：`heading 0 = +x`、`90 = +z`、`180 = −x`（迎面）。
`turn="ccw"` ⇒ 航向角增大，`"cw"` ⇒ 减小，`"short"` ⇒ 走最短路径。

⚠ **三个已经踩过的坑**（都有回归测试）：

1. **腿会重叠，不能各算各的**。"正侧方 90°"的指令往往在"crank 70°"还没转完时就下达。
   如果对每条腿独立累加时间，同一段经过的时间会被算两遍，编出来的角速度总冲量只剩
   指令的 70%（实测 180°→110° 而不是 90°）。本模块按时间轴走一遍，
   **后一条指令直接截断前一条**（物理上就是"改出"）。
2. **腿必须按时序**。内核硬校验"时刻非负且**严格递增**"
   （`Maneuver times must be nonnegative and strictly increasing`），
   而 `table()` 的截断语义（后一条截断前一条）本身也依赖顺序 —— 所以这里在构造期就 `raise`，
   让错误带着意图在最靠外的一层报出来。
   ⚠ 真正的**静默**风险不是乱序（乱序会被内核当场拒收），而是把**相对偏移**当成绝对时刻填进去。
3. **`samples` 必须逐字覆盖到 `duration_s`**。内核硬校验
   （`Recorded target must cover time zero through duration_s`），而 `t += dt` 累加
   会给出 149.99999999999997，被内核直接拒收 —— 时间轴先把最后一个点钉死。

目标速度标量恒定：内核目标是**纯运动学**的，没有气动、没有能量损失，
所以震荡不掉速。

**状态**：模型层已入仓并有测试；**外壳尚未接入**（`Scene` / `scenario_dict()` /
`cache_key()` / `targets._FORM_KEYS` 都还没接），接入顺序见
`docs/MANEUVER-TARGETS.md` §6/§8。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

G0 = 9.80665


@dataclass(frozen=True)
class TurnLeg:
    """`at_s` 时刻开始，以 `turn_g` 过载把航向转到 `heading_deg`，转到即保持。

    在它还没转完时下达的下一条 `TurnLeg` 会**截断**它 —— 这就是"改出"。
    """
    at_s: float
    heading_deg: float
    turn_g: float = 5.0
    turn: str = "short"        # ccw | cw | short
    phase: str = ""            # 想定语义标签：crank | beam | ""（通用调度，见 `_PHASE_STYLE`）

    def sign(self, heading_now: float) -> float:
        """转向：+1 = 航向角增大，−1 = 减小。`short` 走最短路径。"""
        if self.turn == "ccw":
            return 1.0
        if self.turn == "cw":
            return -1.0
        if self.turn != "short":
            raise ValueError(f"turn 只能是 ccw / cw / short，收到 {self.turn!r}")
        target = math.radians(self.heading_deg)
        delta = (target - heading_now + math.pi) % (2 * math.pi) - math.pi
        return 1.0 if delta >= 0 else -1.0

    def delta_rad(self, heading_now: float) -> float:
        """→ **有符号**转角（rad），`ccw` 恒 ≥ 0、`cw` 恒 ≤ 0、`short` 走最短路径。

        ⚠ 转弯时长必须用这个量、**不能**用 `abs(target − h)`：航向跨过 0°/360° 时
        后者会绕远（`ccw` 350°→10° 被算成 340°、36 s，**而且到不了目标**）。
        它的符号与 `sign()` 一致，所以 `h += ω·Δt` 一定朝目标走。
        """
        target = math.radians(self.heading_deg)
        if self.turn == "ccw":
            return (target - heading_now) % (2 * math.pi)
        if self.turn == "cw":
            return -((heading_now - target) % (2 * math.pi))
        if self.turn != "short":
            raise ValueError(f"turn 只能是 ccw / cw / short，收到 {self.turn!r}")
        return (target - heading_now + math.pi) % (2 * math.pi) - math.pi


@dataclass(frozen=True)
class WeaveLeg:
    """从 `start_s` 起俯仰震荡：`θ(t) = phase + amp·sin(2π·hz·(t−start))`。

    代价由两个量决定（`v` = 目标速度）：

        位移幅度 = v·amp/(2π·hz)          目标自身横向过载 = v·amp·2π·hz

    高频小位移（±6°/0.3 Hz ≈ 17 m / 6G）弹跟得住；**低频大位移**
    （±30°/0.1 Hz ≈ 250 m / 10G）才会真正拉开几何。实测见
    `docs/MANEUVER-TARGETS.md` §8.4。
    """
    start_s: float
    amp_deg: float = 4.0
    hz: float = 0.1
    phase_deg: float = 0.0

    def check(self) -> None:
        if self.hz <= 0:
            raise ValueError(f"震荡频率必须为正，收到 {self.hz!r}")
        if not 0 <= self.amp_deg <= 89:
            raise ValueError(f"震荡幅度要在 0~89° 内，收到 {self.amp_deg!r}")


_PHASE_STYLE = {
    ("crank", "turn"): ("转入crank", "orange"),
    ("crank", "hold"): ("crank保持", "red"),
    ("beam", "turn"): ("转入39", "teal"),
    ("beam", "hold"): ("39保持", "blue"),
}


@dataclass(frozen=True)
class Segment:
    """目标航迹的**一段**（`PathSchedule.segments()` 的唯一产物，出图 / CSV / JSON 共用）。

    `t1_s` 允许是 `inf`（最后一段没有尽头，分析上最自然）；
    **落盘前必须用 `segments(duration_s=…)` 夹紧** —— JSON 里没有 `inf`。
    """
    t0_s: float
    t1_s: float
    kind: str                  # straight | turn | hold
    label: str                 # 直飞 / 转入crank / crank保持 / 转入39 / 39保持
    heading0_deg: float        # 段首航向
    heading1_deg: float        # 段尾航向（转弯段与段首不同；直飞/保持段两者相等）
    color_key: str             # grey | orange | red | teal | blue
    phase: str = ""            # crank | beam | ""（通用调度）
    truncated: bool = False    # 转弯段被下一条指令截断 = 用户口径的"没转完"

    def as_dict(self) -> dict:
        return {"t0_s": self.t0_s, "t1_s": self.t1_s, "kind": self.kind,
                "label": self.label, "heading0_deg": self.heading0_deg,
                "heading1_deg": self.heading1_deg, "color_key": self.color_key,
                "phase": self.phase, "truncated": self.truncated}


@dataclass
class PathSchedule:
    """直飞 → 若干条航向指令 → 可选俯仰震荡。编译成内核吃的 `maneuvers` 或 `samples`。"""
    speed_ms: float
    start_heading_deg: float = 180.0
    start_pitch_deg: float = 0.0
    legs: tuple = ()
    weave: WeaveLeg | None = None

    #: `table()` 的缓存。**`init=False` 是必须的**：否则 `dataclasses.replace()`
    #: 会把这个已经算好的表一起搬到新实例上 —— 改了 `legs` / `speed_ms` 之后
    #: 航向表还是旧的，而一切都"看起来正常"（同一族的静默失败）。
    _table: list | None = field(default=None, repr=False, compare=False, init=False)

    # ---- 航向率表（构造一次，之后查表） ----

    def __post_init__(self) -> None:
        if self.speed_ms <= 0:
            raise ValueError(f"目标速度必须为正，收到 {self.speed_ms!r}")
        if self.weave is not None:
            self.weave.check()
        stamps = [leg.at_s for leg in self.legs]
        if any(s < 0 for s in stamps):
            raise ValueError(f"航向指令时刻不能为负：{stamps}")
        if stamps != sorted(stamps):
            raise ValueError(
                f"航向指令必须按时序给，收到 {stamps}：`table()` 的截断语义依赖顺序"
                "（后一条截断前一条），内核也会硬拒非严格递增的时刻 —— 在模型层先报出来")
        for leg in self.legs:
            if leg.turn_g < 0:
                raise ValueError(f"转弯过载不能为负，收到 {leg.turn_g!r}")

    def table(self) -> list:
        """编译成**分段常值航向角速度**表：`[(t0, t1, ω, ψ0), …]`。

        `ω = 0` 表示直飞；`t1 = inf` 表示最后一段。相邻腿在时间轴上**截断**而非叠加：
        下一条指令在下达时刻就把上一条切断（"改出"），即使上一条还没转完。
        """
        if self._table is not None:
            return self._table
        ordered = list(self.legs)
        segs = []
        t, h = 0.0, math.radians(self.start_heading_deg)
        for i, leg in enumerate(ordered):
            if leg.at_s < t - 1e-9:                       # 兜底：乱序（构造期已挡一次）
                raise ValueError(f"航向指令时刻 {leg.at_s:g} 早于前一条的结束时刻 {t:g}")
            if leg.at_s > t + 1e-12:
                segs.append((t, float(leg.at_s), 0.0, h))
                t = float(leg.at_s)
            omega = leg.sign(h) * leg.turn_g * G0 / self.speed_ms
            dur = abs(leg.delta_rad(h) / omega) if omega else 0.0
            nxt = float(ordered[i + 1].at_s) if i + 1 < len(ordered) else float("inf")
            end = min(t + dur, nxt)          # 下一条指令可以截断本条
            segs.append((t, end, omega, h))
            h += omega * (end - t)
            t = end
        segs.append((t, float("inf"), 0.0, h))
        self._table = segs
        return segs

    # ---- 折成分段（出图 / CSV / JSON 的唯一口径） ----

    def segments(self, *, duration_s: float | None = None) -> list:
        """把 `table()` 那张分段常值 ω 表**折成** `[Segment]`。

        刻意**不另做时间算术**（两套口径必然漂移）：一张表、一份折法。

        * 与 `table()` 的行**一一对应**，只丢掉零长度行（`g=0` 或已经在目标航向上
          ⇒ 那一段物理上不存在）；
        * `ω != 0` 的行是 `turn`，其余是 `hold`；**第一条指令之前**的零 ω 行是 `straight`；
        * `duration_s` 给定时把尾段的 `inf` 夹到它、并丢掉起点在它之后的段
          （**落盘前必须给** —— JSON 里没有 `inf`）；
        * 转弯段被下一条指令截断时 `truncated=True`，就是用户口径的"**没转完**"；
        * `heading0_deg` / `heading1_deg` 都**规范化到 [0, 360)**（内部累积的航向不折叠，
          跨 0° 时可能是 370° 这种值，出图/落盘前统一）。
        """
        out, legs, leg_i = [], list(self.legs), -1
        for t0, t1, omega, h0 in self.table():
            if t1 - t0 <= 1e-12:                       # 零长度行：其实没转过
                continue
            while leg_i + 1 < len(legs) and legs[leg_i + 1].at_s <= t0 + 1e-9:
                leg_i += 1                             # 这一行是第 leg_i 条指令下达后的产物
            leg = legs[leg_i] if leg_i >= 0 else None
            phase = leg.phase if leg else ""
            if omega:
                h1 = math.degrees(h0 + omega * (t1 - t0))
                target = float(leg.heading_deg) if leg else h1
                label, color = _PHASE_STYLE.get((phase, "turn"), (f"转入{target:g}°", "orange"))
                short = abs((h1 - target + 180.0) % 360.0 - 180.0) > 1e-6   # 差得远 = 被截断
                out.append(Segment(t0, t1, "turn", label, math.degrees(h0) % 360.0,
                                   h1 % 360.0, color, phase, truncated=short))
            else:
                head = math.degrees(h0) % 360.0
                if leg is None:                        # 还没下过任何指令 ⇒ 迎头直飞
                    out.append(Segment(t0, t1, "straight", "直飞", head, head, "grey"))
                else:
                    label, color = _PHASE_STYLE.get((phase, "hold"), (f"保持{head:g}°", "red"))
                    out.append(Segment(t0, t1, "hold", label, head, head, color, phase))
        if duration_s is None:
            return out
        d = float(duration_s)
        return [replace(s, t1_s=d) if s.t1_s > d else s for s in out if s.t0_s < d - 1e-9]

    # ---- 航向 / 俯仰的时间历程（解析） ----

    def heading_at(self, t: float) -> tuple:
        """→ `(航向 rad, 航向角速度 rad/s)`。"""
        for t0, t1, omega, h0 in self.table():
            if t0 <= t < t1:
                return (h0 + omega * (t - t0), omega) if omega else (h0, 0.0)
        _t0, _t1, omega, h0 = self.table()[-1]
        return h0, omega

    def pitch_at(self, t: float) -> tuple:
        """→ `(俯仰 rad, 俯仰角速度 rad/s)`。"""
        p0 = math.radians(self.start_pitch_deg)
        wp = self.weave
        if wp is None or t < wp.start_s:
            return p0, 0.0
        a = math.radians(wp.amp_deg)
        om = 2 * math.pi * wp.hz
        el = t - wp.start_s
        return p0 + a * math.sin(om * el + math.radians(wp.phase_deg)), \
            a * om * math.cos(om * el + math.radians(wp.phase_deg))

    def state_at(self, t: float) -> tuple:
        """→ `(velocity_m_s, accel_m_s2)`，都是相对世界系的 3 元组。"""
        h, w = self.heading_at(t)
        th, thd = self.pitch_at(t)
        v = self.speed_ms
        u = (math.cos(th) * math.cos(h), math.sin(th), math.cos(th) * math.sin(h))
        du_dh = (-math.cos(th) * math.sin(h), 0.0, math.cos(th) * math.cos(h))
        du_dth = (-math.sin(th) * math.cos(h), math.cos(th), -math.sin(th) * math.sin(h))
        acc = tuple(v * (w * du_dh[i] + thd * du_dth[i]) for i in range(3))
        return tuple(v * x for x in u), acc

    # ---- 编译成内核输入 ----

    def maneuvers(self, *, duration_s: float, dt: float = 0.1) -> tuple:
        """→ `[(time_s, (ax, ay, az)), …]`，可直接喂 `raw["target"]["maneuvers"]`。

        分段常值加速度的离散化误差是 `O(dt)`：实测 `dt=0.1` 与精确积分差 0.2 s
        （命中时刻），`dt=0.02` 收敛到 0.04 s。见 `docs/MANEUVER-TARGETS.md` §8.3。
        """
        if dt <= 0 or duration_s <= 0:
            raise ValueError("dt 与 duration_s 必须为正")
        out = [(0.0, (0.0, 0.0, 0.0))]
        t = dt
        while t <= duration_s - 1e-9:
            _v, acc = self.state_at(t)
            out.append((round(t, 6), acc))
            t += dt
        return tuple(out)

    def samples(self, *, p0, duration_s: float, dt: float = 0.05) -> tuple:
        """→ 内核 `samples` 形状的录制轨迹（中点法积分），从 `t=0` 起、覆盖满 `duration_s`。

        ⚠ 时间轴按 `duration_s/n` 构造并**把最后一个点钉死**在 `duration_s`：
        内核要求 `samples[-1]["time_s"] >= duration_s`，`t += dt` 的浮点累加会被拒收。
        """
        if dt <= 0 or duration_s <= 0:
            raise ValueError("dt 与 duration_s 必须为正")
        n = max(2, int(math.ceil(float(duration_s) / float(dt))))
        times = [float(duration_s) * i / n for i in range(n + 1)]
        times[0], times[-1] = 0.0, float(duration_s)
        p = [float(x) for x in p0]
        out = [{"time_s": 0.0, "position_m": list(p),
                "velocity_m_s": list(self.state_at(0.0)[0])}]
        for i in range(1, n + 1):
            h = times[i] - times[i - 1]
            vm, _ = self.state_at(times[i - 1] + h / 2)
            for k in range(3):
                p[k] += vm[k] * h
            out.append({"time_s": times[i], "position_m": list(p),
                        "velocity_m_s": list(self.state_at(times[i])[0])})
        return tuple(out)


def crank_beam(t_crank: float, crank_deg: float, t_beam: float, beam_deg: float = 90.0,
               speed_ms: float = 300.0, g_crank: float = 5.0, g_beam: float = 5.0,
               react_delay_s: float = 1.0,
               weave: WeaveLeg | None = None) -> PathSchedule:
    """用户想定的常用形状：发射后 `t_crank` 秒 crank 到 `crank_deg`；`t_beam` 时刻
    （一般由"开机距离"反求）**收到 RWR 告警**，再经 `react_delay_s` 的反应时间开始转正侧方
    `beam_deg`（默认 90° = 39 位）。

    时间轴（用户 2026-09-30 定稿的口径）：

        t_react = t_beam + react_delay_s        # 「开始转入 39」的时刻
        t_react >  t_crank  ⇒ 腿 = [crank @ t_crank, 39 @ t_react]   # crank 可能被截断（"没转完"）
        t_react <= t_crank  ⇒ 腿 = [39 @ t_react]                    # 丢弃 crank 腿：没来得及预规避

    默认 `react_delay_s = 1.0` s（人的反应时间量级 0.5~2 s 取标称） ⇒
    **「导引头开机」与「开始转入 39」是两个不同的节点**，延迟期间目标仍按当时的航向飞
    （crank 已转完就是 110°）。给 `0.0` 就是"看到告警即转"。

    延迟只作用在 **39 指令**上，**不作用在 crank 上** —— crank 是事先计划的预规避，
    39 才是对告警的反应；`t_beam` 本身是弹侧事件（首次 `range ≤ lockDistance`），不被反应推迟。

    ⚠ `t_react <= t_crank` 时**丢弃 crank 腿**，而不是造一条零长度腿：两者轨迹完全等价，
    但前者不会在 `table()` 里留下一段 `(t, t, ω, ψ)` 的空段。

    实测（PL-12 / 16 km / t_crank=8 / 70° / 9G）见 `docs/MANEUVER-TARGETS.md` §8.8.5 与 §8.9：
    延迟 0 s ⇒ `t_hit = 69.554 s`，延迟 1.0 s ⇒ `69.172 s`。
    """
    if not math.isfinite(react_delay_s) or react_delay_s < 0:
        raise ValueError(f"反应延迟必须是非负有限数，收到 {react_delay_s!r}")
    t_react = float(t_beam) + float(react_delay_s)
    beam = TurnLeg(t_react, 180.0 - beam_deg, g_beam, "cw", phase="beam")
    if t_react <= float(t_crank):            # 告警来得太晚：预规避无从谈起，直接进 39
        return PathSchedule(speed_ms=speed_ms, start_heading_deg=180.0,
                            legs=(beam,), weave=weave)
    crank = TurnLeg(t_crank, 180.0 - crank_deg, g_crank, "cw", phase="crank")
    return PathSchedule(speed_ms=speed_ms, start_heading_deg=180.0,
                        legs=(crank, beam), weave=weave)

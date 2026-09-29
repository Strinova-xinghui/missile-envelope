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
2. **腿必须按时序**。引擎按时间递增推进，乱序会静默按错序执行 —— 这里直接 `raise`。
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
from dataclasses import dataclass, field

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


@dataclass
class PathSchedule:
    """直飞 → 若干条航向指令 → 可选俯仰震荡。编译成内核吃的 `maneuvers` 或 `samples`。"""
    speed_ms: float
    start_heading_deg: float = 180.0
    start_pitch_deg: float = 0.0
    legs: tuple = ()
    weave: WeaveLeg | None = None

    _table: list | None = field(default=None, repr=False, compare=False)

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
                f"航向指令必须按时序给，收到 {stamps}：引擎按时间递增推进，"
                "乱序会静默按错序执行（这类错不报错、只是结果不对）")
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
            target = math.radians(leg.heading_deg)
            omega = leg.sign(h) * leg.turn_g * G0 / self.speed_ms
            dur = abs((target - h) / omega) if omega else 0.0
            nxt = float(ordered[i + 1].at_s) if i + 1 < len(ordered) else float("inf")
            end = min(t + dur, nxt)          # 下一条指令可以截断本条
            segs.append((t, end, omega, h))
            h += omega * (end - t)
            t = end
        segs.append((t, float("inf"), 0.0, h))
        self._table = segs
        return segs

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
               weave: WeaveLeg | None = None) -> PathSchedule:
    """用户想定的常用形状：发射后 `t_crank` 秒 crank 到 `crank_deg`，
    `t_beam` 时刻（一般由"开机距离"反求）转正侧方 `beam_deg`（默认 90°）。

    ⚠ **`t_beam` 早于 `t_crank` 时按"直接转正侧方"处理**（即取 `t_beam = t_crank`）：
    那表示目标刚想 crank，弹已经开机了 —— crank 无从谈起，于是从当前航向直接转正侧方
    （180° → 90° 一次转完）。这是**物理上唯一自洽**的读法，也让本函数成为全函数
    （否则调用方会送进一个乱序的腿表而被 `PathSchedule` 拒绝）。
    """
    t_beam = max(float(t_beam), float(t_crank))
    return PathSchedule(
        speed_ms=speed_ms, start_heading_deg=180.0,
        legs=(TurnLeg(t_crank, 180.0 - crank_deg, g_crank, "cw"),
              TurnLeg(t_beam, 180.0 - beam_deg, g_beam, "cw")),
        weave=weave)

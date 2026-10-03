# -*- coding: utf-8 -*-
"""图4（机动想定轨迹图）的**纯数据层**：分段 / 节点 / 一次运行的汇总。

**为什么单独一个模块**：`figures.py` 要吃这些类型，而 `workflow.py` 里已经
`import figures` —— 把数据层塞进 `workflow` 就成了循环 import。
本模块只依赖 `spec`（`Scene` / `Shot`）与 `flightpath`（`PathSchedule` / `Segment`），
**不 import 求解器、不 import 出图**，所以：

* 出图能直接吃（`figures.plot_traj(run)`）；
* 纯函数（`find_anchor` / `build_marks` / `summarize`）能用**手造的行**毫秒级单测，
  不需要跑求解器。

口径见 `docs/PLAN-FIG3-TRAJECTORY.md`；实测数字见 `docs/MANEUVER-TARGETS.md` §8。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .flightpath import PathSchedule
from .spec import Scene, Shot

ANCHOR_MODE = "一遍法：在不含 39 腿的轨迹上取首个 range ≤ lockDistance"
"""`anchor["mode"]` 的取值。⚠ 这条口径不能改成迭代法：
"首次 range ≤ lockDistance" 是**自指条件**（39 腿改变轨迹 ⇒ 又改变开机时刻），
拿已经加了 39 腿的轨迹去迭代会漂移；而 39 腿最早在 `t_react` 才起作用，
`t_beam < t_react` 恒成立，所以一遍法在该时刻**精确**。

⚠ 这个常量**会进 manifest 与 WebUI 摘要**（`anchor["mode"]`），是**打印出来的文本**，
所以里面**不能写 markdown**（`figures._plain()` 只兜出图那条路径）—— 星号会原样出现在
`results/traj_<tag>.json` 和网页上。强调写在上面这段 docstring 里就行。"""


def _finite(v):
    """`nan` / `inf` ⇒ `None`（JSON 里没有这两种值；`nan` 还会污染整份产物）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


@dataclass(frozen=True)
class TrajMark:
    """图上的一个节点。`t_s` 落在 `[0, t_end]` 之外就不画（但照样落盘，便于复核）。"""
    name: str            # launch | crank_start | crank_done | seeker_on | beam_start | end
    t_s: float
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "t_s": _finite(self.t_s), "note": self.note}


@dataclass
class TrajRun:
    """一次机动想定的**全部可画 / 可落盘信息**（出图、CSV、JSON 三方共用这一种输入）。

    `rows` 就是 `Shot.rows`（`solver.trajectory()` 的精简行）：键为
    `t / x / y / z / v / mass / thrust / range / tx / ty / tz`，
    其中 **`x`/`z` 是水平面**（`heading 0 = +x`、`90 = +z`）、**`y` 是高度**，
    `t*` 是目标。⚠ 内核对头：原始行叫 `missile_x_m` / `time_s`，精简行不是。
    """

    scene: Scene
    schedule: PathSchedule
    shot: Shot
    segments: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    anchor: dict = field(default_factory=dict)
    missile: str = ""
    beta: float = math.nan
    gamma: float = math.nan
    rows: list = field(default_factory=list)
    note: str = ""

    # ---- 便利读数（省得每个调用方各写一遍 nan 判断）----

    @property
    def t_end_s(self) -> float:
        """这一次跑到的时刻（命中 = `t_hit`，脱靶 = 寿命耗尽）。"""
        return float(self.shot.t_end)

    @property
    def hit(self) -> bool:
        return bool(self.shot.hit)

    @property
    def t_hit_s(self) -> float:
        return float(self.shot.t_hit) if self.shot.hit else math.nan

    def rows_at(self, t_s: float) -> dict | None:
        """取最接近 `t_s` 的那一行（画节点位置用）。"""
        if not self.rows:
            return None
        return min(self.rows, key=lambda r: abs((r.get("t") or 0.0) - t_s))

    def as_dict(self) -> dict:
        marks = [m.as_dict() for m in self.marks]
        return {
            "missile": self.missile, "beta": _finite(self.beta),
            "gamma": _finite(self.gamma),
            "hit": bool(self.shot.hit), "event": self.shot.event,
            "t_hit_s": _finite(self.shot.t_hit), "t_end_s": _finite(self.shot.t_end),
            # 三个距离各写各的名字（A5）：命中时 `min_separation_m` 是**引信半径**，
            # 真"打得多准"看 `cpa_m`（命中工况由 `solver.run(want_cpa=True)` 关引信复跑量出）。
            "min_separation_m": _finite(self.shot.min_separation_m),
            "cpa_m": _finite(self.shot.cpa_m),
            "fuse_radius_m": _finite(self.shot.fuse_radius_m),
            "v_impact_m_s": _finite(self.shot.v_impact),
            "max_alt_m": _finite(self.shot.max_alt_m),
            "backend": self.shot.backend,
            "anchor": dict(self.anchor),
            "segments": [s.as_dict() for s in self.segments],
            "marks": marks, "note": self.note,
        }


def find_anchor(rows, *, lock_distance_m: float, mode: str = ANCHOR_MODE) -> dict:
    """"导引头开机"时刻 = 轨迹上**首个** `range ≤ lock_distance` 的采样时刻。

    ⚠ 传进来的 `rows` 必须是**不含 39 腿**的轨迹（见 `ANCHOR_MODE`）。
    分辨率就是求解器的输出采样间隔（约 0.02 s）—— 不做插值：锚点的定义要在
    "哪一行"上可复核，插值反而让"t_beam 是谁"变得不可查。

    返回 `{mode, lock_distance_m, t_beam_s, range_at_beam_m}`；整条轨迹都没进过
    `lockDistance` 时 `t_beam_s = None`（调用方必须显式处理，不要当成 0）。
    """
    lock = float(lock_distance_m)
    if not math.isfinite(lock) or lock <= 0.0:
        raise ValueError(f"开机距离必须是正的有限数，收到 {lock_distance_m!r}")
    for r in rows:
        rng = r.get("range")
        if rng is not None and float(rng) <= lock:
            return {"mode": mode, "lock_distance_m": lock,
                    "t_beam_s": float(r["t"]), "range_at_beam_m": float(rng)}
    return {"mode": mode, "lock_distance_m": lock, "t_beam_s": None,
            "range_at_beam_m": None}


def leg_at(schedule: PathSchedule, phase: str):
    """取某一段想定语义的腿（`phase="crank"` / `"beam"`）；没有就返回 `None`。"""
    for leg in schedule.legs:
        if leg.phase == phase:
            return leg
    return None


def build_marks(*, schedule: PathSchedule, segments, anchor: dict,
                shot: Shot) -> list:
    """由**分段表 + 锚点 + 求解结果**折出节点表（不另做时间算术）。

    节点就是 `docs/PLAN-FIG3-TRAJECTORY.md` §3.1 那五类，外加一个 `crank_done`
    （"没转完"时它不存在 —— 那正是图上要看得见的东西）。
    """
    marks = [TrajMark("launch", 0.0, "发射")]
    # ⚠ 同一个 phase 有两段（转弯 + 保持），这里只取**转弯**那段
    seg_turn = {s.phase: s for s in segments if s.phase and s.kind == "turn"}
    crank, beam = leg_at(schedule, "crank"), leg_at(schedule, "beam")
    t_beam = anchor.get("t_beam_s")

    if crank is not None:
        marks.append(TrajMark("crank_start", crank.at_s,
                              f"开始 crank 至 {crank.heading_deg:g}°（{crank.turn_g:g}G）"))
        seg = seg_turn.get("crank")
        if seg is not None and not seg.truncated:
            marks.append(TrajMark("crank_done", seg.t1_s,
                                  f"crank 转完（{seg.heading1_deg:g}°）"))
    if t_beam is not None:
        lock_km = float(anchor.get("lock_distance_m") or 0.0) / 1000.0
        marks.append(TrajMark("seeker_on", float(t_beam),
                              f"导引头开机 · R = {lock_km:g} km"))
    if beam is not None:
        delay = (beam.at_s - float(t_beam)) if t_beam is not None else math.nan
        tail = f"（延迟 {delay:g} s）" if math.isfinite(delay) else ""
        marks.append(TrajMark("beam_start", beam.at_s, f"开始转入 39{tail}"))
    t_end = _finite(shot.t_end)
    if t_end is not None:
        if shot.hit:
            note = "命中"
        else:
            # 未命中的结局文案用"终止前最近距离"：那一次飞行本来就飞完了，
            # `min_separation_m` 就是真脱靶量（命中时才退化成引信半径，见 Shot）。
            miss = _finite(shot.min_separation_m)
            note = "脱靶 " + (f"{miss:.0f} m" if miss is not None else "（最近点）")
        marks.append(TrajMark("end", t_end, note))
    marks.sort(key=lambda m: m.t_s)
    return marks

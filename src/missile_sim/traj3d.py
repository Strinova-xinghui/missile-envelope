# -*- coding: utf-8 -*-
"""图4 的**数据层**：把已经落盘的 traj 产物折成前端要吃的 JSON。

两层，互不干扰：

1. `build()` —— **查看器**（`/api/viewer3d/<job>`）：整条轨迹 + 阶段分段 + 节点，抽稀到 `points` 点；
2. `build_replay()` —— **空战沙盒**（`/api/sandbox/<key>`）：在 `build()` 的全套之上再加
   **时间轴 / 事件表 / 双方逐点读数（含姿态）/ 轴刻度 / 悬停字段契约**，逐帧回放用。

**为什么单独一个模块**（而不是塞进 `webui.py`）：
写入侧与读取侧要能分开测 —— 本模块**只读产物**（`traj_<tag>_{missile,target,segments}.csv`
与 `traj_<tag>.json`），**不 import 求解器、不 import workflow**，所以"这个接口不解算"这条
判据可以用毫秒级单测钉住（路由层那条走 HTTP，见 `tests/test_viewer3d.py` / `tests/test_sandbox.py`）。

口径（与静态图、与 `results/traj_*.csv` 的列名逐字对齐）：

* 坐标 `x` / `z` 是**水平面**（航向 0° = +x、90° = +z），`y` 是**高度** —— 别把 `y` 当水平面；
* 配色**从 `figures` 现取**（`TRAJ_COLORS` / `TRAJ_MISSILE_COLOR` / **`TRAJ_MISSILE2_COLOR`** /
  `TRAJ_MARK_COLOR` / …），前端一个颜色字面量都不写，所以"数据配色沿用 TRAJ_COLORS"是**可测**的；
  ⚠ 注意导弹是**两个**色相：开机前 `TRAJ_MISSILE_COLOR`（深灰 #4d4d4d）、开机后
  `TRAJ_MISSILE2_COLOR`（紫 #8e44ad）—— 只取前者会让查看器与静态图**静默不一致**
  （2026-10-02 合并 3d-viewer 与 3d-viz 时真中过，见 `docs/RESTART-PLAN.md` §13.7）；
* 抽稀到 `points` 点（默认 800、上限 4000），但**阶段边界（`Segment` t0/t1）与节点时刻
  所在的采样点必须留下** —— 抽稀把 crank→39 的拐点抽掉，等于把这张图要说的东西抽掉；
* 导弹轨迹按 `t_beam`（导引头开机）**切成两段**：`split_index` 是"第一个 `t ≥ t_beam` 的点"，
  于是 `p[:split_index]` 是开机前、`p[split_index:]` 是开机后（两段共享边界点，画出来不断线）。

沙盒那一层额外守两条纪律（见 `docs/SANDBOX.md` §5 与 `docs/SOLVER-API.md` §3.1）：

1. **拿不到的字段不许编（仓库第一原则："先 grep 内核"）**：内核 60 列里有
   `air_speed_m_s` / `accel_x/y/z_m_s2` / `distance_flown_m` / `trajectory_normal_g` /
   `specific_force_g` / `requested_g` / `target_speed_m_s` / `qx..qw`，但我们的精简行
   （`solver.trajectory()` → `record.write_traj_track_csv()`）只写了 8 列，把它们丢了。
   在产物扩列落地之前，这些字段在**字段契约**里标 `"pending"`（前端显示"待接入"），
   **不用差分或累加弧长去顶**；那两套差额实现只留在模块里当 P6 的**对拍照**；
2. **派生值要标出来**：`horizontal_m`（`sqrt(Δx²+Δz²)`，位置是内核列）与姿态角
   （`yaw_deg`/`pitch_deg`，绘图用）是本仓从内核位置折出来的，契约里标 `"derived"`，
   与 `"kernel"`（直接取产物列）区分开。
"""

from __future__ import annotations

import bisect
import csv
import json
import math
import re
from pathlib import Path

from . import figures

DEFAULT_POINTS = 800
#: 上限：轨迹本身只有几千行，再密也只是把同一批点重复发一遍（3322 行的默认工况，4000 已经超过原始行数）
MAX_POINTS = 4000
MIN_POINTS = 2
#: 开机前那段：`TRAJ_MISSILE_COLOR` 向亮底混合的比例（**派生**，不引入新色相）；
#: 开机后直接用 `figures.TRAJ_MISSILE2_COLOR`（静态图同色），**不**做这个淡化
MISSILE_MIX = 0.45
#: 静态图上的亮底（WebUI / 查看器 chrome 同一支：`#f7f8f9`）
LIGHT_BG = "#f7f8f9"
_POINTS_RE = re.compile(r"[0-9]{1,6}")

#: 回放倍速（参考站：动画速度留左栏，播放控件与进度条放主视图顶部）
REPLAY_SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)
REPLAY_SPEED_DEFAULT = 1.0
#: 镜头模式（`key`, 中文标签）—— `free` 是鼠标自由的现状，另两个把相机中心钉在实体上
FOLLOW_MODES = (("free", "自由"), ("missile", "跟随导弹"), ("target", "跟随敌机"))
FOLLOW_DEFAULT = "free"
#: 悬停框字段契约的"来源"取值：内核产物列 / 本仓派生 / 不适用（该实体没有这个量）/ 待接入（列还没进产物）
SRC_KERNEL = "kernel"
SRC_DERIVED = "derived"
SRC_NA = "n/a"
SRC_PENDING = "pending"
#: 相对发射点算水平距离（默认工况发射点就是原点，但不能写死 —— 换想定后原点会变）
HORIZONTAL_HINT = "相对发射点"
#: 加速度的口径：**内核三分量**在**内核速度方向**上的投影（`(ax,ay,az)·v̂`，用 `vx/vy/vz` 列）
ACCEL_HINT = "内核 accel_x/y/z_m_s2 在速度方向上的投影（v̂ 取内核 vx/vy/vz）"
#: 目标侧速度/加速度对拍照的差分窗口（采样数）：产物位置只到 0.1 m，2 采样窗口会被量化噪声
#: 放大成 ±58 m/s² 的假加速度（实测），±10 采样（≈±0.21 s）压到 ±2 m/s² 量级。
#: ⚠ 这套差分**只用于 P6 与内核列对拍**（`tests/test_sandbox.py`），不进响应、不进悬停框。
TARGET_HALF = 10


# --------------------------------------------------------------------- 参数


def parse_points(raw) -> int:
    """`?points=` → 点数。非法值直接 `ValueError`（路由层折成 400，**不静默截断**）。

    刻意不做宽容修正：`points=800.0` / `+800` / `800 ` 都是**另一回事**，
    "顺手帮你 round 一下"会让调用方以为自己写对了。
    """
    if raw is None or str(raw).strip() == "":
        return DEFAULT_POINTS
    text = str(raw).strip()
    if not _POINTS_RE.fullmatch(text):
        raise ValueError(f"points 必须是整数，收到 {raw!r}")
    n = int(text)
    if n < MIN_POINTS:
        raise ValueError(f"points 至少 {MIN_POINTS}，收到 {n}")
    if n > MAX_POINTS:
        raise ValueError(f"points 最多 {MAX_POINTS}，收到 {n}")
    return n


def parse_speed(raw) -> float:
    """`?speed=` → 倍速。只认 `REPLAY_SPEEDS` 里那几个（**枚举，不是连续量**）。"""
    if raw is None or str(raw).strip() == "":
        return REPLAY_SPEED_DEFAULT
    text = str(raw).strip()
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"speed 必须是数字，收到 {raw!r}") from None
    for known in REPLAY_SPEEDS:
        if abs(v - known) < 1e-9:
            return known
    raise ValueError(f"speed 只能是 {list(REPLAY_SPEEDS)} 之一，收到 {raw!r}")


# --------------------------------------------------------------------- 抽稀


def decimate_indices(n: int, n_max: int, forced=()) -> list:
    """等间隔抽稀到**恰好 ≤ `n_max`** 个下标，且 `forced` 里的下标一个都不丢。

    算法：先把 `forced` 拿出去，再在**剩下的**点上按等间隔取 `n_max - len(forced)` 个。
    这样总数天然受控（等间隔是"取"，不是"删"），也不会出现"为了保住拐点而超发点数"。
    ⚠ 别改成"先等间隔、再补拐点"：那会让返回点数变成 `n_max + len(forced)`，
    "默认 800 点"这条契约当场失效（而画面上看不出任何异常）。
    """
    if n <= 0:
        return []
    keep = sorted({int(i) for i in forced if 0 <= int(i) < n})
    if n <= n_max:
        return list(range(n))
    if len(keep) >= n_max:                     # 极端：强制点本身就超预算，只能保强制点
        return keep[:n_max]
    rest = [i for i in range(n) if i not in set(keep)]
    need = n_max - len(keep)
    if need <= 0 or not rest:
        return keep
    if need == 1:
        picked = {rest[0]}
    else:
        picked = {rest[round(j * (len(rest) - 1) / (need - 1))] for j in range(need)}
    return sorted(set(keep) | picked)


def _nearest_index(ts, t: float) -> int:
    """最接近 `t` 的采样下标（`ts` 必须单调递增）。"""
    i = bisect.bisect_left(ts, float(t))
    if i <= 0:
        return 0
    if i >= len(ts):
        return len(ts) - 1
    return i if abs(ts[i] - t) <= abs(ts[i - 1] - t) else i - 1


def _ceil_index(ts, t: float) -> int:
    """**第一个** `ts[i] ≥ t` 的下标（都小于 `t` 时退化成最后一个）。"""
    i = bisect.bisect_left(ts, float(t))
    return min(i, len(ts) - 1)


def _interp(ts, pts, t: float):
    """按时间在两条采样行之间线性内插（节点时刻常落在两行之间）。"""
    if not ts:
        return None
    i = bisect.bisect_left(ts, float(t))
    if i <= 0:
        return list(pts[0])
    if i >= len(ts):
        return list(pts[-1])
    span = ts[i] - ts[i - 1]
    f = 0.0 if span <= 1e-12 else max(0.0, min(1.0, (float(t) - ts[i - 1]) / span))
    return [pts[i - 1][j] + (pts[i][j] - pts[i - 1][j]) * f for j in range(3)]


# --------------------------------------------------------------------- 颜色


def hex_to_rgb(text: str):
    """`#rrggbb` → 0~1 三元组（前端要的是 float 顶点色）。"""
    s = str(text).strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"只认 #rrggbb 颜色，收到 {text!r}")
    return [int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def mix_hex(a: str, b: str, k: float) -> str:
    """把 `a` 向 `b` 混 `k`（0 = a、1 = b），返回 `#rrggbb`。"""
    ca, cb = hex_to_rgb(a), hex_to_rgb(b)
    f = max(0.0, min(1.0, float(k)))
    return "#" + "".join(f"{round(255 * (ca[i] + (cb[i] - ca[i]) * f)):02x}" for i in range(3))


def palette() -> dict:
    """数据配色：**全部来自 `figures`**（前端不写死任何一个）。"""
    before = mix_hex(figures.TRAJ_MISSILE_COLOR, LIGHT_BG, MISSILE_MIX)
    return {
        "segments": dict(figures.TRAJ_COLORS),
        "fallback": figures.TRAJ_FALLBACK_COLOR,
        "missile_before": before,
        "missile_after": figures.TRAJ_MISSILE2_COLOR,
        "mark": figures.TRAJ_MARK_COLOR,
        "hit": figures.TRAJ_HIT_COLOR,
        "miss": figures.TRAJ_MISS_COLOR,
        "guide": figures.TRAJ_GUIDE_COLOR,
        "source": ("figures.TRAJ_COLORS / TRAJ_MISSILE_COLOR / TRAJ_MISSILE2_COLOR / "
                   "TRAJ_MARK_COLOR / TRAJ_HIT_COLOR / TRAJ_MISS_COLOR / "
                   "TRAJ_GUIDE_COLOR / TRAJ_FALLBACK_COLOR"),
    }


# --------------------------------------------------------------------- 读产物


def read_csv_rows(path) -> list:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _num(v, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _round(v, digits):
    return None if v is None else round(float(v), digits)


def _columns(rows: list):
    """CSV 行 → `(t, x, y, z)` 四个平行列（`p` 是 `[x, y, z]`：x/z 水平、y 高度）。"""
    t = [_num(r.get("t_s"), 0.0) for r in rows]
    x = [_num(r.get("x_m"), 0.0) for r in rows]
    y = [_num(r.get("y_m"), 0.0) for r in rows]
    z = [_num(r.get("z_m"), 0.0) for r in rows]
    return t, x, y, z


def _slice(t, x, y, z, idx: list) -> dict:
    """按下标取子集，并落到前端要的精度（时间 3 位、位置 1 位 —— 位置本来就是米级）。"""
    return {"t": [_round(t[i], 3) for i in idx],
            "p": [[_round(x[i], 1), _round(y[i], 1), _round(z[i], 1)] for i in idx]}


def paths_of(summary: dict):
    """从任务摘要里挑出**图4 那一段**的产物路径。

    `figure=traj` 的摘要就是它自己；`both` / `all` 是合并摘要，图4 藏在 `parts` 里
    （`summarize_all()` 给每份 `part` 都写了显式 `figure` 键 —— 不再靠"缺省 = 图1"猜）。
    找不到就 `LookupError`（路由层折成 404，**不要**回落到图1 的产物）。
    """
    if not isinstance(summary, dict):
        raise LookupError("任务还没有结果")
    if summary.get("figure") == "traj":
        return dict(summary.get("paths") or {}), summary
    for part in summary.get("parts") or ():
        if isinstance(part, dict) and part.get("figure") == "traj":
            return dict(part.get("paths") or {}), part
    raise LookupError("这个任务里没有图4 的产物（`figure` 不是 traj，合并摘要里也没有 traj 那一段）")


REQUIRED_PRODUCTS = ("missile", "target", "segments", "manifest")


def _load(paths: dict) -> dict:
    """产物路径 → 「原始素材」（`build()` / `build_replay()` 共用一次读盘）。

    这里**只做读盘与归一**，不做抽稀、不做 payload 组装 —— 那一层在 `_assemble()` 里，
    于是沙盒能在同一份素材上多切出"逐点读数 + 事件表"，而查看器的输出一个字节都不变。
    """
    missing = [k for k in REQUIRED_PRODUCTS if not paths.get(k)]
    if missing:
        raise FileNotFoundError(f"图4 产物不齐，缺 {missing}（产物被清理过？）")
    for key in REQUIRED_PRODUCTS:
        if not Path(str(paths[key])).is_file():
            raise FileNotFoundError(f"图4 产物不在磁盘上：{key} = {paths[key]}")

    mis = read_csv_rows(paths["missile"])
    tgt = read_csv_rows(paths["target"])
    segs = read_csv_rows(paths["segments"])
    man = json.loads(Path(str(paths["manifest"])).read_text(encoding="utf-8"))
    run = dict(man.get("run") or {})
    scene = dict(man.get("scene") or {})
    anchor = dict(run.get("anchor") or {})
    t_beam = _num(anchor.get("t_beam_s"))
    t_end = _num(run.get("t_end_s"))

    mt, mx, my, mz = _columns(mis)
    tt, tx, ty, tz = _columns(tgt)
    mis_pts, tgt_pts = list(zip(mx, my, mz)), list(zip(tx, ty, tz))
    # 弹的额外列（回放读数用）。⚠ 这些列是 2026-10-02 P6 才加的：**旧产物没有**，
    # 所以一律按"列在不在"取值，缺列 → None，字段契约里降级成 pending（老产物照样能看）。
    mv = [_num(r.get("v_ms")) for r in mis]
    mrange = [_num(r.get("range_m")) for r in mis]
    mthrust = [_num(r.get("thrust_N"), 0.0) for r in mis]
    mair = [_num(r.get("air_speed_ms")) for r in mis]
    mvx = [_num(r.get("vx_ms")) for r in mis]
    mvy = [_num(r.get("vy_ms")) for r in mis]
    mvz = [_num(r.get("vz_ms")) for r in mis]
    max_ = [_num(r.get("ax_ms2")) for r in mis]
    may_ = [_num(r.get("ay_ms2")) for r in mis]
    maz_ = [_num(r.get("az_ms2")) for r in mis]
    tv = [_num(r.get("v_ms")) for r in tgt]              # 目标速度（目标表新列）
    extra_cols = {
        "mach": [_num(r.get("mach")) for r in mis],
        "n_g": [_num(r.get("n_g")) for r in mis],
        "sf_g": [_num(r.get("sf_g")) for r in mis],
        "req_g": [_num(r.get("req_g")) for r in mis],
        "aoa_deg": [_num(r.get("aoa_deg")) for r in mis],
        "aoa_eff_deg": [_num(r.get("aoa_eff_deg")) for r in mis],
        "dist_flown_m": [_num(r.get("dist_flown_m")) for r in mis],
    }
    # 列是否存在（判"能不能接内核值"，见 `_downgrade_spec()`）
    avail = {
        "missile": {"t_s", "x_m", "y_m", "z_m"},
        "target": {"t_s", "x_m", "y_m", "z_m"},
    }
    for key in ("v_ms", "range_m", "air_speed_ms", "vx_ms", "vy_ms", "vz_ms",
                "ax_ms2", "ay_ms2", "az_ms2"):
        if key in (mis[0] if mis else {}):
            avail["missile"].add(key)
    for key in ("v_ms",):
        if key in (tgt[0] if tgt else {}):
            avail["target"].add(key)
    for key in extra_cols:
        if key in (mis[0] if mis else {}):
            avail["missile"].add(key)

    segments = []
    for s in segs:
        key = str(s.get("color_key") or "")
        segments.append({
            "t0": _round(_num(s.get("t0_s")), 3), "t1": _round(_num(s.get("t1_s")), 3),
            "kind": str(s.get("kind") or ""), "label": str(s.get("label") or ""),
            "phase": str(s.get("phase") or ""), "color_key": key,
            "color": figures.TRAJ_COLORS.get(key, figures.TRAJ_FALLBACK_COLOR),
            "truncated": int(_num(s.get("truncated"), 0.0) or 0),
            "heading0_deg": _round(_num(s.get("heading0_deg")), 1),
            "heading1_deg": _round(_num(s.get("heading1_deg")), 1),
        })

    marks = []
    for m in run.get("marks") or ():
        t_mark = _num(m.get("t_s"))
        if t_mark is None:
            continue
        marks.append({"name": str(m.get("name") or ""), "t_s": _round(t_mark, 3),
                      "note": str(m.get("note") or ""),
                      "target": [_round(v, 1) for v in (_interp(tt, tgt_pts, t_mark)
                                                        or [0.0, 0.0, 0.0])],
                      "missile": [_round(v, 1) for v in (_interp(mt, mis_pts, t_mark)
                                                         or [0.0, 0.0, 0.0])]})
    return {
        "man": man, "run": run, "scene": scene, "anchor": anchor,
        "t_beam": t_beam, "t_end": t_end, "mis": mis, "tgt": tgt,
        "mt": mt, "mx": mx, "my": my, "mz": mz,
        "tt": tt, "tx": tx, "ty": ty, "tz": tz,
        "mis_pts": mis_pts, "tgt_pts": tgt_pts,
        "mv": mv, "mrange": mrange, "mthrust": mthrust,
        "mair": mair, "mvx": mvx, "mvy": mvy, "mvz": mvz,
        "max_": max_, "may_": may_, "maz_": maz_, "tv": tv, "extra_cols": extra_cols,
        "avail": avail,
        "segments": segments, "marks": marks,
    }


# --------------------------------------------------------------------- 查看器 payload


def _assemble(L: dict, *, points: int = DEFAULT_POINTS, job: str | None = None,
              tag: str | None = None, extra: dict | None = None,
              want_index: bool = False):
    """「原始素材」→ 查看器要吃的 JSON（`build()` 的唯一实现）。

    `want_index=True` 时额外返回抽稀用的下标（沙盒要拿它切「逐点读数」，见 `build_replay()`）。
    """
    mt, mx, my, mz = L["mt"], L["mx"], L["my"], L["mz"]
    tt, tx, ty, tz = L["tt"], L["tx"], L["ty"], L["tz"]
    segments, marks = L["segments"], L["marks"]
    t_beam, t_end = L["t_beam"], L["t_end"]

    # ---- 抽稀：阶段拐点 + 节点时刻**必须**留下 ----
    forced_t = set()
    for s in segments:
        for edge in (s["t0"], s["t1"]):
            if edge is None or not math.isfinite(edge):
                continue
            if t_end is not None and edge > t_end + 1e-9:
                continue
            forced_t.add(_nearest_index(tt, edge))
    forced_m = set()
    for m in marks:
        forced_t.add(_nearest_index(tt, m["t_s"]))
        forced_m.add(_nearest_index(mt, m["t_s"]))
    if t_beam is not None:                       # 开机点用 ceil：它是"第一个 t ≥ t_beam"的点
        forced_m.add(_ceil_index(mt, t_beam))

    im = decimate_indices(len(L["mis"]), points, forced_m)
    it = decimate_indices(len(L["tgt"]), points, forced_t)

    mis_track = _slice(mt, mx, my, mz, im)
    tgt_track = _slice(tt, tx, ty, tz, it)
    # ⚠ 切分点按**响应里给的那份数**（时间已经落到 3 位小数）算，这样客户端拿到 `t` / `t_beam_s`
    #   自己 `bisect` 一遍能复现同一个 `split_index`；用原始行算会差在 1e-4 s 上，
    #   "契约可复核"就没了（实测：真实行 34.4583 与 t_beam 34.4583343 在 3 位小数上相等）。
    split = len(im)
    if t_beam is not None and mis_track["t"]:
        split = bisect.bisect_left(mis_track["t"], _round(t_beam, 3))
    colors = palette()
    run = L["run"]
    scene = L["scene"]
    payload = {
        "ok": True, "job": job, "tag": tag or L["man"].get("tag"),
        "missile_name": run.get("missile") or "", "native": (extra or {}).get("native", ""),
        "hit": bool(run.get("hit")), "event": run.get("event") or "",
        "t_hit_s": _round(_num(run.get("t_hit_s")), 3),
        # 三个距离都发出去（A5）：`cpa_m` 才是"打得多准"，命中时 `min_separation_m`
        # 恒等于 `fuse_radius_m`（引信半径 10 m）——前端**不要**把后者写成"脱靶量"。
        # `cpa_m` 按原值出（6 位小数）：真 CPA 常在 1e-4 m 量级，按 2/3 位折会抹成 0.0。
        "cpa_m": _round(_num(run.get("cpa_m")), 6),
        "min_separation_m": _round(_num(run.get("min_separation_m")), 2),
        "fuse_radius_m": _round(_num(run.get("fuse_radius_m")), 2),
        "v_impact_m_s": _round(_num(run.get("v_impact_m_s")), 1),
        "max_alt_m": _round(_num(run.get("max_alt_m")), 1),
        "t_end_s": _round(t_end, 3), "t_beam_s": _round(t_beam, 3),
        "anchor": {k: L["anchor"].get(k) for k in
                   ("mode", "lock_distance_m", "t_beam_s", "range_at_beam_m", "completed",
                    "heading_at_beam_deg", "react_delay_s", "t_react_s")},
        "beta": _round(_num(run.get("beta")), 1), "gamma": _round(_num(run.get("gamma")), 2),
        "tier": L["man"].get("tier"), "backend": L["man"].get("backend"),
        "launch": [_round(v, 1) for v in (scene.get("launch_position_m") or [0.0, 0.0, 0.0])],
        "target0": [_round(v, 1) for v in (scene.get("target_position_m") or [0.0, 0.0, 0.0])],
        "points": {"requested": int(points), "missile": len(im), "target": len(it)},
        "rows": {"missile": len(L["mis"]), "target": len(L["tgt"])},
        "missile": {"t": mis_track["t"], "p": mis_track["p"], "split_index": int(split),
                    "before_color": colors["missile_before"],
                    "after_color": colors["missile_after"]},
        "target": {"t": tgt_track["t"], "p": tgt_track["p"]},
        "segments": segments, "marks": marks, "colors": colors,
        "axis_note": "x / z 是水平面（航向 0° = +x、90° = +z），y 是高度",
    }
    if not want_index:
        return payload
    return payload, {"missile": im, "target": it, "split": int(split)}


def build(paths: dict, *, points: int = DEFAULT_POINTS, job: str | None = None,
          tag: str | None = None, extra: dict | None = None) -> dict:
    """产物路径 → 查看器要吃的 JSON。

    `paths` 就是 `summarize_traj()` 里那份（`missile` / `target` / `segments` / `manifest`）。
    全程只**读**盘：一个求解器调用都没有（`solver.run` 零调用由测试钉住）。
    """
    return _assemble(_load(paths), points=points, job=job, tag=tag, extra=extra)


# --------------------------------------------------------------------- 回放：逐点读数


def _attitude(ts, xs, ys, zs) -> tuple:
    """位置列 → 朝向角（`yaw_deg` 航向、`pitch_deg` 俯仰，度）。

    **中心差分**（两端退化成单侧）：朝向来自**轨迹本身**，不是常量、也不是另外拍的。
    约定与全仓一致：航向 0° = +x、90° = +z；俯仰正 = 爬升。
    """
    n = len(ts)
    yaw, pitch = [0.0] * n, [0.0] * n
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        dx, dy, dz = xs[b] - xs[a], ys[b] - ys[a], zs[b] - zs[a]
        h = math.hypot(dx, dz)
        yaw[i] = math.degrees(math.atan2(dz, dx)) % 360.0 if (dx or dz) else 0.0
        pitch[i] = math.degrees(math.atan2(dy, h)) if (h or dy) else 0.0
    return yaw, pitch


def _cumulative(ts, xs, ys, zs) -> list:
    """沿采样折线累积弧长（米）。

    ⚠ **不进响应、不进悬停框**：内核有 `distance_flown_m` 列（第一原则："先 grep 内核"）。
    这里保留它只有一个用途 —— P6 把内核列接进来之后，用它当**对拍照**
    （`assert |弧长 − 内核 distance_flown_m| / 内核值 < 容差`）。
    """
    out = [0.0]
    for i in range(1, len(ts)):
        out.append(out[-1] + math.dist((xs[i - 1], ys[i - 1], zs[i - 1]),
                                       (xs[i], ys[i], zs[i])))
    return out


def _axial_accel(ts, vs, half: int = 1) -> list:
    """沿航迹的加速度 `Δv/Δt`（米/秒²）—— **只作 P6 的对拍照**，不进响应。

    内核有 `accel_x/y/z_m_s2`（在速度方向上投影一下就是"轴向加速度"），所以悬停框里
    显示的那一列**必须**是内核值；这里保留差分实现，是为了接完之后能对拍
    （`assert |差分 − 内核投影| < 容差`），也能在产物还没扩列时验证自己的理解没错。
    `half` 与 `_speed_of()` 的窗口配套（目标侧为 `TARGET_HALF`）。
    """
    n = len(ts)
    out = [None] * n
    for i in range(n):
        if vs[i] is None:
            continue
        a, b = max(0, i - half), min(n - 1, i + half)
        if i == 0:
            b = min(n - 1, 2 * half)
        if i == n - 1:
            a = max(0, n - 1 - 2 * half)
        if b >= n or a < 0 or vs[a] is None or vs[b] is None or b <= a:
            continue
        span = ts[b] - ts[a]
        if span > 1e-9:
            out[i] = (vs[b] - vs[a]) / span
    return out


def _horiz(xs, zs, x0: float, z0: float) -> list:
    """水平距离（相对发射点，米）—— `sqrt(Δx² + Δz²)`。"""
    return [math.hypot(xs[i] - x0, zs[i] - z0) for i in range(len(xs))]


def _speed_of(ts, xs, ys, zs, half: int = 1) -> list:
    """由位置差分算速度标量 —— **只作 P6 的对拍照**，不进响应。

    内核有 `target_speed_m_s`（目标）与 `speed_m_s`（弹），悬停框显示的是内核列；
    这里保留差分实现是为了接完后对拍，以及在没有目标速度列的当下验证轨迹自洽
    （实测与想定输入 300 m/s 一致到 1.5% 以内，判据在 `tests/test_sandbox.py`）。

    ⚠ 两端的**跨度要和内部一致**（`i=0` 取 `[0, 2·half]`、末尾取对称窗口）：
    否则 `speed[0]` 用半跨、`speed[1]` 用全跨，`_axial_accel()` 在首点会差出一个
    假的大加速度（实测首点 −115 m/s²，就是这一步的假象）。
    ⚠ `half` 是**窗口**，不是精度选择：`results/traj_*.csv` 的位置只到 0.1 m，
    2 采样（0.042 s）窗口下量化噪声会放大成 ±58 m/s² 的假加速度 ——
    目标侧因此用 `half=TARGET_HALF`（±0.21 s）压掉量化噪声。
    """
    n = len(ts)
    out = [None] * n
    for i in range(n):
        a, b = max(0, i - half), min(n - 1, i + half)
        if i == 0:
            b = min(n - 1, 2 * half)
        if i == n - 1:
            a = max(0, n - 1 - 2 * half)
        span = ts[b] - ts[a]
        if span > 1e-9 and b > a:
            out[i] = math.dist((xs[a], ys[a], zs[a]), (xs[b], ys[b], zs[b])) / span
    return out


def _nice_step(span: float, target: int = 5) -> float:
    """0/1/2/5×10ⁿ 里挑一个"步长"，让 0..span 大约分 `target` 段。"""
    if span <= 0:
        return 1.0
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= mag * mult:
            return mag * mult
    return mag * 10.0


def _tick_text(v: float) -> str:
    """刻度文本：≥1000 用 `k` 后缀（参考站口径），否则整数。"""
    if abs(v) >= 1000.0 - 1e-9:
        return f"{v / 1000.0:.0f}k"
    return f"{v:.0f}"


def _axis(lo: float, hi: float, label: str) -> dict:
    """一条轴的刻度：从 0（或 lo）到 hi，步长走 0/1/2/5 阶梯，文本带 `k` 后缀。"""
    lo = min(0.0, float(lo))
    hi = max(0.0, float(hi))
    step = _nice_step(hi - lo)
    ticks, v = [], math.floor(lo / step) * step
    while v <= hi + step * 1e-9:
        if abs(v) < step * 1e-9:
            v = 0.0
        ticks.append(round(v, 6))
        v += step
    return {"label": label, "min": round(lo, 3), "max": round(hi, 3), "step": step,
            "ticks": ticks, "texts": [_tick_text(t) for t in ticks]}


def axis_spec(L: dict) -> dict:
    """三轴刻度（带 `k` 后缀与"方向 + 单位"轴名，照参考站；轴名按我们的真实坐标写）。

    ⚠ 参考站写的是 `高度（米向距离 - Z）`（把"高度"和"Z"混在一句里，自相矛盾）；
    我们是 `y` = 高度、`z` = 侧向，所以这里按实际坐标命名 —— 有意偏差，见 `docs/SANDBOX.md`。
    """
    xs = [v for v in L["mx"] + L["tx"] if v is not None]
    ys = [v for v in L["my"] + L["ty"] if v is not None]
    zs = [v for v in L["mz"] + L["tz"] if v is not None]
    return {
        "x": _axis(min(xs or [0.0]), max(xs or [0.0]), "前向距离 - X（米）"),
        "y": _axis(0.0, max(ys or [0.0]), "高度 - Y（米）"),
        "z": _axis(min(zs or [0.0]), max(zs or [0.0]), "侧向距离 - Z（米）"),
    }


# --------------------------------------------------------------------- 回放：悬停字段契约


def hover_spec() -> list:
    """悬停信息框的**字段契约**（顺序照参考站；服务端定义，前端只渲染，不写死标签）。

    每项：`key`（数据键）/ `label` / `unit` / `decimals` / `group`（`main` = 参考站那 9 行，
    `extra` = 别的内核列）/ `merge_with`（与上一行同行显示，如"速度, M1.86"）/
    `source`（按实体给 `kernel` / `derived` / `n/a` / `pending`）/ `hint`。
    ⚠ 第一原则"先 grep 内核，别急着造轮子"已落地：内核 68 列里的 `air_speed_m_s` /
    `accel_x/y/z_m_s2` / `distance_flown_m` / 三个过载 / `mach` / 两个攻角 / `target_speed_m_s`
    现在都在产物里（`FIELD_COLUMNS` 逐字段声明要哪些列、去哪张表查），外壳只搬运或投影。
    四种 `source` 的取值域：`kernel`（直接取内核列）/ `derived`（内核没有、由内核列折出来：
    `horizontal_m` 与 `accel_ms2`）/ `n/a`（这个量对该实体不成立：目标没有体轴/推力/制导，
    所以没有马赫数、攻角、过载的定义）/ `pending`（该实体侧需要的列还没进产物）。
    ⚠ 这里写的是**意图**：列不存在时 `_downgrade_spec()` 会把 `kernel`/`derived` 降级成
    `pending`（前端显示"待接入"）—— 于是"旧产物照样能看"与"新列接上后自动变成内核值"
    两件事由同一张表驱动，不会出现两处口径。
    """
    ms, tg = "missile", "target"
    return [
        {"key": "t_s", "label": "时间", "unit": "秒", "decimals": 2, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_KERNEL}},
        {"key": "horizontal_m", "label": "水平距离", "unit": "米", "decimals": 0, "group": "main",
         "source": {ms: SRC_DERIVED, tg: SRC_DERIVED}, "hint": HORIZONTAL_HINT},
        {"key": "alt_m", "label": "高度", "unit": "米", "decimals": 0, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_KERNEL}},
        {"key": "speed_ms", "label": "速度", "unit": "米/秒", "decimals": 1, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_KERNEL},
         "hint": "弹取内核 speed_m_s；目标取内核 target_speed_m_s（目标表 v_ms 列）"},
        {"key": "mach", "label": "马赫数", "unit": "M", "decimals": 2, "group": "main",
         "merge_with": "speed_ms", "source": {ms: SRC_KERNEL, tg: SRC_NA},
         "hint": "内核 mach 列（= |air| / sound(alt)，外壳不派生）"},
        {"key": "accel_ms2", "label": "加速度", "unit": "米/秒²", "decimals": 2, "group": "main",
         "source": {ms: SRC_DERIVED, tg: SRC_NA},
         "hint": ACCEL_HINT},
        {"key": "range_m", "label": "到目标的距离", "unit": "米", "decimals": 0, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_KERNEL},
         "hint": "内核 range_m（弹目斜距）；两张表同一条时间轴"},
        {"key": "n_g", "label": "G载荷", "unit": "G", "decimals": 2, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_NA},
         "hint": "内核 trajectory_normal_g（轨迹法向过载）；比力/指令过载见 extra 组"},
        {"key": "aoa_deg", "label": "攻角", "unit": "°", "decimals": 1, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_NA},
         "hint": "内核 aoa_deg（运动学：机体 x 轴与空速的夹角，非负）"},
        {"key": "flown_m", "label": "已行驶距离", "unit": "米", "decimals": 0, "group": "main",
         "source": {ms: SRC_KERNEL, tg: SRC_NA},
         "hint": "内核 distance_flown_m（不由前端积分）"},
        {"key": "sf_g", "label": "比力过载", "unit": "G", "decimals": 2, "group": "extra",
         "source": {ms: SRC_KERNEL, tg: SRC_NA}, "hint": "内核 specific_force_g"},
        {"key": "req_g", "label": "指令过载", "unit": "G", "decimals": 2, "group": "extra",
         "source": {ms: SRC_KERNEL, tg: SRC_NA}, "hint": "内核 requested_g（制导指令）"},
        {"key": "aoa_eff_deg", "label": "有效攻角", "unit": "°", "decimals": 1, "group": "extra",
         "source": {ms: SRC_KERNEL, tg: SRC_NA},
         "hint": "内核 aoa_eff_deg（aero() 实际用的 nose↔flow，含力臂/角速度项）"},
    ]


#: 字段 → 需要哪些**产物列名**（`kernel` 意图的字段用；`n/a` 的实体侧不查列）。
#: 值形如 `{实体: ((列名, …), 去哪张表查)}` —— 默认查自己那张表；`range_m` 特殊：
#: 目标的"到目标距离"取的是**弹表**那一列（两张表同一条时间轴，见 `_same_time_axis()`）。
FIELD_COLUMNS = {
    "t_s": {"missile": (("t_s",), "missile"), "target": (("t_s",), "target")},
    "horizontal_m": {"missile": (("x_m", "z_m"), "missile"),
                     "target": (("x_m", "z_m"), "target")},
    "alt_m": {"missile": (("y_m",), "missile"), "target": (("y_m",), "target")},
    "speed_ms": {"missile": (("v_ms",), "missile"), "target": (("v_ms",), "target")},
    "mach": {"missile": (("mach",), "missile")},
    "accel_ms2": {"missile": (("ax_ms2", "ay_ms2", "az_ms2", "vx_ms", "vy_ms", "vz_ms"),
                              "missile")},
    "range_m": {"missile": (("range_m",), "missile"), "target": (("range_m",), "missile")},
    "n_g": {"missile": (("n_g",), "missile")},
    "aoa_deg": {"missile": (("aoa_deg",), "missile")},
    "flown_m": {"missile": (("dist_flown_m",), "missile")},
    "sf_g": {"missile": (("sf_g",), "missile")},
    "req_g": {"missile": (("req_g",), "missile")},
    "aoa_eff_deg": {"missile": (("aoa_eff_deg",), "missile")},
}


def _downgrade_spec(spec: list, avail: dict) -> list:
    """按**产物里实际有哪些列**把 `kernel` / `derived` 意图降级成 `pending`（缺列的字段）。

    ⚠ `derived` 也要查列：`accel_ms2` 虽然是我们投影出来的，但它的输入（三分量加速度与
    速度）本身是内核列 —— 老产物没有这些列时，"我们能算"就是假的，必须一起降级成
    `pending`，否则契约说"算得出来"而 `series` 里根本没有这一列（前端只能显示 `—`）。
    `n/a` **不降级**：那是"这个量对目标不成立"的静态结论。
    """
    out = []
    for f in spec:
        src = dict(f["source"])
        for who, (need, table) in (FIELD_COLUMNS.get(f["key"]) or {}).items():
            if src.get(who) in (SRC_KERNEL, SRC_DERIVED) \
                    and not set(need) <= set(avail.get(table) or ()):
                src[who] = SRC_PENDING
        item = dict(f)
        item["source"] = src
        out.append(item)
    return out


def _keys_with(spec: list, kind: str) -> list:
    """按**字段键**汇总某一种来源（任一实体侧是它就算）—— `pending_keys` / `na_keys` 等用。"""
    return sorted({f["key"] for f in spec if kind in set((f["source"] or {}).values())})


#: 悬停框里"待接入"的字段与它们在内核侧的真源头（缺列时的提示；接了就不显示）
PENDING_SOURCE = {
    "mach": "内核 mach 列（air_speed_m_s ÷ sound(alt)）",
    "accel_ms2": "内核 accel_x/y/z_m_s2 在速度方向的投影",
    "n_g": "内核 trajectory_normal_g",
    "sf_g": "内核 specific_force_g",
    "req_g": "内核 requested_g",
    "aoa_deg": "内核 aoa_deg",
    "aoa_eff_deg": "内核 aoa_eff_deg",
    "flown_m": "内核 distance_flown_m",
    "speed_ms": "内核 target_speed_m_s（目标侧；弹侧本来就有）",
}


#: 逐点读数里给**绘图**用、但**不进悬停框**的键（朝向 = 实体标记的姿态）
DRAW_ONLY_KEYS = ("yaw_deg", "pitch_deg")


# --------------------------------------------------------------------- 回放：事件表


def _entity_pos(L: dict, entity: str, t: float):
    if entity == "target":
        return [_round(v, 1) for v in (_interp(L["tt"], L["tgt_pts"], t) or [0.0, 0.0, 0.0])]
    return [_round(v, 1) for v in (_interp(L["mt"], L["mis_pts"], t) or [0.0, 0.0, 0.0])]


def _event(name: str, label: str, t, entity: str, L: dict, *, text: str = "",
           extra: dict | None = None) -> dict:
    item = {"name": name, "label": label, "t_s": _round(t, 3), "entity": entity,
            "pos": _entity_pos(L, entity, t) if t is not None else None,
            "text": text or f"{label}: {(_round(t, 2) or 0.0):.2f} 秒"}
    if extra:
        item.update(extra)
    return item


def event_list(L: dict) -> list:
    """沙盒的**事件表**：发射 / 燃尽 / crank 开始 / crank 转完 / 开机 / 转 39 / 转完 / 命中或脱靶。

    时刻**全部来自产物**（marks / segments / `thrust_N` 列），一个解算都没有；
    `text` 在服务端就拼好（命中 `命中: 69.17 秒（最近接近 0.003824 m，引信半径 10.0 m）`、
    脱靶 `脱靶: … 秒（最近接近 … m）`），前端只负责画 —— 这样"事件标点写什么"是可测的，
    不靠前端字符串拼。⚠ 命中时那个 10 m 是**引信半径**（A5 之后 `min_separation_m` 的语义），
    不许写成"脱靶量"。
    """
    run = L["run"]
    segs = L["segments"]
    events = []
    t_launch = L["mt"][0] if L["mt"] else 0.0
    events.append(_event("launch", "发射", t_launch, "missile", L))

    # 燃尽 = thrust_N > 0 的最后一个采样（产物列算出来的，不是另拍的常量）
    powered = [L["mt"][i] for i, th in enumerate(L["mthrust"]) if th and th > 0.0]
    if powered:
        events.append(_event("burnout", "燃尽", powered[-1], "missile", L,
                             text=f"燃尽: {powered[-1]:.2f} 秒（推力归零）"))

    def seg_edge(kind: str, edge: str):
        for s in segs:
            if s["kind"] == kind and s[edge] is not None:
                return s
        return None

    turn1 = seg_edge("turn", "t1")            # 转入 crank 那一段的结束
    turn2 = None                              # 转入 39 那一段（航向 90 的那条腿）
    for s in segs:
        if s["kind"] == "turn" and s["heading1_deg"] is not None \
                and abs(s["heading1_deg"] - 90.0) < 1e-6:
            turn2 = s
            break

    if turn1 is not None:
        events.append(_event("crank_start", "crank 开始", turn1["t0"], "target", L))
        events.append(_event("crank_done", "crank 转完", turn1["t1"], "target", L,
                             text=f"crank 转完: {turn1['t1']:.2f} 秒（航向 {turn1['heading1_deg']:.0f}°）"))
    if L["t_beam"] is not None:
        events.append(_event("seeker_on", "导引头开机", L["t_beam"], "missile", L,
                             text=f"开机: {L['t_beam']:.2f} 秒（R = "
                                  f"{(_round(_num(L['anchor'].get('range_at_beam_m')), 0) or 0) / 1000:.0f} km）"))
    t_react = _num(L["anchor"].get("t_react_s"))
    if t_react is not None:
        events.append(_event("beam_start", "转 39", t_react, "target", L,
                             text=f"转 39: {t_react:.2f} 秒（延迟 "
                                  f"{(_num(L['anchor'].get('react_delay_s'), 0.0) or 0.0):.1f} s）"))
    if turn2 is not None:
        events.append(_event("beam_done", "转 39 完成", turn2["t1"], "target", L))

    t_end = L["t_end"]
    hit = bool(run.get("hit"))
    # ⚠ A5（task-23）把三个"距离"拆开了，**别再合成一个"脱靶量"**：
    #   `min_separation_m` —— 终止事件之前的最小弹目距离；**命中时它就等于引信半径**
    #                        （默认工况 10 m），所以那个数**不是**脱靶量；
    #   `cpa_m`           —— **真最近接近距离**（命中工况要关引信复跑一次才量得到，
    #                        没量就是空；未命中时它 == `min_separation_m`）；
    #   `fuse_radius_m`   —— 内核自报的引信半径（0 = 没引信或本次关了）。
    # 文案口径：命中 → "最近接近 …（引信半径 …）"；脱靶 → "最近接近 …"（不写"脱靶量"）。
    min_sep = _round(_num(run.get("min_separation_m")), 2)
    cpa = _round(_num(run.get("cpa_m")), 6)
    fuse = _round(_num(run.get("fuse_radius_m")), 2)
    if t_end is not None:
        if hit:
            bits = []
            if cpa is not None and cpa > 0:
                bits.append(f"最近接近 {cpa:.6g} m")
            if fuse:
                bits.append(f"引信半径 {fuse:.1f} m")
            text = f"命中: {t_end:.2f} 秒" + (f"（{'，'.join(bits)}）" if bits else "")
            label = "命中"
        else:
            near = cpa if cpa is not None else min_sep
            text = f"脱靶: {t_end:.2f} 秒" + (f"（最近接近 {near:.6g} m）" if near else "")
            label = "脱靶"
        events.append(_event("end", label, t_end, "missile", L, text=text,
                             extra={"hit": hit, "min_separation_m": min_sep, "cpa_m": cpa,
                                    "fuse_radius_m": fuse}))
    events.sort(key=lambda e: (e["t_s"] if e["t_s"] is not None else 0.0))
    return events


# --------------------------------------------------------------------- 回放：payload


def _series(L: dict, idx_m: list, idx_t: list) -> dict:
    """双方**逐点读数**（列式，只放**有数据**的列；契约说不出数据的列见 `hover_spec()`）。

    三类：① 内核产物列（`t_s` / `alt_m` / `range_m` / 速度 / `mach` / `n_g` / `sf_g` /
    `req_g` / `aoa_deg` / `aoa_eff_deg` / `flown_m`）；② 由内核列折出来的 `horizontal_m`
    与 `accel_ms2`（**加速度口径**：内核三分量在速度方向的投影，见 `ACCEL_HINT`）；
    ③ **绘图**用的姿态角（`yaw_deg` / `pitch_deg`，见 `DRAW_ONLY_KEYS`）。
    ⚠ 老产物缺列时对应的键**整列不出现**（契约里那几项同时被降级成 `pending`）。
    """
    mt, mx, my, mz = L["mt"], L["mx"], L["my"], L["mz"]
    tt, tx, ty, tz = L["tt"], L["tx"], L["ty"], L["tz"]
    avail = L["avail"]
    # 弹的朝向优先用**内核速度三分量**（比位置差分准，且不受 0.1 m 量化影响）；缺列才退回去。
    # ⚠ 写成条件表达式而不是 if/else：后者会把下面那行只改缩进，`git diff -w` 会把它算成
    #   "没变"，于是 `--stat` 与 `-w --stat` 不一致（本仓要求两者逐行一致）。
    has_velocity = {"vx_ms", "vy_ms", "vz_ms"} <= avail["missile"]
    myaw, mpitch = (_attitude_velocity(L) if has_velocity else _attitude(mt, mx, my, mz))
    tyaw, tpitch = _attitude(tt, tx, ty, tz)
    x0, z0 = (mx[0] if mx else 0.0), (mz[0] if mz else 0.0)
    mh, th = _horiz(mx, mz, x0, z0), _horiz(tx, tz, x0, z0)
    # 两张产物表是**同一条时间轴**（实测 `t_s` 逐位相同），所以内核 `range_m` 直接按下标对齐。
    # `build_replay()` 之前会先断言这一点；不成立就得改成插值，别默默错位。
    mrng = L["mrange"]
    # `avail` 里装的是**产物列名**（不是字段键）：加速度那一路要的是六列都在
    accel_ok = set(FIELD_COLUMNS["accel_ms2"]["missile"][0]) <= avail["missile"]
    accel = _axial_from_kernel(L) if accel_ok else None

    def pack(t, y, horiz, rng, speed, yaw, pitch, idx, extra=None):
        out = {
            "t_s": [_round(t[i], 3) for i in idx],
            "alt_m": [_round(y[i], 1) for i in idx],
            "horizontal_m": [_round(horiz[i], 1) for i in idx],
            "range_m": [_round(rng[i], 2) if rng[i] is not None else None for i in idx],
            "yaw_deg": [_round(yaw[i], 2) for i in idx],
            "pitch_deg": [_round(pitch[i], 2) for i in idx],
        }
        if speed is not None:
            out["speed_ms"] = [_round(speed[i], 3) if speed[i] is not None else None for i in idx]
        for key, col in (extra or {}).items():
            if col is not None:
                out[key] = [_round(col[i], 3) if col[i] is not None else None for i in idx]
        return out

    mis_extra = {
        "accel_ms2": accel,
        "mach": L["extra_cols"]["mach"] if "mach" in avail["missile"] else None,
        "n_g": L["extra_cols"]["n_g"] if "n_g" in avail["missile"] else None,
        "sf_g": L["extra_cols"]["sf_g"] if "sf_g" in avail["missile"] else None,
        "req_g": L["extra_cols"]["req_g"] if "req_g" in avail["missile"] else None,
        "aoa_deg": L["extra_cols"]["aoa_deg"] if "aoa_deg" in avail["missile"] else None,
        "aoa_eff_deg": (L["extra_cols"]["aoa_eff_deg"]
                        if "aoa_eff_deg" in avail["missile"] else None),
        "flown_m": (L["extra_cols"]["dist_flown_m"]
                    if "dist_flown_m" in avail["missile"] else None),
    }
    tgt_speed = L["tv"] if "v_ms" in avail["target"] else None
    return {
        "missile": pack(mt, my, mh, mrng, L["mv"], myaw, mpitch, idx_m, mis_extra),
        # 目标只有位置 + 速度（新列）；马赫数/攻角/过载/已行驶距离对目标不成立（契约里是 n/a）
        "target": pack(tt, ty, th, mrng, tgt_speed, tyaw, tpitch, idx_t),
    }


def _axial_from_kernel(L: dict) -> list:
    """内核三分量加速度 → **沿速度方向**的标量（米/秒²）：`(ax,ay,az)·v̂`。

    这是本仓的**投影**（不是重造内核公式）：`ax/ay/az` 与 `vx/vy/vz` 都是内核列，
    这里只做一次点积。`|v| = 0` 的点（理论上只有 t=0 之前）返回 `None`。
    """
    out = []
    for i in range(len(L["max_"])):
        vx, vy, vz = L["mvx"][i], L["mvy"][i], L["mvz"][i]
        ax, ay, az = L["max_"][i], L["may_"][i], L["maz_"][i]
        if None in (vx, vy, vz, ax, ay, az):
            out.append(None)
            continue
        n = math.sqrt(vx * vx + vy * vy + vz * vz)
        out.append((ax * vx + ay * vy + az * vz) / n if n > 1e-9 else None)
    return out


def _attitude_velocity(L: dict) -> tuple:
    """用**内核速度三分量**算朝向（弹侧；比位置差分更准，也不受 0.1 m 量化影响）。"""
    yaw, pitch = [], []
    for i in range(len(L["mvx"])):
        vx, vy, vz = L["mvx"][i], L["mvy"][i], L["mvz"][i]
        if None in (vx, vy, vz):
            yaw.append(0.0)
            pitch.append(0.0)
            continue
        h = math.hypot(vx, vz)
        yaw.append(math.degrees(math.atan2(vz, vx)) % 360.0 if (vx or vz) else 0.0)
        pitch.append(math.degrees(math.atan2(vy, h)) if (h or vy) else 0.0)
    return yaw, pitch


def _same_time_axis(L: dict) -> bool:
    """两张产物表是不是**同一条时间轴**（`range_m` 按下标对齐的前提）。"""
    mt, tt = L["mt"], L["tt"]
    return len(mt) == len(tt) and all(abs(a - b) < 1e-9 for a, b in zip(mt, tt))


def build_replay(paths: dict, *, points: int = DEFAULT_POINTS, job: str | None = None,
                 tag: str | None = None, extra: dict | None = None) -> dict:
    """产物路径 → **空战沙盒**（回放）要吃的 JSON。

    在 `build()` 的全套之上加：`replay`（时间轴/倍速）、`events`（事件标点，文本已拼好）、
    `series`（双方逐点读数 + 姿态）、`axes`（km 刻度）、`hover`（悬停框字段契约）、
    `entities`（图例：线型 + 配色）、`follow`（镜头模式）。

    与 `build()` 一样**只读产物、不解算**；抽稀策略与它**完全同一套**
    （阶段拐点 + 节点时刻必留），所以 `series` 的下标与 `missile.p`/`target.p` 一一对应。
    """
    L = _load(paths)
    payload, idx = _assemble(L, points=points, job=job, tag=tag, extra=extra, want_index=True)
    colors = payload["colors"]
    mt = L["mt"]
    dt = 0.0
    if len(mt) > 1:
        gaps = sorted(mt[i] - mt[i - 1] for i in range(1, len(mt)))
        dt = gaps[len(gaps) // 2] if gaps else 0.0
    payload["replay"] = {
        "t0": 0.0, "t1": payload["t_end_s"],
        "speeds": list(REPLAY_SPEEDS), "speed_default": REPLAY_SPEED_DEFAULT,
        "step_s": _round(dt, 4),
        "note": "倍速留左栏；播放控件与进度条在主视图顶部（照参考站实测）",
    }
    payload["events"] = event_list(L)
    if not _same_time_axis(L):
        raise ValueError("两张 traj 产物表的 `t_s` 不是同一条时间轴 —— "
                         "`range_m` 不能按下标对齐，得改成插值（别默默错位）")
    payload["series"] = _series(L, idx["missile"], idx["target"])
    payload["axes"] = axis_spec(L)
    spec = _downgrade_spec(hover_spec(), L["avail"])          # 缺列的 kernel 字段 → pending
    payload["hover"] = {
        "note": "框与回放时刻无关：悬停到哪一点就显示那一点（取最近采样）",
        "fields": spec,
        "main_order": [f["key"] for f in spec if f["group"] == "main"],
        "pending_keys": _keys_with(spec, SRC_PENDING),
        "derived_keys": _keys_with(spec, SRC_DERIVED),
        "na_keys": _keys_with(spec, SRC_NA),
        "pending_sources": dict(PENDING_SOURCE),
        "source_enum": [SRC_KERNEL, SRC_DERIVED, SRC_NA, SRC_PENDING],
        "draw_only_keys": list(DRAW_ONLY_KEYS),
        "products": {who: sorted(cols) for who, cols in L["avail"].items()},
        "discipline": "内核输出列里有的量一律接出来（外壳不派生）；缺列的显示'待接入'、"
                      "对目标不成立的量显示'不适用'；差额实现只在 tests 里当对拍照",
    }
    payload["entities"] = {
        "missile": {"name": payload["missile_name"] or "导弹", "style": "solid",
                    "colors": [colors["missile_before"], colors["missile_after"]],
                    "labels": ["开机前", "开机后"]},
        "target": {"name": "目标", "style": "dashed",
                   "colors": [s["color"] for s in payload["segments"]] or [colors["fallback"]],
                   "labels": [s["label"] or s["color_key"] for s in payload["segments"]]},
    }
    payload["follow"] = [{"key": k, "label": v} for k, v in FOLLOW_MODES]
    payload["follow_default"] = FOLLOW_DEFAULT
    payload["axis_note"] = ("x / z 是水平面（航向 0° = +x、90° = +z），y 是高度；"
                            "刻度用 k 后缀，轴名带方向与单位")
    return payload

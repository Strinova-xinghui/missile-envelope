# -*- coding: utf-8 -*-
"""图3 的**交互式 3D 数据层**：把已经落盘的 traj 产物折成前端 WebGL 查看器要吃的 JSON。

**为什么单独一个模块**（而不是塞进 `webui.py`）：
写入侧与读取侧要能分开测 —— 本模块**只读产物**（`traj_<tag>_{missile,target,segments}.csv`
与 `traj_<tag>.json`），**不 import 求解器、不 import workflow**，所以"这个接口不解算"这条
判据可以用毫秒级单测钉住（路由层那条走 HTTP，见 `tests/test_viewer3d.py`）。

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
    """从任务摘要里挑出**图3 那一段**的产物路径。

    `figure=traj` 的摘要就是它自己；`both` / `all` 是合并摘要，图3 藏在 `parts` 里
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
    raise LookupError("这个任务里没有图3 的产物（`figure` 不是 traj，合并摘要里也没有 traj 那一段）")


REQUIRED_PRODUCTS = ("missile", "target", "segments", "manifest")


def build(paths: dict, *, points: int = DEFAULT_POINTS, job: str | None = None,
          tag: str | None = None, extra: dict | None = None) -> dict:
    """产物路径 → 查看器要吃的 JSON。

    `paths` 就是 `summarize_traj()` 里那份（`missile` / `target` / `segments` / `manifest`）。
    全程只**读**盘：一个求解器调用都没有（`solver.run` 零调用由测试钉住）。
    """
    missing = [k for k in REQUIRED_PRODUCTS if not paths.get(k)]
    if missing:
        raise FileNotFoundError(f"图3 产物不齐，缺 {missing}（产物被清理过？）")
    for key in REQUIRED_PRODUCTS:
        if not Path(str(paths[key])).is_file():
            raise FileNotFoundError(f"图3 产物不在磁盘上：{key} = {paths[key]}")

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

    im = decimate_indices(len(mis), points, forced_m)
    it = decimate_indices(len(tgt), points, forced_t)

    mis_track = _slice(mt, mx, my, mz, im)
    tgt_track = _slice(tt, tx, ty, tz, it)
    # ⚠ 切分点按**响应里给的那份数**（时间已经落到 3 位小数）算，这样客户端拿到 `t` / `t_beam_s`
    #   自己 `bisect` 一遍能复现同一个 `split_index`；用原始行算会差在 1e-4 s 上，
    #   "契约可复核"就没了（实测：真实行 34.4583 与 t_beam 34.4583343 在 3 位小数上相等）。
    split = len(im)
    if t_beam is not None and mis_track["t"]:
        split = bisect.bisect_left(mis_track["t"], _round(t_beam, 3))
    colors = palette()
    payload = {
        "ok": True, "job": job, "tag": tag or man.get("tag"),
        "missile_name": run.get("missile") or "", "native": (extra or {}).get("native", ""),
        "hit": bool(run.get("hit")), "event": run.get("event") or "",
        "t_hit_s": _round(_num(run.get("t_hit_s")), 3),
        "miss_m": _round(_num(run.get("miss_m")), 1),
        "v_impact_m_s": _round(_num(run.get("v_impact_m_s")), 1),
        "max_alt_m": _round(_num(run.get("max_alt_m")), 1),
        "t_end_s": _round(t_end, 3), "t_beam_s": _round(t_beam, 3),
        "anchor": {k: anchor.get(k) for k in
                   ("mode", "lock_distance_m", "t_beam_s", "range_at_beam_m", "completed",
                    "heading_at_beam_deg", "react_delay_s", "t_react_s")},
        "beta": _round(_num(run.get("beta")), 1), "gamma": _round(_num(run.get("gamma")), 2),
        "tier": man.get("tier"), "backend": man.get("backend"),
        "launch": [_round(v, 1) for v in (scene.get("launch_position_m") or [0.0, 0.0, 0.0])],
        "target0": [_round(v, 1) for v in (scene.get("target_position_m") or [0.0, 0.0, 0.0])],
        "points": {"requested": int(points), "missile": len(im), "target": len(it)},
        "rows": {"missile": len(mis), "target": len(tgt)},
        "missile": {"t": mis_track["t"], "p": mis_track["p"], "split_index": int(split),
                    "before_color": colors["missile_before"],
                    "after_color": colors["missile_after"]},
        "target": {"t": tgt_track["t"], "p": tgt_track["p"]},
        "segments": segments, "marks": marks, "colors": colors,
        "axis_note": "x / z 是水平面（航向 0° = +x、90° = +z），y 是高度",
    }
    return payload

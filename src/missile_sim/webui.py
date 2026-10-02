# -*- coding: utf-8 -*-
"""本机 Web 表单：填想定 → 跑求解器 → 出图（**纯标准库**，只用 `http.server`）。

三条路径，按耗时切：

| 入口 | 做什么 | 为什么这么切 |
| --- | --- | --- |
| `POST /api/single` | **同步**跑一次 `solver.run()`（fast 档实测 ~0.1 s） | 用户填完要立刻看到 `t_hit` / `max_alt` / 末速 / `event` / `backend` |
| `POST /api/submit` `kind=plot` | 后台任务：`run_plane(with_iso=False)`（约 5 s，matplotlib 出图） | 出图比求解慢两个数量级，不能挂住 HTTP 请求 |
| `POST /api/submit` `kind=scan` | 后台任务：`run_plane(with_iso=True)`（fast 1632 工况 ~24 s，standard 档 ~6 min） | 同上；页面对 `/progress/<id>` 轮询进度条 |
| `POST /api/submit` `figure=bg` | 后台任务：`run_bg()`（图2，扫描 ~20 s / 只出图秒级） | 同上 |
| `POST /api/submit` `figure=traj` | 后台任务：`run_traj()`（图3，两遍 ≈1~2 s；`traj_preview=1` 只画目标航迹、不解算，秒级） | 图3 不分扫描/出图，`kind` 只当排队标签用 |
| `POST /api/submit` `figure=both` | 后台任务：图1 + 图2 **顺序**跑在同一任务里 | 与 CLI 的 `--figure both` 对齐（曾经这里只跑图2 却宣称 both） |
| `POST /api/submit` `figure=all` | 后台任务：图1 + 图2 + 图3 **顺序**跑在同一任务里 | 与 CLI 的 `--figure all` 对齐 |
| `GET /viewer3d` | 可拖拽的 3D 查看器**整页**（静态 `viewer3d.html`，数据由下面那条接口喂） | 内嵌用 `<iframe>`、另给「在新标签页打开」；`?bg=transparent` 走透明底 |
| `GET /api/viewer3d/<job_id>` | 把**已经跑完的**图3 任务折成查看器要吃的 JSON（默认 800 点，`?points=` 可覆盖） | 只读产物、**不再解算**（`solver.run` 零调用）；抽稀保留阶段拐点与节点时刻 |

`figure` 的五个取值（下拉里全都有）与 CLI 的 `--figure` **一一对应**：
`plane` / `bg` / `traj` 单张，`both` = 图1+图2，`all` = 三张；`both` / `all` 的摘要用 `parts`
分列每张图（每份都自带 `figure` 键，页面不靠"缺省 = 图1"猜）。

`/api/viewer3d/<job_id>` 的数据层在 `traj3d.py`（纯标准库、只读 `results/traj_*.csv|json`），
接口与抽稀口径见该模块 docstring 与 `docs/WEBUI.md` §8。

对外接口：`serve(host, port, open_browser)` / `make_server(...)` / `WebState` /
`python -m missile_sim.webui`。

⚠ **两个技术雷，都在本文件里处理掉**：

1. **import 期绝不起服务**。`Engine` 用 `ProcessPoolExecutor`，Windows 的 spawn 会把主模块
   **再执行一遍**：`python -m missile_sim.webui` 走 `init_main_from_name`，
   `python src/missile_sim/webui.py` 走 `init_main_from_path`（那一次的 `__name__` 是
   `__mp_main__`，所以 `if __name__ == "__main__"` 正好挡住）。本文件因此：起服务只在
   `__main__` 分支里；`make_server()` 另加一道 `SERVER_STARTS` 计数，测试用子进程验
   "import 完没有服务"。
   附带一条优化：模块顶层**不 import matplotlib 那条链**（`workflow` → `figures`），
   改为首次请求时懒加载 —— 否则每个 worker 子进程都要白付一次 matplotlib 的导入时间。
2. **扫描不能同步阻塞 HTTP**。`scan` / `plot` 一律丢后台线程，页面拿任务 id 轮询
   `/progress/<id>`；只有快路径 `solver.run()` 是同步的。

写 scope：本文件 + `configs/web_default.json` + `tests/test_webui*.py`
（见 docs/RESTART-PLAN.md §5；图3 的接入只动本文件与新增的 `tests/test_webui_traj.py`；
3D 查看器另加 `traj3d.py` 与 `webui_static/viewer3d.*`，见 docs/WEBUI.md §8）。
行尾 LF：`.gitattributes` 是 `* -text`，混行尾会被 `git diff -w` 抓出来。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from html import escape as _esc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import engine, pool, solver
from .spec import DEFAULT_MISSILE, FIG_DIR, RESULT_DIR, ROOT, TIERS, Scene

CONFIG_PATH = ROOT / "configs" / "web_default.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_LOG_LINES = 200                      # 每个任务保留的日志行数（页面上只显示尾部）
SERVER_STARTS = 0                        # 本进程起过几个服务（测试用来验"import 期不起服务"）
TAG_RE = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")

#: 表单/JSON 里**属于 Web 层**、不该喂给 `targets.build_scene()` 的键。
#: 少写一个，A1 的 `build_scene()` 就会因为"不认识的字段"把正常提交判成非法输入
#: （它那边是硬报错，见 targets.py 的 `_FORM_KEYS`）。
#: ⚠ `preset` **不在这里** —— 它是 `build_scene()` 认得的键（预置想定的入口）。
WEB_ONLY_KEYS = frozenset({
    "kind", "action", "tier", "jobs", "standard", "missiles", "dv_step", "bc_step",
    "iso_step", "with_iso", "tag", "formats", "colorbar", "cache", "xlim", "ylim", "plot",
    # 图2 的表单专名。`figure` 选图；`bg_alt_m` / `bg_speed_ms` 是**参考工况**，
    # 与 `Scene.alt_m`（载机高度）完全不是一回事，必须挡在这里。
    "figure", "beta_step", "gamma_step", "dv_pin", "n_ref", "bg_alt_m", "bg_speed_ms",
    # 图3 的表单专名（`traj_*`，与 CLI 的外部名同一套）。它们全是**请求层**的量：
    # 一个都不属于 `Scene`，少写一个 `targets.build_scene()` 就会把正常提交判成非法输入
    # （它那边对不认识的键是**硬报错**）。
    "traj_t_crank", "traj_crank_deg", "traj_crank_g", "traj_beam_deg", "traj_beam_g",
    "traj_lock_m", "traj_react_delay", "traj_weave", "traj_weave_amp", "traj_weave_hz",
    "traj_t_beam", "traj_preview",
})

DEFAULT_CONFIG = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "open_browser": False,
    "tier": "fast",
    "standard": DEFAULT_MISSILE,
    "jobs": None,                        # None ⇒ engine.default_jobs()
    "max_concurrent_jobs": 2,            # 同时真正在跑的后台任务数（其余排队）
    "missiles": None,                    # None ⇒ 全池
    "dv_step": 10.0,
    "bc_step": 25.0,
    "iso_step": 1.0,
    "duration_s": 150.0,
    "observation": "ideal",
    "formats": ["png"],                  # 页面只显示 PNG；CLI 那边仍是 png,pdf,svg
    "colorbar": True,
    "cache": True,
    "tag": "web",
    "figure_dir": None,
    "result_dir": None,
    "poll_ms": 500,
}


# ===================================================================== 懒加载
#
# `workflow` → `figures` → matplotlib 是重链；`targets` 是 A1 的模块。两者都懒加载，
# 让 spawn 出来的 worker 子进程（它会重新执行本模块）不为它们付费。

_LOCK = threading.Lock()
_WORKFLOW = None
_TARGETS = None
_TARGETS_TRIED = False
_TRAJ3D = None


def workflow_module():
    """懒加载 `missile_sim.workflow`（它 import matplotlib，很重）。"""
    global _WORKFLOW
    if _WORKFLOW is None:
        with _LOCK:
            if _WORKFLOW is None:
                from . import workflow as mod
                _WORKFLOW = mod
    return _WORKFLOW


def traj3d_module():
    """懒加载 `missile_sim.traj3d`（它 import `figures` ⇒ 也是 matplotlib 那条链）。

    与 `workflow_module()` 同一个理由：模块顶层不碰 matplotlib，否则每个 spawn 出来的
    worker 子进程都要白付一次导入时间（本文件头部那条"技术雷 1"）。
    """
    global _TRAJ3D
    if _TRAJ3D is None:
        with _LOCK:
            if _TRAJ3D is None:
                from . import traj3d as mod
                _TRAJ3D = mod
    return _TRAJ3D


def targets_module():
    """A1 的 `targets.py`；**没落盘就返回 None**（调用方退到下面的薄封装）。

    文件在、import 却失败 ⇒ 那是真 bug，直接抛出去，不静默降级成"没有 targets"。
    """
    global _TARGETS, _TARGETS_TRIED
    if not _TARGETS_TRIED:
        with _LOCK:
            if not _TARGETS_TRIED:
                try:
                    from . import targets as mod
                except ImportError:
                    if Path(__file__).with_name("targets.py").exists():
                        raise
                    mod = None
                _TARGETS, _TARGETS_TRIED = mod, True
    return _TARGETS


def targets_available() -> bool:
    """`targets.py` 是否已落盘（页面脚注会写这一条，免得把兜底路径当成正式校验）。"""
    return targets_module() is not None


# ===================================================================== 配置


def load_config(source=None) -> dict:
    """读配置：`source` 可以是路径、已解析的 dict，或 None（用 `configs/web_default.json`）。

    未知键**打警告**但不报错 —— 配置文件写错一个键名不值得让服务起不来。
    """
    cfg = dict(DEFAULT_CONFIG)
    blob = {}
    if isinstance(source, dict):
        blob = dict(source)
    else:
        path = CONFIG_PATH if source is None else Path(source)
        if Path(path).is_file():
            try:
                blob = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                print(f"[web] 配置读取失败，用内置默认：{exc}", flush=True)
                blob = {}
        if not isinstance(blob, dict):
            print(f"[web] 配置顶层必须是对象，用内置默认：{path}", flush=True)
            blob = {}
    unknown = []
    for key, val in blob.items():
        if str(key).startswith("_"):     # 下划线开头是注释
            continue
        if key in DEFAULT_CONFIG:
            cfg[key] = val
        else:
            unknown.append(str(key))
    if unknown:
        print(f"[web] 配置里有不认识的键（已忽略）：{', '.join(sorted(unknown))}", flush=True)
    return cfg


# ===================================================================== 表单 → Scene


@dataclass(frozen=True)
class Field:
    """页面上的一个输入项。`name` 就是表单字段名 = `Scene` / `PlaneRequest` 的字段名。"""

    name: str
    label: str
    unit: str = ""
    hint: str = ""
    kind: str = "text"                   # text | select
    options: tuple = ()


#: 主字段（任务书点名的那些：初始高度 / 初始速度 / 发射距离 / 敌机方向+俯仰+速度+高度）
PRIMARY_FIELDS = (
    Field("range_m", "发射距离（水平）", "m", "双方水平距离；斜距按高度差现算"),
    Field("alt_m", "载机初始高度", "m", "发射点在原点上方 alt_m"),
    Field("vm0", "载机初始速度", "m/s", "速度标量；方向交给航向/俯仰"),
    Field("launch_heading_deg", "载机航向", "°", "0 = +x，正 → +z"),
    Field("launch_pitch_deg", "载机俯仰", "°", "正 = 爬升"),
    Field("target_heading_deg", "敌机方向", "°", "180 = 迎面"),
    Field("target_pitch_deg", "敌机俯仰", "°", "正 = 爬升"),
    Field("target_speed_ms", "敌机速度", "m/s", ""),
    Field("target_alt_m", "敌机高度", "m", "留空 = 与载机同高"),
    Field("target_bearing_deg", "目标方位角", "°", "0 = +x，正 → +z"),
    Field("duration_s", "时域上限", "s", "实际可能提前结束（命中/落地/寿命到）"),
)

#: 高级字段（档位 / 网格 / 基准弹）
ADV_FIELDS = (
    Field("standard", "基准弹", "", "弹池短名（扫描只改它的推力与阻力系数）",
          kind="select", options=("PL-12",)),
    Field("tier", "计算档位", "", "fast = C 内核；standard = 纯 Python 逐物理步",
          kind="select", options=tuple(TIERS)),
    Field("observation", "观测模式", "", "locked = 永久跟踪假设（求解器无闭环入口）",
          kind="select", options=("ideal", "locked")),
    Field("jobs", "并发进程数", "", "扫描用的进程池大小"),
    Field("dv_step", "ΔV 网格步长", "", "越小越慢：1632 工况 = 10 / 25"),
    Field("bc_step", "BC 网格步长", "", ""),
    Field("iso_step", "等时线步长", "s", ""),
    Field("missiles", "参与散点的弹", "", "逗号分隔；留空 = 全 11 型"),
    Field("xlim", "横轴覆盖（ΔV）", "", "如 900,1200；留空 = 自适应"),
    Field("ylim", "纵轴覆盖（BC）", "", "如 3000,3300；留空 = 自适应"),
    Field("tag", "产物名后缀", "", "图/CSV/JSON 的文件名后缀"),
)

#: 图2（β–γ）专属字段。**不进 `Scene`** —— 参考工况只影响等 n* 线与派生指标，
#: β、γ 是弹的固有量。表单里刻意用 `bg_` 前缀命名，免得和场景的 `alt_m` 撞名。
#: （`beta_step` / `gamma_step` / `dv_pin` / `n_ref` 与 `BgRequest` 同名，直接透传。）
BG_FIELDS = (
    Field("beta_step", "β 网格步长", "kg/m²", "图2 扫描用（默认 30）"),
    Field("gamma_step", "γ 网格步长", "kg/m²", "图2 扫描用（默认 2）"),
    Field("dv_pin", "图2 固定 ΔV", "m/s", "留空 = 基准弹标称 ΔV"),
    Field("n_ref", "参考过载 n", "G", "算 R / β_eff 用的过载（默认 20）"),
    Field("bg_alt_m", "参考工况高度", "m", "只影响等 n* 线（默认 10000）"),
    Field("bg_speed_ms", "参考工况速度", "m/s", "只影响等 n* 线（默认 800）"),
)

#: 选图字段。**单独拎出来**放在表单最上面：它同时管图1 / 图2 / 图3，
#: 塞进图2 的字段组里会让人以为它只对图2 生效（那正是"看起来对、其实骗人"的写法）。
#: ⚠ `options` 必须与服务端 `submit_job()` 接受的分流**完全一致**（含 `both`）——
#: 曾经 `both` 能手工 POST 触达、却不在下拉里，于是"只跑图2"这个 bug 藏了很久（D10）。
FIGURE_FIELD = Field(
    "figure", "出哪张图", "",
    "plane = 图1（ΔV–BC）；bg = 图2（β–γ）；traj = 图3（机动想定）；"
    "both = 图1+图2；all = 三张都出",
    kind="select", options=("plane", "bg", "traj", "both", "all"))

#: 图3（机动想定）专属字段。**不进 `Scene`**，全部是 `TrajRequest` 的量。
#: `name` 就是**表单里的外部名**（= CLI 上的 `--traj-*`），与 `cli._TRAJ_ALIASES`
#: 的外层同一套；`tier` / `standard` / `tag` 三个是全局字段，直接共用上面那两组。
TRAJ_FIELDS = (
    Field("traj_t_crank", "开始 crank 时刻", "s", "发射后多久开始预规避（默认 8）"),
    Field("traj_crank_deg", "crank 离轴角", "°", "朝威胁外侧转这么多（默认 70；对应航向 180 − 该值）"),
    Field("traj_crank_g", "crank 转向过载", "G", "默认 9（内核的固定方向加速度不是转弯，这里按航向指令编译）"),
    Field("traj_beam_deg", "39 位离轴角", "°", "默认 90 = 正侧方"),
    Field("traj_beam_g", "转 39 转向过载", "G", "默认 9"),
    Field("traj_lock_m", "导引头开机距离", "m",
          "留空 = 基准弹 blk 的 guidance.lockDistance（120 系 20 km、PL-12/R-77 系 16 km）"),
    Field("traj_react_delay", "反应延迟", "s", "看到 RWR 告警后转入 39 的延迟（默认 1.0；留空 = 默认，不是 0）"),
    Field("traj_weave", "目标俯仰震荡", "", "填 1 / true / 是 开启；留空或 0 = 关（用户经验值待提供）"),
    Field("traj_weave_amp", "震荡幅度", "°", "仅在开启震荡时生效（默认 4）"),
    Field("traj_weave_hz", "震荡频率", "Hz", "仅在开启震荡时生效（默认 0.1）"),
    Field("traj_t_beam", "钉死开机时刻", "s", "复现/预览用；留空 = 在不含 39 腿的轨迹上反求"),
    Field("traj_preview", "只出 3D 预览", "",
          "填 1 / true / 是 只画目标航迹、不解算（秒级，且不含 39 腿；预览会读一次 blk 取开机距离）"),
)

#: 图3 表单**外部名 → `TrajRequest` 字段名**。方向与 `cli._TRAJ_ALIASES`（字段名 → 外部名）
#: 正好相反，`tests/test_webui_traj.py` 里有一条断言把两张表钉在一起 —— 免得哪天加字段
#: 只改了一边，症状是"页面上填了但不生效"。
TRAJ_ALIASES = {
    "traj_t_crank": "t_crank", "traj_crank_deg": "crank_deg",
    "traj_crank_g": "crank_g", "traj_beam_deg": "beam_deg",
    "traj_beam_g": "beam_g", "traj_lock_m": "lock_distance_m",
    "traj_react_delay": "react_delay_s", "traj_weave": "weave",
    "traj_weave_amp": "weave_amp_deg", "traj_weave_hz": "weave_hz",
    "traj_t_beam": "t_beam_s", "traj_preview": "preview",
}

#: 图3 表单的默认值 —— **必须与 `workflow.TrajRequest` 的字段默认值一致**
#: （测试里逐字段比对）。`traj_weave` / `traj_preview` 用空串表示"关"（`_truthy("") is False`），
#: 这样输入框是空的，而不是显示一个 `False`。
TRAJ_DEFAULTS = {
    "traj_t_crank": 8.0, "traj_crank_deg": 70.0, "traj_crank_g": 9.0,
    "traj_beam_deg": 90.0, "traj_beam_g": 9.0, "traj_lock_m": None,
    "traj_react_delay": 1.0, "traj_weave": "", "traj_weave_amp": 4.0,
    "traj_weave_hz": 0.1, "traj_t_beam": None, "traj_preview": "",
}

FORM_SCENE_FIELDS = tuple(f.name for f in PRIMARY_FIELDS)

#: `Scene` 里要转成数字的字段（dt_s / 风 / 地面高度 / 近炸半径本轮 UI 不暴露）
SCENE_FLOAT_FIELDS = ("range_m", "alt_m", "target_alt_m", "target_bearing_deg", "vm0",
                      "launch_heading_deg", "launch_pitch_deg", "target_speed_ms",
                      "target_heading_deg", "target_pitch_deg", "duration_s", "dt_s",
                      "ground_height_m", "hit_radius_m")

_LABEL = {f.name: f.label
          for f in (PRIMARY_FIELDS + ADV_FIELDS + BG_FIELDS + (FIGURE_FIELD,) + TRAJ_FIELDS)}


def _dedupe(items) -> list:
    """去重且保序（`Scene.check()` 与 `PlaneRequest.check()` 会重复报同一条）。"""
    seen, out = set(), []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _scene_part(form: dict) -> dict:
    """只留场景字段 —— `targets.build_scene()` 不该看到 tier / jobs / tag 这些。"""
    return {k: v for k, v in (form or {}).items() if k not in WEB_ONLY_KEYS}


def _fallback_scene(form: dict):
    """A1 的 `targets.py` 未落盘时的**薄封装**：表单场景字段 → `Scene`。

    ⚠ 待 A1 落盘后收敛：这里刻意只做"字符串 → 数字"的机械转换，**不复刻**领域逻辑
    （预置想定、型号与几何组合的可算性判断都在 `targets.py`）。真正的校验仍然走
    `Scene.check()` 与 `targets.check_compatible()`。
    """
    errors, kwargs = [], {}
    for name in SCENE_FLOAT_FIELDS:
        if name not in form:
            continue
        raw = form[name]
        label = _LABEL.get(name, name)
        blank = raw is None or (isinstance(raw, str) and not raw.strip())
        if blank:
            if name == "target_alt_m":
                kwargs[name] = None          # 留空 = 与载机同高
            continue
        if isinstance(raw, bool):
            errors.append(f"{name}（{label}）必须是数字，收到 {raw!r}")
            continue
        try:
            kwargs[name] = float(raw)
        except (TypeError, ValueError):
            # 字段名放前面：与 A1 的 `build_scene()` 报错风格一致，便于 grep 与断言
            errors.append(f"{name}（{label}）必须是数字，收到 {raw!r}")
    if str(form.get("observation") or "").strip():
        kwargs["observation"] = str(form["observation"]).strip()
    if "proximity_fuse" in form:
        kwargs["proximity_fuse"] = _truthy(form["proximity_fuse"])
    try:
        return Scene(**kwargs), errors
    except TypeError as exc:                 # 不该发生：键名全部来自 Scene 自己
        return None, errors + [f"想定字段有误：{exc}"]


def _truthy(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("", "0", "false", "no", "off", "否")


def build_scene_from_form(form: dict):
    """表单 → `(Scene | None, errors)`。**优先用 A1 的 `targets.build_scene`。**"""
    part = _scene_part(form)
    tg = targets_module()
    fn = getattr(tg, "build_scene", None) if tg is not None else None
    if callable(fn):
        try:
            scene = fn(part)
        except Exception as exc:                              # noqa: BLE001
            return None, [f"想定解析失败：{exc}"]
        if not isinstance(scene, Scene):
            return None, [f"targets.build_scene() 返回的不是 Scene，而是 {type(scene).__name__}"]
        return scene, []
    return _fallback_scene(part)


#: 表单里所有字段（含图2/图3 与 `figure`）—— "把错误按字段归位"用得上。
ALL_FIELDS = PRIMARY_FIELDS + ADV_FIELDS + BG_FIELDS + (FIGURE_FIELD,) + TRAJ_FIELDS


def field_errors(messages, fields=ALL_FIELDS) -> dict:
    """把**给人看的**错误串按字段归位：`{字段名: [消息, …]}`。

    错误串是给用户看的（`载机初始高度 必须是数字，收到 'abc'`、`想定解析失败：range_m 需要数字…`），
    里面没有结构化字段名，只能按文本里的 `label` / `name` 反推。把这段判断放在**服务端**
    （Python、有测试）而不是前端：前端只按返回的键上色，规则不会两边各写一份。

    规则（**浏览器实测逼出来的，别照着想象的样例消息写**）：
    * **先认 label**（更贴人话），长 label 优先（"载机初始高度"别被"高度"抢先）；
    * label 认不出**再认字段名**，且必须**词边界**匹配 —— 否则 `target_alt_m` 的消息会被 `alt_m`
      抢走（互为子串）。归错字段比不归更糟：会让人去改一个没问题的框；
    * 字段名可能在句子**中间**（`想定解析失败：range_m 需要数字，收到 'abc'`）⇒ 不能只看开头；
    * 一条消息只归一个字段；认不出（例如 `kind 只能是 scan / plot`）就只留在 `errors` 里。
    """
    labels = sorted(((f.name, f.label) for f in fields if f.label), key=lambda p: -len(p[1]))
    names = sorted(((f.name, re.compile(rf"(?<![0-9A-Za-z_]){re.escape(f.name)}(?![0-9A-Za-z_])"))
                    for f in fields), key=lambda p: -len(p[0]))
    out: dict = {}
    for msg in messages:
        text = str(msg)
        picked = next((name for name, label in labels if label in text), None)
        if picked is None:
            picked = next((name for name, rx in names if rx.search(text)), None)
        if picked:
            out.setdefault(picked, []).append(text)
    return out


def fail_payload(errors) -> dict:
    """统一的失败响应：`errors`（给人看，原样保留）+ `field_errors`（给前端定位输入框）。"""
    messages = _as_reasons(errors) or ["未知错误"]
    return {"ok": False, "errors": messages, "field_errors": field_errors(messages)}


def _as_reasons(raw) -> list:
    """把 `check_compatible()` 的返回值折成"原因列表"。

    A1 的契约只写了签名，没写返回形态，所以这里**容错优先**：
    `None` / `True` / 空串 / 空表 = 通过；字符串、字符串表、`{"reasons": […]}` 都认。
    """
    if raw is None or raw is True:
        return []
    if raw is False:
        return ["与求解器不兼容（check_compatible 返回 False，未给原因）"]
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, dict):
        for key in ("reasons", "errors", "problems", "messages"):
            if key in raw:
                return _as_reasons(raw[key])
        if raw.get("ok") is True or raw.get("compatible") is True:
            return []
        return [json.dumps(raw, ensure_ascii=False)]
    if isinstance(raw, (list, tuple, set, frozenset)):
        out = []
        for item in raw:
            out.extend(_as_reasons(item))
        return out
    return [str(raw)]


def compat_reasons(scene: Scene) -> list:
    """不兼容原因（**空 = 通过**）。内核侧硬约束 + A1 的领域校验，两边都要过。"""
    out = [str(x) for x in (scene.check() or [])]
    tg = targets_module()
    fn = getattr(tg, "check_compatible", None) if tg is not None else None
    if callable(fn):
        try:
            out.extend(_as_reasons(fn(scene)))
        except Exception as exc:                              # noqa: BLE001
            out.append(f"兼容性检查失败：{type(exc).__name__}: {exc}")
    return out


def _missile_reasons(native: str) -> list:
    """A1 的 `check_missile(native)` —— 内核**硬拒绝**的型号在这里就拦下（不做近似替代）。

    它只在调用那一刻才 import vendor（A1 的 docstring 写明了），所以放"提交"路径上没问题。
    """
    tg = targets_module()
    fn = getattr(tg, "check_missile", None) if tg is not None else None
    if not callable(fn):
        return []
    try:
        return _as_reasons(fn(native))
    except Exception as exc:                                  # noqa: BLE001
        return [f"弹型检查失败：{type(exc).__name__}: {exc}"]


def describe(scene: Scene) -> str:
    """一行中文摘要：优先 A1 的 `describe_scene()`，否则退回 `Scene.describe()`。"""
    tg = targets_module()
    fn = getattr(tg, "describe_scene", None) if tg is not None else None
    if callable(fn):
        try:
            text = fn(scene)
            if text:
                return str(text)
        except Exception:                                     # noqa: BLE001
            pass
    return scene.describe()


def scene_to_form(scene: Scene) -> dict:
    """`Scene` → 表单字典（预置想定一键填充用）。"""
    return {name: getattr(scene, name) for name in FORM_SCENE_FIELDS}


def defaults_form(config: dict) -> dict:
    """表单初始值：`targets.DEFAULT_FORM`（若有） < 配置文件 < 内置默认。"""
    cfg = config or {}
    tg = targets_module()
    raw_default = getattr(tg, "DEFAULT_FORM", None) if tg is not None else None
    out = dict(raw_default) if isinstance(raw_default, dict) else \
        {name: getattr(Scene(), name) for name in FORM_SCENE_FIELDS}
    for name in ("duration_s", "observation"):
        if cfg.get(name) is not None:
            out[name] = cfg[name]
    for name in ("tier", "standard", "jobs", "dv_step", "bc_step", "iso_step", "tag"):
        if cfg.get(name) is not None:
            out[name] = cfg[name]
    for name in ("figure", "beta_step", "gamma_step", "dv_pin", "n_ref",
                 "bg_alt_m", "bg_speed_ms"):
        if cfg.get(name) is not None:
            out[name] = cfg[name]
    # 图3：配置 > `TRAJ_DEFAULTS`（后者与 `TrajRequest` 的字段默认值一致）。
    # 用 `setdefault`，这样 `targets.DEFAULT_FORM` 万一给了同名键也不会被覆盖。
    for name, fallback in TRAJ_DEFAULTS.items():
        out.setdefault(name, cfg[name] if cfg.get(name) is not None else fallback)
    out.setdefault("figure", "plane")
    if cfg.get("missiles"):
        out["missiles"] = ",".join(str(x) for x in cfg["missiles"])
    if not out.get("jobs"):
        out["jobs"] = engine.default_jobs()
    return out


def presets_payload() -> dict:
    """A1 的预置想定 → `{名字: {"summary": 一行描述, "form": 表单值}}`（页面一键填充）。

    走 A1 的真实契约：`presets()` 给 `{名字: 摘要}`，`preset_form(名字)` 给表单初值。
    两者的返回形态都做了容错（dict / list / tuple、`(名字, 表单)`、直接是 `Scene`），
    这样 A1 那边改形态不会把页面打空。A1 未落盘 ⇒ `{}`（页面上就没有预置下拉）。
    """
    tg = targets_module()
    if tg is None:
        return {}
    names_fn = getattr(tg, "presets", None)
    form_fn = getattr(tg, "preset_form", None)
    if not callable(names_fn):
        return {}
    try:
        raw = names_fn()
    except Exception:                                         # noqa: BLE001
        return {}

    out = {}
    if callable(form_fn):
        # —— 首选：presets() 只有摘要，表单在 preset_form() ——
        for name in (raw if isinstance(raw, (list, tuple)) else list(raw or {})):
            try:
                form = form_fn(str(name))
            except Exception:                                 # noqa: BLE001
                continue
            if isinstance(form, dict):
                out[str(name)] = {"summary": _preset_summary(raw, name), "form": form}
        if out:
            return out

    # —— 兜底：presets() 自己就给表单（或 Scene）——
    if isinstance(raw, dict):
        pairs = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        pairs = list(enumerate(raw))
    else:
        return {}
    for key, item in pairs:
        name, form = _preset_item(key, item)
        if name:
            out[name] = {"summary": "", "form": form}
    return out


def _preset_summary(raw, name) -> str:
    if isinstance(raw, dict):
        value = raw.get(name)
        return str(value) if isinstance(value, str) else ""
    return ""


def _preset_item(key, item):
    label, payload = str(key), item
    if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
        label, payload = item[0], item[1]
    elif isinstance(item, dict):
        label = str(item.get("label") or item.get("name") or item.get("key") or key)
        payload = item.get("form") or item.get("scene") or item
    if isinstance(payload, Scene):
        payload = scene_to_form(payload)
    if not isinstance(payload, dict):
        return label, {}
    return label, {k: v for k, v in payload.items() if k not in ("label", "name", "key")}


# ===================================================================== 表单 → 请求


def _num_of(raw, default, label: str, errors: list, *, lo=None, hi=None, integer=False,
            allow_blank: bool = False):
    """留空的语义有两种，所以 `allow_blank` 必须显式选：

    * `allow_blank=False`（默认）：留空 ⇒ 用 `default`（"必填，但有默认值"）；
    * `allow_blank=True`：留空 ⇒ `None`（"**留空本身就是一个合法选择**"）。
      图2 的 `dv_pin` / `bg_alt_m` / `bg_speed_ms` 就是这种 ——
      留空 = 用基准弹标称 ΔV / 参考图口径的 10 km、800 m/s，**不是** 0。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if allow_blank:
            return None
        value = default
    else:
        try:
            value = float(str(raw).replace("，", "").strip()) if not isinstance(raw, bool) else None
        except (TypeError, ValueError):
            value = None
        if value is None:
            errors.append(f"{label} 必须是数字，收到 {raw!r}")
            return default
    if value is None:
        return default
    value = int(round(value)) if integer else float(value)
    if lo is not None and value < lo:
        errors.append(f"{label} 不能小于 {lo}，收到 {value}")
    if hi is not None and value > hi:
        errors.append(f"{label} 不能大于 {hi}，收到 {value}")
    return value


def _pair_of(raw, label: str, errors: list):
    """解析 `a,b` 两段（也接受 `[a, b]`）。留空 = None（用自适应轴）。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        parts = list(raw)
    else:
        parts = [p for p in str(raw).replace("，", ",").split(",") if str(p).strip()]
    if len(parts) != 2:
        errors.append(f"{label} 要写成 `a,b` 两段，收到 {raw!r}")
        return None
    try:
        return (float(parts[0]), float(parts[1]))
    except (TypeError, ValueError):
        errors.append(f"{label} 的两段都必须是数字，收到 {raw!r}")
        return None


def _missiles_of(raw, errors: list):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, str):
        text = raw.replace(",", " ").replace("，", " ").replace("、", " ")
        items = [s for s in text.split() if s]
    else:
        items = [str(s) for s in raw]
    if not items or items == ["all"]:
        return None
    try:
        return tuple(e.key for e in pool.resolve_many(items))
    except pool.PoolError as exc:
        errors.append(str(exc))
        return None


def _tag_of(raw) -> str:
    """产物名后缀：**它进文件名**，所以只留安全字符（顺手堵住路径穿越）。"""
    text = TAG_RE.sub("_", str(raw or "").strip())
    return (text.strip("._") or "web")[:48]


def form_to_request(form: dict, config: dict, *, with_iso: bool = True):
    """表单 → `(PlaneRequest | None, Scene | None, errors)`。

    `errors` 非空时**不要往下跑** —— 页面直接把原因回显出来（这是验收里的一条）。
    """
    cfg = config or {}
    form = dict(form or {})
    errors: list = []

    scene, scene_errors = build_scene_from_form(form)
    errors.extend(scene_errors)
    if scene is None:
        return None, None, _dedupe(errors)
    errors.extend(compat_reasons(scene))

    tier = str(form.get("tier") or cfg.get("tier") or "fast").strip().lower()
    if tier not in TIERS:
        errors.append(f"tier 只能是 {' / '.join(TIERS)}，收到 {tier!r}")

    std_name = str(form.get("standard") or cfg.get("standard") or DEFAULT_MISSILE).strip()
    try:
        std = pool.standard_entry(std_name)
    except pool.PoolError as exc:
        errors.append(str(exc))
        std = None
    if std is not None:
        errors.extend(_missile_reasons(std.native))

    missiles = _missiles_of(form.get("missiles"), errors)
    jobs = _num_of(form.get("jobs"), cfg.get("jobs") or engine.default_jobs(),
                   "并发进程数", errors, lo=1, hi=64, integer=True)
    dv_step = _num_of(form.get("dv_step"), cfg.get("dv_step") or 10.0,
                      "ΔV 网格步长", errors, lo=1e-9)
    bc_step = _num_of(form.get("bc_step"), cfg.get("bc_step") or 25.0,
                      "BC 网格步长", errors, lo=1e-9)
    iso_step = _num_of(form.get("iso_step"), cfg.get("iso_step") or 1.0,
                       "等时线步长", errors, lo=1e-9)
    xlim = _pair_of(form.get("xlim"), "横轴覆盖 xlim", errors)
    ylim = _pair_of(form.get("ylim"), "纵轴覆盖 ylim", errors)

    tag = _tag_of(form.get("tag") or cfg.get("tag") or "web")
    if not with_iso:
        tag = _tag_of(tag + "_point")        # 出图任务不覆盖扫描的图
    formats = tuple(str(x).lower().lstrip(".") for x in (cfg.get("formats") or ["png"]))

    wf = workflow_module()
    req = wf.PlaneRequest(
        scene=scene, standard=(std.key if std else std_name), missiles=missiles,
        tier=tier, iso_step=iso_step, dv_step=dv_step, bc_step=bc_step, jobs=jobs,
        cache=bool(cfg.get("cache", True)), with_iso=bool(with_iso),
        xlim=xlim, ylim=ylim, tag=tag, formats=formats,
        colorbar=bool(cfg.get("colorbar", True)),
        figure_dir=Path(cfg["figure_dir"]) if cfg.get("figure_dir") else None,
        result_dir=Path(cfg["result_dir"]) if cfg.get("result_dir") else None)
    errors.extend(req.check())
    return req, scene, _dedupe(errors)


def form_to_bg_request(form: dict, config: dict, *, with_scan: bool = True):
    """表单 → `(BgRequest | None, Scene | None, errors)`（图2 专用）。

    与 `form_to_request()` 共用场景解析与兼容性校验，区别只在网格参数与参考工况：
    参考工况用 `bg_alt_m` / `bg_speed_ms` 两个**表单专名**，映射到 `BgRequest.alt_m` /
    `speed_ms` —— `BgRequest` 里那两个字段名的含义与 `Scene.alt_m`（载机高度）完全不同，
    表单上必须分开，否则用户改"参考工况高度"会顺手把载机高度也改了。
    """
    cfg = config or {}
    form = dict(form or {})
    errors: list = []

    scene, scene_errors = build_scene_from_form(form)
    errors.extend(scene_errors)
    if scene is None:
        return None, None, _dedupe(errors)
    errors.extend(compat_reasons(scene))

    tier = str(form.get("tier") or cfg.get("tier") or "fast").strip().lower()
    if tier not in TIERS:
        errors.append(f"tier 只能是 {' / '.join(TIERS)}，收到 {tier!r}")

    std_name = str(form.get("standard") or cfg.get("standard") or DEFAULT_MISSILE).strip()
    try:
        std = pool.standard_entry(std_name)
    except pool.PoolError as exc:
        errors.append(str(exc))
        std = None
    if std is not None:
        errors.extend(_missile_reasons(std.native))

    missiles = _missiles_of(form.get("missiles"), errors)
    jobs = _num_of(form.get("jobs"), cfg.get("jobs") or engine.default_jobs(),
                   "并发进程数", errors, lo=1, hi=64, integer=True)
    beta_step = _num_of(form.get("beta_step"), cfg.get("beta_step") or 30.0,
                        "β 网格步长", errors, lo=1e-9)
    gamma_step = _num_of(form.get("gamma_step"), cfg.get("gamma_step") or 2.0,
                         "γ 网格步长", errors, lo=1e-9)
    iso_step = _num_of(form.get("iso_step"), cfg.get("iso_step") or 1.0,
                       "等时线步长", errors, lo=1e-9)
    n_ref = _num_of(form.get("n_ref"), cfg.get("n_ref") or 20.0,
                    "参考过载 n", errors, lo=1e-9)
    dv_pin = _num_of(form.get("dv_pin"), cfg.get("dv_pin"),
                     "图2 固定 ΔV", errors, lo=1e-9, allow_blank=True)
    bg_alt = _num_of(form.get("bg_alt_m"), cfg.get("bg_alt_m"),
                     "参考工况高度", errors, allow_blank=True)
    bg_speed = _num_of(form.get("bg_speed_ms"), cfg.get("bg_speed_ms"),
                       "参考工况速度", errors, lo=0.0, allow_blank=True)
    xlim = _pair_of(form.get("xlim"), "横轴覆盖 xlim（此处是 β）", errors)
    ylim = _pair_of(form.get("ylim"), "纵轴覆盖 ylim（此处是 γ）", errors)

    tag = _tag_of(form.get("tag") or cfg.get("tag") or "web")
    if not with_scan:
        tag = _tag_of(tag + "_nofly")        # 出图任务不覆盖扫描的产物
    formats = tuple(str(x).lower().lstrip(".") for x in (cfg.get("formats") or ["png"]))

    wf = workflow_module()
    req = wf.BgRequest(
        scene=scene, standard=(std.key if std else std_name), missiles=missiles,
        tier=tier, iso_step=iso_step, beta_step=beta_step, gamma_step=gamma_step,
        jobs=jobs, cache=bool(cfg.get("cache", True)), with_scan=bool(with_scan),
        dv_pin=dv_pin, n_ref=n_ref, alt_m=bg_alt, speed_ms=bg_speed,
        xlim=xlim, ylim=ylim, tag=tag, formats=formats,
        figure_dir=Path(cfg["figure_dir"]) if cfg.get("figure_dir") else None,
        result_dir=Path(cfg["result_dir"]) if cfg.get("result_dir") else None)
    errors.extend(req.check())
    return req, scene, _dedupe(errors)


def _traj_num(form: dict, config: dict, name: str, *, errors: list, label: str,
              lo=None, hi=None, integer: bool = False, allow_blank: bool = False):
    """图3 表单数字字段：**表单 > 配置 > `TRAJ_DEFAULTS`**（后者 = `TrajRequest` 默认值）。

    ⚠ 只有 `TrajRequest` 里真的是 `float | None` 的两个字段（`traj_lock_m` / `traj_t_beam`）
    才允许 `allow_blank=True`（留空 ⇒ `None`）。`traj_react_delay` 这类**必填 float**
    留空必须回落到默认值 1.0 —— 给它 `None` 会在 `TrajRequest.check()` 里
    `math.isfinite(None)` 直接 `TypeError`（"留空 = 0"更糟：1 s 的反应延迟是用户定稿的经验值）。
    """
    fallback = (config or {}).get(name)
    if fallback is None:
        fallback = TRAJ_DEFAULTS.get(name)
    return _num_of(form.get(name), fallback, label, errors, lo=lo, hi=hi,
                   integer=integer, allow_blank=allow_blank)


def _traj_flag(form: dict, config: dict, name: str) -> bool:
    """图3 表单布尔字段（`traj_weave` / `traj_preview`）：**非空就以它为准**，否则看配置/默认。

    走 `_truthy`，所以 `1` / `true` / `是` / `on` 都算开，`""` / `0` / `false` / `no` / `off` / `否`
    都算关 —— 与 `_fallback_scene` 处理 `proximity_fuse` 是同一套。
    """
    raw = form.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = (config or {}).get(name, TRAJ_DEFAULTS.get(name))
    return _truthy(raw)


def form_to_traj_request(form: dict, config: dict, *, preview: bool | None = None):
    """表单 → `(TrajRequest | None, Scene | None, errors)`（图3 专用）。

    与 `form_to_bg_request()` 同构：共用场景解析 / 兼容性校验 / 基准弹解析，区别只在
    字段集（`traj_*` 外部名 → `TrajRequest` 的短字段名，见 `TRAJ_ALIASES`）。

    `preview=None`（默认）⇒ 由表单的 `traj_preview` 决定；显式给 True/False ⇒ 覆盖表单
    （给"预览按钮"这类调用点留的口子）。`TrajRequest` **没有** `jobs` / `missiles` /
    `xlim` 这些字段，所以它们在这里一律不读。
    """
    cfg = config or {}
    form = dict(form or {})
    errors: list = []

    scene, scene_errors = build_scene_from_form(form)
    errors.extend(scene_errors)
    if scene is None:
        return None, None, _dedupe(errors)
    errors.extend(compat_reasons(scene))

    tier = str(form.get("tier") or cfg.get("tier") or "fast").strip().lower()
    if tier not in TIERS:
        errors.append(f"tier 只能是 {' / '.join(TIERS)}，收到 {tier!r}")

    std_name = str(form.get("standard") or cfg.get("standard") or DEFAULT_MISSILE).strip()
    try:
        std = pool.standard_entry(std_name)
    except pool.PoolError as exc:
        errors.append(str(exc))
        std = None
    if std is not None:
        errors.extend(_missile_reasons(std.native))

    t_crank = _traj_num(form, cfg, "traj_t_crank", errors=errors,
                        label="开始 crank 时刻", lo=0.0)
    crank_deg = _traj_num(form, cfg, "traj_crank_deg", errors=errors,
                          label="crank 离轴角", lo=0.0, hi=180.0)
    crank_g = _traj_num(form, cfg, "traj_crank_g", errors=errors,
                        label="crank 转向过载", lo=1e-9)
    beam_deg = _traj_num(form, cfg, "traj_beam_deg", errors=errors,
                         label="39 位离轴角", lo=0.0, hi=180.0)
    beam_g = _traj_num(form, cfg, "traj_beam_g", errors=errors,
                       label="转 39 转向过载", lo=1e-9)
    lock_m = _traj_num(form, cfg, "traj_lock_m", errors=errors,
                       label="导引头开机距离", lo=1e-9, allow_blank=True)
    react = _traj_num(form, cfg, "traj_react_delay", errors=errors,
                      label="反应延迟", lo=0.0)
    amp = _traj_num(form, cfg, "traj_weave_amp", errors=errors,
                    label="震荡幅度", lo=0.0)
    hz = _traj_num(form, cfg, "traj_weave_hz", errors=errors,
                   label="震荡频率", lo=1e-9)
    t_beam = _traj_num(form, cfg, "traj_t_beam", errors=errors,
                       label="钉死开机时刻", lo=0.0, allow_blank=True)
    weave = _traj_flag(form, cfg, "traj_weave")
    do_preview = _traj_flag(form, cfg, "traj_preview") if preview is None else bool(preview)

    tag = _tag_of(form.get("tag") or cfg.get("tag") or "web")
    formats = tuple(str(x).lower().lstrip(".") for x in (cfg.get("formats") or ["png"]))

    wf = workflow_module()
    req = wf.TrajRequest(
        scene=scene, standard=(std.key if std else std_name), tier=tier,
        t_crank=t_crank, crank_deg=crank_deg, crank_g=crank_g, beam_deg=beam_deg,
        beam_g=beam_g, lock_distance_m=lock_m, react_delay_s=react, weave=weave,
        weave_amp_deg=amp, weave_hz=hz, t_beam_s=t_beam, preview=do_preview,
        tag=tag, formats=formats,
        figure_dir=Path(cfg["figure_dir"]) if cfg.get("figure_dir") else None,
        result_dir=Path(cfg["result_dir"]) if cfg.get("result_dir") else None)
    errors.extend(req.check())
    return req, scene, _dedupe(errors)


# ===================================================================== JSON 安全


def jsonable(obj):
    """JSON 安全投影：**非有限浮点 → None**。

    这是硬要求：`Shot.t_hit` 未命中时是 `nan`，`json.dumps` 会写出裸 `NaN` ——
    Python 读得回来，**JS 的 `JSON.parse` 直接抛错**，页面就白屏。
    """
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "as_dict"):          # Scene / Shot / AxisSpec / PlaneGrid / Provenance
        return jsonable(obj.as_dict())
    return str(obj)


# ===================================================================== 后台任务


def _split_progress(args):
    """进度回调的**两种形态都支持**：

    * `progress(done, total)` —— `engine.Engine.many` 的现状（两个位置参数）；
    * `progress({"done": n, "total": m})` —— 任务书里写的契约。

    两边的字面约定不一致，这里做一层归一，免得哪边先改就把进度条打断。
    """
    if len(args) == 1:
        one = args[0]
        if isinstance(one, dict):
            return one.get("done"), one.get("total")
        if isinstance(one, (list, tuple)) and len(one) >= 2:
            return one[0], one[1]
        return one, None
    if len(args) >= 2:
        return args[0], args[1]
    return None, None


@dataclass
class Job:
    """一个后台任务。状态机：`queued → running → done | error`。"""

    id: str
    kind: str                            # scan | plot
    state: str = "queued"
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    echo: bool = True                    # 把 log 同步打到服务端控制台
    logs: list = field(default_factory=list)
    result: dict | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # --- 回调（由 run_plane / Engine 调用）-----------------------------

    def progress(self, *args):
        done, total = _split_progress(args)
        with self.lock:
            if done is not None:
                try:
                    self.done = int(float(done))
                except (TypeError, ValueError):
                    pass
            if total:
                try:
                    self.total = int(float(total))
                except (TypeError, ValueError):
                    pass

    def log(self, message):
        text = str(message)
        with self.lock:
            self.logs.append(text)
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[:-MAX_LOG_LINES]
        if self.echo:
            print(f"[webui {self.id[:8]}] {text}", flush=True)

    # --- 快照 ---------------------------------------------------------

    def snapshot(self, *, with_result: bool = True) -> dict:
        with self.lock:
            done, total = self.done, self.total
            if self.state == "done":
                percent = 100.0
                if total:
                    done = max(done, total)
            else:
                percent = (100.0 * done / total) if total else 0.0
            start = self.started_at or self.created_at
            end = self.finished_at or time.time()
            return {
                "ok": True, "id": self.id, "kind": self.kind, "state": self.state,
                "done": done, "total": total, "percent": round(percent, 1),
                "message": self.message, "error": self.error,
                "elapsed_s": round(end - start, 2), "logs": list(self.logs),
                "result": self.result if (with_result and self.result) else None,
            }


class JobStore:
    """任务表：**扫描/出图都在后台线程里跑**，HTTP 只负责创建与查询。"""

    def __init__(self, *, max_concurrent: int = 2, keep: int = 32, echo: bool = True):
        self._jobs: dict = {}
        self._order: list = []
        self._lock = threading.Lock()
        self._sem = threading.Semaphore(max(1, int(max_concurrent)))
        self.keep = max(4, int(keep))
        self.echo = bool(echo)

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=str(kind), echo=self.echo)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            # 只留最近若干个**已结束**的任务，避免长跑的服务把内存攒满
            while len(self._order) > self.keep:
                old = self._jobs.get(self._order[0])
                if old is not None and old.state in ("queued", "running"):
                    break
                self._order.pop(0)
                self._jobs.pop(old.id if old else None, None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(str(job_id))

    def snapshot(self, job_id: str):
        job = self.get(job_id)
        return None if job is None else job.snapshot()

    def submit(self, kind: str, work) -> Job:
        """`work(kind, job) -> result dict`；异常一律折进 `job.error`。"""
        job = self.create(kind)
        threading.Thread(target=self._run, args=(job, work), daemon=True,
                         name=f"missile-webui-{job.id[:8]}").start()
        return job

    def _run(self, job: Job, work):
        with self._sem:                        # 超出 max_concurrent 的任务在这里排队
            with job.lock:
                if job.state != "queued":
                    return
                job.state = "running"
                job.started_at = time.time()
            try:
                job.result = work(job.kind, job)
                with job.lock:
                    job.state = "done"
                    if job.total:
                        job.done = job.total
                    if not job.message or job.message.endswith("…"):
                        job.message = "完成"
            except Exception as exc:                              # noqa: BLE001
                with job.lock:
                    job.state = "error"
                    job.error = f"{type(exc).__name__}: {exc}"
            finally:
                with job.lock:
                    job.finished_at = time.time()
                if job.error:
                    job.log(f"任务失败：{job.error}")


# ===================================================================== 任务体


def summarize_plane(out: dict, req) -> dict:
    """`run_plane()` 的返回值 → 页面上要的那点东西（**不带 numpy 数组**）。

    ⚠ `figure: "plane"` 这个键**必须**在（图2/图3 的摘要一直都有）：`figure=both/all` 的合并
    摘要会把每张图的摘要原样放进 `parts`，缺键的后果是页面 JS 只能靠 `else` 兜底 ——
    "这一份到底是哪张图"变成隐式知识（D10）。曾经这里不写它。
    """
    paths = dict(out.get("_paths") or {})
    manifest = dict(out.get("manifest") or {})
    with_iso = bool(manifest.get("with_iso"))
    g, axis = out.get("grid"), out.get("axis")
    n_cases = int(getattr(g, "n_cases", 0) or 0) if with_iso else 0
    n_hit = int(out.get("n_hit") or 0) if with_iso else 0
    figures = [str(p) for p in (paths.get("figures") or [])]
    return {
        "ok": True, "figure": "plane", "with_iso": with_iso,
        "n_hit": n_hit, "n_cases": n_cases,
        "hit_rate": (n_hit / n_cases) if n_cases else None,
        "elapsed_s": round(float(out.get("elapsed_s") or 0.0), 2),
        "backend": out.get("backend") or "",
        "tier": req.tier,
        "standard": getattr(out.get("standard"), "key", req.standard),
        "missiles": [p.key for p in (out.get("points") or ())],
        "grid": g.as_dict() if (with_iso and g is not None) else None,
        "axis": axis.as_dict() if axis is not None else None,
        "t_hit_range_s": manifest.get("t_hit_range_s"),
        "monotonic": manifest.get("monotonic"),
        "iso_levels": manifest.get("iso_levels"),
        "scene_text": describe(req.scene),
        "figures": figures,
        "figure_urls": [f"/figures/{Path(p).name}" for p in figures
                        if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")],
        "paths": {k: (v if isinstance(v, str) else [str(x) for x in v])
                  for k, v in paths.items()},
    }


def run_plane_job(req, job: Job) -> dict:
    """后台任务体：`workflow.run_plane()` —— `progress` / `log` 回调直接接上。"""
    wf = workflow_module()
    job.message = "扫描中…" if req.with_iso else "出图中（matplotlib，约 5 s）…"
    out = wf.run_plane(req, progress=job.progress, log=job.log)
    return summarize_plane(out, req)


def summarize_bg(out: dict, req) -> dict:
    """`run_bg()` 的返回值 → 页面要的那点东西（**不带 numpy 数组**）。

    页面上要和图1 的结果区分开，所以带 `figure: "bg"` 这个键；JS 靠它选渲染分支。
    """
    paths = dict(out.get("_paths") or {})
    manifest = dict(out.get("manifest") or {})
    scan = dict(manifest.get("scan") or {}) or None
    axis = out.get("axis")
    rows_ = list(out.get("rows") or ())
    ref = out.get("reference")
    figures = [str(p) for p in (paths.get("figures") or [])]
    return {
        "ok": True, "figure": "bg", "with_iso": bool(scan),
        "n_hit": int(scan.get("n_hit") or 0) if scan else 0,
        "n_cases": int(scan.get("n_cases") or 0) if scan else 0,
        "hit_rate": (scan or {}).get("hit_rate"),
        "elapsed_s": round(float(out.get("elapsed_s") or 0.0), 2),
        "backend": out.get("backend") or "",
        "tier": req.tier,
        "standard": getattr(out.get("standard"), "key", req.standard),
        "missiles": [r.key for r in rows_],
        "dv_pin": out.get("dv_pin"),
        "n_ref": req.n_ref,
        "reference": (ref.as_dict() if hasattr(ref, "as_dict") else None),
        "axis": axis.as_dict() if axis is not None else None,
        "t_hit_range_s": manifest.get("t_hit_range_s"),
        "monotonic_beta": manifest.get("monotonic_beta"),
        "monotonic_gamma": manifest.get("monotonic_gamma"),
        "iso_levels": manifest.get("iso_levels"),
        "scene_text": describe(req.scene),
        "figures": figures,
        "figure_urls": [f"/figures/{Path(p).name}" for p in figures
                        if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")],
        "paths": {k: (v if isinstance(v, str) else [str(x) for x in v])
                  for k, v in paths.items()},
    }


def run_bg_job(req, job: Job) -> dict:
    """后台任务体：`workflow.run_bg()`（图2）。"""
    wf = workflow_module()
    job.message = "扫描 β×γ 中…" if req.with_scan else "出图中（matplotlib，约 5 s）…"
    out = wf.run_bg(req, progress=job.progress, log=job.log)
    return summarize_bg(out, req)


def _finite_or_none(value, digits: int | None = None):
    """非有限数（`nan` / `inf`）→ `None`，否则按需保留位数。

    `Shot.t_hit` 未命中时是 `nan`、`cpa_m` 没量过时也是 `nan` —— 直接塞进 JSON 会写出
    裸 `NaN`（`json.dumps` 允许，**JS 的 `JSON.parse` 直接抛错**，页面白屏）。`jsonable()`
    兜了一层，这里再显式折成 `None`，页面就不必猜 `nan` 是什么意思。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return round(num, digits) if digits is not None else num


def summarize_traj(out: dict, req) -> dict:
    """`run_traj()` 的返回值 → 页面要的那点东西（**不带 numpy 数组 / 不带逐采样行**）。

    页面靠 `figure: "traj"` 选渲染分支；`preview=True` 时 `out` 里**没有** `shot` / `anchor` /
    `standard`，所以那一段必须单独走一个分支 —— 拿正式工况的字段去读预览结果会
    `AttributeError`（而预览恰恰是用户最先点的那一下）。
    """
    paths = dict(out.get("_paths") or {})
    entry = out.get("standard")
    figures = [str(p) for p in (paths.get("figures") or [])]
    base = {
        "ok": True, "figure": "traj",
        "tier": req.tier,
        "standard": getattr(entry, "key", None) or req.standard,
        "native": getattr(entry, "native", ""),
        "elapsed_s": round(float(out.get("elapsed_s") or 0.0), 2),
        "scene_text": describe(req.scene),
        "figures": figures,
        "figure_urls": [f"/figures/{Path(p).name}" for p in figures
                        if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")],
        "paths": {k: (v if isinstance(v, str) else [str(x) for x in v])
                  for k, v in paths.items()},
    }
    if out.get("preview") or not out.get("shot"):
        base.update({
            "preview": True,
            "note": "预览，未解算：只按运动学画目标航迹 3D（不解算；仍会读一次 blk 取开机距离）",
            "t_beam_s": out.get("t_beam_s"),
            "lock_distance_m": None, "t_react_s": None,
            "heading_at_beam_deg": None, "completed": None,
            "completed_text": "预览未解算（开机时刻与 39 腿都要正式跑才有）",
            "hit": None, "t_hit_s": None, "cpa_m": None,
            "min_separation_m": None, "fuse_radius_m": None,
            "n_segments": None, "backend": "",
        })
        return base

    anchor = dict(out.get("anchor") or {})
    shot = out.get("shot")
    segments = list(out.get("segments") or ())
    completed = anchor.get("completed")
    if completed is None:
        completed_text = "无 crank 腿（告警早于 crank，直接进 39）"
    elif completed:
        completed_text = "转完了"
    else:
        completed_text = "没转完（39 指令截断了 crank 转弯）"
    hit = None if shot is None else bool(shot.hit)
    base.update({
        "preview": False,
        "beta": _finite_or_none(out.get("beta"), 1),
        "gamma": _finite_or_none(out.get("gamma"), 2),
        "t_beam_s": _finite_or_none(out.get("t_beam_s"), 3),
        "range_at_beam_m": _finite_or_none(anchor.get("range_at_beam_m"), 1),
        "anchor_mode": anchor.get("mode") or "",
        "lock_distance_m": _finite_or_none(out.get("lock_distance_m"), 1),
        "react_delay_s": _finite_or_none(req.react_delay_s, 3),
        "t_react_s": _finite_or_none(out.get("t_react_s"), 3),
        "heading_at_beam_deg": _finite_or_none(anchor.get("heading_at_beam_deg"), 1),
        "completed": completed,
        "completed_text": completed_text,
        "t_crank_turn_end_s": _finite_or_none(anchor.get("t_crank_turn_end_s"), 3),
        "pass1_hit": anchor.get("pass1_hit"),
        "pass1_t_hit_s": _finite_or_none(anchor.get("pass1_t_hit_s"), 3),
        "weave": bool(req.weave),
        "backend": out.get("backend") or (getattr(shot, "backend", "") or ""),
        "n_segments": len(segments),
        "hit": hit,
        "t_hit_s": _finite_or_none(getattr(shot, "t_hit", None), 3) if hit else None,
        # 未命中 ⇒ 报"终止前最近距离"（那才是真脱靶量，本来就只有这一种读法）；
        # 命中 ⇒ 报真 CPA（`cpa_m`，关引信复跑量出来的），**不再**把引信半径 10 m
        # 当脱靶量发出去（A5）。三个字段都给全，页面自己挑一个显示。
        # ⚠ `cpa_m` 留 **6 位小数**（= 原值）：真 CPA 常在 1e-4~1e-3 m 量级，
        # 按 2/3 位小数折会把它抹成 0.0 —— 那等于把刚修好的信息又丢了。显示精度交给页面。
        "cpa_m": _finite_or_none(getattr(shot, "cpa_m", None), 6),
        "min_separation_m": (_finite_or_none(getattr(shot, "min_separation_m", None), 2)
                             if hit is False else None),
        "fuse_radius_m": _finite_or_none(getattr(shot, "fuse_radius_m", None), 2),
        "t_end_s": _finite_or_none(getattr(shot, "t_end", None), 3),
    })
    return base


def run_traj_job(req, job: Job) -> dict:
    """后台任务体：`workflow.run_traj()`（图3，两遍法；`preview` **不解算**）。

    ⚠ 口径（2026-09-30 `fig3-verifier` 打桩取证）：`preview=True` 时 `solver.run` **零调用**，
    但会调一次 `solver.profile` 读 blk 拿 `guidance.lockDistance` —— 所以是"不**解算**"，
    不是"完全不碰 solver"；耗时也不是毫秒级（含出图约 1~3 s）。
    """
    wf = workflow_module()
    job.message = ("预览目标航迹（不解算）…" if req.preview
                   else "解算机动想定（两遍：反求开机 → 正式工况）…")
    out = wf.run_traj(req, progress=job.progress, log=job.log)
    return summarize_traj(out, req)


def summarize_all(parts: list, *, figure: str = "all") -> dict:
    """`figure=both` / `figure=all`：各张图的摘要 → 一个合并摘要（页面按 `parts` 列名字）。

    刻意**不做二次加工** —— 每张图的摘要原样放进 `parts`（只把 `figure` 键补成显式值，
    这样任何读 `parts[i]["figure"]` 的地方都不必猜缺省），页面要细节时直接读那一份，
    免得这里再维护一套"合并后的字段"（那种字段最容易和上面几个 `summarize_*` 走散）。

    `figure` 是这一单的名字：`"both"` = 图1+图2（与 CLI `--figure both` 对齐），
    `"all"` = 三张。**不接受** `"bg"` 之类会与单张摘要撞名的值。
    """
    if figure not in ("both", "all"):
        raise ValueError(f"合并摘要只服务于 both / all，收到 {figure!r}")
    figures, urls, paths, norm = [], [], {}, []
    for part in parts:
        # 缺 `figure` 键的旧摘要一律当图1 —— 这是**兼容**写法，不是要求：
        # `summarize_plane()` 现在自带 `"figure": "plane"`（D10）。
        key = str(part.get("figure") or "plane")
        norm.append(dict(part, figure=key))
        figures.extend(str(p) for p in (part.get("figures") or ()))
        urls.extend(str(u) for u in (part.get("figure_urls") or ()))
        for name, val in (part.get("paths") or {}).items():
            paths[f"{key}_{name}"] = val
    return {
        "ok": True, "figure": figure, "parts": norm,
        "elapsed_s": round(sum(float(p.get("elapsed_s") or 0.0) for p in parts), 2),
        "figures": figures, "figure_urls": urls, "paths": paths,
    }


def run_all_job(reqs: dict, job: Job, *, figure: str = "all") -> dict:
    """`figure=both` / `figure=all` 的任务体：按 CLI 的顺序跑在同一个后台任务里。

    `both` ⇒ 图1 → 图2；`all` ⇒ 图1 → 图2 → 图3（与 `cli.main()` 的 dispatch 一一对应，
    `reqs` 里没有的那几张自动跳过）。任一张抛异常 ⇒ 整个任务 `error`（和 CLI 一样）。
    `kind` 只决定图1/图2 跑不跑仿真层（`scan` 跑、`plot` 只出图），图3 不看 `kind`。
    """
    steps = ((reqs.get("plane"), run_plane_job, "图1"),
             (reqs.get("bg"), run_bg_job, "图2"),
             (reqs.get("traj"), run_traj_job, "图3"))
    parts = []
    for req, runner, title in steps:
        if req is None:
            continue
        job.log(f"=== {title} ===")
        parts.append(runner(req, job))
    return summarize_all(parts, figure=figure)


# ===================================================================== 单工况（同步）


def run_single(form: dict, config: dict):
    """单工况：**同步**跑 `solver.run()`，返回 `(payload, http_status)`。

    fast 档实测 ~0.1 s，所以不排队 —— 页面要的是"填完立刻看到数"。
    出图（matplotlib ~5 s）仍然丢后台，见 `kind=plot`。
    """
    t0 = time.perf_counter()
    req, scene, errors = form_to_request(form, config, with_iso=False)
    if errors:
        return fail_payload(errors), 400
    try:
        entry = pool.standard_entry(req.standard)
        shot = solver.run(scene, missile=entry.native, tier=req.tier)
    except Exception as exc:                                  # noqa: BLE001
        return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}, 500
    payload = {"ok": bool(shot.ok), "missile": req.standard, "native": entry.native,
               "tier": req.tier, "scene": scene.as_dict(), "scene_text": describe(scene),
               "shot": shot.as_dict(),
               "elapsed_s": round(time.perf_counter() - t0, 3)}
    if not shot.ok:
        payload["errors"] = [shot.error or "求解器没有返回结果"]
    return payload, 200


# ===================================================================== 服务状态


class WebState:
    """一个服务实例的全部可变状态：配置 + 任务表 + 求解器身份缓存。"""

    def __init__(self, config=None, *, quiet: bool = False):
        self.config = load_config(config)
        self.quiet = bool(quiet)
        self.jobs = JobStore(max_concurrent=self.config.get("max_concurrent_jobs", 2),
                             echo=not self.quiet)
        self._identity = None
        self._lock = threading.Lock()

    def identity(self) -> dict:
        """求解器身份（会做一次 vendor 哈希 ~0.2 s，缓存住）。"""
        with self._lock:
            if self._identity is None:
                self._identity = solver.identity()
            return self._identity

    def solver_text(self) -> str:
        try:
            ident = self.identity()
        except Exception as exc:                              # noqa: BLE001
            return f"求解器不可用：{type(exc).__name__}: {exc}"
        return (f"{ident.get('solver')} {ident.get('version')} · {ident.get('model')} · "
                f"{ident.get('n_profiles')} 预设 · sha256 {str(ident.get('sha256'))[:8]}… · "
                f"校验和 {str(ident.get('archive_sha256') or '')[:8]}…")

    def static_roots(self) -> list:
        """允许静态读取的目录（图片/产物）。**只认配置与 spec 里的目录**。"""
        roots = [FIG_DIR, RESULT_DIR]
        for key in ("figure_dir", "result_dir"):
            if self.config.get(key):
                roots.append(Path(self.config[key]))
        out, seen = [], set()
        for root in roots:
            key = str(root)
            if key not in seen:
                seen.add(key)
                out.append(root)
        return out

    def find_static(self, name: str) -> Path | None:
        """按文件名在允许的目录里找（名字先做 basename 化，堵路径穿越）。"""
        safe = Path(str(name)).name
        if not safe or safe != str(name).strip():
            return None
        for root in self.static_roots():
            try:
                path = (Path(root) / safe).resolve()
            except OSError:
                continue
            if path.is_file() and _is_inside(path, root):
                return path
        return None


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):                             # pragma: no cover
        return False


# ===================================================================== HTTP


class Handler(BaseHTTPRequestHandler):
    """路由表（GET 读、POST 提交）：

        GET  /                  首页（表单 + 进度条 + 结果面板）
        GET  /healthz           存活探针
        GET  /progress/<id>     任务快照（页面轮询的就是它）
        GET  /static/<name>     首页自己的 CSS/JS（白名单 app.css / app.js / viewer3d.css / viewer3d.js）
        GET  /viewer3d          可拖拽 3D 查看器整页（`viewer3d.html`，数据走 /api/viewer3d/<id>）
        GET  /api/viewer3d/<id> 图3 任务的查看器数据（JSON，默认 800 点；不解算）
        GET  /figures/<name>    图片 / 产物（只在允许的目录里找）
        POST /api/single        单工况，同步返回 JSON
        POST /api/submit        提交后台任务（kind=scan | plot）
    """

    server_version = "missile-sim-webui/1.0"
    protocol_version = "HTTP/1.1"

    # --- 工具 ---------------------------------------------------------

    @property
    def state(self) -> WebState:
        return self.server.state                                 # type: ignore[attr-defined]

    def log_message(self, fmt, *args):                           # noqa: A003
        if getattr(self.server, "quiet", False):
            return
        print(f"[web] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code: int = 200):
        body = json.dumps(jsonable(payload), ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _html(self, text: str, code: int = 200):
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8")

    def _fail(self, errors, code: int = 400):
        self._json(fail_payload(errors), code)

    def _payload(self) -> dict:
        """请求体 → dict。`application/json` 与表单编码都认（验收里用 http.client 发表单）。"""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype == "application/json":
            blob = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(blob, dict):
                raise ValueError("JSON 顶层必须是对象")
            return blob
        out = {}
        for key, values in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items():
            out[key] = values[0] if len(values) == 1 else values
        return out

    # --- GET ----------------------------------------------------------

    def do_GET(self):                                            # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._html(render_page(self.state))
            if path == "/healthz":
                return self._json({"ok": True, "targets": targets_available(),
                                   "quiet": self.state.quiet})
            if path.startswith("/progress/"):
                snap = self.state.jobs.snapshot(unquote(path.split("/", 2)[2]))
                if snap is None:
                    return self._fail(["没有这个任务 id"], 404)
                return self._json(snap)
            if path.startswith("/api/viewer3d/"):
                return self._viewer3d_data(unquote(path.split("/", 3)[3]),
                                          parse_qs(parsed.query))
            if path in ("/viewer3d", "/viewer3d.html"):
                return self._viewer3d_page()
            if path.startswith("/static/"):
                return self._web_static(unquote(path.rsplit("/", 1)[1]))
            if path.startswith("/figures/") or path.startswith("/results/"):
                return self._static(unquote(path.rsplit("/", 1)[1]))
            return self._fail([f"未知路径 {path}"], 404)
        except Exception as exc:                              # noqa: BLE001
            return self._json({"ok": False,
                               "errors": [f"{type(exc).__name__}: {exc}"]}, 500)

    def _viewer3d_page(self):
        """`viewer3d.html` 是一条**独立路由**，不在 `/static/` 白名单里。

        它没有服务端占位符（job id / 点数 / 底透明度都从 `location.search` 读），所以直接发字节；
        但仍然不做成 `/static/viewer3d.html` —— 静态白名单只放 CSS/JS 这类**纯资源**，
        页面（含首页）一律走自己的路由，白名单的边界就不必随页面数量变化而解释。
        """
        try:
            data = read_page_file(VIEWER3D_PAGE).encode("utf-8")
        except (OSError, ValueError):
            return self._fail([f"找不到查看器页面 {VIEWER3D_PAGE!r}"], 404)
        return self._send(200, data, "text/html; charset=utf-8")

    def _viewer3d_data(self, job_id: str, query: dict = None):
        # `parse_qs` 给的是**列表**（同名参数可以出现多次）：只认第一个，
        # 别把 `["1200"]` 原样喂给 `parse_points`（那会变成"points 必须是整数"）。
        raw = (query or {}).get("points")
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        payload, code = viewer3d_payload(self.state, job_id, raw)
        return self._json(payload, code)

    def _static(self, name: str):
        path = self.state.find_static(name)
        if path is None:
            return self._fail([f"找不到产物 {name!r}"], 404)
        ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".svg": "image/svg+xml", ".pdf": "application/pdf",
                 ".json": "application/json; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8"}.get(path.suffix.lower(),
                                                        "application/octet-stream")
        return self._send(200, path.read_bytes(), ctype)

    def _web_static(self, name: str):
        """首页自己的静态资源（`webui_static/app.css` / `app.js`）。**白名单，fail-closed**：

        `WEB_STATIC_ASSETS` 之外的名字（含 `index.html`、带路径的名字）一律 404 ——
        `index.html` 里带着未替换的占位符，直接吐原始字节会把 `__DEFAULTS__` 露出去。
        """
        safe = str(name).strip()
        if safe not in WEB_STATIC_ASSETS:
            return self._fail([f"找不到静态资源 {name!r}"], 404)
        try:
            data = read_page_file(safe).encode("utf-8")
        except (OSError, ValueError):
            return self._fail([f"找不到静态资源 {name!r}"], 404)
        return self._send(200, data, WEB_STATIC_ASSETS[safe])

    # --- POST ---------------------------------------------------------

    def do_POST(self):                                           # noqa: N802
        path = urlparse(self.path).path
        try:
            form = self._payload()
        except Exception as exc:                              # noqa: BLE001
            return self._fail([f"请求体解析失败：{type(exc).__name__}: {exc}"], 400)
        try:
            if path == "/api/single":
                payload, code = run_single(form, self.state.config)
                return self._json(payload, code)
            if path == "/api/submit":
                payload, code = submit_job(form, self.state)
                return self._json(payload, code)
            return self._fail([f"未知路径 {path}"], 404)
        except Exception as exc:                              # noqa: BLE001
            return self._json({"ok": False,
                               "errors": [f"{type(exc).__name__}: {exc}"]}, 500)


def viewer3d_payload(state: WebState, job_id: str, points_raw=None):
    """`GET /api/viewer3d/<job_id>` 的数据层：任务摘要 → 查看器 JSON。

    返回 `(payload, http_status)`。几种"不行"要分开说，别都折成一个 404：

    * 任务 id 不认识 → 404；任务还在跑 / 跑挂了 → **409**（页面据此说"还没跑完，稍等"，
      而不是把"还没结果"说成"没有这件东西"）；
    * `points` 不合法 → 400。**不做静默截断**：用户以为设了 1200、实际被悄悄改成 800，
      比报错更糟（这条口径与 CLI / `figures` 的"宁可炸"一致）；
    * 这个任务里没有图3 的产物（图1 / 图2 / `traj_preview=1` 的预览）→ 404，并说清是哪一种。

    ⚠ 全程**只读产物、不解算**：数据来自 `results/traj_<tag>_{missile,target,segments}.csv|json`
    （`traj3d.build()`）—— 一个 `solver.run()` 都没有，有测试钉住。
    """
    t3 = traj3d_module()
    try:
        points = t3.parse_points(points_raw)
    except ValueError as exc:
        return fail_payload([str(exc)]), 400
    job = state.jobs.get(str(job_id or "").strip())
    if job is None:
        return fail_payload([f"没有这个任务 id：{job_id!r}"]), 404
    if job.state != "done":
        tail = f"：{job.error}" if job.error else "，稍后再试"
        return fail_payload([f"任务还没跑完（state={job.state}）{tail}"]), 409
    try:
        paths, part = t3.paths_of(job.result or {})
    except LookupError as exc:
        return fail_payload([str(exc)]), 404
    if part.get("preview"):
        return fail_payload([
            "这个任务跑的是 traj_preview=1 的**预览**：只出了静态图，没有逐点产物，"
            "所以没有可拖拽的 3D 数据。把「只出 3D 预览」清空（正式跑一次图3）后就有。"]), 404
    try:
        payload = t3.build(paths, points=points, job=job.id, tag=part.get("tag"),
                           extra={"native": part.get("native") or ""})
    except FileNotFoundError as exc:
        return fail_payload([str(exc)]), 404
    return payload, 200


def submit_job(form: dict, state: WebState):
    """提交后台任务，返回 `(payload, http_status)`。

    `figure` 决定用哪套参数解析（四套的参数名不同），**分流与 CLI 的 `--figure` 一一对应**：
    `plane`（默认）⇒ 图1；`bg` ⇒ 图2；`traj` ⇒ 图3；`both` ⇒ 图1+图2；`all` ⇒ 三张图。
    `both` / `all` 把多张图跑在**同一个**后台任务里（`run_all_job`），摘要用 `parts` 分列。

    ⚠ 这里曾经有个"藏起来的坑"（D10）：`both` 落在 `figure in ("bg", "both")` 那个分支里，
    **只跑图2却把响应标成 both**，而 CLI 的 `--figure both` 是图1+图2 —— 两边静默不一致，
    且 `FIGURE_FIELD.options` 里没有 `both`，只能手工 POST 触达。现在 `both` 与 CLI 对齐，
    并出现在下拉里（"看得见的选项"才配叫选项）。

    `kind=scan` 跑扫描，`kind=plot` 只出图 —— 这两档**只对图1/图2 有意义**（图3 没有平面可扫，
    两个 `kind` 等价）；`kind` 仍然照原样传给 `JobStore`，图1/图2 的语义一个字没动。
    """
    form = dict(form or {})
    kind = str(form.get("kind") or "scan").strip().lower()
    if kind not in ("scan", "plot"):
        return fail_payload([f"kind 只能是 scan / plot，收到 {kind!r}"]), 400
    figure = str(form.get("figure") or "plane").strip().lower()
    if figure not in ("plane", "bg", "traj", "both", "all"):
        return fail_payload([f"figure 只能是 plane / bg / traj / both / all，"
                                       f"收到 {figure!r}"]), 400

    if figure == "traj":
        req, _scene, errors = form_to_traj_request(form, state.config)
        if errors:
            return fail_payload(errors), 400

        def work_traj(_kind, job):
            return run_traj_job(req, job)

        job = state.jobs.submit(kind, work_traj)
        return {"ok": True, "id": job.id, "kind": kind, "figure": "traj",
                "poll": f"/progress/{job.id}", "preview": bool(req.preview),
                "tag": req.tag}, 200

    if figure in ("both", "all"):
        # 与 CLI 一致：both = 图1+图2，all = 图1+图2+图3。各张图分别解析；任一张的输入不合法
        # 就整单拒收（别让用户拿到"跑了一半"的任务）。
        p_req, _s1, p_err = form_to_request(form, state.config, with_iso=(kind == "scan"))
        b_req, _s2, b_err = form_to_bg_request(form, state.config, with_scan=(kind == "scan"))
        reqs = {"plane": p_req, "bg": b_req}
        errs = list(p_err) + list(b_err)
        if figure == "all":
            t_req, _s3, t_err = form_to_traj_request(form, state.config)
            reqs["traj"] = t_req
            errs += list(t_err)
        errors = _dedupe(errs)
        if errors:
            return fail_payload(errors), 400

        def work_multi(_kind, job):
            return run_all_job(reqs, job, figure=figure)

        job = state.jobs.submit(kind, work_multi)
        return {"ok": True, "id": job.id, "kind": kind, "figure": figure,
                "poll": f"/progress/{job.id}", "with_iso": (kind == "scan"),
                "tag": p_req.tag}, 200

    if figure == "bg":
        req, _scene, errors = form_to_bg_request(form, state.config,
                                                 with_scan=(kind == "scan"))
        if errors:
            return fail_payload(errors), 400

        def work_bg(_kind, job):
            return run_bg_job(req, job)

        job = state.jobs.submit(kind, work_bg)
        return {"ok": True, "id": job.id, "kind": kind, "figure": "bg",
                "poll": f"/progress/{job.id}", "with_iso": req.with_scan,
                "tag": req.tag}, 200

    req, _scene, errors = form_to_request(form, state.config, with_iso=(kind == "scan"))
    if errors:
        return fail_payload(errors), 400

    def work_plane(_kind, job):
        return run_plane_job(req, job)

    job = state.jobs.submit(kind, work_plane)
    return {"ok": True, "id": job.id, "kind": kind, "figure": "plane",
            "poll": f"/progress/{job.id}", "with_iso": req.with_iso, "tag": req.tag}, 200


# ===================================================================== 页面


# 首页静态资源：HTML/CSS/JS 已从内嵌字符串拆出来（2026-10-01，见 docs/WEBUI.md）。
# `index.html` 里保留服务端占位符（`__SOLVER__` 等）；`app.css` / `app.js` 是**纯静态**的，
# 由 `GET /static/<name>` 直接吐字节，不经过渲染。
WEB_STATIC_DIR = Path(__file__).resolve().parent / "webui_static"
PAGE_FILE = WEB_STATIC_DIR / "index.html"
#: 3D 查看器的**整页**：没有服务端占位符（job id / 点数 / 底透明度都从 `location.search` 读），
#: 由 `GET /viewer3d` 这条独立路由发字节 —— 故意**不**进 `WEB_STATIC_ASSETS`
#: （白名单只放 CSS/JS 这类纯资源；页面走自己的路由，边界不随页面数量变化）。
VIEWER3D_PAGE = "viewer3d.html"
# 只有这些名字能被 `GET /static/<name>` 直接吐出去。`index.html` **故意不在里面** ——
# 它带着没渲染的占位符，原始字节发出去会露出 `__DEFAULTS__`。
WEB_STATIC_ASSETS = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "viewer3d.css": "text/css; charset=utf-8",
    "viewer3d.js": "application/javascript; charset=utf-8",
}
# 首页模板里的服务端占位符（大写 + 双下划线）。渲染完还剩就是页面静默残缺，必须当场炸。
TOKEN_RE = re.compile(r"__[A-Z][A-Z_]*__")


def read_page_file(name: str) -> str:
    """读 `webui_static/<name>`：先 basename 化挡路径穿越，再要求真的存在。

    「读得到」不等于「发得出去」—— 能不能对外发由 `WEB_STATIC_ASSETS` 在路由那层判。
    名字口径与 `WebState.find_static()` 一致：**带空白/带目录一律拒**，不做宽容修正。
    """
    raw = str(name)
    safe = raw.strip()
    if not safe or safe != raw or Path(safe).name != safe or \
            Path(safe).suffix.lower() not in (".html", ".css", ".js"):
        raise ValueError(f"非法静态资源名：{name!r}")
    path = WEB_STATIC_DIR / safe
    if not path.is_file():
        raise FileNotFoundError(f"静态资源不存在：{safe}")
    return path.read_bytes().decode("utf-8")


def _field_html(f: Field, value) -> str:
    text = "" if value is None else str(value)
    if f.kind == "select":
        opts = []
        for opt in (f.options or ()):
            selected = " selected" if str(opt) == text else ""
            opts.append(f'<option value="{_esc(str(opt))}"{selected}>{_esc(str(opt))}</option>')
        control = f'<select data-field="{_esc(f.name)}">{"".join(opts)}</select>'
    else:
        control = (f'<input data-field="{_esc(f.name)}" type="text" '
                   f'value="{_esc(text)}" autocomplete="off" spellcheck="false">')
    unit = f' <span style="opacity:.7">{_esc(f.unit)}</span>' if f.unit else ""
    hint = f'<div class="hint">{_esc(f.hint)}</div>' if f.hint else ""
    return f'<div><label>{_esc(f.label)}{unit}</label>{control}{hint}</div>'


def _preset_row(presets: dict) -> str:
    if not presets:
        return ""
    opts = []
    for name, item in presets.items():
        summary = str((item or {}).get("summary") or "")
        title = f' title="{_esc(summary)}"' if summary else ""
        opts.append(f'<option value="{_esc(name)}"{title}>{_esc(name)}</option>')
    return ('<div><label>预置想定</label>'
            f'<select data-field="preset"><option value="">（手动填）</option>{"".join(opts)}</select>'
            '<div class="hint">选中后自动填下面各字段（源：targets.presets / preset_form）；'
            '悬停看描述</div></div>')


def _json_in_script(obj) -> str:
    """塞进 `<script>` 的 JSON：`</` 必须转义，否则会提前闭合 script 标签。"""
    return json.dumps(jsonable(obj), ensure_ascii=False).replace("</", "<\\/")


def render_page(state: WebState) -> str:
    """渲染首页。字段行由 `FIGURE_FIELD` / `PRIMARY_FIELDS` / `ADV_FIELDS` / `BG_FIELDS` /
    `TRAJ_FIELDS` 生成，模板里只有占位符。"""
    cfg = state.config
    defaults = defaults_form(cfg)
    std_options = tuple(pool.names())
    adv = []
    for f in ADV_FIELDS:
        if f.name == "standard":
            f = Field(f.name, f.label, f.unit, f.hint, "select", std_options)
        adv.append(_field_html(f, defaults.get(f.name)))
    try:
        targets_note = ("已接入 targets.py（领域校验 / 预置想定由它提供）"
                        if targets_available()
                        else "targets.py 尚未落盘 —— 正在用 webui.py 里的薄封装兜底"
                             "（只做数字解析，领域校验缺位）")
    except Exception as exc:                                  # noqa: BLE001
        targets_note = f"targets.py 导入失败：{exc}"
    repl = {
        "__SOLVER__": _esc(state.solver_text()),
        "__TARGETS__": _esc(targets_note),
        "__PRESETROW__": _preset_row(presets_payload()),
        "__FIGUREROW__": _field_html(FIGURE_FIELD, defaults.get(FIGURE_FIELD.name)),
        "__FIELDROWS__": "".join(_field_html(f, defaults.get(f.name)) for f in PRIMARY_FIELDS),
        "__ADVROWS__": "".join(adv),
        "__BGROWS__": "".join(_field_html(f, defaults.get(f.name)) for f in BG_FIELDS),
        "__TRAJROWS__": "".join(_field_html(f, defaults.get(f.name)) for f in TRAJ_FIELDS),
        "__DEFAULTS__": _json_in_script(defaults),
        "__PRESETS__": _json_in_script(presets_payload()),
        "__META__": _json_in_script({"poll_ms": int(cfg.get("poll_ms") or 500)}),
    }
    page = read_page_file("index.html")
    for token, value in repl.items():
        page = page.replace(token, value)
    leftover = sorted(set(TOKEN_RE.findall(page)))
    if leftover:                                              # 占位符没填 = 页面静默残缺，宁可 500
        raise RuntimeError(f"首页模板里有没被替换的占位符：{leftover}")
    return page


# ===================================================================== 起服务


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *,
                config=None, state: WebState | None = None, quiet: bool = False):
    """建一个（还没开始 serve 的）`ThreadingHTTPServer`。**测试用它 + 后台线程。**"""
    global SERVER_STARTS
    st = state or WebState(config, quiet=quiet)
    st.quiet = bool(quiet)
    st.jobs.echo = not quiet
    httpd = ThreadingHTTPServer((str(host), int(port)), Handler)
    httpd.daemon_threads = True
    httpd.state = st                                        # type: ignore[attr-defined]
    httpd.quiet = bool(quiet)                               # type: ignore[attr-defined]
    SERVER_STARTS += 1
    return httpd


def warmup(state: WebState) -> None:
    """后台预热重模块（matplotlib 那条链）+ 求解器身份，**别让第一次点击等 2 s**。

    预热失败不影响服务：真正的请求会再试一次，并把原因回显到页面上。
    """
    def work():
        try:
            workflow_module()
            state.identity()
        except Exception as exc:                              # noqa: BLE001
            if not state.quiet:
                print(f"[web] 预热失败（首次请求会再试）：{exc}", flush=True)

    threading.Thread(target=work, name="missile-webui-warmup", daemon=True).start()


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, open_browser: bool = False, *,
          config=None, state: WebState | None = None, block: bool = True, quiet: bool = False):
    """起服务并**返回 server 对象**。

    `block=False` ⇒ 在后台线程里 `serve_forever`（测试用；收尾要自己
    `shutdown()` + `server_close()`）。`port=0` ⇒ 由系统分配（`server.server_address[1]`
    拿到真实端口）。

    ⚠ 这个函数**只在 `__main__` 分支或测试里被调用** —— import 期调用会让进程池的
    worker 子进程递归起服务器（技术雷 1）。
    """
    httpd = make_server(host, port, config=config, state=state, quiet=quiet)
    warmup(httpd.state)                                      # type: ignore[attr-defined]
    url = f"http://{host}:{httpd.server_address[1]}/"
    if not quiet:
        print(f"服务已启动：{url}（Ctrl+C 退出）", flush=True)
    if open_browser:
        webbrowser.open(url)
    if not block:
        threading.Thread(target=httpd.serve_forever, name="missile-webui",
                         daemon=True).start()
        return httpd
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，退出。", flush=True)
    finally:
        # `serve_forever` 已经返回（异常穿过它时 finally 里已置好 __is_shut_down），
        # 所以这里**不要**再调 shutdown() —— 同一线程调它会等自己，直接死锁。
        httpd.server_close()
    return httpd


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m missile_sim.webui",
        description="本机 Web 表单：填想定 → 跑求解器 → 出图（纯标准库，无外部依赖）")
    ap.add_argument("--host", default=None, help="绑定地址（默认 127.0.0.1，只对本机开放）")
    ap.add_argument("--port", type=int, default=None, help="端口（默认 8765；0 = 自动分配）")
    ap.add_argument("--config", default=None, help="配置文件（默认 configs/web_default.json）")
    ap.add_argument("--tier", choices=TIERS, default=None, help="覆盖配置里的档位")
    ap.add_argument("--jobs", type=int, default=None, help="覆盖配置里的并发进程数")
    ap.add_argument("--browser", dest="open_browser", action="store_true", default=None,
                    help="启动后自动打开浏览器")
    ap.add_argument("--no-browser", dest="open_browser", action="store_false",
                    help="不要打开浏览器（默认）")
    ap.add_argument("--quiet", action="store_true", help="不打访问日志与任务日志")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    state = WebState(args.config, quiet=args.quiet)          # None ⇒ configs/web_default.json
    for key in ("tier", "jobs"):                             # 命令行 > 配置文件 > 内置默认
        if getattr(args, key) is not None:
            state.config[key] = getattr(args, key)
    host = args.host or state.config["host"]
    port = args.port if args.port is not None else int(state.config["port"])
    open_browser = (state.config.get("open_browser")
                    if args.open_browser is None else args.open_browser)
    serve(host=host, port=port, open_browser=bool(open_browser), state=state,
          quiet=args.quiet)
    return 0


if __name__ == "__main__":                     # pragma: no cover
    # ⚠ 起服务**只能**在这里（或测试里）：`Engine` 的进程池用 spawn，
    # 子进程会重新执行本模块（`-m` 走 name、直接跑 .py 走 path 且 __name__ = __mp_main__），
    # import 期起服务 ⇒ 每个 worker 都递归起一个服务器。
    raise SystemExit(main())

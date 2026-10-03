# -*- coding: utf-8 -*-
"""本机 Web 表单：填想定 → 跑求解器 → 出图（**纯标准库**，只用 `http.server`）。

三条路径，按耗时切：

| 入口 | 做什么 | 为什么这么切 |
| --- | --- | --- |
| `POST /api/single` | **同步**跑一次 `solver.run()`（fast 档实测 ~0.1 s） | 用户填完要立刻看到 `t_hit` / `max_alt` / 末速 / `event` / `backend` |
| `POST /api/submit` `kind=plot` | 后台任务：`run_plane(with_iso=False)`（约 5 s，matplotlib 出图） | 出图比求解慢两个数量级，不能挂住 HTTP 请求 |
| `POST /api/submit` `kind=scan` | 后台任务：`run_plane(with_iso=True)`（fast 1632 工况 ~24 s，standard 档 ~6 min） | 同上；页面对 `/progress/<id>` 轮询进度条 |
| `POST /api/submit` `figure=bg` | 后台任务：`run_bg()`（图2，扫描 ~20 s / 只出图秒级） | 同上 |
| `POST /api/submit` `figure=traj` | 后台任务：`run_traj()`（图4，两遍 ≈1~2 s；`traj_preview=1` 只画目标航迹、不解算，秒级） | 图4 不分扫描/出图，`kind` 只当排队标签用 |
| `POST /api/submit` `figure=both` | 后台任务：图1 + 图2 **顺序**跑在同一任务里 | 与 CLI 的 `--figure both` 对齐（曾经这里只跑图2 却宣称 both） |
| `POST /api/submit` `figure=all` | 后台任务：图1 + 图2 + 图4 **顺序**跑在同一任务里 | 与 CLI 的 `--figure all` 对齐 |
| `GET /viewer3d` | 可拖拽的 3D 查看器**整页**（静态 `viewer3d.html`，数据由下面那条接口喂） | 内嵌用 `<iframe>`、另给「在新标签页打开」；`?bg=transparent` 走透明底 |
| `GET /api/viewer3d/<job_id>` | 把**已经跑完的**图4 任务折成查看器要吃的 JSON（默认 800 点，`?points=` 可覆盖） | 只读产物、**不再解算**（`solver.run` 零调用）；抽稀保留阶段拐点与节点时刻 |
| `GET /fig4` | **空战沙盒**整页（静态 `sandbox.html`）：把一次图4 工况**回放**出来 | **不带参数就能进**（回放 `results/traj_default_*`）；`?job=<id>` / `?tag=` 换数据源 |
| `GET /api/sandbox/<key>` | 沙盒数据 JSON：时间轴 / 事件表 / 双方逐点读数 / 轴刻度 / 悬停字段契约 | 与查看器**同一套**抽稀与配色；只读产物、**不解算**（见 `docs/SANDBOX.md`） |
| `POST /api/submit` `figure=fig3` | 后台任务：`run_fig3()`（图3：11 弹 × (β,γ,ΔV) 立方体，fast 档 2695 工况 ≈ 78 s） | 图3 也只出**产物**（不出静态图），页面在 `GET /fig3` |
| `GET /fig3` | 图3 交互式三维散点**整页**（静态 `fig3.html`，数据由下面那条接口喂） | 与查看器同形态：内嵌用 `<iframe>`、首页给「在新标签页打开」；`?bg=transparent` 走透明底 |
| `GET /api/fig3/<tag_or_job_id>` | 图3 的立方体 + 逐列拟合 + 判别量 → 前端 JSON | 只读产物（`results/fig3_*.json|csv`），**不解算**；`<id>` 既认任务 id 也认 tag |

`figure` 的取值（下拉里全都有）与 CLI 的 `--figure` **一一对应**：
`plane` / `bg` / `traj` / `fig3` 单张，`both` = 图1+图2，`all` = 前三张；`both` / `all` 的摘要用
`parts` 分列每张图（每份都自带 `figure` 键，页面不靠"缺省 = 图1"猜）。

`/api/viewer3d/<job_id>` 与 `/api/sandbox/<key>` 的数据层都在 `traj3d.py`
（纯标准库、只读 `results/traj_*.csv|json`）：前者是 `build()`，后者是 `build_replay()`；
接口与抽稀口径见该模块 docstring、`docs/WEBUI.md` §8 与 `docs/SANDBOX.md`。

`/api/fig3/<id>` 的数据层在 `fig3.py`（同样只读产物：`results/fig3_*.json|csv`，**不 import
求解器与 workflow**），口径与判据见 `docs/FIG3.md`。

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
（见 docs/RESTART-PLAN.md §5；图4 的接入只动本文件与新增的 `tests/test_webui_traj.py`；
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
from dataclasses import dataclass, field, fields, replace
from html import escape as _esc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import engine, pool, presets, solver
from .spec import (DEFAULT_ENV_PRESET, DEFAULT_MISSILE, FIG_DIR, RESULT_DIR, ROOT, TIERS,
                   Scene)

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
    # 图4 的表单专名（`traj_*`，与 CLI 的外部名同一套）。它们全是**请求层**的量：
    # 一个都不属于 `Scene`，少写一个 `targets.build_scene()` 就会把正常提交判成非法输入
    # （它那边对不认识的键是**硬报错**）。
    "traj_t_crank", "traj_crank_deg", "traj_crank_g", "traj_beam_deg", "traj_beam_g",
    "traj_lock_m", "traj_react_delay", "traj_weave", "traj_weave_amp", "traj_weave_hz",
    "traj_t_beam", "traj_preview",
    # 图3 的表单专名（`fig3_*`，与 CLI 的外部名同一套）。同上：一个都不属于 `Scene`。
    # ⚠ `fig3_alt` / `fig3_speed` 是**判别量**参考工况，与 `Scene.alt_m`（载机高度）无关 ——
    # 少写一个，`targets.build_scene()` 就会把正常提交判成"不认识的字段"。
    "fig3_beta_n", "fig3_gamma_n", "fig3_dv_lim", "fig3_dv_n", "fig3_t_react",
    "fig3_dv", "fig3_n", "fig3_alt", "fig3_speed", "fig3_iso_step",
    # v4 共享环境预设（与 A1 的"预置想定" `preset` 不是一回事）
    "env_preset",
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
_FIG3 = None


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


def fig3_module():
    """懒加载 `missile_sim.fig3`（它 import `figures` ⇒ 也是 matplotlib 那条链）。

    与 `traj3d_module()` 同一个理由（模块顶层不碰 matplotlib），
    而且**只读产物、不解算**：它连 `solver` / `workflow` 都不 import。
    """
    global _FIG3
    if _FIG3 is None:
        with _LOCK:
            if _FIG3 is None:
                from . import fig3 as mod
                _FIG3 = mod
    return _FIG3


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


#: 单位 → 标签里的中文写法（用户 2026-10-02 拍板：**单位写在标签里**，照 statshark 的
#: `发射高度（米）`）。不在这张表里的单位原样进括号 —— 宁可显示 `（kg/m²）` 也不要悄悄吞掉。
UNIT_ZH = {"m": "米", "m/s": "米/秒", "°": "度", "s": "秒", "kg/m²": "千克/米²",
           "Hz": "赫兹", "G": "G", "个": "个"}


def unit_suffix(unit: str) -> str:
    """`Field.unit` → 标签后缀：`"m"` → `"（米）"`；空单位 → `""`。"""
    text = str(unit or "").strip()
    text = UNIT_ZH.get(text, text)
    return f"（{text}）" if text else ""


#: 主字段（任务书点名的那些：初始高度 / 初始速度 / 发射距离 / 敌机方向+俯仰+速度+高度）
#: ⚠ 标签里**不再自带单位**：单位由 `unit` 给出、由 `unit_suffix()` 折进标签
#: （照 statshark 的 `发射高度（米）`）。所以 `range_m` 的"水平"挪进 hint —— 否则会出现
#: "发射距离（水平）（米）"这种双层括号。
PRIMARY_FIELDS = (
    Field("range_m", "发射距离", "m", "双方水平距离；斜距按高度差现算"),
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

#: 选图字段。**单独拎出来**放在表单最上面：它同时管图1 / 图2 / 图4，
#: 塞进图2 的字段组里会让人以为它只对图2 生效（那正是"看起来对、其实骗人"的写法）。
#: ⚠ `options` 必须与服务端 `submit_job()` 接受的分流**完全一致**（含 `both`）——
#: 曾经 `both` 能手工 POST 触达、却不在下拉里，于是"只跑图2"这个 bug 藏了很久（D10）。
FIGURE_FIELD = Field(
    "figure", "出哪张图", "",
    "plane = 图1（ΔV–BC）；bg = 图2（β–γ）；traj = 图4（机动想定）；"
    "fig3 = 图3（β–γ–ΔV 交互式三维散点，只出产物，页面在 /fig3）；"
    "both = 图1+图2；all = 前三张都出（不含图3）",
    kind="select", options=("plane", "bg", "traj", "fig3", "both", "all"))

#: 图4（机动想定）专属字段。**不进 `Scene`**，全部是 `TrajRequest` 的量。
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

#: 图4 表单**外部名 → `TrajRequest` 字段名**。方向与 `cli._TRAJ_ALIASES`（字段名 → 外部名）
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

#: 图4 表单的默认值 —— **必须与 `workflow.TrajRequest` 的字段默认值一致**
#: （测试里逐字段比对）。`traj_weave` / `traj_preview` 用空串表示"关"（`_truthy("") is False`），
#: 这样输入框是空的，而不是显示一个 `False`。
TRAJ_DEFAULTS = {
    "traj_t_crank": 8.0, "traj_crank_deg": 70.0, "traj_crank_g": 9.0,
    "traj_beam_deg": 90.0, "traj_beam_g": 9.0, "traj_lock_m": None,
    "traj_react_delay": 1.0, "traj_weave": "", "traj_weave_amp": 4.0,
    "traj_weave_hz": 0.1, "traj_t_beam": None, "traj_preview": "",
}

#: 图3（β–γ–ΔV 交互式三维散点）专属字段。**不进 `Scene`**，全是 `Fig3Request` 的量。
#: `name` 就是表单里的外部名（= CLI 上的 `--fig3-*`），与 `cli._FIG3_ALIASES` 的外层同一套。
#: ⚠ 提示文字（`hint`）**故意留空**：这一组字段的口径写在 `index.html` 的图3 段落里一行说完 ——
#: 首页有个"渲染后 < 20 KB"的判据（防 CSS/JS 被重新内联），每个字段各带一段 hint 会把它顶爆。
#: 语义提醒：`fig3_alt` / `fig3_speed` 是**判别量 R = (n/n*)² 的参考工况**（默认 10 km / 800 m/s），
#: 动它不动任何一个点，只动"谁算诱导阻力主导"那条线；它们**只在 CLI / JSON 上暴露**
#: （表单里不出现，免得首页再胖一圈）。
FIG3_FIELDS = (
    Field("fig3_beta_n", "BC 轴点数", "个", ""),
    Field("fig3_gamma_n", "γ 轴点数", "个", ""),
    Field("fig3_dv_lim", "ΔV 轴区间", "m/s", ""),
    Field("fig3_dv_n", "ΔV 轴点数", "个", ""),
    Field("fig3_t_react", "39 指令时刻（固定）", "s", ""),
)

#: 图3 表单**外部名 → `Fig3Request` 字段名**（与 `cli._FIG3_ALIASES` 方向相反，测试把两张表钉在一起）。
#: `fig3_alt` / `fig3_speed` / `fig3_n` 只在 CLI / JSON 上暴露（表单里没有这三个框 —— 首页有字节判据）。
#: ⚠ **想定字段（crank / beam / 反应延迟 / 震荡）复用图4 的 `traj_*` 那组外部名**，所以不在
#: 这张表里：它们由 `form_to_traj_request()` 解析一次、再原样搬进 `Fig3Request`。
FIG3_ALIASES = {
    "fig3_beta_n": "n_beta", "fig3_gamma_n": "n_gamma",
    "fig3_dv_lim": "dv_lim", "fig3_dv_n": "n_dv", "fig3_dv": "dv_pin",
    "fig3_t_react": "t_react_s",
}

#: 图3 表单默认值 —— **必须与 `workflow.Fig3Request` 的字段默认值一致**（测试逐字段比对）。
FIG3_DEFAULTS = {
    "fig3_beta_n": 7, "fig3_gamma_n": 7,
    "fig3_dv_lim": "700,1700", "fig3_dv_n": 11, "fig3_t_react": 35.0,
}

FORM_SCENE_FIELDS = tuple(f.name for f in PRIMARY_FIELDS)

#: v4 的**共享环境预设**下拉（图1–图4 共用；与 A1 的"预置想定"`preset` 是两件事，
#: 所以键名用 `env_preset`）。选项直接从 `configs/presets.json` 现读；读不到就退到默认名，
#: 让页面仍然能开（真正读不到的那次会在 `defaults_form()` 里报错）。
def _env_preset_options() -> tuple:
    try:
        got = tuple(presets.names())
    except (OSError, ValueError):
        return (DEFAULT_ENV_PRESET,)
    return got or (DEFAULT_ENV_PRESET,)


ENV_PRESET_FIELD = Field(
    "env_preset", "共享环境预设", "",
    "图1–图4 共用的环境 + 基准弹 + 参考工况（见 configs/presets.json）；"
    "表单里改过的字段仍然以表单为准",
    kind="select", options=_env_preset_options())

#: `Scene` 里要转成数字的字段（dt_s / 风 / 地面高度 / 近炸半径本轮 UI 不暴露）
SCENE_FLOAT_FIELDS = ("range_m", "alt_m", "target_alt_m", "target_bearing_deg", "vm0",
                      "launch_heading_deg", "launch_pitch_deg", "target_speed_ms",
                      "target_heading_deg", "target_pitch_deg", "duration_s", "dt_s",
                      "ground_height_m", "hit_radius_m")

_LABEL = {f.name: f.label
          for f in (PRIMARY_FIELDS + ADV_FIELDS + BG_FIELDS + (FIGURE_FIELD,)
                    + TRAJ_FIELDS + FIG3_FIELDS + (ENV_PRESET_FIELD,))}


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


def build_scene_from_form(form: dict, config: dict | None = None):
    """表单 → `(Scene | None, errors)`。**优先用 A1 的 `targets.build_scene`。**

    v4：表单**没点名**的场景字段一律从共享环境预设取（表单点名的照旧以表单为准）。
    表单通常是"全字段回灌"的（页面初始化就把每个字段填好了），所以这条主要救
    `/api/submit` 的**部分表单**与手写 JSON —— 那种情况下"缺字段 ⇒ 退回 `Scene()` 默认值"
    会让预设静默失效。
    """
    part = _scene_part(form)
    try:
        env = presets.resolve(env_preset_name(form, config)).scene_obj()
    except (OSError, ValueError) as exc:
        return None, [f"共享环境预设读取失败：{exc}"]
    tg = targets_module()
    fn = getattr(tg, "build_scene", None) if tg is not None else None
    if callable(fn):
        try:
            scene = fn(part)
        except Exception as exc:                              # noqa: BLE001
            return None, [f"想定解析失败：{exc}"]
        if not isinstance(scene, Scene):
            return None, [f"targets.build_scene() 返回的不是 Scene，而是 {type(scene).__name__}"]
    else:
        scene, errors = _fallback_scene(part)
        # ⚠ 兜底路径是"**带着错误**返回一个能用的 Scene"（坏字段被跳过、其余照收），
        #   不能只在 `scene is None` 时才把错误交出去 —— 那会把 `vm0=abc` 静默吞掉。
        if errors or scene is None:
            return scene, errors
    missing = {f.name: getattr(env, f.name) for f in fields(Scene)
               if f.name not in part and f.name != "maneuvers"}
    return (replace(scene, **missing) if missing else scene), []


#: 表单里所有字段（含图2/图4 与 `figure`）—— "把错误按字段归位"用得上。
ALL_FIELDS = (PRIMARY_FIELDS + ADV_FIELDS + BG_FIELDS + (FIGURE_FIELD, ENV_PRESET_FIELD)
              + TRAJ_FIELDS + FIG3_FIELDS)


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


def _first(query: dict, name: str):
    """从 `parse_qs()` 的结果里取一个参数：它给的是**列表**（同名参数可出现多次），只认第一个。"""
    raw = (query or {}).get(name)
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    return raw


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


def env_preset_name(form: dict, config: dict | None = None) -> str:
    """表单/配置 → 共享环境预设名（没给就是默认那份）。非法名字**当场报错**。"""
    cfg = config or {}
    raw = (form or {}).get("env_preset")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = cfg.get("env_preset")
    return str(raw).strip() if raw is not None and str(raw).strip() else DEFAULT_ENV_PRESET


def defaults_form(config: dict) -> dict:
    """表单初始值：`targets.DEFAULT_FORM`（若有） < **共享环境预设** < 配置文件 < 内置默认。

    ⚠ v4：环境那一层从**共享预设**来（`configs/presets.json`），不再是 `Scene()` 的默认值 ——
    否则"预设下拉"会是个装饰品：它只改 `env_preset` 这一格，而下面每个字段都还是旧值。
    配置文件仍然盖过预设（它是**这台机器**的更具体设定）。
    """
    cfg = config or {}
    tg = targets_module()
    raw_default = getattr(tg, "DEFAULT_FORM", None) if tg is not None else None
    out = dict(raw_default) if isinstance(raw_default, dict) else \
        {name: getattr(Scene(), name) for name in FORM_SCENE_FIELDS}
    name = env_preset_name({}, cfg)
    try:
        env = presets.resolve(name).scene_obj()
    except (OSError, ValueError) as exc:
        raise ValueError(f"共享环境预设 {name!r} 读取失败：{exc}") from exc
    for field_name in FORM_SCENE_FIELDS:
        out[field_name] = getattr(env, field_name)
    out["env_preset"] = name
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
    # 图4：配置 > `TRAJ_DEFAULTS`（后者与 `TrajRequest` 的字段默认值一致）。
    # 用 `setdefault`，这样 `targets.DEFAULT_FORM` 万一给了同名键也不会被覆盖。
    for name, fallback in TRAJ_DEFAULTS.items():
        out.setdefault(name, cfg[name] if cfg.get(name) is not None else fallback)
    # 图3：同上（`FIG3_DEFAULTS` 与 `Fig3Request` 的字段默认值一致）。
    for name, fallback in FIG3_DEFAULTS.items():
        out.setdefault(name, cfg[name] if cfg.get(name) is not None else fallback)
    out.setdefault("figure", "plane")
    if cfg.get("missiles"):
        out["missiles"] = ",".join(str(x) for x in cfg["missiles"])
    if not out.get("jobs"):
        out["jobs"] = engine.default_jobs()
    return out


def presets_payload(base: dict | None = None) -> dict:
    """A1 的预置想定 → `{名字: {"summary": 一行描述, "d": 与首屏初值不同的字段}}`（chip 一键填充）。

    走 A1 的真实契约：`presets()` 给 `{名字: 摘要}`，`preset_form(名字)` 给表单初值。
    两者的返回形态都做了容错（dict / list / tuple、`(名字, 表单)`、直接是 `Scene`），
    这样 A1 那边改形态不会把页面打空。A1 未落盘 ⇒ `{}`（页面上就没有预置想定 chip）。

    `base` 给的是首屏初值（`defaults_form()`）：给了就**只发差值**（前端 `presetForm()`
    用 `DEFAULTS` + 差值还原完整表单），不给就发全量 —— 见 `preset_delta()` 里那条字节数理由。
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
                out[str(name)] = {"summary": _preset_summary(raw, name),
                                  "d": preset_delta(form, base)}
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
            out[name] = {"summary": "", "d": preset_delta(form, base)}
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


# ===================================================================== 左栏分组与 chip
#
# 用户 2026-10-02 拍板：四页统一成 statshark 那种「左栏 = 输入，右栏 = 主视图」的骨架，
# 预设从下拉框改成 **chip 网格**。这一节是那个骨架的**数据侧**：谁归哪一组、chip 点下去
# 每个输入框该显示什么值。渲染在 `_field_html()` / `chips_html()`（文件后半段）。

#: 左栏的分组（照 statshark：弹种与基准弹在最上面，然后先我方、后目标，最后绘图设置）。
#: 名字必须都在 `ALL_FIELDS` 里 —— 有测试逐条钉住，免得加了字段却漏进左栏
#: （那会变成"页面上填了但不生效"的静默失败）。
BASE_GROUP = ("standard", "tier")
LAUNCH_GROUP = ("range_m", "alt_m", "vm0", "launch_heading_deg", "launch_pitch_deg",
                "observation")
TARGET_GROUP = ("target_speed_ms", "target_alt_m", "target_bearing_deg",
                "target_heading_deg", "target_pitch_deg", "duration_s")
VIEW_GROUP = ("figure", "iso_step", "dv_step", "bc_step", "missiles", "xlim", "ylim",
              "tag", "jobs")
#: 共用骨架的四个分区：`(id, 标题, 字段名)`。图2/图4/图3 的专属字段**不进这里** ——
#: 它们各自留在可折叠的 `<details>` 里（一页承载四张图的输入，左栏不能被它们撑散）。
RAIL_GROUPS = (("base", "弹种与基准弹", BASE_GROUP), ("launch", "发射端", LAUNCH_GROUP),
               ("target", "目标端", TARGET_GROUP), ("view", "绘图与网格", VIEW_GROUP))
_FIELD_BY_NAME = {f.name: f for f in ALL_FIELDS}


def group_rows(names, defaults: dict) -> str:
    """按分组渲染输入行（`standard` 的选项在渲染期从弹池现取，与旧版一致）。"""
    rows = []
    for name in names:
        f = _FIELD_BY_NAME[name]
        if name == "standard":
            f = Field(f.name, f.label, f.unit, f.hint, "select", tuple(pool.names()))
        rows.append(_field_html(f, (defaults or {}).get(name)))
    return "".join(rows)


def chip_text(label: str, name: str) -> str:
    """长标签 → chip 上的短名：`默认：50 km 迎头 …` → `默认`（没有冒号就用原名）。"""
    text = str(label or "").strip()
    head = text.split("：", 1)[0].strip() if "：" in text else ""
    return head or text or str(name)


def chips_html(items) -> str:
    """chip 网格。`items` 是 `[(值, 短标签, data 属性后缀)]`。

    ⚠ 这里**不写 `title`**：chip 的长说明（预设描述 / 预置想定摘要）已经躺在 boot 数据里，
    再往 HTML 里抄一份会让首页顶破"渲染后 < 20 KB"那条判据。`app.js` 开机时从 boot 数据
    把 `title` 补上 —— 用户看到的完全一样，页面小一截。
    """
    out = []
    for value, text, attr in items:
        out.append(f'<button type="button" class="chip" data-{attr}="{_esc(value)}">'
                   f'{_esc(text)}</button>')
    return "".join(out)


def hidden_select(field_name: str, items, blank: str = "", value=None) -> str:
    """chip 网格背后的**字段本体**（`hidden` 的 `<select>`，`collect()` 照收）。

    为什么不把 chip 自己当字段：`collect()` 扫的是 `[data-field]`，一排 chip 会互相覆盖
    （`querySelectorAll` 里最后一个赢）。字段仍然只有一个，chip 只负责改它的值 ——
    这样"点 chip"与"改下拉"在请求里是同一件事。

    ⚠ `value` 必须把当前值标成 `selected`：`<select>` 不标就默认选**第一个** option，
    于是"配置里把 `env_preset` 设成 close"会让表单显示 close 的字段值、请求里却发
    `env_preset=default` —— 看起来一切正常，实际两套口径（`test_webui_layout.py` 钉住）。
    """
    current = "" if value is None else str(value)
    opts = []
    if blank:
        opts.append(f'<option value=""{" selected" if current == "" else ""}>'
                    f'{_esc(blank)}</option>')
    for item_value, text, _attr in items:
        sel = " selected" if str(item_value) == current else ""
        opts.append(f'<option value="{_esc(item_value)}"{sel}>{_esc(text)}</option>')
    return (f'<select id="f-{_esc(field_name)}" data-field="{_esc(field_name)}" hidden>'
            f'{"".join(opts)}</select>')


def _same_scalar(a, b) -> bool:
    """两个表单值算不算同一个（数字按数值比，其余按去空白字符串比）。"""
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def preset_delta(form: dict, base: dict | None) -> dict:
    """预设表单 → **只留与首屏初值不同的键**（`base` = `defaults_form()`；None = 全留）。

    9 份预设 × 18 个字段原样铺开会把首页顶过"渲染后 < 20 KB"的判据。差值编码**一点信息
    都没少**：前端 `presetForm()` 用 `DEFAULTS` + 差值还原出完整表单，chip 点下去照样把
    每个输入框填成该预设的值 —— 变的只是传输形式。
    """
    if base is None:
        return dict(form or {})
    return {k: v for k, v in (form or {}).items()
            if k not in base or not _same_scalar(v, base[k])}


def env_presets_payload(base: dict | None = None) -> dict:
    """**共享环境预设** → `{"_keys": [...], 名字: {"label":…, "d": {与初值不同的字段}}}`。

    `d` 还原出来的完整表单 = "点这个 chip 之后每个输入框该显示什么"。取值口径与
    `defaults_form()` 对齐（环境字段 + 基准弹 + 档位 + 等时线层 + 参考工况都来自预设），
    否则点完 chip 表单与预设对不上，"已偏离预设"会永远亮着 —— 那正是"装饰性预设"的另一种写法。

    ⚠ `_keys` 是**预设真正管的字段清单**（下划线开头 = 保留键，与 configs 那边的注释约定同源）。
    前端算"已偏离预设"只许看这些键：`figure` / `tag` / `jobs` / 网格步长这些**视图与输出**
    设置本来就不在预设层里，拿它们点灯会变成"一开页面就说你偏离了"（真踩过）。
    """
    try:
        table = presets.load()
    except (OSError, ValueError) as exc:
        print(f"[web] 共享环境预设读取失败：{exc}", flush=True)
        return {}
    out: dict = {"_keys": []}
    for name, pre in table.items():
        scene = pre.scene_obj()
        form = {f: jsonable(getattr(scene, f)) for f in FORM_SCENE_FIELDS}
        form.update({"env_preset": name, "standard": pre.standard, "tier": pre.tier,
                     "iso_step": pre.iso_step, "dv_pin": pre.dv_pin, "n_ref": pre.n_ref,
                     "bg_alt_m": pre.ref_alt_m, "bg_speed_ms": pre.ref_speed_ms})
        if not out["_keys"]:
            out["_keys"] = list(form)
        out[name] = {"label": pre.label or name, "d": preset_delta(form, base)}
    return out


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
        scene=scene, env_preset=env_preset_name(form, config),
        standard=(std.key if std else std_name), missiles=missiles,
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
        scene=scene, env_preset=env_preset_name(form, config),
        standard=(std.key if std else std_name), missiles=missiles,
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
    """图4 表单数字字段：**表单 > 配置 > `TRAJ_DEFAULTS`**（后者 = `TrajRequest` 默认值）。

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
    """图4 表单布尔字段（`traj_weave` / `traj_preview`）：**非空就以它为准**，否则看配置/默认。

    走 `_truthy`，所以 `1` / `true` / `是` / `on` 都算开，`""` / `0` / `false` / `no` / `off` / `否`
    都算关 —— 与 `_fallback_scene` 处理 `proximity_fuse` 是同一套。
    """
    raw = form.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = (config or {}).get(name, TRAJ_DEFAULTS.get(name))
    return _truthy(raw)


def form_to_traj_request(form: dict, config: dict, *, preview: bool | None = None):
    """表单 → `(TrajRequest | None, Scene | None, errors)`（图4 专用）。

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
        scene=scene, env_preset=env_preset_name(form, config),
        standard=(std.key if std else std_name), tier=tier,
        t_crank=t_crank, crank_deg=crank_deg, crank_g=crank_g, beam_deg=beam_deg,
        beam_g=beam_g, lock_distance_m=lock_m, react_delay_s=react, weave=weave,
        weave_amp_deg=amp, weave_hz=hz, t_beam_s=t_beam, preview=do_preview,
        tag=tag, formats=formats,
        figure_dir=Path(cfg["figure_dir"]) if cfg.get("figure_dir") else None,
        result_dir=Path(cfg["result_dir"]) if cfg.get("result_dir") else None)
    errors.extend(req.check())
    return req, scene, _dedupe(errors)


def _dv_lim_of(raw, errors: list, label: str):
    """`700,1700` → `(700.0, 1700.0)`。非法值**报错**，不静默给默认值。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = FIG3_DEFAULTS["fig3_dv_lim"]
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        parts = [str(v) for v in raw]
    else:
        parts = [p for p in str(raw).replace("，", ",").split(",") if p.strip()]
    if len(parts) != 2:
        errors.append(f"{label} 要写成 `下限,上限` 两段，收到 {raw!r}")
        return None
    try:
        lo, hi = (float(parts[0]), float(parts[1]))
    except (TypeError, ValueError):
        errors.append(f"{label} 里 {raw!r} 不是数字")
        return None
    if not (hi > lo):
        errors.append(f"{label} 必须递增，收到 {lo:g},{hi:g}")
        return None
    return (lo, hi)


def _dv_factors_of(raw, errors: list, label: str):
    """`0.6,0.8,1.0,1.2,1.4` → 浮点元组。非法值**报错**，不静默给默认值。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = FIG3_DEFAULTS["fig3_dv_factors"]
    if isinstance(raw, (list, tuple)):
        parts = [str(v) for v in raw]
    else:
        parts = [p for p in str(raw).replace("，", ",").split(",") if p.strip()]
    out = []
    for p in parts:
        try:
            v = float(str(p).strip())
        except (TypeError, ValueError):
            errors.append(f"{label} 里 {p!r} 不是数字")
            return None
        if v <= 0:
            errors.append(f"{label} 的倍数必须为正，收到 {v}")
            return None
        out.append(v)
    if len(out) < 2:
        errors.append(f"{label} 至少要两个点，收到 {raw!r}")
        return None
    return tuple(out)


def form_to_fig3_request(form: dict, config: dict):
    """表单 → `(Fig3Request | None, Scene | None, errors)`（图3 专用）。

    与 `form_to_bg_request()` / `form_to_traj_request()` 同构：共用场景解析、兼容性校验、
    基准弹解析与弹池解析，区别只在字段集（`fig3_*` 外部名 → `Fig3Request` 的短字段名）。

    ⚠ 图3 **没有** `formats`（它不出静态图），但 `tag` 有：产物名是 `fig3_<tag>.json|csv`。

    **想定（工况）复用图4**：crank / beam / 反应延迟 / 震荡这些字段走 `TRAJ_FIELDS`（外部名
    `traj_*`），这里直接调 `form_to_traj_request()` 解析一次，再把结果搬进来 ——
    两个页面上的同一个旋钮只有一个解析落点（用户口径："工况按图4 的工况作为默认"）。
    图3 只多一个 `fig3_t_react`：**固定的** 39 指令时刻（图4 是每弹反求 `t_beam` + 延迟）。
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
    # ⚠ `form.get(k) or 默认` 会把**合法输入 0** 当成"没给"（`0 or 35.0 == 35.0`）——
    #   于是 `fig3_t_react=0` 不报错、悄悄用 35 s。空白判定必须显式写。
    def _or_default(key):
        raw = form.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return FIG3_DEFAULTS[key]
        return raw

    n_beta = _num_of(_or_default("fig3_beta_n"), 7,
                     "BC 轴点数", errors, lo=2, hi=64, integer=True)
    n_gamma = _num_of(_or_default("fig3_gamma_n"), 7,
                      "γ 轴点数", errors, lo=2, hi=64, integer=True)
    dv_lim = _dv_lim_of(form.get("fig3_dv_lim"), errors, "ΔV 轴区间")
    n_dv = _num_of(_or_default("fig3_dv_n"), 11,
                   "ΔV 轴点数", errors, lo=2, hi=64, integer=True)
    t_react = _num_of(_or_default("fig3_t_react"), 35.0,
                      "39 指令时刻", errors, lo=1e-9)
    dv_pin = _num_of(form.get("fig3_dv"), None, "ΔV 参考标记", errors, lo=1e-9, allow_blank=True)
    # `fig3_n` / `fig3_alt` / `fig3_speed` **不在表单里**（只在 CLI / JSON 上暴露），
    # 所以这里读的是"表单没给 ⇒ 用 `Fig3Request` 的默认值 / None"。
    n_ref = _num_of(form.get("fig3_n"), 20.0, "判别量参考过载", errors, lo=1e-9)
    ref_alt = _num_of(form.get("fig3_alt"), None, "判别量参考高度", errors,
                      lo=0.0, allow_blank=True)
    ref_speed = _num_of(form.get("fig3_speed"), None, "判别量参考速度", errors,
                        lo=1e-9, allow_blank=True)
    tag = _tag_of(form.get("tag") or cfg.get("tag") or "web")

    # ---- 想定：复用图4 的解析（同一个 `traj_*` 字段集）--------------------------
    tq, _scene2, tq_errors = form_to_traj_request(form, config)
    errors.extend(tq_errors)

    wf = workflow_module()
    proto = wf.Fig3Request()
    base = wf.Fig3Request()
    req = wf.Fig3Request(
        scene=scene, env_preset=env_preset_name(form, config),
        standard=(std.key if std else std_name), tier=tier, jobs=jobs,
        missiles=missiles, cache=True,
        n_beta=(n_beta or 7), n_gamma=(n_gamma or 7),
        dv_lim=(dv_lim or tuple(base.dv_lim)), n_dv=(n_dv or base.n_dv), dv_pin=dv_pin,
        n_ref=(n_ref or 20.0), ref_alt_m=ref_alt, ref_speed_ms=ref_speed, tag=tag,
        iso_step=float(presets.resolve(env_preset_name(form, config)).iso_step),
        # 想定（图4 的解析结果；拿不到就用 `Fig3Request` 自己的默认值）
        t_crank=(tq.t_crank if tq is not None else proto.t_crank),
        crank_deg=(tq.crank_deg if tq is not None else proto.crank_deg),
        crank_g=(tq.crank_g if tq is not None else proto.crank_g),
        beam_deg=(tq.beam_deg if tq is not None else proto.beam_deg),
        beam_g=(tq.beam_g if tq is not None else proto.beam_g),
        react_delay_s=(tq.react_delay_s if tq is not None else proto.react_delay_s),
        weave=bool(tq.weave) if tq is not None else proto.weave,
        weave_amp_deg=(tq.weave_amp_deg if tq is not None else proto.weave_amp_deg),
        weave_hz=(tq.weave_hz if tq is not None else proto.weave_hz),
        t_react_s=(t_react or proto.t_react_s),
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
                # 一次提交四块时，这里给出**四块各自**的状态/计数/失败原因（没四块时是空 dict）
                "blocks": dict(getattr(self, "blocks", None) or {}),
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

    ⚠ `figure: "plane"` 这个键**必须**在（图2/图4 的摘要一直都有）：`figure=both/all` 的合并
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
    """后台任务体：`workflow.run_traj()`（图4，两遍法；`preview` **不解算**）。

    ⚠ 口径（2026-09-30 `fig3-verifier` 打桩取证）：`preview=True` 时 `solver.run` **零调用**，
    但会调一次 `solver.profile` 读 blk 拿 `guidance.lockDistance` —— 所以是"不**解算**"，
    不是"完全不碰 solver"；耗时也不是毫秒级（含出图约 1~3 s）。
    """
    wf = workflow_module()
    job.message = ("预览目标航迹（不解算）…" if req.preview
                   else "解算机动想定（两遍：反求开机 → 正式工况）…")
    out = wf.run_traj(req, progress=job.progress, log=job.log)
    return summarize_traj(out, req)


def summarize_fig3(out: dict, req) -> dict:
    """`run_fig3()` 的返回值 → 页面要的那点东西（**不带立方体、不带逐工况行**）。

    与 `summarize_traj()` 同一套：`paths` 里的 `record`/`cases` 就是产物路径，
    查看器数据层（`fig3.paths_of()`）靠这两个键认领自己的产物。
    图3 **没有静态图**，所以 `figures` / `figure_urls` 是两个空列表（页面按 `figure` 分支渲染）。
    """
    paths = dict(out.get("_paths") or {})
    entry = out.get("standard")
    return {
        "ok": True, "figure": "fig3",
        "tier": req.tier,
        "standard": getattr(entry, "key", None) or req.standard,
        "native": getattr(entry, "native", ""),
        "tag": req.tag,
        "shape": list(getattr(out.get("grid"), "shape", ()) or ()),
        "n_missiles": int(out.get("n_missiles") or 0),
        "n_total": int(out.get("n_total") or 0),
        "n_hit": int(out.get("n_hit") or 0),
        "n_run": int(out.get("n_run") or 0),
        "n_cached": int(out.get("n_cached") or 0),
        "dv_pin": _finite_or_none(out.get("dv_pin"), 4),
        "n_ref": _finite_or_none(req.n_ref, 2),
        "beta_points": int(req.n_beta), "gamma_points": int(req.n_gamma),
        "dv_points": len(tuple(req.dv_factors)),
        "elapsed_s": round(float(out.get("elapsed_s") or 0.0), 2),
        "scene_text": describe(req.scene),
        "viewer_url": f"/fig3?tag={req.tag}",
        "figures": [], "figure_urls": [],
        "paths": {k: str(v) for k, v in paths.items()},
    }


def run_fig3_job(req, job: Job) -> dict:
    """后台任务体：`workflow.run_fig3()`（11 弹 × (β,γ,ΔV) 立方体，fast 档 ≈ 78 s）。

    图3 不出静态图，所以这个任务干的事就是"算 + 落两份产物"；页面随后用
    `GET /api/fig3/<job_id>`（同一份产物）喂 3D 查看器。
    """
    wf = workflow_module()
    job.message = (f"扫描 (β,γ,ΔV) 立方体：{req.n_beta}×{req.n_gamma}×"
                   f"{len(tuple(req.dv_factors))} × 弹池（fast 档快，standard 档慢得多）…")
    out = wf.run_fig3(req, progress=job.progress, log=job.log)
    return summarize_fig3(out, req)


def summarize_all(parts: list, *, figure: str = "all") -> dict:
    """`figure=both` / `figure=all`：各张图的摘要 → 一个合并摘要（页面按 `parts` 列名字）。

    刻意**不做二次加工** —— 每张图的摘要原样放进 `parts`（只把 `figure` 键补成显式值，
    这样任何读 `parts[i]["figure"]` 的地方都不必猜缺省），页面要细节时直接读那一份，
    免得这里再维护一套"合并后的字段"（那种字段最容易和上面几个 `summarize_*` 走散）。

    `figure` 是这一单的名字：`"both"` = 图1+图2（与 CLI `--figure both` 对齐），
    `"all"` = 图1+图2+图4，`"four"` = **一次提交的四块**（沙盒+图1+图2+图3，与 `--figure four` 对齐）。
    **不接受** `"bg"` 之类会与单张摘要撞名的值。
    """
    if figure not in ("both", "all", "four"):
        raise ValueError(f"合并摘要只服务于 both / all / four，收到 {figure!r}")
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


#: 四块的机器名 → 中文标题（`/progress` 与页面文案共用一张表，免得两边各叫一套）
BLOCK_TITLES = {"fig4": "图4 空战沙盒", "fig1": "图1 ΔV–β", "fig2": "图2 β–γ", "fig3": "图3 ΔV–β–γ"}
#: 一次提交四块时的固定顺序：**沙盒置顶**（用户口径 docs/UX-TARGET.md §1），再 图1 → 图2 → 图3
BLOCK_ORDER = ("fig4", "fig1", "fig2", "fig3")


def blocks_of(job: Job) -> dict:
    """任务的四块台账（懒建；非 slots 的 dataclass 允许动态属性，不动 `Job` 定义）。"""
    got = getattr(job, "blocks", None)
    if got is None:
        got = {}
        job.blocks = got
    return got


def set_block(job: Job, name: str, **fields) -> dict:
    """写一块的状态，并把标题/顺序补齐 —— 页面与 `/progress` 只读这份台账。"""
    rec = blocks_of(job).setdefault(name, {"name": name, "title": BLOCK_TITLES.get(name, name),
                                           "order": BLOCK_ORDER.index(name) if name in BLOCK_ORDER
                                           else len(BLOCK_ORDER)})
    rec.update(fields)
    return rec


def run_four_job(reqs: dict, job: Job) -> dict:
    """`figure=four` 的任务体：**一次提交出四块**。

    顺序：**图4 沙盒**（真解算这次工况的轨迹 —— 走 `run_traj_job`，与单独提交 traj 完全同一条链）
    → 图1（`with_iso=True`，扫等时线）→ 图2（`with_scan=True`，扫网格）→ 图3（11 点标称；等时面仍按需扫单弹，
    不在提交里扫，见"滑块零请求"契约）。

    ⚠ 三条硬要求：
    * **逐块 `try/except`**：某块失败**不删**别块的成果，但整任务必须落到 `error`（调用方据此判），
      并把"哪几块挂了、为什么"写在 `message` 与那一块的 `error` 里 —— 绝不装成功；
    * 四块**共用同一份输入**：`reqs` 是同一个表单解析出来的四个请求，没有任何一块各自再解析一次；
    * 每块的摘要**存进台账**（`blocks[name]["result"]`），所以某块挂了也不影响别块在页面上出图。
    """
    steps = (("fig4", reqs.get("traj"), run_traj_job),
             ("fig1", reqs.get("plane"), run_plane_job),
             ("fig2", reqs.get("bg"), run_bg_job),
             ("fig3", reqs.get("fig3"), run_fig3_job))
    parts, failed, skipped = {}, [], []
    for name, req, runner in steps:
        if req is None:
            skipped.append(name)
            set_block(job, name, state="skipped", error="", message="本次输入没带这一块")
            continue
        set_block(job, name, state="running", error="", message="正在跑…")
        job.log(f"=== {BLOCK_TITLES[name]} ===")
        try:
            summary = runner(req, job)
        except Exception as exc:                              # noqa: BLE001 - 逐块兜住
            text = f"{type(exc).__name__}: {exc}"
            failed.append(name)
            set_block(job, name, state="error", error=text, message="失败")
            job.log(f"!! {BLOCK_TITLES[name]} 失败：{text}")
            continue
        parts[name] = summary
        set_block(job, name, state="done", error="", message="完成", result=summary)
    out = summarize_all([parts[n] for n in BLOCK_ORDER if n in parts], figure="four")
    # 每块的**摘要原样留着**：页面按 `r.blocks[k].result` 取那一块的产物与数字，
    # 与 `/progress` 时的台账同构（不在这里另做一套"合并后的字段"）。
    out["blocks"] = {k: dict(v) for k, v in blocks_of(job).items()}
    out["blocks_failed"] = list(failed)
    out["blocks_skipped"] = list(skipped)
    if failed:
        out["ok"] = False
        names = "、".join(BLOCK_TITLES[n] for n in failed)
        raise RuntimeError(f"这次提交有 {len(failed)} 块失败：{names} —— 其余各块的结果仍在页面上"
                           "（逐块状态见四块列表）")
    return out


def run_all_job(reqs: dict, job: Job, *, figure: str = "all") -> dict:
    """`figure=both` / `figure=all` 的任务体：按 CLI 的顺序跑在同一个后台任务里。

    `both` ⇒ 图1 → 图2；`all` ⇒ 图1 → 图2 → 图4（与 `cli.main()` 的 dispatch 一一对应，
    `reqs` 里没有的那几张自动跳过）。任一张抛异常 ⇒ 整个任务 `error`（和 CLI 一样）。
    `kind` 只决定图1/图2 跑不跑仿真层（`scan` 跑、`plot` 只出图），图4 不看 `kind`。
    """
    steps = ((reqs.get("plane"), run_plane_job, "图1"),
             (reqs.get("bg"), run_bg_job, "图2"),
             (reqs.get("traj"), run_traj_job, "图4"))
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
        GET  /static/<name>     首页自己的 CSS/JS（白名单 app.css / app.js / viewer3d.css / viewer3d.js / fig3.css / fig3.js）
        GET  /viewer3d          可拖拽 3D 查看器整页（`viewer3d.html`，数据走 /api/viewer3d/<id>）
        GET  /api/viewer3d/<id> 图4 任务的查看器数据（JSON，默认 800 点；不解算）
        GET  /fig3              图3 交互式三维散点整页（`fig3.html`，数据走 /api/fig3/<id>）
        GET  /api/fig3/<id>     图3 的立方体 + 逐列拟合 + 判别量（JSON；只读产物、不解算）
        GET  /api/fig3/<id>/layers?missile=<key>  单枚弹的 13 层等时面网格（一次给全；滑块零往返）
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
            if path.startswith("/api/sandbox/"):
                return self._sandbox_data(unquote(path.split("/", 3)[3]),
                                         parse_qs(parsed.query))
            if path in ("/viewer3d", "/viewer3d.html"):
                return self._viewer3d_page()
            # 别名（随下个破坏性版本删）：沙盒整页的老路径 /sandbox -> 302 -> /fig4
            if path in ("/sandbox", "/sandbox.html"):
                loc = "/fig4" + ("?" + parsed.query if parsed.query else "")
                return self._redirect(loc)
            if path in ("/fig4", "/fig4.html"):
                return self._sandbox_page()
            # 别名（随下个破坏性版本删）：老三维数据路径 /api/fig4/<id> 原样兼容
            if path.startswith("/api/fig4/"):
                return self._fig3_data(unquote(path.split("/", 3)[3]))
            if path.startswith("/api/fig3/"):
                rest = path.split("/", 3)[3]
                if "/layers" in rest:
                    ref, _slash = rest.split("/layers", 1)
                    q = parse_qs(parsed.query)
                    return self._fig3_layers(unquote(ref), (q.get("missile") or [""])[0])
                return self._fig3_data(unquote(rest))
            if path in ("/fig3", "/fig3.html"):
                return self._fig3_page()
            if path.startswith("/static/"):
                return self._web_static(unquote(path.rsplit("/", 1)[1]))
            if path.startswith("/figures/") or path.startswith("/results/"):
                return self._static(unquote(path.rsplit("/", 1)[1]))
            return self._fail([f"未知路径 {path}"], 404)
        except Exception as exc:                              # noqa: BLE001
            return self._json({"ok": False,
                               "errors": [f"{type(exc).__name__}: {exc}"]}, 500)

    def _redirect(self, location: str):
        """302 到新路径 —— 只给**别名**用（随下个破坏性版本删）。"""
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

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

    def _fig3_page(self):
        """`fig3.html` 与 `viewer3d.html` 同一条形态：**独立路由**发整页字节。

        job id / tag 都从 `location.search` 读（`/fig3?tag=web&bg=transparent`），
        所以页面里没有服务端占位符；它同样**不**进 `/static/` 白名单 ——
        白名单只放 CSS/JS 这类纯资源，页面一律走自己的路由。
        """
        try:
            data = read_page_file(FIG3_PAGE).encode("utf-8")
        except (OSError, ValueError):
            return self._fail([f"找不到图3 页面 {FIG3_PAGE!r}"], 404)
        return self._send(200, data, "text/html; charset=utf-8")

    def _fig3_data(self, ref: str):
        payload, code = fig3_payload(self.state, ref)
        return self._json(payload, code)

    def _fig3_layers(self, ref: str, missile: str):
        """`GET /api/fig3/<id>/layers?missile=<key>` —— 单枚弹的全部等时面层。"""
        payload, code = fig3_layers_payload(self.state, ref, missile)
        return self._json(payload, code)

    def _sandbox_page(self):
        """`sandbox.html` 也是一条**独立路由**（与 `viewer3d.html` 同样的理由）。

        它没有服务端占位符（job id / 点数 / 时刻都从 `location.search` 读），所以直接发字节。
        """
        try:
            data = read_page_file(SANDBOX_PAGE).encode("utf-8")
        except (OSError, ValueError):
            return self._fail([f"找不到沙盒页面 {SANDBOX_PAGE!r}"], 404)
        return self._send(200, data, "text/html; charset=utf-8")

    def _sandbox_data(self, key: str, query: dict = None):
        # ⚠ `?tag=` **故意不接**（2026-10-03 用户口径）：它曾经是"按 tag 回放仓库旧产物"的后门。
        payload, code = sandbox_payload(self.state, key, _first(query, "points"))
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
    * 这个任务里没有图4 的产物（图1 / 图2 / `traj_preview=1` 的预览）→ 404，并说清是哪一种。

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
            "所以没有可拖拽的 3D 数据。把「只出 3D 预览」清空（正式跑一次图4）后就有。"]), 404
    try:
        payload = t3.build(paths, points=points, job=job.id, tag=part.get("tag"),
                           extra={"native": part.get("native") or ""})
    except FileNotFoundError as exc:
        return fail_payload([str(exc)]), 404
    return payload, 200


#: 正在跑的"扫单弹立方体"任务：`(id(state), tag, missile) → job_id`（复用，不重复扫）。
_CUBE_JOBS: dict = {}
_CUBE_LOCK = threading.Lock()


def _fig3_ref(state: WebState, ref: str) -> tuple:
    """`/api/fig3/<id>/...` 的 `<id>` → `(tag, job_or_None, record_paths)`（与 `fig3_payload` 同一套语义）。"""
    f4 = fig3_module()
    key = str(ref or "").strip() or "default"
    job = state.jobs.get(key)
    if job is not None:
        if job.state != "done":
            raise RuntimeError(f"任务还没跑完（state={job.state}）")
        paths, part = f4.paths_of(job.result or {})
        return (part.get("tag") or key), job, paths
    try:
        tag = f4.parse_tag(key)
    except ValueError:
        raise
    return tag, None, f4.default_paths(tag)


def fig3_layers_payload(state: WebState, ref: str, missile: str):
    """`GET /api/fig3/<tag_or_job_id>/layers?missile=<key>`：**一枚弹的全部 N 层等时面**。

    立方体**按需**算：

    * 缓存里有（指纹对得上）⇒ **200**，直接给全部 13 层（滑块之后零请求）；
    * 没有 ⇒ 起（或复用）一个**后台扫描任务** ⇒ **202** + `{scanning, job, message, poll, expected}`，
      页面显示"正在扫描 X：539 工况"并轮询 `/progress/<id>`，算完再打一次本接口就是 200。
    """
    f4 = fig3_module()
    want = str(missile or "").strip()
    if not want:
        return fail_payload(["要指定 missile=<弹池短名>（等时面是**单枚弹**的）"]), 400
    try:
        tag, job_ref, paths = _fig3_ref(state, ref)
    except RuntimeError as exc:
        return fail_payload([str(exc)]), 409
    except ValueError as exc:
        return fail_payload([str(exc)]), 400
    try:
        rec = f4.read_record(paths["record"])
    except (OSError, ValueError) as exc:
        return fail_payload([f"图3 产物读不到：{exc}（重出：python -m missile_sim "
                             f"--figure fig3 --tag {tag}）"]), 404
    grid = rec.get("grid") or {}
    scene = dict(rec.get("scene") or {})
    tier = str(rec.get("tier") or "fast")
    sha = str((rec.get("solver") or {}).get("sha256") or "")
    known = [str(m.get("key") or "") for m in (rec.get("missiles") or ())]
    if want not in known:
        # ⚠ 弹名不认识要**先**判：否则会为它起一个永远扫不出来的后台任务（页面卡在"正在扫描"）
        return fail_payload([f"产物里没有这枚弹：{want!r}（有：{' / '.join(known)}）"]), 404
    try:
        cpath = f4.cube_path(want, scene=scene, tier=tier, grid=grid, solver_sha=sha)
    except ValueError as exc:
        return fail_payload([str(exc)]), 404
    # ① 缓存命中 ⇒ 200
    try:
        cube = f4.read_cube(cpath["cube"], missile=want, scene=scene, tier=tier, grid=grid,
                            solver_sha=sha)
    except (OSError, ValueError):
        cube = None
    if cube is not None:
        cube["cache_read_hit"] = True
        try:
            payload = f4.layers_payload(paths, missile=want, cube=cube,
                                        job=(job_ref.id if job_ref is not None else None),
                                        tag=tag)
        except KeyError as exc:
            return fail_payload([str(exc)]), 404
        except (FileNotFoundError, ValueError) as exc:
            return fail_payload([str(exc)]), 404
        return payload, 200
    # ② 没缓存 ⇒ 起/复用后台任务，202
    try:
        n_cases = int(grid.get("n_cases") or 0)
        job = _start_cube_job(state, tag=tag, missile=want, rec=rec)
    except Exception as exc:                              # noqa: BLE001
        return fail_payload([f"起扫描任务失败：{exc}"]), 500
    payload = {
        "ok": False, "scanning": True, "figure": "fig3", "tag": tag, "missile": want,
        "job": job.id, "state": job.state, "done": job.done, "total": job.total,
        "message": f"正在扫描 {want}：{n_cases} 工况（{tier}）",
        "poll": f"/progress/{job.id}",
        "retry": f"/api/fig3/{ref}/layers?missile={want}",
        "expected": {"cases": n_cases, "levels": int((rec.get("layer") or {}).get("n_levels") or 0),
                     "tier": tier},
        "cache": cpath["cube"],
    }
    return payload, 202


def _cube_job_key(state: WebState, tag: str, missile: str) -> str:
    return f"{id(state)}|{tag}|{missile}"


def _start_cube_job(state: WebState, *, tag: str, missile: str, rec: dict):
    """起一个（或复用）"扫这枚弹的立方体"的后台任务。

    ⚠ 复用很关键：用户连点两下按钮不该扫两遍（539 工况 ≈ 20 s）。
    """
    k = _cube_job_key(state, tag, missile)
    with _CUBE_LOCK:
        jid = _CUBE_JOBS.get(k)
        if jid:
            job = state.jobs.get(jid)
            if job is not None and job.state in ("queued", "running"):
                return job

        def work(_kind, job):
            return _run_cube_job(state, job, tag=tag, missile=missile, rec=rec)

        job = state.jobs.submit("scan", work)
        _CUBE_JOBS[k] = job.id
        return job


def _run_cube_job(state: WebState, job, *, tag: str, missile: str, rec: dict):
    """后台任务体：按**产物里那份工况与网格**扫单弹立方体（不重新编译想定）。"""
    from . import bg3d, fig3scan
    from .engine import default_jobs
    from .spec import Scene as _Scene

    grid = dict(rec.get("grid") or {})
    scene = _Scene.from_dict(dict(rec.get("scene") or {}))
    tier = str(rec.get("tier") or "fast")
    n_cases = int(grid.get("n_cases") or 0)
    job.total = n_cases
    job.message = f"正在扫描 {missile}：{n_cases} 工况（{tier}）"
    g3 = bg3d.Bg3Grid(beta=tuple(float(v) for v in grid["beta"]),
                      gamma=tuple(float(v) for v in grid["gamma"]),
                      dv=tuple(float(v) for v in grid["dv"]),
                      beta_step=float(grid.get("beta_step") or 0.0),
                      gamma_step=float(grid.get("gamma_step") or 0.0),
                      dv_step=float(grid.get("dv_step") or 0.0))
    entry = pool.resolve(missile)
    out = fig3scan.run_cube(scene, entry, grid=g3, tier=tier,
                            jobs=(state.config.get("jobs") or default_jobs()),
                            cache=True, layer=dict(rec.get("layer") or {}),
                            standard=rec.get("standard"),
                            result_dir=state.config.get("result_dir"),
                            log=job.log, progress=job.progress)
    job.message = (f"{missile} 扫完：{out['n_cases']} 工况 · 命中 {out['n_hit']} · "
                   f"{out['elapsed_s']:.1f} s")
    return {"figure": "fig3-cube", "missile": missile, "tag": tag,
            "cube": out["cube"], "cube_key": out["cube_key"],
            "n_hit": int(out["n_hit"]), "n_cases": int(out["n_cases"]),
            "elapsed_s": round(float(out["elapsed_s"]), 3),
            "cache_hit": False}


def fig3_payload(state: WebState, ref: str):
    """`GET /api/fig3/<tag_or_job_id>` 的数据层：产物 → 图3 查看器 JSON。

    返回 `(payload, http_status)`。`<id>` **两种含义**，按顺序判：

    1. **任务 id**（`state.jobs` 里有）：任务没跑完 ⇒ **409**；跑完了但那一单里没有图3 的产物
       ⇒ **404**（并说清是哪一种 —— 与 `/api/viewer3d/<id>` 同一套失败模式）；
    2. 否则当成**产物 tag**：`results/fig3_<tag>.json|csv`。tag 含非法字符 ⇒ **400**
       （不做宽容修正）；产物不在磁盘上 ⇒ **404**（附"怎么重出"的提示）。

    ⚠ 全程**只读产物、不解算**：数据来自 `results/fig3_*.json|csv`（`fig3.build()`）——
    一个 `solver.run()` 都没有，有测试钉住。
    """
    f4 = fig3_module()
    key = str(ref or "").strip() or "default"
    job = state.jobs.get(key)
    if job is not None:
        if job.state != "done":
            tail = f"：{job.error}" if job.error else "，稍后再试"
            return fail_payload([f"任务还没跑完（state={job.state}）{tail}"]), 409
        try:
            paths, part = f4.paths_of(job.result or {})
        except LookupError as exc:
            return fail_payload([str(exc)]), 404
        tag = part.get("tag") or key
    else:
        try:
            tag = f4.parse_tag(key)
        except ValueError as exc:
            return fail_payload([str(exc)]), 400
        paths = f4.default_paths(tag)
        part = {"tag": tag}
    try:
        payload = f4.build(paths, job=(job.id if job is not None else None),
                           tag=tag, extra={"missing_hint": f"--figure fig3 --tag {tag}"})
    except (FileNotFoundError, ValueError) as exc:
        return fail_payload([f"{exc}（重出：python -m missile_sim --figure fig3 --tag {tag}）"]), 404
    return payload, 200


def sandbox_paths(state: WebState, tag: str = "default") -> dict:
    """按 tag 找仓库里那套 `traj_<tag>_*` 产物路径。

    ⚠ 2026-10-03 起**没有任何路由再调它**：沙盒严格随输入，不再回放仓库旧产物
    （`sandbox_payload()` 只认任务 id）。留着是给 CLI / 判据复现某个 tag 用 —— 别当死代码删。
    """
    names = {"missile": f"traj_{tag}_missile.csv", "target": f"traj_{tag}_target.csv",
             "segments": f"traj_{tag}_segments.csv", "manifest": f"traj_{tag}.json"}
    out = {}
    for key, name in names.items():
        path = state.find_static(name)
        if path is None:
            raise FileNotFoundError(f"找不到图4 产物 {name!r}（先跑一次 `--figure traj --tag {tag}`）")
        out[key] = str(path)
    return out


def sandbox_payload(state: WebState, key: str, points_raw=None):
    """`GET /api/sandbox/<key>` 的数据层：产物 → 沙盒（回放）JSON。

    `key` **只能是任务 id**（口径与 `/api/viewer3d/<job_id>` 完全一致，连失败分支的说法都一样）。

    ⚠ 2026-10-03（用户口径 docs/UX-TARGET.md §2）：沙盒**严格随输入** —— 用户没给工况时
    不显示、不跑，**也不回放仓库里的旧产物**。所以这里**刻意没有**下面这两条后门：
    `key = default/空` ⇒ 读 `results/traj_default_*`；`?tag=<tag>` ⇒ 按 tag 回放。
    两条都删掉了（后门只要存在，早晚有人拿旧产物当"我这次的结果"看）。
    要看某个已落库 tag 就走 CLI（`python -m missile_sim --figure traj --tag <tag>`）。

    返回 `(payload, http_status)`：`points` 不合法 → 400（**不静默截断**）；
    `key` 为空 → 400；任务 id 不认识（含服务重启后任务表被清空）→ 404 + 明确提示；
    任务还在跑 / 跑挂 → **409**；任务里没有图4 的产物 → 404。

    ⚠ 全程**只读产物、不解算**：数据来自 `results/traj_<tag>_{missile,target,segments}.csv|json`
    （`traj3d.build_replay()`）—— 一个 `solver.run()` 都没有，有测试钉住。
    契约、事件表与"待接入"清单见 `docs/SANDBOX.md`。
    """
    t3 = traj3d_module()
    try:
        points = t3.parse_points(points_raw)
    except ValueError as exc:
        return fail_payload([str(exc)]), 400
    key = str(key or "").strip()
    job = None
    part = {}
    if not key or key == "default":
        return fail_payload([
            "沙盒只显示你自己提交的那一次工况：请先在首页填好输入并提交"
            "（或用 `/fig4?job=<任务 id>` 打开某次任务）。"
            "旧产物不再在这里回放 —— 要看某个 tag 请走命令行。"]), 400
    else:
        job = state.jobs.get(key)
        if job is None:
            return fail_payload([
                f"该任务已不存在：{key!r} —— 请重新提交。"
                "（服务重启后任务表会清空，网址里的旧 ?job= 也会失效。）"]), 404
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
                "所以没有可回放的数据。把「只出 3D 预览」清空（正式跑一次图4）后就有。"]), 404
    try:
        payload = t3.build_replay(paths, points=points, job=job.id,
                                  tag=(part.get("tag") or job.id))
    except FileNotFoundError as exc:
        return fail_payload([str(exc)]), 404
    return payload, 200


def submit_job(form: dict, state: WebState):
    """提交后台任务，返回 `(payload, http_status)`。

    `figure` 决定用哪套参数解析（四套的参数名不同），**分流与 CLI 的 `--figure` 一一对应**：
    `plane`（默认）⇒ 图1；`bg` ⇒ 图2；`traj` ⇒ 图4；`both` ⇒ 图1+图2；`all` ⇒ 三张图。
    `both` / `all` 把多张图跑在**同一个**后台任务里（`run_all_job`），摘要用 `parts` 分列。

    ⚠ 这里曾经有个"藏起来的坑"（D10）：`both` 落在 `figure in ("bg", "both")` 那个分支里，
    **只跑图2却把响应标成 both**，而 CLI 的 `--figure both` 是图1+图2 —— 两边静默不一致，
    且 `FIGURE_FIELD.options` 里没有 `both`，只能手工 POST 触达。现在 `both` 与 CLI 对齐，
    并出现在下拉里（"看得见的选项"才配叫选项）。

    `kind=scan` 跑扫描，`kind=plot` 只出图 —— 这两档**只对图1/图2 有意义**（图4 没有平面可扫，
    两个 `kind` 等价）；`kind` 仍然照原样传给 `JobStore`，图1/图2 的语义一个字没动。
    """
    form = dict(form or {})
    kind = str(form.get("kind") or "scan").strip().lower()
    if kind not in ("scan", "plot"):
        return fail_payload([f"kind 只能是 scan / plot，收到 {kind!r}"]), 400
    figure = str(form.get("figure") or "plane").strip().lower()
    if figure not in ("plane", "bg", "traj", "fig3", "both", "all", "four"):
        return fail_payload([f"figure 只能是 plane / bg / traj / fig3 / both / all / four，"
                                       f"收到 {figure!r}"]), 400

    if figure == "fig3":
        req, _scene, errors = form_to_fig3_request(form, state.config)
        if errors:
            return fail_payload(errors), 400

        def work_fig3(_kind, job):
            return run_fig3_job(req, job)

        job = state.jobs.submit(kind, work_fig3)
        return {"ok": True, "id": job.id, "kind": kind, "figure": "fig3",
                "poll": f"/progress/{job.id}", "tag": req.tag,
                "viewer_url": f"/fig3?tag={req.tag}"}, 200

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

    if figure == "four":
        # **一次提交出四块**（用户口径 docs/UX-TARGET.md §4-C）。四块共用这一份 form：
        # 各自只是把同一份输入翻译成自己那套请求，没有任何一块另起一份输入。
        p_req, _s1, p_err = form_to_request(form, state.config, with_iso=True)
        b_req, _s2, b_err = form_to_bg_request(form, state.config, with_scan=True)
        f_req, _s3, f_err = form_to_fig3_request(form, state.config)
        t_req, _s4, t_err = form_to_traj_request(form, state.config)
        errors = _dedupe(list(p_err) + list(b_err) + list(f_err) + list(t_err))
        if errors:
            return fail_payload(errors), 400
        reqs = {"plane": p_req, "bg": b_req, "fig3": f_req, "traj": t_req}

        def work_four(_kind, job):
            return run_four_job(reqs, job)

        job = state.jobs.submit("scan", work_four)
        return {"ok": True, "id": job.id, "kind": "scan", "figure": "four",
                "poll": f"/progress/{job.id}", "with_iso": True, "tag": p_req.tag,
                "blocks": list(BLOCK_ORDER),
                "block_titles": {n: BLOCK_TITLES[n] for n in BLOCK_ORDER}}, 200

    if figure in ("both", "all"):
        # 与 CLI 一致：both = 图1+图2，all = 图1+图2+图4。各张图分别解析；任一张的输入不合法
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
#: 空战沙盒的**整页**：同样没有服务端占位符（job id / 点数 / 时刻都从 `location.search` 读），
#: 由 `GET /fig4` 这条独立路由发字节 —— 也不进白名单。
SANDBOX_PAGE = "sandbox.html"
#: 图3 的**整页**：与查看器同形态（没有服务端占位符，`?tag=` / `?job=` 从 `location.search` 读），
#: 由 `GET /fig3` 这条独立路由发字节，同样**不进** `WEB_STATIC_ASSETS`。
FIG3_PAGE = "fig3.html"
# 只有这些名字能被 `GET /static/<name>` 直接吐出去。`index.html` **故意不在里面** ——
# 它带着没渲染的占位符，原始字节发出去会露出 `__DEFAULTS__`。
WEB_STATIC_ASSETS = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "viewer3d.css": "text/css; charset=utf-8",
    "viewer3d.js": "application/javascript; charset=utf-8",
    "sandbox.css": "text/css; charset=utf-8",
    "sandbox.js": "application/javascript; charset=utf-8",
    "fig3.css": "text/css; charset=utf-8",
    "fig3.js": "application/javascript; charset=utf-8",
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
    """一个输入行：**单位写在标签里**（`发射高度（米）`），控件嵌在标签内，行间一条细线。

    `hint` 挪进 `title`（悬停可见）—— 左栏要的是"标签 + 值"两行密排，每个字段再挂一段说明
    会把输入项挤散；口径性说明留在各分区的 `rail-note` 里。

    控件**嵌在 `<label>` 里**（隐式关联）而不是 `id` + `for`：三十多个字段各少一对属性，
    首页"渲染后 < 20 KB"那条判据就是靠这类零碎守住的（`data-field` 仍是唯一的取值口径，
    `markFieldErrors()` 往 `parentNode` 里塞红字提示照旧可用）。
    """
    text = "" if value is None else str(value)
    name = _esc(f.name)
    if f.kind == "select":
        opts = []
        for opt in (f.options or ()):
            selected = " selected" if str(opt) == text else ""
            opts.append(f'<option value="{_esc(str(opt))}"{selected}>{_esc(str(opt))}</option>')
        control = f'<select data-field="{name}">{"".join(opts)}</select>'
    else:
        control = (f'<input data-field="{name}" type="text" value="{_esc(text)}"'
                   ' autocomplete="off" spellcheck="false" inputmode="decimal">')
    tip = f' title="{_esc(f.hint)}"' if f.hint else ""
    return (f'<div class="field-row"{tip}><label>{_esc(f.label)}{_esc(unit_suffix(f.unit))}'
            f'{control}</label></div>')


def _json_in_script(obj) -> str:
    """塞进 `<script>` 的 JSON：`</` 必须转义，否则会提前闭合 script 标签。"""
    return json.dumps(jsonable(obj), ensure_ascii=False).replace("</", "<\\/")


def render_page(state: WebState) -> str:
    """渲染首页。

    ⚠ 首页**一个页面承载四张图的输入**（图1/图2/图4 的分区 + 图3 的 `<details>`），所以左栏
    是"共用骨架（弹种 → 环境预设 chip → 发射端 → 目标端 → 绘图）+ 各图专属折叠块"；
    图3 自己的整页在 `/fig3`（另一条路由），查看器在 `/viewer3d`。
    占位符口径不变：模板里只放 `__X__`，渲染完还剩就是页面静默残缺，宁可 500。
    """
    cfg = state.config
    defaults = defaults_form(cfg)
    env_payload = env_presets_payload(defaults)
    env_items = [(name, chip_text(item["label"], name), "env-preset")
                 for name, item in env_payload.items() if not str(name).startswith("_")]
    preset_payload = presets_payload(defaults)
    preset_items = [(name, chip_text(item["summary"], name), "preset")
                    for name, item in preset_payload.items()]
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
        "__ENVCHIPS__": chips_html(env_items),
        "__ENVSELECT__": hidden_select("env_preset", env_items,
                                       value=defaults.get("env_preset")),
        "__PRESETCHIPS__": chips_html(preset_items)
                           or '<span class="rail-note">（这份 targets.py 没有预置想定）</span>',
        "__PRESETSELECT__": hidden_select("preset", preset_items, blank="（手动填）",
                                          value=defaults.get("preset")),
        "__BASEROWS__": group_rows(BASE_GROUP, defaults),
        "__LAUNCHROWS__": group_rows(LAUNCH_GROUP, defaults),
        "__TARGETROWS__": group_rows(TARGET_GROUP, defaults),
        "__VIEWROWS__": group_rows(VIEW_GROUP, defaults),
        "__BGROWS__": "".join(_field_html(f, defaults.get(f.name)) for f in BG_FIELDS),
        "__TRAJROWS__": "".join(_field_html(f, defaults.get(f.name)) for f in TRAJ_FIELDS),
        "__FIG3ROWS__": "".join(_field_html(f, defaults.get(f.name)) for f in FIG3_FIELDS),
        "__DEFAULTS__": _json_in_script(defaults),
        "__ENVPRESETS__": _json_in_script(env_payload),
        "__PRESETS__": _json_in_script(preset_payload),
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

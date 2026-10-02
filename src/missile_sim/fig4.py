# -*- coding: utf-8 -*-
"""图4 的**数据层**：读落盘产物 → 折成前端 WebGL 要吃的 JSON。

用户 2026-10-02 的口径（**本模块的形态由它决定**）："**命中点不用，只出各弹三参数点即可**"。
所以图4 的数据源是 **11 枚弹各自的标称三参数点**，不是扫出来的格点云：

| 量 | 权威口径（与图1/图2/图3 同一套，别另算） |
| --- | --- |
| ΔV | `pool.metrics_of(entry).dv` |
| BC ≡ β | `bg.point_of(entry).beta`（与 `metrics_of().bc` 实测逐位一致，差 ≤ 9.1e-13） |
| γ | `bg.point_of(entry).gamma`（`mapping.BlkMetrics` **没有** gamma，只有 `bg.BgPoint` 有） |

* 颜色 = 该弹在**当前工况**下的 `t_hit`；命中 ⇒ 实心 + 有 t_hit，未命中 ⇒ 空心 + 没有 t_hit。
* 色标范围只在这 **11 个命中值**上共享（原来是"11 弹 × 539 点"共享）。
* **默认产物里没有立方体**：`results/fig4_<tag>.json` 只有 11 个标称点；既没有格点云，也没有
  `R_ref` / `n_star` / `induced_dominated` 这些"只对格点有意义"的判别量，也没有逐列拟合。

## 等时面：按需算单弹立方体（默认不出面）

`GET /api/fig4/<id>/layers?missile=<key>` 的**对外契约不变**（13 层一次给全、滑块零请求），
但数据来源是"**按需算那枚弹的立方体**"：

1. 先查磁盘缓存 `results/fig4_cube_<key>_<sha8>.json`；
2. 不在 ⇒ 由路由层起**后台任务**（202 + `/progress/<id>`），算完写缓存 ⇒ 第二次秒开。

⚠ **缓存指纹必须覆盖四样**（少一样都会让旧立方体"撒谎"，而画面上看不出来）：
**① 工况（scene，含 `maneuvers`）② 档位（standard/fast）③ 扫描网格参数（β/γ 点数、ΔV 区间与点数）
④ 弹名**（外加求解器身份 `solver.sha256`，换内核时自动失效）。
`cube_key()` 是唯一入口，`read_cube()` 会**用文件里存的那份字段重算一遍**再比对 ——
指纹算法以后改了也不会误读旧文件。

⚠ **标称点脱靶 ≠ 这枚弹没有等时面**：标称点只是立方体里的一个格点，高 ΔV 那一侧仍可能有命中
（S0 实测 ΔV ≥ 1100 全命中）。所以"生成等时面"按钮**一律可用**，扫完如果 0 层可出面才提示降级。

## 其它

* 配色**一律从 `figures` 现取**（前端零颜色字面量）；
* 只读产物、**不 import 求解器与 workflow**（"不解算"由 `tests/test_fig4_web.py` 打桩钉住）；
* 出口再兜一次严格 JSON（裸 `NaN` 会让 `JSON.parse` 抛错、页面白屏）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from . import figures
from .spec import RESULT_DIR

#: 产物 schema（`results/fig4_<tag>.json` 的 `schema`）。改记录语义时 +1。
#: v3：数据源从"格点云"换成"**11 枚弹的标称三参数点**"（用户："命中点不用，只出各弹三参数点即可"）；
#: 立方体只作为**按需扫描**的缓存存在（`fig4_cube_*.json`），默认产物里不再有格点数组。
SCHEMA = 3
#: 单弹立方体缓存的 schema（与产品 schema 分开演进）。
CUBE_SCHEMA = 1

DEFAULT_TAG = "default"
#: 默认 ΔV 钉值 = PL-12 的权威 ΔV（`results/bg_default.json` → `scan.dv_pin_ms`）。
DV_PIN_MS = 932.5697
#: **按需立方体扫描**的网格（默认产物里没有立方体，这组数只决定"扫描时扫多大"）：
#: ΔV 绝对区间 + 点数（S0 探测的实测依据见 `docs/FIG4.md`）；β、γ 各 7 点 = 图2 的自适应域。
DV_LIM = (700.0, 1700.0)
N_DV = 11
N_BETA = 7
N_GAMMA = 7

#: 滑动条的档数（用户口径 12~16，取 13）：从 `grid.iso_levels(cube, iso_step)` 里**等距挑**、
#: 端点保留 ⇒ 档位仍然全是"整数秒"，与图1/图2 的等时线**同一套层定义**。
LAYER_COUNT = 13
#: 「这一层出不出得了面」的门槛（跨过的格子数 / 最少三角形），与 `bg3d` 的默认一致。
LAYER_MIN_CELLS = 4
LAYER_MIN_TRI = 4
#: 等时面顶点坐标在响应里保留几位（4 位 ⇒ 0.1 kg/m² / 0.1 m/s，远小于网格步长）。
LAYER_DIGITS = 4

#: 产物名后缀（`--tag`）只认这套字符：它会进文件名，宽容修正等于给路径穿越开后门。
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
#: 查看器要读的产物（缺一个就报错，不回落）。
REQUIRED_PRODUCTS = ("record", "cases")

#: 展平顺序（**唯一口径**，只有按需立方体还在用）。前端与测试都读这一条，别各自写一遍。
FLAT_ORDER = "ΔV 外层 → γ → β（与 grid.cells() 同序）"

#: 颜色模式的键（与 `figures.FIG4_MODES` 的 `id` 必须一致）。v4 只剩 `t_hit` 一种。
COLOR_MODES = tuple(m["id"] for m in figures.FIG4_MODES)


# --------------------------------------------------------------------- 参数 / 名字


def parse_tag(raw) -> str:
    """`?tag=` / `--tag` → 产物名后缀。非法值直接 `ValueError`（**不静默改成 default**）。"""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_TAG
    text = str(raw).strip()
    if not TAG_RE.fullmatch(text):
        raise ValueError(f"tag 只认 [A-Za-z0-9][A-Za-z0-9._-]{{0,39}}，收到 {raw!r}")
    return text


def default_paths(tag: str = DEFAULT_TAG) -> dict:
    """`default` 这套产物的路径（仓库自带、已入库的那一份）。"""
    t = parse_tag(tag)
    return {"record": str(RESULT_DIR / f"fig4_{t}.json"),
            "cases": str(RESULT_DIR / f"fig4_{t}_cases.csv")}


def paths_of(summary: dict):
    """任务摘要 → 图4 那一段的产物路径。

    `figure=fig4` 的摘要就是它自己；合并摘要（`parts`）里靠**显式 `figure` 键**认领，
    不靠位置猜。找不到就 `LookupError`（路由层折成 404，**不**回落到别的东西）。
    """
    if not isinstance(summary, dict):
        raise LookupError("任务还没有结果")
    if summary.get("figure") == "fig4":
        return dict(summary.get("paths") or {}), summary
    for part in summary.get("parts") or ():
        if isinstance(part, dict) and part.get("figure") == "fig4":
            return dict(part.get("paths") or {}), part
    raise LookupError("这个任务里没有图4 的产物（`figure` 不是 fig4，合并摘要里也没有 fig4 那一段）")


# --------------------------------------------------------------------- 网格 / 展平


def grid_shape(n_beta: int = N_BETA, n_gamma: int = N_GAMMA, n_dv: int = N_DV) -> tuple:
    """立方体形状 `(n_dv, n_gamma, n_beta)` —— 与 `bg3d.Bg3Grid.shape` 同口径。"""
    return (int(n_dv), int(n_gamma), int(n_beta))


def column_index(flat_index: int, n_beta: int = N_BETA, n_gamma: int = N_GAMMA) -> int:
    """展平下标 → 该点所属的 (β,γ) 列下标（0 ~ n_beta·n_gamma−1，γ 外层、β 内层）。

    ΔV 是**最外层**，所以同一根竖线上的点在展平序列里等距 `n_beta·n_gamma` 出现一次 ⇒
    取模就够。这条关系如果错了，"逐列"的统计会整块错位，**而图上只是颜色难看**。
    """
    span = int(n_beta) * int(n_gamma)
    if span <= 0:
        raise ValueError("n_beta / n_gamma 必须为正")
    i = int(flat_index)
    if i < 0:
        raise ValueError(f"展平下标不能为负：{flat_index!r}")
    return i % span


def column_cells(beta, gamma) -> list:
    """单层的 (β, γ) 格点顺序：**γ 外层、β 内层**（与 `bg3d.Bg3Grid.plane_cells()` 同序）。"""
    return [(float(b), float(g)) for g in gamma for b in beta]


def flat_cells(beta, gamma, dv) -> list:
    """全部格点，**ΔV 最外层**（与 `bg3d.Bg3Grid.cells()` 同序）。"""
    return [(float(d), float(b), float(g)) for d in dv for g in gamma for b in beta]


def grid_contract(grid: dict) -> dict:
    """产物里的 `grid` 块 → 按需扫描要的那几个数（缺一不可，缺了就报错）。"""
    beta = [float(v) for v in (grid.get("beta") or ())]
    gamma = [float(v) for v in (grid.get("gamma") or ())]
    dv = [float(v) for v in (grid.get("dv") or ())]
    if min(len(beta), len(gamma), len(dv)) < 2:
        raise ValueError("产物里的扫描网格不完整（每根轴至少要 2 个点）")
    return {"beta": beta, "gamma": gamma, "dv": dv,
            "beta_step": _num(grid.get("beta_step"), 0.0) or 0.0,
            "gamma_step": _num(grid.get("gamma_step"), 0.0) or 0.0,
            "dv_step": _num(grid.get("dv_step"), 0.0) or 0.0,
            "shape": [len(dv), len(gamma), len(beta)],
            "n_cases": int(len(dv) * len(gamma) * len(beta))}


# --------------------------------------------------------------------- 单弹立方体缓存


class CubeMissing(Exception):
    """那枚弹的立方体还没算过 ⇒ 路由层去起后台任务（202），不是一个错误。"""

    def __init__(self, missile: str, cube_key: str = "", *, n_cases: int = 0, tier: str = ""):
        self.missile = str(missile)
        self.cube_key = str(cube_key)
        self.n_cases = int(n_cases or 0)
        self.tier = str(tier or "")
        super().__init__(f"{self.missile} 的立方体还没算过（{self.n_cases} 工况）")


def _canon_scene(scene: dict) -> dict:
    """Scene → 只含"进求解器"的那些键（含 `maneuvers`），全部规范化成可比形态。"""
    sc = dict(scene or {})
    man = [[float(t), [float(x) for x in acc]] for t, acc in (sc.get("maneuvers") or ())]
    wind = [float(v) for v in (sc.get("wind_m_s") or (0.0, 0.0, 0.0))]
    return {
        "range_m": float(sc.get("range_m") or 0.0), "alt_m": float(sc.get("alt_m") or 0.0),
        "target_alt_m": (None if sc.get("target_alt_m") is None
                         else float(sc.get("target_alt_m"))),
        "target_bearing_deg": float(sc.get("target_bearing_deg") or 0.0),
        "vm0": float(sc.get("vm0") or 0.0),
        "launch_heading_deg": float(sc.get("launch_heading_deg") or 0.0),
        "launch_pitch_deg": float(sc.get("launch_pitch_deg") or 0.0),
        "target_speed_ms": float(sc.get("target_speed_ms") or 0.0),
        "target_heading_deg": float(sc.get("target_heading_deg") or 0.0),
        "target_pitch_deg": float(sc.get("target_pitch_deg") or 0.0),
        "duration_s": float(sc.get("duration_s") or 0.0), "dt_s": float(sc.get("dt_s") or 0.0),
        "observation": str(sc.get("observation") or ""),
        "wind_m_s": [round(v, 6) for v in wind],
        "ground_height_m": float(sc.get("ground_height_m") or 0.0),
        "proximity_fuse": bool(sc.get("proximity_fuse", True)),
        "hit_radius_m": float(sc.get("hit_radius_m") or 0.0),
        "maneuvers": [[round(t, 6), [round(x, 6) for x in acc]] for t, acc in man],
    }


def cube_key(scene: dict, tier: str, grid: dict, missile: str,
             solver_sha: str = "") -> str:
    """立方体指纹的**唯一**入口：sha256(canonical({scene, tier, grid, missile, solver}))[:8]。

    ⚠ 这四样（+ 求解器身份）缺一样，旧立方体就会被当成新的复用 —— 形状、数值、甚至
    "面上那个 t 值"都会撒谎，而**画面上看不出来**。格点值先 round 到 6 位再进哈希，
    免得浮点抖动算出两个缓存。

    `solver_sha` **由调用方给**（产物里就有 `solver.sha256`）—— 数据层不许 import 求解器，
    否则"这个接口不解算"那条判据（打桩 `solver.run`）就没法说清了。
    """
    g = grid_contract(grid)
    payload = {
        "scene": _canon_scene(scene),
        "tier": str(tier or ""),
        "grid": {"beta": [round(v, 6) for v in g["beta"]],
                 "gamma": [round(v, 6) for v in g["gamma"]],
                 "dv": [round(v, 6) for v in g["dv"]]},
        "missile": str(missile or ""),
        "solver": str(solver_sha or ""),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def cube_path(missile: str, *, scene: dict, tier: str, grid: dict, result_dir=None,
              solver_sha: str = "") -> dict:
    """那枚弹的立方体缓存路径（+ 指纹）。"""
    key = cube_key(scene, tier, grid, missile, solver_sha)
    root = Path(result_dir) if result_dir is not None else RESULT_DIR
    return {"cube": str(root / f"fig4_cube_{missile}_{key}.json"), "cube_key": key}


def read_cube(path, *, missile: str, scene: dict, tier: str, grid: dict,
              solver_sha: str = "") -> dict:
    """读立方体缓存并**验证指纹**（对不上就当没有 —— 宁可重算，不许撒谎）。"""
    want = cube_key(scene, tier, grid, missile, solver_sha)
    blob = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(blob, dict) or blob.get("kind") != "fig4-cube":
        raise ValueError(f"{path} 不是图4 的立方体缓存")
    if int(blob.get("schema", -1)) != CUBE_SCHEMA:
        raise ValueError(f"{path} 的 schema={blob.get('schema')!r}，本模块只认 {CUBE_SCHEMA}")
    got = str(blob.get("cube_key") or "")
    # ① 先按**文件里存的那份字段**重算（防"指纹算法改了、旧文件被误认"），② 再与本次比
    remake = cube_key(blob.get("scene") or {}, str(blob.get("tier") or ""),
                      blob.get("grid") or {}, str(blob.get("missile") or ""),
                      str((blob.get("solver") or {}).get("sha256") or ""))
    if remake != got or got != want:
        raise ValueError(f"{path} 的指纹对不上（文件 {got} / 重算 {remake} / 本次 {want}）"
                         " —— 工况或网格变了，重算")
    return blob


def write_cube(path, blob: dict) -> str:
    """写立方体缓存（`record.write_json` 同款：CRLF，产物目录里一贯如此）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(blob, ensure_ascii=False, indent=1, allow_nan=False),
                 encoding="utf-8", newline="\r\n")
    return str(p)


# --------------------------------------------------------------------- 配色 / 图例


def palette() -> dict:
    """图4 的全部配色：**源头就是 `figures`**（前端不写死任何一个）。"""
    return {
        "hit": figures.FIG4_HIT_COLOR,
        "miss": figures.FIG4_MISS_COLOR,
        "bg": figures.FIG4_BG_COLOR,
        "text": figures.FIG4_TEXT_COLOR,
        "muted": figures.FIG4_MUTED_COLOR,
        "box": figures.FIG4_BOX_COLOR,
        "axis": dict(figures.FIG4_AXIS_COLORS),
        "cmap": {"t_hit": list(figures.FIG4_CMAP_T_HIT)},
        "layer_alpha": float(figures.FIG4_LAYER_ALPHA),
        "source": ("figures.FIG4_CMAP_T_HIT / FIG4_MISS_COLOR / FIG4_HIT_COLOR / "
                   "FIG4_AXIS_COLORS / FIG4_BG_COLOR / FIG4_TEXT_COLOR / FIG4_MUTED_COLOR / "
                   "FIG4_BOX_COLOR / FIG4_LAYER_ALPHA"),
    }


def legend() -> dict:
    return {"hit": figures.FIG4_LEGEND_HIT, "miss": figures.FIG4_LEGEND_MISS,
            "label": "弹名常显（11 枚都要看得见）"}


def modes() -> list:
    return [dict(m) for m in figures.FIG4_MODES]


def hex_to_rgb(text: str) -> list:
    """`#rrggbb` → 0~1 三元组（自检用；浏览器里那份在 `fig4.js`）。"""
    s = str(text).strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"只认 #rrggbb 颜色，收到 {text!r}")
    return [int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


# --------------------------------------------------------------------- 读产物


def read_csv_rows(path) -> list:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_record(path) -> dict:
    """读 `results/fig4_<tag>.json`；顶层不是对象就报错（宁可炸，不静默给空图）。"""
    blob = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(blob, dict):
        raise ValueError(f"{path} 的顶层必须是对象")
    return blob


def _num(v, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _round(v, digits):
    """`None` / 非有限 ⇒ `None`；其余按位取整。

    ⚠ **非有限必须折成 `None`**：`json.dumps` 会写出裸 `NaN`（Python 读得回来，JS 的
    `JSON.parse` 直接抛错 → 页面白屏）。`round(nan, 4)` 仍然是 `nan`，所以这条不能在
    `round` 之后补 —— 必须在前面拦。
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, digits) if math.isfinite(f) else None


def _finite(vals):
    return [float(v) for v in vals if v is not None and math.isfinite(float(v))]


def _clean(obj):
    """递归把非有限浮点折成 `None`（**响应必须是严格 JSON**：裸 `NaN` 会让前端白屏）。"""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (np.floating, np.integer)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


# --------------------------------------------------------------------- 折成前端 JSON


def build(paths: dict, *, job: str | None = None, tag: str | None = None,
          extra: dict | None = None) -> dict:
    """产物路径 → 图4 页面要吃的 JSON（**11 个标称点 + 层契约**，没有格点云）。

    全程只**读**盘：一个求解器调用都没有（`solver.run` 零调用由测试钉住）。
    """
    missing = [k for k in REQUIRED_PRODUCTS if not (paths or {}).get(k)]
    if missing:
        raise FileNotFoundError(f"图4 产物不齐，缺 {missing}（产物被清理过？`--figure fig4` 可重出）")
    for key in REQUIRED_PRODUCTS:
        if not Path(str(paths[key])).is_file():
            raise FileNotFoundError(f"图4 产物不在磁盘上：{key} = {paths[key]}")
    rec = read_record(paths["record"])
    if str(rec.get("figure") or "") != "fig4":
        raise ValueError(f"这不是图4 的产物：figure = {rec.get('figure')!r}")
    if int(rec.get("schema", -1)) != SCHEMA:
        raise ValueError(f"图4 产物 schema={rec.get('schema')!r}，本模块只认 {SCHEMA}（重出产物）")

    grid = grid_contract(rec.get("grid") or {})
    layer = dict(rec.get("layer") or {})
    colors = palette()
    points, keys = [], []
    for m in rec.get("missiles") or ():
        key = str(m.get("key") or "")
        if not key or key in keys:
            raise ValueError(f"产物里的弹池记录不合法（key = {key!r}）")
        keys.append(key)
        t_hit = _round(_num(m.get("t_hit_s")), 4)
        hit = bool(m.get("hit")) and t_hit is not None
        points.append({
            "key": key, "label": str(m.get("label") or key),
            "native": str(m.get("native") or ""), "full_name": str(m.get("full_name") or ""),
            # 标称三参数（**权威口径**，见模块 docstring）
            "dv": _round(_num(m.get("dv")), 3), "beta": _round(_num(m.get("beta")), 3),
            "gamma": _round(_num(m.get("gamma")), 3),
            "scaling": {k: _round(_num((m.get("scaling") or {}).get(k)), 6)
                        for k in ("thrust_scale", "cx_scale", "cxaoa_scale")},
            # 结局：命中 ⇒ 有 t_hit（实心 + 着色）；未命中 ⇒ None（空心）
            "hit": hit, "t_hit_s": (t_hit if hit else None),
            "event": str(m.get("event") or ""), "t_end_s": _round(_num(m.get("t_end_s")), 4),
            "min_separation_m": _round(_num(m.get("min_separation_m")), 2),
            "fuse_radius_m": _round(_num(m.get("fuse_radius_m")), 2),
            "max_alt_m": _round(_num(m.get("max_alt_m")), 2),
            "v_impact_ms": _round(_num(m.get("v_impact_ms")), 2),
            "dv_measured_ms": _round(_num(m.get("dv_measured_ms")), 2),
            "t_burnout_s": _round(_num(m.get("t_burnout_s")), 4),
            "backend": str(m.get("backend") or ""), "cache_hit": bool(m.get("cache_hit")),
        })
    if not points:
        raise ValueError("产物里一枚弹都没有")

    t_hits = [p["t_hit_s"] for p in points if p["t_hit_s"] is not None]
    ranges = {"t_hit": ([_round(min(t_hits), 4), _round(max(t_hits), 4)] if t_hits else None)}
    n_hit = sum(1 for p in points if p["hit"])
    scene = dict(rec.get("scene") or {})
    scene = {"t_react_s": _round(_num(rec.get("t_react_s")), 3),
             "t_react_note": str(rec.get("t_react_note") or ""),
             "text": str(rec.get("scene_text") or _scene_text(rec))} | scene
    payload = {
        "ok": True, "figure": "fig4", "kind": figures.FIG4_KIND, "schema": SCHEMA,
        "job": job, "tag": tag or rec.get("tag"),
        "title": figures.FIG4_TITLE,
        "subtitle": _subtitle(rec, points),
        "standard": rec.get("standard"), "tier": rec.get("tier"),
        "backend": rec.get("backend"), "solver": dict(rec.get("solver") or {}),
        "scene": scene,
        "axes": _axes(grid, colors),
        "grid": {"beta": grid["beta"], "gamma": grid["gamma"], "dv": grid["dv"],
                 "shape": grid["shape"], "n_cases": grid["n_cases"],
                 "beta_step": _round(grid["beta_step"], 4),
                 "gamma_step": _round(grid["gamma_step"], 4),
                 "dv_step": _round(grid["dv_step"], 5),
                 "dv_pin_ms": _round(_num((rec.get("grid") or {}).get("dv_pin_ms")), 4),
                 "dv_lim": [_num(v) for v in ((rec.get("grid") or {}).get("dv_lim") or ())],
                 "flat_order": FLAT_ORDER, "column_span": len(grid["beta"]) * len(grid["gamma"]),
                 "role": "按需扫描单弹立方体时用的网格（默认产物里没有立方体）"},
        "points": points,
        "shared": {"n_points": len(points), "n_hit": n_hit, "n_miss": len(points) - n_hit,
                   "ranges": ranges,
                   "note": "色标范围只在这 11 枚弹的命中值上共享（切换弹种不跳色标）"},
        "layers": layer_contract(grid, layer),
        "degrade": {"note": ("该弹在该工况下没有可出面的层时照样明说（绝不拿 lifetime 冒充 "
                             "t_hit）。注意：标称点脱靶不等于这枚弹没有等时面 —— 它的立方体里"
                             "高 ΔV 那一侧仍可能有命中，所以按钮一律可用，扫完才知道。")},
        "colors": colors, "legend": legend(), "modes": modes(),
        "markers": {"hit": "dot", "miss": "hollow",
                    "note": "命中/脱靶**不靠颜色区分**：脱靶一律空心标记（且没有 t_hit 可着色）"},
        "labels": {"always": True, "names": keys,
                   "note": "11 个弹名常显（不靠悬停）；避让只做最小上下错开"},
        "footnotes": list(figures.FIG4_FOOTNOTES),
        "axis_note": ("三根轴已各自归一化到等长（刻度与标签是真值）；"
                      "数据源 = 每枚弹的标称三参数点"),
        "extra": dict(extra or {}),
    }
    # 出口再兜一次：响应必须是**严格 JSON**（裸 `NaN` 会让 `JSON.parse` 直接抛错，页面白屏）。
    return _clean(payload)


def _axes(grid: dict, colors) -> list:
    labels = figures.FIG4_AXIS_LABELS
    out = []
    for axis_id, vals, unit in (("beta", grid["beta"], "kg/m²"),
                                ("dv", grid["dv"], "m/s"),
                                ("gamma", grid["gamma"], "kg/m²")):
        out.append({"id": axis_id, "label": labels.get(axis_id, axis_id), "unit": unit,
                    "limits": [float(vals[0]), float(vals[-1])],
                    "values": [float(v) for v in vals],
                    "ticks": [float(v) for v in vals],
                    "color": colors["axis"].get(axis_id, colors["text"])})
    return out


def _subtitle(rec: dict, points: list) -> str:
    scene = dict(rec.get("scene") or {})
    n_hit = sum(1 for p in points if p["hit"])
    parts = [f"弹池 {len(points)} 枚（每枚一个标称三参数点）",
             f"命中 {n_hit} / 未命中 {len(points) - n_hit}",
             f"39 @ {_num(rec.get('t_react_s'), 0):g} s（固定）",
             f"{_num(scene.get('range_m'), 0) / 1000:g} km 迎头",
             f"档位 {rec.get('tier')}（{rec.get('backend')}）"]
    return " · ".join(p for p in parts if p)


def _scene_text(rec: dict) -> str:
    """一行工况说明（产物里没写 `scene_text` 时的兜底），**必须带"39 固定"那句**。"""
    sc = dict(rec.get("scene") or {})
    t_react = _num(rec.get("t_react_s"))
    head = "工况：crank→39"
    if t_react is not None:
        head += f" · 39 @ {t_react:g} s（固定，共用工况）"
    bits = [head]
    if sc:
        bits.append(f"{_num(sc.get('range_m'), 0) / 1000:g} km 迎头")
        bits.append(f"{_num(sc.get('alt_m'), 0) / 1000:g} km 同高")
        bits.append(f"载机 {_num(sc.get('vm0'), 0):g} m/s 航向 "
                    f"{_num(sc.get('launch_heading_deg'), 0):g}°")
        bits.append(f"目标 {_num(sc.get('target_speed_ms'), 0):g} m/s 航向 "
                    f"{_num(sc.get('target_heading_deg'), 0):g}°")
    return " · ".join(bits)


# ===================================================================== 等时面（单层）


def layer_contract(grid: dict, layer: dict) -> dict:
    """前端要的**层契约**：多少档、步长、门槛、接口地址、各档的 t 值与标签。"""
    levels = list(layer.get("levels") or ())
    return {
        "n_levels": int(layer.get("n_levels") or LAYER_COUNT),
        "iso_step": _round(_num(layer.get("iso_step"), 1.0), 4),
        "min_cells": int(layer.get("min_cells") or LAYER_MIN_CELLS),
        "min_tri": int(layer.get("min_tri") or LAYER_MIN_TRI),
        "levels": [_round(v, 4) for v in levels],
        "labels": [figures.iso_label(v) for v in levels],
        "endpoint": "/api/fig4/<id>/layers?missile=",
        "source": "grid.iso_levels(cube, step) → bg3d.iso_surfaces(cube, grid, levels)",
        "cube": {"cases": int(grid.get("n_cases") or 0),
                 "cache": "results/fig4_cube_<弹名>_<指纹8位>.json（按需扫描，第二次秒开）"},
        "note": ("层定义与图1/图2 的等时线**同一套**（`grid.iso_levels`，整秒）；"
                 "一次下发全部层，拖动滑块不再回服务器。"),
    }


def layer_levels(values, *, step: float = 1.0, count: int = LAYER_COUNT) -> list:
    """立方体 → 滑动条要的 **N 档** t 值。

    ⚠ 档位**不是**自己另算一套：先取 `grid.iso_levels(cube, step)`（图1/图2 用的同一个
    函数，整秒层级），再从里面**等距挑 `count` 个、端点保留**。所以每个档位仍然是一个
    整秒等时面，只是不把 40 多档全塞进滑动条。
    """
    from . import grid as grid_mod

    levels = [float(v) for v in grid_mod.iso_levels(values, float(step))]
    n = int(count)
    if n < 2 or len(levels) <= n:
        return levels
    idx = [round(i * (len(levels) - 1) / (n - 1)) for i in range(n)]
    return [levels[i] for i in sorted(set(idx))]


def layers_payload(record_paths: dict, *, missile: str, cube: dict | None = None,
                   job: str | None = None, tag: str | None = None,
                   extra: dict | None = None) -> dict:
    """`GET /api/fig4/<id>/layers?missile=<key>`：**一枚弹的全部 N 层等时面**一次给全。

    `cube` 是**已经读出来并验过指纹**的立方体缓存（`fig4.read_cube()`）；缺失时由调用方
    （路由层）去起后台任务 —— 这里只管"有立方体时怎么折成 JSON"。
    顶点/索引**压成扁平数组**发出去（省 JSON，前端直接塞 WebGL 缓冲）。
    """
    from . import bg3d

    if cube is None:
        raise CubeMissing(str(missile))
    rec = read_record(record_paths["record"])
    if int(rec.get("schema", -1)) != SCHEMA:
        raise ValueError(f"图4 产物 schema={rec.get('schema')!r}，本模块只认 {SCHEMA}（重出产物）")
    grid = grid_contract(rec.get("grid") or {})
    layer = dict(rec.get("layer") or {})
    want = str(missile or "").strip()
    entries = {str(m.get("key") or ""): m for m in (rec.get("missiles") or ())}
    if want not in entries:
        raise KeyError(f"产物里没有这枚弹：{want!r}（有：{' / '.join(sorted(entries))}）")
    m = entries[want]
    cube = dict(cube)
    if str(cube.get("missile") or "") != want:
        raise ValueError(f"立方体缓存是 {cube.get('missile')!r} 的，不是 {want!r}")
    field = np.asarray(cube.get("t_hit"), dtype=float)
    if tuple(field.shape) != tuple(grid["shape"]):
        raise ValueError(f"立方体形状 {tuple(field.shape)} 与网格 {tuple(grid['shape'])} 不一致")
    step = float(layer.get("iso_step") or 1.0)
    count = int(layer.get("n_levels") or LAYER_COUNT)
    levels = layer_levels(field, step=step, count=count)
    grid3 = bg3d.Bg3Grid(beta=tuple(grid["beta"]), gamma=tuple(grid["gamma"]),
                         dv=tuple(grid["dv"]), beta_step=grid["beta_step"],
                         gamma_step=grid["gamma_step"], dv_step=grid["dv_step"])
    surfs = bg3d.iso_surfaces(field, grid=grid3, levels=levels,
                              min_cells=LAYER_MIN_CELLS, min_tri=LAYER_MIN_TRI)
    out = []
    for s in surfs:
        V = np.asarray(s["vertices"], dtype=float)
        T = np.asarray(s["triangles"], dtype=int)
        out.append({
            "level": _round(s["level"], 4), "label": figures.iso_label(s["level"]),
            "ok": bool(s["ok"]), "reason": str(s["reason"]),
            "n_tri": int(s["n_tri"]), "n_vert": int(s["n_vert"]),
            "area": _round(s["area"], 2), "closed": bool(s["closed"]),
            "n_boundary": int(s["n_boundary"]), "n_cells": int(s["n_cells"]),
            "vertices": [round(float(x), LAYER_DIGITS) for x in V.reshape(-1)],
            "triangles": [int(i) for i in T.reshape(-1)],
        })
    summary = dict(cube.get("summary") or {})
    payload = {
        "ok": True, "figure": "fig4", "job": job, "tag": tag or rec.get("tag"),
        "schema": SCHEMA, "kind": figures.FIG4_KIND,
        "missile": {"key": want, "label": str(m.get("label") or want),
                    "dv": _round(_num(m.get("dv")), 3),
                    "beta": _round(_num(m.get("beta")), 3),
                    "gamma": _round(_num(m.get("gamma")), 3),
                    "hit": bool(m.get("hit")), "t_hit_s": _round(_num(m.get("t_hit_s")), 4),
                    "n_hit": int(summary.get("n_hit") or 0),
                    "n_cases": int(summary.get("n_cases") or grid["n_cases"]),
                    "cube_key": str(cube.get("cube_key") or ""),
                    "cube_cache_hit": bool(cube.get("cache_read_hit"))},
        "grid": {"beta": grid["beta"], "gamma": grid["gamma"], "dv": grid["dv"],
                 "shape": grid["shape"], "n_cases": grid["n_cases"],
                 "dv_pin_ms": _round(_num((rec.get("grid") or {}).get("dv_pin_ms")), 4),
                 "dv_lim": [_num(v) for v in ((rec.get("grid") or {}).get("dv_lim") or ())]},
        "layers": layer_contract(grid, dict(layer, levels=levels, n_levels=len(levels))),
        "surfaces": out,
        "colors": palette(),
        "scene": {"t_react_s": _round(_num(rec.get("t_react_s")), 3),
                  "text": str(rec.get("scene_text") or "")},
        "layers_note": ("面是 t_hit = 该层值的等值面（marching tetrahedra，与图1/图2 的等时线"
                        "同一套层定义）。立方体里的脱靶格子会让面被截断 —— 开口是常态，"
                        "`closed` 如实标出。"),
        "extra": dict(extra or {}),
    }
    return _clean(payload)

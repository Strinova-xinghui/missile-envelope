# -*- coding: utf-8 -*-
"""图4 的**交互式三维散点数据层**：读落盘产物 → 折成前端 WebGL 要吃的 JSON。

与 `traj3d.py` 同一套纪律（分写/读两侧）：

* **只读产物**（`results/fig4_<tag>.json` + `fig4_<tag>_cases.csv`），**不 import 求解器、不 import
  workflow** —— 所以"这个接口不解算"可以用毫秒级单测钉住（`solver.run` 打桩计数，见
  `tests/test_fig4.py`）；
* 配色**一律从 `figures` 现取**（`FIG4_CMAP_*` / `FIG4_MISS_COLOR` / …），前端 `fig4.js` 里
  一个颜色字面量都不写，所以"配色沿用 figures"是**可测**的；
* 本模块还提供**证据层的全部口径**（一次/二次拟合、残差、曲率、β–γ 面板的热度），因为这些东西
  必须**今天算的和明天读的**是同一套定义 —— 算核（`fig4scan.py`）与数据层共用下面这几个函数。

## 三根轴与"共享色标"（用户拍板的语义）

1. 三根轴 = **β / γ / ΔV**（都是物理参数，不是某一枚弹的标称值），颜色 = **t_hit**；
2. **11 枚弹共用同一套 (β,γ,ΔV) 网格**（`grid`，490 个格点里 ΔV 最外层）与**同一条色标范围**
   （`shared.ranges`，按**全部**弹的点云算出来）。所以切换弹种只换点云与统计，**不跳色标** ——
   否则同一片颜色在两枚弹上代表不同的秒数，横向比较是假的；
3. 点云的**展平顺序**恒为 `ΔV 外层 → γ → β`（与 `grid.cells()` 同序），于是"第 p 个点属于哪一根
   (β,γ) 竖线"就是 `p % (n_beta·n_gamma)`（`column_index()`）。前端靠这条关系拿到逐列统计，
   所以它必须**只有一个出处**、并被测钉住。

## 单层等时面（v3/v4 的主角；v1/v2 的"残差/曲率证据层"已作废）

用户口径：**默认纯散点**；**选中弹种 + 工况之后**才出**一层**等时面，用**滑动条**改 t、
一次只显示一层。所以：

* **层定义**借 `grid.iso_levels(cube, iso_step)`（图1/图2 的等时线用的**同一个函数**，整秒），
  再等距挑 `LAYER_COUNT = 13` 档（端点保留）—— 档位仍然全是整秒等时面，只是不全塞进滑动条；
* **几何**借 `bg3d.iso_surfaces()`（内部 `marching_tetrahedra`），本模块不重造算法；
* **开口是常态**：立方体里的 `nan`（脱靶）格子会让面被截断，所以逐层如实报
  `ok / reason / closed / n_boundary / n_tri / area`；`ok=False` 的层在界面上置灰并说明原因；
* 0 命中的弹（`layerable=False`）**不出面**，点云只画空心标记 —— 绝不用 `lifetime` 冒充 `t_hit`；
* **零往返**：`layers_payload()` 一次给全 N 层，前端滑块只在本地切换。

逐列的 `slope / intercept / quad / rms_lin / rms_quad / curv_span / curv_frac`
（以及 `plane_fit()` 的全局平面系数）**仍然算、仍然落盘**（用户做视频可能要用），**只是不画**。
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import numpy as np

from . import figures
from .spec import RESULT_DIR

#: 产物 schema（`results/fig4_<tag>.json` 的 `schema`）。改记录语义时 +1。
#: v2：默认想定从**直飞**换成图3 的 **crank→39（39 固定 35.0 s）**、ΔV 轴从"相对倍数"改成
#: **绝对区间**（`dv_lim` + `n_dv`）、新增"单层等时面"的层契约（`layers`）。
SCHEMA = 2

DEFAULT_TAG = "default"
#: 默认 ΔV 钉值 = PL-12 的权威 ΔV（`results/bg_default.json` → `scan.dv_pin_ms`）。
#: 扫描时如果没给 `dv_pin`，算核会用**基准弹**的权威 ΔV 覆盖它（不是硬编码这一个数）。
DV_PIN_MS = 932.5697
#: ΔV 轴的**绝对**区间与点数（v4；以前是"相对基准弹标称 ΔV 的倍数"）。
#: 实测依据（S0 探测：crank→39 / 39 固定 35.0 s / 7×7 网格）：ΔV ≤ 600 整层全脱靶、
#: 700~1000 是**能力边界带**（PL-12：700:0/49、800:14/49、900:28/49、1000:42/49）、
#: ≥1100 该弹全命中。所以轴取 [700,1700]（11 点）而不是 v3 推荐的 [500,1500]
#: （后者会让 11 层里 4 层全空）。数字与理由见 `docs/FIG4.md`。
DV_LIM = (700.0, 1700.0)
N_DV = 11
#: β、γ 各 7 点（域 = 图2 的自适应域，见 `figures.bg_axis`；γ 因此**只在弹池内**）。
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

#: 点云展平顺序（**唯一口径**）。前端与测试都读这一条，别各自写一遍。
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
    取模就够。这条关系如果错了，"逐列"的残差/曲率会整块错位，**而图上只是颜色难看**。
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


# --------------------------------------------------------------------- 证据层：逐列拟合


def _as_cube(values, shape) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.shape != tuple(shape):
        raise ValueError(f"立方体形状不对：收到 {arr.shape}，要 {tuple(shape)}")
    return arr


def fit_columns(t_hit, dv, *, n_beta: int = N_BETA, n_gamma: int = N_GAMMA) -> dict:
    """逐 (β,γ) 列对 ΔV 做**一次**与**二次**最小二乘拟合，并把残差/曲率摊回每个点。

    `t_hit` 的形状是 `(n_dv, n_gamma, n_beta)`，未命中 = `nan`。
    **只有整列都有限**的列才参与拟合（列里有一个脱靶点，"这根竖线"就不完整，
    硬插值补齐只会把脱靶读成"曲率很大"）—— 其余列全部给 `nan`。

    返回（列向量一律 `(n_col,)`、逐点数组一律 `(n_dv, n_col)`，`n_col = n_gamma·n_beta`）：

    | 键 | 含义 |
    | --- | --- |
    | `ok` | 该列是否参与拟合 |
    | `intercept` / `slope` | 一次拟合 `a + b·ΔV` |
    | `quad` | 二次项系数 `c`（`t = a + b·ΔV + c·ΔV²`），单位 s/(m/s)² |
    | `rms_lin` / `rms_quad` | 一次 / 二次拟合的残差 RMS [s] |
    | `curv_span` | `|c|·(ΔV 跨度)²/4`，端点相对中点的抬升 [s]（与 `bg3d.dv_quadratic` 同口径） |
    | `curv_frac` | `curv_span ÷ 该列 ΔV 造成的 t_hit 跨度`（无量纲） |
    | `resid_lin` | 逐点一次拟合残差 `t − (a + b·ΔV)` [s] |
    | `quad_term` | 逐点二次项贡献 `c·(ΔV − ΔV̄)²` [s]（非负） |
    """
    shape = shape_of(t_hit, "fit_columns")
    if len(shape) != 3:
        raise ValueError(f"t_hit 必须是三维立方体 (n_dv, n_gamma, n_beta)，收到 {shape}")
    cube = _as_cube(t_hit, shape)
    n_dv = shape[0]
    dvs = np.asarray(dv, dtype=float).reshape(-1)
    if len(dvs) != n_dv:
        raise ValueError(f"dv 有 {len(dvs)} 个点，与 t_hit 的第一维 {n_dv} 不一致")
    n_col = shape[1] * shape[2]
    Y = cube.reshape(n_dv, n_col)
    out = {
        "n_dv": n_dv, "n_col": n_col, "dv": dvs,
        "ok": np.zeros(n_col, dtype=bool),
        "intercept": np.full(n_col, np.nan), "slope": np.full(n_col, np.nan),
        "quad": np.full(n_col, np.nan),
        "rms_lin": np.full(n_col, np.nan), "rms_quad": np.full(n_col, np.nan),
        "curv_span": np.full(n_col, np.nan), "curv_frac": np.full(n_col, np.nan),
        "resid_lin": np.full((n_dv, n_col), np.nan),
        "quad_term": np.full((n_dv, n_col), np.nan),
    }
    if n_dv < 3 or n_col == 0:
        return out
    ok = np.isfinite(Y).all(axis=0)
    out["ok"] = ok
    if not bool(ok.any()):
        return out
    Ys = Y[:, ok]
    A1 = np.column_stack([np.ones(n_dv), dvs])
    A2 = np.column_stack([np.ones(n_dv), dvs, dvs * dvs])
    c1, *_ = np.linalg.lstsq(A1, Ys, rcond=None)
    c2, *_ = np.linalg.lstsq(A2, Ys, rcond=None)
    r1 = Ys - A1 @ c1
    r2 = Ys - A2 @ c2
    span_dv = float(dvs.max() - dvs.min())
    dvs_mean = float(dvs.mean())
    curv = np.abs(c2[2]) * span_dv ** 2 / 4.0
    eff = np.ptp(Ys, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = curv / np.where(eff > 0, eff, np.nan)
    out["intercept"][ok] = c1[0]
    out["slope"][ok] = c1[1]
    out["quad"][ok] = c2[2]
    out["rms_lin"][ok] = np.sqrt((r1 ** 2).mean(axis=0))
    out["rms_quad"][ok] = np.sqrt((r2 ** 2).mean(axis=0))
    out["curv_span"][ok] = curv
    out["curv_frac"][ok] = frac
    out["resid_lin"][:, ok] = r1
    out["quad_term"][:, ok] = c2[2][None, :] * (dvs[:, None] - dvs_mean) ** 2
    return out


def shape_of(values, who: str = "立方体") -> tuple:
    """`np.asarray(values).shape` 的可读包装（只为了让报错带上调用者名字）。"""
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        raise ValueError(f"{who} 收到标量，应该是三维立方体")
    return tuple(arr.shape)


def plane_fit(t_hit, beta, gamma, dv) -> dict:
    """**全局**最小二乘平面 `t ≈ c0 + c1·β + c2·γ + c3·ΔV`（图上"拟合平面"层就是它）。

    与 `fit_columns()` 的分工：这里回答"**一整张平面**够不够"，逐列拟合回答"每条 ΔV 竖线
    各偏多少"。两个都要报 —— 只报后者会让人以为"平面上到处都是弯"，只报前者看不出弯在哪。
    只用**有限**的点拟合（脱靶点没有 t_hit）。
    """
    cube = np.asarray(t_hit, dtype=float)
    if cube.ndim != 3:
        raise ValueError(f"t_hit 必须是三维立方体，收到 {cube.shape}")
    n_dv, n_gamma, n_beta = cube.shape
    if (len(dv), len(gamma), len(beta)) != (n_dv, n_gamma, n_beta):
        raise ValueError("beta/gamma/dv 的长度与 t_hit 的三个维度不一致")
    # 逐点四列，轴序与立方体 `(i_dv, j_gamma, k_beta)` 对齐（`indexing` 的默认值在这里容易看错，
    # 所以显式展开，别用 meshgrid）。
    rows = []
    for i, d in enumerate(np.asarray(dv, float)):
        for j, g in enumerate(np.asarray(gamma, float)):
            for k, b in enumerate(np.asarray(beta, float)):
                rows.append((b, g, d, cube[i, j, k]))
    rows = np.asarray(rows, dtype=float)
    good = np.isfinite(rows[:, 3])
    n = int(good.sum())
    if n < 4:
        return {"n": n, "coef": None, "rms_s": math.nan}
    X = np.column_stack([np.ones(n), rows[good, 0], rows[good, 1], rows[good, 2]])
    y = rows[good, 3]
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    rms = float(np.sqrt(((y - X @ coef) ** 2).mean()))
    return {"n": n, "coef": [float(v) for v in coef], "rms_s": rms,
            "form": "t ≈ c0 + c1·β + c2·γ + c3·ΔV"}


# --------------------------------------------------------------------- 配色 / 图例


def palette() -> dict:
    """图4 的全部配色：**源头就是 `figures`**（前端不写死任何一个）。

    v4：残差/曲率/拟合平面/热力图那几层不画了，所以只留 `t_hit` 一根色标 + 等时面的透明度。
    """
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
            "induced": figures.FIG4_LEGEND_INDUCED}


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
    `round` 之后补 —— 必须在前面拦。全部脱靶那一档（拟合全 `nan`）就是这条的活样本：
    漏了它，`/api/fig4/miss` 的响应里会出现 `NaN`（本条由
    `test_fig4_payload_is_strict_json` 用 `allow_nan=False` 钉住）。
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


# --------------------------------------------------------------------- 折成前端 JSON


def _cloud(cube, hit, dv_measured, fit, *, n_beta: int, n_gamma: int, digits: int = 4) -> dict:
    """一枚弹的立方体 → 点云（展平顺序见 `FLAT_ORDER`）。"""
    t = np.asarray(cube, dtype=float).reshape(-1)
    h = np.asarray(hit, dtype=bool).reshape(-1)
    dvm = np.asarray(dv_measured, dtype=float).reshape(-1)
    t_out, miss_idx, dvm_out = [], [], []
    for i in range(t.size):
        if h[i] and math.isfinite(t[i]):
            t_out.append(_round(t[i], digits))
        else:
            t_out.append(None)
            miss_idx.append(i)
        dvm_out.append(_round(dvm[i], digits))
    n_col = int(n_beta) * int(n_gamma)
    return {
        # ⚠ v4：逐点的 `resid` / `curv` **不发了**（用户"残差不需要了"，不画就不发）。
        #   逐列的 `slope/rms_lin/curv_span/curv_frac/...` 仍然留着 —— 数值可以备用，只是不画。
        "n": int(t.size),
        "t": t_out,
        "dv_measured": dvm_out, "miss_idx": miss_idx,
        "slope": [_round(v, 6) for v in np.asarray(fit["slope"]).reshape(-1)],
        "intercept": [_round(v, 4) for v in np.asarray(fit["intercept"]).reshape(-1)],
        "quad": [_round(v, 9) for v in np.asarray(fit["quad"]).reshape(-1)],
        "rms_lin": [_round(v, 4) for v in np.asarray(fit["rms_lin"]).reshape(-1)],
        "rms_quad": [_round(v, 4) for v in np.asarray(fit["rms_quad"]).reshape(-1)],
        "curv_span": [_round(v, 4) for v in np.asarray(fit["curv_span"]).reshape(-1)],
        "curv_frac": [_round(v, 5) for v in np.asarray(fit["curv_frac"]).reshape(-1)],
        "n_col": n_col,
    }


def _clean(obj):
    """递归把非有限浮点折成 `None`（**响应必须是严格 JSON**：裸 `NaN` 会让前端白屏）。

    只处理 dict / list / 标量；`fig4scan.plane_fit()` 在"点太少"时会给出 `rms_s = nan`、
    `coef = None`，那一档就是这条的活样本（全脱靶的小档）。
    """
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


def build(paths: dict, *, job: str | None = None, tag: str | None = None,
          extra: dict | None = None) -> dict:
    """产物路径 → 图4 查看器要吃的 JSON。

    `paths` 里要有 `record`（`results/fig4_<tag>.json`）与 `cases`（逐工况 CSV）。
    两者**都必须在磁盘上**：只有 JSON 而缺 CSV，说明产物被清理过一半 —— 报错，别画半张图。
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

    grid = dict(rec.get("grid") or {})
    beta = [float(v) for v in (grid.get("beta") or ())]
    gamma = [float(v) for v in (grid.get("gamma") or ())]
    dv = [float(v) for v in (grid.get("dv") or ())]
    n_beta, n_gamma, n_dv = len(beta), len(gamma), len(dv)
    if min(n_beta, n_gamma, n_dv) < 2:
        raise ValueError("产物里的 (β,γ,ΔV) 网格不完整（每根轴至少要 2 个点）")

    colors = palette()
    missiles, clouds, planes = [], {}, {}
    for m in rec.get("missiles") or ():
        key = str(m.get("key") or "")
        if not key or key in clouds:
            raise ValueError(f"产物里的弹池记录不合法（key = {key!r}）")
        cloud = _cloud(m["t_hit"], m["hit"], m.get("dv_measured"), m["fit"],
                       n_beta=n_beta, n_gamma=n_gamma)
        clouds[key] = cloud
        planes[key] = m.get("plane") or {}
        missiles.append({
            "key": key, "label": str(m.get("label") or key),
            "native": str(m.get("native") or ""),
            "beta": _round(_num(m.get("beta")), 2), "gamma": _round(_num(m.get("gamma")), 3),
            "dv": _round(_num(m.get("dv")), 2),
            "n_star_g": _round(_num(m.get("n_star_g")), 3),
            "R_ref": _round(_num(m.get("R_ref")), 4),
            "q_sens": _round(_num(m.get("q_sens")), 2),
            "n_hit": int(m.get("n_hit") or 0), "n_cases": int(m.get("n_cases") or cloud["n"]),
            "hit_rate": _round(_num(m.get("hit_rate")), 4),
            # ⚠ 0 命中的弹**不许**出等时面（也不许拿 lifetime 冒充 t_hit）：界面靠这个键置灰。
            "layerable": bool(cloud["n"] > 0 and int(m.get("n_hit") or 0) > 0
                              and bool(_finite(cloud["t"]))),
        })

    # ---- 共享色标范围：按**全部**弹的点云算（切换弹种不跳色标）----------------
    all_t = [v for c in clouds.values() for v in c["t"] if v is not None]
    ranges = {"t_hit": [_round(min(all_t), 4), _round(max(all_t), 4)] if all_t else None}
    per_missile_t = {k: [_round(min(_finite(c["t"])), 4), _round(max(_finite(c["t"])), 4)]
                     for k, c in clouds.items() if _finite(c["t"])}

    # ---- 逐列的"是否诱导阻力主导"（R = (n/n*)² ≥ 1）--------------------------
    for m in rec.get("missiles") or ():
        key = str(m.get("key") or "")
        cols = m.get("columns") or {}
        clouds[key]["R_ref"] = [_round(_num(v), 4) for v in (cols.get("R_ref") or ())]
        clouds[key]["n_star_g"] = [_round(_num(v), 3) for v in (cols.get("n_star_g") or ())]

    ref = dict(rec.get("ref_condition") or {})
    scene = dict(rec.get("scene") or {})
    scene = {"t_react_s": _round(_num(rec.get("t_react_s")), 3),
             "t_react_note": str(rec.get("t_react_note") or ""),
             "text": str(rec.get("scene_text") or _scene_text(rec))} | scene
    # 判别量只随 (β,γ) 与参考工况变（与哪枚弹无关），所以"主导列数"按**每弹**报一份，
    # 再乘弹数给总数 —— 不要写成"一个跨弹累加的计数"，那个数没有物理含义。
    per_missile_induced = 0
    for c in clouds.values():
        per_missile_induced = sum(1 for v in c.get("R_ref") or () if _num(v, 0.0) >= 1.0)
        break
    payload = {
        "ok": True, "figure": "fig4", "kind": figures.FIG4_KIND,
        "job": job, "tag": tag or rec.get("tag"), "schema": SCHEMA,
        "title": figures.FIG4_TITLE,
        "subtitle": _subtitle(rec, ref),
        "standard": rec.get("standard"), "tier": rec.get("tier"),
        "backend": rec.get("backend"), "n_ref": _num(rec.get("n_ref")),
        "scene": scene, "solver": dict(rec.get("solver") or {}),
        "ref_condition": ref,
        "axes": _axes(beta, gamma, dv, colors),
        "grid": {"beta": beta, "gamma": gamma, "dv": dv,
                 "shape": [n_dv, n_gamma, n_beta], "n_cases": int(grid.get("n_cases") or 0),
                 "beta_step": _round(_num(grid.get("beta_step")), 4),
                 "gamma_step": _round(_num(grid.get("gamma_step")), 4),
                 "dv_step": _round(_num(grid.get("dv_step")), 5),
                 "dv_pin_ms": _round(_num(grid.get("dv_pin_ms")), 4),
                 "dv_lim": [_num(v) for v in (grid.get("dv_lim") or ())],
                 "flat_order": FLAT_ORDER, "column_span": n_beta * n_gamma},
        "missiles": missiles,
        "clouds": clouds,
        "shared": {"grid": True, "ranges": ranges,
                   "per_missile_t_range": per_missile_t,
                   "note": "11 枚弹共用同一套 (β,γ,ΔV) 网格与同一条色标范围（切换不跳色标）"},
        "fit": {"plane": planes,
                "form": "逐 (β,γ) 列对 ΔV 做一次/二次最小二乘",
                "columns": {"n_col": n_beta * n_gamma, "order": "γ 外层 → β 内层",
                            "ok_key": "rms_lin 非空即参与拟合"}},
        "layers": layer_contract(grid, rec.get("layer") or {}),
        "degrade": {"note": ("该弹在此工况下 0 命中：没有 t_hit，因此不出等时面"
                            "（绝不用 lifetime 冒充命中时间）；点云只画空心标记。")},
        "colors": colors, "legend": legend(), "modes": modes(),
        "markers": {"hit": "dot", "miss": "hollow",
                    "note": "命中/脱靶**不靠颜色区分**：脱靶一律空心标记（且没有 t_hit 可着色）"},
        "footnotes": list(figures.FIG4_FOOTNOTES),
        "induced": {"n_columns": int(per_missile_induced),
                    "n_columns_total": int(per_missile_induced) * len(missiles),
                    "n_ref": _num(rec.get("n_ref")),
                    "rule": "R = (n_ref/n*)² ≥ 1 ⇒ 诱导阻力主导",
                    "columns_total": sum(len(c.get("R_ref") or ()) for c in clouds.values())},
        "axis_note": ("三根轴已各自归一化到等长（刻度与标签是真值）；"
                      "点云展平顺序 " + FLAT_ORDER),
        "extra": dict(extra or {}),
    }
    # 出口再兜一次：响应必须是**严格 JSON**（裸 `NaN` 会让 `JSON.parse` 直接抛错，页面白屏）。
    return _clean(payload)


def _axes(beta, gamma, dv, colors) -> list:
    labels = figures.FIG4_AXIS_LABELS
    out = []
    for axis_id, vals, unit in (("beta", beta, "kg/m²"), ("dv", dv, "m/s"),
                                ("gamma", gamma, "kg/m²")):
        out.append({"id": axis_id, "label": labels.get(axis_id, axis_id), "unit": unit,
                    "limits": [float(vals[0]), float(vals[-1])],
                    "values": [float(v) for v in vals],
                    "ticks": [float(v) for v in vals],
                    "color": colors["axis"].get(axis_id, colors["text"])})
    return out


def _subtitle(rec: dict, ref: dict) -> str:
    sd = dict(rec.get("summary") or {})
    parts = [f"弹池 {len(rec.get('missiles') or ())} 型",
             f"网格 {sd.get('shape') or ''}".replace("[", "").replace("]", "").strip(),
             f"工况 {sd.get('n_cases', '?')} × {len(rec.get('missiles') or ())} 弹"]
    if ref:
        parts.append(f"判别量参考工况 {_num(ref.get('alt_m'), 0) / 1000:g} km / "
                     f"{_num(ref.get('speed_ms'), 0):g} m/s")
    parts.append(f"档位 {rec.get('tier')}（{rec.get('backend')}）")
    return " · ".join(p for p in parts if p)


# ===================================================================== 等时面（单层）

def layer_contract(grid: dict, layer: dict) -> dict:
    """前端要的**层契约**：多少档、步长、门槛、接口地址、各档的 t 值与标签。"""
    return {
        "n_levels": int(layer.get("n_levels") or LAYER_COUNT),
        "iso_step": _round(_num(layer.get("iso_step"), 0.0), 4),
        "min_cells": int(layer.get("min_cells") or LAYER_MIN_CELLS),
        "min_tri": int(layer.get("min_tri") or LAYER_MIN_TRI),
        "levels": [_round(v, 4) for v in (layer.get("levels") or ())],
        "labels": [figures.iso_label(v) for v in (layer.get("levels") or ())],
        "endpoint": "/api/fig4/<id>/layers?missile=",
        "source": ("grid.iso_levels(cube, step) → bg3d.iso_surfaces(cube, grid, levels)"),
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


def layers_payload(paths: dict, *, missile: str, job: str | None = None,
                   tag: str | None = None, extra: dict | None = None) -> dict:
    """`GET /api/fig4/<id>/layers?missile=<key>`：**一枚弹的全部 N 层等时面**一次给全。

    只读产物（`solver.run` 零调用）：层定义来自 `layer_levels()`（= `grid.iso_levels`），
    几何来自 `bg3d.iso_surfaces()`（内部 `marching_tetrahedra`）。
    顶点/索引**压成扁平数组**发出去（省 JSON，前端直接塞 WebGL 缓冲）。
    """
    from . import bg3d, grid as grid_mod  # noqa: F401  （grid 只是为了让"层定义来源"显式）

    rec = read_record(paths["record"])
    if int(rec.get("schema", -1)) != SCHEMA:
        raise ValueError(f"图4 产物 schema={rec.get('schema')!r}，本模块只认 {SCHEMA}（重出产物）")
    grid = dict(rec.get("grid") or {})
    beta = [float(v) for v in (grid.get("beta") or ())]
    gamma = [float(v) for v in (grid.get("gamma") or ())]
    dv = [float(v) for v in (grid.get("dv") or ())]
    if min(len(beta), len(gamma), len(dv)) < 2:
        raise ValueError("产物里的 (β,γ,ΔV) 网格不完整（每根轴至少要 2 个点）")
    want = str(missile or "").strip()
    entries = {str(m.get("key") or ""): m for m in (rec.get("missiles") or ())}
    if want not in entries:
        raise KeyError(f"产物里没有这枚弹：{want!r}（有：{' / '.join(sorted(entries))}）")
    m = entries[want]
    cube = np.asarray(m.get("t_hit"), dtype=float)
    layer = dict(rec.get("layer") or {})
    step = float(layer.get("iso_step") or 1.0)
    count = int(layer.get("n_levels") or LAYER_COUNT)
    levels = layer_levels(cube, step=step, count=count)
    grid3 = bg3d.Bg3Grid(beta=tuple(beta), gamma=tuple(gamma), dv=tuple(dv),
                         beta_step=_num(grid.get("beta_step"), 0.0) or 0.0,
                         gamma_step=_num(grid.get("gamma_step"), 0.0) or 0.0,
                         dv_step=_num(grid.get("dv_step"), 0.0) or 0.0)
    surfs = bg3d.iso_surfaces(cube, grid=grid3, levels=levels,
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
    n_hit = int(m.get("n_hit") or 0)
    payload = {
        "ok": True, "figure": "fig4", "job": job, "tag": tag or rec.get("tag"),
        "schema": SCHEMA, "kind": figures.FIG4_KIND,
        "missile": {"key": want, "label": str(m.get("label") or want),
                    "beta": _round(_num(m.get("beta")), 2),
                    "gamma": _round(_num(m.get("gamma")), 3),
                    "dv": _round(_num(m.get("dv")), 2),
                    "n_hit": n_hit, "n_cases": int(m.get("n_cases") or 0),
                    "layerable": bool(n_hit > 0)},
        "grid": {"beta": beta, "gamma": gamma, "dv": dv,
                 "shape": [len(dv), len(gamma), len(beta)],
                 "dv_pin_ms": _round(_num(grid.get("dv_pin_ms")), 4),
                 "dv_lim": [_num(v) for v in (grid.get("dv_lim") or ())]},
        # 契约里的档位必须就是**这次真发给前端的那 13 个 t**（否则前端滑块刻度与网格对不上）
        "layers": layer_contract(grid, dict(layer, levels=levels, n_levels=len(levels))),
        "surfaces": out,
        "colors": palette(),
        "layers_note": ("面是 t_hit = 该层值的等值面（marching tetrahedra，与图1/图2 的等时线"
                        "同一套层定义）。立方体里的脱靶格子会让面被截断 —— 开口是常态，"
                        "`closed` 如实标出。"),
        "extra": dict(extra or {}),
    }
    return _clean(payload)


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
        bits.append(f"载机 {_num(sc.get('vm0'), 0):g} m/s 航向 {_num(sc.get('launch_heading_deg'), 0):g}°")
        bits.append(f"目标 {_num(sc.get('target_speed_ms'), 0):g} m/s 航向 "
                    f"{_num(sc.get('target_heading_deg'), 0):g}°")
    return " · ".join(bits)

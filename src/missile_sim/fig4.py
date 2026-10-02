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

## 证据层（这张图的主角之一）

用户论点是"**在诱导阻力主导的场合（大 γ），第三轴 ΔV 不再是常数偏移、平面假设失效**"。
可证伪的量就是下面这三个，全部按**逐 (β,γ) 列**（固定 β、γ，沿 ΔV 的那条竖线）定义：

| 量 | 定义 | 单位 | 读法 |
| --- | --- | --- | --- |
| `resid_lin` | `t_hit − (a + b·ΔV)`，逐列一次拟合 | s | 偏离 0 = "ΔV 只造成平移"这条假设在这根竖线上失效 |
| `quad_term` | `c·(ΔV − ΔV̄)²`，含逐列二次项 `c` | s | 二次项到底贡献了几秒（非负） |
| `curv_frac` | `|c|·(ΔV 跨度)²/4 ÷ 该列 t_hit 的 ΔV 跨度` | — | 弯的幅度相对"ΔV 效应"有多大（无量纲，可跨列比） |

`tests/test_fig4.py` 用**合成数据**把这条判据证伪了一遍：一组"ΔV 只造成平移"（残差/曲率必须≈0）、
一组"强曲率且只在大 γ 列"（残差/曲率必须大，且 β–γ 面板的热点必须落在最大 γ 那一列）。
`curv_frac` 与 `resid_lin` 的**数值口径**也在这里，`bg3d.dv_linearity()` / `dv_quadratic()` 是同一族
口径的全场摘要（那张表见 `docs/FIG-BG3D-FEASIBILITY.md` §5）。
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
SCHEMA = 1

DEFAULT_TAG = "default"
#: 默认 ΔV 钉值 = PL-12 的权威 ΔV（`results/bg_default.json` → `scan.dv_pin_ms`）。
#: 扫描时如果没给 `dv_pin`，算核会用**基准弹**的权威 ΔV 覆盖它（不是硬编码这一个数）。
DV_PIN_MS = 932.5697
#: ΔV 轴的 5 个点 = 这个倍数 × `dv_pin`（默认 0.6×~1.4× ⇒ 559.54~1305.60 m/s）。
DV_FACTORS = (0.6, 0.8, 1.0, 1.2, 1.4)
#: β、γ 各 7 点（域 = 图2 的自适应域，见 `figures.bg_axis`）。
N_BETA = 7
N_GAMMA = 7

#: 产物名后缀（`--tag`）只认这套字符：它会进文件名，宽容修正等于给路径穿越开后门。
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
#: 查看器要读的产物（缺一个就报错，不回落）。
REQUIRED_PRODUCTS = ("record", "cases")

#: 点云展平顺序（**唯一口径**）。前端与测试都读这一条，别各自写一遍。
FLAT_ORDER = "ΔV 外层 → γ → β（与 grid.cells() 同序）"

#: 颜色模式的键（与 `figures.FIG4_MODES` 的 `id` 必须一致）。
COLOR_MODES = tuple(m["id"] for m in figures.FIG4_MODES)
#: β–γ 小面板的热度口径键。
HEAT_METRICS = tuple(m["id"] for m in figures.FIG4_HEAT_METRICS)


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


def grid_shape(n_beta: int = N_BETA, n_gamma: int = N_GAMMA, n_dv: int = len(DV_FACTORS)) -> tuple:
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


def heat_values(fit: dict, *, n_beta: int, n_gamma: int) -> dict:
    """逐列统计 → β–γ 小面板要的二维数组（**行 = γ、列 = β**，与散点同序）。

    ⚠ 形状必须**显式给**，对不上就报错：`n_col` 与 `n_gamma·n_beta` 不一致时"reshape 成功"
    只可能发生在 9 = 3×3 这种巧合格子上，其余情况会静默给 `None` ——
    面板上少一片热度**看不出来**，所以这里宁可炸。
    """
    shape = (int(n_gamma), int(n_beta))
    out = {}
    for key, src in (("curv", "curv_frac"), ("resid", "rms_lin")):
        arr = np.asarray(fit.get(src), dtype=float).reshape(-1)
        if arr.size != shape[0] * shape[1]:
            raise ValueError(f"heat_values：{src} 有 {arr.size} 个列值，"
                             f"与 n_gamma·n_beta = {shape[0]}·{shape[1]} = "
                             f"{shape[0] * shape[1]} 不一致")
        out[key] = arr.reshape(shape)
    return out


def max_cell(arr) -> dict | None:
    """二维热度里最大的那一格（`None` = 全 `nan`）。β–γ 面板用它标"热点在哪"。"""
    a = np.asarray(arr, dtype=float)
    if a.size == 0 or not np.isfinite(a).any():
        return None
    flat = int(np.nanargmax(a))
    j, k = divmod(flat, a.shape[1])
    return {"i_gamma": int(j), "j_beta": int(k), "value": float(a[j, k])}


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
        "plane": figures.FIG4_PLANE_COLOR,
        "fit_line": figures.FIG4_FIT_LINE_COLOR,
        "hot_ring": figures.FIG4_HOT_RING_COLOR,
        "axis": dict(figures.FIG4_AXIS_COLORS),
        "cmap": {"t_hit": list(figures.FIG4_CMAP_T_HIT),
                 "resid": list(figures.FIG4_CMAP_RESID),
                 "curv": list(figures.FIG4_CMAP_CURV)},
        "source": ("figures.FIG4_CMAP_T_HIT / FIG4_CMAP_RESID / FIG4_CMAP_CURV / "
                   "FIG4_MISS_COLOR / FIG4_HIT_COLOR / FIG4_AXIS_COLORS / FIG4_BG_COLOR / "
                   "FIG4_TEXT_COLOR / FIG4_MUTED_COLOR / FIG4_BOX_COLOR / FIG4_PLANE_COLOR / "
                   "FIG4_FIT_LINE_COLOR / FIG4_HOT_RING_COLOR"),
    }


def legend() -> dict:
    return {"hit": figures.FIG4_LEGEND_HIT, "miss": figures.FIG4_LEGEND_MISS,
            "fitplane": figures.FIG4_LEGEND_FITPLANE,
            "fitcols": figures.FIG4_LEGEND_FITCOLS,
            "induced": figures.FIG4_LEGEND_INDUCED,
            "heat": figures.FIG4_LEGEND_HEAT}


def modes() -> list:
    return [dict(m) for m in figures.FIG4_MODES]


def heat_metrics() -> list:
    return [dict(m) for m in figures.FIG4_HEAT_METRICS]


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
    resid = np.asarray(fit["resid_lin"], dtype=float).T.reshape(-1)
    qterm = np.asarray(fit["quad_term"], dtype=float).T.reshape(-1)
    t_out, resid_out, curv_out, miss_idx, dvm_out = [], [], [], [], []
    for i in range(t.size):
        if h[i] and math.isfinite(t[i]):
            t_out.append(_round(t[i], digits))
            resid_out.append(_round(resid[i], digits))
            curv_out.append(_round(qterm[i], digits))
        else:
            t_out.append(None)
            resid_out.append(None)
            curv_out.append(None)
            miss_idx.append(i)
        dvm_out.append(_round(dvm[i], digits))
    n_col = int(n_beta) * int(n_gamma)
    return {
        "n": int(t.size),
        "t": t_out, "resid": resid_out, "curv": curv_out,
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
    missiles, clouds, heats, planes = [], {}, {}, {}
    for m in rec.get("missiles") or ():
        key = str(m.get("key") or "")
        if not key or key in clouds:
            raise ValueError(f"产物里的弹池记录不合法（key = {key!r}）")
        cloud = _cloud(m["t_hit"], m["hit"], m.get("dv_measured"), m["fit"],
                       n_beta=n_beta, n_gamma=n_gamma)
        clouds[key] = cloud
        heats[key] = heat_values(m["fit"], n_beta=n_beta, n_gamma=n_gamma)
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
        })

    # ---- 共享色标范围：按**全部**弹的点云算（切换弹种不跳色标）----------------
    all_t = [v for c in clouds.values() for v in c["t"] if v is not None]
    all_r = [v for c in clouds.values() for v in c["resid"] if v is not None]
    all_c = [v for c in clouds.values() for v in c["curv"] if v is not None]
    rmax = max([abs(v) for v in all_r] or [0.0])
    ranges = {
        "t_hit": [_round(min(all_t), 4), _round(max(all_t), 4)] if all_t else None,
        "resid": [-_round(rmax, 4), _round(rmax, 4)],
        "curv": [0.0, _round(max(all_c), 4)] if all_c else None,
    }
    per_missile_t = {k: [_round(min(_finite(c["t"])), 4), _round(max(_finite(c["t"])), 4)]
                     for k, c in clouds.items() if _finite(c["t"])}

    # ---- 逐列的"是否诱导阻力主导"（R = (n/n*)² ≥ 1）--------------------------
    for m in rec.get("missiles") or ():
        key = str(m.get("key") or "")
        cols = m.get("columns") or {}
        clouds[key]["R_ref"] = [_round(_num(v), 4) for v in (cols.get("R_ref") or ())]
        clouds[key]["n_star_g"] = [_round(_num(v), 3) for v in (cols.get("n_star_g") or ())]

    ref = dict(rec.get("ref_condition") or {})
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
        "scene": dict(rec.get("scene") or {}), "solver": dict(rec.get("solver") or {}),
        "ref_condition": ref,
        "axes": _axes(beta, gamma, dv, colors),
        "grid": {"beta": beta, "gamma": gamma, "dv": dv,
                 "shape": [n_dv, n_gamma, n_beta], "n_cases": int(grid.get("n_cases") or 0),
                 "beta_step": _round(_num(grid.get("beta_step")), 4),
                 "gamma_step": _round(_num(grid.get("gamma_step")), 4),
                 "dv_step": _round(_num(grid.get("dv_step")), 5),
                 "dv_pin_ms": _round(_num(grid.get("dv_pin_ms")), 4),
                 "dv_factors": [_num(v) for v in (grid.get("dv_factors") or ())],
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
        "heatmap": {"metrics": heat_metrics(), "default": HEAT_METRICS[0],
                    "beta": beta, "gamma": gamma,
                    "values": {k: {mk: (None if v is None else
                                        [[_round(x, 5) for x in row] for row in v])
                                   for mk, v in hv.items()}
                               for k, hv in heats.items()},
                    "hot": {k: {mk: max_cell(v) for mk, v in hv.items()}
                            for k, hv in heats.items()}},
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

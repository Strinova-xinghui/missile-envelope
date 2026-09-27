# -*- coding: utf-8 -*-
"""输出侧：**逐型对比表** —— 同一环境下，弹池每一型按它自己的标称 (ΔV, BC) 各跑一次。

与包线图的分工：包线图固定一枚基准弹、只动推力与阻力系数（答"同一枚弹换参数会怎样"）；
本模块固定环境、换整枚弹（答"这个环境里 11 型各自会怎样"）。所以这里是
**一弹一个 `Engine`** —— 引擎绑定 `missile` + `metrics` —— 每型只喂一个格点：它自己的
标称 (ΔV, BC)。标称工况下 `thrust_scale = cx_scale = 1.0`，跑的就是该型原始 blk。

三条纪律：

1. **批量必须走 `engine.Engine.many()`**：直接调 `solver.run()` 会绕过引擎的按档位缓存，
   同一工况重复计算（而且表里的数字可能和图分叉）。
2. **`Shot.t_hit = nan` 表示未命中** —— 表与 CSV 一律写占位符 `—`，**绝不写 0**
   （读的人会把 0 当成"命中时间 0 s"）。
3. CSV 沿用 `record.py` 的风格：`UTF-8-SIG`（Excel 才认中文表头）+ `newline=""`。
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from . import engine, pool, solver
from .spec import RESULT_DIR, Scene

#: 未命中 / 缺结果时的占位符。**不能用 0**：`Shot.t_hit = nan` 才是"没命中"。
MISS_PLACEHOLDER = "—"

#: 一行的完整键集（`compare()` 的返回契约，测试按它查"字段齐全"）。
ROW_FIELDS = ("key", "label", "full_name", "native", "dv", "bc",
              "thrust_scale", "cx_scale", "ok", "hit", "event",
              "t_hit", "t_end", "miss_m", "max_alt_m", "v_impact",
              "backend", "error", "tier", "cache_hit")

#: CSV 列：(行键, 中文表头)。顺序即落盘顺序；`native` 留 vendor 预设名便于回溯。
CSV_HEADER = (
    ("key", "弹名"),
    ("full_name", "全名"),
    ("native", "vendor 预设名"),
    ("dv", "ΔV [m/s]"),
    ("bc", "BC"),
    ("hit", "是否命中"),
    ("t_hit", "t_hit [s]"),
    ("max_alt_m", "最高点 [m]"),
    ("v_impact", "末速 [m/s]"),
    ("event", "event"),
    ("backend", "backend"),
    ("miss_m", "脱靶量 [m]"),
    ("error", "error"),
)

#: 控制台表：(表头, 行键, 对齐)。数字右对齐、文本左对齐、命中列居中。
TABLE_COLUMNS = (
    ("弹名", "key", "left"),
    ("ΔV", "dv", "right"),
    ("BC", "bc", "right"),
    ("命中", "hit", "center"),
    ("t_hit", "t_hit", "right"),
    ("最高点", "max_alt_m", "right"),
    ("末速", "v_impact", "right"),
    ("event", "event", "left"),
    ("backend", "backend", "left"),
)

#: 非数值单元格（原样打印，不做数字格式化）。
_TEXT_KEYS = frozenset({"key", "full_name", "native", "event", "backend", "error"})


# --------------------------------------------------------------------- 取值


def _finite(value) -> float:
    """转 float；转不了或非有限 ⇒ `nan`（一切"没有结果"都归到 nan 一种表示）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return math.nan
    return f if math.isfinite(f) else math.nan


def _num_cell(value) -> str:
    """CSV 数值单元格：非有限 ⇒ 占位符；其余与 `record._num` 同式（6 位有效数字）。"""
    f = _finite(value)
    return MISS_PLACEHOLDER if math.isnan(f) else f"{f:.6g}"


def _text_cell(value) -> str:
    return "" if value is None else str(value)


def _hit_cell(value) -> str:
    return "是" if value else "否"


# --------------------------------------------------------------------- 一行


def row_of(point, entry, shot, *, tier: str) -> dict:
    """一个散点 + 一次 `Shot` → 对比表的一行。

    `shot` 为 None（或 `ok=False`）时所有数字落成 `nan`，由落盘/打印层统一变占位符。
    """
    s = shot
    return {
        "key": point.key,
        "label": point.label,
        "full_name": entry.full_name,
        "native": point.native or entry.native,
        "dv": float(point.dv),                 # 标称 ΔV（弹池现算的权威值）
        "bc": float(point.bc),                 # 标称 BC
        "thrust_scale": 1.0,                   # 标称工况 ⇒ 两个乘数恒为 1.0
        "cx_scale": 1.0,
        "ok": bool(s and s.ok),
        "hit": bool(s and s.hit),
        "event": (s.event if s else ""),
        "t_hit": _finite(s.t_hit if s else None),
        "t_end": _finite(s.t_end if s else None),
        "miss_m": _finite(s.miss_m if s else None),
        "max_alt_m": _finite(s.max_alt_m if s else None),
        "v_impact": _finite(s.v_impact if s else None),
        "backend": (s.backend if s else ""),
        "error": (s.error if s else "没有结果"),
        "tier": str(tier),
        "cache_hit": bool(s and s.cache_hit),
    }


def compare(scene: Scene, *, missiles=None, tier: str = "fast", jobs: int | None = None,
            cache: bool = True, progress=None) -> list:
    """对给定环境，弹池每一型按自己的标称 (ΔV, BC) 各跑一次；返回逐型行（顺序 = 弹池顺序）。

    * `missiles`：同 `pool.resolve_many` —— None/"" 表示全池，也可给字符串或短名序列；
    * `tier` / `jobs` / `cache`：透传给 `Engine`；
    * `progress(done, total)`：每跑完一型回调一次（与 `Engine.many` 的回调同签名）。

    一弹一个 `Engine` 是**结构决定**的（引擎绑定 `missile` + `metrics`），所以 11 型是
    11 次 `many()`、每次 1 个格点 —— `jobs` 在这种单格点调用里不会起进程池，
    但接口照旧透传，将来一次喂多格点时无需改调用方。
    """
    pts = pool.points(missiles)
    n_jobs = int(jobs) if jobs else engine.default_jobs()
    shared = engine.ResultCache(tier=tier, enabled=cache)   # 11 次共用一份缓存文件
    rows = []
    for i, point in enumerate(pts, 1):
        entry = pool.resolve(point.key)
        eng = engine.Engine(scene, missile=entry.native, tier=tier, jobs=n_jobs,
                            cache=cache, metrics=pool.metrics_of(entry))
        eng.cache = shared                  # 只 load / save 一次，而不是每型一次
        try:
            shots = eng.many([(point.dv, point.bc)])
        finally:
            eng.close()
        rows.append(row_of(point, entry, shots[0] if shots else None, tier=tier))
        if progress is not None:
            progress(i, len(pts))
    return rows


# --------------------------------------------------------------------- 落盘


def write_compare_csv(rows, path) -> Path:
    """逐型对比表 → CSV。**UTF-8-SIG**（Excel 认中文表头）；未命中写 `—`。

    与 `record.write_cases_csv` 同款写法：`newline=""` 让 `csv.writer` 自己管行尾，
    不让 Python 在 Windows 上把 `\\n` 翻成 `\\r\\n`。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([head for _key, head in CSV_HEADER])
        for row in rows or ():
            w.writerow([_cell(row, key) for key, _head in CSV_HEADER])
    return path


def _cell(row: dict, key: str) -> str:
    """按列类型取单元格文本：命中 → 是/否，文本原样，其余数字（非有限 ⇒ 占位符）。"""
    value = row.get(key)
    if key == "hit":
        return _hit_cell(value)
    if key in _TEXT_KEYS:
        return _text_cell(value)
    return _num_cell(value)


# --------------------------------------------------------------------- 打印


def _disp_width(text: str) -> int:
    """终端显示宽度（与 `figures.wrap_lines` 同一条规则：CJK 记 2 列）。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _pad(text: str, width: int, align: str) -> str:
    gap = max(0, int(width) - _disp_width(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def _table_cell(row: dict, key: str) -> str:
    if key == "hit":
        return "命中" if row.get("hit") else "未命中"
    if key in _TEXT_KEYS:
        return _text_cell(row.get(key))
    return _num_cell(row.get(key))


def format_table(rows, *, scene: Scene | None = None, tier: str = "") -> str:
    """中文对齐表（控制台可直接 `print`）。未命中显示 `—`，**不显示 0**。

    给了 `scene` 就在表头上加一行 `Scene.describe()`（本模块不 import matplotlib）。
    """
    rows = list(rows or ())
    heads = [head for head, _key, _align in TABLE_COLUMNS]
    aligns = [align for _head, _key, align in TABLE_COLUMNS]
    body = [[_table_cell(row, key) for _head, key, _align in TABLE_COLUMNS] for row in rows]
    widths = [max([_disp_width(head)] + [_disp_width(r[i]) for r in body])
              for i, head in enumerate(heads)]

    lines = []
    if scene is not None:
        lines.append(f"环境：{scene.describe()}")
    lines.append("  ".join(_pad(head, w, "left") for head, w in zip(heads, widths)).rstrip())
    lines.append("  ".join("-" * w for w in widths))
    for cells in body:
        lines.append("  ".join(_pad(c, w, a)
                               for c, w, a in zip(cells, widths, aligns)).rstrip())

    n = len(rows)
    n_hit = sum(1 for row in rows if row.get("hit"))
    n_err = sum(1 for row in rows if not row.get("ok"))
    tail = f"共 {n} 型 · 命中 {n_hit}/{n}"
    if n_err:
        tail += f" · 求解失败 {n_err}"
    if tier:
        tail += f" · 档位 {tier}"
    backends = sorted({str(row.get("backend") or "") for row in rows} - {""})
    if backends:
        tail += f"（{' / '.join(backends)}）"
    lines.append("")
    lines.append(tail + " · 标称工况：thrust_scale = cx_scale = 1.0")
    lines.append(f"「{MISS_PLACEHOLDER}」= 未命中（`Shot.t_hit = nan`），不是 0；"
                 "单位：ΔV/末速 m/s、最高点 m、t_hit s")
    return "\n".join(lines)


# --------------------------------------------------------------------- 端到端


def run_compare(scene: Scene, *, missiles=None, tier: str = "fast", jobs: int | None = None,
                tag: str = "default", result_dir=None, cache: bool = True,
                progress=None) -> dict:
    """跑 + 落盘：`results/compare_<tag>.csv`。返回带 `_paths` 的汇总 dict。"""
    rows = compare(scene, missiles=missiles, tier=tier, jobs=jobs, cache=cache,
                   progress=progress)
    out_dir = Path(result_dir) if result_dir else RESULT_DIR
    path = write_compare_csv(rows, out_dir / f"compare_{tag}.csv")
    return {
        "rows": rows,
        "table": format_table(rows, scene=scene, tier=tier),
        "scene": scene.as_dict(),
        "missiles": [row["key"] for row in rows],
        "tier": tier,
        "solver": solver.identity(),
        "n_hit": sum(1 for row in rows if row["hit"]),
        "n_ok": sum(1 for row in rows if row["ok"]),
        "n_cache": sum(1 for row in rows if row["cache_hit"]),
        "backends": sorted({row["backend"] for row in rows if row["backend"]}),
        "_paths": {"compare_csv": str(path)},
    }

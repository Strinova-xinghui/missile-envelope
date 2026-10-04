# -*- coding: utf-8 -*-
"""全弹池目录：把内核认得的**全部**预设算成三张图要用的坐标（ΔV / β / γ / ginv）。

**为什么有这个东西**（用户 2026-10-04 口径）：三张图要能按"用户自选弹池"**实时**自适应，
就要求弹的坐标在**页面本地**可得。于是把全表在构建期算好、打成 `results/missile_catalog.json`
随包（也随静态站）发布 —— 静态站只发**派生数值**，**不发** Gaijin 的 blk 文件；
这份判定的两条阻塞见 `docs/STATIC-LAYER-REALTIME.md` §1。

**单一出处（第一原则）**：本模块**不写任何物理公式** ——
ΔV/BC 走 `mapping.blk_metrics()`，β/γ 走 `bg.point_of()`，预设名单走 `solver.preset_names()`，
参考工况走 `bg.reference()`。它只负责**枚举 / 折叠 / 打包 / 自校验**。

**命名与折叠规则**（写死，避免 UI 抖动）：

* 我们默认对比集的 11 弹沿用 `pool.POOL` 的短名与全名（`in_pool11 = True`）；
* 其余型号 `key = native`，`label = key`；
* `*_default` 是同一型号的孪生条目 ⇒ 标 `duplicate_of = 去掉后缀的名字`、`default_hidden = True`，
  **保留在表里但默认不显示**（不删，删了总数就对不上内核预设表了）；
* 不可算的型号（当前是 `cn_pl15*` 与 `us_aim_54a/b/c/c_plus*`，`propulsion*` 多发动机族）
  进 `unsupported`，**带内核给出的原话原因**，不猜、不近似。
"""

from __future__ import annotations

import json
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

from . import bg, mapping, pool, solver
from .spec import RESULT_DIR

#: 目录 schema：**加字段就 +1**（消费者据此判断能否直接吃）。
SCHEMA = 1

#: 产物名（`results/` 下）。
NAME = "missile_catalog.json"

#: 参考工况字段的顺序（与 `bg.reference()` 一一对应）。
_REF_FIELDS = ("alt_m", "speed_ms", "mach", "q_pa", "f_mach", "cap_f")

#: `bg.point_of()` 只要求对象有 `.key` / `.native`（见其 docstring）——
#: 全表枚举时不值得为每个预设构造 `pool.PoolEntry`，用一个轻量替身即可。
_Entry = namedtuple("_Entry", "key native")


class CatalogError(RuntimeError):
    """目录自校验失败（数值对不上、条目缺失、折叠规则坏了）。"""


def default_path() -> Path:
    return Path(RESULT_DIR) / NAME


def _pool_by_native() -> dict:
    return {e.native: e for e in pool.POOL}


def base_of(native: str) -> str:
    """`x_default` → `x`；其余原样。"""
    s = str(native)
    return s[: -len("_default")] if s.endswith("_default") else s


def key_of(native: str) -> str:
    """短名：11 弹池用池里的短名，其余用预设名本身。"""
    e = _pool_by_native().get(str(native))
    return e.key if e else str(native)


def build(version: str | None = None) -> dict:
    """算全表并返回目录记录（不落盘）。实测 2.59.0.28：168 条里 159 可算，约 2~8 s。"""
    names = list(solver.preset_names())
    if not names:
        raise CatalogError("内核没给出预设名单（solver.preset_names() 为空）—— 版本变了？")
    known = set(names)
    by_native = _pool_by_native()
    missiles, unsupported = [], []
    for native in names:
        info = solver.preset_info(native)
        key = key_of(native)
        entry = by_native.get(native)
        row = {
            "native": native,
            "key": key,
            "label": key,
            "full_name": (entry.full_name if entry else
                          (str(info.get("bullet_name") or "") or native)),
            "seeker": info.get("seeker"),
            "resource": str(info.get("resource") or ""),
            "resource_sha256": info.get("resource_sha256"),
            "in_pool11": bool(entry),
            "duplicate_of": (base_of(native)
                             if base_of(native) != native and base_of(native) in known else None),
        }
        row["default_hidden"] = row["duplicate_of"] is not None
        try:
            metrics = mapping.blk_metrics(solver.profile(native, version))
            point = bg.point_of(_Entry(key=key, native=native), version)
        except Exception as exc:                                # noqa: BLE001
            # 用户 2026-10-04 口径：**置灰原因就写「需要动态解算」**（面用户的话），
            # 内核/公式给的原话另存 `kernel_reason`（诊断与判据要用，别丢出处）。
            unsupported.append({**row, "reason": "需要动态解算",
                                "kernel_reason": f"{type(exc).__name__}: {exc}"})
            continue
        missiles.append({**row, "dv": metrics.dv, "bc": metrics.bc,
                         "gamma": point.gamma, "ginv": bg.ginv_of(point.gamma)})
    ident = solver.identity()
    return {
        "schema": SCHEMA,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "solver": {k: ident.get(k) for k in
                   ("solver", "model", "version", "sha256", "archive_sha256", "n_profiles")},
        "archive_sha256": ident.get("archive_sha256"),
        "reference": dict(zip(_REF_FIELDS, (float(x) for x in bg.reference()))),
        "count": len(names),
        "computable": len(missiles),
        "unsupported": unsupported,
        "missiles": missiles,
    }


def write_json(path=None, version: str | None = None) -> Path:
    """算全表并落盘；返回写出的路径。行尾与其它 `results/*.json` 一致（Windows 上 CRLF）。"""
    rec = build(version)
    path = Path(path) if path is not None else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load(path=None) -> dict:
    path = Path(path) if path is not None else default_path()
    return json.loads(path.read_text(encoding="utf-8"))


def verify(rec: dict, *, version: str | None = None, full: bool = True) -> None:
    """自校验：形状 + **逐值重算**（默认全表；`full=False` 只核 11 弹池，快）。

    有齿的地方：**改了记录里的任何一个坐标值都会在这里炸**（反证用例就是靠这个）。
    没装游戏数据/内核不可用的机器上，本函数会抛出 `SolverUnavailable`（上层按需跳过）。
    """
    if int(rec.get("schema") or 0) != SCHEMA:
        raise CatalogError(f"schema 不是 {SCHEMA}：{rec.get('schema')!r}")
    names = list(solver.preset_names())
    if int(rec.get("count") or 0) != len(names):
        raise CatalogError(f"count={rec.get('count')} 与内核预设数 {len(names)} 不一致")
    rows = {str(m.get("native")): m for m in (rec.get("missiles") or [])}
    bad = {str(u.get("native")) for u in (rec.get("unsupported") or [])}
    if set(rows) | bad != set(names):
        miss = sorted(set(names) - set(rows) - bad)[:5]
        raise CatalogError(f"目录没有覆盖内核预设表；缺 {miss} 等")
    if sum(1 for m in rows.values() if m.get("in_pool11")) != len(pool.POOL):
        raise CatalogError("`in_pool11` 的条目数与我们 11 弹池不一致")
    for native in (list(rows) if full else [e.native for e in pool.POOL]):
        metrics = mapping.blk_metrics(solver.profile(native, version))
        want = bg.point_of(_Entry(key=key_of(native), native=native), version)
        got = rows[native]
        for field, expect in (("dv", metrics.dv), ("bc", metrics.bc),
                              ("gamma", want.gamma), ("ginv", bg.ginv_of(want.gamma))):
            if float(got.get(field, float("nan"))) != float(expect):
                raise CatalogError(
                    f"{native} 的 {field} 对不上：目录 {got.get(field)!r} vs 现算 {expect!r}")


def describe(rec: dict) -> str:
    """一行摘要（CLI 打印用）。"""
    return (f"全弹池目录：{rec.get('computable')}/{rec.get('count')} 可算，"
            f"不可算 {len(rec.get('unsupported') or [])} 条"
            f"（{', '.join(sorted({str(u.get('key')) for u in (rec.get('unsupported') or [])}))}）")


# --------------------------------------------------------------------- 轴 oracle
#
# **为什么有这一段**（Lead 派单 2026-10-04，用户口径"三张图按自选弹池实时自适应"）：
# 静态层（`webui_static/figs2d.js`）要在**浏览器里**算同一根轴，就得有一个**可核对的基准**。
# oracle 把"给定弹子集 → 坐标轴"这件事在 Python 侧算一遍并打印成一行 JSON，
# 静态层拿它对拍。**轴算法一个字都不在这里** —— 范围完全由现成的
# `figures.adaptive_axis()` / `figures.bg_axis()` 算出来（第一原则：单一出处）。

#: `--axes` 支持的两张图。`plane` = 图1（ΔV–BC），`bg` = 图2（β–ginv）。
AXIS_KINDS = ("plane", "bg")

#: 轴函数的**输入替身**：只带轴真正读的那两列。
#: ⚠ 这不是"另写一套轴算法"：图1 的 `figures.adaptive_axis()` 只读 `.dv`/`.bc`，
#: 图2 的 `figures.bg_axis()` 只读 `.beta`/`.ginv`（见两者的源码），
#: 这里只负责把目录里的两列喂进去 —— 边界值仍然是那两个函数算的、按它们的规则四舍五入。
_AxisPoint = namedtuple("_AxisPoint", "dv bc")
_AxisRow = namedtuple("_AxisRow", "beta ginv")


def _index_of(rec: dict) -> dict:
    """{别名（小写）: (规范短名, 行)} —— `key`（短名）与 `native`（内核预设名）都能查到。"""
    idx = {}
    for m in rec.get("missiles") or []:
        for alias in (m.get("key"), m.get("native")):
            if alias:
                idx.setdefault(str(alias).strip().lower(), (str(m["key"]), m))
    return idx


def _unsupported_index(rec: dict) -> dict:
    """{别名（小写）: 不可算条目} —— "内核认得但算不了"要与"查无此名"分开报。"""
    out = {}
    for u in rec.get("unsupported") or []:
        for alias in (u.get("key"), u.get("native")):
            if alias:
                out.setdefault(str(alias).strip().lower(), u)
    return out


def resolve_keys(keys, *, rec: dict | None = None) -> list:
    """把「短名 / 内核预设名」折成**规范短名**：去重、保用户给的顺序。

    `keys=None` ⇒ **11 弹池**（与 `--missiles` 的默认一致，图1/图2 的常规形态）。
    **空字符串或空序列当场报错** —— 空集合画不出轴，静默给一根空轴只会让页面画一张空图。
    查无此名、以及内核认得但算不了的型号，都给可读错误（前者列出可用名）。
    """
    r = load() if rec is None else rec
    if keys is None:
        return [str(m["key"]) for m in (r.get("missiles") or []) if m.get("in_pool11")]
    raw = ([s for s in str(keys).replace(",", " ").split() if s]
           if isinstance(keys, str)
           else [str(s).strip() for s in keys if str(s).strip()])
    if not raw:
        raise CatalogError("一个弹都没选：`--axes` 至少要给一个短名或内核预设名（逗号分隔）")
    idx, bad = _index_of(r), _unsupported_index(r)
    out, seen = [], set()
    for item in raw:
        low = str(item).strip().lower()
        hit = idx.get(low)
        if hit is None:
            if low in bad:
                u = bad[low]
                raise CatalogError(
                    f"{item!r} 算不了 —— 面用户的原因「{u.get('reason')}」；"
                    f"内核原话：{u.get('kernel_reason')}")
            raise CatalogError(_unknown_message(str(item), r, idx))
        key = hit[0]
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _unknown_message(name: str, rec: dict, idx: dict) -> str:
    """查无此名时的可读错误：**列出可用名**（11 弹池全列 + 近似建议 + 全表出处）。"""
    pool_keys = [str(m["key"]) for m in (rec.get("missiles") or []) if m.get("in_pool11")]
    low = name.strip().lower()
    near = sorted({k for alias, (k, _row) in idx.items()
                   if low and (low in alias or alias in low)})[:5]
    n_known = len(rec.get("missiles") or [])
    return (f"目录里没有 {name!r}。11 弹池短名：{' / '.join(pool_keys)}；"
            f"另有 {n_known} 个可算预设（短名或内核名都收，如 `uk_redtop`）"
            + (f"；是否想写 {' / '.join(near)}？" if near else "")
            + "。全部可用名见 results/missile_catalog.json 的 missiles[].key")


def _rows_for(keys, *, rec: dict | None = None) -> list:
    r = load() if rec is None else rec
    idx = _index_of(r)
    return [idx[k.lower()][1] for k in resolve_keys(keys, rec=r)]


def axis_for(kind: str, keys=None, *, rec: dict | None = None):
    """**轴 oracle**：一个弹子集在图1/图2 上的坐标轴（`spec.AxisSpec`）。

    数值**直接来自** `figures.adaptive_axis()`（`kind="plane"`，图1）与
    `figures.bg_axis()`（`kind="bg"`，图2）—— 本模块不含任何轴算法，只负责"选行 → 喂进去"。
    默认从**落盘的目录**（`results/missile_catalog.json`）取数，所以静态层能在没有内核数据的
    机器上复现同一根轴。

    ⚠ 图2 的横轴 β 取目录里的 `bc` 列：两者是**同一个数**（`m_dry/(SD·CxK)` 的两种写法，
    实测逐型 |Δ| ≤ 1e-12、相对 ≤ 3e-16 的浮点路径差），而 `bg_axis()` 的边界按 **6 位小数**
    落定 ⇒ 与现算 β 得到的轴**逐值相同**。目录 schema 里没有单独的 `beta` 列
    （要不要补一列由 Lead 定，见回报）；补上之后这里改指向它即可。
    """
    from . import figures                              # 惰性：本模块默认不拖 matplotlib

    k = str(kind or "").strip().lower()
    if k not in AXIS_KINDS:
        raise CatalogError(f"kind 只能是 {' / '.join(AXIS_KINDS)}，收到 {kind!r}")
    rows = _rows_for(keys, rec=rec)
    if k == "plane":
        return figures.adaptive_axis([_AxisPoint(dv=float(r["dv"]), bc=float(r["bc"]))
                                      for r in rows])
    return figures.bg_axis([_AxisRow(beta=float(r["bc"]), ginv=float(r["ginv"]))
                            for r in rows])


def axis_payload(kind: str, keys=None, *, rec: dict | None = None) -> dict:
    """`--axes` 打印的那**一行 JSON**：字段固定这 5 个（消费者照这个契约吃，别加别减）。"""
    r = load() if rec is None else rec
    ks = resolve_keys(keys, rec=r)
    ax = axis_for(kind, ks, rec=r)
    return {"kind": str(kind or "").strip().lower(), "keys": ks, "n": len(ks),
            "xlim": [float(ax.xlim[0]), float(ax.xlim[1])],
            "ylim": [float(ax.ylim[0]), float(ax.ylim[1])]}

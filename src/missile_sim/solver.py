# -*- coding: utf-8 -*-
"""**与 `vendor/wt-missile/` 的唯一接触面** —— 换求解器只需要改这一个文件。

对外只有四个函数：

    load_solver()                  懒加载 + SHA-256 校验（不符即 SolverUnavailable）
    identity()                     求解器与资源的身份块（不跑积分）
    profile(native_name)           读一份 blk 参数块（弹池现算 ΔV/BC 用）
    run(scene, …)                  跑一次，返回结构化 `Shot`

**乘数不在这里算**：`Scaling` 由 `mapping.py`（ΔV/BC）与 `bg.py`（β/γ）产出，本模块只负责施加 ——
把 `thrust_scale` 乘到 `force`/`force1`、`cx_scale` 乘到 `CxK`、`cxaoa_scale` 乘到 `CxAoA`，
再交给求解器。
施加方式是 monkeypatch 求解器的模块级 `load_profile`（`compiled_simulate` 与
`scene_simulate` 都走它，所以 C 档同样吃到乘数），调用结束在 `finally` 里还原。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from pathlib import Path

from .spec import (HIT_EVENTS, SOLVER_DT, VENDOR_DIR, VERSION_28, Scaling, Scene, Shot)

# vendor 只读副本的身份。改这里等于改 vendor —— 升级流程见 vendor/wt-missile/VENDOR.md
SOLVER_FILE = "wt_missile.py"
SOLVER_SHA256 = "1bfa0fa2a3a6d34faa01e4b6ad77e15ba10573ed857bc3362ed368b4e8511890"

# 内核 `CxAoA` 的兜底值（`wt_missile.py:780`、`:1269`）。11 型 blk 里都没有这个字段，
# 所以实际生效值恒为 9.0 —— 但**不要**在别处硬写 9.0，一律走 `effective_cx_aoa()`。
KERNEL_CX_AOA_DEFAULT = 9.0

_SOLVER = None


class SolverUnavailable(RuntimeError):
    """vendor 求解器不可用：目录缺失、哈希不符、清单损坏或导入失败。"""


# --------------------------------------------------------------------- 加载与身份


def solver_file() -> Path:
    return VENDOR_DIR / SOLVER_FILE


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_solver(*, verify: bool = True):
    """把 vendor 目录挂上 `sys.path` 后 import；进程内只加载一次。

    目录名带连字符（`wt-missile`）不能当包名，但 `wt_missile.py` 本身是合法模块名，
    所以挂目录即可 —— 子进程里同样有效（worker 重新 import 本模块即完成加载）。
    """
    global _SOLVER
    if _SOLVER is not None:
        return _SOLVER
    p = solver_file()
    if not p.is_file():
        raise SolverUnavailable(f"vendor 求解器不在：{p}（见 vendor/wt-missile/VENDOR.md）")
    if verify:
        got = file_sha256(p)
        if got != SOLVER_SHA256:
            raise SolverUnavailable(
                f"vendor 求解器哈希不符：{got}（期望 {SOLVER_SHA256}）。"
                "该目录是只读副本，升级流程见 vendor/wt-missile/VENDOR.md")
    d = str(VENDOR_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        _SOLVER = importlib.import_module("wt_missile")
    except Exception as exc:                                    # noqa: BLE001
        raise SolverUnavailable(f"vendor 求解器导入失败：{type(exc).__name__}: {exc}") from exc
    return _SOLVER


def release_solver() -> None:
    """丢掉本进程缓存的模块句柄（测试用；正常流程不需要）。"""
    global _SOLVER
    _SOLVER = None


def _manifest() -> dict:
    try:
        wt = load_solver()
        path = VENDOR_DIR / "inputs" / "resources" / str(wt.VERSION) / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        return {}


def identity() -> dict:
    """身份块（不跑积分）。进每条记录的 `engine` 与 manifest。"""
    wt = load_solver()
    try:
        rel = str(solver_file().relative_to(VENDOR_DIR.parent.parent))
    except ValueError:                                          # pragma: no cover
        rel = str(solver_file())
    return {
        "solver": "wt-missile",
        "model": str(getattr(wt, "MODEL", "")),
        "version": str(getattr(wt, "VERSION", "")),
        "file": rel,
        "sha256": SOLVER_SHA256,
        "archive_sha256": _manifest().get("archive_sha256"),
        "n_profiles": len(getattr(wt, "PROFILES", ()) or ()),
        "elf_executed": False,
        "formula_basis_elf_sha256": str(getattr(wt, "ELF_SHA256", "")),
    }


def profile(native_name: str, version: str | None = None) -> dict:
    """读一份 blk 参数块。`native_name` 是求解器预设名（如 `cn_pl12`）。"""
    wt = load_solver()
    params, _ident = wt.load_profile(str(native_name), version or VERSION_28)
    return params


def profile_identity(native_name: str, version: str | None = None) -> dict:
    """连同资源出处一起返回（弹池要把它记进产物）。"""
    wt = load_solver()
    _params, ident = wt.load_profile(str(native_name), version or VERSION_28)
    return dict(ident or {})


def supported(native_name: str, version: str | None = None) -> str | None:
    """返回拒绝原因；可算则返回 None。求解器对不支持的型号是**硬拒绝**，不做近似替代。"""
    wt = load_solver()
    return wt.unsupported(profile(native_name, version))


# ---- 内核的阻力/大气子函数：β–γ 平面的派生指标要用，按本模块定位只在这里暴露 ----


def mach_function(mach: float) -> float:
    """内核的 `f(M)`：零升阻力的马赫修正因子（五段式）。

    `β–γ` 平面的 `Q = √(β·γ·F/f)`、`n*`、`R`、`β_eff` 都要用它，而它在内核里是**私有**
    实现（`wt_missile._mach_function`）。本模块是唯一与 vendor 的接触面，所以包在这里，
    业务模块不直接碰下划线函数 —— 内核升级改名时只有这一处要跟着动。
    """
    wt = load_solver()
    fn = getattr(wt, "_mach_function", None)
    if not callable(fn):
        raise SolverUnavailable("内核没有 _mach_function —— 版本变了？见 vendor/wt-missile/VENDOR.md")
    return float(fn(float(mach)))


def atmosphere(alt_m: float) -> tuple:
    """内核的标准大气：返回 `(rho_kg_m3, sound_speed_m_s)`。

    用于把 `β–γ` 的参考工况（高度 + 速度）换成动压 `q` 与马赫数 `M`。
    """
    wt = load_solver()
    fn = getattr(wt, "_atmosphere", None)
    if not callable(fn):
        raise SolverUnavailable("内核没有 _atmosphere —— 版本变了？见 vendor/wt-missile/VENDOR.md")
    rho, sound = fn(float(alt_m))
    return float(rho), float(sound)


def effective_cx_aoa(params: dict) -> float:
    """内核**实际生效**的 `CxAoA`：blk 缺省兜底 `KERNEL_CX_AOA_DEFAULT`，再按
    `applyWingAreaMultToCxAoA` 乘 `wingAreaMult²`（`wt_missile.py:780-782` 的逐行复刻）。

    为什么需要它：`_apply()` 施加 `cxaoa_scale` 时拿到的只有**原始 blk 字典**，
    而内核读的是「兜底 + 乘 wingAreaMult²」之后的**有效值**。用它把有效值算准，
    再把 `applyWingAreaMultToCxAoA` 一并关掉，内核就不会第二次乘。
    正确性由 `tests/test_solver_api.py` 对着 `body_aero()` 逐弹对拍守住。
    """
    raw = params.get("CxAoA")
    if not isinstance(raw, (int, float)):
        raw = KERNEL_CX_AOA_DEFAULT
    if params.get("applyWingAreaMultToCxAoA"):
        w = params.get("wingAreaMult")
        if isinstance(w, (int, float)):
            raw = float(raw) * float(w) ** 2
    return float(raw)


def body_aero(native_name: str, version: str | None = None) -> tuple:
    """内核实际使用的 `(cx_aoa, CyK)`，直接问内核要。

    这两个量在 11 型 blk 里**都不存在**，内核分别兜底 `9.0` / `2.2`
    （`wt_missile.py:780`、`:760`），而且 `cx_aoa` 还会按 `applyWingAreaMultToCxAoA`
    乘 `wingAreaMult²`。与其在业务代码里把这几条规则抄一遍（抄错也不报错），
    不如构造一次内核的 `Body` 把值读出来 —— 规则只有内核一处权威。
    """
    wt = load_solver()
    body = wt.Body(dict(profile(native_name, version)))
    return float(body.cx_aoa), float(body.cy)


# --------------------------------------------------------------------- 场景装配


def scenario_dict(scene: Scene, *, missile: str, tier: str = "standard") -> dict:
    """`Scene` + 基准弹 → 求解器的高级场景 dict。

    三个刻意的选择：
      * `sample_period_s=None` —— 逐物理步输出；给显式周期会让求解器放弃 C 快路径；
      * `step_policy="fixed"` + 客户端时钟 —— 同上，是快路径条件；
      * `fastmode = (tier == "fast")` —— 档位只影响算术路径，不影响物理。

    `Scaling` 不参与本 dict：乘数走 `load_profile` 那条路施加（见 `run`）。
    """
    _raise_scene(scene)
    raw = {
        "schema_version": 1,
        "label": f"wtgame/{tier}/{missile}",
        "missile": str(missile),
        "version": VERSION_28,
        "duration_s": float(scene.duration_s),
        "dt_s": float(scene.dt_s or SOLVER_DT),
        "step_policy": "fixed",
        "fastmode": tier == "fast",
        "sample_period_s": None,
        "observation": {"mode": str(scene.observation)},
        "launch": {"position_m": [float(x) for x in scene.launch_position_m],
                   "velocity_m_s": [float(x) for x in scene.launch_velocity_m_s]},
        "target": {"position_m": [float(x) for x in scene.target_position_m],
                   "velocity_m_s": [float(x) for x in scene.target_velocity_m_s],
                   "collision_radius_m": float(scene.hit_radius_m)},
        "wind_m_s": [float(x) for x in (scene.wind_m_s or (0.0, 0.0, 0.0))],
        "ground_height_m": float(scene.ground_height_m),
        "proximity_fuse": bool(scene.proximity_fuse),
    }
    if scene.maneuvers:
        raw["target"]["maneuvers"] = [
            {"time_s": float(t), "acceleration_m_s2": [float(x) for x in a]}
            for t, a in scene.maneuvers]
    return raw


def _raise_scene(scene: Scene) -> None:
    bad = scene.check()
    if bad:
        raise ValueError("场景不自洽：" + "；".join(bad))


# --------------------------------------------------------------------- 乘数施加


def _patch_profile(p, updates: dict):
    """按 key 名**就地**改写 profile（嵌套 dict / list 全走一遍）。

    求解器的 profile 是嵌套 dict，`force`/`CxK` 可能出现多次；这里命中所有同名标量叶，
    与求解器自己的解析顺序一致（只乘一次，不会累积 —— 因为每次 `load_profile` 都重新解析）。

    ⚠ **`walk()` 只能改"已经存在的键"**（它遍历的是 `node.items()`）。所以 blk 里根本没有的
    字段（`CxAoA` 就是：11 型一个都没有）必须走最后的"补缺"分支显式写进**顶层** ——
    否则注入是**静默 no-op**：不报错、不生效，结果看起来完全正常。
    这个坑曾经真的踩过（β–γ 扫描的 γ 轴在图上完全不动，逐位相同才发现）。
    """
    if not updates:
        return p

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in updates and not isinstance(v, dict):
                    node[k] = updates[k]
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(p)
    for k, v in updates.items():                 # blk 缺失的键：补在顶层（内核就从顶层读）
        if k not in p:
            p[k] = v
    return p


def _apply(wt, orig, scaling: Scaling | None):
    """返回一个替代 `load_profile` 的闭包；乘数全为 1 时直接透传原函数。"""
    s, cx, aoa = ((1.0, 1.0, 1.0) if scaling is None
                  else (float(scaling.thrust_scale), float(scaling.cx_scale),
                        float(getattr(scaling, "cxaoa_scale", 1.0))))
    if abs(s - 1.0) < 1e-15 and abs(cx - 1.0) < 1e-15 and abs(aoa - 1.0) < 1e-15:
        return orig

    def complete(name, version=None):
        params, ident = orig(name, version or wt.VERSION)
        upd = {}
        if abs(s - 1.0) >= 1e-15:
            for k in ("force", "force1"):
                v = params.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    upd[k] = float(v) * s
        if abs(cx - 1.0) >= 1e-15:
            v = params.get("CxK")
            if isinstance(v, (int, float)) and v > 0:
                upd["CxK"] = float(v) * cx
        if abs(aoa - 1.0) >= 1e-15:
            # `CxAoA` 在 11 型 blk 里**都不存在**（内核兜底 9.0，见 docs/BETA-GAMMA.md §2.2），
            # 但 `_patch_profile` 是直接赋值 `node[k] = v`，能新增 blk 没有的键。
            # 写进去的是**有效值**，所以同时关掉 `applyWingAreaMultToCxAoA`（否则内核再乘一次
            # wingAreaMult²）。11 型实测该开关全是 False，这一步对它们是恒等的。
            upd["CxAoA"] = effective_cx_aoa(params) * aoa
            if params.get("applyWingAreaMultToCxAoA"):
                upd["applyWingAreaMultToCxAoA"] = False
        if not upd:
            return params, ident
        return _patch_profile(params, upd), ident

    return complete


# --------------------------------------------------------------------- 输出归一


def _f(x):
    """float 化；缺失/非有限 → None（**刻意不产出 nan** —— nan 会被读成"算出来是 nan"）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def trajectory(rows) -> tuple:
    """求解器的逐采样行 → 精简轨迹（键名固定，供弹道类图与产物用）。

    ⚠ 坐标口径（画 3D/俯视图必须知道）：**水平面是 `(x, z)`**，对应内核的
    `missile_x_m` / `missile_z_m`（`heading 0 = +x`、`90 = +z`）；**`y` 是高度**
    （`missile_y_m`）。`t?` 前缀的是**目标**同一时刻的位置 —— 一个想定要同时画
    弹与目标两条航迹，所以两组都在这一份精简行里出，不再各算一遍（曾想让出图
    自己积分目标运动，那样画出来的轨迹和求解器真正拦的那条不是同一条）。
    """
    out = []
    for r in rows:
        out.append({
            "t": _f(r.get("time_s")), "x": _f(r.get("missile_x_m")),
            "y": _f(r.get("missile_y_m")), "z": _f(r.get("missile_z_m")),
            "v": _f(r.get("speed_m_s")),
            "mass": _f(r.get("mass_kg")), "thrust": _f(r.get("thrust_N")),
            "range": _f(r.get("range_m")),
            "tx": _f(r.get("target_x_m")), "ty": _f(r.get("target_y_m")),
            "tz": _f(r.get("target_z_m")),
        })
    return tuple(out)


def backend_of(summary: dict) -> str:
    """算术后端：`compiled-c` / `python-legacy`；标准档没有这个键。"""
    fm = (summary or {}).get("fastmode") or {}
    return str(fm.get("backend") or "") if fm.get("enabled") else ""


def fallback_of(summary: dict) -> str | None:
    fm = (summary or {}).get("fastmode") or {}
    return fm.get("compiled_fallback_reason") or fm.get("fallback_reason") or None


def shot_from(scene: Scene, summary: dict, rows, *, tier: str = "standard",
              want_rows: bool = False) -> Shot:
    """求解器 `(summary, rows)` → `Shot`。**所有字段语义都在这里定型。**"""
    if not rows:
        return Shot(ok=False, error="求解器没有返回任何轨迹行")
    event = str(summary.get("terminal_event") or "")
    hit = event in HIT_EVENTS
    min_sep = summary.get("minimum_separation_until_event_m", math.nan)
    try:
        min_sep = float(min_sep)
    except (TypeError, ValueError):
        min_sep = math.nan
    if hit and scene.hit_radius_m > 0.0 and math.isfinite(min_sep) \
            and min_sep > scene.hit_radius_m:
        hit = False                                   # 近炸半径外不算命中
    t_end = _f(summary.get("time_s")) or math.nan

    thrusts = [r.get("thrust_N") or 0.0 for r in rows]
    speeds = [float(r.get("speed_m_s") or 0.0) for r in rows]
    masses = [float(r.get("mass_kg") or 0.0) for r in rows]
    powered = [i for i, t in enumerate(thrusts) if t and t > 0.0]
    i_burn = powered[-1] if powered else 0

    backend = backend_of(summary) or ("python-standard" if tier == "standard" else "")
    return Shot(
        ok=True, event=event, hit=hit, t_end=t_end,
        t_hit=(t_end if hit else math.nan),
        miss_m=min_sep,
        max_alt_m=max((_f(r.get("missile_y_m")) or 0.0) for r in rows),
        v_impact=_f(summary.get("final_speed_m_s")) or math.nan,
        dv_measured=speeds[i_burn] - speeds[0],
        t_burnout=(_f(rows[i_burn].get("time_s")) or math.nan),
        m_launch=masses[0], m_dry=min(masses),
        backend=backend,
        fallback_reason=fallback_of(summary),
        resource=f"wt-missile/{VERSION_28}+{backend or 'unknown'}",
        rows=(trajectory(rows) if want_rows else ()),
    )


# --------------------------------------------------------------------- 运行


def run(scene: Scene, *, missile: str, scaling: Scaling | None = None,
        tier: str = "standard", want_rows: bool = False) -> Shot:
    """跑一次。**失败不抛异常**，返回 `Shot(ok=False, error=…)`，由调用方决定怎么处置。

    `scaling=None` ⇒ 标称（不施加任何乘数）。
    """
    try:
        wt = load_solver()
    except SolverUnavailable as exc:
        return Shot(ok=False, error=str(exc))
    _raise_scene(scene)
    raw = scenario_dict(scene, missile=missile, tier=tier)
    orig = wt.load_profile
    wt.load_profile = _apply(wt, orig, scaling)
    try:
        # `python_simulate` 是两档的统一入口：fastmode=False 直接走 scene_simulate，
        # fastmode=True 先试 compiled_simulate，缺编译器时自行回退并给出原因。
        _scenario, summary, rows = wt.python_simulate(raw)
    except Exception as exc:                                    # noqa: BLE001
        return Shot(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        wt.load_profile = orig
    return shot_from(scene, summary, rows, tier=tier, want_rows=want_rows)

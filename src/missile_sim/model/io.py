# -*- coding: utf-8 -*-
"""**模型层 1：输入层**——blk 参数统计 + 用户条件 → `NativeCase`。

“采购原材料”：把游戏数据（权威 blkx）与用户意图，变成模型层唯一接受的输入规格。

两个参考面积**严格分离**（本项目踩过两次的坑，勿再混）：
  * 弹道系数 BC 与阻力用**迎面面积** `SD = π(d/2)²`；
  * 升力用 `SL = 0.3·d·L·wingAreaMult`（与原生 `configure_properties` 同一公式）。

(ΔV, BC) → 原生乘数（**解析、无迭代**；ΔV 是真空等效增速，不考虑衰减）：
  s        = ΔV / ΔV_blk
  cx_scale = m_dry / (BC · SD · CxK_blk)

本层的 `load_blk_profile()` 复用 `scripts/missile_metrics.py` 的权威公式，
**不在此另写一套 metrics**。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from .constants import NATIVE_PROFILES, ROOT, VERSION_28
from .native import NativeCase

# blk 注入的缓存：包内只有 9 型，缺的（Derby / R-Darter）用我们自己的权威 blkx 补。
_EXTERNAL_PROFILES: dict = {}


def load_blk_profile(native_name: str) -> dict | None:
    """读权威 blkx 并解析成原生 profile dict（带缓存）；取不到返回 None。

    依据（`results/native_injection_probe.json`，已实证）：
      * 原生参数全经内存块注入 ELF，ELF 是 (状态, 参数块) 的纯函数；
      * 唯一闸门是 `resources.load_profile` 的 manifest/SHA-256 校验；
      * 我们的 blkx 与原生 `parse_blk` 的叶子路径集合完全相同（423/423）。
    """
    if native_name in _EXTERNAL_PROFILES:
        return _EXTERNAL_PROFILES[native_name]
    try:
        scripts = str(ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import missile_metrics as mm                    # noqa: PLC0415
        fname = None
        for _short, fn, _label in mm.MISSILE_FILES:
            if fn.replace(".blkx", "") == native_name:
                fname = fn
                break
        if fname is None:
            return None
        rk = mm.load_rocket(mm.WORK, fname)
        if not rk:
            return None
        _EXTERNAL_PROFILES[native_name] = rk
        return rk
    except Exception:                                   # noqa: BLE001
        return None


def native_name_of(blkx_file_or_name: str) -> str:
    """`us_aim_120a.blkx` / `PL-12` → 原生 profile 名。"""
    f = str(blkx_file_or_name)
    for suffix in (".blkx", ".blk"):
        if f.endswith(suffix):
            f = f[: -len(suffix)]
    return f


def can_run_native(name: str) -> bool:
    """该型能不能跑原生：包内有，**或**我们有权威 blkx 可注入。

    ⚠ 不要只查 `NATIVE_PROFILES`——注入能力让 Derby / R-Darter 也能跑。
    """
    if name in NATIVE_PROFILES[VERSION_28]:
        return True
    return load_blk_profile(name) is not None


# --------------------------------------------------------------------- 参数统计

def blk_stats(tag: str | None = None, native_name: str | None = None) -> dict:
    """从 blk 统计一型的引擎/几何参数（权威口径 = `missile_metrics.metrics()`）。

    返回：('native_name', 'file', 'dv', 'bc', 'dry', 'sd_m2', 'sl_m2', 'cxk', 'caliber_m', 'length_m')
    """
    import missile_metrics as mm                        # noqa: PLC0415
    from .native import NATIVE_PROFILES as _NP

    name = native_name or ""
    fname = None
    for short, fn, _label in mm.MISSILE_FILES:
        if (native_name and (fn.replace(".blkx", "") == native_name or short == native_name)):
            fname = fn
            break
    if fname is None:
        raise ValueError(f"blk 里没有 {native_name!r}（可用：" + '、'.join(fn for _, fn, _ in mm.MISSILE_FILES) + "）")
    rk = mm.load_rocket(tag or mm.WORK, fname)
    if not rk:
        raise ValueError("读不到 " + fname + "（tag=" + str(tag or mm.WORK) + "）")
    mt = mm.metrics(rk)
    if not mt:
        raise ValueError(fname + " 的 metrics() 字段不全")
    d = float(mt["caliber_m"])
    sd = math.pi * (d / 2.0) ** 2                                  # 迎面面积：BC 用它
    sl = 0.3 * d * float(rk["length"]) * float(rk["wingAreaMult"])  # 升力面积：升力用它
    return {"native_name": fname.replace(".blkx", ""), "file": fname, "tag": tag or mm.WORK,
            "dv": float(mt["dv"]), "bc": float(mt["bc"]), "dry": float(mt["dry"]),
            "sd_m2": sd, "sl_m2": sl, "cxk": float(mt["CxK"]),
            "caliber_m": d, "length_m": float(rk["length"])}


# --------------------------------------------------------------------- 燃烧级 / 真空 ΔV

def module_stages(prof: dict) -> list:
    """blk profile → [(m_start, m_end, force, time_fire), ...]（**逐级**，漏级会让 ΔV_blk 偏小）。

    ⚠ 两级弹的 `massEnd` 只是第一级结束质量，末质量在 `massEnd1`；
    只取第一级会把 PL-12 的 ΔV_blk 算成 536.9（真值 932.6），推力乘数随之放大 1.74 倍。
    """
    stages, m = [], float(prof["mass"])
    for suffix in ("", "1"):
        f = prof.get("force" + suffix)
        tf = prof.get("timeFire" + suffix)
        me = prof.get("massEnd" + suffix)
        if not f or not tf or me is None:
            continue
        stages.append((m, float(me), float(f), float(tf)))
        m = float(me)
    return stages


def vacuum_dv(stages, scale: float = 1.0) -> float:
    """齐奥尔科夫斯基真空 ΔV（任一段数），用于校核"原生是否按 s 线性给出 ΔV"。"""
    total = 0.0
    for m_start, m_end, force, time_fire in stages:
        dm = float(m_start) - float(m_end)
        if dm <= 0 or time_fire <= 0 or force <= 0:
            continue
        ve = float(force) * float(scale) * float(time_fire) / dm
        total += ve * math.log(float(m_start) / float(m_end))
    return total


def scale_for_dv(dv_target: float, dv_blk: float) -> float:
    """ΔV（真空等效增速）→ 推力乘数。`s = ΔV / ΔV_blk`，解析、无迭代。"""
    if dv_blk <= 0:
        raise ValueError("标准弹 ΔV_blk 非法")
    return dv_target / dv_blk


def cx_scale_for_bc(bc_target: float, dry_mass: float, sd_m2: float, cxk_blk: float) -> float:
    """目标 BC → CxK 乘数（精确解析）。

    BC = m_dry / (CxK · SD)  ⇒  CxK_used = m_dry / (BC · SD)；乘数 = CxK_used / CxK_blk。
    ⚠ `sd_m2` 必须是**迎面面积** π(d/2)²，不是升力面积 0.3·d·L·wam。
    """
    if bc_target <= 0 or sd_m2 <= 0 or cxk_blk <= 0 or dry_mass <= 0:
        raise ValueError("BC 反解参数非法")
    return dry_mass / (bc_target * sd_m2 * cxk_blk)


def scales_for(case_dv: float, case_bc: float, prof, sd_m2: float | None = None) -> tuple:
    """(ΔV, BC) → (推力乘数, CxK 乘数)。

    **仅供预览/诊断**：真正的乘数由模型层用 profile 自己的 CxK/干重/迎面面积现算。
    """
    if sd_m2 is None:
        d = float(prof.caliber_m)
        sd_m2 = math.pi * (d / 2.0) ** 2
    return (scale_for_dv(case_dv, prof.dv),
            cx_scale_for_bc(case_bc, prof.dry_mass, sd_m2, prof.cxk))


def scale_tag(case_dv: float, case_bc: float, prof, sd_m2: float | None = None) -> dict:
    """把"外部的 (ΔV, BC)"与"原生的 (推力乘数, CxK 乘数)"一起记进产物，便于复核。"""
    ts, cs = scales_for(case_dv, case_bc, prof, sd_m2)
    return {"dv_target": float(case_dv), "bc_target": float(case_bc),
            "dv_blk": float(prof.dv), "bc_blk": float(prof.bc),
            "thrust_scale": float(ts), "cx_scale": float(cs),
            "cxk_used": float(prof.cxk * cs)}


# --------------------------------------------------------------------- 用户条件 → NativeCase

def build_case(cfg, *, missile: str | None = None, dv: float = 0.0, bc: float = 0.0,
               **over) -> NativeCase:
    """由 `MissileConfig`（含已解析的标准弹）+ 用户条件构造原生工况（唯一入口）。

    `cfg` 提供场景（初始条件/敌机设置）与 Pro 运行参数；`dv`/`bc` 是外部给的 (ΔV, BC)，
    乘法用的参考量由模型层**从该型 profile 自己**算，这里不碰。
    """
    prof = getattr(cfg, "profile", None)
    name = missile
    if name is None:
        name = native_name_of(str(getattr(prof, "file", "") or ""))
    if not can_run_native(name):
        raise ValueError(
            f"原生包没有 {name!r}，且注入源里也找不到它的 blkx —— 无法执行原生仿真")
    scen = cfg.scenario
    kw = dict(
        missile=name, version=VERSION_28,
        range_m=float(scen.range), alt_m=float(scen.alt),
        target_alt_m=(None if scen.target_alt is None else float(scen.target_alt)),
        vm0=float(scen.vm0), vt=float(scen.vt),
        dv_target=float(dv), bc_target=float(bc),
        dt=float(getattr(cfg, "pro_dt", 0.01)),
        duration_s=float(getattr(cfg, "pro_duration_s", 150.0)),
        observation_mode=str(getattr(cfg, "pro_observation", "ideal")),
    )
    kw.update(over)
    return NativeCase(**kw)

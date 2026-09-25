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
from dataclasses import replace
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


def _missile_files() -> list:
    """权威 blkx 表 `missile_metrics.MISSILE_FILES` = [(短名, 文件名, 标签), ...]。"""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import missile_metrics as mm                          # noqa: PLC0415
    return list(mm.MISSILE_FILES)


def short_name_of(native_name: str) -> str | None:
    """原生 profile 名 → 标准弹池短名（`cn_pl12` → `PL-12`）；查不到返回 None。

    ⚠ Flash 后端**必须**经此回到池里的短名：完整参数（质量剖面/CxK/干重/引信/寿命/
    高抛/增益表）只有池里有；原生包只认 profile 名。
    """
    want = native_name_of(native_name)
    for short, fn, _label in _missile_files():
        if fn.replace(".blkx", "") == want:
            return short
    return None


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


# --------------------------------------------------------------------- 结构化输入（引擎契约）

# 权威 blkx 的完整 `rocket` 块（**不是**弹池 JSON）：PID 系数、力臂、惯量缩放、TVC 这些
# 只有 blk 里有。第三方模型（比如开源拿到的更新版）需要的正是这些字段。
def rocket_block(tag: str | None = None, native_name: str | None = None) -> dict:
    """读某型的完整 blkx `rocket` 块（未加工）。取不到抛 `ValueError`。"""
    import missile_metrics as mm                            # noqa: PLC0415

    name = native_name or ""
    fname = None
    for short, fn, _label in mm.MISSILE_FILES:
        if name and (fn.replace(".blkx", "") == name or short == name):
            fname = fn
            break
    if fname is None:
        raise ValueError(f"blk 里没有 {native_name!r}（可用："
                         + '、'.join(fn for _, fn, _ in mm.MISSILE_FILES) + "）")
    rk = mm.load_rocket(tag or mm.WORK, fname)
    if not rk:
        raise ValueError(f"读不到 {fname}（tag={tag or mm.WORK}）")
    return rk


def _pid_rows(ga: dict) -> tuple:
    """`guidanceAutopilot` 的 PID：优先 `pid0…N` 时间表，否则空（调用方用扁平系数）。"""
    from .spec import PidRow                                # noqa: PLC0415

    rows = []
    for k, v in ga.items():
        if k.startswith("pid") and isinstance(v, dict) and "time" in v:
            rows.append(PidRow(time=float(v["time"]), prop=float(v.get("prop", 0.0)),
                               intg=float(v.get("intg", 0.0)), diff=float(v.get("diff", 0.0)),
                               intg_lim=float(v.get("intgLim", 1.0))))
    rows.sort(key=lambda r: r.time)
    return tuple(rows)


def _gain_table(ga: dict, prefix: str) -> tuple:
    """把 `timeToGain0/1`、`timeToHitToGain0/1/2` 收成按 x 排序的 ((x, y), ...)。"""
    out = []
    for k, v in ga.items():
        if k.startswith(prefix) and k[len(prefix):].isdigit() and isinstance(v, (list, tuple)):
            if len(v) >= 2:
                out.append((float(v[0]), float(v[1])))
    out.sort()
    return tuple(out)


def normalize_blk_profile(rk: dict) -> dict:
    """完整 blkx `rocket` 块 → 结构化参数块（`spec.py` 的 dataclass）。

    **这是唯一一处把游戏字段名翻译成引擎字段名的地方**：换模型只换引擎，
    字段翻译不变；游戏改字段名只改这里。
    """
    from .spec import (                                     # noqa: PLC0415
        AeroCoeffs, Autopilot, Fuse, GainTables, Geometry, Limits, LoftConfig, MassProfile,
    )

    def f(node, key, default=None):
        v = (node or {}).get(key, None)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    g = (rk.get("guidance") or {})
    ga = (g.get("guidanceAutopilot") or {})
    geo = Geometry(
        caliber_m=f(rk, "caliber", 0.0),
        length_m=f(rk, "length", 0.0),
        wing_area_mult=f(rk, "wingAreaMult", 1.0),
        dist_from_cm_to_stab=f(rk, "distFromCmToStab", 0.0),
        inertia_scale=f(rk, "inertiaScale", 1.0),
    )
    mass = MassProfile(
        launch=f(rk, "mass", 0.0), mid=f(rk, "massEnd", 0.0), dry=f(rk, "massEnd1", None)
        if rk.get("massEnd1") is not None else f(rk, "massEnd", 0.0),
        force=f(rk, "force", 0.0), time_fire=f(rk, "timeFire", 0.0),
        force1=f(rk, "force1", 0.0), time_fire1=f(rk, "timeFire1", 0.0),
        fire_delay=f(rk, "fireDelay", 0.0),
        two_stage=bool(rk.get("massEnd1") is not None and rk.get("force1")),
    )
    aero = AeroCoeffs(
        cxk=f(rk, "CxK", 0.0),
        cyk=f(rk, "CyK", 2.2),
        cy_max_aoa=f(rk, "CyMaxAoA", 1.0),
        cx_aoa=f(rk, "CxAoA", 9.0),
        use_cxi_mach=bool(rk.get("useCxiMach", True)),
        apply_wing_area_mult_to_cx_aoa=bool(rk.get("applyWingAreaMultToCxAoA", False)),
    )
    autopilot = Autopilot(
        req_accel_max_g=f(ga, "reqAccelMax", f(ga, "propNavAccelMax", 35.0)),
        fins_lat_accel_g=f(rk, "finsLatAccel"),
        fins_aoa_hor=f(rk, "finsAoaHor"),
        fins_aoa_ver=f(rk, "finsAoaVer"),
        base_ind_speed=f(ga, "baseIndSpeed", 1800.0),
        prop_nav_mult=f(ga, "propNavMult", 4.0),
        vel_frame_reference=bool(ga.get("velFrameReference", True)),
        limit_aoa=bool(ga.get("limitAoa", False)),
        aoa_max_deg=f(ga, "aoaMax", 0.0),
        time_out_s=f(ga, "timeOut"),
        pid_rows=_pid_rows(ga),
        kp=f(ga, "accelControlProp"),
        ki=f(ga, "accelControlIntg"),
        kd=f(ga, "accelControlDiff"),
        i_limit=f(ga, "accelControlIntgLim", 1.0),
    )
    t = ga.get("rangeToLoftElevation")
    loft = LoftConfig(
        enabled=bool(ga.get("loftEnabled", False)),
        elevation_deg=f(ga, "loftElevation", 0.0),
        target_elevation_deg=f(ga, "loftTargetElevation", -89.9),
        target_omega_max_dps=f(ga, "loftTargetOmegaMax", 0.0),
        angle_to_accel_mult=f(ga, "loftAngleToAccelMult", 0.0),
        range_to_loft_elevation=tuple(float(x) for x in t) if isinstance(t, (list, tuple)) and len(t) == 4 else (),
    )
    hit = _gain_table(ga, "timeToHitToGain")
    tim = _gain_table(ga, "timeToGain")
    gains = GainTables(time_gain=tim, hit_gain=hit,
                       source=("timeToHitToGain" if hit else ("timeToGain" if tim else "default")))
    limits = Limits(time_life_s=f(rk, "timeLife", 120.0),
                    max_distance_m=f(rk, "maxDistance"), mach_max=f(rk, "machMax"),
                    load_factor_max_g=f(rk, "loadFactorMax"))
    pf = (rk.get("proximityFuse") or {})
    fuse = Fuse(has_proximity_fuse=bool(rk.get("hasProximityFuse", False)),
                radius_m=f(pf, "radius", 0.0), time_out_s=f(pf, "timeOut"))
    return {"geometry": geo, "mass": mass, "aero": aero, "autopilot": autopilot,
            "loft": loft, "gains": gains, "limits": limits, "fuse": fuse}


def build_inputs(cfg, *, missile: str | None = None, dv: float = 0.0, bc: float = 0.0,
                 standard=None, **over) -> "EngineInputs":
    """**引擎契约的唯一构造入口**：权威 blkx + 标准弹 + 用户条件 → `EngineInputs`。

    这里做完全部 (ΔV, BC) 映射（`dv_blk` / `bc_blk` / `thrust_scale` / `cx_scale` / `cxk_used`），
    引擎**不得**重算——今天 `native.py` 与 `flash.py` 各算一遍，口径分叉就是静默数值错误。
    """
    from .spec import EngineInputs                            # noqa: PLC0415

    prof = getattr(cfg, "profile", None)
    name = missile
    if name is None:
        name = native_name_of(str(getattr(prof, "file", "") or ""))
    std_name = standard if standard is not None else str(getattr(prof, "name", "") or "")
    tag = str(getattr(cfg.standard, "tag", "") or "")
    rk = rocket_block(tag or None, name)
    pars = normalize_blk_profile(rk)
    geo, mass = pars["geometry"], pars["mass"]

    stages = module_stages(rk)                                # 逐级；漏级会让 ΔV_blk 偏小
    if not stages:
        raise ValueError(f"{name} 的 blkx 缺质量/推力剖面，无法算 ΔV_blk")
    dry = stages[-1][1]
    dv_blk = vacuum_dv(stages)
    bc_blk = dry / (float(rk["CxK"]) * geo.sd_m2)
    dv_t, bc_t = float(dv), float(bc)
    thrust_scale = 1.0 if not dv_t else scale_for_dv(dv_t, dv_blk)
    cx_scale = (1.0 if not bc_t
                else cx_scale_for_bc(bc_t, dry, geo.sd_m2, float(rk["CxK"])))

    scen = cfg.scenario
    kw = dict(
        missile=name, version=VERSION_28, standard=std_name, tag=tag,
        profile_hash=(prof.profile_hash() if prof is not None and hasattr(prof, "profile_hash") else ""),
        **pars,
        dv_target=dv_t, bc_target=bc_t, dv_blk=dv_blk, bc_blk=bc_blk,
        thrust_scale=thrust_scale, cx_scale=cx_scale, cxk_used=float(rk["CxK"]) * cx_scale,
        range_m=float(scen.range), alt_m=float(scen.alt),
        target_alt_m=(None if scen.target_alt is None else float(scen.target_alt)),
        vm0=float(scen.vm0), vt=float(scen.vt),
        dt=float(getattr(cfg, "pro_dt", 0.01)),
        duration_s=float(getattr(cfg, "pro_duration_s", 150.0)),
        observation_mode=str(getattr(cfg, "pro_observation", "ideal")),
    )
    kw.update(over)
    inp = EngineInputs(**kw)
    bad = inp.check()
    if bad:
        raise ValueError(f"{name} 的引擎输入不自洽：" + "；".join(bad))
    return inp


# --------------------------------------------------------------------- 用户条件 → NativeCase

def inputs_from_case(case, *, standard: str | None = None, tag: str | None = None,
                     profile_hash: str = "", pool_path=None, **over) -> "EngineInputs":
    """`NativeCase` + **标准弹池** → `EngineInputs`（不经过 `MissileConfig`）。

    为什么要有它：引擎契约的构造有两类调用方——
      * `build_inputs(cfg, …)`：从配置/CLI 来（有 `cfg.profile` 与场景）；
      * 本函数：从**已经成型的 `NativeCase`** 来（扫描器、单测、脚本）。
    两条都收敛到同一套映射（`normalize_blk_profile` + 齐奥尔科夫斯基 + 迎面面积反解），
    所以"乘数只有一处算法"这条纪律对两者都成立。

    `standard` 不给时由原生名反查弹池短名；池里没有该型则参数块留空（`check()` 会报）。
    """
    short = standard if standard is not None else (short_name_of(case.missile) or "")
    std_tag = tag
    if short:
        try:
            from ..standard import resolve as _resolve    # noqa: PLC0415
            prof = _resolve(short, pool_path=pool_path, tag=(tag or None))
            std_tag = prof.tag or tag
            profile_hash = profile_hash or prof.profile_hash()
            # 池只给"标准弹"级别的字段；完整参数块仍以权威 blkx 为准
        except Exception:                                 # noqa: BLE001
            pass
    rk = rocket_block(std_tag or None, case.missile)
    pars = normalize_blk_profile(rk)
    geo = pars["geometry"]
    stages = module_stages(rk)
    if not stages:
        raise ValueError(f"{case.missile} 的 blkx 缺质量/推力剖面，无法算 ΔV_blk")
    dry = stages[-1][1]
    dv_blk = vacuum_dv(stages)
    cxk_blk = float(rk["CxK"])
    bc_blk = dry / (cxk_blk * geo.sd_m2)
    dv_t, bc_t = float(case.dv_target or 0.0), float(case.bc_target or 0.0)
    cx_scale = 1.0 if not bc_t else cx_scale_for_bc(bc_t, dry, geo.sd_m2, cxk_blk)

    kw = case.engine_inputs(
        standard=short, tag=std_tag or "", profile_hash=profile_hash,
        **pars,
        dv_blk=dv_blk, bc_blk=bc_blk,
        thrust_scale=(1.0 if not dv_t else scale_for_dv(dv_t, dv_blk)),
        cx_scale=cx_scale, cxk_used=cxk_blk * cx_scale,
    )
    kw = replace(kw, **over) if over else kw
    bad = kw.check()
    if bad:
        raise ValueError(f"{case.missile} 的引擎输入不自洽：" + "；".join(bad))
    return kw


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

# -*- coding: utf-8 -*-
"""模型层 1（输入层）自检：blk 参数统计、参考面积分离、用户条件 → NativeCase。

**两个参考面积是重点**：BC/阻力用迎面面积 `SD=π(d/2)²`，升力用 `SL=0.3·d·L·wam`。
混用会导致乘数与 ΔV_blk 双双算错（历史事故：乘数 0.8529 应为 1.0、ΔV_blk 536.9 应为 932.6）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from missile_sim import standard
from missile_sim.config import apply_standard, load_config, s_ref
from missile_sim.model import io as mio
from missile_sim.model.constants import NATIVE_PROFILES, ROOT, VERSION_28

POINTS = ROOT / "results" / "missile_points.json"
PACKAGE_PROFILES = NATIVE_PROFILES[VERSION_28]


def _points():
    doc = json.loads(POINTS.read_text(encoding="utf-8"))
    rows = doc["missiles"] if isinstance(doc, dict) and "missiles" in doc else doc
    return {r["label"]: r for r in rows}


def _our_pool_profiles():
    """我们 11 弹池对应的原生 profile 名（**不是**包内清单：包内还有 R-73/RVV-AE，我们没这两型）。"""
    import missile_metrics as mm
    return tuple(fn.replace(".blkx", "") for _s, fn, _l in mm.MISSILE_FILES)


def _datamine_available() -> bool:
    return mio.load_blk_profile("cn_pl12") is not None


# --------------------------------------------------------------------- 参数统计

def test_blk_stats_matches_authoritative_points_all_11():
    """`blk_stats` 的 ΔV/BC 必须与权威 `missile_points.json` **逐值一致（11/11）**。"""
    if not _datamine_available():
        return
    pts = _points()
    seen = 0
    for short in pts:
        st = mio.blk_stats(native_name=short)
        ref = pts[short]
        assert st["dv"] == pytest.approx(ref["dv"], rel=1e-9), short
        assert st["bc"] == pytest.approx(ref["bc"], rel=1e-9), short
        assert st["dry"] == pytest.approx(ref["dry"], rel=1e-9), short
        seen += 1
    assert seen == 11, f"应覆盖 11 型，实际 {seen}"


def test_blk_stats_accepts_native_name_and_blkx_name():
    if not _datamine_available():
        return
    a = mio.blk_stats(native_name="cn_pl12")
    b = mio.blk_stats(native_name="PL-12")
    assert a["dv"] == b["dv"] and a["native_name"] == b["native_name"] == "cn_pl12"


def test_blk_stats_rejects_unknown():
    with pytest.raises(ValueError):
        mio.blk_stats(native_name="no_such_missile")


def test_two_reference_areas_are_not_mixed():
    """迎面面积（BC 用）与升力面积（升力用）必须是两个不同的量，且与各自定义一致。"""
    if not _datamine_available():
        return
    for name in _our_pool_profiles():
        prof = mio.load_blk_profile(name)
        st = mio.blk_stats(native_name=name)
        d, L, wam = float(prof["caliber"]), float(prof["length"]), float(prof["wingAreaMult"])
        assert st["sd_m2"] == pytest.approx(math.pi * (d / 2.0) ** 2), name
        assert st["sl_m2"] == pytest.approx(0.3 * d * L * wam), name
        assert st["sd_m2"] != pytest.approx(st["sl_m2"]), name


def test_pl12_reference_areas_numeric():
    """PL-12 的两个面积写死核对（口径变了会立刻暴露）。"""
    if not _datamine_available():
        return
    st = mio.blk_stats(native_name="cn_pl12")
    assert st["sd_m2"] == pytest.approx(0.032365, abs=1e-6)     # π(0.203/2)²
    assert st["sl_m2"] == pytest.approx(0.431245, abs=1e-5)     # 0.3·0.203·3.934·1.8


def test_pool_s_ref_matches_blk_sd():
    """池子里的 `s_ref` 必须就是迎面面积（与 `blk_stats` 一致）；它绝不该等于升力面积。"""
    if not _datamine_available():
        return
    for name in ("PL-12", "120A", "MICA"):
        cfg = load_config()
        cfg.standard.name = name
        apply_standard(cfg)
        st = mio.blk_stats(native_name=name)
        assert s_ref(cfg) == pytest.approx(st["sd_m2"], rel=1e-12), name
        assert s_ref(cfg) < st["sl_m2"], f"{name}: s_ref 应是较小的迎面面积"


# --------------------------------------------------------------------- 燃烧级与 ΔV

def test_module_stages_keeps_second_stage():
    if not _datamine_available():
        return
    st = mio.module_stages(mio.load_blk_profile("cn_pl12"))
    assert len(st) == 2
    assert (st[0][0], st[0][1]) == pytest.approx((198.0, 160.0))
    assert (st[1][0], st[1][1]) == pytest.approx((160.0, 132.0))


def test_vacuum_dv_matches_pool_for_all_11():
    """逐级齐奥尔科夫斯基必须复现池里的 ΔV（漏级会明显偏小）。"""
    if not _datamine_available():
        return
    for short in _points():
        prof = standard.resolve(short)
        assert mio.vacuum_dv(prof.engine.stages()) == pytest.approx(prof.dv, rel=1e-9), short


def test_vacuum_dv_from_blk_profile_matches_pool():
    """直接从 blk profile 算（模型层真实路径）也要对得上池子。"""
    if not _datamine_available():
        return
    for short, label in (("cn_pl12", "PL-12"), ("us_aim_120a", "120A"), ("il_derby", "Derby")):
        ref = standard.resolve(label)
        dv = mio.vacuum_dv(mio.module_stages(mio.load_blk_profile(short)))
        assert dv == pytest.approx(ref.dv, rel=1e-9), short


# --------------------------------------------------------------------- 乘数映射

def test_scale_mapping_reproduces_reference_areas():
    """用**该型自己**的 SD：取 (ΔV, BC) = 标称值时两个乘数都必须是 1.0。"""
    if not _datamine_available():
        return
    for short in _our_pool_profiles():
        st = mio.blk_stats(native_name=short)
        assert mio.scale_for_dv(st["dv"], st["dv"]) == pytest.approx(1.0)
        assert mio.cx_scale_for_bc(st["bc"], st["dry"], st["sd_m2"], st["cxk"]) == pytest.approx(1.0)


def test_cx_scale_uses_sd_not_sl():
    """拿升力面积当 SD 会得到**明显偏小**的乘数——这正是要防的错。

    升力面积 `SL` 比迎面面积 `SD` 大得多，用错时 `cx_scale = m/(BC·SL·CxK)` 会塌下来，
    本项目 PL-12 上表现为 0.0751（正确值 1.0），t_hit 直接被算成 25.6 s 而非 45.1 s。
    """
    if not _datamine_available():
        return
    st = mio.blk_stats(native_name="cn_pl12")
    right = mio.cx_scale_for_bc(st["bc"], st["dry"], st["sd_m2"], st["cxk"])
    wrong = mio.cx_scale_for_bc(st["bc"], st["dry"], st["sl_m2"], st["cxk"])
    assert right == pytest.approx(1.0)
    assert wrong == pytest.approx(st["sd_m2"] / st["sl_m2"], rel=1e-9)
    assert wrong < 0.2, f"用错面积应当把乘数压到 0.2 以下（实际 {wrong:.4f}）"
    assert abs(wrong - right) > 0.5, "两条路径必须明显不同，否则这条测试失去意义"


def test_scale_for_dv_rejects_bad_reference():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            mio.scale_for_dv(900.0, bad)


def test_cx_scale_rejects_bad_input():
    for args in ((0.0, 132.0, 0.032, 1.325), (3078.0, 0.0, 0.032, 1.325),
                 (3078.0, 132.0, 0.0, 1.325), (3078.0, 132.0, 0.032, 0.0)):
        with pytest.raises(ValueError):
            mio.cx_scale_for_bc(*args)


# --------------------------------------------------------------------- 型号可用性

def test_can_run_native_covers_package_plus_injection():
    for name in PACKAGE_PROFILES:
        assert mio.can_run_native(name), name
    for name in ("il_derby", "r_darter"):
        if _datamine_available():
            assert mio.can_run_native(name), f"{name} 应能靠注入跑原生"
    assert not mio.can_run_native("no_such_missile")


def test_native_name_strips_suffixes():
    assert mio.native_name_of("us_aim_120a.blkx") == "us_aim_120a"
    assert mio.native_name_of("cn_pl12.blk") == "cn_pl12"
    assert mio.native_name_of("cn_pl12") == "cn_pl12"


# --------------------------------------------------------------------- build_case

def test_build_case_normalizes_user_input():
    cfg = load_config()
    apply_standard(cfg)
    case = mio.build_case(cfg, missile="cn_pl12", dv=900.0, bc=3000.0)
    assert case.missile == "cn_pl12"
    assert case.dv_target == pytest.approx(900.0)
    assert case.bc_target == pytest.approx(3000.0)
    assert case.range_m == cfg.scenario.range
    assert case.alt_m == cfg.scenario.alt
    assert case.vm0 == cfg.scenario.vm0 and case.vt == cfg.scenario.vt
    assert case.target_alt == (cfg.scenario.target_alt if cfg.scenario.target_alt is not None
                               else cfg.scenario.alt)
    assert case.dt == pytest.approx(cfg.pro_dt)
    assert case.observation_mode == cfg.pro_observation


def test_build_case_derives_native_name_from_profile():
    cfg = load_config()
    cfg.standard.name = "120A"
    apply_standard(cfg)
    case = mio.build_case(cfg)                      # 不给 missile，应从 profile 推
    assert case.missile == "us_aim_120a"
    assert case.dv_target == 0.0 and case.bc_target == 0.0   # 0 ⇒ 标称（乘数 1）


def test_build_case_overrides_scenario():
    cfg = load_config()
    apply_standard(cfg)
    case = mio.build_case(cfg, missile="cn_pl12", dv=1000.0, bc=2500.0,
                          range_m=30000.0, target_alt_m=8000.0)
    assert case.range_m == pytest.approx(30000.0)
    assert case.target_alt == pytest.approx(8000.0)


def test_build_case_rejects_unknown_missile():
    cfg = load_config()
    apply_standard(cfg)
    with pytest.raises(ValueError):
        mio.build_case(cfg, missile="no_such_missile")


def test_build_case_accepts_injected_missile():
    """Derby / R-Darter 不在包内清单，但注入后必须能建工况。"""
    if not _datamine_available():
        return
    cfg = load_config()
    apply_standard(cfg)
    case = mio.build_case(cfg, missile="il_derby", dv=932.8, bc=2567.0)
    assert case.missile == "il_derby"


# --------------------------------------------------------------------- scale_tag

def test_scale_tag_records_both_spaces():
    if not _datamine_available():
        return
    prof = standard.resolve("PL-12")
    tag = mio.scale_tag(prof.dv, prof.bc, prof)
    assert tag["dv_target"] == pytest.approx(prof.dv)
    assert tag["bc_target"] == pytest.approx(prof.bc)
    assert tag["thrust_scale"] == pytest.approx(1.0)
    assert tag["cx_scale"] == pytest.approx(1.0)
    assert tag["dv_blk"] == pytest.approx(prof.dv)
    assert tag["cxk_used"] == pytest.approx(prof.cxk)

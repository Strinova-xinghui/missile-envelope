"""标准弹（11 弹池）测试：池 schema、解析正确性、与权威 ΔV/BC 口径一致、回退可追溯。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from missile_sim import burn, standard  # noqa: E402
from missile_sim.config import (  # noqa: E402
    ConfigError,
    apply_standard,
    ballistic_coefficient,
    delta_v_equiv,
    load_config,
    summary_lines,
)

POOL = ROOT / "results" / "missile_standards.json"
PTS = ROOT / "results" / "missile_points.json"
EXPECTED_11 = ("120A", "120C", "120D", "MICA", "AAM-4", "PL-12", "PL-12A",
               "R-77", "R-77-1", "Derby", "R-Darter")


@pytest.fixture()
def pool():
    return json.loads(POOL.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- 池本身

def test_pool_file_and_schema(pool):
    assert POOL.exists(), "池文件缺失；请运行 scripts\\build_standard_pool.py"
    assert pool["schema"] == 1
    assert pool["default"] == "PL-12"
    assert tuple(pool["missiles"].keys()) == EXPECTED_11
    for name, m in pool["missiles"].items():
        for sect in ("geometry", "aero", "mass", "engine", "impulse", "limits", "loft", "fuse", "gains"):
            assert sect in m, f"{name} 缺 {sect}"
        assert m["geometry"]["caliber_m"] > 0
        assert m["mass"]["launch"] > m["mass"]["dry"] > 0
        assert m["engine"]["force"] > 0 and m["engine"]["time_fire"] > 0
        assert m["gains"]["impact_schedule"]


def test_pool_matches_canonical_missile_points(pool):
    """池里的 ΔV / BC / 干重 / CxK / 口径必须与权威口径 missile_points.json 逐值一致。"""
    pts = {m["label"]: m for m in json.loads(PTS.read_text(encoding="utf-8"))["missiles"]}
    for name, m in pool["missiles"].items():
        q = pts[name]
        assert m["impulse"]["dv"] == pytest.approx(q["dv"], rel=1e-12)
        assert m["impulse"]["bc"] == pytest.approx(q["bc"], rel=1e-12)
        assert m["mass"]["dry"] == pytest.approx(q["dry"], rel=1e-12)
        assert m["aero"]["cxk"] == pytest.approx(q["k"], rel=1e-12)
        assert m["geometry"]["caliber_m"] * 1000.0 == pytest.approx(q["d_mm"], rel=1e-12)
        assert bool(m["mass"]["two_stage"]) == bool(q["two_stage"])


def test_gain_tables_satisfy_min_rule_equivalence(pool):
    """回退规则（有 timeToHitToGain 就用它，否则用 timeToGain）等价于游戏"两条 ramp 取 min"。

    前提：两者都有时，发射 ramp 必须在 0.31 s 内走完、命中前解锁表最早从 10 s 起，
    于是 0.31 s 之后 min 恒等于命中前解锁表。只有发射 ramp 的型号（MICA），
    min(ramp, 1.0) 就是 ramp 本身。两种情形都断言"两条表的断点区间不重叠"。
    """
    for name, m in pool["missiles"].items():
        g = m["gains"]
        launch = [(t, v) for t, v in (g.get("launch_schedule") or [])]
        impact = [(t, v) for t, v in g["impact_schedule"]]
        if g["impact_source"] == "timeToHitToGain":
            # 有发射 ramp 的型号（PL-12/AAM-4/R-77 系…）必须两段不重叠；
            # 只有命中前解锁表的型号（120A/C/D）没有 ramp，min 退化为该表本身。
            if launch:
                assert max(t for t, _ in launch) < 1.0, f"{name} 发射 ramp 断点 ≥1s"
                assert min(t for t, _ in impact) >= 1.0, f"{name} 两表断点区间重叠"
        else:
            assert g["impact_source"] == "timeToGain"
            assert not launch or launch == impact
            assert max(t for t, _ in impact) < 1.0, f"{name} 唯一 ramp 应在 1s 内走完"


# --------------------------------------------------------------------- 解析

def test_resolve_pl12_matches_verified_values():
    """PL-12 是默认标准弹，逐字段对拍 AERO_PLAN §16.3 的核实值。"""
    p = standard.resolve("PL-12")
    assert p.caliber_m == pytest.approx(0.203)
    assert p.length_m == pytest.approx(3.934)
    assert p.wing_area_mult == pytest.approx(1.8)
    assert p.cxk == pytest.approx(1.325)
    assert p.dv == pytest.approx(932.6, abs=0.1)
    assert p.bc == pytest.approx(3078.1, abs=0.1)
    assert p.engine.mass_launch == pytest.approx(198.0)
    assert p.engine.mass_mid == pytest.approx(160.0)
    assert p.engine.mass_dry == pytest.approx(132.0)
    assert p.engine.two_stage is True
    assert p.engine.force == pytest.approx(34960.0)
    assert p.engine.time_fire == pytest.approx(2.5)
    assert p.engine.force1 == pytest.approx(12880.0)
    assert p.engine.time_fire1 == pytest.approx(5.0)
    assert p.engine.burn_time_total == pytest.approx(7.5)
    assert p.req_accel_max_g == pytest.approx(38.0)
    assert p.prop_nav_mult == pytest.approx(6.0)
    assert p.time_life_s == pytest.approx(80.0)
    assert p.fuse_radius_m == pytest.approx(10.0)
    assert p.loft.enabled is True
    assert p.loft.elevation_deg == pytest.approx(20.0)
    assert p.loft.target_elevation_deg == pytest.approx(-2.25)
    assert p.loft.target_omega_max_dps == pytest.approx(0.5)
    assert p.loft.angle_to_accel_mult == pytest.approx(20.0)
    assert p.gain_source == "timeToHitToGain"
    assert p.gain_schedule == ((10.0, 1.0), (25.0, 0.8), (50.0, 0.5))


def test_resolve_all_eleven_and_fallbacks_are_traceable():
    for name in EXPECTED_11:
        p = standard.resolve(name)
        assert p.name == name
        # 全局回退只允许出现在这三项（CyK / CxAoA 全库无键；CyMaxAoA 部分弹无键）
        assert set(p.fallbacks) <= {"cyk", "cx_aoa", "cy_max_aoa", "req_accel_max_g", "gain_schedule"}
        assert "cyk" in p.fallbacks and "cx_aoa" in p.fallbacks
        assert p.engine.mass_dry > 0
        assert p.dv > 0 and p.bc > 0


def test_mica_falls_back_to_launch_ramp():
    """MICA 没有 timeToHitToGain ⇒ 用 timeToGain；其断点 0.15/0.16 s ⇒ 之后恒为 1.0。"""
    p = standard.resolve("MICA")
    assert p.gain_source == "timeToGain"
    assert p.gain_schedule[0][0] == pytest.approx(0.15)
    assert p.gain_schedule[-1][1] == pytest.approx(1.0)


def test_unknown_name_lists_available():
    with pytest.raises(standard.StandardPoolError) as ei:
        standard.resolve("AIM-9X")
    assert "PL-12" in str(ei.value) and "Derby" in str(ei.value)


def test_missing_pool_gives_actionable_error(tmp_path):
    with pytest.raises(standard.StandardPoolError) as ei:
        standard.load_pool(tmp_path / "nope.json")
    assert "build_standard_pool" in str(ei.value)


def test_profile_hash_is_stable_and_discriminating():
    a1, a2 = standard.resolve("PL-12"), standard.resolve("PL-12")
    b = standard.resolve("PL-12A")
    assert a1.profile_hash() == a2.profile_hash()
    assert a1.profile_hash() != b.profile_hash()


# --------------------------------------------------------------------- 配置接入

def test_default_config_is_pl12():
    cfg = load_config()
    assert cfg.standard.name == "PL-12"
    assert cfg.profile is not None and cfg.profile.name == "PL-12"
    assert cfg.drag.caliber_m == pytest.approx(0.203)
    assert cfg.drag.cxk == pytest.approx(1.325)
    assert cfg.aero.length_m == pytest.approx(3.934)
    assert cfg.aero.wing_area_mult == pytest.approx(1.8)
    assert cfg.mass.mass_launch == pytest.approx(198.0)
    assert cfg.mass.mass_end == pytest.approx(132.0)
    assert cfg.sim.theta_loft_deg == pytest.approx(20.0)
    assert cfg.sim.a_lat_max_g == pytest.approx(38.0)
    assert cfg.sim.hit_radius == pytest.approx(10.0)
    assert cfg.sim.t_life == pytest.approx(80.0)
    assert cfg.burn.model == burn.MODEL_FINITE
    assert cfg.burn.two_stage is True
    # ΔV 由标准弹导出（真空等效），BC 用干重
    assert delta_v_equiv(cfg) == pytest.approx(932.6, abs=0.1)
    assert ballistic_coefficient(cfg.drag.cxk, cfg) == pytest.approx(3078.1, abs=0.1)


def test_120c5_config_resolves_to_120c5():
    cfg = load_config(ROOT / "configs" / "standard_120c5.json")
    assert cfg.profile.name == "120C"
    assert cfg.drag.caliber_m == pytest.approx(0.1778)
    assert cfg.drag.cxk == pytest.approx(1.225)
    assert cfg.mass.mass_end == pytest.approx(110.223)
    assert cfg.sim.hit_radius == pytest.approx(12.0)
    assert cfg.sim.t_life == pytest.approx(120.0)
    assert cfg.sim.theta_loft_deg == pytest.approx(22.0)
    assert cfg.burn.two_stage is False
    assert cfg.burn.burn_time_total == pytest.approx(7.75)
    assert delta_v_equiv(cfg) == pytest.approx(897.39, abs=0.02)
    assert ballistic_coefficient(cfg.drag.cxk, cfg) == pytest.approx(3624.0, abs=0.1)


def test_ve_equiv_override_wins_and_restores_legacy_dv():
    """旧口径的 ΔV=865.31 靠 ve_equiv_override 复现（A1 安全绳）。"""
    cfg = load_config(ROOT / "configs" / "standard_120c5.json")
    cfg.impulse.ve_equiv_override = 2266.0
    assert delta_v_equiv(cfg) == pytest.approx(865.31, abs=0.02)


def test_switching_standard_is_idempotent():
    cfg = load_config()
    before = delta_v_equiv(cfg)
    apply_standard(cfg)
    assert delta_v_equiv(cfg) == pytest.approx(before, rel=1e-15)
    cfg.standard.name = "R-77-1"
    apply_standard(cfg)
    assert cfg.profile.name == "R-77-1"
    assert cfg.sim.hit_radius == pytest.approx(10.0)
    assert cfg.burn.two_stage is False
    assert delta_v_equiv(cfg) == pytest.approx(1099.5, abs=0.1)


def test_empty_standard_name_disables_resolution():
    cfg = load_config()
    cfg.standard.name = ""
    apply_standard(cfg)
    assert cfg.profile is None
    assert cfg.burn.model == burn.MODEL_INSTANT
    assert cfg.burn.has_thrust is False


def test_derby_loft_elevation_passes_validation():
    """Derby/R-Darter 的 loftElevation=27.5 必须合法（<40）。"""
    for name in ("Derby", "R-Darter"):
        cfg = load_config()
        cfg.standard.name = name
        apply_standard(cfg)          # 内部不校验
        assert cfg.sim.theta_loft_deg == pytest.approx(27.5)
        cfg.sim.theta_loft_deg = 27.5
        from missile_sim.config import validate
        validate(cfg)


def test_bad_burn_model_rejected():
    cfg = load_config()
    cfg.standard.burn = "warp"
    with pytest.raises(ConfigError):
        from missile_sim.config import validate
        validate(cfg)


def test_unknown_standard_in_config_raises_clear_error(tmp_path):
    src = json.loads((ROOT / "configs" / "baseline.json").read_text(encoding="utf-8"))
    src["standard"]["name"] = "AIM-9X"
    p = tmp_path / "c.json"
    p.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    assert "PL-12" in str(ei.value)


def test_summary_lines_expose_standard_and_fallbacks():
    lines = "\n".join(summary_lines(load_config()))
    assert "标准弹" in lines and "PL-12" in lines
    assert "全局回退字段" in lines and "cyk" in lines
    assert "有限燃烧" in lines


# --------------------------------------------------------------------- 燃烧剖面

def test_engine_stages_shape():
    two = standard.resolve("PL-12").engine.stages()
    assert len(two) == 2
    assert two[0] == pytest.approx((198.0, 160.0, 34960.0, 2.5))
    assert two[1] == pytest.approx((160.0, 132.0, 12880.0, 5.0))
    one = standard.resolve("120C").engine.stages()
    assert len(one) == 1
    assert one[0] == pytest.approx((161.4789, 110.223, 15542.0, 7.75))


def test_burn_profile_mass_and_thrust_timeline():
    b = burn.from_standard(standard.resolve("PL-12"))
    assert b.mass_at(0.0) == pytest.approx(198.0)
    assert b.mass_at(1.25) == pytest.approx(179.0)          # 线性
    assert b.mass_at(2.5) == pytest.approx(160.0)
    assert b.mass_at(5.0) == pytest.approx(146.0)
    assert b.mass_at(7.5) == pytest.approx(132.0)
    assert b.mass_at(50.0) == pytest.approx(132.0)
    assert b.thrust_at(0.0) == pytest.approx(34960.0)
    assert b.thrust_at(2.49) == pytest.approx(34960.0)
    assert b.thrust_at(2.5) == pytest.approx(12880.0)
    assert b.thrust_at(7.5) == pytest.approx(0.0)
    assert b.has_thrust is True


def test_single_stage_burn_profile():
    b = burn.from_standard(standard.resolve("120C"))
    assert b.mass_at(0.0) == pytest.approx(161.4789)
    assert b.mass_at(3.875) == pytest.approx((161.4789 + 110.223) / 2)
    assert b.mass_at(7.75) == pytest.approx(110.223)
    assert b.thrust_at(7.74) == pytest.approx(15542.0)
    assert b.thrust_at(7.75) == pytest.approx(0.0)


def test_instant_profile_has_no_thrust_and_unit_mass_ratio():
    b = burn.instant_profile(dv_blk=897.4)
    assert b.model == burn.MODEL_INSTANT
    assert b.has_thrust is False
    assert burn.mass_ratio_at(0.0, b) == pytest.approx(1.0)
    assert burn.mass_ratio_at(3.0, None) == pytest.approx(1.0)


def test_mass_ratio_at_uses_k_scaling():
    b = burn.from_standard(standard.resolve("PL-12"))
    assert burn.mass_ratio_at(0.0, b) == pytest.approx(198.0 / 132.0)
    assert burn.mass_ratio_at(0.0, b, k=2.0) == pytest.approx(2.0 * 198.0 / 132.0)
    assert burn.mass_ratio_at(7.5, b) == pytest.approx(1.0)


def test_scale_for_dv_is_linear():
    b = burn.from_standard(standard.resolve("PL-12"))
    assert b.scale_for_dv(b.dv_blk) == pytest.approx(1.0)
    assert b.scale_for_dv(b.dv_blk * 2.0) == pytest.approx(2.0)
    assert b.scale_for_dv(b.dv_blk / 2.0) == pytest.approx(0.5)


def test_burn_describe_is_readable():
    txt = "\n".join(burn.describe(burn.from_standard(standard.resolve("PL-12"))))
    assert "有限燃烧" in txt and "34960" in txt and "12880" in txt
    assert "瞬时燃烧" in "\n".join(burn.describe(burn.instant_profile()))

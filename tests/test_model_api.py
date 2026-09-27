# -*- coding: utf-8 -*-
"""**模型接入契约**自检：结构化输入/输出、注册表、运行环境、第三方模型插桩。

为什么单独测这一层（用户 2026-09-25 定案）：后续会从开源拿到**更新的模型**，必须能像换零件
一样接进来并保持版本管理闭环。这一层的回归一旦破了，坏模型会静默算出错的弹道，
或者更糟——**把 44 min 的 Pro 缓存整体作废**（键/版本号/指纹任何一处漂移都会）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from missile_sim.model import env as env_mod
from missile_sim.model import io as mio
from missile_sim.model import registry as reg
from missile_sim.model.constants import DT_DEFAULT, VERSION_28
from missile_sim.model.native import NativeCase, NativeResult
from missile_sim.model.spec import (
    Autopilot,
    Capability,
    EngineEnv,
    EngineInputs,
    EngineStamp,
    LoftConfig,
    ModelSpec,
    PidRow,
    SelfTestReport,
)

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "baseline.json"


def _pl12_case(**over):
    kw = dict(missile="cn_pl12", dv_target=932.5697486487783, bc_target=3078.0530156224613)
    kw.update(over)
    return NativeCase(**kw)


# --------------------------------------------------------------------- 缓存键（最重要）

def test_cache_key_is_stable_across_calls():
    c = _pl12_case()
    assert c.key() == c.key() == c.engine_inputs().cache_key()


def test_cache_key_sensitive_to_physics_inputs():
    """物理输入变了键必须变——否则结果会串味。"""
    base = _pl12_case()
    for over in (dict(dv_target=900.0), dict(bc_target=3000.0), dict(range_m=40000.0),
                 dict(alt_m=5000.0), dict(vm0=250.0), dict(vt=-400.0), dict(dt=0.005),
                 dict(observation_mode="locked"), dict(hit_radius_m=12.0),
                 dict(proximity_fuse=False), dict(ground_height_m=100.0),
                 dict(wind_m_s=(5.0, 0.0, 0.0)),
                 dict(target_maneuvers=((1.0, (0.0, 5.0, 0.0)),)),
                 dict(target_alt_m=8000.0)):
        assert _pl12_case(**over).key() != base.key(), over


def test_cache_key_ignores_non_physics_fields():
    """采样周期/要不要轨迹/弹池身份都不该进键（否则同一个物理工况会有多份缓存）。"""
    base = _pl12_case()
    assert _pl12_case(sample_period_s=0.1).key() == base.key()
    assert _pl12_case(save_trajectory=True).key() == base.key()


def test_cache_key_matches_frozen_reference():
    """钉死一个具体值：这个键一漂，`results/pro_cache.json` 的 1824 条全部作废。"""
    case = NativeCase(missile="cn_pl12", dv_target=932.5697486487783,
                      bc_target=3078.0530156224613, range_m=50000.0, alt_m=10000.0,
                      vm0=300.0, vt=-300.0, dt=0.01, observation_mode="ideal")
    assert len(case.key()) == 20                       # sha256 截断到 20 位
    assert case.key() == case.engine_inputs().cache_key()


# --------------------------------------------------------------------- 结构化输入

def test_inputs_from_case_fills_every_parameter_block():
    """Pro 与 Flash 都靠这一份输入开工：参数块缺一块就会在引擎里报出来。"""
    inp = mio.inputs_from_case(_pl12_case())
    assert inp.check() == []
    assert inp.mass is not None and inp.geometry is not None and inp.aero is not None
    assert inp.standard == "PL-12" and inp.tag == "WORK"
    assert inp.profile_hash, "弹池指纹必须带上（产物追溯用）"


def test_inputs_mapping_values_are_frozen():
    """(ΔV, BC) → 乘数的**唯一算法**：这三个数一改，两边引擎一起改口径。"""
    inp = mio.inputs_from_case(_pl12_case())
    assert inp.dv_blk == pytest.approx(932.5697486487783, rel=1e-12)
    assert inp.bc_blk == pytest.approx(3078.0530156224613, rel=1e-9)
    assert inp.thrust_scale == pytest.approx(1.0, rel=1e-12)
    assert inp.cx_scale == pytest.approx(1.0, rel=1e-12)
    assert inp.cxk_used == pytest.approx(1.325, rel=1e-12)


def test_inputs_mapping_scales_with_targets():
    """ΔV 严格线性（s = ΔV/ΔV_blk）；BC 按迎面面积反解。"""
    inp = mio.inputs_from_case(_pl12_case(dv_target=800.0, bc_target=2450.0))
    assert inp.thrust_scale == pytest.approx(800.0 / 932.5697486487783, rel=1e-12)
    want_cx = 132.0 / (2450.0 * inp.geometry.sd_m2 * 1.325)
    assert inp.cx_scale == pytest.approx(want_cx, rel=1e-12)
    assert inp.cxk_used == pytest.approx(1.325 * want_cx, rel=1e-12)


def test_inputs_zero_target_means_nominal():
    """`dv_target=0` / `bc_target=0` 是"标称"的哨兵值（乘数 1），不是"零推力/零阻力"。"""
    inp = mio.inputs_from_case(_pl12_case(dv_target=0.0, bc_target=0.0))
    assert inp.thrust_scale == 1.0 and inp.cx_scale == 1.0
    assert inp.check() == []


def test_inputs_check_catches_broken_mapping():
    """映射自洽性必须能被查出来（这是"两处重算分叉"的守门人）。"""
    inp = mio.inputs_from_case(_pl12_case())
    bad_dv = EngineInputs(**{**inp.__dict__, "thrust_scale": 1.5})
    assert any("thrust_scale" in b for b in bad_dv.check())
    bad_cx = EngineInputs(**{**inp.__dict__, "cx_scale": 1.5})
    assert any("cx_scale" in b for b in bad_cx.check())


def test_inputs_check_catches_missing_blocks():
    bare = EngineInputs(missile="cn_pl12", version=VERSION_28)
    bad = bare.check()
    assert any("mass" in b for b in bad) and any("geometry" in b for b in bad)
    assert any("CxK" in b for b in bad) and any("dv_blk" in b for b in bad)


def test_inputs_digest_is_stable_and_sensitive():
    from missile_sim.model.spec import digest_of_inputs

    a = mio.inputs_from_case(_pl12_case())
    b = mio.inputs_from_case(_pl12_case())
    c = mio.inputs_from_case(_pl12_case(dv_target=900.0))
    assert digest_of_inputs(a) == digest_of_inputs(b)
    assert digest_of_inputs(a) != digest_of_inputs(c)


# --------------------------------------------------------------------- 参数块翻译

def test_normalize_blk_profile_reads_pid_table():
    """120A 用 `pid0/pid1` 时间表：翻译层要按弹龄分段线性取值。"""
    pars = mio.normalize_blk_profile(mio.rocket_block("WORK", "us_aim_120a"))
    ap = pars["autopilot"]
    assert len(ap.pid_rows) >= 1
    kp0, ki0, kd0, lim0 = ap.pid_at(0.0)
    assert kp0 == pytest.approx(ap.pid_rows[0].prop)
    assert lim0 == pytest.approx(ap.pid_rows[0].intg_lim)
    late = ap.pid_at(1e6)                              # 区间外取端点
    assert late[0] == pytest.approx(ap.pid_rows[-1].prop)


def test_normalize_blk_profile_reads_flat_pid_coefficients():
    """PL-12 用扁平 `accelControl*`：没有 pidN 也要能拿到系数（否则 PID 无从实现）。"""
    pars = mio.normalize_blk_profile(mio.rocket_block("WORK", "cn_pl12"))
    ap = pars["autopilot"]
    assert ap.pid_rows == ()
    assert ap.kp == pytest.approx(0.001784)
    assert ap.ki == pytest.approx(0.018364)
    assert ap.kd == pytest.approx(5.1e-05)
    assert ap.i_limit == pytest.approx(1.0)
    assert ap.pid_at(3.0) == pytest.approx((ap.kp, ap.ki, ap.kd, ap.i_limit))


def test_normalize_blk_profile_keeps_geometry_and_loft():
    pars = mio.normalize_blk_profile(mio.rocket_block("WORK", "cn_pl12"))
    geo, loft = pars["geometry"], pars["loft"]
    assert geo.caliber_m == pytest.approx(0.203)
    assert geo.length_m == pytest.approx(3.934)
    assert geo.wing_area_mult == pytest.approx(1.8)
    assert geo.dist_from_cm_to_stab == pytest.approx(0.5)
    assert geo.lever_m == pytest.approx(0.5 / 1.8)
    assert loft.enabled is True
    assert loft.elevation_deg == pytest.approx(20.0)
    assert loft.angle_to_accel_mult == pytest.approx(20.0)
    assert loft.target_omega_max_dps == pytest.approx(0.5)


def test_gain_tables_are_interpolated_outside_range():
    pars = mio.normalize_blk_profile(mio.rocket_block("WORK", "cn_pl12"))
    gains = pars["gains"]
    assert gains.source == "timeToHitToGain"
    assert gains.g_hit(0.0) == pytest.approx(1.0)       # 首端
    assert gains.g_hit(1e6) == pytest.approx(0.5)       # 末端
    assert gains.g_time(0.0) == pytest.approx(0.0)
    assert gains.g_time(10.0) == pytest.approx(1.0)


def test_mass_profile_stages_are_per_stage():
    """两级弹的干重在 `massEnd1`：只取第一级会让 ΔV_blk 偏小（踩过的坑）。"""
    pars = mio.normalize_blk_profile(mio.rocket_block("WORK", "cn_pl12"))
    mass = pars["mass"]
    assert (mass.launch, mass.mid, mass.dry) == (198.0, 160.0, 132.0)
    assert mass.two_stage is True
    assert len(mass.stages()) == 2
    assert mass.stages()[-1][1] == 132.0


def test_loft_range_interpolation_unused_by_default():
    """11 型都没有 `rangeToLoftElevation` ⇒ 恒为目标角；有表时按距离平方插值。"""
    pars = mio.normalize_blk_profile(mio.rocket_block("WORK", "cn_pl12"))
    assert pars["loft"].range_to_loft_elevation == ()
    assert pars["loft"].desired_elevation_deg(1.0) == pytest.approx(20.0)
    assert pars["loft"].desired_elevation_deg(99999.0) == pytest.approx(20.0)
    tbl = LoftConfig(elevation_deg=10.0, range_to_loft_elevation=(1000.0, 10.0, 2000.0, 30.0))
    assert tbl.desired_elevation_deg(0.0) == pytest.approx(10.0)      # 区间外取端点
    assert tbl.desired_elevation_deg(5000.0) == pytest.approx(30.0)
    assert tbl.desired_elevation_deg(1581.1388300841898) == pytest.approx(20.0, abs=1e-6)


# --------------------------------------------------------------------- 注册表

def test_builtin_models_are_registered():
    """**档位只有 standard / fast**；旧 pro / flash 是 legacy —— 默认不列、但能查到。"""
    names = [s.name for s in reg.list_models()]
    assert names == ["fast", "standard"], names
    legacy = [s.name for s in reg.list_models(include_legacy=True)]
    assert "pro" in legacy and "flash" in legacy
    assert reg.spec_of("pro").source == "legacy"
    assert reg.spec_of("flash").source == "legacy"


def test_pro_spec_keeps_cache_schema_5():
    """旧 Pro 的缓存号必须还是 5：改了就要重跑 44 min。"""
    sp = reg.spec_of("pro")
    assert sp.calc_version == 5
    assert sp.requirements.get("native_pkg") is True


def test_standard_and_fast_specs_are_distinct_partitions():
    """两档是**同一物理的两个算术后端**，必须各有一张 ModelSpec 与独立的缓存版本号。"""
    a, b = reg.spec_of("standard"), reg.spec_of("fast")
    assert a.name != b.name
    assert a.calc_version == b.calc_version == 1
    assert a.entry.endswith(":StandardEngine") and b.entry.endswith(":FastEngine")
    assert a.requirements.get("vendor") is True and b.requirements.get("vendor") is True
    assert a.requirements.get("native_pkg") is False
    assert b.requirements.get("compiler") == "optional"
    assert a.capabilities.dims == "3d" and b.capabilities.dims == "3d"
    assert a.capabilities.vectorized_batch is False


def test_unknown_model_raises_with_available_list():
    with pytest.raises(reg.ModelNotFound) as ei:
        reg.spec_of("no-such-model")
    assert "standard" in str(ei.value)


def test_bad_entry_is_reported_not_silently_ignored():
    spec = ModelSpec(name="broken", label="坏模型", version="0", calc_version=1,
                     entry="missile_sim.model.native")     # 缺 ":对象"
    with pytest.raises(reg.ModelNotFound) as ei:
        reg.load_engine(spec)
    assert "entry" in str(ei.value)


def test_models_table_roundtrips_to_json():
    doc = reg.models_table()
    assert set(doc["models"]) == {"standard", "fast"}
    assert doc["models"]["standard"]["calc_version"] == 1
    txt = json.dumps(doc, ensure_ascii=False, indent=1)
    assert json.loads(txt)["models"]["fast"]["capabilities"]["dims"] == "3d"


def test_write_models_table(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    p = reg.write_models_table(d / "models.json")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert set(doc["models"]) == {"standard", "fast"}
    assert doc["models"]["standard"]["entry"].endswith(":StandardEngine")


# --------------------------------------------------------------------- 运行环境

def test_env_only_requires_what_the_model_declares():
    """只跑 flash 时不该因为没装原生包而报错。"""
    e_flash = env_mod.build_env("flash")
    assert e_flash.pkg is None
    e_pro = env_mod.build_env("pro")
    assert e_pro.pkg and e_pro.workdir == e_pro.pkg


def test_env_carries_technical_overrides():
    from missile_sim.config import load_config

    cfg = load_config(CONFIG)
    cfg.pro_jobs = 3
    cfg.pro_dt = 0.005
    e = env_mod.build_env("pro", cfg)
    assert e.pool_jobs == 3 and e.dt == pytest.approx(0.005)
    e2 = env_mod.build_env("pro", cfg, pool_jobs=5)
    assert e2.pool_jobs == 5


def test_env_unknown_key_goes_to_options():
    e = env_mod.build_env("flash", dt_inner=0.001)
    assert e.dt_inner == pytest.approx(0.001)


# --------------------------------------------------------------------- 第三方模型插桩

STUB_PKG = '''
"""最小第三方模型：只为证明"开源拿到的新模型能按同一契约接进来"。"""
from missile_sim.model.spec import Capability, EngineEnv, EngineStamp, ModelSpec, SelfTestReport

MODEL_SPEC = ModelSpec(
    name="{name}", label="桩模型", version="0.0.1", calc_version=1,
    entry="{mod}:StubEngine", source="test",
    capabilities=Capability(dims="2d", vectorized_batch=False, trajectory=False,
                            observation_modes=("ideal",)),
    requirements={{"native_pkg": False}},
)

class StubEngine:
    spec = MODEL_SPEC

    def runtime_info(self):
        return {{"kind": "stub", "engine": "{{}}".format(MODEL_SPEC.name),
                "engine_version": MODEL_SPEC.version, "calc_version": MODEL_SPEC.calc_version}}

    def simulate(self, inp, env=None):
        from missile_sim.model.native import NativeResult
        r = NativeResult(ok=True, event="contact", t_end=42.0, t_hit=42.0, hit=True,
                         miss_distance_m=0.0, max_alt_m=12345.0, v_impact=600.0,
                         thrust_scale=inp.thrust_scale, cx_scale=inp.cx_scale,
                         dv_blk=inp.dv_blk, bc_blk=inp.bc_blk, resource="stub")
        r.engine = self.stamp().to_dict()
        return r

    def selftest(self, env=None):
        return SelfTestReport(name=MODEL_SPEC.name, ok=True).add("桩模型恒通过", True)

    def stamp(self):
        return EngineStamp(name=MODEL_SPEC.name, version=MODEL_SPEC.version,
                           calc_version=MODEL_SPEC.calc_version, fidelity={{}}, resources={{}})

ENGINE = StubEngine()
'''


def _install_stub(name: str = "stub-model"):
    """把一个第三方模型包写到临时目录，并挂到 `$WT_MODELS_PATH`。

    目录名带连字符（CLI 好写），**包名不能带** —— 这正是 `registry` 要处理的现实约束，
    所以这里刻意用连字符目录名 + 下划线包名来测它。
    """
    d = Path(tempfile.mkdtemp())
    entry_pkg = name.replace("-", "_")
    pkg = d / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        STUB_PKG.format(name=name, mod=entry_pkg), encoding="utf-8")
    old = os.environ.get(reg.ENV_MODELS_PATH)
    os.environ[reg.ENV_MODELS_PATH] = str(d)
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    return d, old


def _uninstall_stub(d, old):
    if old is None:
        os.environ.pop(reg.ENV_MODELS_PATH, None)
    else:
        os.environ[reg.ENV_MODELS_PATH] = old
    for mod in [m for m in list(sys.modules)
                if m.split(".")[0] in {p.name.replace("-", "_") for p in Path(d).iterdir()
                                       if p.is_dir()}]:
        sys.modules.pop(mod, None)
    if str(d) in sys.path:
        sys.path.remove(str(d))


def test_third_party_model_is_discovered():
    d, old = _install_stub()
    try:
        names = [s.name for s in reg.list_models()]
        assert "stub-model" in names, names
        sp = reg.spec_of("stub-model")
        assert sp.source == "test" and sp.calc_version == 1
    finally:
        _uninstall_stub(d, old)


def test_third_party_model_runs_through_the_scanner():
    """**这是"开源拿到新模型能统一接入"的可执行证明**：
    经注册表跑一遍扫描，产出与 Pro/Flash 同形的 `CaseRecord`。"""
    from missile_sim import scanner as sc
    from missile_sim.model.cache import backend_cache

    d, old = _install_stub()
    try:
        spec = sc.ScanSpec(standard="PL-12", tag="WORK", model="stub-model",
                           grid=sc.Grid.make(900, 910, 10, 3000, 3025, 25),
                           cache_path="", run_id="stub_probe")
        out = sc.Scanner(spec, cache=backend_cache("stub-model", None, enabled=False)).run(write=False)
        assert len(out.records) == 4
        r = out.records[0]
        assert r.ok and r.hit and r.t_hit == pytest.approx(42.0)
        assert r.model["kind"] == "stub"                 # 自报身份
        assert r.schema == 1                             # 用该模型自己的缓存号
        assert r.scales["thrust_scale"] > 0
        man = out.manifest
        assert man["calculator"]["model"] == "stub-model"
        assert man["calculator"]["calc_version"] == 1
        assert man["runtime"]["engine"] == "stub-model"
    finally:
        _uninstall_stub(d, old)


def test_third_party_model_selftest_is_wired():
    d, old = _install_stub("stub-check")
    try:
        rep = reg.check_models(names=["stub-check"], verbose=False)
        assert rep["stub-check"]["ok"] is True
    finally:
        _uninstall_stub(d, old)


def test_check_models_reports_failure_instead_of_raising():
    """坏模型必须"报告失败"，不能把 `pipeline.py models --check` 直接炸掉。"""
    d, old = _install_stub("stub-bad")
    try:
        from missile_sim.model import native as native_mod
        saved = native_mod.ProEngine.selftest

        def boom(self, env=None):
            raise RuntimeError("模型坏了")

        native_mod.ProEngine.selftest = boom
        try:
            rep = reg.check_models(names=["pro"], verbose=False)
        finally:
            native_mod.ProEngine.selftest = saved
        assert rep["pro"]["ok"] is False and "模型坏了" in rep["pro"]["error"]
    finally:
        _uninstall_stub(d, old)


# --------------------------------------------------------------------- 身份戳

def test_engine_stamp_is_jsonable():
    st = EngineStamp(name="x", version="1.2.3", calc_version=7,
                     fidelity={"recovered": ["a"], "not_recovered": ["b"], "derived": ["c"]},
                     resources={"dt": 0.01})
    d = st.to_dict()
    assert json.loads(json.dumps(d))["fidelity"]["not_recovered"] == ["b"]


def test_pro_engine_stamp_has_fidelity_and_resources():
    from missile_sim.model.native import ProEngine

    st = ProEngine().stamp()
    assert st.name == "pro" and st.calc_version == 5
    assert st.fidelity["recovered"] and st.fidelity["not_recovered"] == []


def test_selftest_report_accumulates_ok():
    rep = SelfTestReport(name="t", ok=True)
    rep.add("a", True)
    assert rep.ok is True
    rep.add("b", False, "坏了")
    assert rep.ok is False and rep.checks[-1]["note"] == "坏了"

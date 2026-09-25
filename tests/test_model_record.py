# -*- coding: utf-8 -*-
"""模型层 3（输出层）自检：`CaseRecord` 契约、表读写、指纹与时效判定。

这层是"产物自描述"的落点：一条记录必须能独立回答
**输入是什么 / 谁算的 / 还算不算数**。
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from missile_sim.model import record as mrec
from missile_sim.model.constants import CALC_VERSION, ELF_SHA256_28, VERSION_28
from missile_sim.model.native import NativeCase, NativeResult


def _case(**kw):
    base = dict(missile="cn_pl12", range_m=50000.0, alt_m=10000.0, vm0=300.0, vt=-300.0,
                dv_target=932.57, bc_target=3078.05, dt=0.01)
    base.update(kw)
    return NativeCase(**base)


def _result(**kw):
    base = dict(ok=True, event="proximity_fuse", t_end=45.099, t_hit=45.099, hit=True,
                miss_distance_m=10.0, max_alt_m=12723.0, v_impact=617.2,
                dv_measured=795.5, m_launch=198.0, m_dry=132.0, t_burnout=7.45,
                thrust_scale=1.0, cx_scale=1.0, dv_blk=932.57, bc_blk=3078.05,
                resource="native")
    base.update(kw)
    return NativeResult(**base)


STD = {"name": "PL-12", "tag": "WORK", "profile_hash": "11c528f6f2d828d1",
       "cxk": 1.325, "loft_deg": 20.0}
RT = {"pkg": r"E:\WT\wt-missile-backend-runtime-1.0.1", "version": VERSION_28,
      "elf_sha256": ELF_SHA256_28}


# --------------------------------------------------------------------- 记录契约

def test_record_has_all_documented_sections():
    rec = mrec.to_record(_result(), _case(), standard=STD, runtime_info=RT)
    assert set(rec.to_dict()) >= {"case_id", "inputs", "scales", "engine", "outcome",
                                 "model", "samples", "schema", "warnings"}
    assert rec.schema == CALC_VERSION
    assert rec.ok and rec.hit
    assert rec.inputs["standard"] == "PL-12"
    assert rec.inputs["dv"] == pytest.approx(932.57)
    assert rec.inputs["conditions"]["range_m"] == pytest.approx(50000.0)
    assert rec.model["elf_sha256"] == ELF_SHA256_28
    assert rec.model["dt_s"] == pytest.approx(0.01)
    assert rec.model["resource"] == "native"


def test_record_case_id_matches_case_key():
    case = _case()
    rec = mrec.to_record(_result(), case, standard=STD, runtime_info=RT)
    assert rec.case_id == case.key()


def test_record_inputs_are_json_serializable_and_stable():
    rec = mrec.to_record(_result(), _case(), standard=STD, runtime_info=RT)
    a = json.dumps(rec.to_dict(), sort_keys=True, ensure_ascii=False)
    b = json.dumps(rec.to_dict(), sort_keys=True, ensure_ascii=False)
    assert a == b
    assert len(a) > 200


def test_record_loss_percent_is_derived_from_vacuum_dv():
    rec = mrec.to_record(_result(dv_measured=795.5), _case(dv_target=932.57),
                         standard=STD, runtime_info=RT)
    assert rec.engine["loss_pct"] == pytest.approx((1 - 795.5 / 932.57) * 100, rel=1e-6)


def test_record_scales_carry_used_cxk():
    rec = mrec.to_record(_result(cx_scale=1.05), _case(), standard=STD, runtime_info=RT)
    assert rec.scales["cx_scale"] == pytest.approx(1.05)
    assert rec.scales["cxk_used"] == pytest.approx(1.325 * 1.05)


def test_record_nominal_scale_is_one_for_nominal_dv_bc():
    """(ΔV, BC) 取该型标称值 ⇒ 两个乘数应为 1（模型层自算的应有结果）。"""
    rec = mrec.to_record(_result(), _case(), standard=STD, runtime_info=RT)
    assert rec.scales["thrust_scale"] == pytest.approx(1.0)
    assert rec.scales["cx_scale"] == pytest.approx(1.0)


# --------------------------------------------------------------------- 失败与未命中

def test_record_records_failure_without_lying():
    res = NativeResult(ok=False, error="RuntimeError: Non-finite native state")
    rec = mrec.to_record(res, _case(), standard=STD, runtime_info=RT)
    assert not rec.ok and not rec.hit
    assert rec.t_hit is None
    assert "原生执行失败" in rec.warnings[0]
    assert rec.outcome["error"]


def test_record_records_miss_with_event():
    res = _result(hit=False, t_hit=math.nan, event="time_limit")
    rec = mrec.to_record(res, _case(), standard=STD, runtime_info=RT)
    assert not rec.hit and rec.ok
    assert rec.t_hit is None                       # 未命中不得写成 0 或 NaN
    assert any("未命中" in w for w in rec.warnings)


def test_record_marks_cache_hits():
    rec = mrec.to_record(_result(cache_hit=True), _case(), standard=STD, runtime_info=RT)
    assert any("缓存" in w for w in rec.warnings)


def test_record_marks_injected_resource():
    rec = mrec.to_record(_result(resource="INJECTED il_derby.blkx"),
                         _case(missile="il_derby"), standard=STD, runtime_info=RT)
    assert rec.model["resource"] == "INJECTED il_derby.blkx"


def test_record_without_runtime_info_falls_back_to_registered_identity():
    rec = mrec.to_record(_result(), _case(), standard=STD)
    assert rec.model["elf_sha256"] == ELF_SHA256_28
    assert rec.model["version"] == VERSION_28


def test_record_without_standard_leaves_none_not_fake_values():
    rec = mrec.to_record(_result(), _case(), runtime_info=RT)
    assert rec.inputs["standard"] is None
    assert rec.inputs["profile_hash"] is None


# --------------------------------------------------------------------- 采样抽稀

def test_downsample_keeps_endpoints_and_caps_rate():
    samples = [{"t": i * 0.05, "x": i, "y": 0.0, "v": 100.0, "mass": 100.0,
                "thrust": 0.0, "range": 1000.0} for i in range(200)]      # 10 s @20 Hz
    out = mrec.downsample(samples, per_second=4.0)
    assert out[0]["t"] == pytest.approx(0.0)
    assert out[-1]["t"] == pytest.approx(samples[-1]["t"])
    assert len(out) <= 4.0 * 10 + 2
    assert len(out) < len(samples)


def test_downsample_keeps_only_declared_fields():
    samples = [{"t": 0.0, "x": 1.0, "y": 2.0, "v": 3.0, "mass": 4.0, "thrust": 5.0,
                "range": 6.0, "junk": "x"}]
    out = mrec.downsample(samples)
    assert "junk" not in out[0]


def test_downsample_empty():
    assert mrec.downsample([]) == []


# --------------------------------------------------------------------- 表读写

def test_write_read_json_roundtrip():
    d = Path(tempfile.mkdtemp())
    recs = [mrec.to_record(_result(), _case(), standard=STD, runtime_info=RT),
            mrec.to_record(_result(t_hit=math.nan, hit=False, event="time_limit"),
                           _case(dv_target=1500.0), standard=STD, runtime_info=RT)]
    p = mrec.write_table(recs, d / "cases.json")
    back = mrec.read_table(p)
    assert len(back) == 2
    assert back[0].case_id == recs[0].case_id
    assert back[0].t_hit == pytest.approx(45.099)
    assert back[1].hit is False


def test_write_csv_has_expected_columns_and_nan_handling():
    d = Path(tempfile.mkdtemp())
    recs = [mrec.to_record(_result(), _case(), standard=STD, runtime_info=RT)]
    p = mrec.write_table(recs, d / "cases.csv")
    text = p.read_text(encoding="utf-8")
    header = text.splitlines()[0].split(",")
    for col in ("case_id", "dv", "bc", "thrust_scale", "cx_scale", "hit", "t_hit",
                "v_impact", "resource"):
        assert col in header, col
    assert text.splitlines()[1].count(",") == len(header) - 1


def test_write_table_rejects_unknown_format():
    d = Path(tempfile.mkdtemp())
    with pytest.raises(ValueError):
        mrec.write_table([], d / "x.txt")


def test_read_table_accepts_wrapped_json():
    d = Path(tempfile.mkdtemp())
    rec = mrec.to_record(_result(), _case(), standard=STD, runtime_info=RT)
    p = d / "wrapped.json"
    p.write_text(json.dumps({"records": [rec.to_dict()]}), encoding="utf-8")
    assert len(mrec.read_table(p)) == 1


# --------------------------------------------------------------------- 指纹与时效

def test_digest_is_order_insensitive_for_dicts():
    assert mrec.digest_of({"a": 1, "b": 2}) == mrec.digest_of({"b": 2, "a": 1})
    assert mrec.digest_of({"a": 1}) != mrec.digest_of({"a": 2})


def _manifest():
    inputs = {"standard": "PL-12", "conditions": {"range_m": 50000.0}}
    return mrec.make_manifest(run_id="20260925_120000_abc", inputs=inputs,
                              grid={"n_dv": 32, "n_bc": 57},
                              calculator={"dt": 0.01, "observation_mode": "ideal"},
                              cache={"entries_used": 0}, stats={"wall_s": 1.0})


def test_manifest_has_versions_and_digests():
    m = _manifest()
    assert m["schema"] == CALC_VERSION
    assert m["calculator"]["calc_version"] == CALC_VERSION
    assert m["calculator"]["elf_sha256"] == ELF_SHA256_28
    assert len(m["inputs_digest"]) == 16 and len(m["calculator_digest"]) == 16


def test_staleness_fresh_when_nothing_changed():
    m = _manifest()
    st = mrec.check_staleness(m, current_inputs=m["inputs"],
                              current_calculator={"dt": 0.01, "observation_mode": "ideal"})
    assert st["stale"] is False and st["reasons"] == []


def test_staleness_detects_changed_inputs():
    m = _manifest()
    st = mrec.check_staleness(m, current_inputs={"standard": "120C"})
    assert st["stale"] and "stale_inputs" in st["reasons"]


def test_staleness_detects_changed_calculator():
    m = _manifest()
    st = mrec.check_staleness(m, current_calculator={"dt": 0.005, "observation_mode": "ideal"})
    assert st["stale"] and "stale_calculator" in st["reasons"]


def test_staleness_detects_old_schema():
    m = _manifest()
    m["schema"] = CALC_VERSION - 1
    st = mrec.check_staleness(m)
    assert st["stale"] and "stale_calculator" in st["reasons"]


def test_staleness_without_current_values_only_checks_schema():
    m = _manifest()
    assert mrec.check_staleness(m)["stale"] is False

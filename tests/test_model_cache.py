# -*- coding: utf-8 -*-
"""模型层 3（缓存）自检：版本戳失效、读写往返、损坏容忍。

**为什么单独测这个**：原生跑一轮是小时级，缓存是"只做一次"的前提；
而缓存失效一旦漏了，旧公式的结果会被静默当成新结果（本项目踩过：
410 条 `dv_blk=536.9` 的坏条目让 t_hit 从 45.1 变成 25.6）。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from missile_sim.model.cache import ProCache
from missile_sim.model.constants import CACHE_SCHEMA
from missile_sim.model.native import NativeResult


def _result(**kw):
    base = dict(ok=True, event="proximity_fuse", t_end=45.099, t_hit=45.099, hit=True,
                miss_distance_m=10.0, max_alt_m=12723.0, v_impact=617.2, dv_measured=795.5,
                m_launch=198.0, m_dry=132.0, t_burnout=7.45, thrust_scale=1.0, cx_scale=1.0,
                dv_blk=932.57, bc_blk=3078.05, resource="native")
    base.update(kw)
    return NativeResult(**base)


# --------------------------------------------------------------------- 往返

def test_put_get_save_load_roundtrip():
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    c = ProCache(p)
    assert c.get("k1") is None
    c.put("k1", _result())
    assert c.save() == p
    c2 = ProCache(p)
    got = c2.get("k1")
    assert got is not None and got.ok and got.cache_hit
    assert got.t_end == pytest.approx(45.099)
    assert got.resource == "native"


def test_save_writes_schema_and_note():
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    c = ProCache(p)
    c.put("k", _result())
    c.save(runtime_info={"pkg": "X", "version": "2.59.0.28"})
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["schema"] == CACHE_SCHEMA
    assert doc["n_entries"] == 1
    assert doc["runtime"]["version"] == "2.59.0.28"


def test_disabled_cache_writes_nothing():
    d = Path(tempfile.mkdtemp())
    c = ProCache(d / "never.json", enabled=False)
    c.put("k", _result())
    assert c.save() is None
    assert not (d / "never.json").exists()
    assert c.get("k") is None


def test_save_is_noop_when_clean():
    d = Path(tempfile.mkdtemp())
    c = ProCache(d / "c.json")
    assert c.save() is None                     # 没有新条目就不写盘
    assert not (d / "c.json").exists()


def test_save_is_atomic_leftover_tmp_is_replaced():
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    (d / "c.json.tmp").write_text("garbage", encoding="utf-8")
    c = ProCache(p)
    c.put("k", _result())
    c.save()
    assert json.loads(p.read_text(encoding="utf-8"))["n_entries"] == 1
    assert not (d / "c.json.tmp").exists()


# --------------------------------------------------------------------- 版本失效

def test_old_schema_invalidates_whole_cache():
    """schema 不符 ⇒ 整体作废（这是防止旧公式结果污染的唯一开关）。"""
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    p.write_text(json.dumps({"schema": CACHE_SCHEMA - 1,
                             "entries": {"k": _result().to_dict()}}), encoding="utf-8")
    c = ProCache(p)
    assert c.stale is True
    assert c.get("k") is None
    assert c.data == {}


def test_matching_schema_keeps_entries():
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    p.write_text(json.dumps({"schema": CACHE_SCHEMA,
                             "entries": {"k": _result().to_dict()}}), encoding="utf-8")
    c = ProCache(p)
    assert c.stale is False
    assert c.get("k") is not None


def test_explicit_schema_override_separates_corpora():
    """同一文件里两套 schema 可以互不相认（用于并行实验/灰度）。"""
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    c1 = ProCache(p, schema=CACHE_SCHEMA)
    c1.put("k", _result())
    c1.save()
    c_other = ProCache(p, schema=CACHE_SCHEMA + 1)
    assert c_other.stale is True and c_other.get("k") is None
    c_same = ProCache(p, schema=CACHE_SCHEMA)
    assert c_same.get("k") is not None


def test_corrupt_file_is_treated_as_empty_not_crash():
    d = Path(tempfile.mkdtemp())
    p = d / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    c = ProCache(p)
    assert c.get("x") is None and c.data == {}


def test_wrong_type_document_is_tolerated():
    d = Path(tempfile.mkdtemp())
    p = d / "weird.json"
    p.write_text(json.dumps({"schema": "not-an-int", "entries": []}), encoding="utf-8")
    c = ProCache(p)
    assert c.data == {}


def test_entries_survive_unknown_extra_keys():
    """旧记录多出的字段不能让读回失败（向前兼容）。"""
    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    d0 = _result().to_dict()
    d0["some_future_field"] = 123
    p.write_text(json.dumps({"schema": CACHE_SCHEMA, "entries": {"k": d0}}), encoding="utf-8")
    got = ProCache(p).get("k")
    assert got is not None and got.ok


def test_failed_results_are_not_cached_by_runner():
    """失败的工况不写缓存：否则一次网络/路径问题会被永久记住。

    `bare=True` = 明确要求**不要引擎**，走模块级 `simulate_native`（打桩点）。
    """
    from missile_sim.model import runner as runner_mod
    from missile_sim.model.native import NativeCase

    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    runner = runner_mod.ProRunner(jobs=1, cache=ProCache(p), bare=True)

    def fake_fail(case, pkg=None, **kw):
        return NativeResult(ok=False, error="boom")

    saved = runner_mod.simulate_native
    runner_mod.simulate_native = fake_fail
    try:
        res = runner.run_one(NativeCase(missile="cn_pl12"))
    finally:
        runner_mod.simulate_native = saved
        runner.close()
    assert not res.ok
    doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"n_entries": 0}
    assert doc.get("n_entries", 0) == 0


def test_failed_results_are_not_cached_when_engine_fails():
    """同上，但打桩点在**引擎契约**上（结构化 API 的正门）。"""
    from missile_sim.model import io as mio
    from missile_sim.model import runner as runner_mod
    from missile_sim.model.native import NativeCase, NativeResult, ProEngine

    d = Path(tempfile.mkdtemp())
    p = d / "c.json"
    runner = runner_mod.ProRunner(jobs=1, cache=ProCache(p))

    def fake_simulate(self, inp, env=None):
        return NativeResult(ok=False, error="boom")

    saved = ProEngine.simulate
    ProEngine.simulate = fake_simulate
    try:
        case = NativeCase(missile="cn_pl12", dv_target=932.5697486487783,
                          bc_target=3078.0530156224613)
        res = runner.run_inputs(mio.inputs_from_case(case))
    finally:
        ProEngine.simulate = saved
        runner.close()
    assert not res.ok
    doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"n_entries": 0}
    assert doc.get("n_entries", 0) == 0

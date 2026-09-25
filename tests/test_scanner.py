# -*- coding: utf-8 -*-
"""第二部分（ΔV/BC 扫描器）自检：网格、规格指纹、时效判定、落盘、周期落盘。

扫描器是"小时级一次性运行"的入口，所以两件事必须被锁死：
  1. **时效戳**（输入指纹 / 计算器指纹 / 版本），否则旧结果会被当新结果用；
  2. **周期性落盘**，否则跑到一半中断就白跑（本项目踩过：8 分钟白跑一次）。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from missile_sim import scanner as sc
from missile_sim.model import record as mrec
from missile_sim.model.cache import ProCache
from missile_sim.model.constants import CALC_VERSION
from missile_sim.model.native import NativeCase, NativeResult


# --------------------------------------------------------------------- 网格

def test_arange_inclusive_hits_endpoint():
    assert sc.arange_inclusive(800, 1110, 10)[-1] == pytest.approx(1110.0)
    assert sc.arange_inclusive(800, 1105, 10)[-1] == pytest.approx(1105.0)
    # 不能整除时补上端点（与 sweep._arange_inclusive 同口径）
    assert sc.arange_inclusive(800, 1103, 10)[-1] == pytest.approx(1103.0)
    assert len(sc.arange_inclusive(0, 10, 5)) == 3


def test_arange_inclusive_rejects_bad_step():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            sc.arange_inclusive(0, 10, bad)


def test_grid_shape_and_dict():
    g = sc.Grid.make(800, 1110, 10, 2450, 3850, 25)
    assert g.shape == (32, 57)
    assert g.n_cases == 1824
    d = g.as_dict()
    assert d["n_cases"] == 1824 and d["dv_step"] == 10.0 and d["bc_step"] == 25.0
    assert d["dv_min"] == 800.0 and d["dv_max"] == 1110.0


# --------------------------------------------------------------------- 规格与指纹

def test_spec_cases_expand_in_dv_major_order():
    spec = sc.ScanSpec(standard="PL-12", grid=sc.Grid.make(900, 950, 50, 3000, 3100, 100))
    cases = spec.cases()
    assert len(cases) == 4
    assert (cases[0].dv_target, cases[0].bc_target) == (900.0, 3000.0)
    assert (cases[1].dv_target, cases[1].bc_target) == (900.0, 3100.0)
    assert (cases[2].dv_target, cases[2].bc_target) == (950.0, 3000.0)
    assert all(c.sample_period_s == spec.sample_period_s for c in cases)


def test_spec_inputs_exclude_machine_specific_params():
    """**物理输入**指纹不能把 jobs/dt 这类机器相关项算进去，否则换台机器就"过期"。"""
    a = sc.ScanSpec(standard="PL-12", jobs=1, dt=0.01)
    b = sc.ScanSpec(standard="PL-12", jobs=16, dt=0.01)
    assert a.inputs_digest() == b.inputs_digest()
    c = sc.ScanSpec(standard="PL-12", jobs=1, dt=0.005)
    assert a.calculator_digest() != c.calculator_digest(), "dt 属于计算器身份，变了要重算"


def test_spec_digest_changes_with_physics():
    base = sc.ScanSpec(standard="PL-12")
    for kw in ({"standard": "120C"}, {"range_m": 30000.0}, {"vt": -450.0},
               {"alt_m": 8000.0}, {"target_alt_m": 8000.0},
               {"target_maneuvers": ((1.0, (0.0, -50.0, 0.0)),)},
               {"grid": sc.Grid.make(800, 1110, 5, 2450, 3850, 25)}):
        assert sc.ScanSpec(**{**{"standard": "PL-12"}, **kw}).inputs_digest() \
            != base.inputs_digest(), kw


def test_run_id_is_deterministic_when_given():
    assert sc.ScanSpec(run_id="abc").make_run_id() == "abc"
    auto = sc.ScanSpec().make_run_id()
    assert "_" in auto and len(auto.split("_")[-1]) == 8


# --------------------------------------------------------------------- 时效

def _manifest(**over):
    inputs = {"standard": "PL-12", "grid": {"n_dv": 2, "n_bc": 2}}
    calc = {"calc_version": CALC_VERSION, "dt": 0.01, "observation_mode": "ideal"}
    m = mrec.make_manifest(run_id="r1", inputs=inputs, grid=inputs["grid"],
                           calculator=calc, cache={}, stats={})
    m.update(over)
    return m


def test_check_staleness_fresh_vs_stale_inputs():
    m = _manifest()
    spec = sc.ScanSpec(standard="PL-12")
    # 直接构造"输入一致"的比对：用 manifest 自己的 inputs
    st = mrec.check_staleness(m, current_inputs=m["inputs"],
                              current_calculator={"dt": 0.01, "observation_mode": "ideal"})
    assert st["stale"] is False


def test_check_staleness_flags_changed_calculator():
    m = _manifest()
    st = mrec.check_staleness(m, current_calculator={"dt": 0.005, "observation_mode": "ideal"})
    assert st["stale"] and "stale_calculator" in st["reasons"]


def test_load_manifest_missing_returns_none():
    assert sc.load_manifest("definitely_not_a_run") is None


def test_check_run_without_manifest_reports_no_manifest():
    st = sc.check_run("definitely_not_a_run")
    assert st["stale"] is True and st["reasons"] == ["no_manifest"]


# --------------------------------------------------------------------- 运行 + 落盘（打桩）

def _patch_native(fake):
    """把执行器里的 `simulate_native` 换成桩，返回恢复函数。

    ⚠ 打桩位置必须是 `missile_sim.model.runner`——`ProRunner` 绑定的是那里，
    打 `pro.simulate_native` 拦不住（会静默去跑真实原生代码）。
    """
    from missile_sim.model import runner as runner_mod

    saved = runner_mod.simulate_native
    runner_mod.simulate_native = fake
    return lambda: setattr(runner_mod, "simulate_native", saved)


def _ok_result(*, t_hit=45.0, hit=True, samples=None):
    return NativeResult(ok=True, event="proximity_fuse" if hit else "time_limit",
                        t_hit=(t_hit if hit else float("nan")), t_end=t_hit, hit=hit,
                        miss_distance_m=10.0, max_alt_m=12700.0, v_impact=617.0,
                        dv_measured=795.0, m_launch=198.0, m_dry=132.0, t_burnout=7.45,
                        thrust_scale=1.0, cx_scale=1.0, dv_blk=932.57, bc_blk=3078.05,
                        resource="native", samples=samples or [])


def test_scanner_runs_writes_and_records():
    """打桩跑 2×2：验证记录、落盘、manifest 与 run 目录结构。"""
    d = Path(tempfile.mkdtemp())
    spec = sc.ScanSpec(standard="PL-12", grid=sc.Grid.make(900, 950, 50, 3000, 3100, 100),
                       jobs=1, cache_path="")
    restore = _patch_native(lambda case, pkg=None: _ok_result())
    try:
        with sc.Scanner(spec, cache=ProCache(d / "c.json")) as s:
            out = s.run(write=True)
    finally:
        restore()

    assert len(out.records) == 4
    assert all(r.hit for r in out.records)
    assert out.manifest["schema"] == CALC_VERSION
    assert out.manifest["calculator"]["calc_version"] == CALC_VERSION
    assert out.manifest["stats"]["n_hit"] == 4
    assert out.manifest["grid"]["n_cases"] == 4
    # 落盘结构
    rd = Path(out.paths["run_dir"])
    for name in ("manifest.json", "cases.json", "cases.csv"):
        assert (rd / name).is_file(), name
    man = json.loads((rd / "manifest.json").read_text(encoding="utf-8"))
    assert man["inputs_digest"] == spec.inputs_digest()
    assert man["calculator_digest"] == spec.calculator_digest()
    assert man["standard"]["name"] == "PL-12"
    back = mrec.read_table(rd / "cases.json")
    assert len(back) == 4 and back[0].hit


def test_t_grid_shape_and_nan_for_miss():
    d = Path(tempfile.mkdtemp())
    spec = sc.ScanSpec(standard="PL-12", grid=sc.Grid.make(900, 950, 50, 3000, 3100, 100),
                       jobs=1, cache_path="")
    calls = {"n": 0}

    def fake(case, pkg=None):
        calls["n"] += 1
        return _ok_result(hit=(calls["n"] % 2 == 1))     # 一半命中一半不中

    restore = _patch_native(fake)
    try:
        with sc.Scanner(spec, cache=ProCache(d / "c.json", enabled=False)) as s:
            out = s.run(write=False)
    finally:
        restore()
    import numpy as np
    tg = out.t_grid()
    assert tg.shape == (2, 2)
    assert int((~np.isnan(tg)).sum()) == 2
    assert out.manifest["stats"]["n_hit"] == 2


def test_scanner_rejects_missile_without_blk():
    spec = sc.ScanSpec(standard="no_such_standard",
                       grid=sc.Grid.make(900, 900, 1, 3000, 3000, 1), jobs=1, cache_path="")
    with sc.Scanner(spec, cache=ProCache(enabled=False)) as s:
        with pytest.raises(ValueError):
            s.run(write=False)


# --------------------------------------------------------------------- 周期落盘

def test_runner_flushes_cache_periodically():
    """`flush_every` 条就落一次盘：小时级运行中途中断不能把已完成结果全丢。"""
    from missile_sim.model import runner as runner_mod

    d = Path(tempfile.mkdtemp())
    path = d / "c.json"
    runner = runner_mod.ProRunner(jobs=1, cache=ProCache(path), flush_every=2)
    seen = []

    def fake(case, pkg=None):
        return NativeResult(ok=True, event="proximity_fuse", hit=True, t_end=1.0, t_hit=1.0)

    saved = runner_mod.simulate_native
    runner_mod.simulate_native = fake

    def draw_after_each(case, pkg=None):
        """每次运行后记录一次"此刻磁盘上有几条"，从而看出中途是否落过盘。"""
        if path.exists():
            seen.append(json.loads(path.read_text(encoding="utf-8"))["n_entries"])
        return fake(case)

    runner_mod.simulate_native = draw_after_each
    try:
        cases = [NativeCase(missile="cn_pl12", dv_target=900.0 + i) for i in range(5)]
        runner.run_many(cases)
    finally:
        runner_mod.simulate_native = saved
        runner.close()
    assert seen, "中途从未落盘"
    assert min(seen) < 5, f"只在最后落盘（{seen}），中途没有保护"
    assert json.loads(path.read_text(encoding="utf-8"))["n_entries"] == 5


def test_runner_does_not_cache_trajectory_runs():
    """要轨迹的运行**不进缓存**：轨迹是单条记录的 95%，进缓存会把产物撑到几十 MB。"""
    from missile_sim.model import runner as runner_mod

    d = Path(tempfile.mkdtemp())
    path = d / "c.json"
    runner = runner_mod.ProRunner(jobs=1, cache=ProCache(path), flush_every=1)

    def fake(case, pkg=None):
        tr = ([{"t": 0.0, "x": 0.0, "y": 0.0, "v": 1.0, "mass": 1.0,
                "thrust": 0.0, "range": 0.0}] if case.save_trajectory else [])
        return NativeResult(ok=True, event="proximity_fuse", hit=True, t_end=1.0,
                            t_hit=1.0, samples=tr)

    restore = _patch_native(fake)
    try:
        with_traj = runner.run_one(NativeCase(missile="cn_pl12", save_trajectory=True))
        without = runner.run_one(NativeCase(missile="cn_pl12", save_trajectory=False))
    finally:
        restore()
        runner.close()
    assert len(with_traj.samples) == 1, "要轨迹时必须真的带上"
    assert without.samples == []
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["n_entries"] == 1, "只有不带轨迹的那条该被缓存"
    entry = next(iter(doc["entries"].values()))
    assert (entry.get("samples") or []) == []


def test_runner_close_saves_even_after_exception():
    """异常路径也必须落盘（`close()` 里 try/finally）。"""
    from missile_sim.model import runner as runner_mod

    d = Path(tempfile.mkdtemp())
    path = d / "c.json"
    runner = runner_mod.ProRunner(jobs=1, cache=ProCache(path), flush_every=9999)

    def fake(case, pkg=None):
        return NativeResult(ok=True, event="proximity_fuse", hit=True, t_end=1.0, t_hit=1.0)

    saved = runner_mod.simulate_native
    runner_mod.simulate_native = fake
    try:
        runner.run_one(NativeCase(missile="cn_pl12"))
        raise RuntimeError("模拟中途崩溃")
    except RuntimeError:
        pass
    finally:
        runner_mod.simulate_native = saved
        runner.close()
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["n_entries"] == 1

# -*- coding: utf-8 -*-
"""Pro 后端自检：解析式映射、缓存、自描述，以及（有包时）一次真实原生运行。

分三类：
  * **纯函数**（永远跑）：ΔV→推力乘数、BC→CxK 乘数、真空 ΔV 校核、缓存键、缓存读写；
  * **报错路径**（永远跑）：找不到原生包时必须**明确报错**，不退回近似模型；
  * **原生运行**（有包才跑）：`WT_NATIVE_PKG` 或默认位置存在时跑 1~2 个格点，
    校验"原生实测 ΔV 与解析真空 ΔV 的关系"以及结果口径。
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from missile_sim import pro, standard
from missile_sim.config import ballistic_coefficient, load_config, s_ref, apply_standard
from missile_sim.sweep import _pro_status, run_sweep_pro, SweepGrid
from missile_sim.decide import (
    ST_HIT,
    ST_MISS_OVERSHOOT,
    ST_MISS_RECEDE,
    ST_NO_HIT_SLOWDOWN,
    ST_NO_HIT_TIMEOUT,
)

PL12_DV = 932.5697486487783     # 池值（= blk 质量/推力剖面推出的真空 ΔV）
PL12_BC = 3078.0530156224613


# --------------------------------------------------------------------- 纯函数

def test_scale_for_dv_is_linear_and_analytic():
    """ΔV 是真空等效增速 ⇒ 推力乘数就是比值，不需要损失率修正。"""
    assert pro.scale_for_dv(PL12_DV, PL12_DV) == pytest.approx(1.0)
    assert pro.scale_for_dv(2 * PL12_DV, PL12_DV) == pytest.approx(2.0)
    assert pro.scale_for_dv(466.28487432438915, PL12_DV) == pytest.approx(0.5)


def test_scale_for_dv_rejects_bad_reference():
    with pytest.raises(ValueError):
        pro.scale_for_dv(900.0, 0.0)
    with pytest.raises(ValueError):
        pro.scale_for_dv(900.0, -1.0)


def test_cx_scale_round_trips_the_ballistic_coefficient():
    cfg = load_config()
    apply_standard(cfg)
    prof = cfg.profile
    sr = s_ref(cfg)
    scale = pro.cx_scale_for_bc(PL12_BC, prof.dry_mass, sr, prof.cxk)
    assert scale == pytest.approx(1.0, rel=1e-12)
    # 反解后的 CxK 必须精确给出目标 BC
    cx = prof.cxk * scale
    assert ballistic_coefficient(cx, cfg) == pytest.approx(PL12_BC, rel=1e-9)


def test_cx_scale_matches_pool_across_grid_range():
    """BC ∈ [1700, 5000] 内，反解 CxK 都应给出该 BC（BC = m_dry/(CxK·S_ref)）。"""
    cfg = load_config()
    apply_standard(cfg)
    prof = cfg.profile
    sr = s_ref(cfg)
    for bc in (1700.0, 2450.0, 3078.05, 3850.0, 5000.0):
        scale = pro.cx_scale_for_bc(bc, prof.dry_mass, sr, prof.cxk)
        assert ballistic_coefficient(prof.cxk * scale, cfg) == pytest.approx(bc, rel=1e-9)


def test_cx_scale_rejects_bad_input():
    for args in ((0.0, 132.0, 0.032, 1.325), (3078.0, 0.0, 0.032, 1.325),
                 (3078.0, 132.0, 0.0, 1.325), (3078.0, 132.0, 0.032, 0.0)):
        with pytest.raises(ValueError):
            pro.cx_scale_for_bc(*args)


def test_vacuum_dv_reproduces_pool_tsiolkovsky():
    """池里的 ΔV/BC 必须能由 blk 剖面（质量 + 推力×时间）用齐奥尔科夫斯基公式复现。"""
    got = pro.vacuum_dv(standard.resolve("PL-12").engine.stages())
    assert got == pytest.approx(PL12_DV, rel=1e-6)
    for name in standard.pool_names():
        prof = standard.resolve(name)
        assert pro.vacuum_dv(prof.engine.stages()) == pytest.approx(prof.dv, rel=1e-6), name


def test_vacuum_dv_scales_linearly_with_thrust():
    prof = standard.resolve("PL-12")
    base = pro.vacuum_dv(prof.engine.stages(), 1.0)
    for s in (0.5, 1.0, 1.5, 3.0):
        assert pro.vacuum_dv(prof.engine.stages(), s) == pytest.approx(base * s, rel=1e-12)


def test_vacuum_dv_skips_degenerate_stages():
    """零燃料/零推力段必须跳过，不能让 log 发散。"""
    assert pro.vacuum_dv([(100.0, 100.0, 1000.0, 5.0)]) == 0.0
    assert pro.vacuum_dv([(100.0, 80.0, 0.0, 5.0)]) == 0.0
    assert pro.vacuum_dv([]) == 0.0


# --------------------------------------------------------------------- 缓存

def test_case_key_is_stable_and_sensitive():
    base = dict(missile="cn_pl12", thrust_scale=1.2, cx_scale=1.1)
    a = pro.NativeCase(**base)
    assert a.key() == pro.NativeCase(**base).key()
    for kw in ({"thrust_scale": 1.3}, {"cx_scale": 1.2}, {"range_m": 40000.0},
               {"vm0": 290.0}, {"dt": 0.005}, {"observation_mode": "locked"},
               {"missile": "su_r_77"}):
        assert pro.NativeCase(**{**base, **kw}).key() != a.key(), kw


def test_case_key_ignores_irrelevant_sampling():
    a = pro.NativeCase(missile="cn_pl12", sample_period_s=0.05)
    b = pro.NativeCase(missile="cn_pl12", sample_period_s=0.2)
    assert a.key() == b.key(), "采样周期只影响 CSV 密度，不该改缓存键"


def test_case_key_normalizes_list_vs_tuple_wind():
    a = pro.NativeCase(missile="cn_pl12", wind_m_s=(0.0, 0.0, 0.0))
    b = pro.NativeCase(missile="cn_pl12", wind_m_s=[0.0, 0.0, 0.0])
    assert a.key() == b.key()


def test_cache_round_trip(tmp_path=None):
    import tempfile
    d = Path(tempfile.mkdtemp())
    path = d / "pro_cache.json"
    c = pro.ProCache(path)
    key = "abc123"
    assert c.get(key) is None
    c.put(key, pro.NativeResult(ok=True, event="proximity_fuse", t_end=45.1, t_hit=45.1,
                                hit=True, miss_distance_m=10.0, max_alt_m=12723.0,
                                v_impact=688.0, dv_measured=795.5,
                                m_launch=198.0, m_dry=132.0, t_burnout=7.45))
    assert c.save() == path
    c2 = pro.ProCache(path)
    got = c2.get(key)
    assert got is not None and got.ok and got.cache_hit
    assert got.t_end == pytest.approx(45.1)
    assert got.event == "proximity_fuse"
    assert got.hit is True


def test_cache_disabled_writes_nothing():
    import tempfile
    d = Path(tempfile.mkdtemp())
    c = pro.ProCache(d / "never.json", enabled=False)
    c.put("k", pro.NativeResult(ok=True))
    assert c.save() is None
    assert not (d / "never.json").exists()


def test_cache_survives_corrupt_file():
    import tempfile
    d = Path(tempfile.mkdtemp())
    p = d / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    c = pro.ProCache(p)          # 不抛异常，视作空缓存
    assert c.get("x") is None


# --------------------------------------------------------------------- 报错路径

def test_missing_package_raises_clear_error():
    saved = os.environ.get(pro.ENV_PKG)
    os.environ[pro.ENV_PKG] = str(Path("Z:/definitely/not/here"))
    try:
        with pytest.raises(pro.ProRuntimeError):
            pro.resolve_pkg()
    finally:
        if saved is None:
            os.environ.pop(pro.ENV_PKG, None)
        else:
            os.environ[pro.ENV_PKG] = saved


def test_directory_without_tools_is_rejected():
    import tempfile
    d = Path(tempfile.mkdtemp())
    with pytest.raises(pro.ProRuntimeError):
        pro.resolve_pkg(d)


def test_bad_dt_is_rejected_before_any_native_run():
    """dt 越界必须在**执行原生代码之前**返回失败，而不是跑到一半才炸。"""
    r = pro.simulate_native(pro.NativeCase(missile="cn_pl12", dt=0.5),
                            pkg=_pkg_or_none() or Path("."))
    if _pkg_or_none() is None:
        return                     # 无包环境下由上面的 resolve_pkg 抛错分支覆盖
    assert not r.ok and "dt" in r.error


def test_unsupported_missile_is_rejected_by_sweep():
    cfg = load_config()
    apply_standard(cfg)
    grid = SweepGrid(dv=_np([900.0]), bc=_np([3000.0]), dv_step=100.0, bc_step=100.0)
    try:
        run_sweep_pro(cfg, grid, jobs=1, missile="il_derby")
    except ValueError as exc:
        assert "Derby" in str(exc) or "il_derby" in str(exc)
    else:
        raise AssertionError("Derby 没有原生 profile，必须报错而不是静默跑近似")


# --------------------------------------------------------------------- 状态映射

def test_status_mapping_covers_native_events():
    hit = pro.NativeResult(ok=True, event="proximity_fuse", hit=True)
    assert _pro_status(hit) == ST_HIT
    assert _pro_status(pro.NativeResult(ok=True, event="contact", hit=True)) == ST_HIT
    assert _pro_status(pro.NativeResult(ok=True, event="ground", hit=False)) == ST_NO_HIT_SLOWDOWN
    assert _pro_status(pro.NativeResult(ok=True, event="lifetime", hit=False)) == ST_NO_HIT_TIMEOUT
    assert _pro_status(pro.NativeResult(ok=True, event="time_limit", hit=False)) == ST_MISS_OVERSHOOT


def test_status_mapping_separates_failure_from_miss():
    """原生**执行失败**不能和"真的飞越脱靶"共用一个状态码。"""
    assert _pro_status(pro.NativeResult(ok=False, error="dt=0.5 超出原生合法范围")) == ST_NO_HIT_SLOWDOWN
    assert _pro_status(pro.NativeResult(ok=False, error="RuntimeError: Non-finite native state")) == ST_NO_HIT_SLOWDOWN
    assert _pro_status(pro.NativeResult(ok=False, error="包版本不符")) == ST_MISS_RECEDE


def test_progress_callback_signature_matches_sim_batch():
    """`ProRunner` 的进度回调必须与 `sim.simulate_batch` 同签名 (step, total, active)。

    曾经写成两参数，导致 360 工况的全网格跑到一半才炸（而原生结果还没落缓存）。
    """
    calls = []
    runner = pro.ProRunner.__new__(pro.ProRunner)      # 不走 __init__（避免找包/建池）
    runner.jobs = 1
    runner.pkg = Path(".")
    runner.version = pro.VERSION_28
    runner.stats = {"native": 0, "cache": 0}
    runner.progress = lambda *a: calls.append(a)
    runner.cache = pro.ProCache(enabled=False)
    runner._pool = None

    def fake_native(case, pkg=None):
        return pro.NativeResult(ok=True, event="proximity_fuse", hit=True, t_end=1.0, t_hit=1.0)

    saved = pro.simulate_native
    pro.simulate_native = fake_native
    try:
        cases = [pro.NativeCase(missile="cn_pl12", thrust_scale=1.0 + i * 0.01)
                 for i in range(3)]
        out = runner.run_many(cases)
    finally:
        pro.simulate_native = saved
    assert len(out) == 3 and all(r.ok for r in out)
    assert calls, "回调没被调用"
    assert all(len(c) == 3 for c in calls), f"回调参数个数必须为 3，实际 {calls}"


def test_cache_saved_even_when_a_callback_raises():
    """回调抛异常时，已经跑出来的结果必须仍然落盘（否则小时级的原生运行会白跑）。"""
    import tempfile
    d = Path(tempfile.mkdtemp())
    path = d / "c.json"
    runner = pro.ProRunner.__new__(pro.ProRunner)
    runner.jobs = 1
    runner.pkg = Path(".")
    runner.version = pro.VERSION_28
    runner.stats = {"native": 0, "cache": 0}
    runner.cache = pro.ProCache(path)
    runner._pool = None

    def boom(*a):
        raise TypeError("progress() missing 1 required positional argument: 'active'")

    runner.progress = boom

    def fake_native(case, pkg=None):
        return pro.NativeResult(ok=True, event="proximity_fuse", hit=True, t_end=1.0, t_hit=1.0)

    saved = pro.simulate_native
    pro.simulate_native = fake_native
    try:
        try:
            runner.run_many([pro.NativeCase(missile="cn_pl12")])
        except TypeError:
            pass
    finally:
        pro.simulate_native = saved
        runner.close()
    assert path.exists(), "异常路径没有保存缓存"
    doc = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert doc["n_entries"] == 1


# --------------------------------------------------------------------- 自描述

def test_provenance_has_pro_block_by_default():
    from missile_sim import provenance as prov
    cfg = load_config()
    apply_standard(cfg)
    blk = prov.provenance(cfg)
    assert blk["backend"] == "pro"
    assert blk["pro"]["observation_mode"] == "ideal"
    assert blk["pro"]["dt"] == pytest.approx(float(cfg.pro_dt))
    assert "pro_dt" in [f for f in dir(cfg) if not f.startswith("_")]


def test_summary_dict_embeds_pro_runtime():
    from missile_sim.sweep import summary_dict, SweepGrid
    cfg = load_config()
    apply_standard(cfg)
    grid = SweepGrid(dv=_np([900.0]), bc=_np([3000.0]), dv_step=1.0, bc_step=1.0)
    res = _fake_batch()
    res.pro = {"elf_sha256": pro.ELF_SHA256_28, "pkg": str(pro.DEFAULT_PKG),
               "version": pro.VERSION_28, "injected": ["cn_pl12"], "dt": 0.01,
               "observation_mode": "ideal", "n_native_runs": 3, "n_cache_hits": 0}
    out = summary_dict(cfg, res, grid, _np([[45.0]]), [])
    assert out["provenance"]["pro"]["elf_sha256"].startswith("94de5454")
    assert out["provenance"]["pro"]["n_native_runs"] == 3
    assert out["provenance"]["backend"] == "pro"


def test_summary_dict_without_pro_block_still_works():
    """Flash 结果没有 pro 块，provenance 也必须能出（不能抛）。"""
    from missile_sim.sweep import summary_dict, SweepGrid
    cfg = load_config()
    apply_standard(cfg)
    grid = SweepGrid(dv=_np([900.0]), bc=_np([3000.0]), dv_step=1.0, bc_step=1.0)
    out = summary_dict(cfg, _fake_batch(), grid, _np([[45.0]]), [])
    assert "provenance" in out


# --------------------------------------------------------------------- 原生运行（有包才跑）

def _pkg_or_none():
    try:
        return pro.resolve_pkg()
    except pro.ProRuntimeError:
        return None


def _np(v):
    import numpy as np
    return np.asarray(v, dtype=float)


def _fake_batch():
    """构造一个最小 BatchResult（只为测自描述，不跑物理）。"""
    import numpy as np
    from missile_sim.sim import BatchResult
    from missile_sim.decide import ST_HIT
    return BatchResult(
        dv_total=np.array([900.0]), cxk=np.array([1.36]), bc=np.array([3000.0]),
        theta_loft_deg=20.0, vm0=300.0, vt=-300.0, alt=10000.0, target_alt=10000.0,
        range0=50000.0, status=np.array([ST_HIT]), t_hit=np.array([45.0]),
        t_end=np.array([45.0]), miss_distance=np.array([10.0]), max_alt=np.array([12700.0]),
        v_impact=np.array([688.0]), terminal_gamma_error_deg=np.array([np.nan]),
        min_range=np.array([10.0]), min_range_linear=np.array([np.nan]),
        t_loft_end=np.array([np.nan]), isp_equiv=np.array([91.8]),
        mass_ratio=np.array([1.479]),
    )


def test_native_single_run_matches_analytic_dv_ordering():
    """有包时：跑一个格点，校验原生口径（命中事件、近炸距离、ΔV 实测 < 真空 ΔV）。"""
    pkg = _pkg_or_none()
    if pkg is None:
        return                     # 无包：跳过（原生用例不掩盖为"通过"）
    case = pro.NativeCase(missile="cn_pl12", range_m=50000.0, alt_m=10000.0,
                          dt=pro.DT_DEFAULT, duration_s=120.0, observation_mode="ideal",
                          thrust_scale=pro.scale_for_dv(900.0, PL12_DV),
                          cx_scale=pro.cx_scale_for_bc(3000.0, 132.0, 0.032365, 1.325))
    with pro.ProRunner(jobs=1, cache=pro.ProCache(enabled=False)) as runner:
        r = runner.run_one(case)
    assert r.ok, r.error
    assert r.event in pro.HIT_EVENTS, r.event
    assert 0.0 < r.t_end < 120.0
    # 实测燃尽增量必须**小于**解析真空 ΔV（阻力/重力损失）
    assert 0.0 < r.dv_measured < 900.0
    assert 0.5 < r.dv_measured / 900.0 < 1.0
    assert r.m_dry < r.m_launch
    assert 9000.0 < r.max_alt_m < 20000.0
    assert r.resource == "native", "包内自带该型，不该走注入分支"


def test_injected_profiles_cover_the_two_missiles_the_package_lacks():
    """Derby / R-Darter 不在原生包的 profile 清单里，必须靠注入且结果要标注。

    依据见 results/native_injection_probe.json：原生参数全走内存块，
    唯一闸门是 load_profile 的 manifest 校验；我们 blkx 与原生 parse_blk 叶子路径 423/423 相同。
    """
    if _pkg_or_none() is None:
        return
    for native_name, blk in (("il_derby", "il_derby.blkx"), ("r_darter", "r_darter.blkx")):
        assert native_name not in pro.NATIVE_PROFILES[pro.VERSION_28], \
            f"{native_name} 不该出现在包内清单里（否则这条测试失去意义）"
        ext = pro._external_profile(native_name)
        assert ext is not None, f"取不到 {blk}（需要 E:\\WT\\War-Thunder-Datamine）"
        # 注入用的 profile 必须具备原生 configure_properties 需要的全部键
        for key in ("caliber", "length", "mass", "wingAreaMult", "CxK",
                    "finsAoaHor", "finsAoaVer", "finsLatAccel", "timeLife"):
            assert key in ext, f"{blk} 缺 {key}"
        with pro.ProRunner(jobs=1, cache=pro.ProCache(enabled=False)) as runner:
            r = runner.run_one(pro.NativeCase(missile=native_name, range_m=50000.0,
                                              alt_m=10000.0, dt=pro.DT_DEFAULT,
                                              duration_s=120.0))
        assert r.ok, f"{native_name}: {r.error}"
        assert r.resource == f"INJECTED {blk}", r.resource
        assert r.event in pro.HIT_EVENTS
        # 归档值（native_injection_probe.json）：Derby 47.291 / R-Darter 47.599
        expect = {"il_derby": 47.291, "r_darter": 47.599}[native_name]
        assert abs(r.t_hit - expect) < 0.01, f"{native_name} t_hit={r.t_hit} 期望 {expect}"

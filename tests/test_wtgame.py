# -*- coding: utf-8 -*-
"""wt-missile 引擎（`standard` / `fast`）自检：vendor 身份、输入映射、乘数施加、
金标对拍、两档一致性、拒绝路径。

**为什么单独测这个**：两档是**同一物理的两个算术后端**，它们与项目的唯一接缝是
`io.build_inputs` 算出的乘数 + `EngineInputs.cache_key()`。这条缝一旦错，产物不会报错，
只会安静地给出另一个物理的数字。所以这里钉三件事：

  ① vendor 只读副本没被动过（哈希 / 清单 / 预设计数）；
  ② `(ΔV, BC) → force* / CxK` 的乘数**确实**施加到了求解器加载的 profile 上，
     且**不污染**后续加载（`_patch_profile` 是就地改写，靠 `load_profile` 每次重新解析兜底）；
  ③ 金标工况对拍到原生基准（AIM-120D / 60 km / 双方 6000 m / 300 对 250 迎头 / ideal 观测）。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from missile_sim.model import io as mio          # noqa: E402
from missile_sim.model import registry as reg    # noqa: E402
from missile_sim.model import wtgame             # noqa: E402
from missile_sim.model.constants import (  # noqa: E402
    DT_DEFAULT,
    ELF_SHA256_28,
    SOLVER_DT,
    VERSION_28,
)

#: 原生金标（120D / 60 km / 双方 6000 m / 300 对 250 迎头 / `ideal`）的顶点高度，
#: 见 `docs/NEW-SOLVER-HANDOFF.md` §4。容差 10 m 远小于单步高度变化。
GOLD_MAX_ALT_M = 10629.9961
GOLD_TOL_M = 10.0

#: 求解器 168 个预设里有 12 个被**明确拒绝**（外环控制器 / 重复 `endSpeed`）。
#: 拒绝是设计行为（"不做近似替代"），不是缺陷 —— 所以要钉住数量，别哪天悄悄变成了近似。
N_PROFILES = 168
N_REJECTED = 12


def _cfg():
    return wtgame._selftest_cfg()


def _inputs(missile: str = "cn_pl12", **over):
    return mio.inputs_from_case(mio.build_case(_cfg(), missile=missile, **over))


_GOLD: dict = {}


def _gold(tier: str):
    """金标工况跑一次并缓存（60 s 时长、约 3 s；两条用例共用）。"""
    if tier not in _GOLD:
        inp = _inputs("us_aim_120d")
        inp = replace(inp, range_m=60000.0, alt_m=6000.0, target_alt_m=6000.0,
                      vm0=300.0, vt=-250.0, duration_s=60.0, observation_mode="ideal")
        _GOLD[tier] = reg.load_engine(tier).simulate(inp, None)
    return _GOLD[tier]


# --------------------------------------------------------------------- vendor 身份

def test_vendor_solver_matches_the_recorded_hash():
    """`vendor/wt-missile/` 是只读副本：哈希对不上说明它被改过（升级流程见 VENDOR.md）。"""
    p = wtgame.solver_file()
    assert p.is_file(), f"vendor 求解器不在：{p}"
    assert wtgame.file_sha256(p) == wtgame.SOLVER_SHA256
    assert p.stat().st_size == 141720
    notes = (wtgame.VENDOR_DIR / "VENDOR.md").read_text(encoding="utf-8")
    assert wtgame.SOLVER_SHA256.upper() in notes.upper(), \
        "VENDOR.md 里记的哈希与代码里的常量不一致"


def test_resource_manifest_identity():
    rt = wtgame.resource_identity()
    assert rt["solver_model"] == "python-game-6dof-v1"
    assert rt["solver_version"] == VERSION_28
    assert rt["n_profiles"] == N_PROFILES
    assert rt["resource_archive_sha256"] == (
        "303760d4897dd688fdc9d2503d1db8f6978c2d3bc6eef3d064ae2b48f26d6e9b")
    # 求解器**不执行 ELF**：它只是复刻，公式依据的那份 ELF 另记一层
    assert rt["elf_executed"] is False
    assert rt["formula_basis_elf_sha256"] == ELF_SHA256_28


def test_load_solver_rejects_a_tampered_copy():
    """哈希校验必须真的挡住：改了常量就等于要求一个不存在的副本。"""
    saved_mod, saved_sha = wtgame._SOLVER, wtgame.SOLVER_SHA256
    wtgame._SOLVER = None                                   # 绕开已加载的缓存
    wtgame.SOLVER_SHA256 = "0" * 64
    try:
        with pytest.raises(wtgame.SolverUnavailable):
            wtgame.load_solver(verify=True)
    finally:
        wtgame._SOLVER = saved_mod
        wtgame.SOLVER_SHA256 = saved_sha


# --------------------------------------------------------------------- 步长

def test_dt_for_uses_the_client_object_clock():
    """默认步长是求解器的**客户端对象时钟** 1/48 s，不是旧原生档的 `DT_DEFAULT`(0.01)。

    两者必须区分开：求解器见到 `DT_DEFAULT` 之外的"显式"步长会主动放弃 C 快路径。
    所以"没指定"（≤0）和"恰好等于 `DT_DEFAULT`"都按未指定处理、回落到 1/48 s，
    只有真正别的步长才透传。
    """
    inp = _inputs()
    assert float(inp.dt) == pytest.approx(SOLVER_DT)        # config.pro_dt 的默认值
    assert wtgame.dt_for(inp) == pytest.approx(SOLVER_DT)
    assert wtgame.dt_for(replace(inp, dt=0.0)) == pytest.approx(SOLVER_DT)
    assert wtgame.dt_for(replace(inp, dt=DT_DEFAULT)) == pytest.approx(SOLVER_DT)
    assert wtgame.dt_for(replace(inp, dt=1.0 / 96.0)) == pytest.approx(1.0 / 96.0)


def test_scenario_uses_the_fixed_step_policy():
    """`step_policy="fixed"` + `sample_period_s=None` 是"能走 C 快路径"的两个条件。"""
    scen = wtgame.scenario_from_inputs(_inputs(), tier="standard")
    assert scen["step_policy"] == "fixed"
    assert scen["sample_period_s"] is None
    assert scen["dt_s"] == pytest.approx(SOLVER_DT)
    assert scen["fastmode"] is False
    assert wtgame.scenario_from_inputs(_inputs(), tier="fast")["fastmode"] is True


# --------------------------------------------------------------------- 输入映射

def test_input_mapping_matches_repo_authority():
    """PL-12 的 `ΔV_blk` / `BC_blk` 必须与仓库权威值一致（这是乘数的分母）。"""
    inp = _inputs()
    assert inp.dv_blk == pytest.approx(932.57, abs=0.05)
    assert inp.bc_blk == pytest.approx(3078.1, abs=0.05)
    # 标称 (ΔV, BC) ⇒ 两个乘数都是 1，引擎不该多算一遍
    assert inp.thrust_scale == pytest.approx(1.0)
    assert inp.cx_scale == pytest.approx(1.0)
    assert not inp.check()


def test_multipliers_reach_load_profile_without_poisoning_later_loads():
    """乘数**确实**改写了求解器加载的 profile，而且不污染下一次加载。

    `_patch_profile` 是**就地改写**，靠 `wt.load_profile` 每次重新读盘+解析兜底。
    这条同时钉住两件事：改写的 key 名对（`force`/`force1`/`CxK`），以及兜底真的成立
    —— 一旦求解器将来加了 profile 缓存，第二次不同乘数的工况会静默复用第一次的推力。
    """
    wt = wtgame.load_solver()
    base, _ident = wt.load_profile("cn_pl12", wt.VERSION)
    base_force, base_cxk = base["force"], base["CxK"]
    seen = {}

    def fake_python_simulate(scen):
        # 此刻 `wt.load_profile` 已被 `simulate_tier` 换成打补丁的版本
        params, ident = wt.load_profile("cn_pl12", wt.VERSION)
        seen["params"], seen["ident"] = params, ident
        return scen, {"steps": 0, "time_s": 0.0}, []

    # 造一个乘数明显不为 1 的工况：ΔV 高 25%、BC 低 20%（⇒ cx_scale = 1/0.8）
    inp = _inputs(dv=932.57 * 1.25, bc=3078.05 * 0.8)
    assert inp.thrust_scale != pytest.approx(1.0)
    assert inp.cx_scale != pytest.approx(1.0)

    saved = wt.python_simulate
    wt.python_simulate = fake_python_simulate
    try:
        wtgame.simulate_tier(inp, tier="standard")
    finally:
        wt.python_simulate = saved

    assert seen["params"]["force"] == pytest.approx(base_force * inp.thrust_scale, rel=1e-12)
    assert seen["params"]["CxK"] == pytest.approx(base_cxk * inp.cx_scale, rel=1e-12)
    if inp.mass.two_stage and "force1" in base:
        assert seen["params"]["force1"] == pytest.approx(
            base["force1"] * inp.thrust_scale, rel=1e-12)
    # 身份块不能被连带改掉（它进产物，是"用了哪份资源"的证据）
    assert seen["ident"]["missile"] == "cn_pl12"
    assert len(str(seen["ident"]["resource_sha256"])) == 64

    after, _i2 = wt.load_profile("cn_pl12", wt.VERSION)
    assert after["force"] == pytest.approx(base_force, rel=1e-12)
    assert after["CxK"] == pytest.approx(base_cxk, rel=1e-12)


# --------------------------------------------------------------------- 金标

def test_gold_case_apex_matches_native_reference():
    """金标对拍：顶点高度对上原生基准 `10630.40 m` 的 **0.004%** 以内。"""
    res = _gold("standard")
    assert res.ok, res.error
    assert res.max_alt_m == pytest.approx(GOLD_MAX_ALT_M, abs=GOLD_TOL_M)
    # 该工况在 60 s 内打不到（闭合速度 550 m/s、距离 60 km），是**未命中**顶点用例
    assert res.hit is False and res.event == "time_limit"
    assert res.resource == f"wt-missile/{VERSION_28}"


def test_two_tiers_agree_on_the_gold_case():
    """两档只差算术路径，不该差物理：顶点高度逐位一致，终速只差最后一次舍入。"""
    a, b = _gold("standard"), _gold("fast")
    assert a.ok and b.ok
    assert abs(a.max_alt_m - b.max_alt_m) <= 0.05
    assert a.t_end == b.t_end
    assert abs(a.v_impact - b.v_impact) <= 1e-3
    # 档位必须体现在 resource 上（同一个工厂产物要能分辨是谁算的）
    assert a.resource != b.resource


# --------------------------------------------------------------------- 能力与拒绝

def test_capabilities_match_the_solver():
    caps = reg.spec_of("standard").capabilities
    assert caps.dims == "3d"
    scen = wtgame.scenario_from_inputs(_inputs(), tier="standard")
    assert len(scen["launch"]["position_m"]) == 3
    assert len(scen["target"]["velocity_m_s"]) == 3
    # 声明的两种观测模式求解器都真的认（0.5 s 探针，不跑全程）
    for mode in caps.observation_modes:
        _s, rows = wtgame.simulate_tier(
            replace(_inputs(), duration_s=0.5, observation_mode=mode), tier="standard")
        assert len(rows) > 1, mode
    # 求解器是标量循环：并行靠多进程，不靠向量化
    assert caps.vectorized_batch is False


def test_rejected_missiles_are_refused_not_approximated():
    """外环控制器 / 重复 `endSpeed` 的型号必须**明确拒绝**，不许近似替代。

    这条是"求解器自报诚实度"的检验：`unsupported()` 返回非空就必须拒绝，返回空才允许算。
    数量钉住 156/12，改动时会被看见。
    """
    wt = wtgame.load_solver()
    ok, rejected = [], []
    for name in sorted(wt.PROFILES):
        params, _ident = wt.load_profile(name, VERSION_28)
        reason = wt.unsupported(params)
        (rejected if reason else ok).append((name, reason))
    assert len(ok) + len(rejected) == N_PROFILES
    assert len(rejected) == N_REJECTED, [n for n, _r in rejected]
    for name, reason in rejected:
        assert reason, name
        assert ("refusing an approximate replacement" in reason
                or "endSpeed" in reason), (name, reason)
    # 项目在用的那一池必须**全都**可算（名单从弹池现取，别写死）
    from missile_sim import standard as std_mod

    computable = {n for n, _r in ok}
    for short, m in std_mod.load_pool()["missiles"].items():
        native = mio.native_name_of(str(m.get("file") or ""))
        assert native in computable, f"{short} → {native} 不可算"


def test_stamp_backend_comes_from_evidence_not_the_tier_name():
    """`resources.backend` 必须来自证据 —— 没跑过就不许按档位名猜。

    * `standard` 档必然是 `python-standard`：`scenario_from_inputs` 里 `fastmode` 恒为
      `False`，这是**构造事实**，所以不跑也能报；
    * `fast` 档可能是 `compiled-c` 也可能是回退的 `python-legacy`，**没跑过就只能说
      `unreported`**（曾经猜成 `compiled-c`；机器没有 C 编译器时那就是产物在撒谎）。
    """
    assert reg.load_engine("standard").stamp().resources["backend"] == "python-standard"
    assert reg.load_engine("fast").stamp().resources["backend"] == "unreported"

    std = reg.load_engine("standard").simulate(replace(_inputs(), duration_s=0.5), None)
    assert std.engine["resources"]["backend"] == "python-standard"
    assert std.engine["resources"]["elf_executed"] is False
    assert std.engine["fidelity"]["not_recovered"], "明确拒绝项必须写出来，不能留空"

    fast = reg.load_engine("fast").simulate(replace(_inputs(), duration_s=0.5), None)
    got = fast.engine["resources"]["backend"]
    assert got in ("compiled-c", "python-legacy"), got
    assert fast.engine["resources"]["tier"] == "fast"
    # 档位与算术后端必须都体现在 `resource` 上：产物要能分辨是谁算的
    suffix = got if got == "compiled-c" else "python-legacy"
    assert fast.resource == f"wt-missile/{VERSION_28}+{suffix}", fast.resource


# --------------------------------------------------------------------- 失败路径

def test_inconsistent_inputs_are_rejected_before_running():
    """输入不自洽必须在**跑之前**抛错，而不是把坏输入喂给求解器换一个 NaN 结果。"""
    inp = _inputs()
    bad = replace(inp, mass=replace(inp.mass, dry=0.0))
    with pytest.raises(ValueError):
        reg.load_engine("standard").simulate(bad, None)


def test_solver_errors_are_reported_not_raised():
    """求解器内部抛异常时返回 `ok=False`，不把异常漏给批量调用方（进程池会整批挂）。"""
    res = reg.load_engine("standard").simulate(
        replace(_inputs(), missile="no_such_missile"), None)
    assert res.ok is False
    assert res.error and "no_such_missile" in res.error

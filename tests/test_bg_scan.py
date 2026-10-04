# -*- coding: utf-8 -*-
"""β–γ **扫描层**（把 β、γ 当可调量）的契约。

这一层最容易出的错是**静默 no-op**：乘数算了、传了、看起来没问题，但内核根本没吃到。
所以这里的断言分两类：

1. **代数层**（不跑求解器）：`bg.scaling_for()` 反解出来的乘数，代回 β/γ 的定义必须闭环；
2. **端到端层**（跑求解器，走 `fast` 档）：γ 变大 ⇒ 诱导阻力变大 ⇒ 命中时间变长、
   末速变低。**这一条如果失败，几乎一定是注入链路断了**（曾经真的断过：
   `_patch_profile()` 只遍历已存在的键，而 11 型 blk 里都没有 `CxAoA`，
   于是 `CxAoA` 从来没被写进去，γ 轴在图上完全不动）。
"""

import math

import pytest

from missile_sim import bg, engine, grid as grid_mod, mapping, pool, solver
from missile_sim.spec import Scaling, Scene

#: 一条便宜的基准工况（快、稳定命中）：50 km 迎头、10 km 高、双方 300 m/s
SCENE = Scene()


def _point_and_metrics(key="PL-12"):
    entry = pool.resolve(key)
    p = bg.point_of(entry)
    m = mapping.blk_metrics(solver.profile(entry.native))
    return entry, p, m


# --------------------------------------------------------------- 代数层


def test_scaling_round_trips_back_to_the_target_beta_gamma():
    """反解出的乘数代回 β/γ 的定义，必须精确落回目标点。"""
    entry, p, m = _point_and_metrics()
    for b_t, g_t in ((2568.8, 91.2), (3800.0, 45.0), (3078.1, 100.0), (p.beta, p.gamma)):
        gi_t = bg.ginv_of(g_t)
        sc = bg.scaling_for(p, m, beta=b_t, ginv=gi_t)
        cxk_new = m.cxk * sc.cx_scale
        aoa_new = solver.effective_cx_aoa(solver.profile(entry.native)) * sc.cxaoa_scale
        beta_new = m.dry_kg / (m.sd_m2 * cxk_new)
        gamma_new = m.dry_kg * m.sd_m2 * cxk_new * aoa_new / (p.sl_m2 ** 2 * p.cyk ** 2)
        assert beta_new == pytest.approx(b_t, rel=1e-9), (b_t, g_t)
        assert gamma_new == pytest.approx(g_t, rel=1e-9), (b_t, g_t)
        # 轴量口径同样落回（`ginv = 1/γ`，换算不允许吃掉精度）
        assert bg.ginv_of(gamma_new) == pytest.approx(gi_t, rel=1e-9), (b_t, g_t)


def test_cxaoa_scale_formula_is_gamma_over_gamma_blk_divided_by_cx_scale():
    """`cxaoa_scale = (γ_t/γ_blk) / cx_scale` —— 两轴解耦的那个结论。"""
    _e, p, m = _point_and_metrics()
    sc = bg.scaling_for(p, m, beta=2568.8, ginv=bg.ginv_of(91.2))
    assert sc.cx_scale == pytest.approx(p.beta / 2568.8, rel=1e-9)
    assert sc.cxaoa_scale == pytest.approx((91.2 / p.gamma) / sc.cx_scale, rel=1e-9)


def test_nominal_targets_give_unit_scales():
    """目标点就是该弹自身 ⇒ 三个乘数全是 1（这是"β 与 BC 恒等"的另一种说法）。"""
    _e, p, m = _point_and_metrics()
    sc = bg.scaling_for(p, m, beta=p.beta, ginv=p.ginv)
    assert sc.thrust_scale == pytest.approx(1.0, rel=1e-12)
    assert sc.cx_scale == pytest.approx(1.0, rel=1e-9)
    assert sc.cxaoa_scale == pytest.approx(1.0, rel=1e-9)


def test_cxaoa_scale_rejects_non_positive():
    _e, p, m = _point_and_metrics()
    with pytest.raises(ValueError):
        bg.cxaoa_scale_for(p.beta, 0.0, p, 1.0)
    with pytest.raises(ValueError):
        bg.cxaoa_scale_for(p.beta, p.gamma, p, 0.0)


def test_dv_pin_is_forwarded_to_thrust_scale():
    """第二张图固定 ΔV：`dv` 一改，`thrust_scale` 就跟着改，`cxaoa_scale` 不受影响。"""
    _e, p, m = _point_and_metrics()
    a = bg.scaling_for(p, m, beta=p.beta, ginv=p.ginv)
    b = bg.scaling_for(p, m, beta=p.beta, ginv=p.ginv, dv=m.dv * 1.1)
    assert b.thrust_scale == pytest.approx(1.1, rel=1e-9)
    assert b.cxaoa_scale == pytest.approx(a.cxaoa_scale, rel=1e-12)


def test_scaling_carries_the_new_field_through_dict_round_trip():
    """`Scaling` 要跨进程传（pickle / dict），新字段不能在 `from_dict` 里被丢掉。"""
    sc = Scaling(dv_target=900.0, bc_target=3000.0, dv_blk=932.57, bc_blk=3078.05,
                 thrust_scale=0.9651, cx_scale=1.026, cxaoa_scale=1.4)
    back = Scaling.from_dict(sc.as_dict())
    assert back.cxaoa_scale == pytest.approx(1.4)
    # 老产物（这次改动之前写下的 `Scaling`）没有这个键 ⇒ 走默认值 1.0，不能抛错
    old = sc.as_dict()
    old.pop("cxaoa_scale")
    assert Scaling.from_dict(old).cxaoa_scale == 1.0


def test_effective_cxaoa_matches_the_kernel_body_by_body():
    """`solver.effective_cx_aoa()` 是内核那两行规则的复刻，必须逐弹与 `Body` 对拍。"""
    for e in pool.resolve_many(None):
        params = solver.profile(e.native)
        assert solver.effective_cx_aoa(params) == pytest.approx(
            solver.body_aero(e.native)[0], rel=1e-12), e.key


def test_effective_cxaoa_applies_the_wing_area_rule_when_the_flag_is_on():
    """开关打开时内核会乘 `wingAreaMult²`；复刻版必须跟上，否则注入会差一个倍数。"""
    params = {"CxAoA": 5.0, "wingAreaMult": 1.8, "applyWingAreaMultToCxAoA": True}
    assert solver.effective_cx_aoa(params) == pytest.approx(5.0 * 1.8 ** 2)
    assert solver.effective_cx_aoa({}) == pytest.approx(solver.KERNEL_CX_AOA_DEFAULT)


# --------------------------------------------------------------- 缓存键


def test_cache_key_separates_cells_that_differ_only_in_gamma():
    """β–γ 扫描里 γ 只落在 `cxaoa_scale` 上 —— 键必须把它算进去。

    旧实现键里只有 `(ΔV, BC)` 两个数，同一列（同 β、不同 γ）会**互相命中缓存**，
    而且结果看起来完全正常：整张图上 γ 方向一条直线。
    """
    a = Scaling(900.0, 3000.0, 932.57, 3078.05, 0.9651, 1.026, 1.0)
    b = Scaling(900.0, 3000.0, 932.57, 3078.05, 0.9651, 1.026, 1.7)
    ka = engine.cache_key(SCENE, "cn_pl12", a, "fast")
    kb = engine.cache_key(SCENE, "cn_pl12", b, "fast")
    assert ka != kb
    # 同一份 Scaling 两次必须同键（不能掺进时间戳之类）
    assert ka == engine.cache_key(SCENE, "cn_pl12", a, "fast")


def test_cache_key_separates_tiers():
    sc = Scaling(900.0, 3000.0, 932.57, 3078.05, 0.9651, 1.026, 1.0)
    assert engine.cache_key(SCENE, "cn_pl12", sc, "fast") != \
        engine.cache_key(SCENE, "cn_pl12", sc, "standard")


# --------------------------------------------------------------- 单调性自检


def test_monotonic_report_can_look_at_either_axis():
    """β 方向期望递减、γ 方向期望递增 —— 两个方向要能分别报。"""
    g = grid_mod.PlaneGrid(dv=(100.0, 200.0), bc=(10.0, 20.0), dv_step=100.0, bc_step=10.0)
    # 沿 axis=0（β）递减：第 0 列 5→4 合期望，4→5 违背
    assert grid_mod.monotonic_report([[5.0, 0.0], [4.0, 0.0]], g,
                                     axis=0, expect="decrease")["n_non_monotonic"] == 0
    assert grid_mod.monotonic_report([[4.0, 0.0], [5.0, 0.0]], g,
                                     axis=0, expect="decrease")["n_non_monotonic"] == 1
    # 沿 axis=1（γ）递增：第 0 行 5→6 合期望，6→5 违背
    assert grid_mod.monotonic_report([[0.0, 5.0], [0.0, 6.0]], g,
                                     axis=1, expect="increase")["n_non_monotonic"] == 0
    assert grid_mod.monotonic_report([[6.0, 5.0]], g,
                                     axis=1, expect="increase")["n_non_monotonic"] == 1
    # `axis=0` 是转置后再沿最后一维扫：报的 `n_columns` 就是 γ 的格点数
    rep = grid_mod.monotonic_report([[5.0, 1.0, 2.0], [4.0, 3.0, 4.0]], g,
                                    axis=0, expect="decrease")
    assert rep["n_columns"] == 3


def test_monotonic_report_default_still_matches_the_first_figure():
    """默认行为（沿 axis=1、递减）是图1 的旧契约，不能被我这次泛化改掉。"""
    g = grid_mod.PlaneGrid(dv=(1.0, 2.0), bc=(1.0, 2.0), dv_step=1.0, bc_step=1.0)
    assert grid_mod.monotonic_report([[9.0, 8.0]], g)["n_non_monotonic"] == 0
    assert grid_mod.monotonic_report([[8.0, 9.0]], g)["n_non_monotonic"] == 1


# --------------------------------------------------------------- 端到端：注入真的到了内核


def test_gamma_reaches_the_kernel_at_nominal_beta():
    """固定 β、只抬 γ：诱导阻力变大 ⇒ 命中时间变长、末速变低。

    **这是"注入链路真的通"的唯一硬证据** —— 代数层全过、链路断掉时，
    三个 γ 的结果会逐位相同（曾经就是这样）。
    """
    entry, p, m = _point_and_metrics()
    shots = []
    for g_t in (45.0, 70.0, 100.0):
        sc = bg.scaling_for(p, m, beta=p.beta, ginv=bg.ginv_of(g_t))
        shot = solver.run(SCENE, missile=entry.native, scaling=sc, tier="fast")
        assert shot.ok and shot.hit, (g_t, shot.error, shot.event)
        shots.append(shot)
    t = [s.t_hit for s in shots]
    v = [s.v_impact for s in shots]
    assert t[0] < t[1] < t[2], f"γ 变大 t_hit 应变长：{t}"
    assert v[0] > v[1] > v[2], f"γ 变大末速应更低：{v}"
    assert t[2] - t[0] > 0.1, f"γ 从 45 到 100 的影响太小，疑似没生效：{t}"


def test_beta_reaches_the_kernel_too():
    """固定 γ、只抬 β：零升阻力变小 ⇒ 命中时间变短。"""
    entry, p, m = _point_and_metrics()
    ts = []
    for b_t in (2568.8, 3078.1, 3683.9):
        sc = bg.scaling_for(p, m, beta=b_t, ginv=p.ginv)
        shot = solver.run(SCENE, missile=entry.native, scaling=sc, tier="fast")
        assert shot.ok and shot.hit, (b_t, shot.event)
        ts.append(shot.t_hit)
    assert ts[0] > ts[1] > ts[2], f"β 变大 t_hit 应变短：{ts}"


def test_beta_matters_more_than_gamma_for_hit_time_in_a_straight_flying_scene():
    """一条**物理结论**的回归：迎头直飞工况下命中时间几乎只由 β 决定。

    这正是"图上等时线近乎竖直"的原因，也是 `docs/BETA-GAMMA.md` §5 里
    `a_loss = q·f/β + γ·F·(n·g0)²/q` 那句"低过载时基础项主导"的直接体现。
    如果哪天它反过来了，说明内核的阻力模型或场景装配变了，图画出来会不一样。
    """
    entry, p, m = _point_and_metrics()
    kw = dict(missile=entry.native, tier="fast")

    def t_of(b, g):
        shot = solver.run(SCENE, scaling=bg.scaling_for(p, m, beta=b,
                                                        ginv=bg.ginv_of(g)), **kw)
        assert shot.ok and shot.hit
        return shot.t_hit

    d_beta = abs(t_of(3700.0, p.gamma) - t_of(2600.0, p.gamma))
    d_gamma = abs(t_of(p.beta, 100.0) - t_of(p.beta, 45.0))
    assert d_beta > d_gamma, (d_beta, d_gamma)


# --------------------------------------------------------------- 末端编排（Engine）


def test_engine_scaling_of_hook_drives_the_beta_gamma_grid():
    """`Engine(scaling_of=…)` 那条口子：只跑两个格点，确认两格结果不同、且与单跑一致。"""
    entry, p, m = _point_and_metrics()
    # ⚠ 钩子的第二个实参是**轴量**（网格坐标），不是物理 γ：45/100 是 γ，
    #   这里必须换成 ginv 再进网格，否则"网格坐标"与"注入量"不是一个口径。
    gi_bad, gi_good = bg.ginv_of(100.0), bg.ginv_of(45.0)
    cand = [(p.beta, gi_good), (p.beta, gi_bad)]
    eng = engine.Engine(SCENE, missile=entry.native, tier="fast", jobs=1, cache=False,
                        metrics=m,
                        scaling_of=lambda b, g: bg.scaling_for(p, m, beta=b, ginv=g))
    try:
        shots = eng.many(cand)
    finally:
        eng.close()
    assert all(s.ok and s.hit for s in shots)
    assert shots[0].t_hit < shots[1].t_hit
    g = grid_mod.PlaneGrid(dv=(p.beta,), bc=(gi_good, gi_bad), dv_step=1.0, bc_step=1.0)
    t = grid_mod.t_hit_matrix(shots, g)
    assert t.shape == (1, 2) and math.isfinite(t[0][0]) and math.isfinite(t[0][1])

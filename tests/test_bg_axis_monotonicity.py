# -*- coding: utf-8 -*-
"""**换轴口径的中心差分判据 + 反向钻取**（用户 2026-10-04 的原始诉求）。

用户原话：「将γ和β一样取倒数(β物理意义上是零升阻力减速度的倒数)，以此使二者单调性一致」。

⚠ 符号约定（**必须写清楚，否则判据会被读反**）：图上两轴都是「向上＝更好」，
而"更好"在这个工况里表现为**命中更早**（能量损失小 ⇒ 追上目标更快），所以
**t_hit 沿两条轴都在下降**：

    ∂t_hit/∂β < 0   且   ∂t_hit/∂ginv < 0        ← 同号（这是用户要的"单调性一致"）
    ∂t_hit/∂γ > 0                                 ← 旧纵轴：反号（这才是要被消掉的那件事）

`ginv = 1/γ` ⇒ `∂t_hit/∂γ = ∂t_hit/∂ginv · dginv/dγ = −(1/γ²)·∂t_hit/∂ginv`，
所以**同一个物理趋势**在 γ 轴上的导数必然与 ginv 轴反号 —— 这不是新物理，是链式法则。

工况：`Scene()` 默认（50 km 迎头、10 km 高、双方 300 m/s）、基准弹 PL-12、`fast` 档；
中心点 β = 3000、γ = 65（ginv = 0.0153846…），β 半跨 100、γ 半跨 5。
判据用**中心差分**，并给出实测斜率（见下面两个用例的 docstring）；反向钻取把同一个检查喂 γ 轴，
**必须转红**。实测（2026-10-04）：

    ∂t_hit/∂β    = −3.8280e-03  s / 单位β
    ∂t_hit/∂ginv = −2.8808e+01  s / (m²/kg)      ← 与 β 同号 ✅
    ∂t_hit/∂γ    = +6.8590e-03  s / 单位γ        ← 旧轴，与 β 反号 ❌（这就是被消掉的那件事）
"""

from __future__ import annotations

import math

import pytest

from missile_sim import bg, mapping, pool, solver
from missile_sim.spec import Scene

#: 一条便宜的基准工况（快、稳定命中）：50 km 迎头、10 km 高、双方 300 m/s
SCENE = Scene()

BETA_C, BETA_H = 3000.0, 100.0
GAMMA_C, GAMMA_H = 65.0, 5.0
#: 非空判据的下限（斜率不能是"零噪声"）：实测 |∂t_hit/∂β| = 3.83e-3 s/单位β、
#: |∂t_hit/∂ginv| = 28.8 s/(m²/kg)，这里取实测值的 ~1/10 当门槛。
MIN_SLOPE_BETA = 1e-4
MIN_SLOPE_GINV = 1e1


def _t_hit_grid():
    """3×3 格点上的 t_hit（β × γ，γ 只是输入变量名；轴量一律由 `bg.ginv_of` 换算）。"""
    from missile_sim import engine                                  # noqa: F401  仅作可用性检查

    entry = pool.resolve("PL-12")
    p = bg.point_of(entry)
    m = mapping.blk_metrics(solver.profile(entry.native))
    kw = dict(missile=entry.native, tier="fast")
    out = {}
    for b in (BETA_C - BETA_H, BETA_C, BETA_C + BETA_H):
        for g in (GAMMA_C - GAMMA_H, GAMMA_C, GAMMA_C + GAMMA_H):
            shot = solver.run(SCENE, scaling=bg.scaling_for(p, m, beta=b,
                                                            ginv=bg.ginv_of(g)), **kw)
            assert shot.ok and shot.hit, (b, g, getattr(shot, "error", ""), shot.event)
            out[(round(b, 6), round(g, 6))] = float(shot.t_hit)
    return out


def _central(f, x_lo, x_hi) -> float:
    return (f(x_hi) - f(x_lo)) / (x_hi - x_lo)


def _same_sign_report(slope_beta: float, slope_axis: float, *, name: str) -> dict:
    """同一个检查，喂不同的纵轴量：两轴导数同号才算过（返回 dict，便于打印日志）。"""
    same = math.copysign(1.0, slope_beta) == math.copysign(1.0, slope_axis)
    return {"axis_name": name, "slope_beta": slope_beta, "slope_axis": slope_axis,
            "same_sign": bool(same), "ok": bool(same and slope_beta != 0.0)}


def test_central_differences_are_negative_on_both_axes():
    """**用户诉求的判据**：两条轴的 t_hit 中心差分同号（本工况下都为负），且非零。"""
    t = _t_hit_grid()
    b_lo, b_hi = BETA_C - BETA_H, BETA_C + BETA_H
    g_lo, g_hi = GAMMA_C - GAMMA_H, GAMMA_C + GAMMA_H
    # ⚠ 名字按**端点**给，不按大小：`ginv_of(60) > ginv_of(70)`（取倒数会翻次序）
    gi_at_g_lo, gi_at_g_hi = bg.ginv_of(g_lo), bg.ginv_of(g_hi)
    d_beta = _central(lambda b: t[(round(b, 6), round(GAMMA_C, 6))], b_lo, b_hi)
    d_ginv = _central(lambda gi: t[(round(BETA_C, 6), round(bg.gamma_of(gi), 6))],
                      gi_at_g_hi, gi_at_g_lo)
    d_gamma = _central(lambda g: t[(round(BETA_C, 6), round(g, 6))], g_lo, g_hi)

    log = {"d_t_hit_d_beta": d_beta, "d_t_hit_d_ginv": d_ginv, "d_t_hit_d_gamma": d_gamma,
           "chain_rule_at_midpoint": -1.0 / (GAMMA_C ** 2) * d_ginv,
           "chain_rule_with_secant": d_ginv * ((gi_at_g_hi - gi_at_g_lo) / (g_hi - g_lo))}
    print("[drill] 中心差分：", log)

    assert d_beta < -MIN_SLOPE_BETA, log
    assert d_ginv < -MIN_SLOPE_GINV, log
    rep = _same_sign_report(d_beta, d_ginv, name="ginv")
    assert rep["ok"], rep                                    # ← 用户要的"单调性一致"
    # ① 严格那条：用**割线**因子换算（同一批数的代数恒等式），必须到浮点精度
    assert log["chain_rule_with_secant"] == pytest.approx(d_gamma, rel=1e-9), log
    # ② 物理那条：用 γ 中心点的导数 −1/γ² 换算。⚠ 两者差 **0.59%** 是**数学**，不是误差：
    #    割线/切线比 = (Δginv/Δγ)/(−1/γ_c²) = 1.00594（Δγ/γ = 7.7% 的二阶项），所以容差给 2%。
    assert log["chain_rule_at_midpoint"] == pytest.approx(d_gamma, rel=0.02), log


def test_reverse_drill_gamma_axis_turns_the_same_check_red():
    """**反向钻取**：把纵轴量换回 γ，同一个"同号"检查**必须转红**。

    转红才是证据：它证明上面那条判据真的在测**轴口径**，而不是一条"什么轴都能过"的空断言。
    日志（实测，PL-12 / `fast` / β=3000±100 / γ=65±5）：
        ginv 轴：slope_beta = −3.828e-03，slope_axis = −2.881e+01 ⇒ same_sign=True  ⇒ ok
        γ   轴：slope_beta = −3.828e-03，slope_axis = +6.859e-03 ⇒ same_sign=False ⇒ 红
    """
    t = _t_hit_grid()
    b_lo, b_hi = BETA_C - BETA_H, BETA_C + BETA_H
    g_lo, g_hi = GAMMA_C - GAMMA_H, GAMMA_C + GAMMA_H
    gi_at_g_lo, gi_at_g_hi = bg.ginv_of(g_lo), bg.ginv_of(g_hi)

    d_beta = _central(lambda b: t[(round(b, 6), round(GAMMA_C, 6))], b_lo, b_hi)
    d_ginv = _central(lambda gi: t[(round(BETA_C, 6), round(bg.gamma_of(gi), 6))],
                      gi_at_g_hi, gi_at_g_lo)
    d_gamma = _central(lambda g: t[(round(BETA_C, 6), round(g, 6))], g_lo, g_hi)

    on_ginv = _same_sign_report(d_beta, d_ginv, name="ginv")
    on_gamma = _same_sign_report(d_beta, d_gamma, name="gamma")
    print("[drill] 新轴（ginv）：", on_ginv)
    print("[drill] 旧轴（gamma）：", on_gamma)
    assert on_ginv["ok"] is True, on_ginv
    assert on_gamma["ok"] is False, f"反向钻取没能转红（判据是空的）：{on_gamma}"
    # 反向钻取还要指出**为什么会红**：γ 轴的导数与 β 反号（γ 越大损失越大、命中越晚）
    assert d_gamma > 0 > d_beta, (d_gamma, d_beta)

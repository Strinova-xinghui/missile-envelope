# -*- coding: utf-8 -*-
"""求解器 API 回归：身份与哈希、场景映射、金标工况、两档一致、乘数生效、
内核边界（`maneuvers` 时刻严格递增是硬拒）、crank 想定的锚点与命中时刻。

**金标工况**（`docs/NEW-SOLVER-HANDOFF.md` §4 记录、本仓库复现过）：
PL-12 / 水平 50 km / 10 km 同高 / 载机 300 m/s 航向 0° / 敌机 300 m/s 航向 180° / ideal
→ `t_hit = 45.1861 s`、`max_alt = 12725.10 m`。

两档一致那一条会真跑一遍 `standard`（纯 Python，约 1~2 s），是这套测试里最慢的一项。
"""

from __future__ import annotations

import math

import pytest

from missile_sim import pool, solver
from missile_sim.spec import SOLVER_DT, Scene

GOLD_T_HIT = 45.1861
GOLD_MAX_ALT = 12725.10


@pytest.fixture(scope="module")
def gold():
    return solver.run(Scene(), missile="cn_pl12", tier="fast")


# --------------------------------------------------------------- 身份


def test_solver_file_hash_matches_constant():
    """内核文件的 sha256 必须与 `solver.SOLVER_SHA256` 一致 —— 换内核要同时改两处。"""
    import hashlib
    from pathlib import Path

    f = Path(solver.__file__).resolve().parent.parent.parent / "vendor" / "wt-missile" / solver.SOLVER_FILE
    assert f.is_file(), f"内核文件不见了：{f}"
    got = hashlib.sha256(f.read_bytes()).hexdigest()
    assert got == solver.SOLVER_SHA256, (
        f"内核哈希不符：\n  文件 {got}\n  常量 {solver.SOLVER_SHA256}\n"
        "改内核时必须同时更新 solver.SOLVER_SHA256 与 vendor/wt-missile/VENDOR.md")


def test_identity_fields():
    ident = solver.identity()
    assert ident.get("model")
    assert str(ident.get("sha256", "")).startswith(solver.SOLVER_SHA256[:16])
    assert int(ident.get("n_profiles") or 0) >= 150


def test_all_pool_missiles_are_supported():
    """池里 11 型必须都能算 —— 池里放一个算不了的型号，出图时才炸就太晚了。

    注意 `solver.supported()` 返回的是**拒绝原因**（可算时是 `None`），不是布尔值。
    """
    bad = {e.key: solver.supported(e.native) for e in pool.POOL
           if solver.supported(e.native) is not None}
    assert not bad, f"这些池内型号求解器不支持：{bad}"


# --------------------------------------------------------------- 场景映射


def test_scenario_dict_shape_and_coordinates():
    """`range_m` 是水平距离；目标位置在 x-z 平面内按方位角展开。"""
    raw = solver.scenario_dict(
        Scene(range_m=40_000.0, alt_m=5_000.0, target_alt_m=15_000.0,
              target_bearing_deg=90.0),
        missile="cn_pl12", tier="fast")
    assert raw["schema_version"] == 1
    assert raw["missile"] == "cn_pl12"
    assert raw["step_policy"] == "fixed", "固定步长是 C 快路径的条件"
    assert raw["dt_s"] == pytest.approx(SOLVER_DT)
    lp, lv = raw["launch"]["position_m"], raw["launch"]["velocity_m_s"]
    tp, tv = raw["target"]["position_m"], raw["target"]["velocity_m_s"]
    assert len(lp) == len(lv) == len(tp) == len(tv) == 3, "必须是 3 分量"
    # 逐元素比 —— 测试运行器的 approx() 对 list 是精确比较，不能直接套在列表上
    assert lp == [0.0, 5000.0, 0.0]
    assert tp[0] == pytest.approx(0.0, abs=1e-6)          # 方位 90° ⇒ 全在 +z
    assert tp[1] == pytest.approx(15_000.0)
    assert tp[2] == pytest.approx(40_000.0)
    assert lv[0] == pytest.approx(300.0) and lv[1] == 0.0 and lv[2] == 0.0
    assert tv[0] == pytest.approx(-300.0)                 # 航向 180° ⇒ 迎头
    assert tv[1] == 0.0 and tv[2] == pytest.approx(0.0, abs=1e-9)


def test_scenario_dict_rejects_bad_scene():
    with pytest.raises(ValueError):
        solver.scenario_dict(Scene(dt_s=1.0), missile="cn_pl12", tier="fast")
    with pytest.raises(ValueError):
        solver.scenario_dict(Scene(observation="magic"), missile="cn_pl12", tier="fast")


# --------------------------------------------------------------- 金标


def test_gold_case_hits_known_values(gold):
    assert gold.ok, f"求解失败：{gold.error}"
    assert gold.hit
    assert gold.event == "proximity_fuse"
    assert gold.t_hit == pytest.approx(GOLD_T_HIT, abs=5e-4), \
        "金标 t_hit 变了 —— 要么内核换了，要么乘数被悄悄改了"
    assert gold.max_alt_m == pytest.approx(GOLD_MAX_ALT, abs=5e-2)


def test_shot_fields_are_populated(gold):
    assert gold.t_end > 0 and gold.t_hit > 0
    assert gold.m_launch > gold.m_dry > 0
    assert gold.v_impact > 0
    assert gold.resource and "wt-missile" in gold.resource
    assert gold.t_burnout > 0
    assert gold.dv_measured > 0


def test_backend_is_evidence_based(gold):
    """本机 C 内核已启用 ⇒ fast 档必须报 compiled-c；没有编译器时只能是 python-legacy。"""
    assert gold.backend in ("compiled-c", "python-legacy"), gold.backend
    std = solver.run(Scene(), missile="cn_pl12", tier="standard")
    assert std.backend == "python-standard", "standard 档的 backend 是构造事实，不该是别的"


def test_tiers_agree():
    """同物理、不同后端 ⇒ 结果必须一致（这是"两档只差算术后端"的证据）。"""
    fast = solver.run(Scene(), missile="cn_pl12", tier="fast")
    std = solver.run(Scene(), missile="cn_pl12", tier="standard")
    assert fast.t_hit == pytest.approx(std.t_hit, abs=1e-3)
    assert fast.max_alt_m == pytest.approx(std.max_alt_m, abs=1e-2)
    assert fast.event == std.event


# --------------------------------------------------------------- 未命中


def test_miss_yields_nan_not_zero():
    """时域截断必须报 nan —— 用 0 冒充会让读图的人以为"0 秒命中"。"""
    shot = solver.run(Scene(duration_s=1.0), missile="cn_pl12", tier="fast")
    assert shot.ok
    assert not shot.hit
    assert shot.event == "time_limit"
    assert math.isnan(shot.t_hit), "未命中必须是 nan"
    assert shot.t_end == pytest.approx(1.0, abs=0.05)


# --------------------------------------------------------------- 乘数


def test_scaling_changes_the_flight():
    """按目标 (ΔV, BC) 施加乘数后，弹道必须真的变了，且方向符合物理直觉。"""
    from missile_sim import mapping

    m = pool.metrics_of(pool.resolve("PL-12"))
    base = solver.run(Scene(), missile="cn_pl12", tier="fast")
    weaker = solver.run(Scene(), missile="cn_pl12", tier="fast",
                        scaling=mapping.scaling_for(700.0, m.bc, m))
    assert weaker.ok
    assert weaker.t_hit > base.t_hit, "总增速降下来，命中时间应该变长"


def test_scaling_none_is_identical_to_default():
    a = solver.run(Scene(), missile="cn_pl12", tier="fast")
    b = solver.run(Scene(), missile="cn_pl12", tier="fast", scaling=None)
    assert a.t_hit == pytest.approx(b.t_hit, abs=1e-9)
    assert a.max_alt_m == pytest.approx(b.max_alt_m, abs=1e-9)


# --------------------------------------------------------------- 3D 扩位


def test_3d_geometry_cases_run():
    """载机与敌机都能给航向/俯仰（用户拍板的 3D 扩位）。"""
    cases = {
        "同高迎头": Scene(),
        "目标侧方 45°": Scene(target_bearing_deg=45.0),
        "目标爬升 20°": Scene(target_pitch_deg=20.0),
        "载机爬升 15° + 敌机俯冲 10°": Scene(launch_pitch_deg=15.0, target_pitch_deg=-10.0),
        "高度差 3 km + 方位 30°": Scene(alt_m=10_000.0, target_alt_m=13_000.0,
                                        target_bearing_deg=30.0),
    }
    for label, sc in cases.items():
        assert not sc.check(), f"{label}: {sc.check()}"
        shot = solver.run(sc, missile="cn_pl12", tier="fast")
        assert shot.ok, f"{label} 求解失败：{shot.error}"
        assert shot.t_hit > 0, f"{label} 应该命中"


def test_slant_range_accounts_for_altitude():
    sc = Scene(range_m=40_000.0, alt_m=5_000.0, target_alt_m=15_000.0)
    assert sc.range_slant_m == pytest.approx(math.hypot(40_000.0, 10_000.0), rel=1e-12)
    flat = Scene(range_m=40_000.0, alt_m=5_000.0, target_alt_m=5_000.0)
    assert flat.range_slant_m == pytest.approx(40_000.0, rel=1e-12)


def test_scene_roundtrip():
    sc = Scene(range_m=40_000.0, alt_m=5_000.0, target_alt_m=15_000.0,
               target_bearing_deg=90.0, target_pitch_deg=12.5)
    assert Scene.from_dict(sc.as_dict()) == sc


# --------------------------------------------------------------- 内核边界（实测）


def test_kernel_rejects_non_increasing_maneuver_times():
    """`maneuvers` 的时刻必须**非负且严格递增** —— 内核是**硬拒**，不是"静默按错序执行"。

    证据 `vendor/wt-missile/wt_missile.py:247-248`（原文报错
    `Maneuver times must be nonnegative and strictly increasing`）。
    外壳另有一道预检（`targets.check_compatible`），这里证明的是**内核自己也拒** ——
    所以谁再把"乱序会被静默执行"写回文档，会先撞上这条测试。
    """
    a = (0.0, 0.0, 0.0)
    for label, times in (("乱序 5→3", (5.0, 3.0)), ("重复 3/3", (3.0, 3.0))):
        sc = Scene(maneuvers=tuple((t, a) for t in times))
        assert not sc.check(), f"{label}：`Scene.check()` 不该拦它（拦它的是内核）"
        shot = solver.run(sc, missile="cn_pl12", tier="fast")
        assert not shot.ok, f"{label} 竟然被接受了"
        assert "strictly increasing" in shot.error, f"{label}: {shot.error}"


def test_crank_beam_scenario_end_to_end():
    """crank → 39 想定的锚点与命中时刻（黄金值见 `docs/MANEUVER-TARGETS.md` §8.8.5 / §8.9）。

    锚点必须用**同一枚弹**反求，且用**一遍法**（在**不含 39 腿**的轨迹上找首次 `range ≤ lockDistance`）。
    ⚠ `Shot.rows` 是精简过的轨迹（键名 `t` / `range`，见 `solver.trajectory()`），
    不是内核原始的 `time_s` / `range_m`。
    """
    from missile_sim import flightpath

    def scene(mans):
        return Scene(range_m=50_000.0, alt_m=10_000.0, vm0=300.0, launch_heading_deg=0.0,
                     target_heading_deg=180.0, target_pitch_deg=0.0, target_speed_ms=300.0,
                     target_alt_m=None, target_bearing_deg=0.0, duration_s=150.0,
                     observation="ideal", maneuvers=mans)

    def run(sch):
        return solver.run(scene(sch.maneuvers(duration_s=150.0, dt=0.1)),
                          missile="cn_pl12", tier="fast", want_rows=True)

    t_crank, crank_deg, g = 8.0, 70.0, 9.0

    # 1) 只 crank（39 腿排在 10 km 处，落在 150 s 时域之外）→ 反求锚点
    only_crank = run(flightpath.crank_beam(t_crank, crank_deg, 10_000.0,
                                           react_delay_s=0.0, g_crank=g, g_beam=g))
    assert only_crank.ok and only_crank.hit, only_crank.error
    lock = 16_000.0                                    # PL-12 的 guidance.lockDistance
    t_beam = next(r["t"] for r in only_crank.rows
                  if r["range"] is not None and r["range"] <= lock)
    assert 34.4 <= t_beam <= 34.6, f"锚点变了：{t_beam}（§8.8.5 记的是 34.46 s）"

    # 2) 加上 39 腿、延迟 0 → 69.554 s
    hit0 = run(flightpath.crank_beam(t_crank, crank_deg, t_beam,
                                     react_delay_s=0.0, g_crank=g, g_beam=g))
    assert hit0.ok and hit0.hit, hit0.error
    assert hit0.t_hit == pytest.approx(69.554, abs=0.01)

    # 3) 延迟 1.0 s（"看到 RWR 告警才转"）→ 69.172 s，即 −0.382 s
    hit1 = run(flightpath.crank_beam(t_crank, crank_deg, t_beam,
                                     react_delay_s=1.0, g_crank=g, g_beam=g))
    assert hit1.ok and hit1.hit, hit1.error
    assert hit1.t_hit == pytest.approx(69.172, abs=0.01)


# ------------------------------------------- 内核**输出列**契约（2026-10-02 扩列）

# 用户 2026-10-02 拍板"扩内核输出列"：`mach` / `aoa_deg` / `aoa_eff_deg` 由**内核**给出，
# 外壳不再自己派生。口径与定义见 `vendor/wt-missile/VENDOR.md`「本地改动记录」与
# `docs/SOLVER-API.md` §3.1。
NEW_COLUMNS = ("mach", "aoa_deg", "aoa_eff_deg")
GOLD_N_COLUMNS = 68                      # 交付包原样 65 列 + 本轮 3 列
# 前 65 列（交付包原样部分）的**名字与顺序**指纹：任何"插在中间/改名"都会被这条抓住。
GOLD_PREFIX_SHA256 = "00ea06f48a6b06252daf854ba2413b7f114ef1008a0c10a26ccf98d184520047"


def kernel_rows(tier, scene=None, missile="cn_pl12"):
    """内核**原始**逐采样行（68 列）。

    这是唯一能看到"内核输出列"的路径：`Shot.rows` 是精简过的投影（见 `solver.trajectory()`）。
    输入仍走 `solver.scenario_dict()`（"唯一接触面"），不绕过外壳自己拼 scenario。
    """
    wt = solver.load_solver()
    raw = solver.scenario_dict(Scene() if scene is None else scene,
                              missile=missile, tier=tier)
    _, summary, rows = wt.python_simulate(raw)
    return summary, rows


@pytest.fixture(scope="module")
def rows_both_tiers():
    """两档各跑一次金标工况（standard 约 1~2 s；fast 走 compiled-c）。"""
    return {tier: kernel_rows(tier)[1] for tier in ("standard", "fast")}


def _rot_from_q(qx, qy, qz, qw):
    """四元数 `(x,y,z,w)` → 行主序 3×3。**独立实现**，不用内核的 `rotation()`。"""
    x, y, z, w = qx, qy, qz, qw
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _hat(a, fallback):
    n = math.sqrt(_dot(a, a))
    return tuple(c / n for c in a) if n > 1e-9 else fallback


def _angle_deg(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(a, b)))))


def recompute_new_columns(row, lever, wind):
    """只用**行里的原始列** + 内核大气，独立复算 `(mach, aoa_deg, aoa_eff_deg)`。

    刻意不复用内核的 `unit()` / `norm64()` / `rotation()` —— 否则就是拿同一段代码自证。
    """
    rot = _rot_from_q(row["qx"], row["qy"], row["qz"], row["qw"])
    nose = _hat((rot[0][0], rot[1][0], rot[2][0]), (1.0, 0.0, 0.0))
    air = (row["missile_vx_m_s"] - wind[0], row["missile_vy_m_s"] - wind[1],
           row["missile_vz_m_s"] - wind[2])
    air_hat = _hat(air, nose)
    lever_term = (0.0, lever * row["omega_z_rad_s"], -lever * row["omega_y_rad_s"])
    flow = _hat(tuple(air[i] + _dot(rot[i], lever_term) for i in range(3)), air_hat)
    sound = solver.load_solver()._atmosphere(row["missile_y_m"])[1]
    return math.sqrt(_dot(air, air)) / sound, _angle_deg(nose, air_hat), _angle_deg(nose, flow)


def _lever_and_wind(missile="cn_pl12"):
    wt = solver.load_solver()
    raw = solver.scenario_dict(Scene(), missile=missile, tier="standard")
    p, _ = wt.load_profile(raw["missile"], raw.get("version", wt.VERSION))
    return float(wt.Body(p).lever), list(raw.get("wind_m_s", [0.0, 0.0, 0.0]))


def test_output_columns_contract():
    """列数 = 68；新增三列**追加在末尾**；既有 65 列的**名字与顺序一个都没动**。"""
    import hashlib
    wt = solver.load_solver()
    cols = list(wt._CF_COLUMNS)
    assert len(cols) == GOLD_N_COLUMNS, f"输出列数变了：{len(cols)}（新列必须追加在末尾）"
    assert tuple(cols[-3:]) == NEW_COLUMNS, cols[-3:]
    assert len(set(cols)) == len(cols), "列名重复了（按下标读列的消费者会串行）"
    prefix = hashlib.sha256(" ".join(cols[:GOLD_N_COLUMNS - 3]).encode()).hexdigest()
    assert prefix == GOLD_PREFIX_SHA256, (
        "既有 65 列的名字/顺序被改了 —— 这不是「扩列」而是改契约；"
        f"指纹 {prefix}")
    # 三列的物理单位/语义都在名字里：mach 无量纲，两个攻角是 deg。
    assert cols.index("air_speed_m_s") < cols.index("mach"), "新列必须排在既有列之后"


def test_new_columns_are_kernel_output(rows_both_tiers):
    """三列必须是**内核行**里就有的键；外壳的精简出口也把它们接出来了。"""
    for tier, rows in rows_both_tiers.items():
        missing = [k for k in NEW_COLUMNS if k not in rows[0]]
        assert not missing, f"{tier} 档的内核行缺列：{missing}"
    shot = solver.run(Scene(), missile="cn_pl12", tier="fast", want_rows=True)
    assert shot.ok, shot.error
    missing = [k for k in NEW_COLUMNS if k not in shot.rows[0]]
    assert not missing, f"外壳出口（solver.trajectory()）没把新列接出来：{missing}"


def test_mach_matches_airspeed_over_sound(rows_both_tiers):
    """`mach` 必须**恒等于** `air_speed_m_s / sound(alt)`（同一条式子的两个出口）。"""
    wt = solver.load_solver()
    for tier, rows in rows_both_tiers.items():
        worst = 0.0
        for r in rows:
            sound = wt._atmosphere(r["missile_y_m"])[1]
            ref = r["air_speed_m_s"] / sound
            worst = max(worst, abs(r["mach"] - ref) / max(ref, 1e-12))
        assert worst <= 1e-12, f"{tier} 档 mach 与 air_speed/sound 不一致：相对差 {worst:g}"


def test_new_columns_match_independent_recompute(rows_both_tiers):
    """四元数 + 速度**独立复算**三列。

    容差说明（实测）：`standard` 逐位相同（0.0）；`fast` 走编译 C，同一行数据的
    `acos` 在近 1 处的放大效应会把最后几位差放大到 ~1e-8 deg（实测 mach 8.9e-16、
    aoa_deg 6.0e-9、aoa_eff_deg 1.6e-9），所以给 1e-6 的绝对门限 —— 真错了（力臂项、
    符号、用空气速度还是地速）会差**几度**，这个门限拦得住。
    """
    lever, wind = _lever_and_wind()
    for tier, rows in rows_both_tiers.items():
        worst = {k: 0.0 for k in NEW_COLUMNS}
        for r in rows:
            ref = recompute_new_columns(r, lever, wind)
            for k, v in zip(NEW_COLUMNS, ref):
                worst[k] = max(worst[k], abs(r[k] - v))
        assert worst["mach"] <= 1e-6, (tier, worst)
        assert worst["aoa_deg"] <= 1e-6, (tier, worst)
        assert worst["aoa_eff_deg"] <= 1e-6, (tier, worst)
        for k in NEW_COLUMNS:
            assert all(0.0 - 1e-12 <= r[k] <= 180.0 + 1e-12 for r in rows), \
                f"{tier} 档 {k} 越界（攻角是 acos 的非负角 [0,180]）"


def test_tiers_agree_on_new_columns(rows_both_tiers):
    """两档一致（**同物理、不同算术后端**）。

    实测最大差：`mach` 4.6e-7（与既有 `air_speed_m_s` 的相对差 1.2e-7 同源），
    两个攻角 1.2e-4 deg。门限取实测的 ~8 倍：mach 1e-5、攻角 1e-3 deg。
    """
    std, fast = rows_both_tiers["standard"], rows_both_tiers["fast"]
    assert len(std) == len(fast)
    for a, b in zip(std, fast):
        assert a["time_s"] == pytest.approx(b["time_s"], abs=1e-12)
    worst = {k: max(abs(a[k] - b[k]) for a, b in zip(std, fast)) for k in NEW_COLUMNS}
    assert worst["mach"] <= 1e-5, worst
    assert worst["aoa_deg"] <= 1e-3, worst
    assert worst["aoa_eff_deg"] <= 1e-3, worst


def test_new_columns_golden_example(rows_both_tiers):
    """真实轨迹上的**数值锚点**：`standard` 档第一条 `t >= 10 s` 的行。

    PL-12 / 50 km 迎头 / 10 km 同高：t = 10.000000 s、alt = 12208.63 m、
    mach = 3.5489671066、aoa_deg = 1.4947874925、aoa_eff_deg = 1.4953665185
    （有效攻角比运动学攻角大 **0.0005790 deg** —— 力臂×角速度那一项的方向加上的角）。
    """
    rows = rows_both_tiers["standard"]
    r = next(r for r in rows if r["time_s"] >= 10.0)
    assert r["mach"] == pytest.approx(3.5489671066385546, abs=1e-9)
    assert r["aoa_deg"] == pytest.approx(1.494787492526033, abs=1e-9)
    assert r["aoa_eff_deg"] == pytest.approx(1.495366518463927, abs=1e-9)
    assert r["aoa_eff_deg"] > r["aoa_deg"], "这一点的有效攻角应当大于运动学攻角"
    assert r["aoa_eff_deg"] - r["aoa_deg"] == pytest.approx(5.79025937894162e-4, abs=1e-9)

    # 发射段（转弯速率最大的那一点）：两个攻角都到 ~16°，差 0.0077 deg。
    peak = max(rows, key=lambda r: r["aoa_eff_deg"])
    assert peak["time_s"] == pytest.approx(0.6458333525806665, abs=1e-6)
    assert peak["aoa_deg"] == pytest.approx(16.22365271384829, abs=1e-9)
    assert peak["aoa_eff_deg"] == pytest.approx(16.23131781773255, abs=1e-9)

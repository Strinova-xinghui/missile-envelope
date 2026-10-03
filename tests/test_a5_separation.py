# -*- coding: utf-8 -*-
"""**A5 判据**：命中时内核给的"最近距离"是**引信半径**，不是脱靶量。

背景（task-22 审计 A5）：内核 `summary["minimum_separation_until_event_m"]` 在命中工况下
恒等于引信半径（默认 10.0 m）—— 引信一进半径就触发，后面的弹道根本不走。外壳曾经把它
当"脱靶量"一路写进报告表/CSV/图4/页面，于是每条命中工况都显示"脱靶量 10.0 m"。

四条判据（都带牙，且第 3 条是**反向判据**）：

1. 命中 ⇒ `min_separation_m` **等于**引信半径，而**真 CPA**（`cpa_m`，关引信复跑量的）
   **严格小于**引信半径；
2. 未命中 ⇒ `cpa_m` **等于** `min_separation_m`（同一趟飞行的最近距离，且**不复跑**）；
3. 反向：构造命中用例，断言报告表 / 报告 CSV / 图4 的 `run` JSON / 页面摘要里
   **没有任何一格把常数 10.0 当脱靶量输出**；
4. 成本：**只有命中**才多跑一次解算（命中 2 次 / 未命中 1 次；`want_cpa=False` 时 1 次）。

配套：`tests/test_solver_api.py` 钉金标工况，`tests/test_report.py` 钉对比表契约。
"""

from __future__ import annotations

import csv
import math

import pytest

from missile_sim import engine, report, solver, traj
from missile_sim.spec import Scene, Shot

#: 命中工况：默认 50 km 迎头，PL-12 命中 45.1861 s（引信近炸）。
HIT_SCENE = Scene()
#: 未命中工况：200 km 迎头 —— 弹飞完全程也没够着（`lifetime`）。
MISS_SCENE = Scene(range_m=200_000.0)
FUSE_M = 10.0


@pytest.fixture(scope="module")
def hit_shot():
    """命中工况的 `Shot`（`want_cpa` 默认开 ⇒ 真 CPA 已量）。"""
    return solver.run(HIT_SCENE, missile="cn_pl12", tier="fast")


@pytest.fixture(scope="module")
def miss_shot():
    return solver.run(MISS_SCENE, missile="cn_pl12", tier="fast")


# ------------------------------------------------------------------ 1 / 2 语义


def test_hit_min_separation_is_exactly_the_fuse_radius(hit_shot):
    """判据 1a：命中时 `min_separation_m` **就是**引信半径 —— 所以它不可能是脱靶量。"""
    assert hit_shot.ok and hit_shot.hit, hit_shot.error
    assert hit_shot.event == "proximity_fuse"
    assert hit_shot.fuse_radius_m == pytest.approx(FUSE_M, abs=1e-9)
    assert hit_shot.min_separation_m == pytest.approx(hit_shot.fuse_radius_m, abs=1e-9)


def test_hit_true_cpa_is_strictly_inside_the_fuse_radius(hit_shot):
    """判据 1b：关引信复跑量出的真 CPA **严格小于**引信半径（否则复跑口径不对）。"""
    assert math.isfinite(hit_shot.cpa_m), "命中工况必须量出真 CPA（want_cpa 默认开）"
    assert 0.0 <= hit_shot.cpa_m < hit_shot.fuse_radius_m


def test_miss_cpa_equals_min_separation(miss_shot):
    """判据 2：未命中 ⇒ `cpa_m` 与 `min_separation_m` **完全相等**（同一趟飞行）。"""
    assert miss_shot.ok and not miss_shot.hit
    assert miss_shot.event in ("lifetime", "time_limit")
    assert math.isfinite(miss_shot.min_separation_m)
    assert miss_shot.cpa_m == miss_shot.min_separation_m, \
        "未命中的 cpa_m 必须直接取 min_separation_m（不许另算一遍）"


def test_no_cpa_when_not_requested():
    """没请求就不量：`cpa_m` 是 `nan`（"不知道"），**不是 0、也不是引信半径**。"""
    shot = solver.run(HIT_SCENE, missile="cn_pl12", tier="fast", want_cpa=False)
    assert shot.hit and math.isnan(shot.cpa_m)
    assert shot.min_separation_m == pytest.approx(FUSE_M, abs=1e-9)


def test_fuse_radius_survives_the_dict_roundtrip(hit_shot):
    back = Shot.from_dict(hit_shot.as_dict())
    assert back.min_separation_m == hit_shot.min_separation_m
    assert back.cpa_m == hit_shot.cpa_m
    assert back.fuse_radius_m == hit_shot.fuse_radius_m


# ------------------------------------------------------------------ 4 成本


def test_only_a_hit_pays_for_the_cpa_probe():
    """判据 4：数内核解算次数 —— 命中 2 次（主 + 关引信复跑）、未命中 1 次。

    `_simulate` 是"跑一次内核"的唯一落点，所以在这里打桩就是数解算次数；
    参数里带上 `scene.proximity_fuse`，顺手证明复跑那次真的**关了引信**。
    """
    calls = []
    real = solver._simulate

    def spy(wt, scene, missile, scaling, tier):
        calls.append(bool(scene.proximity_fuse))
        return real(wt, scene, missile, scaling, tier)

    solver._simulate = spy
    try:
        solver.run(HIT_SCENE, missile="cn_pl12", tier="fast")
        assert calls == [True, False], f"命中应当是 主解算 + 关引信复跑，实际 {calls}"

        calls.clear()
        solver.run(MISS_SCENE, missile="cn_pl12", tier="fast")
        assert calls == [True], f"未命中不该复跑，实际 {calls}"

        calls.clear()
        solver.run(HIT_SCENE, missile="cn_pl12", tier="fast", want_cpa=False)
        assert calls == [True], f"want_cpa=False 不该复跑，实际 {calls}"
    finally:
        solver._simulate = real


def test_cache_key_carries_want_cpa():
    """缓存键必须含 `want_cpa`：不然"没量过 CPA"的缓存会被当成量过的返回。"""
    from missile_sim import mapping, pool
    metrics = pool.metrics_of(pool.resolve("PL-12"))
    sc = mapping.scaling_for(metrics.dv, metrics.bc, metrics)
    a = engine.cache_key(HIT_SCENE, "cn_pl12", sc, "fast", True)
    b = engine.cache_key(HIT_SCENE, "cn_pl12", sc, "fast", False)
    assert a != b
    assert a == engine.cache_key(HIT_SCENE, "cn_pl12", sc, "fast", want_cpa=True)


# ------------------------------------------------------------------ 3 反向判据


def test_reverse_no_constant_10_as_miss_distance(tmp_path):
    """**反向判据**：命中用例里，报告表/CSV 都不许把 10.0（引信半径）当脱靶量输出。

    三个"不许"：
    * 列名里不许出现"脱靶量"（表头就是契约）；
    * 控制台表的"最近接近"格不许是 10.0 / 10；
    * CSV 的"真最近接近"列对命中行必须 < 引信半径。
    """
    rows = report.compare(HIT_SCENE, missiles=["PL-12", "PL-12A"], tier="fast", cache=False)
    hits = [r for r in rows if r["hit"]]
    assert len(hits) == 2, f"这两个型在默认工况应当都命中：{[(r['key'], r['hit']) for r in rows]}"

    for r in hits:
        assert r["min_separation_m"] == pytest.approx(r["fuse_radius_m"], abs=1e-9)
        assert r["cpa_m"] < r["fuse_radius_m"], f"{r['key']} 的真 CPA 没量到"

    # ① 表头：任何一个列名都不许自称"脱靶量"
    heads = [head for _key, head in report.CSV_HEADER]
    assert not any("脱靶" in h for h in heads), heads
    assert not any("miss_distance" in k for k, _h in report.CSV_HEADER)

    # ② 控制台表：命中行的"最近接近"格不许是 10
    lines = report.format_table(rows).splitlines()
    head = next(ln for ln in lines if ln.startswith("弹名"))
    col = head.split().index("最近接近")
    seen = 0
    for ln in lines:
        cells = ln.split()
        if cells and cells[0] in {r["key"] for r in hits} and len(cells) > col:
            assert cells[col] not in ("10", "10.0"), f"命中行把引信半径当脱靶量了：{ln}"
            assert float(cells[col]) < FUSE_M, ln
            seen += 1
    assert seen == len(hits)

    # ③ CSV：命中行的"真最近接近"列 < 引信半径，且**不存在**脱靶量列
    path = report.write_compare_csv(rows, tmp_path / "a5.csv")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        got = list(reader)
    assert not any("脱靶" in k for k in (reader.fieldnames or []))
    for g in got:
        if g["是否命中"] == "是":
            assert float(g["真最近接近 [m]"]) < FUSE_M, g
            assert float(g["引信半径 [m]"]) == pytest.approx(FUSE_M, abs=1e-9)
            # 事件前最近距离那一列**就是**引信半径 —— 它名字写全了，不是在冒充脱靶量
            assert float(g["事件前最近距离 [m]"]) == pytest.approx(FUSE_M, abs=1e-9)


class _NoLegs:
    """最小 schedule 替身：没有任何腿 ⇒ `build_marks` 只出「发射 / 结束」两个节点。"""

    legs: tuple = ()


def test_reverse_traj_json_has_no_fake_miss_distance(hit_shot):
    """图4 的 `run` JSON：命中行不许出现 `miss_m`，也不许把 10.0 当脱靶量。"""
    sch = _NoLegs()
    run = traj.TrajRun(scene=HIT_SCENE, schedule=sch, shot=hit_shot, segments=[],
                       marks=traj.build_marks(schedule=sch, segments=[], anchor={},
                                              shot=hit_shot),
                       anchor={}, missile="PL-12", beta=3078.1, gamma=56.6)
    d = run.as_dict()
    assert "miss_m" not in d, "旧键名会把引信半径说成脱靶量（A5）"
    assert d["hit"] is True
    assert d["cpa_m"] < d["fuse_radius_m"]
    assert d["min_separation_m"] == pytest.approx(d["fuse_radius_m"], abs=1e-9)
    # 命中工况的结局注记只写"命中"，不写任何距离（要写就写 CPA，见 workflow.run_traj）
    assert [m["note"] for m in d["marks"] if m["name"] == "end"] == ["命中"]

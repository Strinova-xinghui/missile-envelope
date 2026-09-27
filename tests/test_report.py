# -*- coding: utf-8 -*-
"""`report.py` 的验收：逐型对比表的**行数 / 字段 / 标称乘数 / 未命中占位符 / CSV 往返**。

用 `fast` 档 + 一个 40 km 的短环境：11 型约 1.5 s，且 11 型全部命中
（未命中那条路径另用一行**合成结果**覆盖 —— 真实工况里打不中要跑很远才出现）。
`cache=False`：测试既不写 `results/cache/`，也不受已有缓存影响，结果只取决于求解器。
"""

from __future__ import annotations

import csv
import math

import pytest

from missile_sim import engine, mapping, pool, report
from missile_sim.spec import Scene, Shot

#: 测试环境：比默认 50 km 近一点，11 型都稳稳在射程内。
TEST_SCENE = Scene(range_m=40_000, target_speed_ms=280)


@pytest.fixture(scope="module")
def rows():
    """11 型各跑一次（fast 档、不写缓存）；整模块共用这一次结果。"""
    return report.compare(TEST_SCENE, tier="fast", jobs=1, cache=False)


@pytest.fixture(scope="module")
def miss_row():
    """一行**合成的未命中**：`t_hit = nan` —— 专门验证占位符不是 0。"""
    point = pool.points(["PL-12"])[0]
    shot = Shot(ok=True, event="time_limit", hit=False, t_hit=math.nan,
                t_end=60.0, miss_m=2500.0, max_alt_m=20_000.0, v_impact=500.0,
                backend="compiled-c")
    return report.row_of(point, pool.resolve(point.key), shot, tier="fast")


# --------------------------------------------------------------------- 行 / 字段


def test_rows_match_pool(rows):
    """行数 = 弹池数；顺序 = 弹池顺序（与图例一致）。"""
    assert len(rows) == len(pool.names()) == len(pool.POOL)
    assert [r["key"] for r in rows] == pool.names()


def test_rows_have_all_fields(rows):
    for r in rows:
        missing = [k for k in report.ROW_FIELDS if k not in r]
        assert not missing, f"{r['key']} 缺字段：{missing}"


def test_nominal_scaling_is_identity(rows):
    """标称工况：喂进去的 (ΔV, BC) 就是池里现算的权威值 ⇒ 两个乘数恒为 1.0。"""
    for r in rows:
        metrics = pool.metrics_of(pool.resolve(r["key"]))
        sc = mapping.scaling_for(r["dv"], r["bc"], metrics)
        assert sc.thrust_scale == pytest.approx(1.0)
        assert sc.cx_scale == pytest.approx(1.0)
        assert r["thrust_scale"] == 1.0 and r["cx_scale"] == 1.0


def test_dv_bc_equal_pool_points(rows):
    """表里的 ΔV/BC 必须**原样**来自散点，不能另算一遍（否则与图分叉）。"""
    pts = {p.key: p for p in pool.points()}
    for r in rows:
        p = pts[r["key"]]
        assert r["dv"] == p.dv and r["bc"] == p.bc
        assert r["native"] == p.native and r["full_name"] == pool.resolve(p.key).full_name


# --------------------------------------------------------------------- 命中语义


def test_every_row_ran_on_the_solver(rows):
    """`ok` / `backend` 只能来自真跑过的 summary（不许按档位名猜）。"""
    for r in rows:
        assert r["ok"], f"{r['key']} 求解失败：{r['error']}"
        assert r["backend"] and r["backend"] != "unreported"
        assert r["tier"] == "fast"


def test_hit_rows_have_t_hit_misses_are_nan(rows):
    for r in rows:
        if r["hit"]:
            assert r["event"] in ("contact", "proximity_fuse")
            assert math.isfinite(r["t_hit"]) and r["t_hit"] > 0.0, \
                f"{r['key']} 命中却没有有限的 t_hit：{r['t_hit']!r}"
        else:
            assert math.isnan(r["t_hit"]), "未命中的 t_hit 必须是 nan"
    assert sum(1 for r in rows if r["hit"]) == len(rows), "40 km 迎头：11 型应当全部命中"


def test_miss_shows_placeholder_not_zero(miss_row, tmp_path):
    """未命中：控制台表与 CSV 都写 `—`，**绝不写 0**（0 会被读成"命中时间 0 s"）。"""
    assert miss_row["hit"] is False and math.isnan(miss_row["t_hit"])
    assert report.MISS_PLACEHOLDER != "0"

    table = report.format_table([miss_row])
    line = [ln for ln in table.splitlines() if ln.startswith(miss_row["key"])][0]
    assert report.MISS_PLACEHOLDER in line.split()
    assert "0" not in line.split()

    path = report.write_compare_csv([miss_row], tmp_path / "miss.csv")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        got = list(csv.DictReader(fh))[0]
    assert got["t_hit [s]"] == report.MISS_PLACEHOLDER
    assert got["t_hit [s]"] not in ("0", "0.0", "")


# --------------------------------------------------------------------- 落盘 / 打印


def test_csv_is_utf8_sig_and_roundtrips(rows, tmp_path):
    path = report.write_compare_csv(rows, tmp_path / "compare_x.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf"), "CSV 必须是 UTF-8-SIG（Excel 认中文）"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        got = list(reader)
    assert reader.fieldnames == [head for _key, head in report.CSV_HEADER]
    assert len(got) == len(rows)
    assert [g["弹名"] for g in got] == [r["key"] for r in rows]
    for r, g in zip(rows, got):
        assert g["是否命中"] == ("是" if r["hit"] else "否")
        assert g["backend"] == r["backend"] and g["event"] == r["event"]
        if not r["hit"]:
            assert g["t_hit [s]"] in (report.MISS_PLACEHOLDER, "")


def test_format_table_lists_every_missile(rows):
    table = report.format_table(rows, scene=TEST_SCENE, tier="fast")
    for r in rows:
        assert r["key"] in table
    assert "环境：" in table                      # 带 scene 时打印环境行
    assert f"共 {len(rows)} 型" in table
    assert len(table.splitlines()) >= len(rows) + 3
    keys = tuple(r["key"] for r in rows)                # data 行：以弹名开头
    for line in table.splitlines():
        if line.startswith(keys):
            bad = [tok for tok in line.split() if tok.lower() in ("nan", "inf", "-inf")]
            assert not bad, f"nan/inf 不能作为单元格出现在表里：{bad}"


def test_compare_goes_through_engine_many():
    """纪律：批量必须走 `Engine.many()`（绕过它就没有缓存、且会重复计算）。"""
    calls = []
    real = engine.Engine.many

    def spy(self, cells, **kwargs):
        cells = list(cells)                       # 物化后原样转发（many 自己也要迭代）
        calls.append((self.missile, len(cells)))
        return real(self, cells, **kwargs)

    engine.Engine.many = spy
    try:
        report.compare(TEST_SCENE, missiles=["PL-12"], tier="fast", cache=False)
    finally:
        engine.Engine.many = real
    assert calls == [("cn_pl12", 1)], f"实际调用：{calls}"


def test_run_compare_writes_tagged_csv(tmp_path):
    """产物名固定 `compare_<tag>.csv`。"""
    out = report.run_compare(TEST_SCENE, missiles=["PL-12"], tier="fast", tag="unit",
                             result_dir=tmp_path, cache=False)
    path = tmp_path / "compare_unit.csv"
    assert out["_paths"]["compare_csv"] == str(path)
    assert path.exists()
    assert out["missiles"] == ["PL-12"] and out["n_hit"] == 1 and out["n_ok"] == 1
    assert "PL-12" in out["table"]
    assert out["scene"]["range_m"] == TEST_SCENE.range_m


def test_bad_scene_is_rejected():
    with pytest.raises(ValueError):
        report.compare(Scene(duration_s=0.0), missiles=["PL-12"], tier="fast", cache=False)

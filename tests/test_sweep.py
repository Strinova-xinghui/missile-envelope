"""扫描、等时线提取与产物写出测试。"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from missile_sim.config import load_config  # noqa: E402
from missile_sim.decide import STATUS_NAMES, ST_HIT  # noqa: E402
from missile_sim.sweep import (  # noqa: E402
    SweepGrid,
    build_grid,
    extract_isolines,
    monotonic_report,
    run_sweep,
    summary_dict,
    write_cases_csv,
    write_isolines_csv,
    write_summary,
)


@pytest.fixture()
def cfg():
    return load_config()


def test_build_grid_inclusive_endpoints(cfg):
    g = build_grid(cfg)
    assert g.dv[0] == 800.0 and g.dv[-1] == 1500.0
    assert g.bc[0] == 1700.0 and g.bc[-1] == 4000.0
    assert g.shape == (15, 24)


def test_build_grid_non_multiple_range():
    grid = SweepGrid(dv=np.array([800.0, 900.0]), bc=np.array([1700.0]), dv_step=100.0, bc_step=100.0)
    assert grid.shape == (2, 1)
    cfg = load_config()
    cfg.sweep.dv_min, cfg.sweep.dv_max, cfg.sweep.dv_step = 800.0, 1234.0, 100.0
    g = build_grid(cfg)
    assert g.dv[-1] == 1234.0, "非整除时应补上端点"


def test_run_sweep_grid_consistency(cfg):
    cfg.sweep.dv_min, cfg.sweep.dv_max, cfg.sweep.dv_step = 900.0, 1300.0, 200.0
    cfg.sweep.bc_min, cfg.sweep.bc_max, cfg.sweep.bc_step = 1800.0, 3900.0, 700.0
    res, grid, t_grid = run_sweep(cfg)
    assert t_grid.shape == grid.shape
    assert res.dv_total.size == grid.shape[0] * grid.shape[1]
    # 网格首元素对应 (dv[0], bc[0])
    assert res.dv_total[0] == grid.dv[0]
    assert res.bc[0] == pytest.approx(grid.bc[0], rel=1e-9)


def test_isolines_from_synthetic_linear_field():
    """t_hit = 100 - 0.02*(BC-1700)：等时线应是竖直直线，便于校验插值正确性。"""
    bc = np.arange(1700.0, 4001.0, 100.0)
    dv = np.arange(800.0, 1501.0, 50.0)
    t = 100.0 - 0.02 * (bc[None, :] - 1700.0) + 0.0 * dv[:, None]
    grid = SweepGrid(dv=dv, bc=bc, dv_step=50.0, bc_step=100.0)
    lines = extract_isolines(t, grid, step=2.0)
    assert lines, "应至少提取到一条等时线"
    for seg in lines:
        lv = seg["level"]
        # 理论：100 - 0.02*(bc-1700) = lv  =>  bc = 1700 + (100-lv)/0.02
        bc_expect = 1700.0 + (100.0 - lv) / 0.02
        for bc_pt, dv_pt, _ in seg["points"]:
            assert bc_pt == pytest.approx(bc_expect, abs=1.0)
            assert 800.0 - 1e-6 <= dv_pt <= 1500.0 + 1e-6


def test_isolines_skip_nan_regions():
    """BC < 2100 区域全部未命中（NaN），等时线只能在 BC >= 2100 一侧出现。"""
    bc = np.arange(1700.0, 4001.0, 100.0)
    dv = np.array([800.0, 1000.0, 1200.0])
    t = 45.0 + 0.02 * (bc[None, :] - 1700.0) + 1.0 * np.arange(dv.size)[:, None]
    t[:, bc < 2100.0] = np.nan  # 提前未命中区域
    grid = SweepGrid(dv=dv, bc=bc, dv_step=200.0, bc_step=100.0)
    lines = extract_isolines(t, grid, step=2.0)
    assert lines, "NaN 之外仍应提取到等时线"
    for seg in lines:
        for bc_pt, _, _ in seg["points"]:
            assert bc_pt >= 2000.0 - 1e-6, f"等时线不应进入 NaN 区域（BC={bc_pt}）"
    # 常量场 + NaN：marching squares 对完全常量场不给出层级，这里只要求不抛异常
    const = np.full((dv.size, bc.size), 60.0)
    const[:, bc < 2100.0] = np.nan
    extract_isolines(const, grid, step=2.0)


def test_isolines_empty_when_all_nan():
    grid = SweepGrid(dv=np.array([800.0, 900.0]), bc=np.array([1700.0, 1800.0]), dv_step=100.0, bc_step=100.0)
    assert extract_isolines(np.full((2, 2), np.nan), grid) == []


def test_monotonic_report_detects_violation():
    grid = SweepGrid(dv=np.array([900.0, 1000.0]), bc=np.array([1700.0, 1800.0, 1900.0]),
                     dv_step=100.0, bc_step=100.0)
    good = np.array([[80.0, 70.0, 60.0], [78.0, 68.0, 58.0]])
    assert monotonic_report(good, grid) == []
    bad = good.copy()
    bad[1, 1] = 90.0
    assert monotonic_report(bad, grid)
    nan_then_hit = good.copy()
    nan_then_hit[0, 0] = np.nan
    assert monotonic_report(nan_then_hit, grid)


def test_outputs_written(cfg, tmp_path):
    cfg.sweep.dv_min, cfg.sweep.dv_max, cfg.sweep.dv_step = 900.0, 1100.0, 200.0
    cfg.sweep.bc_min, cfg.sweep.bc_max, cfg.sweep.bc_step = 1800.0, 3600.0, 900.0
    res, grid, t_grid = run_sweep(cfg)
    lines = extract_isolines(t_grid, grid, step=2.0)

    cases = write_cases_csv(res, tmp_path / "cases.csv")
    iso = write_isolines_csv(lines, tmp_path / "iso.csv", cfg)
    summary_path = write_summary(tmp_path / "summary.json", summary_dict(cfg, res, grid, t_grid, lines))

    rows = list(csv.DictReader(cases.open(encoding="utf-8")))
    assert len(rows) == grid.shape[0] * grid.shape[1]
    assert set(["dv_total", "bc", "cxk", "status_name", "t_hit_s"]).issubset(rows[0].keys())
    assert all(r["status_name"] in STATUS_NAMES.values() for r in rows)
    # 命中行的 t_hit 必须是数字
    for r in rows:
        if r["status_name"] == "hit":
            assert np.isfinite(float(r["t_hit_s"]))
    iso_rows = list(csv.DictReader(iso.open(encoding="utf-8")))
    assert iso_rows, "等时线 CSV 不应为空"
    assert np.isfinite(float(iso_rows[0]["cxk"]))
    import json

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["grid"]["n_cases"] == grid.shape[0] * grid.shape[1]
    assert data["results"]["n_hit"] == int(np.sum(res.status == ST_HIT))
    assert "config" in data and "derived" in data


def test_summary_counts(cfg):
    cfg.sweep.dv_min, cfg.sweep.dv_max, cfg.sweep.dv_step = 1000.0, 1200.0, 200.0
    cfg.sweep.bc_min, cfg.sweep.bc_max, cfg.sweep.bc_step = 2000.0, 3000.0, 1000.0
    res, grid, t_grid = run_sweep(cfg)
    s = summary_dict(cfg, res, grid, t_grid, [])
    assert s["results"]["n_hit"] == int(np.sum(res.status == ST_HIT))
    assert sum(s["results"]["status_counts"].values()) == res.status.size
    assert s["derived"]["bc_baseline"] == pytest.approx(3624.0, abs=2.0)

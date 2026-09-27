# -*- coding: utf-8 -*-
"""端到端出图与产物：**字节可复现**是硬要求。

`savefig` 的元数据时间戳被压制（PDF 的 `CreationDate`/`ModDate`、SVG 的 `Date`、
PNG 的 `Software`），SVG 里 matplotlib 用 `id()` 派生的元素 id 也被重编号 —— 所以
同参数跑两次，三格式必须逐字节相同。这条要是断了，`figures/` 会每次出图都留一个假 diff。

用小网格（3×5 = 15 工况）+ `fast` 档；整个文件只跑**两次** `run_plane`（约 8 s），
其余用例复用同一批产物。产物写在 `.tmp_test/` 下，**不碰仓库里的 `figures/` 与 `results/`**。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from missile_sim import workflow
from missile_sim.spec import Scene

ROOT = Path(__file__).resolve().parents[1]
FORMATS = ("png", "pdf", "svg")
TAG = "reprotest"
N_CASES = 15                       # 3×5 网格


def _req(tmp_path, **over):
    """小网格请求：轴刻意给窄，网格只有 3×5 = 15 工况。"""
    kw = dict(
        scene=Scene(),
        missiles=("PL-12",),
        tier="fast",
        dv_step=20.0,
        bc_step=50.0,
        jobs=2,
        cache=False,               # 临时目录里的缓存没意义，还会拖慢重复跑
        xlim=(920.0, 946.0),
        ylim=(3000.0, 3160.0),
        tag=TAG,
        formats=FORMATS,
        figure_dir=tmp_path / "figures",
        result_dir=tmp_path / "results",
    )
    kw.update(over)
    return workflow.PlaneRequest(**kw)


def _hashes(paths):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def _fig_files(d):
    return sorted((d / "figures").glob(f"fig_isotime_plane_{TAG}.*"))


def _rows(d, kind):
    """读 CSV：`kind` 取 `cases` / `isolines`。"""
    p = d / "results" / f"plane_{TAG}_{kind}.csv"
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def repro():
    """跑两次 `run_plane`，把产物目录与两轮 sha256 一起交出去。

    自己建目录而不是用 `tmp_path`：`tmp_path` 是函数作用域，模块作用域的 fixture 用不了它；
    而 7 个用例各跑一次 `run_plane` 会把这个文件拖到 30 s 以上。
    """
    base = Path(os.environ.get("MSIM_TEST_TMPDIR", ROOT / ".tmp_test"))
    d = base / f"repro_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        workflow.run_plane(_req(d))
        first = _hashes(_fig_files(d))
        workflow.run_plane(_req(d))
        second = _hashes(_fig_files(d))
        yield {"dir": d, "first": first, "second": second}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------- 产物齐全


def test_run_plane_writes_all_artifacts(repro):
    d = repro["dir"]
    assert len(_fig_files(d)) == 3, f"应该有三个格式，实际 {[p.name for p in _fig_files(d)]}"
    for ext in FORMATS:
        assert (d / "figures" / f"fig_isotime_plane_{TAG}.{ext}").is_file()
    for kind in ("cases", "isolines"):
        assert (d / "results" / f"plane_{TAG}_{kind}.csv").is_file()
    assert (d / "results" / f"plane_{TAG}.json").is_file()


# --------------------------------------------------------------- 可复现


def test_figures_are_byte_reproducible(repro):
    """同参数连跑两次 ⇒ 三格式 sha256 必须逐字节一致。"""
    first, second = repro["first"], repro["second"]
    assert len(first) == 3
    diff = [k for k in sorted(set(first) | set(second)) if first.get(k) != second.get(k)]
    assert not diff, (
        "图不再字节可复现：\n  " +
        "\n  ".join(f"{k}: {first.get(k)} -> {second.get(k)}" for k in diff))


def test_svg_has_no_wallclock_metadata(repro):
    """SVG 里不能留 `Date:` 之类的墙上时钟元数据。"""
    svg = (repro["dir"] / "figures" / f"fig_isotime_plane_{TAG}.svg").read_text(
        encoding="utf-8", errors="replace")
    assert "Date:" not in svg, "SVG 里混进了时间戳"


# --------------------------------------------------------------- CSV 契约


def test_cases_csv_has_one_row_per_grid_point(repro):
    rows = _rows(repro["dir"], "cases")
    assert len(rows) == N_CASES, f"3×5 网格应该有 {N_CASES} 行，实际 {len(rows)}"
    need = {"dv_target", "bc_target", "thrust_scale", "cx_scale",
            "hit", "t_hit_s", "max_alt_m", "backend"}
    assert need <= set(rows[0]), f"cases CSV 缺列：{sorted(need - set(rows[0]))}"


def test_misses_in_csv_are_blank_not_zero(repro):
    """未命中的 `t_hit_s` 必须留空 —— 写成 0 会被当成"0 秒命中"。"""
    for r in _rows(repro["dir"], "cases"):
        if str(r.get("hit", "")).strip() in ("0", "False", "false", ""):
            assert r["t_hit_s"].strip() == "", f"未命中却写了 t_hit_s={r['t_hit_s']!r}"


def test_isolines_csv_round_trips(repro):
    rows = _rows(repro["dir"], "isolines")
    assert rows, "等时线 CSV 是空的（这个网格应该命中）"
    assert {"t_hit_level_s", "dv_target", "bc", "closed"} <= set(rows[0])
    lv = sorted({float(r["t_hit_level_s"]) for r in rows})
    assert all(x.is_integer() for x in lv), "等时线层级必须是 1 s 的整数倍"


# --------------------------------------------------------------- manifest


def test_manifest_is_json_with_provenance(repro):
    man = json.loads((repro["dir"] / "results" / f"plane_{TAG}.json").read_text(encoding="utf-8"))
    assert isinstance(man, dict) and man
    blob = json.dumps(man, ensure_ascii=False)
    assert "wt-missile" in blob, "manifest 里必须留求解器出处"
    for needle in ("fast", "PL-12"):
        assert needle in blob, f"manifest 里缺少 {needle!r}"

# -*- coding: utf-8 -*-
"""图2 的**末端编排**契约：`workflow.run_bg()` 的产物、CLI 参数、WebUI 表单。

分三段：

* `run_bg()` 真的把图 + CSV + manifest 落下来，且 manifest 里记下了
  第二张图独有的两个量（固定 ΔV、参考工况）；
* CLI 的 `--figure bg` 那套参数确实进了 `BgRequest`（argparse 的默认值是 None，
  少一个字段名就会静默丢掉，见 `PlaneRequest` 那次 `--missiles` 失效的事故）；
* WebUI 的表单能过 `build_scene_from_form()`（参考工况那两个专名必须被挡在场景之外）。
"""

import csv
import json
from dataclasses import fields
from pathlib import Path

import pytest

from missile_sim import bg, cli, workflow
from missile_sim.workflow import BgRequest, run_bg

#: 粗网格：只用来验链路，不追求图好看（默认 30/2 会跑 ~1000 个工况）
COARSE = dict(beta_step=400.0, gamma_step=15.0, formats=("png",))


def _read_csv(path):
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def test_run_bg_without_scan_still_lands_points_and_manifest(tmp_path):
    """不跑仿真层也要能出图：散点 + 等 n* 线 + manifest（`scan` 为 None）。"""
    req = BgRequest(with_scan=False, tag="nofly", formats=("png",),
                    figure_dir=tmp_path / "fig", result_dir=tmp_path / "res")
    out = run_bg(req)

    figs = out["_paths"]["figures"]
    assert len(figs) == 1 and Path(figs[0]).suffix == ".png"
    assert Path(figs[0]).stat().st_size > 50_000
    assert Path(out["_paths"]["points"]).is_file()
    assert "cases" not in out["_paths"] and "isolines" not in out["_paths"]

    man = json.loads(Path(out["_paths"]["manifest"]).read_text(encoding="utf-8"))
    assert man["figure"] == "beta-gamma"
    assert man["with_scan"] is False and man["scan"] is None
    assert man["n_ref_g"] == 20.0
    assert len(man["points"]) == 11
    assert man["missiles"][0] == "120A"
    # 参考工况必须逐值记下来 —— `n*` 依赖它，不记就没法复现
    assert man["reference"]["alt_m"] == 10000.0
    assert man["reference"]["speed_ms"] == 800.0
    assert man["reference"]["q_pa"] == pytest.approx(132363.7, abs=0.5)
    assert man["reference"]["cap_over_f"] == pytest.approx(3.0998, abs=1e-4)


def test_run_bg_scan_writes_beta_gamma_columns_and_monotonic_checks(tmp_path):
    """扫描层：逐格点表 / 等时线表用 **β/γ 列名**（不是 dv/bc），并给出双向单调性。"""
    req = BgRequest(tag="scan", figure_dir=tmp_path / "fig", result_dir=tmp_path / "res",
                    **COARSE)
    out = run_bg(req)

    cases = _read_csv(out["_paths"]["cases"])
    head = cases[0]
    assert head[:5] == ["beta_target", "gamma_target", "thrust_scale", "cx_scale",
                        "cxaoa_scale"]
    assert "dv_target" not in head and "bc_target" not in head
    assert len(cases) - 1 == out["grid"].n_cases
    # 每一行都要真的带上三个乘数，而且 cxaoa_scale 不能恒为 1（那就是没生效）
    aoa = [float(r[4]) for r in cases[1:]]
    assert max(aoa) > 1.5 and min(aoa) < 1.0, (min(aoa), max(aoa))

    iso = _read_csv(out["_paths"]["isolines"]) if Path(out["_paths"]["isolines"]).is_file() \
        else None
    if iso is not None:
        assert iso[0] == ["t_hit_level_s", "beta", "gamma", "closed"]

    man = json.loads(Path(out["_paths"]["manifest"]).read_text(encoding="utf-8"))
    scan = man["scan"]
    assert scan["dv_pin_ms"] == pytest.approx(out["dv_pin"])
    assert scan["n_cases"] == out["grid"].n_cases
    assert scan["beta_cells"] == len(out["grid"].dv)
    assert 0 < scan["n_hit"] <= scan["n_cases"]
    # β 越大越省、γ 越大越费：两个方向的自检都要过（网格粗，但方向不该反）
    assert man["monotonic_beta"]["n_non_monotonic"] == 0
    assert man["monotonic_gamma"]["n_non_monotonic"] == 0
    assert len(man["iso_levels"]) >= 2, man["iso_levels"]


def test_run_bg_honours_the_dv_pin(tmp_path):
    """固定 ΔV 是第二张图的关键旋钮：给了就必须进 manifest 与 thrust_scale。"""
    common = dict(with_scan=False, tag="pin", formats=("png",),
                  figure_dir=tmp_path / "fig", result_dir=tmp_path / "res")
    a = run_bg(BgRequest(**common))
    b = run_bg(BgRequest(dv_pin=500.0, **common))
    assert a["dv_pin"] == pytest.approx(932.57, abs=0.01)     # 基准弹标称
    assert b["dv_pin"] == pytest.approx(500.0)
    man = json.loads(Path(b["_paths"]["manifest"]).read_text(encoding="utf-8"))
    assert man["scan"] is None                                # 没跑扫描

    # 真跑一个格点，确认推力乘数跟着 ΔV 走
    from missile_sim import engine, mapping, pool, solver
    entry = pool.resolve("PL-12")
    p = bg.point_of(entry)
    m = mapping.blk_metrics(solver.profile(entry.native))
    sc = bg.scaling_for(p, m, beta=p.beta, gamma=p.gamma, dv=500.0)
    assert sc.thrust_scale == pytest.approx(500.0 / m.dv, rel=1e-9)


def test_run_bg_rejects_inconsistent_input(tmp_path):
    req = BgRequest(beta_step=0.0, figure_dir=tmp_path / "fig", result_dir=tmp_path / "res")
    with pytest.raises(ValueError):
        run_bg(req)


def test_reference_condition_only_moves_the_nstar_family(tmp_path):
    """参考工况只影响等 n* 线与派生指标，**不动散点**（β、γ 是固有量）。"""
    common = dict(with_scan=False, tag="ref", formats=("png",),
                  figure_dir=tmp_path / "fig", result_dir=tmp_path / "res")
    a = run_bg(BgRequest(**common))
    b = run_bg(BgRequest(alt_m=5000.0, speed_ms=600.0, **common))
    assert [(r.key, r.beta, r.gamma) for r in a["rows"]] == \
        [(r.key, r.beta, r.gamma) for r in b["rows"]]
    # 但派生指标要变（参考过载下的 R / β_eff 依赖 q）
    assert a["reference"].q_pa != b["reference"].q_pa
    assert [r.beta_eff for r in a["rows"]] != [r.beta_eff for r in b["rows"]]


# --------------------------------------------------------------- CLI


def test_cli_bg_flags_all_land_on_bg_request():
    """`BgRequest` 的每个字段都必须有 CLI 出口，否则参数是"写了不生效"。"""
    args = cli.build_parser().parse_args([
        "--figure", "bg", "--bg-no-scan", "--beta-step", "40", "--gamma-step", "3",
        "--bg-dv", "880", "--bg-n", "15", "--bg-alt", "12000", "--bg-speed", "900",
        "--missiles", "PL-12,R-77", "--tier", "standard", "--tag", "cli",
        "--no-cache", "--formats", "png",
    ])
    req = cli._request(args, BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    assert req.with_scan is False
    assert (req.beta_step, req.gamma_step) == (40.0, 3.0)
    assert req.dv_pin == 880.0 and req.n_ref == 15.0
    assert (req.alt_m, req.speed_ms) == (12000.0, 900.0)
    assert list(req.missiles) == ["PL-12", "R-77"]
    assert req.tier == "standard" and req.cache is False
    assert req.tag == "cli" and req.formats == ("png",)


def test_cli_bg_defaults_are_the_documented_ones():
    req = cli._request(cli.build_parser().parse_args(["--figure", "bg"]),
                       BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    assert req.with_scan is True
    assert (req.beta_step, req.gamma_step, req.iso_step) == (30.0, 2.0, 1.0)
    assert req.n_ref == 20.0
    assert req.dv_pin is None and req.alt_m is None and req.speed_ms is None


def test_cli_refuses_unknown_json_keys_for_the_selected_figure(tmp_path):
    """`--input` 的键校验跟着 `--figure` 走：图2 不吃 `bc_step`，图1 不吃 `gamma_step`。"""
    path = tmp_path / "in.json"
    path.write_text(json.dumps({"gamma_step": 5.0}), encoding="utf-8")
    args = cli.build_parser().parse_args(["--input", str(path)])
    with pytest.raises(ValueError):
        cli._request(args, workflow.PlaneRequest, cli._PLANE_FIELDS)
    ok = cli._request(args, BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    assert ok.gamma_step == 5.0


def test_cli_field_sets_cover_every_dataclass_field():
    """字段集是从 dataclass 现算的；这条防的是"加了字段忘了接到 CLI"。"""
    for cls, names in ((workflow.PlaneRequest, cli._PLANE_FIELDS),
                       (BgRequest, cli._BG_FIELDS)):
        want = {f.name for f in fields(cls)} - {"scene"}
        assert set(names) == want, (cls.__name__, sorted(want - set(names)),
                                    sorted(set(names) - want))
    # 外部名是 dataclass 字段名经 `_BG_ALIASES` 折出来的那一套，必须一一对应
    assert cli._BG_EXTERNAL == tuple(cli._external_name(n, cli._BG_ALIASES)
                                     for n in cli._BG_FIELDS)
    # 每个外部名都得有一个同名 CLI 参数（dest 对齐）。**输出目录是例外**：
    # `figure_dir` / `result_dir` 由 `spec` 给默认值、只在 WebUI 配置里覆盖，
    # 没有 CLI 出口（图1 也一样）。
    dests = {a.dest for a in cli.build_parser()._actions}
    out_dirs = {"figure_dir", "result_dir"}
    missing = [n for n in cli._BG_EXTERNAL if n not in dests and n not in out_dirs]
    assert not missing, f"这些图2 字段没有 CLI 参数：{missing}"


def test_cli_bg_reference_condition_does_not_alias_the_scene_altitude():
    """`BgRequest.alt_m` 与 `Scene.alt_m` 同名但含义完全不同（参考工况 vs 载机高度）。

    表单/CLI 上必须分开：`--bg-alt` 只改图2 的参考工况，`--alt` 只改载机高度。
    曾经把两者混为一谈的写法会让"改参考高度"顺手改掉发射高度，而且不报错。
    """
    p = cli.build_parser()
    a = p.parse_args(["--figure", "bg", "--bg-alt", "3000", "--alt", "7000"])
    assert a.alt_m == 7000.0 and a.bg_alt_m == 3000.0
    req = cli._request(a, BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    assert req.alt_m == 3000.0                  # 参考工况
    assert req.scene.alt_m == 7000.0             # 载机高度
    # 只给 `--bg-alt` 时，场景的载机高度保持默认，不许被顺手改掉
    b = cli.build_parser().parse_args(["--figure", "bg", "--bg-alt", "3000"])
    req2 = cli._request(b, BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    from missile_sim.spec import Scene
    assert req2.scene.alt_m == Scene().alt_m

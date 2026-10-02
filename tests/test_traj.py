# -*- coding: utf-8 -*-
"""图3（机动想定轨迹）的回归测试。

分两层：

* **纯函数层**（`traj.py` / `TrajRequest.check()` / CLI 映射）—— 毫秒级，不跑求解器；
* **集成层**（`run_traj` 两遍法 → 出图 → 产物）—— fast 档每次约 0.3~0.5 s，锁的是
  `docs/MANEUVER-TARGETS.md` §8.8.5 记录的两个数：延迟 0 ⇒ 69.554 s、延迟 1.0 ⇒ 69.172 s。

⚠ 纯函数层里手造 `rows`（只给 `t` / `range`）就是故意的：`find_anchor` 的契约是
"在轨迹上取首个 `range ≤ lockDistance`"，与求解器无关，拿假行就能把它钉死。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest                                                     # noqa: E402

from missile_sim import cli, traj, workflow                       # noqa: E402
from missile_sim.flightpath import crank_beam                     # noqa: E402
from missile_sim.spec import Scene, Shot                          # noqa: E402

LOCK = 16_000.0                       # PL-12 的 guidance.lockDistance
HIT_NO_DELAY = 69.554                 # §8.8.5（延迟 0）
HIT_WITH_DELAY = 69.172               # §8.8.5（延迟 1.0）
T_BEAM = 34.46                        # 开机时刻（一遍法反求，实测）


def scene_50km(**kw) -> Scene:
    """默认几何：50 km 迎头、10 km 同高、双方 300 m/s —— 与 §8.8 的记录工况一致。"""
    base = dict(range_m=50_000.0, alt_m=10_000.0, vm0=300.0, launch_heading_deg=0.0,
                target_heading_deg=180.0, target_speed_ms=300.0, duration_s=150.0)
    base.update(kw)
    return Scene(**base)


def req_50km(**kw) -> workflow.TrajRequest:
    base = dict(scene=scene_50km(), standard="PL-12", tier="fast", tag="t",
                formats=("png",))
    base.update(kw)
    return workflow.TrajRequest(**base)


def marks_for(sch, *, anchor, shot):
    return traj.build_marks(schedule=sch, segments=sch.segments(duration_s=shot.t_end),
                            anchor=anchor, shot=shot)


ANCHOR = {"mode": "test", "lock_distance_m": LOCK, "t_beam_s": T_BEAM,
          "range_at_beam_m": 15_990.0}


# ------------------------------------------------------------------ 纯函数层


def test_find_anchor_takes_the_first_sample_inside_the_lock_range():
    rows = [{"t": 0.0, "range": 50_000.0}, {"t": 1.0, "range": 20_000.0},
            {"t": 2.0, "range": LOCK}, {"t": 3.0, "range": 15_999.0}]
    got = traj.find_anchor(rows, lock_distance_m=LOCK)
    assert got["t_beam_s"] == 2.0                     # `<=`：正好等于也算进
    assert got["range_at_beam_m"] == LOCK
    assert got["lock_distance_m"] == LOCK


def test_find_anchor_skips_rows_without_a_range_and_reports_never_locked():
    rows = [{"t": 0.0, "range": None}, {"t": 1.0, "range": 90_000.0}]
    got = traj.find_anchor(rows, lock_distance_m=LOCK)
    assert got["t_beam_s"] is None and got["range_at_beam_m"] is None
    assert traj.find_anchor([], lock_distance_m=LOCK)["t_beam_s"] is None


def test_find_anchor_rejects_a_bad_lock_distance():
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="开机距离"):
            traj.find_anchor([{"t": 0.0, "range": 1.0}], lock_distance_m=bad)


def test_marks_use_the_turn_segment_not_the_hold_for_crank_done():
    """`crank_done` 必须取**转弯段**的 `t1`（15.475 s），不是同 phase 那条保持段的 `t1`。

    踩过的坑：`{s.phase: s for s in segments}` 会被"保持段"覆盖，于是
    `crank_done` 落到 39 指令前一刻（34.46 s），图上就凭空多出一段"转完了"。
    """
    sch = crank_beam(8.0, 70.0, T_BEAM, react_delay_s=1.0)   # 默认 5G
    marks = marks_for(sch, anchor=ANCHOR,
                      shot=Shot(ok=True, hit=True, t_end=HIT_NO_DELAY,
                                t_hit=HIT_NO_DELAY, miss_m=10.0, event="hit"))
    assert [m.name for m in marks] == ["launch", "crank_start", "crank_done",
                                       "seeker_on", "beam_start", "end"]
    assert marks[2].t_s == pytest.approx(15.47491, abs=1e-4)
    assert marks[3].t_s == pytest.approx(T_BEAM)
    assert marks[4].t_s == pytest.approx(T_BEAM + 1.0)             # 延迟后才是 39
    assert "延迟 1 s" in marks[4].note


def test_marks_skip_crank_done_when_the_turn_is_truncated():
    """"没转完"时**不许**有 `crank_done` —— 那正是图要表达的东西（计划 §8.7）。"""
    sch = crank_beam(25.0, 70.0, 30.0, react_delay_s=1.0)          # t_react=31 > 25
    segs = sch.segments(duration_s=80.0)
    assert any(s.truncated for s in segs)
    marks = traj.build_marks(schedule=sch, segments=segs,
                             anchor=dict(ANCHOR, t_beam_s=30.0),
                             shot=Shot(ok=True, hit=True, t_end=60.0, t_hit=60.0,
                                       miss_m=8.0, event="hit"))
    names = [m.name for m in marks]
    assert "crank_start" in names and "crank_done" not in names


def test_marks_report_a_miss_with_its_distance():
    sch = crank_beam(8.0, 70.0, T_BEAM, react_delay_s=1.0)
    shot = Shot(ok=True, hit=False, t_end=150.0, miss_m=1988.9, event="lifetime")
    last = marks_for(sch, anchor=ANCHOR, shot=shot)[-1]
    assert last.name == "end" and last.t_s == pytest.approx(150.0)
    assert "脱靶" in last.note and "1989" in last.note


def test_trajrun_as_dict_keeps_json_free_of_nan_and_infinity():
    sch = crank_beam(8.0, 70.0, T_BEAM, react_delay_s=1.0)
    shot = Shot(ok=True, hit=False, t_end=150.0, miss_m=1988.9, event="lifetime")
    run = traj.TrajRun(scene=scene_50km(), schedule=sch, shot=shot,
                       segments=sch.segments(duration_s=150.0), anchor=ANCHOR,
                       marks=marks_for(sch, anchor=ANCHOR, shot=shot),
                       missile="PL-12", beta=3078.1, gamma=56.6)
    text = json.dumps(run.as_dict(), ensure_ascii=False)
    assert "NaN" not in text and "Infinity" not in text
    blob = json.loads(text)
    assert blob["hit"] is False and blob["t_hit_s"] is None       # nan ⇒ None，不是 0
    assert blob["beta"] == 3078.1 and len(blob["segments"]) == 5


def test_segment_tables_must_be_clipped_before_they_are_json_safe():
    """`Segment.t1_s` 允许是 `inf`，但 `json.dumps` **不会报错**——它会写出
    `Infinity`（不是合法 JSON）。所以落盘前必须 `segments(duration_s=…)` 夹紧。"""
    sch = crank_beam(8.0, 70.0, T_BEAM, react_delay_s=1.0)
    raw, clipped = sch.segments(), sch.segments(duration_s=70.0)
    assert raw[-1].t1_s == float("inf")
    assert "Infinity" in json.dumps([s.as_dict() for s in raw])
    assert "Infinity" not in json.dumps([s.as_dict() for s in clipped])


# ------------------------------------------------------------------ 输入校验


def test_traj_request_rejects_a_scene_that_already_has_maneuvers():
    """目标运动由本请求编译；在 `Scene` 上另给一份会被静默覆盖 ⇒ 直接拒收。"""
    bad = req_50km(scene=scene_50km(maneuvers=((0.0, (0.0, 0.0, 0.0)),))).check()
    assert any("maneuvers" in b for b in bad)


def test_traj_request_rejects_every_out_of_range_scenario():
    cases = ({"t_crank": -1.0}, {"crank_deg": 0.0}, {"crank_deg": 180.0},
             {"beam_deg": 0.0}, {"beam_deg": 180.0}, {"crank_g": 0.0},
             {"beam_g": -1.0}, {"lock_distance_m": -5.0}, {"lock_distance_m": 0.0},
             {"react_delay_s": -0.1}, {"react_delay_s": float("inf")},
             {"t_beam_s": -1.0}, {"tier": "turbo"},
             {"weave": True, "weave_hz": 0.0}, {"weave": True, "weave_amp_deg": 90.0})
    for kw in cases:
        assert req_50km(**kw).check(), kw
    assert req_50km().check() == []                               # 默认值必须干净
    assert req_50km(weave=True, weave_amp_deg=6.0, weave_hz=0.3).check() == []


def test_traj_request_reports_paths_out_of_as_dict():
    """输入快照要能直接进 JSON：目录这类 Path 不能混进去。"""
    blob = req_50km(figure_dir=Path("x"), result_dir=Path("y")).as_dict()
    json.dumps(blob, ensure_ascii=False)
    assert "figure_dir" not in blob and "figure_dir" not in blob


def test_run_traj_refuses_an_inconsistent_request_before_solving():
    with pytest.raises(ValueError, match="不自洽"):
        workflow.run_traj(req_50km(crank_deg=0.0))


# ------------------------------------------------------------------ CLI 映射


def test_cli_traj_flags_all_land_on_the_traj_request():
    args = cli.build_parser().parse_args([
        "--figure", "traj", "--traj-t-crank", "12", "--traj-crank-deg", "60",
        "--traj-crank-g", "10", "--traj-beam-deg", "80", "--traj-beam-g", "7",
        "--traj-lock-m", "20000", "--traj-react-delay", "1.5", "--traj-weave",
        "--traj-weave-amp", "6", "--traj-weave-hz", "0.3", "--traj-t-beam", "40",
        "--traj-preview", "--standard", "R-77-1", "--tier", "standard",
        "--tag", "cli", "--formats", "png",
    ])
    req = cli._request(args, workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    assert (req.t_crank, req.crank_deg, req.crank_g) == (12.0, 60.0, 10.0)
    assert (req.beam_deg, req.beam_g) == (80.0, 7.0)
    assert req.lock_distance_m == 20_000.0 and req.react_delay_s == 1.5
    assert req.weave is True and (req.weave_amp_deg, req.weave_hz) == (6.0, 0.3)
    assert req.t_beam_s == 40.0 and req.preview is True
    assert req.standard == "R-77-1" and req.tier == "standard"
    assert req.tag == "cli" and req.formats == ("png",)


def test_cli_traj_defaults_are_the_documented_ones():
    req = cli._request(cli.build_parser().parse_args(["--figure", "traj"]),
                       workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    assert (req.t_crank, req.crank_deg, req.crank_g) == (8.0, 70.0, 9.0)
    assert (req.beam_deg, req.beam_g) == (90.0, 9.0)              # 39 位 = 正侧方
    assert req.react_delay_s == 1.0 and req.lock_distance_m is None
    assert req.weave is False and req.t_beam_s is None and req.preview is False


def test_cli_traj_no_weave_can_override_a_json_true():
    a = cli.build_parser().parse_args(["--figure", "traj", "--traj-no-weave"])
    assert a.traj_weave is False
    assert cli.build_parser().parse_args(["--figure", "traj"]).traj_weave is None


def test_cli_traj_field_sets_cover_every_dataclass_field():
    from dataclasses import fields

    want = {f.name for f in fields(workflow.TrajRequest)} - {"scene"}
    assert set(cli._TRAJ_FIELDS) == want, sorted(want ^ set(cli._TRAJ_FIELDS))
    assert cli._TRAJ_EXTERNAL == tuple(cli._external_name(n, cli._TRAJ_ALIASES)
                                       for n in cli._TRAJ_FIELDS)
    dests = {a.dest for a in cli.build_parser()._actions}
    missing = [n for n in cli._TRAJ_EXTERNAL
               if n not in dests and n not in {"figure_dir", "result_dir"}]
    assert not missing, f"这些图3 字段没有 CLI 参数：{missing}"


def test_cli_figure_choices_cover_three_figures_plus_both_and_all():
    action = next(a for a in cli.build_parser()._actions if a.dest == "figure")
    assert set(action.choices) >= {"plane", "bg", "traj", "both", "all"}


# ------------------------------------------------------------------ JSON 输入
# `_from_json()` 的别名折叠曾经**方向写反**：`aliases` 是"字段名 → 外部名"，
# 折叠却按"外部名 → 字段名"解包，于是 `bg_alt_m` 折出来还是 `bg_alt_m`，
# `cls(**extra)` 直接 `TypeError` —— **凡是带别名的键，`--input` 一律炸**。
# 更隐蔽的是折出来的 `alt_m` 还会被下一步当**场景字段**收走（参考高度悄悄改掉发射高度）。


def _json_req(tmp_path, blob, cls, fields, aliases):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(blob), encoding="utf-8")
    return cli._request(cli.build_parser().parse_args(["--input", str(path)]),
                        cls, fields, aliases)


def test_cli_json_accepts_both_the_external_and_the_field_spelling(tmp_path):
    a = _json_req(tmp_path, {"traj_t_crank": 12.0, "traj_weave": True},
                  workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    b = _json_req(tmp_path, {"t_crank": 12.0, "weave": True},
                  workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    assert (a.t_crank, a.weave) == (12.0, True)
    assert (b.t_crank, b.weave) == (12.0, True)


def test_cli_json_scene_fields_stay_scene_fields(tmp_path):
    """图3 的字段没有与场景撞名的，所以平铺的 `alt_m` / `duration_s` 照旧进场景。"""
    req = _json_req(tmp_path, {"t_crank": 12.0, "alt_m": 7000.0, "duration_s": 90.0},
                    workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    assert (req.scene.alt_m, req.scene.duration_s) == (7000.0, 90.0)


def test_cli_json_external_name_does_not_leak_into_the_scene(tmp_path):
    """图2 的撞名坑：`bg_alt_m` 是**参考工况**，绝不能顺手改掉载机高度。

    正是这个坑决定了别名的存在（见 `cli._BG_ALIASES` 的注释），但 `--input` 这条
    路径原先根本没测过 —— `bg_alt_m` 会被折成 `alt_m` 再被当成场景字段。
    """
    req = _json_req(tmp_path, {"bg_alt_m": 3000.0, "bg_speed_ms": 900.0,
                               "scene": {"alt_m": 7000.0}},
                    workflow.BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    assert (req.alt_m, req.speed_ms) == (3000.0, 900.0)          # 参考工况
    assert req.scene.alt_m == 7000.0                             # 载机高度，没被动
    # 只给平铺的 `alt_m` 时，它是**场景**字段，参考工况保持默认
    req2 = _json_req(tmp_path, {"alt_m": 7000.0},
                     workflow.BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)
    assert req2.alt_m is None and req2.scene.alt_m == 7000.0


def test_cli_json_refuses_two_spellings_of_the_same_key(tmp_path):
    with pytest.raises(ValueError, match="只能给一个"):
        _json_req(tmp_path, {"traj_t_crank": 12.0, "t_crank": 5.0},
                  workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    with pytest.raises(ValueError, match="场景字段"):
        _json_req(tmp_path, {"bg_alt_m": 3000.0, "alt_m": 7000.0},
                  workflow.BgRequest, cli._BG_FIELDS, cli._BG_ALIASES)


def test_cli_json_still_refuses_unknown_keys(tmp_path):
    with pytest.raises(ValueError, match="不认识的键"):
        _json_req(tmp_path, {"traj_nope": 1.0},
                  workflow.TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)


# ------------------------------------------------------------------ 集成层


def test_run_traj_reproduces_the_documented_hit_times(tmp_path):
    """P2 的验收：锚点 34.46 s；延迟 0 ⇒ 69.554 s，延迟 1.0 ⇒ 69.172 s。"""
    out0 = workflow.run_traj(req_50km(react_delay_s=0.0, figure_dir=tmp_path,
                                      result_dir=tmp_path))
    assert out0["t_beam_s"] == pytest.approx(T_BEAM, abs=0.05)
    assert out0["lock_distance_m"] == LOCK                      # 取自 blk
    assert out0["shot"].hit
    assert out0["shot"].t_hit == pytest.approx(HIT_NO_DELAY, abs=0.01)

    out1 = workflow.run_traj(req_50km(react_delay_s=1.0, figure_dir=tmp_path,
                                      result_dir=tmp_path))
    assert out1["anchor"]["t_beam_s"] == pytest.approx(out0["t_beam_s"])
    assert out1["t_react_s"] == pytest.approx(out1["t_beam_s"] + 1.0)
    assert out1["shot"].t_hit == pytest.approx(HIT_WITH_DELAY, abs=0.01)
    # 开机时 crank 已转完（12.15 s 到位），航向就是 110°
    assert out1["anchor"]["completed"] is True
    assert out1["anchor"]["heading_at_beam_deg"] == pytest.approx(110.0, abs=1e-6)
    assert out1["anchor"]["t_crank_turn_end_s"] == pytest.approx(12.1527, abs=1e-3)
    # 第一遍（不含 39 腿）自己也是命中的，但那不是结论
    assert out1["shot_pass1"] is not None and out1["shot_pass1"].hit


def test_run_traj_pinned_t_beam_skips_the_first_pass(tmp_path):
    out = workflow.run_traj(req_50km(t_beam_s=T_BEAM, figure_dir=tmp_path,
                                     result_dir=tmp_path))
    assert out["shot_pass1"] is None
    assert out["anchor"]["mode"].startswith("用户指定")
    assert out["t_react_s"] == pytest.approx(T_BEAM + 1.0)
    assert out["shot"].t_hit == pytest.approx(HIT_WITH_DELAY, abs=0.05)


def test_run_traj_marks_a_truncated_crank_as_not_completed(tmp_path):
    """`completed`（开机时转没转完）与 `Segment.truncated`（39 指令有没有截断它）
    是**两个不同的节点** —— 前者看 `t_beam`，后者看 `t_react`。"""
    out = workflow.run_traj(req_50km(t_crank=28.0, t_beam_s=29.13, figure_dir=tmp_path,
                                     result_dir=tmp_path))
    assert out["anchor"]["completed"] is False
    assert out["anchor"]["heading_at_beam_deg"] > 90.0          # 还没转到 110°
    assert any(s.truncated for s in out["segments"])
    assert "没转完" in out["run"].note


def test_run_traj_drops_the_crank_leg_when_the_warning_comes_too_early(tmp_path):
    out = workflow.run_traj(req_50km(t_crank=40.0, t_beam_s=T_BEAM, figure_dir=tmp_path,
                                     result_dir=tmp_path))
    phases = [leg.phase for leg in out["schedule"].legs]
    assert phases == ["beam"]                                   # crank 腿被丢弃
    assert out["anchor"]["completed"] is None                   # 谈不上转完
    assert out["anchor"]["heading_at_beam_deg"] == pytest.approx(180.0)
    assert [s.phase for s in out["segments"]][:1] == [""]        # 直飞 → 转入39 → 39保持
    assert [s.kind for s in out["segments"]] == ["straight", "turn", "hold"]


def test_run_traj_preview_never_touches_the_solver(tmp_path):
    t0 = time.perf_counter()
    out = workflow.run_traj(req_50km(preview=True, figure_dir=tmp_path,
                                     result_dir=tmp_path))
    assert time.perf_counter() - t0 < 5.0
    assert out["preview"] is True
    assert "shot" not in out                                    # 没有解算结果
    assert out["t_beam_s"] is None                              # 也没法知道开机时刻
    assert len(out["_paths"]["figures"]) == 1
    # 预览不含 39 腿（那正是要解算的量），且比正式工况短
    assert [leg.phase for leg in out["schedule"].legs] == ["crank"]


def test_run_traj_writes_tracks_segments_and_manifest(tmp_path):
    out = workflow.run_traj(req_50km(t_beam_s=T_BEAM, tag="art", formats=("png",),
                                     figure_dir=tmp_path, result_dir=tmp_path))
    assert set(out["_paths"]) == {"figures", "missile", "target", "segments", "manifest"}
    for key in ("figures", "missile", "target", "segments", "manifest"):
        for item in (out["_paths"][key] if isinstance(out["_paths"][key], list)
                     else [out["_paths"][key]]):
            assert Path(item).exists(), (key, item)
    missile_head = (tmp_path / "traj_art_missile.csv").read_text(
        encoding="utf-8").splitlines()[0]
    target_head = (tmp_path / "traj_art_target.csv").read_text(
        encoding="utf-8").splitlines()[0]
    seg_head = (tmp_path / "traj_art_segments.csv").read_text(
        encoding="utf-8").splitlines()[0]
    # 列契约：**两张表都以 `record` 里的元组为准**（P6 扩列后弹 22 列 / 目标 5 列）。
    # 直接写死字符串会在下次加列时悄悄过期，所以这里对"元组 → 表头"的映射本身做断言。
    from missile_sim import record
    assert missile_head == ",".join(record.TRAJ_MISSILE_COLUMNS), missile_head
    assert target_head == ",".join(record.TRAJ_TARGET_COLUMNS), target_head
    assert missile_head.split(",")[:8] == ["t_s", "x_m", "y_m", "z_m", "v_ms", "mass_kg",
                                          "thrust_N", "range_m"], "前 8 列是老口径，不许改"
    assert target_head.split(",")[:4] == ["t_s", "x_m", "y_m", "z_m"]
    assert "mach" in missile_head and "dist_flown_m" in missile_head, "P6 的内核列要真的落盘"
    assert seg_head.startswith("t0_s,t1_s,kind,label,phase,heading0_deg,heading1_deg")
    # 分段覆盖整段飞行：[0, t_end]
    segs = out["segments"]
    assert segs[0].t0_s == 0.0
    assert segs[-1].t1_s == pytest.approx(out["shot"].t_end)
    blob = json.loads((tmp_path / "traj_art.json").read_text(encoding="utf-8"))
    assert blob["figure"] == "traj" and blob["tag"] == "art"
    assert blob["run"]["anchor"]["t_beam_s"] == pytest.approx(T_BEAM)
    assert len(blob["run"]["segments"]) == len(segs)
    assert blob["request"]["react_delay_s"] == 1.0
    assert "Infinity" not in json.dumps(blob) and "NaN" not in json.dumps(blob)


def test_run_traj_flags_a_39_command_that_lands_after_the_first_pass_hit(tmp_path):
    """开机距离被人为调小 ⇒ 39 指令落在**第一遍命中之后**，必须当输出量报出来。

    这不是"目标做了 39 仍被击落"，而是"目标还没收到告警就已经死了"。
    以前是**静默出一张看起来正常的图**（`--traj-lock-m 100` ⇒ t_beam 60.58 s、
    t_react 61.58 s，而第一遍 60.76 s 就命中了）。现在 `anchor.react_after_pass1_hit`
    转成布尔量、脚注另起一行明写，供外壳/看图的人判读。
    """
    ok = workflow.run_traj(req_50km(tag="ok", figure_dir=tmp_path, result_dir=tmp_path))
    assert ok["anchor"]["react_after_pass1_hit"] is False       # 默认工况：39 早于命中

    out = workflow.run_traj(req_50km(lock_distance_m=100.0, tag="d9",
                                     figure_dir=tmp_path, result_dir=tmp_path))
    a = out["anchor"]
    assert a["lock_distance_m"] == pytest.approx(100.0)         # 用户指定值真的生效
    assert a["pass1_hit"] is True
    assert a["react_after_pass1_hit"] is True
    assert a["t_react_s"] > a["pass1_t_hit_s"]                  # 39 指令晚于命中
    # 图仍然出得来（不抛异常），但这条记录进了 manifest，事后可查
    blob = json.loads((tmp_path / "traj_d9.json").read_text(encoding="utf-8"))
    assert blob["run"]["anchor"]["react_after_pass1_hit"] is True


def test_printed_text_has_no_markdown_stars():
    """要**打印出去**的文本里不许出现 markdown 星号（D5 同族，本轮已中三次）。

    `figures._plain()` 只兜"出图"那一条路径；manifest（`anchor["mode"]`）、CLI help、
    WebUI 表单提示都没人兜 —— 星号会原样进 `results/*.json` 和网页上。
    ⚠ 这条扫描是**源头**判据：只要它绿，就不需要有人再去肉眼查产物里的星号。
    """
    from missile_sim import cli, traj, webui

    bad = []
    if "**" in traj.ANCHOR_MODE:
        bad.append(f"traj.ANCHOR_MODE = {traj.ANCHOR_MODE!r}")
    for group in (webui.PRIMARY_FIELDS, webui.ADV_FIELDS, webui.BG_FIELDS,
                  webui.TRAJ_FIELDS):
        for f in group:
            for attr in ("name", "label", "unit", "hint"):
                text = str(getattr(f, attr) or "")
                if "**" in text:
                    bad.append(f"webui.Field.{attr} = {text!r}")
    for line in cli.build_parser().format_help().splitlines():
        if "**" in line:
            bad.append(f"cli help: {line.strip()!r}")
    assert not bad, "要打印出去的文本里出现了 markdown 星号：\n" + "\n".join(bad)

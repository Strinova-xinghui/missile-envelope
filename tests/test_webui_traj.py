# -*- coding: utf-8 -*-
"""图4 在 WebUI 上的端到端验收：**真起 `http.server` + `http.client`**。

与 `test_webui_bg.py` 同款做法（不搭桩、只把产物目录指到 `.tmp_test/`），只测图4 那条新路：

* 表单里的 11 个 `traj_*` 字段必须真的渲染出来、真的**进 `TrajRequest`**
  （本仓库点名的坑是"显示了但不生效"），且都是 **Web 层专名** —— 少写一个
  `WEB_ONLY_KEYS`，`targets.build_scene()` 就会把正常提交判成非法输入（它硬报错）；
* `TRAJ_ALIASES`（外部名 → 字段名）与 `cli._TRAJ_ALIASES`（字段名 → 外部名）是同一张表，
  `TRAJ_DEFAULTS` 与 `TrajRequest` 的字段默认值逐个相等 —— 三条断言把"改了一边忘另一边"钉死；
* `figure=traj` 走 `run_traj()`：钉死 `traj_t_beam` 时跳过第一遍、真解算一遍；
  默认则在不含 39 腿的轨迹上反求开机时刻。
  ⚠ 2026-10-03：`traj_preview=1`（只出输入阶段 3D 预览、不解算）这条入口**已删**，
  随"图4 的静态 3D 图不出"一起走的 —— 见 `docs/UX-TARGET.md` §1；
* `figure` 的五个取值跑哪几张图，**必须与 CLI `--figure` 一一对应**（D10）：
  plane → 图1、bg → 图2、traj → 图4、both → 图1+图2、all → 图1+图2+图4。
  这里有个曾经的静默不一致：`both` 只跑图2 却把响应/摘要标成 `both`，而 CLI 的 `both` 是图1+图2；
  且它不在下拉里 —— 只能手工 POST 触达的"藏起来的坑"。现在两边对齐，`both` 也进了下拉；
* `figure=both` / `figure=all` 把多张图跑在**同一个**后台任务里，结果用 `parts` 分列，
  且 `parts` 里**每一份摘要都自带 `figure` 键**（D10：`summarize_plane()` 过去不写它，
  页面只能靠"缺省 = 图1"猜）。
"""

from __future__ import annotations

import http.client
import json
import math
import shutil
import sys
import time
import uuid
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import cli, figures, spec, webui  # noqa: E402
from missile_sim.workflow import TrajRequest  # noqa: E402

TMP = ROOT / ".tmp_test" / f"webui_traj_{uuid.uuid4().hex[:8]}"
PORT = 0                                     # 见 test_webui.py：固定端口在 Windows 上会假成功

#: 页面初始值（`traj_*` 全部显式写出来，**不从 `TRAJ_DEFAULTS` 派生** ——
#: 那样默认值改了测试也照样绿，"默认值真的被用上"就没人守了）。
DEFAULT_FORM = {
    "range_m": "50000", "alt_m": "10000", "vm0": "300",
    "launch_heading_deg": "0", "launch_pitch_deg": "0",
    "target_heading_deg": "180", "target_pitch_deg": "0",
    "target_speed_ms": "300", "target_alt_m": "",
    "target_bearing_deg": "0", "duration_s": "150",
    "standard": "PL-12", "tier": "fast", "jobs": "1", "tag": "w3",
    "figure": "traj",
    "traj_t_crank": "8", "traj_crank_deg": "70", "traj_crank_g": "9",
    "traj_beam_deg": "90", "traj_beam_g": "9", "traj_lock_m": "",
    "traj_react_delay": "1.0", "traj_weave": "", "traj_weave_amp": "4",
    "traj_weave_hz": "0.1", "traj_t_beam": "",
}

#: 图4 表单里**每一个**字段（= `TRAJ_FIELDS` 的名字，测试自己写一份当独立清单）。
TRAJ_FORM_NAMES = (
    "traj_t_crank", "traj_crank_deg", "traj_crank_g", "traj_beam_deg", "traj_beam_g",
    "traj_lock_m", "traj_react_delay", "traj_weave", "traj_weave_amp", "traj_weave_hz",
    "traj_t_beam",
)

#: 表单外部名 → `TrajRequest` 字段名（与 `webui.TRAJ_ALIASES` 比对的独立清单）。
TRAJ_EXPECTED = {
    "traj_t_crank": "t_crank", "traj_crank_deg": "crank_deg",
    "traj_crank_g": "crank_g", "traj_beam_deg": "beam_deg",
    "traj_beam_g": "beam_g", "traj_lock_m": "lock_distance_m",
    "traj_react_delay": "react_delay_s", "traj_weave": "weave",
    "traj_weave_amp": "weave_amp_deg", "traj_weave_hz": "weave_hz",
    "traj_t_beam": "t_beam_s",
}


def _config() -> dict:
    return {
        "host": "127.0.0.1", "port": PORT, "tier": "fast", "jobs": 1,
        "formats": ["png"], "cache": False,
        "figure_dir": str(TMP / "figures"), "result_dir": str(TMP / "results"),
        "tag": "w3", "poll_ms": 100,
    }


@pytest.fixture(scope="module")
def web():
    TMP.mkdir(parents=True, exist_ok=True)
    httpd = webui.serve("127.0.0.1", PORT, block=False, config=_config(), quiet=True)
    try:
        yield ("127.0.0.1", int(httpd.server_address[1]))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(TMP, ignore_errors=True)


def _get(addr, path):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type") or ""
    finally:
        conn.close()


def _post_json(addr, path, form):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=120)
    try:
        conn.request("POST", path, body=json.dumps(form, ensure_ascii=False).encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


def _poll(addr, job_id, timeout=600.0):
    t0 = time.time()
    seen = []
    while True:
        status, raw, _ = _get(addr, "/progress/" + job_id)
        assert status == 200, status
        snap = json.loads(raw.decode("utf-8"))
        seen.append((snap.get("state"), snap.get("done"), snap.get("total")))
        if snap.get("state") in ("done", "error"):
            return snap, seen
        assert time.time() - t0 < timeout, f"任务超时：{seen[-5:]}"
        time.sleep(0.2)


class _Job:
    """`run_traj_job()` 只要 `message` / `progress` / `log` 三样（不真起线程）。"""

    def __init__(self):
        self.message = ""
        self.logs = []

    def progress(self, *args):
        return None

    def log(self, message):
        self.logs.append(str(message))


class _FakeJobs:
    """`WebState.jobs` 的最小替身：只记下 `(kind, work)`，不真起线程、不真排队。"""

    def __init__(self):
        self.calls = []

    def submit(self, kind, work):
        self.calls.append((kind, work))
        return SimpleNamespace(id="fake-" + str(len(self.calls)), kind=kind)


# --------------------------------------------------------------------- 表单/单元


def test_page_exposes_the_trajectory_fields(web):
    """页面必须真的渲染出图4 的 11 个字段，且 `figure` 的选项含 traj / both / all。"""
    status, raw, ctype = _get(web, "/")
    assert status == 200 and "text/html" in ctype
    html = raw.decode("utf-8")
    for name in TRAJ_FORM_NAMES:
        assert f'data-field="{name}"' in html, f"页面缺少字段 {name}"
    for label in ("开始 crank 时刻", "crank 离轴角", "39 位离轴角", "导引头开机距离",
                  "反应延迟", "目标俯仰震荡"):
        assert label in html, f"页面缺少标签 {label!r}"
    # ⚠ 2026-10-03：`只出 3D 预览`（`traj_preview`）随"图4 的静态 3D 图不出"一起删了 ——
    # 这里反过来钉住"页面上再也没有这个入口"，免得哪天又冒出来。
    assert "只出 3D 预览" not in html and 'data-field="traj_preview"' not in html
    assert '<option value="traj"' in html and '<option value="all"' in html
    assert '<option value="both"' in html, "both 必须出现在下拉里（曾经它只能手工 POST 触达）"
    # 页面 JS 也得认得 both 的聚合分支，且不许把"缺省的 figure"当成图1。
    # ⚠ 2026-10-01 起这段 JS 搬到了静态资源 `webui_static/app.js`（不再内联在页面里）。
    app_js = webui.read_page_file("app.js")
    assert 'r.figure === "both"' in app_js and 'return "未识别的图："' in app_js
    for token in ("__TRAJROWS__", "__FIGUREROW__"):
        assert token not in html, f"模板占位符 {token} 没被替换掉"


def test_traj_fields_stay_out_of_the_scene():
    """`traj_*` 全是 Web/请求层专名：一个字都不许出现在 `Scene` 上。

    它们漏进 `targets.build_scene()` 的后果是**硬报错**（不是静默忽略），
    正常提交会被判成非法输入 —— 这就是 `WEB_ONLY_KEYS` 那条纪律。
    """
    scene, errors = webui.build_scene_from_form(dict(DEFAULT_FORM))
    assert errors == [], errors
    assert scene is not None and scene.range_m == 50000.0
    assert scene.maneuvers in (None, (), []), scene.maneuvers      # 图4 的运动由请求编译


def test_form_to_traj_request_accepts_the_page_defaults():
    """表单默认值必须解析成 `TrajRequest` 的默认值（留空 ≠ 0）。"""
    req, scene, errors = webui.form_to_traj_request(dict(DEFAULT_FORM), _config())
    assert errors == [], errors
    assert scene is not None and scene.range_m == 50000.0
    assert req.standard == "PL-12" and req.tier == "fast" and req.tag == "w3"
    assert req.t_crank == 8.0 and req.crank_deg == 70.0 and req.crank_g == 9.0
    assert req.beam_deg == 90.0 and req.beam_g == 9.0
    assert req.lock_distance_m is None            # 留空 ⇒ 用 blk 的 guidance.lockDistance
    assert req.react_delay_s == 1.0               # 留空 ⇒ **默认 1.0**，不是 0、不是 None
    assert req.weave is False and req.weave_amp_deg == 4.0 and req.weave_hz == 0.1
    assert req.t_beam_s is None


def test_every_traj_field_lands_on_the_request():
    """**"显示了但不生效"的钉子**：11 个字段各给一个非默认值，逐个在请求上验出来。"""
    assert {f.name for f in webui.TRAJ_FIELDS} == set(TRAJ_FORM_NAMES)
    assert webui.TRAJ_ALIASES == TRAJ_EXPECTED
    tr_fields = {f.name for f in fields(TrajRequest)}
    assert set(TRAJ_EXPECTED.values()) <= tr_fields, set(TRAJ_EXPECTED.values()) - tr_fields

    form = dict(DEFAULT_FORM, **{
        "traj_t_crank": "12.5", "traj_crank_deg": "60", "traj_crank_g": "7",
        "traj_beam_deg": "100", "traj_beam_g": "8.5", "traj_lock_m": "20000",
        "traj_react_delay": "2.5", "traj_weave": "1", "traj_weave_amp": "6",
        "traj_weave_hz": "0.2", "traj_t_beam": "30",
    })
    req, _scene, errors = webui.form_to_traj_request(form, _config())
    assert errors == [], errors
    assert req.t_crank == 12.5 and req.crank_deg == 60.0 and req.crank_g == 7.0
    assert req.beam_deg == 100.0 and req.beam_g == 8.5
    assert req.lock_distance_m == 20000.0
    assert req.react_delay_s == 2.5
    assert req.weave is True and req.weave_amp_deg == 6.0 and req.weave_hz == 0.2
    assert req.t_beam_s == 30.0


def test_traj_aliases_and_defaults_match_the_cli_and_the_request():
    """三张表（WebUI / CLI / `TrajRequest`）必须一致，且覆盖每个可配置字段。"""
    assert webui.TRAJ_ALIASES == {ext: fld for fld, ext in cli._TRAJ_ALIASES.items()}
    assert set(webui.TRAJ_DEFAULTS) == set(TRAJ_FORM_NAMES)

    proto = TrajRequest()
    for external, field in TRAJ_EXPECTED.items():
        mine = webui.TRAJ_DEFAULTS[external]
        if field in ("weave",):
            assert bool(mine) == bool(getattr(proto, field)), (external, mine)
        else:
            assert mine == getattr(proto, field), (external, mine, getattr(proto, field))

    # 图4 的表单字段 + 全局字段 + 走配置的路径字段 = `TrajRequest` 除 scene 外的全部字段。
    # ⚠ `env_preset` 是 v4 的**共享环境预设**字段（与 standard / tier / tag 同级），
    #   不进图4 的表单字段表，由预设下拉统一给。
    covered = set(TRAJ_EXPECTED.values()) | {"standard", "tier", "tag", "env_preset"}
    assert covered | {"formats", "figure_dir", "result_dir"} == set(cli._TRAJ_FIELDS)


def test_blank_optionals_become_none_but_the_rest_falls_back():
    """只有 `t_beam_s` / `lock_distance_m` 是可空字段；其余留空 = 默认值。"""
    form = dict(DEFAULT_FORM, traj_lock_m="", traj_t_beam="", traj_react_delay="",
                traj_crank_g="", traj_weave_amp="")
    req, _scene, errors = webui.form_to_traj_request(form, _config())
    assert errors == [], errors
    assert req.lock_distance_m is None and req.t_beam_s is None
    assert req.react_delay_s == 1.0 and req.crank_g == 9.0 and req.weave_amp_deg == 4.0

    # 配置里的值 < 表单里的值；两边都没有才用内置默认。
    cfg = dict(_config(), traj_react_delay=2.0, traj_crank_deg=50.0)
    req2, _s, errors2 = webui.form_to_traj_request(
        dict(DEFAULT_FORM, traj_react_delay="", traj_crank_deg=""), cfg)
    assert errors2 == [], errors2
    assert req2.react_delay_s == 2.0 and req2.crank_deg == 50.0
    req3, _s, errors3 = webui.form_to_traj_request(
        dict(DEFAULT_FORM, traj_react_delay="3.5", traj_crank_deg="55"), cfg)
    assert errors3 == [], errors3
    assert req3.react_delay_s == 3.5 and req3.crank_deg == 55.0


def test_form_to_traj_request_rejects_bad_values():
    """坏数字 / 越界角 / 池外弹名都要报出来（不能"显示了但不生效"）。"""
    _req, _scene, errors = webui.form_to_traj_request(
        dict(DEFAULT_FORM, traj_crank_g="别转"), _config())
    assert any("crank 转向过载" in e for e in errors), errors

    _req, _scene, errors = webui.form_to_traj_request(
        dict(DEFAULT_FORM, traj_crank_deg="0"), _config())
    assert any("离轴角" in e for e in errors), errors

    _req, _scene, errors = webui.form_to_traj_request(
        dict(DEFAULT_FORM, traj_react_delay="-1"), _config())
    assert any("反应延迟" in e for e in errors), errors

    _req, _scene, errors = webui.form_to_traj_request(
        dict(DEFAULT_FORM, standard="R-77X"), _config())
    assert errors, "弹名不在池里必须拦下"


def test_summarize_plane_carries_its_figure_key():
    """**D10 的钉子**：`summarize_plane()` 必须自带 `"figure": "plane"`。

    图1 的摘要是 `figure=both` 里 `parts` 的第一份。没有这个键，任何读
    `parts[i]["figure"]` 的人（页面 `partName()`、测试）就只能靠"缺省 = 图1"这种隐式知识 ——
    认错了也不报错，正是本仓库反复踩的那类坑。

    ⚠ `tests/test_webui_bg.py::test_webui_still_serves_figure_one_when_figure_is_plane`
    用 `r.get("figure") is None` 来分辨图1；补上这个键之后**那条断言必然失败**。
    该文件不在本任务的写范围（禁止改），已写进交付报告交回 Lead 处理。
    """
    req, _scene, errors = webui.form_to_request(dict(DEFAULT_FORM), _config(), with_iso=False)
    assert errors == [], errors
    out = {"_paths": {"figures": ["figures/fig_isotime_plane_w3.png"],
                      "manifest": "results/plane_w3.json"},
           "manifest": {}, "elapsed_s": 1.25, "backend": "python-legacy"}
    payload = webui.summarize_plane(out, req)
    assert payload["figure"] == "plane"
    assert payload["figure_urls"] == ["/figures/fig_isotime_plane_w3.png"]

    # 合并摘要里每一份都显式带 figure 键（不再出现 (None, True)）。
    merged = webui.summarize_all([payload, {"ok": True, "figure": "bg", "elapsed_s": 2.0}],
                                 figure="both")
    assert merged["figure"] == "both"
    assert [(p["figure"], p["ok"]) for p in merged["parts"]] == [("plane", True), ("bg", True)]
    assert merged["paths"]["plane_manifest"] == "results/plane_w3.json"
    assert merged["elapsed_s"] == 3.25

    # 兼容分支：万一哪份摘要真的漏了 figure 键，合并时补成显式 "plane"（而不是留空/None）。
    merged2 = webui.summarize_all([{"ok": True, "elapsed_s": 0.0}], figure="four")
    assert merged2["parts"][0]["figure"] == "plane"

    # 只服务 both / four：传单张图的名字属编程错误，不许"顺手支持一下"。
    # （`all` 已折成 `four`，不再进这里 —— 见 test_four_blocks.test_figure_all_is_an_alias_of_four。）
    with pytest.raises(ValueError):
        webui.summarize_all([], figure="bg")


def test_submit_job_figure_dispatch_matches_the_cli():
    """**D10 的钉子**：`figure` 五个取值跑哪几张图，必须与 CLI `--figure` 的 dispatch 一致。

    CLI：plane → 图1、bg → 图2、traj → 图4、fig3 → 图3、both → 图1+图2、
    four → 四块、all → four（别名，2026-10-03 裁决）。
    WebUI 曾经 `both` 只跑图2（返回 `figure: "bg"`），与 CLI 静默不一致。

    这里用替身 runner 记录**实际调用顺序**（不真解算、不真出图，毫秒级），
    顺带钉住"下拉里的每个 option 服务端都接受、白名单外一律 400"。
    """
    ran = []

    def _recorder(name):
        def run(req, job):
            ran.append(name)
            return {"ok": True, "figure": name, "with_iso": False, "elapsed_s": 0.1,
                    "figures": [f"figures/{name}.png"],
                    "figure_urls": [f"/figures/{name}.png"],
                    "paths": {"manifest": f"results/{name}.json"}}
        return run

    want = {"plane": ["plane"], "bg": ["bg"], "traj": ["traj"], "fig3": ["fig3"],
            "both": ["plane", "bg"]}
    # 下拉里留的是 `all`（别名，值不变、语义变），所以白名单 = want + {"all"}。
    assert set(webui.FIGURE_FIELD.options) == set(want) | {"all"}, "下拉必须与服务端白名单一模一样"

    saved = (webui.run_plane_job, webui.run_bg_job, webui.run_traj_job, webui.run_fig3_job)
    webui.run_plane_job, webui.run_bg_job, webui.run_traj_job, webui.run_fig3_job = (
        _recorder("plane"), _recorder("bg"), _recorder("traj"), _recorder("fig3"))
    try:
        for figure, expected in want.items():
            ran.clear()
            jobs = _FakeJobs()
            state = SimpleNamespace(config=_config(), jobs=jobs)
            payload, code = webui.submit_job(
                dict(DEFAULT_FORM, figure=figure, kind="plot"), state)
            assert code == 200 and payload["ok"] is True, (figure, payload)
            assert payload["figure"] == figure, (figure, payload)
            assert len(jobs.calls) == 1, (figure, jobs.calls)
            kind, work = jobs.calls[0]
            out = work(kind, _Job())
            assert ran == expected, (figure, ran)
            assert out["figure"] == figure, (figure, out["figure"])
            if figure == "both":
                assert [p["figure"] for p in out["parts"]] == expected, (figure, out["parts"])
                assert len(out["figure_urls"]) == len(expected), out["figure_urls"]
                assert sorted(out["paths"]) == sorted(f"{n}_manifest" for n in expected)
            else:
                assert "parts" not in out, (figure, out.keys())
    finally:
        webui.run_plane_job, webui.run_bg_job, webui.run_traj_job, webui.run_fig3_job = saved

    # `all` ≡ `four`（2026-10-03 裁决）：它**不再**是"图1+图2+图4"，而是**四块**那个任务。
    # 钉两件事：①真的走 `run_four_job`（替身，不真扫）；②回执里的 `figure` 是**生效值** `four`
    # （请求值 `all` 被别名表折掉），且不返回 `parts`（旧形态已消失）。
    for requested in ("all", "four"):
        jobs = _FakeJobs()
        state = SimpleNamespace(config=_config(), jobs=jobs)
        saved_four = webui.run_four_job
        webui.run_four_job = lambda reqs, job: {"ok": True, "figure": "four",
                                                "blocks_failed": [], "elapsed_s": 0.1}
        try:
            payload, code = webui.submit_job(dict(DEFAULT_FORM, figure=requested, kind="scan"), state)
            # ⚠ 必须在替身还在位时调用：写在 finally 之后会调到**真** run_four_job（真扫四块）。
            out = jobs.calls[0][1]("scan", _Job())
        finally:
            webui.run_four_job = saved_four
        assert code == 200 and payload["ok"] is True, (requested, payload)
        assert payload["figure"] == "four", (requested, payload)
        assert list(payload["blocks"]) == list(webui.BLOCK_ORDER), (requested, payload)
        assert out["figure"] == "four" and "parts" not in out, (requested, out.keys())


def test_summarize_traj_reports_a_miss_and_the_anchor_nodes():
    """正式工况的摘要：t_beam / 开机距离 / 反应延迟 / 开机时航向 / 转没转完 / 脱靶量。"""
    req = TrajRequest(tier="fast", react_delay_s=1.0, tag="w3")
    shot = spec.Shot(ok=True, hit=False, min_separation_m=123.456, cpa_m=123.456,
                     fuse_radius_m=10.0, t_end=60.0, backend="python-legacy")
    anchor = {"mode": "一遍法", "t_beam_s": 30.0, "range_at_beam_m": 15999.9,
              "completed": False, "heading_at_beam_deg": 140.0, "t_react_s": 31.0,
              "t_crank_turn_end_s": 40.0, "pass1_hit": True, "pass1_t_hit_s": 60.5}
    out = {"shot": shot, "anchor": anchor, "segments": [object(), object(), object()],
           "standard": None, "beta": 3078.06, "gamma": 56.63, "backend": "python-legacy",
           "lock_distance_m": 16000.0, "t_beam_s": 30.0, "t_react_s": 31.0,
           "elapsed_s": 1.5, "_paths": {"figures": []}}
    payload = webui.summarize_traj(out, req)
    # 未命中：脱靶量就是 min_separation_m（也是 cpa_m），两位小数
    assert payload["hit"] is False and payload["min_separation_m"] == 123.46
    assert payload["cpa_m"] == 123.456 and payload["fuse_radius_m"] == 10.0
    assert payload["t_hit_s"] is None                       # 未命中：不许给 0
    assert payload["t_beam_s"] == 30.0 and payload["lock_distance_m"] == 16000.0
    assert payload["react_delay_s"] == 1.0 and payload["t_react_s"] == 31.0
    assert payload["heading_at_beam_deg"] == 140.0
    assert payload["completed"] is False and "没转完" in payload["completed_text"]
    assert payload["n_segments"] == 3 and payload["beta"] == 3078.1
    assert payload["pass1_hit"] is True and payload["pass1_t_hit_s"] == 60.5
    assert "NaN" not in json.dumps(webui.jsonable(payload), ensure_ascii=False)

    # 命中：**不许**把引信半径 10 m 当脱靶量发出去（A5）；
    # `min_separation_m` 命中时折叠成 None，真精度走 `cpa_m`。
    hit_shot = spec.Shot(ok=True, hit=True, t_hit=69.172, min_separation_m=10.0,
                         cpa_m=0.0038, fuse_radius_m=10.0, t_end=69.2,
                         backend="compiled-c")
    out2 = dict(out, shot=hit_shot, anchor=dict(anchor, completed=True))
    p2 = webui.summarize_traj(out2, req)
    assert p2["hit"] is True and p2["t_hit_s"] == 69.172
    assert p2["cpa_m"] == 0.0038 and p2["fuse_radius_m"] == 10.0
    assert p2["min_separation_m"] is None, "命中时不许把引信半径当脱靶量发出去"
    assert p2["completed"] is True and p2["completed_text"] == "转完了"

    # 没量过 CPA（`want_cpa=False` 的缓存 / 老产物）：折成 None，不许编一个 0 出来。
    nan_shot = spec.Shot(ok=True, hit=True, t_hit=69.172, min_separation_m=10.0,
                         cpa_m=math.nan, fuse_radius_m=10.0, t_end=69.2)
    p3 = webui.summarize_traj(dict(out, shot=nan_shot), req)
    assert p3["cpa_m"] is None and p3["min_separation_m"] is None
    assert "NaN" not in json.dumps(webui.jsonable(p3), ensure_ascii=False)


# --------------------------------------------------------------------- HTTP 端到端


def test_webui_traj_pinned_t_beam_solves_and_reports_the_hit(web):
    """钉死 `traj_t_beam=34.46`：跳过第一遍、真解算一遍，摘要报出 t_beam 与命中。"""
    form = dict(DEFAULT_FORM, kind="plot", traj_t_beam="34.46")
    status, payload = _post_json(web, "/api/submit", form)
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["figure"] == "traj"
    snap, seen = _poll(web, payload["id"])
    assert snap["state"] == "done", (snap["state"], snap["error"], seen[-5:])
    r = snap["result"]
    assert r["t_beam_s"] == 34.46, r
    assert "用户指定" in r["anchor_mode"], r["anchor_mode"]
    assert r["hit"] is True, r
    assert r["t_hit_s"] and r["t_hit_s"] > 34.46, r["t_hit_s"]
    assert r["min_separation_m"] is None, "命中时不许把引信半径当脱靶量发出去（A5）"
    assert r["fuse_radius_m"] == 10.0, r["fuse_radius_m"]
    assert r["cpa_m"] is not None and r["cpa_m"] < 10.0, r["cpa_m"]
    assert r["lock_distance_m"] == 16000.0        # PL-12 的 blk guidance.lockDistance
    assert r["react_delay_s"] == 1.0 and r["t_react_s"] == 35.46
    assert r["completed"] is True and r["t_crank_turn_end_s"] is not None
    assert r["n_segments"] >= 3
    assert r["backend"], "backend 必须来自真跑过的 summary"
    assert (r["beta"], r["gamma"]) == (3078.1, 56.6)   # PL-12 的 β/γ（图2 现算）
    for key in ("missile", "target", "segments", "manifest"):
        assert Path(r["paths"][key]).is_file(), (key, r["paths"])
    # ⚠ 2026-10-03：静态轨迹成品图已删（用户口径 docs/UX-TARGET.md §2）—— 正式解算这一次
    # **不再出图**，轨迹只在沙盒（`/fig4?job=`）与 3D 查看器（`/viewer3d?job=`）里动态看。
    # 所以这里反过来钉住"没有图"：谁要是把 `plot_traj` 又接回 `run_traj()`，这条当场红。
    assert r["figure_urls"] == [] and r["figures"] == [], (r["figure_urls"], r["figures"])

    # ---- 3D 查看器：**同一个任务的产物**直接喂给查看器接口，不再解算 ----
    # 这是 e2e 的那一环：真跑出来的 traj_* 产物 → `/api/viewer3d/<id>`，
    # 期间 `solver.run` 不可能被调用（真解算的耗时是秒级，这里只是取数 + 抽稀，毫秒级）。
    t0 = time.time()
    status, raw, ctype = _get(web, f"/api/viewer3d/{payload['id']}")
    assert status == 200 and "application/json" in ctype, (status, raw[:300])
    d = json.loads(raw.decode("utf-8"))
    assert d["ok"] is True and d["job"] == payload["id"]
    assert d["points"] == {"requested": 800, "missile": 800, "target": 800}
    assert d["t_beam_s"] == 34.46 and d["t_hit_s"] == r["t_hit_s"]
    assert d["hit"] is True and d["missile_name"] == "PL-12"
    split = d["missile"]["split_index"]
    assert d["missile"]["t"][split - 1] < d["t_beam_s"] <= d["missile"]["t"][split]
    assert [s["color_key"] for s in d["segments"]] == ["grey", "orange", "red", "teal", "blue"]
    for s in d["segments"]:
        assert s["color"] == figures.TRAJ_COLORS[s["color_key"]], s
    assert [m["name"] for m in d["marks"]] == [
        "launch", "crank_start", "crank_done", "seeker_on", "beam_start", "end"]
    assert time.time() - t0 < 20.0, "查看器接口只是读产物 + 抽稀，不该秒级"

    status, body, _raw = _get(web, f"/api/viewer3d/{payload['id']}?points=1200")
    assert status == 200 and json.loads(body)["points"]["missile"] == 1200
    status, body, _raw = _get(web, f"/api/viewer3d/{payload['id']}?points=4001")
    assert status == 400, (status, body[:200])
    status, raw, ctype = _get(web, "/viewer3d?job=" + payload["id"])
    assert status == 200 and "text/html" in ctype and b"viewer3d.js" in raw


def test_webui_traj_default_form_reverses_the_beam_time(web):
    """默认表单（`traj_t_beam` 留空）走**一遍法反求**：t_beam ≈ 34.458 s。"""
    status, payload = _post_json(web, "/api/submit", dict(DEFAULT_FORM, kind="plot"))
    assert status == 200 and payload["ok"] is True, (status, payload)
    snap, seen = _poll(web, payload["id"])
    assert snap["state"] == "done", (snap["state"], snap["error"], seen[-5:])
    r = snap["result"]
    assert "一遍法" in r["anchor_mode"], r["anchor_mode"]
    assert r["t_beam_s"] is not None and 34.0 < r["t_beam_s"] < 34.9, r["t_beam_s"]
    assert r["range_at_beam_m"] is not None and r["range_at_beam_m"] <= 16000.0
    assert r["hit"] is True, r
    assert r["t_hit_s"] and 68.0 < r["t_hit_s"] < 70.5, r["t_hit_s"]
    assert r["pass1_hit"] is not None, "反求过第一遍，就该有第一遍的结局"


def test_webui_figure_all_is_the_four_block_job(web):
    """`figure=all` ≡ `figure=four`（2026-10-03 裁决）：一个后台任务出**四块**，不是"图1+图2+图4"。

    旧口径（本条判据的原文）把 `all` 写成"图1 + 图2 + 图4 + 按 parts 分列" —— 名字骗人：
    验收的人用 `all` 会以为四块都出了，实际少一块。现在 `all` 只是 `four` 的别名。

    走**真 HTTP**（submit → 轮询 → 回执），但用替身 runner 顶掉四块（不真扫 46 s / 60 s）：
    这里要钉的是**分派与台账形态**，真实四块端到端由 `-k four` 的替身判据 + 作者手工实测
    （61.6 s，见 C2 报告）覆盖。
    """
    def fake_four(reqs, job):
        for name in webui.BLOCK_ORDER:
            webui.set_block(job, name, state="done", error="", message="完成",
                            result={"figure": "traj" if name == "fig4" else "plane",
                                    "elapsed_s": 0.1})
        return {"ok": True, "figure": "four", "blocks_failed": [], "elapsed_s": 0.4}

    saved_four = webui.run_four_job
    webui.run_four_job = fake_four
    try:
        form = dict(DEFAULT_FORM, figure="all", kind="scan")
        status, payload = _post_json(web, "/api/submit", form)
        assert status == 200 and payload["ok"] is True, (status, payload)
        assert payload["figure"] == "four", "`all` 必须折成生效值 four"
        assert list(payload["blocks"]) == list(webui.BLOCK_ORDER), payload
        snap, seen = _poll(web, payload["id"])
    finally:
        webui.run_four_job = saved_four
    assert snap["state"] == "done", (snap["state"], snap["error"], seen[-5:])
    # 台账在 `/progress` 的**顶层** `blocks`（页面按 `r.blocks[k].result` 读）；
    # `result` 里是四块的合并摘要，**没有** `blocks` 键。
    blocks = snap["blocks"]
    assert sorted(blocks) == sorted(webui.BLOCK_ORDER), blocks
    assert all(blocks[k]["state"] == "done" for k in webui.BLOCK_ORDER), blocks
    r = snap["result"]
    assert r["figure"] == "four", r["figure"]
    assert "parts" not in r, "旧 `all` 的 parts 形态必须消失（别再有人按它写前端）"


def test_webui_figure_both_runs_the_two_cli_figures(web):
    """**D10 的端到端钉子**：`figure=both` = 图1 + 图2，与 CLI `--figure both` 一致。

    曾经这里只跑图2 却把响应标成 `both`（而 CLI 的 `both` 是图1+图2）—— 静默不一致。
    """
    form = dict(DEFAULT_FORM, figure="both", kind="plot",
                xlim="900,1200", ylim="3000,3300")
    status, payload = _post_json(web, "/api/submit", form)
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["figure"] == "both", "响应不许再把 both 说成别的"
    assert payload["with_iso"] is False
    snap, seen = _poll(web, payload["id"])
    assert snap["state"] == "done", (snap["state"], snap["error"], seen[-5:])
    r = snap["result"]
    assert r["figure"] == "both", r["figure"]            # 曾经这里是 "bg"
    assert [p["figure"] for p in r["parts"]] == ["plane", "bg"], r["parts"]
    assert len(r["figure_urls"]) == 2, r["figure_urls"]
    for prefix in ("plane_", "bg_"):
        assert any(k.startswith(prefix) for k in r["paths"]), (prefix, r["paths"])
    for url in r["figure_urls"]:
        status, raw, ctype = _get(web, url)
        assert status == 200 and "image/png" in ctype, url
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", url


def test_webui_traj_rejects_bad_input_before_queueing(web):
    """坏值 / 未知 figure 一律 400，且**不建任务**（`id` 不出现）。"""
    status, payload = _post_json(web, "/api/submit",
                                 dict(DEFAULT_FORM, kind="plot", traj_crank_deg="0"))
    assert status == 400 and payload["ok"] is False, (status, payload)
    assert any("离轴角" in e for e in payload["errors"]), payload
    assert "id" not in payload

    status, payload = _post_json(web, "/api/submit",
                                 dict(DEFAULT_FORM, figure="cube", kind="scan"))
    assert status == 400 and payload["ok"] is False, (status, payload)
    assert any("figure" in e for e in payload["errors"]), payload

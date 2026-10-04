# -*- coding: utf-8 -*-
"""图3 的 **Web 层**验收：路由 / 静态白名单 / 前端契约 / 真跑 JS。

python tests\\run_tests.py -k fig3 会一起跑本文件与 	ests\\test_fig3.py
（数据层、证据层、与 g3d 的数值一致性在那边）。这里的四段：

* **不解算**：solver.run 换成"一被调用就炸"的桩，数据层与 HTTP 两遍都得出来；
* **HTTP 层**（真起服务 + http.client）：/fig3 整页、/api/fig3/<tag|job> 的 JSON 与
  404/409/400 三种失败模式、静态白名单 fail-closed（含 .. 穿越）、首页内嵌 + 新标签页链接；
* **前端契约**：函数名 / 元素 id / localStorage 键 / 契约字符串，ig4.js 里**零颜色字面量**，
  拖动方向只有一处符号，要打印的文案没有 markdown 星号；
* **真跑 JS**（有 node 才跑）：共享色标、脱靶空心色、二次曲线与 Python 记录逐值一致、拖拽跟手。

⚠ 本文件**不跑求解器**：数据来自仓库自带的 
esults/fig3_default.*（已入库）。
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import fig3, figures, pool, solver, webui  # noqa: E402

#: 已入库的两份产物：默认 11 弹（2695 工况，100% 命中）与**全脱靶**小档。
PRODUCTS = fig3.default_paths("default")
#: 按需立方体的工况数（`--fig3-*` 默认网格 11×7×7）—— 只作契约断言。
CUBE_CASES = 539
N_MISSILES = 11
N_POINTS = 11


@pytest.fixture(scope="module")
def web4():
    """一个自己的服务（state 由本文件持有，方便塞假任务）。"""
    cfg = {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1,
           "formats": ["png"], "cache": False, "tag": "f4", "poll_ms": 100}
    state = webui.WebState(cfg, quiet=True)
    httpd = webui.make_server("127.0.0.1", 0, state=state, quiet=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield ("127.0.0.1", int(httpd.server_address[1])), state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(addr, path):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type") or ""
    finally:
        conn.close()


def _get_json(addr, path):
    status, raw, _ctype = _get(addr, path)
    return status, json.loads(raw.decode("utf-8")), raw


def _inject(state, *, state_name="done", result=None, error=""):
    job = state.jobs.create("scan")
    job.state = state_name
    job.error = error
    job.result = result
    return job.id


def _fig3_summary(tag="default", **over):
    body = {"ok": True, "figure": "fig3", "tag": tag, "paths": fig3.default_paths(tag)}
    body.update(over)
    return body


def _products_exist():
    return all(Path(p).is_file() for p in PRODUCTS.values())


pytestmark = pytest.mark.skipif(not _products_exist(),
                                reason="仓库自带的图3 产物缺失（--figure fig3 可重出）")




# ============================================================ 5. 不解算


def test_fig3_solver_run_is_never_called(web4):
    """接口**只读产物**：把 `solver.run` 换成"一被调用就炸"，数据照样出得来。"""
    addr, state = web4
    calls = []
    original = solver.run

    def boom(*args, **kwargs):                                   # pragma: no cover - 不该被调用
        calls.append((args, kwargs))
        raise AssertionError("图3 的数据层/接口不该调用 solver.run")

    solver.run = boom
    try:
        d = fig3.build(dict(PRODUCTS), job="demo")
        assert d["grid"]["n_cases"] == 539
        job = _inject(state, result=_fig3_summary())
        status, body, _raw = _get_json(addr, f"/api/fig3/{job}")
        assert status == 200 and body["grid"]["n_cases"] == 539
        status, body, _raw = _get_json(addr, "/api/fig3/default")
        assert status == 200 and len(body["points"]) == N_POINTS
        status, body, _raw = _get_json(addr, "/api/fig3/nope-nope")
        assert status == 404, (status, body)
    finally:
        solver.run = original
    assert calls == []
    assert solver.run is original


# ============================================================ 6. HTTP 层


def test_fig3_paths_of_picks_the_fig3_part():
    paths, _part = fig3.paths_of(_fig3_summary())
    assert paths["record"] == PRODUCTS["record"]
    merged = {"ok": True, "figure": "both", "parts": [
        {"figure": "plane", "paths": {"figures": ["a.png"]}},
        {"figure": "fig3", "tag": "default", "paths": dict(PRODUCTS)}]}
    paths, part = fig3.paths_of(merged)
    assert paths["cases"] == PRODUCTS["cases"] and part["figure"] == "fig3"
    for bad in ({"figure": "plane"}, {"figure": "both", "parts": [{"figure": "bg"}]}, {}):
        with pytest.raises(LookupError):
            fig3.paths_of(bad)


def test_fig3_parse_tag_and_default_paths():
    assert fig3.parse_tag(None) == "default"
    assert fig3.parse_tag("") == "default", "留空 = default（不是错误）"
    assert fig3.parse_tag("  ") == "default"
    assert fig3.parse_tag(" v1 ") == "v1"
    for bad in ("../etc", "a/b", "a\\b", "-lead", "x" * 41, "a b", ".hidden", "a;b"):
        with pytest.raises(ValueError):
            fig3.parse_tag(bad)
    p = fig3.default_paths("v1")
    assert p["record"].endswith(f"fig3_v1.json") and p["cases"].endswith("fig3_v1_cases.csv")
    with pytest.raises(FileNotFoundError):
        fig3.build({"record": PRODUCTS["record"]})                  # 缺 CSV
    with pytest.raises(FileNotFoundError):
        fig3.build({"record": str(ROOT / "results" / "nope.json"), "cases": PRODUCTS["cases"]})


def test_webui_fig3_http_route_json(web4):
    """`GET /api/fig3/<tag>`：200 + JSON 契约（含全脱靶那一档）。"""
    addr, state = web4
    status, body, raw = _get_json(addr, "/api/fig3/default")
    assert status == 200, body
    assert body["ok"] is True and body["figure"] == "fig3" and body["tag"] == "default"
    assert body["grid"]["shape"] == [11, 7, 7]
    assert len(body["points"]) == N_POINTS
    assert body["job"] is None and body["colors"] == fig3.palette()
    assert len(raw) < 300_000, f"响应 {len(raw)} 字节 —— 是不是又把立方体漏进来了？"
    assert [p["key"] for p in body["points"]] == list(pool.names())
    assert body["shared"]["n_hit"] == 7 and body["shared"]["n_miss"] == 4


def test_webui_fig3_http_route_accepts_a_job_id(web4):
    """`<id>` 是**跑完的图3 任务**时：用任务摘要里的产物路径（与 traj 查看器同形态）。"""
    addr, state = web4
    job = _inject(state, result=_fig3_summary("default"))
    status, body, _raw = _get_json(addr, f"/api/fig3/{job}")
    assert status == 200, body
    assert body["job"] == job and body["tag"] == "default"
    assert len(body["points"]) == N_POINTS


def test_webui_fig3_http_route_separates_the_failure_modes(web4):
    """404 / 409 / 400 各说各的话，别都折成一个 404。"""
    addr, state = web4
    status, body, _raw = _get_json(addr, "/api/fig3/nope-nope")
    assert status == 404 and body["ok"] is False
    assert "fig3" in body["errors"][0] and "--figure fig3" in body["errors"][0], body

    status, body, _raw = _get_json(addr, "/api/fig3/bad%2Ftag")
    assert status == 400 and "tag" in body["errors"][0], (status, body)

    queued = _inject(state, state_name="queued")
    status, body, _raw = _get_json(addr, f"/api/fig3/{queued}")
    assert status == 409 and "还没跑完" in body["errors"][0], (status, body)

    failed = _inject(state, state_name="error", error="求解器炸了")
    status, body, _raw = _get_json(addr, f"/api/fig3/{failed}")
    assert status == 409 and "求解器炸了" in body["errors"][0]

    plane = _inject(state, result={"ok": True, "figure": "plane", "paths": {"figures": ["x.png"]}})
    status, body, _raw = _get_json(addr, f"/api/fig3/{plane}")
    assert status == 404 and "没有图3" in body["errors"][0], (status, body)


def test_webui_fig3_http_route_page_and_static_assets(web4):
    """`/fig3` 是**独立路由**发的整页；CSS/JS 进白名单，HTML 不进（仍 fail-closed）。"""
    addr, state = web4
    status, raw, ctype = _get(addr, "/fig3?tag=default&bg=transparent&missile=R-77-1")
    assert status == 200 and "text/html" in ctype
    page = raw.decode("utf-8")
    assert page == webui.read_page_file("fig3.html"), "整页就该是磁盘上那份，不做二次渲染"
    assert "/static/fig3.css" in page and "/static/fig3.js" in page
    # ⚠ 2026-10-02（task-20 统一左栏）：从"只有 fig3.js 一个脚本"改成"app.js + fig3.js"。
    # 判据的本意没变 —— 只允许**本机**脚本，不许内联脚本 / CDN / 第三方资源；
    # `app.js` 是四页共用的左栏骨架（折叠 + localStorage + 预设 chip），图3 页也要它。
    assert page.count("<script") == 2, "图3 页面应当只有 app.js 与 fig3.js 两个脚本"
    assert '<script src="/static/app.js"></script>' in page, "少了共用的左栏骨架脚本"
    assert "<style>" not in page, "chrome 样式走 fig3.css"
    assert webui.TOKEN_RE.findall(page) == []
    assert "**" not in page, "页面文本里不许有 markdown 星号"

    for name, needle, ctype_needle in (("fig3.css", "#f7f8f9", "text/css"),
                                       ("fig3.js", "WebGL2", "javascript")):
        status, raw, got = _get(addr, f"/static/{name}")
        assert status == 200, (name, status)
        assert ctype_needle in got, (name, got)
        assert needle in raw.decode("utf-8"), name
        assert raw.decode("utf-8") == webui.read_page_file(name), name

    for path in ("/static/fig3.html", "/static/../webui.py", "/static/fig3.js.map",
                 "/static/fig3.py", "/static/..%2Ffig3.js"):
        status, raw, _c = _get(addr, path)
        assert status == 404, (path, status, raw[:120])
    assert "fig3.html" not in webui.WEB_STATIC_ASSETS
    assert set(webui.WEB_STATIC_ASSETS) >= {"fig3.css", "fig3.js"}


def test_webui_home_links_to_fig3_in_a_new_tab(web4):
    """首页：给「在新标签页打开」的链接 + 一页内嵌（与图3 查看器同形态）。"""
    addr, state = web4
    status, raw, _c = _get(addr, "/")
    assert status == 200
    page = raw.decode("utf-8")
    assert '<a href="/fig3" target="_blank" rel="noopener">' in page
    assert 'id="fig3frame"' in page and 'src="/fig3?bg=transparent"' in page
    assert 'loading="lazy"' in page, "内嵌那一页要懒加载，别让首页一进来就拉 200 KB"
    assert "fig3_beta_n" in page, "图3 的表单字段要渲染出来（否则'填了不生效'）"
    assert "**" not in page
    assert webui.TOKEN_RE.findall(page) == []


def test_webui_fig3_submit_flow(web4):
    """`figure=fig3` 的分流：字段解析 + 任务提交（不真跑扫描，只看响应与任务状态）。"""
    addr, state = web4
    req, scene, err = webui.form_to_fig3_request({"figure": "fig3", "range_m": 50000,
                                                  "fig3_beta_n": 3, "fig3_ginv_n": 3,
                                                  "fig3_dv_lim": "900,1300", "fig3_dv_n": 5,
                                                  "fig3_t_react": 33.0,
                                                  "fig3_dv": 900.0, "fig3_n": 25.0,
                                                  "fig3_alt": 8000.0, "tag": "web_unit_fig3"},
                                                 state.config)
    assert err == [] and req is not None and scene is not None
    assert (req.n_beta, req.n_ginv) == (3, 3)
    assert req.dv_lim == (900.0, 1300.0) and req.n_dv == 5
    assert req.dv_pin == 900.0 and req.t_react_s == 33.0
    assert req.n_ref == 25.0 and req.ref_alt_m == 8000.0
    assert req.missiles is None, "留空 = 全池（11 枚）"
    assert req.tag == "web_unit_fig3"
    # 想定字段复用图3 的 `traj_*`：表单里给了就要进 `Fig3Request`
    full = dict(webui.defaults_form(state.config))
    req2, _s, err2 = webui.form_to_fig3_request(
        dict(full, figure="fig3", traj_t_crank=5.0, traj_beam_deg=80.0), state.config)
    assert err2 == [] and req2.t_crank == 5.0 and req2.beam_deg == 80.0, err2
    bad, _s, bad_err = webui.form_to_fig3_request(
        {"figure": "fig3", "fig3_dv_lim": "900,abc"}, state.config)
    assert bad_err and any("区间" in e for e in bad_err), bad_err
    bad2, _s2, bad2_err = webui.form_to_fig3_request(
        {"figure": "fig3", "fig3_beta_n": 1}, state.config)
    assert bad2_err and any("BC 轴点数" in e for e in bad2_err), bad2_err
    bad3, _s3, bad3_err = webui.form_to_fig3_request(
        {"figure": "fig3", "fig3_dv_lim": "1300,900"}, state.config)
    assert bad3_err and any("递增" in e for e in bad3_err), bad3_err
    bad4, _s4, bad4_err = webui.form_to_fig3_request(
        {"figure": "fig3", "fig3_t_react": 0.0}, state.config)
    assert bad4_err and any("39 指令时刻" in e for e in bad4_err), bad4_err
    assert "fig3" in webui.FIGURE_FIELD.options
    assert webui.FIG3_DEFAULTS["fig3_beta_n"] == 7
    assert "fig3_beta_n" in webui.WEB_ONLY_KEYS and "fig3_alt" in webui.WEB_ONLY_KEYS


def test_webui_fig3_form_aliases_match_the_request_fields():
    """表单外部名 ↔ `Fig3Request` 字段名 ↔ CLI dest：三张表必须对得上。

    少一边的症状是"页面上填了但不生效"（或 CLI 上 `--fig3-dv` 悄悄改了图2 的钉值）。
    """
    from missile_sim import cli
    from missile_sim.workflow import Fig3Request
    fields = {f.name for f in __import__("dataclasses").fields(Fig3Request)}
    assert set(webui.FIG3_ALIASES.values()) <= fields
    dests = {a.dest for a in cli.build_parser()._actions}
    # `result_dir` 是**没有 CLI 选项**的字段（与 bg/traj 同款：测试/WebUI 才用得到它）
    no_flag = {"result_dir"}
    for name in webui.FIG3_ALIASES:
        assert name in dests, f"{name} 在 CLI 上没有 dest（参数写了不生效）"
    for canonical in cli._FIG3_EXTERNAL:
        if canonical in no_flag:
            continue
        assert canonical in dests, canonical
    # 别名**必须**把与图2 撞名的两个字段折走，否则两个 --bg-* 选项会串台
    assert cli._FIG3_ALIASES["dv_pin"] == "fig3_dv" != "dv_pin"
    assert cli._FIG3_ALIASES["n_ref"] == "fig3_n" != "n_ref"
    assert "fig3" in cli.build_parser().parse_args(["--figure", "fig3"]).figure
    # 每个 CLI 图3 选项的默认值都是 None（"没给就不覆盖 JSON"，见 cli 模块文档第 2 条）
    for action in cli.build_parser()._actions:
        if str(action.dest).startswith("fig3_") or action.dest in ("dv_lim", "n_dv"):
            assert action.default is None, (action.dest, action.default)


# ============================================================ 7. 前端契约


def _tiny_products(tag: str) -> dict:
    """写一份**小网格**的图3 标称产物（2×2×2 = 8 工况），供层路由的 202/200 用例用。

    ⚠ 用真 CLI 跑：这样"产物能驱动路由"这条是被端到端验过的；跑完由调用方删。
    """
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(ROOT / "src")})
    proc = subprocess.run(
        [sys.executable, "-m", "missile_sim", "--figure", "fig3", "--tag", tag,
         "--missiles", "PL-12", "--fig3-beta-n", "2", "--fig3-ginv-n", "2",
         "--fig3-dv-lim", "1100,1200", "--fig3-dv-n", "2", "--jobs", "1", "--quiet"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    return fig3.default_paths(tag)


def test_webui_fig3_layers_route_scans_on_demand_then_serves(web4):
    """**按需扫**：第一次 202（带 job/message/expected）→ 轮询 → 再打一次就是 200 + 13 档。

    同时钉两件事：① 连点两次**复用同一个 job**（不重复扫）；② 扫完缓存落盘，第二次是缓存命中。
    """
    addr, state = web4
    tag = "route_scan_t"
    paths = _tiny_products(tag)
    rec = fig3.read_record(paths["record"])
    # ⚠ 只删**本用例新建**的立方体缓存：早先的写法 `glob("fig3_cube_PL-12_*.json")` 会把
    #   仓库里那份预扫好的 PL-12 缓存一起删掉（Lead 2026-10-02 的验收里就是这么被打成 `M` 的）。
    cubes_before = {p.name for p in (ROOT / "results").glob("fig3_cube_*.json")}
    try:
        status, body, _raw = _get_json(addr, f"/api/fig3/{tag}/layers?missile=PL-12")
        assert status == 202 and body["scanning"] is True, (status, body)
        assert body["expected"]["cases"] == 8 and body["expected"]["tier"] == "fast", body
        assert "正在扫描" in body["message"] and body["poll"] == f"/progress/{body['job']}"
        status2, body2, _ = _get_json(addr, f"/api/fig3/{tag}/layers?missile=PL-12")
        assert status2 == 202 and body2["job"] == body["job"], "连点两次必须复用同一个 job"
        t0 = time.time()
        while True:
            _st, snap, _ = _get_json(addr, f"/progress/{body['job']}")
            if snap["state"] in ("done", "error"):
                break
            assert time.time() - t0 < 300, snap
            time.sleep(0.4)
        assert snap["state"] == "done", snap
        written = [p for p in (ROOT / "results").glob("fig3_cube_PL-12_*.json")
                   if p.name not in cubes_before]
        assert written, "扫完必须把立方体缓存写进 results/"
        status3, body3, _ = _get_json(addr, f"/api/fig3/{tag}/layers?missile=PL-12")
        assert status3 == 200, body3
        assert body3["missile"]["key"] == "PL-12"
        assert len(body3["surfaces"]) == body3["layers"]["n_levels"]
        assert body3["missile"]["cube_cache_hit"] is True
        # 4×4 的小立方体：只要求"契约自洽"（可出面的层数由数据决定）
        for s in body3["surfaces"]:
            assert s["ok"] is (s["reason"] == "")
            assert len(s["vertices"]) % 3 == 0 and len(s["triangles"]) % 3 == 0
        # 没点名 ⇒ 400；弹名不认识 ⇒ 404
        status4, body4, _ = _get_json(addr, f"/api/fig3/{tag}/layers")
        assert status4 == 400 and body4["ok"] is False
        status5, body5, _ = _get_json(addr, f"/api/fig3/{tag}/layers?missile=NOPE")
        assert status5 == 404 and body5["ok"] is False, (status5, body5)
    finally:
        created = [p for p in (ROOT / "results").glob("fig3_cube_*.json")
                   if p.name not in cubes_before]
        for p in list(paths.values()) + created:
            Path(p).unlink(missing_ok=True)


def test_webui_fig3_layers_route_never_solves(web4):
    """层路由与散点路由一样**只读产物**：`solver.run` 被换成"一调用就炸"的桩。"""
    addr, state = web4
    from missile_sim import solver as solver_mod

    def boom(*a, **k):
        raise AssertionError("层路由不该调用 solver.run")

    orig = solver_mod.run
    solver_mod.run = boom
    try:
        status, body, _raw = _get_json(addr, "/api/fig3/default/layers?missile=PL-12")
        if status == 202:                       # 立方体还没扫过：这条路只起任务，不该解算
            assert body["scanning"] is True and body["expected"]["cases"] == CUBE_CASES
        else:
            assert status == 200 and len(body["surfaces"]) == fig3.LAYER_COUNT
    finally:
        solver_mod.run = orig


def test_fig3_frontend_contract_names():
    """前端契约名齐全（函数 / 元素 id / `localStorage` 键 / 契约字符串）。"""
    js = webui.read_page_file("fig3.js")
    html = webui.read_page_file("fig3.html")
    for needle in ("function boot(", "function viewer(", "function cloudColors(",
                   "function colorDomain(", "function dataPos(",
                   "function surfaceBuffers(", "function buildBox(",
                   "function drawColorbar(", "function placeTicks(", "function applyDrag(",
                   "function projectToScreen(", "function loadState(", "function saveState(",
                   "function rampColor(", "function columnOf(", "function nodeOf(",
                   "function axisNorm(", "global.FIG3 = API", '"missile-sim.fig3"',
                   "getContext(\"webgl2\"", "FS_RING", "gl.POINTS",
                   "uniform1f(L_SOLID.alpha", "M4.persp", "gl.TRIANGLES",
                   "setLayer:", "layers?missile=", "layerbadge", "btnLayer", "layernote",
                   "function placeNames(", "pollJob", "SCAN_TIMEOUT_S", "d.points"):
        assert needle in js, needle
    # **删干净**：证据层那几条链路不许以任何形式回来
    for gone in ("fitCurves", "planeQuads", "drawHeatmap", "heatmode", "fitplane",
                 "fitcols", "heatmap", "render2dHeat", "d.heatmap"):
        assert gone not in js, f"前端还留着已删的证据层：{gone}"
        assert gone not in html, f"页面还留着已删的证据层：{gone}"
    for needle in ('id="cv"', 'id="hud"', 'id="bar"', 'id="missile"', 'id="layer"',
                   'id="layerLabel"', 'id="layerbadge"', 'id="btnLayer"', 'id="cbar"',
                   'id="btnReset"', 'id="btnSpin"', 'id="btnOpen"', 'id="scene"',
                   'id="layernote"', 'id="err"'):
        assert needle in html, needle
    for gone in ('id="hm"', 'id="mode"', 'id="heatmode"', 'id="fitplane"', 'id="fitcols"',
                 'id="induced"'):
        assert gone not in html, f"页面里还有已删的控件：{gone}"
    assert "missile-sim.fig3" in js and "missile-sim.fig3" not in webui.read_page_file("viewer3d.js")
    for ident in ("cv", "labels", "hud", "bar", "missile", "layer", "layerLabel",
                  "layerbadge", "btnLayer", "btnReset", "btnSpin", "btnOpen", "cbar",
                  "legend", "err", "title", "sub", "stat", "scene", "layernote"):
        assert f'id="{ident}"' in html, ident
    assert "<script src=\"/static/fig3.js\"></script>" in html
    assert "http://" not in js.lower() and "https://" not in js.lower()
    assert "cdn" not in js.lower() and "unpkg" not in js.lower() and "@import" not in html.lower()


def test_fig3_frontend_has_zero_color_literals_and_light_theme():
    """`fig3.js` 里**一个颜色字面量都没有**（数据配色全部来自响应）；chrome 的亮色在 CSS 里。"""
    js = webui.read_page_file("fig3.js")
    import re as _re
    hexes = _re.findall(r"#[0-9a-fA-F]{3,8}\b", js)
    assert hexes == [], f"fig3.js 里出现了颜色字面量：{sorted(set(hexes))[:8]}"
    # `rgb(...)` 只允许是**用数据拼字符串**（`rgbCss`），不允许写死数字
    assert _re.findall(r"rgba?\(\s*\d", js) == [], "JS 里不许有写死的 rgb() 颜色"
    assert "colors" in js and "needColor" in js and "needRamp" in js
    css = webui.read_page_file("fig3.css")
    for keep in ("#f7f8f9", "#1f2933", "#d8dce1"):
        assert keep in css, keep
    for dark in ("#0f1419", "#000000", "#1b1f23", "#111"):
        assert dark not in css, f"亮色主题里残留了深色 {dark}"
    # 页面侧星号判据：HTML/CSS 一个都不许有；JS 里只允许在注释里
    for name in ("fig3.html", "fig3.css", "fig3.js"):
        text = webui.read_page_file(name)
        for i, line in enumerate(text.splitlines(), start=1):
            if "**" not in line:
                continue
            if name.endswith(".js"):
                assert line.lstrip().startswith(("//", "*", "/*")), f"{name}:{i} 星号不在注释里"
            else:
                assert False, f"{name}:{i} 出现 markdown 星号：{line.strip()!r}"


def test_fig3_drag_sign_has_exactly_one_site():
    """拖动方向的符号只允许出现在一处（`applyDrag` 里那一行），与查看器同款判据。"""
    js = webui.read_page_file("fig3.js")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith(("//", "*", "/*")))
    assert code.count("cam.az += ") == 2, code.count("cam.az += ")
    assert "cam.az -=" not in code
    assert "cam.az += dx * AZ_PER_PX;" in code
    assert "cam.az += dt * 0.35;" in code
    move = code.split("pointermove", 1)[1].split("pointerup", 1)[0]
    assert "AZ_PER_PX" not in move and "applyDrag(cam, dx, dy)" in move


def test_fig3_cli_printed_text_has_no_markdown_stars():
    """要打印 / 要进产物的文案里不许有 markdown 星号（源头判据）。"""
    from missile_sim import cli
    bad = []
    for f in webui.FIG3_FIELDS:
        for attr in ("name", "label", "unit", "hint"):
            text = str(getattr(f, attr) or "")
            if "**" in text:
                bad.append(f"webui.Field.{attr} = {text!r}")
    for text in list(figures.FIG3_FOOTNOTES) + [figures.FIG3_LEGEND_HIT,
                                                figures.FIG3_LEGEND_MISS,
                                                figures.FIG3_LEGEND_INDUCED,
                                                figures.FIG3_TITLE]:
        if "**" in str(text):
            bad.append(f"figures: {text!r}")
    for m in figures.FIG3_MODES:
        for k, v in m.items():
            if "**" in str(v):
                bad.append(f"FIG3_MODES.{k} = {v!r}")
    for line in cli.build_parser().format_help().splitlines():
        if "**" in line:
            bad.append(f"cli help: {line.strip()!r}")
    assert not bad, "要打印出去的文本里出现了 markdown 星号：\n" + "\n".join(bad)


# ============================================================ 8. 真跑 JS（有 node 才跑）


def test_fig3_frontend_numbers_match_the_python_record(tmp_path):
    """真跑一遍 JS：11 个标称点的坐标/颜色、等时面缓冲、拖拽跟手。

    没有 node 就**跳过数值部分**（契约仍由上面那几条文本判据兜住）。
    """
    node = shutil.which("node")
    if not node:
        print("[fig3] 本机没有 node，跳过 JS 数值自检（文本判据仍在上面几条里）")
        return
    js = ROOT / "src" / "missile_sim" / "webui_static" / "fig3.js"
    check = subprocess.run([node, "--check", str(js)], capture_output=True, text=True,
                           timeout=120)
    assert check.returncode == 0, check.stderr[-2000:]

    payload = fig3.build(dict(PRODUCTS), tag="default")
    demo = tmp_path / "fig3.json"
    demo.write_text(json.dumps({"main": payload}, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "check.js"
    script.write_text(f"""
const F = require({json.dumps(str(js))});
const main = require({json.dumps(str(demo))}).main;
const out = {{}};
const cc = F.cloudColors(main, "PL-12", "t_hit");
out.n_hit = cc.hitIdx.length;
out.n_miss = cc.missIdx.length;
out.domain = cc.domain;
out.shared = main.shared.ranges.t_hit;
// 每个点都在归一化盒子里（说明坐标走的是同一条 dataPos 链路）
// ⚠ 只查**位置**：`cc.hit` 是 [x,y,z,r,g,b] 交错排的，颜色能到 1.0，混进来必然误判
const boxes = [];
for (let i = 0; i + 5 < cc.hit.length + 1; i += 6) boxes.push(cc.hit[i], cc.hit[i+1], cc.hit[i+2]);
for (let i = 0; i + 2 < cc.miss.length + 1; i += 3) boxes.push(cc.miss[i], cc.miss[i+1], cc.miss[i+2]);
out.inBox = boxes.length > 0 && boxes.every(v => v >= -0.5001 && v <= 0.5001);
// 11 个弹名：契约给全
out.names = main.labels.names.length;
out.first = main.points[0].key;
// 拖拽跟手：见证点取视轴近侧表面
const cam = {{az: F.AZ0, el: F.EL0, dist: 1.6, pan: [0, 0, 0]}};
const W = 1000, H = 700, center = [0, 0, 0], radius = 0.87;
const d = [Math.cos(F.EL0) * Math.cos(F.AZ0), Math.sin(F.EL0), Math.cos(F.EL0) * Math.sin(F.AZ0)];
const P = [d[0] * 0.2, d[1] * 0.2, d[2] * 0.2];
const s0 = F.projectToScreen(P, cam, center, radius, W, H, 0.9);
const c1 = {{az: cam.az, el: cam.el, dist: cam.dist, pan: [0, 0, 0]}};
F.applyDrag(c1, 200, 0);
const s1 = F.projectToScreen(P, c1, center, radius, W, H, 0.9);
const c2 = {{az: cam.az, el: cam.el, dist: cam.dist, pan: [0, 0, 0]}};
F.applyDrag(c2, -200, 0);
const s2 = F.projectToScreen(P, c2, center, radius, W, H, 0.9);
out.drag = {{plus: s1.x - s0.x, minus: s2.x - s0.x}};
// 等时面缓冲（喂一张合成网格，行/列与响应同构）
const spec = {{vertices: [0,0,0, 1,0,0, 0,1,0], triangles: [0,1,2]}};
const buf = F.surfaceBuffers(main, spec, [0.5, 0.5, 0.5]);
out.surf = {{pos: buf.pos.length / 3, idx: buf.idx.length}};
process.stdout.write(JSON.stringify(out));
""", encoding="utf-8")
    proc = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["n_hit"] == payload["shared"]["n_hit"] == 7
    assert out["n_miss"] == payload["shared"]["n_miss"] == 4
    assert out["domain"] == pytest.approx(payload["shared"]["ranges"]["t_hit"], abs=1e-9)
    assert out["shared"] == pytest.approx(out["domain"], abs=1e-9)
    assert out["inBox"] is True, "标称点跑出归一化盒子（坐标链路接错了）"
    assert out["names"] == N_POINTS and out["first"] == payload["points"][0]["key"]
    assert out["surf"]["pos"] == 3 and out["surf"]["idx"] == 3
    assert out["drag"]["plus"] > 0 and out["drag"]["minus"] < 0, out["drag"]
    assert out["drag"]["minus"] == pytest.approx(-out["drag"]["plus"], rel=1e-6)


def test_fig3_frontend_has_no_grid_cloud_leftovers():
    """前端也不许留格点云时代的残留（`clouds` / `n_star` / `R_ref` / `fitCurves` …）。"""
    js = webui.read_page_file("fig3.js")
    for gone in ("d.clouds", "n_star", "R_ref", "induced_dominated", "fitCurves",
                 "planeQuads", "drawHeatmap", "heatmap", "resid", "curv"):
        assert gone not in js, f"fig3.js 里还留着 {gone!r}"
    for needle in ("placeNames", "d.points", "pollJob", "expected", "SCAN_TIMEOUT_S"):
        assert needle in js, needle


def test_old_fig4_data_path_stays_compatible(web4):
    """别名（随下个破坏性版本删）：老 `/api/fig4/<id>` 与新 `/api/fig3/<id>` 逐字节一致。

    用户口径（docs/UX-TARGET.md §3）：三维页由 `/fig4` 改名 `/fig3`；**页面**老路径不再留别名
    （`/fig4` 现在是沙盒页），但**数据**老路径原样兼容 —— 前端与缓存里可能还存着它。
    """
    addr, _state = web4
    s_new, raw_new, _c = _get(addr, "/api/fig3/default")
    s_old, raw_old, _c2 = _get(addr, "/api/fig4/default")
    assert s_new == 200, (s_new, raw_new[:200])
    assert s_old == 200, (s_old, raw_old[:200])
    assert raw_old == raw_new

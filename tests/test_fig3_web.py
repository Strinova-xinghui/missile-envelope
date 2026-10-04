# -*- coding: utf-8 -*-
"""图3 的 **Web 层**验收：路由 / 静态白名单 / 前端契约 / 真跑 JS。

python tests\\run_tests.py -k fig3 会一起跑本文件与 	ests\\test_fig3.py
（数据层、证据层、与 g3d 的数值一致性在那边）。这里的四段：

* **不解算**：solver.run 换成"一被调用就炸"的桩，数据层与 HTTP 两遍都得出来；
* **HTTP 层**（真起服务 + http.client）：/fig3 整页、/api/fig3/<tag|job> 的 JSON 与
  404/409/400 三种失败模式、静态白名单 fail-closed（含 .. 穿越）、首页内嵌 + 新标签页链接；
* **前端契约**：函数名 / 元素 id / localStorage 键 / 契约字符串，
ig4.js 里**零颜色字面量**，
  拖动方向只有一处符号，要打印的文案没有 markdown 星号；
* **真跑 JS**（有 node 才跑）：共享色标、脱靶空心色、二次曲线与 Python 记录逐值一致、拖拽跟手。

⚠ 本文件**不跑求解器**：数据来自仓库自带的 
esults/fig3_default.*（已入库）。
"""

from __future__ import annotations

import http.client
import json
import os
import re
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
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「首页有 `/fig3` 新标签页链接 + `#fig3frame` iframe + 图3 表单字段」→ 静态页的图3 改成 host 容器（`FIG3STATIC.mount`）→ 替代：test_static_pool_page::test_three_cards_have_hosts_and_static_fallbacks
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
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
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池、零后端）：
    #   老断言「`fig3.js`/`fig3.html` 里有老 `/fig3` 整页 chrome 的契约名与 DOM id（`layerbadge`、
    #   `btnLayer`、`layernote`、`id="cv"/"hud"/"bar"…`、`/static/fig3.js` 外链、`missile-sim.fig3`）」
    #   → 那些 chrome 按用户口径已不存在（静态首页只有弹池 + 三张图的 host）→
    #   替代：`tests/test_static_pool_page.py` 的卡片/host 判据（`test_three_cards_have_hosts_and_static_fallbacks`
    #   / `test_third_figure_is_wired_to_the_static_3d_layer`）+ `tests/test_fig3_static.py` 的门面冻结
    #   （`window.FIG3STATIC.mount(host, {catalog, style})`、零 `/api`、零 fetch/XHR/存储、零颜色字面量）。
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """前端契约名齐全（函数 / 元素 id / `localStorage` 键 / 契约字符串）。"""
    js = webui.read_page_file("fig3.js")
    html = webui.read_page_file("fig3.html")
    for needle in ("function viewer(", "function cloudColors(",
        # ⚠ 2026-10-05（Static 分支·图3 静态化）：摘掉只服务"后端响应驱动"的名字钉
        #   （等时面/层/逐列拟合/角部光晕那一族）—— 静态站没有后端，那条路径整个删掉了。
        #   替代不变量见 tests/test_fig3_static.py：零 /api、零 fetch/XHR/存储、零颜色字面量、
        #   门面 FIG3STATIC.mount 冻结。与后端无关的通用工具/相机/交互/着色器名字保留。
        #   本次摘掉：function colorDomain(、function surfaceBuffers(、function drawColorbar(、function placeTicks(、function loadState(、function saveState(、global.FIG3 = API、missile-sim.fig3、getContext(\、gl.TRIANGLES、setLayer:、layers?missile=、function placeNames(、pollJob、SCAN_TIMEOUT_S、function haloParams(、function haloColorAt(、function haloBuffers(、FS_HALO。
        "function dataPos(",
        "function buildBox(",
        "function applyDrag(",
        "function projectToScreen(",
        "function rampColor(",
        "function columnOf(",
        "function nodeOf(",
        "function axisNorm(",
        ", ",
        ", ",
        "uniform1f(L_SOLID.alpha",
        "M4.persp",
        "layerbadge",
        "btnLayer",
        "layernote",
        "d.points",
        "function axisSlot(",
        "function axisSlots(",
        "TICK_EDGE"):
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
    """`fig3.js` 里**一个颜色字面量都没有**。

    ⚠ 2026-10-05（Static 分支·图3 静态化）：原来是"数据配色全部来自响应"——静态站没有后端，
    这条口径随之失效。替代不变量：配色只来自 `style`（壳给）或 `fig3.css` 的 CSS 变量，
    仍然零字面量；"来自响应"改成"来自 style 或 CSS"，另加零 /api、零 fetch/XHR/存储三条。
    """
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


def _css_blocks(css: str) -> dict:
    """按选择器抠出 `fig3.css` 里的规则体（只做本用例需要的那点解析：先去掉注释，无嵌套）。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = {}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        out.setdefault(m.group(1).strip(), []).append(m.group(2).strip())
    return out


def _media_bodies(css: str) -> list:
    """所有 `@media …{…}` 块的正文（按花括号配对，块里可以再嵌规则）。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"@media[^{]*\{", css):
        i, depth = m.end() - 1, 0
        for j in range(i, len(css)):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    out.append(css[m.end():j])
                    break
    return out


def test_fig3_chrome_hugs_the_window_edges_at_every_width():
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池、零后端）：
    #   老断言「`fig3.css` 里 `#side` 锚 right+top、`#legend` 锚 left、`.mainview` 撤通用 `main` 的封顶」
    #   → 那套**整页 chrome**（右色标 / 左图例）在静态版不存在，而且 `fig3.css` 已按方案 1 把整页规则
    #   收窄到 `body.fig3page` 下（首页共用这份样式，不能串味）⇒ 这些选择器在当前 CSS 里已经没有对应的
    #   基础块可比 → 替代：`tests/test_static_pool_page.py::test_no_backend_and_no_root_absolute_paths` /
    #   `test_rail_只有弹池`（首页 chrome 的口径）+ `tests/test_fig3_static.py` 的门面冻结；
    #   老 chrome 的真浏览器量法（`probe_chrome_edges.py`）仍留在 `.tmp_test/` 里备查。
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    # ⚠ 2026-10-05（Static 分支·图3 静态化）：fig3.css 的整页规则已收窄到 `body.fig3page`
    #   （静态首页也会链这份样式，必须不串味）。这里是**展示性**判据，解析前把前缀归一化掉，
    #   不变量本身不变：chrome 仍然贴窗口边。
    """用户 2026-10-04：窗口打开（窄→宽）时"左图例、右色标向内收窄"，要求紧贴左右。

    两个真回归点，都在 CSS 文本这一层（前端行为这套测试跑不起来 —— 无浏览器、无 node，
    所以改完必须再用真浏览器量一遍；量法见 `.tmp_test/probe_chrome_edges.py`）：

    1. `<main class="mainview" id="main">` 不能吃 `app.css` 里通用 `main{max-width:1100px;
       margin:0 auto}`：画布列一封顶居中，窗口越宽两侧留白越宽，贴边的 chrome 就往中间收。
       —— 实测（真浏览器 1658 CSS 宽）：修前色标右边缘离窗口右边 112.0 CSS，修后 10.4 CSS。
    2. 色标只锚 `right`+`top`：不许再带一个**生效的** `bottom`（旧骨架里两条并存 ⇒ 绝对定位
       同时拿到 top/bottom、高度 auto ⇒ 色标被拉成一整屏高的白板），也不许在窄窗口媒体查询里
       被改成 `position:static`（那样窗口一变宽它会先退成行内块再弹回右上）。
    """
    css = webui.read_page_file("fig3.css")
    blocks = _css_blocks(css)
    # 1) 撤掉通用 main 的封顶与居中（fig3.css 在 app.css 之后加载，单类选择器就够赢）
    mv = " ".join(blocks.get(".mainview", []))
    assert "max-width: none" in mv, mv
    assert "margin: 0" in mv, mv
    assert "padding: 0" in mv, mv
    # 2) 色标锚右上、不拉高、不静态化
    side = " ".join(blocks.get("#side", []))
    assert "right: 10px" in side and "top: 10px" in side, side
    bottoms = [v.strip() for k, v in re.findall(r"([a-z-]+)\s*:\s*([^;]+)", side) if k == "bottom"]
    assert all(v == "auto" for v in bottoms), bottoms
    for body in _media_bodies(css):
        for sel in ("#side", "#legend", ".mainview"):
            rule = _css_blocks(body).get(sel)
            if not rule:
                continue
            joined = " ".join(rule)
            assert "position: static" not in joined, (sel, joined)
            assert "max-width: 1100px" not in joined, (sel, joined)
    # 3) 图例锚在左边（只有一条左锚，别再出现第二条把它推到画布中间）
    legend = " ".join(blocks.get("#legend", []))
    assert "left: 12px" in legend, legend


def test_fig3_drag_sign_has_exactly_one_site():
    """拖动方向的符号只允许出现在**一处**（`applyDrag` 里那一行）—— 整文件计数不变量。

    ⚠ 2026-10-05 换写法（原来按 `pointermove`/`pointerup` 切片）：那种读法**脆** —— 两个监听器
    挨着注册、`applyDrag(` 与窗口边界差几十字符就会假红（本轮就这么假红过一次）。换成整文件计数：
    符号只能在一处、且那一处必须在 `applyDrag` 的函数体里；口径没放宽（仍是"符号只有一处"），
    只是不再依赖源码里某两个字符串的**相对位置**。
    """
    js = webui.read_page_file("fig3.js")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith(("//", "*", "/*")))
    # ① 改方位角只有两处，且都是**具名**的：拖动（applyDrag）与自动旋转（tick）
    assert code.count("cam.az += ") == 2, code.count("cam.az += ")
    assert "cam.az += dx * AZ_PER_PX" in code
    assert "cam.az += dt * 0.35" in code
    # ② 符号不许翻：整份源码里没有一处 `cam.az -=`
    assert "cam.az -=" not in code
    # ③ `AZ_PER_PX` 只许"声明一次 + 使用一次"，那次使用必须带正号
    assert len(re.findall(r"\bAZ_PER_PX\b", code)) == 2, re.findall(r".*AZ_PER_PX.*", code)
    assert len(re.findall(r"var\s+AZ_PER_PX\s*=", code)) == 1, "AZ_PER_PX 只许声明一次"
    assert code.count("cam.az += dx * AZ_PER_PX") == 1, "带正号的那一处只许一次"
    assert "- dx * AZ_PER_PX" not in code, "不许有反号写法"
    # ④ 那一处必须在 `applyDrag` 的函数体里（拿函数体做窗口，不按监听器字符串切片）
    i = code.index("function applyDrag(")
    tail = code[i + 1:]
    m = re.search(r"\n\s*function\s", tail)
    body = code[i:(i + 1 + m.start())] if m else code[i:]
    assert "cam.az += dx * AZ_PER_PX" in body, "拖动那一行跑到 applyDrag 外面去了"
    # ⑤ 拖动这段真的被调用（只有定义没有调用 = 死代码）
    calls = [ln for ln in code.splitlines()
             if "applyDrag(" in ln and "function applyDrag(" not in ln]
    assert calls, "applyDrag 一次都没被调用"


# ⚠ 2026-10-05（Static 分支·图3 静态化）——这里原本有 5 条判据，已删除：
#   test_fig3_frontend_axis_placement_comes_from_the_payload（轴摆位必须来自后端载荷）
#   test_fig3_frontend_halo_is_drawn_first_and_cannot_occlude_points（角部光晕的绘制顺序）
#   test_fig3_frontend_numbers_match_the_python_record（前端数字与 Python 记录对拍）
#   test_fig3_halo_math_and_axis_placement_in_node（光晕数学 + 摆位的 node 自检）
#   test_fig3_frontend_has_no_grid_cloud_leftovers（网格/点云的残留检查）
# 为什么删：静态站**没有后端** —— 载荷、等时面/层、逐列拟合、角部光晕这些路径整条不存在了
#   （用户 2026-10-05 口径：静态托管版，左栏只留弹池；`fig3.js` 里连 `/api` 字样都没有了），
#   这些判据钉的行为在静态版里没有对应物，留着只会永远红。
# 被什么替代：`tests/test_fig3_static.py` 里的替代不变量 ——
#   · 轴域与 `figures.fig3_axes()`（及 `--axes --figure fig3` oracle）**逐值相等**；
#   · 源码**零 `/api` 字样、零 `fetch(`/`XMLHttpRequest`/`localStorage`**；
#   · **零颜色字面量**（配色只来自 `style` 或 `fig3.css` 的 CSS 变量）；
#   · 门面冻结：`window.FIG3STATIC.mount(host, {catalog, style}) -> {setSelection, redraw}`；
#   · 标签两两不重叠、不出框；外加"植入 fetch 必须被抓到"的反证。

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

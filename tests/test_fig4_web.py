# -*- coding: utf-8 -*-
"""图4 的 **Web 层**验收：路由 / 静态白名单 / 前端契约 / 真跑 JS。

python tests\\run_tests.py -k fig4 会一起跑本文件与 	ests\\test_fig4.py
（数据层、证据层、与 g3d 的数值一致性在那边）。这里的四段：

* **不解算**：solver.run 换成"一被调用就炸"的桩，数据层与 HTTP 两遍都得出来；
* **HTTP 层**（真起服务 + http.client）：/fig4 整页、/api/fig4/<tag|job> 的 JSON 与
  404/409/400 三种失败模式、静态白名单 fail-closed（含 .. 穿越）、首页内嵌 + 新标签页链接；
* **前端契约**：函数名 / 元素 id / localStorage 键 / 契约字符串，ig4.js 里**零颜色字面量**，
  拖动方向只有一处符号，要打印的文案没有 markdown 星号；
* **真跑 JS**（有 node 才跑）：共享色标、脱靶空心色、二次曲线与 Python 记录逐值一致、拖拽跟手。

⚠ 本文件**不跑求解器**：数据来自仓库自带的 
esults/fig4_default.*（已入库）。
"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import fig4, figures, solver, webui  # noqa: E402

#: 已入库的两份产物：默认 11 弹（2695 工况，100% 命中）与**全脱靶**小档。
PRODUCTS = fig4.default_paths("default")
MISS_PRODUCTS = fig4.default_paths("miss")
N_MISSILES = 11
N_CASES_PER_MISSILE = 245


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


def _fig4_summary(tag="default", **over):
    body = {"ok": True, "figure": "fig4", "tag": tag, "paths": fig4.default_paths(tag)}
    body.update(over)
    return body


def _products_exist():
    return all(Path(p).is_file() for p in PRODUCTS.values())


pytestmark = pytest.mark.skipif(not _products_exist(),
                                reason="仓库自带的图4 产物缺失（--figure fig4 可重出）")




# ============================================================ 5. 不解算


def test_fig4_solver_run_is_never_called(web4):
    """接口**只读产物**：把 `solver.run` 换成"一被调用就炸"，数据照样出得来。"""
    addr, state = web4
    calls = []
    original = solver.run

    def boom(*args, **kwargs):                                   # pragma: no cover - 不该被调用
        calls.append((args, kwargs))
        raise AssertionError("图4 的数据层/接口不该调用 solver.run")

    solver.run = boom
    try:
        d = fig4.build(dict(PRODUCTS), job="demo")
        assert d["grid"]["n_cases"] == 245
        job = _inject(state, result=_fig4_summary())
        status, body, _raw = _get_json(addr, f"/api/fig4/{job}")
        assert status == 200 and body["grid"]["n_cases"] == 245
        status, body, _raw = _get_json(addr, "/api/fig4/default")
        assert status == 200 and len(body["clouds"]) == 11
        status, body, _raw = _get_json(addr, "/api/fig4/miss")
        assert status == 200 and body["shared"]["ranges"]["t_hit"] is None
    finally:
        solver.run = original
    assert calls == []
    assert solver.run is original


# ============================================================ 6. HTTP 层


def test_fig4_paths_of_picks_the_fig4_part():
    paths, _part = fig4.paths_of(_fig4_summary())
    assert paths["record"] == PRODUCTS["record"]
    merged = {"ok": True, "figure": "all", "parts": [
        {"figure": "plane", "paths": {"figures": ["a.png"]}},
        {"figure": "fig4", "tag": "default", "paths": dict(PRODUCTS)}]}
    paths, part = fig4.paths_of(merged)
    assert paths["cases"] == PRODUCTS["cases"] and part["figure"] == "fig4"
    for bad in ({"figure": "plane"}, {"figure": "all", "parts": [{"figure": "bg"}]}, {}):
        with pytest.raises(LookupError):
            fig4.paths_of(bad)


def test_fig4_parse_tag_and_default_paths():
    assert fig4.parse_tag(None) == "default"
    assert fig4.parse_tag("") == "default", "留空 = default（不是错误）"
    assert fig4.parse_tag("  ") == "default"
    assert fig4.parse_tag(" v1 ") == "v1"
    for bad in ("../etc", "a/b", "a\\b", "-lead", "x" * 41, "a b", ".hidden", "a;b"):
        with pytest.raises(ValueError):
            fig4.parse_tag(bad)
    p = fig4.default_paths("v1")
    assert p["record"].endswith(f"fig4_v1.json") and p["cases"].endswith("fig4_v1_cases.csv")
    with pytest.raises(FileNotFoundError):
        fig4.build({"record": PRODUCTS["record"]})                  # 缺 CSV
    with pytest.raises(FileNotFoundError):
        fig4.build({"record": str(ROOT / "results" / "nope.json"), "cases": PRODUCTS["cases"]})


def test_webui_fig4_http_route_json(web4):
    """`GET /api/fig4/<tag>`：200 + JSON 契约（含全脱靶那一档）。"""
    addr, state = web4
    status, body, raw = _get_json(addr, "/api/fig4/default")
    assert status == 200, body
    assert body["ok"] is True and body["figure"] == "fig4" and body["tag"] == "default"
    assert body["grid"]["shape"] == [5, 7, 7]
    assert len(body["clouds"]) == N_MISSILES
    assert body["job"] is None and body["colors"] == fig4.palette()
    assert len(raw) > 50_000, f"响应只有 {len(raw)} 字节 —— 是不是把点云漏了？"

    status, body, _raw = _get_json(addr, "/api/fig4/miss")
    assert status == 200 and body["tag"] == "miss"
    assert body["shared"]["ranges"]["t_hit"] is None


def test_webui_fig4_http_route_accepts_a_job_id(web4):
    """`<id>` 是**跑完的图4 任务**时：用任务摘要里的产物路径（与 traj 查看器同形态）。"""
    addr, state = web4
    job = _inject(state, result=_fig4_summary("miss"))
    status, body, _raw = _get_json(addr, f"/api/fig4/{job}")
    assert status == 200, body
    assert body["job"] == job and body["tag"] == "miss"


def test_webui_fig4_http_route_separates_the_failure_modes(web4):
    """404 / 409 / 400 各说各的话，别都折成一个 404。"""
    addr, state = web4
    status, body, _raw = _get_json(addr, "/api/fig4/nope-nope")
    assert status == 404 and body["ok"] is False
    assert "fig4" in body["errors"][0] and "--figure fig4" in body["errors"][0], body

    status, body, _raw = _get_json(addr, "/api/fig4/bad%2Ftag")
    assert status == 400 and "tag" in body["errors"][0], (status, body)

    queued = _inject(state, state_name="queued")
    status, body, _raw = _get_json(addr, f"/api/fig4/{queued}")
    assert status == 409 and "还没跑完" in body["errors"][0], (status, body)

    failed = _inject(state, state_name="error", error="求解器炸了")
    status, body, _raw = _get_json(addr, f"/api/fig4/{failed}")
    assert status == 409 and "求解器炸了" in body["errors"][0]

    plane = _inject(state, result={"ok": True, "figure": "plane", "paths": {"figures": ["x.png"]}})
    status, body, _raw = _get_json(addr, f"/api/fig4/{plane}")
    assert status == 404 and "没有图4" in body["errors"][0], (status, body)


def test_webui_fig4_http_route_page_and_static_assets(web4):
    """`/fig4` 是**独立路由**发的整页；CSS/JS 进白名单，HTML 不进（仍 fail-closed）。"""
    addr, state = web4
    status, raw, ctype = _get(addr, "/fig4?tag=default&bg=transparent&missile=R-77-1")
    assert status == 200 and "text/html" in ctype
    page = raw.decode("utf-8")
    assert page == webui.read_page_file("fig4.html"), "整页就该是磁盘上那份，不做二次渲染"
    assert "/static/fig4.css" in page and "/static/fig4.js" in page
    # ⚠ 2026-10-02（task-20 统一左栏）：从"只有 fig4.js 一个脚本"改成"app.js + fig4.js"。
    # 判据的本意没变 —— 只允许**本机**脚本，不许内联脚本 / CDN / 第三方资源；
    # `app.js` 是四页共用的左栏骨架（折叠 + localStorage + 预设 chip），图4 页也要它。
    assert page.count("<script") == 2, "图4 页面应当只有 app.js 与 fig4.js 两个脚本"
    assert '<script src="/static/app.js"></script>' in page, "少了共用的左栏骨架脚本"
    assert "<style>" not in page, "chrome 样式走 fig4.css"
    assert webui.TOKEN_RE.findall(page) == []
    assert "**" not in page, "页面文本里不许有 markdown 星号"

    for name, needle, ctype_needle in (("fig4.css", "#f7f8f9", "text/css"),
                                       ("fig4.js", "WebGL2", "javascript")):
        status, raw, got = _get(addr, f"/static/{name}")
        assert status == 200, (name, status)
        assert ctype_needle in got, (name, got)
        assert needle in raw.decode("utf-8"), name
        assert raw.decode("utf-8") == webui.read_page_file(name), name

    for path in ("/static/fig4.html", "/static/../webui.py", "/static/fig4.js.map",
                 "/static/fig4.py", "/static/..%2Ffig4.js"):
        status, raw, _c = _get(addr, path)
        assert status == 404, (path, status, raw[:120])
    assert "fig4.html" not in webui.WEB_STATIC_ASSETS
    assert set(webui.WEB_STATIC_ASSETS) >= {"fig4.css", "fig4.js"}


def test_webui_home_links_to_fig4_in_a_new_tab(web4):
    """首页：给「在新标签页打开」的链接 + 一页内嵌（与图3 查看器同形态）。"""
    addr, state = web4
    status, raw, _c = _get(addr, "/")
    assert status == 200
    page = raw.decode("utf-8")
    assert '<a href="/fig4" target="_blank" rel="noopener">' in page
    assert 'id="fig4frame"' in page and 'src="/fig4?bg=transparent"' in page
    assert 'loading="lazy"' in page, "内嵌那一页要懒加载，别让首页一进来就拉 200 KB"
    assert "fig4_beta_n" in page, "图4 的表单字段要渲染出来（否则'填了不生效'）"
    assert "**" not in page
    assert webui.TOKEN_RE.findall(page) == []


def test_webui_fig4_submit_flow(web4):
    """`figure=fig4` 的分流：字段解析 + 任务提交（不真跑扫描，只看响应与任务状态）。"""
    addr, state = web4
    req, scene, err = webui.form_to_fig4_request({"figure": "fig4", "range_m": 50000,
                                                  "fig4_beta_n": 3, "fig4_gamma_n": 3,
                                                  "fig4_dv_factors": "0.9,1.1",
                                                  "fig4_dv": 900.0, "fig4_n": 25.0,
                                                  "fig4_alt": 8000.0, "tag": "web_unit_fig4"},
                                                 state.config)
    assert err == [] and req is not None and scene is not None
    assert (req.n_beta, req.n_gamma) == (3, 3)
    assert req.dv_factors == (0.9, 1.1) and req.dv_pin == 900.0
    assert req.n_ref == 25.0 and req.ref_alt_m == 8000.0
    assert req.missiles is None, "留空 = 全池（11 枚）"
    assert req.tag == "web_unit_fig4"
    bad, _s, bad_err = webui.form_to_fig4_request(
        {"figure": "fig4", "fig4_dv_factors": "0.9,abc"}, state.config)
    assert bad_err and any("倍数" in e for e in bad_err), bad_err
    bad2, _s2, bad2_err = webui.form_to_fig4_request(
        {"figure": "fig4", "fig4_beta_n": 1}, state.config)
    assert bad2_err and any("β 轴点数" in e for e in bad2_err), bad2_err
    bad3, _s3, bad3_err = webui.form_to_fig4_request(
        {"figure": "fig4", "fig4_dv_factors": "1.0"}, state.config)
    assert bad3_err and any("至少" in e for e in bad3_err), bad3_err
    assert "fig4" in webui.FIGURE_FIELD.options
    assert webui.FIG4_DEFAULTS["fig4_beta_n"] == 7
    assert "fig4_beta_n" in webui.WEB_ONLY_KEYS and "fig4_alt" in webui.WEB_ONLY_KEYS


def test_webui_fig4_form_aliases_match_the_request_fields():
    """表单外部名 ↔ `Fig4Request` 字段名 ↔ CLI dest：三张表必须对得上。

    少一边的症状是"页面上填了但不生效"（或 CLI 上 `--fig4-dv` 悄悄改了图2 的钉值）。
    """
    from missile_sim import cli
    from missile_sim.workflow import Fig4Request
    fields = {f.name for f in __import__("dataclasses").fields(Fig4Request)}
    assert set(webui.FIG4_ALIASES.values()) <= fields
    dests = {a.dest for a in cli.build_parser()._actions}
    # `result_dir` 是**没有 CLI 选项**的字段（与 bg/traj 同款：测试/WebUI 才用得到它）
    no_flag = {"result_dir"}
    for name in webui.FIG4_ALIASES:
        assert name in dests, f"{name} 在 CLI 上没有 dest（参数写了不生效）"
    for canonical in cli._FIG4_EXTERNAL:
        if canonical in no_flag:
            continue
        assert canonical in dests, canonical
    # 别名**必须**把与图2 撞名的两个字段折走，否则两个 --bg-* 选项会串台
    assert cli._FIG4_ALIASES["dv_pin"] == "fig4_dv" != "dv_pin"
    assert cli._FIG4_ALIASES["n_ref"] == "fig4_n" != "n_ref"
    assert "fig4" in cli.build_parser().parse_args(["--figure", "fig4"]).figure
    # 每个 CLI 图4 选项的默认值都是 None（"没给就不覆盖 JSON"，见 cli 模块文档第 2 条）
    for action in cli.build_parser()._actions:
        if str(action.dest).startswith("fig4_") or action.dest == "dv_factors":
            assert action.default is None, (action.dest, action.default)


# ============================================================ 7. 前端契约


def test_fig4_frontend_contract_names():
    """前端契约名齐全（函数 / 元素 id / `localStorage` 键 / 契约字符串）。"""
    js = webui.read_page_file("fig4.js")
    html = webui.read_page_file("fig4.html")
    for needle in ("function boot(", "function viewer(", "function cloudColors(",
                   "function colorDomain(", "function fitCurves(", "function planeQuads(",
                   "function buildBox(", "function drawColorbar(", "function drawHeatmap(",
                   "function placeTicks(", "function applyDrag(", "function projectToScreen(",
                   "function loadState(", "function saveState(", "function rampColor(",
                   "function columnOf(", "function nodeOf(", "function axisNorm(",
                   "global.FIG4 = API", '"missile-sim.fig4"', "getContext(\"webgl2\"",
                   "FS_RING", "gl.POINTS", "uniform1f(L_SOLID.alpha", "M4.persp"):
        assert needle in js, needle
    assert "missile-sim.fig4" in js and "missile-sim.fig4" not in webui.read_page_file("viewer3d.js")
    for ident in ("cv", "labels", "hud", "bar", "missile", "mode", "heatmode", "fitplane",
                  "fitcols", "induced", "btnReset", "btnSpin", "btnOpen", "cbar", "hm",
                  "legend", "err", "title", "sub", "stat"):
        assert f'id="{ident}"' in html, ident
    assert "<script src=\"/static/fig4.js\"></script>" in html
    assert "http://" not in js.lower() and "https://" not in js.lower()
    assert "cdn" not in js.lower() and "unpkg" not in js.lower() and "@import" not in html.lower()


def test_fig4_frontend_has_zero_color_literals_and_light_theme():
    """`fig4.js` 里**一个颜色字面量都没有**（数据配色全部来自响应）；chrome 的亮色在 CSS 里。"""
    js = webui.read_page_file("fig4.js")
    import re as _re
    hexes = _re.findall(r"#[0-9a-fA-F]{3,8}\b", js)
    assert hexes == [], f"fig4.js 里出现了颜色字面量：{sorted(set(hexes))[:8]}"
    # `rgb(...)` 只允许是**用数据拼字符串**（`rgbCss`），不允许写死数字
    assert _re.findall(r"rgba?\(\s*\d", js) == [], "JS 里不许有写死的 rgb() 颜色"
    assert "colors" in js and "needColor" in js and "needRamp" in js
    css = webui.read_page_file("fig4.css")
    for keep in ("#f7f8f9", "#1f2933", "#d8dce1"):
        assert keep in css, keep
    for dark in ("#0f1419", "#000000", "#1b1f23", "#111"):
        assert dark not in css, f"亮色主题里残留了深色 {dark}"
    # 页面侧星号判据：HTML/CSS 一个都不许有；JS 里只允许在注释里
    for name in ("fig4.html", "fig4.css", "fig4.js"):
        text = webui.read_page_file(name)
        for i, line in enumerate(text.splitlines(), start=1):
            if "**" not in line:
                continue
            if name.endswith(".js"):
                assert line.lstrip().startswith(("//", "*", "/*")), f"{name}:{i} 星号不在注释里"
            else:
                assert False, f"{name}:{i} 出现 markdown 星号：{line.strip()!r}"


def test_fig4_drag_sign_has_exactly_one_site():
    """拖动方向的符号只允许出现在一处（`applyDrag` 里那一行），与查看器同款判据。"""
    js = webui.read_page_file("fig4.js")
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith(("//", "*", "/*")))
    assert code.count("cam.az += ") == 2, code.count("cam.az += ")
    assert "cam.az -=" not in code
    assert "cam.az += dx * AZ_PER_PX;" in code
    assert "cam.az += dt * 0.35;" in code
    move = code.split("pointermove", 1)[1].split("pointerup", 1)[0]
    assert "AZ_PER_PX" not in move and "applyDrag(cam, dx, dy)" in move


def test_fig4_cli_printed_text_has_no_markdown_stars():
    """要打印 / 要进产物的文案里不许有 markdown 星号（源头判据）。"""
    from missile_sim import cli
    bad = []
    for f in webui.FIG4_FIELDS:
        for attr in ("name", "label", "unit", "hint"):
            text = str(getattr(f, attr) or "")
            if "**" in text:
                bad.append(f"webui.Field.{attr} = {text!r}")
    for text in list(figures.FIG4_FOOTNOTES) + [figures.FIG4_LEGEND_HIT,
                                                figures.FIG4_LEGEND_MISS,
                                                figures.FIG4_LEGEND_INDUCED,
                                                figures.FIG4_TITLE]:
        if "**" in str(text):
            bad.append(f"figures: {text!r}")
    for m in figures.FIG4_MODES:
        for k, v in m.items():
            if "**" in str(v):
                bad.append(f"FIG4_MODES.{k} = {v!r}")
    for line in cli.build_parser().format_help().splitlines():
        if "**" in line:
            bad.append(f"cli help: {line.strip()!r}")
    assert not bad, "要打印出去的文本里出现了 markdown 星号：\n" + "\n".join(bad)


# ============================================================ 8. 真跑 JS（有 node 才跑）


def test_fig4_frontend_numbers_match_the_python_record(tmp_path):
    """真跑一遍 JS：共享色标、脱靶空心色、二次曲线逐值、拖拽跟手。

    没有 node 就**跳过数值部分**（契约仍由上面那几条文本判据兜住）。
    """
    node = shutil.which("node")
    if not node:
        print("[fig4] 本机没有 node，跳过 JS 数值自检（文本判据仍在上面几条里）")
        return
    js = ROOT / "src" / "missile_sim" / "webui_static" / "fig4.js"
    check = subprocess.run([node, "--check", str(js)], capture_output=True, text=True,
                           timeout=120)
    assert check.returncode == 0, check.stderr[-2000:]

    payload = fig4.build(dict(PRODUCTS), tag="default")
    miss_payload = fig4.build(dict(MISS_PRODUCTS), tag="miss")
    demo = tmp_path / "fig4.json"
    demo.write_text(json.dumps({"main": payload, "miss": miss_payload}, ensure_ascii=False),
                    encoding="utf-8")
    script = tmp_path / "check.js"
    script.write_text(f"""
const F = require({json.dumps(str(js))});
const d = require({json.dumps(str(demo))});
const main = d.main, miss = d.miss;
const out = {{}};
// ① 每枚弹每次都用**共享**色标域
const keys = main.missiles.map(m => m.key);
out.domains = {{}};
out.missAllowed = 0; out.missBad = 0;
for (const k of keys) {{
  for (const mode of ["t_hit", "resid", "curv"]) {{
    const cc = F.cloudColors(main, k, mode);
    out.domains[k + "|" + mode] = cc.domain;
  }}
  const cc = F.cloudColors(main, k, "t_hit");
  out["hitcount_" + k] = cc.hitIdx.length;
  out["misscount_" + k] = cc.missIdx.length;
}}
out.shared = main.shared.ranges;
// ② 脱靶点用 miss 色、且**从不**用 t_hit 色标里的颜色
const mcc = F.cloudColors(miss, "R-77", "t_hit");
const missRgb = F.hex2rgb(miss.colors.miss);
out.missColorOk = mcc.missColor.every((v, i) => Math.abs(v - missRgb[i]) < 1e-9);
out.missColorNotInRamp = !miss.colors.cmap.t_hit.includes(miss.colors.miss);
out.missAllPointsPlaced = mcc.miss.length === 3 * miss.clouds["R-77"].n;
out.missHasNoHitPoints = mcc.hitIdx.length === 0 && mcc.missIdx.length === miss.clouds["R-77"].n;
out.missDomainIsNull = (mcc.domain === null);
// ④ 逐列二次曲线：端点值 = a + b·ΔV + c·ΔV²
const curves = F.fitCurves(main, "PL-12", "quad");
const c0 = curves[0];
const cloud = main.clouds["PL-12"];
out.curve = {{n: curves.length, first: c0.pts[0][3], last: c0.pts[c0.pts.length - 1][3],
              a: cloud.intercept[0], b: cloud.slope[0], c: cloud.quad[0],
              dv0: main.grid.dv[0], dvN: main.grid.dv[main.grid.dv.length - 1]}};
out.expect = {{first: out.curve.a + out.curve.b * out.curve.dv0 + out.curve.c * out.curve.dv0 * out.curve.dv0,
               last: out.curve.a + out.curve.b * out.curve.dvN + out.curve.c * out.curve.dvN * out.curve.dvN}};
// ⑤ 拖拽跟手：见证点取**视轴近侧表面**（环绕相机绕 center 转，离轴远的点位移方向会反过来）
const cam = {{az: F.AZ0, el: F.EL0, dist: 1.6, pan: [0, 0, 0]}};
const W = 1000, H = 700, center = [0, 0, 0], radius = 0.87;
const dirv = [Math.cos(F.EL0) * Math.cos(F.AZ0), Math.sin(F.EL0), Math.cos(F.EL0) * Math.sin(F.AZ0)];
const P = [center[0] + dirv[0] * 0.2, center[1] + dirv[1] * 0.2, center[2] + dirv[2] * 0.2];
const s0 = F.projectToScreen(P, cam, center, radius, W, H, 0.9);
const c1 = {{az: cam.az, el: cam.el, dist: cam.dist, pan: [0, 0, 0]}};
F.applyDrag(c1, 200, 0);
const s1 = F.projectToScreen(P, c1, center, radius, W, H, 0.9);
const c2 = {{az: cam.az, el: cam.el, dist: cam.dist, pan: [0, 0, 0]}};
F.applyDrag(c2, -200, 0);
const s2 = F.projectToScreen(P, c2, center, radius, W, H, 0.9);
out.drag = {{plus: s1.x - s0.x, minus: s2.x - s0.x}};
out.ticks = F.buildBox(main).ticks.length;
process.stdout.write(JSON.stringify(out) + "\\n");
""", encoding="utf-8")
    proc = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    # ① 共享色标：11 枚弹 × 3 个模式，domain 必须与 payload 的共享范围逐值相同
    for k in (m["key"] for m in payload["missiles"]):
        assert out["hitcount_" + k] == payload["clouds"][k]["n"] - len(payload["clouds"][k]["miss_idx"])
        assert out["misscount_" + k] == len(payload["clouds"][k]["miss_idx"])
        for mode in ("t_hit", "resid", "curv"):
            dom = out["domains"][k + "|" + mode]
            want = out["shared"][mode]
            assert dom == [pytest.approx(want[0], abs=1e-9), pytest.approx(want[1], abs=1e-9)], \
                (k, mode, dom, want)
    assert out["domains"]["120A|t_hit"] == out["domains"]["R-77-1|t_hit"], "切弹不跳色标"

    # ② 脱靶：空心色，且一个点都不用 t_hit 色标
    assert out["missColorOk"] is True
    assert out["missColorNotInRamp"] is True
    assert out["missAllPointsPlaced"] is True
    assert out["missHasNoHitPoints"] is True
    assert out["missDomainIsNull"] is True

    # ④ 曲线端值与记录逐值一致（容差 1e-6 s，见 BETA3D_TOL_S 同一档口径）
    assert out["curve"]["n"] == 49
    assert out["curve"]["first"] == pytest.approx(out["expect"]["first"], abs=1e-6)
    assert out["curve"]["last"] == pytest.approx(out["expect"]["last"], abs=1e-6)

    # ⑤ 跟手：+200 px 拖拽 ⇒ 屏幕同向；镜像取负（两个方向的深度差只有 ~2e-6 px 量级）
    assert out["drag"]["plus"] > 0 and out["drag"]["minus"] < 0, out["drag"]
    assert abs(out["drag"]["plus"] + out["drag"]["minus"]) < 1e-3, out["drag"]
    assert 40.0 <= out["drag"]["plus"] <= 140.0, out["drag"]

    # 刻度数量 = 三根轴的点数之和
    assert out["ticks"] == sum(len(a["values"]) for a in payload["axes"])
    print("[fig4] 跟手自检：dx@+200 = %.2f px，dx@-200 = %.2f px；共享域 %s"
          % (out["drag"]["plus"], out["drag"]["minus"], out["shared"]["t_hit"]))


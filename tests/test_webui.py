# -*- coding: utf-8 -*-
"""`webui.py` 的端到端验收：**真起 `http.server`，用 `http.client` 打真实端口**。

原则：**不搭桩**。走的就是浏览器走的那条路（表单 → `targets`/`Scene` 校验 → `solver` /
后台任务 → `/progress` 轮询），只有产物目录指到 `.tmp_test/<id>/`，免得把交付物
`figures/` 与 `results/` 弄脏。

两点说明：

* `jobs=1` 时 `Engine` **根本不会创建进程池**（`engine.Engine._map` 走进程内分支），
  所以本文件测的是 HTTP + 任务链路，跑得快也可复现；进程池那条路由
  `test_webui_import_does_not_serve`（`__mp_main__` 复现）+ 手动验收（`jobs=8`）覆盖。
* `cache=False`：否则第二次跑同一张网格全是缓存命中，`Engine.many` 一次进度回调都不发，
  进度条就永远停在 0/0 —— 那是**测试的假象**，不是产品的行为。
"""

from __future__ import annotations

import http.client
import re
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import webui  # noqa: E402
from missile_sim.spec import Scene  # noqa: E402

#: ⚠ **不要用固定端口**。Windows 的 `SO_REUSEADDR` 允许第二个 socket 绑上同一个端口，
#: 所以"端口被占"**不会**抛 `OSError`：`serve()` 高高兴兴返回，可请求全进了那个旧进程。
#: 真踩过 —— 分发包的 `run_ui.py` 留着没关，它带着自己的 `cache: True` 与旧产物目录，
#: 4×4 网格全命中缓存，`Engine.many` 一次进度回调都不发，进度就永远停在 0/0，
#: 看起来像"扫描坏了"。交给系统分配端口，冲突概率为 0。
PORT = 0
TMP = ROOT / ".tmp_test" / f"webui_{uuid.uuid4().hex[:8]}"

#: 一张 **4×4 = 16 工况**的小网格：验收要求"把扫描网格缩到 4×4 以省时间"。
SMALL_GRID = {"xlim": "900,1200", "ylim": "3000,3300",
              "dv_step": "100", "bc_step": "100"}

DEFAULT_FORM = {
    "range_m": "50000", "alt_m": "10000", "vm0": "300",
    "launch_heading_deg": "0", "launch_pitch_deg": "0",
    "target_heading_deg": "180", "target_pitch_deg": "0",
    "target_speed_ms": "300", "target_alt_m": "",
    "target_bearing_deg": "0", "duration_s": "150",
    "standard": "PL-12", "tier": "fast", "jobs": "1",
    "dv_step": "10", "bc_step": "25", "iso_step": "1", "tag": "wtest",
}


def _config() -> dict:
    return {
        "host": "127.0.0.1", "port": PORT, "tier": "fast", "jobs": 1,
        "formats": ["png"],                 # 只出 PNG：PDF/SVG 对本用例没有新增信息
        "cache": False,                     # 见模块 docstring：缓存会把进度回调吃掉
        "figure_dir": str(TMP / "figures"), "result_dir": str(TMP / "results"),
        "tag": "wtest", "poll_ms": 100,
    }


@pytest.fixture(scope="module")
def web():
    """起一个真服务；无论成败，模块结束时一定关掉（`shutdown` + `server_close`）。"""
    TMP.mkdir(parents=True, exist_ok=True)
    cfg = _config()
    httpd = webui.serve("127.0.0.1", PORT, block=False, config=cfg, quiet=True)
    try:
        yield ("127.0.0.1", int(httpd.server_address[1]))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(TMP, ignore_errors=True)


# --------------------------------------------------------------------- HTTP 小工具


def _request(addr, method, path, body=None, ctype=None):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        headers = {}
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else body.encode("utf-8")
            if ctype:
                headers["Content-Type"] = ctype
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type") or ""
    finally:
        conn.close()


def _get_json(addr, path):
    status, raw, _ctype = _request(addr, "GET", path)
    return status, json.loads(raw.decode("utf-8"))


def _post_form(addr, path, form):
    """**表单编码**提交 —— 浏览器不跑 JS 时也是这条编码。"""
    return _request(addr, "POST", path, urlencode(form),
                    "application/x-www-form-urlencoded")


def _post_json(addr, path, form):
    """JSON 提交 —— 页面上 JS 用的那条编码。"""
    return _request(addr, "POST", path, json.dumps(form, ensure_ascii=False),
                    "application/json")


def _post_json_obj(addr, path, form):
    status, raw, _ctype = _post_json(addr, path, form)
    return status, json.loads(raw.decode("utf-8"))


def _poll(addr, job_id, timeout=300.0, interval=0.2):
    """轮询到 `done` / `error`；返回 `(最终快照, 见过的 (state, done, total) 序列)`。"""
    t0 = time.time()
    seen = []
    while True:
        status, snap = _get_json(addr, "/progress/" + job_id)
        assert status == 200, (status, snap)
        seen.append((snap.get("state"), snap.get("done"), snap.get("total")))
        if snap.get("state") in ("done", "error"):
            return snap, seen
        assert time.time() - t0 < timeout, f"任务超时，最近几次：{seen[-5:]}"
        time.sleep(interval)


# --------------------------------------------------------------------- 用例


def test_webui_index_200(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「`/` 页面里有『发射距离（米）』等表单标签」→ 表单首页已删 → 替代：test_static_pool_page::test_rail_只有弹池 / test_three_cards_have_hosts_and_static_fallbacks
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """首页 200 + 是 HTML + 主字段都在（用户要填的四项：高度 / 速度 / 距离 / 敌机状态）。"""
    status, raw, ctype = _request(web, "GET", "/")
    assert status == 200, status
    assert "text/html" in ctype, ctype
    html = raw.decode("utf-8")
    for needle in ("发射距离（米）", "载机初始高度", "载机初始速度", "敌机方向",
                   "敌机俯仰", "敌机速度", "敌机高度", "进度"):
        assert needle in html, f"首页缺少 {needle!r}"
    # 轮询路径现在写在**静态 JS** 里（拆分前它内联在页面里），所以换到 app.js 上验
    assert "/progress/" in webui.read_page_file("app.js"), "前端不再轮询 /progress/？"
    assert "__DEFAULTS__" not in html, "模板占位符没被替换掉"
    # 后端渲染出来的默认值必须真的进了页面（不是空的 JSON 占位）
    blob = html.split("var DEFAULTS = ", 1)[1].split(", PRESETS", 1)[0]
    assert float(json.loads(blob)["range_m"]) == 50000.0


def test_webui_rejects_bad_input(web):
    """非法输入在**提交求解器之前**被拦下，并把原因回显出来（不能 500，也不能静默跑）。"""
    cases = [
        ({"range_m": "-1000"}, ("range_m", "不能为负")),
        ({"duration_s": "0"}, ("duration_s", "必须为正")),
        ({"vm0": "abc"}, ("vm0", "数字")),
        ({"launch_pitch_deg": "120"}, ("launch_pitch_deg", "俯仰")),
    ]
    for patch, needles in cases:
        form = dict(DEFAULT_FORM)
        form.update(patch)
        status, payload = _post_json_obj(web, "/api/single", form)
        assert status == 400, (patch, status, payload)
        assert payload["ok"] is False, (patch, payload)
        text = "；".join(payload.get("errors") or [])
        assert text, f"{patch} 被拒了却没给原因"
        assert any(n in text for n in needles), (patch, text)

    # 弹名不在池里（`pool.PoolError`）与档位拼错：同样是 400 + 原因
    for patch in ({"standard": "R-77X"}, {"tier": "turbo"}):
        form = dict(DEFAULT_FORM)
        form.update(patch)
        status, payload = _post_json_obj(web, "/api/submit", dict(form, kind="scan"))
        assert status == 400, (patch, status, payload)
        assert payload.get("errors"), (patch, payload)


def test_webui_single_case_json(web):
    """单工况：同步返回 JSON，五个字段（t_hit / max_alt / 末速 / event / backend）都有。

    用**表单编码**提交，与浏览器不跑 JS 时同一条路。
    """
    status, raw, ctype = _post_form(web, "/api/single", DEFAULT_FORM)
    assert status == 200, (status, raw[:400])
    assert "application/json" in ctype, ctype
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True, payload
    shot = payload["shot"]
    assert shot["t_hit"] is not None and 40.0 < shot["t_hit"] < 50.0, shot["t_hit"]
    assert shot["max_alt_m"] is not None and shot["max_alt_m"] > 10000.0, shot["max_alt_m"]
    assert shot["v_impact"] is not None and shot["v_impact"] > 0.0
    assert shot["event"] in ("contact", "proximity_fuse"), shot["event"]
    assert shot["backend"], "backend 必须来自真跑过的 summary（不许按档位名猜）"
    assert payload["tier"] == "fast" and payload["missile"] == "PL-12"
    assert payload["scene_text"]
    # 非有限浮点必须是 null（否则 JS 的 JSON.parse 会炸）
    assert "NaN" not in raw.decode("utf-8") and "Infinity" not in raw.decode("utf-8")


def test_webui_scan_job_progress_to_100(web):
    """扫描：**提交立刻返回**（不阻塞），进度条一路走到 100%，产物图能取回来。"""
    form = dict(DEFAULT_FORM)
    form.update(SMALL_GRID)
    form["kind"] = "scan"
    t0 = time.perf_counter()
    status, payload = _post_json_obj(web, "/api/submit", form)
    submit_s = time.perf_counter() - t0
    assert status == 200 and payload["ok"] is True, (status, payload)
    job_id = payload["id"]
    assert payload["poll"] == f"/progress/{job_id}" and payload["with_iso"] is True
    assert submit_s < 20.0, f"提交就花了 {submit_s:.1f} s —— 扫描被同步阻塞了？"

    # 提交刚回来时任务必须还没跑完：出图要几秒，这就是"后台任务"的直接证据
    status, immediate = _get_json(web, "/progress/" + job_id)
    assert status == 200, status
    assert immediate["state"] in ("queued", "running"), immediate

    snap, seen = _poll(web, job_id)
    assert snap["state"] == "done", (snap["state"], snap["error"], seen[-5:])
    assert snap["percent"] == 100.0, snap
    assert snap["total"] == 16 and snap["done"] == 16, (snap["done"], snap["total"], seen)
    assert any(t == 16 for _s, _d, t in seen), f"进程里没见过 total=16 的进度：{seen}"

    result = snap["result"]
    assert result["with_iso"] is True
    assert result["n_cases"] == 16 and result["grid"]["n_cases"] == 16, result["grid"]
    assert 0 <= result["n_hit"] <= 16, result["n_hit"]
    assert result["backend"], "backend 必须来自真跑过的 summary"
    assert result["elapsed_s"] > 0.0
    assert result["figure_urls"], result

    # 图真的在那儿：从 HTTP 取回来，且是 PNG
    status, raw, ctype = _request(web, "GET", result["figure_urls"][0])
    assert status == 200 and "image/png" in ctype, (status, ctype)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 10_000, len(raw)
    # 产物落在配置指定的目录里（没污染交付物）
    assert (TMP / "figures").is_dir() and (TMP / "results").is_dir()


def test_webui_unknown_paths_404(web):
    """错误路径要**结构化报错**，不能让页面拿到一坨 HTML。"""
    status, payload = _get_json(web, "/progress/nosuchjob")
    assert status == 404 and payload["ok"] is False, (status, payload)
    status, payload = _get_json(web, "/healthz")
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["targets"] in (True, False)
    status, raw, _ctype = _request(web, "GET", "/figures/../../configs/web_default.json")
    assert status == 404, status            # 路径穿越必须在静态路由那里就断掉


class _no_targets:
    """上下文管理器：把 `webui` 的 targets 探测结果临时改成"没落盘"（用完还原）。

    直接改模块级缓存是有意为之 —— 兜底路径**只在** `targets.py` 缺席时才走得到，
    不这样临时把它的存在抹掉，那段代码就永远没人验。
    """

    def __enter__(self):
        self.saved = (webui._TARGETS, webui._TARGETS_TRIED)
        webui._TARGETS, webui._TARGETS_TRIED = None, True
        return self

    def __exit__(self, *exc):
        webui._TARGETS, webui._TARGETS_TRIED = self.saved
        return False


def test_webui_fallback_without_targets(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「没有 targets 时首页仍渲染出一份表单 + 提示」→ 表单首页已删 → 替代：test_static_pool_page::test_three_cards_have_hosts_and_static_fallbacks
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """A1 的 `targets.py` 不在时的**兜底薄封装**也要真的能用（否则它只是注释里的承诺）。

    兜底只做"字符串 → 数字"，领域校验退到 `Scene.check()` —— 所以非法输入**仍然**必须被拦下，
    只是少了 A1 那层的边界（高度域 / 俯仰域 / 步数规模），首页也要如实说明这一点。
    """
    with _no_targets():
        assert webui.targets_module() is None
        assert webui.targets_available() is False
        assert webui.presets_payload() == {}                 # 页面上就没有预置下拉
        assert webui.describe(Scene()) == Scene().describe()  # 退回 Scene.describe()

        _req, scene, errors = webui.form_to_request(dict(DEFAULT_FORM), _config())
        assert errors == [], errors
        assert scene is not None and scene.range_m == 50000.0
        # 自洽性校验（Scene.check）在兜底路径上仍然生效
        _req, _scene, errs = webui.form_to_request(dict(DEFAULT_FORM, range_m="-1000"),
                                                   _config())
        assert any("range_m" in e for e in errs), errs
        _req, _scene, errs = webui.form_to_request(dict(DEFAULT_FORM, vm0="abc"), _config())
        assert any("vm0" in e and "数字" in e for e in errs), errs
        # 首页要如实说明"领域校验缺位"，不能让人以为校验还是全的
        html = webui.render_page(webui.WebState(_config(), quiet=True))
        assert "targets.py 尚未落盘" in html

    # 退出上下文后一切恢复：A1 在时预置想定照旧有，描述也走 A1 的措辞
    assert webui.targets_available() is True
    assert len(webui.presets_payload()) >= 1


def test_webui_import_does_not_serve():
    """**技术雷 1 的回归用例**：import 期（含 spawn 子进程的 `__mp_main__` 那次）不许起服务。

    `runpy.run_module(..., run_name="__mp_main__")` 就是 `multiprocessing.spawn` 在子进程里
    重新执行主模块的方式：`__name__` 是 `__mp_main__`。若守卫被去掉，这次执行会**起一个
    真实服务器并永远阻塞** —— 子进程超时，这条用例就红。
    """
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
    code = (
        "import runpy, sys;"
        "runpy.run_module('missile_sim.webui', run_name='__mp_main__', alter_sys=True);"
        "sys.argv = ['webui'];"
        "import missile_sim.webui as w;"
        "assert w.SERVER_STARTS == 0, 'import 期起了服务';"
        "import threading;"
        "assert not [t for t in threading.enumerate() if t.name.startswith('missile-webui')];"
        "print('NO_SERVER_ON_IMPORT')"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=120, env=env, cwd=str(ROOT))
    assert proc.returncode == 0, (proc.returncode, proc.stdout[-800:], proc.stderr[-2000:])
    assert "NO_SERVER_ON_IMPORT" in proc.stdout, proc.stdout


# ------------------------------------------- 首页静态资源（2026-10-01 拆分，见 docs/WEBUI.md）
# 首页原来是 `webui.py` 里 440 行的 raw string；现在拆成
# `webui_static/{index.html,app.css,app.js}`：`index.html` 保留服务端占位符并内联 boot 数据，
# CSS / JS 是**纯静态**的，由 `GET /static/<name>` 直接发字节。这几条锁住"拆完还能用"与
# "边界没被放宽"。


def test_webui_serves_its_own_static_assets(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「app.js 里有 `function collect()`（表单收集器）」→ 静态页的 app.js 只服务弹池 → 替代：test_static_pool_page::test_data_comes_from_two_relative_json_files_only
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """`/static/app.css` 与 `/static/app.js` 按正确 content-type 发出，字节与磁盘完全一致。"""
    cases = (("app.css", "text/css", ":root{--bg:"),
             ("app.js", "javascript", "function collect()"))
    for name, ctype, needle in cases:
        status, raw, got = _request(web, "GET", f"/static/{name}")
        assert status == 200, (name, status)
        assert ctype in got, (name, got)
        assert needle in raw.decode("utf-8"), f"{name} 内容不对（找不到 {needle!r}）"
        assert raw == webui.read_page_file(name).encode("utf-8"), name


def test_webui_static_route_is_fail_closed(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「index.html 里必须有未渲染的 `__DEFAULTS__` 占位符」→ 静态页零占位符（组装契约①）→ 替代：test_static_pool_page::test_no_server_placeholders（服务端白名单那几条不受影响）
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """白名单之外一律 404：`index.html`（带未渲染的占位符）、路径穿越、瞎编的名字。

    ⚠ `viewer3d.html` 与 `sandbox.html` 也在这一串里：这两张整页各走**自己的路由**
    （`GET /viewer3d` / `GET /sandbox`），不进静态白名单（白名单只放 CSS/JS —— 页面数量变了
    也不用重新解释边界）。
    """
    for path in ("/static/index.html", "/static/viewer3d.html", "/static/sandbox.html",
                 "/static/nope.js", "/static/../webui.py", "/static/app.py"):
        status, raw, _ctype = _request(web, "GET", path)
        assert status == 404, (path, status, raw[:200])
    # 顺带确认 index.html **真的**带着占位符，否则这条用例是在防一个不存在的问题
    assert "__DEFAULTS__" in webui.read_page_file("index.html")


def test_webui_page_uses_external_assets_and_keeps_boot_data_inline(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「首页必须有唯一一处内联 boot 数据 `var DEFAULTS = …`」→ 静态页没有服务端注入 → 替代：test_static_pool_page::test_data_comes_from_two_relative_json_files_only
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """页面上不再有内联 `<style>`；CSS/JS 走外链；**boot 数据仍内联**（前端不用多打一次请求）。

    ⚠ 体积上限**不是文案配额**（2026-10-03 用户口径）：四块布局让 HTML 正当增长，为凑余量去删
    有用的话就是"代理指标绑架真实意图"。所以真意图由**结构性判据**承担 —— 内联 `<style>` 一个都不许有、
    带内容的 `<script>` 只许 boot 数据那一个；体积上限降级成防回内联的**粗筛**。
    """
    status, raw, ctype = _request(web, "GET", "/")
    assert status == 200
    assert "text/html" in ctype, ctype
    html = raw.decode("utf-8")
    # ---- 结构性判据（主）----
    assert "<style" not in html, "CSS 必须走 /static/app.css，不许内联 <style> 块"
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S)
    inline = [body for attrs, body in scripts if "src=" not in attrs and body.strip()]
    assert len(inline) == 1, f"带内容的内联 <script> 只许 boot 数据一处，现在 {len(inline)} 处"
    assert "var DEFAULTS = " in inline[0], "那唯一一处内联脚本只能是 boot 数据"
    # ---- 外链与占位符 ----
    assert "/static/app.css" in html and "/static/app.js" in html
    # ⚠ 外链脚本是**清单式**判据，不是"数数 == 2"：2026-10-04 阶段 B 加了静态层 `figs2d.js`
    # （客户端实时图），数数那种写法会把正当新增当回归。要守的是"每个外链都是白名单里的静态件、
    # 且没有多出来的内联脚本"（后者由上面 `inline == 1` 守）。
    srcs = sorted(re.findall(r'<script src="([^"]+)"', html))
    assert srcs == ["/static/app.js", "/static/figs2d.js"], srcs
    # boot 数据行原文是 `var DEFAULTS = …, PRESETS = …, META = …;`（只有 DEFAULTS 带 var）
    assert "var DEFAULTS = " in html and ", PRESETS = " in html and ", META = " in html
    assert webui.TOKEN_RE.findall(html) == [], "渲染完不该剩占位符"
    # ---- 松体积上限（副）：防回内联的粗筛，不是文案长度配额 ----
    # ⚠ 上限从 24_000 提到 27_000（2026-10-04 阶段 B）：两张卡片各多了 host 容器、形态切换条
    # 与三个下载链接，弹池那一段也在左栏 —— 是**结构性增长**，不是把 CSS/JS 塞回来（上面两条
    # 结构性判据才是真意图：没有内联 `<style>`、带内容的内联脚本只有 boot 那一处）。
    assert len(raw) < 27_000, f"页面 {len(raw)} 字节 —— 别把 CSS/JS 塞回内联"


def test_webui_app_js_has_no_server_side_placeholders():
    """静态 JS 里不许有服务端占位符 —— 它要是带占位符，`/static/app.js` 就等于把模板原样发出去。"""
    for name in sorted(webui.WEB_STATIC_ASSETS):
        body = webui.read_page_file(name)
        assert webui.TOKEN_RE.findall(body) == [], (name, webui.TOKEN_RE.findall(body))


def test_webui_read_page_file_rejects_traversal():
    """`read_page_file` 是这一层的地基：basename 化 + 只认 html/css/js + 不宽容修名字。"""
    for bad in ("../webui.py", "sub/app.js", "", "webui.py", "app.json", "app.css "):
        with pytest.raises(ValueError):
            webui.read_page_file(bad)
    with pytest.raises(FileNotFoundError):                     # 名字合法但文件不存在
        webui.read_page_file("missing.js")
    assert "index.html" not in webui.WEB_STATIC_ASSETS, "index.html 不能被直接发出去"


def test_webui_page_shows_no_markdown_stars(web):
    """浏览器看见的文本里不许有 markdown 星号（D5 同族）。

    ⚠ 这是**页面侧**的判据：`-k printed_text` 只看 Python 那侧的字符串（`Field.hint` / CLI help），
    页面里**手写**的静态提示它看不到 —— 2026-10-01 拆静态资源时就在 `index.html` 里抓到一处
    `**不解算**`，浏览器上原样显示星号。JS **注释**里的星号不算（`//` 之后不会渲染给用户）。
    """
    status, raw, _ctype = _request(web, "GET", "/")
    assert status == 200
    assert "**" not in raw.decode("utf-8"), "页面文本里出现了 markdown 星号"
    for i, line in enumerate(webui.read_page_file("app.js").splitlines(), start=1):
        if "**" in line:
            assert line.lstrip().startswith("//"), f"app.js:{i} 的星号不在注释里：{line.strip()!r}"


# ------------------------------------------- 输入体验：错误定位 + 记住上次输入（2026-10-01）


def test_webui_400_maps_errors_to_the_field(web):
    """非法输入的 400 里要带 `field_errors`（把消息归到**具体的框**上，前端据此标红）。

    `errors` 必须原样保留 —— 它是给人看的、也是既有调用方的契约，只**新增**不改动。
    两种非法输入都试：**非数字**走的是 `Scene` 解析那条路（消息里字段名在句子中间），
    **越界**走的是表单层 label 那条路 —— 这两条路的文案不一样，早年只测了后者就漏了前者。
    """
    for bad in ("abc", "-1000"):
        form = dict(DEFAULT_FORM)
        form.update({"range_m": bad})
        status, payload = _post_json_obj(web, "/api/single", form)
        assert status == 400 and payload["ok"] is False, (bad, status, payload)
        assert payload["errors"], payload
        assert payload["field_errors"].get("range_m"), (bad, payload["errors"],
                                                        payload.get("field_errors"))
        assert "alt_m" not in payload["field_errors"], "没出错的字段不该被牵连"


def test_webui_field_errors_only_claims_what_it_can_name():
    """`field_errors` 就是**文本匹配**：label 或字段名出现在消息里才归位，认不出就只留在 `errors`。

    三条规则都是实测逼出来的：长 label 优先（`敌机高度` 属于 `target_alt_m`）；
    字段名可能在句子中间（`想定解析失败：range_m 需要数字…` 是真·服务端消息）；
    字段名要做**词边界**匹配（`target_alt_m` 与 `alt_m` 互为子串，归错字段比不归更糟）。
    """
    fe = webui.field_errors
    assert list(fe(["载机初始高度 必须是数字，收到 'x'"])) == ["alt_m"]
    assert list(fe(["敌机高度 必须是数字，收到 'x'"])) == ["target_alt_m"]
    assert list(fe(['figure 只能是 plane / bg / traj / both / all，收到 "z"'])) == ["figure"]
    assert list(fe(["开始 crank 时刻 必须是数字，收到 'x'"])) == ["traj_t_crank"]
    assert list(fe(["想定解析失败：range_m 需要数字，收到 'abc'"])) == ["range_m"]     # 名字在句中
    assert list(fe(["target_alt_m 必须是数字，收到 'x'"])) == ["target_alt_m"]         # 词边界
    assert fe(["kind 只能是 scan / plot，收到 'z'"]) == {}
    assert fe([]) == {}
    one = "发射距离（水平）不能小于 0，收到 -1000.0"
    assert fe([one]) == {"range_m": [one]}                     # 一条消息只归一个字段


def test_webui_page_exposes_input_experience_hooks(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「『忘记上次输入』+ 手改上报钩子（`data-field`）」→ 表单首页已删 → 替代：test_static_pool_page::test_four_pool_actions_have_named_functions
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """输入体验的前端钩子（JS 不在这里跑，所以钉住契约名；真实行为靠浏览器实测）。

    实测记录（2026-10-01）：`field_errors` 的**真实**消息是 `想定解析失败：range_m 需要数字，收到 'abc'`
    （字段名在句中），而第一版规则只认"名字在开头" ⇒ 消息条有输出、**红框没有**。这说明
    "手编样例消息 → Python 测试全绿"完全不能替代真浏览器跑一遍（详见 `NOTES.md` §25）。
    """
    status, raw, _ctype = _request(web, "GET", "/")
    assert status == 200
    html = raw.decode("utf-8")
    assert 'id="forget"' in html, "页面上要有「忘记上次输入」"
    js = webui.read_page_file("app.js")
    for needle in ("function markFieldErrors", "function showFailure", "function restoreLocal",
                   "function clearFieldMarks", "localStorage.setItem", "missile-sim:form",
                   "clearFieldMarks();"):
        assert needle in js, f"app.js 缺少 {needle!r}"
    css = webui.read_page_file("app.css")
    for needle in ("input.bad", ".field-err"):
        assert needle in css, f"app.css 缺少 {needle!r}"


def test_webui_theme_is_light():
    """配色钉在**亮色**（用户 2026-10-01 定的产品要求，参考白底工程工具风）。

    这条不是"随便钉个字符串"：`color-scheme:light` 决定**表单控件/滚动条**也走亮色 ——
    只把背景刷白而漏了它，`<select>` 下拉和滚动条还是深色（很难看又难查）。
    """
    css = webui.read_page_file("app.css")
    assert "color-scheme:light" in css
    assert "--bg:#f5f6f8" in css and "--card:#ffffff" in css and "--fg:#1f2933" in css
    assert "--line:#d8dce1" in css
    assert "#0f1419" not in css, "旧的深色底不该还在 CSS 里"


def test_webui_home_shows_the_notes_that_moved_out_of_the_plots(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「`__FIG1NOTES__` 等占位符渲染出的服务端图注」→ 静态页图注改走 `./notes.json` → 替代：test_static_pool_page::test_notes_title_has_a_single_source + `-k static_site` 的图册图注
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """首页两张卡片要把"原先画在图里、现已移到页面"的批注**逐条**带上（用户 2026-10-04 口径）。

    与静态图册那半边（`sitebuild.figure_notes()`）同源同口径：文本只有一个出处 = `figures`，
    所以这条判据**现读现比** —— 期望值从 `figures` 与 `_static` 产物现算，不在这里抄任何一份副本。
    数字也现读（弹数、基准弹 ΔV），页面里更不许写死。

    图2 的**两份**（静态形态 = 没跑仿真层 / 计算版 = 跑过）都要在页面上：只有一份时，用户提交完
    页面换成计算版图，那句"本次未跑仿真层"就会挂在一张跑过仿真层的图上。哪一份显示由 `app.js`
    决定（它只切 hidden 或显示服务端给的 `figure_notes`，自己不拼文案）。
    """
    from html import escape as html_escape

    from missile_sim import figures
    from missile_sim.spec import RESULT_DIR

    status, raw, ctype = _request(web, "GET", "/")
    assert status == 200, status
    assert "text/html" in ctype, ctype
    page = raw.decode("utf-8")

    plane = json.loads((RESULT_DIR / "plane_static.json").read_text(encoding="utf-8"))
    bgp = json.loads((RESULT_DIR / "bg_static.json").read_text(encoding="utf-8"))
    std = str(plane.get("standard") or "")
    std_pt = next(p for p in plane["points"] if str(p.get("key")) == std)
    assert bgp.get("with_scan") is False, "首页贴的是 _static（没跑仿真层的那一套）"

    want = (list(figures.plane_notes(len(plane["points"])))
            + list(figures.BG_FOOTNOTES) + [figures.BG_READ_NOTE]
            + [figures.bg_scan_def(float(std_pt["dv"])), figures.bg_scan_note(False),
               figures.bg_scan_note(True)])
    for line in want:
        assert line in page or html_escape(line) in page, "首页少了图注：%s" % line[:36]

    assert page.count("图注（原先画在图里，现已移到页面）") == 2, "图1/图2 两块卡片各要有一个图注区块"
    assert 'class="notes notes-static"' in page and 'class="notes notes-scan"' in page, \
        "图2 要同时带静态与计算两份（否则没法跟着图换说法）"
    assert "<li>%s</li>" % html_escape(want[0]) in page, "图注要逐条落在 li 里"

    js = webui.read_page_file("app.js")
    assert "notes-scan" in js and "figure_notes" in js, "app.js 没接上图注切换契约"
    assert "BG_FOOTNOTES" not in js and "本次未跑仿真层" not in js, "文案不许抄进前端"


def test_webui_no_scan_bg_job_says_it_did_not_scan(web):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「app.js 按 `with_iso` 在静态/扫描两份图注间切」→ 静态页没有任务、只一份图注 → 替代：`-k static_site` 的静态图注用例 + test_static_pool_page 的图注单一出处
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """`kind=plot` + `figure=bg`（页面「只出图不扫描」那个按钮）这一跑，图注必须说"没跑仿真层"。

    用户 2026-10-04 的缺陷路径：页面上写着"本次已跑仿真层"，而图里根本没有等时线。
    定因结论：**服务端本来就是对的**（响应带 `figure_notes`、末行 = `bg_scan_note(False)`），
    错在前端挑错了要显示的那一份 ul（按"有结果图就切扫描版"，而不是按这一跑的 `with_iso`）。
    所以这条判据钉的是**"这一跑该给哪句话"**：服务端层面可测、也最该测的那一半。

    前端那一半（切 hidden）在 Python 侧跑不了，只钉契约名：`app.js` 必须按 `with_iso` 选一份。
    """
    from missile_sim import figures

    form = dict(DEFAULT_FORM)
    form.update({"kind": "plot", "figure": "bg"})        # 与 `#bp` 发出去的键一致
    status, payload = _post_json_obj(web, "/api/submit", form)
    assert status == 200 and payload["ok"] is True, (status, payload)
    jid = payload["id"]
    snap = {}
    for _ in range(1200):
        time.sleep(0.5)
        _status, snap = _get_json(web, "/progress/" + str(jid))
        if str(snap.get("state")) in ("done", "error"):
            break
    assert snap.get("state") == "done", snap
    res = snap.get("result") or {}
    assert res.get("figure") == "bg", res.get("figure")
    # 这一跑没扫：页面就靠这个布尔值挑那份图注，所以它必须为 False
    assert res.get("with_iso") is False, res.get("with_iso")
    notes = res.get("figure_notes") or []
    assert notes, "摘要里没带 figure_notes —— 页面只能挂预渲染的通用文案（就是那个缺陷）"
    assert notes[-1] == figures.bg_scan_note(False), notes[-1]
    assert notes[-1] != figures.bg_scan_note(True), "没扫却报'已跑仿真层'"
    # 前四段口径 + 读法段 + 仿真层说明也都在，且都来自 figures（不写副本）
    assert list(notes[:4]) == list(figures.BG_FOOTNOTES), notes[:4]
    assert notes[4] == figures.BG_READ_NOTE, notes[4]
    assert notes[5].startswith("仿真层：固定 ΔV="), notes[5]

    js = webui.read_page_file("app.js")
    assert "with_iso" in js and "ul.notes-static" in js and "ul.notes-scan" in js, \
        "app.js 必须按 with_iso 在静态/扫描两份图注之间切，而不是'有图就切'"
    assert 'notes-scan:not([hidden])' not in js, "又回到按可见性挑 ul 的老写法了（那正是本缺陷）"

# -*- coding: utf-8 -*-
"""阶段 B 前端壳：`GET /api/catalog` + 左栏对比弹池 + 挂载静态层（`figs2d`）。

三件事各有一条判据（`docs/STATIC-LAYER-REALTIME.md` §3 的"前端壳"行）：

* **目录送到页面**：真起服务 `GET /api/catalog`，字段齐、**逐值与磁盘上的
  `results/missile_catalog.json` 一致**（页面画的就是发布出去的那份坐标）；
* **弹池 UI**：首页两张卡片都有 host 容器、`_static` 回落 `<img>` 与三个下载链接**都还在**
  （`-k page_assets` 钉的是"首页不许靠删引用掩盖旧件"，这里钉"新形态别把它们挤掉"）；
* **零往返**：切弹池不许提出图请求 —— 扫 `app.js` 里"对比弹池"那一段源码；反证见
  `test_pool_network_checker_has_teeth`（往那一段塞一行 `post()` 必须被抓到）。

⚠ 前端**行为**这套测试跑不起来（无浏览器、无 node）：这里钉的是**契约与源码**。
真浏览器自验的步骤见 `docs/WEBUI.md` §12 与本次交付的说明。
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import catalog as catalog_mod  # noqa: E402
from missile_sim import webui  # noqa: E402

TMP = ROOT / ".tmp_test" / f"webui_pool_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def web():
    """起一个真服务。端口交给系统分配（固定端口在 Windows 上会被 `SO_REUSEADDR` 静默复用）。"""
    TMP.mkdir(parents=True, exist_ok=True)
    cfg = {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1, "formats": ["png"],
           "cache": False, "figure_dir": str(TMP / "figures"), "result_dir": str(TMP / "results"),
           "tag": "wpool", "poll_ms": 100}
    httpd = webui.serve("127.0.0.1", 0, block=False, config=cfg, quiet=True)
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


# ------------------------------------------------------------------ 目录（真起服务）


def test_api_catalog_serves_the_roster_the_page_draws_from(web):
    """`GET /api/catalog`：字段齐 + 与磁盘上的目录**逐值一致** + 11 弹/9 条置灰的口径。"""
    status, raw, ctype = _get(web, "/api/catalog")
    assert status == 200, status
    assert "json" in ctype, ctype
    got = json.loads(raw.decode("utf-8"))
    assert got["ok"] is True, got.get("errors")
    for key in ("schema", "count", "computable", "missiles", "unsupported", "reference", "style"):
        assert key in got, f"目录响应缺字段 {key}"
    disk = catalog_mod.load()
    assert got["missiles"] == disk["missiles"], "页面拿到的坐标与磁盘上的目录不一致"
    assert got["unsupported"] == disk["unsupported"]
    assert got["count"] == disk["count"] == len(disk["missiles"]) + len(disk["unsupported"])
    assert got["computable"] == len(disk["missiles"])
    pool = [m["key"] for m in got["missiles"] if m.get("in_pool11")]
    assert len(pool) == 11, pool
    assert len(got["unsupported"]) == 9, got["unsupported"]
    for u in got["unsupported"]:
        assert u.get("reason"), u                       # 面用户的原因（悬停显示）
        assert u.get("kernel_reason"), u                # 内核原话另存
    # 图面样式：坐标/颜色/字号只有一个出处 = figures；轴名已去掉 mathtext 的 `$`
    st = got["style"]
    for k in ("point_color", "base_color", "lbl_color", "point_r", "lbl_font",
              "nstar_levels", "xlabel", "ylabel", "xlabel_bg", "ylabel_bg"):
        assert st.get(k) not in (None, "", []), f"style 缺 {k}"
    assert "$" not in st["xlabel"] and "$" not in st["ylabel"]
    assert "$" not in st["xlabel_bg"] and "$" not in st["ylabel_bg"]
    # 基准弹（图上涂绿的那一枚）现读产物；产物在就必须与它一致，认不出就不该编
    prod = ROOT / "results" / "plane_static.json"
    if prod.is_file():
        want = json.loads(prod.read_text(encoding="utf-8")).get("standard")
        if want:
            assert got.get("standard") == want, (got.get("standard"), want)


def test_figs2d_assets_are_whitelisted_and_served(web):
    """静态层两个文件进白名单（fail-closed 白名单之外一律 404），按正确 content-type 发字节。"""
    assert set(webui.WEB_STATIC_ASSETS) >= {"figs2d.js", "figs2d.css"}
    for name, ctype, needle in (("figs2d.js", "javascript", "F.mount"),
                                ("figs2d.css", "text/css", ".figs2d")):
        status, raw, got = _get(web, f"/static/{name}")
        assert status == 200, (name, status)
        assert ctype in got, (name, got)
        assert needle in raw.decode("utf-8"), name
        assert raw == webui.read_page_file(name).encode("utf-8"), name


# ------------------------------------------------------------------ 首页 HTML


def test_home_page_has_the_live_hosts_and_keeps_the_static_fallback(web):
    """两张卡片：host 容器在、`_static` 回落 `<img>` 在、三个下载链接在、弹池控件在。"""
    status, raw, _ctype = _get(web, "/")
    assert status == 200
    html = raw.decode("utf-8")
    for host in ('class="figs2d-host" id="fig1host"', 'class="figs2d-host" id="fig2host"'):
        assert host in html, f"缺 host 容器：{host}"
    for img in ("/figures/fig_isotime_plane_static.png", "/figures/fig_bg_plane_static.png"):
        assert img in html, f"首页不再贴回落图 {img}（渐进增强的底）"
    for stem in ("fig_isotime_plane_static", "fig_bg_plane_static"):
        for ext in ("png", "pdf", "svg"):
            assert f"/figures/{stem}.{ext}" in html, f"缺下载链接 {stem}.{ext}"
    for el in ('id="poollist"', 'id="pool11"', 'id="poolAll"', 'id="poolClear"',
               'id="poolcount"', 'id="poolsearch"'):
        assert el in html, f"缺弹池控件 {el}"
    assert "/static/figs2d.js" in html and "/static/figs2d.css" in html
    # 渲染完不该剩占位符（新增容器不许把模板打断）
    assert webui.TOKEN_RE.findall(html) == [], webui.TOKEN_RE.findall(html)


def test_download_links_point_at_files_that_exist():
    """三个下载链接的目标必须真在 `figures/` 里（`-k page_assets` 的同一批件，这里只防手滑改名）。"""
    html = webui.read_page_file("index.html")
    for stem in ("fig_isotime_plane_static", "fig_bg_plane_static"):
        for ext in ("png", "pdf", "svg"):
            assert (ROOT / "figures" / f"{stem}.{ext}").is_file(), f"{stem}.{ext}"


# ------------------------------------------------------------------ 零往返（源码契约）

#: `app.js` 里"对比弹池"那一段的起始标记 —— 判据只扫这一段（别把整份文件的 `fetch` 算进来）。
POOL_MARK = "// ============================================================ 对比弹池"


def _pool_source(js: str) -> str:
    return js[js.index(POOL_MARK):]


def _code_only(text: str) -> str:
    """去掉整行 `//` 注释（口径与 `test_fig3_drag_sign_has_exactly_one_site` 同款）。

    ⚠ 这里必须先剥注释：那一段的**说明文字**里就会提到 `setSelection(keys)`，
    不剥就会把"解释"数成"调用点"。
    """
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("//"))


def _network_calls(text: str) -> list:
    """那一段源码里的**网络出口**。`GET /api/catalog`（读目录那一次）是唯一允许的。

    实现上先把"允许的那一次"换成占位符再扫 —— 免得给 `fetch(` 开后门把别的请求也放进来。
    """
    text = re.sub(r'\bfetch\s*\(\s*"/api/catalog"', "READ_CATALOG_ONLY", text)
    hits = []
    for pat in (r"\bfetch\s*\(", r"\bpost\s*\(", r"XMLHttpRequest",
                r"\.open\s*\(", r"/api/(?!catalog)"):
        hits.extend(m.group(0) for m in re.finditer(pat, text))
    return hits


def test_pool_switch_makes_no_plotting_request():
    """切弹池 = 纯客户端：那一段只许读一次 `/api/catalog`，不许提交任务、不许轮询进度。"""
    js = webui.read_page_file("app.js")
    seg = _pool_source(js)
    code = _code_only(seg)
    assert _network_calls(code) == [], f"切弹池那一段出现了网络出口：{_network_calls(code)}"
    assert 'fetch("/api/catalog"' in code, "目录就是靠这一次 GET 读来的"
    assert code.count(".setSelection(") == 1, "`setSelection` 只许一处调用点（池子变了就交给静态层）"
    for bad in ("/api/submit", "/api/single", "/progress/", "startPoll", "busy("):
        assert bad not in code, f"弹池那一段不该出现 {bad}"


def test_pool_network_checker_has_teeth():
    """反证：往那一段塞一行 `post()`，上面那条判据必须当场红（否则它是空的）。"""
    js = webui.read_page_file("app.js")
    code = _code_only(_pool_source(js))
    assert _network_calls(code) == []
    bad = code.replace("poolSet(poolDefault(), true);",
                       'post("/api/submit", collect()); poolSet(poolDefault(), true);', 1)
    assert bad != code, "反证没改到源码 —— 换一处锚点"
    assert _network_calls(bad), "塞了 post() 却抓不到：这条判据没有牙"


def test_pool_default_comes_from_the_catalog_not_a_hardcoded_roster():
    """默认选中的是**目录里 `in_pool11` 那些**；壳里不许写死 11 个弹名。"""
    js = webui.read_page_file("app.js")
    seg = _pool_source(js)
    assert "in_pool11" in seg, "默认选中必须来自目录"
    for name in ("PL-12", "PL-12A", "MICA", "Derby", "AAM-4", "R-Darter",
                 "R-77", "R-77-1", "120A", "120C", "120D"):
        assert f'"{name}"' not in seg, f"壳里写死了弹名 {name} —— 应该从目录取"
    assert 'POOL_KEY = "missile-sim:pool"' in js, "选择要存档（沿用 missile-sim:* 命名）"
    assert "localStorage.setItem(POOL_KEY" in seg and "localStorage.getItem(POOL_KEY" in seg


def test_pool_ui_greys_the_unsupported_and_hides_the_twins():
    """9 条不可算：列出但置灰 + 悬停给目录里的原因；`_default` 孪生默认不显示。"""
    seg = _pool_source(webui.read_page_file("app.js"))
    assert 'className = "pool-row off"' in seg, "不可算的要单独一个 off 行（figs2d.css 有它的样式）"
    assert "cb.disabled = true" in seg, "不可算的勾选框要禁用"
    assert "m.reason" in seg and "m.kernel_reason" in seg, "置灰原因要取目录里的字段"
    assert "!m.duplicate_of && !m.default_hidden" in seg, "孪生（_default）默认不进列表"


def test_live_view_never_hides_the_fallback_before_mount_succeeds():
    """渐进增强的顺序：**挂载成功前不许隐藏 `_static` 回落**（目录/渲染器缺一件就保持静态图）。"""
    seg = _pool_source(webui.read_page_file("app.js"))
    i = seg.index("function poolShow(")
    j = seg.index("function ", i + 10)
    body = seg[i:j]
    assert "if (!view) { return; }" in body, "没挂上就该原样返回"
    assert body.index("if (!view) { return; }") < body.index("st.hidden = true"), \
        "先把回落图藏了再判挂载 —— 渲染器缺失时首页就没图了"
    assert 'typeof F.mount !== "function"' in seg, "渲染器不存在那条路要有明确出口"


def test_pool_search_folds_dashes_and_underscores():
    """目录 key 是 `us_aim_120a` 这种下划线名，而用户会打 "aim-120" —— 搜索要折叠 `-`/`_`/空格。"""
    code = _code_only(_pool_source(webui.read_page_file("app.js")))
    assert "function poolFold(" in code, "折叠口径要独立出来（一处）"
    assert r"replace(/[\s_-]+/g" in code, "`-`/`_`/空白折成同一个东西"
    assert "row.hidden = !!q &&" in code, "过滤只切显不显示（不改选择）"


def test_live_view_notes_carry_the_title_the_layer_does_not_write():
    """静态层按冻结接口**一个字都不写**：实时形态那份图注的标题行由壳给（`notes[0]`）。"""
    seg = _pool_source(webui.read_page_file("app.js"))
    m = re.search(r'var POOL_NOTES_TITLE = "([^"]+)"', seg)
    assert m, "标题要有个具名常量（别把中文字符串散在逻辑里）"
    title = m.group(1)
    assert title in webui.read_page_file("index.html"), \
        f"标题 {title!r} 与卡片上那条 <summary> 对不上（两种形态读起来该一致）"
    assert "[POOL_NOTES_TITLE]" in seg, "标题要真的作为 notes 的第一条传下去"


def test_axis_names_are_in_the_payload_and_the_layer_reads_the_same_fields():
    """轴名归壳（静态层不写文案）：`style` 给四个名字，静态层读的就是这四个字段名。"""
    st = webui.catalog_payload().get("style") or {}
    js = webui.read_page_file("figs2d.js")
    for field in ("xlabel", "ylabel", "xlabel_bg", "ylabel_bg"):
        assert st.get(field), f"目录响应里缺 style.{field}"
        assert f"st.{field}" in js, f"静态层没读 style.{field} —— 轴名不会显示"
    assert "$" not in st["xlabel"] and "$" not in st["ylabel"], "mathtext 标记要摘掉（SVG 画不了）"
    assert "ΔV" in st["xlabel"], st["xlabel"]

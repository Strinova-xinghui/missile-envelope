# -*- coding: utf-8 -*-
"""静态托管版首页（`Static` 分支）：左栏只留弹池，整页零服务端。

判据**不依赖任何 Python 服务** —— 托管环境里没有后端，所以这里直接读那三个文件
（`webui_static/index.html` / `app.css` / `app.js`）的文本，外加数据文件里的相对引用。

四条主判据（对应派单）：
  ① 零 `/api`、零 `/static`、零以 `/` 开头的 `src|href`（GitHub Pages 子路径 + Cloudflare 都要能跑）；
  ② 左栏只剩弹池：那份"想定输入"表的字样一个都不许再出现（禁用词逐条断）；
  ③ 三张卡片各有宿主容器、`_static` 回落 `<img>`、三个相对下载链接、`./method.html` 入口；
  ④ 弹池预设按钮由目录数据驱动（HTML 里只有一个空容器），全选 / 清空 / 删除单枚都有具名函数。

反证在 `test_no_absolute_or_backend_refs_has_teeth` 与 `test_no_server_placeholders_has_teeth`：
把违规串**注入文本**后，同一个检查函数必须报出来 —— 否则那两条判据是空的。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "missile_sim" / "webui_static"
HTML = PAGE / "index.html"
CSS = PAGE / "app.css"
JS = PAGE / "app.js"

#: 左栏那份"想定输入"表里才有的字样：静态托管版一个都不该留（连注释里也不许）。
RAIL_BANNED = (
    "环境预设", "预置想定", "提交", "进度", "出哪张图", "后台任务", "后台",
    "忘记上次输入", "等时线步长", "参与散点的弹", "ΔV 步长", "BC 步长",
    "单工况试算", "只出图不扫描", "想定输入",
)
#: 弹池那一节必须有的元素 id（左栏只剩它）—— StatShark 式：搜索框 + 右侧 ＋ + 候选 + 已选导弹。
RAIL_KEEP = ("poolsearch", "pooladd", "poolcands", "poolnone", "poolsub", "poolpicked",
             "poolpresets", "poolcount", "poolAll", "poolClear")
#: 页面里不许再有服务端占位符（`render_page()` 那套在托管环境里不存在）。
TOKEN_RE = re.compile(r"__[A-Z][A-Z_]*__")
#: 以 `/` 开头的 `src`/`href`（GitHub Pages 子路径下会指到域名根，直接裂）。
ABS_REF_RE = re.compile(r"""(?:src|href)\s*=\s*["']\s*/""", re.I)
#: 后端痕迹：接口路径与静态路由（两个都不许出现）。
BACKEND_RE = re.compile(r"/api/|/static/")
#: 相对图件引用。
FIG_REF_RE = re.compile(r"\./figures/([A-Za-z0-9_.\-]+)")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _fn_body(js: str, name: str) -> str:
    """抠出 `function <name>(` 的函数体（到下一个**顶格** `function ` 为止）。

    ⚠ 不能拿"下一个 `function `"直接切：函数体里就有 `.forEach(function (h) {`。
    """
    i = js.index(f"function {name}(")
    m = re.search(r"\nfunction ", js[i + 1:])
    return js[i:(i + 1 + m.start()) if m else len(js)]


def _code_only(text: str) -> str:
    """去掉整行 `//` 注释（口径同 `test_fig3_web`：注释不是代码）。

    注释里会**提到** `fetch(` 这个写法（讲口径），不剥掉就会把解释数成调用。
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))


def _abs_refs(html: str) -> list:
    return ABS_REF_RE.findall(html)


def _backend_refs(text: str) -> list:
    return BACKEND_RE.findall(text)


# ------------------------------------------------------------ ① 零后端 / 零绝对路径


def test_no_backend_and_no_root_absolute_paths():
    """三个文件里既没有后端路径，也没有以 `/` 开头的 `src|href`。"""
    for p in (HTML, CSS, JS):
        bad = _backend_refs(_read(p))
        assert bad == [], f"{p.name} 里出现了后端路径 {bad}"
    html = _read(HTML)
    assert _abs_refs(html) == [], f"首页里有以 `/` 开头的 src/href：{_abs_refs(html)}"
    # 相对引用要真的写出来（别靠浏览器猜；`./` 前缀是这一版的口径）
    for want in ('href="./app.css"', 'href="./figs2d.css"', 'src="./app.js"',
                 'src="./figs2d.js"', 'href="./method.html"', 'href="./LICENSE"'):
        assert want in html, f"首页缺相对引用 {want}"


def test_no_absolute_or_backend_refs_has_teeth():
    """反证：把 `/static/x.js` / `/api/catalog` 塞进文本，检查函数必须当场报出来。"""
    html = _read(HTML)
    assert _abs_refs(html) == [] and _backend_refs(html) == []
    dirty = html.replace('src="./app.js"', 'src="/static/x.js"', 1)
    assert dirty != html, "反证没改到文本 —— 换一处锚点"
    assert _abs_refs(dirty), "塞了以 `/` 开头的 src 却抓不到：这条判据没有牙"
    assert _backend_refs(dirty), "塞了 /static/ 却抓不到：这条判据没有牙"
    assert _backend_refs(_read(JS) + "\n fetch('/api/catalog')"), "JS 里的 /api/ 必须被抓到"


def test_no_server_placeholders():
    """静态页不许留 `__TOKEN__`：托管环境里没有 Python 去替换它们。

    ⚠ 两个**例外**是壳自己冻结的全局名（`window.__CATALOG__` / `window.__NOTES__`，
    组装方写进 `catalog.js` / `notes.js` 的数据），它们长得像服务端占位符但不是。
    """
    frozen = {"__CATALOG__", "__NOTES__"}
    for p in (HTML, CSS, JS):
        got = [t for t in TOKEN_RE.findall(_read(p)) if t not in frozen]
        assert got == [], f"{p.name} 里还有服务端占位符：{got}"


def test_no_server_placeholders_has_teeth():
    """反证：往首页里塞一个占位符，上面那条判据必须红。"""
    html = _read(HTML)
    frozen = {"__CATALOG__", "__NOTES__"}
    assert [t for t in TOKEN_RE.findall(html) if t not in frozen] == []
    assert TOKEN_RE.findall(html + "\n<p>__SOLVER__</p>"), "占位符正则抓不到东西"


def test_data_comes_from_globals_first_and_fetch_only_as_a_fallback():
    """数据口径（`file://` 双击那条路逼出来的）：**优先脚本载入的全局**，fetch 只在全局缺失时发。

    * 页面必须用相对 `<script src>` 先载入 `./catalog.js` / `./notes.js`（`app.js` 之前）；
    * `app.js` 先读 `window.__CATALOG__` / `window.__NOTES__`，**缺哪一半才为那一半 fetch**；
    * `fetch(` 在整个文件里只许出现**一次**（在 `poolFetchJson` 里），URL 只有那两个同目录 JSON；
    * 不许别的东西（XHR / SSE / WebSocket / 轮询）—— 目录与图注读进来之后全是纯客户端。
    """
    html = _read(HTML)
    for tag in ('<script src="./catalog.js"></script>', '<script src="./notes.js"></script>'):
        assert tag in html, f"首页缺脚本载入的数据：{tag}"
    assert html.index('./catalog.js') < html.index('./app.js'), "数据脚本必须在 app.js 之前"
    assert html.index('./notes.js') < html.index('./app.js')
    js = _read(JS)
    code = _code_only(js)          # 注释里提到 fetch( 不算（口径同别处：注释不是代码）
    assert code.count("fetch(") == 1, f"fetch( 只许出现在 poolFetchJson 里，现在 {code.count('fetch(')} 处"
    assert "fetch(url" in code and '"./catalog.json"' in js and '"./notes.json"' in js
    assert "window.__CATALOG__" in js and "window.__NOTES__" in js, "先看全局"
    # 「缺哪一半才 fetch 哪一半」：两个 URL 都是**条件表达式**里的那一支
    i = code.index("function poolLoadData(")
    body = code[i:code.index("\nfunction ", i + 1)]
    assert body.count("poolFetchJson(") == 2, body
    assert "cat ? Promise.resolve(cat) : poolFetchJson" in body
    assert "notes ? Promise.resolve(notes) : poolFetchJson" in body
    assert "XMLHttpRequest" not in code and "EventSource" not in code and "WebSocket" not in code


# ------------------------------------------------------------ ② 左栏只剩弹池


def test_rail_只有弹池():
    """左栏那份输入表的字样一条都不许留，弹池的元素一个都不能少。"""
    html = _read(HTML)
    for word in RAIL_BANNED:
        assert word not in html, f"首页里还留着「{word}」——静态版左栏只留弹池"
    for word in RAIL_BANNED:
        assert word not in _read(JS), f"app.js 里还留着「{word}」"
    for el in RAIL_KEEP:
        assert f'id="{el}"' in html, f"弹池少了控件 #{el}"
    assert '<aside class="rail" id="rail">' in html, "左栏还是那条 rail（观感不变）"
    assert "rail-sec" in html and "chip" in html, "沿用既有骨架与 chip 观感"


# ------------------------------------------------------------ ③ 三张卡片与回落


def test_three_cards_have_hosts_and_static_fallbacks():
    """图1/图2/图3 各有宿主容器；图1/图2 保留 `_static` 回落与三个相对下载链接。"""
    html = _read(HTML)
    for host in ('class="figs2d-host" id="fig1host"', 'class="figs2d-host" id="fig2host"',
                 'class="figs3d-host" id="fig3host"'):
        assert host in html, f"缺宿主容器：{host}"
    for stem in ("fig_isotime_plane_static", "fig_bg_plane_static"):
        assert f'src="./figures/{stem}.png"' in html, f"{stem} 的回落静态图没了"
        for ext in ("png", "pdf", "svg"):
            assert f'href="./figures/{stem}.{ext}"' in html, f"缺下载链接 {stem}.{ext}"
    assert "download" in html, "三个链接要能直接存下来（download 属性）"
    assert 'href="./method.html"' in html, "缺口径页入口"
    assert 'href="./LICENSE"' in html, "缺许可入口"


def test_referenced_figures_exist_in_the_repo():
    """页面里每个相对图件引用都要在 `figures/` 里真实存在（拼错名字 = 上线裂图）。"""
    refs = sorted(set(FIG_REF_RE.findall(_read(HTML))))
    assert refs, "扫不到图件引用 —— 这条判据是空的"
    missing = [n for n in refs if not (ROOT / "figures" / n).is_file()]
    assert not missing, f"首页引用了不存在的图件：{missing}"


# ------------------------------------------------------------ ④ 弹池四个动作


def test_pool_presets_are_data_driven_and_actions_have_named_functions():
    """预设按钮**由目录数据驱动**（HTML 里只有一个空容器），全选 / 清空 / 删除单枚各有具名函数并接上。"""
    js = _read(JS)
    code = _code_only(js)
    html = _read(HTML)
    assert 'id="poolpresets"' in html, "预设容器不在页面上"
    assert "pool11" not in html and "仅 11 弹" not in html, "预设按钮又被写死回 HTML 了"
    for fn in ("function poolBuildPresets(", "function poolApplyPreset(", "function poolPresetKeys(",
               "function poolMatchRule(", "function poolPresets("):
        assert fn in code, f"缺预设渲染的具名函数 {fn}"
    build = _fn_body(code, "poolBuildPresets")
    assert "poolPresets().forEach" in build and "poolApplyPreset(i)" in build, build
    assert '$("#poolpresets")' in build, "预设按钮要渲染进那个容器"
    for fn in ("function poolClear(", "function poolPickAll(", "function poolRemove("):
        assert fn in js, f"缺具名动作 {fn}"
    assert '$("#poolClear").onclick = poolClear;' in code
    assert '$("#poolAll").onclick = poolPickAll;' in code
    assert "poolRemove(k)" in code, "已选导弹那条右侧的 ✕ 要调用 poolRemove"
    # 默认选中来自目录的 `in_pool11`（壳里不写死弹名），存档键沿用既有命名
    assert "in_pool11" in code and "poolEntries()" in code
    for name in ("PL-12", "MICA", "AAM-4", "120C"):
        assert f'"{name}"' not in code, f"壳里写死了弹名 {name}"
    assert 'POOL_KEY = "missile-sim:pool"' in js
    assert "localStorage.setItem(POOL_KEY" in code and "localStorage.getItem(POOL_KEY" in code


def test_pool_has_the_four_statshark_interactions():
    """StatShark 式四件事各自成条：**搜索 / 选中 ＋ 加号 / 已选导弹列表 / 删除单枚**。"""
    js = _read(JS)
    code = _code_only(js)
    html = _read(HTML)
    css = _read(CSS)
    # ① 搜索：键入即筛（绑 oninput）＋ 一条没命中给提示行
    assert "function poolFilter(" in code and "function poolFold(" in code
    assert '$("#poolsearch").oninput = function () { poolFilter(this.value); };' in code
    assert 'id="poolnone"' in html and "没有匹配" in html
    fbody = _fn_body(code, "poolFilter")
    assert "$(\"#poolnone\")" in fbody and "none.hidden = shown > 0" in fbody
    # ② 选中（`poolPickCurrent`，点候选）＋ 加号（`poolAddCurrent`，搜索框右侧 ＋）
    assert "function poolPickCurrent(" in code and "function poolAddCurrent(" in code
    assert '$("#pooladd").onclick = poolAddCurrent;' in code
    assert 'id="pooladd"' in html and "＋" in html
    assert 'row.onclick = function () { poolPickCurrent(String(m.key)); };' in code
    # 加号只在"有选中"时可点；加完清空选中（一次一条）
    sbody = _fn_body(code, "poolShowCurrent")
    assert "btn.disabled = !POOL.current" in sbody and "on" in sbody
    abody = _fn_body(code, "poolAddCurrent")
    assert "POOL.current = null" in abody and "poolAdd(k)" in abody
    # ③ 已选导弹列表：左对齐 + 每条右侧一个**红色 ✕**
    assert 'id="poolpicked"' in html and "已选导弹" in html
    pbody = _fn_body(code, "poolPicked")
    assert 'x.className = "x"' in pbody and 'setText(x, "✕")' in pbody
    assert 'x.onclick = function () { poolRemove(k); };' in pbody
    assert ".pool-picked .pick .x{" in css and "color:var(--err)" in css, "✕ 要是红的"
    assert ".pool-picked .pick{" in css and "text-align:left" in css, "已选列表左对齐"
    assert "还没选，点上面 ＋ 添加" in pbody, "空列表要有一行提示"
    # ④ 删除单枚：具名函数 + 接到 ✕ 上（上面已断），并且是**唯一**入口
    assert code.count('x.onclick = function () { poolRemove(k); };') == 1


def test_pool_candidates_are_left_aligned_and_prefer_full_name():
    """候选一列**左对齐**、名字用 `full_name`（与 `native` 不同时优先它），别把开头裁掉。"""
    css = _read(CSS)
    js = _read(JS)
    assert "#sec-pool .pool-row .nm{text-align:left" in css, "候选名字必须显式左对齐"
    assert "overflow-wrap:anywhere" in css, "长名字在**尾部**换行，别裁开头"
    assert "text-align:right" not in css, "候选/已选都不许右对齐"
    code = _code_only(js)
    body = _fn_body(code, "poolRowName")
    assert "full_name" in body and "native" in body
    assert "full !== native" in body, "与 native 不同才优先 full_name，相同就用 native"
    # 不可算的那几条照样列出、置灰、悬停给目录里的原因（口径没变）
    assert "poolUnsupported().forEach" in body or "poolUnsupported()" in code
    off = _fn_body(code, "poolMakeRow")
    assert 'row.className = off ? "pool-row off" : "pool-row"' in off
    assert "m.reason" in off and "m.kernel_reason" in off


#: 四个交互各自的"绑定"必须在位（拔掉任意一条都要被抓到 —— 见下面的反证）。
POOL_BINDINGS = (
    ('$("#poolsearch").oninput = function () { poolFilter(this.value); };', "搜索框没接 poolFilter"),
    ('$("#pooladd").onclick = poolAddCurrent;', "＋ 没接 poolAddCurrent"),
    ("row.onclick = function () { poolPickCurrent(String(m.key)); };", "候选行没接 poolPickCurrent"),
    ("x.onclick = function () { poolRemove(k); };", "已选那条的 ✕ 没接 poolRemove"),
)


def _pool_binding_problems(code: str) -> list:
    """纯函数：四个交互的绑定缺哪条就报哪条（反证直接喂改坏的源码给它）。"""
    return [why for needle, why in POOL_BINDINGS if needle not in code]


def test_pool_interaction_bindings_are_all_in_place():
    js = _read(JS)
    problems = _pool_binding_problems(_code_only(js))
    assert problems == [], problems


def test_pool_interaction_bindings_checker_has_teeth():
    """反证：把 ＋ 或 ✕ 的绑定删掉，上面那条判据必须当场红。"""
    code = _code_only(_read(JS))
    assert _pool_binding_problems(code) == []
    for needle, why in POOL_BINDINGS:
        mutant = code.replace(needle, "/* 拔掉 */", 1)
        assert mutant != code, f"反证没改到源码：{why}"
        got = _pool_binding_problems(mutant)
        assert got, f"拔掉「{why}」却抓不到 —— 这条判据是空的"


# ------------------------------------------------------------ 冻结接口与渐进增强


def test_frozen_mount_interfaces_are_used_as_documented():
    """两张平面图用 `mount(host,{kind,catalog,notes})`，三维用 `mount(host,{catalog,style})`。"""
    js = _read(JS)
    assert "window.FIGS2D" in js and "F.mount(h.host, {kind: h.kind, catalog: POOL.catalog, notes:" in js
    assert "window.FIG3STATIC" in js
    assert "G.mount(host, {catalog: POOL.catalog, style:" in js
    # 两个接口都要有"不存在就走回落"的出口，且选择必须同步给三张图
    assert js.count('typeof F.mount !== "function"') == 1
    assert js.count('typeof G.mount !== "function"') == 1
    assert '["plane", "bg", "fig3"]' in js and "setSelection(keys)" in js


def test_progressive_enhancement_keeps_the_static_image():
    """挂载成功前不许隐藏 `_static` 回落；目录/脚本缺件都要有一行提示。"""
    js = _read(JS)
    body = _fn_body(js, "poolMount")
    assert "F.mount(" in body, "这次的挂载就在 `poolMount` 里（换名字要同步这条判据）"
    assert body.index("F.mount(") < body.index("st.hidden = true"), \
        "先把回落图藏了再挂载 —— 脚本缺失时首页就没图了"
    assert ('.querySelector("img.static")' in js), "回落图要按元素找，不是删掉"
    for hint in ("目录读不到", "fig3.js 里没有 FIG3STATIC"):
        assert hint in js, f"缺一条回落提示：{hint}"


def test_third_figure_is_wired_to_the_static_3d_layer():
    """图3 接到静态三维层：`./fig3.css` 链上、`FIG3STATIC.mount` 起来后藏掉那行说明。

    ⚠ `fig3.css` 是**收窄版**（整页/老 DOM 那批规则全挂在 `body.fig3page` 下），所以首页能共用它；
    `fig3.html` 必须带这个钩子，否则 `/fig3` 整页会丢掉自己的全屏布局。
    """
    html = _read(HTML)
    assert '<link rel="stylesheet" href="./fig3.css">' in html, "首页没链 ./fig3.css"
    js = _read(JS)
    body = _fn_body(js, "poolMount3d")
    assert "G.mount(host, {catalog: POOL.catalog, style:" in body
    assert body.index("G.mount(") < body.index("fb.hidden = true"), \
        "先把说明藏了再挂载 —— 挂载失败时卡片里就没话说了"
    assert '<body class="fig3page">' in _read(PAGE / "fig3.html"), \
        "/fig3 的 <body> 少了 `fig3page` 钩子 —— 收窄后的 fig3.css 全靠它给整页上样式"


def _fig3_script_order_ok(html: str) -> bool:
    """`fig3.html` 里 `figs2d.js` 的 `<script>` 是否排在 `fig3.js` 之前。"""
    try:
        return html.index('src="/static/figs2d.js"') < html.index('src="/static/fig3.js"')
    except ValueError:
        return False


def test_fig3_page_loads_figs2d_before_fig3():
    """`/fig3` 的脚本顺序：`figs2d.js` 必须在 `fig3.js` **之前**。

    原因：`fig3.js` 不再自带 `niceTick`/`minorFor`，改成复用 `FIGS2D.ticks`（刻度引擎统一到一处）
    ⇒ 缺了 `figs2d.js`（或顺序反了）时它拿不到 `FIGS2D`，**控制台报错**、刻度也画不出来。
    静态首页 `index.html` 早已引 `./figs2d.js`（在 `app.js` 之前），这条只管 `/fig3` 那页。
    """
    html = _read(PAGE / "fig3.html")
    assert 'src="/static/figs2d.js"' in html, "/fig3 那页没引 figs2d.js"
    assert _fig3_script_order_ok(html), "figs2d.js 必须排在 fig3.js 之前（fig3.js 复用 FIGS2D.ticks）"


def test_fig3_page_script_order_checker_has_teeth():
    """反证：把两行的顺序调过来必须被抓到。"""
    html = _read(PAGE / "fig3.html")
    assert _fig3_script_order_ok(html)
    tag2d = '<script src="/static/figs2d.js"></script>'
    tag3d = '<script src="/static/fig3.js"></script>'
    swapped = html.replace(tag2d, "", 1).replace(tag3d, tag3d + "\n" + tag2d, 1)
    assert swapped != html, "反证没改到源码 —— 换一处锚点"
    assert not _fig3_script_order_ok(swapped), "顺序反了却抓不到：这条判据没有牙"


def test_notes_title_has_a_single_source():
    """图注标题只许来自 `./notes.json`：壳里不许再写一遍那行文字。"""
    js = _read(JS)
    assert "notes.title" in js or "n.title" in js, "标题要取 notes.json 的 title"
    for p in (HTML, JS):
        assert "图注（原先画在图里，现已移到页面）" not in _read(p), \
            f"{p.name} 里手写了整整一行标题 —— 单一出处是 ./notes.json"
    assert "notesFor(" in js and "notesInto(" in js, "图注要既喂给静态层、又填进卡片"


# ------------------------------------------------------------ 左栏折叠（行为探针）

#: 用 node + 桩 DOM 真跑一遍 `app.js` 的折叠那一段：点 `#railtoggle` → 写 `localStorage` →
#: **重载后仍生效**。判据不引第三方（手写 20 行桩），没有 node 就 skip（与 `-k fig3` 的 node 探针同款）。
#: 目录那两次 `fetch` 用"永不 resolve 的 Promise"顶掉 —— 折叠行为不依赖目录，也顺带证明
#: 目录还没到之前页面不会因为弹池而抛异常。
RAIL_PROBE_JS = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");

function makeEl(id) {
  const classes = new Set();
  return {
    id: id, textContent: "", hidden: false, title: "", onclick: null,
    classList: {
      has: (c) => classes.has(c),
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) { classes.add(c); } else { classes.delete(c); } },
    },
    setAttribute: () => {}, getAttribute: () => null, appendChild: () => {},
    addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [],
  };
}

function run(store, width) {
  const els = {};
  ["shell", "railtoggle", "poollist", "poolcount", "msg"].forEach((i) => { els[i] = makeEl(i); });
  const document = {
    querySelector: (s) => (s[0] === "#" ? (els[s.slice(1)] || null) : null),
    querySelectorAll: () => [],
    createElement: (t) => makeEl(t),
    addEventListener: () => {},
  };
  const localStorage = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
  const sandbox = {document: document, localStorage: localStorage, fetch: () => new Promise(() => {}),
                   console: console};
  sandbox.window = {innerWidth: width, document: document, localStorage: localStorage};
  vm.runInNewContext(src, sandbox, {filename: "app.js"});
  return {els: els, store: store};
}

const KEY = "missile-sim:rail";
const store = {};
const out = {};
const r1 = run(store, 1400);
out.initial = {collapsed: r1.els.shell.classList.has("rail-collapsed"), stored: store[KEY] || null};
r1.els.railtoggle.onclick();
out.after_click = {collapsed: r1.els.shell.classList.has("rail-collapsed"), stored: store[KEY] || null};
const r2 = run(store, 1400);            // 模拟刷新：同一份 localStorage 再跑一遍
out.after_reload = {collapsed: r2.els.shell.classList.has("rail-collapsed"), stored: store[KEY] || null};
r2.els.railtoggle.onclick();
out.after_second_click = {collapsed: r2.els.shell.classList.has("rail-collapsed"), stored: store[KEY] || null};
console.log(JSON.stringify(out));
"""


def test_static_page_rail_collapse_is_remembered(tmp_path):
    """静态页左栏折叠：点一下收起并写 `missile-sim:rail`，**刷新后仍收起**，再点回到展开。

    ⚠ 这条是 2026-10-05 补的：老探针（`test_webui_layout::test_rail_collapse_is_remembered`）
    按表单首页的点法跑，随首页一起 skip 了；但折叠行为在静态页里**确实还在**
    （`applyRail()` + `missile-sim:rail`），不能因此丢掉覆盖。
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器没有 node，跳过静态页折叠探针（源码级契约仍在上面几条）")
    script = Path(tmp_path) / "rail_probe.js"
    script.write_text(RAIL_PROBE_JS, encoding="utf-8")
    proc = subprocess.run([node, str(script), str(JS)], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, f"折叠探针跑挂了：\n{proc.stderr[-2000:]}"
    got = json.loads(proc.stdout)
    assert got["initial"] == {"collapsed": False, "stored": None}, got
    assert got["after_click"] == {"collapsed": True, "stored": "1"}, got
    assert got["after_reload"] == {"collapsed": True, "stored": "1"}, \
        f"刷新后没恢复收起状态：{got['after_reload']}"
    assert got["after_second_click"] == {"collapsed": False, "stored": "0"}, got


# ------------------------------------------------------------ 数据两条路（`file://` 那条）

#: 数据探针：node + 桩 DOM 真跑一遍 `app.js`，看它**从哪拿数据**、拿不到时会不会白屏。
#: `fetch` 一律**拒绝**（模拟 `file://` 下浏览器按跨源拦掉本地文件），并记录调用次数与 URL。
DATA_PROBE_JS = r"""
const fs = require("fs");
const vm = require("vm");
let src = fs.readFileSync(process.argv[2], "utf8");
const data = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const mode = process.argv[4] || "globals";
const mutate = process.argv[5] || "";
// 反证用：把源码里某一步**真的改坏**，再拿同一批断言去判 —— 判据必须红。
//   `empty-as-restored` ⇒ 把"存的为空数组视同没存"那一步去掉（模拟有人把那一行删了）。
if (mutate === "empty-as-restored") {
  const anchor = "saved.length > 0";
  if (src.indexOf(anchor) < 0) { throw new Error("反证锚点没了：" + anchor); }
  src = src.replace(anchor, "true");
} else if (mutate) {
  throw new Error("不认识的反证：" + mutate);
}

function makeEl(id) {
  const classes = new Set();
  let text = "";
  // ⚠ 真 DOM 的 `children` 是 HTMLCollection：**没有 forEach / push**，而且 `textContent = ""` 会清空它。
  //    桩故意做成"数组样但没有 forEach" —— 壳里若把它当数组用（`.forEach`）会当场炸。
  //    2026-10-05 真页面上抓到过一次（`poolPresetChips(...).forEach is not a function`），
  //    当时桩太宽容（children 是数组、还带 forEach）所以漏过去了。
  const kids = {length: 0};
  const el = {
    id: id, hidden: false, title: "", onclick: null, oninput: null, style: {},
    children: kids,
    classList: {
      has: (c) => classes.has(c), contains: (c) => classes.has(c),
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) { classes.add(c); } else { classes.delete(c); } },
    },
    setAttribute: () => {}, getAttribute: () => null,
    appendChild: (c) => { kids[kids.length] = c; kids.length += 1; return c; },
    addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [],
  };
  Object.defineProperty(el, "textContent", {
    get: () => text,
    set: (v) => { text = String(v); kids.length = 0; },      // 同真 DOM：设 textContent 会清空子节点
  });
  return el;
}

const IDS = ["shell", "railtoggle", "msg", "poolcands", "poolnone", "poolsub",
             "poolpresets", "pooladd", "poolcount", "poolstat", "poolpicked", "poolAll",
             "poolClear", "poolsearch", "poolrestored", "poolrestoredtext",
             "fig1host", "fig1box", "fig1notes", "fig1notestitle",
             "fig2host", "fig2box", "fig2notes", "fig2notestitle",
             "fig3host", "fig3fallback", "fig3notes"];
const els = {};
IDS.forEach((i) => { els[i] = makeEl(i); });
const statics = {plane: makeEl("img"), bg: makeEl("img")};
els.fig1box.querySelector = (s) => (s === "img.static" ? statics.plane : null);
els.fig2box.querySelector = (s) => (s === "img.static" ? statics.bg : null);

const document = {
  querySelector: (s) => (s[0] === "#" ? (els[s.slice(1)] || null) : null),
  querySelectorAll: () => [],
  createElement: (t) => makeEl(t),
  addEventListener: () => {},
};
// 有状态的 localStorage：可选先用 `data.store` 预置（模拟"上次访问存过的弹池"）。
const store = {};
if (data.store) { Object.keys(data.store).forEach((k) => { store[k] = data.store[k]; }); }
const localStorage = {
  getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
const fetches = [];
const sandbox = {
  document: document, localStorage: localStorage, console: console,
  fetch: (u) => { fetches.push(String(u)); return Promise.reject(new Error("file:// 下不许读本地文件")); },
};
sandbox.window = {innerWidth: 1400, document: document, localStorage: localStorage};
if (mode === "globals" || mode === "seeded" || mode === "action") {
  sandbox.window.__CATALOG__ = data.catalog;
  sandbox.window.__NOTES__ = data.notes;
}
vm.runInNewContext(src, sandbox, {filename: "app.js"});

function snap() {
  return {
    hintHidden: els.poolrestored.hidden,
    hintText: els.poolrestoredtext.textContent,
    count: els.poolcount.textContent,
    storeKeys: Object.keys(store),
    storedPool: store["missile-sim:pool"] || null,
  };
}

setTimeout(() => {
  const out = {
    fetches: fetches,
    rows: els.poolcands.children.length,
    notes: els.fig1notes.children.length,
    note0: els.fig1notes.children.length ? els.fig1notes.children[0].textContent : "",
    msg: els.msg.textContent,
    stat: els.poolstat.textContent,
    presetChips: els.poolpresets.children.length,
    presetLabel0: els.poolpresets.children.length ? els.poolpresets.children[0].textContent : "",
    staticHidden: [statics.plane.hidden, statics.bg.hidden],
    before: snap(),
  };
  if (mode === "action") {                // 用户一动手：先点「全选可算」，再点第一条预设按钮
    if (els.poolAll.onclick) { els.poolAll.onclick(); }
    out.after_action1 = snap();
    var chip = els.poolpresets.children[0];      // 预设按钮是壳渲染出来的 ⇒ 它的 onclick 也是壳接的
    if (chip && chip.onclick) { chip.onclick(); }
    out.after_action2 = snap();
  }
  console.log(JSON.stringify(out));
}, 60);
"""


def _tiny_data(tmp_path) -> Path:
    """给探针的最小目录/图注（形状与组装方写进 `catalog.js` / `notes.js` 的一致）。"""
    data = {
        "catalog": {
            "ok": True, "schema": 1, "count": 3, "computable": 2,
            "solver": {"solver": "wt-missile", "model": "python-game-6dof-v1", "version": "2.59.0.28"},
            "reference": {"alt_m": 10000.0, "speed_ms": 800.0, "mach": 2.66, "q_pa": 1.3e5,
                          "f_mach": 0.376, "cap_f": 1.17},
            "standard": "PL-12",
            "style": {"point_color": "#D32F2F", "base_color": "#388E3C", "nstar_color": "#2661d9",
                      "nstar_levels": [14.0, 15.0], "xlabel": "总增速 ΔV（m/s）", "ylabel": "简化弹道系数（β）",
                      "xlabel_bg": "β", "ylabel_bg": "ginv = 1/γ"},
            "missiles": [
                {"key": "PL-12", "label": "PL-12", "full_name": "PL-12", "seeker": "ARH",
                 "in_pool11": True, "duplicate_of": None, "default_hidden": False,
                 "dv": 932.6, "bc": 3078.1, "ginv": 0.01767},
                {"key": "us_aim_120b", "label": "us_aim_120b", "full_name": "us_aim_120b", "seeker": "ARH",
                 "in_pool11": False, "duplicate_of": None, "default_hidden": False,
                 "dv": 1200.0, "bc": 3600.0, "ginv": 0.012},
            ],
            "presets": [
                {"label": "仅主动弹", "keys": {"in_pool11": True}, "hint": "小目录里的主动弹"},
            ],
            "unsupported": [
                {"key": "cn_pl15", "label": "cn_pl15", "seeker": "ARH", "reason": "需要动态解算",
                 "kernel_reason": "propulsion* 多发动机族"},
            ],
        },
        "notes": {"title": "图注（原先画在图里，现已移到页面）",
                  "fig1": ["第一条图注", "第二条图注"], "fig2": ["图2 的一条"]},
    }
    p = Path(tmp_path) / "tiny_data.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _run_data_probe(tmp_path, mode: str, store=None, mutate: str = "") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器没有 node，跳过静态页取数探针（源码级契约仍在上面几条）")
    data_path = _tiny_data(tmp_path)
    if store is not None:                    # 预置 localStorage（模拟"上次访问存过的弹池"）
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["store"] = {"missile-sim:pool": json.dumps(store, ensure_ascii=False)}
        data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = Path(tmp_path) / f"data_probe_{mode}{('_' + mutate) if mutate else ''}.js"
    script.write_text(DATA_PROBE_JS, encoding="utf-8")
    proc = subprocess.run([node, str(script), str(JS), str(data_path), mode, mutate],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, f"取数探针跑挂了（{mode}/{mutate}）：\n{proc.stderr[-2000:]}"
    return json.loads(proc.stdout)


def test_data_comes_from_the_globals_with_zero_fetch(tmp_path):
    """全局在（`file://` 双击那条路）⇒ **一次 fetch 都不发**，弹池照常起来。"""
    got = _run_data_probe(tmp_path, "globals")
    assert got["fetches"] == [], f"全局在却还发 fetch：{got['fetches']}"
    assert got["rows"] == 3, got          # 2 可算 + 1 置灰（不可算的也要列出来）
    assert got["before"]["count"].startswith("已选"), got["before"]["count"]
    assert "待动态解算 1" in got["before"]["count"], got["before"]["count"]
    assert got["notes"] == 2, got          # 图注来自 `window.__NOTES__`
    assert got["msg"] == "", "拿到数据了不该报错"
    assert got["presetChips"] == 1, got          # 预设按钮由目录数据渲染（小目录里就一条）
    assert got["presetLabel0"] == "仅主动弹", got
    assert got["staticHidden"] == [False, False], "没有渲染器时那份静态图必须还在"


def test_no_globals_and_no_fetch_falls_back_without_a_blank_page(tmp_path):
    """**反证**：把 `./catalog.js` 从页面拿掉（全局不存在）+ `file://` 下 fetch 失败 ⇒
    必须显示那行提示、保留静态图，**不许静默白屏**。"""
    got = _run_data_probe(tmp_path, "noglobals")
    assert got["fetches"] == ["./catalog.json", "./notes.json"], got["fetches"]
    assert "目录读不到" in got["msg"] and "file://" in got["msg"], got["msg"]
    assert got["before"]["count"] == "目录不可用", got["before"]["count"]
    assert got["rows"] == 0, got
    assert got["staticHidden"] == [False, False], "回落到静态图 —— 不许白屏"
    assert "图注读不到" in got["note0"], got["note0"]
    assert "catalog.js" in got["stat"], got["stat"]


# ------------------------------------------------------------ 弹池记忆：只在打开那一下亮一次

#: 小目录里"默认 11 弹"就是这一条（`in_pool11`）；另一条是"用户后来加的"。
TINY_DEFAULT = ["PL-12"]
TINY_EXTRA = ["PL-12", "us_aim_120b"]


def test_restored_pool_hint_is_pure_text_in_the_page():
    """提示行是**纯文字**：没有 `#poolreset`、没有「回到 11 弹」这类动作，只有通知条样式。"""
    html = _read(HTML)
    assert 'id="poolrestored"' in html and 'id="poolrestoredtext"' in html
    assert "已恢复你上次的弹池" in html, "缺那句说明"
    assert 'class="pool-restored"' in html
    assert "**" not in html, "文案里不许有 markdown 星号"
    css = _read(CSS)
    assert ".pool-restored{" in css and "text-align:left" in css, "左对齐的通知条"
    assert ".pool-restored[hidden]{display:none}" in css, \
        "定成 flex 会盖掉 UA 的 [hidden]，必须自己补一条（否则藏不住）"
    assert "font-size:11px" in css, "字号与 rail-note 同级"
    assert ".pool-restored button" not in css, "提示条里不该有按钮样式了"
    code = _code_only(_read(JS))
    assert "function poolRestoredOnce(" in code and "function poolHideRestored(" in code
    assert "poolRestoredOnce();" in code, "boot 时要算一次"
    assert "poolHideRestored();" in _fn_body(code, "poolSet"), \
        "用户动手（poolSet(user=true)）时要收掉提示"


def test_restored_hint_and_reset_are_gone_for_good():
    """**否定判据**：`#poolreset`、「回到 11 弹」以及只服务它的函数都不许再出现（防止被加回来）。"""
    for p in (HTML, CSS, JS):
        text = _read(p)
        assert "poolreset" not in text, f"{p.name} 里还有 #poolreset"
        assert "回到 11 弹" not in text, f"{p.name} 里还有「回到 11 弹」"
    code = _code_only(_read(JS))
    assert "poolResetTo11" not in code, "只服务旧复位的函数还在"
    assert "poolClearStore" not in code, "清存档的辅助函数没有别的调用者了，应该一起删掉"
    assert "localStorage.removeItem" not in code, "没有别的调用者就不该再留 removeItem"


def test_restored_pool_hint_only_shows_on_the_first_frame(tmp_path):
    """首帧**四态**：存过非默认 ⇒ 亮（数字 = 已选数）；存过=默认 ⇒ 不亮；**存过=空 ⇒ 不亮**；
    从未存过 ⇒ 不亮。"""
    got = _run_data_probe(tmp_path, "seeded", store=TINY_EXTRA)
    assert got["before"]["hintHidden"] is False, "存过非默认弹池却没提示"
    assert "已恢复你上次的弹池 2 枚" in got["before"]["hintText"], got["before"]["hintText"]
    assert got["before"]["count"].startswith("已选 2 /"), got["before"]["count"]

    same = _run_data_probe(tmp_path, "seeded", store=TINY_DEFAULT)
    assert same["before"]["hintHidden"] is True, "存的正好是默认 11 弹 ⇒ 不该出现"

    # 存过但存的是**空数组**（用户点过「清空」）⇒ 视同"没存过"，别写「已恢复 0 枚」
    empty = _run_data_probe(tmp_path, "seeded", store=[])
    assert empty["before"]["storedPool"] == "[]", empty["before"]
    assert empty["before"]["hintHidden"] is True, "空池不算恢复（用户 2026-10-05 口径）"

    fresh = _run_data_probe(tmp_path, "seeded", store=None)   # 从没存过
    assert fresh["before"]["hintHidden"] is True, "首次访问不该出现"
    assert fresh["before"]["storedPool"] is None, fresh["before"]


def test_empty_store_rule_has_teeth(tmp_path):
    """反证：把"存的为空数组视同没存"那一步从源码里去掉（`saved.length > 0` → `true`）⇒ 上面那条必须红。"""
    empty = _run_data_probe(tmp_path, "seeded", store=[])
    assert empty["before"]["hintHidden"] is True
    mutant = _run_data_probe(tmp_path, "seeded", store=[], mutate="empty-as-restored")
    assert mutant["before"]["hintHidden"] is False, \
        "去掉那条判断后仍不亮 —— 说明这条反证没有咬到「空 ⇒ 不亮」那一步"


def test_restored_pool_hint_disappears_on_the_first_user_action(tmp_path):
    """**行为探针**（这条抓的就是用户报的 bug）：打开时亮着 ⇒ 用户一动手（这里点「全选可算」）
    ⇒ 提示**立刻隐藏**；再点另一个动作（第一条预设按钮）⇒ **仍然隐藏**（本次会话不再回来）。"""
    got = _run_data_probe(tmp_path, "action", store=TINY_EXTRA)
    assert got["before"]["hintHidden"] is False, "先得亮着，这条判据才有意义"
    assert got["after_action1"]["hintHidden"] is True, \
        "用户动了一次之后提示还挂着 —— 这正是用户报的那个 bug"
    assert got["after_action2"]["hintHidden"] is True, "用户又动了一次，提示不该回来"
    # 顺带确认那两个动作真的生效了（不是"什么都没点"）
    assert got["after_action1"]["count"].startswith("已选 2 /"), got["after_action1"]["count"]
    assert got["after_action2"]["count"].startswith("已选 1 /"), got["after_action2"]["count"]


# ------------------------------------------------------------ 2026-10-05 文案/结构（用户点名）

#: 用户点名删掉/改掉的字样，页面里一个都不许再出现（`method.html` 里另有版本与口径，不在这几页）。
COPY_GONE = (
    "导弹包线图 —— 对比弹池",          # 旧主标题
    "hdrsub",                          # 旧副标题那个容器（整行删掉）
    "本页零后端",                       # 旧副标题后半句
    "选中哪几枚，三张图就画哪几枚",        # 左栏那两行说明
    "三张图就画这些",                    # 「已选导弹（…）」括号里那半句
    "仅 11 弹",                         # 旧按钮名（新名走目录 `presets`）
    'id="pool11"',                     # 旧按钮 id（⚠ `in_pool11` 是**数据字段**，不在被删之列）
    '"#pool11"',                       # 旧按钮的选择器
)


def test_deleted_copy_is_gone_and_the_new_title_is_in():
    """用户点名删掉的文字不许再出现；新主标题与「已选导弹」必须在。"""
    for p in (HTML, JS, CSS):
        text = _read(p)
        for bad in COPY_GONE:
            assert bad not in text, f"{p.name} 里还有被删的文字：{bad}"
    html = _read(HTML)
    assert "<h1>导弹远射性能量化对比</h1>" in html, "新主标题不在页面上"
    assert 'id="poolsub">已选导弹</div>' in html, "「已选导弹」应只剩这五个字（括号那半句要删掉）"


def test_copy_cleanup_has_teeth():
    """反证：把删掉的副标题塞回去必须被抓到（这条判据不是空的）。"""
    html = _read(HTML)
    assert all(bad not in html for bad in COPY_GONE)
    mutant = html.replace("<h1>", '<p class="sub" id="hdrsub">本页零后端</p>\n<h1>', 1)
    assert mutant != html, "反证没改到源码"
    assert any(bad in mutant for bad in COPY_GONE), "塞回副标题却抓不到"


def test_tab_title_is_the_new_name_only():
    """标签页标题就写「导弹远射性能量化对比」—— **不带**括号里那串轴名（用户 2026-10-05 拍板）。"""
    html = _read(HTML)
    assert "<title>导弹远射性能量化对比</title>" in html, "标签页标题不对"
    title = html[html.index("<title>"):html.index("</title>") + len("</title>")]
    for bad in ("ΔV–β", "β–ginv", "导弹包线图", "对比弹池", "（", "）"):
        assert bad not in title, f"标签页标题里不该再有：{bad}"
    assert "<h1>导弹远射性能量化对比</h1>" in html, "主标题与标签页标题应当一致"


def test_figure_notes_text_and_structure():
    """图注正文 = 用户 2026-10-05 逐字给定，单一出处是 `webui.page_figure_notes()`
    （静态站 `notes.json` 就是它）。

    * **图1 = 三段**，顺序必须是 ΔV 解读 / β 解读 / 读法；
    * **图2 = 六段**（β 口径 / γ 口径 / 纵轴与读向 / 等 n* 线 / F(M) 与默认系数 / 读法）；
    * 用户新版删掉的两句（「仿真层：固定 ΔV=…」「本次未跑仿真层…」）两版都不许再有。
    """
    from missile_sim import webui

    notes = webui.page_figure_notes()
    fig1, fig2 = list(notes["fig1"]), list(notes["fig2_static"])
    assert len(fig1) == 3, fig1
    assert len(fig2) == 6, fig2
    for i, head in enumerate(("ΔV 解读：", "β 解读：", "读法：")):     # 顺序钉死
        assert fig1[i].startswith(head), f"图1 第 {i + 1} 段应以「{head}」开头：{fig1[i]!r}"
    assert fig2[3].startswith("等 n* 线："), fig2[3]
    assert fig2[-1].startswith("读法："), fig2[-1]
    for line in fig1 + fig2:
        assert "仿真层" not in line, f"旧文案里的仿真层那句该删：{line!r}"
        assert "**" not in line, f"文案里不许有 markdown 星号：{line!r}"
    assert list(notes["fig2_scan"]) == fig2, "两版文本应当一致（状态句已删）"
    # 关键口径句逐字在（不是"看着差不多"）
    assert fig2[0].startswith("β = m燃尽/(SD·CxK) —— 与简化弹道系数 BC 是同一个数"), fig2[0]
    assert "ginv = 1/γ [m²/kg]" in fig2[2], fig2[2]


def test_pool_presets_payload_is_well_formed():
    """目录 payload 里的 `presets`：至少一条、每条有 label 与**可解析的选择依据**；
    且「仅主动弹」点下去就是那 11 枚（用户 2026-10-05 拍板，**不是**"所有 ARH 可算弹"）。"""
    from missile_sim import webui          # 与组装方写 `catalog.js` 用的是同一份 payload

    pay = webui.catalog_payload()
    assert pay.get("ok") is True, pay
    presets = pay.get("presets")
    assert isinstance(presets, list) and presets, f"payload 里没有 presets：{presets!r}"
    pool11 = sorted(str(m["key"]) for m in pay["missiles"] if m.get("in_pool11"))
    assert len(pool11) == 11, pool11
    labels = []
    for p in presets:
        assert isinstance(p, dict), p
        assert str(p.get("label") or "").strip(), f"这条预设没有 label：{p!r}"
        keys = p.get("keys")
        assert isinstance(keys, (list, dict)), f"选择依据只能是数组（key 清单）或对象（过滤条件）：{p!r}"
        labels.append(p["label"])
    assert "仅主动弹" in labels, labels
    only = [p for p in presets if p["label"] == "仅主动弹"][0]
    if isinstance(only["keys"], list):      # 写法一：直接给 key 清单（当前用的是这种）
        assert sorted(str(k) for k in only["keys"]) == pool11, only["keys"]
    else:                                   # 写法二：过滤条件 —— 按同一口径在目录上算一遍
        assert only["keys"].get("in_pool11") is True, only["keys"]


def _picked_rule(css: str) -> str:
    """抠出 `.pool-picked{…}` 这条规则原文。"""
    i = css.index(".pool-picked{")
    return css[i:css.index("}", i) + 1]


def _picked_scroll_problems(css: str) -> list:
    """已选导弹那一列**不许自带滚动**（用户 2026-10-05：直接展开一放到底，页面/左栏自己滚）。"""
    rule = _picked_rule(css)
    bad = []
    if "max-height" in rule:
        bad.append("已选导弹那一列又带上 max-height 了")
    if "overflow" in rule:
        bad.append("已选导弹那一列又自己滚了（overflow）")
    return bad


def test_picked_list_has_no_scrollbar_of_its_own():
    """`#poolpicked` 自然高度全展开；左栏 `.rail-body` 的滚动保留（别把整栏也改成不滚）。"""
    css = _read(CSS)
    problems = _picked_scroll_problems(css)
    assert problems == [], problems
    assert ".pool-picked .pick{" in css, "已选导弹那几条的样式不该丢"
    assert ".rail-body{flex:1 1 auto;overflow-y:auto" in css, "左栏自己的滚动不许被一起删掉"


def test_picked_list_scroll_checker_has_teeth():
    """反证：把 `max-height` 加回 `#poolpicked` 必须被抓到。"""
    css = _read(CSS)
    assert _picked_scroll_problems(css) == []
    mutant = css.replace(".pool-picked{display:flex", ".pool-picked{max-height:200px;display:flex", 1)
    assert mutant != css, "反证没改到源码"
    assert _picked_scroll_problems(mutant), "加回 max-height 却抓不到：这条判据没有牙"



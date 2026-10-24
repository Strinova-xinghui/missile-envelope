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
FIGS2D = PAGE / "figs2d.js"
FIG3JS = PAGE / "fig3.js"

#: 左栏那份"想定输入"表里才有的字样：静态托管版一个都不该留（连注释里也不许）。
RAIL_BANNED = (
    "环境预设", "预置想定", "提交", "进度", "出哪张图", "后台任务", "后台",
    "忘记上次输入", "等时线步长", "参与散点的弹", "ΔV 步长", "BC 步长",
    "单工况试算", "只出图不扫描", "想定输入",
)
#: 发射参数那一节必须有的输入框 id（2026-10-23 照 StatShark 加进来；速度用公里/小时）。
LAUNCH_KEEP = ("sp-vm0", "sp-alt", "sp-pitch", "sp-heading", "sp-tspd", "sp-talt",
               "sp-range", "sp-tbear", "sp-thead", "sp-tpitch")
#: 弹池那一节必须有的元素 id —— StatShark 式：搜索框 + 右侧 ＋ + 候选 + 已选导弹。
#: 2026-10-24 用户口径：预设（仅主动弹）与「全选可算 / 清空」三个按钮**连同计数行一并删掉**，
#: 所以这里不再有 poolpresets / poolAll / poolClear / poolcount。
RAIL_KEEP = ("poolsearch", "pooladd", "poolcands", "poolnone", "poolsub", "poolpicked")
#: 页面里不许再有服务端占位符（`render_page()` 那套在托管环境里不存在）。
TOKEN_RE = re.compile(r"__[A-Z][A-Z_]*__")
#: 以 `/` 开头的 `src`/`href`（GitHub Pages 子路径下会指到域名根，直接裂）。
ABS_REF_RE = re.compile(r"""(?:src|href)\s*=\s*["']\s*/""", re.I)
#: 后端痕迹：接口路径与静态路由（两个都不许出现）。
# ⚠ 2026-10-05（W3a）**唯一**的放宽：允许"外接后端的配置引用"出现在被扫资产里 ——
#   · `./backend.js`：构建期**生成**的配置文件引用（它本身不进 `APP_ASSETS`，URL 字面量不落在资产里）；
#   · `window.__BACKEND__.api_base`：运行时拼 URL 的唯一来源。
# 放宽到**只有**这两样：`/api/`、`/static/`、任何硬编码第三方域名**继续禁**（静态站没有 `/static/`
# 这条路由，出现即死链；`/api/` 是同源后端路径 ⇒ 静态站必然 404）。
BACKEND_RE = re.compile(r"/api/|/static/")
BACKEND_ALLOWED_RE = re.compile(r"\./backend\.js|window\.__BACKEND__|__BACKEND__")
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
    """先摘掉**允许**的配置引用，再看还有没有 `/api/`、`/static/`。"""
    text = BACKEND_ALLOWED_RE.sub("", text)
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
        # ⚠ 2026-10-05（W3a）：`window.__BACKEND__` 是**契约冻结名**（构建期注入的外接后端配置，
        #   只在配置了后端时由 sitebuild 生成的 ./backend.js 提供）⇒ 这里唯一豁免它；
        #   其它 `__XXX__` 照旧禁（反证用 __SOLVER__ 钉着）。
        got = [x for x in got if x != "__BACKEND__"]
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
    * `fetch(` 只许出现在**两处**：① `poolFetchJson`（数据，URL 只有那两个同目录 JSON）；
      ② 外接后端的请求层（W3b 的等时线）—— 后者必须**只经 `APPBACKEND.url(...)` 拼 URL**，
      且被 `APPBACKEND.configured` 挡着（没配 `./backend.js` 时**一个请求都不发**）；
    * 不许别的东西（XHR / SSE / WebSocket / 轮询）—— 目录与图注读进来之后全是纯客户端。
    """
    html = _read(HTML)
    for tag in ('<script src="./catalog.js"></script>', '<script src="./notes.js"></script>'):
        assert tag in html, f"首页缺脚本载入的数据：{tag}"
    assert html.index('./catalog.js') < html.index('./app.js'), "数据脚本必须在 app.js 之前"
    assert html.index('./notes.js') < html.index('./app.js')
    js = _read(JS)
    code = _code_only(js)          # 注释里提到 fetch( 不算（口径同别处：注释不是代码）
    problems = _fetch_site_problems(code)
    assert problems == [], problems
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
    """左栏 = 弹池 + 发射参数两节；老输入表那套字样一条都不许留。

    ⚠ 2026-10-23 放宽：「静态版左栏只留弹池」那条旧口径作废 —— 用户要求照 StatShark
    把发射参数也放到左栏（见 docs/SITE-LAUNCH-PARAMS.md）。禁的仍是**服务端表单那套**
    （预设/提交/进度/后台/想定输入…），放行的只有 #sec-launch 这 10 个 sp-* 输入。
    """
    html = _read(HTML)
    for word in RAIL_BANNED:
        assert word not in html, f"首页里还留着「{word}」——静态版左栏只放弹池与发射参数"
    for word in RAIL_BANNED:
        assert word not in _read(JS), f"app.js 里还留着「{word}」"
    for el in RAIL_KEEP:
        assert f'id="{el}"' in html, f"弹池少了控件 #{el}"
    assert '<aside class="rail" id="rail">' in html, "左栏还是那条 rail（观感不变）"
    assert "rail-sec" in html and "field-row" in html, "沿用既有骨架与 field-row 观感"
    # 发射参数那一节（2026-10-23 新增）：10 个输入一个都不能少，且必须挂在 rail 里。
    assert 'id="sec-launch"' in html, "左栏缺发射参数那一节（#sec-launch）"
    launch = html[html.index('id="sec-launch"'):]
    launch = launch[:launch.index("</section>")]
    for el in LAUNCH_KEEP:
        assert f'id="{el}"' in launch, f"发射参数少了输入框 #{el}"
    assert "公里/小时" in launch, "速度输入要用公里/小时（照 StatShark，用户 2026-10-23 口径）"


# ------------------------------------------------------------ ⑨ 发射参数真的发出去


def test_scene_is_sent_on_every_request_path():
    """**三条**请求路径都必须带 scene：同步 overlay、等时面、**任务队列 /v1/jobs**。

    ⚠ 2026-10-24 实测抓到的真 bug：11 弹的池子（默认）网格太大，走的是 /v1/jobs
    那条**任务队列**，而它一开始没带 scene ⇒ 改发射参数后三张图纹丝不动、且不报错。
    只验「页面里有 sceneOf」抓不到这个 —— 必须逐条数调用点。
    """
    code = _code_only(_read(JS))
    assert "function sceneOf()" in code, "sceneOf 不见了"
    sent = code.count("scene: sceneOf()")
    assert sent == 3, (
        "带 scene 的请求点有 %d 处，应该是 3 处（/v1/overlay 同步、/v1/isosurface、/v1/jobs）" % sent)


def test_speed_inputs_are_kmh_and_converted_before_sending():
    """速度按**公里/小时**输入（用户 2026-10-23 口径），发出去换成 m/s（后端 Scene 吃 m/s）。"""
    html = _read(HTML)
    launch = html[html.index('id="sec-launch"'):]
    launch = launch[:launch.index("</section>")]
    # 只数**两个速度输入框的标签**（注释和脚注里也提到这四个字，不能整段 count）
    assert launch.count("<label>起始速度（公里/小时）") == 1, "起始速度没标公里/小时"
    assert launch.count("<label>目标速度（公里/小时）") == 1, "目标速度没标公里/小时"
    code = _code_only(_read(JS))
    assert "KMH = 3.6" in code or "KMH=3.6" in code, "缺 km/h -> m/s 的换算常数"
    body = _fn_body(_read(JS), "sceneOf")
    assert "/ KMH" in body, "sceneOf 里没把速度换成 m/s（后端会当成 1080 m/s）"


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


def test_pool_presets_and_bulk_buttons_are_gone():
    """**否定判据**（用户 2026-10-24 口径）：预设按钮与「全选可算 / 清空」及其渲染代码全部删掉。

    这几样是 2026-10-05 加的（当时左栏只放弹池，靠它们快速铺满 11 弹）。现在默认 0 弹、
    用户自己搜着加，它们既没用又占地方，而且和 statshark 不像 —— 所以连函数一起删，
    不留"页面没了但代码还在"的半吊子状态。
    """
    js = _read(JS)
    code = _code_only(js)
    html = _read(HTML)
    for gone in ('id="poolpresets"', 'id="poolAll"', 'id="poolClear"', "池预设"):
        assert gone not in html, f"页面里还有被删的控件 {gone}"
    for fn in ("function poolPresets(", "function poolPresetChips(", "function poolBuildPresets(",
               "function poolApplyPreset(", "function poolPresetKeys(", "function poolMatchRule(",
               "function poolPickAll(", "function poolClear(", "function poolAll("):
        assert fn not in code, f"被删的预设/批量函数还在：{fn}"
    assert "poolpresets" not in code and "#poolAll" not in code and "#poolClear" not in code
    # 默认选择必须是**空**（用户口径：载入时 0 弹），而且首屏不能再预选 in_pool11 那 11 枚
    body = _fn_body(code, "poolDefault")
    assert "return [];" in body, "默认弹池不是空的 —— 用户口径是载入 0 弹"
    assert "in_pool11" not in body, "poolDefault 又回去预选 11 弹了"
    # 存档键与删除单枚仍然在（二次进入时恢复上次列表的机制不变）
    assert 'POOL_KEY = "missile-sim:pool"' in js
    assert "localStorage.setItem(POOL_KEY" in code and "localStorage.getItem(POOL_KEY" in code
    assert "function poolRemove(" in js and "poolRemove(k)" in code


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
  ["shell", "railtoggle", "poollist", "msg"].forEach((i) => { els[i] = makeEl(i); });
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
  const anchor = "(saved.length > 0)";
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
             "pooladd", "poolstat", "poolpicked",
             "poolsearch", "poolrestored", "poolrestoredtext",
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
    sel: (els.poolpicked.children || []).length,
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
    staticHidden: [statics.plane.hidden, statics.bg.hidden],
    before: snap(),
  };
  if (mode === "action") {
    // 用户一动手（任何改选择的操作）⇒ 「已恢复」提示应当立刻收掉。
    // 2026-10-24：预设 / 全选 / 清空那三个按钮已删，改用「点 ✕ 删一枚」当动作
    // （走页面真控件：已选卡片上的那颗红圆 ✕）。
    // ⚠ 不能用「点候选行」：存的那枚很可能已经在已选里，
    //   那时点下去只会提示“已经在里面”，选择根本没变。
    function clickX() {
      var box2 = els.poolpicked;
      if (!box2.children.length) { return false; }
      var pick = box2.children[0];
      for (var i = 0; i < pick.children.length; i++) {
        var c = pick.children[i];
        if (c && c.className && String(c.className).indexOf("x") >= 0 && c.onclick) {
          c.onclick(); return true;
        }
      }
      return false;
    }
    out.clicked1 = clickX();
    out.after_action1 = snap();
    out.clicked2 = clickX();
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
    # 计数行（#poolcount）2026-10-24 已删 ⇒ 改数「已选导弹」里的卡片条数
    assert got["before"]["sel"] == 1, got["before"]
    assert got["notes"] == 2, got          # 图注来自 `window.__NOTES__`
    assert got["msg"] == "", "拿到数据了不该报错"
    assert got["staticHidden"] == [False, False], "没有渲染器时那份静态图必须还在"


def test_no_globals_and_no_fetch_falls_back_without_a_blank_page(tmp_path):
    """**反证**：把 `./catalog.js` 从页面拿掉（全局不存在）+ `file://` 下 fetch 失败 ⇒
    必须显示那行提示、保留静态图，**不许静默白屏**。"""
    got = _run_data_probe(tmp_path, "noglobals")
    assert got["fetches"] == ["./catalog.json", "./notes.json"], got["fetches"]
    assert "目录读不到" in got["msg"] and "file://" in got["msg"], got["msg"]
    assert "目录不可用" in got["stat"], got["stat"]
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
    assert got["before"]["sel"] == 2, got["before"]

    same = _run_data_probe(tmp_path, "seeded", store=TINY_DEFAULT)
    assert same["before"]["hintHidden"] is False, "存过 1 枚（非默认）就该提示"

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
    assert got["clicked1"] is True, got
    assert got["after_action1"]["sel"] == 1, got["after_action1"]   # 从 2 枚里删掉一枚


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




# ===================================================================== W3a：外接后端读取端

def test_backend_read_side_is_gated_and_never_hardcodes_urls():
    """外接后端的读取端必须**只看** `window.__BACKEND__`：没配置就什么都不做。

    * `app.js` 代码里**零** `/api/`、零硬编码域名（`http://` / `https://`）—— URL 只由 `api_base` 运行时拼；
    * 必须有 `enabled !== true` 的短路（无配置 / 未启用 ⇒ 直接 return）；
    * `./backend.js` 只以**相对**形式被引用（并且它是生成文件、不进 `APP_ASSETS`）；
    * `index.html` **不含**后端条元素（它由 app.js 运行时创建 ⇒ 无配置时页面逐字节等价）。
    """
    app_code = "\n".join(ln for ln in _read(JS).splitlines()
                         if not ln.lstrip().startswith(("//", "*", "/*")))
    assert "/api/" not in app_code, "app.js 里不许出现 /api/（URL 只能来自 api_base）"
    assert not re.search(r"https?://", app_code), "app.js 代码里不许出现硬编码域名"
    assert "enabled !== true" in app_code, "缺少 'enabled !== true ⇒ 短路' 的判断"
    assert "window.__BACKEND__" in app_code or "__BACKEND__" in app_code, "没有读 __BACKEND__"
    assert "api_base" in app_code, "没有用 api_base 拼 URL"
    assert "backend-bar" not in _read(HTML), "后端条不许写进 index.html（应由 app.js 运行时建）"
    print("[w3a] 读取端：只看 __BACKEND__、零 /api/、零硬编码域名、index.html 不含后端条 ✓")


def test_backend_gate_allows_only_the_config_reference_has_teeth():
    """反证：放宽**只有一条** —— 塞 `/api/x`、`/static/x.js`、`https://evil.example` 必须照旧被抓。"""
    assert _backend_refs("var a = window.__BACKEND__.api_base;") == [], "配置引用应被允许"
    assert _backend_refs('<script src="./backend.js"></script>') == [], "config 引用应被允许"
    for dirty in ('fetch("/api/catalog")', 'fetch("/static/x.js")',
                  'var u = "https://evil.example/v1/health";'):
        assert dirty.find("/api/") >= 0 or dirty.find("/static/") >= 0 or "evil" in dirty
    assert _backend_refs('fetch("/api/catalog")'), "/api/ 必须仍被抓"
    assert _backend_refs('load("/static/x.js")'), "/static/ 必须仍被抓"
    print("[w3a] 反证：放宽只覆盖配置引用，/api/ 与 /static/ 照旧被抓 ✓")


# ------------------------------------------------------------ W3b：fetch 三处的形状与守卫

def _fetch_site_problems(code: str) -> list:
    """`fetch(` 只许三处：`poolFetchJson`（数据）+ 后端请求层（等时线、等时面）。

    后端那两处的要求（**不是放宽**）：URL 只能由 `APPBACKEND.url(...)` 拼；并且调用路径被
    `APPBACKEND.configured` 挡着（没配 `./backend.js` ⇒ 一个请求都不发）。
    ⚠ 2026-10-05 切片 2：等时面（`/v1/isosurface`）加了第三处。**不是**把计数上限放开成"任意多" ——
    仍是逐个数（3），换一条 URL 或撤一道守卫照样红。
    """
    bad = []
    n = code.count("fetch(")
    #: 切片 3（线上 a7c1713）加了四处：估网格 ×2（开关路径 + 扫描路径）、后台任务 ×2（POST /v1/jobs、GET 轮询）。
    #: 上限跟着**逐个**数（7），不是"放开成任意多"——换一条 URL 或撤一道守卫照样红。
    if n != 7:
        bad.append(f"fetch( 应恰好七处（poolFetchJson + 等时线 + 等时面 + 估网格 ×2 + 任务 ×2），现在 {n} 处")
    if "fetch(url" not in code:
        bad.append("数据那处不见了（fetch(url …) 应在 poolFetchJson 里）")
    for path in ('/v1/overlay', '/v1/isosurface'):
        if f'fetch(APPBACKEND.url("{path}")' not in code:
            bad.append(f"后端那处没有走 APPBACKEND.url(...) 拼 URL（缺 {path}）")
    for path in ('/v1/estimate', '/v1/jobs'):
        if f'fetch(APPBACKEND.url("{path}' not in code:
            bad.append(f"切片 3 的后端那处没有走 APPBACKEND.url(...) 拼 URL（缺 {path}）")
    # 守卫：请求入口与刷新入口各一道（等时线与等时面各一对）
    for fn, need in (("isoRefresh", "if (!APPBACKEND.configured) { return; }"),
                     ("isoRequest", "if (!APPBACKEND.configured) { return; }"),
                     ("surfRefresh", "if (!APPBACKEND.configured) { return; }"),
                     ("surfRequest", "if (!APPBACKEND.configured) { return; }")):
        # ⚠ 同样必须**花括号配对**地抠整个函数体：`\n  }` 会在第一个 `.then(...)` 收尾处截断，
        #   后面的守卫就永远看不到（判据静默失效 —— 本轮切片 2 就踩过）。
        body = _fn_body_matched(code, fn)
        if need not in body:
            bad.append(f"{fn}() 少了 configured 守卫（没配后端也能被调 ⇒ 会发请求）")
    return bad


def test_backend_fetch_sites_are_guarded():
    """三处 `fetch` 的**形状**判据（配合数据那条一起看）。"""
    code = _code_only(_read(JS))
    problems = _fetch_site_problems(code)
    assert problems == [], problems


def test_backend_fetch_guard_checker_has_teeth():
    """反证：把 `configured` 守卫删掉、把 URL 改成硬编码、撤掉等时面那处 ⇒ 上面那条必须红。"""
    code = _code_only(_read(JS))
    assert _fetch_site_problems(code) == []
    for mutant in (code.replace("if (!APPBACKEND.configured) { return; }", "", 2),
                   code.replace("if (!APPBACKEND.configured) { return; }", "", 4),
                   code.replace("fetch(APPBACKEND.url(\"/v1/overlay\")",
                                "fetch(\"http://127.0.0.1:8099/v1/overlay\"", 1),
                   code.replace("fetch(APPBACKEND.url(\"/v1/isosurface\")", "", 1)):
        assert mutant != code, "反证没改到源码"
        assert _fetch_site_problems(mutant), "改坏了却抓不到 —— 这条判据没牙"


# ------------------------------------------------------- W3b 切片 2：等时面 + 时间滑块

#: 抠出 `function <name>(` 的**整个**函数体（花括号配对）。
#: ⚠ 不能用 `code.index("\n  }", i)` 那种切法：函数体里第一个 `.then(function (r) {…})`
#:   的收尾就长那样 ⇒ 体被截在半路，后面的作废校验/收面那几条永远看不到（判据静默失效）。
def _fn_body_matched(code: str, name: str) -> str:
    i = code.index("function " + name + "(")
    j = code.index("{", i)
    depth = 0
    for k in range(j, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return code[i:k + 1]
    raise AssertionError("function %s( 的花括号没配平" % name)


#: 等时面里"旧响应作废"那一行出现**几次**才算齐：成功回调一次 + `catch` 一次。
#: ⚠ 只查一次是不够的：`catch` 那一处漏了 ⇒ 出错信息会盖掉新选择的状态行（用户看到的是旧层级的报错）。
SURF_STALE_GUARD = "if (my !== surfTicket) { return; }"
SURF_STALE_GUARD_MIN = 2


def _surf_problems(code: str) -> list:
    """等时面这侧的**形状**要求（纯源码层，行为判据在下面的 node 桩里）。

    逐条对着 `docs/STAGE-C.md` §6：防抖、**旧响应作废**、`level_s` 进请求、单弹。
    """
    bad = []
    i = code.index("function surfRequest(")
    body = _fn_body_matched(code, "surfRequest")
    # ① 单弹：后端一次只算一枚，壳必须只送一个 key
    if "keys: [key]" not in body:
        bad.append("等时面请求没有把 keys 收成单枚（后端 `/v1/isosurface` 一次只算一枚）")
    # ② 层级必须进请求体（滑块改的就是它）
    for need in ("level_s:", "grid:"):
        if need not in body:
            bad.append(f"等时面请求体里没有 {need}")
    # ②b `level_s` 必须**取自滑块**（写死一个数 ⇒ 滑块形同虚设，这条要单独判）
    if "Number(lvl.value)" not in body:
        bad.append("等时面请求体的 level_s 没取自滑块（写死了层级 ⇒ 拖滑块不换面）")
    # ③ 防抖：滑块那条必须有 setTimeout，且等时线那处也一样
    if "setTimeout(function () { surfRequest(); }" not in code:
        bad.append("等时面没有防抖（拖滑块会连发，一格一次请求）")
    # ④ **旧响应作废**：请求入口发一张票，回来先验票（成功 + 失败**两处**都要验）
    if body.count(SURF_STALE_GUARD) < SURF_STALE_GUARD_MIN:
        bad.append("等时面没有作废旧响应（后到的会覆盖用户刚选的新层级；失败回调也要验票）")
    if "++surfTicket" not in body:
        bad.append("等时面没有发票（请求入口没 ++surfTicket ⇒ 作废无从判断）")
    # ⑤ 出错时收面 + 一行可读提示，静态功能仍在（不 throw 到壳）
    if "surfDraw(null);" not in body:
        bad.append("等时面失败时没收掉旧面（会留下一层与当前层级不符的三角网）")
    if "不影响其它功能" not in body:
        bad.append("等时面失败没有一行可读提示")
    # ⑥ 门面：图3 的挂载对象要暴露 setSurface（消费端在 fig3.js）
    return bad


def test_slice2_isosurface_request_layer_has_debounce_and_stale_guard():
    """切片 2 的请求层：单弹 + `level_s` + 防抖 + **旧响应作废**。"""
    code = _code_only(_read(JS))
    problems = _surf_problems(code)
    assert problems == [], problems
    # 图3 的消费端：门面多出 setSurface / surfaceInfo，且冻结接口没丢
    fig = _read(FIG3JS)
    for need in ("setSurface: function (res)", "surfaceInfo: function ()"):
        assert need in fig, f"fig3.js 的 mount 缺 {need}"
    assert "setSelection: function (keys)" in fig and "redraw: function ()" in fig, \
        "冻结接口被弄丢了（setSelection / redraw 必须还在）"


def test_slice2_checkers_have_teeth():
    """反证：撤掉防抖、撤掉作废校验、把单弹改回多弹、把层级写死 ⇒ 上面两条必须红。"""
    code = _code_only(_read(JS))
    assert _surf_problems(code) == []
    # ⚠ 撤作废校验时必须**锚在等时面那一层**：等时线那层用的是 `isoTicket[kind]`，形近而不同；
    #   `replace(…, 1)` 只改第一处 ⇒ 必须先确认锚点只出现于等时面（出现了两次 = 成功 + catch）。
    assert code.count(SURF_STALE_GUARD) == SURF_STALE_GUARD_MIN, code.count(SURF_STALE_GUARD)
    mutants = (
        # 撤掉旧响应作废的校验（成功回调那处）
        code.replace(SURF_STALE_GUARD, "", 1),
        # 撤掉旧响应作废的校验（catch 那处 —— 只撤一处也必须红）
        code.replace(SURF_STALE_GUARD, "", 1).replace(SURF_STALE_GUARD, "", 1),
        # 撤掉防抖
        code.replace("surfTimer = setTimeout(function () { surfRequest(); }, 250);",
                     "surfRequest();", 1),
        # 多弹（后端会 400：等时面一次只算一枚）
        code.replace("keys: [key]", "keys: POOL.sel.slice()", 1),
        # 层级不进请求体（滑块形同虚设）
        code.replace("level_s: Number(lvl.value) || 1", "level_s: 1", 1),
    )
    for mutant in mutants:
        assert mutant != code, "反证没改到源码"
        assert _surf_problems(mutant), "改坏了却抓不到 —— 上面那条判据没牙"


def _surf_mesh_problems(fig: str) -> list:
    """`surfaceBuffers` 必须按 `/v1/isosurface` 的 v1 形状读网格（空 = 通过）。"""
    bad = []
    if "spec.indices" not in fig:
        bad.append("索引数组没读 mesh.indices")
    if "spec.triangles" in fig:
        bad.append("把 mesh.triangles（三角形**个数**）当索引数组用了")
    if "function surfaceBuffers(" not in fig:
        return bad + ["fig3.js 里没有 surfaceBuffers（等时面消费端不见了）"]
    body = _fn_body_matched(fig, "surfaceBuffers")
    # 顶点数组是**三元组的数组** ⇒ 按行取 `V[T[t0]]`，不是展平的 `V[i * 3 + k]`
    #   （后者全读到 undefined ⇒ 顶点与颜色整片 NaN，画面上只是"面不见了"）
    for need in ("V[T[t0]]", "V[T[t0 + 1]]", "V[T[t0 + 2]]"):
        if need not in body:
            bad.append(f"等时面按行取顶点写错了（缺 {need}：mesh.vertices 是三元组的数组）")
    if re.search(r"V\[\s*T\[t0\]\s*\]\s*\*\s*3", body):
        bad.append("等时面把 mesh.vertices 当展平数组按 i*3 取了 ⇒ 顶点全 NaN")
    # 顶点按 (ΔV, β, ginv) 喂给 dataPos(d, beta, ginv, dv) ⇒ 必须重排成 (1, 2, 0)
    for need in ("dataPos(d, va[1], va[2], va[0])",
                 "dataPos(d, vb[1], vb[2], vb[0])",
                 "dataPos(d, vc[1], vc[2], vc[0])"):
        if need not in body:
            bad.append(f"顶点重排口径不对（{need}：mesh.vertices 是 (ΔV, β, ginv)，"
                       f"dataPos 吃 (beta, ginv, dv)）")
    # 绘制顺序：面夹在不写深度的时段里，且画在点之前
    if "if (B_LAYER.count)" not in fig or "if (B_HIT.count)" not in fig:
        bad.append("draw() 里少了 B_LAYER / B_HIT 的绘制分支")
    else:
        i_hit = fig.index("if (B_HIT.count)")
        i_layer = fig.index("if (B_LAYER.count)")
        if i_layer > i_hit:
            bad.append("等时面画在点之后了")
        if "gl.depthMask(false)" not in fig[i_layer:i_hit]:
            bad.append("等时面那一段必须夹在不写深度的时段里")
    if "B_LAYER.count ? 0.35 : 1.0" not in fig:
        bad.append("缺「有点时点变淡、无面时全不透明」那条口径")
    if "B_LAYER, B_HIT" not in fig:
        bad.append("B_LAYER 没进 MVP/blend 列表（面拿不到矩阵 ⇒ 画不出来或跑到错误位置）")
    return bad


def test_slice2_surface_reads_the_v1_mesh_contract():
    """`fig3.js` 必须按 `/v1/isosurface` 的 v1 形状读网格，**不是**老 `/api/fig3` 的那一套。

    这三个错都是切片 2 真实踩过的：**索引数组叫 `indices`（`triangles` 是三角形个数，当数组用
    得到空面）**、**顶点是数据坐标 `(ΔV, β, ginv)`**、**顶点数组是三元组的数组（不是展平数组）**。
    写错时**画面看着正常**（只是"面不见了"或"歪了一点"），不报错 ⇒ 只能靠源码形状
    + `-k fig3_static` 那条 node 数值判据钉住。
    """
    fig = _read(FIG3JS)
    problems = _surf_mesh_problems(fig)
    assert problems == [], problems
    # 反证：三个错各改一处都必须被抓到
    for mutant, why in (
        (fig.replace("spec.indices", "spec.triangles", 1), "索引取成 triangles"),
        (fig.replace("var va = V[T[t0]], vb = V[T[t0 + 1]], vc = V[T[t0 + 2]];",
                     "var va = V[T[t0] * 3], vb = V[T[t0 + 1] * 3], vc = V[T[t0 + 2] * 3];", 1),
         "顶点当展平数组取"),
        (fig.replace("dataPos(d, va[1], va[2], va[0])", "dataPos(d, va[0], va[1], va[2])", 1),
         "顶点没按 (ΔV,β,ginv) 重排"),
    ):
        assert mutant != fig, f"反证没改到源码：{why}"
        assert _surf_mesh_problems(mutant), f"改错了却抓不到（{why}）—— 这条判据没牙"


def test_slice1_overlay_hook_is_pure_drawing():
    """W3b 切片 1：`F.drawOverlay` 只做**裁剪 + 投影 + 落笔**（颜色只能来自 CSS/`style`）。"""
    js = _read(FIGS2D)
    assert "F.drawOverlay = function" in js, "缺 F.drawOverlay"
    i = js.index("F.drawOverlay = function")
    body = js[i:js.index("\n  };", i)]
    assert "F.visibleSeg(" in body, "没做框内裁剪（visibleSeg）"
    assert "F.project(" in body, "没走投影（project）"
    assert "'class': 'iso-line'" in body or '"class": "iso-line"' in body, "等时线要带 iso-line 类"
    for bad in ("#", "rgb(", "hsl("):
        assert bad not in body, f"drawOverlay 里出现色值字面量：{bad}"
    # 两个渲染器都落笔、mount 暴露 setOverlay/axis 且不破坏冻结接口
    assert js.count("axis.isoDrawn = F.drawOverlay(") == 2, "两个渲染器都要画等时线"
    mount = js[js.index("F.mount = function"):]
    for need in ("setSelection: function (keys)", "redraw: function ()",
                 "setOverlay: function (o)", "axis: function ()"):
        assert need in mount, f"mount 返回对象缺 {need}"
    css = _read(CSS)
    assert ".iso-line{" in css and "stroke-dasharray" in css, "等时线样式应在 CSS 里（虚线）"


def test_no_backend_config_means_zero_requests():
    """**最要紧那条**：没配 `./backend.js`（没有 `window.__BACKEND__`）⇒ 一个请求都不发。

    两层证据：① 源码层 —— 请求入口都有 `APPBACKEND.configured` 守卫；
    ② 行为层 —— node 桩探针里 `fetch` 一次都没被调（`test_data_comes_from_the_globals_with_zero_fetch`
    断言的 `fetches == []` 现在同时覆盖了外接后端这条路）。
    """
    code = _code_only(_read(JS))
    assert code.count("if (!APPBACKEND.configured) { return; }") >= 4, \
        "四个入口（等时线/等时面 × 请求/刷新）都得有 configured 守卫"
    html = _read(HTML)
    assert "./backend.js" not in html, "首页不该无条件引 backend.js（构建期有配置才注入）"


# ------------------------------------------- 切片 2 的**行为**判据（node 桩后端，§6 ②④）

#: 桩后端的一批"等时面响应"：`mesh.vertices` 是数据坐标 (ΔV, β, ginv)，`indices` 是索引数组
#: （`triangles` 是**个数** —— 切片 2 的第一个坑就是把它当数组用）。
SURF_PROBE_JS = r"""
const fs = require('fs');
const vm = require('vm');
const appSrc = fs.readFileSync(process.argv[2], 'utf8');
const mode = process.argv[3];

// ---- 一个三角形（数据坐标 (ΔV, β, ginv)）：贴在 β = 0 的面上
function meshFor(level, dv, bc, ginv) {
  return {vertices: [[dv, bc - 0.1, ginv - 0.1], [dv, bc + 0.1, ginv - 0.1], [dv, bc, ginv + 0.1]],
          indices: [0, 1, 2], triangles: 1, level: level};
}
// 记录画到 fig3 视图上的面（替身：`setSurface` 只记账，不碰 WebGL）
const drawn = [];
const fig3view = {
  setSelection: function () {}, redraw: function () {},
  setSurface: function (res) {
    drawn.push({level: res && res.level_s, tris: res && res.mesh ? res.mesh.triangles : 0});
    return drawn[drawn.length - 1].tris;
  },
  surfaceInfo: function () { return {tris: drawn.length ? drawn[drawn.length - 1].tris : 0, level: null}; },
};

// ---- fetch 桩：**可控的到达顺序**（反证④要的就是这个）
const sent = [];
let resolveFns = [];      // 每个请求一个 resolve（乱序释放）
function stubFetch(url, opts) {
  sent.push({url: String(url), body: JSON.parse(opts.body)});
  return new Promise(function (res) { resolveFns.push(res); });
}
function settle(i, payload, status) {
  // ⚠ `status` 不给时**必须**真的落成 200：`status < 400` 在 `undefined` 上是 false（NaN 比较）
  //   ⇒ `ok` 变 false ⇒ 前端报 "HTTP 200"（这种自相矛盾的状态串最容易把人带偏）。
  const st = (status === undefined || status === null) ? 200 : status;
  resolveFns[i]({ok: st < 400, status: st,
                 json: function () { return Promise.resolve(payload); }});
}
// ⚠ app.js 一加载就要 `document`（`var $ = document.querySelector`）⇒ 这里给一份**极简** DOM：
//   只提供它在这条路径上真正用到的那几个方法，别的返回 null（够不够由探针自己暴露出来）。
function makeEl(id) {
  const classes = new Set();
  const kids = {length: 0};
  const el = {
    id: id, hidden: false, title: '', value: '', checked: false, disabled: false,
    min: '', max: '', step: '', type: '', href: '', htmlFor: '', className: '',
    style: {}, children: kids, onclick: null, oninput: null, onchange: null,
    classList: {has: (c) => classes.has(c), contains: (c) => classes.has(c),
                 add: (c) => classes.add(c), remove: (c) => classes.delete(c),
                 toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) { classes.add(c); } else { classes.delete(c); } }},
    setAttribute: () => {}, getAttribute: () => null, removeAttribute: () => {},
    appendChild: (c) => { kids[kids.length] = c; kids.length += 1; return c; },
    insertBefore: (c) => { kids[kids.length] = c; kids.length += 1; return c; },
    addEventListener: () => {}, removeEventListener: () => {},
    querySelector: () => null, querySelectorAll: () => [],
  };
  Object.defineProperty(el, 'textContent', {
    get: () => el._text || '', set: (v) => { el._text = String(v); kids.length = 0; },
  });
  return el;
}
const IDS = ['body', 'shell', 'railtoggle', 'msg', 'poolcands', 'poolnone', 'poolsub',
             'pooladd', 'poolstat', 'poolpicked',
             'poolsearch', 'poolrestored', 'poolrestoredtext',
             'fig1host', 'fig1box', 'fig1notes', 'fig2host', 'fig2box', 'fig2notes',
             'fig3host', 'fig3fallback', 'fig3notes'];
const els = {};
IDS.forEach((i) => { els[i] = makeEl(i); });
const document = {
  // ⚠ `$()` 传的**有的带 `#`、有的不带**（`$("body")` 就是裸标签名）⇒ 两种都要认。
  querySelector: (s) => (s ? (els[s.replace(/^#/, '')] || null) : null),
  querySelectorAll: () => [],
  createElement: (t) => makeEl(t),
  createTextNode: (t) => ({textContent: String(t)}),
  addEventListener: () => {},
  body: els.body, documentElement: makeEl('html'),
};
const sandbox = {console: console, document: document, fetch: stubFetch,
                 setTimeout: setTimeout, clearTimeout: clearTimeout,
                 localStorage: {getItem: () => null, setItem: () => {}, removeItem: () => {}},
                 Promise: Promise, JSON: JSON, Math: Math, Number: Number, String: String,
                 Object: Object, Array: Array, isFinite: isFinite, URLSearchParams: URLSearchParams};
sandbox.window = {__BACKEND__: {api_base: 'http://stub.invalid', enabled: true},
                  __CATALOG__: {ok: true, schema: 1, standard: 'PL-12',
                                style: {point_color: '#D32F2F', base_color: '#388E3C'},
                                missiles: [{key: 'PL-12', label: 'PL-12', in_pool11: true,
                                            duplicate_of: null, default_hidden: false,
                                            dv: 932.6, bc: 3078.1, ginv: 0.01767}],
                                presets: [], unsupported: []},
                  __NOTES__: {fig1: [], fig2: []}};
sandbox.window.fetch = stubFetch;
sandbox.globalThis = sandbox;
vm.runInNewContext(appSrc, sandbox, {filename: 'app.js'});

// ⚠ `poolBoot()` 是**异步**的：它在 `setTimeout` 里建 `POOL.views`（`poolMount3d()` 会往里写）。
//   ⇒ 替身视图必须等它跑完再注入，否则会被它整份覆盖掉（`poolMount3d` 失败 ⇒ `views.fig3 = null`）。
function installFig3View() {
  const POOL = sandbox.POOL;
  POOL.sel = ['PL-12'];
  POOL.catalog = sandbox.window.__CATALOG__;
  POOL.views = {plane: null, bg: null, fig3: fig3view};
}

setTimeout(() => {
  installFig3View();
  const B = sandbox.window.APPBACKEND;
  const out = {sent: sent, drawn: drawn, status: []};

  // ---- ① 开关等时面 ⇒ 发一次请求，body 形状对（单弹 + level_s + tier + grid）
  B.surfToggle.checked = true;
  B.surfaceRefresh();
  setTimeout(() => {
    out.sentAfterOpen = sent.length;
    if (sent.length) { out.firstBody = sent[0].body; out.firstUrl = sent[0].url; }
    if (sent.length) {
      settle(0, {kind: 'fig3', level_s: 45, key: 'PL-12',
                 mesh: meshFor(45, 932.6, 3078.1, 0.01767),
                 identity: {cached: false, elapsed_ms: 12, backend: 'compiled-c'}});
    }
    setTimeout(() => {
      out.drawnAfterFirst = drawn.slice();
      out.statusAfterFirst = B.status.textContent;

      // ---- ② 滑块改层级 ⇒ **必须再发一次新请求**（body 里的 level_s 变了）
      B.levelInput.value = '42';
      B.levelInput.onchange();
      setTimeout(() => {
        out.sentAfterSlider = sent.length;
        out.sliderBody = sent.length > 1 ? sent[sent.length - 1].body : null;

        // ---- ③ 防抖：连着动滑块（3 次，只算最后一次）⇒ 只多发 1 次，不是 3 次
        const before = sent.length;
        B.levelInput.value = '50'; B.levelInput.onchange();
        B.levelInput.value = '55'; B.levelInput.onchange();
        B.levelInput.value = '60'; B.levelInput.onchange();
        setTimeout(() => {
          out.sentAfterBurst = sent.length - before;
          out.lastBody = sent.length ? sent[sent.length - 1].body : null;

          // ---- ④ 反证：**乱序到达** —— 先发出去的（55/50 那批里先到的那次）后到，
          //      不许覆盖新选择。这条是最容易漏的：用户快速拖滑块，后端慢的那次后到。
          //      这里连发两次、**先释放第 1 次（更老的请求）**，看它有没有把画面改回去。
          const mark = drawn.length;
          const n = sent.length;
          B.levelInput.value = '70'; B.levelInput.onchange();      // 发第 n 次（老）
          setTimeout(() => {
            B.levelInput.value = '80'; B.levelInput.onchange();    // 发第 n+1 次（新）
            setTimeout(() => {
              // 先放**老**的（第 n 次）—— 正常网络下完全可能
              settle(n, {kind: 'fig3', level_s: 70, key: 'PL-12',
                         mesh: meshFor(70, 932.6, 3078.1, 0.01767),
                         identity: {cached: false, elapsed_ms: 99, backend: 'compiled-c'}});
              setTimeout(() => {
                out.afterOldArrived = drawn.slice(mark);
                // 再放**新**的（第 n+1 次）
                settle(n + 1, {kind: 'fig3', level_s: 80, key: 'PL-12',
                               mesh: meshFor(80, 932.6, 3078.1, 0.01767),
                               identity: {cached: true, elapsed_ms: 3, backend: 'compiled-c'}});
                setTimeout(() => {
                  out.afterNewArrived = drawn.slice(mark);
                  out.finalStatus = B.status.textContent;

                  // ---- ⑤ 后端 500 ⇒ 一行可读错误 + 旧面收掉，静态功能仍在
                  const before500 = sent.length;
                  B.levelInput.value = '90'; B.levelInput.onchange();
                  setTimeout(() => {
                    settle(before500, {detail: 'boom'}, 500);
                    setTimeout(() => {
                      out.status500 = B.status.textContent;
                      out.drawnAfter500 = drawn.slice(-1);
                      console.log(JSON.stringify(out));
                    }, 40);
                  }, 330);
                }, 40);
              }, 40);
            }, 330);
          }, 330);
        }, 330);
      }, 330);
    }, 40);
  }, 330);
}, 30);
"""


def _run_surface_probe(tmp_path) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器没有 node，跳过等时面行为探针（源码级契约仍在上面几条）")
    script = Path(tmp_path) / "surface_probe.js"
    script.write_text(SURF_PROBE_JS, encoding="utf-8")
    proc = subprocess.run([node, str(script), str(JS)], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    assert proc.returncode == 0, f"等时面探针跑挂了：\n{proc.stderr[-2000:]}"
    return json.loads(proc.stdout)


def test_slice2_surface_draws_and_slider_reissues_with_debounce(tmp_path):
    """§6 ②：等时面按预期绘制；滑块改 `level_s` 会发新请求；连动**只发一次**（防抖）。"""
    got = _run_surface_probe(tmp_path)
    assert got["sentAfterOpen"] == 1, got["sent"]
    # URL 只能由 api_base 运行时拼（这里后端只有一个路由 ⇒ 末尾就是它）
    assert got["firstUrl"].endswith("/v1/isosurface"), got["firstUrl"]
    body = got["firstBody"]
    assert body["keys"] == ["PL-12"], body           # ⚠ 一次一枚（后端 400 的那道）
    assert body["level_s"] == 45, body                # 滑块初值
    assert body["tier"] in ("standard", "fast"), body
    assert isinstance(body["grid"], int) and body["grid"] >= 2, body
    # 响应到了就真的画上去了（不是只发请求）
    assert got["drawnAfterFirst"] and got["drawnAfterFirst"][-1]["tris"] == 1, got["drawnAfterFirst"]
    # 滑块改层级 ⇒ 新请求，且 level_s 真的进了 body
    assert got["sentAfterSlider"] == 2, got["sent"]
    assert got["sliderBody"]["level_s"] == 42, got["sliderBody"]
    # 防抖：连动三次只多发一次
    assert got["sentAfterBurst"] == 1, (got["sentAfterBurst"], got["sent"])
    assert got["lastBody"]["level_s"] == 60, got["lastBody"]


def test_slice2_out_of_order_response_cannot_overwrite_the_new_choice(tmp_path):
    """§6 ④（反证）：**后到的旧响应必须作废** —— 快速拖滑块时慢的那次不许把画面改回去。"""
    got = _run_surface_probe(tmp_path)
    # 老请求（level 70）先到 ⇒ 一个字都不许画
    assert got["afterOldArrived"] == [], got["afterOldArrived"]
    # 新请求（level 80）到 ⇒ 画上去，且状态栏说的是它
    assert got["afterNewArrived"] and got["afterNewArrived"][-1]["level"] == 80, got["afterNewArrived"]
    assert "80" in got["finalStatus"], got["finalStatus"]


def test_slice2_backend_error_is_one_readable_line_and_surface_is_dropped(tmp_path):
    """§6 ③：后端 500 ⇒ 一行可读错误 + **收掉旧面**，散点照常（静态功能仍在）。"""
    got = _run_surface_probe(tmp_path)
    status = got["status500"]
    assert "等时面拿不到" in status and "500" in status, status
    assert "不影响其它功能" in status, status
    # 失败时把面收掉：最后一条绘制记录是 tris=0（没有残留三角网）
    assert got["drawnAfter500"] and got["drawnAfter500"][-1]["tris"] == 0, got["drawnAfter500"]


def test_slice2_probe_would_notice_a_missing_stale_guard(tmp_path):
    """反证**探针本身有牙**：把作废校验改掉，同一个探针必须看到旧响应被画上去。"""
    src = _read(JS)
    mutant = src.replace("if (my !== surfTicket) { return; }", "", 1)
    assert mutant != src, "反证没改到源码"
    js2 = Path(tmp_path) / "app_mutant.js"
    js2.write_text(mutant, encoding="utf-8")
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器没有 node")
    script = Path(tmp_path) / "surface_probe.js"
    script.write_text(SURF_PROBE_JS, encoding="utf-8")
    proc = subprocess.run([node, str(script), str(js2)], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    assert proc.returncode == 0, proc.stderr[-2000:]
    got = json.loads(proc.stdout)
    assert got["afterOldArrived"], "把作废校验去掉后探针**照样过** ⇒ 这条行为判据是空的"

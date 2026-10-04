# -*- coding: utf-8 -*-
"""静态托管版首页（`Static` 分支）：左栏只留弹池，整页零服务端。

判据**不依赖任何 Python 服务** —— 托管环境里没有后端，所以这里直接读那三个文件
（`webui_static/index.html` / `app.css` / `app.js`）的文本，外加数据文件里的相对引用。

四条主判据（对应派单）：
  ① 零 `/api`、零 `/static`、零以 `/` 开头的 `src|href`（GitHub Pages 子路径 + Cloudflare 都要能跑）；
  ② 左栏只剩弹池：那份"想定输入"表的字样一个都不许再出现（禁用词逐条断）；
  ③ 三张卡片各有宿主容器、`_static` 回落 `<img>`、三个相对下载链接、`./method.html` 入口；
  ④ 弹池四个动作（清空 / 全选 / 仅 11 弹 / 删除单枚）在 JS 里都有具名函数。

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
#: 弹池那一节必须有的元素 id（左栏只剩它）。
RAIL_KEEP = ("poollist", "poolsearch", "poolpicked", "poolcount",
             "pool11", "poolAll", "poolClear")
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
    """静态页不许留 `__TOKEN__`：托管环境里没有 Python 去替换它们。"""
    for p in (HTML, CSS, JS):
        got = TOKEN_RE.findall(_read(p))
        assert got == [], f"{p.name} 里还有服务端占位符：{got}"


def test_no_server_placeholders_has_teeth():
    """反证：往首页里塞一个占位符，上面那条判据必须红。"""
    html = _read(HTML)
    assert TOKEN_RE.findall(html) == []
    assert TOKEN_RE.findall(html + "\n<p>__SOLVER__</p>"), "占位符正则抓不到东西"


def test_data_comes_from_two_relative_json_files_only():
    """整份脚本只有两次 `fetch`，都是同目录的静态 JSON —— 不许别的数据来源。"""
    js = _read(JS)
    assert js.count("fetch(") == 2, js.count("fetch(")
    assert 'fetch("./catalog.json"' in js and 'fetch("./notes.json"' in js
    # 目录/图注一次读入后就不再发请求（`setSelection` 是纯客户端）
    assert "XMLHttpRequest" not in js and "EventSource" not in js and "WebSocket" not in js


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


def test_four_pool_actions_have_named_functions():
    """清空 / 全选 / 仅 11 弹 / 删除单枚 —— 四个动作各有一个具名函数，且都接到按钮上。"""
    js = _read(JS)
    for fn in ("function poolClear(", "function poolPickAll(", "function poolPick11(",
               "function poolRemove("):
        assert fn in js, f"缺具名动作 {fn}"
    assert '$("#poolClear").onclick = poolClear;' in js
    assert '$("#poolAll").onclick = poolPickAll;' in js
    assert '$("#pool11").onclick = poolPick11;' in js
    assert "poolRemove(k)" in js, "已选 chips 上的 × 要调用 poolRemove"
    # 默认选中来自目录的 `in_pool11`（壳里不写死弹名），存档键沿用既有命名
    assert "in_pool11" in js and "poolEntries()" in js
    for name in ("PL-12", "MICA", "AAM-4", "120C"):
        assert f'"{name}"' not in js, f"壳里写死了弹名 {name}"
    assert 'POOL_KEY = "missile-sim:pool"' in js
    assert "localStorage.setItem(POOL_KEY" in js and "localStorage.getItem(POOL_KEY" in js


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
    for hint in ("目录（./catalog.json）没读到", "fig3.js 里没有 FIG3STATIC"):
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


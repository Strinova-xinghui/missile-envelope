"use strict";
// ============================================================================
// 静态托管版首页的壳（GitHub Pages / Cloudflare 直接丢上去就能跑）。
//
// 三条硬口径：
//   1. **零后端**：数据只有两条来路，都是**同目录**的静态件 ——
//      ① 脚本标签载入的全局：`./catalog.js`（`window.__CATALOG__`，全弹池派生目录 + 图面样式）
//         与 `./notes.js`（`window.__NOTES__`，图注文本，单一出处）；
//      ② 托管退路：`fetch("./catalog.json")` / `fetch("./notes.json")`，**只在对应全局缺失时**才发。
//      `file://` 双击打开时浏览器按跨源拦掉 `fetch()` 读本地文件，所以 ① 是那条路上的唯一来路。
//      除此之外没有相对服务器发起的任何调用，也没有轮询。
//   2. **渐进增强**：目录/渲染器缺任何一件 ⇒ 卡片保持 HTML 里那份静态图（`img.static`）+
//      一行提示；不隐藏、不删、不改名。
//   3. **选择由壳管**：静态层（`window.FIGS2D` / `window.FIG3STATIC`）不落状态、不发请求，
//      只接受 `setSelection(keys)`；key 就是目录里的 `key`。
//
// 这一节里的类名与 `app.css` / `figs2d.css` 是同一套设计语言（亮色、圆角、chip）。
// ============================================================================

var $ = function (s) { return document.querySelector(s); };

// 一行提示（页面顶部那条）。静态站没有服务端，所有异常都在这里如实说。
function msg(text, cls) {
  var el = $("#msg");
  if (!el) { return; }
  el.textContent = text || "";
  el.className = cls ? ("msg " + cls) : "";
  el.hidden = !text;
}

// `textContent` 赋值（目录里的名字来自数据，一律不当 HTML 用）。
function setText(el, text) {
  if (el) { el.textContent = text === null || text === undefined ? "" : String(text); }
}

// ---------------------------------------------------------------- 左栏折叠

var RAIL_KEY = "missile-sim:rail";
function applyRail(collapsed) {
  var shell = $("#shell");
  if (!shell) { return; }
  shell.classList.toggle("rail-collapsed", !!collapsed);
  var b = $("#railtoggle");
  if (b) { b.textContent = collapsed ? "›" : "‹"; b.setAttribute("aria-expanded", collapsed ? "false" : "true"); }
}
function railStartCollapsed() {
  var v;
  try { v = localStorage.getItem(RAIL_KEY); } catch (e) { v = null; }
  if (v === "1") { return true; }
  if (v === "0") { return false; }
  return (window.innerWidth || 1200) < 980;
}
if ($("#railtoggle")) {
  applyRail(railStartCollapsed());
  $("#railtoggle").onclick = function () {
    var next = !($("#shell") && $("#shell").classList.contains("rail-collapsed"));
    applyRail(next);
    try { localStorage.setItem(RAIL_KEY, next ? "1" : "0"); } catch (e) {}
  };
}

// ---------------------------------------------------------------- 对比弹池

var POOL_KEY = "missile-sim:pool";
var POOL = {catalog: null, notes: null, sel: [], current: null, menu: false, restoredOnce: false,
            standard: '', views: {}};   // standard = 基准弹（绿标），用户可在左栏换一枚

function poolEntries() {
  // 候选列表 = 可算且默认要显示的那些：目录里 `duplicate_of` 的另一半是孪生（`*_default`）
  return ((POOL.catalog || {}).missiles || []).filter(function (m) {
    return m && m.key && !m.duplicate_of && !m.default_hidden;
  });
}
function poolUnsupported() { return ((POOL.catalog || {}).unsupported || []); }
function poolLabel(m) { return String((m && (m.label || m.key)) || ""); }
function poolDefault() {
  // 用户 2026-10-24 口径：**首次打开是 0 弹**。这里就是"默认选择"的唯一定义处，
  // 别退回"预选 in_pool11 那 11 枚"——那会让下面「已恢复」的判据跟着错。
  return [];
}
function poolSave(keys) {
  try { localStorage.setItem(POOL_KEY, JSON.stringify(keys)); } catch (e) {}
}
// 两组 key 是不是同一套（无序比较）。
function poolSameSet(a, b) {
  var x = (a || []).map(String), y = (b || []).map(String);
  if (x.length !== y.length) { return false; }
  var want = {};
  y.forEach(function (k) { want[k] = 1; });
  for (var i = 0; i < x.length; i++) { if (!want[x[i]]) { return false; } }
  return true;
}
// 「已恢复你上次的弹池 N 枚」——**只在页面打开那一下**算一次：存过、且存的不是默认 11 弹才亮。
// 此后**再也不重算**（用户 2026-10-05 口径：它不该老是挂着 —— 加了弹之后"已恢复"就不成立了）。
function poolRestoredOnce() {
  var box = $("#poolrestored");
  var saved = poolStored();
  // 用户 2026-10-05 口径：**存的为空数组**（用户点过「清空」）视同"没存过" ——
  // 别在首帧写「已恢复你上次的弹池 0 枚」，那读着像个 bug。
  // 默认池现在是**空**（用户 2026-10-24 口径）⇒ "存的和默认一样"只剩"存的也是空"这一种，
  // 而那种又被下面的 saved.length > 0 挡掉了。所以这里只判"存过、且不是空"就够。
  var show = (saved !== null) && (saved.length > 0);
  POOL.restoredOnce = show;
  if (box) { box.hidden = !show; }      // 两个分支都显式写，别靠 DOM 的初始值
  if (show) { setText($("#poolrestoredtext"), "已恢复你上次的弹池 " + saved.length + " 枚"); }
}
// 用户一动手（任何改变选择的操作）⇒ 立刻收掉，本次会话内不再出现。
function poolHideRestored() {
  if (!POOL.restoredOnce) { return; }
  POOL.restoredOnce = false;
  var box = $("#poolrestored");
  if (box) { box.hidden = true; }
}
function poolStored() {
  var raw;
  try { raw = localStorage.getItem(POOL_KEY); } catch (e) { return null; }
  if (!raw) { return null; }
  var arr;
  try { arr = JSON.parse(raw); } catch (e) { return null; }
  if (!Array.isArray(arr)) { return null; }
  var known = {};
  poolEntries().forEach(function (m) { known[String(m.key)] = 1; });
  return arr.map(String).filter(function (k) { return known[k]; });
}
function poolStat(text) {
  var el = $("#poolstat");
  if (!el) { return; }
  el.hidden = !text;
  setText(el, text || "");
}
// 候选列表（StatShark 式）：**左对齐**一列，一条一行；点某条 ⇒ 它成为"当前选中"（高亮），
// 再点搜索框右侧的 ＋ 才把它加进下方「已选导弹」。不可算的那几条照样列出、置灰、悬停给原因。
function poolRowName(m) {
  // 名字用 `full_name`；与 `native` 相同时就用 `native`（目录里两栏都可能缺）
  var full = String((m && m.full_name) || "").trim();
  var native = String((m && (m.native || m.key)) || "").trim();
  if (full && native && full !== native) { return full; }
  return full || native || String((m && m.key) || "");
}
function poolMakeRow(m, off) {
  var row = document.createElement("div");
  row.className = off ? "pool-row off" : "pool-row";
  row.setAttribute("data-key", String(m.key));
  var nm = document.createElement("span");
  nm.className = "nm";
  setText(nm, poolRowName(m));
  row.appendChild(nm);
  var tag = document.createElement("span");
  tag.className = "tag";
  setText(tag, m.seeker);
  row.appendChild(tag);
  if (off) {
    var why = document.createElement("span");
    why.className = "why";
    setText(why, m.reason || "不可算");
    row.appendChild(why);
    row.title = String(m.reason || "") + (m.kernel_reason ? "　原因：" + m.kernel_reason : "");
  } else {
    var label = poolRowName(m);
    row.title = label === String(m.key) ? label : (label + "（" + String(m.key) + "）");
    row.onclick = function () { poolPickCurrent(String(m.key)); };
  }
  return row;
}
// 候选面板：**只在下拉打开时**渲染（StatShark 同款：搜索框 -> 弹出 -> 选定 -> 加入）。
// 常驻长列表已经去掉：104 条铺开会把左栏挤满，而用户 90% 的时间只用搜索。
function poolBuildRows() {
  var list = $("#poolcands");
  if (!list) { return; }
  list.textContent = "";
  poolEntries().forEach(function (m) { list.appendChild(poolMakeRow(m, false)); });
  poolUnsupported().forEach(function (m) { list.appendChild(poolMakeRow(m, true)); });
  poolShowCurrent();
}
// 候选面板的开关（StatShark 的下拉）：打开才显示，选完/点外面收起。
function poolMenuOpen(open) {
  var wrap = $("#poolwrap"), list = $("#poolcands");
  if (!wrap || !list) { return; }
  POOL.menu = (open === undefined) ? !POOL.menu : !!open;
  wrap.className = POOL.menu ? "pool-wrap open" : "pool-wrap";
  list.hidden = !POOL.menu;
  var none = $("#poolnone");
  if (none && !POOL.menu) { none.hidden = true; }
}

// 点候选 = **直接加入已选导弹**（StatShark 那种「选定即生效」），并收起候选面板。
// 不再需要「先选中、再点 ＋」两步：多一步就多一次误操作的机会。
function poolPickCurrent(key) {
  var k = String(key || "");
  if (!k) { return; }
  POOL.current = k;
  poolShowCurrent();
  poolAddCurrent();
}
function poolShowCurrent() {
  var btn = $("#pooladd");
  document.querySelectorAll("#poolcands .pool-row").forEach(function (row) {
    var k = String(row.getAttribute("data-key"));
    var on = (!!POOL.current && k === POOL.current);
    row.className = row.className.replace(/\s*\bon\b/, "") + (on ? " on" : "");
  });
  if (btn) { btn.disabled = !POOL.current; }
}
// ＋：把当前选中加入「已选导弹」，加完清空选中、收起面板、清空搜索框。
function poolAddCurrent() {
  var k = POOL.current;
  if (!k) { return; }
  if (POOL.sel.indexOf(k) >= 0) { poolStat(poolRowName(poolEntryOf(k)) + " 已经在已选导弹里了。"); }
  else { poolAdd(k); }
  POOL.current = null;
  poolShowCurrent();
  var s2 = $("#poolsearch");
  if (s2) { s2.value = ""; }
  poolFilter("");
  poolMenuOpen(false);
}

function poolEntryOf(key) {
  var hit = null;
  poolEntries().forEach(function (m) { if (String(m.key) === String(key)) { hit = m; } });
  return hit;
}
// 折叠 `-` / `_` / 空白：目录 key 是 `us_aim_120a` 这种名，用户会打 "aim-120"。
function poolFold(text) {
  return String(text || "").toLowerCase().replace(/[\s_-]+/g, "");
}
// 搜索：**键入即筛**；有关键词就展开候选面板（StatShark 的输入即弹出），空关键词只显示前若干条。
// 匹配顺序：名字从头命中 > 名字任意位置命中 > 其它字段命中 —— 用户打 "pl12" 要最先看到 PL-12。
function poolFilter(text) {
  var q = poolFold(text);
  var list = $("#poolcands");
  if (!list) { return; }
  var rows = [];
  document.querySelectorAll("#poolcands .pool-row").forEach(function (row) { rows.push(row); });
  var scored = [];
  var shown = 0;
  rows.forEach(function (row, idx) {
    var nmEl = row.querySelector(".nm");
    var nm = poolFold(nmEl ? nmEl.textContent : "");
    var hay = poolFold(String(row.getAttribute("data-key") || "") + " "
                       + (nmEl ? nmEl.textContent : "") + " " + (row.title || ""));
    var rank = -1;
    if (!q) { rank = 9; }
    else if (nm.indexOf(q) === 0) { rank = 0; }
    else if (nm.indexOf(q) > 0) { rank = 1; }
    else if (hay.indexOf(q) >= 0) { rank = 2; }
    row.hidden = (rank < 0);
    if (rank >= 0) { shown += 1; scored.push({row: row, rank: rank, idx: idx}); }
  });
  // 命中的按 rank 重排（稳定的第二键 = 原序），这样最相关的排最上面
  scored.sort(function (a, b) { return (a.rank - b.rank) || (a.idx - b.idx); });
  scored.forEach(function (it) { list.appendChild(it.row); });
  var none = $("#poolnone");
  if (none) { none.hidden = shown > 0; }
  if (q) { poolMenuOpen(true); }
  if (q) { poolStat(""); }
}

// 「已选导弹」：**左对齐一列**，每枚右侧一个红色 ✕（删除单枚 = `poolRemove`）；空列表给一行提示。
// 照 statshark 实测（2026-10-24 截图对比）：每条是**一整块 Material filled 卡片** ——
// 上面一行 11px 灰标签「已选导弹」，下面 16px 深色弹名，名字右侧一颗圆形 ⓘ，
// 卡片右缘外面**骑着一颗红色圆形 ✕**（删除单枚 = poolRemove）。基准弹那颗换成绿色左边框 +「基准」。
function poolPicked() {
  var box = $("#poolpicked");
  if (!box) { return; }
  box.textContent = "";
  var byKey = {};
  poolEntries().forEach(function (m) { byKey[String(m.key)] = m; });
  var base = poolStandard();
  if (!POOL.sel.length) {
    var none = document.createElement("span");
    none.className = "none";
    setText(none, "还没选，点上面 ＋ 添加。");
    box.appendChild(none);
    return;
  }
  POOL.sel.forEach(function (k) {
    var m = byKey[k];
    var pick = document.createElement("div");
    pick.className = "pick" + (k === base ? " base" : "");
    var card = document.createElement("div");
    card.className = "card";
    var tag = document.createElement("span");
    tag.className = "tag";
    setText(tag, "已选导弹");
    card.appendChild(tag);
    var line = document.createElement("div");
    line.className = "line";
    var nm = document.createElement("b");
    setText(nm, m ? poolRowName(m) : k);
    line.appendChild(nm);
    if (k === base) {
      var mark = document.createElement("span");
      mark.className = "base";
      setText(mark, "基准");
      line.appendChild(mark);
    }
    // ⓘ：与 statshark 同位置的小圆标（这里给的是目录里的出处/可算性，不弹窗）
    var info = document.createElement("span");
    info.className = "info";
    setText(info, "i");
    info.title = m ? (poolRowName(m) + "（" + String(m.key) + "）"
                     + (m.seeker ? "　导引头：" + String(m.seeker) : ""))
                   : String(k);
    line.appendChild(info);
    card.appendChild(line);
    pick.appendChild(card);
    var x = document.createElement("button");
    x.type = "button";
    x.className = "x";
    x.setAttribute("data-remove", k);
    x.title = "从已选导弹里去掉 " + (m ? poolRowName(m) : k);
    setText(x, "✕");
    x.onclick = function () { poolRemove(k); };
    pick.appendChild(x);
    box.appendChild(pick);
  });
}
function poolMark() {
  var want = {};
  POOL.sel.forEach(function (k) { want[k] = 1; });
  // 已在已选里的候选：淡一点（`in`）——它不是"当前选中"（`on`，那个由 poolShowCurrent 管）
  document.querySelectorAll("#poolcands .pool-row").forEach(function (row) {
    var k = String(row.getAttribute("data-key"));
    var has = row.className.indexOf("in") >= 0;
    if (!!want[k] && !has) { row.className += " in"; }
    if (!want[k] && has) { row.className = row.className.replace(/\s*\bin\b/, ""); }
  });
  // 用户 2026-10-24 口径：预设（仅主动弹）与「全选可算 / 清空」三个按钮全部删掉，
  // 计数那一行也一起收掉（它本来就挂在那一排上）。已选数量改由「已选导弹」小标题右边那枚角标显示。
  poolPicked();
  poolShowCurrent();
  poolSync();
  poolSyncBase();
  poolBaseOptions();
}
// ---- 基准弹（2026-10-23 用户口径：基准弹与它的绿标要回来）--------------------
// 目录里的 standard 是默认基准弹（DEFAULT_MISSILE）；用户可以在左栏换一枚，三张图一起跟着变。
// 渲染器的 style.base 就是这一枚：figs2d / fig3 据此把它画成 base_color（绿）+ 标注「基准」。
var STD_KEY = "missile-sim:standard";
function poolStandardDefault() {
  return String(((POOL.catalog || {}).standard) || "");
}
function poolStandard() {
  var known = {};
  poolEntries().forEach(function (m) { known[String(m.key)] = 1; });
  if (POOL.standard && known[POOL.standard]) { return POOL.standard; }
  var d = poolStandardDefault();
  return known[d] ? d : "";
}
function poolSetStandard(key, user) {
  POOL.standard = String(key || "");
  if (user) { try { localStorage.setItem(STD_KEY, POOL.standard); } catch (e) {} }
  poolSyncBase();
  poolPicked();
  if (APPBACKEND.invalidate) { APPBACKEND.invalidate("基准弹变了"); }
}
function poolSyncBase() {
  var key = poolStandard();
  ["plane", "bg"].forEach(function (k) {
    var v = POOL.views[k];
    if (v && typeof v.setBase === "function") { try { v.setBase(key); } catch (e) {} }
  });
  var v3 = POOL.views.fig3;
  if (v3 && typeof v3.setBase === "function") { try { v3.setBase(key); } catch (e) {} }
}
// 基准弹下拉：选项 = 已选导弹（基准弹必须在池里，否则它根本不会画出来）。
function poolBaseOptions() {
  var sel = $('#poolbase');
  if (!sel) { return; }
  var cur = poolStandard();
  var byKey = {};
  poolEntries().forEach(function (m) { byKey[String(m.key)] = m; });
  sel.textContent = '';
  POOL.sel.forEach(function (k) {
    var o = document.createElement('option');
    o.value = String(k);
    setText(o, byKey[k] ? poolRowName(byKey[k]) : String(k));
    if (String(k) === cur) { o.selected = true; }
    sel.appendChild(o);
  });
  if (!POOL.sel.length) {
    var o2 = document.createElement('option');
    o2.value = '';
    setText(o2, '先选导弹');
    sel.appendChild(o2);
  }
  sel.value = cur;
}

// 唯一的"改选择"入口：存档 → 同步四处状态 → 交给三张图。
function poolSet(keys, user) {
  var known = {};
  poolEntries().forEach(function (m) { known[String(m.key)] = 1; });
  POOL.sel = (keys || []).map(String).filter(function (k) { return known[k]; });
  if (user) { poolHideRestored(); }     // 用户一动手（加/删/预设/全选/清空）⇒ 那条提示立刻收掉
  if (user) { poolSave(POOL.sel); }
  poolMark();
  if (APPBACKEND.invalidate) { APPBACKEND.invalidate("已选导弹变了"); }   // 已画的层是旧清单的 ⇒ 收掉
}
function poolRemove(key) {
  poolSet(POOL.sel.filter(function (k) { return k !== String(key); }), true);
}
function poolAdd(key) {
  var want = POOL.sel.slice();
  if (want.indexOf(String(key)) < 0) { want.push(String(key)); }
  poolSet(want, true);
}

// ---------------------------------------------------------------- 三张图的挂载

// 图注：文本来自 `./notes.json`（单一出处）。壳只负责摆位置、不写文案。
function notesFor(kind) {
  var n = POOL.notes || {};
  var title = String(n.title || "");
  var lines = (kind === "bg" ? n.fig2 : n.fig1) || [];
  var out = [];
  if (title) { out.push(title); }
  (lines || []).forEach(function (t) { out.push(String(t)); });
  return out;
}
function notesInto(kind) {
  var isBg = (kind === "bg");
  var ul = $(isBg ? "#fig2notes" : "#fig1notes");
  var sum = $(isBg ? "#fig2notestitle" : "#fig1notestitle");
  var n = POOL.notes || {};
  if (sum) { setText(sum, n.title || "图注"); }
  if (!ul) { return; }
  ul.textContent = "";
  var lines = (isBg ? n.fig2 : n.fig1) || [];
  if (!lines.length) {
    var li = document.createElement("li");
    setText(li, (POOL.notes === null) ? "图注读不到（notes.json 不在同目录）。" : "这一版没带图注文本。");
    ul.appendChild(li);
    return;
  }
  lines.forEach(function (t) {
    var li = document.createElement("li");
    setText(li, t);
    ul.appendChild(li);
  });
}
function poolHostList() {
  return [{kind: "plane", box: $("#fig1box"), host: $("#fig1host")},
          {kind: "bg", box: $("#fig2box"), host: $("#fig2host")}];
}
function poolMount() {
  var F = window.FIGS2D;
  var bad = [];
  if (!F || typeof F.mount !== "function") {
    return ["画平面图的脚本（figs2d.js）没加载"];
  }
  poolHostList().forEach(function (h) {
    if (!h.host || !h.box) { return; }
    try {
      POOL.views[h.kind] = F.mount(h.host, {kind: h.kind, catalog: POOL.catalog, notes: notesFor(h.kind), base: poolStandard()});
      var st = h.box.querySelector("img.static");
      if (st) { st.hidden = true; }         // 有实时形态了，静态回落那份让位（元素留着，不删）
    } catch (e) {
      POOL.views[h.kind] = null;
      bad.push(h.kind + "：" + ((e && e.message) || e));
    }
  });
  return bad;
}
// 图3：同一套选择喂给三维层。接口是冻结的 `mount(host, {catalog, style})`。
function poolMount3d() {
  var host = $("#fig3host"), fb = $("#fig3fallback");
  var G = window.FIG3STATIC;
  if (!host) { return "这一版没有图3 的宿主容器"; }
  if (!G || typeof G.mount !== "function") {
    if (fb) { fb.hidden = false; }
    return "fig3.js 里没有 FIG3STATIC（卡片里留了一行说明）";
  }
  try {
    POOL.views.fig3 = G.mount(host, {catalog: POOL.catalog, style: (POOL.catalog || {}).style, base: poolStandard()});
    if (fb) { fb.hidden = true; }     // 三维视图起来了 ⇒ 那行说明让位（元素留着，不删）
    return null;
  } catch (e) {
    POOL.views.fig3 = null;
    if (fb) { fb.hidden = false; }
    return "图3 的三维视图没起来：" + ((e && e.message) || e);
  }
}
// 选择变了 ⇒ 一次性同步给三张图（静态层只认 key）。
function poolSync() {
  var keys = POOL.sel.slice();
  ["plane", "bg", "fig3"].forEach(function (k) {
    var v = POOL.views[k];
    if (v && typeof v.setSelection === "function") {
      try { v.setSelection(keys); } catch (e) {}
    }
  });
}

// ---------------------------------------------------------------- 目录/图注 → 页面

// 目录/图注的两条来路：
//   ① **脚本标签载入的全局**（`./catalog.js` / `./notes.js`，由组装方生成）—— `file://` 双击打开时
//      浏览器按跨源把 `fetch()` 本地文件拦掉，**只有这条路能走**；
//   ② `fetch("./catalog.json")` / `fetch("./notes.json")` —— 托管环境可能只发 JSON，或想省一个请求时走这条。
// 先看全局；缺哪一半才为那一半发一次 fetch；两条都没拿到才回落到静态图 + 一行提示（不静默白屏）。
function poolFetchJson(url) {
  return fetch(url, {headers: {"Accept": "application/json"}})
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; });      // `file://` 下会直接抛 ⇒ 一律当"没有"
}
function poolLoadData() {
  var cat = window.__CATALOG__ || null;
  var notes = window.__NOTES__ || null;
  var catReq = cat ? Promise.resolve(cat) : poolFetchJson("./catalog.json");
  var notesReq = notes ? Promise.resolve(notes) : poolFetchJson("./notes.json");
  return Promise.all([catReq, notesReq]);
}
function poolBoot() {
  // 左栏的接线：搜索框 + 右侧 ＋（预设/全选/清空 2026-10-24 按用户口径删掉了）
  if ($("#pooladd")) { $("#pooladd").onclick = poolAddCurrent; }
  if ($("#poolsearch")) { $("#poolsearch").oninput = function () { poolFilter(this.value); }; }
  // 候选面板的开关（2026-10-23）：聚焦即展开（StatShark 输入即弹出），Esc / 点外面收起。
  if ($("#poolsearch")) {
    $("#poolsearch").onfocus = function () { poolMenuOpen(true); poolFilter(this.value); };
    $("#poolsearch").onkeydown = function (e) {
      if (e && e.key === "Escape") { poolMenuOpen(false); if (e.preventDefault) { e.preventDefault(); } }
    };
  }
  if ($("#pooltoggle")) {
    $("#pooltoggle").onclick = function () { poolMenuOpen(); poolFilter($("#poolsearch") ? $("#poolsearch").value : ""); };
  }
  if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("click", function (e) {
      var wrap = $("#poolwrap");
      if (!wrap || !POOL.menu) { return; }
      var t = e && e.target;
      while (t) { if (t === wrap) { return; } t = t.parentNode; }
      poolMenuOpen(false);
    });
  }

  poolLoadData().then(function (got) {
    var cat = got[0], notes = got[1];
    POOL.notes = notes;
    notesInto("plane");
    notesInto("bg");
    if (!cat || cat.ok === false) {
      // 目录拿不到：整页回落到 HTML 里那份静态图，只报一行；**不去任何服务器找数据**
      msg("目录读不到（`catalog.js` 的全局与 `./catalog.json` 都没有）—— 页面回落到静态图；"
          + "双击 `file://` 打开时请用脚本载入的数据（`./catalog.js`），或起个本地 http 服务。", "err");
      poolStat("目录不可用 —— 把 catalog.js / notes.js（或 catalog.json / notes.json）"
               + "与 figures/ 放在页面同一个目录下。");
      return;
    }
    POOL.catalog = cat;
    poolBuildRows();
    var bad2d = poolMount();
    var bad3 = poolMount3d();
    var saved = poolStored();
    try { POOL.standard = localStorage.getItem(STD_KEY) || ''; } catch (e) { POOL.standard = ''; }
    // 用户 2026-10-24 口径：**首次打开时是 0 弹**（不再预选 11 弹）；存过什么就恢复什么。
    poolSet(saved === null ? [] : saved, false);
    if ($('#poolbase')) {
      $('#poolbase').onchange = function () { poolSetStandard(this.value, true); };
    }
    // 提示行只在这一下亮/不亮，之后由用户操作决定（本次会话不再重算）
    poolRestoredOnce();
    var hints = [];
    if (bad2d.length) { hints.push("图1/图2 的实时形态没装上（" + bad2d.join("；") + "）—— 卡片上是静态图"); }
    if (bad3) { hints.push("图3 的三维层还没加载（" + bad3 + "）—— 图1/图2 不受影响"); }
    poolStat(hints.join("；"));
  }).catch(function (e) {
    msg("读目录时出错：" + ((e && e.message) || e), "err");
  });
}
poolBoot();

// ============================================================================ 外接后端（可选 · 构建期注入）
// 机制（Lead 2026-10-05 定稿）：`sitebuild.build_static_app()` **只在配置了后端时**生成一份
// `./backend.js`（`window.__BACKEND__ = {api_base, enabled}`）并在 index.html 里以**相对路径**引入；
// **没配置就完全不引用** ⇒ 下面这一节整段不执行：不建 DOM、不发请求，页面与今天逐字节等价。
// 纪律：URL 只许由 `__BACKEND__.api_base` 在**运行时**拼；本文件不出现同源后端路径、不出现硬编码域名。
var APPBACKEND = { configured: false, apiBase: "" };

(function backendBoot() {
  var b = (typeof window !== "undefined") ? window.__BACKEND__ : null;
  if (!b || b.enabled !== true || typeof b.api_base !== "string" || !b.api_base) {
    return;                                   // ⚠ 无配置 / 未启用 ⇒ 直接返回（W3a 到此为止）
  }
  var base = b.api_base.replace(/\/+$/, "");
  APPBACKEND = { configured: true, apiBase: base, url: function (p) { return base + p; } };
  if (typeof window !== "undefined") { window.APPBACKEND = APPBACKEND; }
  var host = $("body");
  if (!host) { return; }
  // 后端条（2026-10-24 用户口径：改成**两个模式**，默认「弹道」）：
  //   模式 A 弹道（默认）—— 只算所选这几枚的飞行轨迹，在图1 的位置画成三维轨迹集合；
  //   模式 B 扫描 —— 承接原有的等时线 / 等时面（用户必须显式切过去）。
  // 两个模式共用同一颗「开始计算」，按当前模式分派；后端控件 #backend-iso / #backend-surface /
  // #backend-level 的名字与语义**不变**，只是被收进「扫描」这组里（切到弹道时整组隐藏）。
  var bar = document.createElement("div");
  bar.className = "backend-bar";
  // ---- 模式切换（单选）：默认选中「弹道」 ----
  var modeWrap = document.createElement("span");
  modeWrap.className = "backend-modes";
  var modeTraj = document.createElement("input");
  modeTraj.type = "radio"; modeTraj.name = "backend-mode"; modeTraj.id = "backend-mode-traj";
  modeTraj.value = "traj"; modeTraj.checked = true;
  var modeTrajL = document.createElement("label");
  modeTrajL.htmlFor = "backend-mode-traj"; modeTrajL.textContent = "弹道";
  modeTrajL.title = "只算所选导弹的飞行轨迹（三维）";
  var modeScan = document.createElement("input");
  modeScan.type = "radio"; modeScan.name = "backend-mode"; modeScan.id = "backend-mode-scan";
  modeScan.value = "scan";
  var modeScanL = document.createElement("label");
  modeScanL.htmlFor = "backend-mode-scan"; modeScanL.textContent = "扫描";
  modeScanL.title = "等时线 / 等时面（原有功能）";
  modeWrap.appendChild(modeTraj); modeWrap.appendChild(modeTrajL);
  modeWrap.appendChild(modeScan); modeWrap.appendChild(modeScanL);
  bar.appendChild(modeWrap);
  // ---- 扫描这组（等时线 + 等时面 + 时间滑块）：切到弹道时整组隐藏，DOM 与 id 都不动 ----
  var scanBox = document.createElement("span");
  scanBox.className = "backend-scanbox";
  var on = document.createElement("input");
  on.type = "checkbox"; on.id = "backend-iso";
  var lab = document.createElement("label");
  lab.htmlFor = "backend-iso"; lab.textContent = "等时线";
  var step = document.createElement("input");
  step.type = "number"; step.id = "backend-iso-step"; step.min = "1"; step.step = "1"; step.value = "1";
  scanBox.appendChild(on); scanBox.appendChild(lab); scanBox.appendChild(step);
  // 等时面（W3b 切片 2）：开关 + 时间滑块（`level_s`）+ 网格密度。一行，跟等时线并排。
  // ⚠ 只有配了后端才会走到这里（上面 `enabled !== true` 已经 return）⇒ 无配置时 DOM 与今天逐字节等价。
  var sf = document.createElement("input");
  sf.type = "checkbox"; sf.id = "backend-surface";
  var sfl = document.createElement("label");
  sfl.htmlFor = "backend-surface"; sfl.textContent = "等时面";
  var lvl = document.createElement("input");
  lvl.type = "range"; lvl.id = "backend-level"; lvl.min = "1"; lvl.max = "90"; lvl.step = "1"; lvl.value = "45";
  var lvln = document.createElement("span");
  lvln.className = "backend-leveln"; lvln.textContent = "45 s";
  scanBox.appendChild(sf); scanBox.appendChild(sfl); scanBox.appendChild(lvl); scanBox.appendChild(lvln);
  bar.appendChild(scanBox);
  var st = document.createElement("span");
  st.className = "backend-status"; st.textContent = "后端已配置，未连接";
  bar.appendChild(st);
  // 「开始计算」（切片 3）：显式跑一轮扫描 —— 等时线（plane + bg，用已选清单）+ 等时面（当前一枚），
  // 按勾选。多弹网格会超同步上限（实测 3 枚 plane = 1032 工况 > 400）⇒ 估网格先行，大格自动改走
  // `/v1/jobs` 任务队列 + 轮询（docs/STAGE-C.md §3 的 v1 接口，后端 8dc6ed7 已有）。
  var run = document.createElement("button");
  run.type = "button"; run.id = "backend-run"; run.className = "backend-run";
  run.textContent = "开始计算";
  bar.appendChild(run);
  // 插到**展示区标题之下、第一张卡片之前**（2026-10-23 改版）：以前插在 `body` 最前面，
  // 新骨架的顶栏是 sticky 的 ⇒ 那一行会被顶栏压住/挤到页头外面。落点由 `#workbench` 兜底。
  var anchor = $("#workbench");
  if (anchor && anchor.parentNode) {
    anchor.parentNode.insertBefore(bar, anchor.nextSibling);
  } else {
    host.insertBefore(bar, host.firstChild);
  }
  // 顶栏状态：配了后端就点亮「后端已配置」，并把状态行的文字同步给 #viewhint。
  var pill = $("#tierpill");
  if (pill) { pill.textContent = "后端"; }
  var hint = $("#viewhint");
  if (hint) { hint.textContent = "已连接 " + base.replace(/^https?:\/\//, ""); }
  var pillState = $("#viewstate");
  if (pillState) { pillState.className = "statepill live"; pillState.textContent = "可叠加等时线"; }
  APPBACKEND.toggle = on; APPBACKEND.stepInput = step; APPBACKEND.status = st;
  APPBACKEND.surfToggle = sf; APPBACKEND.levelInput = lvl; APPBACKEND.levelLabel = lvln;
  APPBACKEND.runBtn = run;
  APPBACKEND.grid = 5;                       // 每轴采样数（= 后端 `DEFAULT_CUBE_N`；5 ⇒ 125 顶点）

  // ============================================ 两个模式（2026-10-24 用户口径）
  // 默认「弹道」：只算所选这几枚的**飞行轨迹**，在图1 的位置画成三维轨迹集合（像空战沙盒那样能转）。
  // 另一个「扫描」：承接原有的等时线 / 等时面 —— 用户必须显式切过去，控件才露出来。
  // 纪律：两个模式共用同一把 busy 闸（一次只跑一件事）；弹道模式下没选弹 ⇒ 「开始计算」禁用，
  // 绝不发空请求；请求失败 ⇒ 图1 回落那张静态图 + 一行可读提示，页面不白屏。
  var MODE = {cur: "traj"};                  // "traj" | "scan"
  var busy = false;
  function trajKeys() {
    return (typeof POOL !== "undefined" && POOL.sel) ? POOL.sel.slice() : [];
  }
  function syncRun() {
    run.disabled = busy || (MODE.cur === "traj" && !trajKeys().length);
    modeTraj.disabled = busy; modeScan.disabled = busy;
  }
  APPBACKEND.mode = function () { return MODE.cur; };

  // ---- 图1 卡片抬头随模式换（三维轨迹 vs 能力平面）：只改这两行文本，DOM 不增删 ----
  var HEAD0 = null;
  function headEls() {
    var h2 = document.querySelector("#fig1 .cardtitle h2");
    var p = document.querySelector("#fig1 .cardtitle p");
    if (h2 && p && !HEAD0) { HEAD0 = {h2: h2.textContent, p: p.textContent}; }
    return {h2: h2, p: p};
  }
  function syncCardHead() {
    var e = headEls();
    if (!e.h2 || !e.p || !HEAD0) { return; }
    if (MODE.cur === "traj") {
      e.h2.textContent = "弹道轨迹";
      e.p.textContent = "所选导弹的三维飞行轨迹 · 可拖拽旋转";
    } else {
      e.h2.textContent = HEAD0.h2;
      e.p.textContent = HEAD0.p;
    }
  }

  // ---- 三维轨迹层：宿主 / 说明 / 图例都由这里运行时建（没配后端 ⇒ 一个节点都不建） ----
  var trajHost = null, trajCap = null, trajLegend = null, trajView = null, trajDead = false;
  var trajTicket = 0, trajDrawn = 0, trajFailed = [];
  function trajStaticImg() {
    var box = $("#fig1box");
    return (box && box.querySelector) ? box.querySelector("img.static") : null;
  }
  function trajStyle() {
    // 配色一律取目录 style（与两张平面图同一套）；背景/强调色取 CSS 变量，本文件不新增色值。
    var s = ((typeof POOL !== "undefined" && POOL.catalog && POOL.catalog.style) || {});
    function cssVar(name, dflt) {
      try {
        var root = (typeof window !== "undefined" && window.document) ? window.document.documentElement : null;
        var v = (root && window.getComputedStyle) ? window.getComputedStyle(root).getPropertyValue(name) : "";
        return String(v || "").trim() || dflt;
      } catch (e) { return dflt; }
    }
    return {
      bg: cssVar("--card", ""),
      grid: s.grid_major || "",
      line: s.point_color || "",
      axisX: s.point_color || "", axisY: s.base_color || "", axisZ: s.nstar_color || "",
      point: s.point_color || "", base: s.base_color || "", text: s.text || ""
    };
  }
  // 一枚弹的颜色：基准弹 = 目录 base_color（绿）；其余同色相派生深浅（不新增色相）。
  function trajColorOf(key, idx, total, st) {
    // 基准弹 = 目录 standard（用户可在左栏换）⇒ 用 base_color（绿）。poolStandard() 已经
    // 把"用户选的那枚还在不在池里"折进去了，别再自己读 POOL.standard（空串会顶掉目录默认值）。
    var base = String(poolStandard() || "");
    if (key && key === base) { return st.base; }
    var c = st.point;
    var T = (typeof window !== "undefined") ? window.TRAJFAN : null;
    if (!T || typeof T.mixHex !== "function" || total < 2) { return c; }
    // 同色相派生深浅（不引入任何新色值字面量）：往目录里的 text 色混，6 档拉开到 0.65，
    // 这样 11 枚同池时相邻两条也能分得开（图例与线色是同一个来源）。
    var k = 0.13 * (idx % 6);
    return T.mixHex(c, st.text || c, k);
  }
  function trajInsert(node) {
    var box = $("#fig1box");
    if (!box) { return; }
    var img = trajStaticImg();
    if (img && img.parentNode === box) { box.insertBefore(node, img); } else { box.appendChild(node); }
  }
  // ⚠ 两种失败要分开（2026-10-24）：硬失败 = 这一层根本起不来（脚本没加载 / 没有 WebGL2），
  //   之后不必再试；软失败 = 这一次请求没成（网络、后端 500、点列形状不对），下一次点「开始计算」
  //   必须还能画 —— 把软失败也钉成 trajDead 会让用户"失败一次之后永远画不出来"。
  function trajResetView() {
    if (trajHost) { trajHost.hidden = true; }
    if (trajCap) { trajCap.hidden = true; }
    if (trajLegend) { trajLegend.hidden = true; trajLegend.textContent = ""; }
    var img = trajStaticImg();
    if (img) { img.hidden = false; }        // 回落：图1 仍然有图（不白屏）
    cardState("fig1state", "静态 · 标称点", false);
  }
  function trajFail(text) {
    trajResetView();
    isoStatus(text, true);
  }
  function trajDeadFail(text) {            // 硬失败：层/GL 不可用，之后不再重试
    trajDead = true;
    trajFail(text);
  }
  function trajMount() {
    if (trajView) { return trajView; }
    if (trajDead) { return null; }
    var box = $("#fig1box");
    if (!box) { return null; }
    var T = (typeof window !== "undefined") ? window.TRAJFAN : null;
    if (!T || typeof T.mount !== "function") {
      trajDeadFail("三维轨迹层没加载（traj3d.js 不在同目录）—— 图1 仍是静态图，其它功能照常");
      return null;
    }
    trajCap = document.createElement("p");
    trajCap.className = "traj3d-cap";
    trajCap.textContent = "三维飞行轨迹：左键拖拽旋转 / 滚轮缩放 / 右键或 Shift 拖拽平移 / 双击复位";
    trajHost = document.createElement("div");
    trajHost.className = "traj3d-host";
    trajHost.id = "traj3dhost";
    trajLegend = document.createElement("div");
    trajLegend.className = "traj3d-legend";
    trajInsert(trajCap);
    trajInsert(trajHost);
    trajInsert(trajLegend);
    var v = null;
    try { v = T.mount(trajHost, {chrome: trajStyle()}); } catch (e) { v = null; }
    if (!v || !v.available || !v.available()) {
      trajDeadFail("这台浏览器或当前环境不支持 WebGL2 —— 图1 回落静态图，其它功能照常");
      return null;
    }
    trajView = v;
    return v;
  }
  function trajShow3D(on) {
    if (trajHost) { trajHost.hidden = !on; }
    if (trajCap) { trajCap.hidden = !on; }
    if (trajLegend) { trajLegend.hidden = !on; }
    // 卡片里只留一张图：三维轨迹起来时，平面图的宿主与静态回落都让位（元素留着，不删）。
    var host2d = $("#fig1host");
    if (host2d) { host2d.hidden = !!on; }
    var img = trajStaticImg();
    if (!img) { return; }
    if (on) { img.hidden = true; return; }
    // 收掉三维：只有平面图也没挂上时才把静态图放回来（否则会盖在实时 SVG 上面）
    var pv = (typeof POOL !== "undefined" && POOL.views) ? POOL.views.plane : null;
    img.hidden = !!pv;
  }
  // 后端响应 → 三维轨迹。
  // 点列口径（Lead 2026-10-24 实测）：`[t, x, y, z, v]`，y = 高度、z 是第二个水平轴。
  // 不拿 range 当纵轴：range 是"到目标的剩余距离"（50000 → 0），画出来是反着长的。
  // 只有 3 列（老的 `[t, range, v]`）⇒ 明确说清，不假装画得出来。
  function trajDraw(payload) {
    var cases = (payload && payload.cases) || [];
    var img = trajStaticImg();
    if (!cases.length) {
      if (trajView) { trajView.clear(); }
      if (trajLegend) { trajLegend.textContent = ""; }
      trajDrawn = 0;
      trajShow3D(false);
      if (img) { img.hidden = false; }
      cardState("fig1state", "静态 · 标称点", false);
      // ⚠ 状态行必须换掉：否则它会永远停在「正在算 …」，用户以为还在跑（2026-10-24 真浏览器抓到）。
      isoStatus("后端没返回任何轨迹（所选导弹都不在它的弹池里？）—— 图1 仍是静态图，其它功能照常", true);
      return 0;
    }
    var view = trajMount();
    if (!view) { return 0; }
    var st = trajStyle(), series = [], thin = 0, failed = [];
    cases.forEach(function (c, i) {
      var key = String((c && (c.key || c.label)) || "");
      // ⚠ 单个 case 可以自带 error（那一条算失败，整批不算）—— 后端 2026-10-24 的契约：
      //   "未知 key -> 400；内核不支持 -> 400；单个 case 里也可能带 error"。整批当失败会让
      //   一枚不支持就把其余十条本该画出来的轨迹一起吞掉。
      if (c && c.error) { failed.push((c.label || key) + "：" + c.error); return; }
      // 点列是 5 列 [t, x, y, z, v]：**直接用第 2/3/4 个元素**当世界系坐标（米），不再换算，
      // 也不去取第 6 个（没有 mach 列）。y 是高度、z 在默认迎头场景恒 0（那是物理，不是 bug）。
      var pts = [], raw = (c && c.points) || [];
      for (var j = 0; j < raw.length; j++) {
        var p = raw[j];
        if (!p || !p.length) { continue; }
        if (p.length < 4) { thin += 1; continue; }
        var x = +p[1], y = +p[2], z = +p[3];
        if (!isFinite(x) || !isFinite(y) || !isFinite(z)) { continue; }
        pts.push([x, y, z]);
      }
      if (pts.length < 2) { failed.push((c.label || key) + "：点数不足"); return; }
      series.push({key: key, label: String((c && (c.label || c.key)) || key),
                   color: trajColorOf(key, i, cases.length, st), points: pts});
    });
    if (!series.length) {
      trajFail(thin
        ? "后端返回的是两维点列（[t, 距离, 速度]）—— 三维轨迹需要 [t, x, y, z, v]；图1 回落静态图"
        : ("后端没给出可画的轨迹点" + (failed.length ? "（" + failed.join("；") + "）" : "")
           + "；图1 回落静态图，其它功能照常"));
      return 0;
    }
    var n = view.setSeries(series);
    trajDrawn = n;
    if (trajLegend) {
      trajLegend.textContent = "";
      series.forEach(function (s) {
        var sp = document.createElement("span");
        var i2 = document.createElement("i");
        i2.style.background = s.color;                  // 颜色来自目录 style（不是新色值）
        var tx = document.createElement("b");
        tx.textContent = s.label || s.key;
        tx.style.fontWeight = "500";
        sp.appendChild(i2);
        sp.appendChild(tx);
        trajLegend.appendChild(sp);
      });
    }
    trajShow3D(true);
    cardState("fig1state", "弹道 · 轨迹 " + n + " 条" + (failed.length ? "（" + failed.length + " 条失败）" : ""),
              true);
    trajFailed = failed.slice();
    return n;
  }
  // 弹道请求：POST /v1/trajectory（body {keys, tier, scene}），一次拿全（11 枚约 2.5 s）。
  function trajRequest() {
    if (!APPBACKEND.configured) { return; }      // 闸门：没配后端 ⇒ 一个请求都不发
    var keys = trajKeys();
    if (!keys.length) { isoStatus("先在左栏把弹加进「已选导弹」，再点「开始计算」", true); return; }
    var my = ++trajTicket;
    var t0 = Date.now();
    var body = {keys: keys, tier: isoTier(), scene: sceneOf()};
    isoStatus("正在算 " + keys.length + " 枚的轨迹…");
    return fetch(APPBACKEND.url("/v1/trajectory"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)})
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (payload) {
        if (my !== trajTicket) { return; }          // ⚠ 旧响应作废（后到的不许覆盖新选择）
        if (!payload || payload.ok === false) {
          throw new Error((payload && (payload.error || (payload.errors || []).join("；"))) || "后端没返回轨迹");
        }
        var n = trajDraw(payload);
        if (!n) { return; }                        // 失败文案已由 trajDraw 写
        var id = payload.identity || {};
        var extra = trajFailed.length ? (" · " + trajFailed.length + " 条失败：" + trajFailed.join("；")) : "";
        isoStatus("弹道 " + n + " 条 · " + (id.cached ? "缓存" : ((Date.now() - t0) + " ms"))
                  + " · " + (id.backend || "—") + extra, !!trajFailed.length);
      })
      .catch(function (e) {
        if (my !== trajTicket) { return; }
        trajDraw(null);
        trajFail("弹道拿不到（" + ((e && e.message) || e) + "）—— 图1 回落静态图，其它功能照常");
      });
  }
  function trajRun() {
    if (!APPBACKEND.configured || busy) { return; }   // 闸门双保险 + 运行中连点无效
    if (!trajKeys().length) { isoStatus("先在左栏把弹加进「已选导弹」，再点「开始计算」", true); return; }
    busy = true; syncRun();
    var p = trajRequest();
    var done = function () { busy = false; syncRun(); };
    if (p && typeof p.then === "function") { p.then(done, done); } else { done(); }
  }

  // 模式切换：只有扫描模式露出那组控件；切回扫描时把三维让位（平面图/静态图照常）。
  function setMode(m) {
    MODE.cur = (m === "scan") ? "scan" : "traj";
    modeTraj.checked = (MODE.cur === "traj");
    modeScan.checked = (MODE.cur === "scan");
    scanBox.hidden = (MODE.cur !== "scan");
    if (MODE.cur === "scan") {
      trajShow3D(false);
      isoStatus("扫描模式：勾「等时线」或「等时面」，再点「开始计算」");
      syncCardHead();          // 切回扫描 ⇒ 抬头回到「ΔV–β 能力平面」（别顶着"弹道轨迹"画平面图）
      cardStateFromViews();    // 卡片徽标也回到平面图那一套（别留着"弹道 · 轨迹 N 条"）
    } else {
      trajShow3D(trajDrawn > 0);
      isoStatus(trajDrawn > 0 ? ("弹道 " + trajDrawn + " 条") : "弹道模式：点「开始计算」算所选导弹的轨迹");
      syncCardHead();
    }
    syncRun();
  }
  modeTraj.onchange = function () { setMode("traj"); };
  modeScan.onchange = function () { setMode("scan"); };
  APPBACKEND.setMode = setMode;
  // ---- 等时线请求层（W3b）：只在 `__BACKEND__` 配好时动；防抖 + **旧响应作废** ----
  var isoTimer = {plane: null, bg: null}, isoTicket = {plane: 0, bg: 0};
  // 卡片状态（2026-10-23 改版）：后端算出东西之后，卡片右上角那枚徽标要如实变。
  // 静态时是「静态 · 标称点」；画上等时线/等时面之后换成对应的状态，别让用户以为还是静态图。
  function cardState(id, text, live) {
    var el = $("#" + id);
    if (!el) { return; }
    el.textContent = text;
    el.className = "figstate" + (live ? " live" : "");
  }
  function cardStateFromViews() {
    ["fig1", "fig2"].forEach(function (id) {
      var kind = (id === "fig1") ? "plane" : "bg";
      var v = (typeof POOL !== "undefined" && POOL.views) ? POOL.views[kind] : null;
      var ax = (v && typeof v.axis === "function") ? v.axis() : null;
      var n = (ax && ax.isoDrawn) || 0;
      cardState(id + "state", n ? ("已计算 · 等时线 " + n + " 段") : "静态 · 标称点", !!n);
    });
    var v3 = (typeof POOL !== "undefined" && POOL.views) ? POOL.views.fig3 : null;
    var s = (v3 && typeof v3.surfaceInfo === "function") ? v3.surfaceInfo() : null;
    var tris = (s && s.tris) || 0;
    cardState("fig3state", tris ? ("已计算 · 等时面 " + s.level + " s") : "静态 · 标称点", !!tris);
  }
  function isoStatus(text, err) {
    st.textContent = String(text || "");
    if (err) { st.classList.add("err"); } else { st.classList.remove("err"); }
  }
  function isoDraw(kind, payload) {
    var v = (typeof POOL !== "undefined" && POOL.views) ? POOL.views[kind] : null;
    if (!v || typeof v.setOverlay !== "function") { return 0; }
    v.setOverlay(payload);
    cardStateFromViews();
    var ax = (typeof v.axis === "function") ? v.axis() : null;
    return (ax && ax.isoDrawn) || 0;
  }
  function isoTier() {
    var b = (typeof window !== "undefined") ? window.__BACKEND__ : null;
    var t = (b && b.tier) || "fast";
    return (t === "standard" || t === "fast") ? t : "fast";
  }
  // ---- 发射参数（2026-10-23）：照 statshark 的「发射参数」区块 -------------------
  // 单位口径：速度输入是**公里/小时**，发出去转 m/s（后端 missile_solver.Scene 吃 m/s）。
  // 空值一律**不发**那个键（= 用包默认），别发 null / ""。
  var SCENE_FIELDS = [
    ["sp-vm0", "vm0", true], ["sp-alt", "alt_m", false], ["sp-pitch", "launch_pitch_deg", false],
    ["sp-heading", "launch_heading_deg", false], ["sp-tspd", "target_speed_ms", true],
    ["sp-talt", "target_alt_m", false], ["sp-range", "range_m", false],
    ["sp-tbear", "target_bearing_deg", false], ["sp-thead", "target_heading_deg", false],
    ["sp-tpitch", "target_pitch_deg", false]
  ];
  var KMH = 3.6;
  function sceneOf() {
    var out = {};
    SCENE_FIELDS.forEach(function (row) {
      var el = $("#" + row[0]);            // 用 共用的 $()：node 桩只实现了 querySelector
      if (!el) { return; }
      var raw = String(el.value === null || el.value === undefined ? "" : el.value).trim();
      if (raw === "") { return; }                    // 留空 = 不发这个键（用包默认）
      var n = parseFloat(raw);
      if (!isFinite(n)) { return; }
      out[row[1]] = row[2] ? (n / KMH) : n;          // 速度字段 km/h -> m/s
    });
    return out;
  }
  function sceneKey() { return JSON.stringify(sceneOf()); }

  function isoRequest(kind, keys) {
    if (!APPBACKEND.configured) { return; }      // 同上：闸在请求入口再上一道（双保险）
    var my = ++isoTicket[kind];
    var body = {kind: kind, keys: keys, tier: isoTier(),
                iso_step: Math.max(1, Number(step.value) || 1), scene: sceneOf()};
    isoStatus("等时线：请求 " + body.keys.length + " 枚（iso_step " + body.iso_step + " s）…");
    return fetch(APPBACKEND.url("/v1/overlay"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)})
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (payload) {
        if (my !== isoTicket[kind]) { return; }          // ⚠ 旧响应作废（后到的不许覆盖新选择）
        var n = isoDraw(kind, payload);
        var id = payload.identity || {};
        isoStatus("等时线 " + (payload.iso_lines || []).length + " 层 · " + n + " 段 · "
                  + (id.cached ? "缓存" : (id.elapsed_ms + " ms")) + " · "
                  + (id.backend || "—") + " · " + kind);
      })
      .catch(function (e) {
        if (my !== isoTicket[kind]) { return; }
        isoStatus("等时线拿不到（" + ((e && e.message) || e) + "）—— 图照常画，不影响其它功能", true);
      });
  }
  // 开关路径（切片 3）：**估网格先行** —— 小格直接算（单弹 plane 24 工况，和今天一样快）；
  // 大格**不悄悄开任务**（勾一下就占服务器跑几十秒太吓人），提示点「开始计算」。
  // 估网格本身也吃 isoTicket：勾选又变了 ⇒ 旧预估到点不作数（isoRequest 自己再发票）。
  function isoAuto(kind, keys, my) {
    fetch(APPBACKEND.url("/v1/estimate?kind=" + encodeURIComponent(kind)
                         + "&keys=" + encodeURIComponent(keys.join(","))))
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(function (est) {
        if (my !== isoTicket[kind]) { return; }          // ⚠ 旧作废：勾选又变了
        if (!est.ok) { throw new Error(est.error || "网格估不出来"); }
        if (est.sync_ok) { isoRequest(kind, keys); return; }
        isoStatus("等时线 " + kind + "：预计 " + est.nodes + " 工况，超出同步上限 —— 点「开始计算」跑任务");
      })
      .catch(function (e) {
        if (my !== isoTicket[kind]) { return; }
        isoStatus("等时线估不出来（" + ((e && e.message) || e) + "）—— 图照常画，不影响其它功能", true);
      });
  }
  function isoRefresh(kind) {
    if (!APPBACKEND.configured) { return; }      // ⚠ 唯一的"能不能碰后端"的闸：没配就一个请求都不发
    if (!on.checked) { isoDraw(kind, null); isoStatus("等时线：关"); return; }
    var keys = (typeof POOL !== "undefined" && POOL.sel) ? POOL.sel.slice() : [];
    if (!keys.length) { isoDraw(kind, null); isoStatus("等时线：池是空的，先选几枚"); return; }
    var my = ++isoTicket[kind];
    if (isoTimer[kind]) { clearTimeout(isoTimer[kind]); }
    isoTimer[kind] = setTimeout(function () { isoAuto(kind, keys, my); }, 250);   // 防抖（每 kind 各一个：onchange 连调 plane+bg，共享单发会把 plane 的吞掉）
  }
  APPBACKEND.refresh = isoRefresh;
  APPBACKEND.request = isoRequest;
  on.onchange = function () { isoRefresh("plane"); isoRefresh("bg"); };
  step.onchange = function () { isoRefresh("plane"); isoRefresh("bg"); };
  isoStatus("后端已配置，未连接");

  // ============================================ 等时面（切片 2）：/v1/isosurface + 时间滑块
  // 口径（`docs/STAGE-C.md` §6）：**一次只算一枚弹**（`keys` 给一个），滑块改的是 `level_s`；
  // 后端把立方体按 `(key, tier, grid)` 缓存、`level_s` 不进键 ⇒ 拖滑块只重提面（毫秒级）。
  // 前端这侧同样两件：**防抖**（250 ms，别在拖动中连发）+ **旧响应作废**（后到的不能覆盖新选择）。
  var surfTimer = null, surfTicket = 0;
  function surfDraw(res) {
    var v = (typeof POOL !== "undefined" && POOL.views) ? POOL.views.fig3 : null;
    if (!v || typeof v.setSurface !== "function") { return 0; }
    var n = v.setSurface(res);
    cardStateFromViews();
    return n;
  }
  function surfKey() {
    // ⚠ 等时面是**单弹**的：优先用户点中的那枚（`POOL.current`），否则基准弹，否则已选第一枚。
    var cat = (typeof POOL !== "undefined" && POOL.catalog) ? POOL.catalog : {};
    var keys = (typeof POOL !== "undefined" && POOL.sel) ? POOL.sel : [];
    return String(POOL.current || cat.standard || keys[0] || "");
  }
  function surfRequest() {
    if (!APPBACKEND.configured) { return; }      // 与等时线同口径的守卫：没配就一个请求都不发
    var my = ++surfTicket;
    var key = surfKey();
    if (!key) { surfDraw(null); isoStatus("等时面：先选一枚弹"); return; }
    var body = {keys: [key], tier: isoTier(), level_s: Number(lvl.value) || 1, grid: APPBACKEND.grid, scene: sceneOf()};
    isoStatus("等时面：请求 " + key + " @ " + body.level_s + " s（每轴 " + body.grid + " 个采样）…");
    return fetch(APPBACKEND.url("/v1/isosurface"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)})
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (payload) {
        if (my !== surfTicket) { return; }        // ⚠ 旧响应作废（后到的覆盖新选择 = 滑块会"跳回去"）
        var tris = surfDraw(payload);
        var id = payload.identity || {};
        isoStatus("等时面 " + (payload.level_s) + " s · " + tris + " 三角形 · "
                  + (id.cached ? "立方体命中缓存" : (id.elapsed_ms + " ms")) + " · "
                  + (id.backend || "—") + " · " + (payload.key || key));
      })
      .catch(function (e) {
        if (my !== surfTicket) { return; }
        surfDraw(null);
        isoStatus("等时面拿不到（" + ((e && e.message) || e) + "）—— 散点照常画，不影响其它功能", true);
      });
  }
  function surfRefresh() {
    if (!APPBACKEND.configured) { return; }      // ⚠ 闸门与刷新入口各一道（和等时线同一个形状）
    lvln.textContent = (lvl.value) + " s";
    if (!sf.checked) { surfDraw(null); isoStatus("等时面：关"); return; }
    if (surfTimer) { clearTimeout(surfTimer); }
    surfTimer = setTimeout(function () { surfRequest(); }, 250);   // 防抖：拖滑块时不连发
  }
  APPBACKEND.surfaceRefresh = surfRefresh;
  APPBACKEND.surfaceRequest = surfRequest;
  sf.onchange = function () { surfRefresh(); };
  lvl.oninput = function () { lvln.textContent = (lvl.value) + " s"; };
  lvl.onchange = function () { surfRefresh(); };
  // ============================================ 扫描（切片 3）：「开始计算」+ /v1/jobs 任务
  // 口径（docs/STAGE-C.md §3 接口 v1）：按钮按当前勾选**顺序**跑一轮：等时面（当前那一枚）→
  // 等时线 plane → bg（用「已选导弹」清单）。每段等时线先 GET /v1/estimate：`sync_ok` 直发
  // /v1/overlay（同步）；否则 POST /v1/jobs 跑任务 + 每 1 s 轮询（state running → done/error，
  // progress 0..1），done 才落笔。纪律：① 运行中禁用全部后端控件（防连点重复开跑）；
  // ② `scanTicket` 旧作废 —— 新一轮、选池/当前弹变化（invalidate）都会把在跑的轮次（含轮询）
  // 与迟到响应整体作废；③ 失败一行可读提示，散点与静态图不受影响。
  var scanTicket = 0, scanDrawn = {plane: false, bg: false, surface: false}, scanPollFails = 0;
  function scanBusy(b) {
    // 「开始计算」的禁用态由 syncRun() 统一算（它还要管"弹道模式下没选弹 ⇒ 禁用"），
    // 其余扫描控件在这里各自开关。
    on.disabled = b; sf.disabled = b; step.disabled = b; lvl.disabled = b;
    busy = !!b; syncRun();
  }
  function scanOverlay(kind, keys, my, next) {
    if (my !== scanTicket) { return; }                 // 旧轮次：连估网格都不必了
    isoStatus("等时线 " + kind + "：估网格…");
    fetch(APPBACKEND.url("/v1/estimate?kind=" + encodeURIComponent(kind)
                         + "&keys=" + encodeURIComponent(keys.join(","))))
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(function (est) {
        if (my !== scanTicket) { return; }             // ⚠ 旧作废：新一轮已开始
        if (!est.ok) { throw new Error(est.error || "网格估不出来"); }
        if (est.sync_ok) {
          isoStatus("等时线 " + kind + "：预计 " + est.nodes + " 工况，直接算…");
          return isoRequest(kind, keys).then(
            function () { if (my === scanTicket) { scanDrawn[kind] = true; } next("等时线 " + kind); },
            function () { next("等时线 " + kind + " 失败"); });   // 失败文案由 isoRequest 自己写
        }
        isoStatus("等时线 " + kind + "：预计 " + est.nodes + " 工况，走任务队列…");
        return fetch(APPBACKEND.url("/v1/jobs"), {
            method: "POST", headers: {"Content-Type": "application/json"},
            // ⚠ scene 必须一起发：11 弹的池子（默认）走的就是这条**任务队列**，
            //   不带 scene 的后果是"改了发射参数、图纹丝不动"，而且没有任何报错。
            body: JSON.stringify({op: "overlay", kind: kind, keys: keys, tier: isoTier(),
                                  iso_step: Math.max(1, Number(step.value) || 1),
                                  scene: sceneOf()})})
          .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
          .then(function (j) {
            if (my !== scanTicket) { return; }
            scanPoll(j.job_id, my, kind, next);
          });
      })
      .catch(function (e) {
        if (my !== scanTicket) { return; }
        isoStatus("等时线 " + kind + " 拿不到（" + ((e && e.message) || e) + "）—— 图照常画，不影响其它功能", true);
        next("等时线 " + kind + " 失败");
      });
  }
  function scanPoll(id, my, kind, next) {
    if (my !== scanTicket) { return; }                 // ⚠ 旧轮次的轮询到点也不再发
    fetch(APPBACKEND.url("/v1/jobs/" + encodeURIComponent(id)))
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(function (s) {
        if (my !== scanTicket) { return; }
        scanPollFails = 0;
        if (s.state === "running") {
          isoStatus("等时线 " + kind + "：任务 " + Math.round((s.progress || 0) * 100) + "%…");
          // ⚠ 2 s 一轮（30 次/分）—— 后端限流默认 60/min + burst 12，1 s 一轮的全池长任务
          //   必撞 429（全池 plane ≈ 1032 工况，fast 档要跑十几秒到几分钟）。
          setTimeout(function () { scanPoll(id, my, kind, next); }, 2000);
          return;
        }
        if (s.state === "done") {
          var res = s.result || {};
          var n = isoDraw(kind, res);
          scanDrawn[kind] = true;
          isoStatus("等时线 " + kind + "：" + (res.iso_lines || []).length + " 层 · " + n + " 段 · 任务完成");
          next("等时线 " + kind);
          return;
        }
        throw new Error(s.error || ("任务 " + s.state));
      })
      .catch(function (e) {
        if (my !== scanTicket) { return; }
        // 偶发的限流/网络抖动不轻易判死：退避重试几轮，还不行才报失败（任务还在服务器上跑）
        scanPollFails += 1;
        if (scanPollFails <= 5) {
          isoStatus("等时线 " + kind + "：轮询抖了一下（" + ((e && e.message) || e) + "），重试…");
          setTimeout(function () { scanPoll(id, my, kind, next); }, 3000);
          return;
        }
        isoStatus("等时线 " + kind + " 任务失败（" + ((e && e.message) || e) + "）—— 图照常画，不影响其它功能", true);
        next("等时线 " + kind + " 失败");
      });
  }
  function scanRun() {
    if (!APPBACKEND.configured || run.disabled) { return; }   // 闸门双保险 + 运行中连点无效
    var wantIso = !!on.checked, wantSurf = !!sf.checked;
    if (!wantIso && !wantSurf) { isoStatus("先勾「等时线」或「等时面」，再点开始计算"); return; }
    var keys = (typeof POOL !== "undefined" && POOL.sel) ? POOL.sel.slice() : [];
    var skey = surfKey();
    if (wantIso && !keys.length) { isoStatus("先在左栏把弹加进「已选导弹」，再开始计算"); return; }
    if (wantSurf && !skey) { isoStatus("等时面：先选一枚弹"); return; }
    var my = ++scanTicket;
    scanBusy(true);
    var t0 = Date.now(), parts = [], steps = [];
    if (wantSurf) {
      steps.push(function (next) {
        if (my !== scanTicket) { return; }
        var p = surfRequest();                          // 自己发票 + 状态文案（切片 2 的层）
        var go = function () { if (my === scanTicket) { scanDrawn.surface = true; } next("等时面"); };
        if (p && typeof p.then === "function") { p.then(go, go); } else { go(); }
      });
    }
    if (wantIso) {
      ["plane", "bg"].forEach(function (kind) {
        steps.push(function (next) { scanOverlay(kind, keys, my, next); });
      });
    }
    (function stepNext(i) {
      if (my !== scanTicket) { return; }                // 旧轮次到此为止（invalidate 已把按钮放开）
      if (i >= steps.length) {
        scanBusy(false);
        parts.push("用时 " + ((Date.now() - t0) / 1000).toFixed(1) + " s");
        isoStatus("计算完成：" + parts.join(" · "));
        return;
      }
      steps[i](function (part) {
        if (my !== scanTicket) { return; }
        parts.push(String(part || ""));
        stepNext(i + 1);
      });
    })(0);
  }
  // 「开始计算」按当前模式分派（2026-10-24）：弹道 → /v1/trajectory；扫描 → 原有那套
  // 等时线（plane + bg）+ 等时面。两个模式共用同一把 busy 闸，一次只跑一件事。
  run.onclick = function () { if (MODE.cur === "scan") { scanRun(); } else { trajRun(); } };
  // 初值：默认「弹道」（控件组按模式显示/隐藏，状态行给一句可读说明）
  setMode("traj");
  // 选池 / 当前弹变化（`poolSet` / `poolPickCurrent` 调）：收掉已画层 + 作废在跑轮次 ——
  // 层必须**严格随输入**，绝不允许「上一批弹的等时线叠在这一批的散点上」。boot 首次铺选择时
  // 什么都没画也没在跑 ⇒ 静默跳过（不然一开页就先吃一条提示）。
  APPBACKEND.invalidate = function (why) {
    syncRun();                    // 选池变了 ⇒ 「开始计算」的禁用态跟着变（0 弹必须禁用）
    // 弹道这一侧也严格随输入：选池一变，图1 上的三维轨迹就不是这一批弹的了 ⇒ 收掉。
    // （先判"有没有东西要收"，不然 boot 首次铺选择时会先吃一条提示。）
    var hadTraj = trajDrawn > 0 || trajTicket > 0;
    if (hadTraj) {
      trajTicket++;                                    // 在跑的弹道请求作废
      if (trajView) { trajView.clear(); }
      trajDrawn = 0;
      if (trajLegend) { trajLegend.textContent = ""; }
      trajShow3D(false);
      var im = trajStaticImg();
      if (im) { im.hidden = false; }
      cardState("fig1state", "静态 · 标称点", false);
    }
    if (!scanDrawn.plane && !scanDrawn.bg && !scanDrawn.surface && !run.disabled && !hadTraj) { return; }
    scanTicket++;                                      // 在跑的轮次（含 jobs 轮询）全部作废
    scanBusy(false);
    isoDraw("plane", null); isoDraw("bg", null); surfDraw(null);
    scanDrawn.plane = false; scanDrawn.bg = false; scanDrawn.surface = false;
    isoStatus((why || "选择变了") + " —— 点「开始计算」重算");
  };
  if (typeof window !== "undefined") { window.APPBACKEND = APPBACKEND; }
})();

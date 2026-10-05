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
var POOL = {catalog: null, notes: null, sel: [], current: null, views: {}};

function poolEntries() {
  // 候选列表 = 可算且默认要显示的那些：目录里 `duplicate_of` 的另一半是孪生（`*_default`）
  return ((POOL.catalog || {}).missiles || []).filter(function (m) {
    return m && m.key && !m.duplicate_of && !m.default_hidden;
  });
}
function poolUnsupported() { return ((POOL.catalog || {}).unsupported || []); }
function poolLabel(m) { return String((m && (m.label || m.key)) || ""); }
function poolDefault() {
  // 默认选中的就是目录里标了 in_pool11 的那些 —— 壳里不写死任何弹名
  return poolEntries().filter(function (m) { return m.in_pool11; })
                      .map(function (m) { return String(m.key); });
}
function poolAll() { return poolEntries().map(function (m) { return String(m.key); }); }
function poolSave(keys) {
  try { localStorage.setItem(POOL_KEY, JSON.stringify(keys)); } catch (e) {}
}
// 清掉记忆（**只**给"回到 11 弹"用 —— 与「仅 11 弹」的区别就在这里：那条只改当前选择，不动存档）。
function poolClearStore() {
  try { localStorage.removeItem(POOL_KEY); } catch (e) {}
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
// 「已恢复你上次的弹池 N 枚 · 回到 11 弹」——只在**存过、且存的不是默认 11 弹**、且当前选择也不是
// 默认 11 弹时出现（首次访问 / 已选就是 11 弹 / 点过复位 ⇒ 隐藏，不给新访客添噪）。
function poolRestoredHint() {
  var box = $("#poolrestored");
  if (!box) { return; }
  var saved = poolStored();
  var def = poolDefault();
  var show = (saved !== null) && !poolSameSet(saved, def) && !poolSameSet(POOL.sel, def);
  box.hidden = !show;
  if (show) {
    var el = $("#poolrestoredtext");
    if (el) { setText(el, "已恢复你上次的弹池 " + POOL.sel.length + " 枚 ·"); }
  }
}
// 「回到 11 弹」= 清存档 + 选择回到默认 11 弹 + 重绘三张图（`poolSet(..., false)` 不写回存档）。
function poolResetTo11() {
  poolClearStore();
  poolSet(poolDefault(), false);
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
function poolBuildRows() {
  var list = $("#poolcands");
  if (!list) { return; }
  list.textContent = "";
  poolEntries().forEach(function (m) { list.appendChild(poolMakeRow(m, false)); });
  poolUnsupported().forEach(function (m) { list.appendChild(poolMakeRow(m, true)); });
  poolShowCurrent();
}
// 当前选中：只能一条（StatShark 也是一次一条）；点了才点亮 ＋。
function poolPickCurrent(key) {
  POOL.current = (POOL.current === key) ? null : key;
  poolShowCurrent();
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
// ＋：把当前选中加入「已选导弹」，加完清空选中（一次一条，StatShark 同款）。
function poolAddCurrent() {
  var k = POOL.current;
  if (!k) { return; }
  if (POOL.sel.indexOf(k) >= 0) { poolStat(poolRowName(poolEntryOf(k)) + " 已经在已选导弹里了。"); }
  else { poolAdd(k); }
  POOL.current = null;
  poolShowCurrent();
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
// 搜索：**键入即筛**（绑在 `oninput`），只切"显不显示"，不动选择；一条没命中给一行提示。
function poolFilter(text) {
  var q = poolFold(text);
  var shown = 0;
  document.querySelectorAll("#poolcands .pool-row").forEach(function (row) {
    var nm = row.querySelector(".nm");
    var hay = poolFold(String(row.getAttribute("data-key") || "") + " "
                       + (nm ? nm.textContent : "") + " " + (row.title || ""));
    var hit = !q || hay.indexOf(q) >= 0;
    row.hidden = !hit;
    if (hit) { shown += 1; }
  });
  var none = $("#poolnone");
  if (none) { none.hidden = shown > 0; }
  if (q) { poolStat(""); }
}
// 「已选导弹」：**左对齐一列**，每枚右侧一个红色 ✕（删除单枚 = `poolRemove`）；空列表给一行提示。
function poolPicked() {
  var box = $("#poolpicked");
  if (!box) { return; }
  box.textContent = "";
  var byKey = {};
  poolEntries().forEach(function (m) { byKey[String(m.key)] = m; });
  var base = String(((POOL.catalog || {}).standard) || "");
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
    var nm = document.createElement("b");
    setText(nm, m ? poolRowName(m) : k);
    pick.appendChild(nm);
    if (k === base) {
      var mark = document.createElement("span");
      mark.className = "base";
      setText(mark, "基准");
      pick.appendChild(mark);
    }
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
  var cat = POOL.catalog || {};
  setText($("#poolcount"), "已选 " + POOL.sel.length + " / 可算 " + poolEntries().length
    + "（目录 " + (cat.count || "?") + " 条：可算 " + (cat.computable || "?")
    + " + 待动态解算 " + poolUnsupported().length + "）");
  var def = poolDefault(), c11 = $("#pool11"), cAll = $("#poolAll"), cNone = $("#poolClear");
  var sameDef = (def.length === POOL.sel.length);
  if (sameDef) { def.forEach(function (k) { if (!want[k]) { sameDef = false; } }); }
  var all = poolAll(), sameAll = (all.length === POOL.sel.length);
  if (sameAll) { all.forEach(function (k) { if (!want[k]) { sameAll = false; } }); }
  if (c11) { c11.className = sameDef ? "chip on" : "chip"; }
  if (cAll) { cAll.className = sameAll ? "chip on" : "chip"; }
  if (cNone) { cNone.className = (POOL.sel.length === 0) ? "chip on" : "chip"; }
  poolPicked();
  poolShowCurrent();
  poolRestoredHint();
  poolSync();
}
// 唯一的"改选择"入口：存档 → 同步四处状态 → 交给三张图。
function poolSet(keys, user) {
  var known = {};
  poolEntries().forEach(function (m) { known[String(m.key)] = 1; });
  POOL.sel = (keys || []).map(String).filter(function (k) { return known[k]; });
  if (user) { poolSave(POOL.sel); }
  poolMark();
}
function poolPick11() { poolSet(poolDefault(), true); }
function poolPickAll() { poolSet(poolAll(), true); }
function poolClear() { poolSet([], true); }
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
      POOL.views[h.kind] = F.mount(h.host, {kind: h.kind, catalog: POOL.catalog, notes: notesFor(h.kind)});
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
    POOL.views.fig3 = G.mount(host, {catalog: POOL.catalog, style: (POOL.catalog || {}).style});
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

function applyHeader() {
  var cat = POOL.catalog || {};
  var sv = cat.solver || {};
  var bits = [];
  var name = [sv.solver, sv.model, sv.version].filter(Boolean).join(" · ");
  if (name) { bits.push(name); }
  if (cat.count) { bits.push(cat.count + " 条预设（可算 " + (cat.computable || "?") + "）"); }
  bits.push("本页零后端：点全部在浏览器里现算");
  setText($("#hdrsub"), bits.join(" · "));
}
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
  // 左栏的接线：三个动作（仅 11 弹 / 全选可算 / 清空）+ 搜索框（键入即筛）+ 右侧 ＋（加入已选）
  if ($("#pool11")) { $("#pool11").onclick = poolPick11; }
  if ($("#poolAll")) { $("#poolAll").onclick = poolPickAll; }
  if ($("#poolClear")) { $("#poolClear").onclick = poolClear; }
  if ($("#pooladd")) { $("#pooladd").onclick = poolAddCurrent; }
  if ($("#poolreset")) { $("#poolreset").onclick = poolResetTo11; }
  if ($("#poolsearch")) { $("#poolsearch").oninput = function () { poolFilter(this.value); }; }

  poolLoadData().then(function (got) {
    var cat = got[0], notes = got[1];
    POOL.notes = notes;
    notesInto("plane");
    notesInto("bg");
    if (!cat || cat.ok === false) {
      // 目录拿不到：整页回落到 HTML 里那份静态图，只报一行；**不去任何服务器找数据**
      msg("目录读不到（`catalog.js` 的全局与 `./catalog.json` 都没有）—— 页面回落到静态图；"
          + "双击 `file://` 打开时请用脚本载入的数据（`./catalog.js`），或起个本地 http 服务。", "err");
      setText($("#poolcount"), "目录不可用");
      poolStat("把 catalog.js / notes.js（或 catalog.json / notes.json）与 figures/ 放在页面同一个目录下。");
      return;
    }
    POOL.catalog = cat;
    applyHeader();
    poolBuildRows();
    var bad2d = poolMount();
    var bad3 = poolMount3d();
    var saved = poolStored();
    poolSet(saved === null ? poolDefault() : saved, false);
    var hints = [];
    if (bad2d.length) { hints.push("图1/图2 的实时形态没装上（" + bad2d.join("；") + "）—— 卡片上是静态图"); }
    if (bad3) { hints.push("图3 的三维层还没加载（" + bad3 + "）—— 图1/图2 不受影响"); }
    poolStat(hints.join("；"));
  }).catch(function (e) {
    msg("读目录时出错：" + ((e && e.message) || e), "err");
  });
}
poolBoot();

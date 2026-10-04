"use strict";
// ============================================================================
// 静态托管版首页的壳（GitHub Pages / Cloudflare 直接丢上去就能跑）。
//
// 三条硬口径：
//   1. **零后端**：整份脚本只有两次 `fetch`，都是读**同目录**的静态 JSON ——
//      `./catalog.json`（全弹池派生目录 + 图面样式，结构同 阶段 B 的目录响应）与
//      `./notes.json`（图注文本，单一出处）。没有相对服务器发起的任何调用，也没有轮询。
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
var POOL = {catalog: null, notes: null, sel: [], views: {}};

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
function poolBuildRows() {
  var list = $("#poollist");
  if (!list) { return; }
  list.textContent = "";
  poolEntries().forEach(function (m) {
    var row = document.createElement("div");
    row.className = "pool-row";
    row.setAttribute("data-key", String(m.key));
    var label = document.createElement("label");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = String(m.key);
    label.appendChild(cb);
    var nm = document.createElement("span");
    nm.className = "nm";
    setText(nm, poolLabel(m));
    label.appendChild(nm);
    row.appendChild(label);
    var tag = document.createElement("span");
    tag.className = "tag";
    setText(tag, m.seeker);
    row.appendChild(tag);
    if (m.full_name && m.full_name !== m.label) { row.title = String(m.full_name); }
    list.appendChild(row);
  });
  // 目录里报"算不了"的那几条：列出、置灰、悬停给真实原因（读目录给的字段，不另写文案）
  poolUnsupported().forEach(function (m) {
    var row = document.createElement("div");
    row.className = "pool-row off";
    row.setAttribute("data-key", String(m.key));
    var label = document.createElement("label");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.disabled = true;
    label.appendChild(cb);
    var nm = document.createElement("span");
    nm.className = "nm";
    setText(nm, poolLabel(m));
    label.appendChild(nm);
    row.appendChild(label);
    var tag = document.createElement("span");
    tag.className = "tag";
    setText(tag, m.seeker);
    row.appendChild(tag);
    var why = document.createElement("span");
    why.className = "why";
    setText(why, m.reason || "不可算");
    row.appendChild(why);
    row.title = String(m.reason || "") + (m.kernel_reason ? "　原因：" + m.kernel_reason : "");
    list.appendChild(row);
  });
  list.addEventListener("change", function (e) {
    if (!e.target || e.target.type !== "checkbox") { return; }
    poolSet(poolChecked(), true);
  });
}
function poolChecked() {
  var out = [];
  document.querySelectorAll("#poollist input[type=checkbox]").forEach(function (cb) {
    if (cb.checked && !cb.disabled) { out.push(String(cb.value)); }
  });
  return out;
}
// 折叠 `-` / `_` / 空白：目录 key 是 `us_aim_120a` 这种名，用户会打 "aim-120"。
function poolFold(text) {
  return String(text || "").toLowerCase().replace(/[\s_-]+/g, "");
}
// 搜索只切"显不显示"，不改选择（选择只由勾选框与已选 chips 决定）。
function poolFilter(text) {
  var q = poolFold(text);
  document.querySelectorAll("#poollist .pool-row").forEach(function (row) {
    var nm = row.querySelector(".nm");
    var hay = poolFold(String(row.getAttribute("data-key") || "") + " " + (nm ? nm.textContent : ""));
    row.hidden = !!q && hay.indexOf(q) < 0;
  });
}
// 已选集合：chips + 每枚一个删除按钮（删除单枚 = `poolRemove`）。
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
    setText(none, "还没选弹 —— 下面勾几枚，或在上面搜型号。");
    box.appendChild(none);
    return;
  }
  POOL.sel.forEach(function (k) {
    var m = byKey[k];
    var chip = document.createElement("span");
    chip.className = "pick" + (k === base ? " base" : "");
    var nm = document.createElement("b");
    setText(nm, m ? poolLabel(m) : k);
    chip.appendChild(nm);
    if (k === base) {
      var mark = document.createElement("span");
      setText(mark, "基准");
      chip.appendChild(mark);
    }
    var x = document.createElement("button");
    x.type = "button";
    x.setAttribute("data-remove", k);
    x.title = "从已选里去掉 " + (m ? poolLabel(m) : k);
    setText(x, "×");
    x.onclick = function () { poolRemove(k); };
    chip.appendChild(x);
    if (m) { chip.title = String(m.full_name || m.label || k); }
    box.appendChild(chip);
  });
}
function poolMark() {
  var want = {};
  POOL.sel.forEach(function (k) { want[k] = 1; });
  document.querySelectorAll("#poollist .pool-row").forEach(function (row) {
    var cb = row.querySelector("input");
    if (cb && !cb.disabled) { cb.checked = !!want[String(row.getAttribute("data-key"))]; }
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
function poolBoot() {
  // 左栏三个动作 + 已选集合里的删除，都在这里接线（函数名见上）
  if ($("#pool11")) { $("#pool11").onclick = poolPick11; }
  if ($("#poolAll")) { $("#poolAll").onclick = poolPickAll; }
  if ($("#poolClear")) { $("#poolClear").onclick = poolClear; }
  var s = $("#poolsearch");
  if (s) { s.oninput = function () { poolFilter(this.value); }; }

  var catReq = fetch("./catalog.json", {headers: {"Accept": "application/json"}})
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; });
  var notesReq = fetch("./notes.json", {headers: {"Accept": "application/json"}})
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; });

  Promise.all([catReq, notesReq]).then(function (got) {
    var cat = got[0], notes = got[1];
    POOL.notes = notes;
    notesInto("plane");
    notesInto("bg");
    if (!cat || cat.ok === false) {
      // 目录拿不到：整页回落到 HTML 里那份静态图，只报一行；**不去任何服务器找数据**
      msg("目录（./catalog.json）没读到 —— 页面回落到静态图；弹池需要它才能工作。", "err");
      setText($("#poolcount"), "目录不可用");
      setText($("#poolstat"), "把 catalog.json / notes.json / figures/ 与这三个文件放在同一个目录下。");
      poolStat("把 catalog.json / notes.json / figures/ 与页面放同一个目录。");
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

/* 用 node **真跑一遍** `webui_static/app.js` 的左栏骨架与预设 chip（桩 DOM，不联网）。
 *
 * 为什么需要它：`-k webui` 那套 Python 测试跑不了前端行为（无浏览器），只能钉住契约名。
 * 而用户对这次改版的第一条要求是"**点 chip 必须真的改输入框的值**，不许装饰性按钮"——
 * 那是行为，只能真跑。这个探针用 `vm` 把 app.js 装进一个最小 DOM 桩里，然后：
 *   1. 点环境预设 chip `close` ⇒ 读输入框的值（应变）+ 读 `collect()` 的请求体（应变）；
 *   2. 点左栏折叠按钮 ⇒ 读 `.rail-collapsed` 与 `localStorage`（应记住状态）；
 *   3. 手改一格 ⇒ 读「已偏离预设」徽标（应亮起，且 title 指出是哪一格）。
 * 真浏览器再验一遍观感与截图（见 docs/WEBUI.md）。
 *
 * 用法：`node tests/_webui_chrome_probe.js <page.json>`
 *   page.json = {"html": 渲染后的首页, "defaults": …, "presets": …, "envpresets": …}
 * 输出：**一行 JSON**（stdout）；失败时 stderr 带栈、退出码非 0。
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

const page = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const appJsPath = process.argv[3];
const src = fs.readFileSync(appJsPath, "utf8");

// ------------------------------------------------------------------ 桩 DOM
function makeEl(tag, attrs) {
  const node = {
    tagName: String(tag || "").toUpperCase(),
    attrs: Object.assign({}, attrs || {}),
    hidden: false,
    title: "",
    textContent: "",
    innerHTML: "",
    className: "",
    children: [],
    _cls: new Set(),
    _listeners: {}
  };
  // `input.value` 在真 DOM 里**永远是字符串**（赋 20000 读回来是 "20000"）。桩里也得这样，
  // 否则 `fillForm()` 写进去的数字会一路带着类型走，探针看到的请求体与浏览器不一致。
  let rawValue = "";
  Object.defineProperty(node, "value", {
    get: function () { return rawValue; },
    set: function (v) { rawValue = (v === null || v === undefined) ? "" : String(v); },
    enumerable: true, configurable: true
  });
  node.getAttribute = function (k) {
    return Object.prototype.hasOwnProperty.call(node.attrs, k) ? node.attrs[k] : null;
  };
  node.setAttribute = function (k, v) { node.attrs[k] = String(v); };
  node.addEventListener = function (t, fn) {
    (node._listeners[t] = node._listeners[t] || []).push(fn);
  };
  node.removeEventListener = function () {};
  node.appendChild = function (c) { node.children.push(c); return c; };
  node.removeChild = function (c) {
    const i = node.children.indexOf(c);
    if (i >= 0) node.children.splice(i, 1);
  };
  node.querySelector = function () { return null; };
  node.querySelectorAll = function () { return []; };
  node.fire = function (t, ev) {
    (node._listeners[t] || []).forEach(function (f) { f(ev || { target: node }); });
  };
  node.classList = {
    add: function (c) { node._cls.add(c); },
    remove: function (c) { node._cls.delete(c); },
    contains: function (c) { return node._cls.has(c); },
    toggle: function (c, force) {
      const on = (force === undefined) ? !node._cls.has(c) : !!force;
      if (on) node._cls.add(c); else node._cls.delete(c);
      return on;
    }
  };
  return node;
}

const html = page.html;
const byId = {};
const byField = {};
const fields = [];          // document.querySelectorAll("[data-field]") 的顺序
const envChips = [];
const presetChips = [];

// 输入框：`<input data-field="x" type="text" value="…" …>`
let m;
const inputRe = /<input[^>]*data-field="([^"]+)"[^>]*value="([^"]*)"/g;
while ((m = inputRe.exec(html)) !== null) {
  const node = makeEl("input", { "data-field": m[1] });
  node.value = m[2];
  byField[m[1]] = node;
  fields.push(node);
}
// 下拉：`<select … data-field="x" …>…<option value="y" selected>…`
// ⚠ 属性顺序不固定（`hidden_select()` 渲的是 `id=… data-field=… hidden`），所以正则要
//   容忍 `data-field` 出现在中间 —— 第一版写死了 `<select data-field=`，于是 env_preset /
//   preset 这两个字段**根本没被解析出来**，探针却"通过"了（漏测比测错更坏）。
const selectRe = /<select[^>]*data-field="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g;
while ((m = selectRe.exec(html)) !== null) {
  const body = m[2];
  const sel = /<option value="([^"]*)" selected>/.exec(body);
  const first = /<option value="([^"]*)"/.exec(body);
  const node = makeEl("select", { "data-field": m[1] });
  node.value = sel ? sel[1] : (first ? first[1] : "");
  byField[m[1]] = node;
  fields.push(node);
}
// chip：`<button type="button" class="chip" data-env-preset="close">近距</button>`
const chipRe = /<button type="button" class="chip" data-(env-preset|preset)="([^"]+)">([^<]*)</g;
while ((m = chipRe.exec(html)) !== null) {
  const node = makeEl("button", { ["data-" + m[1]]: m[2] });
  node.textContent = m[3];
  (m[1] === "env-preset" ? envChips : presetChips).push(node);
}
// 骨架里必须存在的几个 id（缺了说明页面结构没接上）
["shell", "railtoggle", "envdirty", "msg"].forEach(function (id) {
  if (html.indexOf('id="' + id + '"') >= 0) byId[id] = makeEl("div", { id: id });
});

const docInputListeners = [];
const documentStub = {
  body: makeEl("body"),
  createElement: function (tag) { return makeEl(tag); },
  addEventListener: function (t, fn) {
    if (t === "input") docInputListeners.push(fn);
  },
  querySelector: function (sel) {
    if (sel.charAt(0) === "#") return byId[sel.slice(1)] || null;
    const f = /^\[data-field="([^"]+)"\]$/.exec(sel);
    if (f) return byField[f[1]] || null;
    const c = /^\[data-(env-preset|preset)="([^"]+)"\]$/.exec(sel);
    if (c) {
      const arr = c[1] === "env-preset" ? envChips : presetChips;
      for (const b of arr) {
        if (b.getAttribute("data-" + c[1]) === c[2]) return b;
      }
    }
    return null;
  },
  querySelectorAll: function (sel) {
    if (sel === "[data-field]") return fields.slice();
    if (sel === "[data-env-preset]") return envChips.slice();
    if (sel === "[data-preset]") return presetChips.slice();
    if (sel === "[data-field].bad") return fields.filter(function (e) { return e._cls.has("bad"); });
    if (sel === ".field-err") return [];
    return [];
  }
};
const store = {};
const localStorageStub = {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
  setItem: function (k, v) { store[k] = String(v); },
  removeItem: function (k) { delete store[k]; }
};

const ctx = vm.createContext({
  document: documentStub,
  window: { innerWidth: 1280 },
  localStorage: localStorageStub,
  DEFAULTS: page.defaults,
  PRESETS: page.presets,
  ENVPRESETS: page.envpresets,
  META: { poll_ms: 500 },
  console: console,
  fetch: function () { throw new Error("探针不该发网络请求"); }
});
vm.runInContext(src, ctx, { filename: "app.js" });

// ------------------------------------------------------------------ 探针
function value(name) {
  const el = byField[name];
  return el ? String(el.value) : null;
}
function fireInput(el) {
  docInputListeners.forEach(function (fn) { fn({ target: el }); });
  el.fire("input", { target: el });
  el.fire("change", { target: el });
}
function bodyOf() {
  const b = ctx.collect();
  return b;
}
const out = {
  ok: true,
  fields_seen: fields.length,
  env_chips: envChips.map(function (b) { return b.getAttribute("data-env-preset"); }),
  preset_chips: presetChips.map(function (b) { return b.getAttribute("data-preset"); }),
  chip_titles_filled: envChips.every(function (b) { return !!b.title; })
};

// ① 点 chip：表单值变 + 请求体变
const closeChip = ctx.document.querySelector('[data-env-preset="close"]');
if (!closeChip || typeof closeChip.onclick !== "function") {
  out.ok = false;
  out.error = "chip 上没有 onclick（app.js 没接上？）";
} else {
  out.before_chip = { env_preset: value("env_preset"), range_m: value("range_m"),
                      alt_m: value("alt_m"), body_range_m: bodyOf().range_m };
  closeChip.onclick();
  const body = bodyOf();
  out.after_chip = {
    env_preset: value("env_preset"), range_m: value("range_m"), alt_m: value("alt_m"),
    body_range_m: body.range_m, body_env_preset: body.env_preset,
    body_alt_m: body.alt_m, bg_alt_m: value("bg_alt_m"),
    body_dirty: body._dirty,          // 服务端只认 `_dirty` 里点过名的字段
    body_full: body,                  // 整份请求体：交给 Python 侧喂 form_to_request 验到 scene
    active_chip: envChips.filter(function (b) { return b._cls.has("on"); })
                         .map(function (b) { return b.getAttribute("data-env-preset"); }),
    badge_hidden: byId.envdirty ? byId.envdirty.hidden : null
  };
  // ② 视图设置（figure）**不属预设层** ⇒ 改了它不该亮"已偏离预设"
  //    （真踩过：一开页面就因为恢复出来的 figure 报"已偏离"，那个徽标就成了噪音）
  const fig = byField["figure"];
  if (fig) {
    fig.value = "all";
    fireInput(fig);
    out.after_view_edit = {
      figure: value("figure"),
      badge_hidden: byId.envdirty ? byId.envdirty.hidden : null
    };
  }
  // ③ 手改预设管的字段 ⇒ 徽标亮起并点名
  const rm = byField["range_m"];
  if (rm) {
    rm.value = "33000";
    fireInput(rm);
    out.after_edit = {
      range_m: value("range_m"), body_range_m: bodyOf().range_m,
      badge_hidden: byId.envdirty ? byId.envdirty.hidden : null,
      badge_title: byId.envdirty ? byId.envdirty.title : null
    };
  }
}

// ③ 折叠：状态进 localStorage
const toggle = ctx.document.querySelector("#railtoggle");
if (toggle && typeof toggle.onclick === "function") {
  toggle.onclick();
  out.rail = {
    collapsed_class: byId.shell ? byId.shell._cls.has("rail-collapsed") : null,
    stored: localStorageStub.getItem("missile-sim:rail"),
    aria: toggle.getAttribute("aria-expanded"),
    glyph: toggle.textContent
  };
  toggle.onclick();                     // 再点一次应回到展开
  out.rail.expanded_again = byId.shell ? !byId.shell._cls.has("rail-collapsed") : null;
  out.rail.stored_after = localStorageStub.getItem("missile-sim:rail");
} else {
  out.ok = false;
  out.error = "折叠按钮没接上（#railtoggle.onclick 不是函数）";
}

// ④ 预设想定 chip 也要真填值
const headChip = ctx.document.querySelector('[data-preset="tail_chase"]');
if (headChip && typeof headChip.onclick === "function") {
  headChip.onclick();
  const body = bodyOf();
  out.preset_chip = { preset: value("preset"), range_m: value("range_m"),
                      body_preset: body.preset, body_range_m: body.range_m,
                      body_target_heading_deg: body.target_heading_deg };
}

process.stdout.write(JSON.stringify(out));

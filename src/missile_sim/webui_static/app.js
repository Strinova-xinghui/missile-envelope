"use strict";
var $ = function (s) { return document.querySelector(s); };
function inp(name) { return document.querySelector('[data-field="' + name + '"]'); }
// 用户**手动**动过的字段。程序性赋值（fillForm 里的 el.value = …）不触发 input 事件，
// 所以"选预置 → 自动填表"不会把它们记成手改 —— 这正是我们要的语义。
var DIRTY = new Set();
document.querySelectorAll("[data-field]").forEach(function (el) {
  var mark = function () {
    var n = el.getAttribute("data-field");
    if (n && n !== "preset") DIRTY.add(n);
    saveLocal();
  };
  el.addEventListener("input", mark);
  el.addEventListener("change", mark);
});
function fillForm(obj) {
  for (var k in obj) {
    if (!Object.prototype.hasOwnProperty.call(obj, k)) continue;
    var el = inp(k);
    if (!el) continue;
    el.value = (obj[k] === null || obj[k] === undefined) ? "" : obj[k];
  }
}
function collect() {
  var f = {};
  document.querySelectorAll("[data-field]").forEach(function (el) {
    f[el.getAttribute("data-field")] = el.value;
  });
  // 如实上报"哪些框被人动过"：后端据此决定哪些值覆盖预置、哪些沿用预置。
  // 少了这个键，后端只能靠"值是否等于默认值"猜，会把**特意填成默认值**的框丢掉。
  f._dirty = Array.from(DIRTY).join(",");
  return f;
}
function msg(text, cls) {
  var box = $("#msg");
  box.innerHTML = "";
  if (!text) return;
  var div = document.createElement("div");
  div.className = "msg " + (cls || "");
  div.textContent = text;
  box.appendChild(div);
}
// ---- 失败响应的**字段级定位** -------------------------------------------------
// 归位（`field_errors`）由服务端算好 —— 它知道每个字段的 label，前端只知道 DOM。这里只上色。
function clearFieldMarks() {
  document.querySelectorAll("[data-field].bad").forEach(function (el) { el.classList.remove("bad"); });
  document.querySelectorAll(".field-err").forEach(function (el) { el.remove(); });
}
function markFieldErrors(map) {
  clearFieldMarks();
  if (!map) return false;
  var first = null;
  Object.keys(map).forEach(function (name) {
    var el = inp(name);
    if (!el) return;
    el.classList.add("bad");
    var tip = document.createElement("div");
    tip.className = "field-err";
    tip.textContent = (map[name] || []).join("；");
    el.parentNode.appendChild(tip);
    if (!first) first = el;
  });
  if (first) {                       // 眼不见不算提示：滚到它、并把光标放进去
    if (first.scrollIntoView) first.scrollIntoView({block: "center", behavior: "smooth"});
    first.focus();
  }
  return !!first;
}
// 一动手就先清掉这个框自己的红框与提示（别的框留到下次提交，免得别的错突然消失）
document.addEventListener("input", function (e) {
  var el = e.target;
  if (!el || !el.getAttribute || !el.getAttribute("data-field")) return;
  el.classList.remove("bad");
  var tip = el.parentNode && el.parentNode.querySelector(".field-err");
  if (tip) tip.remove();
}, true);
// 失败统一走这里：给人看的 `errors` 打消息条，`field_errors` 标到框上
function showFailure(body, fallback) {
  msg(((body && body.errors) || [fallback]).join("\n"), "err");
  markFieldErrors((body && body.field_errors) || {});
}
// ---- 记住上次手改的输入 ------------------------------------------------------
// 只记"人手改过的"（`_dirty`）。全是默认值时**不打扰** —— 否则第一次打开就弹一句"已恢复"很怪。
var LS_KEY = "missile-sim:form";
function saveLocal() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(collect())); } catch (e) {}
}
function restoreLocal() {
  var raw = null;
  try { raw = localStorage.getItem(LS_KEY); } catch (e) { return; }
  if (!raw) return;
  var obj = null;
  try { obj = JSON.parse(raw); } catch (e) { return; }
  if (!obj || typeof obj !== "object") return;
  var dirty = String(obj._dirty || "").split(",").filter(Boolean);
  if (!dirty.length) return;
  fillForm(obj);                     // 程序性赋值不会记成手改，所以下面按存下来的 _dirty 补回
  dirty.forEach(function (n) { if (inp(n)) DIRTY.add(n); });
  msg("已恢复上次的手改输入：" + dirty.join("、") + "（点「忘记上次输入」可清掉）。", "ok");
}

function fmt(v, digits) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toFixed(digits === undefined ? 3 : digits);
  return String(v);
}
async function post(url, body) {
  var r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"},
                            body: JSON.stringify(body)});
  var j;
  try { j = await r.json(); }
  catch (e) { j = {ok: false, errors: ["服务端返回的不是 JSON（HTTP " + r.status + "）"]}; }
  return {status: r.status, body: j};
}
function table(rows) {
  var t = $("#restab");
  t.innerHTML = "";
  rows.forEach(function (pair) {
    var tr = document.createElement("tr");
    var th = document.createElement("th");
    th.textContent = pair[0];
    var td = document.createElement("td");
    td.textContent = pair[1];
    tr.appendChild(th); tr.appendChild(td); t.appendChild(tr);
  });
}
function showFigures(urls, paths) {
  var box = $("#figs");
  box.innerHTML = "";
  (urls || []).forEach(function (u) {
    var im = document.createElement("img");
    im.src = u + "?t=" + Date.now();
    box.appendChild(im);
  });
  if (paths && paths.length) {
    var pre = document.createElement("pre");
    pre.textContent = paths.join("\n");
    box.appendChild(pre);
  }
}
var timer = null;
function startPoll(id, title) {
  $("#jobcard").hidden = false;
  $("#jobtitle").textContent = "后台任务 · " + title;
  $("#jlog").textContent = "";
  if (timer) { clearInterval(timer); timer = null; }
  var tick = async function () {
    var s;
    try { s = await (await fetch("/progress/" + id)).json(); }
    catch (e) { return; }
    if (!s || s.ok === false) return;
    renderJob(s);
    if (s.state === "done" || s.state === "error") {
      if (timer) { clearInterval(timer); timer = null; }
      if (s.state === "done" && s.result) showResult(s.result);
    }
  };
  tick();
  timer = setInterval(tick, META.poll_ms);
}
function renderJob(s) {
  var pct = (s.state === "done") ? 100 : (s.percent || 0);
  $("#fill").style.width = pct + "%";
  $("#bar").classList.toggle("indet", !s.total && s.state !== "done");
  var names = {queued: "排队中", running: "运行中", done: "完成", error: "失败"};
  $("#jstate").textContent = (names[s.state] || s.state) + (s.message ? " · " + s.message : "");
  $("#jpct").textContent = s.total ? (s.done + "/" + s.total + " · " + pct.toFixed(1) + "%")
                                   : (pct.toFixed(0) + "%");
  $("#jelapsed").textContent = fmt(s.elapsed_s, 1) + " s";
  var log = $("#jlog");
  log.textContent = (s.logs || []).join("\n");
  log.scrollTop = log.scrollHeight;
  if (s.error) msg(s.error, "err");
}
function trajRows(r) {
  var rows = [];
  if (r.preview) {
    rows.push(["口径", r.note || "预览，未解算"]);
    rows.push(["基准弹", (r.standard || "") + "（" + (r.native || "") + "）"]);
    rows.push(["档位", r.tier]);
    rows.push(["钉死开机时刻", fmt(r.t_beam_s, 2) + " s（留空 = 正式出图时反求）"]);
    rows.push(["想定（目标航迹）", r.scene_text]);
    rows.push(["耗时", fmt(r.elapsed_s, 3) + " s"]);
    return rows;
  }
  var done = {true: "转完了", false: "没转完（39 指令截断了 crank 转弯）"};
  rows.push(["结局", r.hit ? "命中 " + fmt(r.t_hit_s, 3) + " s"
                           : "未命中 " + fmt(r.miss_m, 1) + " m"]);
  rows.push(["基准弹", (r.standard || "") + "（" + (r.native || "") + "）"]);
  rows.push(["(β, γ)", fmt(r.beta, 1) + " / " + fmt(r.gamma, 2) + " kg/m²"]);
  rows.push(["档位 / 后端", r.tier + " / " + fmt(r.backend, 0)]);
  rows.push(["导引头开机 t_beam", fmt(r.t_beam_s, 2) + " s"
      + (r.anchor_mode ? "（" + r.anchor_mode + "）" : "")]);
  if (r.range_at_beam_m !== null && r.range_at_beam_m !== undefined)
    rows.push(["开机那一刻距离", fmt(r.range_at_beam_m, 0) + " m"]);
  rows.push(["开机距离", fmt((r.lock_distance_m || 0) / 1000, 1) + " km"]);
  rows.push(["反应延迟 / 39 指令", fmt(r.react_delay_s, 2) + " s / " + fmt(r.t_react_s, 2) + " s"]);
  rows.push(["开机时航向 / crank 是否转完",
      fmt(r.heading_at_beam_deg, 1) + "° / "
      + ((r.completed === true || r.completed === false) ? done[r.completed] : r.completed_text)
      + (r.t_crank_turn_end_s === null || r.t_crank_turn_end_s === undefined
         ? "" : "（crank 转完于 " + fmt(r.t_crank_turn_end_s, 2) + " s）")]);
  if (r.pass1_hit !== null && r.pass1_hit !== undefined)
    rows.push(["第一遍（不含 39 腿）", r.pass1_hit ? "命中 " + fmt(r.pass1_t_hit_s, 3) + " s"
                                                  : "未命中"]);
  rows.push(["目标震荡", r.weave ? "开启" : "关（用户经验默认值待提供）"]);
  rows.push(["航迹分段", fmt(r.n_segments, 0) + " 段"]);
  rows.push(["想定（仅仿真层用）", r.scene_text]);
  rows.push(["耗时", fmt(r.elapsed_s, 1) + " s"]);
  return rows;
}
function partName(p) {
  // 每张图的摘要都**自带** figure 键（`summarize_plane/bg/traj`），所以这里逐个显式认领；
  // 认不出来就直说，**不要**再"默认当图1"（那正是 D10 的成因：缺省语义）。
  if (p.figure === "plane") return "图1（ΔV–BC）";
  if (p.figure === "bg") return "图2（β–γ）";
  if (p.figure === "traj") return "图3（机动想定）";
  return "未识别的图：" + p.figure;
}
function partHeadline(p) {
  if (p.figure === "traj") {
    return (p.preview ? "预览（未解算）"
                      : (p.hit ? "命中 " + fmt(p.t_hit_s, 3) + " s"
                               : "未命中 " + fmt(p.miss_m, 1) + " m"))
           + " · 耗时 " + fmt(p.elapsed_s, 1) + " s";
  }
  if (p.figure !== "plane" && p.figure !== "bg") return "页面不认识这一份，请看原始 JSON";
  var hit = p.with_iso ? "命中 " + p.n_hit + " / " + p.n_cases : "只出图（不扫描）";
  return hit + " · 基准弹 " + (p.standard || "") + " · 耗时 " + fmt(p.elapsed_s, 1) + " s";
}
function showAllResult(r) {
  // both = 图1+图2（与 CLI `--figure both` 对齐），all = 三张；标题如实说，别把 both 说成三张。
  $("#restitle").textContent = (r.figure === "both")
      ? "两张图结果（图1 + 图2）" : "三张图结果（图1 + 图2 + 图3）";
  var rows = [];
  (r.parts || []).forEach(function (p) { rows.push([partName(p), partHeadline(p)]); });
  rows.push(["产物总数", (r.figure_urls || []).length + " 张图"]);
  rows.push(["总耗时", fmt(r.elapsed_s, 1) + " s"]);
  table(rows);
  showFigures(r.figure_urls, r.figures || []);
}
function showResult(r) {
  $("#rescard").hidden = false;
  var rows = [];
  if (r.figure === "both" || r.figure === "all") { showAllResult(r); return; }
  if (r.figure === "traj") {
    $("#restitle").textContent = r.preview ? "图3 预览结果（未解算）"
                                           : "图3 机动想定结果（crank → 39）";
    table(trajRows(r));
    showFigures(r.figure_urls, (r.paths && r.paths.figures) || r.figures || []);
    return;
  }
  if (r.figure === "bg") {
    $("#restitle").textContent = r.with_iso ? "图2 扫描结果（β–γ）" : "图2 出图结果（β–γ）";
    if (r.with_iso) rows.push(["命中", r.n_hit + " / " + r.n_cases
        + (r.hit_rate === null || r.hit_rate === undefined
           ? "" : "（" + (100 * r.hit_rate).toFixed(0) + "%）")]);
    rows.push(["档位 / 后端", r.tier + " / " + fmt(r.backend, 0)]);
    rows.push(["基准弹", r.standard + "（散点 " + (r.missiles || []).length + " 型）"]);
    rows.push(["仿真层固定 ΔV", fmt(r.dv_pin, 2) + " m/s（留空 = 基准弹标称）"]);
    if (r.reference) rows.push(["参考工况", fmt(r.reference.alt_m / 1000, 0) + " km / "
        + fmt(r.reference.speed_ms, 0) + " m/s（Ma " + fmt(r.reference.mach, 2)
        + "，q " + fmt(r.reference.q_pa / 1000, 1) + " kPa）"]);
    rows.push(["参考过载 n", fmt(r.n_ref, 0) + " G（决定 R / β_eff）"]);
    if (r.t_hit_range_s) rows.push(["t_hit 范围", fmt(r.t_hit_range_s[0], 2) + " ~ "
        + fmt(r.t_hit_range_s[1], 2) + " s"]);
    if (r.iso_levels && r.iso_levels.length) rows.push(["等时线层级",
        r.iso_levels.join(" / ") + " s"]);
    var mono = function (m, dir) {
      return dir + "方向非单调 " + m.n_non_monotonic + " 处（最大违背 "
             + fmt(m.max_increase_s, 3) + " s）";
    };
    if (r.monotonic_beta) rows.push(["单调性自检 β", mono(r.monotonic_beta, "β 递减应为 0，")]);
    if (r.monotonic_gamma) rows.push(["单调性自检 γ", mono(r.monotonic_gamma, "γ 递增应为 0，")]);
    rows.push(["想定（仅仿真层用）", r.scene_text]);
    rows.push(["耗时", fmt(r.elapsed_s, 1) + " s"]);
    table(rows);
    showFigures(r.figure_urls, (r.paths && r.paths.figures) || []);
    return;
  }
  if (r.figure !== undefined && r.figure !== null && r.figure !== "plane") {
    // 兜底：后端加了分支而页面还没接 —— 直说，**不要**静默当成图1（D10 的教训）。
    $("#restitle").textContent = "未识别的 figure 分支：" + r.figure;
    table([["提示", "后端返回的 figure 页面还不认识，请把这条截图给维护者。"],
           ["原始 figure", String(r.figure)]]);
    return;
  }
  $("#restitle").textContent = r.with_iso ? "扫描结果" : "出图结果";
  if (r.with_iso) rows.push(["命中", r.n_hit + " / " + r.n_cases
      + (r.hit_rate === null ? "" : "（" + (100 * r.hit_rate).toFixed(0) + "%）")]);
  rows.push(["档位 / 后端", r.tier + " / " + fmt(r.backend, 0)]);
  rows.push(["基准弹", r.standard + "（散点 " + (r.missiles || []).length + " 型）"]);
  rows.push(["耗时", fmt(r.elapsed_s, 1) + " s"]);
  if (r.grid) rows.push(["网格", r.grid.n_dv + "×" + r.grid.n_bc + " = " + r.grid.n_cases
      + " 工况（ΔV 步长 " + fmt(r.grid.dv_step, 0) + " / BC 步长 " + fmt(r.grid.bc_step, 0) + "）"]);
  if (r.t_hit_range_s) rows.push(["t_hit 范围", fmt(r.t_hit_range_s[0], 2) + " ~ "
      + fmt(r.t_hit_range_s[1], 2) + " s"]);
  if (r.iso_levels && r.iso_levels.length) rows.push(["等时线层级", r.iso_levels.join(" / ") + " s"]);
  if (r.monotonic) rows.push(["单调性自检", "非单调格点 " + r.monotonic.n_non_monotonic
      + " 处（最大违背 " + fmt(r.monotonic.max_increase_s, 3) + " s）"]);
  rows.push(["想定", r.scene_text]);
  table(rows);
  showFigures(r.figure_urls, (r.paths && r.paths.figures) || []);
}
function showSingle(body) {
  var s = body.shot || {};
  $("#rescard").hidden = false;
  $("#restitle").textContent = "单工况结果";
  table([
    ["命中", s.hit ? "是" : "否"],
    ["t_hit", fmt(s.t_hit, 4) + " s"],
    ["最高点 max_alt", fmt(s.max_alt_m, 1) + " m"],
    ["末速 v_impact", fmt(s.v_impact, 1) + " m/s"],
    ["终止事件 event", s.event || "—"],
    ["后端 backend", s.backend || "—"],
    ["最近距离 miss", fmt(s.miss_m, 1) + " m"],
    ["燃尽时刻", fmt(s.t_burnout, 3) + " s"],
    ["飞行时长 t_end", fmt(s.t_end, 3) + " s"],
    ["弹 / 档位", (body.missile || "") + "（" + (body.native || "") + "） / " + (body.tier || "")],
    ["想定", body.scene_text || ""],
    ["求解耗时", fmt(body.elapsed_s, 3) + " s"]
  ]);
  showFigures([], []);
}
async function busy(btn, fn) {
  btn.disabled = true;
  try { await fn(); }
  catch (e) { msg("请求失败：" + e, "err"); }
  finally { btn.disabled = false; }
}
// 按钮标题跟着"出哪张图"走 —— 同一排按钮在不同图上的含义不同，标题骗人比没有标题更糟。
function figTitle(base) {
  var f = inp("figure") ? inp("figure").value : "plane";
  if (f === "traj") return "图3·" + base;
  if (f === "both") return "图1+图2·" + base;
  if (f === "all") return "三张图·" + base;
  return (f === "bg") ? "图2·" + base : base;
}
if (inp("preset")) {
  inp("preset").onchange = function (e) {
    var p = PRESETS[e.target.value];
    if (p && p.form) {
      DIRTY.clear();          // 换预置 = 从头开始，先前的手改记录一并作废
      fillForm(p.form);
      saveLocal();
    }
  };
}
if ($("#forget")) {
  $("#forget").onclick = function () {
    try { localStorage.removeItem(LS_KEY); } catch (e) {}
    DIRTY.clear();
    msg("已忘记上次输入；刷新后回到默认值。", "ok");
  };
}
restoreLocal();
$("#bs").onclick = function () {
  var btn = this;
  // 单工况试算跑的是图1 的散点工况；选 traj / both / all 时它答非所问，索性直接说清楚，
  // 而不是给它一个"看起来正常"的答案。
  var f = inp("figure") ? inp("figure").value : "plane";
  if (f === "traj" || f === "both" || f === "all") {
    msg("单工况试算跑的是图1 的散点工况。"
        + (f === "traj" ? "图3" : (f === "both" ? "图1+图2" : "选 all 时"))
        + "请用下面两个提交按钮（后台 + 进度条）。", "err");
    return;
  }
  busy(btn, async function () {
    msg("");
    clearFieldMarks();
    var r = await post("/api/single", collect());
    if (!r.body.ok) { showFailure(r.body, "单工况失败"); return; }
    showSingle(r.body);
    msg("单工况完成（" + fmt(r.body.elapsed_s, 3) + " s）。正在后台出图，稍等…", "ok");
    var q = await post("/api/submit", Object.assign(collect(), {kind: "plot"}));
    if (!q.body.ok) { showFailure(q.body, "出图任务提交失败"); return; }
    startPoll(q.body.id, figTitle("单点图（不扫描）"));
  });
};
$("#bk").onclick = function () {
  var btn = this;
  busy(btn, async function () {
    msg("");
    clearFieldMarks();
    var r = await post("/api/submit", Object.assign(collect(), {kind: "scan"}));
    if (!r.body.ok) { showFailure(r.body, "提交失败"); return; }
    msg("已提交扫描任务（后台跑，可继续操作页面）。", "ok");
    startPoll(r.body.id, figTitle("扫描 + 等时线"));
  });
};
$("#bp").onclick = function () {
  var btn = this;
  busy(btn, async function () {
    msg("");
    clearFieldMarks();
    var r = await post("/api/submit", Object.assign(collect(), {kind: "plot"}));
    if (!r.body.ok) { showFailure(r.body, "提交失败"); return; }
    msg("已提交出图任务（后台跑）。", "ok");
    startPoll(r.body.id, figTitle("只出图（不扫描）"));
  });
};

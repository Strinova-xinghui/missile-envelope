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
  if (!box) return;              // 图3 / 查看器页也加载本文件，那两页没有 #msg
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
function figBoxOf(url) {
  // 产物名就带图号：`fig_isotime_plane_*` = 图1（ΔV–β），`fig_bg_plane_*` = 图2（β–ginv）。
  return (String(url).indexOf("fig_bg_plane") >= 0) ? $("#fig2box") : $("#fig1box");
}
function showFigures(urls, paths) {
  (urls || []).forEach(function (u) {
    var box = figBoxOf(u);
    var st = box.querySelector("img.static");      // 静态形态（11 点）让位给真结果
    if (st) { box.removeChild(st); }
    // ⚠ 这个函数会被调**两次**（块渲染一次、整任务 done 的合并摘要再一次）：追加式会出两张同图。
    var old = box.querySelector("img.result");
    if (old) { box.removeChild(old); }
    var im = document.createElement("img");
    im.className = "result";
    im.src = u + "?t=" + Date.now();
    box.appendChild(im);
    poolAfterResult(box);       // 本次结果来了 ⇒ 卡片上的形态切到"本次结果"那一版
  });
  if (paths && paths.length) {
    var pre = document.createElement("pre");
    pre.textContent = paths.join("\n");
    $("#rescard").appendChild(pre);
  }
}
// 图4（沙盒）**只在有任务时出现**：没有工况就不显示、不跑、也不回放仓库旧产物。
function showSandbox(job, r) {
  var sec = $("#fig4");
  if (!job) { sec.hidden = true; return; }
  sec.hidden = false;
  var bits = [];
  if (r) {
    if (r.standard) { bits.push("基准弹 " + r.standard); }
    if (r.scene_text) { bits.push(r.scene_text); }
    if (r.tag) { bits.push("tag=" + r.tag); }
  }
  $("#fig4case").textContent = bits.length
    ? ("本次展示的工况 —— " + bits.join(" · "))
    : "本次展示的工况：图4 这一块还在跑（跑完这里会写上是哪次工况）；"
      + "摘要里若没带工况文字，请以左栏输入为准。";
  if (!r) { return; }                       // 结果还没出来：先别给 iframe 设 src
  loadSandboxFrame(job);                    // 这一块就绪就能取数（见上面 loadSandboxFrame 的注释）
  if (sec.scrollIntoView) { sec.scrollIntoView({block: "start"}); }
}
// 沙盒（`/api/sandbox/<job>`）与查看器（`/api/viewer3d/<job>`）**按块就绪**就能取数
// （服务端 `webui.block_ready()`，2026-10-03 裁决 1）：图4 块 ≈1 s 就好，整任务要 ≈60 s ——
// 用"整任务 done"当闸门，用户就得盯着空沙盒等一分钟，与"给定输入后置顶显示沙盒"直接冲突。
// ⚠ 同一块只装一次：重复装会叠出一堆空 iframe（C3 修过的那一族）。
function loadSandboxFrame(job) {
  if (!job) { return; }
  var f = $("#fig4frame");
  if (!f) { return; }
  var url = "/fig4?job=" + encodeURIComponent(job);
  if (f.getAttribute("src") !== url) { f.setAttribute("src", url); }
}
var RENDERED = {job: null, blocks: {}};
// 四块提交：**每块跑完就渲染那一块**，不等整任务（用户口径："沙盒一出结果就置顶显示"）。
// 以前只有整任务 `done` 才走 `showFourResult()` —— 那会让沙盒等到四块全跑完才出现，
// 与"置顶显示沙盒"直接冲突（2026-10-03 改）。同一块只渲染一次；重新提交换 job id 会重置。
// 图注：两份文本都由服务端给（`index.html` 里预渲染的那两份 + 摘要里的 `figure_notes`），
// 页面只负责"显示哪一份"。判据是**这一跑自己的 `with_iso`**，不是"有没有结果图" ——
// ⚠ 曾经按"结果图一上来就切扫描版"写，于是 `#bp`（只出图不扫描）会让页面上挂着
// "本次已跑仿真层"，替用户宣布没发生的事（2026-10-04 用户路径实测踩到）。
function showNotes(box, lines, scan) {
  var card = box && box.closest ? box.closest("section.card") : null;
  if (!card) { return; }
  var stat = card.querySelector("ul.notes-static");
  var scanUl = card.querySelector("ul.notes-scan");
  if (stat && scanUl && typeof scan === "boolean") {
    stat.hidden = scan;
    scanUl.hidden = !scan;
  }
  var ul = (scanUl && !scanUl.hidden) ? scanUl
        : ((stat && !stat.hidden) ? stat : (stat || scanUl || card.querySelector("ul.notes")));
  if (!ul || !lines || !lines.length) { return; }   // 没带文本就只切显示，不动内容
  ul.textContent = "";
  lines.forEach(function (t) {
    var li = document.createElement("li");
    li.textContent = String(t);
    ul.appendChild(li);
  });
}
function applyResultNotes(r) {
  if (!r) { return; }
  var parts = (r.parts && r.parts.length) ? r.parts : [r];
  parts.forEach(function (p) {
    if (!p || (p.figure !== "bg" && p.figure !== "plane")) { return; }   // 图4/图3 没有这份图注
    var box = p.figure === "bg" ? $("#fig2box") : $("#fig1box");
    showNotes(box, p.figure_notes, typeof p.with_iso === "boolean" ? p.with_iso : undefined);
  });
}
function renderBlockResults(s, id) {
  // 四块任务：每块跑完就把那一块的图注换成"这次"的说法（各块自带 figure_notes）
  if (s && s.blocks) {
    Object.keys(s.blocks).forEach(function (k) {
      var b = s.blocks[k];
      if (b && b.result) { applyResultNotes(b.result); }
    });
  }
  if (!s || !s.blocks || !id) { return; }
  if (RENDERED.job !== id) { RENDERED.job = id; RENDERED.blocks = {}; }
  ["fig4", "fig1", "fig2", "fig3"].forEach(function (k) {
    var b = s.blocks[k] || {};
    if (RENDERED.blocks[k] || b.state !== "done" || !b.result) { return; }
    RENDERED.blocks[k] = true;
    var one = b.result;
    if (k === "fig4") {
      showSandbox(id, one);                 // 沙盒：置顶 + iframe 立刻指向这次工况
      showViewer3d(id);
    } else if (k === "fig1" || k === "fig2") {
      showFigures(one.figure_urls, (one.paths && one.paths.figures) || one.figures || []);
    } else if (k === "fig3") {
      var f3 = $("#fig3frame");
      // `iso=1`：这一块**不用用户点"生成等时面"**，页面自己去拉基准弹那枚等时面（裁决 2）。
      var u3 = "/fig3?job=" + encodeURIComponent(id) + "&iso=1";
      if (f3 && f3.getAttribute("src") !== u3) { f3.setAttribute("src", u3); }
    }
  });
}
var timer = null;
// 当前后台任务的 id —— 3D 查看器（`/viewer3d?job=`）要用它换数据；
// 结果摘要里**不带** id（`summarize_*` 是纯产物摘要），所以由轮询这一处记下来。
var CURJOB = null;
function startPoll(id, title) {
  CURJOB = id;
  RENDERED.job = id; RENDERED.blocks = {};
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
    renderBlockResults(s, id);
    if (s.state === "done" || s.state === "error") {
      if (timer) { clearInterval(timer); timer = null; }
      if (s.state === "done") {
        // 收尾再装一次（幂等）：单跑一张图4 的任务**没有块台账**，全靠这里装；
        // 四块任务里正常情况下块就绪时就装好了，这两行是空操作。
        loadSandboxFrame(id);               // 沙盒回放
        showViewer3d(id);                   // 图4 可拖拽三维轨迹（只嵌一个）
      }
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
  renderBlocks(s.blocks);
  if (s.error) msg(s.error, "err");
}
// 四块各自的进度/成败：一次提交出四块时，谁跑完了、谁挂了、为什么，全在这张表里。
function renderBlocks(blocks) {
  var tab = $("#blocktab");
  if (!tab) { return; }
  var names = Object.keys(blocks || {}).sort(function (x, y) {
    return ((blocks[x] || {}).order || 0) - ((blocks[y] || {}).order || 0);
  });
  tab.hidden = names.length === 0;
  if (!names.length) { return; }
  tab.innerHTML = "";
  var words = {queued: "排队", running: "跑…", done: "完成", error: "失败", skipped: "跳过"};
  names.forEach(function (k) {
    var b = blocks[k] || {};
    var tr = document.createElement("tr");
    var td0 = document.createElement("td");
    td0.textContent = b.title || k;
    var td1 = document.createElement("td");
    td1.textContent = words[b.state] || b.state || "";
    td1.className = (b.state === "error") ? "bad" : "";
    var td2 = document.createElement("td");
    td2.textContent = b.error || b.message || "";
    tr.appendChild(td0); tr.appendChild(td1); tr.appendChild(td2);
    tab.appendChild(tr);
  });
}
function fourRows(r) {
  var rows = [["提交", "一次提交四块（沙盒置顶，四块共用这一份输入）"]];
  var blocks = r.blocks || {};
  var words = {queued: "排队", running: "跑…", done: "完成", error: "失败", skipped: "跳过"};
  Object.keys(blocks).sort(function (x, y) {
    return ((blocks[x] || {}).order || 0) - ((blocks[y] || {}).order || 0);
  }).forEach(function (k) {
    var b = blocks[k] || {};
    var one = b.result || {};
    var bits = [words[b.state] || b.state || ""];
    if (one.n_hit !== undefined && one.n_cases) { bits.push("命中 " + one.n_hit + "/" + one.n_cases); }
    if (one.t_hit_s !== undefined && one.t_hit_s !== null) { bits.push("t_hit " + fmt(one.t_hit_s, 1) + " s"); }
    if (one.n_points !== undefined) { bits.push("标称点 " + one.n_points + " 个"); }
    if (one.face) { bits.push("等时面 " + one.face.missile + " " + one.face.n_cases + " 工况"
                              + (one.face.read_hit ? "（缓存）" : "")); }
    if (one.elapsed_s !== undefined) { bits.push(fmt(one.elapsed_s, 1) + " s"); }
    if (b.error) { bits.push("原因：" + b.error); }
    rows.push([b.title || k, bits.join(" · ")]);
  });
  if (r.blocks_failed && r.blocks_failed.length) {
    rows.push(["结论", "有 " + r.blocks_failed.length + " 块失败 —— 本次提交不算成功"]);
  }
  return rows;
}
function showFourResult(r) {
  $("#restitle").textContent = "一次提交 · 四块结果";
  table(fourRows(r));
  var blocks = r.blocks || {};
  ["fig1", "fig2"].forEach(function (k) {
    var one = ((blocks[k] || {}).result) || null;
    if (one) { showFigures(one.figure_urls, (one.paths && one.paths.figures) || one.figures || []); }
  });
  var t4 = ((blocks.fig4 || {}).result) || null;
  if (CURJOB) {
    showSandbox(CURJOB, t4);
    if (t4) { showViewer3d(CURJOB); }
  }
}
function trajRows(r) {
  var rows = [];
  var done = {true: "转完了", false: "没转完（39 指令截断了 crank 转弯）"};
  // 命中报**真最近接近距离**（cpa_m，关引信复跑量）；未命中才有"脱靶量"这回事
  // （min_separation_m）。命中时内核那个数是引信半径 10 m，当脱靶量显示就是 A5。
  rows.push(["结局", r.hit ? "命中 " + fmt(r.t_hit_s, 3) + " s · 最近接近 "
                             + fmt(r.cpa_m, 4) + " m"
                           : "未命中 " + fmt(r.min_separation_m, 1) + " m"]);
  rows.push(["基准弹", (r.standard || "") + "（" + (r.native || "") + "）"]);
  rows.push(["(β, ginv)", fmt(r.beta, 1) + " / " + fmt(r.ginv, 6) + " m²/kg"]);
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
// ---------------------------------------------------------------- 图4 的 3D
// 内嵌 + 另开一个标签页，两件事都要：
//   * iframe 里就是整页查看器（`bg=transparent` 让画布融入卡片，不再套一层深色底）；
//   * 链接指向**同一个 job** 的独立页（去掉 bg），可以拉大、可以单独留在屏幕上看。
// `job` 由 `CURJOB` 给（结果摘要里没有 id）；点数走服务端默认（800），页面不写死。
function viewer3dUrl(job, transparent) {
  return "/viewer3d?job=" + encodeURIComponent(job) + (transparent ? "&bg=transparent" : "");
}
function showViewer3d(job, note) {
  var box = $("#fig4");
  if (box.querySelector(".v3d")) { return; }  // 同一块只嵌一个：重复调用会叠出一堆空 iframe
  var card = document.createElement("div");
  card.className = "v3d";
  var bar = document.createElement("div");
  bar.className = "v3dbar";
  var span = document.createElement("span");
  span.textContent = note || "可拖拽三维轨迹：左键旋转 / 滚轮缩放 / 右键（或 Shift + 左键）平移";
  var a = document.createElement("a");
  a.href = viewer3dUrl(job, false);
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = "在新标签页打开";
  bar.appendChild(span);
  bar.appendChild(a);
  var fr = document.createElement("iframe");
  fr.className = "v3dframe";
  fr.src = viewer3dUrl(job, true);
  fr.title = "图4 三维轨迹查看器（可拖拽）";
  fr.setAttribute("loading", "lazy");
  card.appendChild(bar);
  card.appendChild(fr);
  box.appendChild(card);
  return card;
}
// 合并摘要里有图4 那一段就嵌入。
function trajPart(r) {
  if (r && r.figure === "traj") return r;
  var parts = (r && r.parts) || [];
  for (var i = 0; i < parts.length; i++) {
    if (parts[i].figure === "traj") return parts[i];
  }
  return null;
}
function partName(p) {
  // 每张图的摘要都**自带** figure 键（`summarize_plane/bg/traj`），所以这里逐个显式认领；
  // 认不出来就直说，**不要**再"默认当图1"（那正是 D10 的成因：缺省语义）。
  if (p.figure === "plane") return "图1（ΔV–BC）";
  if (p.figure === "bg") return "图2（β–ginv）";
  if (p.figure === "traj") return "图4（机动想定）";
  return "未识别的图：" + p.figure;
}
function partHeadline(p) {
  if (p.figure === "traj") {
    return (p.hit ? "命中 " + fmt(p.t_hit_s, 3) + " s"
                  : "未命中 " + fmt(p.min_separation_m, 1) + " m")
           + " · 耗时 " + fmt(p.elapsed_s, 1) + " s";
  }
  if (p.figure !== "plane" && p.figure !== "bg") return "页面不认识这一份，请看原始 JSON";
  var hit = p.with_iso ? "命中 " + p.n_hit + " / " + p.n_cases : "只出图（不扫描）";
  return hit + " · 基准弹 " + (p.standard || "") + " · 耗时 " + fmt(p.elapsed_s, 1) + " s";
}
function showAllResult(r) {
  // both = 图1+图2（与 CLI `--figure both` 对齐），all = 三张；标题如实说，别把 both 说成三张。
  $("#restitle").textContent = (r.figure === "both")
      ? "两张图结果（图1 + 图2）" : "三张图结果（图1 + 图2 + 图4）";
  var rows = [];
  (r.parts || []).forEach(function (p) { rows.push([partName(p), partHeadline(p)]); });
  rows.push(["产物总数", (r.figure_urls || []).length + " 张图"]);
  rows.push(["总耗时", fmt(r.elapsed_s, 1) + " s"]);
  table(rows);
  showFigures(r.figure_urls, r.figures || []);
  if (trajPart(r) && CURJOB) showViewer3d(CURJOB, "可拖拽三维轨迹（图4 那一段）");
}
function showResult(r) {
  applyResultNotes(r);
  $("#rescard").hidden = false;
  var rows = [];
  if (r.figure === "four") { showFourResult(r); return; }
  if (r.figure === "both" || r.figure === "all") { showAllResult(r); return; }
  if (r.figure === "traj") {
    $("#restitle").textContent = "图4 机动想定结果（crank → 39）";
    table(trajRows(r));
    showFigures(r.figure_urls, (r.paths && r.paths.figures) || r.figures || []);
    if (CURJOB) {
      showSandbox(CURJOB, r);
      showViewer3d(CURJOB);
    }
    return;
  }
  if (r.figure === "bg") {
    $("#restitle").textContent = r.with_iso ? "图2 扫描结果（β–ginv）" : "图2 出图结果（β–ginv）";
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
    if (r.monotonic_ginv) rows.push(["单调性自检 ginv", mono(r.monotonic_ginv, "ginv 递增应为 0，")]);
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
    // 命中时**不要**报"脱靶量"：内核那个数是引信半径（10 m）。真精度看 cpa_m，
    // 未命中才有脱靶量这回事（min_separation_m）。见 solver.Shot 的 docstring。
    // ⚠ CPA 用 4 位小数：它常在 1e-4~1e-3 m 量级，2/3 位会显示成 "0.000 m"。
    ...(s.hit
      ? [["最近接近 cpa（关引信复跑）", fmt(s.cpa_m, 4) + " m"],
         ["引信半径 fuse_radius", fmt(s.fuse_radius_m, 1) + " m"]]
      : [["脱靶量 min_separation", fmt(s.min_separation_m, 1) + " m"],
         ["引信半径 fuse_radius", fmt(s.fuse_radius_m, 1) + " m"]]),
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
  if (f === "traj") return "图4·" + base;
  if (f === "both") return "图1+图2·" + base;
  if (f === "all") return "三张图·" + base;
  return (f === "bg") ? "图2·" + base : base;
}
// ============================================================ 统一左栏骨架
// 用户 2026-10-02 拍板：四页照 statshark —— 左栏 = 输入（可折叠、可滚动），右栏 = 主视图。
// 样式与 class 口径见 `app.css` 末尾那一节（沙盒页照同一套写，别再各写一份）。
// 这里只管行为：折叠状态存 localStorage；预设 chip **真的**改输入框的值。
var RAIL_KEY = "missile-sim:rail";
function applyRail(collapsed) {
  var shell = $("#shell");
  if (!shell) return;
  shell.classList.toggle("rail-collapsed", !!collapsed);
  var btn = $("#railtoggle");
  if (!btn) return;
  btn.textContent = collapsed ? "›" : "‹";
  btn.title = collapsed ? "展开输入栏" : "折叠输入栏";
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
}
function railStartCollapsed() {
  try {
    var v = localStorage.getItem(RAIL_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch (e) {}
  return window.innerWidth < 900;        // 没存过：窄屏默认收起（那种宽度下左栏是抽屉）
}
if ($("#railtoggle")) {
  $("#railtoggle").onclick = function () {
    var collapsed = !$("#shell").classList.contains("rail-collapsed");
    applyRail(collapsed);
    try { localStorage.setItem(RAIL_KEY, collapsed ? "1" : "0"); } catch (e) {}
  };
  applyRail(railStartCollapsed());
}
// ---- 预设 chip ---------------------------------------------------------------
// 判据（真浏览器验收）：点 chip ⇒ 输入框的值变 ⇒ 下一次请求的 body 变 ⇒ 结果变。
// 所以 chip 走 fillForm（程序性赋值不触发 input ⇒ 不会被记成"手改"），并且把背后那个
// **唯一的字段**（hidden 的 <select>）一起改掉 —— 这样"点 chip"与"改下拉"在请求里是同一件事。
function envPresetOf(name) {
  var key = String(name || "");
  if (!key || key.charAt(0) === "_") return null;   // `_keys` 是保留键，不是预设
  return (ENVPRESETS || {})[key] || null;
}
function activeEnvPreset() {
  var el = inp("env_preset");
  return el ? String(el.value || "") : "";
}
// 预设只管这些字段（`_keys` 由服务端给）。**视图与输出**设置（figure / tag / jobs /
// 网格步长…）不在预设层里 —— 拿它们点"已偏离预设"会变成"一开页面就报警"。
function envKeys() {
  var keys = (ENVPRESETS || {})["_keys"];
  return (keys && keys.length) ? keys : [];
}
// 预设只发"与首屏初值的差异"（9 份预设 × 18 字段原样铺开会把首页顶破 20 KB 的判据）。
// 这里用 DEFAULTS + 差值还原出完整表单 —— chip 点下去照样把每个框填成该预设的值。
function presetForm(item) {
  var form = {};
  Object.keys(DEFAULTS || {}).forEach(function (k) { form[k] = DEFAULTS[k]; });
  var d = (item && item.d) || {};
  Object.keys(d).forEach(function (k) { form[k] = d[k]; });
  return form;
}
function numericText(text) {
  return /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/.test(text);
}
function sameValue(a, b) {
  // 预设里是数字（50000.0），输入框里是字符串（"50000"）—— 直接比字符串会**永远**显示
  // "已偏离预设"。两边都是纯数字时按数值比，其余按去掉首尾空白后的字符串比。
  var sa = (a === null || a === undefined) ? "" : String(a).trim();
  var sb = (b === null || b === undefined) ? "" : String(b).trim();
  if (sa === sb) return true;
  if (sa !== "" && sb !== "" && numericText(sa) && numericText(sb)) {
    return Math.abs(parseFloat(sa) - parseFloat(sb)) < 1e-9;
  }
  return false;
}
function envDrift() {
  var pre = envPresetOf(activeEnvPreset());
  if (!pre) return [];
  var want = presetForm(pre);
  var out = [];
  envKeys().forEach(function (k) {
    var el = inp(k);
    if (!el) return;
    var cur = String(el.value === null || el.value === undefined ? "" : el.value).trim();
    if (cur === "") return;       // 空 = "用预设/默认"，不算偏离（清空不是改值）
    if (!sameValue(cur, want[k])) out.push(k);
  });
  return out;
}
function syncEnvChips() {
  var cur = activeEnvPreset();
  document.querySelectorAll("[data-env-preset]").forEach(function (b) {
    b.classList.toggle("on", b.getAttribute("data-env-preset") === cur);
  });
  var badge = $("#envdirty");
  if (!badge) return;
  var drift = envDrift();
  badge.hidden = drift.length === 0;
  badge.title = drift.length ? ("已偏离预设的字段：" + drift.join("、")) : "";
}
function applyEnvPreset(name) {
  var pre = envPresetOf(name);
  if (!pre) return false;
  fillForm(presetForm(pre));           // 环境字段 + 基准弹 + 档位 + 参考工况，一起换
  // ⚠ **必须**把这些字段记成"手改"（`_dirty`）：服务端 `targets.build_scene()` 对
  // `_dirty` 里没有的字段会**丢弃表单值、回退到默认想定**（真踩过：点「近距」后输入框
  // 显示 20000，请求里也发 20000，可算出来还是 50 km —— 因为 `_dirty` 是空的）。
  // 语义上也对：点 chip 就是用户显式指定了这些值。
  envKeys().forEach(function (k) { if (inp(k)) DIRTY.add(k); });
  var sel = inp("env_preset");
  if (sel) sel.value = name;
  syncEnvChips();
  saveLocal();
  return true;
}
function syncPresetChips() {
  var el = inp("preset");
  var cur = el ? String(el.value || "") : "";
  document.querySelectorAll("[data-preset]").forEach(function (b) {
    b.classList.toggle("on", b.getAttribute("data-preset") === cur);
  });
}
function applyPreset(name) {
  var p = (PRESETS || {})[name];
  if (!p) return false;
  DIRTY.clear();                 // 换预置 = 从头开始，先前的手改记录一并作废
  fillForm(presetForm(p));
  var sel = inp("preset");
  if (sel) sel.value = name;
  syncPresetChips();
  saveLocal();
  return true;
}
// chip 的长说明来自 boot 数据（HTML 里不重复抄一份，见 chips_html 的字节数理由）
document.querySelectorAll("[data-env-preset]").forEach(function (b) {
  var name = b.getAttribute("data-env-preset");
  var pre = envPresetOf(name);
  if (pre && pre.label) b.title = pre.label;
  b.onclick = function () { applyEnvPreset(name); };
});
document.querySelectorAll("[data-preset]").forEach(function (b) {
  var name = b.getAttribute("data-preset");
  var p = (PRESETS || {})[name];
  if (p && p.summary) b.title = p.summary;
  b.onclick = function () { applyPreset(name); };
});
if (inp("env_preset")) {           // 下拉仍在 DOM 里（只是 hidden）：程序改它也要同步 chip
  inp("env_preset").addEventListener("change", syncEnvChips);
}
if (inp("preset")) {
  inp("preset").onchange = function (e) { applyPreset(e.target.value); };
}
// 手改任意一格 ⇒ 重算"是否偏离预设"。DIRTY 的记录在上面的监听里，两者互不干扰。
document.addEventListener("input", function (e) {
  var el = e.target;
  if (!el || !el.getAttribute || !el.getAttribute("data-field")) return;
  syncEnvChips();
}, true);
if ($("#forget")) {
  $("#forget").onclick = function () {
    try { localStorage.removeItem(LS_KEY); } catch (e) {}
    DIRTY.clear();
    msg("已忘记上次输入；刷新后回到默认值。", "ok");
  };
}
restoreLocal();
syncEnvChips();                    // 恢复出来的值与当前预设可能对不上 —— 开机就要如实显示
syncPresetChips();
// ⚠ 下面三段**必须**守卫：图3 页与查看器页也加载本文件（为了共用左栏折叠那一套），
// 那两页没有 #bs / #bk / #bp —— 不守卫就会在 `$("#bs").onclick` 上抛，后面的绑定全死。
if ($("#bs")) {
$("#bs").onclick = function () {
  var btn = this;
  // 单工况试算跑的是图1 的散点工况；选 traj / both / all 时它答非所问，索性直接说清楚，
  // 而不是给它一个"看起来正常"的答案。
  var f = inp("figure") ? inp("figure").value : "plane";
  if (f === "traj" || f === "both" || f === "all") {
    msg("单工况试算跑的是图1 的散点工况。"
        + (f === "traj" ? "图4" : (f === "both" ? "图1+图2" : "选 all 时"))
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
}
if ($("#bk")) {
$("#bk").onclick = function () {
  var btn = this;
  busy(btn, async function () {
    msg("");
    clearFieldMarks();
    // **一次提交出四块**（用户口径 docs/UX-TARGET.md §4-C）：不看「出哪张图」选的是什么，
    // 这个按钮永远提交同一个任务的四块（沙盒置顶 → 图1 → 图2 → 图3）。
    var r = await post("/api/submit", Object.assign(collect(), {kind: "scan", figure: "four"}));
    if (!r.body.ok) { showFailure(r.body, "提交失败"); return; }
    msg("已提交：一个后台任务同时出四块（先行图4 沙盒，再图1、图2、图3）。", "ok");
    startPoll(r.body.id, "一次提交 · 四块");
    showSandbox(r.body.id, null);       // 沙盒块置顶先显形；工况文字等图4 那一块跑完再写
  });
};
}
if ($("#bp")) {
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
}


// 网址里带 `?job=<id>`：恢复那次任务。任务表在服务重启后是空的 —— 这条一定会发生，
// 所以必须给明确提示，而不是留一个白框（用户口径 docs/UX-TARGET.md §3）。
(function () {
  var job = new URLSearchParams(location.search).get("job");
  if (!job) { return; }
  showSandbox(job, null);
  fetch("/progress/" + encodeURIComponent(job)).then(function (x) { return x.json(); })
    .then(function (s) {
      if (!s || s.ok === false) {
        msg("该任务已不存在（服务重启后任务表会清空），请重新提交。", "err");
        $("#fig4").hidden = true;
        return;
      }
      if (s.state === "done" && s.result) { showResult(s.result); }
      else if (s.state === "running" || s.state === "queued") { startPoll(job, "恢复上次任务"); }
    }).catch(function () {});
})();

// ============================================================ 对比弹池（目录驱动，零往返）
// 这一段只做三件事：读一次目录（`GET /api/catalog`）、管选择（`localStorage`）、
// 把选择交给静态层 `window.FIGS2D.mount(host, {kind, catalog, notes})` 的 `setSelection(keys)`。
// 轴与点全部由那一层在客户端现算 ⇒ 切弹池不发任务、不重出图（判据扫这一段源码钉住）。
// 冻结接口见 docs/STATIC-LAYER-REALTIME.md §3；形状要改先报 Lead。
// ⚠ 本文件也被 /fig3 与查看器页加载（共用左栏折叠），所以入口一律按 `#poollist` 是否存在守卫。
var POOL_KEY = "missile-sim:pool";
//: 实时形态那份图注的标题行 —— 静态层按冻结接口只把 `notes` 渲染成 `<ul>`、**一个字都不写**，
//: 所以标题由壳给（与卡片上那条 `<details><summary>` 同一行文字，两种形态读起来一致）。
var POOL_NOTES_TITLE = "图注（原先画在图里，现已移到页面）";
var POOL = {catalog: null, sel: [], views: {}};

function poolHostList() {
  return [{kind: "plane", box: $("#fig1box"), host: $("#fig1host"), bar: $("#fig1bar")},
          {kind: "bg", box: $("#fig2box"), host: $("#fig2host"), bar: $("#fig2bar")}];
}
function poolHost(kind) {
  var all = poolHostList(), i;
  for (i = 0; i < all.length; i++) { if (all[i].kind === kind) { return all[i]; } }
  return null;
}
function poolEntries() {                 // 可算且默认要显示的：目录里没有 `duplicate_of` 孪生
  return ((POOL.catalog || {}).missiles || []).filter(function (m) {
    return m && m.key && !m.duplicate_of && !m.default_hidden;
  });
}
function poolUnsupported() { return ((POOL.catalog || {}).unsupported || []); }
function poolDefault() {
  return poolEntries().filter(function (m) { return m.in_pool11; })
                      .map(function (m) { return String(m.key); });
}
function poolCount() { return (poolEntries().length); }
function poolStat(text) {
  var el = $("#poolstat");
  if (!el) { return; }
  el.hidden = !text;
  el.textContent = text || "";
}
function poolStore(keys) {
  try { localStorage.setItem(POOL_KEY, JSON.stringify(keys)); } catch (e) {}
}
function poolStored() {                  // 存档 → 已按目录校验过的 key 数组；没有/读坏 ⇒ null
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
function poolBuildRows() {               // 建行（只建一次）：可算的上勾选框，不可算的置灰并带原因
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
    nm.textContent = String(m.label || m.key);
    label.appendChild(nm);
    row.appendChild(label);
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = String(m.seeker || "");
    row.appendChild(tag);
    if (m.full_name && m.full_name !== m.label) { row.title = String(m.full_name); }
    list.appendChild(row);
  });
  poolUnsupported().forEach(function (m) {   // 9 条：列出但置灰，悬停给目录里的真实原因
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
    nm.textContent = String(m.label || m.key);
    label.appendChild(nm);
    row.appendChild(label);
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = String(m.seeker || "");
    row.appendChild(tag);
    var why = document.createElement("span");
    why.className = "why";
    why.textContent = String(m.reason || "不可算");
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
function poolFold(text) {                // 目录 key 是 `us_aim_120a` 这种下划线名，用户会打 "aim-120"
  return String(text || "").toLowerCase().replace(/[\s_-]+/g, "");
}
function poolFilter(text) {              // 搜索只切"显不显示"：不改变选择（选择只由勾选框决定）
  var q = poolFold(text);
  document.querySelectorAll("#poollist .pool-row").forEach(function (row) {
    var nm = row.querySelector(".nm");
    var hay = poolFold(String(row.getAttribute("data-key") || "") + " " + (nm ? nm.textContent : ""));
    row.hidden = !!q && hay.indexOf(q) < 0;
  });
}
function poolMark() {                    // 勾选框/计数/徽标/静态层，四处状态一次同步
  var want = {};
  POOL.sel.forEach(function (k) { want[k] = 1; });
  document.querySelectorAll("#poollist .pool-row").forEach(function (row) {
    var cb = row.querySelector("input");
    if (cb && !cb.disabled) { cb.checked = !!want[String(row.getAttribute("data-key"))]; }
  });
  var cat = POOL.catalog || {};
  var cnt = $("#poolcount");
  if (cnt) {
    cnt.textContent = "已选 " + POOL.sel.length + " / 列出 " + poolCount()
      + "（可算 " + (cat.computable || "?") + "/" + (cat.count || "?")
      + "，含 " + poolUnsupported().length + " 条待动态解算）";
  }
  var def = poolDefault(), same = (def.length === POOL.sel.length);
  if (same) { def.forEach(function (k) { if (!want[k]) { same = false; } }); }
  var badge = $("#pooldirty");
  if (badge) { badge.hidden = same; }
  var allKeys = poolEntries().map(function (m) { return String(m.key); });
  var allSame = (allKeys.length === POOL.sel.length);
  if (allSame) { allKeys.forEach(function (k) { if (!want[k]) { allSame = false; } }); }
  var c11 = $("#pool11"), cAll = $("#poolAll"), cNone = $("#poolClear");
  if (c11) { c11.className = same ? "chip on" : "chip"; }
  if (cAll) { cAll.className = allSame ? "chip on" : "chip"; }
  if (cNone) { cNone.className = (POOL.sel.length === 0) ? "chip on" : "chip"; }
  poolHostList().forEach(function (h) {
    var v = POOL.views[h.kind];
    if (v) { v.setSelection(POOL.sel); }
  });
  var st = $("#fig1state");
  if (st) { st.textContent = "选中 " + POOL.sel.length + " 枚 · 客户端现算"; }
  var st2 = $("#fig2state");
  if (st2) { st2.textContent = "选中 " + POOL.sel.length + " 枚 · 客户端现算"; }
}
function poolShow(kind, mode) {          // 形态切换：live = 客户端实时图，result = 本次任务产物
  var h = poolHost(kind);
  if (!h || !h.box) { return; }
  var view = POOL.views[kind];
  var res = h.box.querySelector("img.result");
  var live = (mode !== "result") || !res;
  if (!view) { return; }                 // 没挂上（目录/渲染器缺失）⇒ 什么都不动，保持静态回落
  var st = h.box.querySelector("img.static");
  if (st) { st.hidden = true; }          // 有实时形态了，静态回落那份让位
  h.host.hidden = !live;
  if (res) { res.hidden = live; }
  var card = h.box.closest ? h.box.closest("section.card") : null;
  var notes = card ? card.querySelector("details.fignotes") : null;
  if (notes) { notes.hidden = live; }    // 图注同一时刻只显示一份（实时那份在 host 里）
  var lb = $("#fig1live"), rb = $("#fig1result");
  if (kind === "bg") { lb = $("#fig2live"); rb = $("#fig2result"); }
  if (lb) { lb.className = live ? "on" : ""; }
  if (rb) { rb.className = live ? "" : "on"; rb.disabled = !res; }
}
function poolAfterResult(box) {          // showFigures() 追加了本次结果图 ⇒ 切到 result 那一版
  var kind = (box && box.id === "fig2box") ? "bg" : "plane";
  poolShow(kind, "result");
}
function poolNotes(h) {                  // 图注文本只有服务端一处：读当前可见那条 ul 的行
  var card = h.box && h.box.closest ? h.box.closest("section.card") : null;
  if (!card) { return []; }
  var uls = card.querySelectorAll("ul.notes"), i, j;
  for (i = 0; i < uls.length; i++) {
    if (uls[i].hidden) { continue; }
    var out = [POOL_NOTES_TITLE], lis = uls[i].querySelectorAll("li");
    for (j = 0; j < lis.length; j++) { out.push(String(lis[j].textContent)); }
    return out;
  }
  return [];
}
function poolMount() {                   // 渐进增强：渲染器/目录缺一件就不挂，保持静态回落
  var F = window.FIGS2D;
  if (!F || typeof F.mount !== "function") {
    poolStat("客户端渲染器未加载（figs2d.js）—— 图1/图2 保持静态形态，其他功能不受影响。");
    return;
  }
  var bad = [];
  poolHostList().forEach(function (h) {
    if (!h.host) { return; }
    try {
      POOL.views[h.kind] = F.mount(h.host, {kind: h.kind, catalog: POOL.catalog, notes: poolNotes(h)});
      if (h.bar) { h.bar.hidden = false; }
    } catch (e) {
      POOL.views[h.kind] = null;
      bad.push(h.kind + "：" + ((e && e.message) || e));
    }
  });
  if (bad.length) { poolStat("实时形态挂载失败（" + bad.join("；") + "）—— 保持静态形态。"); }
}
function poolSet(keys, user) {           // 唯一的"改选择"入口：存档 → 同步四处状态
  var known = {};
  poolEntries().forEach(function (m) { known[String(m.key)] = 1; });
  POOL.sel = (keys || []).map(String).filter(function (k) { return known[k]; });
  if (user) { poolStore(POOL.sel); }
  poolMark();
  if (user) { poolShow("plane", "live"); poolShow("bg", "live"); }
}
function poolBoot() {
  if (!$("#poollist")) { return; }        // /fig3 与查看器页也加载本文件 —— 那两页没有弹池
  $("#pool11").onclick = function () { poolSet(poolDefault(), true); };
  $("#poolAll").onclick = function () { poolSet(poolEntries().map(function (m) { return String(m.key); }), true); };
  $("#poolClear").onclick = function () { poolSet([], true); };
  var s = $("#poolsearch");
  if (s) { s.oninput = function () { poolFilter(this.value); }; }
  [["plane"], ["bg"]].forEach(function (p) {
    var kind = p[0];
    var lv = $("#fig" + (kind === "bg" ? "2" : "1") + "live");
    var rs = $("#fig" + (kind === "bg" ? "2" : "1") + "result");
    if (lv) { lv.onclick = function () { poolShow(kind, "live"); }; }
    if (rs) { rs.onclick = function () { poolShow(kind, "result"); }; }
  });
  var cat = $("#poolcount");
  if (cat) { cat.textContent = "正在读目录…"; }
  fetch("/api/catalog", {headers: {"Accept": "application/json"}})
    .then(function (r) { return r.json(); })
    .then(function (j) {
      if (!j || j.ok === false) {
        throw new Error((j && j.errors && j.errors[0]) || "目录响应不可用");
      }
      POOL.catalog = j;
      poolBuildRows();
      poolMount();
      var saved = poolStored();
      poolSet(saved === null ? poolDefault() : saved, false);
      poolShow("plane", "live");
      poolShow("bg", "live");
    })
    .catch(function (e) {
      poolStat("目录不可用：" + ((e && e.message) || e) + " —— 图1/图2 保持静态形态（页面其他功能不受影响）。");
      if (cat) { cat.textContent = "目录不可用"; }
    });
}
poolBoot();


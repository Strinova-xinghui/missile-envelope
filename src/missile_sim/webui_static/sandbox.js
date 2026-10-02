"use strict";
/* 空战沙盒（图3 回放页）—— 手写 WebGL2，零第三方（离线免安装是底线）。
 *
 * 复用 `viewer3d.js` 导出的 `TRAJ3D`：相机与交互（`applyDrag`/`applyPan`，左键旋转 /
 * 滚轮缩放 / 右键或 Shift 平移）、投影（`projectToScreen`）、矩阵（`M4`）、调色（`CHROME`/`hex2rgb`/
 * `mixHex`）、二分（`idxLeft`/`idxRight`）—— 这三样是"跟手"与"贴点"已经被判据钉过的部分，不重写。
 *
 * 不复用的是它的**几何模型**：查看器画的是一整条轨迹 + 抽稀点，沙盒画的是"随时间推进"的画面
 * （飞过的实、未飞的淡 + 两个带朝向的实体 + 事件标点），几何每帧变，所以自带一份很小的线段/点批次层。
 *
 * 界面口径见 `docs/SANDBOX.md`；数据契约（事件表、悬停字段、轴刻度）全部由服务端给
 * （`GET /api/sandbox/<key>`），**前端一个字段标签/颜色都不写死**。
 *
 * URL 参数：`?job=<id>`（回放该任务；不给就回放 `traj_default` 那套产物）、`?points=N`、
 * `?t=<秒>`（从某一时刻开始）、`?paused=1`（进来先暂停）、`?follow=<key>`、`?az=`/`?el=`（相机初值）、
 * `?hover=<实体>:<下标>`（**取证用**：把悬停框钉在某个采样点上，截图可复现）。
 */
(function (global) {
  var PENDING_TEXT = "待接入";
  var NA_TEXT = "不适用";
  var ABSENT_TEXT = "—";
  var FIG = 0.9;                                  // 与查看器同一支 fovy

  /* ==================================================== 纯函数（node 自检 + 渲染共用） */

  // 数值 → 文本。⚠ 三种"没有值"要分开：
  //   契约里标 pending（内核列还没进产物）→ 待接入；标 n/a（该实体没有这个量）→ 不适用；
  //   内核在这一采样点确实没定义（例如第一行的过载）→ —（`null`）。
  function fmtValue(v, decimals) {
    if (v === null || v === undefined) return ABSENT_TEXT;
    if (typeof v !== "number" || !isFinite(v)) return String(v);
    return v.toFixed(decimals === undefined ? 2 : decimals);
  }

  // 悬停框的字段顺序 = 服务端 `hover.fields` 里 `group === "main"` 那批（参考站那 9 行）
  function fieldPlan(d) {
    var all = (d && d.hover && d.hover.fields) || [];
    var out = [];
    for (var i = 0; i < all.length; i++) if (all[i].group === "main") out.push(all[i]);
    return out;
  }

  function valueOf(d, who, key, index) {
    var s = (d.series || {})[who] || {};
    var col = s[key];
    if (!col || index === undefined || index === null) return undefined;
    return col[index];
  }

  // 悬停取值：**与回放时刻无关**（悬停到哪个点就显示哪个点）
  function hoverAt(d, who, index) {
    var plan = fieldPlan(d);
    var rows = [];
    for (var i = 0; i < plan.length; i++) {
      var f = plan[i];
      var src = (f.source || {})[who] || "";
      var na = src === "n/a";
      var pending = src === "pending";
      var v = (na || pending) ? undefined : valueOf(d, who, f.key, index);
      rows.push({
        key: f.key, label: f.label, unit: f.unit, decimals: f.decimals,
        value: (v === undefined ? null : v),
        na: na,
        pending: pending,
        derived: src === "derived",
        merge_with: f.merge_with || "",
        hint: f.hint || "",
        text: f.label + ": " + (na ? NA_TEXT : (pending ? PENDING_TEXT
                                    : fmtValue(v === undefined ? null : v, f.decimals))) +
              (!na && !pending && f.unit && v !== undefined ? " " + f.unit : ""),
      });
    }
    var s = (d.series || {})[who] || {};
    return {
      entity: who, index: index,
      name: who === "missile" ? (d.missile_name || "导弹") : "目标",
      t_s: (s.t_s || [])[index],
      rows: rows,
    };
  }

  function eventLine(e) {
    if (!e) return "";
    return e.text || ((e.label || e.name || "") + ": " + fmtValue(e.t_s, 2) + " 秒");
  }

  function trackTime(d) {
    var t = d && d.replay ? d.replay.t1 : 0;
    return typeof t === "number" && isFinite(t) ? t : 0;
  }

  // 插值：t 时刻的位置（回放头要落在两点之间，不能一格一格跳）
  function posAt(ts, pts, t) {
    if (!ts || !ts.length) return [0, 0, 0];
    if (t <= ts[0]) return pts[0].slice();
    if (t >= ts[ts.length - 1]) return pts[pts.length - 1].slice();
    var i = global.TRAJ3D.idxLeft(ts, t);
    var j = Math.min(i + 1, ts.length - 1);
    var span = ts[j] - ts[i];
    var f = span > 1e-12 ? (t - ts[i]) / span : 0;
    return [pts[i][0] + (pts[j][0] - pts[i][0]) * f,
            pts[i][1] + (pts[j][1] - pts[i][1]) * f,
            pts[i][2] + (pts[j][2] - pts[i][2]) * f];
  }

  // 姿态：`yaw_deg`/`pitch_deg` → 机体三轴（前/右/上）。与全仓坐标一致：
  // 航向 0° = +x、90° = +z；俯仰正 = 爬升。
  function entityAxes(yawDeg, pitchDeg) {
    var y = (yawDeg || 0) * Math.PI / 180, p = (pitchDeg || 0) * Math.PI / 180;
    var fwd = [Math.cos(p) * Math.cos(y), Math.sin(p), Math.cos(p) * Math.sin(y)];
    var right = [-Math.sin(y), 0, Math.cos(y)];
    var up = [right[1] * fwd[2] - right[2] * fwd[1],
              right[2] * fwd[0] - right[0] * fwd[2],
              right[0] * fwd[1] - right[1] * fwd[0]];
    return { fwd: fwd, right: right, up: up };
  }

  /* ==================================================== DOM 小工具 */

  function el(id) { return document.getElementById(id); }
  function css(el_, k, v) { if (el_) el_.style[k] = v; }
  function place(node, s) { css(node, "left", (s.x | 0) + "px"); css(node, "top", (s.y | 0) + "px"); }

  /* ==================================================== WebGL 批次层 */

  var VS = [
    "#version 300 es",
    "in vec3 a_pos; in vec3 a_col; uniform mat4 u_mvp; out vec3 v_col;",
    "void main(){ v_col = a_col; gl_Position = u_mvp * vec4(a_pos, 1.0); }"].join("\n");
  var VS_PT = [
    "#version 300 es",
    "in vec3 a_pos; in vec3 a_col; uniform mat4 u_mvp; uniform float u_size;",
    "out vec3 v_col;",
    "void main(){ v_col = a_col; gl_PointSize = u_size;",
    "  gl_Position = u_mvp * vec4(a_pos, 1.0); }"].join("\n");
  var FS = [
    "#version 300 es",
    "precision mediump float; in vec3 v_col; out vec4 outColor;",
    "void main(){ outColor = vec4(v_col, 1.0); }"].join("\n");
  // 点是**菱形**（事件标点）：在 gl_PointCoord 里做掩膜，比画 4 条短线省事、也不随视角变细
  var FS_PT = [
    "#version 300 es",
    "precision mediump float; in vec3 v_col; out vec4 outColor;",
    "void main(){",
    "  vec2 c = gl_PointCoord - vec2(0.5);",
    "  if (abs(c.x) + abs(c.y) > 0.44) discard;",
    "  outColor = vec4(v_col, 1.0); }"].join("\n");

  function compile(gl, vs, fs) {
    function sh(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        throw new Error("着色器编译失败：" + gl.getShaderInfoLog(s));
      }
      return s;
    }
    var p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error("着色器链接失败：" + gl.getProgramInfoLog(p));
    }
    return p;
  }

  // 一帧一批：攒线/点 → 上传 → 一次 drawArrays。
  // 顶点 7 float（pos3 + col3 + size1），与 viewer3d 的交错布局同款，方便日后合并。
  function batch(gl, prog, mode) {
    var pos = prog.attr.pos, col = prog.attr.col;
    var data = new Float32Array(7 * 8192), n = 0;
    function grow() {
      var bigger = new Float32Array(data.length * 2);
      bigger.set(data);
      data = bigger;
    }
    return {
      clear: function () { n = 0; },
      count: function () { return n; },
      add: function (p, c, size) {
        if ((n + 1) * 7 > data.length) grow();
        var o = n * 7;
        data[o] = p[0]; data[o + 1] = p[1]; data[o + 2] = p[2];
        data[o + 3] = c[0]; data[o + 4] = c[1]; data[o + 5] = c[2];
        data[o + 6] = size === undefined ? 1 : size;
        n++;
      },
      line: function (a, b, c) { this.add(a, c); this.add(b, c); },
      point: function (a, c) { this.add(a, c); },
      draw: function (mvp, size) {
        if (!n) return;
        gl.useProgram(prog.id);
        gl.bindBuffer(gl.ARRAY_BUFFER, prog.vbo);
        gl.bufferData(gl.ARRAY_BUFFER, data.subarray(0, n * 7), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(pos);
        gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, 28, 0);
        gl.enableVertexAttribArray(col);
        gl.vertexAttribPointer(col, 3, gl.FLOAT, false, 28, 12);
        gl.uniformMatrix4fv(prog.mvp, false, mvp);
        if (prog.size) gl.uniform1f(prog.size, size || 9);
        gl.drawArrays(mode, 0, n);
      },
    };
  }

  function makeProg(gl, vs, fs, withSize) {
    var id = compile(gl, vs, fs);
    var o = {
      id: id, vbo: gl.createBuffer(),
      attr: { pos: gl.getAttribLocation(id, "a_pos"), col: gl.getAttribLocation(id, "a_col") },
      mvp: gl.getUniformLocation(id, "u_mvp"),
      size: withSize ? gl.getUniformLocation(id, "u_size") : null,
    };
    return o;
  }

  /* ==================================================== 主程序 */

  function boot() {
    var params = new URLSearchParams(global.location.search);
    var job = params.get("job") || "";
    var points = params.get("points") || "";
    var key = job ? encodeURIComponent(job) : "default";
    var url = "/api/sandbox/" + key + (points ? "?points=" + encodeURIComponent(points) : "");
    fetch(url, { cache: "no-store" }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok || body.ok === false) {
          throw new Error((body.errors || ["取数据失败 HTTP " + r.status]).join("；"));
        }
        return body;
      });
    }).then(function (d) { start(d, params); })
      .catch(function (e) {
        var box = el("sbErr");
        if (box) box.textContent = "错误：" + (e && e.message ? e.message : String(e));
      });
  }

  function start(d, params) {
    var T = global.TRAJ3D;
    var cv = el("sbScene");
    var gl = null;
    try { gl = cv.getContext("webgl2", { antialias: true, alpha: false }); } catch (e) { gl = null; }
    if (!gl) { if (el("sbErr")) el("sbErr").textContent = "错误：本浏览器/环境不支持 WebGL2"; return; }

    var prog = makeProg(gl, VS, FS, false);
    var progPt = makeProg(gl, VS_PT, FS_PT, true);
    var bLine = batch(gl, prog, gl.LINES);
    var bGhost = batch(gl, prog, gl.LINES);
    var bMark = batch(gl, progPt, gl.POINTS);
    var CH = T.CHROME;
    var BG = T.hex2rgb(CH.bg);

    var tEnd = trackTime(d);
    var state = {
      t: 0, playing: !(params.get("paused") === "1"), speed: d.replay.speed_default,
      follow: d.follow_default, showEvents: true, showGrid: true,
      hoverEnt: "", hoverIdx: null, sideCollapsed: false,
    };
    var t0Param = parseFloat(params.get("t") || "");
    if (isFinite(t0Param)) state.t = Math.max(0, Math.min(tEnd, t0Param));
    var follow0 = params.get("follow");
    if (follow0) state.follow = follow0;
    // 取证钩子：把悬停框钉在某个采样点上（`?hover=missile:520`）—— 鼠标一动就交还给鼠标
    var hv = (params.get("hover") || "").split(":");
    if ((hv[0] === "missile" || hv[0] === "target") && isFinite(parseInt(hv[1], 10))) {
      state.hoverEnt = hv[0];
      state.hoverIdx = parseInt(hv[1], 10);
      state.hoverPin = true;
    }

    /* ---------------- 世界包围盒与相机 */
    var mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    function extend(p) {
      for (var i = 0; i < 3; i++) { if (p[i] < mn[i]) mn[i] = p[i]; if (p[i] > mx[i]) mx[i] = p[i]; }
    }
    var i;
    for (i = 0; i < d.missile.p.length; i++) extend(d.missile.p[i]);
    for (i = 0; i < d.target.p.length; i++) extend(d.target.p[i]);
    for (i = 0; i < d.events.length; i++) if (d.events[i].pos) extend(d.events[i].pos);
    var center0 = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
    var radius = 0.5 * Math.hypot(mx[0] - mn[0], Math.max(mx[1] - mn[1], 1), mx[2] - mn[2]);
    var unit = Math.max(radius / 26, 400);            // 实体线框的世界尺寸（随场景缩放）
    var cam = { az: -1.05, el: 0.36, dist: 1, pan: [0, 0, 0] };

    function fit() {
      var aspect = cv.width / Math.max(cv.height, 1);
      var need = radius / Math.tan(FIG / 2);
      cam.dist = Math.max(need, need / Math.max(aspect, 0.2)) * 0.72;
      // ⚠ 只按**包围球**定视距会裁掉轨迹两端（0.72 是查看器那套"细长轨迹"的口径，沙盒里
      //   还有一大片地面网格和两个实体）。这里再按**真实点集**迭代放大，直到两条轨迹的所有
      //   采样点都落在视口内 —— 网格被裁掉无所谓，**交战双方必须都在画面里**。
      for (var it = 0; it < 14 && !allInside(); it++) cam.dist *= 1.12;
    }
    function allInside() {
      var c = [center0[0] + cam.pan[0], center0[1] + cam.pan[1], center0[2] + cam.pan[2]];
      var lists = [d.missile.p, d.target.p];
      for (var w = 0; w < lists.length; w++) {
        var ps = lists[w];
        for (var i = 0; i < ps.length; i++) {
          var s = T.projectToScreen(ps[i], cam, c, radius, cv.width, cv.height, FIG);
          if (!s || s.x < 0.03 * cv.width || s.x > 0.97 * cv.width ||
              s.y < 0.03 * cv.height || s.y > 0.97 * cv.height) return false;
        }
      }
      return true;
    }
    function debugTitle() {
      if (params.get("debug") !== "1") return;
      document.title = "DBG t=" + state.t.toFixed(2) + " playing=" + (state.playing ? 1 : 0) +
        " speed=" + state.speed + " follow=" + state.follow +
        " hover=" + (state.hoverEnt || "-") + ":" + (state.hoverIdx === null ? "-" : state.hoverIdx) +
        " cv=" + cv.width + "x" + cv.height + " css=" + cv.clientWidth + "x" + cv.clientHeight +
        " aspect=" + (cv.width / Math.max(cv.height, 1)).toFixed(3) +
        " radius=" + radius.toFixed(0) + " dist=" + cam.dist.toFixed(0);
    }
    function resize() {
      var dpr = Math.min(global.devicePixelRatio || 1, 2);
      var w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
      if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) { cv.width = w; cv.height = h; }
    }

    function camCenter() {
      var c = center0.slice();
      if (state.follow === "missile" || state.follow === "target") {
        var who = d.series[state.follow];
        c = posAt(who.t_s, state.follow === "missile" ? d.missile.p : d.target.p, state.t);
      }
      return [c[0] + cam.pan[0], c[1] + cam.pan[1], c[2] + cam.pan[2]];
    }
    function mvp() {
      var c = camCenter();
      var dist = Math.max(cam.dist, radius * 0.05);
      var near = Math.max(dist * 0.01, 1e-3), far = dist * 8 + radius * 4;
      var V = T.M4.view(cam.az, cam.el, dist, c[0], c[1], c[2]);
      var P = T.M4.persp(FIG, cv.width / Math.max(cv.height, 1), near, far);
      return T.M4.mul(P, V);
    }

    /* ---------------- 静态几何：地面网格 + 三轴 */
    function gridAndAxes() {
      if (state.showGrid) {
        var ax = d.axes, gx = T.hex2rgb(CH.grid);
        for (i = 0; i < ax.x.ticks.length; i++) {
          bLine.line([ax.x.ticks[i], 0, ax.z.min], [ax.x.ticks[i], 0, ax.z.max], gx);
        }
        for (i = 0; i < ax.z.ticks.length; i++) {
          bLine.line([ax.x.min, 0, ax.z.ticks[i]], [ax.x.max, 0, ax.z.ticks[i]], gx);
        }
      }
      bLine.line([0, 0, 0], [d.axes.x.max, 0, 0], T.hex2rgb(CH.axisX));
      bLine.line([0, 0, 0], [0, d.axes.y.max, 0], T.hex2rgb(CH.axisY));
      bLine.line([0, 0, 0], [0, 0, d.axes.z.max], T.hex2rgb(CH.axisZ));
    }

    /* ---------------- 轨迹（幽灵段 + 已飞段） */
    function segRanges(ts, segs) {
      var out = [];
      for (var k = 0; k < segs.length; k++) {
        var a = T.idxLeft(ts, segs[k].t0), b = T.idxRight(ts, segs[k].t1);
        if (b > a) out.push({ a: a, b: b, seg: segs[k] });
      }
      return out;
    }
    function polyline(B, ts, ps, a, b, rgb) {
      for (var k = a; k < b; k++) B.line(ps[k], ps[k + 1], rgb);
    }
    function dashed(B, ts, ps, a, b, rgb) {
      for (var k = a; k < b; k++) if ((k & 1) === 0) B.line(ps[k], ps[k + 1], rgb);
    }
    function ghostRgb(hex) { return T.hex2rgb(T.mixHex(hex, CH.bg, 0.78)); }

    function tracks() {
      bGhost.clear();
      var mr = [[0, d.missile.split_index], [d.missile.split_index, d.missile.p.length - 1]];
      var mc = [d.colors.missile_before, d.colors.missile_after];
      for (var k = 0; k < 2; k++) {
        if (mr[k][1] > mr[k][0]) polyline(bGhost, d.missile.t, d.missile.p, mr[k][0], mr[k][1],
                                         ghostRgb(mc[k]));
      }
      var tr = segRanges(d.target.t, d.segments);
      for (k = 0; k < tr.length; k++) {
        dashed(bGhost, d.target.t, d.target.p, tr[k].a, tr[k].b, ghostRgb(tr[k].seg.color));
      }
    }

    function flown() {
      bLine.clear();
      gridAndAxes();
      var upto = state.t;
      var mis = { t: d.missile.t, p: d.missile.p };
      // 导弹：两段各自只画到 `upto`
      var parts = [[0, d.missile.split_index, d.colors.missile_before],
                   [d.missile.split_index, d.missile.p.length - 1, d.colors.missile_after]];
      for (var k = 0; k < parts.length; k++) {
        var a = parts[k][0], b = parts[k][1], rgb = T.hex2rgb(parts[k][2]);
        for (var j = a; j < b && mis.t[j + 1] <= upto; j++) bLine.line(mis.p[j], mis.p[j + 1], rgb);
        // 头部那半格：插值到当前时刻，回放看起来是连续的
        var head = T.idxLeft(mis.t, upto);
        if (head >= a && head + 1 <= b && mis.t[head] <= upto && upto < mis.t[head + 1]) {
          bLine.line(mis.p[head], posAt(mis.t, mis.p, upto), rgb);
        }
      }
      var tgt = segRanges(d.target.t, d.segments);
      for (k = 0; k < tgt.length; k++) {
        var aa = tgt[k].a, bb = tgt[k].b, c = T.hex2rgb(tgt[k].seg.color);
        for (j = aa; j < bb && d.target.t[j + 1] <= upto; j++) {
          if ((j & 1) === 0) bLine.line(d.target.p[j], d.target.p[j + 1], c);
        }
      }
    }

    /* ---------------- 实体线框（带朝向） */
    function wire(B, pos, yaw, pitch, size, rgb, kind) {
      var A = entityAxes(yaw, pitch);
      function P(f, r, u) {
        return [pos[0] + A.fwd[0] * f + A.right[0] * r + A.up[0] * u,
                pos[1] + A.fwd[1] * f + A.right[1] * r + A.up[1] * u,
                pos[2] + A.fwd[2] * f + A.right[2] * r + A.up[2] * u];
      }
      var tail = -size * (kind === "target" ? 0.5 : 0.45);
      B.line(P(size, 0, 0), P(tail, 0, 0), rgb);                       // 机身
      B.line(P(size * 0.55, 0, 0), P(size * 0.05, size * 0.75, 0), rgb);   // 前缘
      B.line(P(size * 0.55, 0, 0), P(size * 0.05, -size * 0.75, 0), rgb);
      B.line(P(tail, 0, 0), P(tail * 1.15, size * 0.55, 0), rgb);      // 尾翼
      B.line(P(tail, 0, 0), P(tail * 1.15, -size * 0.55, 0), rgb);
      B.line(P(tail, 0, 0), P(tail, 0, size * 0.5), rgb);              // 垂尾
    }

    function entities(M) {
      var misY = d.series.missile, tgtY = d.series.target;
      var mp = posAt(misY.t_s, d.missile.p, state.t);
      var tp = posAt(tgtY.t_s, d.target.p, state.t);
      var mi = Math.min(T.idxLeft(misY.t_s, state.t), misY.yaw_deg.length - 1);
      var ti = Math.min(T.idxLeft(tgtY.t_s, state.t), tgtY.yaw_deg.length - 1);
      wire(bLine, mp, misY.yaw_deg[mi], misY.pitch_deg[mi], unit, T.hex2rgb(
        state.t >= (d.t_beam_s || 0) ? d.colors.missile_after : d.colors.missile_before), "missile");
      wire(bLine, tp, tgtY.yaw_deg[ti], tgtY.pitch_deg[ti], unit * 1.3,
           T.hex2rgb(d.segments.length ? d.segments[Math.min(
             segIndex(d, state.t), d.segments.length - 1)].color : d.colors.fallback), "target");
      return { missile: mp, target: tp, mi: mi, ti: ti };
    }
    function segIndex(dd, t) {
      for (var k = dd.segments.length - 1; k >= 0; k--) if (t >= dd.segments[k].t0) return k;
      return 0;
    }

    /* ---------------- 事件标点（GL 菱形 + DOM 文本） */
    function marks() {
      bMark.clear();
      var box = el("sbEvents");
      if (box) box.innerHTML = "";
      for (var k = 0; k < d.events.length; k++) {
        var e = d.events[k];
        if (!e.pos) continue;
        var hex = e.hit === true ? d.colors.hit : (e.hit === false ? d.colors.miss : d.colors.mark);
        bMark.point(e.pos, T.hex2rgb(hex));
        if (!state.showEvents || !box) continue;
        var sp = T.projectToScreen(e.pos, cam, camCenter(), radius, cv.width, cv.height, FIG);
        if (!sp) continue;
        var node = document.createElement("span");
        node.textContent = eventLine(e);
        place(node, { x: sp.x * (cv.clientWidth / Math.max(cv.width, 1)),
                      y: sp.y * (cv.clientHeight / Math.max(cv.height, 1)) });
        box.appendChild(node);
      }
    }

    /* ---------------- 三轴刻度文本 */
    function labels() {
      var box = el("sbAxisLabels");
      if (!box) return;
      box.innerHTML = "";
      if (!state.showGrid) return;
      var ax = d.axes, c = camCenter();
      var W = cv.width, H = cv.height, sx = cv.clientWidth / Math.max(W, 1),
          sy = cv.clientHeight / Math.max(H, 1);
      function add(p, text, cls) {
        var sp = T.projectToScreen(p, cam, c, radius, W, H, FIG);
        if (!sp) return;
        var node = document.createElement("span");
        node.textContent = text;
        if (cls) node.className = cls;
        place(node, { x: sp.x * sx, y: sp.y * sy });
        box.appendChild(node);
      }
      var k;
      for (k = 0; k < ax.x.ticks.length; k++) add([ax.x.ticks[k], 0, ax.z.min], ax.x.texts[k]);
      for (k = 0; k < ax.z.ticks.length; k++) add([ax.x.min, 0, ax.z.ticks[k]], ax.z.texts[k]);
      for (k = 0; k < ax.y.ticks.length; k++) add([0, ax.y.ticks[k], 0], ax.y.texts[k]);
      add([ax.x.max * 0.5, 0, ax.z.min], ax.x.label, "sbAxisName");
      add([0, ax.y.max * 1.05, 0], ax.y.label, "sbAxisName");
      add([ax.x.min, 0, ax.z.max * 0.5], ax.z.label, "sbAxisName");
    }

    /* ---------------- 图例（线型区分双方，颜色来自响应） */
    function legend() {
      var box = el("sbLegend");
      if (!box) return;
      var ent = d.entities, html = "";
      function swatch(css_, colors) {
        var out = "";
        for (var k = 0; k < colors.length; k++) {
          out += '<i class="' + css_ + '" style="border-top-color:' + colors[k] + '"></i>';
        }
        return out;
      }
      html += "<div>" + swatch("dashed", ent.target.colors) +
        "<span>" + ent.target.name + "</span><em>" + ent.target.labels.join(" / ") + "</em></div>";
      html += "<div>" + swatch("", ent.missile.colors) +
        "<span>" + ent.missile.name + "</span><em>" + ent.missile.labels.join(" / ") + "</em></div>";
      box.innerHTML = html;
    }

    /* ---------------- 左栏（想定 / 倍速 / 镜头 / 数据来源） */
    function side() {
      var kv = el("sbScenario");
      if (kv) {
        var rows = [
          ["基准弹", d.missile_name || "—"],
          ["档位 / 后端", (d.tier || "—") + " / " + (d.backend || "—")],
          ["导引头开机", fmtValue(d.t_beam_s, 2) + " s"],
          ["命中 / 脱靶", d.hit ? ("命中 " + fmtValue(d.t_hit_s, 2) + " s")
                                : ("脱靶 " + fmtValue(d.t_end_s, 2) + " s")],
          ["近炸 / 最近距离", (d.miss_m === null || d.miss_m === undefined ? "—"
                               : fmtValue(d.miss_m, 1) + " m")],
          ["总时长", fmtValue(tEnd, 2) + " s"],
          ["β / γ", fmtValue(d.beta, 1) + " / " + fmtValue(d.gamma, 2)],
        ];
        var html = "";
        for (var k = 0; k < rows.length; k++) {
          html += "<b>" + rows[k][0] + "</b><span>" + rows[k][1] + "</span>";
        }
        kv.innerHTML = html;
      }
      var sp = el("sbSpeed");
      if (sp) {
        sp.innerHTML = "";
        for (var j = 0; j < d.replay.speeds.length; j++) {
          var o = document.createElement("option");
          o.value = String(d.replay.speeds[j]);
          o.textContent = d.replay.speeds[j] + "×";
          if (Math.abs(d.replay.speeds[j] - state.speed) < 1e-9) o.selected = true;
          sp.appendChild(o);
        }
        sp.onchange = function () { state.speed = parseFloat(sp.value) || 1; };
      }
      var fo = el("sbFollow");
      if (fo) {
        fo.innerHTML = "";
        for (j = 0; j < d.follow.length; j++) {
          var o2 = document.createElement("option");
          o2.value = d.follow[j].key;
          o2.textContent = d.follow[j].label;
          if (d.follow[j].key === state.follow) o2.selected = true;
          fo.appendChild(o2);
        }
        fo.onchange = function () { state.follow = fo.value; };
      }
      var src = el("sbSource");
      if (src) {
        var pend = d.hover.pending_keys || [];
        var na = d.hover.na_keys || [];
        var lines = [];
        lines.push(d.axis_note || "");
        for (var q = 0; q < pend.length; q++) {
          lines.push('<span class="sbpend">' + pend[q] + "</span> → 待接入：" +
                     ((d.hover.pending_sources || {})[pend[q]] || ""));
        }
        if (na.length) {
          lines.push('<span class="sbpend">不适用</span>（目标没有这个量）：' + na.join("、"));
        }
        src.innerHTML = lines.join("<br>");
      }
      var tog = el("sbToggle");
      if (tog) {
        tog.onclick = function () {
          state.sideCollapsed = !state.sideCollapsed;
          document.body.classList.toggle("sb-collapsed", state.sideCollapsed);
          tog.textContent = state.sideCollapsed ? "›" : "‹";
          try { localStorage.setItem("sandbox.sideCollapsed", state.sideCollapsed ? "1" : "0"); } catch (e) {}
        };
        try {
          if (localStorage.getItem("sandbox.sideCollapsed") === "1") tog.onclick();
        } catch (e) {}
      }
      var se = el("sbShowEvents"), sg = el("sbShowGrid");
      if (se) se.onchange = function () { state.showEvents = se.checked; };
      if (sg) sg.onchange = function () { state.showGrid = sg.checked; };
    }

    /* ---------------- 悬停 */
    function nearestSample(who, px, py, c, W, H) {
      var s = d.series[who], ps = who === "missile" ? d.missile.p : d.target.p;
      var best = -1, bestD = 1e9;
      for (var k = 0; k < ps.length; k++) {
        var sp = T.projectToScreen(ps[k], cam, c, radius, W, H, FIG);
        if (!sp) continue;
        var dd = Math.hypot((sp.x * (cv.clientWidth / Math.max(W, 1))) - px,
                            (sp.y * (cv.clientHeight / Math.max(H, 1))) - py);
        if (dd < bestD) { bestD = dd; best = k; }
      }
      return { idx: best, dist: bestD };
    }
    function showHover(px, py) {
      var box = el("sbHover"), c = camCenter();
      var m = nearestSample("missile", px, py, c, cv.width, cv.height);
      var t2 = nearestSample("target", px, py, c, cv.width, cv.height);
      var pick = (m.dist <= t2.dist && m.dist <= 22) ? ["missile", m] : (t2.dist <= 22 ? ["target", t2] : null);
      if (!pick || pick[1].idx < 0) {
        state.hoverEnt = ""; state.hoverIdx = null;
        if (box) box.style.display = "none";
        cv.classList.remove("hover");
        return;
      }
      state.hoverEnt = pick[0]; state.hoverIdx = pick[1].idx;
      cv.classList.add("hover");
      renderHover(px, py);
    }
    var lastHover = { x: 0, y: 0 };
    function renderHover(px, py) {
      var box = el("sbHover");
      if (!box || !state.hoverEnt) return;
      var info = hoverAt(d, state.hoverEnt, state.hoverIdx);
      var html = "<b>" + info.name + "</b>";
      var prev = "";
      for (var k = 0; k < info.rows.length; k++) {
        var r = info.rows[k];
        if (r.merge_with && prev === r.merge_with) {
          // 与上一行同行显示（参考站："速度: 1951.5 米/秒, M1.86"）；
          // 待接入/不适用的那个要把标签带上，否则"速度: 627.0 米/秒, 待接入"读不出是哪个量
          var extra = (r.pending || r.na) ? (r.label + ": " + renderValue(r)) : renderValue(r);
          html = html.replace(/<\/div>$/, ", " + extra + "</div>");
        } else {
          html += "<div>" + r.label + ": " + renderValue(r) +
                  (r.derived ? ' <i class="sbDerived">差分/几何</i>' : "") + "</div>";
        }
        prev = r.key;
      }
      box.innerHTML = html;
      box.style.display = "block";
      var w = box.offsetWidth || 200, h = box.offsetHeight || 120;
      var x = px + 14, y = py + 14;
      if (x + w > cv.clientWidth - 6) x = px - w - 14;
      if (y + h > cv.clientHeight - 6) y = Math.max(6, cv.clientHeight - h - 6);
      css(box, "left", (x | 0) + "px");
      css(box, "top", (y | 0) + "px");
    }
    function renderValue(r) {
      if (r.na) return '<span class="sbNa">' + NA_TEXT + "</span>";
      if (r.pending) return '<span class="sbPending">' + PENDING_TEXT + "</span>";
      return fmtValue(r.value, r.decimals) + (r.unit ? " " + r.unit : "");
    }

    /* ---------------- 交互：拖动 / 缩放 / 悬停 */
    var drag = 0, lx = 0, ly = 0;
    cv.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    cv.addEventListener("pointerdown", function (e) {
      drag = (e.button === 2 || e.shiftKey) ? 2 : 1;
      lx = e.clientX; ly = e.clientY;
      cv.classList.add("drag");
      try { cv.setPointerCapture(e.pointerId); } catch (err) {}
    });
    cv.addEventListener("pointerup", function () { drag = 0; cv.classList.remove("drag"); });
    cv.addEventListener("pointerleave", function () {
      drag = 0; cv.classList.remove("drag");
      var box = el("sbHover");
      if (box) box.style.display = "none";
      state.hoverEnt = ""; state.hoverIdx = null;
    });
    cv.addEventListener("pointermove", function (e) {
      var dx = e.clientX - lx, dy = e.clientY - ly;
      if (drag) { lx = e.clientX; ly = e.clientY; }
      if (drag === 1) T.applyDrag(cam, dx, dy);
      else if (drag === 2) T.applyPan(cam, dx, dy);
      else {
        var r = cv.getBoundingClientRect();
        lastHover.x = e.clientX - r.left; lastHover.y = e.clientY - r.top;
        state.hoverPin = false;
        showHover(lastHover.x, lastHover.y);
      }
    });
    cv.addEventListener("wheel", function (e) {
      e.preventDefault();
      cam.dist *= Math.exp((e.deltaY > 0 ? 1 : -1) * 0.12);
    }, { passive: false });

    /* ---------------- 播放控件 */
    function bindBar() {
      var pr = el("sbProgress");
      if (el("sbReplay")) el("sbReplay").onclick = function () { state.t = 0; state.playing = true; };
      if (el("sbPause")) el("sbPause").onclick = function (e) {
        state.playing = !state.playing;
        e.currentTarget.classList.toggle("on", !state.playing);
      };
      if (el("sbStep")) el("sbStep").onclick = function () {
        state.playing = false;
        state.t = Math.min(tEnd, state.t + (d.replay.step_s || 0.02));
      };
      if (pr) {
        pr.oninput = function () {
          state.playing = false;
          state.t = (parseFloat(pr.value) / 1000) * tEnd;
        };
      }
    }
    function clock() {
      var pr = el("sbProgress"), out = el("sbClock");
      if (pr && document.activeElement !== pr) pr.value = String(tEnd > 0 ? (state.t / tEnd) * 1000 : 0);
      if (out) out.textContent = fmtValue(state.t, 1) + "s / " + fmtValue(tEnd, 1) + "s";
    }
    function readout(pos) {
      var box = el("sbReadout");
      if (!box) return;
      var s = d.series.missile, k = Math.min(T.idxLeft(s.t_s, state.t), s.t_s.length - 1);
      var bits = [d.missile_name || "导弹", "t=" + fmtValue(state.t, 1) + "s"];
      if (s.speed_ms) bits.push("v=" + fmtValue(s.speed_ms[k], 0) + "m/s");
      if (s.range_m) {
        // 近炸是 10 m 量级：小于 1 km 就按米给，否则 "R=0.0km" 会把这枚弹最关键的读数抹平
        var r = s.range_m[k];
        bits.push("R=" + (r >= 1000 ? fmtValue(r / 1000, 1) + "km" : fmtValue(r, 0) + "m"));
      }
      box.textContent = bits.join(" · ");
      var sp = T.projectToScreen(pos, cam, camCenter(), radius, cv.width, cv.height, FIG);
      if (!sp) { box.style.display = "none"; return; }
      box.style.display = "block";
      place(box, { x: sp.x * (cv.clientWidth / Math.max(cv.width, 1)),
                   y: sp.y * (cv.clientHeight / Math.max(cv.height, 1)) });
    }

    /* ---------------- 主循环 */
    var last = (global.performance || Date).now();
    function frame(now) {
      var dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      resize();
      if (state.playing) {
        state.t += dt * state.speed;
        if (state.t >= tEnd) { state.t = tEnd; state.playing = false;
          if (el("sbPause")) el("sbPause").classList.add("on"); }
      }
      var M = mvp();
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
      // 亮底、不透明（沙盒是整页，不是内嵌 iframe；内嵌那套 `bg=transparent` 是 viewer3d 的）
      gl.clearColor(BG[0], BG[1], BG[2], 1);
      gl.enable(gl.DEPTH_TEST);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      tracks();
      bGhost.draw(M);
      var e = entities(M);
      marks();
      flown();
      bLine.draw(M);
      bMark.draw(M, Math.max(7, Math.min(14, unit / 90)));
      labels();
      clock();
      debugTitle();
      readout(e.missile);
      if (state.hoverEnt) {
        if (state.hoverPin) {
          var s0 = d.series[state.hoverEnt];
          var pp = state.hoverEnt === "missile" ? d.missile.p : d.target.p;
          var sc = T.projectToScreen(pp[Math.min(state.hoverIdx, pp.length - 1)], cam, camCenter(),
                                     radius, cv.width, cv.height, FIG);
          if (sc) renderHover(sc.x * (cv.clientWidth / Math.max(cv.width, 1)),
                              sc.y * (cv.clientHeight / Math.max(cv.height, 1)));
        } else {
          renderHover(lastHover.x, lastHover.y);
        }
      }
      global.requestAnimationFrame(frame);
    }

    resize();
    fit();
    var az0 = parseFloat(params.get("az") || ""), el0 = parseFloat(params.get("el") || "");
    if (isFinite(az0)) cam.az = az0;                 // 取证/复查用：直接给相机初值
    if (isFinite(el0)) cam.el = el0;
    side();
    legend();
    tracks();
    bindBar();
    global.requestAnimationFrame(frame);
  }

  var API = { fmtValue: fmtValue, fieldPlan: fieldPlan, hoverAt: hoverAt, eventLine: eventLine,
              trackTime: trackTime, entityAxes: entityAxes, posAt: posAt };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // Node 自检用
  global.SANDBOX = API;
  if (typeof document !== "undefined" && document.getElementById) boot();
})(typeof window !== "undefined" ? window : globalThis);

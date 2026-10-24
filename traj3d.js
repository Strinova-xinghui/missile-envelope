"use strict";
/* 弹道模式的三维飞行轨迹视图 —— **手写 WebGL2**，零第三方（与 fig3.js / viewer3d.js 同一条路线）。
 *
 * 口径（Lead 2026-10-24）：
 *   ① **只画不算**：点列由壳（app.js）从 /v1/trajectory 响应里取，颜色由壳按目录 style 给；
 *      本文件不读目录、不碰物理量，只做相机、投影、几何装配与交互。
 *   ② y 轴是**高度**（后端 points 的列序是 [t, x, y, z, v]；z 常为 0，那是物理决定的）。
 *   ③ 相机**自适应包围盒**（x/y/z 的实际范围算中心与半径），默认共面轨迹也能看；
 *      范围全为 0 时有兜底（半径至少 1），不除零、不画空画面。
 *   ④ 初始视角 az≈45° / el≈25°，能同时看到 x 与 z 两个方向。
 *
 * 壳照这个接口调用（冻结形状，要改先报 Lead）：
 *
 *     window.TRAJFAN.mount(host, {chrome}) -> {
 *       available()            -> bool      （false = 本环境不支持 WebGL2，壳走回落）
 *       setSeries(list)        -> number    （画几条；list=[{key,label,color,points:[[x,y,z],…]}]）
 *       clear()                            （清空，保留相机）
 *       reset()                            （相机复位 + 重新取景）
 *       stats()                -> {lines, verts, radius, center}
 *     }
 *
 * 交互：左键拖拽旋转 / 右键或 Shift+拖拽平移 / 滚轮缩放 / 双击复位。
 */
(function (global) {
  /* ==================================================================== 数学 */
  // 4x4 列主序矩阵（WebGL 口径），只写这个视图用得到的四则。
  var M4 = {
    ident: function () { return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]); },
    mul: function (a, b) {
      var o = new Float32Array(16);
      for (var c = 0; c < 4; c++) {
        for (var r = 0; r < 4; r++) {
          var s = 0;
          for (var k = 0; k < 4; k++) { s += a[k * 4 + r] * b[c * 4 + k]; }
          o[c * 4 + r] = s;
        }
      }
      return o;
    },
    // 相机在 (az, el, dist) 的球坐标上，看向 center（y 是高度轴）
    view: function (az, el, dist, cx, cy, cz) {
      var ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
      var dir = [ce * ca, se, ce * sa];                 // center -> 相机
      var eye = [cx + dir[0] * dist, cy + dir[1] * dist, cz + dir[2] * dist];
      var f = [-dir[0], -dir[1], -dir[2]];
      var up = [0, 1, 0];
      var F = norm(f);
      var S = [F[1] * up[2] - F[2] * up[1], F[2] * up[0] - F[0] * up[2], F[0] * up[1] - F[1] * up[0]];
      var Sv = norm(S);
      var U = [Sv[1] * F[2] - Sv[2] * F[1], Sv[2] * F[0] - Sv[0] * F[2], Sv[0] * F[1] - Sv[1] * F[0]];
      return new Float32Array([
        Sv[0], U[0], -F[0], 0,
        Sv[1], U[1], -F[1], 0,
        Sv[2], U[2], -F[2], 0,
        -(Sv[0] * eye[0] + Sv[1] * eye[1] + Sv[2] * eye[2]),
        -(U[0] * eye[0] + U[1] * eye[1] + U[2] * eye[2]),
        (F[0] * eye[0] + F[1] * eye[1] + F[2] * eye[2]),
        1]);
    },
    persp: function (fovy, aspect, near, far) {
      var t = 1 / Math.tan(fovy / 2);
      return new Float32Array([
        t / aspect, 0, 0, 0,
        0, t, 0, 0,
        0, 0, (far + near) / (near - far), -1,
        0, 0, (2 * far * near) / (near - far), 0]);
    }
  };
  function norm(v) {
    var n = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  /* ==================================================================== 颜色 */
  // 数据配色由壳给（目录 style）；这里只有"浏览器环境读不到 CSS 变量"时的亮色兜底。
  var CHROME_DEFAULT = { bg: "#ffffff", grid: "#d6dde6", line: "#1f6feb",
                         axisX: "#cc3322", axisY: "#227855", axisZ: "#2661d9" };
  function mergeChrome(src) {
    var out = {}, k;
    for (k in CHROME_DEFAULT) {
      if (Object.prototype.hasOwnProperty.call(CHROME_DEFAULT, k)) {
        out[k] = (src && src[k]) ? String(src[k]) : CHROME_DEFAULT[k];
      }
    }
    return out;
  }
  function hex2rgb(text) {
    var s = String(text || "").replace("#", "");
    if (s.length === 3) { s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2]; }
    var r = parseInt(s.substr(0, 2), 16), g = parseInt(s.substr(2, 2), 16), b = parseInt(s.substr(4, 2), 16);
    if (!isFinite(r) || !isFinite(g) || !isFinite(b)) { return [0.12, 0.44, 0.92]; }
    return [r / 255, g / 255, b / 255];
  }
  function rgb2hex(c) {
    var out = "#";
    for (var i = 0; i < 3; i++) {
      var v = Math.round(clamp(c[i], 0, 1) * 255);
      out += ("0" + v.toString(16)).slice(-2);
    }
    return out;
  }
  // 把 a 向 b 混 k（地面投影用"淡一档"的轨迹色）；与 viewer3d.mixHex 同一个意思。
  function mixHex(a, b, k) {
    var ca = hex2rgb(a), cb = hex2rgb(b), f = clamp(k, 0, 1);
    return rgb2hex([ca[0] + (cb[0] - ca[0]) * f,
                    ca[1] + (cb[1] - ca[1]) * f,
                    ca[2] + (cb[2] - ca[2]) * f]);
  }

  /* ================================================================== 着色器 */
  var VS = ["#version 300 es",
    "in vec3 a_pos; in vec3 a_col;",
    "uniform mat4 u_mvp;",
    "out vec3 v_col;",
    "void main() { v_col = a_col; gl_Position = u_mvp * vec4(a_pos, 1.0); }"].join("\n");
  var FS = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; out vec4 outColor;",
    "void main() { outColor = vec4(v_col, 1.0); }"].join("\n");

  /* ============================================================ 相机交互规则 */
  // 拖动方向 = 跟手（"抓住物体转"，与 viewer3d.js 同惯例）。
  var AZ_PER_PX = 0.008;
  var EL_PER_PX = 0.008;
  var EL_LIMIT = 1.45;                       // 别让相机翻过极点
  var AZ0 = 0.785, EL0 = 0.436;              // 初始视角：az≈45° / el≈25°
  function applyDrag(cam, dx, dy) {
    cam.az += dx * AZ_PER_PX;
    cam.el = clamp(cam.el + dy * EL_PER_PX, -EL_LIMIT, EL_LIMIT);
  }
  function applyPan(cam, dx, dy, radius) {
    var k = Math.max(cam.dist, radius) * 0.0016;
    var ca = Math.cos(cam.az), sa = Math.sin(cam.az);
    cam.pan[0] -= (-sa * dx) * k;
    cam.pan[2] -= (ca * dx) * k;
    cam.pan[1] += dy * k;
  }

  /* ================================================================== 几何装配 */
  /** 三维包围盒：中心 / 各向跨度 / 外接球半径（全 0 时有兜底，不除零）。 */
  function boundsOf(series) {
    var mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity], n = 0;
    (series || []).forEach(function (s) {
      var pts = (s && s.points) || [];
      for (var i = 0; i < pts.length; i++) {
        var p = pts[i];
        if (!p || p.length < 3) { continue; }
        var ax = +p[0], ay = +p[1], az = +p[2];
        if (!isFinite(ax) || !isFinite(ay) || !isFinite(az)) { continue; }
        if (ax < mn[0]) { mn[0] = ax; }
        if (ax > mx[0]) { mx[0] = ax; }
        if (ay < mn[1]) { mn[1] = ay; }
        if (ay > mx[1]) { mx[1] = ay; }
        if (az < mn[2]) { mn[2] = az; }
        if (az > mx[2]) { mx[2] = az; }
        n += 1;
      }
    });
    if (!n) { mn = [0, 0, 0]; mx = [0, 0, 0]; }
    var center = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
    var span = [Math.max(mx[0] - mn[0], 0), Math.max(mx[1] - mn[1], 0), Math.max(mx[2] - mn[2], 0)];
    var radius = 0.5 * Math.sqrt(span[0] * span[0] + span[1] * span[1] + span[2] * span[2]);
    if (!(radius > 1e-6)) { radius = 1; }     // 兜底：三点全 0 / 只有一个点
    return { lo: mn, hi: mx, center: center, span: span, radius: radius, points: n };
  }

  /** 地面投影（y = 地面高度）：只改 y，其它两轴不动。 */
  function shadowOf(pts, groundY) {
    var out = [];
    for (var i = 0; i < (pts || []).length; i++) {
      out.push([+pts[i][0], groundY, +pts[i][2]]);
    }
    return out;
  }

  /**
   * 数据 → 顶点（并行数组 pos/col）+ 索引。**纯函数**（node 可测，不碰 gl）。
   * 画的东西：地面网格（y = 最低点）→ 三色坐标轴 → 每枚弹一条轨迹线 + 它的地面投影。
   */
  function buildGeometry(series, chrome) {
    var b = boundsOf(series);
    var pos = [], col = [], idx = [];
    var data = [];                      // 只装轨迹点：取景按它算，别让地面网格抢了景（否则弧线会被挤小）
    function push(pts, rgb) {
      if (!pts || pts.length < 2) { return; }
      var base = pos.length / 3;
      for (var i = 0; i < pts.length; i++) {
        pos.push(+pts[i][0], +pts[i][1], +pts[i][2]);
        col.push(rgb[0], rgb[1], rgb[2]);
      }
      for (var j = 0; j + 1 < pts.length; j++) { idx.push(base + j, base + j + 1); }
    }
    // 地面网格：水平跨度自适应（默认场景 z 恒为 0，网格会退成一条线 —— 那是数据决定的）。
    var half = Math.max(b.span[0], b.span[2], b.radius) * 0.62;
    var gy = b.lo[1], gx = b.center[0], gz = b.center[2], n = 8;
    var gridRgb = hex2rgb(chrome.grid);
    if (half > 0) {
      for (var g = 0; g <= n; g++) {
        var u = -half + (2 * half * g) / n;
        push([[gx + u, gy, gz - half], [gx + u, gy, gz + half]], gridRgb);
        push([[gx - half, gy, gz + u], [gx + half, gy, gz + u]], gridRgb);
      }
    }
    // 坐标轴三色：x 红 / y 绿（高度）/ z 蓝，长度按包围盒自适应
    var ax = Math.max(half * 0.32, b.radius * 0.1);
    var yax = Math.max(b.span[1] * 0.5, ax * 0.5);
    var ox = b.lo[0], oy = b.lo[1], oz = b.lo[2];
    push([[ox, oy, oz], [ox + ax, oy, oz]], hex2rgb(chrome.axisX));
    push([[ox, oy, oz], [ox, oy + yax, oz]], hex2rgb(chrome.axisY));
    push([[ox, oy, oz], [ox, oy, oz + ax]], hex2rgb(chrome.axisZ));
    // 轨迹线（一条一个弹）+ 它在地面上的淡色投影
    var lines = 0;
    (series || []).forEach(function (s) {
      if (!s || !s.points || s.points.length < 2) { return; }
      var color = s.color || chrome.line;
      push(s.points, hex2rgb(color));
      for (var q = 0; q < s.points.length; q++) {
        data.push(+s.points[q][0], +s.points[q][1], +s.points[q][2]);
      }
      push(shadowOf(s.points, gy), hex2rgb(mixHex(color, chrome.bg, 0.62)));
      lines += 1;
    });
    return { pos: pos, col: col, idx: idx, data: data, bounds: b, lines: lines };
  }

  /**
   * 取景距离：先按外接球估，再用**真实投影**迭代收紧（弹道常常很扁，球估会显得很小）。
   * 目标是"最外的顶点落在 ±0.86 的 NDC 内"（留 14% 边）。纯函数，node 可测。
   */
  function fitDistance(geo, cam, aspect) {
    var b = geo.bounds;
    // 取景只看**轨迹点**（geo.data）；没有 data 的调用方（老 probe）退回全部顶点。
    var src = (geo.data && geo.data.length) ? geo.data : geo.pos;
    var r = Math.max(b.radius, 1e-6);
    var fovy = 0.9;
    var asp = Math.max(aspect, 0.05);
    var d = Math.max(2.2 * r, (2.2 * r) / Math.max(asp, 0.25));
    var cx = b.center[0], cy = b.center[1], cz = b.center[2];
    for (var it = 0; it < 12; it++) {
      var V = M4.view(cam.az, cam.el, d, cx, cy, cz);
      var M = M4.mul(M4.persp(fovy, asp, Math.max(d * 0.01, 1e-3), d * 8 + r * 4), V);
      var worst = 0;
      for (var i = 0; i < src.length; i += 3) {
        var x = src[i], y = src[i + 1], z = src[i + 2];
        var cw = M[3] * x + M[7] * y + M[11] * z + M[15];
        if (!(cw > 0)) { worst = Math.max(worst, 4); continue; }
        var nx = (M[0] * x + M[4] * y + M[8] * z + M[12]) / cw;
        var ny = (M[1] * x + M[5] * y + M[9] * z + M[13]) / cw;
        var m = Math.max(Math.abs(nx), Math.abs(ny));
        if (m > worst) { worst = m; }
      }
      if (!(worst > 1e-9)) { break; }
      var k = worst / 0.86;
      if (Math.abs(k - 1) < 0.02) { break; }
      d = clamp(d * k, r * 0.12, r * 40);
    }
    return d;
  }

  /* ================================================================== 渲染器 */
  function makeProgram(gl, vs, fs) {
    var p = gl.createProgram();
    var pair = [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]];
    for (var i = 0; i < pair.length; i++) {
      var sh = gl.createShader(pair[i][0]);
      gl.shaderSource(sh, pair[i][1]);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(sh) || "shader 编译失败");
      }
      gl.attachShader(p, sh);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(p) || "program 链接失败");
    }
    return p;
  }

  function viewer(gl, chrome) {
    var prog = makeProgram(gl, VS, FS);
    var aPos = gl.getAttribLocation(prog, "a_pos");
    var aCol = gl.getAttribLocation(prog, "a_col");
    var uMvp = gl.getUniformLocation(prog, "u_mvp");
    var vbo = gl.createBuffer(), ibo = gl.createBuffer();
    var count = 0;
    var geo = { pos: [], col: [], idx: [], bounds: boundsOf([]), lines: 0 };
    var cam = { az: AZ0, el: EL0, dist: 1, pan: [0, 0, 0] };
    var didFit = false;
    var bg = hex2rgb(chrome.bg);

    function setGeometry(g) {
      geo = g || geo;
      var n = geo.pos.length / 3;
      var DATA = new Float32Array(n * 6);
      for (var i = 0; i < n; i++) {
        DATA[i * 6] = geo.pos[i * 3];
        DATA[i * 6 + 1] = geo.pos[i * 3 + 1];
        DATA[i * 6 + 2] = geo.pos[i * 3 + 2];
        DATA[i * 6 + 3] = geo.col[i * 3];
        DATA[i * 6 + 4] = geo.col[i * 3 + 1];
        DATA[i * 6 + 5] = geo.col[i * 3 + 2];
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, DATA, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint32Array(geo.idx), gl.STATIC_DRAW);
      count = geo.idx.length;
    }

    function fit(aspect, force) {
      if (!force && didFit) { return; }
      cam.dist = fitDistance(geo, cam, aspect);
      if (force) { cam.pan = [0, 0, 0]; }
      didFit = true;
    }

    function draw() {
      var W = gl.drawingBufferWidth || 1, H = gl.drawingBufferHeight || 1;
      gl.viewport(0, 0, W, H);
      gl.clearColor(bg[0], bg[1], bg[2], 1);
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      if (!count) { return; }
      var aspect = W / Math.max(H, 1);
      var b = geo.bounds;
      var cx = b.center[0] + cam.pan[0], cy = b.center[1] + cam.pan[1], cz = b.center[2] + cam.pan[2];
      var r = Math.max(b.radius, 1);
      var dist = Math.max(cam.dist, r * 0.05);
      var near = Math.max(dist * 0.01, 1e-3), far = dist * 8 + r * 4;
      var V = M4.view(cam.az, cam.el, dist, cx, cy, cz);
      var MVP = M4.mul(M4.persp(0.9, aspect, near, far), V);
      gl.useProgram(prog);
      gl.uniformMatrix4fv(uMvp, false, MVP);
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 24, 0);
      gl.enableVertexAttribArray(aCol);
      gl.vertexAttribPointer(aCol, 3, gl.FLOAT, false, 24, 12);
      gl.drawElements(gl.LINES, count, gl.UNSIGNED_INT, 0);
    }

    return {
      cam: cam,
      setGeometry: setGeometry,
      fit: fit,
      draw: draw,
      bounds: function () { return geo.bounds; },
      lineCount: function () { return geo.lines; },
      vertCount: function () { return count; }
    };
  }

  /* ================================================================ 门面（冻结） */
  function mount(host, opts) {
    if (!host || typeof document === "undefined") { throw new Error("mount 需要 DOM 宿主"); }
    opts = opts || {};
    var chrome = mergeChrome(opts.chrome);
    host.textContent = "";
    var cv = document.createElement("canvas");
    cv.className = "traj3d-canvas";
    host.appendChild(cv);
    var gl = null;
    try { gl = cv.getContext("webgl2", { antialias: true, alpha: false }); } catch (e) { gl = null; }
    if (!gl) {
      var msgEl = document.createElement("div");
      msgEl.className = "traj3d-fail";
      msgEl.textContent = "这台浏览器或当前环境不支持 WebGL2，三维轨迹画不出来";
      host.appendChild(msgEl);
      return {
        available: function () { return false; },
        setSeries: function () { return 0; },
        clear: function () {},
        reset: function () {},
        stats: function () { return null; }
      };
    }
    var raf = global.requestAnimationFrame || function (fn) { return setTimeout(function () { fn(Date.now()); }, 16); };
    var v = viewer(gl, chrome);
    var pending = 0, series = [];

    function drawFrame() { try { v.draw(); } catch (e) { /* 一帧画不出来不该把页面打挂 */ } }
    function requestDraw() {
      if (pending) { return; }
      pending = raf(function () { pending = 0; drawFrame(); });
    }
    function aspect() { return (cv.width || 1) / Math.max(cv.height || 1, 1); }
    function resize() {
      var dpr = Math.min(global.devicePixelRatio || 1, 2);
      var w = Math.round((cv.clientWidth || 0) * dpr), h = Math.round((cv.clientHeight || 0) * dpr);
      if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) { cv.width = w; cv.height = h; }
      v.fit(aspect(), false);
      requestDraw();
    }

    /* ---- 交互：拖拽旋转 / 右键或 Shift 平移 / 滚轮缩放 / 双击复位 ---- */
    var dragging = 0, lx = 0, ly = 0;
    cv.addEventListener("pointerdown", function (e) {
      dragging = (e.button === 2 || e.shiftKey) ? 2 : 1;
      lx = e.clientX; ly = e.clientY;
      cv.classList.add("drag");
      if (cv.setPointerCapture) { try { cv.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ } }
    });
    cv.addEventListener("pointermove", function (e) {
      if (!dragging) { return; }
      var dx = e.clientX - lx, dy = e.clientY - ly;
      lx = e.clientX; ly = e.clientY;
      var b = v.bounds();
      if (dragging === 1) { applyDrag(v.cam, dx, dy); } else { applyPan(v.cam, dx, dy, b.radius); }
      requestDraw();
    });
    function stopDrag() { dragging = 0; cv.classList.remove("drag"); }
    cv.addEventListener("pointerup", stopDrag);
    cv.addEventListener("pointercancel", stopDrag);
    cv.addEventListener("pointerleave", stopDrag);
    cv.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    cv.addEventListener("wheel", function (e) {
      e.preventDefault();
      var b = v.bounds();
      var r = Math.max(b.radius, 1);
      v.cam.dist = clamp(v.cam.dist * (e.deltaY > 0 ? 1.1 : 0.9), r * 0.12, r * 40);
      requestDraw();
    }, { passive: false });
    cv.addEventListener("dblclick", function () { reset(); });
    if (global.addEventListener) { global.addEventListener("resize", resize); }
    if (global.ResizeObserver) { new global.ResizeObserver(function () { resize(); }).observe(host); }

    function reset() {
      v.cam.az = AZ0; v.cam.el = EL0;
      v.fit(aspect(), true);
      requestDraw();
    }

    var api = {
      available: function () { return true; },
      setSeries: function (list) {
        series = (list || []).filter(function (s) { return s && s.points && s.points.length >= 2; });
        v.setGeometry(buildGeometry(series, chrome));
        v.fit(aspect(), true);
        resize();
        requestDraw();
        return series.length;
      },
      clear: function () {
        series = [];
        v.setGeometry(buildGeometry([], chrome));
        requestDraw();
      },
      reset: reset,
      stats: function () {
        var b = v.bounds();
        return { lines: v.lineCount(), verts: v.vertCount(), radius: b.radius,
                 center: b.center, span: b.span };
      }
    };
    resize();
    return api;
  }

  var API = { mount: mount, M4: M4, AZ0: AZ0, EL0: EL0,
              applyDrag: applyDrag, applyPan: applyPan,
              boundsOf: boundsOf, buildGeometry: buildGeometry, fitDistance: fitDistance,
              hex2rgb: hex2rgb, mixHex: mixHex, CHROME_DEFAULT: CHROME_DEFAULT };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node 自检用
  global.TRAJFAN = API;
})(typeof window !== "undefined" ? window : globalThis);

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
  // 信息窗格里只放来自目录的字符串 —— 仍然转义一遍，别让名字里的 < 破坏结构。
  function esc(t) {
    return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }

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
  // ---- 色相旋转（2026-10-24 用户口径："加上弹道颜色区分"）----
  // 目录 style 只有红/绿/蓝灰三个色相，11 条弹道全从 point_color 派生深浅 ⇒ 挤在一起分不开。
  // 这里在**目录基色的色相**上做等间隔旋转，亮度/饱和度保持不变 ⇒ 不引入任何新色值字面量，
  // 仍然是"配色来自目录"（转的是同一个颜色的色相，不是另起一套调色板）。
  function rgb2hsl(c) {
    var r = c[0], g = c[1], b = c[2];
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    var l = (mx + mn) / 2, h = 0, s = 0, d = mx - mn;
    if (d > 1e-9) {
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      if (mx === r) { h = ((g - b) / d + (g < b ? 6 : 0)); }
      else if (mx === g) { h = (b - r) / d + 2; }
      else { h = (r - g) / d + 4; }
      h = h / 6;
    }
    return [h, s, l];
  }
  function hsl2rgb(h, s, l) {
    h = ((h % 1) + 1) % 1;
    if (s <= 1e-9) { return [l, l, l]; }
    function hue2rgb(p, q, t) {
      if (t < 0) { t += 1; }
      if (t > 1) { t -= 1; }
      if (t < 1 / 6) { return p + (q - p) * 6 * t; }
      if (t < 1 / 2) { return q; }
      if (t < 2 / 3) { return p + (q - p) * (2 / 3 - t) * 6; }
      return p;
    }
    var q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    return [hue2rgb(p, q, h + 1 / 3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1 / 3)];
  }
  // 第 i 条（共 n 条）：色相转 i/n 圈，亮度按奇偶微调一档 —— 相邻两条既不同色相也不同明度。
  function spinHex(text, i, n) {
    var c = hex2rgb(text), hsl = rgb2hsl(c);
    if (!(n > 1)) { return rgb2hex(c); }
    var h = hsl[0] + (i / n) * 0.82;                 // 留一小段不闭环，首尾更好分
    var l = clamp(hsl[2] + ((i % 2) ? -0.07 : 0.03), 0.22, 0.72);
    return rgb2hex(hsl2rgb(h, clamp(hsl[1], 0.35, 0.92), l));
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
    "in vec3 a_pos; in vec3 a_col; in float a_prog;",
    "uniform mat4 u_mvp; uniform float u_ptSize;",
    "out vec3 v_col; out float v_prog;",
    "void main() {",
    "  v_col = a_col; v_prog = a_prog;",
    "  gl_Position = u_mvp * vec4(a_pos, 1.0);",
    "  gl_PointSize = u_ptSize;",
    "}"].join("\n");
  // 播放器靠这一行：每个顶点带「全局归一化时间」a_prog（0..1），超过 u_progress 的直接丢弃
  // => 不用重建几何、不用重传缓冲，拖滑块也是即时的。网格/坐标轴给 -1 => 永远不丢。
  var FS = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; in float v_prog; out vec4 outColor;",
    "uniform float u_progress;",
    "void main() {",
    "  if (v_prog >= 0.0 && v_prog > u_progress) { discard; }",
    "  outColor = vec4(v_col, 1.0);",
    "}"].join("\n");

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
    // prog：每个顶点的「全局归一化时间」；<0 表示"不参与播放"（网格/坐标轴/地面投影）。
    var prog = [];
    function push(pts, rgb, progOf) {
      if (!pts || pts.length < 2) { return; }
      var base = pos.length / 3;
      for (var i = 0; i < pts.length; i++) {
        pos.push(+pts[i][0], +pts[i][1], +pts[i][2]);
        col.push(rgb[0], rgb[1], rgb[2]);
        prog.push(progOf ? +progOf(i) : -1);
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
      // 播放进度：本弹自身时间轴上归一化（ts 是秒；缺 ts 就按点序均分，仍能播）。
      var ts = s.ts || null, tEnd = 0;
      if (ts && ts.length === s.points.length) {
        for (var z2 = 0; z2 < ts.length; z2++) { if (+ts[z2] > tEnd) { tEnd = +ts[z2]; } }
      }
      push(s.points, hex2rgb(color), function (i) {
        if (ts && ts.length === s.points.length) {
          return tEnd > 0 ? clamp(+ts[i] / tEnd, 0, 1) : 0;
        }
        return s.points.length > 1 ? i / (s.points.length - 1) : 0;
      });
      for (var q = 0; q < s.points.length; q++) {
        data.push(+s.points[q][0], +s.points[q][1], +s.points[q][2]);
      }
      // 地面投影不参与播放（它只是参照，跟着长出来反而乱）
      push(shadowOf(s.points, gy), hex2rgb(mixHex(color, chrome.bg, 0.62)), null);
      lines += 1;
    });
    return { pos: pos, col: col, prog: prog, idx: idx, data: data, bounds: b, lines: lines };
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
    var aProg = gl.getAttribLocation(prog, "a_prog");
    var uMvp = gl.getUniformLocation(prog, "u_mvp");
    var uProgress = gl.getUniformLocation(prog, "u_progress");
    var progress = 1;                     // 1 = 全部显示（默认，非播放态）
    var vbo = gl.createBuffer(), ibo = gl.createBuffer();
    var count = 0;
    var geo = { pos: [], col: [], idx: [], bounds: boundsOf([]), lines: 0 };
    var cam = { az: AZ0, el: EL0, dist: 1, pan: [0, 0, 0] };
    var didFit = false;
    var lastMvp = null, lastW = 0, lastH = 0;
    var bg = hex2rgb(chrome.bg);

    function setGeometry(g) {
      geo = g || geo;
      var n = geo.pos.length / 3;
      var DATA = new Float32Array(n * 7);          // x y z r g b prog
      for (var i = 0; i < n; i++) {
        DATA[i * 7] = geo.pos[i * 3];
        DATA[i * 7 + 1] = geo.pos[i * 3 + 1];
        DATA[i * 7 + 2] = geo.pos[i * 3 + 2];
        DATA[i * 7 + 3] = geo.col[i * 3];
        DATA[i * 7 + 4] = geo.col[i * 3 + 1];
        DATA[i * 7 + 5] = geo.col[i * 3 + 2];
        DATA[i * 7 + 6] = (geo.prog && geo.prog.length > i) ? +geo.prog[i] : -1;
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
      gl.uniform1f(uProgress, progress);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 28, 0);
      gl.enableVertexAttribArray(aCol);
      gl.vertexAttribPointer(aCol, 3, gl.FLOAT, false, 28, 12);
      if (aProg >= 0) {
        gl.enableVertexAttribArray(aProg);
        gl.vertexAttribPointer(aProg, 1, gl.FLOAT, false, 28, 24);
      }
      gl.drawElements(gl.LINES, count, gl.UNSIGNED_INT, 0);
      lastMvp = MVP; lastW = W; lastH = H;
    }

    return {
      cam: cam,
      mvp: function () { return lastMvp; },
      size: function () { return [lastW || 1, lastH || 1]; },
      // 播放进度 0..1：只改一个 uniform，**不重建几何、不重传缓冲**。
      setProgress: function (p) { progress = clamp(+p, 0, 1); },
      progress: function () { return progress; },
      setGeometry: setGeometry,
      fit: fit,
      draw: draw,
      bounds: function () { return geo.bounds; },
      lineCount: function () { return geo.lines; },
      vertCount: function () { return count; }
    };
  }

  // 世界坐标 -> 画布像素（与 draw() 用同一个 MVP ⇒ 标注和线永远对得上）。
  function projectPoint(mvp, W, H, p) {
    if (!mvp || !p) { return null; }
    var x = p[0], y = p[1], z = p[2];
    var cx = mvp[0] * x + mvp[4] * y + mvp[8] * z + mvp[12];
    var cy = mvp[1] * x + mvp[5] * y + mvp[9] * z + mvp[13];
    var cw = mvp[3] * x + mvp[7] * y + mvp[11] * z + mvp[15];
    if (!(cw > 1e-6)) { return null; }                 // 在相机后面
    return [(cx / cw * 0.5 + 0.5) * W, (0.5 - cy / cw * 0.5) * H];
  }
  // 点到线段的屏幕距离（拾取用）。返回 {dist, t}。
  function segDist(px, py, ax, ay, bx, by) {
    var vx = bx - ax, vy = by - ay;
    var len2 = vx * vx + vy * vy;
    var t = len2 > 1e-9 ? ((px - ax) * vx + (py - ay) * vy) / len2 : 0;
    t = clamp(t, 0, 1);
    var qx = ax + vx * t, qy = ay + vy * t;
    return {dist: Math.sqrt((px - qx) * (px - qx) + (py - qy) * (py - qy)), t: t};
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

    /* ---- 覆盖层：命中点标签 + 悬停信息窗格（DOM，不是 WebGL —— 文字才清晰、可选中）---- */
    var overlay = document.createElement("div");
    overlay.className = "traj3d-overlay";
    host.appendChild(overlay);
    var tips = [];                       // 每条线的"末端命中"标签
    var tip = null;                      // 悬停信息窗格
    function makeTip() {
      if (tip) { return tip; }
      tip = document.createElement("div");
      tip.className = "traj3d-tip";
      tip.hidden = true;
      overlay.appendChild(tip);
      return tip;
    }
    function setTip(html, x, y) {
      var el = makeTip();
      el.innerHTML = html;
      el.hidden = false;
      // 靠近右/下边缘时翻到另一侧，别被画布裁掉
      var w = el.offsetWidth || 180, h = el.offsetHeight || 60;
      var W = cv.clientWidth || 0, H = cv.clientHeight || 0;
      var px = x + 14, py = y + 14;
      if (px + w > W - 4) { px = Math.max(4, x - w - 14); }
      if (py + h > H - 4) { py = Math.max(4, y - h - 14); }
      el.style.left = px + "px";
      el.style.top = py + "px";
    }
    function hideTip() { if (tip) { tip.hidden = true; } }

    // 每条线的末端画一个小标签（命中时间）；点就是点列最后一点。
    function rebuildLabels() {
      tips.forEach(function (el) { if (el.parentNode) { el.parentNode.removeChild(el); } });
      tips = [];
      series.forEach(function (s2) {
        if (!s2 || !s2.points || !s2.points.length) { return; }
        var el = document.createElement("span");
        el.className = "traj3d-hit";
        el.textContent = (s2.label || s2.key) + (s2.tHit != null ? " " + fmtT(s2.tHit) : "");
        el.style.borderColor = s2.color || chrome.line;
        el.style.color = s2.color || chrome.line;
        overlay.appendChild(el);
        tips.push(el);
      });
      placeLabels();
    }
    function fmtT(t) {
      var n = Number(t);
      if (!isFinite(n)) { return ""; }
      return n.toFixed(2) + " s";
    }
    // 标签位置 = 末端点的屏幕坐标；按 y 排序后做简单避让（同一高度的标签错开）
    function placeLabels() {
      var mvp = v.mvp(), sz = v.size();
      var W = sz[0], H = sz[1];
      var dpr = (cv.width || 1) / Math.max(cv.clientWidth || 1, 1);
      var used = [];
      var items = [];
      series.forEach(function (s2, i) {
        var el = tips[i];
        if (!el || !s2.points || !s2.points.length) { return; }
        var p = s2.points[s2.points.length - 1];
        var sp = projectPoint(mvp, W, H, p);
        if (!sp) { el.style.display = "none"; return; }
        items.push({el: el, x: sp[0] / dpr, y: sp[1] / dpr});
      });
      items.sort(function (a, b) { return a.y - b.y; });
      items.forEach(function (it) {
        var y = it.y, guard = 0;
        while (guard < 40) {
          var clash = false;
          for (var k = 0; k < used.length; k++) {
            if (Math.abs(used[k] - y) < 13) { clash = true; break; }
          }
          if (!clash) { break; }
          y += 13; guard += 1;
        }
        used.push(y);
        it.el.style.display = "";
        it.el.style.left = Math.max(2, Math.min(it.x + 6, (cv.clientWidth || 0) - 60)) + "px";
        it.el.style.top = y + "px";
      });
    }

    // 悬停拾取：把鼠标位置换成"离哪条线最近"（阈值 10 CSS px）
    var hoverSeq = 0;
    function pickAt(mx, my) {
      var mvp = v.mvp(), sz = v.size();
      var W = sz[0], H = sz[1];
      var dpr = (cv.width || 1) / Math.max(cv.clientWidth || 1, 1);
      var best = null;
      series.forEach(function (s2) {
        if (!s2 || !s2.points || s2.points.length < 2) { return; }
        var pts = s2.points;
        var prev = projectPoint(mvp, W, H, pts[0]);
        for (var i = 1; i < pts.length; i++) {
          var cur = projectPoint(mvp, W, H, pts[i]);
          if (prev && cur) {
            var d = segDist(mx * dpr, my * dpr, prev[0], prev[1], cur[0], cur[1]);
            if (!best || d.dist < best.dist) {
              best = {dist: d.dist, t: (i - 1 + d.t) / (pts.length - 1), s: s2};
            }
          }
          prev = cur;
        }
      });
      if (!best) { return null; }
      if (best.dist / dpr > 10) { return null; }
      // 把 0..1 的线段比例换成**精确采样点下标**：遥测按点取值，别在两点之间插值
      // （点列是抽稀过的，插值出来的数不来自内核）。
      var n2 = best.s.points.length;
      best.idx = Math.max(0, Math.min(n2 - 1, Math.round(best.t * (n2 - 1))));
      return best;
    }

    function drawFrame() {
      try { v.draw(); } catch (e) { /* 一帧画不出来不该把页面打挂 */ }
      try { placeLabels(); } catch (e2) { /* 标注定位失败不该影响画面 */ }
    }
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
      if (!dragging) {
        // 悬停：命中某条轨迹 ⇒ 出信息窗格（拖动时不出，避免跟手打架）
        var rect = cv.getBoundingClientRect ? cv.getBoundingClientRect() : {left: 0, top: 0};
        var mx = e.clientX - (rect.left || 0), my = e.clientY - (rect.top || 0);
        var hit = pickAt(mx, my);
        if (!hit) { hideTip(); cv.classList.remove("hot"); return; }
        cv.classList.add("hot");
        // 悬停窗格交给壳渲染（2026-10-24 用户口径：窗格是**鼠标放上去才显示**的，
        // 不是常驻面板）。三维层只负责"选中了哪条线、哪个采样点"。
        if (typeof opts.onHover === "function") {
          try {
            opts.onHover({key: hit.s.key, label: hit.s.label, color: hit.s.color,
                          idx: hit.idx, n: hit.s.points.length, t: hit.t, series: hit.s},
                         mx, my);
          } catch (e2) { /* 壳里的渲染出错不该把三维交互打挂 */ }
        } else {
          // 兜底（没挂 onHover 时）：仍给一个最小提示，别让用户以为没反应
          var s2 = hit.s;
          var html = '<b style="color:' + (s2.color || chrome.line) + '">'
            + esc(s2.label || s2.key) + '</b>';
          setTip(html, mx, my);
        }
        return;
      }
      var dx = e.clientX - lx, dy = e.clientY - ly;
      lx = e.clientX; ly = e.clientY;
      var b = v.bounds();
      if (dragging === 1) { applyDrag(v.cam, dx, dy); } else { applyPan(v.cam, dx, dy, b.radius); }
      requestDraw();
    });
    function stopDrag() { dragging = 0; cv.classList.remove("drag"); }
    cv.addEventListener("pointerup", stopDrag);
    cv.addEventListener("pointercancel", stopDrag);
    cv.addEventListener("pointerleave", function () {
      stopDrag(); hideTip(); cv.classList.remove("hot");
      if (typeof opts.onHover === "function") { try { opts.onHover(null); } catch (e2) {} }
    });
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
      hideTip();
      requestDraw();
    }

    /* ---- 播放器状态 ---- */
    var playT = 1, playing = false;
    function stopPlay() { playing = false; }
    // 全局时长（秒）= 所有弹 t_hit 的最大值；没有 t_hit 就退回 1（按点序播）。
    function duration() {
      var d = 0;
      series.forEach(function (s2) {
        if (s2 && s2.tHit != null && isFinite(+s2.tHit) && +s2.tHit > d) { d = +s2.tHit; }
      });
      return d > 0 ? d : 0;
    }
    // 进度变化时：还没飞到的弹，末端标签要藏起来（否则会浮在空白处）
    function updateLabelsForProgress(p) {
      series.forEach(function (s2, i) {
        var el = tips[i];
        if (!el) { return; }
        var t = (s2 && s2.tHit != null) ? +s2.tHit : null;
        var reached = (p >= 0.999) || (t == null) || (t <= p * duration() + 1e-9);
        el.hidden = !reached;
      });
    }

    var api = {
      available: function () { return true; },
      setSeries: function (list) {
        // 每条可以有 tHit / maxAlt / distFlown（壳从 /v1/trajectory 的 case 里带过来）；
        // 缺了也不影响画线，只是标签与窗格里少几行。
        series = (list || []).filter(function (s) { return s && s.points && s.points.length >= 2; });
        v.setGeometry(buildGeometry(series, chrome));
        v.fit(aspect(), true);
        resize();
        rebuildLabels();
        requestDraw();
        return series.length;
      },
      clear: function () {
        series = [];
        tips.forEach(function (el) { if (el.parentNode) { el.parentNode.removeChild(el); } });
        tips = [];
        hideTip();
        stopPlay();
        v.setGeometry(buildGeometry([], chrome));
        requestDraw();
      },
      // ---- 播放器（2026-10-24 用户口径：从发射播到最后一枚命中）----
      // 全局时间轴 = 所有轨迹的 [0, max(t_hit)]。progress 是**时间**归一化，不是点序，
      // 所以快慢不同的弹会按真实时间先后到达（这是这个功能的意义）。
      setProgress: function (p) {
        var q = clamp(+p, 0, 1);
        playT = q;
        v.setProgress(q);
        updateLabelsForProgress(q);
        requestDraw();
        return q;
      },
      progress: function () { return playT; },
      duration: function () { return duration(); },
      play: function (onDone) {
        stopPlay();
        var dur = duration();
        if (!(dur > 0)) { return false; }
        var t0 = (global.performance && global.performance.now) ? global.performance.now() : Date.now();
        var from = playT >= 0.999 ? 0 : playT;
        playing = true;
        function tick() {
          if (!playing) { return; }
          var now = (global.performance && global.performance.now) ? global.performance.now() : Date.now();
          var p = from + (now - t0) / (dur * 1000);
          if (p >= 1) {
            api.setProgress(1);
            playing = false;
            if (typeof onTick === "function") { try { onTick(1); } catch (e) {} }
            if (typeof onDone === "function") { try { onDone(); } catch (e) {} }
            return;
          }
          api.setProgress(p);
          // ⚠ 每帧回调一次：时钟与滑块要跟着走（只更新三维层的话，用户看到的是"暂停着但按钮写暂停"）。
          if (typeof onTick === "function") { try { onTick(p); } catch (e) {} }
          raf(tick);
        }
        var onTick = api._onTick;
        raf(tick);
        return true;
      },
      // 壳把"每帧刷新时钟/滑块"挂在这里（三维层不该知道 DOM 长什么样）。
      onTick: function (fn) { api._onTick = fn; },
      pause: function () { stopPlay(); },
      playing: function () { return playing; },
      // 拾取与投影也给出去：判据要在 node 里验"鼠标压在线附近能选中"这件事。
      pick: function (mx, my) { return pickAt(mx, my); },
      project: function (p) {
        var sz = v.size();
        return projectPoint(v.mvp(), sz[0], sz[1], p);
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
              hex2rgb: hex2rgb, rgb2hex: rgb2hex, mixHex: mixHex, spinHex: spinHex,
              rgb2hsl: rgb2hsl, hsl2rgb: hsl2rgb, projectPoint: projectPoint,
              segDist: segDist, esc: esc, CHROME_DEFAULT: CHROME_DEFAULT };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node 自检用
  global.TRAJFAN = API;
})(typeof window !== "undefined" ? window : globalThis);

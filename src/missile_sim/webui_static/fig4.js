"use strict";
/* 图4 交互式三维散点 —— **手写 WebGL2**，零第三方 JS/CSS/字体（离线免安装是底线）。
 *
 * 数据：`GET /api/fig4/<tag|job_id>`（服务端只读产物、**不解算**）。
 * 三根轴：x = β、y = ΔV、z = γ（各自归一化到 [-0.5, 0.5] 的等长立方体，刻度与标签是真值）。
 * 颜色 = t_hit（连续色标）或两个证据量（线性残差 / 二次项曲率），色标范围**11 枚弹共享**。
 *
 * 三条硬约束（有测试钉着）：
 *   1. 本文件**一个颜色字面量都没有** —— 全部颜色从响应里的 `colors` 取
 *      （源头是 `figures.FIG4_*`）；chrome 的底色/线色写在 `fig4.css` 里；
 *   2. 命中/脱靶**不靠颜色区分**：脱靶一律画成**空心**标记（它根本没有 t_hit 可着色）；
 *   3. 切换弹种**只换点云**：色标范围来自响应里的 `shared.ranges`，不按选中的那朵点云重算。
 */
(function (global) {
  // localStorage 键：与查看器（viewer3d）不共用 —— 两张图的控件不一样，
  // 混用一个键会让"记住上次选择"互相打补丁。测试钉着这个字面量。
  var STORE_KEY = "missile-sim.fig4";

  /* ==================================================================== 数学 */
  var M4 = {
    ident: function () { return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]); },
    mul: function (a, b) {
      var o = new Float32Array(16);
      for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) {
        var s = 0;
        for (var k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
        o[c * 4 + r] = s;
      }
      return o;
    },
    view: function (az, el, dist, cx, cy, cz) {
      var ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
      var dir = [ce * ca, se, ce * sa];
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
    },
  };
  function norm(v) {
    var n = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  /* =================================================================== 颜色 */
  // 颜色全部由响应给（`d.colors`）；这里只做**插值**，不定义任何色相。
  function hex2rgb(text) {
    var s = String(text).replace("#", "");
    return [parseInt(s.substr(0, 2), 16) / 255,
            parseInt(s.substr(2, 2), 16) / 255,
            parseInt(s.substr(4, 2), 16) / 255];
  }
  function mixColor(a, b, k) {
    var f = clamp(k, 0, 1);
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }
  function rampBands(stops) {
    return stops.map(function (h) { return hex2rgb(h); });
  }
  // ⚠ 取颜色只有这一条路：**响应里没有就当场抛**。
  //   绝不写 `colors.x || "#rrggbb"` —— 本文件的判据就是"零颜色字面量"，
  //   而且兜底色会让"配色没传对"变成一张**看起来正常**的图（静默不一致那类坑）。
  function needColor(colors, key) {
    var v = colors ? colors[key] : null;
    if (typeof v !== "string" || v.length < 4) {
      throw new Error("配色缺 " + key + "（响应里的 colors 不完整）");
    }
    return hex2rgb(v);
  }
  function needRamp(colors, mode) {
    var stops = colors && colors.cmap ? colors.cmap[mode] : null;
    if (!Array.isArray(stops) || stops.length < 2) {
      throw new Error("配色缺 cmap." + mode + "（响应里的 colors 不完整）");
    }
    return stops;
  }
  // `t` 用**数据域**里的比例（0 = 色标左端、1 = 右端）；越界一律夹住，不外推。
  function rampColor(stops, t) {
    var bands = Array.isArray(stops[0]) ? stops : rampBands(stops);
    if (bands.length === 1) return bands[0].slice();
    var f = clamp(t, 0, 1) * (bands.length - 1);
    var i = Math.min(Math.floor(f), bands.length - 2);
    return mixColor(bands[i], bands[i + 1], f - i);
  }
  function rgbCss(c) {
    return "rgb(" + Math.round(clamp(c[0], 0, 1) * 255) + "," +
      Math.round(clamp(c[1], 0, 1) * 255) + "," + Math.round(clamp(c[2], 0, 1) * 255) + ")";
  }
  function fmt(v, digits) {
    if (v === null || v === undefined) return "—";
    return (typeof v === "number") ? v.toFixed(digits === undefined ? 3 : digits) : String(v);
  }

  /* ============================================================ 网格 / 展平 */
  // 展平顺序：ΔV 外层 → γ → β（与 `fig4.FLAT_ORDER` 同序）。这三条关系必须只有一个出处。
  function nodeOf(p, nBeta, nGamma) {
    var span = nBeta * nGamma;
    var rest = p % span;
    return { i_dv: Math.floor(p / span), rest: rest,
             j_gamma: Math.floor(rest / nBeta), k_beta: rest % nBeta };
  }
  function columnOf(p, span) { return p % span; }
  function axisNorm(v, lo, hi) {
    var span = (hi - lo) || 1;
    return (v - lo) / span - 0.5;
  }
  // 一个格点的世界坐标：x = β、y = ΔV、z = γ（各自归一化 ⇒ 等长三轴）
  function pointPos(d, p) {
    var g = d.grid, nb = g.beta.length, ng = g.gamma.length;
    var nd = nodeOf(p, nb, ng);
    return [axisNorm(g.beta[nd.k_beta], g.beta[0], g.beta[g.beta.length - 1]),
            axisNorm(g.dv[nd.i_dv], g.dv[0], g.dv[g.dv.length - 1]),
            axisNorm(g.gamma[nd.j_gamma], g.gamma[0], g.gamma[g.gamma.length - 1])];
  }

  /* =============================================================== 点云配色 */
  // 当前弹 + 当前颜色模式 → 每个点的颜色、色标域、单位/口径。
  // ⚠ 色标域来自 `d.shared.ranges`（**全部**弹的点云算出来的），不是选中这朵点云自己的范围 ——
  //   否则切换弹种时同一片颜色会代表不同的秒数，"横向比较"当场变成假的。
  function colorDomain(d, mode) {
    var r = (d.shared && d.shared.ranges) || {};
    var dom = r[mode];
    if (!dom || dom[0] === null || dom[1] === null) {
      // 兜底：用当前弹自己的范围（并明确告诉调用方这是兜底，而不是"共享范围"）
      return null;
    }
    return [Number(dom[0]), Number(dom[1])];
  }
  function cloudColors(d, key, mode) {
    var cloud = (d.clouds || {})[key];
    var colors = d.colors || {};
    var cmap = needRamp(colors, mode);
    var modeInfo = (d.modes || []).filter(function (m) { return m.id === mode; })[0] || {};
    var dom = colorDomain(d, mode);
    var missC = needColor(colors, "miss");
    var hit = [], miss = [], hitIdx = [], missIdx = [];
    if (!cloud) return { hit: hit, miss: miss, hitIdx: hitIdx, missIdx: missIdx, domain: dom,
                         unit: modeInfo.unit || "", label: modeInfo.label || mode,
                         note: modeInfo.note || "", shared: !!dom };
    var lo = dom ? dom[0] : 0, hi = dom ? dom[1] : 1;
    var span = (hi - lo) || 1;
    var isMiss = {};
    (cloud.miss_idx || []).forEach(function (i) { isMiss[i] = true; });
    for (var p = 0; p < cloud.n; p++) {
      var pos = pointPos(d, p);
      if (isMiss[p]) {
        missIdx.push(p);
        miss.push(pos[0], pos[1], pos[2]);
        continue;
      }
      var v = cloud[mode === "t_hit" ? "t" : (mode === "resid" ? "resid" : "curv")];
      var val = (v && v[p] !== null && v[p] !== undefined) ? Number(v[p]) : lo;
      var c = rampColor(cmap, (val - lo) / span);
      hitIdx.push(p);
      hit.push(pos[0], pos[1], pos[2], c[0], c[1], c[2]);
    }
    return { hit: hit, miss: miss, hitIdx: hitIdx, missIdx: missIdx, domain: dom,
             unit: modeInfo.unit || "", label: modeInfo.label || mode,
             note: modeInfo.note || "", shared: !!dom, missColor: missC, cmap: cmap };
  }

  /* ==================================================== 证据层：曲线 / 平面 */
  // 逐 (β,γ) 列的二次拟合曲线（5 个 ΔV 节点连成的折线）—— 在三维盒子里就是"拟合曲面"的
  // 一族母线；弯不弯、弯在哪一根竖线上，一眼可见。
  function fitCurves(d, key, mode) {
    var cloud = (d.clouds || {})[key];
    var g = d.grid, nb = g.beta.length, ng = g.gamma.length;
    var out = [];
    if (!cloud || !cloud.quad) return out;
    var a = cloud.intercept || [], b = cloud.slope || [], c = (mode === "linear" ? null : cloud.quad) || [];
    for (var rest = 0; rest < nb * ng; rest++) {
      if (a[rest] === null || a[rest] === undefined) continue;
      var pts = [];
      for (var i = 0; i < g.dv.length; i++) {
        var dv = g.dv[i];
        var t = a[rest] + b[rest] * dv + (c[rest] ? c[rest] * dv * dv : 0);
        pts.push([axisNorm(g.beta[rest % nb], g.beta[0], g.beta[nb - 1]),
                  axisNorm(dv, g.dv[0], g.dv[g.dv.length - 1]),
                  axisNorm(g.gamma[Math.floor(rest / nb)], g.gamma[0], g.gamma[ng - 1]), t]);
      }
      out.push({ column: rest, pts: pts });
    }
    return out;
  }
  // 全局最小二乘平面的**等值面**：t = c0 + c1·β + c2·γ + c3·ΔV = L 在 (β,γ,ΔV) 盒子里是一个平面。
  // 逐 (β,γ) 小格解出 ΔV，超出盒子（或 c3≈0 退化成竖直面）就丢掉 —— 于是能直接看到
  // "这个平面在盒子的哪个角落根本够不到"。
  function planeQuads(d, key, levels) {
    var pl = ((d.fit || {}).plane || {})[key] || {};
    var coef = pl.coef;
    var out = { tris: [], levels: [], n: 0 };
    if (!coef || Math.abs(coef[3]) < 1e-12) return out;
    var g = d.grid, nb = g.beta.length, ng = g.gamma.length;
    var b0 = g.beta[0], b1 = g.beta[nb - 1], g0 = g.gamma[0], g1 = g.gamma[ng - 1];
    var d0 = g.dv[0], d1 = g.dv[g.dv.length - 1];
    for (var li = 0; li < levels.length; li++) {
      var L = levels[li], quads = [];
      for (var jb = 0; jb + 1 < nb; jb++) {
        for (var jg = 0; jg + 1 < ng; jg++) {
          var corners = [[g.beta[jb], g.gamma[jg]], [g.beta[jb + 1], g.gamma[jg]],
                         [g.beta[jb + 1], g.gamma[jg + 1]], [g.beta[jb], g.gamma[jg + 1]]];
          var world = [], ok = true;
          for (var q = 0; q < 4; q++) {
            var bb = corners[q][0], gg = corners[q][1];
            var dv = (L - coef[0] - coef[1] * bb - coef[2] * gg) / coef[3];
            if (!(dv >= d0 - 1e-9 && dv <= d1 + 1e-9)) { ok = false; break; }
            world.push([axisNorm(bb, b0, b1), axisNorm(dv, d0, d1), axisNorm(gg, g0, g1)]);
          }
          if (ok) quads.push(world);
        }
      }
      for (var qi = 0; qi < quads.length; qi++) {
        var w = quads[qi];
        out.tris.push(w[0], w[1], w[2], w[0], w[2], w[3]);
      }
      if (quads.length) out.levels.push(L);
    }
    out.n = out.tris.length;
    return out;
  }

  /* ================================================================== 盒子 */
  // 12 条棱 + 三根轴的刻度（刻度值是真的，世界坐标是归一化后的）。
  function buildBox(d) {
    var g = d.grid, colors = d.colors || {};
    var edges = [], ec = [], ticks = [];
    var C = [[-0.5, -0.5, -0.5], [0.5, -0.5, -0.5], [0.5, -0.5, 0.5], [-0.5, -0.5, 0.5],
             [-0.5, 0.5, -0.5], [0.5, 0.5, -0.5], [0.5, 0.5, 0.5], [-0.5, 0.5, 0.5]];
    var pairs = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4],
                 [0, 4], [1, 5], [2, 6], [3, 7]];
    var boxC = needColor(colors, "box");
    for (var i = 0; i < pairs.length; i++) {
      var p0 = C[pairs[i][0]], p1 = C[pairs[i][1]];
      edges.push(p0[0], p0[1], p0[2], p1[0], p1[1], p1[2]);
      ec.push(boxC[0], boxC[1], boxC[2], boxC[0], boxC[1], boxC[2]);
    }
    function addTicks(axisId, vals, lo, hi, at) {
      var c = hex2rgb((colors.axis || {})[axisId] || needColor(colors, "text"));
      for (var k = 0; k < vals.length; k++) {
        var u = axisNorm(vals[k], lo, hi);
        var p = at(u);
        ticks.push({ axis: axisId, value: vals[k], world: p,
                     color: colors.axis ? colors.axis[axisId] : undefined });
        // 刻度小短线：沿"朝外"的方向画一小段，让刻度在 3D 里看得见
        var out = [p[0] === -0.5 ? -0.03 : (p[0] === 0.5 ? 0.03 : 0),
                   p[1] === -0.5 ? -0.03 : (p[1] === 0.5 ? 0.03 : 0),
                   p[2] === -0.5 ? -0.03 : (p[2] === 0.5 ? 0.03 : 0)];
        if (!out[0] && !out[1] && !out[2]) out = [0, -0.03, 0];
        edges.push(p[0], p[1], p[2], p[0] + out[0], p[1] + out[1], p[2] + out[2]);
        ec.push(c[0], c[1], c[2], c[0], c[1], c[2]);
      }
    }
    addTicks("beta", g.beta, g.beta[0], g.beta[g.beta.length - 1],
             function (u) { return [u, -0.5, -0.5]; });
    addTicks("gamma", g.gamma, g.gamma[0], g.gamma[g.gamma.length - 1],
             function (u) { return [0.5, -0.5, u]; });
    addTicks("dv", g.dv, g.dv[0], g.dv[g.dv.length - 1],
             function (u) { return [-0.5, u, -0.5]; });
    return { edges: edges, edge_colors: ec, ticks: ticks };
  }

  /* ============================================================== 相机交互 */
  var AZ_PER_PX = 0.008, EL_PER_PX = 0.008, EL_LIMIT = 1.45;
  var AZ0 = -0.95, EL0 = 0.42;
  function applyDrag(cam, dx, dy) {
    cam.az += dx * AZ_PER_PX;                      // 跟手：拖 Δx>0 ⇒ 物体向右转
    cam.el = clamp(cam.el + dy * EL_PER_PX, -EL_LIMIT, EL_LIMIT);
  }
  function applyPan(cam, dx, dy) {
    var k = cam.dist * 0.0016;
    var ca = Math.cos(cam.az), sa = Math.sin(cam.az);
    cam.pan[0] -= (-sa * dx) * k;
    cam.pan[2] -= (ca * dx) * k;
    cam.pan[1] += dy * k;
  }
  function projectToScreen(P, cam, center, radius, W, H, fovy) {
    fovy = fovy || 0.9;
    var dist = Math.max(cam.dist, radius * 0.05);
    var near = Math.max(dist * 0.01, 1e-3), far = dist * 8 + radius * 4;
    var V = M4.view(cam.az, cam.el, dist,
      center[0] + cam.pan[0], center[1] + cam.pan[1], center[2] + cam.pan[2]);
    var M = M4.mul(M4.persp(fovy, W / Math.max(H, 1), near, far), V);
    var x = P[0], y = P[1], z = P[2];
    var cw = M[3] * x + M[7] * y + M[11] * z + M[15];
    if (!(cw > 0)) return null;
    var cx = M[0] * x + M[4] * y + M[8] * z + M[12];
    var cy = M[1] * x + M[5] * y + M[9] * z + M[13];
    return { x: (cx / cw * 0.5 + 0.5) * W, y: (0.5 - cy / cw * 0.5) * H };
  }

  /* ================================================================== 着色器 */
  var VS = ["#version 300 es",
    "in vec3 a_pos; in vec3 a_col; in float a_size;",
    "uniform mat4 u_mvp; uniform mat4 u_mv; uniform float u_ptScale;",
    "out vec3 v_col;",
    "void main() {",
    "  v_col = a_col;",
    "  vec4 mv = u_mv * vec4(a_pos, 1.0);",
    "  gl_Position = u_mvp * vec4(a_pos, 1.0);",
    "  gl_PointSize = clamp(a_size * u_ptScale / max(-mv.z, 1.0), 1.0, 24.0);",
    "}"].join("\n");
  var FS_SOLID = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; uniform float u_alpha; out vec4 outColor;",
    "void main() { outColor = vec4(v_col, u_alpha); }"].join("\n");
  var FS_DISC = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; out vec4 outColor;",
    "void main() {",
    "  vec2 d = gl_PointCoord - vec2(0.5);",
    "  if (dot(d, d) > 0.25) discard;",
    "  outColor = vec4(v_col, 1.0);",
    "}"].join("\n");
  // 脱靶：**空心**（只留外圈）—— 形状就分得开，不依赖颜色
  var FS_RING = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; out vec4 outColor;",
    "void main() {",
    "  float r = length(gl_PointCoord - vec2(0.5));",
    "  if (r > 0.5 || r < 0.30) discard;",
    "  outColor = vec4(v_col, 1.0);",
    "}"].join("\n");

  function compile(gl, vs, fs) {
    var p = gl.createProgram();
    var pair = [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]];
    for (var i = 0; i < pair.length; i++) {
      var sh = gl.createShader(pair[i][0]);
      gl.shaderSource(sh, pair[i][1]);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
      gl.attachShader(p, sh);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }

  /* ================================================================== 渲染器 */
  function viewer(gl, d, opts) {
    opts = opts || {};
    var colors = d.colors || {};
    var bg = needColor(colors, "bg");     // 透明底那一档用不到它，但契约上必须给
    var box = buildBox(d);
    var P_SOLID = compile(gl, VS, FS_SOLID);
    var P_DISC = compile(gl, VS, FS_DISC);
    var P_RING = compile(gl, VS, FS_RING);
    function loc(p) {
      return { pos: gl.getAttribLocation(p, "a_pos"), col: gl.getAttribLocation(p, "a_col"),
               size: gl.getAttribLocation(p, "a_size"),
               mvp: gl.getUniformLocation(p, "u_mvp"), mv: gl.getUniformLocation(p, "u_mv"),
               ptScale: gl.getUniformLocation(p, "u_ptScale"),
               alpha: gl.getUniformLocation(p, "u_alpha") };
    }
    var L_SOLID = loc(P_SOLID), L_DISC = loc(P_DISC), L_RING = loc(P_RING);

    function upload(spec, layout) {
      var n = spec.pos.length / 3;
      var DATA = new Float32Array(n * 7);
      for (var i = 0; i < n; i++) {
        DATA[i * 7 + 0] = spec.pos[i * 3]; DATA[i * 7 + 1] = spec.pos[i * 3 + 1];
        DATA[i * 7 + 2] = spec.pos[i * 3 + 2];
        DATA[i * 7 + 3] = spec.col[i * 3]; DATA[i * 7 + 4] = spec.col[i * 3 + 1];
        DATA[i * 7 + 5] = spec.col[i * 3 + 2];
        DATA[i * 7 + 6] = spec.size[i];
      }
      var vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, DATA, gl.STATIC_DRAW);
      var ibo = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint32Array(spec.idx), gl.STATIC_DRAW);
      return { vbo: vbo, ibo: ibo, count: spec.idx.length, layout: layout, n: n };
    }
    function update(buf, spec) {
      var n = buf.n, DATA = new Float32Array(n * 7);
      for (var i = 0; i < n; i++) {
        DATA[i * 7 + 0] = spec.pos[i * 3]; DATA[i * 7 + 1] = spec.pos[i * 3 + 1];
        DATA[i * 7 + 2] = spec.pos[i * 3 + 2];
        DATA[i * 7 + 3] = spec.col[i * 3]; DATA[i * 7 + 4] = spec.col[i * 3 + 1];
        DATA[i * 7 + 5] = spec.col[i * 3 + 2];
        DATA[i * 7 + 6] = spec.size[i];
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, buf.vbo);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, DATA);
      buf.count = spec.idx.length;
    }
    function uploadBuf(spec, layout, old) {
      if (old) { gl.deleteBuffer(old.vbo); gl.deleteBuffer(old.ibo); }
      return upload(spec, layout);
    }

    var B_BOX = upload({ pos: box.edges, col: box.edge_colors,
                         size: box.edges.map(function () { return 1; }),
                         idx: box.edges.map(function (_v, i) { return i; }) }, L_SOLID);
    var B_PLANE = upload({ pos: [], col: [], size: [], idx: [] }, L_SOLID);
    var B_FCURVE = upload({ pos: [], col: [], size: [], idx: [] }, L_SOLID);
    var B_HIT = upload({ pos: [], col: [], size: [], idx: [] }, L_DISC);
    var B_MISS = upload({ pos: [], col: [], size: [], idx: [] }, L_RING);

    var cam = { az: AZ0, el: EL0, dist: 1.6, pan: [0, 0, 0] };
    var radius = 0.87, center = [0, 0, 0];
    var spinning = false, showAxes = true;
    var state = { missile: "", mode: "t_hit", fitplane: 1, fitcols: 1, induced: 1, axes: 1 };

    // 点云 / 曲线 / 平面：切换弹种或颜色模式时重建（245 个点，代价可以忽略）。
    function buildCloud() {
      var cc = cloudColors(d, state.missile, state.mode);
      var hitPos = [], hitCol = [], hitIdx = [];
      for (var i = 0; i + 5 < cc.hit.length + 1; i += 6) {
        hitPos.push(cc.hit[i], cc.hit[i + 1], cc.hit[i + 2]);
        hitCol.push(cc.hit[i + 3], cc.hit[i + 4], cc.hit[i + 5]);
        hitIdx.push(hitIdx.length);
      }
      var missPos = [], missCol = [], missIdx = [];
      var mc = cc.missColor || needColor(colors, "miss");
      for (var j = 0; j + 2 < cc.miss.length + 1; j += 3) {
        missPos.push(cc.miss[j], cc.miss[j + 1], cc.miss[j + 2]);
        missCol.push(mc[0], mc[1], mc[2]);
        missIdx.push(missIdx.length);
      }
      // 诱导阻力主导的过滤：R_ref ≥ 1 的列保留（判定量是 (β,γ) 列的性质，不是单点的）
      var cloud = (d.clouds || {})[state.missile] || { n: 0 };
      var span = d.grid.column_span;
      var R = cloud.R_ref || [];
      var keepHit = [], keepCol = [], keepIdx = [];
      for (var k = 0; k < hitIdx.length; k++) {
        var p = cc.hitIdx[k];
        if (state.induced && R.length && !(Number(R[columnOf(p, span)]) >= 1)) continue;
        keepHit.push(hitPos[k * 3], hitPos[k * 3 + 1], hitPos[k * 3 + 2]);
        keepCol.push(hitCol[k * 3], hitCol[k * 3 + 1], hitCol[k * 3 + 2]);
        keepIdx.push(keepIdx.length);
      }
      var keepMiss = [], keepMC = [], keepMIdx = [];
      for (var m = 0; m < missIdx.length; m++) {
        var pm = cc.missIdx[m];
        if (state.induced && R.length && !(Number(R[columnOf(pm, span)]) >= 1)) continue;
        keepMiss.push(missPos[m * 3], missPos[m * 3 + 1], missPos[m * 3 + 2]);
        keepMC.push(mc[0], mc[1], mc[2]);
        keepMIdx.push(keepMIdx.length);
      }
      B_HIT = uploadBuf({ pos: keepHit, col: keepCol, size: keepHit.map(function () { return 0.020; }),
                          idx: keepIdx }, L_DISC, B_HIT);
      B_MISS = uploadBuf({ pos: keepMiss, col: keepMC,
                           size: keepMiss.map(function () { return 0.024; }),
                           idx: keepMIdx }, L_RING, B_MISS);
      return cc;
    }
    function buildFit() {
      // ① 逐列二次拟合曲线（line）
      var pos = [], col = [], idx = [];
      var lineC = needColor(colors, "fit_line");
      if (state.fitcols) {
        var curves = fitCurves(d, state.missile, "quad");
        var Rc = (((d.clouds || {})[state.missile] || {}).R_ref) || [];
        for (var ci = 0; ci < curves.length; ci++) {
          // 筛选开时曲线也一起过滤：只留点云、留着一堆被排除列的曲线会自相矛盾
          if (state.induced && Rc.length && !(Number(Rc[curves[ci].column]) >= 1)) continue;
          var pts = curves[ci].pts, base = pos.length / 3;
          for (var k = 0; k < pts.length; k++) {
            pos.push(pts[k][0], pts[k][1], pts[k][2]);
            col.push(lineC[0], lineC[1], lineC[2]);
          }
          for (var s = 0; s + 1 < pts.length; s++) idx.push(base + s, base + s + 1);
        }
      }
      B_FCURVE = uploadBuf({ pos: pos, col: col, size: pos.map(function () { return 1; }),
                             idx: idx }, L_SOLID, B_FCURVE);
      // ② 全局拟合平面的等值面（triangle，半透明）
      var ppos = [], pcol = [], pidx = [];
      if (state.fitplane) {
        var cloud = (d.clouds || {})[state.missile] || {};
        var fin = (cloud.t || []).filter(function (v) { return v !== null && v !== undefined; });
        if (fin.length) {
          var lo = Math.min.apply(null, fin), hi = Math.max.apply(null, fin);
          var levels = [lo + 0.25 * (hi - lo), lo + 0.5 * (hi - lo), lo + 0.75 * (hi - lo)];
          var pq = planeQuads(d, state.missile, levels);
          var pc = needColor(colors, "plane");
          for (var q = 0; q + 2 < pq.tris.length + 1; q += 3) {
            ppos.push(pq.tris[q][0], pq.tris[q][1], pq.tris[q][2],
                      pq.tris[q + 1][0], pq.tris[q + 1][1], pq.tris[q + 1][2],
                      pq.tris[q + 2][0], pq.tris[q + 2][1], pq.tris[q + 2][2]);
            pcol.push(pc[0], pc[1], pc[2], pc[0], pc[1], pc[2], pc[0], pc[1], pc[2]);
            pidx.push(pidx.length, pidx.length + 1, pidx.length + 2);
          }
        }
      }
      B_PLANE = uploadBuf({ pos: ppos, col: pcol, size: ppos.map(function () { return 1; }),
                            idx: pidx }, L_SOLID, B_PLANE);
    }

    function fit(aspect) {
      var fovy = 0.9;
      var need = radius / Math.tan(fovy / 2);
      cam.dist = Math.max(need, need / Math.max(aspect, 0.2)) * 0.80;
    }
    fit(gl.drawingBufferWidth / Math.max(gl.drawingBufferHeight, 1));

    function bind(buf, prog) {
      var L = buf.layout;
      gl.useProgram(prog);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf.vbo);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buf.ibo);
      gl.enableVertexAttribArray(L.pos);
      gl.vertexAttribPointer(L.pos, 3, gl.FLOAT, false, 28, 0);
      gl.enableVertexAttribArray(L.col);
      gl.vertexAttribPointer(L.col, 3, gl.FLOAT, false, 28, 12);
      gl.enableVertexAttribArray(L.size);
      gl.vertexAttribPointer(L.size, 1, gl.FLOAT, false, 28, 24);
      gl.uniformMatrix4fv(L.mvp, false, buf.mvp);
      gl.uniformMatrix4fv(L.mv, false, buf.mv);
      gl.uniform1f(L.ptScale, gl.drawingBufferHeight * 0.5 / Math.tan(0.9 / 2));
      if (L.alpha) gl.uniform1f(L.alpha, 1.0);
    }

    function draw() {
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
      // 透明底必须清成 (0,0,0,0)：WebGL 画布默认**预乘 alpha**，清成"亮底色 + alpha 0"
      // 是非法预乘值（RGB > A），合成器会当成半透明暗色 —— 内嵌视图上就是一层灰雾。
      if (opts.transparent) gl.clearColor(0, 0, 0, 0);
      else gl.clearColor(bg[0], bg[1], bg[2], 1);
      gl.enable(gl.DEPTH_TEST);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      var aspect = gl.drawingBufferWidth / Math.max(gl.drawingBufferHeight, 1);
      var cx = center[0] + cam.pan[0], cy = center[1] + cam.pan[1], cz = center[2] + cam.pan[2];
      var V = M4.view(cam.az, cam.el, Math.max(cam.dist, radius * 0.05), cx, cy, cz);
      var near = Math.max(cam.dist * 0.01, 1e-3), far = cam.dist * 8 + radius * 4;
      var MVP = M4.mul(M4.persp(0.9, aspect, near, far), V);
      [B_BOX, B_PLANE, B_FCURVE, B_HIT, B_MISS].forEach(function (b) {
        b.mvp = MVP; b.mv = V;
      });
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      // ① 半透明平面（不写深度，避免它把后面的点挡掉）
      if (B_PLANE.count) {
        gl.depthMask(false);
        gl.useProgram(P_SOLID);
        gl.uniform1f(L_SOLID.alpha, 0.16);
        gl.bindBuffer(gl.ARRAY_BUFFER, B_PLANE.vbo);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, B_PLANE.ibo);
        gl.enableVertexAttribArray(L_SOLID.pos);
        gl.vertexAttribPointer(L_SOLID.pos, 3, gl.FLOAT, false, 28, 0);
        gl.enableVertexAttribArray(L_SOLID.col);
        gl.vertexAttribPointer(L_SOLID.col, 3, gl.FLOAT, false, 28, 12);
        gl.enableVertexAttribArray(L_SOLID.size);
        gl.vertexAttribPointer(L_SOLID.size, 1, gl.FLOAT, false, 28, 24);
        gl.uniformMatrix4fv(L_SOLID.mvp, false, B_PLANE.mvp);
        gl.uniformMatrix4fv(L_SOLID.mv, false, B_PLANE.mv);
        gl.drawElements(gl.TRIANGLES, B_PLANE.count, gl.UNSIGNED_INT, 0);
        gl.depthMask(true);
      }
      // ② 盒子 + 拟合曲线（不透明线）
      gl.useProgram(P_SOLID);
      gl.uniform1f(L_SOLID.alpha, 0.85);
      if (showAxes) { bind(B_BOX, P_SOLID); gl.drawElements(gl.LINES, B_BOX.count, gl.UNSIGNED_INT, 0); }
      if (B_FCURVE.count) {
        bind(B_FCURVE, P_SOLID);
        gl.uniform1f(L_SOLID.alpha, 0.95);
        gl.drawElements(gl.LINES, B_FCURVE.count, gl.UNSIGNED_INT, 0);
      }
      // ③ 点：命中 = 实心圆盘；脱靶 = 空心圈
      if (B_HIT.count) {
        bind(B_HIT, P_DISC);
        gl.drawElements(gl.POINTS, B_HIT.count, gl.UNSIGNED_INT, 0);
      }
      if (B_MISS.count) {
        bind(B_MISS, P_RING);
        gl.drawElements(gl.POINTS, B_MISS.count, gl.UNSIGNED_INT, 0);
      }
    }

    /* ---------------------------------------------------------------- 交互 */
    var cv = gl.canvas;
    var dragging = 0, lx = 0, ly = 0;
    cv.addEventListener("pointerdown", function (e) {
      dragging = (e.button === 2 || e.shiftKey) ? 2 : 1;
      lx = e.clientX; ly = e.clientY;
      cv.classList.add("drag");
      if (cv.setPointerCapture) cv.setPointerCapture(e.pointerId);
    });
    cv.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var dx = e.clientX - lx, dy = e.clientY - ly;
      lx = e.clientX; ly = e.clientY;
      if (dragging === 1) applyDrag(cam, dx, dy); else applyPan(cam, dx, dy);
    });
    function stop() { dragging = 0; cv.classList.remove("drag"); }
    cv.addEventListener("pointerup", stop);
    cv.addEventListener("pointercancel", stop);
    cv.addEventListener("pointerleave", stop);
    cv.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    cv.addEventListener("wheel", function (e) {
      e.preventDefault();
      cam.dist *= Math.exp(Math.sign(e.deltaY) * 0.12);
    }, { passive: false });

    return {
      draw: draw, cam: cam, fit: fit, box: box, state: state,
      setMissile: function (key) { state.missile = key; buildCloud(); buildFit(); },
      setMode: function (mode) { state.mode = mode; buildCloud(); },
      setFlags: function (o) {
        if (o.fitplane !== undefined) state.fitplane = o.fitplane ? 1 : 0;
        if (o.fitcols !== undefined) state.fitcols = o.fitcols ? 1 : 0;
        if (o.induced !== undefined) state.induced = o.induced ? 1 : 0;
        if (o.axes !== undefined) showAxes = !!o.axes;
        buildCloud(); buildFit();
      },
      cloudInfo: function () { return cloudColors(d, state.missile, state.mode); },
      get spinning() { return spinning; },
      set spinning(v) { spinning = !!v; },
      stats: function () {
        return { points: B_HIT.count + B_MISS.count, lines: B_BOX.count + B_FCURVE.count,
                 tris: B_PLANE.count, radius: radius, center: center };
      },
      tick: function (dt) { if (spinning) cam.az += dt * 0.35; },
    };
  }

  /* =================================================== 色标图例（2D canvas） */
  function drawColorbar(ctx, d, key, mode) {
    var cc = cloudColors(d, key, mode);
    var w = ctx.canvas.width, h = ctx.canvas.height;
    ctx.clearRect(0, 0, w, h);
    var x0 = 10, x1 = 34, y0 = 8, y1 = h - 22;
    var dom = cc.domain || [0, 1];
    var n = 96;
    for (var i = 0; i < n; i++) {
      var t = i / (n - 1);
      var c = rampColor(cc.cmap || (d.colors.cmap || {}).t_hit, t);
      ctx.fillStyle = rgbCss(c);
      var yy = y1 - (y1 - y0) * t;
      ctx.fillRect(x0, yy, x1 - x0, Math.ceil((y1 - y0) / n) + 1);
    }
    ctx.strokeStyle = (d.colors || {}).text;
    ctx.lineWidth = 1;
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.fillStyle = d.colors.text;
    ctx.font = "11px Consolas, monospace";
    ctx.textAlign = "left";
    var degenerate = !(dom[1] > dom[0]);
    if (degenerate) {
      // 全部脱靶那一档：t_hit 一个都没有 ⇒ 色标无从谈起。**明说**，不要印一串 0.000
      // （"看起来有刻度"比"没有刻度"更误导）。
      ctx.fillText("这一档没有可着色的命中点", x0, y1 + 15);
      return;
    }
    var steps = 4;
    for (var s = 0; s <= steps; s++) {
      var tt = s / steps;
      var val = dom[0] + (dom[1] - dom[0]) * tt;
      var yv = y1 - (y1 - y0) * tt;
      ctx.fillRect(x1, yv - 0.5, 4, 1);
      ctx.fillText(fmt(val, Math.abs(dom[1] - dom[0]) < 2 ? 3 : 1), x1 + 7, yv + 4);
    }
    ctx.fillText((cc.label || mode) + (cc.unit ? " [" + cc.unit + "]" : ""), x0, y1 + 15);
  }

  /* ================================================= β–γ 热力图（2D canvas） */
  function drawHeatmap(ctx, d, key, metric) {
    var hm = (d.heatmap && d.heatmap.values) || {};
    var vals = (hm[key] || {})[metric];
    var w = ctx.canvas.width, h = ctx.canvas.height;
    ctx.clearRect(0, 0, w, h);
    var x0 = 46, y0 = 10, x1 = w - 14, y1 = h - 30;
    var ng = d.grid.gamma.length, nb = d.grid.beta.length;
    var info = ((d.heatmap || {}).metrics || []).filter(function (m) { return m.id === metric; })[0] || {};
    var colors = d.colors || {};
    if (!vals) {
      ctx.fillStyle = colors.muted;
      ctx.font = "12px sans-serif";
      ctx.fillText("这一档没有数据", x0, (y0 + y1) / 2);
      return;
    }
    var flat = [];
    for (var j = 0; j < ng; j++) for (var k = 0; k < nb; k++) {
      var v = vals[j][k];
      if (v !== null && v !== undefined) flat.push(Number(v));
    }
    if (!flat.length) {
      // 全部脱靶 ⇒ 拟合无从谈起。这里必须**显式拦**：`Math.min.apply(null, [])` 是 `Infinity`，
      // 面板会印出 "Infinity ~ Infinity" 并涂成一片纯色（看起来像"热度爆表"，其实是没数据）。
      ctx.fillStyle = colors.muted;
      ctx.font = "12px sans-serif";
      ctx.fillText("这一档没有可画的格子（全部脱靶，拟合无意义）", x0, (y0 + y1) / 2);
      return;
    }
    var lo = Math.min.apply(null, flat), hi = Math.max.apply(null, flat);
    var cmap = (colors.cmap || {})[metric === "curv" ? "curv" : "resid"];
    var cw = (x1 - x0) / nb, ch = (y1 - y0) / ng;
    for (var jj = 0; jj < ng; jj++) for (var kk = 0; kk < nb; kk++) {
      var vv = vals[jj][kk];
      var t = (vv === null || vv === undefined) ? 0 : (vv - lo) / ((hi - lo) || 1);
      ctx.fillStyle = rgbCss(rampColor(cmap, t));
      // 行 = γ（下小上大），列 = β（左小右大）
      ctx.fillRect(x0 + kk * cw, y1 - (jj + 1) * ch, cw, ch);
    }
    ctx.strokeStyle = colors.box;
    ctx.lineWidth = 1;
    ctx.strokeRect(x0, y0 - 0 + (y1 - (y1 - y0) - (y1 - y0)) * 0, x1 - x0, y1 - y0);
    var hot = ((d.heatmap.hot || {})[key] || {})[metric] || null;
    if (hot) {
      ctx.strokeStyle = colors.hot_ring;
      ctx.lineWidth = 2;
      ctx.strokeRect(x0 + hot.j_beta * cw + 1, y1 - (hot.i_gamma + 1) * ch + 1, cw - 2, ch - 2);
      ctx.fillStyle = colors.hot_ring;
      ctx.font = "11px sans-serif";
      ctx.fillText("热点 γ=" + fmt(d.grid.gamma[hot.i_gamma], 2) +
                   " β=" + fmt(d.grid.beta[hot.j_beta], 0), x0, h - 16);
    }
    ctx.fillStyle = colors.muted;
    ctx.font = "10px sans-serif";
    ctx.fillText("β " + fmt(d.grid.beta[0], 0) + "→" + fmt(d.grid.beta[nb - 1], 0), x0, h - 4);
    ctx.save();
    ctx.translate(12, y1);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("γ " + fmt(d.grid.gamma[0], 1) + "→" + fmt(d.grid.gamma[ng - 1], 1), 0, 0);
    ctx.restore();
    ctx.fillStyle = colors.text;
    ctx.font = "11px sans-serif";
    ctx.fillText((info.label || metric) + (info.unit && info.unit !== "—" ? " [" + info.unit + "]" : "") +
                 "   " + fmt(lo, 3) + " ~ " + fmt(hi, 3), x0, 10);
  }

  /* ============================================================== 状态持久化 */
  function loadState() {
    try {
      var raw = global.localStorage ? global.localStorage.getItem(STORE_KEY) : null;
      return raw ? (JSON.parse(raw) || {}) : {};
    } catch (e) { return {}; }
  }
  function saveState(state) {
    try {
      if (global.localStorage) global.localStorage.setItem(STORE_KEY, JSON.stringify(state));
    } catch (e) { /* 隐私模式：存不了就算了，不打断看图 */ }
  }

  /* ==================================================================== 引导 */
  function boot() {
    var params = new URLSearchParams(global.location.search);
    var target = params.get("job") || params.get("tag") || "default";
    var transparent = params.get("bg") === "transparent";
    var el = function (id) { return document.getElementById(id); };
    var err = el("err");
    function fail(text) { if (err) err.textContent = "错误：" + text; }
    var cv = el("cv");
    var gl = null;
    try { gl = cv.getContext("webgl2", { antialias: true, alpha: transparent }); } catch (e) { gl = null; }
    if (!gl) { fail("本浏览器/环境不支持 WebGL2"); return; }
    if (transparent) document.body.classList.add("transparent");
    fetch("/api/fig4/" + encodeURIComponent(target), { cache: "no-store" })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok || body.ok === false) {
            throw new Error((body.errors || ["取数据失败 HTTP " + r.status]).join("；"));
          }
          return body;
        });
      })
      .then(function (d) { start(d); })
      .catch(function (e) { fail(e && e.message ? e.message : String(e)); });

    function start(d) {
      var keys = (d.missiles || []).map(function (m) { return m.key; });
      if (!keys.length) { fail("产物里一枚弹都没有"); return; }
      var saved = loadState();
      // 优先 `?missile=`（"在新标签页打开"会把当前选择带过去），其次 localStorage，最后第一枚
      var want = params.get("missile") || saved.missile;
      var state = {
        missile: keys.indexOf(want) >= 0 ? want : keys[0],
        mode: (d.modes || []).some(function (m) { return m.id === saved.mode; }) ? saved.mode : "t_hit",
        fitplane: saved.fitplane === undefined ? 1 : saved.fitplane,
        fitcols: saved.fitcols === undefined ? 1 : saved.fitcols,
        induced: saved.induced === undefined ? 0 : saved.induced,
        heat: saved.heat || ((d.heatmap || {}).default || "curv"),
      };
      var v = viewer(gl, d, { transparent: transparent });
      var dpr = Math.min(global.devicePixelRatio || 1, 2);
      function resize() {
        var w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
        if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) { cv.width = w; cv.height = h; }
      }
      resize();
      v.fit(cv.width / Math.max(cv.height, 1));

      // ---- 控件 ----
      var selM = el("missile"), selMode = el("mode"), selHeat = el("heatmode");
      keys.forEach(function (k) {
        var o = document.createElement("option");
        o.value = k; o.textContent = k;
        selM.appendChild(o);
      });
      (d.modes || []).forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.id; o.textContent = m.label + (m.unit ? "（" + m.unit + "）" : "");
        selMode.appendChild(o);
      });
      ((d.heatmap || {}).metrics || []).forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.id; o.textContent = m.label;
        selHeat.appendChild(o);
      });
      selM.value = state.missile; selMode.value = state.mode; selHeat.value = state.heat;
      var cbPlane = el("fitplane"), cbCurve = el("fitcols"), cbInduced = el("induced");

      function persist() {
        saveState({ missile: state.missile, mode: state.mode, fitplane: state.fitplane,
                    fitcols: state.fitcols, induced: state.induced, heat: state.heat });
      }
      function refresh() {
        var cc = v.cloudInfo();
        drawColorbar(el("cbar").getContext("2d"), d, state.missile, state.mode);
        drawHeatmap(el("hm").getContext("2d"), d, state.missile, state.heat);
        legend(el("legend"), d, state, cc);
        hud(d, state, v, cc);
        persist();
      }
      selM.addEventListener("change", function () {
        state.missile = selM.value; v.setMissile(state.missile); refresh();
      });
      selMode.addEventListener("change", function () {
        state.mode = selMode.value; v.setMode(state.mode); refresh();
      });
      selHeat.addEventListener("change", function () {
        state.heat = selHeat.value; refresh();
      });
      cbPlane.addEventListener("change", function () {
        state.fitplane = cbPlane.checked ? 1 : 0;
        v.setFlags({ fitplane: cbPlane.checked }); refresh();
      });
      cbCurve.addEventListener("change", function () {
        state.fitcols = cbCurve.checked ? 1 : 0;
        v.setFlags({ fitcols: cbCurve.checked }); refresh();
      });
      cbInduced.addEventListener("change", function () {
        state.induced = cbInduced.checked ? 1 : 0;
        v.setFlags({ induced: cbInduced.checked }); refresh();
      });
      cbPlane.checked = !!state.fitplane;
      cbCurve.checked = !!state.fitcols;
      cbInduced.checked = !!state.induced;

      el("btnReset").onclick = function () {
        v.cam.az = AZ0; v.cam.el = EL0; v.cam.pan = [0, 0, 0];
        v.fit(cv.width / Math.max(cv.height, 1));
        v.spinning = false;
        el("btnSpin").classList.remove("on");
      };
      el("btnSpin").onclick = function (e) {
        v.spinning = !v.spinning;
        e.target.classList.toggle("on", v.spinning);
      };
      var a = el("btnOpen");
      // 「在新标签页打开」：同一个 tag，去掉 `bg`（独立页用亮底、带完整面板）
      if (a) {
        a.href = "/fig4?tag=" + encodeURIComponent(d.tag || target) +
          (state.missile ? "&missile=" + encodeURIComponent(state.missile) : "");
      }

      v.state.missile = state.missile; v.state.mode = state.mode;
      v.setFlags({ fitplane: !!state.fitplane, fitcols: !!state.fitcols,
                   induced: !!state.induced });
      refresh();

      // ---- 帧循环 + 每帧把刻度数字贴到投影位置 ----
      var last = (global.performance || Date).now();
      function frame(now) {
        var dt = Math.min((now - last) / 1000, 0.1);
        last = now;
        resize();
        v.tick(dt);
        v.draw();
        placeTicks(d, v, el("labels"));
        global.requestAnimationFrame(frame);
      }
      global.requestAnimationFrame(frame);
    }
  }

  function placeTicks(d, v, box) {
    if (!box) return;
    var s = v.stats();
    var cv = document.getElementById("cv");
    var W = cv ? cv.clientWidth : 800, H = cv ? cv.clientHeight : 600;
    var ticks = v.box.ticks;
    while (box.childNodes.length < ticks.length) {
      box.appendChild(document.createElement("span"));
    }
    while (box.childNodes.length > ticks.length) box.removeChild(box.lastChild);
    // 三根轴的刻度数字**往各自外侧挪一点**，否则相机转到某个角度时三组数字会叠在一起
    var dx = { beta: 0, gamma: 10, dv: -10 };
    var dy = { beta: 10, gamma: 0, dv: 0 };
    for (var i = 0; i < ticks.length; i++) {
      var t = ticks[i];
      var p = projectToScreen(t.world, v.cam, s.center, s.radius, W, H, 0.9);
      var node = box.childNodes[i];
      if (!p) { node.style.display = "none"; continue; }
      node.style.display = "";
      node.style.left = (p.x + (dx[t.axis] || 0)).toFixed(1) + "px";
      node.style.top = (p.y + (dy[t.axis] || 0)).toFixed(1) + "px";
      node.textContent = (t.axis === "gamma" ? t.value.toFixed(1) : t.value.toFixed(0));
      node.style.color = t.color || d.colors.text;
    }
  }

  function hud(d, state, v, cc) {
    var m = (d.missiles || []).filter(function (x) { return x.key === state.missile; })[0] || {};
    var s = v.stats();
    var el = function (id) { return document.getElementById(id); };
    if (el("title")) el("title").textContent = "图4 三维散点 · " + state.missile +
      "（" + (cc.label || state.mode) + "）";
    if (el("sub")) {
      // 轴名与单位**从 `d.axes` 取**（源头是 `figures.FIG4_AXIS_LABELS`），不在这里手写一段
      // 会跟产物漂移的文案；每根轴配一块它的轴色小方块。
      var ax = (d.axes || []).map(function (a) {
        var lo = a.limits[0], hi = a.limits[1];
        var dig = Math.abs(hi - lo) < 100 ? 1 : 0;
        return '<span class="ax"><i style="background:' + a.color + '"></i>' +
          a.label + "　" + fmt(lo, dig) + "~" + fmt(hi, dig) + "</span>";
      }).join("");
      el("sub").innerHTML = ax + "<br>" +
        (d.legend.hit || "") + " / " + (d.legend.miss || "") +
        " · 命中 " + m.n_hit + "/" + m.n_cases +
        " · 标称 β " + fmt(m.beta, 0) + " γ " + fmt(m.gamma, 2) + " ΔV " + fmt(m.dv, 1) +
        " · n* " + fmt(m.n_star_g, 2) + " G（R=" + fmt(m.R_ref, 2) + " @ n=" + fmt(d.n_ref, 0) + "G）";
    }
    if (el("stat")) {
      el("stat").textContent = "点 " + s.points + " · 线 " + s.lines + " · 三角形 " + s.tris +
        " · 网格 " + d.grid.shape.join("×") + "×" + (d.missiles || []).length + " 弹 = " +
        (d.grid.n_cases * (d.missiles || []).length) + " 工况 · 手写 WebGL2 · 无第三方 JS";
    }
  }

  function legend(box, d, state, cc) {
    if (!box) return;
    var C = d.colors || {}, L = d.legend || {};
    var html = "";
    html += '<span><i class="sw" style="background:' + C.hit + '"></i>' + (L.hit || "命中") + "</span>";
    html += '<span><i class="sw ring" style="border-color:' + C.miss + '"></i>' +
      (L.miss || "脱靶") + "</span>";
    html += "<span>颜色 = " + (cc.label || state.mode) +
      (cc.unit ? " [" + cc.unit + "]" : "") +
      (cc.domain ? "（共享范围 " + fmt(cc.domain[0], 2) + "~" + fmt(cc.domain[1], 2) + "）" : "") +
      "</span>";
    if (state.fitplane) html += '<span><i class="sw" style="background:' + C.plane + ';opacity:.35"></i>' +
      (L.fitplane || "") + "</span>";
    if (state.fitcols) html += '<span><i class="sw" style="background:' + C.fit_line + '"></i>' +
      (L.fitcols || "") + "</span>";
    html += '<span><i class="sw" style="background:' + C.hot_ring + '"></i>' +
      (L.induced || "诱导阻力主导") + "（筛选开时只看这些列）</span>";
    html += '<span class="note">' + (cc.note || "") + "</span>";
    box.innerHTML = html;
  }

  var API = { M4: M4, norm: norm, clamp: clamp, hex2rgb: hex2rgb, mixColor: mixColor,
              rampColor: rampColor, rgbCss: rgbCss, fmt: fmt,
              nodeOf: nodeOf, columnOf: columnOf, axisNorm: axisNorm, pointPos: pointPos,
              colorDomain: colorDomain, cloudColors: cloudColors, fitCurves: fitCurves,
              planeQuads: planeQuads, buildBox: buildBox,
              applyDrag: applyDrag, applyPan: applyPan, projectToScreen: projectToScreen,
              viewer: viewer, drawColorbar: drawColorbar, drawHeatmap: drawHeatmap,
              loadState: loadState, saveState: saveState, boot: boot,
              STORE_KEY: STORE_KEY, AZ_PER_PX: AZ_PER_PX, EL_PER_PX: EL_PER_PX, AZ0: AZ0, EL0: EL0 };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  global.FIG4 = API;
  if (typeof document !== "undefined" && document.getElementById) boot();
})(typeof window !== "undefined" ? window : globalThis);

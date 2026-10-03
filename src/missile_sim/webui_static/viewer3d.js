"use strict";
/* 图4 三维轨迹查看器 —— **手写 WebGL2**，零第三方 JS/CSS/字体（离线免安装是底线）。
 *
 * 出处：`spikes/fig3d/fig3d_viewer.html`（分支 `3d-viz` @ d05ad72）。产品化时改了四处：
 *   1. 数据不再靠 `?src=` 读静态 JSON，而是取 `GET /api/viewer3d/<job_id>?points=N`（服务端不解算）；
 *   2. 导弹轨迹按 `split_index`（导引头开机 t_beam）画成**两段**（开机前淡、开机后实，同一色相派生）；
 *   3. 目标轨迹按 `segments` 的**阶段色键**逐段画（与静态图 `plot_traj_segments` 同义）；
 *   4. 数据配色一律由响应里的 `colors` 给（源头是 `figures.TRAJ_COLORS` …），本文件只有亮色 chrome 的字面量。
 *
 * ⚠ 拖动方向 = **跟手**（"抓住物体转"），不是镜像。判据可复现：拖 Δx = +200 px ⇒
 *   可识别特征在**屏幕坐标**里也向 +x 走（`?dragtest=200` 会把自检结果写进页面）。
 *   ⚠ 要换成镜像惯例：**只**把 `applyDrag` 里方位角那一行的 `+` 改成 `-`；
 *   全文件 `cam.az += …` 恰好 2 处（另一处是自动旋转的 `tick`），`cam.az -= …` 一处都没有。
 */
(function (global) {
  /* ==================================================================== 数学 */
  // 4x4 列主序矩阵（WebGL 口径）。只写这个查看器用得到的四则。
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
    // 相机在 (az, el, dist) 的球坐标上，看向 center（y 是高度轴）
    view: function (az, el, dist, cx, cy, cz) {
      var ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
      var dir = [ce * ca, se, ce * sa];              // center -> 相机
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
  // 线性查找（时间轴单调、点数 ≤ 4000，不值得为它写二分以外的东西；下面两个都是二分）
  function idxLeft(ts, t) {                     // 最后一个 ts[i] <= t
    var lo = 0, hi = ts.length - 1, out = 0;
    while (lo <= hi) {
      var m = (lo + hi) >> 1;
      if (ts[m] <= t) { out = m; lo = m + 1; } else { hi = m - 1; }
    }
    return out;
  }
  function idxRight(ts, t) {                    // 第一个 ts[i] >= t
    var lo = 0, hi = ts.length - 1, out = Math.max(ts.length - 1, 0);
    while (lo <= hi) {
      var m = (lo + hi) >> 1;
      if (ts[m] >= t) { out = m; hi = m - 1; } else { lo = m + 1; }
    }
    return out;
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
    "  gl_PointSize = clamp(a_size * u_ptScale / max(-mv.z, 1.0), 1.0, 32.0);",
    "}"].join("\n");
  var FS = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; out vec4 outColor;",
    "void main() { outColor = vec4(v_col, 1.0); }"].join("\n");
  var FS_PT = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; out vec4 outColor;",
    "void main() {",
    "  vec2 d = gl_PointCoord - vec2(0.5);",
    "  if (dot(d, d) > 0.25) discard;",
    "  outColor = vec4(v_col, 1.0);",
    "}"].join("\n");

  /* ============================================================ 相机交互规则 */
  // 拖动方向 = 跟手（"抓住物体转"）。水平：Δx > 0 ⇒ az 增加 ⇒ 物体向右转；
  // 垂直：Δy > 0 ⇒ el 增加 ⇒ 上缘向观察者倾倒（与 three.js OrbitControls 同惯例）。
  var AZ_PER_PX = 0.008;
  var EL_PER_PX = 0.008;
  var EL_LIMIT = 1.45;                           // 别让相机翻过极点
  function applyDrag(cam, dx, dy) {
    cam.az += dx * AZ_PER_PX;                    // ← 镜像惯例就把这里改成 `-=`
    cam.el = clamp(cam.el + dy * EL_PER_PX, -EL_LIMIT, EL_LIMIT);
  }
  function applyPan(cam, dx, dy) {
    var k = cam.dist * 0.0016;
    var ca = Math.cos(cam.az), sa = Math.sin(cam.az);
    cam.pan[0] -= (-sa * dx) * k;
    cam.pan[2] -= (ca * dx) * k;
    cam.pan[1] += dy * k;
  }
  // 世界点 → 屏幕像素（左上原点，y 向下）。与 `draw()` 同一套 near/far 口径，
  // 所以"拖动方向自检"量的就是屏幕上真实发生的事，不是另算一套公式。
  function projectToScreen(P, cam, center, radius, W, H, fovy) {
    fovy = fovy || 0.9;
    var dist = Math.max(cam.dist, radius * 0.05);
    var near = Math.max(dist * 0.01, 1e-3), far = dist * 8 + radius * 4;
    var V = M4.view(cam.az, cam.el, dist,
      center[0] + cam.pan[0], center[1] + cam.pan[1], center[2] + cam.pan[2]);
    var M = M4.mul(M4.persp(fovy, W / Math.max(H, 1), near, far), V);
    var x = P[0], y = P[1], z = P[2];
    var cw = M[3] * x + M[7] * y + M[11] * z + M[15];
    if (!(cw > 0)) return null;                  // 落在相机后面
    var cx = M[0] * x + M[4] * y + M[8] * z + M[12];
    var cy = M[1] * x + M[5] * y + M[9] * z + M[13];
    return { x: (cx / cw * 0.5 + 0.5) * W, y: (0.5 - cy / cw * 0.5) * H, w: cw };
  }
  // "跟手"自检：把**真实拖动代码**（`applyDrag`）跑两遍，比同一个世界点在屏幕上的位移。
  // 见证点必须落在"物体正对观察者的那一片表面"上（环绕相机绕 center 转，离轴远的世界点
  // 位移方向可能反向）—— 所以主判据是"视轴上离观察者最近的那点" + "弹道里最靠视野中心的点"。
  function dragFollowCheck(d, cam, center, radius, W, H, smallPx, largePx) {
    var base = { az: cam.az, el: cam.el, dist: cam.dist, pan: cam.pan.slice() };
    var dirv = [Math.cos(cam.el) * Math.cos(cam.az), Math.sin(cam.el),
                Math.cos(cam.el) * Math.sin(cam.az)];
    var nearSurf = center.map(function (v, i) { return v + dirv[i] * 0.2 * radius; });
    var P = (d.missile && d.missile.p) || [];
    if (!P.length) return [];
    var apex = P.reduce(function (a, b) { return b[1] > a[1] ? b : a; }, P[0]);
    var nearest = P[0], bestD = Infinity;
    for (var i = 0; i < P.length; i++) {
      var s = projectToScreen(P[i], base, center, radius, W, H);
      if (!s) continue;
      var dd = Math.hypot(s.x - W / 2, s.y - H / 2);
      if (dd < bestD) { bestD = dd; nearest = P[i]; }
    }
    var witnesses = [
      { name: "物体近侧表面(视轴)", P: nearSurf, primary: true },
      { name: "弹道最近视野中心点", P: nearest, primary: true },
      { name: "发射点", P: P[0], primary: false },
      { name: "结束点", P: P[P.length - 1], primary: false },
      { name: "弹道最高点", P: apex, primary: false }];
    var rows = [];
    for (var w = 0; w < witnesses.length; w++) {
      var wit = witnesses[w];
      var s0 = projectToScreen(wit.P, base, center, radius, W, H);
      if (!s0) continue;
      var row = { name: wit.name, primary: wit.primary, s0: s0,
                  dist_center_px: Math.hypot(s0.x - W / 2, s0.y - H / 2) };
      var probes = [["x_plus", smallPx, 0], ["x_minus", -smallPx, 0],
                    ["y_plus", 0, smallPx], ["y_minus", 0, -smallPx]];
      for (var p = 0; p < probes.length; p++) {
        var c = { az: cam.az, el: cam.el, dist: cam.dist, pan: cam.pan.slice() };
        applyDrag(c, probes[p][1], probes[p][2]);
        var s1 = projectToScreen(wit.P, c, center, radius, W, H);
        row["small_" + probes[p][0]] = s1
          ? (probes[p][1] ? s1.x - s0.x : s1.y - s0.y) : null;
      }
      var bigs = [["x_plus", largePx, 0], ["x_minus", -largePx, 0],
                  ["y_plus", 0, largePx], ["y_minus", 0, -largePx]];
      for (var b2 = 0; b2 < bigs.length; b2++) {
        var c2 = { az: cam.az, el: cam.el, dist: cam.dist, pan: cam.pan.slice() };
        applyDrag(c2, bigs[b2][1], bigs[b2][2]);
        var s2 = projectToScreen(wit.P, c2, center, radius, W, H);
        row["large_" + bigs[b2][0]] = s2
          ? (bigs[b2][1] ? s2.x - s0.x : s2.y - s0.y) : null;
      }
      row.follow_x = row.small_x_plus > 0 && row.small_x_minus < 0;
      row.follow_y = row.small_y_plus > 0 && row.small_y_minus < 0;
      rows.push(row);
    }
    return rows;
  }
  // 人能读的文本（Node 端打印、浏览器端塞进 #dragtest，两边逐字一致）。
  function formatDragCheck(rows, smallPx, largePx) {
    var L = ["DRAG small=" + smallPx + "px large=" + largePx +
             "px  (dx/dy = 屏幕位移，canvas y 向下为正)",
             "  判据：小拖拽时 dx 增/减号要跟 Δx 一致、dy 增/减号要跟 Δy 一致（= 跟手）",
             "  特征                 到视野中心  |  dx@+20  dx@-20  |  dy@+20  dy@-20  | dx@+200 | 跟手"];
    var prim = 0, px = 0, py = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var f = function (v) { return v == null ? "n/a" : (v > 0 ? "+" : "") + v.toFixed(1); };
      L.push("  " + r.name.padEnd(18) + " " + r.dist_center_px.toFixed(0).padStart(7) + "px  | "
        + f(r.small_x_plus).padStart(7) + " " + f(r.small_x_minus).padStart(7) + "  | "
        + f(r.small_y_plus).padStart(7) + " " + f(r.small_y_minus).padStart(7) + "  | "
        + f(r.large_x_plus).padStart(7) + " | " + (r.follow_x && r.follow_y ? "OK" : "NO")
        + (r.primary ? "" : "  (参考，不作判据)"));
      if (r.primary) { prim++; if (r.follow_x) px++; if (r.follow_y) py++; }
    }
    var ok = prim > 0 && px === prim && py === prim;
    L.push("DRAG primary_witnesses=" + prim + " follow_x_ok=" + px + "/" + prim +
           " follow_y_ok=" + py + "/" + prim + " ok=" + (ok ? 1 : 0));
    return L.join("\n");
  }

  /* ==================================================================== 颜色 */
  function hex2rgb(text) {
    var s = String(text).replace("#", "");
    return [parseInt(s.substr(0, 2), 16) / 255,
            parseInt(s.substr(2, 2), 16) / 255,
            parseInt(s.substr(4, 2), 16) / 255];
  }
  // 与 `traj3d.mix_hex()` 同一个意思（把 a 向 b 混 k）—— 地面投影用"淡一档的轨迹色"
  function mixHex(a, b, k) {
    var ca = hex2rgb(a), cb = hex2rgb(b), f = clamp(k, 0, 1), out = "#";
    for (var i = 0; i < 3; i++) {
      var v = Math.round(255 * (ca[i] + (cb[i] - ca[i]) * f));
      out += ("0" + v.toString(16)).slice(-2);
    }
    return out;
  }
  // chrome 只有这几个字面量，全是**亮色**（数据配色一律从响应里的 colors 拿）
  var CHROME = {
    bg: "#f7f8f9", grid: "#c9d1d9", faint: "#f7f8f9",
    axisX: "#cc3322", axisY: "#227855", axisZ: "#2661d9"};
  var BG_RGB = [0.969, 0.973, 0.976];             // == hex2rgb(CHROME.bg)，每帧要用就不重算了

  /* ============================================================== 顶点装配 */
  // 顶点用**并行数组**攒（pos / col / sizes），上传时再交错成 7 float 一个顶点。
  // 轨迹线：逐顶点颜色 + 索引（LINES 成对给，段与段之间不连）。
  function pushLine(buf, idx, pts, cols) {
    if (!pts || pts.length < 2) return;
    var base = buf.pos.length / 3;
    var perVertex = Array.isArray(cols) && Array.isArray(cols[0]) && cols.length === pts.length;
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i];
      buf.pos.push(p[0], p[1], p[2]);
      var c = perVertex ? cols[i] : cols;
      buf.col.push(c[0], c[1], c[2]);
      buf.sizes.push(1.0);
    }
    for (var j = 0; j + 1 < pts.length; j++) idx.push(base + j, base + j + 1);
  }
  function pushPoints(buf, idx, pts, col, size) {
    if (!pts || !pts.length) return;
    var base = buf.pos.length / 3;
    for (var i = 0; i < pts.length; i++) {
      buf.pos.push(pts[i][0], pts[i][1], pts[i][2]);
      buf.col.push(col[0], col[1], col[2]);
      buf.sizes.push(size);
    }
    for (var j = 0; j < pts.length; j++) idx.push(base + j);
  }

  // 数据 → 三份几何：轨迹线 / 节点 / 坐标轴。
  // 导弹按 `split_index` 切两段（共享切分点 ⇒ 不断线）；目标按阶段色键逐段画。
  function buildGeometry(d) {
    var C = d.colors || {};
    var line = { pos: [], col: [], sizes: [] }, pt = { pos: [], col: [], sizes: [] };
    var li = [], pi = [];
    var M = d.missile || { t: [], p: [], split_index: 0 };
    var T = d.target || { t: [], p: [] };
    var k = M.split_index || 0;
    var bg = CHROME.faint;

    if (k > 0) pushLine(line, li, M.p.slice(0, k + 1), hex2rgb(M.before_color || C.missile_before));
    if (k < M.p.length) pushLine(line, li, M.p.slice(k), hex2rgb(M.after_color || C.missile_after));

    var segs = d.segments || [];
    if (segs.length) {
      for (var s = 0; s < segs.length; s++) {
        var seg = segs[s];
        var i0 = idxLeft(T.t, seg.t0);
        var i1 = (seg.t1 == null) ? T.t.length - 1 : idxRight(T.t, seg.t1);
        if (i1 > i0) pushLine(line, li, T.p.slice(i0, i1 + 1), hex2rgb(seg.color));
      }
    } else if (T.p.length) {
      pushLine(line, li, T.p, hex2rgb(C.fallback || "#333333"));
    }

    // 地面投影（高度 0 的淡色细线）——颜色由各自的轨迹色向亮底混出来，不新增色相
    var misC = hex2rgb(M.after_color || C.missile_after || "#4d4d4d");
    var tgtC = hex2rgb((segs[0] && segs[0].color) || C.fallback || "#333333");
    function ground(pts) {
      var out = [];
      for (var i = 0; i < pts.length; i++) out.push([pts[i][0], 0, pts[i][2]]);
      return out;
    }
    var gM = ground(M.p), gT = ground(T.p);
    pushLine(line, li, gM, hex2rgb(mixHex(rgb2hex(misC), bg, 0.55)));
    pushLine(line, li, gT, hex2rgb(mixHex(rgb2hex(tgtC), bg, 0.55)));

    // 地面网格 + 坐标轴：以数据的水平中心为中心，边长按跨度自适应
    var all = M.p.concat(T.p);
    var mnx = Infinity, mxx = -Infinity, mny = Infinity, mxy = -Infinity,
        mnz = Infinity, mxz = -Infinity, cx = 0, cz = 0;
    for (var a = 0; a < all.length; a++) {
      var q = all[a];
      cx += q[0]; cz += q[2];
      mnx = Math.min(mnx, q[0]); mxx = Math.max(mxx, q[0]);
      mnz = Math.min(mnz, q[2]); mxz = Math.max(mxz, q[2]);
      mny = Math.min(mny, q[1]); mxy = Math.max(mxy, q[1]);
    }
    if (!all.length) { mnx = mxx = mnz = mxz = 0; mny = mxy = 0; }
    cx /= Math.max(all.length, 1); cz /= Math.max(all.length, 1);
    var span = Math.max(mxx - mnx, mxz - mnz, 1);
    var n = 10, half = span * 0.6;
    var gridC = hex2rgb(CHROME.grid);
    for (var g = 0; g <= n; g++) {
      var u = -half + (2 * half * g) / n;
      pushLine(line, li, [[cx + u, 0, cz - half], [cx + u, 0, cz + half]], gridC);
      pushLine(line, li, [[cx - half, 0, cz + u], [cx + half, 0, cz + u]], gridC);
    }
    var axis = { pos: [], col: [], sizes: [] }, axi = [];
    var ax = span * 0.22, yax = Math.max((mxy - mny) * 0.6, ax * 0.6);
    var aBase = [cx, 0, cz];
    var axisDefs = [[[ax, 0, 0], hex2rgb(CHROME.axisX)], [[0, yax, 0], hex2rgb(CHROME.axisY)],
                    [[0, 0, ax], hex2rgb(CHROME.axisZ)]];
    for (var ad = 0; ad < axisDefs.length; ad++) {
      var e = axisDefs[ad][0];
      pushLine(axis, axi, [aBase, [aBase[0] + e[0], aBase[1] + e[1], aBase[2] + e[2]]],
               axisDefs[ad][1]);
    }

    // 节点：发射点 / 结束点（命中或脱靶）/ 导引头开机（落在**导弹**轨迹上）/ 其余落在目标轨迹上
    var markC = hex2rgb(C.mark || "#333333");
    var hitC = hex2rgb(C.hit || "#d62728"), missC = hex2rgb(C.miss || "#8c564b");
    var guideC = hex2rgb(C.guide || "#2e7d32");
    pushPoints(pt, pi, [d.launch || [0, 0, 0]], markC, 650);
    if (M.p.length) pushPoints(pt, pi, [M.p[M.p.length - 1]], d.hit ? hitC : missC, 900);
    for (var mi = 0; mi < (d.marks || []).length; mi++) {
      var m = d.marks[mi];
      if (m.name === "launch" || m.name === "end") continue;
      if (m.name === "seeker_on") pushPoints(pt, pi, [m.missile], guideC, 700);
      else pushPoints(pt, pi, [m.target], markC, 420);
    }
    return { line: line, pt: pt, axis: axis, li: li, pi: pi, axi: axi,
             bounds: { mnx: mnx, mxx: mxx, mny: mny, mxy: mxy, mnz: mnz, mxz: mxz, cx: cx, cz: cz,
                       span: span } };
  }
  function rgb2hex(c) {
    var out = "#";
    for (var i = 0; i < 3; i++) {
      var v = Math.round(clamp(c[i], 0, 1) * 255);
      out += ("0" + v.toString(16)).slice(-2);
    }
    return out;
  }

  /* ================================================================== 渲染器 */
  function viewer(gl, d, opts) {
    opts = opts || {};
    var G = buildGeometry(d);
    function prog(vs, fs) {
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
    var P_LINE = prog(VS, FS), P_PT = prog(VS, FS_PT);
    function loc(p) {
      return { pos: gl.getAttribLocation(p, "a_pos"), col: gl.getAttribLocation(p, "a_col"),
               size: gl.getAttribLocation(p, "a_size"),
               mvp: gl.getUniformLocation(p, "u_mvp"), mv: gl.getUniformLocation(p, "u_mv"),
               ptScale: gl.getUniformLocation(p, "u_ptScale") };
    }
    var L_LINE = loc(P_LINE), L_PT = loc(P_PT);
    function upload(G_, layout) {
      var n = G_.pos.length / 3;
      var DATA = new Float32Array(n * 7);
      for (var i = 0; i < n; i++) {
        DATA[i * 7 + 0] = G_.pos[i * 3]; DATA[i * 7 + 1] = G_.pos[i * 3 + 1];
        DATA[i * 7 + 2] = G_.pos[i * 3 + 2];
        DATA[i * 7 + 3] = G_.col[i * 3]; DATA[i * 7 + 4] = G_.col[i * 3 + 1];
        DATA[i * 7 + 5] = G_.col[i * 3 + 2];
        DATA[i * 7 + 6] = G_.sizes[i];
      }
      var vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, DATA, gl.STATIC_DRAW);
      var ibo = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint32Array(G_.idx), gl.STATIC_DRAW);
      return { vbo: vbo, ibo: ibo, count: G_.idx.length, layout: layout };
    }
    var B_LINE = upload({ pos: G.line.pos, col: G.line.col, sizes: G.line.sizes, idx: G.li }, L_LINE);
    var B_PT = upload({ pos: G.pt.pos, col: G.pt.col, sizes: G.pt.sizes, idx: G.pi }, L_PT);
    var B_AXIS = upload({ pos: G.axis.pos, col: G.axis.col, sizes: G.axis.sizes, idx: G.axi },
                        L_LINE);

    var cam = { az: -1.05, el: 0.36, dist: 1.0, pan: [0, 0, 0] };
    var b = G.bounds;
    var radius = 0.5 * Math.hypot(b.mxx - b.mnx, Math.max(b.mxy - b.mny, 1), b.mxz - b.mnz);
    var center = [(b.mnx + b.mxx) / 2, (b.mny + b.mxy) / 2, (b.mnz + b.mxz) / 2];
    var spinning = false, showAxes = true;

    function fit(aspect) {
      var fovy = 0.9;
      var need = radius / Math.tan(fovy / 2);
      cam.dist = Math.max(need, need / Math.max(aspect, 0.2)) * 0.72;
    }
    fit(gl.drawingBufferWidth / Math.max(gl.drawingBufferHeight, 1));

    function bind(buf) {
      var L = buf.layout, st = 7 * 4, MVP = buf._mvp, V = buf._mv;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf.vbo);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buf.ibo);
      gl.enableVertexAttribArray(L.pos);
      gl.vertexAttribPointer(L.pos, 3, gl.FLOAT, false, st, 0);
      gl.enableVertexAttribArray(L.col);
      gl.vertexAttribPointer(L.col, 3, gl.FLOAT, false, st, 12);
      gl.enableVertexAttribArray(L.size);
      gl.vertexAttribPointer(L.size, 1, gl.FLOAT, false, st, 24);
      gl.uniformMatrix4fv(L.mvp, false, MVP);
      gl.uniformMatrix4fv(L.mv, false, V);
      // 点的世界尺寸(m) → 屏幕像素：px = d_m · (H/2) / (depth · tan(fovy/2))。
      // 着色器里已经除了 depth，所以这里只给 (H/2)/tan(fovy/2)。
      // ⚠ 曾经多乘一个 radius ⇒ 每个点都被 clamp 到 32 px、糊成一排黑球（单位错了不报错，只是难看）。
      gl.uniform1f(L.ptScale, gl.drawingBufferHeight * 0.5 / Math.tan(0.9 / 2));
    }

    function draw() {
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
      // ⚠ 透明底必须清成 **(0,0,0,0)**，不能清成"亮底色 + alpha 0"。
      //   WebGL 画布默认是**预乘 alpha**：清成 (0.97,0.97,0.98, 0) 是非法预乘值（RGB > A），
      //   合成器会把它当"半透明暗色"处理 —— 实测整张图变成一层灰雾、细线断成点线
      //   （`?bg=transparent` 的内嵌视图上第一眼就能看出来）。
      if (opts.transparent) {
        gl.clearColor(0, 0, 0, 0);
      } else {
        gl.clearColor(BG_RGB[0], BG_RGB[1], BG_RGB[2], 1);
      }
      gl.enable(gl.DEPTH_TEST);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      var aspect = gl.drawingBufferWidth / Math.max(gl.drawingBufferHeight, 1);
      var cx = center[0] + cam.pan[0], cy = center[1] + cam.pan[1], cz = center[2] + cam.pan[2];
      var V = M4.view(cam.az, cam.el, Math.max(cam.dist, radius * 0.05), cx, cy, cz);
      // 近远平面按相机距离给，别写死（否则一缩放就被裁）
      var near = Math.max(cam.dist * 0.01, 1e-3), far = cam.dist * 8 + radius * 4;
      var MVP = M4.mul(M4.persp(0.9, aspect, near, far), V);
      B_LINE._mvp = B_AXIS._mvp = B_PT._mvp = MVP;
      B_LINE._mv = B_AXIS._mv = B_PT._mv = V;
      gl.useProgram(P_LINE);
      bind(B_LINE);
      gl.drawElements(gl.LINES, B_LINE.count, gl.UNSIGNED_INT, 0);
      if (showAxes && B_AXIS.count) {
        bind(B_AXIS);
        gl.drawElements(gl.LINES, B_AXIS.count, gl.UNSIGNED_INT, 0);
      }
      if (B_PT.count) {
        gl.useProgram(P_PT);
        bind(B_PT);
        gl.drawElements(gl.POINTS, B_PT.count, gl.UNSIGNED_INT, 0);
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
      // 旋转方向由 `applyDrag` 一处定义（跟手），这里不写字面量符号
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
      draw: draw, cam: cam, fit: fit, geometry: G,
      get spinning() { return spinning; },
      set spinning(v) { spinning = !!v; },
      set axes(v) { showAxes = !!v; },
      get stats() {
        return { verts: B_LINE.count + B_PT.count + B_AXIS.count, lines: B_LINE.count,
                 points: B_PT.count, radius: radius, center: center };
      },
      tick: function (dt) { if (spinning) cam.az += dt * 0.35; },
    };
  }

  /* ==================================================================== 引导 */
  function boot() {
    var params = new URLSearchParams(global.location.search);
    var job = params.get("job") || "";
    var points = params.get("points") || "";
    var transparent = params.get("bg") === "transparent";
    var el = function (id) { return document.getElementById(id); };
    var err = el("err");
    function fail(text) { if (err) err.textContent = "错误：" + text; }
    // 「在新标签页打开」：同一个 job，去掉 `bg`（独立页用亮底），保留点数
    var link = el("btnOpen");
    if (link) {
      link.href = "/viewer3d?job=" + encodeURIComponent(job) +
                  (points ? "&points=" + encodeURIComponent(points) : "");
    }
    if (!job) { fail("缺少 ?job= 参数（本页要配一个跑完的图4 任务）"); return; }
    var url = "/api/viewer3d/" + encodeURIComponent(job) +
              (points ? "?points=" + encodeURIComponent(points) : "");
    var cv = el("cv");
    var gl = null;
    try {
      gl = cv.getContext("webgl2", { antialias: true, alpha: transparent });
    } catch (e) { gl = null; }
    if (!gl) { fail("本浏览器/环境不支持 WebGL2"); return; }
    if (transparent) document.body.classList.add("transparent");

    fetch(url, { cache: "no-store" }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok || body.ok === false) {
          throw new Error((body.errors || ["取数据失败 HTTP " + r.status]).join("；"));
        }
        return body;
      });
    }).then(function (d) {
      var v = viewer(gl, d, { transparent: transparent });
      var dpr = Math.min(global.devicePixelRatio || 1, 2);
      function resize() {
        var w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
        if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) { cv.width = w; cv.height = h; }
      }
      resize();
      v.fit(cv.width / Math.max(cv.height, 1));      // 画布真实尺寸出来之后再定初始视距
      var s = v.stats;
      el("title").textContent = "图4 三维轨迹 · " + (d.missile_name || "") +
        (d.hit ? "（命中）" : "（脱靶）");
      var mid = d.missile.split_index;
      el("sub").innerHTML = "t_hit = " + fmt(d.t_hit_s, 2) + " s · 开机 t_beam = " +
        fmt(d.t_beam_s, 2) + " s · 两段 " + mid + " / " + (d.missile.p.length - mid) +
        " 点（开机前 / 开机后）<br>" +
        "左键拖拽旋转 / 滚轮缩放 / 右键或 Shift+拖拽平移";
      el("stat").textContent = "顶点 " + s.verts + " · 抽稀 " + d.points.target + " 点（原始 " +
        d.rows.target + " 行）· 手写 WebGL2 · 无第三方 JS";
      legend(el("legend"), d);
      // `?dragtest=N`：在真浏览器里跑一遍"跟手"自检并把结果写进 DOM
      var dtPx = +(params.get("dragtest") || 0);
      if (dtPx) {
        var W = cv.width || global.innerWidth || 1280;
        var H = cv.height || global.innerHeight || 800;
        var rows = dragFollowCheck(d, v.cam, s.center, s.radius, W, H, 20, dtPx);
        el("dragtest").textContent = "# 真浏览器自检 canvas=" + W + "x" + H + "\n" +
          formatDragCheck(rows, 20, dtPx);
      }
      var last = (global.performance || Date).now();
      function frame(now) {
        var dt = Math.min((now - last) / 1000, 0.1);
        last = now;
        resize();
        v.tick(dt);
        v.draw();
        global.requestAnimationFrame(frame);
      }
      el("btnReset").onclick = function () {
        v.cam.az = -1.05; v.cam.el = 0.36; v.cam.pan = [0, 0, 0];
        v.fit(cv.width / Math.max(cv.height, 1));
        v.spinning = false;
        el("btnSpin").classList.remove("on");
      };
      el("btnSpin").onclick = function (e) {
        v.spinning = !v.spinning;
        e.target.classList.toggle("on", v.spinning);
      };
      el("btnAxes").onclick = function (e) {
        v.axes = e.target.classList.toggle("on");
      };
      global.requestAnimationFrame(frame);
    }).catch(function (e) { fail(e && e.message ? e.message : String(e)); });
  }
  function fmt(v, digits) {
    if (v === null || v === undefined) return "—";
    return (typeof v === "number") ? v.toFixed(digits === undefined ? 3 : digits) : String(v);
  }
  // 图例：阶段色键（左）与节点（右）—— 颜色就在响应里，不在这里写死
  function legend(box, d) {
    if (!box) return;
    var html = "";
    var segs = d.segments || [];
    for (var i = 0; i < segs.length; i++) {
      var s = segs[i];
      html += '<span><i style="background:' + s.color + '"></i>' +
        (s.label || s.kind || s.phase || s.color_key) + "</span>";
    }
    var marks = d.marks || [];
    for (var j = 0; j < marks.length; j++) {
      if (marks[j].name === "end" || marks[j].name === "launch") continue;
      html += "<span>" + fmt(marks[j].t_s, 2) + " s " + marks[j].name + "</span>";
    }
    box.innerHTML = html;
  }

  var API = { M4: M4, norm: norm, clamp: clamp, idxLeft: idxLeft, idxRight: idxRight,
              applyDrag: applyDrag, applyPan: applyPan, projectToScreen: projectToScreen,
              dragFollowCheck: dragFollowCheck, formatDragCheck: formatDragCheck,
              hex2rgb: hex2rgb, mixHex: mixHex, rgb2hex: rgb2hex, CHROME: CHROME,
              buildGeometry: buildGeometry, viewer: viewer,
              AZ_PER_PX: AZ_PER_PX, EL_PER_PX: EL_PER_PX, EL_LIMIT: EL_LIMIT };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // Node 自检用
  global.TRAJ3D = API;
  if (typeof document !== "undefined" && document.getElementById) boot();
})(typeof window !== "undefined" ? window : globalThis);

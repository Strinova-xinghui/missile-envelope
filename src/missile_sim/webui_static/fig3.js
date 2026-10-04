"use strict";
/* 图3 交互式三维散点 —— **手写 WebGL2**，零第三方 JS/CSS/字体（离线免安装是底线）。
 *
 * 数据：`GET /api/fig3/<tag|job_id>`（服务端只读产物、**不解算**）。
 * 三根轴：**横轴 ΔV、纵轴 β、纵深 1/γ**（用户 2026-10-04 口径）。三根各自归一化到
 * [-0.5, 0.5] 的等长立方体、区间随弹池自适应（`figures.fig3_axes`，与图1/图2 同口径）。
 * ⚠ 哪个量摆在哪根**世界轴**上，前端**不写死**：一律读响应里每个轴的 `role`（x/y/z）——
 * 所以 Python 侧把轴序改回去，画面会跟着变，判据也会当场变红。
 * 颜色 = t_hit（连续色标）；色标范围**11 枚弹共享**。
 * 角部光晕 = 好角（三轴最大角）绿 / 差角（三轴最小角）红，按世界坐标三维距离衰减到白底，
 * 画在背对相机的那三块面上、最先画且不写深度 ⇒ 永远压在散点与等时面之下。
 *
 * 三条硬约束（有测试钉着）：
 *   1. 本文件**一个颜色字面量都没有** —— 全部颜色从响应里的 `colors` 取
 *      （源头是 `figures.FIG3_*`）；chrome 的底色/线色写在 `fig3.css` 里；
 *   2. 命中/脱靶**不靠颜色区分**：脱靶一律画成**空心**标记（它根本没有 t_hit 可着色）；
 *   3. 切换弹种**只换点云**：色标范围来自响应里的 `shared.ranges`，不按选中的那朵点云重算。
 */
(function (global) {
  // localStorage 键：与查看器（viewer3d）不共用 —— 两张图的控件不一样，
  // 混用一个键会让"记住上次选择"互相打补丁。测试钉着这个字面量。
  var STORE_KEY = "missile-sim.fig3";

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

  //: 每根轴的显示小数位 —— **唯一出处**（刻度与轴注记都走这里）。
  //  β/ΔV 是三位整数（`toFixed(0)`），ginv = 1/γ 是 1e-2 量级（0.0101~0.0196，`toFixed(4)`）。
  //  ⚠ 2026-10-04 把纵轴从 γ 换成 ginv 时**只改了刻度那一处**，轴注记那处漏改 ⇒ 真浏览器上
  //  写成 "0.0~0.0"（刻度是对的，所以肉眼很容易漏；同一天 `--gamma-step` 也是在冒烟才发现）。
  function axisDigits(id, value) {
    if (id === "ginv") return 4;
    if (id === "beta" || id === "dv") return 0;
    var a = Math.abs(value);                                  // 兜底：按量级给
    return a >= 100 ? 0 : (a >= 1 ? 1 : 4);
  }

  /* ============================================================ 网格 / 展平 */
  // 展平顺序：ΔV 外层 → ginv → β（与 `fig3.FLAT_ORDER` 同序）。这三条关系必须只有一个出处。
  function nodeOf(p, nBeta, nGinv) {
    var span = nBeta * nGinv;
    var rest = p % span;
    return { i_dv: Math.floor(p / span), rest: rest,
             j_ginv: Math.floor(rest / nBeta), k_beta: rest % nBeta };
  }
  function columnOf(p, span) { return p % span; }
  function axisNorm(v, lo, hi) {
    var span = (hi - lo) || 1;
    return (v - lo) / span - 0.5;
  }

  /* ------------------------------------------------- 三根轴的世界摆位（读响应） */
  // 哪个量摆在哪根世界轴上，**只有 Python 侧一处口径**（`figures.FIG3_AXIS_ORDER`）：
  // 响应里每个轴都带 `role`（x/y/z）。这里把它读出来 ⇒ 前端不写死"β 在 x"。
  // 缺 role / 缺轴就当**契约破损**当场抛：兜底成"β 在 x"会让轴序改回去也看不出来。
  function axisSlot(d, axisId) {
    var axes = (d && d.axes) || [];
    for (var i = 0; i < axes.length; i++) {
      if (axes[i].id === axisId) {
        var role = axes[i].role;
        if (role !== "x" && role !== "y" && role !== "z") {
          throw new Error("fig3 响应里轴 " + axisId + " 没有合法 role（轴摆位必须来自数据层）");
        }
        return (role === "x") ? 0 : ((role === "y") ? 1 : 2);
      }
    }
    throw new Error("fig3 响应里没有轴 " + axisId);
  }
  function axisSlots(d) {
    return { beta: axisSlot(d, "beta"), dv: axisSlot(d, "dv"), ginv: axisSlot(d, "ginv") };
  }
  // 三个归一化值 → 世界坐标（各就各位）
  function packWorld(s, beta, dv, ginv) {
    var out = [0, 0, 0];
    out[s.beta] = beta; out[s.dv] = dv; out[s.ginv] = ginv;
    return out;
  }
  // 一个格点的世界坐标（按 role 摆放；各自归一化 ⇒ 等长三轴）
  function pointPos(d, p) {
    var g = d.grid, nb = g.beta.length, ng = g.ginv.length;
    var nd = nodeOf(p, nb, ng);
    return dataPos(d, g.beta[nd.k_beta], g.ginv[nd.j_ginv], g.dv[nd.i_dv]);
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
  // **11 个标称点**（task-24：用户"命中点不用，只出各弹三参数点即可"）。
  // 坐标 = 该弹的标称 (ΔV, BC≡β, ginv)；颜色 = 该弹在当前工况下的 t_hit；
  // 命中 ⇒ 实心 + 色标值，未命中 ⇒ **空心 + 没有 t_hit**（不参与色标范围）。
  // ⚠ 名字保留 `cloudColors`：`drawColorbar` / `hud` / `showLayer` 三处调用点共用它，
  //   返回形状（hit / miss / hitIdx / missIdx / domain / unit / label / note）也保持不变。
  function cloudColors(d, key, mode) {
    var colors = d.colors || {};
    var cmap = needRamp(colors, mode || "t_hit");
    var modeInfo = (d.modes || []).filter(function (m) { return m.id === (mode || "t_hit"); })[0] || {};
    var dom = colorDomain(d, "t_hit");
    var missC = needColor(colors, "miss");
    var hit = [], miss = [], hitIdx = [], missIdx = [];
    var pts = d.points || [];
    var lo = dom ? dom[0] : 0, hi = dom ? dom[1] : 1;
    var span = (hi - lo) || 1;
    for (var p = 0; p < pts.length; p++) {
      var it = pts[p];
      var pos = dataPos(d, it.beta, it.ginv, it.dv);
      if (!it.hit || it.t_hit_s === null || it.t_hit_s === undefined) {
        missIdx.push(p);
        miss.push(pos[0], pos[1], pos[2]);
        continue;
      }
      var c = rampColor(cmap, (Number(it.t_hit_s) - lo) / span);
      hitIdx.push(p);
      hit.push(pos[0], pos[1], pos[2], c[0], c[1], c[2]);
    }
    return { hit: hit, miss: miss, hitIdx: hitIdx, missIdx: missIdx, domain: dom,
             unit: modeInfo.unit || "", label: modeInfo.label || (mode || "t_hit"),
             note: modeInfo.note || "", shared: !!dom, missColor: missC, cmap: cmap,
             points: pts };
  }

  /* ==================================================== 证据层：曲线 / 平面 */
  // 逐 (β,ginv) 列的二次拟合曲线（5 个 ΔV 节点连成的折线）—— 在三维盒子里就是"拟合曲面"的
  // 一族母线；弯不弯、弯在哪一根竖线上，一眼可见。
  /* ============================================================ 等时面网格 */
  // 数据坐标 (β, ginv, ΔV) → 视图坐标（与 `pointPos()` 同一条归一化链路，所以面与点云天然对齐）。
  function dataPos(d, beta, ginv, dv) {
    var g = d.grid;
    return packWorld(axisSlots(d),
                     axisNorm(beta, g.beta[0], g.beta[g.beta.length - 1]),
                     axisNorm(dv, g.dv[0], g.dv[g.dv.length - 1]),
                     axisNorm(ginv, g.ginv[0], g.ginv[g.ginv.length - 1]));
  }

  // 一层等时面（响应里那张网格）→ 可直接 `upload()` 的缓冲规格。
  // **纯函数**：不碰 WebGL、不读全局（Node 侧自检直接喂数据就能验）。
  // 每个三角形独立顶点 + 用面法线做一次假光照（flat shading），所以不需要新的着色器。
  function surfaceBuffers(d, spec, rgb, opts) {
    opts = opts || {};
    var V = (spec && spec.vertices) || [];
    var T = (spec && spec.triangles) || [];
    var light = opts.light || [0.45, 0.72, 0.53];
    var base = rgb || [0.6, 0.6, 0.6];
    var pos = [], col = [], size = [], idx = [];
    var k = 0;
    for (var t0 = 0; t0 + 2 < T.length; t0 += 3) {
      var ia = T[t0] * 3, ib = T[t0 + 1] * 3, ic = T[t0 + 2] * 3;
      // ⚠ 响应里的顶点是**数据坐标** `(β, ginv, ΔV)`（`bg3d.Surface` 的口径），
      //   而 `dataPos()` 吃的是 `(beta, ginv, dv)` 三个实参、吐的是视图坐标 `[β, ΔV, ginv]`。
      //   这里曾经把后两个参数写反（照 `pointPos` 的顺序抄的）—— 面上的三个轴会被整体**换位**，
      //   而画面看起来只是"面歪了一点"。判据：`-k fig3` 的 JS 数值自检（顶点必须落在 ±0.5 盒内）。
      var a = dataPos(d, V[ia], V[ia + 1], V[ia + 2]);
      var b = dataPos(d, V[ib], V[ib + 1], V[ib + 2]);
      var c = dataPos(d, V[ic], V[ic + 1], V[ic + 2]);
      var ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
      var vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
      var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      var nn = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
      var lam = Math.abs((nx * light[0] + ny * light[1] + nz * light[2]) / nn);
      var f = 0.55 + 0.45 * lam;
      [a, b, c].forEach(function (q) {
        pos.push(q[0], q[1], q[2]);
        col.push(Math.min(base[0] * f, 1), Math.min(base[1] * f, 1), Math.min(base[2] * f, 1));
        size.push(1);
      });
      idx.push(k, k + 1, k + 2);
      k += 3;
    }
    return { pos: pos, col: col, size: size, idx: idx, n_tri: T.length / 3 };
  }

  // 刻度摆在哪条棱上：**按世界轴**（x/y/z），轴名 → 世界轴由响应里的 `role` 决定。
  //   x → 前下缘 (y=-0.5, z=-0.5)   y → 左竖棱 (x=-0.5, z=-0.5)   z → 底面右缘 (x=+0.5, y=-0.5)
  // 这三条棱**永不重合**：所以三根轴的刻度不会挤在一起（用户 2026-10-04 口径）。
  var TICK_EDGE = {
    x: function (u) { return [u, -0.5, -0.5]; },
    y: function (u) { return [-0.5, u, -0.5]; },
    z: function (u) { return [0.5, -0.5, u]; },
  };

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
    var roleOf = ["x", "y", "z"];
    var slots = axisSlots(d);            // {beta, dv, ginv} → 0/1/2（缺 role 当场抛）
    ["dv", "beta", "ginv"].forEach(function (axisId) {
      var vals = g[axisId];
      addTicks(axisId, vals, vals[0], vals[vals.length - 1], TICK_EDGE[roleOf[slots[axisId]]]);
    });
    return { edges: edges, edge_colors: ec, ticks: ticks, slots: slots };
  }

  /* ==================================================== 角部光晕（四分之一球） */
  // 好角 = 三轴最大角（绿）、差角 = 三轴最小角（红）——**角与参数全来自响应**（`d.halo` / `colors.halo`）。
  // 三块面 = 背对默认相机的那三块（后壁 ×2 + 底面），每块两个三角形；颜色**在片元里按世界坐标
  // 到两个角的三维距离**算 ⇒ 等色线在面上是圆弧（不是分区涂色、也不是贴一张渐变图）。
  // **纯函数**：Node 侧自检直接喂世界坐标就能验（WebGL 那部分只是把同一个式子搬进 GLSL）。
  function haloParams(d) {
    var h = (d && d.halo) || {};
    var colors = (d || {}).colors || {};
    var c = colors.halo || {};
    function rgb(key) {
      if (!c[key]) throw new Error("fig3 响应缺少 colors.halo." + key + "（配色必须来自 figures）");
      return hex2rgb(c[key]);
    }
    var good = h.corner_good || [0.5, 0.5, 0.5];
    var bad = h.corner_bad || [-0.5, -0.5, -0.5];
    var alpha = Number((c.alpha === undefined) ? h.alpha : c.alpha);
    // 缺字段 / NaN ⇒ 兜底（正常路径永远来自响应 `colors.halo.alpha`；颜色仍必须来自响应）
    if (!(alpha >= 0)) { alpha = 0.32; }
    return { good: good, bad: bad, radius: Number(h.radius), power: Number(h.power),
             alpha: alpha,
             goodRGB: rgb("good"), badRGB: rgb("bad"),
             baseRGB: needColor(colors, "bg"),
             faces: h.faces || [], facesPerCorner: h.faces_per_corner || null,
             note: h.note || "" };
  }
  // 某个世界位置的光晕颜色（与片元着色器**同一个式子**）：返回 [r, g, b, a]，a = 0 表示看不见。
  function haloColorAt(p, params) {
    var wb = haloWeight(p, params.bad, params.radius, params.power);
    var wg = haloWeight(p, params.good, params.radius, params.power);
    var c = mixRGB(params.baseRGB, params.badRGB, wb);
    c = mixRGB(c, params.goodRGB, wg);
    return [c[0], c[1], c[2], params.alpha * Math.max(wb, wg)];
  }
  function haloWeight(p, corner, radius, power) {
    var dx = p[0] - corner[0], dy = p[1] - corner[1], dz = p[2] - corner[2];
    var t = 1 - Math.sqrt(dx * dx + dy * dy + dz * dz) / (radius || 1);
    if (t <= 0) return 0;
    return Math.pow(t, power);
  }
  function mixRGB(a, b, w) {
    return [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w, a[2] + (b[2] - a[2]) * w];
  }
  // **六个面** → 可以直接 `upload()` 的缓冲规格（每个角恰好被三块面共用 ⇒ 两团对称；
  // 顶点颜色只是占位，真色在片元里算）。
  function haloBuffers(d) {
    var params = haloParams(d);
    var pos = [], col = [], size = [], idx = [], k = 0;
    params.faces.forEach(function (f) {
      var fixed = Number(f.at);
      var free = [0, 1, 2].filter(function (i) { return i !== Number(f.slot); });
      var quad = [];
      [[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5]].forEach(function (uv) {
        var p = [0, 0, 0];
        p[Number(f.slot)] = fixed;
        p[free[0]] = uv[0]; p[free[1]] = uv[1];
        quad.push(p);
      });
      var order = [0, 1, 2, 0, 2, 3];
      order.forEach(function (q) {
        pos.push(quad[q][0], quad[q][1], quad[q][2]);
        col.push(params.baseRGB[0], params.baseRGB[1], params.baseRGB[2]);
        size.push(1);
        idx.push(k++);
      });
    });
    return { pos: pos, col: col, size: size, idx: idx, params: params };
  }

  /* ============================================================== 相机交互 */
  var AZ_PER_PX = 0.008, EL_PER_PX = 0.008, EL_LIMIT = 1.45;
  // 默认视角 = **响应里的 `view`**（源头是 `figures.FIG3_VIEW_AZ/EL`，见 `viewer()`）。
  // 这两个变量故意**不写死**：前端写一份默认角度、Python 侧再写一份，两边一漂移就没人发现。
  var AZ0 = null, EL0 = null;
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
    "out vec3 v_col; out vec3 v_world;",
    "void main() {",
    "  v_col = a_col;",
    "  v_world = a_pos;",                      // 光晕的片元着色器按「世界坐标」算距离
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
  // 角部光晕：**逐片元**按世界坐标到两个角的三维距离衰减 ⇒ 等色线在面上是圆弧（四分之一球）。
  // 颜色（红/绿/白）、两个角、半径与指数**全部来自响应**（`colors.halo` / `d.halo`）——
  // 这里一个颜色字面量都没有（判据扫这个文件）。
  var FS_HALO = ["#version 300 es", "precision mediump float;",
    "in vec3 v_world; in vec3 v_col;",
    "uniform vec3 u_bad; uniform vec3 u_good; uniform vec3 u_base;",
    "uniform vec3 u_bad_corner; uniform vec3 u_good_corner;",
    "uniform float u_radius; uniform float u_power; uniform float u_alpha;",
    "out vec4 outColor;",
    "float haloW(vec3 p, vec3 corner) {",
    "  float t = 1.0 - length(p - corner) / max(u_radius, 1e-4);",
    "  return (t <= 0.0) ? 0.0 : pow(t, u_power);",
    "}",
    "void main() {",
    "  float wb = haloW(v_world, u_bad_corner);",
    "  float wg = haloW(v_world, u_good_corner);",
    "  vec3 c = mix(u_base, u_bad, wb);",
    "  c = mix(c, u_good, wg);",
    "  outColor = vec4(c, u_alpha * max(wb, wg));",
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
    var halo = haloBuffers(d);
    var P_SOLID = compile(gl, VS, FS_SOLID);
    var P_DISC = compile(gl, VS, FS_DISC);
    var P_RING = compile(gl, VS, FS_RING);
    var P_HALO = compile(gl, VS, FS_HALO);
    function loc(p) {
      return { pos: gl.getAttribLocation(p, "a_pos"), col: gl.getAttribLocation(p, "a_col"),
               size: gl.getAttribLocation(p, "a_size"),
               mvp: gl.getUniformLocation(p, "u_mvp"), mv: gl.getUniformLocation(p, "u_mv"),
               ptScale: gl.getUniformLocation(p, "u_ptScale"),
               alpha: gl.getUniformLocation(p, "u_alpha") };
    }
    var L_SOLID = loc(P_SOLID), L_DISC = loc(P_DISC), L_RING = loc(P_RING);
    var L_HALO = { pos: gl.getAttribLocation(P_HALO, "a_pos"),
                   col: gl.getAttribLocation(P_HALO, "a_col"),
                   size: gl.getAttribLocation(P_HALO, "a_size"),
                   mvp: gl.getUniformLocation(P_HALO, "u_mvp"),
                   mv: gl.getUniformLocation(P_HALO, "u_mv"),
                   ptScale: gl.getUniformLocation(P_HALO, "u_ptScale"),
                   alpha: gl.getUniformLocation(P_HALO, "u_alpha"),
                   bad: gl.getUniformLocation(P_HALO, "u_bad"),
                   good: gl.getUniformLocation(P_HALO, "u_good"),
                   base: gl.getUniformLocation(P_HALO, "u_base"),
                   badCorner: gl.getUniformLocation(P_HALO, "u_bad_corner"),
                   goodCorner: gl.getUniformLocation(P_HALO, "u_good_corner"),
                   radius: gl.getUniformLocation(P_HALO, "u_radius"),
                   power: gl.getUniformLocation(P_HALO, "u_power") };

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
    var B_HALO = upload(halo, L_HALO);
    var B_LAYER = upload({ pos: [], col: [], size: [], idx: [] }, L_SOLID);
    var B_HIT = upload({ pos: [], col: [], size: [], idx: [] }, L_DISC);
    var B_MISS = upload({ pos: [], col: [], size: [], idx: [] }, L_RING);

    // 默认视角来自响应（`d.view` ← `figures.FIG3_VIEW_AZ/EL`）：前端不写死"从哪看"，
    // 免得 Python 侧调了默认视角而页面上纹丝不动（那会让"轴序改回去也看不出来"）。
    var V0 = d.view || {};
    if (typeof V0.az !== "number" || typeof V0.el !== "number") {
      throw new Error("fig3 响应缺少 view.az / view.el（默认视角必须来自数据层）");
    }
    AZ0 = V0.az; EL0 = V0.el;
    var cam = { az: AZ0, el: EL0, dist: 1.6, pan: [0, 0, 0] };
    var alphaLayer = (colors.layer_alpha === undefined) ? 0.55 : Number(colors.layer_alpha);
    var radius = 0.87, center = [0, 0, 0];
    var spinning = false, showAxes = true;
    var state = { missile: "", layer: null, axes: 1 };

    // 点云：切换弹种时重建（几百个点，代价可以忽略）。
    function buildCloud() {
      var cc = cloudColors(d, state.missile, "t_hit");
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
      B_HIT = uploadBuf({ pos: hitPos, col: hitCol, size: hitPos.map(function () { return 0.020; }),
                          idx: hitIdx }, L_DISC, B_HIT);
      B_MISS = uploadBuf({ pos: missPos, col: missCol,
                           size: missPos.map(function () { return 0.024; }),
                           idx: missIdx }, L_RING, B_MISS);
      return cc;
    }
    function fit(aspect) {
      var fovy = 0.9;
      var need = radius / Math.tan(fovy / 2);
      // 系数 1.10（原来是 0.80）：0.80 会把立方体的两个角推到画布外，连带**把 9~14 个刻度数字裁掉**
      //    （实测 911x812 画布上只剩 11/25 个刻度可见）—— 三根轴的刻度数字就是这张图的读数面，
      //    所以留约 10% 余量，25 个刻度在任何常见画布纵横比下都落在画布内。
      cam.dist = Math.max(need, need / Math.max(aspect, 0.2)) * 1.10;
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
      if (L.alpha) gl.uniform1f(L.alpha, buf.alpha === undefined ? 1.0 : buf.alpha);
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
      [B_BOX, B_LAYER, B_HIT, B_MISS, B_HALO].forEach(function (b) {
        b.mvp = MVP; b.mv = V;
      });
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      // ⓪ 角部光晕（**第一个画、且不写深度**）：三块背面当底衬，永远压在散点/等时面/盒子之下。
      //    放到后面画或者写深度都会**挡点**（那是判据里明令禁止的）。
      if (B_HALO.count) {
        gl.depthMask(false);
        bind(B_HALO, P_HALO);
        gl.uniform3fv(L_HALO.bad, halo.params.badRGB);
        gl.uniform3fv(L_HALO.good, halo.params.goodRGB);
        gl.uniform3fv(L_HALO.base, halo.params.baseRGB);
        gl.uniform3fv(L_HALO.badCorner, halo.params.bad);
        gl.uniform3fv(L_HALO.goodCorner, halo.params.good);
        gl.uniform1f(L_HALO.radius, halo.params.radius);
        gl.uniform1f(L_HALO.power, halo.params.power);
        gl.uniform1f(L_HALO.alpha, halo.params.alpha);
        gl.drawElements(gl.TRIANGLES, B_HALO.count, gl.UNSIGNED_INT, 0);
        gl.depthMask(true);
      }
      // ① 等时面（半透明三角网；不写深度，免得它把背后的点挡掉）
      if (B_LAYER.count) {
        gl.depthMask(false);
        B_LAYER.alpha = alphaLayer;
        bind(B_LAYER, P_SOLID);
        gl.drawElements(gl.TRIANGLES, B_LAYER.count, gl.UNSIGNED_INT, 0);
        gl.depthMask(true);
      }
      // ② 盒子（不透明线）
      gl.useProgram(P_SOLID);
      gl.uniform1f(L_SOLID.alpha, 0.85);
      if (showAxes) { bind(B_BOX, P_SOLID); gl.drawElements(gl.LINES, B_BOX.count, gl.UNSIGNED_INT, 0); }
      // ③ 点：命中 = 实心圆盘（出面时淡显）；脱靶 = 空心圈
      if (B_HIT.count) {
        B_HIT.alpha = B_LAYER.count ? 0.35 : 1.0;
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
      draw: draw, cam: cam, fit: fit, box: box, state: state, gl: gl,
      setMissile: function (key) { state.missile = key; buildCloud(); },
      // 换层：只换缓冲，**不发任何请求**（层数据早就一次性拿全了）
      setLayer: function (spec, rgb) {
        state.layer = spec ? spec.level : null;
        B_LAYER = uploadBuf(spec ? surfaceBuffers(d, spec, rgb) : { pos: [], col: [], size: [], idx: [] },
                            L_SOLID, B_LAYER);
      },
      layerInfo: function () { return { tris: B_LAYER.count / 3, level: state.layer }; },
      setFlags: function (o) {
        if (o.axes !== undefined) showAxes = !!o.axes;
      },
      cloudInfo: function () { return cloudColors(d, state.missile, "t_hit"); },
      names: function () { return placeNames(d, this); },
      get spinning() { return spinning; },
      set spinning(v) { spinning = !!v; },
      stats: function () {
        return { points: B_HIT.count + B_MISS.count, lines: B_BOX.count,
                 tris: B_LAYER.count / 3, layer: state.layer,
                 radius: radius, center: center };
      },
      tick: function (dt) { if (spinning) cam.az += dt * 0.35; },
    };
  }

  /* =================================================== 色标图例（2D canvas） */
  function drawColorbar(ctx, d, key, mode) {
    var cc = cloudColors(d, key, mode);
    var w = ctx.canvas.width, h = ctx.canvas.height;
    ctx.clearRect(0, 0, w, h);
    // ⚠ 这一档**没有命中**（`domain === null`）：别画一根 0~1 的假色标 ——
    //   那会让读者以为"颜色 = 0~1 秒"，而实际上一个 t_hit 都没有。
    if (!cc.domain) {
      // ⚠ 配色**必须来自响应**（`d.colors.muted` ← `figures.FIG3_MUTED_COLOR`）：
      //   前端一个颜色字面量都不写（`tests/test_fig3_web.py` 有一条判据扫这个）；
      //   缺了就当**契约破损**当场抛，不写兜底色 —— 兜底色会让"配色来自 figures"变成空话。
      if (!d.colors || !d.colors.muted) {
        throw new Error("fig3 响应缺少 colors.muted（数据配色必须来自 figures，前端不写兜底色）");
      }
      ctx.fillStyle = d.colors.muted;
      ctx.font = "13px system-ui,sans-serif";
      ctx.fillText("该弹在此工况下没有命中", 12, 34);
      ctx.fillText("（无 t_hit 可着色）", 12, 56);
      return;
    }
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

  /* ============================================== β–ginv 热力图（2D canvas） */
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
    fetch("/api/fig3/" + encodeURIComponent(target), { cache: "no-store" })
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
      // ⚠ 弹池列表现在在 `d.points` 里（task-24：每枚弹一个标称点，`d.missiles` 没了）
      var keys = (d.points || []).map(function (m) { return m.key; });
      if (!keys.length) { fail("产物里一枚弹都没有"); return; }
      var saved = loadState();
      // ⚠ "当前弹"的来源（2026-10-03 裁决：必须与**左栏基准弹**是同一枚，否则用户把基准弹改成
      //    R-77 之后，图3 这块还停在 120A 上，而且**看起来一切正常**）：
      //    ① `?missile=` 显式指定（"在新标签页打开"会把当前选择带过去）
      //    ② `?iso=1`（四块提交的自动等时面流程）⇒ 用**基准弹**，不用浏览器里上次点的那枚
      //    ③ localStorage ④ 基准弹 ⑤ 第一枚
      var iso = params.get("iso") === "1";
      var base = d.standard ? String(d.standard) : "";
      var isBase = !!(base && keys.indexOf(base) >= 0);
      var explicit = params.get("missile");
      var want = explicit || ((iso && isBase) ? base : saved.missile);
      if (!want && isBase) { want = base; }
      var state = {
        missile: keys.indexOf(want) >= 0 ? want : keys[0],
        base: isBase ? base : null,   // 基准弹（画布标题要说清当前弹是不是它）
        layer: null,            // 当前显示第几档（null = 没生成/没显示）
        layerBusy: false,
      };
      var v = viewer(gl, d, { transparent: transparent });
      var dpr = Math.min(global.devicePixelRatio || 1, 2);
      function resize() {
        var w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
        if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) { cv.width = w; cv.height = h; }
      }
      resize();
      v.fit(cv.width / Math.max(cv.height, 1));

      // ---- 控件：弹种下拉 + 工况文本 + 「生成等时面」+ 层滑块 ----
      var selM = el("missile");
      keys.forEach(function (k) {
        var o = document.createElement("option");
        o.value = k; o.textContent = k;
        // 0 命中的弹：**可以选中**（点云是空心的），但等时面按钮会置灰并说明原因
        var m = missileInfo(k);
        // ⚠ 标称点未命中**不等于**这枚弹没有等时面（它的立方体里高 ΔV 那一侧仍可能有命中）
        //   ⇒ 只加一个提示后缀，**不禁用**（按钮一律可用，扫完 0 层可出面才提示降级）。
        if (m && !m.hit) { o.textContent = k + "（标称点未命中）"; }
        selM.appendChild(o);
      });
      selM.value = state.missile;
      var sceneEl = el("scene");
      if (sceneEl) sceneEl.textContent = (d.scene && d.scene.text) || "—";
      var rangeEl = el("layer"), labelEl = el("layerLabel"), noteEl = el("layernote");
      var btnLayer = el("btnLayer"), badge = el("layerbadge");
      var layerData = null;             // 一次性拿全的 N 层（拖动滑块不再回服务器）

      function missileInfo(key) {
        var ms = d.points || [];
        for (var i = 0; i < ms.length; i++) if (ms[i].key === key) return ms[i];
        return null;
      }
      function persist() { saveState({ missile: state.missile }); }
      function setNote(text) { if (noteEl) noteEl.textContent = text || ""; }
      function refresh() {
        var cc = v.cloudInfo();
        drawColorbar(el("cbar").getContext("2d"), d, state.missile, "t_hit");
        legend(el("legend"), d, state, cc, v);
        hud(d, state, v, cc);
        persist();
      }
      // 层数据 → 画面：**本地**把第 i 档的网格上传（没有请求）
      function showLayer(i) {
        if (!layerData) return;
        var i0 = Math.max(0, Math.min(i, layerData.surfaces.length - 1));
        state.layer = i0;
        var s = layerData.surfaces[i0];
        if (labelEl) labelEl.textContent = s.label + (s.ok ? "" : "（无可显示的面）");
        if (badge) {
          badge.textContent = s.ok ? (s.label + " · 三角形 " + s.n_tri
                                       + (s.closed ? " · 闭合" : " · 开口"))
                                   : (s.label + " · " + (s.reason || "该层不可出面"));
          badge.className = s.ok ? "" : "off";
        }
        if (s.ok) {
          var cc = cloudColors(d, state.missile, "t_hit");
          var rgb = rampColor(needRamp(d.colors || {}, "t_hit"),
                             (s.level - cc.domain[0]) / ((cc.domain[1] - cc.domain[0]) || 1));
          v.setLayer(s, rgb);
        } else {
          v.setLayer(null);
        }
        setNote(s.ok ? "" : (s.reason || ""));
        refresh();
      }
      function applyLayerData(data) {
        layerData = data;
        var lv = data.layers || {}, surfs = data.surfaces || [];
        if (!surfs.length) { setNote("这一层没有可显示的等时面（该弹在此工况下没有命中）"); return; }
        var okCount = 0;
        (rangeEl ? rangeEl : {}).max = String(surfs.length - 1);
        if (rangeEl) {
          rangeEl.min = "0"; rangeEl.max = String(surfs.length - 1); rangeEl.step = "1";
          rangeEl.disabled = false;
          // 默认停在**第一个可出面**的档上（"默认不出面"这条由按钮把关，不是由这里）
          var first = 0;
          for (var i = 0; i < surfs.length; i++) { if (surfs[i].ok) { first = i; break; } }
          rangeEl.value = String(first);
          for (var j = 0; j < surfs.length; j++) if (surfs[j].ok) okCount++;
          showLayer(first);
        }
        setNote((lv.note || "") + " 共 " + surfs.length + " 档，其中可出面 " + okCount + " 档；"
                + "拖动滑块只在本地切换。");
      }
      // 等时面**按需扫**：第一次点会拿到 **202 + job**，页面显示"正在扫描 X：539 工况"，
      // 轮询 `/progress/<id>`；扫完再打一次本接口就是 200 + 13 层（第二次秒开）。
      var layerUrl = function (missile) {
        return "/api/fig3/" + encodeURIComponent(target) + "/layers?missile="
               + encodeURIComponent(missile);
      };
      var SCAN_TIMEOUT_S = 900;              // 上限：超时就报错，不许无限轮询

      function fetchLayers(missile) {
        return fetch(layerUrl(missile)).then(function (r) {
          return r.json().then(function (body) { return { status: r.status, body: body }; });
        });
      }

      function pollJob(jobId, missile, t0, tier) {
        return fetch("/progress/" + encodeURIComponent(jobId)).then(function (r) {
          return r.json();
        }).then(function (snap) {
          if (snap.state === "error") {
            throw new Error("扫描失败：" + (snap.error || "未知错误"));
          }
          if (snap.state === "done") return true;
          if ((Date.now() - t0) / 1000 > SCAN_TIMEOUT_S) {
            throw new Error("扫描超时（超过 " + SCAN_TIMEOUT_S + " s）");
          }
          var pct = snap.total ? Math.round(100 * (snap.done || 0) / snap.total) : 0;
          // ⚠ 档位从 202 的 `expected.tier` 直接拿：别拿正则去啃消息里的**全角**括号（`（fast）`
          //   匹配 ASCII 的 `\(` 会永远失败，页面上就显示成"（?）"）。
          setNote("正在扫描 " + missile + "：" + (snap.total || "?") + " 工况（" + tier + "）"
                  + " · 进度 " + pct + "% —— 扫完会自动出这一层，第二次打开秒开。");
          return new Promise(function (res) { setTimeout(res, 400); }).then(function () {
            return pollJob(jobId, missile, t0);
          });
        });
      }

      function requestLayers(missile) {
        if (btnLayer) { btnLayer.disabled = true; btnLayer.textContent = "正在生成…"; }
        var t0 = Date.now();
        fetchLayers(missile).then(function (got) {
          if (got.status === 200) return got.body;
          if (got.status === 202) {
            var b = got.body || {};
            var exp = b.expected || {};
            setNote((b.message || ("正在扫描 " + missile))
                    + " · 共 " + (exp.cases || "?") + " 工况（" + (exp.tier || "?") + "）"
                    + " · 扫完自动出这一层");
            return pollJob(b.job, missile, t0, exp.tier || "fast").then(function () {
              return fetchLayers(missile).then(function (again) {
                if (again.status !== 200) {
                  throw new Error("扫完了但取层失败：HTTP " + again.status);
                }
                return again.body;
              });
            });
          }
          throw new Error(((got.body || {}).errors || ["HTTP " + got.status]).join("；"));
        }).then(function (body) {
          applyLayerData(body);
        }).catch(function (e) {
          setNote("取等时面失败：" + (e && e.message ? e.message : e));
        }).then(function () {
          if (btnLayer) { btnLayer.disabled = false; btnLayer.textContent = "生成等时面"; }
        });
      }
      selM.addEventListener("change", function () {
        state.missile = selM.value; layerData = null; state.layer = null;
        v.setLayer(null);
        if (rangeEl) { rangeEl.disabled = true; rangeEl.max = "0"; rangeEl.value = "0"; }
        if (labelEl) labelEl.textContent = "未生成";
        if (badge) { badge.textContent = ""; badge.className = "off"; }
        setNote("");
        v.setMissile(state.missile);
        refresh();
      });
      if (rangeEl) {
        // ⚠ 拖动只做本地切换（**没有 fetch**）：这是"零往返"那条判据在代码里的落点
        rangeEl.addEventListener("input", function () { showLayer(Number(rangeEl.value)); });
      }
      if (btnLayer) {
        btnLayer.addEventListener("click", function () { requestLayers(state.missile); });
      }
      // ---- 裁决 2：`?iso=1`（四块提交里图3 那一块）⇒ **不用点按钮**，自动对基准弹拉一次等时面。
      // 命中缓存秒回；没命中会拿到 202 + scanning，由 `requestLayers()` 自己轮询（那条路径本来就有）。
      if (iso) { requestLayers(state.missile); }

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
        a.href = "/fig3?tag=" + encodeURIComponent(d.tag || target) +
          (state.missile ? "&missile=" + encodeURIComponent(state.missile) : "");
      }

      v.state.missile = state.missile;
      // ⚠ 必须真的建一次点云：`setFlags()` 现在只管坐标轴开关（v4 去掉了拟合层），
      //   不调 `buildCloud()` 的话画面上一个点都没有，而 HUD 会诚实地写"点 0"。
      v.setMissile(state.missile);
      v.setFlags({});
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
        placeNames(d, v);                    // 11 个弹名常显（最小上下错开）
        global.requestAnimationFrame(frame);
      }
      global.requestAnimationFrame(frame);
    }
  }

  // 11 个弹名**常显**（不靠悬停）：每帧把名字贴到该点的投影位置，并做**最小的上下错开** ——
  // 挤在一起时把后面的往下推，保证没有两个标签重叠。
  function placeNames(d, v) {
    // ⚠ 弹名**不能**挂在 `#labels` 里：`placeTicks()` 每帧会把那个容器的子节点裁到刻度个数，
    //   挂在里面的话弹名会被它一起删掉（第一次跑就发现弹名一闪就没了）。
    var host = document.getElementById("view") || document.getElementById("labels");
    if (!host) return [];
    var pts = d.points || [];
    var key = "fig3names";
    var box = host.querySelector("[data-names='" + key + "']");
    if (!box) {
      box = document.createElement("div");
      box.setAttribute("data-names", key);
      box.style.position = "absolute";
      box.style.inset = "0";
      box.style.pointerEvents = "none";
      host.appendChild(box);
    }
    while (box.children.length < pts.length) {
      var sp = document.createElement("span");
      sp.className = "name";
      box.appendChild(sp);
    }
    // ⚠ 必须和 `placeTicks()` 走**同一条**投影链路：W/H 用画布的 CSS 像素（不是
    //   drawingBuffer，否则 devicePixelRatio>1 上标签整体跑偏），center/radius 取 `v.stats()`
    //   （盒子的实际中心与半径，不是写死的 [0,0,0]/0.87）。
    var st = v.stats();
    var cv = document.getElementById("cv");
    var W = cv ? cv.clientWidth : 800, H = cv ? cv.clientHeight : 600;
    var placed = [];
    for (var i = 0; i < pts.length; i++) {
      var it = pts[i];
      var el = box.children[i];
      var P = dataPos(d, it.beta, it.ginv, it.dv);
      var s = projectToScreen(P, v.cam, st.center, st.radius, W, H, 0.9);
      el.textContent = it.label || it.key;
      el.style.color = (d.colors || {}).text || "";
      el.dataset.key = it.key;
      if (!s) { el.style.display = "none"; continue; }     // 转到相机背后的点：连名字一起收
      el.style.display = "";
      placed.push({ el: el, x: s.x, y: s.y, w: Math.max(el.offsetWidth || 0, 26), h: 15 });
    }
    // 最小避让：**只往下推**（不隐藏、不换位），保证没有两个标签重叠
    placed.sort(function (a, b) { return a.y - b.y || a.x - b.x; });
    for (var j = 0; j < placed.length; j++) {
      for (var k = 0; k < j; k++) {
        var a = placed[j], b = placed[k];
        var dx = Math.abs(a.x - b.x), dy = Math.abs(a.y - b.y);
        if (dx < (a.w + b.w) / 2 + 4 && dy < a.h + 1) {
          a.y = b.y + a.h + 1;
        }
      }
      placed[j].el.style.transform = "translate(" + Math.round(placed[j].x + 5) + "px,"
        + Math.round(placed[j].y - 7) + "px)";
    }
    return placed.map(function (q) { return q.el; });
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
    // 三根轴的刻度数字**往各自外侧挪一点**，否则相机转到某个角度时三组数字会叠在一起。
    // 偏移按**世界轴**给（不是按轴名）：x 在前下缘 ⇒ 数字往下、y 在左竖棱 ⇒ 往左、
    // z 在底面右缘 ⇒ 往右。轴名 → 世界轴由 `d.axes[].role` 决定（见 `buildBox`）。
    var off = { x: { dx: 0, dy: 10 }, y: { dx: -10, dy: 0 }, z: { dx: 10, dy: 0 } };
    var roleOf = ["x", "y", "z"];
    var slots = axisSlots(d);
    for (var i = 0; i < ticks.length; i++) {
      var t = ticks[i];
      var p = projectToScreen(t.world, v.cam, s.center, s.radius, W, H, 0.9);
      var node = box.childNodes[i];
      var dxy = off[roleOf[slots[t.axis]]] || { dx: 0, dy: 0 };
      if (!p) { node.style.display = "none"; continue; }
      node.style.display = "";
      node.style.left = (p.x + dxy.dx).toFixed(1) + "px";
      node.style.top = (p.y + dxy.dy).toFixed(1) + "px";
      // ⚠ 刻度小数位**按量级给**：β/ΔV 是三位整数（toFixed(0)），
      //   而 ginv = 1/γ 是 1e-2 量级（0.010066~0.019594）—— 沿用 toFixed(1) 会全部显示 "0.0"。
      node.textContent = t.value.toFixed(axisDigits(t.axis, t.value));
      node.style.color = t.color || d.colors.text;
    }
  }

  function hud(d, state, v, cc) {
    var m = (d.points || []).filter(function (x) { return x.key === state.missile; })[0] || {};
    var s = v.stats();
    var el = function (id) { return document.getElementById(id); };
    if (el("title")) el("title").textContent = "图3 三维散点 · " + state.missile +
      (state.missile === state.base ? "（当前弹＝基准弹，" : "（当前弹，") +
      (cc.label || "t_hit") + "）";
    if (el("sub")) {
      // 轴名与单位**从 `d.axes` 取**（源头是 `figures.FIG3_AXIS_LABELS`），不在这里手写一段
      // 会跟产物漂移的文案；每根轴配一块它的轴色小方块。
      var ax = (d.axes || []).map(function (a) {
        var lo = a.limits[0], hi = a.limits[1];
        var dig = axisDigits(a.id, hi);
        return '<span class="ax"><i style="background:' + a.color + '"></i>' +
          a.label + "　" + fmt(lo, dig) + "~" + fmt(hi, dig) + "</span>";
      }).join("");
      var sh = d.shared || {};
      var order = (d.axis_order || {}).note || "";
      var halonote = (d.halo || {}).note || "";
      el("sub").innerHTML = ax + "<br>" +
        (d.legend.hit || "") + " / " + (d.legend.miss || "") +
        " · 标称点 " + sh.n_points + " 个：命中 " + sh.n_hit + " / 未命中 " + sh.n_miss +
        "（颜色 = 该弹标称点在本工况下的 t_hit；空心 = 未命中，没有 t_hit）" +
        " · " + ((d.labels && d.labels.note) || "") +
        // 摆位与光晕的**口径文本来自响应**（`figures.FIG3_FOOTNOTES` / `FIG3_HALO_NOTE`）——
        // 前端不自己编一段会跟产物漂移的说明。
        (order ? "<br>" + order : "") + (halonote ? " · " + halonote : "");
    }
    if (el("stat")) {
      var sh = d.shared || {};
      el("stat").textContent = "标称点 " + s.points + "（命中 " + sh.n_hit + " / 未命中 "
        + sh.n_miss + "）· 线 " + s.lines +
        (s.tris ? " · 等时面 " + s.tris + " 三角形（" + (s.layer === null ? "—" : s.layer + " s") + "）" : "") +
        " · 按需立方体 " + d.grid.n_cases + " 工况/弹 · 手写 WebGL2 · 无第三方 JS";
    }
  }

  function legend(box, d, state, cc, v) {
    if (!box) return;
    var C = d.colors || {}, L = d.legend || {};
    var html = "";
    html += '<span><i class="sw" style="background:' + C.hit + '"></i>' + (L.hit || "命中") + "</span>";
    html += '<span><i class="sw ring" style="border-color:' + C.miss + '"></i>' +
      (L.miss || "脱靶") + "</span>";
    html += "<span>颜色 = " + (cc.label || "t_hit") +
      (cc.unit ? " [" + cc.unit + "]" : "") +
      (cc.domain ? "（共享范围 " + fmt(cc.domain[0], 2) + "~" + fmt(cc.domain[1], 2) + "）" : "") +
      "</span>";
    var layer = v && v.layerInfo ? v.layerInfo() : null;
    html += '<span><i class="sw" style="background:' + (C.text || "") + '"></i>'
      + ((L.label) || "弹名常显") + "</span>";
    html += '<span><i class="sw" style="background:' + C.hit + ';opacity:' +
      (C.layer_alpha === undefined ? 0.55 : C.layer_alpha) + '"></i>等时面（单层，滑块切）' +
      (layer && layer.level !== null ? "：t = " + layer.level + " s" : "：未生成") + "</span>";
    // 角部光晕：两枚色块（红/绿都来自响应）+ 口径文本也来自响应（`figures.FIG3_HALO_NOTE`）。
    var H = C.halo || {};
    if (H.bad && H.good && (d.halo || {}).note) {
      html += '<span><i class="sw" style="background:' + H.bad + '"></i>' +
        '<i class="sw halo2" style="background:' + H.good + '"></i>' +
        (d.halo.note || "") + "</span>";
    }
    html += '<span class="note">' + (cc.note || "") + "</span>";
    box.innerHTML = html;
  }

  var API = { M4: M4, norm: norm, clamp: clamp, hex2rgb: hex2rgb, mixColor: mixColor,
              rampColor: rampColor, rgbCss: rgbCss, fmt: fmt,
              nodeOf: nodeOf, columnOf: columnOf, axisNorm: axisNorm, pointPos: pointPos,
              axisSlot: axisSlot, axisSlots: axisSlots, packWorld: packWorld,
              dataPos: dataPos, cloudColors: cloudColors, colorDomain: colorDomain,
              surfaceBuffers: surfaceBuffers, buildBox: buildBox,
              haloParams: haloParams, haloWeight: haloWeight, haloColorAt: haloColorAt,
              haloBuffers: haloBuffers, FS_HALO: FS_HALO, TICK_EDGE: TICK_EDGE,
              applyDrag: applyDrag, applyPan: applyPan, projectToScreen: projectToScreen,
              viewer: viewer, drawColorbar: drawColorbar,
              loadState: loadState, saveState: saveState, boot: boot,
              STORE_KEY: STORE_KEY, AZ_PER_PX: AZ_PER_PX, EL_PER_PX: EL_PER_PX, AZ0: AZ0, EL0: EL0,
              defaultView: function () { return { az: AZ0, el: EL0 }; } };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  global.FIG3 = API;
  if (typeof document !== "undefined" && document.getElementById) boot();
})(typeof window !== "undefined" ? window : globalThis);

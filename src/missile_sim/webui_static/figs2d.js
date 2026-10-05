/* 图1（ΔV–β）/ 图2（β–ginv）的**客户端 SVG 渲染器** —— 零第三方、无模块系统，挂一个全局。
 *
 * 三条硬口径（别凭记忆改）：
 *
 * ① **只画不算**：点的坐标全部来自壳给的 `catalog`（= `results/missile_catalog.json`，
 *    由 Python 侧用内核 blk 现算的派生目录）。本文件不碰内核参数、不推转向损失、不解方程，
 *    除图数据之外没有任何计算；唯一的算式是「等 n* 线的斜率」，那是**画法**（解析式），
 *    口径与 `bg.nstar_slope()` 逐值一致，由 `tests/test_figs2d.py` 的 node 探针钉住。
 * ② **轴域与 Python 逐值一致**：`planeAxis()` 对 `figures.adaptive_axis()`（`_one_axis` +
 *    `_nice_tick` + `_minor_for` + `MIN_PAD`/`PAD_FRAC`/`DEFAULT_*`），`bgAxis()` 对
 *    `figures.bg_axis()`（pad 0.06 / 下限 60 与 9e-4 / `y_minor = y_major/5`）。同一个子集，
 *    两边必须给出同一个 xlim/ylim 与同一组刻度（node 探针逐值比对）。
 * ③ **不写文案、不发请求、不落状态**：图注文本由壳通过 `notes` 传进来，本文件只摆位置；
 *    选中集合由壳管（`setSelection(keys)`），这里不存任何东西；整份源码里**零网络调用**
 *    —— 切弹池必然是零网络往返（这条就是它的机器证据，由判据按源码扫）。
 *
 * 壳按这个**冻结接口**调用（形状别改，要改先报 Lead）：
 *
 *     window.FIGS2D = {
 *       mount(host, {kind, catalog, notes}) {
 *         return { setSelection(keys) {...}, redraw() {} };
 *       }
 *     };
 *
 * `host` 是一个空的 `<div>`；`kind` 取 "plane" | "bg"；`catalog` 是目录对象；
 * `notes` 是字符串数组（图注，壳给）。挂载后内部自己建 `<svg>` 与图注 `<ul>`。
 */
(function (global) {
  'use strict';

  var F = {};

  //: SVG 的逻辑画布尺寸（viewBox）。CSS 负责响应式缩放，这里只定坐标。
  F.VIEW = { w: 760, h: 420, pad: { l: 66, r: 24, t: 26, b: 44 } };

  // ============================================================ ① 轴口径（对齐 figures.py）
  F.PAD_FRAC = 0.06;
  F.MIN_PAD = { x: 12.0, y: 60.0 };
  F.DEFAULT_XLIM = [800.0, 1110.0];
  F.DEFAULT_YLIM = [2450.0, 3850.0];
  F.DEFAULT_TICKS = { x: [30.0, 10.0], y: [100.0, 50.0] };
  F.BG_PAD = 0.06;
  F.BG_MIN_PAD = { x: 60.0, y: 9e-4 };
  F.G0 = 9.81;
  // ⚠ 2026-10-05：这里原来硬编码 `[14…20]` —— 具体 G 数是**数据**，客户端不许自己发明。
  //   层数一律来自 payload 的 `style.nstar_levels`（`figures.BG_NSTAR_*`），缺失即空数组。
  F.NSTAR_LEVELS = [];

  function roundN(v, n) {
    var f = Math.pow(10, n);
    return Math.round(v * f) / f;
  }
  F.roundN = roundN;

  /** 落在一组整数刻度上的主刻度（对齐 `figures._nice_tick`）。 */
  /** 统一刻度口径（与 `figures.axis_ticks()` 同一规格；六个轴共用，见那里的长注释）。 */
  F.NICE_STEPS = [1.0, 2.0, 2.5, 5.0, 10.0];
  F.TICK_TARGET = 6.5;
  F.MINORS_PER_MAJOR = 5;
  F.ticks = function (lo, hi, opt) {
    opt = opt || {};
    var target = +opt.target || F.TICK_TARGET;
    var mpm = +opt.minorsPerMajor || F.MINORS_PER_MAJOR;
    var a = +lo, b = +hi, span = b - a;
    if (!(span > 0)) { throw new Error('ticks 需要 hi > lo'); }
    var raw = span / Math.max(target, 1e-9);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var step = F.NICE_STEPS
      .map(function (c) { return c * mag; })
      .reduce(function (best, s) {
        return (Math.abs(s - raw) < Math.abs(best - raw) - 1e-12) ? s : best;
      });
    // ⚠ 用主刻度数夹住（∈[5,9]）：只按 span/target 选档会越界（实测跨度 0.0095 会选到 1e-3 ⇒ 10 格）
    function majorsOf(st) { return Math.floor(b / st) - Math.ceil(a / st) + 1; }
    function at(i) { return [1.0, 2.0, 2.5, 5.0][((i % 4) + 4) % 4] * Math.pow(10, Math.floor(i / 4)); }
    var seq = [];
    for (var s = -40; s <= 40; s++) { seq.push(at(s)); }
    var i0 = 0;
    for (var q = 1; q < seq.length; q++) {
      if (Math.abs(seq[q] - step) < Math.abs(seq[i0] - step) - 1e-18) { i0 = q; }
    }
    while (majorsOf(seq[i0]) > (opt.maxMajors || 9) && i0 < seq.length - 1) { i0++; }
    while (majorsOf(seq[i0]) < (opt.minMajors || 5) && i0 > 0) { i0--; }
    step = seq[i0];
    mag = Math.pow(10, Math.floor(Math.log10(step)));
    var mantissa = step / mag;
    var equalParts = (Math.abs(mantissa - 2.0) < 1e-9 || Math.abs(mantissa - 2.5) < 1e-9) ? 4 : mpm;
    var decimals = Math.max(0, -Math.floor(Math.log10(step)));
    var majors = [], minors = [], out = [];
    var first = Math.ceil(a / step) * step;
    for (var v = first; v <= b + 1e-9; v += step) {
      var val = roundN(v, Math.max(0, decimals + 2));
      majors.push(val);
      // 标签去掉多余 0（用户口径「无多余 0」）：0.00010 -> 0.0001；decimals 本身不改
      var lab = val.toFixed(decimals);
      if (lab.indexOf('.') >= 0) { lab = lab.replace(/0+$/, '').replace(/\.$/, ''); }
      out.push({ v: val, label: lab });
    }
    for (var w = Math.ceil(a / (step / equalParts)) * (step / equalParts); w <= b + 1e-9;
         w += step / equalParts) {
      minors.push(roundN(w, Math.max(0, decimals + 2)));
    }
    return { lo: a, hi: b, step: step, minor: step / equalParts, majors: majors, minors: minors,
             decimals: decimals, ticks: out };
  };

  F.niceTick = function (span, target) {
    var raw = Math.max(Number(span), 1e-9) / Math.max(Number(target) | 0, 1);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var cand = [1.0, 2.0, 2.5, 5.0, 10.0];
    for (var i = 0; i < cand.length; i++) {
      if (raw <= cand[i] * mag * (1 + 1e-9)) { return cand[i] * mag; }
    }
    return 10.0 * mag;
  };

  /** 次刻度（对齐 `figures._minor_for`）：五等分，太细就二等分。 */
  F.minorFor = function (major) {
    return (major / 5.0 >= 5e-3) ? major / 5.0 : major / 2.0;
  };

  /** 一条轴（对齐 `figures._one_axis`）：范围 + 主/次刻度。 */
  F.oneAxis = function (vals, axis) {
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var pad = Math.max((hi - lo) * F.PAD_FRAC, F.MIN_PAD[axis]);
    var a = lo - pad, b = hi + pad;
    // ⚠ 2026-10-05：刻度统一走 F.ticks()（原来有一条"跨度 ≥ 默认跨度一半就照旧用 30/100"的捷径，
    //   正是它让图1 出现 11/12/38 格而图2 只有 2/3 格）。**范围 lim 完全不动**。
    var t = F.ticks(a, b);
    return { lim: [a, b], major: t.step, minor: t.minor, decimals: t.decimals };
  };

  /** 图1 的轴（对齐 `figures.adaptive_axis`）：横 ΔV、纵 β(=BC)。 */
  F.planeAxis = function (points) {
    var pts = (points || []).filter(function (p) { return p && isFinite(+p.dv) && isFinite(+p.bc); });
    if (!pts.length) { throw new Error('自适应轴至少需要一个点'); }
    var x = F.oneAxis(pts.map(function (p) { return +p.dv; }), 'x');
    var y = F.oneAxis(pts.map(function (p) { return +p.bc; }), 'y');
    return {
      xlim: [roundN(x.lim[0], 3), roundN(x.lim[1], 3)],
      ylim: [roundN(y.lim[0], 3), roundN(y.lim[1], 3)],
      x_major: x.major, x_minor: x.minor, y_major: y.major, y_minor: y.minor
    };
  };

  /** 图2 的轴（对齐 `figures.bg_axis`）：横 β、纵 ginv。 */
  F.bgAxis = function (rows, opt) {
    opt = opt || {};
    var rws = (rows || []).filter(function (r) { return r && isFinite(+r.beta) && isFinite(+r.ginv); });
    if (!rws.length) { throw new Error('bg_axis 需要至少一行数据'); }
    var bs = rws.map(function (r) { return +r.beta; });
    var gs = rws.map(function (r) { return +r.ginv; });
    var b0 = Math.min.apply(null, bs), b1 = Math.max.apply(null, bs);
    var g0 = Math.min.apply(null, gs), g1 = Math.max.apply(null, gs);
    var bp = Math.max((b1 - b0) * F.BG_PAD, F.BG_MIN_PAD.x);
    var gp = Math.max((g1 - g0) * F.BG_PAD, F.BG_MIN_PAD.y);
    var xlim = opt.xlim ? [+opt.xlim[0], +opt.xlim[1]] : [b0 - bp, b1 + bp];
    var ylim = opt.ylim ? [+opt.ylim[0], +opt.ylim[1]] : [g0 - gp, g1 + gp];
    if (!(xlim[1] > xlim[0]) || !(ylim[1] > ylim[0])) {
      throw new Error('坐标轴范围必须是递增的两个数');
    }
    // ⚠ 2026-10-05：x/y 都走 F.ticks()（原来 x 用 target=5、y 用 target=4，纵轴次刻度还单独
    //   走 ymaj/5 ⇒ 与图1 分叉）。**范围 xlim/ylim 完全不动**。
    var tx = F.ticks(xlim[0], xlim[1]);
    var ty = F.ticks(ylim[0], ylim[1]);
    return {
      xlim: [roundN(xlim[0], 6), roundN(xlim[1], 6)],
      ylim: [roundN(ylim[0], 6), roundN(ylim[1], 6)],
      x_major: tx.step, x_minor: tx.minor, x_decimals: tx.decimals,
      y_major: ty.step, y_minor: ty.minor, y_decimals: ty.decimals
    };
  };

  // ============================================================ ② 等 n* 线（画法，口径对齐 nstar_slope）
  /** 斜率 m：`ginv = m·β`（对齐 `bg.nstar_slope`，`ref` 来自目录的 `reference`）。 */
  F.nstarSlope = function (nStar, ref) {
    var q = +ref.q_pa, f = +ref.f_mach, cap = +ref.cap_f;
    if (!(q > 0) || !(f > 0) || !(cap > 0)) { throw new Error('reference 不完整'); }
    if (!(+nStar > 0)) { throw new Error('n* 必须为正'); }
    return Math.pow(+nStar * F.G0 / q, 2) * (cap / f);
  };

  /** 等 n* 线在当前轴域里的两个端点（直线过原点，裁到轴矩形）：[{n, m, x0, y0, x1, y1}]。 */
  F.nstarLines = function (axis, ref, levels) {
    var x0 = axis.xlim[0], x1 = axis.xlim[1], y0 = axis.ylim[0], y1 = axis.ylim[1];
    var out = [];
    (levels || F.NSTAR_LEVELS).forEach(function (n) {
      var m = F.nstarSlope(n, ref);
      var xa = Math.max(x0, y0 / m), xb = Math.min(x1, y1 / m);
      if (xb > xa) { out.push({ n: n, m: m, x0: xa, y0: m * xa, x1: xb, y1: m * xb }); }
    });
    return out;
  };

  // ============================================================ ③ 标签避让（纯函数：浏览器与 node 同一套）
  /** 标签盒的估算尺寸（不量 DOM，node 里也能算）：等宽粗体近似 + 内边距。 */
  F.estimateBox = function (text, fontPx) {
    var f = fontPx || 9.5;
    return { w: 0.62 * f * String(text).length + 3.0, h: f * 1.35 };
  };

  function overlaps(a, b) {
    return !(a.x1 <= b.x0 || b.x1 <= a.x0 || a.y1 <= b.y0 || b.y1 <= a.y0);
  }
  F.overlaps = overlaps;

  /** 把一个数据点投影到像素（SVG 坐标系：y 向下）。 */
  F.project = function (rect, axis, x, y) {
    var px = rect.x + (x - axis.xlim[0]) / (axis.xlim[1] - axis.xlim[0]) * rect.w;
    var py = rect.y + rect.h - (y - axis.ylim[0]) / (axis.ylim[1] - axis.ylim[0]) * rect.h;
    return { x: px, y: py };
  };

  /**
   * 贪心 + 候选位评分：给每个点挑一个不压点/不压已放标签、且不出轴的标注位。
   *
   * 输入 items = [{key, label, x, y}]（数据坐标）、axis、rect（绘图区像素矩形）。
   * 返回 [{key, label, tx, ty, box, kept}] —— kept=false 表示这一枚放不下就不放
   * （159 枚全选时必然放不下；宁可少标，也不叠成一团）。
   *
   * 评分（越小越好）：压已放标签罚 1000/次、出轴罚 1000/次、压到别的点罚 300/次、
   * 引线太长按像素加罚；同分取靠前的候选位。候选位：8 个方向 × 2 个半径。
   */
  F.placeLabels = function (items, axis, rect, opt) {
    opt = opt || {};
    var font = +opt.font || 9.5;
    var pad = +opt.pad || 6.0;
    var items2 = (items || []).map(function (it) {
      var p = F.project(rect, axis, +it.x, +it.y);
      var box = F.estimateBox(it.label, font);
      return { key: it.key, label: it.label, px: p.x, py: p.y, w: box.w, h: box.h };
    });
    var order = items2.map(function (it, i) { return i; }).sort(function (a, b) {
      var A = items2[a], B = items2[b];
      var da = 0, db = 0;
      items2.forEach(function (o) {
        if (Math.hypot(o.px - A.px, o.py - A.py) < 46) { da++; }
        if (Math.hypot(o.px - B.px, o.py - B.py) < 46) { db++; }
      });
      return (db - da) || (A.py - B.py) || (a - b);
    });
    var dirs = [[1, 0], [0, -1], [-1, 0], [0, 1], [1, -1], [-1, -1], [1, 1], [-1, 1]];
    var radii = [+opt.r1 || (font + pad), +opt.r2 || (font * 2.4 + pad)];
    var placed = [];
    var res = items2.map(function (it) {
      return { key: it.key, label: it.label, tx: it.px, ty: it.py, box: null,
               kept: false, ha: 'left', va: 'middle' };
    });
    order.forEach(function (idx) {
      var it = items2[idx];
      var best = null;
      radii.forEach(function (r) {
        dirs.forEach(function (d) {
          var ha = d[0] > 0 ? 'left' : (d[0] < 0 ? 'right' : 'center');
          var va = d[1] > 0 ? 'top' : (d[1] < 0 ? 'bottom' : 'middle');
          var cx = (d[0] === 0) ? it.px : it.px + d[0] * (r + it.w / 2);
          var cy = (d[1] === 0) ? it.py : it.py + d[1] * (r + it.h / 2);
          var box = { x0: cx - it.w / 2, x1: cx + it.w / 2, y0: cy - it.h / 2, y1: cy + it.h / 2 };
          var score = 0;
          placed.forEach(function (b) { if (overlaps(box, b)) { score += 1000; } });
          items2.forEach(function (o) {                       // 别压到别的点（自己的点不算）
            if (o === it) { return; }
            if (Math.hypot(o.px - cx, o.py - cy) < (o.w * 0.18 + 3.2)) { score += 300; }
          });
          var m = 2.0;
          if (box.x0 < rect.x - m || box.x1 > rect.x + rect.w + m ||
              box.y0 < rect.y - m || box.y1 > rect.y + rect.h + m) { score += 1000; }
          score += Math.hypot(cx - it.px, cy - it.py) * 0.6;  // 引线越长越差
          if (!best || score < best.score) {
            best = { score: score, box: box, tx: cx, ty: cy, ha: ha, va: va };
          }
        });
      });
      if (best && best.score < 1000) {                        // 有硬冲突就干脆不标
        placed.push(best.box);
        var slot = res[idx];
        slot.tx = best.tx; slot.ty = best.ty; slot.box = best.box;
        slot.kept = true; slot.ha = best.ha; slot.va = best.va;
      }
    });
    return res;
  };

  // ============================================================ ④ 目录 → 可画条目
  /**
   * 图上该画哪些条目：unsupported（不可算）不进图；duplicate_of / default_hidden
   * （_default 孪生）默认不进图；坐标缺一项也不进。顺序按目录原序（稳定）。
   */
  F.drawableEntries = function (catalog) {
    var out = [];
    (catalog && catalog.missiles ? catalog.missiles : []).forEach(function (m) {
      if (!m || m.duplicate_of || m.default_hidden) { return; }
      if (!isFinite(+m.dv) || !isFinite(+m.bc) || !isFinite(+m.ginv)) { return; }
      out.push(m);
    });
    return out;
  };

  /** 图面样式：目录里带 style 就用它（壳/服务端给），否则用与 figures 对齐的常量。 */
  F.styleOf = function (catalog) {
    var s = (catalog && catalog.style) || {};
    return {
      point_color: s.point_color || '#D32F2F',       // figures.POINT_COLOR
      lbl_color: s.lbl_color || '#C62828',           // figures.LBL_COLOR
      base_color: s.base_color || '#388E3C',         // figures.BASE_COLOR
      nstar_color: s.nstar_color || '#90A4AE',       // figures.BG_NSTAR_COLOR
      text: s.text || '#555555',                     // figures.GRAY
      leader: s.leader || '#BBBBBB',
      grid_major: s.grid_major || '#CCCCCC',
      grid_minor: s.grid_minor || '#E9E9E9',
      axis: s.axis || '#8A8A8A',
      point_r: s.point_r || 6.3,                     // sqrt(figures.POINT_SIZE/π)（pt→px @96dpi）
      lbl_font: s.lbl_font || 9.5,                   // figures.LBL_FONTSIZE
      nstar_levels: s.nstar_levels || F.NSTAR_LEVELS,
      // 标签步长（payload 的 `style.nstar_label_step`）：数值 ⇒ 只在整数倍打标签；null ⇒ 全打；
      // **未给**（undefined）⇒ 走与数据无关的通用回落，见 renderBg。
      nstar_label_step: s.nstar_label_step,
      // 随框动态的间距/滑动预算（轴高比例；Python 侧同名下发，缺省 0.02 / 0.05）
      nstar_label_min_gap: s.nstar_label_min_gap,
      nstar_label_slide: s.nstar_label_slide,
      xlabel: s.xlabel || '', ylabel: s.ylabel || '',
      xlabel_bg: s.xlabel_bg || '', ylabel_bg: s.ylabel_bg || '',
      base: s.base || ''
    };
  };

  // ============================================================ ⑤ 渲染（只在有 DOM 时跑）
  var NS = 'http://www.w3.org/2000/svg';
  function el(svg, tag, attrs, text) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    svg.appendChild(node);
    return node;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  /** 刻度标签的小数位：跟着步长走（ginv 那种 1e-2 量级不会被打成 0.00）。 */
  F.tickDecimals = function (step) {
    if (!(step > 0)) { return 0; }
    return Math.max(0, Math.ceil(-Math.log10(step)) + 1);
  };
  F.fmtTick = function (v, step) {
    var d = F.tickDecimals(step);
    var s = (+v).toFixed(d);
    if (d > 0) { s = s.replace(/0+$/, '').replace(/\.$/, ''); }
    return s === '-0' ? '0' : s;
  };

  /** 绘图区像素矩形（viewBox 坐标）。 */
  F.rectOf = function (view) {
    view = view || F.VIEW;
    return { x: view.pad.l, y: view.pad.t,
             w: Math.max(80, view.w - view.pad.l - view.pad.r),
             h: Math.max(60, view.h - view.pad.t - view.pad.b) };
  };

  function frame(svg, rect, axis, st) {
    var x = axis.xlim[0], y0 = axis.ylim[0], i, v;
    for (v = Math.ceil(x / axis.x_minor) * axis.x_minor; v <= axis.xlim[1]; v += axis.x_minor) {
      i = F.project(rect, axis, v, y0);
      el(svg, 'line', { x1: i.x, y1: rect.y, x2: i.x, y2: rect.y + rect.h,
                        stroke: st.grid_minor, 'stroke-width': 0.5 });
    }
    for (v = Math.ceil(y0 / axis.y_minor) * axis.y_minor; v <= axis.ylim[1]; v += axis.y_minor) {
      i = F.project(rect, axis, x, v);
      el(svg, 'line', { x1: rect.x, y1: i.y, x2: rect.x + rect.w, y2: i.y,
                        stroke: st.grid_minor, 'stroke-width': 0.5 });
    }
    for (v = Math.ceil(x / axis.x_major) * axis.x_major; v <= axis.xlim[1]; v += axis.x_major) {
      i = F.project(rect, axis, v, y0);
      el(svg, 'line', { x1: i.x, y1: rect.y, x2: i.x, y2: rect.y + rect.h,
                        stroke: st.grid_major, 'stroke-width': 0.8 });
      el(svg, 'text', { x: i.x, y: rect.y + rect.h + 13, 'text-anchor': 'middle',
                        fill: st.text, 'font-size': 9 }, F.fmtTick(v, axis.x_major));
    }
    for (v = Math.ceil(y0 / axis.y_major) * axis.y_major; v <= axis.ylim[1]; v += axis.y_major) {
      i = F.project(rect, axis, x, v);
      el(svg, 'line', { x1: rect.x, y1: i.y, x2: rect.x + rect.w, y2: i.y,
                        stroke: st.grid_major, 'stroke-width': 0.8 });
      el(svg, 'text', { x: rect.x - 6, y: i.y + 3, 'text-anchor': 'end',
                        fill: st.text, 'font-size': 9 }, F.fmtTick(v, axis.y_major));
    }
    el(svg, 'line', { x1: rect.x, y1: rect.y, x2: rect.x, y2: rect.y + rect.h,
                      stroke: st.axis, 'stroke-width': 1 });
    el(svg, 'line', { x1: rect.x, y1: rect.y + rect.h, x2: rect.x + rect.w, y2: rect.y + rect.h,
                      stroke: st.axis, 'stroke-width': 1 });
  }

  function drawLabels(svg, items, axis, rect, st) {
    var placed = F.placeLabels(items, axis, rect, { font: st.lbl_font });
    placed.forEach(function (p, i) {
      if (!p.kept) { return; }
      var it = items[i];
      var pt = F.project(rect, axis, +it.x, +it.y);
      if (Math.hypot(p.tx - pt.x, p.ty - pt.y) > st.lbl_font + 9) {
        el(svg, 'line', { x1: pt.x, y1: pt.y, x2: p.tx, y2: p.ty,
                          stroke: st.leader, 'stroke-width': 0.6 });
      }
      el(svg, 'text', { x: p.tx, y: p.ty,
                        'text-anchor': p.ha === 'right' ? 'end' : (p.ha === 'center' ? 'middle' : 'start'),
                        'dominant-baseline': 'middle', fill: it.color,
                        'font-size': st.lbl_font, 'font-weight': 'bold' }, p.label);
    });
    return placed;
  }

  function dots(svg, items, axis, rect, st) {
    items.forEach(function (it) {
      var p = F.project(rect, axis, +it.x, +it.y);
      el(svg, 'circle', { cx: p.x, cy: p.y, r: st.point_r, fill: it.color,
                          stroke: '#ffffff', 'stroke-width': 0.9 });
      el(svg, 'title', {}, it.title || it.label);
    });
  }

  function axisTitles(svg, rect, st, xlabel, ylabel) {
    if (xlabel) {
      el(svg, 'text', { x: rect.x + rect.w / 2, y: rect.y + rect.h + 34, 'text-anchor': 'middle',
                        fill: st.text, 'font-size': 12 }, xlabel);
    }
    if (ylabel) {
      el(svg, 'text', { x: 14, y: rect.y + rect.h / 2, 'text-anchor': 'middle', fill: st.text,
                        'font-size': 12,
                        transform: 'rotate(-90 14 ' + (rect.y + rect.h / 2) + ')' }, ylabel);
    }
  }

  /** 图1：ΔV–β 散点 + 标签（基准弹涂绿）。points 直接来自目录条目。 */
  F.renderPlane = function (svg, points, style, view) {
    var st = style || F.styleOf(null);
    var axis = F.planeAxis(points);
    var rect = F.rectOf(view);
    clear(svg);
    frame(svg, rect, axis, st);
    var items = (points || []).map(function (p) {
      return { key: p.key, label: p.label || p.key, x: +p.dv, y: +p.bc,
               color: (st.base && p.key === st.base) ? st.base_color : st.point_color,
               title: (p.full_name || p.key) + '　ΔV=' + (+p.dv).toFixed(1)
                      + '，β=' + (+p.bc).toFixed(1) };
    });
    dots(svg, items, axis, rect, st);
    drawLabels(svg, items, axis, rect, st);
    axisTitles(svg, rect, st, st.xlabel, st.ylabel);
    return axis;
  };

  /** 线段在数据域里的参数区间（框内可见段）；完全在框外返回 null —— 这就是"可见线"判定。 */
  F.visibleSeg = function (axis, x0, y0, x1, y1) {
    var dx = x1 - x0, dy = y1 - y0, t0 = 0, t1 = 1;
    function clip(p, q) {                       // Liang–Barsky
      if (Math.abs(p) < 1e-15) { return q >= 0; }
      var r = q / p;
      if (p < 0) { if (r > t1) { return false; } if (r > t0) { t0 = r; } }
      else { if (r < t0) { return false; } if (r < t1) { t1 = r; } }
      return true;
    }
    if (!clip(-dx, x0 - axis.xlim[0]) || !clip(dx, axis.xlim[1] - x0) ||
        !clip(-dy, y0 - axis.ylim[0]) || !clip(dy, axis.ylim[1] - y0) || t1 <= t0) { return null; }
    return { x0: x0 + dx * t0, y0: y0 + dy * t0, x1: x0 + dx * t1, y1: y0 + dy * t1, t0: t0, t1: t1 };
  };

  /** n* 标签摆放（**纯函数**，node 可测）：只给框内可见的线打标签，沿可见段错开 + 贪心避让。

   * 为什么不是"线末端一个标签"：`BG_NSTAR_LABEL_STEP = None`（用户口径：每根线都要看到 G 值）
   * 之后 12~20 共 9 条线会同时出现在框内，末端标签会**挤成一团**。这里按索引沿可见段取不同的
   * 参数 t（0.30~0.70 铺开），再按矩形两两不重叠做贪心微调；**绝不减少标签数量**
   * （数量由 `nstar_label_step` 决定，不由摆放决定）。
   */
  /** 出口点：这条线与轴框的交点落在**上边**还是**右边**（确定性，两侧都能算）。 */
  F.nstarExit = function (axis, seg) {
    var onTop = Math.abs(seg.y1 - axis.ylim[1]) < 1e-9 || Math.abs(seg.y0 - axis.ylim[1]) < 1e-9;
    var onRight = Math.abs(seg.x1 - axis.xlim[1]) < 1e-9 || Math.abs(seg.x0 - axis.xlim[1]) < 1e-9;
    if (onTop && onRight) {                      // 角上出：按"离上边更近"归一边，避免二义
      return { x: (Math.abs(seg.y1 - axis.ylim[1]) < 1e-9 ? seg.x1 : seg.x0), y: axis.ylim[1], edge: 'top' };
    }
    if (onTop) { return { x: (Math.abs(seg.y1 - axis.ylim[1]) < 1e-9 ? seg.x1 : seg.x0), y: axis.ylim[1], edge: 'top' }; }
    return { x: axis.xlim[1], y: (Math.abs(seg.x1 - axis.xlim[1]) < 1e-9 ? seg.y1 : seg.y0), edge: 'right' };
  };

  /** n* 标签"随框动态"摆放（**纯函数**，node 可测；确定性：同一输入两次调用逐值相同）。

  规格（Lead 2026-10-05 批准，含两处修正）：
   1. 候选 = **框内可见**的等 n* 线（`F.visibleSeg` 判定），锚点 = 该线与轴框的**出口点**；
   2. ⚠ **标签盒整体朝框内偏移**：上边出 ⇒ 向下 `h/2+3`；右边出 ⇒ 向左 `w/2+3`。
      不这么做的话盒子一半挂在框外 —— 实测会导致**一个都放不下**（0/8，这就是那条陷阱）；
   3. **间距用轴高的比例**（`--fig3`/payload 的 `nstar_label_min_gap`，缺省 0.02）：像素在页面与
      matplotlib 之间不可比，比例才两侧一致；
   4. 冲突时**沿该线朝框内滑**，最多 `nstar_label_slide`（缺省 0.05）轴高；滑完仍冲突 ⇒ 放弃；
   5. **优先级 = 预留位**：先放 5 的整数倍（10/15/20/25…），再按 G 升序填空位 ⇒ 极端窗里被放弃的是
      **非 5 倍数**（例：全目录窗 14 条里弃 13、保 45）。这是**几何硬限，不是 bug**。
   6. 字号固定 9（行高 ≈ 0.035 轴高；实测 8 个候选铺开时最小间距 0.146 轴高，无需缩字号）。
  数量由 `nstar_label_step` 决定（null ⇒ 全打），摆放**只会放弃**、不会凭空多打。
   */
  F.nstarLabelLayout = function (rect, axis, lines, st, opt) {
    opt = opt || {};
    var font = opt.font || 9;
    var gap = (st.nstar_label_min_gap === undefined ? 0.02 : +st.nstar_label_min_gap) * rect.h;
    var slide = (st.nstar_label_slide === undefined ? 0.05 : +st.nstar_label_slide) * rect.h;
    var step = (st.nstar_label_step === undefined) ? ((lines.length <= 5) ? null : 2)
                                                   : st.nstar_label_step;
    var five = function (n) { return Math.abs(n / 5 - Math.round(n / 5)) < 1e-9; };
    function inset(edge, box) {
      return (edge === 'top') ? { x: 0, y: box.h / 2 + 3 } : { x: -(box.w / 2 + 3), y: 0 };
    }
    var cand = [];
    lines.forEach(function (L, i) {
      var nv = (L.n !== undefined) ? L.n : L.nstar;
      if (!(step === null || nv === undefined ||
            Math.abs(nv / step - Math.round(nv / step)) < 1e-9)) { return; }
      var seg = F.visibleSeg(axis, L.x0, L.y0, L.x1, L.y1);
      if (!seg) { return; }                                  // 线在框外 ⇒ 不打标签
      var e = F.nstarExit(axis, seg), box = F.estimateBox('n*=' + nv, font);
      var p0 = F.project(rect, axis, e.x, e.y);
      // 滑动方向 = 该**出口边的内法线**（上边 ⇒ +y；右边 ⇒ −x）。用内法线而不是"沿线的单位向量"，
      // 是为了不在这个**纯绘图**文件里引入归一化数学（`-k figs2d` 的"只画不算"判据禁止 Math.sqrt 之类）。
      var ux = (e.edge === 'right') ? -1 : 0, uy = (e.edge === 'top') ? 1 : 0;
      cand.push({ n: nv, box: box, edge: e.edge, p0: p0, ux: ux, uy: uy,
                  prio: five(nv) ? 0 : 1 });
    });
    cand.sort(function (a, b) { return (a.prio - b.prio) || (a.n - b.n); });   // 5 的倍数先占位
    var boxes = [], out = [], cramped = [];
    function pos(r, edge) {                      // 加内偏、夹进框
      var off = inset(edge, r.w ? r : { w: r.w, h: r.h });
      return r;
    }
    function candidates(c) {                     // 该线的 13 个候选位（含内偏与 clamp）
      var res = [], off = inset(c.edge, c.box);
      for (var k = 0; k <= 12; k++) {
        var adv = k * (slide / 12);
        var p = { x: c.p0.x + c.ux * adv + off.x, y: c.p0.y + c.uy * adv + off.y };
        p.x = Math.min(Math.max(p.x, rect.x + c.box.w / 2 + 1), rect.x + rect.w - c.box.w / 2 - 1);
        p.y = Math.min(Math.max(p.y, rect.y + c.box.h / 2 + 1), rect.y + rect.h - c.box.h / 2 - 1);
        var r = { x0: p.x - c.box.w / 2, y0: p.y - c.box.h / 2,
                  x1: p.x + c.box.w / 2, y1: p.y + c.box.h / 2 };
        var inFrame = r.x0 >= rect.x - 1 && r.x1 <= rect.x + rect.w + 1 &&
                      r.y0 >= rect.y - 1 && r.y1 <= rect.y + rect.h + 1;
        var minGapHere = Infinity;
        boxes.forEach(function (q) {
          var g = Math.max(q.x0 - r.x1, r.x0 - q.x1, q.y0 - r.y1, r.y0 - q.y1);
          if (g < minGapHere) { minGapHere = g; }
        });
        res.push({ x: p.x, y: p.y, box: r, inFrame: inFrame, minGap: minGapHere, slid: k });
      }
      return res;
    }
    function take(c, cands) {                    // 首选"在框内且间距够"的，其次"间距最大"的
      var ok = cands.filter(function (p) { return p.inFrame && p.minGap >= gap; });
      if (ok.length) { return ok[0]; }
      var fit = cands.filter(function (p) { return p.inFrame; });
      var pool = fit.length ? fit : cands;
      var best = pool[0];
      pool.forEach(function (p) { if (p.minGap > best.minGap) { best = p; } });
      best.cramped = true;                       // ⚠ 硬挤：绝不丢弃标签（两侧集合恒等于可见线集合）
      return best;
    }
    // 顺序：5 的整数倍先占位（第 1 轮），其余按 G 升序填空位（第 2 轮）；**两轮都不丢**
    cand.forEach(function (c) {
      var got = take(c, candidates(c));
      boxes.push(got.box);
      out.push({ n: c.n, label: 'n*=' + c.n, x: got.x, y: got.y, box: got.box,
                 slid: got.slid, prio: c.prio, cramped: !!got.cramped });
      if (got.cramped) { cramped.push(c.n); }
    });
    return { labels: out, visible: cand.length, step: step, gap: gap, slide: slide,
             dropped: [], cramped: cramped };
  };

  /** 图2：β–ginv 散点 + 等 n* 线 + 标签。rows 来自目录条目，ref 来自目录的 reference。 */
  F.renderBg = function (svg, rows, style, ref, view) {
    var st = style || F.styleOf(null);
    var axis = F.bgAxis((rows || []).map(function (r) { return { beta: r.bc, ginv: r.ginv }; }));
    var rect = F.rectOf(view);
    clear(svg);
    frame(svg, rect, axis, st);
    var lines = F.nstarLines(axis, ref, st.nstar_levels);
    lines.forEach(function (L) {
      var a = F.project(rect, axis, L.x0, L.y0), b = F.project(rect, axis, L.x1, L.y1);
      el(svg, 'line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: st.nstar_color,
                        'stroke-width': 1, 'stroke-dasharray': '5 3' });
    });
    // 标签：数量由 nstar_label_step 决定（null ⇒ 全打），**位置**由 nstarLabelLayout 做错开+避让，
    // 全部落在框内、两两不重叠（2026-10-05：全打之后末端标签会挤成一团）。
    var layout = F.nstarLabelLayout(rect, axis, lines, st, { font: 9 });
    axis.nstarCramped = layout.cramped;      // 硬挤的 n* 标签（绝不丢弃，只是略挤）
    layout.labels.forEach(function (L) {
      el(svg, 'text', { x: L.x, y: L.y + 3, 'text-anchor': 'middle', fill: st.nstar_color,
                        'font-size': 9, 'class': 'nstar-lbl', 'data-n': L.n }, L.label);
    });
    var items = (rows || []).map(function (r) {
      return { key: r.key, label: r.label || r.key, x: +r.bc, y: +r.ginv,
               color: (st.base && r.key === st.base) ? st.base_color : st.point_color,
               title: (r.full_name || r.key) + '　β=' + (+r.bc).toFixed(1)
                      + '，ginv=' + (+r.ginv).toFixed(5) };
    });
    dots(svg, items, axis, rect, st);
    drawLabels(svg, items, axis, rect, st);
    axisTitles(svg, rect, st, st.xlabel_bg, st.ylabel_bg);
    return axis;
  };

  // ============================================================ ⑥ 壳调用的门面（冻结接口）
  /**
   * 挂载到 host（一个空的 div）：内部建 svg + 图注 ul。
   *
   * 返回 {setSelection(keys), redraw()}：keys 是目录里的 key 数组（壳管选择、壳管存储）。
   * 空数组 ⇒ 只画轴（清空是合法状态，不偷偷回落）；认不出的 key 直接忽略。
   * 整条路径不发请求、不落任何状态（选择由壳管）。
   */
  F.mount = function (host, opts) {
    if (!host || typeof document === 'undefined') { throw new Error('mount 需要 DOM 宿主'); }
    opts = opts || {};
    var kind = (opts.kind === 'bg') ? 'bg' : 'plane';
    var catalog = opts.catalog || {};
    var notes = (opts.notes || []).map(function (t) { return String(t); });
    var st = F.styleOf(catalog);
    st.base = st.base || String(catalog.standard || '');
    var entries = F.drawableEntries(catalog);
    var sel = entries.filter(function (m) { return m.in_pool11; });
    if (!sel.length) { sel = entries.slice(); }               // 目录里没有池内 11 弹时：全画

    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + F.VIEW.w + ' ' + F.VIEW.h);
    svg.setAttribute('class', 'figs2d');
    svg.setAttribute('role', 'img');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    var ul = document.createElement('ul');
    ul.className = 'figs2d-notes';
    clear(host);
    host.appendChild(svg);
    if (notes.length) { host.appendChild(ul); }

    function paintNotes() {
      clear(ul);
      notes.forEach(function (t) {
        var li = document.createElement('li');
        li.textContent = t;
        ul.appendChild(li);
      });
    }
    function draw() {
      if (kind === 'bg') {
        F.renderBg(svg, sel, st, catalog.reference);
      } else {
        F.renderPlane(svg, sel, st);
      }
    }
    try {
      draw();
    } catch (err) {                                          // 少一件/坏一件都不该把页面打挂
      clear(svg);
      el(svg, 'text', { x: 12, y: 20, fill: st.text, 'font-size': 12 },
         String((err && err.message) || err));
    }
    paintNotes();
    return {
      setSelection: function (keys) {
        var want = {};
        (keys || []).forEach(function (k) { want[String(k)] = 1; });
        sel = entries.filter(function (m) { return want[m.key]; });
        try { draw(); } catch (err) { /* 同上：只提示，不抛给壳 */ }
      },
      redraw: function () { try { draw(); } catch (err) { /* 同上 */ } paintNotes(); }
    };
  };

  if (typeof module !== 'undefined' && module.exports) { module.exports = F; }
  global.FIGS2D = F;
})(typeof window !== 'undefined' ? window : globalThis);

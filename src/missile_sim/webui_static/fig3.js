/* 图3 的静态版渲染器（零后端、零第三方、手写 WebGL2）。
 *
 * 与旧版的区别（Static 分支）：旧版从后端接口取载荷（标称点坐标、轴域、逐列拟合、等时面层、
 * 角部光晕…），静态站**没有后端**，所以这一版：
 *   · 点：每枚弹的 (ΔV, β, ginv) 直接来自 `catalog`（`missiles[].dv/bc/ginv`，β≡bc）；
 *   · 轴：三根轴的自适应域与 `figures.fig3_axes()` **同口径**（ΔV 走图1 的 `_one_axis(...,"x")`，
 *     β/ginv 走图2 的 `bg_axis`：pad 0.06、下限 60 与 9e-4），由 `tests/test_fig3_static.py`
 *     的 node 探针与 Python（或 `--axes --figure fig3` 的 oracle）逐值比对；
 *   · 等时面 / 层 / 逐列拟合 / 角部光晕一律不做（都需要求解器），代码里也没有留半截路径。
 *   · 不做命中/脱靶判定、同色同形、不放那个图例（判定需要解算，静态层没有求解器）。
 *
 * 硬约束：零网络请求（源码里连 fetch 调用都没有）、不落任何浏览器存储、不写文案（轴名等由壳通过
 * `style` 给，没给就不画）、配色只来自 `style` 或 `fig3.css` 的 CSS 变量 —— 本文件里零颜色字面量。
 *
 * 冻结接口（壳按这个挂；形状别改）：
 *
 *     window.FIG3STATIC = {
 *       mount(host, {catalog, style}) {
 *         return { setSelection(keys) {...}, redraw() {} };
 *       }
 *     };
 */
(function (global) {
  'use strict';

  // ============================================================ 轴口径（对齐 figures.fig3_axes）
  var PAD_FRAC = 0.06, MIN_PAD = { x: 12.0, y: 60.0 };
  var DEFAULT_XLIM = [800.0, 1110.0], DEFAULT_YLIM = [2450.0, 3850.0];
  var DEFAULT_TICKS = { x: [30.0, 10.0], y: [100.0, 50.0] };
  var BG_PAD = 0.06, BG_MIN_PAD = { x: 60.0, y: 9e-4 };

  function roundN(v, n) { var f = Math.pow(10, n); return Math.round(v * f) / f; }

  function niceTick(span, target) {
    var raw = Math.max(Number(span), 1e-9) / Math.max(Number(target) | 0, 1);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var cand = [1.0, 2.0, 2.5, 5.0, 10.0];
    for (var i = 0; i < cand.length; i++) {
      if (raw <= cand[i] * mag * (1 + 1e-9)) { return cand[i] * mag; }
    }
    return 10.0 * mag;
  }
  function minorFor(major) { return (major / 5.0 >= 5e-3) ? major / 5.0 : major / 2.0; }

  /** 刻度**复用 figs2d.js 的同一个实现**（Lead 2026-10-05：图3 三轴别复制第二份）。
   *  `/fig3` 那一页要多引一行 `./figs2d.js`（壳那边一行；静态首页已经引了）。 */
  function ticksOf(lo, hi) {
    var T = global.FIGS2D && global.FIGS2D.ticks;
    if (!T) {
      throw new Error('图3 的刻度复用 figs2d.js 的 FIGS2D.ticks：请在本页也引入 ./figs2d.js');
    }
    return T(lo, hi);
  }
  function oneAxis(vals, axis) {
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var pad = Math.max((hi - lo) * PAD_FRAC, MIN_PAD[axis]);
    var a = lo - pad, b = hi + pad;
    var t = ticksOf(a, b);                        // ⚠ 范围算法不变，只换刻度
    return { lim: [a, b], major: t.step, minor: t.minor, decimals: t.decimals };
  }

  function bgAxis(rows) {
    var bs = rows.map(function (r) { return +r.beta; });
    var gs = rows.map(function (r) { return +r.ginv; });
    var b0 = Math.min.apply(null, bs), b1 = Math.max.apply(null, bs);
    var g0 = Math.min.apply(null, gs), g1 = Math.max.apply(null, gs);
    var bp = Math.max((b1 - b0) * BG_PAD, BG_MIN_PAD.x);
    var gp = Math.max((g1 - g0) * BG_PAD, BG_MIN_PAD.y);
    var xlim = [b0 - bp, b1 + bp], ylim = [g0 - gp, g1 + gp];
    var tx = ticksOf(xlim[0], xlim[1]), ty = ticksOf(ylim[0], ylim[1]);   // 同一个实现
    return { xlim: [roundN(xlim[0], 6), roundN(xlim[1], 6)],
             ylim: [roundN(ylim[0], 6), roundN(ylim[1], 6)],
             x_major: tx.step, x_minor: tx.minor, x_decimals: tx.decimals,
             y_major: ty.step, y_minor: ty.minor, y_decimals: ty.decimals };
  }

  /** 三根轴的域（= `figures.fig3_axes()`：ΔV 走图1 口径、β/ginv 走图2 口径）。 */
  function fig3Axes(rows) {
    var rws = (rows || []).filter(function (r) {
      return r && isFinite(+r.dv) && isFinite(+r.bc) && isFinite(+r.ginv);
    });
    if (!rws.length) { throw new Error('fig3_axes 至少需要一行数据'); }
    var dv = oneAxis(rws.map(function (r) { return +r.dv; }), 'x');
    var bg = bgAxis(rws.map(function (r) { return { beta: +r.bc, ginv: +r.ginv }; }));
    return { dv: [roundN(dv.lim[0], 3), roundN(dv.lim[1], 3)],
             beta: [bg.xlim[0], bg.xlim[1]], ginv: [bg.ylim[0], bg.ylim[1]],
             dv_major: dv.major, beta_major: bg.x_major, ginv_major: bg.y_major };
  }

  /** 域内主刻度（**端点必须在首尾**：`dataPos` 拿首尾当归一化范围）。 */
  function ticksIn(lo, hi, major) {
    var out = [lo], v = Math.ceil(lo / major) * major;
    for (; v < hi; v += major) { if (v > lo + 1e-9) { out.push(roundN(v, 9)); } }
    out.push(hi);
    return out;
  }

  // ============================================================ 风格（style 优先，其次 CSS 变量）
  function cssVar(name) {
    var root = global.document && global.document.documentElement;
    if (!root || !global.getComputedStyle) { return ''; }
    return (global.getComputedStyle(root).getPropertyValue(name) || '').trim();
  }
  /** 取一个颜色：`style` → CSS 变量 → **报错**（不写死任何色值，见文件头那条约束）。 */
  function pickColor(style, key, cssName) {
    var v = (style && style[key]) || cssVar(cssName);
    if (!v) {
      throw new Error('缺配色：style.' + key + ' 或 CSS 变量 ' + cssName + '（fig3.css）');
    }
    return v;
  }
  /** 取一个数值：`style` → CSS 变量 → **报错**（与 pickColor 同口径，不写死）。 */
  function pickNum(style, key, cssName) {
    var v = (style && style[key] !== undefined) ? style[key] : cssVar(cssName);
    var n = Number(v);
    if (!isFinite(n)) {
      throw new Error('缺数值：style.' + key + ' 或 CSS 变量 ' + cssName + '（fig3.css）');
    }
    return n;
  }

  function styleOf(style, catalog) {
    var s = style || {};
    return {
      point: pickColor(s, 'point_color', '--fig3-point'),
      base: pickColor(s, 'base_color', '--fig3-base'),
      box: pickColor(s, 'box_color', '--fig3-box'),
      bg: pickColor(s, 'bg_color', '--fig3-bg'),
      text: pickColor(s, 'text_color', '--fig3-text'),
      axis: { dv: pickColor(s, 'axis_dv', '--fig3-axis-dv'),
              beta: pickColor(s, 'axis_beta', '--fig3-axis-beta'),
              ginv: pickColor(s, 'axis_ginv', '--fig3-axis-ginv') },
      labels: { dv: s.label_dv || '', beta: s.label_beta || '', ginv: s.label_ginv || '' },
      halo: {
        good: pickColor(s, 'halo_good', '--fig3-halo-good'),
        bad: pickColor(s, 'halo_bad', '--fig3-halo-bad'),
        base: pickColor(s, 'halo_base', '--fig3-halo-base'),
        alpha: pickNum(s, 'halo_alpha', '--fig3-halo-alpha'),
        radius: pickNum(s, 'halo_radius', '--fig3-halo-radius'),
        power: pickNum(s, 'halo_power', '--fig3-halo-power')
      },
      baseKey: s.base || (catalog && catalog.standard) || '',
      // 默认视角：style.view 优先；否则用与 figures.FIG3_VIEW_AZ/EL 对齐的兜底（角度是数值，不是文案）
      view: s.view || { az: -1.25, el: 0.34 }
    };
  }
  // ⚠ viewer 认的 d.colors 是**十六进制字符串**（老代码用 needColor() 现转三元组）；
  //   这里不能先转数组 —— 那样 needColor() 会判成配色缺失（踩过一次）。
  function colorsOf(st) {
    return { point: st.point, base: st.base, box: st.box, bg: st.bg, text: st.text,
             axis: { dv: st.axis.dv, beta: st.axis.beta, ginv: st.axis.ginv },
             // 角部光晕：颜色/数值都来自 style 或 fig3.css（本文件零颜色字面量）
             halo: { good: st.halo.good, bad: st.halo.bad, base: st.halo.base,
                     alpha: st.halo.alpha, radius: st.halo.radius, power: st.halo.power } };
  }

  // ============================================================ 合成模型（catalog → viewer 认的 d）
  function drawableEntries(catalog) {
    return ((catalog && catalog.missiles) || []).filter(function (m) {
      if (!m || m.duplicate_of || m.default_hidden) { return false; }
      return isFinite(+m.dv) && isFinite(+m.bc) && isFinite(+m.ginv);
    });
  }
  function modelOf(catalog, keys, st) {
    var ent = drawableEntries(catalog);
    var want = null;
    if (keys) { want = {}; keys.forEach(function (k) { want[String(k)] = 1; }); }
    var pts = want ? ent.filter(function (m) { return want[m.key]; }) : ent;
    // 空集也要有个确定的取景框：用"全部可画条目"的域（不随选择跳变）
    var ax = fig3Axes(pts.length ? pts : ent);
    return {
      points: pts.map(function (m) {
        return { key: m.key, label: m.label || m.key, full_name: m.full_name || m.key,
                 dv: +m.dv, beta: +m.bc, ginv: +m.ginv };
      }),
      baseKey: st.baseKey,
      axes: [{ id: 'dv', role: 'x', lim: ax.dv }, { id: 'beta', role: 'y', lim: ax.beta },
             { id: 'ginv', role: 'z', lim: ax.ginv }],
      grid: { dv: ticksIn(ax.dv[0], ax.dv[1], ax.dv_major),
              beta: ticksIn(ax.beta[0], ax.beta[1], ax.beta_major),
              ginv: ticksIn(ax.ginv[0], ax.ginv[1], ax.ginv_major) },
      colors: colorsOf(st),
      labels: st.labels,
      view: st.view,
      axesSpec: ax
    };
  }

  // ============================================================ 标签避让（纯函数，node 可测）
  function estimateBox(text, fontPx) {
    var f = fontPx || 11;
    return { w: 0.62 * f * String(text).length + 4.0, h: f * 1.35 };
  }
  function overlaps(a, b) {
    return !(a.x1 <= b.x0 || b.x1 <= a.x0 || a.y1 <= b.y0 || b.y1 <= a.y0);
  }
  /** `items=[{key,label,x,y}]`（屏幕坐标）→ `[{key,label,tx,ty,box,kept}]`（贪心，放不下就不标）。 */
  function placeLabels3D(items, rect, opt) {
    opt = opt || {};
    var font = +opt.font || 11, pad = +opt.pad || 8;
    var src = (items || []).map(function (it) {
      var box = estimateBox(it.label, font);
      return { key: it.key, label: it.label, px: +it.x, py: +it.y, w: box.w, h: box.h };
    });
    var order = src.map(function (it, i) { return i; }).sort(function (a, b) {
      return (src[a].py - src[b].py) || (a - b);
    });
    var dirs = [[1, 0], [0, -1], [-1, 0], [0, 1], [1, -1], [-1, -1], [1, 1], [-1, 1]];
    var radii = [font + pad, font * 2.6 + pad];
    var placed = [];
    var res = src.map(function (it) {
      return { key: it.key, label: it.label, tx: it.px, ty: it.py, box: null, kept: false };
    });
    order.forEach(function (idx) {
      var it = src[idx], best = null;
      radii.forEach(function (r) {
        dirs.forEach(function (dir) {
          var cx = (dir[0] === 0) ? it.px : it.px + dir[0] * (r + it.w / 2);
          var cy = (dir[1] === 0) ? it.py : it.py + dir[1] * (r + it.h / 2);
          var box = { x0: cx - it.w / 2, x1: cx + it.w / 2, y0: cy - it.h / 2, y1: cy + it.h / 2 };
          var score = 0;
          placed.forEach(function (b) { if (overlaps(box, b)) { score += 1000; } });
          src.forEach(function (o) {
            if (o !== it && Math.hypot(o.px - cx, o.py - cy) < 6) { score += 300; }
          });
          if (rect && (box.x0 < rect.x - 2 || box.x1 > rect.x + rect.w + 2 ||
                       box.y0 < rect.y - 2 || box.y1 > rect.y + rect.h + 2)) { score += 1000; }
          score += Math.hypot(cx - it.px, cy - it.py) * 0.6;
          if (!best || score < best.score) { best = { score: score, box: box, tx: cx, ty: cy }; }
        });
      });
      if (best && best.score < 1000) {
        placed.push(best.box);
        var slot = res[idx];
        slot.tx = best.tx; slot.ty = best.ty; slot.box = best.box; slot.kept = true;
      }
    });
    return res;
  }

  // ============================================================ 门面（冻结接口）
  function mount(host, opts) {
    if (!host || typeof document === 'undefined') { throw new Error('mount 需要 DOM 宿主'); }
    opts = opts || {};
    var catalog = opts.catalog || {};
    var st = styleOf(opts.style, catalog);
    var cv = document.createElement('canvas');
    cv.className = 'fig3static';
    var ov = document.createElement('div');
    ov.className = 'fig3-labels';
    host.textContent = '';
    if (!host.style.position) { host.style.position = 'relative'; }
    host.appendChild(cv);
    host.appendChild(ov);
    var gl = cv.getContext('webgl2', { antialias: true });
    if (!gl) {
      var msg = document.createElement('div');
      msg.className = 'fig3-fail';
      msg.textContent = '本浏览器或当前环境不支持 WebGL2';
      host.appendChild(msg);
      return { setSelection: function () { }, redraw: function () { } };
    }

    var cam0 = { az: null, el: null, pan: [0, 0, 0], dist: 3.2 };
    var d = null, v = null;

    function resize() {
      var dpr = Math.min(global.devicePixelRatio || 1, 2);
      var w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
      if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) {
        cv.width = w; cv.height = h;
        if (v) { v.fit(cv.width / Math.max(cv.height, 1)); }
      }
    }
    function keepCam() {
      if (!v) { return; }
      cam0.az = v.cam.az; cam0.el = v.cam.el;
      cam0.pan = v.cam.pan.slice(); cam0.dist = v.cam.dist;
    }
    function build() {
      keepCam();
      var view = { az: (st.view && st.view.az !== undefined) ? st.view.az : cam0.az,
                   el: (st.view && st.view.el !== undefined) ? st.view.el : cam0.el };
      d = modelOf(catalog, state.keys, st);
      d.view = view;
      v = viewer(gl, d, { transparent: true });
      v.setMissile(st.baseKey || "");        // 必须真建一次点云（不调则一个点都不画，旧代码注释警告过）
      if (cam0.az !== null) { v.cam.az = cam0.az; v.cam.el = cam0.el; v.cam.pan = cam0.pan.slice(); }
      v.cam.dist = cam0.dist || 3.2;
      resize();
      v.fit(cv.width / Math.max(cv.height, 1));
    }
    var state = { keys: ((catalog.missiles || []).filter(function (m) { return m.in_pool11; })
                     .map(function (m) { return m.key; })) };

    cv.addEventListener('pointerdown', function (e) {
      try { cv.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      var x0 = e.clientX, y0 = e.clientY;
      cv.classList.add('drag');
      function move(ev) {
        var dx = ev.clientX - x0, dy = ev.clientY - y0;
        x0 = ev.clientX; y0 = ev.clientY;
        if (ev.shiftKey || ev.buttons === 2 || ev.buttons === 4) { applyPan(v.cam, dx, dy); }
        else { applyDrag(v.cam, dx, dy); }
      }
      function up() {
        cv.classList.remove('drag');
        cv.removeEventListener('pointermove', move);
        cv.removeEventListener('pointerup', up);
        cv.removeEventListener('pointercancel', up);
      }
      cv.addEventListener('pointermove', move);
      cv.addEventListener('pointerup', up);
      cv.addEventListener('pointercancel', up);
    });
    cv.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    cv.addEventListener('wheel', function (e) {
      e.preventDefault();
      v.cam.dist = Math.max(1.6, Math.min(9.0, v.cam.dist * (e.deltaY > 0 ? 1.08 : 0.93)));
    }, { passive: false });
    cv.addEventListener('dblclick', function () {
      if (AZ0 !== null) { v.cam.az = AZ0; }
      if (EL0 !== null) { v.cam.el = EL0; }
      v.cam.pan = [0, 0, 0];
      v.fit(cv.width / Math.max(cv.height, 1));
    });

    function paintLabels() {
      ov.textContent = '';
      if (!v || !d) { return; }
      var W = cv.clientWidth || 1, H = cv.clientHeight || 1;
      var stats = v.stats();
      var items = (d.points || []).map(function (p) {
        var s = projectToScreen(dataPos(d, p.beta, p.ginv, p.dv), v.cam, stats.center, stats.radius,
                                W, H, 0.9);
        var xy = (s && s.x !== undefined) ? s : { x: s && s[0], y: s && s[1] };
        return { key: p.key, label: p.label || p.key, x: xy.x, y: xy.y };
      }).filter(function (it) { return isFinite(it.x) && isFinite(it.y); });
      placeLabels3D(items, { x: 0, y: 0, w: W, h: H }, { font: 11, pad: 8 }).forEach(function (p, i) {
        if (!p.kept) { return; }
        var node = document.createElement('span');
        node.className = 'fig3-lbl';
        node.textContent = p.label;
        node.style.left = Math.round(p.tx) + 'px';
        node.style.top = Math.round(p.ty) + 'px';
        node.style.color = (items[i].key === st.baseKey) ? st.base : st.point;
        ov.appendChild(node);
      });
    }
    var last = (global.performance || Date).now();
    function frame(now) {
      var dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      resize();
      if (v) { v.tick(dt); v.draw(); paintLabels(); }
      global.requestAnimationFrame(frame);
    }

    build();
    if (global.ResizeObserver) {
      new global.ResizeObserver(function () { resize(); }).observe(host);
    }
    global.requestAnimationFrame(frame);
    return {
      setSelection: function (keys) { state.keys = (keys || []).slice(); build(); },
      redraw: function () { build(); },
      stats: function () { return v ? v.stats() : null; },
      axes: function () { return d ? d.axesSpec : null; }
    };
  }

  // ============================================================ 角部光晕（纯几何 + 常量，静态可算）
  // 用户 2026-10-05 口径："图3 加上原有的红绿标出好区、坏区，这肯定是能静态的" —— 对：
  // 好角 = 三轴最大角、坏角 = 三轴最小角（我们三根轴都是"越大越好"，见 figures.FIG3_AXIS_BETTER），
  // 每角 3 块面（共 6 块），从角色向外按幂律衰减到白底。几何/衰减曲线/峰值 alpha 与 886eccf
  // 那版**逐字相同**，只把**颜色来源**从响应换成 fig3.css 的 CSS 变量（本文件仍然零颜色字面量）。
  var HALO_FACES_PER_CORNER = 3;
  /** 每角 3 块面：固定一根轴在 ±0.5，另两轴在面上取 ±0.5 —— 与旧响应里的 faces 同构。 */
  function haloFaces(good) {
    var at = good ? 0.5 : -0.5;
    return [0, 1, 2].map(function (slot) { return { slot: slot, at: at }; });
  }
  /** 光晕参数：角写死（三轴 max / min），颜色与 alpha 来自 `d.colors.halo`（源头是 fig3.css）。 */
  function haloParams(d) {
    var c = ((d || {}).colors || {}).halo || {};
    function need(key) {
      if (!c[key]) { throw new Error('缺光晕配色：fig3.css 的 CSS 变量 --fig3-halo-' + key); }
      return c[key];
    }
    var alpha = Number(c.alpha);
    if (!(alpha >= 0)) { throw new Error('缺 --fig3-halo-alpha（fig3.css）'); }
    var radius = Number(c.radius), power = Number(c.power);
    if (!(radius > 0)) { throw new Error('缺 --fig3-halo-radius（fig3.css）'); }
    if (!(power > 0)) { throw new Error('缺 --fig3-halo-power（fig3.css）'); }
    return { good: [0.5, 0.5, 0.5], bad: [-0.5, -0.5, -0.5], radius: radius, power: power,
             alpha: alpha,
             goodRGB: hex2rgb(need('good')), badRGB: hex2rgb(need('bad')),
             baseRGB: hex2rgb(need('base')),
             faces: haloFaces(false).concat(haloFaces(true)),
             facesPerCorner: HALO_FACES_PER_CORNER };
  }
  /** 光晕体：**几何逐字取自 886eccf**（6 块四边形 → 每块 2 个三角形），只换参数来源。 */
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

    function mixRGB(a, b, w) {
    return [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w, a[2] + (b[2] - a[2]) * w];
  }

    function haloWeight(p, corner, radius, power) {
    var dx = p[0] - corner[0], dy = p[1] - corner[1], dz = p[2] - corner[2];
    var t = 1 - Math.sqrt(dx * dx + dy * dy + dz * dz) / (radius || 1);
    if (t <= 0) return 0;
    return Math.pow(t, power);
  }

    function haloColorAt(p, params) {
    var wb = haloWeight(p, params.bad, params.radius, params.power);
    var wg = haloWeight(p, params.good, params.radius, params.power);
    var c = mixRGB(params.baseRGB, params.badRGB, wb);
    c = mixRGB(c, params.goodRGB, wg);
    return [c[0], c[1], c[2], params.alpha * Math.max(wb, wg)];
  }

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

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { fig3Axes: fig3Axes, placeLabels3D: placeLabels3D, oneAxis: oneAxis,
                       niceTick: niceTick, minorFor: minorFor, ticksIn: ticksIn,
                       drawableEntries: drawableEntries, modelOf: modelOf, mount: mount,
                       haloFaces: haloFaces, haloParams: haloParams, haloBuffers: haloBuffers,
                       haloColorAt: haloColorAt, haloWeight: haloWeight, mixRGB: mixRGB,
                       colorsOf: colorsOf, styleOf: styleOf };
  }
  global.FIG3STATIC = { mount: mount, fig3Axes: fig3Axes, placeLabels3D: placeLabels3D,
                        oneAxis: oneAxis, niceTick: niceTick, minorFor: minorFor };
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
  //   绝不写 `colors.x || 某个写死的色值` —— 本文件的判据就是"零颜色字面量"，
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
  // ⚠ 名字保留 `cloudColors`：`drawColorbar` / `hud` / `showLayer` 三处调用点共用它，
  //   返回形状（hit / miss / hitIdx / missIdx / domain / unit / label / note）也保持不变。
  function cloudColors(d) {
    var colors = d.colors || {};
    return { points: d.points || [], label: "", unit: "", note: "",
             point: needColor(colors, "point"), base: needColor(colors, "base") };
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

  // **纯函数**：不碰 WebGL、不读全局（Node 侧自检直接喂数据就能验）。
  // 每个三角形独立顶点 + 用面法线做一次假光照（flat shading），所以不需要新的着色器。

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
  // 三块面 = 背对默认相机的那三块（后壁 ×2 + 底面），每块两个三角形；颜色**在片元里按世界坐标
  // 到两个角的三维距离**算 ⇒ 等色线在面上是圆弧（不是分区涂色、也不是贴一张渐变图）。
  // **纯函数**：Node 侧自检直接喂世界坐标就能验（WebGL 那部分只是把同一个式子搬进 GLSL）。
  // **六个面** → 可以直接 `upload()` 的缓冲规格（每个角恰好被三块面共用 ⇒ 两团对称；
  // 顶点颜色只是占位，真色在片元里算）。

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
    "  v_world = a_pos;",   // ⚠ 光晕的 FS 要读世界坐标：少了这一行 v_world 就是未定义值（=0）⇒ 光晕算出来 alpha≈0（2026-10-05 修）
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
  var FS_RING = ["#version 300 es", "precision mediump float;",
    "in vec3 v_col; out vec4 outColor;",
    "void main() {",
    "  float r = length(gl_PointCoord - vec2(0.5));",
    "  if (r > 0.5 || r < 0.30) discard;",
    "  outColor = vec4(v_col, 1.0);",
    "}"].join("\n");
  // 这里一个颜色字面量都没有（判据扫这个文件）。

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
    var halo = haloBuffers(d);           // 角部光晕：纯几何 + CSS 变量，静态可算
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
      // 全部点走同一个 disc 程序；B_MISS 恒空（保留缓冲只为统计口径一致）。
      var pos = [], col = [], idx = [];
      var pts = d.points || [];
      var baseKey = d.baseKey || "";
      for (var i = 0; i < pts.length; i++) {
        var it = pts[i];
        var p = dataPos(d, it.beta, it.ginv, it.dv);
        var c = (baseKey && it.key === baseKey) ? needColor(colors, "base") : needColor(colors, "point");
        pos.push(p[0], p[1], p[2]);
        col.push(c[0], c[1], c[2]);
        idx.push(idx.length);
      }
      var sz = [];
      for (var j = 0; j < idx.length; j++) { sz.push(0.020); }
      B_HIT = uploadBuf({ pos: pos, col: col, size: sz, idx: idx }, L_DISC, B_HIT);
      B_MISS = uploadBuf({ pos: [], col: [], size: [], idx: [] }, L_RING, B_MISS);
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
      [B_BOX, B_HALO, B_HIT, B_MISS].forEach(function (b) {
        b.mvp = MVP; b.mv = V;
      });
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      //    放到后面画或者写深度都会**挡点**（那是判据里明令禁止的）。


      // ② 盒子（不透明线）
      gl.useProgram(P_SOLID);
      gl.uniform1f(L_SOLID.alpha, 0.85);
      if (showAxes) { bind(B_BOX, P_SOLID); gl.drawElements(gl.LINES, B_BOX.count, gl.UNSIGNED_INT, 0); }
      // 角部光晕：**先画光晕、再画点**（写深度的时段严格夹在中间，绝不遮点）
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
      if (B_HIT.count) {
        B_HIT.alpha = 1.0;
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
      setFlags: function (o) {
        if (o.axes !== undefined) showAxes = !!o.axes;
      },
      cloudInfo: function () { return { points: (d.points || []).length, label: "", unit: "" }; },
      get spinning() { return spinning; },
      set spinning(v) { spinning = !!v; },
      stats: function () {
        return { points: B_HIT.count + B_MISS.count, lines: B_BOX.count,
                 radius: radius, center: center };
      },
      tick: function (dt) { if (spinning) cam.az += dt * 0.35; },
    };
  }

  /* =================================================== 色标图例（2D canvas） */

  /* ============================================== β–ginv 热力图（2D canvas） */

  /* ==================================================================== 引导 */

  // 11 个弹名**常显**（不靠悬停）：每帧把名字贴到该点的投影位置，并做**最小的上下错开** ——
  // 挤在一起时把后面的往下推，保证没有两个标签重叠。




})(typeof window !== "undefined" ? window : globalThis);

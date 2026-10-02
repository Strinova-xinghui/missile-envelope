// spike (e)：**拖动方向"跟手"自检**（不依赖浏览器，直接复用 viewer 里那份真实代码）。
//
//   node spikes/fig3d/spike_d_drag.js
//
// 用户 2026-10-01 的硬要求：3D 视图水平拖动必须"跟手"（抓住物体转），
// 明确点名 https://jari-aerospace.top/ 那种"拖右而物体左转"的镜像手感是要避免的反例。
//
// 做法：把 viewer 的 `applyDrag`（**唯一**改方位角/仰角的地方）+ `projectToScreen`
// （与 `draw()` 同一套矩阵口径）搬出来，对每个见证点各量一次屏幕位移：
//   dx@±20px、dy@±20px（**判据**：小拖拽方向必须与光标一致）、dx@+200px（用户给的量级）。
//
// ⚠ 见证点怎么选是这个 spike 里最容易搞错的一步（第一版就搞错了）：
//   环绕相机绕 `center` 的**竖直轴**转，离轴越远的点位移方向越可能反向 ——
//   相机在 39 km 外，轨道中心**后方**的点仍在相机前方、仍能投出来，只是 u/w 换了号。
//   拿"发射点"当见证会得出**相反的结论**（本文件把它作为参考行打印出来，
//   实测 dx@+20px = −57.2，而正对观察者的近侧表面是 +8.9）。所以判据只落在
//   物体**正对观察者的近侧表面**与**弹道上最靠近视野中心的点**上。
//
// 输出固定格式，`tests/test_fig3d_spike.py` 断言 `DRAG ... ok=1`。
"use strict";
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "fig3d_viewer.html"), "utf8");
const js = html.split("<script>")[1].split("</script>")[0];
const cut = js.indexOf("/* ==================================================================== main */");
if (cut < 0) throw new Error("找不到 main 分隔标记，viewer 结构变了");
const core = js.slice(0, cut);
const data = JSON.parse(fs.readFileSync(
  path.join(__dirname, "out", "c", "data.slim.json"), "utf8"));

const fn = new Function("window", "location", "document", core +
  "\nreturn { M4, buildGeometry, applyDrag, projectToScreen, dragFollowCheck," +
  " formatDragCheck, AZ_PER_PX, EL_PER_PX, EL_LIMIT, THEME };");
const api = fn({}, { search: "" }, { getElementById: () => null });

// ---- 复刻 viewer 的初始相机（默认方位角/仰角 + `fit()` 自适应距离） ----
const W = 1280, H = 800, FOVY = 0.9, SMALL = 20, LARGE = 200;
const G = api.buildGeometry(data);
const b = G.bounds;
const radius = 0.5 * Math.hypot(b.mxx - b.mnx, Math.max(b.mxy - b.mny, 1), b.mxz - b.mnz);
const center = [(b.mnx + b.mxx) / 2, (b.mny + b.mxy) / 2, (b.mnz + b.mxz) / 2];
const need = radius / Math.tan(FOVY / 2);
const dist = Math.max(need, need / Math.max(W / H, 0.2)) * 0.72;
const cam0 = { az: -1.05, el: 0.36, dist, pan: [0, 0, 0] };

console.log(`# viewer: 手写 WebGL2  camera az=${cam0.az} el=${cam0.el} dist=${dist.toFixed(1)} m`
  + `  canvas ${W}x${H} fovy=${FOVY}`);
console.log(`# 轨道中心 = (${center.map(v => v.toFixed(1)).join(", ")})  半径 = ${radius.toFixed(1)} m`);
console.log(`# 转率 AZ_PER_PX=${api.AZ_PER_PX} rad/px ⇒ 拖 ${LARGE}px = `
  + `${(LARGE * api.AZ_PER_PX * 180 / Math.PI).toFixed(1)}°，EL_LIMIT=${api.EL_LIMIT} rad`);
const rows = api.dragFollowCheck(data, cam0, center, radius, W, H, SMALL, LARGE);
console.log(api.formatDragCheck(rows, SMALL, LARGE));

// ---- 对照：把 az 的符号写反（= 旧实现 / 镜像手感），看看会差成什么样 ----
{
  const mirror = (sign) => ({ az: cam0.az + sign * LARGE * api.AZ_PER_PX, el: cam0.el,
                              dist, pan: [0, 0, 0] });
  const dirv = [Math.cos(cam0.el) * Math.cos(cam0.az), Math.sin(cam0.el),
                Math.cos(cam0.el) * Math.sin(cam0.az)];
  const witness = center.map((v, i) => v + dirv[i] * 0.2 * radius);
  const x = (c) => api.projectToScreen(witness, c, center, radius, W, H).x;
  const x0 = x({ ...cam0, pan: [0, 0, 0] });
  console.log(`# 对照 a 正对观察者的近侧表面  dx@+${LARGE}px：`
    + `az +=（现在的实现）= ${(x(mirror(+1)) - x0).toFixed(1)}  `
    + `az -=（旧实现/jari 那种镜像）= ${(x(mirror(-1)) - x0).toFixed(1)}`);
  const P = data.missile.p;
  for (const [name, pt] of [["发射点", P[0]], ["命中点", P[P.length - 1]]]) {
    const px = (c) => api.projectToScreen(pt, c, center, radius, W, H).x;
    const q0 = px({ ...cam0, pan: [0, 0, 0] });
    console.log(`# 对照 b ${name}（离轨道轴远，不作判据）  dx@+${LARGE}px：`
      + `az += = ${(px(mirror(+1)) - q0).toFixed(1)}   az -= = ${(px(mirror(-1)) - q0).toFixed(1)}`);
  }
}

// ---- 判据（同时要求水平与垂直四个方向都跟手） ----
const prim = rows.filter(r => r.primary);
const px = prim.filter(r => r.follow_x).length;
const py = prim.filter(r => r.follow_y).length;
const ok = prim.length > 0 && px === prim.length && py === prim.length;
console.log(`DRAG small_px=${SMALL} large_px=${LARGE} primary_witnesses=${prim.length} `
  + `follow_x_ok=${px}/${prim.length} follow_y_ok=${py}/${prim.length} ok=${ok ? 1 : 0}`);
process.exit(ok ? 0 : 1);

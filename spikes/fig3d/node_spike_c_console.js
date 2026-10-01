// spike (c) 的可重跑量测：**不依赖浏览器**，把 viewer 的纯函数段搬到 Node 里量。
//
//   node spikes/fig3d/node_spike_c_console.js
//
// 量三件事：
//   1) 顶点装配（buildGeometry）耗时 —— 每场想定的**前端 CPU 成本**；
//   2) 4x4 矩阵（M4.view × M4.persp × M4.mul）每帧耗时 —— 每帧 CPU 成本；
//   3) 顶点/POS+COLOR 缓冲的字节数 —— 显存占用。
// 输出固定格式、可被 tests/test_fig3d_spike.py 断言。浏览器端真渲染的结论另见
// docs/FIG3D-FEASIBILITY.md（本机 Edge + SwiftShader 无头截图取证）。
"use strict";
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "fig3d_viewer.html"), "utf8");
const js = html.split("<script>")[1].split("</script>")[0];
const cut = js.indexOf("/* ==================================================================== main */");
const core = js.slice(0, cut);
const data = JSON.parse(fs.readFileSync(
  path.join(__dirname, "out", "c", "data.slim.json"), "utf8"));

const fn = new Function("window", "location", "document",
  core + "\nreturn { M4, buildGeometry };");
const api = fn({}, { search: "" }, { getElementById: () => null });

// ---- 1) 装配 ----
{
  const t0 = process.hrtime.bigint();
  let G = null;
  for (let i = 0; i < 20; i++) G = api.buildGeometry(data);
  const ms = Number(process.hrtime.bigint() - t0) / 1e6 / 20;
  const nLine = G.line.pos.length / 3, nPt = G.pt.pos.length / 3, nAx = G.axis.pos.length / 3;
  const ok = G.line.col.length / 3 === nLine && G.pt.col.length / 3 === nPt
    && G.line.sizes.length === nLine && G.pt.sizes.length === nPt
    && G.axis.col.length / 3 === nAx && G.axis.sizes.length === nAx;
  console.log(`GEOM lines=${nLine} points=${nPt} axes=${nAx} idx=${G.li.length + G.pi.length + G.axi.length} ` +
              `assembled_ms=${ms.toFixed(3)} aligned=${ok ? 1 : 0}`);
  const nv = nLine + nPt + nAx, ni = G.li.length + G.pi.length + G.axi.length;
  const bytes = nv * 7 * 4;
  console.log(`GEOM buffer_bytes=${bytes} (pos+col+size 交错 7*float4, ${nv} 顶点) ` +
              `index_bytes=${ni * 4}`);
}

// ---- 2) 矩阵 ----
{
  // 相机距离取自动适配那一档（半径量级）：与真实视角同量级
  const d = 70000, cx = 35000, cy = 11000, cz = 7000;
  const t0 = process.hrtime.bigint();
  const N = 200000;
  let acc = 0;
  for (let i = 0; i < N; i++) {
    const V = api.M4.view(i * 1e-4, 0.36, d, cx, cy, cz);
    const P = api.M4.persp(0.9, 1.6, d * 0.01, d * 8);
    const MVP = api.M4.mul(P, V);
    acc += MVP[0];
  }
  const us = Number(process.hrtime.bigint() - t0) / 1e3 / N;
  console.log(`MATRIX per_frame_us=${us.toFixed(3)} (view+persp+mul, ${N} 次, acc=${acc.toFixed(1)})`);
}

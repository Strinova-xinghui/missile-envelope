# `spikes/fig3d/` —— 三张图 3D 化的可行性 spike

**结论、方案对比与完整数字见 [`docs/FIG3D-FEASIBILITY.md`](../../docs/FIG3D-FEASIBILITY.md)。**
本目录只是"证据可重跑"的部分。**本目录不属于生产路径**：`src/**`、`figures/**`、`results/**`
一个字节都没有被它改动。

## 一句话结论

* **只有 图3 该 3D**：静态交付用 `matplotlib` mplot3d（零新依赖、三格式字节可复现），
  交互探索用手写 **WebGL2**（零第三方 JS、整页 55 kB、离线可用）。
* **图1 / 图2 不值得**：它们的第三维（`t_hit`）已经被**等时线 + 颜色条**完整表达，
  转成 3D 只增加遮挡与体积（图1 PNG 209 → 527 kB），信息量不变。
* **plotly 否决**：包 56.1 MB、`plotly.min.js` 4.8 MB、还要新运行时依赖（`narwhals`）。
* **两条交互硬要求（用户 2026-10-01）**：拖动必须**跟手**（拖右 ⇒ 物体朝右走，不许镜像）、
  chrome 走**亮色**。都在 spike 里做完且有机器判据 —— 见 `docs/FIG3D-FEASIBILITY.md` §3.5。

## 这份 spike 的结论**已被采纳**（2026-10-01，图3 静态 3D 已落地）

用户裁决：图3 的静态交付图**替换**成 3D 斜视（不并存），并要求保留关键点位注释与阶段配色、
新增"导弹到达开机距离后换色"、去掉左下角放大 inset。生产改动在 `src/missile_sim/figures.py`
（`plot_traj` + 新增 `_style_view3d` / `_place_label3d` / `_proj_frac` / `_text_bbox_px`）与
`tests/test_traj_plot.py`（删 8 条 inset 判据、加 3 条 3D 判据），口径与实测见
`docs/PLAN-FIG3-TRAJECTORY.md` §11。

⚠ **本目录的样本仍是 spike 的旧参数**（`az=-1.05 rad / el=0.36 rad` 等），生产图用的是
`elev=24° / azim=-60°` + 竖向放大 0.45，两者**不要互相引用数值**。交互式 WebGL 那条
（`fig3d_viewer.html` / `?dragtest=N`）**尚未**接进 WebUI —— 那是**另一个 worktree**
（`E:\导弹包线图-viewer`，分支 `3d-viewer`）的范围。

## 怎么重跑（在 worktree 根）

```powershell
cd "E:\导弹包线图-3d"
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"

# (a) mplot3d：13 变体 × 3 格式；同进程连出两次 + 跨进程各出一次，比对 sha256（约 1~2 min）
python spikes\fig3d\spike_a_mpl3d.py --cross --cross-dir spikes\fig3d\out

# (c) WebGL：数据通路（两种形状 + 单文件离线版）与 Node 端 CPU 量测
python spikes\fig3d\make_viewer_data.py --inline
node spikes\fig3d\node_spike_c_console.js

# (c) 拖动"跟手"自检（复用 viewer 里真实的 applyDrag/projectToScreen；退出码 0 = 双向都跟手）
node spikes\fig3d\spike_d_drag.js

# 无头浏览器真渲染（本机 Edge + SwiftShader；产物 out/c/shot.png）
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --disable-gpu --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader `
  --window-size=1280,800 --virtual-time-budget=8000 `
  --screenshot="$PWD\spikes\fig3d\out\c\shot.png" `
  "file:///E:/导弹包线图-3d/spikes/fig3d/out/c/fig3d_viewer_offline.html"

# 同一份自检搬进**真浏览器**跑一遍（结果写进 #dragtest，dump 出来看）
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --disable-gpu --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader `
  --window-size=1280,800 --virtual-time-budget=8000 --dump-dom `
  "file:///E:/导弹包线图-3d/spikes/fig3d/out/c/fig3d_viewer_offline.html?dragtest=200" |
  Select-String -Pattern "DRAG"

# 只看 spike 的 smoke 判据（16 项，约 1 s）
python tests\run_tests.py -k fig3d
```

## 查看器的两个 URL 开关（调试/取证用）

| 参数 | 作用 |
| --- | --- |
| `?dragtest=200` | **在真浏览器里**跑"跟手"自检，把整张表写进 DOM 的 `#dragtest`（供 `--dump-dom` 抓取）。`200` = 大拖拽的像素量级，与 `spike_d_drag.js` 对齐 |
| `?bg=transparent` | canvas 透明底（`alpha:true` + `clearColor` 的 alpha=0），供嵌进宿主页面时由宿主兜底 |
| `?src=<url>` | 按相对路径 `fetch` 外部 JSON（HTTP 服务形态）；`file://` 下用 `--inline` 单文件版 |

## 文件

| 文件 | 作用 |
| --- | --- |
| `spike_a_mpl3d.py` | (a) 13 个变体 × 3 格式；同进程/跨进程 sha256 比对；`--json` 供子进程写记录 |
| `make_viewer_data.py` | (c) 已交付 CSV → 前端 JSON（`full` / `slim`），`--inline` 生成单文件离线版 |
| `fig3d_viewer.html` | (c) **手写 WebGL2** 查看器模板（无 three.js，JS 512 行；亮色 chrome + 拖动跟手）；内含"禁止 http(s) 字面量"的自律说明 |
| `spike_d_drag.js` | (c) **拖动方向"跟手"自检**：见证点=近侧表面 + 弹道最近视野中心点，四方向逐个小拖拽比投影位移；退出码 0 = `ok=1` |
| `node_spike_c_console.js` | (c) 不依赖浏览器的量测：顶点装配耗时 / 每帧矩阵耗时 / 缓冲字节 |
| `clean_out.py` | 只保留入库样本，清掉其余可重建产物 |
| `out/c/shot.png` | 无头 Edge **真渲染**截图（不是示意图；亮色主题） |

## 入库产物（≈ 1.3 MB）

`out/a_report.json`、`out/crossA.json`、`out/crossB.json`（复现性原始记录）、
`out/a/v02_traj_3d.*`、`out/a/v03_traj_3d_proj.*`、`out/a/v13_traj_preview_existing.png`、
`out/c/{data.full.json,data.slim.json,fig3d_viewer_offline.html,shot.png}`。

其余 117 个文件（13 变体 × 3 格式的 PDF/PNG/SVG）**刻意不入库**：一条
`python spikes\fig3d\spike_a_mpl3d.py` 就能全部重建，所以不占仓库体积。

## 数字来源要标清

本文与 `docs/FIG3D-FEASIBILITY.md` 里的全部数字都来自**本机**：
Python 3.14.7 / matplotlib 3.11.1 / numpy 2.5.2 / Node 24 / Edge（Chromium，SwiftShader 软渲染），
数据来自 `results/traj_default_*` 与 `results/{plane,bg}_default_cases.csv`。
**没有**在别的机器或别的 matplotlib 版本上验证过。

## ⚠ 两个"不报错但会错"的坑（本轮真中过）

1. **`[System.IO.File]::*` 用相对路径会打到别的工作树去**：pwsh 的 `cd` 不同步 .NET 的
   `CurrentDirectory`，所以脚本里一律用**绝对路径**（本会话真在 `E:\导弹包线图` 建过一个垃圾文件）。
2. **颜色/尺寸的单位错了不报错，只是难看**：`[THEME.x]` 多包一层数组 ⇒ `Float32Array` 收到数组变
   `NaN` ⇒ 所有节点变黑球；点精灵尺寸多乘一个 `radius` ⇒ 全部被 clamp 到 32 px。
   细节与修正口径见 `docs/FIG3D-FEASIBILITY.md` §3.5.2。

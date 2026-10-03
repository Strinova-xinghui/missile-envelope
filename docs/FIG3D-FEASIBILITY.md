# 图 3 三维化 / 交互式 WebGL 可行性（分支 `3d-viz`，worktree `E:\导弹包线图-3d`）

> 阶段：**可行性侦察**，不改生产路径（`src/**`、`figures/**`、`results/**` 一个字节都没动）。
> 全部数字都在本机实测，命令见 §3；样例产物在 `spikes/fig3d/out/`（合计 < 0.5 MB）。
> 基线 `73eb2bc`（该 commit 的 WebUI 还是 `webui.py` 里内联的 `PAGE` 单串；
> Lead 的 `webui` 分支已把它拆成 `src/missile_sim/webui_static/` + `GET /static/<name>`，
> 本文按**拆分后的形态**给落地口径）。

---

## 1. 结论先行

| 图 | 3D 化 | 判定 | 一句话理由 |
| --- | --- | --- | --- |
| **图 3 机动轨迹** | **静态 3D（mplot3d）值得做** | ✅ **推荐** | 它的第三维是**真实空间高度**（本工况弹从 10000 m 爬到 12847 m），俯视图把这个信息**完全压掉**；三格式字节可复现，成本 ≈ 2 s / 245 kB |
| **图 3 机动轨迹** | **WebUI 内嵌 WebGL 交互视图值得做** | ✅ **推荐（手写，不引 three.js）** | 纯离线、零第三方 JS，整页 **55.4 kB**、数据 **30.4 kB**，本机无头 Edge 实测**渲染出正确画面**；拖动**跟手**（§3.5.1）且 chrome 为亮色（§3.5.2）—— 这正是 `mplot3d` 做不到的"转一转看" |
| **图 1 ΔV–BC 平面** | 第三维换 `t_hit` | ❌ **不推荐** | `t_hit` 在网格上**已经由等时线 + 颜色条完整表达**，旋转视角只增加遮挡与读图成本；实测 3D 曲面版 PNG 527 kB vs 2D 209 kB（+152%），信息量没变 |
| **图 2 β–γ 平面** | 第三维换 `t_hit` | ❌ **不推荐** | 同图 1，且 β、γ **跨度差 1~2 个量级**（真实跨度做 `box_aspect` 后 γ 轴被压成一条线，不做则几何失真）—— 两个都是坏选择 |
| **plotly 交互 HTML** | — | ❌ **否决** | `pip` 能装（有网），但包 **56.1 MB**、其中 `plotly.min.js` **4.8 MB**；离线内联式 HTML ≈ 4.8 MB+，还要新增 `narwhals` 运行时依赖。**自包含 HTML 与免安装分发互斥** |

**一句话总纲**：**只有图 3 该 3D**；静态交付走 `mplot3d`（零新依赖、字节可复现），
交互探索走**手写 WebGL2**（零第三方 JS、整页 55 kB），两条路都**离线可用**。
两个"对不对"级别的交互硬要求（**拖动必须跟手、chrome 走亮色**）已在 spike 里做完并**机器验证**
（§3.5：拖 `Δx=+200 px` 时物体近侧表面同向走 `+105.3 px`，镜像写法则为 `−105.3 px`）。

---

## 2. 硬约束核对

| 约束 | 结论 | 证据 |
| --- | --- | --- |
| 免安装分发（`make_dist.py` / `docs/DISTRIBUTION.md`）**必须仍离线可用** | ✅ 两条路都不破坏 | 分发包运行时**零网络请求**（`DISTRIBUTION.md` §"不联网也能用"）。`mplot3d` 在 matplotlib 里（已随包走）；WebGL 查看器是**纯静态文件 + 手写 JS**，无 CDN、无三方可执行代码。实测 `file://` 直开即工作（§3.3） |
| 产物**字节可复现**（`-k figures_repro` 同款判据） | ✅ **13/13 变体同进程 + 跨进程全绿** | §3.1、§3.2 |
| **尽量不引新依赖** | ✅ `mplot3d`（matplotlib 自带）与手写 WebGL 都是**零新增**；plotly 被否掉 | §3.4 |
| 不改生产路径 | ✅ 只新增 `docs/`、`spikes/`、`tests/test_fig3d_spike.py` | `git diff --stat` 只有新增 |

> ⚠ 关于 `mplot3d` 的"z 排序不稳"担忧：**没被证实**。实测 13 个变体（含 `plot_surface`、
> 按时间着色的 `scatter`、带地面投影与垂线的复杂场景、双视角分格）**同进程连出两次**与
> **跨进程各出一次**（`PYTHONHASHSEED` 一个随机一个 `1`、间隔 1.2 s）三格式 sha256 **全部一致**。
> 原因：`mplot3d` 的画家算法按 `zsort` 深度排序，深度是**纯浮点函数**（同样输入同样输出），
> 真正的随机源是 matplotlib 的 SVG id 盐 `svg.hashsalt`（默认 `uuid4()`）—— 它**已被
> `figures.setup_style()` 钉死**，`normalize_svg_ids()` 再兜一层，所以稳定。
> 但要注意：**这个结论只在"图元不交叠/不相切"的场景成立**（见 §5 风险 R1）。

---

## 3. 实测证据

### 3.0 环境与重跑命令

```powershell
cd "E:\导弹包线图-3d"
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"

# (a) mplot3d：13 变体 × 3 格式，同进程连出两次 + 跨进程各出一次，比对 sha256
python spikes\fig3d\spike_a_mpl3d.py --cross --cross-dir spikes\fig3d\out

# (c) WebGL 查看器：数据通路 + 单文件版 + Node 端 CPU 量测
python spikes\fig3d\make_viewer_data.py --inline
node spikes\fig3d\node_spike_c_console.js

# (c) 拖动方向"跟手"自检（§3.5.1；`-k fig3d` 也跑这一条）
node spikes\fig3d\spike_d_drag.js

# 无头浏览器真渲染取证（本机 Edge + SwiftShader 软渲染）
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --disable-gpu --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader `
  --window-size=1280,800 --virtual-time-budget=8000 `
  --screenshot="$PWD\spikes\fig3d\out\c\shot.png" `
  "file:///E:/导弹包线图-3d/spikes/fig3d/out/c/fig3d_viewer_offline.html"

# 同一份自检搬到**真浏览器**里跑一遍（把结果写进 DOM，再 dump 出来；§3.5.1 的交叉印证）
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --disable-gpu --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader `
  --window-size=1280,800 --virtual-time-budget=8000 --dump-dom `
  "file:///E:/导弹包线图-3d/spikes/fig3d/out/c/fig3d_viewer_offline.html?dragtest=200" |
  Select-String -Pattern "DRAG"
```

环境：Python 3.14.7 / matplotlib 3.11.1 / numpy 2.5.2 / Node 24 / Edge（Chromium）。
数据来源**全部是已交付产物**（`results/traj_default_{missile,target,segments}.csv`、
`results/plane_default_cases.csv` 1632 行、`results/bg_default_cases.csv`），
**spike 不跑求解器**，13 个变体全流程秒级可重跑。

### 3.1 (a) matplotlib mplot3d —— 同进程复现（`spikes/fig3d/out/a_report.json`）

| 变体 | 说明 | t1 [s] | t2 [s] | PNG | PDF | SVG | 同进程 sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `v01_traj_plan_2d` | 图3 俯视（2D 对照） | 1.49 | 1.40 | 104.4 kB | 14.0 kB | 32.7 kB | OK |
| `v02_traj_3d` | 图3 三维：弹+目标+命中点 | 1.60 | 1.50 | 210.6 kB | 17.3 kB | 44.8 kB | OK |
| `v03_traj_3d_proj` | **图3 三维 + 地面投影 + 垂线** | 1.99 | 2.06 | 245.9 kB | 20.6 kB | 54.6 kB | OK |
| `v04_traj_3d_color_t` | 三维 + 按时间着色（`scatter` 3300 点） | 5.16 | 4.25 | 240.1 kB | **783.1 kB** | **690.5 kB** | OK |
| `v05_traj_3d_multi_azim` | 三维 + 双方位角分格 | 3.71 | 2.83 | 335.9 kB | 24.2 kB | 78.8 kB | OK |
| `v06_traj_alt_2d` | 图3 高度–时间（2D 对照） | 1.36 | 1.27 | 114.7 kB | 15.6 kB | 34.6 kB | OK |
| `v13_traj_preview_existing` | **现有 `figures.plot_traj_preview_3d`**（两方位角，160 dpi） | 2.80 | 2.96 | 272.7 kB | 60.2 kB | 132.9 kB | OK |
| `v07_plane_2d` | 图1 2D 对照 | 1.80 | 1.58 | 209.4 kB | 23.2 kB | 77.7 kB | OK |
| `v08_plane_3d_surface` | 图1 第三维 `t_hit` 曲面 | 2.07 | 2.23 | 526.7 kB | 45.3 kB | 153.0 kB | OK |
| `v09_plane_3d_scatter` | 图1 11 弹落点 + 曲面 | 1.89 | 1.92 | 405.3 kB | 23.2 kB | 61.2 kB | OK |
| `v10_plane_3d_2panel` | 图1 2D \| 3D 并排 | 3.14 | 3.15 | 533.2 kB | 44.8 kB | 159.6 kB | OK |
| `v11_bg_2d` | 图2 2D 对照 | 0.80 | 0.79 | 80.4 kB | 16.0 kB | 40.4 kB | OK |
| `v12_bg_3d_surface` | 图2 第三维 `t_hit` 曲面 | 0.79 | 0.71 | 142.9 kB | 31.2 kB | 95.7 kB | OK |

**同进程不可复现变体数：0/13。**

读法（对"该不该 3D"有用）：
* **图3 三维的增量成本很小**：`v03` 比 2D 对照 `v01` 只多 **0.5 s / +141 kB PNG**，而换回来的是
  俯视图里根本不存在的高度维。
* **按时间着色是最坏的一个**：`v04` 的 PDF/SVG 体积爆炸到 **783 / 690 kB**（逐点着色 =
  3300 个独立路径），比 2D 对照大 **22 倍**。**要 3D 就别用 `scatter` 逐点着色，用分段线**。
* **图1 的 3D 曲面没有任何体积优势**：`v08` 527 kB vs `v07` 209 kB，而颜色条已经表达了同一件事。
* **图2 的 3D 更别扭**：`v12` 用真实跨度做 `box_aspect` 后 γ 方向被压扁（β≈2500~3100 vs γ≈0~180），
  曲线在投影里几乎成一条线 —— 要么几何失真（不做 box_aspect），要么没信息（做了）。

### 3.2 (a) 跨进程复现（`spikes/fig3d/out/crossA.json` vs `crossB.json`）

两个**独立子进程**各出一次（A 用当前随机 `PYTHONHASHSEED`，B 用 `PYTHONHASHSEED=1`，
中间 `sleep 1.2`，输出目录也不同），比对三格式 sha256：

```
v01_traj_plan_2d OK      v06_traj_alt_2d   OK      v13_traj_preview_existing OK
v02_traj_3d      OK      v07_plane_2d      OK      v11_bg_2d                 OK
v03_traj_3d_proj OK      v08_plane_3d_surface OK   v12_bg_3d_surface         OK
v04_traj_3d_color_t OK   v09_plane_3d_scatter OK
v05_traj_3d_multi_azim OK v10_plane_3d_2panel OK
跨进程不一致变体数：0/13
```

**判定：`mplot3d` 的 PNG / PDF / SVG 三格式跨进程逐字节可复现**，与本仓库
`-k figures_repro` 同款判据一致。**SVG/PDF 上的 mplot3d 稳定性问题在本仓库的用法下不存在**
（前提见 §5 R1）。

### 3.3 (c) 离线 WebGL 交互视图

**真渲染取证**：`spikes/fig3d/out/c/shot.png`（1280×800，**47 700 B**，sha256 `8c0f961fa82545cf…`）
是无头 Edge **实际渲染**出来的画面，不是示意图 —— 可以看见分段着色的导弹航迹、红色目标航迹、
两条地面投影、浅灰网格、地面网格中心处的 RGB 坐标三轴、深色命中点/琥珀发射点与事件节点、
以及 HUD 上的 `t_hit = 69.17 s / 脱靶量 10.0 m / 开机 34.46 s`。
渲染器是**手写 WebGL2**（无 three.js）：两个着色器程序（线 / 圆点精灵）+ 索引缓冲 + 画家无关的
深度测试，前端 JS 共 **512 行 / 21 930 字符**。

| 项 | 实测 |
| --- | --- |
| 查看器模板 `fig3d_viewer.html`（HTML+CSS+JS，未压缩） | **28 629 B**（JS 本体 21 930 字符 / 512 行；CSS 1 227 字符） |
| 单文件离线版 `out/c/fig3d_viewer_offline.html`（模板 + 内联数据） | **55 385 B** |
| 数据 `full`（3322+3322 行，全时间序列） | 319 906 B（312.4 kB） |
| 数据 `slim`（抽稀到 320+320 点 + 分段色 + 节点 + 锚点） | **30 421 B**（29.7 kB） |
| 顶点装配 CPU（320 点档，20 次平均，Node） | **0.848 ms / 场**（一次性，加载时） |
| 每帧矩阵 CPU（`view`+`persp`+`mul`，20 万次平均，Node） | **1.080 µs / 帧** |
| GPU 缓冲（1324 线顶点 + 8 点顶点 + 6 轴顶点，交错 7 float/顶点） | **37 464 B 顶点 + 10 440 B 索引** |
| 拖动方向（用户硬要求，判据见 §3.5） | ✅ `ok=1`；拖 `Δx=+200 px` 时近侧表面 **+105.3 px**（同向） |
| chrome 配色（用户硬要求） | ✅ 亮色：底 `#f7f8f9` / 字 `#1f2933` / 1 px 描边 `#d8dce1`；`?bg=transparent` 可透明嵌宿主 |
| `file://` 直开 | ✅ 可用（`--inline` 单文件版**零请求**；宽版按相对路径 `fetch(?src=)` 也走 `file://`） |
| 由 WebUI 静态服务提供 | ✅ 纯静态资源；`webui.py` 已在发 `/figures/`、`/results/`，加 `/static/` 是一条同形分支 |
| 第三方 JS | **0** |
| 帧率 | ⚠ **没取到可信数字**：无头 `--virtual-time-budget` 下 `requestAnimationFrame` 走的是虚拟时钟，量出来是假的。诚实口径：**本机软渲染下能正常出帧**（截图为准），真机 GPU 帧率待用户在浏览器里看 |

**交互**：左键拖拽旋转 / 滚轮缩放 / 右键或 `Shift`+拖拽平移 / 复位 / 自动旋转 / 坐标轴开关。
**数据通路设计**（落地时的 `/api/traj/<tag>.json` 响应体就是 `data.slim.json`）：

```json
{ "tag": "default", "missile_name": "PL-12", "hit": true,
  "t_hit_s": 69.172, "miss_m": 10.0,
  "launch": [0, 10000, 0], "target0": [50000, 10000, 0],
  "missile": { "t": [...], "p": [[x, y, z], ...], "c": [[r, g, b], ...] },
  "target":  { "t": [...], "p": [[x, y, z], ...] },
  "segments": [ { "t0": 0.0, "t1": 8.0, "label": "直飞", "color_key": "grey",
                  "heading0": 180.0, "heading1": 180.0, ... } ],
  "marks":  [ { "name": "seeker_on", "t_s": 34.458, "note": "..." } ],
  "anchor": { "lock_distance_m": 16000.0, "t_beam_s": 34.458, "t_react_s": 35.458,
              "completed": true } }
```

坐标口径**原样搬运内核口径**：数组按 `(x, y, z)` 给，其中 **`y` 是高度**、水平面是 `(x, z)`
（与 `solver.trajectory()` 的注释一致）。前端只做 `(x, z, y)` 重排，**不做任何坐标换算** ——
避免又一处"看起来对"的静默错位。分段色由后端算好（`Segment.color_key` → RGB），
前端不复制 `figures.TRAJ_COLORS`。

**`file://` vs WebUI 静态服务**：两种都可行，**但用途不同** ——
* `file://` 单文件版适合**分发/归档/离线看**（对方双击即看，不需要起服务）；
* WebUI 静态服务适合**在线探索**（能顺着表单改了参数立刻重画，不必手动搬 JSON）。
建议**两种都给**：单文件版作为"导出"按钮的产物，静态服务版作为结果面板里的内嵌入口。

### 3.4 (b) plotly —— 否决证据

| 项 | 实测 |
| --- | --- |
| 可获取性 | ✅ 有网，`python -m pip download plotly --no-deps` 成功（`plotly-7.1.0-py3-none-any.whl`，9.7 MB） |
| 装到隔离目录后的体积 | **56.12 MB**（`--target .tmp_test/plotly_probe/pkg`） |
| `plotly/package_data/plotly.min.js` | **4 815 814 B（4.8 MB）** |
| `widgetbundle.js` | 4 959 028 B |
| `include_plotlyjs=True` 的 HTML | ≈ 4.8 MB + 数据（自包含，但比整个 WebGL 查看器大 **100 倍**） |
| `include_plotlyjs='cdn'` 的 HTML | ≈ 几十 kB，但**浏览器要联网取 CDN** ⇒ 与"离线分发"直接冲突 |
| 新运行时依赖 | ⚠ plotly 7.1.0 的 `graph_objects` 顶层 `import narwhals.stable.v1` ⇒ `--no-deps` 装完**当场 ImportError**，真实依赖是 `plotly + narwhals(+pandas 生态)` |

**结论**：装得上，但 `56 MB` 包体 + `4.8 MB` 内联 JS + 新运行时依赖，**与免安装分发（现 134.4 MB
解压 / 54.8 MB zip）和"不引新依赖"两条约束同时冲突**。本项目已有 `matplotlib` mplot3d 做静态、
手写 WebGL 做交互，**plotly 没有位置**。

---

### 3.5 (c-补) 两条硬要求：拖动**跟手** + chrome **亮色**

> 用户 2026-10-01 追加，**优先级高于"好看"**。这两条不是审美，是"对不对"。

#### 3.5.1 水平拖动必须"跟手"（抓住物体转，不许像镜像）

用户点名 [jari-aerospace.top](https://jari-aerospace.top/) 那套 3D 视图"左右拖动方向反直觉"
—— 那是**镜像手感**：拖右而物体逆着走。本 spike 的第一版就是那个号（`cam.az -=`），已改成跟手。

**判据（可复现）**：把 viewer 里**真实的** `applyDrag()` 跑两遍，只换相机方位角/仰角，
再拿同一个世界点投影两次，比屏幕位移。见证点必须落在**物体正对观察者的近侧表面**上
（`center + dir·0.2R`，投影恰好落在屏幕中心 —— 那就是用户手指按住的地方）：

| 见证点（到视野中心距离） | `dx`@Δx=+20 px | `dx`@Δx=−20 px | `dy`@Δy=+20 px | `dy`@Δy=−20 px | `dx`@**Δx=+200 px** |
| --- | --- | --- | --- | --- | --- |
| **物体正对观察者的近侧表面**（0 px） | **+19.1** | −19.1 | **+20.4** | −20.4 | **+105.3** |
| **弹道上最靠近视野中心的点**（23 px） | **+16.6** | −16.7 | **+15.9** | −16.7 | **+90.2** |
| 发射点（481 px，参考） | −57.2 | +56.0 | −15.4 | +15.5 | −555.8 |
| 命中点（458 px，参考） | −26.0 | +33.4 | +4.2 | −5.5 | +567.7 |
| 弹道最高点（261 px，参考） | −7.9 | +1.3 | +9.0 | −8.6 | −231.7 |

单位 px，canvas y 向下为正。**判据 = 两个"主见证点"的四个方向全部同号** ⇒ `ok=1`。
同一段代码在**真浏览器**里也跑了一遍（`?dragtest=200`，canvas 1254×707，数字随画布尺寸缩放）：
近侧表面 `+16.9 / +18.0 / +93.1`、弹道最近点 `+14.6 / +14.0 / +79.7`，同样 `ok=1`。

**镜像对照（同一段代码，只把符号写反）**：拖 `+200 px` 时近侧表面
`az +=`（**现在的实现，跟手**）= **+105.3 px**；`az -=`（旧实现 / jari 那种镜像）= **−105.3 px**。

> ⚠ **拿"发射点/命中点"当见证会得出相反结论** —— 这不是 bug，是环绕相机的几何：
> 相机绕 `center` 的**竖直轴**转，离轴远的点位移方向可能反向（本工况相机在 39 km 外，
> 轨道中心**后方**的点仍在相机前方、仍能投出来，只是 `u/w` 换了号）。
> 所以文档里"跟手"的判据**只**落在近侧表面上，上面那三行参考值故意留着防止后人误判。

**要改成反向（若用户之后要求）**：`spikes/fig3d/fig3d_viewer.html` 里
`applyDrag()` 的**一行**——`cam.az += dx * AZ_PER_PX;` 的 `+` 改成 `-`，**别处没有第二处方位角赋值**
（另两处是复位与自动旋转，测试会数出正好 3 处）。转折率 `AZ_PER_PX = 0.008 rad/px`
（拖过整屏 ≈ 半圈，与常见 3D 工具同量级），仰角 `EL_PER_PX = 0.008`，极点夹在 `EL_LIMIT = 1.45 rad`
（拖到顶会"顶住"而不翻面 —— 这是所有环绕相机的标准行为）。

#### 3.5.2 chrome 走亮色（嵌进亮色 WebUI 不许自带深色外壳）

| 项 | 取值 | 说明 |
| --- | --- | --- |
| 页面底色 | `#f7f8f9` | 与 WebUI 近白底一致；不用纯白，避免网格线"浮"起来 |
| 正文/数字 | `#1f2933` | 深灰字 |
| 描边/分隔 | `#d8dce1` 1 px | 按钮与 HUD 卡片 |
| 背景透明（嵌宿主） | `?bg=transparent` → `clearColor(…, alpha=0)` + `context{alpha:true}` | 让宿主页面兜底；独立 HTML 就自带上面那套亮色 |
| 网格线 | 中灰 `[0.79, 0.82, 0.85]` | 远看不抢戏 |
| 坐标轴 | R/G/B `[0.80,0.20,0.18] / [0.13,0.55,0.22] / [0.15,0.38,0.85]` | 地面网格中心处的三轴 |
| 命中点 | 近黑 `[0.09,0.11,0.14]` | ⚠ **亮底上必须用深色**：原来用白色，白底会直接消失 |
| 弹道/目标轨迹 | 沿用现有 `figures.TRAJ_COLORS`，**不改浅** | 亮色化只动 chrome，不动数据配色（浅色在近白底上不可辨） |

**这轮顺手修掉的两个真 bug**（都是"改配色才暴露"的，记在这里防复发）：
1. `[THEME.x]` 把颜色**多包了一层数组** → `Float32Array` 收到数组变 `NaN` → 所有节点渲染成**黑球**。
   修法是传**扁平三元组**（`THEME.hit`），只有逐顶点色才传"三元组的数组"。
2. 点精灵尺寸公式多乘了一个 `radius`（`H*0.5*radius`），导致**每个点都被 clamp 到 32 px**、
   亮底上糊成一排黑圆。正确口径：`px = d_m · (H/2) / (depth · tan(fovy/2))`，着色器已除 `depth`，
   所以 uniform 只给 `(H/2)/tan(fovy/2)`，点的尺寸参数单位=**米**（命中点 900 m / 发射点 650 m /
   事件节点 420 m）。
   —— 这两条**不报错、只是难看**，正是"前端行为只能靠真浏览器看"的那类（见 AGENTS.md 已知缺口）。

## 4. 对现有判据/分发的影响

| 现有约束 | 3D 化的影响 | 判定 |
| --- | --- | --- |
| **8 项物化判据**（`-k traj_plot` 23 项：inset 像素宽高、注记两两不重叠、字形/线型、字节复现…） | `mplot3d` 的**注记落在三维投影里**，"两两不重叠"在 3D 下不是"像素不重叠"那么简单（近处物体遮远处物体）⇒ 需要**新增**一组 3D 专用判据，**不是**改现有 23 项 | ⚠ 需要新增判据（见 §6） |
| **字节复现**（`-k figures_repro`、`test_traj_plot.py::test_traj_figures_are_byte_identical_across_two_runs`） | 实测**通过**（§3.1/§3.2） | ✅ 无影响 |
| **免安装分发** | `mplot3d` 零增量；WebGL 静态资源 ~28.6 kB 模板 + 每次请求 ~30 kB 数据；plotly 被否决 | ✅ 无影响 |
| **`-k printed_text`**（文案里没有 markdown 星号） | 3D 图题/脚注要走 `figures._plain()`；WebGL 页面的 HUD 文案是**新落点**（没人兜） | ⚠ 新文案要纳入扫描 |
| **`results/*.json` 契约** | 若新增 `/api/traj/<tag>.json`，它是**响应体**而非落盘产物，不进 `results/`；要不要落盘一份 `.json` 供离线单文件版复用，需要拍板 | ⚠ 待拍板（§7 Q3） |

---

## 5. 遗留风险

* **R1（mplot3d 的"稳"是有条件的）**：复现实验证明的是**本仓库当前这几类图元**稳定。
  `mplot3d` 用画家算法 + `zsort` 深度排序，**相交/相切/共面**的图元在同一深度上排序规则未定义；
  一旦图上出现"两条线在同一像素深度交叉"或"注记正好压在深度接近的曲面上"，
  可能出现**逐次不同的遮挡**（那会破坏字节复现）。→ 落地时**先跑一条 3D 专用复现用例**，
  再往图里加新图元（尤其是悬浮文字注记）。
* **R2（注记在 3D 里的可读性没有判据）**：现有 23 项物化判据全部是**2D 像素几何**。
  3D 下"标在命中点旁边的字"可能被轨迹挡住、或投影到大半个图外。本阶段**只做了视觉抽查**
  （`out/a/v03_traj_3d_proj.png`），**没有**建立自动判据。
* **R3（WebGL 的功能缺口）**：spike 的渲染器**没有文字标注**（只有点/线/网格/坐标轴）——
  轴刻度、节点名称、图例都没画。真做要加 DOM 覆盖层（把 3D 点投影到屏幕坐标再放 `<div>`），
  这是**新增工作量**，且要注意"文字与几何的相对位置"也要有判据。
* **R4（性能口径不完整）**：帧率**没量到**（无头虚拟时钟不可信，§3.3）。真机 GPU 帧率、
  低端集显表现、移动端触摸交互**都没验**。
* **R5（`file://` 的浏览器差异）**：`file://` 下 `fetch()` 相对路径在我这台机器的 Edge 上工作
  （`--inline` 单文件版完全不依赖它）。Chrome 对 `file://` 的 `fetch` 更保守 ——
  **建议离线版一律出 `--inline` 单文件**，把 `?src=` 形态只留给 HTTP 服务。
* **R6（抽稀点的视觉折线感）**：`slim` 用 320 点，截图里航迹略见折线。
  落地建议 **800~1200 点**（体积约 70~100 kB，装配 < 3 ms），不改变结论。
* **R7（数据双份风险）**：`mplot3d` 静态图与 WebGL 交互视图若各读一份轨迹，
  可能出现"静态图与交互图不一致"。→ 两边都必须从 `solver.trajectory()` 的同一份 `Shot.rows` 出发。
* **R8（"跟手"的见证点容易被选错）**：环绕相机绕 `center` 竖直轴转，**离轴远的特征位移方向会反向**
  （§3.5.1 的三行参考值实测就是负的）。所以落地时"拖动方向"的自动判据**必须**用近侧表面当见证，
  否则会得到一个**符号相反**的结论、然后"顺手改坏"正确实现。
  本 spike 已把这条写进 `tests/test_fig3d_spike.py`（钉住符号，改动即红）。
* **R9（亮色嵌入的宿主依赖）**：`?bg=transparent` 只保证 canvas 透明，**页面样式（按钮/HUD/字体）
  在 iframe 里仍会自带**；要真正"继承宿主"，需要宿主通过 `postMessage` 传主题、或只嵌 canvas 视图
  （无 chrome）。本 spike 只做到"独立 HTML 自带亮色 + 可透明底"，**没有**做主题双向同步。
* **R10（前端行为判据的缺口）**：本 spike 的拖动自检是**唯一**能钉住前端行为的用例
  （Node 复算 + 真浏览器 `?dragtest` 双口径）。WebUI 正式落地后若把拖动代码搬进
  `webui_static/viewer3d.js`，**必须把这条自检一起搬过去** —— AGENTS.md 已经写明
  "前端行为在这套测试里跑不起来"，别指望 `-k webui` 能兜住。

---

## 6. 真要做，落地要改哪些文件 + 预计工作量

### 6.1 方案 A：图3 静态 3D（`mplot3d`）—— 推荐先做

| # | 文件 | 改什么 | 估计 |
| --- | --- | --- | --- |
| A1 | `src/missile_sim/figures.py` | 新增 `plot_traj_3d(run, *, out_base, ...)`：吃 `run.rows`（`x/y/z` + `tx/ty/tz`）画弹/目标/命中点/**地面投影**/节点，沿用 `TRAJ_COLORS`、`_box_aspect`、`add_traj_header`、`add_footnotes`、`save_formats`；`--traj-preview` 的 `plot_traj_preview_3d` 当时**保留不动**（⚠ 2026-10-03 已随"图4 不出静态 3D 图"删除） | 0.5~1 d |
| A2 | `src/missile_sim/workflow.py` | `TrajRequest` 加 `view: str = "2d"`（`2d`/`3d`）；`run_traj` 出图分支按它走；`as_dict()` 出口 + `cache_key()` **不受影响**（出图不参与缓存键） | 0.3 d |
| A3 | `src/missile_sim/cli.py` | 加 `--traj-view 2d|3d`；`--figure traj` 帮助文本同步 | 0.2 d |
| A4 | `src/missile_sim/webui_static/app.js` + `index.html` | 图3 表单加"3D 视图"开关（登记进 `WEB_ONLY_KEYS`，见 AGENTS.md 的 `add-webui-form-field` 坑） | 0.3 d |
| A5 | `tests/test_fig3d_plot.py`（**新文件**，不动 `tests/test_traj_plot.py`） | 3D 专用物化判据：**同一进程连出两次三格式 sha256 一致**、`**` 计数为 0、无缺字形、注记与命中点在投影框内、地面投影与命中点垂线存在 | 0.5 d |
| A6 | `docs/PLAN-FIG3-TRAJECTORY.md`、`AGENTS.md`（图3 段落）、`README.md`、`docs/DISTRIBUTION.md`（体积表） | 同步口径与体积 | 0.3 d |
| | | **合计** | **≈ 2~3 人日** |

**不动**：`spec.py` / `pool.py` / `grid.py` / `solver.py` / `vendor/` / `results/*` / `figures/*`（除了新增一张 `fig_traj_default_3d.*`）。

### 6.2 方案 B：WebUI 内嵌 WebGL 交互视图 —— 推荐其次做

| # | 文件 | 改什么 | 估计 |
| --- | --- | --- | --- |
| B1 | `src/missile_sim/webui_static/viewer3d.html` + `viewer3d.js`（**新静态资源**，按 Lead 已落地的 `webui_static/` 形态） | 把 spike 的 `fig3d_viewer.html` 拆成模板 + JS；URL 参数 `?src=/api/traj/<tag>.json` | 0.5 d |
| B2 | `src/missile_sim/webui.py` | `GET /api/traj/<tag>.json` 返回 §3.3 的 `slim` 形状；`GET /static/<name>` 已在 Lead 分支落地，直接复用 | 0.5 d |
| B3 | `src/missile_sim/figures.py` 或新 `viewer3d.py` | `traj_to_viewer_payload(run, *, n_max=1000) -> dict`：**唯一的坐标口径出口**（`(x,y,z)`→前端 `(x,z,y)` 重排也在这里做），供 `/api/traj` 与离线单文件版共用 | 0.5 d |
| B4 | `src/missile_sim/webui_static/app.js` + `index.html` | 结果面板加"3D 交互视图"按钮（内嵌 iframe 或新标签页）；再加"导出单文件版"（把 payload 内联进 `viewer3d.html` 下载） | 0.5 d |
| B5 | `tests/test_webui_viewer3d.py`（**新文件**） | 用 `http.client` 打真服务：`/api/traj/<tag>.json` 的键集合与坐标口径断言、`/static/viewer3d.js` 的 MIME 与体积上限、`file://` 单文件版**字符串内不含任何 `http(s)://`**（= 无 CDN 的机器可判定据） | 0.5 d |
| B6 | `src/missile_sim/webui_static/viewer3d.js` | **拖动方向"跟手"**（用户硬要求）：`applyDrag(cam, dx, dy)` 一处定义 `cam.az += dx·AZ_PER_PX`（默认 `AZ_PER_PX=EL_PER_PX=0.008`、`EL_LIMIT=1.45`），配 `projectToScreen()`；**符号只此一处**（§3.5.1） | 0.3 d |
| B7 | `src/missile_sim/webui_static/viewer3d.js` + 该文件的 Node 自检 | **把自检一起搬过去**：`spike_d_drag.js` 那套（见证点=近侧表面 + 弹道最近视野中心点）改成对 `viewer3d.js` 跑，断言 `ok=1`；这是**唯一**能钉住前端行为的判据（R10） | 0.3 d |
| B8 | `src/missile_sim/webui_static/viewer3d.js` + `app.css` 联动 | **亮色 chrome**（用户硬要求）：近白底 `#f7f8f9`、深灰字 `#1f2933`、1 px `#d8dce1`、中灰网格、三轴 R/G/B；嵌入态走 `?bg=transparent`（`context{alpha:true}`）由宿主兜底；**弹道/目标配色沿用 `TRAJ_COLORS` 不调浅**（§3.5.2） | 0.4 d |
| B9 | `docs/WEBUI.md`、`docs/DISTRIBUTION.md`、`README.md` | 记录入口、体积增量、导出方式 | 0.3 d |
| | | **合计** | **≈ 3.3~3.9 人日** |

> B6~B8 是用户 2026-10-01 追加的两条硬要求（拖动跟手 + 亮色 chrome）落在落地清单里的位置 ——
> 在 spike 里都已经**做完并机器验证**（§3.5），所以这里的估计是"照搬"而不是"探索"。

**可维护性评估（手写 vs three.js）**：手写 512 行、两个着色器、无构建步骤、无第三方许可证与
版本升级负担；three.js 要引 ~600 kB min 的 JS（且 `r1xx` 后 ES module + 构建流程）。
本项目的渲染需求只有**线 + 点 + 网格**三类图元，**手写是更划算的一边**；
一旦要做光照/材质/贴图/大量文字标注，再评估 three.js。

### 6.3 明确**不做**的

* 图1 / 图2 的第三维（§1）。
* plotly（§3.4）。
* 改 `tests/test_traj_plot.py` 的现有 23 项判据、以及任何已交付的 `figures/*`。

---

## 7. 需要用户拍板的点

> **已拍板（用户 2026-10-01，第 1 条）**：**替换**，不是并存 —— 用户原话
> "替换，但是图3 的关键点位注释和不同阶段颜色区分都保留，导弹到达开机距离后也要换色，
> 左下角的放大图有点何意味了去掉"。**但第 1 条里"23 项物化判据必须整体迁移"的估计是错的**：
> 8 条是 inset 自己的尺寸/闸门判据（随 inset 一起删），**15 条**（注记不重叠/不出界、线型、
> 字形、markdown、竖排标签、字节复现…）在 3D 口径下**一条都不用改**，只需把"面板"改成
> "3D 盒"；新增 3 条 3D 判据（主视图真的是 3D 且无 child_axes、注记不压轴刻度/轴标题、
> `t_beam` 两侧两色且切点重合）。落地与实测见 `docs/PLAN-FIG3-TRAJECTORY.md` §11。

1. **图3 静态 3D 是"替换俯视图"还是"新增一张并存的图"？**
   并存要多一份 `figures/fig_traj_default_3d.*`（PNG 246 kB + PDF 21 kB + SVG 55 kB ≈ 322 kB 入库），
   替换则现有 23 项物化判据必须整体迁移到 3D 口径。**建议并存**（回退成本最低）。
   → **用户选替换**；实际只删了 8 条 inset 判据、加了 3 条 3D 判据（见本节开头）。
2. **交互视图的入口位置**：结果面板内嵌 `iframe`（一眼可见，但和现有"图卡片"布局要协调），
   还是新标签页打开（改动最小）。**建议内嵌 + 一个"新标签页"链接**。
3. **交互视图的轨迹点抽稀档位**：320 点（30 kB，现截图略见折线）/ 800 点（~70 kB）/ 1200 点（~100 kB）。
   **建议 800 起**。
4. **离线单文件版是否作为正式交付物**（每次出图后由 `run_traj` 顺带写一份
   `figures/fig_traj_default_3d.html`，约 44 kB）？若要，它进 `figures/` 就要纳入字节复现判据。
   **建议要**（这是"免安装分发"最贴合图3 交互诉求的形态）。
5. **是否接受"手写渲染器无文字标注"的初版**（轴刻度/节点名后置），还是首版就必须带标注
   （会多 0.5~1 d，且要新增"标注不重叠"的 3D 判据）。
6. **拖动方向已按"跟手"实现**（拖右 ⇒ 物体朝右走，§3.5.1），请上手确认手感。
   若要求反向，**改一个符号**（`applyDrag` 里 `cam.az +=` → `-=`），
   同时把 `tests/test_fig3d_spike.py::test_drag_sign_is_not_mirrored` 的期望反过来
   —— 现在这条用例会**故意变红**，防止有人顺手改反。
7. **初始视角**：当前默认 `az=-1.05 rad（-60°）/ el=0.36 rad（20.6°）`、自动 fit 到包围盒
   （本工况距离 39.4 km）。要不要给一个"更俯视"的默认（`el≈0.55`）让地面投影更明显？**建议保持现默认**。
8. **`?bg=transparent` 的嵌入形态**：内嵌时是全页 iframe（自带 chrome，看起来像换了个页面）
   还是只嵌 canvas 区（真正"继承宿主"但要拆 DOM）。本 spike 两者都支持，**没说死**（R9）。

---

## 8. 产物与复现锚点

| 路径 | 内容 | 字节 |
| --- | --- | --- |
| `spikes/fig3d/spike_a_mpl3d.py` | (a) 13 变体 × 3 格式 + 同进程/跨进程 sha256 比对 | — |
| `spikes/fig3d/out/a_report.json` | 同进程复现与体积/耗时的**原始记录** | 12 225 |
| `spikes/fig3d/out/crossA.json`、`crossB.json` | 两个独立子进程各一次出图的 sha256 | 10 507 / 10 504 |
| `spikes/fig3d/out/a/v02_traj_3d.png\|svg`、`v03_traj_3d_proj.png\|svg`、`v13_traj_preview_existing.png` | 图3 三维静态样本（其余 12 变体的产物用 `clean_out.py` 清掉，一条命令可重建全部） | 合计 ≈ 90 kB |
| `spikes/fig3d/make_viewer_data.py` | (c) 数据通路：`full` / `slim` / `--inline` 单文件 | — |
| `spikes/fig3d/fig3d_viewer.html` | (c) 手写 WebGL2 查看器模板（亮色 chrome + 拖动跟手，`?dragtest=N` 自检 / `?bg=transparent` 透明底） | 28 629 |
| `spikes/fig3d/spike_d_drag.js` | (c) **拖动方向"跟手"自检**（Node，复用 viewer 里真实的 `applyDrag`/`projectToScreen`；`tests/test_fig3d_spike.py` 断言 `ok=1`） | — |
| `spikes/fig3d/out/c/data.full.json` / `data.slim.json` | 两种数据形状 | 319 906 / 30 421 |
| `spikes/fig3d/out/c/fig3d_viewer_offline.html` | 单文件离线版（双击即看） | 55 385 |
| `spikes/fig3d/out/c/shot.png` | 无头 Edge **真渲染**截图（亮色主题） | 47 700 |
| `spikes/fig3d/node_spike_c_console.js` | (c) 不依赖浏览器的 CPU 量测（装配 / 矩阵 / 缓冲字节） | — |
| `spikes/fig3d/clean_out.py` | 产物清理器（只留入库样本） | — |
| `tests/test_fig3d_spike.py` | smoke：`python tests\run_tests.py -k fig3d`（16 项，约 1 s） | — |

**入库产物合计 ≈ 1.3 MB**（不含被清掉的 117 个可重建文件）。

---

## 9. 复现锚点与本阶段边界

* 本阶段**只新增**：`docs/FIG3D-FEASIBILITY.md`、`spikes/fig3d/**`、`tests/test_fig3d_spike.py`。
* **没有**改动 `src/**`、`figures/**`、`results/**`、`tests/test_traj*.py`、`tests/test_webui*.py`。
* `NOTES.md` 只做**字节追加**（`open("ab")`），不重写任何现有行。
* 所有数字的机器口径：本机 Python 3.14.7 / matplotlib 3.11.1 / numpy 2.5.2 / Node 24 / Edge
  （Chromium，SwiftShader 软渲染）。**没有**在别的机器/别的 matplotlib 版本上验证过。

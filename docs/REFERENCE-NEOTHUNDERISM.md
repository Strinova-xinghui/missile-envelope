# 参考站 `neothunderism.pages.dev` 的求解器（逆向解析）

> 目的：判断这个参考站能不能当我们**对拍的第二来源**，以及引用它有什么许可约束。
> 本文只保留**可公开的事实性要点**（事实与数值不受版权保护，表达受保护）；
> 完整取证（60 KB 报告 + 65 个原始文件、逐条原文引用）留在 `.tmp_test/neo-solver/`，
> 那是 gitignored 的临时目录，**不进公开仓**。解析日期 2026-10-02。

## 0. 一句话

它的算核**不在网页里**：前端只是表单，把输入 POST 给一台 Oracle VM 上的**服务端 Python**。
那份 Python 是 War Thunder 客户端 `aces.exe` 原生 6DOF 导弹弹道的**逐指令 float32 位序复原**，
源码公开在 GitHub `Leo-TY-H/wt-em-calc`（线上 `/api/health` 报的 commit 与读到的主干树 SHA 一致）。
它与我们内核的方法论同源（都是"原生 6DOF 的 float32 复原"），但**版本、参数逐弹不同、且自认整场次未验证**。

## 1. 关键定位（每条都能追到出处）

| 事实 | 证据 |
| --- | --- |
| 前端只做 UI、计算在服务端 | 站点 `config.js`：`apiBase` 指向 `https://150.136.64.13.sslip.io`，注释写着 Pages 只发界面、Oracle 跑计算 |
| 算核位置 | 仓库 `scripts/missile_model/`（77 文件）；入口 `scripts/missile_worker.py::simulate()`；服务层 `missile_service.py` 用 `subprocess` 喂 JSON、收 NDJSON |
| 线上版本 | `GET /api/health` → commit `a2c7ee60…`，release `v2026.10.01.2`（与该仓主干树 SHA 一致 ⇒ 引用即线上实际运行的代码） |
| 积分器 | float32 半隐式欧拉：位置用**旧速度**（`x += v·dt + ½a·dt²`）；加速度是 double，乘完 `dt` 才转 float32 |
| 步长 | 主步 `f32(1/48)` = 48 Hz；`properties.precision=2` ⇒ 刚体子步 **1/96 s**；线上响应实测 `model.step_s = 0.02083333395421505` |
| 轨迹落盘 | 每 3 步存一次（16 Hz）⇒ 行间隔 `0.3750000298023224 s`；与 `missile_worker.py` 的 `if i % 3 == 2` 一致 |
| 大气 | `kernels.py` 的常数与本仓 `AGENTS.md`「Atmospheric Density」记录的 DagorEngine 常数同源（`rho0=1.225`、`P0=101300`、`T0=288.16`、`hMax=18300` + 同一组 5 项密度多项式）；独立重算相对差 ≤ 4e-7，>18.3 km 的 `hMax/h` 尾部一致 |
| 制导律 | 比例导引，`omega_gain ≡ propNavMult`；**不是全局 4.0**：PL-12 = **6.0**、AIM-9L = **4.0** |
| 近炸 | 逐弹不同：PL-12 `radius = 10.0 m`、AIM-9L `radius = 5.0 m`；`timeOut` 是解锁延迟而非引信 |
| 开机/解锁 | PL-12：`lockDistance = 16000`、`lockAfterLaunch = true`、`warmUpTime = 0.3`、`lockTimeOut = 0.75` |
| 投放语义 | 要对接 `launch`（post-release）：t=0 原样接受输入；`launcher` 会跑一遍原生投放（`launch_mode=2`，加 `startSpeed`/散布/横向速度）。两者同给会报错 |
| 它自认的边界（逐字） | manifest 的 `scope` = "Research validation is component-level; website engagements are not whole-game validated."；线上 `model.limitations[0]` = "Whole engagements are not yet validated against live-game flights."；`component_provenance` = "2.59.0.34 profiles/core with separately recovered 2.59.0.38 shared arithmetic; whole-build equivalence unproven" |

⚠ 它**有两个**求解器，别混：`scripts/missile_model/` 只对应**导弹弹道**（与我们内核同类）；
对应我们**包线图**（ΔV–BC / β–γ 能力平面）的是 `scripts/em_solver.py`，本轮**未解析**。

## 2. 能不能对拍：能，但我方要先对齐四件事

1. **版本**：我们 `2.59.0.28`，它 `2.59.0.34`（且自认 .34 核心混用 .38 的共享算术）。
   ⇒ 出偏差时**先怀疑版本**，不要先怀疑某一方的实现。
2. **时间轴**：48 Hz 主步 / 1/96 s 子步 / 16 Hz 落盘 ⇒ `t_hit` 可以**逐帧**比，不是只能比终值。
3. **语义**：它只支持 `target_motion = constant_velocity`（没有 crank / 39 / 蛇形）
   ⇒ 我们图3 的机动想定**对不上**，只能对拍**直飞**想定。
4. **参数**：`propNavMult` 与近炸半径都是**逐弹**的 ⇒ 对拍前先把这两组数从它那边取全，
   否则差异会混进"参数不同"和"实现不同"两种来源。

## 3. 许可（公开前必读，这条最关键）

* GitHub `/repos/Leo-TY-H/wt-em-calc/license` → **404**；仓库 `license` 字段为空；
  树里搜 `licen|copying|notice|credit|acknowledg` **零命中** ⇒ **无 LICENSE = 默认保留全部权利**。
* **可以**：引用**事实与数值**并给出 URL（事实不受版权保护）；把它的公开 API 当**黑箱**取数；
  引用通用算法结构（半隐式欧拉）与游戏常数 —— 但游戏常数应从我方 `E:\WT` 自取，只把它当交叉核对。
* **不可以**：把它的代码或公式文本搬进本仓、做代码级翻译（构成派生作品）、打包它的 profile JSON
  或其 Windows 资产。
* 若在文档里引用它的数值，用这种标注：

  > 数值取自 `neothunderism.pages.dev`（服务端实现见 `github.com/Leo-TY-H/wt-em-calc`，**该仓库无 LICENSE**），
  > 仅作事实性引用与交叉核对，未复制其代码。

* 注意它的 `launch-profiles/*.json` 与 `radar-launch-properties.json` 是从 `aces.exe`/blkx 提取的
  **游戏数据**（权属归 Gaijin）—— 与我们已在用 `E:\WT` 派生数据同类，**不必再多引一层**。

## 4. 没查清的（照实记）

1. `baseIndSpeed = 1800.0` 的消费点找不到：只看到 `base_speed_squared = 250000.03…`（≈500²）用于动压，
   与 `1800²` 不符；grep 已下载的全部源码 `baseIndSpeed` 零命中。
2. `kernels.py::aero_properties()` 疑似**死代码**（把 blkx 参数换算成 `front_area`/`inertia` 等），
   全仓无调用者；线上用的是**预先算好写死在 JSON 里**的值 ⇒「从 blkx 复现同一组气动参数」
   这一步**不可直接复核**（对拍时最可能踩的暗坑）。
3. Cython 加速层：`WT_MISSILE_BACKEND=auto` 会加载编译扩展并替换 `f32/add/sub/mul/div`；
   未下载/未反编译那个 `.pyd`，响应里也没有字段说明线上跑的是 `compiled` 还是 `python`
   ⇒ 无法完全排除极少数情况不逐位一致。
4. `radar-launch-properties.json`（470 KB）未分析 ⇒ 雷达弹导引头模式/门限的还原**不完整**。
5. `em_solver.py`（88 KB）与 `/api/meta`（4.3 MB 飞机目录）**未读** —— 前者才是对应我们包线图的那部分。
6. 该站点 SPA 有**全路径回退**：任何未命中路径都返回同一份 HTML 的**假 200**（近 10 KB）——
   抓资源时必须核对内容，否则会把回退页当源码。
7. 它自认"整场次未对实机验证" ⇒ **不能当权威**，只能当第二来源。
8. **我们与它的实测差异还没做**（本节只是可行性判断，不是对拍结论）。

## 5. 若要对拍，下一步的三件事

1. 取全它对 PL-12 的 profile（`propNavMult`、近炸半径、`lockDistance`、投放语义），
   与我们 `docs/SOLVER-API.md` §1 的 `Scene` 做一次字段级映射表。
2. 选**直飞、无机动**的 5~10 个工况（同一初速/高度/距离），两边各跑一次，比 `t_hit` 与逐帧弹道；
   差异按"版本 / 参数 / 调度"三类归因（它自己给的怀疑顺序也是这个）。
3. 把结果写进 `docs/SOLVER-API.md` §4（实测到的内核能力边界）或新开一节；
   **只记数值与结论，不搬它的代码**。

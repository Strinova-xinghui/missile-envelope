# 导弹包线图

> ⚠ **本公开仓库含求解器内核（自有代码），但不含 War Thunder 游戏数据**：
> `vendor/wt-missile/wt_missile.py` 自 2026-10-01 起**归本项目作者本人所有**，随仓库公开分发、
> 由本仓库 `LICENSE` 覆盖；而它硬依赖的 **168 份 `.blk` 游戏数据**（`vendor/wt-missile/inputs/`，
> 权利归 Gaijin）**不进这个仓库**（见 `docs/OPENSOURCE-READINESS.md` §0）。
> 第一次 clone 之后请先按 [`vendor/README.md`](vendor/README.md) 把游戏数据放回原位并核对 SHA-256；
> 在数据到位之前，测试**不会红** —— 需要它的用例会打印一行说明后**跳过**
> （`-k flightpath` / `-k form_dirty` / `-k printed_text` 这 **50 项**仍然真跑真绿；
> 全量 402 项在有内核、无数据时是 **254 通过 / 148 跳过 / 0 失败**（实测 2026-10-02，合并 webui 后重测），见
> [`docs/OPENSOURCE-READINESS.md`](docs/OPENSOURCE-READINESS.md) §10.3）。
>
> 本项目是**独立社区研究项目**，与 Gaijin Entertainment / War Thunder
> **没有任何隶属、赞助或背书关系**。完整免责声明与数据来源见文末 §9。

**11 型主动弹的两张能力图**（同一套 vendor 求解器现算的数据）：

1. **图1 · ΔV–BC 包线图**：`(总增速 ΔV, 简化弹道系数 BC)` 散点，叠加基准弹的等命中时间线；
2. **图2 · β–ginv 能力平面**：`(β 直飞保能, ginv = 1/γ 转向能力)` 散点，
   叠加等 `n*` **直线**（过原点），
   再叠一层固定 ΔV 的仿真等时线。

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"

python -m missile_sim                     # 图1：全 11 型散点 + PL-12 基准 + 1 s 等时线（约 25 s）
python -m missile_sim --no-iso            # 图1 只要散点（秒级）
python -m missile_sim --figure bg         # 图2：β–ginv 平面 + 仿真等时线（1032 工况，约 20 s）
python -m missile_sim --figure bg --bg-no-scan   # 图2 只要参考图那一套（秒级）
python -m missile_sim --figure both --tag all    # 两张图一起出
python -m missile_sim --list-missiles
python tests\run_tests.py                 # 自检（402 项，约 2.6 min），不需要装 pytest
```

产物落在 `figures/`（png/pdf/svg）与 `results/`（csv/json），都是**逐字节可复现**的。

> **2026-09-27：外壳整体重建（分支 `restart`）。**
> 旧外壳 —— `flash` 公式引擎、`pro`/`unicorn` 原生 ELF 后端、三段式脚本流水线、
> `configs/*.json` 输入文件、`--burn` / `--aero` / `--loft` / `--bc-anchor` 这类旋钮 ——
> **已全部删除**。它们对内核对内核是惰性的，留着只会让人以为改了物理。
> 重建的来龙去脉（含用户拍板的 8 项决定）见 [`docs/RESTART-PLAN.md`](docs/RESTART-PLAN.md)；
> 内核的输入/输出契约见 [`docs/SOLVER-API.md`](docs/SOLVER-API.md)。

> **图2（β–ginv 能力平面）在 `图2` 分支上，从 `restart` 出。**
> 定义、与内核的一一对应、黄金值、适用边界见 [`docs/BETA-GAMMA.md`](docs/BETA-GAMMA.md)；
> 工程侧（两层怎么叠、注入踩过的静默 no-op）见 `docs/RESTART-PLAN.md` §10。

---

## 1. 这张图在说什么

### 散点：11 型弹的 (ΔV, BC)

每型的 ΔV 与 BC **从求解器自己的 blk 现算**（`mapping.blk_metrics`），不读任何外部 JSON 池 ——
所以散点与求解器物理**同源**，不可能出现"池里写的是一个版本、引擎跑的是另一个版本"。

* `ΔV`：真空等效总增速（两级弹是两级之和），公式见 [`AGENTS.md`](AGENTS.md) 的权威 `metrics()`。
* `BC`：简化弹道系数 `BC = 干重 / (CxK · (口径/2)² · π)`。**口径在 blk 里已经是米**。

### 等时线：环境不变，穷举 (ΔV, BC)

一条等时线 = **命中时间相同**的那些 (ΔV, BC) 组合连成的线。做法：

1. 固定环境与双方状态，只让基准弹的 `(ΔV, BC)` 在网格上变 ——
   通过两个乘数注入：`thrust_scale = ΔV目标/ΔV基准`（缩推力）、
   `cx_scale = 干重/(BC目标 · SD · CxK基准)`（缩阻力系数）；
2. 网格步长 **ΔV 10 / BC 25**（照旧），逐格点真跑一次求解器；
3. 把 `t_hit` 排成矩阵，取整秒等值线。

所以等时线是**真算出来的**，不是拟合。默认步长 **1 s**（`--iso-step`）。

### 第二张图：β–ginv 能力平面（`图2` 分支）

> ⚠ 纵轴自 2026-10-04 起是 **`ginv = 1/γ`**（`m²/kg`，越大越好）—— 与 β 同为「向上＝更好」。
> 物理 γ 的定义与内核注入未变，换算只在 `bg.ginv_of()` / `bg.gamma_of()` 一处，
> 见 `docs/BETA-GAMMA.md` 顶部口径块。

横轴 **β = 燃尽质量/(SD·CxK)** 管"直飞保能"（越大越好），纵轴
**γ = 燃尽质量·SD·CxK·CxAoA/(SL²·CyK²)** 管"转向损失"（越小越好）。
**β 与第一张图的 BC 是同一个数**，所以两张图共享一个坐标轴。

图上两层：

* **参考层**：11 型散点（点径与第一张图一致）+ 等 `n*` 双曲线（`n*` = 机动损失恰好等于基础阻力损失的过载），基准弹**涂绿**标出；
* **仿真层**：把基准弹的 ΔV 固定住，在 β×γ 网格上只改 `CxK` 与 `CxAoA` 扫出的命中时间等时线。
  不要这层就加 `--bg-no-scan`。

⚠ **一个必须知道的读法**：迎头直飞这种几乎不机动的工况下，等时线**近乎竖直** ——
命中时间几乎只由 β 决定，γ 要等到需要大过载转弯时才显出来。这是物理，不是画错：
机动损失 `a_loss = q·f/β + γ·F·(n·g0)²/q`，低过载时基础项主导。

完整定义、与内核的一一对应、黄金值、适用边界见 [`docs/BETA-GAMMA.md`](docs/BETA-GAMMA.md)；
机动目标工况的可行性（能让 γ 显出来的那条路）见 [`docs/MANEUVER-TARGETS.md`](docs/MANEUVER-TARGETS.md)。

### 怎么看图4：空战沙盒（没有静态成品，回放看）

一个机动想定的轨迹图 —— **不扫参数，画一个工况**，只跑**被选中的基准弹**（`--standard`，默认 PL-12）：

目标直飞 → 看到 RWR 告警后 crank 至 70° → 导弹**导引头开机**后转入正 39 位（正侧方 90°），
可叠加俯仰震荡。图上节点 = 发射 / 开始 crank / crank 转完 / 导引头开机 / 开始转入 39 / 命中或结束；
「开机」与「开始转入 39」之间隔着**反应延迟**（`--traj-react-delay`，默认 1.0 s），
所以是两个分开的点 —— 延迟期间目标还在原航向上飞。

```powershell
python -m missile_sim --figure traj                 # 图4：跑一个机动想定（crank → 39），不出静态图
python -m missile_sim --figure four                 # 一次出四块（沙盒 + 图1 + 图2 + 图3；`all` 是 four 的别名）
```

常用旋钮（都加 `--traj-` 前缀）：

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--traj-t-crank` | 8.0 s | 发射后多久开始 crank |
| `--traj-crank-deg` | 70° | crank 离轴角 |
| `--traj-crank-g` | 9 G | crank 段转向过载 |
| `--traj-beam-deg` | 90° | 39 位离轴角（90 = 正侧方） |
| `--traj-beam-g` | 9 G | 转入 39 的转向过载 |
| `--traj-lock-m` | 该弹 `guidance.lockDistance` | 开机距离（PL-12 / R-77 系列 16 km，120 系列 / MICA / Derby / AAM-4 / R-Darter 20 km） |
| `--traj-react-delay` | 1.0 s | 看到告警到开始转入 39 的反应时间 |
| `--traj-weave` / `--traj-no-weave` | 关 | 俯仰震荡（默认振幅/频率待用户经验数据） |
| `--traj-t-beam` | 反求 | 显式钉住开机时刻（复现用；钉住即跳过第一遍） |

⚠ **开机距离那个字段内核根本不读**（`wt_missile.py` 里 grep 该字段名零命中），它是外壳自己定的
"导引头开机"口径：跑**两遍** —— 先在**不含 39 腿**的轨迹上求首次 `range ≤ lockDistance` 的时刻
（一遍法，不自指），再跑正式工况加 39 腿。所以 fast 档也要约 0.4~0.5 s，不是一次求解。
⚠ **反应延迟帮的是导弹**（延迟期间目标在 110° 上仍有接近分量），完整口径见
[`docs/MANEUVER-TARGETS.md`](docs/MANEUVER-TARGETS.md) §8.10。

### 轴为什么每次不一样

范围随**选中弹**自适应（`figures.adaptive_axis`）：全部 11 型时约 ΔV 804~1116 / BC 2500~3751，
主刻度 30/100、次刻度 10/50（照旧）；只选一两型时会收紧范围并把刻度按 nice 序列下调。
想固定就用 `--xlim 800,1110 --ylim 2450,3850`。

---

## 2. 输入

### 2.1 环境与双方状态（`Scene`）

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--range` | 50000 | 双方**水平**距离 [m]（斜距由高度差现算，**不是**斜距） |
| `--alt` | 10000 | 发射高度 [m] |
| `--target-alt` | 同发射高度 | 目标高度 [m] |
| `--bearing` | 0 | 目标**方位角** [°]：0 = +x，正 → +z |
| `--vm0` | 300 | 载机速度 [m/s] |
| `--launch-heading` | 0 | 载机航向 [°] |
| `--launch-pitch` | 0 | 载机速度俯仰 [°]，正 = 爬升 |
| `--target-speed` | 300 | 敌机速度 [m/s] |
| `--target-heading` | 180 | 敌机航向 [°]（180 = 迎面） |
| `--target-pitch` | 0 | 敌机速度俯仰 [°]，正 = 爬升 |
| `--duration` | 150 | 请求时域上限 [s] |
| `--dt` | 0.0208333 | 物理步长 [s] = 1/48，**不要改**（C 快路径的固定步长条件） |
| `--observation` | ideal | `ideal` / `locked` |
| `--hit-radius` | 0 | 几何接触半径 [m]；0 = 只用求解器自己的近炸判定 |

⚠ **`--tier standard`（算术后端）与 `--standard PL-12`（基准弹）是两件不相干的事。**

### 2.2 坐标与角度约定（3D）

* **x / z 水平，y 向上。**
* 航向 `heading_deg`：**0° = +x**，正方向转向 **+z**。
* 俯仰 `pitch_deg`：**正 = 爬升**。
* 速度用「标量 + 航向 + 俯仰」表示，`velocity_vector()` 保证模长恒等于标量。
* `range_m` 是水平距离；`range_slant_m = hypot(range_m, Δh)`。

求解器是原生 3D，所以**发射方与目标方都能给方向 + 俯仰**。

### 2.3 弹池与档位

```powershell
python -m missile_sim --missiles "PL-12,R-77-1,120A"   # 自选子集（顺序照你给的）
python -m missile_sim --standard 120C                  # 换基准弹（等时线跟着换）
python -m missile_sim --tier standard                  # 纯 Python 档（慢，用于对拍）
python -m missile_sim --input scene.json               # 从 JSON 读工况
```

⚠ **PowerShell 里 `--missiles` 的逗号会被当数组分隔符，必须加引号。**
弹池 11 型：`120A` `120C` `120D` `MICA` `AAM-4` `PL-12` `PL-12A` `R-77` `R-77-1` `Derby` `R-Darter`。
未知弹名**硬拒绝**，不做近似替代。

---

## 3. 输出产物

以 `--tag demo` 为例：

| 文件 | 内容 |
| --- | --- |
| `figures/fig_isotime_plane_demo.{png,pdf,svg}` | 图，三格式 |
| `results/plane_demo_cases.csv` | 每个网格点一行（ΔV / BC / 乘数 / 命中 / `t_hit` / 最高点 / 末速 / backend） |
| `results/plane_demo_isolines.csv` | 等时线的点（层级 / ΔV / BC / 是否闭合） |
| `results/plane_demo.json` | manifest：出处、档位、backend、场景、网格、命中率 |
| `results/compare_demo.csv` | 逐型对比表（每型一发标称弹道） |

图2（`python -m missile_sim --figure bg --tag demo`）另有一套，**列名写 β/γ**：

| 文件 | 内容 |
| --- | --- |
| `figures/fig_bg_plane_demo.{png,pdf,svg}` | 图2，三格式 |
| `results/bg_demo_points.csv` | 逐型一行：β / γ / ΔV / Q / `n*` / R / `β_eff` |
| `results/bg_demo_cases.csv` | 每个网格点一行（**β_target / γ_target** / 三个乘数 / 命中 / `t_hit` / …） |
| `results/bg_demo_isolines.csv` | 仿真等时线的点（层级 / β / γ / 是否闭合） |
| `results/bg_demo.json` | manifest：固定住的 ΔV、参考工况（高度/速度/q/f/F）、网格、双向单调性自检 |

图4（空战沙盒）只落**产物**（`python -m missile_sim --figure traj --tag demo`）——
它**不出任何静态图**（2026-10-03 起连"输入阶段 3D 预览"也删了）：

| 文件 | 内容 |
| --- | --- |
| `results/traj_demo_missile.csv` | 导弹航迹逐采样点（`t_s / x_m / y_m / z_m / v_ms / mass_kg / thrust_N / range_m`） |
| `results/traj_demo_target.csv` | 目标航迹逐采样点（`t_s / x_m / y_m / z_m`，同一坐标系） |
| `results/traj_demo_segments.csv` | 分段表（`t0_s / t1_s / kind / label / phase / heading0_deg / heading1_deg / color_key / truncated`） |
| `results/traj_demo.json` | manifest：想定输入、锚点（`t_beam_s` / `lock_distance_m` / `completed` / 开机时航向）、分段、节点、两遍结局 |

⚠ 航迹列名里的 **`x` / `z` 是水平面**（`heading 0 = +x`、`90 = +z`）、**`y` 是高度** ——
别按"x 水平、y 水平、z 高度"的直觉读。要看轨迹请用**沙盒页**（`/fig4?job=<id>`）或
3D 查看器（`/viewer3d?job=<id>`）回放这次任务的产物 —— `--figure traj` 本身**只解算 + 落
CSV/JSON，不出图**。（"解算前先看计划航迹"的 3D 预览 2026-10-03 已删：用户口径是
"图4 的静态 3D 图不出了，只保留可交互沙盒即可"。）

**未命中一律留空**（CSV 空串、表格 `—`）—— 绝不写 0，否则会被读成"0 秒命中"。

图与 CSV 都**逐字节可复现**：`savefig` 的元数据时间戳被压制（PDF `CreationDate`/`ModDate`、
SVG `Date`、PNG `Software`），matplotlib 用 `id()` 派生的 SVG 元素 id 也被重编号。
只有 `results/*.json` 会因嵌入耗时而有正常 diff。

---

## 4. 两个档位

两档**物理完全相同**，只差算术路径：

| 档位 | 后端 | 说明 |
| --- | --- | --- |
| `fast` | `compiled-c` | 同一物理编译成 C 内核；**没有编译器时回落到 `python-legacy`**，并在产物里报告原因 |
| `standard` | `python-standard` | 纯 Python 逐物理步 |

⚠ **默认值分层是刻意的，不是笔误**：

| 层 | 默认档位 | 为什么 |
| --- | --- | --- |
| 命令行 / WebUI / `workflow` / `report` | `fast` | 用户要的是快 |
| `solver.run()` / `engine.Engine` | `standard` | 底层 API 不该默认依赖一台装了 C 编译器的机器 |

本机（VS 2022 MSVC 19.44）C 内核已缓存在 `%LOCALAPPDATA%\wt-missile\compiled-fast\`，
60 s 金标工况实测 **1765 → 77 ms（约 23×）**，逐位一致。
换机器后不要引用这个数字：跑一次读产物里的 `backend` / `fallback_reason` ——
`Shot.backend` **只认真跑过的证据**。

---

## 5. WebUI

```powershell
python -m missile_sim.webui          # 打开 http://127.0.0.1:8765/
```

表单式输入工况与弹池，提交后**跑成后台任务**，页面轮询 `/progress/<id>` 显示进度 ——
一次扫描要几十秒，同步阻塞会把页面卡死。

高级区里有 **「出哪张图」**（`plane` = 图1 / `bg` = 图2），以及图2 专属的一栏
（β/γ 网格步长、固定 ΔV、参考过载、参考工况高度/速度）。下面三个按钮对两张图都通用：

| 按钮 | 图1 | 图2 |
| --- | --- | --- |
| 单工况试算（同步） | 基准弹标称值一发 | 同上（图2 的仿真层也固定这个 ΔV） |
| 提交扫描 | ΔV×BC 网格 + 等时线 | β×γ 网格 + 等时线 |
| 只出图不扫描 | 只出散点 | 只出参考图那一套（散点 + 等 n* 线） |

---

### 5.1 打包成免安装版发给别人

要让**没装 Python 的人**也能直接用：

```powershell
python make_dist.py --prepare    # 一次性：准备内嵌 Python（需联网，约 90 MB）
python make_dist.py --zip        # 组装 + 裁剪 + 冒烟测试 + 打包
```

产物解压后**根目录只有一个 `启动.bat`**，双击就进 UI（浏览器自动打开），其余全在
`app/` 里。实测解压 132.7 MB、zip 53.8 MB，内含 Python 3.14 + numpy + matplotlib +
预编译 C 内核 + 中文字体子集 —— 对方**什么都不用装、运行时不用联网**。

组装脚本自己会跑一次冒烟测试（用分发包自己的解释器出 png/pdf/svg），
裁错依赖或路径写错都会当场失败，不会等对方双击才发现。

细节、体积构成与踩过的坑见 [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md)。

## 6. 代码结构

`src/missile_sim/` —— **每个职责只有一个出处**：

| 模块 | 职责 |
| --- | --- |
| `spec.py` | 契约：`Scene` / `Scaling` / `Shot` / `MissilePoint` / `AxisSpec` / `PlaneGrid` / `IsoGrid` |
| `solver.py` | **唯一**与 `vendor/wt-missile/` 的接触面 |
| `mapping.py` | `(ΔV, BC) ↔ (thrust_scale, cx_scale)` 的唯一算法 + 权威 `BlkMetrics` |
| `pool.py` | 11 弹池；ΔV/BC 从 blk 现算 |
| `engine.py` | 进程池 + 按档位分库的结果缓存 |
| `grid.py` | 网格 → `t_hit` 矩阵 → 等时线提取 |
| `figures.py` | **唯一**出图处（含图上的全部文案） |
| `record.py` | CSV / 摘要 / manifest / 出处块 |
| `workflow.py` | 端到端编排 |
| `cli.py` | 命令行 |
| `targets.py` | 输入契约层：想定表单 → `Scene`、预置库、**求解器兼容性前置校验** |
| `report.py` | 逐型对比表 |
| `webui.py` | 本地网页表单（纯标准库） |
| `webui_static/` | 首页的 HTML / CSS / JS（纯静态资源，`GET /static/<name>`；见 [`docs/WEBUI.md`](docs/WEBUI.md)） |

依赖只有 `vendor/wt-missile/` + numpy + matplotlib。

---

## 7. 文档索引

| 文档 | 什么时候看 |
| --- | --- |
| [`docs/SOLVER-API.md`](docs/SOLVER-API.md) | **要换求解器时唯一要读的**：输入契约、ΔV/BC→乘数映射、输出契约、实测到的内核能力边界 |
| [`docs/RESTART-PLAN.md`](docs/RESTART-PLAN.md) | 重建的架构决策、用户拍板记录、分工、待办 |
| [`AGENTS.md`](AGENTS.md) | 仓库约定：权威公式、数据源、行尾纪律、提交规范 |
| [`docs/NEW-SOLVER-HANDOFF.md`](docs/NEW-SOLVER-HANDOFF.md) | 内核交接原文（含 C 内核构建配方） |
| [`docs/OPENSOURCE-READINESS.md`](docs/OPENSOURCE-READINESS.md) | **接 GitHub 前的合规审计**：哪些资产不能公开、git 历史怎么处理、许可怎么选 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 想改代码 / 提 PR 先看这份（含提交前必过的四条判据） |
| [`vendor/README.md`](vendor/README.md) | 内核随仓；**游戏数据要自备** —— 落位步骤、哈希校验、数据缺席时会跳过哪些用例 |
| [`NOTES.md`](NOTES.md) | 决策与踩坑的流水记录 |
| `docs/SHELL-REBUILD-FEASIBILITY.md` | 重建前的评估报告（拍板依据） |

---

## 8. 已知限制

* **敌机轨迹是"开环预设"，不是闭环反应**：求解器没有实时/闭环的目标状态输入入口，也没有
  "导引头开机 / pitbull"事件。所以图4 能给的只是**分段航向指令**（直飞 → crank → 39 位，
  可叠震荡），由外壳解析编译成内核的 `maneuvers`（见 `src/missile_sim/flightpath.py`）；
  `samples` / `turn_rate` / `maneuvers` 在核心里**三选一互斥**，且 `samples` 必须从 t=0 起
  覆盖整个 `duration_s`。"看到告警才转"要靠外壳的**反应延迟**近似，不是内核行为。
  详见 `docs/SOLVER-API.md` §4 与 `docs/MANEUVER-TARGETS.md`。
* **欧拉法 + 固定步长**：`dt` 必须落在内核允许区间内，改大会被拒绝。
* **ΔV/BC ↔ 乘数是等效映射**，不是改发动机：它复现的是"同样总增速/同样弹道系数"的弹道，
  不代表真实的推力曲线或气动外形。
* 模拟器自身的**绝对阻力水平未标定**：字段相关性不等于引擎公式证明。
* 旧口径（`flash` 引擎的燃烧/气动/高抛公式、`--burn`/`--aero`/`--loft` 旋钮、三段式流水线）
  已随外壳删除；需要查历史时用 `git show <旧提交>:README.md`。

---

## 9. 免责声明、许可与数据来源

### 9.1 独立社区项目

本项目是一个**独立的社区研究项目**，与 **Gaijin Entertainment** 及
**War Thunder** 没有任何隶属、赞助、合作或背书关系。项目名、图上文字与本仓库文档中
出现的任何型号名（PL-12 / AIM-120 / R-77 / MICA / Derby / AAM-4 / R-Darter 等）
**仅用于技术指代**，相关商标与名称的权利归各自持有者。

### 9.2 产物是仿真结果，不是武器数据

本仓库的图与表是**对一个公开社区求解器的数值仿真结果**：

* **不是**实弹性能数据，**不能**用于任何工程、作战或评估用途；
* ΔV / BC 与乘数之间是**等效映射**（同样总增速 / 同样弹道系数），不代表真实推力曲线或气动外形；
* 模拟器自身的**绝对阻力水平未标定**：字段相关性不等于引擎公式证明；
* 所有数字都必须连同**来源版本**一起读（`WORK` = 2.59.0.11 / git tag / blk 现算），
  因为游戏数据每个版本都在改。

### 9.3 数据来源与版本标注方式

| 数据 | 来源 | 标注方式 |
| --- | --- | --- |
| 单弹 ΔV / BC | 求解器内核自带的 `.blk`（2.59.0.28），由 `mapping.blk_metrics()` **现算** | 产物 manifest 里的 `standard.tag` / `profile_hash` / `resource` |
| 求解器物理 | **本项目自有的**纯 Python 6DOF 复刻（内核自 2026-10-01 起归本项目作者，随仓分发），`MODEL = python-game-6dof-v1` | `shot.identity` / `EngineStamp.resources`（含 `wt_missile.py` SHA-256） |
| 权威公式交叉核对 | 社区数据挖掘工作流的 `metrics()`（外部，仓库内复刻在 `scripts/missile_metrics.py`） | `results/version_metrics.json` 的 `formula_source` |
| 参考图 | 用户提供的 **2.57 基线**对照图（`results/reference_fig.png`） | 只作对比，不进图；来源与处置建议见 §9.4 |

`figures/` 与 `results/` 里的每个产物都是**逐字节可复现**的（`savefig` 元数据时间戳被压制、
SVG 元素 id 被重编号），复现命令见 README §1。

### 9.4 本仓库**含内核**、**不含**哪些东西（以及为什么）

**内核源码 `vendor/wt-missile/wt_missile.py` 是含在这个仓库里的** —— 它自 2026-10-01 起归本项目作者本人所有，由本仓库 `LICENSE` 覆盖（归属转移的来龙去脉见
[`docs/OPENSOURCE-READINESS.md`](docs/OPENSOURCE-READINESS.md) §0）。不随仓的只是它硬依赖的游戏数据：

| 不含 | 原因 |
| --- | --- |
| `vendor/wt-missile/inputs/resources/2.59.0.28/**`（168 份 `.blk`） | **War Thunder 游戏数据**，权利归 Gaijin；已 `git rm -r --cached` + 写进 `.gitignore` |
| 任何 War Thunder 原始文件（`.vromfs.bin_u` / `*.blkx` / `WT.xlsx` / ELF） | 同上 |
| `results/reference_fig.png`（2.57 基线对照图） | 来源与授权**尚未确认**，标为"待用户确认"；移出它对测试 0 影响 |

**游戏数据**的落位目录形状、SHA-256 校验步骤、以及"数据缺席时哪些用例会跳过"见
[`vendor/README.md`](vendor/README.md)。完整的资产审计（每一项移出仓库的实测影响面、git 历史对象数、
两条落地路线、测试降级怎么关掉）见 [`docs/OPENSOURCE-READINESS.md`](docs/OPENSOURCE-READINESS.md)。

### 9.5 许可：AGPL-3.0-only（中文要点）

> ⚠ **非官方译述，冲突以 [`LICENSE`](LICENSE) 英文原文为准** —— 正文是 **GNU Affero General
> Public License, Version 3** 的官方全文（逐字未改，含 preamble 与文末 "How to Apply These
> Terms"；取自 <https://www.gnu.org/licenses/agpl-3.0.txt>，首行只加了版权归属）。
> SPDX 标识：**`AGPL-3.0-only`** —— **钉死这个版本**，不是 `AGPL-3.0-or-later`。
> 下面这张表只是帮你 30 秒内判断"我这么用行不行"。

本项目自 **2026-10-04** 起按 **[AGPL-3.0-only](LICENSE)** 授权（此前那份宽松许可已作废；
决策过程与三选一对比见 [`docs/OSS-LICENSE.md`](docs/OSS-LICENSE.md)）。它是 **OSI 认可的
开源许可**（"开源"这个标签照用），代价是**义务跟着分发走**：

| 你想这么用 | 结论 |
| --- | --- |
| 自己用 / 学习 / 研究 / 改一份自用 / 企业内部使用 | ✅ 允许（**不分发**就没有额外义务） |
| **商用**（做业务、做产品、做服务、接项目） | ✅ 允许 —— **AGPL 不禁商用** |
| 分发原版、或你改过的版本 | ✅ 允许 —— **必须**附上完整对应源码 + 本 `LICENSE` + 保留版权与许可声明 |
| 改过之后再分发 | ✅ 允许 —— 但要在明显位置写明**你改了什么**（保留声明、别把原作者的署名删掉） |
| 衍生作品**闭源**分发 | ❌ 禁止（copyleft：衍生作品必须同样以 AGPL 授权） |
| **把修改版闭源地对外提供服务** | ❌ 禁止 —— 这条正是选它的原因 |
| **通过网络对外提供本工具的能力**（SaaS / 在线接口 / 内网对外服务） | ⚠ **可以，但必须向使用者提供完整对应源码**（**第 13 条 "Remote Network Interaction"**） |
| 无任何担保 | ⚠ AGPL 第 15/16 条：软件**按原样提供，无任何担保** |
| 想豁免 AGPL 义务做闭源商用 | ✉️ **可联系作者另行授权**（联系作者即可谈） |

**为什么是 AGPL**：用户要拦的是"拿我们的高精度内核偷偷开个闭源服务去卖"。宽松许可拦不住这
件事（改了不发源码也合法），一刀切禁商用又会把教学/研究/企业自用一起挡掉。AGPL 第 13 条
把"通过网络提供服务"也算作分发触发点 —— 只要对外提供服务，使用者就有权拿到对应源码；
而它**不是**禁商用许可，正常商业使用不需要额外授权（想闭源商用才需要另行谈授权）。

**AGPL 覆盖什么、不覆盖什么**（写错比写漏更糟）：

| 东西 | 归谁 / 受哪份许可管 |
| --- | --- |
| 本仓库代码（`src/`、`tests/`、`scripts/`、`make_dist.py`…） | 本项目作者 ⇒ **由本仓 `LICENSE`（AGPL-3.0-only）覆盖** |
| 随仓内核 `vendor/wt-missile/`（`wt_missile.py` 等） | **本项目作者自有**（2026-10-01 归属确认）⇒ 同样由本仓 AGPL 覆盖，**不是**第三方代码 |
| War Thunder 游戏数据 `vendor/wt-missile/inputs/**` | **不在本许可覆盖范围内**，权利归 **Gaijin Entertainment** ⇒ 只能自用/小范围交流，**公开集一律不带 `inputs/`**（见 §9.4） |
| 内嵌 Python / numpy / matplotlib 等 / Noto 字体 | 各自许可（PSF-2.0 / BSD 系 / MIT / OFL-1.1）⇒ **都与 AGPL-3.0 兼容**，照旧随包保留声明（见 §9.6） |

`LICENSE` 一份覆盖**外壳代码与随仓内核源码**；`pyproject.toml` 里对应
`license = "AGPL-3.0-only"`（PEP 639 SPDX 表达式）+ classifier
`License :: OSI Approved :: GNU Affero General Public License v3`（wheel 的 METADATA 会写
`License-Expression: AGPL-3.0-only`，并把 `LICENSE` 打进 `dist-info/licenses/`）；
**免安装分发包**则把它放在 `app\LICENSE`（与 `app\README.md` 同层；漏拷会在组装期直接炸）。

⚠ **不做 per-file SPDX 头**（2026-10-04 决定）：仓库根 `LICENSE` + 项目级声明已足够，
逐文件加头属于收工后可选项、法律上不必要（记在 [`docs/OSS-LICENSE.md`](docs/OSS-LICENSE.md) 的遗留清单）。

### 9.6 第三方组件与游戏数据：**不归上面那份许可管**

上面那份许可只覆盖**本项目自己写的代码、随仓内核、以及自己生成的产物**。仓库里/包里还有别人的
东西 —— 它们各自的许可与权利**照旧生效**，既不被我们的许可覆盖，也不能被它改写；
分发时**必须一并带上它们各自的声明**（好消息：下面这些许可**都与 AGPL-3.0 兼容**，
可以与 AGPL 代码聚合分发，**不需要改任何代码**）：

| 随仓 / 随包的东西 | 权利方与许可 | 我们的义务 |
| --- | --- | --- |
| 内嵌 Python（免安装包 `app\python\`） | Python Software Foundation，**PSF-2.0** | 随包保留 `app\python\LICENSE.txt` 与各 `dist-info` 里的许可文本 |
| `numpy` | **BSD-3-Clause** | 同上（`app\python\Lib\site-packages\numpy*` 的 `dist-info`） |
| `matplotlib` 及其依赖 `Pillow` / `contourpy` / `kiwisolver` / `cycler` | **BSD 系**（每个包各自的 `dist-info`） | 同上 |
| `fonttools` / `pyparsing` / `six` | **MIT**（各自 `dist-info`） | 同上（MIT 与 AGPL 兼容，保留声明即可） |
| 中文字体子集 `app\fonts\NotoSansSC-subset.ttf` | SIL **OFL 1.1**（Noto Sans SC） | 分发时一并带上 OFL 文本；子集由 `make_dist.py` 从本机 Noto 字体现生成 |
| War Thunder 游戏数据 `vendor/wt-missile/inputs/**`（168 份 `.blk`） | **权利归 Gaijin Entertainment**，**不是**开源资产，**也不在 AGPL 覆盖范围内** | **不随仓库分发、不进公开渠道**；分发包里也只能自用/小范围交流（见 §9.4）；这条**与选哪个许可无关** |
| `results/reference_fig.png`（2.57 基线对照图） | 来源与授权**尚未确认** | 公开前要么移出公开集、要么先向原作者取得授权（见 §9.4） |

⚠ **灰色地带（与许可无关、但要心里有数）**：matplotlib 默认把文字转成路径，所以已入库的
**矢量产物全都内嵌了渲染所用字体的字形**——实测 `figures/` 里 **8 份**（4 张图的 SVG + PDF；
PNG 不内嵌）**全部**含 Microsoft YaHei 子集：SVG 里是 `id="MicrosoftYaHei-<n>"` 的字形路径，
PDF 里是 `XXXXXX+MicrosoftYaHei` / `…-Bold` 这类子集字体。公开前若想彻底干净，就用
**OFL 字体（Noto Sans CJK SC）重出这 8 份矢量产物**（PNG 一并重出以保持一致）
并更新字节复现基线（会动 `-k figures_repro` 与图1/图2 及预览的字节复现用例；**只改外观、不改任何数值**）。

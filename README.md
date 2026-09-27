# 导弹包线图

**11 型主动弹的「总增速 ΔV × 简化弹道系数 BC」散点，叠加基准弹的等命中时间线。**

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"

python -m missile_sim              # 默认：全 11 型散点 + PL-12 基准 + 1 s 等时线（约 25 s）
python -m missile_sim --no-iso     # 只要散点（秒级）
python -m missile_sim --list-missiles
python tests\run_tests.py          # 自检，不需要装 pytest
```

产物落在 `figures/`（png/pdf/svg）与 `results/`（csv/json），都是**逐字节可复现**的。

> **2026-09-27：外壳整体重建（分支 `restart`）。**
> 旧外壳 —— `flash` 公式引擎、`pro`/`unicorn` 原生 ELF 后端、三段式脚本流水线、
> `configs/*.json` 输入文件、`--burn` / `--aero` / `--loft` / `--bc-anchor` 这类旋钮 ——
> **已全部删除**。它们对内核对内核是惰性的，留着只会让人以为改了物理。
> 重建的来龙去脉（含用户拍板的 8 项决定）见 [`docs/RESTART-PLAN.md`](docs/RESTART-PLAN.md)；
> 内核的输入/输出契约见 [`docs/SOLVER-API.md`](docs/SOLVER-API.md)。

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

---

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

依赖只有 `vendor/wt-missile/` + numpy + matplotlib。

---

## 7. 文档索引

| 文档 | 什么时候看 |
| --- | --- |
| [`docs/SOLVER-API.md`](docs/SOLVER-API.md) | **要换求解器时唯一要读的**：输入契约、ΔV/BC→乘数映射、输出契约、实测到的内核能力边界 |
| [`docs/RESTART-PLAN.md`](docs/RESTART-PLAN.md) | 重建的架构决策、用户拍板记录、分工、待办 |
| [`AGENTS.md`](AGENTS.md) | 仓库约定：权威公式、数据源、行尾纪律、提交规范 |
| [`docs/NEW-SOLVER-HANDOFF.md`](docs/NEW-SOLVER-HANDOFF.md) | 内核交接原文（含 C 内核构建配方） |
| [`NOTES.md`](NOTES.md) | 决策与踩坑的流水记录 |
| `docs/SHELL-REBUILD-FEASIBILITY.md` | 重建前的评估报告（拍板依据） |

---

## 8. 已知限制

* **不支持敌机自定义轨迹**：求解器没有实时/闭环的目标状态输入入口。目标只支持
  **带方向 + 俯仰的匀速直飞**（`samples` / `turn_rate` / `maneuvers` 在核心里三选一互斥，
  且 `samples` 必须从 t=0 起覆盖整个 `duration_s`）。详见 `docs/SOLVER-API.md` §4。
* **欧拉法 + 固定步长**：`dt` 必须落在内核允许区间内，改大会被拒绝。
* **ΔV/BC ↔ 乘数是等效映射**，不是改发动机：它复现的是"同样总增速/同样弹道系数"的弹道，
  不代表真实的推力曲线或气动外形。
* 模拟器自身的**绝对阻力水平未标定**：字段相关性不等于引擎公式证明。
* 旧口径（`flash` 引擎的燃烧/气动/高抛公式、`--burn`/`--aero`/`--loft` 旋钮、三段式流水线）
  已随外壳删除；需要查历史时用 `git show <旧提交>:README.md`。

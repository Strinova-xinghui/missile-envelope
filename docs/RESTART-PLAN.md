# `restart` 分支：外壳重建 · 计划与拍板记录

> **用途**：上下文压缩或换会话后先读这一份 —— 分支怎么来的、删了什么、建了什么、
> 哪些事已经拍板、接下来谁做什么。
> 相关：`docs/SOLVER-API.md`（内核的输入/输出契约，**改内核只动 `solver.py`**）、
> `docs/SHELL-REBUILD-FEASIBILITY.md`（重建前的可行性评估）。

---

## 0. 一句话现状

**新外壳已端到端跑通。** 11 弹散点 + 1 s 等时线，1632 工况 / **23.5 s**（`fast`，jobs=8），
命中 1632/1632，PNG/PDF/SVG 三格式连跑两次 sha256 全一致。剩下的是**输入侧（WebUI）**与
**输出侧（对比表 / 图文案对齐）**两块，以及测试与文档收尾。

```
python -m missile_sim                                   # 默认：11 弹 + PL-12 基准等时线
python -m missile_sim --missiles "PL-12,R-77-1,120C"     # 自选弹池（PowerShell 里要加引号）
python -m missile_sim --range 50000 --bearing 45 --target-pitch 10
python -m missile_sim --no-iso                          # 只出散点（秒级）
python -m missile_sim --list-missiles                   # 弹池与现算 ΔV/BC
```

---

## 1. 分支与提交序列

**基线**：`restart` 从 `new`（`76c4671`）出。工作树的旧未提交改动**全部丢弃**（用户定案
"从零干净构建"）。挑 `new` 而不是 `main`，是因为 `new` 上有三件不可重建的资产：
`vendor/wt-missile/` 整包、权威公式 `scripts/missile_metrics.py`、以及评估/交接文档。

| 提交 | 内容 |
| --- | --- |
| `abe3e5d` | `refactor!:` 大扫除 —— 删 22 个旧脚本 + 16 个作废测试（8844 行） |
| `4cab029` | `feat(shell):` 新外壳 10 个模块；`docs:` SOLVER-API + 本文件 |
| `2f4a7fc` | `feat(shell):` targets / report / webui 三块 + 测试套件 + 脚注与弹名标签修正 |
| `691c669` | `docs:` `README.md` 全文重写、`AGENTS.md` 15 处修订、旧壳残留清理 |

> ⚠ **并发写警告**：开工当时有**另一个会话**在同一工作树推进（它建了
> `docs/PIPELINE-MAP.md` 与 `scripts/e2e_check.py`，是"渐进重构"路线，与本分支的
> **从零重建**互斥）。它的两份产物已备份为 `docs/_wip_PIPELINE-MAP.old.md` /
> `scripts/_wip_e2e_check.old.py` 待处置。**同一工作树同一时刻只能有一个写入者** ——
> 派子代理时必须按 §5 的写 scope 严格隔离。

---

## 2. 大扫除（已执行）

**删除**：`src/missile_sim/` 全部旧模块（31 个，含两代旧引擎 `sim/aero/ballistics/burn/
decide/atmosphere/pro/flash/native` 约 2800 行）；`scripts/` 22 个（16 个标定/对拍 +
`pipeline`/`workflow`/`workflow_web`/`make_missile_bc_overlay` + `build_standard_pool`/
`missile_sources`）；`tests/` 16 个用例文件。

**保留**：13 个 `E:\WT` 数据出处链脚本（`missile_metrics.py` 是保留脚本的依赖）；
`tests/{run_tests,_pytest_shim,conftest}.py`；`vendor/`（只读）；`figures/`、`results/`
的旧产物（旧 Pro/Flash 口径，作历史保留）；`results/pro_cache.json`、`missile_standards.json`。

**搬迁保留**（领域资产，改写进新模块）：`io.py` 的两条乘数公式 + 齐奥尔科夫斯基 →
`mapping.py`；`native._patch_profile` → `solver.py`；`standard.py` 的 11 弹清单 → `pool.py`
（**改为从 vendor 现算**）；`crossplot/plot` 的版式常量与等时线标注算法 → `figures.py`；
`scanner.Grid` + `sweep.extract_isolines` 的语义 → `grid.py`。

---

## 3. 新外壳模块（已落地）

| 模块 | 职责 | 行 |
| --- | --- | --- |
| `spec.py` | 契约：`Scene`/`Scaling`/`Shot`/`MissilePoint`/`AxisSpec`/`PlaneGrid`/`IsoGrid` | ~420 |
| `solver.py` | **唯一**与 vendor 的接触面（加载/身份/乘数/输出归一） | ~290 |
| `mapping.py` | `(ΔV,BC) ↔ (thrust_scale, cx_scale)` 的唯一算法 + 权威 `BlkMetrics` | ~180 |
| `pool.py` | 11 弹池：短名 ↔ vendor 预设名，**ΔV/BC 从 blk 现算** | ~150 |
| `engine.py` | 执行层：进程池 + 按档位分库的结果缓存 | ~230 |
| `grid.py` | 网格 → `t_hit` 矩阵 → 等时线提取 | ~170 |
| `figures.py` | **唯一**出图处：自适应轴散点 + 等时线 + 三格式可复现 | ~430 |
| `record.py` | CSV / 摘要 / manifest / 出处块 | ~150 |
| `workflow.py` | 端到端编排（`PlaneRequest` → 图 + 产物） | ~230 |
| `cli.py` | 命令行（参数优先级：命令行 > JSON > 默认值） | ~230 |

**关键简化**：**不再读 `results/missile_standards.json` 之类的 JSON 池** —— ΔV/BC 直接从
vendor 的 blk 现算，所以散点与求解器物理**同源**。实测 11 型与既有权威表**逐值一致**。

**已知行为差异（相对旧外壳）**：旧外壳里 `--aero/--burn/--loft/--loft-rule` 这类旋钮对内核
是惰性的却照常打印；新外壳**不提供**它们 —— 少一个参数，少一次"以为自己改了物理"的误读。

---

## 4. 拍板记录（用户 2026-09-27 定案）

| # | 事项 | 定案 | 状态 |
| --- | --- | --- | --- |
| 1 | 旧外壳处置 | 按评估报告 §3 **原地重建**，删除旧引擎与旧脚本 | ✅ 已执行 |
| 2 | 基线 | `restart` **从零干净构建**，丢弃旧未提交改动 | ✅ 已执行 |
| 3 | 自适应轴 | 范围**随选中弹**自适应；**网格步长（ΔV 10 / BC 25）与出图分辨率照旧** | ✅ 已实现 |
| 4 | 敌机自定义轨迹 | **跳过**（求解器无实时闭环入口）；只做**带航向的直飞** | ✅ 已实现 |
| 5 | 敌机航向 | **方向 + 俯仰都要**（比"只有方向"多一点） | ✅ 已实现 |
| 6 | 发射方 | **也做 3D**（航向 + 俯仰） | ✅ 已实现 |
| 7 | 输出内容 | **11 弹散点 + 等时线**（等时线 = 环境不变、穷举 ΔV×BC、筛命中时间相同的组合连线） | ✅ 已实现 |
| 8 | WebUI | **后台任务 + 进度条**（不做同步阻塞） | ✅ 已实现（纯标准库，只听 127.0.0.1、无鉴权、**没有取消按钮**） |

### 4.1 用户给的参考图（输出侧的对照标准）

`figures/fig_isotime_plane_default.png` 已经对齐它的**内容与版式**：

| 元素 | 参考图 | 现图 |
| --- | --- | --- |
| 内容 | 11 弹散点 + 1 s 等时线 + 色标 | 同 |
| 轴范围 | ΔV 800~1110 / BC 2450~3850（写死） | **自适应**（11 弹时算得 ≈804~1116 / 2500~3751） |
| 刻度 | 主 30/100、次 10/50 | 同（跨度小时按 nice 序列下调） |
| 高亮环 | 120C（历史设计：高抛基准） | **基准弹**（默认 PL-12，可换） |
| 画布 | 12×6.8 @110 dpi、PNG 300 dpi | 同 |

**输出侧待办**：文案对齐（标题「主动弹 总增速-弹道系数 与 等命中时间线」、轴标签
「总增速 ΔV（m/s）」/「简化弹道系数（BC）」、图例「最新版 blkx 弹值（11 型）」）+ 逐型对比表。

---

## 5. 分工与写 scope（三人并行，文件不重叠）

| 成员 | 职责 | **独占写 scope** | 禁止碰 |
| --- | --- | --- | --- |
| **A1 · 输入契约** | 用户想定 → `Scene` 的领域转换、预置想定库、**求解器兼容性前置校验**（对照 `SOLVER-API.md` §4） | `src/missile_sim/targets.py`、`tests/test_targets.py` | `spec.py`、`solver.py`、`engine.py`、`figures.py` |
| **A2 · WebUI** | 表单 + 后台任务 + 进度轮询 + 单工况/扫描两条路径 | `src/missile_sim/webui.py`、`configs/web_*.json`、`tests/test_webui.py` | 同上 |
| **B · 输出** | 逐型对比表（`report.py`）+ 图文案对齐参考图 | `src/missile_sim/report.py`、`src/missile_sim/figures.py`、`tests/test_report.py` | `spec.py`、`solver.py`、`engine.py`、`grid.py` |
| **Lead** | `spec.py`/`solver.py`/`engine.py`/`grid.py`/`workflow.py`/`cli.py`、文档、提交与验收 | 其余全部 | — |

**契约已冻结**：`Scene` / `Scaling` / `Shot` / `MissilePoint` / `AxisSpec` / `IsoGrid`
由 Lead 拥有；A1/A2/B 需要的字段已经全部就位，**不要再加字段** —— 缺什么先跟 Lead 说。

**A2 的两个技术雷**（已在 `webui.py` 的任务书里写明）：
1. Web 进程里跑 `ProcessPoolExecutor`：spawn 会重新 import 主模块，必须
   `if __name__ == "__main__"` + **不要在 import 期起服务**，否则子进程递归起服务器；
2. 扫描 fast 档 20 s+、standard 档约 6 min ⇒ **必须后台任务 + 进度轮询**，不能同步阻塞。

---

## 6. 待办与验收

| # | 事项 | 验收 |
| --- | --- | --- |
| 1 | `docs/SOLVER-API.md` | ✅ 已写（含内核能力边界实测、换求解器 5 步） |
| 2 | 3D 几何扩位 | ✅ 已实测：基准不回归（45.1861 s）、6 种 3D 工况跑通、round-trip 相等 |
| 3 | A1 / A2 / B 三块 | ✅ 全部 complete：A1 52 用例（6 个预置真跑）、A2 7 用例（真端口端到端）、B 12 用例 + 文案对齐 |
| 4 | `docs/RESTART-PLAN.md` | ✅ 本文件 |
| 5 | `NOTES.md` / `README.md` / `AGENTS.md` 跟进 | ✅ `NOTES.md` §10.14；✅ `AGENTS.md` 15 处修订（见 §8）；✅ `README.md` 全文重写 |
| 6 | 测试：Lead 新写 4 个用例文件 | ✅ 59 用例（17+15+20+7）；全量 **129/129 绿、exit 0** |
| 7 | 处置并发会话的遗留产物 | ✅ **已删除**（见 §8）：它们画的是已删的 `src/missile_sim/config.py` 那条流水线，改写成新架构没有价值 |
| 8 | 行尾纪律 | `git diff --stat` == `git diff -w --stat` |

---

## 7. 未决问题

1. **`figures.py` 的高亮环**：默认跟基准弹。参考图上是 120C（历史设计），要不要给
   `--highlight <弹名>` 参数？
2. **第二张图**是什么，用户说之后再定。
3. **`E:\WT` 数据链脚本**（13 个）保留在 `scripts/`，但新外壳**不依赖**它们 ——
   是否要移到 `scripts/datamine/` 以示区别？
4. **`Scene.range_m` 的语义**已从"斜距"改为"水平距离"（同高时两者相等，所以默认工况
   不受影响），`CACHE_SCHEMA` 因此升到 3。若要保留斜距口径需显式说明。

## 8. 收尾阶段记录（2026-09-27）

### 8.1 三块并行交付的结果

| 块 | 文件 | 状态 | 验收证据 |
| --- | --- | --- | --- |
| A1 输入契约 | `targets.py`（504 行）、`tests/test_targets.py`（52 用例） | ✅ complete | 6 个预置**真跑全命中**：head_on 45.1861（与金标逐位一致）/ tail_chase 29.0827 / beam_90 50.4061 / target_climb 42.6405 / target_dive 35.7659 / altitude_gap 41.7199 s |
| A2 WebUI | `webui.py`（1492 行）、`configs/web_default.json`、`tests/test_webui.py` | ✅ complete | 单工况 0.097 s；4×4 扫描提交 0.006 s 返回 → 16/16=100%；全尺寸 1632 工况 30.1 s done |
| B 输出侧 | `report.py`（277 行）、`tests/test_report.py`（12 用例）、`figures.py` 文案改造 | ✅ complete | 11 型逐型对比表（PL-12 45.1861 与金标一致）；三格式连跑两次 sha256 一致；未命中渲染 `—` 而非 0 |

**新增接口**（后续可依赖）：
* `targets`：6 个冻结签名 + `preset_form(name)`（选预置自动填表）、`check_missile(native_name)`、
  常量 `ALT_MAX_M=40 km` / `PITCH_LIMIT_DEG=90` / `MAX_STEPS=1e6`（**外壳输入域，不是内核实测边界**）。
* `report`：`compare()` / `write_compare_csv()` / `format_table()` / `run_compare()`；`MISS_PLACEHOLDER="—"`。
  一弹一个 `Engine`（引擎绑定 missile+metrics 是结构决定），11 次共用一份 `ResultCache`。
* `figures`：`plane_title(with_iso)` / `plane_subtitle(scene, *, standard=, tier=)` —— **图的文案唯一出处**；
  `workflow.py` 只负责调用，不再持有字符串。

### 8.2 清理（本阶段删除）

| 删除 | 原因 |
| --- | --- |
| `docs/PIPELINE-MAP.md` + `docs/_wip_PIPELINE-MAP.old.md` | 画的是 `src/missile_sim/config.py` 那条已删流水线 |
| `scripts/e2e_check.py` + `scripts/_wip_e2e_check.old.py` | 同上，检查的是已删模块 |
| `docs/MODEL-API.md` | 描述已删的 `model/` 包 |
| `AERO_PLAN.md` | 旧 `flash` 引擎的气动方案（该引擎已删） |
| `configs/{baseline,standard_120c5,workflow_example}.json` | 旧壳输入；新外壳**零引用**（弹池硬编码在 `pool.py`，ΔV/BC 现算） |

保留：`docs/NEW-SOLVER-HANDOFF.md`（内核交接，仍有效）、`docs/SHELL-REBUILD-FEASIBILITY.md`
（重建评估报告，拍板依据）、`configs/web_default.json`（A2 的）。

### 8.3 `AGENTS.md` 修订（15 处）

换掉了全部过时内容：模块清单、命令块、行尾清单、两个 ⚠ 段（`flash` 引擎 / `atmosphere.py` 已删）、
交接说明、Agent 指引。其中一处是**事实纠错**：旧文说"`cache_key()` 刻意不含 tier，靠分文件隔离" ——
新架构的 `cache_key()` **显式包含 tier**，并把 `CACHE_SCHEMA` 必须随 `Scene` 语义变化递增写成了硬规则。

### 8.4 测试运行器的一个坑（已修）

`tests/run_tests.py::_load_module` 用 `spec_from_file_location` 加载模块却**没有注册进 `sys.modules`**，
而 Python 3.14 的 `dataclasses` 会 `sys.modules.get(cls.__module__).__dict__` 回查 —— 于是
**任何在模块级定义 `@dataclass` 的测试文件都会在 collect 阶段炸掉整个测试跑**，报错还指向一个
语法完全正常的 `@dataclass` 行。已改为先注册再 `exec_module`，失败时摘掉半成品。

⚠ 连带结论：`-k` 是 **collect 之后**才过滤的，所以任何一个测试文件 import 失败都会让
`python tests\run_tests.py -k <你的>` 一起挂掉，看起来像"你的测试坏了"。

### 8.5 `git diff --stat` vs `-w --stat`

全局唯一的不一致在 `tests/run_tests.py`（15 vs 13 行），来源是把 `spec.loader.exec_module(mod)`
移进 `try:` 造成的**纯缩进变化**（4 → 8 空格），`-w` 按设计忽略它。**不是行尾问题**，
`AGENTS.md` 明确把"纯重新缩进"列为合法例外。其余文件两份 diff 逐字节一致。

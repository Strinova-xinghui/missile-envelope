# `restart` 分支：外壳重建 · 计划与拍板记录

> **用途**：上下文压缩或换会话后先读这一份 —— 分支怎么来的、删了什么、建了什么、
> 哪些事已经拍板、接下来谁做什么。
> 相关：`docs/SOLVER-API.md`（内核的输入/输出契约，**改内核只动 `solver.py`**）、
> `docs/BETA-GAMMA.md`（**图2**：β–γ 能力平面的定义、口径、反解、扫描与出图）、
> `docs/MANEUVER-TARGETS.md`（**机动目标可行性**：三条通道、实测数字、非单调陷阱）、
> `docs/SHELL-REBUILD-FEASIBILITY.md`（重建前的可行性评估）。

---

## 0. 一句话现状

**外壳已端到端跑通，两张图都在。** 

* 图1（ΔV–BC 包线图）：11 弹散点 + 1 s 等时线，1632 工况 / **23.5 s**（`fast`，jobs=8），
  命中 1632/1632。
* 图2（β–γ 能力平面，`图2` 分支）：11 弹散点（点径与图1 一致）+ 等 `n*` 双曲线，
  叠一层固定 ΔV 的仿真等时线，1032 工况 / **14 s**。

PNG/PDF/SVG 三格式对两张图都逐字节可复现。输入侧（WebUI）与输出侧（对比表 / 图文案对齐）
都已接入图2；`docs/BETA-GAMMA.md` §8 的 6 条待拍板全部给了默认值 + 覆盖开关。

```
python -m missile_sim                                   # 图1：11 弹 + PL-12 基准等时线
python -m missile_sim --figure bg                       # 图2：β–γ 平面 + 仿真等时线
python -m missile_sim --figure bg --bg-no-scan           # 图2 只出参考图那一套
python -m missile_sim --figure both --tag all            # 两张图一起出
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
| `cf37cc7` | `docs:` `README.md` 全文重写、`AGENTS.md` 15 处修订、旧壳残留清理 |
| （分发） | `feat(dist):` 免安装分发包 + 组装脚本 + 文档 |

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
| `record.py` | CSV / 摘要 / manifest / 出处块 | ~300 |
| `workflow.py` | 端到端编排（`PlaneRequest` → 图1；`BgRequest` → 图2） | ~430 |
| `cli.py` | 命令行（参数优先级：命令行 > JSON > 默认值；`--figure plane|bg|both`） | ~300 |
| `bg.py` | **图2 的域**：β/γ/Q/n\*/R/β_eff + β–γ 反解（`scaling_for`） | ~330 |

`src/missile_sim/` 现为 **14 个模块**（上表 + `targets` / `report` / `webui`）。
`bg.py` 是 `图2` 分支新增的：它与 `mapping.py` 平行 —— `mapping` 管 `(ΔV,BC)` 的乘数，
`bg` 管 `(β,γ)` 的乘数与派生指标，两者都只产出 `spec.Scaling`。

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

## 9. 免安装分发（2026-09-27 追加）

用户要求：「做成一个文件直接启动到 UI 的版本，其他文件放在二级文件夹里，我要发给别人交流」。
拍板走**免安装版**（对方零依赖）。实现 `make_dist.py`，说明 `docs/DISTRIBUTION.md`，
证据 `NOTES.md` §10.16。

产物 `dist/导弹包线图/`：**根目录只有 `启动.bat`**，其余全在二级目录 `app/`。
解压 132.7 MB / zip 53.8 MB。

| 决定 | 理由 |
| --- | --- |
| 内嵌 Python（embeddable 3.14.7）而不是 PyInstaller | 本机 Python 3.14.7 太新，打包器支持存疑；embeddable 用官方产物，稳且可复现 |
| 保住 `app/{src,vendor,figures,results}` 的相对结构 | `spec.ROOT = parents[2]` ⇒ 所有路径自动正确，**业务代码零改动** |
| `LOCALAPPDATA` 重定向，把预编译内核随包带走 | 对方没装 MSVC 也能吃 `compiled-c`；分发包里实测 `backend = compiled-c` |
| 随包思源黑体子集（3.6 MB） | 英文 Windows 上 YaHei/SimHei/SimSun 全没有，中文会变豆腐块；SIL OFL 可再分发 |
| 只裁 `tests/` 与 `bin/`（约 20 MB） | `PIL` + `fontTools` 实测是 matplotlib **硬依赖**（32 MB 删不得），其余大头也都有硬依赖 |
| 组装脚本内置冒烟测试 | 用分发包自己的解释器出 png+pdf+svg；裁错依赖当场失败，不会等对方双击才发现 |
| `build/` 与 `dist/` 不入库 | 已在 `.gitignore`；分发包可一条命令重建，没有入库价值 |

不在本轮范围：把 13 个 `E:\WT` 数据出处链脚本一起分发（它们与新外壳无关，对方也用不上）。

---

## 10. 图2：β–γ 能力平面（`图2` 分支，从 `restart` 出）

用户要求：「从 restart 开另一个分支做，分支名图2」「第二张图是 β–γ 图，先建立认知」。
**认知与口径全文在 `docs/BETA-GAMMA.md`**，这里只记工程侧的三件事。

### 10.1 一张图两层

| 层 | 内容 | 数据来源 | 开关 |
| --- | --- | --- | --- |
| 参考层 | 11 弹散点（点径与图1 一致，**不按 ΔV 缩放**；基准弹**涂绿**）+ 等 `n*` 双曲线 | `bg.rows()`，**不跑求解器** | 总是画 |
| 仿真层 | 固定 ΔV，在 β×γ 网格上只改 `CxK`/`CxAoA` 扫出的命中时间等时线 + 色标 | `Engine(scaling_of=bg.scaling_for)` | `--bg-no-scan` 关 |

### 10.2 一个必须记住的静默失败（已修）

`_patch_profile()` 的 `walk()` **只遍历已经存在的键**，所以往 blk 里注入一个"它本来没有的
字段"（`CxAoA` 就是：11 型一个都没有）是**静默 no-op** —— 不报错、不生效。
症状极具欺骗性：γ 轴在图上**完全不动**，三个 γ 的 `t_hit` 逐位相同
（`45.185932964507536`）。修法是末尾加"补缺"分支，把 `updates` 里 blk 没有的键补在顶层。

**教训（写进检查清单）**：给内核注入新字段后，必须有一条**"结果真的变了"**的端到端断言，
不能只看"乘数算对了"。现在由
`tests/test_bg_scan.py::test_gamma_reaches_the_kernel_at_nominal_beta` 守住。

### 10.3 一条物理结论（图上看得出来）

直飞、不机动的工况下，**命中时间几乎只由 β 决定**：γ 从 45 拉到 100 只改 0.37 s，
β 从 2600 拉到 3700 改 4.3 s ⇒ **仿真等时线在图上近乎竖直**。
这不是画错，是 `a_loss = q·f/β + γ·F·(n·g0)²/q` 里"低过载时基础项主导"。
图上脚注如实写了读法，`tests/test_bg_scan.py` 把这条钉住了
（`test_beta_matters_more_than_gamma_for_hit_time_in_a_straight_flying_scene`）。
γ 要显出来得有高过载需求（离轴 / 机动目标），本轮不引入机动目标 —— 见 §11。

### 10.4 象限底色（红区绿区）已按用户要求删除

参考图的"双优区（绿底）/ 双差区（红底）"是对着 11 弹池**目测定的阈值**（β ≥ 3250 且 γ ≤ 70 /
β ≤ 3000 且 γ ≥ 85），换池子或换数据版本就失去意义，画在图上却会被当成有物理含义的分界。
用户 2026-09-29 拍板"红区绿区没必要"，已连同 `BG_GOOD_*` / `BG_BAD_*` 常量与 `_bg_quadrants()`
一起删掉；象限信息由等 `n*` 线 + 点本身的位置承担。
`tests/test_figures_bg.py::test_no_quadrant_shading_anymore` 直接断言产物 SVG 里不再出现
那两个填充色与"双优/双差"字样。

---

## 11. 下一步（图2 之后）

1. **机动目标工况**：**可行性已打通，模型层已入仓，外壳未接**（2026-09-30）。
   全文见 `docs/MANEUVER-TARGETS.md`，简要：
   * 内核三条通道（`maneuvers` / `turn_rate_rad_s` / `samples`）全部生效，其中只有
     `maneuvers` 在外壳里全通（`Scene` 字段 + `scenario_dict` 出口 + `cache_key` + 校验）；
     另两条"内核认、外壳不认"。
   * **目标过载不是单调难度轴**（10~15.5G 是脱靶带，≥16G 又能命中），
     所以不要做"最大可对付过载"这种标量指标。
   * **内核没有"导弹开机/pitbull"事件**（永久锁定 + 无限截获），开机口径要外壳自己定；
     给"开机距离"时用一遍法（在不含该腿的轨迹上求时刻），**不要迭代**（自指条件会漂移）。
   * 用户第一个想定（直飞 → crank 70° → 正侧方 90° → 可选震荡）**已验证**：
     11 型弹 **5 型脱靶**；**γ 直接翻转命中/脱靶**（β 2580~2660 区间内 γ=40 全中、γ=91.2 全脱靶，
     两轴交换率约 80 个 β）；**按 β 排序与按命中时间排序不一致**（AAM-4 β 最高却最慢）。
     机理是"能量换位移"（不是控制权限不够）：同 β 下 γ 40→91.2，弹速只低 1.3%，
     但同一时刻距目标远 400~580 m。
   * **"没转完"是结局不是坏参数**（用户口径）：晚 crank 时该段根本转不完，
     于是 crank 角 60/70/80/90° 给出**完全相同**的结果 —— 这正是"没能完成 39 干扰 ⇒ 被击落"，
     要把「是否转完」与「开机时实际航向」当**输出量**报出来。
   * 已入仓 `src/missile_sim/flightpath.py`（航向指令 → `maneuvers`，解析编译，能导出 `samples`
     互校）+ `tests/test_flightpath.py` **27 项**；三个坑都锁进测试了。
     边界规则（`react_delay_s`，默认 1.0 s）已在 `图2` 收尾时落地，见下第 5 条。
   * **开机距离已定** = blk 的 `guidance.lockDistance`（120 系列/MICA/Derby/AMRAAM = 20 km，
     PL-12/R-77 系列 = 16 km；内核不读该字段，正好当我们的定义）；
     转向过载 6~14G、默认 9G；震荡默认值待用户经验数据。
2. **图3：机动想定轨迹图**（**独立成图 + 独立分支**）：**计划已落盘，未实施** ——
   见 `docs/PLAN-FIG3-TRAJECTORY.md`。用户 2026-09-30 取向：图3 **独立**（不再往图2 上加面板，
   于是图2 一个字节都不用动）；**在 `图2` 整体完成后从 `图2` 分出单独分支**（见 §0.1），
   定位是**纯展示性的叶节点（树梢）** —— 没有别的功能依赖它，所以排最后、优先级最低；
   叶子约束 = **不许改内核、不许改 `Scene`/`cache_key`/`CACHE_SCHEMA`**；
   不做 β/γ 解析临界点（等时线 + 斜率够了）；图一图二全不动；
   主方案**纯俯视 + 高度–时间副面板**（把"看不到的那一维"讲清楚）+ 开机→转39 放大 inset；
   **输入阶段（解算前）给目标航迹的 3D 预览**（目标航迹是纯运动学，不需要求解器，秒级）；
   **可交互 3D（鼠标拖动换视角）记为备用方案**（现有 WebUI 是纯标准库 + 离线分发包，
   不能引外部 JS/CDN）。
   三张图分工：图1 ΔV–BC / 图2 β–γ / **图3 一个机动想定的轨迹**；CLI 的 `--figure` 扩成
   可组合 `plane,bg,traj`（保留 `both` = `plane,bg` 兼容，新增 `all`）。待拍板项见该文件 §9。
3. **免安装分发包重建**：把 `--figure bg` 与 WebUI 的图2 一块带进 `dist/`，
   并同步 `packaging/README.app.md` / `使用说明.txt`。（已完成，2026-09-29）
4. **`docs/SOLVER-API.md`**：§2.1 的"β–γ 扫描的乘数注入契约"**已完成**（含
   `_patch_profile()` 只能改已存在键 ⇒ 第一版注入 `CxAoA` 是静默 no-op 这个坑）。
   还差的是 §4"内核能力边界"补三条（见下条）。
5. **`图2` 收尾 —— 已完成**（做完才从 `图2` 分出 `图3` 分支）：
   * ✅ **`src/missile_sim/flightpath.py` 的行为修正（不是文档）**：`crank_beam()` 原实现是旧规则
     `t_beam = max(t_beam, t_crank)` 且**没有延迟参数**。现按用户 2026-09-30 定稿实现：
     加参数 `react_delay_s`（默认 **1.0 s**）、`t_react = t_beam + react_delay_s`；
     `t_react > t_crank` 保留 crank + 39 两条腿（crank 可能被截断 = "没转完"）；
     `t_react <= t_crank` **丢弃 crank 腿**、只留 `39 @ t_react`（"没准备预规避直接开始39"，延迟照给）；
     `react_delay_s` 为负/NaN/Inf 构造期 `ValueError`。
     测试：旧用例 `test_beam_before_crank_means_go_straight_to_beam`（断言腿表 `[26.0, 26.0]`）已由
     6 条新用例取代，`-k flightpath` **22 → 27 项**；另在 `tests/test_solver_api.py` 加
     `test_kernel_rejects_non_increasing_maneuver_times` 与
     `test_crank_beam_scenario_end_to_end`（把锚点 **34.46 s**、命中 **69.554 s**、
     延迟 1 s ⇒ **69.172 s** 钉成回归值）。口径与实测见
     `docs/MANEUVER-TARGETS.md` §8.8.3 / §8.9（延迟每 1 s 吃掉约 78 m 脱靶余量）。
   * ✅ `docs/SOLVER-API.md` §4 补三条实测边界：**内核没有"导弹开机/pitbull"事件**
     （`seeker_assumptions` 是**四个键全 True**：`permanent_lock` / `unlimited_acquisition` /
     `unlimited_tracking_rate` / `unlimited_off_boresight`，`wt_missile.py:2750`；
     `observed_range_channel_valid` 是**静态**列 —— 看 blk 有没有测距通道，不随时间变）；
     **`guidance.lockDistance` 内核不读**（`wt_missile.py` 里 grep 零命中），
     由外壳消费作为"导引头开机"的定义；`maneuvers` 是**世界系分段常值加速度**、时刻是**绝对**时间、
     固定方向加速度**不是转弯**、时刻**非负且严格递增**且内核**硬拒**；
   * ✅ `docs/SOLVER-API.md` §1.2 的 `Scene.maneuvers` 行已写明外壳模型层
     （`flightpath.py`，形状 `((t_s, (ax, ay, az)), …)`）与 `docs/MANEUVER-TARGETS.md` 指向；
   * ✅ **更正一处被证伪的旧表述**：仓库四处写的"目标运动的腿乱序会被引擎**静默**按错序执行"
     **是错的** —— 内核硬拒（`ValueError: Maneuver times must be nonnegative and strictly increasing`，
     `wt_missile.py:247-248`，本轮实测：乱序/重复/同刻全部抛错）。已改 `AGENTS.md`、
     `flightpath.py`（docstring + 报错文案）、`docs/MANEUVER-TARGETS.md` §8.3；
     `NOTES.md` 的历史行**不动**（日志），由新增 §20 记录更正。真正静默的风险是
     把**相对偏移**当**绝对时刻**填。
   * ✅ 收敛：全量测试 + `git diff --stat` 对照 `git diff -w --stat`，一次收尾提交；
   * ⏭ 然后 `git switch -c 图3`。

---

## 12. 图3：机动想定轨迹图（2026-09-30 落地）

图3 = **一个机动想定的轨迹图**（纯展示性叶节点）：不扫参数、只画一个工况，只跑**被选中的基准弹**
（`--standard`，默认 PL-12）。目标直飞 → 看到 RWR 告警后 crank 至 70° → 导弹开机后转入正 39 位
（90°），可叠加俯仰震荡。计划与全部理由见 `docs/PLAN-FIG3-TRAJECTORY.md`；想定口径见
`docs/MANEUVER-TARGETS.md` §8（实测小结在 §8.10）。

**交付物**：

| 文件 | 内容 |
| --- | --- |
| `src/missile_sim/flightpath.py` | 新增 `TurnLeg.delta_rad()`、`Segment`、`PathSchedule.segments(*, duration_s=None)`、`_PHASE_STYLE` |
| `src/missile_sim/traj.py`（**新**，纯数据层） | `ANCHOR_MODE`、`TrajMark`、`TrajRun`、`find_anchor()`、`leg_at()`、`build_marks()`（只依赖 `flightpath` + `spec`，不 import 求解器/出图 —— 否则与 `workflow` 循环 import） |
| `src/missile_sim/workflow.py` | `TrajRequest`、`run_traj()`（**两遍法**：第一遍在**不含 39 腿**的轨迹上反求开机时刻，第二遍跑正式工况） |
| `src/missile_sim/figures.py` | `plot_traj()`（俯视等比例 + 分段色 + 节点 + 高度–时间副面板 + 「开机→转39」放大 inset + 题头/脚注）、`plot_traj_preview_3d()`（输入阶段 3D 预览，**不解算**）、`plot_traj_segments()` |
| `src/missile_sim/record.py` | `write_traj_track_csv()`（导弹/目标两套列）、`write_traj_segments_csv()`、`make_traj_manifest()` |
| `src/missile_sim/cli.py` | `--figure` 扩成 `plane|bg|traj|both|all`（`both` 仍是图1+图2），新增 `--traj-*` 一组参数 |
| `tests/` | `test_flightpath.py` 27 → **37 项**；`test_traj.py`（**新**，**30 项**，含真解算与出图 + 打印文本的 markdown 扫描）；`test_webui_traj.py`（**新**，**18 项**）；`test_traj_plot.py`（**新**，**23 项**：inset 像素宽高/注记重叠/字形/线型/图例↔artist/字节复现 —— 判据是**像素**，不是"命令退出 0"）|

产物：`figures/fig_traj_<tag>.{png,pdf,svg}` + `results/traj_<tag>.json` /
`traj_<tag>_missile.csv` / `traj_<tag>_target.csv` / `traj_<tag>_segments.csv`
（预览另出 `figures/fig_traj_preview_<tag>.*`）。

**实测数字**（PL-12，crank 8 s 起转 70°@9G，39 位 90°@9G，反应延迟默认 1.0 s）：

| 量 | 值 |
| --- | --- |
| 开机距离（blk `guidance.lockDistance`） | **16 km**（PL-12 / R-77 系列；120 系列 / MICA / Derby / AAM-4 / R-Darter = 20 km） |
| 开机时刻 `t_beam`（一遍法：首个 `range ≤ 16 km` 的行） | **34.458 s**（该行 range = 15989.97 m，行分辨率 ≈0.02 s，**不插值**） |
| crank 转完 | 9G 转 70° 用 **4.153 s** ⇒ **12.153 s** 到位（航向 110°） |
| 开机时航向 | 110.0°（`completed = True`：开机前已转完） |
| 39 指令时刻 `t_react = t_beam + react_delay_s` | **35.458 s** |
| 结局 · 延迟 0 | 命中 **69.554 s** |
| 结局 · 延迟 1.0（默认） | 命中 **69.172 s**，脱靶量 10.0 m（近炸判定为命中） |
| 第一遍（不含 39 腿）自己的结局 | 命中 60.760 s（**不是结论**，只用来反求开机时刻） |
| 一遍法成本 | fast 档走完两遍 ≈0.4~0.5 s |
| 3D 预览（`--traj-preview`） | **不解算**（`solver.run` **零调用**，只调用一次 `solver.profile` 读 blk 取 `guidance.lockDistance`）：自报 `elapsed_s` 不出图 **0.074~0.095 s** / 只出 png ≈0.75 s / 三格式 1.9~2.6 s，CLI 端到端 ≈3.5 s；且不含 39 腿（那正是要解算的量） |

`t_beam` 随 `t_crank` 变（crank 越晚、迎头时间越长、开机越早）：8 s → 34.46 s；26 s → 29.25 s；
28 s → 29.13 s。

**两个必须讲清的口径（别写反）**：

* `anchor.completed`（**开机时**转没转完）看 **`t_beam`** —— 用**不含 39 腿**的调度判定（一遍法第一遍）；
* `Segment.truncated`（39 指令有没有**截断** crank 转弯）看 **`t_react`**。
  两者是**两个不同的节点**（实测 t_crank 26 s：`completed = False` 而 `truncated = False`）。
* **延迟帮的是导弹**：延迟期间目标在 110° 上仍有 `cos110° = −0.342` 的接近分量，
  实测**每 1 s 吃掉约 78 m 脱靶余量**（远离边界时 t_hit 只早约 0.38 s/s）。
  **不要写成"延迟让目标更安全"。**
* **39 指令可能落在命中之后**（第三个口径，2026-09-30 补）：把开机距离人为调小
  （`--traj-lock-m 100` ⇒ `t_beam = 60.583 s`、`t_react = 61.583 s`）时，第一遍 **60.760 s 就命中**，
  第二遍的 39 腿**起于命中之后** —— 以前**静默出一张看起来正常的图**，会被误读成
  "目标做了 39 仍被击落"，实际是"目标还没收到告警就已经死了"。
  现在 `run_traj()` 的 `anchor["react_after_pass1_hit"]`（布尔）会报出来，脚注也另起一行明写。
  ⚠ **引用"10~15.5G 脱靶带"必须带想定**：那是固定 (β,γ)、30 s 起转 8 s 的结论；
  在 crank→39 想定上扫 `crank_g`/`beam_g` 8→18 G **全部命中、脱靶量 10.0 m**，没有脱靶带。

**新发现的坑**（都已在代码里修掉，细节见 `docs/PLAN-FIG3-TRAJECTORY.md` §8）：

1. **`TurnLeg` 的环绕航向 bug**：旧 `table()` 用 `abs((target − h)/ω)` 算时长，`ccw` 350°→10°
   被算成转 340°（36.3 s）并**脱靶**（实际停在 690° ≡ 330°），`truncated` 还误报。
   修法：`TurnLeg.delta_rad()` 走最短路径（现在 20°/ω = 2.136 s，`heading1_deg == 10.0`）。
2. **`PathSchedule._table` + `dataclasses.replace()`**：缓存字段没设 `init=False`，`replace()`
   会把**旧的航向表**悄悄带进新实例（改了 `legs` / `speed_ms` 仍用旧表，而一切"看起来正常"）。
   现在 `_table` 是 `init=False, repr=False, compare=False`。
3. **`completed` 与 `truncated` 是两个不同的节点**（见上一节口径）—— 图3 的 `build_marks()`
   只在**未截断**时才画 `crank_done`。
4. **`cli._from_json()` 的别名折叠方向写反（既有 bug）**：`_BG_ALIASES` / `_TRAJ_ALIASES` 的方向是
   「字段名 → 外部名」，折叠却按「外部名 → 字段名」解包 ⇒ `bg_alt_m` 折出来还是 `bg_alt_m`，
   `cls(**extra)` 直接 `TypeError`：**凡是带别名的键，`--input` 一律炸**（默认 JSON 恰好没有别名键，
   所以一直没暴露）。更隐蔽的是折出的 `alt_m` 还会被下一步当**场景字段**收走 ——
   **"改参考高度顺手改掉发射高度"而且不报错**。现在：外部名先折并**锁定**给请求（`claimed`），
   `bg_alt_m` 只改图2 参考工况、`scene.alt_m` 才是载机高度；两种拼写都收，同一字段给两种写法直接报错。

**未做项**：

* 可交互 3D（鼠标拖动换视角）仍是**备用方案**（`docs/PLAN-FIG3-TRAJECTORY.md` §7），主方案不依赖它；
* 服务端**多角度拼图**（同一套预渲染机制，低成本中间态）没做；
* **震荡的默认振幅/频率待用户提供**游戏经验值，在给之前**默认关闭**（不自造经验值）；
* **WebUI 表单字段收尾中**（CLI / JSON / `--traj-preview` / 文档已落地）；
* 三条内核通道仍只走 `maneuvers`（`turn_rate_rad_s` / `samples` 未接），
  `Scene` / `cache_key()` / `CACHE_SCHEMA` 一个字都没动（叶子约束）。


## 13. WebUI 拆分与三条并行线（2026-10-01）

### 13.1 分支拓扑（三个工作树，互不干扰）

| 分支 | 工作树 | 任务 |
| --- | --- | --- |
| `webui` | `E:\导弹包线图` | **主线**：WebUI 改造（拆静态资源 → 输入体验 → 结果展示） |
| `3d-viz` | `E:\导弹包线图-3d` | 图3 **真 3D** + WebUI 里**离线 WebGL** 交互的可行性（子代理/团队） |
| `opensource` | `E:\导弹包线图-oss` | 开源前准备（**排除 `vendor/` 与游戏数据**、README/LICENSE/CONTRIBUTING、秘密扫描） |

三者都从 `图3` 的 HEAD `73eb2bc` 出；**没有合并、没有推远端**（用户要求"先于 GitHub 连接进行开源"）。
每个分支各自满足"一个可交付阶段一次提交"。

### 13.2 WebUI：首页静态资源拆分（已落地）

`webui.py` 的 440 行 `PAGE` raw string → `src/missile_sim/webui_static/{index.html,app.css,app.js}`：
`index.html` 保留服务端占位符 + 内联 boot 数据；CSS/JS 纯静态，由新路由 `GET /static/<name>`
（白名单 `app.css` / `app.js`，fail-closed）直发字节。**判据是逐字节等价**：拆前产物 + 两处替换
（`<style>` 块 → `<link>`；`<script>` 主体 → boot 行 + `<script src>`）== 拆后产物 ✓。
响应体 36350 → 15507 字节，`webui.py` 2203 → 1780 行，全量 345 / 0 / 345。
架构、路由表、扩展点与"要一起改的判据"见 **`docs/WEBUI.md`**（新）。

顺手修掉一个真 bug：页面里**手写**的提示 `**不解算**` 会原样显示星号（`-k printed_text` 只看
Python 侧字符串，看不到页面）；已补页面侧判据（渲染出的 HTML 里 `**` 计数为 0）。

### 13.3 待办（用户给的优先级顺序）

1. **输入体验** —— ✅ **已落地（2026-10-01）**：失败响应按字段归位（`field_errors`）+ 前端红框/
   框下红字/滚到第一个出错的框；手改输入存 `localStorage`（`missile-sim:form`）刷新不丢，
   配「忘记上次输入」；真浏览器实测过（见 `NOTES.md` §25）。
2. **结果展示增强** —— ⏳ **未动**：结果面板的表格/图注/产物链接（图1/图2/图3 与 `paper`/`all`
   两种聚合）、多任务面板、等图状态。**2026-10-01 用户给了第二个参考站 `statshark.net` 之后，
   这一项有了具体清单**（实测与"抄/不抄"结论见 `docs/WEBUI.md` §7）：
   ① 两栏布局（左窄参数栏可折叠 + 右宽图占满）；② 预置工况改按钮网格（替 `<select>`）；
   ③ 图表设置面板（Y 轴量过滤 + 显示标签）；④ 图3 回放动画；⑤ 页脚 IA（许可/隐私/更新日志/反馈）；
   ⑥ 错误页改成卡片。**明确不做**：前端框架、Plotly、外部字体图标（体积与离线两条底线）。
3. 两条并行线的结论回填：图3 3D 的落地清单与工作量、开源前必须处理的合规项。

### 13.4 用户 2026-10-01 当场加的两条

* **亮色主题** —— ✅ 已落地（`webui` 分支）：`app.css` 变量整组换亮色 + `color-scheme:light`，
  判据 `test_webui_theme_is_light`（含"旧深色底不该还在"）。参考站 `jari-aerospace.top`
  实测是近白底 / 深灰字 / 1px 浅灰描边的工程工具风（`web_fetch` 被"非公网 IP"拦下，用浏览器看的）。
* **3D 拖动必须跟手** —— 已作为**硬需求**发给 3D 线（`fig3d-scout` / `3d-viz` 分支）：
  光标下的点跟着光标走（水平拖右 ⇒ 物体右转；垂直拖下 ⇒ 上缘向观察者倾倒），
  并在 spike 里给可复现自检（Δx=+200 px ⇒ 特征点在屏幕坐标也向 +x 移动）+ 写清"反向要改哪个符号"；
  3D 的 chrome 也要跟亮色。**结论见 3D 线的 `docs/FIG3D-FEASIBILITY.md` 与 `NOTES.md` §26.2**
  （已落地并复核：`d05ad72`）。

### 13.5 3D 落地拍板（2026-10-01 用户决定，两条线并行开工）

| 决策 | 用户拍板 | 落地任务 |
| --- | --- | --- |
| 图3 静态 3D | **替换**俯视图（不并存）；**保留**关键点位注释与阶段配色；**新增**"导弹过开机距离后换色"；**去掉**左下角 inset 放大图 | **task-11**（`fig3d-scout` / `3d-viz` / 工作树 `E:\导弹包线图-3d`） |
| 可拖拽 3D 的入口 | **WebUI 内嵌 + 另给「在新标签页打开」链接** | **task-12**（`webui-fig3` / 新分支 `3d-viewer` / 工作树 `E:\导弹包线图-viewer`，从 `webui` `d0113ed` 切出） |
| 轨迹抽稀 | **800 点**（320 略见折线，1200 数据更大） | **task-12** |

⚠ 两条线的**写范围必须不相交**（figures/workflow/traj_plot 判据 vs webui/webui_static/viewer 判据），
`NOTES.md` 与 `AGENTS.md` **只由 Lead 改**（两个进程同时字节追加会互相插队）。
⚠ 合并顺序：先 task-11（静态图）后 task-12（内嵌），两条都落完再统一改 `AGENTS.md` 与 `NOTES.md`。

### 13.6 新探究线：β–γ–ΔV 三维图 + 等时面（2026-10-01 用户追加）

用户原话："另外探究新的3维表格，把β、γ、ΔV放到单一3维图，并辅以等时面，同样允许使用teams。"
（按"图"理解：三轴 = β、γ、ΔV，叠加等时面。）

**Lead 先核实了四个事实**（否则任务会写歪）：

| 事实 | 证据 | 后果 |
| --- | --- | --- |
| β、γ 是**弹的固有属性**（kg/m²），不是自由参数 | `bg.BgPoint`：`beta = m_dry/(sd*cxk)`、`gamma = m_dry*sd*cxk*cx_aoa/(sl*sl*cyk*cyk)` | 图2 的平面是**可自由扫描的定义域**，11 型弹是里面的点 |
| **现有扫描把 ΔV 钉死** | `results/bg_default.json` → `scan.dv_pin_ms = 932.5697`（PL-12 的 ΔV）；`cx_scale`/`cxaoa_scale` 是命中 (β,γ) 的手段；1032 工况 = 43×24，命中率 100% | **ΔV 不是轴** ⇒ 要做三轴图必须**解开 ΔV** 并做**三维扫描** |
| `bg_default_cases.csv` 有 `dv_measured_ms` | 列清单已核（16 列） | 它是**结果**，不能冒充自变量（验证任务专门盯这一条） |
| marching cubes 的依赖现状 | 本机 numpy/matplotlib/**scipy**/PIL 有，**skimage 缺**（`marching_cubes` 在 skimage 里），`pyproject.toml` **未声明 scipy** | "自己写 marching tetrahedra" vs "新增 scipy 依赖"是**必须写进报告**的取舍 |

**两种"等时面"口径必须分清**（任务里要求给出语义差别，防混淆）：
(a) **真等值面** —— 三维扫描后提取 `t_hit = const` 的面，表示 `t_hit(β,γ,ΔV)` 的等值面；
(b) **"等时线立起来"** —— 把现有二维等时线沿 ΔV 拉伸成柱面，**并不表示** t_hit 对 ΔV 的依赖。

| 任务 | 谁 / 在哪儿 | 内容 |
| --- | --- | --- |
| **task-13** | `figures-fig3` / 新分支 `bg3d` / 工作树 `E:\导弹包线图-bg3d`（基线 `d05ad72`，带 3D 工具链） | 数据层（ΔV 成轴）+ 三维扫描成本实测 + 等值面提取 + mplot3d 多面可复现 + 可读性截图 + `docs/FIG-BG3D-FEASIBILITY.md` |
| **task-14** | `fig3-verifier`（阻塞于 task-13） | 对抗性验证：ΔV 真是自变量（固定 (β,γ) 只动 ΔV 看 t_hit 变不变）、等值面提取用**合成解析场**独立验、成本数字重跑核对、字节可复现（同进程 + 跨进程）、grep 取证"没偷偷 import scipy" |

⚠ 该分支从 `3d-viz` 的 `d05ad72` 切出，**不含** task-11 正在做的图3 3D 改造；两边都改 `figures.py` 时
由 Lead 人工合并（任务里已要求尽量新增模块、保持最小 diff）。

### 13.8 图4（β–γ–ΔV + 等时面）：结论与待拍板（task-13 交付在 `bg3d` @ `705b529`）

**结论：技术上做得出，但这个想定下不值得做成正式图。** 三个实测支柱（Lead 已复核产物与截图）：

1. **第三根轴的独立信息量 ≈ 一个斜率（一阶），但存在可测曲率**：`t_hit ≈ a(β,γ) − 0.0336·ΔV`，
   逐列 `R²` 中位 **0.9893**、斜率相对散布 **3.0%** ⇒ 6 张等值面是**一族近似平行的板**
   （正证据 `spikes/bg3d/out/iso/v8_cube_six.png`）。⚠ 口径（2026-10-01 由 task-14 对抗验证指出后修正）：
   **"只有一个斜率"偏强** —— 补二次项后残差 RMS 从 **0.5519 s 降到 0.0582 s**，曲率在 ΔV 区间端点
   相对中点的抬升中位 **1.5449 s = 该列 ΔV 效应的 9.16%**，**459/459 列同号**（系统性弯曲，非噪声）。
   所以准确说法是"**一阶近乎线性 + 可测曲率**"，但结论"先不做图4"不变。
2. **按真实跨度画会糊成一块**：三轴真实跨度 `β 2500~3750 / γ 44~96 / ΔV 600~1100`，比例约 1 : 0.012 : 0.12；
   `box_aspect` 一按真实比例，盒子就是一张薄饼、第 6 张面只剩 **18%** 可见（负证据
   `spikes/bg3d/out/iso/v3_six.png`：6 张面在图上是一整块褐色板，ΔV 刻度全叠在一条缝里）。
   要看得清**必须等长三轴 + 半透明**，而那是"把三个量纲不同的量强行等长"，几何直觉会被牺牲。
3. **两种"等时面"语义差别能量化**（这条比图本身有用）：真等值面上 `t_hit` 散布 **0.004 s（0.02%）**，
   而"把二维等时线沿 ΔV 立起来"的柱面上散布 **17.6 s（79%）** —— 后者**不是** `t_hit` 的等值面；
   两者在图上长得很像（`v4_two_flavors.png`），**若做，图注必须写口径**。

**代价**（本机 fast / `compiled-c` / 8 并发）：细网格 5049 工况、命中率 100%。**墙钟有两套测量，
两个数都有效但不可混比**：初版 **120.9 s / 24.0 ms**（当时与别的算例**并发**跑求解器）、
清缓存逐档冷跑复测 **81.85 s / 16.2 ms**（quick 4.31 s、coarse 16.58 s）；
**跨负载比墙钟没有意义**，要比就比"**耗时倍数 ≈ 工况数倍数**"——它在两次测量里都成立
（对照图2 的 1032 工况 ≈ 20 s）。`Bg3Scan` 现在记录 `n_run`/`n_cached`（quick 126/0、coarse 840/84、
fine 4699/350，三档 `n_run + n_cached == n_cases` 自洽；coarse/fine 有缓存是因为扫描按
quick→coarse→fine **继承缓存**，CLI 上可见）。提 6 张真等值面 **101 ms**（向量化后；第一版逐点
Python 1120 ms —— 这条"提速后 PNG 逐字节未变"**未被独立复现**，旧实现不在 git 历史里）。
**零新依赖**：自写 marching tetrahedra，`-k bg3d_spike` 里有一条测试**扫源码禁止** `import scipy/skimage/...`。
提交克制：两次提交都只碰自己的文件，**`results/` 与 `figures.py` 一个字节没动**；入库只留 5 张截图
（色条加完后 v8/v9 变大），13 MB SVG/PDF 与 2.1 MB 全量几何留在工作树未跟踪、脚本 1 分钟可重出。
⚠ 色条说明（诚实细节）：v8/v9 各配一根**离散层级色条**（`ListedColormap`+`BoundaryNorm` 取 `COLORS`
原色，不是插值色），但**面本身是 `α=0.45` 的混合色**，所以"与色条同色"只在混合前成立 —— 色条在这里
的作用是标**层级次序**，不是像素级配色。

**待用户拍板（四条）**：

| # | 问题 | Lead 的建议 |
| --- | --- | --- |
| 1 | 要不要做**图4** | **先不做**：它回答不了新问题 —— ΔV 那一维用"图2 的一张面 + 一个斜率标注"就够 |
| 2 | ΔV 轴范围/步长（600~1100 还是收窄） | 若做：收窄到 **820~1100**（弹池实际区间，避免等值面被立方体边界切掉） |
| 3 | 要几张等时面 + 画法 | 若做：**4 张面 + ΔV 剖切面**（`v9_cube_cutaway.png` 比 6 张清爽），等长三轴、`α=0.45`、`elev=24, azim=−62` |
| 4 | 静态还是可交互 | 若做：**静态**（已字节可复现）；交互要单开一条前端腿，且与 §8 的 3D 查看器收益重叠 |

⚠ **未证**（照抄 spike 的诚实清单）：换机动想定后斜率会不会变（只测了 50 km 迎头 / 目标 300 m/s 直飞 /
PL-12 / fast 档 / 本机）；ΔV 轴边界该不该放宽；三轴等步长、未做自适应加密。细节见
`docs/FIG-BG3D-FEASIBILITY.md`（在该分支上）。

**对抗验证（task-14，`fig3-verifier`，报告 `.tmp_test/verify/BG3D-VERIFY.md`）**：**没能驳倒** ——
11 条声明逐条独立复算全部成立，而且它的独立重算与 task-13 落盘数据**逐位相同**（斜率 −0.0335526814、
散布 3.04598%、`R²` 中位 0.9893197、RMS 0.5518670；自跑 36 工况真解算，9 列严格单调）；跨进程
（`PYTHONHASHSEED` 0/12345）20 个文件 19 个 sha 全同、同进程 9/9；用 **6×2×4 椭球**复现并验证了那个
梯度 bug（老写法 50.00%/−465143.7 → 修好后 100%/+786670.9）；`scipy|skimage|vtk|plotly` 全零命中。
**但挖出 7 条要改的**，其中一条是结论口径：**"ΔV 只有一个斜率"偏强** —— 二次项把残差 RMS 从
**0.5519 s 降到 0.0582 s**，曲率场中位 **1.5449 s ≈ 该列 ΔV 效应的 9.2%**（459/459 平滑为正）；
其余 6 条是数字错（"21820 个三角形"→ 实际 **22820**；柱面旧值 16.36~17.99 → **16.7822/17.5925**；
"22 项约 9 s" → **23 项 / 2.0 s**）、`scan_quick.json` 的 0.0247 s 是**热缓存**（冷跑 4.32 s）、
`bg3d_iso.py --cross` 是**死参数**、5 张图**无 colorbar**、`iso_report.json` 的 `same_process` 为 `null`。
⇒ **"先不做图4"的结论未被推翻**，已把这 7 条打回 `figures-fig3`，它在 **`b8a874e`** 上逐条改完
（+342/−82，15 文件；判据 23 → **26 项**，`-k bg3d_spike` 1.6 s 全绿）；改的过程中它自己又抓到
一个错（`rms_resid_lin_s` 第一版写成 `mean|resid|` = 0.474，被"必须与 `dv_linearity` 一致到 1e-12"
的断言照出来）与三处边界内瑕疵（已入库的 `crossSame.json` 一度是**加色条前的过期证据**、两处
markdown 星号会打到屏幕、`--grid both` 的缓存继承没写进 help）。新增部分由 **task-16** 补验
（`dv_quadratic` 用**独立解析场**打、RMS 身份、色条与面颜色取像素比对、`crossSame` 三份记录与盘上
17 个格式文件逐键一致）。

**补验（task-16）结论**：4 件成立（`dv_quadratic` 被独立解析场验到 1e-12；`rms_resid_lin_s` 身份正确
且写错必挂；色条与面颜色做了**像素级 + SVG 逐多边形反卷积**双层取证 —— v8 六格色值逐位等于
`COLORS[0..5]`、面侧残差 ≤1.5/255；`crossSame` 真被重生成，它自己跨进程 ×2 复核 17/17 一致），
挖出 **1 条真缺陷 + 3 条口径**，已在 **`cda568e`** 修完（判据 26 → **30**，全量 **385/385**）：

* 真缺陷：`bg3d.scan_from_record()` 漏带 `n_run`/`n_cached` ⇒ 入库 `iso_report.json` 里
  `scan.n_run = n_cached = 0` 与同块 `stats{runs:4699, cache:350}`、`n_cases=5049` 矛盾；
  修法是从 `rec["summary"]` 读回并把 **dataclass 默认值从 `0` 改成 `None`**（"没记"不许伪装成
  "真跑了 0 个"），加往返判据（三档 `n_run + n_cached == n_cases`）+ 故意 `pop` 字段必须为 `None`
  且 `None + None` 抛异常 + 入库 `scan` 块自洽 + `in_repo` 与 `git ls-files` 双向对齐（5/17）。
  修后实测 `4699 + 350 = 5049` ✓。
* 口径：提面耗时**不锁死**（同机读到 101 / 111.5 / 143.2 ms，12 次实测 103.2~215.1、中位 121.8）
  ⇒ 文档只承诺"量级 0.10~0.22 s + 分布 + 别跨机器比"；"160 dpi" → **299.9994 ≈ 300 dpi**（3 处；
  根因：`setup_style()` 的 `rcParams["savefig.dpi"]=160` 被 `save_formats` 的 `SAVE_DPI=300` 覆盖）；
  `cross*.json` 每条 sha256 加 `in_repo: true/false` 并写明 **17 条里只有 5 条入库可复核**。
* **"判据有牙"要用变异实验证明**：作者把 `bg3d.py` 逐字节换回缺陷版（先断言替身确有该函数、
  默认值确为 0），两条往返判据当场 FAIL 并打出 `n_run: 0, n_cached: 0 vs n_cases: 126`；
  ⚠ 它第一次的替身用 `git show | Set-Content -NoNewline` 造，**文件被写坏**（函数整个消失），
  那时是 `AttributeError` 失败 —— **那种失败什么都没证明**。变异体必须用 `write_bytes` 逐字节替换
  且**先断言变异体具备预期特征**。

### 13.9 内核归属转移（2026-10-01，用户当场告知）：对开源线的影响

用户出示原对话并明确：**内核现在归他本人所有**（原话："内核没声明许可证我就没打包只开了一套 API" →
对方回"无所谓" → 用户："内核现在是我的了"）。**后果三条，全是连锁的**：

1. **"内核无许可、不能公开"整条失效** ⇒ 内核可随公开仓分发、由本仓 `LICENSE` 覆盖。此前
   `docs/OPENSOURCE-READINESS.md` 的"最高风险"分析（§3/§5）与 13 处「无许可的第三方内核」口径
   **全部作废**，必须改写（清单与做法见 **task-15**；做法是先加 §0「更新：内核归属转移」再改正文，
   历史分析不抹掉）。
2. **游戏数据仍排除**：`vendor/wt-missile/inputs/resources/2.59.0.28/*.blk`（**168 份**，从 War Thunder
   抽出的游戏数据）与内核归属无关，按用户早先 `oss_scope` 的"排除 vendor + 游戏数据"处理 ⇒
   `git rm -r --cached` + `.gitignore`，并让测试/CI 在数据缺失时**优雅降级**（受影响的组
   `pool_mapping 8/9`、`solver_api 4/13`、`figures_repro 0/7` 是现成清单）。
3. **`LICENSE` 的候选排序要重述**：以前"MIT 与无许可内核兼容性最好 / GPL 会逼出整体分发合规问题"
   是选 MIT 的主要论据之一 —— 现在这条论据**不成立**（内核是自有代码），三个候选（MIT / Apache-2.0 /
   GPL-3.0）回到"要不要防闭源 + 专利条款"的纯粹取舍。用户仍**未拍板**（"等我看过对比"）。

⚠ **Lead 自查漏项**（记一笔）：上一轮开源审计只查了"必需文件在不在 + 密钥/绝对路径"，**没查"该排除的
排没排"** —— 结果公开仓里实际躺着内核本体与 168 份游戏数据，而文档写着"不公开、自备"。这类
"**文档与仓库状态互相矛盾**"必须用"文档说的每一件排除项都到 `git ls-files` 里核一遍"来兜。

### 13.7 合并与发布顺序（**提案，未执行** —— 用户 2026-10-01 定"未经同意不合并、不推送"）

本仓库**没有远端**，下面全是本地分支操作；每一步只做一次线性合并，**合完立刻跑判据**再进下一步。

**已核实的提交（2026-10-01 晚）**：

| 分支 | 工作树 | HEAD | 内容 | Lead 外部验收 |
| --- | --- | --- | --- | --- |
| `webui` | `E:\导弹包线图` | `7e105ea` → **`8b2d15b`** | 首页拆静态资源、亮色主题、输入体验、StatShark 实测、§13.5/§13.6 决策；之后是 Lead 的合并方案与决策记录（§13.7 顺序、§13.8 图4 结论、§13.9 内核归属） | 已：`-k webui` **43/43** + `-k figures_repro` **7/7**，跑完工作树仍干净；`docs/RESTART-PLAN.md` 每次改动都过 `--stat`==`-w --stat` |
| `3d-viewer` | `E:\导弹包线图-viewer` | `1e2005b` | task-12：内嵌可拖拽 3D（`traj3d.py` + `webui_static/viewer3d.*`，见 `docs/WEBUI.md` §8） | 已：12/12、55/55、全量 **361/361**（253.7 s）、真指针事件 + 像素 + 白名单 + 入口形态 |
| `3d-viz` | `E:\导弹包线图-3d` | `eec4ccc`（基线 `d05ad72`） | task-11：图3 静态图主视图改 3D 斜视、删 inset、导弹过 `t_beam` 换色 | 已：`-k traj_plot` **18/18**、`-k traj` **67/67**、`-k figures_repro` 7/7、全量 **350/350**（252.6 s）；物化验器：**0 个小尺寸 axes**（无 inset）、`#8e44ad` 在、文字"开机前/开机后/发射/命中/参考方向"都在、三格式字节与自报**逐个相同** |
| `bg3d` | `E:\导弹包线图-bg3d` | `705b529` → `b8a874e` → **`cda568e`**（基线 `d05ad72`） | task-13：β–γ–ΔV 三维图 + 等时面 spike（结论见 §13.8）；`b8a874e` = task-14 的 8 条整改；`cda568e` = task-16 补验的 1 缺陷 + 3 口径 | 已：三次提交都只碰自己文件、`results/`+`figures.py` 零改动、`-w` 判据一致、scipy 零命中（有条测试扫源码禁止）；`-k bg3d_spike` **30/30**、全量 **385/385**（241.4 s）；对抗验证 task-14 与补验 task-16 均完成 |
| `opensource` | `E:\导弹包线图-oss` | `84a7dbb` → **`190f815`** | 开源化骨架 + 合规审计；`190f815` = task-15（内核归属转移后改口径 + 游戏数据取消跟踪 + 测试降级） | 已：184 文件 +536/−125274、`--stat`==`-w --stat`、`inputs/` 与 `.blk` 跟踪命中 **0**、`wt_missile.py` **1**；Lead 独立复现 **数据在位 339/0/339**（221.6 s）、**数据缺席 190 通过/149 跳过/0 失败 退出码 0**、`--strict` 149 失败退出码 1；`NOTES.md` 字节改写无损（CR/LF 1226/1537 不变，numstat `2 2`）；密钥 0 真实命中 |

⚠ `opensource` 是从 **`73eb2bc`** 切出的，**不含** WebUI 与 3D 两条线的提交 —— 发布前必须合并（见步骤 5）。

⚠ **步骤 1 的合并必改项（Lead 复核时抓到的静默不一致）**：交互查看器的两段导弹配色只认
`TRAJ_MISSILE_COLOR` —— `src/missile_sim/traj3d.py` 的 `palette()` 里写的是
`"missile_after": figures.TRAJ_MISSILE_COLOR`，**没有** task-11 新加的 `TRAJ_MISSILE2_COLOR`；
而 `tests/test_viewer3d.py` 第 158 行钉的也正是 `missile_after == figures.TRAJ_MISSILE_COLOR`。
两条线各自自洽（`3d-viewer` 上还没有第二个颜色），但**合并后**静态图是「深灰 → 紫」、查看器还是
「浅灰 → 深灰」，**那条测试照样绿** —— 属于"静默通过的不一致"。合并时按序做三件事：
改 `palette()["missile_after"]`（用 `TRAJ_MISSILE2_COLOR`，`before` 仍走 `mix_hex(..., LIGHT_BG, …)` 的
"未激活淡化"约定）→ 同步改 `source` 字符串 → 改第 158 行的断言并补一条"两色不相等"，
再跑 `-k viewer3d` + `-k webui`。

**建议顺序**（冲突点已预判）：

1. `webui` ← `3d-viewer`（task-12）。预判**无冲突**：它动的是 `webui.py` / `webui_static/**` / 新增文件，
   与 `webui` 的 §5–§7 文档段不重叠；`docs/WEBUI.md` 两边都改过，但 §8 是纯新增。
2. `webui` ← `3d-viz`（task-11）。⚠ **必须排在 `bg3d` 之前**：`figures.py` 的 `plot_traj` 与
   `tests/test_traj_plot.py` 是 task-11 与 task-13 的唯一重叠面（先定静态 3D 图口径，再看三维图要不要复用它）。
3. `webui` ← `bg3d`（task-13）。若它只新增 `bg3d.py` / `spikes/bg3d/**` / 新文档则**无冲突**；
   合完补跑 `-k bg` 与 `-k figures_repro`。
4. **Lead 统一改一次** `AGENTS.md`（测试计数）与 `NOTES.md`（追加三条线的验收结论与本轮教训）。
   这两件事**只能在所有写者停手之后**做 —— `NOTES.md` 是**字节追加**，两个进程同写会互相插队。
5. `opensource` ← `webui`（**最后一步**）：合并后重跑全量，**并重做一次绝对路径 / 密钥扫描**
   （新代码可能带进新的本机路径，本轮已登记过 `VENDOR.md:7,9` 与 3 个 `native_compare*.json`）。
   ⚠ **合并后"降级数字"当场过期，必须重测并同步四处**：`opensource` 现在写的是"数据在位 339/0/339、
   数据缺席 190 通过/149 跳过/0 失败"，而合并会带进 WebUI / 3D 查看器 / bg3d 的新判据（其中
   `-k viewer3d`、`-k bg3d_spike` 是纯函数、不需要游戏数据 ⇒ **它们不会跳过**），数字必然变。
   要改的地方：`README.md` 顶部提示与 §9、`CONTRIBUTING.md` 顶部与 §6/§7、`docs/OPENSOURCE-READINESS.md`
   §0/§10.2、`.github/workflows/ci.yml` 的契约片段（它把"内核在、数据缺"的实测文案**写死在注释里**）。
   另外两条同批办（都是 task-15 自己记的待办）：拼写/文案（降级横幅里"放回：vendor/README.md（把游戏
   数据放回…）"读起来像"把数据放回 README.md"，改成"见 vendor/README.md"）+ 建议补一条
   `tests/test_runner_degrade.py` 钉住降级行为本身（本轮没做：降级是**运行器级**的，数据缺席时
   **任何**失败都记 SKIP ⇒ 理论上会掩盖"与数据无关的真失败"，只有 `--strict` 能照出来）。
   ⚠ **并发纪律**（本轮真踩到）：降级探针的做法是**把 `inputs/` 改名让开**，所以在别人跑全量的窗口里
   做这件事，会让那次全量得到 190/149 而不是 339/0 —— 探针必须**串行**做、做完立刻还原，
   且 Lead 的全量取证期间不要有人动 `inputs/`。
6. 推远端**仍未获授权**，且当前没有远端；`LICENSE` 还是占位，等用户看过许可对比再定。

⚠ 步骤 4 之后**不要再让任何队友写文件**：计数与 NOTES 会当场过期。本轮已中过一次 ——
task-12 把 `-k webui` 从 **43** 加到 **55**、全量 349 → 361，而 `AGENTS.md` 里仍写着 "42 / 349"。

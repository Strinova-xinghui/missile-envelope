# `new` 分支交接：用 wt-missile 整体替换两档求解器

> 会话中断/压缩后**先读这一份**。决策、实测数值、卡点、下一步都在这里。
> 分支：`new`（从 `main` = `cf25120` 出）。用户 2026-09-26 定案的两档名：**`standard` / `fast`**。

## 1. 目标（用户原话的落地口径）

「就用这一套替换整个求解器，两个档位同步更名，从 main 新建分支 new，将新求解器 API 化并对接，
并将档位选择能力也外化给输入。」三项已确认的选择：命名 `standard`/`fast`、资源**整包入库**、
范围**全部替换**。

## 2. 提交序列（已完成）

| 提交 | 内容 |
| --- | --- |
| `4363795` | cherry-pick `1d54dbb`「模型接入结构化 API」——**main 上没有 API 化**，它停在 `pro-api`；`1d54dbb` 的直接父就是 `main`，所以从 main 出分支再 cherry-pick 是干净的（不引入 pro-api 后续那些已被否证的高抛实验） |
| `dc960b8` | `chore(vendor)`：入库 `vendor/wt-missile/`（`wt_missile.py` + `inputs/resources/2.59.0.28/` 168 份 blk + `VENDOR.md`） |
| `4366cd6` | `feat(model)`：新增 `src/missile_sim/model/wtgame.py`（`standard` / `fast` 两档引擎） |
| `23ec96f` | `refactor(model)`：注册表 / 常量 / 缓存 / 环境 / 导出切到两档（含 `constants.py` 行尾修正后的 amend） |

## 3. 已落地的改动

### 3.1 `vendor/wt-missile/`（只读副本，不得改）

* 来源 zip SHA-256 `4EEA9890…F780`；`wt_missile.py` SHA-256 `1BFA0FA2…1890`
  （与包内 README §9 记录的"计时源码 SHA-256"一致，确认同一份被测代码）。
* 求解器自报 `MODEL = "python-game-6dof-v1"`；2.59.0.28 原生 6DOF 的纯 Python 复刻，
  **不执行 ELF**（`summary.elf_executed == false`）。
* 现有信源包 `E:\WT\wt-missile-backend-runtime-1.0.1` 的 `.28` 资源只有 **11 份**与本包 manifest
  对得上，**不能复用** —— 这是整包入库的根本原因。

### 3.2 `src/missile_sim/model/wtgame.py`（新引擎）

* 契约外壳照 `native.ProEngine`；运行方式照 `simulate_native`：**monkeypatch
  `wt_missile.load_profile`** 施加已算好的乘数（`force`/`force1`/`impulse*.force` ×
  `thrust_scale`；`CxK` × `cx_scale`）。已确认 `load_profile` 是模块级全局名，
  `compiled_simulate`（L2215）与 `scene_simulate` 都走它，**C 档同样吃到乘数**。
* 两档只差算术路径：`StandardEngine`（纯 Python）/ `FastEngine`（`compiled_simulate`，
  缺编译器时求自身回退 `python-legacy`，原因进 `EngineStamp.resources.backend`）。
* 场景关键三参数：`dt_s = SOLVER_DT = 1/48 s`（客户端对象时钟）、`step_policy="fixed"`、
  `sample_period_s=None` —— 这三条同时是"能走 C 快路径"的条件。
* `stamp()` 的 `fidelity` 自报 recovered / not_recovered / derived（外环控制器、重复
  `endSpeed`、非恒定 `Cy` 表被明确拒绝，不静默降级）。
* `selftest()`：vendor 哈希 + 资源清单 + 型号可算性 + 输入映射自洽 + 最小工况真跑 + 能力声明对实测。

### 3.3 注册表与常量

* `registry.BUILTIN_SPECS`：`standard`（`…wtgame:StandardEngine`，calc_version 1）、
  `fast`（`…wtgame:FastEngine`，calc_version 1），能力 `dims="3d"`、`vectorized_batch=False`、
  `requirements={"native_pkg": False, "vendor": True, "numpy": True}`（fast 另加
  `"compiler": "optional"`）。
* **旧 `pro` / `flash` 保留注册但标记 `source="legacy"`**，`list_models()` 默认**不列**它们
  （`LEGACY_MODELS`），`models_table()` / `results/models.json` / `--backend` 都只看两档；
  `spec_of("pro")` 仍能查到，旧脚本与旧测试可回退。
* `constants.py`：新增 `CALC_VERSION_STANDARD/FAST = 1`、`SOLVER_DT`、`VENDOR_DIR`；
  `BACKEND_VERSIONS` 扩为四档（pro=5 / flash=1 原样保留）；`calc_version()` 默认与
  `CALC_VERSION`、`CACHE_SCHEMA` 指向 `standard`。
* `cache.py`：新档位落 `results/cache/<档位>.json`；旧 pro/flash 路径不变。
* `env.py`：按 `requirements.vendor` 填 `env.options["vendor_dir"]`；两档不再碰 `WT_NATIVE_PKG`。

### 3.4 三条分派路径（全部替换）

| 位置 | 改法 |
| --- | --- |
| `scanner.ScanSpec` | 默认 `model="standard"`；`from_config` 分三支：`pro`（旧，用 `cfg.pro_cache`）／`flash`（旧，用 flash 常量）／**其余（standard/fast/第三方）走 `pro_*` 运行参数 + 缓存只按档位名落 `results/cache/<档位>.json`，绝不受 `cfg.pro_cache` 影响** |
| `flight.TrajectoryRunner` | 新增 `_runner_for()`（注册表 + `EngineRunner`；`pro` 仍走 `ProRunner`）；新增 `engine_flight()`（`pro_flight` 成为它的包装）；`run()` 只对 `flash` 保留旧路径 |
| `sweep` | `run_sweep_pro` 泛化为 `run_sweep_engine(model=…)`（注册表 + `EngineRunner` + `run_grid`），`run_sweep_pro` 变包装；`run_sweep()` 只在 `backend=="flash"` 时走旧向量化路径；`res.pro` 诊断块改 `get()` 并新增 solver/engine 键 |
| `config.py` | `backend` 默认 `standard`；`BACKENDS=("standard","fast")`；`pro_dt` 默认改为 `field(default_factory=_default_solver_dt)`（**延迟 import**，否则 `config → model` 会经 `flash → sim → config` 循环）；`pro_cache` 默认 `""`；`PRO_BACKEND_HINT` 重写 |
| `configs/*.json` | `baseline.json` / `standard_120c5.json` / `workflow_example.json` 的 `backend.name` 改 `standard`，`pro_dt` 改 `0.02083333395421505` |
| `provenance.py` | `pro` 块改为**总是输出**（`pro_*` 是命名遗留，现在是两档共用的运行参数）；`backend` 默认 `standard` |
| `record.py` | 默认 backend 由 `pro` 改 `standard`（`to_record` / `make_manifest` / `check_staleness` 的多处默认值） |

### 3.5 关键 bug 修复（新档位必现）

**1）子进程还原不了嵌套参数块。** `runner._worker_run_engine` 原先用 `EngineInputs(**inp_dict)`
还原输入，但 `_dataclass_dict` 走的是 `dataclasses.asdict`（**递归**展平），嵌套参数块变成 dict
⇒ 子进程里 `inp.mass.dry` 抛 `AttributeError: 'dict' object has no attribute 'dry'`。
新增 `runner.restore_engine_inputs()` 逐块还原（含 `pid_rows` / `gain` 表 / `wind_m_s` /
`target_maneuvers` 的 tuple 还原），并把 `missile_sim.model.wtgame` 加进 `_pool_payload` 的
预载模块名。**这条路径（EngineRunner + jobs>1 + 嵌套 dataclass）在替换前从未被跑过。**

**2）要轨迹的请求会命中"没有轨迹"的缓存记录。** `save_trajectory` **不参与
`EngineInputs.cache_key()`**（改它会作废 1824 条既有键），所以带轨迹与不带轨迹的请求
**共用同一个键**。写侧一直只在无轨迹时落盘（轨迹占单条记录 95%），**读侧却照查**
⇒ "先扫描（已缓存、无轨迹）→ 再要轨迹画弹道剖面图"会拿到 `samples == []` 的旧记录，
**弹道图静默消失且不报错**。这条不对称在 `NativeRunner` / `FlashRunner` / `EngineRunner`
里各有一份（共 11 处），是改造前就有的潜伏 bug，新档位把 `cli --figure` 接到这条路上才暴露。
修法：新增 `cache.cacheable(obj)` 作为**唯一判据**，读写两侧共用。

### 3.6 `cli.py` 单工况走统一入口（提交 `…`）

| 位置 | 改法 |
| --- | --- |
| `cli.py::_run_single` | 原先写死 `sim.simulate_one`（**旧 Flash 公式引擎**）——`--backend` 对单工况**完全无效**，选了 pro 也照样出 Flash 的数。改为 `flight.TrajectoryRunner`（档位由 `cfg.backend` 分派） |
| 打印字段 | `n_eff_at_min_range` / `terminal_gamma_error*` / `t_loft_end` 只有旧 Flash 产出。新增 `_print_diag()`：没有就打印"该档位不提供"，**不打印 nan**（nan 会被读成"算出来是 nan"）；JSON 里落 `null` |
| 弹道图 | 新档位没有 `sim.Trace`，只有逐采样 `samples`。新增 `flight.SampleTrace` + `trace_from_samples(samples, stride=…)`（`gamma` 由 `(x,h)` 对 t 中心差分反算），`FlightResult.display_trace` 统一两条路 |
| `cli.py` 导入 | 补上 `ConfigError`（**原代码在 `except ConfigError` 用了它却没导入**，一旦走到那条分支就是 `NameError`）；清掉未用的 `s_ref` / `plot_loft_family` |
| `--mass` | **停用**。它只在旧 Flash 公式引擎里成立（覆盖干重）；新两档的干重取自权威 blkx，而它同时是 `ΔV_blk`/`BC_blk` 的锚，求解器没有这个入口。改造前 `--backend pro --mass …` 就是**悄悄吃掉** `--mass` 还照常出数。现在改为 `ConfigError` + `exit 2`，并在 `main()` 里统一捕获成 `错误：…` |
| `--backend` 帮助 | 改用 `PRO_BACKEND_HINT` 作 epilog，并写明 **`--standard`（标准弹池）与 `--backend standard`（档位）不是一回事** |

## 4. 已验证的实测数值（可直接作为验收基线）

| 项 | 数值 |
| --- | --- |
| 两档 `selftest` | 全绿；PL-12 输入映射 `ΔV_blk=932.57 / BC_blk=3078.1`，与仓库权威值一致 |
| **金标**（AIM-120D / 60 km / 双方 6000 m / 300 对 250 迎头 / `ideal` 观测） | `max_alt = **10629.9961 m**` @t=25.4792；原生金标 10630.40 ⇒ **−0.40 m（0.0038%）** |
| 两档一致性（同上工况） | `Δmax_alt = 0.000000 m`、`Δt_end = 0`、`Δv_impact = 8.2e-6` |
| PL-12 基准（50 km / 10 km / 300 对 −300，dv=932.6 bc=3078.1） | `t_hit = 45.1851 s`、`max_alt = 12725.1 m`；旧 Pro 基线 `45.1983 / 12978.9` ⇒ `t_hit` 差 **0.029%**（旧 Flash 对 Pro 是 0.65%，好 20 倍）；`max_alt` 差 254 m（2%，非 dt 造成 —— dt 从 1/48 到 1/96 只差 4 m） |
| 进程池路径 | `run_sweep(jobs=2)` 未缓存工况：`native=1 cache=0`，2.6 s 跑完 ⇒ 子进程还原正确 |
| 本机环境 | Python 3.14.7 / numpy 2.5.2 / **无 C 编译器** ⇒ fast 档实测走 `python-legacy`（`compiled_fallback_reason` 有原因） |

## 5. 测试收尾（**已完成**，提交 `0230cd8`）

`python tests\run_tests.py` → **通过 328 / 失败 0**（554 s）。原先剩的 21 个失败有两个根因，
都不是"测试写错了"，而是**产品代码里两处改名漏改**：

1. **`record.py` 的内置模型白名单硬编码 `("pro","flash")`** —— 18 个失败（几乎整个
   `test_model_record`）的同一个根因，报 `ValueError: 未知模型：'standard'`。
   修法：新增 `record.builtin_model_names()`，**惰性查注册表**（`BUILTIN_SPECS` 的全部键，
   含 legacy 名）并缓存；注册表本身导入失败时退回 `("standard","fast")`。
   不写死名单是刻意的 —— 档位还会再改名，写死的白名单会在改名当天再炸一次。
2. **`make_manifest` / `check_staleness` 的 `backend` 默认值还是 `"pro"`** ——
   3 个 staleness 假阳性的真正根因。manifest 按 `standard` 记 `calc_version=1`，
   比对时却按默认的 pro 算出 `calc_version=5` + 附 `elf_sha256`/`version`，
   `calculator_digest` 必然不等。修法：两处默认值改 `"standard"`，并在 docstring 里
   写明"跨档位比对必须显式传 `backend`"。

顺带在同一个提交里修掉的陈旧断言：`config.validate` 的报错文案（不再说"pro 尚未接入"）、
`test_model_record` 的 fixture（拆成 standard 的 `RT` 与旧 Pro 的 `RT_PRO`）、
`test_workflow` 的 `SMALL`（`flash` → `standard`）与 `--backend pro/flash` 断言
（现在是断言被 argparse 拒）。


## 6. 剩余待办（按计划顺序）

1. ~~修完上面 21 个测试。~~ **已完成**（§5，`0230cd8`）。
2. ~~`cli.py` 的 `_run_single`。~~ **已完成**（§3.6）。注意这条顺手挖出两个改造前就有的
   潜伏 bug：`cache.cacheable` 的读写不对称（§3.5-2）与 `except ConfigError` 少导入。
3. `scripts/pipeline.py`（`models --check` 与 `--backend` 帮助文本）、
   `scripts/workflow.py`（输入 JSON 的 `backend` 值域、出处面板文案）、
   `scripts/workflow_web.py`（表单选项）、`scripts/make_missile_bc_overlay.py`
   （`--backend` 的 choices 仍是 pro/flash）、`src/missile_sim/crossplot.py:278`
   （出处行按 `elf_sha256` 有无反推 backend，会把两档都认成 flash）。
4. 新增 `tests/test_wtgame.py`：vendor 完整性（哈希/清单计数）、输入映射逐字段、
   乘数施加（`force*`/`CxK` 被改写且 `dv_blk`/`bc_blk` 来自 `inp`）、**金标对拍**
   （`max_alt` 10629.9961 ± 10 m）、**两档一致性**（≤0.05 m）、能力声明对实测、拒绝路径。
5. `python scripts\pipeline.py models --check` 两档 OK；重新生成 `results/models.json`
   （`registry.write_models_table()`，应**只含 standard/fast**）。
6. 文档：`docs/MODEL-API.md`（内置两档 + vendor 依赖 + **`--standard`（标准弹池）与
   `--backend standard`（档位）不是一回事**）、`README.md`、`NOTES.md`、`AERO_PLAN.md`、`AGENTS.md`。
7. 全量验收：`python tests\run_tests.py` 全绿、`git diff --stat` == `git diff -w --stat`
   （唯一允许的例外是纯缩进改动，`-w` 会忽略它）。

## 7. 不可动摇的前提（改之前先读）

* **`results/pro_cache.json` 保持字节不变** —— 实测 **1844 条**（不是 1824；1824 是 32×57 的
  **网格点数**，两个数字一直被混用）、约 44 min 计算量、schema 5。
  ⚠ `results/flash_cache.json` **既不在仓库里也不在 `git ls-files` 里**（从来只是运行期产物），
  所以"flash 缓存不能动"这条约束是空的。
  新档位用自己的 `results/cache/standard.json` / `fast.json`（已 gitignore）。
  `scanner.from_config` 刻意让新档位**不受 `cfg.pro_cache` 影响**，否则会写进 Pro 的资产文件。
* **`EngineInputs.cache_key()` 逐字不变**（冻结回归在 **`tests/test_model_api.py:72`**
  `test_cache_key_matches_frozen_reference` —— 旧文档误记为 `test_model_io.py`，那里没有这条）；
  两档因此必须靠**缓存文件**隔离，而不是靠键。
  ⚠ 推论：`save_trajectory` 也不在键里 ⇒ 读写缓存必须共用 `cache.cacheable()`（§3.5-2）。
* **行尾纪律**：`.gitattributes` 是 `* -text`，而本仓库行尾**混杂**：
  * `NOTES.md` = 1~2 个 CR 混合、`AERO_PLAN.md` = 1~2 个 CR 混合 → **必须字节级编辑**
    （`open(rb)` → `split(b"\n")` → 拼 `CR` 尾 → `b"\n".join()` → `write(wb)`）；
  * CRLF：`README.md`、`io/native/record/runner/grid/flight/scanner/sweep/pro`、
    `configs/workflow_example.json`、`scripts/pipeline.py`、`tests/test_pro.py`；
  * LF：`AGENTS.md`、`docs/*`、`src/` 的其余文件（含 `sim/aero/ballistics/burn/decide/atmosphere`）、
    **`scripts/workflow.py`（AGENTS.md 说它是 CRLF，实测是纯 LF，以实测为准）**、
    `scripts/workflow_web.py`、`scripts/make_missile_bc_overlay.py`、`tests/` 的其余文件、
    `configs/baseline.json`、`configs/standard_120c5.json`。
  改完**必须**核对 `git diff --stat` 是否等于 `git diff -w --stat`；不等就是行尾被重写了
  （唯一合法例外是**纯缩进**改动，`-w` 会忽略）。
* 用户要求"两个档位同步更名" ⇒ `BACKENDS`、`results/models.json`、`--backend` 都只暴露
  `standard`/`fast`；旧名只作 legacy 回退入口（`scripts/pipeline.py` 的 `--model` 仍收旧名，
  因为它的职责是"按注册名跑任意模型"）。

## 8. 复现命令

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python -c "from missile_sim.model import registry as r; [print(s.name, s.calc_version, s.entry) for s in r.list_models()]"
python scripts\pipeline.py models --check          # 两档 selftest
python tests\run_tests.py                          # 全量自检
```

金标场景的构造（`tests/test_wtgame.py` 里要固化）：`EngineInputs` 用
`io.inputs_from_case(io.build_case(cfg, missile="us_aim_120d"))` 再 `replace(range_m=60000,
alt_m=6000, target_alt_m=6000, vm0=300, vt=-250, duration_s=60, observation_mode="ideal")`。

## 9. 下一步的岔路口：外壳要不要重建

`docs/SHELL-REBUILD-FEASIBILITY.md` 是**独立评估**（不是本交接的一部分）：以 wt-missile
为核心、抛开现有外壳从头重建的可行性。要点：

* **可行**，属"中等规模重写 + 大扫除"：新写 ~1200–1800 行、重写 ~900–1300、删 ~2900、
  原样保留 ~1500；`src/missile_sim`（9506 行）里 **≈30% 是两代旧引擎留下的死代码**。
* 求解器侧无包袱：单文件 2989 行，输入 1 个 scenario dict，输出 `(scenario, summary, rows 65 列)`，
  **不含缓存 / 批量 / 网格 / ΔV-BC / 绘图** —— 外壳该干的它一件没抢。
* **判据**：旧 Pro/Flash 口径还要不要。若要（继续和参考图对拍），继续改造；若不要，
  重建的收益才开始大于代价。报告 §5 还给了个折中：先"止血式清理"（把旧引擎挪进 `legacy/`）观察一周。
* 报告给出的 6 条待拍板问题在它的 §6，其中第 1 条直接决定走哪条路。

**该报告基于 HEAD `a95e5ce` 的快照**，其中关于 `pro_cache.json`（1844 条）、
`cache_key` 冻结测试位置、行尾清单三处**与我原先的记录不符且它是对的** —— §7 已按它订正。

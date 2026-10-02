# 抛开现有外壳、以 `wt-missile` 为核心重建外壳 —— 可行性评估

> **快照**：HEAD `a95e5ce`（分支 `new`），工作树时刻 2026-09-27 13:27。当时 `git diff --stat` 有 **7 个未提交文件**
> （`cli.py` / `flight.py` / `model/runner.py` / `model/cache.py` / `model/flash.py` / `tests/test_model_cache.py` /
> `docs/NEW-SOLVER-HANDOFF.md`）—— 外壳正在被其他人改，本报告行号以该快照为准。
> **环境**：Python 3.14.7 / numpy 2.5.2。
> ⚠ **订正（2026-09-27 晚，后续提交）**：成稿时记的是"无 C 编译器"。实际本机装了
> **VS 2022 Community（MSVC 19.44）**，只是 `cl.exe` 不在 PATH 上；在 VS 开发者环境里编译一次
> 内核之后 `fast` 档已真跑 **`compiled-c`**，实测 **17.5~23×**（金标 60 s 工况 1765 → 77 ms）。
> ⇒ §1.5 的性能结论与 §4.2 的 **R6** 都要按"本机已有 C 内核"重读 —— **§1.5 里那份
> "fast 恒回退"的实测因此不再成立**，但那 11.3 min 的网格外推仍是 standard 档的数字。
> 详见 `docs/NEW-SOLVER-HANDOFF.md` §4.1。

---

## 0. 结论（先行）

**可行。这不是"重造"，而是一次"中等规模的重写 + 一次大扫除"。** 三条依据：

1. **求解器边界极干净**：`vendor/wt-missile/wt_missile.py` 2989 行单文件，输入 = 一个 JSON scenario dict，
   输出 = `(scenario, summary, rows)`；**没有缓存、没有批量、没有网格、没有 ΔV/BC 概念、没有绘图**
   （§1.4 有 grep 证据）。外壳该做的事它一件都没抢。
2. **真正不可替代的领域资产只有 5 块、约 1700 行**：`io.py` 的 (ΔV,BC)→引擎参数映射、`standard.py` 的 11 弹池、
   `sweep.py` 的网格/等时线、`plot.py`+`crossplot.py` 的版式、`record.py`+`scanner.py`+`provenance.py` 的产物自描述与时效。
3. **历史包袱也量化得出来**：约 **2900 行**的 Flash/Pro 两代引擎（`sim.py` 935 + `aero.py` 246 +
   `ballistics.py` 186 + `burn.py` 125 + `decide.py` 物理部分 ~150 + `model/flash.py` 526 +
   `model/native.py` 引擎部分 ~380 + `pro.py` 68 + `atmosphere.py` 76）在新外壳里**一行都不需要**，
   占 `src/missile_sim`（顶层 5235 + `model/` 4271 = **9506 行**）的 **≈30%**。

**量级**：新写 ~1200–1800 行、重写 ~900–1300 行、删除 ~2900 行、原样保留 ~1500 行。
**什么时候不值得**：若目标是"继续出图、继续对拍旧 Pro 结果、不重跑那 1844 条缓存"，
重建的收益（架构干净）远小于代价（历史可比性断链）。**§5 有判据。**

---

## 1. 核心求解器：能干什么、不能干什么

### 1.1 输入契约（`wt_missile.py`）

| 项 | 契约 | 证据 |
| --- | --- | --- |
| 唯一入口 | `python_simulate(raw)` / `Calculator.calculate(inputs)` | L2502、L2903–2929 |
| 场景格式 | `schema_version=1` + 白名单键（14 个），多一个键就 `ValueError` | L154–161 |
| 版本 | 只认 `2.59.0.28` / `2.59.0.22`；`fastmode` 只在 `.28` 被验证 | L164–169 |
| 简单格式 | 11 个数值字段**全部必填**（缩写/拼错即报错，无默认值） | `FIELDS` L2801–2813、`to_scenario` L2825–2882 |
| 时间 | `duration_s ∈ [0.001, 600]`（默认 60）；`dt_s ∈ [0.00025, 0.02083333395421505]` | L172–174、`CLIENT_OBJECT_DT_S` L124 |
| 步进策略 / 输出采样 | `step_policy ∈ {version_default, fixed}`（`dt_s == 客户端时钟` 即固定网格）；`sample_period_s = None` ⇒ **逐物理步输出**，给显式周期会让 C 档回退 | L170–171、L2535–2536、L174–178、L2210–2211 |
| 观测 | `observation.mode ∈ {locked, ideal}`；`ideal` 下给延迟/偏置**直接报错**（不静默忽略） | L185–198（实测复现） |
| 初态 | `launch{position_m, velocity_m_s, quaternion_xyzw, angular_rate_rad_s, age_s ∈[0,600), ejection_velocity_body_m_s, feedback_acceleration_m_s2, motor_start_times_s(1..4)}` | L209–229 |
| 目标 | `target{position_m, velocity_m_s, collision_radius_m∈[0,100], turn_rate_rad_s \| maneuvers \| samples}`（三者互斥） | L230–283 |
| 目标轨迹回放 | `samples` 必须从 t=0 严格递增并**覆盖全部 duration_s**，不许外推；默认 hermite，可 `recorded_linear` | L251–283 |
| 资源清单 / 可选顶层键 | `presets.json` 在 import 时校验 SHA-256，每次 `load_profile` 再校验 blk 逐文件 SHA-256，不符即 `Resource identity mismatch`；可选 `wind_m_s` / `ground_height_m` / `proximity_fuse` | L474–476、L532–547、L199–204 |

**型号覆盖（实测）**：`PROFILES = 168` 个预设，其中 **156 可算、12 被拒**。
拒绝原因分布：`Duplicate endSpeed values` ×5、`orientationAutopilot 未移植` ×3、
`propulsionAutopilot` ×2、`useThrustVectoring` ×2（`unsupported()` L2311–2325、`list_missiles()` L2936–2944）。
拒绝是**硬拒绝**，不会退化成另一种弹（L2320 原文：`refusing an approximate replacement`）。

### 1.2 输出契约

* `python_simulate` 返回 `(normalized_scenario, summary, rows)`（L2502–2514）；`Calculator.calculate` 再包一层
  `{schema_version, engine, input_format, scenario, summary, trajectory, event}`（L2927–2929）。
* **`summary` 实测 32 个键**，组装点 L2741–2776（公共）+ L2777–2792（Python 内核专有）。关键键：
  `time_s` / `steps` / `terminal_event` / `minimum_separation_until_event_m` / `closest_time_s` /
  `distance_flown_m` / `final_speed_m_s` / `peak_{speed,requested_g_before_native_limit,specific_force_g,trajectory_normal_g}` /
  `kill_assessed` / `dt_s` / `initial_age_s` / `output_mode` / `sample_period_s` / `event_interpolation` /
  `seeker_assumptions` / `observation` / `timing` / `fastmode` / `limitations` / `identity` / `model` /
  `elf_executed` / `formula_basis_elf_sha256` / `fuse_radius_m` / `fuse_arm_time_s` / `motor_start_times_s`。
* **`rows` 逐采样 68 列**（`_CF_COLUMNS` L2009–2018；`len == 65` 是 2026-10-02 扩列**前**的实测值，现在是 **68**，末尾三列为 `mach`/`aoa_deg`/`aoa_eff_deg`）：轨迹、姿态四元数、角速度、目标运动、
  质量/推力/TVC，**以及制导内量** —— `requested_g`、`control_horizontal/vertical`、`guidance_vx/vy/vz`、
  `linear_time_to_go_s`、`guidance_velocity_source`、`specific_force_g`、`trajectory_normal_g`，
  以及观测通道 `observed_los_*` / `observed_omega_*` / `observed_range_m` / `source_observation_age_s` / `state_interpolated`。
  **没有** `t_loft_end`、**没有** `n_eff`、没有 `k_go`。
* **终端事件 5 种**：`time_limit` / `lifetime` / `ground` / `contact` / `proximity_fuse`
  （判定 `first_event` L401–414；装配 L2738、L2280）。
* `kill_assessed` **恒为 False**（L2761、L2890）—— 接触/近炸不等于击毁；末行可能是步内插值
  （`state_interpolated=true`，L2631），终止后**不补行**（L2735–2737）。
* `save_result()` 落 5 个文件（`scenario/summary/trajectory.csv/trajectory.json/event.json`，UTF-8）L2885–2892、L2947–2953。

### 1.3 内部已经做掉的（逐条确认，全部在 `wt_missile.py`）

| 能力 | 位置 | 备注 |
| --- | --- | --- |
| 大气密度 + 温度 + 声速 / 马赫阻力 f(M) / 气压推力修正 | `_atmosphere` L67–86、`_mach_function` L89–98、`pressure` L564–570 + `extPressureToThrustMult` L661–665 | 大气常数与本仓库 `atmosphere.py` 同源（1.225 / 18300 / 同一组多项式系数） |
| 有限级发动机 / 分级质量流失 / TVC | `class Engine` L573–717 | 支持 `propulsion0..3` 与 `force/force1` 两族；1..4 台发动机、每台 1..4 级（L630–631） |
| 三维气动力 + 力矩 + 阻尼 + 惯量 | `Body.__init__` L753–782、`Body.forces` L784–839 | 阻力/升力/**诱导阻力 CxAoA**/迎角限制/舵面饱和/力臂 |
| 四元数刚体积分 | `advance_attitude` L736 + `Body.step` L841–873 | 保留 float32 舍入点（L860–873 注释） |
| 比例导引 + 增益表 + 纯追踪/角度导引 | `Controller.request` L1005–1053 | `G = Gtime(age) × Ghit(Tgo)`（L1011） |
| 双轴 PID（两种形态：`pid0…N` 时间表 / 扁平 `accelControl*`） | `Controller.__init__` L921–931、`pid` L936–1003 | 含 `baseIndSpeed` 尺度换算（L958–964） |
| 速度系控制帧 `velFrameReference` | `control_frame` L887–908 | 保留游戏的最短弧合成顺序（L906–908） |
| **自动高抛** | `_loft_elevation` L101–110 + L1033–1052 | `rangeToLoftElevation` 按**距离平方**插值；退出判据用 `loftTargetElevation` + `loftTargetOmegaMax` |
| 导引头（雷达/光学两族，角度/距离/多普勒滤波 + 多径）；`locked` 模式才启用 | `class Seeker` L1103–1244 | 观测链路（采样周期 / 延迟 / 常速外推）`ObservationTransport` L425–461 |
| 目标机动（恒定转弯率 / 分段加速度 / 录制回放） | `class Target` L287–369 | hermite 或 `recorded_linear` |
| 引信（半径 + 解除保险时间）与球形接触、撞地 | `first_event` L401–414 | |
| 结束速度封顶 / 重力 / 风 | L2484–2490 / L835 / L789 | 重力硬编码 `-9.81`（**不可配置**）；风仅平移风速 |

### 1.4 明确不做 / 做不到的

| 限制 | 证据 |
| --- | --- |
| **外环控制器**（`orientationAutopilot` / `orientationAutopilotLeadingMult` / `propulsionAutopilot` / `useThrustVectoring`）→ **拒绝该型** | `unsupported()` L2313–2320 |
| **重复 `endSpeed`** 资源 → 拒绝 | L2321–2322 |
| **非恒定 `Cy` 表** → 拒绝 | L2323–2324 |
| **单一目标点**：永久锁定、无竞争回波、无载机雷达/数据链调度 | `BOUNDARIES` L2523–2524、L2750–2751 |
| **无损伤/击毁模型** | L2761、L2528 |
| **无网格碰撞、无地形、平地 + 标准大气、无随机推进散布 / 无环境修正** | L2527–2528 |
| **无批量/向量化接口**：`Calculator` 是无状态标量句柄，重复调用**重算**（无缓存） | L2903–2904、README L218；grep `simulate_many/vectoriz/cache` 全空 |
| **无 ΔV/BC 概念**：求解器只读 blk 的 `force` / `CxK`，想要 (ΔV,BC) 参数化缩放只能 monkeypatch `wt_missile.load_profile` | grep `dv\|bc\|delta_v\|thrust_scale\|cx_scale\|ballistic` 唯一命中是局部变量 `dv`（相对速度）L1929/2419；现有外壳的做法见 `model/wtgame.py:192–217` |
| **制导内量只给"请求量"，不给"闭环指标"**：没有 `t_loft_end`、没有 `n_eff`、没有 `k_go` | 对照 `_CF_COLUMNS` L2009–2018 |
| `observation.mode="ideal"` 与延迟/偏置**互斥** | L197–198（实测报错） |
| 记录目标轨迹必须覆盖整个 `duration_s`，不许外推 | L279–280 |

### 1.5 性能量级（本机实测）

| 场景 | 标准档实测中位数 | 求解器交付方 README 声称（Linux / 9950X3D） |
| --- | --- | --- |
| 0.1 s 飞行 | 6.1 ms | 1.35 ms |
| 1 s | 29.5 ms | 7.18 ms |
| 5 s | 143.5 ms | 32.76 ms |
| 20 s | 550.8 ms | 131.89 ms |
| 60 s | 3102 ms | 392.04 ms |
| 每飞行秒 | **~29–52 ms/s** | ~6.57 ms/s（README L271） |

* **本机比交付方基准慢约 5–9 倍**，其线性式 `0.54 + 6.57·T` 不能直接搬来做容量规划。
* **fast 档在本机等于 `python-legacy`**：60 s 工况 3246 ms，`compiled_fallback_reason =
  "No C compiler/cache available; install MinGW-w64 or use a Visual Studio developer terminal on Windows"`（L2100–2146）。
  C 内核的加速比本机无法实测；交付方 README L279–289 的同机对比是 60 s：392.04 ms → 24.24 ms，即 **≈16×**。
* **标准档 vs python-legacy 数值一致**（AIM-120D / 60 km 金标）：`max_alt` 10629.9961 vs 10629.9961（差 0.000000），
  `v_impact` 差 8.2e-6 ⇒ 本机上两档是同一物理的同一条算术路径。
* **整张等时线网格的实际吞吐（走外壳 `EngineRunner` + `run_grid`）**：36 工况 / jobs=8 / 13.4 s ⇒ **0.37 s/工况**；
  外推 32×57 = **1824 格点 ≈ 11.3 min**（全命中区）。脱靶格点会飞到资源寿命（PL-12 `timeLife = 80 s`）⇒ 最坏 ~20–25 min。

---

## 2. 现有外壳提供了什么（含"死代码还是仍在用"的判定）

判定方法：对每个"看起来像物理"的模块，用 grep 找**当前默认档位（standard/fast）**路径上的调用点。
`config.backend` 默认 `"standard"`（`config.py:193`、`BACKENDS` `config.py:214`），
`run_sweep` 分派在 `sweep.py:85–118`，飞行分派在 `flight.py:212–300`。分类记号见下表。

### 2.1 `src/missile_sim/`（5235 行）

| 模块 | 行 | 一句话职责 | 分类 | 标准/快档路径上的实际状态 |
| --- | ---: | --- | --- | --- |
| `atmosphere.py` | 76 | WT 大气（密度/温度/声速） | **A 可废弃** | 仅 `sim.py:279/308/902` 调用 → **默认档位不经过** |
| `ballistics.py` | 186 | tgo / LOS 率 / PN 指令 / 增益表 / 高抛退出判据 | **A 可废弃** | 仅 `decide.py:146–173` → `sim.py` 调用；默认档位不经过 |
| `aero.py` | 246 | f(M) 阻力、升力配平、诱导阻力 | **A 可废弃** | 物理仅 `sim.py`；**唯一存活点**是 `config.py:488`（`summary_lines` 打印标签）与 `make_missile_bc_overlay.py:297/419`（图中标签） |
| `burn.py` | 125 | 燃烧剖面（质量/推力 = t 的纯函数） | **A 可废弃** | 物理仅 `sim.py`/`model/flash.py:33`；`provenance.py:28–39` 只把它当**描述性元数据** |
| `decide.py` | 200 | 阶段机 + 终止判定 + `ST_*` 状态词表 | **A + E 混合** | 物理函数 L97–200 仅 `sim.py` 调用 ⇒ 死；但 `ST_*`/`STATUS_LABELS`（L17–52）被 `sweep.py:32`、`cli.py:40` 当**词表**用 ⇒ 仍在服役 |
| `sim.py` | 935 | 2D 点质量弹道（标量 + 向量化双路） | **A 可废弃** | 唯一活入口是 `flight.py:134 flash_flight`，而 `flash` 已不是默认档位；`sweep.py:102` 只在 `backend=="flash"` 时走它 |
| `config.py` | 529 | 配置/单位/派生量（ΔV↔ve、BC↔CxK、标准弹 apply） | **C 需重写** | 一半是领域价值（标准弹/场景/CLI 覆盖），一半是 Flash 专属（`aero`/`burn`/`loft` 旋钮） |
| `standard.py` | 283 | 11 弹池 → 不可变快照 + `profile_hash()` | **D 领域价值** | 保留（`io.py:410` 用它给 `standard`/`profile_hash`） |
| `flight.py` | 306 | 后端无关"跑一条弹道"统一入口 | **C 需重写** | `_runner_for()` L225 已切到注册表；但 `flash_flight`/`SampleTrace`/`trace_from_samples` 是 Flash 残留 |
| `sweep.py` | 507 | ΔV×BC 网格 → 等时线 + CSV/摘要 | **D 领域价值** | 保留；`run_sweep`(L85)/`run_sweep_engine`(L154)/`run_sweep_pro`(L273) 三头应合一 |
| `scanner.py` | 463 | 扫描规格 / 指纹 / 时效 / run 目录 | **D 领域价值** | 保留 |
| `plot.py` / `crossplot.py` | 351 / 431 | 出图版式（散点/等时线/弹道/基准曲线）；`aam_fit` 版式交叉图 + 等时线叠加 | **D 领域价值** | 保留；`crossplot.py:278` 用 `elf_sha256` 有无反推后端，会把两档都认成 flash（交接文档 §6.3 已记） |
| `provenance.py` | 78 | 产物自描述块 | **D 领域价值** | 保留，但 `burn`/`aero_model`/`loft` 三块对默认档位已是**空壳**，应换成求解器自报字段 |
| `pro.py` | 68 | Pro 兼容 shim | **A 可废弃** | `flight.py:244` 仅在 `backend=="pro"` 时用 |
| `cli.py` | 421 | 命令行入口 | **C 需重写** | `_run_single`(L159) 已改用 `TrajectoryRunner`(L182)；但大量 Flash 专属旋钮（`--aero`/`--loft-rule`/`--mass`）仍在 |
| `__init__.py` / `__main__.py` | 24 / 6 | 包导出 / 入口 | C / B | 导出面会随重写变 |

### 2.2 `src/missile_sim/model/`（4271 行，新三层）

| 模块 | 行 | 职责 | 分类 |
| --- | ---: | --- | --- |
| `spec.py` | 540 | 引擎契约：`EngineInputs` / `NativeResult` / `ModelSpec` / `Capability` / `EngineEnv` | **C 需重写**（`dv_target`/`bc_target`/`cache_key` 是给旧 Pro 兼容而留的包袱） |
| `io.py` | 470 | **唯一输入映射入口**：blkx → 参数块；ΔV/BC → `thrust_scale`/`cx_scale` | **D 领域价值**（重建的核心资产） |
| `wtgame.py` | 450 | 新引擎（两档）+ `selftest` + monkeypatch `load_profile` | **B 保留**（重建的起点） |
| `registry.py` | 337 | 模型注册表 + 第三方发现 | **C 需重写**（若只留一档，注册表可砍成一张常量表） |
| `env.py` | 63 | `EngineEnv` 显式运行环境 | **C** |
| `runner.py` | 465 | 进程池 + 缓存调度（`EngineRunner` L310 / `ProRunner` L122） | **C 需重写**（`restore_engine_inputs` L54 的 dataclass 往返是为跨进程传嵌套输入而生的补丁） |
| `cache.py` | 157 | 按模型分库的结果缓存 | **C 需重写** |
| `grid.py` | 95 | 网格执行内核 | **B 保留**（类型标注从 `ProRunner` 改 `EngineRunner`） |
| `record.py` | 365 | 结果 → 结构化记录 / manifest / 时效 | **D 领域价值** |
| `constants.py` | 82 | 共享常量 | **B**（要删 pro/flash 那几条） |
| `native.py` | 523 | Pro 原生包装（Unicorn + ELF + blk 注入） | **A**（引擎部分）**+ B**：`NativeResult` / `_patch_profile` / `_trajectory` / `HIT_EVENTS` 被 `wtgame.py:40` 复用 —— **删之前必须先搬走这 4 个** |
| `flash.py` | 526 | Flash 包装（向量化网格快车道） | **A 可废弃** |
| `__init__.py` | 198 | 模型层门面 | C |

### 2.3 `scripts/`（35 个文件，5857 行）

| 类别 | 脚本 | 处置 |
| --- | --- | --- |
| **A 与求解器重复/已被取代** | `calibrate.py`(100)、`calibrate_loft.py`(105)、`compare_paths.py`(169)、`check_consistency.py`(50)、`debug_batch_membership.py`(44)、`debug_hit_detect.py`(97)、`debug_terminal.py`(52)、`probe_aero_upgrade.py`(270)、`native_identify_loft.py`(194)、`native_speed_check.py`(161)、`native_compare.py`(292)、`pro_missiles.py`(138)、`smoke_baseline.py`(65)、`run_baseline.py`(124)、`run_ranges.py`(98)、`trace_table_params.py`(103) | **删**（≈2150 行）：全都在标定/对拍将被废弃的 Flash/Pro 物理 |
| **D 领域价值（保留）** | `missile_metrics.py`(123)、`build_standard_pool.py`(224)、`version_metrics.py`(155)、`workflow.py`(698)、`make_missile_bc_overlay.py`(503)、`pipeline.py`(431)、`workflow_web.py`(283) | 保留/小改 |
| **D 数据出处链（保留）** | `extract_wt_table.py`(132)、`extract_reference_points.py`(142)、`extract_missile_points.py`(121)、`compare_table_vs_blkx.py`(141)、`compare_wt_vs_figure.py`(95)、`blkx_vs_table_vs_figure.py`(158)、`build_missile_sources.py`(79)、`missile_sources.py`(78)、`scan_table_source.py`(92)、`find_wt_column_for_figure_point.py`(36)、`check_live_archive.py`(142)、`wt_missiles.py`(162) | 保留（`E:\WT` 数据链，与求解器无关） |

---

## 3. 重建后的最小外壳设计

### 3.1 模块划分（10 个模块 + 1 个 vendor）

```text
missile_sim/
├── spec.py      # 输入/输出结构（唯一的跨模块契约）                 ~250
├── solver.py    # 包装 wt-missile：加载/哈希/乘数施加/输出归一       ~350
├── pool.py      # 11 弹池 + blkx 权威口径（ΔV_blk/BC_blk/干重）     ~380
├── mapping.py   # (ΔV,BC) ↔ 引擎参数（唯一算法）                    ~120
├── engine.py    # 进程池 + 结果缓存 + 单/多工况执行                  ~380
├── grid.py      # ΔV×BC 网格 → t_hit 矩阵 → 等时线提取              ~220
├── record.py    # 记录 / manifest / 时效 / 出处                      ~330
├── figures.py   # plot + crossplot 版式（不变）                     ~780
├── cli.py       # 命令行 + 单工况                                    ~250
└── workflow.py  # 端到端（输入 JSON → 扫描 → 图 + CSV + 摘要）       ~600
                  ──────────────────────────────────────────────
                  合计 ≈ 3660 行（现 `src/` 9506 行）
```

**领域价值 vs 历史包袱一句话**：`pool` / `mapping` / `grid` / `record` / `figures` / `workflow`
是**这个项目存在的理由**（ΔV/BC 平面上的等时线包线图 + 可追溯出处），一行都不能少；
`spec` / `solver` / `engine` 是**胶水**，按求解器的形状重写即可；
`atmosphere` / `ballistics` / `aero` / `burn` / `decide` 物理 / `sim` / `flash` / `native` / `pro` 是**历史包袱**，全部删除。

### 3.2 关键接口草案

```python
# ---------- spec.py：只描述"求解器要什么"和"我们要记什么" ----------
@dataclass(frozen=True)
class Scene:                       # 与求解器 scenario 一一对应，不做多余抽象
    missile: str                   # "cn_pl12"
    duration_s: float = 150.0
    dt_s: float = CLIENT_DT        # 0.02083333395421505（客户端对象时钟）
    observation: str = "ideal"     # ideal | locked
    alt_m: float = 10000.0; vm0: float = 300.0; target_alt_m: float | None = None
    vt: float = -300.0;    range_m: float = 50000.0; hit_radius_m: float = 0.0
    wind_m_s: tuple = (0., 0., 0.); ground_height_m: float = 0.0
    target_maneuvers: tuple = ()
    version: str = "2.59.0.28"

@dataclass(frozen=True)
class Scaling:                     # (ΔV, BC) 的落点
    dv_target: float; bc_target: float; dv_blk: float; bc_blk: float
    thrust_scale: float            # = dv_target / dv_blk
    cx_scale: float                # = m_dry / (bc_target · S_d · CxK_blk)
    def key(self) -> str: ...      # 若沿用旧键必须逐字复刻（§4 R1）

@dataclass(frozen=True)
class Shot:
    ok: bool; event: str           # time_limit|lifetime|ground|contact|proximity_fuse
    t_end: float; t_hit: float     # t_hit: NaN = 未命中
    miss_m: float; max_alt_m: float; v_impact: float
    rows: list = ()                # 可选：68 列逐采样（2026-10-02 起）
    error: str = ""

# ---------- solver.py：与 vendor 的唯一接触面 ----------
def load(*, verify_sha256: bool = True) -> ModuleType: ...
def identity() -> dict: ...        # solver_sha256 / archive_sha256 / n_profiles
def run(scene: Scene, scaling: Scaling | None) -> tuple[dict, list]: ...
    # = 现有 model/wtgame.py:183–217：monkeypatch wt_missile.load_profile，
    #   只乘 force/force1/impulse*.force 与 CxK；不重算任何物理
def to_shot(scene, summary, rows) -> Shot: ...   # = 现有 to_native_result 的裁剪版
def backend_of(summary) -> str: ...              # compiled-c | python-legacy | python-standard
def fallback_reason(summary) -> str | None: ...

# ---------- pool.py / mapping.py ----------
def resolve(short: str, *, tag: str = "WORK") -> MissileProfile: ...
    # 现 standard.resolve 裁剪版：几何/质量/推力/引信/寿命/增益/高抛 + profile_hash()
def blk_metrics(missile: str, *, tag=None) -> BlkMetrics: ...
    # ΔV_blk（逐级齐奥尔科夫斯基）/ BC_blk / S_d / m_dry / CxK_blk
    # 权威公式仍只在 scripts/missile_metrics.py
def scale_for(dv_target: float, bc_target: float, m: BlkMetrics) -> Scaling: ...

# ---------- engine.py ----------
class Engine:
    def __init__(self, scene: Scene, *, jobs: int = 8, cache: Path | None = None): ...
    def one(self, dv: float, bc: float, *, keep_rows=False) -> Shot: ...
    def many(self, cells: Iterable[tuple[float, float]], *, progress=None) -> list[Shot]: ...
    def close(self) -> None: ...
    stats: dict                    # {"native": n, "cache": m}

# ---------- grid.py / record.py ----------
def sweep(engine, grid: Grid2D, *, progress=None) -> np.ndarray: ...  # t_hit (n_dv, n_bc)
def isolines(t_hit, grid, *, step: float = 2.0) -> list[dict]: ...
def monotonic_report(...) -> list: ...
def make_manifest(*, run_id, scene, pool, grid, solver_identity) -> dict: ...
def check_staleness(manifest: dict, current: dict) -> tuple[bool, list]: ...
def write_cases_csv / write_isolines_csv / write_summary(...) -> Path: ...
```

### 3.3 三个设计决定（与现状的差别）

1. **取消"档位"这一概念层**。求解器只有一条物理，`fast` 只是同一物理的 C 内核（本机还必然回退）。
   重建后 `tier` 是**运行参数**，而不是一张 `ModelSpec` + 一个缓存文件 + 一套 CLI 取值域
   （现状：`registry.py:48–81` 两张 spec + `results/cache/{standard,fast}.json`）。缓存键里带 `backend` 即可 —— §4 R1 反正要求换键。
2. **删掉"模型注册表 + 第三方模型发现"**（`registry.py:180–234`，~120 行）：当前只有内置两档在用，
   第三方插桩只在 `tests/test_model_api.py` 里被测试，没有实际消费者。将来真接第三方再引入。
3. **轨迹不再经过 `SampleTrace` 反算**：求解器的 `rows` 已含 `missile_v[xyz]_m_s` 与 `qx..qw`，直接取列即可；
   现状 `flight.py:67–92` 从 `(x,h)` 差分反算 `gamma`，是"Flash 只给位置"时代的产物。

---

## 4. 迁移代价

### 4.1 行数账

| 动作 | 内容 | 行数 |
| --- | --- | ---: |
| **删除** | ① `sim.py` 935、`model/flash.py` 526、`model/native.py` 引擎部分 ~380、`aero.py` 246、`ballistics.py` 186、`decide.py` 物理 ~150、`burn.py` 125、`atmosphere.py` 76、`pro.py` 68、`config.py` 的 aero/burn 旋钮 ~150 ⇒ **~2840**；② `scripts/` 16 个标定/对拍脚本 ⇒ **~2150** | **~4990** |
| **重写 + 新写** | 重写 `spec→models`、`runner→engine`、`cache`、`registry`、`env`、`cli`、`flight`（~900–1300）；新写 `solver.py`、`mapping.py`、等时线部分（~500–700） | **~1400–2000** |
| **保留** | `io.py` 的 blk 解析/归一、`standard.py`、`record.py`、`plot.py`、`crossplot.py`、`sweep.py` 的 CSV/摘要 | **~1500** |
| **测试** | 现 17 个测试文件 4505 行；`test_aero/test_atmosphere/test_ballistics/test_burn/test_sim/test_pro`（1457 行）整体作废 | 需新写 ~1200–1800 |

### 4.2 风险点与不可逆点

| # | 风险 | 证据 | 处置 |
| --- | --- | --- | --- |
| **R1** | **`EngineInputs.cache_key()` 被测试冻结**：`tests/test_model_api.py:72 test_cache_key_matches_frozen_reference`。注意两处文档漂移：`native.py:168–169` 与交接文档 §7 都写"在 `tests/test_model_io.py`"，实测该文件里**没有**任何 `cache_key` 断言 | `spec.py:333–346`、`native.py:165–171`、`tests/test_model_api.py:72–78` | 重建必然换键。若还想复用旧缓存，必须**逐字复刻** `json.dumps([...])` 的字段顺序与 `round(...,6)`；否则 1844 条全部作废 |
| **R2** | **`results/pro_cache.json` 是既有资产**：实测 **`n_entries = 1844`**（文档里写的 1824 是网格点数 32×57，不是条目数） | `results/pro_cache.json`、`scanner.py:106` 的 `Grid.make(800,1110,10,2450,3850,25)` | 见下方"不可逆性辨析" |
| **R3** | **行尾纪律**：`.gitattributes = * -text`，仓库行尾**混杂**且**有 CRLF 与 LF 两种**（实测：`flight.py`/`pro.py`/`scanner.py`/`sweep.py`/`model/{constants,grid,io,native,record,runner}.py`/`scripts/pipeline.py`/`tests/test_pro.py` 是 CRLF；其余 LF） | `.gitattributes`、`AGENTS.md`「Version Control」、交接文档 §7 | 重建时**新文件一律 LF**，删掉 CRLF 文件即可，不要"统一" |
| **R4** | **`native.py` 是隐性公共依赖**：`wtgame.py:40` 从它 import `NativeResult`/`_f`/`_patch_profile`/`_trajectory` | `wtgame.py:39–41` | 删 `native.py` 前先把这 4 个符号搬到 `spec.py`/`solver.py` |
| **R5** | **产物断代**：`figures/` 与 `results/` **已入库**，重建后 `plot/crossplot` 若改了出处面板字段，旧图重跑会全量 diff | `AGENTS.md`「Version Control」 | 只改数值来源，不改版式；`crossplot.py:278` 的反推逻辑要一起改 |
| **R6** | ~~性能预期：本机无编译器，重建后仍是纯 Python 单核 ~30–50 ms/飞行秒~~ **已解除**：VS 2022 的 MSVC 在位，内核编译一次即缓存，`fast` 实测 17.5~23×（金标 60 s 工况 1765 → 77 ms，1824 格点网格 ≈4.7 min → ≈0.27 min） | `NEW-SOLVER-HANDOFF.md` §4.1 | 重建时**保留"档位 = 算术后端"这层抽象**；内核缓存键跟源码/开关绑定，改内核要重编一次 |
| **R7** | **工作树正在被改**：快照时刻 7 个未提交文件，`cli.py` 在我读取期间从 416 行变成 421 行 | `git status` / `git diff --stat` | 重建前必须先落定当前分支，或另起 worktree |

**不可逆性辨析（重要）**：`pro_cache.json` 的"44 min"是 **Pro（Unicorn 执行 ELF）** 的成本；
**用新求解器重跑同一张 32×57 网格实测约 11.3 min（jobs=8，§1.5）**。所以这份缓存**在算力上并不稀缺**，
它真正不可逆的是**历史可比性**：里面 1844 条的 `t_hit` 是旧 Pro 口径（PL-12 基准 45.1983 s），
新求解器同一工况是 45.1851 s（差 0.029%）。一旦删除或改变键，就再也无法在同一张图上叠加"旧 Pro 口径"的等时线。

---

## 5. 与"继续改造现有外壳"的对比

| 维度 | 继续改造（当前 `new` 分支路线） | 从头重建 |
| --- | --- | --- |
| 剩余工作量 | 交接文档 §6 还剩 6 项（`cli._run_single` 已完成、`scripts/*` 收尾、`tests/test_wtgame.py`、`results/models.json` 重生成、文档、全量验收）≈ **3–5 天** | **8–15 天**（含新测试） |
| 代码规模 | `src/` 9506 行，其中 **~30% 是死代码**，且新旧路径并存 | ~3660 行，无死代码 |
| 阅读成本 | 要读完 Flash + Pro + 新档三套物理才能确定"哪条路径在跑"（`sweep.py` / `flight.py` / `scanner.from_config` 各三分支） | 一条路径 |
| 历史可比性 | **完整保留**（旧脚本、旧缓存、旧图逐字节可复现） | **断链**（除非刻意复刻 `cache_key` 与旧 Pro 口径） |
| 回归测试 | 328 项已全绿，可直接复用 | 需重建 ~1200–1800 行测试 |
| 风险 / 收益 | 低风险、随时可停；收益 = 把技术债摊平 | 中风险、一次性切换；收益 = 架构干净、可持续演进 |

**判据（结论性）**：

* **继续改造** —— 若未来 1–2 个月的主线是"接着出包线图、继续和旧 Pro / 参考图对拍"。这条路已走完 ~70%。
* **重建** —— 若已确认"旧 Pro / Flash 口径不再需要"，且下一步要**长期迭代物理口径**（换 `.29`/`.30` 资源、
  接第三方模型、加多目标/编队/雷达模型）。此时那 30% 死代码会**持续**成为每次改动的阅读税与误改风险。
* **折中（推荐）** —— 先花 1–2 天"**止血式清理**"：`sim.py`/`flash.py`/`native.py`/`pro.py` 与 16 个标定脚本移入 `legacy/`
  （或直接摘掉 `pro`/`flash` 的注册与缓存路径），观察一周。之后再按 §3 重建，输入已干净得多，`pro_cache.json` 的历史角色也已想清楚。

---

## 6. 需要用户拍板的未决问题

1. **旧 Pro / Flash 口径还要不要？** 决定 `results/pro_cache.json`（1844 条）、`scripts/native_compare.py` 等
   12 个对拍脚本、以及 `pro`/`flash` 两个注册名是否整体退役。**这一条决定重建 vs 继续改造。**
2. **`EngineInputs.cache_key()` 允不允许变？** 允许 ⇒ 重建无约束；不允许 ⇒ 必须逐字复刻 `json.dumps([...])`
   的字段顺序与 `round(...,6)`，并把冻结测试一起搬过去。
3. **"档位"这个概念要不要留？** 当前 `standard`/`fast` = 两张 `ModelSpec` + 两个缓存文件 + 一套 CLI 取值域；
   本机 `fast` 必然回退 `python-legacy`，两档实测数值一致。是否只留一档，把 `fastmode` 降级成运行开关？
4. **要不要装 MinGW-w64 拿回 ~16× 的 C 内核？** 本机实测 60 s 工况纯 Python 3102 ms，交付方同机对比 392 → 24 ms；
   装了之后整张 1824 格点网格从 ~11 min 降到 ~1 min。
5. **第三方模型插件机制保留吗？** `registry.py` 的 `$WT_MODELS_PATH` 发现机制（~120 行）只在测试里被用到。
6. **重建期间冻结工作树？** 快照时刻有 7 个未提交文件且正在被修改；重建需要冻结基线（新分支或 worktree）。

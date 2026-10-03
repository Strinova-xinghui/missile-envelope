# NOTES — 交接文档（结论优先；压缩上下文或换会话后看这一份即可接上）

**最后更新**：**已启用 git 管理**（`main` 分支，初始提交 `11a5976` = 启用前的全部状态）。
第二阶段——只维护 `fig_missile_bc_overlay_crossplot` 一张图并美化：
等时线步长 10 s → **1 s**、**线性拟合已彻底移除**、坐标轴范围/刻度分辨率**改用 `自动化分析` 工作流规格**（800~1110 / 2450~3850）。
第三阶段——**升力/诱导阻力升级已实现并实机验证**（全部见 **`AERO_PLAN.md`**）。
**证据规则（用户指定）：信源交付的文件包为准，聊天记录转述冲突处一律算转述错误。**
要点：① 气动三档 `legacy/mach/full`（默认 `full` = f(M) + 升力配平 + 诱导阻力），
`--aero legacy` **逐字节复现旧扫描结果**；
② 信源那个文件包里的仿真器**能在这台 Windows 上跑**（装 unicorn 即可），直接执行游戏 2.59.0.28 原生代码。
第四阶段——**标准弹落地（默认 PL-12、11 弹池自选）+ 通用 N 段有限燃烧**，见 **`AERO_PLAN.md` §14–§17**：
① 弹池 `results/missile_standards.json`（11 型，与权威 ΔV/BC 口径逐值一致），`--standard` 可切；
② 燃烧从 blk 读取（PL-12：198→160→132 kg、34 960 N/2.5 s + 12 880 N/5.0 s），
`--burn instant` **逐字节复现升级前产物**（A1 安全绳，`results/*_a1_std_refactor.*` 钉住）；
③ **与 Pro 对拍：速度偏差从 +801 m/s 降到 ≤11.8 m/s、质量/推力时序逐点吻合、
≥50 km 命中时间进 1% 以内**；
④ **高抛退出判据已换成游戏口径**（`|λ̇|≥loftTargetOmegaMax` 或 `λ≤loftTargetElevation`，逐弹从 blk 填），
<40 km 的偏差从 −57% 一次性收到 −1.7%：**全包线 9/9 可对拍、中位 0.65%、最大 2.57%、绝对误差 ≤0.23 s**；
旧口径组合变为五件套（多一个 `--loft-rule heuristic`）。
⑤ 遗留：高抛**控制器**仍顶 γ 而非 θ（朴素改法不稳定，正解是隐式解，见 `AERO_PLAN.md` §17.5）；过载滞后未做。
第五阶段——**Flash 后端落地 + 工作流升级 + 11 弹标签**（见 `AERO_PLAN.md` §18）：`backend` 成为配置/CLI 一等字段（`--backend pro` 明确报错退出，接口留给下一阶段）；新增 `src/missile_sim/provenance.py`，**workflow / sweep / 交叉图三处产物共用同一份出处块**（后端 + 标准弹名/指纹/回退 + 燃烧 + 高抛 + 气动 + dt）；工作流输入支持 `backend`/`standard`/`sim.loft_rule`，逐弹评估改为**每型用各自标准弹**，主图的"ΔV–BC 拟合关系"面板按二阶段决定**换成出处面板**，轴规格与出图元数据与交叉图共用（工作流图现在也是字节可复现的）；`iso_step` 默认 10→1 s；Web 表单加标准弹/燃烧/高抛选择器。自检 142 → **156/156**（新增 `tests/test_workflow.py` 14 项）。
另：逐项对照 `charts.md` 后确认交叉图**本来就合规**（轴范围/刻度/网格/字号/点标签规格），只补了"标签全部 bold"；把标签偏移与样式抽成共用常量并把**工作流主图的 11 型标签**补上（此前只有红点没有名字），图例移出轴外避免压住 Derby/MICA/R-77 那簇。
**下一阶段已定调：美化 / 新功能 / Pro**，具体清单见 §10。

---

## 0. 30 秒接上（新会话请按序执行）

```powershell
cd E:\导弹包线图
$env:PYTHONUTF8="1"          # 中文控制台
$env:PYTHONPATH="src"        # 免安装直接跑仿真器
$env:WT_NATIVE_PKG="E:\WT\wt-missile-backend-runtime-1.0.1"   # 原生运行包（Pro 后端必需）

git log --oneline -5         # 已启用 git：main 分支，先看最近提交
git status -s                # 应干净

# 三段式流水线（见 AERO_PLAN §22）：四段可分别单跑
python scripts\pipeline.py stat                     # ① 第一层：blk 统计 → 弹池
python scripts\pipeline.py model --standard PL-12   # ② 第二/三层：一个工况 + 结构化记录
python scripts\pipeline.py scan  --standard PL-12   # ③ 第二部分：ΔV/BC 扫描（1824 工况 ≈ 44 min）
python scripts\pipeline.py plot  --iso-step 1       # ④ 第三部分：aam_fit 版式 + 等时线

python -m missile_sim                    # 旧入口单工况（Pro 后端；PL-12 命中 45.10 s）
python -m missile_sim --aero legacy --backend flash   # 旧口径回归：命中 60.81 s
python tests\run_tests.py                # 249 项自检（约 500 s，含原生用例）
```

⚠ **多进程必须从 `.py` 文件跑**：Windows 的 spawn 会重新 import 主模块，
从 `python - <<EOF`（stdin）跑会 `BrokenProcessPool`。

读文档顺序：**本文件 → `README.md`（权威规范：模型/口径/产物/局限）→ `AERO_PLAN.md`（§22 三段式架构、§19~21 Pro 口径）→ `AGENTS.md`（仓库约定、数据源、提交约定）**。

---

## 1. 一句话状态

`E:\导弹包线图` 下是一套**三段式流水线**：**模型（三层：输入/计算/输出）→ ΔV/BC 扫描器 → 绘图**。
模型层默认走 **Pro 后端**（信源包里执行游戏机器码的原生仿真器）；扫描器改基准弹的**推力倍率与 CxK**
来扫 `(ΔV, BC)`，结果带版本戳与时效判定；绘图是 **`aam_fit` 版式 + 等时线叠加**。
基准弹默认 **PL-12**（11 弹池可选）；50 km 迎头 / 10 km / 300 对 −300 m/s 下 PL-12 命中 **45.10 s**。
Flash 快模型保留为近似档（`--backend flash`，无原生包时可用），**不再是正式口径**。

---

## 2. 当前产物清单（按用途）

| 类别 | 文件 | 说明 |
| --- | --- | --- |
| **本阶段唯一主图** | `figures/fig_missile_bc_overlay_crossplot.png`（+`.pdf`/`.svg`） | **交叉图**：1 s 等时线（按命中时间着色 + 色标）+ 最新版 11 型弹值；120C 加环为高抛基准；**无拟合线** |
| 主图 | `figures/fig_sweep_isotime_baseline.png` | 等时线 + 散点（ΔV 800~1500 × BC 1700~4000，2 s 步长） |
| 工作流 | `figures/workflow_<tag>_main.png` / `_detail.png` | 自定义输入 → 等时线 + 弹点 + 拟合 + 逐弹结果表 |
| 辅助图 | `fig_range_sweep.png`、`fig_loft_family_baseline.png`、`fig_traj_baseline.png`、`fig_baseline_time_baseline.png` | 距离/高抛角/单弹道/存速曲线 |
| 数据 | `results/cases_baseline.csv`、`isolines_baseline.csv`、`summary_baseline.json` | 360 工况逐点结果、等时线顶点、扫描摘要 |
| 数据 | `results/missile_points.json` | **最新版弹值（出图默认口径）** |
| 数据 | `results/missile_shot_crossplot.json` | 交叉图的全部出图参数（轴规格/网格/等时线等级/命中率）+ 11 型逐条结果 |
| 数据 | `results/base257_missiles.json`、`missile_sources_all.json` | 2.57 基线（对照）、三套口径快照+拟合 |
| 数据 | `results/version_metrics.json`、`blkx_vs_table_vs_figure.json` | 各版本 ΔV/BC、历史三方对照（核对用，已不出图） |
| 历史 | `results/reference_fig.png`、`reference_points.json` | 用户提供的参考图与其像素点（**不再进图**） |
| 方案文档 | `AERO_PLAN.md` | **气动升级的评估、实施与实机验证**（公式验收、冲突裁决、α 闭合方式、量化影响、§9 原生对拍） |
| 探针 | `scripts/probe_aero_upgrade.py` → `results/aero_upgrade_probe.json` | 三种阻力口径同工况对比；**不改模型**（运行时替换 `_accel`） |
| 气动代码 | `src/missile_sim/aero.py`、`tests/test_aero.py` | 三档气动模型（f(M)/F(M) 双实现、升力配平、诱导阻力）+ 28 项对拍测试 |

---

## 3. 权威口径（唯一来源，改这里才改口径）

`E:\WT\War-Thunder-Datamine\自动化分析\skills\wt-aam-analysis\scripts\plot_version_compare.py` 的 `metrics()`，
在本仓库复刻为 **`scripts/missile_metrics.py`**（逐行同式）：

```text
fu1 = mass - massEnd                      # 一级装药
fu2 = massEnd - massEnd1                  # 二级装药（无 massEnd1 时为 0）
Isp1 = force*timeFire/(9.81*fu1);  dV1 = Isp1*9.81*ln(mass/(mass-fu1))
Isp2 = force1*timeFire1/(9.81*fu2); dV2 = Isp2*9.81*ln((mass-fu1)/(mass-fu1-fu2))
ΔV   = dV1 + dV2（有二级）或 dV1
dry  = mass - fu1 - fu2 = massEnd1
BC   = dry / (CxK * (caliber/2)^2 * pi)   # caliber 在 blkx 里已是【米】
```

**两个曾算错的坑**：① 只读 `mass - massEnd` 当全部装药、按单级算（二级装药在 `massEnd1` 里）——
120A 会从 820.5 变 252、PL-12 从 932.6 变 490；② 把 `caliber` 当毫米（它是米）。
历史版本用 `git show <tag>:<路径>`（datamine 是真 git 仓库，tag 例：`2.57.1.132`）。

---

## 4. 已验证的数值（可复现）

**最新版弹值（WORK = 2.59.0.11）**，复现：`python scripts\version_metrics.py`

| 弹 | ΔV | BC | t_hit（50 km 迎头） | 弹 | ΔV | BC | t_hit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 120A | 820.5 | 3609.0 | 62.2 s | PL-12 | 932.6 | 3078.1 | 63.3 s |
| 120C | 897.4 | 3624.0 | 59.9 s | PL-12A | 989.1 | 3245.9 | 60.4 s |
| 120D | 891.3 | 3653.8 | 59.9 s | R-77 | 965.7 | 2568.8 | 67.9 s |
| AAM-4 | 826.3 | 3683.9 | 61.5 s | R-77-1 | 1099.5 | 2705.6 | 63.2 s |
| MICA EM | 947.0 | 2636.0 | 67.6 s | Derby | 932.8 | 2567.0 | 68.8 s |
| R-Darter | 913.9 | 2631.2 | 68.5 s | | | | |

其他已核实项：

* **实机 = 解包数据**：`E:\War Thunder\warthunder.yup` 索引里 `aces.vromfs.bin`
  length=18,691,594、mtime=1789133674，与 datamine 解包源一致；实机 `content\pkg_*.ver` = `2.58.0.36`
* **版本漂移**（2.57 → 当前）：MICA ΔV −155.5/BC +649.1、120A −67.8/+745.1、AAM-4 −16.5/+594.2、
  R-77 +13.5/+378.1、R-77-1 −23.8/+409.9；Derby / R-Darter 无变化
* **WT.xlsx 表内公式复算 vs 缓存值**：32/34 列一致（例外 R-27ER 的 BC、AIM-7F high-alt 的 ΔV，工作簿自身有问题）
* 基准单工况（ΔV=865.3、BC=3624、full 档）：50 km 迎头命中 **45.11 s**、最高 15 040 m、命中点 **672.0 m/s**、高抛 11.70 s 结束
  （legacy 档：60.81 s / 14 970 m / 366.5 m/s / 14.27 s，`--aero legacy` 可逐位复现）
* 高抛角（50 km，full）：0°→45.82 s/533 m/s；10°→44.73 s/639；22°→45.11 s/672；39°→47.38 s/685
* **与游戏原生代码对拍**（信源 2 仿真器执行 2.59.0.28 ELF）：15/30/50/70 km 偏差 +3.87/+0.63/+0.25/+0.72 s
* 距离：70 km 无高抛能量耗尽未命中，有高抛 92.59 s 命中
* 网格：360/360 全命中，t_hit 45.5~86.6 s，每个 ΔV 列内 t_hit 随 BC 严格递减（等时线成立前提）
* 交叉图网格（1 s 等时线专用）：ΔV 800~1110 /10 × BC 2450~3850 /25 = **1824/1824 全命中**，
  t_hit **53.4~73.9 s**（≈ 20 条等时线：54~73 s），仿真 ~25~35 s
* 自检：`python tests\run_tests.py` → **92/92 通过**

---

## 5. 复现命令（按依赖顺序）

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python scripts\version_metrics.py              # ① 权威口径：各版本 ΔV/BC（WORK + git tags）→ results/version_metrics.json
python scripts\build_missile_sources.py        # ② 生成弹值数据（最新版 + 2.57 基线）→ results/*.json
python -m missile_sim --sweep --tag baseline   # ③ 等时线扫描 → results/cases_*.csv, isolines_*.csv, summary_*.json, figures/*
python scripts\make_missile_bc_overlay.py                    # ④ 交叉图（1 s 等时线 + 着色 + 色标，默认出 png+pdf+svg）
python scripts\make_missile_bc_overlay.py --formats png      # ④' 只要位图
python scripts\make_missile_bc_overlay.py --no-colorbar      # ④'' 单色蓝线版（无右侧色标）
python scripts\workflow.py run                 # ⑤ 完整工作流（命令行）
python scripts\workflow.py web                 # ⑤' 网页表单 http://127.0.0.1:8765/
python tests\run_tests.py                      # ⑥ 自检
# 历史核对（不再进图）：extract_wt_table.py / extract_reference_points.py / compare_*.py
```

**提交（每一阶段收尾一次）**

```powershell
git status -s                                  # 先看这一阶段到底动了哪些文件
git add <本阶段涉及的文件…>                    # 不要 git add -A 夹带无关改动
git commit -m "一句话说清这一阶段做了什么"
git log --oneline -5                           # 核对
```

约定见 `AGENTS.md` "Version Control"：身份是**仓库级**的（`MK <MK@localhost>`，本机没有全局身份）、
`figures/` 与 `results/` **照常入库**（它们是交付物且可复现）、`.gitattributes` 固定 `* -text`
（行尾原样存储，**不要开 `core.autocrlf`**）、绝不把 `E:\WT` 下的东西加进来。

---

## 6. 下一阶段的接口（直接可用的接缝）

| 想扩展的方向 | 现有接缝 |
| --- | --- |
| 目标机动（蛇形/桶滚/俯冲） | `src/missile_sim/sim.py` 里目标运动只有 `tx = tx0 + vt*t`、`th = target_alt`；`Case` 已支持 `vt/alt/target_alt/range0/mass` |
| 高度差交战 | 已实现：`--target-alt`、`Case.target_alt`、`scenario.target_alt`（单工况与批量都支持） |
| 阻力标定 | `configs/baseline.json` 的 `drag.drag_base`（现 1.0）；单工况可直接 `--drag-base` |
| 换弹/换口径 | `scripts/build_missile_sources.py` + `--source latest/base257`；`configs` 里 `mass.mass_anchor`、`Case.mass` |
| 扫描范围/步长 | `--dv-min/max/step`、`--bc-min/max/step`、`--iso-step`；交叉图默认 ΔV/10 × BC/25（配 1 s 等时线） |
| 换图规格/版式 | `scripts/make_missile_bc_overlay.py` 顶部常量：`FIG_SIZE/FIG_DPI/XLIM/YLIM/X_MAJOR/X_MINOR/Y_MAJOR/Y_MINOR/ISO_CMAP/AX_RECT/LBL_OFFSETS`；轴规格来源 = `自动化分析/skills/wt-aam-analysis/references/charts.md` §一 |
| 多工况批量 | `missile_sim.simulate_batch(cfg, dv, cxk, theta_loft_deg=…, target_alt=…, mass=…)` 返回 `BatchResult`（扁平数组） |
| 单工况含弹道 | `missile_sim.simulate_one(cfg, Case(...), record_trace=True, stride=n)` → `SimResult.trace` |
| 网页/脚本集成 | `scripts/workflow.py::run_workflow(cfg_dict, verbose=…)` 返回带 `_paths` 的汇总字典 |
| 用现成的外部工作流 | `E:\WT\War-Thunder-Datamine\自动化分析\skills\wt-aam-analysis\scripts\run_plot.py`（旧 vs 新 + 箭头 + adjustText 风格） |

---

## 7. 未解决 / 已知偏差

1. **气动已按游戏口径实现（原"缺 `f(M)`"已修）**：`D = q·S_ref·CxK·drag_base·f(M) + 诱导阻力`，
   三档 `legacy/mach/full` 默认 `full`。与游戏原生代码对拍 ≥30 km 偏差 ≤2.4%。
   剩余三条气动偏差：α 是准定常配平（非姿态量）、过载无建立时间、需求超升力峰值时诱导阻力低估。
   见 `AERO_PLAN.md` §2/§9。`--aero legacy` 可逐位复现旧数字。
2. **高抛项公式用错（残差主因，2026-09-25 由原生探针定论）**：真值 `a_loft = k_loft·(θ_loft − θ_body)`，
   **无速度因子、目标角是弹体俯仰 θ**；本项目是 `k_loft·(θ_loft − γ)·v`（乘了 v 且用 γ）。
   退出判据本身已于第五阶段换成游戏口径（`loft_exit_game`），且"退出即永久"的语义经 50 km 原生轨迹
   反解证实**是对的**。见 `AERO_PLAN.md` §19.1/§19.2；改法与 Flash 侧新增 θ 状态的方案见 §10.2。
3. **法向过载上限写死 35 g**：权威文档给的是 `staticG ≈ min(kappa·q_kPa, B)`，
   `kappa = 1000·SL·min(CyK·finsAoa, CyPeak)/(m·g)`、`B = finsLatAccel·massInit/m ≈ 51 g`。
   ⇒ 10 km/300 m/s 只有 **5.7 g**；高动压侧被 B 卡在 51.3 g。本项目 `reqAccelMax = 35 g` < B，故 B 当前不生效。
   见 `AERO_PLAN.md` §2.4（`aero.clip_lift_peak` 是部分修法，默认关）。
4. **过载"立刻生效"，没有建立时间（末段系统性乐观）**：原生机器码实测 0→20 g 阶跃的
   `t90,50` = **65~146 ms**（AIM-120C5 新参数 81.25 ms，一阶 τ ≈ 35 ms）。
   末速 700 m/s 时 81 ms ≈ **56 m**，而引信半径只有 12 m。修法见 `AERO_PLAN.md` §2.2/§2.3。
5. **制导增益表按统一口径硬编码**：一律用 `timeToHitToGain` + 固定 0.3 s 延迟；
   但 MICA **没有** `timeToHitToGain`、120C **没有** `timeToGain`，R-77/PL-12 的 `timeToGain` 是
   `(0.3,0)→(0.31,1)`、MICA 是 `(0.15,0)→(0.16,1)`。见 `AERO_PLAN.md` §4.2。
6. 目标不机动、等高平飞；未建模离轴角、导引头锁定距离、中制导/数据链、引信延时、杀伤概率。
7. 测试运行器自建（pytest 因网络受限装不上），语法兼容但功能子集（无 `-x/--lf`）。
8. `terminal_gamma_err_deg` 只在擦碰工况有意义（正命中时最近点距离为 0）。
9. WT.xlsx 表内 PL-12 / PL-12A 各有重复列（X/Y、Z/AA），当前取 Y/AA；改 `scripts/wt_missiles.py` 的 `PREFERRED`。
10. 未把 `自动化分析` 工作流整体接进来（只复用公式、tag 取数与 `charts.md` 的轴/网格规格）。

---

## 8. 踩过的坑（避免重复）

* 高抛退出判据若用"γ ≤ 视线角"：高抛段把 γ 顶在 +22°，判据永远不成立 → 120 s 能量耗尽
* 命中半径取 0：末段 10~16 m 擦碰被误判为脱靶（现用 blkx `proximityFuse.radius = 12 m`）
* 批量路径终止状态未冻结：命中后被 `miss_overshoot` 覆盖（曾 360 工况只命中 13 个）
* `prev_rng = rng` 未 copy、裁剪时循环变量 `m` 被 `keep` 覆盖、`np.float64` 是 `float` 子类导致误入标量分支
* 源码改动后行为不变时：先清 `__pycache__`（已踩两次）
* 参考图红点标签必须先核对（放大裁剪看标签锚线），否则会把 R-77 的坐标贴到别的名字上
* **AGENTS.md 是 CRLF 行尾**：多行字符串匹配容易失败，改它优先用 Python 脚本（指定 `newline=''`）
* **写文档时 Windows 路径里的反斜杠会被当转义**：`\figures`/`\results`/`` ```\text `` 曾把 `\f`、`\r`、`\t`
  真写进了 README.md（表现为行首字母丢失、代码块围栏被吃掉）。路径一律写成 `figures/...` 或用正斜杠/代码反引号包裹
* `fig.add_axes` 手排版式时脚注别贴太近：`bottom=0.135` 时 x 轴标题会压在脚注第一行上（现用 `bottom=0.175` + 脚注 y=0.088/0.040）
* 图例放在图内左下角会盖住从下边缘出去的等时线线名（72/73 s），现改为放在坐标区**上方**一行的无框图例
* `clabel(manual=[...])` 的落点必须**由该等级的折线几何反推**（现按"出口端沿折线回退 54 px"算），
  随手给点会被吸附到最近的另一条线，导致某条线永远没有线名
* **PowerShell 不支持 heredoc**：`git commit -F - <<'EOF'` 会直接 `ParserError`；提交信息先写文件再 `git commit -F <文件>`
* git 身份是仓库级的（本机没有全局 `user.name/user.email`）：换机器/换人提交前先 `git config user.email "…"`，
  否则提交会失败（提示 "Please tell me who you are"）
* **本仓库行尾是混的，而且"混"是正常状态**：`AGENTS.md`、`README.md`、`scripts/workflow.py` 是 CRLF；
  **全部 `results/*.json` / `*.csv` 也是 CRLF**，因为 Python 在 Windows 上 `Path.write_text()` 默认把 `\n`
  翻成 `\r\n`（脚本每次重跑都如此，是确定性的，所以 git 里不会抖）；`src/`、`tests/`、`configs/`、
  `NOTES.md` 是 LF。`.gitattributes` 用 `* -text` 原样存储，**别开 `core.autocrlf`、也别去"统一"行尾**
* 判断某文件到底是哪种行尾：`python -c "b=open('x','rb').read(); print(b.count(b'\r\n'), b.count(b'\n'))"`，
  或直接看 git 里的 blob：`git show HEAD:AGENTS.md | python -c "import sys;b=sys.stdin.buffer.read();print(b.count(b'\r\n'))"`
* **matplotlib 出图默认不是"可复现"的**（启用 git 后才暴露）：PDF/SVG 会写创建时间（`CreationDate`/`dc:date`），
  SVG 还用 `id(obj)`（内存地址）当元素 id（前缀 `m`/`p`/`image`…）——同一份数据每次出图整篇都不一样，
  git 里全是假 diff。`make_missile_bc_overlay.py` 已处理：`savefig(metadata=SAVE_META[ext])`
  （PDF `CreationDate/ModDate=None`、SVG `Date=None`、PNG `Software=None`）+ `normalize_svg_ids()` 顺序化 id。
  **验证**：连跑两次，PNG/PDF/SVG 三者 sha256 全一致；PNG 像素与改动前 **0 差异**（只少一个 Software 元数据）；
  SVG 仍是合法 XML、175 个内部引用 0 个解析不到。**注意**：id 正则要写成"字母 + ≥5 位十六进制"
  （`[A-Za-z]+[0-9a-f]{5,}`），只写 `m[0-9a-f]{6,}` 会漏掉 `p*` 裁剪路径和 `image*` 内嵌位图的 id

---

## 9. 会话记录（本阶段）

| 阶段 | 做了什么 | 结论/证据 |
| --- | --- | --- |
| 搭建 | 仿真器从零实现（标量+数组双路径、决策核心共用、测试与工作流） | 61 项自检全绿；默认工况 60.81 s |
| 参考图核对 | 从用户参考图像素解出 11 个弹点，与自算值比对 | 发现 9/11 对得上，MICA/R-77 系差得多 |
| 口径纠错 | 按用户指引从 `WT.xlsx` 表 `AAM (ARH)` 复核公式 | 表内公式复算与缓存值 32/34 一致；定位到 `massEnd1` 与 `caliber` 两个坑 |
| 找到源头 | 用户指出 `自动化分析` 文件夹里有生成参考图的原始工作流 | 权威公式 = `plot_version_compare.py::metrics()`；参考图 = **2.57 基线**值 |
| 版本确认 | 核对实机归档与 datamine | `warthunder.yup` 指向的 `aces.vromfs.bin` 与解包源同 length/mtime；实机 pkg = 2.58.0.36 |
| 统一口径 | 新增 `scripts/missile_metrics.py` + `build_missile_sources.py`，交叉图/工作流改为默认最新版 | 拟合 `BC=-3.942·ΔV+6752.4`（R²=0.391）；11 型全命中 |
| 清理 | 按用户要求移除参考图读点图层与 ΔΔV 列，文档同步 | 两张主图只剩最新版内容；61/61 仍通过 |
| **二阶段·改图** | 只保交叉图并美化：等时线 10 s→**1 s**；**删除线性拟合**（含 R²、`fit_main` 字段、`linear_fit()`）；轴范围/刻度改用 `自动化分析/references/charts.md` 规格 | 20 条等时线（54~73 s）全部自动标名；1824 工况全命中；61/61 仍通过 |
| **二阶段·版式迭代** | 三个渲染版本对比后才定稿：①色标+5 s 线名 → ②色标+贴边框 1 s 线名（x 轴标题压脚注、图例压 72/73 s 线名、70 s 线名丢失）→ ③图例移到坐标区上方、脚注下移、色标贴近、120C 加环 | 定稿图：`figures/fig_missile_bc_overlay_crossplot.png`（另存 pdf/svg） |
| **二阶段·启用 git** | `git init -b main` + 仓库级身份 `MK <MK@localhost>`；写 `.gitignore`（只忽略缓存/临时）与 `.gitattributes`（`* -text`，行尾原样存储）；初始提交 `11a5976` 收录启用前的全部状态（96 个文件） | `git status` 干净；`figures/`、`results/` 入库；`__pycache__`、`.tmp_test` 已忽略 |
| **二阶段·出图可复现** | matplotlib 默认把创建时间写进 PDF/SVG、SVG 还用内存地址当元素 id → 重跑必假 diff。改为 `savefig(metadata=…)` 关时间戳 + `normalize_svg_ids()` 顺序化 id | 连跑两次 PNG/PDF/SVG sha256 全一致；PNG 像素与改动前 0 差异 |
| **三阶段·升力可行性** | 只按 `E:/War Thunder/_recon/升力与诱导阻力_实现规格.md` 逐条对着实机数据验收（其余 `_recon` 文档不作为依据）；写探针 `scripts/probe_aero_upgrade.py` 量化三种阻力口径 | `f(M)`/`F(M)` 与文件 §7 自检表 10 点吻合到 4.8e-9；**发现最大偏差 = 缺 `f(M)`**；`CyMaxAoA=1.8` 与 `CxK=1.405` 均为旧版/串味，AIM-120 全系无该键（查 9 个 tag + 扫 676 个 blkx） |
| **三阶段·声速修正** | 从 `atmosphere.cpp/.h` 取到游戏精确模型 `T=T0·poly(TEMPERATURE_COEFFS)`、`a=20.1·√T`，替换原 ISA 实现；加对拍测试 | ISA 在 **15 km 差 −2.2%**（295.07 vs 288.69）；改后 `T(5 km)=255.58 K`、`a=321.34 m/s` 与规格文件 **完全一致**，参考实例 `D_base` 差 **0.00%**；自检 61 → **62/62** |
| **三阶段·第二信源** | 按用户给定的**证据规则**（信源交付的文件包为准、聊天转述冲突即转述错误）重读其 `FORMULAS-PLAIN.md`/`MISSILE-VARIABLES.md`/`response-time/README.md` | 阻力侧**逐条印证**（含结构体偏移、`sin²α`、`CxAoA=9`、`BC=betaEnergy` 与我们定义相同）；**推翻"由过载反解 α"**（α 是姿态状态量）；新增三项硬数据：**静态包线 `staticG=min(kappa·q,B)`**（我先前漏了 `B=51.3 g` 这道控制上限）、**过载建立时间 `t90,50`=65~146 ms（原生实测）**、以及我们**制导增益表用错型号**（MICA 无 `timeToHitToGain`、120C 无 `timeToGain`） |
| **三阶段·气动升级落地** | 新增 `src/missile_sim/aero.py`（f(M)/F(M) 双实现、升力配平、诱导阻力保能形式）；`AeroConfig` 三档；`_accel`/`_accel_arr` 两处接入 + 批量两条每工况数组随淘汰收缩；trace 加 `alpha_deg`；`--aero` 进 CLI/交叉图/工作流；`tests/test_aero.py` 28 项 | **92/92 通过**；`--aero legacy` 的 cases/isolines CSV 与 git 里旧产物**逐字节一致**；full 档基准 45.11 s / 672 m/s |
| **三阶段·原生对拍** | 装 `unicorn`+`pyelftools`，把信源文件包里的仿真器在本机跑起来（它执行游戏 2.59.0.28 原生代码），对同一场景逐距离对拍 | 15/30/50/70 km 原生 13.30/25.91/44.86/65.32 s；我们 full 档偏差 **+3.87/+0.63/+0.25/+0.72 s**（≥30 km ≤2.4%）；legacy 档偏差 +3.0/+6.9/+16.0/+27.3 s |
| **四阶段·标准弹落地** | 建 11 弹池 `results/missile_standards.json`（`build_standard_pool.py`）+ `standard.py` 解析层 + `StandardConfig`；默认 **PL-12**，`--standard` 可切；配置改名 `configs/baseline.json` | 池与权威 `missile_points.json` 的 ΔV/BC/干重/CxK/口径 **11/11 逐值一致**；`tests/test_standard.py` 26 项；**A1 逐字节回归**（`--standard 120C --burn instant --ve-equiv 2266.0` 复现升级前产物） |
| **四阶段·有限燃烧** | `burn.py`（质量/推力为 t 的纯函数，N 段）+ `_accel(h,v,gamma,t)` 与批量接入 + aero 质量比 μ + trace 加 `mass_kg/thrust_N` | 真空 ΔV 守恒 **+0.004~0.021%**；瞬时档**精确 0.0000**；`tests/test_burn.py` 25 项；自检 142/142 |
| **四阶段·Flash×Pro 复验** | 新增 `native_speed_check.py`、`native_compare.py --standard`；对同一场景并排速度/质量/推力历程 | **速度偏差从 +801 m/s 降到 ≤11.8 m/s、质量与推力时序逐点吻合**；A2 通过 |
| **四阶段·高抛判据** | `ballistics.loft_exit_game`：**退出 ⇔ \|λ̇\|≥loftTargetOmegaMax 或 λ≤loftTargetElevation**（逐弹从 blk 填）；`sim.loft_rule` game/heuristic；`loft_min_time` 2.0→0.5 s | <40 km 误差从 **−57% 收到 −1.7%**；全包线 **9/9 可对拍、中位 0.65%、最大 2.57%、绝对误差 ≤0.23 s** |
| **五阶段·Flash 后端落地** | `backend` 成一等字段（`--backend pro` 明确报错退出）；新增 `provenance.py`，**workflow/sweep/交叉图三处产物共用出处块**；工作流输入接 `standard/burn/loft_rule`、逐弹用各自标准弹、主图拟合面板换成**出处面板**、轴规格与出图元数据抽到 `plot.py` 与交叉图共用 | 工作流图**字节可复现**；`tests/test_workflow.py` 14 项；自检 **156/156** |
| **五阶段·标签与规格** | 逐项对照 `charts.md` 后确认交叉图本已合规；把标签偏移/样式抽成共用常量（`MISSILE_LBL_OFFSETS`/`LBL_COLOR`/`LBL_FONTSIZE`/`LBL_LEADER`），**工作流主图补上 11 型标签**、图例移出轴外、交叉图标签全部 bold | 两张图标签位置一致；产物全部重出 |
| **六阶段·信源第三份文档对表** | 收到 `D:\Download\CALCULATION-FORMULAS.md`（实为包内 `FORMULAS-PLAIN.md` 的改写版）；写三个原生探针把高抛项**实验定论**，并用已有 50 km 原生轨迹反解高抛激活态 | ✅ 阻力/大气/发动机/PID/限幅**逐条已一致**；❗**高抛项真值 = `k·(θ_loft−θ_body)`、无速度因子、目标角是弹体 θ** ⇒ 本项目 `k·(θ_loft−γ)·v` **两处都错**；❗`CyMaxAoA` 有 4 型覆盖（R-77 系 1.3、MICA 1.35）；包已迁至 `E:\WT\wt-missile-backend-runtime-1.0.1`；原生 CLI 50 km 基准实测 **62.9 s** |
| **七阶段·Pro 后端落地** | `pro.py`（运行时/ELF 校验/进程池/缓存/解析缩放/**blk 注入**）+ `flight.py`（后端无关入口）+ `sweep.run_sweep_pro`（装进现有 `BatchResult`）+ CLI/config 默认改 pro + workflow 7 处改 `TrajectoryRunner`；新增 `scripts/pro_missiles.py` | **11/11 命中、11 次原生运行 17.4 s**；Derby/R-Darter 靠注入跑通（`resource="INJECTED …"`）；一次性 15×24=360 工况 **490.9 s**、命中 360/360、等时线 15 层；踩坑：进度回调签名、缓存只在正常路径保存、逐弹没重解析标准弹 |
| **八阶段·三段式重构** | 拆 `model/` 三层（io/native/runner/record/cache/grid）+ `scanner.py` + `crossplot.py` + `scripts/pipeline.py` 四段 CLI；`pro.py` 变兼容 shim；`CALC_VERSION` 升到 4 | 新增 `test_model_io/record/cache`（65 项）+ `test_crossplot`（25 项）；既有 187 项无回归；修掉两个真 bug（`to_record` 丢轨迹、线名少一个）与三处版式问题；绘图三格式**字节可复现** |

---

## 10. 下一阶段（用户 2026-09-25 定调：**美化 / 新功能 / Pro**）

当前状态一句话：**Flash 后端已跑通并与 Pro 对齐到中位 0.65%，一切产物自描述、可复现、自检 156/156。**

### 10.1 美化（低风险，可随时做）

1. **点标签带 t_hit**（二阶段遗留）：现在标签只有型号名；可在型号后附本次弹道下的命中时间。
2. **等时线加白描边 + "命中时间递减方向"提示箭头**（二阶段遗留，`charts.md` 未规定，属自选）。
3. **`fig_sweep_isotime_baseline.png` 与交叉图统一视觉**：它现在是转置版（BC 横轴）、无弹标签、
   色标与网格风格也不同——要么并入交叉图规格，要么只保留为"扫描诊断图"并在 README 标注。
4. **工作流 detail 图**（t_hit–BC / 初距 / 弹道剖面）与主图统一字体、网格、脚注位置。

### 10.2 新功能与 Flash 修正（**注意：Flash 已于 §10.3 让位给 Pro**）

> ⚠ 本节 1~4 项是针对 **Flash 快模型**的修正；Pro 后端落地后，**Flash 只剩"无包/探索"用途**，
> 所以这些修正是**可选**的（要做就得先想清楚还要不要维护 Flash）。条目已按 `AERO_PLAN.md` §19 修正过口径：
> 原文的"隐式解"修法建立在错前提上，**不要按它实施**。

1. **高抛项改写**（`AERO_PLAN.md` §19.1，残差的**唯一**已知主因）：真值是
   `a_loft = k_loft·(θ_loft − θ_body)`，**没有速度因子**，目标角是**弹体俯仰 θ** 而不是航迹角 γ。
   实测证据：`req_y = mult×Δθ`（20×20=400），对速度 200~800 m/s 完全无关；弹体 20°/速度 0° 时
   高抛项 = 0，弹体 0°/速度 20° 时 = 400。
   ⇒ 需要给 Flash 引入**独立的姿态角 θ 状态**（现在是"指令→法向加速度"直接映射，没有 θ）。
   `decide.guidance_command_scalar/array` 现有的 `cmd = k_loft·(θ_loft − γ)·v` **两处都要改**。
   （原 §17.5 的 `a = k_loft·Δθ·v / (1 + k_loft·(k_alpha·μ/q)·v)` 作废；朴素改法的不稳定结论仍有效。）
2. **`CyMaxAoA` 逐弹入池**（§19.3）：R-77 / R-77-1 / RVV-AE = **1.3**、MICA EM = **1.35**，其余默认 1.0。
   我们现在全按 1.0 ⇒ 两处受影响（诱导阻力 `Da`、升力峰值限幅 `sin_alpha_peak`），
   R-77/MICA 的可用迎角被砍 ~25%/20%。
3. **过载建立时间（P3）**：原生实测 `t90,50`≈81 ms，一阶滞后 τ≈35 ms。与 1 同属"指令→实际"动力学，
   建议一起做（引入 θ 状态时天然可以带上）。
4. **动态过载上限**：结论修正为 **B 平台基本不生效**（PL-12 `q_break`=290.85 kPa，正常交战动压低于此），
   真正卡住指令的是 `reqAccelMax`（PL-12 = 38 g = 372.8 m/s²，原生已实测）。见 §19.4.1。
5. **目标机动**：给目标加平飞外机动（蛇形/俯冲/拉起），看等时线形状怎么变——这是唯一的"新维度"。
6. **其它工况的交叉图**：`--range 30000`、`--vt -450`、`--target-alt 8000` 各出一张（脚本已支持，只差产物与文档）。
7. **制导增益表**：现在按"有 `timeToHitToGain` 就用它，否则 `timeToGain`"，等价于游戏的 min 规则
   （断点不重叠，见 `tests/test_standard.py`）；若将来出现重叠型号需补 min。

### 10.3 Pro 后端（**已完成落地**，详见 `AERO_PLAN.md` §21）

**用户定案（2026-09-25）**：弃用 Flash、完全移植到 Pro；扫描 ΔV 与 BC 时默认基准弹 PL-12、
可外部在 11 弹池里选；仍改 CxK 与推力乘数（后者改比冲）。并明确 **ΔV 是真空增速**，
推力倍率用**纯理论解析式**、不考虑损失率。

已落地：

| 件 | 状态 |
| --- | --- |
| `pro.py`（运行时/ELF 校验/进程池/缓存/解析缩放/**blk 注入**） | ✅ |
| `flight.py`（后端无关的"跑一条弹道"统一入口） | ✅ |
| `sweep.py::run_sweep_pro`（原生结果装进现有 `BatchResult`，等时线/CSV/出图原样复用） | ✅ |
| `backend` 默认改 **`pro`**；CLI `--jobs/--pro-dt/--pro-duration/--pro-observation/--no-pro-cache` | ✅ |
| `workflow.py` 去掉 Pro 拦截，7 处 `simulate_one` 换成 `TrajectoryRunner` | ✅ |
| `scripts/pro_missiles.py` → `results/pro_missiles_50km.json` | ✅ **11/11 命中，17.4 s** |
| 一次性等时线场 15×24=360 工况 | ✅ **490.9 s，360/360 命中，已落 `results/pro_cache.json`** |
| `tests/test_pro.py` | ✅ 30 项（含注入、回调签名、缓存异常路径） |

关键数字（50 km 迎头 / 10 km / 300 对 −300）：MICA **41.163 s** 最快、AAM-4 **46.772 s** 最慢；
末速 557（R-77）~786（120C）m/s；Derby/R-Darter 走注入（`resource="INJECTED …"`）。

**成本实测**：单工况 ≈ 1.4 s/工况（8 并发、dt=0.01）⇒ 360 工况 8.2 min；缓存命中后秒级。

**注意 Flash 的定位变了**：`--backend flash` 仍可用（无包环境/快速探索），但**不再是正式口径**。
§10.2 那几条 Flash 修正现在是可选工作。

**剩余（还没做）**：

1. **对称性检查**：在 52 km 处用 `vm0=-300` 起算，应等价于 50 km 基准（误差应 ~1e-3 s 量级）。
2. **多工况 sweep**：`--range` / `--vt` / `--target-alt` 各出一张 Pro 版交叉图。
3. `--observation locked` 对照（现在默认 ideal，locked 会引入原生滤波/多径）。
4. 11 弹的 `observation.locked` 与 `ideal` 差异量化。

---

## 10.4 三段式架构（**已完成**，详见 `AERO_PLAN.md` §22）

**用户定案（2026-09-25）**：把工作流分成三部分——① 模型（三层：输入/计算/输出）
② ΔV/BC 扫描器 ③ 绘图（`aam_fit` 版式 + 等时线）。落地后 **Pro 是正式口径**，Flash 只作近似档。

| 段 | 模块 | 已落地 |
| --- | --- | --- |
| ① 第一层 输入层 | `model/io.py` | blk 统计（复用权威 `metrics()`）、**两个参考面积分离**、逐级齐奥尔科夫斯基、解析乘数、`build_case` |
| ① 第二层 计算层 | `model/native.py` + `model/runner.py` | `NativeCase → NativeResult`；进程池 + 缓存 + **blk 注入** |
| ① 第三层 输出层 | `model/record.py` + `model/cache.py` | `CaseRecord` 稳定契约、表读写、`manifest`/`check_staleness`、`ProCache` |
| ② 扫描器 | `scanner.py` | `ScanSpec`/`Grid`/`Scanner`；run 级指纹 + 时效；**周期性落盘** |
| ③ 绘图 | `crossplot.py` | `make_figure`/`plot_points`/`plot_isotime`/`plot_crossplot`；三格式字节可复现 |
| CLI | `scripts/pipeline.py` | `stat` / `model` / `scan` / `plot` 四段可分别单跑 |

**关键数字**

* `CALC_VERSION = 5`（唯一失效开关）。4→5：轨迹默认不入缓存（见下产物体积一条）。
* 正式全网格（32×57 = **1824 工况**，8 并发）：**2620.8 s（≈44 min）**、**命中 1824/1824**、
  `t_hit` **38.56~52.63 s**；产物 `results/runs/full_pro/{manifest,cases.json,cases.csv}`。
* 缓存 1824 条 ≈ **1.06 MB**（cases.json 2.5 MB）→ 之后任何重跑/调图都是**秒级**。
* 主图：`figures/fig_missile_bc_overlay_crossplot.{png,pdf,svg}`（等时线 1 s，39~53 s 共 15 层）。

**本轮修掉的真 bug**（都补了回归测试）

1. `to_record(..., samples=None)` 写成 `downsample(samples or [])` ⇒ `None or []` 把 187 点原生轨迹**静默丢光**。
2. 等时线**线名少一个**：只擦到网格角点、形不成线段的层被 `zip` 静默截断。
3. **缓存只在 `close()` 落盘** ⇒ 小时级扫描中途中断就全丢；改为每 `flush_every`（默认 200）条落一次。
4. 题头三件套（标题/副标题/图例）抢同一块区域 ⇒ 改 figure 坐标手工排布。
5. 脚注压 x 轴标题 ⇒ 起点改由**实测的标题包围盒**反推（不再猜坐标）。

**下一步（未做）**

1. `pipeline.py plot --with-fit` 出"aam_fit 原版 + 等时线"双风格对照（可选）。
2. 多工况：`scan --range/--vt/--target-alt` 各出一张（每条只需再跑一次网格，缓存分层存放）。
3. HTTP 服务（P5，可选）：本机无 fastapi/uvicorn，需用标准库实现；包内 REST 依赖 `fcntl`，Windows 不可用。
4. 高抛项按 §19.1 改写（**仅 Flash 档**；Pro 已是游戏原生，无需修）。
---

## 10.6 模型接入 API 化（**已完成**，分支 `pro-api`）

> 用户 2026-09-25 定案：**取消"按 `CALCULATION-FORMULAS.md` 重建 Flash"这一路**，
> 先只做**模型接入的结构化 API 化**——让 Pro、Flash、以及将来从开源拿到的第三方模型
> 都能像换零件一样接进来，并保持版本管理闭环。**做完即收尾。**

### 为什么先做 API 化

原来的"引擎"是隐式的，三处耦合已经会咬人：

| # | 缺口 | 证据 | 后果 |
| --- | --- | --- | --- |
| 1 | **输入映射重复** | `native.py::simulate_native._apply` 与 `flash.py::flash_case_from` 各算一遍 `dv_blk`/`bc_blk`/乘数 | 两处口径一分叉就是静默数值错误（踩过 `dv_blk=536.9`） |
| 2 | **引擎协议隐式** | 无 Protocol，靠 `ProRunner`/`FlashRunner` 同名方法鸭子类型 | 新模型要么猜方法名，要么改上层 |
| 3 | **版本戳散落** | 两个整数 + `NATIVE_PROFILES` + 模块级全局 `chdir` | 新模型的身份没有落点 |
| 4 | **无自检入口** | 没有"接入即验" | 坏模型要等 44 min 扫完才暴露 |

### 落地内容

| 件 | 落点 | 说明 |
| --- | --- | --- |
| 契约 | `model/spec.py` | `ModelSpec`/`Capability`/`Engine`(Protocol)/`EngineEnv`/`EngineInputs`/`EngineResult`(=带 `EngineStamp` 的 `NativeResult`)/`SelfTestReport` |
| 输入映射唯一落点 | `model/io.py::build_inputs` / `inputs_from_case` | 乘数只在这里算；引擎**不得**重算（`EngineInputs.check()` 会查自洽） |
| 字段翻译唯一落点 | `model/io.py::normalize_blk_profile` | 完整 blkx `rocket` 块 → 结构化参数块（含 PID 两种形态、力臂、惯量缩放、增益表、高抛表） |
| 注册表 | `model/registry.py` | 内置 `pro`/`flash` + `$WT_MODELS_PATH` 第三方发现/加载；`models_table()` → `results/models.json` |
| 显式运行环境 | `model/env.py::build_env` | 替掉隐式 `pkg`/`chdir`/步长：按 `requirements` 只填该模型真要的东西 |
| 引擎实现 | `native.ProEngine`、`flash.FlashEngine` | 同一协议；`ProEngine.selftest` 查包/ELF/unicorn/映射自洽/能力声明 |
| 通用执行器 | `model/runner.py::EngineRunner` | **任意模型**都能跑：进程池 + 缓存 + 进度；`ProRunner` 保留（`bare=True` = 不要引擎，走模块级 `simulate_native`，是单测打桩点） |
| 按模型分派 | `scanner.py` | `ScanSpec.model`（`backend` 为别名）；`_get_runner` 由注册表驱动，删掉 `make_runner(**kw)` 猜测 |
| 版本分区 | `model/cache.py` | `schema` 取 `ModelSpec.calc_version`，路径按模型分（`pro`/`flash` 路径不变，第三方落 `results/cache/<名>.json`） |
| CLI | `scripts/pipeline.py` | 新增 `models [--check] [--write]`；`model`/`scan` 支持 `--model`（`--backend` 仍可用） |
| 接入规范 | **`docs/MODEL-API.md`**（新） | 第三方模型怎么写、注册、启用、版本管理、边界 |

### 可替换性的可执行证明

`tests/test_model_api.py`（33 项）里放了一个**最小第三方模型**（20 行、恒返回固定结果）：
写进临时目录 → 挂 `WT_MODELS_PATH` → `pipeline`/`Scanner` 全链路跑通，
产出与 Pro/Flash **同形**的 `CaseRecord`，`schema` 用该模型自己的 `calc_version`，
manifest 的 `calculator` 记它的注册名。这条用例就是"开源拿到新模型能统一接入"的证明。

### 硬验收（全部实测通过）

| 验收项 | 结果 |
| --- | --- |
| `results/pro_cache.json` 逐字节不变 | ✅ SHA-256 `7D6ED046…2741E` 前后一致 |
| 1824 条缓存键逐个相等 | ✅ 用 `full_pro/cases.json` 的 `case_id` 逐条重算，**0 不一致** |
| 键公式等价 | ✅ 1728 组参数化对比（弹型×ΔV×BC×距离×高度×步长×观测×引信×近炸）全等 |
| 全网格 Pro 扫描 | ✅ **1824/1824 命中，0.3 s，0 次原生运行** |
| `calculator_digest` | ✅ 仍为 `8779f3bc55d3d75c`（键集合冻结） |
| `inputs_digest` | ✅ 仍为 `05dba6a95908a88f` |
| `pipeline.py models --check` | ✅ pro/flash 双双通过（含 ELF SHA-256 校验、输入映射自洽、能力声明一致） |
| 单工况端到端 | ✅ PL-12 50 km：`t_hit=45.0985`、`max_alt=12723.2`、`v_impact=617.2`、903 采样点（与 `AERO_PLAN §21.4` 一致） |
| 全量自检 | ✅ 325 项（291 + 新增 33 + 1） |

### 分支现状（`main` 全程未动）

| 分支 | HEAD | 内容 |
| --- | --- | --- |
| `main` | `cf25120` | 基准（Pro 版三段式） |
| **`pro-api`** | 本阶段提交 | **本次交付**：模型接入 API 化 |
| `flash-backend` | `46aa393` | Flash 双后端闭环的进度锚点（**文档**），未含本次 API 化 |
| `flash-next` | `46aa393` | 与 `flash-backend` 同点（曾计划用作重建分支，已废弃） |
| `tmp-verify-0` | `608a635` | 临时快照（当时工作树，内容已并入 `pro-api`），**可删** |

### 后续（可选，不阻塞）

1. **Flash 内核重建**：按 `D:\Download\CALCULATION-FORMULAS.md`（唯一权威依据）替换
   `FlashEngine` 的内核为纵向平面 θ+α+PID 闭环——**对外形状不用改**（这正是 API 化的意义）。
   已知四处结构性错误（`a_loft = k·(θ_loft−γ)·v`、无姿态状态、无建立时间、`G` 用 min 而非乘积）
   见 `AERO_PLAN.md §19.1` 与 §17.5。
2. 第三方模型接进来后，用 `flash_vs_pro_report` 式的误差报告判定它值不值得当默认模型。
3. `lib` 侧的 `EngineRunner` 已支持任意模型多进程；给 Pro 的 `ProEngine` 也补上
   `simulate_many`（若将来原生包支持批处理）。
## 10.11 求解器整体替换为 wt-missile 两档（分支 `new`，2026-09-26）

用户定案：**用入库的第三方求解器整体替换两档**，档位更名为 `standard`（纯 Python 逐物理步，
正式口径）与 `fast`（同一物理的 C 编译内核；缺编译器时求自身回退 `python-legacy`）。

* 求解器：`vendor/wt-missile/`（2.59.0.28 原生 6DOF 的纯 Python 复刻，`MODEL = python-game-6dof-v1`；
  源码 SHA-256 `1BFA0FA2...`；**不执行 ELF**）。现有信源包的 `.28` 资源只有 11 份与本包 manifest
  对得上，所以必须整包入库。
* 新引擎：`src/missile_sim/model/wtgame.py`。两档只在算术路径不同；ΔV/BC 乘数仍然**只由
  `io.build_inputs` 算**，引擎 monkeypatch `wt_missile.load_profile` 只负责施加。
* 旧 `pro` / `flash` 保留为 **legacy 入口**（引擎、版本号、缓存一律不动），但不再注册为档位：
  `--backend`、`results/models.json`、`list_models()` 都只看 `standard` / `fast`。
* 已实测：金标（120D / 60 km / 双方 6000 m / 300 对 250，ideal 观测）`max_alt = 10629.9961 m`，
  与原生金标 10630.40 差 **-0.40 m（0.0038%）**；两档差 0.000000 m；PL-12 基准 50 km 的
  `t_hit` 差 0.029%（旧 Flash 对 Pro 是 0.65%，好 20 倍）。本机无 C 编译器，fast 档实测走回退。
* 顺带修掉一个既有 bug：`runner._worker_run_engine` 还原跨进程输入时没把嵌套参数块转回 dataclass，
  `EngineRunner` 一旦走多进程就抛 `'dict' object has no attribute 'dry'`（替换前从未跑到）。

⚠ **完整交接（卡点、剩余待办、行尾纪律、不可动摇的前提）见 `docs/NEW-SOLVER-HANDOFF.md`**；
本节只作索引，细节不在处重复。

## 10.12 两档求解器接线收尾（分支 `new`，2026-09-27）

§10.11 之后的提交把"替换"从"能跑"推到"**所有入口都走新档位**"，全量自检 332 → 346 全绿。

* 卡点收尾：`record.py` 的内置模型白名单曾硬编码 `("pro","flash")`（改名当天把 18 条记录判成
  "未知模型"），改为惰性查注册表；`make_manifest` / `check_staleness` 的 `backend` 默认值也是
  漏改的 `"pro"` —— 那才是 3 条 staleness 假阳性的真正根因。
* `cli` 单工况原先写死旧 Flash 引擎（`--backend` 对它**完全无效**，选 pro 也照样出 Flash 的数），
  改走 `TrajectoryRunner`；新档位没有 `sim.Trace`，新增 `flight.SampleTrace` +
  `trace_from_samples` 把两条路统一成弹道图认的形状；没产出的诊断量（`n_eff` / 终端航向误差 /
  高抛退出时刻）如实报"该档位不提供"，**不打 nan**（nan 会被读成"算出来是 nan"）。
* `--mass` **停用**：干重覆盖只在旧 Flash 里成立，而新两档的干重取自权威 blkx、同时是
  `ΔV_blk`/`BC_blk` 的锚。改造前 `--backend pro --mass …` 是**悄悄吃掉它还照常出数**。
* 修掉三个改造前就有的潜伏 bug：
  1. **缓存读写不对称** —— `save_trajectory` 不进 `cache_key()`，写侧只在无轨迹时落盘、读侧却照查
     ⇒ "先扫描（已缓存、无轨迹）→ 再要轨迹"拿到 `samples == []` 的旧记录，**弹道图静默消失且
     不报错**。11 处读写统一改走 `cache.cacheable()`。
  2. `scripts/pipeline.py model` 一进来就 `AttributeError`（读 `args.backend`，而 argparse 里是
     `dest="model"`），并且 `--model standard` 会**静默跑成旧 Flash 引擎**、产物却写着 standard。
  3. `cli.py` 的 `except ConfigError` 用了**没导入**的名字。
* `crossplot.provenance_lines` 两处修正：档位名取 `calculator.model`（不再按 `elf_sha256` 有无
  反推成 pro/flash）；**步长按档位选** —— 新两档报的是引擎外层步长 `pro.dt`，而 `prov["dt"]`
  是旧 Flash 的 `sim.dt`，两档根本不用它，以前在图上报的是**假步长**。
* 新增 `tests/test_wtgame.py`（14 条）：vendor 哈希/清单/预设计数、输入映射对上仓库权威值、
  **乘数确实施加到 `load_profile` 且不污染后续加载**、金标对拍、两档一致性、能力对声明、
  12 个型号被明确拒绝（不做近似替代）、失败路径。
* 文档订正三处与实测不符的记录：`results/pro_cache.json` 实为 **1844** 条（1824 是 32×57 的网格
  点数，两个数一直被混用）；`cache_key` 冻结测试在 `tests/test_model_api.py:72`（不在
  `test_model_io.py`）；`results/flash_cache.json` **既不存在也没入库**，"flash 缓存不能动"是空约束。
* `tests/run_tests.py` 的 fixture 现在**兑现 `scope`** —— 此前 `scope="module"` 被忽略，workflow 的
  `run_small`（一次完整工作流）被每个用到它的用例各跑一遍。

⚠ 与 §10.11 一样，**完整交接见 `docs/NEW-SOLVER-HANDOFF.md`**：§3.5/§3.6 是本轮技术细节，
§7 是不可动摇的前提（含行尾清单与 1844 条的订正），§9 指向下一步的岔路口。
另见 **`docs/SHELL-REBUILD-FEASIBILITY.md`**：独立评估"以 wt-missile 为核心、抛开现有外壳重建"
的可行性（结论：可行，属中等规模重写 + 大扫除；`src/missile_sim` 9506 行里 ≈30% 是两代旧引擎
留下的死代码；判据是"旧 Pro/Flash 口径还要不要"）。

## 10.13 修好 `fast` 档：17.5~23× 加速（2026-09-27）

`fast` 档此前一直报 `python-legacy`，原因不是求解器有问题，而是**编译器不在 PATH 上**。
本机其实装了 Visual Studio 2022 Community（MSVC 19.44），只是 MSVC 需要开发者环境来设
`INCLUDE`/`LIB`，普通终端里 `shutil.which("cl")` 找不到。

求解器的编译是**一次性**的：内核缓存在 `%LOCALAPPDATA%\wt-missile\compiled-fast\<hash>.dll`
（带 `.sha256` 校验），命中缓存时**根本不再找编译器**。所以在 VS 开发者环境里成功编译一次之后，
任何普通终端都走 `compiled-c`：

```bat
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=amd64 -no_logo
set PYTHONUTF8=1 & set PYTHONPATH=src
python scripts\pipeline.py models --check      :: fast 档那行应从 python-legacy 变 compiled-c
```

实测（`cache=None` 的执行器，预热后取最快一次）：

| 工况 | standard | fast | 加速比 |
| --- | ---: | ---: | ---: |
| 金标 120D / 60 km / ideal | 1765 ms | **77 ms** | **23.0×** |
| PL-12 / 50 km / 300 对 −300 | 1243 ms | **71 ms** | **17.5×** |
| 1824 格点网格外推（jobs=8） | ≈4.7 min | **≈0.27 min** | 17× |

两档结果**逐位一致**：`Δmax_alt = 0.000e+00 m`、`Δt_hit = 0`、`Δv_impact = 1.03e-05 m/s`（末位）。
金标 `max_alt = 10629.99609375 m` 两档相同，对原生 10630.40 仍是 **−0.4039 m（0.0038%）**。

顺带修的两处：

* `wtgame.stamp()` 在没给 `summary` 时曾对**所有**档位报 `unreported`（上一轮的"不许猜"修过头了）。
  `standard` 档的 `fastmode` 恒为 `False`，后端是 `python-standard` —— 这是**构造事实**不是猜测，
  所以标准档不跑也能如实报；只有 `fast` 档在没跑过时才是 `unreported`。
* ⚠ **`.bat` 必须是纯 ASCII**：`cmd.exe` 按 OEM 代码页（本机 GBK）读批处理，中文注释会当场
  把解析搞坏（这次踩过，报了一串 `'xxx' is not recognized`）。

⚠ 完整交接与"怎么重编内核/什么时候会失效"见 `docs/NEW-SOLVER-HANDOFF.md` §4.1。

## 10.14 restart 分支：以 wt-missile 为核心重建外壳（2026-09-27）

用户定案：旧外壳不再修补，**从零重建**（"原本的外壳被改乱了"）。`restart` 从 `new` 的
`76c4671` 出，工作树里那批未提交改动**全部丢弃**。挑 `new` 而不是 `main` 出，是因为
`new` 上有三件不可重建的资产：`vendor/wt-missile/` 整包、权威公式 `scripts/missile_metrics.py`、
以及 `docs/SHELL-REBUILD-FEASIBILITY.md` 评估。

**规划与拍板全文见 `docs/RESTART-PLAN.md`**；**内核输入/输出契约见 `docs/SOLVER-API.md`**。

### 删了什么（提交 `abe3e5d`）

* `src/missile_sim/` **31 个旧模块全删**（两代旧引擎 `sim`/`aero`/`ballistics`/`burn`/`decide`/
  `atmosphere`/`pro`/`flash`/`native` 约 2800 行，加上外壳 10 个）；
* `scripts/` **22 个**：16 个标定/对拍脚本 + `pipeline`/`workflow`/`workflow_web`/
  `make_missile_bc_overlay` + `build_standard_pool`/`missile_sources`；
* `tests/` **16 个**用例文件（合计 8844 行 + src 侧）。
* 保留：13 个 `E:\WT` 数据出处链脚本（`missile_metrics.py` 是保留脚本的依赖）、
  tests 三件套、`vendor/`（只读）、旧 `figures/`/`results/` 产物（旧 Pro/Flash 口径，作历史）。

### 建了什么

10 个新模块：`spec`（契约）/ `solver`（**唯一** vendor 接触面）/ `mapping`（ΔV·BC ↔ 乘数）/
`pool`（11 弹池）/ `engine`（进程池 + 缓存）/ `grid`（网格 + 等时线）/ `figures`（**唯一**出图）/
`record`（产物）/ `workflow`（端到端）/ `cli`。清单与写 scope 见 `docs/RESTART-PLAN.md` §3。

**关键简化**：ΔV/BC **不再读 `results/missile_standards.json` 之类的 JSON 池**，改为
`mapping.blk_metrics()` **从 vendor 的 blk 现算**。实测 11 型与既有权威表**逐值一致**
（820.47/3609.0 … 1099.53/2705.6）—— 散点与求解器物理**同源**，不可能口径分叉。

**惰性旋钮不再存在**：旧外壳的 `--aero`/`--burn`/`--loft`/`--loft-rule` 对内核是惰性的却照常
打印；新外壳**不提供**它们 —— 少一个参数，少一次"以为自己改了物理"的误读。

### 已实测（可作验收基线）

* 默认工况（PL-12 / 50 km 水平 / 10 km 同高 / 载机 300 m/s 航向 0° / 敌机 300 m/s 航向 180°）
  `t_hit = 45.1861 s`、`max_alt = 12725.10 m` —— 与 `docs/NEW-SOLVER-HANDOFF.md` §4 记录一致。
* 两档（`standard` / `fast`）同工况**结果相同**，`backend` 分别 `python-standard` / `compiled-c`。
* 全网格 32×51 = **1632 工况 / 23.5 s**（fast，jobs=8），命中 1632/1632，等时线 13 层（39~51 s）。
* PNG/PDF/SVG **三格式连跑两次 sha256 全一致**（`SAVE_META` 关时间戳 + `normalize_svg_ids`）。

### 3D 扩位（用户定案：载机与敌机都给航向 + 俯仰）

`Scene.range_m` 语义改为**水平距离**（同高时与斜距相等，所以默认同高工况不受影响；斜距由
`range_slant_m` 现算）。新增 `target_bearing_deg` / `launch_heading_deg` / `launch_pitch_deg` /
`target_speed_ms` / `target_heading_deg` / `target_pitch_deg`，去掉带符号的 `vt`。
`CACHE_SCHEMA` 升到 **3**（语义变了就整库作废，不混口径）。

实测 3D 工况全部跑通：目标侧方 45° → 68.31 s；目标爬升 20° → 45.29 s；载机爬升 15° + 敌机
俯冲 10° → 45.89 s；高度差 3 km + 方位 30° → 50.96 s；水平 40 km（斜距 41.23 km）→ 42.62 s。

### 内核能力边界（实测，不是转述）

* **完整 3D ✅**：位置与速度都是 3 分量，输出 65 列含 `target_x/y/z_m`、`target_vx/vy/vz_m_s`、
  `target_accel_x/y/z_m_s2`。
* **实时敌机状态（闭环）❌ 没有入口**：只吃**预先给定**的完整目标时域。UI 上的"实时" =
  改一下就重算。
* `turn_rate_rad_s` / `maneuvers` / `samples` **三选一且互斥**，混用直接报错；
  `samples` 必须**从 t=0 起覆盖到 `duration_s` 末尾**（`no extrapolation`）。
* **本轮据此跳过自定义敌机轨迹**，只做带航向的直飞。

### ⚠ 并发写警告（真实踩过）

开工期间**有另一个会话在同一工作树**推进（路线是"渐进重构 + 不变量安全网"，与本分支的
"从零重建"互斥）。它的两份产物已备份为 `docs/_wip_PIPELINE-MAP.old.md` /
`scripts/_wip_e2e_check.old.py`，待处置。**同一工作树同一时刻只能有一个写入者** ——
派子代理时必须按 `docs/RESTART-PLAN.md` §5 的写 scope 严格隔离。
## 10.15 三块并行交付 + 文档换代 + 旧产物清理（2026-09-27）

§10.14 的收尾阶段。三块并行（A1 输入契约 / A2 WebUI / B 输出侧），Lead 独占其余模块、文档与提交。

### 已交付

| 块 | 文件 | 状态 |
| --- | --- | --- |
| A1 | `targets.py`（504 行）+ `tests/test_targets.py`（52 用例） | complete |
| A2 | `webui.py`（约 63 KB）+ `configs/web_default.json` + `tests/test_webui.py` | complete |
| B | `report.py`（277 行）+ `tests/test_report.py`（12 用例）+ `figures.py` 文案改造 | complete |
| Lead | 4 个用例文件（59 用例）、`AGENTS.md` 15 处修订、`README.md` 全文重写 | — |

**全量 `python tests\run_tests.py` → 129/129 PASS、exit 0、15.3 s。**

### 已验证（可复现的硬证据）

* 金标工况（`Scene()` + `cn_pl12`）：`t_hit = 45.1861 s`、`max_alt = 12725.1 m`、
  `event = proximity_fuse`、`backend = compiled-c`；`standard` 档同值（两档一致）。
* 11 型 ΔV/BC 与权威表**逐值一致**（相对差 < 1e-4）；`test_pool_mapping` 把这张表钉成黄金值。
* 6 个预置想定真跑全命中：45.1861 / 29.0827 / 50.4061 / 42.6405 / 35.7659 / 41.7199 s。
* 出图**字节可复现**：三格式连跑两次 sha256 一致（`test_figures_repro` 自动化守着）。
* 未命中渲染为空串 / `—`，绝不写 0 —— 否则会被读成"0 秒命中"。

### 踩到的坑（都值得记）

1. **测试运行器 collect 期崩溃**（最隐蔽的一个）：`tests/run_tests.py::_load_module` 用
   `spec_from_file_location` 加载模块却**不注册进 `sys.modules`**，而 Python 3.14 的 `dataclasses`
   解析 `@dataclass` 时会 `sys.modules.get(cls.__module__).__dict__` 回查 —— 于是任何在**模块级**
   定义 dataclass 的测试文件都会炸掉**整个**测试跑，报错还指向一个语法完全正常的 `@dataclass` 行。
   已修（先注册再 `exec_module`，失败时摘掉半成品）。连带结论：`-k` 是 collect **之后**才过滤的，
   所以别人的 import 错误会伪装成"你的测试坏了"。
2. **`solver.supported()` 返回的是拒绝原因**（可算时是 `None`），不是布尔值 ——
   写成 `if not supported(x)` 会得出完全相反的结论。`pool.py` 的 11 型全部返回 `None`。
3. **测试运行器的 `approx()` 不支持列表**：`pytest.approx([1,2,3])` 在 shim 里退化成精确比较，
   浮点向量必须逐元素断言。
4. **`arange_inclusive` 会补一个贴边界的端点**：网格最后一个 ΔV 是轴的 hi（如 1116.277）
   而不是步长格点（1110）。`test_grid_axis` 已把这个行为钉死，免得以后被当成 bug"修掉"。
5. **`adaptive_axis` 把轴范围归整到 2 位小数**，所以 `MIN_PAD=12` 实测是 11.99975 ——
   断言要留 0.01 容差。
6. **`PlaneRequest` 的字段漏了类型注解**会让 `dataclasses.fields()` 直接忽略它，`replace()`
   静默丢弃 CLI 值（早前 `--missiles` 就是这么失效的）。已在 `workflow.py` 写入警告注解。
7. **写补丁脚本时中文里的引号要用全角**：ASCII `"` 夹在中文中间会提前闭合 Python 字符串，
   而且报错行号指向**下一行**，很难一眼看出。
8. **默认档位刻意分层**：命令行 / WebUI / `workflow` / `report` 默认 `fast`，
   而 `solver.run()` / `engine.Engine` 默认 `standard`（底层 API 不该默认依赖 C 编译器）。
   两处不一致不是笔误，已写进 `README.md` §4。

### 清理（本阶段删除）

`docs/PIPELINE-MAP.md`、`docs/_wip_PIPELINE-MAP.old.md`、`scripts/e2e_check.py`、
`scripts/_wip_e2e_check.old.py`（四者都画/查已删的 `src/missile_sim/config.py` 那条流水线）、
`docs/MODEL-API.md`（描述已删的 `model/` 包）、`AERO_PLAN.md`（已删的 flash 气动方案）、
`configs/{baseline,standard_120c5,workflow_example}.json`（新外壳零引用）。
⚠ §10.14 里记为"待处置"的两个 `_wip_*` 备份随之删除，**该项已闭环**。

### 文档换代

* `AGENTS.md` 15 处修订：模块清单、命令块、行尾清单、两个 ⚠ 段（`flash` 引擎 / `atmosphere.py`
  已删）、交接说明、Agent 指引全部换掉。其中一处是**事实纠错** —— 旧文说"`cache_key()` 刻意不含
  tier，靠分文件隔离"，新架构恰好相反（`cache_key()` 显式含 tier），并把 `CACHE_SCHEMA` 必须随
  `Scene` 语义变化递增写成了硬规则。
* `README.md` 全文重写（576 → 204 行，保持 CRLF）：旧文描述的引擎、入口、输入文件全都不存在了。
* `docs/RESTART-PLAN.md` 增 §8 收尾记录。

### 遗留

* 高亮环图例文案仍是「基准弹 PL-12」（参考图只说"高亮环标弹名"）；若要纯弹名，改 `workflow.py` 一处。
* `Scene` 上仍缺 `samples` / `turn_rate` 字段（`targets.check_compatible` 用 `getattr` 探测，
  补上就自动生效）。
* 第二张图、等时线步长的用户自定义、出图美化：按用户指示"之后再告诉"。


## 10.16 免安装分发包（`make_dist.py`）

**目标**：发给没装 Python 的人，双击即用。根目录**只有一个 `启动.bat`**，其余全在二级目录 `app/`。

**产物**（实测 2026-09-27，Python 3.14.7 / numpy 2.5.3 / matplotlib 3.11.2）：
解压 **132.7 MB** / zip **53.8 MB**，2725 个文件。构成：`app/python/` 124.1（内嵌解释器 + 依赖，
已裁 tests）、`app/vendor/` 3.2、`app/fonts/` 3.6（思源黑体子集 7036 字）、产物 1.3。

### 三个关键设计

1. **目录形状不能改。** `spec.ROOT = Path(__file__).resolve().parents[2]` —— 只要 `app/` 下保住
   `src/ vendor/ figures/ results/` 的相对结构，所有路径自动正确，**业务代码零改动**。
2. **内核缓存靠 `LOCALAPPDATA` 重定向。** `wt_missile` 在 `%LOCALAPPDATA%\wt-missile\compiled-fast\`
   找编译产物，而且**只认这一个环境变量**（源码写死）。`run_ui.py` 在 `import missile_sim` **之前**
   把它指到包内 ⇒ 预编译内核随包走。ABI 对得上：本机 MSVC 19.44，内嵌 Python 也是 `MSC v.1944`
   且自带 `vcruntime140.dll`。**已在分发包里实测 `backend = compiled-c`** —— 对方没装 MSVC 也吃得到。
   ⚠ 一旦 `wt_missile` 被导入，它已经按默认路径找过一遍并缓存了失败结果，所以顺序不能反。
3. **中文字体必须随包。** 对方若是英文 Windows，`Microsoft YaHei` / `SimHei` / `SimSun` 一个都没有，
   图上全是豆腐块。带思源黑体 `NotoSansSC-VF.ttf`（**SIL OFL 1.1，可再分发**）的子集：
   GB2312 一二级汉字 + 希腊字母 + 常用符号共 7036 字，**17 MB → 3.6 MB**。

### 踩过的坑

* ⚠ **`PIL` 和 `fontTools` 是 matplotlib 的硬依赖**，看着像可选其实**删不得**：
  `matplotlib/colors.py:53 from PIL import Image`、`matplotlib/dviread.py:32 import fontTools.agl`。
  合计 32 MB。实测删掉立刻 `ModuleNotFoundError`，而且**只在第一次出图时**才报，极易漏掉。
  其余大头也都有硬依赖：`numpy.libs/`（20 MB OpenBLAS）是 numpy C 扩展链接的，
  `matplotlib/mpl-data/fonts/`（7 MB）含 mathtext 要用的 DejaVu 系列。
  真正能安全删的只有 numpy / matplotlib 自带的 `tests/` 目录和 pip 留下的 `bin/`，合计约 20 MB。
* `results/reference_fig.png` 从 `E:\WT` 那边拷来带**只读**属性，裸 `shutil.rmtree()` 在 Windows 上
  直接 `WinError 5` 把组装打断在半路 ⇒ `rmtree_force()` 用 `onexc` 回调先 `chmod S_IWRITE` 再删。
* `启动.bat` 的 `%*` 第一版被 `run_ui.py` 里写死的 argv 吞掉（传 `--port` 无效）⇒ 现在转发
  `sys.argv[1:]`，只在没显式给 `--no-browser` 时补 `--browser`。
* **内嵌 Python 存在 `._pth` 时进入隔离模式**：忽略 `PYTHONPATH`、不自动 `import site`。
  所以 `..\src` / `..\vendor\wt-missile` 只能写在 `._pth` 里（路径相对 `python.exe`，
  这样整包挪位置也不会坏）。
* python.org 直连下载**反复中断**（`unexpected EOF`），换**华为云镜像**
  `mirrors.huaweicloud.com/python/<ver>/python-<ver>-embed-amd64.zip` 成功；PyPI 走阿里云镜像。

### 验证

* 组装脚本**内置冒烟测试**：用分发包自己的解释器出 png + pdf + svg，任何一种失败就中止组装，
  不会等对方双击才发现。（故意带上 pdf/svg —— 那两条路径才走 fontTools，是最容易误删的依赖。）
* 双击路径实测：`cmd /c 启动.bat --port 8799 --no-browser` → **HTTP 200 · 19770 字节 ·
  页面含「等时线」「PL-12」**。
* 分发包自己的解释器 + 包内 `kernel-cache`：全尺寸 1632 工况 **命中 100%**、等时线 13 层、
  `backend = compiled-c`、43.6 s。
* 分发说明见 `docs/DISTRIBUTION.md`；`build/` 与 `dist/` 已在 `.gitignore` 里（组装产物不入库）。


## 2026-09-27 · 表单静默丢字段：图上写的工况和用户填的不是一回事

**现象**（用户报）：选了预置想定，把距离改成 50 km 再出图，图上写的还是预置的距离。
按要求"举一反三"复查后，挖出**另一个更隐蔽的**：改目标方位角 `target_bearing_deg`，
整张图**一个字都不变**。

### 根因 1 —— `targets.build_scene()` 在猜

HTML 表单**每次都会提交全部字段**，服务端因此分不清"没动过"和"特意填成默认值"。旧逻辑
（`preset` 非空时）把凡是等于 `DEFAULT_FORM[key]` 的字段一律当成"用户没动过"丢掉：

| 预置 | 用户填 | 后端收到 |
| --- | --- | --- |
| `tail_chase` | `range_m=50000`（恰好是默认值） | `20000`（预置值） |

复现时只有 5 个字段暴露出来，纯属那个预置的值恰好不等于默认值 —— **缺陷覆盖全部 17 个字段**。

**修法：前端如实上报。** `webui.py` 的 JS 加 `DIRTY` 集合：给每个 `[data-field]` 挂
`input`/`change` 监听，`collect()` 时发 `f._dirty = Array.from(DIRTY).join(",")`；换预置时
`DIRTY.clear()`。关键性质：`fillForm()` 用的是**程序性赋值** `el.value = …`，按规范**不触发**
`input`/`change`，所以"选预置自动填表"不会污染手改记录 —— 白拿的语义正确。

后端 `_parse_dirty()` 收 `"a,b"` / 列表 / 集合；`None` 或缺失 ⇒ **退回旧的猜法**，
CLI 与老客户端行为**一字不变**（有用例钉住）。`_dirty` **不进** `WEB_ONLY_KEYS`，
否则 `_scene_part()` 会把它剔掉。

### 根因 2 —— 图上的文字漏字段

`figures.plane_subtitle()` 与 `spec.Scene.describe()`（进脚注第三行）都**没写**
`target_bearing_deg`，所以改方位全图无反应；`describe()` 还漏了载机俯仰、时长、风、
地面高、命中半径、近炸开关。

**修法：非默认才写。** 两边统一规则 —— 只有**偏离默认工况**的量才出现在文字里。
于是默认工况的输出**逐字不变**，`figures/` 与 `results/` 产物**一个字节都不用重算**
（`git status` 实测确认）。

### 顺带修掉的测试地雷：`PORT = 8765` 是个假防护

Windows 的 `SO_REUSEADDR` 允许**第二个 socket 绑同一端口**，所以"端口被占"**不抛
`OSError`**：`serve()` 正常返回，HTTP 请求却全进了那个旧进程。真踩到了 —— 验收免安装版留下的
`dist\导弹包线图\app\run_ui.py`（PID 22624）没关，它带着自己的 `cache: True` 与产物目录，
4×4 网格**全部命中缓存**；而 `engine.Engine.many` 在 `todo` 为空时**一次进度回调都不发**
（`engine.py:198` 的 `if not todo: return out`），进度就永远停在 `0/0`，看起来像"扫描坏了"。
现在 `PORT = 0` 交给系统分配。**教训：那句 `except OSError` 分支从来没生效过。**

### 回归用例

新增 `tests/test_form_dirty.py`（11 条）：6 预置 × 17 字段手填默认值必须生效、`_dirty` 的各种
拼法、老客户端兜底行为不变、**每个场景字段改了图上文字都必须变**、默认工况文字逐字锁定。
全量 **146/146 通过**。

### 遗留

`_dirty` 是 `build_scene()` 契约的合法扩展（未知键仍硬报错，有用例），表单口径写在
`targets.build_scene()` 的 docstring 里（已同步成 6 条规则），**不进** `docs/SOLVER-API.md` ——
那是内核契约，换了求解器才要读。

### 补记（同一次修复的第二轮）

* ⚠ **工况文字有第三处。** 除了 `figures.plane_subtitle()` 与 `spec.Scene.describe()`，
  `targets.describe_scene()` 是**页面 `scene_text`** 用的那一套（`webui.describe()` 优先用它，
  失败才退回 `Scene.describe()`）。三处并列、措辞各异 —— 第一轮只改了前两处，于是"改方位"
  在图上修好了、**页面上还是没反应**。是分发包的端到端验收（走 `/api/single` 读
  `scene_text`）把它抓出来的：单元测试全绿，因为我自己写的可见性检查只覆盖了前两处。
  现在三处都写方位，并加 `test_the_three_scene_texts_agree_on_the_basics()` 钉住
  "同一批事实三处都得有"，免得下次又只改一处。
  **教训：查"改了参数图上没反应"时，先把该工况的字符串出口数一遍。**
* **分发包验收脚本的两个坑**（都白踩过一次）：单发接口是 `/api/single` 而**不是**
  `/api/submit`（后者只认 `kind=scan|plot` 的 JSON），且必须**表单编码**而不是 JSON；
  `scene_text` 来自上面那第三处实现，不是 `Scene.describe()`。
* **`--no-clean` 会被只读文件挡住**：`results/reference_fig.png` 自带 `ReadOnly`（从
  `E:\WT` 拷来时就带着）。`rmtree_force()` 会先 `chmod` 所以删除没问题，但 `copytree`
  **覆盖**它时直接 `PermissionError: [Errno 13]`，组装半途而废且已拷进去的部分留在原地。
  结论：`--no-clean` 只适合"改了几个 `.py`"的增量重建；动了 `results/` 或 `figures/`
  就走干净重建。
* **Windows 上删目录失败优先怀疑 CWD**：`dist\导弹包线图` 已经是**空目录**却仍报
  `WinError 32` —— 是早先验收时 `cmd /c 启动.bat` 留下的 `cmd.exe`（PID 15412）**把那个目录
  当工作目录**。`taskkill` 掉它，目录立刻可删。
* 本轮最终状态：仓库全量 **147/147**；分发包干净重建 **132.8 MB / zip 53.8 MB**，
  根目录只有 `启动.bat` + `app/`，包内自带自检 **147/147**，端到端验收 4/4 全绿
  （含用户报的"预置 + 把距离填成默认值 50 km → 图上必须写 50 km"）。


---

## 12. 图2：β–γ 能力平面（`图2` 分支，2026-09-27）

### 12.1 一张图两层

| 层 | 内容 | 数据来源 | 开关 |
| --- | --- | --- | --- |
| 参考层 | 11 弹气泡（面积 ∝ 权威 ΔV）+ 等 `n*` 双曲线 + 双优/双差象限底色 | `bg.rows()`，**不跑求解器** | 总是画 |
| 仿真层 | 固定 ΔV，在 β×γ 网格上只改 `CxK`/`CxAoA` 扫出的命中时间等时线 + 色标 | `Engine(scaling_of=bg.scaling_for)` | `--bg-no-scan` 关 |

默认网格 β 步长 30 / γ 步长 2 → **43×24 = 1032 工况**，fast 档 **14.2 s**（jobs=8），命中 1032/1032，
出 4 级等时线（44~47 s）。三格式逐字节可复现（连跑两遍 sha256 一致）。

### 12.2 ⚠ 一个静默 no-op（本轮最有价值的发现）

`_patch_profile()` 的 `walk()` **只遍历 `node.items()`，也就是只改"已经存在的键"**。
第一版照着"`node[k] = updates[k]` 直接赋值就能新增键"的假设写，而 **11 型 blk 里一个都没有
`CxAoA`** —— 于是注入**完全没生效**：不报错、不生效，产物看起来一切正常。

**症状**：γ 轴在图上**完全不动**。同一个 β、γ = 45/70/100 三个点，
`t_hit = 45.185932964507536` 逐位相同；命中时间只随 β 变（4.3 s），不随 γ 变（0.0000 s）。

**为什么差点漏掉**：代数层的自洽测试全过（乘数算对了、反解闭环了），只有"结果真的变了"
这条端到端断言能抓住它。所以现在有一条钉死的用例：
`tests/test_bg_scan.py::test_gamma_reaches_the_kernel_at_nominal_beta`
（γ↑ ⇒ `t_hit`↑、末速↓）。

**修法**：`walk()` 之后补一个"补缺"分支，把 `updates` 里 blk 没有的键写到**顶层**
（内核就是从顶层读这些字段）。同时注意注进去的是**有效值**：
内核读 `p.get('CxAoA', 9.0) × (wingAreaMult² if applyWingAreaMultToCxAoA)`，
所以 `solver.effective_cx_aoa()` 先把这条规则算准，注入时顺手把那个开关关掉。

**教训（检查清单）**：往内核注入新字段后，**必须**有一条"结果真的变了"的端到端断言，
不能只看"乘数算对了"。同类坑：`engine.cache_key()` 旧实现只收 `(ΔV, BC)` 两个数，
β–γ 扫描的 `cxaoa_scale` 进不了键 —— 同列不同 γ 会**互相命中缓存**，而且看起来完全正常。
现在键吃**整块 `Scaling`**，`CACHE_SCHEMA` 3 → 4。

### 12.3 一条物理结论

直飞不机动的工况（50 km 迎头 / 双方 300 m/s / 10 km 高 / ideal）下，命中时间**几乎只由 β 决定**：

* 固定 β，γ 从 45 → 100：`t_hit` 45.11 → 45.48（**0.37 s**）；
* 固定 γ，β 从 2600 → 3700：`t_hit` **4.3 s**。

所以仿真等时线在图上**近乎竖直**。这不是画错，是 `a_loss = q·f/β + γ·F·(n·g0)²/q` 里
"低过载时基础项主导"。图上脚注如实写了读法，`tests/test_bg_scan.py` 把这条钉住了。
γ 要显出来得有高过载需求：**40° 离轴那一档已经能看到 γ=100 直接脱靶**（`lifetime` 事件），
但本项目 UI 的预置工况都是直飞，本轮不引入机动目标（`Scene.maneuvers` 内核支持、接口留着但没暴露）。

### 12.4 接口命名的一个坑（`--bg-alt` vs `--alt`）

`BgRequest.alt_m`（图2 的**参考工况高度**，只影响等 `n*` 线）与 `Scene.alt_m`（载机发射高度）
同名但语义完全不同。第一版 CLI 让两个选项都写 `dest="alt_m"`，于是
`--bg-alt 3000 --alt 7000` 里后者覆盖前者，`_request()` 还会把 `bg_alt_m` 当 dataclass 字段名传进去
（`TypeError`）。**划不清就会"改参考高度顺手改掉发射高度"，而且不报错。**

现在有唯一一张改名表 `cli._BG_ALIASES = {"alt_m": "bg_alt_m", "speed_ms": "bg_speed_ms"}`：
CLI 的 `dest`、JSON 的键、WebUI 的表单名都用外部名，`_request()` 折回 dataclass 字段名。
同理 `WebUI.WEB_ONLY_KEYS` 必须收录 `figure` / `beta_step` / `gamma_step` / `dv_pin` / `n_ref` /
`bg_alt_m` / `bg_speed_ms`，否则 `targets.build_scene()` 会把正常提交判成"不认识的字段"。

### 12.5 测试与产物

* `tests/test_bg.py` 32 项（黄金值，来自 `_recon` 文档，不跑或只跑很少的求解器）；
* `tests/test_bg_scan.py` 16 项（反解闭环、缓存键、单调性双向、**注入真的生效**、Engine 钩子）；
* `tests/test_bg_pipeline.py` 10 项（`run_bg` 产物、CLI 字段覆盖、别名不串）；
* `tests/test_figures_bg.py` 12 项（图2 出图契约、三格式可复现）；
* `tests/test_webui_bg.py` 8 项（真起服务的图2 端到端：表单 → 后台任务 → 进度 → 产物）。

全量自检 **225/225**。正式产物：
`figures/fig_bg_plane_default.{png,pdf,svg}`、
`results/bg_default_points.csv` / `bg_default_cases.csv` / `bg_default_isolines.csv` / `bg_default.json`。
复现：`python -m missile_sim --figure bg --tag default`。
---

## 13. 机动目标可行性（2026-09-29）

用户："红区绿区没必要，另外图二的等时线也是固定条件然后改 CxK 扫描吗？那 γ 是改的 CxAOA 吗？
如果是我计划引入机动目标，我有几个设想的场景，你先打通可行性。"

### 13.1 象限底色删除

`BG_GOOD_*` / `BG_BAD_*` 常量、`_bg_quadrants()`、图例里那两块色标全部删除。
理由：两个阈值（β≥3250 且 γ≤70 / β≤3000 且 γ≥85）是对着 11 弹池目测定的，换池子即失效，
画在图上会被当成有物理含义的分界。`tests/test_figures_bg.py::test_no_quadrant_shading_anymore`
直接断言产物 SVG 里不再出现 `#E8F5E9`/`#FDECEA` 与"双优/双差"。图已重出。

### 13.2 等时线机制（确认）

图2 仿真层：**固定基准弹标称 ΔV（thrust_scale 吸收差值）**，在 β×γ 网格上
**只改两个阻力系数** —— β 走 `CxK`（`cx_scale = β_blk/β_t`），γ 走 `CxAoA`
（`cxaoa_scale = (γ_t/γ_blk)/cx_scale`）。其余量一个不动。实现见 `bg.scaling_for()`。

### 13.3 机动目标：内核全通，外壳只通一条

详见 `docs/MANEUVER-TARGETS.md`（全文）。要点：

* 三条通道 `maneuvers` / `turn_rate_rad_s` / `samples` 内核**全部生效**；
  只有 `maneuvers` 在外壳里全通（Scene 字段 + scenario_dict 出口 + cache_key + 校验）。
  另两条"内核认、外壳不认"（Scene 是 frozen dataclass，连 setattr 都挂不上）。
* `maneuvers` 是**世界系分段常值加速度** ⇒ 固定方向推不是转弯；真转弯要按
  ω = n·g0/|v_h| 逐段转动加速度方向（`.tmp_test/probe_maneuver.py::turn_schedule()` 是原型）。
* ⚠ **目标过载不是单调难度轴**（实测 β=3078/γ=56.6、30s 起转 8s）：
  0.5~9.5G 命中（t_hit 45.2→79.6s）→ 10~15.5G **脱靶**（峰值 1470 m @12.5G）→ ≥16G 又命中。
  因为 R = v²/(n·g0)，n 大 ⇒ R 小 ⇒ 目标"待在原地"。
  二分求"最大可对付过载"会给出虚假的 28G 饱和值 —— 这个坑当场踩过一次。
* γ 被激活：6G 转弯时 γ 40→140 使 t_hit 散开 **3.00 s**（直飞只有 0.67 s），
  8G 时 **10.43 s**；全程 3G 盘旋下 γ=100 命中而 γ=140 脱靶。
* 结论：不要让用户输入一个"最大过载"，而要让用户给**想定**，我们出图（命中窗口图 / β×γ 扫描）。

## 14. 想定一：crank → 正侧方（2026-09-30）

用户给了第一个机动想定：直飞 → 发射后一定时间转到 70°附近 crank（60~90 视战机而定）→
导弹开机后转正侧方 90° → 可选固定频率/振幅上下震荡。结论：**可行，且是目前最能体现
图2 两轴价值的场景**。全文与全部实测数字见 `docs/MANEUVER-TARGETS.md` §8。

关键结论（每条都有实测支撑）：

* **内核没有"导弹开机"事件**：`seeker_assumptions` 固定 `permanent_lock` /
  `unlimited_acquisition`，`observed_range_channel_valid` 是静态的。
  ⇒ 开机口径由外壳定，推荐"给距离 + 一遍法"：在**不含正侧方腿**的轨迹上取首次
  `range ≤ R` 的时刻。⚠ 拿已加腿的轨迹迭代会漂移（自指条件），别迭代。
* **模型层已入仓**：`src/missile_sim/flightpath.py`（航向指令 → `maneuvers` 解析编译）
  + `tests/test_flightpath.py` 21 项。三个坑都锁进测试了：
  (a) 腿重叠必须**截断**而非叠加（错法总转角只剩 70%，但结果看起来正常）；
  (b) 腿必须按时序（乱序静默按错序执行）；(c) `samples` 必须逐字覆盖到 `duration_s`
  （`t += dt` 累加会给出 149.99999999999997，被内核拒收）。
* **两条路互校有效**：`maneuvers`（0.1 s 分段常值）vs `samples`（精确积分）。
  段长 0.5/0.2/0.1/0.05/0.02 s ⇒ t_hit 与精确值的差 0.868/0.099/0.199/0.084/**0.037** s，
  收敛。**第一条路写错时就是靠这条互校抓出来的（差 6.06 s）。**
* **crank 必须早开始**：5G 转 70° 要 7.48 s。crank 排在发射后 25 s（距离只剩 20.5 km）
  时只转了 49°，于是 **crank 角 60/70/80/90° 给出完全相同的 t_hit** —— 参数是假的。
  取 t_crank=8 s 后：60°→65.0 s、70°→67.5 s、80°→71.2 s、90°→76.2 s（直飞 45.2 s）。
* **震荡能造成脱靶，但要选对角落**：代价由位移幅度 `v·amp/(2πf)` 与目标横向过载
  `v·amp·2πf` 共同决定。±6°/0.3 Hz（6G 却只有 17 m 位移）毫无影响；
  **±30°/0.1 Hz（10.1G、250 m）⇒ 脱靶 207.5 m**。
* **γ 第一次决定命中与否**：β 2580~2660 区间内，γ=40 **全部命中**、γ=91.2 **全部脱靶**
  ⇒ 两轴交换率约 80 个 β。γ=56.6 时 β 的命中阈值 β*≈2600，
  而**直飞时 β=2567 也命中** ⇒ 阈值完全是这条轨迹造的。
  机理：同 β=2800 下 γ 从 40 拉到 91.2，弹速只低 1.3%（549→542 m/s），
  但同一时刻距目标远 400~580 m ⇒ 轨迹被整体推后，末段闭合窗口收窄。
  **不是控制权限不够**（末段实际横向过载仅 4~5G），是"能量换位移"的账。
* **11 型弹命中 6/11**（t_crank=8 s）：低 β 的 R-77-1/MICA/R-Darter/R-77/Derby 全脱靶
  （897~1975 m）。且**排序与 β 不一致**：按 β 排第一的 AAM-4 按命中时间排最后
  （59.842 s vs 120D 的 59.390 s），因为它用最高 β 换来了最高 γ（89.32 vs 57.06）。
  ⇒ 这就是"两轴互相独立、合起来才完整刻画"的直接证据。
* **外壳尚未接入**：`Scene` / `scenario_dict()` / `cache_key()` / `targets._FORM_KEYS`
  都还没动，现在跑不出这条想定，只能用测试与文档里的实测数字。接入清单见 §8.7。
## 15. 用户确认四条口径（2026-09-30）——"开机距离"就在 blk 里

用户回复了四条（详见 `docs/MANEUVER-TARGETS.md` §8.8），前三条把契约定下来了：

* **开机距离 = `guidance.lockDistance`**（变量名找到了）。实测 120A/120C/120D、MICA、
  Derby、AAM-4、R-Darter = **20000**；PL-12/PL-12A、R-77/R-77-1 = **16000** ——
  和用户凭记忆给的"120 系列/德比/米卡 20 km、PL12/R77 系列 16 km"**完全一致**。
  ⚠ 内核 `wt_missile.py` 里 grep **`lockDistance` 零命中**（与 `permanent_lock` +
  `unlimited_acquisition` 一致）：它是 blk 里内核不用的字段，**正好当我们"开机"的定义**，
  不用改内核。另：`radarSeeker.receiver.range` 也是 16000 但全弹一样，不是区分项。
* **转向过载 6~14G 可调、默认 9G**；转 70° 用时 6G 6.23 s / 9G 4.15 s / 14G 2.67 s。
  用户的定性口径："**没转完正是对应实战中没能完成 39 干扰从而被击落**" ——
  所以"是否转完"和"开机时实际航向"要作为**输出量**报出来，不是把参数判为无效（原来 §8.4
  的措辞已改）。
* **39 干扰成败网格**（开机 20 km、crank 70°、PL-12、7 时机 × 6 过载 = 42 点）：
  只有 (crank 2 s, 10~14G) 这 3 格**脱靶**（= 干扰成功）；t_crank ≥ 22 s 时 6~10G
  **全都转不完 ⇒ 被击落**；中间一大片（6~22 s）都是被击落。
  ⚠ **非单调**：9G→10G 在 t_crank=2 s 时从"被击落"变"脱靶"，但在 6 s 时几乎无差别。
* **`crank_beam()` 补了边界语义**：开机早于 crank 时 `t_beam = max(t_beam, t_crank)`
  —— 弹已开机，crank 无从谈起，从当前航向**直接转正侧方**（180°→90° 一次转完）。
  原先这会生成一个乱序腿表而被 `PathSchedule` 拒绝（探针就是这么发现的）。测试 +1（22 项）。
* **⚠ 锚点必须用同一枚弹反求**：同一 crank-only 轨迹上"20 km 出现在何时"随 β/γ 变动 ——
  标称 29.40 s、β3000/γ40 29.44、β3000/γ91.2 29.77、β2500/γ91.2 31.10 s（弱弹差 1.7 s）。
  对 t_hit 影响约 0.4 s，**但在命中边界附近足以翻转结果** ⇒ 出图时每点各反求一次（成本 ×2）。
* **9G + 各自 lockDistance 下的 11 型弹**：仍命中 6/11，脱靶的还是低 β 那五型
  （R-77-1 1272 m / MICA 1989 m / R-Darter 2211 m / R-77 2378 m / Derby 2695 m）；
  按 β 排序与按 t_hit 排序**仍然不一致**。
  附带发现：**开机距离本身是战术量** —— 16 km 那组比 20 km 那组多 5 s crank 时间
  （t_beam 34.46 vs 29.40 s），所以 PL-12 家族"沾了开机晚的光"，但仍比 120 家族慢。
* **震荡默认值待用户经验数据**：接口按 (振幅 deg, 频率 Hz) 做，用户给之前**默认关闭**，
  不自造经验值（字段里放占位说明）。
* **外壳接入的最终形状**（§8.7）：表单字段 = crank 起始/角度、开机距离（默认 `lockDistance`）、
  正侧方角、转向过载（默认 9G）、震荡振幅+频率（默认关）；输出加"转完?"与"开机时航向"；
  第一优先出图 = **39 干扰成败图**。
## 16. 图2 附加俯视轨迹面板 —— 计划（2026-09-30 夜，未实施）

用户睡前给了取向：**不求 β/γ 主导交换的解析临界点**（沿用等时线 + 斜率读法就够直观）、
**图一保持不变**、**图二额外附加俯视轨迹**（敌机 + 导弹，标明"导引头开机 / 开始转入 crank /
crank 段 / 开始由 crank 转入 39 / 39 段"，不同段用颜色区分）。3D 渲染记入后续。
完整计划落盘在 `docs/PLAN-FIG3-TRAJECTORY.md`（含数据契约、分段表、5 阶段、10 条预判坑、
4 个待拍板项），本轮**不动代码**。

要点（供实施时先看这一段）：

* **绕不过去的事实**：图2 是手工固定版面（`FIG_SIZE=(12.0,6.8)`、`AX_RECT`、`CAX_RECT`、
  题头与脚注手工锚定）。往同一画布加面板 ⇒ 主轴矩形/画布必须变 ⇒ **现有
  `fig_bg_plane_default.*` 字节必变**，图2 的字节测试与 manifest 要重基线。
  所以给了两方案（推荐 A：现有文件逐字节不动 + 新增 `fig_bg_traj_*` + 拼版预览；
  B：直接改默认图为两面板 + 重基线）。**待用户拍板**。
* **朝向口径**：内核 `heading 0=+x / 90=+z / 180=−x` ⇒ crank 段 110°、39 段 90°，
  39 段在俯视图里**平行于 z 轴**。必须 `set_aspect("equal")`，否则 110° 与 90° 看起来一样。
* **节点一律查 `rows` 的表**（`dt=1/48 s`），不自算第二套时间口径；
  "导引头开机"建议画成空心大圆 **+ 连到目标当时位置的细线**并标 `R=16.0 km`。
* **分段直接由 `PathSchedule.table()` 的 ω 表折出**（新增 `segments()`），
  不另做时间算术 —— 这也是 §8.3"腿重叠"坑的防线。
* ⚠ **"没转完"天然可见**：两条指令同时刻下达 ⇒ 后一条截断前一条 ⇒ 180° 一次弧转到 90°，
  **没有 110° 平台段**。这正是"没做成 39 干扰 ⇒ 被击落"的可视化，图例要单列这一条。
* ⚠ **震荡在俯视图里看不见**（若"上下震荡"指高度方向）—— 最容易被误解的一点，
  要么图注写明，要么加一个很扁的侧视 inset。**待用户确认方向**。
* **第一版不碰 `Scene` 契约**：只需 `maneuvers`（已全通），所以 `turn_rate_rad_s` / `samples`
  两条通道**不接**，`CACHE_SCHEMA` 也**不用动**；预跑（无 39 腿）与正式跑是两个 Scene，
  各自进缓存是正确的。
* **必须输出的两个量**：`anchor.completed`（是否转完）与 `anchor.heading_at_beam_deg`
  （开机时实际航向）。
* 数据契约：新增 `Segment` / `TrajMark` / `ScenarioRun` 三个纯数据类，
  出图、`results/bg_traj_*.json`、航迹 CSV 三方共用；图里每个节点都能在 CSV 里查到（可复核）。
* 另记一条边界（进 `docs/SOLVER-API.md` 时别忘）：**`guidance.lockDistance` 内核不读**，
  由外壳消费作为"导引头开机"的定义。
## 17. 图3 定案：独立成图（2026-09-30 补充）

用户看完计划后定案，要点（计划全文见 `docs/PLAN-FIG3-TRAJECTORY.md`）：

* **改成独立的"图3"**，不再往图2 上叠面板。用户原话："那就直接弄成独立的图3，
  细想来确实是独立更贴切。" ⇒ 直接收益：上一轮那个"加面板必然改图2 字节、要重基线"
  的纠结点**整个消失**，图2 一个字节都不用动。三张图分工：
  图1 ΔV–BC / 图2 β–γ 能力平面 / **图3 一个机动想定的轨迹**（`fig_traj_<tag>.*`）。
  CLI 的 `--figure` 扩成可组合 `plane,bg,traj`（保留 `both` = `plane,bg` 兼容，新增 `all`）。
* **主方案仍是纯俯视**，但用**副面板"高度–时间"**把看不见的那一维讲清楚
  （一物三用：高度方向震荡可见 / 节点的时间疏密可读 / 脱靶时 39 段拖多久一眼看到），
  节点在两幅图上**同一时刻**、纸面上竖直对齐；再加一个**放大 inset** 画"开机→转39"
  那 1~2 s（俯视图上那 20° 角差在 50 km 量级里看不出来）。
  → 上一轮"震荡是高度还是水平方向"这条**不再阻塞**：副面板两种情况都覆盖。
* **输入阶段给 3D 预览**（用户点名："开始解算前用户输入的时候也有 3D 动画直观展示，
  我觉得这样用户是能拿捏准的"）。⚠ 关键洞察：**目标航迹是纯运动学，不需要求解器** ——
  `PathSchedule.samples()` 只依赖（速度、起始航向、crank 时机/角度、转向过载、正侧方角、
  震荡），毫秒级。所以"改一个参数立刻看到 3D 轨迹"做得到，解算那几十秒留给正式图。
  3D 用 matplotlib 自带的 `mplot3d`（**无新依赖**）；"动画"用服务端预渲染 N 帧方位角
  + 前端 `<img>` 轮播（纯标准库，**不引外部 JS/CDN**，保住"离线分发包双击即用"的约束）。
* **可交互 3D（鼠标拖动换视角）记为备用方案**（用户："这需要交互式网页，记为备用方案"）。
  诱人是因为数据本来就是 3D 的、俯视图天然丢一维；成本在于现有 WebUI 是纯标准库离线包，
  引入 Three.js 必须单文件内联、不许 CDN。低成本中间态可先做：服务端**多角度拼图**或
  转一圈帧序列（与输入预览同一套机制）。触发条件：主方案落地后仍嫌视角不够。
* 计划里同步更新：分段表、`TrajRun` 数据契约（独立于 `BgRequest` 的 `TrajRequest`）、
  5 阶段实现步骤（P4 = 输入阶段 3D 预览）、11 条预判坑、待拍板 3 项。
* 仍未定的两项：**震荡默认振幅/频率**（等你经验数据，之前默认关闭）、
  **"导引头开机"与"开始转入39"是否同刻**（默认同刻，延迟 0）、**图3 跑哪几型弹**。
## 18. 图3 的分支策略（2026-09-30 追加）

用户："图3 同样在图2 整体完成后单独分支，这只是一个纯展示性的所以可以作为树梢。"

* **分支点**：**在 `图2` 整体完成之后，从完成后的 `图2` 分出单独分支**（建议名 `图3`）。
  好处：`图3` 天然继承 `src/missile_sim/flightpath.py`、`docs/MANEUVER-TARGETS.md` 与本计划；
  而且**图3 的图注要指回图2 上的那个点**（同一个 (β, γ)），图2 就在同一分支上，最顺。
  备选是从 `restart` 分（图3 其实不依赖 β–γ 平面），代价是 cherry-pick 两个提交、
  且图注要指回的图2 不在分支上 —— **不推荐**。
* **定位 = 纯展示性的叶节点（树梢）**：整棵树上最后一片叶子，没有别的功能依赖它，
  做不完也不影响前两张图 ⇒ **排最后、优先级最低**，可以慢慢打磨。
* **叶子约束（这条是原则，不是建议）**：叶节点**只消费、不改变上游契约** ——
  图3 **不许**改内核（`vendor/` 只读）、**不许**改 `Scene` / `scenario_dict()` / `cache_key()`
  / `CACHE_SCHEMA`。这正是"第一版不接 `turn_rate_rad_s` / `samples`，只需 `maneuvers`"
  的由来。哪天图3 非要动契约，它就不是叶子了，应当拆成独立特性分支。
* **`图2` 的收尾清单**（做完才分图3）已写进 `docs/RESTART-PLAN.md` §11 第 5 条，只有两件事：
  1. `docs/SOLVER-API.md` **§4** 补三条实测边界 —— 内核**没有"导弹开机/pitbull"事件**
     （`seeker_assumptions` 固定 `permanent_lock` + `unlimited_acquisition`，
     `rows.observed_range_channel_valid` 是**静态**列）、**`guidance.lockDistance` 内核不读**
     （grep 零命中）由外壳消费作为开机定义、`maneuvers` 是**世界系分段常值加速度**
     且**固定方向的加速度不是转弯**；
  2. `docs/SOLVER-API.md` **§1.2** 确认 `Scene.maneuvers` 有出口说明，并指向模型层
     `flightpath.py` 与 `docs/MANEUVER-TARGETS.md`。
  查证：原以为要补的 §2.1"β–γ 扫描的乘数注入契约"**早在图2 落地时就写完了**
  （含 `_patch_profile()` 只能改已存在键 ⇒ 第一版注入 `CxAoA` 是静默 no-op 这个坑）。
  然后：全量测试 + `git diff --stat` 对照，打一次收尾提交，再 `git switch -c 图3`。
* ⚠ **过程记录（本轮踩的 git 坑）**：`git mv` 已经把改名**放进索引**，之后再
  `git add <旧路径>` 会因为 pathspec 不匹配让**整条命令失败**（一个文件都没加），
  于是提交里只有"rename 100%"、**内容是旧的**，真实改动还留在工作区。
  症状：`git show <commit>:<path>` 的头一行还是旧标题。
  处置：`git add <新路径> <其他>` → `git commit --amend -F <同一个消息文件>`，
  提交 `48cc49b` → `104aba9`。**教训：改名后不要再引用旧路径去 add。**
## 19. 图3 契约收口：反应延迟 + 只跑基准弹（2026-09-30）

用户三条收口（原话）：

1. "正常来说看到 RWR 告警才转，按人的反应时间可以酌情给延迟"
2. "图3只跑被选中的那型基准弹即可"
3. "开机早于 crank则同样给与延迟，因为等于是没准备预规避直接开始39"

### 19.1 定稿的规则

```text
t_react = t_beam + react_delay_s        # 开机 + 人的反应时间；默认 1.0 s（可调）
若 t_react >= t_crank：腿 = [crank @ t_crank(70°), 39 @ t_react(90°)]   # crank 可能被截断
若 t_react <  t_crank：腿 = [39 @ t_react(90°)]                        # 丢弃 crank 腿，延迟照给
```

* **「导引头开机」与「开始由 crank 转入 39」是两个不同的节点**（延迟为 0 时才重合）
  —— 这正是用户点名要标的 5 类节点里那两个，图3 要各画一个点。
* 延迟期间目标**不是停着等**：仍在原航向上飞（crank 段 110°，或没来得及 crank 时仍 180°），
  所以第 3 段（或第 1 段）会延长 `react_delay_s` 秒。
* ⚠ **现有代码是旧规则**：`flightpath.crank_beam()` 里是 `t_beam = max(t_beam, t_crank)`、
  且**没有延迟参数** ⇒ 必须改（加 `react_delay_s` 默认 1.0、按上表分支、改
  `test_beam_before_crank_means_go_straight_to_beam`）。已列为 **`图2` 收尾项**
  （`docs/RESTART-PLAN.md` §11 第 5 条），在 `图3` 分支之前完成。
* **图3 只跑"被选中的那型基准弹"**（全局 `--standard`，默认 PL-12）⇒ `TrajRequest` **不设弹型字段**，
  `lockDistance` 与图注里的 (β, γ) 都取自该型；这样图3 与图2 上的圈标记是同一枚弹。

### 19.2 实测：延迟帮的是导弹（每 1 s 吃掉约 78 m 脱靶余量）

**远离边界时是二阶**（PL-12 / 16 km / t_crank=8 / 9G）：

| 延迟 | 0 s | 0.5 s | 1.0 s | 2.0 s | 3.0 s |
| --- | --- | --- | --- | --- | --- |
| t_hit | 69.554 | 69.363 | 69.172 | 68.794 | 68.418 |

⇒ 只早约 **0.38 s / 秒延迟**，全部仍命中。

**边界附近是一阶量** —— 脱靶量随延迟**线性变小，约 −78 m 每秒**：

| 脱靶格（开机 20 km / crank 70°） | 0 s | 0.5 s | 1.0 s | 1.5 s | 2.0 s | 斜率 |
| --- | --- | --- | --- | --- | --- | --- |
| 10 G | 229.6 m | 190.1 | 151.0 | 112.1 | 73.8 | −78.0 m/s |
| 12 G | 440.6 m | 400.5 | 360.4 | 320.5 | 280.8 | −79.9 m/s |
| 14 G | 395.2 m | 354.1 | 313.2 | 272.4 | 231.9 | −81.7 m/s |

11 型里脱靶的五型（各自 `lockDistance`、延迟 0 → 1.0 s）落在同一条线上：
R-77-1 1153.7→1074.9（−78.8）/ MICA 1522.4→1450.1（−72.3）/
R-Darter 2044.4→1963.9（−80.5）/ R-77 2224.6→2141.7（−82.9）/ Derby 2217.0→2143.0（−74.0）。

* 10 个工况落在 **−72 ~ −83 m/s**，跨越 β 2567~3078、开机 16/20 km、过载 9~14 G —— 稳定得反常。
* **机理（别写反）**：延迟期间目标在 110° 上，`cos110° = −0.342` ⇒ **仍在向导弹靠近 103 m/s**；
  "多飞 282 m 侧向"被"多逼近 103 m"抵掉一部分 ⇒ **净效应帮导弹**。
  所以"看到告警才转"对目标是个真实代价，不是模型噪声。
* 引信量级 10 m，所以"余量 73.8 m"那格（10G + 2 s 延迟）再晚约 0.9 s 就会被翻成命中。
* 五型脱靶弹在延迟 1 s 后**仍然全部脱靶** ⇒ §8.8.5 的 6/11 命中结论对延迟是**稳健的**。

### 19.3 边界规则修正的实测差

t_crank=26 s / 开机 20 km（t_beam=25.48 s，早于 crank 起始）、9G：

| 读法 | 转入 39 起于 | t_hit |
| --- | --- | --- |
| 旧规则（夹到 t_crank） | 26.00 s | 59.528 s |
| 新规则（丢弃 crank） | 25.48 s | 60.086 s |

差 0.56 s，方向是**新规则更早转 39 ⇒ 弹飞得更久**（侧方段去掉了接近分量）—— 与 19.2 机理一致。
（延迟 ≥0.52 s 时两种读法重合，因为那时 `t_react` 已经晚于 `t_crank`。）

### 19.4 落盘位置

`docs/MANEUVER-TARGETS.md` §8.8.3（边界规则修订）+ **§8.9（新增：延迟契约与全部实测表）**；
`docs/PLAN-FIG3-TRAJECTORY.md` §0（两条新拍板）/ §3.2（分段表改用 `t_react`）/
**§3.3（新增：延迟实测效应）**/ §5 P1-P2（`react_delay_s` + 边界规则修正是 P1 第一项）/
§8 第 12~14 条（新坑）/ §9（待拍板从 3 项收到 **1 项**：只剩震荡默认振幅/频率）；
`AGENTS.md` 机动目标一节；`docs/RESTART-PLAN.md` §11 第 5 条（`图2` 收尾第一项）。
本轮**仍未动代码**（探针在 `.tmp_test/`，gitignored）。

## 20. 图2 收尾：延迟契约落地 + 内核边界实测（2026-09-30）

§19 只落了**文档**（当时代码还是旧规则）；本轮把**代码、测试、内核边界文档**一起收口，
然后从"完成后的 `图2`"切出 `图3` 分支。

### 20.1 代码：`crank_beam()` 的边界规则换成定稿版

`src/missile_sim/flightpath.py`：

```python
def crank_beam(t_crank, crank_deg, t_beam, beam_deg=90.0, speed_ms=300.0,
               g_crank=5.0, g_beam=5.0, react_delay_s=1.0, weave=None): ...
    t_react = t_beam + react_delay_s
    if t_react <= t_crank:            # 告警来得太晚：丢弃 crank 腿
        legs = (TurnLeg(t_react, 180 - beam_deg, g_beam, "cw"),)
    else:                             # 两条腿，crank 可能被截断（"没转完"）
        legs = (TurnLeg(t_crank, 180 - crank_deg, g_crank, "cw"),
                TurnLeg(t_react, 180 - beam_deg, g_beam, "cw"))
```

* `react_delay_s` 默认 **1.0 s**；`t_react <= t_crank`（**含相等**）丢弃 crank 腿 ——
  两种情况轨迹完全等价，丢弃只是不会在 `table()` 里留下 `(t, t, ω, ψ)` 空段。
* `react_delay_s` 为负 / NaN / Inf ⇒ 构造期 `ValueError`。
* 全仓 grep 确认 `crank_beam()` **没有任何生产调用方**（只有测试），所以换语义是安全的；
  `flightpath` 也还没有被任何 `src/` 模块 import，因此**不影响任何已跟踪产物**（`figures/`、`results/` 字节不动）。

### 20.2 测试：`-k flightpath` 22 → 27，`-k solver_api` 15 → 17（全量 247 → 254）

* 作废 `test_beam_before_crank_means_go_straight_to_beam`（它锁的是旧的 `[26.0, 26.0]`），
  新增/改写：`test_beam_command_before_crank_drops_the_crank_leg`、
  `test_delay_applies_when_beam_command_precedes_crank`（用户最新口径的专属回归：
  `t_beam=20.0` + 延迟 1.0 ⇒ 腿表 `[21.0]`，既不是 20.0 也不是 26.0）、
  `test_beam_command_equal_to_crank_drops_the_crank_leg`（钉住 `<=` 这一侧）、
  `test_react_delay_default_is_one_second`（钉住文档默认值 1.0）、
  `test_react_delay_shifts_the_beam_command`（延迟窗口内航向仍是 110°、角速度为 0）、
  `test_bad_react_delay_is_rejected`。
* `tests/test_solver_api.py::test_kernel_rejects_non_increasing_maneuver_times`：
  乱序 / 重复时刻都必须是 `Shot(ok=False)` 且错误里含 `strictly increasing`
  （这条测试的作用是**把 20.4 的更正锁住**：谁再把"静默按错序执行"写回来就会先撞上它）。
* `tests/test_solver_api.py::test_crank_beam_scenario_end_to_end`：走**外壳 API**
  （`solver.run` + `Scene`）复现 §8.8.4/§8.8.5/§8.9 的三个数 —— 一遍法反求锚点
  **34.46 s**、延迟 0 ⇒ **69.554 s**、延迟 1.0 ⇒ **69.172 s**。**第一次跑就全中**，
  说明探针路径与外壳路径给出同一组数字（这比探针自证更有力）。
* ⚠ 顺带记一个坑：`Shot.rows` 是 `solver.trajectory()` **精简过**的轨迹，
  键名是 **`t` / `range` / `x` / `y` / `v` / `mass` / `thrust`** ——
  不是内核原始的 `time_s` / `range_m`。探针脚本用原始行，测试用 `Shot.rows`，两者别混。

### 20.3 内核边界（写进 `docs/SOLVER-API.md` §4 的三条）

1. **没有"导弹开机 / pitbull"事件**：`summary['seeker_assumptions']` 恒为
   `{'permanent_lock': True, 'unlimited_acquisition': True, 'unlimited_tracking_rate': True,
   'unlimited_off_boresight': True}`（`wt_missile.py:2750`）——
   ⚠ **是四个键**，之前笔记里只写了前两个，本轮按源码补全。
   逐采样行的 `observed_range_channel_valid` 由导引头**静态通道能力**决定
   （`:1886` = `p[P_locked] && p[P_range_valid]`），**不随时间变**：它说的是"这枚弹有没有测距通道"，
   **不是**"导引头开没开机"。
2. **`guidance.lockDistance` 内核不读**（`wt_missile.py` grep 零命中，只在 blk 资源里），
   于是正好当"开机"的物理定义：120A/120C/120D/MICA/Derby/AAM-4/R-Darter = 20000 m，
   PL-12/PL-12A/R-77/R-77-1 = 16000 m。⚠ `radarSeeker.receiver.range` 对 11 弹**全是 16000**，
   不能当区分依据。
3. **`maneuvers` 的语义与硬校验**：世界系分段常值加速度、`time_s` 是**绝对**时间、
   固定方向加速度**不是转弯**；时刻必须非负且**严格递增**。

### 20.4 更正一处被证伪的旧表述（重要）

仓库四处写着"目标运动的腿乱序会被引擎**静默按错序执行**（不报错、只是结果不对）"。
**实测证伪**：这是一次**硬拒绝**。

实测（`fast` 档，直接喂内核）：

| 输入 | 结果 |
| --- | --- |
| 乱序 5 s → 3 s | `ValueError: Maneuver times must be nonnegative and strictly increasing` |
| 重复 3 s / 3 s | 同上 |
| 同刻 3 s / 3 s / 4 s | 同上 |
| 正常 3 s / 5 s | 通过 |

源码同证：`wt_missile.py:247-248` 里 `time <= previous` 就 `raise`；外壳另有一道预检
（`targets.py:363` `maneuvers 的时间必须严格递增`），`solver.scenario_dict` 按原顺序搬运
（不排序、不丢弃）⇒ **没有任何静默路径**。

已改：`AGENTS.md`、`flightpath.py`（docstring + 报错文案）、`docs/MANEUVER-TARGETS.md` §8.3、
`docs/SOLVER-API.md` §4。**`NOTES.md` 第 959 行的历史记录不动**（日志按原样保留，更正记在本节）。
⚠ 真正**静默**的风险是另一件事：把**相对偏移**当成**绝对时刻**填 —— 那种时刻表看起来递增、
内核照样接受，结果全错。`PathSchedule` 里那道按时序的 `raise` 保留，理由改成"`table()` 的截断语义
依赖顺序，且错误要带意图在最靠外一层报出来"。

### 20.5 交付

`-k flightpath` 27 项、`-k solver_api` 17 项、全量 **254 项**全绿；`git diff --stat` 与
`git diff -w --stat` 一致；一次收尾提交后 `git switch -c 图3`（只建分支，不写代码）。
图3 的实施计划见 `docs/PLAN-FIG3-TRAJECTORY.md`（§5 P1/P2 的验收数字已被本轮测试锁住）。

### 21. 图3：机动想定的完整轨迹（v1 落地）

**21.1 用户口径（定稿，别再自行发挥）**：敌机不是"持续定 G 转弯"，而是
**直飞 → 看到 RWR 告警后（人反应延迟）转到 70° 附近做 crank 预防御 → 导弹开机后转入正 39 位（90°）**，
可选的叠加**固定频率/振幅的俯仰震荡**。三个节点都要在图上看得见：
**告警/预规避落点、导引头开机、开始转入 39**；`--traj-preview` 要在**输入阶段**就能看 3D。

**21.2 两条口径（都不许改）**：
* **"导引头开机"没有内核事件**（内核只有 `permanent_lock` + `unlimited_acquisition`），
  所以定义成 **首个 `range ≤ blk 的 guidance.lockDistance`**（PL-12/R-77 系列 16 km，
  120 系列/MICA/Derby/AAM-4/R-Darter 20 km），并且用**一遍法**在**不含 39 腿**的轨迹上反求、
  **同一枚弹**、**不插值、不迭代**（自指条件，迭代会漂移）。
* **`t_react = t_beam + react_delay_s`**（默认 1.0 s = 人的反应时间）；
  `anchor.completed`（**开机时**转没转完）看 `t_beam`，`Segment.truncated`（39 指令**截断**了 crank 转弯）
  看 `t_react` —— **两个不同的节点**，别混。
  **延迟帮的是导弹**（延迟期间目标在 110° 上仍有 `cos110° = −0.342` 的接近分量）。

**21.3 锁值（PL-12 / 50 km 迎头 / 16 km 开机 / crank 8 s 70°@9G / 39 位 90°@9G）**：
`t_beam = 34.458 s`（该行 `range = 15989.97 m`）、crank 转完 12.153 s（航向 110°）、
延迟 0 ⇒ 命中 **69.554 s**、延迟 1.0 ⇒ **69.172 s**；一遍法成本 fast 档两遍 ≈0.4~0.5 s。
边界：t_crank 26 s ⇒ `completed = False`、开机航向 125.2°；t_crank 40 s + 钉死 t_beam ⇒
**丢弃 crank 腿**，段数 **3**（直飞/转入39/39保持）、`completed = None`、开机航向 180°。

**21.4 独立对抗性验证（`fig3-verifier`，只读，证据在 `.tmp_test/verify/`，报告 `REPORT-task5.md`）**：
数值层（锁值、锚点、边界、分段、manifest、CSV 表头、CLI/JSON 入口）**全部确认**；
追加 A（图1/图2 与 `HEAD` **逐字节一致**，工作区比 + 重跑比两种比法）与追加 B（WebUI 摘要键数
preview 23 / 正式 32、`figure=all` 真跑三张、`traj_react_delay` 留空回落 1.0 与 CLI 一致）
**都已做且通过**。同时证伪出 **11 条缺陷**（D1~D11），最严重的是
**放大 inset 退化成 6.5 px × 723 px 的紫竖线**（`pad_z` 把 ylim 撑大约 21×，再被 `set_aspect("equal")`
二次收缩 200×）而图例仍在宣传它 —— **5 个哈希都没修好**。

**21.5 本轮判掉/修掉的东西**：
* **D5（脚注里的 markdown `**`）在产出侧修**：`workflow.py` 不再往脚注里写 `**`
  （出图侧再清洗是第二道防线，不替代产出侧）。同理 `⚠`(U+26A0) 在 Microsoft YaHei 缺字形，
  产出侧改用 `※`。
* **D9（39 指令落在命中之后）**：开机距离人为调小（`--traj-lock-m 100` ⇒ `t_beam = 60.583 s`、
  `t_react = 61.583 s`）时第一遍 **60.760 s 就命中**，第二遍的 39 腿**起于命中之后** ——
  以前**静默出一张看起来正常的图**，会被误读成"目标做了 39 仍被击落"。
  现在它是**输出量**：`anchor["react_after_pass1_hit"]`（布尔）+ 脚注另起一行明写，
  回归测试 `tests/test_traj.py::test_run_traj_flags_a_39_command_that_lands_after_the_first_pass_hit`。
* **D11（文档口径）**：`--traj-preview` **不解算**（`solver.run` **零调用**，但会调用一次
  `solver.profile` 读 blk 取 `lockDistance` ⇒"完全不碰 solver"是错的、"不解算"才对）；
  耗时实测 **不出图 0.074~0.095 s / 只出 png ≈0.75 s / 三格式 1.9~2.6 s，
  CLI 端到端 ≈3.5 s**（含解释器 + matplotlib 启动）。**早期那个"0.010 s"作废**。
* ⚠ **"10~15.5G 是脱靶带"只属于另一个想定**（固定 (β,γ)、30 s 起转 8 s）：
  在 crank→39 想定上把 `crank_g`/`beam_g` 从 8 扫到 18 G，**全部命中、脱靶量都是 10.0 m**，
  **没有脱靶带**。引用这条必须带想定。
* **D10（WebUI `figure=both` 静默不一致）**：WebUI 里 `both` 只跑图2、CLI 里是图1+图2，
  而且 `both` 不在下拉里（只能手工 POST 触达）。已改成**与 CLI 对齐**（下拉 5 个取值与服务端白名单
  逐字相同），`summarize_plane()` 补显式 `"figure": "plane"`（`figure=all` 的 `parts` 第一个
  不再是 `(None, True)`）。连带修 `tests/test_webui_bg.py:205` 的**隐式**旧断言
  （用"缺 `figure` 键"认图1 ⇒ 改成认显式值）。
* **D1~D8（出图缺陷）** 由队友 `figures-fig3` 接手（task-6）修完，复验由 `fig3-verifier` 接（task-7）：
  判据是**像素**与**图例一致性**，不是"命令退出 0"。它顺带挖出两个新缺陷：`_inset_slot` 返回**四角**
  却被当成 `inset_axes` 的 `(x0,y0,宽,高)`（框高系统性多出一个 `ay0`），以及 inset **自己**的 x 刻度
  互压（`44.144.244.3k` 一团糊）。修后实测：inset 137.5×361.3 / 137.1×361.3 / 148.8×200.6 /
  162.6×172.2 / 137.6×361.3 px（@300 dpi），ylim 跨度 879~1696 m（**8~22 倍真放大**，改前是
  "幅值为零的假放大"）；注记两两重叠 **0.0 px²**；`Glyph ... missing` **0 条**；SVG 里 `**` **0 处**；
  truncated 段实测 `TRAJ_TRUNC_LS=(0,(4,2))`；图1/图2 六件产物**逐字节与 HEAD 相同**（无泄漏）。
* **图2 脚注里的字面 markdown**（同族缺陷，Lead 顺手修）：`workflow.py` 给图2 写的"读法"那句带
  `**几乎不机动**`，matplotlib 不解析 ⇒ 图上就是星号。删星号后重出 `fig_bg_plane_default.*`；
  **用 Pillow 逐像素比过**：与 HEAD 的差异 bbox = `(75,2361)-(2647,2474)`、非零像素 0.5669%、
  全在底部脚注带，**绘图区零变化** —— 这是"只改了一行文案"的机器证据，不是"看起来对"。
* **输入阶段 3D 预览的版式**（Lead 修，`plot_traj_preview_3d`）：原来标题压在副标题上、图例压在轴标题
  上、水平轴刻度糊成一团（`35000 40000 45000…`）、高度轴两个刻度叠印。现在标题/副标题/图例/轴标题
  四者不重叠（间距按**字号行高**换算，不是拍脑袋），x/z 轴各限 4 个刻度，**高度跨度远小于水平跨度时
  只留一个刻度**并用 `labelpad` 避开轴标题；脚注口径也改成"不解算"。

**21.6 未做项 / 下一步**：
* **可交互 3D（鼠标拖动换视角）**仍是**备用方案**（`PLAN-FIG3-TRAJECTORY.md` §7），主方案不依赖它；
* **震荡的默认参数等用户给**（在给之前**默认关闭**，不自造经验值）；
  震荡到底是**竖向**还是**水平**摆动也要用户确认（现在按俯仰/竖向实现）；
* 多方位分格面板（`plot_traj_preview_3d` 已支持 `azimuths=`，外壳未暴露）；
* 出图侧的物化判据**已落地** `tests/test_traj_plot.py`（23 项：inset 像素宽高/在框内、注记两两重叠、
  `Glyph ... missing`、truncated 线型（要用 `_unscaled_dash_pattern`，`get_linestyle()` 有损）、
  图例↔artist、三格式字节复现）；`test_traj.py` + `test_webui_traj.py` + 它 = `-k traj` 71 项。

**21.7 交付**：见本轮收尾提交（`图3` 分支）。测试：`-k flightpath` 37、`-k traj` 71
（30 + 18 + 23）、`-k traj_plot` 23、`-k webui` 33、**全量 335 项**（`AGENTS.md` 已写实测值）。

产物（都进 `figures/` / `results/`，连跑两次逐字节一致）：
`fig_traj_default.{png,pdf,svg}`（sha256 `6A754C1B…` / `6ACB3DD6…` / `7102A7AC…`）、
`fig_traj_preview_default.{png,pdf,svg}`（`658135E9…` / `96B17764…` / `BEC9684E…`）、
`traj_default.json` + `traj_default_{missile,segments,target}.csv`。
⚠ **图2 也用本轮一起刷新了**（删脚注星号），所以 `fig_bg_plane_default.*` 相对 HEAD 有改动 ——
如果你之后要拿"图1/图2 与 HEAD 逐字节相同"当无泄漏证据，记得这一条已经**不再成立**（图1 仍然成立）。

**21.8 复验收口：缺陷 A（图例多挂一格实线）**

* `fig3-verifier` 在 task-7 复验了修复后的出图（结论针对 `figures.py = 8FEB7849…`）：inset 四工况
  137.45×361.28 / 137.15×361.28 / 148.82×200.64 / 146.33×97.73 px（@300 dpi）全 ≥20 且落在主轴框内、
  inset 与主轴 y 刻度的**墨迹**交集 0 px²、注记两两重叠 0 对、`Glyph ... missing` 0 条、
  SVG 里 `**` 与 `⚠` 均 0 处、数值断言与 task-5 锁值逐位相同、6 个产物两跑一致；
  并且它的测试断言被证明**真会红**（阈值变异 2 红 + 产品侧变异 1 红，红的正是线型那条）。
  唯一没过的一条：**trunc 工况图例 12/13**。
* 缺陷 A 的现象：`t_crank=28`（crank 没转完）时图例里同时有「转入crank」的**实线**把手与
  「crank 没转完（被下一条指令截断）」的虚线段，而图上唯一的 crank 段是**橙虚线** ——
  多出来的那格广告了图上不存在的图元。修法：`add_traj_header()` 给分段挂图例代理时，
  `s.truncated` 为真就 `continue`（与 `plot_traj_segments()` 按"label 首次出现"选线型保持一致）；
  截断那层意思仍由 `LEGEND_TRAJ_TRUNC` 那格（同色 + `TRAJ_TRUNC_LS`）解释。
* 这条为什么漏过原有测试：`test_every_legend_entry_has_a_visible_artist` 只比 **label**，
  而图例把手是画在**另一张画布**上的代理线 ⇒「实线 转入crank」格配上「虚线 转入crank」段照样通过。
  现在 `_snapshot` 抓 `legend_dash`（把手的真实线型，走 `_unscaled_dash_pattern`，不能用有损的
  `get_linestyle()`），该测试对分段类条目**同时比 label 与线型**。
* **变异检验**（脚本 `.tmp_test/mutate_legend_gap.py`）：把那行就地改成 `if False:` ⇒ 退出码 1、
  报错原文 `trunc：图例「转入crank」的线型是 ()，图上同名图元却是 [(4, 2)]`；
  按字节还原后 sha256 一致、复跑通过 ⇒ 新断言不是"永远为真"。
* 收口后的状态：`figures.py = 349f12a1…`（task-7 的结论针对 `8FEB7849…`，这处改动**在复验之后**，
  由上面的变异检验 + 交付队友的一次窄复验兜底）；**6 个成品图哈希一个字节未变**（默认是命中工况，
  图例本来就有实线那格），全量仍 **335 项**。

**22. 早期图归档到垃圾站（2026-10-01）**

* 用户要求"早期图打包到单独的垃圾站避免干扰"：把 `figures/` 里 **23 个重建前（最后一个提交都在
  2026-09-25）的图**整体 `git mv` 到 `archive/figures-legacy/`。`figures/` 现在只剩 **12 个**成品：
  图1 `fig_isotime_plane_default.*`、图2 `fig_bg_plane_default.*`、图3 `fig_traj_default.*` 与
  `fig_traj_preview_default.*`（各 png/pdf/svg）。
* 动手**之前**先查了两件事：① 这些图出自**已删除**的 `pro`/`flash` 引擎与已删脚本
  （`scripts/pipeline.py`、`workflow.py`、`workflow_web.py`、`make_missile_bc_overlay.py`），
  **没有任何脚本能把它们重出来**；② `tests/` 里**零引用**这些文件名，也没有"`figures/` 目录里
  应当有哪些文件"的断言（只有 `figures` **模块**的用法）—— 所以移动不会让任何测试变红（全量 335 仍全绿）。
* 归档目录里有 `README.md`：分组清单、为什么重不出来、`git mv` 恢复与 `git rm -r` 彻底删除的命令。
  用 `git mv` 而不是删除，历史可追溯（`git log --follow`、`git show 28f7c7c:figures/…`）。
* **没动**的东西：`results/missile_shot_crossplot.json`、`results/workflow_clitest.json`、
  `results/workflow_demo.json` 这些旧 manifest 里仍写着**移动前**的 `figures/...` 路径
  （例如 crossplot 12 处、clitest/demo 各 8 处）—— 它们同样是重建前的历史记录，用户本轮只要求收拾早期图。
* 文档同步：`AGENTS.md` 的仓库结构段现在写明 `figures/` 只剩三张图的成品、早期图在
  `archive/figures-legacy/`（非交付物）。
### 23. 图1/图2 出图口径：点径统一 + 基准弹涂绿（2026-10-01）

用户四句原话（按序）：① "图2红点大小和文字大小不一致的问题修一下"；② "然后用红色的反色绿色给选中的基准弹"；
③ "图1也应用绿色"；④ "绿色标记之后就不需要外面的环了,去掉"。

#### 23.1 先量再改：不一致的根在图2 按 ΔV 缩放气泡
| | 图1 | 图2（改前） |
| --- | --- | --- |
| 点直径 | **统一 9.44 pt**（`POINT_SIZE = 70`） | **9.44~24.46 pt**（面积 70~470 ∝ 理想 ΔV，`BG_BUBBLE`） |
| 标签字号 | 9.5 pt（`LBL_FONTSIZE`） | 9.5 pt（**两图本来就相同**） |
| 基准弹标记 | 空心环面积 `POINT_SIZE*4.2` ⇒ 直径 19.34 pt（恒为点的 2.05 倍） | 环**固定** 681.5 pt² ⇒ 直径 29.46 pt，罩在 PL-12 自己 17.14 pt 的气泡上（比例 1.72，且每型不同） |

⇒ 图1 的"点 9.44 pt / 字高 9.5 pt"是协调的；图2 最大点到 24.46 pt 而字不动，就是用户看到的"不一致"。
口径由用户三选一拍了"**统一成图1 的点大小**"（三选一里的推荐项；另两项是"只收窄跨度"与"字号跟着点缩放"）。

#### 23.2 落地的改动
* `figures.BASE_COLOR = "#388E3C"`（Material Green 700，与 `POINT_COLOR = "#D32F2F"` Red 700 同明度同族）
  = "红的反色绿"。图1 `plot_points(highlight=<key>)` 与图2 `_bg_bubbles()` **共用**这一个常量。
* 图1：`plot_points()` 新增 `highlight` 参数（按 `p.key` 命中即涂绿，其余红）；`plot_plane()` 传
  `str(getattr(highlight, "key", "") or "")`。
* 图2：`_bg_bubbles()` 的 `s=sizes` 改成 `s=POINT_SIZE`（不再按 ΔV 缩放），颜色按 key 逐点给。
* **空心环整体删除**：删 `figures.mark_highlight()` 函数（图1 的调用点一并删）；删图2 那段
  `s=BG_BUBBLE[1]*1.45` 的环。图例里的"基准弹"条目从空心环改成**绿色实心点**（与图上一致）。
* 删 `BG_BUBBLE` / `LEGEND_BG_BUBBLE`，新增 `LEGEND_BG_POINTS = "弹池 {n} 型"`；
  `add_bg_header()` 新增 `n_points` 参数（图例报真实池规模，不再写死 11）。
* **点与标签同色**（用户 2026-10-01 追加"标签也绿"，见 §23.6）：选中态的点、它自己的标签文字、
  以及图例里那一条的文字都涂 `BASE_COLOR`；其余弹名仍是 `LBL_COLOR`（红字），字号一个都没动。
  颜色规则收敛成一条 `_pick_color(key, highlight, normal)`，图1/图2 共用。

#### 23.3 顺带堵掉一个"点径统一之后才露头"的不可复现（重要）
点径一统一，matplotlib 的 SVG 后端就把散点标记折叠成**一条共享 `<defs>` 路径**，id 是 `_make_id()`
造的 `C0_0_<hash>`；而 `_make_id()` 的盐是 `rcParams['svg.hashsalt']`，**默认 `uuid4()`**
（`backend_svg.py:495-502`）—— 实测**同一个进程里连跑两次 id 也不同**。`normalize_svg_ids()` 的旧正则
（"字母 + ≥5 位十六进制"）匹配不到中间的 `_`，于是 `tests/test_figures_bg.py` 的字节复现用例红字
`.svg 不可复现`。图1 一直没暴露，是因为它没有共享标记路径。

修法两层：① `figures.SVG_HASH_SALT = "missile-sim"`，在 `setup_style()` 里钉给 `svg.hashsalt`；
② `normalize_svg_ids()` 的正则加上"可选 `_十六进制` 段"。
影响面实测（在一份**未归一化**的 SVG 上对比新旧正则）：图2 **只多命中 1 个**（`C0_0_…`），
`figure_1` / `DejaVuSans-*` / `MicrosoftYaHei-*` 等 335 种稳定 id 一律不碰。

#### 23.4 产物、测试与自检
* 重出：`figures/fig_bg_plane_default.{png,pdf,svg}` + `figures/fig_isotime_plane_default.{png,pdf,svg}`
  （图1 的绿点与图例、图2 的点径/颜色/图例）。**图3 三格式一个字节都没动**（`git status --porcelain` 为证），
  说明钉盐值 + 新正则对没受影响的图是零影响。
* 图1 PNG 像素对比（Pillow）：差异 5862 px（0.0710%），全部落在坐标区（红点抗锯齿）+ 图例；
  尺寸不变 3542×2332。SVG 差异 +36/−30 行，其中 `#388e3c` 出现 2 处（图上的点 + 图例条目），
  `C0_0_` 残留 0（已被归一化）。
* 新增 2 项测试，判据都落在 **artist** 上（不看像素）：
  `test_figure_labels.py::test_baseline_point_is_green_and_the_hollow_ring_is_gone`
  （`len(ax.collections) == 1` ⇒ 环确实没了；`to_rgba` 逐点比色；不给 `highlight` 时全红）、
  `test_figures_bg.py::test_bg_points_are_uniform_and_the_baseline_is_green`
  （尺寸集合 `== {POINT_SIZE}`、恰好一处绿、`ax.collections` 只有 1 个）。
  `test_figures_bg.py` 里原断言 `"气泡大小" in svg` 改成 `"弹池 11 型" in svg` + `"气泡大小" not in svg`。
* 全量自检 **337 / 0 / 337**（261.5 s；比上一轮多这 2 项）。

#### 23.5 遗留
* 图1 manifest 仍缺 `figure` 键（图2/图3 有）—— 不影响复现，纯粹键不齐。
* `-k traj_plot` 的"crank 没转完"条目只比线型不比颜色（非阻塞）。
* 副标题里那句"基准弹 PL-12"仍是整行深灰文本（没拆成多色）—— 它是题头，不是弹的标签。
#### 23.6 追改：标签也绿（2026-10-01，用户追加）

用户第五句："标签也绿"。落地：

* 新增 `figures._pick_color(key, highlight, normal)` —— **颜色规则只有一条**：命中基准弹的 key 就
  `BASE_COLOR`，否则用常规色。四处调用：图1 的点/标签、图2 的点/标签。
* 新增 `figures._green_legend_text(leg, highlight)` —— 图例里"基准弹"那一条的**文字**也涂绿
  （`add_header()` / `add_bg_header()` 各调一次，按 `t.get_text() == highlight` 命中）。
* 产物：图1/图2 的 SVGs 里 `#388e3c` 各出现 **4 次** = 图上的点 + 它的标签文字 + 图例的点 + 图例的文字；
  **图3 三格式仍然一个字节都没动**（`git status --porcelain` 为证）。
* 测试：新增 2 项（`test_figure_labels.py::test_legend_text_of_the_baseline_is_green_too`、
  `test_figures_bg.py::test_legend_text_of_the_baseline_is_green_too`），并把原有两项扩展成"点与标签
  逐点比色"（基准弹那一个必须绿，其余必须是 `POINT_COLOR` / `LBL_COLOR`；不给 highlight 时全不算绿）。
  全量自检 **339 / 0 / 339**。
* 一处 nudge：改 `add_header()` 图例那段时手滑删掉过一个换行（`if extra:` 与下一行粘在一起），
  `python -c "import missile_sim.figures"` 当场报错、已修回 —— 这也说明**改完立刻 import 一次**值得。

## 24. 开源化准备与合规审计（2026-10-01，分支 `opensource`，worktree `E:\导弹包线图-oss`）

**用户拍板**：公开代码，但**排除 `vendor/` 与游戏数据**（README 说明需自备内核）。
完整交付见 **`docs/OPENSOURCE-READINESS.md`**（结论先行 / 审计表 / 实测证据 / 12 条决策清单）。

### 24.1 合规审计（逐项实测，全部 `try/finally` 复原，未提交任何删除）
* **最高风险 = `vendor/wt-missile/` 的**游戏数据**：`wt_missile.py` 已于 2026-10-01 **归本项目作者**（随仓公开、由本仓库 LICENSE 覆盖），要排除的只有下面这一项
  + `inputs/resources/2.59.0.28/` 的 **168 份 War Thunder `.blk`**（Gaijin）。
  **移出即全局崩**：`-k pool_mapping` 17→8、`-k solver_api` 17→4、`-k figures_repro` 7→**0**；
  只留源码、只删 `inputs/` 一样崩（17→8 / 17→5 / 7→0）—— 内核**逐文件 SHA-256 校验**游戏数据。
* 全量自检在内核缺席时：**189 通过 / 150 失败 / 339**（3.1 s）。
* **完全不需要内核的 50 项**（可进托管 CI）：`-k flightpath` 37、`-k form_dirty` 12、`-k printed_text` 1。
* **移出后 0 项变红**的四项：`results/reference_fig.png`（用户提供的第三方参考图，权利不明）、
  `archive/figures-legacy/**`（23 图 + README，不可复现）、`results/runs/full_pro/**`（2.6 MB，旧 `pro` 架构）、
  `results/pro_cache.json`（1.1 MB，同族）、`scripts/**`（13 个 `E:\WT` 工具）。
  `git grep` 取证：`src/` 与 `tests/` 对它们**零引用**（唯一命中 `test_figures_bg.py:69` 是函数名里的
  "reference figure"，假命中）。
* **密钥扫描 0 命中**；真正要清的是**绝对路径**：`results/runs/full_pro/cases.json` 里 1824 行
  `E:\WT\wt-missile-backend-runtime-1.0.1`、3 个 `native_compare*.json` 里的 `C:\Users\MK\AppData\...`、
  `VENDOR.md:7` 的 `D:\Download\...`（只留文件名）。

### 24.2 历史取证（`.gitignore` 管不住历史）
* vendor 只在 **1 个提交**（`dc960b8`），但那 1 个提交在**全部 11 个分支的共同祖先链**上。
* 历史 1213 个对象 / **28.19 MB**；路径含 `vendor/` 的 **103 个对象 / 0.38 MB（未压缩 1.75 MB）**，
  其 `.blk` 唯一 blob **93 个**（168 个文件里 75 份逐字节重复）→ **体积小 ≠ 不侵权**。
* ⚠ **本仓库是三个 worktree 共享同一个对象库**（`E:\导弹包线图` + `-3d` + `-oss`，
  `git-common-dir` = `E:/导弹包线图/.git`）⇒ **绝不能在这里重写历史**，会打断 Lead 与 3d 队友；
  路线 B 必须**先 clone 再重写**。

### 24.3 两条落地路线（都本机真跑过）
* **路线 A（推荐）：干净导出 + 单次初始提交。** `git archive HEAD` → 解压 → 删排除集 → `git init` →
  一次提交。实测：提交数 **1**、跟踪文件 **144**、工作树 **6.54 MB**、`.git` **3.79 MiB**、
  `vendor` 只剩 `VENDOR.md`、`.blk` **0 条**、CI 子集 37/12/1 全绿。
* **路线 B：clone 后 `filter-branch` 重写。** ⚠ **第一版失败**：只做
  `reflog expire + gc --prune=now` 而**没删 `refs/original/*`** —— 历史里仍有 **104 个 vendor 对象 /
  93 个 `.blk`**、`.git` 只从 28.45 → 22.14 MB，**看着像重写了，其实一个对象都没删**。
  **补上 `git update-ref -d refs/original/refs/heads/opensource` 后**：`.git` 28.45 → **21.49 MB**、
  历史 `.blk` **0 条**、vendor 只剩 2 条（树 + `VENDOR.md`）、提交数仍 **79**（哈希全变）。
* 另一条实测口径：`git clone <worktree>` **只带当前分支**（`refs/heads/opensource`），
  其余 10 个分支只在 `refs/remotes/origin/*` 里 —— 所以**别用 `--mirror` 推送**，
  否则另外 10 个分支的 vendor 历史照样出去。

### 24.4 本次落库的文件
`docs/OPENSOURCE-READINESS.md`（主交付）、`CONTRIBUTING.md`、`pyproject.toml`
（`>=3.12,<3.15` / `numpy>=2.5.2,<3` / `matplotlib>=3.11,<4`；**刻意不写 license 字段**）、
`vendor/README.md`（**公开**：自备内核的落位与 SHA-256 校验）、`.github/workflows/ci.yml`（草稿）、
`.gitignore`（删掉 `!results/runs/full_pro/` 白名单 + 加"开源排除集"段）、`LICENSE`（**占位，不是许可证**）、
`README.md`（标题后加"本仓库不含内核"提示 + 文末新增 §9 免责声明 / 数据来源 / 不含哪些东西）。
**未提交任何删除** —— 所有"建议移出"只在文档里给方案。

### 24.5 待用户拍板（阻塞公开）
许可类型（**推荐 MIT**：本项目价值在文档与可复现产物，且 MIT 覆盖整仓（外壳 + 随仓内核）最干净；
不推荐 GPL-3.0）／ 历史走 A 还是 B ／ 是否先私有 ／ `reference_fig.png` 与旧架构遗留是否移出。


## 2026-10-01 · 三张图 3D 化可行性（分支 `3d-viz` / worktree `E:\导弹包线图-3d`，基线 `73eb2bc`）

**用户拍板**：图3 **真 3D** + WebUI 里**可交互旋转（离线 WebGL）**；图1/图2 **不 3D 化**。
完整报告见 `docs/FIG3D-FEASIBILITY.md`，可重跑证据见 `spikes/fig3d/`，smoke 用
`python tests\run_tests.py -k fig3d`（11 项，约 1 s，**不跑求解器**）。

### 结论（哪张图值得 3D）

* **图3 值得，而且是唯一值得的**：它的第三维是**真实空间高度**（本工况弹从 10000 m 爬到
  12847 m），俯视图把这一维**完全压掉**；`v03`（三维+地面投影）比 2D 对照只多 **0.5 s / +141 kB PNG**。
* **图1 / 图2 不值得**：第三维是 `t_hit`，**等时线 + 颜色条已经完整表达**它。实测图1 3D 曲面
  527 kB vs 2D 209 kB（+152%），信息量没变；图2 更差 —— β≈2500~3100 与 γ≈0~180 **差 1~2 个量级**，
  真实跨度做 `box_aspect` 后 γ 被压成一条线，不做就几何失真。
* **plotly 否决**：能装（有网），但包 **56.12 MB**、`plotly.min.js` **4 815 814 B（4.8 MB）**，
  且 7.1.0 的 `graph_objects` 顶层 `import narwhals.stable.v1` ⇒ `--no-deps` 装完当场 ImportError。
  与"免安装分发（134.4 MB 解压 / 54.8 MB zip）+ 尽量不引新依赖"两条约束同时冲突。

### 实测（本机 Python 3.14.7 / matplotlib 3.11.1 / numpy 2.5.2 / Node 24 / Edge）

* **mplot3d 三格式字节可复现：13/13 变体全绿** —— 同进程连出两次、**跨进程各出一次**
  （`PYTHONHASHSEED` 一个随机一个 `1`、间隔 1.2 s、输出目录不同）逐字节一致。
  ⚠ 这条**推翻了"mplot3d 的 z 排序容易不稳"的先验担忧**：画家算法的 `zsort` 深度是**纯浮点函数**，
  真正随机的只有 matplotlib 的 SVG id 盐 `svg.hashsalt`，而它**已被 `figures.setup_style()` 钉死**。
  但要有条件地引用：只在"图元不交叠/不相切"的场景成立。
* **最坏变体是"逐点着色"**：`scatter` 按时间着色 3300 点 ⇒ PDF **783 kB** / SVG **690 kB**，
  是 2D 对照的 **22 倍**。**要做 3D 就用分段线，别用逐点 scatter。**
* **现有 `plot_traj_preview_3d` 已具备可复现性**：`v13` 两方位角 160 dpi ⇒ 272.7 kB PNG /
  2.80 s，与仓库里已交付的 `figures/fig_traj_preview_default.png`（245 810 B）同量级。
* **手写 WebGL2 交互查看器（零第三方 JS）**：模板 **17 662 B**（JS 346 行）、单文件离线版
  **44 418 B**、`slim` 数据 **30 421 B**（320 点；`full` 319 906 B）；顶点装配 **1.055 ms/场**、
  每帧矩阵 **1.280 µs**、GPU 缓冲 47.9 kB。**无头 Edge + SwiftShader 实测渲染出正确画面**
  （`spikes/fig3d/out/c/shot.png`）。`file://` 单文件版**零请求**、零 CDN。
* ⚠ **帧率没量到**：无头 `--virtual-time-budget` 下 `requestAnimationFrame` 走虚拟时钟，
  量出来是假数字 —— 所以文档里**不给帧率**，只给"渲染成功"+CPU 量测。

### 落地口径（真做要改什么）

* **静态 3D**：`figures.py` 新增 `plot_traj_3d()`（复用 `_box_aspect`/`TRAJ_COLORS`/`save_formats`）+
  `workflow.TrajRequest.view` + `cli --traj-view` + `webui_static` 表单开关 + **新文件**
  `tests/test_fig3d_plot.py`（3D 专用物化判据），≈ **2~3 人日**。
* **交互视图**：`webui_static/viewer3d.{html,js}`（把 spike 的查看器拆开）+ `GET /api/traj/<tag>.json`
  （形状见文档 §3.3）+ 唯一的坐标口径出口 `traj_to_viewer_payload()` + 新
  `tests/test_webui_viewer3d.py`（含"JS 里不许出现 `http(s)://`"这条离线判据），≈ **2.5~3 人日**。
* 现有 8 项物化判据 / `-k figures_repro` / `-k printed_text` / `make_dist.py` **都不需要改**；
  3D 的注记可读性要**新增**一组 3D 判据（现有 23 项全是 2D 像素几何，管不到 3D 遮挡）。

### 本阶段的边界

只新增 `docs/FIG3D-FEASIBILITY.md`、`spikes/fig3d/**`、`tests/test_fig3d_spike.py`；
**没有**改动 `src/**`、`figures/**`、`results/**`、`tests/test_traj*.py`、`tests/test_webui*.py`。
入库产物 **0.52 MB**（其余 117 个可重建文件由 `spikes/fig3d/clean_out.py` 清掉）。

## 3D 可行性补遗：拖动"跟手" + 亮色 chrome（2026-10-01，`3d-viz` 分支）

用户在侦察阶段追加了**两条硬要求**（"优先级高于好看"），已并入同一份
`docs/FIG3D-FEASIBILITY.md`（**没有**为此另开分支或提交）：

1. **水平拖动必须跟手**（抓住物体转），点名的反例是 jari-aerospace 那种"拖右而对象左走"的镜像手感。
2. **视图 chrome 走亮色**（WebUI 已是近白底 `#fff`/`#f7f8f9`、深灰字 `#1f2933`、1 px 描边 `#d8dce1`）；
   viewer 不许自带深色外壳，嵌入态背景透明交给宿主。

### 结论与实测（本机 Node 24 复算 + 无头 Edge 交叉印证）

* 跟手的号是 **`cam.az += dx·AZ_PER_PX`**（`AZ_PER_PX = EL_PER_PX = 0.008 rad/px`，
  `EL_LIMIT = 1.45 rad` 夹极点）。拖 `Δx = +200 px` 时**物体正对观察者的近侧表面**同向走
  **+105.3 px**；把符号写反（旧实现）就是 **−105.3 px** —— 那就是镜像。
  真浏览器口径（`?dragtest=200`，canvas 1254×707）给 +93.1 px，同向同结论。
* **判据只能落在"近侧表面"上**（`center + dir·0.2R`，投影恰在视野中心）。第一版拿
  "发射点/命中点/最高点"当见证，得到 `horizontal_ok=1/3`，差点把正确的实现改坏 ——
  原因是环绕相机绕 `center` 的**竖直轴**转，离轴远的特征位移方向会反向
  （相机在 39 km 外，轨道中心**后方**的点仍在相机前方、仍能投出来，只是 `u/w` 换了号）。
  实测：发射点 `dx@+20px = −57.2`、命中点 `−26.0`，而近侧表面 `+19.1`。
  → 这条已写进 `tests/test_fig3d_spike.py`（`test_drag_follows_the_cursor` /
  `test_drag_sign_is_not_mirrored`），**符号被改反就变红**。
* "要反向就改一个符号"是**真的**：方位角只有 3 处赋值（拖动/自动旋转/复位），
  拖动那处就是 `applyDrag()` 里的一行，用例会数出正好 3 处。
* 亮色化只动 chrome，**不动数据配色**（`figures.TRAJ_COLORS` 原色保留，浅色在近白底上不可辨）。
  命中点必须从白改成近黑 `[0.09,0.11,0.14]`，否则白底上直接消失。

### 顺手修掉的两个真 bug（"不报错、只是难看"那一类）

1. `[THEME.x]` 把颜色**多包了一层数组** → `Float32Array` 收到数组变 `NaN` → 所有节点渲染成**黑球**。
2. 点精灵尺寸多乘了一个 `radius` → **每个点都被 clamp 到 32 px**，亮底上糊成一排黑圆。
   正确口径 `px = d_m·(H/2)/(depth·tan(fovy/2))`，uniform 只给 `(H/2)/tan(fovy/2)`，
   点尺寸参数单位=**米**。

这两条都只靠"真浏览器截图"才看得出来（Node 复算与 Python 测试全绿）——再次印证 AGENTS.md
"前端的**行为/观感**在这套测试里跑不起来"那条缺口。另外顺手修了 `坐标轴` 按钮
（之前是死开关，且三轴 origin 画在相机背后、屏幕上根本看不见）。

### ⚠ 操作事故与教训（本会话真中过，已清理）

用 `[System.IO.File]::WriteAllText("docs\...")` 这种**相对路径**的 .NET 调用时，
pwsh 的 `cd` **不会**同步 .NET 的 `CurrentDirectory`，结果在
`E:\导弹包线图\docs\FIG3D-FEASIBILITY.md` 建了一个 3 字节垃圾文件（主工作树 `webui` 分支）。
确认它 `git status` 是 `??`、且全历史无此路径后**已删除**，主工作树现已干净。
→ 教训：脚本里访问文件**一律用绝对路径**；`[System.IO.File]` / `[math]::` 这类 .NET 调用尤其。

### 落地工作量（已把这两条算进去）

* 方案 A（图3 静态 mplot3d）：**≈ 2~3 人日**（不变 —— 拖动与配色不属于静态图）。
* 方案 B（WebUI 内嵌手写 WebGL）：**≈ 3.3~3.9 人日**（原 2.5~3，新增
  拖动方向+默认视角 0.3 d、自检一并搬运 0.3 d、亮色 CSS+透明底 0.4 d）。
* `spikes/fig3d/` 入库产物 ≈ **1.3 MB**（查看器模板 28 629 B / 单文件版 55 385 B /
  亮色截图 47 700 B）；`-k fig3d` **16 项 0.9 s** 全绿。


### 24. WebUI 拆分：内嵌 PAGE → 静态资源（2026-10-01，`webui` 分支）

**用户拍板（本轮开头定案）**：三条线并行 —— (1) `webui` 分支**专注 WebUI**（主线）；(2) `3d-viz` 分支
探究图3 真 3D + 交互（允许子代理/团队）；(3) `opensource` 分支做开源前准备。
范围决策：**3D = 只做图3 的真 3D + WebUI 里离线 WebGL 交互**（图1/图2 不 3D 化）；
**开源 = 公开代码但排除 `vendor/` 与游戏数据**；WebUI 优先级 = **先拆静态资源 → 输入体验 → 结果展示**。

**分支拓扑**：`图3`(HEAD `73eb2bc`) → 新出 `webui`（`E:\导弹包线图`）、`3d-viz`（`E:\导弹包线图-3d`）、
`opensource`（`E:\导弹包线图-oss`），三个工作树各自独立，互不影响；**没有合并且没有推远端**。

**做的事**：`webui.py` 里那个 440 行的 `PAGE` raw string 拆成
`src/missile_sim/webui_static/{index.html,app.css,app.js}`：
* `index.html` 保留服务端占位符（`__SOLVER__` / `__FIELDROWS__` …）**并内联 boot 数据**
  （`var DEFAULTS = …, PRESETS = …, META = …;`）⇒ 前端不用多打一次请求，首屏即完整；
  `app.css` / `app.js` 是**纯静态**的（`app.js` 里一个占位符都没有）；
* 新增路由 `GET /static/<name>`，白名单 `WEB_STATIC_ASSETS = {app.css, app.js}`（fail-closed）；
  `read_page_file()` 只负责"按名字读"（basename 化挡穿越 + 只认 `.html/.css/.js`），
  **"读得到"与"发得出去"分两层判** —— `index.html` 故意不在白名单里（它带着没渲染的占位符）。
* `render_page()` 末尾加 `TOKEN_RE` 兜底：渲染完还剩 `__XXX__` 就**当场 500**，不让页面静默残缺。

**证据（这一轮唯一的强判据）**：拆前先把 `render_page()` 的产物存成基准，拆后按"两处替换"重建期望页面，
**逐字节一致 ✓**。数字：响应体 **36350 → 15507 字节**；`webui.py` **2203 → 1780 行**；
`app.css` 2626 B、`app.js` 15678 B、`index.html` 3162 B；全量自检 **345 / 0 / 345**（175.3 s，339 → +6）。

**顺带抓到的真 bug**：`index.html` 里有一行**手写**的用户可见提示写着 `**不解算**` ——
浏览器上原样显示星号（D5 那一族的漏网：`-k printed_text` 只扫 Python 侧的字符串
（`Field.hint` / CLI help），页面里手写的提示没人兜）。已修，并补页面侧判据
`test_webui_page_shows_no_markdown_stars`（渲染出的 HTML 里 `**` 必须为 0；`app.js` 的 `//` 注释豁免）。

**两个必须记住的连带**：
1. **测试契约换了新的"更强判据"**：`test_form_dirty.py::test_front_end_reports_dirty_fields` 原来是
   `inspect.getsource(webui)` 找 `DIRTY.add`，现在扫 `webui.read_page_file("app.js")` ——
   也就是**浏览器真正收到的那份 JS**（改错文件、放错目录都会被抓住）。
   `test_webui_index_200` 里"前端轮询 `/progress/`"、`test_webui_traj.py` 里
   `r.figure === "both"` 那两条同理（JS 搬走了，就得扫 app.js）。
2. **`read_page_file` 的白名单一开始把 `render_page` 自己也挡了**（它要读 `index.html`）——
   这正是"能读 ≠ 能发"的教训：白名单要判在**路由那一层**，不要判在读取函数里。

**小坑两枚**（都已修）：测试运行器的 `pytest.raises` **不吃异常元组**（`(ValueError, FileNotFoundError)`
会 `AttributeError: 'tuple' object has no attribute '__name__'`）；boot 数据行里只有 `DEFAULTS` 带 `var`
（`var DEFAULTS = X, PRESETS = Y, META = Z;`），断言别写成 `var PRESETS`。

**下一步**：WebUI 主线还剩用户点的两项 —— **输入体验**（字段分组/校验反馈/预置想定的可用性）与
**结果展示增强**；两条并行线（`3d-viz` / `opensource`）的结论回来后再合并决策。

### 25. WebUI 第 2 刀：输入体验 + 亮色主题 + 3D 拖动方向（2026-10-01，`webui` 分支）

**用户这一轮的三条要求**（原话）：
1. 在 `webui` 分支专注 WebUI 修改；
2. **背景改成亮色**，参考 https://jari-aerospace.top/ ；
3. 那家"3D 视图的左右拖动旋转方向反直觉了，我们改一下"（= 我们的要做成跟手的）。

#### 25.1 失败响应按字段归位（`field_errors`）

- 现状问题：`/api/single` / `/api/submit` 的 400 只给 `errors: ["…"]`（纯字符串），前端只知道"有个错"，
  不知道该给哪个输入框标红。用户看到的是"消息条里一句话"，得自己对号入座。
- 做法：**新增**（不改旧键）`field_errors: {字段名: [消息, …]}`，`errors` 原样保留。
  `webui.field_errors()` 做归位：**先认 label**（长 label 优先），认不出**再认字段名**且必须**词边界**；
  7 处失败响应统一走 `fail_payload()`，`_fail()` 也改用它。
- 规则放在**服务端**：只写一份、Python 侧可测；前端只按返回的键上色（`markFieldErrors`：
  红框 + 框下红字 + 滚到第一个出错的框并 `focus()`）。

**⚠ 两个坑（都踩了，第二个是真教训）**：
1. **`re.S` 事故**：我用 `\{"ok": False, "errors": (\[.*?\])\}, 400` + `re.S` 批量改那批返回值，
   `.` 跨行 ⇒ 惰性匹配从更早的一条 `, 500` 响应一路吞到后面的 `, 400`，**把两个 500 分支连根删掉**
   （当场 `SyntaxError`，好在是编译期就炸）。改成 `\[^\]*\]`（不可能跨过内部列表的 `]`）+ 命中数断言，
   `git checkout --` 回滚重打。**教训：多行正则替换要么禁 `re.S`，要么先把候选匹配打印出来看。**
2. **别拿自己编的样例消息写规则**：我编的消息是 `载机初始高度 必须是数字…`（名字在**开头**），
   于是规则写成"label 命中 **或** `text.startswith(name)`"。Python 侧测试**全绿**（用的就是我编的样例）。
   真浏览器一跑：消息条有字、**红框不出现** —— 真消息是
   `想定解析失败：range_m 需要数字，收到 'abc'`（字段名在**句子中间**，走的是 `Scene` 解析那条路，
   不是表单层的 `_num_of` 那条路）。修成"label 优先 → 否则名字**词边界**出现在任意位置"。
   顺带发现同族坑：`alt_m` 是 `target_alt_m` 的后缀 ⇒ 必须 `(?<![0-9A-Za-z_])name(?![0-9A-Za-z_])`，
   否则敌机高度的错会算到载机高度头上（**归错字段比不归更糟**：会让人去改一个没问题的框）。
   两条都写进了判据（真消息 + 词边界），见 `tests/test_webui.py`。

#### 25.2 记住上次手改的输入

- `localStorage` 键 `missile-sim:form`，存 `collect()` 的整份表单（含 `_dirty` = 手改字段清单）。
  加载时 `restoreLocal()` **只回填手改过的字段**，并照存下来的 `_dirty` 重新标 dirty
  （程序性赋值不算手改 ⇒ 必须补标，否则恢复出来的值会被后端当成预置）；全是默认值就不打扰。
  按钮「忘记上次输入」（`#forget`）清掉记忆。语义与后端一致：手改 = 覆盖预置。

#### 25.3 亮色主题

- 用户定的产品要求，实现就是 `app.css` 顶部那 6+4 个变量：`--bg:#f5f6f8` / `--card:#ffffff` /
  `--field:#ffffff` / `--line:#d8dce1` / `--fg:#1f2933` / `--dim:#5b6672` / `--accent:#1f6feb` …
- ⚠ **`color-scheme:light` 不能漏**：它决定**表单控件与滚动条**的配色。只刷背景的话，
  `<select>` 下拉和滚动条还是深色（难看又难查）。判据 `test_webui_theme_is_light` 钉住它，
  并且明确断言旧深色底 `#0f1419` **不该还在** CSS 里（主题是产品决定，不能被悄悄改回去）。
- 参考站（`jari-aerospace.top`）实测是**近白底 + 深灰字 + 1px 浅灰描边**的工程工具风，
  几乎没有强调色；我们保留了一个蓝色 accent 给主按钮/焦点，其余照白底走。
  （该站 `web_fetch` 被拦 —— 域名解析到非公网地址；改用浏览器打开看的。）

#### 25.4 3D 拖动方向（用户点名要改的）

- 参考站那家的 3D 视图"左右拖动旋转方向反直觉" ⇒ 我们的**必须跟手**：光标下的点跟着光标走
  （水平拖右 ⇒ 物体右转；垂直拖下 ⇒ 上缘向观察者倾倒）。已作为**硬需求**发给 3D 线
  （`fig3d-scout`，`3d-viz` 分支）：要求在 spike 里给可复现自检（拖动 Δx=+200 px ⇒
  某个可识别特征在**屏幕坐标**里也向 +x 移动），把数值写进 `docs/FIG3D-FEASIBILITY.md`，
  并写清"要反向就改哪一个符号"。另外 3D 的 chrome 也要跟亮色（背景浅色/透明，轨迹沿用现有配色）。

#### 25.5 实测与证据（2026-10-01）

- `-k webui` **42 / 0 / 42**（39 → +3）。全量自检见本轮提交信息。
- **真浏览器实测**（`browser-skill` + 本机 Edge，`python -m missile_sim.webui --port 8799`）：
  1. 填入非法值 `abc` 点「单工况试算」→ `/api/single` 返回 **400**（console 无 JS 异常），
     截图里**发射距离那个框是红框**，框下红字 `想定解析失败：range_m 需要数字，收到 'abc'` ✓；
  2. **新开一个标签页**（无该页表单状态、同源共享 localStorage）打开首页 ⇒ 发射距离仍是 `abc`
     ⇒ 证明是 `localStorage` 生效，不是浏览器自带的表单恢复 ✓；
  3. 亮色主题在同一张截图里验到（白底卡片 + 蓝主按钮 + 白输入框）✓。
- ⚠ `browser-skill` 的操作坑：`bsk fill --value -1000` 会被底层 CLI 当成参数
  （`unexpected argument '-1'`）⇒ 用不以 `-` 开头的非法值（`abc`）绕开；`browser_inspect html`
  的 `target` 选择器不生效（返回整个文档），**DOM 级证据要靠 `observe` 的可访问性树或用 `ref`**。
- ⚠ `bsk` 守护进程在本机**不能由客户端自动拉起**（Job Object 限制）—— 先用后台任务跑
  `bsk daemon start --foreground`，再用 `browser_session` 开会话（并显式给 `browser` 实例 id）。

#### 25.6 下一步

- WebUI 第 3 项「结果展示增强」（用户排的优先级第 3）：等图、结果表、多任务面板还没动。
- 3D 线在 `3d-viz` 分支跑（静态 mplot3d 字节可复现 + 离线 WebGL 查看器 + 跟手拖动）；
  开源线在 `opensource` 分支已备好文档与必备文件，**等用户拍板**：vendor 处置 / 历史走 A(干净单提交) 还是 B(重写) /
  是否先私有 / 许可类型（推荐 MIT）。

### 26. 参考站 StatShark 实测 + 3D 线交付复核（2026-10-01）

#### 26.1 StatShark（用户推荐的第二个参考站）

用户原话："前端还可以参考 statshark，这是一个优良示范"。**没靠印象，实地拆了**：

* **`web_fetch` 拿不到它**（"resolves to a non-public IP"，与 `jari-aerospace.top` 同病），
  但**本机 pwsh 直连可以**：`Invoke-WebRequest https://statshark.net/` → 200 / 72 520 B，
  样式表 `styles-2SGSLABJ.css` **213 174 B**。抓到的 CSS 存在 `.tmp_test/statshark.css`（已 gitignore）。
* **技术指纹**：Angular Material（`:root` 里 `--mat-*` 变量 **2769** 条）、Roboto + Material Icons +
  Font Awesome、**Plotly** 画图（DOM 里 `plotly-logomark`）、Cloudflare、Vite 风格 `chunk-*.js` 分包、
  自建 API（`/api/missiles/versions` ⇒ 它也把数据层 API 化了，和 `docs/SOLVER-API.md` 同思路）。
* **主色 = Angular Material 默认主题**：`#3f51b5`（indigo）+ `#ff4081`（pink A200）。
  高频色里 `#f44336` / `#6ab0de` / `#007bff` 是图表与库色，`#fafafa` / `#303030` 是亮/暗面。
  ⇒ **这个"优良示范"自己并没有花哨配色**，克制才是它好看的原因（印证我们亮色定案的方向）。
* **圆角主要 4~5 px**、阴影走 Material elevation、字号由 Material token 给（label 16/24、tooltip 12）。
* **它的"导弹计算器"页和我们是同一领域**：左窄**可折叠**参数栏（`chevron_left`）+ 右宽 Plotly 图；
  表单 label 在上、值大一号、浅填充 + 底边线；**预置工况是按钮网格**（短程红外 / 远程主雷达 /
  机动性 / 自定义预设 —— 实测点"短程（红外）"会把 `发射高度` 3000 → 200）；
  `图表设置` 面板给 `过滤 Y 轴元素` / `动画速度` / `显示飞行标签` / `标签元素`；
  整站 i18n（实测中文）；页脚 服务条款/隐私声明/常见问题/更新日志/法律声明/Discord；404 也是卡片。
* **结论（写进 `docs/WEBUI.md` §7）**：**抄信息组织与交互，不抄技术栈与体积**。
  照抄 6 条（两栏布局 / 预置按钮网格 / 图表设置 / 图3 回放动画 / 页脚 IA / 错误页卡片）；
  想清楚 2 条（i18n 先做"文案集中"、密集表格先量宽度）；**坚决不抄** 3 条
  （前端框架、Plotly、外部字体图标）—— 我们是"纯标准库 + 离线免安装"，引框架等于送掉优势
  （3D 线已实测：手写 WebGL 只要 28 KB，而它一个 CSS 就 213 KB）。
* 版权口径：只做**阅读参考**，不抄它的代码/文案/色值；**它的截图不进仓库**（讨论截图只留本机）。

#### 26.2 3D 线（`fig3d-scout` / task-9）交付复核 —— Lead 独立验过，不是听汇报

* 提交 `d05ad72`（分支 `3d-viz`，基线 `73eb2bc`）：23 files / **+7364 / −0**；
  `git show --stat` 与用户台账一致。
* **范围核对**：`git diff --name-only HEAD~1 HEAD -- src figures results` → **空** ⇒
  它确实没碰求解器、出图代码与正式产物（只加 `docs/`、`spikes/`、新增测试与 `NOTES.md` 追加）。
* **独立跑它的判据**：`python tests\run_tests.py -k fig3d` → **16 / 0 / 16，1.3 s** ✓（与我之前 349 项全量是两条独立路径）。
* **事故核对**：它自报用 `[System.IO.File]::WriteAllText` 相对路径时，pwsh 的 `cd` 不同步 .NET 的
  `CurrentDirectory`，在**主工作区**建过一个 3 字节垃圾文件。我查了 `git status --porcelain` = 空、
  `docs\` 下 9 个文件无异常 ⇒ 已清干净 ✓。**教训（值得全队记）**：脚本里一律**绝对路径**。
* 交付结论（摘要）：只有**图3 值得 3D**（第三维是真空间高度）；静态走 mplot3d（零新依赖、
  13 变体 × 3 格式同进程/跨进程 sha256 全一致）；交互走**手写 WebGL2**（模板 28 629 B、JS 512 行）；
  图1/图2 不做（第三维已被等时线+色条表达完，3D 只增遮挡：图1 PNG 209 → 527 kB）；plotly 否决。
* 两条硬要求已并入（我发的那两条）：拖动**跟手**（`Δx=+200px` ⇒ 见证点同向 +105.3 px；镜像写法 −105.3 px；
  真浏览器 `?dragtest=200` 复算 +93.1 px；符号唯一位置在 `applyDrag()` 的 `cam.az += dx * AZ_PER_PX`，
  测试数"方位角赋值恰好 3 处"）；chrome **亮色**（`#f7f8f9`/`#1f2933`/`#d8dce1` + `?bg=transparent`），
  数据配色不动、命中点白改近黑。
* ⚠ 它的两条诚实限制：**帧率没有可信数字**（无头下 rAF 走虚拟时钟），字节复现只在**本机**验过。
* ⚠ 一条差点改坏正确实现的坑（记档）：第一版拖动自检拿"发射点/命中点/最高点"当见证，
  得到 `horizontal_ok=1/3`，差点把正确实现改成镜像。原因：环绕相机绕 `center` 竖直轴转，
  **离轴很远的特征本来就可能反向**（发射点 `dx@+20px = −57.2`）。认"物体正对观察者的近侧表面"才对。

#### 26.3 本轮踩到的操作坑（工具层）

* **PowerShell 没有 heredoc**：`git commit -F - <<'EOF'` 直接 `ParserError`，而且**整段脚本在解析期就失败**，
  `git add` 都不会执行（我因此白跑一次）。提交消息一律写文件 + `git commit -F <file>`。
* PowerShell 里提交中文消息要 `git -c i18n.commitEncoding=utf-8 commit -F <file>`；
  更稳的做法是**用 Python 写消息文件**（`Path.write_text(..., encoding="utf-8")`），
  免得 pwsh 的重定向把编码写坏。
* `browser_inspect network` 的 `url` 子串过滤对列表不总生效（我用 `.css` 过滤仍返回尾部同一批），
  **想拿样式表就用 pwsh 直连下载**（更快更全）；`bsk fill --value -1000` 会被 CLI 当参数，
  填非法值用不以 `-` 开头的（如 `abc`）。

#### 26.4 下一步

* WebUI 第 3 阶段（结果展示增强）已按 StatShark 实测拆成 6 条具体项（见 `docs/WEBUI.md` §7.3）。
* 3D 线待用户拍板 3 条（并存还是替换 / 入口形态 / 抽稀档位），其余 5 条在 `docs/FIG3D-FEASIBILITY.md` §7。
* 开源线：`opensource` 分支已提交许可对比页与三项拍板记录（`84a7dbb`）；⚠ 该分支**尚缺** WebUI 两笔提交
  与 3D 线，公开前必须先合并。

### 27. 图3 静态图的判据陷阱：inset 与文字在 SVG 里长什么样（2026-10-01）

背景：用户拍板"图3 静态图改 3D 替换俯视图 + 去掉左下角放大图"，我（Lead）先写**独立验收器**
（`.tmp_test/verify_task11_static3d.py`、`.tmp_test/verify_task12_viewer.py`，都在 gitignore 里），
并且**先拿"改造前"的旧图验验收器本身** —— 否则很容易做出一个恒 PASS/恒 FAIL 的橡皮图章。

#### 27.1 两个陷阱（第一版验收器全中）

1. **别用 `clipPath` 找 inset**：我按 `<clipPath id="p…"><rect …>` 匹配，命中 **0** 个。
   原因是 `figures.normalize_svg_ids()` 把 id 重编过，实际形如 `<clipPath id="id_00010">`。
   判据于是**静默失效**（"没找到小坐标区"被我当成"没有 inset"）。
   **正确的物证是每个 axes 自带的白色底板**：每个 axes 都以
   `<g id="patch_K"><path d="M x1 y1 L x2 y1 L x2 y2 L x1 y2 z" style="fill: #ffffff"/>` 开头，
   那个矩形就是它的绘图区。解析它 ⇒ 旧图实测：
   `axes_1` 67.4~814.5 x 140.5~395.6 pt（满宽主图）、
   **`axes_2` 33.0 x 86.7 pt（只占画布宽 4.0%，落在左上/左下之间）⇒ 就是那个"放大"图**、
   `axes_3` 67.4~814.5 x 438.6~574.4 pt（下面还有一个满宽面板）。
   判据：宽度 < 45% 画布的 axes = 疑似 inset。
2. **文字不是 `<text>`**：这份 SVG 里 `<text>` **0 次**、`<!--` 76 次、`<use>` 1571 次
   —— matplotlib 把字形落成路径，**原文只留在 `<!-- … -->` 注释里**。
   所以"图里有没有写『开机前/开机后』"可以查注释判定（判据有效），但
   **"注释会不会压字/出界"注释里看不出来 —— 视觉必须目视 PNG**。验收器里已写明这一点。

#### 27.2 验收器的正确用法（验"它的声明"，不是验"我的想象"）

* 参数按**被验者的自报**填：`--expect-text 开机前 --expect-text 开机后 --forbid-text 放大 --min-colors N`，
  它把每条判据的**命中次数**都打出来，对不上就 FAIL 并给退出码 1。
* 反向自检过一次：把判据放宽（`--max-small-rects 99 --min-colors 1`）必须 PASS ——
  这样才能排除"恒 FAIL 的假验收器"。
* ⚠ 这条经验适用于**所有**"用产物结构反推行为"的判据（SVG/PDF/CSV/manifest）：
  先证明**判据在旧产物上会失败**，再相信它在新产物上的通过。

#### 27.3 当前状态（等两条线回报）

* task-11（`fig3d-scout` / `3d-viz`）：图3 改 3D + 去 inset + 过开机距离换色。
* task-12（`webui-fig3` / `3d-viewer` / 工作树 `E:\导弹包线图-viewer`）：WebUI 内嵌可拖拽 3D + 800 点。
* 两条线落地后：Lead 跑这两个验收器 + 真浏览器拖一次（跟手）+ 独立跑测试，再统一改 `AGENTS.md`。

## 28. 三条线收口、内核归属转移、本轮真缺陷清单（2026-10-01 深夜）

### 28.1 五条分支的落点（**未合并、未推送**；本仓库没有远端）
| 分支 | 工作树 | HEAD | 一句话 |
| --- | --- | --- | --- |
| `webui` | `E:\导弹包线图` | `7e105ea` → `a614f3b` | 首页拆静态资源 / 亮色主题 / 输入体验 / StatShark 实测；之后是 Lead 的 §13.5–§13.9 决策与合并方案 |
| `3d-viewer` | `E:\导弹包线图-viewer` | `1e2005b` | 内嵌可拖拽 3D 查看器（`traj3d.py` + `webui_static/viewer3d.*`），见 `docs/WEBUI.md` §8 |
| `3d-viz` | `E:\导弹包线图-3d` | `eec4ccc` | 图3 静态图主视图改 3D 斜视、删左下角 inset、导弹过 `t_beam` 换色 |
| `bg3d` | `E:\导弹包线图-bg3d` | `705b529` → `b8a874e` | β–γ–ΔV 三维图 + 等时面 spike；结论"先不做图4"，见 `docs/FIG-BG3D-FEASIBILITY.md` |
| `opensource` | `E:\导弹包线图-oss` | `84a7dbb` → `190f815` | 内核归属转移后改口径 + 游戏数据取消跟踪 + 测试降级 |

合并顺序与冲突预判见 `docs/RESTART-PLAN.md` §13.7；图4 的结论与四条待拍板见 §13.8；内核归属的影响见 §13.9。

### 28.2 Lead 外部验收的数字（判据一律**自己重跑**，不信作者自报）
* `3d-viz`：`-k traj_plot` **18/18**、`-k traj` **67/67**、`-k figures_repro` **7/7**、全量 **350/350**（252.6 s）。
  物化验器 `.tmp_test/verify_task11_static3d.py`：**0 个小尺寸 axes**（inset 真的删了，不是"看不见"）、
  `#8e44ad` 在、文字"开机前/开机后/发射/命中/参考方向"都在、三格式字节与自报**逐个相同**。
* `3d-viewer`：`-k viewer3d` 12/12、`-k webui` 55/55、全量 **361/361**；真指针拖拽 + 像素 + 白名单 + 入口形态。
* `bg3d`：`-k bg3d_spike` **26/26**（1.5 s）、全量 **381/381**（196.1 s）。
* `opensource`：数据在位 **339/0/339**（221.6 s）；游戏数据缺席 **190 通过 / 149 跳过 / 0 失败**（退出码 0，3.8 s）；
  同状态 `--strict` 那 149 项记失败（退出码 1）。`git ls-files` 里 `inputs/` 与 `.blk` 命中 **0**、`wt_missile.py` **1**。

### 28.3 本轮抓到的真缺陷（两类：**合并后才炸** 与 **静默通过**）
1. **交互查看器与静态图配色会不一致（合并后）**：`traj3d.palette()` 只认 `TRAJ_MISSILE_COLOR`，
   **没有** task-11 新加的 `TRAJ_MISSILE2_COLOR`，而 `tests/test_viewer3d.py:158` 钉的正是前者
   ⇒ 合并后静态图是「深灰 → 紫」、查看器还是「浅灰 → 深灰」，**那条测试照样绿**。合并时必改（§13.7）。
2. **"第三根轴只有一个斜率"偏强**：补二次项后残差 RMS **0.5519 → 0.0582 s**，曲率端点抬升中位
   **1.5449 s = 该列 ΔV 效应的 9.16%**，**459/459 列同号**。准确口径是"一阶近乎线性 + 可测曲率"。
3. **作者自己的 RMS 写法错**：`rms_resid_lin_s` 第一版写成 `mean|resid|`（0.474 vs 真值 0.5519），
   被"必须与 `dv_linearity` 一致到 1e-12"的断言照出来 —— **对账断言比自证断言值钱**。
4. **入库的 `crossSame.json` 一度是过期证据**（加色条之前算的 sha256），重生成后三份记录才自洽。
5. **`iso_report.json` 的 `n_run/n_cached` 恒为 0**，与同块 `stats{runs:4699, cache:350}`、`n_cases=5049`
   矛盾；根因 `bg3d.scan_from_record()` 不带新计数，而判据只读 `scan_fine.json` ⇒ 抓不到（task-17 在修）。
6. **文档数字错**：三角形 21820 → **22820**；柱面散布 16.36~17.99 → **16.7822/17.5925 s = 75.52/79.16%**；
   "22 项约 9 s" → **26 项 / 1.6 s**；"160 dpi" → 实为 **300 dpi**（3 处）。
7. **`scan_quick.json` 记的 0.0247 s 是热缓存**（冷跑 4.31 s）⇒ 记录里补 `n_run`/`n_cached`，
   三档 126/0、840/84、4699/350 且 `n_run + n_cached == n_cases`。
8. **墙钟有两套测量**：并发时 120.9 s vs 清缓存冷跑 81.85 s（17.9/16.2 ms 每工况）
   ⇒ **跨负载比墙钟没有意义**，要比就比"耗时倍数 ≈ 工况数倍数"，它在两次测量里都成立。

### 28.4 内核归属转移（用户 2026-10-01 明确："内核现在是我的了"）
* 原话链条：「内核没声明许可证我就没打包只开了一套 API」→ 对方回「无所谓」→ 用户「内核现在是我的了」。
* **"内核无许可、不能公开"整条失效** ⇒ 内核随仓分发、由本仓 `LICENSE` 覆盖；公开仓 13 处
  "无许可的第三方内核"口径已改正（`opensource` `190f815`，先加 §0「归属转移」再改正文，历史分析不抹掉）。
* **但 War Thunder 游戏数据仍排除**：168 份 `.blk` + `presets.json`/`manifest.json` 共 170 个文件
  `git rm -r --cached`（工作树保留）+ `.gitignore` 只忽略 `inputs/`（**不要**再忽略内核本身，
  否则 `git add -A` 反而漏掉内核源码）；测试/CI 数据缺席时**降级**：横幅 + 逐条 SKIP + 三个计数分开报 +
  按模块汇总，`--strict` 关掉降级让那 149 项记失败（self-hosted 全量 job 用它，免得"跳过"被读成"全绿"）。
* **`LICENSE` 候选排序的论据作废**："MIT 与无许可内核兼容性最好 / GPL 会逼出整体分发合规问题"不再成立
  （整仓只有一个权利人）—— 三个候选回到"要不要防闭源 + 专利条款"的纯取舍；用户**仍未拍板**。
* **Lead 自查漏项**（记一笔）：上一轮开源审计只查了"必需文件在不在 + 密钥/绝对路径"，
  **没查"该排除的排没排"** ⇒ 公开仓里实际躺着内核本体与 168 份游戏数据，而文档写着"不公开、自备"。
  以后凡文档写了排除集，就要**逐条到 `git ls-files` 里核**。

### 28.5 教训（可复用的判据与纪律）
* **脚本改文本文件一律 `read_bytes`/`write_bytes` 或显式 `newline=""`**：Python 文本模式在 Windows 会把
  整份文件翻成 CRLF。本轮真中：把 `tests/test_traj_plot.py`（585 行）写成全 CRLF，靠提交前
  `--stat` vs `-w --stat`（1255 vs 411）才发现。`edit` 工具不动行尾。
* **降级探针要串行**：降级验证的做法是"把 `inputs/` 改名让开"，若与别人的全量取证并发，那次全量会
  得到 190/149 而不是 339/0（本轮真踩到，探针是我的，已即时还原）。
* **`-w --stat` 的差值要能解释**：纯重构/重排缩进会跨 hunk 匹配掉（`figures.py` 1064 vs 1040 = 24 行），
  而行尾被整体重写会给出更大的差值（1255 vs 411）—— 两者的数量级不同，可据此分诊。
* **对抗验证的价值**：task-14 对 11 条声明逐条独立复算**全部成立**（还自跑 36 工况真解算），
  却仍挖出 7 条问题，其中一条是**结论口径过强** —— 没有对抗验证，"只有一个斜率"就写进文档了。
* **验证者的写范围要说死**：`results/cache/fast.json` 被验证方越界重写过一次（gitignored、tracked 无改动），
  此后它的报告首节都自报边界；共享工作区里"只读"必须显式写成"不许写 `results/`"。
* **色条"同色"只在 α 混合前成立**：面是 `α=0.45` 的混合色，色条标的是**层级次序**，不是像素级配色。
* **"能不能画"与"值不值得画"是两个问题**：后者要用"第三根轴的独立信息量"回答（这里是一个斜率 + 9% 曲率）。
* **图3 竖直轴放大约 7.2 倍**（`TRAJ_VIEW_ALT_GAIN=0.45`）已写进图内脚注；绝对高度读右侧面板。

### 28.6 追加：task-17 收尾（`bg3d` `cda568e`）与两条新教训（2026-10-02 凌晨）

* task-16 补验挖到的真缺陷已修：`bg3d.scan_from_record()` 漏带 `n_run`/`n_cached`，导致入库的
  `iso_report.json` 里 `scan.n_run = n_cached = 0` 与同块 `stats{runs:4699, cache:350}`、
  `n_cases=5049` 矛盾。修法：从 `rec["summary"]` 读回，**dataclass 默认值从 `0` 改成 `None`**
  （"没记"不许伪装成"真跑了 0 个"）；判据 26 → **30**：三档往返 `n_run + n_cached == n_cases`、
  故意 `pop` 字段必须是 `None` 且 `None + None` 要抛异常、入库 `scan` 块自洽、
  `in_repo` 与 `git ls-files` 双向对齐（5/17）。修后实测 `4699 + 350 = 5049` ✓。
* **"判据有牙"要做变异实验才算数**：作者把 `bg3d.py` **逐字节**换回缺陷版（并先断言替身里确有
  那个函数、默认值确为 0），两条往返判据当场 FAIL 并打出矛盾本体 —— 然后逐字节还原、核对 sha256。
  ⚠ 它第一次的替身是用 `git show | Set-Content -NoNewline` 造的，**文件被写坏**（函数整个消失），
  那时判据是 `AttributeError` 失败 —— **那种失败什么都没证明**。造变异体要用 `write_bytes` 逐字节
  替换，并**先断言变异体具备预期特征**，否则你在验的是一条坏掉的实验装置。
* **耗时类数字不锁死**：同机同代码，提面耗时在不同负载下读到 101 / 111.5 / 143.2 ms（12 次实测
  103.2~215.1，中位 121.8）⇒ 文档只承诺"量级 0.10~0.22 s + 分布 + **别跨机器比**"，不写"当前值"
  —— 写死某一组，下次重跑文档就过期。墙钟同理（§28.3 第 8 条）。
* **"160 dpi" 的根因值得记**：`figures.setup_style()` 里 `rcParams["savefig.dpi"] = 160` 是**画布默认**，
  而 `save_formats` 对 PNG 显式传 `SAVE_DPI = 300` 把它覆盖了 —— 只读 rcParam 会得出错数
  （实测 9 张 PNG 的 pHYs 块都是 299.9994 dpi）。
* 最终态：`bg3d` `cda568e`，`-k bg3d_spike` **30/30**、全量 **385/385**（241.4 s，Lead 独立重跑）。
## 29. 五分支合并（1–3/5 已完成）+ 查看器配色静默不一致 + 参考站求解器逆向解析（2026-10-02）

### 29.1 合并序列进展（`webui` 为集成分支；**全部本地，未推送、无远端**）

| 步骤 | 提交 | 并入分支 | 规模 | 冲突 |
| --- | --- | --- | --- | --- |
| 1/5 | `64367f7` | `3d-viewer` | 11 文件 +1868/−8 | 零 |
| 2/5 | `b51c485` | `3d-viz` | 30 文件 +15697/−7429 | **只有 `NOTES.md`** |
| 3/5 | `b40cda7` | `bg3d` | 20 文件 +3520/−0 | 零 |
| 4/5 | 本文 | `AGENTS.md` 计数 + 本节 | — | — |
| 5/5 | 待做 | `webui` → `opensource` | — | 待定 |

* 步骤 2 的 `NOTES.md` 冲突按**三方字节并集**解（时间序 `base + theirs + ours`）：
  base 122,968 + theirs（`3d-viz`）8,404 + ours 29,248 = **160,620 B**；
  验过"原文件是结果的前缀"+ 无冲突标记 + `git diff --cached --numstat` = `107 0`（纯追加）。
  ⚠ 这个文件是**每次合并的固定碰撞点**（两边都在尾部追加），`spikes/fig3d/append_notes.py` 就是配套工具。
* 步骤 3 那 12 个 `in_repo: false` 的大件（SVG/PDF/几何 JSON）**不在 git 里**，所以合到 `webui` 的 worktree
  只会有 5 张入库 PNG —— 这正是 `test_in_repo_flags_match_git_and_cover_five_of_seventeen` 断言的 5/17。
* 合并后判据（**402 项全绿**，162.9 s）：`-k viewer3d` 12、`-k webui` 55、`-k traj_plot` 18、
  `-k traj` 68（比合并前多 1 项，来自 `test_fig3d_spike.py` 里名字含 `traj` 的用例）、
  `-k figures_repro` 7、`-k bg3d_spike` 30。`AGENTS.md` 的计数与命令清单已同步（349→402、42→55、
  23→18、71→68，并补 `-k viewer3d` / `-k bg3d_spike` 两行）。

### 29.2 抓到一个"静默通过的不一致"（已修：提交 `0d430a6`）

task-11 让**静态图**的导弹变成两个色相（开机前 `TRAJ_MISSILE_COLOR` `#4d4d4d`、
开机后 `TRAJ_MISSILE2_COLOR` `#8e44ad`），但**交互查看器** `traj3d.palette()` 里写的是
`"missile_after": figures.TRAJ_MISSILE_COLOR`，而 `tests/test_viewer3d.py` 钉的**也正是这个旧值**。
⇒ 两条线各自自洽、各自全绿，**合并后静态图是「深灰→紫」而查看器还是「浅灰→深灰」，
判据却照样通过**。修法三件：`traj3d.palette()` 改用 `TRAJ_MISSILE2_COLOR`（`source` 串同步）、
`tests/test_viewer3d.py` 改断言**并补关系判据**（`TRAJ_MISSILE2_COLOR != TRAJ_MISSILE_COLOR`
且 `after != before`）、`docs/WEBUI.md` §8.2 那段"同色相派生、静态图本来一个颜色"的**过时口径**改写。
实测：`palette()` → before `#9a9a9a` / after `#8e44ad`。

⚠ **教训（可迁移）**：判据只钉"等于某个常量"是不够的 —— 常量一起被改错/被旧值钉住时判据会**静默通过**；
凡是"两边各存一份公共量、只在合并时才相遇"的地方（`figures.py` 的颜色表、`webui.WEB_STATIC_ASSETS`
白名单、`docs/SOLVER-API.md` 的契约名）都要有一条第**关系**判据。
另外：本项的修复**只能排在步骤 2 之后**（`TRAJ_MISSILE2_COLOR` 是 `3d-viz` 带进来的），
`docs/RESTART-PLAN.md` §13.7 原先把它写成步骤 1 的事项，已更正。

### 29.3 参考站 `neothunderism.pages.dev` 的求解器 = 服务端 Python（详见 `docs/REFERENCE-NEOTHUNDERISM.md`）

* 它**不是** JS/WASM：前端只发界面，计算在一台 Oracle VM 上跑服务端 Python
  （站点 `config.js` 的 `apiBase` 指过去）；算核是 War Thunder `2.59.0.34` 客户端原生 6DOF 弹道的
  **逐指令 float32 位序复原**，源码公开在 GitHub `Leo-TY-H/wt-em-calc`（线上 commit 与读到的主干树 SHA 一致）。
* 与我们**同方法**（float32 6DOF 复原），且它的**步长调度可逐帧对齐**（主步 1/48 s、刚体子步 1/96 s、
  轨迹 16 Hz 落盘，线上响应 `model.step_s` 与之一致）；大气常数与本仓 `AGENTS.md` 记录的 DagorEngine
  那组**同源**（独立重算相对差 ≤ 4e-7）⇒ 可以做**逐帧**对拍，不是只能比终值。
* 新增两条**逐弹**事实（可交叉核对我方 blk）：`propNavMult` ≡ 它的 `omega_gain` —— **PL-12 = 6.0、AIM-9L = 4.0**，
  **不是**社区口径的全局 4.0；近炸半径也逐弹不同（PL-12 = 10 m、AIM-9L = 5 m）。
* 它的**自认边界**：整场次未对实机验证；`.34` 核心混用 `.38` 共享算术；只支持匀速直飞目标
  ⇒ 我们图3 的机动想定**对不上**，只能对拍直飞。
* ⚠ **许可**：该仓 `/license` 404、无 LICENSE 文件 ⇒ **默认保留全部权利**。
  可以引用**事实与数值并给 URL**、可以当黑箱调 API；**不可**搬代码/公式文本、不可做代码级翻译、
  不可打包它的 profile JSON 或游戏资产。游戏数据（`launch-profiles/*.json` 等）权属归 Gaijin，
  与我方已在用 `E:\WT` 派生数据同类，**不必再多引一层**。
* 完整取证（60 KB 报告 + 65 个原始文件）在 `.tmp_test/neo-solver/`（gitignored，不进公开仓）。

### 29.4 下一步

1. **步骤 5/5**：`opensource` ← `webui`，然后在有/无游戏数据两种条件下各跑一遍全量，
   重做密钥/绝对路径扫描，并同步 `README.md` / `CONTRIBUTING.md` / `docs/OPENSOURCE-READINESS.md`
   / `.github/workflows/ci.yml` 里那些**合并后会过期**的降级数字。
2. 仍待用户拍板：图4 是否建（Lead 建议不建）、`LICENSE` 选择、OSS 待办 #5–#12、`requires-python` 区间。
## 30. 合并 5/5 完成：`webui` → `opensource` + 降级数字重测（2026-10-02）

### 30.1 合并本身

* 提交 **`ac3198d`**（父 `190f815` + `5536bfb`）：把 `webui` 并进 `opensource`。
  `opensource` 是从 `73eb2bc` 切出的，**天生不含** WebUI 与 3D 两条线，这一步才把它们补回来。
* **唯一冲突 `NOTES.md`**（追加型文件的老毛病）：ours = `opensource` 的 §24 合规审计（54 行），
  theirs = `webui` 的「三张图 3D 化可行性」+ §28 + §29（493 行）。按时间序 ours→theirs 拼接、只删 3 行标记（38 B）。
  并集恒等式核对：`127,789 + 166,139 − 122,968 = 170,960` ✓；合并后 `--numstat` = `493 0`（纯追加），
  `--stat` == `-w --stat`。⚠ `README.md` 两侧都改过却**自动合并**成功（无冲突）。
* **删除面保持**（这是这次合最需要盯的）：`vendor/wt-missile/inputs` 跟踪命中 **0**、`*.blk` **0**、
  `wt_missile.py` **1** —— 即 `opensource` 侧取消跟踪的那 168 份游戏数据**没有**被并回来；
  合并后跟踪文件 **236** 个，`traj3d.py` / `bg3d.py` / `viewer3d.*` / `test_viewer3d.py` /
  `test_bg3d_spike.py` / `docs/FIG3D-FEASIBILITY.md` / `docs/FIG-BG3D-FEASIBILITY.md` /
  `docs/REFERENCE-NEOTHUNDERISM.md` / `tests/_vendor_data.py` / `ci.yml` / `LICENSE` **逐个在位**。

### 30.2 三遍重测（Lead 亲自跑，权威数字）

| 条件 | 命令 | 结果 | 用时 | 退出码 |
| --- | --- | --- | --- | --- |
| 游戏数据在位 | `python tests\run_tests.py` | **402 通过 / 0 失败 / 402** | 156.5 s | 0 |
| 数据缺席（默认降级） | `python tests\run_tests.py` | **254 通过 / 148 跳过 / 0 失败 / 402** | 8.1 s | **0** |
| 数据缺席 + `--strict` | `python tests\run_tests.py --strict` | **254 通过 / 148 失败 / 402** | 9.0 s | **1** |

* 全量基线 **339 → 402**（合并带进 3d-viewer 12、3d-viz、bg3d 30、WebUI 55 等新判据）。
* 无数据时的跳过明细（按模块）：`test_bg` 32、`test_traj_plot` 14、`test_report` 12、`test_solver_api` 12、
  `test_webui_traj` 11、`test_bg_scan` 10、`test_pool_mapping` 9、`test_figures_bg` 8、`test_figures_repro` 7、
  `test_traj` 7、`test_grid_axis` 6、`test_figure_labels` 5、`test_webui_bg` 5、`test_bg_pipeline` 4、
  `test_bg3d_spike` 2、`test_targets` 2、`test_webui` 2（合计 148）。
  ⚠ 注意 `test_webui*` 三组也进了跳过名单 —— **WebUI 测试大多也需要内核数据**，
  所以"WebUI 是纯前端、不碰内核"这个印象是错的。
* 降级纪律（本轮照做）：先**清 `results/cache/*.json`** 再移动数据目录，否则旧缓存会让"数据缺席"也照常通过；
  探针**串行**做、`try/finally` 立刻还原；还原后复查 `vendor/wt-missile/inputs` **168 份 `.blk`** 在位、
  `solver.profile('cn_pl12')` 返回 `lockDistance = 16000.0`、弹池 11 型、`-k pool_mapping` 17/17。
  ⚠ 复核这类探针时**别用外部弹名**（`PL-12`）：内核要的是原生名（`cn_pl12`），写错会得到
  `Unsupported missile` 而看起来像"数据没还原"。用 `python -m missile_sim --list-missiles` 更稳。

### 30.3 顺带修掉的一处可误读文案

降级横幅原文 `…；放回：vendor/README.md（把游戏数据放回 …）` 会被读成"把数据放回到 `vendor/README.md`"，
实意是"放回**方法见** `vendor/README.md`"。已在 `tests/run_tests.py` 改成 `放回方法见 vendor/README.md`，
并同步所有出现处（含断言与 `ci.yml`）。

### 30.4 密钥 / 绝对路径重扫（合并后，2026-10-02）

工具 `.tmp_test/scan_oss_after_merge.py`（只读 git 跟踪集：`git ls-files -z` 逐文件按字节扫，跳过 39 个二进制）。
**必须为 0 的项全部为 0**：`vendor/wt-missile/inputs/**` 0、`*.blk` 0、`.env` 0、`.pem/.key/.p12/.pfx` 0、
文件名含 `credential`/`secret` 0。

| 模式 | 命中 | 判定 |
| --- | --- | --- |
| `sk-` / `ghp_` / `github_pat_` / `AKIA` | **0** | ✅ 无真密钥 |
| `Bearer` / `Authorization:` | **0** | ✅ |
| `password` / `passwd` / `api_key` / `private_key` 等字面词 | 4（全在 `docs/OPENSOURCE-READINESS.md`） | ✅ 那是审计文档在**描述**搜了哪些模式，不是凭据 |
| 长 base64/hex（≥40） | 2172 | ✅ SVG 内嵌的 PNG（`iVBORw0KGgo…`）+ `results/*.json` 里的内核文件 SHA-256 |
| `C:\Users\MK` | 7 | ⚠ **真实残留 3 处**：`results/native_compare{,_PL-12,_all}.json` 第 2 行（已登记为 OSS 待办 #7）；另 4 处是审计文档与历史记录里的**文字提及** |
| `E:\WT` | 1897 | ✅ 外部游戏数据目录的引用（文档 / `scripts/**`），已登记为待办 #9（doc-only） |
| `E:\导弹包线图*` | 38 | ✅ 全在文档与 `spikes/fig3d/README.md` —— **没有**跑进 `src/**` 或 `tests/**` |

✅ **合并本身没有带进新的泄漏面**：本轮新增的 `traj3d.py` / `bg3d.py` / `webui_static/viewer3d.*` /
`spikes/{fig3d,bg3d}/**` / `docs/REFERENCE-NEOTHUNDERISM.md` / `tests/test_viewer3d.py` /
`tests/test_bg3d_spike.py` 里**都没有** `C:\Users\…` 或本仓绝对路径。

### 30.5 ⚠ 工具教训：`NOTES.md` **只能**用字节脚本改，别用 `edit`/`write` 工具

本轮真踩到：用 `edit` 工具在 `NOTES.md` 里插入一段（本想只加 20 行），结果**整个文件被归一成 CRLF** ——
`CR=LF=2100`，原有的 **389 个孤立 CR + 1087 个孤立 LF 全被抹平**，`git diff --stat` 立刻显示
**3022 行变动（1546/1476）**，而 `git diff -w --stat` 只有 `70 +`（内容其实没坏）。
修法：`git checkout -- NOTES.md` 回到 HEAD，再用 `open('rb')`→拼接→`open('wb')` 重做，
复原后 `lone-CR=389` 保住、`--stat` == `-w --stat`（`50 +` 纯追加）。

**规则**：`NOTES.md` 是**混行尾**文件（既有 CRLF 也有孤立 CR/LF），任何"读成文本再写回"的工具都会
统一行尾 ⇒ 只能用字节脚本改；`git diff --stat` 与 `git diff -w --stat` 必须**逐次比对**，
不一致就是行尾被改写了（唯一合法例外是纯缩进调整）。
✅ 反过来，仓库里其余常改文件是**纯行尾**的（`README.md` 纯 CRLF；`CONTRIBUTING.md` /
`vendor/README.md` / `docs/**` / `.github/workflows/ci.yml` / `tests/**` 纯 LF，0 个孤立 CR），
对它们用 `edit` 工具是安全的 —— 危险只集中在 `NOTES.md` 这一个文件上。

### 30.6 交付状态

* 五条分支的合并（§13.7 的 1–5 步）**已完成**，集成分支 = `opensource`（合并后 HEAD `ac3198d`）。
* **仍未推送**（仓库无远端）；`premerge-*` 五个安全标签是回滚路径，不要删。
* 降级数字在 `README.md` / `CONTRIBUTING.md` / `vendor/README.md` / `docs/OPENSOURCE-READINESS.md` /
  `ci.yml` 里已按 §30.2 同步（`NOTES.md` 与 `docs/RESTART-PLAN.md` 的历史数字**不抹**，本节就是新基准）。
* 仍待用户拍板：图4 是否建（Lead 建议不建）、`LICENSE` 选择、OSS 待办 #5–#12、`requires-python` 区间。
## 31. 许可拍板 = MIT（2026-10-02）+ 图4 立项 + 字体许可灰色地带

### 31.1 MIT 落地（用户拍板，Lead 执行并实测）

拍板结果：**MIT**（三选一的对比与推荐理由保留在 `docs/OSS-LICENSE.md` 与
`docs/OPENSOURCE-READINESS.md` §5，作为决策依据）。改了三处代码/元数据 + 两份文档状态：

| 位置 | 改动 | 验证 |
| --- | --- | --- |
| `LICENSE` | 换成 MIT **完整标准英文正文**（`Copyright (c) 2026 MK`） | 文件 1,070 B；不再是占位 |
| `pyproject.toml` | `license = "MIT"` + `license-files = ["LICENSE"]`（PEP 639 写法） | `pip wheel . --no-deps` **退出码 0**；METADATA 实测 `License-Expression: MIT`、`License-File: LICENSE`，且 `LICENSE` 进 `dist-info/licenses/` |
| `README.md` §9.5 | 从"尚未拍板/占位"改成 MIT + 覆盖范围 + **覆盖不到的三类东西** | 见下 |
| `CONTRIBUTING.md` §7 | 改成"按 MIT 分发 + 只提交你自己有权再许可的内容" | — |
| `docs/OSS-LICENSE.md` / `docs/OPENSOURCE-READINESS.md` | 状态类表述改为"已拍板 MIT"（对比表保留为决策依据） | 由并行子代理同步 |

⚠ 本机**没装 setuptools**：`pip wheel` 之所以能成功，是因为走了**构建隔离**（临时装最新 setuptools）。
所以 `license = "MIT"` 这种 PEP 639 写法在本仓库的真实构建路径上是安全的；若有人用
`--no-build-isolation` 且本地 setuptools < 77，才会失败（与本次改动无关的老问题）。

### 31.2 新发现：许可覆盖不到的第三方项（已写进 README §9.5）

1. **War Thunder 游戏数据**（`vendor/wt-missile/inputs/`，168 份 `.blk`）：权利归 Gaijin，不随仓库分发
   —— 与选哪个许可无关（老口径）。
2. **分发包里的中文字体** `NotoSansSC-subset.ttf`：Noto Sans SC 是 **OFL**，分发时要一并带上它的许可；
   注意仓库跟踪集里**没有**字体文件（`make_dist.py` 是从 `C:\Windows\Fonts\NotoSansSC-VF.ttf` 生成子集）。
3. **`results/reference_fig.png`**：外部参考图，授权待确认 —— 公开前要么移出公开集、要么向原作者取得授权。
4. ⚠ **字形轮廓灰色地带（本轮新查到的）**：`figures.py` 的字体链是
   `["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC", "DejaVu Sans"]`，而 matplotlib
   **默认把文字转成路径**（`svg.fonttype` 默认 `path`）⇒ 已入库的 `figures/*.svg|pdf` 里内嵌了
   系统字体（本机实际命中 **Microsoft YaHei**）的**字形轮廓**（SVG 里有 `MicrosoftYaHei-98` 这类
   `<path id>`）。多数商业字体的 EULA 允许"嵌入文档供查看/打印"，但**公开仓库长期分发**含其字形轮廓的
   矢量产物属**灰色地带**。干净做法：改用 **OFL 字体（Noto Sans CJK SC，本机 `C:\Windows\Fonts\NotoSansSC-VF.ttf`
   已存在）重出这 8 份矢量产物**（实测 4 张图的 SVG+PDF 全部内嵌 MicrosoftYaHei 子集：SVG 是字形路径 id、PDF 是 XXXXXX+MicrosoftYaHei 子集前缀；PNG 不内嵌），并同步更新字节复现基线（会动 `figures/*` 与 `-k figures_repro`
   和图2/图3 的字节复现用例）。**待用户拍板是否做**。

### 31.3 图4 立项（用户拍板：**要做**，交互式三维散点图）

* 用户原话理由："在一些**诱导阻力主导**的场合就不再是近似于一个平面无变化了" —— 与
  `docs/FIG-BG3D-FEASIBILITY.md` 里已测到的**曲率**（二次项把残差 RMS 从 0.5519 s 压到 0.0582 s、
  端点上抬中位数 9.16%、459/459 同号）方向一致；γ ∝ `cx_aoa` ⇒ 直觉上对应**大 γ 角落**，
  正由并行子代理用已有数据量化（`E:\导弹包线图-fig4\.tmp_test\fig4\EVIDENCE.md`）。
* 拍板规格：**轴 = β / γ / ΔV，颜色 = t_hit**；**11 枚弹可切换**（每弹一朵点云，共享同一网格与色标）；
  **证据层当主角**（每个 (β,γ) 列的一次/二次拟合 + 拟合面可开关 + 残差/曲率着色 + β–γ 平面上的曲率热力图）。
* 新分支/工作树：**`fig4` = `E:\导弹包线图-fig4`**，基线 = 集成分支 `opensource` @ `bb8709c`。
* 默认网格：β、γ 各 7 点（取图2 域）× ΔV 5 点（0.6×~1.4× `dv_pin_ms`）⇒ 每弹 245 工况、11 弹 2695 工况
  （fast 档，命中缓存更快）；若 `EVIDENCE.md` 给出更合适的范围则以它为准。
* 交付形态沿用图3 查看器的范式：WebUI 内嵌页 + 新标签页入口、手写 WebGL（**前端零第三方**）、
  数据层单独模块且**不解算**、`WEB_STATIC_ASSETS` fail-closed 白名单、新判据 `tests/test_fig4.py`
  （含"合成数据能把'只有平移'与'强曲率'分开"的**有牙**判据）。
## 33. 常驻原则：有内核完整源码时**先查内核有没有，别造轮子**（2026-10-02）

用户原话："**这是个要点，值得记下来，在有内核、求解器完整源码时不要造轮子先找内核有无实现**"。
起因是用户让我查"内核有算但没直接接原始数据出来、反而我们在外壳造轮子"的地方 —— 一查就有四类，
于是把它升级成**仓库第一原则**（已写进 `AGENTS.md` 的「⚠ 第一原则」一节）＋ 一次系统审计（task-22）。

### 33.1 原则的次序（写进 AGENTS.md 的版本）

1. **先查内核输出**：`_CF_COLUMNS`（内核逐采样列清单）里有没有 ⇒ 有就**接出来**，不要自己算。
2. **再查内核内部**：没输出但内部在算（`_atmosphere()` 的 `rho`/`sound`、`_mach_function()`、
   `forces()` 里的 `dynamic_pressure`/`nose`/`flow`、导引头观测模型、近炸/碰撞逻辑）⇒ 优先**给内核加输出列**
   （按 `vendor/wt-missile/VENDOR.md` 协议：同步 `SOLVER_SHA256` + 重建 fast 缓存）。
3. **只有内核确实没有**才在外壳实现；若是**重写内核已有公式**，**必须配一条与内核对拍的判据** ——
   否则内核一升级就**静默偏差**，图上完全看不出来。
4. 一句话：**别急着造轮子 —— 先 `grep` 内核。**

### 33.2 触发这次原则的四处实例（Lead 初查，`fig3-verifier` 正在核实）

| # | 量 | 内核侧 | 我们现状 | 性质 |
| --- | --- | --- | --- | --- |
| 1 | 最小弹目距离 | 近炸/碰撞逻辑内部跟踪最近接近 | `solver.py:394 miss_m=min_sep`、`workflow.py:577 near=min(rows["range"])` **两处各扫一遍** | 造轮子（还可能与内核触发条件不同口径） |
| 2 | 动态压 / Mach 修正 / 过载上限 | `dynamic_pressure`（792 行）、`_mach_function()`（89 行）、`fins_*/cy_peak/req_cap/control_limit` | `bg.py:172 n_star_of(q_pa,…)`、`bg.py:217` 的 `f_mach`/`cap_f` 外壳自算 | **最危险**：外壳重写了内核公式 |
| 3 | 导引头开机时刻 | 列里有 `observation_mode`/`locked`/`observation_time_s`/`observed_*` ⇒ **内核有观测模型** | 外壳用 blk `lockDistance` + **一遍法反求** | 若 `observation=locked` 能直接给，反求该退场 |
| 4 | 已行驶距离 | `distance_flown_m` 列 | 没接（沙盒正打算自己累积弧长） | 丢原始数据 |

### 33.3 已经按这条原则做出的动作

* **Mach / 攻角**：内核内部本来就在算（`speed/sound`、`nose @ flow`）却没输出 ⇒ 用户拍板**扩内核输出列**
  （task-21：加 `mach`/`aoa_deg`/`aoa_eff_deg`，60 → 63 列，含 `VENDOR.md`+`SOLVER_SHA256`+fast 缓存重建协议）。
* **G 载荷**：内核**早就输出了** `specific_force_g`/`trajectory_normal_g`/`requested_g` ⇒ 不用改内核，只需接出来。
* **系统审计**：task-22 交 `fig3-verifier`，按 **(A) 丢数据 / (B) 造轮子 / (C) 正常归约** 三类逐条判定，
  每条要求"内核 `file:line` + 外壳 `file:line` + 能对拍就给数字"，产出优先级排序表。

### 33.4 审计的连带效应（等 AUDIT.md 出来再定）

* (A) 类会变成"给产物加列"的小活（`record.py` / `traj3d.py` 的出口列）；
* (B) 类要分两种处置：**能接内核就接**；**故意的解析模型**（β–γ 那一套）则补"与内核公式对拍"的判据，
  把它从"隐形重写"变成"有判据的独立实现"；
* (C) 类要明确列出来豁免，免得以后又被当成漏接项重复审一遍。
## 34. 接线审计结论（task-22，`fig3-verifier`）：1 个真错误 + 5+5 条接线缺口（2026-10-02）

审计对象 `E:\导弹包线图-fig4` @ `951dac3`，内核 sha256 `1bfa0fa2…`（**65 列**），读数 15:06；
数字来自 24 个工况（全 `fast`/`compiled-c`，engine 缓存命中 0）。产出 `.tmp_test/audit/AUDIT.md` + `raw/`。
分类：(A) 丢数据 **5** 条（+`speed_kmh` 极小）／(B) 造轮子 **5** 条／(C) 正常归约 **11 类**（含 5 条假阳性澄清）。

### 34.1 ⚠ A5（最高优先级，**交付物里的真错误**）：命中时把引信半径当"脱靶量"

核心里 `summary["minimum_separation_until_event_m"]`（`:2690-2695`）在**命中**时恒等于**引信半径**，
而外壳把它当"脱靶量"一路传下去：`solver.py:374,394` → `record.py:18,50,169`（列名 `miss_distance_m`）
→ `report.py:49`（表头**"脱靶量 [m]"**）→ `fig4scan.py:221`、`traj.py:105`、`traj3d.py:304`。
**只有 `webui.py:1488` 做对了**（仅在未命中时才给这个数）。

实测（交付想定 R3）：内核值 **10.000000 m**（`fuse_radius_m=10.0`）；同想定 `proximity_fuse=False`
⇒ 真 CPA **0.003824 m**，**差 9.996 m**。`results/traj_default.json` 的 `run.miss_m` 就是这个常数 10.0。
⇒ **命中工况的"脱靶量"是一个常数，不是几何量**，读者会当成"差 10 m 打中"。

**处置**（task-23）：① 把语义拆成两个字段：`min_separation_m`（事件前最近距离，**命中时 = 引信半径**）
与 `cpa_m`（真最近接近距离，命中时用 `proximity_fuse=False` 复跑一次得到 —— 实测可行、成本 = 1 次解算）；
② 报告表头与 CSV 列名按真实语义改写，**命中行不显示"脱靶量"**（显示"命中（引信 10.0 m）"或 `—`）；
③ 重出 `results/traj_default.json`；④ 加判据：命中工况 `cpa_m < fuse_radius`、未命中 `cpa_m == min_separation_m`。

### 34.2 B1 潜伏静默偏差（第二优先）：外壳抄了内核诱导阻力因子却丢掉开关

内核 `induced = cx_aoa·(3.247·(0.308+0.75·(fm−0.308)) if useCxiMach)`（`:796-798` python、`:1295` compiled、
C 源 `:1742`）；外壳 `bg.py:161` 抄成常量式、**不看 `useCxiMach`**，喂 `Q/n*/R/β_eff`（`figures.py:536` 注解）
与图4 落盘（`fig4scan.py:298`）。
**数字**：`cap_f=1.166263`（M=2.660396、f=0.376242）⇒ PL-12 `Q=734.873910`、`n*=18.360613 G`；
注入 `useCxiMach=False` 后内核 `t_end` **45.186109→45.094219 s（Δ0.0919）**，而外壳 Q/n* **纹丝不动**。
168 份 blk 里该键 **0 命中** ⇒ **今天数值仍对，属潜伏偏差**（内核一改就静默偏）。

### 34.3 (A) 类 5 条：逐行 54 列 + 摘要 26 键全丢

* **A1**：`solver.trajectory()`（`solver.py:333-353`）**只留 11 键并改名**，产物 CSV 只有 8 列 ⇒ **丢 54 列**。
  沙盒悬停框那 9 个 `PENDING` 字段**内核今天全都有**：`flown_m→distance_flown_m`、`accel_ms2→accel_*`、
  `n_g→trajectory_normal_g`、`sf_g→specific_force_g`、`req_g→requested_g`、目标 `speed→target_speed_m_s`，
  以及 `closing_speed_m_s`、`linear_time_to_go_s`、`speed_kmh`。
* **A2**：摘要 31 键只读 5 个；未读且有数：`closest_time_s=45.186109`、`distance_flown_m=36966.4347`、
  `peak_requested_g_before_native_limit=41.0674`、`peak_specific_force_g=21.656`、
  `peak_trajectory_normal_g=9.3405`、`fuse_radius_m`、`fuse_arm_time_s=1.7`、`steps=2169`、
  `motor_start_times_s`、`seeker_assumptions`。
* **A3**：内核 `observation.{latency_s 0..30, position_bias_m, velocity_bias_m_s}`（`:185-198`、`:425-460`）
  而我们 `Scene` 只发 `{"mode":…}` ⇒ 通道活着但**发不出去**（实测 `locked+latency 2.0` ⇒
  `source_observation_age_s` 最大 2.0208 s；`ideal+latency` 会被内核 `ValueError`）。
* **A4**：内核接受 `launch.{quaternion_xyzw, angular_rate_rad_s, ejection_velocity_body_m_s, age_s,
  feedback_acceleration_m_s2, motor_start_times_s}` 与 `target.{samples, turn_rate_rad_s, interpolation}`，
  我们只发 position/velocity/collision_radius/maneuvers。

### 34.4 (B) 类其余四条

* **B2**：`bg.py:126-127` 自算 `lift_area/drag_area`，而内核 `Body.lift_area/drag_area`（`:757-758`）已暴露；
  今天 5 型 **Δ=0.000e+00**（PL-12 SD 0.0323654729 / SL 0.4312450800）⇒ 潜伏。⚠ 文档 `figures.py:532-533`
  声称"SD/SL 直接取内核、没有另造面积口径"**与代码相反**（文档要改）。
* **B3**：`solver.effective_cx_aoa()`（`solver.py:172-188`）是内核 `:780-782`（`:1269`）的**逐行复刻**，
  而同文件 `body_aero()` 已经能问内核 ⇒ 改 `wt.Body(params).cx_aoa` 即可；今天 5 型同值、有对拍判据，**风险最低**。
* **B4**：沙盒自算弧长/加速度/目标速度，内核逐行已有 `distance_flown_m`:2630、`accel_*`:2646、`target_speed_m_s`:2623。
  实测：全采样折线弧长 Δ=+0.0000 m、抽稀 800 点 Δ=−0.0134 m（R3）⇒ **精度不是理由，重复实现与口径漂移才是**。
* **B5**：`workflow.py:577`（HEAD:574）报错分支再扫 `min(r["range"])`，而同 run 的 `shot1.miss_m` 就是内核值；
  事件终止时一致（Δ=5.68e-14 m），**生命期终止时差几米**（R2 2.2e-06 vs 5.29997 m）。

### 34.5 ✅ 被推翻的 Lead 判断（记下来，免得下次又猜）

* **我的线索 1**"两处扫行取最小弹目距离" —— 只有 `workflow.py:577` 那个报错文案重复；
  `solver.py:394` 用的**就是内核值** ✓。
* **我的线索 2** 里的"过载上限" —— 外壳 `req_cap|limitAoa|finsLatAccel|control_limit|cy_peak` **0 命中**，
  属 **(A) 丢数据** 而非造轮子；`bg.n_star` 是本项目自己的分析量，别混。
* **我的线索 3**"开机时刻反求可能是造轮子" —— **错**。内核 `:2638` 把 `locked` **硬写 True**、`:2756` 自述
  `initial_track='pre-acquired at time zero'`、`:2750` `permanent_lock/unlimited_acquisition=True`，
  `lockDistance` 在内核与 blk **0 命中** ⇒ **内核没有"开机事件"可接**，我们用 `lockDistance` 反求是**正确且必要**的
  （三种观测模式下 `locked` 取值集合都是 `{True}`；`observation_time_s` 只是滤波更新时刻）。
* 另外两条主动澄清：β/γ/BC 的燃尽质量 vs 内核 `min(mass_kg)` **11 型最大差 1.34e-6 kg** ✓；
  `bg.py:162 q=½ρv²` 是定义式且 ρ 取内核 `_atmosphere()` ⇒ 不算造轮子 ✓。

### 34.6 下一步（按优先级）

1. **task-23（A5）**：语义拆分 + 真 CPA（命中时 fuse-off 复跑）+ 报告/CSV 列名改写 + 重出产物 + 判据。
2. **A1/A2 接线**：扩 `trajectory()` 与 CSV 列、摘要峰值进 `Shot`（沙盒 9 个 PENDING 一次解决）；
   其中 `mach/aoa*` 三列要等 **task-21（kernel-out）** 落地后升级内核并同步 `SOLVER_SHA256`/`VENDOR.md`。
3. **B1/B2/B3/B5 收口**：能问内核就问内核（`Body` 已暴露），并补"外壳值 vs 内核值"对拍判据。
4. `figures.py:532-533` 那段"没有另造面积口径"的文档**改成与代码一致**。
## 35. kernel-out 落地（task-21：内核输出列 **65 → 68**）（2026-10-02）

commit **`fae340d`**（父 `91601e3`），5 files +286/−8；`git diff --cached --stat` == `-w --stat`。

* **列数 = 68**：前 65 列的名字/顺序用指纹 `sha256(" ".join(cols[:65])) = 00ea06f4…` 钉死（插在中间/改名/换序都会红），
  末三列 = `mach` / `aoa_deg` / `aoa_eff_deg`，列名唯一。
  ⚠ 我（Lead）早先在派单里写的 60/63 是**按可见行数估的，错了**；实测一直是 **65**（`docs/SHELL-REBUILD-FEASIBILITY.md:69`
  也记着"实测 len == 65"）⇒ 加 3 列 = **68**。oss-prep 全程按实测办事，判据硬编码 68。
* **fast 编译缓存已重建**（在 VS 开发者环境里；`cl.exe 14.44.35207`）：`_CF_HASH` `8fbed960…` → **`386ac698…`**，
  DLL `%LOCALAPPDATA%\wt-missile\compiled-fast\386ac698…dll`（166912 B，2026-10-02 15:01:50）。
* **普通终端实测**（没有编译器在 PATH）：`standard` → `python-standard`、`fast` → **`compiled-c`**，
  两者 `t_hit` 都是 **45.186109475831095（逐位相同）** ⇒ **加列没动物理**。
  另一条带机动的 2881 行场景同样是 `compiled-c`。
* `vendor/wt-missile/VENDOR.md`（新增「本地改动记录（2026-10-02）」节 + "输出列 68 列" 一行）与
  `src/missile_sim/solver.py` 的 `SOLVER_SHA256 = dad09cae…` **两项都已改**，实测文件哈希 == 常量。
* 全量自检 **408 / 0 / 408**（218.3 s；402 + 新增 6 项）。
* **独立复算**：外壳自己写的四元数+速度复算 vs 内核新列 —— `standard` 差 **0.0**（逐位相同）、
  `fast` 差 **6.7e-12**；真实产物 CSV 表头已含三列（crank 想定 2881 行；
  `t≈12 s` 行：`mach 3.431107` / `aoa_deg 1.707684` / `aoa_eff_deg 1.708242`）。

### 35.1 ⚠ 合并时待办（Lead）

1. **产物陈旧（"绿着但陈旧"）**：3 个 `figures/fig_{isotime_plane,bg_plane,traj}_default.svg` 的图注、
   以及 3 个 `results/{plane,bg,traj}_default.json` 的 provenance 里仍是**旧内核 sha `1bfa0fa2…`**
   ⇒ 按"产物的身份不许撒谎"要重出图与产物（`--formats png,pdf,svg` / `--figure bg|traj --tag default`）。
   测试不比对仓库里的 `figures/`，所以全绿**掩盖**了这一点 —— 这类"绿着但陈旧"正是要主动重出的。
2. **`docs/SOLVER-API.md` §3.1 出现两份**：我在 `fig4` 树写过一份（口径写"mach/aoa 由本仓**派生**"），
   oss-prep 在 `kernel-out` 树按 68 列实现又写了一份（口径"**必须由内核给出，外壳不派生**"）
   ⇒ **以 `kernel-out` 版为准**（它才符合用户拍板），合并时覆盖 `fig4` 那份。
   （教训：**契约文档要在同一棵树上写**，各分支各写一份必冲突；以后契约类修改统一由 Lead 在集成分支做。）
3. `record.write_traj_track_csv` 的列是**写死**的 ⇒ 新三列不会自动进 traj CSV（属 §34 的 A1 接线任务）。
## 36. 五分支合并（2026-10-02）：4/5 已并入，附 Lead 验收抓到的四处缺陷

集成分支 = `opensource`。合并顺序按"先内核与契约、后表现层"：
**kernel-out → sep-fix → fig4 → sandbox → layout**（每合一步重跑全量 + `-k figures_repro` + `git diff -- figures`）。

| 步 | 分支 | 合并提交 | 并进来的东西 | 冲突 | 合完的全量 |
| --- | --- | --- | --- | --- | --- |
| 1 | `kernel-out` | `c8c7f85` | 内核输出列 65 → **68**（`mach`/`aoa_deg`/`aoa_eff_deg`）+ SHA + VENDOR + 缓存重建 | 无 | **408/408** |
| 1b | （Lead） | `241303c` | 全仓内核口径对齐（6 个文件）+ `AGENTS.md` 新增「环境与指令纪律」（worktree junction / 指令前先核仓库） | — | 408/408 |
| 2 | `sep-fix` | `a2b5589` | **修 A5**：`min_separation_m`/`cpa_m`/`fuse_radius_m` 三语义拆分（`miss_m` 删除） | 无（`solver.py` 自动合并） | **417/417** |
| 3 | `fig4` | `9bf38a1` | 图4 v4（散点 + 单层等时面 + 13 档层契约 + 共享环境预设层） | 无 | 464/466（两红，见 §36.1） |
| 3b | （Lead） | `9834e49` | 修集成冲突 + `identity()` 加输出 schema 身份 + 重出图4 产物 | — | **466/466** |
| 4 | `sandbox` | `fcd3988` | 空战沙盒 P1–P6（`/sandbox` + `/api/sandbox/<key>`，产物 22/5 列） | `webui.py` 7 块（见 §36.2） | 见 §36.3 |

### 36.1 Lead 验收抓到：fig4 的 `-k fig4` 在 HEAD 上就是红的（作者自报 40/40 不可复现）

`fig4.js` 的 no-hit 分支写了兜底色 `"|| \"#52606d\""`（= `figures.FIG4_MUTED_COLOR`），
而它自己的判据要求"`fig4.js` 零颜色字面量" ⇒ 实测 **39/40**。
修法（`becd289`）：配色必须来自响应 `d.colors.muted`，**缺了当场抛**（契约破损），不写兜底色 ——
否则"配色全部来自 figures"就成了一句空话。

**合并后另有两红**（跨分支语义冲突，不是谁写错）：A5 删了 `Shot.miss_m`，而图4 的算核与产物列还在用
`miss_m` / `miss_distance_m`。修法（`9834e49`）：`fig4scan.case_rows()` 改 `min_separation_m` +
补 `cpa_m`（网格不量 ⇒ 空）与 `fuse_radius_m`；`record.write_fig4_cases_csv()` 的行值跟着改
（⚠ `FIG4_CASES` 是从 `CSV_CASES[4:]` 拼的，A5 一改它就自动换名 —— **只有行值那一处漏了**，
正是"列名都对、值全空"的静默坑）；判据升级成 A5 语义（命中行 `min_separation_m == fuse_radius_m`）。

### 36.2 `webui.py` 的合并：机械拼接是错的，锚点插入才对

fig4 与沙盒**在同一个文件、同一批位置各自追加**（路由表、`do_GET` 分支、`_*_page`/`_*_data` 方法、
payload 函数、`WEB_STATIC_ASSETS`、页面常量），git 报 7 个冲突块。踩到的三条：
1. **`git merge` 的冲突块会把函数从中间切开**（`ours` 以 `def f():` 结尾、`theirs` 以另一函数体内行开头）
   ⇒ "ours + theirs 拼接"产生 **IndentationError**（我第一版就是这么干的，被 `py_compile` 拦下）；
2. `git apply --3way` 会停在同一批位置（两边插入点相同），**没有更聪明**；
3. 严格整-hunk 补丁应用也失败 —— 因为 fig4 往同一段里插过自己的行，**旧侧不再连续**。
   可行做法：**以 HEAD 版为底，按 9 条唯一锚点逐条并入沙盒改动**，每条断言"锚点恰好 1 次"
   （脚本 `.tmp_test/merge_sandbox_webui.py`），再用两条 diff 反向验证：
   `git diff HEAD -- webui.py` 的删除行**只有 2 行**（就是被"两接口并列"版本有意替换掉的文档句），
   两侧符号计数全为 2（定义 + 调用点）。

### 36.3 沙盒判据与"集成后现实"脱节（已派回作者修）

重出 `results/traj_default_*`（新 22/5 列）后 `-k sandbox` 从 16/20 变 13/20 —— **不是新列的问题**，
而是 7 条判据钉的是集成前的现实：`miss_m`（A5 已删）、命中行文案（A5 改成"最近接近"）、
series/pending 期望（P6 接完内核列后 `pending_keys == []`、`new` 列必须出现）。
处置：让 `webui-fig3` 把自己的分支并到 `fcd3988`、用 `git checkout fcd3988 -- results/...` 取新产物，
并把"老产物降级"那条判据改成用 `.tmp_test/` 里自造的 8 列小产物（否则它以后还会被"产物重出"弄红）。

### 36.4 另外两处"文档与代码不一致"（同类隐患，都当场修了）

* `docs/FIG4.md` §3.3 的重出命令写着 `--fig4-dv-factors 0.5,0.7` —— **该开关在 v4 换轴时已删除**
  （ΔV 从"基准弹倍数"改成绝对区间）。照抄会 `error: unrecognized arguments`；
  更糟的是我第一次误用 `--tag miss`（不带场景参数）**把默认网格写进了 miss 档**（`-k fig4` 掉到 32/40）。
  正确命令：`--missiles R-77 --range 80000 --fig4-beta-n 2 --fig4-gamma-n 2 --fig4-dv-lim 700,800 --fig4-dv-n 2`
  ⇒ 8 工况 / 0 命中 / ΔV = {700,800} ✓。文档已更正并加了一行"老开关已删除"。
* `identity()` 之前没有输出 schema 身份 —— 现在加了 `output_columns`(68) + `output_columns_sha256`
  （实测 `f097c34e…`）+ `output_columns_tail`，**不 bump `MODEL`**（物理逐位未变，变的是 schema）。

### 36.5 待办（收尾清单）

1. `layout`（5/5）合并：已让 `webui-author` 先把自己的分支并到 `fcd3988`、在它自己分支里解冲突；
2. `sandbox` 判据对齐（已派 `webui-fig3`）；
3. **全仓产物重出**：`figures/`（3 张图三格式，图注里的旧内核 sha）+ `results/{plane,bg,traj,fig4}_*`
   （旧 sha + 旧列名）—— 一次做完，再跑全量；
4. 文档誊写（Lead）：`docs/WEBUI.md`（`/fig4`、`/sandbox` 路由 + 静态资源 + §9 统一布局）、
   `docs/RESTART-PLAN.md`（沙盒段落）；`docs/SOLVER-API.md` §3.1 补第 4 条（缓存判据）。
5. 真浏览器最终验收：沙盒**真鼠标拖拽**、图4 滑块零往返、四页统一布局（截图）；
6. 向用户交总账。
## 37. 五分支合并**全部完成** + 最终验收（2026-10-02，集成分支 `opensource`）

### 37.1 合并结果（5/5）

| 步 | 分支 | 合并提交 | 合完的全量 |
| --- | --- | --- | --- |
| 1 | `kernel-out` | `c8c7f85` | 408/408 |
| 2 | `sep-fix` | `a2b5589` | 417/417 |
| 3 | `fig4` | `9bf38a1`（+ Lead 修复 `9834e49`） | 466/466 |
| 4 | `sandbox` | `fcd3988`（+ P7 收尾 `42e1b3b`） | 488/488 |
| 5 | `layout` | **`5dca33b`** | **498/498** ✓ |

**终局验收（Lead 亲跑）**：全量 **498 通过 / 0 失败 / 共 498**（201.5 s）、`-k figures_repro` **7/7**、
`git diff HEAD^ -- figures results` **零变化**（layout 只换皮）、工作区干净。

### 37.2 真浏览器验收（Lead，集成树 `E:\导弹包线图-oss`，端口 8795）

**接口层**（Python `urllib` 探，22 条路由里抽 11 条）：

| 路由 | 结果 |
| --- | --- |
| `/healthz` `/` `/sandbox` `/fig4` `/viewer3d` | 200（首页 **19 595 B**，在 20 KB 判据内） |
| `/static/sandbox.js` | 200（35 551 B） |
| `/static/sandbox.html` | **404** ✓（整页不进白名单，边界正确） |
| `/api/sandbox/default?points=200` | 200（58.5 KB）：`events=8`、`hover.fields=13`、**`pending_keys=[]`**、`derived=['accel_ms2','horizontal_m']`、`na_keys=8` |
| `/api/fig4/default` | 200（203 KB） |
| `/api/fig4/default/layers?missile=120A` | 200（**308 342 B**，0.23 s） |
| `/api/viewer3d/nope` | 404 ✓ |

**页面层**（真 Edge/Chromium，截图存 `.tmp_test/final/`）：
* `/sandbox`：左栏「想定」区直接显示 **`最近接近 / 引信 = 0.003824 m / 10.0 m`** ——
  **A5 修复的可见面**（改前这里是把引信半径当脱靶量的错值）；顶部回放条 `2.9s / 69.2s`；右上角**线型**图例
  （目标虚线五段 / PL-12 实线两段）；8 个事件标点（含 `命中: 69.17 秒（最近接近 0.003824 m，引信半径 10.0 m）`）；
  `k` 刻度轴；悬停框（`PL-12 · t=2.9s · v=773m/s · R=47.6km`）。
* `/fig4` 默认：**纯散点**、三轴标题**自带好坏方向**（`BC（≡β）直飞保能 →（越大越好）`、
  `ΔV 理想（真空等效）总增速`、`γ 转向损失 →（越小越省）`）；空心圈 = 脱靶；右栏色标 "11 枚弹共享范围"。
* `/fig4` 点「生成等时面」后：**`等时面 420 三角形（46 s）`**，滑块启用、半透明网面横跨点云。
* **零往返（Lead 用 network 独立验证）**：整个会话里 `/api/fig4` 只有 **1 个请求**
  （`layers?missile=120A` → 200、308 KB、193 ms，initiator `requestLayers fig4.js:747`）；
  此后在滑块上按两次方向键，**请求数仍为 1** ⇒ 拖动纯前端 ✓

### 37.3 仍然没做到的（诚实清单）

* **真鼠标拖拽**没验成：`browser-skill` 只有 click/hover/wheel/press/scroll，**没有 press-move-release**。
  相机可变性用 `?az=&el=` 钩子、滚轮（缩放）与页内自检/节点数值判据间接证明；**建议你亲手左键拖一下**。
* 沙盒轨迹线宽固定 1 px（WebGL `lineWidth` 多数实现忽略）；参考站那种粗线要改成屏幕空间四边形，未做。
* 沙盒 debug 钩子（`?t/?paused/?follow/?az/?el/?hover/?debug`）**保留**，已在 `docs/SANDBOX.md` 标注为调试入口。

### 37.4 本轮"Lead 验收"抓到的缺陷（这就是为什么作者自测不算数）

1. `fig4.js` 兜底颜色字面量 `#52606d` ⇒ 它自己那条"零颜色字面量"判据在 HEAD 上**就是红的**（作者自报 40/40 不可复现）；
2. A5 改名与图4 算核的**跨分支语义冲突**（`miss_m` 已删，`fig4scan`/产物列还在用）⇒ 合并后 2 红；
3. `docs/FIG4.md` 的**过期命令**（`--fig4-dv-factors` 已删除）⇒ 照抄即报错；我误用 `--tag miss` 还**把默认网格写进了 miss 档**；
4. 沙盒 7 条判据钉着"集成前的现实"（`miss_m`、旧文案、旧 series/pending 期望）⇒ 已让作者改成**由产物表头推**的解耦写法；
5. `-m` 参数里的中文引号会被 PowerShell 当**字符串定界符**（连续栽两次）⇒ 一律改用 `git commit -F <消息文件>`。
## 38. 图4 v5：点云换成"每弹一个标称三参数点"（2026-10-02，用户拍板）

**用户原话**："我看了，**命中点不用，只出各弹三参数点即可**"；追问后两条拍板：
① **11 个点 + 常显弹名标签 + 颜色 = 该弹 t_hit**；② **等时面保留**（按需扫单弹、默认不出面）。

* 分支 `fig4-lite`（从集成分支 `95bb167` 切）→ 合并提交 **`0313d63`**，15 文件 +16178/−61443
  （大删除 = 格点云产物与只对格点有意义的判据）。
* **标称三参数的唯一权威口径**（作者查清后写进文档）：`ΔV = pool.metrics_of().dv`、
  `β ≡ BC = bg.point_of().beta`、`γ = bg.point_of().gamma`。
  ⚠ `BlkMetrics` 里**没有** γ、`BgPoint` 里**没有** ΔV —— 所以只能这么取；`metrics().bc` 与 `point_of().beta`
  实测逐位一致到 **9.1e-13**。这也正是图2/图3 用的出口。
* **默认产物只解 11 个工况**：打桩实测 `solver.run` 调用 = **11**（关缓存跑，否则会命中缓存变 0），
  构建 `elapsed_s = 3.5 s`、CLI 端到端 6.7 s —— 旧版是 5929 工况 / 218 s。
* **实测 7 实心 / 4 空心**（Lead 独立复算过 `/api/fig4/default`）：
  命中 = 120A 70.00 · 120C 62.89 · 120D 63.13 · AAM-4 71.59 · PL-12 69.47 · PL-12A 60.83 · R-77-1 62.46 s；
  空心 = MICA / R-77 / Derby / R-Darter（事件 `lifetime`）。⇒ "默认全命中 ⇒ 看不见脱靶标记"那个老别扭消失。
* **等时面改按需**（对外契约不变：13 层一次给全、滑块零请求）：
  * 缓存键指纹覆盖**五样**：`scene`（含 maneuvers）/ `tier` / `grid` / `弹名` / **`solver.sha256`**；
    文件里存同一份 key、读时重算比对（对不上就当没有）⇒ 堵住"改了工况却命中旧立方体、t 值撒谎"。
  * 不在缓存 ⇒ **202** `{scanning, job, message, poll, expected, cache}` + `/progress/<id>` 轮询；连点复用同一 job；
    900 s 上限；job 失败把错误**显式写到页面**；弹名不认识**先 404**。
  * 单弹立方体 539 工况实测：**冷扫 jobs=8 → 21.7 s**、`jobs=1` → 141.7 s、**缓存命中 → 0.48 s**。
  * 入库一份预扫缓存 `results/fig4_cube_PL-12_1989434c.json`（133 KB）⇒ 默认工况点"生成等时面"秒开。
* **"标称点脱靶 ≠ 这枚弹没有等时面"**（同弹在高 ΔV 侧仍可能命中，S0 实测 ΔV ≥ 1100 全命中）⇒ 按钮一律可用，
  扫完 0 层可出面才提示降级 —— 已写进 `docs/FIG4.md`（解释性口径，防以后被当 bug）。
* Lead 验收：`-k fig4` **41/41**、全量 **499/499**（独立复跑 204.8 s）、
  接口级全链路实测（11 点 → 7/4 → PL-12 缓存 200/10 层 → MICA 202 + job done + 再取 200/10 层 → 未知弹 404）。

### 38.1 验收中发现的小缺陷（已派回作者）

**"读缓存"会回写缓存文件**：我只读了一次 `/api/fig4/.../layers?missile=PL-12`，`results/fig4_cube_PL-12_1989434c.json`
就被打成 `M` —— diff 只有一处：`"elapsed_s": 1.539` → `1.545`（同文件里 `n_run: 0, n_cached: 539` ⇒ 确实全命中、没重算）。
后果：**每看一次页面就把仓库弄脏**（对"工作区干净"与可复现性都是噪音）。
处置：先 `git checkout --` 恢复该文件，并把"读路径不得写文件（或只在真的扫描过时才写 `elapsed_s`）"派回作者修。

### 38.2 作者如实上报、我接受的两点

* 6 个文件的 `git diff --stat` 与 `-w --stat` **不一致** —— 原因是他把整段重写进新缩进层级（**只改缩进**），
  并已用"10 个改动文件的 CRLF 计数与 HEAD 逐一为 0"证明**行尾没被动过**。这属 AGENTS.md 里"唯一合法例外"。
* 删掉了 `results/fig4_miss.{json,cases.csv}`（那是"扫全脱靶档"的格点产物）：v5 默认视图自带 4 个空心点，
  0 层降级由合成数据判据钉住，且旧 `docs/FIG4.md` 的重出命令里那句 `--tag miss` 正是害人之处 —— **同意删除**
  （需要留档用 `git show 95bb167:results/fig4_miss.json`）。
* `record.FIG4_CASES` / `write_fig4_cases_csv()`：作者说"没人用了"，但我查见 `tests/test_fig4.py` 仍有两条用例
  与 `docs/FIG4.md` 的列序说明在引用它 ⇒ **先不删**（删了会连坐判据与文档）。

> 归档说明（2026-10-02，Lead）：本节写于 ig4 分支的工作树里、一直未提交；五分支合并后
> 集成分支的 NOTES 从 §31 直接跳到 §33 —— 这节差一点在「清理工作树」时丢掉（我第一次的归档脚本
> 因公共前缀切在标题行中间而正确中止，但同一条命令里的 git checkout -- 仍然执行了）。
> 内容从当时的源文件 .tmp_test/notes32.md 按原字节补录，未改一字；编号落在 §38 之后。

## 32. 图1–4 的统一架构拍板 + 图4 轴口径纠正（β ≡ BC）+ 图3 拆沙盒（2026-10-02）

### 32.1 用户拍板（原话要点）

1. **图1–图4 共用一套「环境预设 + 基准弹」**，由**前端接收**、四张图都用；
   Lead 追问后用户选：**落到后端也统一**（不是只统一前端 UI）。
2. **图3 独立出来做「空战沙盒」**，展示**导弹与敌机**的飞行过程。
   参照站 = **`statshark.net/missilecalculator`**；用户明确"**从功能上我们做的可拖动的交互式沙盒
   已经实现了这一功能了**" ⇒ 已有 `webui_static/viewer3d.*` 就是它的功能底座，本轮范围 = **回放型**
   （时间轴 / 倍速 / 跟随镜头 / 事件标点），**不是**实时改参重算型。
3. **图4 = 图1 + 图2 的三维统合**："图4 其实是造1、2的轮子"，所以**基准弹、等时面逻辑应与图1/图2 同源**
   （t 层怎么取、参考工况是什么，只能有一套定义；2D 出等时线、3D 出等值面可以算法不同）。
4. 用户原话："3维再放叠加等时面观感会极差，**所以改成单层滑动**" ⇒ 单层等时面 + 滑动条改 t。

### 32.2 ⚠ 轴口径纠正：用户先说 (ΔV, BC, β)，实测**β ≡ BC** ⇒ 改为 (ΔV, BC, γ)

* 用户选的是 `(ΔV, BC, β)`。但本仓库里 **β 与 BC 是同一个量**：
  * `src/missile_sim/bg.py` 注释逐字："**β 与 BC 恒等，见 `docs/BETA-GAMMA.md` §2.1**"；
  * 定义都是 `m_dry / (SD · CxK)`，单位都是 kg/m²；
  * **实测（`results/fig4_default.json` 的 11 枚弹 β vs `AGENTS.md` 的 BC 表，逐位一致）**：
    3609.04 / 3623.95 / 3653.78 / 2636.00 / 3683.89 / 3078.05 / 3245.95 / 2568.82 / 2705.63 / 2567.02 / 2631.19。
* ⇒ 把 BC 与 β 当两根轴，三维网格会**退化成平面**（两轴共线、参数化不可逆）。
* ⇒ 正确写法 **(ΔV, BC, γ)**：正是"图1 的 (ΔV, BC) 平面 + 图2 的诱导阻力维 γ"，
  与既有 (ΔV, β, γ) **是同一个空间**（`bg3d.py` 顶部已推导：`thrust_scale↔ΔV`、`cx_scale↔β`、
  `cx_scale·cxaoa_scale↔γ` 一一对应）⇒ **数据层不用改，只需把第二根轴标签从 β 改成 BC（并注明 BC ≡ β）**。
* 教训同 §13.7 那条：**用户给的量名要先在仓库里对一遍定义**，否则会把退化参数化当成三维空间去扫。

### 32.3 任务板（三张，均待派单）

| 任务 | 内容 | 关键约束 |
| --- | --- | --- |
| **task-18** | 图4：散点 + **单层等时面 + 层滑块** + 用户自定义工况（v4 规格，轴改 (ΔV, BC, γ)） | 数据层不解算；等时面用 `bg3d.marching_tetrahedra`；未命中弹**不许用 `lifetime` 冒充 `t_hit`** |
| **task-19** | 图3 独立成**空战沙盒**（回放型；导弹 + 敌机实体、时间轴/倍速/镜头/事件标点） | 复用 `traj3d.py` 与 `viewer3d.js`；前端行为须**真浏览器取证** |
| **task-20** | 抽共享「**环境预设 + 基准弹**」层，四图统一消费 | ⚠ **不许改数值行为**：改造前后同工况数值逐位一致 + 全量仍 402/402；发现默认值互相矛盾**先报告** |

### 32.4 图4 前端现状（Lead 真浏览器实测，2026-10-02 14:27）

* `fig4.js` 43,878 字符，**手写 WebGL2、零第三方 JS**；`GET /fig4` 200、`fig4.js|css` 200、
  未登记的 `/static/fig4.html` **404**（白名单 fail-closed 有效）。
* **实测可用**：切弹种（120A → MICA：标称 β 2636 γ 64.43 ΔV 947.0、三角形 444→582、热点跟着动），
  且**色标保持 11 弹共享范围 34.69~68.62 不跳**（正是 v4 要的口径）。
* **要删**：全局最小二乘拟合平面（`plane` 25 处）、逐 (β,γ) 列二次拟合曲线（`fit` 49 处）、
  β–γ 曲率小面板与"只看诱导阻力主导"筛选（`heatmap`/`curv`）。
* **要加**：`marching`/`iso`/`layer`/`slider` 四个词在 `fig4.js` 里**零命中** ⇒ 等时面与 13 档层滑块还没做；
  工况输入表单（复用 `TRAJ_FIELDS`，默认 crank→39、39 时刻可输入）也还没做。
* 截图存档：`.tmp_test/fig4/frontend_v2_{120A,MICA}.png`。

### 32.5 并发状态

`E:\导弹包线图-fig4` 里前一个写者（子代理）**仍在迭代**（14:29 还在改 `webui.py`/`index.html`，尚未提交）；
`fig3d-scout`（teammate）已按 v4 待命，**不会动文件**；等前一个写者停手并提交后由 Lead 发"可以开始"。


## 39. 产品形态 v6（用户 2026-10-03 拍板）+ 五个真 bug 与两条方法论

### 39.1 口径：`docs/UX-TARGET.md` 是唯一来源
用户原话即规格：一次计算出全部图；**图1 = ΔV–β、图2 = β–γ、图3 = 原图4 的三维版、图4 = 原沙盒**；
**无输入时图1/2/3 直出 11 弹标称散点（不解算）**，**给了输入后沙盒置顶 + 三张图加等时线/面**；
**沙盒严格随输入**。用户追问后定三条：旧静态轨迹成品图**删掉**；布局 = **单页四块**；沙盒**没给工况就不显示**。
落地口径（路由 `/fig3`=三维页、`/fig4`=沙盒页、旧 `/fig4` 不留别名；`fig4*.py`→`fig3*.py`；产物 `results/fig3_*`）
与全部警示都写在 `docs/UX-TARGET.md`。该文件**原稿有一处自相矛盾**（`/fig4` 被同时要求当三维页旧名与沙盒页新名），
由作者 `webui-author` 发现并要求裁决后才修正 —— 记一笔：**规格也会错，作者有权停下来问，这比照着矛盾干完再返工便宜得多。**

### 39.2 这一轮抓到的五个真 bug（全部由"真跑"而非"读代码"暴露）
1. `summarize_all()` 只服务 `both/all`，收 `four` 当场 `ValueError`；
2. 表单 `figure` 白名单不认 `four` —— **提交被自己的门禁 400 拒收**；
3. `cli._request()` 尾部无条件 `rest["formats"]=…`，而 `Fig3Request` 无该字段 ⇒ **`--figure fig3 --formats png` 必炸**（既有 bug）；
4. webui 读**幽灵字段** `req.dv_factors`（`Fig3Request` 的 ΔV 轴是 `dv_lim`+`n_dv`）⇒ **任何走 webui 的图3 任务必挂**（既有 latent bug，被四块分支抬到主路径）；
5. 四块提交里图3 块**默认整块立方体**（600 s 未完成），期间 `/progress` **十几次全超时**（服务进程里跑纯 Python 扫描抢 GIL）⇒ **沙盒迟迟不显形**，直接违反"沙盒置顶"。

### 39.3 方法论（比 bug 更值钱）
* **假 runner 走不到"构造请求"那一步**：`-k four` 全绿而真实 `--figure four` 必炸。⇒ 凡"一次提交/一条命令"的判据，
  **必须有一条真的从命令行/HTTP 构造请求**。
* **写判据本身也会踩坑**：幽灵字段判据第一版正则 `(?!\s*\()` 被回溯咬掉一个字符（把 `req.check()` 读成 `req.chec`），
  **把真代码判成幽灵字段**。⇒ 判据要有**正面样例**（拿真实字段断言"不被误报"）。
* **验收先怀疑自己的测量工具**：我用 `git show … | Out-String` 数 CRLF，`Out-String` **会把行重新用 CRLF 拼起来** ⇒ 差点
  冤枉作者"把 app.js 从 CRLF 重写成 LF"。改用 `git cat-file blob` 原始字节 + `--ignore-cr-at-eol` 交叉验证才定性。
  （同类前科：`curl.exe` 返回 `000`、Python 探针读错字段名。）

### 39.4 阶段与状态（`ux4` 分支）
A 编号搬家（503/503）→ B 单页四块 / D 静态形态（独立 tag `static`，9 个新产物、零重出）/ F 沙盒严格化（删 `default`/空 与 `?tag=` 两条**回放仓库产物**的后门，只留真实 job id）→ C 一次提交出四块 + `/progress` 汇总 + 失败不装成功（512/512）→ E 删渲染成品轨迹图（**`run_traj` 解算与 `results/traj_default_*` 一字节未动**，508/508）。
**待办**：C2（图3 块改单弹等时面 + 沙盒先显形 + 长扫描别占 GIL）、G（`AGENTS.md`/`WEBUI.md`/`README.md`/`DISTRIBUTION.md`/包内文案按新编号与"无静态轨迹图"改口；`make_dist.py` 必带件加 6 个 `*_static.*`、去 `fig_traj_default*`）、真浏览器两态截图、以及 **Lead 自己的收尾验收**（独立 worktree 真跑 `--figure four` 冷/热、全量、四块真浏览器）。

### 39.5 沙盒的两条配套（防"看到别人的结果"）
① 沙盒块**必须显示它在展示哪个工况**（用**任务自己的摘要**，不是左栏输入回显）；② **失效 job id**（服务重启后任务表清空）
必须给明确提示、**不许白屏**。二者都有判据。

### 39.6 更正 §39.2 第 5 条（作者自我撤回，2026-10-03）—— 并撤回 Lead 的"裁决 3"

**先更正**：上面 39.2 的第 5 条（"四块提交里图3 块默认整块立方体 ⇒ 600 s 未完成 + `/progress` 全超时 +
沙盒不显形"）**是错的**。真因是 **`run_fig3_job()` 的进度文案在撒谎** —— 它写着"扫描 (β,γ,ΔV) 立方体：
7×7×11 × 弹池"，而 `workflow.run_fig3()` 只解 **11 枚弹各自的标称三参数点**（`fig3.py` 模块契约原话：
"默认产物里没有立方体"）。**作者把进度文案当成了证据**，据此报了"600 s 卡死"。

**实测（`ux4`、fast、45 km 冷工况，2026-10-03）**：
单块 `figure=fig3` 任务 **0.74 s**；四块提交（全命中缓存）**7.1 s**，期间 `/progress` **0.003~0.028 s**；
四块**冷跑**端到端 **61.6 s**（fig4 1.1 → fig1 26.6 → fig2 43.0 → fig3 61.6；其中面 = PL-12 **539 工况 15.2 s**、命中 468 面）；
全程 61 次轮询：`/progress` 最慢 **0.122 s**、`/` 最慢 **0.089 s**；
**按需**冷扫另一枚弹（R-77）539 工况 **16.5 s**（13 层 / 8862 三角形），期间 layers 最慢 **0.187 s**、`/` 最慢 **0.020 s**。

**两条结论**：
1. **Lead 的裁决 3（"把长扫描挪进 worker 进程池"）撤回** —— 扫面本就在**后台任务线程**里、求解走
   `Engine(jobs=8)` **进程池**，HTTP 循环没有被饿死，**不需要改架构**。（Lead 的裁决被数据推翻时也要撤回。）
2. 那次 **622 s 的观测不可复现**（当时机器上还跑着别的 agent 的测试），**不再归因于立方体**。

**新增第四条方法论**：**进度文案/标签不是证据**。要测的是**真实工况数**（`summary.n_cases` / 网格维度之积 /
产物里的计数），不是它**自称**在扫什么；"进程在扫什么"必须由**数据**说，不能由**文案**说。
本轮顺带把撒谎的文案改成了实话。同族前科：Lead 用 `Out-String` 数 CRLF（工具会伪造行尾）、`curl.exe` 返回 `000`、
Python 探针读错字段名（`t_hit` vs `t_hit_s`）—— **先怀疑测量对象，再怀疑被测对象。**

**同时更正形态口径**（§39.4 的 C2 落地）：四块提交里的**图3 块 = 11 标称点 + 当前基准弹的单弹等时面**
（539 工况，新增 `run_fig3_four_job()`）；**11 弹整块立方体只走显式按需**（CLI `--fig3-cube`、页面「生成等时面」按钮、
`GET /api/fig3/<id>/layers?missile=` —— **命中缓存直接给、没有才起后台任务**）。**逐块渲染**：每块跑完即渲染，
**沙盒块落地即置顶**（并设 `/fig4?job=`），不等其它块；同块只渲染一次，整任务 done 时仍出四块汇总表。

**判据（`-k four` 8 → 11）**：(a) 图3 块只扫**一枚**弹、就是基准弹、工况数 = 网格三维之积且有上限（≤600）、摘要带 `face`；
(b) 假 runner 拖慢图1 ⇒ 图4 块在别块仍 `running` 时已 `done` **且带 result**；
(c) 真起 `ThreadingHTTPServer` + 真跑一段 CPU 重的出图 ⇒ 长块期间 `/progress` 最慢 < 1.5 s **且终态必须是 `done`**
（作者自报：第一版只要求"不是 running"，那样**一开跑就 error 也能变绿** —— 属于"绿着但错"，自己抓出来并改强了）；
(d) 幽灵字段扫描加**正面样例**（`tag`/`tier`/`scene`/`n_dv` 必须在抓到的集合里）。

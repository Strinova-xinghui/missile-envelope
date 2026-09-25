# NOTES — 交接文档（结论优先；压缩上下文或换会话后看这一份即可接上）

**最后更新**：**已启用 git 管理**（`main` 分支，初始提交 `11a5976` = 启用前的全部状态）。
第二阶段——只维护 `fig_missile_bc_overlay_crossplot` 一张图并美化：
等时线步长 10 s → **1 s**、**线性拟合已彻底移除**、坐标轴范围/刻度分辨率**改用 `自动化分析` 工作流规格**（800~1110 / 2450~3850）。

---

## 0. 30 秒接上（新会话请按序执行）

```powershell
cd E:\导弹包线图
$env:PYTHONUTF8="1"          # 中文控制台
$env:PYTHONPATH="src"        # 免安装直接跑仿真器

git log --oneline -5         # 已启用 git：main 分支，先看最近提交
git status -s                # 应干净

python -c "import sys; sys.path.insert(0,'scripts'); import missile_metrics; [print(r['label'], round(r['dv'],1), round(r['bc'],1)) for r in missile_metrics.current_missiles()]"
python -m missile_sim                    # 单工况自检（应输出 命中 60.81 s）
python tests\run_tests.py                # 61 项自检（约 90~240 s）
```

读文档顺序：**本文件 → `README.md`（权威规范：模型/口径/产物/局限）→ `AGENTS.md`（仓库约定、数据源、提交约定）**。

---

## 1. 一句话状态

`E:\导弹包线图` 下有一套完整可跑的**简化模型弹道仿真器**（T=0+ 瞬时燃烧 + 0.3 s 后高抛 + 比例导引/动态解锁导引比），
默认工况 50 km 迎头命中 **60.81 s**；能出 **ΔV×BC 平面的等命中时间线**（扫描图 2 s 步长），
另有**交叉图**与**完整工作流**（命令行 / JSON / 网页表单 → 出对比图）。
**第二阶段起只维护交叉图 `figures/fig_missile_bc_overlay_crossplot.(png|pdf|svg)`**：等时线 1 s、无拟合线、
坐标轴规格照抄 `自动化分析` 工作流。
弹值口径 = **最新版**（工作区 blkx = 实机 2.59.0.11），公式见 §3。

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
* 基准单工况（ΔV=865.3、BC=3624）：50 km 迎头命中 60.81 s、最高 14 970 m、命中点 366.5 m/s、高抛 14.27 s 结束
* 高抛角（50 km）：0°→67.31 s/213 m/s；22°→60.81 s/366 m/s；39°→60.14 s/417 m/s
* 距离：70 km 无高抛能量耗尽未命中，有高抛 92.59 s 命中
* 网格：360/360 全命中，t_hit 45.5~86.6 s，每个 ΔV 列内 t_hit 随 BC 严格递减（等时线成立前提）
* 交叉图网格（1 s 等时线专用）：ΔV 800~1110 /10 × BC 2450~3850 /25 = **1824/1824 全命中**，
  t_hit **53.4~73.9 s**（≈ 20 条等时线：54~73 s），仿真 ~25~35 s
* 自检：`python tests\run_tests.py` → **61/61 通过**

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
| 阻力标定 | `configs/baseline_aim120c5.json` 的 `drag.drag_base`（现 1.0）；单工况可直接 `--drag-base` |
| 换弹/换口径 | `scripts/build_missile_sources.py` + `--source latest/base257`；`configs` 里 `mass.mass_anchor`、`Case.mass` |
| 扫描范围/步长 | `--dv-min/max/step`、`--bc-min/max/step`、`--iso-step`；交叉图默认 ΔV/10 × BC/25（配 1 s 等时线） |
| 换图规格/版式 | `scripts/make_missile_bc_overlay.py` 顶部常量：`FIG_SIZE/FIG_DPI/XLIM/YLIM/X_MAJOR/X_MINOR/Y_MAJOR/Y_MINOR/ISO_CMAP/AX_RECT/LBL_OFFSETS`；轴规格来源 = `自动化分析/skills/wt-aam-analysis/references/charts.md` §一 |
| 多工况批量 | `missile_sim.simulate_batch(cfg, dv, cxk, theta_loft_deg=…, target_alt=…, mass=…)` 返回 `BatchResult`（扁平数组） |
| 单工况含弹道 | `missile_sim.simulate_one(cfg, Case(...), record_trace=True, stride=n)` → `SimResult.trace` |
| 网页/脚本集成 | `scripts/workflow.py::run_workflow(cfg_dict, verbose=…)` 返回带 `_paths` 的汇总字典 |
| 用现成的外部工作流 | `E:\WT\War-Thunder-Datamine\自动化分析\skills\wt-aam-analysis\scripts\run_plot.py`（旧 vs 新 + 箭头 + adjustText 风格） |

---

## 7. 未解决 / 已知偏差

1. **绝对阻力水平未标定**：`CxK` 按游戏口径本就与马赫数无关；偏差来自未对 `dragCx` 与 `CxK` 的合成口径做标定，
   表现为 50 km 命中点 366 m/s，比公开资料同量级弹偏低。`drag.drag_base` 是标定旋钮（现 1.0）。
2. 目标不机动、等高平飞；未建模离轴角、导引头锁定距离、中制导/数据链、引信延时、杀伤概率。
3. 测试运行器自建（pytest 因网络受限装不上），语法兼容但功能子集（无 `-x/--lf`）。
4. `terminal_gamma_err_deg` 只在擦碰工况有意义（正命中时最近点距离为 0）。
5. WT.xlsx 表内 PL-12 / PL-12A 各有重复列（X/Y、Z/AA），当前取 Y/AA；改 `scripts/wt_missiles.py` 的 `PREFERRED`。
6. 未把 `自动化分析` 工作流整体接进来（只复用公式、tag 取数与 `charts.md` 的轴/网格规格）。

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

---

## 10. 下一步可做（未确认，供下阶段选择）

1. **继续美化交叉图**：点标签是否带 t_hit（如 `120C 59.9 s`）、等时线加粗/加白描边、要不要背景渐变、
   是否改成"命中时间更快→更慢"的方向提示箭头
2. **阻力标定**：用 10 km / 0.9M 迎头等公开量级反推 `drag_base`，再看等时线整体平移多少（图会立刻变样）
3. **目标机动**：给目标加平飞外机动（蛇形/俯冲），观察等时线形状变化
4. **换坐标轴口径**：`--xlim/--ylim` 走 `plot_version_compare.py` 的宽轴规格（800~1150 / 1900~3800）
5. **其它工况的交叉图**：`--range 30000`、`--vt -450`、`--target-alt 8000` 各出一张，看等时线族如何整体移动
6. **接外部工作流**：把 `自动化分析` 的"旧 vs 新 + 箭头"风格并进来，做版本对比图

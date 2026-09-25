# 简化模型导弹弹道仿真器与等命中时间线

2D 纵向平面的点质量弹道仿真：**T=0+ 瞬时完成燃烧加速** → **0.3 s 后进入高抛** → **高抛结束后比例导引（导引比按剩余命中时间动态解锁）**。
默认参数取自 AIM-120C5（`us_aim_120c_5.blkx`，War Thunder 2.59.0.11），输出**命中时间**，并进一步给出
`ΔV_total × 弹道系数 BC` 平面上的**等命中时间线**（扫描图默认步长 2 s，交叉图见 §8 用 1 s）。

---

## 1. 快速开始

```powershell
$env:PYTHONUTF8="1"                 # 中文输出
$env:PYTHONPATH="src"               # 免安装直接用

# 单工况（默认：10 km、50 km、发射 300 m/s、目标 -300 m/s 迎头、高抛 22°）
python -m missile_sim
python -m missile_sim --vm0 300 --vt -450 --alt 10000 --range 70000 --loft 30
python -m missile_sim --dv 1200 --bc 3000          # 指定总增速与弹道系数

# 参数扫描 + 等命中时间线（默认 15×24=360 工况，约 10 s）
python -m missile_sim --sweep --tag baseline
python -m missile_sim --sweep --bc-step 50 --dv-step 25 --tag fine

# 脚本入口
python scripts\run_baseline.py --loft-family       # 单工况 + 高抛角对比图
python scripts\run_ranges.py                       # 多距离：无高抛 vs 有高抛
python tests\run_tests.py                          # 61 项自检（无需 pytest）

# 版本管理（2026-09-25 起启用，main 分支）
git log --oneline -5
git status -s

# 若装了 pytest，也可以用：
python -m pytest tests -q
```

依赖：Python 3.11+（本项目在 3.14.7 上开发）、numpy、matplotlib。测试与绘图不需要额外依赖。

### 文档顺序

1. **`NOTES.md`** —— 先看这一份：30 秒接上、产物清单、权威口径、下一步接口、踩坑记录
2. `README.md` —— 模型口径、参数、结果、局限（**权威规范**）
3. `AGENTS.md` —— 仓库约定、数据源、**git 提交约定**（"Version Control" 段）

提交约定（细节见 `AGENTS.md`）：一个交付阶段一次提交，只 `git add` 本阶段涉及的文件；
`figures/` 与 `results/` 照常入库（它们是交付物，且可用 §5 的命令复现）；
缓存与临时文件已在 `.gitignore` 中排除；`.gitattributes` 固定 `* -text`，**不要开 `core.autocrlf`**。
行尾本来就是混的（`AGENTS.md`、`README.md`、`scripts/workflow.py` 与**全部 `results/*.json|csv`** 是 CRLF
——后者是 Python 在 Windows 上 `write_text()` 的默认行为；`src/`、`tests/`、`configs/`、`NOTES.md` 是 LF），
原样入库即可。另外 `results/*.json` 里含运行时信息（耗时、工况数），重跑后出现 diff 属正常。

### 其他入口

* 调参：改 `configs/baseline_aim120c5.json`，或用命令行覆盖（`--vm0/--vt/--alt/--range/--loft/--dv/--bc/--drag-base/--hit-radius`）
* 敏感性分析：`python scripts\calibrate.py`、`python scripts\calibrate_loft.py`
* 调试某条弹道：`python scripts\debug_terminal.py`（终端导引时序）、`python scripts\compare_paths.py`（两条路径逐步对照）

### 输入约定（重要）

| 输入 | 含义 |
| --- | --- |
| `--vm0` | 发射方速度 [m/s] |
| `--vt` | 目标速度 [m/s]，**负值 = 迎头（距离闭合）**，正值 = 尾追（距离拉开），0 = 静止靶 |
| `--alt` | 双方高度 [m]（同高度平飞） |
| `--target-alt` | 目标高度 [m]，默认等于 `--alt`；与发射高度不同即构成高度差交战 |
| `--range` | 初始距离 [m]（双方同高时等于水平距离；有高度差时为水平距离） |
| `--loft` | 高抛角 [度]，**必须在 [0, 40) 内**，默认 22°（= AIM-120C5 `loftElevation`） |
| `--dv` | 总增速 ΔV [m/s]，默认取 AIM-120C5 火箭方程值 865.3 m/s |
| `--bc` | 弹道系数，默认取 `CxK=1.225` 对应值 3624 |

---

## 2. 模型定义（唯一权威口径）

坐标：`x` 水平指向目标初始方向为正，`h` 向上为正；`gamma` 为速度方向角（抬头为正）。

### 2.1 瞬时燃烧（T=0+）

* `t=0` 瞬间把 `ΔV_total` 一次性加到弹速上：`V(0+) = vm0 + ΔV_total`，之后**全程没有推力项**；
* 质量全程取干重锚定值 `m_end = 110.223 kg`；
* **ΔV 只改变等效比冲，不改变质量**（按用户确认，反现实但为设计选择）：
  `Isp_eq = ΔV / g0`，基准 865.3 m/s ↔ 88.2 s；
* 对照量：AIM-120C5 原始数据 `m0=161.4789 kg`、`massEnd=110.223 kg`、`force=15542 N`、`timeFire=7.75 s`
  ⇒ `ve = 2266 m/s`、`Isp = 231 s`，按火箭方程给出 `ΔV = 2266·ln(161.4789/110.223) = 865.3 m/s`（落在扫描区间 [800,1500] 内）。

### 2.2 力与加速度

```
rho(h) = rho0 · poly(c, min(h,hMax)) · hMax/max(hMax,h)      # War Thunder 大气多项式
c = [1, -9.59387e-5, 3.53118e-9, -5.83556e-14, 2.28719e-19], rho0 = 1.225, hMax = 18300
a_drag = -(0.5 · CxK · drag_base · S_ref / m) · rho(h) · V²   # 只有零升阻力
dV/dt  = a_drag − g·sin(gamma)                                # g = 9.81 m/s²（AGENTS.md 记录的运行默认值）
dgamma/dt = a_perp / V ,  |a_perp| ≤ 35 g                     # 法向过载上限 = finsLatAccel / reqAccelMax / loadFactorMax
S_ref  = π · (d/2000)² = 0.024829 m²,  d = 0.1778 m           # AGENTS.md 的 BC 公式口径
```

**显式忽略**：升力、诱导阻力、`a_perp` 与阻力的耦合（只有一条零升阻力抛物线）；转弯由法向加速度指令直接给出。

### 2.3 阶段机

| 阶段 | 时间/触发 | 控制律 |
| --- | --- | --- |
| **BOOST** | `t ∈ [0, 0.3)` | 纯弹道滑行（`a_perp = 0`），0.3 s 对应 blkx 的 `warmUpTime` |
| **LOFT** | `t ≥ 0.3` 起 | 有界速率控制器把 `gamma` 拉向 `+θ_loft`：`a_perp = clamp(k_loft·(θ_loft−γ)·V, ±35 g)`，`k_loft=1.5 1/s` |
| **PN** | 高抛退出后 | 比例导引：`a_perp = N_eff·Vc·λ̇`，限幅 35 g |

**高抛退出判据**（任一满足，且需连续 2 步 + 最短高抛 2 s）：

1. **下沉角**：`γ − λ ≥ 60°`（视线已经远低于速度矢量）；
2. **高度增量**：`h − h0 ≥ 4000 m`（默认**实际生效**的就是这一条，约在 t≈14 s、爬升约 4~5 km 时触发）；
3. **高抛时长**：`t − 0.3 s ≥ 20 s`；
4. **下压兜底**：`V_h ≤ 0`。

> 为什么不是"γ 降到视线角就退出"：高抛段主动把速度矢量顶在 `+22°`，`γ` 不会自己下降，
> 用固定几何式会导致导弹一路爬到能量耗尽（实测 120 s 都到不了顶点）。见 §7 踩坑记录。

### 2.4 导引比动态解锁

`N_eff = n_base · K_go(T_go)`，`n_base = propNavMult = 6.0`，`K_go` 直接取 AIM-120C5 的
`timeToHitToGain{0,1,2}`：

| `T_go` [s] | `<10` | `10→25` | `25→50` | `>50` |
| --- | --- | --- | --- | --- |
| `K_go` | 1.0 | 1.0→0.8 | 0.8→0.5 | 0.5（不外推） |

`T_go = range / max(Vc, 100)` 经一阶低通（`τ = 0.5 s`）后查表。本模型只有**一次解锁**（高抛结束后即进入 PN），
没有中段/末段两段式切换。

### 2.5 终止与命中

* **命中半径 = 12 m**，取自 blkx `proximityFuse.radius = 12.0`（近炸引信作用半径）；命中时刻在跨越该半径的那一步内线性内插；
* 未命中分四类：`no_hit_timeout`（120 s 上限）、`no_hit_slowdown`（`V < 150 m/s`）、`miss_overshoot`（`Vc<0` 且距离 > 5 m）、`miss_recede`（全程未接近）；
* 积分：固定步长 RK4，`dt = 0.005 s`；命中时间对步长已收敛（0.02→0.001 s 变化 < 0.15 s，见 `tests/test_sim.py`）。

---

## 3. 参数扫描与等命中时间线

* **行**：`ΔV_total ∈ [800, 1500]`，步长 50 → 15 行；
* **列**：`BC ∈ [1700, 4000]`，步长 100 → 24 列（合计 360 工况，向量化后约 10 s）；
* 每个网格点**只改 ΔV 与 BC**，其余（发射/目标速度、高度、距离、高抛角 22°、过载上限）全部固定；
* `BC` 反解 `CxK = m_end / (BC · S_ref)`：默认 BC 1700→4000 对应 **CxK 2.604→1.107**
  （基准 BC=3624 ⟺ CxK=1.225，与 blkx 原值自洽）；图上副轴同时标注 CxK；
* **等时线**：直接在 `t_hit(ΔV, BC)` 网格上做 marching squares 等值线（双线性插值），层级为 2 s 步长；
  未命中点 `t_hit = NaN`，等值线在该区域**自动断开**，不会被插值掩盖。

### 产物

| 文件 | 内容 |
| --- | --- |
| `results/cases_baseline.csv` | 逐工况：ΔV、BC、CxK、等效比冲、状态、命中时间、终止时刻、最小距离、最大高度、命中点速度、终端航向误差、高抛结束时刻 |
| `results/isolines_baseline.csv` | 每条等时线的折线顶点：`t_hit_level, bc, cxk, dv_total, segment_index` |
| `results/summary_baseline.json` | 完整配置快照 + 派生量 + 网格定义 + 命中统计 + 等时线层级 |
| `figures/fig_sweep_isotime_baseline.png` | **主图**：散点按命中时间着色 + 2 s 等时线 + 未命中灰 × + AIM-120C5 基准点 |
| `figures/fig_baseline_time_baseline.png` | 固定 BC 时命中时间 / 命中点存速 随 ΔV 的变化 |
| `figures/fig_traj_baseline.png` | 单工况弹道剖面、速度衰减、航向角 |
| `figures/fig_loft_family_baseline.png` | 高抛角 0/10/22/30/39° 的弹道与存速对比 |
| `figures/fig_range_sweep.png` | 20~90 km 各距离下 无高抛 vs 高抛 |

> `terminal_gamma_err_deg` 记录的是**最近点处**速度方向与视线的夹角（由相邻两步按线性运动内插得到），
> 只在"擦碰/勉强够到"的工况下才有判别意义；正命中工况的最近点距离为 0，该角度接近 0 或受采样影响，
> 不要把它当作命中精度指标——命中精度看 `min_range_linear_m`。

---

## 4. 基准结果（默认工况）

工况：发射 300 m/s、目标 −300 m/s（迎头）、双方 10 km、距离 50 km、高抛 22°、
`ΔV = 865.3 m/s`、`CxK = 1.225`（BC = 3624）。

| 量 | 值 |
| --- | --- |
| 状态 | **命中** |
| 命中时间 | **60.81 s** |
| 引信半径 / 步内最接近距离 | 12 m / ≈0 m |
| 高抛结束时刻 | 14.27 s（爬升约 4.97 km） |
| 最大高度 | 14 970 m |
| 命中点速度 | 366.5 m/s |
| 终端航向误差 | −11.27° |

扫描网格：**360/360 全部命中**，命中时间 45.5~86.6 s，每个 ΔV 列内 `t_hit` 随 BC **严格递减**
（等时线成立的前提已由测试与运行期断言双重校验）。

### 高抛的作用（同工况、只改高抛角）

| 高抛角 | 命中时间 | 命中点速度 | 最大高度 |
| --- | --- | --- | --- |
| 0° | 67.31 s | 213 m/s | 10 000 m |
| 10° | 63.01 s | 305 m/s | 12 705 m |
| **22°（默认）** | **60.81 s** | **366 m/s** | 14 970 m |
| 30° | 60.18 s | 389 m/s | 15 859 m |
| 39° | 60.14 s | 417 m/s | 17 084 m |

### 距离维度（无高抛 vs 高抛 22°）

| R0 | 无高抛 | 高抛 22° |
| --- | --- | --- |
| 20 km | 命中 18.97 s / 515 m/s | 命中 22.41 s / 575 m/s |
| 35 km | 命中 40.41 s / 316 m/s | 命中 39.27 s / 443 m/s |
| 50 km | 命中 67.31 s / 213 m/s | 命中 60.81 s / 366 m/s |
| 70 km | **未命中（能量耗尽）** | 命中 92.59 s / 325 m/s |
| 90 km | **未命中（能量耗尽）** | 未命中（超时，最近 3.8 km） |

近距（20 km）高抛略增飞行时间，中远距同时改善命中时间与存速，70 km 处是"能否够到"的分界。

---

## 5. 已验证 / 未验证

**已验证（自动测试，`python tests\run_tests.py` → 61 项全绿）**

1. 大气：`rho(0)=1.225`、`rho(10 km)≈0.414`、`h>18300` 时按 `18300/h` 衰减、单调递减；
2. 参数换算：`BC↔CxK` 往返、`S_ref`、`ΔV = ve·ln(m0/m1)`、阻力系数 `1.3797e-4 1/m`；
3. 视线几何：碰撞航路 `λ̇ = 0`、解析 `λ̇` 与有限差分一致、接近/远离符号正确、标量与数组实现等价；
4. 导引比：分段线性取值（10/17.5/25/50 s）、区间夹取、数组与标量一致；
5. 物理一致性：**无阻力无重力时是精确匀速直线**、阻力使速度单调衰减、0.3 s 前不机动、
   高抛段 phase 顺序正确、过载不超限、导引比末段解锁到 1.0；
6. 命中/边界：基准工况命中、近距快速命中、尾追远处如实报未命中、抬速度下限触发能量耗尽、
   起始即在引信半径内、高抛角 ≥40° 报错、命中时间对 `dt` 收敛；
7. **两条实现路径一致性**：标量单工况与数组批量在命中判定、步内最接近距离、最大高度、终止速度上一致；
8. 等时线：合成线性场中抽取的等值线位置正确、NaN 区域不进入、全 NaN 返回空、单调性检查能报出违例；
9. 目标高度差可用（`Case.target_alt` 与 `scenario.target_alt` 两种指定方式等价、批量路径同样支持）；
10. 逐工况质量覆盖（`Case.mass` / `simulate_batch(mass=...)`）：更重的弹同一 CxK 下存速更高，
    阻力系数与质量成反比，非法质量报错；
11. 产物：CSV 列/行数、状态名合法性、JSON 统计自洽。

**未验证（重要局限，勿当作武器性能结论）**

* **绝对射程/存速没有对标真值**。模型用固定 `CxK`，而 `CxK` 按游戏口径就**与马赫数无关**（没有阻力峰、没有马赫数依赖），
  所以这里不存在"模型缺了马赫数依赖"这回事；偏差来自我们**没有对 `dragCx`（寄生阻力）与 `CxK` 的合成口径做标定**。
  表现为 50 km 迎头命中点约 366 m/s，明显低于公开资料中同类弹的量级，即当前口径整体偏保守（阻力偏大）。
  `drag_base` 即为此预留的标定旋钮（见 §6）。
* 目标模型是**等高直线平飞、不机动**（高度差已支持：`--target-alt`）；没有考虑目标过载、导弹最大离轴角、中制导/数据链丢失、导引头锁定距离等。
* 单脉冲瞬时燃烧抹掉了真实推力曲线，近距/低空工况的初段弹道与实际差异最大。
* 未建模引信延时（`fuseDelayDist = 0.4 m`）、杀伤概率；命中判定只有几何半径。

---

## 6. 可调参数与标定旋钮

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `drag.drag_base` | 1.0 | 有效阻力系数标定旋钮。>1 更保守、<1 更接近公开存速量级；改动它会让全部命中时间整体平移 |
| `sim.hit_radius` | 12.0 | 近炸引信作用半径（blkx `proximityFuse.radius`） |
| `sim.theta_loft_deg` | 22.0 | 高抛角，`[0, 40)` |
| `sim.loft_dh_gain_max` | 4000 | 高度增量退出阈值；调大爬升更高、末段存速更高但也更耗时 |
| `sim.loft_time_max` | 20.0 | 高抛时长上限（防止无限爬升） |
| `sim.a_lat_max_g` | 35.0 | 法向过载上限（blkx `finsLatAccel`/`reqAccelMax`/`loadFactorMax`） |
| `sim.dt` | 0.005 | RK4 固定步长；命中时间对步长已收敛 |

用 `scripts/calibrate.py` 可整体复现"阻力标定 × 高抛退出参数"的敏感性扫描。

### 关于 ΔV 与质量约定的取舍（必须知道）

按需求约定"ΔV 改变比冲、不改变质量"，因此扫 ΔV 时质量恒为干重 110.223 kg——**弹体质量是定值，这是设计前提**。
这**不是物理上可实现的**（同一枚弹无法在不增加装药的情况下增加总冲），它的作用是：
把 ΔV 当作**纯粹的能量预算**，让等时线回答"若给这枚弹多少速度增量、配多大弹道系数，命中时间会是多少"。
`configs` 的 `mass.mass_anchor` / `Case.mass` 只是把这个定值换成别的数（例如按某型弹的干重跑一条弹道），
**不需要**为散点图上的各型弹分别改质量。

---

## 7. 实现与踩坑记录（避免重复踩）

**架构**

```
src/missile_sim/
  atmosphere.py   WT 大气多项式 + 声速/马赫（仅诊断）
  ballistics.py   视线几何、λ̇ 解析式、导引比查表、高抛退出判据（标量/数组双实现）
  decide.py       阶段机、制导指令、终止判定（两条路径共用的唯一决策核心）
  config.py       dataclass 配置 + BC/CxK、ΔV/Isp、S_ref 派生与校验
  sim.py          _ScalarSim（单工况快路径）+ simulate_batch（向量化批量，活跃工况压缩）
  sweep.py        网格、CSV/JSON 写出、等时线提取、单调性校验
  plot.py         主图（散点+等时线）、基准曲线、弹道族、高抛族
  cli.py          `python -m missile_sim`
```

**关键设计决策**

* **两条路径、一个决策核心**：`decide.py` 里的阶段机/制导/终止判定被标量与数组路径共同调用，
  物理逻辑不可能出现两份。标量路径用纯 float（numpy 长度-1 数组的开销会让单工况慢 10 倍以上）。
* **批量路径的活跃工况压缩**：已终止的工况每 200 步被剔除并回写全局数组，
  否则 360 工况 × 24000 步会做大量无用功（实测 10 s 完成）。
* **终止状态一经写入即冻结**：否则"命中之后继续推进"会被后续的 `miss_overshoot` 覆盖成脱靶
  （曾导致 360 工况只有 13 个命中，实际是 360/360）。
* **步内最接近距离（`min_range_linear`）**：用相邻两步的距离与视线角按线性运动解析求最近点，
  消除了"最小距离只有采样点决定"的假象（曾出现"最小距离 1.35 m 但 T_go 导引项很小"的误判）。
* **批次 CSV 与图都能复现**：所有产物可由同一条命令重跑，无随机数；`summary.json` 内嵌完整配置。

**踩过的坑（都已修）**

1. 高抛退出用 `γ ≤ 视线角`：高抛段把 `γ` 顶在 +22°，该判据永远不满足 → 导弹爬到 120 s 能量耗尽。
   现改为"下沉角阈值 / 高度增量 / 时长上限 / 下压兜底"四选一，默认由高度增量触发。
2. 命中半径原本取 0 m：末段 10~16 m 的擦碰被判成脱靶。按用户提示改用 blkx 近炸引信半径 12 m。
3. 批量路径命中状态被覆盖（见上），以及 `t_hit` 被后续步重算成 NaN。
4. `prev_rng = rng`（未 copy）导致步内距离插值用错起点。
5. 裁剪时把循环变量 `m` 用作 `keep`，破坏了收尾写回。
6. `np.float64` 是 `float` 的子类，`isinstance` 分派会让 numpy 标量误入标量路径 → 统一用
   "是否纯 Python 标量"判定。
7. 缓存 `.pyc` 与源码不一致曾造成"改了不生效"的假象；改完源码后如行为异常，先清 `__pycache__`。

**调试脚本**（`scripts/`）保留下来，用于复现上述问题的定位过程：

| 脚本 | 用途 |
| --- | --- |
| `debug_terminal.py` | 打印末段（最后 60 步）的视线几何、λ̇、导引指令、T_go，用于判断脱靶成因 |
| `debug_hit_detect.py` | 用批量逻辑逐行打点，复现"命中被后续状态覆盖"这类判定缺陷 |
| `debug_batch_membership.py` | 对比"单独跑一个工况"与"整网格跑"的结果，排查批处理自身缺陷 |
| `compare_paths.py` | 标量路径与数组路径逐步对照（最大距离差应 ≈0） |
| `check_consistency.py` | 跨 dt、跨工况的命中判定一致性检查 |
| `extract_missile_points.py` | 从 blkx 复算各型弹 (ΔV, BC) 并做线性拟合，写 `results/missile_points.json` |
| `make_missile_bc_overlay.py` | 交叉图（§8）：等时线（1 s）+ 各型弹散点，**不含线性拟合** |
| `smoke_baseline.py` | 最小冒烟：参数表 + 单工况结果 |

---

## 8. 交叉图：等时线 × 各型主动弹（ΔV–BC 散点）

python scripts\make_missile_bc_overlay.py（默认 50 km 迎头、10 km、高抛 22°、引信 12 m、等时线 1 s）

* `figures/fig_missile_bc_overlay_crossplot.png`（同目录另有 `.pdf` / `.svg` 矢量版，默认一起生成）
  —— 横轴 ΔV、纵轴 BC；**蓝色曲线 = 本仿真器的等命中时间线**（按命中时间着色 + 右侧色标）；
  **红点 = 最新版弹值（工作区 blkx = 实机 2.59.0.11）**，120C 加环标注为高抛基准。
* `results/missile_shot_crossplot.json` —— 各型弹在该弹道下的逐条结果（命中时间 / 存速 / 最大高度）+ 本图全部出图参数。
* 口径固定为最新版；如需历史对照可用 `--source base257`（2.57.1.132 基线）。

**图规格（2026-09 起，勿自行改）**

| 项 | 值 | 来源 |
| --- | --- | --- |
| 画布 | `figsize=(12, 6.8)`、`dpi=110`、白底、PNG 300 dpi | 自动化分析 `references/charts.md` §一 |
| 横轴 | 800~1110，主刻度 30 / 次刻度 10 | 同上（`aam_fit` 当前版收紧规格） |
| 纵轴 | 2450~3850，主刻度 100 / 次刻度 50 | 同上 |
| 网格 | 主 `alpha .35 lw .8`、次 `alpha .18 lw .5`、`axisbelow` | 同上 |
| 等时线 | 步长 1 s（`--iso-step`），线色深→浅 = 命中时间短→长 | 本仓库 |
| 网格分辨率 | ΔV 每 10 m/s × BC 每 25（32×57 = 1824 工况，约 30 s） | 本仓库（1 s 间距 ≈ 39 m/s ≈ 110 BC，故取此步长） |
| 线名 | 贴出口边框（右边/下边）自动排布，每条线一个标签 | 本仓库（避免压中部弹型标签） |
| **线性拟合** | **已移除**：拟合线与 R² 不再计算、不再出现在图上 | 等时线取代其功能 |
| **出图可复现** | PNG / PDF / SVG **逐字节可复现**：savefig 不写创建时间，SVG 的随机元素 id 顺序化为 `id_00000…` | 本仓库（重跑后 `figures/` 无假 diff，见 NOTES §8） |

```powershell
python scripts\make_missile_bc_overlay.py                       # 默认：1 s 等时线 + 着色 + 色标
python scripts\make_missile_bc_overlay.py --no-colorbar         # 单色蓝线版
python scripts\make_missile_bc_overlay.py --iso-step 2          # 恢复 2 s 步长
python scripts\make_missile_bc_overlay.py --xlim 800,1110 --ylim 2450,3850
python scripts\make_missile_bc_overlay.py --range 30000 --vt -450 --formats png,pdf,svg
```

### 权威口径（唯一来源）

E:\WT\War-Thunder-Datamine\自动化分析\skills\wt-aam-analysis\scripts\plot_version_compare.py 的 metrics()，
在本仓库复刻为 scripts/missile_metrics.py（逐行同式，勿在别处另写一份）：

```text
fu1 = mass - massEnd                      # 一级装药
fu2 = massEnd - massEnd1                  # 二级装药（无 massEnd1 时为 0）
ΔV  = (force*timeFire/(9.81*fu1))*9.81*ln(mass/(mass-fu1))
    + (force1*timeFire1/(9.81*fu2))*9.81*ln((mass-fu1)/(mass-fu1-fu2))   # 有二级时
dry = mass - fu1 - fu2                    # = massEnd1（干重）
BC  = dry / (CxK * (caliber/2)^2 * pi)    # caliber 在 blkx 里已是【米】
```

两个曾算错的坑（务必避免）：

1. 只读 mass - massEnd 当**全部**装药并按单级算 —— blkx 的二级装药在 massEnd1 里，
   mass - massEnd 只是**一级**（120A 会从 820.5 被算成 252，PL-12 从 932.6 变 490）。
2. 把 caliber 当毫米 —— blkx 里是米（0.1778），要换算再平方，否则 BC 差几个量级。

### 最新版弹值（图上 11 型，WORK = 2.59.0.11）

| 弹 | ΔV | BC | t_hit（50 km 迎头） | 弹 | ΔV | BC | t_hit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 120A | 820.5 | 3609.0 | 62.2 s | PL-12 | 932.6 | 3078.1 | 63.3 s |
| 120C | 897.4 | 3624.0 | 59.9 s | PL-12A | 989.1 | 3245.9 | 60.4 s |
| 120D | 891.3 | 3653.8 | 59.9 s | R-77 | 965.7 | 2568.8 | 67.9 s |
| AAM-4 | 826.3 | 3683.9 | 61.5 s | R-77-1 | 1099.5 | 2705.6 | 63.2 s |
| MICA EM | 947.0 | 2636.0 | 67.6 s | Derby | 932.8 | 2567.0 | 68.8 s |
| R-Darter | 913.9 | 2631.2 | 68.5 s | | | | |

拟合 BC = -3.942·ΔV + 6752.4（R² = 0.391）——**该拟合只保留在 `results/missile_sources_all.json` 里供数据源对照，
图上已不再画拟合线**。以上数值可用 python scripts\version_metrics.py 复现。

**质量口径（重要）**：仿真器里的弹体质量是**定值**，即干重锚定值 m_end = 110.223 kg，
扫 ΔV 时不变——这是本模型的设计前提，不需要让它随弹型变（各组弹点只是被送进同一条弹道做对比）。

---

## 9. 完整工作流（自定义输入 → 仿真 → 对比图）

三个入口，同一套 `run_workflow()`（`scripts/workflow.py`）：

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"

# 1) 命令行 + 输入文件
python scripts\workflow.py run --config configs\workflow_example.json
python scripts\workflow.py run --set scenario.range=70000 --set sim.theta_loft_deg=30 --set compare.tag=t30

# 2) 本地网页表单（标准库实现，无第三方依赖）
python scripts\workflow.py web        # 打开 http://127.0.0.1:8765/ 填参数 → 生成 → 页面直接看图

# 3) 代码调用
python -c "import sys; sys.path.insert(0,'scripts'); import workflow; workflow.run_workflow({...})"
```

### 输入项（`configs/workflow_example.json` 为模板）

| 段 | 字段 | 含义 |
| --- | --- | --- |
| `scenario` | `vm0` / `vt` | 发射方 / 目标速度 [m/s]，**`vt` 为负=迎头** |
| | `alt` / `target_alt` | 发射高度 / 目标高度 [m]（可不同高） |
| | `range` | 初始水平距离 [m] |
| `sim` | `theta_loft_deg` | 高抛角，**必须在 [0, 40)** |
| | `hit_radius` | 命中半径 [m]（默认 12 = blkx 近炸引信半径） |
| | `dt` / `t_life` | 积分步长 / 飞行时限 |
| `sweep` | `dv_min/max/step` | 等时线网格的 ΔV 范围与步长 |
| | `bc_min/max/step` | 等时线网格的 BC 范围与步长（工况数 = 行×列） |
| `compare` | `iso_step` | 等时线步长 [s] |
| | `title` / `tag` | 图标题 / 产物文件名后缀 |

### 产物

| 文件 | 内容 |
| --- | --- |
| `figures/workflow_<tag>_main.png` | **主对比图**：等时线 + 最新版弹点与拟合 + 当前基准星标 + 逐弹结果表 |
| `figures/workflow_<tag>_detail.png` | 细节：同 ΔV 下 t_hit–BC、t_hit–初始距离、弹道剖面 |
| `results/workflow_<tag>.csv` | 网格逐工况结果 |
| `results/workflow_<tag>_isolines.csv` | 等时线折线顶点 |
| `results/workflow_<tag>.json` | 汇总：输入、派生量、命中率、单调性校验、逐弹两套口径结果、产物路径 |

网页端要点：并发请求串行化处理、单次工况数上限 8000（超出直接提示）、失败时把 traceback 回显在表单页上、
只监听 `127.0.0.1`。

---

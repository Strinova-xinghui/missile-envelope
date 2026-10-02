# 图4：β–γ–ΔV 交互式三维散点（t_hit 着色 + 证据层）

> 分支 `fig4`。数据层 `src/missile_sim/fig4.py`、算核 `src/missile_sim/fig4scan.py`、
> 页面 `src/missile_sim/webui_static/fig4.{html,css,js}`、判据 `tests/test_fig4.py`（数据层 / 证据层 /
> 与 `bg3d` 的一致性 / 产物 / CLI，22 项）+ `tests/test_fig4_web.py`（路由 / 白名单 / 前端契约 / 真跑 JS，
> 12 项）—— `python tests\run_tests.py -k fig4` 一次跑完 **34 项**，约 6 s。
> 产物 `results/fig4_default*.{json,csv}` **已入库**（另有一份全脱靶的 `fig4_miss*`，见 §3.3）。
> 上一轮"β–γ–ΔV 三维图 + 等时面"的探究结论见 `docs/FIG-BG3D-FEASIBILITY.md`（本文是它的交付版）。

## 0. 一句话

**11 枚弹在同一套 (β,γ,ΔV) 网格上的点云，颜色 = t_hit**，三根轴都是物理参数（不是某一枚弹的标称值），
切换弹种**只换点云**（网格与色标范围共享）；**证据层**把"ΔV 那一维能不能用一条斜率（平面）说完"
量出来：默认立方体上，逐列一次拟合的残差中位 **1.38 s**、最大 **2.83 s**，二次项贡献占该列 ΔV 效应的
中位 **14%**、最大 **22%** —— 所以"平面假设失效"在这套网格上是**可测的**，不是一个说法。

## 1. 三根轴与口径（与图1/图2 同一套，别发明第四套）

| 轴 | 出口 | 说明 |
| --- | --- | --- |
| β（**≡ BC**） | `bg.scaling_for(..., beta=…)` → `cx_scale = β_blk/β` | 与图2 的横轴**是同一个数**（β ≡ BC，见下） |
| γ | 同上 → `cxaoa_scale = (γ/γ_blk)/cx_scale` | `γ ∝ cx_aoa`，即**诱导阻力/攻角阻力那一支的强度参数** |
| ΔV | 同上 → `thrust_scale = ΔV/ΔV_blk`（严格只动这一项） | **理想（真空等效）总增速**，与图1/图2 同口径 |

* ⚠ **β 与 BC 是同一个量**（定义都是 `m燃尽/(SD·CxK)`，见 `docs/BETA-GAMMA.md` §2.1），
  所以"轴写 (ΔV, BC, γ)"与"轴写 (ΔV, β, γ)"指的是**同一个三维空间**：
  图上的轴标签取 `figures.FIG4_AXIS_LABELS["beta"] = "β（≡ BC）…"`（Lead 2026-10-02 的口径是
  「轴写 (ΔV, BC, γ)，并注明 BC ≡ β」）。**不要**把它写成 (ΔV, BC, β)：那样两轴共线、
  参数化退化，而"扫出来的立方体"看起来仍然正常（`bg3d.axis_effects()` 的判据就是防这个的）。
* 三根轴在 `Scaling` 上是**可逆参数化**（`bg3d.axis_effects()` + `tests/test_bg3d_spike.py` 钉住），
  所以图上看到的每一朵点云都对应一组真实的内核乘数，不是三条轴各画一遍。
* **11 枚弹各自**用自己的 `(β_blk, γ_blk, ΔV_blk)` 做上面这条反解 ⇒ 同一个格点在不同弹上是**不同的
  乘数**，而轴上的坐标（物理量）是同一个。这正是"11 朵点云可横向比较"的前提。
* 颜色 = **t_hit** [s]（连续色标 + 刻度图例）；**脱靶没有 t_hit**，一律画成**空心**标记
  （形状不同，不靠颜色区分）——见 §3.3。

## 2. 网格与产物（默认值 = 用户拍板）

| 项 | 默认 | 出处 |
| --- | --- | --- |
| β | **7 点**，2500.00 ~ 3750.90 kg/m²（= 图2 的自适应域，含端点） | `figures.bg_axis(rows)` |
| γ | **7 点**，49.00 ~ 95.69 kg/m²（同上） | 同上 |
| ΔV | **5 点**，0.6 / 0.8 / **1.0** / 1.2 / 1.4 × 钉值 ⇒ 559.54 ~ 1305.60 m/s | `fig4.DV_FACTORS` |
| ΔV 钉值 | **932.5697 m/s**（PL-12 权威 ΔV，与图2 的 `dv_pin_ms` 同一个数） | `pool.metrics_of(standard).dv` |
| 每弹工况 | 5×7×7 = **245**；11 弹共 **2695** | — |
| 档位 / 并发 | `fast`（`compiled-c`）/ 8 | — |

* **11 弹的 (β,γ) 全部落在立方体内**：这一点是**故意**用"等分到图2 域端点"实现的。若改用
  `bg3d.make_grid3()` 的"向内对齐到整步长"，7 个点会把 β 下限抬到 2600，把 R-77（β=2568.8）与
  Derby（β=2567.0）挤出盒子 —— 而"图上没有它"会被读成"它不行"（坑见 `docs/FIG-BG3D-FEASIBILITY.md` §3，
  判据见 `test_fig4_default_grid_is_7x7x5_and_covers_the_pool`）。
* 重出产物（**一条命令**）：

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python -m missile_sim --figure fig4 --tag default          # ≈78 s（fast 档、2695 工况、冷缓存）
python -m missile_sim --figure fig4 --fig4-beta-n 5 --fig4-gamma-n 5 --fig4-dv-factors 0.7,1.0,1.3
python -m missile_sim --figure fig4 --fig4-dv 1000 --fig4-alt 8000 --fig4-speed 900 --fig4-n 15
```

  产物：`results/fig4_<tag>.json`（网格 + 11 个立方体 + 逐列拟合 + 判别量）与
  `results/fig4_<tag>_cases.csv`（**每工况一行**，2695 行）。
  `--figure fig4` **不在** `all` 里（图4 只出产物、不出静态图，且耗时是图1~图3 的量级）。

### 2.1 逐工况表（`fig4_<tag>_cases.csv`）

列序 = `record.FIG4_CASES`：

```
missile, beta_target, gamma_target, dv_target,
thrust_scale, cx_scale, cxaoa_scale,
n_star_g, R_ref, induced_dominated,
event, hit, t_hit_s, t_end_s, miss_distance_m, max_alt_m, v_impact_ms,
dv_measured_ms, t_burnout_s, backend, error
```

* 前三列是**坐标本身**，三个乘数是"这个格点落进求解器时到底改了什么"；
* `n_star_g` / `R_ref` / `induced_dominated` 是**判别量**（§3.4）；它只随 (β,γ) 与参考工况变，
  **同一根 ΔV 竖线上的 5 行同值**（判据钉住），别把它读成"这一炮打没打中"；
* `hit=0` 的行 **`t_hit_s` 留空**（不是 0 —— 写 0 会被读成"瞬间命中"）。

## 3. 证据层（这张图的主角之一）

用户论点：**"在诱导阻力主导的场合（大 γ），第三轴 ΔV 不再是常数偏移、平面假设失效"**。
可证伪的量全部按**逐 (β,γ) 列**（固定 β、γ，沿 ΔV 的那条竖线）定义：

| 量 | 定义 | 单位 | 图上怎么用 |
| --- | --- | --- | --- |
| `resid_lin` | `t_hit − (a + b·ΔV)`（逐列一次拟合） | s | 颜色模式 **线性拟合残差**（发散色标，0 在浅色中点） |
| `quad_term` | `c·(ΔV − ΔV̄)²` | s | 颜色模式 **二次项曲率**（单色相顺序色标，非负） |
| `curv_frac` | `\|c\|·(ΔV 跨度)²/4 ÷ 该列 ΔV 造成的 t_hit 跨度` | — | β–γ 小面板的默认热度（无量纲、可跨列比） |
| `rms_lin` / `rms_quad` | 逐列一次/二次拟合的残差 RMS | s | 小面板的第二个热度口径 |
| `plane` | **全局**最小二乘平面 `t ≈ c0 + c1β + c2γ + c3ΔV` | — | 3D 里的"拟合平面"层（等值面） |

三个**可开关**的图层：**拟合平面**（全局平面在盒子里的等值面，半透明；够不到的地方直接不画 ⇒
"这个平面在盒子哪个角落失效"是看得见的）、**逐 (β,γ) 列二次拟合曲线**（49 条母线，就是"拟合曲面"）、
以及"只看诱导阻力主导"筛选（点云与曲线一起过滤）。

### 3.1 实测（默认产物，2695 工况，2026-10-02）

| 量 | 11 弹中位 | 全场范围 |
| --- | --- | --- |
| 逐列一次拟合斜率 `b` | −0.0305 s/(m/s) | −0.0304 ~ −0.0322（弹间） |
| 一次拟合残差 RMS | **1.38 s** | 1.22 ~ **2.83 s** |
| 二次拟合残差 RMS | 0.142 s | 0.100 ~ 0.211 s（掉 ~10 倍） |
| 二次项占比 `curv_frac` | **0.140** | 0.130 ~ **0.220** |
| 端点抬升 `curv_span` | 3.51 s | 最大 **6.47 s** |
| t_hit 全场 | 34.69 ~ 68.62 s | — |
| 命中 | **2695 / 2695（100%）** | 默认网格里没有洞 |

**与上一轮 spike 的差异（必须一起读）**：`docs/FIG-BG3D-FEASIBILITY.md` §5 报的是残差 RMS 0.55 s、
曲率占比 9.2% —— 那一轮的 ΔV 轴是 **600~1100（跨度 500 m/s）**，本轮是 **559.5~1305.6（跨度 746 m/s）**。
抛物线拟合的残差随 ΔV 跨度的平方走，**所以"平面假设失效多严重"直接取决于你把 ΔV 扫多宽**；
两个数都对，但引用的必须带上跨度（本轮口径见 §2 表）。

### 3.2 "大 γ 角落是热点"——数据说什么（照实）

* **γ 方向确实同向**：77/77 个（弹, β）对上，`curv_frac(γ_max) > curv_frac(γ_min)`；
  从 γ≈49 到 γ≈96 的相对抬升中位 **2.6%**（1.1% ~ 26.2%）。
  合并全部弹后 `corr(γ, curv_frac) = +0.22`、`corr(γ, rms_lin) = +0.21`。
* **β 方向更强**：`corr(β, rms_lin) = −0.43`（**低 β 更糟**），而 `corr(β, curv_frac) ≈ −0.06`。
  极端例子：**120A**（ΔV 最低、最弱的弹）在低 β/大 γ 角落残差 **2.83 s**，而高 β/小 γ 角落 **1.35 s**（2.1 倍）。
* 结论（**不是**"右上角爆表"这么简单）：**"平面假设失效"随 γ 单调加深、但幅度是几个百分点的量级；
  真正把残差拉大的是低 β**。热力图把两者都画出来（热点框画在最大值那一格）——
  默认产物上 PL-12 的曲率热点在 **(γ=95.7, β=3750.9)**、残差热点在 **(γ=95.7, β=2500.0)**，
  也就是说**两个口径的热点都在最大 γ 那一行**，这一点支持用户论点；差距在于"有多大"。

### 3.3 命中 / 脱靶怎么区分

* 命中 = 实心圆盘、颜色 = t_hit；脱靶 = **空心圈**、固定色（来自 `figures.FIG4_MISS_COLOR`）。
* ⚠ **默认网格 2695 个工况全部命中**，所以**默认产物上看不到空心标记**（这是实测，不是 bug）。
  要看见它，用一份"打得着才有鬼"的小档（已入库，8 工况、秒级）：

```powershell
python -m missile_sim --figure fig4 --tag miss --missiles R-77 --range 80000 `
       --fig4-beta-n 2 --fig4-gamma-n 2 --fig4-dv-factors 0.5,0.7
# 8/8 全部脱靶 ⇒ /fig4?tag=miss 上就是 8 个空心圈
```

* 判据不靠"等于某个常量"：`命中色 ≠ 脱靶色`、**脱靶色不在 t_hit 色标里**、色标首末不同、
  脱靶标记名是 `hollow`（形状关系）—— 见 `test_fig4_hit_and_miss_are_distinguishable_by_more_than_a_constant`。

### 3.4 "是否诱导阻力主导"的判别量

`R = (n_ref/n*)²`，`n* = q/(Q·g0)`、`Q = sqrt(β·γ·F(M)/f(M))`，与**图2 的等 `n*` 线同一套口径**
（`bg.evaluate`，参考工况默认 10 km / 800 m/s、`n_ref = 20G`）：`R ≥ 1` ⇒ 诱导阻力项压过基础阻力项。
`γ` 本身（= 诱导阻力那一支的强度参数）也在 CSV/点云里，两个口径都能用。

* 默认产物上 **45/49 列** `R ≥ 1`（`R` 范围 0.83 ~ 2.44）：只有"低 β 且低 γ"那个角落在 `R < 1`。
  ⇒ 这个判别量在默认参考工况下**几乎全选中**，"筛选"作用有限；要让分界线动起来改
  `--fig4-n` / `--fig4-alt` / `--fig4-speed`（它们**不动任何一个点**，只动这条线）。
* ⚠ **判别量与"哪枚弹"无关**（物理必然：它只依赖 (β,γ) 与参考工况），11 枚逐值相同 ——
  用 `bg.evaluate` 独立复算对拍钉住（`test_fig4_induced_drag_columns_match_bg_and_ignore_the_missile`）。

### 3.5 判据能证伪（`-k fig4` 里的核心一条）

用**合成数据**做两组，断言残差/曲率能把它们分开：

| 组 | 构造 | 实测断言 |
| --- | --- | --- |
| 平移 | `t = base(β,γ) + b·ΔV` | `max|resid_lin| < 1e-9`、`curv_frac < 1e-9`、全局平面 `rms < 1e-9` |
| 强曲率（只在大 γ 列） | 低 γ 仍是直线，高 γ 列加开口向上二次项（8 s 幅度） | `max|resid_lin| > 1.0 s`、`max curv_frac > 0.2`、`curv_span > 5 s`、二次残差 < 一次残差的 1/50 |
| 两组比值 | — | **> 1e6**（判据失效当场红） |
| 热点位置 | — | 曲率/残差热点必须落在 `i_gamma ≥ ng/2`，低 γ 行必须干净；平移组**没有**热点 |

## 4. 路由与契约

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/fig4` | 图4 **整页**（`fig4.html`，**不进** `WEB_STATIC_ASSETS`；`?tag=` / `?job=` / `?bg=transparent` / `?missile=`） |
| GET | `/api/fig4/<tag_or_job_id>` | 前端 JSON。`<id>` 先当**任务 id**（`state.jobs` 里有 ⇒ 未跑完 409、那一单没有图4 产物 404），否则当**产物 tag**（非法字符 400、产物不在盘上 404 并附重出命令） |
| GET | `/static/fig4.css` `/static/fig4.js` | 白名单内的纯资源（`fig4.html` 仍 fail-closed：404） |
| POST | `/api/submit` `figure=fig4` | 后台任务：`run_fig4()`（重出产物；页面随后用同一条 `/api/fig4/<job_id>` 看） |

数据层是 `fig4.py`，**只读产物、不 import 求解器/workflow**（源码判据
`test_fig4_data_layer_imports_no_solver_and_no_workflow` + 打桩判据
`test_fig4_solver_run_is_never_called`）。响应里几个**必须**知道的键：
| 键 | 含义 |
| --- | --- |
| `grid` | 三根轴的点 + `shape`/`n_cases`/`flat_order`；**只有一份**（11 枚弹共享） |
| `clouds[key]` | 点云：`t`/`resid`/`curv`（**展平顺序 ΔV 外层 → γ → β**）、`miss_idx`、逐列 `slope/intercept/quad/rms_*/curv_*/R_ref/n_star_g` |
| `shared.ranges` | **共享色标范围**（按全部弹的点云算）：`t_hit` / `resid`（对称）/ `curv`；`per_missile_t_range` 供"这不是按选中弹算"的判据 |
| `axes` / `modes` / `legend` / `footnotes` / `colors` | 全部来自 `figures.FIG4_*`（前端**零颜色字面量**） |
| `markers` | `{hit: "dot", miss: "hollow"}` —— 命中/脱靶**换形状** |
| `markers`/`heatmap`/`induced` | 小面板热度口径、热点格、诱导阻力主导的列数与规则 |

**前端契约名**（`tests/test_fig4.py` 逐条钉住）：`window.FIG4`、`localStorage` 键
**`missile-sim.fig4`**（与查看器的键分开）、`boot()` / `viewer()` / `cloudColors()` /
`colorDomain()` / `fitCurves()` / `planeQuads()` / `buildBox()` / `drawColorbar()` /
`drawHeatmap()` / `placeTicks()` / `applyDrag()` / `projectToScreen()` / `loadState()` /
`saveState()` / `rampColor()` / `needColor()` / `needRamp()`，以及页面元素
`cv/labels/hud/bar/missile/mode/heatmode/fitplane/fitcols/induced/btnReset/btnSpin/btnOpen/cbar/hm/legend/err`。

## 5. 复现与自检

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python -m missile_sim --figure fig4 --tag default     # 产物（≈78 s）
python tests\run_tests.py -k fig4                     # 34 项判据（≈6 s；两个测试文件一起）
python -m missile_sim.webui --port 8791               # 看图：http://127.0.0.1:8791/fig4
```

浏览器侧实测（2026-10-02，本机 Edge / `browser-skill`，1280×820）：

| 项 | 实测 |
| --- | --- |
| `/fig4?tag=default` | 点 245 · 线 578（盒/刻度 + 49 条二次曲线）· 三角形 444（3 张平面等值面）；色标 34.7~68.6 s；β–γ 小面板 + 热点框；无 JS 报错 |
| 切弹种 | `240A → R-77-1`：点云与统计换、**色标范围不动**（共享 `-3.86~3.86`），与"横向可比"一致 |
| 切颜色模式 | `t_hit → 线性拟合残差`：色标换成发散刻度、0 在浅色中点；小面板切到残差 RMS |
| 两个图层开关 | 关"拟合平面" ⇒ 三角形 0、图例条目同步消失；开"只看诱导阻力主导" ⇒ 点 245→225、曲线同步过滤 |
| 刷新 | 选择被 `localStorage`（`missile-sim.fig4`）记住并恢复 |
| 全脱靶档 `/fig4?tag=miss` | 8 个**空心**标记；色标处写"这一档没有可着色的命中点"、小面板写"全部脱靶，拟合无意义"（不留 `Infinity` 那种假刻度） |
| 抓到并修掉的真 bug | ① `fig4.js` 里一处 `'…background:' + C.plane + ";opacity:.35\"></i>'"` 混用引号 ⇒ **SyntaxError 整页白屏**（`node --check` 现在把它挡在提交前）；② `STORE_KEY` 只用未声明 ⇒ `ReferenceError`；③ 全脱靶档的 `NaN`/`Infinity` 会写进 JSON 与画布（`allow_nan=False` 判据 + 面板显式拦） |

## 6. 已知缺口 / 待回灌

1. ⚠ **`EVIDENCE.md` 未回灌**：动手扫产物时 `E:\导弹包线图-fig4\.tmp_test\fig4\EVIDENCE.md`
   （并行子代理在写"ΔV 该扫多宽"）**还不存在**，所以按用户给的口径做了默认值
   （0.6~1.4× 钉值、5 点）。若那份实测给出别的范围/密度，重出即可（改 `--fig4-dv-factors`
   **不需要动一行代码**）；**本文 §3.1 的残差/曲率数字会跟着变**（残差随 ΔV 跨度平方走，见 §3.1 末）。
2. **默认网格 100% 命中** ⇒ 空心标记只能在 §3.3 那份 `tag=miss` 小档上看到。
   若想让默认档也出现脱靶，得把 ΔV 下界或距离推到求解器边界（那是**另一套想定**，会改变整张图的语义）。
3. **判别量在默认参考工况下几乎全选中**（45/49 列 `R ≥ 1`），"只看诱导阻力主导"的筛选作用有限；
   分界线依赖 `n_ref = 20G` 与 10 km / 800 m/s 这两个口径（都可改，但不能默认乱改）。
4. **三根轴各自归一化到等长**（视觉约定，`docs/FIG-BG3D-FEASIBILITY.md` §7.6）：轴向不做角度测量；
   刻度与标签是真值。
5. **没有做**：截面/剖切面、按 ΔV 分层隐藏、等值面（上一轮 spike 的 marching tetrahedra 没有接进来
   —— 本轮的点云 + 拟合曲线 + 平面等值面已经能说清"哪片区域失效"）；`standard` 档能跑但极慢。
6. **前端行为判据只到"node 能算的"这一层**：跟手方向、共享色标、脱靶空心色、二次曲线逐值一致
   都有 node 自检（无 node 会跳过并打印一行说明）；**真指针事件**（`PointerEvent` → `cam.az` 变化）
   只在浏览器里手验过（见 §5），没有做成自动化判据。

## 7. ⚠ 与 `NOTES.md` §32（Lead 2026-10-02，本图交付**之后**的口径）的差异

Lead 在 `NOTES.md` §32 里把图4 的任务改成了 **v4 规格**（`task-18`）：散点 + **单层等时面 + 13 档层滑块**
+ 用户自定义工况，并点名要求**删掉**：全局最小二乘拟合平面（`plane`）、逐 (β,γ) 列二次拟合曲线（`fit`）、
β–γ 曲率小面板与"只看诱导阻力主导"筛选（`heatmap`/`curv`），**加**等时面（`bg3d.marching_tetrahedra`）。

**本轮交付（按我收到的任务书）没有做 v4 的这些增删**，原因是任务书原文把证据层定成
"**主角之一**"并逐条要求："拟合平面/曲面（可开关）"、"残差 / 曲率着色（可开关）"、
"β–γ 平面上的曲率或残差热力图（2D 小面板）"。两者**不冲突的部分**已经按 Lead 口径落地：

* 轴标签改成 `β（≡ BC）` + 一条脚注说明"β ≡ BC，故 (ΔV, BC, γ) 与 (ΔV, β, γ) 同空间"（§1）；
* 其余（删三样、加等时面/滑块/工况表单）**留给下一位写者**（Lead 已排给 `fig3d-scout`）。
  删那些东西**只动 `fig4.js` + `fig4.py` 的响应字段**，数据层与产物不用重算
  （`plane`/`fit`/`heatmap` 都是从同一份立方体算出来的派生量）。

⇒ **下一位写者/Lead 请在此处对齐**：本文件 §3 承认的"证据层"是本轮任务书的产物，
与 §32.4 的"要删"是**两套口径**；删之前请确认用户那边到底要哪一套（本仓库刚在合并时栽过
"两边静默不一致"，这次不要再默默二选一）。


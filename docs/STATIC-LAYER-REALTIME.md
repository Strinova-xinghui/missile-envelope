# 全弹池 + 客户端实时出图（静态层自渲染）—— 计划与静态可行性判定

> 用户口径（2026-10-04）：**默认 11 弹之外，让用户像 StatShark 那样自己组对比弹池，三张图的轴与点
> 同步自适应，并且是实时的**；为此**发布时就把全弹坐标打包好**（而不是让页面回服务器跑脚本出图），
> 让"WebUI 壳下的静态层自己出图"；**原有的图脚本只负责叠加等时线/面**，这样改注释、换版本数值
> 都不必再动脚本 + 重验。**先静态版（阶段 A 已落地），再实时显示（阶段 B），最后在发布版基础上重构动态（阶段 C）。**

## 0. 依据事实（2026-10-04 实测，计划建在这些数上）

| 事实 | 值 / 出处 |
| --- | --- |
| 弹的**全集** | `vendor/wt-missile/inputs/resources/2.59.0.28/presets.json` 的 `presets` 子键 = **168 条**（`solver.preset_names()`） |
| 全是**对空弹** | seeker 分类 **IR 119 / ARH 49** —— 表里没有非对空武器 |
| 不可算的 **9 条 = 5 个型号** | `cn_pl15`(+`_default`)、`us_aim_54a`(+`_default`)、`us_aim_54b`、`us_aim_54c`(+`_default`)、`us_aim_54c_plus`(+`_default`)：**PL-15 与 AIM-54A/B/C/C+**（都是 ARH 对空弹）。原因 = **`propulsion*` 多发动机族**，权威两级公式不覆盖，`mapping.blk_metrics()` **明确报错**（不是静默算错） |
| 全表可算性 / 成本 | **159/168 可算**，全表 **2.0~4.1 s**（≈24 ms/个） |
| 全表量程 | ΔV **399.7~1432.5**、BC **708.6~3683.9**（11 弹池只有 820.5~1099.5 / 2567.0~3683.9）⇒ 轴自适应是硬需求 |
| 轴口径的现成实现 | `figures.adaptive_axis()`（图1）、`figures.bg_axis()`（图2）、`figures.fig3_axes()`（图3，前端**已经**在消费它的域） |
| 客户端渲染先例 | `webui_static/fig3.js`：手写 WebGL、零第三方、轴域/标签/光晕全从响应来 |

⚠ **更正一条口述**：那 9 个**不是 KH-31 系列** —— `KH-31` 在预设表里**一条都没有**（0 命中）。

## 1. 静态可行性判定（用户直接问的两件事）

| 能力 | 纯静态站（无后端） | 依据 / 前提 |
| --- | --- | --- |
| **弹池选择 + 三图轴/点自适应** | ✅ **可行** | 纯几何（选中集合 min/max + 现有 pad/round 口径），零网络往返。前提 = 弹的坐标在客户端 ⇒ 随站发布**派生目录**（§2）。判据钉 JS 与 `figures.adaptive_axis`/`bg_axis`/`fig3_axes` **逐值一致** |
| 图2 的等 `n*` 线随轴重画 | ✅ 可行 | 解析式（`bg.nstar_curve` / `bg.nstar_slope` 口径），不依赖求解器 |
| **现场拉 Datamine 算** | ❌ **不可行**（两条独立阻塞） | ① **浏览器读不到本地 Datamine 目录**：纯静态站没有后端代劳；把数据放进站点 = 分发 Gaijin 的 blk；从第三方站拉 = 运行时依赖 + CORS + 对方挂掉就废，且违背"不依赖别人的 CDN"纪律。② **权利口径**：本项目明确**不分发游戏数据**（`vendor/README.md`、`docs/OPENSOURCE-READINESS.md` §0） |
| ↳ 替代（= 用户提的第一条路线） | ✅ **就是这个** | 构建期算好**派生数值**（ΔV/BC/γ/ginv，**不含 blk**）随站发布。⚠ 与今天图上已公开的 11 弹数值同类，但规模 11 → 159 ⇒ **"只发派生数值、不发 blk"是发布口径** |
| ↳ **本地免安装包**里现场算 | ✅ 可行 | 包内有 vendor blk + Python ⇒ 缺目录时可现场重算（2~4 s，`--catalog`）。**静态站与本地包答案不同**，别混 |
| 等时线/等时面**按需叠加** | ⚠️ 静态站只能"预计算后随站发" | 组合是 弹×工况，静态站无法穷举；按需算 ⇒ **必须有后端**（阶段 C，即 `docs/HOSTING.md` 的架构 B/C） |

一句话：**"按弹池自适应缩放"纯静态完全可行；"现场拉 Datamine 算"不行**（技术 + 权利两条）；
静态站的正解是**构建期算好、随站发布派生目录**；**等时线/面**要按需叠加就绕不开后端。

## 2. 数据契约：`results/missile_catalog.json`（`schema=1`）

```
{ schema, generated_utc, solver:{solver,model,version,sha256,archive_sha256,n_profiles},
  archive_sha256,
  reference:{alt_m,speed_ms,mach,q_pa,f_mach,cap_f},          # 图2 的 n* / R 需要
  count:168, computable:159,
  unsupported:[{native,key,label,full_name,seeker,resource,resource_sha256,
                in_pool11,duplicate_of,default_hidden, reason}],   # 9 条，reason = 内核原话
  missiles:[{native,key,label,full_name,seeker,resource,resource_sha256,
             in_pool11,duplicate_of,default_hidden, dv,bc,gamma,ginv}] }
```

* **生成**：`python -m missile_sim --catalog`（也可由 `scripts/refresh_products.py` 的 `catalog` 步一起刷）。
* **命名/折叠规则**（写死，避免 UI 抖动）：11 弹沿用 `pool.POOL` 短名/全名；其余 `key = native`；
  `*_default` 是孪生 ⇒ 标 `duplicate_of` + `default_hidden`（**保留在表里**，删了总数就对不上内核表）；
  β ≡ BC（同一公式）⇒ 只存 `bc`。
* **自校验**：`catalog.verify(rec, full=…)` 逐值重算（改任何一个坐标值都会炸）——判据与反证在 `tests/test_catalog.py`。

## 3. 阶段划分与勾选

### 阶段 0：收尾在途（✅ 2026-10-04）
首页图注接回 + 「只出图不扫描却写已跑仿真层」缺陷修复（定因在前端 `showResult()` 里 `applyResultNotes()`
跑在 `showFigures()` 前，文本写进了即将隐藏的那条 `ul`；改成按**这一跑的 `with_iso`** 决定显示哪一份）。

### 阶段 A：全弹池目录（✅ 2026-10-04）
- [x] `src/missile_sim/catalog.py`（**不写物理公式**：复用 `mapping.blk_metrics` / `bg.point_of` / `bg.reference`）
- [x] `solver.preset_names()` / `solver.preset_info()`（唯一 vendor 接触面上的两个薄入口）
- [x] `results/missile_catalog.json`（159/168；9 条带内核原话原因）
- [x] `python -m missile_sim --catalog`、`scripts/refresh_products.py` 的 `catalog` 步（`--check` 连 `-k catalog` 一起跑）
- [x] `tests/test_catalog.py`（6 项：覆盖全表 / 逐值一致 / 不可算带原因 / `_default` 折叠 / **四条反证** / JSON 往返）
- [x] 随包：`make_dist.py` 的 `RESULTS_KEEP` + `REQUIRED_IN_BUNDLE` 各加一条

### 阶段 B：实时静态层（未做）
- [ ] `webui_static/figs2d.js` + `figs2d.css`（**SVG**、零第三方）：图1/图2 渲染器（轴自适应、点、**标签算法避让**、图2 等 `n*` 线、注释区块）
- [ ] 选择 UI：初始勾选 **11 弹** + 「清空/全选/仅 11 弹」；`localStorage` 记选择
- [ ] 图册 `sitebuild.py` 接同一层（图册升级为"零第三方 + 自渲染"），无 JS 回落 `_static` PNG
- [ ] 图3：点集来源从 `fig3_default.json` 的 11 点改为**目录 + 选中集合**（轴域照 `figures.fig3_axes` 口径客户端重算）
- [ ] 判据：`-k figs2d`（node 探针，JS 轴域与 Python **逐值一致**、标签两两不重叠、等 `n*` 斜率一致）；"切换子集不产生任何 `/api/*` 出图请求"

### 阶段 C：在发布版基础上重构动态（未做，**需要后端**）
- [ ] `workflow.overlay_plane/overlay_bg`：只产出**等时线折线 + 轴域 + 口径文本 + 身份戳**的 JSON（交互路径不再走 matplotlib）
- [ ] `GET /api/catalog`、`POST /api/overlay`（走现有后台任务 + `/progress`）
- [ ] matplotlib 路径与 12 件成品**保留**（发布/下载/投稿），只把**交互视图**切到客户端渲染

## 4. 边界与默认取值

| 项 | 取值 |
| --- | --- |
| 那 9 条不可算的 | **列出但置灰**（按用户口径），悬停给**真实原因**（`propulsion*` 多发动机族）；`_default` 孪生折叠成 5 个型号 |
| 子集只选 1 枚 / 全选 159 枚 | 沿用 Python 侧现成的最小跨度与 pad/round 口径（同一批判据）；全选时的拥挤由 SVG 内缩放/平移解决，**不做对数轴**（会改口径） |
| 目录缺件 | 页面回落静态 PNG + 一行提示；**本地包**可现场重算，静态站只能重新发布 |
| JS 里出现第二份物理公式 | 判据封（源码扫描 + 载荷身份戳） |
| 第三方库 | **一个都不引**（Chart.js/Plotly/D3/ECharts 全封） |

## 5. 相关文件

`src/missile_sim/catalog.py`、`solver.py`（预设名单入口）、`cli.py`（`--catalog`）、
`scripts/refresh_products.py`、`tests/test_catalog.py`、`make_dist.py`（随包清单）、
`webui_static/fig3.js`（客户端渲染先例）、`docs/WEBUI.md` §12（首页图注与真浏览器验收步骤）。

# 阶段 C：在现有静态页面上接后端（等时线 / 等时面 + 时间滑块）

> 用户指令（2026-10-05）：**开启阶段 C —— 在现有静态页面上构建后端，使等时线能计算并叠加到图上；等时面及相关时间滑块同理；沙盒（图4）暂缓。**

## 1. 分工（三路并行，文件不重叠）

| 路 | 负责 | 范围 | 状态 |
| --- | --- | --- | --- |
| W1 后端服务 | `webui-fig3` | 新仓 `https://github.com/Strinova-xinghui/missile-backend`（public，已建）；依赖 `missile-solver` 包；数据运行时挂载（`DATA_DIR` + `verify_data()`，不过就拒绝启动）；`LICENSE` = AGPL-3.0-only | 进行中 |
| W2 叠加数据产出 | `figures-fig3` | 主仓 `workflow.overlay_plane/overlay_bg` 只产 JSON；`python -m missile_sim --overlay plane\|bg --axes "…" [--json]`；`--axes` 老路径逐字节未变；matplotlib 与 12 件成品原样保留 | 已完成（未提交） |
| W3 前端接线 | `webui-author` | W3a 已完成（骨架 + 闸门放宽 + 运行时验收）；W3b 待排期 | W3a 完成 |

## 2. 两条冻结决定

1. **后端配置 = 构建期注入**（不是运行时探测）：`sitebuild.build_static_app()` 在**配置了后端时**生成并内联 `backend.js`（`window.__BACKEND__ = {api_base, enabled}`）；**没配置就完全不引用** ⇒ 页面与今天**逐字节等价、零网络请求**。
   - 运行时探测做不到：浏览器要「知道文件在不在」必然发一次请求（`fetch('./backend.json')` 缺文件就是一次 404）。
   - `backend.js` 是生成文件、不进 `APP_ASSETS`（闸门不扫它 ⇒ URL 字面量不落在被扫资产里）；`app.js`/`figs2d.js`/`fig3.js` 只许引用 `window.__BACKEND__`。
2. **闸门精确放宽一条**：允许 `./backend.js` 与 `window.__BACKEND__.api_base`；`/api/`、**`/static/`（静态站没有这条路由 ⇒ 出现即死链）**、硬编码第三方域名**继续禁**；占位符闸门（`__[A-Z][A-Z_]*__`）**只豁免 `__BACKEND__`**。
   - `index.html` **保持一字不动**（后端条由 `app.js` 运行时创建）⇒ 保住「无配置时 HTML 逐字节等价」。

## 3. 接口 v1（冻结，三路对齐）

```
GET  /v1/health      → {ok, version, solver:{model,version,sha256}, data:{dir_ok,identity}, tier_default}
GET  /v1/catalog     → 与站点 catalog.json 同 schema（复用求解器包单一出处）
POST /v1/overlay     → req {kind:"plane"|"bg", keys:[…], tier, dv_pin?, iso_step?}
                       res {kind, keys, axis:{xlim,ylim}, iso_lines:[{level, points:[[x,y],…]}], notes:[…],
                            identity:{solver_sha256,resource_sha256,tier,backend,cached,elapsed_ms}}
POST /v1/isosurface  → req {keys:[k], tier, level_s, grid?}
                       res {kind:"fig3", level_s, mesh:{vertices,indices}, axis, notes, identity}
POST /v1/jobs        → {job_id}；GET /v1/jobs/{id} → {state, progress, result?}
```
- CORS 白名单 = `https://strinova-xinghui.github.io` + `http://127.0.0.1:*`（**不用 `*`**）。
- `identity.cached` = 本次至少一条命中缓存；`identity.resource_sha256` = **基准弹 blk** 的 sha256（只锁定扫描物理，弹池内其它弹的参数不影响它）。

## 4. W2 的关键裁决：等时线几何允许依赖 matplotlib

- 事实：`grid.py:16-19` 与 `figures.py:23-29` 顶层硬 `import matplotlib`（`use("Agg")`）；等时线本体就是 `grid._contour_segments()` 的 Agg contour，`bg3d.py:717-720` 记着**全仓只有这一条算路**。
- **裁决 A（已定）**：复用这条唯一算路，**后端进程允许依赖 matplotlib**；判据③写成「**不落图 / 不留 figure / 不写文件 + `figures/`、`results/` 的 size+mtime 不变**」。
- 否决 B（纯 marching squares 第二实现）：会引入**第二份几何**、与成品只能按容差比、永久维护一致性 —— 与本周「消灭第二份实现」的纪律冲突。
- W2 判据 `tests/test_overlay.py`：形状（六键 `kind/keys/axis/iso_lines/notes/identity`）+ **与产物路径 `run_plane()` 的 isolines 逐点相等**（同源）+ `axis == catalog.axis_payload()`（oracle）+ 只产数据 + 反证（把 `adaptive_axis` 换硬编码必须红）。

## 5. 一个环境类坑（已定位，修复已派）

本机 `%APPDATA%\Python\Python314\site-packages` 里出现 **pytest 9.1.1** ⇒ `tests/conftest.py` 的 `try: import pytest` 走**真 pytest** 注册 fixture，而 `tests/run_tests.py` 用 `tests/_pytest_shim.py` 驱动 ⇒ 两套注册表对不上，`-k grid_axis` / `-k catalog` 等**成片假失败**（`未定义的 fixture: pool_points/rec/tmp_path`）。

**纪律**：环境里多装一个包**不该**改变自检结果 ⇒ 修法是让 runner 与 conftest 显式使用同一套注册表（不跟环境走），并配反证。

## 6. W3b 待做 + 可直接复用的定位

- **等时线叠加（图1/图2）**：开关 + 间隔输入 + 虚线族（颜色/线型取自 `style`/CSS 变量）+ 图例带 `identity` + 切池重算。
- **图3 等时面 + 时间滑块**：从历史**逐字取回**（`git show 886eccf:src/missile_sim/webui_static/fig3.js`）：
  - `surfaceBuffers` @239、`applyDrag` @393（现文件已有保留版）、`B_LAYER` 缓冲 @559、参与 blend 的列表 @639、绘制段 @661-674（含 `B_HIT.alpha = B_LAYER.count ? 0.35 : 1.0` 这条「有点时点变淡」的口径）、上传 @715-716、`layerInfo()` @718、`drawColorbar` @736；
  - 响应驱动部分 @815（原 `/api/fig3/…`）、@937（layers URL）、@837/@1016（`?iso=1` 自动拉面）**换成 `/v1/isosurface`**；
  - 要求：防抖 + **旧响应作废**（后到的响应不能覆盖新选择）。
- **判据**：① 无 `backend.js` ⇒ 逐字节等价 + 零请求（W3a 已覆盖 ✓）；② node 桩后端 ⇒ 等时线/等时面按预期绘制、滑块改 `level_s` 会发新请求、旧响应不覆盖新选择；③ 后端 500/超时 ⇒ 一行可读错误 + 静态功能仍在；④ 反证：把响应乱序必须被抓；⑤ 仍零物理公式、零第三方库、零色值字面量。
- **可复用件（勿重造）**：`F.ticks()`、`F.visibleSeg()`、`F.nstarLabelLayout()`、`FIG3STATIC.mount()` 门面、node 桩骨架、CDP + SwiftShader 驱动模板。
- **W3a 的运行时证据**（可复跑 `%TEMP%\dsh-w3a\verify.js`）：`file://` 请求 **0** 条、上层目录 http 12 条（全是自身资产）、**后端相关请求 0**、`.card` 3 张照常、控制台 0 错。

## 7. 待决定 / 暂缓

- **后端部署到哪**（Fly.io / Railway / VPS）⇒ 决定静态站 `backend.js` 的 `api_base`。
  ⚠ 「Pages 的 HTTPS 页面直连本机 http 后端」会被浏览器**私有网络策略**挡 ⇒ 只适合临时试；**正式形态必须是托管 HTTPS 后端**。
- **沙盒（图4）按用户口径暂缓** ⊘。
- 三个仓现状：`missile-envelope`（静态站，`gh-pages` 线上）、`missile-solver`（求解器包，`main` = `c55b346`）、`missile-backend`（新，空仓）。

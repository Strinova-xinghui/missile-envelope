# GitHub Pages 站点接入「发射参数」：方案（2026-10-23）

用户口径：**近乎完美复刻 StatShark，同时保留我们的三种图 + 等时线**。
线上现状：Pages 站点只有弹池选择，**没有发射参数输入**；发射参数硬编码在
`missile-backend` 的 `pkg.Scene()`（默认 50 km / 10 km / 300 m/s 迎头）。

## 1. 两侧要改什么

### 后端（missile-backend 仓）

| 文件 | 改动 |
| --- | --- |
| `app/main.py` | `OverlayReq` / `IsoReq` / `JobReq` 增加 `scene: dict \| None` |
| `app/overlay.py` | `overlay()` / `isosurface()` 收 `scene`，转成 `pkg.Scene` 后传给 `physics.run_case*` |
| `app/physics.py` | `run_case` / `run_case_bg` 已有 `scene=` 形参，**只需有人传进去**；`cache_key` 要含 scene |
| `app/config.py` | 无（除非新增字段校验常量） |

关键点：

1. **`cache_key` 必须含 scene** —— 否则改了发射参数仍命中旧缓存，而且看起来完全正常
   （与主仓 `CACHE_SCHEMA` 那条坑同族）。建议 `physics.cache_key` 里加
   `"scene": {k: v for k, v in sorted(scene.items())}`，并把 `CACHE_SCHEMA` 思路对齐主仓。
2. **`pkg.Scene` 的字段名要以 missile-solver 包为准**，不是主仓的 `Scene`。
   先 `inspect.signature(pkg.Scene)` 确认，别凭记忆写。
3. `sync_max_nodes` 不变：换发射参数不改变网格规模，只是每个格点的 `t_hit` 变。

### 前端（Static 分支 webui_static/）

| 文件 | 改动 |
| --- | --- |
| `index.html` | 左栏加「发射参数」区块（11 个 `field-row`，与 localhost 版同一套标签） |
| `app.js` | 读取 / 收集这组输入；km/h ↔ m/s 换算（`KMH_FIELDS`）；随 `/v1/overlay` 一起 POST |
| `app.css` | 复用已移植的 Material filled 样式（`field-row`） |

**不能照搬 localhost 版**：它是 `webui.py` 服务端渲染 + `data-field` 约定；
静态站要自己写这段 HTML，且**不许出现 `/api/` 或服务端占位符**（`check_app_asset` 闸门）。

## 2. 闸门与判据

- `sitebuild.check_app_asset()`：相对路径 + 禁 `/api/` `/static/` `__X__` 占位符
- `tests/test_static_pool_page.py::test_no_backend_and_no_root_absolute_paths`
- `RAIL_BANNED`：左栏禁用词表 —— **新增发射参数框会撞「进度」「后台」等词吗？要逐条核**
- `tests/test_static_pool_page.py::test_rail_只有弹池` —— 这条会**直接红**：
  它断言左栏只许有弹池。要么改判据（左栏现在多了发射参数），要么把发射参数放到别处。
- 页面体积：无 24000 上限（那是 localhost 首页的），但保持克制

## 3. 分期

| 期 | 内容 | 判据 |
| --- | --- | --- |
| **S1** | 后端收 `scene` + cache_key 含 scene | 同一 keys、不同 scene ⇒ t_hit 不同；同 scene 两次 ⇒ 命中缓存 |
| **S2** | 前端加发射参数区块 + 换算 + POST | 改速度点计算 ⇒ 曲线/等时线随之变 |
| **S3** | 判据与文档同步 | `-k static_pool_page` / `-k static_site` 全绿 + 真浏览器截图 |

## 4. 风险

- **`test_rail_只有弹池` 必然要改**：它是"左栏只放弹池"的旧口径，现在要放发射参数。
  改判据要同时更新它的 docstring，说明为什么。
- **CORS / 限流**：多一轮请求不变（仍是一次 `/v1/overlay`），但 scene 变大，注意
  `max_keys` 与请求体体积。
- **后端未知**：`pkg.Scene` 字段名、`solver.run` 是否吃 `turn_rate_rad_s` 都要实测确认。
---

## 4. 落地结果（2026-10-24）

**状态：S1–S3 全部完成并已上线。**

| 件 | 提交 | 说明 |
| --- | --- | --- |
| 后端 | `missile-backend e2722ab` | `scene` 进三个请求模型 + 两条物理分支 + 立方体键 |
| 本站点 | `Static 734e21c` | 左栏 `#sec-launch` 十项 + `sceneOf()` + Material filled |
| gh-pages | `a13689b` | 已经 GitHub API 推上去（见下「网络坑」） |

真机实测（Pages + `strinova.me/missile`）：50 km ⇒ 等时线 **47–59 s**（570 段）；
60 km ⇒ **53–64 s**（734 段）。同一份弹池、同一档位，只有 `range_m` 不同。

### 4.1 实际踩到的两个坑（都不是"写错代码"，是"看起来正常"）

1. **bg 分支没吃 scene**。`overlay()` 里 `kind="bg"` 走的是 `physics.run_case_bg(...)`，
   与 plane 的 `run_case(...)` 是**两条不同的调用**。第一版只给 plane 传了 scene，
   而缓存键已经含 scene ⇒ 改发射参数后图2 纹丝不动、缓存还乖乖换了新键。
   判据 `test_overlay_bg_scene_really_changes_physics` 专门守它（反证实测会红）。

2. **`/v1/jobs` 那条路把 scene 丢了**。默认 11 弹的网格超过同步上限，
   「开始计算」走的是**任务队列**而不是同步 `/v1/overlay`；那条 body 只有
   `op/kind/keys/tier/iso_step`。后果同样是"图不动且不报错"。
   判据 `test_scene_is_sent_on_every_request_path` 逐条数
   `scene: sceneOf()` 必须 **3** 处。

> 教训：这类"静默降级"用「页面里有 `sceneOf`」是抓不到的，
> 必须**逐条数调用点** + **反证**（把那处删掉看判据是否红）。

### 4.2 网络坑（本机 `github.com:443` 不通，但 `api.github.com` 通）

`git push` 走不了，改用 **GitHub Git Data API**（`gh auth token` + REST）：
先 `POST /git/blobs`，再 `POST /git/trees`（**base_tree 必须取远程 ref 的 commit**，
拿本地未推送提交的 tree 会被 422 拒），再 `POST /git/commits`，最后
`PATCH /git/refs/heads/gh-pages`。后端仓同理：本机打包 `git bundle` → scp 到 VM →
VM 上 `git merge --ff-only` + `systemctl restart missile-backend`。

### 4.3 仍未做

- `Static` 与 `missile-backend` 的提交**没有推到 GitHub**（本机到 github.com 不通），
  线上 gh-pages 已是新内容、VM 已是新代码，但仓库历史里还缺这两个提交。
  恢复网络后补一次 `git push origin Static` 与 `git push origin main` 即可。
- `turn_rate_rad_s`、版本下拉、图表设置（过滤 Y 轴元素 / 动画速度 / 显示飞行标签）
  仍是"近乎完美复刻"缺口清单里未做项。
---

## 5. 「弹道」模式（2026-10-24）

用户口径：「默认开始计算是只计算列表中的弹道，像 statshark 一样降低学习成本；
另有扫描出图来承接现有功能」，随后修正为「出的图应该是一个 3D 视角下的列表中导弹飞行轨迹集合，
而不是简单的距离时间图」。

### 5.1 两侧改动

| 侧 | 提交 | 内容 |
| --- | --- | --- |
| 后端 | `362380e`（本地 `036e875`） | `POST /v1/trajectory` |
| 站点 | `8e2559f` | `traj3d.js`（468 行手写 WebGL2）+ 模式切换 |
| gh-pages | `ca41b51` | 已上线 |

后端关键点：
- `physics.run_trajectory()` → `solver.run(want_rows=True)` → `thin_points()` 抽稀到 ≤300 点。
  ⚠ `want_rows=False`（默认）时 `Shot.rows` **是空的** —— 这是最容易踩的一步。
- 点列 5 列 `[t, x, y, z, v]`，x/y/z 直接取 `Shot.rows` 原列，零换算。
  ⚠ **`z` 在默认迎头场景恒为 0**，高度在 `y`（不是 z）。带 `target_bearing_deg=45` 时 z 到 35345。
- `physics.resolve_any()`：目录里**全部可算条目**都能算（原来只认 11 枚池，
  用户点第 12 枚直接 400）。
- 同步返回（11 枚约 2.6 s / 124 KB），**不走 /v1/jobs**；刻意不用线程池
  （求解器靠 monkeypatch 模块级 `wt.load_profile` 施加乘数，并发会串味）。

### 5.2 前端

- 新增 `traj3d.js`：自适应包围盒相机、拖动旋转、滚轮缩放、右键/Shift 平移、双击复位、地面网格。
  相机与拖拽移植自 `viewer3d.js`，嵌卡片里的尺寸/DPR 处理照 `fig3.js`。
- 后端条改成两个单选模式，**默认「弹道」**；扫描把 `#backend-iso` / `#backend-surface` /
  `#backend-level` 整组收起来（id 与语义不变）。
- ⚠ **新资产必须登记 `sitebuild.APP_ASSETS`** —— 漏了 = 本地测试全绿、构建报成功、线上 404。

### 5.3 判据

- `-k static_pool_page/static_site/fig3_static/traj3d_static` **94 项全绿**。
- 后端 `tests/test_trajectory.py` 10 条 + 全量 **33 passed / 1 skipped**。
- 两条反证（都是"看起来正常"的失败）：
  - `range_m` 50k vs 60k ⇒ `t_hit` 45.186 vs 55.748（证明 scene 真进物理，不是只进缓存键）。
  - `target_bearing_deg=45` ⇒ z 到 35345.4、300 点里 296 点 `|z|>1`（证明真的三维）。
- `fetch(` 计数 7→8、`scene: sceneOf()` 3→4，都是**逐个数**，不是放开成任意多。

### 5.4 真机实测

- 本地站 + 本地后端：默认弹道模式出 3D 曲线，多枚各一条，可旋转缩放。
- 线上站 + 线上后端：11 枚 → **2052 ms**，图例 11 条，各弹独立配色。

### 5.5 踩到的坑

1. `.tmp_*.txt`（写提交信息的临时文件）被 `git add -A` 一起提交了 —— 两个仓库各中一次。
   已 `git rm --cached` 并 amend。**以后写提交信息别放仓库目录里。**
2. 本机 `github.com:443` 反复不通（代理时好时坏），但 `api.github.com` 一直通
   ⇒ 全部改用 Git Data API 逐 blob/tree/commit 上传。注意：
   - `base_tree` 必须取**远程** ref 对应提交的 tree（拿本地未推送提交的 tree 会 422）；
   - tree 里**只有删除项**时也会 422（"Invalid tree info"）⇒ 合并成一个提交上传。
3. 前端队友中途挂掉（无 closing message），但代码已落盘且测试全绿，由 Lead 验收后提交。

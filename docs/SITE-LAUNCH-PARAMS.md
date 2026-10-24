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

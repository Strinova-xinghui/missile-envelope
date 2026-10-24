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

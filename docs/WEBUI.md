# WebUI（本地网页外壳）

面向**改 WebUI 的人**：路由表、静态资源布局、渲染管线、后台任务与轮询、怎么加一个字段/资源/路由、
以及"哪些判据必须跟着改"。业务逻辑一律不在这里 —— 它在 `workflow.py` / `targets.py` / `engine.py`。

启动（只听本机）：

```powershell
python -m missile_sim.webui                     # http://127.0.0.1:8765/
python -m missile_sim.webui --port 0            # 端口交给系统分配（测试就这么干）
python -m missile_sim.webui --tier standard --jobs 4 --quiet --no-browser
```

`--host` **默认 `127.0.0.1`**，是"本机表单"不是服务器：没有鉴权、没有 HTTPS、没有并发保护，
**不要**绑到 `0.0.0.0` 或放到公网。免安装分发包里由 `run_ui.py` 起它（见 `docs/DISTRIBUTION.md`）。

## 1. 静态资源布局（2026-10-01 拆分）

首页原来是 `webui.py` 里一个 440 行的 `PAGE` raw string。现在拆成：

| 文件 | 角色 | 由谁渲染 |
| --- | --- | --- |
| `src/missile_sim/webui_static/index.html` | 页面骨架 + **服务端占位符**（`__SOLVER__` / `__FIELDROWS__` / `__TRAJROWS__` …）+ **内联 boot 数据**（`var DEFAULTS = …`） | `render_page()` 每次请求替换占位符 |
| `src/missile_sim/webui_static/app.css` | 全部样式 | **不渲染**，`GET /static/app.css` 直发字节 |
| `src/missile_sim/webui_static/app.js` | 全部前端逻辑（表单收集 / 轮询 / 结果渲染） | **不渲染**，`GET /static/app.js` 直发字节 |

设计口径：

* **boot 数据留在 HTML 里、内联**（`var DEFAULTS = …, PRESETS = …, META = …;`）：前端不用多打一次
  请求，且首屏就是完整的；`app.js` 因此**一个服务端占位符都没有**，可以放心加缓存头。
* **"读得到"与"发得出去"分开**：`read_page_file()` 只负责按名字读（basename 化挡穿越 + 只认
  `.html/.css/.js`），能不能对外发由 `WEB_STATIC_ASSETS` 白名单在**路由那一层**判。
  `index.html` **故意不在白名单里** —— 它带着没渲染的占位符，原样发出去会把 `__DEFAULTS__` 露给浏览器。
* `render_page()` 末尾用 `TOKEN_RE`（`__[A-Z][A-Z_]*__`）兜底：渲染完还剩占位符就**当场 500**，
  不允许页面静默残缺（这类失败以前只会表现为"某个下拉空的"）。

实测（2026-10-01，本机）：首页响应体 **36350 → 15507 字节**；`webui.py` **2203 → 1780 行**；
`app.css` 2626 B / `app.js` 15678 B。拆分**逐字节等价**：把拆前的 `render_page()` 产物、按两处替换
（`<style>…</style>` → `<link>`、`<script>` 主体 → boot 行 + `<script src>`)重建成"期望页面"，
与拆后的产物**完全相同**（唯一故意的内容改动是修掉页面里手写的 markdown 星号，见 §4）。

## 2. 路由表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` `/index.html` | 首页（`render_page()`） |
| GET | `/healthz` | 存活探针 + `targets` 是否可用 |
| GET | `/progress/<id>` | 任务快照（前端轮询它；`poll_ms` 来自配置，默认 500） |
| GET | `/static/<name>` | 首页自己的 CSS/JS，**白名单** `app.css` / `app.js` |
| GET | `/figures/<name>` `/results/<name>` | 产物图片 / CSV / JSON，只在 `static_roots()`（`figures/`、`results/` + 配置里的目录）里按 **basename** 找 |
| POST | `/api/single` | 单工况同步求解（表单 → `Scene` → `solver.run`），返回 JSON |
| POST | `/api/submit` | 提交后台任务：`kind=scan`（扫描）/ `kind=plot`（只出图），`figure=plane/bg/traj/both/all` |

静态路由一律"文件名 basename 化 + 必须落在允许目录内"（`_is_inside`），所以 `/figures/../../x`
在路由层就 404，不会走到文件系统。

## 3. 后台任务与轮询

`JobStore`（`jobs.submit(kind, work)`）在后台线程里跑 `workflow.run_*`，`Job.snapshot()` 给出
`state` / `percent` / `done` / `total` / `result` / `error`；前端 `startPoll(id, title)` 按 `META.poll_ms`
轮询 `/progress/<id>`，进度条与"第几个工况"都来自这里。任务失败时 `error` 会**回显到页面上**，不是静默。

⚠ 测试里 `cache: false` 是刻意的：缓存命中会让 `Engine.many` 一次进度回调都不发，进度永远停在 `0/0`，
看起来像"扫描坏了"（见 `tests/test_webui.py` 顶部注释与 `NOTES.md`）。

## 4. 改 WebUI 时的判据（别只改页面）

* **加/改一个表单字段**：改 `webui.py` 里的 `Field` 列表（`PRIMARY_FIELDS` / `ADV_FIELDS` /
  `BG_FIELDS` / `TRAJ_FIELDS`）就会被 `_field_html()` 渲染成一行，**不用动 HTML**。
  同时要过的判据：`-k printed_text`（`hint`/`label` 里不许有 markdown 星号）、
  `tests/test_webui_traj.py::test_page_exposes_the_trajectory_fields`（`data-field` 与标签真的在页面上）、
  `tests/test_form_dirty.py::test_dirty_covers_every_field_of_every_preset`（手改字段要能上报）。
* **加一个静态资源**：写进 `webui_static/`，把名字加进 `WEB_STATIC_ASSETS`（含 content-type）——
  不加就 404（fail-closed）。
* **文案不许带 markdown 星号**：`figures._plain()` 只兜"出图"那条路径。页面侧现在有
  `tests/test_webui.py::test_webui_page_shows_no_markdown_stars`：**渲染出来的 HTML 里 `**` 计数必须为 0**；
  `app.js` 里允许 `**` 存在于 `//` 注释中（不渲染给用户），其他位置一律判失败。
  这条判据是 2026-10-01 拆资源时补的 —— 当时在 `index.html` 里抓到一处手写的 `**不解算**`，
  浏览器上原样显示星号，而 `-k printed_text` 只看 Python 那侧的字符串，看不到页面里手写的提示。
* **改 JS 的位置要跟着改测试**：前端源码从 `webui.py` 搬到 `app.js` 后，
  `test_form_dirty.py::test_front_end_reports_dirty_fields` 与
  `test_webui_index_200` 里"前端轮询 `/progress/`"的断言改成扫**浏览器真正收到的那份 JS**（比扫源码更强）。

覆盖这一层的测试：`-k webui`（39 项，真起服务 + `http.client`，含图2/图3 端到端）、
`-k form_dirty`（12 项）、`-k printed_text`（1 项）。

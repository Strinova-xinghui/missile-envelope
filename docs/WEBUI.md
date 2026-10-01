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
`app.css` 2626 B / `app.js` 15678 B（**拆分当时**的字节数；§5/§6 之后又长了，最新看
`git log -1 --stat`）。拆分**逐字节等价**：把拆前的 `render_page()` 产物、按两处替换
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

覆盖这一层的测试：`-k webui`（42 项，真起服务 + `http.client`，含图2/图3 端到端与静态资源白名单）、
`-k form_dirty`（12 项）、`-k printed_text`（1 项）。

## 5. 输入体验（2026-10-01）：错误按字段归位 + 记住上次输入

### 5.1 `field_errors`：把"给人看的话"折成"给框用的键"

失败响应原本只有 `{"ok": false, "errors": ["…"]}` —— 纯字符串，前端只知道"有个错"，
不知道该给哪个框标红。现在**新增**一个键（`errors` 原样保留，向后兼容）：

```json
{"ok": false,
 "errors": ["想定解析失败：range_m 需要数字，收到 'abc'"],
 "field_errors": {"range_m": ["想定解析失败：range_m 需要数字，收到 'abc'"]}}
```

归位规则在 `webui.field_errors()`：**先认 label**（长 label 优先），认不出**再认字段名**且必须
**词边界**匹配。放在服务端而不是前端 —— 规则只该写一份，而且 Python 侧能测。

⚠ **两个坑（都踩过）**：

* **字段名可能在句子中间**：真消息是 `想定解析失败：range_m 需要数字，收到 'abc'`，而第一版规则
  只认"名字在开头"，于是"消息条有字、红框没有"。**别拿自己编的样例消息写规则** ——
  手编样例让 Python 测试全绿，真浏览器一跑就露馅（见 `NOTES.md` §25）。
* **字段名互为子串**：`alt_m` 是 `target_alt_m` 的后缀，直接 `name in text` 会把敌机高度的错算到
  载机高度头上 —— 归错比不归更糟（会让人去改一个没问题的框）。用
  `(?<![0-9A-Za-z_])name(?![0-9A-Za-z_])` 卡词边界。

前端只做三件事（`app.js`）：`showFailure()` 把 `errors` 打到消息条、把 `field_errors` 交给
`markFieldErrors()` 上色（红框 + 框下红字），并把**第一个**出错的框滚到眼前、`focus()` 进去；
用户一改动那个框就清掉它自己的红框与提示（别的框留到下次提交，免得别的错突然消失）。

### 5.2 记住上次手改的输入

`localStorage` 键 **`missile-sim:form`**，存 `collect()` 的整份表单（含 `_dirty` = 手改字段清单）。
加载时 `restoreLocal()` **只回填手改过的字段**，并照存下来的 `_dirty` 重新标成 dirty
（程序性赋值不算手改，所以必须补标）；全是默认值就**不打扰**，不弹"已恢复"。
按钮**「忘记上次输入」**（`#forget`）清掉这份记忆。语义与后端一致：手改 = 覆盖预置。

### 5.3 判据

* 归位规则：`test_webui_field_errors_only_claims_what_it_can_name`（含真消息 + 词边界）、
  `test_webui_400_maps_errors_to_the_field`（**非数字**与**越界**两条路的文案不一样，都要过）。
* 前端钩子：`test_webui_page_exposes_input_experience_hooks`（函数名 / 类名 / `localStorage` 键名）。
* ⚠ JS 行为在这套测试里**跑不起来**（无浏览器、无 node）：钩子只能钉住契约名，
  **真实行为必须靠浏览器实测**（做法与实测结论见 `NOTES.md` §25）。

## 6. 亮色主题（2026-10-01）

用户定：**背景改亮色**（参考白底工程工具风，如 `jari-aerospace.top`）。实现就是 `app.css` 顶部那组变量：

```css
--bg:#f5f6f8  --card:#ffffff  --field:#ffffff  --line:#d8dce1  --fg:#1f2933  --dim:#5b6672
--accent:#1f6feb  --warn:#9a6700  --err:#c9252d  --ok:#1a7f37    /* + color-scheme:light */
```

* ⚠ **`color-scheme:light` 不能漏**：它决定**表单控件与滚动条**的配色。只把背景刷白而漏掉它，
  `<select>` 下拉与滚动条还是深色（既难看又难查）。判据 `test_webui_theme_is_light` 钉着它。
* 想回深色就改这几个变量（旧值：`--bg:#0f1419` / `--card:#171d26` / `--line:#2a3441` /
  `--fg:#e6edf3` / `--accent:#3fb950`；输入框与 `pre` 另有几个硬编码的深色值，见那次提交的 diff）。
  但那条判据**明确写着"深色底不该还在"** —— 主题是产品决定，改它时要连判据一起改，不能被悄悄改回去。
* 出图产物本身是**白底**的，亮色页面与它们更合（深色页面上贴一张白底 PNG 很扎眼）。
* 3D 视图（图3 预览 / 将来的可交互 3D）**跟随亮色**：背景浅色或透明，轨迹沿用现有配色 ——
  这条已作为硬需求通知 3D 线（见 `docs/RESTART-PLAN.md` §13.3 与 `NOTES.md` §25）。

## 7. 参考站实测：StatShark（2026-10-01，用户推荐）

用户给的第二个参考站是 <https://statshark.net/>（做 War Thunder 数据统计的网站），
理由是"前端优良示范"。**它不是印象派参考，实测过**：抓了它的样式表与两个页面（证据见 §7.4）。
它的 **导弹计算器** 页和我们是**同一个领域**（左边填发射参数、右边出弹道曲线），
所以它的信息组织方式可以直接照抄。

### 7.1 它是什么做的（技术指纹）

| 维度 | 实测 | 对我们的意义 |
| --- | --- | --- |
| 框架 | **Angular Material**（CSS 里 `--mat-*` 变量 **2769** 条，Zen 于一个 `:root`） | 它是**重框架 + 重设计系统**路线；我们**不能**跟 |
| 样式体积 | 单个 `styles-2SGSLABJ.css` **213 KB** | 我们的 `app.css` 是 **~3 KB** —— 这是"免安装、离线、单文件"的优势，别丢 |
| 字体 | `Roboto` / `Material Icons` / `Font Awesome` / 自定义字体 | 要联网或带字体文件；我们用系统字体 + 少量内联 SVG |
| 图表 | **Plotly**（DOM 里有 `plotly-logomark` 链接） | 已被 3D 线否决（内联 JS 4.8 MB）；我们自己画 SVG/canvas |
| 主色 | `#3f51b5`（Material indigo）+ `#ff4081`（pink A200）= **Angular Material 默认主题**，没另起配色 | 参考站自己也**没有**做花哨配色：**克制**才是那个"优良示范" |
| 深/浅色 | `#fafafa`（亮面）与 `#303030`（暗面）两套 + 顶栏 `dark_mode` 切换 | 我们的亮色定案与它同类（浅灰底 + 白卡片），说明方向没错 |
| 圆角/阴影 | 圆角主要 **4~5 px**（不是大圆角）、阴影走 Material elevation | 我们现在的 6~8 px 圆角略"软"，要更像工程工具可收到 4~5 px |
| 其他 | Cloudflare（`cdn-cgi`）、Vite 风格 `chunk-*.js` 分包、自建 API（`/api/missiles/versions`） | 它也把数据层 API 化了 —— 和我们 `docs/SOLVER-API.md` 的思路一致 |

### 7.2 它的信息组织（这才是要抄的部分）

1. **两栏：左窄参数栏（可折叠，`chevron_left` 收起）+ 右宽图表**，图表占满剩余空间；
   我们目前是**单列**，图被压在小卡片里 —— 这是第 3 阶段第 1 个要改的。
2. **表单：label 在上、值大一号、浅填充 + 底边线**（不是四周描边的盒子）；
   一节一个小标题（`发射参数` / `图表设置`），一组一个"配置"。
3. **预置工况是按钮网格**（`短程（红外）` / `远程（主动雷达制导）` / `机动性` / `自定义预设`），
   点一下**直接改表单值**（实测：点"短程（红外）"把 `发射高度` 从 3000 改成 200）。
   我们是 `<select>` 下拉 —— 按钮网格更快、更能一眼看全。
4. **图表设置面板把"画什么"交给用户**：`过滤 Y 轴元素`（多选）、`动画速度`（1 倍）、
   `显示飞行标签`（勾选）、`标签元素`。我们目前是固定输出。
5. **回放动画**：它有"动画速度"，配合"显示飞行标签"就是在图上放弹道动画 —— 对**图3（机动想定）**
   特别合适，而我们的 `PathSchedule.samples()` 已经能给出逐点数据。
6. **整站 i18n**（右上角语言选择器，实测整页中文）。
7. **页脚 IA 完整**：`服务条款` / `隐私声明` / `常见问题` / `更新日志` / `法律声明` / Discord ——
   开源发布前正好需要这几样（我们只有 README）。
8. **404 也做成卡片**（大号蓝字 + 说明 + pill 按钮），不是一行裸文本。

### 7.3 抄 / 不抄（结论）

**照抄（低成本高收益，进第三阶段待办）**

1. 两栏布局 + 参数栏可折叠（左窄右宽，图占满）；
2. 预置工况改成按钮网格（替掉 `<select>`）；
3. 图表设置：Y 轴量过滤（我们 `ALL_FIELDS` 41 个字段里的轨迹量）+ 显示标签开关；
4. 图3 回放动画（播放/暂停 + 速度档）；
5. 页脚 IA（许可 / 隐私 / 更新日志 / 问题反馈）；
6. 错误页（404/500）做成卡片，带"回到首页"。

**要想清楚再做**

7. i18n：开源后是刚需，但手写全站的文案会成倍增长。**先做"文案集中"的准备动作**
   （把散在 `webui.py` / `app.js` 里的中文字符串收成一张表），不立刻上双语。
8. 大表格密度（它的"全服载具数据"是典型密集表格）—— 我们的 `report.py` 对比表可以借，
   但先量最宽一行的实际像素宽，别让横向滚动条成为默认体验。

**坚决不抄**

9. **任何前端框架**（Angular/Vue/React + 组件库）：它的 CSS 213 KB / 2769 个变量就是代价。
   我们是"纯标准库 + 离线免安装"，引框架等于把这个优势送掉（3D 线已实测手写 WebGL 只要 28 KB）。
10. **Plotly**：内联 JS 4.8 MB（`docs/FIG3D-FEASIBILITY.md` 里有否决依据）。
11. **Roboto / Material Icons / Font Awesome**：要联网或带字体文件；我们可用系统字体 + 内联 SVG 图标。

> 一句话：**抄它的"信息组织与交互"，不抄它的"技术栈与体积"。**
> 它的配色克制（默认 Material indigo，没有花哨渐变）恰好印证了我们亮色主题定案的风格取向。

### 7.4 证据与复现

| 证据 | 怎么复现 |
| --- | --- |
| 样式表（213 174 B，2769 个变量） | `.tmp_test/statshark.css`（已 gitignore）；`Invoke-WebRequest https://statshark.net/styles-2SGSLABJ.css`（**`web_fetch` 工具会拒绝该域名** —— 它被判成非公网 IP，用本机 pwsh 直连可拿到） |
| 首页/登录页、导弹计算器页、404 页 | 浏览器打开 <https://statshark.net/>，点左上 `☰` → `导弹计算器`；未登录也能用（它自己在登录页写明"查看玩家数据无需登录"） |
| token 统计（颜色/圆角/字体频次） | 对下载的 CSS 做正则分组统计，见 `NOTES.md` §26 |
| ⚠ 版权 | 只是**阅读参考**，页面上没有抄任何代码/文案/色值资产；**不要把它的截图提交进仓库**（讨论用截图只留在本机） |

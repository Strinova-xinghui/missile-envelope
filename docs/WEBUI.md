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
| `src/missile_sim/webui_static/viewer3d.html` | 图3 的 3D 查看器**整页**（无占位符） | `GET /viewer3d` 直发字节（**不**进静态白名单，见 §8） |
| `src/missile_sim/webui_static/viewer3d.css` / `viewer3d.js` | 3D 查看器的样式与逻辑（手写 WebGL2） | **不渲染**，`GET /static/viewer3d.*` 直发字节 |

设计口径：

* **boot 数据留在 HTML 里、内联**（`var DEFAULTS = …, PRESETS = …, META = …;`）：前端不用多打一次
  请求，且首屏就是完整的；`app.js` 因此**一个服务端占位符都没有**，可以放心加缓存头。
* **"读得到"与"发得出去"分开**：`read_page_file()` 只负责按名字读（basename 化挡穿越 + 只认
  `.html/.css/.js`），能不能对外发由 `WEB_STATIC_ASSETS` 白名单在**路由那一层**判。
  `index.html` **故意不在白名单里** —— 它带着没渲染的占位符，原样发出去会把 `__DEFAULTS__` 露给浏览器。
  `viewer3d.html`（3D 查看器整页）也不在白名单里，但理由不同：它是**没有占位符的整页**，
  走自己的 `GET /viewer3d`；白名单只放 CSS/JS 这类纯资源，页面数量变了也不用重新解释边界（§8）。
* `render_page()` 末尾用 `TOKEN_RE`（`__[A-Z][A-Z_]*__`）兜底：渲染完还剩占位符就**当场 500**，
  不允许页面静默残缺（这类失败以前只会表现为"某个下拉空的"）。

实测（2026-10-01，本机）：首页响应体 **36350 → 15507 字节**；`webui.py` **2203 → 1780 行**；
`app.css` 2626 B / `app.js` 15678 B（**拆分当时**的字节数；§5/§6 之后又长了，最新看
`git log -1 --stat`）。拆分**逐字节等价**：把拆前的 `render_page()` 产物、按两处替换
（`<style>…</style>` → `<link>`、`<script>` 主体 → boot 行 + `<script src>`)重建成"期望页面"，
与拆后的产物**完全相同**（唯一故意的内容改动是修掉页面里手写的 markdown 星号，见 §4）。

> 图4（β–γ–ΔV 交互式三维散点）走的是与查看器**同一套形态**：整页 `fig4.html`（**不**进
> `WEB_STATIC_ASSETS`，由 `GET /fig4` 直发字节）+ 白名单里的 `fig4.css` / `fig4.js` +
> 只读产物的数据层 `fig4.py`（`GET /api/fig4/<id>`）。口径、契约与判据见 `docs/FIG4.md`，
> 本文只登记它的路由与静态资源。

## 2. 路由表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` `/index.html` | 首页（`render_page()`） |
| GET | `/healthz` | 存活探针 + `targets` 是否可用 |
| GET | `/progress/<id>` | 任务快照（前端轮询它；`poll_ms` 来自配置，默认 500） |
| GET | `/static/<name>` | 首页自己的 CSS/JS，**白名单** `app.css` / `app.js` / `viewer3d.css` / `viewer3d.js` / `fig4.css` / `fig4.js` |
| GET | `/viewer3d` | 图3 的 3D 查看器整页（`viewer3d.html`；数据由下一条接口喂，见 §8） |
| GET | `/api/viewer3d/<job_id>` | 已跑完的图3 任务 → 查看器 JSON（默认 800 点、`?points=` 可覆盖；**不解算**） |
| GET | `/fig4` | 图4 的交互式三维散点整页（`fig4.html`；`?tag=` / `?job=` / `?bg=transparent`；数据由下一条接口喂，见 `docs/FIG4.md`） |
| GET | `/api/fig4/<tag_or_job_id>` | 图4 的立方体 + 逐列拟合 + 判别量 → 前端 JSON（`<id>` 既认任务 id 也认产物 tag；**只读产物、不解算**） |
| GET | `/figures/<name>` `/results/<name>` | 产物图片 / CSV / JSON，只在 `static_roots()`（`figures/`、`results/` + 配置里的目录）里按 **basename** 找 |
| POST | `/api/single` | 单工况同步求解（表单 → `Scene` → `solver.run`），返回 JSON |
| POST | `/api/submit` | 提交后台任务：`kind=scan`（扫描）/ `kind=plot`（只出图），`figure=plane/bg/traj/fig4/both/all` |

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

覆盖这一层的测试：`-k webui`（55 项，真起服务 + `http.client`，含图2/图3 端到端、静态资源白名单、
3D 查看器的页面/接口/静态资源）、`-k viewer3d`（12 项，上一条里那 12 项，另有跟手数值自检）、
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

## 8. 图3 的 3D 查看器（2026-10-01）

把 `3d-viz` 分支上那份**手写 WebGL2** 的尖刀稿（`spikes/fig3d/fig3d_viewer.html` @ `d05ad72`）
产品化：首页结果面板里内嵌一个可拖拽的 3D 轨迹 + 一个「在新标签页打开」。

### 8.1 三个文件 + 两条路由

| 文件 | 角色 | 由谁渲染 |
| --- | --- | --- |
| `src/missile_sim/webui_static/viewer3d.html` | 查看器**整页**（没有服务端占位符：job/点数/底透明度都从 `location.search` 读） | `GET /viewer3d` 直发字节 —— **故意不进** `WEB_STATIC_ASSETS` |
| `src/missile_sim/webui_static/viewer3d.css` | 亮色 chrome（`#f7f8f9` 底 / `#1f2933` 字 / `1px #d8dce1` 线） | `GET /static/viewer3d.css` |
| `src/missile_sim/webui_static/viewer3d.js` | 全部前端逻辑（数学 / 着色器 / 相机 / 交互 / 装配） | `GET /static/viewer3d.js` |
| `src/missile_sim/traj3d.py` | **数据层**：只读产物 → 查看器 JSON；抽稀；配色 | `GET /api/viewer3d/<job_id>`（懒加载） |

* `GET /viewer3d?job=<id>[&points=800][&bg=transparent]` —— 整页。`bg=transparent` 时页面与画布全透明，
  给内嵌用（宿主卡片兜底底色）；不带就是独立页的亮底。
* `GET /api/viewer3d/<job_id>[?points=N]` —— JSON，缺省 **800** 点、上限 **4000**。

**状态码分开说**（不要都折成 404）：id 不认识 → 404；任务还在跑 / 跑挂 → **409**；
`points` 不合法 → **400**（不静默截断）；任务里没有图3（图1/图2/`traj_preview=1`）→ 404 并说清是哪一种。

### 8.2 数据契约（`traj3d.build()`）

```jsonc
{ "ok": true, "job": "<id>", "tag": "default", "points": {"requested": 800, "missile": 800, "target": 800},
  "rows": {"missile": 3322, "target": 3322},
  "missile_name": "PL-12", "hit": true, "t_hit_s": 69.172, "miss_m": null,
  "t_beam_s": 34.458, "anchor": { ... },                       // 开机时刻与反求口径
  "launch": [...], "target0": [...],
  "missile": {"t": [...], "p": [[x,y,z], ...], "split_index": 398,
              "before_color": "#9a9a9a", "after_color": "#4d4d4d"},   // 两段
  "target": {"t": [...], "p": [...]},
  "segments": [{"t0": 0.0, "t1": 8.0, "kind": "straight", "label": "...", "phase": "...",
                "color_key": "grey", "color": "#7f7f7f", "heading0_deg": ..., "heading1_deg": ...}],
  "marks": [{"name": "seeker_on", "t_s": 34.458, "note": "...",
             "target": [x,y,z], "missile": [x,y,z]}],
  "colors": {"segments": {...}, "missile_before": ..., "missile_after": ..., "mark": ..., "hit": ...,
             "miss": ..., "guide": ..., "fallback": ...},
  "axis_note": "x / z 是水平面（航向 0° = +x、90° = +z），y 是高度" }
```

三条口径值得单独记：

1. **坐标**：`x`/`z` 是水平面、`y` 是高度（与 `results/traj_*.csv` 的列名逐字对齐，别把 `y` 当水平面）。
2. **配色全部来自 `figures`**（`TRAJ_COLORS` / `TRAJ_MISSILE_COLOR` / `TRAJ_MISSILE2_COLOR` /
   `TRAJ_MARK_COLOR` / `TRAJ_HIT_COLOR` / `TRAJ_MISS_COLOR` / `TRAJ_GUIDE_COLOR` /
   `TRAJ_FALLBACK_COLOR`）—— 前端一个数据颜色字面量都不写，"沿用配色"这条是**可测**的
   （`tests/test_viewer3d.py` 逐键相等）。
   导弹切成两段是**两个色相**：开机后用静态图同色的 `TRAJ_MISSILE2_COLOR`（紫 `#8e44ad`，不淡化），
   开机前用 `mix_hex(TRAJ_MISSILE_COLOR, #f7f8f9, 0.45)` 的**同色相派生**（深灰向亮底混，表达"未激活"）。
   ⚠ 这两者必须不同：2026-10-02 合并 `3d-viewer` 与 `3d-viz` 时，查看器只取了
   `TRAJ_MISSILE_COLOR`（静态图当时还没第二条曲线），于是静态图是「深灰→紫」、查看器是「浅灰→深灰」，
   **而 `-k viewer3d` 照样全绿** —— 现在那条用例里多了"两色不相等"的回归钉。
3. **`split_index` 按响应里给的那份数算**：`t` 与 `t_beam_s` 都落到 3 位小数，客户端 `bisect` 一遍
   能复现同一个切分点（`t[split-1] < t_beam_s <= t[split]`）。用原始行算会差在 1e-4 s 上 ——
  实测默认工况的真实行 34.4583 与 `t_beam = 34.4583343` 在 3 位小数上相等，契约就不可复核了。

### 8.3 抽稀：**阶段拐点与节点时刻必须留下**

`traj3d.decimate_indices(n, n_max, forced)`：先把 `forced`（每个 `Segment` 的 t0/t1 最近采样 +
每个节点时刻最近采样 + 开机点）拿出去，再在**剩下的**点上等间隔取，总数**恰好 ≤ n_max**。

⚠ 别改成"先等间隔、再补拐点"：返回点数会变成 `n_max + len(forced)`，"默认 800 点"当场失效，
而画面上看不出任何异常。反证在测试里：纯等间隔（老 `make_viewer_data.py` 的做法）**恰好会抽掉**
crank→39 的拐点（`tests/test_viewer3d.py::...decimation_keeps_segment_corners_and_marks`）。

实测（本机，默认工况 3322 行，`json.dumps(separators=(',',':'))`）：

| 点数 | 响应字节 | 说明 |
| --- | --- | --- |
| 800（默认） | **53 201 B** | 首页内嵌的就是它 |
| 1200 | **78 340 B** | `?points=1200` |
| 4000（上限） | 206.8 kB | 原始 3322 行 ⇒ 到顶就是全部点 |

### 8.4 交互契约：「跟手」只有一处符号

拖动 = **抓住物体转**（跟手），不是镜像。判据可复现：

* 符号**只**出现在 `viewer3d.js` 的 `applyDrag()`：`cam.az += dx * AZ_PER_PX;`（`AZ_PER_PX = 0.008` rad/px）；
  全文件 `cam.az +=` 恰好 2 处（另一处是自动旋转 `tick` 的 `cam.az += dt * 0.35;`），`cam.az -=` 一处都没有。
  测试把**注释行去掉**之后数这个数，并且断言 `pointermove` 里没有第二个符号。
* 数值（`?dragtest=200` 会把同一张表打进页面；`tests/test_viewer3d.py` 用 node 跑同一份 JS）：
  1100×700 画布下，拖 Δx = **+200 px** ⇒ 视轴近侧见证点 dx = **+92.17 px**；镜像写法 dx = **−92.17 px**。
  ⚠ 见证点必须落在"物体正对观察者的那片表面"：环绕相机绕 center 转，离轴远的世界点
  （发射点/结束点/最高点）位移方向会**反过来**，它们在自检里只是参考、不作判据。
  ⚠ 尖刀稿自报的是 **+105.3 px**（它那份几何里带了 110°/90° 参考射线，拟合半径更大 ⇒ 视距更远、
  每米像素更多）；两处的**符号**一致，绝对值随视口/拟合半径变 —— 判据钉的是符号与镜像取负，
  数值只给一个宽松带（60~140 px）。

### 8.5 「不解算」怎么钉住

`traj3d.py` **不 import 求解器**；`tests/test_viewer3d.py::...solver_run_is_never_called` 把
`solver.run` 换成一个"一被调用就炸"的桩，然后走**数据层 + HTTP 路由**各一遍；
`test_webui_traj.py` 那条真跑一次的用例里，任务跑完后再取一次查看器 JSON（毫秒级，不是秒级）。

### 8.6 覆盖这一层的测试

`-k viewer3d`（12 项，1.5 s：契约 / 800 与上限 / 拐点保留 / 零解算 / HTTP 状态码分离 / 白名单 /
零第三方与亮色 / 跟手文本判据 / 跟手数值（有 node 才跑）/ `app.js` 内嵌）、
`-k webui`（55 项，30 s）里另含真跑一次的 e2e（`test_webui_traj_pinned_t_beam_solves_and_reports_the_hit`
尾部追加的那几条：真解算一遍 → 任务产物喂给查看器 → 800/1200/4001 三种点数 → `/viewer3d` 整页）。
全量：**361 项通过**（本轮之前 349 项，本层 +12；`-k traj` 72 项，因函数名含 `traj` 多收 1 项）。
⚠ 这是**当时（task-12 那一轮）的口径**；2026-10-02 合并五分支后全量已涨到 **402 项**，
`-k traj` 为 **68 项**（见 `NOTES.md` §30.2）。

### 8.7 真浏览器实测（2026-10-01，本机 Chromium / `browser-skill`）

| 项 | 实测 |
| --- | --- |
| 独立页 `/viewer3d?job=<id>` | 200，881 B；无 JS 报错（只有 `favicon.ico` 404）；三维轨迹、网格、坐标轴、图例、6 个节点都画出来了 |
| `?dragtest=200` 页内自检 | `物体近侧表面(视轴) 0px \| +16.8 -16.8 \| +17.9 -17.9 \| +92.6 \| OK`；`弹道最近视野中心点 20px \| +14.6 -14.6 \| +14.0 -14.7 \| +79.3 \| OK`；`DRAG primary_witnesses=2 follow_x_ok=2/2 follow_y_ok=2/2 ok=1`（画布 1348×703，dpr 1.25） |
| 滚轮缩放 / 「复位」 / 「自动旋转」 | 三者都生效；「复位」把视图精确还原到首帧（与首帧截图逐像素同款） |
| 首页内嵌（`figure=traj` 从页面提交 → 结果卡片） | iframe 出现在 `.v3d` 卡片里，顶部有「可拖拽三维轨迹：左键旋转 / 滚轮缩放 / 右键（或 Shift + 左键）平移」+ 右侧「在新标签页打开」；iframe 里渲染与独立页一致 |
| ⚠ 抓到并修掉的一个真 bug | `bg=transparent` 时清屏清成了**「亮底色 + alpha 0」**：WebGL 画布默认预乘 alpha，`RGB > A` 是非法预乘值，合成器把它当半透明暗色 ⇒ **整张图蒙一层灰雾、细线断成点线**（内嵌视图第一眼就能看出来，`-k webui` 完全测不到）。改成透明的清屏值 **(0,0,0,0)**，实测恢复正常。 |

**没做 / 没验**（写清楚，免得下次当成做过了）：

* **真正的鼠标拖拽手势**没有在浏览器里做（`browser-skill` 只给点击/滚轮/悬停，没有 press-move-release）。
  跟手这条链路上，"`applyDrag` 的符号 + 数值"用页内自检（`?dragtest=`）与 node 跑过，
  "pointermove → `applyDrag(cam, dx, dy)`（且没有第二处符号）"用文本判据钉住 —— 中间那段
  **指针事件接线**仍是人眼读代码，没人用真手势走过一遍。
  （**同日已由 Lead 用 `bsk evaluate` 发合成真事件补上，数字见 §8.8**；人手的"手感"仍只有人能给。）
* `-k viewer3d` 里的数值自检**需要 node**；没有 node 的机器会打印一行说明后跳过（文本判据照跑）。
* 查看器**不动**旋钮：点数只吃 URL（`?points=`），页面上没有点数输入框；改点数请直接改 URL。
* 没有做"动画回放/时间轴"（§7 参考站那条"图3 回放动画"仍是待办）。

### 8.8 Lead 外部验收（2026-10-01，与作者无关的一方重跑）

作者在 §8.7 里点名了一条"没人走过"的链路：**真指针事件 → 旋转**。Lead 用 `bsk evaluate` 在真页面补齐，
并且**不采信作者的自检**，另起一套判据（工具留在 `.tmp_test/`，不进仓库）：

| 判据 | Lead 的独立取证 | 结论 |
| --- | --- | --- |
| 判据重跑 | `-k viewer3d` **12/12**（1.3 s）、`-k webui` **55/55**（27.2 s），跑完工作树干净 | 与作者数字一致 |
| 契约 | `/api/viewer3d/<job>` 200、59 847 B、`points{requested:800,missile:800,target:800}`、`missile{before_color:#9a9a9a, after_color:#4d4d4d, split_index:399}` | 两段换色确实进了接口 |
| 拐点保留（比作者更严） | 5 段 × `t0/t1` + 6 个节点 = **16 个时刻**逐个在抽稀后的 800 点里找最近点：最大偏差 **0.007 s**（原始步长约 0.02 s） | 16/16 保住 |
| 点数与上限 | 1200 → 88 186 B / 1200 点；4000 → 238 545 B / **3322 点（原始行数到顶）**；100000 → **400** `points 最多 4000` | 上限不是静默截断 |
| 离线底线 | `/viewer3d` 整页 881 B；扫 `http(s)://` 外链 **0 个** | 无第三方 |
| 静态白名单（裸 socket，绕开客户端归一化） | 13/13：`app.js`(21 326 B) / `app.css` / `viewer3d.js`(30 874 B) / `viewer3d.css` → 200；`index.html`、`nope.js`、**`../webui.py`**、**`%2e%2e%2fwebui.py`**、**`..%2f..%2fREADME.md`**、`APP.JS`、`viewer3d.js.bak` → 404 | fail-closed ✓ |
| **真指针事件（补 §8.7 那条）** | 页面里 `fetch` 同一份数据 → `TRAJ3D.viewer(gl, d)` 起第二个实例 → 对它的 canvas `dispatchEvent` 真 `PointerEvent`（down/move/up）：拖 **+200 px** ⇒ `cam.az` **−1.05 → +0.55（Δ = +1.600 = 200 × 0.008，一位不差）**，**钉死的同一个世界点** `[27233.1, 12041, 4702.1]` 屏幕 x **449.39 → 531.75（+82.36 px，同向）**；再拖 **−400 px** ⇒ Δaz **−3.200**、dx **−163.35 px**（镜像） | 跟手 ✓，走的是真实事件接线 |
| 真页面（不是离屏副本） | 对可见 `#cv` 发 +200 px 拖拽 → 两张截图逐像素比：**3.33%** 采样像素改变，数据色（橙/红/青/蓝，容差 30）质心 **Δx = +152.9 px** | 真页面确实转了、且同向 |
| 入口形态（用户拍板项） | 从页面提交 traj → 结果卡片里 `iframe[src="/viewer3d?job=…&bg=transparent"]`（1013×518）+ `a[href="/viewer3d?job=…"]`「在新标签页打开」（**去掉 `bg`** ⇒ 独立页亮底） | 内嵌 + 新标签页都在 |

⚠ **三条诚实的边界**：

1. 事件是**合成**的（`isTrusted=false`，不是人手），但走的是页面**自己的监听器**。
   `cv.setPointerCapture()` 对合成 pointerId 会抛 `NotFoundError`（控制台可见，`viewer3d.js:480`）——
   无害，因为 `dragging` 在**前一行**赋值（源码顺序即证据）。真手势的"手感"仍只有人能给。
2. **垂向**跟手没能取到有说服力的证据：该轨迹 50 km 长、高 12 km，投影后弹道点几乎全挤在水平中线附近
   （连"最靠上"的点也只离画布中心约 20 px），拖 +50 px（Δel = +0.4，与 `EL_PER_PX` 一致）只让见证点动
   **−0.1 px**，拖 −100 px 动 **+3.22 px**。符号与 three.js OrbitControls 同惯例（`cam.el += dy * EL_PER_PX`
   只有一处定义），但"肉眼能看出随手上跑"这件事**未证** —— 要证得换一个垂向尺度更大的想定，
   或给初始视角加一点俯仰偏置。
3. **验收工具自己也会说谎**（这轮实测到两次，都改掉了）：第一版探针按 `missile: [...]` 取点数
   （实际契约是 `missile: {t, p, split_index}`）⇒ 误报"点数不符"；第一版见证点**每帧重选**
   "离屏幕中心最近的点" ⇒ 量到的其实是两个不同的物体。改成 `s.x / s.y` 并**钉死同一个世界点索引**
   之后结论才成立 —— 所以**先拿旧产物把验收器验出 FAIL，再去信它在新产物上的 PASS**。




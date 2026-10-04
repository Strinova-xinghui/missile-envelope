# 候选托管方/参考站 `sensorwhale.com` 的事实清单（2026-10-04 取证）

> 目的：评估"与 sensorwhale.com 合作托管"的可行性与风险。本文**只记可公开的事实与出处**；
> 截图存证留在 `.tmp_test/sensorwhale-home.png`、`.tmp_test/sensorwhale-missile-calc.png`（gitignored，不进仓）。
> 抓取方式：本机直连（已关代理）+ 真浏览器渲染 + 抓包，均为 2026-10-04 实测。

## 0. 一句话

大陆**个人备案**的小型战雷数据工作台（首页自报 717 注册用户 / 3,454 次计算 / 当前在线 1）。
**算核完全在浏览器**（首页自述 "OFFLINE · 本地计算 · 无遥测"、"ENGINE FM-CORE"，界面注释提到
"encrypted engine"，CSP 允许 `wasm-unsafe-eval` 与 `worker-src blob:`）；
**游戏数据不随站分发** —— 运行时从 jsDelivr 上的公开 datamine 镜像按 commit 拉 `*.blkx`。

## 1. 运营与合规（事实 + 出处）

| 事实 | 证据 |
| --- | --- |
| 备案号 **沪ICP备2026034415号-1**，备案类型 **个人**，备案主体 **李海锐**，域名 `sensorwhale.com`，更新时间 **2026-10-03** | 公开备案查询页 `https://icplishi.com/沪ICP备2026034415号/`（2026-10-04 抓取） |
| 首页响应头 `Server: Caddy`、`Alt-Svc: h3=":443"`、`Last-Modified: 2026-09-24`；解析 `124.221.195.231`（腾讯云段），权威 DNS `dnspod.net` | 直连 `https://sensorwhale.com/` 的响应头 |
| 前端 = Preact SPA（`<html lang="en" class="dark">`，资源 `assets/renderApp-*.js|css`），
  CSP 引 `gcaptcha4.geetest.com` / `static.geetest.com`（**极验 4 代验证码**） | 首页 HTML 原文 |
| 社区入口：**QQ 交流群 821597965** | 首页渲染文本 |
| **全路径假 200**：`/terms`、`/privacy`、`/robots.txt`、`/license`、`/sitemap.xml`、`/openapi.json` 全部返回
  同一份 **10,951 B HTML**（SPA 回退） | 逐路径探测（HTTP 200 + 同一长度/内容）⇒ 站点政策页抓不到静态文本 |
| 首页口径与数据的矛盾点：首页写 "游戏飞行模型 **1:1 复刻**"，页脚却写
  "**FM 数据为本地近似,非 datamine 原值 · 仅供分析,请勿用于 bug 上报**" | 首页与页脚渲染文本（逐字） |
| 规模：**717 注册用户 / 3,454 累计计算·查询 / 666 玩家档案 / 当前在线 1**；`SYS ONLINE · ENGINE FM-CORE · LATENCY 64~114 ms · BUILD rework·2026.06` | 首页统计区渲染文本 |

## 2. 架构（事实）

| 事实 | 证据 |
| --- | --- |
| **算核在浏览器**：首页徽标 "OFFLINE · 本地计算 · 无遥测"；工具集文案 "点击任意卡片进入 · **全部本地计算**" | 首页渲染文本 |
| 算核是**加密**的 WASM 资源 | 首页 HTML 注释 "when the **encrypted engine** finishes booting"；CSP `wasm-unsafe-eval` + `worker-src 'self' blob:` |
| 后端只有小 API，**不算物理**：`/api/health`（`{"status":"ok","uptimeMs":826998758}` ≈ **9.6 天**）、`/api/stats`、`/api/me`（×2）、`/api/ai-analyzer/providers` | 抓包（2026-10-04） |
| 有**开 DevTools 上报**：`POST /api/ops/devtools-event`，并被限流（多次 **429**） | 抓包；与首页"无遥测"的口号**有出入**（也可能只指"不上报计算输入/结果"） |
| **游戏数据不随站分发**：导弹参数运行时从
  `https://cdn.jsdelivr.net/gh/gszabi99/War-Thunder-Datamine@<commit>/aces.vromfs.bin_u/gamedata/weapons/rocketguns/*.blkx` 拉取，
  且按**多个不同 commit** 各拉一份（对应它的"版本对比"功能） | 抓包 URL 列表 |
| 它自产的**版本清单**是自家资产：`/datamine-snapshots/versions-manifest.json`
  （`generatedFrom: scripts/datamine-versions.mjs`、`baseline: 2.56.0.32`、`units[].allTags`） | 该 JSON 原文 |

## 3. 产品面（与我们重叠 / 互补）

| 它有什么 | 与我们的关系 |
| --- | --- |
| **导弹计算器**：自述 "Offline proportional-navigation **point-mass** simulation · **487 guided missiles**"，可换导引头
  （原始(数据矿)/无制导(火箭)/红外 IR/半主动雷达/主动雷达），输入投放速度/高度/俯仰/偏航 + 目标速度/高度/初始距离/方位/航向/过载，
  输出时序量；右侧自述 "Missile parameters are derived from datamine values; outputs … **intended to approximate in-game behaviour**" | **互补，不撞车**：它做"单次交战时历"；我们做"跨弹**能力包线**（ΔV–β / β–γ / ΔV–β–ginv 三维）"。
  它自认是**质点近似**，我们是 6DOF float32 位序复原 ⇒ **精度是我们的差异化** |
| `FM 计算器` / `爬升优化`（SEP 能量图、最优爬升剖面）/ `雷达计算器` / `雷达沙盒` / `空战沙盒` / `红外对抗` / `知识库` / `玩家查询`（Gaijin 战绩 + 5 档评分）/ `AI 锐评`（DeepSeek，24 h 缓存） | 与我们的"沙盒（图4）"部分重叠；但它做**整机 FM 与雷达/对抗**，我们做**导弹能力包线** |
| 首页自报 "18 机型 FM 数据 / 10 图表类型 / TWS 雷达模拟 / 5 档技术评分 / 离线 · 无遥测" | 全是**客户端能力**，无服务器算力型功能 |

## 4. 对我们的三条可搬实践

1. **游戏数据用公开镜像运行时拉取（可钉 commit）**：既不分发游戏数据，又天然得到"版本对比"能力 ——
   直接解决我们"公开集不能带 `inputs/`"的老问题（代价：依赖第三方镜像的可用性与它的许可/权利链）。
2. **算核搬到浏览器**（WASM + Worker）：服务器零算力成本，且不触发 AGPL 第 13 条；
   代价是引擎与（部分）数据要下发到客户端。
3. **成品"壳"组合可直接照抄**：大陆云（腾讯云）+ **Caddy** + DNSPod + 个人备案 + 极验验证码 +
   极简 JSON API（账号/统计）+ 端点级限流（429）。

## 5. 没查清的（照实记）

1. 那个加密 WASM 引擎**是什么**（自研？何种加密/打包？是否可被浏览器端提取）—— 只从 CSP 与注释推断，未取资源分析。
2. 站点**没有可静态抓取的《服务条款/隐私政策》**（全路径假 200）⇒ 用户协议只能登录后在界面里看，或直接问运营者。
3. `/api/*` 的完整路由与是否存在开放 API（`/openapi.json` 是假 200，无法枚举）。
4. "无遥测"与 `devtools-event` 上报的口径差异，需要问运营者解释。
5. 它的数据镜像链（`gszabi99/War-Thunder-Datamine` → jsDelivr）的可用性/许可边界未评估（**那正是我们自己在用的同一份公开镜像**）。

# 候选托管方/参考站 `sensorwhale.com` 的事实清单（2026-10-04 取证）

> 目的：评估"与 sensorwhale.com 合作托管"的可行性与风险。本文**只记可公开的事实与出处**；
> 截图存证留在 `.tmp_test/sensorwhale-home.png`、`.tmp_test/sensorwhale-missile-calc.png`（gitignored，不进仓）。
> 抓取方式：本机直连（已关代理）+ 真浏览器渲染 + 抓包，均为 2026-10-04 实测。

## 0. 一句话

大陆**个人备案**的小型战雷数据工作台（首页自报 717 注册用户 / 3,454 次计算 / 当前在线 1）。
**算核完全在浏览器**（首页自述 "OFFLINE · 本地计算 · 无遥测"、"ENGINE FM-CORE"，界面注释提到
"encrypted engine"，CSP 允许 `wasm-unsafe-eval` 与 `worker-src blob:`）；
**游戏数据不随站分发** —— 运行时从 jsDelivr 上的公开 datamine 镜像按 commit 拉 `*.blkx`。

⚠ **"中国人自己的 StatShark"这个说法查无公开出处**：站内 bundle 里 `statshark/StatShark` **0 命中**，
公开检索（多引擎 / B 站 / GitHub / `site:` / 多组中文措辞）也**零相关结果**（2026-10-04 独立子代理复核）。
该说法目前只见于用户口径，最可能只存在于它的 QQ 群公告里 —— 引用时**不要当事实**。

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

## 6. 补充实测（独立子代理复核，2026-10-04）

| 事实 | 证据 |
| --- | --- |
| **加密内核形同虚设**：`GET /protected/fm-core.enc`（476,842 B）与 `/protected/fm-core-wasm.enc`（9,302 B）头部是自定义魔数 `SWEN\x01`（**不是** wasm 的 `00 61 73 6d`）；而 **`GET /api/engine-key` 无鉴权、明文返回解密密钥**（54 字符 base64） | 直接 HTTP 取证；启动画面自述 "Decrypting the physics core…" |
| 前端体量与防护：入口 `index-BdlSUrQw.js`（14,848 B，**javascript-obfuscator 混淆**：字符串数组 + RC4）、`renderApp-Bij9yZ6L.js` **9,318,044 B**、CSS 192,792 B；3D 用 Three.js（MIT 头）；**Preact + Vite** | 构建产物实测 |
| 配额（对匿名访客）：`GET /api/me` → `{"role":"guest","limits":{"calcPerMin":2}}`；连发约 14 次触发 **429** | 实测 |
| 完整 API 面：`/api/health`、`/api/stats`、`/api/me`、`/api/engine-key`、`POST /api/engine/session`、`/api/ai-analyzer/providers`、`POST /api/ops/bundle-access-check`(204)、`POST /api/ops/devtools-event`；`/api/ai-analyzer/review` → **403**；**无任何开放 API 文档**（`/api/openapi.json`、`/api/docs` = 404，另试 14 个常见路径全 404） | 逐端点实测 |
| `/api/ai-analyzer/providers` **无鉴权暴露** provider 清单（百炼 DashScope / 火山 volces / `local`(`http://127.0.0.1:8123`)），`apiKey` 返回空串 ⇒ AI 锐评走服务端代理 | 实测 |
| **站内没有任何条款/隐私/ICP/版权行**：`/terms`、`/privacy`、`/about`、`/robots.txt` 全是 SPA 假 200；bundle 内 `'/terms'`、`'/privacy'`、`'license'` 命中 0；**无 robots.txt** | 静态抓取 + bundle 检索 |
| 基础设施：反代 `Server: Caddy`；源站 `124.221.195.231` = **中国上海 · 腾讯云 · AS45090**；NS = 腾讯 DNSPod；证书 **Let's Encrypt 2026-09-21 → 2026-12-20（90 天）**；静态资源**同源直出、无 CDN、无 `Cache-Control`**；**推断**单机单节点 | 响应头 / DNS / 证书实测 |
| **处理 Gaijin 凭据**：bundle 含 `gaijinClientId`、`regenerateGaijinClientId`、**`testGaijinLogin(email,password)`**，并有片段 `Gaijin 账号…存储,绝不上传。`（前后自相矛盾） | bundle 检索 |
| 注册体系：邮箱 + 密码 + 极验验证码 + 安全问题；**无任何数据留存/处理说明** | 实测 |
| 规模权威值来自 API（首页数字是滚动动画）：`/api/stats` → `{"registeredUsers":717,"totalRequests":3454,"cachedPlayers":666,"onlineNow":1}` | 实测 |
| 知识库明写数据来源：`All .blkx data is from the gszabi99 War-Thunder-Datamine GitHub mirror; the in-game-effect meanings are interpolated by the author and may contain flaws. This is an enthusiast reference, NOT for bug reporting.` | 知识库页原文 |
| **无任何付费/赞助入口**（bundle 内 `会员/赞助/捐赠/付费/充值/订阅/sponsor/donate` 命中全 0）；无公告页 | bundle 检索 |
| 与 StatShark 对照（事实）：`statshark.net` 是 **Cloudflare + Angular + 11 语言**，重心"玩家/载具统计对比"；SensorWhale 是**腾讯云大陆单机 + 双语**，重心"复现游戏模型的计算器"；StatShark 有贴吧自述"经开发者 Hadi 授权组建中文社区"，SensorWhale **只有 QQ 群** | 双方站点实测 + 公开帖 |

### 6.1 三条对我们有直接影响的推论（标"推断"）

1. **它的"加密护城河"是纸的**：密钥对匿名访问者公开 ⇒ 任何人都能离线拉走并在自己页面跑同一套内核。
   教训（对我们是好消息也是警告）：**加密 ≠ 保护**；我们真正的杠杆是 AGPL + 校准/数据/体验，而不是把引擎藏起来。
2. **架构级不匹配**：它的算力在浏览器（加密 WASM），我们是**服务端 Python 重 CPU 任务**（fast 档 1824 点 ≈ 0.27 min）；
   共用它那台腾讯云单机 = 我们的请求与它 717 个用户抢同一台机器。
3. **没有合规兜底**：个人备案 + 无条款/隐私政策 + 用户凭据（含 Gaijin 账号处理）都在他手上 ⇒ 与他联署会把我们的声誉绑上去。

## 7. 合作尽调问题清单（31 条，A–I 组；**C 组是硬前提**）

> 用法：**C 组任一条对方不接受，其余都不必谈**；B/G 是技术硬约束，F 是法律硬约束，A/D/E/H/I 是条款细节。

**A. 主体与责任**
1. 签约对方是个人（备案主体"李海锐"）还是公司？→ 个人备案无法开票、责任财产有限；出事只能追个人。
2. 有没有公示的运营主体 / 用户协议 / 隐私政策？→ 把用户数据放在**没有隐私政策**的站上会被指违规；风险会落到我们头上。
3. 现有 717 用户 / 666 玩家档案里的 Gaijin 昵称、邮箱、AI provider key 由谁持有、存多久、谁能导出？→ 决定是否与他混库；混了我们就成了共同控制者。

**B. 域名 / 证书 / 服务器 / 带宽 / 成本 / 降级**
4. 域名（sensorwhale.com）与证书归谁？我们拿子域还是子路径？→ 答错 = 入口永挂别人域名下。
5. 共用他那台腾讯云上海单机，还是给我们独立额度？CPU/内存/并发上限多少？→ 我们是重 CPU 任务；答错 = 双方用户一起卡死。
6. 现在没有 CDN、没有 `Cache-Control`；我们的静态图/WASM 直出还是走 CDN？→ 答错 = 图出不来。
7. 成本谁承担（域名/证书/机器/带宽/存储）？有无月流量上限与突发额度、超限怎么降级？→ 答错 = 要么账单甩我们，要么超限全站 502。
8. 谁负责证书续期与监控告警？→ 90 天证书（当前 2026-12-20 到期），无人续期 = 整站告警页。

**C. AGPL 连带与授权（最硬前提）**
9. 托管的是**原样部署**还是**他们的修改版 / 与 fm-core 的合并版**？→ AGPL-3.0-only 第 13 条只对"通过网络交互的**修改版**"要求提供对应源码；答错 = 我们对上游读者的源码义务无法履行。
10. 若托管修改版，他们是否接受"必须向该站用户提供他们的对应源码"？→ 法律底线，不是礼貌；不接受 ⇒ 唯一合法路径只剩"版权人另行授权"。
11. 若给例外/商业授权：排他还是非排他？可否撤销？范围到哪（仅托管？可否修改 / 二次分发 / 商用 / 再许可）？→ 给宽 = 丧失控制与未来双许可空间；给窄 = 对方不签。
12. 例外是否要求他们**回传**对内核/前端的一切修改？→ 不回传 = 出个闭源分叉却拿不到改进。
13. 我方是否已有 **CLA/DCO**？→ 没有 CLA，未来任何外部 PR 都会让例外授权失效。
14. vendored 内核与 LICENSE 口径（内核归我方；`vendor/wt-missile/inputs/` 游戏数据不随公开集）他们是否知情并接受？→ 两种交付口径法律风险完全不同。

**D. 品牌与归属**
15. 署名怎么写（"官方"/双 logo）？域名、商标归谁？→ 被抢注或反向主张后，我们连自己工具的叫法都受限。
16. 用户数据与产物（CSV/JSON/图像/历史）权利归谁？能否被二次使用？→ 产物含算法指纹与用户数据。
17. 我们能否把这次合作作为案例对外宣传？→ 单向禁言会让我们在自家社区无法解释。

**E. 排他性**
18. 是否要求独家？我们能否**同时自建站点**、同时与 StatShark 类第三方合作？→ 独家锁死渠道与议价。
19. 若我们自建，他们能否要求下架或索费？→ 与排他互为表里。

**F. 数据来源与合规**
20. 他们自用 datamine 数据的风险谁承担？我们"不含游戏数据"的交付他们接受哪种？→ 我们仓库明确排除 Gaijin 数据；随包发数据 = 把风险搬进我们仓库。
21. 我们结论与他们的计算器结论冲突时，对外口径归谁？→ 同站两个"复现游戏模型"的数字不一致，会同时砸掉两边可信度。
22. 会不会被当 bug 上报材料？（他们自己写"请勿用于 bug 上报"）→ 口径必须一致。

**G. 算力与滥用**
23. 谁负责配额/限流/防刷？我们的重任务是否也吃 `calcPerMin=2`？→ 我们一个请求可能顶他几百个；答错 = 正常用户被限流，站长来找我们。
24. 被刷爆/被挖矿式调用时谁背锅？有没有一键降级/停机开关？→ 避免"别人刷，账单给站长"。
25. 他们算在客户端、我们必须服务端算 —— 这个矛盾怎么解（谁改前端、谁出算力、是否容器化/队列）？→ **架构级不匹配**，不谈清必卡在联调。

**H. 可迁移性与退出**
26. 停合作后：域名、证书、用户、日志、产物、缓存谁带走？我们能否完整导出？
27. 我们能否用他们的配置/镜像独立复现部署？→ 答错 = 被"事实锁定"，只能续约。
28. 用户表/计算缓存的迁移格式与时限？→ 影响自建站冷启动。

**I. 交付与边界**
29. 他们提供什么（托管/运维/推广/数据/带宽/中文社区）？我们给什么（代码/授权/品牌/内容）？→ 边界不清 = 每次扯皮。
30. 是否要求我们接入他们的加密闭源内核？→ 一旦产生"合并作品"，AGPL 边界与例外授权范围都会变复杂。
31. 是否要签 NDA / 竞业？→ 影响后续与其他平台合作与自建。

## 8. 追加"没查清的"（本轮子代理）

1. **"中国人自己的 StatShark"仍零原文**：若真有出处，最可能是 **QQ 群 821597965 的群公告/群文件**（无法访问）。
2. 备案未在 **MIIT 官方站**复核（目前只有第三方镜像页）。
3. 站内那个 `id='about' / cn='关于'` 条目**在 UI 里没能打开**（可能含作者自述/免责）。
4. 是否存在**仅管理员可见**的付费/赞助层。
5. **凭据如何存储**（邮箱/密码/Gaijin 账号）没有直接证据。
6. 服务器规格 / 带宽 / 真实成本外部不可得（无 status 页）；whois 未取到。
7. `.enc` 内核**未尝试解密**（只验证了"魔数 SWEN + 密钥公开可取"这两个事实）。

# 分发：免安装版打包

对方拿到 `导弹包线图.zip` → 解压 → **双击 `启动.bat`** → 浏览器自动打开界面。
**不需要装 Python、不需要联网、不需要 C 编译器。**

## ⚠ 许可与分发边界（出包之前先读）

**本仓库 / 本包按 AGPL-3.0-only 发布**：根目录 [`LICENSE`](../LICENSE) = **GNU Affero General
Public License, Version 3** 的官方全文逐字（<https://www.gnu.org/licenses/agpl-3.0.txt>，含
preamble 与 "How to Apply These Terms"；首行只加版权归属），SPDX **`AGPL-3.0-only`**
（**钉死版本，不是 `or-later`**），**2026-10-04 起生效**（此前那份宽松许可已作废；决策过程见
[`OSS-LICENSE.md`](OSS-LICENSE.md)）。中文要点写在 `README.md` §9.5（**非官方译述，冲突以
`LICENSE` 英文原文为准**）；面向收件人的口径写在包内 `app/README.md` 与 `app/使用说明.txt`，
**许可正文本身随包放在 `app/LICENSE`** —— 它登记在 `REQUIRED_IN_BUNDLE` 里，漏拷会在组装期直接炸
（AGPL 第 4/5 条：分发时必须把许可正文与版权声明一起交出去）。

| 这份软件能不能… | 结论 |
| --- | --- |
| 自用 / 学习 / 研究 / 改一份自用 / 企业内部使用 | ✅ 允许（**不分发**就没有额外义务） |
| **商用** | ✅ 允许 —— AGPL 不禁商用 |
| 分发原版或修改版 | ✅ 允许 —— **必须**附完整对应源码 + 本 `LICENSE` + 保留版权与许可声明 |
| 修改版**闭源**分发 | ❌ 禁止（copyleft：衍生作品必须同样以 AGPL 授权） |
| **通过网络对外提供本工具的能力**（SaaS / 在线接口） | ⚠ 可以，但**必须向使用者提供完整对应源码**（**第 13 条 "Remote Network Interaction"**） |
| 想豁免 AGPL 义务做闭源商用 | ✉️ **可联系作者另行授权**（联系作者即可谈） |

**AGPL 覆盖什么 / 不覆盖什么**：覆盖**本仓代码 + `vendor/wt-missile/` 内核（作者自有，
2026-10-01 归属确认）**；**不覆盖** `vendor/wt-missile/inputs/**` 的 War Thunder 游戏数据
（权利归 Gaijin，见下）。

**第三方义务不被上面那份许可覆盖**（这些许可**都与 AGPL-3.0 兼容**，可聚合分发、不需改任何代码，
只需声明与保留）：内嵌 Python = **PSF-2.0**、`numpy` = **BSD-3-Clause**、`matplotlib` / `Pillow` /
`contourpy` / `kiwisolver` / `cycler` = **BSD 系**、`fonttools` / `pyparsing` / `six` = **MIT**、
中文字体子集 = **SIL OFL 1.1** —— 各自的声明照旧随包（`make_dist.py` 会把内嵌 Python 的
`LICENSE.txt` 与各 `dist-info` 一起带上）。

**游戏数据是另一条独立的线**（与选哪个许可无关）：包里**含 War Thunder 游戏数据**：
`app/vendor/wt-missile/inputs/` 下的 **168 份 `.blk`**
（权利归 **Gaijin Entertainment**；**AGPL 不覆盖它，也替它授权不了**）。求解器内核硬依赖它，
去掉就跑不了 —— 这是"拿到就能用"与"能公开分发"之间的**唯一冲突点**。

| 这份包能不能… | 结论 |
| --- | --- |
| 自用 / 发给同事朋友小范围用 | ✅ 可以 |
| 传公开仓库、公开网盘链接、论坛附件 | ❌ **不行** |
| 内核源码（`wt_missile.py`） | ✅ 自有代码，随包分发没问题（见 `vendor/wt-missile/VENDOR.md`） |

⇒ 要**公开分发**必须另出一个**不含 `inputs/` 的变体**：包里只放壳 + 内核，游戏数据由
使用者自备（`vendor/README.md` 有落位步骤与 SHA-256 校验；缺数据时程序会打印一行说明
并**跳过**依赖数据的自检，不会崩）。**本仓库的 `make_dist.py` 目前只做"含数据"这一版** ——
出公开变体时至少要改三处：`build_tree()` 里跳过 `inputs/`、`verify_bundle()` 的必带清单、
以及包内 README 的数据来源段。

这条口径同时写在**包内 README**（`packaging/README.app.md` 的「许可与分发边界」）、
**包内使用说明**（`packaging/使用说明.txt`）和**启动窗口**（`启动.bat` 的启动横幅）里 ——
三处都写，是因为收件人可能只看其中一处；**许可正文**则随包放在 `app/LICENSE`。

## 一条命令

```powershell
python make_dist.py --prepare    # 一次性：下载内嵌 Python + 装依赖（约 90 MB，需联网）
python make_dist.py              # 组装 + 裁剪 + 冒烟测试 → dist/导弹包线图/
python make_dist.py --zip        # 顺便打成 zip
```

`--prepare` 的产物落在 `build/`（已 gitignore），之后组装不再联网。
组装脚本会**自己跑一次冒烟测试**：用分发包自己的解释器出 png/pdf/svg 三种格式，
任何一处裁错、路径写错、字体缺失都会当场炸掉，不会等对方双击才发现。

内嵌 Python 的三个镜像（按顺序试，第一个下得动的就用；2026-10-02 实测**三个都通**）：

| 镜像 | 实测 |
| --- | --- |
| `mirrors.huaweicloud.com` | HTTP 206 · 0.45 s（12,673,227 B 全量大小） |
| `registry.npmmirror.com` | HTTP 206 · 0.51 s |
| `www.python.org` | HTTP 206 · 0.28 s |

装依赖走 `mirrors.aliyun.com/pypi/simple/`（实测 200 · 0.13 s）。三个都下不动时，
脚本会打印每个镜像的**错误原文**并退出，提示手动把 `python-3.14.7-embed-amd64.zip`
放到 `build/py-embed.zip` 再重跑 —— 这条路不需要联网，也不要求文件名与官方一致。

## 产物结构

根目录**只有一个文件**，其余都在二级目录 `app/` 里：

```text
dist/导弹包线图/
├── 启动.bat                    ← 对方只需要双击这个
└── app/
    ├── run_ui.py               启动逻辑（重定向内核缓存 → 注册中文字体 → **真跑一次最小工况报 backend** → 起 WebUI）
    ├── python/                 内嵌 Python 3.14.7 + numpy/matplotlib，不碰系统环境
    ├── src/missile_sim/        外壳代码（含 `webui_static/`：index / app / viewer3d / fig3 / sandbox 五套前端）
    ├── vendor/wt-missile/      求解器内核 + **游戏数据 `inputs/`**（离线解算的前提；许可见上）
    ├── kernel-cache/           预编译 C 内核（对方没装 MSVC 也能吃 compiled-c）
    ├── fonts/                  中文字体子集（对方是英文系统也不出方块）
    ├── tests/                  自检脚本（项数**别手抄**：下面「包内自检」那节有 `python make_dist.py --sync-docs` 生成的计数块）
    ├── configs/                `web_default.json` + `presets.json`（**共享环境预设层，少它首页 500**）
    ├── figures/ results/       图1/图2 各两套（default + static，各三格式，共 12 件）；沙盒与图3 的**只读产物**
    ├── docs/SOLVER-API.md      换内核唯一要读的
    ├── docs/BETA-GAMMA.md      β–γ 图的定义、推导与黄金值
    ├── README.md               面向**收件人**，模板在 packaging/README.app.md
    ├── LICENSE                 **许可正文**（AGPL-3.0-only 官方全文，逐字），由根目录 `LICENSE` 复制
    └── 使用说明.txt             极简引导，模板在 packaging/使用说明.txt
```

⚠ **不要把仓库的 `README.md` 拷进包。** 它面向开发者，引用了 `NOTES.md`、
`docs/RESTART-PLAN.md`、`docs/DISTRIBUTION.md`、`make_dist.py` 这些**包里根本没有**的东西，
收件人按图索骥只会扑空。分发包的说明单独维护在 `packaging/`，组装时写进去；
`README.app.md` 里**带图**（相对路径指向 `figures/`），对方打开就能看见成果长什么样。

`docs/` 只带两份：`SOLVER-API.md`（换内核的契约）与 `BETA-GAMMA.md`（β/γ 是什么）。
后者引用的 `tests/`、`src/` 包里都有，对方能顺着查；其余 `docs/*.md` 是开发过程记录，
引用的东西包里没有，不带。

实测体积（**2026-10-04 v8：纵轴换成 `ginv = 1/γ` 之后重测**，Python 3.14.7 / numpy 2.5.3 / matplotlib 3.11.2）：

| 项 | 大小 |
| --- | --- |
| `app/python/`（解释器 + 依赖，已裁 `tests`） | 117.2 MB |
| `app/vendor/`（内核 + inputs/：**170 个文件** = 168 份 `.blk` + 2 份 `.json`；zip 里连 3 条目录条目共 **173 条**） | 3.2 MB |
| `app/fonts/`（思源黑体子集，7036 字） | 3.6 MB |
| `app/figures/`（**12 个**：图1/图2 各 default+static 两套，各三格式；**静态 3D 预览那 3 件已删**） | 3.9 MB |
| `app/results/`（**21 个**：四套 default 产物 + 3 份 static + 沙盒 4 份 + 图3 的 11 点与立方体 + 权威表 + `bg_ref_curves.json`） | 1.5 MB |
| `app/tests/` | 0.5 MB |
| **解压后合计**（2311 个文件） | **131.3 MB** |
| **zip** | **53.6 MB**（精确字节数与 sha256 每次重打都会变 —— 变的是**条目时间戳**，内容逐条 CRC 不变 ⇒ 看「验证记录」当前那一节，或 `python make_dist.py --zip` 自己打印的两行） |

## 打包清单怎么定的（逐项，2026-10-02 审计）

页码都在 `make_dist.py` 顶部；改动这一节之前先跑一次 `python make_dist.py`（它自带
`verify_bundle()`，清单里少一条必带文件就当场中止）。

| 项 | 带/不带 | 理由（少它的后果） |
| --- | --- | --- |
| `configs/presets.json` | **带** | 共享环境预设层（`presets.ENV_PRESET_PATH`）。**旧清单漏了它 ⇒ `GET /` 直接 500**（`presets.resolve()` → `FileNotFoundError`）；首屏就崩 |
| `configs/web_default.json` | 带 | `webui.CONFIG_PATH`（host/port/jobs/formats/tag…） |
| `configs/` 其余文件 | 自动带 | 整目录拷 + `CONFIGS_DENY` 挡私货名（`*.local.json` / `secrets*` / `*token*` / `*.key` / `*.pfx`） |
| `src/missile_sim/**`（含 `webui_static/`） | 带 | 壳 + 五套前端。`/`、`/fig4`（沙盒，旧 `/sandbox` 302 跳过来）、`/fig3`、`/viewer3d` 与 `/static/*` 全指着它 |
| `vendor/wt-missile/**`（含 `inputs/`） | **带** | 内核源码 + 168 份 blk。**不带 = 离线根本算不了**（这也是本包不可公开分发的原因） |
| `%LOCALAPPDATA%\wt-missile\compiled-fast\*.dll` | 带 | 对方没装 MSVC 也能 `compiled-c`（快 20 倍）。`verify_bundle()` 会核对 dll 指纹与随包内核是否对得上 |
| `figures/` | 图1/图2 各 default+static 两套（各三格式，共 12 个）；**图3/图4 没有静态成品，输入阶段的 3D 预览已于 2026-10-03 删除** | 对方打开就能看成品（页面上的图是跑出来才有的，不靠这几张） |
| `figures/fig_*_static.png`（6 个 static） | **带** | v6 的"无输入静态形态"：`index.html` 里 `<img src="/figures/fig_isotime_plane_static.png">` 直接指它们（缺 ⇒ 首页两块裂图） |
| `results/plane_static.json`、`bg_static.json` | **带** | ⚠ **包内自检会读这两份**（`test_sandbox.py::test_static_forms_come_from_offline_products_without_scanning` 按 `Path(__file__).parent.parent/"results"` 找）。**2026-10-03 实测：REQUIRED_IN_BUNDLE 里有、`RESULTS_KEEP` 里没有 ⇒ `verify_bundle()` 在组装期硬失败**（正是这条机制该干的事）；补上后 468 项全绿 |
| `results/bg_static_points.csv` | 带 | 代码不读它；与 `bg_default_points.csv` 同族（静态形态的点表），一起带免得下次有人问"为什么少一张表" |
| `results/plane_default*`、`bg_default*`、`compare_default.csv` | 带 | 首页摘要、图1/图2 的 manifest 与逐型表（`with_iso=True` / `with_scan=True` 的动态形态） |
| `results/traj_default_{missile,target,segments}.csv` + `traj_default.json` | **带** | `/fig4`、`/api/sandbox/<key>`、`/viewer3d` **只读**这四份（不带 ⇒ 页面 404 "没有产物"） |
| `results/fig3_default.json` + `fig3_default_cases.csv` | **带** | `/fig3`、`/api/fig3/<tag>` 的 11 个点 |
| `results/fig3_cube_*.json` | **带（glob）** | 文件名带**指纹**（`cube_key()` 含求解器 sha），所以按 glob 带。**少它 ⇒ `/api/fig3/<tag>/layers` 从"200 秒开"退化成"202 + 现扫几百工况"** |
| `results/missile_standards.json` | 带 | 11 型权威表（文档/对比用，也是 `-k pool_mapping` 黄金值的出处） |
| `results/bg_ref_curves.json` | **带** | ⚠ **包内自检会读它**（`tests/test_bg_reference_curves.py` 的 fixture 直接 `assert REF.is_file()`；`src/` 不读）。**2026-10-04 实测：判据随 task-28 进来了、`RESULTS_KEEP` 里没加 ⇒ 包内 7 项红**（"缺少入库快照"）—— 与 `plane_static.json` 是**同一个坑**：只有测试读的产物最容易漏，而组装期没人拦 |
| `results/` 其余历史产物（`pro_cache.json`、`native_compare*`、`cases_*.csv`…） | 不带 | 旧架构遗留，外壳不读 |
| `docs/` 只带 `SOLVER-API.md` + `BETA-GAMMA.md` | 带 | 后者引用的 `tests/`、`src/` 包里都有；其余 `docs/*` 是开发过程记录，引用的东西包里没有 |
| `tests/**` | 带（**排除 2 个 spike 模块**） | 让对方能自己验证这一包。`test_fig3d_spike.py` / `test_bg3d_spike.py` 的判据要读 `spikes/**` 的产物，而 `spikes/` 不随包 ⇒ 留着它们会让自检冒出 27 条红字（与"包好不好"无关）。项数见下面「清单一致性怎么保证的」那一节（**程序数出来的，不是手抄的**） |
| `spikes/`、`archive/`、`.tmp_test/`、`make_dist.py`、`.git`、`NOTES.md` | 不带 | 探究记录 / 历史图 / 开发脚本，会让人按图索骥扑空 |
| `packaging/README.app.md` → `app/README.md` | 带 | 面向收件人（**表头就是许可边界**）；仓库 README 面向开发者，不能照抄 |

## 清单一致性怎么保证的（2026-10-03 补的两条判据）

两条判据都是**列表级**的（跑得飞快、不组装、不联网），由 `make_dist.py --check`
（组装前也会自动跑一遍）与 `tests/test_dist_manifest.py`（`-k dist_manifest`）执行：

1. **必带项必须有产出规则**：`REQUIRED_IN_BUNDLE` 的每一条，都要能由某条拷贝/生成规则解释
   （`RESULTS_KEEP` / `RESULTS_GLOBS` / `FIGURES_KEEP` / `CONFIGS_DENY` / `DOCS_KEEP` /
   `TESTS_EXCLUDE` / `copy_tree` 的前缀 …）。**这正是 v6 咬到的那条**：必带清单加了两份
   `results/*.json`、拷贝清单忘了同步，旧脚本只在**组装期**（文件已经不在包里）才炸 ——
   CI 与包内自检都看不见。现在组装**之前**就中止，并指名是哪一条。
2. **KEEP 清单里的文件必须真的在仓库里**：`build_tree()` 是 `if s.exists()` 才拷，
   KEEP 里写错一个名字或产物被删了会**静默少拷**，只有翻 zip 才看得出来；`RESULTS_GLOBS`
   还要保证至少命中一个文件（少了它 `/api/fig3/<tag>/layers` 会从"200 秒开"退化成"现扫几百工况"）。

配套：`tests/test_dist_manifest.py` 里有一条**反向判据**（故意往必带清单里塞一个不存在于 KEEP
的条目，断言它被点名），免得这两条变成永远为真的橡皮图章。

### 自检项数（程序生成，别手改）

<!-- SELFTEST-COUNTS:BEGIN（`python make_dist.py --sync-docs` 生成，别手改）-->
自检项数（由程序数出，别手抄）：仓库全量 **570** 项 − `TESTS_EXCLUDE` 排掉的 **46** 项（`test_fig3d_spike.py`、`test_bg3d_spike.py`，判据要读不随包的 `spikes/**`）= 包内 **524** 项；包内这 6 项要读组装脚本 `make_dist.py`（不随包）⇒ 记 **SKIP**（跳过≠通过）：`test_dist_manifest.py`；另有前端行为探针要 `node`（包里不随 node）⇒ 没装 node 的机器上 `test_webui_layout.py` 里那几项也记 **SKIP**（同模块其余 Python 侧契约判据照跑）；再有 **2** 条判据要判 `figures/` 的 **git 跟踪状态**（分发包里没有版本库 ⇒ 必然 **SKIP**；把包解压进**别的** git 工作树的子目录时同样记 SKIP、不算失败）。**包内实跑应为 516 通过 / 0 失败 / 8 跳过**（共 524 项；跳过 ≠ 通过；装了 `node` 的机器上如此）
<!-- SELFTEST-COUNTS:END -->

上面这行由 `make_dist.py --sync-docs` 从 `tests/run_tests.py -l` 的输出算出来
（**同一处推导**：排掉哪两个模块、因此少几项，都由 `TESTS_EXCLUDE` 决定）；
`verify_bundle()` 与 `-k dist_manifest` 都会核对它与算出来的一致，不一致就中止组装。

## 三个设计要点（都是被坑出来的）

**1. 目录形状不能改。** `src/missile_sim/spec.py` 用 `Path(__file__).resolve().parents[2]`
推仓库根 —— 只要 `app/` 下保持 `src/ vendor/ figures/ results/` 的相对结构，
所有路径自动正确，业务代码一行都不用动。这也是为什么不能把 `src/` 拍平。

**2. 内核缓存靠改 `LOCALAPPDATA` 重定向。** `wt_missile` 在
`%LOCALAPPDATA%\wt-missile\compiled-fast\<hash>.dll` 找编译产物，而且**只认这一个
环境变量**（源码里写死的）。`run_ui.py` 在 import 之前把它指到包内 `kernel-cache/`，
本机编译的内核就随包走。ABI 对得上：本机 MSVC 19.44，内嵌 Python 也是 `MSC v.1944`，
且 embeddable 自带 `vcruntime140.dll`。

⚠ 必须**在 `import missile_sim` 之前**设置 —— 一旦 `wt_missile` 被导入，它已经按默认
路径找过一遍并缓存了失败结果。

**3. 中文字体必须随包。** 对方若是英文 Windows，`Microsoft YaHei` / `SimHei` / `SimSun`
一个都没有，图上全是豆腐块。包里带思源黑体 `NotoSansSC-VF.ttf` 的子集
（GB2312 一二级汉字 + 希腊字母 + 常用符号，7036 字），17 MB → 3.6 MB。
字体是 **SIL OFL 1.1**，可以再分发；`run_ui.py` 用 `font_manager.addfont()` 注册后
插到 `figures._CN_FONTS` 最前面，注册失败不致命（退回系统字体并打警告）。

## 裁剪：哪些能删，哪些绝对不能

`prune_bundle()` 只删两样：numpy / matplotlib 自带的 `tests/` 目录，和 pip 留下的
`bin/` 脚本 —— 合计约 20 MB。

⚠ **`PIL` 和 `fontTools` 看着像可选依赖，其实是 matplotlib 的硬依赖**，实测删掉当场报废：

* `matplotlib/colors.py` 第 53 行 `from PIL import Image`
* `matplotlib/dviread.py` 第 32 行 `import fontTools.agl`

两者合计 32 MB，删不得。其余大头也都有硬依赖：`numpy.libs/`（20 MB OpenBLAS）是
numpy 的 C 扩展链接的，`matplotlib/mpl-data/fonts/`（7 MB）含 mathtext 要用的
DejaVu 系列。**想再瘦身必须先跑冒烟测试，别凭感觉删。**

## 附带的三个坑

* **只读属性**：`results/reference_fig.png` 是从 `E:\WT` 那边拷来的，带只读位，
  裸 `shutil.rmtree()` 在 Windows 上直接 `WinError 5` 把组装打断在半路。
  脚本里用 `rmtree_force()`（`onexc` 回调先 `chmod S_IWRITE` 再删）。
  但**占用**（`WinError 32`）跟只读是两回事，`chmod` 救不了 —— 那说明还有 `python.exe`
  活着（实测：上一轮测 UI 留下的服务进程把 `dist/` 锁住），所以这种情况**直接抛**，
  不要静默跳过，否则失败会推迟到后面 `copytree` 里以更难懂的方式再炸一次。
* **参数转发**：`启动.bat` 里的 `%*` 要真能传到 `webui.main()`。第一版 `run_ui.py`
  把 argv 写死成 `["--config", ..., "--browser"]`，`--port` 之类全被吞掉。
  现在转发 `sys.argv[1:]`，只在没显式给 `--no-browser` 时补 `--browser`。
* **包内文档要与仓库文档分开维护**：见上面目录树下的警告 —— 仓库 README 是写给开发者的，
  照抄进包只会让收件人找不到北。

## 对方机器上的预期

* **能跑**：Windows x64。内嵌解释器与 `python.exe` 都是 amd64。
* **速度**：吃上随包内核时，图1 全尺寸扫描（1632 工况）约 40 s、图2（1032 工况）约 20 s；
  内核加载失败会自动退回纯 Python，**结果完全相同，约 5 分钟 / 2.5 分钟**。
  界面上有进度条。
* **不联网也能用**：除首次 pip 装依赖（只在打包机上进行）外，运行时零网络请求。
* **只听 `127.0.0.1`**，无鉴权，适合本机自用与内网演示。

## 验证记录

> ⚠ **本节全是"某一次组装"的历史样张**（按日期倒序：v8 → v7 → v6 → 更早）。
> 里面的**判断项数、必带项条数、包内自检的"通过/跳过"数字**都会随判据增减而变，
> 而且它们在**当时那一版**上是对的、**不代表现在**：例如 v7 样张里写着"仓库全量 507 项 /
> 必带项 35 条 / 包内 461 项"，与今天的数字早就不同。
> **当前数字只认下面这两处的生成块**（`python make_dist.py --sync-docs` 从程序里数出来的）：
> 「包内自检」那节的 `SELFTEST-COUNTS` 块，以及 `packaging/README.app.md` 里同名的块。
> 读样张时请把它当**当时的取证记录**看（进程/端口/字节数/耗时那些仍然是那一次的真实测量），
> 不要拿它去核对今天的清单。

### 2026-10-04：v8 形态（纵轴 γ → `ginv = 1/γ` 之后）的隔离验证 —— **当前交付的那一版**

形态变化（相对 v7）：**图2 / 图3 的纵轴从物理 γ 换成它的倒数 `ginv = 1/γ [m²/kg]`**（用户
2026-10-04 口径，含义是"向上＝更好"）。两根轴于是都朝上变大，图2 上原本是**双曲线**的等 `n*` 线
变成**过原点的直线**；γ 仍是内核口径，公式一个字没改，只影响画法与读数。
`CACHE_SCHEMA 5 → 6`（纵轴语义变了，旧缓存必须作废）；CLI `--gamma-step` 改名 `--ginv-step`
（`dest=ginv_step`）、WebUI 表单字段 `ginv_step`（标签"ginv 网格步长"、单位 `m²/kg`、
提示"图2 扫描用（默认 0.0004）"），网格键 `gamma/gamma_step` → `ginv/ginv_step`；图2 / 图3
的成品与随包立方体**已按新轴重生成**（`results/fig3_cube_PL-12_e0f46009.json`，立方体内的
`grid` 键是 `beta/beta_step/dv/dv_step/ginv/ginv_step`）。

同轮的前置清理（`dist8` 上前两个提交）：

* `results/` 里**只留当前 `fig3.cube_key()` 命中的那一份**立方体，旧指纹那份
  `git rm results/fig3_cube_PL-12_1989434c.json` —— 它再也不可能被 `cube_key()` 命中，而
  `make_dist.py` 按 `RESULTS_GLOBS = ["fig3_cube_*.json"]` **用 glob 装包**，留着就会被一起打进去。
* 两条**有牙**判据：立方体指纹判据（`tests/test_fig3.py`，包内也跑）+ 反向演练
  （`tests/test_dist_manifest.py`：往必带清单里塞一条不存在于 KEEP 的路径，判据必须翻红 ——
  它要读不随包的 `make_dist.py`，所以只在仓库里跑、包内记 SKIP）。
* `verify_bundle()` 在**当前指纹那份立方体缺失**时走**产品入口**
  （`python -m missile_sim --figure fig3 --fig3-cube PL-12`）自动补一份，补不出来就把确切命令
  打出来并 `exit≠0`。**判据里不另写一份缓存逻辑** —— 那样它会与内核指纹脱钩，而"脱钩了也照样出包"。
  缺/旧都在 `--check` 上翻红；**旧指纹那份不会自动删**（删除是要人拍板的事）。

做法与口径跟 v7 那一节一致：解到 `%TEMP%\导弹包线图 v8 release 测试 20261004\`（路径带空格与中文）、
系统 `python` 从 PATH 排除、包内解释器当 HTTP 客户端（脚本 `.tmp_test\run_isolated_v8.ps1` +
`probe_v8.py`，清单核对 `verify_required_v8.py`，秘密扫描 `scan_secrets.py`）。

```text
zip  ：E:\导弹包线图-dist\dist\导弹包线图.zip  **56,249,197 B（53.6 MB）**
       sha256 = **5c23189859ca90a3a26b0cf409bb889c3de248000c8d41d350e514dabda31640**
       （这两行由 `python make_dist.py --zip` **自己打印**，不是手抄；zip 条目 **2540 条**
        = 229 条目录条目 + 2311 个文件条目）
  ⚠ 本轮先后打过三份：`56234901 B / c2c2755…`（之后把 `results/bg_ref_curves.json` 补进 KEEP
      清单、修了一处前端轴注记位数）、`56249168 B / a583ac4…`（之后把本文档与包内 README 里
      "冷跑约 3.5 分钟"改成实测的 307 s / 124 s）—— **那两份都作废**，别拿去核对。
      v7 的 `56,097,067 B / 25432a76…` 以及更早的 v6/v5 全部作废。
  ⚠ **这个 zip 不是逐字节可复现的**（同 v7）：条目清单与每条 CRC 相同，但条目时间戳是重打时刻。
      要"内容级"校验请用 `python make_dist.py --check`（本轮退出 0）。
解压 ：**3.7 s**（python `zipfile`；见下面"本轮踩到的验证缺口"为什么不用 `tar`），
       解包后 **2311 个文件 / 131.3 MB**；`figures\` **12 件**、`results\` **21 件**
       （其中图3 立方体**恰好 1 份**）、`inputs\` 170 个文件、`tests\` 34 个文件、
       `webui_static\` 12 件；根目录只有 `启动.bat`；
       **预览/旧成品残留 0 件、Edge 用户配置残留 0 件**
       （解压后**立刻**拿 zip 的条目名集合与盘上文件逐条比对：缺 0、多 0）
首屏 ：**13.87 s / 15.07 s / 17.90 s**（三次**冷**启：探针、重打后复验、干净件复验 ——
       包里 117 MB 的 `python\` 是刚解出来的，第一次读要落盘）
       **热启 2.84 s**（同一份解压件、文件已在系统缓存里）⇒ 与 v7 记的 2.94~3.37 s **同一量级**，
       十几秒那一档是**冷读盘**，不是产品变慢；机器上压着浏览器/守护进程时两者都会再慢一截。
探针 ：**35 项 / 失败 0 项**（`probe_v8.py`；比 v7 多的那一条见下）
  /healthz 200 · / 200（19,549 B：四个锚点都在、`id="fig4" hidden` 在、两张 static 图被引用、
      页面里没有 `fig_traj_preview` / `traj_preview` 残留）
  /fig3 200 · /fig4 200 · /viewer3d 200 · `/sandbox` → **302 Location=/fig4**
  **v8 表单口径**：`data-field="ginv_step"`、标签"ginv 网格步长"、单位 `m²/kg`、
      提示 `title="图2 扫描用（默认 0.0004）"` 都在；旧口径 `gamma_step` / "gamma 网格步长"
      **一处都不许出现**（实测 0 处）
  **页面引用到的 10 个静态资源逐条 200**（含 `app.js` / `fig3.js` / `fig3.css`）—— 这是本轮新加的
      判据，专治"包里少了一件 JS 而探针只打点名的几条"（见"本轮踩到的验证缺口"）
  **删掉的成品在包里也确实没有**：`/figures/fig_traj_preview_default.{png,pdf,svg}` **3 条全 404**、
      `fig_traj_default.png` 404；而 figures/ 那 **12 件逐条 200**
  边界：`/static/sandbox.html` → **404**（白名单 fail-closed）；`/api/sandbox/default` → **400**
  随包立方体：`/results/fig3_cube_PL-12_e0f46009.json` → 200、**135,839 B**、`schema=1`、`tier=fast`、
      `grid` 键含 `ginv` / `ginv_step`（不是 `gamma`）
  图3：`/api/fig3/default` → 11 点；`/api/fig3/default/layers?missile=PL-12` → 200 + **10 层 / 0.31 s**
      （退化路径要现扫几百工况 ≈200 s），**跑完 cube 集合没变** ⇒ 真的吃的是随包立方体，没退化
  解算：`POST /api/single` → 200，t_hit = **45.186109475831095**、backend = **compiled-c**（与仓库金标一致）
  一次提交出四块（`figure=four`）：四块全 done，**冷跑 50.40 s**
      （fig4 @1.20 s → fig1 @27.93 s → fig2 @46.27 s → fig3 @50.11 s；v7 同口径 50.55 s / 52.53 s）
      另两次 74.52 s / 75.90 s 是**机器上压着浏览器与守护进程**时跑的，同一份代码；
      60 s 那一档才可比较
  裁决 1：图4 块 **@1.52 s** 就绪时 `/api/sandbox/<job>` 已是真回放 —— 200、**203,468 B**、
      events = 8，而**当时整任务 state 还是 running**
  裁决 2：图3 块就绪 **@50.40 s** 时 `/api/fig3/<job>/layers?missile=PL-12` → 200、10 层
  `/fig4?job=<id>` 200；产出图能下：`fig_isotime_plane_v8probe.png` 679,551 B、
      `fig_bg_plane_v8probe.png` 796,172 B；`result.parts` 四块齐（traj / plane / bg / fig3）
包内自检（`app\python\python.exe app\tests\run_tests.py`，LOCALAPPDATA 指向包内 kernel-cache）：
  **通过 473 / 失败 0 / 跳过 5 / 共 478，冷跑 307.3 s**（同一台机器上热跑一次 123.6 s；
  跳过的是"分发包清单判据"5 项，要读不随包的 `make_dist.py`）。
  ⚠ v7 记的 457 / 0 / 4 / 461 里"跳过 4"在 v8 变成 **5**，且 v7 的 461 ≠ v8 的 478 ——
  差的 17 项是这轮前后加进来的判据（`test_bg_reference_curves.py` 7 项 +
  `tests/test_fig3.py` 的立方体指纹判据等）；v7 那次**没有** `bg_ref_curves.json` 判据，
  所以它的"0 失败"不能拿来说明"这份也没有"。
  包内 `tests\test_fig3.py` 的立方体判据**真跑**（它只读 `results/`，不读组装脚本）；
  `tests\test_dist_manifest.py` 的 5 项要读 `make_dist.py`、`test_webui_layout.py` 的 4 项前端
  行为探针要 `node`，缺谁就把那几项记 SKIP（本机有 node，那 4 项**真跑了**）。
清单/文档一致性（`python make_dist.py --check`，纯列表级，**退出 0**）：必带项 **36 条全部有产出规则**、
  KEEP 清单逐条在位、`tests/` 34 个文件（排除 2 个 spike 模块）、
  自检项数同一处推导（仓库 524 − 排除 46 = 包内 478，其中 5 项包内记 SKIP）。
必带文件：`REQUIRED_IN_BUNDLE` **36 条逐项核对，缺 0 条**（对着**没跑过**的解压件验，
  不是源树；脚本 `verify_required_v8.py` 逐条打印序号与字节数）。
立方体：`results/fig3_cube_*.json` glob **恰好命中 1 份**，且文件名指纹 == 现算的
  `fig3.cube_key()`（`e0f46009`）；`fig3_cube_problems()` 返回空。
秘密扫描（对着**没跑过**的解压件，2311 个文件、1203 个文本文件）：
  文件名命中 **1**（`app/python/Lib/site-packages/packaging/_tokenizer.py` —— 上游 `packaging`
  库自己的文件名里带 `token`）；内容命中 **44** = **43 条上游许可/作者邮箱**
  （numpy / Pillow / libdivide / packaging）+ **1 条上游自带构建机路径**
  （`numpy/__config__.py:96` 的 `C:\Users\runneradmin\…`）；
  **本项目自己的文件（`src/` `tests/` `configs/` `results/` `figures/` `docs/` `README.md`
  `使用说明.txt`）命中 0 条**。
真双击（`Start-Process 启动.bat`，ShellExecute 语义 + 让它**真开浏览器**）：
  cmd PID 起得来、**4.33 s** 首页可用、**自动开出了一个真浏览器窗口**（2 个新 msedge 进程，
  最早在双击后 **0.04 s**；窗口标题实测 `导弹 (ΔV, BC) 包线图 · 本机表单 …`）；
  收尾后端口 8765 不再监听、残留 python 0 个。
```

**图2 纵轴取证**（这一轮的产品变化就在这一处，所以单独留证）：

* 真浏览器打的是**最终 zip 解出来的那份** `figures/fig_bg_plane_default.png`
  （sha256 `eb41f20a43c27f4ea5105be61e6058438409d2b6671768331667913046ae216a`，
  3543×3063），纵轴标签读作 **`ginv = 1/γ　[m²/kg]　转向能力 →（越大越好）`**，
  刻度是 **4 位小数**（`0.0175` / `0.0150` / `0.0125`）；等 `n*` 线（14~20 G，7 条）是
  **过原点的直线**。
* 证据文件（都在 `.tmp_test\evidence_v8\`）：`fig2_axis_browser_final_clean.png`
  （浏览器截图，300,200 B）、`fig2_yaxis_label.png`（从包内 PNG 裁的标签条）、
  `fig2_yaxis_ticks.png`（刻度条）、`fig3_axis_note_browser.txt`（图3 轴注记的浏览器读数）。
* 包内**手写**页面（`src/missile_sim/webui_static/index.html` + `webui._field_html()`）里的表单：
  `data-field="ginv_step"`、标签 **`ginv 网格步长`**、单位 **`m²/kg`**、提示
  **`图2 扫描用（默认 0.0004）`**、默认值 **0.0004 m²/kg**；图3 侧另有
  `fig3_ginv_n`（"ginv 轴点数（个）"，默认 7）。

**本轮踩到的验证缺口（已修，记在这里免得下轮再踩）**：v8 第二次解压用了 `tar -xf` 一把过，
它**返回 0**、文件"数"也对得上 —— 但上一轮失败的 `Remove-Item -Recurse` 还在同一个目录上
边解边删，活下来的是个**半残的包**：`/static/app.js`、`/static/fig3.js`、`/static/fig3.css`
三件不见了（`app/python/Lib/site-packages` 里也短了一大片）。那一轮探针 **34/34 全绿**，
因为它只打了我点名的 `app.css` / `sandbox.js` / `viewer3d.js`；页面上 JS 根本加载不了，
而浏览器那一次之所以看着正常，是 **Edge 缓存**里还有旧 JS。三处一起修：

1. 解压改成 python `zipfile`，**解完立刻拿 zip 的条目名集合与盘上文件逐条比对**
   （`extract_and_check.py`：缺一条或多一条都算失败、退出码非 0，并且**事后还能 `--check-only` 复核**）；
2. 探针加"**页面里引用到的每一个 `/static` `/figures` `/results` 资源都要 200**"（本轮 10 条）；
3. 上一条把 `app.js` / `fig3.js` / `fig3.css` 纳进了判据 —— 同样的坑再出现会当场翻红。

同族的一个**清理**坑（本轮踩了两次，都是 `WinError 32`）：`启动.bat` 里的 `cd /d "%~dp0"`
会让那个 `cmd.exe` 的**工作目录**就是包根，于是**只杀"端口占用者"不够** —— 它的父 `cmd` 还活着、
目录照样删不掉（Restart Manager 也看不见**工作目录**这种句柄，会报"空闲"，别信它）。
正确做法：把起服务时的 `cmd` PID 记下来（`v8_live.json` 里就有），收尾时按那个 PID `taskkill /T /F`。

**前端轴注记位数（本轮修的真缺陷）**：`fig3.js` 原来按 `Math.abs(hi-lo) < 100 ? 1 : 0` 取位数，
换到 `ginv` 量级（0.0101~0.0196）后退化成 **`0.0~0.0`**（图3 纵轴注记）。现在按轴取位数
（`axisDigits()`：`ginv` 4 位、`beta`/`dv` 0 位），浏览器实测该行读作
**`ginv = 1/γ [m²/kg] 转向能力 →（越大越好） 0.0101~0.0196`**。

### 2026-10-03：v7 形态（task-27 之后）的隔离验证 —— **已被 v8 取代（历史留证，指纹作废）**

形态变化（相对 v6，**净删除 + 前端标记**）：**输入阶段的静态 3D 预览整条线删掉** ——
`figures.plot_traj_preview_3d`、`workflow.TrajRequest.preview` 与它的快捷键、CLI `--traj-preview`、
WebUI 的 `traj_preview` 字段、results/响应里的 `preview` 全部下线，`figures/` 由 15 件降为
**12 件**（`git rm figures/fig_traj_preview_default.{png,pdf,svg}`）；三维只保留**交互页**
`/fig3`、`/fig4`、`/viewer3d`。沙盒页（`/fig4`）新增**双方实时位置点**：导弹 = 9 px 实心点、
敌机 = 12 px 点 + 名字标签（名字取响应的 `d.entities.target.name`），颜色都来自响应；
两个文字标签的偏移**从 CSS 搬到 JS**（`sandbox.js` 的 `LABEL_OFF` + `placeLabel()` 夹边），
因为在 t=8 s 那一帧 CSS 的 `transform` 夹不住边界，读数胶囊 `R=41.4km` 会被画布右边缘切掉。

做法与口径跟下一节完全一致：解到 `%TEMP%\导弹包线图 v7 release 测试 20261003\`（路径带空格与中文）、
系统 `python` 从 PATH 排除、包内解释器当 HTTP 客户端
（脚本 `.tmp_test/run_isolated_v7.ps1` + `probe_v7.py`；核对脚本 `verify_bundle_v7.ps1`）。

```text
zip  ：E:\导弹包线图-dist\dist\导弹包线图.zip  **56,097,067 B（53.5 MB）**
       sha256 = **25432a762674cf09da47b72ca29473a1924c8a31b0e89d06918b9f11429eed0a**
       ⚠ **这一版已被 v8 取代**（当前是 `v8` 那一节：`56,249,197 B / 5c231898…`）——
       下面这两行与本节所有数字**只作历史留证，别再拿去核对**。
       （这两行由 `python make_dist.py --zip` **自己打印**，不是手抄；zip 条目 **2537 条**
        = 229 条目录条目 + 2308 个文件条目）
       比 v6 小 346,781 B —— 这一轮是净删除（3 张成品图 + 预览那条线的代码与判据）。
       同一份源码先前打过一次 56,097,064 B / `24a17e01…`，之后又把两处**收件人文档**
       （`packaging/README.app.md`、`packaging/使用说明.txt`）的文字改准，只有 +3 字节 ⇒
       那次也算作废。上一版 56,443,848 B / `a78ff31b…`、更早的 56,440,832 B / `5e53d0ae…`、
       56,435,656 B / `7207bf4b…` **全部作废**，别拿去核对
       ⚠ **这个 zip 不是逐字节可复现的**：同一份源码重打一次，字节数一样（56,097,067 B）、
       条目清单 2537 条全同、**每条 CRC 与大小 0 条不同**，但 **349 条条目的时间戳**变成重打时刻
       ⇒ sha256 变成 `94336d17…`（实测）。所以上面那两行是**那一次构建**的指纹，不是内容的校验值；
       要"内容级"校验请用 `python make_dist.py --check`，或比 `app/` 里各文件的哈希。
       （想让它逐字节可复现，得在写 zip 时把 `ZipInfo.date_time` 钉死 —— 属于后续打磨项，本轮没动组装脚本。）
       交付物以**恢复回来的这一份**为准（`25432a76…`，就是这个指纹）。
解压 ：17.5 s / 23.4 s（两次从零解压；解包后 **2308 个文件 / 131.0 MB**，
       inputs\ 170 个文件（+3 条目录条目 = zip 里 173 条）；根目录只有 启动.bat；
       **预览/旧成品残留 0 件、Edge 用户配置残留 0 件**）
首屏 ：**2.94 s / 3.30 s / 3.32 s / 3.37 s**（探针、真双击、记录器双击、组装期核对各一次；
       v6 基线 2.93 s，同一量级）
探针 ：**31 项 / 失败 0 项**（`probe_v7.py`）
  /healthz 200 · / 200（19,533 B：四个锚点都在、`id="fig4" hidden` 在、两张 static 图被引用、
      页面里**没有** `fig_traj_preview` / `traj_preview` / `v3dnote` 任何一处残留）
  /fig3 200 · /fig4 200 · /viewer3d 200 · `/sandbox` → **302 Location=/fig4**
  **删掉的成品在包里也确实没有**：`/figures/fig_traj_preview_default.{png,pdf,svg}` **3 条全 404**、
      `fig_traj_default.png` 404（v7 关键点）；而 figures/ 那 **12 件逐条 200**
  边界：`/static/sandbox.html` → **404**（白名单 fail-closed）；`/api/sandbox/default` → **400**（回放后门已删）
  包内 `sandbox.js`（39,588 B）两个实时点 + JS 夹边全在：`sbDotMissile` / `sbDotTarget` /
      `sbTargetLabel` / `sbReadout` / `LABEL_OFF` / `placeLabel` / `d.entities.target.name`
  图3：`/api/fig3/default` → 11 点；`/api/fig3/default/layers?missile=PL-12` → 200 + 10 层（吃随包立方体）
  解算：`POST /api/single` → 200，t_hit = 45.186109475831095、backend = **compiled-c**（与仓库金标一致）
  一次提交出四块（`figure=four`）：四块全 done，**冷跑 50.55 s / 52.53 s**
      （核对脚本那次：fig4 @1.16 s → fig1 @27.91 s → fig2 @46.61 s → fig3 @50.55 s；
       探针那次：fig4 @1.17 s → fig1 @29.77 s → fig2 @49.30 s → fig3 @52.28 s；v6 同一口径 48.82 s）
      另有一次 **66.70 s** —— 那次机器上压着 17 个 Edge 进程，**同一份代码**，是负载不是产品变慢；
      把 Edge 清干净后重跑才是上面那两个数（另一次 50.97 s）
  裁决 1（v6 就定型的行为，v7 复测）：图4 块 **@1.42 s** 就绪时 `/api/sandbox/<job>` 已是真回放
      —— 200、**203,454 B**、events = 8，而**当时整任务 state 还是 running**
  裁决 2：图3 块就绪 **@52.53 s** 时 `/api/fig3/<job>/layers?missile=PL-12` → 200、10 层
  `/fig4?job=<id>` 200，回放页拿得到 job；产出图能下：`fig_isotime_plane_v7probe.png` 679,551 B、
      `fig_bg_plane_v7probe.png` 727,967 B；`result.parts` 四块齐（traj / plane / bg / fig3）
包内自检（`app\python\python.exe app\tests\run_tests.py`，LOCALAPPDATA 指向包内 kernel-cache）：
  **通过 457 / 失败 0 / 跳过 4 / 共 461，用时 216.8 s**（另一次 208.7 s；跳过的是"分发包清单判据"4 项，
  要读不随包的 `make_dist.py`；v6 是 468 / 0 / 4 / 472 —— 差的 11 项正是随预览一起删掉的判据）
  ⚠ 别把"461"当通过数：**461 是含那 4 项跳过在内的总项数**，通过是 **457**
清单/文档一致性（`python make_dist.py --check`，纯列表级）：必带项 **35 条全部有产出规则**、
  KEEP 清单逐条在位、仓库全量 **507** 项 − `TESTS_EXCLUDE` 46 项 = 包内 **461** 项（与文档里那行一致）
必带文件：REQUIRED_IN_BUNDLE **35 条逐项核对，缺 0 条**（对着**解压出来的** 2308 个文件验，不是源树）
秘密扫描（`.tmp_test/scan_secrets.py`，2308 个文件、1200 个按文本扫）：命中 44 条内容 + 1 条文件名，
  逐条看过仍是**同一批上游误报**（43 条上游作者邮箱、1 条 numpy `__config__.py` 里的 GitHub Actions
  构建机路径 `C:\Users\runneradmin\...`、1 条 PyPA `packaging/_tokenizer.py` 撞 `*token*`）⇒ 无凭据/无本机路径
双击 + 自动开浏览器（v7 版脚本 `.tmp_test/test_dblclick*_v7.ps1`，同一份解压目录）：
  **真双击语义**（`Start-Process 启动.bat`、ShellExecute、不给参数 ⇒ 默认端口 8765）
      → 首页可用 **3.32 s**（HTTP 200、19,533 B）；控制台窗口标题 = `导弹包线图`
  **自动开浏览器分支**：`webbrowser.open("http://127.0.0.1:8765/")` 确实被调用（`BROWSER` 记录器取证，
      双击后 0.01 s、URL 与端口都对）；不拦的那一次**真的起来了 Microsoft Edge**
      （**21 个新 msedge 进程**，最早在双击后 0.02 s，首页可用 **3.30 s**），
      窗口标题 = `导弹 (ΔV, BC) 包线图 · 本机表单 - 用户配置 1 - Microsoft Edge`（= 页面 <title>）；
      取证完服务与这批 Edge 都已关闭（端口释放、无残留 python、无残留 msedge）
```

#### 沙盒两个实时位置点的现场取证（v7 新形态，真浏览器读包内那份页面）

`.tmp_test/evidence_v7/sb_dots_dom_evidence.md` + 截图。浏览器是真 Edge（browser-skill 会话，
窗口 1280x900；画布 buffer 1198x904 / CSS 958x723）。页面自带取证钩子 `?t=<秒>&paused=1`
（`sandbox.js` 第 265 行把回放时刻钉死并暂停）⇒ 每一帧都可复现，不需要手拖进度条。
**取证对象是包内那份前端**：最终 zip 里 `app/src/missile_sim/webui_static/sandbox.js`
sha256 = `f724dc17f7af73993aab92f1b94acde03041d2df00e92e194ec8c6d9c0eb5886`，
与源树同一文件逐字节相同（DOM 读数取自同一份字节的另一份构建，两次构建只差两处**文档文字**、
共 +3 字节）。

| 回放时刻 | #sbDotMissile (left,top) | 点色 | #sbReadout (left,top) | 读数 − 弹点 | #sbDotTarget (left,top) | 点色 | #sbTargetLabel (left,top) | 标签 − 敌机点 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t=8.0 s | 779, 347 | #9a9a9a（开机前） | 759, 321 | **−20, −26（夹边）** | 125, 543 | #ff7f0e（转入crank） | 137, 555 | +12, +12 |
| t=35.0 s | 448, 381 | #8e44ad（开机后） | 458, 355 | +10, −26（= LABEL_OFF） | 178, 459 | #d62728（crank保持） | 190, 471 | +12, +12 |
| t=69.0 s | 153, 394 | #8e44ad（开机后） | 163, 368 | +10, −26（= LABEL_OFF） | 153, 394 | #1f77b4（转入39） | 165, 406 | +12, +12 |

* **点随回放时间轴走**：弹点 t=8→35 位移 (−331, +34) px、t=35→69 位移 (−295, +13) px；
  敌机点 t=8→35 (+53, −84) px、t=35→69 (−25, −65) px。
* **t=8 s 那一帧就是用户报的"字被切"**：不夹边时读数应在 `779+10 = 789`，实测 **759** ⇒ 被
  `placeLabel()` 夹回 **30 px**；夹边规则是 `min(x, W − w)`，W = 画布 CSS 宽 **958** ⇒ 反推标签宽
  199 px，右端刚好落在 958 = 画布右边界上，**裁掉 0 px**（截图 `sb_dots_t8.png` 里胶囊完整、贴边不越界）。
  同一帧敌机标签仍是原始偏移（+12, +12）⇒ 夹边只在需要时发生。
* **t=69 s（命中瞬间两个点完全重合，都是 153, 394）**时，两个标签分别在点的右上（+10, −26）与
  右下（+12, +12）⇒ 不会互相压住（截图 `sb_dots_t69.png`）。
* 截图（`E:\导弹包线图-dist\.tmp_test\evidence_v7\`）：`sb_dots_t8.png` / `sb_dots_t35.png` /
  `sb_dots_t69.png`（1573x952 整窗、DPR 1.25，含左栏），sha256 分别 a6544a52… / 3ed0fffa… / 464446ba…
* **另做了一次"最终包自己渲染出来的像素"交叉核对**（无头 Edge，独立临时 profile，
  `--hide-scrollbars --window-size=1258,761` ⇒ DPR=1、1 px == 1 CSS px；
  脚本 `.tmp_test/dom_frames_v7.ps1` + `dom_pixel_check.py`，截图 `pixel_t8/35/69.png`）。
  ⚠ Edge 154 在 Windows 上 `--dump-dom` **不吐 stdout**（新旧 headless 都试了，0 字节），
  所以 DOM 读数只能走 browser-skill 会话；无头这边只能拿截图。
  像素里量到的：**t=35 s 的读数胶囊左上角 (754, 397) 与弹点中心 (743.5, 422.5) 相差 (+10, −26)**，
  正是 `LABEL_OFF` 的常量（这个差是固定的 CSS px，与画布尺寸无关 ⇒ 可以直接跟 DOM 对拍）✓；
  **t=8 s 那一帧胶囊右端正好落在画布右边界上、余量 0 px**（画布右边界 1257、胶囊右端 1257）⇒
  贴边不越界，回到"没被裁掉"。弹点本身在像素里不好孤立：t=8 时导弹点与"开机前"的轨迹线**同色**，
  t=69 时 12 px 的敌机点盖住了 9 px 的导弹点（两点重合），这两条都跟 DOM 读数一致。

### 2026-10-03：v6 形态（单页四块）的隔离验证 —— **已被 v7 取代（历史版本）**

形态按 `docs/UX-TARGET.md`：图1 = ΔV–β、图2 = β–γ、图3 = 三维交互页 `/fig3`、图4 = 空战沙盒
`/fig4`（老 `/sandbox` 302 跳过去）；单页四块；**一次提交出四块**（`figure=four`，`all` 同义）；
无输入时图1/图2/图3 直出 11 弹静态散点、沙盒区不显形。

做法：zip 解到 `%TEMP%\导弹包线图 v6 release 测试 20261003\`（**路径带空格与中文**），把系统
`python` 从 PATH 排除后 `cmd /c 启动.bat --port 8877 --no-browser`，再用**包内解释器**当 HTTP
客户端逐条打（`.tmp_test/run_isolated_v6.ps1` → `probe_v6.py`；另有 `diag_four.py` 单独取裁决 1 的
时间线、`test_dblclick*.ps1` 取双击与开浏览器）。

```text
zip  ：E:\导弹包线图-dist\dist\导弹包线图.zip  56,443,848 B（53.8 MB）
       sha256 = a78ff31b26dfc95d4675e48da21e43e851782df9ef6e53da8464e9aa019bbc69
       （本版比上一版多了 `tests/test_dist_manifest.py` 与两条清单判据的文档，所以字节/指纹又变了：
         上一版 56,440,832 B / 5e53d0ae…，**已被本版取代**）
解压 ：15~17 s；解包后 2311 个文件 / 131.5 MB；inputs\ 170 个文件（+3 条目录条目 = zip 里 173 条）；
       根目录只有 启动.bat
首屏 ：**2.93 s**（`启动.bat` → `GET /` 返回 200，19,862 B 已渲染 HTML；另几次 2.43 / 2.96 s）
探针 ：**28 项 / 失败 0 项**（`probe_v6.py`）
  /healthz 200 · / 200（19,862 B：`id="fig1..fig4"` 四个锚点都在、`id="fig4" hidden` 在、
      两张 static 图被引用、页面里没有 `?tag=` 回放后门）· /fig3 200 · /fig4 200 · /viewer3d 200
  老路径：`/sandbox` → **302 Location=/fig4**
  边界：`/static/sandbox.html` → **404**（白名单 fail-closed）；`/api/sandbox/default` → **400**（回放后门已删）
  静态形态：`fig_isotime_plane_static.png` 251,395 B、`fig_bg_plane_static.png` 641,623 B、
      `plane_static.json` 5,306 B、`bg_static.json` 5,795 B 全部 200
      （⚠ v6/v8 打的这两版，图2 的 `_static` 还是 **10-03 的旧 γ 轴件**：首页贴的是 `_static`，
      而换轴那轮只重出了 `_default`。2026-10-04 已重出 ⇒ `fig_bg_plane_static.png` 现为
      **701,988 B**，v9 起随包的是新件。别照抄这里的字节数当期望值，见 `NOTES.md` §43）
  旧"渲染成品图" `fig_traj_default.png` → **404**（v6 已删，确认没跟着进包）
  图3：`/api/fig3/default` → 11 点；`/api/fig3/default/layers?missile=PL-12` → **200 + 10 层**（吃随包立方体）
  解算：`POST /api/single` → 200，t_hit = 45.186109475831095、backend = **compiled-c**
  一次提交四块：`POST /api/submit {figure: "four"}` → 200，id 拿到；四块全部 done
      **冷跑 48.82 s**（块就绪：fig4 @0.89 s → fig1 @26.51 s → fig2 @45.34 s → fig3 @48.57 s；
      更早两次 48.14 s / 47.17 s）
      热跑（同一份解包目录再提交一次）**7.42 s**
      产出图能下：`fig_isotime_plane_v6probe.png` 679,551 B、`fig_bg_plane_v6probe.png` 727,967 B
  裁决 1（**v6 关键行为**）：图4 块 **@1.22 s** 就绪时 `/api/sandbox/<job>` 已能取到**真回放**
      —— 200、**203,454 B**、events = 8、耗时 0.33 s，而**当时整任务 state 还是 running**
      （`diag_four.py` 另取一条时间线：@1.09 s → 200 / 203,454 B / 0.271 s / events 8）
  裁决 2：图3 块就绪 **@48.82 s** 时 `/api/fig3/<job>/layers?missile=PL-12` → 200、10 层、0.24 s
  result.parts 四块齐（traj / plane / bg / fig3）
包内自检（`app\python\python.exe app\tests\run_tests.py`，LOCALAPPDATA 指向包内 kernel-cache）：
  **通过 468 / 失败 0 / 跳过 4 / 共 472，用时 169.6 s**（那 4 项跳过的是"分发包清单判据"，它们要读
  `make_dist.py`，组装脚本不随包 ⇒ 记 SKIP，跳过≠通过；项数由 `make_dist.py --sync-docs` 生成）
清单/文档一致性（`python make_dist.py --check`，纯列表级、不组装）：
  必带项 **35 条全部有产出规则**；KEEP 清单与 `RESULTS_GLOBS` 逐条在位；仓库全量 **518** 项
  （= 514 + 本轮新增的 4 条清单判据）− `TESTS_EXCLUDE` 的 46 项 = 包内 472 项
  反向演练（证判据有牙）：把 `plane_static.json` 从 `RESULTS_KEEP` 摘掉 ⇒ 当场点名
  "`results/plane_static.json` 没有任何拷贝/生成规则能产出（清单漂移）"，`problems` 0 → 1
必带文件：REQUIRED_IN_BUNDLE **35 条逐项核对，缺 0 条**（对着**解压出来的**文件验，不是源树）
秘密扫描（`.tmp_test/scan_secrets.py`，2311 个文件、1200 个按文本扫）：
  **无凭据/无密钥/无作者机器路径**。命中 44 条内容 + 1 条文件名，逐条看过全是误报 ——
  43 条是随包 numpy/matplotlib/PIL/packaging 源码里的**上游作者邮箱**，1 条是 numpy 自己的
  `__config__.py` 里 `C:\Users\runneradmin\...`（GitHub Actions 构建机，不是本机），
  1 条文件名是 PyPA `packaging/_tokenizer.py` 撞了 `*token*` 规则
双击 + 自动开浏览器（补掉上一轮两个 gap，脚本 `.tmp_test/test_dblclick*.ps1`）：
  **真双击语义**（`Start-Process 启动.bat`，ShellExecute、不给参数、走默认端口 8765）
      → 首页可用 **2.34 s / 2.69 s**（最终版两次；更早两次 2.54 s / 3.36 s）；控制台窗口标题 = `导弹包线图`
  **自动开浏览器分支**：`webbrowser.open("http://127.0.0.1:8765/")` 确实被调用（用 `BROWSER`
      记录器拦下来取证，URL 与端口都对）；不拦的那一次**真的起来了 Microsoft Edge**，
      窗口标题 = `导弹 (ΔV, BC) 包线图 · 本机表单 - 用户配置 1 - Microsoft Edge`（= 页面 <title>），
      取证完已关闭（服务进程与 23 个 Edge 进程都杀了，端口释放、无残留 python）
```

### 2026-10-02：隔离目录端到端验证（上一版：图3 = 立方体页、图4 = 沙盒的老编号）

做法：`dist/导弹包线图.zip` 解到 `%TEMP%\导弹包线图 release 测试 20261002\`（**路径带空格与中文**），
在**把系统 python 从 PATH 里排除**的终端里 `cmd /c 启动.bat --port 8877 --no-browser`，
再用**包内解释器**当 HTTP 客户端逐条打（脚本 `.tmp_test/run_isolated.ps1` + `.tmp_test/probe_webui.py`）。

```text
⚠ 历史版本（**不是当前交付物** —— 当前那一版是 2026-10-03 v7 形态，见最上面那一节）：
zip  ：E:\导弹包线图-dist\dist\导弹包线图.zip  56,435,656 B（53.8 MB）
       sha256 = 7207bf4b9234eea1366407c549cabf9fa2d8bf66fa9dd924a7035217e5f5f0a9   ← 已被取代，别拿去核对
解压 ：17 s（从零解压，模拟"对方拿到就解压"）
PATH ：系统 python 已排除（`Get-Command python` 为空）⇒ 起服务用的就是 app\python\python.exe
首屏 ：**2.96 s**（从 `启动.bat` 到 `GET /` 返回 200、19,595 B 的已渲染 HTML）
探针 ：**23 项 / 失败 0 项**
  /healthz 200 · / 200（19,595 B，含 PL-12）· /sandbox 200 · /fig3 200 · /viewer3d 200
  /api/sandbox/default?points=200 → 200，events = 8（launch/burnout/crank_start/crank_done/
      seeker_on/beam_start/beam_done/end），hover.pending_keys = []
  /api/fig3/default → 200，points = 11
  /api/fig3/default/layers?missile=PL-12 → **200，layers = 10**（缓存命中：首次 0.26 s → 第二次 0.18 s）
  /static/sandbox.html → **404**（静态白名单 fail-closed）
  图1/图2/图4 成品图 + 沙盒产物 + 图3 产物 都能下（200）
  完整链路：`POST /api/single` → 200，t_hit = 45.186109475831095（= 仓库金标值）、backend = **compiled-c**
            后台任务 figure=plane（1.7 s）与 figure=traj（4.95 s）都跑到 done，产出的 PNG 能下载
收尾 ：无残留 python 进程，端口已释放
包内自检（app\python\python.exe app\tests\run_tests.py，LOCALAPPDATA 指向包内 kernel-cache）：
  **通过 455 / 失败 0 / 共 455，用时 291.3 s**
启动横幅（cmd 窗口里能看到）：许可提醒 + 中文字体 Noto Sans SC + 求解器身份 `dad09cae…` + **后端 compiled-c**
```

### 2026-09-27：更早一版（只含图1/图2）的验证

```text
分发包自己的解释器 + LOCALAPPDATA 指向包内 kernel-cache：
  python -m missile_sim --formats png,pdf,svg --tag smoke
  → 命中 1632/1632（100%）；等时线 13 层；backend = compiled-c；43.6 s

双击路径（cmd /c 启动.bat --port 8799 --no-browser）：
  → HTTP 200 · 19770 字节 · 页面含「等时线」「PL-12」

组装脚本内置冒烟测试（2026-09-27 扩到三条，图2 那条**必须真跑仿真**）：
  → 图1 不扫描 / 图2 不扫描 / 图2 粗扫（2×2），三条都出 png + pdf + svg
```

⚠ 冒烟测试为什么必须包含一次**真仿真**：图2 的仿真层靠给内核注入 `CxAoA`，
而这个注入**曾经是静默 no-op**（见 `docs/BETA-GAMMA.md` §4.2）—— 不报错、产物照样出，
只是 γ 轴完全不动。只验"三种格式都能写出来"是抓不住的。

## 已知小瑕疵（不影响一键可用）

* **字体权重警告**：随包字体是**可变字体**（`NotoSansSC-VF.ttf`）的子集，matplotlib 挑不到
  `weight=normal`，会退到 100（Thin）并每次打一行
  `findfont: Failed to find font weight normal for Noto Sans SC, now using 100.`。
  中文能正常显示（冒烟测试与图4 都出图了），只是笔画偏细。要根治得在子集化时把实例固定成
  Regular（`fontTools.subset` 的 instancer 参数），属于后续打磨项。
* `app/README.md` 与 `使用说明.txt` 里的模块/功能清单是**手写维护**的：壳里新增模块时
  记得回 `packaging/` 更新（这次就把 14 → 23 个模块、图4/沙盒/图3 的入口补上了）。
* 包内自检**剔掉了两个 `*_spike` 模块**（见上表，项数由 `--sync-docs` 生成）—— 因此收件人看不到
  "27 条缺 `spikes\...` 的红字"；另 3 项分发包清单判据在包内记 **SKIP**（要读不随包的 `make_dist.py`）。
* **包里唯一一处作者机器路径**：`vendor/wt-missile/VENDOR.md` 里写着 `E:\WT\...`。
  那句话是**作者机器上的内核/游戏数据来源说明，运行时不需要**（包内 `inputs/` 已经带全，
  内核也不去读那个目录）；按仓库规矩 `vendor/` 是**只读副本**，所以不改它。
* **两次踩到的同一个坑（值得记）**：v6 这轮 `REQUIRED_IN_BUNDLE` 加了
  `results/plane_static.json` / `bg_static.json`，但 `RESULTS_KEEP` 忘了同步 —— 组装期
  `verify_bundle()` **当场硬失败**（不是等收件人双击才发现）。这就是这条自检存在的意义：
  **要求清单与拷贝清单是两张表，必须一起改**。
* **`--zip` 之前必须先确认没有"从 `dist\导弹包线图\` 里双击起过的服务"**（2026-10-03 踩到，v7 重打时中招）：
  `run_ui` 会把 `LOCALAPPDATA` 重定向到包内 `app\kernel-cache\`，所以对方双击一次，
  **自动打开的那个浏览器就把它自己的用户配置写进了包内**（实测 `kernel-cache\Microsoft\Edge\User Data`
  堆到 262.7 MB / 1175 个文件，还有 23 个 `msedge.exe` 活着）。此时 `--zip` 的第一步
  `build_tree(..., clean=True)` 删暂存树会撞上 `WinError 32（另一个程序正在使用此文件）`，
  组装当场中止。**发出去的 zip 不受影响**（`clean=True` 先清再拷，且出包前核对过 zip 里
  `Microsoft/Edge` 条目数为 **0**），但打包机上要先把那棵 Edge 树杀掉再重打：
  按 `--user-data-dir` 指向包内目录筛进程（**别用"杀掉所有 msedge"**，会连用户自己开着的浏览器一起关）。
  取证脚本 `test_dblclick_real*.ps1` 结尾已经会杀它自己起的那一批。

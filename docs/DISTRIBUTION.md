# 分发：免安装版打包

对方拿到 `导弹包线图.zip` → 解压 → **双击 `启动.bat`** → 浏览器自动打开界面。
**不需要装 Python、不需要联网、不需要 C 编译器。**

## ⚠ 许可与分发边界（出包之前先读）

包里**含 War Thunder 游戏数据**：`app/vendor/wt-missile/inputs/` 下的 **168 份 `.blk`**
（权利归 **Gaijin Entertainment**）。求解器内核硬依赖它，去掉就跑不了 —— 这是"拿到就能用"
与"能公开分发"之间的**唯一冲突点**。

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
三处都写，是因为收件人可能只看其中一处。

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
    ├── tests/                  自检脚本（实测 455 项全绿；**剔掉了两个 `*_spike` 模块**，见下）
    ├── configs/                `web_default.json` + `presets.json`（**共享环境预设层，少它首页 500**）
    ├── figures/ results/       图1/图2 各两套 + 图4 输入预览（三格式）；沙盒与图3 的**只读产物**
    ├── docs/SOLVER-API.md      换内核唯一要读的
    ├── docs/BETA-GAMMA.md      β–γ 图的定义、推导与黄金值
    ├── README.md               面向**收件人**，模板在 packaging/README.app.md
    └── 使用说明.txt             极简引导，模板在 packaging/使用说明.txt
```

⚠ **不要把仓库的 `README.md` 拷进包。** 它面向开发者，引用了 `NOTES.md`、
`docs/RESTART-PLAN.md`、`docs/DISTRIBUTION.md`、`make_dist.py` 这些**包里根本没有**的东西，
收件人按图索骥只会扑空。分发包的说明单独维护在 `packaging/`，组装时写进去；
`README.app.md` 里**带图**（相对路径指向 `figures/`），对方打开就能看见成果长什么样。

`docs/` 只带两份：`SOLVER-API.md`（换内核的契约）与 `BETA-GAMMA.md`（β/γ 是什么）。
后者引用的 `tests/`、`src/` 包里都有，对方能顺着查；其余 `docs/*.md` 是开发过程记录，
引用的东西包里没有，不带。

实测体积（**2026-10-02**，Python 3.14.7 / numpy 2.5.3 / matplotlib 3.11.2；含图4、沙盒、图3 的那一版）：

| 项 | 大小 |
| --- | --- |
| `app/python/`（解释器 + 依赖，已裁 `tests`） | 117.2 MB |
| `app/vendor/`（内核 + 168 份 blk） | 3.2 MB |
| `app/fonts/`（思源黑体子集，7036 字） | 3.6 MB |
| `app/figures/`（当时 12 个：图1/图2/图4/预览 ×3 格式；**2026-10-03 起仓库里是 15 个** = 图1/图2 各 default+static 两套 + 预览，打包会跟着变大） | 4.1 MB |
| `app/results/`（17 个：含沙盒 4 份 + 图3 的 11 点与立方体） | 1.4 MB |
| `app/tests/` | 0.4 MB |
| **解压后合计** | **131.4 MB** |
| **zip** | **53.8 MB** |

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
| `figures/` | 图1/图2 各 default+static 两套 + 图4 输入预览（各三格式，共 15 个）；**图3/图4 没有静态成品** | 对方打开就能看成品（页面上的图是跑出来才有的，不靠这几张） |
| `results/plane_default*`、`bg_default*`、`compare_default.csv` | 带 | 首页摘要、图1/图2 的 manifest 与逐型表 |
| `results/traj_default_{missile,target,segments}.csv` + `traj_default.json` | **带** | `/fig4`、`/api/sandbox/<key>`、`/viewer3d` **只读**这四份（不带 ⇒ 页面 404 "没有产物"） |
| `results/fig3_default.json` + `fig3_default_cases.csv` | **带** | `/fig3`、`/api/fig3/<tag>` 的 11 个点 |
| `results/fig3_cube_*.json` | **带（glob）** | 文件名带**指纹**（`cube_key()` 含求解器 sha），所以按 glob 带。**少它 ⇒ `/api/fig3/<tag>/layers` 从"200 秒开"退化成"202 + 现扫几百工况"** |
| `results/missile_standards.json` | 带 | 11 型权威表（文档/对比用，也是 `-k pool_mapping` 黄金值的出处） |
| `results/` 其余历史产物（`pro_cache.json`、`native_compare*`、`cases_*.csv`…） | 不带 | 旧架构遗留，外壳不读 |
| `docs/` 只带 `SOLVER-API.md` + `BETA-GAMMA.md` | 带 | 后者引用的 `tests/`、`src/` 包里都有；其余 `docs/*` 是开发过程记录，引用的东西包里没有 |
| `tests/**` | 带（**排除 2 个 spike 模块**） | 让对方能自己验证这一包。`test_fig3d_spike.py` / `test_bg3d_spike.py` 的判据要读 `spikes/**` 的产物，而 `spikes/` 不随包 ⇒ 留着它们会让自检冒出 27 条红字（与"包好不好"无关） |
| `spikes/`、`archive/`、`.tmp_test/`、`make_dist.py`、`.git`、`NOTES.md` | 不带 | 探究记录 / 历史图 / 开发脚本，会让人按图索骥扑空 |
| `packaging/README.app.md` → `app/README.md` | 带 | 面向收件人（**表头就是许可边界**）；仓库 README 面向开发者，不能照抄 |

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

### 2026-10-02：隔离目录端到端验证（**含图4/沙盒/图3 的当前尖端**）

做法：`dist/导弹包线图.zip` 解到 `%TEMP%\导弹包线图 release 测试 20261002\`（**路径带空格与中文**），
在**把系统 python 从 PATH 里排除**的终端里 `cmd /c 启动.bat --port 8877 --no-browser`，
再用**包内解释器**当 HTTP 客户端逐条打（脚本 `.tmp_test/run_isolated.ps1` + `.tmp_test/probe_webui.py`）。

```text
zip  ：E:\导弹包线图-dist\dist\导弹包线图.zip  56,435,656 B（53.8 MB）
       sha256 = 7207bf4b9234eea1366407c549cabf9fa2d8bf66fa9dd924a7035217e5f5f0a9
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
* 包内自检**剔掉了两个 `*_spike` 模块**（见上表）—— 因此收件人看到的是"455 全绿"，
  而不是"27 条缺 `spikes\...` 的红字"。

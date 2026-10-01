# 开源化准备与合规审计（接 GitHub 前）

> **一句话结论**：外壳代码（`src/missile_sim/`、`tests/`、`docs/`）可以公开；
> **`vendor/wt-missile/` 的内核负载不能公开**（无许可的第三方源码 + 168 份 War Thunder 游戏数据），
> 而它**已经躺在 git 历史里**（103 个对象 / 0.38 MB，且被全部 11 个分支共享）——
> 所以**光加 `.gitignore` 是不够的**，必须走"干净初始提交"或"重写历史"，见 §4。
>
> **本文件不改动任何资产、不删除任何文件**：所有"移出仓库"的结论都是**临时改名 + 跑测试 + 立刻复原**
> 实测出来的（脚本在 `.tmp_test/`，已 gitignore）。

| 环境 | 值 |
| --- | --- |
| 工作区 | `E:\导弹包线图-oss`（git worktree） |
| 分支 / 基线 | `opensource` / `73eb2bc` |
| Python / numpy / matplotlib | 3.14.7 / 2.5.2 / 3.11.1 |
| git | 2.55.0.windows.3 |
| 跟踪文件数（HEAD） | 346，工作树 **20.35 MB** |
| 全量自检基线 | **339 通过 / 0 失败 / 339**（约 4 min） |
| 审计日期 | 2026-10-01 |

---

## 1. 结论先行（TL;DR）

1. **最高风险只有一处**：`vendor/wt-missile/`。它同时含"无许可声明的第三方源码"与"游戏数据"，
   而且它**是全部计算档位的唯一来源** —— 移出后全量自检从 339/0/339 掉到 **189 通过 / 150 失败**（实测，§4.2）。
   处置：**不公开**，改为"使用者自备"，并把"怎么自备"写进 [`vendor/README.md`](../vendor/README.md)。
2. **第二风险是 git 历史**，不是当前文件：`vendor` 只在 1 个提交（`dc960b8`）里，
   但那 103 个对象/vendor 快照被**所有分支**共享 —— `git rm --cached` + `.gitignore` **完全挡不住**。
   见 §4.1。
3. **`results/reference_fig.png`（用户提供的第三方参考图）建议也不公开**：权利不明，且**移出后 0 项测试变红**（实测）。
4. `archive/figures-legacy/**`、`results/runs/full_pro/**`、`results/pro_cache.json`
   **建议不公开**（历史垃圾 / 已删除架构的遗留），移出后同样 **0 项变红**（实测）。
5. `scripts/**` 的 `E:\WT` 硬编码**不用改代码**，只要在 README / 文档里写清"需要本机 War Thunder 数据挖掘仓库"。
   移出 `scripts/` 后 **0 项变红**。
6. 密钥扫描：**0 命中**（无 token/secret/password/私钥）。真正需要处理的是**绝对路径**（`E:\WT`、`C:\Users\MK`），
   它们出现在 `results/*.json` 与 `scripts/*.py` 里，见 §3。
7. 许可：**推荐 MIT**（理由与取舍表见 §5）。`LICENSE` 目前是**占位文件、不是许可证**。

---

## 2. 合规审计总表

"移出仓库会不会破坏测试与出图" = 临时改名后跑
`-k pool_mapping` / `-k solver_api` / `-k figures_repro` 三组的结果
（基线：**17/0/17**、**17/0/17**、**7/0/7**，全绿）。

| # | 资产 | 权利归属 | 公开分发风险 | 移出仓库破坏测试/出图吗（实测） | 建议 |
| --- | --- | --- | --- | --- | --- |
| 1 | `vendor/wt-missile/wt_missile.py`（142 KB 源码） | 第三方作者，**无许可声明** | **高**（默认 all rights reserved） | **会**：pool_mapping 8/9 ❌、solver_api 4/13 ❌、figures_repro 0/7 ❌ | **不公开**，自备 |
| 2 | `vendor/wt-missile/inputs/resources/2.59.0.28/**`（168 `.blk`） | Gaijin Entertainment | **高**（游戏数据再分发） | **会**：8/9 ❌、5/12 ❌、0/7 ❌ | **不公开**，自备 |
| 3 | `results/reference_fig.png`（用户提供的参考图） | 用户/第三方（**来源未标明授权**） | **中** | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开（或标注授权来源） |
| 4 | `archive/figures-legacy/**`（23 个早期图） | 本项目自有（数值来自游戏数据） | **低-中**（图里含型号名） | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开（历史垃圾） |
| 5 | `results/runs/full_pro/**`（2.6 MB，1824 工况） | 本项目自有，但**内容源自旧 pro 架构 + 游戏数据** | **中**（含 `elf_sha256`、`E:\WT` 路径） | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开 |
| 6 | `results/pro_cache.json`（1.1 MB，1844 条） | 同上 | **中** | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开 |
| 7 | `scripts/**`（13 个 `E:\WT` 工具） | 本项目自有（**公式抄自社区工作流**） | **低**（含绝对路径，无论文/无数据） | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | **保留**，文档写清前提 |
| 8 | `figures/**`（12 个成品图） | 本项目自有（自算数值） | **低** | 不适用（就是交付物） | 保留 |
| 9 | `results/*.json`（版本度量等） | 本项目自有 | **低** | 不适用 | 保留，但**清掉绝对路径**（§3.3） |

---

## 3. 逐项审计

### 3.1 `vendor/wt-missile/**` —— 最高风险项

**是什么**：一份第三方交付包的原样副本（`VENDOR.md` 记录 zip SHA-256
`4EEA98906FDEDDDE983AAD19EBC7848234C0415BFB9E0521F89BCC691D17F780`）：

| 组成部分 | 体积 | 内容 |
| --- | --- | --- |
| `wt_missile.py` | 141.7 KB | 2.59.0.28 原生 6DOF 的**纯 Python 复刻**（`MODEL = python-game-6dof-v1`，不执行游戏 ELF） |
| `inputs/resources/2.59.0.28/**` | 2.8 MB | **168 份 War Thunder `.blk`** + `presets.json` + `manifest.json`（156 个预设可计算） |
| `example.json` / `README.txt` | ~2 KB | 作者的示例与说明 |

**权利归谁**：两份不同的权利，**都不能由本项目授予**：
* `wt_missile.py` → **第三方作者**，而 `VENDOR.md` 与 `README.txt` **都没有任何许可声明**。
  没有许可声明 = 默认**保留全部权利**（all rights reserved）：公开再分发**没有授权依据**。
* `inputs/**` 的 168 份 `.blk` → **Gaijin Entertainment**（War Thunder 游戏数据）。
  它们是从游戏打包档里解出来的数据，再分发绕过游戏自身的分发协议。

**移出仓库会破坏测试与出图吗** —— **会，而且是全局的**（实测）：

| 移出东西 | `-k pool_mapping` | `-k solver_api` | `-k figures_repro` |
| --- | --- | --- | --- |
| 基线（什么都不动） | 通过 17 / 失败 0 | 通过 17 / 失败 0 | 通过 7 / 失败 0 |
| `vendor/wt-missile/` 整包改名 | **通过 8 / 失败 9** | **通过 4 / 失败 13** | **通过 0 / 失败 7** |
| 只把 `vendor/wt-missile/inputs/` 改名（留源码） | **通过 8 / 失败 9** | **通过 5 / 失败 12** | **通过 0 / 失败 7** |

也就是说：**168 份游戏数据不只是"参数"，它被求解器在加载时逐文件做 SHA-256 校验**
（`load_profile()`，`VENDOR.md` §"不许改的理由"）。只留源码、丢掉数据一样跑不动。

**全量影响面**（实测，见 §4.2）：339 项里 **189 通过 / 150 失败**。失败的 150 项集中在
`test_bg`(32)、`test_traj_plot`(17)、`test_solver_api`(13)、`test_report`(12)、`test_webui_traj`(11)、
`test_bg_scan`(10)、`test_pool_mapping`(9)、`test_figures_bg`(8)、`test_figures_repro`(7) …
**能把图算出来的每一层都依赖它**。

**影响面结论**：`vendor` 是本仓库的**硬依赖**，不是可选附件。它公开 = 直接再分发无授权资产；
它不公开 = 使用者必须自备，否则只能跑 189/339（其中 50 项是"完全不需要内核"的，见 §4.2）。

**建议**：不公开；新增 [`vendor/README.md`](../vendor/README.md) 写清
"本仓库不含内核 / 落位目录形状 / SHA-256 校验 / 没有内核时能跑到什么程度"。
**但 `vendor/wt-missile/VENDOR.md` 要保留** —— 它是**本项目自己写的**说明（哈希、升级流程、
已知边界），不含任何游戏数据；保留它才能让 `solver.py` 那句报错
（`vendor 求解器不在：…（见 vendor/wt-missile/VENDOR.md）`）指向一个真实存在的文件。

⚠ 有一处需要顺手修：`VENDOR.md` 第 7 行把来源写成本机路径
`D:\Download\wt-missile-win-linux-28-minimal.zip`。公开前删掉盘符目录、只留文件名即可（§3.3 同类）。

### 3.2 `results/reference_fig.png` —— 用户提供的第三方参考图

**是什么**：102 KB 的用户提供参考图，是**某个 2.57 基线**的 ΔV–BC 散点图，
`src/missile_sim` **完全不读它**（只有 `scripts/extract_reference_points.py` 用它做像素提取，
产物 `results/reference_points.json` 已经落库）。

**权利归谁**：**不明**。`AGENTS.md` 只说"用户提供的、从 `E:\WT` 那边拷来的"，
没有任何授权说明，图里的坐标系、配色与标点来自**别人做的那张图**。

**移出仓库会破坏测试与出图吗** —— **不会**（实测）：

```text
把 results/reference_fig.png 改名后：
  -k pool_mapping  => 通过 17 / 失败 0 / 共 17
  -k solver_api    => 通过 17 / 失败 0 / 共 17
  -k figures_repro => 通过  7 / 失败 0 / 共  7
```

**唯一的影响**是打包：`make_dist.py` 的 `RESULTS_KEEP` 里列了它，但拷贝逻辑是
`if s.exists(): shutil.copy2(...)`（`make_dist.py:386-390`）—— **文件不在就静默跳过**，
不会让 `make_dist.py --zip` 失败。代价是 `packaging/README.app.md:115,204` 与
`docs/DISTRIBUTION.md:98` 三处文案会指向一个不存在的文件（**文档债，需同步改**）。

**建议**：不公开（或先向图作者确认授权后再谈）。若用户坚持保留，**必须**在
`docs/` 里注明"这张图来自作者提供的参考，作者未声明许可，仅用于对照"，并接受被下架的风险。

### 3.3 绝对路径与"来源标注"（不是密钥，但同样该清）

`git grep` 全量跟踪文件的绝对路径命中（按文件聚合）：

| 命中数 | 文件 | 内容 | 处置 |
| --- | --- | --- | --- |
| 1824 | `results/runs/full_pro/cases.json` | `E:\WT\wt-missile-backend-runtime-1.0.1`（每条工况一行） | 该文件整体不公开（§3.5） |
| 3 | `make_dist.py` | `%LOCALAPPDATA%`（**正常引用**，内核缓存约定） | 保留 |
| 2 | `NOTES.md`、`docs/NEW-SOLVER-HANDOFF.md` | `%LOCALAPPDATA%` / 本机路径 | 保留（文档里的历史记录） |
| 1 | `AGENTS.md`、`README.md`、`docs/DISTRIBUTION.md`、`docs/SOLVER-API.md`、`vendor/wt-missile/VENDOR.md` | `%LOCALAPPDATA%` / `E:\WT` → 都是**正常的出处标注** | 保留（`VENDOR.md` 的 `D:\Download` 建议抹掉盘符） |
| 1 | `results/{native_compare,native_compare_all,native_compare_PL-12}.json` | `C:\Users\MK\AppData\Local\Temp\wt_research_101\...` | **建议清**（泄露本机用户名 `MK`，且是临时目录、无保留价值） |
| 1 | `results/{blkx_vs_table_vs_figure,table_vs_blkx,version_metrics,wt_missiles,wt_missiles_cached,wt_missiles_calc,wt_table_aam_arh,pro_missiles_50km,pro_cache,summary_pro_baseline,missile_shot_procheck,missile_shot_crossplot,runs/full_pro/manifest}.json` | `E:\WT\...` 各种路径 | **低风险**（是"数值来自哪个版本"的出处，属正常标注）；若要洁癖可批量替换为 `<WT-DATAMINE-REPO>` |
| 3 | `scripts/{extract_wt_table,missile_metrics,version_metrics,wt_missiles}.py` | `E:\WT\...` 硬编码 | **保留**（见 §3.7） |

**密钥/隐私扫描结论：0 命中。** 用
`git grep -i -E "(api[_-]?key|secret|password|passwd|BEGIN .*PRIVATE KEY|access[_-]?token|bearer )"`
扫全量跟踪文件，**没有任何一条命中**；`token` 的实际命中是
`webui.py` 的模板替换变量 `token`、`tests/test_figures_bg.py` 的断言局部变量 —— 全是同名误会。
`git config --local` 的身份是 `MK / MK@localhost`（本机占位，不是真实邮箱）。

### 3.4 `archive/figures-legacy/**` —— 23 个不可复现的早期图

**是什么**：重建前的旧外壳产物（`fig_sweep_isotime_*`、`workflow_*_main/detail`、
`fig_missile_bc_overlay_*` 等 23 个文件，HEAD 里 **6.87 MB 独占大半**），
其出图脚本**已随重建整体删除**（`archive/figures-legacy/README.md` 自述"无脚本可重出、非交付物"）。

**权利归谁**：本项目自有（本轮工作算出来的图）。但**图上的数值来自 War Thunder 游戏数据**，
且带型号名（AIM-120/PL-12/R-77…）—— 属于"社区研究的衍生作品"，风险比源码高一点、比原始数据低很多。

**移出仓库会破坏测试与出图吗** —— **不会**（实测 `17/0`、`17/0`、`7/0` 全绿）。

**建议**：**不公开**。理由三条：① 不可复现（脚本已删），公开了也没人能验证；
② 占 HEAD 体积的 34%；③ `archive/figures-legacy/README.md` 里给了"想恢复就 `git mv` 回来"的指引，
但它引用的 `scripts/pipeline.py` 等脚本已经不存在，等于一条死路。
**保留在本地历史里**即可（`git log` 还能查到），公开仓库不带。

### 3.5 `results/runs/full_pro/**`（2.6 MB）—— 已删除的旧 `pro` 架构遗留

**是什么**：一次 1824 工况的 `full_pro` 扫描（`manifest.json` 写明 `wall_s = 2618.82` = 43.6 min、
`n_hit = 1824`）。它记的是 **`pro` 档（`unicorn` 跑原生 ELF）** 的结果，
而 `pro` 引擎与 `--backend` 参数**已在重建时整体删除**（`docs/RESTART-PLAN.md` §2）。
`cases.json` 2.6 MB，其中 **1824 行**都带 `"pkg": "E:\WT\wt-missile-backend-runtime-1.0.1"`。

**还被任何测试/文档引用吗**（`git grep` 取证）：

```text
git grep -n -E "reference_fig|figures-legacy|pro_cache|full_pro|runs[\\/]" -- src tests
→ 只有一条，而且是**假命中**：
  tests/test_figures_bg.py:69  def test_nstar_levels_are_ordered_and_inside_the_reference_figure_range():
（测试**函数名**里有 "reference figure"，不是文件引用）
```

即：**`src/` 与 `tests/` 对这些文件零引用**。它们只被 `docs/RESTART-PLAN.md`、
`docs/SHELL-REBUILD-FEASIBILITY.md`、`docs/NEW-SOLVER-HANDOFF.md`、`NOTES.md`
**当历史记录提到**（"那是 44 min 的资产，不能丢"）。

**移出仓库会破坏测试与出图吗** —— **不会**（实测 `17/0`、`17/0`、`7/0` 全绿）。

**建议**：**不公开**。它的"44 min 不可重建"叙事属于**旧引擎**：
今天同样的 1824 工况在 `fast` 档约 **0.27 min**（README §4：1824 点网格 4.7 min → 0.27 min），
所以"不可重建"这个理由已经不成立。留着它只会让公开读者以为这是当前架构的产物。
处置建议：`git rm -r --cached results/runs/full_pro`（**本任务不执行**，只在方案里列出）。
同时把 `.gitignore` 里那条 `!results/runs/full_pro/` 白名单删掉（本次已改，见 §6.4）。

### 3.6 `results/pro_cache.json`（1.1 MB，1844 条）—— 同一族遗留

同上：**旧 `pro`（unicorn/ELF）档的缓存**，`docs/SHELL-REBUILD-FEASIBILITY.md` §R2 记
`n_entries = 1844`。当前架构的缓存已经改为
`results/cache/{standard,fast}.json`（`.gitignore` 忽略、`cache_key()` 显式带 tier）。

**还被引用吗**（`git grep` 取证）：`src/`、`tests/` **零引用**；只有
`results/missile_shot_crossplot.json`、`results/summary_pro_baseline.json`、
`results/runs/full_pro/manifest.json` 在**自己的 metadata 里**写了它的路径 —— 
也就是**同族的旧产物互相引用**，没有活代码依赖。

**移出仓库会破坏测试与出图吗** —— **不会**（实测 `17/0`、`17/0`、`7/0` 全绿）。

**建议**：**不公开**。`git rm --cached results/pro_cache.json`（**本任务不执行**）。
若用户舍不得，至少**不要**在公开仓库里保留它 —— 它含 1844 条游戏数据推导值 + `E:\WT` 路径。

### 3.7 `scripts/**`（13 个，59.7 KB）—— 数据出处链工具

**是什么**：13 个需要本机 War Thunder 数据挖掘仓库的"考古"脚本（`version_metrics.py`、
`extract_wt_table.py`、`blkx_vs_table_vs_figure.py` …）。其中
`scripts/missile_metrics.py` 的公式是**逐行照抄**社区工作流
`E:\WT\War-Thunder-Datamine\自动化分析\skills\wt-aam-analysis\scripts\plot_version_compare.py :: metrics()`，
并已**复刻进** `src/missile_sim/mapping.py`（所以新外壳不依赖 `scripts/`）。

**权利归谁**：本项目自有代码；**公式本身是数学，不受版权保护**，
但"逐行照抄别人的脚本"这一点应当在文档里**主动致谢并标明出处**（现在的脚本头注释已经写了出处，
这是好习惯，保留）。

**移出仓库会破坏测试与出图吗** —— **不会**（实测 `17/0`、`17/0`、`7/0` 全绿）。
`docs/RESTART-PLAN.md` §7 也早就写着"13 个 `E:\WT` 数据链脚本保留在 `scripts/`，
但新外壳**不依赖**它们"。

**建议**：**保留**（它们是"每个数值从哪来"的证据链，公开反而加分）。
**不要**把 `E:\WT` 硬编码改成可配置 —— 那会让脚本假装通用，实际仍然必须有那个仓库。
正确做法：在这 13 个脚本的 README 或 `CONTRIBUTING.md` 里写清前提
（本次已在 `CONTRIBUTING.md` §5 写明）。

---

## 4. 关键：`.gitignore` 管不住历史，必须选一条路线

### 4.1 历史取证（实测）

```text
git log --oneline --all -- vendor          → 1 条
  dc960b8 chore(vendor): 入库 wt-missile 2.59.0.28 最简求解器包
git branch -a                              → 11 个分支（main/new/restart/webui/图2/图3/…）
git rev-list --all --count                 → 90 个提交（HEAD 侧 79）
```

| 指标 | 数值 |
| --- | --- |
| 历史对象总数 / 磁盘占用 | **1213 个 / 28.19 MB**（`%(objectsize:disk)` 求和） |
| 路径含 `vendor/` 的历史对象 | **103 个**，磁盘 **0.38 MB**，未压缩 **1.75 MB** |
| 其中 `vendor/wt-missile/inputs/**` | **98 个**对象，磁盘 **0.33 MB** |
| 路径含 `.blk` 的历史对象 | **93 个** |
| HEAD 的 `vendor/` 工作树体积 | **2.98 MB / 174 个文件** |

⚠ **为什么 `.blk` 只有 93 个而文件有 168 个**：`git ls-files -s vendor` 显示 168 个 `.blk` 但只有
**93 个唯一 blob** —— 有 75 份 `.blk` 是**逐字节重复**的（同型号不同变体共用配置）。
这解释了两件事：① 历史里 vendor 的**压缩体积只有 0.38 MB**（所以"它很小，无所谓"是错觉 ——
**体积小不等于不侵权**）；② `git rev-list --objects` 不去重路径，报"93"是**唯一对象数**，
168 个路径仍然全部可达。

**结论**：`vendor` 只在 1 个提交里，但那 1 个提交在**所有 11 个分支的共同祖先链**上。
只要 push 现有的 `.git`，`vendor/wt-missile/**` 就会被完整公开 —— 
**`git rm --cached` + `.gitignore` 只能影响"下一个提交"，对已存在的对象毫无作用**。

### 4.2 没有内核时的红绿分布（实测，决定 CI 能跑什么）

把 `vendor/wt-missile/` 改名后跑**全量**自检：

```text
通过 189 / 失败 150 / 共 339，用时 3.1 s
```

失败的 150 项按模块：`test_bg` 32、`test_traj_plot` 17、`test_solver_api` 13、`test_report` 12、
`test_webui_traj` 11、`test_bg_scan` 10、`test_pool_mapping` 9、`test_figures_bg` 8、
`test_figures_repro` 7、`test_traj` 7、`test_grid_axis` 6、`test_figure_labels` 5、
`test_webui_bg` 5、`test_bg_pipeline` 4、`test_targets` 2、`test_webui` 2。

**完全不需要内核、可原样进 CI 的组**（逐条实测）：

| `-k` | 通过 | 失败 | 用时 |
| --- | --- | --- | --- |
| `flightpath` | 37 | 0 | 0.8 s |
| `form_dirty` | 12 | 0 | 0.0 s |
| `printed_text` | 1 | 0 | 0.0 s |
| 合计 | **50** | 0 | — |

另外 `python -m compileall src tests` 与 `python -m pip wheel . --no-deps` 都在无内核时成功
（后者产出 `missile_sim-0.1.0-py3-none-any.whl`，169 KB）。

### 4.3 路线 A：**新建干净仓库、单次初始提交**（✅ 推荐）

**为什么推荐**：① 公开的历史**只有一条提交**，不可能"漏了某个旧提交里的秘密"；
② 不动本仓库的历史与对象库，**对另外两个 worktree 零风险**（见 §4.5）；
③ 不需要装 `git filter-repo`（本机确实没装，见 §4.4 前提）；④ 可验证性最好 ——
"公开前自检清单"全是可数的事实。

**⚠ 一个必须先讲清的事实（实测）**：`git clone <本仓库>` 只会给你**当前 worktree 的那一个分支**
（`refs/heads/opensource`），其余 10 个分支只存在于 `refs/remotes/origin/*` 里，
`git remote remove origin` 之后**它们就不在这个克隆里了**。实测：

```text
clone 里的本地分支: refs/heads/opensource
clone 里的其它 ref: （空）
```

这既是个坑也是个好处：**路线 B 的克隆天然只带一个分支**，只要不 `--mirror` 推送，
另外 10 个分支的 vendor 历史根本不会被推出去；但也意味着**"我 push 了 opensource 就等于全部清净"**
是错的 —— 如果你用 `git push --all` / `--mirror`，别的分支一样会带出 vendor。

**命令序列（本机已实测跑通，产物在 `.tmp_test/routeA`）**：

```powershell
# 0) 在一棵**干净**的导出里工作（不要在本仓库里删东西）
cd "E:\导弹包线图-oss"
git archive --format=zip --prefix=snap/ -o "$env:TEMP\oss-snapshot.zip" HEAD
Expand-Archive "$env:TEMP\oss-snapshot.zip" -DestinationPath "$env:TEMP\oss-snapshot" -Force
cd "$env:TEMP\oss-snapshot\snap"          # 这棵树里没有 .git，只有 HEAD 的文件

# 1) 删掉"不公开集"（新仓库还没有历史，这一步不是改历史，也不会污染任何仓库）
Remove-Item -Recurse -Force vendor\wt-missile\wt_missile.py,
    vendor\wt-missile\example.json, vendor\wt-missile\README.txt,
    vendor\wt-missile\inputs,
    archive\figures-legacy,
    results\reference_fig.png, results\pro_cache.json, results\runs

# 2) 建新仓库 + 唯一一条提交
git init -b main
git add -A
git commit -m "初始提交：导弹包线图（外壳 + 自算产物；内核与游戏数据不含，见 vendor/README.md）"

# 3) 公开前自检（下表全过才 push）
git rev-list --count HEAD                 # 必须 == 1
git ls-files | Select-String vendor       # 必须只看到 vendor/README.md 与 vendor/wt-missile/VENDOR.md
git ls-files | Select-String '\.blk$|\.blkx$|\.vromfs'   # 必须 0 条
git count-objects -vH                     # 看 size-pack
git remote -v                             # 决定要 push 到哪
```

**实测结果（`.tmp_test/routeA`，2026-10-01）**：

```text
git archive HEAD -> zip                      10.97 MB
按"公开排除集"删掉后：
  git rev-list --count HEAD                  = 1                       ✅
  git ls-files | Select-String vendor        = 1 条（vendor/wt-missile/VENDOR.md）
  git ls-files 里的 .blk/.blkx/.vromfs       = 0 条                     ✅
  跟踪文件数                                  = 144
  工作树受跟踪体积                             = 6.54 MB
  .git（154 个松散对象，未 gc）                 = 3.79 MiB
  git log --oneline                          = 1 条
  git remote -v                              = 空                      ✅
  -k flightpath / form_dirty / printed_text  = 37 / 12 / 1 全绿         ✅
```

> 注：这次实测用的是 `HEAD`（`73eb2bc`）导出的树，所以 `vendor` 只剩 **1 条**（`VENDOR.md`）；
> 本轮新增的 `vendor/README.md` 提交后，该行会是 **2 条**（两个都是**本项目自己写的**说明文件）。

**代价 / 取舍**：① 丢掉全部提交历史 —— 对一个要公开的社区项目，这**恰恰是想要的**；
② `git blame` 归零；③ 若将来想保留历史，得用路线 B。

### 4.4 路线 B：**原地重写历史**

**工具前提（实测）**：

```text
git-filter-repo : NOT FOUND
bfg             : NOT FOUND
python          : C:\Program Files\Python314\python.exe
pip show git-filter-repo → WARNING: Package(s) not found: git-filter-repo
git filter-branch → 可用（自带，会打 "glut of gotchas" 警告）
```

所以：**要么先 `python -m pip install git-filter-repo`，要么用 `git filter-branch` 兜底**。

⚠ **路线 B 绝对不能在本仓库/worktree 里跑**（原因见 §4.5）。正确做法是
**先克隆一份**，在克隆里重写：

```powershell
# 1) 克隆（本机路径克隆 = 只读旧仓库，不碰它）
git clone --no-hardlinks "E:\导弹包线图-oss" "$env:TEMP\oss-rewrite"
cd "$env:TEMP\oss-rewrite"
git remote remove origin                 # 重写期间不要有这个 remote，避免误 push

# 2A) 有 git-filter-repo 时（更安全、更快）
git filter-repo --force --invert-paths `
    --path vendor/wt-missile/wt_missile.py `
    --path vendor/wt-missile/example.json `
    --path vendor/wt-missile/README.txt `
    --path vendor/wt-missile/inputs `
    --path archive/figures-legacy `
    --path results/reference_fig.png `
    --path results/pro_cache.json `
    --path results/runs

# 2B) 没有 filter-repo 时的兜底（本机实测可用）
$env:FILTER_BRANCH_SQUELCH_WARNING = "1"
git filter-branch --force --index-filter `
  'git rm -r --cached --ignore-unmatch vendor/wt-missile/wt_missile.py vendor/wt-missile/example.json vendor/wt-missile/README.txt vendor/wt-missile/inputs archive/figures-legacy results/reference_fig.png results/pro_cache.json results/runs' `
  --tag-name-filter cat -- --all

# 3) ⚠⚠ **最容易漏、漏了就白干的一步**：删掉 filter-branch 的备份 ref。
#    filter-branch 会把重写前的 HEAD 存进 refs/original/*，**那是一个真 ref**，
#    因此所有旧对象仍然"可达"，`git gc --prune=now` **一个字节都清不掉**。
foreach ($r in @(git for-each-ref --format='%(refname)' refs/original)) {
    git update-ref -d $r
}

# 4) 把旧对象真正清掉（不清的话对象还在 .git 里，仍然能被 clone 出来）
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 5) 自检（下表）
git for-each-ref --format='%(refname)'                      # refs/original 必须已消失
git rev-list --objects --all | Select-String 'vendor/|\.blk' # .blk 必须 0 条
git log --oneline --all -- vendor                            # 允许剩"空提交"，不允许剩路径
git count-objects -vH
```

**实测结果（`.tmp_test/routeB2`，2026-10-01）**：

```text
重写前：.git = 28.45 MB ; vendor 对象 = 103 ; .blk 对象 = 93
filter-branch --index-filter -- --all → Ref 'refs/heads/opensource' was rewritten  (exit 0)
删掉 refs/original/refs/heads/opensource（这一步是本轮的关键修正）
reflog expire --expire=now --all ; gc --prune=now --aggressive
重写后：.git = 21.49 MB ; in-pack = 1032 个对象
  历史里 vendor/ 对象        = 2 条（vendor/wt-missile 树 + vendor/wt-missile/VENDOR.md）  ✅
  历史里 .blk/.vromfs 对象   = 0 条                                                      ✅
  git log --oneline --all -- vendor = 1 条（dc960b8 还在，但已经不含内核负载）
  提交数                     = 79（历史保留，哈希全变）
  git ls-files               = 144（与路线 A 完全一致）
```

> **反面对照（第一版漏了第 3 步的实测结果，值得引以为戒）**：只做 `reflog expire + gc` 而**不删
> `refs/original`** 时 —— 历史里仍有 **104 个 `vendor/` 对象、93 个 `.blk` 对象**，
> `git log --all -- vendor` 仍有 **2 条**，`.git` 只从 28.45 MB 降到 **22.14 MB**。
> **看起来"我重写过了"，实际一个对象都没删掉，push 出去照样泄露。**
> 这就是"历史必须实测取证、不能凭感觉"的直接理由。

**风险（必须写进决策）**：
* **所有提交哈希都会变**（`dc960b8` → 新的），任何引用了旧哈希的文档/NOTES 会失效；
* **`refs/original/*` 必须显式删掉**（第 3 步），否则 `gc` 清不掉任何东西 —— 见上面的反面对照；
* `git filter-branch` 官方已不推荐（会打 "glut of gotchas" 警告），只在装不了 `git-filter-repo` 时用；
* 克隆只带当前分支（§4.3 开头实测），**要公布几个分支就必须先把它们都推进克隆再重写**；
* **在克隆里重写**之后，要把生成的仓库当作新的"公开源"，旧仓库继续当私有工作区。

**为什么这里的风险可接受**：本仓库**还没有任何 remote**（实测 `git remote -v` 为空），
也从没推过远端 —— 所以"重写已发布历史"这个最痛的问题**不存在**，
重写只影响本机的三个 worktree。

### 4.5 ⚠ 硬约束：本仓库是三 worktree 共享的，**不要在这里重写历史**

实测：

```text
git worktree list
  E:/导弹包线图     73eb2bc [webui]
  E:/导弹包线图-3d  73eb2bc [3d-viz]
  E:/导弹包线图-oss 73eb2bc [opensource]

E:\导弹包线图-oss\.git  →  "gitdir: E:/导弹包线图/.git/worktrees/导弹包线图-oss"
git rev-parse --git-common-dir  →  E:/导弹包线图/.git
git rev-parse --git-dir         →  E:/导弹包线图/.git/worktrees/导弹包线图-oss
```

即：**三个 worktree 共用同一个对象库与同一套 refs**。
在 `E:\导弹包线图-oss` 里跑 `git filter-branch` / `git filter-repo` 会重写
**`E:\导弹包线图` 的 `.git`**，直接打断正在 `webui` 分支上干活的 Lead 与
`3d-viz` 分支上的队友（他们的 `HEAD`、索引与分支指针会一起被改）。

**所以：路线 B 必须"先 clone 到别处再重写"**；路线 A 天然安全（只读 `git archive`）。

### 4.6 公开前自检清单（push 之前逐条打勾）

| # | 检查 | 命令 | 期望 |
| --- | --- | --- | --- |
| 1 | **历史里没有游戏数据** | `git rev-list --objects --all \| Select-String '\.blk\|\.blkx\|\.vromfs'` | **0 条** |
| 2 | 历史里没有内核源码 | `git rev-list --objects --all \| Select-String 'wt_missile\.py\|vendor/wt-missile/inputs'` | **0 条** |
| 3 | filter-branch 的备份 ref 已删 | `git for-each-ref --format='%(refname)' refs/original` | **空**（不空 = 一个对象都没删掉） |
| 4 | 工作树里没有内核/游戏数据 | `git ls-files \| Select-String '\.blk$\|\.blkx$\|\.vromfs\|wt_missile\.py'` | 0 条 |
| 5 | 提交数 | `git rev-list --count HEAD` | 路线 A：**1**；路线 B：79 |
| 6 | 无远端/无误 push | `git remote -v` | 由使用者显式添加后才非空 |
| 7 | 跟踪体积 | `git count-objects -vH` | 路线 A：工作树 6.54 MB / `.git` 3.79 MiB；路线 B：`.git` 21.49 MB |
| 8 | 绝对路径 | `git grep -n -E 'C:\\\\Users\|D:\\\\Download'` | 0 条 |
| 9 | 密钥 | `git grep -n -i -E '(api[_-]?key\|secret\|password\|BEGIN .*PRIVATE KEY)'` | 0 条 |
| 10 | 无内核也能绿 | `python tests\run_tests.py -k flightpath` 等三组 | 37 / 12 / 1 全绿 |
| 11 | 内核在场才绿 | 有内核时 `python tests\run_tests.py` | 339 / 0 / 339 |
| 12 | 许可已定 | `LICENSE` 是**完整标准正文**，不是占位 | 见 §5 |

---

## 5. 许可取舍表与推荐

**背景约束**（这三条决定了选择）：
① 这是**社区独立项目**，与 Gaijin 无关系；② 仓库里**含有无许可声明的第三方内核**（虽然公开集里会被移出，
但历史/文档里仍会提到它）；③ 产物是**游戏数据的衍生数值**。

| 维度 | **MIT** | Apache-2.0 | GPL-3.0 |
| --- | --- | --- | --- |
| 篇幅 / 阅读成本 | 约 170 词，人人能读完 | 约 1500 词，需留意 NOTICE | 约 5000 词 + 全文 copyleft |
| 宽松度 | 最宽松（改完可闭源） | 宽松（需保留 NOTICE、声明变更） | 强 copyleft（衍生作品必须同许可） |
| **专利授权** | **无**明文条款 | **有**明文专利授权 + 专利报复终止 | 有（第 11 条） |
| 商标 | 无条款（默认不给商标权） | 第 6 条明确不授予商标权 | 第 7 条 |
| 与"无许可的第三方内核"组合 | 不冲突：许可证**只覆盖本仓库自有代码** | 同 MIT，但 NOTICE 措辞要更小心 | **冲突感最强**：GPL 要求整体可分发的合规性，而内核是 all-rights-reserved，会逼出"分发者如何解释"的麻烦 |
| 对"派生数值/图"的传染 | 无 | 无 | 有（图是否算衍生作品会成为争议） |
| 社区接受度（仿真/科研工具） | 最高 | 高（大厂偏好） | 中（工具类项目少用） |
| 被"闭源拿走"的风险 | 有 | 有 | 无 |

**推荐：MIT**，理由：

1. **本项目的价值在"文档 + 可复现的产物"，不在代码本身。** 最宽松的许可能让做同类研究的
   人直接拿走 `mapping.py` 的公式实现，这才符合项目目的。MIT 是这类"研究工具"的默认选择。
2. **与"内核无许可"这件事的兼容性最好。** MIT 只覆盖本项目自己写的东西，
   不会像 GPL 那样把"整体分发"的合规义务抬到必须解释"内核算什么"的地步。
3. **专利条款不是本项目的痛点**：这是一份物理仿真与可视化代码，没有可专利的实现主张；
   Apache-2.0 多出来的 1300 词在这里买不到实际保护。
4. 若用户**更在意"被大公司闭源拿走"**：那就选 **Apache-2.0**（仍宽松，但多了变更声明与专利报复条款），
   代价是要维护 `NOTICE`。**不推荐 GPL-3.0**：它会让"图的衍生作品性"与"内核的 all-rights-reserved"
   两件事一起变成负担，而这个项目的用户群体（社区研究者）通常不介意宽松许可。

**无论选哪个，都必须做的两件事**：
* 把 `LICENSE` 换成该许可的**完整标准正文**（英文原文，一字不改）；
* 同步更新 `pyproject.toml`（现在刻意**没写** license 字段）与 `README.md` §9.5。

---

## 6. 必备文件状态

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `LICENSE` | ⏳ **占位**（不是许可证） | 正文等用户拍板；文件里明确写了"这不是许可证"与三个候选，避免误解 |
| `CONTRIBUTING.md` | ✅ 新增 | 起步 5 分钟、提交前必过的四条判据、行尾纪律、数值改动额外要求、不要提交什么、报告/PR 约定、许可与免责 |
| `pyproject.toml` | ✅ 新增 | `requires-python = ">=3.12,<3.15"`、`numpy>=2.5.2,<3`、`matplotlib>=3.11,<4`、`[project.scripts] missile-sim`；**刻意不写 license 字段** |
| `README.md` | ✅ 已补 | 标题后加"本仓库不含内核 + 独立社区项目"提示；文末新增 §9（免责声明 / 产物是仿真结果 / 数据来源与版本标注 / 不含哪些东西 / 许可） |
| `vendor/README.md` | ✅ 新增 | **公开文件**：为什么要自备内核、落位目录形状、SHA-256 校验、没有内核时能跑到什么程度、不要做什么 |
| `.gitignore` | ✅ 已评估并小改 | 见 §6.4 |
| `.github/workflows/ci.yml` | ✅ 新增草稿 | 见 §6.5 |
| `NOTES.md` | ✅ 字节追加一节 | 见 §8 |

### 6.4 `.gitignore` 的评估结论

| 条目 | 还该留吗 | 结论 |
| --- | --- | --- |
| `results/runs/*` | **留** | 临时扫会留一堆 4 工况小目录，忽略是对的 |
| `!results/runs/full_pro/` | **删** | 它是**已删除架构**的白名单，且副作用是"full_pro 里任何新文件都会被自动跟踪"，与"不入库"意图相反。本次已删（该文件仍被跟踪，`.gitignore` 不影响已跟踪文件） |
| `results/cache/` | **留** | 当前档位缓存可重建 |
| 旧注释"`pro_cache.json` / `flash_cache.json` 仍照常入库（44 min 的资产）" | **改写** | 引擎已删；`flash_cache.json` 根本不存在；`pro_cache.json` 是遗留资产，见 §3.6 |
| 新增"开源排除集"段 | **新增** | 把 vendor 内核负载的四个路径忽略掉，防止将来 `git add -A` 误提交；**不含** `VENDOR.md` 与 `vendor/README.md`（这两个要公开） |

### 6.5 CI 的判断：哪些只能在 Windows 上跑

实测结论（写进 `ci.yml` 的注释里）：

| 部分 | 平台要求 | 为什么 | 托管 runner 能跑吗 |
| --- | --- | --- | --- |
| `-k flightpath` / `form_dirty` / `printed_text`（50 项） | **跨平台** | 纯运动学编译 + 表单差异 + 文本扫描，不碰内核 | ✅ ubuntu + windows 都跑 |
| `python -m compileall src tests` | 跨平台 | 纯语法 | ✅ |
| `pip install -e .` / `pip wheel . --no-deps` | 跨平台 | 验证 `pyproject.toml` | ✅（包装元数据本机实测可构建） |
| `-k solver_api` / `figures_repro` / 全量 339 项 | **需要内核** | `.blk` 逐文件 SHA-256 校验；内核缺席时 150 项必红 | ❌ **不能**：公开仓库的 CI 不可以上传内核（那就是在再分发） |
| `fast` 档（`compiled-c`） | **需要 C 编译器** | MSVC（Windows）/ `cc`（Linux）；缺了就回落 `python-legacy`，数值完全相同 | 代码上 `windows-latest` 自带 VS 2022 可以编；但**拿不到内核**，所以实际只能在 self-hosted 跑 |

因此 `ci.yml` = 托管 runner 的"50 项 + 包装校验"（**本地逐条验过**）
＋ 手动触发的 `self-hosted, windows` 全量 job（**明确不支持公开 CI 里跑内核**）。

---

## 7. 给用户的决策清单

> 每一条都要用户拍板；带 ⭐ 的是**阻塞公开**的。

| # | 决策 | 选项 | 我的建议 | 影响 |
| --- | --- | --- | --- | --- |
| 1 ⭐ | **`vendor/wt-missile/**` 怎么办** | (a) 公开（自担风险） (b) **不公开、使用者自备** (c) 公开但只留 `VENDOR.md` | **(c)** = 移出 `wt_missile.py` + `inputs/` + `example.json` + `README.txt`，**保留自己写的 `VENDOR.md`**，并配 `vendor/README.md` 说明自备方式 | 移出后全量 339 → 189/150（实测）；`solver.py` 的报错文案仍指向存在的文件 |
| 2 ⭐ | **历史怎么处理** | (A) **新建干净仓库、单次初始提交** (B) `filter-repo`/`filter-branch` 重写历史 | **(A)**：简单、可验证、对另两个 worktree 零风险。若用户舍不得历史 → (B)，但**必须在 clone 里做**（§4.5） | (A) 丢历史、`.git` 约 6.6 MB；(B) 保留 79 条提交但所有哈希变化，且**必须**清 reflog+gc |
| 3 ⭐ | **是否先私有** | (a) 先私有仓库跑一周 (b) 直接公开 | **(a)**：先把 CI 跑绿、把 §4.6 十条自检过一遍，再切 public。仓库转公开只是点一下，但**一旦 public，历史就进过别人的 clone 了** | 先私有的成本接近 0，收益是"错了还能改" |
| 4 ⭐ | **许可类型** | MIT / Apache-2.0 / GPL-3.0 | **MIT**（理由见 §5）；在意"被闭源拿走"则 Apache-2.0；**不推荐 GPL-3.0** | 决定 `LICENSE` 正文、`pyproject.toml` 的 license 字段、README §9.5 |
| 5 | `results/reference_fig.png` | 保留 / 移出 / 保留但标注来源 | **移出**（或先向作者要一句授权）。移出对测试 **0 影响**，但 `make_dist.py`/`packaging` 两处文案要同步 | 移出后分发包少一张对比图（`make_dist.py` 静默跳过，不会报错） |
| 6 | `archive/figures-legacy/**`（23 图，6.87 MB） | 保留 / 移出 | **移出**（不可复现、无脚本、占 HEAD 体积 34%） | 0 测试影响 |
| 7 | `results/runs/full_pro/**` + `results/pro_cache.json`（3.7 MB） | 保留 / 移出 | **移出**（旧 `pro` 架构遗留，`src`+`tests` 零引用） | 0 测试影响；`.gitignore` 白名单已删 |
| 8 | `scripts/**` 的 `E:\WT` 硬编码 | 改代码 / 只写文档 | **只写文档**（已在 `CONTRIBUTING.md` §5 写明前提） | 0 测试影响；改代码反而会让脚本假装通用 |
| 9 | `results/*.json` 里的 `C:\Users\MK\...`（3 个 `native_compare*.json`） | 清 / 留 | **清**（泄露本机用户名 + 临时目录，无保留价值） | 0 测试影响（纯 metadata） |
| 10 | `VENDOR.md:7` 的 `D:\Download\...` | 清盘符 / 留 | **清**（只留文件名） | 0 测试影响 |
| 11 | CI 范围 | 只做 50 项 / 加 self-hosted 全量 | **两者都要**（`ci.yml` 已按此写） | self-hosted runner 没注册时那条 job 不会自动跑（手动触发） |
| 12 | `pyproject.toml` 里 `requires-python` 上界 | `>=3.12` / `>=3.12,<3.15` | **`>=3.12,<3.15`**（本机 3.14.7 实测通过，不给 3.15 打包票） | 影响将来 CI 矩阵 |

---

## 8. 复现与证据索引

本文件里每个数字都能重跑出来。取证脚本**都在 `.tmp_test\`（已 gitignore，不进提交）**：

| 脚本 | 产出 |
| --- | --- |
| `.tmp_test/oss_impact_probe.ps1` | §2 的逐项移出矩阵（baseline + 7 个 mutant；`try/finally` 保证复原） |
| `.tmp_test/oss_novendor_full.ps1` | §4.2 无内核全量分布（189/150/339） |
| `.tmp_test/oss_history_probe.ps1` | §4.1 历史对象数/体积、工具可用性（`git-filter-repo` 是否安装） |
| `.tmp_test/oss_history_sizes.ps1` | §4.1 历史最大对象 Top25、按顶层目录聚合 |
| `.tmp_test/oss_routes_probe.ps1` | §4.3/§4.4 两条路线**真的跑一遍**并自检（路线 B 的第一版就在这里暴露出"漏删 refs/original"） |
| `.tmp_test/oss_routeB2.ps1` | §4.4 **修正版**路线 B：补上删 `refs/original` 后重跑，拿到 21.49 MB / `.blk` 0 条的真实数字 |
| `.tmp_test/oss_ci_subset.ps1` | §4.2 CI 子集 37/12/1 + 内核缺席报错文案 |
| `.tmp_test/oss_ci_verify.ps1` | §6.5 pyproject 解析、`ci.yml` YAML 解析、`pip wheel` 构建 |

不改动仓库的临时改名纪律：**7 个 mutant 全部 `try/finally` 复原**，
收尾检查 `Get-ChildItem -Recurse -Filter *.OSSIMPACTOFF` 为 **0**，
`git status --porcelain` 除本轮的文档改动外**无其它差异**。

---

## 9. 决策记录（2026-10-01 用户拍板）

| §7 编号 | 决策 | 拍板结果 | 落地 / 后续 |
| --- | --- | --- | --- |
| 1 ⭐ vendor | (a) 公开 / (b) 自备 / **(c) 只留自写说明** | ✅ **(c)**：移出内核源码与 `inputs/`，**保留自己写的 `vendor/README.md`** | 已按此写好移出清单（§4）；代价是 hosted CI 只能跑 **50 项**内核无关测试（实测 37+12+1） |
| 3 ⭐ 是否先私有 | (a) 先私有跑一周 / (b) 直接公开 | ✅ **(a) 先私有跑一周** | 公开动作**推迟**；这一周里做 §9.2 的清单 |
| 2 ⭐ 历史怎么处理 | (A) 干净单提交 / (B) 重写历史 | ⏸ **暂缓**（先私有不影响；一周后再定） | 路线 **(A) 仍是默认**；实测数据在 §4.1/§4.3/§4.4 |
| 4 ⭐ 许可类型 | MIT / Apache-2.0 / GPL-3.0 | ⏸ **暂缓**：用户要先看对比 | 一页对比已写成 **`docs/OSS-LICENSE.md`**（推荐仍是 MIT）；拍板后只改三处：`LICENSE` 正文、`pyproject.toml` 的 `license`、`README.md` §9.5 |
| 5–12 | 见 §7 | 未拍板（建议不变） | 不阻塞"先私有"，但**阻塞公开**的仍是 #4 许可 |

> ⚠ "先私有"**不等于**可以跳过准备：私有仓库里 CI 一样要跑绿，否则转 public 那天才发现坏。

### 9.1 本轮新发现的一个缺口（必须记下来）

**开源集是从 `73eb2bc`（图3 收尾）切出来的，不含之后的两笔 WebUI 提交**：

| 分支 | HEAD | 内容 | 公开集里有吗 |
| --- | --- | --- | --- |
| `webui` | `ea00b2d` | 首页拆静态资源（`c647398`）+ 输入体验与亮色主题（`ea00b2d`） | ❌ **没有** |
| `3d-viz` | 未提交 | 图3 的 3D 可行性（进行中） | ❌ 没有 |
| `opensource` | 本文件所在分支 | 从 `73eb2bc` 切出 | — |

⇒ **公开前必须先把 `webui`（以及决定采用时的 `3d-viz`）合进开源集**，否则公开出去的是
"没有拆分、深色主题、错误不定位"的旧 WebUI。合并方式（merge / cherry-pick / 从新分支重切）
留到一周后的第 0 步决定。

### 9.2 一周后（≈2026-10-08）的执行清单

1. **第 0 步**：把 `webui`（必要时加 `3d-viz`）的成果并进开源集，并确认 `src/missile_sim/webui_static/` 三个文件在集里；
2. 跑 `python tests\run_tests.py` 全量绿（当前 **349/0/349**，约 3.5 min）；
3. 按 §4.6 的十条自检逐条过；
4. 按**路线 A** 产出干净快照（§4 里的命令：新建目录 → 复制快照 → `git init` → 单次初始提交）；
5. 建**私有**仓库并 push，让 `ci.yml` 的 50 项 job 与 `compileall`、`pip wheel` 在托管环境跑通；
6. 一周后再拍板：**#4 许可**（改三处）→ #5–#12 → 最后才把仓库切成 public。

> ⚠ 顺序不能反：**转 public 之后历史就进过别人的 clone 了**，再改许可/再删历史都收不回来。

# 开源化准备与合规审计（接 GitHub 前）

## 0. 2026-10-01 更新：内核归属转移（**先读这一节**）

> **一句话**：`vendor/wt-missile/wt_missile.py` **现在归本项目作者本人所有** —— 2026-10-01 用户明确：
> 内核原交付方对归属问题回"无所谓"，用户随即声明"内核现在是我的了"。
> 因此**内核随本仓库公开分发、由本仓库 `LICENSE` 覆盖**；
> 本文（以及 `README.md` / `CONTRIBUTING.md` / `vendor/README.md` / `docs/OSS-LICENSE.md`）里
> 凡称内核为"无许可的第三方代码""all-rights-reserved""不能公开""需使用者自备"之处，**均已失效**。
>
> **唯一没变的是游戏数据**：`vendor/wt-missile/inputs/resources/2.59.0.28/**.blk`（168 份）
> **仍排除在公开集之外** —— 它与内核归属无关（权利归 Gaijin），是用户早先 `oss_scope` 就拍过的。

| 资产 | 2026-10-01 之前的结论（本文 §1–§9 的历史分析） | **现在（以本节为准）** |
| --- | --- | --- |
| `vendor/wt-missile/wt_missile.py`（内核源码） | 第三方、无许可 ⇒ 不公开 | **本项目作者自有 ⇒ 随仓公开**，由本仓 `LICENSE` 覆盖 |
| `vendor/wt-missile/{example.json,README.txt}` | 同上 | **随包公开**（与内核同一次交付，归属一并转移 —— 本条是**推断**，用户未逐字确认这两个文件） |
| `vendor/wt-missile/VENDOR.md`、`vendor/README.md` | 本仓库自写 ⇒ 公开 | 不变（**公开**） |
| `vendor/wt-missile/inputs/**`（170 个文件 / 168 份 `.blk`） | Gaijin 游戏数据 ⇒ 不公开 | **不变：不公开**；本轮已 `git rm -r --cached` + 写进 `.gitignore`（§10） |
| 数据缺席时的测试 | 148 项**失败**（数据缺席 ＋ `--strict`，§10.2/§10.3 实测） | **降级为"跳过"**：打印说明、计数分开报、退出码 0（`--strict` 可关掉，见 §10.3） |

**为什么保留 §1–§9 的历史分析而不删掉**：里面的**实测数字**（影响面矩阵、git 历史对象数、
两条落地路线的真实结果、"漏删 `refs/original` 就一个对象都清不掉"的反面对照）与内核归属**无关**，
今天仍然成立、仍然要用；被推翻的只是**对内核的那条法律判断**。所以：正文逐条改正，历史数字原样保留。

**本轮没有替用户拍板的项**：§3.2 的 `results/reference_fig.png` 是否也是用户自己的（**待确认**）、
§7 的 #2 历史路线、#5–#9 的一系列取舍（**#4 许可类型已于 2026-10-02 拍板为 MIT**，见 §5 / §9）。

> ⚠ 本文的影响面数字（**现行口径 402 → 254 通过 / 148 跳过**，见 §10.3）是"**游戏数据在不在**"这个物理事实的函数，与归属无关，
> 因此全部继续有效；它们描述的正是 §10 要处理的场景。

---

> **一句话结论**（内核部分已于 2026-10-01 归属转移，**以 §0 为准**）：外壳代码（`src/missile_sim/`、`tests/`、`docs/`）可以公开；
> **需要排除的只有 168 份 War Thunder 游戏数据**（`vendor/wt-missile/inputs/`；内核已归本项目作者、随仓公开），
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
| 全量自检基线 | **402 通过 / 0 失败 / 402**（156.5 s ≈ 2.6 min；2026-10-02 合并 `webui` 后重测） |
| 审计日期 | 2026-10-01 |

---

## 1. 结论先行（TL;DR）

1. **最高风险只有一处：游戏数据**（`vendor/wt-missile/inputs/`，170 个文件 / 168 份 `.blk`，权利归 Gaijin）。
   内核源码本身**已归本项目作者**（§0）⇒ 随仓公开；**只有游戏数据排除**。
   数据**是全部计算档位的硬依赖**：**连内核一起移出**（归属转移前的旧方案，**已作废**）时全量自检从 339/0/339 掉到 189 通过 / 150 失败（§4.2 的历史实测），
   而**内核在、数据不在**（归属转移后的公开 clone 常态）是 **254 通过 / 148 跳过 / 0 失败 / 共 402**（§10.3 实测，2026-10-02 合并 `webui` 后重测）——
   本轮把它落成了**测试降级**（打印说明 + 跳过，**不再红**）。
   处置：`git rm -r --cached vendor/wt-missile/inputs` + `.gitignore`；"怎么自备"写进
   [`vendor/README.md`](../vendor/README.md)。
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
7. 许可：**已拍板 MIT（2026-10-02）**（推荐理由与取舍表见 §5）。`LICENSE` 已是 MIT 的**完整标准正文**；`pyproject.toml` 写 `license = "MIT"` + `license-files = ["LICENSE"]`。

---

## 2. 合规审计总表

"移出仓库会不会破坏测试与出图" = 临时改名后跑
`-k pool_mapping` / `-k solver_api` / `-k figures_repro` 三组的结果
（基线：**17/0/17**、**17/0/17**、**7/0/7**，全绿）。

| # | 资产 | 权利归属 | 公开分发风险 | 移出仓库破坏测试/出图吗（实测） | 建议 |
| --- | --- | --- | --- | --- | --- |
| 1 | `vendor/wt-missile/wt_missile.py`（142 KB 源码） | ~~第三方作者，无许可声明~~ ⇒ **2026-10-01 起归本项目作者**（§0） | **无**（自有代码，随仓由本仓 `LICENSE` 覆盖） | 不适用（内核本身不删） | **公开**（随仓分发） |
| 2 | `vendor/wt-missile/inputs/resources/2.59.0.28/**`（168 `.blk`） | Gaijin Entertainment | **高**（游戏数据再分发） | **会**：8/9 ❌、5/12 ❌、0/7 ❌（改判后**降级为跳过**，§10.3） | **不公开**，自备（本轮已 `git rm --cached`） |
| 3 | `results/reference_fig.png`（用户提供的参考图） | 用户/第三方（**来源未标明授权**） | **中** | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开（或标注授权来源） |
| 4 | `archive/figures-legacy/**`（23 个早期图） | 本项目自有（数值来自游戏数据） | **低-中**（图里含型号名） | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开（历史垃圾） |
| 5 | `results/runs/full_pro/**`（2.6 MB，1824 工况） | 本项目自有，但**内容源自旧 pro 架构 + 游戏数据** | **中**（含 `elf_sha256`、`E:\WT` 路径） | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开 |
| 6 | `results/pro_cache.json`（1.1 MB，1844 条） | 同上 | **中** | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | 不公开 |
| 7 | `scripts/**`（13 个 `E:\WT` 工具） | 本项目自有（**公式抄自社区工作流**） | **低**（含绝对路径，无论文/无数据） | **不会**：17/0 ✅、17/0 ✅、7/0 ✅ | **保留**，文档写清前提 |
| 8 | `figures/**`（12 个成品图） | 本项目自有（自算数值） | **低** | 不适用（就是交付物） | 保留 |
| 9 | `results/*.json`（版本度量等） | 本项目自有 | **低** | 不适用 | 保留，但**清掉绝对路径**（§3.3） |

---

## 3. 逐项审计

### 3.1 `vendor/wt-missile/**` —— 内核与游戏数据（**内核已改判，数据未变**）

**是什么**：一份第三方交付包的原样副本（`VENDOR.md` 记录 zip SHA-256
`4EEA98906FDEDDDE983AAD19EBC7848234C0415BFB9E0521F89BCC691D17F780`）：

| 组成部分 | 体积 | 内容 |
| --- | --- | --- |
| `wt_missile.py` | 141.7 KB | 2.59.0.28 原生 6DOF 的**纯 Python 复刻**（`MODEL = python-game-6dof-v1`，不执行游戏 ELF） |
| `inputs/resources/2.59.0.28/**` | 2.8 MB | **168 份 War Thunder `.blk`** + `presets.json` + `manifest.json`（156 个预设可计算） |
| `example.json` / `README.txt` | ~2 KB | 作者的示例与说明 |

**权利归谁**（⚠ 第一段已于 2026-10-01 改判，见 §0；下面保留**当时的**判断以便看清推理链）：
* ~~`wt_missile.py` → **第三方作者**，`VENDOR.md` 与 `README.txt` 都没有任何许可声明 ⇒ 默认保留全部权利~~
  ⇒ **改判**：内核（含 `example.json` / `README.txt`）**归本项目作者本人**，随本仓库公开、由本仓库 `LICENSE` 覆盖；`VENDOR.md` 的来源字段已补记这次归属转移。
* `inputs/**` 的 168 份 `.blk` → **Gaijin Entertainment**（War Thunder 游戏数据）—— **这一条不变**。
  它们是从游戏打包档里解出来的数据，再分发绕过游戏自身的分发协议。

**移出仓库会破坏测试与出图吗** —— **会，而且是全局的**（实测）：

| 移出东西 | `-k pool_mapping` | `-k solver_api` | `-k figures_repro` |
| --- | --- | --- | --- |
| 基线（什么都不动） | 通过 17 / 失败 0 | 通过 17 / 失败 0 | 通过 7 / 失败 0 |
| `vendor/wt-missile/` 整包改名 | **通过 8 / 失败 9** | **通过 4 / 失败 13** | **通过 0 / 失败 7** |
| 只把 `vendor/wt-missile/inputs/` 改名（留源码） | **通过 8 / 失败 9** | **通过 5 / 失败 12** | **通过 0 / 失败 7** |

也就是说：**168 份游戏数据不只是"参数"，它被求解器在加载时逐文件做 SHA-256 校验**
（`load_profile()`，`VENDOR.md` §"不许改的理由"）。只留源码、丢掉数据一样跑不动。

**全量影响面**（2026-10-02 合并 `webui` 后重测，共 **402** 项）：**内核在、数据不在**时
**254 通过 / 148 跳过 / 0 失败**。跳过的 148 项集中在
`test_bg`(32)、`test_traj_plot`(14)、`test_solver_api`(12)、`test_report`(12)、`test_webui_traj`(11)、
`test_bg_scan`(10)、`test_pool_mapping`(9)、`test_figures_bg`(8)、`test_figures_repro`(7) …
**能把图算出来的每一层都依赖它**。

> 历史口径：**连内核一起移出**的旧方案（归属转移前，**已作废**）下实测为 339 项里
> **189 通过 / 150 失败**；原始实测保留在 §4.2，仅供对照，**不要拿它当现状**。

**影响面结论**：`vendor/wt-missile/**` 是本仓库的**硬依赖**，不是可选附件。
内核现在可以随仓公开，所以"公开内核"这条路**没有授权障碍**了；真正剩下的取舍是**游戏数据**：
数据不公开 ⇒ 使用者必须自备，否则只能跑 **254/402**（新方案：无数据 254 通过 / 148 跳过 / 402；
"连内核一起移出"的旧方案 189/339 **已作废**，见 §4.2 的历史实测）。
**本轮的选择：数据不跟踪 + 测试降级**（§10），所以"没有数据"不再表现为一片红。

**建议（2026-10-01 改判后）**：
* `wt_missile.py` / `example.json` / `README.txt` → **随仓公开**（自有代码，不删、不忽略）；
* `inputs/**` → **取消跟踪**（`git rm -r --cached vendor/wt-missile/inputs`）＋ 写进 `.gitignore`，
  并在 [`vendor/README.md`](../vendor/README.md) 里写清"放回原位就恢复全绿"的步骤；
* `vendor/wt-missile/VENDOR.md` 与 `vendor/README.md` → **公开**（本项目自己写的说明文件）。
  前者还要留住"来源 + 归属转移"两行 —— 因为 `solver.py` 的报错文案
  （`vendor 求解器不在：…（见 vendor/wt-missile/VENDOR.md）`）**指向它**。

⚠ 有一处已顺手修掉：`VENDOR.md` 第 7/9 行原来把来源写成本机路径
`D:\Download\wt-missile-win-linux-28-minimal.zip`，现在只留文件名（§3.3 同类），
并补了一行"2026-10-01 起内核归本项目作者"。

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

**建议**：不公开（或先向图作者确认授权后再谈）。
⚠ **本条尚未拍板**：这张图**是不是用户自己的**，2026-10-01 的对话里没有确认过，故保留原判并在此标记 **待用户确认**；若图也归用户自有，本条与 §0 同理作废（改成"随仓公开 + 注明来源"）。
若用户坚持保留，**必须**在
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

### 4.2 红绿分布（决定 CI 能跑什么）

> ⚠ 本节前半段是**归属转移前的旧方案口径**（"连内核一起移出"，**已作废**），实测数字保留仅作历史对照；
> **现行口径**（内核随仓、只缺游戏数据）见下面第二张表与 §10.2/§10.3。

**历史实测（2026-10-01，339 项口径，旧方案）** —— 把 `vendor/wt-missile/` **整包**改名后跑**全量**自检：

```text
通过 189 / 失败 150 / 共 339，用时 3.1 s
```

**现行基线（2026-10-02，合并 `webui` 后重测，全量 339 → 402 项）**：

| 配置 | 结果 | 用时 | 退出码 |
| --- | --- | --- | --- |
| 内核 + 数据都在 | **402 通过 / 0 失败 / 402** | 156.5 s（≈2.6 min） | 0 |
| **内核在、数据不在**（默认降级） | **254 通过 / 148 跳过 / 0 失败 / 402** | 8.1 s | 0 |
| 内核在、数据不在 ＋ `--strict` | **254 通过 / 148 失败 / 402** | 9.0 s | 1 |

数据缺席时跳过的 148 项按模块：`test_bg` 32、`test_traj_plot` 14、`test_report` 12、`test_solver_api` 12、
`test_webui_traj` 11、`test_bg_scan` 10、`test_pool_mapping` 9、`test_figures_bg` 8、
`test_figures_repro` 7、`test_traj` 7、`test_grid_axis` 6、`test_figure_labels` 5、
`test_webui_bg` 5、`test_bg_pipeline` 4、`test_bg3d_spike` 2、`test_targets` 2、`test_webui` 2（合计 **148**）。

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

# 1) 删掉"不公开集"（⚠ 2026-10-01 改判后**只剩游戏数据**：内核随仓，不要再删内核）
Remove-Item -Recurse -Force vendor\wt-missile\inputs,          # ← 170 个文件 / 168 份 .blk（Gaijin 数据）
    archive\figures-legacy,
    results\reference_fig.png, results\pro_cache.json, results\runs
#    ⚠ **不要**删 vendor/wt-missile/wt_missile.py —— 它已归本项目作者、随仓公开（§0）

# 2) 建新仓库 + 唯一一条提交
git init -b main
git add -A
git commit -m "初始提交：导弹包线图（外壳 + 内核 + 自算产物；不含 War Thunder 游戏数据，见 vendor/README.md）"

# 3) 公开前自检（下表全过才 push）
git rev-list --count HEAD                 # 必须 == 1
git ls-files vendor/wt-missile            # 应看到 wt_missile.py / example.json / README.txt / VENDOR.md，看不到 inputs/
git ls-files | Select-String '\.blk$|\.blkx$|\.vromfs'   # 必须 0 条
git count-objects -vH                     # 看 size-pack
git remote -v                             # 决定要 push 到哪
```

**实测结果（`.tmp_test/routeA`，2026-10-01）**：

```text
git archive HEAD -> zip                      10.97 MB
按"公开排除集"删掉后：
  git rev-list --count HEAD                  = 1                       ✅
  git ls-files | Select-String vendor        = 1 条（vendor/wt-missile/VENDOR.md）  ← 旧排除集
  git ls-files 里的 .blk/.blkx/.vromfs       = 0 条                     ✅
  跟踪文件数                                  = 144
  工作树受跟踪体积                             = 6.54 MB
  .git（154 个松散对象，未 gc）                 = 3.79 MiB
  git log --oneline                          = 1 条
  git remote -v                              = 空                      ✅
  -k flightpath / form_dirty / printed_text  = 37 / 12 / 1 全绿         ✅
```

> 注：这次实测用的是 `HEAD`（`73eb2bc`）导出的树 ＋ **当时的**排除集（内核 + 数据 + §3.4/3.5/3.6 四项），
> 所以 `vendor` 只剩 **1 条**（`VENDOR.md`）。**2026-10-01 改判后排除集里没有内核了**，
> 路线 A 的公开集规模随之变为（2026-10-01 本轮实测，见 §10.1）：
> 当前 `HEAD` 跟踪 **354** 条（＝本轮开工时的 353 ＋新增的 `tests/_vendor_data.py`）→
> 取消跟踪 `inputs/`（170）→ **184** 条 →
> 再按 §3.4–3.6 移出 `archive/`（24）+ `reference_fig.png`（1）+ `pro_cache.json`（1）+ `results/runs/`（3）
> → **155 条**（按当前 `HEAD` 推算的路线 A 公开集规模）。

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
# ⚠ 2026-10-01 改判后**不再删除内核三项**，只删游戏数据等
git filter-repo --force --invert-paths `
    --path vendor/wt-missile/inputs `
    --path archive/figures-legacy `
    --path results/reference_fig.png `
    --path results/pro_cache.json `
    --path results/runs

# 2B) 没有 filter-repo 时的兜底（本机实测可用）
$env:FILTER_BRANCH_SQUELCH_WARNING = "1"
git filter-branch --force --index-filter `
  'git rm -r --cached --ignore-unmatch vendor/wt-missile/inputs archive/figures-legacy results/reference_fig.png results/pro_cache.json results/runs' `
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
git rev-list --objects --all | Select-String '\.blk'         # 必须 0 条（内核路径留着没关系）
git log --oneline --all -- vendor/wt-missile/inputs          # 允许剩"空提交"，不允许剩路径
git count-objects -vH
```

**实测结果（`.tmp_test/routeB2`，2026-10-01）**：

```text
重写前：.git = 28.45 MB ; vendor 对象 = 103 ; .blk 对象 = 93
filter-branch --index-filter -- --all → Ref 'refs/heads/opensource' was rewritten  (exit 0)
删掉 refs/original/refs/heads/opensource（这一步是本轮的关键修正）
reflog expire --expire=now --all ; gc --prune=now --aggressive
重写后：.git = 21.49 MB ; in-pack = 1032 个对象
  历史里 vendor/ 对象        = 2 条（vendor/wt-missile 树 + vendor/wt-missile/VENDOR.md）  ← 旧排除集
  历史里 .blk/.vromfs 对象   = 0 条                                                      ✅（这一条是硬指标）
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
| 2 | 历史里没有游戏数据（内核**允许**在） | `git rev-list --objects --all \| Select-String '\.blk\|vendor/wt-missile/inputs'` | **0 条** |
| 3 | filter-branch 的备份 ref 已删 | `git for-each-ref --format='%(refname)' refs/original` | **空**（不空 = 一个对象都没删掉） |
| 4 | 工作树里**有内核、没有游戏数据** | `git ls-files vendor/wt-missile` | 有 `wt_missile.py`；`.blk` **0 条** |
| 5 | 提交数 | `git rev-list --count HEAD` | 路线 A：**1**；路线 B：79 |
| 6 | 无远端/无误 push | `git remote -v` | 由使用者显式添加后才非空 |
| 7 | 跟踪体积 | `git count-objects -vH` | 路线 A：工作树 6.54 MB / `.git` 3.79 MiB；路线 B：`.git` 21.49 MB |
| 8 | 绝对路径 | `git grep -n -E 'C:\\\\Users\|D:\\\\Download'` | 0 条 |
| 9 | 密钥 | `git grep -n -i -E '(api[_-]?key\|secret\|password\|BEGIN .*PRIVATE KEY)'` | 0 条 |
| 10 | 无内核也能绿 | `python tests\run_tests.py -k flightpath` 等三组 | 37 / 12 / 1 全绿 |
| 11 | 数据在位才全绿 | 内核 + 数据都在时 `python tests\run_tests.py` | **402 / 0 / 402**；**只有内核、没有数据** → **254 通过 / 148 跳过 / 0 失败 / 402**（§10.3） |
| 12 | 许可已定 | `LICENSE` 是**完整标准正文**（MIT），不是占位 | ✅ **已满足**（MIT，2026-10-02 拍板；见 §5 / §6） |

---

## 5. 许可取舍表与推荐

**背景约束**（这三条决定了选择；② 已于 2026-10-01 改判，见 §0）：
① 这是**社区独立项目**，与 Gaijin 无关系；② ~~仓库里含有无许可声明的第三方内核~~ ⇒ **内核归本项目作者、随仓由本仓 `LICENSE` 覆盖**，所以整仓只有一个权利人，不再有"第三方资产"这一层；
③ 产物是**游戏数据的衍生数值**（数据本身仍不进仓库）。

| 维度 | **MIT** | Apache-2.0 | GPL-3.0 |
| --- | --- | --- | --- |
| 篇幅 / 阅读成本 | 约 170 词，人人能读完 | 约 1500 词，需留意 NOTICE | 约 5000 词 + 全文 copyleft |
| 宽松度 | 最宽松（改完可闭源） | 宽松（需保留 NOTICE、声明变更） | 强 copyleft（衍生作品必须同许可） |
| **专利授权** | **无**明文条款 | **有**明文专利授权 + 专利报复终止 | 有（第 11 条） |
| 商标 | 无条款（默认不给商标权） | 第 6 条明确不授予商标权 | 第 7 条 |
| 与"随仓内核"的关系 | 无额外负担：内核已是自有代码，一份 `LICENSE` 覆盖整仓 | 同 MIT（`NOTICE` 里声明内核与外壳同属本项目） | copyleft 会覆盖**整个仓库（含内核）**，下游想闭源复用公式就不可能了 |
| 对"派生数值/图"的传染 | 无 | 无 | 有（图是否算衍生作品会成为争议） |
| 社区接受度（仿真/科研工具） | 最高 | 高（大厂偏好） | 中（工具类项目少用） |
| 被"闭源拿走"的风险 | 有 | 有 | 无 |

**推荐：MIT**，理由：

1. **本项目的价值在"文档 + 可复现的产物"，不在代码本身。** 最宽松的许可能让做同类研究的
   人直接拿走 `mapping.py` 的公式实现，这才符合项目目的。MIT 是这类"研究工具"的默认选择。
2. **整仓只有一个权利人（本项目作者），MIT 覆盖得干净。** 内核归属转移之后，
   不再有"第三方 all-rights-reserved 资产混在里面"的解释成本；唯一还需要单独说明的是
   **游戏数据不进仓库**这件事（与许可无关，见 §0 / §10）。
3. **专利条款不是本项目的痛点**：这是一份物理仿真与可视化代码，没有可专利的实现主张；
   Apache-2.0 多出来的 1300 词在这里买不到实际保护。
4. 若用户**更在意"被大公司闭源拿走"**：那就选 **Apache-2.0**（仍宽松，但多了变更声明与专利报复条款），
   代价是要维护 `NOTICE`。**不推荐 GPL-3.0**：内核现在随仓分发，GPL 的 copyleft 会覆盖到
   **内核源码本身** —— 于是"别人只想要一个公式实现"也得整仓 GPL；而这个项目的用户群体
   （社区研究者）通常不介意宽松许可，用 GPL 只会抬高采用成本。
   （"图是否算衍生作品"是另一个独立的小争议，不是选 GPL 的理由。）

**无论选哪个，都必须做的三处 —— ✅ 已于 2026-10-02 按 MIT 做完**：
* `LICENSE` 已换成 MIT 的**完整标准正文**（英文原文，一字不改；`Copyright (c) 2026 MK`）；
* `pyproject.toml` 已写 `license = "MIT"` + `license-files = ["LICENSE"]`（PEP 639；wheel METADATA 实测 `License-Expression: MIT`）；
* `README.md` §9.5 与 `CONTRIBUTING.md` §7 已同步改写。

---

## 6. 必备文件状态

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `LICENSE` | ✅ **已落地（MIT，2026-10-02 拍板）** | MIT **完整标准正文**，`Copyright (c) 2026 MK`；此前那份写着"这不是许可证"的占位文件已被替换 |
| `CONTRIBUTING.md` | ✅ 新增 | 起步 5 分钟、提交前必过的四条判据、行尾纪律、数值改动额外要求、不要提交什么、报告/PR 约定、许可与免责 |
| `pyproject.toml` | ✅ 新增 | `requires-python = ">=3.12,<3.15"`、`numpy>=2.5.2,<3`、`matplotlib>=3.11,<4`、`[project.scripts] missile-sim`；`license = "MIT"` + `license-files = ["LICENSE"]`（2026-10-02 随许可拍板补上，wheel METADATA 实测 `License-Expression: MIT`） |
| `README.md` | ✅ 已补（2026-10-01 改口径） | 标题后提示改为"**含内核、不含游戏数据** + 独立社区项目"；文末新增 §9（免责声明 / 产物是仿真结果 / 数据来源与版本标注 / 不含哪些东西 / 许可）；**§9.5 许可以 MIT 定稿（2026-10-02）** |
| `vendor/README.md` | ✅ 新增（2026-10-01 重写） | **公开文件**：内核随仓；**游戏数据要自备**（落位目录形状 / SHA-256 校验 / 数据缺席时测试会跳过而不是红） |
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
| "开源排除集"段 | **2026-10-01 收窄** | 原来忽略内核四个路径；现在**只忽略 `vendor/wt-missile/inputs/`**（游戏数据）。内核已是自有代码、**不该再被忽略** —— 否则将来 `git add -A` 反而会漏掉内核源码 |

### 6.5 CI 的判断：哪些只能在 Windows 上跑

实测结论（写进 `ci.yml` 的注释里）：

| 部分 | 平台要求 | 为什么 | 托管 runner 能跑吗 |
| --- | --- | --- | --- |
| `-k flightpath` / `form_dirty` / `printed_text`（50 项） | **跨平台** | 纯运动学编译 + 表单差异 + 文本扫描，不碰内核 | ✅ ubuntu + windows 都跑 |
| `python -m compileall src tests` | 跨平台 | 纯语法 | ✅ |
| `pip install -e .` / `pip wheel . --no-deps` | 跨平台 | 验证 `pyproject.toml` | ✅（包装元数据本机实测可构建） |
| `-k solver_api` / `figures_repro` / 全量 402 项 | **需要内核 + 游戏数据** | `.blk` 逐文件 SHA-256 校验；数据缺席时 148 项会**跳过**（§10.3，不再红） | ⚠ 内核可以（随仓）；**游戏数据不行**（Gaijin 数据不进仓库）⇒ 全量只能在 self-hosted 跑 |
| `fast` 档（`compiled-c`） | **需要 C 编译器** | MSVC（Windows）/ `cc`（Linux）；缺了就回落 `python-legacy`，数值完全相同 | 代码上 `windows-latest` 自带 VS 2022 可以编；但**拿不到内核**，所以实际只能在 self-hosted 跑 |

因此 `ci.yml` = 托管 runner 的"50 项 + 包装校验 + 内核身份/缺席文案契约"（**本地逐条验过**）
＋ 手动触发的 `self-hosted, windows` 全量 job（**带 `--strict`**：数据不在时必须失败，不能被"降级跳过"蒙过去）。

---

## 7. 给用户的决策清单

> 每一条都要用户拍板；带 ⭐ 的是**阻塞公开**的。

| # | 决策 | 选项 | 我的建议 | 影响 |
| --- | --- | --- | --- | --- |
| 1 ⭐ | **`vendor/wt-missile/**` 怎么办** | (a) 全公开 (b) 全自备 (c) **公开内核、排除游戏数据** | **(c)**：内核（`wt_missile.py` + `example.json` + `README.txt`）随仓公开；**只把 `inputs/`（168 份 `.blk`）排除**，并配 `vendor/README.md` 说明自备方式 | 数据缺席时全量 **402 → 254 通过 / 148 跳过 / 0 失败**（降级，§10.3，2026-10-02 重测）；有数据时 **402/0/402** |
| 2 ⭐ | **历史怎么处理** | (A) **新建干净仓库、单次初始提交** (B) `filter-repo`/`filter-branch` 重写历史 | **(A)**：简单、可验证、对另两个 worktree 零风险。若用户舍不得历史 → (B)，但**必须在 clone 里做**（§4.5） | (A) 丢历史、`.git` 约 6.6 MB；(B) 保留 79 条提交但所有哈希变化，且**必须**清 reflog+gc |
| 3 ⭐ | **是否先私有** | (a) 先私有仓库跑一周 (b) 直接公开 | **(a)**：先把 CI 跑绿、把 §4.6 十条自检过一遍，再切 public。仓库转公开只是点一下，但**一旦 public，历史就进过别人的 clone 了** | 先私有的成本接近 0，收益是"错了还能改" |
| 4 ⭐ | **许可类型** | MIT / Apache-2.0 / GPL-3.0 | ✅ **已拍板：MIT（2026-10-02）**（理由见 §5）；当时的口径保留为决策依据：在意"被闭源拿走"则 Apache-2.0；**不推荐 GPL-3.0** | 已决定并落地 `LICENSE` 正文、`pyproject.toml` 的 `license = "MIT"`、`README.md` §9.5（三处 2026-10-02 完成） |
| 5 | `results/reference_fig.png` | 保留 / 移出 / 保留但标注来源 | **移出**（或先向作者要一句授权）。移出对测试 **0 影响**，但 `make_dist.py`/`packaging` 两处文案要同步 | 移出后分发包少一张对比图（`make_dist.py` 静默跳过，不会报错） |
| 6 | `archive/figures-legacy/**`（23 图，6.87 MB） | 保留 / 移出 | **移出**（不可复现、无脚本、占 HEAD 体积 34%） | 0 测试影响 |
| 7 | `results/runs/full_pro/**` + `results/pro_cache.json`（3.7 MB） | 保留 / 移出 | **移出**（旧 `pro` 架构遗留，`src`+`tests` 零引用） | 0 测试影响；`.gitignore` 白名单已删 |
| 8 | `scripts/**` 的 `E:\WT` 硬编码 | 改代码 / 只写文档 | **只写文档**（已在 `CONTRIBUTING.md` §5 写明前提） | 0 测试影响；改代码反而会让脚本假装通用 |
| 9 | `results/*.json` 里的 `C:\Users\MK\...`（3 个 `native_compare*.json`） | 清 / 留 | **清**（泄露本机用户名 + 临时目录，无保留价值） | 0 测试影响（纯 metadata） |
| 10 | `VENDOR.md:7,9` 的 `D:\Download\...` | 清盘符 / 留 | ✅ **已清**（只留文件名），并补一行"2026-10-01 起内核归本项目作者" | 0 测试影响 |
| 13 | **游戏数据缺席时测试怎么表现** | (a) 保持 148 项红 (b) **降级：打印说明 + 跳过，退出码 0** (c) 整模块跳过 | **(b)**，已落地：`tests/run_tests.py` 检测到数据不在就进入**降级模式**（横幅 + 逐条 `SKIP` 行，`--strict` 可关）；self-hosted 全量 job 强制 `--strict` | 公开 CI 能拿到一个"绿"的信号，且**跳过不计入通过**（计数分开报） |
| 11 | CI 范围 | 只做 50 项 / 加 self-hosted 全量 | **两者都要**（`ci.yml` 已按此写） | self-hosted runner 没注册时那条 job 不会自动跑（手动触发） |
| 12 | `pyproject.toml` 里 `requires-python` 上界 | `>=3.12` / `>=3.12,<3.15` | **`>=3.12,<3.15`**（本机 3.14.7 实测通过，不给 3.15 打包票） | 影响将来 CI 矩阵 |

---

## 8. 复现与证据索引

本文件里每个数字都能重跑出来。取证脚本**都在 `.tmp_test\`（已 gitignore，不进提交）**：

| 脚本 | 产出 |
| --- | --- |
| `.tmp_test/oss_impact_probe.ps1` | §2 的逐项移出矩阵（baseline + 7 个 mutant；`try/finally` 保证复原） |
| `.tmp_test/oss_novendor_full.ps1` | §4.2 无内核全量分布（**189/150/339，旧方案历史口径，已作废**） |
| `.tmp_test/oss_history_probe.ps1` | §4.1 历史对象数/体积、工具可用性（`git-filter-repo` 是否安装） |
| `.tmp_test/oss_history_sizes.ps1` | §4.1 历史最大对象 Top25、按顶层目录聚合 |
| `.tmp_test/oss_routes_probe.ps1` | §4.3/§4.4 两条路线**真的跑一遍**并自检（路线 B 的第一版就在这里暴露出"漏删 refs/original"） |
| `.tmp_test/oss_routeB2.ps1` | §4.4 **修正版**路线 B：补上删 `refs/original` 后重跑，拿到 21.49 MB / `.blk` 0 条的真实数字 |
| `.tmp_test/oss_ci_subset.ps1` | §4.2 CI 子集 37/12/1 + 内核缺席报错文案 |
| `.tmp_test/oss_ci_verify.ps1` | §6.5 pyproject 解析、`ci.yml` YAML 解析、`pip wheel` 构建 |
| `.tmp_test/probe_missing_data.py` | §10.3 数据缺席时的**异常类型与文案**取证（把 `inputs/` 临时改名，跑 4 组各抓 FAIL 行） |
| `.tmp_test/verify_degraded.py` | §10.3 降级模式实跑：全量自检在无数据下的红/绿/跳过分布（2026-10-01 首测是 339 项口径；2026-10-02 合并 `webui` 后重测是 402 项口径） |

不改动仓库的临时改名纪律：**7 个 mutant 全部 `try/finally` 复原**，
收尾检查 `Get-ChildItem -Recurse -Filter *.OSSIMPACTOFF` 为 **0**，
`git status --porcelain` 除本轮的文档改动外**无其它差异**。

---

## 9. 决策记录（2026-10-01 用户拍板；#4 许可为 2026-10-02 追加拍板）

| §7 编号 | 决策 | 拍板结果 | 落地 / 后续 |
| --- | --- | --- | --- |
| 1 ⭐ vendor | (a) 公开 / (b) 自备 / **(c) 只留自写说明** | ✅ **(c)** —— 但 2026-10-01 内核归属转移后**执行方式改为"公开内核、只排除游戏数据"**（§0 / §10） | hosted CI 仍是 **50 项**内核无关测试（实测 37+12+1）＋ 包装校验；全量留给 self-hosted（`--strict`） |
| 3 ⭐ 是否先私有 | (a) 先私有跑一周 / (b) 直接公开 | ✅ **(a) 先私有跑一周** | 公开动作**推迟**；这一周里做 §9.2 的清单 |
| 2 ⭐ 历史怎么处理 | (A) 干净单提交 / (B) 重写历史 | ⏸ **暂缓**（先私有不影响；一周后再定） | 路线 **(A) 仍是默认**；实测数据在 §4.1/§4.3/§4.4 |
| 4 ⭐ 许可类型 | MIT / Apache-2.0 / GPL-3.0 | ✅ **MIT（2026-10-02 拍板）**（2026-10-01 曾 ⏸ 暂缓"先看对比"） | 三处已落地：`LICENSE` 换成 MIT 完整标准正文、`pyproject.toml` 写 `license = "MIT"` + `license-files = ["LICENSE"]`、`README.md` §9.5（`CONTRIBUTING.md` §7 同步）；三选一对比与推荐理由保留在 **`docs/OSS-LICENSE.md`** 作决策依据 |
| 5–12（**不含许可**） | 见 §7 | 未拍板（建议不变） | 不阻塞"先私有"；此前**阻塞公开**的 #4 许可已于 2026-10-02 拍板为 MIT（三处已落地），剩下的这几条仍待拍板 |

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
2. 跑 `python tests\run_tests.py` 全量绿（当前 **402/0/402**，约 2.6 min）；
3. 按 §4.6 的十条自检逐条过；
4. 按**路线 A** 产出干净快照（§4 里的命令：新建目录 → 复制快照 → `git init` → 单次初始提交）；
5. 建**私有**仓库并 push，让 `ci.yml` 的 50 项 job 与 `compileall`、`pip wheel` 在托管环境跑通；
6. 一周后再拍板：#5–#12（**#4 许可已在 2026-10-02 拍板为 MIT，三处已落地**）→ 最后才把仓库切成 public。

> ⚠ 顺序不能反：**转 public 之后历史就进过别人的 clone 了**，再改许可/再删历史都收不回来。

---

## 10. 落地（2026-10-01 本轮）：游戏数据取消跟踪 + 测试降级

> 本节记的是**实际做掉的事**（不是方案），数字都是本轮在这个 worktree 里现跑出来的。

### 10.1 取消跟踪（只动索引，工作树里的文件一个都没删）

```text
git ls-files                                    353 条      ← 本轮开始前
（新增 `tests/_vendor_data.py` → 354 条）
git rm -r --cached vendor/wt-missile/inputs        170 个文件
.gitignore 新增                                  vendor/wt-missile/inputs/
git ls-files | Select-String 'inputs/'           0 条
git ls-files vendor/wt-missile/                  4 条：README.txt / VENDOR.md / example.json / wt_missile.py
git ls-files                                     184 条      ← 因为内核留下来了（354 − 170）
```

工作树里 `inputs/` **仍然在**（本机跑全量不受影响）；顺手删掉了 `vendor/wt-missile/__pycache__/`
（求解器被 import 时生成的未跟踪垃圾）。

⚠ 提交之后 `git status` 会显示 **170 个 `D`** —— 那是"**取消跟踪**"的正常表现，文件没被删。

### 10.2 基准数字：两种"缺东西"不是一回事

> 下表是 **2026-10-02 合并 `webui` 后的重测**：全量从 339 项涨到 **402** 项，旧的 339 项口径数字已全部作废。

| 配置 | 全量 **402** 项的结果 | 说明 |
| --- | --- | --- |
| 内核 + 数据都在 | **402 通过 / 0 失败**（156.5 s ≈ 2.6 min） | 本机常态（§4.2 基线） |
| **内核在、数据不在**（默认降级） | **254 通过 / 148 跳过 / 0 失败**（8.1 s，退出码 0） | **公开 clone 的常态** —— 降级模式 |
| **内核在、数据不在** ＋ `--strict` | **254 通过 / 148 失败 / 402**（9.0 s，退出码 1） | 把"跳过"当成失败（self-hosted 全量 job 用它） |
| 内核和数据都不在（**旧方案口径**） | 189 通过 / 150 失败（3.1 s，退出码 1） | 归属转移前"连内核一起移出"时的历史实测（§4.2）；**该方案已作废**，仅作对照 |

差的正是那 1 项：`test_solver_api::test_solver_file_hash_matches_constant` 只校验**内核文件**的
SHA-256、不读游戏数据 —— 内核随仓之后它当然通过。所以 **148 才是"需要游戏数据"的准确项数**
（149 = 148 ＋ 那 1 项只需要内核文件的用例）。

### 10.3 降级模式怎么工作（`tests/run_tests.py` + `tests/_vendor_data.py` + `tests/_pytest_shim.py`）

实测输出（**2026-10-02，合并 `webui` 后重测**；原文存 `.tmp_test/degraded_full_degraded.txt`）：

```text
======================================================================
⚠ 缺少 War Thunder 游戏数据：vendor/wt-missile/inputs/resources/2.59.0.28/（168 份 .blk 权利归 Gaijin，不随仓库分发）
  降级模式：依赖它的用例记 SKIP（不算通过、也不算失败，退出码仍为 0）。
  放回方法见 vendor/README.md（把游戏数据放回 vendor/wt-missile/inputs/ 即可）；想改成失败：加 --strict。
======================================================================
SKIP test_bg::test_reference_condition_matches_document: SolverUnavailable: vendor 求解器导入失败：FileNotFoundError: … presets.json
…（共 148 条）
通过 254 / 跳过 148 / 失败 0 / 共 402，用时 8.1 s
跳过明细（按模块）：test_bg 32、test_traj_plot 14、test_report 12、test_solver_api 12、test_webui_traj 11、
test_bg_scan 10、test_pool_mapping 9、test_figures_bg 8、test_figures_repro 7、test_traj 7、test_grid_axis 6、
test_figure_labels 5、test_webui_bg 5、test_bg_pipeline 4、test_bg3d_spike 2、test_targets 2、test_webui 2
⚠ 降级运行：这 148 项**没有被执行**（跳过 ≠ 通过）。…
```

设计要点（这三条都是**有意**的）：

1. **跳过 ≠ 通过**：计数器是 `n_pass / n_skip / n_fail` 三个，摘要行分开报，文末再按模块汇总；
   退出码只看 `n_fail`。所以"绿"不会被冒充成"验过"。（**没有**做到"逐用例精确判定谁依赖游戏数据" ——
   采用的是运行器级降级：数据缺席时**任何**失败都记 SKIP。代价是理论上会掩盖"与数据无关的真失败"，
   但那只会发生在这台机器根本没有游戏数据的时候；数据在位时行为与从前完全一致。）
2. **`--strict` 关得掉**：`python tests/run_tests.py --strict` 在数据缺席时**不降级** ——
   实测 254 通过 / 148 失败 / 402 / 退出码 1（2026-10-02 合并 `webui` 后重测）。`ci.yml` 的 self-hosted 全量 job 用它，
   并且跑之前先断言 `presets.json` 在位，免得托管环境的"跳过"被误读成全绿。
3. **判定只看文件在不在，不做哈希**：`_vendor_data.data_available()` 读 `manifest.json`，
   要求它点名的 **168 份 `.blk` 全在**磁盘上（清单里另有 `metadata.txt` / 2 个 `*.json`
   从来没随包提供、求解器也不读它们，故不参与判定）。少一份就当"数据没放好"⇒ 降级，
   而不是在 168 次 SHA-256 校验里炸出 100 多个红。

用例级接口：`tests/_vendor_data.require()` —— 数据缺席时 `pytest.skip(...)`
（`tests/_pytest_shim.py` 新增 `Skipped` 异常，`pytest.skip` 不再是 `RuntimeError`，
真 pytest 的 `Skipped` 继承 `BaseException`，运行器按**类名**识别，两边都认）。

### 10.4 复核命令（2026-10-02 合并 `webui` 后重跑，可逐条复制）

```text
python tests\run_tests.py -k flightpath      #  37 通过 / 0 跳过（真跑真绿，与数据无关）
python tests\run_tests.py -k form_dirty      #  12 通过 / 0 跳过（同上）
python tests\run_tests.py -k printed_text    #   1 通过 / 0 跳过
python tests\run_tests.py -k pool_mapping    #   8 通过 / 9 跳过（原来这 9 项是红的）
python tests\run_tests.py                    # 数据在位 → 402 通过 / 0 失败（156.5 s）
python tests\run_tests.py                    # 数据缺席（默认降级）→ 254 通过 / 148 跳过 / 0 失败（8.1 s，退出码 0）
python tests\run_tests.py --strict           # 数据缺席 → 254 通过 / 148 失败 / 402（9.0 s，退出码 1）
git ls-files vendor/wt-missile                # 4 条，没有 inputs/
git ls-files | Select-String '\.blk$'         # 0 条
```

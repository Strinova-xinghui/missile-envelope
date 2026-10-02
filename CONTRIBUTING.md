# 贡献指南（CONTRIBUTING）

感谢你愿意搭把手。这个仓库是**一个人也能看懂、一个人也能跑起来**的研究工具，
所以贡献流程刻意保持轻：**没有 CLA、没有 DCO 签名、没有强制 PR 模板**。

> ⚠ **先读这一节再看代码**：本公开仓库**含求解器内核、但不含 War Thunder 游戏数据**。
> 内核（`vendor/wt-missile/wt_missile.py`）自 2026-10-01 起归**本项目作者本人**所有，
> 随仓分发、由本仓库 `LICENSE` 覆盖；它硬依赖的 **168 份 `.blk` 游戏数据**
> （`vendor/wt-missile/inputs/`，权利归 Gaijin）**不进仓库**。
> 数据缺席时测试**不会红**：需要它的用例打印一行说明后**跳过**（有内核、无数据时
> 全量 402 项 = **254 通过 / 148 跳过 / 0 失败**（实测 2026-10-02，合并 webui 后重测），见
> [`docs/OPENSOURCE-READINESS.md`](docs/OPENSOURCE-READINESS.md) §10.3）。
> 游戏数据的落位目录与哈希校验见 [`vendor/README.md`](vendor/README.md)。

---

## 1. 起步（5 分钟）

```powershell
git clone <this-repo> missile-sim
cd missile-sim

# 1) 内核已在仓库里。把**游戏数据**放回 vendor/wt-missile/inputs/（见 vendor/README.md）
#    落位后应存在 vendor/wt-missile/inputs/resources/2.59.0.28/presets.json

# 2) 依赖：只有 numpy + matplotlib（Python 3.12+）
python -m pip install -e .

# 3) 自检 —— 不需要装 pytest
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python tests\run_tests.py                                 # 全量 402 项，约 2.6 分钟
python tests\run_tests.py -k flightpath                    # 37 项，约 1 s，**不需要内核**

# 4) 出图
python -m missile_sim --no-iso --tag probe                 # 秒级：只出散点
python -m missile_sim                                      # 图1（约 25 s）
```

Linux / macOS 把 `$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"` 换成
`PYTHONUTF8=1 PYTHONPATH=src` 即可，其余命令一致（内核在 Linux 已实测；Windows 原生
由本仓库使用者验证）。

### 1.1 内核没到位时会看到什么

这是**预期行为**，不是 bug：

```text
missile_sim.solver.SolverUnavailable: vendor 求解器不在：<repo>/vendor/wt-missile/wt_missile.py
（见 vendor/wt-missile/VENDOR.md）
```

此时能跑的是 `-k flightpath` / `-k form_dirty` / `-k printed_text` 这三组
（纯运动学编译、WebUI 表单差异、文案扫描，共 50 项），以及 `python -m compileall`。

---

## 2. 提交前必须过的四条

| # | 判据 | 命令 |
| --- | --- | --- |
| 1 | 全量自检绿 | `python tests\run_tests.py`（当前基线 **402 / 0 / 402**） |
| 2 | 行尾没被重写 | `git diff --stat` 与 `git diff -w --stat` **一致** |
| 3 | 改完立刻 import 一次 | `python -c "import missile_sim.figures, missile_sim.cli"` |
| 4 | 只 stage 本阶段碰过的文件 | `git status --porcelain` 逐行看一遍 |

第 2 条不是洁癖：`.gitattributes` 锁了 `* -text`，本仓库的行尾**本来就是混的**
（`README.md` 是 CRLF，`AGENTS.md`/`docs/`/`src/` 是 LF，`NOTES.md` 里有 1~2 个 CR 的连续串）。
`.gitattributes` 与行尾纪律的完整说明见 [`AGENTS.md`](AGENTS.md)「Version Control」。

⚠ **`NOTES.md` 只能字节追加**（`open("ab")`）。用编辑器整篇保存会把 CR 串折叠掉，
diff 会变成整个文件，评审时什么都看不出来。

---

## 3. 提交信息风格

中文，**一行摘要 + `-` 项目符号正文**，照 `git log` 里既有的样子：

```text
图3：锚点用一遍法反求开机时刻

- 新增 traj.find_anchor()：在不含 39 腿的轨迹上求首次 range <= lockDistance
- 两遍法实测 PL-12 / 50 km：t_beam = 34.458 s（该行 range = 15989.97 m，不插值）
- 测试：tests/test_traj.py 新增 7 项；全量 402/0/402
```

一个可交付阶段一次提交。不要在一个提交里混"重构 + 改数值 + 重出产物"。

---

## 4. 数值类改动的额外要求

这个仓库的产物（`figures/`、`results/`）**逐字节可复现**，所以改数值要给出**代价与证据**：

* **改了会打到屏幕/进产物的文案**：跑 `python tests\run_tests.py -k printed_text`，
  并确认 `figures/*.svg` 与 `results/*.json|csv` 里 `**` 计数为 0
  （`figures._plain()` 只兜"出图"一条路径，manifest / CLI help / WebUI hint **没人兜**）。
* **改了 `Scene` 语义或 `Scaling` 的构成**：`engine.CACHE_SCHEMA` 必须 `+= 1`，
  否则新工况会命中语义完全不同的旧结果，而且**看起来一切正常**。
* **改了出图样式**：`-k figures_repro` 必须过；`SVG_HASH_SALT` 与
  `normalize_svg_ids()` 的正则要一起看（两处都动过才踩出过"同一进程连跑两次 id 不同"）。
* **改了给内核注入 blk 里的字段**：跑 `tests/test_bg_scan.py`。`_patch_profile()` 的
  `walk()` 只遍历已存在的键，注入**未定义字段是静默 no-op** —— 结果照样出、图照样画，
  只是物理没变。
* **测出来的数**：报告数字时**必须带来源版本**（`WORK` = 2.59.0.11 / git tag / blk 现算），
  字段相关性**不等于**引擎公式证明。

完整清单（这份清单本身是被坑出来的）见 `AGENTS.md` 的三个 ⚠ 段。

---

## 5. 不要把什么提交进来

| 不要提交 | 为什么 |
| --- | --- |
| `vendor/wt-missile/inputs/**`（168 份 `.blk` + `presets.json` + `manifest.json`） | **War Thunder 游戏数据**，权利归 Gaijin；已 `git rm -r --cached` + 写进 `.gitignore`，见 `docs/OPENSOURCE-READINESS.md` §0/§10 |
| ~~`vendor/wt-missile/wt_missile.py` 等内核文件~~ | **不是要排除的**：内核自 2026-10-01 起归本项目作者，**随仓公开**、由 `LICENSE` 覆盖（原先"无许可声明"的判断已作废） |
| War Thunder 的原始游戏文件（`.vromfs.bin_u`、`*.blkx`、`WT.xlsx`、ELF/`.so`） | 同上；本仓库**只**保留自己算出来的数值与图 |
| `results/cache/`、`results/runs/<临时 run>` | 可重建的缓存 |
| 任何 `E:\WT`（或其它本机挖掘仓库）下的内容 | 那是外部只读参考数据，不属于本仓库 |

`scripts/` 里对 `E:\WT` 的**硬编码绝对路径是故意的**：它们是一条"数据出处链"考古工具，
需要本机有 War Thunder 数据挖掘仓库。这部分**不打算改成可配置**，只在文档里写清前提。

---

## 6. 报告问题 / 提 PR

* Issue 里请带上：`python -m missile_sim --no-iso --tag probe` 产出的
  `results/plane_probe.json`（里面有 `backend` / `fallback_reason`，能一眼看出你吃的是
  C 内核还是回落档），以及 `python tests\run_tests.py` 的末行统计。
* PR 请**一个主题一个 PR**。改动面越大，越需要把"为什么"写在提交正文里。
* 无法在本机验证的部分（例如没有 C 编译器、没有游戏数据）**直说**，
  这比"看起来绿了"有用得多。

---

## 7. 许可与免责

* 贡献即表示你有权提交这份内容，并同意按本仓库的许可（**MIT**，2026-10-02 拍板；正文见根目录
  [`LICENSE`](LICENSE)，取舍表见 [`docs/OSS-LICENSE.md`](docs/OSS-LICENSE.md)）分发。
  ⇒ 请只提交你自己**有权再许可**的内容：不要贴入来源不明或带限制性许可的代码/数据/图片
  （外部参考图、抓取来的数据集、非 OFL/非宽松许可的字体都算）。
  注意 `vendor/wt-missile/wt_missile.py`（内核）与 `src/missile_sim/**` **同属本项目作者**，
  不是第三方代码；本仓库里唯一的外部权利是 `vendor/wt-missile/inputs/**`（Gaijin 游戏数据，已排除）。
* 本项目是**独立社区研究项目**，与 Gaijin Entertainment / War Thunder
  没有任何隶属、赞助或背书关系。详见 [`README.md`](README.md) 的免责声明一节。

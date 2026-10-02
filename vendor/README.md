# vendor/ —— 求解器内核（**随本仓库分发**）与游戏数据（**要你自备**）

这个目录放求解器内核：本仓库全部计算档位（`standard` / `fast`）都由它提供。
**内核源码随仓库公开**；它硬依赖的 **War Thunder 游戏数据不随仓库公开**，clone 之后要自己放回来。

## 两部分的归属不同（2026-10-01 起）

| 内容 | 权利 | 随本仓库公开吗 |
| --- | --- | --- |
| `wt_missile.py`（约 142 KB 源码） | **本项目作者本人**（2026-10-01 归属转移，原交付方对此回"无所谓"）⇒ 由本仓库根目录的 `LICENSE` 覆盖 | ✅ **随仓**（连同 `example.json` / `README.txt`） |
| `inputs/resources/2.59.0.28/`（168 份 `.blk` + `presets.json` + `manifest.json`） | **Gaijin Entertainment**（War Thunder 游戏数据） | ❌ **不随仓**（`git rm -r --cached` + 写进 `.gitignore`） |
| `VENDOR.md` / `README.md`（本文件） | 本仓库自己写 | ✅ 随仓 |

所以：**"没有内核"已经不再是本仓库的状态** —— 你 clone 下来就有内核；
缺的只有内核**运行时**要读的那 168 份游戏数据。归属转移的完整记录见
[`../docs/OPENSOURCE-READINESS.md`](../docs/OPENSOURCE-READINESS.md) §0。

## 为什么游戏数据不随仓

`.blk` 是从游戏打包档里解出来的资源，权利归 Gaijin，公开再分发绕过游戏自身的分发协议。
它与内核归属无关，也**与选哪个许可无关** —— 这是本仓库唯一一件"永远要排除"的东西。

## 落位步骤（只放游戏数据）

把游戏数据解到 **`vendor/wt-missile/inputs/`**，最终目录形状必须是（大小写与层级都不能改）：

```text
vendor/
└── wt-missile/
    ├── wt_missile.py                    ← 内核源码：**本来就有**（随仓）
    ├── example.json
    ├── README.txt
    ├── VENDOR.md                        ← 本仓库自己的说明文件
    ├── README.md                        ← 本文件（在上一级 `vendor/README.md`）
    └── inputs/                          ← ⚠ **需要你放回来的**（本仓库不含）
        └── resources/
            └── 2.59.0.28/               ← 168 份 .blk + presets.json + manifest.json
```

### 身份校验（先对哈希，再谈结果）

| 项 | 期望值 |
| --- | --- |
| `wt_missile.py` SHA-256 | `dad09caea2c31e0ef26a8327f3bb96c50f83b91bcb29d6b05616f23faba2f730` |
| 资源归档 | 2.59.0.28，168 份 blk、156 个预设可计算 |
| 建模身份 | `MODEL = "python-game-6dof-v1"`（2.59.0.28 原生 6DOF 的纯 Python 复刻，**不执行游戏 ELF**） |

```powershell
# 源码哈希（Windows）
(Get-FileHash vendor\wt-missile\wt_missile.py -Algorithm SHA256).Hash.ToLower()

# Linux / macOS
sha256sum vendor/wt-missile/wt_missile.py
```

哈希不符、或数据里少/多一个文件时，求解器会**硬拒绝**（`Resource identity mismatch` /
`SolverUnavailable`），不会静默降级 —— 这是故意的。升级流程写在
[`wt-missile/VENDOR.md`](wt-missile/VENDOR.md)。

### 落位成功的判据

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python -c "import missile_sim.solver as s; print(s.identity())"   # 应打印内核身份块
python -m missile_sim --list-missiles                              # 11 型 + 现算 ΔV/BC
python tests\run_tests.py -k solver_api                            # 内核身份/哈希/金标工况
python tests\run_tests.py                                          # 全量 402 项，约 2.6 分钟
```

## 游戏数据不在位时会发生什么（**不会红**）

`tests/run_tests.py` 会先检测游戏数据在不在：

* **在** → 正常跑，全量基线 **402 通过 / 0 失败**（156.5 s ≈ 2.6 min）；
* **不在** → 进入**降级模式**：开头打一行横幅，凡是需要游戏数据的用例（148 项）
  逐个打印一行 `SKIP …` 并**跳过**，退出码仍是 **0**。
  实测（2026-10-02 合并 webui 后重测，内核在、数据不在）：**254 通过 / 148 跳过 / 0 失败 / 共 402**（8.1 s）。

跳过**不计入通过** —— 计数是分开报的，所以"绿"不会被冒充成"验过"：

```text
⚠ 缺少 War Thunder 游戏数据：vendor/wt-missile/inputs/resources/2.59.0.28/（168 份 .blk 权利归 Gaijin，不随仓库分发）
  降级模式：依赖它的用例记 SKIP（不算通过、也不算失败，退出码仍为 0）。
  放回方法见 vendor/README.md（把游戏数据放回 vendor/wt-missile/inputs/ 即可）；想改成失败：加 --strict。
SKIP test_bg::test_golden_beta_gamma_q_nstar[key=120A]: SolverUnavailable: vendor 求解器导入失败：FileNotFoundError: … presets.json
通过 254 / 跳过 148 / 失败 0 / 共 402，用时 8.1 s
跳过明细（按模块）：test_bg 32、test_traj_plot 14、test_report 12、test_solver_api 12、test_webui_traj 11、
test_bg_scan 10、test_pool_mapping 9、test_figures_bg 8、test_figures_repro 7、test_traj 7、test_grid_axis 6、
test_figure_labels 5、test_webui_bg 5、test_bg_pipeline 4、test_bg3d_spike 2、test_targets 2、test_webui 2（合计 148）
```

需要"把跳过当成失败"时用 `--strict`（CI 的 self-hosted 全量 job 就是这么跑的）：

```powershell
python tests\run_tests.py --strict    # 数据不在位 -> 148 项失败、退出码 1
```

注意：**完全不碰内核数据的 50 项**在任何情况下都是真跑真绿的：

```text
python tests\run_tests.py -k flightpath     # 37 项  通过 37 / 失败 0
python tests\run_tests.py -k form_dirty     # 12 项  通过 12 / 失败 0
python tests\run_tests.py -k printed_text   #  1 项  通过  1 / 失败 0
```

数据缺席时的报错是**明确**的（实测原文，出现在 `SKIP` 行里）：

```text
missile_sim.solver.SolverUnavailable: vendor 求解器导入失败：FileNotFoundError: [Errno 2]
No such file or directory: '<repo>\vendor\wt-missile\inputs\resources\2.59.0.28\presets.json'
```

## 请不要做的事

* **不要**把游戏数据提交回本仓库（`.gitignore` 已挡，但 `git add -f` 能绕过）。
* **不要**把游戏数据塞进分发包（`make_dist.py`）后公开分发。
* **不要**改 `wt_missile.py` 一个字节：`load_profile()` 对每份 blk 与 `presets.json`
  做 SHA-256 校验，改一字节就抛 `Resource identity mismatch`；而且
  `solver.SOLVER_SHA256` 是外壳里**写死**的，改了它等于换了内核身份。
  （内核**源码本身**现在归本项目作者、可以正常参与开发，但改它属于"换内核"：
  必须同时更新 `solver.SOLVER_SHA256` 与 [`wt-missile/VENDOR.md`](wt-missile/VENDOR.md)。）

# vendor/ —— 求解器内核（**本公开仓库不含，请自备**）

这个目录**只放一份东西**：第三方交付的 War Thunder 6DOF 求解器内核。本仓库的
全部计算档位（`standard` / `fast`）都由它提供。

## 为什么这里现在是空的

内核负载由两部分组成，**两部分都不适合公开再分发**（详细审计见
[`docs/OPENSOURCE-READINESS.md`](../docs/OPENSOURCE-READINESS.md) §3）：

| 内容 | 权利 | 公开分发风险 |
| --- | --- | --- |
| `wt_missile.py`（约 142 KB 源码） | 第三方作者，包内**没有任何许可声明** | **高**：默认保留全部权利（all rights reserved），公开再分发无授权依据 |
| `inputs/resources/2.59.0.28/`（168 份 `.blk` + `presets.json` + `manifest.json`） | Gaijin Entertainment（War Thunder 游戏数据） | **高**：游戏数据被再分发，绕过游戏自身的分发协议 |

所以本仓库只公开**外壳**（`src/missile_sim/`）与**自己算出来的产物**
（`figures/`、`results/`），内核由使用者按下方步骤自备。

## 落位步骤

把内核解到 **`vendor/wt-missile/`**，最终目录形状必须是（大小写与层级都不能改）：

```text
vendor/
└── wt-missile/
    ├── wt_missile.py                    ← 求解器源码，必须存在
    ├── example.json
    ├── README.txt
    ├── VENDOR.md                        ← 本仓库自己的说明文件（公开，保留）
    └── inputs/
        └── resources/
            └── 2.59.0.28/               ← 168 份 .blk + presets.json + manifest.json
```

### 身份校验（先对哈希，再谈结果）

| 项 | 期望值 |
| --- | --- |
| `wt_missile.py` SHA-256 | `1bfa0fa2a3a6d34faa01e4b6ad77e15ba10573ed857bc3362ed368b4e8511890` |
| 资源归档 | 2.59.0.28，168 份 blk、156 个预设可计算 |
| 建模身份 | `MODEL = "python-game-6dof-v1"`（2.59.0.28 原生 6DOF 的纯 Python 复刻，**不执行游戏 ELF**） |

```powershell
# 源码哈希（Windows）
(Get-FileHash vendor\wt-missile\wt_missile.py -Algorithm SHA256).Hash.ToLower()

# Linux / macOS
sha256sum vendor/wt-missile/wt_missile.py
```

哈希不符时求解器会**硬拒绝**（`Resource identity mismatch` / `SolverUnavailable`），
不会静默降级 —— 这是故意的。内核自己的升级流程写在
[`vendor/wt-missile/VENDOR.md`](wt-missile/VENDOR.md)（该文件是本仓库写的，公开保留）。

### 落位成功的判据

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python -c "import missile_sim.solver as s; print(s.identity())"   # 应打印内核身份块
python -m missile_sim --list-missiles                              # 11 型 + 现算 ΔV/BC
python tests\run_tests.py -k solver_api                            # 内核身份/哈希/金标工况
python tests\run_tests.py                                          # 全量 339 项
```

## 没有内核时能做什么

**50 项测试**仍然全绿，它们完全不碰求解器（实测：

```text
python tests\run_tests.py -k flightpath     # 37 项  通过 37 / 失败 0，0.8 s
python tests\run_tests.py -k form_dirty     # 12 项  通过 12 / 失败 0，0.0 s
python tests\run_tests.py -k printed_text   #  1 项  通过  1 / 失败 0，0.0 s
```

而**全量 339 项**在无内核时是 **189 通过 / 150 失败**（2026-10-01 实测，3.1 s；
失败集中在内核、出图与图2/图3 端到端。逐项明细见 `docs/OPENSOURCE-READINESS.md` §4.2）。

内核缺失时的报错是**明确**的（实测原文）：

```text
missile_sim.solver.SolverUnavailable: vendor 求解器不在：<repo>/vendor/wt-missile/wt_missile.py
（见 vendor/wt-missile/VENDOR.md）
```

## 请不要做的事

* **不要**把内核负载提交回本仓库（`.gitignore` 已挡，但 `git add -f` 能绕过）。
* **不要**把内核负载塞进分发包（`make_dist.py`）后公开分发。
* **不要**改 `wt_missile.py` 一个字节：`load_profile()` 对每份 blk 与 `presets.json`
  做 SHA-256 校验，改一字节就抛 `Resource identity mismatch`；而且
  `solver.SOLVER_SHA256` 是外壳里**写死**的，改了它等于换了内核身份。

# vendor/wt-missile —— 求解器内核（只读副本；**2026-10-01 起归本项目作者**）

本目录是**内核交付物的原样副本**，不得改动其中任何文件。

⚠ **归属（2026-10-01）**：本内核已归**本项目作者本人**所有 —— 原交付方对归属问题回"无所谓"，
作者随即声明其归己所有。因此它**随本仓库公开分发、由仓库根目录的 `LICENSE` 覆盖**，
不再是"无许可的第三方代码"。**唯一仍不进仓库的是游戏数据**
（`inputs/resources/2.59.0.28/**`，权利归 Gaijin；见 `vendor/README.md` 与
`docs/OPENSOURCE-READINESS.md` §0）。

| 项 | 值 |
| --- | --- |
| 来源 | `wt-missile-win-linux-28-minimal.zip`（原交付包文件名，本机路径盘符已抹掉）· **2026-10-01 起内核归本项目作者** |
| zip SHA-256 | `4EEA98906FDEDDDE983AAD19EBC7848234C0415BFB9E0521F89BCC691D17F780` |
| 随附说明 | `README.md`（扩写版，含计时研究，随交付包提供，本机路径盘符已抹掉）；包内 `README.txt`（简版） |
| 求解器源码 SHA-256 | `1BFA0FA2A3A6D34FAA01E4B6AD77E15BA10573ED857BC3362ED368B4E8511890` |
| 资源归档标识 | `manifest.json` 的 `archive_sha256`（`303760d4897dd688…`） |
| 型号资源 | 168 份 blk + `presets.json` + `manifest.json`；156 个预设可计算 |
| 建模身份 | `MODEL = "python-game-6dof-v1"` —— 2.59.0.28 原生 6DOF 的纯 Python 复刻 |

源码哈希与包内 README §9 结尾记录的"计时源码 SHA-256"完全一致，确认入库的就是那
一份被测代码。

## 为什么必须入库

仓库的全部计算档位（`standard` / `fast`）都由它提供，而它**硬依赖**同目录下的
`inputs/resources/2.59.0.28/`：`wt_missile.py` 用 `ROOT = Path(__file__).resolve().parent`，
并逐文件核对 `manifest.json` 的 SHA-256。现有信源包
（`E:\WT\wt-missile-backend-runtime-1.0.1\inputs\resources\2.59.0.28`）只有 11 份文件与
本包 manifest 对得上，**不能复用**。

体积：2.97 MB 未压缩；git 压缩后约 0.6 MB。

## 不许改的理由

`load_profile()` 对每份 blk 与 `presets.json` 做 SHA-256 校验，改一个字节就会抛
`Resource identity mismatch`。`wt_missile.py` 的哈希同时用于引擎 `selftest` 与
`EngineStamp.resources`，产物据此自报身份。

## 升级流程

1. 取新的交付 zip，记录新的 zip SHA-256 与源码 SHA-256；
2. **整目录替换**（保持 `wt-missile/` 结构），不要只换 `wt_missile.py`；
3. 更新本文件里的哈希与版本；
4. 跑 `python scripts\pipeline.py models --check` 与 `python tests\run_tests.py`；
5. 若金标数值变化，按 `ModelSpec.calc_version` 的纪律 +1，并重跑受影响的扫描。

## 已知边界（来自包内 `README.txt` 与求解器自报的 `summary.limitations`）

* 不含预编译库、Python、NumPy 或编译器；`fast` 首次运行在本机编译，之后复用缓存
  （Windows `%LOCALAPPDATA%\wt-missile\compiled-fast`；可用 `WT_MISSILE_FAST_CACHE` 改）。
* 不依赖游戏 ELF：`summary.elf_executed == false`，`formula_basis_elf_sha256` 只表示公式
  的**溯源依据**。
* 加载时显式拒绝未移植的外环控制器（`orientationAutopilot` / `orientationAutopilotLeadingMult` /
  `propulsionAutopilot` / `useThrustVectoring`）、重复 `endSpeed`、非恒定 `Cy` 表；
  **不静默降级为质点模型**。
* `fast` 的加速依赖本机 C 编译器；缺编译器时回退 `python-legacy`（原因在
  `summary.fastmode.compiled_fallback_reason` 与 `EngineStamp.resources.backend`）。
* 平台验证范围：Linux 已实测；Windows x64 + MinGW 在 Wine 下验证，**原生 Windows 10/11 未实机验证**。
* 作者要求 `numpy 2.5.3`；本仓库环境为 2.5.2，实测可正常运行。

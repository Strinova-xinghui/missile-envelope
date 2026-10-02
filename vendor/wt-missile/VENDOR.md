# vendor/wt-missile —— 求解器内核（**2026-10-01 起归本项目作者**；2026-10-02 起可本地扩列）

本目录是**内核源码**（本项目作者自有，随本仓库分发）。

⚠ **2026-10-02 起它不再只是"原样副本"**：作者已就地加过输出列（见下面「本地改动记录」）。
**任何改动都要同时做三件事**（漏一件就是"产物的身份在撒谎"）：改本文件 → 更新
`src/missile_sim/solver.py` 的 `SOLVER_SHA256` → 重建 fast 档编译缓存。

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
| 求解器源码 SHA-256 | `DAD09CAEA2C31E0EF26A8327F3BB96C50F83B91BCB29D6B05616F23FABA2F730`（**2026-10-02 加了 3 个输出列**；交付包原样为 `1BFA0FA2…51890`） |
| 资源归档标识 | `manifest.json` 的 `archive_sha256`（`303760d4897dd688…`） |
| 型号资源 | 168 份 blk + `presets.json` + `manifest.json`；156 个预设可计算 |
| 建模身份 | `MODEL = "python-game-6dof-v1"` —— 2.59.0.28 原生 6DOF 的纯 Python 复刻 |
| 输出列 | **68 列**（交付包原样 65 列 + 本地新增 3 列，见下） |

## 本地改动记录（2026-10-02）：输出列 +3（`mach` / `aoa_deg` / `aoa_eff_deg`）

* **谁**：本项目作者（经 Lead 派单、`oss-prep` 落地）。
* **为什么**：用户 2026-10-02 拍板"**修改输出 API 加这三个量以规范化**……**内核本身应该是支持的**"，
  三选一里选的是 **"扩内核输出列"**（而不是"外壳自己派生"或折中）⇒ 目标状态是
  **换内核时新内核必须给出这几列**，外壳不再自己算。
* **改了什么**（只**追加**在 `_CF_COLUMNS` 末尾，既有 65 列的**名字/顺序/单位一个都没动**）：
  | 新列 | 定义 | 单位 | 备注 |
  | --- | --- | --- | --- |
  | `mach` | `|air| / sound(alt)` | 无量纲 | 内核本来就在算这个比值喂 `_mach_function`，只是没输出 |
  | `aoa_deg` | `angle(nose, ûair)` = 运动学攻角 | deg | `acos` 出来的**非负角** `[0,180]` |
  | `aoa_eff_deg` | `angle(nose, ûflow)`，`flow = û(air + R @ [0, lever·ω_z, −lever·ω_y])` | deg | **有效攻角** = `aero()` 实际用的那个 `flow` |
* **两条实现纪律**（都在代码注释里）：
  1. 输出行是**步后**状态，而 C 路 `record()` 里 `m->r` 是**步前**姿态（`body()` 只就地更新 `m->q`）
     ⇒ 新列**就地**用当前 `q` 重算 `R`，否则会差一个步长；
  2. `180/π` 必须写成"**先算常量再乘**"，才与 Python 的 `math.degrees` 逐位一致。
* **没改**：`MODEL`（仍是 `python-game-6dof-v1`）与 `VERSION` —— 物理一步没动
  （旧 65 列在改前/改后**逐位相同**，见 `docs/SOLVER-API.md` §3.1 的判据），
  变的只是**输出 schema**。因此需要升级的消费者是"按下标读列"的那种，不是物理口径。
* **连带动作**：`solver.SOLVER_SHA256` 已同步；`fast` 编译缓存必须重建
  （`_CF_HASH` 随源码变，缓存文件名变）；`docs/SOLVER-API.md` §3.1 已改为"内核输出列"口径。

源码哈希与包内 README §9 结尾记录的"计时源码 SHA-256"**在交付包原样状态**完全一致
（`1BFA0FA2…1890`），确认入库的就是那一份被测代码。⚠ **2026-10-02 扩列之后不再一致** ——
新哈希见上表；需要交付包原样那一份时用 `git show 91601e3:vendor/wt-missile/wt_missile.py`
取回（本轮的不变性比对就是这么做并逐位核过的：2170 行 × 既有 65 列，0 处差异）。

## 为什么必须入库

仓库的全部计算档位（`standard` / `fast`）都由它提供，而它**硬依赖**同目录下的
`inputs/resources/2.59.0.28/`：`wt_missile.py` 用 `ROOT = Path(__file__).resolve().parent`，
并逐文件核对 `manifest.json` 的 SHA-256。现有信源包
（`E:\WT\wt-missile-backend-runtime-1.0.1\inputs\resources\2.59.0.28`）只有 11 份文件与
本包 manifest 对得上，**不能复用**。

体积：2.97 MB 未压缩；git 压缩后约 0.6 MB。

## 改动代价（不是"不许改"）

`load_profile()` 对每份 blk 与 `presets.json` 做 SHA-256 校验，改**数据**一个字节就会抛
`Resource identity mismatch`（数据本身仍然只读）。`wt_missile.py` 的哈希同时用于引擎
`selftest` 与 `EngineStamp.resources`，产物据此自报身份 —— 所以改**源码**可以，但必须同步哈希
（见开头那三件事）并重建 `fast` 编译缓存，否则产物会在身份栏里撒谎。

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

# Win / Linux 单文件导弹计算器 · 2.59.0.28

这个包用于离线计算导弹飞行轨迹。计算代码集中在 `wt_missile.py`，同一份代码可在 Windows 和 Linux 使用；导弹参数保存在外部资源目录。

默认使用标准模式；添加 `--fastmode` 或在 Python 调用中设置 `fastmode=True`，可使用本地 C 编译加速。fast 保留逐物理步计算和完整轨迹输出，允许部分浮点算术近似，不保证与标准结果逐位相同。

## 1. 包里有什么

```text
wt-missile/
├── wt_missile.py
├── example.json
├── README.md
└── inputs/resources/2.59.0.28/
    ├── presets.json
    ├── manifest.json
    └── gamedata__weapons__rocketguns__*.blk
```

包含 `.28` 目录内全部 **168 份型号资源，其中 156 个预设可计算**。其余型号会给出拒绝原因，不会自动换成另一种导弹。这个精简包只发布 `.28` 资源及目录，不提供 `.22` 计算。

请保留上述相对目录。资源文件使用原始校验和核对，直接修改 BLK 会触发身份不匹配；不要为了绕过报错删除校验。

## 2. 安装

需要 Python 3.12+ 和 NumPy 2.5.3。标准模式不需要 C 编译器；编译 fast 第一次运行需要编译器，后续复用本机缓存。

### Linux

进入解压目录，用实际运行计算器的那个 Python 安装依赖：

```bash
python3 -m pip install numpy==2.5.3
python3 -X utf8 wt_missile.py example.json --output result.json
```

如系统要求虚拟环境，可先执行 `python3 -m venv .venv`，然后用 `.venv/bin/python` 替代上面的 `python3`。使用 fast 前，确认 `cc --version` 能正常执行；如果没有编译器，通过所用发行版安装 GCC 或等效 C 编译工具。

### Windows

推荐 **64 位 Python + 64 位 MinGW-w64**。本轮实际验证工具链是 [w64devkit 2.10.0](https://github.com/skeeto/w64devkit/releases/tag/v2.10.0)，建议解压到 `C:\w64devkit`。编译器自身使用英文安装路径；计算器、输入文件和缓存可以放中文路径。

进入解压目录，在 PowerShell 中执行：

```powershell
py -m pip install numpy==2.5.3
$env:PATH = "C:\w64devkit\bin;" + $env:PATH
py -X utf8 wt_missile.py example.json --fastmode --output result-fast.json
```

如果你的 Python 命令是 `python`，把 `py` 换成 `python`。`PATH` 这条命令只影响当前 PowerShell；新开窗口需要再次设置，或自行将工具链加入用户 PATH。

已有 Visual Studio C++ 工具和 Windows SDK 的用户，也可以在 x64 Native Tools Command Prompt 中执行 `set CC=cl`，再运行计算器。较新 MSVC 的 C11 编译命令已适配，但本轮未实际运行 MSVC 工具链，建议优先选择上述 MinGW 路线。

**平台验证范围：Linux 已实测；Windows x64 Python + MinGW 已在 Wine 下完成 DLL 编译、加载、中文路径、缓存和计算验证，尚未在原生 Windows 10/11 实机验证。** Python 与编译器的架构需要一致。

## 3. 常用命令

下面统一写作 `python`，按系统替换为 `python3`、`py` 或虚拟环境内的 Python。

```bash
# 标准模式，保存完整结果
python -X utf8 wt_missile.py example.json --output result.json

# fast 模式
python -X utf8 wt_missile.py example.json --fastmode --output result-fast.json

# 同时导出 CSV、轨迹 JSON、摘要和终止状态
python -X utf8 wt_missile.py example.json --fastmode --output result-fast.json --save-dir result-files

# 查看型号标识、可计算状态及拒绝原因
python -X utf8 wt_missile.py --list-missiles --output missiles.json

# 帮助
python wt_missile.py --help
```

`--save-dir` 目录中包含 `scenario.json`、`summary.json`、`trajectory.csv`、`trajectory.json`、`event.json`。文件输出采用 UTF-8，输入 JSON 接受 UTF-8 BOM。

省略 `--output` 时，完整 JSON 会写入终端；长轨迹建议直接输出文件。`--format auto` 是默认值，也可以显式指定 `--format calculator` 或 `--format scenario`。

没有 `--fastmode` 时，会使用输入 JSON 中的 `fastmode` 值；输入也没指定时才默认标准模式。要确保标准计算，可将 JSON 的 `fastmode` 设为 `false`，或在 Python API 中明确传 `fastmode=False`。

## 4. 简单输入：修改 example.json

最容易上手的方式是复制 `example.json`，只修改需要的数值。以下是完整合法示例：

```json
{
  "missile": "cn_pl12",
  "version": "2.59.0.28",
  "duration_s": 30,
  "launch_speed_kmh": 1200,
  "launch_altitude_m": 3000,
  "launch_pitch_deg": 0,
  "launch_yaw_deg": 0,
  "target_speed_kmh": -200,
  "target_altitude_m": 2000,
  "target_distance_m": 20000,
  "target_bearing_deg": 0,
  "target_heading_deg": 0,
  "target_turn_g": 0,
  "target_pitch_deg": 0
}
```

下面 11 个数值字段都必须提供，即使值为零也不要删除：

| 字段 | 含义与单位 |
|---|---|
| `launch_speed_kmh` | 导弹初始速度，km/h，非负 |
| `launch_altitude_m` | 初始高度，m，平地以上 |
| `launch_pitch_deg` | 初始俯仰角，度；正值抬头 |
| `launch_yaw_deg` | 初始偏航角，度 |
| `target_speed_kmh` | 目标速度，km/h；允许负值 |
| `target_altitude_m` | 目标初始高度，m |
| `target_distance_m` | 初始三维斜距，m，不是水平距离 |
| `target_bearing_deg` | 目标初始位置方位角，度 |
| `target_heading_deg` | 目标速度航向，度 |
| `target_turn_g` | 恒定水平转弯的向心加速度，单位 g；0 为不转弯 |
| `target_pitch_deg` | 目标速度的垂直角度，度 |

可选字段：`missile` 默认 `cn_pl12`；`version` 默认 `2.59.0.28`；`duration_s` 默认资源寿命；`fastmode` 默认 `false`；`dt_s` 默认约 0.020833334 秒；`motor_start_times_s` 可指定发动机点火弹龄列表。日常使用建议保留默认物理步长和点火设置。

坐标是 **x/z 水平、y 向上**；零航向沿 +x，正航向转向 +z。目标负速度会反转整个速度向量，例如零航向、速度 -200 km/h 表示向 -x 运动。`target_turn_g` 的正值向 +z 方向改变航向，它表示水平向心加速度，不是飞机气动模型的载荷因数。

`target_distance_m` 不能小于发射高度与目标高度之差的绝对值。所有角度都在同一固定世界坐标中定义。

## 5. 高级输入：直接指定初态和目标轨迹

需要风、已有飞行初态、四元数、观测延迟或自定义目标轨迹时，使用场景格式。不要把两种输入格式的字段混在一起。

```json
{
  "schema_version": 1,
  "version": "2.59.0.28",
  "missile": "us_aim_120d",
  "duration_s": 20,
  "launch": {
    "position_m": [0, 6000, 0],
    "velocity_m_s": [330, 0, 0],
    "quaternion_xyzw": [0, 0, 0, 1],
    "angular_rate_rad_s": [0, 0, 0],
    "age_s": 0
  },
  "target": {
    "position_m": [20000, 6000, 1000],
    "velocity_m_s": [-250, 0, 0],
    "collision_radius_m": 3
  }
}
```

这里的速度单位是 **m/s**，不是简单输入的 km/h；位置是 m，角速度是 rad/s，四元数顺序是 x、y、z、w，必须归一化。若不提供四元数，默认机体 +x 朝世界 +x，不会自动根据高级输入的速度向量调整姿态。

高级场景 `duration_s` 默认 60 秒，范围 0.001–600 秒；这与简单输入默认资源寿命不同。`launch.age_s` 是初态已有弹龄，默认 0；结果 `time_s` 是从这个初态继续推进的时间，`missile_age_s` 则包含已有弹龄。

其他常用高级选项：

| 位置 | 字段 | 说明 |
|---|---|---|
| 顶层 | `wind_m_s` | 世界坐标风速向量，默认 `[0,0,0]` |
| 顶层 | `ground_height_m` | 平地高度，默认 0 |
| 顶层 | `proximity_fuse` | 是否使用资源近炸设置，默认 `true` |
| 顶层 | `sample_period_s` | 输出采样周期；默认 `null`，输出每个物理步；显式周期会回退 Python fast |
| 顶层 | `dt_s`、`step_policy` | 物理步长和步进策略；更小步长通常增加计算量，非默认边界切分可能回退 |
| `launch` | `ejection_velocity_body_m_s` | 机体坐标弹射附加速度，默认零向量 |
| `launch` | `feedback_acceleration_m_s2` | 飞控初始反馈加速度，默认零向量 |
| `launch` | `motor_start_times_s` | 点火时刻，采用弹龄而非本次模拟相对时间 |
| `target` | `collision_radius_m` | 几何接触半径；默认 0，关闭球体接触判断 |
| `observation` | `mode` | 默认 `locked`，保留当前观测滤波；`ideal` 用于理想观测对照 |
| `observation` | `sample_period_s`、`latency_s` | 目标观测采样周期与延迟，单位秒 |

注意 `observation.sample_period_s` 控制观测采样，顶层 `sample_period_s` 控制输出采样，二者不同。

要使用记录的目标轨迹，在 `target` 中添加 `samples`：

```json
[
  {"time_s": 0, "position_m": [20000, 6000, 1000], "velocity_m_s": [-250, 0, 0]},
  {"time_s": 10, "position_m": [17500, 6000, 1500], "velocity_m_s": [-250, 0, 100]},
  {"time_s": 20, "position_m": [15000, 6000, 3000], "velocity_m_s": [-250, 0, 200]}
]
```

这段数组要作为 `target.samples` 的值，不能直接当作完整输入。时间严格递增，从 0 开始，并覆盖所请求的全部 `duration_s`；目标初始位置和速度必须与第一个样本一致。默认 `target.interpolation` 为 `hermite`，可改为 `recorded_linear`。记录轨迹不能同时指定 `maneuvers` 或恒定 `turn_rate_rad_s`。

## 6. Python API 与逐次计时

将下面代码保存为同目录的 `run.py`，再运行 `python -X utf8 run.py`：

```python
import json
from time import perf_counter
from wt_missile import Calculator, save_result

with open("example.json", encoding="utf-8-sig") as stream:
    inputs = json.load(stream)

calculator = Calculator()
for index in range(5):
    start = perf_counter()
    result = calculator.calculate(inputs, fastmode=True)
    elapsed_ms = (perf_counter() - start) * 1000
    backend = result["summary"]["fastmode"].get("backend", "python-standard")
    print(f"第 {index + 1} 次：{elapsed_ms:.3f} ms，{backend}，"
          f"实际飞行 {result['summary']['time_s']:.3f} s")
    if backend == "python-legacy":
        print(result["summary"]["fastmode"].get("compiled_fallback_reason"))

save_result(result, "result-files")
```

第一调用可能包含编译或加载开销，后续更接近持续使用时的耗时。上面的计时包含参数校验、整段计算和完整输出对象生成，不包含最后的文件保存。

也可直接使用 `from wt_missile import calculate, list_missiles`。`calculate(inputs, fastmode=False)` 明确使用标准模式；`fastmode=None` 或不传时沿用输入中的设置。`input_format` 可以是 `auto`、`calculator` 或 `scenario`。

每次调用都有独立的计算状态，不修改输入字典。`Calculator` 不是计算结果缓存；重复调用会重新计算。连续批量工作可复用 Python 进程，避免每次导入和启动解释器。

## 7. 返回结果怎么看

一次计算返回 `scenario`、`summary`、`trajectory` 和 `event` 等字段。

| 字段 | 含义 |
|---|---|
| `summary.time_s` | 实际模拟飞行时长；可能小于 `duration_s` |
| `summary.steps` | 实际积分步数 |
| `summary.terminal_event` | 终止原因 |
| `summary.minimum_separation_until_event_m` | 终止前的最小几何距离，m |
| `summary.distance_flown_m` | 已飞路径长度，m，不是到目标的初始距离 |
| `summary.output_rows` | 输出轨迹行数 |
| `summary.fastmode.backend` | fast 后端：`compiled-c` 或 `python-legacy`；标准模式没有这个键 |
| `trajectory` | 初态及各输出时间点，共 65 个字段/行 |
| `event.state` | 终止状态，与最后一行轨迹对应 |

常用轨迹列：`time_s`、`missile_age_s`、`missile_x_m/y_m/z_m`、`missile_vx_m_s/vy_m_s/vz_m_s`、`speed_m_s`、`range_m`、`mass_kg`、`thrust_N`、`distance_flown_m`。姿态、角速度、制导请求、控制量和观测状态也在每行中。

终止原因包括 `time_limit`（达到请求时长）、`lifetime`（达到资源寿命）、`ground`（到达平地）、`contact`（球体接触）、`proximity_fuse`（几何近炸条件满足）。接触/近炸不等于已评估击毁，`event.kill_assessed` 为 `false`。

最后一行可能是步内事件插值得到的状态，此时 `state_interpolated=true`。程序不会在终止之后补足轨迹行。初态加速度等不可用量可以是 JSON `null`，不要当成数值零。

## 8. fast 的编译、缓存与回退

C 源码内嵌在 `wt_missile.py` 中，第一次 fast 调用由本机编译器生成机器码库，Python 用 `ctypes` 调用整个计算循环。包内不含预编译 DLL/SO，也不需要游戏 ELF。

默认缓存位置：

- Windows：`%LOCALAPPDATA%\wt-missile\compiled-fast`。
- Linux：`$XDG_CACHE_HOME/wt-missile/compiled-fast`；未设置 XDG 时为 `~/.cache/wt-missile/compiled-fast`。

可设置 `WT_MISSILE_FAST_CACHE` 改缓存目录、`CC` 指定编译器可执行文件；`WT_MISSILE_COMPILED_FAST=0` 主动禁用编译 fast。`CC` 是可执行文件名称或路径，不是带参数的 shell 命令。换机器重新编译，不搬运旧机器缓存。

代码、平台与架构决定缓存身份。编译代码会复用，轨迹不会复用。删除本机缓存可触发重编译；Windows 下先退出正在加载该 DLL 的 Python 进程。

只有 `summary.fastmode.backend == "compiled-c"` 才能套用下面的编译 fast 耗时。缺少可用编译器/缓存、显式周期输出、需要边界切分的非默认步长或超过编译路径步数上限等条件，会回退 `python-legacy`，原因在 `compiled_fallback_reason`。这些回退路径仍可计算，但速度不同。

## 9. 计算耗时与飞行时长

**大致呈“固定开销 + 每秒飞行的线性开销”。** 这里的计算时长是现实世界的等待时间，单位毫秒；飞行时长是模型推进的时间，单位秒，二者不要混用。

本轮用交付包原样代码，在 Ryzen 9 9950X3D、Linux x86_64、CPython 3.14.7、NumPy 2.5.3 上测试 PL-12 与 AIM-120D。默认物理步长约 1/48 秒，输出每个物理步的全部 65 个字段。统一设置为 10 km 高度、初速 330 m/s、目标初始距离 200 km、目标以 250 m/s 同向直线飞行，避免在 0.1–80 秒扫描范围内提前接触或落地。

每种型号取 0.1、0.5、1、2、5、10、20、40、60、80 秒；每种模式先预热 2 次，再测 11 次，交替执行标准/fast，取中位数。计时包含整个 `calculate()`：输入校验、目标轨迹准备、积分、摘要及完整轨迹对象；不包含导入、首次编译、JSON 编码与落盘。

### 没有提前终止：直接按飞行秒数估算

设 T 为 `summary.time_s`，并且它等于请求的时长。两种导弹合并拟合得到：

```text
标准模式耗时（ms） ≈ 0.54 + 6.57 × T（s）
编译 fast 耗时（ms）≈ 1.49 + 0.386 × T（s）
```

也就是本机本组场景中，每增加 1 秒飞行，标准计算大约多 6.6 ms，fast 大约多 0.39 ms。默认步长下，每秒约 48 个积分步，通常输出行数约为 `48 × T + 1`，因此增加飞行时间也会线性增加计算和输出对象生成工作。

下面列出 PL-12 的实际中位数，末列额外测量命令行同款 `indent=2` JSON 编码，不计入前两列：

| 实际飞行时长 | 标准计算 | 编译 fast | JSON 编码（另计） |
|---:|---:|---:|---:|
| 0.1 s | 1.35 ms | 1.77 ms | 0.10 ms |
| 0.5 s | 3.83 ms | 2.03 ms | 0.33 ms |
| 1 s | 7.18 ms | 2.13 ms | 0.66 ms |
| 2 s | 13.76 ms | 2.52 ms | 1.28 ms |
| 5 s | 32.76 ms | 3.41 ms | 3.04 ms |
| 10 s | 65.66 ms | 5.20 ms | 6.16 ms |
| 20 s | 131.89 ms | 9.22 ms | 12.10 ms |
| 40 s | 264.41 ms | 16.36 ms | 24.15 ms |
| 60 s | 392.04 ms | 24.24 ms | 39.45 ms |
| 80 s | 523.58 ms | 33.10 ms | 52.46 ms |

两个模式的线性拟合 R² 分别为 0.99994 和 0.99920。经验式描述这些条件下的中位数，不是单次延迟上限；例如 60 秒 PL-12 的 fast 中位数 24.24 ms，11 次样本的 P95 为 29.82 ms。0.1 秒这样的极短计算，fast 固定成本可能使它比标准更慢。

### 提前终止：fast 还受请求时域影响

`duration_s` 是上限，不一定是实际飞行时长。令 H 为 `min(duration_s, 资源寿命 - 初始弹龄)`。编译 fast 当前会先准备 0 到 H 的目标轨迹，再积分到实际终止时刻 T。因此即使 T 很短，H 很长仍会有准备成本。

固定近距 AIM-120D 案例中，所有请求都在约 4.062656 秒发生几何近炸，实际飞行时间相同：

| 请求上限 duration_s | 实际飞行时长 | 标准计算 | 编译 fast |
|---:|---:|---:|---:|
| 5 s | 4.062656 s | 27.21 ms | 3.26 ms |
| 10 s | 4.062656 s | 26.75 ms | 4.37 ms |
| 30 s | 4.062656 s | 27.07 ms | 8.98 ms |
| 60 s | 4.062656 s | 26.74 ms | 15.84 ms |
| 100 s | 4.062656 s | 27.34 ms | 25.51 ms |

把完整飞行与提前终止样本合并，本机这组直线目标条件下可以更细地估算：

```text
编译 fast 耗时（ms）≈ 1.48 + 0.154 × 实际飞行 T（s）+ 0.233 × 请求时域 H（s）
```

这个二变量拟合 R² 约 0.99928。没有提前终止、T=H 时，它就回到前面的约 `1.5 + 0.386 × T`。因此在满足实际研究需求的前提下，避免给很短的场景设置无必要的超长 `duration_s`；不要据此截断尚需研究的后续飞行。

### 首次调用、导出与其他机器

本轮 Linux 空缓存下，首次编译加 1 秒轨迹计算用时 232.8 ms；模块导入约 27.2 ms。它们是各一次观测，不是多次中位数。

命令行从启动到结果落盘的总等待时间，还要加解释器启动、导入、必要时的编译/库加载、JSON 编码和文件写入。比如本轮 80 秒 PL-12，API 计算约 33.10 ms，漂亮格式 JSON 编码另需约 52.46 ms，文件约 9.33 MB；完整命令耗时自然会高于 33 ms。批量计算尽量复用一个进程。

同一套扫描也用 Windows x64 CPython + NumPy 在 Wine 11.17 下完成，完整飞行拟合为标准约 `0.84 + 7.55 × T` ms、fast 约 `2.36 + 0.506 × T` ms。**这是 Wine 环境实测，不是原生 Windows 性能结论。**

这些系数不是所有机器/所有弹种的常数。CPU、解释器、目标机动/轨迹插值、观测设置、物理步长、资源型号、输出方式和系统负载都会影响它。改变步长、走 Python 回退、额外进行 JSON 编码或大量磁盘写入后，应重新测量。计时代码见第 6 节。

原始逐次样本、输入条件、拟合脚本和曲线保留在研究仓库的 `runs/readme-timing-20260926/`；最简包只带本 README，不捆绑这些实验文件。本轮没有修改计算代码，计时源码 SHA-256：`1bfa0fa2a3a6d34faa01e4b6ad77e15ba10573ed857bc3362ed368b4e8511890`。


## 10. 常见问题

| 现象 | 处理 |
|---|---|
| `No module named numpy` | 用运行计算器的同一个 Python 执行 `-m pip install numpy==2.5.3` |
| `No C compiler/cache available` | 标准模式仍能用；fast 需要检查当前终端的 `cc`/`gcc`/`cl` 与 PATH |
| Windows 找不到 `ld` | 将 MinGW 工具链放到英文路径，例如 `C:\w64devkit`，确认其 bin 在当前 PATH |
| Windows DLL 无法加载或架构错误 | Python 与编译器都使用 x64，查看完整 `compiled_fallback_reason`；不要复制其他架构缓存 |
| 明明加了 fast 却没变快 | 检查 backend，区分首次编译、Python 回退、JSON 输出和导入时间；极短轨迹的固定成本也可能占主导 |
| 输入提示 `missing` | 简单输入的 11 个数值字段都必须保留；从 `example.json` 修改最稳妥 |
| 输入提示未知字段 | 检查拼写和输入格式；高级场景字段不能直接塞进简单格式 |
| `Resource identity mismatch` | 重新解压原始资源，核对目录，不删除身份检查 |
| 输出未达到请求秒数 | 查看 `terminal_event`；命中几何、近炸、地面或寿命都会提前结束 |
| 自定义目标轨迹不够长 | `target.samples` 必须覆盖完整请求时域，不能只覆盖预计接触之前 |

包内接口与示例以这份代码为准。当前最简包没有测试框架、基准工具链和游戏进程依赖；README 中的计时代码即可在你自己的机器上估算耗时。

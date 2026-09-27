# 导弹包线图

给定一个空战工况，算出 11 型主动弹各自的 **(总增速 ΔV, 简化弹道系数 BC)**，
再把「命中时间相同」的参数组合连成**等时线**画在同一张图上。

![默认工况](figures/fig_isotime_plane_default.png)

（图是默认工况跑出来的：50 km 迎头、双方各 10 km / 300 m/s。上面这张是 PNG，
`figures\` 里还有 PDF 和 SVG。）

---

## 先跑起来

双击**上一级目录**的 `启动.bat`。等几秒，浏览器会自动打开操作界面。

那个黑色窗口就是程序本体 —— **关掉它 = 退出程序**。

什么都不用装：Python 和依赖库都在 `python\` 里，不碰你系统上的环境。

---

## 这张图在说什么

| 元素 | 含义 |
| --- | --- |
| 一个点 | 一型弹。横轴是它**现算**的总增速 ΔV，纵轴是简化弹道系数 BC |
| 一条彩色曲线 | **等命中时间线**。线上任意一点的 (ΔV, BC) 组合，命中时间都一样 |
| 红圈 | 基准弹（默认 PL-12） |
| 右侧色条 | 命中时间 $t_{hit}$，单位秒 |

怎么用：把一型弹实际的 (ΔV, BC) 在图上一落，看它夹在哪两条等时线之间，
就知道它在这个工况下大概几秒命中。**换个工况，整张图重算。**

等时线的画法就是它的定义：**环境不变**，把 (ΔV, BC) 平面穷举一遍，
再把命中时间相同的组合连成线。

### ΔV 与 BC 是怎么算出来的

从 blkx 原始参数**现算**，不是查表：

```text
fu1 = mass − massEnd                    Isp1 = force ·timeFire  / (9.81·fu1)
fu2 = massEnd − massEnd1                dV1  = Isp1·9.81·ln(mass / (mass−fu1))
Isp2 = force1·timeFire1 / (9.81·fu2)    dV2  = Isp2·9.81·ln((mass−fu1)/(mass−fu1−fu2))
ΔV  = dV1 + dV2                         # 无二级时就是 dV1
BC  = (mass−fu1−fu2) / (CxK·(caliber/2)²·π)      # caliber 单位是米
```

拿到目标的 ΔV / BC 后，反推**推力乘数**和**阻力乘数**喂给求解器 ——
复现的是「同样总增速、同样弹道系数」的弹道。

---

## 界面上能改什么

* **几何**：距离、发射高度、目标高度、方位、俯仰
* **速度**：载机与目标各自的速度 / 航向 / 俯仰
* **弹**：基准弹（默认 PL-12）、弹池子集（只挑其中几型）
* **网格**：ΔV 与 BC 的步长、等时线步长、仿真时长、观测模式

跑的时候是**后台任务 + 进度条**，页面里能直接看图，也能下载产物。

---

## 已经跑好的结果

`figures\` 里是图，`results\` 里是同一批数据的表格：

| 文件 | 内容 |
| --- | --- |
| `figures\fig_isotime_plane_default.png / .pdf / .svg` | 默认工况那张图，三种格式 |
| `results\plane_default.json` | 整批扫描的清单（工况、网格、命中率、用的哪个内核…） |
| `results\plane_default_cases.csv` | 逐工况命中时间（1632 行） |
| `results\plane_default_isolines.csv` | 等时线采样点 |
| `results\compare_default.csv` | 11 型逐个对比 |
| `results\reference_fig.png` | 作者给的参考图，用来对比 |

---

## 算得慢？

包里带了**预编译的 C 内核**（`kernel-cache\`）。如果它在你的机器上加载不了，
程序会**自动退回纯 Python** —— **结果完全相同**，只是慢：

| | 全尺寸扫描（32×51 = 1632 个工况） |
| --- | --- |
| 用上内核 | 约 40 秒 |
| 纯 Python | 约 5 分钟 |

只出散点图（不扫等时线）是秒级的。实际用了哪个内核，跑完在图旁边的
`results\plane_*.json` 的 `backend` 字段里能看到。

---

## 目录里都有什么

```text
启动.bat              双击这个
app\
  ├─ run_ui.py        启动逻辑（重定向内核缓存、注册字体、起界面）
  ├─ python\          内嵌 Python + numpy + matplotlib（不用管）
  ├─ src\missile_sim\ 外壳代码（13 个模块，可以改）
  ├─ vendor\wt-missile\  求解器内核（只读）
  ├─ kernel-cache\    预编译的 C 内核
  ├─ fonts\           中文字体（英文系统上不出方块）
  ├─ configs\         默认配置
  ├─ figures\ results\   已经跑好的图和数据
  ├─ tests\           自检
  ├─ docs\SOLVER-API.md  求解器输入/输出契约
  ├─ 使用说明.txt      极简版说明
  └─ README.md        你正在看的这份
```

---

## 想改代码

`src\missile_sim\` 里 13 个模块，每个只管一件事：

| 模块 | 干什么 |
| --- | --- |
| `spec.py` | 契约层：`Scene`（工况）、`Scaling`、`MissilePoint`、`AxisSpec`… |
| `solver.py` | **唯一**和求解器内核打交道的地方 |
| `mapping.py` | ΔV/BC ↔ 推力/阻力乘数（唯一实现） |
| `pool.py` | 11 型弹池，ΔV/BC 现算 |
| `engine.py` | 多进程 + 分档缓存 |
| `grid.py` | 参数网格与等时线提取 |
| `figures.py` | **唯一**出图 |
| `record.py` | CSV / JSON 产物 |
| `workflow.py` | 端到端编排（5 步） |
| `cli.py` | 命令行入口 |
| `targets.py` | 想定表单 → `Scene`、预置工况、兼容性前置校验 |
| `report.py` | 11 型逐个对比表 |
| `webui.py` | 界面（纯标准库 `http.server`，只听 127.0.0.1） |

直接用内嵌 Python 跑命令行：

```bat
python\python.exe -m missile_sim --help
python\python.exe -m missile_sim --list-missiles
python\python.exe -m missile_sim --no-iso --tag probe
```

自检（135 项，约 20 秒）：

```bat
python\python.exe tests\run_tests.py
```

**想换求解器内核**：只需要读 `docs\SOLVER-API.md`。输入 / 输出契约都固定在那里，
`src\missile_sim\` 里只有 `solver.py` 一个文件需要动。

---

## 口径与限制（别当成游戏内定论）

* ΔV/BC ↔ 乘数是**等效映射**，不是改发动机：复现的是「同样总增速 / 同样弹道系数」的
  弹道，**不代表**真实的推力曲线或气动外形。
* 求解器自身的**绝对阻力水平未标定**：字段相关性不等于引擎公式证明。
* 内核对应 War Thunder **2.59.0.28** 的 6DOF 实现；blkx 参数取自 **2.59.0.11** 的数据副本。
* `results\reference_fig.png` 是 **2.57 基线**的值，只用于对比，不要拿它当当前版本。

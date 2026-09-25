# 升力 / 诱导阻力升级 —— 可行性评估与实施计划

> **证据规则（用户 2026-09-25 指定）**
> **信源 2 = 权威**：`wt-missile-backend-runtime-research-1.0.1`（信源本人交付的文件包 —— Python 仿真器 +
> 19 份文档 + 16 份 blk，运行 Linux ELF 2.59.0.22/.28 的**游戏原生机器码**）
> **信源 1 = 转述**：`E:/War Thunder/_recon/升力与诱导阻力_实现规格.md`（与信源的**聊天记录转述**）
> ⇒ **冲突处一律判为 1 的转述错误。**
>
> 所有数字可用 `scripts/probe_aero_upgrade.py` 复现 · 目标版本 WORK = 2.59.0.11（实机 2.58.0.36 包）
> 评估日期 2026-09-25

---

## 0. 结论（四句）

1. **阻力侧可以做到精确。** `f(M)`、`F(M)`、`D0`、`Da`（`sin²α`）、`SD`、`SL`、`CxAoA=9`
   —— 两源一致，且 2 明确标"2.59.0.28 受限工况已核对"。我方实现与 1 的自检表吻合 **4.8e-9**，
   参考实例 `D_base` 差 **0.00%**。**收益最大的一项就是补 `f(M)`**（现状阻力偏大 1.61~3.31 倍）。
2. **升力/迎角侧"精确"的代价已经量化出来了**：α 是**姿态状态量**（弹体系来流方向角），
   而它经由**控制回路**建立 —— 2 用原生执行实测 **t90,50 = 65~146 ms**（AIM-120C5：正式服 134.5 / 新参数 81.25 ms）。
   这个时间尺度与末端几何（引信 12 m、末速 ~700 m/s ⇒ 80 ms ≈ 56 m）同量级
   ⇒ **点质量瞬时过载模型在末段是乐观的，不能靠"准定常配平"糊过去。**
3. **因此有两条明确的路**：① 加"过载建立滞后"（用实测 t90 标定，改动小，能修掉末段乐观）；
   ② 复刻内环（姿态 + 力矩 + 惯量 + PID + 限幅），2 的文档已把公式给全。
4. **`f(M)` 与升力无关、零决策、收益最大 ⇒ 建议先单独落地并提交**（A 段）。

---

## 1. 以 2 为准后的冲突裁决

| # | 项目 | 1（转述） | 2（权威） | 裁决 |
| --- | --- | --- | --- | --- |
| 1 | **α 怎么来** | §6-1「信源未说明」，只提示"弹体相对气流总迎角" | §2：`alpha = atan2(bodyAirVelocity.z, bodyAirVelocity.x)`，弹体系为 x前/y右/z下；§6 再补**局部来流** `+ cross(omega, aeroPointFromCM)` | **2 胜**：α 由**姿态 + 角速度**给出，不是配平反解 |
| 2 | **折返限幅的输入** | `Cy' = CyK·sin(\|α\|)`，对 `Cy'` 折返 | §8：`c = 分支内部两个有效单位方向的点积`，`z = CyK·√(max(0,1−c²))`，对 `z` 折返 | **2 胜**：作用在**分支内部方向角**上，不能一概换成质心迎角 |
| 3 | **AIM-120C5 的 `CyMaxAoA`** | 1.8（"该弹种取值"） | 16 份 blk 无此键 → 原生默认 **1.0** | **2 胜**（我另行复核：扫 676 个 blkx + 9 个 tag，1.8 属老式 AGM）⇒ 折返点 **27.04°**，不是 54.90° |
| 4 | **`CxK` / `wingAreaMult`** | 1.405 / 1.225 | 2.59.0.28 = 1.225 / 1.7（与工作区 blkx 相同） | **2 胜** ⇒ `SL` 从 0.23915 变 **0.331881 m²**（+38.8%） |
| 5 | **`loadFactorMax` 的语义** | 与 `finsLatAccel`/`reqAccelMax` 混用 | §2 表：三者**分别保留**；`loadFactorMax` "独立于气动控制参数与自动驾驶仪指令限幅" | **2 胜** |
| 6 | **升力侧上限** | 只给"折返限幅" | §11 静态包线：`staticG ≈ min(kappa·q_kPa, B)`，`kappa = 1000·SL·min(CyK·finsAoa, CyPeak)/(m·g0)`，`B = finsLatAccel·massInitial/m` | **2 胜**：控制权限与升力峰值**取小**，另有一道控制上限 B |
| 7 | **`CyMachMult`** | "字段存在但未在升力链中定位" | §2 表：本次样本**不含**该表 | 对我们这 11 型 = 无该键（我扫过），忽略 |
| 8 | **阻力分解** | 只给 `D0 + Da` | §11 另给保能形式：`BC = betaEnergy = m/(SD·CxK)`、`gammaEnergy = m·SD·CxK·CxAoA/(SL²·CyK²)`、`D/m = q·f(M)/betaEnergy + gammaEnergy·Fmach·(n·g)²/q` | **补充**（`BC` 与我们既有定义**完全一致**，见下） |
| 9 | **`useCxiMach=false` 时** | 未说明 | §10：`Fmach = 1`，但 **`D0` 仍然乘 `f(M)`** | **补充**（重要，别一起关掉） |
| 10 | 声速/大气 | §6-7「已单独确证」 | §3 给全：`T = 288.16·poly(TEMPERATURE_COEFFS)`、`a = 20.1·√T` | 一致；我方已按此重写 `atmosphere.py` |

**两处独立印证我们既有实现**：

* `BC = betaEnergy = m/(SD·CxK)` —— 与本项目 `ballistic_coefficient()` 的定义**逐字相同**（120C5 算得 3624.0）。
  即我们一直用的 BC 就是游戏的"保能系数"，不是自造指标。
* `propNavMult`：2 记录"正式服均为 4，测试服除 Derby 外均为 6"；我们 WORK blkx 读到 **6.0**，
  与我们的 `n_base = 6.0` 一致（WORK = 2.59.0.11 属新参数侧）。

---

## 2. α 与"精确"的分界：控制回路 ~80 ms

### 2.1 α 的定义（2 §2/§6）

```text
airVelocity          = v − wind
bodyAirVelocity      = transpose(Rbody) × airVelocity
localAirVelocityBody = bodyAirVelocity + cross(omega, aeroPointFromCM)   # 局部来流
alpha                = atan2(localAirVelocityBody.z, localAirVelocityBody.x)
```

即 **α 由姿态（R_body）与角速度（omega）决定**。二维纵向平面里就是 **α = θ − γ**
（俯仰姿态角 − 航迹角；`ω×r` 项在弹长 3.66 m、角速度 ≲1 rad/s 时 <0.1°，可忽略）。

### 2.2 但"精确"的真正门槛是**建立时间**（2 的实测）

2 在 `research/arh-overload-20260916/response-time/` 用**原生机器码**跑了 0→20 G 阶跃
（燃尽质量、6 km、800 m/s、初始 α 与 ω 为零），定义 `t90,50` = 实际过载达标且随后连续 50 ms 不掉回的时刻：

| 型号 | 正式服 t90,50 | 新参数（2.58 侧） | 型号 | 正式服 | 新参数 |
| --- | ---: | ---: | --- | ---: | ---: |
| AIM-120A | 120.0 ms | 71.75 ms | PL-12 | 135.0 ms | 70.0 ms |
| **AIM-120C-5** | **134.5 ms** | **81.25 ms** | PL-12A | 146.5 ms | 72.0 ms |
| R-77 | 92.0 ms | 65.5 ms | AAM-4 | 110.5 ms | 78.0 ms |
| R-77-1 | 97.25 ms | 68.75 ms | MICA EM | 89.75 ms | 75.0 ms |
| | | | Derby | 116.5 ms | 116.5 ms |

* 我们 WORK = 2.59.0.11 属新参数侧 ⇒ AIM-120C5 取 **≈81 ms**（一阶等效 τ ≈ 35 ms）。
* **这个尺度不能忽略**：末速 ~700 m/s 时 80 ms ≈ **56 m**，而引信半径只有 12 m。
  也就是说，**现在这个"指令过载立刻生效"的点质量模型，末段脱靶量是被系统性低估的。**
* 2 同时给了完整内环（可原样复刻）：

```text
maxRequested = reqAccelMax × g0                 # ① 制导请求限幅（合成向量）
ch = u_h × finsAoaHor ; cv = u_v × finsAoaVer   # ② 控制量 → 迎角域
K  = massInitial × g0 × finsLatAccel / (CyK × SL)
若 qbar×|(ch,cv)| > K：整体按 K/(qbar×size) 缩放   # ③ 动压 × finsLatAccel 限幅
z  = CyK·√(max(0,1−c²)) → 折返限幅                # ④ 气动分支
s  = 1.225 × 500 / (rho × V)                    # baseIndSpeed 1800 km/h
integral  = clip(integral + Ki·s·error·dt, ±lim)
derivative+= 48 × (error − prevError − dt·derivative)
control   = clip(Kp·s·error + integral + Kd·s²·derivative, −1, 1)
```

### 2.3 三条路（按代价排序）

| 路线 | 做法 | 精度 |
| --- | --- | --- |
| **①-A** 保持点质量 + 准定常配平 α | `sinα = m·n·g/(q·SL·CyK)`；过载上限用 `min(reqAccelMax, staticG)` | 巡航/中段够用；**末段乐观**（无建立时间） |
| **①-B** 点质量 + **过载一阶滞后** | 用上面实测 `t90`（120C5 ≈ 81 ms）标定 τ≈35 ms，命令过载过一阶环节后再算 α 与诱导阻力 | **便宜地修掉末段乐观**，推荐先做这条 |
| **②** 复刻内环 | 姿态 Q、角速度 ω、惯量（`Ixx=m·r²`、`Iyy=Izz=m(L²+3r²)/12`）、`I·dω/dt = M − ω×Iω`、四元数积分 + 上面那套 PID/限幅 | 最接近原生；工作量最大 |

三条路都用同一条 α→阻力关系，所以 **C 段（诱导阻力）与路线选择无关，可以先做**。

### 2.4 静态过载包线（2 §11）——顺带修正我先前的一个简化

`staticG ≈ min(kappa·q_kPa, B)`，AIM-120C5（`m` 取燃尽 110.223 kg，`massInitial` 161.4789 kg）：

| 高度 | 300 m/s | 600 m/s | 800 m/s | 1000 m/s | 1200 m/s |
| --- | --- | --- | --- | --- | --- |
| 5 km | 10.1 | 40.6 | **51.3（B 限）** | **51.3（B 限）** | **51.3（B 限）** |
| 10 km | **5.7** | 22.8 | 40.5 | **51.3（B 限）** | **51.3（B 限）** |

* `B = finsLatAccel·massInitial/m = 35×161.4789/110.223 = **51.3 G**` 是高动压侧的上限
  （我先前只写 `q·SL·CyMaxAoA/(m·g)`，在 5 km/1000 m/s 会高估到 113 G，**错 2.2 倍**）。
* 因为我们的请求上限 `reqAccelMax = 35 G` < 51.3 G，**B 在我们当前工况下永不生效**，
  所以探针里 `③ 完整` 的数字不受影响；但**一旦放宽请求上限或做高动压包线分析，必须换成 `min(kappa·q, B)`**。
* `min(CyK·finsAoa, CyPeak)`：120C5 是 `min(0.99646, 1.0) = 0.99646` —— **控制权限**刚好略小于**升力峰值**。

---

## 3. 量化影响（`scripts/probe_aero_upgrade.py`，三种阻力口径同工况）

### 3.1 基础阻力：现状偏大 1.61~3.31 倍

倍数 = `1/f(M)`，全包线（0~15 km × 300~1400 m/s）**1.61× ~ 3.31×，中位 2.80×**。

### 3.2 基准工况（50 km 迎头、10 km、高抛 22°、ΔV 865.3、BC 3624）

| 口径 | 状态 | t_hit | V命中 |
| --- | --- | --- | --- |
| ① 现状 | hit | 60.81 s | 366 m/s |
| ② +f(M) | hit | **43.9 s** | **701 m/s** |
| ③ +诱导阻力+气动上限 | hit | 45.1 s | 672 m/s |

### 3.3 工况边界（定性翻转）

| 工况 | ① 现状 | ② +f(M) | ③ 完整 |
| --- | --- | --- | --- |
| 50 km 高抛22° | hit 60.8 / 366 | hit 43.9 / 701 | hit 45.1 / 672 |
| 50 km 无高抛 | hit 67.3 / 213 | hit 45.8 / 533 | hit 45.8 / 533 |
| 70 km 高抛22° | hit 92.6 / 325 | hit 64.5 / 621 | hit 66.0 / 601 |
| **70 km 无高抛** | **no_hit_slowdown** | **hit 72.7 / 367** | **hit 72.7 / 367** |
| 30 km 无高抛 | hit 32.6 / 368 | hit 24.3 / 745 | hit 24.3 / 745 |
| 80 km 高抛30° | hit 105.8 / 347 | hit 74.3 / 652 | hit 77.1 / 619 |

### 3.4 11 型主动弹（默认工况）

命中速度**平均 +311 m/s**（+278 ~ +375）、命中时间 **−15 ~ −22 s**。

### 3.5 诱导阻力占比（同表工况）

10 km/600 m/s 拉 20 G 时占总阻力 **81%**、10 km/1000 m/s 拉 10 G 时 **13%**
—— "格斗段掉能量、远射段几乎不痛"，与 1 §4.4 的机理结论方向一致。

---

## 4. 顺带发现的两个既有偏差（不属于本次升级，但影响"精确"）

1. **声速已修**：原 ISA 线性温降在 15 km 差 **−2.2%**；已按 2 §3 的精确式重写，
   `T(5 km)=255.58 K`、`a=321.34 m/s`，与 1 的参考工况完全一致（自检 62/62）。
2. **制导增益表用错型号**（未修）：我们统一硬编码 `timeToHitToGain`（10 s→1.0 / 25 s→0.8 / 50 s→0.5）
   与固定 0.3 s 延迟，但 WORK blkx 实测：
   * 120C / R-77 / PL-12 有 `timeToHitToGain` = 上面那三点 ✓，R-77 与 PL-12 另有
     `timeToGain = (0.3, 0) → (0.31, 1)`（10 ms 解锁斜坡）；
   * **MICA 没有 `timeToHitToGain`**，其 `timeToGain = (0.15, 0) → (0.16, 1)`；
   * **120C 没有 `timeToGain`**。
   ⇒ 我们对 MICA 施加了它没有的导航增益表，对 120C 施加了它没有的 0.3 s 解锁斜坡。

---

## 5. 需要拍板的事

1. **是否切换默认口径**：`f(M)` 会让现有全部数字失效（等时线、60.81 s、11 型表、交叉图）。
   建议切成游戏口径，保留 `--drag-model flat` 复现旧结果。
2. **升力路线选 ①-B（过载滞后，推荐先做）还是 ②（复刻内环）**。
3. **是否同时修 §4.2 的制导增益表**（逐弹读 `timeToGain` / `timeToHitToGain`）。

---

## 6. 实施计划

### A 段：`f(M)` 基础阻力（零决策、收益最大、**建议立刻单独落地**）

* 新增 `src/missile_sim/aero.py`：`f_mach`、`F_mach`（照 2 §9/§10）；`mach(v,h)` 用已修好的 `atmosphere`
* `config.py`：`DragConfig.model: "flat" | "mach"`（默认 `mach`）；另加 `use_cxi_mach`（对应 `useCxiMach`，
  默认 true；**关闭时只把 `Fmach` 置 1，`D0` 仍乘 `f(M)`**）
* `sim.py`：标量 `_ScalarSim._accel` 与数组 `_accel_arr` **两处同时**加 `×f(M)`
* 测试：`tests/test_aero.py` 对拍 1 的 §7 自检表 10 点（容差 1e-6）
* 验收：基准工况 60.81 → 43.9 s、366 → 701 m/s；`--drag-model flat` 复现 60.81 s

### B 段：升力 + 过载上限（路线 ①-B）

* `aero.py`：`lift_trim(q, m, sl, cyk, cy_peak, n, g) -> (alpha, cy, capped)`（上升支路）
* 过载上限：`min(reqAccelMax, staticG)`，`staticG = min(kappa·q_kPa, B)`
* **过载一阶滞后**：`n_actual += (n_cmd − n_actual)·dt/τ`，τ 由实测 `t90` 标定（120C5 ≈ 35 ms，
  逐弹从 2 的表取；正式服/新参数两列按数据版本选）
* 逐弹参数从 blkx 取 `caliber`/`length`/`wingAreaMult`/`finsAoa`/`finsLatAccel`/`reqAccelMax`；
  `CyK` 全用默认 2.2；`CyMaxAoA` 除 MICA 1.35 / R-77 系 1.3 外全用默认 1.0
* trace 加 `alpha` / `n_actual` / `staticG` / `capped`

### C 段：诱导阻力（与路线无关，可先做）

* `aero.py::drag_aoa(q, sd, cxk, cx_aoa, F_mach, alpha)`；两处 `_accel` 加该项
* 出 `D_aoa/D_total` 随航程曲线；重跑等时线与交叉图并**归档旧图**

### 路线 ②（若要做"精确"）

在 B 段之上加姿态状态（θ、ω）+ 惯量（2 §5）+ 力矩（`M = N × L_arm`，`L_arm = distFromCmToStab/wingAreaMult`）
+ 四元数/角速度积分（2 §13）+ 2 §16 的 PID 与三层限幅。

### 不做

2 的代码与 ELF（**无许可证**，且内含正版 Gaijin 二进制，`PROVENANCE.md` 明确不授予再分发许可）、
`CyMachMult`（我们这 11 型无此表）、`dragCx`（2 的阻力公式里没有它的位置）。

---

## 7. 复现

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python scripts\probe_aero_upgrade.py            # 全部（约 60 s）
python scripts\probe_aero_upgrade.py --quick    # 跳过 11 型弹逐条
# 输出：results/aero_upgrade_probe.json
```

探针**不改动仓库里的模型**：运行时替换 `_ScalarSim._accel` 的阻力项，退出前恢复。

---

## 8. 信源 2 的定位

* **是什么**：信源本人交付的文件包 —— 能在 Unicorn 里**执行游戏原生 x86-64 例程**的 Python 仿真器
  （`tools/simulator/{core,native,emulation}.py`）+ 19 份文档 + `research/` 下 14 份历史报告 + 16 份 blk
  + 一个 180 MB 正版 ELF。属 **Linux ELF 2.59.0.22/.28**，与信源 1 的 Windows PE 2.57.1.140 **地址体系无交集**，
  任何地址/函数身份都不可混用。
* **能用的**：公式文本、结构体布局、逐弹 blk 参数、惯量/力矩/四元数、PID/限幅链、以及一批可对拍的数值
  （231 组原生阻力核对最大相对误差 3.492e-6；576 个冻结状态包线核对最大差 0.001076 G；PID 独立复现最大差 6.45e-7）。
* **不能用的**：代码、ELF、镜像（无 LICENSE）。
* **期望值校准**：即使原生执行机器码，其实战轨迹一致性仍未达成 ——
  新批 PL-12 位置 RMSE **0.112~212.017 m**，旧批 RVV-AE 修正后 **1.17~34.76 m**，
  自述「**结果不支持"完整还原已完成"**」，其"验收完成"仅限自定的"导引律＋飞控＋弹体"范围。

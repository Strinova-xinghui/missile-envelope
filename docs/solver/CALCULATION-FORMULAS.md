# 当前模拟器的计算方式：公式版

2026-09-25。按实际计算顺序整理，主要对应已支持的 .22／.28 空空弹、常数 Cy 分支和当前离线环境。使用普通文本公式，所有向量均有明确坐标系。本文区分可写成公式的已核对分支和用于说明运动的连续方程；完整原生例程的浮点顺序、分支和离散积分不能由连续方程自动替代。

来源：[现有公式研究](FORMULAS-PLAIN.md)、[当前原生接通](NATIVE-259028.md)、[字段调用链](FIELD-CALL-CHAIN.md)、`tools/simulator/native.py`、`emulation.py`、`core.py`。本次新增两构建的 18 个 loft 公式案例、退出历史检查和 12 个发动机端点案例，见 [核对记录](../runs/formula-summary-20260925/verify_loft.json)。不修改模拟器数值代码。

## 1. 量与坐标

```text
r, v         导弹位置、世界速度
rT, vT       目标位置、世界速度
Q            弹体系到世界系的四元数，存储顺序 x,y,z,w
R(Q)         对应旋转矩阵
omegaBody    弹体角速度
m, m0        当前质量、初始质量
h            高度；世界 y 向上
wind         世界风速
g            [0, -9.81, 0] m/s²
g0           9.81 m/s²

norm(a)      向量长度
dot(a,b)     点积
cross(a,b)   叉积
clip(x,a,b)  限制在 [a,b]
```

距离 m、速度 m/s、质量 kg、力 N、力矩 N·m、角度 rad。配置中的角度字段需要先做单位转换。无限追踪率／锁定能力／离轴角只作用于导引头假设，弹体机动限制仍然生效。

## 2. 目标几何与导航参考速度

理想几何定义：

```text
dr = rT - r
dv = vT - v
range = norm(dr)
u = dr / range
Vc = -dot(u, dv)
omegaLOS = cross(dr, dv) / range²

Tgo = range / Vc        abs(Vc) > 4e-19 时
Tgo = 0                 否则
```

`Vc > 0` 表示接近，负的预计命中时间不擅自改成正值。距离近零单独处理。默认模式把滤波后的视线、角速度、距离和闭合速度代入后续计算，不直接使用理想真值。游戏接口存储的视线角速度符号与这里相反：

```text
omegaNative = -omegaLOS
```

当 `useTargetVel=true` 且距离、多普勒通道都有效：

```text
vRef = u × Vc + cross(omegaNative, u) × range
     = u × Vc - cross(omegaLOS, u) × range
```

理想观测下，`vRef = v - vT`。关闭该字段或任一所需通道无效时，`vRef = v`。这里的 `×` 在标量与向量之间表示普通乘法，向量叉乘统一写作 `cross`。

## 3. PN 导引与增益

对当前关闭角度修正／纯追踪附加项的 PN 分支：

```text
G = Gtime(age) × Ghit(Tgo)
aPN = G × N × cross(omegaLOS, vRef)
```

`N` 对应 `omegaToAccelMult`，未指定时回退 `propNavMult`。当总增益 `G < 0.001` 时，原生外环直接输出零控制，本步不继续正常 PN／loft／PID 更新。

时间增益、预计命中时间增益按分段线性表取值，区间外使用端点：

```text
lambda = (x - x_i) / (x_(i+1) - x_i)
f(x) = (1-lambda) × y_i + lambda × y_(i+1)
```

该式描述数学插值，原生代码还保留端点、符号及 float32 运算顺序。开启角度偏置／纯追踪等分支时，不能只用这一条 PN 式替换完整外环。`N × Vc × cross(omegaLOS,u)` 是另一种 PN 表达，不能无条件视为本模型正在执行的公式。

## 4. 当前 loft 高抛分支

令弹头世界方向为 `b = R(Q) × [1,0,0]`：

```text
thetaBody = atan2(b_y, sqrt(b_x² + b_z²))
```

若配置 `rangeToLoftElevation = [R1, theta1, R2, theta2]`，按距离平方插值，并在区间外取端点；固定 `loftElevation` 则给出常角：

```text
lambda = clip((range² - R1²) / (R2² - R1²), 0, 1)
thetaDesired = (1-lambda) × theta1 + lambda × theta2
```

上式先按距离端点排序；重合端点走原生退化分支，不除以零。当前普通 loft 状态的维持条件用原生形式表示为：

```text
u_y × abs(u_y) >= (u_x²+u_z²) × tan(thetaExit) × abs(tan(thetaExit))
norm(omegaLOS)² <= radians(loftTargetOmegaMax)²
```

`thetaExit` 来自 `loftTargetElevation`。在通常的非竖直 LOS 下，第一条相当于目标视线仰角不低于退出角度。满足条件且 loft 状态仍有效时：

```text
KloftRad = loftAngleToAccelMult × 180/pi
aLoftY = KloftRad × (thetaDesired - thetaBody)
requested = aPN
requested_y = max(aPN_y, aLoftY)
```

这不是 `aPN_y + aLoftY`，也不能另乘导弹速度。角度若改用度，等价为：

```text
aLoftY = loftAngleToAccelMult × (thetaDesired_deg - thetaBody_deg)
```

这一路的高抛项没有再乘 PN 的 `G`；但前面的总增益启控判断仍有效。条件失败后，普通 loft 状态退出，不能每步仅凭资源中的 `loftEnabled=true` 自动重新开启。这里不描述未用于当前初始化路径的其他高度控制状态。

## 5. 请求限幅与 PID

过载参数先换算为加速度，飞控再处理参考系及迎角限制：

```text
aMax = reqAccelMax × g0
requestedLimited = requested × min(1, aMax / norm(requested))
```

零向量不除法。没有 `reqAccelMax` 时适配器使用 `propNavAccelMax`，再按已恢复缺省值处理。

在已核对的正 `baseIndSpeed` PID 标量分支，完成坐标投影后的每个受控轴使用：

```text
Vbase = baseIndSpeed / 3.6
s = 1.225 × Vbase / (rho × Vcontroller)
e_k = aRequested_k - aFeedback_k

I_k = clip(I_(k-1) + Ki × s × e_k × dt, -Ilimit, Ilimit)
D_k = D_(k-1) + 48 × (e_k - e_(k-1) - dt × D_(k-1))
u_k = clip(Kp × s × e_k + I_k + Kd × s² × D_k, -1, 1)
```

`Kp/Ki/Kd/Ilimit` 按弹龄从 PID 时间表插值。`I_k` 已经包含 Ki 的累积贡献，不再额外乘一次 Ki。以上标量式不包含参考系变换、迎角限制和低速等其他原生分支；这些仍由完整 PID 执行。

下一步的实际反馈取速度差分，和瞬时受力加速度分别保存：

```text
aFeedback_(k+1) = (v_(k+1) - v_k) / dt
```

原生合同中的速度相减、倒数与乘法按 float32 执行。

## 6. 发动机、减重与 TVC

当前平铺阶段、无环境／随机推力修正、factorIndex=-1 的质量表达：

```text
burnFraction_i(t) = clip((t - start_i) / duration_i, 0, 1)
m(t) = m0 - sum(massLost_i × burnFraction_i(t))
```

阶段开始时间包含点火延迟及此前阶段时长。推力由当前有效阶段决定，不能拿一个双级发动机的第一阶段结束质量当最终燃尽质量。

PL-12 的当前实例（忽略 float32 舍入）：

```text
m(t) = 198 - 15.2×t                  0 <= t <= 2.5
m(t) = 160 - 5.6×(t-2.5)             2.5 < t <= 7.5
m(t) = 132                           t > 7.5

T(t) = 34960 N                       0 < t < 2.5
T(t) = 12880 N                       2.5 < t < 7.5
T(t) = 0                             其他时刻
```

特意保留端点：两个当前构建的原生 PL-12 例程在恰好 `t=0、2.5、7.5` 时均输出零推力，不把这种边界平滑掉。阶段内质量变化则连续。

发动机例程给出体轴力、力臂分量和直接力矩；适配器按调用方合同组合：

```text
FthrustWorld = R(Q) × FthrustBody
lever = length / 2
Mthrust = Mdirect + [0, -lever×Flever_z, lever×Flever_y]
```

`Flever` 是原生输出的力臂分量，不能无条件把全部推力再算一次力臂矩。

## 7. 大气、空速与动压

```text
vAir = v - wind
Va = norm(vAir)
qbar = rho(h) × Va² / 2
Mach = Va / soundSpeed(h)
```

既有游戏标准大气核对表达（显示常数为十进制近似）：

```text
hp = min(h, 18300)
hd = max(h, 18300)
P = 1 - 9.59387e-5×hp + 3.53118e-9×hp²
      - 5.83556e-14×hp³ + 2.28719e-19×hp⁴
rho = 1.225 × P × 18300 / hd

Temp = 288.16 × (1 - 2.27712e-5×hp + 2.18069e-10×hp²
                  - 5.71104e-14×hp³ + 3.97306e-18×hp⁴)
soundSpeed = 20.1 × sqrt(Temp)
```

这些是当前标准环境的解释，不代表天气、海水和所有地图环境覆盖。

## 8. 面积、惯量和控制有效量

令 `d=caliber`、`L=length`、`w=wingAreaMult`：

```text
SL = 0.3 × d × L × w
SD = pi × d² / 4
leverAero = distFromCmToStab / w

Ixx0 = m0 × (d/2)²
Iyy0 = Izz0 = m0 × (L² + 3×(d/2)²) / 12 × inertiaScale
```

这是当前支持资源的初始长弹体属性。不能自行把惯量按当前质量同比缩放，也不能把 Ixx 改成教科书实心圆柱系数 0.5。

控制输出映射到两轴有效量并作合成动压限制：

```text
ch = uHorizontal × finsAoaHor
cv = uVertical × finsAoaVer
cSize = sqrt(ch² + cv²)
K = m0 × g0 × finsLatAccel / (CyK × SL)

qbar × cSize > K 时：
    scale = K / (qbar × cSize)
    ch *= scale
    cv *= scale
```

这是合成向量的限制，不是每轴分别允许额外一份总过载。`finsAoa` 在此是原生控制系数，不能直接称为已恢复的机械舵偏角。

## 9. 阻力与升力的可展示分支

马赫基础函数：

```text
f(M) = 0.308                                     M < 0.61
f(M) = 0.308 + 0.505×(M-0.61)^2.31               0.61 <= M < 1
f(M) = 0.551 + 0.4485×(M-1)^0.505×exp[-5.68(M-1)] 1 <= M < 1.4
f(M) = M / [(0.356×M+2.237)×M-1.4]               1.4 <= M < 4
f(M) = 0.302                                     M >= 4
```

空气中、零角速度、无额外运行时阻力修正的已核对分支：

```text
Fmach = 3.247 × [0.308 + 0.75×(f(M)-0.308)]
D = qbar × SD × CxK × [f(M) + CxAoA × Fmach × sin(alpha)²]
```

当前资源使用 `CxAoA=9` 和 `useCxiMach=true`。关闭后者只令此处 `Fmach=1`，基础项仍计算 `f(M)`。分段原有跳变保留。

常数 Cy 分支的标量形状为：

```text
z = CyK × sqrt(max(0, 1-c²))
CyMagnitude = z                         z <= CyPeak
CyMagnitude = max(0, 2×CyPeak-z)         z > CyPeak
```

`c` 是原生内部有效单位方向的点积。单平面、零角速度、升力上升支路可写成：

```text
Lift = qbar × SL × CyK × sin(alpha)
```

上述标量式不能直接替代所有三维气动力和力矩。非零角速度会通过作用点局部来流、阻尼和力矩改变受力；当前模拟器执行完整原生物理函数处理这些状态。

## 10. 平移、转动与反馈的数学说明

下面是解释受力到运动的连续方程，不声称它们已逐项替代原生离散积分器：

```text
dr/dt = v
dv/dt = (Faero + Fthrust + Fother) / m + g

I × domegaBody/dt = Mtotal - cross(omegaBody, I×omegaBody)
```

转动式写的是恒定惯量的刚体形式，实际原生惯量／惯性耦合分支仍按代码执行。采用 Hamilton、body-to-world、角速度右乘的四元数数学约定时：

```text
dQ/dt = 0.5 × Q ⊗ [omegaBody_x, omegaBody_y, omegaBody_z, 0]
```

原生角速度轴序／符号由适配器合同决定，不把外部右手系数据未经转换代入。数值程序使用原生更新和归一化，不在这里凭连续方程宣称用了欧拉法或 RK4。

当前离线每步顺序是：先用步初状态更新观测和制导／PID，再按步末弹龄计算发动机和质量，随后更新弹体，最后保存速度差分反馈和检查事件。阶段、观测到达等边界会切分 dt；默认 2 ms 不是已证明的完整游戏调度周期。

## 11. 实际转弯能力与输出指标

```text
vhat = v / norm(v)
aParallel = dot(a,vhat) × vhat
aNormal = a - aParallel
trajectoryG = norm(aNormal) / g0
turnRadius = norm(v)² / norm(aNormal)
specificForceG = norm(a-g) / g0
```

速度或法向加速度为零时相应比值需要单独处理。请求 G、气动 G、轨迹法向 G 和非重力比力 G 不混用。

已有单平面、无角速度的静态配平近似：

```text
kappa = 1000 × SL × min(CyK×finsAoa, CyPeak) / (m×g0)
B = finsLatAccel × m0/m
staticAeroG ≈ min(kappa × qbar_kPa, B)
```

该近似用来比较指定条件下的静态气动能力，不是每步动态硬上限，也不包括 TVC 的全部贡献。

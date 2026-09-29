# 图2 附加"俯视轨迹"面板 —— 实施计划

> 状态：**计划，未实施**（2026-09-30 用户口述后落盘；用户当晚不实施）。
> 上游依据：`docs/MANEUVER-TARGETS.md` §8（想定可行性、全部实测数字、`lockDistance` 口径）。
> 模型层已入仓：`src/missile_sim/flightpath.py` + `tests/test_flightpath.py`（22 项）。

## 0. 拍板与范围（用户 2026-09-30 口述）

| 决定 | 内容 |
| --- | --- |
| **不做** β/γ 主导交换的解析临界点 | 沿用现有**等时线 + 斜率**读法即可直观判断工况；不新增任何解析判据 |
| **图一保持不变** | `fig_isotime_plane_*` 的画法、接口、测试、字节一律不动 |
| **图二附加俯视轨迹** | 敌机 + 导弹航迹，标明关键节点，**不同段用颜色区分** |
| 3D 渲染 | 记入后续（用户："后续安排上如果可行"），**不在本计划** |

## 1. 绕不过去的事实：往同一张画布加面板 ⇒ 现有图2 字节必变

现有图2 是**手工调过的固定版面**：`FIG_SIZE = (12.0, 6.8)`、主轴 `AX_RECT = (0.075, 0.175, 0.822, 0.700)`、
色标 `CAX_RECT = (0.905, 0.175, 0.013, 0.700)`，题头在 `add_bg_header()`、脚注锚在
`xlabel_bottom_fig()`。加第二个轴就要改画布高度/宽度或主轴矩形，**左面板的像素必然变化**，
于是 `figures/fig_bg_plane_default.{png,pdf,svg}` 与相关字节测试、manifest 全部要重基线。

用户要的是"图二额外附加上"，所以两条路，**待拍板**：

* **方案 A（推荐）**：现有 `fig_bg_plane_default.*` **逐字节不动**；新增一张
  `fig_bg_traj_<tag>.*` 专画俯视轨迹（新开关），再出一张**拼版预览**
  `fig_bg_combo_<tag>.*`（上=平面、下=轨迹）只供阅读，不进字节测试。
  ⇒ 交付物不破、测试不用重基线，代价是"附加"体现在拼版图与文档里而不是默认文件名。
* **方案 B**：直接把 `fig_bg_plane_default.*` 改成两面板（画布加高，如 `(12.0, 10.2)`），
  一次到位最符合"附加"，但要**重基线**图2 的字节测试、`results/bg_*.json` 的产物清单与
  `docs/DISTRIBUTION.md` 里引用的文件尺寸。

## 2. 俯视轨迹面板要画什么

### 2.1 坐标系与航向（内核口径，必须照抄）

内核 `Target.velocity()`：**`heading 0 = +x`、`90 = +z`、`180 = −x`**。本题设里：

* 载机在 x 正侧，敌机从 +x 迎头飞向 −x（`start_heading_deg = 180`）；
* crank 段 = 110°（即从迎头转 70°，`cw` 方向）；
* 39 段（正侧方）= **90°** ⇒ 在俯视图里是一条**平行于 z 轴**的直线，与发射轴垂直；
* 所以"110° 的 crank 段比 39 段偏 20°"这件事，只有**等比例坐标**（`set_aspect("equal")`）
  才看得出来 —— 这是本面板唯一的硬性绘图要求。

### 2.2 数据来源（都已验证存在）

`Shot.rows` 的列：`time_s`、`missile_x_m` / `missile_z_m`、`target_x_m` / `target_z_m`、
`range_m`、`speed_m_s`（⚠ 导弹位置**没有** `x_m` 这个名字）。时间栅格 `dt = 1/48 s`。
节点时刻一律**查表取得**，不自己另算，避免与求解器出现第二套时间口径。

### 2.3 ⚠ 震荡在俯视图里**看不见**（必须先和用户说清）

用户原话是"以一个**固定频率和振幅轨迹上下震荡**飞行"。若"上下"指**高度方向**的振荡，
那么俯视图（x–z 平面）里**完全看不到**它 —— 只能看到一条平滑的 39 段直线。
三个选项（待用户定，见 §7）：

1. 俯视图只画水平面，震荡用**文字注明**"震荡 ±A°/f Hz（在高度方向，本图不可见）"；
2. 俯视图 + **一个很扁的侧视图 inset**（x–y 或时间–高度），只画目标高度曲线；
3. 若用户其实指**水平面内左右摆动**，则俯视图直接可见，无需 inset。

## 3. 节点与分段（本图的定义）

### 3.1 关键节点（用户点名的 5 类）

| 节点 | 由什么决定 | 图上怎么画 |
| --- | --- | --- |
| **发射**（隐含起点） | `t = 0`，双方初始位置 | 导弹航迹起点 + "我方"方向标注 |
| **开始转入 crank** | `t_crank`（用户可调） | 目标航迹上的实心圆点 + 文字 `t=..s` |
| **crank 段** | 转弯段 + 110° 保持段（见 3.2） | 一整段**独立颜色** |
| **导引头开机** | 首次 `range ≤ lockDistance`（**一遍法**反求，§8.2/§8.8.4） | 导弹航迹上的空心大圆 **+ 一条连到目标当时位置的细线**，标注 `开机 · R = 16.0 km`（比单纯一个点信息量大得多） |
| **开始由 crank 转入 39** | 默认 = 开机时刻；用户可给**触发延迟**（§7 待确认） | 目标航迹上的实心圆点 |
| **39 段** | 转入 39 的转弯段 + 90° 保持段 | 一整段**独立颜色**，直到命中/结束 |
| **命中 / 结束** | `shot.hit` / `t_hit` / `lifetime` | 命中点星标（或脱靶最近点标注脱靶量） |

### 3.2 分段表（颜色建议，PNG/PDF/SVG 通用，不依赖字体）

分段**直接由 `PathSchedule.table()` 导出的分段常值 ω 表驱动**，不另做时间算术
（避免出现第二套口径；这也是 §8.3 那个"腿重叠"坑的防线）：

| # | 段 | 时间区间 | 航向 | 颜色键 |
| --- | --- | --- | --- | --- |
| 1 | 直飞（迎头） | `[0, t_crank)` | 180° | `grey` |
| 2 | 转入 crank（转弯） | `[t_crank, t_crank+Δ1)` | 180° → 110° | `orange` |
| 3 | crank 保持 | `[t_crank+Δ1, t_beam)` | 110° | `red` |
| 4 | 转入 39（转弯） | `[t_beam, t_beam+Δ2)` | 110° → 90° | `teal` |
| 5 | 39 保持 | `[t_beam+Δ2, 结束)` | 90° | `blue` |
| — | 导弹航迹 | `[0, t_hit / 结束]` | — | 深灰细虚线 + 命中点 |

`Δ1 = radians(crank_deg)/(g·g0/v)`（9G、70° ⇒ 4.15 s）、`Δ2 = radians(20°)/ω2`。

⚠ **"没转完"在本图里天然可见**：若 `t_beam < t_crank + Δ1`，则第 2、4 段的指令在**同一时刻**
下达，后一条截断前一条（`flightpath` 的既定语义），目标从 180° **一次弧**转到 90°，
**没有 110° 平台段（第 3 段消失）** —— 这正是"实战中没能完成 39 干扰 ⇒ 被击落"的可视化。
图例里要专门给这种情况一个条目（如"crank 未转完（直接被压成一条弧）"）。

## 4. 数据契约（"输入/输出 API 化"的落点）

新增一个**纯数据**的中间层，供出图、CSV、JSON 三方共用（沿用仓库既有风格：
dataclass + `as_dict()`，出图模块只吃这一种输入）：

```python
@dataclass(frozen=True)
class Segment:            # 目标航迹的一段
    t0_s: float; t1_s: float
    kind: str             # straight | turn | hold
    label: str            # 直飞 / 转入crank / crank保持 / 转入39 / 39保持
    heading_deg: float
    color_key: str

@dataclass(frozen=True)
class TrajMark:           # 一个节点
    name: str             # launch | crank_start | crank_done | seeker_on | beam_start | beam_done | end
    t_s: float
    note: str             # 图上的文字，如 "开机 · R=16.0 km"

@dataclass(frozen=True)
class ScenarioRun:
    scene: Scene                    # 输入工况（含 maneuvers）
    schedule: PathSchedule          # 目标航向指令（模型层对象）
    shot: Shot                      # 求解器输出（hit / t_hit / miss_m / event / backend）
    rows: list                      # 求解器原始输出（时间栅格，画图与查表都靠它）
    segments: list[Segment]
    marks: list[TrajMark]
    anchor: dict                    # lock_distance_m / mode / t_beam_s / completed(bool) / heading_at_beam_deg
    missile: str                    # 弹池短名（决定 lockDistance 与 (β, γ)）
    beta: float; gamma: float
```

落盘（沿用 `record.py`）：`results/bg_traj_<tag>.json`（manifest + 全部分段/节点）+
`results/bg_traj_<tag>_target.csv` / `_missile.csv`（航迹点）。**图里每个节点时刻都能在
CSV 里查到**，这是"可复核"的验收条件。

## 5. 实现步骤（每阶段的验收）

**P1 模型层补齐（不改内核、不改 `Scene`）**
* `PathSchedule.segments()` → 由 ω 表折出 `[Segment]`（含"被截断的转弯"这种情形）；
* 单测：直飞段唯一；正常 crank→39 出 5 段；**没转完**出 4 段（无 110° 保持）；
  相邻段首尾相接且覆盖 `[0, duration_s]`；段数与 `table()` 行数一致。
* 验收：`python tests\run_tests.py -k flightpath` 全绿（22 → 约 27 项）。

**P2 想定运行器（要动求解器，所以放 `workflow.py`）**
* 表单字段 → `PathSchedule` → `maneuvers`；**锚点用一遍法且必须用同一枚弹反求**（§8.8.4）；
* 跑正式轨迹（带 39 腿）→ 组装 `ScenarioRun`；
* ⚠ 预跑与正式跑是**两个不同 `Scene`**（`maneuvers` 不同），各自进缓存是**正确**的，
  `CACHE_SCHEMA` **不用动**（第一版不碰 `Scene` 契约：`turn_rate_rad_s` / `samples`
  两条通道本阶段**不接**）；
* 输出新增两个量：**`anchor.completed`（是否转完）** 与 **`anchor.heading_at_beam_deg`**
  （开机时实际航向）—— 用户口径要求的"输出量"，不是坏参数（§8.8.2）；
* 验收：PL-12 / 16 km / t_crank=8 / 70° / 9G 一条端到端跑通，节点时刻与
  `MANEUVER-TARGETS.md` §8.8.5 记录的数字（命中 69.554 s）逐位对上。

**P3 出图**
* `figures.plot_bg_trajectory(run, *, out_base, ...)`：等比例俯视面板 +
  分段着色 + 节点标注 + 图例 + 命中/脱靶标注；
* **局部放大 inset**：把"开机 → 转 39"那一小段放大（否则在 50 km 量级里那 1.2 s 的转弯
  看不出来）；x 范围按弹道自适应，z 范围按目标航迹自适应并留边；
* 布局按 §1 的方案 A 或 B；
* 验收：三格式字节可复现（沿用 `savefig` 去时间戳 + `normalize_svg_ids`）；
  两次运行图字节一致；`--bg-no-scan` 时轨迹面板照常出。

**P4 入口**
* `BgRequest` 增一个可选嵌套 `traj`（"字段名即 CLI 参数名"的既定规矩，
  外部名沿用 `--bg-*` 前缀与 `_BG_ALIASES` 折名机制）：
  `--bg-traj`（开关）、`--bg-traj-missile`、`--bg-traj-crank-start`、
  `--bg-traj-crank-deg`、`--bg-traj-g`、`--bg-traj-beam-deg`、
  `--bg-traj-lock-distance`（默认取该型弹 `guidance.lockDistance`）、
  `--bg-traj-trigger-delay`、`--bg-traj-weave-amp-deg`、`--bg-traj-weave-hz`；
* WebUI 同名表单字段 + 说明文字（默认值、单位、"震荡在高度方向时本图不可见"的提示）；
* `README.md` 补一节"怎么看这张俯视轨迹图"。

**P5 文档与提交**
* `docs/MANEUVER-TARGETS.md` §8.7 改成"已实施"并指向本计划；
* `docs/SOLVER-API.md` §4 补"`lockDistance` 内核不读、由外壳消费"这条能力边界；
* `NOTES.md`（追加）、`AGENTS.md`（模块职责 + 新坑）、`docs/RESTART-PLAN.md`（§12）；
* 一次提交，只带上本阶段文件；全量 `python tests\run_tests.py`。

## 6. 已知坑（实施时逐条对照）

1. **加面板必然改现有图2 的字节**（§1）—— 先拍板方案 A/B 再动手。
2. **`rows` 没有 `x_m`**，是 `missile_x_m`；`speed_m_s` 不是 `missile_speed_m_s`。
3. **`t_hit` 可能不在时间栅格上**（事件时间），画到命中点要单独取该时刻的位置，
   不能只截到最近栅格点。
4. **脱靶 / `lifetime` 的轨迹会一直画到 `duration_s`**（39 段可能几十秒），
   必须裁范围与图例说明，否则空白一片。
5. **等比例不能省**：不等比例时 110° 与 90° 看起来一样，图的结论就错了。
6. **震荡的可见性**（§2.3）—— 最容易被误解的一点，图注必须写清。
7. **"没转完"不要当成错误输入**：`crank_beam()` 已按"开机早于 crank ⇒ 直接转正侧方"
   处理（`t_beam = max(t_beam, t_crank)`），出图要把这种情况画成一条弧并在图例里解释。
8. **开机时刻的锚点必须用同一枚弹反求**（§8.8.4，弱弹差 1.7 s，边界附近会翻转命中）。
9. **不要把预跑结果当成最终结果**返回（两个 Scene 各自的缓存条目要分清）。
10. **脚注/题头是手工锚定的**（`add_bg_header` / `xlabel_bottom_fig`）：改画布尺寸后
    脚注会盖住轨迹面板，要同步算新的 `y0`。

## 7. 待用户拍的四件事

1. **方案 A 还是 B**（新增文件 + 拼版预览 / 直接改默认图并重基线）？
2. **震荡是高度方向还是水平方向**？若高度 ⇒ 俯视图不可见，要不要加侧视 inset？
   另外**默认振幅/频率**等你游戏里的经验数据（在那之前默认关闭，不自造经验值）。
3. **"导引头开机"与"开始转入 39"是否同一时刻**？默认同一时刻（触发延迟 0 秒），
   若实战里是"看到 RWR 告警后才转"则给一个延迟。
4. **俯视轨迹跑哪几型弹**？单型（PL-12，图上已有它的圈标记，两个面板天然对应）还是
   11 型叠一张（会很乱，不建议）？

## 8. 明确不做

* 不算 β/γ 主导交换的解析临界点（用户明确：等时线 + 斜率够了）。
* 不改图一（`fig_isotime_plane_*`、`PlaneRequest`、相关测试与字节全不动）。
* 不改内核（`vendor/` 只读，`SOLVER_SHA256` 不变）。
* 本阶段**不接** `turn_rate_rad_s` / `samples` 两条通道（第一版只需 `maneuvers`，
  所以 `Scene` / `CACHE_SCHEMA` 都不用动）。
* 不做 3D 渲染（后续）。
* 不做 β–γ 网格上的"成败图"（用户此轮的取向是等时线 + 斜率 + 轨迹示例，
  原候选仍留在 `docs/MANEUVER-TARGETS.md` §8.7 里备用）。

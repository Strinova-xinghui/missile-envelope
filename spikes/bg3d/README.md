# `spikes/bg3d` —— β–ginv–ΔV 三维图可行性 spike（纵轴 2026-10-04 起为 `ginv = 1/γ`）

**结论一句话**：**技术上能出，但这个想定的三维图信息量有限** —— 等值面确实能提（
`marching_tetrahedra` 自写，零新依赖，5000 工况提 6 张面 **≈0.1 s**——口径见
`out/iso/iso_report.json` 的 `timing`，该数随 CPU 负载波动，别跨机器比），ΔV 方向**一阶近乎线性**
（逐列直线拟合 `R²` 中位 0.989、斜率 `b ≈ −0.0336 s/(m/s)`、相对散布 3.0%），
**但有一层可测的系统性曲率**（加二次项后残差 0.5519 s → 0.0582 s，曲率抬升中位 1.5449 s
≈ 该列 ΔV 效应的 9.2%，459/459 列同号）—— 所以是"**一条斜率 + 约一成的弯曲**"，不是"只有一个数"；
图在等长三轴 + 半透明下能看（`out/iso/v8_cube_six.png`），但按真实跨度画就是一块板
（`out/iso/v3_six.png`）。详见 [`docs/FIG-BG3D-FEASIBILITY.md`](../../docs/FIG-BG3D-FEASIBILITY.md)。

## 跑法（在 worktree 根，先设环境）

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python spikes\bg3d\probe_math.py                    # 7 组解析自检（秒级，不出图）
# ⚠ 三个档**分开跑**：--grid both 按 quick→coarse→fine 跑，后档会继承前档缓存，
#    重跑时墙钟接近 0（记录里的 n_run/n_cached 能看出来）；要冷跑数字先删 results/cache/fast.json
python spikes\bg3d\bg3d_scan.py --grid quick         # 126 工况，冷跑约 4.3 s
python spikes\bg3d\bg3d_scan.py --grid coarse        # 924 工况，冷跑约 22 s
python spikes\bg3d\bg3d_scan.py --grid fine          # 5049 工况，冷跑约 121 s
python spikes\bg3d\bg3d_iso.py --scan fine --same-process   # 提面 + 9 变体 + 可读性 + 同进程复现，约 100 s
# ⚠ 本 spike 自带 `_box_aspect()`（原来在 `figures.py`，task-27 删静态 3D 预览时一并删了）：
#   非交付物按「自包含」处理，**不要**为了让它跑起来把这个 helper 塞回 `figures.py`
python spikes\bg3d\bg3d_iso.py --scan fine --cross --cross-dir .tmp_test\bg3dA `
       --json spikes\bg3d\out\crossA.json            # 跨进程字节复现：A/B 两次，各约 50 s
```

判据：`python tests\run_tests.py -k bg3d_spike`（26 项，约 2 s，**不跑长扫描、不碰 `results/`**）。
⚠ 文件名含 `bg3d`，所以既有的 `-k bg` 也会收集到它（都是纯函数）。

## 产物

| 文件 | 入库 | 内容 |
| --- | --- | --- |
| `out/scan_quick.json` / `scan_coarse.json` / `scan_fine.json` | ✓ | 网格 + 立方体 + 命中掩码 + `dv_measured` + 摘要（`Bg3Scan.record()` 的逐字节可读回格式） |
| `out/iso/iso_report.json` | ✓ | 每个面的三角形数/面积/面上 t_hit 散布/耗时；ΔV 依赖；**一次+二次**线性体检；9 个变体的字节数与 sha256；同进程/跨进程复现；可读性 z-buffer 表 |
| `out/iso/iso_surfaces_sample.json` | ✓ | 几何**小样**（1 张真等值面 + 1 张柱面、3 位小数，0.29 MB）：给交互前端的最小格式样本 |
| `out/iso/v3_six.png`、`v4_two_flavors.png`、`v6_slices.png`、`v8_cube_six.png`、`v9_cube_cutaway.png` | ✓ | 可读性取证的 5 张真实截图（PNG 元数据实测 **299.9994 ≈ 300 dpi**） |
| `out/crossA.json` / `crossB.json` / `crossSame.json` | ✓ | 跨进程 / 同进程的 sha256 记录；**17 条里只有 5 条（上面那 5 个 PNG）入库可复核**，每条带 `in_repo: true/false` 标记 |
| `out/iso/iso_surfaces.json`（2.1 MB）、`v1/v2/v5/v7` 的 PNG 与全部 PDF/SVG（≈13 MB） | ✗ | **脚本 1 分钟可重出**，不入库（照 `spikes/fig3d` 只留取证子集的做法）⇒ 记录里剩下那 **12 条**必须先本地重出才能核 |

⚠ **别把复现记录的 17 条当成 17/17 可核**：新克隆只能直接核对入库的那 **5/17**；
`v1/v2/v5/v7` 的 PNG 与所有 SVG/PDF 都要先跑一次 `bg3d_iso.py`。
判据 `test_in_repo_flags_match_git_and_cover_five_of_seventeen` 会把 `in_repo` 标记与
`git ls-files spikes/bg3d/out/iso` **双向**对齐（标 true 的必须真入库；入库的必须标 true）。

**一个字节都不进 `results/`**：新产物全在 `spikes/bg3d/out/`；扫描只用了仓库既有的
`results/cache/<tier>.json`（gitignore，正常副作用）。

## 9 个画法变体

| 变体 | 画法 | 要说明的事 |
| --- | --- | --- |
| `v1_one` | 1 张面，真实跨度比例 | 下界参照 |
| `v2_three` | 3 张面，不透明 | 3 张时第 3 张只剩 50% 可见 |
| `v3_six` | 6 张面，不透明，真实跨度比例 | **就是"糊成一块板"的证据**（第 6 张只剩 18% 可见） |
| `v4_two_flavors` | 左真等值面 / 右拉伸柱面 | 两种"等时面"口径长得像、含义不同 |
| `v5_layers_and_pin` | 3 张面 + ΔV=950 薄片 + 弹池散点 | ΔV 是新加的那根轴 |
| `v6_slices` | 3 个 ΔV 切片云图 + 1 张面 | ΔV 依赖有多大（颜色 = t_hit） |
| `v7_2panel` | 左 2D 等时线 / 右 3D 三张面 | 同一份数据的两种看法 |
| `v8_cube_six` | **等长三轴 + 半透明 6 张面 + 色条** | 唯一能数清 6 层的画法 |
| `v9_cube_cutaway` | 等长三轴 + 4 张面 + 剖切面 + 色条 | 看单张面怎么在 ΔV 上斜 |

色条（只有 `v8`/`v9` 有）标的是**等值面层级 `t_hit [s]`**（42~52 s 六格），用
`ListedColormap` + `BoundaryNorm` 取 `COLORS` 原色 ⇒ 每一格与它对应的那张面颜色完全一致；
它不是多余的：六张面沿 ΔV 分层只说明"上下次序"，色条才把"层"钉成"秒"。ΔV 轴本身已编码
次序，所以色条不重复标 ΔV；其余变体保持无色条 —— 它们要么只画一两张面（层级写在标题里），
要么用颜色表达**云图数值**而不是层级。

## 三个已知坑（都在模块注释与测试里钉着）

1. **`_sample_grad` 的坐标口径**：`_cubes_vec` 按数组轴序 `(ΔV, ginv, β)` 取点，三个分量必须传
   **同一个点**。曾经把「该分量的坐标」当 `z` 递进去（β 分量拿到 `(β, ginv, β)`），β 导数于是恒为
   `0.0`（越界兜底），**绕向永远不会被修正** —— 平面场一半法向反了，而球面因为三根轴恰好都是
   −2…2 而"看起来没事"。判据：`test_orientation_survives_unequal_axis_ranges`（6×2×4 椭球，
   混向会让有向体积掉到 0 附近）。
2. **`sample_cube` 的边界面**：正好压在 `ΔV = dv[-1]` 上的顶点属于**最后一个格子**
   （格内相对位置 1.0），必须插得出值。丢掉的后果是"凡被立方体外表面切出来的面都只量到内部顶点"，
   数字还挺合理 —— 当初就是这样把拉伸柱面的散布从 17.6 s 量成了 0.2 s。
3. **墙钟 ≠ 真解算量**：`summary.elapsed_s` 是本次运行的墙钟，**命中缓存的工况不真解算**。
   `--grid both` 按 quick→coarse→fine 跑，后档继承前档缓存；**重跑**任何档都会得到接近 0 的墙钟
   （本 spike 初版就在这里栽过：`scan_quick.json` 被一次全命中的重跑覆盖成 0.0247 s，
   和同表的 23.5/24.0 ms 并排会把读者带沟里）。所以记录里加了 `summary.n_run` / `n_cached`
   两个计数，报数字前先看它们。

## 交互那条腿（**没做**）

原计划再做一份手写 WebGL2 的交互前端（复用 `spikes/fig3d/fig3d_viewer.html` 的相机/拖拽代码）。
**没做**，原因写在 `docs/FIG-BG3D-FEASIBILITY.md` §6：本会话拿不到可用的委派
（`spawn_teammate` 只有 Lead 能调；`subagent` 在本层报 `depth 2 exceeds maxDepth 1`），
静态那条腿已经吃满时间。几何 payload（`iso_surfaces.json`，2.1 MB）与画法结论都已落盘，
前端可以照 `spikes/fig3d/README.md` 的浏览器取证流程续做。

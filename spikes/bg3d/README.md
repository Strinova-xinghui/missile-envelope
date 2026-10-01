# `spikes/bg3d` —— β–γ–ΔV 三维图可行性 spike

**结论一句话**：**技术上能出，但这个想定的三维图信息量很小** —— 等值面确实能提（
`marching_tetrahedra` 自写，零新依赖，5000 工况提 6 张面 ≈ 1.1 s），可它们是一族
**近似平行的板**（逐列直线拟合 `R²` 中位 0.989），ΔV 轴上真正独立的东西只有斜率
`b ≈ −0.0336 s/(m/s)` 一个数；图在等长三轴 + 半透明下能看（`out/iso/v8_cube_six.png`），
但按真实跨度画就是一块板（`out/iso/v3_six.png`）。详见
[`docs/FIG-BG3D-FEASIBILITY.md`](../../docs/FIG-BG3D-FEASIBILITY.md)。

## 跑法（在 worktree 根，先设环境）

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="src"
python spikes\bg3d\probe_math.py                    # 7 组解析自检（秒级，不出图）
python spikes\bg3d\bg3d_scan.py --grid quick         # 126 工况，约 5 s（验证链路）
python spikes\bg3d\bg3d_scan.py --grid both          # 粗 924 + 细 5049，冷跑约 143 s
python spikes\bg3d\bg3d_iso.py --scan fine           # 提面 + 9 个变体 + 可读性量测，约 50 s
python spikes\bg3d\bg3d_iso.py --scan fine --cross --cross-dir .tmp_test\bg3dA `
       --json spikes\bg3d\out\crossA.json            # 跨进程字节复现：A/B 两次
python spikes\bg3d\bg3d_iso.py --scan fine --same-process ...   # 同进程连出两次
```

判据：`python tests\run_tests.py -k bg3d_spike`（22 项，约 9 s，**不跑长扫描、不碰 `results/`**）。
⚠ 文件名含 `bg3d`，所以既有的 `-k bg` 也会收集到它（都是纯函数）。

## 产物

| 文件 | 入库 | 内容 |
| --- | --- | --- |
| `out/scan_quick.json` / `scan_coarse.json` / `scan_fine.json` | ✓ | 网格 + 立方体 + 命中掩码 + `dv_measured` + 摘要（`Bg3Scan.record()` 的逐字节可读回格式） |
| `out/iso/iso_report.json` | ✓ | 每个面的三角形数/面积/面上 t_hit 散布/耗时；ΔV 依赖；线性体检；9 个变体的字节数与 sha256；可读性 z-buffer 表 |
| `out/iso/iso_surfaces_sample.json` | ✓ | 几何**小样**（1 张真等值面 + 1 张柱面、3 位小数，0.29 MB）：给交互前端的最小格式样本 |
| `out/iso/v3_six.png`、`v4_two_flavors.png`、`v6_slices.png`、`v8_cube_six.png`、`v9_cube_cutaway.png` | ✓ | 可读性取证的 5 张真实截图（160 dpi） |
| `out/crossA.json` / `crossB.json` / `crossSame.json` | ✓ | 跨进程 / 同进程的 sha256 记录 |
| `out/iso/iso_surfaces.json`（2.1 MB）、其余 4 个变体的 PNG 与全部 PDF/SVG（≈13 MB） | ✗ | **脚本 1 分钟可重出**，不入库（照 `spikes/fig3d` 只留取证子集的做法） |

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
| `v8_cube_six` | **等长三轴 + 半透明 6 张面** | 唯一能数清 6 层的画法 |
| `v9_cube_cutaway` | 等长三轴 + 4 张面 + 剖切面 | 看单张面怎么在 ΔV 上斜 |

## 两个已知坑（都在模块注释与测试里钉着）

1. **`_sample_grad` 的坐标口径**：`_trilin` 按数组轴序 `(ΔV, γ, β)` 取点，三个分量必须传
   **同一个点**。曾经把"该分量的坐标"当 `z` 递进去（β 分量拿到 `(β, γ, β)`），β 导数于是恒为
   `0.0`（越界兜底），**绕向永远不会被修正** —— 平面场一半法向反了，而球面因为三根轴恰好都是
   −2…2 而"看起来没事"。判据：`test_orientation_survives_unequal_axis_ranges`（6×2×4 椭球，
   混向会让有向体积掉到 0 附近）。
2. **`sample_cube` 的边界面**：正好压在 `ΔV = dv[-1]` 上的顶点属于**最后一个格子**
   （格内相对位置 1.0），必须插得出值。丢掉的后果是"凡被立方体外表面切出来的面都只量到内部顶点"，
   数字还挺合理 —— 当初就是这样把拉伸柱面的散布从 17.6 s 量成了 0.2 s。

## 交互那条腿（**没做**）

原计划再做一份手写 WebGL2 的交互前端（复用 `spikes/fig3d/fig3d_viewer.html` 的相机/拖拽代码）。
**没做**，原因写在 `docs/FIG-BG3D-FEASIBILITY.md` §6：本会话拿不到可用的委派
（`spawn_teammate` 只有 Lead 能调；`subagent` 在本层报 `depth 2 exceeds maxDepth 1`），
静态那条腿已经吃满时间。几何 payload（`iso_surfaces.json`，2.1 MB）与画法结论都已落盘，
前端可以照 `spikes/fig3d/README.md` 的浏览器取证流程续做。

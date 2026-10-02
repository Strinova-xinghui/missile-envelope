# -*- coding: utf-8 -*-
"""把本轮（3D 可行性侦察）的一节**字节追加**到 NOTES.md。

⚠ **跑过一次就够了 —— 别再跑第二遍**：它是**追加**，重跑会在 NOTES.md 末尾
  再粘一份同样的小节（不报错，只是重复）。第二次追加（两条交互硬要求那节）走的是
  同目录下另一个一次性脚本，已删（内容已在 NOTES.md 里，见"3D 可行性补遗"那节）。

⚠ 仓库规矩：`NOTES.md` 里有 1~2 个 CR 的连续段，**任何整篇重写都会把行尾冲掉**（整文件 diff）。
所以这里只 `open("ab")` 追加，现有字节一个都不动。跑完用
`git diff --stat` vs `git diff -w --stat` 自检两者一致。

⚠ 路径一律用**绝对路径**：pwsh 的 `cd` 不同步 .NET 的 `CurrentDirectory`，
   相对路径的 `[System.IO.File]::*` 会打到别的工作树去（本会话真中过一次）。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTES = ROOT / "NOTES.md"

SECTION = """
## 2026-10-01 · 三张图 3D 化可行性（分支 `3d-viz` / worktree `E:\\导弹包线图-3d`，基线 `73eb2bc`）

**用户拍板**：图3 **真 3D** + WebUI 里**可交互旋转（离线 WebGL）**；图1/图2 **不 3D 化**。
完整报告见 `docs/FIG3D-FEASIBILITY.md`，可重跑证据见 `spikes/fig3d/`，smoke 用
`python tests\\run_tests.py -k fig3d`（11 项，约 1 s，**不跑求解器**）。

### 结论（哪张图值得 3D）

* **图3 值得，而且是唯一值得的**：它的第三维是**真实空间高度**（本工况弹从 10000 m 爬到
  12847 m），俯视图把这一维**完全压掉**；`v03`（三维+地面投影）比 2D 对照只多 **0.5 s / +141 kB PNG**。
* **图1 / 图2 不值得**：第三维是 `t_hit`，**等时线 + 颜色条已经完整表达**它。实测图1 3D 曲面
  527 kB vs 2D 209 kB（+152%），信息量没变；图2 更差 —— β≈2500~3100 与 γ≈0~180 **差 1~2 个量级**，
  真实跨度做 `box_aspect` 后 γ 被压成一条线，不做就几何失真。
* **plotly 否决**：能装（有网），但包 **56.12 MB**、`plotly.min.js` **4 815 814 B（4.8 MB）**，
  且 7.1.0 的 `graph_objects` 顶层 `import narwhals.stable.v1` ⇒ `--no-deps` 装完当场 ImportError。
  与"免安装分发（134.4 MB 解压 / 54.8 MB zip）+ 尽量不引新依赖"两条约束同时冲突。

### 实测（本机 Python 3.14.7 / matplotlib 3.11.1 / numpy 2.5.2 / Node 24 / Edge）

* **mplot3d 三格式字节可复现：13/13 变体全绿** —— 同进程连出两次、**跨进程各出一次**
  （`PYTHONHASHSEED` 一个随机一个 `1`、间隔 1.2 s、输出目录不同）逐字节一致。
  ⚠ 这条**推翻了"mplot3d 的 z 排序容易不稳"的先验担忧**：画家算法的 `zsort` 深度是**纯浮点函数**，
  真正随机的只有 matplotlib 的 SVG id 盐 `svg.hashsalt`，而它**已被 `figures.setup_style()` 钉死**。
  但要有条件地引用：只在"图元不交叠/不相切"的场景成立。
* **最坏变体是"逐点着色"**：`scatter` 按时间着色 3300 点 ⇒ PDF **783 kB** / SVG **690 kB**，
  是 2D 对照的 **22 倍**。**要做 3D 就用分段线，别用逐点 scatter。**
* **现有 `plot_traj_preview_3d` 已具备可复现性**：`v13` 两方位角 160 dpi ⇒ 272.7 kB PNG /
  2.80 s，与仓库里已交付的 `figures/fig_traj_preview_default.png`（245 810 B）同量级。
* **手写 WebGL2 交互查看器（零第三方 JS）**：模板 **17 662 B**（JS 346 行）、单文件离线版
  **44 418 B**、`slim` 数据 **30 421 B**（320 点；`full` 319 906 B）；顶点装配 **1.055 ms/场**、
  每帧矩阵 **1.280 µs**、GPU 缓冲 47.9 kB。**无头 Edge + SwiftShader 实测渲染出正确画面**
  （`spikes/fig3d/out/c/shot.png`）。`file://` 单文件版**零请求**、零 CDN。
* ⚠ **帧率没量到**：无头 `--virtual-time-budget` 下 `requestAnimationFrame` 走虚拟时钟，
  量出来是假数字 —— 所以文档里**不给帧率**，只给"渲染成功"+CPU 量测。

### 落地口径（真做要改什么）

* **静态 3D**：`figures.py` 新增 `plot_traj_3d()`（复用 `_box_aspect`/`TRAJ_COLORS`/`save_formats`）+
  `workflow.TrajRequest.view` + `cli --traj-view` + `webui_static` 表单开关 + **新文件**
  `tests/test_fig3d_plot.py`（3D 专用物化判据），≈ **2~3 人日**。
* **交互视图**：`webui_static/viewer3d.{html,js}`（把 spike 的查看器拆开）+ `GET /api/traj/<tag>.json`
  （形状见文档 §3.3）+ 唯一的坐标口径出口 `traj_to_viewer_payload()` + 新
  `tests/test_webui_viewer3d.py`（含"JS 里不许出现 `http(s)://`"这条离线判据），≈ **2.5~3 人日**。
* 现有 8 项物化判据 / `-k figures_repro` / `-k printed_text` / `make_dist.py` **都不需要改**；
  3D 的注记可读性要**新增**一组 3D 判据（现有 23 项全是 2D 像素几何，管不到 3D 遮挡）。

### 本阶段的边界

只新增 `docs/FIG3D-FEASIBILITY.md`、`spikes/fig3d/**`、`tests/test_fig3d_spike.py`；
**没有**改动 `src/**`、`figures/**`、`results/**`、`tests/test_traj*.py`、`tests/test_webui*.py`。
入库产物 **0.52 MB**（其余 117 个可重建文件由 `spikes/fig3d/clean_out.py` 清掉）。
"""


def main() -> int:
    if not NOTES.is_file():
        return 1
    before = NOTES.stat().st_size
    data = SECTION.replace("\n", "\r\n").encode("utf-8")
    with NOTES.open("ab") as f:                     # ← 只追加，绝不重写
        f.write(data)
    after = NOTES.stat().st_size
    print(f"NOTES.md {before} → {after}（追加 {after - before} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

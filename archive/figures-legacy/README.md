# 早期图垃圾站（重建前的遗留产物）

这里是 **`restart` 分支重建（2026-09-27）之前**旧外壳产出的图，共 **23 个文件**，
最后一个提交都在 **2026-09-25**（`28f7c7c` / `794d63b` / `562a63e` / `d7d972c` / `9d1aead` / `350bb5c` /
`db019fb` / `ac648f4`）。2026-10-01 从 `figures/` 整体 `git mv` 到这里，目的只是**别和正式交付的三张图混在一起**。

## 为什么它们再也重不出来

旧的两代引擎（`pro` = unicorn 跑原生 ELF、`flash` = 本仓库自己的公式引擎）连同它们的脚本
已经随 `restart` **整体删除**（`scripts/pipeline.py`、`scripts/workflow.py`、`scripts/workflow_web.py`、
`scripts/make_missile_bc_overlay.py` 等，见 `docs/RESTART-PLAN.md` §2）。
也就是说：这些图**没有现成脚本能复现**，既不是交付物，也不参与任何测试（已确认 `tests/` 里
没有一处引用它们的文件名，也没有断言"`figures/` 里有哪些文件"）。

## 与 `results/` 里旧产物的关系

`results/missile_shot_crossplot.json`、`results/workflow_clitest.json`、`results/workflow_demo.json`
是同一批旧跑的 manifest，里面写的路径仍是**移动前**的 `figures/...`（例如
`missile_shot_crossplot.json` 里 12 处引用 `fig_missile_bc_overlay_*`）。
它们同样只是历史记录、不影响现在的链路；本轮**没有动** `results/`（用户只要求收拾早期图）。

## 清单（按生成它们的旧流程分组）

| 组 | 文件 |
| --- | --- |
| 旧 `pro`/`flash` 基线计时 | `fig_baseline_time_{baseline,pro_baseline,a1_std_refactor,legacy_check}.png` |
| 旧等时线扫描 | `fig_sweep_isotime_{baseline,pro_baseline,a1_std_refactor,legacy_check}.png` |
| 旧航迹（重建前那版） | `fig_traj_baseline.png` |
| 高抛族 / 距离扫描 | `fig_loft_family_baseline.png`、`fig_range_sweep.png` |
| ΔV–BC 叠加交叉核对 | `fig_missile_bc_overlay_{crossplot,procheck}.{png,pdf,svg}` |
| 旧 WebUI / CLI 流程演示 | `workflow_{demo,clitest,web}_{main,detail}.png` |

## 想恢复 / 想彻底扔掉

```powershell
# 恢复：原样搬回去（历史里的路径也是 figures/，git 能自动认出来）
git mv archive/figures-legacy/*.png archive/figures-legacy/*.pdf archive/figures-legacy/*.svg figures/

# 彻底扔掉：删掉这个目录（历史仍留得住，随时能 git show <commit>:figures/<名字> 取回）
git rm -r archive/figures-legacy
```

⚠ 别把这里的文件当成"某个数值的证据"：它们出自**已删除的引擎**，与现在 `vendor/wt-missile`
（2.59.0.28 / `python-game-6dof-v1`）算出来的东西**不是一回事**。要看当代数值请用
`figures/fig_isotime_plane_default.*`（图1）、`figures/fig_bg_plane_default.*`（图2）、
`figures/fig_traj_default.*`（图3），它们的口径记在 `docs/SOLVER-API.md` 与 `NOTES.md`。

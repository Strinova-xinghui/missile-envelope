# -*- coding: utf-8 -*-
"""**不提交**的产物清理器：`spikes/fig3d/out/` 只留"值得入库"的样例。

保留（都是小而关键的取证材料，合计 < 1 MB）：
  * `a/v02_traj_3d.png|svg`、`a/v03_traj_3d_proj.png|svg`、`a/v13_traj_preview_existing.png`
    —— 图3 三维轨迹的静态样本（PDF 与其余 12 个对照变体的三格式一律不留）；
  * `a_report.json`、`crossA.json`/`crossB.json` —— **复现性数字**（这是本 stage 的核心论据）。
  * `c/` 全部 —— WebGL 查看器 + 数据 + 无头截图（不到 200 kB）。

重跑命令见 `README.md`；删掉以后 `python spikes\\fig3d\\clean_out.py` 之外，
直接重跑 spike 就能全量重建。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "spikes" / "fig3d" / "out"

KEEP_A = {
    "a_report.json", "crossA.json", "crossB.json",
    "v02_traj_3d.png", "v02_traj_3d.svg",
    "v03_traj_3d_proj.png", "v03_traj_3d_proj.svg",
    "v13_traj_preview_existing.png",
}

#: 记录类文件在 `out/` 根，变体产物在 `out/a/` —— 用**文件名**匹配，不拼路径
#: （第一版按 `relative_to` 拼过，改过目录布局后静默失配过一次，所以这里只认 basename）。
KEEP_ANYWHERE = KEEP_A


def main() -> int:
    if not OUT.is_dir():
        print(f"没有 {OUT}，先跑 spike_a_mpl3d.py")
        return 1
    removed = kept = 0
    for p in sorted(OUT.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(OUT)
        # 保留：c/ 下的全部（WebGL 证据）+ 上面那张**按文件名**的白名单
        keep = (rel.parts[0] == "c") or (p.name in KEEP_ANYWHERE)
        if keep:
            kept += 1
            continue
        p.unlink()
        removed += 1
    # 清空目录
    for p in sorted(OUT.rglob("*"), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"保留 {kept} 个文件 / 删除 {removed} 个；out/ 现在 {total / 1024:.1f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

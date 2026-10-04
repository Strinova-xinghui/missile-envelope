#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""**唯一入口**：一次刷完正式产物的**全部形态**（图1/图2 各两个形态 + 图3 与沙盒数据）。

为什么要有这个入口（2026-10-04 真实事故，别删这段）：
`figures/` 里每张图有**两个形态** —— `_default`（提交后出的那一套，含扫描/等时线）与
`_static`（**首页无输入时直接贴的那一张**，`webui_static/index.html` 硬编码引用）。
旧文档的"重出产物"清单只写了 `--figure bg --tag default` 一条 ⇒ 换轴那天只重出了 `_default`，
**用户一打开首页看到的还是旧 γ 轴的 `_static`**，而所有验收都从这儿漏过去
（HTTP 200、字节数、包内探针"资源全部 200"都只证明"文件在"，不证明"内容是新口径"）。

⇒ 「记得重出另一个形态」是**人工承诺**，本脚本把它消掉：
一次调用刷完全部形态，刷完**自校验**（名单级轴口径 + 两个形态成对），不过就非零退出。

⚠ 两个形态**还有两处口径差异**（用户 2026-10-04，都在 `_static` 一侧）：
① **无基准弹**（`--no-baseline` ⇒ 11 枚全红、图例无「基准弹 …」、图1 副标题也不写它）——
"刚打开、没输入"时本来就没有基准弹可言；
② **坐标轴下方没有批注**（图内批注已全部移出，文本改由页面渲染）。

用法：
    python scripts\\refresh_products.py            # 刷全部形态 + 自校验（图1 全扫约 24 s，图2 约 20 s）
    python scripts\\refresh_products.py --check    # 只自校验（不重出，秒级；平时跑这个）
    python scripts\\refresh_products.py --only bg_static   # 只刷某一步（调试用）

⚠ 判据的唯一出处是 `tests/test_page_assets.py`（它读 `figures.py` 里的轴标签常量），
本脚本**不重新实现**那套规则，而是把同一组判据跑一遍 —— 规则只写一处。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 每一步 =（名字, 说明, `python -m missile_sim` 的参数）
#:
#: ⚠ `_static` 那两步（首页无输入时贴的就是它们）**必须带 `--no-baseline`**（用户 2026-10-04
#: 口径）：没输入的时候本来就没有基准弹可言，图上不许出现绿点；给定工况的 `_default` 保持显示。
STEPS = (
    ("plane_default", "图1 default（11 弹散点 + PL-12 等时线扫描，绿标基准弹）",
     ["--formats", "png,pdf,svg", "--tag", "default"]),
    ("plane_static", "图1 static（只散点 + 无基准弹，首页无输入时贴的就是它）",
     ["--formats", "png,pdf,svg", "--no-iso", "--no-baseline", "--tag", "static"]),
    ("bg_default", "图2 default（β–ginv 平面 + 仿真等时线扫描，绿标基准弹）",
     ["--formats", "png,pdf,svg", "--figure", "bg", "--tag", "default"]),
    ("bg_static", "图2 static（参考图那一套 + 无基准弹，首页无输入时贴的就是它）",
     ["--formats", "png,pdf,svg", "--figure", "bg", "--bg-no-scan",
      "--no-baseline", "--tag", "static"]),
    ("traj", "图3 与沙盒页数据（机动想定轨迹；`results/traj_default_*`）",
     ["--formats", "png,pdf,svg", "--figure", "traj", "--tag", "default"]),
)

#: 自校验用的判据组（页面引用 + 名单级轴口径 + 两个形态成对 + 反例层）
GATE = "page_assets"

#: 交付图件：2 个图族 × 2 个形态 × 3 种格式
FAMILIES = ("bg_plane", "isotime_plane")
FORMS = ("default", "static")
FORMATS = ("png", "pdf", "svg")


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONPATH", "src")
    return env


def _run(args, *, label) -> int:
    print(f"\n=== {label} ===")
    print("  $ python -m missile_sim " + " ".join(args))
    got = subprocess.run([sys.executable, "-m", "missile_sim"] + list(args),
                         cwd=str(ROOT), env=_env())
    return got.returncode


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def refresh(only=None) -> int:
    failed = []
    for name, label, args in STEPS:
        if only and name != only:
            continue
        rc = _run(args, label=label)
        if rc != 0:
            failed.append((name, rc))
            print(f"  ✗ 这一步失败（退出码 {rc}）")
    if failed:
        print("\n✗ 有步骤失败：", failed)
        return 1
    return 0


def check() -> int:
    """自校验：交付图件齐不齐 + 跑 `-k page_assets`（规则只在测试里写一份）。"""
    print("=== 交付图件（2 图族 × 2 形态 × 3 格式）===")
    missing = []
    for family in FAMILIES:
        for form in FORMS:
            row = []
            for fmt in FORMATS:
                p = ROOT / "figures" / f"fig_{family}_{form}.{fmt}"
                if p.is_file():
                    row.append(f"{fmt}={_sha(p)}")
                else:
                    row.append(f"{fmt}=**缺**")
                    missing.append(p.name)
            print("  %-38s %s" % (f"fig_{family}_{form}", "  ".join(row)))
    if missing:
        print("\n✗ 缺产物：", missing, "⇒ 先不带 --check 跑一次")
        return 1
    print(f"\n=== 判据：-k {GATE}（页面引用 + 名单级轴口径 + 两形态成对 + 反例层）===")
    got = subprocess.run([sys.executable, str(ROOT / "tests" / "run_tests.py"), "-k", GATE],
                         cwd=str(ROOT), env=_env())
    if got.returncode != 0:
        print(f"\n✗ 判据 `-k {GATE}` 没过 —— 产物口径不对（多半是漏重出某个形态）")
        return 1
    print(f"\n✅ 全部形态已刷新且过判据（`-k {GATE}`）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="刷新正式产物的全部形态（图1/图2 各两形态 + 图3）")
    ap.add_argument("--check", action="store_true", help="只自校验，不重出")
    ap.add_argument("--only", default=None, choices=[s[0] for s in STEPS],
                    help="只刷某一步（调试用）")
    ap.add_argument("--list", action="store_true", help="列出步骤")
    got = ap.parse_args()
    if got.list:
        for name, label, args in STEPS:
            print(f"  {name:<14} {label}\n{'':<16}$ python -m missile_sim {' '.join(args)}")
        return 0
    if got.check:
        return check()
    rc = refresh(only=got.only)
    return rc if rc else check()


if __name__ == "__main__":
    raise SystemExit(main())

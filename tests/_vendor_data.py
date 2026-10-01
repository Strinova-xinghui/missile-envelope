"""求解器内核 / War Thunder 游戏数据是否在位 —— 全测试共用的一处判定。

**为什么需要它**：`vendor/wt-missile/inputs/` 里的 168 份 `.blk` 是 War Thunder 游戏数据，
权利归 Gaijin，**不随本仓库分发**（`git rm -r --cached` + `.gitignore`，见 `vendor/README.md`
与 `docs/OPENSOURCE-READINESS.md` §0）。缺了它，凡是碰求解器的用例都会抛
`missile_sim.solver.SolverUnavailable` —— **那不是代码坏了，是数据没放回来**。
所以这类缺失必须表现为"打印一行说明后跳过"，而不是把一百多项判成红。

两条使用方式：

1. **运行器级**（`tests/run_tests.py`）：跑之前问一次 `ready()`，不在位就进入**降级模式** ——
   需要数据的用例失败时记成 `SKIP`（计数与"通过"分开报，退出码仍为 0），`--strict` 关掉降级。
2. **用例级**：`_vendor_data.require()` —— 数据不在位时当场 `pytest.skip(...)`，
   与"没有 node 就打印一行并返回"是同一个套路（真 pytest 与本仓库的 shim 都认）。

判定口径（都只看文件在不在，不做哈希校验 —— 哈希由求解器自己硬校验）：

* `kernel_available()`：`vendor/wt-missile/wt_missile.py` 存在（内核**随仓**，正常情况下必然存在）；
* `data_available()`：`manifest.json` 能解析，且它**点名的 168 份 `.blk` 全在磁盘上**
  （清单里另有 3 个 `metadata.txt` / `*.json` 从来就没随包提供，求解器也不读它们，故不参与判定；
  少一份 `.blk` 就算"数据没放好"，宁可降级也不要在 168 次 SHA-256 校验里炸出 100 多个红）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "wt-missile"
KERNEL_FILE = VENDOR / "wt_missile.py"
DATA_DIR = VENDOR / "inputs" / "resources" / "2.59.0.28"

HOWTO = "vendor/README.md（把游戏数据放回 vendor/wt-missile/inputs/ 即可）"


@lru_cache(maxsize=1)
def kernel_available() -> bool:
    return KERNEL_FILE.is_file()


@lru_cache(maxsize=1)
def data_available() -> bool:
    if not (DATA_DIR / "manifest.json").is_file() or not (DATA_DIR / "presets.json").is_file():
        return False
    try:
        manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 清单坏了也算"数据不在位"
        return False
    blks = [k for k in (manifest.get("files") or {}) if str(k).endswith(".blk")]
    if not blks:
        return False
    return all((DATA_DIR / k).is_file() for k in blks)


def ready() -> bool:
    """求解器能不能真的跑：内核文件在 + 它加载时要读的 `.blk` 全在。"""
    return kernel_available() and data_available()


def missing_reason() -> str:
    """一行"缺什么"（给横幅与 SKIP 行用）。"""
    if not kernel_available():
        return f"内核不在：{KERNEL_FILE.relative_to(ROOT)}（内核随仓，缺了说明这不是完整 clone）"
    if not data_available():
        return ("缺少 War Thunder 游戏数据：vendor/wt-missile/inputs/resources/2.59.0.28/"
                "（168 份 .blk 权利归 Gaijin，不随仓库分发）")
    return ""


def require(reason: str = "") -> None:
    """数据不在位就跳过本用例（在位的开销 ≈ 一次 stat 缓存）。"""
    if ready():
        return
    import pytest  # 运行器已把 shim 注册成 pytest

    pytest.skip(reason or missing_reason())

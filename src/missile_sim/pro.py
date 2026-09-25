# -*- coding: utf-8 -*-
"""**兼容 shim**：Pro 后端已按三段式重构进 `missile_sim.model`（见 AERO_PLAN §22）。

本模块只做名字转发，**不再承载实现**：

    ┌─ 第一层 输入层   model/io.py        blk 统计 + 用户条件 → NativeCase
    ├─ 第二层 计算层   model/native.py    `NativeCase → NativeResult`（原生仿真器薄包装）
    │                  model/runner.py    进程池 + 缓存调度
    └─ 第三层 输出层   model/record.py    结构化记录 / 表 / 时效校验
                       model/cache.py     版本化磁盘缓存

新代码请直接 `from missile_sim.model import ...`。此处的转发是为了让既有调用方
（`flight.py` / `sweep.py` / `scripts/pro_missiles.py` / `tests/test_pro.py`）零改动。

⚠ 打桩注意：`ProRunner` 内部绑定的是 `model.native.simulate_native`。
   要拦截它请打桩 `missile_sim.model.runner.simulate_native`，**不是** `pro.simulate_native`。
"""

from __future__ import annotations

from .model import ProCache
from .model.constants import (  # noqa: F401
    CACHE_SCHEMA,
    CALC_VERSION,
    DEFAULT_CACHE,
    DEFAULT_PKG,
    DT_DEFAULT,
    DT_RANGE,
    ELF_REL,
    ELF_SHA256_28,
    ENV_PKG,
    HIT_EVENTS,
    NATIVE_PROFILES,
    ROOT,
    VERSION_28,
)
from .model.grid import CellSolution, GridOutcome, run_grid  # noqa: F401
from .model.io import (  # noqa: F401
    build_case,
    can_run_native,
    cx_scale_for_bc,
    load_blk_profile,
    module_stages,
    native_name_of,
    scale_for_dv,
    scale_tag,
    scales_for,
    vacuum_dv,
)
from .model.native import (  # noqa: F401
    NativeCase,
    NativeResult,
    ProRuntimeError,
    _build_scenario,
    _import_native,
    _patch_profile,
    check_unicorn,
    resolve_pkg,
    runtime,
    simulate_native,
    verify_elf,
)
from .model.runner import ProRunner, _worker_init, _worker_run  # noqa: F401

# 旧名兼容：注入源取 profile（实现已移到输入层）
_external_profile = load_blk_profile
# 旧名兼容：“由配置造工况”已更名为 build_case
native_case_from_config = build_case

# -*- coding: utf-8 -*-
"""模型层（三段式架构的第一部分）。

    ┌─ 第一层 输入层  io.py      blk 参数统计 + 用户条件 → NativeCase（"采购原材料"）
    ├─ 第二层 计算层  native.py / runner.py   原生仿真器薄包装（"直接外包"，不改包）
    └─ 第三层 输出层  record.py / cache.py    结构化记录 + 版本化缓存

**依赖方向**：`io → native`（输入层用计算层的规格类型），`runner → native + cache`，
`record → native`。计算层内部对输入层只用**模块引用**（`io_mod.xxx`）在函数里延迟导入，
所以不存在模块级循环依赖；同时保留"输入层决定映射口径、计算层只执行"的分工。

对外只需要认这三组名字（见 `docs`/`AERO_PLAN.md` §22）：

    # 第一层
    blk_stats, list_standards, build_case, native_name_of, can_run_native
    # 第二层
    NativeCase, NativeResult, ProRuntimeError, ProRunner, simulate_native, runtime
    # 第三层
    CaseRecord, to_record, write_table, read_table, check_staleness, ProCache
    # 版本
    CALC_VERSION
"""

from __future__ import annotations

from .cache import ProCache
from .constants import (  # noqa: F401
    CALC_VERSION,
    CACHE_SCHEMA,
    DEFAULT_CACHE,
    DEFAULT_PKG,
    DT_DEFAULT,
    DT_RANGE,
    ELF_SHA256_28,
    ENV_PKG,
    HIT_EVENTS,
    NATIVE_PROFILES,
    ROOT,
    VERSION_28,
)
from .grid import CellSolution, GridOutcome, run_grid
from .io import (
    blk_stats,
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
from .native import (
    NativeCase,
    NativeResult,
    ProRuntimeError,
    check_unicorn,
    resolve_pkg,
    runtime,
    simulate_native,
    verify_elf,
)
from .record import CaseRecord, check_staleness, read_table, to_record, write_table
from .runner import ProRunner

__all__ = [
    # 版本
    "CALC_VERSION", "CACHE_SCHEMA",
    # 第一层：输入
    "blk_stats", "build_case", "native_name_of", "can_run_native", "load_blk_profile",
    "module_stages", "vacuum_dv", "scale_for_dv", "cx_scale_for_bc", "scales_for", "scale_tag",
    # 第二层：计算
    "NativeCase", "NativeResult", "ProRuntimeError", "ProRunner", "simulate_native",
    "resolve_pkg", "verify_elf", "check_unicorn", "runtime",
    # 第三层：输出与缓存
    "CaseRecord", "to_record", "write_table", "read_table", "check_staleness", "ProCache",
    "CellSolution", "GridOutcome", "run_grid",
    # 常量
    "DEFAULT_CACHE", "DEFAULT_PKG", "DT_DEFAULT", "DT_RANGE", "ELF_SHA256_28", "ENV_PKG",
    "HIT_EVENTS", "NATIVE_PROFILES", "ROOT", "VERSION_28",
]


def list_standards(pool_path=None):
    """池内可选基准弹（11 弹池）；返回 `standard.StandardProfile` 列表。"""
    from .. import standard as standard_mod
    return [standard_mod.resolve(n, pool_path) for n in standard_mod.pool_names(pool_path)]

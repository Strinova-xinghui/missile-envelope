# -*- coding: utf-8 -*-
"""模型层（三段式架构的第一部分）。

    ┌─ 第一层 输入层  io.py       blk 参数统计 + 用户条件 → EngineInputs（"采购原材料"）
    ├─ 第二层 计算层  wtgame.py   **当前正式口径**：wt-missile 两档 standard / fast
    │                 native.py   旧 Pro 引擎：原生仿真器薄包装（保留，不再注册）
    │                 flash.py    旧 Flash 引擎：本仓库公式引擎（保留，不再注册）
    │                 runner.py   执行器：进程池 + 缓存 + 进度（不认识物理）
    └─ 第三层 输出层  record.py / cache.py    结构化记录 + 按档位分版本的缓存

**结构化模型 API**（用户 2026-09-25 定案，为"换用开源拿到的更新模型"而设）：

    EngineInputs  ──┐
                    ├──►  Engine.simulate  ──►  NativeResult(+EngineStamp)  ──► 输出层
    EngineEnv     ──┘

换模型 = 写一个满足 `Engine` 协议（`spec.py`）的类 + 在 `registry.py` 登记一张 `ModelSpec`；
扫描器/缓存/记录/绘图一行都不用改。接入规范见 `docs/MODEL-API.md`。

**2026-09-26 整体替换**：求解器换成入库的 `vendor/wt-missile/`（2.59.0.28 原生 6DOF 的纯 Python
复刻，`MODEL = "python-game-6dof-v1"`），两档为 `standard`（纯 Python 逐物理步）与 `fast`
（同一物理的 C 编译内核，缺编译器自动回退）。旧 `pro` / `flash` 的代码、版本号与缓存全部保留
（可回退、可对拍），但**不再注册**，任何默认路径都不再调用。

**依赖方向**：`io → spec/native`（输入层用计算层的规格类型），`runner → engine + cache`，
`record → native`。计算层内部对输入层只用**模块引用**在函数里延迟导入，不存在模块级循环依赖。

对外只需要认这几组名字（见 `AERO_PLAN.md` §22/§23 与 `docs/MODEL-API.md`）：

    # 第一层
    blk_stats, list_standards, build_inputs, inputs_from_case, build_case,
    rocket_block, normalize_blk_profile, native_name_of, short_name_of, can_run_native
    # 第二层（当前口径）
    StandardEngine, FastEngine, SolverUnavailable, load_solver, resource_identity,
    scenario_from_inputs, simulate_tier, to_native_result, dt_for
    # 第二层（保留，不再注册）
    NativeCase, NativeResult, ProRuntimeError, ProEngine, ProRunner, simulate_native, runtime
    FlashEngine, FlashRunner, simulate_flash
    EngineRunner
    # 契约与注册表
    EngineInputs, EngineEnv, EngineStamp, Engine, ModelSpec, Capability, SelfTestReport
    spec_of, load_engine, list_models, models_table, check_models
    # 第三层
    CaseRecord, to_record, write_table, read_table, check_staleness, ProCache, FlashCache
    # 版本（**按档位分**：standard / fast 同物理不同算术路径，缓存必须隔离）
    CALC_VERSION, CALC_VERSION_STANDARD, CALC_VERSION_FAST, calc_version
"""

from __future__ import annotations

from .cache import FlashCache, ProCache, ResultCache, backend_cache, model_cache_path
from .constants import (  # noqa: F401
    CALC_VERSION,
    CALC_VERSION_FAST,
    CALC_VERSION_FLASH,
    CALC_VERSION_PRO,
    CALC_VERSION_STANDARD,
    CACHE_SCHEMA,
    DEFAULT_CACHE,
    DEFAULT_PKG,
    DT_DEFAULT,
    DT_RANGE,
    ELF_SHA256_28,
    ENV_PKG,
    FLASH_CACHE,
    HIT_EVENTS,
    NATIVE_PROFILES,
    ROOT,
    SOLVER_DT,
    VENDOR_DIR,
    VERSION_28,
    calc_version,
)
from .env import build_env
from .flash import (
    FlashEngine,
    FlashModelError,
    FlashRunner,
    flash_case_from,
    flash_config,
    simulate_flash,
    standard_for,
)
from .grid import CellSolution, GridOutcome, run_grid
from .io import (
    blk_stats,
    build_case,
    build_inputs,
    can_run_native,
    cx_scale_for_bc,
    inputs_from_case,
    load_blk_profile,
    module_stages,
    native_name_of,
    normalize_blk_profile,
    rocket_block,
    scale_for_dv,
    scale_tag,
    scales_for,
    short_name_of,
    vacuum_dv,
)
from .native import (
    NativeCase,
    NativeResult,
    ProEngine,
    ProRuntimeError,
    case_from_inputs,
    check_unicorn,
    resolve_pkg,
    runtime,
    simulate_native,
    verify_elf,
)
from .record import CaseRecord, check_staleness, read_table, to_record, write_table
from .registry import (
    BUILTIN_SPECS,
    ModelNotFound,
    check_models,
    list_models,
    load_engine,
    models_table,
    spec_of,
)
from .runner import EngineRunner, ProRunner
from .spec import (
    AeroCoeffs,
    Autopilot,
    Capability,
    Engine,
    EngineEnv,
    EngineInputs,
    EngineStamp,
    Fuse,
    GainTables,
    Geometry,
    Limits,
    LoftConfig,
    MassProfile,
    ModelSpec,
    PidRow,
    SelfTestReport,
    digest_of_inputs,
)
from .wtgame import (
    FastEngine,
    SolverUnavailable,
    StandardEngine,
    dt_for,
    load_solver,
    resource_identity,
    scenario_from_inputs,
    simulate_tier,
    to_native_result,
)

__all__ = [
    # 版本（按档位分）
    "CALC_VERSION", "CALC_VERSION_STANDARD", "CALC_VERSION_FAST",
    "CALC_VERSION_PRO", "CALC_VERSION_FLASH", "CACHE_SCHEMA", "calc_version",
    # 契约与注册表
    "Engine", "ModelSpec", "Capability", "EngineEnv", "EngineInputs", "EngineStamp",
    "SelfTestReport", "digest_of_inputs",
    "MassProfile", "Geometry", "AeroCoeffs", "Autopilot", "PidRow", "LoftConfig",
    "GainTables", "Limits", "Fuse",
    "spec_of", "load_engine", "list_models", "models_table", "check_models",
    "ModelNotFound", "BUILTIN_SPECS", "build_env",
    # 第一层：输入
    "blk_stats", "build_case", "build_inputs", "inputs_from_case", "rocket_block",
    "normalize_blk_profile", "native_name_of", "short_name_of", "can_run_native",
    "load_blk_profile", "module_stages", "vacuum_dv", "scale_for_dv", "cx_scale_for_bc",
    "scales_for", "scale_tag",
    # 第二层：计算（wt-missile 两档 —— 当前正式口径）
    "StandardEngine", "FastEngine", "SolverUnavailable", "load_solver", "resource_identity",
    "scenario_from_inputs", "simulate_tier", "to_native_result", "dt_for",
    # 第二层：计算（旧 Pro / 旧 Flash —— 保留，但不再注册）
    "NativeCase", "NativeResult", "ProRuntimeError", "ProEngine", "ProRunner",
    "simulate_native", "case_from_inputs", "resolve_pkg", "verify_elf", "check_unicorn",
    "runtime",
    "FlashEngine", "FlashRunner", "FlashModelError", "simulate_flash", "flash_case_from",
    "flash_config", "standard_for",
    # 第二层：执行器
    "EngineRunner",
    # 第三层：输出与缓存
    "CaseRecord", "to_record", "write_table", "read_table", "check_staleness",
    "ProCache", "FlashCache", "ResultCache", "backend_cache", "model_cache_path",
    "CellSolution", "GridOutcome", "run_grid",
    # 常量
    "DEFAULT_CACHE", "FLASH_CACHE", "DEFAULT_PKG", "DT_DEFAULT", "DT_RANGE",
    "ELF_SHA256_28", "ENV_PKG", "HIT_EVENTS", "NATIVE_PROFILES", "ROOT",
    "SOLVER_DT", "VENDOR_DIR", "VERSION_28",
]


def list_standards(pool_path=None):
    """池内可选基准弹（11 弹池）；返回 `standard.StandardProfile` 列表。"""
    from .. import standard as standard_mod
    return [standard_mod.resolve(n, pool_path) for n in standard_mod.pool_names(pool_path)]

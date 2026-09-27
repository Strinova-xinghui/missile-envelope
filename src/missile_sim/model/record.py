# -*- coding: utf-8 -*-
"""**模型层 3：输出层**——把原生结果变成结构化、可追溯、可校验时效的记录。

职责边界：本层**只**做"结果 → 记录 / 表 / 版本戳"，不做物理、不做调参、不做缓存命中逻辑
（缓存命中在 `cache.ProCache`，扫描编排在包外层的 `scanner`）。

产物里必须回答三个问题：
  1. **输入是什么**（标准弹 + 指纹、工况、敌机、外部 (ΔV,BC)）
  2. **谁算的**（后端、包/ELF、步长、观测模式、注入来源、`CALC_VERSION`）
  3. **还算不算数**（`check_staleness` 对照当前输入与计算器版本）
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .constants import (
    CALC_VERSION,
    CALC_VERSION_FLASH,
    CALC_VERSION_PRO,
    ELF_SHA256_28,
    VERSION_28,
    calc_version,
)
from .native import NativeCase, NativeResult

SAMPLE_FIELDS = ("t", "x", "y", "v", "mass", "thrust", "range", "q_dyn")
SAMPLES_PER_SECOND = 4.0          # 轨迹采样下限（弹道剖面图用；不是物理步长）


def _finite(x, default=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


#: 内置模型名缓存（见 `builtin_model_names`）。
_BUILTIN_NAMES: tuple = ()

#: 注册表都取不到时的兜底 —— 只列**当前档位**，旧名靠注册表给（别在这里再抄一份，
#: 曾经的硬编码 `("pro", "flash")` 在档位改名成 standard/fast 后把所有记录判成了未知模型）。
_BUILTIN_FALLBACK = ("standard", "fast")


def builtin_model_names() -> tuple:
    """全部内置模型名（**含** `pro` / `flash` 这类 legacy 注册名）。

    故意从注册表取而不是在 `to_record` 里写死：档位是会改名的（pro/flash → standard/fast），
    写死的白名单会在改名当天把所有既有记录判成"未知模型"。

    惰性 + 缓存：`to_record` 是逐工况热路径，但模块只导入一次，之后只是一次全局查表；
    同时避开 `record ← registry ← native ← record` 这条潜在导入环。注册表本身坏掉时退回
    `_BUILTIN_FALLBACK` —— 记录这一步不该因为注册表的问题整体失败。
    """
    global _BUILTIN_NAMES
    if not _BUILTIN_NAMES:
        try:
            from .registry import BUILTIN_SPECS
            _BUILTIN_NAMES = tuple(sorted(BUILTIN_SPECS))
        except Exception:                                   # noqa: BLE001
            _BUILTIN_NAMES = _BUILTIN_FALLBACK
    return _BUILTIN_NAMES


# --------------------------------------------------------------------- 记录


@dataclass
class CaseRecord:
    """一个工况的**稳定输出契约**（绘图与外部消费只依赖它）。

    `schema` 按后端解析（Pro=5 / Flash=1）：改了要同步 +1，否则缓存与产物会错配。
    """

    case_id: str
    inputs: dict = field(default_factory=dict)      # standard/hash/dv/bc/conditions/target/dv_blk/bc_blk
    scales: dict = field(default_factory=dict)      # thrust_scale/cx_scale/cxk_used
    engine: dict = field(default_factory=dict)      # 真空 ΔV 与实测增量、损失、燃尽
    outcome: dict = field(default_factory=dict)     # ok/hit/event/t_hit/t_end/v_impact/max_alt/miss
    model: dict = field(default_factory=dict)       # kind/pkg/version/elf/dt/observation/resource
    samples: list = field(default_factory=list)     # 轨迹采样（可为空）
    schema: int = field(default_factory=lambda: calc_version("standard"))
    warnings: list = field(default_factory=list)

    # --- 便捷读取（绘图/表格用） ------------------------------------

    @property
    def ok(self) -> bool:
        return bool(self.outcome.get("ok"))

    @property
    def hit(self) -> bool:
        return bool(self.outcome.get("hit"))

    @property
    def t_hit(self):
        return self.outcome.get("t_hit")

    @property
    def v_impact(self):
        return self.outcome.get("v_impact")

    @property
    def dv(self):
        return self.inputs.get("dv")

    @property
    def bc(self):
        return self.inputs.get("bc")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CaseRecord":
        keep = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in keep})


def downsample(samples: list, *, per_second: float = SAMPLES_PER_SECOND) -> list:
    """按时间抽稀原生采样（保留首尾），只留 SAMPLE_FIELDS 里存在的键。"""
    if not samples:
        return []
    if per_second <= 0:
        return [{k: s[k] for k in SAMPLE_FIELDS if k in s} for s in samples]
    out, next_t = [], -1.0
    for s in samples:
        t = _finite(s.get("t"), 0.0)
        if t >= next_t:
            out.append({k: s[k] for k in SAMPLE_FIELDS if k in s})
            next_t = t + 1.0 / per_second
    if out and out[-1].get("t") != _finite(samples[-1].get("t"), None):
        out.append({k: samples[-1][k] for k in SAMPLE_FIELDS if k in samples[-1]})
    return out


def to_record(result: NativeResult, case: NativeCase, *,
              standard: dict | None = None,
              samples: list | None = None,
              runtime_info: dict | None = None,
              backend: str = "standard",
              model: str | None = None) -> CaseRecord:
    """原生结果 + 工况 → `CaseRecord`（唯一入口）。

    `samples` 不给（None）时用 `result.samples`；给 `[]` 才是"显式空轨迹"。
    ⚠ 别写成 `samples or []`——`None or []` 会得到 `[]`，把原生轨迹静默丢掉。

    `model`（旧名 `backend`）决定 `schema` 与 `model` 块的身份字段：Pro 记
    `pkg/version/elf_sha256`，其他模型只留 `dt/observation` 与自报的 `resource`。
    """
    if samples is None:
        samples = result.samples or []
    std = dict(standard or {})
    rt = dict(runtime_info or {})
    name = str(model or backend or "standard").strip().lower()
    allowed = builtin_model_names()
    if name not in allowed and not {"kind", "engine"} & set(rt):
        raise ValueError(
            f"未知模型：{name!r}（内置 {'/'.join(allowed)}；第三方模型必须在 "
            f"runtime_info 里自报 kind/engine）")
    dv_t = float(case.dv_target or 0.0)
    bc_t = float(case.bc_target or 0.0)
    dv_meas = _finite(result.dv_measured)
    loss = ((1.0 - dv_meas / dv_t) * 100.0
            if (dv_meas is not None and dv_t > 0) else None)
    warnings = []
    if not result.ok:
        warnings.append(f"原生执行失败：{result.error}")
    elif not result.hit:
        warnings.append(f"未命中（{result.event or 'unknown'}）")
    if result.cache_hit:
        warnings.append("来自缓存")
    model_block = {
        "kind": str(rt.get("kind") or name).lower(),
        "dt_s": case.dt, "observation_mode": case.observation_mode,
        "duration_s": case.duration_s,
        "resource": result.resource or "native",
    }
    if model_block["kind"] == "pro":
        model_block.update({
            "version": rt.get("version", VERSION_28),
            "pkg": rt.get("pkg"),
            "elf_sha256": rt.get("elf_sha256", ELF_SHA256_28),
        })
    if rt.get("engine"):
        model_block["engine"] = rt["engine"]
    if rt.get("engine_version"):
        model_block["engine_version"] = rt["engine_version"]
    return CaseRecord(
        case_id=case.key(),
        inputs={
            "standard": std.get("name"), "tag": std.get("tag"),
            "profile_hash": std.get("profile_hash"),
            "dv": dv_t or None, "bc": bc_t or None,
            "dv_blk": _finite(result.dv_blk), "bc_blk": _finite(result.bc_blk),
            "conditions": {
                "range_m": case.range_m, "alt_m": case.alt_m, "vm0": case.vm0,
                "target_alt_m": case.target_alt, "loft_deg": std.get("loft_deg"),
            },
            "target": {
                "vt": case.vt, "maneuvers": [list(m) for m in case.target_maneuvers],
                "collision_radius_m": case.hit_radius_m,
            },
        },
        scales={
            "thrust_scale": _finite(result.thrust_scale),
            "cx_scale": _finite(result.cx_scale),
            "cxk_used": (_finite(result.cx_scale) * std.get("cxk")
                         if (_finite(result.cx_scale) is not None and std.get("cxk")) else None),
        },
        engine={
            "dv_measured": dv_meas, "loss_pct": loss,
            "t_burnout": _finite(result.t_burnout),
            "m_launch": _finite(result.m_launch), "m_dry": _finite(result.m_dry),
        },
        outcome={
            "ok": bool(result.ok), "hit": bool(result.hit), "event": result.event,
            "t_hit": (_finite(result.t_hit) if result.hit else None),
            "t_end": _finite(result.t_end), "v_impact": _finite(result.v_impact),
            "max_alt_m": _finite(result.max_alt_m),
            "miss_distance_m": _finite(result.miss_distance_m),
            "error": result.error or None,
        },
        model=model_block,
        samples=downsample(samples),
        schema=int(rt.get("calc_version") or calc_version(name)),
        warnings=warnings,
    )


# --------------------------------------------------------------------- 表与清单


def write_table(records, path, *, fmt: str | None = None) -> Path:
    """写逐工况表。`.csv` → 扁平表；`.json` → 完整记录（含 provenance 由调用方塞进 `extra`）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "json":
        payload = [r.to_dict() if isinstance(r, CaseRecord) else r for r in records]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    if fmt != "csv":
        raise ValueError(f"不支持的表格格式：{fmt}（只支持 csv/json）")
    cols = ["case_id", "standard", "dv", "bc", "thrust_scale", "cx_scale", "cxk_used",
            "dv_blk", "bc_blk", "ok", "hit", "event", "t_hit", "t_end", "v_impact",
            "max_alt_m", "miss_distance_m", "dv_measured", "loss_pct", "t_burnout",
            "m_launch", "m_dry", "dt_s", "observation_mode", "resource", "warnings"]
    lines = [",".join(cols)]
    for r in records:
        rec = r if isinstance(r, CaseRecord) else CaseRecord.from_dict(r)
        row = {
            "case_id": rec.case_id,
            "standard": rec.inputs.get("standard"),
            "dv": rec.inputs.get("dv"), "bc": rec.inputs.get("bc"),
            "thrust_scale": rec.scales.get("thrust_scale"),
            "cx_scale": rec.scales.get("cx_scale"), "cxk_used": rec.scales.get("cxk_used"),
            "dv_blk": rec.inputs.get("dv_blk"), "bc_blk": rec.inputs.get("bc_blk"),
            **rec.outcome, **rec.engine, **{k: rec.model.get(k) for k in
                                            ("dt_s", "observation_mode", "resource")},
            "warnings": "; ".join(rec.warnings),
        }
        cells = []
        for c in cols:
            v = row.get(c)
            if v is None:
                cells.append("")
            elif isinstance(v, bool):
                cells.append("1" if v else "0")
            elif isinstance(v, float):
                cells.append("nan" if not math.isfinite(v) else f"{v:.6g}")
            else:
                cells.append(str(v).replace(",", "；"))
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_table(path) -> list:
    """读回记录：`.json` → `CaseRecord` 列表；`.csv` → dict 列表（扁平）。"""
    import csv
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):                      # 允许 {records: [...]} 包装
            data = data.get("records") or []
        return [CaseRecord.from_dict(d) for d in data]
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------- 指纹与时效


def digest_of(obj: Any) -> str:
    """任意可 JSON 化对象的稳定指纹（用于输入/manifest 级比对）。"""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def make_manifest(*, run_id: str, inputs: dict, grid: dict, calculator: dict,
                  cache: dict | None = None, stats: dict | None = None,
                  artifacts: list | None = None, extra: dict | None = None,
                  backend: str = "standard") -> dict:
    """run 级清单：输入指纹 + 计算器版本 + 缓存摘要 + 统计（"表明版本号"的落点）。

    `backend` 决定版本号与是否附 ELF 身份：旧 Pro 记 `elf_sha256`/`version`，
    其余档位只记 `calc_version`（它们不碰原生包）。**未知键一律不塞**，否则各档位的
    `calculator_digest` 会被互相污染。
    """
    base = {"calc_version": calc_version(backend)}
    if str(backend).strip().lower() == "pro":
        base.update({"elf_sha256": ELF_SHA256_28, "version": VERSION_28})
    calc = {**base, **dict(calculator or {})}
    return {
        "schema": calc_version(backend),
        "run_id": run_id,
        "kind": "scan",
        "inputs": inputs,
        "inputs_digest": digest_of(inputs),
        "grid": {**dict(grid or {}), "digest": digest_of(grid or {})},
        "calculator": calc,
        "calculator_digest": digest_of(calc),
        "cache": dict(cache or {}),
        "stats": dict(stats or {}),
        "artifacts": list(artifacts or []),
        **(extra or {}),
    }


def check_staleness(manifest: dict, current_inputs: dict | None = None,
                    current_calculator: dict | None = None,
                    backend: str = "standard") -> dict:
    """判定清单是否过期。返回 `{stale, reasons[], inputs_digest, calculator_digest}`。

    三种判定：`fresh` / `stale_inputs`（输入变了）/ `stale_calculator`（版本或 ELF 变了）。
    **换档位必然 stale**：各档位的 `calculator_digest` 不同，不会互相偷结果。

    ⚠ `backend` 必须与**生成该清单时**用的档位一致，否则 `stale_calculator` 是假阳性
    ——默认值只是"当前默认档位"，跨档位比对时请显式传。
    """
    reasons = []
    if current_inputs is not None:
        if digest_of(current_inputs) != manifest.get("inputs_digest"):
            reasons.append("stale_inputs")
    if current_calculator is not None:
        base = {"calc_version": calc_version(backend)}
        if str(backend).strip().lower() == "pro":
            base.update({"elf_sha256": ELF_SHA256_28, "version": VERSION_28})
        calc = {**base, **dict(current_calculator)}
        if digest_of(calc) != manifest.get("calculator_digest"):
            reasons.append("stale_calculator")
    if int(manifest.get("schema", 0)) != calc_version(backend):
        reasons.append("stale_calculator")
    wanted = {r for r in reasons if r.startswith("stale_")}
    return {"stale": bool(wanted), "reasons": sorted(wanted),
            "inputs_digest": manifest.get("inputs_digest"),
            "calculator_digest": manifest.get("calculator_digest")}

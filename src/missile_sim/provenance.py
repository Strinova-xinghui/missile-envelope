# -*- coding: utf-8 -*-
"""产物自描述块（provenance）：把"这批数字是谁算的"讲清楚，三处产物共用一份。

**为什么要有它**：Flash/Pro 双后端（AERO_PLAN §18）之后，同一张图可能由不同后端、
不同标准弹、不同燃烧/高抛档位产生。产物里只写"命中时间 45.2 s"是不够的——
必须能回答：哪个后端？哪型标准弹（含参数指纹）？燃烧是有限还是瞬时？高抛用哪套判据？

**唯一来源**：`provenance(cfg)` 只实现一次，`workflow`、`sweep`、交叉图三处都调它。
Pro 后端将来只需在 `extra` 里补 `elf_sha256` / `injected` 两个键，**调用方不用改**。
"""

from __future__ import annotations

from . import burn as burn_mod


def provenance(cfg, *, extra: dict | None = None) -> dict:
    """由配置对象生成自描述块。"""
    prof = getattr(cfg, "profile", None)
    if prof is None:
        std = {"name": None, "tag": None, "file": None, "profile_hash": None,
               "note": "未启用标准弹（用配置字面值；见 configs/*.json 的 standard.name）"}
    else:
        std = {"name": prof.name, "label": prof.label, "tag": prof.tag, "file": prof.file,
               "profile_hash": prof.profile_hash(),
               "fallbacks": list(prof.fallbacks),
               "dv": prof.dv, "bc": prof.bc, "dry_mass": prof.dry_mass}
    b = getattr(cfg, "burn", None)
    if b is None:
        burn_blk = {"model": None}
    elif b.model == burn_mod.MODEL_INSTANT:
        burn_blk = {"model": b.model, "note": "瞬时燃烧（旧口径，ΔV 在 t=0 一次给出）"}
    else:
        stages = [[s[2], s[3]] for s in b.engine_stages()] if hasattr(b, "engine_stages") else []
        if not stages:
            stages = [[b.force, b.time_fire]] + ([[b.force1, b.time_fire1]] if b.two_stage else [])
        burn_blk = {"model": b.model, "stages_thrust_n_s": stages,
                    "mass_kg": [b.mass_launch, b.mass_mid, b.mass_dry],
                    "two_stage": bool(b.two_stage), "burn_time_s": b.burn_time_total}
    out = {
        "backend": str(getattr(cfg, "backend", "flash")),
        "standard": std,
        "burn": burn_blk,
        "loft": {"rule": str(cfg.sim.loft_rule), "elevation_deg": cfg.sim.theta_loft_deg,
                 "target_elevation_deg": cfg.sim.loft_target_elevation_deg,
                 "target_omega_max_dps": cfg.sim.loft_target_omega_max_dps},
        "aero_model": str(cfg.aero.model),
        "dt": float(cfg.sim.dt),
        "hit_radius_m": float(cfg.sim.hit_radius),
        "t_life_s": float(cfg.sim.t_life),
        "g": float(cfg.atmosphere.g),
    }
    if extra:
        out.update(extra)
    return out


def summary_line(prov: dict) -> str:
    """一行摘要（控制台/结果页用）。"""
    s = prov.get("standard") or {}
    if not s.get("name"):
        std = "无标准弹"
    else:
        std = f"{s['name']}@{s.get('tag')}#{s.get('profile_hash')}"
    burn = (prov.get("burn") or {}).get("model")
    return (f"backend={prov.get('backend')} · 标准弹 {std} · 燃烧 {burn} · "
            f"高抛 {prov.get('loft', {}).get('rule')} · 气动 {prov.get('aero_model')}")

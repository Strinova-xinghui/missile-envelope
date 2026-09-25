# -*- coding: utf-8 -*-
"""**模型层 3（缓存部分）**：原生结果的磁盘缓存。

一次穷举是小时级，之后所有迭代都应该读缓存（“只做一次”的前提）。
键 = `NativeCase.key()`；顶层 `schema` = `CALC_VERSION`，不符则**整体作废**并记原因。

⚠ 缓存必须带 schema 版本：映射口径改过之后，旧条目是“用旧公式算出来的”，
直接用会静默污染新结果——本项目踩过：410 条 `dv_blk=536.9` 的坏条目让 t_hit 从 45.1 变 25.6。
"""

from __future__ import annotations

import json
from pathlib import Path

from .constants import CACHE_SCHEMA, DEFAULT_CACHE
from .native import NativeResult

class ProCache:
    """原生结果的磁盘缓存：`results/pro_cache.json`。

    一次穷举是小时级，之后所有迭代都应该读缓存（这是"只做一次"的前提）。
    键 = `NativeCase.key()`（含版本/弹型/dv_target/bc_target/场景/dt/观测模式）。

    ⚠ **缓存必须带 schema 版本**：映射口径改过（乘数的参照量、参考面积、级数）之后，
    旧条目是"用旧公式算出来的"，直接用会静默污染新结果——本项目踩过：
    410 条 `dv_blk=536.9` 的坏条目让 t_hit 从 45.1 变成 25.6。
    `CACHE_SCHEMA` 一改，旧缓存整体作废（重跑即可）。
    """

    def __init__(self, path=None, *, enabled: bool = True, schema: int = CACHE_SCHEMA):
        self.path = Path(path) if path else DEFAULT_CACHE
        self.enabled = bool(enabled)
        self.schema = int(schema)
        self.data: dict = {}
        self.dirty = False
        self.stale = False
        if self.enabled and self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
                if int(doc.get("schema", 0)) != self.schema:
                    self.stale = True
                    self.data = {}
                else:
                    self.data = dict(doc.get("entries") or {})
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                self.data = {}

    def get(self, key: str) -> NativeResult | None:
        if not self.enabled:
            return None
        d = self.data.get(key)
        if not d:
            return None
        r = NativeResult.from_dict(d)
        r.cache_hit = True
        return r

    def put(self, key: str, result: NativeResult):
        if not self.enabled:
            return
        self.data[key] = result.to_dict()
        self.dirty = True

    def save(self, *, runtime_info: dict | None = None) -> Path | None:
        if not self.enabled or not self.dirty:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema": self.schema,
            "note": "Pro 后端原生结果缓存（键 = NativeCase.key()）；可安全删除，重跑会重建",
            "runtime": runtime_info or {},
            "n_entries": len(self.data),
            "entries": self.data,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False
        return self.path


# --------------------------------------------------------------------- 子进程与运行器

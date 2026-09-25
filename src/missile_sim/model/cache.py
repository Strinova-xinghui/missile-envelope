# -*- coding: utf-8 -*-
"""**模型层 3（缓存部分）**：单工况结果的磁盘缓存（**按模型分库**）。

一次 Pro 穷举是小时级（1824 工况 ≈ 44 min），之后所有迭代都应该读缓存（“只做一次”的前提）；
Flash 是秒级，缓存只为省重复劳动。**不同模型的缓存必须分开**：

  * 键 = `EngineInputs.cache_key()`，其中含 `version` 与全部物理输入；
  * 顶层 `schema` = 该模型的 `ModelSpec.calc_version`（Pro=5 / Flash=1 / 第三方自定义），
    不符则**整体作废**并记原因；
  * 默认路径也是分开的（`results/pro_cache.json` / `results/flash_cache.json` /
    `results/cache/<模型名>.json`）。

⚠ **缓存必须带 schema 版本**：映射口径改过之后，旧条目是“用旧公式算出来的”，
直接用会静默污染新结果——本项目踩过：410 条 `dv_blk=536.9` 的坏条目让 t_hit 从 45.1 变 25.6。
⚠ 动 Flash 只改 `CALC_VERSION_FLASH`：Pro 那 1824 条重跑要 44 min。
"""

from __future__ import annotations

import json
from pathlib import Path

from .constants import CACHE_SCHEMA, DEFAULT_CACHE, FLASH_CACHE, ROOT, calc_version
from .native import NativeResult

# 模型 → 默认缓存路径 / 说明文字（说明文字会进产物，改它会让 `git diff` 多一行，无功能影响）
DEFAULT_PATH = {"pro": DEFAULT_CACHE, "flash": FLASH_CACHE}
CACHE_DIR = ROOT / "results" / "cache"
DEFAULT_NOTE = {
    "pro": "Pro 后端原生结果缓存（键 = EngineInputs.cache_key()）；可安全删除，重跑会重建",
    "flash": "Flash 后端结果缓存（键 = EngineInputs.cache_key()）；可安全删除，重跑会重建",
}


def model_cache_path(model: str) -> Path:
    """模型的默认缓存文件。`pro` / `flash` **路径保持不变**（既有资产不能挪）。"""
    m = str(model or "pro").strip().lower()
    return DEFAULT_PATH.get(m, CACHE_DIR / f"{m}.json")


def schema_of(model: str) -> int:
    """模型的缓存版本号：优先问注册表（第三方模型也能被正确分区）。"""
    try:
        from .registry import spec_of                            # noqa: PLC0415
        return int(spec_of(model).calc_version)
    except Exception:                                            # noqa: BLE001
        from .constants import calc_version                      # noqa: PLC0415
        return int(calc_version(model))


class ResultCache:
    """单工况结果的磁盘缓存：一层 JSON，`{schema, note, runtime, n_entries, entries}`。

    `model` 同时决定**默认路径**与**版本号**（也可用 `path`/`schema` 显式覆盖，
    例如把两套灰度实验塞进同一个文件里互不相认，见 `test_model_cache`）。
    """

    def __init__(self, path=None, *, enabled: bool = True, schema: int | None = None,
                 model: str = "pro", backend: str | None = None, note: str | None = None):
        self.model = str(model or backend or "pro").strip().lower()
        self.path = Path(path) if path else model_cache_path(self.model)
        self.enabled = bool(enabled)
        self.schema = int(schema_of(self.model) if schema is None else schema)
        self.note = note or DEFAULT_NOTE.get(
            self.model, f"{self.model} 模型结果缓存（键 = EngineInputs.cache_key()）；可安全删除")
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
            "note": self.note,
            "runtime": runtime_info or {},
            "n_entries": len(self.data),
            "entries": self.data,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False
        return self.path


class ProCache(ResultCache):
    """Pro 后端的缓存别名（签名保持旧样：`ProCache(path, enabled=…, schema=…)`）。

    既有代码与测试都用这个名字；`schema` 缺省 = `CACHE_SCHEMA`（= 5，与
    `results/pro_cache.json` 一致，**不要改**）。
    """

    def __init__(self, path=None, *, enabled: bool = True, schema: int = CACHE_SCHEMA, **kw):
        super().__init__(path, enabled=enabled, schema=schema, backend="pro", **kw)


class FlashCache(ResultCache):
    """Flash 后端的缓存：`results/flash_cache.json`，schema = `CALC_VERSION_FLASH`。"""

    def __init__(self, path=None, *, enabled: bool = True, schema: int | None = None, **kw):
        super().__init__(path, enabled=enabled, schema=schema, backend="flash", **kw)


def backend_cache(backend: str, path=None, *, enabled: bool = True) -> ResultCache:
    """按**模型注册名**建缓存（`pro` → `ProCache`；`flash` → `FlashCache`；其余 → 通用池）。

    名字保留"backend"是历史原因：它一侧是模型、一侧是缓存分区，两者必须同源。
    """
    b = str(backend or "pro").strip().lower()
    if b == "pro":
        return ProCache(path, enabled=enabled)
    if b == "flash":
        return FlashCache(path, enabled=enabled)
    return ResultCache(path, enabled=enabled, model=b)

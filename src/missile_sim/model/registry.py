# -*- coding: utf-8 -*-
"""**模型注册表**：名字 → 模型规格 → 引擎实现。

为什么要有它：后续会从开源拿到**更新的模型**（甚至换一整套公式），必须能像换零件一样接进来，
并且"这个产物是谁算的"要能一路追到具体实现与版本。所以：

    --model pro                     内置：原生仿真器（信源包执行游戏机器码）
    --model flash                   内置：本仓库公式引擎
    --model my-model                第三方：`missile_sim.models.my_model` 或 `$WT_MODELS_PATH` 下的包

第三方模型包只需要两个模块级对象（见 `docs/MODEL-API.md`）：

    MODEL_SPEC = ModelSpec(name="my-model", version="1.0.0", calc_version=1,
                           entry="my_model:MyEngine", source="…", capabilities=…)
    ENGINE = MyEngine(...)          # 提供 simulate / selftest / runtime_info（见 spec.Engine）

**接入即验**：`pipeline.py models --check` 会逐个跑 `Engine.selftest()`；注册表本身只负责发现与
缓存身份，不替模型背书。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

from .constants import ROOT
from .spec import Capability, Engine, ModelSpec

ENV_MODELS_PATH = "WT_MODELS_PATH"
MODELS_JSON = ROOT / "results" / "models.json"

# 第三方模型的发现前缀（包名 = 前缀 + "." + 注册名，且下划线化）
THIRD_PARTY_PKG = "missile_sim.models"

# 内置模型：这里**只写身份**，真正 import 引擎实现是懒的（缺原生包时也要能列出来）
BUILTIN_SPECS: dict = {
    "pro": ModelSpec(
        name="pro", label="Pro（原生仿真器）", version="2.59.0.28", calc_version=5,
        entry="missile_sim.model.native:ProEngine", source="builtin",
        capabilities=Capability(dims="3d", target_maneuvers=True, vectorized_batch=False,
                                trajectory=True, observation_modes=("ideal", "locked"),
                                wind=True, tvc=True),
        requirements={"native_pkg": True, "unicorn": True, "datamine": True},
        note="信源包在 Unicorn 里执行 2.59.0.28 的 aces 例程；保真但 ~1.4 s/工况"),
    "flash": ModelSpec(
        name="flash", label="Flash（本仓库公式引擎）", version="2.59.0.28", calc_version=1,
        entry="missile_sim.model.flash:FlashEngine", source="builtin",
        capabilities=Capability(dims="2d", target_maneuvers=False, vectorized_batch=True,
                                trajectory=True, observation_modes=("ideal",),
                                wind=False, tvc=False),
        requirements={"native_pkg": False, "numpy": True, "datamine": True},
        note="纯 Python 公式实现；无原生包也能跑，用于快速迭代"),
}


class ModelNotFound(KeyError):
    """注册名不存在，或第三方模型包导入失败。"""


def _as_name(name) -> str:
    if isinstance(name, ModelSpec):
        return _norm(name.name)
    return _norm(name)


def _norm(name: str) -> str:
    """注册名归一：大小写不敏感、连字符与下划线等价（`stub-model` == `stub_model`）。"""
    return str(name or "").strip().lower().replace("-", "_")


def package_name_for(pkg_dir) -> str:
    """第三方模型目录 → **实际可导入的包名**。

    目录名可以带连字符（CLI 好写），但 import 不认；所以先 `<目录>/__init__.py` 里的
    `MODEL_SPEC.entry`，再退回目录名本身。
    """
    entry = read_entry_field(Path(pkg_dir))
    if entry:
        return str(entry).partition(":")[0]
    return Path(pkg_dir).name


def read_entry_field(pkg_dir) -> str:
    """不 import 也能读 `MODEL_SPEC` 的 entry（按文本抠一行，够用且无副作用）。"""
    for fn in ("__init__.py", "model.py"):
        p = Path(pkg_dir) / fn
        if not p.is_file():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in txt.splitlines():
            s = line.strip()
            if s.startswith(("entry=", "entry =")):
                val = s.split("=", 1)[1].strip().split(",")[0].strip()
                return val.strip('"\'')
    return ""


def _import_from_dir(pkg_name: str, pkg_dir: Path, sub: str = ""):
    """从**目录**直接加载第三方包（目录名带连字符时普通 import 找不到，这条兜底）。

    依据文件推导模块名（`<pkg_name>.model` 优先），再用 `spec_from_file_location` 按
    `submodule_search_locations` 建包，因此包内的相对 import 仍然可用。
    """
    for fn in ("__init__.py", "model.py"):
        p = pkg_dir / fn
        if not p.is_file():
            continue
        mod_name = f"{pkg_name}.model" if fn == "model.py" else pkg_name
        if sub:
            mod_name = f"{mod_name}.{sub}"
            p = pkg_dir / sub / "__init__.py"
            if not p.is_file():
                continue
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        search = [str(pkg_dir)] if fn == "__init__.py" else None
        spec = importlib.util.spec_from_file_location(mod_name, p, submodule_search_locations=search)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod
    return None


def _third_party_dirs() -> list:
    """`$WT_MODELS_PATH` 下的候选模型目录：[(实际包名, 目录)]。"""
    out = []
    for raw in (os.environ.get(ENV_MODELS_PATH, "") or "").split(os.pathsep):
        raw = raw.strip()
        if not raw or not Path(raw).is_dir():
            continue
        base = Path(raw)
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            if any((entry / f).exists() for f in ("__init__.py", "model.py")):
                out.append((package_name_for(entry), entry))
    return out


def _load_third_party(name: str) -> ModelSpec:
    """按注册名找第三方模型：内置包的 `missile_sim.models.<名>` 或 `$WT_MODELS_PATH` 下的目录。

    ⚠ 目录名可能带连字符（为了 CLI 好写），但**包名不能**——所以按目录名归一化匹配，
    再用 `package_name_for` 得到的真名 import。
    """
    want = _norm(name)
    errs = []
    listed = _third_party_dirs()
    pkg_name = None
    for dir_name, entry in listed:
        if _norm(entry.name) == want or _norm(dir_name) == want:
            pkg_name = dir_name
            break
    if pkg_name is None:
        cand = f"{THIRD_PARTY_PKG}.{want}"
        try:
            mod = importlib.import_module(cand)
            spec = getattr(mod, "MODEL_SPEC", None)
            if spec is None or getattr(mod, "ENGINE", None) is None:
                errs.append(f"{cand}: 缺少 MODEL_SPEC/ENGINE")
            else:
                return spec
        except ImportError as exc:
            errs.append(f"{cand}: {exc}")
        raise ModelNotFound(
            f"没有注册名为 {name!r} 的模型。已注册：{'、'.join(sorted(BUILTIN_SPECS))}"
            + (f"；$WT_MODELS_PATH 下发现："
               + "、".join(e.name for _d, e in listed) if listed else "")
            + (f"；查找失败：" + "；".join(errs) if errs else "")
        )
    for mod_name in (pkg_name, f"{pkg_name}.model"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            errs.append(f"{mod_name}: {exc}")
            continue
        spec = getattr(mod, "MODEL_SPEC", None)
        if spec is None:
            errs.append(f"{mod_name}: 缺少 MODEL_SPEC")
            continue
        if getattr(mod, "ENGINE", None) is None:
            errs.append(f"{mod_name}: 缺少 ENGINE")
            continue
        return spec
    # 兜底：目录名带连字符等普通 import 找不到的情况，直接按文件加载
    pkg_dir = next((e for d, e in listed if d == pkg_name), None)
    if pkg_dir is not None:
        mod = _import_from_dir(pkg_name, pkg_dir)
        if mod is not None:
            spec = getattr(mod, "MODEL_SPEC", None)
            if spec is not None and getattr(mod, "ENGINE", None) is not None:
                return spec
            errs.append(f"{pkg_dir}: 缺少 MODEL_SPEC/ENGINE（按文件加载后仍缺）")
    raise ModelNotFound(f"第三方模型 {name!r} 加载失败：" + "；".join(errs))


def spec_of(name) -> ModelSpec:
    """注册名 → `ModelSpec`（内置优先，其次第三方）。"""
    if isinstance(name, ModelSpec):
        return name
    key = _as_name(name)
    if key in BUILTIN_SPECS:
        return BUILTIN_SPECS[key]
    return _load_third_party(key)


def load_engine(name, *, env=None, **kw) -> Engine:
    """注册名 → 引擎实例。

    `env` 只用于内置模型需要运行环境时（如原生包路径）；第三方模型由自己的 `ENGINE`
    负责，`env` 通过 `EngineEnv` 在 `simulate` 时传入。
    """
    spec = spec_of(name)
    mod_name, _, attr = str(spec.entry).partition(":")
    if not attr:
        raise ModelNotFound(f"模型 {spec.name!r} 的 entry 非法：{spec.entry!r}（应为 '模块:对象'）")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as exc:
        raise ModelNotFound(f"模型 {spec.name!r} 的实现模块导不进来：{mod_name}（{exc}）") from exc
    obj = getattr(mod, attr, None)
    if obj is None:
        raise ModelNotFound(f"模型 {spec.name!r} 的 entry 指向不存在的对象：{spec.entry!r}")
    if isinstance(obj, type):
        try:
            return obj(env=env, **kw)
        except TypeError:
            return obj()
    return obj


def list_models(*, include_third_party: bool = True) -> list:
    """全部已知模型规格（内置 + `$WT_MODELS_PATH` 下的第三方目录）。

    第三方目录：子目录名即注册名（连字符/下划线等价），目录里要有 `__init__.py`
    （含 `MODEL_SPEC` / `ENGINE`）或 `model.py`。
    """
    out = [BUILTIN_SPECS[k] for k in sorted(BUILTIN_SPECS)]
    if include_third_party:
        seen = {_norm(s.name) for s in out}
        for dir_name, _p in _third_party_dirs():
            if _norm(dir_name) in seen:
                continue
            try:
                out.append(spec_of(dir_name))
            except ModelNotFound:
                continue
    return out


def models_table() -> dict:
    """版本矩阵（落 `results/models.json`）：谁、什么版本、缓存号、能力、依赖。"""
    return {
        "schema": 1,
        "note": "已注册计算模型的身份表（--model 的取值来源）；改模型数值必须同时 +calc_version",
        "models": {s.name: s.to_dict() for s in list_models()},
    }


def write_models_table(path: Path | None = None) -> Path:
    import json

    p = Path(path) if path else MODELS_JSON
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(models_table(), ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def check_models(*, names=None, env=None, verbose: bool = True) -> dict:
    """逐个跑 `selftest`。返回 {名字: SelfTestReport.to_dict()}；不抛异常，如实记录。"""
    from .env import build_env

    picked = [spec_of(n) for n in names] if names else list_models()
    out = {}
    for spec in picked:
        try:
            engine = load_engine(spec.name, env=env)
            e = env if env is not None else build_env(spec)
            rep = engine.selftest(e)
        except Exception as exc:                            # noqa: BLE001
            from .spec import SelfTestReport
            rep = SelfTestReport(name=spec.name, ok=False, error=f"{type(exc).__name__}: {exc}")
        out[spec.name] = rep.to_dict()
        if verbose:
            mark = "OK  " if rep.ok else "FAIL"
            print(f"{mark} {spec.name:12s} {spec.label}")
            for c in rep.checks:
                print(f"       [{'√' if c['ok'] else '×'}] {c['item']}"
                      + (f" —— {c['note']}" if c.get("note") else ""))
            if rep.error:
                print(f"       ! {rep.error}")
    return out

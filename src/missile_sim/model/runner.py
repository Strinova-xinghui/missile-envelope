# -*- coding: utf-8 -*-
"""**模型层 2（执行器）**：进程池 + 缓存调度。

每次原生积分都要独立 Unicorn 实例；`simulate_native` 不可重入（它改 `core.load_profile`），
所以并发只能靠**多进程**——每个子进程独立 import 原生包。

`simulate_native` 与 `ProRunner` 放在同一模块，是为了让"打桩测试"能真正生效：
若把 `simulate_native` 挪到别处，对它的 monkeypatch 就拦不住这里。
（要拦截本模块的调用请打桩 `missile_sim.model.runner.simulate_native`。）

**与结构化 API 的关系**：执行器只管"并发 + 缓存 + 进度"，不知道物理。引擎实现走
`Engine` 协议（`self.engine`）；传入 `EngineInputs` 时优先经引擎跑，没有引擎时退回
模块级 `simulate_native`（单测与脚本用）。
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

from .cache import ProCache
from .constants import CACHE_SCHEMA, DEFAULT_PKG, ELF_SHA256_28, ENV_PKG, VERSION_28
from .native import (  # noqa: F401
    NativeCase,
    NativeResult,
    ProEngine,
    case_from_inputs,
    resolve_pkg,
    simulate_native,
    verify_elf,
)


def _worker_run_engine(payload) -> dict:
    """子进程：用**引擎契约**跑一个工况（输入/输出都是普通 dict，可安全跨进程）。"""
    engine_name, inp_dict, env_dict, model_names = payload
    import importlib                                            # noqa: PLC0415

    for m in model_names:
        importlib.import_module(m)
    from . import registry as reg                               # noqa: PLC0415
    from .spec import EngineEnv                                 # noqa: PLC0415

    inp = restore_engine_inputs(inp_dict)
    env = EngineEnv(**{k: v for k, v in env_dict.items() if k in EngineEnv.__dataclass_fields__})
    if env.workdir:
        import os as _os                                        # noqa: PLC0415
        _os.chdir(env.workdir)
    engine = reg.load_engine(engine_name, env=env)
    return engine.simulate(inp, env).to_dict()


def restore_engine_inputs(inp_dict: dict):
    """跨进程传回来的普通 dict → `EngineInputs`。

    `_dataclass_dict` 用的是 `dataclasses.asdict`，它**递归**把嵌套参数块也变成 dict，因此这里
    必须逐块还原 —— 否则子进程里访问 `inp.mass.dry`（`EngineInputs.check()` 就会碰）会抛
    `AttributeError: 'dict' object has no attribute 'dry'`。
    frozen dataclass 里的嵌套集合（`pid_rows` / `time_gain` / `hit_gain` / `wind_m_s` /
    `target_maneuvers`）本来都是 tuple，`asdict` 会把它们变成 list，这里一并转回 tuple。
    """
    from . import spec as SP                                    # noqa: PLC0415

    def build(cls, raw):
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in raw.items() if k in fields})

    blocks = {
        "mass": SP.MassProfile, "geometry": SP.Geometry, "aero": SP.AeroCoeffs,
        "autopilot": SP.Autopilot, "loft": SP.LoftConfig, "gains": SP.GainTables,
        "limits": SP.Limits, "fuse": SP.Fuse,
    }
    kw = {k: v for k, v in inp_dict.items() if k in SP.EngineInputs.__dataclass_fields__}
    for key, cls in blocks.items():
        raw = kw.get(key)
        if isinstance(raw, dict):
            kw[key] = build(cls, raw)

    ap = kw.get("autopilot")
    if isinstance(ap, SP.Autopilot) and ap.pid_rows:
        object.__setattr__(ap, "pid_rows",
                           tuple(build(SP.PidRow, r) if isinstance(r, dict) else r
                                 for r in ap.pid_rows))
    lo = kw.get("loft")
    if isinstance(lo, SP.LoftConfig) and isinstance(lo.range_to_loft_elevation, list):
        object.__setattr__(lo, "range_to_loft_elevation", tuple(lo.range_to_loft_elevation))
    ga = kw.get("gains")
    if isinstance(ga, SP.GainTables):
        for k in ("time_gain", "hit_gain"):
            v = getattr(ga, k)
            if isinstance(v, list):
                object.__setattr__(ga, k, tuple(tuple(x) if isinstance(x, list) else x for x in v))
    for key in ("wind_m_s", "target_maneuvers"):
        v = kw.get(key)
        if isinstance(v, list):
            kw[key] = tuple(tuple(x) if isinstance(x, list) else x for x in v)
    return SP.EngineInputs(**kw)


def _worker_init(pkg_str: str):
    """子进程初始化：切到包根（原生 resources 用**相对** ROOT 找 inputs/），并挂 sys.path。"""
    import os as _os
    _os.chdir(pkg_str)
    for p in (str(Path(pkg_str) / "tools"), pkg_str):
        if p not in sys.path:
            sys.path.insert(0, p)


def _worker_run(payload) -> dict:
    case_dict, pkg_str = payload
    fields = NativeCase.__dataclass_fields__
    case = NativeCase(**{k: v for k, v in case_dict.items() if k in fields})
    if isinstance(case.wind_m_s, list):
        object.__setattr__(case, "wind_m_s", tuple(case.wind_m_s))
    if isinstance(case.target_maneuvers, list):
        object.__setattr__(case, "target_maneuvers",
                           tuple((m[0], tuple(m[1])) for m in case.target_maneuvers))
    return simulate_native(case, pkg_str).to_dict()


class ProRunner:
    """Pro 执行器（原生）：进程池 + 缓存。

    单进程只能串行（`simulate_native` 不可重入——它改 `core.load_profile`），
    所以并发靠**多进程**：每个子进程独立 import 原生包、独立 Unicorn 实例。

    **引擎可替换**：传 `engine` 就用引擎（结构化契约的正门）；不传则按需建 `ProEngine`，
    但**没有任何引擎的裸调用仍走模块级 `simulate_native`**（单测打桩点）。

    **缓存周期性落盘**（`flush_every`）：一轮扫满是小时级，只在 `close()` 时写盘意味着
    中途任何中断都会把已跑完的原生结果全丢（本项目踩过：跑 8 分钟崩一次，结果全没）。
    """

    def __init__(self, *, pkg=None, version: str = VERSION_28, jobs: int = 8,
                 cache: ProCache | None = None, progress=None, flush_every: int = 200,
                 engine=None, env=None, bare: bool = False):
        self.pkg = resolve_pkg(pkg)
        self.version = version
        self.jobs = max(1, int(jobs))
        self.cache = cache if cache is not None else ProCache()
        self.progress = progress
        self.flush_every = max(1, int(flush_every))
        self._pending = 0
        self._pool = None
        self.stats = {"native": 0, "cache": 0}
        # 结构化 API：引擎是正门（输入契约 = EngineInputs）。
        # ⚠ `bare=True` 是**权威开关**：明确"不要引擎"，一律走模块级 `simulate_native`
        #   ——单测打桩点（`tests/test_scanner.py` / `test_model_cache.py` 都靠它）。
        #   注意它必须优先于外部传进来的 engine，否则调用方传了 engine 就悄悄绕过了打桩。
        self.env = env
        if bare:
            self.engine = None
        elif engine is not None:
            self.engine = engine
        else:
            self.engine = ProEngine(pkg=self.pkg, version=version, env=env)
        self.runtime_info = {"pkg": str(self.pkg), "version": version}
        if self.engine is not None:
            try:
                self.runtime_info = {**self.runtime_info, **self.engine.runtime_info()}
            except Exception:                               # noqa: BLE001  身份拿不到不该挡住计算
                pass

    def _flush(self, force: bool = False):
        """累计到 `flush_every` 条就落盘（force=True 时无条件落）。"""
        if not force and self._pending < self.flush_every:
            return
        if self.cache.save(runtime_info=self.runtime_info) is not None:
            self._pending = 0

    # --- 池管理 -------------------------------------------------------

    def _ensure_pool(self):
        if self._pool is None and self.jobs > 1:
            from concurrent.futures import ProcessPoolExecutor
            self._pool = ProcessPoolExecutor(
                max_workers=self.jobs, initializer=_worker_init, initargs=(str(self.pkg),))
        return self._pool

    def close(self):
        """关闭池并**持久化缓存**。

        缓存保存必须放在 `finally` 里：原生跑一轮是小时级，任何中途异常（回调签名、
        键盘中断、原生失败）都不能把已经跑出来的结果丢掉。
        """
        try:
            if self._pool is not None:
                self._pool.shutdown(wait=True)
        finally:
            self._pool = None
            self.cache.save(runtime_info=self.runtime_info)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- 运行 ---------------------------------------------------------

    def _can_pool(self) -> bool:
        """能不能走进程池：jobs > 1，且引擎**没有声明**向量化批量。

        引擎自己声明了 `capabilities.vectorized_batch`（纯 Python 引擎一次算整个网格，
        比多进程更快更省内存）时就不该再套一层进程池；没声明的（如 Pro）走多进程。
        """
        if self.jobs <= 1:
            return False
        caps = getattr(getattr(self.engine, "spec", None), "capabilities", None)
        return not bool(getattr(caps, "vectorized_batch", False))

    def _run_single(self, case: NativeCase) -> NativeResult:
        """单工况执行：**有引擎走引擎**（结构化契约），否则退回模块级 `simulate_native`。

        退回路径是给单测/脚本/打桩留的（`tests/test_pro.py` 打桩
        `runner.simulate_native` 来验证"失败不写缓存"）。
        """
        if self.engine is not None:
            from . import io as io_mod                          # noqa: PLC0415
            inp = io_mod.inputs_from_case(case)
            return self.engine.simulate(inp, self.env)
        return simulate_native(case, self.pkg)

    def run_inputs(self, inputs, *, progress=None) -> NativeResult:
        """按**结构化输入**跑一个工况（引擎契约的正门；缓存键由输入算）。"""
        if self.engine is None:
            self.engine = ProEngine(pkg=self.pkg, version=self.version, env=self.env)
        key = inputs.cache_key()
        hit = self.cache.get(key)
        if hit is not None:
            self.stats["cache"] += 1
            return hit
        res = self.engine.simulate(inputs, self.env)
        self.stats["native"] += 1
        if res.ok and not inputs.save_trajectory:
            self.cache.put(key, res)
            self._pending += 1
            self._flush()
        return res

    def run_one(self, case: NativeCase) -> NativeResult:
        key = case.key()
        hit = self.cache.get(key)
        if hit is not None:
            self.stats["cache"] += 1
            return hit
        if self._can_pool():
            ex = self._ensure_pool()
            res = NativeResult.from_dict(ex.submit(_worker_run, (asdict(case), str(self.pkg))).result())
        else:
            res = self._run_single(case)
        self.stats["native"] += 1
        # 只缓存"不带轨迹"的结果：轨迹是单条记录的 95%，进缓存会把文件撑到几十 MB
        # （实测 1824 工况会到 73 MB）。要轨迹就显式 `save_trajectory=True` 且不缓存。
        if res.ok and not case.save_trajectory:
            self.cache.put(key, res)
            self._pending += 1
            self._flush()
        return res

    def run_many(self, cases) -> list[NativeResult]:
        """批量：先打缓存，再一次性并发跑缺的。返回顺序与入参一致。"""
        cases = list(cases)
        out: list[NativeResult | None] = [None] * len(cases)
        todo = []
        for i, c in enumerate(cases):
            key = c.key()
            got = self.cache.get(key)
            if got is not None:
                out[i] = got
                self.stats["cache"] += 1
            else:
                todo.append((i, c))
        if todo:
            if self._can_pool():
                ex = self._ensure_pool()
                futs = {ex.submit(_worker_run, (asdict(c), str(self.pkg))): i for i, c in todo}
                from concurrent.futures import as_completed
                done = 0
                for fut in as_completed(futs):
                    i = futs[fut]
                    res = NativeResult.from_dict(fut.result())
                    out[i] = res
                    self.stats["native"] += 1
                    if res.ok and not cases[i].save_trajectory:
                        self.cache.put(cases[i].key(), res)
                        self._pending += 1
                        self._flush()
                    done += 1
                    if self.progress:
                        # 回调签名与 sim.simulate_batch 一致：(step, total, active)
                        self.progress(done, len(todo), 0)
            else:
                for n, (i, c) in enumerate(todo, 1):
                    res = self._run_single(c)
                    out[i] = res
                    self.stats["native"] += 1
                    if res.ok and not c.save_trajectory:
                        self.cache.put(c.key(), res)
                        self._pending += 1
                        self._flush()
                    if self.progress:
                        self.progress(n, len(todo), 0)
        return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]


# --------------------------------------------------------------------- 通用执行器

class EngineRunner:
    """**任意模型**的通用执行器：进程池 + 缓存 + 进度，完全不含物理。

    与 `ProRunner` 的区别：这个不认识原生包，只认"`Engine` 协议 + `EngineInputs`"，因此
    Pro / Flash / 第三方（开源拿到的更新模型）都能用它跑；进程池里的 worker 用
    **可跨进程的普通 dict** 传输入与身份（`_worker_run_engine`）。
    """

    def __init__(self, engine, *, env=None, cache=None, jobs: int = 1, progress=None,
                 flush_every: int = 200):
        from .registry import spec_of                           # noqa: PLC0415

        self.engine = engine
        self.env = env
        self.spec = getattr(engine, "spec", None) or spec_of(
            getattr(engine, "spec", None) or "flash")
        self.jobs = max(1, int(jobs))
        self.cache = cache
        self.progress = progress
        self.flush_every = max(1, int(flush_every))
        self._pending = 0
        self._pool = None
        self.stats = {"native": 0, "cache": 0}
        self.pkg = getattr(env, "pkg", None)
        try:
            self.runtime_info = dict(engine.runtime_info())
        except Exception:                                       # noqa: BLE001
            self.runtime_info = {"engine": self.spec.name, "engine_version": self.spec.version}

    # --- 池 -----------------------------------------------------------

    def _can_pool(self) -> bool:
        caps = getattr(self.spec, "capabilities", None)
        return self.jobs > 1 and not bool(getattr(caps, "vectorized_batch", False))

    def _pool_payload(self, inp):
        env_dict = self.env.to_dict() if hasattr(self.env, "to_dict") else {}
        # 子进程 spawn 后是干净的：把它需要的模块先 import 回来
        names = ["missile_sim.model.registry", "missile_sim.model.spec",
                 "missile_sim.model.native", "missile_sim.model.wtgame"]
        if self.env is not None and self.env.pkg:
            names.append("missile_sim.model.runner")
        return (self.spec.name, _dataclass_dict(inp), env_dict, names)

    def _ensure_pool(self):
        if self._pool is None and self._can_pool():
            from concurrent.futures import ProcessPoolExecutor   # noqa: PLC0415
            self._pool = ProcessPoolExecutor(max_workers=self.jobs)
        return self._pool

    def _flush(self, force: bool = False):
        if self.cache is None:
            return
        if not force and self._pending < self.flush_every:
            return
        if self.cache.save(runtime_info=self.runtime_info) is not None:
            self._pending = 0

    def close(self):
        try:
            if self._pool is not None:
                self._pool.shutdown(wait=True)
        finally:
            self._pool = None
            self._flush(force=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- 运行 ---------------------------------------------------------

    def run_inputs(self, inputs):
        key = inputs.cache_key()
        if self.cache is not None:
            got = self.cache.get(key)
            if got is not None:
                self.stats["cache"] += 1
                return got
        ex = self._ensure_pool()
        if ex is not None:
            res = NativeResult.from_dict(ex.submit(_worker_run_engine, self._pool_payload(inputs)).result())
        else:
            res = self.engine.simulate(inputs, self.env)
        self.stats["native"] += 1
        if res.ok and not inputs.save_trajectory and self.cache is not None:
            self.cache.put(key, res)
            self._pending += 1
            self._flush()
        return res

    def run_one(self, case: NativeCase):
        return self.run_inputs(self._case_inputs(case))

    def run_many(self, cases):
        cases = list(cases)
        inputs = [self._case_inputs(c) for c in cases]
        out = [None] * len(cases)
        todo = []
        for i, inp in enumerate(inputs):
            if self.cache is not None:
                got = self.cache.get(inp.cache_key())
                if got is not None:
                    out[i] = got
                    self.stats["cache"] += 1
                    continue
            todo.append((i, inp))
        ex = self._ensure_pool()
        if ex is not None and todo:
            futs = {ex.submit(_worker_run_engine, self._pool_payload(inp)): i for i, inp in todo}
            done = 0
            from concurrent.futures import as_completed           # noqa: PLC0415
            for fut in as_completed(futs):
                i = futs[fut]
                res = NativeResult.from_dict(fut.result())
                out[i] = res
                self._after(res, inputs[i], i)
                done += 1
                if self.progress:
                    self.progress(done, len(todo), 0)
        else:
            total = len(todo)
            for n, (i, inp) in enumerate(todo, 1):
                res = self.engine.simulate(inp, self.env)
                out[i] = res
                self._after(res, inp, i)
                if self.progress:
                    self.progress(n, total, 0)
        return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]

    # --- 内部 ---------------------------------------------------------

    def _after(self, res, inp, index):
        self.stats["native"] += 1
        if res.ok and not inp.save_trajectory and self.cache is not None:
            self.cache.put(inp.cache_key(), res)
            self._pending += 1
            self._flush()

    def _case_inputs(self, case: NativeCase):
        from . import io as io_mod                              # noqa: PLC0415
        return io_mod.inputs_from_case(case)


def _dataclass_dict(obj) -> dict:
    from dataclasses import asdict                              # noqa: PLC0415
    d = asdict(obj)
    for k, v in list(d.items()):
        if isinstance(v, tuple):
            d[k] = list(v)
    return d


# --------------------------------------------------------------------- ΔV → 推力乘数（解析）

# -*- coding: utf-8 -*-
"""**模型层 2（执行器）**：进程池 + 缓存调度。

每次原生积分都要独立 Unicorn 实例；`simulate_native` 不可重入（它改 `core.load_profile`），
所以并发只能靠**多进程**——每个子进程独立 import 原生包。

`simulate_native` 与 `ProRunner` 放在同一模块，是为了让"打桩测试"能真正生效：
若把 `simulate_native` 挪到别处，对它的 monkeypatch 就拦不住这里。
（要拦截本模块的调用请打桩 `missile_sim.model.runner.simulate_native`。）
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
    resolve_pkg,
    simulate_native,
    verify_elf,
)

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
    """原生运行器：进程池 + 缓存。

    单进程只能串行（`simulate_native` 不可重入——它改 `core.load_profile`），
    所以并发靠**多进程**：每个子进程独立 import 原生包、独立 Unicorn 实例。

    **缓存周期性落盘**（`flush_every`）：一轮扫满是小时级，只在 `close()` 时写盘意味着
    中途任何中断都会把已跑完的原生结果全丢（本项目踩过：跑 8 分钟崩一次，结果全没）。
    """

    def __init__(self, *, pkg=None, version: str = VERSION_28, jobs: int = 8,
                 cache: ProCache | None = None, progress=None, flush_every: int = 200):
        self.pkg = resolve_pkg(pkg)
        self.version = version
        self.jobs = max(1, int(jobs))
        self.cache = cache if cache is not None else ProCache()
        self.progress = progress
        self.flush_every = max(1, int(flush_every))
        self._pending = 0
        self._pool = None
        self.stats = {"native": 0, "cache": 0}
        self.runtime_info = {"pkg": str(self.pkg), "version": version}

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

    def run_one(self, case: NativeCase) -> NativeResult:
        key = case.key()
        hit = self.cache.get(key)
        if hit is not None:
            self.stats["cache"] += 1
            return hit
        if self.jobs > 1:
            ex = self._ensure_pool()
            res = NativeResult.from_dict(ex.submit(_worker_run, (asdict(case), str(self.pkg))).result())
        else:
            res = simulate_native(case, self.pkg)
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
            if self.jobs > 1:
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
                    res = simulate_native(c, self.pkg)
                    out[i] = res
                    self.stats["native"] += 1
                    if res.ok and not c.save_trajectory:
                        self.cache.put(c.key(), res)
                        self._pending += 1
                        self._flush()
                    if self.progress:
                        self.progress(n, len(todo), 0)
        return [r if r is not None else NativeResult(ok=False, error="未执行") for r in out]


# --------------------------------------------------------------------- ΔV → 推力乘数（解析）

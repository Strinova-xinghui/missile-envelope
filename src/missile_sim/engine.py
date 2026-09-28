# -*- coding: utf-8 -*-
"""执行层：**单工况 / 多工况（进程池）+ 结果缓存**。

求解器是标量循环、没有向量化批量，所以并发只能靠多进程；两档的 `standard` 逐物理步、
`fast` 走 C 内核，同一 `Engine` 换 `tier` 即可。

缓存按**档位分文件**（`results/cache/<tier>.json`），并且 `cache_key()` **显式包含 tier**：
两档是同一物理的两条算术路径，理论上键可以不带档位，但旧架构正是"靠分文件隔离、键里不带档"
而让一个档的键被另一个档复用（AGENTS.md 记着这次事故），所以两处都带上，冗余换安全。

跨进程只传**扁平**的 `Scene`/`Scaling` dict：新契约里没有旧实现那些对求解器惰性的参数块
（mass/geometry/aero/…），所以不需要"子进程重建嵌套 dataclass"的补丁。
"""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import mapping, solver
from .spec import CACHE_DIR, VERSION_28, Scaling, Scene, Shot

CACHE_SCHEMA = 4                     # 改任何影响"输入→结果"的东西就 +1（整库作废重建）


# --------------------------------------------------------------------- 缓存


class ResultCache:
    """按档位分库的结果缓存。schema 不符 ⇒ 整库作废（不抛错）。"""

    def __init__(self, path: Path | None = None, *, tier: str = "standard",
                 enabled: bool = True, schema: int = CACHE_SCHEMA):
        self.enabled = bool(enabled)
        self.schema = int(schema)
        self.tier = str(tier)
        self.path = Path(path) if path else (CACHE_DIR / f"{self.tier}.json")
        self.stale = False
        self.data: dict = {}
        self.dirty = False
        self.loaded = False

    def _load(self) -> None:
        if self.loaded:
            return
        self.loaded = True
        if not self.enabled or not self.path.exists():
            return
        try:
            blob = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self.data = {}
            return
        if int(blob.get("schema", -1)) != self.schema:
            self.stale = True                 # 整库作废：宁可从零重算，也不混口径
            self.data = {}
            return
        self.data = dict(blob.get("entries") or {})

    def get(self, key: str) -> Shot | None:
        self._load()
        hit = self.data.get(key)
        if not hit:
            return None
        shot = Shot.from_dict(hit)
        shot.cache_hit = True
        return shot

    def put(self, key: str, shot: Shot) -> None:
        if not self.enabled:
            return
        self._load()
        d = shot.as_dict()
        d["cache_hit"] = False                # 缓存里存"原始结果"，命中标记由 get 打
        self.data[key] = d
        self.dirty = True

    def save(self) -> Path | None:
        if not self.enabled or not self.dirty:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = {"schema": self.schema, "tier": self.tier, "n_entries": len(self.data),
                "note": "键含 version/missile/tier/全部 Scaling 乘数/场景全部自由量；schema 不符整库作废",
                "entries": self.data}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False
        return self.path


# --------------------------------------------------------------------- 缓存键


def cache_key(scene: Scene, missile: str, scaling: Scaling, tier: str) -> str:
    """一次求解的身份。**场景的全部自由量与全部乘数都在里面**（含 `duration_s` —— 它影响超时截断）。

    乘数取 `Scaling.as_dict()` 逐项 `round(…, 6)`：网格步长是 10/25 这种量级，
    小数点后 6 位足够且避免浮点抖动。

    ⚠ 曾经这里只收 `(dv, bc)` 两个数 —— 那样 β–γ 扫描的 `cxaoa_scale` 不在键里，
    同一张图上不同 γ 的格点会**互相命中缓存**，而且结果看起来完全正常。整块 `Scaling`
    进键以后，以后再加乘数就自动进键，不会再犯。
    """
    sc = scaling.as_dict()
    blob = json.dumps([
        VERSION_28, str(missile), str(tier),
        {k: (round(float(v), 6) if isinstance(v, (int, float)) else v)
         for k, v in sorted(sc.items())},
        scene.range_m, scene.alt_m, scene.target_alt, scene.target_bearing_deg,
        scene.vm0, scene.launch_heading_deg, scene.launch_pitch_deg,
        scene.target_speed_ms, scene.target_heading_deg, scene.target_pitch_deg,
        scene.duration_s, scene.dt_s, scene.observation, scene.hit_radius_m,
        scene.proximity_fuse, list(scene.wind_m_s), scene.ground_height_m,
        [list(m) for m in (scene.maneuvers or ())],
    ], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


# --------------------------------------------------------------------- 进程池 worker


def _run_payload(payload: dict) -> dict:
    """子进程入口（必须是模块级函数才可 pickle）。"""
    scene = Scene.from_dict(payload["scene"])
    sc = Scaling.from_dict(payload["scaling"]) if payload.get("scaling") else None
    shot = solver.run(scene, missile=payload["missile"], scaling=sc,
                      tier=payload["tier"], want_rows=bool(payload.get("want_rows")))
    return shot.as_dict()


# --------------------------------------------------------------------- 引擎


class Engine:
    """跑"基准弹 + 二维网格"的执行器。

    用法：
        eng = Engine(scene, missile="cn_pl12", tier="fast", jobs=8)
        shot = eng.one(932.57, 3078.1)
        shots = eng.many(grid.cells)
        eng.close()

    `scaling_of(x, y) -> Scaling` 决定"一个格点怎么落到求解器上"：默认是 `(ΔV, BC)` 平面
    （第一张图，`mapping.scaling_for`），β–γ 平面（第二张图）传 `bg.scaling_for`。
    `Engine` 本身对"这两个数叫什么"不作假设。
    """

    def __init__(self, scene: Scene, *, missile: str, tier: str = "standard",
                 jobs: int = 8, cache: bool = True, cache_path=None,
                 metrics: mapping.BlkMetrics | None = None, progress=None,
                 scaling_of=None):
        bad = scene.check()
        if bad:
            raise ValueError("场景不自洽：" + "；".join(bad))
        self.scene = scene
        self.missile = str(missile)
        self.tier = str(tier)
        self.jobs = max(1, int(jobs))
        self.progress = progress
        self.metrics = metrics if metrics is not None else mapping.blk_metrics(
            solver.profile(self.missile))
        self.scaling_of = scaling_of or (
            lambda x, y: mapping.scaling_for(x, y, self.metrics))
        self.cache = ResultCache(cache_path, tier=self.tier, enabled=cache)
        self.stats = {"runs": 0, "ok": 0, "cache": 0, "errors": 0}
        self._pool: ProcessPoolExecutor | None = None

    # --- 单工况 -------------------------------------------------------

    def one(self, dv: float | None = None, bc: float | None = None,
            *, want_rows: bool = False) -> Shot:
        """跑一个格点。`dv`/`bc` 为 None ⇒ 标称值（不施加乘数）。

        β–γ 平面同样走这个方法：那两个位置参数就是 `(β, γ)`，由 `scaling_of` 解释。
        """
        sc = self.scaling_of(dv, bc)
        key = cache_key(self.scene, self.missile, sc, self.tier)
        if not want_rows:
            hit = self.cache.get(key)
            if hit is not None:
                self.stats["cache"] += 1
                return hit
        shot = solver.run(self.scene, missile=self.missile, scaling=sc,
                          tier=self.tier, want_rows=want_rows)
        self.stats["runs"] += 1
        if shot.ok:
            self.stats["ok"] += 1
        else:
            self.stats["errors"] += 1
        if shot.ok and not want_rows:
            self.cache.put(key, shot)
        return shot

    # --- 多工况 -------------------------------------------------------

    def many(self, cells, *, want_rows: bool = False, flush_every: int = 200) -> list:
        """跑一批格点（行优先顺序与输入一致）。命中缓存的直接返回，不重算。"""
        cells = [(None if dv is None else float(dv), None if bc is None else float(bc))
                 for dv, bc in cells]
        out: list = [None] * len(cells)
        todo = []
        for i, (dv, bc) in enumerate(cells):
            sc = self.scaling_of(dv, bc)
            key = cache_key(self.scene, self.missile, sc, self.tier)
            if not want_rows:
                hit = self.cache.get(key)
                if hit is not None:
                    out[i] = hit
                    self.stats["cache"] += 1
                    continue
            todo.append((i, sc, key))
        if not todo:
            return out

        payloads = [{"scene": self.scene.as_dict(), "missile": self.missile,
                     "scaling": sc.as_dict(), "tier": self.tier, "want_rows": want_rows}
                    for _i, sc, _k in todo]
        results = self._map(payloads)

        done = len(cells) - len(todo)
        for (i, _sc, key), raw in zip(todo, results):
            shot = Shot.from_dict(raw)
            out[i] = shot
            if shot.ok:
                self.stats["ok"] += 1
                if not want_rows:
                    self.cache.put(key, shot)
            else:
                self.stats["errors"] += 1
            self.stats["runs"] += 1
            done += 1
            if done % max(1, int(flush_every)) == 0:
                self.cache.save()
            if self.progress is not None:
                try:
                    self.progress(done, len(cells))
                except Exception:                       # noqa: BLE001
                    pass
        self.cache.save()
        return out

    def _map(self, payloads: list) -> list:
        if self.jobs > 1 and len(payloads) > 1:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(max_workers=self.jobs)
            return list(self._pool.map(_run_payload, payloads))
        return [_run_payload(p) for p in payloads]

    # --- 收尾 ---------------------------------------------------------

    def save(self) -> Path | None:
        return self.cache.save()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None
        self.cache.save()

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def describe(self) -> str:
        return (f"tier={self.tier} jobs={self.jobs} 基准弹={self.missile} "
                f"ΔV_blk={self.metrics.dv:.2f} BC_blk={self.metrics.bc:.1f}")


def default_jobs() -> int:
    """默认并发：留一个核给主进程，上限 8（与求解器交付方建议一致）。"""
    n = os.cpu_count() or 4
    return max(1, min(8, n - 1))

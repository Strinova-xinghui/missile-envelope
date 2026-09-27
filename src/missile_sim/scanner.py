# -*- coding: utf-8 -*-
"""三段式架构第二部分：**ΔV / BC 扫描器**。

职责：从用户输入拿到（初始条件、敌机设置、基准弹、网格），
改变基准弹的**推力倍率**与 **CxK**，生成一批预定工况交给模型层，
把返回结果缓存并**声明时效**。

口径（用户定案，勿改）：
  * 扫描变量 `ΔV` **始终是真空等效增速**，不考虑衰减 ⇒ `thrust_scale = ΔV / ΔV_blk`；
  * `BC` 解析反解 ⇒ `cx_scale = m_dry / (BC · SD · CxK_blk)`，`SD` 是**迎面面积**；
  * 乘数由模型层用**该型自己的 profile**现算（本层不碰参考量，避免拿错面积的旧 bug）。

    spec = ScanSpec.from_config(cfg, dv=(800, 1110, 10), bc=(2450, 3850, 25))
    with Scanner(spec, jobs=8) as sc:
        out = sc.run()
        out.records        # list[CaseRecord]
        out.manifest       # 含 inputs_digest / calculator_digest / cache / stats
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .model import grid as grid_mod
from .model import io as mio
from .model import record as mrec
from .model.cache import backend_cache
from .model.constants import (
    CALC_VERSION_PRO,
    ELF_SHA256_28,
    ROOT,
    SOLVER_DT,
    VERSION_28,
    calc_version,
)
from .model.native import NativeCase

RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"


# --------------------------------------------------------------------- 网格


def arange_inclusive(lo: float, hi: float, step: float) -> list:
    """闭区间等差序列（与 `sweep._arange_inclusive` 同口径，含端点补足）。"""
    if step <= 0:
        raise ValueError("步长必须为正")
    n = int(math.floor((hi - lo) / step + 1e-9)) + 1
    vals = [lo + step * i for i in range(n)]
    if vals[-1] < hi - 1e-9:
        vals.append(hi)
    return [round(v, 10) for v in vals]


@dataclass(frozen=True)
class Grid:
    """(ΔV, BC) 网格。`triple` = (min, max, step)。"""

    dv: tuple
    bc: tuple
    dv_step: float
    bc_step: float

    @property
    def shape(self) -> tuple:
        return (len(self.dv), len(self.bc))

    @property
    def n_cases(self) -> int:
        return len(self.dv) * len(self.bc)

    def as_dict(self) -> dict:
        return {"n_dv": len(self.dv), "n_bc": len(self.bc), "n_cases": self.n_cases,
                "dv_min": self.dv[0], "dv_max": self.dv[-1], "dv_step": self.dv_step,
                "bc_min": self.bc[0], "bc_max": self.bc[-1], "bc_step": self.bc_step}

    @classmethod
    def make(cls, dv_min, dv_max, dv_step, bc_min, bc_max, bc_step) -> "Grid":
        return cls(dv=tuple(arange_inclusive(float(dv_min), float(dv_max), float(dv_step))),
                   bc=tuple(arange_inclusive(float(bc_min), float(bc_max), float(bc_step))),
                   dv_step=float(dv_step), bc_step=float(bc_step))


# --------------------------------------------------------------------- 规格


@dataclass
class ScanSpec:
    """扫描输入：**只有这四样是用户给的**（其余是技术参数，与物理无关）。"""

    standard: str = "PL-12"
    tag: str = "WORK"
    # 初始条件 / 敌机设置（与模型层 NativeCase 的字段一一对应）
    range_m: float = 50000.0
    alt_m: float = 10000.0
    vm0: float = 300.0
    vt: float = -300.0
    target_alt_m: float | None = None
    target_maneuvers: tuple = ()
    # 网格
    grid: Grid = field(default_factory=lambda: Grid.make(800, 1110, 10, 2450, 3850, 25))
    # 技术参数（依机器而变，写进 provenance 但不影响物理口径）
    dt: float = 0.01
    duration_s: float = 150.0
    sample_period_s: float = 0.25      # 轨迹采样间隔（弹道剖面图用；不是物理步长）
    observation_mode: str = "ideal"
    jobs: int = 8
    # 档位与缓存：`standard` / `fast`（当前正式口径）各落 `results/cache/<档位>.json`；
    # 旧 `pro` 用 results/pro_cache.json（schema 5）、旧 `flash` 用 results/flash_cache.json
    # （schema 1）。**各档缓存绝不可混**——Pro 那 1824 条重跑要 44 min。
    # `model` 是注册名（`model/registry.py`）；`backend` 保留为别名（旧配置/CLI 仍在用）。
    model: str = "standard"
    cache_path: str = ""               # ⚠ 空串 = **不缓存**（旧口径）；要默认路径请显式给
    bare_runner: bool = False          # 执行器**不要引擎**（走模块级 `simulate_native`）
    run_id: str | None = None

    @property
    def backend(self) -> str:
        """兼容别名：`backend` == `model`。"""
        return self.model

    @backend.setter
    def backend(self, value):
        self.model = str(value or "standard").strip().lower()

    @property
    def calc_version(self) -> int:
        """该模型的缓存版本号（第三方模型也走注册表，所以这里必须是动态查）。"""
        from .model import registry as reg
        try:
            return int(reg.spec_of(self.model).calc_version)
        except reg.ModelNotFound:
            return calc_version(self.model)

    @classmethod
    def from_config(cls, cfg, *, dv=None, bc=None, backend: str | None = None, **over) -> "ScanSpec":
        """由 `MissileConfig` 构造；`dv`/`bc` 给 (min,max,step) 覆盖网格。

        `backend` 不给时取 `cfg.backend`（配置里的默认模型）。模型决定缓存路径：
        Pro 用 `cfg.pro_cache`（默认 results/pro_cache.json），Flash 用 `results/flash_cache.json`。
        """
        from . import config as cfg_mod

        b = str(backend or getattr(cfg, "backend", "standard") or "standard").strip().lower()
        g = cfg.sweep
        grid = cls().grid if (dv is None and bc is None) else cls().grid
        if dv is not None or bc is not None:
            grid = Grid.make(*(dv or (g.dv_min, g.dv_max, g.dv_step)),
                             *(bc or (g.bc_min, g.bc_max, g.bc_step)))
        if b == "pro":
            # 旧 Pro：缓存路径由 `cfg.pro_cache` 决定（空 = 不缓存），其余取配置
            p = cfg_mod.resolve_cache_path(cfg)
            cache_path = "" if p is None else str(p)
            dt = float(getattr(cfg, "pro_dt", 0.01))
            duration = float(getattr(cfg, "pro_duration_s", 150.0))
            obs = str(getattr(cfg, "pro_observation", "ideal"))
            jobs = int(getattr(cfg, "pro_jobs", 8))
        elif b == "flash":
            from .model import flash as flash_mod         # noqa: PLC0415  函数级：避开 import 环
            cache_path = str(flash_mod.FLASH_CACHE)
            dt = float(flash_mod.FLASH_DT)
            duration = float(flash_mod.FLASH_DURATION_S)
            obs = "ideal"                    # 旧 Flash 无"观测"档；locked 没有对应物
            jobs = 1                         # 旧 Flash 可重入且向量化，单进程最快
        else:
            # **当前正式档位**（standard / fast）与第三方模型：运行参数取配置里的 `pro_*`
            # （命名遗留，含义已是"档位共用的运行参数"）；缓存**只按档位名**落
            # `results/cache/<档位>.json` —— 绝不受 `cfg.pro_cache` 影响，否则会写进 Pro
            # 那 1824 条的资产文件（44 min）。
            from .model.cache import model_cache_path     # noqa: PLC0415
            cache_path = str(model_cache_path(b))
            dt = float(getattr(cfg, "pro_dt", SOLVER_DT))
            duration = float(getattr(cfg, "pro_duration_s", 150.0))
            obs = str(getattr(cfg, "pro_observation", "ideal"))
            jobs = int(getattr(cfg, "pro_jobs", 8))
        return cls(
            standard=cfg.standard.name, tag=cfg.standard.tag or "WORK",
            range_m=float(cfg.scenario.range), alt_m=float(cfg.scenario.alt),
            vm0=float(cfg.scenario.vm0), vt=float(cfg.scenario.vt),
            target_alt_m=(None if cfg.scenario.target_alt is None
                          else float(cfg.scenario.target_alt)),
            grid=grid,
            dt=dt, duration_s=duration, observation_mode=obs, jobs=jobs,
            model=b, cache_path=cache_path,
            **over)

    # --- 指纹 -------------------------------------------------------

    def inputs(self) -> dict:
        """**物理输入**（不含机器相关技术参数）——时效判定的比对对象。"""
        return {
            "standard": self.standard, "tag": self.tag,
            "conditions": {"range_m": self.range_m, "alt_m": self.alt_m,
                           "vm0": self.vm0, "target_alt_m": self.target_alt_m},
            "target": {"vt": self.vt, "maneuvers": [list(m) for m in self.target_maneuvers]},
            "grid": self.grid.as_dict(),
        }

    def calculator(self) -> dict:
        """**计算器身份**——版本/步长/观测模式变了同样要重算。

        Pro 额外带原生包身份（`elf_sha256`/`version`）；其他模型不碰原生包，只带版本与步长。
        **键集合按模型区分**，否则不同模型的 `calculator_digest` 会互相污染。

        ⚠ Pro 这一支的键集合**必须逐字节冻结**：它参与 `calculator_digest`，
        而 `results/pro_cache.json` 的 1824 条（约 44 min）靠它判时效。
        """
        cv = self.calc_version
        if self.model == "pro":
            return {"calc_version": CALC_VERSION_PRO, "elf_sha256": ELF_SHA256_28,
                    "version": VERSION_28, "dt": self.dt,
                    "observation_mode": self.observation_mode}
        return {"calc_version": cv, "model": self.model,
                "dt": self.dt, "observation_mode": self.observation_mode}

    def inputs_digest(self) -> str:
        return mrec.digest_of(self.inputs())

    def calculator_digest(self) -> str:
        return mrec.digest_of(self.calculator())

    def make_run_id(self) -> str:
        return self.run_id or f"{time.strftime('%Y%m%d_%H%M%S')}_{self.inputs_digest()[:8]}"

    def cases(self) -> list:
        """把网格展开成 `NativeCase` 列表（行优先：ΔV 主序）。"""
        out = []
        for dv in self.grid.dv:
            for bc in self.grid.bc:
                out.append(NativeCase(
                    missile="", version=VERSION_28,
                    range_m=self.range_m, alt_m=self.alt_m, target_alt_m=self.target_alt_m,
                    vm0=self.vm0, vt=self.vt, dv_target=float(dv), bc_target=float(bc),
                    dt=self.dt, duration_s=self.duration_s,
                    sample_period_s=self.sample_period_s,
                    observation_mode=self.observation_mode,
                    target_maneuvers=self.target_maneuvers))
        return out


# --------------------------------------------------------------------- 产物


@dataclass
class ScanOutput:
    """扫描产物：记录 + 清单 + 落盘路径 + 统计。"""

    spec: ScanSpec
    records: list
    manifest: dict
    paths: dict = field(default_factory=dict)
    grid: Grid | None = None

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]

    def t_grid(self, fill=math.nan):
        """命中时间二维网格（形状 = grid.shape；未命中填 `fill`）。"""
        import numpy as np
        vals = [(r.t_hit if (r.ok and r.hit and r.t_hit is not None) else fill)
                for r in self.records]
        return np.array(vals, dtype=float).reshape(self.grid.shape)

    def status_row(self, index: int) -> str:
        return "hit" if self.records[index].hit else (
            self.records[index].outcome.get("event") or "unknown")


# --------------------------------------------------------------------- 扫描器


class Scanner:
    """扫描器：负责网格展开、缓存命中、时效校验与落盘编排。"""

    def __init__(self, spec: ScanSpec, *, progress=None, cache=None):
        self.spec = spec
        self.progress = progress
        self._cache = cache
        self._runner = None

    # --- 运行器 -----------------------------------------------------

    def _get_runner(self):
        """按 `spec.model` 建执行器（**注册表驱动**，不再靠 `**kw` 猜参数）。

        `standard` / `fast`（当前正式档位）与第三方模型 → `EngineRunner`（求解器是标量循环，
        走多进程）；`pro`（旧原生档，保留但不再注册）→ `ProRunner`。
        """
        if self._runner is None:
            from .model import env as env_mod
            from .model import registry as reg

            spec_of = reg.spec_of(self.spec.model)
            cache = self._cache
            if cache is None:
                cp = self.spec.cache_path
                cache = backend_cache(self.spec.model, Path(cp) if cp else None,
                                      enabled=bool(cp))
            env = env_mod.build_env(spec_of, jobs=self.spec.jobs, dt=self.spec.dt)
            engine = reg.load_engine(self.spec.model, env=env)
            if self.spec.model == "pro":
                from .model.runner import ProRunner
                runner = ProRunner(jobs=self.spec.jobs, cache=cache, progress=self.progress,
                                   env=env, engine=engine, bare=self.spec.bare_runner)
            else:
                from .model.runner import EngineRunner
                runner = EngineRunner(engine, env=env, cache=cache, jobs=self.spec.jobs,
                                      progress=self.progress)
            self._runner = runner
        return self._runner

    def close(self):
        if self._runner is not None:
            self._runner.close()
            self._runner = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- 主流程 -----------------------------------------------------

    def run(self, *, write: bool = True) -> ScanOutput:
        """执行扫描。返回 `ScanOutput`；`write=True` 时落 manifest/表并归档到 runs/<id>。"""
        spec = self.spec
        model = spec.model
        runner = self._get_runner()
        # 标准弹身份（含指纹）：只用于**记录**；乘数由模型层用该型 profile 现算
        std_rec = self._standard_record()
        # 计算器身份按模型分开记：非 Pro 不碰原生包，写 pkg/elf 会误导读者
        if model == "pro":
            runtime_rec = {"kind": "pro", "pkg": str(runner.pkg), "version": VERSION_28,
                           "elf_sha256": ELF_SHA256_28}
            runtime_man = {**runtime_rec, "jobs": spec.jobs}
        else:
            rt = dict(getattr(runner, "runtime_info", None) or {})
            runtime_rec = {k: rt[k] for k in ("kind", "engine", "engine_version") if k in rt}
            runtime_rec.setdefault("kind", model)
            # 缓存号由**注册表**给（模型自报也要以注册表为准，否则缓存分区会串）
            runtime_rec["calc_version"] = spec.calc_version
            runtime_man = {**runtime_rec, "dt": spec.dt, "jobs": spec.jobs}
        n_before = len(runner.cache.data)
        cases = self._bind_missiles(spec.cases())
        t0 = time.perf_counter()
        results = runner.run_many(cases)
        wall = time.perf_counter() - t0
        records = [mrec.to_record(r, c, standard=std_rec, runtime_info=runtime_rec,
                                  model=model)
                   for r, c in zip(results, cases)]
        hits = [r for r in records if r.hit]
        stats = {
            "n_cases": len(records),
            "n_hit": len(hits),
            "hit_rate": (len(hits) / len(records)) if records else 0.0,
            "t_hit_min_s": min((r.t_hit for r in hits), default=None),
            "t_hit_max_s": max((r.t_hit for r in hits), default=None),
            "wall_s": round(wall, 2),
            "ms_per_case": round(wall * 1000.0 / max(1, len(records)), 1),
        }
        cache_info = {"entries_before": n_before, "entries_after": len(runner.cache.data),
                      "entries_added": len(runner.cache.data) - n_before,
                      "hits": runner.stats["cache"], "native_runs": runner.stats["native"],
                      "schema": spec.calc_version, "path": str(runner.cache.path)}
        manifest = mrec.make_manifest(
            run_id=spec.make_run_id(), inputs=spec.inputs(), grid=spec.grid.as_dict(),
            calculator=spec.calculator(), cache=cache_info, stats=stats,
            backend=model,
            extra={"standard": std_rec, "runtime": runtime_man,
                   "conditions": spec.inputs()["conditions"], "target": spec.inputs()["target"]})
        out = ScanOutput(spec=spec, records=records, manifest=manifest, grid=spec.grid)
        if write:
            out.paths = self._write(out)
        return out

    # --- 内部 -------------------------------------------------------

    def _standard_record(self) -> dict:
        """标准弹身份（含指纹）——写进每条记录与清单。"""
        from . import standard as standard_mod
        try:
            prof = standard_mod.resolve(self.spec.standard)
        except standard_mod.StandardPoolError:
            return {"name": self.spec.standard, "tag": self.spec.tag,
                    "profile_hash": None, "cxk": None, "loft_deg": None}
        return {"name": prof.name, "label": prof.label, "tag": prof.tag,
                "file": prof.file, "profile_hash": prof.profile_hash(),
                "cxk": prof.cxk, "dv": prof.dv, "bc": prof.bc,
                "dry_mass": prof.dry_mass, "loft_deg": prof.loft.elevation_deg}

    def _bind_missiles(self, cases: list) -> list:
        """把空 missile 字段填成该标准弹对应的原生 profile 名（含注入型）。"""
        from . import standard as standard_mod
        try:
            prof = standard_mod.resolve(self.spec.standard)
        except standard_mod.StandardPoolError as exc:
            raise ValueError(f"标准弹 {self.spec.standard!r} 不在池里：{exc}") from exc
        name = mio.native_name_of(prof.file or prof.name)
        if not mio.can_run_native(name):
            raise ValueError(
                f"原生包没有 {name!r}，注入源里也找不到它的 blkx —— 无法执行原生仿真")
        out = []
        for c in cases:
            d = asdict(c)
            d["missile"] = name
            out.append(NativeCase(**d))
        return out

    def _write(self, out: ScanOutput) -> dict:
        d = RUNS / out.run_id
        d.mkdir(parents=True, exist_ok=True)
        manifest_path = d / "manifest.json"
        cases_json = mrec.write_table(out.records, d / "cases.json")
        cases_csv = mrec.write_table(out.records, d / "cases.csv")
        manifest_path.write_text(
            json.dumps(out.manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"run_dir": str(d), "manifest": str(manifest_path),
                "cases_json": str(cases_json), "cases_csv": str(cases_csv)}


# --------------------------------------------------------------------- 时效


def latest_run_id() -> str | None:
    """最近一次扫描的 run_id（按目录名排序，名字以时间戳开头）。"""
    if not RUNS.is_dir():
        return None
    ids = sorted(p.name for p in RUNS.iterdir() if (p / "manifest.json").is_file())
    return ids[-1] if ids else None


def load_manifest(run_id: str | None = None) -> dict | None:
    rid = run_id or latest_run_id()
    if not rid:
        return None
    p = RUNS / rid / "manifest.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def check_run(run_id: str | None = None, spec: "ScanSpec | None" = None) -> dict:
    """校验某次扫描是否过期。

    给 `spec` 时比对输入与计算器；不给时只能判 schema（返回 `stale_calculator` 表示版本不符）。
    """
    man = load_manifest(run_id)
    if man is None:
        return {"stale": True, "reasons": ["no_manifest"], "run_id": run_id}
    st = mrec.check_staleness(
        man,
        current_inputs=(spec.inputs() if spec else None),
        current_calculator=(spec.calculator() if spec else None))
    st["run_id"] = man.get("run_id")
    st["stats"] = man.get("stats")
    return st

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
from .model.constants import CALC_VERSION, ELF_SHA256_28, ROOT, VERSION_28
from .model.native import NativeCase, ProRuntimeError
from .model.runner import ProRunner

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
        return cls(dv=tuple(arange_inclusive(dv_min, dv_max, dv_step)),
                   bc=tuple(arange_inclusive(bc_min, bc_max, bc_step)),
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
    cache_path: str = "results/pro_cache.json"
    run_id: str | None = None

    @classmethod
    def from_config(cls, cfg, *, dv=None, bc=None, **over) -> "ScanSpec":
        """由 `MissileConfig` 构造；`dv`/`bc` 给 (min,max,step) 覆盖网格。"""
        g = cfg.sweep
        grid = cls().grid if (dv is None and bc is None) else cls().grid
        if dv is not None or bc is not None:
            grid = Grid.make(*(dv or (g.dv_min, g.dv_max, g.dv_step)),
                             *(bc or (g.bc_min, g.bc_max, g.bc_step)))
        return cls(
            standard=cfg.standard.name, tag=cfg.standard.tag or "WORK",
            range_m=float(cfg.scenario.range), alt_m=float(cfg.scenario.alt),
            vm0=float(cfg.scenario.vm0), vt=float(cfg.scenario.vt),
            target_alt_m=(None if cfg.scenario.target_alt is None
                          else float(cfg.scenario.target_alt)),
            grid=grid,
            dt=float(getattr(cfg, "pro_dt", 0.01)),
            duration_s=float(getattr(cfg, "pro_duration_s", 150.0)),
            observation_mode=str(getattr(cfg, "pro_observation", "ideal")),
            jobs=int(getattr(cfg, "pro_jobs", 8)),
            cache_path=str(getattr(cfg, "pro_cache", "results/pro_cache.json") or ""),
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
        """**计算器身份**——版本/步长/观测模式变了同样要重算。"""
        return {"calc_version": CALC_VERSION, "elf_sha256": ELF_SHA256_28,
                "version": VERSION_28, "dt": self.dt, "observation_mode": self.observation_mode}

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

    def _get_runner(self) -> ProRunner:
        if self._runner is None:
            from .model.cache import ProCache
            cache = self._cache
            if cache is None:
                cp = self.spec.cache_path
                cache = ProCache(Path(cp) if cp else None, enabled=bool(cp))
            self._runner = ProRunner(jobs=self.spec.jobs, cache=cache, progress=self.progress)
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
        runner = self._get_runner()
        # 标准弹身份（含指纹）：只用于**记录**；乘数由模型层用该型 profile 现算
        std_rec = self._standard_record()
        runtime_rec = {"pkg": str(runner.pkg), "version": VERSION_28,
                       "elf_sha256": ELF_SHA256_28}
        n_before = len(runner.cache.data)
        cases = self._bind_missiles(spec.cases())
        t0 = time.perf_counter()
        results = runner.run_many(cases)
        wall = time.perf_counter() - t0
        records = [mrec.to_record(r, c, standard=std_rec, runtime_info=runtime_rec)
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
                      "schema": CALC_VERSION, "path": str(runner.cache.path)}
        manifest = mrec.make_manifest(
            run_id=spec.make_run_id(), inputs=spec.inputs(), grid=spec.grid.as_dict(),
            calculator=spec.calculator(), cache=cache_info, stats=stats,
            extra={"standard": std_rec,
                   "runtime": {"pkg": str(runner.pkg), "version": VERSION_28,
                               "elf_sha256": ELF_SHA256_28, "jobs": spec.jobs},
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

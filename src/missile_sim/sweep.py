"""参数扫描（ΔV × 弹道系数 BC）与等命中时间线提取。

流程：
  1. 生成网格：ΔV ∈ [dv_min, dv_max] 步长 dv_step；BC ∈ [bc_min, bc_max] 步长 bc_step；
  2. 由 BC 反解 CxK = m_bound / (BC * S_ref)，交给向量化批量仿真；
  3. 输出 cases_*.csv（逐工况，含状态码/命中时间/终端量）；
  4. 在 t_hit(ΔV, BC) 网格上做等值线提取 → isolines_*.csv（每条等时线的折线顶点）；
  5. 校验：任一 ΔV 列内 t_hit 必须随 BC 单调（这是"等命中时间线"成立的前提）。

未命中工况 t_hit = NaN，等值线自动断开，不会被插值掩盖。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .config import (
    MissileConfig,
    ballistic_coefficient,
    config_to_dict,
    cxk_for_bc,
    delta_v_equiv,
    effective_ve_equiv,
    isp_equiv,
    mass_ratio_for_dv,
    s_ref,
)
from .decide import (
    STATUS_LABELS,
    STATUS_NAMES,
    ST_HIT,
    ST_MISS_OVERSHOOT,
    ST_MISS_RECEDE,
    ST_NO_HIT_SLOWDOWN,
    ST_NO_HIT_TIMEOUT,
)
from . import provenance as prov_mod
from .sim import BatchResult, simulate_batch

RESULT_DIR = Path(__file__).resolve().parents[2] / "results"
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SweepGrid:
    dv: np.ndarray  # (n_dv,)
    bc: np.ndarray  # (n_bc,)
    dv_step: float
    bc_step: float

    @property
    def shape(self):
        return (len(self.dv), len(self.bc))


def build_grid(cfg: MissileConfig, dv_step: float | None = None, bc_step: float | None = None) -> SweepGrid:
    s = cfg.sweep
    dvs = _arange_inclusive(s.dv_min, s.dv_max, s.dv_step if dv_step is None else dv_step)
    bcs = _arange_inclusive(s.bc_min, s.bc_max, s.bc_step if bc_step is None else bc_step)
    return SweepGrid(dv=dvs, bc=bcs, dv_step=s.dv_step if dv_step is None else dv_step,
                     bc_step=s.bc_step if bc_step is None else bc_step)


def _arange_inclusive(lo: float, hi: float, step: float) -> np.ndarray:
    if step <= 0.0:
        raise ValueError("步长必须为正")
    n = int(np.floor((hi - lo) / step + 1e-9)) + 1
    vals = lo + step * np.arange(n)
    if vals[-1] < hi - 1e-9:
        vals = np.append(vals, hi)
    return np.round(vals, 10)


def grid_cases(grid: SweepGrid, cfg: MissileConfig, theta_loft_deg: float | None = None):
    """构造批量仿真的 (dv, cxk) 二维网格（形状 = (n_dv, n_bc)）。"""
    dv2d, bc2d = np.meshgrid(grid.dv, grid.bc, indexing="ij")
    cxk2d = cxk_for_bc(bc2d, cfg)
    return dv2d, cxk2d, bc2d


def run_sweep(
    cfg: MissileConfig,
    grid: SweepGrid | None = None,
    *,
    theta_loft_deg: float | None = None,
    mass=None,
    progress=None,
    jobs: int | None = None,
) -> tuple[BatchResult, SweepGrid, np.ndarray]:
    """执行扫描，返回 (batch_result, grid, t_hit 二维网格)。

    按 `cfg.backend` 分派：`standard` / `fast`（默认，wt-missile 两档）与第三方模型走统一的
    引擎路径（进程池 + 按档位分区的缓存）；旧 `pro` 走原生执行器；旧 `flash` 走本仓库的
    向量化公式引擎（保留可回退）。
    """
    grid = build_grid(cfg) if grid is None else grid
    name = str(getattr(cfg, "backend", "standard")).strip().lower()
    if name == "flash":
        # 旧 Flash（本仓库公式引擎，向量化批量）：保留可回退，但不再是默认路径
        dv2d, cxk2d, _ = grid_cases(grid, cfg, theta_loft_deg)
        res = simulate_batch(
            cfg,
            dv2d.ravel(),
            cxk2d.ravel(),
            theta_loft_deg=theta_loft_deg,
            target_alt=(cfg.scenario.target_alt if cfg.scenario.target_alt is not None else cfg.scenario.alt),
            mass=mass,
            progress=progress,
        )
    else:
        # standard / fast（当前档位）、旧 pro、第三方模型：统一的引擎网格路径
        res = run_sweep_engine(cfg, grid, model=name, progress=progress, jobs=jobs)
    t_grid = res.t_hit.reshape(grid.shape)
    return res, grid, t_grid


# --------------------------------------------------------------------------- Pro 后端（原生）
#
# 口径（用户 2026-09-25 定案）：**Pro 是唯一正式后端**，Flash 保留为可迭代的近似档。
#   * 扫描变量仍是 (ΔV, BC)；
#   * ΔV 是**真空等效增速**，⇒ 推力乘数解析给出 `s = ΔV / ΔV_blk`（无迭代）；
#   * BC 反解 CxK（`BC = m_dry/(CxK·S_ref)`）⇒ CxK 乘数 `= m_dry/(BC·S_ref·CxK_blk)`；
#   * 基准弹默认 PL-12，可在 11 弹池里选（`cfg.standard.name`）。
# 每个格点 = 一次原生全程积分；结果落 `results/pro_cache.json`，重复跑直接读缓存。


def _pro_status(r) -> int:
    """把原生终端事件映射到本仓库的 ST_* 口径。

    注意区分三种"没命中"：原生**执行失败**（数值异常/包问题）、**寿命到**、**真的飞越脱靶**。
    以前两者都塞进 ST_MISS_OVERSHOOT 会让"脱靶"这种物理结论被污染。
    """
    if not r.ok:
        err = (r.error or "")
        if "Non-finite" in err or "did not return" in err or "did not reach" in err:
            return ST_NO_HIT_SLOWDOWN          # 原生数值发散/未返回
        if "dt=" in err or "超出原生合法范围" in err:
            return ST_NO_HIT_SLOWDOWN          # 参数非法，未能起算
        return ST_MISS_RECEDE                  # 包/版本等运行环境问题
    if r.hit:
        return ST_HIT
    ev = (r.event or "").lower()
    # wt-missile 2.59.0.28 **只报这五个事件**（源码核实：`contact`/`proximity_fuse` 在 406/409 行、
    # `ground` 411/413、`time_limit`/`lifetime` 2738 行）：
    #   contact / proximity_fuse → 命中（上面已返回）· ground → 撞地
    #   lifetime → 本弹 timeLife 到 · time_limit → 配置的 duration_s 用完
    # ⚠ `time_limit` 现在落在 OVERSHOOT，是为**旧 Pro** 定的口径（`tests/test_pro.py:256` 钉住）。
    # 新档位下 duration_s=150 s > 各型寿命 80~120 s，所以实际只会出 `lifetime`；真要出现
    # `time_limit`，"超时"比"飞越脱靶"更贴切 —— 这属于口径决策，留给用户拍板，别偷偷改。
    if ev == "ground":
        return ST_NO_HIT_SLOWDOWN
    if ev == "lifetime":
        return ST_NO_HIT_TIMEOUT
    return ST_MISS_OVERSHOOT


def run_sweep_engine(
    cfg: MissileConfig,
    grid: SweepGrid,
    *,
    model: str | None = None,
    progress=None,
    jobs: int | None = None,
    missile: str | None = None,
    cache=None,
) -> BatchResult:
    """用**注册表里的任意档位**跑整张 (ΔV, BC) 网格，产出与旧 Flash 同形的 `BatchResult`。

    `model` 缺省取 `cfg.backend`（standard / fast）；执行器是通用的 `EngineRunner`
    （进程池 + 缓存），所以第三方模型也能走这条路。旧 `pro` 由 `run_sweep_pro` 保留。
    """
    from .model import io as mio
    from .model import registry as reg
    from .model.cache import backend_cache
    from .model.env import build_env
    from .model.grid import run_grid
    from .model.runner import EngineRunner

    prof = cfg.profile
    if prof is None:
        raise ValueError("必须先解析标准弹（cfg.standard.name 不能为空）——"
                         "它决定几何/质量/推力/引信，是 ΔV 与 BC 的锚")
    name = str(model or getattr(cfg, "backend", "standard")).strip().lower()
    jobs = int(jobs if jobs is not None else getattr(cfg, "pro_jobs", 8))
    native = missile or _native_name(prof.file or f"{prof.name}")
    if not mio.can_run_native(native):
        raise ValueError(f"信源里找不到 {native!r} 的 blkx —— 无法执行仿真")

    spec = reg.spec_of(name)
    env = build_env(spec, cfg, jobs=jobs)
    engine = reg.load_engine(name, env=env)
    if cache is None:
        # 缓存**只按档位名**落 results/cache/<档位>.json —— 不受 cfg.pro_cache 影响，
        # 否则会写进 Pro 那 1824 条的资产文件（44 min）。
        cache = backend_cache(name, None, enabled=True)
    # 工况构造的唯一入口（含步长/时长/观测模式），避免各处各写一遍
    base = mio.build_case(cfg, missile=native)
    dt = float(base.dt)

    with EngineRunner(engine, env=env, cache=cache, jobs=jobs, progress=progress) as runner:
        outcome = run_grid(runner, base, grid.dv, grid.bc, progress=progress)
        runtime_info = {
            **dict(getattr(runner, "runtime_info", {}) or {}),
            "injected": [native], "dt": dt, "observation_mode": base.observation_mode,
            "duration_s": base.duration_s, "jobs": jobs,
            "n_native_runs": runner.stats.get("native", 0),
            "n_cache_hits": runner.stats.get("cache", 0),
        }

    n = len(outcome.solutions)
    arr = {k: np.full(n, np.nan) for k in (
        "t_hit", "t_end", "miss_distance", "max_alt", "v_impact",
        "terminal_gamma_error_deg", "min_range", "min_range_linear", "t_loft_end",
        "isp_equiv", "mass_ratio", "dv_measured")}
    status = np.full(n, ST_MISS_RECEDE, dtype=np.int64)
    for i, sol in enumerate(outcome.solutions):
        r = sol.result
        if r is None:
            continue
        status[i] = _pro_status(r)
        arr["t_hit"][i] = r.t_hit if r.hit else np.nan
        arr["t_end"][i] = r.t_end
        arr["miss_distance"][i] = r.miss_distance_m
        arr["max_alt"][i] = r.max_alt_m
        arr["v_impact"][i] = r.v_impact
        arr["min_range"][i] = r.miss_distance_m
        arr["dv_measured"][i] = r.dv_measured
        arr["isp_equiv"][i] = isp_equiv(sol.dv_target)
        arr["mass_ratio"][i] = mass_ratio_for_dv(sol.dv_target, effective_ve_equiv(cfg))

    cxk_arr = np.array([cxk_for_bc(bc, cfg) for bc in outcome.bc], dtype=float)
    dv_arr = np.array(outcome.dv, dtype=float)
    res = BatchResult(
        dv_total=np.repeat(dv_arr, len(outcome.bc)),
        cxk=np.tile(cxk_arr, len(dv_arr)),
        bc=np.tile(np.array(outcome.bc, dtype=float), len(dv_arr)),
        theta_loft_deg=float(cfg.sim.theta_loft_deg),
        vm0=base.vm0, vt=base.vt, alt=base.alt_m, target_alt=base.target_alt,
        range0=base.range_m,
        status=status,
        t_hit=arr["t_hit"], t_end=arr["t_end"], miss_distance=arr["miss_distance"],
        max_alt=arr["max_alt"], v_impact=arr["v_impact"],
        terminal_gamma_error_deg=arr["terminal_gamma_error_deg"],
        min_range=arr["min_range"], min_range_linear=arr["min_range_linear"],
        t_loft_end=arr["t_loft_end"],
        isp_equiv=arr["isp_equiv"], mass_ratio=arr["mass_ratio"],
    )
    res.pro = {                                       # 额外诊断（不进 CSV，进汇总 JSON）
        "outcome": outcome,
        "runtime": runtime_info,
        "dv_measured": arr["dv_measured"],
        "loss_pct": (1.0 - arr["dv_measured"] / res.dv_total) * 100.0,
        "n_converged": outcome.stats.get("n_converged"),
        # 自描述：与 provenance(cfg) 的 backend/standard 一起构成完整出处。
        # 旧 Pro 有 `pkg`/`elf_sha256`；wt-missile 两档给的是 `solver`/`solver_sha256`/`backend`，
        # 所以一律用 `get` —— 缺哪个键就不写哪个，**不编造**。
        "engine": name,
        "engine_kind": runtime_info.get("kind"),
        "engine_version": runtime_info.get("engine_version"),
        "elf_sha256": runtime_info.get("elf_sha256"),
        "pkg": runtime_info.get("pkg"),
        "solver": runtime_info.get("solver"),
        "solver_sha256": runtime_info.get("solver_sha256"),
        "solver_model": runtime_info.get("solver_model"),
        "backend": runtime_info.get("backend"),
        "version": runtime_info.get("version"),
        "injected": list(runtime_info.get("injected") or ()),
        "dt": dt,
        "observation_mode": base.observation_mode,
        "n_native_runs": runtime_info.get("n_native_runs", 0),
        "n_cache_hits": runtime_info.get("n_cache_hits", 0),
    }
    return res


def run_sweep_pro(cfg: MissileConfig, grid: SweepGrid, **kw) -> BatchResult:
    """旧 Pro 后端（保留名）：转调 `run_sweep_engine(model="pro")`。"""
    kw.pop("model", None)
    return run_sweep_engine(cfg, grid, model="pro", **kw)


def _native_name(file_or_name: str) -> str:
    """标准弹 → 原生 profile 名（= blkx 文件名去后缀；池里 `file` 字段就是它）。"""
    s = str(file_or_name)
    for suffix in (".blkx", ".blk"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


# --------------------------------------------------------------------------- 校验


def monotonic_report(t_grid: np.ndarray, grid: SweepGrid):
    """检查每个 ΔV 列内 t_hit 随 BC 单调性；返回违规明细列表。

    物理预期：同一 ΔV 下 BC 越大（阻力越小）→ 越早命中/越能命中。容许浮点抖动。
    """
    tol = 1e-6
    issues = []
    for i in range(t_grid.shape[0]):
        col = t_grid[i, :]
        for j in range(t_grid.shape[1] - 1):
            a, b = col[j], col[j + 1]
            if np.isnan(a) and np.isnan(b):
                continue
            if np.isnan(a) and not np.isnan(b):
                issues.append((grid.dv[i], grid.bc[j], grid.bc[j + 1], "NaN→命中", a, b))
            elif not np.isnan(a) and not np.isnan(b) and b > a + tol:
                issues.append((grid.dv[i], grid.bc[j], grid.bc[j + 1], "Δt 增大", a, b))
    return issues


# --------------------------------------------------------------------------- 输出


def write_cases_csv(res: BatchResult, path: Path) -> Path:
    """逐工况 CSV：ΔV / BC / CxK / 等效比冲 / 命中时间 / 状态 / 终端量。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "dv_total", "bc", "cxk", "isp_equiv_s", "mass_ratio_nominal",
        "status", "status_name", "t_hit_s", "t_end_s", "miss_distance_m",
        "min_range_m", "min_range_linear_m", "max_alt_m", "v_impact_ms",
        "terminal_gamma_err_deg", "t_loft_end_s",
    ]
    status_name = np.array([STATUS_NAMES[int(s)] for s in res.status], dtype=object)
    data = {
        "dv_total": res.dv_total,
        "bc": res.bc,
        "cxk": res.cxk,
        "isp_equiv_s": res.isp_equiv,
        "mass_ratio_nominal": res.mass_ratio,
        "status": res.status,
        "status_name": status_name,
        "t_hit_s": res.t_hit,
        "t_end_s": res.t_end,
        "miss_distance_m": res.miss_distance,
        "min_range_m": res.min_range,
        "min_range_linear_m": res.min_range_linear,
        "max_alt_m": res.max_alt,
        "v_impact_ms": res.v_impact,
        "terminal_gamma_err_deg": res.terminal_gamma_error_deg,
        "t_loft_end_s": res.t_loft_end,
    }
    header = ",".join(cols)
    lines = [header]
    for k in range(len(res.dv_total)):
        row = []
        for c in cols:
            v = data[c][k]
            if isinstance(v, str):
                row.append(v)
            elif c in ("status",):
                row.append(str(int(v)))
            elif np.isnan(v):
                row.append("nan")
            else:
                row.append(f"{float(v):.6g}")
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _iso_levels(finite: np.ndarray, step: float, extra_levels=None):
    """给定有限值集合与步长，生成等值线层级（含端点兜底，避免常量场退化）。"""
    lo = float(np.floor(finite.min() / step) * step)
    hi = float(np.ceil(finite.max() / step) * step)
    levels = list(np.arange(max(step, lo), hi + step * 0.5, step))
    if extra_levels is not None:
        levels.extend(float(x) for x in np.atleast_1d(extra_levels))
    if not levels:
        levels = [float(finite.mean())]
    vmin, vmax = float(finite.min()), float(finite.max())
    return sorted(lv for lv in levels if vmin - 1e-9 <= lv <= vmax + 1e-9)


def extract_isolines(
    t_grid: np.ndarray,
    grid: SweepGrid,
    levels=None,
    step: float = 2.0,
) -> list[dict]:
    """在 t_hit(BC, ΔV) 网格上提取等命中时间线（marching squares，NaN 自动断开）。

    返回 [{level, points:[(bc, dv, t), ...], closed}, ...]
    """
    finite = t_grid[np.isfinite(t_grid)]
    if finite.size == 0:
        return []
    if levels is None:
        levels = _iso_levels(finite, step)
    vmin, vmax = float(finite.min()), float(finite.max())
    levels = np.asarray([lv for lv in np.atleast_1d(levels) if vmin - 1e-9 <= lv <= vmax + 1e-9])
    if levels.size == 0:
        return []

    # contour 需要 X 形状 (n_bc,)、Y 形状 (n_dv,)、Z 形状 (n_dv, n_bc)
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots()
    try:
        cs = ax.contour(grid.bc, grid.dv, t_grid, levels=levels)
        segs = cs.allsegs
    finally:
        plt.close(fig)

    out = []
    for lv, group in zip(levels, segs):
        for seg in group:
            if seg is None or len(seg) < 2:
                continue
            pts = [(float(p[0]), float(p[1]), float(lv)) for p in seg]
            closed = bool(np.allclose(seg[0], seg[-1]))
            out.append({"level": float(lv), "points": pts, "closed": closed})
    return out


def write_isolines_csv(lines: list[dict], path: Path, cfg: MissileConfig) -> Path:
    """等时线 CSV（含由 BC 反解的 CxK），便于外部复核。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["t_hit_level_s,bc,cxk,dv_total,segment_index"]
    for idx, seg in enumerate(lines):
        for bc, dv, lv in seg["points"]:
            rows.append(f"{lv:.6g},{bc:.6g},{cxk_for_bc(bc, cfg):.6g},{dv:.6g},{idx}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _prov_extra(res: BatchResult) -> dict:
    """从 Pro 结果里取出原生身份/runtime，补进 provenance（Flash 结果返回空）。"""
    pro = getattr(res, "pro", None)
    if not pro:
        return {}
    rt = dict(pro.get("runtime") or {})
    # 扁平镜像（便于按固定路径取字段），完整分组也保留在 pro 里
    for k in ("elf_sha256", "pkg", "version", "dt", "observation_mode",
              "n_native_runs", "n_cache_hits", "injected"):
        if k in pro:
            rt[k] = pro[k]
    return {"pro": rt, "dt_pro_s": rt.get("dt")}


def summary_dict(
    cfg: MissileConfig,
    res: BatchResult,
    grid: SweepGrid,
    t_grid: np.ndarray,
    lines: list[dict],
    *,
    extra: dict | None = None,
) -> dict:
    hit = res.status == ST_HIT
    per_status = {STATUS_NAMES[int(c)]: int(np.sum(res.status == c)) for c in np.unique(res.status)}
    out = {
        # 产物自描述（与 workflow / 交叉图共用同一实现，见 provenance.py）
        "provenance": prov_mod.provenance(cfg, extra=_prov_extra(res)),
        "config": config_to_dict(cfg),
        "derived": {
            "s_ref_m2": s_ref(cfg),
            "cxk_baseline": cfg.drag.cxk,
            "bc_baseline": ballistic_coefficient(cfg.drag.cxk, cfg),
            "dv_baseline_rocket_eq": delta_v_equiv(cfg),
            "isp_equiv_baseline_s": isp_equiv(delta_v_equiv(cfg)),
        },
        "scenario": {
            "vm0": res.vm0,
            "vt": res.vt,
            "alt": res.alt,
            "target_alt": res.target_alt,
            "range": res.range0,
            "theta_loft_deg": res.theta_loft_deg,
        },
        "grid": {
            "n_dv": int(len(grid.dv)),
            "n_bc": int(len(grid.bc)),
            "n_cases": int(res.dv_total.size),
            "dv": [float(x) for x in grid.dv],
            "bc": [float(x) for x in grid.bc],
            "dv_step": grid.dv_step,
            "bc_step": grid.bc_step,
        },
        "results": {
            "n_hit": int(np.sum(hit)),
            "hit_rate": float(np.mean(hit)),
            "status_counts": per_status,
            "t_hit_min_s": _nanmin(res.t_hit),
            "t_hit_max_s": _nanmax(res.t_hit),
            "isolines": sorted({seg["level"] for seg in lines}),
            "n_isolines": len(lines),
        },
    }
    if extra:
        out.update(extra)
    return out


def _nanmin(a):
    a = a[np.isfinite(a)]
    return float(a.min()) if a.size else None


def _nanmax(a):
    a = a[np.isfinite(a)]
    return float(a.max()) if a.size else None


def write_summary(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

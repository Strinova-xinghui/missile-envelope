# -*- coding: utf-8 -*-
"""三段式流水线的统一入口（四段可分别单独跑，每段只依赖上一段的落盘产物）。

    python scripts\\pipeline.py stat  [--tag WORK] [--out results/missile_standards.json]
    python scripts\\pipeline.py model --standard PL-12 --dv 932.6 --bc 3078.1
    python scripts\\pipeline.py scan  --standard PL-12 --dv-min 800 --dv-max 1110 --dv-step 10 \\
                                     --bc-min 2450 --bc-max 3850 --bc-step 25 --jobs 8
    python scripts\\pipeline.py plot  [--run-id <id>] [--iso-step 1] [--tag crossplot]

对应关系：
    stat  → 第一部分·第一层  输入层（blk 统计 → 弹池）        `model.io`
    model → 第一部分·第二/三层 计算 + 结构化输出              `model.native/runner/record`
    scan  → 第二部分           ΔV/BC 扫描器（改推力倍率与 CxK）`scanner`
    plot  → 第三部分           绘图（aam_fit 版式 + 等时线）   `crossplot`

机器相关参数（`--jobs/--pro-dt/--observation`）只影响速度与观测口径，不参与物理口径。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from missile_sim import crossplot as cp  # noqa: E402
from missile_sim import scanner as sc  # noqa: E402
from missile_sim import standard  # noqa: E402
from missile_sim.config import apply_standard, load_config  # noqa: E402
from missile_sim.model import CALC_VERSION, ProRuntimeError  # noqa: E402
from missile_sim.model import io as mio  # noqa: E402
from missile_sim.model import record as mrec  # noqa: E402
from missile_sim.model.native import simulate_native  # noqa: E402

FIG_DIR = ROOT / "figures"
RES_DIR = ROOT / "results"


# ============================================================ stat


def cmd_stat(args) -> int:
    """第一层：从 blk 统计参数，产出弹池快照（"采购原材料"）。"""
    out = Path(args.out) if args.out else RES_DIR / "missile_standards.json"
    if args.rebuild_pool or not out.exists():
        import subprocess
        cmd = [sys.executable, str(ROOT / "scripts" / "build_standard_pool.py"),
               "--tag", args.tag, "--out", str(out)]
        print(f"[stat] 重建弹池：{' '.join(cmd[1:])}")
        rc = subprocess.call(cmd)
        if rc != 0:
            return rc
    doc = json.loads(out.read_text(encoding="utf-8"))
    print(f"[stat] 弹池 {out}（tag={doc.get('tag')}，{len(doc['missiles'])} 型，"
          f"默认 {doc.get('default')}）")
    print(f"{'短名':<9}{'ΔV':>9}{'BC':>9}{'干重':>8}{'口径mm':>8}{'迎面积':>9}{'升面积':>9}")
    for name in doc["missiles"]:
        try:
            st = mio.blk_stats(tag=args.tag, native_name=name)
            area = (f"{st['sd_m2']:9.5f}{st['sl_m2']:9.5f}")
        except Exception:                          # noqa: BLE001  没装 datamine 时退化为池值
            area = f"{'—':>9}{'—':>9}"
        prof = standard.resolve(name)
        print(f"{name:<9}{prof.dv:9.2f}{prof.bc:9.1f}{prof.dry_mass:8.1f}"
              f"{prof.caliber_m * 1000:8.1f}{area}")
    return 0


# ============================================================ model


def cmd_model(args) -> int:
    """第一部分的第二/三层：跑一个工况并打印结构化记录。"""
    cfg = load_config(args.config)
    cfg.standard.name = args.standard
    apply_standard(cfg)
    if args.missile:
        name = args.missile
    else:
        name = mio.native_name_of(cfg.profile.file or cfg.profile.name)
    dv = args.dv if args.dv is not None else cfg.profile.dv
    bc = args.bc if args.bc is not None else cfg.profile.bc
    for k, v in (("range", args.range), ("alt", args.alt), ("vm0", args.vm0),
                 ("vt", args.vt), ("dt", args.pro_dt)):
        if v is not None:
            setattr(cfg.scenario if k in ("range", "alt", "vm0", "vt") else cfg,
                    {"range": "range", "alt": "alt", "vm0": "vm0", "vt": "vt",
                     "dt": "pro_dt"}[k], v)
    if args.duration is not None:
        cfg.pro_duration_s = args.duration
    if args.observation is not None:
        cfg.pro_observation = args.observation
    # 单工况**要**轨迹（弹道剖面图用；扫描网格里不要，否则产物会到几十 MB）
    case = mio.build_case(cfg, missile=name, dv=dv, bc=bc, save_trajectory=True)
    print(f"[model] {case.missile} · ΔV={case.dv_target:g} · BC={case.bc_target:g} · "
          f"R0={case.range_m:g} m · alt={case.alt_m:g} m · dt={case.dt:g} s")
    t0 = time.perf_counter()
    res = simulate_native(case, args.pkg)
    wall = time.perf_counter() - t0
    std_rec = {"name": cfg.profile.name, "tag": cfg.profile.tag,
               "profile_hash": cfg.profile.profile_hash(), "cxk": cfg.profile.cxk,
               "loft_deg": cfg.profile.loft.elevation_deg}
    from missile_sim.model.native import resolve_pkg
    from missile_sim.model.constants import ELF_SHA256_28
    rec = mrec.to_record(res, case, standard=std_rec,
                         runtime_info={"pkg": str(resolve_pkg(args.pkg)),
                                       "version": mio.VERSION_28,
                                       "elf_sha256": ELF_SHA256_28})
    print(f"[model] {wall:.1f} s · ok={rec.ok} hit={rec.hit} "
          f"event={rec.outcome['event']} t_hit={rec.t_hit} v_impact={rec.v_impact}")
    print(f"        乘数 thrust×{rec.scales['thrust_scale']:.4f} / CxK×{rec.scales['cx_scale']:.4f}"
          f"（CxK_used={rec.scales['cxk_used']}）")
    print(f"        ΔV_blk={rec.inputs['dv_blk']:.2f} BC_blk={rec.inputs['bc_blk']:.1f} "
          f"实测ΔV={rec.engine['dv_measured']:.1f}（损失 {rec.engine['loss_pct']:.2f}%）")
    print(f"        轨迹采样 {len(rec.samples)} 点 · 资源 {rec.model['resource']} · "
          f"步长 {rec.model['dt_s']:g} s · 观测 {rec.model['observation_mode']}")
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"        记录 → {p}")
    return 0 if rec.ok else 1


# ============================================================ scan


def _scan_spec(args) -> "sc.ScanSpec":
    cfg = load_config(args.config)
    cfg.standard.name = args.standard
    if args.tag:
        cfg.standard.tag = args.tag
    apply_standard(cfg)
    dv = (args.dv_min, args.dv_max, args.dv_step) if args.dv_min is not None else None
    bc = (args.bc_min, args.bc_max, args.bc_step) if args.bc_min is not None else None
    spec = sc.ScanSpec.from_config(cfg, dv=dv, bc=bc)
    for name, val in (("jobs", args.jobs), ("dt", args.pro_dt),
                      ("duration_s", args.duration), ("observation_mode", args.observation),
                      ("cache_path", args.cache if args.cache is not None else None),
                      ("range_m", args.range), ("alt_m", args.alt),
                      ("vm0", args.vm0), ("vt", args.vt),
                      ("target_alt_m", args.target_alt)):
        if val is not None:
            setattr(spec, name, val)
    if args.run_id:
        spec.run_id = args.run_id
    return spec


def cmd_scan(args) -> int:
    """第二部分：ΔV/BC 扫描器。"""
    spec = _scan_spec(args)
    st = sc.check_run(spec=spec)
    g = spec.grid
    print(f"[scan] 基准弹 {spec.standard}@{spec.tag} · 网格 {g.shape[0]}×{g.shape[1]}"
          f" = {g.n_cases} 工况")
    print(f"       ΔV {g.dv[0]:.0f}~{g.dv[-1]:.0f}/{g.dv_step:g} · "
          f"BC {g.bc[0]:.0f}~{g.bc[-1]:.0f}/{g.bc_step:g}")
    print(f"       工况 vm0={spec.vm0:g} vt={spec.vt:g} alt={spec.alt_m:g} "
          f"R0={spec.range_m:g} · dt={spec.dt:g} s · 观测 {spec.observation_mode} · "
          f"并发 {spec.jobs}")
    print(f"       inputs_digest={spec.inputs_digest()} "
          f"calculator_digest={spec.calculator_digest()}（CALC_VERSION={CALC_VERSION}）")
    if spec.cache_path:
        print(f"       成本参考：{g.n_cases} 工况 8 并发约 "
              f"{g.n_cases / 0.45 / 60:.0f} min（单工况 ~1.4 s）；缓存命中后秒级")
    spec.cache_path = "" if args.no_cache else spec.cache_path

    def progress(done, total, _active=0):
        print(f"    原生进度 {done}/{total}", end="\r", flush=True)

    t0 = time.perf_counter()
    with sc.Scanner(spec, progress=progress) as s:
        out = s.run(write=not args.no_write)
    wall = time.perf_counter() - t0
    print(" " * 40, end="\r")
    print(f"[scan] 完成 {wall:.1f} s · {out.manifest['stats']}")
    print(f"       缓存 {out.manifest['cache']['hits']} 命中 / "
          f"{out.manifest['cache']['native_runs']} 次原生运行（新增 "
          f"{out.manifest['cache']['entries_added']} 条，schema={CALC_VERSION}）")
    if out.paths:
        for k, v in out.paths.items():
            print(f"       {k:<12} {v}")
    print(f"       run_id = {out.run_id}（用 plot --run-id 出图；"
          f"check：{sc.check_run(out.run_id, spec)}）")
    return 0


# ============================================================ plot


def _load_points(args) -> list:
    """弹点：优先用扫描产物里的逐弹结果，否则回落到权威 `missile_points.json`。"""
    src = Path(args.points) if args.points else RES_DIR / "missile_points.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    rows = doc["missiles"] if isinstance(doc, dict) and "missiles" in doc else doc
    picks = {p.strip() for p in args.only.split(",")} if args.only else None
    pts = []
    for r in rows:
        label = r.get("label") or r.get("name")
        if picks and label not in picks:
            continue
        pts.append(cp.MissilePoint(label=label, dv=float(r["dv"]), bc=float(r["bc"]),
                                   name=r.get("name", ""), t_hit=r.get("t_hit"),
                                   hit=r.get("hit")))
    return pts


def cmd_plot(args) -> int:
    """第三部分：绘图（aam_fit 版式 + 等时线）。"""
    run_id = args.run_id or sc.latest_run_id()
    man = sc.load_manifest(run_id)
    if man is None:
        print(f"[plot] 找不到扫描产物（run_id={run_id}）；先跑 "
              f"`pipeline.py scan`", file=sys.stderr)
        return 2
    st = sc.check_run(run_id)
    if st["stale"] and not args.allow_stale:
        print(f"[plot] 产物已过期 {st['reasons']}（run_id={run_id}）；"
              f"请重跑 scan，或加 --allow-stale 强出图", file=sys.stderr)
        return 2
    recs = mrec.read_table(sc.RUNS / run_id / "cases.json")
    g = man["grid"]
    dv = np.array(sc.arange_inclusive(g["dv_min"], g["dv_max"], g["dv_step"]), dtype=float)
    bc = np.array(sc.arange_inclusive(g["bc_min"], g["bc_max"], g["bc_step"]), dtype=float)
    t_grid = np.full((len(dv), len(bc)), np.nan)
    for r in recs:
        i = int(np.argmin(np.abs(dv - float(r.inputs["dv"]))))
        j = int(np.argmin(np.abs(bc - float(r.inputs["bc"]))))
        t_grid[i, j] = r.t_hit if (r.ok and r.hit and r.t_hit is not None) else np.nan
    iso = cp.IsoGrid(dv=dv, bc=bc, t_grid=t_grid)

    pts = _load_points(args)
    cond = man.get("conditions") or {}
    std = man.get("standard") or {}
    sub = (f"{cond.get('range_m', 0) / 1000:.0f} km 迎头"
           f"（{cond.get('vm0', 0):g} / {man.get('target', {}).get('vt', 0):g} m/s）· "
           f"高度 {cond.get('alt_m', 0) / 1000:.1f} km · 基准弹 {std.get('name')}")
    foot = [
        f"等时线 = Pro 原生仿真器在 ΔV×BC 网格（{g['n_dv']}×{g['n_bc']} = {g['n_cases']} 工况）"
        f"上算出的命中时间，步长 {args.iso_step:g} s；命中率 "
        f"{(man.get('stats') or {}).get('hit_rate', 0) * 100:.0f}%。",
        "ΔV 为真空等效增速（不考虑衰减）：thrust_scale = ΔV/ΔV_blk；"
        "BC = m_dry/(CxK·SD)，SD 为迎面面积。",
        f"点 = War-Thunder-Datamine WORK rocketguns 权威 ΔV/BC；"
        f"run_id={run_id} · CALC_VERSION={CALC_VERSION}"
        + ("（已过期，仅示意）" if args.allow_stale and st["stale"] else ""),
    ]
    paths = cp.plot_crossplot(
        points=pts, iso=iso, out_base=FIG_DIR / f"fig_missile_bc_overlay_{args.tag}",
        title=args.title, subtitle=sub, prov=man,
        iso_step=args.iso_step, iso_label_every=args.iso_label_every,
        colorbar=not args.no_colorbar, formats=tuple(args.formats.split(",")),
        footnotes=foot, highlight_label=args.highlight or "", with_fit=args.with_fit)
    for p in paths:
        print(f"[plot] {p}")
    shot = {"run_id": run_id, "manifest": man, "points": [p.__dict__ for p in pts],
            "axis_spec": {"xlim": list(cp.DEFAULT_XLIM), "ylim": list(cp.DEFAULT_YLIM),
                          "source": "自动化分析/aam_plot.py + charts.md"},
            "isoline": {"step_s": args.iso_step, "grid_shape": list(iso.shape),
                        "levels": cp.iso_levels(t_grid, args.iso_step)},
            "figures": [str(p) for p in paths]}
    shot_path = RES_DIR / f"missile_shot_{args.tag}.json"
    shot_path.write_text(json.dumps(shot, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[plot] {shot_path}")
    return 0



# ============================================================ main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline", description="三段式流水线：模型（三层）· ΔV/BC 扫描器 · 绘图")
    ap.add_argument("--config", default=None, help="配置 JSON（默认 configs/baseline.json）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stat", help="第一层：blk 参数统计 → 弹池")
    p.add_argument("--tag", default="WORK", help="数据源版本（默认 WORK 工作区）")
    p.add_argument("--out", default=None)
    p.add_argument("--rebuild-pool", action="store_true")
    p.set_defaults(func=cmd_stat)

    p = sub.add_parser("model", help="第二/三层：跑一个工况并输出结构化记录")
    p.add_argument("--standard", default="PL-12")
    p.add_argument("--missile", default=None, help="原生 profile 名（默认由标准弹推）")
    p.add_argument("--dv", type=float, default=None, help="真空等效增速（默认取该型标称）")
    p.add_argument("--bc", type=float, default=None, help="弹道系数（默认取该型标称）")
    p.add_argument("--range", type=float, default=None)
    p.add_argument("--alt", type=float, default=None)
    p.add_argument("--vm0", type=float, default=None)
    p.add_argument("--vt", type=float, default=None)
    p.add_argument("--pro-dt", type=float, default=None)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--observation", choices=["ideal", "locked"], default=None)
    p.add_argument("--pkg", default=None, help="原生运行包路径（默认取 WT_NATIVE_PKG）")
    p.add_argument("--json", default=None, help="把记录写到该文件")
    p.set_defaults(func=cmd_model)

    p = sub.add_parser("scan", help="第二部分：ΔV/BC 扫描")
    p.add_argument("--standard", default="PL-12")
    p.add_argument("--tag", default=None, help="标准弹池的数据源版本")
    p.add_argument("--dv-min", type=float, default=None)
    p.add_argument("--dv-max", type=float, default=None)
    p.add_argument("--dv-step", type=float, default=10.0)
    p.add_argument("--bc-min", type=float, default=None)
    p.add_argument("--bc-max", type=float, default=None)
    p.add_argument("--bc-step", type=float, default=25.0)
    p.add_argument("--range", type=float, default=None)
    p.add_argument("--alt", type=float, default=None)
    p.add_argument("--target-alt", type=float, default=None)
    p.add_argument("--vm0", type=float, default=None)
    p.add_argument("--vt", type=float, default=None)
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--pro-dt", type=float, default=None)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--observation", choices=["ideal", "locked"], default=None)
    p.add_argument("--cache", default=None, help="缓存路径（空串=禁用）")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-write", action="store_true", help="不落盘（只跑并打印）")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("plot", help="第三部分：出图（aam_fit 版式 + 等时线）")
    p.add_argument("--run-id", default=None, help="扫描产物 id（默认取最近一次）")
    p.add_argument("--tag", default="crossplot")
    p.add_argument("--iso-step", type=float, default=1.0)
    p.add_argument("--iso-label-every", type=float, default=0.0)
    p.add_argument("--points", default=None, help="弹点来源（默认 results/missile_points.json）")
    p.add_argument("--only", default=None, help="只画这些型号（逗号分隔）")
    p.add_argument("--highlight", default="", help="给该型画空心环")
    p.add_argument("--title", default="主动弹 总增速–弹道系数 与 等命中时间线")
    p.add_argument("--formats", default="png,pdf,svg")
    p.add_argument("--no-colorbar", action="store_true")
    p.add_argument("--with-fit", action="store_true", help="额外画线性拟合线（默认不画）")
    p.add_argument("--allow-stale", action="store_true", help="产物过期也强出图（会打标记）")
    p.set_defaults(func=cmd_plot)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ProRuntimeError as exc:
        print(f"[错误] 原生运行包不可用：{exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

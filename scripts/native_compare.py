# -*- coding: utf-8 -*-
"""原生仿真器对拍：把信源文件包里的原生仿真器当"真值"，量化本仓库快模型的误差。

原生侧直接执行游戏 2.59.0.28 的 x86-64 代码（Unicorn），**包体不入库**，
用环境变量指路：

    $env:WT_NATIVE_PKG = "E:\\WT\\tools\\wt-missile-backend"
    python scripts\\native_compare.py                     # 全部分组，ideal 观测
    python scripts\\native_compare.py --groups range loft # 只跑若干组
    python scripts\\native_compare.py --jobs 8 --dt 0.01
    python scripts\\native_compare.py --no-native         # 只算快模型（无包时自检用）

输出：results/native_compare.json（含每条用例的双侧数值与误差）+ 控制台表。
未设置 WT_NATIVE_PKG 时优雅退出（仓库单独克隆仍可运行）。

**观测模式**：`ideal` = 直接把目标真实状态喂给原生制导链（与本模型同一假设，用于比物理）；
`locked` = 走原生导引头滤波 + 传输适配器（默认值，会额外引入观测链路误差）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RES_DIR = ROOT / "results"

# --------------------------------------------------------------------- 用例矩阵

def _native_name(short: str) -> str:
    """标准弹短名 → 原生 profile 名（= blkx 文件名去后缀）。"""
    import missile_metrics
    for s, fn, _label in missile_metrics.MISSILE_FILES:
        if s == short:
            return fn.replace(".blkx", "")
    return short


def _case(group, name, *, standard="PL-12", rng=50000.0, alt=10000.0,
          target_alt=None, vm0=300.0, vt=-300.0, loft=None, dv=None, bc=None,
          mode="ideal", patch=None):
    prof = _native_name(standard)
    return {"group": group, "name": name, "standard": standard, "missile": prof,
            "range": rng, "alt": alt, "target_alt": alt if target_alt is None else target_alt,
            "vm0": vm0, "vt": vt, "loft": loft, "dv": dv, "bc": bc, "mode": mode,
            "patch": patch or {}}


def build_cases(groups: set[str], standard: str = "PL-12") -> list[dict]:
    cases: list[dict] = []
    if "range" in groups:
        for r in (10000.0, 15000.0, 20000.0, 25000.0, 30000.0, 40000.0, 50000.0, 60000.0, 70000.0):
            cases.append(_case("range", f"{r / 1000:.0f} km", standard=standard, rng=r))
    if "alt" in groups:
        for a in (5000.0, 15000.0):
            cases.append(_case("alt", f"{a / 1000:.0f} km 高度", standard=standard, alt=a, rng=50000.0))
    if "loft" in groups:
        # 注意：Flash 侧的高抛控制器仍是启发式（AERO_PLAN P2 才换游戏判据），
        # 故 0° 时不再给原生打 loftEnabled=false 的补丁——两边都按各自的高抛逻辑跑，
        # 差异体现在数值里而不是被补丁掩盖。
        for r in (15000.0, 50000.0):
            cases.append(_case("loft", f"{r / 1000:.0f} km 高抛角 0°", standard=standard,
                               rng=r, loft=0.0))
            cases.append(_case("loft", f"{r / 1000:.0f} km 高抛角 20°", standard=standard,
                               rng=r, loft=20.0))
    if "speed" in groups:
        for vt in (-150.0, -450.0):
            cases.append(_case("speed", f"50 km 目标 {vt:.0f} m/s", standard=standard, vt=vt))
    if "dalt" in groups:
        for ta in (8000.0, 12000.0):
            cases.append(_case("dalt", f"50 km 目标高度 {ta / 1000:.0f} km",
                               standard=standard, target_alt=ta))
    if "missile" in groups:
        import missile_sources
        for m in missile_sources.load_source("latest"):
            cases.append(_case("missile", m["label"], standard=m["label"],
                               dv=m["dv"], bc=m["bc"]))
    if "obsmode" in groups:
        for r in (15000.0, 50000.0):
            for mode in ("ideal", "locked"):
                cases.append(_case("obsmode", f"{r / 1000:.0f} km {mode}",
                                   standard=standard, rng=r, mode=mode))
    return cases


# --------------------------------------------------------------------- 原生侧（子进程）

def _patch_profile(p, updates: dict):
    """在 profile dict 里按 key 名就地改写（取第一个命中处）。模块内可能嵌套。"""
    if not updates:
        return p

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in updates and not isinstance(v, dict):
                    node[k] = updates[k]
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(p)
    return p


def native_worker(payload):
    """子进程：导入包 → 造场景 → 调 core.simulate → 回传 summary。"""
    pkg, case, dt = payload
    pkg = Path(pkg)
    sys.path.insert(0, str(pkg))
    sys.path.insert(0, str(pkg / "tools"))
    try:
        import simulator.core as core                      # noqa: PLC0415
        import simulator.resources as resources            # noqa: PLC0415

        raw = {
            "schema_version": 1, "label": f"{case['group']}/{case['name']}",
            "missile": case["missile"], "version": resources.VERSION,
            "duration_s": 150.0, "dt_s": dt, "sample_period_s": 0.1,
            "observation": {"mode": case["mode"]},
            "launch": {"position_m": [0.0, case["alt"], 0.0],
                       "velocity_m_s": [case["vm0"], 0.0, 0.0]},
            "target": {"position_m": [case["range"], case["target_alt"], 0.0],
                       "velocity_m_s": [case["vt"], 0.0, 0.0], "collision_radius_m": 3.0},
        }
        orig = core.load_profile
        if case["patch"]:
            def patched(name, version=resources.VERSION, _o=orig, _u=case["patch"]):
                p, ident = _o(name, version)
                return _patch_profile(p, _u), ident
            core.load_profile = patched
        try:
            _s, summary, samples = core.simulate(raw)
        finally:
            core.load_profile = orig
        ys = [sm["missile_y_m"] for sm in samples]
        rngs = [sm["range_m"] for sm in samples]
        return {"ok": True, "time_s": summary["time_s"],
                "terminal_event": summary["terminal_event"],
                "final_speed_m_s": summary["final_speed_m_s"],
                "max_alt_m": max(ys) if ys else None,
                "min_range_m": min(rngs) if rngs else None,
                "steps": summary["steps"], "dt_s": summary["dt_s"],
                "model": summary.get("model")}
    except Exception as exc:                                # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------- 快模型侧

def fast_run(case):
    """本仓库快模型跑同一工况（用该用例自己的标准弹 + 有限燃烧）。"""
    from missile_sim.config import (apply_standard, cxk_for_bc, delta_v_equiv,
                                    load_config)
    from missile_sim.sim import Case, simulate_one

    cfg = load_config()
    cfg.standard.name = case["standard"]
    apply_standard(cfg)
    cfg.scenario.vm0 = case["vm0"]
    cfg.scenario.vt = case["vt"]
    cfg.scenario.alt = case["alt"]
    cfg.scenario.range = case["range"]
    cfg.scenario.target_alt = case["target_alt"]
    if case["loft"] is not None:
        cfg.sim.theta_loft_deg = case["loft"]
    dv = delta_v_equiv(cfg) if case["dv"] is None else float(case["dv"])
    cxk = cfg.drag.cxk if case["bc"] is None else float(cxk_for_bc(case["bc"], cfg))
    r = simulate_one(cfg, Case(dv_total=dv, cxk=cxk), record_trace=False)
    return {"t_hit": r.t_hit if r.hit else None, "status": r.status_name,
            "v_impact": r.v_impact, "max_alt_m": r.max_alt,
            "profile": cfg.profile.name if cfg.profile else None,
            "profile_hash": cfg.profile.profile_hash() if cfg.profile else None,
            "burn": cfg.standard.burn, "dv": dv}


# --------------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="原生仿真器 vs 快模型 对拍")
    ap.add_argument("--groups", nargs="+", default=["range", "alt", "loft", "speed", "dalt", "missile", "obsmode"],
                    choices=["range", "alt", "loft", "speed", "dalt", "missile", "obsmode"])
    ap.add_argument("--jobs", type=int, default=8, help="原生侧并发进程数（每进程约 228 MB）")
    ap.add_argument("--dt", type=float, default=0.01, help="原生侧步长，允许上限 0.01")
    ap.add_argument("--no-native", action="store_true", help="只算快模型（无包时自检）")
    ap.add_argument("--standard", default="PL-12", help="Flash 侧标准弹短名（场景组用它；跨弹型组逐弹用自己的）")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    pkg = os.environ.get("WT_NATIVE_PKG", "").strip()
    if not args.no_native and not pkg:
        pkg = r"E:\WT\tools\wt-missile-backend"
        if not Path(pkg).exists():
            print("未设置 WT_NATIVE_PKG（且 E:\\WT\\tools\\wt-missile-backend 不存在）。\n"
                  "原生侧跳过——只跑快模型。设置方式：\n"
                  '  $env:WT_NATIVE_PKG = "<解压后的 wt-missile-backend 目录>"', file=sys.stderr)
            args.no_native = True
    if not args.no_native and not (Path(pkg) / "tools" / "simulator" / "core.py").exists():
        print(f"WT_NATIVE_PKG={pkg} 不是有效的包根（找不到 tools/simulator/core.py）", file=sys.stderr)
        return 2

    supported = None
    if not args.no_native:
        try:
            sys.path.insert(0, str(Path(pkg) / "tools"))
            sys.path.insert(0, pkg)
            from simulator.resources import PROFILES_BY_VERSION, VERSION as NATIVE_VERSION  # noqa: PLC0415
            supported = set(PROFILES_BY_VERSION.get(NATIVE_VERSION, ()))
            print(f"原生包版本 {NATIVE_VERSION}，支持 {len(supported)} 型：{', '.join(sorted(supported))}")
        except Exception as exc:                            # noqa: BLE001
            print(f"（读取原生 profile 列表失败，不过滤：{type(exc).__name__}: {exc}）", file=sys.stderr)

    cases = build_cases(set(args.groups), standard=args.standard)
    print(f"用例 {len(cases)} 条（Flash 标准弹 {args.standard}）；原生侧 dt={args.dt:g} s，"
          f"并发 {args.jobs}"
          f"{'（已跳过原生）' if args.no_native else f'，包根 {pkg}'}")
    fast = {f"{c['group']}/{c['name']}": fast_run(c) for c in cases}
    native: dict[str, dict] = {}
    if not args.no_native:
        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(native_worker, (pkg, c, args.dt)): c for c in cases}
            for i, fut in enumerate(as_completed(futs), 1):
                c = futs[fut]
                native[f"{c['group']}/{c['name']}"] = fut.result()
                print(f"\r  原生进度 {i}/{len(cases)}", end="", flush=True)
        print(f"\r  原生完成，用时 {time.perf_counter() - t0:.1f} s" + " " * 12)

    rows = []
    for c in cases:
        key = f"{c['group']}/{c['name']}"
        f_, n_ = fast[key], native.get(key, {})
        rec = {"group": c["group"], "name": c["name"], "standard": c["standard"],
               "missile": c["missile"],
               "range_m": c["range"], "alt_m": c["alt"], "target_alt_m": c["target_alt"],
               "vm0": c["vm0"], "vt": c["vt"], "loft_deg": c["loft"], "mode": c["mode"],
               "patch": c["patch"], "fast": f_, "native": n_}
        ft, nt = f_.get("t_hit"), n_.get("time_s")
        if ft is not None and nt is not None:
            rec["dt_s"] = nt - ft
            rec["dt_pct"] = (nt - ft) / nt * 100.0
            rec["dv_impact"] = (n_.get("final_speed_m_s") or 0.0) - f_.get("v_impact", 0.0)
        rows.append(rec)

    print()
    print(f"{'用例':<22}{'原生 t':>9}{'快模型 t':>10}{'Δt':>8}{'Δ%':>8}"
          f"{'原生 V':>9}{'快模型 V':>10}{'ΔV':>7}  事件")
    for r in rows:
        n_, f_ = r["native"], r["fast"]
        if not n_.get("ok", True) and n_.get("error"):
            print(f"{r['group'] + '/' + r['name']:<22}  原生失败: {n_['error'][:60]}")
            continue
        if r.get("dt_s") is None:
            print(f"{r['group'] + '/' + r['name']:<22}  不完整: 原生={n_.get('terminal_event')} 快={f_['status']}")
            continue
        print(f"{r['group'] + '/' + r['name']:<22}{n_['time_s']:9.3f}{f_['t_hit']:10.3f}"
              f"{r['dt_s']:+8.3f}{r['dt_pct']:+8.2f}{n_.get('final_speed_m_s', float('nan')):9.0f}"
              f"{f_['v_impact']:10.0f}{r['dv_impact']:+7.0f}  {n_.get('terminal_event')}")

    ok = [r for r in rows if r.get("dt_s") is not None]
    if ok:
        import statistics as st
        pcts = [abs(r["dt_pct"]) for r in ok]
        print()
        print(f"可对拍 {len(ok)}/{len(rows)} 条：时间相对误差 中位 {st.median(pcts):.2f}% / "
              f"最大 {max(pcts):.2f}%；绝对误差 最大 {max(abs(r['dt_s']) for r in ok):.2f} s")
        for g in sorted({r["group"] for r in ok}):
            sub = [abs(r["dt_pct"]) for r in ok if r["group"] == g]
            print(f"   {g:<9} n={len(sub):2d}  中位 {st.median(sub):6.2f}%  最大 {max(sub):6.2f}%")

    RES_DIR.mkdir(parents=True, exist_ok=True)
    tag = args.tag or f"native_compare_{args.standard}"
    out = RES_DIR / f"{tag}.json"
    out.write_text(json.dumps({"native_pkg": None if args.no_native else pkg, "dt_s": args.dt,
                               "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

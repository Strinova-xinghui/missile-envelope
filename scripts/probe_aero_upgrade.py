# -*- coding: utf-8 -*-
"""探针：严格按单一信源文件评估「升力 + 诱导阻力」升级的可行性与影响。

**唯一公式来源**：`E:/War Thunder/_recon/升力与诱导阻力_实现规格.md`
（第三部分实现规格 §3.1~§3.4、第四部分参数 §4.1~§4.2、第七部分参考实现与自检值）。
其余任何逆向文档都**不作为依据**。

本脚本不改动仓库里的模型：运行时替换 `_ScalarSim._accel` 的阻力项，同工况对比：

    ① 现状      D = q·S·CxK
    ② +f(M)     D = q·S·CxK·f(M)
    ③ 完整      D = q·S·CxK·f(M) + q·S·CxK·CxAoA·F(M)·sin²α，并把过载截到气动极限

α 的取法（该文件未给出，按本文件 §3.1 的力公式反解，是本文件自身唯一自洽的闭合方式）：
    N = q·A_wing·Cy，Cy = CyK·sin|α|（折返限幅）
    点质量模型里法向力就是指令过载 N = m·|a_perp| ⇒ sin|α| = m·|a_perp|/(q·A_wing·CyK)
    气动上限 N_max = q·A_wing·CyMaxAoA ⇒ 对应的 α_max = asin(CyMaxAoA/CyK)

用法：
    python scripts\\probe_aero_upgrade.py            # 全部
    python scripts\\probe_aero_upgrade.py --quick    # 跳过 11 型弹逐条
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import missile_sim.sim as S  # noqa: E402
from missile_sim import atmosphere  # noqa: E402
from missile_sim.config import cxk_for_bc, load_config  # noqa: E402
from missile_sim.sim import Case, simulate_one  # noqa: E402

RES_DIR = ROOT / "results"


# ------------------------------------------------- 信源 §3.4：两个公共马赫函数（§2.1 标 ✅）

def f_mach(M: float) -> float:
    """基础阻力马赫函数 f(M)，信源 §1.3 五段式。"""
    if M < 0.61:
        return 0.308
    if M < 1.0:
        return 0.308 + 0.505 * (M - 0.61) ** 2.31
    if M < 1.4:
        d = M - 1.0
        return 0.551 + 0.4485 * (d ** 0.505) * math.exp(-5.68 * d)
    if M < 4.0:
        return M / ((0.356 * M + 2.237) * M - 1.4)
    return 0.302


def F_mach(M: float) -> float:
    """迎角附加阻力的马赫系数，信源 §3.4：F(M) = 3.247×[0.308 + 0.75(f(M)−0.308)]。"""
    return 3.247 * (0.308 + 0.75 * (f_mach(M) - 0.308))


# 信源 §7 自检值（M, f(M), F(M)）——本实现必须逐项吻合
SPEC_CHECK = [
    (0.5, 0.308, 1.000076), (0.61, 0.308, 1.000076), (0.99, 0.362024591, 1.13163938),
    (1.0, 0.551, 1.59184175), (1.2, 0.614888702, 1.74742671), (1.4, 0.576236026, 1.65329778),
    (2.0, 0.444642063, 1.33283358), (3.112, 0.34542308, 1.09121055),
    (3.999, 0.302064021, 0.985620406), (4.0, 0.302, 0.9854645),
]

# 信源 §4.1 参数名与默认值（blkx 键名）；§4.2 参考实例 AIM-120C5（注：该实例是 2.57.1.99 数据）
P_DEFAULT = dict(cyk=2.2, cy_max_aoa=1.0, cx_aoa=9.0, wing_area_mult=1.0,
                 cxk=0.2, caliber=1.0)
P_SPEC_120C5 = dict(caliber=0.1778, length=3.66, cxk=1.405, cyk=2.2,
                    wing_area_mult=1.225, cy_max_aoa=1.8, mass=161.4789, mass_end=110.223)


# ------------------------------------------------- 信源 §3.1 / §3.2：升力与阻力

def lift_trim(q, m, a_wing, cyk, cy_max_aoa, n_cmd_g, g):
    """由需求过载反解迎角与实际升力系数（信源 §3.1 的力公式 + 折返限幅）。

    返回 (N_actual[N], alpha[rad], Cy, 是否触到气动极限)
    """
    n_req = abs(n_cmd_g)
    n_peak = q * a_wing * cy_max_aoa / (m * g)          # 升力系数峰值对应的过载
    if n_req > n_peak:
        alpha = math.asin(min(1.0, cy_max_aoa / cyk))    # 折返峰值攻角
        return n_peak * m * g, alpha, cy_max_aoa, True
    sin_a = n_req * m * g / max(q * a_wing * cyk, 1e-12)
    sin_a = min(sin_a, 1.0)
    alpha = math.asin(sin_a)
    cy_pre = cyk * sin_a
    cy = cy_pre if cy_pre <= cy_max_aoa else max(0.0, 2.0 * cy_max_aoa - cy_pre)
    return n_req * m * g, alpha, cy, False


MODE = [0]
_orig_accel = S._ScalarSim._accel
PAR = {"caliber": 0.1778, "length": 3.66, "cxk": 1.225, "cyk": 2.2,
       "cy_max_aoa": 1.0, "cx_aoa": 9.0, "wing_area_mult": 1.7}
A_WING = S_FRONT = 0.0


def _accel_patched(self, h, v, gamma):
    c = self.const
    rho = float(atmosphere.density(h, c.rho0, c.h_max)) if h > 0.0 else c.rho0
    a_snd = float(atmosphere.speed_of_sound(h)) if h > 0.0 else float(atmosphere.speed_of_sound(1.0))
    q = 0.5 * rho * v * v
    mach = v / a_snd
    coeff = c.drag_coeff * (f_mach(mach) if MODE[0] >= 1 else 1.0)   # 信源 §3.3 基础阻力
    a_perp = self.a_perp
    if MODE[0] >= 2:                                                  # 信源 §3.1 + §3.2
        n_cmd = a_perp / c.g
        _n, alpha, _cy, capped = lift_trim(q, self.mass, A_WING, PAR["cyk"],
                                           PAR["cy_max_aoa"], n_cmd, c.g)
        if capped:                       # 气动拉不出来 → 实际过载被截断
            a_perp = math.copysign(min(abs(a_perp), _n * c.g), a_perp)
        d_aoa = (q * S_FRONT * PAR["cxk"] * PAR["cx_aoa"] * F_mach(mach)
                 * math.sin(alpha) ** 2)
        coeff += d_aoa / (rho * v * v * self.mass)
    return coeff * rho * v * v * -1.0 - c.g * math.sin(gamma), a_perp / max(v, 1.0)


S._ScalarSim._accel = _accel_patched      # 只在本进程内生效，退出前恢复


def run(dv, bc, mode, rng=None, loft=None):
    MODE[0] = mode
    cfg = load_config()
    if rng is not None:
        cfg.scenario.range = rng
    if loft is not None:
        cfg.sim.theta_loft_deg = loft
    return simulate_one(cfg, Case(dv_total=dv, cxk=float(cxk_for_bc(bc, cfg))), record_trace=False)


def main(argv=None) -> int:
    global A_WING, S_FRONT
    ap = argparse.ArgumentParser(description="按单一信源文件评估升力+诱导阻力升级")
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    PAR.update(caliber=cfg.drag.caliber_m, length=3.66, cxk=cfg.drag.cxk,
               wing_area_mult=1.7)          # 工作区 blkx（2.59.0.11）的 120C5 实际取值
    A_WING = 0.3 * PAR["caliber"] * PAR["length"] * PAR["wing_area_mult"]
    S_FRONT = math.pi * PAR["caliber"] ** 2 / 4.0
    mass, g = cfg.mass.mass_end, cfg.atmosphere.g
    out: dict = {"source": "E:/War Thunder/_recon/升力与诱导阻力_实现规格.md",
                 "params_used": {**PAR, "mass_end": mass},
                 "a_wing": A_WING, "s_front": S_FRONT}

    print("=" * 88)
    print("① 信源 §7 自检表对拍（f(M) / F(M)，本实现 vs 文件给定值）")
    worst = max(max(abs(f_mach(M) - f), abs(F_mach(M) - F)) for M, f, F in SPEC_CHECK)
    print(f"   {len(SPEC_CHECK)} 点最大偏差 {worst:.3e} → "
          f"{'完全一致' if worst < 1e-6 else '★不一致'}")
    out["f_check_max_dev"] = worst

    print()
    print("② 用信源 §4.2 参考实例复算 D_base（h=5000 m, V=1000 m/s）")
    rho5 = float(atmosphere.density(5000.0))
    a5 = float(atmosphere.speed_of_sound(5000.0))
    M5 = 1000.0 / a5
    q5 = 0.5 * rho5 * 1000.0 ** 2
    s_spec = math.pi * P_SPEC_120C5["caliber"] ** 2 / 4.0
    a_spec = 0.3 * P_SPEC_120C5["caliber"] * P_SPEC_120C5["length"] * P_SPEC_120C5["wing_area_mult"]
    d_base_spec = q5 * s_spec * P_SPEC_120C5["cxk"] * f_mach(M5)
    print(f"   ρ={rho5:.6f}（信源 0.736757）  a={a5:.2f}（信源 321.3，差 "
          f"{abs(a5 - 321.3) / 321.3 * 100:.2f}%）  M={M5:.4f}（信源 3.112）")
    print(f"   A_wing={a_spec:.6f}（信源 0.239150）  S_front={s_spec:.6f}（信源 0.024829）")
    print(f"   D_base={d_base_spec:.1f} N（信源 4438.9 N，差 "
          f"{abs(d_base_spec - 4438.9) / 4438.9 * 100:.2f}%）")
    out["ref_case"] = {"rho": rho5, "a": a5, "mach": M5, "a_wing": a_spec,
                       "s_front": s_spec, "d_base": d_base_spec}

    print()
    print("③ 基础阻力口径：现状 ÷ 游戏 = 1/f(M)（>1 表示现状阻力偏大）")
    ratio = []
    for h_km in (0.0, 5.0, 10.0, 15.0):
        for V in (300.0, 500.0, 800.0, 1000.0, 1400.0):
            a_s = float(atmosphere.speed_of_sound(h_km * 1000.0 if h_km else 1.0))
            ratio.append(1.0 / f_mach(V / a_s))
    print(f"   全包线 {min(ratio):.2f}x ~ {max(ratio):.2f}x，中位 "
          f"{sorted(ratio)[len(ratio) // 2]:.2f}x")
    out["drag_ratio"] = {"min": min(ratio), "max": max(ratio)}

    print()
    print("④ 同工况对比（10 km、300/-300 m/s、ΔV 865.3、BC 3624）")
    scen = [("50 km 高抛22°", 50000.0, 22.0), ("50 km 无高抛", 50000.0, 0.0),
            ("70 km 高抛22°", 70000.0, 22.0), ("70 km 无高抛", 70000.0, 0.0),
            ("30 km 无高抛", 30000.0, 0.0), ("80 km 高抛30°", 80000.0, 30.0)]
    print(f"   {'工况':<15}{'① 现状':>21}{'② +f(M)':>21}{'③ 完整':>21}")
    cases = []
    for name, rng, loft in scen:
        cells, rec = [], {"name": name}
        for mode in (0, 1, 2):
            r = run(865.3, 3624.0, mode, rng, loft)
            cells.append(f"{r.status_name[:11]:>11}{r.t_hit if r.hit else float('nan'):6.1f}"
                         f"{r.v_impact:5.0f}")
            rec[f"mode{mode}"] = {"status": r.status_name, "t_hit": r.t_hit if r.hit else None,
                                  "v_impact": r.v_impact}
        cases.append(rec)
        print(f"   {name:<15}" + "".join(cells))
    print("   （每格 = 状态 / t_hit[s] / V命中[m/s]）")
    out["scenarios"] = cases

    if not args.quick:
        print()
        print("⑤ 11 型主动弹（默认 50 km 迎头、10 km、高抛 22°）")
        import missile_sources
        missiles = missile_sources.load_source("latest")
        print(f"   {'弹':<8}{'ΔV':>7}{'BC':>7} |{'① t':>7}{'V命中':>7} |{'② t':>7}{'V命中':>7} "
              f"|{'③ t':>7}{'V命中':>7} |{'ΔV命中':>8}")
        recs, deltas = [], []
        t0 = time.perf_counter()
        for m in missiles:
            rs = [run(m["dv"], m["bc"], mode) for mode in (0, 1, 2)]
            d = rs[2].v_impact - rs[0].v_impact
            deltas.append(d)
            recs.append({"label": m["label"], "t_hit": [r.t_hit if r.hit else None for r in rs],
                         "v_impact": [r.v_impact for r in rs]})
            print(f"   {m['label']:<8}{m['dv']:7.1f}{m['bc']:7.1f} |{rs[0].t_hit:7.2f}{rs[0].v_impact:7.0f} "
                  f"|{rs[1].t_hit:7.2f}{rs[1].v_impact:7.0f} |{rs[2].t_hit:7.2f}{rs[2].v_impact:7.0f} "
                  f"|{d:+8.0f}")
        print(f"   命中速度平均提升 {sum(deltas) / len(deltas):+.0f} m/s，用时 {time.perf_counter() - t0:.0f} s")
        out["missiles"] = recs

    print()
    print("⑥ 升力配平表（信源 §3.1 反解：sinα = n·m·g/(q·A_wing·CyK)；气动上限 n=q·A_wing·CyMaxAoA/(m·g)）")
    trim = []
    for h_km in (5.0, 10.0):
        h = h_km * 1000.0
        rho = float(atmosphere.density(h))
        a_s = float(atmosphere.speed_of_sound(h))
        print(f"\n   h={h_km:.0f} km  A_wing={A_WING:.5f} m²  CyMaxAoA/CyK 折返点 α="
              f"{math.degrees(math.asin(min(1.0, PAR['cy_max_aoa'] / PAR['cyk']))):.2f}°")
        print(f"   {'V':>6}{'M':>6}{'q[Pa]':>9}{'n_max':>8}{'10g→α':>9}{'占比':>7}"
              f"{'20g→α':>9}{'占比':>7}{'35g→α':>9}{'占比':>7}")
        for V in (300.0, 400.0, 600.0, 800.0, 1000.0, 1200.0):
            M = V / a_s
            q = 0.5 * rho * V * V
            n_max = q * A_WING * PAR["cy_max_aoa"] / (mass * g)
            line, row = f"   {V:6.0f}{M:6.2f}{q:9.0f}{n_max:8.1f}", {"h_m": h, "v": V, "n_max": n_max}
            for n in (10.0, 20.0, 35.0):
                _N, alpha, _cy, capped = lift_trim(q, mass, A_WING, PAR["cyk"],
                                                   PAR["cy_max_aoa"], n, g)
                db = q * S_FRONT * PAR["cxk"] * f_mach(M)
                da = q * S_FRONT * PAR["cxk"] * PAR["cx_aoa"] * F_mach(M) * math.sin(alpha) ** 2
                line += f"{math.degrees(alpha):9.2f}{da / (db + da) * 100:6.0f}%"
                row[f"n{n:g}"] = {"alpha_deg": math.degrees(alpha), "share": da / (db + da),
                                  "capped": capped}
            print(line + ("   ← 拉不满" if n_max < 35 else ""))
            trim.append(row)
    out["trim"] = trim

    RES_DIR.mkdir(parents=True, exist_ok=True)
    p = RES_DIR / "aero_upgrade_probe.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON：{p}")
    S._ScalarSim._accel = _orig_accel
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

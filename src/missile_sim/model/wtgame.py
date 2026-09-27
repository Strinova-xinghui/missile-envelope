# -*- coding: utf-8 -*-
"""**wt-missile 引擎**：2.59.0.28 原生 6DOF 的纯 Python 复刻，两档 `standard` / `fast`。

模型身份（求解器自报）：`MODEL = "python-game-6dof-v1"`。它不是"又一套近似公式"，而是把
2.59.0.28 那份 ELF 的导引/高抛、双轴 PID、有限级发动机与 TVC、三维气动力矩、刚体积分与
观测滤波**逐式重写**成 Python（源码内留地址溯源），因此**不需要游戏 ELF，也不需要 Unicorn**。
公式依据的 ELF 是 `94de5454…`（与 `constants.ELF_SHA256_28` 同源）。评估报告见
`docs/THIRD-PARTY-SOLVER.md`，只读副本约定见 `vendor/wt-missile/VENDOR.md`。

两档的区别**只在算术路径，不在物理**：

    standard  纯 Python 逐物理步
    fast      同一物理编译成 C 内核（`compiled_simulate`）；本机没有 C 编译器时它自己回退
              `python-legacy`（标量刚体力求值），回退原因进 `EngineStamp.resources.backend`

所以两档各是一张 `ModelSpec`（各有自己的缓存文件），而**不是**同一模型上的一个字段：
`EngineInputs.cache_key()` 里不含档位，两档必须靠缓存文件物理隔离。

**ΔV/BC 乘数的唯一算法仍在 `io.build_inputs`**。本模块按 `native.simulate_native` 的同款做法
monkeypatch `wt_missile.load_profile`，只把**已经算好的**乘数施加到 profile 上：
`force` / `force1`（以及多元发动机的 `impulse*.force`，同一 key 名）× `thrust_scale`；
`CxK` × `cx_scale`。已确认 `load_profile` 是模块级全局名，`compiled_simulate`（L2215）与
`scene_simulate` 都走它，因此 C 档同样吃到乘数。

步长默认取求解器的**客户端对象时钟** `SOLVER_DT = 1/48 s`（带 ELF 地址溯源，金标即在此时钟下
验证），并固定 `step_policy="fixed"` —— 这两条同时是"能走 C 快路径"的条件（求解器对显式周期
输出、以及需要边界切分的非默认步长会主动回退 Python 并如实报告原因）。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from pathlib import Path

from .constants import DT_DEFAULT, HIT_EVENTS, ROOT, SOLVER_DT, VENDOR_DIR, VERSION_28
from .native import NativeResult, _f, _patch_profile, _trajectory
from .spec import EngineStamp, EngineEnv, EngineInputs, ModelSpec, SelfTestReport

# vendor 只读副本的身份（改这里等于改 vendor，必须同步 VENDOR.md）
SOLVER_FILE = "wt_missile.py"
SOLVER_SHA256 = "1bfa0fa2a3a6d34faa01e4b6ad77e15ba10573ed857bc3362ed368b4e8511890"

TIERS = ("standard", "fast")

_SOLVER = None


class SolverUnavailable(RuntimeError):
    """vendor 求解器不可用：目录缺失、哈希不符或导入失败。"""


# --------------------------------------------------------------------- 加载


def solver_file() -> Path:
    return VENDOR_DIR / SOLVER_FILE


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_solver(*, verify: bool = True):
    """懒加载 vendor 求解器：把 vendor 目录挂上 `sys.path` 后 `import wt_missile`。

    目录名带连字符（`wt-missile`）不能当包名，但 `wt_missile.py` 本身是合法模块名，
    所以挂目录即可 —— 子进程里同样有效（`EngineRunner._pool_payload` 会 import 本模块，
    本模块再完成这次加载）。
    """
    global _SOLVER
    if _SOLVER is not None:
        return _SOLVER
    p = solver_file()
    if not p.is_file():
        raise SolverUnavailable(f"vendor 求解器不在：{p}；见 vendor/wt-missile/VENDOR.md")
    if verify:
        got = file_sha256(p)
        if got != SOLVER_SHA256:
            raise SolverUnavailable(
                f"vendor 求解器哈希不符：{got}（期望 {SOLVER_SHA256}）。"
                "该目录是只读副本，升级流程见 vendor/wt-missile/VENDOR.md")
    d = str(VENDOR_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        _SOLVER = importlib.import_module("wt_missile")
    except Exception as exc:                                    # noqa: BLE001
        raise SolverUnavailable(f"vendor 求解器导入失败：{type(exc).__name__}: {exc}") from exc
    return _SOLVER


def resource_identity(*, verify: bool = True) -> dict:
    """求解器与资源的身份块（不跑积分）。"""
    wt = load_solver(verify=verify)
    man = {}
    try:
        man = json.loads(
            (VENDOR_DIR / "inputs" / "resources" / wt.VERSION / "manifest.json")
            .read_text(encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        man = {}
    try:
        rel = str(solver_file().relative_to(ROOT))
    except ValueError:
        rel = str(solver_file())
    return {
        "solver": "wt-missile",
        "solver_model": str(getattr(wt, "MODEL", "")),
        "solver_version": str(getattr(wt, "VERSION", "")),
        "solver_file": rel,
        "solver_sha256": SOLVER_SHA256,
        "resource_archive_sha256": man.get("archive_sha256"),
        "n_profiles": len(getattr(wt, "PROFILES", ()) or ()),
        "elf_executed": False,
        "formula_basis_elf_sha256": str(getattr(wt, "ELF_SHA256", "")),
    }


# --------------------------------------------------------------------- 场景


def dt_for(inp) -> float:
    """本次实际用的步长。

    默认 `SOLVER_DT`（1/48 s 客户端对象时钟，金标即在此时钟下验证）。只有调用方**显式**给了
    别的步长才透传 —— `DT_DEFAULT`(0.01) 是本项目旧原生档的默认值，无法区分"显式设成 0.01"
    与"没设"，故按"未指定"处理（与 `config.pro_dt` 的新默认值一致）。
    """
    try:
        d = float(getattr(inp, "dt", 0.0) or 0.0)
    except (TypeError, ValueError):
        d = 0.0
    if d <= 0.0 or abs(d - DT_DEFAULT) < 1e-12:
        return float(SOLVER_DT)
    return d


def scenario_from_inputs(inp: EngineInputs, *, tier: str) -> dict:
    """`EngineInputs` → 求解器的高级场景格式（字段名与语义一一对应）。

    `sample_period_s=None` 是刻意的：显式周期输出会让求解器放弃 C 快路径。
    `step_policy="fixed"` + 客户端时钟同样是快路径条件；非默认步长会被求解器主动回退并
    在 `fastmode.compiled_fallback_reason` 里说明。
    """
    raw = {
        "schema_version": 1,
        "label": f"wtgame/{tier}/{inp.missile}",
        "missile": str(inp.missile),
        "version": str(inp.version or VERSION_28),
        "duration_s": float(inp.duration_s),
        "dt_s": float(dt_for(inp)),
        "step_policy": "fixed",
        "fastmode": tier == "fast",
        "sample_period_s": None,
        "observation": {"mode": str(inp.observation_mode)},
        "launch": {"position_m": [0.0, float(inp.alt_m), 0.0],
                   "velocity_m_s": [float(inp.vm0), 0.0, 0.0]},
        "target": {"position_m": [float(inp.range_m), float(inp.target_alt), 0.0],
                   "velocity_m_s": [float(inp.vt), 0.0, 0.0],
                   "collision_radius_m": float(inp.hit_radius_m)},
        "wind_m_s": [float(x) for x in (inp.wind_m_s or (0.0, 0.0, 0.0))],
        "ground_height_m": float(inp.ground_height_m),
        "proximity_fuse": bool(inp.proximity_fuse),
    }
    if inp.target_maneuvers:
        raw["target"]["maneuvers"] = [
            {"time_s": float(t), "acceleration_m_s2": [float(x) for x in a]}
            for t, a in inp.target_maneuvers]
    return raw


# --------------------------------------------------------------------- 运行


def simulate_tier(inp: EngineInputs, *, tier: str):
    """跑一档，返回 `(summary, rows)`。

    乘数**不在这里算**：从 `inp`（`io.build_inputs` 产出）读，只负责施加。
    """
    wt = load_solver()
    raw = scenario_from_inputs(inp, tier=tier)
    s_scale = float(inp.thrust_scale)
    cx_scale = float(inp.cx_scale)
    orig = wt.load_profile

    def complete(name, version=None):
        params, ident = orig(name, version or wt.VERSION)
        if s_scale == 1.0 and cx_scale == 1.0:
            return params, ident
        upd = {}
        if s_scale != 1.0:
            for k in ("force", "force1"):
                v = params.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    upd[k] = v * s_scale
        if cx_scale != 1.0:
            v = params.get("CxK")
            if isinstance(v, (int, float)) and v > 0:
                upd["CxK"] = v * cx_scale
        return _patch_profile(params, upd), ident

    wt.load_profile = complete
    try:
        # `python_simulate` 是 fast/standard 的统一入口：fastmode=False 直接走 scene_simulate，
        # fastmode=True 先试 `compiled_simulate`，缺编译器时自行回退并给出原因。
        _s, summary, rows = wt.python_simulate(raw)
    finally:
        wt.load_profile = orig
    return summary, rows


def to_native_result(inp: EngineInputs, summary: dict, rows: list) -> NativeResult:
    """求解器输出 → 项目统一的 `NativeResult`（口径与 `simulate_native` 对齐）。"""
    if not rows:
        return NativeResult(ok=False, error="求解器没有返回任何轨迹行")
    thrusts = [r.get("thrust_N") or 0.0 for r in rows]
    speeds = [float(r.get("speed_m_s") or 0.0) for r in rows]
    masses = [float(r.get("mass_kg") or 0.0) for r in rows]
    powered = [i for i, t in enumerate(thrusts) if t and t > 0.0]
    i_burn = powered[-1] if powered else 0
    event = str(summary.get("terminal_event", "") or "")
    hit = event in HIT_EVENTS
    min_sep = float(summary.get("minimum_separation_until_event_m", math.nan))
    if hit and inp.hit_radius_m > 0.0 and math.isfinite(min_sep) and min_sep > inp.hit_radius_m:
        hit = False                                    # 近炸半径外不算命中
    t_end = float(summary.get("time_s", math.nan))
    return NativeResult(
        ok=True, event=event, t_end=t_end, t_hit=(t_end if hit else math.nan), hit=hit,
        miss_distance_m=min_sep,
        max_alt_m=max(float(r.get("missile_y_m") or 0.0) for r in rows),
        v_impact=float(summary.get("final_speed_m_s", math.nan)),
        dv_measured=float(speeds[i_burn] - speeds[0]),
        m_launch=float(masses[0]), m_dry=float(min(masses)),
        t_burnout=float(rows[i_burn].get("time_s", math.nan)),
        thrust_scale=float(inp.thrust_scale), cx_scale=float(inp.cx_scale),
        dv_blk=float(inp.dv_blk), bc_blk=float(inp.bc_blk),
        samples=(_trajectory(rows) if inp.save_trajectory else []),
        resource=("wt-missile/" + str(inp.version or VERSION_28)
                  + ("+compiled-c" if _backend_of(summary) == "compiled-c" else "")),
    )


def _backend_of(summary: dict) -> str:
    fm = (summary or {}).get("fastmode") or {}
    return str(fm.get("backend") or "") if fm.get("enabled") else ""


def _fallback_of(summary: dict) -> str | None:
    fm = (summary or {}).get("fastmode") or {}
    return fm.get("compiled_fallback_reason") or fm.get("fallback_reason") or None


# --------------------------------------------------------------------- 引擎


class _WtEngine:
    """两档共用的 `Engine` 实现（差别只有 `tier`）。"""

    tier = "standard"

    def __init__(self, *, env: EngineEnv | None = None, **kw):
        self.env = env

    # --- 身份 ---------------------------------------------------------

    @property
    def spec(self) -> ModelSpec:
        from .registry import spec_of                            # noqa: PLC0415
        return spec_of(self.tier)

    def runtime_info(self) -> dict:
        """身份块（进记录与 manifest）。**懒解析**：不跑就不碰 vendor。"""
        sp = self.spec
        d = {"kind": "wtgame", "engine": sp.name, "engine_version": sp.version,
             "calc_version": sp.calc_version, "tier": self.tier}
        try:
            d.update(resource_identity())
        except Exception as exc:                                # noqa: BLE001
            d["runtime_error"] = f"{type(exc).__name__}: {exc}"
        return d

    def stamp(self, inp: EngineInputs | None = None, summary: dict | None = None) -> EngineStamp:
        sp = self.spec
        rt = self.runtime_info()
        # 后端**只能来自证据**，不能按档位名猜：
        #   * `standard` 档必然是 `python-standard` —— `scenario_from_inputs` 里 `fastmode`
        #     恒为 `False`，这是**构造事实**；
        #   * `fast` 档可能是 `compiled-c` 也可能是回退的 `python-legacy`，没跑过就只能
        #     说不知道（曾经猜成 `compiled-c`；机器没有 C 编译器时那就是撒谎）。
        backend = _backend_of(summary or {}) or (
            "python-standard" if self.tier == "standard" else "unreported")
        return EngineStamp(
            name=sp.name, version=sp.version, calc_version=sp.calc_version,
            fidelity={
                "recovered": [
                    "原生 PN + 高抛控制律（含 loft* 字段、退出判据与弹体俯仰口径）",
                    "双轴 PID（pid0…N 时间表 / 扁平 accelControl* 两种形态）",
                    "有限级发动机、分级质量流失、TVC、气压推力修正",
                    "三维气动力与力矩、四元数刚体积分",
                    "观测滤波（locked）与理想观测（ideal）",
                ],
                "not_recovered": [
                    "外环控制器 orientationAutopilot / orientationAutopilotLeadingMult / "
                    "propulsionAutopilot / useThrustVectoring —— 命中即拒绝该型，不做近似替代",
                    "重复 endSpeed 资源与非恒定 Cy 表 —— 明确拒绝",
                    "损伤/击毁模型与完整多回波雷达环境（locked 仍为永久跟踪假设）",
                ],
                "derived": [
                    "ΔV/BC → force*/CxK 的乘数由本项目 io.build_inputs 提供，加载 profile 时施加",
                ],
            },
            resources={
                "tier": self.tier, "backend": backend,
                **{k: v for k, v in rt.items()
                   if k in ("solver", "solver_model", "solver_version", "solver_sha256",
                            "resource_archive_sha256", "elf_executed",
                            "formula_basis_elf_sha256", "n_profiles")},
            },
        )

    # --- 运行 ---------------------------------------------------------

    def inputs(self, env, inp: EngineInputs) -> EngineInputs:
        if inp is None:
            raise ValueError(f"{type(self).__name__} 需要 EngineInputs")
        bad = inp.check()
        if bad:
            raise ValueError(f"{self.tier} 引擎输入不自洽：" + "；".join(bad))
        return inp

    def simulate(self, inp: EngineInputs, env: EngineEnv | None = None) -> NativeResult:
        inp = self.inputs(env, inp)
        try:
            summary, rows = simulate_tier(inp, tier=self.tier)
        except SolverUnavailable as exc:
            return NativeResult(ok=False, error=str(exc))
        except Exception as exc:                                # noqa: BLE001
            return NativeResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        res = self.to_result(inp, summary, rows)
        res.engine = self.stamp(inp, summary).to_dict()
        return res

    def to_result(self, inp: EngineInputs, summary: dict, rows: list) -> NativeResult:
        res = to_native_result(inp, summary, rows)
        if self.tier == "fast":
            res.resource = ("wt-missile/" + str(inp.version or VERSION_28) + "+"
                            + (_backend_of(summary) or "python-legacy"))
        return res

    # --- 接入即验 -----------------------------------------------------

    def selftest(self, env: EngineEnv | None = None) -> SelfTestReport:
        """① vendor 身份；② 资源清单；③ 型号可算性；④ 最小工况真跑一次；
        ⑤ 声明能力 vs 实测。**不跑全程积分**（接入检查不该这么贵）。
        """
        sp = self.spec
        rep = SelfTestReport(name=sp.name, ok=True)
        rep.detail["spec"] = sp.to_dict()

        try:
            p = solver_file()
            got = file_sha256(p)
            rep.detail["solver_sha256"] = got
            rep.add("vendor 求解器存在且哈希一致", got == SOLVER_SHA256,
                    f"{p.name} {got[:16]}…（{p.stat().st_size if p.is_file() else 0} B）")
        except Exception as exc:                                # noqa: BLE001
            rep.add("vendor 求解器存在且哈希一致", False, f"{type(exc).__name__}: {exc}")
            return rep

        try:
            rt = resource_identity()
            rep.detail["resources"] = rt
            rep.add("资源清单可读", bool(rt.get("n_profiles")),
                    f"{rt.get('solver_model')} · {rt.get('n_profiles')} 个预设 · "
                    f"archive {(rt.get('resource_archive_sha256') or '')[:12]}…")
        except Exception as exc:                                # noqa: BLE001
            rep.add("资源清单可读", False, f"{type(exc).__name__}: {exc}")

        try:
            wt = load_solver()
            params, ident = wt.load_profile("cn_pl12", VERSION_28)
            reason = wt.unsupported(params)
            rep.detail["cn_pl12"] = {"resource": ident.get("resource"),
                                     "resource_sha256": ident.get("resource_sha256")}
            rep.add("默认型（cn_pl12）可算", reason is None, reason or "unsupported() 为空")
        except Exception as exc:                                # noqa: BLE001
            rep.add("默认型（cn_pl12）可算", False, f"{type(exc).__name__}: {exc}")

        # 输入映射自洽（最容易写错也最贵的一环）
        try:
            from . import io as io_mod                          # noqa: PLC0415
            inp = io_mod.inputs_from_case(
                io_mod.build_case(_selftest_cfg(), missile="cn_pl12"))
            rep.detail["inputs"] = {"dv_blk": inp.dv_blk, "bc_blk": inp.bc_blk,
                                    "thrust_scale": inp.thrust_scale,
                                    "cx_scale": inp.cx_scale, "dt": dt_for(inp)}
            rep.add("输入映射自洽（cn_pl12 标称）", not inp.check(),
                    f"ΔV_blk={inp.dv_blk:.2f} BC_blk={inp.bc_blk:.1f} "
                    f"×{inp.thrust_scale:.4f}/×{inp.cx_scale:.4f} dt={dt_for(inp):g} s")
        except Exception as exc:                                # noqa: BLE001
            rep.add("输入映射自洽（cn_pl12 标称）", False, f"{type(exc).__name__}: {exc}")

        # 最小工况真跑（0.5 s，只验证"能跑通 + 身份自洽"）
        try:
            from dataclasses import replace                  # noqa: PLC0415
            from . import io as io_mod                          # noqa: PLC0415
            inp = io_mod.inputs_from_case(
                io_mod.build_case(_selftest_cfg(), missile="cn_pl12"))
            probe = replace(inp, duration_s=0.5)
            summary, rows = simulate_tier(probe, tier=self.tier)
            backend = _backend_of(summary) or "python-standard"
            rep.detail["probe"] = {"steps": summary.get("steps"), "rows": len(rows),
                                   "steps_time_s": summary.get("time_s"),
                                   "backend": backend}
            rep.add("最小工况跑通", len(rows) > 1 and summary.get("steps", 0) > 1,
                    f"{summary.get('steps')} 步 / {len(rows)} 行 · backend={backend}")
            if self.tier == "fast":
                why = _fallback_of(summary)
                rep.detail["fast_fallback"] = why
                rep.add("fast 档后端已自报", True,
                        f"{backend}" + (f"（回退原因：{why}）" if why else "（C 内核生效）"))
        except Exception as exc:                                # noqa: BLE001
            rep.add("最小工况跑通", False, f"{type(exc).__name__}: {exc}")

        caps = sp.capabilities
        rep.add("声明 3D（6DOF）", caps.dims == "3d", f"dims={caps.dims}")
        rep.add("声明无向量化批量", caps.vectorized_batch is False,
                "求解器是标量循环，走多进程而非向量化")
        return rep


class StandardEngine(_WtEngine):
    """标准档：纯 Python 逐物理步（`python-game-6dof-2.59.0.28`）。"""

    tier = "standard"


class FastEngine(_WtEngine):
    """加速档：同一物理编译成 C 内核；缺编译器时求自身回退 `python-legacy`。"""

    tier = "fast"


def _selftest_cfg():
    """自检用的最小配置（默认 PL-12 标准弹 + 默认场景）。"""
    from ..config import MissileConfig                          # noqa: PLC0415
    return MissileConfig()

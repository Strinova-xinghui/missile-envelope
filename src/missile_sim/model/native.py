# -*- coding: utf-8 -*-
"""**模型层 2：Pro 计算层**——信源包原生仿真器的薄包装（"直接外包"）。

本层职责只有一件：`NativeCase` → `NativeResult`。它**不**解析 blk、不决定 ΔV/BC 怎么映射、
不做缓存、不做传播；这些分别属于输入层（`io.py`）与输出层（`record.py`/`cache.py`）。

包体与 ELF **永不入库**，只经 `WT_NATIVE_PKG` 定位；找不到就明确报错，不退回近似模型。
本模块不 import 任何 `missile_sim` 之外的原生依赖——原生包只在子进程里 import，
所以仓库单独克隆（无包）时其它模块仍可正常导入与自检。
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .constants import (  # noqa: F401  （对调用方保持同一组名字）
    CACHE_SCHEMA,
    CALC_VERSION,
    DEFAULT_CACHE,
    DEFAULT_PKG,
    DT_DEFAULT,
    DT_RANGE,
    ELF_REL,
    ELF_SHA256_28,
    ENV_PKG,
    HIT_EVENTS,
    NATIVE_PROFILES,
    ROOT,
    VERSION_28,
)

class ProRuntimeError(RuntimeError):
    """找不到/校验不过原生运行包（**不退回近似模型**）。"""


# --------------------------------------------------------------------- 运行时定位与校验


def resolve_pkg(pkg=None) -> Path:
    """定位原生运行包根目录。优先级：显式入参 > WT_NATIVE_PKG > 默认位置。"""
    raw = pkg or os.environ.get(ENV_PKG, "").strip() or DEFAULT_PKG
    p = Path(raw)
    if not p.is_dir():
        raise ProRuntimeError(
            f"找不到原生运行包：{p}\n"
            f"请设置 ${ENV_PKG}（解压后的 wt-missile-backend 目录），或放到 {DEFAULT_PKG}。\n"
            "包体不入库（见 AERO_PLAN §10.7）。"
        )
    core = p / "tools" / "simulator" / "core.py"
    if not core.exists():
        raise ProRuntimeError(f"{p} 不是有效的包根（找不到 tools/simulator/core.py）")
    return p


def verify_elf(pkg: Path, version: str = VERSION_28) -> dict:
    """校验 ELF 存在且 SHA-256 与版本匹配。返回身份块（供 provenance 用）。"""
    want = {VERSION_28: ELF_SHA256_28}.get(version)
    if want is None:
        raise ProRuntimeError(f"没有登记的 ELF 身份：version={version}")
    elf = Path(pkg) / ELF_REL
    if not elf.exists():
        raise ProRuntimeError(
            f"缺少 ELF：{elf}\n（包不完整，或包根指错了：{pkg}）"
        )
    h = hashlib.sha256()
    with open(elf, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != want:
        raise ProRuntimeError(f"ELF SHA-256 不符：期望 {want}，实际 {got}（{elf}）")
    return {"version": version, "elf_sha256": got, "elf_bytes": elf.stat().st_size}


def check_unicorn():
    """原生执行依赖 unicorn；缺失时给出可执行的修复命令。"""
    try:
        import unicorn  # noqa: F401
    except ImportError as exc:                          # pragma: no cover
        raise ProRuntimeError(
            "缺少 unicorn（原生机器码模拟器）。安装：pip install --user unicorn pyelftools"
        ) from exc


def runtime(pkg=None, version: str = VERSION_28, *, deep: bool = False) -> dict:
    """一次性把运行时信息收齐（路径 / ELF 身份 / 依赖）。`deep=True` 才做 ELF 全量哈希。"""
    p = resolve_pkg(pkg)
    check_unicorn()
    ident = verify_elf(p, version) if deep else {"version": version, "elf_sha256": ELF_SHA256_28}
    return {"pkg": str(p), **ident}


# --------------------------------------------------------------------- 单工况

@dataclass(frozen=True)
class NativeCase:
    """原生单工况输入（SI，全部外部可见）。

    **缩放口径**：外部给的是 `dv_target`（真空等效增速）与 `bc_target`（弹道系数），
    乘数由 `simulate_native` 用**该型自己的 profile** 现算：

        s        = dv_target / dv_blk
        cx_scale = m_dry / (bc_target · CxK_blk · S_ref_blk)

    这样 S_ref 只能来自 profile，不会再出现"用基准弹的参考面积去反解别的型号"这类错误。
    `dv_target=0`（默认）表示按该型标称参数跑（乘数 = 1）。
    """

    missile: str                       # 原生 profile 名，如 cn_pl12
    version: str = VERSION_28
    range_m: float = 50000.0
    alt_m: float = 10000.0
    target_alt_m: float | None = None  # None ⇒ 同高
    vm0: float = 300.0
    vt: float = -300.0
    dv_target: float = 0.0             # 0 ⇒ 标称（乘数 1）
    bc_target: float = 0.0             # 0 ⇒ 标称（乘数 1）
    dt: float = DT_DEFAULT
    duration_s: float = 200.0
    sample_period_s: float = 0.05
    observation_mode: str = "ideal"    # ideal = 与 Flash 同假设；locked = 带滤波/多径
    hit_radius_m: float = 0.0          # 0 ⇒ 只用原生近炸判定
    proximity_fuse: bool = True
    wind_m_s: tuple = (0.0, 0.0, 0.0)
    ground_height_m: float = 0.0
    target_maneuvers: tuple = ()       # ((time_s, (ax,ay,az)), ...)
    save_trajectory: bool = False      # 轨迹很占地方（单条 95%）：**默认不要**，且不参与缓存键

    @property
    def target_alt(self) -> float:
        return self.alt_m if self.target_alt_m is None else self.target_alt_m

    def key(self) -> str:
        """缓存键（不含与物理无关的采样设置）。"""
        blob = json.dumps([
            self.version, self.missile,
            round(self.dv_target, 6), round(self.bc_target, 6),
            self.range_m, self.alt_m, self.target_alt, self.vm0, self.vt,
            self.dt, self.observation_mode, self.hit_radius_m, self.proximity_fuse,
            list(self.wind_m_s), self.ground_height_m, [list(m) for m in self.target_maneuvers],
        ], sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


@dataclass
class NativeResult:
    """原生单工况结果（已归一成与 Flash 可比的口径）。"""

    ok: bool
    event: str = ""
    t_end: float = math.nan
    t_hit: float = math.nan
    hit: bool = False
    miss_distance_m: float = math.nan
    max_alt_m: float = math.nan
    v_impact: float = math.nan
    dv_measured: float = math.nan     # 燃尽时刻速度 − 初速（原生侧的"实际速度增量"）
    m_launch: float = math.nan
    m_dry: float = math.nan
    t_burnout: float = math.nan
    thrust_scale: float = math.nan     # 本次实际用的乘数（由 case.dv/bc_target 现算）
    cx_scale: float = math.nan
    dv_blk: float = math.nan           # 该型标称真空 ΔV / BC（乘数的参照）
    bc_blk: float = math.nan
    resource: str = ""                # "native" 或 "INJECTED il_derby.blkx"（注入须可追溯）
    samples: list = field(default_factory=list)   # 轨迹采样 [{t,x,y,v,mass,thrust,range}]（可选）
    error: str = ""
    cache_hit: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "NativeResult":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def to_dict(self) -> dict:
        return asdict(self)


def _import_native(pkg: Path):
    """在**当前进程**里把原生包挂上 sys.path 并 import。子进程专用。"""
    for p in (str(pkg / "tools"), str(pkg)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import simulator.core as core                      # noqa: PLC0415
    import simulator.resources as resources            # noqa: PLC0415
    return core, resources


# --- blk 注入：包内只有 9 型，缺的（Derby / R-Darter）用我们自己的 blkx 补 ---------
#
# 依据（见 results/native_injection_probe.json，已实证）：
#   * 原生参数全经内存块注入 ELF（CFG/GCFG/CTL/PROP/ENGINE），ELF 是 (状态, 参数块) 的纯函数；
#   * 唯一闸门是 `resources.load_profile` 的 manifest/SHA-256 校验，`scenario.validate` 不校验型号；
#   * 我们的 blkx 与原生 parse_blk 的叶子路径集合**完全相同（423/423）**，
#     共有 9 型在两者之间**逐值 0 差异** ⇒ Derby / R-Darter 的文件对 .28 ELF 结构完整。
# 注入**不改包内文件、不动 manifest**，且结果里必须记 `resource="INJECTED ..."`。
#
# "取 profile" 的实现属于**输入层**（`io.load_blk_profile`）。这里包一层函数、在调用时
# 才 import——既是函数级延迟导入（断开 io→native→io 环），也让打桩 `_external_profile`
# 仍然拦得住（写成 `from ... import` 的话，打桩会失效并静默去读真实文件）。
def _external_profile(native_name: str) -> dict | None:
    """兼容入口：转发到输入层的 `io.load_blk_profile`。"""
    from . import io as io_mod
    return io_mod.load_blk_profile(native_name)


def _patch_profile(p, updates: dict):
    """按 key 名就地改写 profile（原生 profile 是嵌套 dict；取第一个标量命中处）。"""
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


def _build_scenario(case: NativeCase, resources) -> dict:
    raw = {
        "schema_version": 1, "label": f"pro/{case.missile}",
        "missile": case.missile, "version": case.version,
        "duration_s": float(case.duration_s), "dt_s": float(case.dt),
        "sample_period_s": float(max(case.sample_period_s, case.dt)),
        "observation": {"mode": case.observation_mode},
        "launch": {"position_m": [0.0, case.alt_m, 0.0],
                   "velocity_m_s": [case.vm0, 0.0, 0.0]},
        "target": {"position_m": [case.range_m, case.target_alt, 0.0],
                   "velocity_m_s": [case.vt, 0.0, 0.0],
                   "collision_radius_m": 0.0},
        "wind_m_s": list(case.wind_m_s),
        "ground_height_m": float(case.ground_height_m),
        "proximity_fuse": bool(case.proximity_fuse),
    }
    if case.target_maneuvers:
        raw["target"]["maneuvers"] = [
            {"time_s": float(t), "acceleration_m_s2": [float(x) for x in a]}
            for t, a in case.target_maneuvers
        ]
    return raw


def _trajectory(samples: list) -> list:
    """原生采样 → 精简轨迹（弹道剖面图用；键名与 `record.SAMPLE_FIELDS` 对齐）。"""
    out = []
    for s in samples:
        out.append({
            "t": _f(s.get("time_s")),
            "x": _f(s.get("missile_x_m")),
            "y": _f(s.get("missile_y_m")),
            "v": _f(s.get("speed_m_s")),
            "mass": _f(s.get("mass_kg")),
            "thrust": _f(s.get("thrust_N")),
            "range": _f(s.get("range_m")),
        })
    return out


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def simulate_native(case: NativeCase, pkg=None) -> NativeResult:
    """跑一次原生全程积分。**必须在能 import 原生包的进程里调用**（见 `ProRunner`）。"""
    p = resolve_pkg(pkg)
    if not (DT_RANGE[0] - 1e-12 <= case.dt <= DT_RANGE[1] + 1e-12):
        return NativeResult(ok=False, error=f"dt={case.dt} 超出原生合法范围 {DT_RANGE}")
    core, resources = _import_native(p)
    if case.version != resources.VERSION:
        return NativeResult(ok=False, error=f"包版本 {resources.VERSION} ≠ 请求 {case.version}")
    raw = _build_scenario(case, resources)
    orig = core.load_profile
    injected = {"name": None}
    scales = {"s": 1.0, "cx": 1.0, "dv_blk": math.nan, "bc_blk": math.nan}

    def _apply(prof: dict) -> dict:
        """**用该 profile 自己**算 (推力乘数, CxK 乘数)，再施加。

        两个参考面积**不能混**（这是本项目踩过两次的坑）：
          * BC 与阻力用**迎面面积** `SD = π(d/2)²`；
          * 升力用 `SL = 0.3·d·L·wingAreaMult`（原生 `configure_properties` 的 area）。
        """
        from . import io as io_mod                      # 函数级延迟导入：断开 io→native→io 环
        d = float(prof["caliber"])
        sd = math.pi * (d / 2.0) ** 2              # 迎面面积：BC = m_dry/(CxK·SD)
        cxk = prof["CxK"]
        stages = io_mod.module_stages(prof)
        dry = stages[-1][1] if stages else float(prof["mass"])
        dv_blk = io_mod.vacuum_dv(stages)
        bc_blk = dry / (cxk * sd)
        s = 1.0 if not case.dv_target else io_mod.scale_for_dv(case.dv_target, dv_blk)
        cx = 1.0 if not case.bc_target else io_mod.cx_scale_for_bc(case.bc_target, dry, sd, cxk)
        scales.update({"s": s, "cx": cx, "dv_blk": dv_blk, "bc_blk": bc_blk})
        upd = {}
        if s != 1.0:
            for k in ("force", "force1"):
                v = prof.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    upd[k] = v * s
        if cx != 1.0:
            upd["CxK"] = cxk * cx
        return _patch_profile(prof, upd)

    def complete(name, version=resources.VERSION):
        """包内没有该型时，回落到我们的权威 blkx（注入）；有则照常。"""
        try:
            prof, ident = orig(name, version)
            return _apply(prof), ident
        except Exception:                               # noqa: BLE001  包内不支持该型
            ext = _external_profile(name)
            if ext is None:
                raise
            injected["name"] = name
            return (_apply(copy.deepcopy(ext)),
                    {"missile": name, "version": version,
                     "resource": f"INJECTED {name}.blkx"})

    core.load_profile = complete
    try:
        _scen, summary, samples = core.simulate(raw)
    except Exception as exc:                            # noqa: BLE001
        return NativeResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        core.load_profile = orig

    thrusts = [s["thrust_N"] for s in samples]
    speeds = [s["speed_m_s"] for s in samples]
    masses = [s["mass_kg"] for s in samples]
    powered = [i for i, t in enumerate(thrusts) if t and t > 0.0]
    i_burn = powered[-1] if powered else 0
    event = str(summary.get("terminal_event", ""))
    hit = event in HIT_EVENTS
    min_sep = float(summary.get("minimum_separation_until_event_m", math.nan))
    if hit and case.hit_radius_m > 0.0 and min_sep > case.hit_radius_m:
        hit = False                                     # 近炸半径外不算命中
    t_end = float(summary.get("time_s", math.nan))
    return NativeResult(
        ok=True, event=event, t_end=t_end, t_hit=(t_end if hit else math.nan), hit=hit,
        miss_distance_m=min_sep,
        max_alt_m=max(s["missile_y_m"] for s in samples) if samples else math.nan,
        v_impact=float(summary.get("final_speed_m_s", math.nan)),
        dv_measured=float(speeds[i_burn] - speeds[0]),
        m_launch=float(masses[0]), m_dry=float(min(masses)),
        t_burnout=float(samples[i_burn]["time_s"]),
        thrust_scale=scales["s"], cx_scale=scales["cx"],
        dv_blk=scales["dv_blk"], bc_blk=scales["bc_blk"],
        samples=(_trajectory(samples) if case.save_trajectory else []),
        resource=(f"INJECTED {injected['name']}.blkx" if injected["name"] else "native"),
    )

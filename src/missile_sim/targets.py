# -*- coding: utf-8 -*-
"""输入契约层：把「用户脑子里的交战想定」变成 `spec.Scene`，并在**提交求解器之前**
拦下不合法的输入。

三层职责（谁拥有什么，一目了然）：

    spec.py     `Scene` 数据结构 + `Scene.check()` —— **自洽性**（字段自己跟自己矛盾吗）
    targets.py  本文件 —— **求解器兼容性**（这个场景内核吃得下吗）+ 预置想定库
    solver.py   `Scene` → 求解器 dict（唯一接触面） + 真跑

**`check_compatible()` 与 `Scene.check()` 职责不同、都要能用**：

* `Scene.check()` 管字段自身的合法性（负距离、步长区间、观测枚举、速度符号、接触半径）。
  本函数**原样纳入**它的结论，所以 `check_compatible()` 为空 ⟹ `Scene.check()` 也为空。
* 本函数只叠加**只能在求解器层判断**的边界：数值有限性、高度域、俯仰域、步数规模、
  目标运动三选一（`maneuvers` / `samples` / `turn_rate`）与 `samples` 覆盖时域。
* 依据：`docs/SOLVER-API.md` §1（Scene 契约）与 §4（内核能力边界**实测**）。

本文件不 import `solver`（WebUI 只填表时不该加载 vendor）；只有 `check_missile()` 在
调用的那一刻才延迟加载。

表单约定（WebUI / CLI 共用）：字段名 = `Scene` 的字段名（英文），**角度用度、距离用米**，
速度一律是「标量 + 航向 + 俯仰」。坐标约定见 `spec.Scene`：x/z 水平、y 向上、零航向 +x、
正航向转 +z、俯仰抬头为正。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

from .spec import Scene

# --------------------------------------------------------------------- 求解器能力边界

#: 外壳输入域的高度上限 [m]。**不是内核实测出来的硬边界** —— 内核只吃向量，多少米都能算；
#: 这条是工程约束：平流层以内（40 km）覆盖一切现实交战想定，同时挡住"手滑多打一个零"。
#: 要算更高的工况，改这里。
ALT_MAX_M = 40_000.0

#: 速度俯仰的允许范围 [°]。超过 ±90° 时 `cos(pitch)` 变号、航向被悄悄翻转 180°，
#: 「标量 + 航向 + 俯仰」这套表达已经退化（想给反向速度就该改航向 180°，而不是俯仰 130°）。
PITCH_LIMIT_DEG = 90.0

#: 单次求解的物理步数上限（`duration_s / dt_s`）。默认工况 150 / (1/48) = 7200 步；
#: 1e6 步在 `standard` 档要跑几十分钟，那是"提交前就该拦下"的量级（默认步长下相当于 5.8 h 时域）。
MAX_STEPS = 1_000_000

#: 内核原生目标运动能力，**三选一互斥**（`maneuvers` / `samples` / `turn_rate`）。
MOTION_KEYS = ("maneuvers", "samples", "turn_rate")


# --------------------------------------------------------------------- 预置想定


@dataclass(frozen=True)
class _Preset:
    summary: str
    scene: Scene


#: 预置想定库。**全部是直飞**（用户已拍板跳过自定义敌机轨迹）：敌机只给航向与俯仰，
#: 不给 `maneuvers` / `samples`。顺序即 `presets()` 的展示顺序。
_PRESETS: dict = {
    "head_on": _Preset(
        "典型迎头拦截：50 km 同高 10 km，双方 300 m/s 迎面（金标工况，PL-12 约 45.2 s 命中）",
        Scene(range_m=50_000.0, alt_m=10_000.0, vm0=300.0, launch_heading_deg=0.0,
              target_speed_ms=300.0, target_heading_deg=180.0)),
    "tail_chase": _Preset(
        "尾追：20 km 同高 9 km，载机 400 m/s 追 220 m/s 的同向敌机",
        Scene(range_m=20_000.0, alt_m=9_000.0, vm0=400.0, launch_heading_deg=0.0,
              target_speed_ms=220.0, target_heading_deg=0.0)),
    "beam_90": _Preset(
        "侧向 90° 拦截：敌机在正侧方 25 km（方位 90°）横穿，双方 300 m/s",
        Scene(range_m=25_000.0, alt_m=8_000.0, target_bearing_deg=90.0,
              vm0=300.0, launch_heading_deg=0.0,
              target_speed_ms=300.0, target_heading_deg=0.0)),
    "target_climb": _Preset(
        "敌机爬升：45 km 迎面，敌机在 15 km 高、以 15° 爬升 280 m/s（初始高差 +6 km）",
        Scene(range_m=45_000.0, alt_m=9_000.0, target_alt_m=15_000.0,
              vm0=300.0, launch_heading_deg=0.0,
              target_speed_ms=280.0, target_heading_deg=180.0, target_pitch_deg=15.0)),
    "target_dive": _Preset(
        "敌机俯冲：40 km 迎面，敌机从 11 km 以 -20° 俯冲 320 m/s（载机 10 km）",
        Scene(range_m=40_000.0, alt_m=10_000.0, target_alt_m=11_000.0,
              vm0=300.0, launch_heading_deg=0.0,
              target_speed_ms=320.0, target_heading_deg=180.0, target_pitch_deg=-20.0)),
    "altitude_gap": _Preset(
        "带高度差的拦截：40 km 水平距离，载机 5 km 打 12 km 的敌机（高差 +7 km）",
        Scene(range_m=40_000.0, alt_m=5_000.0, target_alt_m=12_000.0,
              vm0=320.0, launch_heading_deg=0.0,
              target_speed_ms=280.0, target_heading_deg=180.0)),
}


def presets() -> dict:
    """预置想定：名字 → 一行中文描述（顺序即展示顺序）。"""
    return {name: p.summary for name, p in _PRESETS.items()}


def scene_of_preset(name: str, **overrides) -> Scene:
    """取预置想定，`overrides` 里**出现过的字段一律生效**（包括显式给 `None`）。

    与 `build_scene()` 的差别：这里是 Python 调用，给了就是要改；表单里的空值则是
    "没填"，走基底值（见 `build_scene()` 的 docstring）。字符串数字会被转成数字。
    """
    key = "" if name is None else str(name).strip()
    if key not in _PRESETS:
        raise KeyError(f"没有这个预置想定：{name!r}；可用：{', '.join(_PRESETS)}")
    unknown = sorted(k for k in overrides if k not in _SCENE_FIELDS)
    if unknown:
        raise TypeError(f"不认识的场景字段：{', '.join(unknown)}；"
                        f"可用：{', '.join(_SCENE_FIELDS)}")
    clean = {}
    for k, v in overrides.items():
        if isinstance(v, str):
            value = _form_value(k, v)
            if value is _UNSET:
                raise ValueError(f"{k} 不能是空字符串（想恢复默认就整个字段别给）")
            clean[k] = value
        else:
            clean[k] = v
    base = _PRESETS[key].scene
    return replace(base, **clean) if clean else base


# --------------------------------------------------------------------- 表单字段

_UNSET = object()                       #: 哨兵："这一项没填，走基底值"

_FORM_FIELDS = tuple(f.name for f in fields(Scene))
_FORM_KEYS = _FORM_FIELDS + ("preset",)
_SCENE_FIELDS = _FORM_FIELDS

#: 需要"有限数"的字段（`observation` / `proximity_fuse` / `maneuvers` / `wind_m_s` 另有检查）
_FLOAT_FIELDS = tuple(f.name for f in fields(Scene)
                      if f.name not in ("observation", "proximity_fuse", "maneuvers",
                                        "wind_m_s"))

_BOOL_TRUE = ("1", "true", "yes", "on", "y", "t", "是", "开")
_BOOL_FALSE = ("0", "false", "no", "off", "n", "f", "否", "关")
_NONE_WORDS = ("none", "null", "nil", "-", "--", "同高")


def _build_default_form() -> dict:
    """从 `Scene()` 派生表单默认值 —— 字段默认值只有一个来源，不会漂移。"""
    scene = Scene()
    form = {name: getattr(scene, name) for name in _FORM_FIELDS}
    form.pop("maneuvers", None)        # 内核原生能力，本轮 UI 不暴露（留接口）
    return {"preset": "", **form}


#: 表单默认值（WebUI 直接用）。键 = `Scene` 字段名 + `preset`（空串 = 不用预置）。
DEFAULT_FORM: dict = _build_default_form()


def preset_form(name: str) -> dict:
    """预置想定的**表单初值**（含 `preset` 键），"选预置 → 自动填表"直接用。

    回灌 `build_scene(preset_form(name))` 会得到同一个 `Scene`。
    """
    scene = scene_of_preset(name)
    form = dict(DEFAULT_FORM)
    for key in form:
        if key != "preset":
            form[key] = getattr(scene, key)
    form["preset"] = "" if name is None else str(name).strip()
    return form


def _float_of(name: str, text) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 需要数字，收到 {text!r}") from None


def _bool_of(name: str, text: str) -> bool:
    low = str(text).strip().lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    raise ValueError(f"{name} 需要布尔值（true/false、1/0、on/off），收到 {text!r}")


def _wind_of(text: str) -> tuple:
    parts = [p for p in (str(text).replace("，", ",").replace("[", " ").replace("]", " ")
                         .replace(",", " ").split()) if p]
    if len(parts) != 3:
        raise ValueError(f"wind_m_s 要写成三个数（世界坐标 x,y,z，如 0,0,0），收到 {text!r}")
    return tuple(_float_of("wind_m_s", p) for p in parts)


def _form_value(name: str, raw):
    """表单原始值 → 字段值。返回 `_UNSET` = "没填"（走基底值）。

    HTTP 表单来的全是字符串，所以这里统一做一次强转；转不动就**报错**，不静默吞。
    """
    if raw is None:
        return _UNSET
    if isinstance(raw, bool):
        # `bool` 是 `int` 的子类：数字字段收到 True/False 别悄悄变成 1/0
        if name == "proximity_fuse":
            return raw
        raise ValueError(f"{name} 是数字字段，收到布尔值 {raw!r}")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return _UNSET
        low = text.lower()
        if name == "observation":
            return low
        if name == "proximity_fuse":
            return _bool_of(name, low)
        if name == "target_alt_m" and low in _NONE_WORDS:
            return None                                   # 显式"与发射同高"
        if name == "wind_m_s":
            return _wind_of(text)
        if name == "maneuvers":
            raise ValueError("maneuvers 只接受 [(time_s, (ax, ay, az)), …] 序列，"
                             "不接受字符串（本轮 UI 不暴露）")
        return _float_of(name, text)
    return raw


def _is_default(name: str, value) -> bool:
    """这个值是不是就等于 `DEFAULT_FORM` 里的默认值？"""
    sentinel = DEFAULT_FORM.get(name, _UNSET)
    if sentinel is _UNSET or sentinel is None:
        return False
    if isinstance(sentinel, tuple):
        try:
            return tuple(value) == sentinel
        except TypeError:
            return False
    if isinstance(sentinel, float):
        try:
            return math.isclose(float(value), sentinel, rel_tol=1e-12, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    return value == sentinel


def build_scene(form: dict) -> Scene:
    """表单字典 → `Scene`。**未知键报错，不静默吞。**

    取值规则（按优先级）：

    1. `form` 里键不认识 ⟹ `ValueError`（拼错的字段名会被当场指出）。
    2. `form["preset"]` 非空 ⟹ 以该预置为基底，否则以 `Scene()` 为基底。
    3. 键缺失 / `None` / 空串 ⟹ **没填**，用基底值。
    4. `preset` 非空，且某一项**恰好等于 `DEFAULT_FORM` 的默认值** ⟹ 视为"用户没动过
       这个框"，仍用预置值。这样 WebUI 可以放心地把整张表单（含默认值）提交上来，
       预置不会被默认值悄悄抹掉。
    5. `target_alt_m` 例外：它没有"默认值"可言（`None` 就是"与发射同高"这个合法值），
       所以照第 3 条走；想显式恢复同高，填 `"none"`。

    字符串数字会被强转（HTTP 表单全是字符串）；转不动就报错。
    """
    if form is None:
        form = {}
    if not isinstance(form, dict):
        raise TypeError(f"build_scene() 只吃字典，收到 {type(form).__name__}")
    unknown = sorted(k for k in form if k not in _FORM_KEYS)
    if unknown:
        raise ValueError(f"表单里有不认识的字段：{', '.join(unknown)}；"
                         f"可用：{', '.join(_FORM_KEYS)}")

    preset = form.get("preset")
    preset = "" if preset is None else str(preset).strip()
    base = scene_of_preset(preset) if preset else Scene()

    over = {}
    for key, raw in form.items():
        if key == "preset":
            continue
        value = _form_value(key, raw)
        if value is _UNSET:
            continue
        if preset and key != "target_alt_m" and _is_default(key, value):
            continue
        over[key] = value
    return replace(base, **over) if over else base


# --------------------------------------------------------------------- 兼容性校验


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _attr(obj, name, default=None):
    """安全取属性：属性不存在或自己抛异常（如 `target_alt` 撞上坏类型）时给 default。"""
    try:
        return getattr(obj, name, default)
    except Exception:                                          # noqa: BLE001
        return default


def _motion_problems(scene: Scene) -> list:
    """目标运动：三选一互斥 + `samples` 的硬约束（`SOLVER-API.md` §4 实测）。

    `spec.Scene` 目前只带 `maneuvers`；`samples` / `turn_rate` 用 `getattr` 探测 ——
    哪天 Lead 在 `Scene` 上补了字段，这里的校验自动生效，不用改。
    """
    out = []
    maneuvers = _attr(scene, "maneuvers") or ()
    samples = _attr(scene, "samples") or ()
    turn = _attr(scene, "turn_rate")

    used = []
    if maneuvers:
        used.append("maneuvers")
    if samples:
        used.append("samples")
    if turn is not None and _finite(turn) and abs(float(turn)) > 0.0:
        used.append("turn_rate")
    if len(used) > 1:
        out.append("目标运动三选一互斥（内核原文报错 'Invalid constant turn rate or "
                   f"conflicting target motion'），同时给了：{'、'.join(used)}")

    last_t = None
    for i, item in enumerate(maneuvers):
        try:
            t, acc = item
            acc = tuple(float(x) for x in acc)
        except Exception:                                      # noqa: BLE001
            out.append(f"maneuvers[{i}] 要写成 (time_s, (ax, ay, az))，收到 {item!r}")
            continue
        if not _finite(t):
            out.append(f"maneuvers[{i}] 的时间不是有限数：{t!r}")
        elif last_t is not None and float(t) <= last_t:
            out.append(f"maneuvers 的时间必须严格递增：第 {i} 条 {float(t):g} s "
                       f"<= 上一条 {last_t:g} s")
        else:
            last_t = float(t)
        if len(acc) != 3 or not all(_finite(x) for x in acc):
            out.append(f"maneuvers[{i}] 的加速度要是三个有限数，收到 {item[1]!r}")

    if samples:
        if len(samples) < 2:
            out.append("samples 至少两条（内核原文 'Recorded target needs at least "
                       f"two samples and no maneuvers'），收到 {len(samples)} 条")
        times = []
        for i, s in enumerate(samples):
            if not isinstance(s, dict):
                out.append(f"samples[{i}] 要是 {{time_s, position_m, velocity_m_s}} 字典，"
                           f"收到 {type(s).__name__}")
                continue
            t = s.get("time_s")
            if not _finite(t):
                out.append(f"samples[{i}].time_s 不是有限数：{t!r}")
            else:
                times.append(float(t))
            for key in ("position_m", "velocity_m_s"):
                v = s.get(key)
                try:
                    vv = tuple(float(x) for x in v)
                except (TypeError, ValueError):
                    out.append(f"samples[{i}].{key} 要是三个数，收到 {v!r}")
                    continue
                if len(vv) != 3 or not all(_finite(x) for x in vv):
                    out.append(f"samples[{i}].{key} 要是三个有限数，收到 {v!r}")
        if times:
            if abs(times[0]) > 1e-9:
                out.append(f"samples 必须从 t=0 起（内核不做外推），首条是 {times[0]:g} s")
            if any(b <= a for a, b in zip(times, times[1:])):
                out.append("samples 的时间必须严格递增")
            dur = _attr(scene, "duration_s")
            if _finite(dur) and times[-1] < float(dur) - 1e-9:
                out.append(f"samples 必须覆盖到 duration_s={float(dur):g} s"
                           "（内核原文 'Recorded target must cover time zero through "
                           f"duration_s; no extrapolation'），只给到 {times[-1]:g} s")

    if turn is not None and not _finite(turn):
        out.append(f"turn_rate 必须是有限数 [rad/s]，收到 {turn!r}")
    return out


def check_compatible(scene: Scene) -> list:
    """**提交求解器之前**的兼容性校验。返回问题清单（空 = 可以提交）。

    第一段是 `Scene.check()` 的结论（原样纳入，措辞归 `spec` 所有），后面几段是
    求解器层独有的边界：数值有限性、风速三元组、高度域、俯仰域、步数规模、目标运动。
    **不抛异常**：坏类型也会变成一条消息，而不是把异常扔给 WebUI。
    """
    if not isinstance(scene, Scene):
        return [f"check_compatible() 只吃 spec.Scene，收到 {type(scene).__name__}"]

    bad = []
    try:
        bad.extend(scene.check())
    except Exception as exc:                                   # noqa: BLE001
        bad.append(f"场景字段类型不对，Scene.check() 自己就抛了："
                   f"{type(exc).__name__}: {exc}")

    # —— 有限性：nan / inf 会被内核一路算进结果，甚至让积分不终止 ——
    for name in _FLOAT_FIELDS:
        value = _attr(scene, name)
        if value is None:                                      # target_alt_m=None 合法
            continue
        if not _finite(value):
            bad.append(f"{name} 必须是有限数，收到 {value!r}")

    # —— 风速：必须是世界坐标三元组 ——
    wind = _attr(scene, "wind_m_s")
    if wind is not None:
        try:
            ws = tuple(float(x) for x in wind)
        except (TypeError, ValueError):
            bad.append(f"wind_m_s 要是三个数（世界坐标 x/y/z），收到 {wind!r}")
        else:
            if len(ws) != 3:
                bad.append(f"wind_m_s 要是三个数（世界坐标 x/y/z），收到 {len(ws)} 个：{wind!r}")
            elif not all(_finite(x) for x in ws):
                bad.append(f"wind_m_s 要是有限数，收到 {wind!r}")

    # —— 高度域：地面以下会被内核立刻判 ground；过高属于外壳输入域 ——
    ground = _attr(scene, "ground_height_m")
    alt = _attr(scene, "alt_m")
    target_alt = _attr(scene, "target_alt")                    # None 已折成 alt_m
    if _finite(ground):
        g = float(ground)
        if _finite(alt):
            if float(alt) < g:
                bad.append(f"发射高度 {float(alt):g} m 低于地面 {g:g} m："
                           "内核会在 t=0 就判 ground 终止")
            elif float(alt) > ALT_MAX_M:
                bad.append(f"发射高度 {float(alt):g} m 超出外壳输入域上限 "
                           f"{ALT_MAX_M:g} m（要算更高就调 targets.ALT_MAX_M）")
        if _finite(target_alt):
            if float(target_alt) < g:
                bad.append(f"目标高度 {float(target_alt):g} m 低于地面 {g:g} m")
            elif float(target_alt) > ALT_MAX_M:
                bad.append(f"目标高度 {float(target_alt):g} m 超出外壳输入域上限 "
                           f"{ALT_MAX_M:g} m")

    # —— 俯仰域：超过 ±90° 时 cos(pitch) 变号，航向被悄悄翻转 ——
    for name in ("launch_pitch_deg", "target_pitch_deg"):
        v = _attr(scene, name)
        if _finite(v) and abs(float(v)) > PITCH_LIMIT_DEG:
            bad.append(f"{name}={float(v):g}° 超出 ±{PITCH_LIMIT_DEG:g}°：俯仰一过 90°，"
                       "水平分量变号、航向被翻转 180°，「标量 + 航向 + 俯仰」这套表达"
                       "已经退化（想给反向速度请改航向）")

    # —— 步数规模：dt 拉到最小、duration 又很长时，单次求解会跑成"服务器卡死" ——
    dur = _attr(scene, "duration_s")
    dt = _attr(scene, "dt_s")
    if _finite(dur) and _finite(dt) and float(dt) > 0.0 and float(dur) > 0.0:
        steps = float(dur) / float(dt)
        if steps > MAX_STEPS:
            bad.append(f"duration_s / dt_s = {steps:,.0f} 步，超过单次求解上限 "
                       f"{MAX_STEPS:,} 步（放大 dt_s 或缩短 duration_s；"
                       "要改就调 targets.MAX_STEPS）")

    bad.extend(_motion_problems(scene))
    return bad


def check_missile(native_name: str) -> list:
    """弹型是否被内核接受（§4：不支持的型号是**硬拒绝**，不做近似替代）。空 = 可算。

    只有这个函数会碰 vendor（延迟 import）—— WebUI 在"提交"那一刻调它一次即可。
    """
    name = "" if native_name is None else str(native_name).strip()
    if not name:
        return ["弹型不能为空"]
    from . import solver                                       # 延迟加载，保持本模块轻量
    try:
        reason = solver.supported(name)
    except solver.SolverUnavailable as exc:
        return [f"求解器不可用：{exc}"]
    except Exception as exc:                                   # noqa: BLE001
        return [f"弹型 {name!r} 读不出来：{type(exc).__name__}: {exc}"]
    return [f"内核不接受弹型 {name!r}：{reason}"] if reason else []


# --------------------------------------------------------------------- 文案


def describe_scene(scene: Scene) -> str:
    """一行中文摘要（可直接进图副标题）。

    与 `Scene.describe()` 同构、措辞同源：`Scene.describe()` 面向日志与 manifest
    （带斜距、带 `observation`），这里面向图副标题 —— 高度用 km、把载机与敌机的
    航向/俯仰都写全（`Scene.describe()` 不写载机俯仰）。
    """
    kind = "迎头" if scene.head_on else "尾追/侧向"
    dh = scene.target_alt - scene.alt_m
    if abs(dh) < 1.0:
        alt = f"高度 {scene.alt_m / 1000:.1f} km（同高）"
    else:
        alt = (f"高度 {scene.alt_m / 1000:.1f}→{scene.target_alt / 1000:.1f} km"
               f"（高差 {dh / 1000:+.1f} km）")
    return (f"{scene.range_m / 1000:.0f} km 水平距离 {kind} · {alt} · "
            f"载机 {scene.vm0:.0f} m/s 航向 {scene.launch_heading_deg:g}° "
            f"俯仰 {scene.launch_pitch_deg:g}° · "
            f"敌机 {scene.target_speed_ms:.0f} m/s 航向 {scene.target_heading_deg:g}° "
            f"俯仰 {scene.target_pitch_deg:g}° · 观测 {scene.observation}")

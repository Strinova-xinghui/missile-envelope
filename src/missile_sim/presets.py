# -*- coding: utf-8 -*-
"""**共享预设层**：图1–图4 共用的一套「环境 + 基准弹 + 参考工况」。

用户 2026-10-02 的架构拍板（v4）：四张图必须吃**同一套**环境预设与基准弹，
否则"同一张图上的同一根轴"在四页里可以是不同物理量。这一层就是那个唯一出处。

## 分了三层，各管各的（边界不是随手划的）

| 层 | 放什么 | 为什么 |
| --- | --- | --- |
| `configs/presets.json`（本模块读） | **环境**（`Scene` 的全部自由量）+ **基准弹** + **参考工况**（`ref_alt_m` / `ref_speed_ms` / `n_ref`）+ **等时线/面的层定义**（`iso_step` / `dv_pin`）+ `tier` | 这些量一旦两套，两张图就不可比；`n*` / R 的参考工况、等时线的整秒层级都属于"口径" |
| `configs/web_default.json`（`webui` 读） | `host` / `port` / `poll_ms` / `max_concurrent_jobs` / `jobs` / `cache` / `formats` / `tag` / `*_dir` / `missiles` | 机器与输出层：与物理无关，也不该进缓存键或产物 |
| 各图的 `*Request` | 只有"这张图画多细 / 扫多宽"（步长、点数、范围、`with_iso`、想定参数…） | 混进预设会让"改图3"顺手改掉图1 |

## 优先级：**显式参数 > 预设 > 字段默认**

`build()` 是唯一入口；`presets.json` 里**不认识的键一律报错**（`ValueError`），
不做宽容修正 —— 一个拼错的键如果被静默忽略，图上看起来会完全正常
（仓库里已经吃过两次这种亏，见 `AGENTS.md` 的「静默失败高危区」）。

## 不变量（`tests/test_presets.py` 钉住）

1. **只换来源、不改数值**：同一组显式参数下，`build(cls, …)` 与手工 `cls(…)` 的
   字段逐项相等（四个 Request 各一条）。
2. **文件真的被读**：改一份临时 `presets.json`（在 `tmp_path` 里），请求随之改变。
3. **缓存键的边界**：只改 `n_ref` / `iso_step`（不碰求解器）⇒ `engine.cache_key()` 不变；
   改 `Scene` 的任一自由量或 `tier` ⇒ 变。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields, replace
from pathlib import Path

from . import spec
from .spec import Scene

#: 预设文件里允许出现的顶层键（其余一律 `ValueError`）。
TOP_KEYS = frozenset({"label", "scene", "standard", "tier", "n_ref", "ref_alt_m",
                      "ref_speed_ms", "iso_step", "dv_pin"})
#: `Scene` 里**不许**由预设给的键：目标运动由各图的想定编译器写（图4/图3 会显式检查留空）。
SCENE_FORBIDDEN = frozenset({"maneuvers"})
#: `Scene` 里要按数字收的字段（`target_alt_m` / `wind_m_s` 另处理）。
_SCENE_FLOAT = ("range_m", "alt_m", "target_bearing_deg", "vm0", "launch_heading_deg",
                "launch_pitch_deg", "target_speed_ms", "target_heading_deg",
                "target_pitch_deg", "duration_s", "dt_s", "ground_height_m",
                "hit_radius_m")
_SCENE_INT = ()
_SCENE_BOOL = ("proximity_fuse",)


#: 预设键 → **各图请求里**的同义字段名（第一个命中的就用）。
#: ⚠ 图2 的参考工况历史上叫 `alt_m` / `speed_ms`（`BgRequest` 自己的字段名），
#: 而图3 那一对叫 `ref_alt_m` / `ref_speed_ms`；预设层只认一个名字（`ref_*`），
#: 由这张表折到各自的字段上 —— 这样"参考工况只有一套定义"才是真的。
FIELD_ALIASES: dict = {
    "ref_alt_m": ("ref_alt_m", "alt_m"),
    "ref_speed_ms": ("ref_speed_ms", "speed_ms"),
}


def path_of(path=None) -> Path:
    return Path(path) if path is not None else spec.ENV_PRESET_PATH


@dataclass(frozen=True)
class Preset:
    """一份具名预设。`scene` 是 `Scene` 字段名的字典（JSON 友好，且不含 `maneuvers`）。"""

    name: str
    label: str = ""
    scene: dict = None                                  # type: ignore[assignment]
    standard: str = spec.DEFAULT_MISSILE
    tier: str = "fast"
    n_ref: float = 20.0
    ref_alt_m: float = 10_000.0
    ref_speed_ms: float = 800.0
    iso_step: float = 1.0
    dv_pin: float | None = None

    def __post_init__(self):
        if self.scene is None:
            object.__setattr__(self, "scene", {})
        if not isinstance(self.scene, dict):
            raise ValueError(f"预设 {self.name!r} 的 scene 必须是对象，收到 {type(self.scene).__name__}")
        if self.tier not in spec.TIERS:
            raise ValueError(f"预设 {self.name!r} 的 tier 只能是 {' / '.join(spec.TIERS)}，收到 {self.tier!r}")
        if not (float(self.iso_step) > 0):
            raise ValueError(f"预设 {self.name!r} 的 iso_step 必须为正，收到 {self.iso_step!r}")
        if self.dv_pin is not None and not (float(self.dv_pin) > 0):
            raise ValueError(f"预设 {self.name!r} 的 dv_pin 必须为正，收到 {self.dv_pin!r}")
        for key, val in (("n_ref", self.n_ref), ("ref_alt_m", self.ref_alt_m),
                         ("ref_speed_ms", self.ref_speed_ms)):
            if not math.isfinite(float(val)):
                raise ValueError(f"预设 {self.name!r} 的 {key} 必须是有限数，收到 {val!r}")
        if not (float(self.ref_speed_ms) > 0):
            raise ValueError(f"预设 {self.name!r} 的 ref_speed_ms 必须为正，收到 {self.ref_speed_ms!r}")

    # ---------------------------------------------------------------- 出口
    def scene_obj(self) -> Scene:
        """预设 → `Scene`（`maneuvers` 恒空；不给的字段用 `Scene` 自己的默认值）。"""
        return Scene(**dict(self.scene))

    def request_fields(self) -> dict:
        """预设里**与请求同形**的那几个键（供 `build()` 铺底；名称与 `*Request` 字段一致）。"""
        return {"standard": self.standard, "tier": self.tier, "n_ref": self.n_ref,
                "ref_alt_m": self.ref_alt_m, "ref_speed_ms": self.ref_speed_ms,
                "iso_step": self.iso_step, "dv_pin": self.dv_pin}

    def as_dict(self) -> dict:
        out = {"label": self.label, "scene": dict(self.scene), "standard": self.standard,
               "tier": self.tier, "n_ref": self.n_ref, "ref_alt_m": self.ref_alt_m,
               "ref_speed_ms": self.ref_speed_ms, "iso_step": self.iso_step,
               "dv_pin": self.dv_pin}
        return out


def _coerce_scene(raw: dict, *, name: str) -> dict:
    """校验并折成 `Scene` 能吃的一层（未知键、禁键、类型不对都当场报错）。"""
    known = {f.name for f in fields(Scene)}
    out = {}
    for key, val in raw.items():
        if key in SCENE_FORBIDDEN:
            raise ValueError(f"预设 {name!r} 的 scene.{key} 不许给：目标运动由各图的想定编译器写")
        if key not in known:
            raise ValueError(f"预设 {name!r} 的 scene 里有个不认识的键 {key!r}"
                             f"（Scene 的键：{' / '.join(sorted(known - SCENE_FORBIDDEN))}）")
        if key == "target_alt_m":
            out[key] = None if val is None else float(val)
        elif key == "wind_m_s":
            if val is None:
                out[key] = (0.0, 0.0, 0.0)
            elif isinstance(val, (list, tuple)) and len(val) == 3:
                out[key] = tuple(float(v) for v in val)
            else:
                raise ValueError(f"预设 {name!r} 的 wind_m_s 要三个数，收到 {val!r}")
        elif key in _SCENE_BOOL:
            if not isinstance(val, bool):
                raise ValueError(f"预设 {name!r} 的 scene.{key} 要布尔，收到 {val!r}")
            out[key] = val
        elif key in _SCENE_FLOAT:
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                raise ValueError(f"预设 {name!r} 的 scene.{key} 要数字，收到 {val!r}") from None
        else:                                     # observation 这类枚举字符串
            if not isinstance(val, str):
                raise ValueError(f"预设 {name!r} 的 scene.{key} 要字符串，收到 {val!r}")
            out[key] = val
    if "observation" in out and out["observation"] not in spec.OBSERVATIONS:
        raise ValueError(f"预设 {name!r} 的 observation 只能是 {' / '.join(spec.OBSERVATIONS)}"
                         f"，收到 {out['observation']!r}")
    return out


def _one(name: str, raw: dict) -> Preset:
    if not isinstance(raw, dict):
        raise ValueError(f"预设 {name!r} 必须是一个对象")
    unknown = sorted(set(raw) - TOP_KEYS)
    if unknown:
        raise ValueError(f"预设 {name!r} 里有不认识的键 {unknown}"
                         f"（允许：{' / '.join(sorted(TOP_KEYS))}）")
    scene = _coerce_scene(dict(raw.get("scene") or {}), name=name)
    return Preset(name=name, label=str(raw.get("label") or ""), scene=scene,
                  standard=str(raw.get("standard") or spec.DEFAULT_MISSILE),
                  tier=str(raw.get("tier") or "fast"),
                  n_ref=float(raw.get("n_ref", 20.0)),
                  ref_alt_m=float(raw.get("ref_alt_m", 10_000.0)),
                  ref_speed_ms=float(raw.get("ref_speed_ms", 800.0)),
                  iso_step=float(raw.get("iso_step", 1.0)),
                  dv_pin=(None if raw.get("dv_pin") is None else float(raw["dv_pin"])))


_CACHE: dict = {}


def load(path=None) -> dict:
    """读预设文件 → `{name: Preset}`。按 (路径, mtime, 大小) 缓存（测试改文件能立刻生效）。"""
    p = path_of(path)
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError as exc:
        raise FileNotFoundError(f"预设文件读不到：{p}（{exc}）") from exc
    hit = _CACHE.get("key")
    if hit is not None and hit[0] == key:
        return _CACHE["data"]
    raw = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"预设文件 {p} 的顶层必须是一个非空对象")
    # 与 `configs/web_default.json` 同一套约定：**下划线开头的是注释**，解析时跳过。
    # 除了这种注释，顶层键一律当预设名（名字不认识时 `resolve()` 会当场报错）。
    body = {k: v for k, v in raw.items() if not str(k).startswith("_")}
    if not body:
        raise ValueError(f"预设文件 {p} 里一份预设都没有（只有注释？）")
    data = {str(name): _one(str(name), item) for name, item in body.items()}
    _CACHE["key"] = (key,)
    _CACHE["data"] = data
    return data


def names(path=None) -> tuple:
    return tuple(load(path))


def resolve(name=None, path=None) -> Preset:
    """具名 → 预设。名字不认识就报错（不悄悄退回 default）。"""
    key = str(name or spec.DEFAULT_ENV_PRESET)
    table = load(path)
    if key not in table:
        raise ValueError(f"没有这个预设：{key!r}（有：{' / '.join(table)}）")
    return table[key]


def build(cls, *, env_preset=None, scene=None, path=None, **explicit):
    """预设 + 显式覆盖 → 请求对象。**优先级：explicit > 预设 > 字段默认**。

    `scene` 给的是"要覆盖的环境字段"（`None` 表示不覆盖）；`explicit` 里值为 `None` 的键
    一律跳过（"没给"与"给成 None"在这里同义，与 CLI 的 `None = 未指定` 约定一致）。
    """
    pre = resolve(env_preset, path)
    allowed = {f.name for f in fields(cls)}
    vals: dict = {}
    for key, val in pre.request_fields().items():
        if val is None:
            continue
        for name in FIELD_ALIASES.get(key, (key,)):
            if name in allowed:
                vals[name] = val
                break
    base = pre.scene_obj()
    if scene:
        bad = sorted(set(scene) - {f.name for f in fields(Scene)})
        if bad:
            raise ValueError(f"scene 覆盖里有不认识的键：{bad}")
        base = replace(base, **dict(scene))
    if "scene" in allowed:
        vals["scene"] = base
    if "env_preset" in allowed:
        vals["env_preset"] = pre.name
    for key, val in explicit.items():
        if key not in allowed:
            raise ValueError(f"{cls.__name__} 没有字段 {key!r}")
        if val is not None:
            vals[key] = val
    return cls(**vals)


def resolved_scene(env_preset=None, scene=None, path=None) -> Scene:
    """只要环境那一层（`webui.build_scene_from_form()` 用它铺底）。"""
    pre = resolve(env_preset, path)
    base = pre.scene_obj()
    if scene:
        base = replace(base, **dict(scene))
    return base

# -*- coding: utf-8 -*-
"""共享预设层的判据（v4）：图1–图4 共用一套「环境 + 基准弹 + 参考工况」。

这一层最容易出的两种错，都是"看起来一切正常"的那种，所以每条判据都对着一个具体的反例：

| 反例 | 会看到什么 | 判据 |
| --- | --- | --- |
| 预设文件是**装饰性**的（读了但没用 / 没读） | 四个页面各说各的环境，数值"差不多" | `test_preset_file_is_actually_read` |
| 拼错的键被静默忽略 | 改了半天环境没生效 | `test_preset_unknown_keys_fail_closed` |
| JSON 的 `scene` 把预设**整块盖掉** | `--env-preset close --input x.json` 静默变成 50 km | `test_json_scene_only_overrides_what_it_names` |
| 非求解器的量混进缓存键 | 改 `n_ref` 让所有缓存失效（或反过来：改了环境却命中旧缓存） | `test_cache_key_boundary` |
| 文件里的数与代码里的兜底数**各改一处** | 图2 用 10 km、图4 用 12 km | `test_default_preset_matches_the_documented_fallbacks` |
| 四张图里有一张没接 | 那一张的环境永远来自 `Scene()` 默认值 | `test_all_four_requests_carry_the_env_preset` |

配套（不在本文件、但同一条链路）：
`-k figures_repro` 的七项**字节**判据证明"图1/图2 的产物一个字节都没变"；
`-k fig4` 钉住图4 的产物契约。
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

from missile_sim import cli, engine, presets, spec
from missile_sim.spec import Scene, Scaling
from missile_sim.workflow import BgRequest, Fig4Request, PlaneRequest, TrajRequest

REQUESTS = (PlaneRequest, BgRequest, TrajRequest, Fig4Request)


def _write(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "presets.json"
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return p


def _copy_default(**scene_over) -> dict:
    base = presets.resolve("default").as_dict()
    base["scene"] = dict(base["scene"], **scene_over)
    return base


# --------------------------------------------------------------------- ① 只换来源


def test_default_preset_matches_the_documented_fallbacks():
    """`configs/presets.json` 里的 `default` 必须与代码里**写死的那几个兜底数**逐项相等。

    这几个数字在仓库里出现过两处（预设文件 + 各自的模块文档/兜底），两处不一致时
    四张图会各自"看起来正常"却不可比 —— 所以这里把"两处必须相等"变成判据：
    10 km / 800 m/s / 20 G 是图2 的参考图口径（`figures.bg_*` 的注释也这么写），
    一整秒是 `--iso-step` 的默认值。
    """
    pre = presets.resolve("default")
    assert pre.ref_alt_m == 10_000.0
    assert pre.ref_speed_ms == 800.0
    assert pre.n_ref == 20.0
    assert pre.iso_step == 1.0
    assert pre.tier in spec.TIERS
    assert pre.standard == spec.DEFAULT_MISSILE
    # 环境 = `Scene()` 的默认值（逐字段；`maneuvers` 不在预设里，由各图的想定编译器写）
    for f in fields(Scene):
        if f.name == "maneuvers":
            continue
        assert asdict(pre.scene_obj())[f.name] == asdict(Scene())[f.name], \
            f"预设 default 的 {f.name} 与 Scene() 的默认值不一致"


def test_preset_build_reproduces_the_hardcoded_requests():
    """`presets.build(cls)` 与"手工写全默认值"的请求**逐字段相等**（四个 Request 各一条）。

    `None` 语义的字段（图2 的 `alt_m` / `speed_ms`）由预设**显式填上**同一个数：
    这正是 v4 要的"参考工况只有一套定义" —— 于是这里比的是"显式填好的那一份"。
    """
    want = {
        PlaneRequest: PlaneRequest(scene=Scene(), env_preset="default", standard="PL-12",
                                   tier="fast", iso_step=1.0),
        BgRequest: BgRequest(scene=Scene(), env_preset="default", standard="PL-12",
                             tier="fast", iso_step=1.0, dv_pin=None, n_ref=20.0,
                             alt_m=10_000.0, speed_ms=800.0),
        TrajRequest: TrajRequest(scene=Scene(), env_preset="default", standard="PL-12",
                                 tier="fast"),
        Fig4Request: Fig4Request(scene=Scene(), env_preset="default", standard="PL-12",
                                 tier="fast", n_ref=20.0, ref_alt_m=10_000.0,
                                 ref_speed_ms=800.0),
    }
    for cls in REQUESTS:
        got = presets.build(cls)
        for f in fields(cls):
            if f.name in ("scene", "alt_m", "speed_ms"):
                continue
            assert getattr(got, f.name) == getattr(want[cls], f.name), \
                f"{cls.__name__}.{f.name}: {getattr(got, f.name)!r} != {getattr(want[cls], f.name)!r}"
        assert got.scene.range_m == 50_000.0 and got.scene.alt_m == 10_000.0
        assert got.env_preset == "default"


def test_all_four_requests_carry_the_env_preset():
    """四个请求都得有 `env_preset` 字段、且 `build()` 把它填成预设名（少一张图就是漏接）。"""
    for cls in REQUESTS:
        assert "env_preset" in {f.name for f in fields(cls)}, f"{cls.__name__} 没有 env_preset 字段"
        assert presets.build(cls, env_preset="high").env_preset == "high"
    assert TrajRequest().as_dict()["env_preset"] == "default"


# --------------------------------------------------------------------- ② 文件真的被读


def test_preset_file_is_actually_read(tmp_path):
    """改一份临时预设文件，请求与场景必须**跟着变**（装饰性文件会在这里红）。"""
    path = _write(tmp_path, {"x": _copy_default(range_m=60_000.0, alt_m=7_000.0)})
    pre = presets.resolve("x", path=path)
    assert pre.scene_obj().range_m == 60_000.0
    req = presets.build(TrajRequest, env_preset="x", path=path)
    assert req.scene.range_m == 60_000.0 and req.scene.alt_m == 7_000.0
    # 显式值仍然覆盖预设（优先级：显式 > 预设 > 字段默认）
    req2 = presets.build(TrajRequest, env_preset="x", path=path, scene={"range_m": 1.0})
    assert req2.scene.range_m == 1.0 and req2.scene.alt_m == 7_000.0
    # 名字不认识 ⇒ 报错，不悄悄退回 default
    with pytest.raises(ValueError, match="没有这个预设"):
        presets.resolve("nope", path=path)


def test_preset_unknown_keys_fail_closed(tmp_path):
    """未知键 / 禁键 / 类型不对一律**当场报错**（静默忽略会让"改了没生效"看起来正常）。"""
    cases = [
        ({"x": dict(_copy_default(), nope=1)}, "不认识的键"),
        ({"x": {"scene": {"nope": 1}}}, "不认识的键"),
        ({"x": {"scene": {"maneuvers": [[0.0, [0.0, 0.0, 0.0]]]}}}, "不许给"),
        ({"x": {"scene": {"range_m": "far"}}}, "要数字"),
        ({"x": {"tier": "turbo"}}, "tier"),
        ({"x": {"iso_step": 0}}, "必须为正"),
        ({"x": {"observation": "telepathic"}}, "observation"),
        ({"x": []}, "必须是一个对象"),
    ]
    for i, (body, needle) in enumerate(cases):
        path = _write(tmp_path, body)
        with pytest.raises(ValueError) as exc:
            presets.load(path=path)
        assert needle in str(exc.value), f"第 {i} 例：报错里没有 {needle!r}：{exc.value}"
    # 只有注释的文件（下划线键）也算错：一份预设都没有
    path = _write(tmp_path, {"_说明": "只有注释"})
    with pytest.raises(ValueError, match="一份预设都没有"):
        presets.load(path=path)


def test_json_scene_only_overrides_what_it_names(tmp_path):
    """`--input` 的 `scene` **只覆盖它点名的字段**，其余留给预设（v4 之前是整块盖掉）。

    反例：`--env-preset close` + 一个只写 `{"scene": {"alt_m": 9000}}` 的 JSON，
    旧写法会静默变成"50 km 迎头"（因为 JSON 那侧是从 `Scene()` 起底的）。
    """
    path = _write(tmp_path, {"close": _copy_default(range_m=20_000.0, alt_m=5_000.0)})
    js = tmp_path / "in.json"
    js.write_text(json.dumps({"scene": {"alt_m": 9000.0}}), encoding="utf-8")
    args = cli.build_parser().parse_args(["--env-preset", "close", "--input", str(js)])
    # `_request` 读的是 `spec.ENV_PRESET_PATH`；这里换成临时文件走同一条代码路径
    orig = spec.ENV_PRESET_PATH
    try:
        import missile_sim.spec as sp
        sp.ENV_PRESET_PATH = path                      # type: ignore[misc]
        req = cli._request(args, TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES)
    finally:
        sp.ENV_PRESET_PATH = orig                      # type: ignore[misc]
    assert req.env_preset == "close"
    assert req.scene.alt_m == 9000.0, "JSON 点名的字段要被覆盖"
    assert req.scene.range_m == 20_000.0, "JSON 没点名的字段必须留给预设（这里曾整块盖掉）"
    assert req.scene.target_heading_deg == 180.0


# --------------------------------------------------------------------- ③ 缓存键的边界


def _scaling() -> Scaling:
    return Scaling(dv_target=932.5697, bc_target=3078.05, dv_blk=932.5697, bc_blk=3078.05,
                   thrust_scale=1.0, cx_scale=1.0, cxaoa_scale=1.0)


def test_cache_key_boundary(tmp_path):
    """只有**流进求解器**的量才进缓存键：参考工况/等时线步长不算，环境与档位算。"""
    base = engine.cache_key(Scene(), "PL-12", _scaling(), "fast")
    # ① 只改"参考工况 + 等时线步长"（不碰求解器）⇒ 键必须**一模一样**
    path = _write(tmp_path, {"ref": dict(_copy_default(), n_ref=30.0, iso_step=2.0,
                                        ref_alt_m=12_000.0, ref_speed_ms=700.0)})
    req = presets.build(TrajRequest, env_preset="ref", path=path)
    assert engine.cache_key(req.scene, "PL-12", _scaling(), req.tier) == base
    # ② 改环境的任一自由量 ⇒ 键必须变
    path2 = _write(tmp_path, {"far": _copy_default(range_m=60_000.0)})
    req2 = presets.build(TrajRequest, env_preset="far", path=path2)
    assert engine.cache_key(req2.scene, "PL-12", _scaling(), req2.tier) != base
    # ③ 换档位 ⇒ 键必须变
    assert engine.cache_key(Scene(), "PL-12", _scaling(), "standard") != base
    # ④ 想定（maneuvers）是环境的一部分：图3/图4 的 crank→39 必须与直飞不同键
    from missile_sim import flightpath
    sch = flightpath.crank_beam(8.0, 70.0, 34.0, react_delay_s=1.0)
    man = sch.maneuvers(duration_s=150.0, dt=0.1)
    crank = replace(Scene(), maneuvers=man)
    assert engine.cache_key(crank, "PL-12", _scaling(), "fast") != base


# --------------------------------------------------------------------- ④ 与各图接口对齐


def test_request_fields_map_onto_every_figure(tmp_path):
    """预设的每个键都要在**至少一张图**上落地（无人认领的键会让人以为改了有用）。"""
    pre = presets.resolve("default")
    landed = {}
    for cls in REQUESTS:
        got = presets.build(cls)
        landed[cls.__name__] = {k for k in pre.request_fields()
                                if k in {f.name for f in fields(cls)}}
    assert "standard" in landed["PlaneRequest"] and "tier" in landed["Fig4Request"]
    assert {"standard", "tier", "n_ref", "ref_alt_m", "ref_speed_ms", "iso_step", "dv_pin"} \
        <= (landed["BgRequest"] | landed["Fig4Request"]), landed
    # 图2 走别名表折到自己的字段名上（`alt_m` / `speed_ms`）
    bg = presets.build(BgRequest)
    assert bg.alt_m == 10_000.0 and bg.speed_ms == 800.0
    assert presets.resolve("default").request_fields()["ref_alt_m"] == bg.alt_m


# --------------------------------------------------------------------- ⑤ WebUI 也吃它


def test_webui_form_uses_the_shared_preset(tmp_path):
    """WebUI 的**表单初值**来自预设，且请求里带着预设名（下拉不是装饰品）。

    反例（改造前那条链路）：下拉改了 `env_preset`，可下面每个环境字段都还是上一次的值 ——
    页面上看起来"换了预设"，实际一个数都没动。所以这里比的是**表单初值**，不是请求。
    """
    from missile_sim import webui

    assert "env_preset" in webui.WEB_ONLY_KEYS, "env_preset 是 Web 层专名，不能喂给 build_scene()"
    assert "env_preset" in {f.name for f in webui.ALL_FIELDS}
    opts = {f.name: f.options for f in webui.ALL_FIELDS if f.name == "env_preset"}[
        "env_preset"]
    assert set(opts) >= {"default", "close", "high"}
    # 默认那份：表单初值 = 预设的环境
    base = webui.defaults_form({})
    assert base["env_preset"] == "default" and base["range_m"] == 50_000.0
    # 换一份（用临时文件把 `close` 改成可辨识的值，证明"表单初值真的跟着预设走"）
    path = _write(tmp_path, {"close": _copy_default(range_m=21_000.0, alt_m=6_000.0)})
    orig = spec.ENV_PRESET_PATH
    try:
        spec.ENV_PRESET_PATH = path                    # type: ignore[misc]
        got = webui.defaults_form({"env_preset": "close"})
        assert got["range_m"] == 21_000.0 and got["alt_m"] == 6_000.0
        # 表单里手改过的字段仍然以表单为准
        req, scene, errors = webui.form_to_request(
            dict(got, range_m="33000", env_preset="close"), {"cache": False})
        assert errors == [], errors
        assert scene.range_m == 33_000.0 and scene.alt_m == 6_000.0
        assert req.env_preset == "close"
        # 名字不认识 ⇒ 报错，不悄悄退回 default
        _r, _s, bad = webui.form_to_request(dict(got, env_preset="nope"), {"cache": False})
        assert any("共享环境预设" in e for e in bad), bad
    finally:
        spec.ENV_PRESET_PATH = orig                    # type: ignore[misc]

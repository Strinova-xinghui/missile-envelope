# -*- coding: utf-8 -*-
"""回归：表单里"用户手动改过"的字段必须如实生效，且改了就要在图上看得见。

用户报的现象：选了预置想定之后，把距离改成 50 km（恰好是默认值），图上写的还是预置的
距离。根因是 `targets.build_scene()` 的**兜底猜法** —— `preset` 非空时，凡是恰好等于
`DEFAULT_FORM` 默认值的字段一律当成"用户没动过"而丢弃。这个猜法留着兼容老客户端
（CLI、旧脚本），但 WebUI 现在一律发 `_dirty`，走"前端如实上报"那条不猜的路。

同时钉住"工况改了图上必须看得见"：`Scene.describe()`（进脚注）与
`figures.plane_subtitle()`（副标题），加上脚注本身，不许漏掉任何影响弹道的输入
（曾经 `target_bearing_deg` 改了整张图毫无反应）。
"""

import inspect
import types

import pytest

from missile_sim import figures, record, spec, targets, webui

FIELDS = [k for k in targets.DEFAULT_FORM if k not in ("preset", "maneuvers")]
PRESETS = sorted(targets.presets())


def _figure_text(scene) -> str:
    """这个工况在**所有**出口上的文字：图副标题 + 页面摘要 + 脚注三行。

    ⚠ 工况文字有三处并列实现 —— `figures.plane_subtitle()`（图上副标题）、
    `targets.describe_scene()`（页面 `scene_text`）、`spec.Scene.describe()`（脚注）。
    可见性检查必须把三处都算进来，只查其中一处会漏（真漏过：方位角）。
    """
    prov = types.SimpleNamespace(solver={}, tier="fast", backend="compiled-c",
                                 standard="PL-12", scene=scene.as_dict())
    return "\n".join([figures.plane_subtitle(scene, standard="PL-12"),
                      targets.describe_scene(scene),
                      scene.describe(),
                      *record.provenance_lines(prov)])


# ------------------------------------------------------------------ _dirty


def test_dirty_absent_keeps_legacy_guess():
    """不给 _dirty：兜底猜法照旧，老客户端行为不变。"""
    form = targets.preset_form("tail_chase")
    form["range_m"] = targets.DEFAULT_FORM["range_m"]
    assert targets.build_scene(form).range_m == 20_000.0            # 预置值胜出
    assert targets.build_scene({**form, "_dirty": None}).range_m == 20_000.0


def test_dirty_lets_a_default_valued_field_win():
    """给了 _dirty，手填"默认值"必须生效 —— 就是用户报的那个场景。"""
    form = targets.preset_form("tail_chase")
    form["range_m"] = targets.DEFAULT_FORM["range_m"]
    form["_dirty"] = "range_m"
    assert targets.build_scene(form).range_m == 50_000.0


def test_dirty_covers_every_field_of_every_preset():
    """6 个预置 × 全部场景字段：手填默认值一律必须生效。"""
    bad = []
    for preset in PRESETS:
        base = targets.preset_form(preset)
        for key in FIELDS:
            # target_alt_m 的"默认值"是 None，而 None 的语义是"没填" —— 显式恢复同高填 "同高"
            explicit = "同高" if key == "target_alt_m" else targets.DEFAULT_FORM[key]
            want = None if key == "target_alt_m" else targets.DEFAULT_FORM[key]
            got = getattr(targets.build_scene({**base, key: explicit, "_dirty": key}), key)
            if str(got) != str(want):
                bad.append(f"{preset}.{key}：期望 {want!r}，实得 {got!r}")
    assert not bad, "这些字段仍被静默丢弃：\n" + "\n".join(bad)


def test_dirty_empty_reproduces_the_preset():
    """空 _dirty（一个框都没动）⟹ 整份预置原样生效。"""
    for preset in PRESETS:
        form = targets.preset_form(preset)
        form["_dirty"] = ""
        assert targets.build_scene(form) == targets.scene_of_preset(preset)
        assert targets.build_scene(targets.preset_form(preset)) == targets.scene_of_preset(preset)


def test_dirty_accepts_several_spellings():
    """HTTP 传过来可能是逗号串，Python 调用可能给列表；都得认。"""
    base = {"preset": "tail_chase", "range_m": 50_000.0}
    for spelling in ("range_m", "range_m,", "range_m;", " range_m ", "range_m,nope",
                     ["range_m"], ("range_m",), {"range_m"}):
        assert targets.build_scene({**base, "_dirty": spelling}).range_m == 50_000.0, spelling


def test_dirty_rejects_a_bad_type():
    with pytest.raises(ValueError):
        targets.build_scene({"_dirty": 12345})


def test_dirty_survives_the_web_layer_filter():
    """`_scene_part()` 只该剔 Web 层键，`_dirty` 必须透给 build_scene。"""
    part = webui._scene_part({"preset": "head_on", "range_m": "50000",
                              "_dirty": "range_m", "tier": "fast", "tag": "x"})
    assert "_dirty" in part and "range_m" in part
    assert "tier" not in part and "tag" not in part


def test_front_end_reports_dirty_fields():
    """前端必须真的记录并上报手改字段 —— 少了它，后端只能回去猜。"""
    src = inspect.getsource(webui)
    assert "DIRTY.add" in src, "没有任何地方记录用户手改过的字段"
    assert "f._dirty" in src, "collect() 没有把 _dirty 发出去"


# ------------------------------------------------------------ 图上看得见


def test_every_scene_field_changes_something_on_the_figure():
    """改任一场景字段，图上文字（副标题或脚注）必须跟着变。"""
    base_text = _figure_text(spec.Scene())
    non_default = {
        "range_m": 70_000.0, "alt_m": 12_000.0, "target_alt_m": 13_000.0,
        "target_bearing_deg": 45.0, "vm0": 350.0, "launch_heading_deg": 20.0,
        "launch_pitch_deg": 10.0, "target_speed_ms": 260.0,
        "target_heading_deg": 150.0, "target_pitch_deg": -15.0,
        "duration_s": 200.0, "dt_s": 0.01, "observation": "locked",
        "wind_m_s": (10.0, 0.0, 5.0), "ground_height_m": 500.0,
        "proximity_fuse": False, "hit_radius_m": 15.0,
    }
    assert sorted(non_default) == sorted(FIELDS), "字段清单与 Scene 脱节了"
    invisible = [k for k, v in non_default.items()
                 if _figure_text(spec.Scene(**{k: v})) == base_text]
    assert not invisible, f"这些字段改了图上完全看不出来：{invisible}"


def test_bearing_is_written_out_everywhere():
    """方位单独钉一条：3D 工况的关键量，曾经**三处**工况文字全都不写它。"""
    scene = spec.Scene(target_bearing_deg=45.0)
    assert "方位 45°" in figures.plane_subtitle(scene, standard="PL-12")
    assert "方位 45°" in targets.describe_scene(scene)          # 页面上的那套
    assert "方位 45°" in scene.describe()                        # 脚注里的那套
    # 默认 0° 不写，免得默认工况的文字被"方位 0°"撑长
    assert "方位" not in figures.plane_subtitle(spec.Scene(), standard="PL-12")
    assert "方位" not in targets.describe_scene(spec.Scene())
    assert "方位" not in spec.Scene().describe()


def test_the_three_scene_texts_agree_on_the_basics():
    """三处文字措辞可以不同，但**同一批事实**必须都在（免得改一处忘两处）。"""
    scene = spec.Scene(target_bearing_deg=45.0, launch_pitch_deg=10.0,
                       target_pitch_deg=-15.0, vm0=350.0, target_speed_ms=260.0)
    texts = {
        "plane_subtitle": figures.plane_subtitle(scene, standard="PL-12"),
        "describe_scene": targets.describe_scene(scene),
        "Scene.describe": scene.describe(),
    }
    for name, text in texts.items():
        for fact in ("方位 45°", "350", "260", "10°", "-15°"):
            assert fact in text, f"{name} 少写了 {fact!r}：{text}"


def test_default_scene_text_is_unchanged():
    """默认工况的文字**逐字**不变 —— 已入库的 figures/ 产物才不会无故重算。"""
    assert spec.Scene().describe() == (
        "50 km（50.0 km 斜距）迎头 · 高度 10000 m · 载机 300 m/s 航向 0° · "
        "敌机 300 m/s 航向 180° 俯仰 0° · ideal")
    assert figures.plane_subtitle(spec.Scene(), standard="PL-12") == (
        "50 km 迎头 · 高度 10.0 km · 载机 300 m/s 航向 0° · "
        "敌机 300 m/s 航向 180° · 基准弹 PL-12")

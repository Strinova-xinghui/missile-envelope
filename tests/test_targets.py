# -*- coding: utf-8 -*-
"""`targets.py` 的契约测试：预置想定、表单转换、求解器兼容性前置校验、角度→向量方向。

跑法：`python tests\\run_tests.py -k targets`（其中 `test_head_on_preset_hits_with_solver`
会真跑一次 fast 档求解器，约 1~3 s；其余用例都是纯计算）。
"""

from __future__ import annotations

import math
from dataclasses import fields

import pytest

from missile_sim import targets
from missile_sim.spec import SOLVER_DT, Scene, velocity_vector


# --------------------------------------------------------------------- 伪造"带运动字段"的 Scene
# `spec.Scene` 目前只带 `maneuvers`；`samples` / `turn_rate` 是内核原生能力（SOLVER-API §4），
# 这里就地补两个属性，验证 `check_compatible()` 的三选一互斥校验**真的能生效**。
#
# ⚠ 刻意**不用 `@dataclass` 子类**：`tests/run_tests.py` 用 `spec_from_file_location` 加载测试
# 模块时不一定把它注册进 `sys.modules`，而 `dataclasses` 解析注解要拿 `cls.__module__` 回查
# `sys.modules` —— 查不到就抛 `AttributeError: 'NoneType' object has no attribute '__dict__'`，
# 而且是在**收集阶段**炸掉整个测试跑（`-k` 过滤发生在 collect 之后，一个文件的写法能让所有人
# 跑不了测试）。runner 那边已经补了注册，这里再自保一层。


def _with_motion(**kwargs) -> Scene:
    """造一个"带内核原生运动字段"的 `Scene`（`samples` / `turn_rate` 就地补上）。"""
    samples = kwargs.pop("samples", ())
    turn_rate = kwargs.pop("turn_rate", 0.0)
    scene = Scene(**kwargs)
    object.__setattr__(scene, "samples", samples)       # frozen dataclass ⇒ 绕过 __setattr__
    object.__setattr__(scene, "turn_rate", turn_rate)
    return scene


# --------------------------------------------------------------------- 预置想定


def test_presets_cover_required_scenarios():
    got = targets.presets()
    need = {"head_on", "tail_chase", "beam_90", "target_climb", "target_dive", "altitude_gap"}
    assert need <= set(got), f"缺预置想定：{need - set(got)}"
    for name, desc in got.items():
        assert isinstance(desc, str) and desc.strip(), f"{name} 的描述是空的"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in desc), f"{name} 的描述不是中文：{desc!r}"


def test_every_preset_builds_a_runnable_scene():
    for name in targets.presets():
        scene = targets.scene_of_preset(name)
        assert isinstance(scene, Scene)
        assert targets.check_compatible(scene) == [], f"{name} 不该被拦下"
        assert scene.range_m > 0.0 and scene.alt_m > 0.0
        assert scene.vm0 >= 0.0 and scene.target_speed_ms >= 0.0
        assert scene.observation in ("ideal", "locked")
        assert not scene.maneuvers, f"{name} 本轮只做直飞"


def test_preset_overrides_take_effect():
    sc = targets.scene_of_preset("head_on", range_m=60_000)
    assert sc.range_m == 60_000.0
    assert sc.target_heading_deg == 180.0, "没被覆盖的字段应保持预置值"

    sc = targets.scene_of_preset("altitude_gap", range_m="45000")       # 字符串也认
    assert sc.range_m == 45_000.0

    sc = targets.scene_of_preset("altitude_gap", target_alt_m=None)     # 显式 None 生效
    assert sc.target_alt_m is None
    assert sc.target_alt == sc.alt_m


def test_preset_unknown_name_raises():
    with pytest.raises(KeyError):
        targets.scene_of_preset("head-on")          # 拼写/命名不一致要当场报错


def test_preset_unknown_field_raises():
    with pytest.raises(TypeError):
        targets.scene_of_preset("head_on", rnage_m=1000)


def test_preset_form_round_trip():
    for name in targets.presets():
        form = targets.preset_form(name)
        assert form["preset"] == name
        assert set(form) == set(targets.DEFAULT_FORM)
        assert targets.build_scene(form) == targets.scene_of_preset(name)


# --------------------------------------------------------------------- 表单 → Scene


def test_default_form_matches_scene_defaults():
    scene = Scene()
    assert targets.DEFAULT_FORM["preset"] == ""
    for f in fields(Scene):
        if f.name == "maneuvers":                       # 内核原生能力，本轮不暴露
            assert f.name not in targets.DEFAULT_FORM
            continue
        assert targets.DEFAULT_FORM[f.name] == getattr(scene, f.name), f.name
    assert targets.DEFAULT_FORM["dt_s"] == SOLVER_DT


def test_build_scene_empty_is_default():
    assert targets.build_scene({}) == Scene()
    assert targets.build_scene(None) == Scene()


def test_build_scene_casts_form_strings():
    """HTTP 表单来的全是字符串 —— 数字、枚举、布尔、三元组都要能转。"""
    scene = targets.build_scene({
        "range_m": "60000", "alt_m": "12000", "target_alt_m": "13000",
        "target_bearing_deg": "90", "vm0": "350", "launch_pitch_deg": "-5",
        "target_heading_deg": "170", "target_pitch_deg": "10",
        "duration_s": "120", "observation": "LOCKED",
        "proximity_fuse": "off", "wind_m_s": "5,0,-3", "hit_radius_m": "25",
    })
    assert scene.range_m == 60_000.0 and scene.alt_m == 12_000.0
    assert scene.target_alt_m == 13_000.0
    assert scene.target_bearing_deg == 90.0
    assert scene.vm0 == 350.0 and scene.launch_pitch_deg == -5.0
    assert scene.target_heading_deg == 170.0 and scene.target_pitch_deg == 10.0
    assert scene.duration_s == 120.0
    assert scene.observation == "locked"
    assert scene.proximity_fuse is False
    assert scene.wind_m_s == (5.0, 0.0, -3.0)
    assert scene.hit_radius_m == 25.0
    assert targets.check_compatible(scene) == []


def test_build_scene_unknown_key_raises():
    with pytest.raises(ValueError):
        targets.build_scene({"rnage_m": 1000})              # 拼错的距离字段
    with pytest.raises(ValueError):
        targets.build_scene({"missile": "PL-12"})           # 弹型不是场景字段，别混进来


def test_build_scene_bad_value_raises():
    with pytest.raises(ValueError):
        targets.build_scene({"range_m": "五十公里"})
    with pytest.raises(ValueError):
        targets.build_scene({"proximity_fuse": "maybe"})
    with pytest.raises(ValueError):
        targets.build_scene({"wind_m_s": "1,2"})
    with pytest.raises(ValueError):
        targets.build_scene({"range_m": True})              # bool 不是数字


def test_build_scene_non_dict_raises():
    with pytest.raises(TypeError):
        targets.build_scene([("range_m", 1000)])


def test_build_scene_preset_survives_form_defaults():
    """WebUI 会把整张表（含默认值）提交上来 —— 默认值不许把预置抹掉。"""
    form = dict(targets.DEFAULT_FORM)
    form["preset"] = "tail_chase"
    assert targets.build_scene(form) == targets.scene_of_preset("tail_chase")


def test_build_scene_explicit_value_beats_preset():
    scene = targets.build_scene({"preset": "tail_chase", "range_m": "30000"})
    assert scene.range_m == 30_000.0
    assert scene.target_heading_deg == 0.0, "只改了一个字段，预置的其余字段要留着"


def test_build_scene_blank_means_unset():
    scene = targets.build_scene({"preset": "beam_90", "alt_m": "", "target_bearing_deg": None})
    assert scene == targets.scene_of_preset("beam_90")


def test_build_scene_target_alt_none_word():
    scene = targets.build_scene({"preset": "altitude_gap", "target_alt_m": "none"})
    assert scene.target_alt_m is None
    assert scene.target_alt == scene.alt_m == 5_000.0


# --------------------------------------------------------------------- 兼容性校验


def test_check_compatible_accepts_default_scene():
    assert targets.check_compatible(Scene()) == []
    assert targets.check_compatible(targets.scene_of_preset("head_on")) == []


def test_check_compatible_includes_scene_check():
    """契约层的问题必须一条不少地传上来 —— 这是"叠加"而不是"另起一套"。"""
    scene = Scene(dt_s=0.5, vm0=-1.0)
    contract = scene.check()
    assert contract, "测试前提：这个场景要违反 Scene.check()"
    mine = targets.check_compatible(scene)
    for msg in contract:
        assert msg in mine, f"Scene.check() 的结论丢了：{msg!r}"


_BAD_SCENES = [
    ("dt_s 比客户端时钟还大", Scene(dt_s=0.05)),
    ("dt_s 太小", Scene(dt_s=1e-6)),
    ("observation 非法", Scene(observation="track")),
    ("载机速度为负", Scene(vm0=-300.0)),
    ("敌机速度为负", Scene(target_speed_ms=-1.0)),
    ("duration_s = 0", Scene(duration_s=0.0)),
    ("duration_s < 0", Scene(duration_s=-10.0)),
    ("range_m < 0", Scene(range_m=-1.0)),
    ("hit_radius_m < 0", Scene(hit_radius_m=-1.0)),
    ("发射高度在地下", Scene(alt_m=5_000.0, ground_height_m=6_000.0)),
    ("目标高度在地下", Scene(alt_m=5_000.0, target_alt_m=1_000.0, ground_height_m=2_000.0)),
    ("发射高度过高", Scene(alt_m=targets.ALT_MAX_M + 1.0)),
    ("目标高度过高", Scene(target_alt_m=100_000.0)),
    ("载机俯仰超限", Scene(launch_pitch_deg=120.0)),
    ("敌机俯仰超限", Scene(target_pitch_deg=-95.0)),
    ("步数过多", Scene(duration_s=100_000.0, dt_s=0.00025)),
    ("range_m 是 nan", Scene(range_m=math.nan)),
    ("duration_s 是 inf", Scene(duration_s=math.inf)),
    ("alt_m 是 nan", Scene(alt_m=math.nan)),
    ("wind_m_s 只有两段", Scene(wind_m_s=(1.0, 2.0))),
    ("wind_m_s 里有 nan", Scene(wind_m_s=(0.0, math.nan, 0.0))),
]


@pytest.mark.parametrize("why, scene", _BAD_SCENES)
def test_check_compatible_rejects_bad_scene(why, scene):
    bad = targets.check_compatible(scene)
    assert bad, f"{why}：应该被拦下，却通过了"
    assert all(isinstance(m, str) and m for m in bad)


def test_check_compatible_accepts_ground_level_and_pitch_limit():
    """边界内侧要放过：海平面发射（alt = ground = 0）、俯仰恰好 ±90°。"""
    assert targets.check_compatible(Scene(alt_m=0.0, target_alt_m=0.0)) == []
    assert targets.check_compatible(Scene(launch_pitch_deg=90.0)) == []
    assert targets.check_compatible(Scene(target_pitch_deg=-90.0)) == []
    assert targets.check_compatible(Scene(alt_m=targets.ALT_MAX_M)) == []


def test_check_compatible_never_raises_on_broken_types():
    """坏类型也要变成消息，不能把异常扔给 WebUI。"""
    bad = targets.check_compatible(Scene(range_m="abc", alt_m=None, target_alt_m="xyz",
                                         observation=42, vm0="fast"))
    assert bad and all(isinstance(m, str) for m in bad)


def test_check_compatible_rejects_non_scene():
    assert targets.check_compatible(None)
    assert targets.check_compatible({"range_m": 50_000.0})


def test_check_compatible_motion_exclusivity():
    """`maneuvers` / `samples` / `turn_rate` 三选一（SOLVER-API §4 实测的硬拒绝）。"""
    m = ((0.0, (0.0, 0.0, 0.0)),)
    msg = " ".join(targets.check_compatible(_with_motion(maneuvers=m, turn_rate=0.1)))
    assert "三选一" in msg

    sc = _with_motion(turn_rate=0.05,
                          samples=({"time_s": 0.0, "position_m": (1.0, 0.0, 0.0),
                                    "velocity_m_s": (0.0, 0.0, 0.0)},))
    assert "三选一" in " ".join(targets.check_compatible(sc))

    # 单独给一种：不算冲突
    assert "三选一" not in " ".join(targets.check_compatible(_with_motion(turn_rate=0.1)))
    assert "三选一" not in " ".join(targets.check_compatible(_with_motion(maneuvers=m)))


def test_check_compatible_maneuvers_shape():
    bad = targets.check_compatible(Scene(maneuvers=((0.0, (0.0, 0.0, 0.0)),
                                                    (0.0, (0.0, 0.0, 1.0)))))
    assert any("严格递增" in m for m in bad)

    bad = targets.check_compatible(Scene(maneuvers=((0.0, (0.0, 0.0)),)))
    assert any("三个有限数" in m for m in bad)


def test_check_compatible_samples_must_cover_duration():
    """§4 硬约束：从 t=0 起、时间严格递增、覆盖到 duration_s、至少两条。"""
    def sample(t):
        return {"time_s": t, "position_m": (1000.0, 8000.0, 0.0),
                "velocity_m_s": (300.0, 0.0, 0.0)}

    bad = " ".join(targets.check_compatible(
        _with_motion(duration_s=150.0, samples=(sample(0.0), sample(4.0)))))
    assert "覆盖到 duration_s" in bad

    bad = " ".join(targets.check_compatible(
        _with_motion(duration_s=10.0, samples=(sample(1.0), sample(10.0)))))
    assert "从 t=0 起" in bad

    bad = " ".join(targets.check_compatible(
        _with_motion(duration_s=10.0, samples=(sample(0.0), sample(5.0), sample(5.0),
                                                   sample(10.0)))))
    assert "严格递增" in bad

    bad = " ".join(targets.check_compatible(
        _with_motion(duration_s=10.0, samples=(sample(0.0),))))
    assert "至少两条" in bad

    ok = _with_motion(duration_s=10.0, samples=(sample(0.0), sample(10.0)))
    assert targets.check_compatible(ok) == []


# --------------------------------------------------------------------- 角度 → 向量 / 坐标


def test_velocity_vector_directions():
    """零航向 +x、正航向转 +z、俯仰抬头为正；|v| 恒等于标量。"""
    v = velocity_vector(300.0, 0.0, 0.0)
    assert v[0] == pytest.approx(300.0)
    assert abs(v[1]) < 1e-9 and abs(v[2]) < 1e-9

    v = velocity_vector(300.0, 90.0, 0.0)               # 正航向转向 +z
    assert abs(v[0]) < 1e-9 and v[2] == pytest.approx(300.0)

    v = velocity_vector(300.0, 180.0, 0.0)
    assert v[0] == pytest.approx(-300.0)

    v = velocity_vector(300.0, 270.0, 0.0)
    assert v[2] == pytest.approx(-300.0)

    v = velocity_vector(300.0, 0.0, 90.0)               # 抬头为正 → +y
    assert v[1] == pytest.approx(300.0)

    v = velocity_vector(300.0, 0.0, -30.0)              # 俯冲 → -y
    assert v[1] == pytest.approx(-150.0)
    assert v[0] == pytest.approx(300.0 * math.cos(math.radians(30.0)))

    for speed in (0.0, 250.0, 400.0):
        for h in (0.0, 45.0, 90.0, 180.0, 315.0):
            for p in (-60.0, 0.0, 30.0):
                vec = velocity_vector(speed, h, p)
                norm = math.sqrt(sum(c * c for c in vec))
                assert norm == pytest.approx(speed), f"|v| 应恒等于标量（{h}°, {p}°）"


def test_scene_geometry_follows_bearing_and_altitude():
    scene = Scene(range_m=10_000.0, alt_m=8_000.0, target_bearing_deg=90.0)
    x, y, z = scene.target_position_m
    assert abs(x) < 1e-9 and y == 8_000.0 and z == pytest.approx(10_000.0)
    assert scene.launch_position_m == (0.0, 8_000.0, 0.0)
    assert scene.range_slant_m == pytest.approx(10_000.0)      # 同高 ⇒ 水平距离 = 斜距

    scene = Scene(range_m=3_000.0, alt_m=1_000.0, target_alt_m=5_000.0)
    assert scene.range_slant_m == pytest.approx(5_000.0)       # 3-4-5
    assert scene.target_alt == 5_000.0


def test_head_on_flag():
    assert Scene(target_heading_deg=180.0).head_on is True
    assert Scene(target_heading_deg=100.0).head_on is True
    assert Scene(target_heading_deg=90.0).head_on is False      # 恰好 90° 不算迎头
    assert Scene(target_heading_deg=0.0).head_on is False


def test_preset_headings_match_their_intent():
    """预置想定的航向要真的表达出"迎头/尾追/侧向"：不能只有名字对。"""
    head_on = targets.scene_of_preset("head_on")
    assert head_on.head_on
    assert head_on.target_velocity_m_s[0] < 0.0, "迎头 ⇒ 敌机朝 -x 飞"

    tail = targets.scene_of_preset("tail_chase")
    assert not tail.head_on
    assert tail.target_velocity_m_s[0] > 0.0, "尾追 ⇒ 敌机朝 +x 逃"
    assert tail.vm0 > tail.target_speed_ms, "尾追 ⇒ 载机更快"

    beam = targets.scene_of_preset("beam_90")
    assert beam.target_bearing_deg == 90.0
    assert abs(beam.target_position_m[2]) == pytest.approx(beam.range_m)

    climb = targets.scene_of_preset("target_climb")
    assert climb.target_pitch_deg > 0.0 and climb.target_velocity_m_s[1] > 0.0
    dive = targets.scene_of_preset("target_dive")
    assert dive.target_pitch_deg < 0.0 and dive.target_velocity_m_s[1] < 0.0

    gap = targets.scene_of_preset("altitude_gap")
    assert gap.target_alt > gap.alt_m
    assert gap.range_slant_m > gap.range_m


def test_describe_scene_mentions_key_numbers():
    text = targets.describe_scene(targets.scene_of_preset("altitude_gap"))
    assert "40 km" in text and "迎头" in text
    assert "5.0" in text and "12.0" in text and "+7.0" in text
    assert "航向 0°" in text and "航向 180°" in text
    assert "\n" not in text, "副标题必须是一行"

    same_alt = targets.describe_scene(Scene())
    assert "同高" in same_alt and "50 km" in same_alt


# --------------------------------------------------------------------- 与求解器对接


def test_check_missile_uses_solver_hard_rejection():
    """§4：不支持的型号是硬拒绝，不做近似替代 —— 提交前先问一句。"""
    assert targets.check_missile("cn_pl12") == []
    assert targets.check_missile("no_such_missile_xyz")
    assert targets.check_missile("")


def test_head_on_preset_hits_with_solver():
    """验收锚点：预置想定真跑求解器，金标 t_hit = 45.1861 s（SOLVER-API §0）。"""
    from missile_sim import solver

    scene = targets.scene_of_preset("head_on")
    assert targets.check_compatible(scene) == []
    shot = solver.run(scene, missile="cn_pl12", tier="fast")
    assert shot.ok, f"求解器没跑通：{shot.error}"
    assert shot.hit, f"迎头 50 km 该命中，实际 event={shot.event!r}"
    assert abs(shot.t_hit - 45.1861) < 0.01, f"t_hit={shot.t_hit}"
    assert shot.backend, "backend 必须来自真跑过的 summary"

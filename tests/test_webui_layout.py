# -*- coding: utf-8 -*-
"""task-20：四页统一输入布局（照 statshark：左栏可折叠输入 + 预设 chip）的判据。

用户 2026-10-02 拍板，三条最容易做错的：

1. **预设 chip 点下去必须真的改输入框的值**，不许装饰性按钮 —— 判据要能证明
   「点 chip ⇒ 表单值变 ⇒ 请求变」。这条是**行为**，Python 侧测不了，所以走
   `tests/_webui_chrome_probe.js`：用 `vm` 把真 `app.js` 装进桩 DOM 里真点一遍。
   没有 node 就 `pytest.skip`（与 `-k fig3d_spike` 同一个套路：跑得动就跑）。
2. **单位写在标签里**（`发射高度（米）`），不再是"数值 + 单位塞在 hint 里"两套写法并存。
3. **左栏可折叠、状态记在 `localStorage`**，四页共用一份骨架 CSS（`webui_static/app.css`）。

数值行为一条都不许变：这些判据只读页面/DOM 契约，不碰任何求解器输入。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import presets as presets_mod  # noqa: E402
from missile_sim import webui  # noqa: E402

PROBE = ROOT / "tests" / "_webui_chrome_probe.js"
APP_JS = ROOT / "src" / "missile_sim" / "webui_static" / "app.js"


@pytest.fixture(scope="module")
def home():
    """渲染一次首页 + boot 数据（模块级缓存，探针与断言共用）。"""
    state = webui.WebState({}, quiet=True)
    defaults = webui.defaults_form(state.config)
    env = webui.env_presets_payload(defaults)
    return {
        "state": state,
        "config": state.config,
        "defaults": defaults,
        "env": env,
        "presets": webui.presets_payload(defaults),
        "html": webui.render_page(state),
    }


# --------------------------------------------------------------- 1. 左栏骨架


def test_home_page_carries_the_shared_shell(home):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「首页有 `.shell/.rail/#envchips/#presetchips/#envdirty` 等骨架元素」→ 表单首页已删 → 替代：test_static_pool_page::test_rail_只有弹池（骨架仍共用同一份 app.css）
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """首页必须是「左栏 = 输入 + 右栏 = 主视图」那套骨架（class 口径见 app.css 末尾）。"""
    html = home["html"]
    for needle in ('class="shell" id="shell"', 'class="rail" id="rail"',
                   'class="mainview"', 'id="railtoggle"', 'class="rail-body"',
                   'class="rail-sec"', 'class="rail-actions"',
                   'class="chips" id="envchips"', 'class="chips" id="presetchips"',
                   'class="badge-dirty" id="envdirty"'):
        assert needle in html, f"首页缺少骨架元素 {needle!r}"
    # 折叠按钮必须在 .rail **外面**：放里面的话，左栏一收起它自己也跟着看不见了，
    # 于是永远展不开（这条是结构判据，真正的行为由下面的 node 探针验）。
    assert html.index('id="railtoggle"') < html.index('class="rail" id="rail"'), \
        "折叠按钮必须排在 .rail 之前（在它里面就永远展不开）"


def test_units_live_in_the_labels(home):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「字段标签里带单位（读 `data-field` 的 label）」→ 表单字段没了 → 替代：test_static_pool_page::test_rail_只有弹池（静态页左栏没有输入框）
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """单位进标签：`发射距离（米）`；不再有"数值框 + opacity 单位尾巴"那种写法。"""
    html = home["html"]
    for needle in ("发射距离（米）", "载机初始速度（米/秒）", "载机航向（度）",
                   "时域上限（秒）", "敌机高度（米）", "等时线步长（秒）"):
        assert needle in html, f"标签里没有单位：{needle!r}"
    assert 'style="opacity:.7"' not in html, "单位还挂在输入框尾巴上（两套写法并存）"
    assert '<div class="hint">' not in html, "字段说明还占一行（应挪进 title，左栏才排得下）"
    # 说明文字没丢：挪进了 `title=`（悬停可见）
    assert 'title="双方水平距离；斜距按高度差现算"' in html


def test_env_presets_are_chips_not_a_dropdown(home):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「环境预设是 chips 而不是下拉」→ 环境预设整块删掉 → 替代：无（该功能按用户口径不发布）
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """环境预设从下拉框改成 chip 网格；字段本体（hidden `<select>`）仍在，值标成 selected。

    ⚠ `selected` 那条是**真 bug 的判据**：`<select>` 不标就默认选第一个 option，于是
    配置里把 `env_preset` 设成 close 时，表单显示 close 的字段值、请求里却发 default。
    """
    html = home["html"]
    names = list(presets_mod.names())
    assert len(names) >= 2, "预设文件至少要有两份，否则这条判据没意义"
    for name in names:
        assert f'data-env-preset="{name}"' in html, f"缺少环境预设 chip {name!r}"
    assert f'data-field="env_preset"' in html, "chip 背后要有唯一的字段本体"
    cur = home["defaults"]["env_preset"]
    assert f'<option value="{cur}" selected>' in html, f"当前预设 {cur!r} 没被标成 selected"
    # 预置想定（A1 那一层）同样是 chip
    for name in home["presets"]:
        assert f'data-preset="{name}"' in html, f"缺少预置想定 chip {name!r}"
    # `_keys`（预设管的字段清单）是保留键，不能变成一个名叫 `_keys` 的 chip
    assert 'data-env-preset="_keys"' not in html
    assert home["env"]["_keys"], "载荷里没有 _keys：前端就算不出『已偏离预设』"
    assert "range_m" in home["env"]["_keys"] and "figure" not in home["env"]["_keys"], \
        "_keys 应当只含预设管的字段（figure 这类视图设置不在预设层里）"


def test_chip_payload_restores_the_preset_values(home):
    """服务端半边：`ENVPRESETS` 载荷 + 初值还原出来 = 该预设的环境（点 chip 该得到的东西）。

    前端 `presetForm()`（DEFAULTS + 差值）就是这个还原；这里用 Python 复算一遍，
    免得"差值编码"哪天把某个字段吃掉 —— 那种 bug 页面上只表现为"点 chip 没反应"。
    """
    for name, item in home["env"].items():
        if str(name).startswith("_"):          # `_keys` 是保留键（预设管的字段清单）
            continue
        form = dict(home["defaults"])
        form.update(item["d"])
        pre = presets_mod.resolve(name)
        scene = pre.scene_obj()
        for field_name in webui.FORM_SCENE_FIELDS:
            want = getattr(scene, field_name)
            got = form[field_name]
            assert str(got) == str(want), f"{name}.{field_name}：期望 {want!r}，还原出 {got!r}"
        assert form["env_preset"] == name
        assert form["standard"] == pre.standard and form["tier"] == pre.tier


def test_four_pages_share_one_skeleton_css():
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「index.html 引用 `/static/app.css`」→ 静态页一律相对路径（`./app.css`）→ 替代：test_static_pool_page::test_no_backend_and_no_root_absolute_paths（同一份 app.css 仍在用）
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """四页（首页 / 图3 / 查看器 / ——沙盒落地后照同一套）共用 `app.css` 的骨架。"""
    css = webui.read_page_file("app.css")
    for needle in (".shell{", ".shell.rail-collapsed", ".rail{", ".rail-toggle{",
                   ".rail-sec{", ".field-row{", ".chips{", ".chip{", ".chip.on{",
                   ".badge-dirty{", ".mainview{", "@media (max-width:900px)"):
        assert needle in css, f"app.css 缺少骨架规则 {needle!r}"
    for page in ("index.html", "fig3.html", "viewer3d.html"):
        body = webui.read_page_file(page)
        assert '<link rel="stylesheet" href="/static/app.css">' in body, \
            f"{page} 没有引用共用的 app.css"
    # 两个画布页也要那份骨架行为（折叠 + localStorage），所以加载同一个 app.js
    for page in ("fig3.html", "viewer3d.html"):
        assert '<script src="/static/app.js"></script>' in webui.read_page_file(page), \
            f"{page} 没有加载共用的左栏骨架脚本"


def test_skeleton_and_chip_contract_names():
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「app.js 里有 `presetForm/applyPreset/syncEnvChips` 等表单函数」→ 表单首页已删 → 替代：test_static_pool_page::test_four_pool_actions_have_named_functions
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """前端契约名（JS 不在 Python 里跑，行为另由 node 探针验）。"""
    js = webui.read_page_file("app.js")
    for needle in ("missile-sim:rail", "function applyRail", "function railStartCollapsed",
                   "function presetForm", "function applyEnvPreset", "function envDrift",
                   "function syncEnvChips", "data-env-preset", "data-preset",
                   "function sameValue"):
        assert needle in js, f"app.js 缺少 {needle!r}"
    # 两页共用 app.js ⟹ 里面不许对首页专有元素做无守卫的绑定（一抛后面全死）
    for guard in ('if ($("#bs"))', 'if ($("#bk"))', 'if ($("#bp"))'):
        assert guard in js, f"app.js 没有守卫 {guard}（图3/查看器页会整段抛掉）"


# --------------------------------------------------------------- 2. 行为（node）


def _run_probe(home, tmp_path) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器没有 node，跳过前端行为探针（Python 侧只钉契约名）")
    payload = {
        "html": home["html"],
        "defaults": webui.jsonable(home["defaults"]),
        "presets": webui.jsonable(home["presets"]),
        "envpresets": webui.jsonable(home["env"]),
    }
    page_json = Path(tmp_path) / "page.json"
    page_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run([node, str(PROBE), str(page_json), str(APP_JS)],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, f"探针跑挂了：\n{proc.stderr[-3000:]}"
    out = json.loads(proc.stdout)
    assert out.get("ok") is True, out
    return out


def test_chip_click_really_changes_the_request(home, tmp_path):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「点预置 chip 真的改请求体」→ 预置想定 + 提交链路删掉 → 替代：无（没有请求可改了）
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """**核心判据**：点环境预设 chip `close` ⇒ 输入框的值变 ⇒ 请求体变 ⇒ **求解器看到的想定变**。

    三层缺一不可：
    1. 输入框的值（用户看得见的）；
    2. `collect()` 的请求体（真发出去的那份）；
    3. 把那份请求体喂回 `form_to_request()`，看**服务端算出来的 Scene** ——
       2026-10-02 就是漏了第 3 层：输入框与请求体都显示 20000，可算出来还是 50 km，
       因为 `_dirty` 是空的，`targets.build_scene()` 会把"没点过名"的字段整片丢掉。
       **只验前两层的判据会放过一个纯装饰的 chip。**
    """
    out = _run_probe(home, tmp_path)
    before, after = out["before_chip"], out["after_chip"]
    # 点之前：默认预设的 50 km
    assert str(before["env_preset"]) == "default"
    assert float(before["range_m"]) == 50000.0
    assert float(before["body_range_m"]) == 50000.0
    # 点之后：近距预设的 20 km / 5 km —— 输入框与请求体**一起**变
    assert str(after["env_preset"]) == "close", after
    assert float(after["range_m"]) == 20000.0, after
    assert float(after["alt_m"]) == 5000.0, after
    assert float(after["body_range_m"]) == 20000.0, after
    assert float(after["body_alt_m"]) == 5000.0, after
    assert str(after["body_env_preset"]) == "close", after
    assert float(after["bg_alt_m"]) == 5000.0, "参考工况（预设层的一部分）没跟着换"
    assert after["active_chip"] == ["close"], "选中的 chip 没有高亮"
    assert after["badge_hidden"] is True, "刚点完 chip 就说『已偏离预设』？"
    assert out["chip_titles_filled"] is True, "chip 的悬停说明没从 boot 数据补上"
    # 第 2.5 层：chip 点过的字段必须上报为"手改"，否则服务端会把它们丢掉（见 docstring）
    dirty = str(after["body_dirty"] or "")
    for key in ("range_m", "alt_m", "env_preset"):
        assert key in dirty, f"{key} 没进 _dirty（服务端会丢弃这个值）：{dirty!r}"
    # 第 3 层：拿真请求体走一遍服务端，看 Scene
    body = dict(after["body_full"])
    req, scene = None, None
    req, scene, errors = webui.form_to_request(body, home["config"])
    assert errors == [], errors
    assert scene is not None
    assert float(scene.range_m) == 20000.0, \
        f"请求体写着 20000，服务端却算出 {scene.range_m}（chip 是装饰品）"
    assert float(scene.alt_m) == 5000.0, scene.alt_m
    assert req.env_preset == "close", req.env_preset


def test_manual_edit_marks_drifted_from_preset(home, tmp_path):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「手改字段标记『已偏离预设』」→ 表单首页已删 → 替代：无
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """手改一格 ⇒ 亮「已偏离预设」并点名是哪一格（否则那个徽标是死的）。

    同时钉住反例：改 `figure`（视图设置，不属于预设层）**不该**点灯 —— 否则恢复上次输入
    之后一进页面就报警，徽标沦为噪音（这版实现的第一稿就是这样）。
    """
    out = _run_probe(home, tmp_path)
    view = out.get("after_view_edit")
    assert view, out
    assert str(view["figure"]) == "all"
    assert view["badge_hidden"] is True, "改『出哪张图』被误判成偏离环境预设"
    edited = out["after_edit"]
    assert float(edited["range_m"]) == 33000.0
    assert float(edited["body_range_m"]) == 33000.0
    assert edited["badge_hidden"] is False, "手改了却还显示『没偏离』"
    assert "range_m" in str(edited["badge_title"]), edited["badge_title"]
    assert "figure" not in str(edited["badge_title"]), edited["badge_title"]


def test_preset_chip_also_fills_the_form(home, tmp_path):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「点 chip 回填表单值」→ 表单首页已删 → 替代：无
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """A1 的预置想定 chip 同样要真填值（尾追：敌机航向 180 → 0）。"""
    out = _run_probe(home, tmp_path)
    got = out.get("preset_chip")
    assert got, out
    assert str(got["preset"]) == "tail_chase", got
    assert float(got["body_range_m"]) == 20000.0, got
    assert float(got["body_target_heading_deg"]) == 0.0, got


def test_rail_collapse_is_remembered(home, tmp_path):
    # ⚠ Static 分支（2026-10-05 用户口径：左栏只留弹池）：
    #   老断言「折叠状态存 localStorage」→ 折叠行为仍在（`applyRail`/`missile-sim:rail`），但这条探针按表单首页的点法跑 → 替代：静态页里同一套键，待补一条只点 `#railtoggle` 的探针
    pytest.skip("Static 分支已按用户口径去掉表单首页（左栏只留弹池）")
    """折叠 ⇒ 加 `.rail-collapsed` + 写 `localStorage`；再点一次展开并回写。"""
    out = _run_probe(home, tmp_path)
    rail = out["rail"]
    assert rail["collapsed_class"] is True and rail["stored"] == "1"
    assert rail["aria"] == "false" and rail["glyph"] == "›"
    assert rail["expanded_again"] is True and rail["stored_after"] == "0"

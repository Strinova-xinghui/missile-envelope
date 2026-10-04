# -*- coding: utf-8 -*-
"""路径 A（纯静态图册）的判据。

被测对象是 `missile_sim.sitebuild`（薄壳 CLI 在 `scripts/build_static_site.py`）—— 把成品图打成可直接发布的静态图册。
⚠ 逻辑放 `src/` 而不是 `scripts/`：`scripts/` **不随分发包**，而这条判据要能在**包内自检**里跑。
本文件钉住四件事：

| 判据 | 为什么 |
| --- | --- |
| 只发两个 `_static` 变体（6 件图 + index + 口径页 + LICENSE，多一个都算红） | 用户口径：先只展示「不含等时线」的图1/图2 |
| **构建期闸门**：产物开关 `with_iso`/`with_scan` 为真 ⇒ 拒绝出站 | 2026-10-04 的 `_static` 陈旧事故就是这一族（发出去的是另一版） |
| **口径页只讲 γ**（定义 / 单位过载来历 / 参数出处 / 固有量 / 取倒数 / 派生量 / 边界 七件事齐全） | 用户 2026-10-04 口径：「实际需要讲清楚的只有 γ」 |
| **反向守卫**：口径页里不得出现实现级内容（导引律 / 控制环 / 高抛 / 惯量 / 大气密度 / 推进时序 / 终止事件…） | 该保的实现细节不外泄；防止以后有人"顺手把内核讲解贴进去" |
| 两页的引用全部存在且**零第三方**（不给 `--source-url` 时不许有任何外链） | 离线与"不依赖别人的 CDN"是本项目一贯纪律 |
| 可见文案里没有 markdown 星号；`LICENSE` 是 AGPL | 星号会原样显示（`NOTES.md` §25 起五次同类）；AGPL §4/§5 要求随附许可正文 |

**反证（真的演练）**：① `test_gate_refuses_the_isoline_variant` 把图1 的计划项换成
`fig_isotime_plane_default` + `plane_default.json`（**含等时线**的那一版），必须抛 `GateError`；
② `test_gate_refuses_an_unknown_placeholder` 往模板里塞 `{{nope}}`，必须抛 `GateError`。
若哪天闸门被写松，这两条立刻红。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import sitebuild as SITE  # noqa: E402

FIGURES = ("fig_isotime_plane_static", "fig_bg_plane_static")
FORMATS = ("png", "pdf", "svg")

pytestmark = pytest.mark.skipif(
    not all((ROOT / "figures" / f"{s}.{e}").is_file() for s in FIGURES for e in FORMATS),
    reason="figures/ 里的两个 _static 变体不在（先跑 scripts\\refresh_products.py）")


# ---------------------------------------------------------------- 1. 只发静态版

def test_site_contains_exactly_the_two_static_variants(tmp_path):
    """文件清单必须**恰好**是：index.html + method.html + LICENSE + 6 件图（每个变体三格式）。"""
    res = SITE.build(tmp_path / "site", source_url=None)
    got = sorted(p.relative_to(tmp_path / "site").as_posix() for p in res["written"])
    want = sorted(["index.html", "method.html", "LICENSE"]
                  + [f"figures/{s}.{e}" for s in FIGURES for e in FORMATS])
    assert got == want, got
    # 含等时线的 _default 变体一个都不许被打包
    for p in res["written"]:
        assert "_default" not in p.name, p


def test_shipped_figures_are_byte_identical_to_the_tracked_ones(tmp_path):
    """发出去的 PNG/PDF/SVG 必须与仓库里那两个同名文件逐字节相同（防"另存一版陈旧图"）。"""
    import hashlib

    res = SITE.build(tmp_path / "site", source_url=None)
    for p in res["written"]:
        if p.suffix in (".png", ".pdf", ".svg"):
            src = ROOT / "figures" / p.name
            assert hashlib.sha256(p.read_bytes()).hexdigest() == \
                hashlib.sha256(src.read_bytes()).hexdigest(), p.name


def test_gate_refuses_the_isoline_variant(tmp_path):
    """**反证**：把图1 换成含等时线的 `_default` 版 ⇒ 构建期闸门必须拒绝。"""
    bad = (("fig_isotime_plane_default", "plane_default.json", "图1", "t", "s", "n", "with_iso"),)
    with pytest.raises(SITE.GateError) as ei:
        SITE.build(tmp_path / "site", source_url=None, plan=bad)
    assert "不是「无等时线」的那一版" in str(ei.value)


def test_site_has_no_isolines_claiming_otherwise(tmp_path):
    """产物里连"等时线"三个字都不该出现在图注的肯定语气里：页面必须写"不含/未跑"。"""
    res = SITE.build(tmp_path / "site", source_url=None)
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "不含等时线" in html and "未跑仿真" in html


# ---------------------------------------------------------------- 2. 页面卫生

def _visible_text(html: str) -> str:
    """去掉 <style>/<script>/注释 —— 只留会渲染给读者的文本（与项目其它星号判据同口径）。"""
    body = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
    body = re.sub(r"<script[\s\S]*?</script>", "", body, flags=re.I)
    body = re.sub(r"<!--[\s\S]*?-->", "", body)
    return body


def test_pages_references_all_exist_and_are_local(tmp_path):
    """两页里每个 src/href 要么是同目录的相对路径且**存在**，要么是显式给的源码 URL。"""
    SITE.build(tmp_path / "site", source_url=None)
    for name in ("index.html", "method.html"):
        html = (tmp_path / "site" / name).read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="([^"]+)"', html)
        assert refs, f"{name} 里一个引用都没有？"
        for r in refs:
            assert not r.startswith(("http://", "https://", "//")), f"{name} 未给 source-url 却出现外链：{r}"
            assert (tmp_path / "site" / r).is_file(), f"{name} 引用不存在：{r}"
        # 未给 source-url 时不许有占位 URL
        assert "example.com" not in html and "<owner>" not in html


def test_pages_visible_text_has_no_markdown_marks(tmp_path):
    SITE.build(tmp_path / "site", source_url=None)
    for name in ("index.html", "method.html"):
        text = _visible_text((tmp_path / "site" / name).read_text(encoding="utf-8"))
        assert "**" not in text, name
        assert "`" not in text, name


def test_license_ships_and_is_agpl(tmp_path):
    SITE.build(tmp_path / "site", source_url=None)
    body = (tmp_path / "site" / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in body and "Version 3" in body
    assert "MIT License" not in body.splitlines()[0]


def test_source_link_appears_only_when_asked(tmp_path):
    """给了 --source-url 才写链接（AGPL §13 入口留在这里，而不是写死一个不存在的仓库）。"""
    SITE.build(tmp_path / "site-plain", source_url=None)
    url = "https://github.com/example/missile-sim"
    SITE.build(tmp_path / "site-src", source_url=url)
    for name in ("index.html", "method.html"):
        plain = (tmp_path / "site-plain" / name).read_text(encoding="utf-8")
        assert "github.com" not in plain, name
        assert f'href="{url}"' in (tmp_path / "site-src" / name).read_text(encoding="utf-8"), name


def test_page_header_metadata_is_read_from_products(tmp_path):
    """页头必须**现读**产物（内核版本/工况），不是手写常量；读错了会与 results 不一致。"""
    import json

    SITE.build(tmp_path / "site", source_url=None)
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    rec = json.loads((ROOT / "results" / "plane_static.json").read_text(encoding="utf-8"))
    ident = rec["solver"]
    assert ident["model"] in html and ident["version"] in html, "页头没带内核版本"
    assert "PL-12" in html


# ---------------------------------------------------------------- 3. 口径页：只讲 γ

#: 口径页必须讲清的七件事（用户 2026-10-04 口径：「实际需要讲清楚的只有 γ」）
GAMMA_MUST_HAVE = (
    "CxAoA / (SL² · CyK²)",         # γ 的定义式
    "drag_area", "lift_area",        # 两个面积的出处（取求解器的量，不另造口径）
    "n ≡ L / (m · g0)",             # 过载定义
    "sinα ∝ n",                     # n² 的来历
    "ginv = 1/γ",                   # 取倒数的读法
    "Q = √(β · γ · F/f)",           # 派生量：机动敏感度
    "n* = q / (Q · g0)",            # 临界过载
    "R = (n / n*)²",                # 机动惩罚比
    "β_eff = β / (1 + R)",          # 等效 BC
    "升力线性段", "CyMaxAoA",        # 适用边界
)

#: 口径页**不得**出现的实现级内容（该保的实现细节不外泄）
FORBIDDEN_WORDS = ("比例导引", "高抛", "四元数", "惯量", "大气密度", "发动机", "推力",
                   "终止事件", "kill_assessed", "time_limit", "proximity_fuse")
FORBIDDEN_RE = re.compile(r"\b(PN|PID|LOFT|Loft|loft)\b")


def test_method_page_explains_gamma_end_to_end(tmp_path):
    """口径页必须把 γ 讲全：定义 / 面积出处 / 单位过载来历 / n² / 取倒数 / 派生量 / 边界。"""
    SITE.build(tmp_path / "site", source_url=None)
    html = _visible_text((tmp_path / "site" / "method.html").read_text(encoding="utf-8"))
    missing = [s for s in GAMMA_MUST_HAVE if s not in html]
    assert not missing, f"口径页缺这些 γ 口径串：{missing}"


def test_method_page_has_no_implementation_details(tmp_path):
    """**反向守卫**：口径页不许出现实现级内容（导引律 / 控制环 / 高抛 / 惯量 / 推进时序 / 终止事件…）。"""
    SITE.build(tmp_path / "site", source_url=None)
    html = _visible_text((tmp_path / "site" / "method.html").read_text(encoding="utf-8"))
    hit = [w for w in FORBIDDEN_WORDS if w in html]
    assert not hit, f"口径页混进了实现级词：{hit}"
    m = FORBIDDEN_RE.search(html)
    assert m is None, f"口径页混进了实现级缩写：{m.group(0)!r}"


def test_method_page_values_come_from_products(tmp_path):
    """口径页的数字必须**现读产物**注入：与 results 逐值一致，且没有占位符残留。"""
    import json

    SITE.build(tmp_path / "site", source_url=None)
    html = (tmp_path / "site" / "method.html").read_text(encoding="utf-8")
    assert "{{" not in html and "}}" not in html, "占位符没替换干净"
    bgp = json.loads((ROOT / "results" / "bg_static.json").read_text(encoding="utf-8"))
    std = bgp["standard"]
    pt = next(p for p in bgp["points"] if p["label"] == std or p["key"] == std)
    assert f"{float(pt['beta']):,.1f}" in html
    assert f"{float(pt['gamma']):,.2f}" in html
    assert f"{float(pt['ginv']):.5f}" in html
    assert f"{float(pt['n_star']):,.2f}" in html
    gmin = min(float(p["ginv"]) for p in bgp["points"])
    gmax = max(float(p["ginv"]) for p in bgp["points"])
    assert f"{gmin:.5f}" in html and f"{gmax:.5f}" in html
    plane = json.loads((ROOT / "results" / "plane_static.json").read_text(encoding="utf-8"))
    assert plane["solver"]["model"] in html and plane["solver"]["version"] in html


def test_method_page_has_disclaimer_and_license(tmp_path):
    """口径页必须自带边界声明：独立社区项目 / 无隶属 / 数据权利归 Gaijin / AGPL / 勿用于 bug 上报。"""
    SITE.build(tmp_path / "site", source_url=None)
    html = _visible_text((tmp_path / "site" / "method.html").read_text(encoding="utf-8"))
    for s in ("独立的社区研究项目", "Gaijin", "没有任何隶属", "不分发任何游戏数据",
              "AGPL-3.0-only", "请勿用于 bug 上报"):
        assert s in html, f"口径页缺声明：{s}"


def test_index_links_to_method_page(tmp_path):
    """首页必须有到口径页的入口，且那个链接在本站里存在。"""
    SITE.build(tmp_path / "site", source_url=None)
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert 'href="method.html"' in html


def test_page_carries_the_text_moved_out_of_the_figures(tmp_path):
    """用户口径：图内批注全部移到页面 ⇒ 页面必须**逐条**带上，且出处是 `figures`（单一出处）。

    这条与 `-k figures_bg` 的「这些文本不许出现在图里」是一对：一个管图外有、一个管图内无。
    """
    from missile_sim import figures

    SITE.build(tmp_path / "site", source_url=None)
    html = _visible_text((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    # 图1：说明文本（弹数由产物现算）
    assert figures.plane_notes(11)[0] in html, "图1 的说明文本没搬到页面"
    # 图2：四段口径 + 读法 + 仿真层定义 + 状态句
    for line in figures.BG_FOOTNOTES:
        assert line in html, f"图2 口径段没搬到页面：{line[:24]}…"
    assert figures.BG_READ_NOTE in html
    assert "仿真层：固定 ΔV=" in html
    assert figures.bg_scan_note(False) in html, "「本次未跑仿真层」那句没在页面上"
    # 并声明这些文字是「原先画在图里」的
    assert "原先画在图里" in html


def test_gate_refuses_an_unknown_placeholder(tmp_path):
    """**反证**：模板里塞一个白名单外的占位符 ⇒ 渲染必须拒绝（不许把 `{{...}}` 发上线）。"""
    bad = SITE.METHOD_PAGE + "\n<p>{{nope}}</p>\n"
    with pytest.raises(SITE.GateError) as ei:
        SITE.render_method(SITE.read_site_facts(root=ROOT), source_url=None, template=bad)
    assert "未替换的占位符" in str(ei.value)


# ---------------------------------------------------------------- 4. 静态托管版（Static 分支）

def _stripped(root=ROOT):
    """壳那边的静态化落地了没有（页面里不许再有服务端占位符）。"""
    p = root / "src" / "missile_sim" / "webui_static" / "index.html"
    return p.is_file() and "__FIG1NOTES__" not in p.read_text(encoding="utf-8")


def _asset_problems(root=ROOT):
    """`APP_ASSETS` 里还没过"静态化闸门"的条目（空 = 两块都落地了，可以真组装）。"""
    d = root / "src" / "missile_sim" / "webui_static"
    out = []
    for name in SITE.APP_ASSETS:
        p = d / name
        if not p.is_file():
            out.append(f"{name}: 不在")
            continue
        out.extend(SITE.check_app_asset(name, p.read_text(encoding="utf-8")))
    return out


def test_static_app_gate_has_teeth():
    """**反证**：路径/占位符闸门必须抓得住后端路径、绝对引用、没冻结的占位符。"""
    check = SITE.check_app_asset
    assert check("app.js", 'fetch("/api/catalog")'), "后端路径没被抓到"
    assert check("index.html", '<script src="/static/app.js"></script>'), "绝对 /static 引用没被抓到"
    assert check("index.html", '<img src="https://cdn.example/a.png">'), "外链没被抓到"
    assert check("index.html", "<!--__FIG1NOTES__-->"), "没冻结的占位符没被抓到"
    assert check("app.js", 'fetch("./catalog.json")') == []      # 相对路径必须放行
    assert check("app.js", 'x.setAttribute("href", "./method.html")') == []


def test_static_app_ships_only_relative_paths_and_static_json(tmp_path):
    """组装出来的静态托管版：页面资源全部相对、零 `/api`、目录与图注都是**静态 JSON**。"""
    _missing = _asset_problems()
    if _missing:
        pytest.skip("Static 分支的静态化还没全部落地（先跑 -k static_site 的闸门）："
                    + "；".join(_missing[:3]))
    res = SITE.build_static_app(tmp_path / "app", source_url=None)
    got = sorted(p.relative_to(tmp_path / "app").as_posix() for p in res["written"])
    for name in ("index.html", "app.css", "app.js", "figs2d.js", "figs2d.css",
                 "fig3.js", "catalog.json", "notes.json", "method.html", "LICENSE"):
        assert name in got, f"静态托管版少了 {name}"
    for name in SITE.APP_ASSETS:
        text = (tmp_path / "app" / name).read_text(encoding="utf-8")
        assert SITE.check_app_asset(name, text) == [], f"{name} 没过路径/占位符闸门"


def test_static_app_catalog_and_notes_come_from_the_single_source(tmp_path):
    """目录与图注都**复用壳那边的单一出处**（不是本模块另写一份）。"""
    import json

    from missile_sim import figures

    _missing = _asset_problems()
    if _missing:
        pytest.skip("Static 分支的静态化还没全部落地（先跑 -k static_site 的闸门）："
                    + "；".join(_missing[:3]))
    res = SITE.build_static_app(tmp_path / "app2", source_url=None)
    pay = json.loads((tmp_path / "app2" / "catalog.json").read_text(encoding="utf-8"))
    notes = json.loads((tmp_path / "app2" / "notes.json").read_text(encoding="utf-8"))
    assert pay["computable"] == 159 and pay["count"] == 168
    assert len(pay["unsupported"]) == 9 and pay["unsupported"][0]["reason"] == "需要动态解算"
    for key in ("xlabel", "ylabel", "xlabel_bg", "ylabel_bg", "point_color", "nstar_levels"):
        assert key in pay["style"], f"目录 style 缺 {key}"
    assert notes["title"] == SITE.NOTES_TITLE
    assert notes["fig1"][0] == figures.plane_notes(11)[0]
    assert notes["fig2"][0] == figures.BG_FOOTNOTES[0]
    assert notes["fig2"][-1] == figures.bg_scan_note(False)

# -*- coding: utf-8 -*-
"""路径 A（纯静态图册）的判据。

被测对象是 `missile_sim.sitebuild`（薄壳 CLI 在 `scripts/build_static_site.py`）—— 把成品图打成可直接发布的静态图册。
⚠ 逻辑放 `src/` 而不是 `scripts/`：`scripts/` **不随分发包**，而这条判据要能在**包内自检**里跑。
本文件钉住四件事：

| 判据 | 为什么 |
| --- | --- |
| 只发两个 `_static` 变体（6 件图 + index + LICENSE，多一个都算红） | 用户口径：先只展示「不含等时线」的图1/图2 |
| **构建期闸门**：产物开关 `with_iso`/`with_scan` 为真 ⇒ 拒绝出站 | 2026-10-04 的 `_static` 陈旧事故就是这一族（发出去的是另一版） |
| 页面的引用全部存在且**零第三方**（不给 `--source-url` 时不许有任何外链） | 离线/免安装与"不依赖别人的 CDN"是本项目一贯纪律 |
| 可见文案里没有 markdown 星号；`LICENSE` 是 AGPL | 星号会原样显示（`NOTES.md` §25 起五次同类）；AGPL §4/§5 要求随附许可正文 |

**反证（真的演练）**：`test_gate_refuses_the_isoline_variant` 把图1 的计划项换成
`fig_isotime_plane_default` + `plane_default.json`（**含等时线**的那一版），必须抛 `GateError`；
若哪天闸门被写松，这条立刻红。
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
    """文件清单必须**恰好**是：index.html + LICENSE + 6 件图（每个变体三格式）。"""
    res = SITE.build(tmp_path / "site", source_url=None)
    got = sorted(p.relative_to(tmp_path / "site").as_posix() for p in res["written"])
    want = sorted(["index.html", "LICENSE"]
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


def test_index_references_all_exist_and_are_local(tmp_path):
    """页面里每个 src/href 要么是同目录的相对路径且**存在**，要么是显式给的源码 URL。"""
    res = SITE.build(tmp_path / "site", source_url=None)
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert refs, "index.html 里一个引用都没有？"
    for r in refs:
        assert not r.startswith(("http://", "https://", "//")), f"未给 source-url 却出现外链：{r}"
        assert (tmp_path / "site" / r).is_file(), f"引用不存在：{r}"
    # 未给 source-url 时不许有占位 URL
    assert "example.com" not in html and "<owner>" not in html


def test_index_visible_text_has_no_markdown_marks(tmp_path):
    SITE.build(tmp_path / "site", source_url=None)
    text = _visible_text((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    assert "**" not in text
    assert "`" not in text


def test_license_ships_and_is_agpl(tmp_path):
    SITE.build(tmp_path / "site", source_url=None)
    body = (tmp_path / "site" / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in body and "Version 3" in body
    assert "MIT License" not in body.splitlines()[0]


def test_source_link_appears_only_when_asked(tmp_path):
    """给了 --source-url 才写链接（AGPL §13 入口留在这里，而不是写死一个不存在的仓库）。"""
    SITE.build(tmp_path / "site-plain", source_url=None)
    plain = (tmp_path / "site-plain" / "index.html").read_text(encoding="utf-8")
    assert "github.com" not in plain
    url = "https://github.com/example/missile-sim"
    SITE.build(tmp_path / "site-src", source_url=url)
    with_src = (tmp_path / "site-src" / "index.html").read_text(encoding="utf-8")
    assert f'href="{url}"' in with_src


def test_page_header_metadata_is_read_from_products(tmp_path):
    """页头必须**现读**产物（内核版本/工况），不是手写常量；读错了会与 results 不一致。"""
    import json

    SITE.build(tmp_path / "site", source_url=None)
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    rec = json.loads((ROOT / "results" / "plane_static.json").read_text(encoding="utf-8"))
    ident = rec["solver"]
    assert ident["model"] in html and ident["version"] in html, "页头没带内核版本"
    assert "PL-12" in html

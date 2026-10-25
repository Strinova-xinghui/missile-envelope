"""backend.js 构建期注入的判据（Lead 2026-10-05 裁决，见 docs/STAGE-C.md §2）。

规则：
- **配置了 `api_base`** ⇒ 生成 `backend.js`（`window.__BACKEND__ = {api_base, enabled}`）
  且 `index.html` 在 `catalog.js` 之前引用它（`backend.js` 必须在 `app.js` 读取 `__BACKEND__` 之前 ✓）。
- **没配置** ⇒ 不生成、不引用 ⇒ 无后端时页面与纯静态版**逐字节等价、零请求** ✓。
"""

import pathlib

import pytest

from missile_sim import sitebuild

OUT = pathlib.Path("build/site-app")


def _build(tmp_path, **kw):
    return sitebuild.build_static_app(pathlib.Path(tmp_path) / "app", **kw)


def test_backend_js_is_generated_and_wired_when_api_base_given(tmp_path):
    res = _build(tmp_path, source_url=None, api_base="http://127.0.0.1:8099", backend_enabled=True)
    names = sorted(p.name for p in res["written"])
    assert "backend.js" in names, f"配置了 api_base 却没生成 backend.js：{names}"
    bj = (pathlib.Path(tmp_path) / "app" / "backend.js").read_text(encoding="utf-8")
    assert '"api_base":"http://127.0.0.1:8099"' in bj, bj[:200]
    assert '"enabled":true' in bj, bj[:200]
    idx = (pathlib.Path(tmp_path) / "app" / "index.html").read_text(encoding="utf-8")
    assert '<script src="./backend.js">' in idx, "index.html 没有引用 backend.js"
    _src_order = [m.group(1) for m in __import__("re").finditer(r'<script[^>]*src="([^"]+)"', idx)]
    # 2026-10-25：页面脚本现在带内容指纹（`?v=<hash>`）用于击穿 CDN 缓存，
    # 所以比较时要先剥掉查询串；backend.js 由构建期单独生成，**不带**指纹。
    _bare = [s.split("?")[0] for s in _src_order]
    assert _bare[:2] == ["./backend.js", "./catalog.js"], (
        "backend.js 必须是第一个页面脚本且在 catalog.js 之前（app.js 读 __BACKEND__ 要在数据到达之前）；"
        "实际顺序：" + repr(_src_order))


def test_no_backend_means_no_backend_js_at_all(tmp_path):
    res = _build(tmp_path, source_url=None)  # 不传 api_base
    names = sorted(p.name for p in res["written"])
    assert "backend.js" not in names, "未配置后端却生成了 backend.js ✗"
    idx = (pathlib.Path(tmp_path) / "app" / "index.html").read_text(encoding="utf-8")
    assert "backend.js" not in idx, "index.html 不该引用 backend.js"


def test_api_base_must_be_http_or_https(tmp_path):
    with pytest.raises(Exception):
        _build(pathlib.Path(tmp_path) / "app2", source_url=None, api_base="ftp://x")
    with pytest.raises(Exception):
        _build(pathlib.Path(tmp_path) / "app3", source_url=None, api_base="not-a-url")

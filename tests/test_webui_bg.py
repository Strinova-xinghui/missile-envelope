# -*- coding: utf-8 -*-
"""图2 在 WebUI 上的端到端验收：**真起 `http.server` + `http.client`**。

与 `test_webui.py` 同款做法（不搭桩、只把产物目录指到 `.tmp_test/`），
只测图2 那条新路：

* 表单新增的 7 个字段必须过 `build_scene_from_form()`（`figure` / `bg_alt_m` 这些
  是 **Web 层专名**，忘了加进 `WEB_ONLY_KEYS` 就会被 `targets.build_scene()` 判成非法输入）；
* `figure=bg` 时 `kind=scan` 提交的是 `BgRequest`，`kind=plot` 是不带仿真层的；
* 结果面板拿到的 `figure == "bg"`（JS 靠它选渲染分支），且 β/γ 列名、双向单调性都在。
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import webui  # noqa: E402

TMP = ROOT / ".tmp_test" / f"webui_bg_{uuid.uuid4().hex[:8]}"
PORT = 0                                     # 见 test_webui.py：固定端口在 Windows 上会假成功

#: 粗网格：图2 的默认网格是 ~1000 工况，验收用 4×4 足够验链路
SMALL_BG = {"beta_step": "400", "gamma_step": "15", "iso_step": "1"}

DEFAULT_FORM = {
    "range_m": "50000", "alt_m": "10000", "vm0": "300",
    "launch_heading_deg": "0", "launch_pitch_deg": "0",
    "target_heading_deg": "180", "target_pitch_deg": "0",
    "target_speed_ms": "300", "target_alt_m": "",
    "target_bearing_deg": "0", "duration_s": "150",
    "standard": "PL-12", "tier": "fast", "jobs": "1", "tag": "wbg",
    "figure": "bg", "dv_pin": "", "n_ref": "20", "bg_alt_m": "", "bg_speed_ms": "",
}


def _config() -> dict:
    return {
        "host": "127.0.0.1", "port": PORT, "tier": "fast", "jobs": 1,
        "formats": ["png"], "cache": False,
        "figure_dir": str(TMP / "figures"), "result_dir": str(TMP / "results"),
        "tag": "wbg", "poll_ms": 100,
    }


@pytest.fixture(scope="module")
def web():
    TMP.mkdir(parents=True, exist_ok=True)
    httpd = webui.serve("127.0.0.1", PORT, block=False, config=_config(), quiet=True)
    try:
        yield ("127.0.0.1", int(httpd.server_address[1]))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(TMP, ignore_errors=True)


def _get(addr, path):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type") or ""
    finally:
        conn.close()


def _post_json(addr, path, form):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=120)
    try:
        conn.request("POST", path, body=json.dumps(form, ensure_ascii=False).encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


def _poll(addr, job_id, timeout=600.0):
    t0 = time.time()
    seen = []
    while True:
        status, raw, _ = _get(addr, "/progress/" + job_id)
        assert status == 200, status
        snap = json.loads(raw.decode("utf-8"))
        seen.append((snap.get("state"), snap.get("done"), snap.get("total")))
        if snap.get("state") in ("done", "error"):
            return snap, seen
        assert time.time() - t0 < timeout, f"任务超时：{seen[-5:]}"
        time.sleep(0.2)


# --------------------------------------------------------------------- 用例


def test_page_exposes_the_beta_gamma_fields(web):
    """页面必须真的渲染出图2 的 7 个字段（后端 Field 表 → 模板占位符 → HTML）。"""
    status, raw, ctype = _get(web, "/")
    assert status == 200 and "text/html" in ctype
    html = raw.decode("utf-8")
    for name in ("figure", "beta_step", "gamma_step", "dv_pin", "n_ref",
                 "bg_alt_m", "bg_speed_ms"):
        assert f'data-field="{name}"' in html, f"页面缺少字段 {name}"
    for label in ("出哪张图", "β 网格步长", "γ 网格步长", "参考工况高度"):
        assert label in html, f"页面缺少标签 {label!r}"
    assert "__BGROWS__" not in html, "模板占位符没被替换掉"


def test_form_to_bg_request_accepts_the_page_defaults():
    """表单默认值（参考工况留空）必须解析成"用参考图口径"，**不是 0**。"""
    req, scene, errors = webui.form_to_bg_request(dict(DEFAULT_FORM), _config(),
                                                  with_scan=False)
    assert errors == [], errors
    assert scene is not None and scene.range_m == 50000.0
    assert req.alt_m is None and req.speed_ms is None       # 留空 ⇒ 用默认 10 km / 800 m/s
    assert req.dv_pin is None and req.n_ref == 20.0
    assert req.with_scan is False


def test_form_to_bg_request_separates_reference_from_launch_altitude():
    """`bg_alt_m`（参考工况）与 `alt_m`（载机高度）在表单上必须是两个量。"""
    form = dict(DEFAULT_FORM, bg_alt_m="3000", alt_m="7000")
    req, scene, errors = webui.form_to_bg_request(form, _config(), with_scan=False)
    assert errors == [], errors
    assert req.alt_m == 3000.0 and req.scene.alt_m == 7000.0
    assert scene.alt_m == 7000.0


def test_form_to_bg_request_rejects_bad_numbers_and_missiles():
    bad = dict(DEFAULT_FORM, beta_step="0")
    _req, _scene, errors = webui.form_to_bg_request(bad, _config(), with_scan=False)
    assert any("β 网格步长" in e for e in errors), errors
    bad = dict(DEFAULT_FORM, standard="R-77X")
    _req, _scene, errors = webui.form_to_bg_request(bad, _config(), with_scan=False)
    assert errors, "弹名不在池里必须拦下"


def test_webui_bg_plot_job_lands_a_figure(web):
    """`figure=bg` + `kind=plot`：出参考图那一套，结果带 `figure == "bg"`。"""
    status, payload = _post_json(web, "/api/submit", dict(DEFAULT_FORM, kind="plot"))
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["figure"] == "bg" and payload["with_iso"] is False
    snap, _seen = _poll(web, payload["id"])
    assert snap["state"] == "done", (snap["state"], snap["error"])
    r = snap["result"]
    assert r["figure"] == "bg" and r["with_iso"] is False
    assert r["n_cases"] == 0 and r["dv_pin"] is not None
    assert r["reference"]["alt_m"] == 10000.0 and r["reference"]["speed_ms"] == 800.0
    assert len(r["missiles"]) == 11
    assert r["paths"]["points"].endswith(".csv")
    assert "cases" not in r["paths"]
    assert r["figure_urls"], r
    status, raw, ctype = _get(web, r["figure_urls"][0])
    assert status == 200 and "image/png" in ctype
    assert raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 10_000


def test_webui_bg_scan_job_progresses_and_lands_beta_gamma_products(web):
    """`figure=bg` + `kind=scan`：后台任务走到 100%，产物用 β/γ 列名。"""
    form = dict(DEFAULT_FORM, kind="scan", **SMALL_BG)
    status, payload = _post_json(web, "/api/submit", form)
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["with_iso"] is True and payload["figure"] == "bg"
    snap, seen = _poll(web, payload["id"])
    assert snap["state"] == "done", (snap["state"], snap["error"], seen[-5:])
    assert snap["percent"] == 100.0, snap
    n = snap["result"]["n_cases"]
    assert n > 0 and snap["total"] == n, (snap["done"], snap["total"], n, seen)

    r = snap["result"]
    assert r["with_iso"] is True and r["n_cases"] == n
    assert 0 < r["n_hit"] <= n
    assert r["backend"], "backend 必须来自真跑过的 summary"
    assert r["monotonic_beta"]["n_non_monotonic"] == 0, r["monotonic_beta"]
    assert r["monotonic_gamma"]["n_non_monotonic"] == 0, r["monotonic_gamma"]
    assert r["t_hit_range_s"] and r["t_hit_range_s"][1] > r["t_hit_range_s"][0]

    # 产物真的落盘、且列名是 β/γ（不是 dv/bc）
    cases = Path(r["paths"]["cases"])
    assert cases.is_file()
    head = cases.read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith("beta_target,gamma_target,thrust_scale,cx_scale,cxaoa_scale"), head


def test_webui_still_serves_figure_one_when_figure_is_plane(web):
    """默认 `figure=plane` 那条路没被图2 的改动带坏。"""
    form = dict(DEFAULT_FORM, figure="plane", kind="plot", xlim="900,1200", ylim="3000,3300")
    status, payload = _post_json(web, "/api/submit", form)
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["figure"] == "plane"
    snap, _seen = _poll(web, payload["id"])
    assert snap["state"] == "done", (snap["state"], snap["error"])
    r = snap["result"]
    # 2026-09-30：`summarize_plane()` 现在**显式**写 `"figure": "plane"`（D10②）。
    # 旧断言用"缺 `figure` 键"来认图1，那是个隐式契约 —— 已改成认显式值。
    assert r.get("figure") == "plane" and r["paths"]["manifest"].endswith(".json")
    assert r["figure_urls"], r


def test_webui_rejects_an_unknown_figure(web):
    status, payload = _post_json(web, "/api/submit",
                                 dict(DEFAULT_FORM, figure="cube", kind="scan"))
    assert status == 400 and payload["ok"] is False, (status, payload)
    assert any("figure" in e for e in payload["errors"]), payload

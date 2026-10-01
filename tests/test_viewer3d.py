# -*- coding: utf-8 -*-
"""3D 轨迹查看器（`traj3d.py` + `GET /viewer3d` + `GET /api/viewer3d/<job_id>`）的验收。

分三层，各自都能单独跑：

1. **数据层**（毫秒级、不碰求解器）：`traj3d.build()` 的字段契约、默认 **800** 点、上限校验、
   抽稀**必须保留阶段拐点与节点时刻**、配色确实取自 `figures`（`TRAJ_COLORS` …）；
2. **HTTP 层**（真起服务 + `http.client`）：新路由的状态码与 JSON、静态白名单仍 fail-closed；
3. **前端契约**（读文本 + 有 node 就真跑一遍 JS）：模板里零第三方 URL、拖动方向只有一处符号、
   `dragFollowCheck()` 给出"跟手"的数（正拖为正、镜像精确取负）。

数据来自仓库自带的图3 产物 `results/traj_default_*`（**已入库**），所以这些用例**不跑求解器**；
"这个接口不解算"另由 `test_webui_viewer3d_solver_run_is_never_called` 把一个"一被调用就炸"的桩
塞进 `solver.run` 来钉死。

实测（本机，默认工况 3322 行 → 800 点，`json.dumps(separators=(',',':'))`）：

| 点数 | 响应字节 | 备注 |
| --- | --- | --- |
| 800（默认） | 53 201 B | 页面内嵌的就是它 |
| 1200 | 78 340 B | `?points=1200` |
| 4000（上限） | 206.8 kB | 原始只有 3322 行 ⇒ 到顶就是全部点 |
"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import figures, solver, traj3d, webui  # noqa: E402

#: 仓库自带的图3 产物（PL-12 / 50 km / 16 km 开机 / crank 8 s 70°@9G）。
PRODUCTS = {
    "missile": str(ROOT / "results" / "traj_default_missile.csv"),
    "target": str(ROOT / "results" / "traj_default_target.csv"),
    "segments": str(ROOT / "results" / "traj_default_segments.csv"),
    "manifest": str(ROOT / "results" / "traj_default.json"),
}
#: 黄金值（`tests/test_traj.py` 锁的同一组，见 AGENTS.md §图3）。
T_BEAM_S = 34.4583
T_HIT_S = 69.172
#: 开机后 1 s（反应延迟）转入 39 的拐点：阶段色 red → teal 就切在这里。
#: 响应里的时间是 3 位小数（34.458），原始行是 4 位（34.4583），对边界一律用**响应里的值**比对。
CORNER_S = 35.458
RAW_ROWS = 3322


@pytest.fixture(scope="module")
def web3d():
    """起一个**自己的**服务（`state` 由本文件持有，方便塞假任务）。

    不用 `webui.serve()`：那会顺带起预热线程（白导一次 matplotlib），这里不需要。
    """
    cfg = {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1,
           "formats": ["png"], "cache": False, "tag": "v3d", "poll_ms": 100}
    state = webui.WebState(cfg, quiet=True)
    httpd = webui.make_server("127.0.0.1", 0, state=state, quiet=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield ("127.0.0.1", int(httpd.server_address[1])), state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(addr, path):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type") or ""
    finally:
        conn.close()


def _get_json(addr, path):
    status, raw, _ctype = _get(addr, path)
    return status, json.loads(raw.decode("utf-8")), raw


def _inject(state, *, state_name="done", result=None, error=""):
    """往任务表里塞一个"已经跑完"的假任务：产物路径指向仓库里那三份 CSV。"""
    job = state.jobs.create("plot")
    job.state = state_name
    job.error = error
    job.result = result
    return job.id


def _traj_summary(**over):
    body = {"ok": True, "figure": "traj", "tag": "default", "preview": False,
            "paths": dict(PRODUCTS)}
    body.update(over)
    return body


def _nearest(seq, target):
    return min(seq, key=lambda v: abs(v - target))


def _nearest_idx(seq, target):
    return min(range(len(seq)), key=lambda i: abs(seq[i] - target))


# ============================================================ 1. 数据层


def test_webui_viewer3d_payload_contract():
    """字段契约：默认 800 点、两段导弹、目标分段带颜色键、节点、以及来自 `figures` 的配色。"""
    for name, path in PRODUCTS.items():
        assert Path(path).is_file(), f"仓库自带产物缺失：{name} = {path}（`--figure traj --tag default` 可重出）"
    d = traj3d.build(dict(PRODUCTS), points=traj3d.DEFAULT_POINTS, job="demo")

    assert d["ok"] is True
    assert d["points"] == {"requested": 800, "missile": 800, "target": 800}
    assert d["rows"] == {"missile": RAW_ROWS, "target": RAW_ROWS}
    assert d["t_beam_s"] == pytest.approx(T_BEAM_S, abs=0.001)
    assert d["t_hit_s"] == pytest.approx(T_HIT_S, abs=0.001)
    assert d["hit"] is True
    assert d["missile_name"] == "PL-12"
    assert d["axis_note"].startswith("x / z 是水平面")

    # 导弹：两段（t < t_beam / t >= t_beam），共享切分点 ⇒ 画出来不断线
    mis = d["missile"]
    split = mis["split_index"]
    assert 0 < split < len(mis["t"]), split
    assert mis["t"][split - 1] < d["t_beam_s"] <= mis["t"][split]
    assert mis["t"][split] == min([t for t in mis["t"] if t >= d["t_beam_s"]])
    assert mis["before_color"] != mis["after_color"]

    # 目标：分段来自产物 CSV，颜色键 → 颜色必须落在 `figures.TRAJ_COLORS` 上
    keys = [s["color_key"] for s in d["segments"]]
    assert keys == ["grey", "orange", "red", "teal", "blue"], keys
    for s in d["segments"]:
        assert s["color"] == figures.TRAJ_COLORS[s["color_key"]], s
    assert d["segments"][-1]["t1"] == pytest.approx(T_HIT_S, abs=0.001)

    # 节点 6 个（`traj.build_marks`），位置既有目标航迹上的、也有导弹航迹上的
    names = [m["name"] for m in d["marks"]]
    assert names == ["launch", "crank_start", "crank_done", "seeker_on", "beam_start", "end"]
    for m in d["marks"]:
        assert len(m["target"]) == 3 and len(m["missile"]) == 3, m

    # 配色**源头就是 figures**（前端一个颜色字面量都不写）
    c = d["colors"]
    assert c["segments"] == figures.TRAJ_COLORS
    assert c["missile_after"] == figures.TRAJ_MISSILE_COLOR
    assert c["mark"] == figures.TRAJ_MARK_COLOR
    assert c["hit"] == figures.TRAJ_HIT_COLOR
    assert c["miss"] == figures.TRAJ_MISS_COLOR
    assert c["fallback"] == figures.TRAJ_FALLBACK_COLOR
    assert c["missile_before"] == traj3d.mix_hex(figures.TRAJ_MISSILE_COLOR, traj3d.LIGHT_BG,
                                                 traj3d.MISSILE_MIX)


def test_webui_viewer3d_points_default_and_over_limit():
    """`?points=`：默认 800、可覆盖、有上限；非法值**报错**而不是静默截断。"""
    assert traj3d.parse_points(None) == 800
    assert traj3d.parse_points("") == 800
    assert traj3d.parse_points("1200") == 1200
    assert traj3d.parse_points(str(traj3d.MAX_POINTS)) == traj3d.MAX_POINTS
    for bad in ("4001", "0", "1", "-1", "abc", "800.0", "+800", "1e3", "800px"):
        with pytest.raises(ValueError):
            traj3d.parse_points(bad)
    # 抽稀后的点数**恰好**不超过请求值（不是"大约"）
    for n in (2, 100, 800, 1200, traj3d.MAX_POINTS):
        d = traj3d.build(dict(PRODUCTS), points=n)
        assert d["points"]["missile"] <= n and d["points"]["target"] <= n, n
        assert d["points"]["missile"] == min(n, RAW_ROWS), n


def test_webui_viewer3d_decimation_keeps_segment_corners_and_marks():
    """抽稀**必须**留下阶段边界与节点时刻所在的采样点。

    这是这张图的核心信息：crank→39 的拐点如果被抽掉，图上就只剩一条"弯回来的线"，
    看不出"开机后 1 s 才转"。判据用**全局最近采样**：抽稀集里离边界最近的那个点，
    必须就是原始行里离边界最近的那个点（等间隔抽稀恰好会抽掉它 ⇒ 见下面那条反证）。
    """
    d = traj3d.build(dict(PRODUCTS), points=800)
    raw_t = [float(r["t_s"]) for r in traj3d.read_csv_rows(PRODUCTS["target"])]
    kept = d["target"]["t"]
    assert len(kept) == 800 < len(raw_t)

    edges = set()
    for s in d["segments"]:
        for edge in (s["t0"], s["t1"]):
            if edge is not None:
                edges.add(edge)
    for m in d["marks"]:
        edges.add(m["t_s"])
    for edge in sorted(edges):
        best_raw = _nearest(raw_t, edge)
        # 抽稀集里的守护判据：原始行里离边界最近的那个采样点，**必须原样还在抽稀集里**
        # （响应里的时间落到 3 位小数，所以按同样的精度比；行距 ~0.02 s，不会撞精度）。
        assert round(best_raw, 3) in kept, (
            f"边界 {edge}s 的最近采样 {best_raw} 被抽掉了（抽稀后最近的是 "
            f"{_nearest(kept, edge)}）")

    # 拐点（red → teal，开机后 1 s 的 39 指令）就在抽稀集里，且**颜色正好切在它上面**
    assert CORNER_S in kept, f"拐点 {CORNER_S}s 不在抽稀后的时间里"
    i = kept.index(CORNER_S)
    before = [s for s in d["segments"] if s["t1"] == CORNER_S][0]
    after = [s for s in d["segments"] if s["t0"] == CORNER_S][0]
    assert before["color"] == figures.TRAJ_COLORS["red"]
    assert after["color"] == figures.TRAJ_COLORS["teal"]
    assert kept[i - 1] >= before["t0"] and kept[i + 1] <= after["t1"]

    # 反证：纯等间隔抽稀（老 `make_viewer_data.py` 的做法）会把这个拐点丢掉 ——
    # 所以上面那条断言不是"随便放个点都能过"。
    naive = {round(j * (len(raw_t) - 1) / (800 - 1)) for j in range(800)}
    assert _nearest_idx(raw_t, CORNER_S) not in naive, "这条反证失效了（换数据后要重挑判据）"


def test_webui_viewer3d_solver_run_is_never_called(web3d):
    """接口**只读产物**：把 `solver.run` 换成"一被调用就炸"，数据照样出得来（数据层 + HTTP 层各一遍）。"""
    addr, state = web3d
    calls = []
    original = solver.run

    def boom(*args, **kwargs):                                   # pragma: no cover - 不该被调用
        calls.append((args, kwargs))
        raise AssertionError("3D 查看器接口不该调用 solver.run")

    solver.run = boom
    try:
        d = traj3d.build(dict(PRODUCTS), points=800, job="demo")
        assert d["points"]["missile"] == 800
        job = _inject(state, result=_traj_summary())
        status, body, _raw = _get_json(addr, f"/api/viewer3d/{job}")
        assert status == 200 and body["points"]["missile"] == 800
        status, body, _raw = _get_json(addr, f"/api/viewer3d/{job}?points=1200")
        assert status == 200 and body["points"]["target"] == 1200
    finally:
        solver.run = original
    assert calls == []
    assert solver.run is original


def test_webui_viewer3d_paths_of_picks_the_traj_part():
    """`figure=both/all` 的合并摘要里，图3 那一段靠**显式 `figure` 键**认领，不靠位置猜。"""
    paths, _part = traj3d.paths_of(_traj_summary())
    assert paths["missile"] == PRODUCTS["missile"]
    merged = {"ok": True, "figure": "all", "parts": [
        {"figure": "plane", "paths": {"figures": ["a.png"]}},
        {"figure": "bg", "paths": {"figures": ["b.png"]}},
        {"figure": "traj", "preview": False, "tag": "default", "paths": dict(PRODUCTS)}]}
    paths, part = traj3d.paths_of(merged)
    assert paths["segments"] == PRODUCTS["segments"] and part["figure"] == "traj"
    for bad in ({"figure": "plane"}, {"figure": "all", "parts": [{"figure": "bg"}]}, {}):
        with pytest.raises(LookupError):
            traj3d.paths_of(bad)


# ============================================================ 2. HTTP 层


def test_webui_viewer3d_http_route_json_and_points(web3d):
    """`GET /api/viewer3d/<id>`：200 + JSON 契约；`?points=` 覆盖生效（响应确实变大）。"""
    addr, state = web3d
    job = _inject(state, result=_traj_summary())

    status, body, raw800 = _get_json(addr, f"/api/viewer3d/{job}")
    assert status == 200, body
    assert body["ok"] is True and body["job"] == job
    assert body["points"] == {"requested": 800, "missile": 800, "target": 800}
    assert body["tag"] == "default" and body["missile_name"] == "PL-12"
    assert body["colors"]["segments"] == figures.TRAJ_COLORS

    status, body, raw1200 = _get_json(addr, f"/api/viewer3d/{job}?points=1200")
    assert status == 200
    assert body["points"] == {"requested": 1200, "missile": 1200, "target": 1200}
    assert len(raw1200) > len(raw800), (len(raw800), len(raw1200))

    status, body, _raw = _get_json(addr, f"/api/viewer3d/{job}?points={traj3d.MAX_POINTS}")
    assert status == 200 and body["points"]["missile"] == RAW_ROWS, "超过原始行数就发全部"


def test_webui_viewer3d_http_route_separates_the_failure_modes(web3d):
    """404 / 409 / 400 各说各的话：id 不认识、任务没跑完、点数不合法、任务里没有图3。"""
    addr, state = web3d
    status, body, _raw = _get_json(addr, "/api/viewer3d/nope-nope")
    assert status == 404 and "没有这个任务 id" in body["errors"][0]

    queued = _inject(state, state_name="queued")
    status, body, _raw = _get_json(addr, f"/api/viewer3d/{queued}")
    assert status == 409 and "还没跑完" in body["errors"][0], (status, body)

    failed = _inject(state, state_name="error", error="求解器炸了")
    status, body, _raw = _get_json(addr, f"/api/viewer3d/{failed}")
    assert status == 409 and "求解器炸了" in body["errors"][0]

    done = _inject(state, result=_traj_summary())
    for bad in ("4001", "0", "abc", "800.0"):
        status, body, _raw = _get_json(addr, f"/api/viewer3d/{done}?points={bad}")
        assert status == 400, (bad, status, body)
        assert body["ok"] is False and "points" in body["errors"][0]

    plane = _inject(state, result={"ok": True, "figure": "plane", "paths": {"figures": ["x.png"]}})
    status, body, _raw = _get_json(addr, f"/api/viewer3d/{plane}")
    assert status == 404 and "没有图3" in body["errors"][0]

    prev = _inject(state, result=_traj_summary(preview=True,
                                               paths={"figures": ["fig_traj_preview_default.png"]}))
    status, body, _raw = _get_json(addr, f"/api/viewer3d/{prev}")
    assert status == 404 and "预览" in body["errors"][0]

    merged = _inject(state, result={"ok": True, "figure": "both", "parts": [
        {"figure": "plane", "paths": {"figures": ["a.png"]}},
        {"figure": "traj", "preview": False, "tag": "default", "paths": dict(PRODUCTS)}]})
    status, body, _raw = _get_json(addr, f"/api/viewer3d/{merged}")
    assert status == 200 and body["points"]["missile"] == 800, "合并摘要要能认出图3 那一段"


def test_webui_viewer3d_http_route_page_and_static_assets(web3d):
    """`/viewer3d` 是**独立路由**发的整页；CSS/JS 进白名单，HTML 不进（仍 fail-closed）。"""
    addr, state = web3d
    status, raw, ctype = _get(addr, "/viewer3d?job=whatever&points=800&bg=transparent")
    assert status == 200 and "text/html" in ctype
    page = raw.decode("utf-8")
    assert page == webui.read_page_file("viewer3d.html"), "整页就该是磁盘上那份，不做二次渲染"
    assert "/static/viewer3d.css" in page and "/static/viewer3d.js" in page
    assert page.count("<script") == 1, "查看器页面只有 viewer3d.js 一个脚本"

    for name, needle, ctype_needle in (("viewer3d.css", "#f7f8f9", "text/css"),
                                       ("viewer3d.js", "WebGL2", "javascript")):
        status, raw, got = _get(addr, f"/static/{name}")
        assert status == 200, (name, status)
        assert ctype_needle in got, (name, got)
        assert needle in raw.decode("utf-8"), name
        assert raw.decode("utf-8") == webui.read_page_file(name), name

    for path in ("/static/viewer3d.html", "/static/../webui.py", "/static/viewer3d.js.map"):
        status, raw, _c = _get(addr, path)
        assert status == 404, (path, status, raw[:120])
    assert "viewer3d.html" not in webui.WEB_STATIC_ASSETS
    assert webui.TOKEN_RE.findall(page) == []


def test_webui_viewer3d_no_third_party_and_light_theme():
    """零第三方资源（离线免安装）+ 亮色 chrome 没有深色残留 + 文案没有 markdown 星号。"""
    files = {
        "viewer3d.html": webui.read_page_file("viewer3d.html"),
        "viewer3d.css": webui.read_page_file("viewer3d.css"),
        "viewer3d.js": webui.read_page_file("viewer3d.js"),
        "app.js": webui.read_page_file("app.js"),
    }
    for name, text in files.items():
        lowered = text.lower()
        assert "http://" not in lowered and "https://" not in lowered, name
        assert "<script src=\"http" not in lowered and "@import" not in lowered, name
        assert "cdn" not in lowered and "unpkg" not in lowered, name

    css = files["viewer3d.css"]
    for keep in ("#f7f8f9", "#1f2933", "#d8dce1"):
        assert keep in css, keep
    for dark in ("#0f1419", "#000000", "#000;", "#111", "#1b1f23", "#222"):
        assert dark not in css, f"亮色主题里残留了深色 {dark}"
    js = files["viewer3d.js"]
    assert '"#f7f8f9"' in js, "JS 的 chrome 底色也要是亮色那一支"
    for dark in ("#0f1419", "#000000", "#1b1f23"):
        assert dark not in js, dark

    # 页面侧星号判据（`-k printed_text` 看不到手写的页面文案）：HTML/CSS 里一个都不许有，
    # JS 里只允许出现在注释里（注释不会渲染给用户）。
    for name, text in files.items():
        for i, line in enumerate(text.splitlines(), start=1):
            if "**" not in line:
                continue
            if name.endswith(".js"):
                assert line.lstrip().startswith(("//", "*", "/*")), f"{name}:{i} 的星号不在注释里"
            else:
                assert False, f"{name}:{i} 出现 markdown 星号：{line.strip()!r}"


# ============================================================ 3. 前端契约


def test_webui_viewer3d_drag_sign_has_exactly_one_site():
    """拖动方向的符号**只允许出现在一处**（`applyDrag` 里那一行）。

    这条是"跟手"能被复现的前提：两处符号就会互相打补丁，改一边坏一边。
    全文件 `cam.az +=` 恰好 2 处（另一处是自动旋转的 `tick`），`cam.az -=` 一处都没有。
    """
    js = webui.read_page_file("viewer3d.js")
    # 注释里的那句"恰好 2 处"不算代码（否则这条判据会把自己的说明文字也数进去）
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith(("//", "*", "/*")))
    assert code.count("cam.az += ") == 2, code.count("cam.az += ")
    assert "cam.az -=" not in code
    assert "cam.az += dx * AZ_PER_PX;" in code, "applyDrag 里那一行是判据本体"
    assert "cam.az += dt * 0.35;" in code, "另一处是自动旋转"
    assert "AZ_PER_PX = 0.008" in code and "EL_PER_PX = 0.008" in code
    assert "if (dragging === 1) applyDrag(cam, dx, dy); else applyPan(cam, dx, dy);" in code
    # 拖动方向只能由 applyDrag 决定：pointermove 里不许再出现裸的乘号修正
    move = code.split("pointermove", 1)[1].split("pointerup", 1)[0]
    assert "AZ_PER_PX" not in move and "applyDrag(cam, dx, dy)" in move


def test_webui_viewer3d_drag_follows_the_pointer(tmp_path):
    """真跑一遍 JS：拖 Δx = +200 px ⇒ 视轴近侧见证点同向 +92 px；镜像写法精确取负。

    视距/半径都按产品代码里的 `fit()` 口径算（`buildGeometry` 的实际包围盒 + 1100×700 画布），
    所以这个数可以复现。⚠ 见证点必须落在"物体正对观察者的那片表面"上：环绕相机绕 center 转，
    离轴远的世界点（发射点/结束点/最高点）位移方向会**反过来** —— 它们在自检里只是参考，
    不作判据（`?dragtest=200` 在真浏览器里会把同一张表打进页面）。

    没有 node 就**跳过数值部分**（仓库的 CI 机器没 node）——契约仍由上面那条文本判据兜住。
    """
    node = shutil.which("node")
    if not node:
        print("[viewer3d] 本机没有 node，跳过 JS 数值自检（文本判据仍在上面那条用例里）")
        return

    demo = tmp_path / "demo.json"
    demo.write_text(json.dumps(traj3d.build(dict(PRODUCTS), points=800), ensure_ascii=False),
                    encoding="utf-8")
    js = ROOT / "src" / "missile_sim" / "webui_static" / "viewer3d.js"
    script = tmp_path / "check.js"
    script.write_text(f"""
const T = require({json.dumps(str(js))});
const d = require({json.dumps(str(demo))});
const g = T.buildGeometry(d), b = g.bounds;
const radius = 0.5 * Math.hypot(b.mxx - b.mnx, Math.max(b.mxy - b.mny, 1), b.mxz - b.mnz);
const center = [(b.mnx + b.mxx) / 2, (b.mny + b.mxy) / 2, (b.mnz + b.mxz) / 2];
const W = 1100, H = 700, aspect = W / H, need = radius / Math.tan(0.9 / 2);
const cam = {{az: -1.05, el: 0.36, dist: Math.max(need, need / Math.max(aspect, 0.2)) * 0.72,
             pan: [0, 0, 0]}};
const rows = T.dragFollowCheck(d, cam, center, radius, W, H, 20, 200);
process.stdout.write(JSON.stringify({{rows: rows, text: T.formatDragCheck(rows, 20, 200)}}) + "\\n");
""", encoding="utf-8")
    proc = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    rows = {r["name"]: r for r in out["rows"]}
    primary = [r for r in out["rows"] if r["primary"]]
    assert primary, out["text"]

    for r in primary:
        assert r["follow_x"] is True, (r["name"], r, out["text"])
        assert r["follow_y"] is True, (r["name"], r, out["text"])
        assert r["small_x_plus"] > 0 and r["small_x_minus"] < 0, (r["name"], r)

    axis = rows["物体近侧表面(视轴)"]
    assert axis["large_x_plus"] > 0
    # 镜像写法 ⇒ 取负（同一个见证点、同一段代码，只有方位角那一行的符号相反）。
    # 见证点几乎正好在视轴上（离视野中心 2e-5 px），所以两个方向的深度差只有 4e-5 px。
    assert abs(axis["large_x_plus"] + axis["large_x_minus"]) < 1e-3, axis
    assert 60.0 <= axis["large_x_plus"] <= 140.0, axis["large_x_plus"]
    assert "+92." in out["text"] or "+93." in out["text"], out["text"]
    assert out["text"].rstrip().endswith("ok=1"), out["text"]
    print("[viewer3d] 跟手自检：dx@+200 = %.2f px，dx@-200 = %.2f px（镜像精确取负）"
          % (axis["large_x_plus"], axis["large_x_minus"]))


def test_webui_viewer3d_app_js_embeds_the_viewer_and_offers_a_new_tab():
    """首页结果面板：内嵌 iframe（透明底）+「在新标签页打开」（独立页）。"""
    js = webui.read_page_file("app.js")
    assert "function showViewer3d(" in js and "function viewer3dUrl(" in js
    assert "document.createElement(\"iframe\")" in js
    assert "在新标签页打开" in js
    assert 'a.target = "_blank";' in js and 'a.rel = "noopener";' in js
    assert "&bg=transparent" in js, "内嵌用透明底"
    assert "fr.src = viewer3dUrl(job, true);" in js
    assert "a.href = viewer3dUrl(job, false);" in js
    assert "var CURJOB = null;" in js and "CURJOB = id;" in js, "结果摘要里没有 id，要靠轮询记下来"
    assert 'if (trajPart(r) && CURJOB) showViewer3d(CURJOB' in js, "合并摘要里也要嵌图3 那一段"
    assert "function trajPart(r)" in js
    assert "preview" in js and "没有可交互的 3D" in js, "预览要直说没有 3D，而不是放个空框"

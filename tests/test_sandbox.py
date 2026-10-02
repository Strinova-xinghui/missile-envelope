# -*- coding: utf-8 -*-
"""空战沙盒（图3 回放页）的验收。

分两层，都能单独跑：

1. **数据层**（毫秒级、不碰求解器）：`traj3d.build_replay()` 的事件表**与产物逐位一致**、
   倍速枚举、逐点读数与抽稀后的轨迹**逐点对齐**、姿态取自轨迹（不是常量）、
   悬停字段契约（键名/单位/顺序/`pending` 不许有值）；
2. **前端契约**（读文本 + 有 node 就真跑一遍 `sandbox.js` 的纯函数）：
   字段标签**只能来自响应**（前端不许写死）、事件标点用服务端拼好的文本、
   回放条/图例/实体的契约名、页面里 `**` 计数为 0。

HTTP 那一层（`GET /sandbox`、`GET /api/sandbox/<key>`、白名单 fail-closed）在路由落地后
补在同一个文件里，用例名带上 `webui` 前缀，于是 `-k sandbox` 与 `-k webui` 都能选到。
"""

from __future__ import annotations

import http.client
import json
import math
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

PRODUCTS = {
    "missile": str(ROOT / "results" / "traj_default_missile.csv"),
    "target": str(ROOT / "results" / "traj_default_target.csv"),
    "segments": str(ROOT / "results" / "traj_default_segments.csv"),
    "manifest": str(ROOT / "results" / "traj_default.json"),
}
#: 参考站悬停框那 9 行（`UI-LAYOUT-REF-3D.md` §3）—— 顺序就是契约
REF_HOVER_ORDER = ["t_s", "horizontal_m", "alt_m", "speed_ms", "mach", "accel_ms2",
                   "range_m", "n_g", "aoa_deg", "flown_m"]
#: 内核列还没进产物 ⇒ 只许报"待接入"（`speed_ms` 只在**目标侧** pending）
PENDING_KEYS = ["speed_ms", "mach", "accel_ms2", "n_g", "aoa_deg", "flown_m",
                "sf_g", "req_g", "aoa_eff_deg"]


def _manifest() -> dict:
    return json.loads(Path(PRODUCTS["manifest"]).read_text(encoding="utf-8"))


def _replay(**kw):
    kw.setdefault("points", 800)
    return traj3d.build_replay(dict(PRODUCTS), **kw)


def _csv(path):
    return traj3d.read_csv_rows(path)


# ============================================================ 1. 数据层


def test_sandbox_replay_does_not_solve():
    """回放数据层**只读产物**：把 `solver.run` 换成"一被调用就炸"，数据照样出得来。"""
    calls = []
    original = solver.run

    def boom(*args, **kwargs):                                   # pragma: no cover - 不该被调用
        calls.append((args, kwargs))
        raise AssertionError("沙盒数据层不该调用 solver.run")

    solver.run = boom
    try:
        d = _replay(job="demo")
        assert d["points"]["missile"] == 800 and d["events"]
    finally:
        solver.run = original
    assert calls == []
    assert solver.run is original
    # 模块**结构上**不可能解算：import 表里没有求解器那一族（比"没调用"更强的判据）
    import ast
    src = (ROOT / "src" / "missile_sim" / "traj3d.py").read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
            if node.level:                     # `from . import figures` ⇒ 名字才是模块名
                mods.update(a.name for a in node.names)
    assert not [m for m in mods if any(w in m for w in ("solver", "workflow", "engine", "webui"))], mods
    assert mods <= {"", "__future__", "bisect", "csv", "json", "math", "re", "pathlib", "figures"}, mods
    assert "figures" in mods


def test_sandbox_events_match_the_products_bit_for_bit():
    """事件表 8 条：时刻与产物**逐位一致**（marks / segments / `thrust_N` 列），文本已拼好。"""
    man = _manifest()
    run = man["run"]
    anchor = run["anchor"]
    segs = _csv(PRODUCTS["segments"])
    rows = _csv(PRODUCTS["missile"])
    powered = [float(r["t_s"]) for r in rows if float(r["thrust_N"]) > 0.0]
    t_turn1 = [s for s in segs if s["kind"] == "turn" and s["heading1_deg"] == "110"][0]
    t_turn2 = [s for s in segs if s["kind"] == "turn" and s["heading1_deg"] == "90"][0]

    d = _replay()
    got = {e["name"]: e for e in d["events"]}
    assert list(got) == ["launch", "burnout", "crank_start", "crank_done", "seeker_on",
                        "beam_start", "beam_done", "end"], list(got)

    def same(name, expect):
        assert got[name]["t_s"] == expect, (name, got[name]["t_s"], expect)

    same("launch", round(float(rows[0]["t_s"]), 3))
    same("burnout", round(max(powered), 3))                    # 燃尽 = 推力>0 的最后一行
    same("crank_start", round(float(t_turn1["t0_s"]), 3))
    same("crank_done", round(float(t_turn1["t1_s"]), 3))
    same("seeker_on", round(float(anchor["t_beam_s"]), 3))
    same("beam_start", round(float(anchor["t_react_s"]), 3))
    same("beam_done", round(float(t_turn2["t1_s"]), 3))
    same("end", round(float(run["t_hit_s"]), 3))

    # 时间单调 + 事件一定要落在回放区间里
    ts = [e["t_s"] for e in d["events"]]
    assert ts == sorted(ts) and ts[0] == 0.0 and ts[-1] == d["replay"]["t1"]
    assert d["replay"]["t1"] == d["t_end_s"]
    # 文本在服务端拼好（前端不拼字符串）：命中那条要带近炸距离
    assert got["end"]["text"].startswith("命中: 69.17 秒")
    assert "近炸 10.0 m" in got["end"]["text"]
    assert "推力归零" in got["burnout"]["text"]
    assert "R = 16 km" in got["seeker_on"]["text"]
    assert "延迟 1.0 s" in got["beam_start"]["text"]
    # 事件点位：发射在发射点、命中在弹的末点（近炸 10 m 内）
    assert got["launch"]["pos"] == [0.0, 10000.0, 0.0]
    mis_last = d["missile"]["p"][-1]
    assert math.dist(got["end"]["pos"], mis_last) < 5.0, (got["end"]["pos"], mis_last)
    assert got["burnout"]["entity"] == "missile" and got["beam_start"]["entity"] == "target"


def test_sandbox_speed_is_an_enum_and_points_reuse_the_viewer_contract():
    """倍速是**枚举**（0.25/0.5/1/2/4），点数契约与查看器同源（`parse_points`）。"""
    assert list(traj3d.REPLAY_SPEEDS) == [0.25, 0.5, 1.0, 2.0, 4.0]
    assert traj3d.REPLAY_SPEED_DEFAULT == 1.0
    assert traj3d.parse_speed(None) == 1.0 and traj3d.parse_speed("") == 1.0
    for text, want in (("0.25", 0.25), ("0.5", 0.5), ("1", 1.0), ("1.0", 1.0),
                       ("2", 2.0), ("4", 4.0)):
        assert traj3d.parse_speed(text) == want, text
    for bad in ("3", "0", "-1", "abc", "1x"):
        with pytest.raises(ValueError):
            traj3d.parse_speed(bad)
    d = _replay()
    assert d["replay"]["speeds"] == [0.25, 0.5, 1.0, 2.0, 4.0]
    assert d["replay"]["speed_default"] == 1.0
    assert abs(d["replay"]["step_s"] - 0.0208) < 5e-4, d["replay"]["step_s"]
    assert [f["key"] for f in d["follow"]] == ["free", "missile", "target"]
    assert d["follow_default"] == "free"
    # 点数仍然是查看器那套：默认 800、上限 4000、非法值报错
    assert d["points"] == {"requested": 800, "missile": 800, "target": 800}
    assert traj3d.parse_points("1200") == 1200
    with pytest.raises(ValueError):
        traj3d.parse_points("4001")


def test_sandbox_series_aligns_with_the_drawn_track():
    """逐点读数必须与**画出来的那批点**逐点对齐（同一套抽稀下标），否则悬停框会指错地方。"""
    d = _replay()
    mis, mt = d["series"]["missile"], d["missile"]
    tgt, tt = d["series"]["target"], d["target"]
    assert len(mis["t_s"]) == len(mt["t"]) == d["points"]["missile"]
    assert mis["t_s"] == mt["t"]
    assert tgt["t_s"] == tt["t"]
    for i in range(len(mt["t"])):
        x, y, z = mt["p"][i]
        assert mis["alt_m"][i] == y, i
        assert abs(mis["horizontal_m"][i] - math.hypot(x, z)) <= 0.15, i   # 相对原点（发射点）
    # 到目标的距离：**内核 range_m 列**（两张表同一条时间轴，按下标对齐）
    assert abs(mis["range_m"][0] - 50000.0) < 1.0, mis["range_m"][0]
    assert abs(mis["range_m"][-1] - 10.0) < 0.5, mis["range_m"][-1]      # 近炸距离
    # 目标的到目标距离取自**同一条内核列**（两边的抽稀下标不同，所以只对首末点比）
    assert tgt["range_m"][0] == mis["range_m"][0] == 50000.0
    assert tgt["range_m"][-1] == mis["range_m"][-1] == 10.0
    assert all(5.0 < v < 51000.0 for v in tgt["range_m"])
    # 只放"内核产物列 + 位置折出来的几何量 + 绘图姿态"，别的（accel/flown/目标速度）一律不放
    for who, series in (("missile", mis), ("target", tgt)):
        assert set(series) == {"t_s", "alt_m", "horizontal_m", "range_m",
                               "yaw_deg", "pitch_deg"} | ({"speed_ms"} if who == "missile" else set()), who
    # 差额实现仍然在模块里（P6 对拍照），但**不进响应**
    arc = traj3d._cumulative(mt["t"], [p[0] for p in mt["p"]], [p[1] for p in mt["p"]],
                             [p[2] for p in mt["p"]])
    assert arc[0] == 0.0 and all(arc[i] < arc[i + 1] for i in range(len(arc) - 1))
    assert arc[-1] > 45000.0, arc[-1]


def test_sandbox_products_share_one_time_axis():
    """`range_m` 按下标对齐的**前提**：两张产物表是同一条时间轴（不同就得改插值）。"""
    mt = [float(r["t_s"]) for r in _csv(PRODUCTS["missile"])]
    tt = [float(r["t_s"]) for r in _csv(PRODUCTS["target"])]
    assert len(mt) == len(tt) == 3322
    assert mt == tt, "弹/目标产物表的时间轴不一致 ⇒ `range_m` 不能按下标对齐"


def test_sandbox_attitude_comes_from_the_trajectory():
    """朝向取自轨迹（不是常量）：导弹用速度方向、目标与航向指令（`segments`）对得上。"""
    man = _manifest()
    segs = _csv(PRODUCTS["segments"])
    d = _replay()
    mis, tgt = d["series"]["missile"], d["series"]["target"]

    def spread(seq):
        return max(seq) - min(seq)

    assert spread(mis["yaw_deg"]) > 30.0 and spread(mis["pitch_deg"]) > 15.0, \
        (spread(mis["yaw_deg"]), spread(mis["pitch_deg"]))
    assert spread(tgt["yaw_deg"]) > 60.0, spread(tgt["yaw_deg"])
    assert spread(tgt["pitch_deg"]) < 5.0, "目标全程平飞，俯仰不该大动"

    # 目标朝向 vs 航向指令：直飞段 180°、crank 保持段 110°、39 保持段 90°（容差 2°）
    for s in segs:
        if s["kind"] != "hold":
            continue
        want = float(s["heading1_deg"])
        t0, t1 = float(s["t0_s"]), float(s["t1_s"])
        picked = [tgt["yaw_deg"][i] for i, t in enumerate(tgt["t_s"])
                  if t0 + 2.0 <= t <= t1 - 2.0]
        assert picked, s
        assert max(abs(v - want) for v in picked) < 2.0, (s["label"], want, picked[:4])
    # 目标速度（位置差分，P6 对拍照）与想定输入一致：想定里目标恒速 300 m/s
    want = float(man["scene"]["target_speed_ms"])
    tp = d["target"]["p"]
    derived = traj3d._speed_of(tgt["t_s"], [q[0] for q in tp], [q[1] for q in tp],
                               [q[2] for q in tp], half=traj3d.TARGET_HALF)
    assert abs(sum(derived) / len(derived) - want) < 7.5, (want, sum(derived) / len(derived))
    # 轴向加速度差分（P6 对拍照）：导弹点火段大正、末端减速为负；量级合理
    macc = traj3d._axial_accel(mis["t_s"], mis["speed_ms"])
    assert max(macc) > 150.0 and min(macc) < -5.0, (max(macc), min(macc))
    assert "speed_ms" not in tgt and "accel_ms2" not in mis and "flown_m" not in mis
    # 姿态是**画实体**要用的，不进悬停框
    assert set(traj3d.DRAW_ONLY_KEYS) <= set(mis) and set(traj3d.DRAW_ONLY_KEYS) <= set(tgt)
    assert not (set(traj3d.DRAW_ONLY_KEYS) & {f["key"] for f in d["hover"]["fields"]})


def test_sandbox_hover_contract_locks_keys_units_and_pending():
    """悬停框字段契约：顺序照参考站；单位/精度/来源逐条钉死；`pending` 的键**不许**有值。"""
    d = _replay()
    fields = d["hover"]["fields"]
    by_key = {f["key"]: f for f in fields}
    assert d["hover"]["main_order"] == REF_HOVER_ORDER, d["hover"]["main_order"]
    want_units = {"t_s": ("时间", "秒", 2), "horizontal_m": ("水平距离", "米", 0),
                  "alt_m": ("高度", "米", 0), "speed_ms": ("速度", "米/秒", 1),
                  "mach": ("马赫数", "M", 2), "accel_ms2": ("加速度", "米/秒²", 2),
                  "range_m": ("到目标的距离", "米", 0), "n_g": ("G载荷", "G", 2),
                  "aoa_deg": ("攻角", "°", 1), "flown_m": ("已行驶距离", "米", 0)}
    for key, (label, unit, dec) in want_units.items():
        f = by_key[key]
        assert (f["label"], f["unit"], f["decimals"]) == (label, unit, dec), key
        assert set(f["source"]) == {"missile", "target"}, key
        assert f["source"]["missile"] in (traj3d.SRC_KERNEL, traj3d.SRC_DERIVED,
                                         traj3d.SRC_PENDING), key
    assert by_key["mach"]["merge_with"] == "speed_ms", "马赫数要与速度同行显示"
    assert [f["key"] for f in fields if f["group"] == "extra"] == ["sf_g", "req_g", "aoa_eff_deg"]

    assert d["hover"]["pending_keys"] == PENDING_KEYS, d["hover"]["pending_keys"]
    # 每个 pending 字段都要写清内核侧的**真源头**（P6 照它接，不许换口径）
    assert set(d["hover"]["pending_sources"]) == set(PENDING_KEYS)
    assert "distance_flown_m" in d["hover"]["pending_sources"]["flown_m"]
    assert "accel_x/y/z_m_s2" in d["hover"]["pending_sources"]["accel_ms2"]
    assert "trajectory_normal_g" in d["hover"]["pending_sources"]["n_g"]
    series = d["series"]
    # pending 的键：**按实体**判 —— 该实体侧标了 pending 就不许有那一列（不许用派生值顶）
    for key in PENDING_KEYS:
        f = by_key[key]
        for who in ("missile", "target"):
            if f["source"][who] == traj3d.SRC_PENDING:
                assert key not in series[who], f"{who} 不该有 {key}（内核列还没进产物）"
            else:
                assert isinstance(series[who].get(key), list), (who, key)
    # 非 pending 的 main 字段：该实体侧要真的有一列，且长度等于点数
    for f in fields:
        if f["group"] != "main":
            continue
        for who in ("missile", "target"):
            if f["source"][who] == traj3d.SRC_PENDING:
                assert f["key"] not in series[who], (who, f["key"])
                continue
            col = series[who].get(f["key"])
            assert isinstance(col, list) and len(col) == d["points"][who], (who, f["key"])
    # 目标的速度是 pending（内核 target_speed_m_s 还没进产物），但弹的是内核列
    assert by_key["speed_ms"]["source"] == {"missile": traj3d.SRC_KERNEL,
                                           "target": traj3d.SRC_PENDING}
    assert by_key["range_m"]["source"] == {"missile": traj3d.SRC_KERNEL,
                                          "target": traj3d.SRC_KERNEL}
    assert by_key["horizontal_m"]["source"] == {"missile": traj3d.SRC_DERIVED,
                                               "target": traj3d.SRC_DERIVED}


def test_sandbox_axes_use_k_suffix_and_direction_labels():
    """三轴刻度：`k` 后缀 + "方向 + 单位"轴名（轴名按我们的真实坐标，不照抄参考站那句自相矛盾的）。"""
    d = _replay()
    ax = d["axes"]
    assert ax["x"]["label"] == "前向距离 - X（米）"
    assert ax["y"]["label"] == "高度 - Y（米）"
    assert ax["z"]["label"] == "侧向距离 - Z（米）"
    for name in ("x", "y", "z"):
        a = ax[name]
        assert a["ticks"] == sorted(a["ticks"]) and 0.0 in a["ticks"], name
        assert a["texts"][0] == "0"
        assert len(a["ticks"]) == len(a["texts"]) and 3 <= len(a["ticks"]) <= 8, name
        for v, text in zip(a["ticks"], a["texts"]):
            if abs(v) >= 1000:
                assert text.endswith("k") and text == f"{v / 1000:.0f}k", (name, v, text)
    assert ax["x"]["max"] >= 50000.0 and ax["y"]["max"] >= 12800.0
    assert ax["z"]["max"] >= 17000.0


def test_sandbox_shares_the_viewer_payload_instead_of_forking_it():
    """沙盒与查看器**同一套**轨迹/分段/节点/配色（不各写一份，避免静默分叉）。"""
    base = traj3d.build(dict(PRODUCTS), points=800, job="demo")
    rep = _replay(job="demo")
    for key in ("missile", "target", "segments", "marks", "colors", "points", "rows",
                "t_beam_s", "t_hit_s", "hit", "miss_m", "missile_name", "segments"):
        assert rep[key] == base[key], key
    assert rep["colors"]["segments"] == figures.TRAJ_COLORS
    # 图例：线型区分双方（导弹实线 / 目标虚线），颜色仍来自 figures
    ent = rep["entities"]
    assert ent["missile"]["style"] == "solid" and ent["target"]["style"] == "dashed"
    assert ent["missile"]["colors"] == [rep["colors"]["missile_before"], rep["colors"]["missile_after"]]
    assert ent["missile"]["colors"][1] == figures.TRAJ_MISSILE2_COLOR
    assert ent["target"]["colors"] == [s["color"] for s in rep["segments"]]
    assert ent["target"]["name"] == "目标"


# ============================================================ 3. HTTP 层（`GET /sandbox`）


@pytest.fixture(scope="module")
def websb():
    """自己起一个 WebUI（`state` 归本文件，方便塞假任务）—— 与 `test_viewer3d.py` 同款做法。

    不用 `webui.serve()`：那会顺带起预热线程，这里不需要。`config` 指向仓库自己的
    `figures/` 与 `results/`，于是 `/api/sandbox/default` 能读到那套 `traj_default_*` 产物。
    """
    cfg = {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1, "formats": ["png"],
           "cache": False, "tag": "default", "poll_ms": 100,
           "figure_dir": str(ROOT / "figures"), "result_dir": str(ROOT / "results")}
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


def _inject(state, *, state_name="done", result=None, error=""):
    """往任务表里塞一个假任务：产物路径指向仓库里那三份 CSV。"""
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


def test_webui_sandbox_route_serves_the_page_and_the_json(websb):
    """`GET /sandbox` 是独立路由发的整页；`GET /api/sandbox/<key>` 给回放数据；静态白名单仍 fail-closed。"""
    addr, _state = websb
    status, raw, ctype = _get(addr, "/sandbox?job=x")
    assert status == 200 and "text/html" in ctype
    page = raw.decode("utf-8")
    assert page == webui.read_page_file("sandbox.html"), "整页就该是磁盘上那份，不做二次渲染"
    assert "/static/sandbox.css" in page and "/static/sandbox.js" in page
    assert 'src="/static/viewer3d.js"' in page, "沙盒复用查看器导出的相机/投影"
    assert webui.TOKEN_RE.findall(page) == [], "整页里没有服务端占位符"

    status, raw, ctype = _get(addr, "/api/sandbox/default")
    assert status == 200 and "application/json" in ctype
    d = json.loads(raw.decode("utf-8"))
    assert d["ok"] is True and d["tag"] == "default" and d["job"] is None
    assert d["points"] == {"requested": 800, "missile": 800, "target": 800}
    assert [e["name"] for e in d["events"]][:2] == ["launch", "burnout"]
    assert d["hover"]["main_order"][0] == "t_s" and d["axes"]["x"]["texts"][-1].endswith("k")
    assert set(d["series"]) == {"missile", "target"}

    status, raw1200, _c = _get(addr, "/api/sandbox/default?points=1200")
    assert status == 200 and len(raw1200) > len(raw)
    assert json.loads(raw1200)["points"]["missile"] == 1200
    status, body, _c = _get(addr, "/api/sandbox/default?points=4000")
    assert status == 200 and json.loads(body)["points"]["missile"] == 3322, "到顶就是全部原始行"

    for name, needle, ctype_needle in (("sandbox.css", "#f7f8f9", "text/css"),
                                       ("sandbox.js", "WebGL2", "javascript")):
        status, raw, got = _get(addr, f"/static/{name}")
        assert status == 200 and ctype_needle in got, (name, status, got)
        assert needle in raw.decode("utf-8")
        assert raw.decode("utf-8") == webui.read_page_file(name), name
    assert "sandbox.css" in webui.WEB_STATIC_ASSETS and "sandbox.js" in webui.WEB_STATIC_ASSETS
    assert "sandbox.html" not in webui.WEB_STATIC_ASSETS, "整页不进白名单（同 viewer3d.html）"
    for path in ("/static/sandbox.html", "/static/../webui.py", "/static/sandbox.js.map"):
        status, raw, _c = _get(addr, path)
        assert status == 404, (path, status, raw[:120])


def test_webui_sandbox_route_separates_the_failure_modes(websb):
    """400 / 404 / 409 各说各的话：点数、未知 key、任务没跑完、任务里没有图3、tag 不存在。"""
    addr, state = websb
    for bad in ("4001", "0", "abc", "800.0"):
        status, body, _c = _get(addr, f"/api/sandbox/default?points={bad}")
        assert status == 400 and json.loads(body)["ok"] is False, (bad, status)
        assert "points" in json.loads(body)["errors"][0]

    status, body, _c = _get(addr, "/api/sandbox/nope-nope")
    assert status == 404 and "没有这个任务 id" in json.loads(body)["errors"][0]

    status, body, _c = _get(addr, "/api/sandbox/default?tag=no-such-tag")
    assert status == 404 and "找不到图3 产物" in json.loads(body)["errors"][0]

    queued = _inject(state, state_name="queued")
    status, body, _c = _get(addr, f"/api/sandbox/{queued}")
    assert status == 409 and "还没跑完" in json.loads(body)["errors"][0]

    plane = _inject(state, result={"ok": True, "figure": "plane", "paths": {"figures": ["x.png"]}})
    status, body, _c = _get(addr, f"/api/sandbox/{plane}")
    assert status == 404 and "没有图3" in json.loads(body)["errors"][0]

    prev = _inject(state, result=_traj_summary(preview=True, paths={"figures": ["p.png"]}))
    status, body, _c = _get(addr, f"/api/sandbox/{prev}")
    assert status == 404 and "预览" in json.loads(body)["errors"][0]

    done = _inject(state, result=_traj_summary())
    status, body, _c = _get(addr, f"/api/sandbox/{done}?points=1200")
    assert status == 200
    d = json.loads(body)
    assert d["job"] == done and d["points"]["missile"] == 1200 and d["tag"] == "default"


def test_webui_sandbox_route_does_not_solve(websb):
    """路由层同样**不解算**：把 `solver.run` 换成"一被调用就炸"，三条请求全都能出数据。"""
    addr, _state = websb
    calls = []
    original = solver.run

    def boom(*args, **kwargs):                                   # pragma: no cover - 不该被调用
        calls.append((args, kwargs))
        raise AssertionError("沙盒接口不该调用 solver.run")

    solver.run = boom
    try:
        for path in ("/api/sandbox/default", "/api/sandbox/default?points=1200",
                     "/api/sandbox/default?tag=default"):
            status, body, _c = _get(addr, path)
            assert status == 200 and json.loads(body)["events"], (path, status)
    finally:
        solver.run = original
    assert calls == []


# ============================================================ 4. 前端契约


def test_sandbox_reports_a_miss_with_the_closest_distance(tmp_path):
    """脱靶分支：默认工况是**命中**，`hit=false` 那条路径没被走到过 —— 这里把它走一遍。

    只翻 manifest 里的"结局"（`hit/event/t_hit_s/miss_m`），轨迹数据不动 ⇒ 这条测的是
    **事件文案与颜色分支**（`脱靶: … 秒（最近 … m）` + `colors.miss`），不是物理。
    """
    man = _manifest()
    man["run"]["hit"] = False
    man["run"]["event"] = "time_limit"
    man["run"]["t_hit_s"] = None
    man["run"]["miss_m"] = 123.4
    paths = {}
    for key, src in PRODUCTS.items():
        dst = tmp_path / Path(src).name
        if key == "manifest":
            dst.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
        else:
            shutil.copy(src, dst)
        paths[key] = str(dst)

    d = traj3d.build_replay(paths, points=800)
    end = [e for e in d["events"] if e["name"] == "end"][0]
    assert end["hit"] is False and end["miss_m"] == 123.4
    assert end["label"] == "脱靶"
    assert end["text"] == "脱靶: 69.17 秒（最近 123.4 m）", end["text"]
    assert d["hit"] is False and d["miss_m"] == 123.4
    assert d["colors"]["miss"] == figures.TRAJ_MISS_COLOR
    assert [e["t_s"] for e in d["events"]] == sorted(e["t_s"] for e in d["events"])
    # 前端按 `hit` 布尔挑颜色（命中用 TRAJ_HIT_COLOR、脱靶用 TRAJ_MISS_COLOR）
    js = (ROOT / "src" / "missile_sim" / "webui_static" / "sandbox.js").read_text(encoding="utf-8")
    assert "e.hit === true ? d.colors.hit" in js and "d.colors.miss" in js


def _stripped_of_comments(name: str, text: str) -> str:
    """去掉注释后的文本 —— 星号判据只管**会渲染出去**的那部分（注释里的 `**` 无所谓）。"""
    import re as _re
    out = _re.sub(r"<!--.*?-->", "", text, flags=_re.S)
    out = _re.sub(r"/\*.*?\*/", "", out, flags=_re.S)
    if name.endswith(".js"):
        out = "\n".join(ln for ln in out.splitlines() if not ln.lstrip().startswith("//"))
    return out


def test_sandbox_page_has_no_markdown_stars_and_no_third_party():
    """页面侧两条纪律：**渲染出去**的文案里没有 markdown 星号；零第三方资源（离线免安装）。"""
    files = {}
    for name in ("sandbox.html", "sandbox.css", "sandbox.js"):
        path = ROOT / "src" / "missile_sim" / "webui_static" / name
        assert path.is_file(), f"{name} 还没写"
        files[name] = path.read_text(encoding="utf-8")
    for name, text in files.items():
        lowered = text.lower()
        assert "http://" not in lowered and "https://" not in lowered, name
        assert "cdn" not in lowered and "unpkg" not in lowered, name
        stripped = _stripped_of_comments(name, text)
        for i, line in enumerate(stripped.splitlines(), start=1):
            assert "**" not in line, f"{name}:{i} 渲染出来的文案里有 markdown 星号：{line.strip()!r}"
    # 页面里手写的提示文案也不许有星号（它们不归 `-k printed_text` 管）
    html = files["sandbox.html"]
    for line in _stripped_of_comments("sandbox.html", html).splitlines():
        assert "**" not in line


def test_sandbox_frontend_reuses_the_viewer_camera_and_labels_come_from_the_response():
    """前端**复用** `TRAJ3D` 的相机/投影，且悬停框的标签**只能来自响应**（不许写死字段名）。

    ⚠ 沙盒页自己的 DOM id 一律 `sb` 前缀：`viewer3d.js` 的 `boot()` 会在 `window` 里自己跑一遍
    并在缺 `#cv` 时静默退出 —— 只要沙盒页**不出现它的那批 id**，两页共用一个脚本就不会互相打扰。
    这一条（下面那段 `viewer3d` id 的断言）是"复用 viewer3d.js"能成立的前提。
    """
    static = ROOT / "src" / "missile_sim" / "webui_static"
    js = (static / "sandbox.js").read_text(encoding="utf-8")
    html = (static / "sandbox.html").read_text(encoding="utf-8")
    for need in ("TRAJ3D", "projectToScreen", "applyDrag", "applyPan", "idxLeft", "idxRight"):
        assert need in js, need
    assert 'src="/static/viewer3d.js"' in html, "必须复用查看器导出的相机/投影"
    for bad in ('id="cv"', 'id="err"', 'id="btnReset"', 'id="btnSpin"', 'id="btnAxes"',
                'id="btnOpen"', 'id="title"', 'id="dragtest"'):
        assert bad not in html, f"sandbox.html 不能出现 viewer3d.js boot() 会去抢的 {bad}"
    # 字段标签/单位来自响应里的 hover.fields：前端不许出现这些中文字面量
    for label in ("水平距离", "到目标的距离", "已行驶距离", "马赫数", "攻角", "G载荷"):
        assert label not in js, f"sandbox.js 里写死了字段标签 {label!r}（应从 hover.fields 渲染）"
    assert "hover.fields" in js or "hover['fields']" in js
    # 回放条/图例/实体/悬停的契约名（前端行为由真浏览器取证，这里只钉名字）
    for need in ("sbReplay", "sbPause", "sbStep", "sbProgress", "sbLegend", "sbHover",
                 "renderHover", "wire", "entityAxes", "showHover"):
        assert need in js, need
    for need in ('id="sbReplay"', 'id="sbPause"', 'id="sbStep"', 'id="sbProgress"',
                 'id="sbHover"', 'id="sbLegend"', 'id="sbScene"', 'id="sbSide"'):
        assert need in html, need


def test_sandbox_js_pure_helpers_match_the_server_contract(tmp_path):
    """真有 node 就把 `sandbox.js` 的纯函数拉出来跑一遍（悬停取值 + 事件文本 + 单位格式）。

    没 node 的机器上**跳过数值部分**（文本判据仍在上面那条），打印一行说明。
    """
    node = shutil.which("node")
    if not node:
        print("[sandbox] 本机没有 node，跳过 sandbox.js 纯函数数值自检")
        return
    demo = tmp_path / "replay.json"
    demo.write_text(json.dumps(_replay(), ensure_ascii=False), encoding="utf-8")
    js = ROOT / "src" / "missile_sim" / "webui_static" / "sandbox.js"
    script = tmp_path / "check.js"
    script.write_text(f"""
const S = require({json.dumps(str(js))});
const d = require({json.dumps(str(demo))});
const out = {{}};
out.fields = S.fieldPlan(d).map(f => f.key + '|' + f.label + '|' + f.unit);
out.hoverMid = S.hoverAt(d, 'missile', 400);
out.hoverEnd = S.hoverAt(d, 'target', d.points.target - 1);
out.fmt = [S.fmtValue(3.14159, 2), S.fmtValue(50000, 0), S.fmtValue(null, 1)];
out.hit = S.eventLine(d.events.filter(e => e.name === 'end')[0]);
out.trackTime = S.trackTime(d);
process.stdout.write(JSON.stringify(out) + "\\n");
""", encoding="utf-8")
    proc = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["fmt"] == ["3.14", "50000", "待接入"], out["fmt"]
    assert "命中" in out["hit"] and "近炸" in out["hit"], out["hit"]
    assert abs(out["trackTime"] - 69.172) < 0.01, out["trackTime"]
    keys = [row.split("|")[0] for row in out["fields"]]
    assert keys == REF_HOVER_ORDER, keys
    # 悬停取值：导弹 400 号点 = 服务端那一列的值；末端 = 近炸距离
    mid = out["hoverMid"]
    assert mid["rows"][0]["key"] == "t_s" and 20.0 < mid["rows"][0]["value"] < 50.0, mid
    end = out["hoverEnd"]
    endrows = {r["key"]: r for r in end["rows"]}
    assert endrows["range_m"]["value"] is not None
    assert 5.0 < endrows["range_m"]["value"] < 20.0, endrows["range_m"]
    assert endrows["mach"]["value"] is None and endrows["mach"]["pending"] is True
    print("[sandbox] 悬停取值自检：导弹#400 t=%.2f s，目标末点 range=%.1f m"
          % (out["hoverMid"]["rows"][0]["value"], endrows["range_m"]["value"]))

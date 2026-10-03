# -*- coding: utf-8 -*-
"""空战沙盒（图4 回放页）的验收。

分两层，都能单独跑：

1. **数据层**（毫秒级、不碰求解器）：`traj3d.build_replay()` 的事件表**与产物逐位一致**、
   倍速枚举、逐点读数与抽稀后的轨迹**逐点对齐**、姿态取自轨迹（不是常量）、
   悬停字段契约（键名/单位/顺序/`pending` 不许有值）；
2. **前端契约**（读文本 + 有 node 就真跑一遍 `sandbox.js` 的纯函数）：
   字段标签**只能来自响应**（前端不许写死）、事件标点用服务端拼好的文本、
   回放条/图例/实体的契约名、页面里 `**` 计数为 0。

HTTP 那一层（`GET /fig4`、`GET /api/sandbox/<key>`、白名单 fail-closed）在路由落地后
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
#: 内核列还没进产物 ⇒ 只许报"待接入"（`speed_ms` 只在**目标侧** pending）；列表是排序过的
PENDING_KEYS = ["accel_ms2", "aoa_deg", "aoa_eff_deg", "flown_m", "mach", "n_g", "req_g",
                "sf_g", "speed_ms"]


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
    # 文本在服务端拼好（前端不拼字符串）。⚠ A5（task-23）之后三个"距离"语义不同：
    # 命中时 `min_separation_m` **就是引信半径**（默认 10 m）⇒ 文案写"引信半径"，不写"脱靶量"；
    # 真最近接近是 `cpa_m`（命中工况关引信复跑量出来的，默认工况 ~4 mm）。
    assert got["end"]["text"].startswith("命中: 69.17 秒")
    assert "引信半径 10.0 m" in got["end"]["text"] and "脱靶" not in got["end"]["text"]
    assert "最近接近" in got["end"]["text"], got["end"]["text"]
    assert got["end"]["min_separation_m"] == run["min_separation_m"] == 10.0
    assert got["end"]["fuse_radius_m"] == run["fuse_radius_m"] == 10.0
    assert got["end"]["cpa_m"] == pytest.approx(run["cpa_m"], rel=1e-4), got["end"]["cpa_m"]
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
    # 末点是"终止事件前的最近距离"：命中时它 == 引信半径（A5 之后不再叫脱靶量）
    man = _manifest()
    tail = man["run"]["min_separation_m"]
    assert abs(mis["range_m"][-1] - tail) < 0.5, (mis["range_m"][-1], tail)
    # 目标的到目标距离取自**同一条内核列**（两边的抽稀下标不同，所以只对首末点比）
    assert tgt["range_m"][0] == mis["range_m"][0] == 50000.0
    assert tgt["range_m"][-1] == mis["range_m"][-1]
    assert all(1.0 < v < 51000.0 for v in tgt["range_m"])
    # 逐点读数只放"契约说得出数据"的列 —— 期望值**由产物表头推**，于是
    # "产物还没扩列（降级）"与"产物已扩列（kernel）"两种现实都能过（§ 合成老产物那条用例）
    for who, series, table in (("missile", mis, PRODUCTS["missile"]),
                               ("target", tgt, PRODUCTS["target"])):
        cols = set(_csv(table)[0])
        expect = {"t_s", "alt_m", "horizontal_m", "range_m", "yaw_deg", "pitch_deg"}
        for f in d["hover"]["fields"]:
            src = f["source"][who]
            if src == "n/a":
                assert f["key"] not in series, (who, f["key"])
            elif src == "pending":
                assert f["key"] not in series, (who, f["key"])
            else:
                assert f["key"] in series, (who, f["key"], src)
                expect.add(f["key"])
        missing = expect - set(series)
        assert not missing, (who, missing, sorted(cols))
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
    # 目标侧：**速度有**（内核目标表 `v_ms` ⇒ 悬停框要显目标速度），但**弹体量永远没有**
    # （Mach / 法向过载 / 已行驶距离对目标不适用 = `n/a`）。⚠ 别把 `speed_ms` 写死成"不许在" ——
    # 那是 P6 之前的产物形态；现在按**该键所需列在不在目标表**来判（与上面那条同一个解耦口径）。
    assert ("speed_ms" in tgt) == ("v_ms" in set(_csv(PRODUCTS["target"])[0])), sorted(tgt)
    assert "mach" not in tgt and "n_g" not in tgt and "flown_m" not in tgt
    mis_cols = set(_csv(PRODUCTS["missile"])[0])
    for key, col in (("accel_ms2", "ax_ms2"), ("flown_m", "dist_flown_m"), ("mach", "mach")):
        assert (key in mis) == (col in mis_cols), (key, col, sorted(mis_cols))
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

    # `pending` 的键**由产物表头算出来**（不是写死的常量）：契约说 pending ⟺ 那一列真的不在。
    # 这样"产物还没扩列"与"产物已扩列"两种现实都算得对，"产物重出"再也不会把它弄红。
    cols = {"missile": set(_csv(PRODUCTS["missile"])[0]),
            "target": set(_csv(PRODUCTS["target"])[0])}
    expect_pending = set()
    for f in fields:
        for who in ("missile", "target"):
            src = f["source"][who]
            if src == traj3d.SRC_PENDING:
                expect_pending.add(f["key"])
            elif src == traj3d.SRC_NA:
                assert f["key"] not in d["series"][who], (who, f["key"])
            else:
                assert f["key"] in d["series"][who], (who, f["key"], src)
    assert set(d["hover"]["pending_keys"]) == expect_pending, \
        (d["hover"]["pending_keys"], sorted(expect_pending), sorted(cols["missile"]))
    # 每个 pending 字段都要写清内核侧的**真源头**（接上时照它走，不许换口径）
    assert set(d["hover"]["pending_sources"]) == set(PENDING_KEYS)
    assert "distance_flown_m" in d["hover"]["pending_sources"]["flown_m"]
    assert "accel_x/y/z_m_s2" in d["hover"]["pending_sources"]["accel_ms2"]
    assert "trajectory_normal_g" in d["hover"]["pending_sources"]["n_g"]
    series = d["series"]
    # 非 pending/n-a 的 main 字段：该实体侧要真的有一列，且长度等于点数
    for f in fields:
        if f["group"] != "main":
            continue
        for who in ("missile", "target"):
            if f["source"][who] in (traj3d.SRC_PENDING, traj3d.SRC_NA):
                assert f["key"] not in series[who], (who, f["key"])
                continue
            col = series[who].get(f["key"])
            assert isinstance(col, list) and len(col) == d["points"][who], (who, f["key"])
    # 静态口径（与产物无关）：`range_m`/`horizontal_m` 两侧都是内核列/派生；
    # 目标速度在弹表里天生就有、在目标表里要 `v_ms` 列（有没有列由上面那段动态判）
    assert by_key["range_m"]["source"] == {"missile": traj3d.SRC_KERNEL,
                                          "target": traj3d.SRC_KERNEL}
    assert by_key["horizontal_m"]["source"] == {"missile": traj3d.SRC_DERIVED,
                                               "target": traj3d.SRC_DERIVED}
    assert by_key["speed_ms"]["source"]["missile"] == traj3d.SRC_KERNEL


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
                "t_beam_s", "t_hit_s", "hit", "missile_name",
                # A5（task-23）之后是三个**语义不同**的距离，`miss_m` 已删除
                "cpa_m", "min_separation_m", "fuse_radius_m"):
        assert rep[key] == base[key], key
    assert "miss_m" not in base and "miss_m" not in rep, "A5 已删除 `miss_m`，别再借尸还魂"
    assert rep["colors"]["segments"] == figures.TRAJ_COLORS
    # 图例：线型区分双方（导弹实线 / 目标虚线），颜色仍来自 figures
    ent = rep["entities"]
    assert ent["missile"]["style"] == "solid" and ent["target"]["style"] == "dashed"
    assert ent["missile"]["colors"] == [rep["colors"]["missile_before"], rep["colors"]["missile_after"]]
    assert ent["missile"]["colors"][1] == figures.TRAJ_MISSILE2_COLOR
    assert ent["target"]["colors"] == [s["color"] for s in rep["segments"]]
    assert ent["target"]["name"] == "目标"


# ============================================================ 3. HTTP 层（`GET /fig4`）


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
    body = {"ok": True, "figure": "traj", "tag": "default", "paths": dict(PRODUCTS)}
    body.update(over)
    return body


def test_webui_sandbox_route_serves_the_page_and_the_json(websb):
    """`GET /fig4` 是独立路由发的整页；`GET /api/sandbox/<key>` 给回放数据；静态白名单仍 fail-closed。"""
    addr, state = websb
    job = _inject(state, result=_traj_summary())          # 假任务 id + 真产物路径
    status, raw, ctype = _get(addr, "/fig4?job=x")
    assert status == 200 and "text/html" in ctype
    page = raw.decode("utf-8")
    assert page == webui.read_page_file("sandbox.html"), "整页就该是磁盘上那份，不做二次渲染"
    assert "/static/sandbox.css" in page and "/static/sandbox.js" in page
    assert 'src="/static/viewer3d.js"' in page, "沙盒复用查看器导出的相机/投影"
    assert webui.TOKEN_RE.findall(page) == [], "整页里没有服务端占位符"

    status, raw, ctype = _get(addr, f"/api/sandbox/{job}")
    assert status == 200 and "application/json" in ctype
    d = json.loads(raw.decode("utf-8"))
    assert d["ok"] is True and d["tag"] == "default" and d["job"] == job
    assert d["points"] == {"requested": 800, "missile": 800, "target": 800}
    assert [e["name"] for e in d["events"]][:2] == ["launch", "burnout"]
    assert d["hover"]["main_order"][0] == "t_s" and d["axes"]["x"]["texts"][-1].endswith("k")
    assert set(d["series"]) == {"missile", "target"}

    status, raw1200, _c = _get(addr, f"/api/sandbox/{job}?points=1200")
    assert status == 200 and len(raw1200) > len(raw)
    assert json.loads(raw1200)["points"]["missile"] == 1200
    status, body, _c = _get(addr, f"/api/sandbox/{job}?points=4000")
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
    """400 / 404 / 409 各说各的话：点数、后门已删、未知任务、任务没跑完、任务里没有图4。"""
    addr, state = websb
    done0 = _inject(state, result=_traj_summary())
    for bad in ("4001", "0", "abc", "800.0"):
        status, body, _c = _get(addr, f"/api/sandbox/{done0}?points={bad}")
        assert status == 400 and json.loads(body)["ok"] is False, (bad, status)
        assert "points" in json.loads(body)["errors"][0]

    status, body, _c = _get(addr, "/api/sandbox/nope-nope")
    assert status == 404 and "该任务已不存在" in json.loads(body)["errors"][0]

    # 后门（2026-10-03 删）：`key = default/空` 不再回放仓库里的 `results/traj_default_*`
    status, body, _c = _get(addr, "/api/sandbox/default")
    assert status == 400 and "只显示你自己提交的那一次工况" in json.loads(body)["errors"][0]

    queued = _inject(state, state_name="queued")
    status, body, _c = _get(addr, f"/api/sandbox/{queued}")
    assert status == 409 and "还没跑完" in json.loads(body)["errors"][0]

    plane = _inject(state, result={"ok": True, "figure": "plane", "paths": {"figures": ["x.png"]}})
    status, body, _c = _get(addr, f"/api/sandbox/{plane}")
    assert status == 404 and "没有图4" in json.loads(body)["errors"][0]

    done = _inject(state, result=_traj_summary())
    status, body, _c = _get(addr, f"/api/sandbox/{done}?points=1200")
    assert status == 200
    d = json.loads(body)
    assert d["job"] == done and d["points"]["missile"] == 1200 and d["tag"] == "default"


def test_webui_sandbox_route_does_not_solve(websb):
    """路由层同样**不解算**：把 `solver.run` 换成"一被调用就炸"，三条请求全都能出数据。"""
    addr, state = websb
    job = _inject(state, result=_traj_summary())
    calls = []
    original = solver.run

    def boom(*args, **kwargs):                                   # pragma: no cover - 不该被调用
        calls.append((args, kwargs))
        raise AssertionError("沙盒接口不该调用 solver.run")

    solver.run = boom
    try:
        for path in (f"/api/sandbox/{job}", f"/api/sandbox/{job}?points=1200",
                     f"/api/sandbox/{job}?tag=default"):   # `?tag=` 已不参与读哪份产物
            status, body, _c = _get(addr, path)
            assert status == 200 and json.loads(body)["events"], (path, status)
    finally:
        solver.run = original
    assert calls == []


# ============================================================ 3b. P6：内核列接进产物（真跑一次）

#: 真解算用的表单（`traj_t_beam` 钉死 ⇒ 只跑一遍；`kind=plot` 只出图）
SOLVE_FORM = {"range_m": "50000", "alt_m": "10000", "vm0": "300", "launch_heading_deg": "0",
              "launch_pitch_deg": "0", "target_heading_deg": "180", "target_pitch_deg": "0",
              "target_speed_ms": "300", "target_alt_m": "", "target_bearing_deg": "0",
              "duration_s": "150", "standard": "PL-12", "tier": "fast", "jobs": "1",
              "tag": "sbp6", "figure": "traj", "traj_t_crank": "8", "traj_crank_deg": "70",
              "traj_crank_g": "9", "traj_beam_deg": "90", "traj_beam_g": "9", "traj_lock_m": "",
              "traj_react_delay": "1.0", "traj_weave": "", "traj_weave_amp": "4",
              "traj_weave_hz": "0.1", "traj_t_beam": "34.46", "kind": "plot"}
#: 落在 `.tmp_test/` 下 —— **不动仓库的 `results/`**（正式重出由 Lead 统一做）
SB_TMP = ROOT / ".tmp_test" / "sandbox_p6"


@pytest.fixture(scope="module")
def fresh_products():
    """真跑一次图4 → 拿到**带新列**（P6 扩列后）的产物路径。约 7 s（fast 档、一遍）。"""
    import time
    if SB_TMP.exists():
        shutil.rmtree(SB_TMP, ignore_errors=True)
    cfg = {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1, "formats": ["png"],
           "cache": False, "tag": "sbp6", "poll_ms": 100,
           "figure_dir": str(SB_TMP / "figures"), "result_dir": str(SB_TMP / "results")}
    state = webui.WebState(cfg, quiet=True)
    payload, code = webui.submit_job(dict(SOLVE_FORM), state)
    assert code == 200 and payload["ok"], (code, payload)
    job = state.jobs.get(payload["id"])
    deadline = time.time() + 240
    while job.state not in ("done", "error") and time.time() < deadline:
        time.sleep(0.2)
        job = state.jobs.get(payload["id"])
    assert job.state == "done", (job.state, job.error, job.logs[-5:])
    return job.result["paths"]


def test_webui_sandbox_products_carry_the_kernel_columns_both_tables(fresh_products):
    """P6 的列契约：**两张表分别**断言列集合（少一列就是读侧静默空值 —— 本仓最该防的"绿着但错"）。"""
    from missile_sim import record
    mis_hdr = Path(fresh_products["missile"]).read_text(encoding="utf-8").splitlines()[0]
    tgt_hdr = Path(fresh_products["target"]).read_text(encoding="utf-8").splitlines()[0]
    mis_cols, tgt_cols = mis_hdr.split(","), tgt_hdr.split(",")
    assert tuple(mis_cols) == record.TRAJ_MISSILE_COLUMNS, mis_cols
    assert tuple(tgt_cols) == record.TRAJ_TARGET_COLUMNS, tgt_cols
    assert len(mis_cols) == 22 and len(tgt_cols) == 5
    # 每一行都要有同样多的值（列名与值一一对应；`record` 里也有自检，这里再钉一次产物层）
    for key, n in (("missile", 22), ("target", 5)):
        for r in _csv(fresh_products[key])[:5]:
            assert len(r) == n, (key, r)
    # 目标表**必须**有 v_ms（就是它让悬停框的目标速度从 pending 变成内核值）
    assert "v_ms" in tgt_cols


def test_webui_sandbox_new_columns_replace_pending_with_kernel_values(fresh_products):
    """新列到位后：`pending_keys` 清空、`derived` 只剩两个、目标侧 8 项变 `n/a`，逐点读数补齐。"""
    d = traj3d.build_replay(dict(fresh_products), points=800)
    assert d["hover"]["pending_keys"] == [], d["hover"]["pending_keys"]
    assert d["hover"]["derived_keys"] == ["accel_ms2", "horizontal_m"], d["hover"]["derived_keys"]
    assert d["hover"]["na_keys"] == ["accel_ms2", "aoa_deg", "aoa_eff_deg", "flown_m", "mach",
                                     "n_g", "req_g", "sf_g"], d["hover"]["na_keys"]
    assert set(d["hover"]["source_enum"]) == {"kernel", "derived", "n/a", "pending"}
    mis, tgt = d["series"]["missile"], d["series"]["target"]
    n = d["points"]["missile"]
    for key in ("mach", "accel_ms2", "n_g", "sf_g", "req_g", "aoa_deg", "aoa_eff_deg", "flown_m"):
        assert isinstance(mis.get(key), list) and len(mis[key]) == n, key
    for key in ("mach", "n_g", "aoa_deg", "flown_m", "accel_ms2"):
        assert key not in tgt, f"目标侧不该有 {key}（契约里是 n/a）"
    assert isinstance(tgt.get("speed_ms"), list) and len(tgt["speed_ms"]) == n
    # 值本身要合理（拿产物列直接对：**按时刻对齐** —— 沙盒的抽稀带强制点，不是等间隔下标）
    rows = _csv(fresh_products["missile"])
    by_t = {round(float(r["t_s"]), 3): r for r in rows}
    for j in list(range(1, 40)) + [len(mis["mach"]) // 2]:
        r = by_t[mis["t_s"][j]]
        assert mis["mach"][j] == pytest.approx(float(r["mach"]), rel=2e-3)
        assert mis["flown_m"][j] == pytest.approx(float(r["dist_flown_m"]), abs=0.11)
        assert mis["n_g"][j] == pytest.approx(float(r["n_g"] or 0.0), abs=1e-3)
    trows = _csv(fresh_products["target"])
    assert tgt["speed_ms"][0] == pytest.approx(float(trows[0]["v_ms"]), abs=0.01)
    # 目标侧的弹量在契约里是 n/a，前端要渲染"不适用"（不是"待接入"，也不是"—"）
    js = (ROOT / "src" / "missile_sim" / "webui_static" / "sandbox.js").read_text(encoding="utf-8")
    assert "r.na" in js and "sbNa" in js and "NA_TEXT" in js
    spec = {f["key"]: f for f in d["hover"]["fields"]}
    assert spec["mach"]["source"] == {"missile": "kernel", "target": "n/a"}
    assert spec["n_g"]["source"]["target"] == "n/a" and spec["flown_m"]["source"]["target"] == "n/a"
    assert spec["speed_ms"]["source"] == {"missile": "kernel", "target": "kernel"}
    assert spec["accel_ms2"]["source"]["missile"] == "derived"


def test_webui_sandbox_cross_checks_against_the_kernel_columns(fresh_products):
    """三条**对拍照**（差分/几何 vs 内核列）：数字都落在"能对得上"的范围内。

    ① Mach：`air_speed_ms / sound(alt)`（声速取内核 `_atmosphere`）—— CSV 只有 6 位有效数字，
       所以门限是 1e-5 而不是内核那几个 1e-12；
    ② 已行驶距离：折线弧长 vs 内核 `dist_flown_m`（相对差 < 1e-4）；
    ③ 目标速度：位置差分（±0.21 s 窗口）vs 内核 `target_speed_m_s`（相对差 < 5e-3）；
    ④ 加速度：差分 vs 内核三分量在速度方向的投影 —— **平稳段**对得上，点火/分级/燃尽那种
       不连续处会差很多（内核 `accel_*` 是**上一步**的值，差分是中心平均），这正是
       "显示必须用内核值"的理由，所以这里只断言平稳段。
    """
    from missile_sim import solver
    mis, tgt = _csv(fresh_products["missile"]), _csv(fresh_products["target"])
    t = [float(r["t_s"]) for r in mis]
    v = [float(r["v_ms"]) for r in mis]

    worst_mach = 0.0
    for r in mis[::25]:
        ref = float(r["air_speed_ms"]) / solver.atmosphere(float(r["y_m"]))[1]
        worst_mach = max(worst_mach, abs(float(r["mach"]) - ref) / max(ref, 1e-12))
    assert worst_mach < 1e-5, worst_mach

    arc = traj3d._cumulative(t, [float(r["x_m"]) for r in mis], [float(r["y_m"]) for r in mis],
                             [float(r["z_m"]) for r in mis])
    kern = float(mis[-1]["dist_flown_m"])
    assert abs(arc[-1] - kern) / kern < 1e-4, (arc[-1], kern)

    tt = [float(r["t_s"]) for r in tgt]
    dsp = traj3d._speed_of(tt, [float(r["x_m"]) for r in tgt], [float(r["y_m"]) for r in tgt],
                           [float(r["z_m"]) for r in tgt], half=traj3d.TARGET_HALF)
    tv = [float(r["v_ms"]) for r in tgt]
    rel = [abs(dsp[i] - tv[i]) / tv[i] for i in range(len(tv)) if dsp[i] is not None]
    assert max(rel) < 5e-3, max(rel)
    assert sum(rel) / len(rel) < 1e-3, sum(rel) / len(rel)

    diff = traj3d._axial_accel(t, v)
    proj = []
    for r in mis:
        vx, vy, vz = (float(r[k]) for k in ("vx_ms", "vy_ms", "vz_ms"))
        n = math.sqrt(vx * vx + vy * vy + vz * vz)
        ax, ay, az = (float(r[k]) for k in ("ax_ms2", "ay_ms2", "az_ms2"))
        proj.append((ax * vx + ay * vy + az * vz) / n if n > 1e-9 else None)
    # 不连续点：推力变化的那一步（点火/一级关机→二级点火/燃尽）±2 个采样
    thrust = [float(r["thrust_N"] or 0.0) for r in mis]
    jump = {i for i in range(1, len(mis)) if abs(thrust[i] - thrust[i - 1]) > 1.0}
    jump |= {i + d for i in jump for d in (-1, 1)}
    calm = [i for i in range(2, len(t) - 2)
            if i not in jump and diff[i] is not None and proj[i] is not None]
    worst_calm = max(abs(diff[i] - proj[i]) for i in calm)
    assert worst_calm < 5.0, worst_calm          # 平滑段：差分与内核投影贴得住
    worst_all = max(abs(diff[i] - proj[i]) for i in range(2, len(t) - 2)
                    if diff[i] is not None and proj[i] is not None)
    assert worst_all > worst_calm, "应当存在不连续点让两者明显分开（否则这条判据没测到东西）"
    print(f"[sandbox] 对拍：mach 相对差 {worst_mach:.2e}、弧长 {abs(arc[-1] - kern) / kern:.2e}、"
          f"目标速度最大 {max(rel):.2e}、加速度平稳段 {worst_calm:.3f} m/s²（全段最大 {worst_all:.1f}）")


def test_webui_sandbox_trajectory_never_hits_the_engine_cache(tmp_path):
    """`want_rows=True` 必须**绕开缓存**（`engine.one()` 的既有行为）—— 于是"旧缓存缺新列"不可能发生。

    判据用 `Engine.stats["cache"]`（内核/引擎自己数的命中数），不用读代码：
    ① 先跑一次 `want_rows=False`（写缓存）；② 再跑 `want_rows=True`（**不许命中**，
    且返回的 rows 里要有新列）；③ 再跑一次 `want_rows=False`（**必须命中**，证明缓存确实生效了 —— 正向对照）。
    """
    from missile_sim import engine as engine_mod
    from missile_sim.spec import Scene
    scene = Scene(range_m=50000.0, alt_m=10000.0, vm0=300.0, target_heading_deg=180.0,
                  target_speed_ms=300.0, duration_s=150.0)
    eng = engine_mod.Engine(scene, missile="cn_pl12", tier="fast", jobs=1, cache=True,
                            cache_path=tmp_path / "cache.json")
    a = eng.one(want_rows=False)
    assert a.ok and eng.stats["cache"] == 0
    b = eng.one(want_rows=True)
    assert b.ok and b.rows, "带行的求解必须给出 rows"
    assert eng.stats["cache"] == 0, "want_rows=True 不许命中缓存"
    assert "mach" in b.rows[0] and "dist_flown" in b.rows[0] and "ax" in b.rows[0]
    c = eng.one(want_rows=False)
    assert c.ok and eng.stats["cache"] == 1, "正向对照：不带行的第二次应当命中缓存"


# ============================================================ 4. 前端契约
def test_sandbox_reports_a_miss_with_the_closest_distance(tmp_path):
    """脱靶分支：默认工况是**命中**，`hit=false` 那条路径没被走到过 —— 这里把它走一遍。

    只翻 manifest 里的"结局"（`hit/event/t_hit_s/min_separation_m/cpa_m`），轨迹数据不动
    ⇒ 这条测的是**事件文案与颜色分支**（`脱靶: … 秒（最近接近 … m）` + `colors.miss`），不是物理。
    ⚠ A5 语义：未命中时 `cpa_m` 必须**等于** `min_separation_m`（同一趟飞行，不许另算）；命中时
    `min_separation_m` 是引信半径、真 CPA 是 `cpa_m` —— 两种都不许写成"脱靶量"。
    """
    man = _manifest()
    man["run"].update({"hit": False, "event": "time_limit", "t_hit_s": None,
                       "min_separation_m": 123.4, "cpa_m": 123.4, "fuse_radius_m": 10.0})
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
    assert end["hit"] is False
    assert end["min_separation_m"] == 123.4 and end["cpa_m"] == 123.4
    assert end["label"] == "脱靶"
    assert end["text"] == "脱靶: 69.17 秒（最近接近 123.4 m）", end["text"]
    assert d["hit"] is False and d["cpa_m"] == 123.4 and d["min_separation_m"] == 123.4
    assert d["fuse_radius_m"] == 10.0
    assert d["colors"]["miss"] == figures.TRAJ_MISS_COLOR
    assert [e["t_s"] for e in d["events"]] == sorted(e["t_s"] for e in d["events"])
    # 前端按 `hit` 布尔挑颜色（命中用 TRAJ_HIT_COLOR、脱靶用 TRAJ_MISS_COLOR）
    js = (ROOT / "src" / "missile_sim" / "webui_static" / "sandbox.js").read_text(encoding="utf-8")
    assert "e.hit === true ? d.colors.hit" in js and "d.colors.miss" in js
    # 左栏那两行也要用 A5 的三个字段（不许再引用已删除的 `miss_m`）
    assert "d.miss_m" not in js and "d.cpa_m" in js and "d.fuse_radius_m" in js


def test_sandbox_hit_never_calls_the_fuse_radius_a_miss_distance(tmp_path):
    """命中分支的文案：`min_separation_m` = 引信半径（不是脱靶量），真 CPA 另有其数。"""
    man = _manifest()
    man["run"].update({"hit": True, "event": "proximity_fuse",
                       "t_hit_s": man["run"]["t_end_s"],
                       "min_separation_m": 10.0, "cpa_m": 0.004, "fuse_radius_m": 10.0})
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
    assert end["label"] == "命中"
    assert "引信半径 10.0 m" in end["text"], end["text"]
    assert "最近接近 0.004 m" in end["text"], end["text"]
    assert "脱靶" not in end["text"] and "10.0 m" not in end["text"].split("引信半径")[0], end["text"]
    # CPA 没量出来（网格路径）：文案不许拿引信半径冒充最近接近
    man["run"]["cpa_m"] = None
    (tmp_path / Path(PRODUCTS["manifest"]).name).write_text(
        json.dumps(man, ensure_ascii=False), encoding="utf-8")
    end2 = [e for e in traj3d.build_replay(paths, points=800)["events"]
            if e["name"] == "end"][0]
    assert end2["cpa_m"] is None and "最近接近" not in end2["text"], end2["text"]
    assert "引信半径 10.0 m" in end2["text"]


def _write_old_products(root: Path) -> dict:
    """造一份**扩列之前**的小产物（导弹 8 列 / 目标 4 列）。

    ⚠ 降级路径不能拿仓库产物当"老产物"（产物一重出就红）—— 所以这里现造一份最小的：
    6 个采样点、一条直飞分段、一个命中结局。
    """
    root.mkdir(parents=True, exist_ok=True)
    mis = root / "traj_old_missile.csv"
    tgt = root / "traj_old_target.csv"
    seg = root / "traj_old_segments.csv"
    mis_rows = [(0.0, 0.0, 10000.0, 0.0, 300.0, 198.0, 0.0, 50000.0),
                (1.0, 310.0, 10000.0, 0.0, 320.0, 197.5, 30000.0, 49690.0),
                (2.0, 640.0, 10000.0, 0.0, 350.0, 197.0, 35000.0, 49360.0),
                (3.0, 990.0, 10000.0, 0.0, 380.0, 196.5, 35000.0, 49010.0),
                (4.0, 1360.0, 10000.0, 0.0, 400.0, 196.0, 20000.0, 48640.0)]
    tgt_rows = [(t, 50000.0 - 300.0 * t, 10000.0, 0.0) for t, *_ in mis_rows]
    mis.write_text("t_s,x_m,y_m,z_m,v_ms,mass_kg,thrust_N,range_m\n" + "".join(
        ",".join(f"{v:.6g}" for v in r) + "\n" for r in mis_rows), encoding="utf-8")
    tgt.write_text("t_s,x_m,y_m,z_m\n" + "".join(
        ",".join(f"{v:.6g}" for v in r) + "\n" for r in tgt_rows), encoding="utf-8")
    seg.write_text("t0_s,t1_s,kind,label,phase,heading0_deg,heading1_deg,color_key,truncated\n"
                   "0,4,straight,直飞,,180,180,grey,0\n", encoding="utf-8")
    man = {"schema": 1, "figure": "traj", "tag": "old", "tier": "fast", "backend": "compiled-c",
           "scene": {"launch_position_m": [0.0, 10000.0, 0.0],
                     "target_position_m": [50000.0, 10000.0, 0.0],
                     "target_speed_ms": 300.0, "range_m": 50000.0},
           "run": {"missile": "PL-12", "beta": 3078.1, "gamma": 56.6, "hit": True,
                   "event": "proximity_fuse", "t_hit_s": 4.0, "t_end_s": 4.0,
                   "min_separation_m": 10.0, "cpa_m": 0.01, "fuse_radius_m": 10.0,
                   "v_impact_m_s": 400.0, "max_alt_m": 10000.0,
                   "anchor": {"mode": "一遍法", "lock_distance_m": 16000.0, "t_beam_s": 3.0,
                              "range_at_beam_m": 15000.0, "completed": True,
                              "heading_at_beam_deg": 180.0, "react_delay_s": 1.0,
                              "t_react_s": 4.0},
                   "marks": [{"name": "launch", "t_s": 0.0, "note": "发射"},
                             {"name": "seeker_on", "t_s": 3.0, "note": "导引头开机"},
                             {"name": "end", "t_s": 4.0, "note": "命中"}]}}
    (root / "traj_old.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return {"missile": str(mis), "target": str(tgt), "segments": str(seg),
            "manifest": str(root / "traj_old.json")}


def test_sandbox_old_products_degrade_to_pending(tmp_path):
    """**扩列之前的产物**：悬停框自动退回"待接入"，逐点读数只出现老列 —— 不许报错、不许编数。"""
    paths = _write_old_products(tmp_path / "old")
    d = traj3d.build_replay(paths, points=800)
    assert set(d["hover"]["pending_keys"]) == set(PENDING_KEYS), d["hover"]["pending_keys"]
    assert set(d["hover"]["derived_keys"]) == {"horizontal_m"}, d["hover"]["derived_keys"]
    assert set(d["hover"]["na_keys"]) == {"accel_ms2", "aoa_deg", "aoa_eff_deg", "flown_m",
                                         "mach", "n_g", "req_g", "sf_g"}
    assert set(d["series"]["missile"]) == {"t_s", "alt_m", "horizontal_m", "range_m",
                                          "yaw_deg", "pitch_deg", "speed_ms"}
    assert set(d["series"]["target"]) == {"t_s", "alt_m", "horizontal_m", "range_m",
                                         "yaw_deg", "pitch_deg"}
    assert d["points"]["missile"] == 5 and d["points"]["target"] == 5
    assert d["events"] and d["events"][-1]["name"] == "end"
    # 事件文案在**老产物**上同样成立（三个距离来自 manifest，与 CSV 列无关）
    assert "引信半径 10.0 m" in d["events"][-1]["text"]


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


def _sandbox_static() -> dict:
    static = ROOT / "src" / "missile_sim" / "webui_static"
    return {n: (static / n).read_text(encoding="utf-8")
            for n in ("sandbox.js", "sandbox.html", "sandbox.css")}


def _fn_body(text: str, header: str) -> str:
    """取 `function x(...) {` 起、配对大括号止的那一段 —— 按深度切，够用（这几段里没有字符串花括号）。"""
    i = text.index(header)
    j = text.index("{", i)
    depth = 0
    for k in range(j, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[j:k + 1]
    raise AssertionError(f"{header} 的大括号没配对")


def test_sandbox_marks_both_entities_at_their_live_positions():
    """弹与敌机的**实时位置点**：两个 DOM 点、与各自标签同一个投影点、名字标签取自带响应。

    ⚠ 这条判据是"用户 2026-10-03 的界面口径"（原话：导弹实时位置虽有标签跟着，但没有小点标记；
    敌机则完全没有实时位置）落成的**前端契约**：行为本身由真浏览器取证（DOM 里的 left/top 与
    截图像素），这里钉住不许回退的几件事。
    ⚠ 点是 **DOM 点不是 GL 点**：WebGL 画布永远画在 HTML 之下，GL 点会被 `#sbEvents` 的白底
    事件标签压得几乎看不见 —— 那正是"看不到小点"的成因，所以这里钉住 `.sbdot` 的 z-index。
    """
    f = _sandbox_static()
    js, html, css = f["sandbox.js"], f["sandbox.html"], f["sandbox.css"]
    # 两个实体各一个点，节点在页面里建好、由 `dotAt()` 反复用（不是每帧 createElement）
    for need in ("entityDots", "dotAt", "sbDotMissile", "sbDotTarget"):
        assert need in js, f"sandbox.js 缺 {need}"
    for need in ('id="sbDotMissile"', 'id="sbDotTarget"', 'class="sbdot"'):
        assert need in html, f"sandbox.html 缺 {need}"
    for bad in ("bDot.add(", "bDot.draw(", "VS_DOT", "FS_DOT", "progDot"):
        assert bad not in js, f"实体位置点不该再走 GL 点那条路（{bad} 会被事件标签压住）"
    # 两个点都画：少一个就是"某一方没有实时位置"（用户报的就是这个）
    for need in ('dotAt(el("sbDotMissile"), e.missile, e.missileColor)',
                 'dotAt(el("sbDotTarget"), e.target, e.targetColor)'):
        assert need in js, f"没画点：{need}"
    # 点径有下限（CSS 像素写死，不随视距缩），且两个实体不一样大（弹小、敌机大）
    assert "#sbDotMissile { width: 9px" in css and "#sbDotTarget { width: 12px" in css
    assert ".sbdot" in css and "border-radius: 50%" in css and "translate(-50%, -50%)" in css, \
        "点必须以 left/top 为圆心（与标签同一个投影点）"
    assert "z-index: 1" in css, "点要盖在事件标签（z-index auto）之上"
    # 敌机的名字只能来自响应（`entities.target.name`），前端不许编
    assert "d.entities.target.name" in js, "敌机名字必须取响应的 entities.target.name"
    # 标签 DOM 与样式：与导弹读数**反着放**，两机贴近时不互相压住
    assert 'id="sbTargetLabel"' in html, "sandbox.html 缺 sbTargetLabel 容器"
    assert "#sbTargetLabel" in css, "sandbox.css 没给敌机标签样式"
    assert "translate(12px, 12px)" in css and "translate(10px, -26px)" in css, \
        "两个标签的偏移必须一上一下（同向会在命中瞬间叠在一起）"
    # 每帧只改数据、**不新建对象**：DOM/GL 对象都在 boot 时建好（否则跑久了卡在 GC 上）
    for fn in ("function entityDots(", "function dotAt(", "function targetLabel("):
        b = _fn_body(js, fn)
        for bad in ("createElement", "createBuffer", "makeProg(", "compile("):
            assert bad not in b, f"{fn} 每帧都在重建 {bad}"


def test_sandbox_draws_entity_markers_after_the_track_clear():
    """⚠ 静默缺陷回归：实体线框曾经**永远画不出来** —— `frame()` 里 `entities()` 先写 `bLine`，
    紧接着 `flown()` 第一件事就是 `bLine.clear()`，刚写的线当场被清空；而 DOM 读数用的是
    `entities()` 的返回值，照样跟着走 ⇒ 屏幕上"只有标签、没有实体"，测试全绿。

    所以这里钉两件事：**画线框要在清屏之后**；**位置、颜色只有一份来源**（不许谁再 `posAt` 一遍）。
    """
    js = _sandbox_static()["sandbox.js"]
    frame = _fn_body(js, "function frame(now)")
    assert "flown()" in frame and "entities(M)" in frame
    assert frame.index("flown()") < frame.index("entities(M)"), \
        "flown() 里的 bLine.clear() 会把实体线框清掉：entities(M) 必须排在 flown() 之后"
    assert frame.index("entities(M)") < frame.index("bLine.draw(M)"), "线框得在 bLine 上传之前攒好"
    # 两个位置点、两条线框、两个标签共用 `e`（同一个 ents 对象）—— 同源才不会"标签在飘"
    for need in ("var e = entities(M)", "readout(e.missile)", "targetLabel(e.target)", "entityDots(e)"):
        assert need in frame, f"frame() 里缺 {need}"
    ents = _fn_body(js, "function entities(")
    assert ents.count("posAt(") == 2, f"entities() 里位置只该算一次（弹+机各一次）：{ents.count('posAt(')}"
    for need in ("wire(bLine, mp,", "wire(bLine, tp,", "return { missile: mp, target: tp,"):
        assert need in ents, f"entities() 缺 {need}（位置与线框/返回值必须同源）"
    assert "missileColor" in ents and "targetColor" in ents, "颜色也一起返回，别在两处各挑一次"
    for fn in ("function readout(", "function targetLabel("):
        assert "posAt(" not in _fn_body(js, fn), f"{fn} 又自己算了一遍位置"


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
    assert out["fmt"] == ["3.14", "50000", "—"], out["fmt"]      # 内核在该点没定义 → "—"（不是"待接入"）
    assert "命中" in out["hit"] and "引信半径" in out["hit"], out["hit"]   # A5 文案
    assert "脱靶" not in out["hit"], out["hit"]
    assert abs(out["trackTime"] - 69.172) < 0.01, out["trackTime"]
    keys = [row.split("|")[0] for row in out["fields"]]
    assert keys == REF_HOVER_ORDER, keys
    # 悬停取值：导弹 400 号点 = 服务端那一列的值；末点 = 终止前的最近距离（A5）
    mid = out["hoverMid"]
    assert mid["rows"][0]["key"] == "t_s" and 20.0 < mid["rows"][0]["value"] < 50.0, mid
    end = out["hoverEnd"]
    endrows = {r["key"]: r for r in end["rows"]}
    midrows = {r["key"]: r for r in out["hoverMid"]["rows"]}
    man = _manifest()["run"]
    # ⚠ 这几个断言**由产物推**（不写死）：产物有没有扩列都算得对
    assert endrows["range_m"]["value"] is not None
    assert abs(endrows["range_m"]["value"] - man["min_separation_m"]) < 0.5, endrows["range_m"]
    # 弹侧的 mach：有列就是内核值（`kernel`）、没有列就是"待接入"（`pending`）；永远不是 `n/a`
    have_mach = "mach" in set(_csv(PRODUCTS["missile"])[0])
    assert midrows["mach"]["na"] is False
    assert midrows["mach"]["pending"] is (not have_mach)
    if have_mach:
        assert isinstance(midrows["mach"]["value"], (int, float)), midrows["mach"]
    else:
        assert midrows["mach"]["value"] is None, midrows["mach"]
    # 目标侧 mach 永远"不适用"，与前一张表有没有列无关
    assert endrows["mach"]["value"] is None and endrows["mach"]["na"] is True
    assert "不适用" in endrows["mach"]["text"]
    print("[sandbox] 悬停取值自检：导弹#400 t=%.2f s，目标末点 range=%.1f m、mach=%s"
          % (out["hoverMid"]["rows"][0]["value"], endrows["range_m"]["value"],
             "内核" if have_mach else "待接入"))


def _get_full(addr, path):
    """带响应头的 GET（别名判据要看 `Location`；`_get()` 只回 body）。"""
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


def test_old_sandbox_page_path_is_kept_as_a_302_alias(websb):
    """别名（随下个破坏性版本删）：老 `/sandbox` / `/sandbox.html` -> 302 -> `/fig4`。

    用户口径（docs/UX-TARGET.md §3）：沙盒页由 `/sandbox` 改名为 `/**fig4**`，旧路径留别名、不许 404。
    别名最容易悄悄腐烂 —— 它烂掉时没有别的判据会红，所以这里单独钉一条。
    """
    addr, state = websb
    status, headers, _raw = _get_full(addr, "/sandbox?job=x")
    assert status == 302, status
    assert headers.get("Location") == "/fig4?job=x", headers.get("Location")
    # 老路径的 `.html` 变体也留别名
    assert _get_full(addr, "/sandbox.html")[0] == 302

    # 新路径就是沙盒整页本身
    s_new, _h2, page = _get_full(addr, "/fig4?job=x")
    assert s_new == 200, s_new
    assert b"/static/sandbox.js" in page and b"/static/sandbox.css" in page
    # 数据接口**没**跟着页面搬家（沙盒侧保名；也因此不与老三维数据路径 /api/fig4/<id> 撞车）
    job = _inject(state, result=_traj_summary())
    assert _get(addr, f"/api/sandbox/{job}")[0] == 200
    assert _get(addr, "/api/sandbox/default")[0] == 400, "后门（无工况回放仓库产物）已删"


def test_sandbox_has_no_replay_backdoor(websb):
    """后门（2026-10-03 删）：`key=default/空` 与 `?tag=` 都不再回放仓库旧产物。

    用户口径（docs/UX-TARGET.md §2）：沙盒**严格随输入** —— 没给工况就不显示、不跑，
    也不回放仓库里的旧产物。后门只要存在，早晚有人（包括验收的人）拿旧产物当"我这次的结果"看。
    """
    addr, state = websb
    status, body, _c = _get(addr, "/api/sandbox/default")
    assert status == 400, status
    assert "只显示你自己提交的那一次工况" in json.loads(body)["errors"][0]

    status, body, _c = _get(addr, "/api/sandbox/")
    assert status == 400, status

    job = _inject(state, result=_traj_summary())
    status, body, _c = _get(addr, f"/api/sandbox/{job}?tag=web&tag=default")
    assert status == 200, (status, body[:160])
    assert json.loads(body)["tag"] == "default", "只认任务自己的 tag，不认 query 里的 tag"


def test_sandbox_unknown_job_says_resubmit_instead_of_blank(websb):
    """失效 job id（服务重启后任务表清空，这条一定会发生）必须给明确提示，不许白屏。"""
    addr, _state = websb
    status, body, _c = _get(addr, "/api/sandbox/nosuchjob")
    assert status == 404, status
    err = json.loads(body)["errors"][0]
    assert "该任务已不存在" in err and "重新提交" in err, err


def test_homepage_opens_with_three_static_figures_and_a_hidden_sandbox(websb):
    """单页四块 + 静态形态（docs/UX-TARGET.md §1/§2）：

    无输入时 图1/图2/图3 直出 11 弹标称点（离线产物，不解算），**沙盒区不显示**；
    页面里也不许留 `?tag=` 这种回放后门。
    """
    addr, _state = websb
    status, raw, _c = _get(addr, "/")
    assert status == 200
    page = raw.decode("utf-8")
    for anchor in ('id="fig1"', 'id="fig2"', 'id="fig3"', 'id="fig4"'):
        assert anchor in page, anchor
    assert 'id="fig4" hidden' in page, "没有工况 ⇒ 沙盒区必须隐藏"
    assert "/figures/fig_isotime_plane_static.png" in page, "图1 静态形态（只散点、不解算）"
    assert "/figures/fig_bg_plane_static.png" in page, "图2 静态形态（不扫网格）"
    assert 'src="/fig3?bg=transparent"' in page, "图3 静态形态（11 弹标称点，v5）"
    assert "?tag=" not in page, "页面里不许留 tag 后门"


def test_static_forms_come_from_offline_products_without_scanning():
    """静态形态的产物口径：图1 `with_iso=False`、图2 不扫网格 —— 都不依赖输入、秒级可出。"""
    root = Path(__file__).resolve().parent.parent
    plane = json.loads((root / "results" / "plane_static.json").read_text(encoding="utf-8"))
    bg = json.loads((root / "results" / "bg_static.json").read_text(encoding="utf-8"))
    assert plane["with_iso"] is False, "图1 静态形态不许带等时线（等时线是动态形态）"
    assert not bg.get("scan") and not bg.get("n_cases"), "图2 静态形态不许扫网格"
    for name in ("fig_isotime_plane_static.png", "fig_bg_plane_static.png"):
        p = root / "figures" / name
        assert p.exists() and p.stat().st_size > 10_000, name

# -*- coding: utf-8 -*-
"""弹道模式的三维轨迹层（`webui_static/traj3d.js`）判据：几何 / 取景 / 兜底 / 零第三方。

为什么要有**数值**判据（源码形状挡不住的那几条）：
  * 点列口径是 `[t, x, y, z, v]`，画的时候必须取 **(x, y, z)** —— 写成 `(t, x, y)` 或
    `(x, z, y)` 时画面只是"看着有点怪"，不抛异常；
  * 相机必须**按包围盒自适应**：默认场景 z 恒为 0（轨迹落在一个竖直平面里），
    写死轴向/边长的实现会把那条弧线挤成一条线；
  * 三点全 0 / 只有一个点时不许除零、不许画空画面（`radius` 兜底 >= 1）。

无 node => `pytest.skip` 并打印原因（与 `-k figs2d` / `-k fig3_static` 同款）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "missile_sim" / "webui_static" / "traj3d.js"

NODE_HOST = r"""
const fs = require('fs');
const T = require(process.argv[2]);
const spec = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = {bounds: {}, geo: {}, fit: {}, api: {mount: typeof T.mount}};
(spec.bounds || []).forEach(function (t) {
  const b = T.boundsOf(t.series);
  out.bounds[t.name] = {center: b.center, span: b.span, radius: b.radius, points: b.points};
});
(spec.geo || []).forEach(function (t) {
  const g = T.buildGeometry(t.series, T.CHROME_DEFAULT);
  const pts = [];
  for (let i = 0; i < g.pos.length; i += 3) { pts.push([g.pos[i], g.pos[i + 1], g.pos[i + 2]]); }
  out.geo[t.name] = {lines: g.lines, n_vert: g.pos.length / 3, n_idx: g.idx.length,
                     bounds: {center: g.bounds.center, span: g.bounds.span, radius: g.bounds.radius},
                     first: pts.slice(0, 3), last: pts.slice(-1)[0], pts: pts,
                     prog: (g.prog || []).slice()};
});
(spec.fit || []).forEach(function (t) {
  const g = T.buildGeometry(t.series, T.CHROME_DEFAULT);
  const cam = {az: t.az, el: t.el, dist: 1, pan: [0, 0, 0]};
  out.fit[t.name] = T.fitDistance(g, cam, t.aspect);
});
// 2026-10-24 新增：投影 / 拾取 / 调色板
out.proj = {};
(spec.proj || []).forEach(function (t) {
  const M = T.M4.mul(T.M4.persp(0.9, t.aspect, 100, 400000),
                     T.M4.view(t.az, t.el, t.dist, t.cx, t.cy, t.cz));
  const pts = t.points.map(function (p) { return T.projectPoint(M, t.W, t.H, p); });
  const a = pts[0], b = pts[1];
  const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const on = T.segDist(mid[0], mid[1], a[0], a[1], b[0], b[1]);
  const off = T.segDist(mid[0] + t.away, mid[1] + t.away, a[0], a[1], b[0], b[1]);
  out.proj[t.name] = {pts: pts, on: on.dist, tmid: on.t, off: off.dist};
});
out.palette = (spec.palette || []).map(function (t) {
  const seen = [];
  for (let i = 0; i < t.n; i++) { seen.push(T.spinHex(t.base, i, t.n)); }
  return {colors: seen, distinct: new Set(seen).size};
});
process.stdout.write(JSON.stringify(out));
"""


def _node():
    return shutil.which("node")


def _probe(tmp_path: Path, spec: dict) -> dict:
    node = _node()
    if node is None:
        pytest.skip("这台机器没有 node，跳过 traj3d 数值判据（源码契约仍在 test_static_pool_page）")
    host = tmp_path / "traj3d_host.js"
    host.write_text(NODE_HOST, encoding="utf-8")
    spec_path = tmp_path / "traj3d_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    subprocess.run([node, "--check", str(JS)], check=True, capture_output=True, text=True)
    proc = subprocess.run([node, str(host), str(JS), str(spec_path)],
                          capture_output=True, text=True, timeout=120, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr[-1200:]
    return json.loads(proc.stdout)


#: 三条真实形态（Lead 2026-10-24 实测的 PL-12 包围盒量级）：
#: 迎头（z 恒 0，共面）/ 方位角 45（z 到 35345）/ 方位角 45 + 俯仰 20。
COPLANAR = [[0, 10000, 0], [12000, 11500, 0], [24000, 12700, 0], [36434, 9999, 0]]
BEARING45 = [[0, 10000, 0], [8000, 10500, 17000], [17204, 9937, 35345]]
PITCH20 = [[0, 10000, 0], [9000, 11000, 18000], [17838, 12066, 35346]]
FLAT = [[0, 10000, 0], [5000, 10400, 0], [10000, 10500, 0]]


def test_bounds_are_adaptive_and_never_divide_by_zero(tmp_path):
    """包围盒按 x/y/z 实际范围算；共面轨迹也不会退化成一条线；全 0 时有兜底。"""
    got = _probe(tmp_path, {"bounds": [
        {"name": "coplanar", "series": [{"key": "a", "points": COPLANAR}]},
        {"name": "threed", "series": [{"key": "a", "points": BEARING45}]},
        {"name": "empty", "series": []},
        {"name": "single", "series": [{"key": "a", "points": [[0, 0, 0]]}]},
    ]})
    cop = got["bounds"]["coplanar"]
    assert cop["span"][2] == 0, cop                     # z 恒 0：共面是这个场景的物理事实
    assert cop["span"][0] > 30000 and cop["span"][1] > 2000, cop
    assert cop["radius"] > cop["span"][0] * 0.4, cop    # 半径要反映真实跨度
    three = got["bounds"]["threed"]
    assert three["span"][2] > 30000, three              # 给了方位角就是真三维
    for name in ("empty", "single"):
        b = got["bounds"][name]
        assert b["radius"] >= 1, (name, b)              # 兜底：不除零、不留空画面
        assert all(v == 0 for v in b["span"]), (name, b)


def test_geometry_takes_xyz_and_keeps_every_point_in_order(tmp_path):
    """轨迹线按 (x, y, z) 逐点入几何、顺序不动；两枚弹 => 两条线。"""
    got = _probe(tmp_path, {"geo": [
        {"name": "one", "series": [{"key": "a", "color": "#d32f2f", "points": BEARING45}]},
        {"name": "two", "series": [
            {"key": "a", "color": "#d32f2f", "points": BEARING45},
            {"key": "b", "color": "#388e3c", "points": PITCH20}]},
    ]})
    one = got["geo"]["one"]
    assert one["lines"] == 1, one
    assert one["n_vert"] > len(BEARING45), one
    assert one["n_idx"] > 0 and one["n_idx"] % 2 == 0, one       # LINES 成对给
    for p in BEARING45:
        assert p in one["pts"], "轨迹点丢/错位了：%r（几何里前几个是 %r）" % (p, one["first"])
    two = got["geo"]["two"]
    assert two["lines"] == 2, two
    assert two["n_vert"] > one["n_vert"], (two["n_vert"], one["n_vert"])


def test_fit_distance_frames_the_data_whatever_the_shape(tmp_path):
    """取景距离必须把整条轨迹框进视野，且不随"有没有 z 分量"崩掉。"""
    got = _probe(tmp_path, {"fit": [
        {"name": "coplanar", "series": [{"key": "a", "points": COPLANAR}], "az": 0.785,
         "el": 0.436, "aspect": 1.8},
        {"name": "threed", "series": [{"key": "a", "points": BEARING45}], "az": 0.785,
         "el": 0.436, "aspect": 1.8},
        {"name": "flat", "series": [{"key": "a", "points": FLAT}], "az": 0.785,
         "el": 0.436, "aspect": 1.8},
    ]})
    for name, d in got["fit"].items():
        assert isinstance(d, float) and d > 0, (name, d)
        assert d < 1e9, (name, d)                       # 不许爆成无限远（那等于画不出来）
    assert got["fit"]["flat"] > 0
    print("[traj3d] 取景距离：coplanar=%.0f threed=%.0f flat=%.0f"
          % (got["fit"]["coplanar"], got["fit"]["threed"], got["fit"]["flat"]))


def test_traj3d_source_has_no_third_party_and_no_network():
    """手写 WebGL2：零第三方、零网络、零存储、零硬编码域名（离线免安装是底线）。"""
    src = JS.read_text(encoding="utf-8")
    for bad in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage",
                "three.js", "three.min", "cdn", "unpkg"):
        assert bad not in src, "traj3d.js 里出现了 %s" % bad
    assert ("http://" not in src) and ("https://" not in src), "traj3d.js 里有硬编码 URL"
    assert "getContext(" + chr(34) + "webgl2" + chr(34) in src, "不是手写 WebGL2"
    for need in ("mount", "available", "setSeries", "clear", "reset", "stats"):
        assert need in src, "门面少了 %s" % need


# ------------------------------------------------------------ 颜色区分 / 命中标签 / 悬停拾取

def test_palette_gives_every_trajectory_a_distinct_colour(tmp_path):
    """**颜色区分**（用户 2026-10-24 口径）：同池 11 枚必须 11 个不同颜色。

    目录 style 只有红/绿/蓝灰三个色相，早期实现是"同色相混深浅" ⇒ 11 枚挤在一起分不开。
    现在改成色相等间隔旋转：亮/饱和度仍取目录基色，所以没有引入新色值字面量。
    """
    got = _probe(tmp_path, {"palette": [
        {"name": "eleven", "base": "#D32F2F", "n": 11},
        {"name": "two", "base": "#D32F2F", "n": 2},
    ]})
    eleven = got["palette"][0]
    assert eleven["distinct"] == 11, eleven["colors"]
    # 相邻两条不能几乎同色：粗判一下首字符不同（真判据是 distinct==11）
    assert len(set(c.lower() for c in eleven["colors"])) == 11, eleven["colors"]
    assert got["palette"][1]["distinct"] == 2


def test_pick_math_hits_the_line_and_misses_off_it(tmp_path):
    """**悬停拾取**的数学：压在线上距离≈0，偏开就够不着（阈值 10 CSS px 在 mount 里）。

    这条挡的是"窗格永远不出现"或"鼠标在空白处也弹窗格"两种反向 bug。
    """
    got = _probe(tmp_path, {"proj": [
        {"name": "mid", "points": [[0, 10000, 0], [18000, 12700, 0]], "az": 0.785, "el": 0.436,
         "dist": 120000, "cx": 18000, "cy": 11000, "cz": 0, "aspect": 1.6, "W": 1200, "H": 500,
         "away": 200},
    ]})
    m = got["proj"]["mid"]
    assert m["on"] < 1e-6, ("压在线段中点上的距离该是 0", m)
    assert abs(m["tmid"] - 0.5) < 1e-6, m
    assert m["off"] > 100, ("偏开 200px 就不该命中", m)
    # 投影结果必须是有限数（相机在物体后面时会返回 null，这里不该出现）
    assert all(p is not None for p in m["pts"]), m["pts"]


def test_hit_labels_and_tooltip_wiring_exist():
    """**命中时间标签 + 悬停信息窗格**的接线必须在（DOM 层，不是 WebGL 里画文字）。"""
    src = JS.read_text(encoding="utf-8")
    app = (ROOT / "src" / "missile_sim" / "webui_static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "missile_sim" / "webui_static" / "app.css").read_text(encoding="utf-8")
    # 三维层：覆盖层 + 标签 + 窗格，且覆盖层不吃鼠标事件（否则挡住拖拽与悬停）
    for need in ("traj3d-overlay", "traj3d-hit", "traj3d-tip", "pointer-events:none"):
        assert need in css, "app.css 少了 %s" % need
    assert "traj3d-overlay" in src and "traj3d-hit" in src and "traj3d-tip" in src
    assert "pickAt(" in src and "segDist(" in src and "projectPoint(" in src
    # 壳把命中时间/高度/已飞距离带给三维层（后端 case 里已有，不许前端重算）
    for need in ("tHit", "maxAlt", "distFlown"):
        assert need in app, "app.js 没把 %s 传给轨迹层" % need
    assert "c.t_hit" in app and "c.max_alt_m" in app and "c.dist_flown_m" in app
    # 标签文字要带秒（不是裸数字）
    assert 'toFixed(2) + " s"' in src, "命中标签没带单位"

# ------------------------------------------------------------ 播放器（2026-10-24）

def test_player_geometry_carries_normalized_time(tmp_path):
    """**播放器的数据前提**：轨迹顶点要带归一化时间 prog∈[0,1]，网格/坐标轴/投影给 -1。

    prog 是"这一帧该不该画"的唯一依据（着色器里 discard）；给错了整条线要么一直不出现、
    要么一开始就全画出来 —— 而画面看起来"只是没动"，最难查。
    """
    got = _probe(tmp_path, {"geo": [
        {"name": "timed", "series": [{"key": "a", "color": "#d32f2f", "points": COPLANAR,
                                      "ts": [0, 10, 20, 45]}]},
    ]})
    g = got["geo"]["timed"]
    # 顶点顺序是「网格 → 坐标轴 → 轨迹线 → 地面投影」，所以按"参与播放的那些"取：
    timed = [x for x in g["prog"] if x >= 0]
    # 轨迹 4 点、ts=[0,10,20,45] ⇒ prog 应是 0, 10/45, 20/45, 1
    assert len(timed) == 4, ("参与播放的顶点数该等于轨迹点数（投影不参与）", timed)
    assert abs(timed[0]) < 1e-9, timed
    assert abs(timed[-1] - 1.0) < 1e-9, timed
    assert timed == sorted(timed), ("时间必须单调", timed)
    assert abs(timed[1] - 10 / 45) < 1e-6 and abs(timed[2] - 20 / 45) < 1e-6, timed
    # 网格与坐标轴必须 -1（永远不参与播放）
    assert any(x < 0 for x in g["prog"]), "网格/坐标轴不该参与播放"


def test_player_reaches_last_hit_at_full_progress():
    """**"播到最后一枚命中"的判据**：时长 = max(t_hit)，满进度时每一条都到齐。

    这条挡的是"按点序播"那种实现：快慢不同的弹会一起结束，看不出谁先到。
    """
    src = JS.read_text(encoding="utf-8")
    # 时长取所有 tHit 的最大值（不是第一条、不是点数）
    i = src.index("function duration()")
    body = src[i:i + 400]
    assert "s2.tHit" in body and "Math" not in body.split("return")[0].split("s2.tHit")[0], body
    assert "d = +s2.tHit" in body or "+s2.tHit > d" in body, body
    # 满进度分支必须把所有弹画完（setProgress(1) + 标签全部显示）
    assert "api.setProgress(1)" in src, "播到末尾没有强制满进度"
    assert "p >= 0.999" in src, "标签/进度判断没有到末尾的容差"


def test_player_ui_is_wired_and_not_fake():
    """播放器 UI 的三个件（播放/滑块/时钟）都在，且**每帧回调**接上了。

    ⚠ 2026-10-24 真机抓到的 bug：播放只推了三维层、没刷时钟与滑块 ⇒
    按钮写着「暂停」、画面在动、读数却停在 0.5 s。这条就是防它。
    """
    app = (ROOT / "src" / "missile_sim" / "webui_static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "missile_sim" / "webui_static" / "app.css").read_text(encoding="utf-8")
    src = JS.read_text(encoding="utf-8")
    for need in ("traj3d-player", "traj3d-play", "traj3d-seek", "traj3d-clock"):
        assert need in css, "app.css 少了 %s" % need
    for need in ("traj3d-play", "traj3d-seek", "traj3d-clock"):
        assert need in app, "app.js 没建 %s" % need
    assert "onTick" in src and "onTick" in app, "每帧回调没接（时钟会停在原地）"
    assert "view.onTick(function (p) { syncClock(p); })" in app, "回调没接到时钟"
    assert "view.setProgress(p)" in app and "view.play(" in app


# ------------------------------------------------------------ 跳到结束 + 遥测窗格（2026-10-24）

def test_jump_to_end_button_exists_and_skips_stepping():
    """「跳到结束」是**一步到 100%**，不是逐帧步进（用户原话：「那不是步进，是直接到结束」）。

    这条挡两种写法跑偏：① 做成 +/- 步进按钮；② 只改滑块不推三维层（点了没反应）。
    """
    app = (ROOT / "src" / "missile_sim" / "webui_static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "missile_sim" / "webui_static" / "app.css").read_text(encoding="utf-8")
    assert "traj3d-jump" in app and "traj3d-jump" in css, "缺「跳到结束」按钮"
    assert "跳到结束" in app, "按钮文案不对"
    i = app.index("traj3d-jump")
    seg = app[i:i + 900]
    assert "view.setProgress(1)" in seg, "点了没有把进度推到 100%"
    assert "view.pause()" in seg, "跳结束前该先停播（否则会和播放抢进度）"
    # 不许出现步进按钮
    for bad in ("traj3d-step", "traj3d-prev", "traj3d-next", "上一帧", "下一帧"):
        assert bad not in app and bad not in css, "用户要的是跳到结束，不是逐帧步进：%s" % bad


def test_telemetry_panel_is_time_driven_and_uses_backend_columns():
    """遥测窗格：**跟着播放时间走**（不是跟鼠标），数值按**列名**从后端点列取。

    ⚠ 两条都是真踩过的：① 窗格若挂到鼠标上，播放时它不动；
      ② 若按写死的下标取列，后端一加列就整排错位，而画面看起来完全正常。
    """
    app = (ROOT / "src" / "missile_sim" / "webui_static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "missile_sim" / "webui_static" / "app.css").read_text(encoding="utf-8")
    assert "traj3d-tele" in css and "traj3d-tele" in app, "缺遥测窗格"
    # 时间驱动：syncClock 里要调 telePanel（而不是 pointermove 里）
    i = app.index("function syncClock(")
    seg = app[i:i + 600]
    assert "telePanel(series" in seg, "窗格没跟播放时间联动"
    # 按列名取，不写死下标
    assert 'cols.indexOf(name)' in app or "indexOf(name)" in app, "取列没按列名（写死下标会错位）"
    for need in ('col("mach")', 'col("n_g")', 'col("mass")', 'col("aoa_deg")',
                 'col("range")', 'col("acc")'):
        assert need in app, "遥测缺列 %s" % need
    # 窗格里要显示这几个中文项（用户对着参考图点的名）
    for label in ("速度：", "马赫：", "高度：", "过载：", "加速度：", "质量：", "攻角：", "剩余距离："):
        assert label in app, "窗格少了「%s」" % label

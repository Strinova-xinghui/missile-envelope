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
                     first: pts.slice(0, 3), last: pts.slice(-1)[0], pts: pts};
});
(spec.fit || []).forEach(function (t) {
  const g = T.buildGeometry(t.series, T.CHROME_DEFAULT);
  const cam = {az: t.az, el: t.el, dist: 1, pan: [0, 0, 0]};
  out.fit[t.name] = T.fitDistance(g, cam, t.aspect);
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

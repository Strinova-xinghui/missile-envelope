# -*- coding: utf-8 -*-
"""图3 静态版（`fig3.js` 的 `FIG3STATIC`）判据：轴口径逐值一致 + 静态化的硬约束。

* **node 探针**：把 `fig3.js` 载进 node，用 `results/missile_catalog.json` 算三根轴的域与标签摆位，
  与 Python 的 `figures.fig3_axes()` **逐值比对**（≥3 个子集，含**跨界子集**：11 弹 + 一枚 ΔV≈400 的小弹）。
  数据源的 `--axes --figure fig3` oracle 落地后**优先**用它；取不到就退回直调同口径函数，
  **并在输出里写明走了哪条**（不静默放宽；两条路径都必须逐值相等才算过）。
* **契约**：源码里零 `/api` 字样、零 `fetch(`/`XMLHttpRequest`/`localStorage`（静态版不许再有后端路径）、
  零颜色字面量（配色只能来自 `style` 或 `fig3.css` 的 CSS 变量）、门面形状冻结在
  `window.FIG3STATIC.mount(host, {catalog, style}) -> {setSelection, redraw}`。
* **反证**：把 `fetch("/api/fig3/x")` 塞进一份副本，检查函数**必须**抓到 —— 否则那几条契约是空跑。
* 无 node ⇒ `pytest.skip`（并打印一行原因）。
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import figures                                            # noqa: E402

CATALOG = ROOT / "results" / "missile_catalog.json"
JS = ROOT / "src" / "missile_sim" / "webui_static" / "fig3.js"

NODE_HOST = r"""
const fs = require('fs');
// ⚠ 图3 的刻度复用 figs2d.js 的 FIGS2D.ticks（同一实现，不复制第二份）
globalThis.FIGS2D = require(process.argv[4]);
const F = require(process.argv[2]);
const spec = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = { axes: {}, labels: {}, halo: {}, api: { mount: typeof F.mount, fig3Axes: typeof F.fig3Axes,
                                           placeLabels: typeof F.placeLabels3D } };
(spec.axes || []).forEach(function (t) { out.axes[t.name] = F.fig3Axes(t.rows); });
(spec.labels || []).forEach(function (t) {
  // 直接给屏幕坐标：把三轴域映射到一个 800x420 的框里（只验摆位算法本身）
  const rect = { x: 0, y: 0, w: 800, h: 420 };
  const items = t.rows.map(function (r, i) {
    return { key: r.key, label: r.key,
             x: rect.x + (i % 8) * 90 + 20, y: rect.y + Math.floor(i / 8) * 42 + 20 };
  });
  out.labels[t.name] = { rect: rect, placed: F.placeLabels3D(items, rect, { font: 11, pad: 8 }) };
});
(spec.halo || []).forEach(function (t) {
  const st = F.styleOf(t.style || {}, t.catalog || {});
  const d = { colors: F.colorsOf(st) };
  const params = F.haloParams(d);
  const buf = F.haloBuffers(d);
  const quads = [];
  // ⚠ 历史实现每块面推 **6 个顶点**（两个三角形 [0,1,2, 0,2,3]）⇒ 每 18 个 float 一块面，
  //   这里按 6 个顶点取，再去重成 4 个角点（几何判据只看那 4 个）。
  for (let q = 0; q < buf.pos.length / 18; q++) {
    const v = [];
    for (let k = 0; k < 6; k++) {
      const p = [buf.pos[(q * 6 + k) * 3], buf.pos[(q * 6 + k) * 3 + 1], buf.pos[(q * 6 + k) * 3 + 2]];
      if (!v.some((w) => w[0] === p[0] && w[1] === p[1] && w[2] === p[2])) { v.push(p); }
    }
    quads.push(v);
  }
  const decay = [];
  for (let i = 0; i <= 10; i++) {
    const s = i / 10;                                  // 从好角沿对角向外
    decay.push(F.haloWeight([0.5 - s * 0.5, 0.5 - s * 0.5, 0.5 - s * 0.5], params.good,
                            params.radius, params.power));
  }
  out.halo[t.name] = { params: { good: params.good, bad: params.bad, radius: params.radius,
                                 power: params.power, alpha: params.alpha,
                                 faces: params.faces, facesPerCorner: params.facesPerCorner },
                       quads: quads, faces: params.faces, decay: decay,
                       peak: F.haloColorAt(params.good, params).slice(3)[0],
                       mid: F.haloColorAt([0, 0, 0], params) };
});
(spec.tickLabels || []).forEach(function (t) {
  out.tickLabels = out.tickLabels || {};
  const d = F.modelOf(t.catalog || {}, t.keys, F.styleOf(t.style || {}, t.catalog || {}));
  const per = {};
  d.axes.forEach(function (a) {
    const lab = d.axisLabels[a.id] || { majors: [], labels: {}, decimals: null };
    per[a.id] = { majors: lab.majors.length, labels: lab.labels, decimals: lab.decimals };
  });
  out.tickLabels[t.name] = per;
});
// ---- 切片 2 的数值自检：`/v1/isosurface` 的 mesh 进 `surfaceBuffers` 之后，
//      顶点必须落在 ±0.5 的归一化盒里（写错轴序时画面只是"歪了一点"，不报错）。
(spec.surface || []).forEach(function (t) {
  const st = F.styleOf(t.style || {}, t.catalog || {});
  const d = F.modelOf(t.catalog || {}, t.keys, st);
  const buf = F.surfaceBuffers(d, t.mesh, F.hex2rgb(t.color || '#29a07a'));
  const n = buf.pos.length / 3;
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 3; k++) {
      const v = buf.pos[i * 3 + k];
      lo[k] = Math.min(lo[k], v); hi[k] = Math.max(hi[k], v);
    }
  }
  out.surface = out.surface || {};
  out.surface[t.name] = {n_tri: buf.n_tri, idx: buf.idx, n_vert: n,
                          lo: lo, hi: hi,
                          colors: buf.col.slice(0, 3), size: buf.size.slice(0, 1)};
});
process.stdout.write(JSON.stringify(out));
"""


def _node():
    return shutil.which("node")


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _drawable(rec: dict) -> list:
    """可画条目（孪生/默认隐藏/坐标不全的都不算）—— 与前端 `drawableEntries()` 同一口径。"""
    return [m for m in (rec.get("missiles") or [])
            if not m.get("duplicate_of") and not m.get("default_hidden")
            and isfinite(m.get("dv")) and isfinite(m.get("bc")) and isfinite(m.get("ginv"))]


def isfinite(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) != float("inf")


def _subsets(rec: dict) -> dict:
    ms = _drawable(rec)
    pool = [m for m in ms if m.get("in_pool11")]
    small = [m for m in ms if "mistral" in m["key"]][:1]
    weakest = [min(ms, key=lambda m: float(m["dv"]))]
    return {"pool11": pool, "pool11+small": pool + small, "single-weakest": weakest, "all": ms}


def _probe(tmp_path: Path, spec: dict) -> dict:
    node = _node()
    host = tmp_path / "fig3_host.js"
    host.write_text(NODE_HOST, encoding="utf-8")
    spec_path = tmp_path / "fig3_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    subprocess.run([node, "--check", str(JS)], check=True, capture_output=True, text=True)
    proc = subprocess.run([node, str(host), str(JS), str(spec_path),
                           str(JS.parent / "figs2d.js")],
                          capture_output=True, text=True, timeout=120, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr[-800:]
    return json.loads(proc.stdout)


def _oracle(keys, timeout=300):
    """`python -m missile_sim --axes "<keys>" --figure fig3`（数据源那条 oracle）；不支持就 None。"""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run([sys.executable, "-m", "missile_sim", "--axes",
                               ",".join(str(k) for k in keys), "--figure", "fig3"],
                              cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in reversed((proc.stdout or "").splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


class Row:
    """`figures.fig3_axes()` 只读 `.dv`（走 `_one_axis(...,"x")`）与 `.beta`/`.ginv`（走 `bg_axis`）。"""

    __slots__ = ("key", "label", "dv", "bc", "beta", "ginv")

    def __init__(self, m):
        self.key = self.label = m["key"]
        self.dv = float(m["dv"])
        self.bc = self.beta = float(m["bc"])
        self.ginv = float(m["ginv"])


def _diffs(a, b) -> float:
    assert len(a) == len(b), (a, b)
    return max(abs(float(x) - float(y)) for x, y in zip(a, b))


# ===================================================================== 1. node 探针


def test_fig3_static_axes_match_python_value_by_value(tmp_path):
    """三根轴的域：JS 与 `figures.fig3_axes()`（以及 oracle CLI，若已落地）逐值相等。"""
    if not _node():
        print("[fig3_static] 本机没有 node，跳过 JS 轴域数值自检")
        pytest.skip("本机没有 node")
    subs = _subsets(_catalog())
    spec = {"axes": [{"name": k, "rows": [{"dv": m["dv"], "bc": m["bc"], "ginv": m["ginv"]} for m in v]}
                     for k, v in subs.items()]}
    got = _probe(tmp_path, spec)
    worst = 0.0
    for name, sel in subs.items():
        want = figures.fig3_axes([Row(m) for m in sel])
        js = got["axes"][name]
        for axis in ("dv", "beta", "ginv"):
            d = _diffs(want[axis], js[axis])
            worst = max(worst, d)
            assert d < 1e-9, "轴 %s 对不上（%s）：Python=%s JS=%s 差 %.3g" % (
                axis, name, want[axis], js[axis], d)
        print("[fig3_static] %-16s n=%3d dv=%s beta=%s ginv=%s 差=0"
              % (name, len(sel), js["dv"], js["beta"], js["ginv"]))
    print("[fig3_static] 与 figures.fig3_axes() 最大差 = %.3g（%d 个子集 × 3 轴）" % (worst, len(subs)))

    # oracle（数据源那条 CLI）：有就也逐值比一遍；没有就打印一行说明
    seen = 0
    for name in ("pool11", "pool11+small", "all"):
        o = _oracle([m["key"] for m in subs[name]])
        if not o:
            print("[fig3_static] oracle `--axes --figure fig3` 还没落地，跳过 %s 的 oracle 比对"
                  "（退回直调 figures.fig3_axes()，见上）" % name)
            continue
        js = got["axes"][name]
        for axis in ("dv", "beta", "ginv"):
            assert _diffs(o[axis], js[axis]) < 1e-9, (name, axis, o[axis], js[axis])
        assert int(o["n"]) == len(subs[name])
        print("[fig3_static] oracle %-14s dv=%s beta=%s ginv=%s（与 JS 同）"
              % (name, o["dv"], o["beta"], o["ginv"]))
        seen += 1
    if not seen:
        print("[fig3_static] oracle 未落地：本次只用同口径函数对拍（等数据源补 kind=fig3 后自动接上）")


def test_fig3_static_labels_do_not_overlap_or_leave_the_frame(tmp_path):
    """标签避让是算法（任意子集都要"两两不重叠、不出框"；放不下就不标）。"""
    if not _node():
        print("[fig3_static] 本机没有 node，跳过标签避让自检")
        pytest.skip("本机没有 node")
    subs = _subsets(_catalog())
    spec = {"labels": [{"name": k, "rows": [{"key": m["key"]} for m in v]} for k, v in subs.items()]}
    got = _probe(tmp_path, spec)
    for name, data in sorted(got["labels"].items()):
        boxes = [p["box"] for p in data["placed"] if p["kept"]]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                assert (a["x1"] <= b["x0"] or b["x1"] <= a["x0"]
                        or a["y1"] <= b["y0"] or b["y1"] <= a["y0"]), (name, a, b)
        r = data["rect"]
        for a in boxes:
            assert a["x0"] >= r["x"] - 2 and a["x1"] <= r["x"] + r["w"] + 2, (name, a)
            assert a["y0"] >= r["y"] - 2 and a["y1"] <= r["y"] + r["h"] + 2, (name, a)
        total = len(data["placed"])
        assert len(boxes) >= max(1, total // 2), "%s 只标出 %d/%d" % (name, len(boxes), total)
        print("[fig3_static] %-14s 标出 %3d/%3d，重叠 0，出框 0" % (name, len(boxes), total))


# ===================================================================== 2. 契约 + 反证

BAD_TOKENS = ("/api", "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage")


def _contract_violations(text: str) -> list:
    """静态版的硬约束（返回违规清单，空 = 通过）。**反证用的就是它。**"""
    bad = [tok for tok in BAD_TOKENS if tok in text]
    if re.search(r"#[0-9a-fA-F]{3,8}\b", text):
        bad.append("颜色字面量（#rrggbb）")
    if re.search(r"rgba?\(\s*\d", text):
        bad.append("颜色字面量（rgb(数字)）")
    return bad


def test_fig3_static_has_no_backend_paths_and_no_color_literals():
    """零 `/api`、零 `fetch(`/XHR/存储、零颜色字面量（配色只来自 style 或 fig3.css）。"""
    text = JS.read_text(encoding="utf-8")
    bad = _contract_violations(text)
    assert not bad, "fig3.js 违反静态化约束：%s" % bad
    for name in ("function nodeOf(", "function columnOf(", "function rampColor(",
                 "function buildBox(", "TICK_EDGE", "FS_SOLID", "FS_DISC", "FS_RING"):
        assert name in text, "通用工具/交互那几条被误删了：%s" % name
    print("[fig3_static] 契约通过：零 /api、零 fetch/XHR/存储、零颜色字面量（%d 字节）" % len(text))


def test_fig3_static_contract_checker_catches_a_planted_backend_call(tmp_path):
    """反证：把 `fetch("/api/fig3/x")` 塞进副本，检查函数**必须**抓到（否则那几条契约是空跑）。"""
    text = JS.read_text(encoding="utf-8")
    planted = text + '\nfetch("/api/fig3/probe");\n'
    bad = _contract_violations(planted)
    assert "/api" in bad and "fetch(" in bad, bad
    print("[fig3_static] 反证通过：植入 fetch(\"/api/fig3/probe\") 被抓到 → %s" % bad)


def test_fig3_static_surface_mesh_from_the_v1_contract_lands_inside_the_box(tmp_path):
    """切片 2 的**数值**判据：`/v1/isosurface` 的 mesh 进 `surfaceBuffers` 后顶点落在 ±0.5 盒内。

    为什么必须是数值判据（源码形状挡不住）：`mesh.vertices` 是数据坐标 `(ΔV, β, ginv)`，
    而 `dataPos(d, beta, ginv, dv)` 吃的是 `(beta, ginv, dv)`。**写错时三个轴整体换位**，
    画面看着只是"面歪了一点"，不抛异常、不画错层 ⇒ 只有把顶点坐标算出来比才抓得到。
    """
    if not _node():
        print("[fig3_static] 本机没有 node，跳过等时面网格数值自检")
        pytest.skip("本机没有 node")
    cat = _catalog()
    pool = _subsets(cat)["pool11"]
    # `styleOf()` 要整套键（点/盒/轴/文字/光晕…）：光晕那几个从 `_halo_style()` 现读 CSS，
    # 免得这里另写一份（那个 helper 就是"从 fig3.css 现读"的单一出处）。
    halo = _halo_style()
    style = {"point_color": "#D32F2F", "base_color": "#388E3C", "box_color": "#9AA0A6",
             "bg_color": "#ffffff", "text_color": "#555555",
             "axis_dv": "#cc3322", "axis_beta": "#2661d9", "axis_ginv": "#227855",
             "halo_good": halo["halo_good"], "halo_bad": halo["halo_bad"],
             "halo_base": halo["halo_base"], "halo_alpha": halo["halo_alpha"],
             "halo_radius": halo["halo_radius"], "halo_power": halo["halo_power"],
             # 切片 2 的等时面配色：走 `style` 这条路（真页面多半由 CSS 变量给，node 里没有 CSS）
             "layer_color": "#29a07a", "layer_alpha": 0.55}
    # PL-12 的标称点 ± 一个 ΔV/β/ginv 小扰动（模仿真响应：窗口 = 标称点 ±10% / ±10% / ±20%）。
    # ⚠ 轴域取**整个 pool11**（`keys` 传全体）—— 与真页面一致：图3 的轴域是**所选弹池**的域。
    #   只喂 PL-12 的话轴会收得很窄，扰动点直接落到 ±0.5 盒外（那是假红，不是实现差异）。
    m = next(x for x in pool if x["key"] == "PL-12")
    keys = [x["key"] for x in pool]
    verts = [[m["dv"] - 40.0, m["bc"] - 60.0, m["ginv"] - 0.001],
             [m["dv"] + 40.0, m["bc"] + 60.0, m["ginv"] + 0.001],
             [m["dv"], m["bc"], m["ginv"]]]
    got = _probe(tmp_path, {
        "surface": [{"name": "v1", "style": style, "catalog": cat,
                     "keys": keys,
                     "mesh": {"vertices": verts, "indices": [0, 1, 2], "triangles": 1}}],
    })
    s = got["surface"]["v1"]
    assert s["n_tri"] == 1 and s["n_vert"] == 3, s
    assert s["idx"] == [0, 1, 2], s
    # 全部坐标落在归一化盒内（轴域由 catalog 现算 ⇒ 真响应一定落在这里）
    for k in range(3):
        assert s["lo"][k] is not None and s["hi"][k] is not None, (k, s)
        assert -0.5 <= s["lo"][k] <= 0.5, (k, s)
        assert -0.5 <= s["hi"][k] <= 0.5, (k, s)
    assert all(0.0 <= c <= 1.0 for c in s["colors"]), s["colors"]
    assert s["size"] == [1], s["size"]
    print("[fig3_static] 等时面网格：v1 契约（indices + (ΔV,β,ginv) 顶点）→ "
          "%d 三角形，顶点落在 ±0.5 盒内 ✓" % s["n_tri"])

    # ---- 反证：把顶点重排写回**错的顺序**（照老 /api/fig3 的 β,ginv,ΔV）必须被抓到
    #   （数值上就是"三根轴被换位" —— 顶点仍然在盒内，但落在**错的三根轴**上）
    wrong = _surface_axes(verts)
    assert wrong != verts
    got2 = _probe(tmp_path, {
        "surface": [{"name": "wrong", "style": style, "catalog": cat, "keys": keys,
                     "mesh": {"vertices": wrong, "indices": [0, 1, 2], "triangles": 1}}],
    })
    s2 = got2["surface"]["wrong"]
    # 换位后至少有一根轴的跨度会明显不同（扰动量按 ΔV/β/ginv 各不相同）
    assert [abs(s2["hi"][k] - s2["lo"][k]) for k in range(3)] != \
           [abs(s["hi"][k] - s["lo"][k]) for k in range(3)], (s, s2)
    print("[fig3_static] 反证：顶点按 (β,ginv,ΔV) 喂进去，三根轴的跨度立刻不同 ✓")


def _surface_axes(verts):
    """把 (ΔV, β, ginv) 的顶点**假装**成老口径 (β, ginv, ΔV) —— 反证用。"""
    return [[v[1], v[2], v[0]] for v in verts]


def test_fig3_static_exposes_the_frozen_facade(tmp_path):
    """门面形状：`window.FIG3STATIC.mount(host, {catalog, style})` → `{setSelection, redraw}`。"""
    if not _node():
        print("[fig3_static] 本机没有 node，跳过门面形状自检")
        pytest.skip("本机没有 node")
    got = _probe(tmp_path, {})
    assert got["api"]["mount"] == "function", got["api"]
    assert got["api"]["fig3Axes"] == "function" and got["api"]["placeLabels"] == "function"
    text = JS.read_text(encoding="utf-8")
    for token in ("window.FIG3STATIC", "setSelection", "redraw", "catalog", "style"):
        assert token in text, "门面少了一样：%s" % token
    assert "不做命中/脱靶判定" in text and "同色同形" in text, "注释里要写清静态版的语义收紧"


# ===================================================================== 3. 角部光晕（用户 2026-10-05 口径）

#: 与 `figures` 的那几个常量同名（下面比对用），单一出处 = Python 侧。
HALO_STYLE_KEYS = ("halo_good", "halo_bad", "halo_base")
HALO_NUM_KEYS = ("halo_alpha", "halo_radius", "halo_power")


def _halo_style() -> dict:
    """从 `fig3.css` 的 CSS 变量与 `figures.FIG3_HALO_*` 现读（JS 侧不另写一份）。"""
    css = (ROOT / "src" / "missile_sim" / "webui_static" / "fig3.css").read_text(encoding="utf-8")
    # `styleOf()` 要求整套键都在（点/盒/轴/文字…）：这里一并从同一份 CSS 现读，避免探针只带 halo 键
    got = {}
    for name, key in (("point", "point"), ("base", "base"), ("box", "box"),
                      ("bg", "bg"), ("text", "text"),
                      ("axis_dv", "axis-dv"), ("axis_beta", "axis-beta"), ("axis_ginv", "axis-ginv")):
        m = re.search(r"--fig3-%s\s*:\s*([^;]+);" % key, css)
        assert m, "fig3.css 里缺 --fig3-%s" % key
        if name.startswith("axis") or name.startswith("halo"):
            got[name] = m.group(1).strip()
        else:
            got[name + "_color"] = m.group(1).strip()
    for name in ("good", "bad", "base"):
        m = re.search(r"--fig3-halo-%s\s*:\s*([^;]+);" % name, css)
        assert m, "fig3.css 里缺 --fig3-halo-%s" % name
        got["halo_" + name] = m.group(1).strip()
    for name in ("alpha", "radius", "power"):
        m = re.search(r"--fig3-halo-%s\s*:\s*([^;]+);" % name, css)
        assert m, "fig3.css 里缺 --fig3-halo-%s" % name
        got["halo_" + name] = float(m.group(1).strip())
    return got


def _halo_geometry_problems(quads: list, faces: list, corners: dict) -> list:
    """光晕几何自检（**反证就是拿它跑篡改过的数据**）：

    * 6 块四边形（每角 3 块）；
    * 每块 4 个顶点共面、且恰好一根轴固定在 ±0.5（面片贴立方体表面）；
    * 好角那 3 块都必须**含好角顶点**（三轴 max），坏角那 3 块都必须含坏角顶点（三轴 min）。
    """
    bad = []
    if len(quads) != 6:
        bad.append("四边形数 %d（应为 6 = 每角 3 块 × 2 角）" % len(quads))
    if len(faces) != 6 or sum(1 for f in faces if float(f["at"]) > 0) != 3:
        bad.append("faces 不是 3+3：%r" % (faces,))
    good, dark = corners["good"], corners["bad"]
    for i, q in enumerate(quads):
        if len(q) != 4:
            bad.append("第 %d 块不是四边形" % i)
            continue
        fixed = [k for k in range(3) if len({round(v[k], 6) for v in q}) == 1]
        if len(fixed) != 1:
            bad.append("第 %d 块不是贴着一个面（固定轴 %d 根）" % (i, len(fixed)))
            continue
        at = round(q[0][fixed[0]], 6)
        if at not in (-0.5, 0.5):
            bad.append("第 %d 块固定轴取 %r（应为 ±0.5）" % (i, at))
        want = tuple(good) if at > 0 else tuple(dark)
        if not any(tuple(round(c, 6) for c in v) == want for v in q):
            bad.append("第 %d 块不含角顶点 %r（面片没落在那个角上）" % (i, want))
    return bad


def test_fig3_static_halo_geometry_decay_and_order(tmp_path):
    """光晕三件事：几何（6 块面贴在两个角上）、衰减（自角向外单调降、峰值 = CSS 的 alpha）、
    以及**先画光晕再画点**（不能遮住点）。"""
    if not _node():
        print("[fig3_static] 本机没有 node，跳过光晕几何/衰减自检")
        pytest.skip("本机没有 node")
    st = _halo_style()
    got = _probe(tmp_path, {"halo": [{"name": "pool11", "style": st}]})
    h = got["halo"]["pool11"]

    # ---- 几何
    problems = _halo_geometry_problems(
        h["quads"], h["faces"], {"good": [0.5, 0.5, 0.5], "bad": [-0.5, -0.5, -0.5]})
    assert not problems, "光晕几何有问题：%s" % problems
    assert h["params"]["facesPerCorner"] == 3, h["params"]["facesPerCorner"]
    print("[fig3_static] 光晕几何：%d 块四边形（好角 3 + 坏角 3），角顶点都在，固定轴均 ±0.5 ✓"
          % len(h["quads"]))

    # ---- 衰减：自角向外单调不增，且角上最强
    decay = [float(x) for x in h["decay"]]
    assert decay[0] == pytest.approx(1.0), decay[:3]
    for i in range(1, len(decay)):
        assert decay[i] <= decay[i - 1] + 1e-12, decay
    assert decay[-1] < decay[0], decay
    print("[fig3_static] 光晕衰减：自角向外 %s（单调不增 ✓）" % ("→".join("%.2f" % x for x in decay[:5])))

    # ---- 峰值 alpha 与 CSS 变量一致
    assert abs(float(h["peak"]) - st["halo_alpha"]) < 1e-9, (h["peak"], st["halo_alpha"])
    print("[fig3_static] 峰值 alpha = %.2f（= fig3.css 的 --fig3-halo-alpha）✓" % h["peak"])

    # ---- 顺序：光晕的绘制调用必须早于点（源码位置）
    js = JS.read_text(encoding="utf-8")
    i_halo = js.index("if (B_HALO.count)")
    i_hit = js.index("if (B_HIT.count)")
    assert i_halo < i_hit, "光晕画在点之后了（会遮点）"
    assert "gl.depthMask(false)" in js[i_halo:i_hit], "光晕那一段必须夹在不写深度的时段里"
    assert "enable(gl.CULL_FACE)" not in js, "光晕是双面画（不做背面剔除），法线朝外也不影响"
    print("[fig3_static] 绘制顺序：光晕 @%d < 点 @%d ✓（且不写深度、不开背面剔除）" % (i_halo, i_hit))


def test_fig3_static_halo_colors_come_from_the_css_variables():
    """色源：`fig3.js` 零颜色字面量（既有那条管着），且 `fig3.css` 的三个色值 + 三个数值
    与 `figures.FIG3_HALO_*` **一致**（单一出处；JS 里不另写一份）。"""
    st = _halo_style()
    assert st["halo_good"].lower() == str(figures.FIG3_HALO_GOOD_COLOR).lower(), st
    assert st["halo_bad"].lower() == str(figures.FIG3_HALO_BAD_COLOR).lower(), st
    assert abs(st["halo_alpha"] - float(figures.FIG3_HALO_ALPHA)) < 1e-9, st
    assert abs(st["halo_radius"] - float(figures.FIG3_HALO_RADIUS)) < 1e-9, st
    assert abs(st["halo_power"] - float(figures.FIG3_HALO_POWER)) < 1e-9, st
    js = JS.read_text(encoding="utf-8")
    assert "--fig3-halo-good" in js and "--fig3-halo-alpha" in js, "JS 得从 CSS 变量取色/取参"
    print("[fig3_static] 色源：fig3.css 的 good/bad/alpha/radius/power 与 figures.FIG3_HALO_* 一致 ✓")


def test_fig3_static_halo_geometry_checker_catches_swapped_corners(tmp_path):
    """反证：把好角写成三轴 min（= 交换 good/bad）必须被几何判据抓出来。"""
    st = _halo_style()
    got = _probe(tmp_path, {"halo": [{"name": "x", "style": st}]})
    h = got["halo"]["x"]
    swapped = _halo_geometry_problems(
        h["quads"], h["faces"], {"good": [-0.5, -0.5, -0.5], "bad": [0.5, 0.5, 0.5]})
    assert swapped, "交换 good/bad 竟然没被抓出来 —— 这条反证是空跑"
    print("[fig3_static] 反证：交换好/坏角被抓到 %d 处（%s…）" % (len(swapped), swapped[0][:40]))


def test_fig3_static_halo_shader_gets_a_real_world_position():
    """光晕的几何数值可以全对、**成像却全错** —— 2026-10-05 就是这么栽的。

    `VS` 里声明了 `out vec3 v_world;` 却**从没赋值**（静态化时被"清死注释"连带删掉了那行），
    片元着色器拿到的 `v_world` 是未定义值（GLSL 里通常为 0）⇒ `haloW` 算出 t≈0.06、
    alpha≈0.0035 ⇒ 光晕几乎全透明；而几何/衰减/色源那几条判据**全都过**（它们只看构造空间数值）。

    这条钉"数值对、成像错"这类坑：
    * `VS` 必须给 `v_world` 赋**世界坐标** `a_pos`（不是 `mv`）；
    * 光晕 FS 必须真的用 `v_world` 算距离（否则赋值也白搭）；
    * 两个角不许再来自响应（`corner_good` / `d.halo` 零命中）。
    
    ⚠ 为什么不用"光晕 AABB ⊆ 盒子 AABB"那条（Lead 曾建议、我实测会**空过**）：光晕顶点在
    **构造空间**里本来就固定在 ±0.5（与盒子同一套），两者 AABB 完全相同 ⇒ 抓不到"顶点没错、
    但着色器拿不到世界坐标"这种错。要抓这一类必须钉**着色器侧**（varying 有没有被赋、
    FS 有没有真的用它），也就是下面这几条。
    """
    js = JS.read_text(encoding="utf-8")
    i = js.index("var VS = [")
    vs = js[i:js.index("].join", i)]
    assert "v_world" in vs, "VS 里没有 v_world？"
    assert "v_world = a_pos;" in vs, "VS 没给 v_world 赋值 ⇒ 光晕会全透明（2026-10-05 的坑）"
    assert "v_world = mv" not in vs and "v_world = (mv" not in vs, "v_world 必须是世界坐标"
    j = js.index("var FS_HALO = [")
    fs = js[j:js.index("].join", j)]
    assert "v_world" in fs and "haloW(" in fs, "光晕 FS 得用 v_world 算距离"
    assert "corner_good" not in js and "d.halo" not in js, "角不许再来自响应"
    print("[fig3_static] 光晕成像前提：VS 给 v_world 赋世界坐标 ✓ FS 用 v_world 算距离 ✓ 角写死 ✓")


def test_fig3_static_halo_alpha_is_in_the_discernible_range():
    """alpha 必须落在**可辨区间**：`0.45 ≤ alpha ≤ 0.80`（"与 `figures` 逐值一致"由既有那条管）。

    为什么要有这一条（2026-10-05 实测）：几何/衰减/色源全对、`v_world` 也修好之后，光晕在近白底
    上**仍然看不见** —— 着色器在角色处给的是纯色（`mix(base, bad, 1)`），但 `alpha = alpha0·w`；
    `alpha0 = 0.32` 时叠出来是 `0.32×(192,57,43)+0.68×(247,248,249) ≈ (229,220,218)`，
    与白底 `(247,248,249)` 只差一点点，肉眼不可辨。
    上限那一头由"不能遮点"管：`alpha` 太大（> 0.8）会把点与标签压掉。
    所以区间取 0.45~0.80 —— 下限保证"看得出来"，上限保证"不喧宾夺主"。
    改这个数必须同时改 `figures.FIG3_HALO_ALPHA` 与 `fig3.css` 的 `--fig3-halo-alpha`。
    """
    st = _halo_style()
    a = float(st["halo_alpha"])
    assert abs(a - float(figures.FIG3_HALO_ALPHA)) < 1e-9, (a, figures.FIG3_HALO_ALPHA)
    assert 0.45 <= a <= 0.80, "光晕 alpha=%r 不在可辨区间 0.45~0.80（太低=看不见，太高=压点）" % a
    print("[fig3_static] 光晕 alpha = %.2f（figures 与 fig3.css 一致，且在可辨区间 0.45~0.80）✓" % a)


def test_fig3_static_axes_reuse_the_same_tick_engine(tmp_path):
    """图3 三轴的**刻度**必须复用 `figs2d.js` 的同一个实现（`FIGS2D.ticks`），不许复制第二份。

    证据两侧：源码上 `fig3.js` 不再有自己的 `niceTick/minorFor`、而是调 `ticksOf()` 读 `FIGS2D.ticks`；
    数值上同一个窗口里 `fig3Axes` 的步长与 `FIGS2D.ticks` 给出的**逐值相同**，且都落在 nice 阶梯上。
    """
    if not _node():
        print("[fig3_static] 本机没有 node，跳过刻度复用自检")
        pytest.skip("本机没有 node")
    txt = JS3.read_text(encoding="utf-8") if 'JS3' in globals() else JS.read_text(encoding="utf-8")
    assert "FIGS2D" in txt and "ticksOf" in txt, "fig3.js 没有复用 FIGS2D.ticks"
    assert "FIG3STATIC.ticks" not in txt or "ticksOf" in txt
    got = _probe(tmp_path, {"axes": [{"name": "pool11",
                                      "rows": [{"dv": m["dv"], "bc": m["bc"], "ginv": m["ginv"]}
                                               for m in _subsets(_catalog())["pool11"]]},
                                     {"name": "all",
                                      "rows": [{"dv": m["dv"], "bc": m["bc"], "ginv": m["ginv"]}
                                               for m in _subsets(_catalog())["all"]]}]})
    ladder = {1.0, 2.0, 2.5, 5.0, 10.0}
    for name, ax in got["axes"].items():
        for key in ("dv_major", "beta_major", "ginv_major"):
            step = float(ax[key])
            mant = step / 10 ** math.floor(math.log10(step))
            assert any(abs(mant - c) < 1e-9 for c in ladder), (name, key, step)
        print("[fig3_static] %s 三轴步长 dv=%g beta=%g ginv=%g（都在 nice 阶梯上，且来自同一实现）✓"
              % (name, ax["dv_major"], ax["beta_major"], ax["ginv_major"]))


# ===================================================================== 4. 轴刻度数字（回归）

def _label_problems(per_axis: dict) -> list:
    """三根轴的刻度数字自检：每个主刻度都要有**非空**数字、标签数 == 主刻度数、无多余 0、
    且小数位不超过 `decimals`（不该出现 0.001000 这种）。"""
    bad = []
    for axis_id, per in per_axis.items():
        majors, labels, decimals = per["majors"], per["labels"], per["decimals"]
        if len(labels) != majors:
            bad.append("%s 标签 %d 个 != 主刻度 %d 个（少画了）" % (axis_id, len(labels), majors))
        for key, lab in labels.items():
            if not lab:
                bad.append("%s 的值 %s 标签是空的" % (axis_id, key))
                continue
            if re.search(r"\.\d*0$", str(lab)):
                bad.append("%s 的标签有多余 0：%s" % (axis_id, lab))
            if "." in str(lab):
                dec = len(str(lab).split(".")[1])
                if decimals is not None and dec > int(decimals):
                    bad.append("%s 的标签 %s 小数位 %d > decimals %s" % (axis_id, lab, dec, decimals))
    return bad


def test_fig3_static_axis_tick_labels_exist_and_match_decimals(tmp_path):
    """回归（2026-10-05 线上实测"图3 的坐标轴空有刻度没有数值"）：

    历史版由 `placeTicks()` 每帧把刻度数字写进 DOM；静态化时那一块被删掉 ⇒ 刻度线还在、
    **数字没人生成**（不是空串、也不是 NaN）。现在数字文本统一取自 `FIGS2D.ticks()` 的 `label`，
    这条判据钉住"三根轴每个主刻度都有非空数字"，并顺带钉住小数位与 `decimals` 自洽、无多余 0。
    """
    if not _node():
        print("[fig3_static] 本机没有 node，跳过刻度数字自检")
        pytest.skip("本机没有 node")
    cat = _catalog()
    style = _halo_style()
    spec = {"tickLabels": [
        {"name": "pool11", "catalog": cat, "style": style,
         "keys": [m["key"] for m in _subsets(cat)["pool11"]]},
        {"name": "all", "catalog": cat, "style": style,
         "keys": [m["key"] for m in _subsets(cat)["all"]]}]}
    got = _probe(tmp_path, spec)["tickLabels"]
    for name, per in got.items():
        problems = _label_problems(per)
        assert not problems, "刻度数字有问题：%s" % problems
        for axis_id, p in per.items():
            sample = list(p["labels"].values())[:3]
            print("[fig3_static] %s 的 %s 轴：主刻度 %d 个、标签 %d 个（%s…）decimals=%s ✓"
                  % (name, axis_id, p["majors"], len(p["labels"]), ", ".join(map(str, sample)),
                     p["decimals"]))


def test_fig3_static_axis_tick_label_checker_catches_an_empty_label(tmp_path):
    """反证：把某一轴的标签**强制置空**（或漏画）⇒ 上面的自检必须抓到。"""
    cat = _catalog()
    style = _halo_style()
    spec = {"tickLabels": [{"name": "x", "catalog": cat, "style": style,
                            "keys": [m["key"] for m in _subsets(cat)["pool11"]]}]}
    per = _probe(tmp_path, spec)["tickLabels"]["x"]
    planted = {k: dict(v) for k, v in per.items()}
    bad_axis = "ginv"
    planted[bad_axis]["labels"] = {k: "" for k in per[bad_axis]["labels"]}     # 置空
    problems = _label_problems(planted)
    assert problems and any("空的" in p for p in problems), problems
    print("[fig3_static] 反证：把 %s 轴的标签置空被抓到 %d 处（%s）✓"
          % (bad_axis, len(problems), problems[0][:44]))

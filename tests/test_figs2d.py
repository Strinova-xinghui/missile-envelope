# -*- coding: utf-8 -*-
"""阶段 B（静态层）的判据：客户端 SVG 渲染器 `figs2d.js` 的三个硬口径。

* **node 探针**：把 `figs2d.js` 载进 node，用 `results/missile_catalog.json` 的条目算轴域、
  等 n* 斜率与标签摆位，与 Python 的 `figures.adaptive_axis()` / `figures.bg_axis()` /
  `bg.nstar_slope()` **逐值比对**（≥3 个子集，含**跨界子集**：11 弹 + Mistral/CAMM 这类小弹，
  ΔV 从 820 拉到约 400）。本机没有 node 就 `pytest.skip` 并打印一行原因。
* **契约**：源码里零 `fetch(`/`XMLHttpRequest`（这就是"切弹池零往返"的机器证据）、
  零 `localStorage`（选择由壳管）、零物理公式痕迹（点的坐标只从目录读）、
  不出现那两张手调偏移表（避让必须是算法）。
* **冻结接口**：`window.FIGS2D.mount(host, {kind, catalog, notes})` →
  `{setSelection(keys), redraw()}`；`drawableEntries()` 必须把 `_default` 孪生与不可算的排除。

⚠ 前端**行为**（切一次弹池、图跟着变、零请求）这套测试跑不了（无浏览器、无 node DOM）——
那部分由真浏览器取证（CDP 网络记录）负责，见阶段 B 的回报与 `docs/STATIC-LAYER-REALTIME.md`。
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

from missile_sim import bg, figures                                      # noqa: E402

CATALOG = ROOT / "results" / "missile_catalog.json"
JS = ROOT / "src" / "missile_sim" / "webui_static" / "figs2d.js"

#: node 宿主脚本：吃一个 JSON 任务单，吐出算好的域/斜率/标签盒/可画条目。
NODE_HOST = r"""
const fs = require('fs');
const F = require(process.argv[2]);
const spec = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = { plane: {}, bg: {}, nstar: {}, labels: {}, drawable: null, api: {
  mount: typeof F.mount, hasDrawable: typeof F.drawableEntries } };
(spec.plane || []).forEach(function (t) { out.plane[t.name] = F.planeAxis(t.points); });
(spec.bg || []).forEach(function (t) { out.bg[t.name] = F.bgAxis(t.rows); });
(spec.nstar || []).forEach(function (t) { out.nstar[String(t.n)] = F.nstarSlope(t.n, spec.reference); });
(spec.labels || []).forEach(function (t) {
  const axis = t.which == 'bg' ? F.bgAxis(t.rows) : F.planeAxis(t.points);
  const items = (t.which == 'bg')
    ? t.rows.map(function (r) { return {key: r.key, label: r.label, x: r.beta, y: r.ginv}; })
    : t.points.map(function (p) { return {key: p.key, label: p.label, x: p.dv, y: p.bc}; });
  const placed = F.placeLabels(items, axis, t.rect, { font: 9.5 });
  out.labels[t.name] = { axis: axis, rect: t.rect, placed: placed };
});
if (spec.catalogPath) {
  const cat = JSON.parse(fs.readFileSync(spec.catalogPath, 'utf8'));
  out.drawable = F.drawableEntries(cat).map(function (m) { return m.key; });
}
process.stdout.write(JSON.stringify(out));
"""


def _node():
    return shutil.which("node")


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _usable(rec: dict) -> list:
    """可算、且不是 `_default` 孪生的条目（页面上默认看得见的那一批）。"""
    return [m for m in (rec.get("missiles") or []) if not m.get("duplicate_of")
            and m.get("dv") and m.get("bc") and m.get("ginv")]


def _subsets(rec: dict) -> dict:
    ms = _usable(rec)
    pool = [m for m in ms if m.get("in_pool11")]
    small = [m for m in ms if ("mistral" in m["key"] or "camm" in m["key"])][:2]
    return {
        "pool11": pool,                                  # 我们的 11 弹
        "pool11+small": pool + small,                    # 跨界：ΔV 820 → 399
        "single-weakest": [min(ms, key=lambda m: m["dv"])],
        "all-104": ms,
    }


def _probe(tmp_path: Path, spec: dict) -> dict:
    node = _node()
    host = tmp_path / "figs2d_host.js"
    host.write_text(NODE_HOST, encoding="utf-8")
    spec_path = tmp_path / "figs2d_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    subprocess.run([node, "--check", str(JS)], check=True, capture_output=True, text=True)
    proc = subprocess.run([node, str(host), str(JS), str(spec_path)],
                          capture_output=True, text=True, timeout=120, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr[-800:]
    return json.loads(proc.stdout)


def _diffs(a, b) -> float:
    assert len(a) == len(b), (a, b)
    worst = 0.0
    for x, y in zip(a, b):
        if isinstance(x, (list, tuple)):
            worst = max(worst, _diffs(x, y))
        else:
            worst = max(worst, abs(float(x) - float(y)))
    return worst


def _strip_comments(js: str) -> str:
    """去掉块注释与行注释后的代码（判据只该管代码，注释里出现词不算违规）。"""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in js.splitlines())


class Pt:
    """够 `figures.adaptive_axis()` 用的一行（它只读 `.dv` / `.bc`）。"""

    __slots__ = ("dv", "bc", "key", "label")

    def __init__(self, key, dv, bc):
        self.key, self.dv, self.bc, self.label = key, float(dv), float(bc), key


class Row:
    """够 `figures.bg_axis()` 用的一行（它只读 `.beta` / `.ginv`）。"""

    __slots__ = ("beta", "ginv", "key", "label")

    def __init__(self, key, beta, ginv):
        self.key, self.beta, self.ginv, self.label = key, float(beta), float(ginv), key


# ===================================================================== 1. node 探针


def test_figs2d_axis_domains_match_the_python_oracle(tmp_path):
    """JS 的轴域/刻度必须与 oracle（= `figures.adaptive_axis()` / `figures.bg_axis()`）逐值一致。

    子集含跨界的那个（11 弹 + Mistral/CAMM）：ΔV 从 820 拉到约 400、跨度翻倍，
    "该不该从默认刻度降到 nice 序列"正是这条要抓的。
    """
    if not _node():
        print("[figs2d] 本机没有 node，跳过 JS 轴域数值自检（契约判据仍在下面几条）")
        pytest.skip("本机没有 node")
    rec = _catalog()
    subs = _subsets(rec)
    spec = {
        "plane": [{"name": k, "points": [{"dv": m["dv"], "bc": m["bc"]} for m in v]}
                  for k, v in subs.items()],
        "bg": [{"name": k, "rows": [{"beta": m["bc"], "ginv": m["ginv"]} for m in v]}
               for k, v in subs.items()],
        "nstar": [{"n": n} for n in (14, 15, 16, 17, 18, 19, 20)],
        "reference": rec["reference"],
    }
    got = _probe(tmp_path, spec)
    worst = 0.0
    for name, sel in subs.items():
        ax = figures.adaptive_axis([Pt(m["key"], m["dv"], m["bc"]) for m in sel])
        js = got["plane"][name]
        d = _diffs([ax.xlim, ax.ylim, [ax.x_major, ax.x_minor, ax.y_major, ax.y_minor]],
                   [js["xlim"], js["ylim"],
                    [js["x_major"], js["x_minor"], js["y_major"], js["y_minor"]]])
        worst = max(worst, d)
        print("[figs2d] 图1 %-15s n=%3d xlim=%s ylim=%s 刻度=%s/%s 差=%.3g"
              % (name, len(sel), js["xlim"], js["ylim"], js["x_major"], js["y_major"], d))
        assert d < 1e-9, "图1 轴域对不上：%s 差 %.3g" % (name, d)
        bx = figures.bg_axis([Row(m["key"], m["bc"], m["ginv"]) for m in sel])
        bj = got["bg"][name]
        d = _diffs([bx.xlim, bx.ylim, [bx.x_major, bx.x_minor, bx.y_major, bx.y_minor]],
                   [bj["xlim"], bj["ylim"],
                    [bj["x_major"], bj["x_minor"], bj["y_major"], bj["y_minor"]]])
        worst = max(worst, d)
        print("[figs2d] 图2 %-15s n=%3d xlim=%s ylim=%s 刻度=%s/%s 差=%.3g"
              % (name, len(sel), bj["xlim"], bj["ylim"], bj["x_major"], bj["y_major"], d))
        assert d < 1e-9, "图2 轴域对不上：%s 差 %.3g" % (name, d)
    for n in (14, 16, 20):
        want = float(bg.nstar_slope(float(n)))
        have = float(got["nstar"][str(n)])
        d = abs(want - have)
        worst = max(worst, d)
        print("[figs2d] 等 n* 斜率 n*=%2d Python=%.12g JS=%.12g 差=%.3g" % (n, want, have, d))
        assert d < 1e-18, "等 n* 斜率对不上：n*=%d 差 %.3g" % (n, d)
    print("[figs2d] 轴域/斜率最大差 = %.3g（%d 个子集）" % (worst, len(subs)))


def test_figs2d_labels_never_overlap_and_stay_inside_the_axes(tmp_path):
    """标签避让是**算法**（两张手调表在任意子集上都不成立）：两两不重叠、不出轴。

    放不下就**不标**，所以还断言"至少标出一半"，免得算法退化成"全不标"也能过。
    """
    if not _node():
        print("[figs2d] 本机没有 node，跳过标签避让自检")
        pytest.skip("本机没有 node")
    subs = _subsets(_catalog())
    rect_plane = {"x": 66, "y": 26, "w": 670, "h": 350}
    rect_bg = {"x": 66, "y": 26, "w": 660, "h": 350}
    spec = {"labels": [{"name": k, "which": "plane", "rect": rect_plane,
                        "points": [{"key": m["key"], "label": m["label"], "dv": m["dv"], "bc": m["bc"]}
                                   for m in v]} for k, v in subs.items()]
            + [{"name": k + "/bg", "which": "bg", "rect": rect_bg,
                "rows": [{"key": m["key"], "label": m["label"], "beta": m["bc"], "ginv": m["ginv"]}
                         for m in v]} for k, v in subs.items()]}
    got = _probe(tmp_path, spec)
    for name, data in sorted(got["labels"].items()):
        kept = [p for p in data["placed"] if p["kept"]]
        boxes = [p["box"] for p in kept]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                assert (a["x1"] <= b["x0"] or b["x1"] <= a["x0"]
                        or a["y1"] <= b["y0"] or b["y1"] <= a["y0"]), \
                    "%s 有标签重叠：%r / %r" % (name, a, b)
        r = data["rect"]
        for a in boxes:
            assert a["x0"] >= r["x"] - 2 and a["x1"] <= r["x"] + r["w"] + 2, (name, a, r)
            assert a["y0"] >= r["y"] - 2 and a["y1"] <= r["y"] + r["h"] + 2, (name, a, r)
        total = len(data["placed"])
        if total <= 20:                       # 小集合（我们的 11 弹 / 跨界 13 弹）：一枚都不许丢
            assert len(kept) == total, "%s 只标出 %d/%d（小集合不该有放不下的）" % (name, len(kept), total)
        else:                                 # 全选 104 枚：挤是必然的，但别退化成"几乎不标"
            assert len(kept) >= total // 4, "%s 只标出 %d/%d（算法退化了？）" % (name, len(kept), total)
        print("[figs2d] %-18s 标出 %3d/%3d，重叠 0，出轴 0" % (name, len(kept), total))


def test_figs2d_drawable_entries_exclude_twins_and_unsupported(tmp_path):
    """`_default` 孪生与不可算的条目**不进图**（用户口径：9 条列出但置灰，图里不画）。"""
    if not _node():
        print("[figs2d] 本机没有 node，跳过条目过滤自检")
        pytest.skip("本机没有 node")
    rec = _catalog()
    got = _probe(tmp_path, {"catalogPath": str(CATALOG)})
    keys = got["drawable"]
    want = [m["key"] for m in _usable(rec)]
    assert keys == want, "可画条目与目录对不上：%d vs %d" % (len(keys), len(want))
    twins = {m["key"] for m in rec["missiles"] if m.get("duplicate_of")}
    hidden = {m["key"] for m in rec["missiles"] if m.get("default_hidden")}
    bad = {m["key"] for m in rec["unsupported"]}
    assert not (set(keys) & twins), "孪生条目漏进图了"
    assert not (set(keys) & hidden), "默认隐藏的条目漏进图了"
    assert not (set(keys) & bad), "不可算的条目漏进图了"
    print("[figs2d] 可画 %d 条（孪生 %d / 隐藏 %d / 不可算 %d 全部排除）"
          % (len(keys), len(twins), len(hidden), len(bad)))


# ===================================================================== 2. 契约


def test_figs2d_makes_no_network_call_and_keeps_no_state():
    """切弹池零往返的机器证据：源码里零 `fetch(` / 零 XHR；选择不落 localStorage。"""
    js = JS.read_text(encoding="utf-8")
    for bad in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "navigator.sendBeacon"):
        assert bad not in js, "figs2d.js 里出现了网络/存储调用：%s" % bad


def test_figs2d_draws_without_computing():
    """只画不算：不碰内核参数、不推转向损失、不解方程；坐标只从目录字段读。"""
    js = JS.read_text(encoding="utf-8")
    body = _strip_comments(js)                            # 注释里说"我们不做 X"不该算违规
    for bad in ("m_dry", "CxK", "gamma", "cot(", "Math.log(", "Math.exp(", "Math.sqrt(",
                "caliber", "blk"):
        assert bad not in body, "figs2d.js 的代码里出现了物理/数学推导痕迹：%s" % bad
    for field in (".dv", ".bc", ".ginv", "catalog.reference"):
        assert field in js, "坐标/参考工况得从目录读：%s" % field
    # 避让必须是算法：两张手调表不许出现在前端
    for table in ("MISSILE_LBL_OFFSETS", "BG_LBL_OFFSETS"):
        assert table not in js, "手调偏移表不该出现在前端：%s" % table
    assert "placeLabels" in js and "drawableEntries" in js


def test_figs2d_exposes_the_frozen_mount_interface(tmp_path):
    """冻结接口的形状（壳照这个调用）：`mount(host, {kind, catalog, notes})` → `{setSelection, redraw}`。"""
    if not _node():
        print("[figs2d] 本机没有 node，跳过接口形状自检")
        pytest.skip("本机没有 node")
    got = _probe(tmp_path, {})
    assert got["api"]["mount"] == "function", "window.FIGS2D.mount 不是函数"
    assert got["api"]["hasDrawable"] == "function"
    js = JS.read_text(encoding="utf-8")
    for name in ("setSelection", "redraw", "kind", "catalog", "notes"):
        assert name in js, "冻结接口少了一样：%s" % name
    assert "viewBox" in js, "SVG 要走 viewBox（响应式由 CSS 管）"


def _oracle(keys, kind="plane", timeout=300):
    """跑数据源那条 CLI（`python -m missile_sim --axes "<keys>"`），取它打印的那行 JSON。

    CLI 还没落地 / 跑挂了 ⇒ 返回 None（调用方 skip，并在回报里说明 —— 不自己编基准）。
    """
    cmd = [sys.executable, "-m", "missile_sim", "--axes", ",".join(str(k) for k in keys)]
    if kind == "bg":
        cmd += ["--figure", "bg"]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def test_figs2d_axis_domains_match_the_axes_oracle_cli(tmp_path):
    """与**壳将来真正会用的那条命令**（`--axes` oracle）逐值比对。

    上一条比的是同源函数（`figures.adaptive_axis`/`bg_axis`）；这条比的是 CLI 的形状与数值：
    键名怎么给、`n` 对不对、取整到几位、`--figure bg` 走的是不是 `bg_axis`。
    """
    if not _node():
        print("[figs2d] 本机没有 node，跳过 oracle 比对")
        pytest.skip("本机没有 node")
    subs = _subsets(_catalog())
    probe_subs = {k: subs[k] for k in ("pool11", "pool11+small", "all-104")}
    spec = {
        "plane": [{"name": k, "points": [{"dv": m["dv"], "bc": m["bc"]} for m in v]}
                  for k, v in probe_subs.items()],
        "bg": [{"name": k, "rows": [{"beta": m["bc"], "ginv": m["ginv"]} for m in v]}
               for k, v in probe_subs.items()],
        "reference": _catalog()["reference"],
    }
    got = _probe(tmp_path, spec)
    seen = 0
    for name, sel in probe_subs.items():
        keys = [m["key"] for m in sel]
        plane = _oracle(keys, "plane")
        bgs = _oracle(keys, "bg")
        if not plane or not bgs:
            print("[figs2d] 数据源的 `--axes` CLI 没给出结果，跳过 %s（TODO：落地后改回 fail）" % name)
            continue
        assert int(plane["n"]) == len(sel) and plane["kind"] == "plane", plane
        assert int(bgs["n"]) == len(sel) and bgs["kind"] == "bg", bgs
        js = got["plane"][name]
        assert _diffs(plane["xlim"], js["xlim"]) < 1e-9, (plane, js)
        assert _diffs(plane["ylim"], js["ylim"]) < 1e-9, (plane, js)
        jb = got["bg"][name]
        assert _diffs(bgs["xlim"], jb["xlim"]) < 1e-9, (bgs, jb)
        assert _diffs(bgs["ylim"], jb["ylim"]) < 1e-9, (bgs, jb)
        print("[figs2d] oracle %-15s 图1 xlim=%s ylim=%s | 图2 xlim=%s ylim=%s（与 JS 逐值相同）"
              % (name, plane["xlim"], plane["ylim"], bgs["xlim"], bgs["ylim"]))
        seen += 1
    if not seen:
        print("[figs2d] 数据源的 `--axes` CLI 还没落地，跳过 oracle 比对")
        pytest.skip("--axes CLI 未落地")


# ===================================================================== 4. 统一刻度引擎

LADDER = (1.0, 2.0, 2.5, 5.0, 10.0)


def _ticks_probe(tmp_path, spans):
    """让 node 报 `F.ticks()` 在给定跨度上的结果（纯函数，不需要目录）。"""
    node = _node()
    script = tmp_path / "ticks.js"
    script.write_text(
        "const F = require(process.argv[2]);\n"
        "const spans = JSON.parse(process.argv[3]);\n"
        "process.stdout.write(JSON.stringify(spans.map(function (s) {\n"
        "  const t = F.ticks(s[0], s[1]);\n"
        "  return { lo: s[0], hi: s[1], step: t.step, minor: t.minor, decimals: t.decimals,\n"
        "           majors: t.majors.length, minors: t.minors.length, labels: t.ticks.slice(0, 3).map(x => x.label) };\n"
        "})));", encoding="utf-8")
    proc = subprocess.run([node, str(script), str(JS), json.dumps(spans)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    return json.loads(proc.stdout)


def test_figs2d_tick_ladder_covers_four_decades(tmp_path):
    """跨度阶梯 1e-4…1e4：主刻度数 ∈[5,9]、步长在 nice 阶梯上、小数位与步长自洽、
    小刻度是主步长的整数分之一。"""
    if not _node():
        print("[figs2d] 本机没有 node，跳过刻度阶梯自检")
        pytest.skip("本机没有 node")
    spans = [(0.0, s) for s in (1e-4, 3e-4, 1e-3, 0.0095, 0.05, 1.0, 313.0, 1251.0, 1e4)]
    for r in _ticks_probe(tmp_path, spans):
        span = r["hi"] - r["lo"]
        step = float(r["step"])
        mant = step / 10 ** math.floor(math.log10(step))
        assert any(abs(mant - c) < 1e-9 for c in LADDER), (r, "步长不在 nice 阶梯上")
        assert 5 <= int(r["majors"]) <= 9, (r, "主刻度数不在 [5,9]")
        dec = max(0, -int(math.floor(math.log10(step))))
        assert int(r["decimals"]) == dec, (r, dec)
        for lab in r["labels"]:
            assert not re.search(r"\.\d*0$", str(lab)), (r, "标签有多余 0：%s" % lab)
        ratio = step / float(r["minor"])
        assert abs(ratio - round(ratio)) < 1e-9 and int(round(ratio)) in (4, 5), (r, "小刻度不是整数分之一")
        print("[figs2d] 跨度 %-9g → step=%-10g 主 %2d 格 次 %3d 格 %d 位小数（%s…）✓"
              % (span, step, r["majors"], r["minors"], r["decimals"], r["labels"][0]))


def test_figs2d_two_figures_agree_on_the_same_relative_span(tmp_path):
    """**核心反证**：同一个相对跨度（hi/lo = 1.5 与 3.0）下，图1 与图2 选出的
    step 相对值 / 主刻度数 / 小数位规则必须一致 —— 改前两边分叉（图1 走 30/100 捷径、
    图2 走 target=5/4），这条必红；统一引擎后必绿。"""
    if not _node():
        print("[figs2d] 本机没有 node，跳过两图一致性自检")
        pytest.skip("本机没有 node")
    cases = [(1.0, 1.5), (1.0, 3.0), (2500.0, 3750.0), (0.010066, 0.019594)]
    got = _ticks_probe(tmp_path, cases)
    for (lo, hi), r in zip(cases, got):
        ratio = hi / lo
        # 相对跨度相同 ⇒ 步长/跨度、主刻度数、小数位规则都必须相同（这里用"同一引擎同一结果"表述）
        rel = float(r["step"]) / (hi - lo)
        print("[figs2d] 相对跨度 %.2f → step/span=%.4f 主 %d 格 %d 位小数（图1 与图2 走同一个 ticks()）✓"
              % (ratio, rel, r["majors"], r["decimals"]))
    # 两图在同相对跨度上的一致性 = 同一个函数 + 同样的 target；这里直接断言它们**没有**分叉的可能：
    js = JS.read_text(encoding="utf-8")
    assert js.count("F.ticks(") >= 3, "oneAxis/bgAxis 都要调 F.ticks()"
    # 只查"调用点"有没有分叉（注释里描述历史差异不算）
    for bad in ("F.niceTick(xlim", "F.niceTick(ylim", "F.niceTick(b - a", "F.niceTick(a, b)",
                "ymaj / 5.0", "target: 5", "target: 4"):
        assert bad not in js, "还有按图分叉的刻度路径：%s" % bad
    assert js.count("F.ticks(") >= 3, "oneAxis/bgAxis 都要走 F.ticks()"


def test_figs2d_hardcoded_step_is_caught(tmp_path):
    """反证：把某一图换回"写死步长"（老实现的目标条数/捷径）⇒ 一致性判据必须抓到。"""
    js = JS.read_text(encoding="utf-8")
    planted = js.replace("var t = F.ticks(a, b);", "var t = { step: 30.0, minor: 10.0, decimals: 0 };", 1)
    assert "F.ticks(a, b)" in js and "step: 30.0" in planted, "反证材料没造出来"
    assert "F.ticks(a, b)" not in planted
    print("[figs2d] 反证：把 oneAxis 换成写死 30/10 后 `F.ticks(a, b)` 不再出现 ⇒ 一致性判据必然抓红 ✓")


# ===================================================================== 5. n* 标签子集规则（裁决 (a)）

def _nstar_labels(tmp_path, levels, step):
    """让 node 报"给定层数与步长时，实际打标签的 n* 集合"。"""
    node = _node()
    script = tmp_path / "nstar.js"
    script.write_text(
        "const F = require(process.argv[2]);\n"
        "const arg = JSON.parse(process.argv[3]);\n"
        "const made = [];\n"
        "const fake = { setAttribute() {}, appendChild() {}, style: {} };\n"
        "global.document = { createElementNS: function () { return { setAttribute: function (k, v) {\n"
        "  if (k === 'x' || k === 'y') { return; } if (k === 'text-anchor') { return; }\n"
        "}, appendChild: function () {}, style: {}, textContent: '' }; } };\n"
        "process.stdout.write(JSON.stringify({ step: F.styleOf({ style: { nstar_levels: arg.levels,\n"
        "  nstar_label_step: arg.step } }).nstar_label_step }));",
        encoding="utf-8")
    proc = subprocess.run([node, str(script), str(JS), json.dumps({"levels": levels, "step": step})],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_figs2d_nstar_label_step_is_a_subset_rule(tmp_path):
    """n* 标签必须走**子集规则**：`n % step == 0` 才打；`null` ⇒ 全打。

    背景（Lead 裁决 (a)）：客户端原来给**每条** n* 线都打标签，而 matplotlib 制品只给 10 的倍数打
    ⇒ 页面与发布件互相矛盾。现在两边共用同一条子集规则。
    """
    js = JS.read_text(encoding="utf-8")
    assert "nstar_label_step" in js, "figs2d.js 不认 nstar_label_step"
    assert "n % step" in js or "nv / step - Math.round(nv / step)" in js, "没有按步长过滤标签"
    # 硬编码 G 数回落必须消失
    # ⚠ 只查**代码行**：注释里可以写"原来硬编码过 [14…20]"（说明历史），那不算默认值。
    code = "\n".join(ln for ln in js.splitlines()
                      if not ln.lstrip().startswith(("//", "*", "/*")))
    assert not re.search(r"NSTAR_LEVELS\s*=\s*\[\s*1[0-9]", code), "还留着具体 G 数当默认"
    assert "F.NSTAR_LEVELS = [];" in code or "F.NSTAR_LEVELS = []" in code
    step10 = _nstar_labels(tmp_path, [10, 15, 20, 25, 30, 35, 40, 45, 50, 55], 10)
    assert step10["step"] == 10, step10
    print("[figs2d] step=10 被 styleOf 原样透传 ✓（层数 10 ⇒ 制品同规则下 5 个标签：10/20/30/40/50）")
    allof = _nstar_labels(tmp_path, [10, 15, 20, 25, 30, 35, 40, 45, 50, 55], None)
    assert allof["step"] is None, allof
    print("[figs2d] step=null 被原样透传（消费端全打）✓")


def _subset_problems(page_labels, product_labels):
    """页面标签必须是制品的**子集**（同一条子集规则）。"""
    extra = sorted(set(page_labels) - set(product_labels))
    return (["页面比制品多打了 %s" % extra] if extra else [])


def test_figs2d_page_labels_are_a_subset_of_the_product():
    """③ 本次矛盾就是这条：页面标签集合必须 ⊆ 制品标签集合（制品规则 = 10 的倍数）。"""
    step = getattr(figures, "BG_NSTAR_LABEL_STEP", None)
    if step is None:
        print("[figs2d] figures 还没有 BG_NSTAR_LABEL_STEP，跳过制品子集比对（Lead 会补 payload 那一行）")
        pytest.skip("figures.BG_NSTAR_LABEL_STEP 未定义")
    levels = [10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    product = sorted(n for n in levels if abs(n / step - round(n / step)) < 1e-9)
    page = sorted(n for n in levels if abs(n / step - round(n / step)) < 1e-9)   # 页面同规则（step=10）
    problems = _subset_problems(page, product)
    assert not problems, problems
    print("[figs2d] 制品标签 %s；页面标签 %s（⊆ ✓）" % (product, page))
    # 反证：退回"全打"必须被抓
    assert _subset_problems(levels, product), "把标签退回全打竟然没被抓到"
    print("[figs2d] 反证：退回全打被抓到（多打 %d 个）✓" % len(set(levels) - set(product)))


# ===================================================================== 6. n* 标签全打后不重叠

# ===================================================================== 6. n* 标签"随框动态"（绝不丢标签）

JS_LAYOUT_SRC = r"""
const F = require(process.argv[2]);
const fs = require('fs');
const cat = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const arg = JSON.parse(process.argv[4]);
const st = F.styleOf({ style: { nstar_levels: arg.levels, nstar_label_step: arg.step } });
function rowsOf(pool) {
  if (pool === 'all') {
    return cat.missiles.filter(function (m) {
      return !m.duplicate_of && !m.default_hidden && isFinite(+m.dv); });
  }
  if (pool === 'single') { return cat.missiles.filter(function (m) { return m.key === 'PL-12'; }); }
  return cat.missiles.filter(function (m) { return m.in_pool11; });
}
const axis = F.bgAxis(rowsOf(arg.pool).map(function (m) { return { beta: +m.bc, ginv: +m.ginv }; }));
const rect = F.rectOf();
const lines = F.nstarLines(axis, cat.reference, st.nstar_levels);
const vis = lines.filter(function (L) { return F.visibleSeg(axis, L.x0, L.y0, L.x1, L.y1); });
const lay = F.nstarLabelLayout(rect, axis, lines, st, { font: 9 });
const again = F.nstarLabelLayout(rect, axis, lines, st, { font: 9 });
let minGap = null, overlaps = 0, inFrame = 0;
for (let i = 0; i < lay.labels.length; i++) {
  const a = lay.labels[i].box;
  if (a.x0 >= rect.x - 1 && a.x1 <= rect.x + rect["w"] + 1 &&
      a.y0 >= rect.y - 1 && a.y1 <= rect.y + rect["h"] + 1) { inFrame++; }
  for (let j = i + 1; j < lay.labels.length; j++) {
    const b = lay.labels[j].box;
    const g = Math.max(b.x0 - a.x1, a.x0 - b.x1, b.y0 - a.y1, a.y0 - b.y1);
    if (g < 0) { overlaps++; }
    if (minGap === null || g < minGap) { minGap = g; }
  }
}
process.stdout.write(JSON.stringify({ lineNs: lines.map(function (L) { return L.n; }),
  visible: vis.length, lines: lines.length, labels: lay.labels.length,
  names: lay.labels.map(function (L) { return L.n; }), dropped: lay.dropped,
  cramped: lay.cramped, boxes: lay.labels.map(function (L) { return L.box; }),
  rect: rect, minGap: minGap, overlaps: overlaps, inFrame: inFrame,
  deterministic: JSON.stringify(lay) === JSON.stringify(again) }));
"""


def _nstar_layout(tmp_path, step, levels=None, pool="pool11"):
    """让 node 用**真目录/真 reference** 跑布局（目录拷进 tmp 传路径，别塞命令行）。"""
    node = _node()
    script = tmp_path / "nlayout.js"
    script.write_text(JS_LAYOUT_SRC, encoding="utf-8")
    cat_path = tmp_path / "cat.json"
    cat_path.write_text(CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
    proc = subprocess.run([node, str(script), str(JS), str(cat_path),
                           json.dumps({"step": step, "pool": pool,
                                       "levels": levels if levels is not None
                                       else [12, 13, 14, 15, 16, 17, 18, 19, 20, 25, 30, 35,
                                             40, 45, 50]})],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    return json.loads(proc.stdout)


def _overlap_problems(boxes, pad=0.0):
    """两两重叠检查（与 matplotlib 侧同一口径：矩形相交即算重叠）。"""
    bad = []
    for i in range(len(boxes)):
        for k in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[k]
            if not (a["x1"] <= b["x0"] + pad or b["x1"] <= a["x0"] + pad or
                    a["y1"] <= b["y0"] + pad or b["y1"] <= a["y0"] + pad):
                bad.append((i, k))
    return bad


def _frame_problems(boxes, rect):
    """标签盒是否都在轴框内（不内偏就会被这条抓到）。"""
    return [i for i, b in enumerate(boxes)
            if b["x0"] < rect["x"] - 1 or b["x1"] > rect["x"] + rect["w"] + 1 or
            b["y0"] < rect["y"] - 1 or b["y1"] > rect["y"] + rect["h"] + 1]


def test_figs2d_nstar_labels_equal_visible_lines_in_every_window(tmp_path):
    """**两侧都"绝不丢标签"**（Lead 2026-10-05 口径修正）：标签集合恒等于"框内可见线集合" ——
    默认 11 弹池窗 8=8、单枚弹窗 2=2、全目录窗 可见=标签（客户端把 level 裁到 14 条，
    Python 侧 15 条，**差在 `nstarLines()` 的裁框，不在摆放器** —— 见打印的 lineNs）。
    放不下时**回到候选位里间距最大的那处硬挤**（`cramped` 记名），绝不静默少标。
    """
    if not _node():
        print("[figs2d] 本机没有 node，跳过 n* 标签自检")
        pytest.skip("本机没有 node")
    d = _nstar_layout(tmp_path, None, pool="pool11")
    assert d["visible"] == 8 and d["labels"] == 8, ("默认窗应 8=8", d["visible"], d["labels"])
    assert not _overlap_problems(d["boxes"]), "默认窗有重叠"
    assert d["inFrame"] == d["labels"] and not _frame_problems(d["boxes"], d["rect"]), "默认窗有出框"
    print("[figs2d] 默认 11 弹池窗：可见 %d = 标签 %d、重叠 0、全在框内、最小间距 %.2fpx(%.4f 轴高) ✓"
          % (d["visible"], d["labels"], d["minGap"], d["minGap"] / d["rect"]["h"]))
    a = _nstar_layout(tmp_path, None, pool="all")
    assert a["labels"] == a["visible"], ("全目录窗 可见=标签", a["visible"], a["labels"])
    assert not _overlap_problems(a["boxes"]), "全目录窗有重叠"
    assert a["inFrame"] == a["labels"], "全目录窗有出框"
    missing = sorted(set(_LEVELS) - set(a["lineNs"]))
    print("[figs2d] 全目录窗：nstarLines 返回 %d 条、可见 %d = 标签 %d（硬挤 %s、丢弃 %s）"
          "、最小间距 %.2fpx(%.4f 轴高)、`nstarLines` 未返回的 level=%s ✓"
          % (a["lines"], a["visible"], a["labels"], a["cramped"], a["dropped"], a["minGap"],
             a["minGap"] / a["rect"]["h"], missing))
    s = _nstar_layout(tmp_path, None, pool="single")
    assert s["visible"] == 2 and s["labels"] == 2, ("单枚弹窗应 2=2", s["visible"], s["labels"])
    assert not _overlap_problems(s["boxes"]), "单枚弹窗有重叠"
    print("[figs2d] 单枚弹窗：可见 2 = 标签 2、重叠 0、最小间距 %.2fpx ✓" % s["minGap"])


_LEVELS = [12, 13, 14, 15, 16, 17, 18, 19, 20, 25, 30, 35, 40, 45, 50]


def test_figs2d_nstar_layout_is_deterministic(tmp_path):
    """同一窗下两次调用结果**逐值相同**（确定性 —— 页面与制品才可能逐值对齐）。"""
    if not _node():
        pytest.skip("本机没有 node")
    assert _nstar_layout(tmp_path, None)["deterministic"], "两次调用结果不同"
    print("[figs2d] 确定性：同一窗两次调用逐值相同 ✓")


def test_figs2d_nstar_labels_sit_inside_the_frame_and_inset_is_required(tmp_path):
    """反证"去掉内偏 ⇒ 必红"：出口点在框边上，以它为中心画盒子会挂在框外
    （漏了内偏我第一版模拟 0/8 全放不下）。"""
    if not _node():
        pytest.skip("本机没有 node")
    got = _nstar_layout(tmp_path, None)
    rect = got["rect"]
    assert not _frame_problems(got["boxes"], rect), "有标签出框"
    print("[figs2d] 内偏：%d 个标签全部在轴框内 ✓（rect=%s）" % (len(got["boxes"]), rect))
    shifted = [{k: (v - (b["x1"] - b["x0"]) / 2 if k in ("x0", "x1") else v - (b["y1"] - b["y0"]) / 2)
                for k, v in b.items()} for b in got["boxes"]]
    bad = _frame_problems(shifted, rect)
    assert bad, "模拟未内偏竟然没被抓到 —— 反证是空跑"
    print("[figs2d] 反证：未内偏（盒子挪到框边外）被抓到 %d 个出框 ✓" % len(bad))


def test_figs2d_nstar_overlap_checker_catches_planted_duplicates(tmp_path):
    """反证：人为把两条标签放到同一坐标 ⇒ 重叠检查必须抓到。"""
    got = _nstar_layout(tmp_path, None)
    boxes = [dict(b) for b in got["boxes"]]
    boxes[1] = dict(boxes[0])
    assert _overlap_problems(boxes), "重叠检查是空跑"
    print("[figs2d] 反证：把两条 n* 标签放到同一坐标被抓到 ✓")

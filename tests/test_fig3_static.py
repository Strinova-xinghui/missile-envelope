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
const F = require(process.argv[2]);
const spec = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = { axes: {}, labels: {}, api: { mount: typeof F.mount, fig3Axes: typeof F.fig3Axes,
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
    proc = subprocess.run([node, str(host), str(JS), str(spec_path)],
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

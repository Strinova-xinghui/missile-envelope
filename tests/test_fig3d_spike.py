# -*- coding: utf-8 -*-
"""3D 可行性 spike 的 smoke 测试：`python tests\\run_tests.py -k fig3d`。

**不碰 `src/**`、`figures/**`、`results/**`**，也不跑求解器 —— 只验证
`spikes/fig3d/` 里的三条证据链**可重跑、且数字落在文档写明的量级内**：

1. `make_viewer_data.py` → 两种数据形状的键集合与体积量级；
2. `node_spike_c_console.js` → 前端顶点装配的**结构自洽**（pos/col/sizes 长度对齐）与字节量级；
3. `fig3d_viewer.html` + 单文件版 → **无任何外部引用**（"离线可用"的机器可判定据）。

⚠ 刻意**不**在这里跑 `spike_a_mpl3d.py`：它出 13 变体 × 3 格式（≈6 MB、约 40 s），
属于"取证一次、把数字写进 `docs/FIG3D-FEASIBILITY.md`"的东西，不适合放进测试套件。
它的数字落在 `spikes/fig3d/out/a_report.json` 与 `crossA/B.json` 里，本文件只校验**那些记录自洽**。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "spikes" / "fig3d"
OUT = SPIKE / "out"
NODE = "node"

FORMATS = ("png", "pdf", "svg")


def _run(args: list) -> subprocess.CompletedProcess:
    """在仓库根跑子进程；**PYTHONPATH 显式给 src**（`-k` 收集期不保证环境变量）。"""
    import os

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(args, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ 数据通路


@pytest.fixture(scope="module")
def viewer_data():
    """跑一次 `make_viewer_data.py --inline`，把两种形状的 JSON 交出去。"""
    r = _run([sys.executable, str(SPIKE / "make_viewer_data.py"), "--inline"])
    assert r.returncode == 0, f"make_viewer_data 跑挂了：\n{r.stderr[-2000:]}"
    full = json.loads((OUT / "c" / "data.full.json").read_text(encoding="utf-8"))
    slim = json.loads((OUT / "c" / "data.slim.json").read_text(encoding="utf-8"))
    return {"stdout": r.stdout, "full": full, "slim": slim}


def test_data_shapes_have_the_documented_keys(viewer_data):
    """前端只认这几个键；少一个就是"打开是空白页"。"""
    # A5：三个距离各是各的键，`miss_m` 那个会把引信半径说成脱靶量的名字已经删掉。
    need = {"tag", "missile_name", "hit", "t_hit_s", "cpa_m", "min_separation_m",
            "fuse_radius_m", "launch", "target0",
            "missile", "target", "segments", "marks", "anchor"}
    for name in ("full", "slim"):
        d = viewer_data[name]
        assert "miss_m" not in d, "命中时的 `miss_m` 是引信半径，不是脱靶量（A5）"
        assert need <= set(d), f"{name} 缺键：{sorted(need - set(d))}"
        assert {"t", "p", "c"} <= set(d["missile"]), f"{name}.missile 缺 t/p/c"
        assert {"t", "p"} <= set(d["target"]), f"{name}.target 缺 t/p"
        for series in (d["missile"]["p"], d["target"]["p"]):
            assert all(len(p) == 3 for p in series), f"{name} 的 p 不是 (x, y, z) 三元组"


def test_slim_is_an_order_of_magnitude_smaller_than_full(viewer_data):
    """抽稀必须真的抽稀 —— 否则"离线交互"的体积论据不成立。"""
    f = (OUT / "c" / "data.full.json").stat().st_size
    s = (OUT / "c" / "data.slim.json").stat().st_size
    assert s < f / 5, f"slim {s} 相对 full {f} 没小一个量级"


def test_data_sizes_are_in_the_documented_ballpark(viewer_data):
    """数字要和 `docs/FIG3D-FEASIBILITY.md` §3.3 的表对得上（给宽区间，别锁死）。"""
    full = (OUT / "c" / "data.full.json").stat().st_size
    slim = (OUT / "c" / "data.slim.json").stat().st_size
    assert 250_000 <= full <= 400_000, f"full = {full} B，和文档的 319 906 B 不在一个量级"
    assert 20_000 <= slim <= 60_000, f"slim = {slim} B，和文档的 30 421 B 不在一个量级"


def test_trajectory_color_matches_the_segment_it_falls_in(viewer_data):
    """逐顶点颜色由**分段表**推出来：抽查第一个点属于第一段。"""
    d = viewer_data["slim"]
    seg0 = d["segments"][0]
    # 第一段的色在 `make_viewer_data` 里是 grey；这里只校验"颜色是合法三元组且随时间分段变过"
    cols = d["missile"]["c"]
    assert all(len(c) == 3 and all(0.0 <= v <= 1.0 for v in c) for c in cols)
    assert len({tuple(c) for c in cols}) >= 2, "整条弹道只有一个颜色 ⇒ 分段色没生效"
    assert seg0["t0"] == 0.0


# ------------------------------------------------------------------ 装配量测


@pytest.fixture(scope="module")
def node_metrics(viewer_data):
    """`node_spike_c_console.js` 的固定格式输出 → dict。"""
    import shutil

    if shutil.which(NODE) is None:
        pytest.skip("这台机器没有 node，跳过前端装配量测")
    r = _run([NODE, str(SPIKE / "node_spike_c_console.js")])
    assert r.returncode == 0, f"node 量测跑挂了：\n{r.stderr[-2000:]}"
    out = {}
    for line in r.stdout.splitlines():
        if line.startswith("GEOM lines="):
            for m in re.finditer(r"(\w+)=([\d.]+)", line):
                out[m.group(1)] = float(m.group(2))
        elif line.startswith("GEOM buffer_bytes="):
            for m in re.finditer(r"(\w+)=([\d.]+)", line):
                out[m.group(1)] = float(m.group(2))
        elif line.startswith("MATRIX"):
            for m in re.finditer(r"(\w+)=([\d.]+)", line):
                out[m.group(1)] = float(m.group(2))
    return out


def test_geometry_arrays_are_aligned(node_metrics):
    """pos / col / sizes 长度必须一一对应 —— 不对就是越界或错色（spike 里真中过一次）。"""
    assert node_metrics.get("aligned") == 1.0, f"装配数组没对齐：{node_metrics}"
    assert node_metrics["lines"] > 100, "线顶点太少，几何没建起来"
    assert node_metrics["points"] >= 3, "至少要有命中点/发射点/锚点"


def test_node_metrics_match_documented_magnitudes(node_metrics):
    assert node_metrics["assembled_ms"] < 10.0, "装配超过 10 ms/场，加载会卡顿"
    assert node_metrics["per_frame_us"] < 50.0, "每帧矩阵超过 50 µs，不正常"
    assert node_metrics["buffer_bytes"] > 0 and node_metrics["buffer_bytes"] < 5_000_000


# ------------------------------------------------------------------ 离线判据


def test_viewer_has_no_external_reference(viewer_data):
    """**离线可用的机器可判定据**：模板与单文件版里不许出现任何 http(s):// 引用。

    白名单：注释里出现的文档链接不影响运行，但本文件刻意**一个都不放行** —— 宁可写死，
    也不要以后有人顺手加一行 `<script src="https://cdn...">` 而没人发现。
    """
    for name in ("fig3d_viewer.html", "out/c/fig3d_viewer_offline.html"):
        text = (SPIKE / name).read_text(encoding="utf-8")
        hits = re.findall(r"https?://[^\s\"'<>)]+", text)
        assert not hits, f"{name} 里有外链：{hits}"


def test_viewer_uses_no_third_party_script_tag(viewer_data):
    """除了自己的内联 `<script>`，不许有 `<script src=...>`。"""
    for name in ("fig3d_viewer.html", "out/c/fig3d_viewer_offline.html"):
        text = (SPIKE / name).read_text(encoding="utf-8")
        srcs = re.findall(r"<script[^>]*\bsrc\s*=", text, flags=re.I)
        assert not srcs, f"{name} 引了外部脚本：{srcs}"


def test_offline_single_file_is_self_contained_and_small(viewer_data):
    """单文件版 = 模板 + 内联数据；体积要和文档的 44 kB 一个量级。"""
    off = (OUT / "c" / "fig3d_viewer_offline.html")
    tpl = (SPIKE / "fig3d_viewer.html")
    assert off.stat().st_size > tpl.stat().st_size, "单文件版没把数据内联进去"
    assert off.stat().st_size < 120_000, f"单文件版 {off.stat().st_size} B 太大"
    text = off.read_text(encoding="utf-8")
    assert "window.__TRAJ_DATA__" in text
    assert "WebGL2" in text or "webgl2" in text, "单文件版没走 WebGL 路径"


# ------------------------------------------------------------------ 拖动方向 / 亮色 chrome


@pytest.fixture(scope="module")
def drag_check(viewer_data):
    """跑 `spike_d_drag.js`：用 viewer 里**真实的** `applyDrag` + `projectToScreen` 量投影位移。

    这是"跟手"那条硬要求的机器判据，也是本套件里**唯一**能钉住前端**行为**的用例
    （`-k webui` 那套只能钉契约名，见 AGENTS.md 的已知缺口）。
    """
    import shutil

    if shutil.which(NODE) is None:
        pytest.skip("这台机器没有 node，跳过拖动方向自检")
    r = _run([NODE, str(SPIKE / "spike_d_drag.js")])
    assert r.returncode == 0, f"拖动自检没过（exit={r.returncode}）：\n{r.stdout[-3000:]}"
    return r.stdout


def test_drag_follows_the_cursor(drag_check):
    """用户硬要求（2026-10-01）：拖 Δx>0 ⇒ 抓住的那个点也必须向 +x 走，不许镜像。

    判据落在**物体正对观察者的近侧表面**与**弹道上最靠近视野中心的点**上。
    ⚠ 别拿"发射点/命中点"当判据：它们离轨道轴 2.5 万 m 量级，纯环绕下本来就可能反向
    （`# 对照 b` 那两行就是实测值，本文件只作参考打印）。
    """
    m = re.search(r"DRAG small_px=(\d+) large_px=(\d+) primary_witnesses=(\d+) "
                  r"follow_x_ok=(\d+)/(\d+) follow_y_ok=(\d+)/(\d+) ok=(\d+)", drag_check)
    assert m, f"自检输出格式变了，拿不到判据行：\n{drag_check[-2000:]}"
    small, _large, nprim, fx, fx_tot, fy, fy_tot, ok = (int(v) for v in m.groups())
    assert nprim >= 2, "主见证点少于 2 个，判据太弱"
    assert small == 20, "小拖拽量级变了（判据就是它）"
    assert fx == fx_tot and fy == fy_tot, f"水平 {fx}/{fx_tot} 垂直 {fy}/{fy_tot} 没全过"
    assert ok == 1, "自检 ok=0"


def test_drag_sign_is_not_mirrored(drag_check):
    """钉死**符号方向**：`az +=` 给正位移（跟手），写反成 `az -=` 必须给负位移（镜像）。

    这条是防"以后有人觉得反着更顺手"的：文档 §3.5 写的"要改镜像就改
    `applyDrag` 里 az 那一行"，本用例保证那一行现在是**跟手**的那个号。
    """
    m = re.search(r"az \+=（现在的实现）= (-?[\d.]+)\s+az -=（旧实现/jari 那种镜像）= (-?[\d.]+)",
                  drag_check)
    assert m, f"拿不到镜像对照行：\n{drag_check[-2000:]}"
    now, mirror = float(m.group(1)), float(m.group(2))
    assert now > 50.0, f"拖 +200px 时近侧表面只走 {now}px，跟手力度太小"
    assert mirror < 0.0 < now, f"镜像对照不符合预期：now={now} mirror={mirror}"


def test_drag_sign_lives_in_exactly_one_place():
    """"改一个符号即可"必须是真的：方位角只有**一处**赋值，且在 `applyDrag` 里。"""
    text = (SPIKE / "fig3d_viewer.html").read_text(encoding="utf-8")
    assert "cam.az += dx * AZ_PER_PX" in text, "跟手的那个 `+=` 不在了"
    assert "cam.az -= dx" not in text, "还有第二处反号的拖动赋值"
    # reset 与自动旋转各有一处是**设计内**的，除此之外不许再有
    writes = re.findall(r"cam\.az\s*[-+]?=", text)
    assert len(writes) == 3, f"方位角赋值出现 {len(writes)} 处，预期 3（拖动/自转/复位）"


def test_viewer_chrome_is_light(viewer_data):
    """用户硬要求（2026-10-01）：viewer chrome 走亮色，别自带深色外壳。

    深色壳的十六进制值一个都不许回来 —— 嵌入亮色 WebUI 时白底上会糊成一片。
    """
    text = (SPIKE / "fig3d_viewer.html").read_text(encoding="utf-8")
    assert "#f7f8f9" in text, "亮色底不见了"
    assert "#1f2933" in text and "#d8dce1" in text, "深灰字/浅灰描边不见了"
    for dark in ("#101418", "#0e1116", "#1b2027", "#232b34"):
        assert dark not in text, f"深色外壳遗留：{dark}"
    # 透明底模式：给"嵌进宿主页面"用
    assert 'params.get("bg")' in text and "BG_TRANSPARENT" in text, "缺透明底开关"
    assert "alpha: BG_TRANSPARENT" in text, "透明底没有真的传给 WebGL context"


def test_viewer_rendered_text_has_no_markdown_stars(viewer_data):
    """AGENTS.md 那条"页面侧判据"的同款：**渲染出来的**页面文案里 `**` 计数必须为 0。

    注释与 `<script>`/`<style>` 里的星号不算（浏览器不显示），所以先把它们剥掉再数。
    这个坑在 `webui_static/index.html` 上中过一次（手写的 `**不解算**` 原样显示在页面上）。
    """
    for name in ("fig3d_viewer.html", "out/c/fig3d_viewer_offline.html"):
        text = (SPIKE / name).read_text(encoding="utf-8")
        body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S | re.I)
        body = re.sub(r"<style\b.*?</style>", "", body, flags=re.S | re.I)
        assert "**" not in body, f"{name} 的可见文案里有 markdown 星号"


# ------------------------------------------------------------------ mplot3d 取证记录


def test_mpl3d_report_is_self_consistent():
    """`a_report.json` 是 (a) 路线的原始记录：13 变体 × 3 格式，同进程 sha256 必须自洽。"""
    p = OUT / "a_report.json"
    if not p.is_file():
        pytest.skip("还没跑过 spike_a_mpl3d.py（见 docs/FIG3D-FEASIBILITY.md §3.0）")
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert len(rec) >= 12, f"变体数 {len(rec)} 少于文档写的 13"
    for r in rec:
        assert r["t_run1_s"] > 0 and r["t_run2_s"] > 0
        assert set(r["sha_run1"]) == set(r["sha_run2"]), f"{r['variant']} 两次格式不一致"
        assert r["reproducible"] is True, f"{r['variant']} 同进程不可复现：{r['diff_formats']}"
        assert r["diff_formats"] == []
        for name, h in r["sha_run1"].items():
            assert len(h) == 64 and int(h, 16) >= 0, f"{name} 不是 sha256：{h!r}"
        # 三格式齐全（`v13` 走的是现成的 preview 函数，也是三格式）
        for ext in FORMATS:
            assert any(n.endswith("." + ext) for n in r["bytes"]), \
                f"{r['variant']} 缺 {ext} 的体积记录"


def test_mpl3d_cross_process_records_agree():
    """跨进程取证：crossA / crossB 两份 sha256 必须逐键相同（含 SVG 与 PDF）。"""
    a, b = OUT / "crossA.json", OUT / "crossB.json"
    if not (a.is_file() and b.is_file()):
        pytest.skip("还没跑过 spike_a_mpl3d.py --cross --cross-dir spikes/fig3d/out")
    ra = json.loads(a.read_text(encoding="utf-8"))
    rb = json.loads(b.read_text(encoding="utf-8"))
    assert len(ra) == len(rb) and ra, "两份跨进程记录条数不一致"
    diff_all = []
    for x, y in zip(ra, rb):
        assert x["variant"] == y["variant"]
        diff = [k for k in sorted(set(x["sha_run1"]) | set(y["sha_run1"]))
                if x["sha_run1"].get(k) != y["sha_run1"].get(k)]
        if diff:
            diff_all.append((x["variant"], diff))
    assert not diff_all, f"跨进程不一致（mplot3d 排序不稳）：{diff_all}"

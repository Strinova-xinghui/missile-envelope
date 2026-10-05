# -*- coding: utf-8 -*-
"""图2（β–γ 能力平面）的出图契约：字节可复现、自适应轴、图注齐备。

与 `test_figures_repro.py` 平行的另一套 —— 图1 与图2 的版式元素不同（图2 有等 `n*` 线族、
象限底色、散点配色），所以各自钉自己的契约。
"""

import hashlib
import inspect
from pathlib import Path

import pytest

from missile_sim import bg, engine, figures, pool, spec

ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = ROOT / "figures"
TMP = ROOT / ".tmp_test" / "figures_bg"
#: `BASE_COLOR` 的小写十六进制（matplotlib 写进 SVG 时统一小写）—— **绿点的机器指纹**。
GREEN_HEX = figures.BASE_COLOR.lower()


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def rows():
    return bg.rows()


def test_bg_axis_is_adaptive_and_contains_all_points(rows):
    """轴范围必须把全部点包住并留出边距（散点与象限角标要地方）。"""
    ax = figures.bg_axis(rows)
    x0, x1 = ax.xlim
    y0, y1 = ax.ylim
    assert x0 < min(r.beta for r in rows) < x1
    assert y0 < min(r.ginv for r in rows) < y1
    assert x0 < max(r.beta for r in rows) < x1
    assert y0 < max(r.ginv for r in rows) < y1
    # 上边距要够：最上面的点（120A, ginv≈0.01869）不能贴着框
    span = max(r.ginv for r in rows) - min(r.ginv for r in rows)
    assert y1 - max(r.ginv for r in rows) > 0.05 * span
    assert ax.x_major > 0 and ax.x_minor > 0 and ax.y_major > 0 and ax.y_minor > 0
    assert ax.x_minor < ax.x_major and ax.y_minor < ax.y_major


def test_bg_axis_rejects_empty():
    with pytest.raises(ValueError):
        figures.bg_axis([])


def test_bg_axis_handles_a_single_missile():
    """只画一型时范围塌成一点 —— 必须靠最小值兜住，不能出现零宽度轴。"""
    ax = figures.bg_axis(bg.rows(["PL-12"]))
    assert ax.xlim[1] > ax.xlim[0] and ax.ylim[1] > ax.ylim[0]


def test_bg_axis_ticks_follow_the_overridden_range(rows):
    """覆盖范围后，**刻度必须按最终范围现算**（不是沿用弹池跨度算出来的那个）。

    回归判据（2026-10-04 真事故）：`ginv` 的刻度是按弹池跨度（0.0095）算的
    `y_major = 0.0025`，一旦范围被覆盖成 `3000~3300`，matplotlib 生成
    `300/0.0025 = 12 万`个主刻度位、次刻度 60 万个 ⇒ `MemoryError: 536 GiB`。
    """
    ax = figures.bg_axis(rows, ylim=(3000.0, 3300.0))
    assert ax.ylim == (3000.0, 3300.0)
    n_major = (ax.ylim[1] - ax.ylim[0]) / ax.y_major
    assert 2.0 <= n_major <= 20.0, f"刻度位 {n_major:.0f} 个（步长 {ax.y_major:g}），量级不对"
    ax2 = figures.bg_axis(rows, xlim=(2000.0, 4000.0), ylim=(0.008, 0.022))
    assert ax2.xlim == (2000.0, 4000.0) and ax2.ylim == (0.008, 0.022)
    assert (ax2.ylim[1] - ax2.ylim[0]) / ax2.y_minor <= 100.0
    with pytest.raises(ValueError):
        figures.bg_axis(rows, ylim=(3300.0, 3000.0))       # 反了就当场炸，不画空图


def test_bg_subtitle_keeps_only_the_reference_condition_and_mach():
    """用户 2026-10-04 口径：副标题**只留参考工况**，大气参数**只给马赫数**。

    两条都要钉住（缺一不可）：
    * 参考工况必须写着 —— `n*` 依赖动压，不写就没法比；
    * `q / f(M) / F(M)` 三个大气参数与「机动惩罚比 R 取 n = …G」**都不许出现**。
      后半句用户已在侧边对话里核实为**无效表述**：临界过载是从图上那族等 `n*` 线读出来的，
      不是钉一个指定的 `n`。
    """
    _a, _s, mach, _q, _f, _cap = bg.reference()
    text = figures.bg_subtitle(alt_m=10_000.0, speed_ms=800.0, mach=mach)
    for token in ("参考工况", "10 km", "800 m/s", "Ma 2.66"):
        assert token in text, f"副标题少了 {token!r}：{text}"
    for banned in ("132.4 kPa", "kPa", "0.3762", "1.1663", "机动惩罚比", "20G",
                   "q ", "f ", "F "):
        assert banned not in text, f"副标题不该再出现 {banned!r}：{text}"
    # 参数表也只留三个（alt / speed / mach）—— 少一个多一个都说明口径漂了
    import inspect
    assert list(inspect.signature(figures.bg_subtitle).parameters) == [
        "alt_m", "speed_ms", "mach"], inspect.signature(figures.bg_subtitle)


def test_label_offsets_cover_the_whole_pool():
    """标签偏移必须覆盖池里每一型 —— 漏了会静默用默认偏移，可能压在别的点上。"""
    missing = [k for k in pool.names() if k not in figures.BG_LBL_OFFSETS]
    assert not missing, f"这些型号没有标签偏移：{missing}"


def test_nstar_levels_are_the_agreed_17_level_set():
    """等 `n*` 线的层集合：**5~50G 共 17 条**，三段密度不同 —— 逐值钉死。

    用户 2026-10-05 口径：「12G 到 20G 直接更密一点，就按原来的 1G 的密度来，其余部分你看怎样
    过渡更合理」⇒ 过渡由 Lead 定为下面这一套：12~20 逐 1G；低端 `5, 10` 粗一档；
    高端 `25, 30, 35, 40, 45, 50` 每 5G（γ ∝ n*²，越往上越散）。

    历史：**旧是参考图那套 14~20 共 7 条**（`bg.REF_FIGURE_NSTAR_LEVELS`）；2026-10-05 先改成
    `(5,10,…,50)` 每 5G 共 10 条，随后细化为本 17 条。
    图例文案**从元组现算**（`add_bg_header` 里 `LEGEND_BG_NSTAR` 的 lo/hi/n），所以这里只钉
    元组本身 + 文案确实跟着算出来，**别在别处再钉一遍数字**。
    """
    lv = figures.BG_NSTAR_LEVELS
    assert lv == (5.0, 10.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0,
                  25.0, 30.0, 35.0, 40.0, 45.0, 50.0), ("层集合被改动了（逐值比对）", lv)
    assert list(lv) == sorted(lv) and len(set(lv)) == len(lv), lv
    assert len(lv) == 17, lv
    assert min(lv) == 5.0 and max(lv) == 50.0, lv
    # 三段密度：12~20 逐 1G（用户口径的核心）；<12 与 >20 各自粗化
    dense = [n for n in lv if 12.0 <= n <= 20.0]
    assert dense == [12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0], dense
    assert all(b - a == 1.0 for a, b in zip(dense, dense[1:])), ("12~20 必须逐 1G", dense)
    assert [n for n in lv if n < 12.0] == [5.0, 10.0], lv
    assert [n for n in lv if n > 20.0] == [25.0, 30.0, 35.0, 40.0, 45.0, 50.0], lv
    # 图例文案是**算出来的**（不是第二处硬编码）：改元组它就跟着变
    text = figures.LEGEND_BG_NSTAR.format(lo=min(lv), hi=max(lv), n=len(lv))
    assert "共 17 条" in text and "5~50" in text, text
    # ⚠ 判"旧口径残留"要连"共"一起写：单查 `7 条` 会被 `17 条` 误伤（真踩过）
    assert "14~20" not in text and "共 10 条" not in text and "共 7 条" not in text, \
        ("文案残留旧口径", text)


def _in_box_levels(lv, ax_spec, q_pa, f_mach, cap_f) -> list:
    """**几何定义**（不是抄实现）：哪些线真的穿过轴矩形。

    `ginv = m·β` 与 `β∈[x0,x1] × ginv∈[y0,y1]` 有交点 ⟺ `max(x0, y0/m) < min(x1, y1/m)`。
    穿过才该有标签 —— 落在框外的线打了标签也看不见（旧实现只看下边界，给"在框上方"的线
    也画了一堆贴上边框的假标签，实测 30/40/50 三个坐标完全相同）。
    """
    out = []
    for n in lv:
        m = (n * bg.G0 / q_pa) ** 2 * (cap_f / f_mach)
        x0, x1 = ax_spec.xlim
        y0, y1 = ax_spec.ylim
        if max(x0, y0 / m) < min(x1, y1 / m):
            out.append(float(n))
    return out


def _naive_bottom_only(lv, ax_spec, q_pa, f_mach, cap_f) -> list:
    """**旧实现的错判据**（只看下边界）—— 反证用，不许在实现里复活。

    `m·x0 ≥ y0 or m·x1 > y0` 对"整条在框**上方**"的陡线也为真 ⇒ 会给不存在的线打标签
    （实测 30/40/50 三个标签坐标完全相同、bbox 互压）。
    """
    out = []
    x0, x1 = ax_spec.xlim
    y0 = ax_spec.ylim[0]
    for n in lv:
        m = (n * bg.G0 / q_pa) ** 2 * (cap_f / f_mach)
        if (m * x0 >= y0) or (m * x1 > y0):
            out.append(float(n))
    return out


def test_visibility_is_a_real_segment_rectangle_intersection():
    """可见性判据必须是**线段–矩形真求交（双边）**：三窗逐值 + 反证 + 陡线端点列表。

    * 三窗：默认 11 弹池 / 全目录 159 枚 / 单弹 PL-12；
    * 三条路径互相对齐：**真的画一遍的标签集合** == `_in_box_levels()`（几何定义）
      == `figures._nstar_span_in_box()`（实现里的 helper）；
    * **反证**：换回旧的"只看下边界"必须**多出**整条在框上方的陡线（默认窗多 `25~50`、
      全目录窗多 `50`）—— 这正是修掉的那个 bug，判据没牙的话这条会红；
    * 顺带把 `25/30/40/50` 在三窗里的 β 区间与判定 print 出来（回报要用），并钉住三窗条数
      （8 / 15 / 2）。
    """
    import types

    import matplotlib.pyplot as plt

    from missile_sim import catalog

    _a, _s, _mach, q_pa, f_mach, cap_f = bg.reference()
    lv = figures.BG_NSTAR_LEVELS
    miss = catalog.load()["missiles"]

    def row(b, g):
        return types.SimpleNamespace(beta=b, ginv=g)

    windows = {
        "默认 11 弹池": (figures.bg_axis(bg.rows()), [(r.beta, r.ginv) for r in bg.rows()]),
        "全目录 159 枚": (figures.bg_axis([row(m["bc"], m["ginv"]) for m in miss]),
                          [(m["bc"], m["ginv"]) for m in miss]),
        "单弹 PL-12": (figures.bg_axis([row(m["bc"], m["ginv"]) for m in miss
                                        if m["key"] == "PL-12"]),
                       [(m["bc"], m["ginv"]) for m in miss if m["key"] == "PL-12"]),
    }
    counted = {}
    for name, (ax_spec, cloud) in windows.items():
        want = _in_box_levels(lv, ax_spec, q_pa, f_mach, cap_f)
        # 路径②：实现里的 helper 必须与几何定义一致
        got_helper = []
        for n in lv:
            m = (n * bg.G0 / q_pa) ** 2 * (cap_f / f_mach)
            _xa, _xb, span = figures._nstar_span_in_box(m, ax_spec.xlim, ax_spec.ylim)
            if span > 0:
                got_helper.append(float(n))
        assert want == got_helper, (name, want, got_helper)
        # 路径③：真的画一遍，标签必须正好是 want
        fig = plt.figure(figsize=(12.0, 6.8), dpi=110)
        ax = fig.add_subplot(111)
        try:
            ax.set_xlim(*ax_spec.xlim)
            ax.set_ylim(*ax_spec.ylim)
            figures._bg_nstar_lines(ax, ax_spec, lv, q_pa, f_mach, cap_f, cloud=cloud)
            drawn = sorted(float(t.get_text().split("=")[1]) for t in ax.texts
                           if t.get_text().startswith("$n^*$="))
            assert drawn == sorted(want), (name, drawn, want)
        finally:
            plt.close(fig)
        # 反证：旧判据必须与真求交不同（否则这条判据是橡皮图章）
        extra = sorted(set(_naive_bottom_only(lv, ax_spec, q_pa, f_mach, cap_f)) - set(want))
        assert extra, f"{name}：旧判据竟然和真求交一样 ⇒ 反证失效"
        print("  [可见性] %-12s 真交集 %s" % (name, [int(v) for v in want]))
        print("  %-22s 旧「只看下边界」多出 %s" % ("", [int(v) for v in extra]))
        counted[name] = [int(v) for v in want]
        for n in (25.0, 30.0, 40.0, 50.0):
            m = (n * bg.G0 / q_pa) ** 2 * (cap_f / f_mach)
            xa, xb, span = figures._nstar_span_in_box(m, ax_spec.xlim, ax_spec.ylim)
            print("     n*=%2g 需 β∈[%.1f, %.1f] 框内 β∈[%.1f, %.1f] 长度=%9.1f %s"
                  % (n, ax_spec.ylim[0] / m, ax_spec.ylim[1] / m, xa, xb, span,
                     "可见" if span > 0 else "不可见"))
    # 三窗条数钉住：数不对说明可见性又漂了
    assert counted["默认 11 弹池"] == [13, 14, 15, 16, 17, 18, 19, 20], counted
    assert counted["全目录 159 枚"] == [10, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                                        25, 30, 35, 40, 45], counted
    assert counted["单弹 PL-12"] == [18, 19], counted


def test_every_line_in_the_box_gets_exactly_one_label():
    """**每一层都打标签**（用户 2026-10-05：「1G 一根没错，但除了 20G 都看不到对应的 G 值了」）。

    判据落在 **artist** 上：先钉"17 条线都画了"，再钉**标签集合 == 框内线集合**（不重不漏）。
    `BG_NSTAR_LABEL_STEP` 默认必须是 `None`（全打）；给数就退化成"只打整数倍"（调试口子）。
    """
    import matplotlib.pyplot as plt

    assert figures.BG_NSTAR_LABEL_STEP is None, \
        "默认必须全打（用户口径：每根线都要能读出 G 值）"
    rows = bg.rows()
    ax_spec = figures.bg_axis(rows)
    _a, _s, _mach, q_pa, f_mach, cap_f = bg.reference()
    lv = figures.BG_NSTAR_LEVELS
    want = _in_box_levels(lv, ax_spec, q_pa, f_mach, cap_f)
    # 默认 11 弹池：框内就是 13~20（5/10/12 在框下方；25~50 在框上方）
    assert want == [13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0], want

    fig = plt.figure()
    ax = fig.add_subplot(111)
    try:
        figures._bg_nstar_lines(ax, ax_spec, lv, q_pa, f_mach, cap_f,
                                cloud=[(r.beta, r.ginv) for r in rows])
        assert len(ax.lines) == len(lv), ("17 条线每条都要画", len(ax.lines), len(lv))
        labels = sorted(t.get_text() for t in ax.texts if t.get_text().startswith("$n^*$="))
        assert labels == sorted(f"$n^*$={n:g}" for n in want), (labels, want)
    finally:
        plt.close(fig)


def test_nstar_labels_never_overlap():
    """**标签两两不重叠**（放开全打之后唯一的风险）—— 判据用 renderer 量的真实 bbox。

    两个池子都查，第二个才是压力档：
    * **默认 11 弹池**：框内 8 条（13~20），最密的一段；
    * **全目录 159 枚**：β 下探到 530、ginv 下探到 0.002146 ⇒ 框内线多得多（真正的挤）。

    重叠了**不许**退回"只打一部分"（用户要每根都能读 G 值），要调摆位/字号 —— 见
    `figures._place_nstar_labels`（沿各自直线错位 + 上下错开，像素级贪心）。
    """
    import types

    import matplotlib.pyplot as plt

    from missile_sim import catalog

    _a, _s, _mach, q_pa, f_mach, cap_f = bg.reference()
    lv = figures.BG_NSTAR_LEVELS
    pools = {"默认 11 弹池": [(r.beta, r.ginv) for r in bg.rows()]}
    pools["全目录 159 枚"] = [(m["bc"], m["ginv"])
                              for m in catalog.load()["missiles"]]
    report = {}
    for name, cloud in pools.items():
        rows_like = [types.SimpleNamespace(beta=b, ginv=g) for b, g in cloud]
        ax_spec = figures.bg_axis(rows_like)
        fig = plt.figure(figsize=(12.0, 6.8), dpi=110)
        ax = fig.add_subplot(111)
        try:
            ax.set_xlim(*ax_spec.xlim)
            ax.set_ylim(*ax_spec.ylim)
            figures._bg_nstar_lines(ax, ax_spec, lv, q_pa, f_mach, cap_f, cloud=cloud)
            fig.canvas.draw()
            ren = fig.canvas.get_renderer()
            boxes = [(t.get_text(), t.get_window_extent(ren)) for t in ax.texts
                     if t.get_text().startswith("$n^*$=")]
            assert boxes, f"{name}：一个标签都没有"
            # 只该给框内的线打标签；数量与几何定义一致
            assert len(boxes) == len(_in_box_levels(lv, ax_spec, q_pa, f_mach, cap_f)), \
                (name, [t for t, _ in boxes])
            bad, gaps = [], []
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    a, b = boxes[i][1], boxes[j][1]
                    if min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0):
                        bad.append((boxes[i][0], boxes[j][0]))
                    gaps.append((max(a.x0, b.x0) - min(a.x1, b.x1),
                                 max(a.y0, b.y0) - min(a.y1, b.y1)))
            assert not bad, f"{name}：{len(bad)} 对标签重叠：{bad[:5]}"
            # 不只是"不重叠"：每对之间至少在某一轴上留出 `NSTAR_LABEL_GAP_PX` 的间隙
            # （bbox 贴到 1~2 px 时人眼仍是糊的；留 0.5 px 量测余量）
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    a, b = boxes[i][1], boxes[j][1]
                    gx = max(a.x0, b.x0) - min(a.x1, b.x1)
                    gy = max(a.y0, b.y0) - min(a.y1, b.y1)
                    assert max(gx, gy) >= figures.NSTAR_LABEL_GAP_PX - 0.5, \
                        (name, boxes[i][0], boxes[j][0], gx, gy)
            # 每个标签都必须在轴框内（不出框）
            frame = ax.get_window_extent(ren)
            for text, bb in boxes:
                assert (bb.x0 >= frame.x0 and bb.y0 >= frame.y0
                        and bb.x1 <= frame.x1 and bb.y1 <= frame.y1), (name, text)
            tight = sorted(gaps, key=lambda g: max(g[0], g[1]))[0]
            report[name] = (len(boxes), round(tight[0], 1), round(tight[1], 1))
        finally:
            plt.close(fig)
    # 记下实测（回报里要写）：标签数 + 最紧那一对的水平/垂直间隙（px）
    print("  n* 标签避让实测（标签数, 最紧水平间隙 px, 最紧垂直间隙 px）：", report)
    assert report["默认 11 弹池"][0] == 8, report
    assert report["全目录 159 枚"][0] >= 12, ("全目录池应当有更多框内线", report)


def test_no_quadrant_shading_anymore(tmp_path):
    """用户否掉了四象限底色（红区绿区）：阈值常量、填充函数、图例色标全删。

    只留等 `n*` 线 + 散点 —— 那两个阈值是"对着 11 弹池目测定的"，换个池子就失去意义，
    留在图上反而会被当成有物理含义的分界。

    断言直接落在**产物**上：底色若钻回来，SVG 里必然出现那两个填充色；
    "双优/双差"两个图例词也必然出现在文字里。
    """
    for name in ("BG_GOOD_BETA", "BG_GOOD_GAMMA", "BG_BAD_BETA", "BG_BAD_GAMMA",
                 "BG_GOOD_FILL", "BG_GOOD_EDGE", "BG_BAD_FILL", "BG_BAD_EDGE",
                 "BG_GOOD_TEXT", "BG_BAD_TEXT"):
        assert not hasattr(figures, name), f"象限底色应该已经删掉，还剩 {name}"
    assert not hasattr(figures, "_bg_quadrants"), "填充函数应该已经删掉"

    out = figures.plot_bg_plane(rows=bg.rows(), out_base=tmp_path / "noquad",
                                formats=("png", "pdf", "svg"))
    assert len(out) == 3, out
    svg = next(p for p in out if p.suffix == ".svg").read_text(encoding="utf-8")
    for color in ("#E8F5E9", "#FDECEA", "#2E7D32", "#C62828",
                  "e8f5e9", "fdecea"):
        assert color not in svg, f"底色又回来了：出现 {color}"
    for word in ("双优", "双差"):
        assert word not in svg, f"象限图例又回来了：出现 {word!r}"
    # 该留的还在
    assert "n^*" in svg or "n*" in svg
    # 图例不许再报弹池规模（用户 2026-10-04 口径：那条图例项不画了）
    assert "弹池" not in svg, "图例里不该再出现「弹池 … 型」"
    assert "气泡大小" not in svg, "气泡大小编码已按用户口径取消（点径与图1 统一）"


def test_bg_footnotes_and_notes_are_not_drawn_into_the_figure(tmp_path):
    """用户 2026-10-04 口径：**坐标轴下方的批注全部移出图外**（文本改由页面渲染）。

    判据落在**产物**上：`BG_FOOTNOTES` / `BG_READ_NOTE` / `bg_scan_def()` / `bg_scan_note()`
    的正文一个字都不许出现在图里；而它们作为文本仍然可取（页面要用）。
    """
    out = figures.plot_bg_plane(rows=bg.rows(), out_base=tmp_path / "nofoot",
                                formats=("svg",))
    svg = Path(out[0]).read_text(encoding="utf-8")
    notes = ([*figures.BG_FOOTNOTES, figures.BG_READ_NOTE,
              figures.bg_scan_def(932.57), figures.bg_scan_note(False),
              figures.bg_scan_note(True)])
    for line in notes:
        assert line.strip(), "文本出处不该是空的"
        # 取一个足够长的特征片段，避免"因为太短刚好没出现"的假绿
        probe = line.strip()[:24]
        assert probe not in svg, f"这条批注又画进图里了：{probe!r}"
    # 逐条留一个可核对的样本（说明这些文本确实"存在但不在图上"）
    assert "真空等效" in figures.plane_notes(11)[0]
    assert "未跑仿真层" in figures.bg_scan_note(False)


def test_text_sources_avoid_mathtext_delimiters():
    """`wrap_lines()` 会把一对 `$` 拆到两行，mathtext 见到落单的 `$` 就原样输出。

    ⚠ 这几条文本**已不再画进图**（见上一条），但页面渲染同样不能被 `$` 拆行，
    所以这条判据保留 —— 它管的是**文本来源**的卫生，不是"图里有没有"。
    """
    for line in [*figures.BG_FOOTNOTES, *figures.PLANE_FOOTNOTES, figures.BG_READ_NOTE,
                 figures.bg_scan_def(932.57), figures.bg_scan_note(True),
                 figures.bg_scan_note(False)]:
        assert line.count("$") == 0, f"这些文本不能写 $…$：{line[:40]}"
    # 图例那几条短，不会被折行，允许用数学
    assert "$n^*$" in figures.LEGEND_BG_NSTAR


def test_plot_bg_plane_needs_data():
    with pytest.raises(ValueError):
        figures.plot_bg_plane(rows=[], out_base=TMP / "empty")


def test_plot_bg_plane_is_byte_reproducible_in_three_formats(rows, tmp_path):
    """两遍出图，png / pdf / svg 都必须逐字节一致（时间戳与 SVG id 已归一）。"""
    a = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "a", highlight="PL-12")
    b = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "b", highlight="PL-12")
    assert len(a) == 3 and len(b) == 3
    for x, y in zip(sorted(a), sorted(b)):
        assert Path(x).suffix == Path(y).suffix
        assert _sha(x) == _sha(y), f"{Path(x).suffix} 不可复现"
        assert Path(x).stat().st_size > 5_000


def test_plot_bg_plane_defaults_build_a_real_figure(rows, tmp_path):
    """默认参数（无 title/subtitle/axis）必须能自己撑起来 —— 编排层只传数据。"""
    out = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "d", formats=("png",))
    assert len(out) == 1 and Path(out[0]).suffix == ".png"
    assert Path(out[0]).stat().st_size > 50_000


def test_plot_bg_plane_accepts_an_explicit_axis(rows, tmp_path):
    ax = spec.AxisSpec(xlim=(2400.0, 3900.0), ylim=(40.0, 110.0),
                       x_major=500.0, x_minor=100.0, y_major=20.0, y_minor=4.0)
    out = figures.plot_bg_plane(rows=rows, out_base=tmp_path / "x", axis=ax,
                                formats=("png",))
    assert len(out) == 1


def test_bg_points_are_uniform_and_the_baseline_is_green(rows):
    """图2 的点径 = 图1 的 `POINT_SIZE`（不再按 ΔV 缩放）；基准弹的**点与标签**都绿；**无空心环**。

    2026-10-01 用户口径：① 旧 `BG_BUBBLE` 让最大的"红气泡"直径到 24.5 pt，而标签只有 9.5 pt，
    与图1（统一点径 9.44 pt）不一致 ⇒ 点大小统一；② 选中态只用**颜色**表达（点与标签同色）
    ⇒ 空心环去掉。

    判据落在 **artist** 上（不看像素）：只有一个散点集合、尺寸集合只有 `POINT_SIZE`、
    点与标签的颜色都恰好一处绿。
    """
    from matplotlib.colors import to_rgba
    import matplotlib.pyplot as plt

    i_base = [r.key for r in rows].index("PL-12")
    red = to_rgba(figures.POINT_COLOR)[:3]
    red_lbl = to_rgba(figures.LBL_COLOR)[:3]
    green = to_rgba(figures.BASE_COLOR)[:3]

    fig = plt.figure()
    ax = fig.add_subplot(111)
    try:
        figures._bg_bubbles(ax, rows, highlight="PL-12")
        assert len(ax.collections) == 1, f"空心环应该已经删掉，还剩 {ax.collections}"
        sc = ax.collections[0]
        assert set(sc.get_sizes()) == {figures.POINT_SIZE}, set(sc.get_sizes())
        faces = [to_rgba(c)[:3] for c in sc.get_facecolors()]
        assert len(faces) == len(rows)
        assert faces[i_base] == green, f"基准弹的点必须涂绿，实际 {faces[i_base]}"
        assert all(c == red for i, c in enumerate(faces) if i != i_base), faces
        tcol = [to_rgba(t.get_color())[:3] for t in ax.texts]
        assert len(tcol) == len(rows), (len(tcol), len(rows))
        assert tcol[i_base] == green, f"基准弹的标签也要绿，实际 {tcol[i_base]}"
        assert all(c == red_lbl for i, c in enumerate(tcol) if i != i_base), tcol
    finally:
        plt.close(fig)
    assert "气泡" not in figures.LEGEND_BG_POINTS
    assert "气泡" not in figures.BG_FOOTNOTES[0]


def test_legend_text_of_the_baseline_is_green_too():
    """图例里"基准弹"那一条的**文字**也涂绿（用户 2026-10-01 追加"标签也绿"）。"""
    from matplotlib.colors import to_rgba
    import matplotlib.pyplot as plt

    green = to_rgba(figures.BASE_COLOR)[:3]
    fig = plt.figure()
    try:
        figures.add_bg_header(fig, title="t", highlight="PL-12", n_points=11)
        cols = {t.get_text(): to_rgba(t.get_color())[:3] for t in fig.legends[0].get_texts()}
        assert cols["PL-12"] == green, cols
        assert all(c != green for txt, c in cols.items() if txt != "PL-12"), cols
    finally:
        plt.close(fig)


def test_bg_legend_has_no_pool_size_entry():
    """用户 2026-10-04：图2 图例里**不留**「弹池 N 型」（`points_legend=False`）。

    `add_bg_header` 的开关要真的生效（默认仍是 True —— 图1 的 `add_header` 口径不动）。
    """
    import matplotlib.pyplot as plt

    fig = plt.figure()
    fig2 = plt.figure()
    try:
        figures.add_bg_header(fig, title="t", n_points=11, points_legend=False)
        words = " ".join(t.get_text() for t in fig.legends[0].get_texts())
        assert "弹池" not in words, words
        assert "n" in words, "等 n* 线那一条必须还在：" + words
        figures.add_bg_header(fig2, title="t", n_points=11)
        words2 = " ".join(t.get_text() for t in fig2.legends[0].get_texts())
        assert "弹池 11 型" in words2, words2
    finally:
        plt.close(fig)
        plt.close(fig2)


def test_no_baseline_switch_is_typed_wired_and_never_reaches_the_cache_key():
    """`show_baseline` 这条链：**有类型注解** + CLI/JSON 通 + **不进 `engine.cache_key()`**。

    仓库里的老坑：请求类上一个字段没写注解 ⇒ dataclass 不当它是字段 ⇒ CLI 传进来的值被
    `dataclasses.replace()` **静默丢掉**。所以这条判据同时盯注解、`_*_FIELDS`、CLI `dest`
    与缓存键四件事。
    """
    from dataclasses import fields

    from missile_sim import cli, workflow

    for cls in (workflow.PlaneRequest, workflow.BgRequest):
        f = {x.name: x for x in fields(cls)}["show_baseline"]
        assert f.type in (bool, "bool"), f"{cls.__name__}.show_baseline 必须有 bool 注解，实际 {f.type!r}"
        assert f.default is True, f"{cls.__name__}.show_baseline 默认必须为 True（给定工况照旧显示）"
    assert "show_baseline" in cli._PLANE_FIELDS and "show_baseline" in cli._BG_FIELDS
    args = cli.build_parser().parse_args(["--no-baseline"])
    assert cli._request(args, workflow.PlaneRequest, cli._PLANE_FIELDS).show_baseline is False
    assert cli._request(args, workflow.BgRequest, cli._BG_FIELDS,
                        cli._BG_ALIASES).show_baseline is False
    # 不给就是 True（WebUI / 默认出图那条路必须仍然显示基准弹）
    plain = cli.build_parser().parse_args([])
    assert cli._request(plain, workflow.PlaneRequest, cli._PLANE_FIELDS).show_baseline is True
    # ⚠ 画法开关不许进缓存键：它是"怎么画"，不是"算什么"
    assert "show_baseline" not in inspect.getsource(engine.cache_key)
    assert "show_baseline" not in inspect.signature(engine.cache_key).parameters


def test_run_plane_and_run_bg_honour_the_show_baseline_switch(tmp_path):
    """端到端对照（**不跑求解器**）：同一套输入，只翻这个开关，图上绿点从有到无。

    顺带钉住"给定计算 = 有绿点、无输入形态 = 全红"这件行为，以及图1 副标题里的
    「基准弹 PL-12」跟着开关一起消失。
    """
    from missile_sim import workflow
    from missile_sim.spec import Scene

    def green_count(paths):
        svg = next(p for p in paths if str(p).endswith(".svg"))
        return Path(svg).read_text(encoding="utf-8").lower().count(GREEN_HEX)

    # ---- 图1：只出散点（`with_iso=False` ⇒ 不解算，秒级）------------------
    for flag in (True, False):
        req = workflow.PlaneRequest(scene=Scene(), with_iso=False, tag=f"bl{int(flag)}",
                                    formats=("svg",), show_baseline=flag,
                                    figure_dir=tmp_path, result_dir=tmp_path)
        out = workflow.run_plane(req)
        svg = Path(out["_paths"]["figures"][0]).read_text(encoding="utf-8")
        n = green_count(out["_paths"]["figures"])
        if flag:
            assert n > 0, "给定时必须绿标基准弹"
            assert "基准弹 PL-12" in svg, "副标题应当写基准弹"
        else:
            assert n == 0, f"无基准弹形态里不该有任何绿点，实测 {n} 处"
            assert "基准弹" not in svg, "副标题也不该再写基准弹"

    # ---- 图2：不跑仿真层（`with_scan=False`）-----------------------------
    for flag in (True, False):
        req = workflow.BgRequest(scene=Scene(), with_scan=False, tag=f"bl{int(flag)}",
                                 formats=("svg",), show_baseline=flag,
                                 figure_dir=tmp_path, result_dir=tmp_path)
        out = workflow.run_bg(req)
        svg = Path(out["_paths"]["figures"][0]).read_text(encoding="utf-8")
        n = green_count(out["_paths"]["figures"])
        if flag:
            assert n > 0, "给定时必须绿标基准弹"
        else:
            assert n == 0, f"无基准弹形态里不该有任何绿点，实测 {n} 处"
        # 两个形态都不许有图下批注（2026-10-04 口径），也都不许有「机动惩罚比」
        for line in figures.BG_FOOTNOTES:
            assert line[:24] not in svg, f"批注又进图了：{line[:24]!r}"
        assert "机动惩罚比" not in svg
        assert "参考工况" in svg and "Ma " in svg, "参考工况与马赫数必须留着"


def test_static_products_have_no_green_baseline_and_default_ones_do():
    """**成品级**对照判据（首页贴的就是 `_static`）：12 件里有 4 个 SVG 承载绿点信息。

    `_static`（无输入形态）= 一个绿点都没有；`_default`（给定工况）= 有。
    这条比"看 mtime/字节数"靠谱：内容对不对是唯一能证明"两个形态都按新口径重出过"的东西。
    """
    problems = []
    for family in ("bg_plane", "isotime_plane"):
        for form in ("static", "default"):
            p = FIG_DIR / f"fig_{family}_{form}.svg"
            if not p.is_file():
                problems.append(f"{p.name} 不存在 ⇒ 先跑 python scripts\\refresh_products.py")
                continue
            n = p.read_text(encoding="utf-8").lower().count(GREEN_HEX)
            if form == "static" and n:
                problems.append(f"{p.name} 里还有 {n} 处绿点（无基准弹形态必须全红）")
            if form == "default" and not n:
                problems.append(f"{p.name} 里没有绿点（给定工况必须绿标基准弹）")
    assert not problems, "\n".join(problems) + "\n  ⇒ 重出：python scripts\\refresh_products.py"

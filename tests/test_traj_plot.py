# -*- coding: utf-8 -*-
"""图3 出图层的**版面硬约束**（不是美化）。

这批缺陷的共同点是**静默**：图照样出得来、代码一个数都不报错，只有量"成品图上真实的
像素与矩形"才发现 —— 所以这里用 `save_formats` 探针在 `fig.canvas.draw()` **之后**量
renderer 的 bbox，而不是读我们自己的意图（`docs/PLAN-FIG3-TRAJECTORY.md` 的 D1~D11）：

* **D1 放大 inset 退化**：`set_aspect("equal", adjustable="box")` 的收缩只在 `draw()` 里
  发生，`get_position()` 在此之前返回的还是**设定值** —— 曾经出过"6.9 px 宽的紫竖线 +
  面板左边游离的 8 个 y 刻度"，而图例里还留着"放大"那一格。另一版把显示范围撑到十几倍大
  （放大倍率归零、框里一条几乎不动的线），同样不报错。
* **D2/D8 注记打架**：命中/脱靶那两条文案压在同一个点上（实测 1421.3 px²），脱靶工况还写着
  「命中 / 结束」，读起来自相矛盾。
* **D3 节点名说两遍**：`build_marks()` 的 note 自带节点名，旧版又拼了一遍图例前缀。
* **D4 线型与图例对不上**：`truncated` 段画的是实线，图例那一格却是虚线。
* **D5 markdown**：matplotlib 不解析 `**`，它把星号原样打出来（预览图脚注实测 2 处）。
* **D6 缺字形**：`⚠`(U+26A0) 在 Microsoft YaHei 里没有字形，出图时刷
  `Glyph 9888 ... missing from font` 并留一个豆腐块。
* **D7 竖排标签出框**：图例右边界那一列必然超 17.0 px，两个节点同刻时纵向错 10 pt 也躲不掉
  （实测重叠 578.8 px²）。

⚠ **两条与 matplotlib 3.11.1 有关的实测口径**（写断言时别踩）：

1. `set_aspect(..., adjustable="box")`、`apply_aspect()`、`get_tightbbox()` 都依赖 draw；
   `get_position()` 在 draw 之前**不是**最终值。
2. `Line2D.get_linestyle()` 对**元组**线型是**有损**的：`(0, (4, 2))` 与 `(0, (5, 3))`
   都返回 `'--'`。真实图案只在 `_unscaled_dash_pattern` 里（4/2 与 5/3 画出来不一样），
   所以"截断段用的是 `TRAJ_TRUNC_LS`"**不能**拿 `get_linestyle()` 比字符串。

产物一律写进 `.tmp_test/traj_plot/`，**不碰仓库里的 `figures/` 与 `results/`**。
"""

from __future__ import annotations

import hashlib
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt                                # noqa: E402
import numpy as np                                             # noqa: E402
import pytest                                                  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from missile_sim import figures, workflow                      # noqa: E402
from missile_sim.spec import Scene                             # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".tmp_test" / "traj_plot"
DPI = figures.SAVE_DPI                      # PNG 的 300 dpi
PAD = 3.0                                   # 允许的亚像素/抗锯齿误差
#: 注记**行框**允许压出俯视面板的余量（display px，fig dpi = 110）：
#: 行框含 ascent/descent 与 bbox 内边距，比墨迹大；命中点贴在面板顶边时注记只能往上让。
#: 实测 3.0 display px；D7 那种整行出界是 17.0，仍会被抓住。
LABEL_EDGE_SLACK = 6.0
#: 300 dpi 上"看得见"的下限（与 `figures.TRAJ_INSET_MIN_PX` 同一个口径）
MIN_PX = figures.TRAJ_INSET_MIN_PX


# ============================================================ 小组件：口径换算与度量


def _dash(ln) -> tuple:
    """线型**真实**图案。`get_linestyle()` 会把任何元组糊成 `'--'`（见模块 docstring）。"""
    pat = getattr(ln, "_unscaled_dash_pattern", None)
    if pat is None:                                              # 老版本兜底
        return tuple(matplotlib.lines._get_dash_pattern(ln.get_linestyle())[1] or ())
    return tuple(pat[1] or ())


def _dash_of(ls) -> tuple:
    return tuple(matplotlib.lines._get_dash_pattern(ls)[1] or ())


def _ov(a, b) -> float:
    """两个 bbox（`(x0, y0, w, h)`，display px）的重叠面积。"""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _pv(bb) -> tuple:
    return (bb[0], bb[1], bb[0] + bb[2], bb[1] + bb[3])


def _px300(disp_len: float, fig_dpi: float) -> float:
    """display px（figure dpi）→ **成品图**像素（300 dpi）。"""
    return float(disp_len) / float(fig_dpi) * DPI


def _purple_frame(fig, main_disp) -> tuple:
    """从 **Agg 缓冲区**里直接量紫框（**不经** `get_position()`）：`(w, h)` 单位 display px。

    口径：紫框的两条竖边在"每一列有几个紫像素"上给出最大值，两条横边在"每一行"上给出
    最大值 —— 取到这个最大值 80% 的行/列才算"边"，这样渲染在框上面的紫色标题
    （「放大 30–36 s」）不会被算进来。图例里的紫色把手在主轴**框外**，也被排除。
    """
    buf = np.asarray(fig.canvas.buffer_rgba()).astype(int)[:, :, :3]
    # ⚠ 用**色相**判紫、不比精确颜色：figure 只有 110 dpi，1 pt 的框线是抗锯齿混出来的
    #   （实测混成 (187,143,206)，离 `#8e44ad` 差 75/级），精确比色会一个像素都找不到。
    #   其它图元的颜色（teal / blue / orange / grey / 黑）都过不了"G 明显低于 R 和 B"。
    mask = ((buf[:, :, 2] - buf[:, :, 1] > 30) & (buf[:, :, 0] - buf[:, :, 1] > 20)
            & (buf[:, :, 1] < 220))
    h_img = mask.shape[0]
    x0, y0, x1, y1 = main_disp
    rows = slice(int(h_img - y1), int(h_img - y0))               # display y 向上，buffer 向下
    mask = mask[rows, int(x0):int(x1)]
    if not mask.any():
        return (0.0, 0.0)
    col, row = mask.sum(axis=0), mask.sum(axis=1)
    ce = np.nonzero(col >= 0.8 * col.max())[0]                   # 竖边：列计数 ≈ 框高
    re = np.nonzero(row >= 0.8 * row.max())[0]                   # 横边：行计数 ≈ 框宽
    return (float(ce.max() - ce.min() + 1), float(re.max() - re.min() + 1))


def _snapshot(fig, ren) -> dict:
    """在 `draw()` 之后把"版面事实"全量抓下来（测试只读这个 dict）。"""
    ax = fig.axes[0]
    mbb = ax.get_window_extent(ren)
    d = {"fig_dpi": float(fig.dpi), "fig_in": tuple(float(v) for v in fig.get_size_inches()),
         "main": ax.get_position().bounds,
         "main_disp": (float(mbb.x0), float(mbb.y0), float(mbb.x1), float(mbb.y1)),
         "texts": [(t.get_text(), tuple(float(v) for v in
                                        t.get_window_extent(renderer=ren).bounds))
                   for t in ax.texts],
         "lines": [{"label": ln.get_label(), "dash": _dash(ln), "color": str(ln.get_color()),
                    "marker": str(ln.get_marker()),
                    "bb": tuple(float(v) for v in
                                ln.get_window_extent(renderer=ren).bounds)}
                   for ln in ax.lines],
         "legend": [t.get_text() for t in (fig.legends[0].get_texts() if fig.legends else [])],
         # ⚠ 图例**把手**的线型也要抓：图例档是用代理线画在另一张画布上的，
         #   只比文字/label 的话「实线 转入crank」格配「虚线 转入crank」段也能过
         #   （复验 task-7 缺陷 A 就是这么漏掉的）。`legend_handles` 在 mpl 3.7+ 才改名。
         "legend_dash": {},
         "figtexts": [t.get_text() for t in fig.texts],
         "insets": [], "alt": None}
    if fig.legends:
        hs = getattr(fig.legends[0], "legend_handles",
                     getattr(fig.legends[0], "legendHandles", [])) or []
        d["legend_dash"] = {h.get_label(): _dash(h) for h in hs if h.get_label()}
    for ch in getattr(ax, "child_axes", ()):
        cbb = ch.get_window_extent(ren)
        ytl = [t.get_window_extent(renderer=ren) for t in ch.get_yticklabels() if t.get_text()]
        d["insets"].append({
            "frac": tuple(float(v) for v in ch.get_position().bounds),
            "disp": (float(cbb.x0), float(cbb.y0), float(cbb.x1), float(cbb.y1)),
            "xlim": tuple(float(v) for v in ch.get_xlim()),
            "ylim": tuple(float(v) for v in ch.get_ylim()),
            "n_ytick": len(ch.get_yticks()),
            "tick_gap": float(cbb.x0 - max((t.x1 for t in ytl), default=cbb.x0)),
            "title": ch.get_title(),
            # inset 的标题画在框**上方**（还是主轴的地盘）：主轴注记同样不许压上去
            "title_bb": (None if not ch.get_title() else
                         tuple(float(v) for v in ch.title.get_window_extent(renderer=ren).bounds)),
            # inset **自己**的刻度文字：x 轴标签太宽会互相压（看图发现的缺陷，见测试）。
            # 存 `(文字, 刻度位置, bbox)`：位置落在 `xlim`/`ylim` 内的刻度才会真被画出来，
            # 窗口外的刻度对象照样有文字、`get_visible()` 也是 True，按它筛会把没画的算进来。
            "xticks": [(t.get_text(), float(t.get_position()[0]),
                        tuple(float(v) for v in t.get_window_extent(renderer=ren).bounds))
                       for t in ch.get_xticklabels() if t.get_text()],
            "yticks": [(t.get_text(), float(t.get_position()[1]),
                        tuple(float(v) for v in t.get_window_extent(renderer=ren).bounds))
                       for t in ch.get_yticklabels() if t.get_text()]})
    if len(fig.axes) > 1:
        a1 = fig.axes[1]
        abb = a1.get_window_extent(ren)
        d["alt"] = {"disp": (float(abb.x0), float(abb.y0), float(abb.x1), float(abb.y1)),
                    "texts": [(t.get_text(), tuple(float(v) for v in
                                                   t.get_window_extent(renderer=ren).bounds))
                              for t in a1.texts]}
    return d


# ============================================================ 纯函数层（不跑求解器）


def test_plain_strips_markdown_emphasis():
    """`**x**` / `__x__` 在 matplotlib 里不是加粗，是**原样打出来的星号**（D5）。"""
    assert figures._plain("开机时刻用**一遍法**反求") == "开机时刻用一遍法反求"
    assert figures._plain("__a__ 与 **b**") == "a 与 b"
    assert figures._plain(None) == ""


def test_mark_label_names_the_outcome_for_the_end_node():
    """图例那一格叫「命中 / 结束」（一格管两种结局），**图上标注**必须二选一（D8）。"""

    class _M:
        name = "end"
        t_s = 90.0
        note = "脱靶 1152 m"

    assert figures.TRAJ_MARK_LABELS["end"] == "命中 / 结束"
    assert figures._mark_label(_M(), hit=True) == "命中"
    assert figures._mark_label(_M(), hit=False) == "结束"
    # 其它节点不受影响
    _M.name, _M.note = "launch", "发射"
    assert figures._mark_label(_M(), hit=False) == "发射"


def test_mark_text_never_says_a_node_name_twice():
    """`build_marks()` 的 note 自带节点名，旧版又拼了一遍图例前缀（D3）。"""

    class _M:
        name = "crank_start"
        t_s = 8.0
        note = "开始 crank 至 110°（9G）"

    txt = figures._mark_text(_M())
    assert txt.count("开始 crank") == 1
    assert txt.count("t=") == 1
    assert "110°（9G）" in txt

    _M.name, _M.note, _M.t_s = "seeker_on", "导引头开机 · R = 16 km", 34.46
    txt = figures._mark_text(_M(), extra="实际航向 110.3°")
    assert txt.count("导引头开机") == 1 and txt.count("t=") == 1
    assert "R = 16 km" in txt and "实际航向 110.3°" in txt

    _M.name, _M.note, _M.t_s = "launch", "发射", 8.0   # note == 图例名 ⇒ 只留一份
    assert figures._mark_text(_M()) == "发射 t=8.00 s"


def test_inset_px_matches_the_saved_300dpi_size():
    """`_inset_px` 是"看得见/看不见"的判据：槽位是**父轴 fraction**，少乘一次就判反（D1）。"""
    rect = (0.055, 0.415, 0.8, 0.385)
    w, h = figures._inset_px((0.1, 0.2, 0.3, 0.25), rect, fig_w=12.6, fig_h=9.2)
    assert w == pytest.approx(0.3 * 0.8 * 12.6 * DPI, rel=1e-9)
    assert h == pytest.approx(0.25 * 0.385 * 9.2 * DPI, rel=1e-9)
    assert w > MIN_PX and h > MIN_PX
    # 退化到一条线时必须被闸门挡住（否则就是那根 6.9 px 的紫竖线）
    w2, h2 = figures._inset_px((0.1, 0.2, 0.0002, 0.005), rect, fig_w=12.6, fig_h=9.2)
    assert w2 < MIN_PX and h2 < MIN_PX


def test_inset_slot_keeps_the_window_aspect_and_stays_in_the_panel():
    """框的**英寸比**必须等于窗口的数据跨度比 —— 这样两个方向的"米/英寸"才相等，
    也才不需要 `set_aspect()` 再收缩一次（那一次收缩就是 D1 的静默退化）。"""
    fig_w, fig_h = figures.TRAJ_FIG_SIZE
    xlim, zlim = (-45000.0, 8000.0), (-32000.0, 12000.0)
    rect = (0.055, 0.415, 0.726, 0.385)
    pts = [(0.0, 0.0), (1200.0, 900.0), (400.0, 1500.0)]         # 高而窄的放大窗口
    slot, wx, wz = figures._inset_slot(xlim, zlim, rect, (28.0, 36.0), pts,
                                       fig_w=fig_w, fig_h=fig_h)
    w_in = slot[2] * rect[2] * fig_w
    h_in = slot[3] * rect[3] * fig_h
    assert (w_in / h_in) == pytest.approx((wx[1] - wx[0]) / (wz[1] - wz[0]), rel=1e-9)
    assert 0.0 <= slot[0] and slot[0] + slot[2] <= 1.0
    assert 0.0 <= slot[1] and slot[1] + slot[3] <= 1.0
    # 窗口只由数据定：不能把显示范围撑到俯视面板的米/英寸（那等于没放大）
    assert (wz[1] - wz[0]) <= 3.0 * (max(p[1] for p in pts) - min(p[1] for p in pts))
    assert (wx[1] - wx[0]) <= 3.0 * (max(p[0] for p in pts) - min(p[0] for p in pts))


def test_truncated_segment_is_drawn_with_the_documented_dash_pattern():
    """`Segment.truncated` ⇒ 线型必须就是图例那一格用的 `TRAJ_TRUNC_LS`（D4）。"""

    class _Seg:
        def __init__(self, label, t0, t1, key, trunc):
            self.label, self.t0_s, self.t1_s = label, t0, t1
            self.color_key, self.truncated = key, trunc

    class _Run:
        rows = [{"t": float(i), "tx": float(i) * 100.0, "tz": float(i) * 50.0}
                for i in range(11)]
        segments = [_Seg("直飞", 0.0, 4.0, "grey", False),
                    _Seg("转入crank", 4.0, 10.0, "orange", True)]

    fig, ax = plt.subplots(figsize=(4.0, 3.0), dpi=100)
    try:
        figures.plot_traj_segments(ax, _Run())
        got = {ln.get_label(): _dash(ln) for ln in ax.lines}
        assert got["转入crank"] == _dash_of(figures.TRAJ_TRUNC_LS)
        assert got["转入crank"] != _dash_of("-")
        assert got["直飞"] == _dash_of("-")
        # 图例里那一格用的是同一个线型对象，所以两边画出来一模一样
        assert _dash_of(figures.TRAJ_TRUNC_LS) != _dash_of(figures.TRAJ_MISSILE_LS)
    finally:
        plt.close(fig)


# ============================================================ 出图层（真解算 + 真出图）

CASES = {
    "hit": ({}, "命中（默认）"),
    "miss": ({"standard": "R-77"}, "脱靶（R-77）"),
    "trunc": ({"t_crank": 28.0}, "crank 没转完（t_crank=28）"),
    "w30": ({"weave": True, "weave_amp_deg": 30.0, "weave_hz": 0.1}, "震荡 ±30°/0.1 Hz"),
    "prev": ({"preview": True}, "3D 预览"),
}
#: 有俯视面板 + inset 的四个工况（`prev` 是 3D 预览，没有俯视面板）
TRAJ_KEYS = ("hit", "miss", "trunc", "w30")


def _cases(shots):
    """只遍历四个轨迹工况（跳过预览）。"""
    return [(k, shots[k]) for k in TRAJ_KEYS]


@pytest.fixture(scope="module")
def shots():
    """渲染五个工况（四个轨迹 + 一个预览），把 draw 之后的版面事实抓下来。

    只跑一次（模块级），后面十几个断言都读同一批诊断 —— 真解算 fast 档每例约 0.3 s，
    出图三格式约 1~2 s。产物留在 `.tmp_test/traj_plot/` 里，方便拿成品图复核断言。

    ⚠ 这里**不用** `tmp_path_factory`：本仓库的零依赖运行器（`tests/run_tests.py` +
    `conftest.py`）只提供 `tmp_path`，没有 `tmp_path_factory` / `monkeypatch` ——
    用了会在**收集期**报 `未定义的 fixture`，把整个跑挂掉。
    """
    import shutil

    base = OUT / "latest"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    diag: dict = {}
    glyphs: list = []
    orig = figures.save_formats
    pending: dict = {}

    def spy(fig, out_base, *, formats=("png", "pdf", "svg")):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fig.canvas.draw()
            ren = fig.canvas.get_renderer()
            d = _snapshot(fig, ren)
            # 紫框：**独立于 renderer** 的一条路径（直接从 Agg 缓冲区数像素）
            if d["insets"]:
                d["frame_px"] = _purple_frame(fig, d["main_disp"])
            d["glyphs"] = [str(w.message) for w in caught if "Glyph" in str(w.message)]
            d["md_figtexts"] = [t for t in d["figtexts"] if "**" in t]
        glyphs.extend(d["glyphs"])
        res = orig(fig, out_base, formats=formats)
        pending[out_base.name] = d
        return res

    figures.save_formats = spy
    try:
        for key, (kw, _desc) in CASES.items():
            fdir, rdir = base / f"fig_{key}", base / f"res_{key}"
            fdir.mkdir(parents=True, exist_ok=True)
            rdir.mkdir(parents=True, exist_ok=True)
            workflow.run_traj(workflow.TrajRequest(
                scene=Scene(), tier="fast", tag=key, formats=("png", "pdf", "svg"),
                figure_dir=fdir, result_dir=rdir, **kw))
            name = f"fig_traj_{'preview_' if kw.get('preview') else ''}{key}"
            d = pending.pop(name, None)
            assert d is not None, f"{name} 没有走到 save_formats（出图路径变了？）"
            d["png"] = fdir / f"{name}.png"
            d["svg"] = fdir / f"{name}.svg"
            d["dir"] = fdir
            d["name"] = name
            diag[key] = d
    finally:
        figures.save_formats = orig
    diag["_glyphs"] = glyphs
    diag["_base"] = base
    return diag


# ------------------------------------------------------------ D1：放大 inset


def test_inset_box_is_visible_in_the_saved_png(shots):
    """框在 **300 dpi 成品图**上宽高都 ≥ 20 px，并且落在俯视面板里（D1）。

    两条独立路径同时成立才算通过：renderer 的 `get_position()`（draw 之后）与
    Agg 缓冲区里数出来的紫框。
    """
    assert not shots["prev"]["insets"], "3D 预览不该有俯视 inset"
    for key, d in _cases(shots):
        assert d["insets"], f"{key}：放大 inset 不见了"
        c0 = d["insets"][0]
        w_px = _px300(c0["disp"][2] - c0["disp"][0], d["fig_dpi"])
        h_px = _px300(c0["disp"][3] - c0["disp"][1], d["fig_dpi"])
        assert w_px >= MIN_PX and h_px >= MIN_PX, f"{key}：inset 只有 {w_px:.1f}×{h_px:.1f} px"
        mx0, my0, mx1, my1 = d["main_disp"]
        assert (c0["disp"][0] >= mx0 - PAD and c0["disp"][2] <= mx1 + PAD
                and c0["disp"][1] >= my0 - PAD and c0["disp"][3] <= my1 + PAD), \
            f"{key}：inset 伸出俯视面板 {c0['disp']} vs {d['main_disp']}"
        if "frame_px" in d:
            fw, fh = d["frame_px"]
            assert fw >= MIN_PX / DPI * d["fig_dpi"] * 0.9 and fh >= MIN_PX / DPI * d["fig_dpi"] * 0.9, \
                f"{key}：缓冲区里的紫框只有 {fw:.1f}×{fh:.1f} display px"
            assert abs(fw - (c0["disp"][2] - c0["disp"][0])) <= 0.2 * fw, \
                f"{key}：两条独立量法不一致 {fw:.1f} vs {c0['disp'][2] - c0['disp'][0]:.1f}"


def test_inset_really_zooms_instead_of_restating_the_main_panel(shots):
    """放大倍率必须真的存在：inset 的 y 跨度 ≪ 俯视面板的 z 跨度（D1 的第二种退化）。

    旧版把显示范围反解成"俯视面板的米/英寸"，于是 span 比值 ≈ 框高/面板高（0.88）——
    框很大、里面一条几乎不动的线，而图例写着「放大」。
    """
    for key in ("hit", "miss", "trunc", "w30"):
        d = shots[key]
        c0 = d["insets"][0]
        main_span = d["main"][3]                       # 只用来算比值量级，不要求精确
        ins_span_px = c0["disp"][3] - c0["disp"][1]
        ratio_px = ins_span_px / (d["main_disp"][3] - d["main_disp"][1])
        # 旧版：ylim 跨度 / 面板跨度 ≈ 框高占比（0.88），也就是"米/英寸"一样
        assert ratio_px > 0.1 and main_span > 0.1
        assert c0["ylim"][1] - c0["ylim"][0] < 6000.0, \
            f"{key}：inset 的 y 跨度为 {c0['ylim'][1] - c0['ylim'][0]:.1f} m（放大倍率被撑没了）"


def test_inset_y_tick_labels_belong_to_the_inset_frame(shots):
    """没有"第二套游离的 y 刻度"：inset 的刻度文字必须紧贴**它自己的**左框（D1）。"""
    for key, d in _cases(shots):
        c0 = d["insets"][0]
        assert c0["n_ytick"] >= 2, f"{key}：inset 的 y 刻度少于 2 个"
        assert 0.0 <= c0["tick_gap"] <= 30.0, \
            f"{key}：刻度到框的距离 {c0['tick_gap']:.1f} px（游离刻度）"


def test_inset_and_its_legend_entry_disappear_together(shots):
    """硬闸门：框 < 20 px 时 **inset 与图例那一格一起**撤掉，不许只撤图（D1）。"""
    fdir = shots["_base"] / "tiny"
    fdir.mkdir(parents=True, exist_ok=True)
    seen: dict = {}
    orig_save, orig_min = figures.save_formats, figures.TRAJ_INSET_MIN_PX

    def spy(fig, out_base, *, formats=("png", "pdf", "svg")):
        seen["n_inset"] = len(getattr(fig.axes[0], "child_axes", ()))
        seen["legend"] = [t.get_text() for t in fig.legends[0].get_texts()]
        return orig_save(fig, out_base, formats=formats)

    figures.TRAJ_INSET_MIN_PX = 1.0e6          # 人为把闸门抬到不可能满足
    figures.save_formats = spy
    try:
        workflow.run_traj(workflow.TrajRequest(
            scene=Scene(), tier="fast", tag="tiny", formats=("png",),
            figure_dir=fdir, result_dir=fdir / "res"))
    finally:
        figures.save_formats = orig_save
        figures.TRAJ_INSET_MIN_PX = orig_min
    assert seen.get("n_inset") == 0, "闸门没生效：框太小却还画了 inset"
    assert figures.LEGEND_TRAJ_ZOOM not in seen["legend"], "inset 撤了，图例还留着「放大」"


# ------------------------------------------------------------ D2/D3/D8：注记


def test_node_name_appears_once_in_every_annotation(shots):
    """同一句里节点名只出现一次，且只有一个 `t=`（D3）。"""
    names = [v for v in figures.TRAJ_MARK_LABELS.values()]
    for key, d in _cases(shots):
        for txt, _bb in d["texts"]:
            assert txt.count("t=") <= 1, f"{key}：{txt!r} 里时间出现多次"
            for nm in names:
                assert txt.count(nm) <= 1, f"{key}：{txt!r} 里「{nm}」出现两次"
            assert "命中 / 结束" not in txt, f"{key}：图上出现了只该在图例里的合并名"


def test_annotations_do_not_overlap_on_the_main_panel(shots):
    """俯视面板里的注记两两**不重叠**（D2：实测曾重叠 1421.3 px²）。"""
    for key, d in _cases(shots):
        boxes = d["texts"]
        bad = [(round(_ov(boxes[i][1], boxes[j][1]), 1), boxes[i][0], boxes[j][0])
               for i in range(len(boxes)) for j in range(i + 1, len(boxes))
               if _ov(boxes[i][1], boxes[j][1]) > 0.0]
        assert not bad, f"{key}：注记重叠 {bad}"


def test_miss_case_ends_with_one_annotation_that_names_the_outcome(shots):
    """脱靶工况：结束处**只有一条**文案，写明"未命中 + 脱靶量"（D8）。"""
    d = shots["miss"]
    end = [t for t, _bb in d["texts"] if "结束" in t or "命中 t=" in t]
    assert len(end) == 1, f"结束处文案不是一条：{end}"
    assert "未命中" in end[0] and "脱靶" in end[0]
    assert not [t for t, _bb in d["texts"] if "末段最近点" in t], "旧版的第二条文案还在"


def test_hit_case_marks_the_event_time_with_three_decimals(shots):
    """命中工况：星标旁的时间是**事件**时刻（69.172 s），不是节点那行的两位小数。"""
    d = shots["hit"]
    hit = [t for t, _bb in d["texts"] if t.startswith("命中 t=")]
    assert len(hit) == 1, f"命中文案不是一条：{hit}"
    assert hit[0] == "命中 t=69.172 s"


# ------------------------------------------------------------ D7：竖排标签


def test_vertical_alt_panel_labels_stay_inside_and_do_not_overlap(shots):
    """高度–时间面板的竖排标签：不出面板、两两不重叠（D7：曾出右边界 17.0 px、重叠 578.8 px²）。"""
    for key, d in _cases(shots):
        if not d["alt"]:
            continue
        x0, y0, x1, y1 = d["alt"]["disp"]
        vert = [(t, bb) for t, bb in d["alt"]["texts"] if bb[3] > bb[2] * 1.2]
        assert vert, f"{key}：竖排标签一个都没有（节点没标？）"
        out = [(t, round(bb[0] + bb[2] - x1, 1)) for t, bb in vert if bb[0] + bb[2] > x1 + PAD]
        assert not out, f"{key}：竖排标签出右边界 {out}"
        assert all(bb[0] >= x0 - PAD for _t, bb in vert), f"{key}：竖排标签出左边界"
        bad = [(round(_ov(a[1], b[1]), 1), a[0], b[0])
               for i, a in enumerate(vert) for b in vert[i + 1:] if _ov(a[1], b[1]) > 0.0]
        assert not bad, f"{key}：竖排标签重叠 {bad}"


# ------------------------------------------------------------ D4/D5/D6：线型 / 文本 / 字形


def test_truncated_segment_matches_its_legend_entry(shots):
    """截断段画的是虚线，线型与图例那一格**同一个图案**（D4）。"""
    d = shots["trunc"]
    want = _dash_of(figures.TRAJ_TRUNC_LS)
    dashed = [ln for ln in d["lines"] if ln["dash"] == want and ln["marker"] == "None"]
    assert dashed, f"截断段不是虚线：{[(l['label'], l['dash']) for l in d['lines']]}"
    assert figures.LEGEND_TRAJ_TRUNC in d["legend"]
    # 没被截断的工况不该出现那一格（图例只列真画了的东西）
    assert figures.LEGEND_TRAJ_TRUNC not in shots["hit"]["legend"]


def test_inset_tick_labels_do_not_overlap_each_other(shots):
    """放大框**自己**的刻度文字不许互相压，也不许 x 刻度压到 y 刻度。

    这条同样是**看图**发现的：数值断言全绿，但 miss/trunc 两个工况的 x 刻度挤成了
    `44.144.244.3k`（实测相邻标签 −11.9 / −4.1 display px）。根因是 matplotlib 的
    `get_tick_space()` 在 50 display px 宽的框上仍给出 5 个刻度，而一个 `44.2k` 就有
    27 px 宽。修法：刻度个数按框宽反算（`figures._inset_xtick_count`）**并等分**放在窗口上
    （`_inset_xtick_locs`），刻度文字一律左对齐（居中时最左边那个有一半探到框外，
    正好压住同一角的 y 刻度，实测 9.7~25.0 px²）。
    """
    for key, d in _cases(shots):
        c0 = d["insets"][0]
        xlo, xhi = c0["xlim"]
        ylo, yhi = c0["ylim"]
        xs = [(t, bb) for t, pos, bb in c0["xticks"] if xlo - 1e-9 <= pos <= xhi + 1e-9]
        ys = [(t, bb) for t, pos, bb in c0["yticks"] if ylo - 1e-9 <= pos <= yhi + 1e-9]
        assert len(xs) >= 2 and len(ys) >= 2, f"{key}：放大框刻度太少 x={xs} y={ys}"
        for tag, boxes, i0, i1 in (("x", xs, 0, 2), ("y", ys, 1, 3)):
            boxes = sorted(boxes, key=lambda e: e[1][i0])
            bad = [(boxes[i][0], boxes[i + 1][0], round(boxes[i][1][i1] - boxes[i + 1][1][i0], 1))
                   for i in range(len(boxes) - 1) if boxes[i][1][i1] > boxes[i + 1][1][i0]]
            assert not bad, f"{key}：放大框 {tag} 刻度文字互相压 {bad}"
        cross = [(tx, ty, round(_ov(bx, by), 1)) for tx, bx in xs for ty, by in ys
                 if _ov(bx, by) > 0.0]
        assert not cross, f"{key}：放大框 x 刻度压到 y 刻度 {cross}"


def test_no_annotation_covers_the_inset(shots):
    """主轴注记不许压在放大框上，也不许压到框的标题上。

    这条是**看图才发现的**（数值断言全绿，图上一眼就看出问题）：inset 的槽位原来在所有
    注记**之后**才算，于是先放的「110° / 90° 参考方向」两条注记正好落在框里 ——
    两条射线本来就指向左上，跟 inset 抢同一块地方。注记是"可移动"的一方，
    所以修法是：**先定 inset 槽位并占位，再放所有注记**。
    """
    for key, d in _cases(shots):
        assert d["insets"], f"{key}：放大 inset 不见了"
        c0 = d["insets"][0]
        frame = (c0["disp"][0], c0["disp"][1],
                 c0["disp"][2] - c0["disp"][0], c0["disp"][3] - c0["disp"][1])
        for txt, bb in d["texts"]:
            ov = _ov(bb, frame)
            assert ov <= 1e-9, f"{key}：「{txt}」压在放大框上 {ov:.1f} px²（{bb} vs {frame}）"
            if c0["title_bb"] is not None:
                ov = _ov(bb, c0["title_bb"])
                assert ov <= 1e-9, f"{key}：「{txt}」压住放大框标题 {ov:.1f} px²"


def test_main_panel_annotations_stay_inside_the_panel(shots):
    """注记不许被挤到俯视面板外面（`_place_label` 的越界罚分要真的起作用）。

    ⚠ 留 `LABEL_EDGE_SLACK`：`get_window_extent` 给的是**行框**（含 ascent/descent 与
    `bbox` 内边距），比墨迹大；而命中点就落在面板顶边上，那条结局注记只能往上让
    （实测顶边出 3.0 display px ≈ 8 px @300 dpi）。真正的缺陷是 D7 那种**整行**出界
    （17.0 display px），比这个余量大一倍以上。
    """
    for key, d in _cases(shots):
        mx0, my0, mx1, my1 = d["main_disp"]
        for txt, bb in d["texts"]:
            assert (bb[0] >= mx0 - LABEL_EDGE_SLACK and bb[1] >= my0 - LABEL_EDGE_SLACK
                    and bb[0] + bb[2] <= mx1 + LABEL_EDGE_SLACK
                    and bb[1] + bb[3] <= my1 + LABEL_EDGE_SLACK), \
                f"{key}：「{txt}」出面板 {bb} vs {d['main_disp']}"


def test_every_legend_entry_has_a_visible_artist(shots):
    """图例 ↔ 图元：每一格都得在图上找到**画出来的**图元（D1/D4 的共同根因）。

    分段/参考线/航迹用颜色或线型图案认，节点用标记认，inset 用子轴认。
    量的是屏幕 bbox 的**面积**（≥ 20 px²）：一个"转弯段"在 50 km 量级的俯视图上本来就只有
    20 来 px 长（实测 22.8 px），线长阈值只对两条**参考线/航迹**用（≥ 30 px，实测 800+ px）。
    这条断言要抓的是**退化**（一条 1 px 的线、一个消失的 inset），不是"短"。
    """
    for key, d in _cases(shots):
        seg_labels = {ln["label"] for ln in d["lines"] if ln["label"]}
        for entry in d["legend"]:
            if entry.startswith("放大"):
                assert d["insets"], f"{key}：图例有「放大」但没有 inset"
                continue
            long_line = entry in (figures.LEGEND_TRAJ_MISSILE, figures.LEGEND_TRAJ_GUIDE)
            if entry.startswith("crank 没转完"):
                hit = [ln for ln in d["lines"] if ln["dash"] == _dash_of(figures.TRAJ_TRUNC_LS)]
            elif entry == figures.LEGEND_TRAJ_MISSILE:
                hit = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_MISSILE_COLOR]
            elif entry == figures.LEGEND_TRAJ_GUIDE:
                hit = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_GUIDE_COLOR]
            elif entry in figures.TRAJ_MARK_LABELS.values():
                hit = [ln for ln in d["lines"] if ln["marker"] == "o"
                       and ln["color"] == figures.TRAJ_MARK_COLOR]
            else:
                assert entry in seg_labels, f"{key}：图例「{entry}」找不到对应分段"
                hit = [ln for ln in d["lines"] if ln["label"] == entry]
                # ⚠ **线型也要对上**：图例把手是画在另一张画布上的代理线，旧版只比 label
                #   ⇒「实线 转入crank」格配上「虚线 转入crank」段照样算过（复验缺陷 A）。
                want = d.get("legend_dash", {}).get(entry)
                if want is not None:
                    assert [ln for ln in hit if ln["dash"] == want], (
                        f"{key}：图例「{entry}」的线型是 {want}，图上同名图元却是 "
                        f"{[ln['dash'] for ln in hit]}")
            assert hit, f"{key}：图例「{entry}」在图上找不到图元"
            if entry in figures.TRAJ_MARK_LABELS.values():
                area = max(ln["bb"][2] * ln["bb"][3] for ln in hit)
                assert area >= 8.0, f"{key}：「{entry}」的节点标记只有 {area:.1f} px²"
                continue
            # 线量**屏幕长度**：`直飞` 那一段 z 恒定 ⇒ bbox 高度正好是 0，用面积会误判成"没画"。
            # ⚠ 长度阈值分两档：参考线/航迹 ≥ 30 px（实测 800+ px），**分段**只要 ≥ 3 px ——
            #   分段有多长是**想定几何**决定的（实测「转入39」6.8 px、「转入crank」22.8 px，
            #   都是真画出来的），这里要抓的是"退化成一个点/没画"，不是"短"。
            longest = max((ln["bb"][2] ** 2 + ln["bb"][3] ** 2) ** 0.5 for ln in hit)
            need = 30.0 if long_line else 3.0
            assert longest >= need, f"{key}：「{entry}」只有 {longest:.1f} px"


def test_footnotes_have_no_markdown_and_no_missing_glyphs(shots):
    """脚注里 0 个 `**`、0 条 `Glyph ... missing from font`（D5/D6）。

    `**` 在 SVG 文本里也要查一遍：那是**成品**里肉眼最容易漏的东西。
    """
    assert not shots["_glyphs"], f"缺字形：{shots['_glyphs'][:3]}"
    for key, d in ((k, v) for k, v in shots.items() if not k.startswith("_")):
        assert not d["md_figtexts"], f"{key}：脚注里有 markdown {d['md_figtexts']}"
        if d["svg"].exists():
            body = d["svg"].read_text(encoding="utf-8", errors="replace")
            assert "**" not in body, f"{key}：SVG 文本里还有 '**'"
            assert "\u26a0" not in body, f"{key}：SVG 里还有没有字形的 U+26A0"


def test_preview_footnote_is_clean_too(shots):
    """3D 预览的脚注同样是**成品**：实测改前 SVG 里有 2 处 `**`（D5）。"""
    d = shots["prev"]
    joined = "\n".join(d["figtexts"])
    assert "不解算" in joined
    assert "**" not in joined
    assert "**" not in d["svg"].read_text(encoding="utf-8", errors="replace")


# ------------------------------------------------------------ 字节可复现


def test_traj_figures_are_byte_identical_across_two_runs(tmp_path):
    """同参数连画两次，**三格式**逐字节一致（`test_figures_repro` 只覆盖图1）。"""
    def once(root):
        d = root / "f"
        d.mkdir(parents=True, exist_ok=True)
        workflow.run_traj(workflow.TrajRequest(
            scene=Scene(), tier="fast", tag="byte", formats=("png", "pdf", "svg"),
            figure_dir=d, result_dir=root / "r"))
        return {p.suffix: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(d.glob("fig_traj_byte.*")) if p.is_file()}

    a, b = once(tmp_path / "a"), once(tmp_path / "b")
    assert set(a) == {".png", ".pdf", ".svg"}
    assert a == b, f"字节不一致：{a} vs {b}"

# -*- coding: utf-8 -*-
"""图4 出图层的**版面硬约束**（不是美化）。

这批缺陷的共同点是**静默**：图照样出得来、代码一个数都不报错，只有量"成品图上真实的
像素与矩形"才发现 —— 所以这里用 `save_formats` 探针在 `fig.canvas.draw()` **之后**量
renderer 的 bbox，而不是读我们自己的意图（`docs/PLAN-FIG3-TRAJECTORY.md` 的 D1~D11）：

* **D2/D8 注记打架**：命中/脱靶那两条文案压在同一个点上（实测 1421.3 px²），脱靶工况还写着
  「命中 / 结束」，读起来自相矛盾。
* **D3 节点名说两遍**：`build_marks()` 的 note 自带节点名，旧版又拼了一遍图例前缀。
* **D4 线型与图例对不上**：`truncated` 段画的是实线，图例那一格却是虚线。
* **D5 markdown**：matplotlib 不解析 `**`，它把星号原样打出来（预览图脚注实测 2 处）。
* **D6 缺字形**：`⚠`(U+26A0) 在 Microsoft YaHei 里没有字形，出图时刷
  `Glyph 9888 ... missing from font` 并留一个豆腐块。
* **D7 竖排标签出框**：图例右边界那一列必然超 17.0 px，两个节点同刻时纵向错 10 pt 也躲不掉
  （实测重叠 578.8 px²）。
* **D12（2026-10-01，用户口径）主视图改 3D 斜视 + 导弹开机后换色 + 删掉放大 inset**：
  三条判据都在这一层量 —— ①主视图真的是 `Axes3D` 且**没有任何 child_axes**（删干净，
  不是"藏起来"）；②导弹航迹按 `t_beam` 切成**两种颜色**且切点重合（`t_beam` 那一行同时是
  前一段的末点与后一段的首点）；③注记除了两两不压，还**不许压轴的刻度数字与轴标题** ——
  3D 的刻度/轴标题是画在盒子**里面**的，旧判据（"不压 inset"）随着 inset 一起删掉后，
  这一类缺陷就没有闸门了（实测裸放注记时压住 5 条刻度）。

⚠ **三条与 matplotlib 3.11.1 有关的实测口径**（写断言时别踩）：

1. `apply_aspect()` / `get_tightbbox()` 依赖 draw；`get_position()` 在 draw 之前**不是**
   最终值。`Axes3D.apply_aspect()` 的 `box_aspect` 恒为 1，所以给定的 axes rect 一定会被
   收缩成一个**物理正方形**（`get_window_extent()` 给的就是收缩后的那个方块）。
2. `Line2D.get_linestyle()` 对**元组**线型是**有损**的：`(0, (4, 2))` 与 `(0, (5, 3))`
   都返回 `'--'`。真实图案只在 `_unscaled_dash_pattern` 里（4/2 与 5/3 画出来不一样），
   所以"截断段用的是 `TRAJ_TRUNC_LS`"**不能**拿 `get_linestyle()` 比字符串。
3. **`Annotation.get_window_extent()` 会把引线一起算进去**（框从文字一路拉到锚点），
   量注记必须走 `figures._text_bbox_px()`；否则"注记两两不重叠"这条判据自己就会误报。

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
import pytest                                                  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from missile_sim import figures, workflow                      # noqa: E402
from missile_sim.spec import Scene                             # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".tmp_test" / "traj_plot"
PAD = 3.0                                   # 允许的亚像素/抗锯齿误差
#: 注记**行框**允许压出 3D 盒的余量（display px，fig dpi = 110）：
#: 行框含 ascent/descent 与 bbox 内边距，比墨迹大。实测 0.0（`_place_label3d` 的越界罚分
#: 把注记全部关在盒子里），留一点余量给不同字体版本。
LABEL_EDGE_SLACK = 6.0


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


def _text_bb(t, ren) -> tuple:
    """**文字**的屏幕框 `(x0, y0, w, h)`（display px）。

    ⚠ 不能直接 `t.get_window_extent()`：节点注记现在是带**引线**的 `Annotation`，
      `Annotation.get_window_extent()` 会把引线一起并进框里（从文字一路拉到锚点），
      拿它判"两两不重叠"必然误报。`figures._text_bbox_px()` 是专门量文字的（它内部
      自己调 `update_positions()`，见其 docstring）。
      预览图里的注释是普通 `Text`（没有 `update_positions`），走原路。
    """
    try:
        x0, y0, x1, y1 = figures._text_bbox_px(t, ren)
        return (float(x0), float(y0), float(x1 - x0), float(y1 - y0))
    except AttributeError:
        return tuple(float(v) for v in t.get_window_extent(renderer=ren).bounds)


def _snapshot(fig, ren) -> dict:
    """在 `draw()` 之后把"版面事实"全量抓下来（测试只读这个 dict）。"""
    ax = fig.axes[0]
    mbb = ax.get_window_extent(ren)
    d = {"fig_dpi": float(fig.dpi), "fig_in": tuple(float(v) for v in fig.get_size_inches()),
         "axes_name": str(getattr(ax, "name", "?")),
         "axes_proj": type(ax).__name__,
         "n_axes": len(fig.axes),
         "n_child_axes": len(getattr(ax, "child_axes", ())),
         "main": ax.get_position().bounds,
         "main_disp": (float(mbb.x0), float(mbb.y0), float(mbb.x1), float(mbb.y1)),
         "texts": [(t.get_text(), _text_bb(t, ren)) for t in ax.texts],
         "lines": [{"label": ln.get_label(), "dash": _dash(ln), "color": str(ln.get_color()),
                    "marker": str(ln.get_marker()),
                    # 点数用来验"按 t_beam 切开的切点在哪"（`get_data_3d` 是 Line3D 上
                    # 唯一可信的数据出口，`get_window_extent` 在 3D 上也是可用的）
                    "n": int(len(ln.get_data_3d()[0])),
                    "bb": tuple(float(v) for v in
                                ln.get_window_extent(renderer=ren).bounds)}
                   for ln in ax.lines],
         "legend": [t.get_text() for t in (fig.legends[0].get_texts() if fig.legends else [])],
         # ⚠ 图例**把手**的线型也要抓：图例档是用代理线画在另一张画布上的，
         #   只比文字/label 的话「实线 转入crank」格配「虚线 转入crank」段也能过
         #   （复验 task-7 缺陷 A 就是这么漏掉的）。`legend_handles` 在 mpl 3.7+ 才改名。
         "legend_dash": {},
         "figtexts": [t.get_text() for t in fig.texts],
         "alt": None}
    if fig.legends:
        hs = getattr(fig.legends[0], "legend_handles",
                     getattr(fig.legends[0], "legendHandles", [])) or []
        d["legend_dash"] = {h.get_label(): _dash(h) for h in hs if h.get_label()}
    # 轴的**墨迹**（三条轴标题 + 所有刻度文字）：3D 里这些全画在盒子**内部**，
    # 所以"注记两两不重叠"并**不足以**说明注记没压住它们（实测裸放时压住 5 条刻度）。
    d["ink"] = figures._axes_ink(ax, ren)
    d["ink_hits"] = [(txt, round(o, 1)) for txt, bb in d["texts"]
                     for o in (_ov(bb, ik) for ik in
                               ((b[0], b[1], b[2] - b[0], b[3] - b[1]) for b in d["ink"]))
                     if o > 0.0]
    if len(fig.axes) > 1:
        a1 = fig.axes[1]
        abb = a1.get_window_extent(ren)
        d["alt"] = {"disp": (float(abb.x0), float(abb.y0), float(abb.x1), float(abb.y1)),
                    "texts": [(t.get_text(), _text_bb(t, ren)) for t in a1.texts]}
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


def test_truncated_segment_is_drawn_with_the_documented_dash_pattern():
    """`Segment.truncated` ⇒ 线型必须就是图例那一格用的 `TRAJ_TRUNC_LS`（D4）。"""

    class _Seg:
        def __init__(self, label, t0, t1, key, trunc):
            self.label, self.t0_s, self.t1_s = label, t0, t1
            self.color_key, self.truncated = key, trunc

    class _Run:
        # ⚠ `ty`（高度）不能省：`_target_xyz()` 认的是 (t, tx, tz, ty) 四元组，
        #   少一个分量整条航迹就当"取不到坐标"被丢掉 —— 图上一条线都不画，
        #   测试却会在 `KeyError: '转入crank'` 上摔一跤（看着像线型问题，其实没有线）。
        rows = [{"t": float(i), "tx": float(i) * 100.0, "tz": float(i) * 50.0,
                 "ty": 10_000.0 + float(i) * 10.0} for i in range(11)]
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
#: 四个轨迹工况（3D 主视图 + 高度–时间面板；`prev` 是输入阶段的 3D 预览）
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
            out = workflow.run_traj(workflow.TrajRequest(
                scene=Scene(), tier="fast", tag=key, formats=("png", "pdf", "svg"),
                figure_dir=fdir, result_dir=rdir, **kw))
            name = f"fig_traj_{'preview_' if kw.get('preview') else ''}{key}"
            d = pending.pop(name, None)
            assert d is not None, f"{name} 没有走到 save_formats（出图路径变了？）"
            d["png"] = fdir / f"{name}.png"
            d["svg"] = fdir / f"{name}.svg"
            d["dir"] = fdir
            d["name"] = name
            # 换色判据要的两个量：图上报告的 t_beam 与**导弹自己的**时间序列。
            # `_missile_xyz()` 与 `plot_traj` 用的是同一个出口，这样"切点在第几个点"才是
            # 可独立重算的（而不是把 `_split_by_time` 自己的结果再抄一遍）。
            # `beam_split` 取自**图元**：开机前那段最后一个点对应的时间。
            run = out.get("run")
            if run is not None and out.get("t_beam_s") is not None:
                mtrack = figures._missile_xyz(run, t_end=float(run.t_end_s))
                ts = [float(e[0]) for e in mtrack]
                pre = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_MISSILE_COLOR]
                d["missile_ts"] = ts
                d["t_beam_s"] = float(out["t_beam_s"])
                d["beam_split"] = (ts[pre[0]["n"] - 1] if pre else None)
            diag[key] = d
    finally:
        figures.save_formats = orig
    diag["_glyphs"] = glyphs
    diag["_base"] = base
    return diag


# ------------------------------------------------------------ D12：3D 主视图 / 无 inset


def test_main_view_is_3d_and_carries_no_inset(shots):
    """主视图真的是 `Axes3D`，且**一个 child_axes 都没有**、放大 inset 的代码整个不在了。

    用户口径（2026-10-01）："替换，但是……左下角的放大图有点何意味了去掉"。
    所以判据分两层，缺一不可：

    * **结构层**：`fig.axes[0].name == "3d"`、`fig.axes` 正好两个（3D + 高度–时间面板）、
      `child_axes == 0`。只把 inset 藏起来（`set_visible(False)`）过不了这一条。
    * **源码层**：inset 的公开常量（`TRAJ_INSET_MIN_PX` / `TRAJ_ZOOM_COLOR` /
      `LEGEND_TRAJ_ZOOM`）与实现函数都**不存在**了 —— 留着它们就迟早有人再画回去。

    另外量一条"真的画出来了"：3D 盒的投影范围是个**物理正方形**（`Axes3D.apply_aspect()`
    的既定行为），边长 ≥ 300 display px，且盒子里有 ≥ 8 条带数据的 3D 线（分段 + 导弹两段 +
    参考线 + 节点标记）。
    """
    for gone in ("TRAJ_INSET_MIN_PX", "TRAJ_ZOOM_COLOR", "LEGEND_TRAJ_ZOOM",
                 "_inset_px", "_inset_slot", "_zoom_window", "_place_label"):
        assert not hasattr(figures, gone), f"放大 inset 的残留：figures.{gone}"
    for key, d in _cases(shots):
        assert d["axes_name"] == "3d", f"{key}：主视图不是 3D（{d['axes_name']}）"
        assert d["n_axes"] == 2, f"{key}：轴的个数是 {d['n_axes']}，应当只有 3D + 高度面板"
        assert d["n_child_axes"] == 0, f"{key}：还有 {d['n_child_axes']} 个 child_axes（inset？）"
        x0, y0, x1, y1 = d["main_disp"]
        assert abs((x1 - x0) - (y1 - y0)) <= 1.0, f"{key}：3D 盒不是正方形 {d['main_disp']}"
        assert x1 - x0 >= 300.0, f"{key}：3D 盒只有 {x1 - x0:.1f} px 宽"
        with_data = [ln for ln in d["lines"] if ln["n"] >= 2]
        assert len(with_data) >= 8, f"{key}：3D 盒里只有 {len(with_data)} 条线有数据"
        assert not [t for t in d["legend"] if "放大" in t], f"{key}：图例里还有「放大」那一格"


def test_annotations_avoid_the_axis_ticks_and_titles(shots):
    """注记不许压**轴的墨迹**：三条轴标题 + 所有刻度数字（3D 里它们画在盒子**内部**）。

    这条是 `test_no_annotation_covers_the_inset` 的替代判据：inset 删掉之后，"注记压住
    图上的其它文字"这一类缺陷就没有闸门了。3D 的刻度数字/轴标题沿着盒子的棱斜排，注记
    正好落在同一条带上（实测裸放时 9 条注记里压住 5 条刻度，图上就是 "30000" 被文字盖住）。

    口径：`figures._axes_ink()` 给的就是这些文字的屏幕框；注记一侧走 `_text_bb()`
    （**不含引线**，见模块 docstring 第 3 条）。要求重叠面积 0。
    """
    for key, d in _cases(shots):
        assert len(d["ink"]) >= 6, f"{key}：轴的墨迹只抓到 {len(d['ink'])} 条（口径失效？）"
        assert not d["ink_hits"], f"{key}：注记压住轴刻度/轴标题 {d['ink_hits']}"


def test_missile_colour_switches_at_the_beam_time(shots):
    """导弹航迹按 `t_beam` 切成**两种颜色**，切点重合、线型不变、成品里两种颜色都画出来了。

    用户口径："导弹到达开机距离后也要换色"。判据不读代码里的意图，全部在**画出来的图元**上量：

    * 用图上报告的 `t_beam` **自己重算**切点：`idx = 最后一个 t <= t_beam 的下标`，
      于是前一段该有 `idx+1` 个点、后一段该有 `n-idx` 个点（**共用切点**那一行）；
    * 两段的颜色分别是 `TRAJ_MISSILE_COLOR` / `TRAJ_MISSILE2_COLOR`，线型都还是
      `TRAJ_MISSILE_LS`（同一枚弹，颜色只标阶段，见 `plot_traj` docstring）；
    * 图例两格都在（`导弹航迹（导引头开机前）` / `（开机后换色）`），且都找得到对应图元；
    * **SVG 里两种颜色的 hex 都真的出现**（防"只在图例里承诺、图上没画"）。
    """
    for key, d in _cases(shots):
        ts, t_beam = d["missile_ts"], d["t_beam_s"]
        assert t_beam is not None and d["beam_split"], f"{key}：没取到 t_beam"
        assert t_beam == pytest.approx(d["beam_split"], abs=1e-9), \
            f"{key}：切点 {d['beam_split']} 不是 t_beam {t_beam}"
        idx = max(i for i, t in enumerate(ts) if t <= t_beam)
        assert ts[idx] <= t_beam < ts[idx + 1], f"{key}：切点下标 {idx} 不在 t_beam 两侧"
        pre = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_MISSILE_COLOR]
        post = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_MISSILE2_COLOR]
        assert len(pre) == 1 and len(post) == 1, \
            f"{key}：两种颜色的导弹航迹各该正好一条（{len(pre)} / {len(post)}）"
        assert pre[0]["n"] == idx + 1, f"{key}：开机前那段 {pre[0]['n']} 点，应为 {idx + 1}"
        assert post[0]["n"] == len(ts) - idx, \
            f"{key}：开机后那段 {post[0]['n']} 点，应为 {len(ts) - idx}"
        want = _dash_of(figures.TRAJ_MISSILE_LS)
        assert pre[0]["dash"] == want and post[0]["dash"] == want, \
            f"{key}：两段的线型应都是 {want}"
        assert figures.LEGEND_TRAJ_MISSILE_BEFORE in d["legend"]
        assert figures.LEGEND_TRAJ_MISSILE_AFTER in d["legend"]
        svg = d["svg"].read_text(encoding="utf-8", errors="replace")
        for col, tag in ((figures.TRAJ_MISSILE_COLOR, "开机前"),
                         (figures.TRAJ_MISSILE2_COLOR, "开机后")):
            assert col in svg, f"{key}：SVG 里没有{tag}的颜色 {col}"


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
    """3D 主视图里的注记两两**不重叠**（D2：实测曾重叠 1421.3 px²）。"""
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


def test_main_panel_annotations_stay_inside_the_panel(shots):
    """注记不许被挤到 3D 盒外面（`_place_label3d` 的越界罚分要真的起作用）。

    ⚠ 留 `LABEL_EDGE_SLACK`：`_text_bbox_px` 给的是**行框**（含 ascent/descent 与 `bbox`
    内边距），比墨迹略大。真正的缺陷是 D7 那种**整行**出界（17.0 display px）。
    3D 里这条尤其重要：盒子右边就是高度–时间面板，注记飘出去会压到另一张图上。
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

    分段/参考线/航迹用颜色或线型图案认，节点用标记认，导弹的两段颜色各认一格。
    量的是屏幕 bbox 的**面积**（≥ 8 px²）：一个"转弯段"在 50 km 量级的主视图上本来就很短
    （实测「转入39」6.8 px），线长阈值只对**参考线/航迹/导弹两段**用（≥ 30 px，实测 800+ px）。
    这条断言要抓的是**退化**（一条 1 px 的线、一段消失的航迹），不是"短"。
    """
    for key, d in _cases(shots):
        seg_labels = {ln["label"] for ln in d["lines"] if ln["label"]}
        for entry in d["legend"]:
            long_line = entry in (figures.LEGEND_TRAJ_MISSILE, figures.LEGEND_TRAJ_GUIDE,
                                  figures.LEGEND_TRAJ_MISSILE_BEFORE,
                                  figures.LEGEND_TRAJ_MISSILE_AFTER)
            if entry.startswith("crank 没转完"):
                hit = [ln for ln in d["lines"] if ln["dash"] == _dash_of(figures.TRAJ_TRUNC_LS)]
            elif entry == figures.LEGEND_TRAJ_MISSILE_BEFORE:
                hit = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_MISSILE_COLOR]
            elif entry == figures.LEGEND_TRAJ_MISSILE_AFTER:
                hit = [ln for ln in d["lines"] if ln["color"] == figures.TRAJ_MISSILE2_COLOR]
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
            # ⚠ 阈值分两档：参考线/航迹/导弹两段 ≥ 30 px（实测 800+ px），**分段**放得很松。
            #   分段有多长是**想定几何 + 投影**一起决定的：改 3D 之后「转入39」（1 s 的转弯、
            #   目标只走 ~300 m）在 52 km 宽的盒子里只剩 1.4 px —— 它是**真画出来的**（11~21 个
            #   数据点、颜色/线型都对），这类判据要抓的是"退化成没画"，不是"短"。
            #   所以分段额外用**数据点数**兜底：≥ 2 个点才算一条线。
            longest = max((ln["bb"][2] ** 2 + ln["bb"][3] ** 2) ** 0.5 for ln in hit)
            if long_line:
                assert longest >= 30.0, f"{key}：「{entry}」只有 {longest:.1f} px"
            else:
                assert max(ln["n"] for ln in hit) >= 2, f"{key}：「{entry}」的数据点少于 2 个"
                assert longest >= 0.5, f"{key}：「{entry}」只有 {longest:.1f} px"


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

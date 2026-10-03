# -*- coding: utf-8 -*-
"""图4 出图层**剩下的**判据（全部不依赖出图）。

2026-10-03 之内删了两张静态图（用户口径 `docs/UX-TARGET.md` §1）：
`fig_traj_default.*`（静态轨迹成品图）与 `fig_traj_preview_default.*`（输入阶段的 3D 预览）。
本文件原来是"图4 出图层的版面硬约束"—— 用 `save_formats` 探针在 `fig.canvas.draw()` **之后**
量真实的像素与矩形（D2 注记打架 / D3 节点名说两遍 / D4 线型与图例对不上 / D5 markdown 星号 /
D6 缺字形 / D7 竖排标签出框 / D12 主视图 3D 且无 inset）。

**图没了，那些判据一条都留不下**：留着就只能改成"量一张不存在的图"，或者变成空循环 ——
而**空循环会假绿，比删掉更糟**。所以随图一起删，只保留**不碰画布**的纯函数判据：

* `figures._plain()` 剥星号（`**x**` 在 matplotlib 里不是加粗，是原样打出的星号）；
* `figures._mark_label()` 让「命中 / 结束」这一格**图上二选一**；
* `figures._mark_text()` 不让同一个节点名说两遍、时间只说一次；
* `figures.plot_traj_segments()` 的截断段线型必须与图例那一格同源。

⚠ 仍然活着的口径：要打印出去 / 进产物的文案里不许有 markdown 星号
（`-k printed_text` 扫源头，`results/*.json`、`figures/*.svg` 扫工件）；`figures._plain()`
只兜"出图"这一条路径，本文件第一条判据钉的就是它的口径。

⚠ 随图一起删的旧判据（**不是漏掉**，是对象不存在了）：`test_main_view_is_3d_and_carries_no_inset`、
`test_annotations_avoid_the_axis_ticks_and_titles`、`test_node_name_appears_once_in_every_annotation`、
`test_annotations_do_not_overlap_on_the_main_panel`、
`test_vertical_alt_panel_labels_stay_inside_and_do_not_overlap`、
`test_every_legend_entry_has_a_visible_artist`、`test_footnotes_have_no_markdown_and_no_missing_glyphs`、
`test_preview_footnote_is_clean_too`、`test_traj_figures_are_byte_identical_across_two_runs`
（最后那条量的是预览图三格式的字节复现，图删了就没有对象；图1 的字节复现仍由 `-k figures_repro` 守着）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt                                # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from missile_sim import figures                                # noqa: E402


def _dash(ln) -> tuple:
    """线型**真实**图案。`get_linestyle()` 对**元组**线型是有损的，会把任何图样糊成 `'--'`。"""
    pat = getattr(ln, "_unscaled_dash_pattern", None)
    if pat is None:                                              # 老版本兜底
        return tuple(matplotlib.lines._get_dash_pattern(ln.get_linestyle())[1] or ())
    return tuple(pat[1] or ())


def _dash_of(ls) -> tuple:
    return tuple(matplotlib.lines._get_dash_pattern(ls)[1] or ())


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

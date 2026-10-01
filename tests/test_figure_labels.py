# -*- coding: utf-8 -*-
"""图上弹点标签的**可读性硬约束**。

这一组不是"美化"：标签越出轴范围会被裁掉（读不出是哪个弹），标签压住弹点会让点看起来
像文字的一部分（`MICA` 曾经就被自己的邻居压成 `M●ICA`），标签互相重叠会糊成一团。
三者在 300 dpi 的出图上肉眼都很难发现 —— 只有拿 renderer 量每个 `Text` 的 bbox 才可靠。

⚠ 改 `figures.MISSILE_LBL_OFFSETS`、`figures.adaptive_axis` 的 pad、或点数（弹池）之后
**必须**重跑本文件。
"""

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from missile_sim import figures, pool


def _render(keys=None):
    figures.setup_style()
    pts = pool.points(keys)
    axis = figures.adaptive_axis(pts)
    fig, ax, cax = figures.make_figure(axis)
    _, texts = figures.plot_points(ax, pts)
    fig.canvas.draw()
    return fig, ax, pts, texts, fig.canvas.get_renderer()


def _collect(ax, pts, texts, renderer, tol=0.5):
    """返回三类问题：出界 / 压点 / 标签互相重叠。"""
    axbb = ax.get_window_extent()
    boxes = [t.get_window_extent(renderer) for t in texts]
    out = []

    for p, bb in zip(pts, boxes):
        hits = []
        if bb.x0 < axbb.x0 - tol:
            hits.append(f"左超 {axbb.x0 - bb.x0:.1f}px")
        if bb.x1 > axbb.x1 + tol:
            hits.append(f"右超 {bb.x1 - axbb.x1:.1f}px")
        if bb.y0 < axbb.y0 - tol:
            hits.append(f"下超 {axbb.y0 - bb.y0:.1f}px")
        if bb.y1 > axbb.y1 + tol:
            hits.append(f"上超 {bb.y1 - axbb.y1:.1f}px")
        if hits:
            out.append(f"标签出界 {p.label}：" + " / ".join(hits))

    for p, bb in zip(pts, boxes):
        for q in pts:
            qx, qy = ax.transData.transform((q.dv, q.bc))
            if bb.x0 <= qx <= bb.x1 and bb.y0 <= qy <= bb.y1:
                out.append(f"标签压点 {p.label} 盖住 {q.label} 的点")

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes[i].overlaps(boxes[j]):
                out.append(f"标签重叠 {pts[i].label} × {pts[j].label}")

    return out


def _assert_clean(keys=None):
    fig, ax, pts, texts, renderer = _render(keys)
    try:
        issues = _collect(ax, pts, texts, renderer)
    finally:
        plt.close(fig)
    assert not issues, "标签可读性问题：\n  " + "\n  ".join(issues)


def test_default_pool_labels_are_readable():
    """11 型全集（默认出图路径）：标签不出界、不压点、不互相重叠。"""
    _assert_clean()


def test_single_missile_labels_are_readable():
    """单型时轴范围收紧到最小，固定像素偏移最容易在这里出界。"""
    for key in ("120A", "R-77-1", "PL-12", "Derby"):
        _assert_clean([key])


def test_two_missile_extremes_are_readable():
    """取 ΔV 最小 + 最大两型：轴被拉到最宽，标签仍在范围内。"""
    _assert_clean(["120A", "R-77-1"])


def test_label_boxes_are_inside_axes_for_full_pool():
    """直接量：每个标签的 bbox 都严格落在轴 bbox 内（不靠容差）。"""
    fig, ax, pts, texts, renderer = _render()
    try:
        axbb = ax.get_window_extent()
        for p, t in zip(pts, texts):
            bb = t.get_window_extent(renderer)
            assert axbb.x0 <= bb.x0 and bb.x1 <= axbb.x1, (
                f"{p.label} 横向超出轴：[{bb.x0:.1f},{bb.x1:.1f}] vs [{axbb.x0:.1f},{axbb.x1:.1f}]")
            assert axbb.y0 <= bb.y0 and bb.y1 <= axbb.y1, (
                f"{p.label} 纵向超出轴：[{bb.y0:.1f},{bb.y1:.1f}] vs [{axbb.y0:.1f},{axbb.y1:.1f}]")
    finally:
        plt.close(fig)


def test_offsets_cover_every_pooled_missile():
    """偏移表必须覆盖弹池里的每一型 —— 漏了会静默退回 (10, 10)，通常就压点了。"""
    keys = set(pool.names())
    covered = set(figures.MISSILE_LBL_OFFSETS)
    missing = keys - covered
    assert not missing, f"这些弹没有标签偏移，会退回默认值：{sorted(missing)}"


def test_baseline_point_is_green_and_the_hollow_ring_is_gone():
    """基准弹（选中态）= **绿色实心点**，其余红；外面那圈空心环已按用户要求删掉（2026-10-01）。

    判据落在 **artist** 上（不看像素）：`plot_points(highlight=…)` 之后只应有**一个**散点集合
    —— 旧实现的 `mark_highlight` 会再加一个空心环 collection（`s = POINT_SIZE * 4.2`）；
    颜色则必须恰好一处是 `BASE_COLOR`，其余全是 `POINT_COLOR`。
    """
    from matplotlib.colors import to_rgba

    figures.setup_style()
    pts = pool.points()
    axis = figures.adaptive_axis(pts)
    keys = [p.key for p in pts]
    i_base = keys.index("PL-12")
    red = to_rgba(figures.POINT_COLOR)[:3]
    green = to_rgba(figures.BASE_COLOR)[:3]

    fig, ax, _ = figures.make_figure(axis)
    fig2, ax2, _ = figures.make_figure(axis)
    try:
        sc, _ = figures.plot_points(ax, pts, highlight="PL-12")
        assert len(ax.collections) == 1, f"空心环应当已经删掉，还剩 {ax.collections}"
        faces = [to_rgba(c)[:3] for c in sc.get_facecolors()]
        assert len(faces) == len(keys), (len(faces), len(keys))
        assert faces[i_base] == green, f"基准弹必须涂绿，实际 {faces[i_base]}"
        assert all(c == red for i, c in enumerate(faces) if i != i_base), faces
        # 不给 highlight 时全是红的 —— 默认口径不能被"选中态"污染
        sc2, _ = figures.plot_points(ax2, pts)
        assert all(to_rgba(c)[:3] == red for c in sc2.get_facecolors())
    finally:
        plt.close(fig)
        plt.close(fig2)

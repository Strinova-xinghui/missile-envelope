# -*- coding: utf-8 -*-
"""页面引用的图件闸门：**存在 + 入库 + 内容口径 + 两个形态成对**（Lead 2026-10-04 验收项）。

来由（真实事故，别删这段）：换轴那天只重出了 `figures/fig_bg_plane_default.*`，
而首页 `webui_static/index.html` 贴的是**另一份**产物 `figures/fig_bg_plane_static.png`
（"无输入静态形态"），它还是旧的 γ 轴 —— 用户一打开首页就看到了旧图。
三个验收全从这里漏过去：**HTTP 200、文件字节数、包内探针"资源全部 200"都只证明"文件在"，
不证明"内容是新口径"**；而且**同名（都叫"图2"）不同文件，没有任何判据把两者绑在一起**。

所以本文件分四层，缺一层就还会漏：

1. **页面引用层**：`webui_static/*.{html,js,css}` 里出现的每个 `/figures/<name>` 都必须真实存在、
   并且（在 git 工作树里时）**被 git 跟踪** —— "页面贴了一个没人管的本地文件"是同一族事故；
2. **名单层**：`figures/` 里**所有** `*bg_plane*` 与 `*isotime_plane*` 变体逐个查（a）入库、
   （b）轴口径 —— 不是只查页面引用的那一个，也不是只查 `_default`；
3. **成对层（这条才是"漏重出一个变体"的直接闸门）**：同一张图的 `_default` 与 `_static`，
   轴标签必须**逐字相同**（拿 `figures.py` 里的轴标签常量当基准，去空白后比对）。
   比 mtime 靠谱：mtime 只能告诉你"动过"，判据要告诉你"两个形态说的是同一件事"；
4. **反例层**：把旧口径文本喂给检查函数必须报红（判据不能是空转的）。

⚠ 红线只钉**轴标签**，不拿「双曲线」「转向损失」当红线：`_default` 的脚注里合法地留着它们
（讲旧口径那一段）。红线是 `figures.BG_OLD_AXIS_MARKS` 那两条轴注记与 `figures.BG_AXIS_MARK`。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from missile_sim import figures

ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = ROOT / "figures"
STATIC_DIR = ROOT / "src" / "missile_sim" / "webui_static"

#: 页面里引用的图件：`/figures/<文件名>`（前端只贴 PNG，PDF/SVG 是同源兄弟件）
PAGE_ASSET_RE = re.compile(r"/figures/([A-Za-z0-9_.\-]+)")

#: 两张图各自的**文件名标记**与**两个形态**（形态名 = `fig_*_plane_<form>.*` 里的 `<form>`）
FAMILIES = {
    "bg_plane": ("default", "static"),
    "isotime_plane": ("default", "static"),
}

#: 每个形态至少要有一张 SVG 可查
SVG_SUFFIX = ".svg"


def _norm(s: str) -> str:
    """去空白后比对：SVG 注释里的全角空格会被后端规范化成普通空格。"""
    return re.sub(r"\s+", "", s)


def _page_files():
    return sorted(p for p in STATIC_DIR.rglob("*")
                  if p.is_file() and p.suffix in (".html", ".js", ".css"))


def _referenced_figures() -> dict:
    """`{引用的文件名: [引用它的页面文件…]}`。"""
    out: dict = {}
    for p in _page_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        for name in PAGE_ASSET_RE.findall(text):
            out.setdefault(name, []).append(p.name)
    return out


def _variants(family: str, suffix: str = SVG_SUFFIX):
    """`{"default": Path, "static": Path}` —— 某个图族的各形态（缺的就不出现）。"""
    out = {}
    for p in sorted(FIG_DIR.glob(f"fig_{family}_*{suffix}")):
        form = p.name[len(f"fig_{family}_"):-len(suffix)]
        out[form] = p
    return out


def _axis_problems(svg_text: str, family: str) -> list:
    """内容口径检查（**纯函数**，反例层直接喂它旧文本）。"""
    t = _norm(svg_text)
    if family == "bg_plane":
        bad = [m for m in figures.BG_OLD_AXIS_MARKS if m in svg_text]
        if figures.BG_AXIS_MARK not in svg_text:
            bad.append(f"缺少新轴标记 {figures.BG_AXIS_MARK!r}")
        return bad
    bad = [m for m in figures.PLANE_FORBIDDEN if m in svg_text]
    if figures.PLANE_AXIS_MARK not in svg_text:
        bad.append(f"缺少轴标记 {figures.PLANE_AXIS_MARK!r}")
    return bad


def _git_tracked_figures():
    """`figures/` 里被 git 跟踪的文件名集合；**本目录不是那个 git 工作树的根**时返回 `None`。

    为什么必须比对 `--show-toplevel`（2026-10-04 实测踩到）：分发包常被解压进**别的** git 工作树
    的子目录里 —— 本项目自己的校验解压就落在 `E:\\导弹包线图-dist` 这个工作树内部。那时
    `git ls-files -- figures` 会向上找到**别人的** `.git` 并**成功返回一个空集**（0 退出码），
    于是"这一份没在版本控制里"被误报成"图件没入库"，包内自检凭空多出 2 项红。
    ⇒ 只认"工作树根 == 本目录"这一种情况，其余一律 `None`（= 跳过跟踪检查，存在性与轴口径照查）。
    """
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(ROOT),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
        if top.returncode != 0:
            return None
        try:
            if Path(top.stdout.strip()).resolve() != Path(ROOT).resolve():
                return None
        except OSError:
            return None
        got = subprocess.run(["git", "ls-files", "--", "figures"], cwd=str(ROOT),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if got.returncode != 0:
        return None
    return {Path(line.strip()).name for line in got.stdout.splitlines() if line.strip()}


def _git_ignored_figures() -> set:
    """`figures/` 里**被 `.gitignore` 忽略**的文件名（`figures/*_web*` 这类临时网页产物）。

    ⚠ 为什么要有它（2026-10-04 实测）：应用每跑一次就在 `figures/` 落一份 `*_web*.png`
    （`docs/WEBUI.md` §10.4「网页产物是临时的」，`.gitignore` 第 63~65 行**明文**忽略）。
    旧版名单判据不分设计，一律要求"`figures/` 里每个图件都入库" ⇒ 只要有人打开过应用，
    `-k page_assets` 就永久变红，而"修"它的办法居然是去删临时件（那次真误删了别人的新文件）。
    **被忽略 ≠ 没入库**：忽略是设计，漏入库才是事故。
    """
    if _git_tracked_figures() is None:      # 不在本仓工作树里 ⇒ 跟踪/忽略都无从判断
        return set()
    try:
        got = subprocess.run(["git", "ls-files", "--others", "--ignored",
                              "--exclude-standard", "--", "figures"],
                             cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    if got.returncode != 0:
        return set()
    return {Path(line.strip()).name for line in got.stdout.splitlines() if line.strip()}


# ------------------------------------------------------------ 第 1 层：页面引用


def test_pages_only_reference_figures_that_exist():
    """页面里出现的每个 `/figures/<name>` 都必须在 `figures/` 里真实存在（否则首页裂图）。"""
    refs = _referenced_figures()
    assert refs, "页面里一个 /figures/ 引用都没有？扫不到引用说明这条判据是空的"
    missing = sorted(n for n in refs if not (FIG_DIR / n).is_file())
    assert not missing, f"页面引用了不存在的图件：{missing}（引用者：{refs}）"


def test_page_referenced_figures_are_git_tracked():
    """页面引用的图件必须**入库** —— 否则随包/克隆出去就是裂图。"""
    tracked = _git_tracked_figures()
    if tracked is None:
        pytest.skip("不在 git 工作树里（分发包内）—— 跟踪状态无从判断，存在性与口径仍然照查")
    refs = _referenced_figures()
    untracked = sorted(n for n in refs if n not in tracked)
    assert not untracked, (
        f"页面引用了没有入库的图件：{untracked}\n"
        "  ⇒ `git add figures/<name>`，或者把页面改成引用随包的那一份"
    )


def test_index_still_points_at_both_static_variants():
    """首页必须仍然贴**两份 static 形态**（图1/图2 各一张）。

    这条防的是"用删引用代替重出产物"——旧件轴口径不对时，删掉引用能让上面两条判据全绿，
    但用户首页就没图了。
    """
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for want in ("/figures/fig_isotime_plane_static.png", "/figures/fig_bg_plane_static.png"):
        assert want in page, f"首页不再引用 {want}（是漏了还是被删了？）"


# ------------------------------------------------------------ 第 2 层：名单


def test_every_figure_variant_on_disk_covers_all_forms_and_formats():
    """每个图族在 `figures/` 里都要有**两个形态 × 三种格式**（少一个形态 = 漏了一份产物）。"""
    problems = []
    for family, forms in FAMILIES.items():
        for form in forms:
            for suffix in (".png", ".pdf", ".svg"):
                p = FIG_DIR / f"fig_{family}_{form}{suffix}"
                if not p.is_file():
                    problems.append(p.name)
    assert not problems, (
        f"`figures/` 里缺这些产物：{problems}\n"
        "  ⇒ 走唯一入口重出：`python scripts/refresh_products.py`"
    )


def test_every_figure_variant_is_git_tracked():
    """名单层（a）：`figures/` 里两个图族的**所有**变体都必须入库 —— **被 `.gitignore` 忽略的除外**。

    忽略的是设计里的临时件（`figures/*_web*`，见 `_git_ignored_figures` 的说明）；
    真正"该入库却没入库"的图件仍然会被这条抓到（反证见下一条）。
    """
    tracked = _git_tracked_figures()
    if tracked is None:
        pytest.skip("不在 git 工作树里（分发包内）—— 跟踪状态无从判断")
    ignored = _git_ignored_figures()
    names = [p.name for family in FAMILIES for p in FIG_DIR.glob(f"fig_{family}_*")]
    assert names, "一个图件都没扫到？判据会空转"
    untracked = sorted(n for n in names if n not in tracked and n not in ignored)
    assert not untracked, f"这些图件没入库：{untracked}（交付物必须随仓库走）"


def test_roster_gate_still_sees_a_non_ignored_newcomer():
    """**反证**：过滤掉"被忽略的临时产物"之后，名单闸门**仍然**能抓到真正漏入库的图件。"""
    tracked = _git_tracked_figures()
    if tracked is None:
        pytest.skip("不在 git 工作树里 —— 无从判断")
    ignored = _git_ignored_figures()
    on_disk = sorted(p.name for p in FIG_DIR.glob("fig_*_web*"))
    if on_disk:
        assert set(on_disk) <= ignored, \
            f"磁盘上有 *_web* 临时产物，但忽略集没认出它们：{sorted(set(on_disk) - ignored)}"
    fake = "fig_bg_plane_zzz_newcomer.png"          # 名字不匹配任何忽略规则
    assert fake not in ignored and fake not in tracked, \
        "过滤规则过宽：真正的漏入库图件会被放过"


def test_every_bg_plane_variant_is_on_the_new_axis():
    """名单层（b）：`figures/` 里所有 `*bg_plane*` 变体都要是新纵轴口径。

    这条就是漏重出变体的直接闸门 —— 2026-10-04 事故里 `_static` 正是从这儿漏过去的。
    PNG/PDF 是二进制的，内容检查落在同名 `.svg` 兄弟件上（三者永远同一批出图）。
    """
    problems = {}
    ignored = _git_ignored_figures()          # 临时网页产物（figures/*_web*）不参与口径核对
    for p in sorted(FIG_DIR.glob(f"fig_{'bg_plane'}_*")):
        if p.name in ignored:
            continue
        if p.suffix == ".pdf" or p.suffix == ".png":
            if not p.with_suffix(SVG_SUFFIX).is_file():
                problems[p.name] = ["缺少同名 .svg 兄弟件（无法核对内容口径）"]
            continue
        bad = _axis_problems(p.read_text(encoding="utf-8", errors="replace"), "bg_plane")
        if bad:
            problems[p.name] = bad
    assert not problems, (
        "有 β–ginv 图还是旧纵轴口径（多半是漏重出某个变体）：\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(problems.items()))
        + "\n  ⇒ 重出：`python scripts/refresh_products.py`"
    )


def test_every_isotime_plane_variant_has_no_axis_swap_bleed():
    """名单层（b）：图1（ΔV–BC）**不该出现 γ/ginv 任何字样** —— 一旦出现说明轴注记被串了。"""
    problems = {}
    for p in sorted(FIG_DIR.glob("fig_isotime_plane_*.svg")):
        bad = _axis_problems(p.read_text(encoding="utf-8", errors="replace"), "isotime_plane")
        if bad:
            problems[p.name] = bad
    assert not problems, f"图1 的轴注记被串了：{problems}"


# ------------------------------------------------------------ 第 3 层：成对


def test_two_forms_of_the_same_figure_share_the_same_axis_labels():
    """**成对闸门**：同一张图的 `_default` 与 `_static`，轴标签必须逐字相同。

    基准是 `figures.py` 里的轴标签常量（唯一出处）：
    图2 = `XLABEL_BG` / `YLABEL_BG`，图1 = `XLABEL` / `YLABEL`。
    只重出一个形态时，另一个的轴标签就对不上 —— 这条比查 mtime 靠谱。
    """
    want = {
        "bg_plane": (figures.XLABEL_BG, figures.YLABEL_BG),
        "isotime_plane": (figures.XLABEL, figures.YLABEL),
    }
    problems = {}
    for family, labels in want.items():
        variants = _variants(family)
        if len(variants) < 2:
            problems[family] = [f"只有 {sorted(variants)} 个形态（成对闸门失效）"]
            continue
        for form, p in sorted(variants.items()):
            text = _norm(p.read_text(encoding="utf-8", errors="replace"))
            miss = [lbl for lbl in labels if _norm(lbl) not in text]
            if miss:
                problems[p.name] = [f"轴标签对不上：{lbl!r}" for lbl in miss]
    assert not problems, (
        "同一张图的两个形态**轴标签不一致**（典型原因：只重出了其中一份）：\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(problems.items()))
        + "\n  ⇒ 重出全部形态：`python scripts/refresh_products.py`"
    )


# ------------------------------------------------------------ 第 4 层：反例


def test_gate_has_teeth_it_rejects_the_old_axis_note():
    """**反例层**：把旧口径文本喂给检查函数，必须报红。

    没有这一条，上面那些"必须过"的断言可能只是因为 `_axis_problems()` 恒返回空表。
    旧文本取自 10-03 那份 `fig_bg_plane_static.svg`（用户截图里看到的就是它）。
    """
    old_static = ("γ [kg/m²] 转向损失 →（越小越好） 两类存能能力平面：β（直飞保能） vs γ（转向损失）"
                  " 因 γ ∝ 1/β，这族线是双曲线（不是直线）。")
    assert _axis_problems(old_static, "bg_plane"), "旧口径文本竟然通过了检查：判据是空的"
    # 轴标签常量本身必须带新轴标记（否则成对闸门会拿旧标签当基准）
    assert figures.BG_AXIS_MARK in figures.YLABEL_BG
    assert not any(m in figures.YLABEL_BG for m in figures.BG_OLD_AXIS_MARKS)
    # 红线不是「双曲线」这个词：新图的脚注里它合法存在
    new_footnote = "ginv = 1/γ [m²/kg] 转向能力 →（越大越好） 旧口径的等 n* 线是双曲线。"
    assert not _axis_problems(new_footnote, "bg_plane")


def test_page_referenced_bg_figures_pass_the_axis_gate():
    """页面**实际引用**的那张 β–ginv 图必须过内容口径（引用 → 同名 SVG 兄弟件）。"""
    refs = [n for n in _referenced_figures() if "bg_plane" in n]
    assert refs, "页面里没有引用任何 β–ginv 图？这条判据会空转"
    problems = {}
    for name in refs:
        svg = (FIG_DIR / name).with_suffix(SVG_SUFFIX)
        if not svg.is_file():
            problems[name] = ["没有同名 .svg 兄弟件"]
            continue
        bad = _axis_problems(svg.read_text(encoding="utf-8", errors="replace"), "bg_plane")
        if bad:
            problems[name] = bad
    assert not problems, f"页面贴的 β–ginv 图内容口径不对：{problems}"

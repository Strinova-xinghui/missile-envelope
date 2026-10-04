# -*- coding: utf-8 -*-
"""参考图曲线（入库快照 `results/bg_ref_curves.json`）的判据。

**为什么要有这一组**：用户 2026-10-04 换纵轴口径（γ → `ginv = 1/γ`）的物理后果之一，是等 `n*` 线
从双曲线 `γ = C/β` 变成**过原点的直线** `ginv = m·β`。光在自己画的新图上量"看起来是直线"不够 ——
**参考图本身就是矢量的**（`_recon/fig2_turn_energy.svg`，7 条虚线 `<polyline>`），把它解析入库后
可以在同一个判据里同时钉住三件事：① 曲线是过原点直线；② 斜率族满足 `m ∝ n*²`；
③ 提取出来的常数与**本项目自己的** `m = (n*·G0/q)²·(F/f)` 对得上。

⚠ **判据只读仓库里的 JSON**，绝不去读 `E:\\War Thunder\\` 下的源文件（那台机器之外的文件不该决定
本仓库的判据）。文件里记了 `source.sha256`，最后一条用例会扫 `tests/` 确保没人偷偷把外部路径写进来。
"""

from __future__ import annotations

import io
import json
import math
import re
from pathlib import Path

import pytest

from missile_sim import bg

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "results" / "bg_ref_curves.json"

#: 参考图源文件的 sha256（`_recon/fig2_turn_energy.svg`，实测 21937 字节）—— 入库快照的完整性钉子。
SVG_SHA256 = "bdcdf2fdaa1b1a023d7de7ef0a2404b6a7add44f9253eb5fd14471e565df8c44"
#: 层号：参考图脚注是 14~20 共 7 条，其中 5 条带文字标签，14/15 按几何次序补。
LEVELS = [14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
#: 总点数（7 条虚线折线的点数实测）：96 + 142 + 161×3 + 139 + 97 = 957。
N_POINTS = 957


@pytest.fixture(scope="module")
def ref() -> dict:
    assert REF.is_file(), f"缺少入库快照 {REF}（用 scripts/extract_bg_reference_curves.py 生成）"
    return json.loads(io.open(REF, encoding="utf-8").read())


def test_snapshot_records_its_provenance(ref):
    """入库快照必须能自证出处：源路径、字节数、sha256、标定式、提取时间。"""
    src = ref["source"]
    assert src["sha256"] == SVG_SHA256, "源 SVG 的哈希与记录不符（换了图就必须重新提）"
    assert src["bytes"] == 21937
    assert "_recon" in src["path"] and src["path"].lower().endswith(".svg")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", ref["extracted_at"])
    cal = ref["calibration"]
    assert cal["limits"] == {"beta": [2450.0, 3800.0], "gamma": [45.0, 100.0]}
    # 从绘图区推出来的标定，必须与记录在案的老标定式一致（相对差 ≤ 1e-3）
    assert cal["cross_check"]["beta"]["rel_slope"] < 1e-3
    assert cal["cross_check"]["gamma"]["rel_slope"] < 1e-3


def test_seven_levels_and_the_expected_point_count(ref):
    assert ref["levels"] == LEVELS
    assert ref["counts"]["n_curves"] == 7
    assert ref["counts"]["n_points"] == N_POINTS
    assert [c["n_star"] for c in ref["curves"]] == LEVELS
    for c in ref["curves"]:
        assert c["n_points"] >= 90, (c["n_star"], c["n_points"])
        assert len(c["points"]) == c["n_points"]
    assert [c["label_source"] for c in ref["curves"]].count("svg_text") == 5
    assert [c["label_source"] for c in ref["curves"]].count("geometry") == 2


def test_every_point_carries_both_readings(ref):
    """每个点都要同时给 γ（内核口径）与 ginv（轴口径），且互为倒数。"""
    worst = 0.0
    for c in ref["curves"]:
        for beta, gamma, ginv in c["points"]:
            assert 2400.0 < beta < 3850.0, beta
            assert 40.0 < gamma < 105.0, gamma
            assert 1.0 / 105.0 < ginv < 1.0 / 40.0, ginv
            worst = max(worst, abs(ginv * gamma - 1.0))
    # ⚠ 容差按**快照自己的位数**给（γ 4 位、ginv 9 位）：四舍五入后乘积必然偏离 1，
    #   γ ≈ 53.5 处 1e-4 的 γ 舍入 ⇒ 相对偏差 ~2e-6，取 1e-5 仍然宽松。
    assert worst < 1e-5, f"ginv·γ 偏离 1 的最大值 {worst:.3e}"


def test_curves_are_straight_lines_through_the_origin(ref):
    """**核心判据**：过原点拟合的相对残差必须小（实测 2.3e-4 ~ 4.6e-4）。"""
    for c in ref["curves"]:
        fit = c["fit"]
        assert fit["intercept_fixed_at"] == 0.0
        assert fit["m"] > 0
        assert fit["rel_resid"] < 1e-3, (c["n_star"], fit["rel_resid"])
        # 相对残差是"最大偏差 / ginv 跨度"，再对一遍绝对值口径
        span = c["ginv_range"][1] - c["ginv_range"][0]
        assert fit["max_abs_resid"] < 1e-3 * span


def test_the_family_satisfies_m_proportional_to_n_star_squared(ref):
    """斜率族 `m ∝ n*²`：`m/n*²` 在 7 层上必须是同一个常数（实测 5 位有效数字相同）。"""
    ratios = [c["fit"]["m"] / (c["n_star"] ** 2) for c in ref["curves"]]
    lo, hi = min(ratios), max(ratios)
    assert (hi - lo) / lo < 0.01, ratios                       # 相对散开 ≤ 1%
    ms = [c["fit"]["m"] for c in ref["curves"]]
    assert all(b > a for a, b in zip(ms, ms[1:])), ms          # 层号越大斜率越大
    # 层号与斜率的**秩**必须一致（防止标签错配到曲线上）
    assert sorted(range(7), key=lambda i: ms[i]) == list(range(7))


def test_extracted_constant_matches_our_own_formula(ref):
    """把参考图提取出的常数与本项目自己的 `m = (n*·G0/q)²·(F(M)/f(M))` 对比。

    参考图是**同一套物理**画出来的（`_recon/make_fig2_turn_energy.py`），所以这条同时校验了
    两件事：标定没歪、以及我们 `bg.nstar_slope()` 的解析式就是参考图那一族线的解析式。
    实测两边都是 `1.7027e-08`（4~5 位有效数字一致）。
    """
    _alt, _spd, _ma, q_pa, f_mach, cap_f = bg.reference()
    k_ours = (bg.G0 / q_pa) ** 2 * (cap_f / f_mach)
    ratios = [c["fit"]["m"] / (c["n_star"] ** 2) for c in ref["curves"]]
    k_ref = sum(ratios) / len(ratios)
    assert k_ref == pytest.approx(k_ours, rel=0.01), (k_ref, k_ours)
    # 与解析式 `bg.nstar_slope()` 也对一遍（同一条式子，两个入口）
    for n in (14.0, 20.0):
        assert bg.nstar_slope(n) == pytest.approx(k_ours * n * n, rel=1e-12)


def test_tests_never_reach_outside_the_repo():
    """扫 `tests/*.py` 的**代码**里没有绝对外部路径（`E:\\…`）—— 判据必须自足。

    ⚠ 只扫**代码**：文档字符串与 `#` 注释里提到出处（例如"黄金值来自 `_recon` 的既有研究"）
    是**该留的**provenance，不是依赖。所以先把三引号块与行注释抹掉再找。
    """
    def code_only(text: str) -> str:
        text = re.sub(r'"""(?:.|\n)*?"""', "", text)
        text = re.sub(r"'''(?:.|\n)*?'''", "", text)
        return "\n".join(line.split("#", 1)[0] for line in text.splitlines())

    offenders = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        body = code_only(io.open(path, encoding="utf-8", errors="replace").read())
        if re.search(r"""["']E:[\\/]""", body):
            offenders.append(path.name)
    assert not offenders, f"判据的代码里出现了外部绝对路径：{offenders}"


def test_snapshot_is_json_serialisable_and_finite(ref):
    """产物里不许有 NaN/Infinity（`json.dumps` 会写出非法 JSON 而不报错），也不许有 markdown 星号。"""
    text = io.open(REF, encoding="utf-8").read()
    for bad in ("NaN", "Infinity", "-Infinity"):
        assert bad not in text, bad
    # 星号规则对**所有产物**生效（写进去就会被前端/文档原样显示）；本文件第一版就中过一次
    assert "**" not in text, "入库快照里出现了 markdown 星号（加粗请用「」）"
    assert json.dumps(ref, allow_nan=False)
    for c in ref["curves"]:
        assert math.isfinite(c["fit"]["m"]) and math.isfinite(c["fit"]["rel_resid"])

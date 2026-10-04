# -*- coding: utf-8 -*-
"""**轴 oracle** 的判据（`catalog.axis_for()` / `--axes`）。

**为什么有这一段**（Lead 派单 2026-10-04，用户口径"三张图按自选弹池**实时**自适应"）：
静态层（`webui_static/figs2d.js`）要在**浏览器里**算同一根轴，就必须有一个**可对拍的基准**。
`catalog.axis_for(kind, keys)` / `python -m missile_sim --axes …` 就是那个基准。
所以这套判据钉的不是"它自己自洽"，而是**它与既有出图实现逐值相同**：

| 判据 | 为什么 |
| --- | --- |
| oracle 的轴 == `figures.adaptive_axis()` / `figures.bg_axis()` **逐值**（含刻度） | 不许出现"第二套轴算法"：范围/刻度只能是那两个函数算的 |
| 跨界子集（11 弹 + ΔV≈400 的 AIM-4G）轴域**真的扩**且**包住**新点 | 自适应轴的全部意义；只测 11 弹池会漏掉"收紧/放宽"这一半行为 |
| 缺名 / 空集合 / 内核认不得算不了的型号**当场报错** | 静默当空集 ⇒ 页面画一张空图，而且**看不出来** |
| CLI 只吐**一行** JSON、字段固定 5 个、`--figure` 决定 kind | 静态层照这一行吃；多一行/少一字段就是破坏契约 |

⚠ 判据里的"直接调 figures"用的是**池内**子集（`pool.points()` / `bg.rows()` 只认 11 弹池的
短名）；跨界子集用的是目录行 ⇒ 那一档比的是"轴域扩了没、包住没"，不是逐值相等。
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _vendor_data  # noqa: E402
from missile_sim import bg, catalog, cli, figures, pool  # noqa: E402

# 真 pytest 下按数据缺席跳过；本项目跑的是 `tests/run_tests.py`，
# 它是靠"数据缺席时把异常记成 SKIP"这条降级机制达到同样效果的（与 test_catalog.py 一致）。
pytestmark = pytest.mark.skipif(not _vendor_data.ready(), reason=_vendor_data.missing_reason())

#: 跨界用的那枚小弹：AIM-4G「猎鹰」，ΔV **399.7 m/s**（目录里最小的一条），
#: β=1193.15、ginv=0.009174 —— 两个方向都在 11 弹池之外。
SMALL = "us_aim4g_falcon"

#: 11 弹池的短名（顺序 = 目录顺序）。
POOL11 = ["PL-12", "PL-12A", "MICA", "Derby", "AAM-4", "R-Darter",
          "R-77", "R-77-1", "120A", "120C", "120D"]

#: 契约字段（**固定 5 个**，别加别减）。
PAYLOAD_FIELDS = ("kind", "keys", "n", "xlim", "ylim")


def _same_spec(a, b) -> bool:
    """两个 `AxisSpec` 是否**逐值**相同（范围 + 四个刻度量）。"""
    return (tuple(a.xlim) == tuple(b.xlim) and tuple(a.ylim) == tuple(b.ylim)
            and (a.x_major, a.x_minor, a.y_major, a.y_minor)
            == (b.x_major, b.x_minor, b.y_major, b.y_minor))


def test_oracle_axis_equals_the_figure_functions_for_pooled_subsets():
    """**判据①**：池内子集下，oracle 与直接调 `figures` 的轴函数**逐值相等**（含刻度）。

    这是"不许另写一套轴算法"的机器证明：范围、主次刻度有一处不同就红。
    """
    for keys in (POOL11, ["PL-12", "MICA", "R-77"], ["Derby"]):
        want_p = figures.adaptive_axis(pool.points(keys))
        got_p = catalog.axis_for("plane", keys)
        assert _same_spec(got_p, want_p), (keys, got_p, want_p)

        want_b = figures.bg_axis(bg.rows(keys))
        got_b = catalog.axis_for("bg", keys)
        assert _same_spec(got_b, want_b), (keys, got_b, want_b)
    # 默认（keys=None）就是 11 弹池 —— 与 `--missiles` 的默认同口径
    assert _same_spec(catalog.axis_for("plane"), figures.adaptive_axis(pool.points()))


def test_oracle_beta_column_is_the_same_number_as_bc():
    """图2 的横轴取目录的 `bc` 列 —— 这条把"为什么可以"钉住，免得被当成近似。

    β 与 BC 是**同一个数**（`m_dry/(SD·CxK)`）的两条浮点路径：实测逐型绝对差 ≤ 1e-12，
    而 `bg_axis()` 的边界按 **6 位小数**落定 ⇒ 与现算 β 得到同一根轴（上一条判据就是证据）。
    若哪天两者的差涨到 1e-9 以上，说明有一条路径改了公式，必须回头查（不是"调个容差"）。
    """
    worst = 0.0
    for e in pool.POOL:
        worst = max(worst, abs(bg.point_of(e).beta - pool.metrics_of(e).bc))
    assert worst < 1e-9, f"β 与 bc 已经不是同一个数了：最大差 {worst!r}"


def test_oracle_expands_for_a_cross_boundary_subset():
    """**判据②**：11 弹 + 一枚 ΔV≈400 的小弹 ⇒ 轴域**真的扩**、且**包住**那枚弹。

    只测 11 弹池会漏掉"自适应"的另一半（往外放宽）；这条同时也守住 kind 不串
    （plane 与 bg 是两根完全不同的轴）。
    """
    small = {m["key"]: m for m in catalog.load()["missiles"]}[SMALL]
    assert small["dv"] < 420.0, ("跨界用例挑的小弹变了（ΔV 应当 ≈400）", small)

    wide = POOL11 + [SMALL]
    a_p, b_p = catalog.axis_for("plane", POOL11), catalog.axis_for("plane", wide)
    assert b_p.xlim[0] < a_p.xlim[0], ("加了低 ΔV 的弹，横轴左端必须外扩", a_p.xlim, b_p.xlim)
    assert b_p.xlim[1] >= a_p.xlim[1]
    assert b_p.xlim[0] <= small["dv"] <= b_p.xlim[1], "新点必须落在轴里"
    assert b_p.ylim[0] <= small["bc"] <= b_p.ylim[1]

    a_b, b_b = catalog.axis_for("bg", POOL11), catalog.axis_for("bg", wide)
    assert b_b.xlim[0] < a_b.xlim[0] and b_b.ylim[0] < a_b.ylim[0], \
        ("图2 两个方向都该外扩", a_b.xlim, b_b.xlim, a_b.ylim, b_b.ylim)
    assert b_b.xlim[0] <= small["bc"] <= b_b.xlim[1]
    assert b_b.ylim[0] <= small["ginv"] <= b_b.ylim[1]
    # kind 不串：两张图的轴不该是同一根
    assert not _same_spec(b_p, b_b), "plane 与 bg 返回了同一根轴 —— kind 接错了"

    payload = catalog.axis_payload("plane", wide)
    assert payload["n"] == len(POOL11) + 1 and payload["keys"] == wide


def test_oracle_rejects_unknown_empty_and_incomputable_selections():
    """**判据③（反证）**：缺名 / 空集合 / 内核认得但算不了的型号，三种都必须当场报错。

    静默把未知名字当空集的后果不是"报错"而是"**页面画一张空图**"——那是最难发现的一类坏。
    """
    with pytest.raises(catalog.CatalogError) as e1:
        catalog.resolve_keys("PL-12,NOPE")
    msg = str(e1.value)
    assert "NOPE" in msg and "PL-12" in msg, msg          # 报出坏名字与可用名
    assert "missiles[].key" in msg, msg                    # 并指出全量名单在哪

    for empty in ("", "   ", [], ()):
        with pytest.raises(catalog.CatalogError):
            catalog.resolve_keys(empty)
    with pytest.raises(catalog.CatalogError):
        catalog.axis_payload("plane", "")

    # 内核认得的型号、但这条算不了：给面用户的原因 + 内核原话，别混成"查无此名"
    with pytest.raises(catalog.CatalogError) as e3:
        catalog.resolve_keys("cn_pl15")
    m3 = str(e3.value)
    assert "需要动态解算" in m3 and "propulsion" in m3, m3

    # kind 也不许乱给
    with pytest.raises(catalog.CatalogError):
        catalog.axis_for("gamma", POOL11)
    # 大小写/空格不敏感（用户在表单里手打）
    assert catalog.resolve_keys(" pl-12 ,MICA ") == ["PL-12", "MICA"]
    # 去重保序
    assert catalog.resolve_keys("MICA,PL-12,MICA") == ["MICA", "PL-12"]


def test_axes_cli_prints_exactly_one_json_line():
    """**判据④**：`--axes` 只吐**一行** JSON，字段固定 5 个；`--figure` 决定 kind。

    静态层照这一行吃 ⇒ 多一行日志、少一个字段都是破坏契约（而且很容易不知不觉改坏）。
    """
    def run(argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(argv)
        return rc, buf.getvalue()

    rc, out = run(["--axes", "PL-12,MICA,R-77"])
    assert rc == 0 and out.count("\n") == 1, (rc, repr(out))
    got = json.loads(out)
    assert tuple(got) == PAYLOAD_FIELDS, ("字段集变了", tuple(got))
    assert got["kind"] == "plane" and got["keys"] == ["PL-12", "MICA", "R-77"]
    assert got["n"] == 3 and len(got["xlim"]) == 2 and len(got["ylim"]) == 2
    assert got == catalog.axis_payload("plane", "PL-12,MICA,R-77")

    rc2, out2 = run(["--axes", "PL-12,MICA,R-77", "--figure", "bg"])
    assert rc2 == 0 and json.loads(out2)["kind"] == "bg"
    assert json.loads(out2)["xlim"] != got["xlim"], "图2 的横轴是 β，不该等于图1 的 ΔV 轴"

    # 不给弹、给了错名、给错图：一律退出码 2 且 stdout 干净（不许吐半截 JSON）
    for argv in (["--axes", ""], ["--axes", "NOPE"], ["--axes", "PL-12", "--figure", "fig3"]):
        rc3, out3 = run(argv)
        assert rc3 == 2, (argv, rc3)
        assert out3 == "", (argv, repr(out3))

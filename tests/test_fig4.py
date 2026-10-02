# -*- coding: utf-8 -*-
"""图4（β–γ–ΔV 交互式三维散点 + 证据层）的验收。`python tests\\run_tests.py -k fig4`

分五层，各自都能单独跑：

1. **数据层**（毫秒级、只读产物）：`fig4.build()` 的字段契约、**共享网格 + 共享色标范围**、
   展平顺序 / 列号关系、配色逐键取自 `figures`（含"命中色 ≠ 脱靶色""脱靶色不在 t_hit 色标里"
   这两条**关系**判据）、以及"`fig4.py` 不 import 求解器/workflow"的源码判据；
2. **证据层**（要求"能证伪"）：用**合成数据**把"ΔV 只造成平移"与"强曲率"两组分开 ——
   残差与曲率必须真的分得开（否则等于没有判据），并验证曲线弯曲只出现在大 γ 列；
3. **数值一致性**：同一 (β,γ,ΔV) 上 `fig4scan`（弹在外层、ΔV 在内层）与 `bg3d.scan3`
   （单弹）**两条路径各算一次**，`t_hit` 一致（容差写在用例里）；
4. **HTTP 层**（真起服务 + `http.client`）：`/fig4` 整页、`/api/fig4/<tag|job>` 的 JSON 与
   404/409/400 三种失败模式、静态白名单 fail-closed（含 `..` 穿越）；
5. **前端契约**（读文本 + 有 node 就真跑 JS）：函数名 / 元素 id / `localStorage` 键、
   `fig4.js` 里**零颜色字面量**、拖动方向只有一处符号、以及"共享色标""脱靶空心"
   "二次曲线与 Python 记录逐值一致"这些**数值**关系。

⚠ 这些用例**不跑求解器**（除了第 3 层那 8 个工况与最后一层的 CLI 端到端 8 个工况），
数据来自仓库自带的 `results/fig4_default.*`（已入库）；"这个接口不解算"另由
`test_fig4_solver_run_is_never_called` 用"一被调用就炸"的桩钉死。
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import bg, bg3d, fig4, fig4scan, figures, pool, record, solver, webui  # noqa: E402
from missile_sim.spec import Scene  # noqa: E402

#: 已入库的两份产物：默认 11 弹（2695 工况，100% 命中）与**全脱靶**小档
#: （`--missiles R-77 --range 80000 --fig4-beta-n 2 --fig4-gamma-n 2 --fig4-dv-factors 0.5,0.7`）。
PRODUCTS = fig4.default_paths("default")
MISS_PRODUCTS = fig4.default_paths("miss")
DV_PIN_MS = 932.5697
N_MISSILES = 11
N_CASES_PER_MISSILE = 245
#: 与 `bg3d.scan3` 的数值一致性容差 [s]：两条路径走**同一个** `solver.run`，
#: 实测逐位相同；留 1e-6 s 是为了不把"编译路径/浮点求和顺序"这种噪声当成回归。
BETA3D_TOL_S = 1e-6


@pytest.fixture(scope="module")
def web4():
    """一个自己的服务（`state` 由本文件持有，方便塞假任务）。"""
    cfg = {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1,
           "formats": ["png"], "cache": False, "tag": "f4", "poll_ms": 100}
    state = webui.WebState(cfg, quiet=True)
    httpd = webui.make_server("127.0.0.1", 0, state=state, quiet=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield ("127.0.0.1", int(httpd.server_address[1])), state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(addr, path):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=60)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type") or ""
    finally:
        conn.close()


def _get_json(addr, path):
    status, raw, _ctype = _get(addr, path)
    return status, json.loads(raw.decode("utf-8")), raw


def _inject(state, *, state_name="done", result=None, error=""):
    job = state.jobs.create("scan")
    job.state = state_name
    job.error = error
    job.result = result
    return job.id


def _fig4_summary(tag="default", **over):
    body = {"ok": True, "figure": "fig4", "tag": tag, "paths": fig4.default_paths(tag)}
    body.update(over)
    return body


def _products_exist():
    return all(Path(p).is_file() for p in PRODUCTS.values())


pytestmark = pytest.mark.skipif(not _products_exist(),
                                reason="仓库自带的图4 产物缺失（`--figure fig4` 可重出）")


# ============================================================ 0. 源码 / 网格口径


def test_fig4_data_layer_imports_no_solver_and_no_workflow():
    """数据层**只读产物**：源码里不许出现求解器 / 编排 / 算核的 import。

    这条比"打桩计数"更狠：它不是"这次没调用"，而是"根本连不上" ——
    以后有人顺手 `from . import engine` 也会当场红。
    """
    src = (ROOT / "src" / "missile_sim" / "fig4.py").read_text(encoding="utf-8")
    imports = [ln.strip() for ln in src.splitlines()
               if ln.startswith(("import ", "from "))]
    joined = " ".join(imports)
    for bad in ("solver", "workflow", "engine", "pool", "mapping", "bg3d", "fig4scan", "figures."):
        assert bad not in joined, f"fig4.py 的 import 里出现了 {bad!r}：{imports}"
    assert "import numpy as np" in src and "from . import figures" in src
    assert "from .spec import RESULT_DIR" in src


def test_fig4_default_grid_is_7x7x5_and_covers_the_pool():
    """默认网格：β、γ 各 **7** 点取图2 的域（含端点），ΔV **5** 点 = 0.6~1.4 × 钉值。

    ⚠ 同时钉住"11 弹**全部**落在立方体内" —— `bg3d.make_grid3()` 的向内对齐会把 β 下限抬到
    2600，把 R-77（2568.8）与 Derby（2567.0）挤出盒子，而"图上没有它"会被读成"它不行"
    （docs/FIG-BG3D-FEASIBILITY.md §3 记过这个坑）。
    """
    rows = bg.rows(None)
    axis = figures.bg_axis(rows)
    grid = fig4scan.default_grid(rows, dv_pin=DV_PIN_MS)
    assert grid.shape == (5, 7, 7) == fig4.grid_shape()
    assert grid.n_cases == 245
    assert len(grid.beta) == fig4.N_BETA and len(grid.gamma) == fig4.N_GAMMA
    assert grid.beta[0] == pytest.approx(axis.xlim[0], abs=1e-6)
    assert grid.beta[-1] == pytest.approx(axis.xlim[1], abs=1e-6)
    assert grid.gamma[0] == pytest.approx(axis.ylim[0], abs=1e-6)
    assert grid.gamma[-1] == pytest.approx(axis.ylim[1], abs=1e-6)
    for f in fig4.DV_FACTORS:
        # 网格点是 `round(..., 4)` 出来的，所以按 1e-3 比（不是逐位相等）
        assert any(abs(v - DV_PIN_MS * f) < 1e-3 for v in grid.dv), f
    assert grid.dv[len(grid.dv) // 2] == pytest.approx(DV_PIN_MS, abs=1e-6)
    assert grid.dv[0] == pytest.approx(DV_PIN_MS * 0.6, abs=1e-3)
    assert grid.dv[-1] == pytest.approx(DV_PIN_MS * 1.4, abs=1e-3)
    for r in rows:                                   # 11 型都在盒子里（β、γ 两个方向）
        assert grid.beta[0] <= r.beta <= grid.beta[-1], r.key
        assert grid.gamma[0] <= r.gamma <= grid.gamma[-1], r.key
    # 别把"用户拍的 7×7×5"偷偷改成别的：默认值就在数据层里
    assert fig4scan.DEFAULT_N_BETA == 7 and fig4scan.DEFAULT_N_GAMMA == 7
    assert tuple(fig4scan.DEFAULT_DV_FACTORS) == (0.6, 0.8, 1.0, 1.2, 1.4)


def test_fig4_flat_order_and_column_index_agree():
    """展平顺序（ΔV 外层 → γ → β）与"第 p 个点属于哪根竖线"必须一致。

    `column_index(p) == p % (n_beta·n_gamma)` 这条关系是前端拿逐列统计的唯一依据；
    它错了，残差/曲率会整块错位，而图上只是"颜色有点怪"。
    """
    beta = [2500.0, 3000.0, 3500.0]
    gamma = [50.0, 70.0, 90.0]
    dv = [600.0, 900.0, 1200.0]
    cells = fig4.flat_cells(beta, gamma, dv)
    cols = fig4.column_cells(beta, gamma)
    assert len(cells) == 27 and len(cols) == 9
    assert cells[0] == (600.0, 2500.0, 50.0), "ΔV 必须是最外层"
    assert cols[0] == (2500.0, 50.0) and cols[1] == (3000.0, 50.0), "γ 外层、β 内层"
    for p, (d_v, b_v, g_v) in enumerate(cells):
        ci = fig4.column_index(p, len(beta), len(gamma))
        cb, cg = cols[ci]
        assert (cb, cg) == (b_v, g_v), (p, cells[p], cols[ci])
        assert ci == p % 9
    with pytest.raises(ValueError):
        fig4.column_index(-1)
    with pytest.raises(ValueError):
        fig4.column_index(0, 0, 0)


# ============================================================ 1. 数据层契约


def test_fig4_payload_contract():
    """字段契约：三根轴、11 弹、共享网格、每朵点云 245 点、图例与口径全部来自 `figures`。"""
    d = fig4.build(dict(PRODUCTS), job="demo", tag="default")
    assert d["ok"] is True and d["figure"] == "fig4" and d["schema"] == fig4.SCHEMA
    assert d["kind"] == figures.FIG4_KIND
    assert d["title"] == figures.FIG4_TITLE
    assert d["job"] == "demo" and d["tag"] == "default"

    g = d["grid"]
    assert g["shape"] == [5, 7, 7] and g["n_cases"] == 245
    assert g["flat_order"] == fig4.FLAT_ORDER and g["column_span"] == 49
    assert g["dv_pin_ms"] == pytest.approx(DV_PIN_MS, abs=1e-3)
    assert [round(v, 6) for v in g["dv_factors"]] == [0.6, 0.8, 1.0, 1.2, 1.4]

    assert [m["key"] for m in d["missiles"]] == pool.names(), "弹池顺序 = pool"
    assert len(d["missiles"]) == N_MISSILES
    for m in d["missiles"]:
        assert m["n_cases"] == N_CASES_PER_MISSILE
        assert 0 <= m["n_hit"] <= m["n_cases"]
        assert m["beta"] and m["gamma"] and m["dv"], m
    for key in pool.names():
        c = d["clouds"][key]
        assert c["n"] == N_CASES_PER_MISSILE, key
        assert len(c["t"]) == len(c["resid"]) == len(c["curv"]) == N_CASES_PER_MISSILE
        assert len(c["slope"]) == len(c["intercept"]) == len(c["quad"]) == 49
        assert len(c["R_ref"]) == 49 and len(c["n_star_g"]) == 49
        assert c["n_col"] == 49

    # 三根轴的名字与单位来自 `figures`（前端不自己编）
    axes = {a["id"]: a for a in d["axes"]}
    assert set(axes) == {"beta", "gamma", "dv"}
    for aid, a in axes.items():
        assert a["label"] == figures.FIG4_AXIS_LABELS[aid]
        assert len(a["values"]) == len(a["ticks"])
    assert axes["beta"]["unit"] == "kg/m²" and axes["dv"]["unit"] == "m/s"

    # 图例 / 颜色模式 / 脚注：逐键来自 figures
    assert d["legend"]["hit"] == figures.FIG4_LEGEND_HIT
    assert d["legend"]["miss"] == figures.FIG4_LEGEND_MISS
    assert d["legend"]["fitplane"] == figures.FIG4_LEGEND_FITPLANE
    assert d["legend"]["fitcols"] == figures.FIG4_LEGEND_FITCOLS
    assert d["legend"]["induced"] == figures.FIG4_LEGEND_INDUCED
    assert [m["id"] for m in d["modes"]] == [m["id"] for m in figures.FIG4_MODES]
    assert [m["unit"] for m in d["modes"]] == [m["unit"] for m in figures.FIG4_MODES]
    assert d["modes"][0]["unit"] == "s" and "残差" in d["modes"][1]["label"]
    assert tuple(d["footnotes"]) == tuple(figures.FIG4_FOOTNOTES)
    assert [m["id"] for m in d["heatmap"]["metrics"]] == list(fig4.HEAT_METRICS)
    assert d["heatmap"]["default"] == fig4.HEAT_METRICS[0]
    assert d["axis_note"].startswith("三根轴已各自归一化到等长")
    assert d["ref_condition"]["alt_m"] == 10000.0 and d["ref_condition"]["speed_ms"] == 800.0
    assert d["induced"]["rule"].startswith("R = (n_ref/n*)²")


def test_fig4_shared_grid_and_shared_color_range():
    """**11 枚弹共用同一套网格与同一条色标范围**（切换弹种不跳色标）。

    判据要能抓住"按选中那朵点云重算色标"这个静默错误：所以除了"范围 = 全体极值"，
    还要求"**至少有一枚弹自己的范围比共享范围窄**" —— 那样一来，任何按弹重算的实现
    都会在某枚弹上给出不同的 domain。
    """
    d = fig4.build(dict(PRODUCTS))
    rng = d["shared"]["ranges"]
    assert d["shared"]["grid"] is True
    assert rng["t_hit"] is not None and rng["t_hit"][1] > rng["t_hit"][0]
    assert rng["resid"][0] == pytest.approx(-rng["resid"][1], abs=1e-9), "残差色标必须对称"
    assert rng["curv"][0] == 0.0 and rng["curv"][1] > 0

    all_t = [v for c in d["clouds"].values() for v in c["t"] if v is not None]
    assert rng["t_hit"][0] == pytest.approx(min(all_t), abs=1e-6)
    assert rng["t_hit"][1] == pytest.approx(max(all_t), abs=1e-6)
    rmax = max(abs(v) for c in d["clouds"].values() for v in c["resid"] if v is not None)
    assert rng["resid"][1] == pytest.approx(rmax, abs=1e-6)
    cmax = max(v for c in d["clouds"].values() for v in c["curv"] if v is not None)
    assert rng["curv"][1] == pytest.approx(cmax, abs=1e-6)

    narrow = [k for k, v in d["shared"]["per_missile_t_range"].items()
              if v[0] > rng["t_hit"][0] + 1e-6 or v[1] < rng["t_hit"][1] - 1e-6]
    assert narrow, "每一枚弹自己的范围都和共享范围一样 ⇒ 这条判据抓不到'按弹重算'"
    for key, (lo, hi) in d["shared"]["per_missile_t_range"].items():
        assert rng["t_hit"][0] <= lo <= hi <= rng["t_hit"][1], key
    # 每一朵点云的 t 都落在共享范围内
    for key, c in d["clouds"].items():
        vals = [v for v in c["t"] if v is not None]
        assert min(vals) >= rng["t_hit"][0] - 1e-6 and max(vals) <= rng["t_hit"][1] + 1e-6, key


def test_fig4_palette_comes_from_figures_key_by_key():
    """配色**逐键**来自 `figures`（前端零颜色字面量的唯一出处）。"""
    p = fig4.palette()
    assert p["hit"] == figures.FIG4_HIT_COLOR
    assert p["miss"] == figures.FIG4_MISS_COLOR
    assert p["bg"] == figures.FIG4_BG_COLOR
    assert p["text"] == figures.FIG4_TEXT_COLOR
    assert p["muted"] == figures.FIG4_MUTED_COLOR
    assert p["box"] == figures.FIG4_BOX_COLOR
    assert p["plane"] == figures.FIG4_PLANE_COLOR
    assert p["fit_line"] == figures.FIG4_FIT_LINE_COLOR
    assert p["hot_ring"] == figures.FIG4_HOT_RING_COLOR
    assert p["axis"] == dict(figures.FIG4_AXIS_COLORS)
    assert p["cmap"]["t_hit"] == list(figures.FIG4_CMAP_T_HIT)
    assert p["cmap"]["resid"] == list(figures.FIG4_CMAP_RESID)
    assert p["cmap"]["curv"] == list(figures.FIG4_CMAP_CURV)
    assert "figures.FIG4" in p["source"]
    d = fig4.build(dict(PRODUCTS))
    assert d["colors"] == p, "响应里的 colors 必须就是 palette()（别在 build 里另拼一份）"


def test_fig4_hit_and_miss_are_distinguishable_by_more_than_a_constant():
    """**关系**判据（不是"等于某个常量"）：命中/脱靶必须分得开，而且脱靶色**不能**是色标里的一档。

    这个仓库刚在合并时栽过"只钉等于某常量"的静默不一致，所以这里钉的是三条**关系**：
    ①命中/脱靶两色不同；②脱靶色不在 t_hit 色标里（否则会被读成"某个 t_hit 值"）；
    ③色标首末必须不同（值域全同色 = 色标失效）。再补一条**形状**关系：脱靶是空心。
    """
    p = fig4.palette()
    assert p["hit"] != p["miss"]
    cmap = list(figures.FIG4_CMAP_T_HIT)
    assert p["miss"] not in cmap, "脱靶色落在 t_hit 色标里 ⇒ 会被误读成某个命中时间"
    assert len(cmap) >= 3 and cmap[0] != cmap[-1]
    assert len(set(cmap)) == len(cmap), "色标里有重复档位"
    assert list(figures.FIG4_CMAP_RESID)[0] != list(figures.FIG4_CMAP_RESID)[-1]
    assert list(figures.FIG4_CMAP_CURV)[0] != list(figures.FIG4_CMAP_CURV)[-1]
    assert figures.FIG4_HIT_COLOR in cmap, "图例里的'命中'取样色应当是色标的一档"
    for name, hexes in (("t_hit", cmap), ("resid", list(figures.FIG4_CMAP_RESID)),
                        ("curv", list(figures.FIG4_CMAP_CURV))):
        for h in hexes:
            r, g, b = fig4.hex_to_rgb(h)
            assert 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0, (name, h)
    d = fig4.build(dict(PRODUCTS))
    assert d["markers"]["hit"] != d["markers"]["miss"]
    assert d["markers"]["miss"] == "hollow", "脱靶必须换**形状**，不能只靠颜色"


def test_fig4_miss_columns_are_not_colored_by_the_t_hit_ramp():
    """全脱靶那一档：`miss_idx` 列全，`t`/`resid`/`curv` 一律 `null`，t_hit 范围是 `None`。

    这条是"脱靶没有 t_hit 可着色"这个物理事实的机器判据 —— 若哪天用 0 兜底，
    脱靶点会被涂成色标左端色（= "命中得最快"），而画面看起来完全正常。
    """
    d = fig4.build(dict(MISS_PRODUCTS))
    clouds = d["clouds"]
    assert clouds, "产物里没有弹"
    for key, c in clouds.items():
        assert c["miss_idx"], f"{key} 这一档应当全是脱靶"
        assert sorted(c["miss_idx"]) == list(range(c["n"]))
        assert all(v is None for v in c["t"]), key
        assert all(v is None for v in c["resid"]), key
        assert all(v is None for v in c["curv"]), key
        assert all(v is None for v in c["slope"]), "整列脱靶 ⇒ 该列不参与拟合（不能补 0）"
    assert d["shared"]["ranges"]["t_hit"] is None, "一个命中点都没有 ⇒ 没有共享 t_hit 范围"
    assert d["missiles"][0]["n_hit"] == 0
    # 有命中的那一档：miss_idx 与 t 的 null 位置必须**一一对应**
    dd = fig4.build(dict(PRODUCTS))
    for key, c in dd["clouds"].items():
        nulls = [i for i, v in enumerate(c["t"]) if v is None]
        assert nulls == list(c["miss_idx"]), key


def test_fig4_induced_drag_columns_match_bg_and_ignore_the_missile():
    """判别量（`n*` / `R`）只随 (β,γ) 与参考工况变，**与哪枚弹无关**。

    物理上必然如此（`Q = sqrt(βγF/f)`），但"每枚弹各算一遍"很容易写成"各存一份、值不同"——
    所以这里既钉"11 枚逐值相同"，也用 `bg.evaluate()` **独立复算**前几列对拍。
    """
    rec = fig4.read_record(PRODUCTS["record"])
    grid = rec["grid"]
    ref = rec["ref_condition"]
    first = None
    for m in rec["missiles"]:
        cols = m["columns"]
        assert len(cols["R_ref"]) == 49 and len(cols["n_star_g"]) == 49
        if first is None:
            first = (list(cols["R_ref"]), list(cols["n_star_g"]))
        else:
            assert cols["R_ref"] == first[0], "判别量不该随弹变"
            assert cols["n_star_g"] == first[1]
        assert cols["induced"] == [1 if v >= 1.0 else 0 for v in cols["R_ref"]]
    betas = grid["beta"]
    gammas = grid["gamma"]
    k = 0
    for g in gammas:
        for b in betas:
            e = bg.evaluate(b, g, alt_m=ref["alt_m"], speed_ms=ref["speed_ms"],
                            n=rec["n_ref"])
            assert first[1][k] == pytest.approx(e.n_star, rel=1e-9, abs=1e-9), (b, g)
            assert first[0][k] == pytest.approx(e.ratio, rel=1e-9, abs=1e-9), (b, g)
            k += 1
    assert k == 49
    d = fig4.build(dict(PRODUCTS))
    assert d["induced"]["columns_total"] == 11 * 49
    assert 0 <= d["induced"]["n_columns"] <= 49
    assert d["induced"]["n_columns_total"] == d["induced"]["n_columns"] * 11


def test_fig4_column_fit_agrees_with_an_independent_polyfit():
    """逐列拟合的**第二条路径**：直接用 `np.polyfit` 复算，逐值对拍。

    （`bg3d.dv_linearity/dv_quadratic` 是同一族口径的全场摘要；这里选 `polyfit` 是因为它
    与 `fit_columns` 的 `lstsq` 是两条独立的数值路径。）
    """
    rec = fig4.read_record(PRODUCTS["record"])
    dv = np.asarray(rec["grid"]["dv"], dtype=float)
    m = rec["missiles"][0]
    cube = np.asarray([[m["t_hit"][i][j] for j in range(7)] for i in range(5)], dtype=float)
    fit = fig4.fit_columns(cube, dv)
    nb, ng = 7, 7
    for col in range(nb * ng):
        j, k = divmod(col, nb)
        y = cube[:, j, k]
        if not np.isfinite(y).all():
            assert not fit["ok"][col]
            continue
        lin = np.polyfit(dv, y, 1)
        quad = np.polyfit(dv, y, 2)
        assert fit["slope"][col] == pytest.approx(lin[0], rel=1e-9), col
        assert fit["intercept"][col] == pytest.approx(lin[1], rel=1e-9), col
        assert fit["quad"][col] == pytest.approx(quad[0], rel=1e-9), col
        resid = y - (fit["intercept"][col] + fit["slope"][col] * dv)
        assert fit["rms_lin"][col] == pytest.approx(float(np.sqrt((resid ** 2).mean())),
                                                   rel=1e-9), col
        # 二次项贡献：c·(ΔV − ΔV̄)²，且在两端取到极值
        qt = fit["quad_term"][:, col]
        # `ΔV` 的 5 个点是**关于均值对称**的（0.6/0.8/1.0/1.2/1.4 × 钉值），所以两端贡献相等；
        # 容差给 1e-6 s：网格点是 `round(...,4)` 出来的，两端离均值差在 1e-9 量级。
        assert qt[0] == pytest.approx(qt[-1], abs=1e-6), col
        assert qt.min() >= -1e-12, "二次项贡献只有在 c 为负时才可能为负，这里给的是 c·(…)^2"
        # curv_span 与 bg3d 的口径一致：|c|·span²/4
        span = float(dv.max() - dv.min())
        expect = abs(fit["quad"][col]) * span ** 2 / 4.0
        assert fit["curv_span"][col] == pytest.approx(expect, rel=1e-9), col


# ============================================================ 2. 证据层：能证伪


def _synth_grid():
    """用**产物里的真实网格**做合成数据（这样 β/γ/ΔV 的跨度就是图上的那套）。"""
    rec = fig4.read_record(PRODUCTS["record"])
    return (np.asarray(rec["grid"]["beta"], float),
            np.asarray(rec["grid"]["gamma"], float),
            np.asarray(rec["grid"]["dv"], float))


def _synth_cube(beta, gamma, dv, kind: str):
    """两组合成数据：

    * `"shift"` —— **ΔV 只造成平移**：`t = base(β,γ) + b·ΔV`，一阶就该完全解释掉；
    * `"curve"` —— **强曲率，而且只在大 γ 列**：低 γ 列仍是直线，高 γ 列加一个开口向上的
      二次项（幅度 8 s / ±373 m/s）。热点因此必须落在最大 γ 那一行。
    """
    out = np.zeros((len(dv), len(gamma), len(beta)))
    for i, d_v in enumerate(dv):
        for j, g in enumerate(gamma):
            for k, b in enumerate(beta):
                base = 52.0 + 0.002 * (b - beta[0]) - 0.05 * (g - gamma[0])
                lin = -0.03 * (d_v - dv[len(dv) // 2])
                bend = 0.0
                if kind == "curve" and g >= gamma[len(gamma) // 2]:
                    bend = 8.0 * ((d_v - dv[len(dv) // 2]) / 400.0) ** 2
                out[i, j, k] = base + lin + bend
    return out


def test_fig4_evidence_separates_translation_from_curvature():
    """**要求"能证伪"**：残差与曲率判据必须真的把两组数据分开。

    这不是"跑一遍不报错"，而是：平移组的残差/曲率必须是**机器零**，曲率组必须**远大于**它，
    两组之间至少差 3 个数量级 —— 判据失效（例如把残差算成 `t − t̄`）当场红。
    """
    beta, gamma, dv = _synth_grid()
    shift = _synth_cube(beta, gamma, dv, "shift")
    curve = _synth_cube(beta, gamma, dv, "curve")
    fs = fig4.fit_columns(shift, dv)
    fc = fig4.fit_columns(curve, dv)

    assert fs["ok"].all() and fc["ok"].all()
    shift_res = float(np.nanmax(np.abs(fs["resid_lin"])))
    curve_res = float(np.nanmax(np.abs(fc["resid_lin"])))
    assert shift_res < 1e-9, f"平移组不该有残差：{shift_res}"
    assert curve_res > 1.0, f"曲率组的残差太小，判据没有牙：{curve_res}"
    assert curve_res / max(shift_res, 1e-12) > 1e6, (shift_res, curve_res)

    assert float(np.nanmax(np.abs(fs["curv_frac"]))) < 1e-9, "平移组不该有曲率占比"
    assert float(np.nanmax(fc["curv_frac"])) > 0.2, "曲率组的曲率占比太小"
    assert float(np.nanmax(fc["curv_span"])) > 5.0, "曲率组的端点抬升应当有若干秒"
    # 二次项拟合把残差吃掉：曲线组二次残差必须远小于一次残差
    assert float(np.nanmax(fc["rms_quad"])) < float(np.nanmax(fc["rms_lin"])) / 50.0
    # 而平移组本来就该是"一条斜率"：一次拟合的 R² 意义上的残差已是机器零
    assert float(np.nanmax(fs["rms_lin"])) < 1e-9
    # 全局平面在曲线组上一定拟合不动（这也是"平面假设失效"的直接证据）
    pl_s = fig4.plane_fit(shift, beta, gamma, dv)
    pl_c = fig4.plane_fit(curve, beta, gamma, dv)
    assert pl_s["rms_s"] < 1e-9 and pl_c["rms_s"] > 1.0, (pl_s["rms_s"], pl_c["rms_s"])


def test_fig4_heatmap_hot_cell_follows_the_curved_gamma_rows():
    """β–γ 小面板的热点必须落在**真正弯了的那几行 γ** 上（合成数据：只有大 γ 弯）。

    再加上"平移组没有热点"这条 —— 否则"热点永远等于最右上角"也能过。
    """
    beta, gamma, dv = _synth_grid()
    shape = (len(gamma), len(beta))
    fs = fig4.fit_columns(_synth_cube(beta, gamma, dv, "shift"), dv)
    fc = fig4.fit_columns(_synth_cube(beta, gamma, dv, "curve"), dv)
    hs = fig4.heat_values(fs, n_beta=len(beta), n_gamma=len(gamma))
    hc = fig4.heat_values(fc, n_beta=len(beta), n_gamma=len(gamma))
    assert hs["curv"].shape == shape and hc["curv"].shape == shape
    assert float(np.nanmax(hs["curv"])) < 1e-9
    hot = fig4.max_cell(hc["curv"])
    assert hot is not None and hot["i_gamma"] >= len(gamma) // 2, hot
    assert hot["value"] > 0.2, hot
    # 低 γ 那几行必须干净（合成数据里它们就是直线）
    assert float(np.nanmax(hc["curv"][:len(gamma) // 2])) < 1e-9
    # 残差口径的热点也在大 γ 行
    hot_r = fig4.max_cell(hc["resid"])
    assert hot_r is not None and hot_r["i_gamma"] >= len(gamma) // 2, hot_r
    assert fig4.max_cell(np.full(shape, np.nan)) is None


# ============================================================ 3. 与 bg3d 的数值一致性


def test_fig4_t_hit_matches_bg3d_on_every_corner():
    """**两条独立路径**在同一个 (β,γ,ΔV) 上各算一次：`t_hit` 必须一致（容差 1e-6 s）。

    路径 A = `fig4scan.scan_missile`（本图4 的算核：弹在外层、ΔV 在内层）；
    路径 B = `bg3d.scan3`（上一轮的 spike：单弹、ΔV 外层）。
    两条都走同一个 `solver.run`，所以期待**逐位相同**；给 1e-6 s 的余量是为了不把
    编译路径/求和顺序的浮点噪声当回归 —— 但轴序接反、乘数接错这类错误差的是**秒**，
    一定跑不掉。
    """
    grid = bg3d.Bg3Grid(beta=(2500.0, 3000.0), gamma=(50.0, 90.0), dv=(700.0, 1000.0),
                        beta_step=500.0, gamma_step=40.0, dv_step=300.0)
    assert grid.shape == (2, 2, 2) and grid.n_cases == 8
    scene = Scene()
    entry = pool.resolve("PL-12")

    mine = fig4scan.scan_missile(scene, entry, grid, tier="fast", jobs=1, cache=False)
    ref = bg3d.scan3(scene, standard="PL-12", grid=grid, tier="fast", jobs=1, cache=False)

    assert mine["t_hit"].shape == ref.t_hit.shape == grid.shape
    np.testing.assert_allclose(mine["t_hit"], ref.t_hit, rtol=0, atol=BETA3D_TOL_S,
                               equal_nan=True)
    np.testing.assert_array_equal(mine["hit"], ref.hit)
    np.testing.assert_allclose(mine["dv_measured"], ref.dv_measured, rtol=1e-9, atol=1e-6,
                               equal_nan=True)
    assert mine["n_hit"] == ref.n_hit and mine["n_ok"] == ref.n_ok
    assert mine["n_run"] == ref.n_run == 8
    assert mine["n_cached"] == ref.n_cached == 0
    assert mine["backend"] == ref.backend, "两条路径必须落在同一个档位/后端上"
    # 本图4 的立方体里至少要有一个命中，否则 `assert_allclose(equal_nan=True)` 形同虚设
    assert mine["n_hit"] >= 1 and int(np.isfinite(mine["t_hit"]).sum()) == mine["n_hit"]


def test_fig4_scan_one_case_matches_a_direct_engine_run():
    """第三条路径（最独立的一条）：手搓 `Engine.one(...)` 单算一个格点，与算核逐值对拍。"""
    grid = bg3d.Bg3Grid(beta=(2700.0,), gamma=(60.0,), dv=(DV_PIN_MS,),
                        beta_step=300.0, gamma_step=20.0, dv_step=100.0)
    scene = Scene()
    entry = pool.resolve("PL-12")
    mine = fig4scan.scan_missile(scene, entry, grid, tier="fast", jobs=1, cache=False)
    point = bg.point_of(entry)
    metrics = pool.metrics_of(entry)
    from missile_sim.engine import Engine

    eng = Engine(scene, missile=entry.native, tier="fast", jobs=1, cache=False, metrics=metrics,
                 scaling_of=lambda b, g: bg3d.scaling3_for(point, metrics, beta=b, gamma=g,
                                                           dv=grid.dv[0]))
    try:
        got = eng.one(grid.beta[0], grid.gamma[0])
    finally:
        eng.close()
    assert got.ok and got.hit
    assert mine["t_hit"][0, 0, 0] == pytest.approx(float(got.t_hit), abs=BETA3D_TOL_S)
    assert mine["dv_measured"][0, 0, 0] == pytest.approx(float(got.dv_measured), rel=1e-9)


# ============================================================ 4. 产物 / CSV 契约


def test_fig4_payload_is_strict_json():
    """响应必须是**严格 JSON**：`allow_nan=False` 下也要能 dump。

    裸 `NaN` 在 Python 里读得回来、在 JS 里是 `JSON.parse` 直接抛错（页面白屏）——
    全脱靶那一档的拟合全是 `nan`，正是这条的活样本（`plane.rms_s` 与逐列 `slope` 都是）。
    """
    for paths in (PRODUCTS, MISS_PRODUCTS):
        d = fig4.build(dict(paths))
        blob = json.dumps(d, ensure_ascii=False, allow_nan=False)
        assert "NaN" not in blob and "Infinity" not in blob
        back = json.loads(blob)
        assert back["figure"] == "fig4"
    d = fig4.build(dict(MISS_PRODUCTS))
    pl = d["fit"]["plane"]["R-77"]
    assert pl["n"] < 4 and pl["coef"] is None and pl["rms_s"] is None, pl
    assert all(v is None for v in d["clouds"]["R-77"]["slope"])


def test_fig4_cases_csv_contract():
    """逐工况表：列名固定、**每工况一行**（11×245）、判别量只随 (β,γ) 变。"""
    rec = fig4.read_record(PRODUCTS["record"])
    rows = fig4.read_csv_rows(PRODUCTS["cases"])
    assert tuple(rows[0].keys()) == record.FIG4_CASES
    assert len(rows) == N_MISSILES * N_CASES_PER_MISSILE
    per = {}
    for r in rows:
        per.setdefault(r["missile"], []).append(r)
    assert sorted(per) == sorted(pool.names())
    for key, got in per.items():
        assert len(got) == N_CASES_PER_MISSILE, key
    # 每弹的 5 层 ΔV × 49 列：同一根 (β,γ) 竖线上 5 行必须同判别量
    got = per["PL-12"]
    by_col = {}
    for r in got:
        by_col.setdefault((r["beta_target"], r["gamma_target"]), []).append(r)
    assert len(by_col) == 49
    for cell, group in by_col.items():
        assert len(group) == 5, cell
        assert len({g["induced_dominated"] for g in group}) == 1, cell
        assert len({g["R_ref"] for g in group}) == 1, cell
        assert len({g["n_star_g"] for g in group}) == 1, cell
        assert len({g["dv_target"] for g in group}) == 5, "5 层 ΔV 必须各一行"
    # 命中行的 t_hit 与 JSON 立方体对得上（取 PL-12 的一个格点）
    m = [x for x in rec["missiles"] if x["key"] == "PL-12"][0]
    found = [r for r in got if r["hit"] == "1"][0]
    # ⚠ CSV 里的数字是 `%.6g`（"746.056"），JSON 里是 746.0558 —— **不能**直接 `list.index`，
    #   要按最近值找（这条正是"看着一样、其实不等"的那种坑）。
    def _nearest(seq, target):
        return min(range(len(seq)), key=lambda i: abs(float(seq[i]) - float(target)))

    i = _nearest(rec["grid"]["dv"], found["dv_target"])
    j = _nearest(rec["grid"]["gamma"], found["gamma_target"])
    k = _nearest(rec["grid"]["beta"], found["beta_target"])
    assert abs(rec["grid"]["dv"][i] - float(found["dv_target"])) < 1.0
    assert abs(rec["grid"]["gamma"][j] - float(found["gamma_target"])) < 0.05
    assert abs(rec["grid"]["beta"][k] - float(found["beta_target"])) < 1.0
    assert float(found["t_hit_s"]) == pytest.approx(m["t_hit"][i][j][k], rel=1e-5)
    assert float(found["miss_distance_m"]) >= 0


def test_fig4_miss_cases_csv_leaves_t_hit_empty():
    """全脱靶那一档：CSV 里 `t_hit_s` 必须**留空**（不是 0），`hit` 是 0，近炸距离仍要写。"""
    rows = fig4.read_csv_rows(MISS_PRODUCTS["cases"])
    assert rows and all(r["hit"] == "0" for r in rows)
    assert all(r["t_hit_s"] == "" for r in rows), "脱靶不能写 0（那会被读成'瞬间命中'）"
    assert all(r["t_end_s"] != "" for r in rows)
    assert all(r["miss_distance_m"] != "" for r in rows)
    assert all(r["induced_dominated"] in ("0", "1") for r in rows)


def test_fig4_json_record_shape_and_summary():
    """记录的结构：立方体形状 = 网格、命中掩码 0/1、`n_run + n_cached == n_cases`。"""
    rec = fig4.read_record(PRODUCTS["record"])
    assert rec["schema"] == fig4.SCHEMA and rec["figure"] == "fig4"
    assert tuple(rec["summary"]["shape"]) == (5, 7, 7)
    assert rec["summary"]["n_cases"] == 245
    assert rec["summary"]["n_total"] == N_MISSILES * 245
    assert rec["summary"]["n_run"] + rec["summary"]["n_cached"] == rec["summary"]["n_total"]
    assert rec["grid"]["beta_step"] > 0 and rec["grid"]["gamma_step"] > 0
    for m in rec["missiles"]:
        assert len(m["t_hit"]) == 5 and len(m["t_hit"][0]) == 7 and len(m["t_hit"][0][0]) == 7
        assert len(m["hit"]) == 5 and len(m["fit"]["slope"]) == 49
        assert len(m["fit"]["resid_lin"]) == 245 and len(m["fit"]["quad_term"]) == 245
        flat = [int(v) for plane in m["hit"] for row in plane for v in row]
        assert set(flat) <= {0, 1}
        t_flat = [v for plane in m["t_hit"] for row in plane for v in row]
        assert sum(1 for v in t_flat if v is not None) == m["n_hit"] == sum(flat)
        assert m["plane"]["n"] == sum(1 for v in t_flat if v is not None)

# ============================================================ 9. CLI 端到端（小网格）


def test_fig4_cli_regenerates_products_end_to_end(tmp_path):
    """`python -m missile_sim --figure fig4` 一条命令重出两份产物（小网格：8 工况）。"""
    tag = "cli_unittest"
    # ⚠ 必须**继承 os.environ**：matplotlib 装在用户 site-packages
    # （`%APPDATA%\Python\...\site-packages`），只给三个变量会让子进程算不出那个目录，
    # 于是 `import figures` 直接 ModuleNotFoundError（实测踩过）。
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(ROOT / "src")})
    proc = subprocess.run(
        [sys.executable, "-m", "missile_sim", "--figure", "fig4", "--tag", tag,
         "--missiles", "PL-12", "--fig4-beta-n", "2", "--fig4-gamma-n", "2",
         "--fig4-dv-factors", "0.9,1.1", "--jobs", "2", "--quiet"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    paths = fig4.default_paths(tag)
    try:
        assert Path(paths["record"]).is_file() and Path(paths["cases"]).is_file()
        rec = fig4.read_record(paths["record"])
        assert rec["figure"] == "fig4" and rec["tag"] == tag
        assert rec["summary"]["shape"] == [2, 2, 2]
        assert rec["summary"]["n_total"] == 8
        rows = fig4.read_csv_rows(paths["cases"])
        assert len(rows) == 8 and {r["missile"] for r in rows} == {"PL-12"}
        assert rec["standard"] == "PL-12"
        d = fig4.build(paths, tag=tag)                       # 产物能被查看器读回来
        assert d["grid"]["shape"] == [2, 2, 2] and len(d["clouds"]) == 1
        assert d["shared"]["ranges"]["t_hit"] is not None
        assert d["missiles"][0]["n_hit"] == rec["summary"]["n_hit"]
    finally:
        for p in paths.values():
            Path(p).unlink(missing_ok=True)

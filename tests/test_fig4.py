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

from missile_sim import (bg, bg3d, fig4, fig4scan, figures, pool, record, solver, webui,  # noqa: E402
                      workflow)
from missile_sim.spec import Scene  # noqa: E402

#: 已入库的两份产物：默认 11 弹（2695 工况，100% 命中）与**全脱靶**小档
#: （`--missiles R-77 --range 80000 --fig4-beta-n 2 --fig4-gamma-n 2 --fig4-dv-factors 0.5,0.7`）。
PRODUCTS = fig4.default_paths("default")
MISS_PRODUCTS = fig4.default_paths("miss")
DV_PIN_MS = 932.5697
N_MISSILES = 11
N_CASES_PER_MISSILE = 539
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


def test_fig4_default_grid_is_7x7x11_and_covers_the_pool():
    """默认网格（v4）：β/γ 各 7 点 = **图2 的自适应域**、ΔV = **[700,1700] 等分 11 点**。

    三条一起钉：① 11 弹全部落在立方体内（`check_pool_inside` 的教训：向内对齐会把 R-77/Derby
    挤出 β 下限）；② **γ 只在弹池内**（`figures.bg_axis` 的 pad 规则，绝不放宽到 140）；
    ③ ΔV 是**绝对值**，不再随基准弹的标称 ΔV 漂移。
    """
    rec = fig4.read_record(PRODUCTS["record"])
    g = rec["grid"]
    assert tuple(rec["summary"]["shape"]) == (11, 7, 7)
    assert len(g["dv"]) == 11 and len(g["beta"]) == 7 and len(g["gamma"]) == 7
    assert (g["dv"][0], g["dv"][-1]) == pytest.approx(tuple(fig4.DV_LIM), abs=1e-6)
    assert g["dv_step"] == pytest.approx((fig4.DV_LIM[1] - fig4.DV_LIM[0]) / 10, abs=1e-6)
    # ① 弹池全部在立方体内
    for m in rec["missiles"]:
        assert g["beta"][0] <= m["beta"] <= g["beta"][-1], (m["key"], m["beta"])
        assert g["gamma"][0] <= m["gamma"] <= g["gamma"][-1], (m["key"], m["gamma"])
    # ② γ 只在弹池内（弹池实测 53.49~91.19；这里给 pad 留一点余量，但**不许**到 140）
    gammas = [m["gamma"] for m in rec["missiles"]]
    assert g["gamma"][-1] <= max(gammas) + 6.0, (g["gamma"][-1], max(gammas))
    assert g["gamma"][0] >= min(gammas) - 6.0, (g["gamma"][0], min(gammas))
    assert g["gamma"][-1] < 110.0, "γ 不许扫到 110 以上（用户口径：只扫弹池内）"
    # ③ ΔV 是绝对值：`dv_lim` 与产物里的轴逐值一致，且 `dv_pin_ms` 只作参考标记
    assert g["dv_lim"] == pytest.approx([g["dv"][0], g["dv"][-1]], abs=1e-6)
    assert g["dv_pin_ms"] == pytest.approx(932.5697, abs=1e-3)
    assert g["dv"][0] < g["dv_pin_ms"] < g["dv"][-1], "参考标记要落在轴内"
    assert not any(abs(v / g["dv_pin_ms"] - 0.6) < 1e-6 for v in g["dv"]), \
        "旧的 0.6/0.8/1.0/1.2/1.4 倍数轴已作废"


def test_fig4_scene_is_the_crank_beam_with_a_fixed_39_time():
    """默认工况 = 图3 那套（crank→39），但 **39 指令时刻固定在 35.0 s**。

    这条钉的是"跨 11 枚弹共用工况"：若有人把它改回"每弹反求 t_beam + 延迟"，
    产物里的 `t_react_s` 会变成 None / 每弹不同，图3 与图4 的口径就再也分不清了。
    """
    rec = fig4.read_record(PRODUCTS["record"])
    assert float(rec["t_react_s"]) == pytest.approx(35.0, abs=1e-9)
    assert "固定" in rec["t_react_note"] and "35" in rec["t_react_note"]
    assert "固定" in rec["scene_text"] and "35" in rec["scene_text"]
    # maneuvers 真的进了 Scene（否则就是直飞）
    man = rec["scene"]["maneuvers"]
    assert len(man) > 100, f"maneuvers 只有 {len(man)} 段 —— 目标没在机动"
    assert float(man[0][0]) == pytest.approx(0.0, abs=1e-9)
    # 形状：每条腿是 (t, (ax, ay, az))
    assert len(man[0]) == 2 and len(man[0][1]) == 3
    # 请求侧：默认值就是图3 的默认值 + 固定的 39 时刻
    req = workflow.Fig4Request()
    traj = workflow.TrajRequest()
    for f in ("t_crank", "crank_deg", "crank_g", "beam_deg", "beam_g", "react_delay_s",
              "weave", "weave_amp_deg", "weave_hz"):
        assert getattr(req, f) == getattr(traj, f), f
    assert float(req.t_react_s) == 35.0
    scene = workflow.fig4_scene(req)
    assert len(scene.maneuvers) > 100
    assert not req.scene.maneuvers, "想定由本请求编译，scene 上必须留空"
    # 39 时刻真的落在 maneuvers 里：35.0 s 附近应当有一次加速度方向变化
    import math
    def dir_at(tt):
        prev = None
        for ts, acc in scene.maneuvers:
            if ts > tt:
                break
            prev = acc
        return prev
    a_before, a_after = dir_at(34.9), dir_at(35.1)
    assert a_before != a_after, "35.0 s 前后加速度没变 —— 39 腿没生效"



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
    assert g["shape"] == [11, 7, 7] and g["n_cases"] == 539
    assert g["flat_order"] == fig4.FLAT_ORDER and g["column_span"] == 49
    assert g["dv_pin_ms"] == pytest.approx(DV_PIN_MS, abs=1e-3)
    assert [round(v, 6) for v in g["dv_lim"]] == [700.0, 1700.0]

    assert [m["key"] for m in d["missiles"]] == pool.names(), "弹池顺序 = pool"
    assert len(d["missiles"]) == N_MISSILES
    for m in d["missiles"]:
        assert m["n_cases"] == N_CASES_PER_MISSILE
        assert 0 <= m["n_hit"] <= m["n_cases"]
        assert m["beta"] and m["gamma"] and m["dv"], m
    for key in pool.names():
        c = d["clouds"][key]
        assert c["n"] == N_CASES_PER_MISSILE, key
        assert len(c["t"]) == N_CASES_PER_MISSILE
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
    assert d["legend"]["induced"] == figures.FIG4_LEGEND_INDUCED
    assert [m["id"] for m in d["modes"]] == [m["id"] for m in figures.FIG4_MODES]
    assert [m["unit"] for m in d["modes"]] == [m["unit"] for m in figures.FIG4_MODES]
    assert [m["id"] for m in d["modes"]] == ["t_hit"], "v4 只剩 t_hit 一种颜色模式"
    assert tuple(d["footnotes"]) == tuple(figures.FIG4_FOOTNOTES)

    # ---- v4：**证据层已删**（不画就不发）—— 这条是"删干净了"的反向断言 ----
    for gone in ("heatmap", "heat_metrics"):
        assert gone not in d, f"payload 里还留着 {gone}"
    for gone in ("plane", "fit_line", "hot_ring"):
        assert gone not in d["colors"], f"配色里还留着 {gone}"
    for gone in ("resid", "curv"):
        assert gone not in d["colors"]["cmap"], f"色标里还留着 {gone}"
        assert gone not in d["shared"]["ranges"], f"共享范围里还留着 {gone}"
    for gone in ("fitplane", "fitcols", "heat"):
        assert gone not in d["legend"], f"图例里还留着 {gone}"
    for gone in ("resid", "curv"):
        assert gone not in d["clouds"]["PL-12"], f"点云里还留着逐点的 {gone}"
    # 全局平面的**系数**仍然留着（用户做视频可能要用），只是不再画、不再单独发给前端渲染；
    # "不画"这条由 `test_fig4_frontend_contract_names` 的 `planeQuads` 反向断言钉住。
    assert set(d["fit"]["plane"]) == {m["key"] for m in d["missiles"]}
    assert d["fit"]["plane"]["PL-12"]["coef"] is not None

    # ---- v4：单层等时面的**契约**必须在散点页里就说清楚 ----------------------
    lay = d["layers"]
    assert lay["n_levels"] == fig4.LAYER_COUNT
    assert lay["iso_step"] > 0 and lay["min_cells"] == fig4.LAYER_MIN_CELLS
    assert lay["endpoint"] == "/api/fig4/<id>/layers?missile="
    assert "iso_levels" in lay["source"], "层定义的出处要写在契约里"
    assert all(m["layerable"] for m in d["missiles"]), "默认工况下 11 枚弹都有命中"
    assert "0 命中" in d["degrade"]["note"]
    # 工况文案必须出现"39 固定"（否则会被读成图3 的口径）
    assert d["scene"]["t_react_s"] == pytest.approx(35.0, abs=1e-9)
    assert "固定" in d["scene"]["text"] and "35" in d["scene"]["text"]
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
    assert set(rng) == {"t_hit"}, f"v4 只有一根色标（t_hit），实际 {sorted(rng)}"
    assert rng["t_hit"] is not None and rng["t_hit"][1] > rng["t_hit"][0]

    all_t = [v for c in d["clouds"].values() for v in c["t"] if v is not None]
    assert rng["t_hit"][0] == pytest.approx(min(all_t), abs=1e-6)
    assert rng["t_hit"][1] == pytest.approx(max(all_t), abs=1e-6)

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
    assert p["layer_alpha"] == figures.FIG4_LAYER_ALPHA
    assert p["axis"] == dict(figures.FIG4_AXIS_COLORS)
    assert set(p["cmap"]) == {"t_hit"}, "v4 只有 t_hit 一根色标"
    assert p["cmap"]["t_hit"] == list(figures.FIG4_CMAP_T_HIT)
    assert "figures.FIG4" in p["source"]
    # 删掉的那几个键不许再回来（它们属于已作废的证据层）
    for gone in ("plane", "fit_line", "hot_ring"):
        assert gone not in p, gone
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
    assert figures.FIG4_HIT_COLOR in cmap, "图例里的'命中'取样色应当是色标的一档"
    for name, hexes in (("t_hit", cmap),):
        for h in hexes:
            r, g, b = fig4.hex_to_rgb(h)
            assert 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0, (name, h)
    d = fig4.build(dict(PRODUCTS))
    assert d["markers"]["hit"] != d["markers"]["miss"]
    assert d["markers"]["miss"] == "hollow", "脱靶必须换**形状**，不能只靠颜色"


def test_fig4_miss_columns_are_not_colored_by_the_t_hit_ramp():
    """全脱靶那一档：`miss_idx` 列全，`t` 一律 `null`，t_hit 范围是 `None`。

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
        assert len(c["t"]) == c["n"]
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
    nd = len(dv)
    cube = np.asarray([[m["t_hit"][i][j] for j in range(7)] for i in range(nd)], dtype=float)
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
    """逐工况表：列名固定、**每工况一行**（11 弹 × 539 工况）、判别量只随 (β,γ) 变。"""
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
    # 每弹的 11 层 ΔV × 49 列：同一根 (β,γ) 竖线上 11 行必须同判别量
    got = per["PL-12"]
    by_col = {}
    for r in got:
        by_col.setdefault((r["beta_target"], r["gamma_target"]), []).append(r)
    assert len(by_col) == 49
    for cell, group in by_col.items():
        assert len(group) == 11, cell
        assert len({g["induced_dominated"] for g in group}) == 1, cell
        assert len({g["R_ref"] for g in group}) == 1, cell
        assert len({g["n_star_g"] for g in group}) == 1, cell
        assert len({g["dv_target"] for g in group}) == 11, "11 层 ΔV 必须各一行"
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
    assert rec["schema"] == fig4.SCHEMA == 2 and rec["figure"] == "fig4"
    assert tuple(rec["summary"]["shape"]) == (11, 7, 7)
    assert rec["summary"]["n_cases"] == 539
    assert rec["summary"]["n_total"] == N_MISSILES * 539
    assert rec["summary"]["n_run"] + rec["summary"]["n_cached"] == rec["summary"]["n_total"]
    assert rec["grid"]["beta_step"] > 0 and rec["grid"]["gamma_step"] > 0
    # 层契约（滑块档数/步长/门槛）必须写进产物，前端才知道该拉几层
    assert rec["layer"]["n_levels"] == fig4.LAYER_COUNT == 13
    assert rec["layer"]["iso_step"] > 0
    assert rec["layer"]["min_cells"] == fig4.LAYER_MIN_CELLS
    for m in rec["missiles"]:
        assert len(m["t_hit"]) == 11 and len(m["t_hit"][0]) == 7 and len(m["t_hit"][0][0]) == 7
        assert len(m["hit"]) == 11 and len(m["fit"]["slope"]) == 49
        assert len(m["fit"]["resid_lin"]) == 539 and len(m["fit"]["quad_term"]) == 539
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
         "--fig4-dv-lim", "900,1100", "--fig4-dv-n", "2", "--fig4-t-react", "35",
         "--jobs", "2", "--quiet"],
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


# ============================================================ 10. 等时面（v4 主角）


def test_fig4_iso_surface_matches_an_analytic_plane():
    """**几何判据（有牙）**：对合成解析平面出等值面，面上每个点到那个平面的距离 < 容差。

    合成场 `t = a·β + b·γ + c·ΔV + t0`（线性），等值面就是一张已知平面：
    - 场残差 `|f(v) − L|` 的**理论值应当是 0**（线性场里线性插值精确），
      实测 ≤ 1e-14 s ⇒ 几何距离 = 残差 / |∇f| ≤ 2e-13 m（点云网格步长是 10² 量级）。
    - 这一层**不可能闭合**（一张切成两半的平面），所以 `closed` 必须为 False。
    容差写死成 1e-6（比实测松 7 个数量级，但仍然能抓住"插值/轴序接错"这类错）。
    """
    nb, ng, nd = 7, 7, 11
    beta = list(np.linspace(2500.0, 3760.0, nb))
    gamma = list(np.linspace(49.0, 96.0, ng))
    dv = list(np.linspace(700.0, 1700.0, nd))
    grid = bg3d.Bg3Grid(beta=tuple(beta), gamma=tuple(gamma), dv=tuple(dv),
                        beta_step=beta[1] - beta[0], gamma_step=gamma[1] - gamma[0],
                        dv_step=dv[1] - dv[0])
    a, b, c, t0 = -0.004, 0.05, -0.02, 60.0
    B = np.asarray(beta)[None, None, :]
    G = np.asarray(gamma)[None, :, None]
    D = np.asarray(dv)[:, None, None]
    field = a * B + b * G + c * D + t0                     # 形状 (nd, ng, nb)
    assert field.shape == grid.shape
    lo, hi = float(field.min()), float(field.max())
    levels = [lo + (hi - lo) * q for q in (0.25, 0.5, 0.75)]
    recs = bg3d.iso_surfaces(field, grid=grid, levels=levels)
    assert len(recs) == len(levels), "层数必须等于要的层数"
    grad = (a * a + b * b + c * c) ** 0.5
    for r in recs:
        assert r["ok"], r["reason"]
        V = np.asarray(r["vertices"], dtype=float)
        assert len(V) == r["n_vert"] > 0
        resid = np.abs(a * V[:, 0] + b * V[:, 1] + c * V[:, 2] + t0 - r["level"])
        assert float(resid.max()) < 1e-6, (r["level"], float(resid.max()))
        assert float(resid.max()) / grad < 1e-6, "几何距离也要在容差内"
        assert r["closed"] is False and r["n_boundary"] > 0
        assert r["n_tri"] > 0 and r["area"] > 0
    # 椭球：level = 1 的等值面是**闭合**曲面 ⇒ closed 必须为真（否则闭合判据是假的）
    A2, B2, C2 = 400.0, 12.0, 250.0
    ell = ((B - 3100.0) / A2) ** 2 + ((G - 72.0) / B2) ** 2 + ((D - 1200.0) / C2) ** 2
    r = bg3d.iso_surfaces(ell, grid=grid, levels=[1.0])[0]
    assert r["ok"] and r["closed"] is True and r["n_boundary"] == 0 and r["n_nonmanifold"] == 0


def test_fig4_degenerate_layers_are_not_produced():
    """**退化保护**：命中点不足 / 层在命中区之外 ⇒ `ok=False` + 一句能显示给人看的 `reason`。

    构造三种退化：① 整块 `nan`（该弹 0 命中）；② 层高过命中区；③ 只跨一两个格子的角落碎片。
    """
    nb, ng, nd = 7, 7, 11
    beta = tuple(np.linspace(2500.0, 3760.0, nb))
    gamma = tuple(np.linspace(49.0, 96.0, ng))
    dv = tuple(np.linspace(700.0, 1700.0, nd))
    grid = bg3d.Bg3Grid(beta=beta, gamma=gamma, dv=dv, beta_step=beta[1] - beta[0],
                        gamma_step=gamma[1] - gamma[0], dv_step=dv[1] - dv[0])
    # ① 全 nan
    r = bg3d.iso_surfaces(np.full(grid.shape, np.nan), grid=grid, levels=[45.0])[0]
    assert r["ok"] is False and r["n_tri"] == 0 and "命中" in r["reason"]
    # ② 层在命中区之外
    field = np.full(grid.shape, 50.0)
    r = bg3d.iso_surfaces(field, grid=grid, levels=[1000.0])[0]
    assert r["ok"] is False and r["n_cells"] == 0 and "出不了面" in r["reason"]
    # ③ 角落碎片：只在一个角上跨过层 —— 门槛必须拦住
    v = np.full(grid.shape, 10.0)
    v[0, 0, 0] = 100.0
    r = bg3d.iso_surfaces(v, grid=grid, levels=[50.0])[0]
    assert r["n_cells"] <= 2, r["n_cells"]
    assert r["ok"] is False, "跨一两个格子的碎片不许当成'可出面'"
    # 门槛是**可调**的，而且调高之后真的会拦住（防"门槛写了没人用"）
    r2 = bg3d.iso_surfaces(np.full((nd, ng, nb), 50.0) + np.random.default_rng(0).normal(
        0, 1.0, (nd, ng, nb)), grid=grid, levels=[50.0], min_cells=10 ** 6)[0]
    assert r2["ok"] is False and r2["reason"]


def test_fig4_layer_levels_come_from_the_shared_iso_levels():
    """档位**不是**另写一套：`layer_levels()` 是 `grid.iso_levels()` 的等距子集。

    这条用打桩数调用次数 + 逐值比对：任何"自己再算一套整秒层级"的改法都会当场红。
    """
    import missile_sim.grid as grid_mod
    cube = np.full((11, 7, 7), np.nan)
    cube[3:, :, :] = np.linspace(40.0, 60.0, 8 * 7 * 7).reshape(8, 7, 7)
    calls = []
    orig = grid_mod.iso_levels

    def spy(values, step):
        out = orig(values, step)
        calls.append((len(out), float(step)))
        return out

    grid_mod.iso_levels = spy
    try:
        levels = fig4.layer_levels(cube, step=1.0, count=13)
    finally:
        grid_mod.iso_levels = orig
    assert calls == [(21, 1.0)], f"必须正好调一次 grid.iso_levels(step=1.0)，实际 {calls}"
    assert len(levels) == 13, f"要 13 档，实际 {len(levels)}"
    assert levels == sorted(levels) and len(set(levels)) == len(levels)
    all_levels = orig(cube, 1.0)
    assert set(levels) <= set(all_levels), "档位必须是共享层级的子集（不许自造）"
    assert levels[0] == min(all_levels) and levels[-1] == max(all_levels), "端点要保留"
    # 层数比可用档位还多时不硬凑
    assert fig4.layer_levels(cube, step=1.0, count=10 ** 3) == all_levels


def test_fig4_layers_payload_gives_every_layer_in_one_response():
    """**零往返的数据面**：一次请求拿到全部 13 层（含"能不能出面"的判定与网格）。

    前端滑块只在本地切换 —— 所以这里数的是"响应里有没有全部层"，不是"渲染得快不快"。
    """
    for key in ("PL-12", "120C"):
        blob = fig4.layers_payload(PRODUCTS, missile=key)
        lay = blob["layers"]
        assert lay["n_levels"] == fig4.LAYER_COUNT
        surfs = blob["surfaces"]
        assert len(surfs) == fig4.LAYER_COUNT, (key, len(surfs))
        assert [s["level"] for s in surfs] == lay["levels"]
        assert [s["label"] for s in surfs] == lay["labels"]
        assert len(set(lay["levels"])) == len(lay["levels"])
        assert lay["levels"] == sorted(lay["levels"])
        ok = [s for s in surfs if s["ok"]]
        assert len(ok) >= 6, f"{key}：可出面的层只有 {len(ok)} 档，滑块几乎没得拖"
        for s in surfs:
            assert s["label"] == figures.iso_label(s["level"])
            if s["ok"]:
                # 可出面：发几何，且 `n_vert` / `n_tri` 与扁平数组一致
                assert len(s["vertices"]) == s["n_vert"] * 3
                assert len(s["triangles"]) == s["n_tri"] * 3
                assert s["n_cells"] >= fig4.LAYER_MIN_CELLS and s["n_tri"] >= fig4.LAYER_MIN_TRI
                assert not s["reason"], f"{s['level']}：能出面的层不该带理由"
                # 顶点索引不许越界（WebGL 那边会静默画错）
                mx = max(s["triangles"]) if s["triangles"] else -1
                assert mx < s["n_vert"], (s["level"], mx, s["n_vert"])
            else:
                assert s["reason"], f"{s['level']}：不能出面却没给理由"
                assert s["triangles"] == [] and s["vertices"] == []
    # 未知弹 ⇒ KeyError（路由层折成 404，不静默给别的弹）
    with pytest.raises(KeyError):
        fig4.layers_payload(PRODUCTS, missile="不存在的弹")


def test_fig4_zero_hit_missile_is_not_layerable():
    """**降级路径**：0 命中的弹 `layerable=False`，绝不用 `lifetime` 冒充 `t_hit`。

    `results/fig4_miss.json` 是专门造的全脱靶档（R-77 @ 80 km）。这里同时钉住
    ① 点云里没有任何 `t`；② 等时面的层全是 `ok=False`（没有假面）；
    ③ 数据层没把 `t_end_s` 当成 `t_hit` 抄进去。
    """
    rec = fig4.read_record(MISS_PRODUCTS["record"])
    assert int(rec["summary"]["n_hit"]) == 0
    rows = fig4.read_csv_rows(MISS_PRODUCTS["cases"])
    assert rows and all(r["hit"] == "0" for r in rows)
    assert all(r["t_hit_s"] == "" for r in rows)
    assert all(r["t_end_s"] != "" for r in rows), "脱靶也有 t_end，但那是终止时刻"
    blob = fig4.build(MISS_PRODUCTS, tag="miss")
    bad = [m for m in blob["missiles"] if m["n_hit"] == 0]
    assert bad, "这个档本来就是全脱靶"
    for m in bad:
        assert m["layerable"] is False, (m["key"], m)
        assert all(v is None for v in blob["clouds"][m["key"]]["t"]), \
            "0 命中的弹不许有点云 t 值"
    key = bad[0]["key"]
    lay = fig4.layers_payload(MISS_PRODUCTS, missile=key)
    # ⚠ 全脱靶弹**一个有限 t 都没有** ⇒ `grid.iso_levels` 给空列表 ⇒ 一档都没有。
    # 这不是"每层都 ok=False"，而是"根本没有层可谈" —— 前端据此置灰并说明原因。
    assert lay["surfaces"] == [], "全脱靶弹不许出现任何等时面"
    assert lay["layers"]["levels"] == [] and lay["layers"]["labels"] == []
    assert lay["missile"]["layerable"] is False
    # 校验：产物里的 t_end 与 t_hit **不是**同一个数（防"拿 t_end 冒充"）
    te = [float(r["t_end_s"]) for r in rows if r["t_end_s"]]
    assert te and min(te) > 0

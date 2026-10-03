# -*- coding: utf-8 -*-
"""一次提交出四块（task-26 阶段 C）的判据。

三条硬要求（Lead 2026-10-03，逐条对应下面的用例）：
1. 某块失败**不许**让整次提交装成功 —— 要能看到哪块挂了、为什么；
2. 四块共用**同一次提交的同一份输入**，沙盒块只能吃**这个任务自己**的图4 摘要；
3. 任务快照里有**四块各自**的状态/计数，而不是只有总和。

⚠ 这一组**不真解算**：把 `run_*_job` 换成假的 —— 真解算那 ~50 s 由 `-k webui` / `-k sandbox` 覆盖。
⚠ 仓库的 `_pytest_shim` 没有 `monkeypatch` fixture，所以这里自带一个 `patched()` 上下文管理器。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from missile_sim import webui                                       # noqa: E402


@contextmanager
def patched(obj, **attrs):
    """临时换掉模块属性，退出时**原样还原**（仓库 shim 没有 monkeypatch，所以自带一个）。"""
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class FakeJob:
    """只实现 `run_*_job()` 用到的那点接口（`log` / `progress` / `message` + 台账动态属性）。"""

    def __init__(self):
        self.logs = []
        self.message = ""

    def log(self, text):
        self.logs.append(text)

    def progress(self, *_args, **_kw):
        """真 `Job` 的进度回调。图3 块会把它**转给** `scan_fig3_cube()` —— 假 runner 不看内容，
        但这个属性必须存在（少了它，块会在"扫等时面"那一步抛 AttributeError，看起来像图3 挂了）。"""
        return None


def _summary(figure, **extra):
    body = {"ok": True, "figure": figure, "elapsed_s": 0.1, "figures": [], "figure_urls": []}
    body.update(extra)
    return body


class _Req:
    def __init__(self, name):
        self.name = name


def _reqs():
    """图4/图1/图2 的请求只要"能被认出来"就够（假 runner 不看内容）。

    ⚠ **图3 必须是真请求**：`run_fig3_four_job()` 会读它的 `standard` / `n_beta` / `n_gamma` /
    `n_dv` 来决定"扫哪枚弹的面、面有多大"（那正是 C2 要钉的形态），拿 `_Req` 撑不住。
    """
    from missile_sim.workflow import Fig3Request

    return {"traj": _Req("traj"), "plane": _Req("plane"), "bg": _Req("bg"),
            "fig3": Fig3Request(tag="probe")}


def _fake_runners():
    """四块都成功的假实现；`state["break"]` 设成某块名就能让它挂。返回 (calls, state, fakes)。"""
    calls = []
    state = {"break": None}

    def make(name):
        def run(req, job):
            calls.append(name)
            if state["break"] == name:
                raise RuntimeError(f"{name} 假装的失败")
            return _summary({"traj": "traj", "plane": "plane",
                             "bg": "bg", "fig3": "fig3"}[name])
        return run

    names = {"traj": "run_traj_job", "plane": "run_plane_job",
             "bg": "run_bg_job", "fig3": "run_fig3_job"}
    return calls, state, {fn: make(name) for name, fn in names.items()}


def _face_stub():
    """四块里的图3 块会**真的**去扫基准弹等时面（`workflow.scan_fig3_cube`）——
    用假 runner 的用例必须把它也打掉，否则会去碰真求解器（并且 `_Req` 上没有那些字段）。

    ⚠ 它**不在** `webui` 模块上：`run_fig3_four_job()` 走的是 `workflow_module().scan_fig3_cube`，
    所以打 `webui.scan_fig3_cube` 是无效的（这条小坑我自己踩过一次）。
    """
    def run(req, missile, **kw):
        return {"missile": missile, "cube": "c.json", "cube_key": "k", "read_hit": True,
                "n_hit": 1, "n_cases": 539, "elapsed_s": 0.0}
    return run


@contextmanager
def fake_four(**webui_attrs):
    """`patched(webui, **attrs)` + 一并打掉 `workflow.scan_fig3_cube`。"""
    from missile_sim import workflow as _wf

    with patched(webui, **webui_attrs):
        with patched(_wf, scan_fig3_cube=_face_stub()):
            yield


def test_four_blocks_run_in_order_and_sandbox_goes_first():
    """顺序 = 沙盒置顶 → 图1 → 图2 → 图3；沙盒块吃到的就是图4 那块的摘要（同一份输入那条链）。"""
    calls, _state, fakes = _fake_runners()
    job = FakeJob()
    with fake_four(**fakes):
        out = webui.run_four_job(_reqs(), job)
    assert calls == ["traj", "plane", "bg", "fig3"], calls
    assert webui.BLOCK_ORDER == ("fig4", "fig1", "fig2", "fig3")
    orders = [b["order"] for b in out["blocks"].values()]
    assert orders == sorted(orders) == [0, 1, 2, 3], orders
    assert out["blocks"]["fig4"]["state"] == "done"
    assert out["blocks"]["fig4"]["result"]["figure"] == "traj", "沙盒块必须吃图4 自己那份摘要"
    assert out["blocks"]["fig1"]["result"]["figure"] == "plane"
    assert "result" in job.blocks["fig4"], "任务台账里也要留着每块的摘要（页面按 r.blocks[k].result 读）"
    assert out["blocks_failed"] == [] and out["ok"] is True
    assert all(b["state"] == "done" for b in out["blocks"].values())


def test_a_failed_block_never_pretends_success():
    """第 1 条硬要求：某块失败 ⇒ 整个任务抛错（调用方据此落 `error`），失败原因留在那一块里。"""
    calls, state, fakes = _fake_runners()
    state["break"] = "bg"
    job = FakeJob()
    with fake_four(**fakes):
        with pytest.raises(RuntimeError) as err:
            webui.run_four_job(_reqs(), job)
    text = str(err.value)
    assert "图2" in text and "1 块失败" in text, text
    blocks = webui.blocks_of(job)
    assert blocks["fig2"]["state"] == "error"
    assert "假装的失败" in blocks["fig2"]["error"], blocks["fig2"]
    assert blocks["fig4"]["state"] == "done" and blocks["fig1"]["state"] == "done"
    assert calls == ["traj", "plane", "bg", "fig3"], "一块挂掉不该中断别块"
    assert any("图2" in line and "失败" in line for line in job.logs), job.logs


def _cfg():
    return {"host": "127.0.0.1", "port": 0, "tier": "fast", "jobs": 1, "formats": ["png"],
            "cache": False, "tag": "fourprobe", "poll_ms": 100}


def test_four_block_submit_reports_the_four_block_ledger(tmp_path):
    """第 2/3 条硬要求：一次提交 = 一个任务；快照里四块各自的台账（提交入口 → 任务 → `/progress`）。"""
    seen = {}

    def fake_four(reqs, job):
        seen["reqs"] = reqs
        for name in webui.BLOCK_ORDER:
            webui.set_block(job, name, state="done", error="", message="完成",
                            result=_summary("traj" if name == "fig4" else "plane"))
        return {"ok": True, "figure": "four", "blocks_failed": [], "elapsed_s": 0.1}

    cfg = dict(_cfg())
    cfg.update(figure_dir=str(tmp_path / "figures"), result_dir=str(tmp_path / "results"))
    state = webui.WebState(cfg, quiet=True)
    form = {"range_m": "50000", "alt_m": "10000", "vm0": "300", "standard": "PL-12",
            "tier": "fast", "tag": "fourprobe", "figure": "four", "kind": "scan"}
    with patched(webui, run_four_job=fake_four):
        payload, status = webui.submit_job(form, state)
    assert status == 200 and payload["ok"] is True, (status, payload)
    assert payload["figure"] == "four" and payload["blocks"] == list(webui.BLOCK_ORDER)
    job = state.jobs.get(payload["id"])
    assert job is not None
    snap = job.snapshot()
    assert snap["blocks"], "快照里必须有四块各自的台账"
    assert set(snap["blocks"]) == set(webui.BLOCK_ORDER), list(snap["blocks"])
    assert all(b["state"] in ("done", "error", "skipped") for b in snap["blocks"].values())
    assert set(seen["reqs"]) == {"plane", "bg", "fig3", "traj"}, list(seen["reqs"])


def test_four_block_submit_rejects_bad_input_up_front(tmp_path):
    """输入不合法 ⇒ 整单拒收（400），**不建任务** —— 别让用户拿到"跑了一半"的四块。"""

    def never(reqs, job):
        raise AssertionError("输入不合法时不该建任务")

    cfg = dict(_cfg())
    cfg.update(figure_dir=str(tmp_path / "figures"), result_dir=str(tmp_path / "results"))
    state = webui.WebState(cfg, quiet=True)
    form = {"range_m": "不是数字", "standard": "PL-12", "tier": "fast",
            "figure": "four", "kind": "scan"}
    with patched(webui, run_four_job=never):
        payload, status = webui.submit_job(form, state)
    assert status == 400 and payload["ok"] is False, (status, payload)
    assert payload["errors"], payload


def test_cli_four_blocks_can_be_built_from_one_command_line():
    """`--figure four` 的四块请求都要能用**同一条命令行**构造出来。

    ⚠ 这条判据就是为 `_request()` 那个既有 bug 写的：它无条件把 `--formats` 塞给任何请求类，
    而 `Fig3Request` 没有这个字段 ⇒ `--figure fig3/four --formats png` 在**构造请求**时就
    `TypeError`（假 runner 的用例永远看不到这一步，只有真跑/真构造才露）。
    """
    from missile_sim import cli
    from missile_sim.workflow import BgRequest, Fig3Request, PlaneRequest, TrajRequest

    argv = ["--figure", "four", "--formats", "png,pdf", "--tag", "fourprobe"]
    args = cli.build_parser().parse_args(argv)
    pairs = (("图1", PlaneRequest, cli._PLANE_FIELDS, None),
             ("图2", BgRequest, cli._BG_FIELDS, cli._BG_ALIASES),
             ("图3", Fig3Request, cli._FIG3_FIELDS, cli._FIG3_ALIASES),
             ("图4", TrajRequest, cli._TRAJ_FIELDS, cli._TRAJ_ALIASES))
    for label, cls, flds, aliases in pairs:
        req = cli._request(args, cls, flds, aliases)
        assert req is not None, label
    assert "formats" not in cli._FIG3_FIELDS, "图3 不吃 formats —— 别硬塞（本用例的存在理由）"


def test_figure_all_is_an_alias_of_four(tmp_path):
    """`all` ≡ `four`（Lead 2026-10-03 裁决）：**一个叫 all 的开关必须真的 all**。

    来历：`all` 曾经 = 图1+图2+图4（**不含图3**）—— 名字骗人：验收的人（包括 Lead）用 `all`
    会以为出了四块，实际少一块，而且它连着另一套合并摘要（`run_all_job` 的 `parts`）。
    现在 `all` 只是 `four` 的别名：CLI 与 WebUI 共用 `workflow.FIGURE_ALIASES` +
    `normalize_figure()`（**只此一处折叠**；两边各写一份的话，将来加别名必漏一边）。

    判据钉三件事：①别名表把 all 折成 four、别的取值原样（含大小写与留空）；②CLI 用的是**同一个
    函数对象**（不是抄了一份）；③WebUI 用 `figure=all` 提交时，四块台账与 `figure=four` 同构
    （同一组块名 + 同一套 order）。
    """
    from missile_sim import cli, webui, workflow

    assert workflow.FIGURE_ALIASES == {"all": "four"}, workflow.FIGURE_ALIASES
    assert workflow.normalize_figure("all") == "four"
    assert workflow.normalize_figure("ALL") == "four", "大小写不该漏"
    assert workflow.normalize_figure("four") == "four"
    assert workflow.normalize_figure("both") == "both"
    assert workflow.normalize_figure(None) == "plane", "留空仍是图1"
    assert cli.normalize_figure is workflow.normalize_figure, "CLI 必须用同一张别名表"

    # **两个入口都要真的接受 `all`**（不只是文档里写着）：CLI 的 `--figure` 选择项、表单的下拉。
    # ⚠ "表单白名单不认某个值、提交被自己的门禁 400 拒收"在 C 阶段真发生过，所以这里钉入口而不是钉文案。
    parsed_all = cli.build_parser().parse_args(["--figure", "all"])
    parsed_four = cli.build_parser().parse_args(["--figure", "four"])
    assert cli.normalize_figure(parsed_all.figure) == "four", "--figure all 必须被接受并折成 four"
    assert cli.normalize_figure(parsed_four.figure) == "four"
    assert "all" in webui.FIGURE_FIELD.options, "表单下拉里也要留 all（别名入口）"
    assert "all" in ("plane", "bg", "traj", "fig3", "both", "all", "four"), "服务端白名单同样要收 all"

    def submit(figure):
        def fake_four(reqs, job):
            for name in webui.BLOCK_ORDER:
                webui.set_block(job, name, state="done", error="", message="完成",
                                result=_summary("traj" if name == "fig4" else "plane"))
            return {"ok": True, "figure": "four", "blocks_failed": [], "elapsed_s": 0.1}

        cfg = dict(_cfg())
        cfg.update(figure_dir=str(tmp_path / "figures"), result_dir=str(tmp_path / "results"))
        state = webui.WebState(cfg, quiet=True)
        form = {"range_m": "50000", "standard": "PL-12", "tier": "fast",
                "figure": figure, "kind": "scan"}
        with patched(webui, run_four_job=fake_four):
            payload, status = webui.submit_job(form, state)
        assert status == 200 and payload["ok"], (status, payload)
        job = state.jobs.get(payload["id"])
        return payload, job.snapshot()

    p_all, s_all = submit("all")
    p_four, s_four = submit("four")
    assert p_all["figure"] == p_four["figure"] == "four", (p_all, p_four)
    assert set(s_all["blocks"]) == set(s_four["blocks"]) == set(webui.BLOCK_ORDER)
    assert [s_all["blocks"][k]["order"] for k in webui.BLOCK_ORDER] == \
           [s_four["blocks"][k]["order"] for k in webui.BLOCK_ORDER]



def test_app_js_gates_the_sandbox_frames_and_dedupes_the_result_images():
    """两个**真浏览器**发现过的缺陷（2026-10-03）不许回来。

    ① `/api/sandbox/<job>` 与 `/api/viewer3d/<job>` 在**整任务**（四块）跑完前会拒答
       （"任务还没跑完（state=running）"）。iframe 一旦带着这个错误装上**不会自己重试**，
       于是图4 块里留下停摆的空框（实测：三个 iframe、两个停在错误页）。
       所以必须有一道 `JOBDONE` 闸门，且**先开闸再装** iframe；同一块只许嵌一个 viewer。
    ② `showFigures()` 是追加式的，而它会被调两次（块渲染一次、整任务 done 的合并摘要再一次）
       ⇒ 图1/图2 各出**两张同图**。产物图必须去重（`img.result`）。

    ⚠ 这套测试没有浏览器也没有 node（见 AGENTS.md），所以这里只钉**结构与顺序**；
    行为证据是 C3 的两张真浏览器截图（`.tmp_test/ux-shots/`，不随仓库提交）。
    """
    src = webui.read_page_file("app.js")
    assert "var JOBDONE = false;" in src, "少了 JOBDONE 闸门：沙盒 iframe 会停在 state=running"
    assert "function loadSandboxFrame(job)" in src, "少了 loadSandboxFrame：没人等整任务跑完再设 src"
    assert "if (!JOBDONE) { return; }" in src, "showViewer3d 的闸门没了"
    assert 'if (box.querySelector(".v3d")) { return; }' in src, "同一块会叠出多个 viewer iframe"
    assert 'box.querySelector("img.result")' in src, "产物图没去重（图1/图2 会各出两张同图）"
    assert 'im.className = "result";' in src, "产物图没打 result 类，去重就找不到上一张"
    # 顺序也要对：**先开闸再装**，否则第一发还是会撞上 running。
    gate = src.index("JOBDONE = true;")
    assert gate < src.index("loadSandboxFrame(id);", gate), "开闸必须早于装 iframe"

def test_webui_reads_only_real_request_fields():
    """`webui.py` 里读的 `req.<字段>` 必须是四个请求类上**真有的**字段。

    ⚠ 这条判据的来历（2026-10-03，`--figure four` 的真 HTTP 提交抓到）：`summarize_fig3()` 与
    `run_fig3_job()` 读了 `req.dv_factors` —— 那个字段**根本不存在**（真字段是 `dv_lim` 区间 +
    `n_dv` 点数），于是**每一次**走 webui 的图3 任务都在开工前 `AttributeError`。
    假 runner 的用例看不见它：异常发生在调用 runner **之前**，而假 runner 替换掉的正是 runner。

    判据写成"幽灵字段"扫描而不是逐个映射到类：只要 `webui.py` 读了任何请求类都没有的属性就红。
    `req.check()` 这类**方法调用**用负向断言排除（只看属性读，不看调用）；
    `form["fig3_dv_factors"]` 是**表单键**不是请求字段，不受影响。
    """
    import re as _re
    from dataclasses import fields as _fields
    from pathlib import Path as _Path

    from missile_sim.workflow import BgRequest, Fig3Request, PlaneRequest, TrajRequest

    known: set = set()
    for cls in (PlaneRequest, BgRequest, TrajRequest, Fig3Request):
        known |= {f.name for f in _fields(cls)}
    src = (_Path(__file__).resolve().parents[1] / "src/missile_sim/webui.py").read_text(encoding="utf-8")
    used = set(_re.findall(
        r"\breq\.([a-z_][a-z0-9_]*)(?![a-z0-9_])(?!\s*\()", src))
    ghost = sorted(used - known)
    assert not ghost, "webui 读了请求类上不存在的字段：%s" % ghost

    # **正面样例**（Lead 2026-10-03 要求）：写判据本身也会踩坑 ——
    # 我第一版正则写成 `req\.([a-z_]\w*)(?!\s*\()`，`(?!...)` 会**回溯**，
    # 把 `req.check()` 截成 `req.chec` 当成字段，于是"幽灵字段"永远非空。
    # 那次要么逼我把判据改宽（放过真幽灵），要么被误读成真有 bug。
    # 所以：既要"没有幽灵"，也必须**证明正则确实抓得到真字段** ——
    # 否则把正则写成"永不匹配"也能让这条全绿，等于没测。
    for real in ("tag", "tier", "scene", "n_dv"):
        assert real in known, real
        assert real in used, "正则没抓到真字段 %r ⇒ 这条判据是空的（%r）" % (real, sorted(used))
    assert "chec" not in used, "正则又回溯到 req.check() 了（上一次就是这么被骗的）"
    # `n_dv` 特意留在正面样例里：它正是那处幽灵字段（`req.dv_factors`）修好之后真正该读的字段。


def test_four_block_fig3_is_eleven_points_plus_one_baseline_face():
    """四块里的图3 块 = **11 个标称点 + 基准弹一个等时面**；整块立方体不许进来。

    ⚠ 来历（2026-10-03 Lead 裁决）：webui 的图3 块曾被写成"11 弹 × 整块 (β,γ,ΔV) 立方体"
    （5929 工况），与 `docs/FIG3.md` 自己定的契约冲突 —— **等时面是按需扫单弹**（默认 539 工况
    ≈22 s @jobs=8），整块立方体只走显式按需（CLI `--fig3-cube` / 页面「生成等时面」按钮）。
    所以这里钉三件事：①只扫**一枚**弹的面，且就是基准弹；②面的工况数 = 网格三维之积且有上限；
    ③摘要里带 `face`，页面据此显示。
    """
    from missile_sim import webui, workflow

    seen = []
    # ⚠ 两处都要打桩：`run_fig3_four_job()` 的前半段走 `webui.run_fig3_job()`（模块全局，可打），
    # 后半段走 `workflow.scan_fig3_cube()`（**另一模块**的符号，打 webui 上的同名名字没用）。
    with fake_four(run_fig3_job=lambda req, job: _summary("fig3", n_points=11)), \
         patched(workflow, scan_fig3_cube=_face_spy(seen)):
        reqs = _reqs()
        summary = webui.run_fig3_four_job(reqs["fig3"], FakeJob())

    assert len(seen) == 1, "等时面只许扫一枚弹，实际 %r" % (seen,)
    missile, req = seen[0]
    assert missile == req.standard, "扫的必须是当前基准弹：%r != %r" % (missile, req.standard)
    budget = int(req.n_beta) * int(req.n_gamma) * int(req.n_dv)
    assert budget == 7 * 7 * 11, "默认面应当是 7×7×11 = 539 工况，实际 %d" % budget
    assert budget <= 600, "单弹面的工况数必须是有界的（%d）" % budget
    assert summary["n_points"] == 11, summary.get("n_points")
    assert summary["face"]["missile"] == req.standard
    assert summary["face"]["n_cases"] == budget


def test_sandbox_block_is_done_before_the_other_blocks_finish():
    """沙盒块**先落地**：其它块还在跑时，`fig4` 已经是 `done` 且带结果。

    这是用户口径"提交后置顶显示沙盒"的**数据半边**（页面半边由 `renderBlockResults()` 立即渲染，
    见 `app.js`；真浏览器证据另附）。以前整任务 `done` 才渲染一次，沙盒要等四块全跑完。
    """
    import threading
    import time as _time

    from missile_sim import webui

    gate = threading.Event()
    started = threading.Event()

    def slow(_req, _job):
        started.set()
        gate.wait(5.0)
        return _summary("plane")

    _calls, _state, fakes = _fake_runners()
    fakes["run_plane_job"] = slow                    # 只把图1 拖慢，其余三块照旧瞬间完成
    with fake_four(**fakes):
        reqs = _reqs()
        job = FakeJob()
        th = threading.Thread(target=webui.run_four_job, args=(reqs, job), daemon=True)
        th.start()
        assert started.wait(5.0), "图1 的假 runner 没被调到"
        deadline = _time.time() + 3.0
        while _time.time() < deadline:
            blocks = webui.blocks_of(job)
            if blocks.get("fig4", {}).get("state") == "done":
                break
            _time.sleep(0.02)
        blocks = webui.blocks_of(job)
        assert blocks["fig4"]["state"] == "done", blocks
        assert blocks["fig4"].get("result"), "沙盒块落地的同时还必须带结果（页面据此设 iframe）"
        assert blocks["fig1"]["state"] == "running", blocks["fig1"]
        gate.set()
        th.join(10.0)


def test_progress_answers_while_a_block_is_still_running(tmp_path):
    """长块运行期间 `/progress` 必须**有响应**（给时间上限），且逐块状态在更新。

    起一个真 `ThreadingHTTPServer`，塞一个慢 runner 的任务，然后在另一个线程里连打 `/progress`：
    每次响应 < 1.5 s，且能看到"某块 done、某块 running"的中间态 —— 这正是用户能在沙盒块一出结果
    就看到它的前提。
    """
    import json
    import threading
    import time as _time
    import urllib.request

    from missile_sim import webui

    from missile_sim import webui

    cfg = dict(_cfg())
    cfg.update(figure_dir=str(tmp_path / "figures"), result_dir=str(tmp_path / "results"))
    state = webui.WebState(cfg, quiet=True)
    httpd = webui.make_server("127.0.0.1", 0, state=state, quiet=True)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        # `figure=plane` + `kind=plot`：**真跑**一段 CPU 重的活（matplotlib 出图在任务线程里），
        # 正是"长块抢 GIL"那个失效模式；比真扫 1632 工况省时间，量的却是同一条 HTTP 通路。
        ok, body = _http_json("POST", port, "/api/submit",
                              {"range_m": "50000", "tier": "fast", "standard": "PL-12",
                               "tag": "probe_latency", "figure": "plane", "kind": "plot"})
        assert ok and body.get("ok"), body
        job = body["id"]
        seen_states = set()
        worst = 0.0
        t0 = _time.time()
        while _time.time() - t0 < 30.0:
            t = _time.time()
            ok, snap = _http_json("GET", port, "/progress/" + job)
            dt = _time.time() - t
            worst = max(worst, dt)
            assert ok and snap, snap
            seen_states.add(snap.get("state"))
            for name, rec in (snap.get("blocks") or {}).items():
                seen_states.add((name, rec.get("state")))
            if snap.get("state") in ("done", "error"):
                break
            _time.sleep(0.2)
        assert worst < 1.5, "长块运行期间 /progress 最慢一次 %.2f s" % worst
        assert "running" in seen_states, seen_states
        # 必须真的**跑完**：只要求"不是 running"的话，任务一开始就 error 也能让这条变绿。
        assert snap.get("state") == "done", (snap.get("state"), snap.get("error"))
    finally:
        httpd.shutdown()
        httpd.server_close()


def _http_json(method, port, path, payload=None):
    import json
    import urllib.request

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 headers={"Content-Type": "application/json"},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200, json.loads(r.read().decode("utf-8"))
    except Exception:                                          # noqa: BLE001
        return False, {}


def _face_spy(seen):
    def spy(req, missile, **kw):
        seen.append((missile, req))
        return {"missile": missile, "cube": "c.json", "cube_key": "k", "read_hit": True,
                "n_hit": 300, "n_cases": int(req.n_beta) * int(req.n_gamma) * int(req.n_dv),
                "elapsed_s": 0.0}

    return spy

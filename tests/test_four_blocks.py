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
    """只实现 `run_four_job()` 用到的那点接口（`log` + 台账动态属性）。"""

    def __init__(self):
        self.logs = []

    def log(self, text):
        self.logs.append(text)


def _summary(figure, **extra):
    body = {"ok": True, "figure": figure, "elapsed_s": 0.1, "figures": [], "figure_urls": []}
    body.update(extra)
    return body


class _Req:
    def __init__(self, name):
        self.name = name


def _reqs():
    """四个请求对象只要"能在 reqs 里被认出来"就够 —— 假 runner 不看内容。"""
    return {"traj": _Req("traj"), "plane": _Req("plane"), "bg": _Req("bg"), "fig3": _Req("fig3")}


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


def test_four_blocks_run_in_order_and_sandbox_goes_first():
    """顺序 = 沙盒置顶 → 图1 → 图2 → 图3；沙盒块吃到的就是图4 那块的摘要（同一份输入那条链）。"""
    calls, _state, fakes = _fake_runners()
    job = FakeJob()
    with patched(webui, **fakes):
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
    with patched(webui, **fakes):
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


def test_four_block_submit_reports_the_four_block_ledger():
    """第 2/3 条硬要求：一次提交 = 一个任务；快照里四块各自的台账（提交入口 → 任务 → `/progress`）。"""
    seen = {}

    def fake_four(reqs, job):
        seen["reqs"] = reqs
        for name in webui.BLOCK_ORDER:
            webui.set_block(job, name, state="done", error="", message="完成",
                            result=_summary("traj" if name == "fig4" else "plane"))
        return {"ok": True, "figure": "four", "blocks_failed": [], "elapsed_s": 0.1}

    state = webui.WebState(_cfg(), quiet=True)
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


def test_four_block_submit_rejects_bad_input_up_front():
    """输入不合法 ⇒ 整单拒收（400），**不建任务** —— 别让用户拿到"跑了一半"的四块。"""

    def never(reqs, job):
        raise AssertionError("输入不合法时不该建任务")

    state = webui.WebState(_cfg(), quiet=True)
    form = {"range_m": "不是数字", "standard": "PL-12", "tier": "fast",
            "figure": "four", "kind": "scan"}
    with patched(webui, run_four_job=never):
        payload, status = webui.submit_job(form, state)
    assert status == 400 and payload["ok"] is False, (status, payload)
    assert payload["errors"], payload

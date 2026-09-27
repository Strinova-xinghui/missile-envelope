"""工作流测试：后端声明、标准弹可切换、覆盖顺序、逐弹切标准弹、产物自描述。

用极小网格（数条工况）跑真实 `run_workflow`，秒级；产物写到 `*_pytest` 后缀并在用后清理。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

import workflow  # noqa: E402
from missile_sim.config import ConfigError, load_config, validate  # noqa: E402
from missile_sim.provenance import provenance, summary_line  # noqa: E402

TAG = "pytest"
# **测试显式走 standard**：本文件测的是"工作流装配/自描述/覆盖顺序"，与档位算法无关；
# standard 是纯 Python 逐物理步，缺 C 编译器也能跑，且不需要信源原生包
# （仓库单独克隆仍能全绿 —— 求解器本身已整包入库 vendor/wt-missile/）。
SMALL = {                       # 2×2 = 4 工况：够验证全流程，又不拖慢测试
    "backend": {"name": "standard"},
    "pro": {"pro_jobs": 1},     # 极小网格不值得建进程池（子进程每次都要重载求解器）
    "sweep": {"dv_min": 900.0, "dv_max": 1000.0, "dv_step": 100.0,
              "bc_min": 3000.0, "bc_max": 3100.0, "bc_step": 100.0},
    "compare": {"tag": TAG, "iso_step": 2.0},
}


@pytest.fixture(scope="module")
def run_small():
    """跑一次小工作流，结束后清掉它产生的产物。"""
    summary = workflow.run_workflow(SMALL, verbose=False)
    yield summary
    for p in (ROOT / "figures").glob(f"workflow_{TAG}*"):
        p.unlink(missing_ok=True)
    for p in (ROOT / "results").glob(f"workflow_{TAG}*"):
        p.unlink(missing_ok=True)


# --------------------------------------------------------------------- 后端

def test_default_backend_is_standard():
    """用户 2026-09-26 定案：**wt-missile 两档**，默认 `standard`（纯 Python 逐物理步）。"""
    m = load_config()
    assert m.backend == "standard"
    assert provenance(m)["backend"] == "standard"
    blk = provenance(m)["pro"]              # `pro_*` 是命名遗留：现在是两档共用的运行参数
    assert blk["observation_mode"] == "ideal"
    assert blk["dt"] > 0


def test_legacy_tier_names_are_no_longer_cli_tiers():
    """旧名 `pro` / `flash` **不再是档位**：`--backend` 只认 standard/fast。

    它们没有消失 —— 注册表里仍是 `source="legacy"`（`spec_of("pro")` 查得到），
    `run_sweep_pro` / `ScanSpec(model="pro")` 也仍能跑；只是不再占着 CLI 的档位选项，
    否则"两档同步更名"就没落地。真跑一次 Pro 需要信源原生包，所以这里只验入口。
    """
    import missile_sim.cli as cli
    from missile_sim.model import registry as reg

    for legacy in ("pro", "flash"):
        with pytest.raises(SystemExit):
            cli.main(["--backend", legacy, "--list-standards"])
    rc = cli.main(["--backend", "fast", "--list-standards"])
    assert rc == 0, "--backend fast 必须可选"

    assert reg.spec_of("pro").source == "legacy"
    assert reg.spec_of("flash").source == "legacy"
    assert "pro" not in {s.name for s in reg.list_models()}


def test_fast_tier_is_selectable_from_config():
    """`fast`（同一物理的 C 编译内核）必须能从输入里选；缺编译器时它自己回退，不是配置错误。"""
    m = load_config()
    m.backend = "fast"
    validate(m)
    prov = provenance(m)
    assert prov["backend"] == "fast"
    # `pro` 块是**命名遗留**：现在是两档共用的运行参数，所以任何档位下都要在
    assert prov["pro"]["dt"] > 0
    assert prov["pro"]["observation_mode"] == "ideal"


def test_unknown_backend_rejected_in_config(tmp_path):
    m = load_config()
    m.backend = "warp"
    with pytest.raises(ConfigError):
        validate(m)


def test_backend_field_roundtrips_through_config_dict():
    from missile_sim.config import config_to_dict

    d = config_to_dict(load_config())
    assert d["backend"] == "standard"
    for key in ("pro_jobs", "pro_dt", "pro_duration_s", "pro_observation", "pro_cache"):
        assert key in d, f"{key} 必须写进产物自描述"


# --------------------------------------------------------------------- standard 档端到端

def test_standard_backend_workflow_runs(tmp_path):
    """`standard` 档的最小端到端：2×2 网格 + 逐弹（走缓存）——验证 workflow 真的能驱动新求解器。

    显式 `pro_jobs=1`：避免测试里反复建进程池（子进程每次都要重新载入求解器）。
    """
    cfg = dict(SMALL)
    cfg["backend"] = {"name": "standard"}
    cfg["pro"] = {"pro_jobs": 1}
    cfg["compare"] = {"tag": TAG + "std", "iso_step": 2.0}
    # ≥2×2：等值线提取/绘图需要至少 (2,2) 的网格
    cfg["sweep"] = {"dv_min": 900.0, "dv_max": 1000.0, "dv_step": 100.0,
                    "bc_min": 3000.0, "bc_max": 3100.0, "bc_step": 100.0}
    try:
        s = workflow.run_workflow(cfg, verbose=False)
        prov = s["provenance"]
        assert prov["backend"] == "standard", prov.get("backend")
        assert s["results"]["n_hit"] == 4, s["results"]
        tb = s["derived"]["t_hit_baseline_s"]
        assert tb is not None and 40.0 < tb < 50.0, f"baseline t_hit = {tb}"
        bad = [(m["label"], m["backend"], m["standard_error"]) for m in s["missiles"]
               if m["backend"] != "standard"]
        assert not bad, f"逐弹没走 standard：{bad}"
    finally:
        for p in (ROOT / "figures").glob(f"workflow_{TAG}std*"):
            p.unlink(missing_ok=True)
        for p in (ROOT / "results").glob(f"workflow_{TAG}std*"):
            p.unlink(missing_ok=True)


# --------------------------------------------------------------------- 标准弹接入

def test_workflow_uses_standard_missile(run_small):
    prov = run_small["provenance"]
    assert prov["standard"]["name"] == "PL-12"
    assert prov["standard"]["profile_hash"]
    assert prov["burn"]["model"] == "finite"
    # 标准弹接管了引信半径与寿命（PL-12 = 10 m / 80 s，而非 120C5 的 12 / 120）
    assert prov["hit_radius_m"] == pytest.approx(10.0)
    assert prov["t_life_s"] == pytest.approx(80.0)
    assert prov["loft"]["elevation_deg"] == pytest.approx(20.0)
    assert "backend=standard" in run_small["provenance_line"]


def test_workflow_records_provenance_to_json(run_small):
    doc = json.loads((ROOT / "results" / f"workflow_{TAG}.json").read_text(encoding="utf-8"))
    assert doc["provenance"]["standard"]["name"] == "PL-12"
    assert doc["provenance_line"] == run_small["provenance_line"]
    # 旧读者兼容：missiles 与 missiles_blkx 指向同一份数据
    assert doc["missiles"] == doc["missiles_blkx"]


def test_switching_standard_changes_provenance_and_physics():
    a = workflow.build_sim_config(dict(SMALL))
    b = workflow.build_sim_config(dict(SMALL, standard={"name": "R-77-1"}))
    pa, pb = provenance(a), provenance(b)
    assert pa["standard"]["profile_hash"] != pb["standard"]["profile_hash"]
    assert pb["standard"]["name"] == "R-77-1"
    # R-77-1 单段、干重 119 kg、引信 10 m；PL-12 两段、干重 132 kg
    assert pb["burn"]["two_stage"] is False
    assert pa["burn"]["two_stage"] is True
    assert pa["standard"]["dry_mass"] != pb["standard"]["dry_mass"]


def test_explicit_sim_override_beats_standard():
    """显式覆盖必须压过标准弹（顺序写反就会被标准弹悄悄冲掉）。"""
    m = workflow.build_sim_config(dict(SMALL, sim={"theta_loft_deg": 33.0, "hit_radius": 25.0}))
    assert m.sim.theta_loft_deg == pytest.approx(33.0)      # PL-12 本是 20
    assert m.sim.hit_radius == pytest.approx(25.0)          # PL-12 本是 10
    m2 = workflow.build_sim_config(dict(SMALL))
    assert m2.sim.theta_loft_deg == pytest.approx(20.0)


def test_burn_instant_is_selectable():
    m = workflow.build_sim_config(dict(SMALL, standard={"name": "120C", "burn": "instant"}))
    assert m.burn.model == "instant"
    assert provenance(m)["burn"]["model"] == "instant"


# --------------------------------------------------------------------- 逐弹

def test_evaluate_missiles_switches_standard_per_missile():
    m = workflow.build_sim_config(dict(SMALL))
    rows = workflow.evaluate_missiles(m, workflow.load_wt_missiles())
    assert len(rows) == 11
    hashes = {r["profile_hash"] for r in rows}
    assert len(hashes) == 11, "每型必须有自己的标准弹指纹"
    labels = {r["label"] for r in rows}
    assert {"PL-12", "120C", "MICA"} <= labels
    for r in rows:
        assert r["standard"] == r["label"] and r["standard_error"] is None
    # 引信半径随型不同（PL-12 = 10 m，120C = 12 m）
    by = {r["label"]: r for r in rows}
    assert by["PL-12"]["hit_radius_m"] == pytest.approx(10.0)
    assert by["120C"]["hit_radius_m"] == pytest.approx(12.0)


# --------------------------------------------------------------------- provenance 边界

def test_provenance_without_standard_has_note():
    m = load_config()
    m.standard.name = ""
    from missile_sim.config import apply_standard

    apply_standard(m)
    p = provenance(m)
    assert p["standard"]["name"] is None
    assert "未启用标准弹" in p["standard"]["note"]
    assert p["burn"]["model"] == "instant"
    assert "无标准弹" in summary_line(p)


def test_provenance_extra_is_merged():
    p = provenance(load_config(), extra={"elf_sha256": "deadbeef", "injected": True})
    assert p["elf_sha256"] == "deadbeef" and p["injected"] is True


# --------------------------------------------------------------------- 等时线为空

def test_empty_isolines_warns_but_does_not_crash():
    """iso_step 远大于命中时间跨度时抽不出等时线：应给出空层且不崩（并在运行时打印）。"""
    import contextlib
    import io

    cfg = dict(SMALL, compare={"tag": f"{TAG}_iso", "iso_step": 9999.0})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        summary = workflow.run_workflow(cfg, verbose=True)
    out = buf.getvalue()
    assert "等时线" in out
    assert summary["results"]["iso_levels"] == []
    for p in (ROOT / "figures").glob(f"workflow_{TAG}_iso*"):
        p.unlink(missing_ok=True)
    for p in (ROOT / "results").glob(f"workflow_{TAG}_iso*"):
        p.unlink(missing_ok=True)


def test_figures_are_byte_reproducible():
    """同一输入跑两次，图必须逐字节一致（否则 git 里每次都是假 diff）。"""
    import hashlib

    def h():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT / "figures").glob(f"workflow_{TAG}_rep*"))}

    cfg = dict(SMALL, compare={"tag": f"{TAG}_rep", "iso_step": 2.0})
    workflow.run_workflow(cfg, verbose=False)
    a = h()
    workflow.run_workflow(cfg, verbose=False)
    b = h()
    assert a and a == b
    for p in (ROOT / "figures").glob(f"workflow_{TAG}_rep*"):
        p.unlink(missing_ok=True)
    for p in (ROOT / "results").glob(f"workflow_{TAG}_rep*"):
        p.unlink(missing_ok=True)

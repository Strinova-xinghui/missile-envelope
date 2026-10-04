# -*- coding: utf-8 -*-
"""全弹池目录（`missile_sim.catalog`）的判据。

**为什么需要**（用户 2026-10-04 口径）：三张图要能按"用户自选弹池"**实时**自适应，就要求弹的
坐标在页面本地可得 ⇒ 构建期把内核**全部**预设算成目录随包发布。这份判据钉四件事：

| 判据 | 为什么 |
| --- | --- |
| 覆盖内核预设**全表**（当前 168 条） | 目录缺条目 = 用户在页面上选不到那枚弹，而且**看不出来** |
| 11 弹池的坐标与既有实现**逐值相等** | 目录**不是**第二套数：ΔV/BC 必须等于 `mapping.blk_metrics`、β/γ 等于 `bg.point_of` |
| 不可算的条目**带内核原话原因**，且**保留**在表里 | 现在是 `propulsion*` 多发动机族的 9 条（PL-15 与 AIM-54 系）；静默丢弃会让人以为"内核里没有这型号" |
| `*_default` 孪生**折叠**而不是删除 | 折叠（`duplicate_of` + `default_hidden`）保住"总数 == 内核预设数"这条不变量 |

**反证（真的演练）**：`test_verify_rejects_tampered_or_truncated_catalogs` 逐类篡改目录
（改 `dv` / 删条目 / 改 schema / 改非池内 `gamma`），`catalog.verify()` 必须当场抛错。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _vendor_data  # noqa: E402
from missile_sim import bg, catalog, pool, solver  # noqa: E402

pytestmark = pytest.mark.skipif(not _vendor_data.ready(), reason=_vendor_data.missing_reason())

#: 2.59.0.28 实测：内核预设 168 条、可算 159 条、不可算 9 条 = 5 个型号（含 `_default` 孪生）。
N_PRESETS = 168
N_UNCOMPUTABLE = 9
UNCOMPUTABLE_KEYS = (
    "cn_pl15", "cn_pl15_default",
    "us_aim_54a", "us_aim_54a_default", "us_aim_54b",
    "us_aim_54c", "us_aim_54c_default", "us_aim_54c_plus", "us_aim_54c_plus_default",
)


@pytest.fixture(scope="module")
def rec():
    return catalog.build()


def test_catalog_covers_every_kernel_preset(rec):
    """目录必须**覆盖内核预设全表**，且 11 弹池被正确标出。"""
    names = list(solver.preset_names())
    assert len(names) == N_PRESETS, \
        f"内核预设数变了（{len(names)} ≠ {N_PRESETS}）—— 换内核版本时这条与本文件顶部常量要一起看"
    assert rec["schema"] == catalog.SCHEMA
    assert rec["count"] == len(names)
    seen = {m["native"] for m in rec["missiles"]} | {u["native"] for u in rec["unsupported"]}
    assert seen == set(names), "目录没有覆盖内核预设表"
    assert rec["computable"] == len(rec["missiles"])
    assert rec["computable"] + len(rec["unsupported"]) == rec["count"]
    assert sum(1 for m in rec["missiles"] if m["in_pool11"]) == len(pool.POOL) == 11
    ident = solver.identity()
    assert rec["solver"]["sha256"] == ident["sha256"]
    assert rec["solver"]["n_profiles"] == len(names)
    assert rec["archive_sha256"] == ident["archive_sha256"]
    assert len(rec["reference"]) == 6 and rec["reference"]["alt_m"] == bg.REF_ALT_M


def test_catalog_values_equal_the_existing_implementations(rec):
    """11 弹池逐值相等 —— 目录**不是**第二套数。"""
    rows = {m["native"]: m for m in rec["missiles"]}
    for e in pool.POOL:
        metrics = pool.metrics_of(e)
        point = bg.point_of(e)
        row = rows[e.native]
        assert row["dv"] == metrics.dv, e.key
        assert row["bc"] == metrics.bc, e.key
        assert row["gamma"] == point.gamma, e.key
        assert row["ginv"] == bg.ginv_of(point.gamma), e.key
        assert row["key"] == e.key and row["full_name"] == e.full_name
        assert row["in_pool11"] is True and row["duplicate_of"] is None


def test_unsupported_entries_are_few_and_carry_the_kernel_reason(rec):
    """不可算的条目：数量、名单、**原因必须有原话**（不许猜、不许静默丢）。"""
    bad = rec["unsupported"]
    assert len(bad) == N_UNCOMPUTABLE, \
        f"不可算条目数变了（{len(bad)} ≠ {N_UNCOMPUTABLE}）—— 支持了新发动机族就要更新这条"
    assert sorted(u["key"] for u in bad) == sorted(UNCOMPUTABLE_KEYS)
    for u in bad:
        assert str(u.get("reason") or "").strip(), f"{u['key']} 没带原因"
        assert "propulsion" in u["reason"], f"{u['key']} 的原因不是多发动机族：{u['reason']}"
        assert u["in_pool11"] is False


def test_default_twins_are_folded_not_dropped(rec):
    """`x_default` 与 `x` 同型号 ⇒ 标 `duplicate_of` 并默认隐藏，但**留在表里**。"""
    names = {m["native"] for m in rec["missiles"]} | {u["native"] for u in rec["unsupported"]}
    folded = 0
    for m in list(rec["missiles"]) + list(rec["unsupported"]):
        native = str(m["native"])
        base = native[: -len("_default")] if native.endswith("_default") else None
        if base and base in names:
            assert m["duplicate_of"] == base, native
            assert m["default_hidden"] is True, native
            folded += 1
        else:
            assert m["duplicate_of"] is None, native
            assert m["default_hidden"] is False, native
    assert folded > 0, "一条 _default 孪生都没折 —— 折叠规则或数据变了"


def test_verify_rejects_tampered_or_truncated_catalogs(rec):
    """**反证**：改数、删条目、改 schema 都必须当场炸（四种篡改逐个演练）。"""
    first = pool.POOL[0].native

    tampered = copy.deepcopy(rec)
    for m in tampered["missiles"]:
        if m["native"] == first:
            m["dv"] += 1.0
    with pytest.raises(catalog.CatalogError):
        catalog.verify(tampered, full=False)          # 11 弹池那一档就能抓到

    truncated = copy.deepcopy(rec)
    truncated["missiles"] = [m for m in truncated["missiles"] if m["native"] != first]
    with pytest.raises(catalog.CatalogError):
        catalog.verify(truncated, full=False)

    bumped = copy.deepcopy(rec)
    bumped["schema"] = catalog.SCHEMA + 1
    with pytest.raises(catalog.CatalogError):
        catalog.verify(bumped, full=False)

    off_pool = copy.deepcopy(rec)
    for m in off_pool["missiles"]:
        if not m["in_pool11"]:
            m["gamma"] += 1.0
            break
    with pytest.raises(catalog.CatalogError):
        catalog.verify(off_pool, full=True)           # 非池内条目只有全表校验才管


def test_catalog_round_trips_through_json(tmp_path, rec):
    """落盘/读回一致（除 `generated_utc`），且读回来的记录仍然过校验。"""
    path = catalog.write_json(tmp_path / catalog.NAME)
    assert path.is_file() and path.name == catalog.NAME
    got = catalog.load(path)
    assert got["generated_utc"].endswith("+00:00") and "T" in got["generated_utc"]
    strip = lambda d: {k: v for k, v in d.items() if k != "generated_utc"}   # noqa: E731
    assert strip(got) == strip(rec)
    catalog.verify(got, full=False)

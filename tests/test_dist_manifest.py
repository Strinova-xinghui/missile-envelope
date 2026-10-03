"""分发包清单的**列表级**判据（不组装、不联网、秒级）。

来由（v6 收尾实测）：`REQUIRED_IN_BUNDLE` 加了两份 `results/*.json`（静态形态 manifest），
而 `RESULTS_KEEP` 忘了同步 —— `make_dist.py` 的 `verify_bundle()` 只在**组装期**
（文件已经不在包里）才炸，CI 与包内自检都看不见这类漂移。这里把同一条判断提到**列表级**，
谁改漂了当场红：不碰磁盘、不跑打包。

三条：
1. 必带清单每一条都要有产出规则；
2. KEEP 清单/`RESULTS_GLOBS`/测试文件都要真的在位（`build_tree()` 是 `if s.exists()` 才拷，
   写错名字会**静默少拷**）；
3. 反向判据：故意塞一个不存在于任何 KEEP 清单的必带项，必须被点名 —— 免得前两条变成橡皮图章；
4. 文档里那行"仓库 a − 排除 b = 包内 c"必须等于**算出来的**（`--sync-docs` 生成的那一行）。

⚠ 包内（收件人那份）**没有 `make_dist.py`**（组装脚本不随包），所以这几条在那里记 **SKIP**，
与 `-k viewer3d` 在无 node 时同样的口径：跳过 ≠ 通过。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKE_DIST = ROOT / "make_dist.py"


def _load_make_dist():
    """把组装脚本当模块加载（它只在 `__main__` 里干活，import 期无副作用）。"""
    if not MAKE_DIST.is_file():
        pytest.skip("包内没有 make_dist.py（组装脚本不随包），清单判据无从查起")
    spec = importlib.util.spec_from_file_location("make_dist_for_tests", MAKE_DIST)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_required_in_bundle_every_entry_has_a_producing_rule():
    """必带清单里的每一条，都要能由某条拷贝/生成规则解释。"""
    mk = _load_make_dist()
    uncovered = [rel for rel, rule in mk.required_coverage() if rule is None]
    assert not uncovered, (
        "REQUIRED_IN_BUNDLE 里这些条目没有任何拷贝/生成规则能产出（清单漂移，"
        f"组装期才会炸）：{uncovered}"
    )
    # 顺带把"规则名不是空白"也钉住：防止有人写了规则但规则名是空串（等于没写）
    blank = [rel for rel, rule in mk.required_coverage() if rule is not None and not rule.strip()]
    assert not blank, f"这些必带项的产出规则名是空的：{blank}"


def test_keep_lists_and_test_files_are_all_present():
    """KEEP 清单、`RESULTS_GLOBS`、运行器必需文件都要在位（否则是**静默少拷**）。"""
    mk = _load_make_dist()
    problems = mk.manifest_problems()
    assert not problems, "清单指向了仓库里不存在的文件/glob 空转：\n  - " + "\n  - ".join(problems)
    # 与 `build_tree()` 同源：包里会带的测试文件 = tests/ 全量 − TESTS_EXCLUDE
    shipped = set(mk.tests_shipped())
    assert "run_tests.py" in shipped and "test_dist_manifest.py" in shipped
    for mod in mk.TESTS_EXCLUDE:
        assert mod not in shipped, f"{mod} 应当被 TESTS_EXCLUDE 排除，却还在待拷清单里"


def test_negative_control_uncovered_entry_is_reported():
    """反向判据：塞一个没人产出、也不在任何 KEEP 清单里的必带项，必须被点名。"""
    mk = _load_make_dist()
    bogus = "results/definitely_not_kept_4f2c.json"
    saved = list(mk.REQUIRED_IN_BUNDLE)
    try:
        mk.REQUIRED_IN_BUNDLE.append(bogus)
        uncovered = [rel for rel, rule in mk.required_coverage() if rule is None]
        assert uncovered == [bogus], f"反向判据失效：期望只点名 {bogus}，实际 {uncovered}"
        assert any(bogus in p for p in mk.manifest_problems()), "manifest_problems() 没报出来"
    finally:
        mk.REQUIRED_IN_BUNDLE[:] = saved
    # 还原后必须重新干净 —— 否则说明判据污染了模块状态
    assert [rel for rel, rule in mk.required_coverage() if rule is None] == []


def test_doc_selftest_counts_block_matches_the_runner_collector():
    """文档里那行自检项数必须等于**数出来的**（同一处推导，见 `make_dist.py --sync-docs`）。"""
    mk = _load_make_dist()
    counts = mk.test_item_counts()
    assert counts["packaged"] == counts["total"] - counts["excluded"] > 0
    assert counts["excluded"] > 0, (
        f"仓库里应当能数到被 TESTS_EXCLUDE{list(mk.TESTS_EXCLUDE)} 排掉的用例；"
        f"数到 0 说明那两个模块不在了（列表该跟着清，或测试文件丢了）"
    )
    problems = mk.doc_block_problems(counts)
    assert not problems, (
        "文档里的自检项数与算出来的不一致（跑 `python make_dist.py --sync-docs` 重新生成）：\n  - "
        + "\n  - ".join(problems)
    )

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
4. 文档里那行"仓库 a − 排除 b = 包内 c"必须等于**算出来的**（`--sync-docs` 生成的那一行）；
5. **许可正文必须随包**（`app/LICENSE`）+ `pyproject.toml` 有 `license` 表达式（2026-10-04 加；
   与选型无关 —— 协议名与反证由 `tests/test_license.py` 钉）。

⚠ 包内（收件人那份）**没有 `make_dist.py`**（组装脚本不随包），所以这几条在那里记 **SKIP**，
与 `-k viewer3d` 在无 node 时同样的口径：跳过 ≠ 通过。
"""

from __future__ import annotations

import importlib.util
import re
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


def test_make_dist_fig3_cube_glob_hits_exactly_one_live_cube():
    """`make_dist.py` 的 cube glob 必须**恰好命中 1 份，且是当前 `cube_key()` 那份**。

    反向演练（就在本用例里）：把 2026-10-04 换 ginv 轴前那份指纹塞回去 ⇒ 必须红。
    `RESULTS_GLOBS = ["fig3_cube_*.json"]` 是**按 glob 全带**，旧指纹那份会一起进包
    （语义过期、看起来还活着）—— 这就是这条判据存在的理由。
    """
    mk = _load_make_dist()
    live = mk.live_fig3_cube()
    hits = sorted(p.name for p in (ROOT / "results").glob(mk.CUBE_GLOB))
    assert hits == [live["name"]], (
        f"`results/{mk.CUBE_GLOB}` 应当恰好命中当前指纹那份 [{live['name']}]，实际 {hits}"
    )
    assert mk.fig3_cube_problems() == [], f"真实仓库应当干净：{mk.fig3_cube_problems()}"

    stale = "fig3_cube_PL-12_1989434c.json"          # 换 ginv 轴前那一份（历史指纹）
    two = mk.fig3_cube_problems(names=[live["name"], stale])
    assert any(stale in p for p in two), f"两份并存时没点名旧那份：{two}"
    assert any("git rm" in p for p in two), f"两份并存时没给出 `git rm` 处置：{two}"
    assert any("命中 2 份" in p for p in two), f"两份并存时没报命中数：{two}"
    one_stale = mk.fig3_cube_problems(names=[stale])
    assert any(stale in p for p in one_stale) and \
        any("没有**当前指纹**那份" in p for p in one_stale), f"只有旧那份时没报全：{one_stale}"
    assert mk.fig3_cube_problems(names=[]), "一份都没有时必须红（缺当前指纹那份）"
    assert mk.fig3_cube_problems(names=[live["name"]]) == [], "干净那一份不许被误报"


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


def test_bundle_ships_a_license_body_and_the_metadata_agrees():
    """分发包必须**带上许可正文**（`app/LICENSE`），且 `pyproject.toml` 里有许可表达式。

    来由（2026-10-04 实测缺口）：包内当时只有内嵌 Python 的 `python/LICENSE.txt` 与各第三方
    `dist-info` 许可，**仓库根的 `LICENSE` 根本没进包** —— 收件人拿到的是"没有许可正文的软件"。
    这条**与选型无关**（不管最后选 AGPL / GPL / 别的，"正文必须随包"都成立），所以只查：
    `LICENSE` 在必带清单里 + 有产出规则 + 仓库里真有这份文件 + `pyproject.toml` 有 `license` 表达式。
    协议名与反证由 `tests/test_license.py` 钉（那一份两边都跑：仓库根与包内 `app/`）。
    """
    mk = _load_make_dist()
    assert "LICENSE" in mk.REQUIRED_IN_BUNDLE, (
        "REQUIRED_IN_BUNDLE 里没有 LICENSE —— 拷了也没被判据钉住（只拷不判 = 下次漏拷没人发现）"
    )
    rules = dict(mk.required_coverage())
    assert rules.get("LICENSE"), "LICENSE 没有任何产出规则（这类漂移只在组装期才会炸）"
    assert (ROOT / "LICENSE").is_file(), "仓库根的 LICENSE 不在位"

    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^\s*license\s*=\s*"([^"]+)"', py)
    assert m, 'pyproject.toml 里没有 `license = "…"` 表达式（PEP 639 那份"机器可读声明"）'
    assert m.group(1).strip(), "pyproject.toml 的 license 表达式是空的"

    # 反向演练：把必带项改名成谁都产不出的名字，必须被点名（免得上面两条变橡皮图章）
    saved = list(mk.REQUIRED_IN_BUNDLE)
    try:
        mk.REQUIRED_IN_BUNDLE[mk.REQUIRED_IN_BUNDLE.index("LICENSE")] = "LICENSE-mit.txt"
        uncovered = [rel for rel, rule in mk.required_coverage() if rule is None]
        assert uncovered == ["LICENSE-mit.txt"], f"把 LICENSE 改名后没被点名：{uncovered}"
        assert any("LICENSE-mit.txt" in p for p in mk.manifest_problems()), "manifest_problems() 没报出来"
    finally:
        mk.REQUIRED_IN_BUNDLE[:] = saved

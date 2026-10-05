# -*- coding: utf-8 -*-
"""判据：**环境里有没有真 pytest，都不许改变自检结果**（两套 fixture 注册表必须唯一）。

背景（2026-10-05 实测事故）：`%APPDATA%\\Python\\Python3xx\\site-packages` 里装上了 pytest 9.1.1
⇒ `tests/conftest.py` 的 `try: import pytest` 分支用**真 pytest** 注册 fixture，而
`tests/run_tests.py` 自己驱动用例、只认 shim 的 `_dsh_is_fixture` 标记 ⇒ `-k grid_axis` /
`-k catalog` 成片假失败（`未定义的 fixture: pool_points / rec / tmp_path`）。

修法：`run_tests._make_pytest_shim()` **无条件**把 shim 注册成 `sys.modules["pytest"]`。
这里两条判据（都在**子进程**里做，避免污染本进程的 `sys.modules`）：

* ① 场景"环境里有真 pytest"（子进程里预置一个**假** pytest 模块）⇒ 跑一个**用 fixture** 的探针
  用例（`test_grid_axis::test_axis_covers_all_points`）必须 **PASS**、退出码 0；
* ② 反证：同一个假 pytest 场景下，**不经过** `_make_pytest_shim()` 直接 `collect()` ⇒ fixture
  解析必须失败（`KeyError: 未定义的 fixture: pool_points`）—— 也就是"把注入那一步拿掉"。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "run_tests.py"
PROBE = "test_axis_covers_all_points"          # 用 `pool_points` fixture 的用例（11 弹池）
PROBE_FIXTURE = "pool_points"

#: 子进程里预置的"假 pytest"：**故意**不提供 shim 的标记 `_dsh_is_fixture`
#: （模拟"环境里有一个别的 pytest"）。`mark` 要给，否则收集阶段就会在
#: `pytestmark = pytest.mark.skipif(...)` 上先炸掉，摸不到我们真正要看的 fixture 解析。
_FAKE = (
    "import sys, types\n"
    "class _Mark:\n"
    "    def __getattr__(self, item):\n"
    "        def deco(*a, **k):\n"
    "            return a[0] if (len(a) == 1 and callable(a[0])) else (lambda f: f)\n"
    "        return deco\n"
    "fake = types.ModuleType('pytest')\n"
    "fake.fixture = lambda *a, **k: (a[0] if (len(a) == 1 and callable(a[0])) else (lambda f: f))\n"
    "fake.mark = _Mark()\n"
    "fake.approx = lambda v, **k: v\n"
    "fake.skip = lambda *a, **k: None\n"
    "sys.modules['pytest'] = fake\n"
)


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", timeout=600)


def test_runner_still_resolves_fixtures_when_a_foreign_pytest_exists():
    """① 环境里已有别的 pytest ⇒ runner 仍必须能把 fixture 解析出来（探针用例 PASS）。"""
    code = (
        _FAKE
        + "import runpy, sys\n"
        + f"sys.argv = [r'{RUNNER}', '-k', '{PROBE}']\n"
        + f"runpy.run_path(r'{RUNNER}', run_name='__main__')\n"
    )
    got = _run(code)
    out = (got.stdout or "") + (got.stderr or "")
    assert f"PASS test_grid_axis::{PROBE}" in out, out[-1500:]
    assert "未定义的 fixture" not in out, out[-800:]
    assert got.returncode == 0, f"退出码 {got.returncode}\n{out[-800:]}"


def test_without_the_shim_injection_fixtures_vanish():
    """② 反证：不注入 shim（等价于"把 `_make_pytest_shim()` 里那一步拿掉"）⇒ fixture 必须解析失败。

    这段子进程**只**做三件事：塞一个假 pytest、`import run_tests`、`collect()` ——
    不调用 `_make_pytest_shim()`，所以 runner 眼里的 "pytest" 是那个假货，而它只认
    shim 的 `_dsh_is_fixture` 标记 ⇒ 探针 fixture 必然找不到。找不到（拿到 KeyError）才算这条
    反证成立；**如果它能解析成功，说明"注入 shim"根本没起作用**（判据①就是橡皮图章）。
    """
    code = (
        _FAKE
        + "import sys\n"
        + f"sys.path[:0] = [r'{ROOT / 'src'}', r'{ROOT / 'tests'}']\n"
        + "import run_tests as R\n"
        + "cases = R.collect(R.ROOT / 'tests')\n"
        + f"probe = [c for c in cases if c[1] == '{PROBE}']\n"
        + "assert probe, '没收集到探针用例 '\n"
        + "entry = probe[0]\n"
        + "fn, *rest = entry[2:]\n"
        + "factories = entry[-1]\n"
        + "try:\n"
        + f"    R._resolve_fixture('{PROBE_FIXTURE}', factories, {{}}, (), entry[1])\n"
        + "except KeyError as exc:\n"
        + f"    assert '{PROBE_FIXTURE}' in str(exc), exc\n"
        + "    print('RED-OK fixture 找不到：', exc)\n"
        + "    raise SystemExit(0)\n"
        + "raise SystemExit('✗ 不注入 shim 也能解析 fixture —— 这条反证没有牙')\n"
    )
    got = _run(code)
    out = (got.stdout or "") + (got.stderr or "")
    assert got.returncode == 0, out[-1500:]
    assert "RED-OK" in out, out[-800:]


def test_shim_injection_is_the_only_pytest_the_runner_registers():
    """③ runner 注入的对象必须是 shim 本身（不是"环境里的那个"）。"""
    code = (
        "import sys, types\n"
        + "fake = types.ModuleType('pytest')\n"
        + "sys.modules['pytest'] = fake\n"
        + f"sys.path[:0] = [r'{ROOT / 'src'}', r'{ROOT / 'tests'}']\n"
        + "import run_tests as R\n"
        + "got = R._make_pytest_shim()\n"
        + "import _pytest_shim\n"
        + "assert got is _pytest_shim, got\n"
        + "assert sys.modules['pytest'] is _pytest_shim\n"
        + "print('SHIM-OK')\n"
    )
    got = _run(code)
    out = (got.stdout or "") + (got.stderr or "")
    assert got.returncode == 0, out[-800:]
    assert "SHIM-OK" in out, out[-800:]

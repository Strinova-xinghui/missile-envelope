"""零依赖测试运行器（pytest 不可用时的替代，语法与 pytest 兼容）。

用法：
    python tests/run_tests.py                 # 跑全部
    python tests/run_tests.py -k batch        # 只跑名字包含 batch 的用例
    python tests/run_tests.py -l              # 列出用例

支持的 pytest 子集：模块级 test_* 函数、fixture（按名字注入，支持 fixture 调用 fixture）、
@pytest.mark.parametrize 参数化、pytest.raises / pytest.approx（由 tests/_pytest_shim.py 提供）。
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _make_pytest_shim():
    """尽量用真 pytest；不可用时注册 tests/_pytest_shim.py。"""
    try:
        import pytest  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    import _pytest_shim

    sys.modules["pytest"] = _pytest_shim  # type: ignore[assignment]


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _fixture_factories(mod):
    import pytest

    out = {}
    for name, obj in vars(mod).items():
        if callable(obj) and getattr(obj, "_dsh_is_fixture", False):
            out[name] = obj
    return out


def _resolve_fixture(name, factories, cache, stack=(), mod_name=""):
    if name in cache:
        return cache[name]
    if name not in factories:
        raise KeyError(f"未定义的 fixture: {name}")
    if name in stack:
        raise RuntimeError(f"fixture 循环依赖: {stack + (name,)}")
    fn = factories[name]
    scope = getattr(fn, "_dsh_fixture_scope", "function")
    skey = (mod_name, scope, name)
    if scope != "function" and skey in _SCOPED:
        return _SCOPED[skey]
    kwargs = {p: _resolve_fixture(p, factories, cache, stack + (name,), mod_name)
              for p in _params(fn)}
    gen = fn(**kwargs)
    if inspect.isgenerator(gen):  # 支持 yield fixture
        value = next(gen)
        cache[name] = value
        if scope == "function":
            _GENERATORS.append(gen)
        else:                                   # 收尾推迟到作用域结束（见 _teardown_scope）
            _SCOPED_GENS.append((mod_name, gen))
        _SCOPED[skey] = value
        return value
    cache[name] = value = gen
    _SCOPED[skey] = value
    return value


#: 函数级 yield fixture 的收尾发生器（每个用例结束就收）。
_GENERATORS: list = []
#: 非函数级（module/session）fixture 的值与收尾发生器 —— **跨用例复用**。
_SCOPED: dict = {}
_SCOPED_GENS: list = []


def _teardown_scope(mod_name=None):
    """收尾某个模块的 module/session 级 yield fixture（`None` = 全部）。

    `run_small`（`scope="module"`）的收尾会删掉 `results/workflow_pytest*`；必须在**该模块
    最后一个用例之后**才收，否则后面的用例找不到产物。
    """
    while _SCOPED_GENS and (mod_name is None or _SCOPED_GENS[-1][0] == mod_name):
        _m, gen = _SCOPED_GENS.pop()
        try:
            next(gen)
        except StopIteration:
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def _params(fn):
    return [p.name for p in inspect.signature(fn).parameters.values()]


def collect(test_dir: Path):
    """返回 [(module_name, test_name, fn, kwargs, params, factories)]；conftest.py 的 fixture 作为全局 fixture。"""
    global_fixtures = {}
    conftest = test_dir / "conftest.py"
    if conftest.exists():
        _load_module(conftest)  # 触发 sys.path 引导
        global_fixtures = _fixture_factories(_load_module(conftest))

    cases = []
    for path in sorted(test_dir.glob("test_*.py")):
        mod = _load_module(path)
        factories = dict(global_fixtures)
        factories.update(_fixture_factories(mod))
        for name, obj in vars(mod).items():
            if not name.startswith("test_") or not callable(obj):
                continue
            paramsets = getattr(obj, "_dsh_paramsets", None)
            if paramsets is None:
                paramsets = [{}]
            params = [p for p in _params(obj) if p not in paramsets[0]]
            for extra in paramsets:
                cases.append((path.stem, f"{name}{_suffix(extra)}", obj, extra, params, factories))
    return cases


def _suffix(kwargs):
    if not kwargs:
        return ""
    inner = "-".join(f"{k}={v}" for k, v in kwargs.items())
    return f"[{inner}]"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", dest="filter", default=None, help="只运行名字包含该子串的用例")
    ap.add_argument("-l", "--list", action="store_true", help="列出用例后退出")
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args(argv)

    _make_pytest_shim()
    cases = collect(Path(args.dir))
    if args.filter:
        cases = [c for c in cases if args.filter in c[1] or args.filter in c[0]]

    if args.list:
        for mod, name, *_ in cases:
            print(f"{mod}::{name}")
        print(f"\n共 {len(cases)} 个用例")
        return 0

    n_pass = n_fail = 0
    failures = []
    t_start = time.perf_counter()
    cur_mod = None
    for mod_name, name, fn, extra, params, factories in cases:
        if mod_name != cur_mod:                     # 模块边界：收掉上一个模块的作用域 fixture
            if cur_mod is not None:
                _teardown_scope(cur_mod)
            cur_mod = mod_name
        cache = {}
        try:
            kwargs = dict(extra)
            for p in _params(fn):
                if p in kwargs:
                    continue
                kwargs[p] = _resolve_fixture(p, factories, cache, (), mod_name)
            fn(**kwargs)
            n_pass += 1
            print(f"PASS {mod_name}::{name}")
        except Exception as exc:  # noqa: BLE001
            n_fail += 1
            failures.append((mod_name, name, exc, traceback.format_exc()))
            print(f"FAIL {mod_name}::{name}: {type(exc).__name__}: {exc}")
        finally:
            while _GENERATORS:  # 结束**函数级** yield fixture（模块级留到模块边界）
                gen = _GENERATORS.pop()
                try:
                    next(gen)
                except StopIteration:
                    pass
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
    _teardown_scope()
    wall = time.perf_counter() - t_start

    print("\n" + "=" * 70)
    for mod_name, name, exc, tb in failures:
        print(f"\n--- {mod_name}::{name} ---\n{tb.rstrip()}")
    print("=" * 70)
    print(f"通过 {n_pass} / 失败 {n_fail} / 共 {n_pass + n_fail}，用时 {wall:.1f} s")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

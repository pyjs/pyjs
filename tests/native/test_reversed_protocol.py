import cProfile

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java.transpiler import transpile_jvm
from pyjs.native.llvm import transpile_llvm
from pyjs.python.native import reversed_result
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly.transpiler import transpile_webassembly
from tests.backend_semantics import REVERSED_PROTOCOL_CONTRACT
from tests.semantics.helpers import run_javascript


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_reversed_protocol_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        REVERSED_PROTOCOL_CONTRACT.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0, REVERSED_PROTOCOL_CONTRACT.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reversed_virtual_protocols_effects_and_gc(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self, events: list[str]):
                self.events = events
            def __reversed__(self) -> Iterator[str]:
                self.events.append("base")
                gc_collect()
                yield "three"
                yield "two"

        class MoreValues(Values):
            def __reversed__(self) -> Iterator[str]:
                self.events.append("derived")
                yield "seven"
                gc_collect()
                yield "five"

        class Narrow:
            @staticmethod
            def __reversed__() -> int8:
                return int8(127)

        class Failing:
            def __init__(self, events: list[str]):
                self.events = events
            def __reversed__(self) -> int:
                self.events.append("method")
                gc_collect()
                raise ValueError("method failed")

        def make(events: list[str], fail: bool) -> Failing:
            events.append("receiver")
            gc_collect()
            if fail:
                raise ValueError("receiver failed")
            return Failing(events)

        def collect(values: Values) -> list[str]:
            return list(reversed(values))

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            base = collect(Values(events))
            derived = collect(MoreValues(events))
            cursor = reversed(MoreValues(events))
            first = next(cursor)
            gc_collect()
            rest = list(cursor)
            narrow: list[int8] = [reversed(Narrow())]
            for fail in [False, True]:
                try:
                    reversed(make(events, fail))
                except ValueError as error:
                    events.append(str(error))
            return repr((base, derived, first, rest, narrow, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reversed_class_lookup_unions_and_disabled_overrides(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def fake() -> int: return 42
        class Base:
            def __init__(self):
                self.__reversed__: Callable[[], int] = fake
            def __reversed__(self) -> int:
                gc_collect()
                return 7
        class Disabled(Base):
            __reversed__ = None
        class Restored(Disabled):
            def __reversed__(self) -> int: return 8
        class Static:
            @staticmethod
            def __reversed__() -> int: return 9
        def nominal(value: Base) -> str:
            try:
                return str(reversed(value))
            except TypeError:
                return "disabled"
        def union(value: Base | Static) -> str:
            try:
                return str(reversed(value))
            except TypeError:
                return "disabled"
        def main() -> str:
            gc_set_threshold(1)
            value = Base()
            return repr((nominal(value), value.__reversed__(), nominal(Disabled()),
                         nominal(Restored()), union(value), union(Disabled()),
                         union(Restored()), union(Static())))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("transpile", [transpile_llvm, transpile_jvm, transpile_webassembly])
@pytest.mark.parametrize("declaration", [
    "__reversed__ = None",
    "@property\n    def __reversed__(self) -> int: return 3",
    "@classmethod\n    def __reversed__(cls) -> int: return 3",
    "def alternate(self) -> int: return 3\n    __reversed__ = alternate",
    "def __len__(self) -> int: return 2\n    def __getitem__(self, index: int) -> int: return index",
])
def test_reversed_protocol_keeps_explicit_descriptor_and_sequence_boundaries(transpile, declaration):
    source = f"class Value:\n    {declaration}\ndef main() -> int:\n    return reversed(Value())\n"
    with pytest.raises(CompilationError, match="native reversed requires an instance or static __reversed__ method"):
        transpile(source)


@pytest.mark.parametrize("transpile", [transpile_llvm, transpile_jvm, transpile_webassembly])
@pytest.mark.parametrize(("expression", "message"), [
    ("reversed()", "missing required argument"),
    ("reversed(1, 2)", "too many positional arguments"),
    ("reversed(values=[1])", "positional-only"),
    ("reversed(1)", "expects Iterable"),
])
def test_reversed_keeps_call_shape_and_builtin_diagnostics(transpile, expression, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile(f"def main() -> int:\n    return {expression}\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("optimize", [0, 2])
def test_reversed_owned_result_and_shadowed_builtin(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from builtins import reversed as reverse
        from pyjs.native import gc_collect, gc_set_threshold
        class Payload:
            def __init__(self, text: str): self.text = text
        class Owner:
            def __init__(self, value: Payload): self.value = value
            def __reversed__(self) -> Payload:
                gc_collect()
                return self.value
        def reversed(value: int) -> int: return value + 1
        def main() -> str:
            gc_set_threshold(1)
            payload = Payload("kept")
            same = reverse(Owner(payload))
            detached = reverse(Owner(Payload("detached")))
            gc_collect()
            return repr((same is payload, same.text, detached.text, reversed(3)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_reversed_keeps_the_javascript_builtin_boundary():
    with pytest.raises(CompilationError, match="Argument 'values' to reversed expects Iterable"):
        run_javascript(REVERSED_PROTOCOL_CONTRACT.print_source)


@pytest.mark.parametrize("application", [False, True])
def test_nested_reversed_analysis_grows_linearly(tmp_path, application):
    counts = []
    for depth in (4, 8):
        expression = "R(0)" if application else "[1, 2, 3]"
        for _ in range(depth):
            expression = f"reversed({expression})" if application else f"list(reversed({expression}))"
        prefix = ("class R:\n    def __init__(self, value: int): self.value = value\n"
                  "    def __reversed__(self) -> 'R': return R(self.value + 1)\n") if application else ""
        source = prefix + f"def main() -> int:\n    return {expression}" + (".value" if application else "[0]")
        # Count real analysis calls, without mocks or a machine-speed threshold.
        # Doubling syntax depth must not recursively duplicate the inner work.
        with cProfile.Profile() as profile:
            transpile_llvm(source)
        counts.append(sum(stat.callcount for stat in profile.getstats()
                          if stat.code is reversed_result.__code__))
    assert counts[0] >= 4
    assert counts[1] <= 2 * counts[0], counts
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=2,
                                          sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("transpile", [transpile_llvm, transpile_jvm, transpile_webassembly])
@pytest.mark.parametrize("base", ["list[int]", "str"])
def test_reversed_builtin_subclasses_have_an_explicit_boundary(transpile, base):
    source = f"class Value({base}): pass\ndef main() -> int:\n    return len(list(reversed(Value())))\n"
    with pytest.raises(CompilationError, match="native reversed does not support builtin-container subclasses") as caught:
        transpile(source)
    assert caught.value.lineno == 3


@pytest.mark.parametrize("transpile", [transpile_llvm, transpile_jvm, transpile_webassembly])
def test_reversed_mixed_builtin_application_union_has_an_explicit_boundary(transpile):
    source = """class Value:
    def __reversed__(self) -> list[int]: return [1]
def reverse(value: Value | list[int]) -> list[int]:
    return list(reversed(value))
def main() -> int:
    return len(reverse(Value()))
"""
    with pytest.raises(CompilationError, match="native reversed does not support mixed builtin and application receivers") as caught:
        transpile(source)
    assert caught.value.lineno == 4

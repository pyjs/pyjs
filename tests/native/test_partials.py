import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("attribute", ["overload", "_analyze_partial", "functools", "not_a_real_attribute"])
def test_functional_module_does_not_export_its_implementation_namespace(attribute):
    with pytest.raises(CompilationError, match=f"has no attribute '{attribute}'") as caught:
        transpile_llvm(f'''import functools as fn
def main() -> str:
    return str(fn.{attribute})
''', filename="functional_namespace.py")
    assert caught.value.filename == "functional_namespace.py"
    assert caught.value.lineno == 3


@pytest.mark.parametrize("optimize", [0, 2])
def test_functional_module_imports_share_typed_callback_and_partial_bindings(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import functools
        import functools as fn
        from functools import reduce as fold, partial as bind
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def add(left: int8, right: int8) -> int8:
            gc_collect()
            return left + right

        def shifted(left: int8, right: int8, extra: int8 = 1) -> int8:
            gc_collect()
            return left + right + extra

        def reduce(value: int) -> int:
            return value + 100

        def main() -> str:
            gc_set_threshold(1)
            values = [int8(100), int8(20), int8(10)]
            step = fn.partial(shifted, extra=int8(2))
            other = bind(shifted, extra=int8(3))
            unary = bind(shifted, functools.Placeholder, int8(4))
            return str([int(functools.reduce(add, values)),
                        int(fn.reduce(step, values, int8(0))),
                        int(fold(other, values, initial=int8(0))), reduce(1),
                        int(unary(int8(5)))])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_forwards_optional_source_arguments(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from functools import partial

        def add(left: int, right: int = 10) -> int:
            return left + right

        def main() -> str:
            callback = partial(add, 1)
            return str([callback(2), callback(), partial(add)(3), partial(partial(add), 4)()])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == "[3, 11, 13, 14]"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_optional_holes_defaults_and_virtual_receivers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from functools import Placeholder, partial
        from pyjs.native import gc_collect, gc_set_threshold

        def record(left: int, middle: int = 10, right: int = 100, *, seen: list[int] = []) -> int:
            seen.append(left)
            gc_collect()
            if left < 0:
                raise ValueError("negative")
            return left + middle + right + len(seen)

        class Base:
            def __init__(self, offset: int):
                self.offset = offset

            def add(self, left: int, right: int = 5) -> int:
                return self.offset + left + right

        class Child(Base):
            def add(self, left: int, right: int = 20) -> int:
                gc_collect()
                return self.offset + left + right

        def create(events: list[int]) -> Base:
            events.append(1)
            return Child(1000)

        def main() -> str:
            gc_set_threshold(1)
            callback = partial(record, Placeholder, 20)
            result = [callback(1), callback(2, 200)]
            try:
                callback(-1)
            except ValueError:
                result.append(-1)
            filled = partial(callback, 3)
            gc_collect()
            result.append(filled())
            result.append(filled(300))
            keyword = partial(record, 4, right=40)
            result.append(keyword(30))
            events: list[int] = []
            bound = partial(create(events).add, 5)
            gc_collect()
            result.extend([bound(), bound(50), len(events)])
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == "[122, 224, -1, 127, 328, 80, 1025, 1055, 1]"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_defaults_preserve_numeric_and_void_contracts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from functools import partial
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def add(left: int8, right: int8 = 2) -> int8:
            gc_collect()
            return left + right

        def large(left: int64, right: int64 = 3) -> int64:
            return left + right

        def record(values: list[int], value: int = 10) -> None:
            gc_collect()
            values.append(value)

        def main() -> str:
            gc_set_threshold(1)
            callback = partial(add, int8(127))
            short: Callable[[], int8] = callback
            result = [str(short()), str(callback(int8(3)))]
            wide = partial(large, int64(9007199254740993))
            result.append(str(wide()))
            result.append(str(wide(int64(4))))
            values: list[int] = []
            sink = partial(record, values)
            gc_collect()
            sink()
            sink(20)
            result.append(str(values))
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == "['-127', '-126', '9007199254740996', '9007199254740997', '[10, 20]']"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("declaration, binding, invocation, diagnostic", [
    ("left: int = 1, right: int = 2", "Placeholder, 3", "", "Callable expects 1 arguments, got 0"),
    ("left: int, right: int = 2", "1", "3, 4", "Callable expects 0 to 1 arguments, got 2"),
    ("left: int, *, right: int", "1", "", "Callable requires keyword-only arguments: right"),
    ("left: int = 1, right: int = 2", "right=3", "", "Callable expects 1 arguments, got 0"),
])
def test_partial_optional_signature_boundaries(declaration, binding, invocation, diagnostic):
    with pytest.raises(CompilationError, match=diagnostic):
        transpile_llvm(f'''
            from functools import Placeholder, partial

            def add({declaration}) -> int:
                return left + right

            def main() -> int:
                callback = partial(add, {binding})
                return callback({invocation})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_capture_views_none_and_lexical_cells(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        import functools as fn
        from functools import partial as bind
        from pyjs import float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def object_text(value: object) -> str:
            gc_collect()
            return str(value)

        def combine(callback: Callable[[int], str], value: int, suffix: str) -> str:
            gc_collect()
            return callback(value) + suffix

        def nullable(value: Box | None, suffix: str) -> str:
            gc_collect()
            return str(value.value) + suffix if value is not None else "none" + suffix

        def sink(value: None, seen: list[str]) -> None:
            gc_collect()
            seen.append(str(value))

        def half(value: float32, divisor: float32) -> float32:
            return value / divisor

        def main() -> str:
            gc_set_threshold(1)
            prefix = "first"
            callback: Callable[[int], str] = lambda value: prefix + str(value)
            frozen = bind(combine, callback, suffix="!")
            callback = object_text
            prefix = "later"
            converted = fn.partial(combine, object_text, 42)
            one = bind(nullable, Box(7))
            absent = bind(nullable, None)
            seen: list[str] = []
            record = bind(sink, None)
            numeric = bind(half, float32(3.0))
            gc_collect()
            result = [frozen(1), converted("?"), one("!"), absent("!"),
                      str(record(seen)), str(numeric(float32(2.0))), str(seen)]
            holes = fn.partial(combine, fn.Placeholder, 9, "#")
            result.append(holes(object_text))
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("binding, diagnostic", [
    ("partial()", "requires a typed callable"),
    ("partial(3)", "requires a concrete callable signature"),
    ("partial(add, 1, 2, 3)", "binds more arguments"),
    ("partial(add, 'bad')", "expects int, got"),
    ("partial(add, Placeholder)", "does not allow a trailing Placeholder"),
    ("partial(add, 1, left=2)", "already bound positionally"),
    ("partial(add, missing=2)", "has no positional parameter"),
    ("partial(add, left=2)", "must cover a trailing parameter suffix"),
    ("partial(add, *[1])", "requires explicit argument bindings"),
    ("partial(add, **{'right': 2})", "requires explicit argument bindings"),
])
def test_partial_binding_diagnostics(binding, diagnostic):
    with pytest.raises(CompilationError, match=diagnostic):
        transpile_llvm(f'''
            from functools import Placeholder, partial
            def add(left: int, right: int) -> int:
                return left + right
            def main() -> int:
                callback = {binding}
                return 0
        ''')


@pytest.mark.parametrize("source", ["add", "partial(add)"])
def test_partial_rejects_keyword_binding_of_positional_only_parameter(source):
    with pytest.raises(CompilationError, match="cannot bind positional-only"):
        transpile_llvm(f'''
            from functools import partial
            def add(left: int, /, right: int) -> int:
                return left + right
            def main() -> int:
                callback = partial({source}, left=1, right=2)
                return callback()
        ''')


@pytest.mark.parametrize("union", ["Left | Right", "Right | Left"])
@pytest.mark.parametrize("parameter", ["other: int = 2", "right: str = 'x'"])
def test_partial_union_keywords_require_common_names_and_positions(union, parameter):
    with pytest.raises(CompilationError, match="has no positional parameter 'right'"):
        transpile_llvm(f'''
            from functools import partial
            class Left:
                def read(self, left: int, right: int = 1) -> int:
                    return left
            class Right:
                def read(self, left: int, {parameter}) -> int:
                    return left
            def use(receiver: {union}) -> int:
                callback = partial(receiver.read, right=2)
                return callback(1)
            def main() -> int:
                return use(Right())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_only_lowers_reached_default_arities(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from functools import partial
        def add(left: int, right: int = -1) -> int:
            return left + right
        def main() -> str:
            # Unary defaults are intentionally unsupported by native binding.
            # Neither this unused arity nor a nested partial should lower it.
            callback = partial(add, 4)
            nested = partial(partial(add), 5)
            return str([callback(2), nested(3)])
    ''', directory=tmp_path, optimize=optimize)
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_generator_captures_and_failed_consumer_arguments(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable, Iterator
        from functools import partial
        from pyjs.native import gc_collect, gc_set_threshold

        def add(left: int, right: int) -> int:
            gc_collect()
            return left + right

        def callbacks() -> Iterator[Callable[[int], int]]:
            for value in range(3):
                yield partial(add, value)

        def total(values: Iterable[int], extra: int) -> int:
            gc_collect()
            return sum(values) + extra

        def prefix(left: str, right: str) -> str:
            return left + right

        def fail(seen: list[str]) -> str:
            seen.append("failed")
            gc_collect()
            raise ValueError("argument failed")

        def main() -> str:
            gc_set_threshold(1)
            saved = list(callbacks())
            gc_collect()
            result = [callback(10) for callback in saved]
            frozen = [partial(add, value) for value in range(3)]
            result.extend(callback(20) for callback in frozen)
            summed = partial(total, [1, 2, 3])
            gc_collect()
            result.append(summed(4))
            values = {"original"}
            alias = values
            seen: list[str] = []
            try:
                values.symmetric_difference_update(map(partial(prefix, fail(seen)), ["tail"]))
            except ValueError:
                seen.append("caught")
            gc_collect()
            assert values is alias and sorted(values) == ["original"]
            values.update(map(partial(prefix, "re"), ["try"]))
            return repr((result, sorted(values), seen))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_partial_trace_contains_only_authored_frames(tmp_path):
    result = LLVM().run_source('''
        from functools import partial
        def fail(left: int, right: int = 1) -> int:
            raise ValueError("partial failed")
        def main() -> str:
            callback = partial(partial(fail), 2)
            return str(callback())
    ''', filename="partial_trace.py", directory=tmp_path)
    assert result.returncode < 0
    assert result.stderr == (
        "Traceback (native PyJS):\n"
        '  File "partial_trace.py", line 7, in main\n'
        '  File "partial_trace.py", line 4, in fail\n'
        "ValueError: partial failed\n"
    )


@pytest.mark.parametrize("annotation", ["object", "int", "int | None"])
@pytest.mark.parametrize("alias", [False, True])
def test_keyword_placeholder_is_rejected_at_its_argument(annotation, alias):
    marker = "marker" if alias else "Placeholder"
    source = f'''from functools import Placeholder, partial
def show(a: int, b: {annotation}) -> str:
    return str(a) + str(b)
def main() -> str:
    marker = Placeholder
    callback = partial(show, b={marker})
    return callback(1)
'''
    with pytest.raises(CompilationError, match="Placeholder cannot be passed as a keyword argument") as caught:
        transpile_llvm(source, filename="placeholder_keyword.py")
    assert caught.value.filename == "placeholder_keyword.py"
    assert caught.value.lineno == 6


@pytest.mark.parametrize("annotation", ["object", "int"])
def test_local_placeholder_alias_has_a_focused_boundary(annotation):
    with pytest.raises(CompilationError, match="function-local Placeholder aliases are unsupported") as caught:
        transpile_llvm(f'''from functools import Placeholder, partial
def show(a: {annotation}, b: int) -> str:
    return str(a) + str(b)
def main() -> str:
    marker = Placeholder
    callback = partial(show, marker, 2)
    return callback(1)
''', filename="placeholder_alias.py")
    assert caught.value.filename == "placeholder_alias.py"
    assert caught.value.lineno == 6


@pytest.mark.parametrize("optimize", [0, 2])
def test_imported_and_module_level_placeholder_aliases_remain_holes(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from functools import Placeholder as Hole, partial
        marker = Hole
        def add(left: int, right: int) -> int:
            return left + right
        def main() -> str:
            direct = partial(add, Hole, 2)
            aliased = partial(add, marker, 3)
            return str([direct(4), aliased(5)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""

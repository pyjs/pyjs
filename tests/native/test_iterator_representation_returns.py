import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.semantics.helpers import run_python


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("items_source", ["[child(), child()]", "(child(), child())", "borrowed", "iterate()"],
                         ids=["list", "tuple", "list-variable", "iterator-function"])
@pytest.mark.parametrize("boundary", ["argument", "local", "return"])
@pytest.mark.parametrize("checked_cast", [False, True], ids=["valid-cast", "invalid-cast"])
def test_iterable_generator_items_keep_source_yield_and_destination_send_layouts(
    tmp_path, optimize, items_source, boundary, checked_cast,
):
    setup = "borrowed = [child(), child()]" if items_source == "borrowed" else "pass"
    entry = {
        "argument": f"return consume({items_source})",
        "local": f"items: Iterable[G] = {items_source}; return consume(items)",
        "return": "return consume(make())",
    }[boundary]
    source = f'''
        from collections.abc import Generator, Iterable, Iterator
        from typing import cast
        from pyjs import int8, int16
        from pyjs.native import gc_collect, gc_set_threshold
        G = Generator[object, list[int16], object]
        S = Generator[list[int8], object, list[int8]]
        def child() -> Generator[list[int8], object, list[int8]]:
            payload = [int8(127)]
            received = yield payload
            gc_collect()
            assert cast(list[int16], received)[0] + 1 == -32768
            try:
                yield payload
            finally:
                return payload
        def iterate() -> Iterator[S]:
            yield child()
            yield child()
        def consume(items: Iterable[G]) -> str:
            for value in items:
                first = next(value)
                if {checked_cast!r}:
                    try:
                        cast(list[int], first)
                    except TypeError:
                        pass
                    else:
                        return 'invalid yield cast accepted'
                payload = cast(list[int8], first)
                assert payload[0] + 1 == -128
                sent = [int16(32767)]
                assert value.send(sent) is first
                assert sent[0] + 1 == -32768
                assert value.close() is first
                gc_collect()
                assert payload[0] + 1 == -128
            return 'independent channel layouts'
        def make() -> Iterable[G]:
            {setup}
            return {items_source}
        def main() -> str:
            gc_set_threshold(1)
            {setup if boundary != 'return' else 'pass'}
            {entry}
    '''
    options = dict(directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # CPython casts are unchecked. The negative branch tests native storage
    # safety, while the positive branch compares complete Python/native runs.
    result = (LLVM().run_source(source, **options) if checked_cast
              else LLVM().assert_matches_python(source, **options).native)
    assert result.returncode == 0
    assert result.stdout == 'independent channel layouts'
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal", ["[child(), child()]", "(child(), child())"], ids=["list", "tuple"])
@pytest.mark.parametrize("boundary", ["argument", "local", "return"])
def test_iterable_literals_keep_generator_item_channel_witnesses(tmp_path, optimize, literal, boundary):
    entry = {
        "argument": f"return total({literal})",
        "local": f"items: Iterable[G] = {literal}; return total(items)",
        "return": "return total(make())",
    }[boundary]
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Generator, Iterable
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        G = Generator[int8, list[int8], object]
        def child() -> Generator[int8, object, object]:
            received = yield int8(127)
            gc_collect()
            items = cast(list[int8], received)
            yield items[0] + 1
        def total(items: Iterable[G]) -> str:
            output: list[str] = []
            for source in items:
                payload = [int8(127)]
                output.append(str((next(source), source.send(payload))))
                source.close()
                assert payload[0] + 1 == -128
            return ','.join(output)
        def make() -> Iterable[G]:
            return {literal}
        def main() -> str:
            gc_set_threshold(1)
            {entry}
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal", ["[child(), child()]", "(child(), child())"], ids=["list", "tuple"])
def test_iterable_literal_views_reject_invalid_send_relabeling(tmp_path, optimize, literal):
    # CPython typing.cast is unchecked; this is the native storage guarantee.
    result = LLVM().run_source(f'''
        from collections.abc import Generator, Iterable
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def child() -> Generator[int8, object, object]:
            received = yield int8(127)
            gc_collect()
            try:
                cast(list[int], received)
            except TypeError:
                yield cast(list[int8], received)[0] + 1
            else:
                yield int8(1)
        def total(items: Iterable[Generator[int8, list[int8], object]]) -> str:
            for source in items:
                assert next(source) + 1 == -128
                payload = [int8(127)]
                assert source.send(payload) == -128
                assert payload[0] + 1 == -128
                source.close()
            return 'checked iterable layout'
        def main() -> str:
            gc_set_threshold(1)
            return total({literal})
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stdout == 'checked iterable layout'
    assert not result.stderr


@pytest.mark.parametrize("source, target", [
    ("int8, int8, None", "object, int8, None"),
    ("list[int8], int8, None", "object, int, None"),
    ("list[int8], list[int8], int8", "object, list[int8], object"),
    ("list[int8], object, None", "object, int8, None"),
    ("list[int8], list[int8], None", "object, list[int16], None"),
    ("int8, list[int8], None", "int16, list[int8], None"),
    ("list[int8], None, int8", "object, None, int16"),
])
def test_generator_reference_view_does_not_erase_another_scalar_channel(source, target):
    with pytest.raises(CompilationError, match="representation|represented arithmetic"):
        with analyze_source(f'''
            from collections.abc import Generator
            from pyjs import int8, int16
            def view(value: Generator[{source}]) -> Generator[{target}]:
                return value
        ''', entry_point="view", wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("boundary", [
    "source = view(original)",
    "source: Generator[int8, list[int8], object] = original",
    "source = Holder(original).value",
    "source = argument(original)",
    "items: list[Generator[int8, list[int8], object]] = [original]; source = items[0]",
    "items: tuple[Generator[int8, list[int8], object]] = (original,); source = items[0]",
    "items: dict[str, Generator[int8, list[int8], object]] = {'g': original}; source = items['g']",
    "items: list[Generator[int8, list[int8], object]] = []; items.append(original); source = items[0]",
    "items: list[Generator[int8, list[int8], object]] = []; items.insert(0, original); source = items[0]",
    "items: list[Generator[int8, list[int8], object]] = [view(child())]; items[0] = original; source = items[0]",
    "items: dict[str, Generator[int8, list[int8], object]] = {}; items['g'] = original; source = items['g']",
    "items: dict[str, Generator[int8, list[int8], object]] = {}; source = items.setdefault('g', original)",
    "source = argument(*(original,))",
    "source = argument(**{'source': original})",
    "items: dict[str, Generator[int8, list[int8], object]] = dict.fromkeys(['g'], original); source = items['g']",
    "items: tuple[Generator[int8, list[int8], object], ...] = (original, original); source = items[1]",
    "source = next(outer(original))",
    "carrier = echo(view(original)); next(carrier); source = carrier.send(original)",
    "source = invoke(argument, original)",
    "source = varargs(original)",
    "source = kwargs(source=original)",
    "source = partial(argument, original)()",
], ids=["return", "local", "field", "argument", "list", "tuple", "dict", "append", "insert", "list-set", "dict-set", "setdefault", "star", "kwstar", "fromkeys", "variadic", "yield", "send", "callable", "varargs", "kwargs", "partial"])
def test_generator_view_adapts_send_and_completion_without_erasing_yield_width(tmp_path, optimize, boundary):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Callable, Generator
        from functools import partial
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def child() -> Generator[int8, object, list[int8]]:
            received = yield int8(127)
            gc_collect()
            try:
                yield int8(126)
            finally:
                return cast(list[int8], received)
        def view(source: Generator[int8, object, list[int8]]) -> Generator[int8, list[int8], object]:
            return source
        def argument(source: Generator[int8, list[int8], object]) -> Generator[int8, list[int8], object]:
            return source
        def invoke(callback: Callable[[Generator[int8, list[int8], object]], Generator[int8, list[int8], object]], source: Generator[int8, object, list[int8]]) -> Generator[int8, list[int8], object]:
            return callback(source)
        def varargs(*sources: Generator[int8, list[int8], object]) -> Generator[int8, list[int8], object]:
            return sources[0]
        def kwargs(**sources: Generator[int8, list[int8], object]) -> Generator[int8, list[int8], object]:
            return sources['source']
        def outer(source: Generator[int8, object, list[int8]]) -> Generator[Generator[int8, list[int8], object], None, None]:
            yield source
        def echo(source: Generator[int8, list[int8], object]) -> Generator[Generator[int8, list[int8], object], Generator[int8, list[int8], object], None]:
            received = yield source
            assert received is not None
            yield received
        class Holder:
            def __init__(self, source: Generator[int8, object, list[int8]]):
                self.value: Generator[int8, list[int8], object] = source
        def main() -> str:
            gc_set_threshold(1)
            original = child()
            {boundary}
            assert source is original
            assert next(source) + 1 == -128
            payload = [int8(127)]
            assert source.send(payload) + 2 == -128
            returned = source.close()
            gc_collect()
            assert returned is payload
            payload.append(int8(130))
            assert payload[0] + 1 == -128
            assert source.close() is None
            assert next(original, None) is None
            return repr(returned)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("boundary", ["source = next(outer(original))", "carrier = echo(view(original)); next(carrier); source = carrier.send(original)"],
                         ids=["yield", "send"])
def test_suspended_generator_views_cannot_relabel_reference_payloads(tmp_path, optimize, boundary):
    # Native casts check storage; CPython's typing.cast is deliberately unchecked.
    result = LLVM().run_source(f'''
        from collections.abc import Generator
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def child() -> Generator[int8, object, None]:
            received = yield int8(127)
            gc_collect()
            try:
                cast(list[int], received)
            except TypeError:
                yield int8(2)
            else:
                yield int8(1)
        def view(source: Generator[int8, object, None]) -> Generator[int8, list[int8], None]:
            return source
        def outer(source: Generator[int8, object, None]) -> Generator[Generator[int8, list[int8], None], None, None]:
            yield source
        def echo(source: Generator[int8, list[int8], None]) -> Generator[Generator[int8, list[int8], None], Generator[int8, list[int8], None], None]:
            received = yield source
            assert received is not None
            yield received
        def main() -> str:
            gc_set_threshold(1)
            original = child()
            {boundary}
            assert source is original
            assert next(source) + 1 == -128
            payload = [int8(127)]
            assert source.send(payload) == 2
            assert payload[0] + 1 == -128
            source.close()
            return 'checked layout'
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stdout == 'checked layout'
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_view_cache_and_literal_roots_keep_distinct_send_widths(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterable
        from typing import cast
        from pyjs import int8, int16
        from pyjs.native import gc_collect, gc_set_threshold
        def child(narrow: bool) -> Generator[int8, object, object]:
            received = yield int8(127)
            gc_collect()
            if narrow:
                assert cast(list[int8], received)[0] + 1 == -128
            else:
                assert cast(list[int16], received)[0] + 1 == -32768
            try:
                yield int8(126)
            finally:
                return received
        def make(narrow: bool) -> Generator[int8, object, object]:
            gc_collect()
            return child(narrow)
        def narrow(items: Iterable[Generator[int8, list[int8], object]]) -> None:
            for source in items:
                payload = [int8(127)]
                next(source)
                source.send(payload)
                assert source.close() is payload
        def wide(items: Iterable[Generator[int8, list[int16], object]]) -> None:
            for source in items:
                payload = [int16(32767)]
                next(source)
                source.send(payload)
                assert source.close() is payload
        def main() -> str:
            gc_set_threshold(1)
            pair: tuple[Generator[int8, list[int8], object], Generator[int8, list[int16], object]] = (
                make(True), make(False))
            first, second = pair
            gc_collect()
            assert next(first) + 1 == next(second) + 1 == -128
            small, large = [int8(127)], [int16(32767)]
            assert first.send(small) + 2 == -128
            assert second.send(large) + 2 == -128
            assert first.close() is small
            assert second.close() is large
            assert first.close() is second.close() is None
            # Identical nominal source/target types, distinct destination
            # witnesses: neither Iterable nor cursor adapter may share a cache
            # entry across these widths. Reacquisition must keep the witness.
            smalls: Iterable[Generator[int8, list[int8], object]] = [make(True)]
            larges: Iterable[Generator[int8, list[int16], object]] = [make(False)]
            narrow(smalls)
            wide(larges)
            narrow((make(True), make(True)))
            wide((make(False), make(False)))
            return 'distinct send layouts'
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("target", ["Iterator[object]", "Iterable[object]", "Generator[object, None, None]"])
@pytest.mark.parametrize("extra", ["", " | None", " | str"])
def test_returned_iterator_view_does_not_silently_erase_portable_yields(target, extra):
    target += extra
    with pytest.raises(CompilationError, match="iterator views cannot erase represented arithmetic") as caught:
        transpile_llvm(f'''from collections.abc import Generator, Iterator, Iterable
from pyjs import int8
def produce() -> Generator[int8, None, None]:
    yield int8(127)
def widen(value: Generator[int8, None, None]) -> {target}:
    return value
def main() -> str:
    return str(widen(produce()))
''')
    assert caught.value.lineno == 6


@pytest.mark.parametrize("item", ["int", "object"])
@pytest.mark.parametrize("target, expression", [
    ("tuple[Iterator[ITEM]]", "(value,)"),
    ("list[Iterator[ITEM]]", "[value]"),
    ("dict[str, Iterator[ITEM]]", "{'cursor': value}"),
    ("tuple[list[Iterator[ITEM]]] | None", "([value],)"),
    ("tuple[Iterator[ITEM], ...]", "(value, value)"),
    ("list[tuple[Iterator[ITEM], ...]]", "[(value, value)]"),
])
def test_nested_return_views_cannot_erase_portable_arithmetic(item, target, expression):
    with pytest.raises(CompilationError, match="iterator views cannot erase represented arithmetic") as caught:
        transpile_llvm(f'''from collections.abc import Generator, Iterator
from pyjs import int8
def produce() -> Generator[int8, None, None]:
    yield int8(127)
def widen(value: Generator[int8, None, None]) -> {target.replace("ITEM", item)}:
    return {expression}
def main() -> str:
    widen(produce())
    return "done"
''')
    assert caught.value.lineno == 6


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("target, expression, access", [
    ("tuple[Iterator[int], ...]", "(value, value)", "pair[0]"),
    ("list[tuple[Iterator[int], ...]]", "[(value, value)]", "pair[0][0]"),
])
def test_variadic_return_views_keep_hidden_generator_domains(tmp_path, optimize, target, expression, access):
    result = LLVM().assert_matches_python(f'''
from collections.abc import Generator, Iterator
from pyjs import int8
from pyjs.native import gc_collect
def produce() -> Generator[int, None, int8]:
    yield 127
    return int8(3)
def wrap(value: Generator[int, None, int8]) -> {target}:
    return {expression}
def main() -> str:
    source = produce()
    pair = wrap(source)
    gc_collect()
    result = next({access}) + 1
    source.close()
    return str(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_return_views_preserve_hidden_domains_and_opaque_references(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator, Iterator
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect
def produce() -> Generator[int8, None, None]:
    yield int8(127)
def hidden() -> Generator[int, int8, int8]:
    value = yield 1
    yield int(value)
    return int8(9)
def opaque(value: list[int8]) -> tuple[object]:
    return (value,)
def view(value: Generator[int, int8, int8]) -> tuple[Iterator[int]]:
    return (value,)
def ordinary(value: Generator[int8, None, None]) -> Iterator[int]:
    for item in value:
        yield int(item)
def nested(value: Iterator[int]) -> tuple[list[Iterator[int]]]:
    return ([value],)
def main() -> str:
    raw = [int8(127)]
    boxed = opaque(raw)
    source = hidden()
    cursor = view(source)[0]
    converted = nested(ordinary(produce()))
    gc_collect()
    assert boxed[0] is raw
    fixed = cast(list[int8], boxed[0])[0]
    first = next(cursor)
    second = source.send(int8(130))
    return str((fixed + 1, first, second, next(converted[0][0]) + 1))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegated_completion_keeps_typed_scalars_and_erased_reference_layout(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator, Iterator
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect
def scalar() -> Generator[int, None, int8]:
    yield 1
    return int8(127)
def reference() -> Generator[int, None, list[int8]]:
    yield 2
    return [int8(127)]
def erase(value: Generator[int, None, list[int8]]) -> Iterator[int]:
    return value
def typed(source: Generator[int, None, int8]) -> Generator[int, None, None]:
    result = yield from source
    if result is not None:
        yield int(result + 1)
def opaque(source: Iterator[int]) -> Generator[int, None, None]:
    result = yield from source
    gc_collect()
    items = cast(list[int8], result)
    yield int(items[0] + 1)
def main() -> str:
    return str((list(typed(scalar())), list(opaque(erase(reference())))))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("declared", ["Iterator[int]", "Generator[int, None, SCALAR]"])
@pytest.mark.parametrize("scalar", ["int8", "float32"])
def test_erased_capture_checks_hidden_frame_completion_and_recovers(tmp_path, optimize, declared, scalar):
    # Python annotations do not guard erased scalar domains. The explicit
    # oracle raises only at that boundary, preserving all cleanup/retry events.
    source = '''
from collections.abc import Generator, Iterator
from pyjs import int8, float32
from pyjs.native import gc_collect, gc_set_threshold
def child(events: list[str]) -> DECLARED:
    try:
        yield 1
        return SCALAR(127)
    finally:
        events.append("child")
def erased(events: list[str]) -> Iterator[int]:
    return child(events)
def capture(cursor: Iterator[int], events: list[str]):
    try:
        result = yield from cursor
        events.append(str(result))
    finally:
        gc_collect()
        events.append("parent")
def discard(cursor: Iterator[int]):
    yield from cursor
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    cursor = erased(events)
    parent = capture(cursor, events)
    assert next(parent) == 1
    try:
        next(parent)
    except TypeError as error:
        events.append(str(error))
    gc_collect()
    assert list(capture(cursor, events)) == []
    assert list(discard(erased(events))) == [1]
    closing = discard(erased(events))
    assert next(closing) == 1
    closing.close()
    assert list(capture(iter([2]), events)) == [2]
    return str(events)
'''.replace("DECLARED", declared).replace("SCALAR", scalar)
    message = "erased delegation cannot expose represented scalar completion; use a concrete Generator"
    oracle = source.replace("        events.append(str(result))", f'''
        if result is not None:
            raise TypeError({message!r})
        events.append(str(result))''')
    expected = run_python(oracle + "\nprint(main(), end='')\n")
    actual = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert expected.returncode == actual.returncode == 0
    assert actual.stdout == expected.stdout
    assert not actual.stderr and not expected.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("declared", ["Iterator[int]", "Generator[int, None, DOMAIN]"])
@pytest.mark.parametrize("scalar, ordinary", [("int8", "float"), ("float32", "int")])
def test_completion_provenance_survives_wrappers_and_selects_actual_union_arm(
    tmp_path, optimize, declared, scalar, ordinary,
):
    source = '''
from collections.abc import Generator, Iterator
from typing import cast
from pyjs import int8, float32
from pyjs.native import gc_collect, gc_set_threshold
def child(mode: int, events: list[str]) -> DECLARED:
    result: DOMAIN = None
    if mode == 0:
        result = SCALAR(127)
    elif mode == 1:
        result = "safe"
    elif mode == 2:
        result = [int8(127)]
    elif mode == 4:
        result = ORDINARY(4)
    try:
        yield 1
        return result
    finally:
        events.append("child")
def identity(value: int) -> int:
    return value
def predicate(value: int) -> bool:
    return True
def wrap(kind: int, mode: int, events: list[str]) -> Iterator[int]:
    source = child(mode, events)
    if kind == 0:
        return source
    if kind == 1:
        return map(identity, source)
    if kind == 2:
        return filter(predicate, source)
    return map(identity, filter(predicate, source))
def capture(cursor: Iterator[int], events: list[str], mode: int) -> Iterator[int]:
    try:
        result = yield from cursor
        gc_collect()
        if mode == 2 and result is not None:
            events.append(str(cast(list[int8], result)[0] + 1))
        else:
            events.append(str(result))
    finally:
        events.append("parent")
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    for kind in range(4):
        for mode in range(5):
            cursor = wrap(kind, mode, events)
            try:
                events.append(str(list(capture(cursor, events, mode))))
            except TypeError as error:
                events.append(str(error))
            # Repeated exhaustion and fresh ordinary exceptions must not
            # inherit a previous completion's provenance bit.
            events.append(str(list(capture(cursor, events, mode))))
            gc_collect()
    return str(events)
'''.replace("DECLARED", declared).replace("DOMAIN", "SCALAR | str | list[int8] | None | ORDINARY")
    source = source.replace("SCALAR", scalar).replace("ORDINARY", ordinary)
    message = "erased delegation cannot expose represented scalar completion; use a concrete Generator"
    oracle = source.replace("        gc_collect()", f'''
        if isinstance(result, {scalar}):
            raise TypeError({message!r})
        gc_collect()''', 1)
    expected = run_python(oracle + "\nprint(main(), end='')\n")
    actual = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert expected.returncode == actual.returncode == 0
    assert actual.stdout == expected.stdout
    assert not actual.stderr and not expected.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_return_view_validation_keeps_static_array_representation_shapes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import StaticArray, int8
from pyjs.native import gc_collect
def direct(value: StaticArray[int8, 2]) -> StaticArray[int8, 2]:
    return value
def nested(value: tuple[StaticArray[int8, 2]]) -> tuple[StaticArray[int8, 2]]:
    return value
def ordinary(value: StaticArray[int, 2]) -> StaticArray[int, 2]:
    return value
def main() -> str:
    fixed = StaticArray[int8, 2]([127, 2])
    first = direct(fixed)
    second = nested((fixed,))[0]
    plain = ordinary(StaticArray[int, 2]([127, 2]))
    gc_collect()
    assert first is fixed and second is fixed
    first[1] = int8(5)
    return str((second[0] + 1, second[1], plain[0] + 1))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("slot", ["send", "completion"])
def test_generator_return_view_does_not_drop_send_or_completion_representation(slot):
    source = "Generator[int, int8, None]" if slot == "send" else "Generator[int, None, int8]"
    target = "Generator[int, int, None]" if slot == "send" else "Generator[int, None, object]"
    body = "value = yield 1\n    yield int(value)" if slot == "send" else "yield 1\n    return int8(127)"
    with pytest.raises(CompilationError, match="iterator views cannot erase represented arithmetic"):
        transpile_llvm(f'''
from collections.abc import Generator
from pyjs import int8
def produce() -> {source}:
    {body}
def view(value: {source}) -> {target}:
    return value
def main() -> str:
    return str(view(produce()))
''')


@pytest.mark.parametrize("target", ["Iterator[object]", "Iterable[object]", "Generator[object, None, None]"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_reference_items_keep_their_portable_contents(tmp_path, optimize, target):
    result = LLVM().assert_matches_python(f'''
from collections.abc import Generator, Iterator, Iterable
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect
def produce() -> Generator[list[int8], None, None]:
    yield [int8(127)]
def view(value: Generator[list[int8], None, None]) -> {target}:
    return value
def main() -> str:
    results: list[str] = []
    for value in view(produce()):
        gc_collect()
        values = cast(list[int8], value)
        results.append(str(values[0] + 1))
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("target", ["Iterator", "Iterable"])
@pytest.mark.parametrize("collection, expression", [
    ("list[list[int8]]", "[[int8(127)]]"),
    ("tuple[list[int8]]", "([int8(127)],)"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_container_views_keep_nested_item_layout_and_aliases(tmp_path, optimize, target, collection, expression):
    result = LLVM().assert_matches_python(f'''
from collections.abc import Iterator, Iterable
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect
def view(values: {collection}) -> {target}[object]:
    return {"iter(values)" if target == "Iterator" else "values"}
def main() -> str:
    values = {expression}
    result = next(iter(view(values)))
    gc_collect()
    items = cast(list[int8], result)
    items.append(int8(126))
    return str((items[0] + 1, values[0][1]))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("target", ["Iterator[object]", "Iterable[object]"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_view_factories_distinguish_same_semantic_type_with_different_item_layouts(tmp_path, optimize, target):
    result = LLVM().assert_matches_python(f'''
from collections.abc import Generator, Iterator, Iterable
from typing import cast
from pyjs import int8, int16
from pyjs.native import gc_collect
def small() -> Generator[list[int8], None, None]:
    yield [int8(127)]
def large() -> Generator[list[int16], None, None]:
    yield [int16(32767)]
def small_view(value: Generator[list[int8], None, None] | None) -> {target} | None:
    return value
def large_view(value: Generator[list[int16], None, None]) -> {target}:
    return value
def main() -> str:
    assert small_view(None) is None
    first = small_view(small())
    second = large_view(large())
    assert first is not None
    left = next(iter(first))
    right = next(iter(second))
    gc_collect()
    return str((cast(list[int8], left)[0] + 1, cast(list[int16], right)[0] + 1))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_reference_completion_keeps_its_numeric_container_layout(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect
def produce() -> Generator[int, None, list[int8]]:
    yield 1
    return [int8(127)]
def view(value: Generator[int, None, list[int8]]) -> Generator[int, None, object]:
    return value
def main() -> str:
    value = view(produce())
    next(value)
    try:
        next(value)
    except StopIteration as error:
        gc_collect()
        return str(cast(list[int8], error.value)[0] + 1)
    return "missing"
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_yield_conversion_and_retained_portable_views(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator, Iterator, Iterable
from pyjs import int8
def produce() -> Generator[int8, None, None]:
    yield int8(127)
def preserve(values: Generator[int8, None, None]) -> Iterator[int8]:
    return values
def ordinary(values: Generator[int8, None, None]) -> Iterator[int]:
    for value in values:
        yield int(value)
def widen(values: Iterator[int]) -> Iterable[object]:
    return values
def main() -> str:
    fixed = next(preserve(produce()))
    results = [str(fixed + 1)]
    for value in widen(ordinary(produce())):
        if isinstance(value, int):
            results.append(str(value + 1))
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_view_does_not_erase_hidden_generator_send_or_result_domains(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator, Iterator
from pyjs import int8
def produce() -> Generator[int, int8, int8]:
    value = yield 1
    yield int(value)
    return int8(9)
def view(values: Generator[int, int8, int8]) -> Iterator[int]:
    return values
def main() -> str:
    raw = produce()
    cursor = view(raw)
    first = next(cursor)
    second = raw.send(int8(130))
    result = raw.close()
    return str((first, second, result))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr

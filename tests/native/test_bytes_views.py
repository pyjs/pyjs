import pytest

from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMEmitter, LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_views_preserve_application_conversion_without_consuming_cursor(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self, events: list[str]):
                self.events = events
                self.position = 64
            def __iter__(self) -> 'Cursor':
                self.events.append('iter')
                return self
            def __next__(self) -> int:
                gc_collect()
                self.position += 1
                if self.position > 67:
                    raise StopIteration()
                return self.position
        class Binary(Cursor):
            def __bytes__(self) -> bytes:
                gc_collect()
                self.events.append('bytes')
                return b'custom'
        class Count(Cursor):
            def __index__(self) -> int:
                gc_collect()
                self.events.append('index')
                return 3
        class Broken(Binary):
            def __bytes__(self) -> bytes:
                gc_collect()
                self.events.append('broken')
                raise ValueError('conversion failed')
        def via_iterator(value: Iterator[int]) -> bytes:
            return bytes(value)
        def via_iterable(value: Iterable[int]) -> bytes:
            return bytes(value)
        def widened(value: Iterator[int]) -> bytes:
            return via_iterable(value)
        def check(value: Cursor) -> str:
            rows: list[str] = []
            for mode in range(3):
                try:
                    if mode == 0:
                        result = via_iterator(value)
                    elif mode == 1:
                        result = via_iterable(value)
                    else:
                        result = widened(value)
                    rows.append(result.hex())
                except ValueError as error:
                    rows.append(str(error))
                rows.append(str(value.position))
            return '|'.join(rows)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            empty: list[int] = []
            rows = [check(Binary(events)), check(Count(events)), check(Broken(events)),
                    check(Cursor(events)), via_iterator(iter([1, 2])).hex(),
                    via_iterable([3, 4]).hex(), via_iterable((5, 6)).hex(),
                    via_iterable(range(7, 9)).hex(), via_iterable(b'ab').hex(),
                    via_iterable(empty).hex(), via_iterable(()).hex()]
            gc_collect()
            return repr((rows, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_views_preserve_independent_class_protocols_after_cursor_exhaustion(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class First:
            def __iter__(self) -> 'First':
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def __bytes__(self) -> bytes:
                gc_collect()
                return b'first'
        class Second:
            def __iter__(self) -> 'Second':
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def __index__(self) -> int:
                gc_collect()
                return 2
        def convert(value: Iterator[int]) -> str:
            next(value, 0)
            gc_collect()
            return bytes(value).hex()
        def main() -> str:
            gc_set_threshold(1)
            return convert(First()) + ':' + convert(Second()) + ':' + convert(iter([65]))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_view_dependencies_exclude_unconverted_classes_and_other_item_domains(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        class Source:
            def __iter__(self) -> Iterator[int]:
                return iter([65])
            def __bytes__(self) -> bytes:
                return b'converted'
            def unrelated(self) -> bytes:
                return unknown_source_body
        class Unconverted:
            def __iter__(self) -> Iterator[int]:
                return unknown_iterator_body
            def __bytes__(self) -> bytes:
                return unknown_conversion_body
        class Text:
            def __iter__(self) -> Iterator[str]:
                return iter(['text'])
            def __bytes__(self) -> bytes:
                return unknown_text_conversion
        def binary(value: Iterable[int]) -> bytes:
            return bytes(value)
        def text(value: Iterable[str]) -> str:
            return repr(list(value))
        def main() -> str:
            unused = Unconverted()
            return binary(Source()).hex() + text(Text())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_reusable_views_keep_identity_live_updates_and_conversion_failure_recovery(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs.native import gc_collect, gc_set_threshold
        class Source:
            def __init__(self):
                self.fail = True
            def __iter__(self):
                yield 65
            def __bytes__(self) -> bytes:
                gc_collect()
                if self.fail:
                    raise ValueError('not yet')
                return b'recovered'
        def expose(value: Source) -> Iterable[int]:
            return value
        def build(value: Iterable[int]) -> bytes:
            return bytes(value)
        def live(value: Iterable[int]) -> str:
            return build(value).hex()
        def main() -> str:
            gc_set_threshold(1)
            source = Source()
            view = expose(source)
            result = b'unchanged'
            try:
                result = build(view)
            except ValueError:
                pass
            before = result.hex()
            source.fail = False
            assert view is source
            value = b'original'
            assert build(value) is value
            rows = [1, 2]
            first = live(rows)
            rows.append(3)
            gc_collect()
            return before + ':' + build(view).hex() + ':' + first + ':' + live(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_view_conversion_allocation_failure_preserves_source_and_retries(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining
        class Source:
            def __iter__(self) -> 'Source':
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def __bytes__(self) -> bytes:
                gc_collect()
                return bytes(range(128))
        def as_iterable(source: Iterable[int]) -> bytes:
            return bytes(source)
        def as_iterator(source: Iterator[int]) -> bytes:
            return bytes(source)
        def build(source: Source, mode: int) -> bytes:
            if mode == 0:
                return as_iterable(source)
            return as_iterator(source)
        def main() -> int:
            source = Source()
            alias = source
            sentinel = b'unchanged'
            for mode in range(2):
                expected = build(source, mode)
                arm(1000)
                result = build(source, mode)
                stages = 1000 - remaining()
                arm(0)
                if stages < 1 or result != expected:
                    return 1
                for failure in range(1, stages + 1):
                    result = sentinel
                    caught = False
                    arm(failure)
                    try:
                        result = build(source, mode)
                    except MemoryError:
                        caught = True
                    arm(0)
                    gc_collect()
                    if not caught or result is not sentinel or source is not alias:
                        return 2
                    if build(source, mode) != expected:
                        return 3
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("interface", ["Iterable", "Iterator"])
@pytest.mark.parametrize("declaration", [
    "@property\n    def __bytes__(self) -> bytes:\n        return b'not callable'",
    "def __bytes__(self) -> str:\n        return 'not bytes'",
])
def test_bytes_views_keep_focused_protocol_boundary_diagnostics(interface, declaration):
    with pytest.raises(LLVMUnsupported, match="LLVM __bytes__ requires an instance method returning bytes"):
        transpile_llvm(f'''
from collections.abc import Iterable, Iterator
class Source:
    def __iter__(self) -> 'Source':
        return self
    def __next__(self) -> int:
        return 1
    {declaration}
def build(value: {interface}[int]) -> bytes:
    return bytes(value)
def main() -> bytes:
    return build(Source())
''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("direct_arm", [False, True], ids=["acquired-only", "mixed-layouts"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_bytes_acquired_cursors_preserve_protocols_and_never_use_another_class_layout(optimize, direct_arm, sanitized):
    # Binary's list pointer and Acquired's integer occupy the same field slot.
    # An incomplete one-class dispatch set previously called Binary.__bytes__
    # with Acquired's layout: unsanitized builds crashed, while ASan could hang.
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Binary:
            def __init__(self):
                self.payload = [65, 65, 66]
            def __iter__(self) -> 'Binary':
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def __bytes__(self) -> bytes:
                gc_collect()
                return bytes(self.payload)
        class Acquired:
            def __init__(self):
                self.number = 66
                self.position = 0
            def __iter__(self) -> 'Acquired':
                return self
            def __next__(self) -> int:
                gc_collect()
                self.position += 1
                if self.position > 2:
                    raise StopIteration()
                return self.number + self.position - 1
            def __bytes__(self) -> bytes:
                gc_collect()
                return bytes([self.number])
        class Plain:
            def __init__(self):
                self.position = 0
            def __iter__(self) -> 'Plain':
                return self
            def __next__(self) -> int:
                self.position += 1
                if self.position > 1:
                    raise StopIteration()
                return 90
        class Empty:
            def __iter__(self) -> 'Empty':
                return self
            def __next__(self) -> int:
                raise StopIteration()
        class Source:
            def __iter__(self) -> Acquired:
                return Acquired()
        class Redirect:
            def __iter__(self) -> Acquired:
                return Acquired()
            def __next__(self) -> int:
                raise StopIteration()
        class PlainSource:
            def __iter__(self) -> Plain:
                return Plain()
        def acquire(value: Iterable[int]) -> Iterator[int]:
            return iter(value)
        def reacquire(value: Iterator[int]) -> Iterator[int]:
            return iter(value)
        def convert(value: Iterator[int]) -> bytes:
            return bytes(value)
        def through_iterable(value: Iterable[int]) -> bytes:
            return bytes(value)
        def main() -> str:
            gc_set_threshold(1)
            rows = [{"convert(Binary()).hex()," if direct_arm else ""}
                    bytes(iter(Acquired())).hex(), convert(iter(Acquired())).hex(),
                    convert(iter(Source())).hex(), convert(acquire(Source())).hex(),
                    through_iterable(acquire(Source())).hex(), convert(reacquire(Redirect())).hex(),
                    bytes(iter(Plain())).hex(), convert(acquire(PlainSource())).hex(),
                    bytes(iter(Empty())).hex(), convert(iter([1, 2])).hex()]
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined") if sanitized else ())
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("keep_known", [False, True], ids=["no-arm", "one-arm"])
def test_iterator_byte_dispatch_fails_safely_if_source_metadata_is_incomplete(tmp_path, optimize, keep_known):
    # Deliberately remove one analysis fact after normal reachability. This is
    # fault injection into the compiler contract, not a supported Python program
    # outcome: an omitted future handle path must never permit type confusion.
    source = '''
        from collections.abc import Iterator
        class Known:
            def __init__(self):
                self.payload = [65]
            def __iter__(self) -> 'Known':
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def __bytes__(self) -> bytes:
                return bytes(self.payload)
        class Unknown:
            def __iter__(self) -> 'Unknown':
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def __bytes__(self) -> bytes:
                return b'unknown'
        def convert(value: Iterator[int]) -> bytes:
            return bytes(value)
        def main() -> int:
            if False:
                convert(Known())
            try:
                convert(iter(Unknown()))
            except TypeError as error:
                return 0 if str(error) == 'unknown application byte conversion source' else 2
            return 1
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        program = build_program_ir(entry)
        assert {original.name for original, _ in entry.runtime_view_sources} == {"Known", "Unknown"}
        entry.runtime_view_sources = {(original, view) for original, view in entry.runtime_view_sources
                                      if keep_known and original.name == "Known"}
        llvm_ir = LLVMEmitter("main").emit(program)
    tool = LLVM()
    executable = tool.compile(llvm_ir, tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    result = tool.runner.run([executable], capture_output=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    assert not result.stderr

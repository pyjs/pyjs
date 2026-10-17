import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_expandtabs_matches_python_columns_index_callbacks_and_bounds(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Size:
            def __init__(self, value: int, events: list[int], fail: bool):
                self.value = value
                self.events = events
                self.fail = fail

            def __index__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                if self.fail:
                    raise ValueError("index failed")
                return self.value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            results: list[str] = []
            for value in ["", "a\\tb", "é\\t🙂", "é\\tx", "a\\tb\\nc\\td", "a\\tb\\rc\\td", "a\\tb\\vc\\td", "\\0\\t", "\\t\\t"]:
                for size in [-5, 0, 1, 4, 8]:
                    result = value.expandtabs(Size(size, events, False))
                    gc_collect()
                    results.append(repr(result))
            for size in [-9223372036854775808, -2147483649, -2147483648, 2147483647, 2147483648, 9223372036854775807]:
                result = "unchanged"
                try:
                    result = "plain".expandtabs(tabsize=Size(size, events, False))
                except OverflowError as error:
                    results.append(str(error))
                results.append(result)
            try:
                results.append("\\t".expandtabs(Size(2147483648, events, True)))
            except ValueError as error:
                results.append(str(error))
            gc_collect()
            results.append("a\\tb".expandtabs())
            return "|".join(results) + repr(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_edit_counts_use_index_protocol_and_preserve_defaults(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for count in [-2, 0, 1, 4]:
                value = Index(count)
                rows.append(repr(('é😀'.ljust(value, '-'), 'é😀'.rjust(value),
                    'é😀'.center(value, '界'), '-7'.zfill(value),
                    'é\\t😀\\n\\ta'.expandtabs(tabsize=value),
                    'a\\0aéa'.replace('a', '界', count=value),
                    ' a b c '.split(maxsplit=value), 'a-b-c'.rsplit('-', value),
                    b'a\\xffa\\0a'.replace(b'a', b'xy', value),
                    b' a b c '.rsplit(maxsplit=value), b'a-b-c'.split(b'-', value))))
            rows.append(repr(('a\\tb'.expandtabs(), 'aa'.replace('a', 'b'),
                ' a b '.split(), b' a b '.split(), 'a-b'.rsplit(sep='-'),
                'a-b-c'.split(**{'maxsplit': Index(1), 'sep': '-'}),
                'x'.center(int8(3)), 'x'.zfill(int64(3)), 'aa'.replace('a', 'b', True))))
            separators: list[str | None] = [None, '-', '']
            for separator in separators:
                try:
                    rows.append(repr(' a-b c '.split(sep=separator, maxsplit=Index(1))))
                except ValueError:
                    rows.append('empty separator')
            binary_separators: list[bytes | None] = [None, b'-', b'']
            for separator in binary_separators:
                try:
                    rows.append(repr(b' a-b c '.rsplit(sep=separator, maxsplit=Index(1))))
                except ValueError:
                    rows.append('empty separator')
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_counts_bind_all_expressions_before_conversion_and_recover(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, events: list[str], fail: bool):
                self.events, self.fail = events, fail
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                if self.fail:
                    raise ValueError('count failed')
                return 3
        def count(events: list[str], fail: bool) -> Index:
            events.append('count expression')
            return Index(events, fail)
        def text(events: list[str], value: str) -> str:
            events.append(value)
            gc_collect()
            return value + ''
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            rows: list[str] = []
            for fail in [False, True]:
                try:
                    rows.append(text(events, 'abc').center(count(events, fail), text(events, '-')))
                except ValueError as error:
                    rows.append(str(error))
                try:
                    rows.append(repr(text(events, 'a-b-c').split(
                        maxsplit=count(events, fail), sep=text(events, '-'))))
                except ValueError as error:
                    rows.append(str(error))
                try:
                    rows.append(text(events, 'aaa').replace(text(events, 'a'), text(events, 'b'),
                                                          count=count(events, fail)))
                except ValueError as error:
                    rows.append(str(error))
            rows.append(repr(events))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_counts_dispatch_nominal_erased_tagged_and_missing_protocols(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Index(Base):
            def __index__(self) -> int:
                gc_collect()
                return 2
        class IntOnly:
            def __int__(self) -> int:
                raise ValueError('must not call int')
        def erased(value: object) -> str:
            rows: list[str] = []
            try:
                rows.append('x'.center(value))
            except TypeError:
                rows.append('bad width')
            try:
                rows.append(repr(b'a-b-c'.split(maxsplit=value, sep=b'-')))
            except TypeError:
                rows.append('bad split')
            try:
                rows.append('aaa'.replace('a', 'b', count=value))
            except TypeError:
                rows.append('bad replace')
            return repr(rows)
        def nominal(value: Base) -> str:
            try:
                return '3'.zfill(value)
            except TypeError:
                return 'bad nominal'
        def tagged(value: int | Index | str | None) -> str:
            try:
                return 'a\\tb'.expandtabs(tabsize=value)
            except TypeError:
                return 'bad tagged'
        def main() -> str:
            gc_set_threshold(1)
            return repr((erased(Index()), erased(2), erased(True), erased(None), erased(1.5),
                erased('bad'), erased(IntOnly()), nominal(Index()), nominal(Base()),
                tagged(Index()), tagged(2), tagged(True), tagged(None), tagged('bad')))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "'x'.center(width=3)", "'x'.replace(old='x', new='y')",
    "b'x'.replace(b'x', b'y', count=1)", "'x'.expandtabs(2, tabsize=3)",
    "'x'.split('-', sep='-')", "b'x'.rsplit(unknown=1)",
])
def test_text_edit_binding_preserves_python_argument_errors(expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f'def main() -> str:\n    return repr({expression})\n')


@pytest.mark.parametrize("expression", ["'a-b-c'.split(*args)", "'x'.center(*[3])"])
def test_text_edit_positional_packs_have_a_located_boundary(expression):
    with pytest.raises(LLVMUnsupported, match="LLVM text editing requires statically bound arguments") as caught:
        transpile_llvm(f"def main() -> str:\n    args = ('-', 1)\n    return repr({expression})\n")
    assert caught.value.node.lineno == 3


def test_text_edit_dynamic_keyword_packs_keep_shared_diagnostic():
    with pytest.raises(CompilationError, match=r"dynamic \*\* argument expansion is not supported"):
        transpile_llvm('''
            def main() -> str:
                options: dict[str, int] = {'maxsplit': 1}
                return repr('a-b-c'.split(**options))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_count_errors_run_in_python_order_and_none_is_not_omitted(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        class Index:
            def __init__(self, events: list[str]):
                self.events = events
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                return 2
        def main() -> str:
            events: list[str] = []
            try:
                'x'.center(Index(events), 'xx')
            except TypeError:
                events.append('fill error')
            try:
                b'x'.split(b'', Index(events))
            except ValueError:
                events.append('separator error')
            try:
                'x'.replace('x', 'y', count=None)
            except TypeError:
                events.append('count error')
            try:
                'x'.split(maxsplit=None)
            except TypeError:
                events.append('limit error')
            try:
                'x'.expandtabs(tabsize=None)
            except TypeError:
                events.append('tab error')
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "'x'.center(count)", "'aaa'.replace('a', 'bb', count=count)", "b'a-b-c'.split(b'-', count)",
])
def test_text_allocation_failure_after_index_callback_is_recoverable(tmp_path, optimize, expression):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Index:
            def __init__(self, events: list[int], fail: bool):
                self.events, self.fail = events, fail
            def __index__(self) -> int:
                self.events.append(1)
                gc_collect()
                if self.fail:
                    arm(1)
                return 4
        def main() -> int:
            events: list[int] = []
            count = Index(events, True)
            try:
                {expression}
            except MemoryError:
                arm(0)
                events.append(2)
            else:
                return 1
            gc_collect()
            count.fail = False
            {expression}
            assert events == [1, 2, 1]
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)

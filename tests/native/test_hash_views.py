import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["hash(Hashed())", "hash((Hashed(),)) == hash((-1,))"])
def test_concrete_custom_hash_is_reached_without_an_opaque_consumer(tmp_path, optimize, expression):
    # No explicit method call or Element-typed hash site may retain the override
    # accidentally: the concrete implicit protocol must do that on its own.
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import CustomElement
        class Hashed(CustomElement):
            def __hash__(self) -> int:
                gc_collect()
                return -1
        def main() -> str:
            gc_set_threshold(1)
            return str({expression})
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_reference_hashes_keep_identity_across_views_and_gc(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import div
        def flags() -> Iterator[bool]:
            yield True
            yield False
        def widen(value: Iterator[bool]) -> Iterator[bool | int]:
            return value
        def main() -> str:
            gc_set_threshold(1)
            source = {'first': 1}
            values = source.values()
            iterator = iter([1, 2])
            generator = flags()
            view = widen(generator)
            node = div('before')
            before = (values.__hash__(), iterator.__hash__(), generator.__hash__(), node.__hash__())
            source['second'] = 2
            node.setAttribute('class', 'changed')
            gc_collect()
            same = before == (hash(values), hash(iterator), hash(view), hash(node))
            first = next(view)
            second = next(generator)
            exhausted = False
            try:
                next(view)
            except StopIteration:
                exhausted = True
            gc_collect()
            return str((same, first, second, exhausted, view.__hash__() == hash(generator),
                        next(iterator), list(values)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_cursor_hashes_select_original_application_protocols(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self):
                self.position = 0
            def __iter__(self) -> Iterator[int]:
                return self
            def __next__(self) -> int:
                self.position += 1
                return self.position
        class Hashed(Cursor):
            def __hash__(self) -> int:
                gc_collect()
                return self.position - 1
        class Disabled(Cursor):
            __hash__ = None
        class Retry(Cursor):
            def __hash__(self) -> int:
                if self.position == 0:
                    self.position = 1
                    raise ValueError('retry')
                gc_collect()
                return 7
        def direct(value: Iterator[int]) -> int:
            return value.__hash__()
        def implicit(value: Iterator[int]) -> int:
            return hash(value)
        def main() -> str:
            gc_set_threshold(1)
            cursor = Cursor()
            view = iter(cursor)
            same = direct(view) == hash(cursor) == implicit(cursor)
            first = next(view)
            gc_collect()
            output = [str((same, first, direct(view) == hash(cursor),
                           direct(Hashed()), implicit(Hashed())))]
            try:
                direct(Disabled())
            except TypeError as error:
                output.append(str(error))
            try:
                implicit(Disabled())
            except TypeError as error:
                output.append(str(error))
            recovering: Iterator[int] = Retry()
            try:
                direct(recovering)
            except ValueError as error:
                output.append(str(error))
            gc_collect()
            output.append(str(direct(recovering) == implicit(recovering) == 7))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dom_hashes_select_wrappers_and_preserve_default_node_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div
        class Plain(CustomElement):
            pass
        class Hashed(CustomElement):
            def __hash__(self) -> int:
                gc_collect()
                return -1
            def identity(self) -> int:
                return super().__hash__()
        class Disabled(CustomElement):
            __hash__ = None
        def direct(value: Element) -> int:
            return value.__hash__()
        def implicit(value: Element) -> int:
            return hash(value)
        def main() -> str:
            gc_set_threshold(1)
            node = div('plain')
            plain = Plain()
            hashed = Hashed()
            output = [str((direct(node) == hash(node), direct(plain) == hash(plain),
                           direct(hashed), implicit(hashed), hashed.identity() != -1))]
            try:
                direct(Disabled())
            except TypeError as error:
                output.append(str(error))
            gc_collect()
            output.append(str(direct(plain) == hash(plain)))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


def test_factory_recovers_body_signature_without_changing_public_iterator_type():
    source = '''
        from collections.abc import Iterator
        from pyjs import int8

        def parent():
            return (yield from child())

        def child() -> Iterator[int8]:
            received: int8 = yield int8(1)
            return received + 1

        def main() -> int:
            return int(next(parent()))
    '''
    # Analyze twice independently: body facts must not rely on a previous
    # module compilation or on source definition order.
    for _ in range(2):
        with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
            validate_program_ir(build_program_ir(analysis.entry_point))
            child = analysis.entry_point.container.search("child")
            parent = analysis.entry_point.container.search("parent")
            assert child.return_type.generic_name == "Iterator"
            assert parent.return_type.generic_name == "Generator"
            assert parent.return_type.generic_types["R"].generic_name == "int"
            item, sent, completed = parent.return_representation.arguments
            assert item.numeric.bits == 8
            assert item == sent == completed
            signature, representation = child.native_generator_signature
            assert signature.generic_name == "Generator"
            assert representation == parent.return_representation


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_iterator_factory_forwards_control_completion_and_gc_roots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, label: str):
                self.label = label

        def child(events: list[str], box: Box) -> Iterator[int8]:
            events.append("child started")
            try:
                received: int8 = yield int8(127)
                gc_collect()
                try:
                    yield received + 1
                except ValueError as error:
                    events.append(str(error))
                    yield int8(9)
                return box
            finally:
                events.append("child closed")

        def argument(events: list[str]) -> Box:
            events.append("argument")
            gc_collect()
            return Box("retained-" + str(len(events)))

        def statement(events: list[str]):
            try:
                yield from child(events, argument(events))
            finally:
                events.append("parent closed")

        def expression(events: list[str]):
            completed = yield from child(events, argument(events))
            gc_collect()
            return completed.label

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            frame = statement(events)
            assert not events
            values = [int(next(frame)), int(frame.send(int8(127)))]
            values.append(int(frame.throw(ValueError("handled"))))
            frame.close()
            other = expression(events)
            values.append(int(next(other)))
            values.append(int(other.send(int8(1))))
            completion: object = None
            try:
                next(other)
            except StopIteration as error:
                completion = error.value
            gc_collect()
            # The same factory still supports its ordinary erased interface.
            plain: Iterator[int8] = child(events, argument(events))
            values.append(int(next(plain)))
            return repr((values, completion, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_iterator_factory_statement_replay_and_optional_completion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def child(prefix: str) -> Iterator[str]:
            gc_collect()
            yield prefix + "-one"
            gc_collect()
            yield prefix + "-two"

        def failing() -> Iterator[str]:
            yield "before-error"
            raise ValueError("delegated")

        def optional(flag: bool) -> Iterator[str]:
            yield "optional"
            if flag:
                return "returned"

        def wide() -> Iterator[object]:
            yield 7
            yield "text"

        alias = wide

        def wide_parent() -> Iterator[object]:
            yield from alias()

        def recursive(depth: int) -> Generator[str, None, None]:
            if depth:
                yield from recursive(depth - 1)
            else:
                yield "bottom"

        def mutual(depth: int) -> Generator[str, None, None]:
            yield str(depth)
            if depth:
                yield from relay(depth - 1)

        def relay(depth: int) -> Iterator[str]:
            yield from mutual(depth)

        def parent() -> Iterator[str]:
            label = "item-" + str(3)
            yield "start"
            yield from child(label)
            gc_collect()
            yield label + "-done"
            try:
                yield from failing()
            except ValueError as error:
                yield "caught-" + str(error)
            yield from ["tail-one", "tail-two"]
            for flag in [True, False]:
                result = yield from optional(flag)
                yield str(result)
            yield from recursive(2)
            yield from mutual(2)

        def main() -> str:
            gc_set_threshold(1)
            return "|".join(parent()) + repr(list(wide_parent()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("factory, delegation", [
    ("def child() -> Iterator[int]:\n    return iter([1])", "child()"),
    ("def child() -> Iterator[int]:\n    yield 1", "saved"),
    ("class Factory:\n    def child(self) -> Iterator[int]:\n        yield 1", "Factory().child()"),
    ('@llvm.inline("{source}")\ndef child(source: Iterator[int]) -> Iterator[int]:\n    yield 99', "child(saved)"),
])
@pytest.mark.parametrize("expression", [False, True])
def test_factory_recovery_does_not_narrow_erased_or_virtual_results(factory, delegation, expression):
    source = f'''
from typing import Iterator
from pyjs import llvm
{factory}
def parent(saved: Iterator[int]):
    {"return (" if expression else ""}yield from {delegation}{")" if expression else ""}
def main() -> int:
    return next(parent(iter([1])))
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        parent = analysis.entry_point.container.search("parent")
        assert parent.return_type.generic_types["R"].generic_name == ("object" if expression else "NoneType")
        assert parent.return_type.generic_types["S"].generic_name == "NoneType"
        validate_program_ir(build_program_ir(analysis.entry_point))
    transpile_llvm(source)


def test_recursive_factory_requires_explicit_generator_contract():
    with pytest.raises(CompilationError, match="recursive delegation requires an explicit Generator"):
        transpile_llvm('''
            from typing import Iterator
            def child(depth: int) -> Iterator[int]:
                if depth:
                    yield from child(depth - 1)
                else:
                    yield 1
            def main() -> int:
                return next(child(2))
        ''')


def test_mutually_recursive_iterator_factories_report_dependency_cycle():
    with pytest.raises(CompilationError, match="Types in dependency cycle") as caught:
        transpile_llvm('''
            from typing import Iterator
            def left(depth: int) -> Iterator[int]:
                yield depth
                if depth:
                    yield from right(depth - 1)
            def right(depth: int) -> Iterator[int]:
                yield from left(depth)
            def main() -> int:
                return next(left(2))
        ''')
    assert caught.value.diagnostic.primary.span.start_position.line >= 2


@pytest.mark.parametrize("selected, body", [("int8", "int16"), ("int", "int8"), ("int8", "int")])
@pytest.mark.parametrize("delegated", [False, True])
def test_factory_overloads_cannot_replace_or_erase_portable_item_formats(selected, body, delegated):
    source = f'''
from typing import Iterator, overload
from pyjs import int8, int16
@overload
def child(flag: bool) -> Iterator[{selected}]: ...
@overload
def child(flag: int) -> Iterator[{body}]: ...
def child(flag: bool | int) -> Iterator[{body}]:
    yield {body}(127)
def parent():
    yield from child(True)
def main() -> str:
    return repr([value + 1 for value in {"parent()" if delegated else "child(True)"}])
'''
    with pytest.raises(LLVMUnsupported, match="call result projection requires matching representations"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_overload_uses_the_compiled_factory_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator, Iterator, overload
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        @overload
        def child(flag: bool) -> Generator[int8, int8, str | None]: ...
        @overload
        def child(flag: int) -> Iterator[int8]: ...
        def child(flag: bool | int) -> Iterator[int8]:
            received: int8 = yield int8(127)
            gc_collect()
            yield received + 1
            return "done-" + str(flag)

        def parent():
            return (yield from child(True))

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = []
            for frame in [child(True), parent()]:
                values.append(int(next(frame) + 1))
                values.append(int(frame.send(int8(127))))
                try:
                    next(frame)
                except StopIteration as error:
                    values.append(error.value)
            gc_collect()
            return repr(values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("yielded, sent, completed, message", [
    ("int8", "None", "int16", "projection requires matching representations"),
    ("int16", "str", "int16", "covariant yields/results and contravariant sends"),
    ("int16", "None", "str", "covariant yields/results and contravariant sends"),
    ("int16", "None", "int8", "projection requires matching representations"),
    ("int16", "None", "int", "projection requires matching representations"),
])
def test_generator_overloads_check_hidden_item_send_and_completion_contracts(yielded, sent, completed, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from typing import Generator, Iterator, overload
            from pyjs import int8, int16
            @overload
            def child(flag: bool) -> Generator[{yielded}, {sent}, {completed}]: ...
            @overload
            def child(flag: int) -> Iterator[int16]: ...
            def child(flag: bool | int) -> Iterator[int16]:
                yield int16(127)
                return int16(128)
            def main() -> str:
                return repr(list(child(True)))
        ''')

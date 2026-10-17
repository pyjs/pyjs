import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_splitlines_keepends_callbacks_collect_and_raise(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Flag:
            def __init__(self, events: list[str], fail: bool):
                self.events = events
                self.fail = fail

            def __bool__(self) -> bool:
                self.events.append("bool")
                gc_collect()
                if self.fail:
                    raise TypeError("truth failed")
                return True

        class Length:
            def __init__(self, value: int):
                self.value = value

            def __len__(self) -> int:
                gc_collect()
                return self.value

        class IndexOnly:
            def __index__(self) -> int:
                raise AssertionError("keepends must not use __index__")

        def text_argument(events: list[str]) -> str:
            events.append("text")
            return "\\n".join(["long" * 64, "tail"])

        def flag_argument(events: list[str]) -> Flag:
            events.append("flag")
            return Flag(events, False)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            text = "é\\r\\n" * 3
            result = text.splitlines(keepends=Flag(events, False))
            try:
                result = text.splitlines(Flag(events, True))
            except TypeError as error:
                events.append(str(error))
            for value in [-1, 0, 2]:
                try:
                    events.append(repr(b"a\\nb".splitlines(keepends=Length(value))))
                except ValueError as error:
                    events.append(str(error))
            events.append(repr(text.splitlines(IndexOnly())))
            temporary = text_argument(events).splitlines(keepends=flag_argument(events))
            assert temporary == ["long" * 64 + "\\n", "tail"]
            assert events[-3:] == ["text", "flag", "bool"]
            gc_collect()
            return repr((result, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_splitlines_truth_bindings_and_reached_overrides(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect

        class Base:
            def __len__(self) -> int:
                return 0

        class Child(Base):
            def __bool__(self) -> bool:
                gc_collect()
                return True

        def nominal(flag: Base) -> list[str]:
            return "a\\nb".splitlines(flag)

        def erased(flag: object) -> list[bytes]:
            return b"a\\nb".splitlines(keepends=flag)

        def main() -> str:
            result = [repr(nominal(Base())), repr(nominal(Child())), repr(erased(Child()))]
            for flag in [None, 0, 2, False, True]:
                result.append(repr("a\\nb".splitlines(keepends=flag)))
            result.append(repr("a\\nb".splitlines(int8(1))))
            result.append(repr(b"a\\nb".splitlines(keepends=int8(0))))
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("expression", [
    '"a".splitlines(True, keepends=False)',
    'b"a".splitlines(unknown=True)',
    'str.splitlines("a", True, False)',
    # Unbound builtin text methods are a pre-existing analyzer boundary.
    'str.splitlines("a", keepends=True)',
    'bytes.splitlines(b"a", True)',
])
def test_splitlines_rejects_invalid_argument_binding(expression):
    with pytest.raises(CompilationError) as caught:
        transpile_llvm(f'def main() -> str:\n    return repr({expression})\n')
    assert caught.value.lineno == 2


@pytest.mark.parametrize("expression", ['str.splitlines("a")', 'bytes.splitlines(b"a")'])
def test_single_unbound_splitlines_receiver_is_rejected_during_lowering(expression):
    from pyjs.native.llvm import LLVMUnsupported

    with pytest.raises(LLVMUnsupported, match="class objects are not runtime values"):
        transpile_llvm(f'def main() -> str:\n    return repr({expression})\n')

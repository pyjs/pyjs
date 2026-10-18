from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly.transpiler import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import EXCEPTION_HIERARCHIES


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_hierarchies_dispatch_and_reraise(tmp_path, optimize):
    # Compile the matrix once per optimization level; named source functions
    # and returned labels keep failures attributable to the individual class.
    source = "from pyjs.native import gc_collect, gc_set_threshold\n"
    for name, parent, sibling in EXCEPTION_HIERARCHIES:
        source += dedent(f'''
            def case_{name}(size: int) -> str:
                result = ""
                try:
                    try:
                        raise {name}("{name}:" + "x" * size)
                    except {sibling}:
                        return "wrong handler: {sibling}"
                    except {parent} as error:
                        gc_collect()
                        result = str(error)
                        raise
                except {name} as outer:
                    gc_collect()
                    return result + ":" + str(outer)
                return "not raised: {name}"
        ''')
    calls = ", ".join(f"case_{name}(20)" for name, _, _ in EXCEPTION_HIERARCHIES)
    source += f'\ndef main() -> str:\n    gc_set_threshold(1)\n    return "|".join([{calls}])\n'
    comparison = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_subclass_alias_and_nested_cleanup(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from builtins import ConnectionError as TransportBase
        from pyjs.native import gc_collect

        class Disconnected(TransportBase):
            pass

        def fail(size: int) -> None:
            raise Disconnected("connection:" + "x" * size)

        def main() -> str:
            events: list[str] = []
            try:
                try:
                    fail(30)
                except TransportBase as outer:
                    try:
                        raise FileNotFoundError("cleanup")
                    except OSError as inner:
                        events.append(str(inner))
                        gc_collect()
                    events.append(str(outer))
                    raise outer
                finally:
                    events.append("finally")
            except Disconnected as error:
                gc_collect()
                events.append(str(error))
            return "|".join(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_messages_and_tuple_handlers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        def describe(message: str | int | float | bool | None) -> str:
            try:
                raise PermissionError(message)
            except (ArithmeticError, OSError) as error:
                return str(error)
            return "not caught"

        def main() -> str:
            result = "not caught"
            try:
                raise EOFError()
            except BaseException as error:
                result = str(error)
            return "|".join([
                result, describe("text"), describe(42), describe(1.5),
                describe(True), describe(None),
            ])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_omitted_syntax_messages_remain_distinct_from_empty_text(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        class ParseFailure(SyntaxError):
            pass

        def stream() -> Generator[str, None, None]:
            try:
                yield "ready"
            except SyntaxError as error:
                gc_collect()
                yield str(error)

        def main() -> str:
            messages: list[str] = []
            try:
                raise SyntaxError()
            except SyntaxError as error:
                messages.append(str(error))
            try:
                raise IndentationError()
            except SyntaxError as error:
                messages.append(str(error))
            try:
                raise TabError()
            except SyntaxError as error:
                messages.append(str(error))
            try:
                raise ParseFailure()
            except SyntaxError as error:
                messages.append(str(error))
            try:
                raise TabError("")
            except SyntaxError as error:
                messages.append(str(error))
            try:
                raise TabError(None)
            except SyntaxError as error:
                messages.append(str(error))
            iterator = stream()
            next(iterator)
            messages.append(iterator.throw(TabError()))
            iterator.close()
            return repr(messages)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("name", ["TabError", "ModuleNotFoundError", "BrokenPipeError", "SystemError"])
def test_unhandled_builtin_preserves_leaf_name(name):
    execution = LLVM().run_source(
        f'def main() -> int:\n    raise {name}("message")\n', filename="hierarchy.py",
    )
    assert execution.returncode < 0
    assert execution.stderr == (
        'Traceback (native PyJS):\n  File "hierarchy.py", line 2, in main\n'
        f"{name}: message\n"
    )


@pytest.mark.parametrize("name", ["FileNotFoundError", "ImportError", "SyntaxError"])
def test_keyword_message_remains_an_explicit_boundary(name):
    with pytest.raises(CompilationError, match="positional message"):
        transpile_llvm(f'def main() -> int:\n    raise {name}(message="lost")\n')


@pytest.mark.parametrize("expression", [
    'FileNotFoundError(2, "missing", "file")',
    'SyntaxError("invalid", ("file", 1, 2, "text"))',
])
def test_rich_constructors_remain_an_explicit_boundary(expression):
    with pytest.raises(CompilationError, match="at most one message argument") as caught:
        transpile_llvm(f"def main() -> int:\n    raise {expression}\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("name", [row[0] for row in EXCEPTION_HIERARCHIES])
def test_shared_declarations_keep_webassembly_boundary(name):
    source = f'def main() -> int:\n    raise {name}("message")\n'
    with pytest.raises(WebAssemblyUnsupported, match="exception raising is not implemented"):
        transpile_webassembly(source)

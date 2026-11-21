import textwrap

import pytest

from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.javascript.source import analyze_source
from pyjs.testing.helpers import ad, at, diagnostic_text


def test_nested_promise_diagnostic_points_at_the_callers_annotation():
    ad(
        '''\
        from pyjs.javascript import Promise
        from collections.abc import Awaitable
        def main(value: Promise[Awaitable[int]]):
            pass
        ''',
        diagnostic_text(
            "promise.py", 3, "def main(value: Promise[Awaitable[int]]):",
            "                ^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: JavaScript promises cannot preserve an awaitable as their resolved value [PYJS2001]",
            "help: Use the final resolved type, or wrap the awaitable in a container.",
        ),
        filename="promise.py",
    )


@pytest.mark.parametrize("annotation", [
    "Promise[Promise[int]]", "Promise[int | Awaitable[int]]",
    "Awaitable[Promise[int]]", "Awaitable[Awaitable[int]]",
    "list[Promise[Awaitable[int]]]",
])
def test_nested_awaitable_annotations_are_rejected(annotation):
    source = (
        "from pyjs.javascript import Promise\n"
        "from collections.abc import Awaitable\n"
        f"def main(value: {annotation}):\n    pass\n"
    )
    with pytest.raises(CompilationError, match="cannot preserve an awaitable"):
        with analyze_source(source):
            pass


@pytest.mark.parametrize("annotation", ["", " -> object", " -> Awaitable[int]"])
def test_async_return_cannot_hide_an_awaitable(annotation):
    source = (
        "from pyjs.javascript import Promise\n"
        "from collections.abc import Awaitable\n"
        f"async def main(){annotation}:\n    return Promise.resolve(42)\n"
    )
    with pytest.raises(CompilationError, match="changes meaning in JavaScript") as caught:
        with analyze_source(source):
            pass
    assert caught.value.diagnostic.code == DiagnosticCode.INCOMPATIBLE_RETURN


@pytest.mark.parametrize(("body", "message"), [
    ('return Promise[int](lambda resolve, reject: resolve("wrong"))', "expects int|Awaitable[int]"),
    ('pending = Promise[int].withResolvers()\npending.resolve("wrong")', "expects int|Awaitable[int]"),
    ('return Promise[int](lambda resolve: resolve(1))', "exactly 2 positional parameters"),
    ('return Promise.resolve(1).then(lambda value: value.missing())', "missing"),
    ('return Promise[int].resolve("wrong")', "expects int|Awaitable[int]"),
    ('return Promise.resolve(1).__await__()', "do not expose Python __await__"),
])
def test_promise_type_errors_are_compile_time_errors(body, message):
    source = (
        "from pyjs.javascript import Promise\ndef main():\n"
        + textwrap.indent(body, "    ")
    )
    with pytest.raises(CompilationError, match=message):
        with analyze_source(source):
            pass


def test_async_executor_is_rejected_before_it_can_lose_a_rejection():
    source = '''
        from pyjs import js
        from pyjs.javascript import Promise
        from collections.abc import Callable
        @js
        async def executor(resolve: Callable[[int], None], reject: Callable[[object], None]) -> None:
            resolve(42)
        def main():
            return Promise[int](executor)
    '''
    with pytest.raises(CompilationError, match="executor.*cannot be async"):
        with analyze_source(textwrap.dedent(source)):
            pass


@pytest.mark.parametrize("expression", [
    "Promise[int](executor=lambda resolve, reject: resolve(42))",
    "Promise.resolve(value=42)",
    "Promise[int].reject(reason='failure')",
    "Promise.all(values=[1, 2])",
    "Promise.allSettled(values=[1, 2])",
    "Promise.race(values=[1, 2])",
    "Promise.any(values=[1, 2])",
    "Promise.try_(callback=lambda: 42)",
    "value.then(onfulfilled=lambda item: item + 1)",
    "value.then(None, onrejected=lambda reason: 42)",
    "value.then(lambda item: item, onrejected=lambda reason: 42)",
    "value.catch(onrejected=lambda reason: 42)",
    "value.finally_(onfinally=lambda: None)",
])
def test_promise_keyword_arguments_fail_before_native_emission(expression):
    source = (
        "from pyjs.javascript import Promise\n"
        "def main(value: Promise[int]):\n"
        f"    return {expression}\n"
    )
    with pytest.raises(CompilationError, match="positional-only") as caught:
        with analyze_source(source):
            pass
    assert caught.value.diagnostic.code == DiagnosticCode.INCOMPATIBLE_ARGUMENT


def test_promise_keyword_diagnostic_locates_the_argument():
    ad(
        '''\
        from pyjs.javascript import Promise
        def main():
            return Promise.resolve(value=42)
        ''',
        diagnostic_text(
            "promise.py", 3, "return Promise.resolve(value=42)",
            "                       ^^^^^^^^",
            "pyjs.CompilationError: resolve() parameter 'value' is positional-only [PYJS1104]",
            "help: Pass 'value' as a positional argument.",
        ),
        filename="promise.py",
    )


@pytest.mark.parametrize(("binding", "argument"), [
    ("Promise[int].resolve", "value=42"),
    ("value.then", "onfulfilled=lambda item: item + 1"),
])
def test_extracted_promise_methods_retain_positional_only_parameters(binding, argument):
    source = (
        "from pyjs.javascript import Promise\n"
        "def main(value: Promise[int]):\n"
        f"    operation = {binding}\n"
        f"    return operation({argument})\n"
    )
    with pytest.raises(CompilationError, match="unexpected keyword argument") as caught:
        with analyze_source(source):
            pass
    assert caught.value.diagnostic.code == DiagnosticCode.INCOMPATIBLE_ARGUMENT


def test_python_await_protocol_is_not_mistaken_for_a_native_promise():
    source = '''
        from pyjs import js
        from collections.abc import Awaitable, Iterator
        @js
        class Custom(Awaitable[int]):
            def __await__(self) -> Iterator[int]:
                yield 42
        async def main(value: Custom):
            return await value
    '''
    with pytest.raises(CompilationError, match="Python __await__ implementations"):
        with analyze_source(textwrap.dedent(source)):
            pass


def test_thenable_python_return_is_rejected():
    source = '''
        from pyjs import js
        @js
        class Thenable:
            def then(self, resolve: callable, reject: callable) -> None:
                resolve(42)
        async def main():
            return Thenable()
    '''
    with pytest.raises(CompilationError, match="changes meaning in JavaScript"):
        with analyze_source(textwrap.dedent(source)):
            pass


def test_native_generic_methods_expand_only_when_reached():
    at(
        '''
        @js.native
        class NativeBox[T]:
            def __init__(self, value: T): ...
            def nested(self) -> NativeBox[list[T]]: ...
        def main():
            return NativeBox[int](42).nested().nested()
        ''',
        '''
        def main() -> NativeBox[list[list[int]]]:
            return NativeBox__int(42).[NativeBox__int]nested().[NativeBox__list__int]nested()
        ''',
        '''
        export function main() {
            return new globalThis.NativeBox(42).nested().nested();
        }
        ''',
    )


def test_two_argument_then_retains_lambda_parameter_type():
    at(
        '''
        from pyjs.javascript import Promise
        async def main(value: Promise[int]) -> int:
            return await value.then(lambda item: item + 1, None)
        ''',
        '''
        async def main(value: Promise__int) -> int:
            return await value.[Promise__int]then(lambda item: item.[int]__add__!(1), None)
        ''',
        '''
        export async function main(value) {
            return await value.then((item) => item + 1, null);
        }
        ''',
    )


def test_native_constructor_extra_spread_arguments_have_a_diagnostic():
    source = '''
        from pyjs import js
        @js.native
        class Native:
            def __init__(self, value: int): ...
        def main():
            return Native(1, *(2,), 3)
    '''
    with pytest.raises(CompilationError, match="received too many positional arguments"):
        with analyze_source(textwrap.dedent(source)):
            pass


def test_native_awaitable_cannot_silently_use_the_wrong_numeric_type_argument():
    source = '''
        from pyjs import js, int8, int64
        from collections.abc import Awaitable, Iterator
        @js.native
        class Deferred[A, B](Awaitable[B]):
            def __await__(self) -> Iterator[B]: ...
        async def main(value: Deferred[int8, int64]):
            return await value
    '''
    with pytest.raises(CompilationError, match="cannot project this result representation"):
        with analyze_source(textwrap.dedent(source)):
            pass

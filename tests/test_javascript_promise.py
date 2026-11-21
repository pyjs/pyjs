import textwrap

import pytest

from pyjs.javascript import Promise
from pyjs.testing.helpers import at
from tests.semantics.helpers import run_javascript


def test_native_promise_constructor_and_resolver_types():
    at(
        '''
        from pyjs.javascript import Promise

        async def main() -> int:
            pending = Promise[int].withResolvers()
            pending.resolve(42)
            return await pending.promise
        ''',
        '''
        async def main() -> int:
            pending: PromiseResolvers[int] = Promise__int.[Promise__int]withResolvers()
            pending.resolve(42)
            return await pending.promise
        ''',
        '''
        export async function main() {
            var pending = globalThis.Promise.withResolvers();
            pending.resolve(42);
            return await pending.promise;
        }
        ''',
    )


@pytest.mark.parametrize("body", [
    '''
    events: list[int] = []
    promise = Promise[None](lambda resolve, reject: resolve(events.append(1)))
    assert events == [1]
    chained = promise.then(lambda value: events.append(2))
    assert events == [1]
    await chained
    assert events == [1, 2]
    ''',
    '''
    pending = Promise[int].withResolvers()
    pending.resolve(1)
    pending.resolve(2)
    pending.reject("ignored")
    assert await pending.promise == 1
    assert await pending.promise == 1
    ''',
    '''
    inner = Promise[int].withResolvers()
    outer = Promise[int].withResolvers()
    outer.resolve(inner.promise)
    outer.reject("ignored after adoption")
    inner.resolve(42)
    assert await outer.promise == 42
    ''',
    '''
    promise = Promise[int].reject("reason")
    assert await promise.catch(lambda reason: 42) == 42
    ''',
    '''
    assert await Promise.resolve(42).then(lambda value: str(value)) == "42"
    assert await Promise.resolve(42).then(lambda value: Promise.resolve(str(value))) == "42"
    ''',
    '''
    pending = Promise[int].withResolvers()
    pending.reject("failed")
    result = pending.promise.then(lambda value: str(value), lambda reason: "recovered")
    assert await result == "recovered"
    ''',
    '''
    events: list[int] = []
    assert await Promise.resolve(42).finally_(lambda: events.append(1)) == 42
    assert events == [1]
    result = Promise[int].reject("failed").finally_(lambda: events.append(2))
    assert await result.catch(lambda reason: 7) == 7
    assert events == [1, 2]
    ''',
    '''
    second = Promise[int].withResolvers()
    first = Promise[int].withResolvers()
    result = Promise.all([first.promise, second.promise, 3])
    second.resolve(2)
    first.resolve(1)
    assert await result == [1, 2, 3]
    assert await Promise.all([]) == []
    assert await Promise.all({1: 9, 2: 8}) == [1, 2]
    assert await Promise.all((1, 2)) == [1, 2]
    assert await Promise.all({1, 2}) == [1, 2]
    assert await Promise.allSettled([]) == []
    ''',
    '''
    assert await Promise[int].race([Promise.resolve(1), Promise.resolve(2)]) == 1
    assert await Promise[int].any([Promise[int].reject("failed"), Promise.resolve(2)]) == 2
    ''',
    '''
    result = await Promise.allSettled([Promise.resolve(1), Promise[int].reject("failed")])
    assert result[0].status == "fulfilled"
    assert result[0].value == 1
    assert result[1].status == "rejected"
    assert result[1].reason == "failed"
    ''',
    '''
    assert await Promise.resolve(42).then() == 42
    result = Promise[int].reject("failed").then(None, lambda reason: "recovered")
    assert await result == "recovered"
    assert await Promise.resolve(42).catch(lambda reason: "unused") == 42
    ''',
    '''
    pending = Promise[int].withResolvers()
    pending.resolve(pending.promise)
    rejected = False
    try:
        await pending.promise
    except TypeError:
        rejected = True
    assert rejected
    ''',
    '''
    rejected = False
    try:
        await Promise[int].any([])
    except Exception:
        rejected = True
    assert rejected
    ''',
    '''
    resolve = Promise[int].resolve
    assert await resolve(42) == 42
    ''',
    '''
    assert await Promise.try_(lambda: 42) == 42
    assert await Promise.try_(lambda: Promise.resolve(42)) == 42
    ''',
])
def test_native_promise_execution(body):
    source = (
        "from pyjs import js\nfrom pyjs.javascript import Promise\n"
        "@js\nasync def main():\n"
        + textwrap.indent(textwrap.dedent(body).strip(), "    ")
        + '\n    print("passed")\n'
    )
    result, javascript = run_javascript(source)
    assert result.returncode == 0, result.stderr + "\n" + javascript
    assert result.stdout == "passed\n"


@pytest.mark.parametrize("create", [
    lambda: Promise[int](lambda resolve, reject: resolve(1)),
    lambda: Promise.resolve(1),
    lambda: Promise[int].withResolvers(),
    lambda: Promise[int].reject("failed"),
    lambda: Promise.all([]),
    lambda: Promise.allSettled([]),
    lambda: Promise.any([]),
    lambda: Promise.race([]),
    lambda: Promise.try_(lambda: 42),
])
def test_promise_cannot_silently_run_on_cpython(create):
    with pytest.raises(NotImplementedError, match="Promise requires the JavaScript runtime"):
        create()


def test_promise_exception_propagation_and_erased_async_result_guard():
    source = '''
        from pyjs import js
        from pyjs.javascript import Promise
        from collections.abc import Callable
        from typing import cast

        @js
        def failing_executor(resolve: Callable[[int], None], reject: Callable[[object], None]) -> None:
            raise ValueError("executor failed")

        @js
        def failing_cleanup() -> None:
            raise ValueError("cleanup failed")

        @js
        async def hidden(value: object) -> object:
            return value

        @js
        async def wrapped(value: object) -> list[object]:
            return [value]

        @js
        async def increment(value: int) -> int:
            return value + 1

        @js
        async def cleanup() -> None:
            await Promise.resolve(None)

        @js
        async def main():
            assert await Promise.resolve(41).then(increment).finally_(cleanup) == 42
            pending = Promise[int](failing_executor)
            failed = False
            try:
                await pending
            except ValueError as error:
                assert str(error) == "executor failed"
                failed = True
            assert failed
            failed = False
            try:
                await Promise.resolve(42).finally_(failing_cleanup)
            except ValueError as error:
                assert str(error) == "cleanup failed"
                failed = True
            assert failed
            failed = False
            try:
                await Promise.try_(failing_cleanup)
            except ValueError as error:
                assert str(error) == "cleanup failed"
                failed = True
            assert failed
            failed = False
            try:
                await hidden(Promise.resolve(42))
            except TypeError as error:
                assert "async Python return" in str(error)
                failed = True
            assert failed
            assert cast(int, await hidden(42)) == 42
            container = await wrapped(Promise.resolve(42))
            assert await cast(Promise[int], container[0]) == 42
            print("passed")
    '''
    result, javascript = run_javascript(source)
    assert result.returncode == 0, result.stderr + "\n" + javascript
    assert result.stdout == "passed\n"


def test_native_promise_alias_is_not_captured_by_python_local_names():
    source = '''
        from pyjs import js
        from pyjs.javascript import Promise as NativePromise

        @js
        async def run(Promise: int, globalThis: int) -> int:
            pending = NativePromise[int](lambda resolve, reject: resolve(Promise + globalThis))
            return await pending

        @js
        async def main():
            assert await run(40, 2) == 42
    '''
    result, javascript = run_javascript(source)
    assert result.returncode == 0, result.stderr + "\n" + javascript


def test_promise_preserves_portable_numeric_representations():
    source = '''
        from pyjs import js, int8, int64, float32
        from pyjs.javascript import Promise

        @js
        async def main():
            assert (await Promise[int8].resolve(int8(127))) + int8(1) == int8(-128)
            assert (await Promise[float32].resolve(float32(16777216))) + float32(1) == float32(16777216)
            large = int64(9007199254740991) + int64(2)
            assert await Promise[int64].resolve(large) == large
            result = Promise[int8].resolve(int8(127)).then(lambda value: value + int8(1))
            assert await result == int8(-128)
    '''
    result, javascript = run_javascript(source)
    assert result.returncode == 0, result.stderr + "\n" + javascript

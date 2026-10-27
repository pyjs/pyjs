import pytest

from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("expression", [
    "await value(events, 1) < value_sync(events, 2) < value_sync(events, 3)",
    "value_sync(events, 1) < await value(events, 2) < value_sync(events, 3)",
    "value_sync(events, 1) < value_sync(events, 2) < await value(events, 3)",
    "await value(events, 1) < await value(events, 2) < await value(events, 3)",
    "value_sync(events, 3) < await value(events, 2) < await value(events, 99)",
    "await value(events, 1) < await value(events, 2) > value_sync(events, 3) < await value(events, 99)",
    "await value(events, 1) < (4 if await value(events, 2) < await value(events, 3) < 5 else 0) < 9",
    "await value(events, 1) < (4 if 2 < 3 < 5 else 0) < 9",
    "1 < (4 if 2 < await value(events, 3) < 5 else 0) < 9",
    "(1 < await value(events, 2) < 3) == (4 < await value(events, 5) < 6)",
    "len([1 < await value(events, 2) < 3, 4 < await value(events, 5) < 6]) == 2",
])
def test_awaited_operands_are_once_ordered_and_short_circuited(expression):
    assert_semantics(f'''
import asyncio
from pyjs import js

@js
def value_sync(events: list[int], value: int) -> int:
    events.append(value)
    if value == 99:
        raise ValueError("must not execute")
    return value

@js
async def value(events: list[int], item: int) -> int:
    return value_sync(events, item)

@js
async def main() -> None:
    events: list[int] = []
    result = {expression}
    print(result)
    for item in events:
        print(item)

asyncio.run(main())
''')


@pytest.mark.parametrize("expression", [
    'await value() < schedule(events) < 3',
    '3 < schedule(events) < await value()',
])
def test_comparison_does_not_add_a_suspension(expression):
    assert_semantics(f'''
import asyncio
from pyjs import js
from pyjs.web.timers import queueMicrotask

@js
def schedule(events: list[str]) -> int:
    asyncio.get_running_loop().call_soon(events.append, "tick")
    return 2

@schedule.client
def schedule(events: list[str]) -> int:
    queueMicrotask(lambda: events.append("tick"))
    return 2

@js
async def value() -> int:
    return 1

@js
async def main() -> None:
    events: list[str] = []
    result = {expression}
    events.append("after")
    print(result, ",".join(events))

asyncio.run(main())
''')


def test_method_comparison_locals_survive_nested_calls_and_repeat_in_loops():
    assert_semantics('''
import asyncio
from pyjs import js

@js
async def value(item: int) -> int:
    return item

@js
class Checker:
    async def check(self, item: int) -> bool:
        if item > 0:
            return 0 < await value(2 if await self.check(item - 1) else 0) < 3
        return 1 < await value(2) < 3

@js
async def main() -> None:
    checker = Checker()
    for item in range(3):
        print(await checker.check(item))
        print(0 < await value(item) < 2)

asyncio.run(main())
''')


def test_comparison_propagates_rejection_and_does_not_evaluate_the_tail():
    assert_semantics('''
import asyncio
from pyjs import js

@js
async def failed() -> int:
    raise ValueError("failed operand")

@js
def tail(events: list[int]) -> int:
    events.append(1)
    return 3

@js
async def main() -> None:
    events: list[int] = []
    try:
        result = 1 < await failed() < tail(events)
        print(result)
    except ValueError as error:
        print(str(error), len(events))

asyncio.run(main())
''')

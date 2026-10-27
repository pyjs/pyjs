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

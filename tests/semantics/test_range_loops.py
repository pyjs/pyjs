import pytest

from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("step", ["-2", "2", "0"])
def test_range_argument_order_errors_and_finally(step):
    assert_semantics(f'''
from pyjs import js
@js
def argument(events: list[int], marker: int, value: int) -> int:
    events.append(marker)
    return value
@js
def main():
    events: list[int] = []
    try:
        for i in range(argument(events, 1, 5), argument(events, 2, 0), argument(events, 3, {step})):
            try:
                events.append(i)
                if i == 5:
                    continue
                break
            finally:
                events.append(9)
        else:
            events.append(8)
    except ValueError:
        events.append(7)
    for event in events:
        print(event)
main()
''')


def test_range_shadow_alias_first_class_and_boolean_indices():
    assert_semantics('''
from pyjs import js
from builtins import range as Range
@js
def range(stop: int) -> list[int]:
    return [stop, 42]
@js
def main():
    for value in range(3):
        print(value)
    for value in Range(True, 4, True):
        print(value)
    try:
        for value in Range(4, 0, False):
            print(value)
    except ValueError:
        print("zero")
    values = Range(3)
    for value in values:
        print(value)
main()
''')


def test_awaited_range_arguments_keep_the_callers_scope():
    assert_semantics('''
import asyncio
from pyjs import js
@js
async def bound(events: list[int], value: int) -> int:
    events.append(value)
    return value
@js
async def main():
    events: list[int] = []
    for value in range(await bound(events, 1), await bound(events, 4)):
        events.append(value * 10)
    for event in events:
        print(event)
asyncio.run(main())
''')


def test_range_safe_integer_edges_and_represented_arguments():
    assert_semantics('''
from pyjs import js, int64
@js
def main():
    for value in range(9007199254740988, 9007199254740991, 2):
        print(value)
    for value in range(-9007199254740988, -9007199254740991, -2):
        print(value)
    for value in range(int64(1), int64(6), int64(2)):
        print(value)
main()
''')

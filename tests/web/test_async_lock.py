import pytest

from pyjs import js
from pyjs.web.async_lock import AsyncLock

pytestmark = pytest.mark.pyjs_web


@js
async def append_locked(lock: AsyncLock, values: list[int], value: int):
    await lock.acquire()
    try:
        values.append(value)
    finally:
        lock.release()


@js
async def test_lock_serializes_overlapping_browser_callbacks():
    lock = AsyncLock()
    values: list[int] = []
    await lock.acquire()
    first = append_locked(lock, values, 1)
    second = append_locked(lock, values, 2)
    assert len(values) == 0
    lock.release()
    third = append_locked(lock, values, 3)
    await first
    await second
    await third
    assert values == [1, 2, 3]
    assert not lock.locked()


@js
async def test_lock_can_be_reused_after_an_exception():
    lock = AsyncLock()
    try:
        await lock.acquire()
        try:
            raise ValueError("request failed")
        finally:
            lock.release()
    except ValueError:
        pass
    assert await lock.acquire()
    lock.release()
    caught = False
    try:
        lock.release()
    except RuntimeError:
        caught = True
    assert caught

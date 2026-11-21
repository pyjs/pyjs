import asyncio
from collections.abc import Callable

from pyjs import js
from pyjs.javascript import Promise


@js
class AsyncLock:
    """Serialize asynchronous browser operations in acquisition order.

    Use ``await acquire()`` with ``release()`` in a ``finally`` block.
    The lock is not reentrant. Browser promises do not support task cancellation;
    cancellation of pending acquisitions is therefore not exposed by this API.
    CPython uses an asyncio lock for host-side tests.
    """

    @js
    def __init__(self):
        self._host_lock = asyncio.Lock()

    @__init__.client
    def __init__(self):
        self._locked = False
        self._waiters: list[Callable[[], None]] = []

    @js
    async def acquire(self) -> bool:
        return await self._host_lock.acquire()

    @acquire.client
    async def acquire(self) -> bool:
        if not self._locked and len(self._waiters) == 0:
            self._locked = True
            return True
        await Promise[None](
            lambda resolve, reject: self._waiters.append(lambda: resolve(None))
        )
        self._waiters.pop(0)
        self._locked = True
        return True

    @js
    def release(self) -> None:
        self._host_lock.release()

    @release.client
    def release(self) -> None:
        if not self._locked:
            raise RuntimeError("Lock is not acquired.")
        self._locked = False
        if len(self._waiters) > 0:
            self._waiters[0]()

    @js
    def locked(self) -> bool:
        return self._host_lock.locked()

    @locked.client
    def locked(self) -> bool:
        return self._locked

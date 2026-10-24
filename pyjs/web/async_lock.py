import asyncio

from pyjs import js


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
        self._waiters: list[callable] = []

    @js
    async def acquire(self) -> bool:
        return await self._host_lock.acquire()

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


AsyncLock.acquire.source("""
if (!this._locked && this._waiters.length === 0) {
    this._locked = true;
    return true;
}
await new Promise(resolve => this._waiters.push(resolve));
this._waiters.shift();
this._locked = true;
return true;
""")

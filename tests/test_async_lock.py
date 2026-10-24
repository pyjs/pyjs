import asyncio

from pyjs.javascript.source import compile_source
from pyjs.tooling.node import Node
from pyjs.web.async_lock import AsyncLock


def test_host_lock_orders_waiters_and_releases_after_failure():
    async def run():
        lock = AsyncLock()
        assert not lock.locked()
        assert await lock.acquire() is True
        completed = []

        async def worker(value):
            await lock.acquire()
            try:
                completed.append(value)
                if value == 1:
                    raise ValueError("test")
            except ValueError:
                completed.append("recovered")
            finally:
                lock.release()

        tasks = [asyncio.create_task(worker(value)) for value in (1, 2)]
        await asyncio.sleep(0)
        assert completed == []
        lock.release()
        tasks.append(asyncio.create_task(worker(3)))
        await asyncio.gather(*tasks)
        assert completed == [1, "recovered", 2, 3]
        assert not lock.locked()
        try:
            lock.release()
        except RuntimeError as error:
            assert str(error) == "Lock is not acquired."
        else:
            raise AssertionError("Double release must fail")

    asyncio.run(run())


def test_browser_lock_orders_waiters_without_barging():
    source = '''
from pyjs import js
from pyjs.web.async_lock import AsyncLock

@js
async def main() -> AsyncLock:
    lock = AsyncLock()
    await lock.acquire()
    assert lock.locked()
    lock.release()
    return lock
'''
    with compile_source(source, module_name="_lock_test") as compiled:
        javascript = compiled.javascript
    # The source exercises every public method before the contended probe.
    assert "async acquire" in javascript
    result = Node().run_javascript(javascript + '''
const lock = await __pyjsEntry__.main();
const completed = [];
await lock.acquire();
const worker = async value => {
    await lock.acquire();
    try {
        completed.push(value);
        if (value === 1) throw new Error('test');
    } catch (error) {
        completed.push('recovered');
    } finally {
        lock.release();
    }
};
const first = worker(1);
const second = worker(2);
if (completed.length) throw new Error('acquired a held lock');
lock.release();
if (lock.locked()) throw new Error('handoff should not report acquired');
const third = worker(3);
await Promise.all([first, second, third]);
if (JSON.stringify(completed) !== '[1,"recovered",2,3]') {
    throw new Error(JSON.stringify(completed));
}
if (lock.locked()) throw new Error('lock leaked');
try {
    lock.release();
    throw new Error('double release succeeded');
} catch (error) {
    if (error.message !== 'Lock is not acquired.') throw error;
}
console.log('passed');
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout == "passed\n"

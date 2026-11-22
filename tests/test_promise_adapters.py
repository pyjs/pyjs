import subprocess

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.source import compile_source
from pyjs.testing.helpers import analyze_module_source
from pyjs.tooling.node import Node


@pytest.fixture(scope="module")
def adapters(tmp_path_factory):
    root = tmp_path_factory.mktemp("promise-adapters")
    # Callback probes supply their own terminal; real xterm is tested in Chrome.
    (root / "pyjs-vendor.js").write_text("export const $fit = {}, $xterm = {};\n")
    with compile_source('''
        from pyjs.node import sleep
        from pyjs.testing.web import next_frame, wait_for_event
        from pyjs.web.xterm import write

        def main() -> list[callable]:
            return [next_frame, sleep, write, wait_for_event]
    ''') as compiled:
        return compiled.javascript, root


def run_adapter_probe(adapters, script):
    javascript, root = adapters
    runtime = Node()
    runtime.ensure()
    result = subprocess.run(
        [runtime.executable, "--input-type=module", "-"],
        input=javascript + '''
import assert from 'node:assert/strict';
const [nextFrame, sleep, write, waitForEvent] = __pyjsEntry__.main();
''' + script,
        cwd=root, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_frame_and_timer_register_immediately_and_resume_in_one_microtask(adapters):
    run_adapter_probe(adapters, '''
let frame, timer, delay;
globalThis.requestAnimationFrame = callback => { frame = callback; return 7; };
globalThis.setTimeout = (callback, milliseconds) => {
    timer = callback; delay = milliseconds; return 8;
};
const events = [];
const framed = nextFrame();
const slept = sleep(12);
assert.equal(typeof frame, 'function');
assert.equal(typeof timer, 'function');
assert.equal(delay, 12);
framed.then(value => events.push(value));
slept.then(value => { assert.equal(value, null); events.push('timer'); });
frame(12.5);
timer();
frame(99);
timer();
assert.deepEqual(events, []);
queueMicrotask(() => events.push('later'));
await Promise.all([framed, slept]);
assert.deepEqual(events, [12.5, 'timer', 'later']);
const failure = new Error('registration failed');
globalThis.requestAnimationFrame = () => { throw failure; };
globalThis.setTimeout = () => { throw failure; };
await assert.rejects(nextFrame(), error => error === failure);
await assert.rejects(sleep(0), error => error === failure);
''')


def test_event_trigger_failure_removes_only_owned_listener(adapters):
    run_adapter_probe(adapters, '''
class Target extends EventTarget {
    listeners = new Set();
    addEventListener(name, callback, options) {
        this.listeners.add(callback);
        super.addEventListener(name, callback, options);
    }
    removeEventListener(name, callback) {
        this.listeners.delete(callback);
        super.removeEventListener(name, callback);
    }
}
const target = new Target();
let unrelated = 0;
const other = () => unrelated++;
target.addEventListener('ready', other);
const failure = new Error('trigger failed');
const rejected = waitForEvent(target, 'ready', {trigger: () => { throw failure; }});
await assert.rejects(rejected, error => error === failure);
assert.deepEqual([...target.listeners], [other]);
target.dispatchEvent(new Event('ready'));
assert.equal(unrelated, 1);

const first = new Event('ready');
const fulfilled = waitForEvent(target, 'ready', {trigger: () => {
    target.dispatchEvent(first);
    throw failure;
}});
assert.equal(await fulfilled, first);
assert.deepEqual([...target.listeners], [other]);

const waiting = waitForEvent(target, 'ready', {trigger: null});
target.dispatchEvent(first);
target.dispatchEvent(new Event('ready'));
assert.equal(await waiting, first);
await assert.rejects(
    waitForEvent({addEventListener() { throw failure; }}, 'ready'),
    error => error === failure,
);
''')


def test_terminal_write_waits_for_its_callback_and_rejects_native_errors(adapters):
    run_adapter_probe(adapters, '''
let callback;
const terminal = {write(text, complete) {
    assert.equal(text, 'captured'); callback = complete;
}};
const pending = write(terminal, 'captured');
assert.equal(typeof callback, 'function');
const events = [];
pending.then(value => { assert.equal(value, null); events.push('written'); });
await Promise.resolve();
assert.deepEqual(events, []);
callback();
callback();
queueMicrotask(() => events.push('later'));
await pending;
assert.deepEqual(events, ['written', 'later']);
const failure = new Error('write failed');
await assert.rejects(write({write() { throw failure; }}, 'text'), error => error === failure);
assert.equal(await write({write(text, complete) { complete(); throw failure; }}, ''), null);
''')


def test_event_wait_rejects_async_triggers_during_compilation():
    with pytest.raises(CompilationError, match="Argument 'trigger' to wait_for_event cannot be async"):
        analyze_module_source('''
            from pyjs import js
            from pyjs.testing.web import wait_for_event
            from pyjs.web.events import EventTarget

            @js
            async def trigger() -> None:
                pass

            @js
            async def main(target: EventTarget):
                await wait_for_event(target, "ready", trigger)
        ''')


@pytest.mark.parametrize("trigger", ["trigger", "None"])
@pytest.mark.parametrize("wait", ["wait_for_event", "wait_for_event if choose else other", "alias"])
def test_event_wait_rejects_erasing_the_optional_trigger_abi(trigger, wait):
    setup = ("alias = other\n                if choose:\n                    alias = wait_for_event"
             if wait == "alias" else "")
    with pytest.raises(CompilationError, match="callable views cannot require optional positional arguments"):
        analyze_module_source(f'''
            from collections.abc import Callable
            from pyjs import js
            from pyjs.javascript import Promise
            from pyjs.testing.web import wait_for_event
            from pyjs.web.events import Event, EventTarget

            @js
            def other(target: EventTarget, name: str,
                      trigger: Callable[[], object] | None) -> Promise[Event]:
                return wait_for_event(target, name, trigger)

            @js
            def indirect(wait: Callable[[EventTarget, str, Callable[[], object] | None], Promise[Event]],
                         target: EventTarget, trigger: Callable[[], object]) -> Promise[Event]:
                return wait(target, "ready", {trigger})

            @js
            def main(target: EventTarget, trigger: Callable[[], object], choose: bool) -> Promise[Event]:
                {setup}
                return indirect({wait}, target, trigger)
        ''')

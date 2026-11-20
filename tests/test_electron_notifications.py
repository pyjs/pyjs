import importlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from pyjs.tooling.node import Node
from pyjs.tooling.node_build import build_node


def test_native_notification_options_events_and_owned_listener_cleanup(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "fixtures/node")
    try:
        module = importlib.import_module("notification_host")
        bundle = build_node(module.main, tmp_path / "notifications.cjs", executable=False)
    finally:
        sys.modules.pop("notification_host", None)
    script = r'''
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const Module = require('node:module'), original = Module._load;
let supported = false, unrelated = 0;
const created = [];
const event = {nativeEvent: true};
const observer = () => unrelated++;
class Notification extends EventEmitter {
    static isSupported() {return supported}
    constructor(options) {
        super();
        created.push(options);
        this.on('failed', observer);
    }
    show() {
        this.emit('show', event);
        this.emit('click', event);
        this.emit('failed', event, 'publication failed');
    }
    close() {this.emit('close', event)}
}
Module._load = function(name, ...args) {
    return name === 'electron' ? {Notification} : original.call(this, name, ...args);
};
const {main} = require(process.argv[1]);
assert.equal(main(), null);
assert.equal(created.length, 0);
supported = true;
const notification = main();
assert(notification instanceof Notification);
assert.deepEqual(created, [
    {title:'Example 🐍', body:'Open the app', id:'schedule-1', groupId:'account-1', silent:true},
    {title:'Defaults', body:'', silent:false},
]);
assert.equal(unrelated, 3);
assert.deepEqual(notification.listeners('failed'), [observer]);
assert.deepEqual(notification.listeners('show'), []);
Notification.isSupported = () => {throw new Error('presenter failed')};
assert.throws(main, /presenter failed/);
Notification.isSupported = () => true;
Notification.prototype.show = () => {throw new Error('show failed')};
assert.throws(main, /show failed/);
'''
    result = subprocess.run([str(Node().executable), "-e", script, bundle],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_async_publication_is_bounded_and_releases_only_owned_listeners(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "fixtures/node")
    try:
        module = importlib.import_module("notification_async")
        bundle = build_node(module.main, tmp_path / "notifications.cjs", executable=False)
    finally:
        sys.modules.pop("notification_async", None)
    script = r'''
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {main} = require(process.argv[1]);
(async () => {
    for (const scenario of ['sync-show', 'async-show', 'failed', 'empty-error',
                            'close', 'timeout', 'throw', 'late-failure']) {
        const notification = new EventEmitter();
        const external = () => {};
        for (const event of ['show', 'failed', 'close']) notification.on(event, external);
        // Native show() dismisses an earlier alert synchronously on some OSes.
        notification.close = () => notification.emit('close', {});
        notification.show = () => {
            if (scenario === 'sync-show') notification.emit('show', {});
            if (scenario === 'async-show') setImmediate(() => notification.emit('show', {}));
            if (scenario === 'failed') notification.emit('failed', {}, 'service failed');
            if (scenario === 'empty-error') notification.emit('failed', {}, '');
            if (scenario === 'close') notification.emit('close', {});
            if (scenario === 'throw') throw new Error('synchronous failure');
            if (scenario === 'late-failure') {
                notification.emit('show', {});
                notification.emit('failed', {}, 'too late');
            }
        };
        if (['sync-show', 'async-show', 'late-failure'].includes(scenario)) {
            await main(notification, 1000);
        } else {
            const message = {failed:'service failed', 'empty-error':'Notification publication failed',
                close:'Notification closed before publication',
                timeout:'Notification publication timed out', throw:'synchronous failure'}[scenario];
            await assert.rejects(main(notification, scenario === 'timeout' ? 10 : 1000), {message});
        }
        for (const event of ['show', 'failed', 'close']) {
            assert.deepEqual(notification.listeners(event), [external], scenario);
            notification.emit(event, {}, 'after settlement');
        }
    }
    for (const timeout of [0, -1, 0.5, NaN, Infinity, 2147483648]) {
        const notification = new EventEmitter();
        notification.show = () => assert.fail('must validate timeout before showing');
        await assert.rejects(main(notification, timeout), /Notification timeout must be/);
        assert.deepEqual(notification.eventNames(), []);
    }
    const notification = new EventEmitter();
    notification.close = () => {};
    notification.show = () => {throw null};
    await assert.rejects(main(notification, 1000), error => error === null);
    assert.deepEqual(notification.eventNames(), []);
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    result = subprocess.run([str(Node().executable), "-e", script, bundle],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_linux_native_notification_lifecycle_on_private_bus(tmp_path, monkeypatch):
    runtime = os.environ.get("PYJS_ELECTRON_RUNTIME")
    if sys.platform != "linux" or not runtime:
        pytest.skip("Set PYJS_ELECTRON_RUNTIME to opt into native Linux notifications")
    if not shutil.which("dbus-run-session"):
        pytest.fail("Native notification acceptance requires dbus-run-session")
    python = Path("/usr/bin/python3")
    dependency = subprocess.run([python, "-c", "import dbus, gi"],
                                text=True, capture_output=True, timeout=10)
    assert dependency.returncode == 0, dependency.stderr
    fixtures = Path(__file__).parent / "fixtures/node"
    monkeypatch.syspath_prepend(fixtures)
    try:
        module = importlib.import_module("notification_native")
        bundle = build_node(module.main, tmp_path / "notifications.cjs", executable=False)
    finally:
        sys.modules.pop("notification_native", None)
    entry = tmp_path / "main.cjs"
    entry.write_text("const {app} = require('electron');\n"
                     "app.whenReady().then(() => require('./notifications.cjs').main({app}))"
                     ".catch(error => {console.error(error); app.exit(1)});\n")
    executable = Path(runtime) / "electron"
    assert executable.is_file(), executable
    environment = os.environ.copy()
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    process = subprocess.Popen([
        "dbus-run-session", "--", python, fixtures / "notification_service.py",
        executable, entry, "--ozone-platform=headless", "--disable-gpu",
        f"--user-data-dir={tmp_path / 'profile'}",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=environment, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=20)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    assert process.returncode == 0, output
    assert "native-timeout" not in output, output
    for expected in ("notify: Native example Body 🐍", "native-shown", "native-acknowledged",
                     "native-clicked", "close: 1", "notify: Failure example",
                     "native-failed"):
        assert expected in output, output
    # This test has small stable event output surrounded by native diagnostic logs.
    assert "require('electron').Notification" in bundle.read_text()

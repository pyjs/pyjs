import importlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from pyjs.tooling.electron import build_application
from pyjs.tooling.node import Node
from pyjs.tooling.node_build import build_node


def test_isolated_notification_requests_lifetime_timeout_and_retry(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "fixtures/node")
    try:
        module = importlib.import_module("notification_isolation")
        bundle = build_node(module.main, tmp_path / "service.cjs", executable=False)
    finally:
        sys.modules.pop("notification_isolation", None)
    script = r'''
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const Module = require('node:module'), original = Module._load;
const children = [], profiles = new Set();
const removals = [];
const app = new EventEmitter();
app.getAppPath = () => '/packaged/app';
app.commandLine = {hasSwitch: () => false};
let mode = 'normal', boot = 'ready', clicks = 0, count = 0;
let holdCleanup = false, quitCalls = 0;
app.quit = () => quitCalls++;
const options = {title: 'Example', body: 'Open the app'};
class Child extends EventEmitter {
    send(message, callback) {
        if (mode === 'send-throw') throw new Error('IPC send failed');
        callback();
        this.messages.push(message);
        if (message.operation === 'identity' || mode === 'wait') return;
        queueMicrotask(() => this.emit('message', {
            event:'reply', id:message.id, value:message.operation === 'support',
            error:mode === 'error' ? 'native failure' : '',
        }));
    }
    kill(signal) {
        assert.equal(signal, 'SIGKILL');
        this.killed = true;
        queueMicrotask(() => {this.emit('exit'); this.emit('close')});
    }
}
Module._load = function(name, ...args) {
    if (name === 'electron') return {app};
    if (name === 'node:fs') return {
        mkdtempSync: () => {const path = '/owned-profile-' + count++; profiles.add(path); return path},
        rm: (path, options, done) => {
            const finish = () => {assert(profiles.delete(path)); done()};
            if (holdCleanup) removals.push(finish); else finish();
        },
    };
    if (name === 'node:child_process') return {spawn: (executable, args, options) => {
        assert.equal(executable, process.execPath);
        assert.equal(options.env.ELECTRON_RUN_AS_NODE, undefined);
        assert.deepEqual(options.stdio, ['ignore', 'ignore', 'ignore', 'ipc']);
        assert.equal(args[0], '/packaged/app');
        assert(args.includes('--pyjs-notification-worker'));
        assert(!args.includes('--no-sandbox'));
        const child = new Child();
        child.messages = [];
        children.push(child);
        if (boot === 'ready') queueMicrotask(() => child.emit('message', {event:'ready'}));
        if (boot === 'error') queueMicrotask(() => child.emit('error', new Error('Spawn failed')));
        return child;
    }};
    return original.call(this, name, ...args);
};
const main = require(process.argv[1]).main;
(async () => {
    const listeners = process.listenerCount('exit');
    const service = main(40);
    assert.equal(children.length, 0);
    assert.equal(await service.supported(), true);
    const first = children[0];
    assert.deepEqual(first.messages[0], {operation:'identity', application_id:'org.example.notes',
        name:'Example Notes', desktop_name:'org.example.notes.desktop'});
    await service.show('one', options, () => clicks++);
    const show = first.messages.find(message => message.operation === 'show');
    first.emit('message', {event:'click', id:show.id, key:'one'});
    assert.equal(clicks, 1);
    await assert.rejects(service.show('one', options, () => {}), /already active/);
    const closing = service.close('one');
    first.emit('message', {event:'click', id:show.id, key:'one'});
    await closing;
    assert.equal(clicks, 1, 'close revokes clicks synchronously');
    await service.show('one', options, () => clicks++);
    first.emit('message', {event:'click', id:show.id, key:'one'});
    assert.equal(clicks, 1, 'reused keys reject stale handle events');
    first.emit('message', {event:'closed', id:show.id, key:'one'});
    await assert.rejects(service.show('one', options, () => {}), /already active/);
    for (let i = 0; i < 140; i++) {
        await service.show('expired', options, () => clicks++);
        const active = first.messages.at(-1);
        first.emit('message', {event:'closed', key:'expired', id:active.id});
        first.emit('message', {event:'click', key:'expired', id:active.id});
    }
    assert.equal(clicks, 1, 'native close revokes callbacks and releases slots');
    mode = 'wait';
    const started = Date.now();
    const stalled = service.show('stalled', options, () => clicks++);
    const concurrent = service.supported();
    const results = await Promise.allSettled([stalled, concurrent]);
    assert(results.every(result => result.status === 'rejected' && /timed out/.test(result.reason.message)));
    assert(Date.now() - started < 500);
    assert(first.killed);
    assert.equal(profiles.size, 0);
    first.emit('message', {event:'click', id:show.id, key:'one'});
    assert.equal(clicks, 1);
    mode = 'normal';
    assert.equal(await service.supported(), true);
    assert.equal(children.length, 2);
    await service.show('two', options, () => clicks++);
    mode = 'error';
    await assert.rejects(service.close('two'), /native failure/);
    assert(children[1].killed);
    mode = 'normal';
    await service.supported();
    mode = 'wait';
    const abandoned = service.show('last', options, () => clicks++);
    service.dispose();
    await assert.rejects(abandoned, /disposed/);
    await assert.rejects(service.supported(), /disposed/);
    await assert.rejects(service.show('last', options, () => {}), /disposed/);
    service.dispose();
    assert.equal(profiles.size, 0);
    assert.equal(app.listenerCount('will-quit'), 0);
    assert.equal(process.listenerCount('exit'), listeners);
    for (const timeout of [0, -1, 0.5, NaN, Infinity, 2147483648]) {
        assert.throws(() => main(timeout), /Notification timeout must be/);
    }
    mode = 'normal';
    const retry = main(40);
    boot = 'error';
    await assert.rejects(retry.supported(), /Spawn failed/);
    boot = 'wait';
    await assert.rejects(retry.supported(), /timed out/);
    boot = 'ready';
    await retry.supported();
    mode = 'send-throw';
    await assert.rejects(retry.supported(), /IPC send failed/);
    mode = 'normal';
    for (let i = 0; i < 128; i++) await retry.show(String(i), options, () => {});
    await assert.rejects(retry.show('overflow', options, () => {}), /full/);
    await retry.close('0');
    await retry.show('replacement', options, () => clicks++);
    const last = children.at(-1), replacement = last.messages.at(-1);
    await retry.close('1');
    mode = 'wait';
    const queued = Array.from({length:128}, () => retry.supported());
    const settled = Promise.allSettled(queued);
    await assert.rejects(retry.supported(), /busy/);
    await assert.rejects(retry.show('busy', options, () => {}), /busy/);
    await assert.rejects(retry.close('replacement'), /busy/);
    last.emit('message', {event:'click', key:'replacement', id:replacement.id});
    assert.equal(clicks, 1, 'even a rejected close revokes its callback');
    assert(!last.killed, 'overload must not invalidate unrelated alerts or requests');
    retry.dispose();
    assert((await settled).every(result => result.status === 'rejected'));
    assert.equal(profiles.size, 0);
    assert.equal(app.listenerCount('will-quit'), 0);
    assert.equal(process.listenerCount('exit'), listeners);
    mode = 'normal';
    holdCleanup = true;
    for (const dispose of [false, true]) {
        const cleanup = main(40);
        await cleanup.supported();
        if (dispose) cleanup.dispose();
        let prevented = 0;
        const before = quitCalls;
        app.emit('will-quit', {preventDefault: () => prevented++});
        app.emit('will-quit', {preventDefault: () => prevented++});
        assert.equal(prevented, 2);
        await assert.rejects(cleanup.supported(), /disposed/);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(quitCalls, before, 'quit waits for asynchronous profile cleanup');
        assert.equal(removals.length, 1, 'exit plus close must clean each profile once');
        removals.shift()();
        assert.equal(quitCalls, before + 1);
        assert.equal(profiles.size, 0);
        assert.equal(app.listenerCount('will-quit'), 0);
        assert.equal(process.listenerCount('exit'), listeners);
    }
    const slowCleanup = main(40);
    await slowCleanup.supported();
    const before = quitCalls;
    app.emit('will-quit', {preventDefault: () => {}});
    await new Promise(resolve => setTimeout(resolve, 2100));
    assert.equal(quitCalls, before + 1, 'broken cleanup cannot prevent application exit');
    removals.shift()();
    assert.equal(quitCalls, before + 1, 'late cleanup cannot trigger another quit');
    assert.equal(profiles.size, 0);
    assert.equal(app.listenerCount('will-quit'), 0);
    assert.equal(process.listenerCount('exit'), listeners);
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    result = subprocess.run([str(Node().executable), '-e', script, bundle],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('dispose', [False, True])
def test_packaged_isolated_notifications_on_private_bus(tmp_path, dispose):
    runtime = os.environ.get('PYJS_ELECTRON_RUNTIME')
    if sys.platform != 'linux' or not runtime:
        pytest.skip('Set PYJS_ELECTRON_RUNTIME to opt into packaged Linux notifications')
    assert shutil.which('dbus-run-session'), 'Install dbus-run-session'
    fixtures = Path(__file__).parent / 'fixtures/node'
    host = tmp_path / 'isolated_notification_acceptance'
    host.mkdir()
    shutil.copyfile(fixtures / 'notification_isolation_native.py', host / 'main.py')

    def render(directory):
        path = directory / 'index.html'
        path.write_text('<p>Notification acceptance</p>')
        return path

    try:
        executable = build_application(tmp_path / 'package', render, runtime=Path(runtime), host=host)
    finally:
        sys.modules.pop('isolated_notification_acceptance.main', None)
        sys.modules.pop('isolated_notification_acceptance', None)
    environment = os.environ.copy()
    environment.pop('ELECTRON_RUN_AS_NODE', None)
    scratch = tmp_path / 'temporary-profiles'
    scratch.mkdir()
    environment['TMPDIR'] = str(scratch)
    environment['PYJS_NOTIFICATION_DISPOSE'] = '1' if dispose else '0'
    process = subprocess.Popen([
        'dbus-run-session', '--', '/usr/bin/python3', fixtures / 'notification_service.py',
        executable, '--ozone-platform=headless', '--disable-gpu',
        f'--user-data-dir={tmp_path / "profile"}',
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=environment, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    assert process.returncode == 0, output
    for expected in ['isolated-responsive', 'isolated-clicked', 'isolated-retryable',
                     'close: 2', 'native-slots-released']:
        assert expected in output, output
    assert output.count('notify: Native example') == 1, output
    assert not list(scratch.glob('pyjs-notifications-*')), output

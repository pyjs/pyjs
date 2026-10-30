import importlib
import subprocess
import sys
from pathlib import Path

from pyjs.tooling.node import Node
from pyjs.tooling.node_build import build_node


def test_close_and_removable_preload_messages(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / 'fixtures/node')
    try:
        module = importlib.import_module('lifecycle_host')
        bundle = build_node(module.main, tmp_path / 'host.cjs', executable=False)
    finally:
        sys.modules.pop('lifecycle_host', None)
    script = r'''
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const Module = require('node:module'), original = Module._load;
const ipc = new EventEmitter(), window = new EventEmitter();
let prevented = false, unrelated = 0;
const other = () => unrelated++;
ipc.on('example:message', other);
Module._load = function(name, ...args) {
    return name === 'electron' ? {ipcRenderer:ipc} : original.call(this, name, ...args);
};
window.webContents = {send: (channel, message) => {
    assert.equal(channel, 'example:message');
    ipc.emit(channel, {sender:'must not reach callback'}, message);
}};
window.close = () => window.emit('close', {preventDefault: () => prevented = true});
(async () => {
    await require(process.argv[1]).main({createWindow: () => window});
    assert.equal(prevented, true);
    assert.equal(unrelated, 3);
    assert.deepEqual(ipc.listeners('example:message'), [other]);
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    result = subprocess.run([str(Node().executable), '-e', script, bundle],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'registered first', 'registered second', 'first hello 🐍',
        'second hello 🐍', 'second still listening',
    ]

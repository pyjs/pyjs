"""Executable Node contract for the Electron session/window bindings."""
import importlib
import subprocess
import sys
from pathlib import Path

from pyjs.tooling.node import Node
from pyjs.tooling.node_build import build_node


def test_session_host_callbacks_and_fetch(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "fixtures/node")
    try:
        module = importlib.import_module("session_host")
        bundle = build_node(module.main, tmp_path / "host.cjs", executable=False)
    finally:
        sys.modules.pop("session_host", None)
    script = r'''
const assert = require('node:assert/strict');
const Module = require('node:module'), original = Module._load;
const events = {}, recorded = {};
const session = {
  protocol: {handle: (scheme, handler) => {assert.equal(scheme, 'https'); recorded.handler = handler}},
  setPermissionCheckHandler: callback => recorded.check = callback,
  setPermissionRequestHandler: callback => recorded.permission = callback,
  webRequest: {onBeforeRequest: callback => recorded.filter = callback},
  fetch: async (request, options) => {
    assert.equal(request.headers.get('X-Desktop'), '1');
    assert.equal(await request.text(), 'original');
    assert.deepEqual(options, {credentials:'include', redirect:'follow', bypassCustomProtocolHandlers:true});
    return new Response('accepted');
  },
};
const electron = {
  session: {fromPartition: name => {assert.equal(name, 'persist:example'); return session}},
  BrowserWindow: class {
    constructor(options) {
      assert.deepEqual(options, {title:'Example', width:1280, height:900, minWidth:400,
        minHeight:300, backgroundColor:'#202124', webPreferences: {
          partition:'persist:example', sandbox:true, contextIsolation:true,
          nodeIntegration:false, webSecurity:true, webviewTag:false}});
      this.webContents = {
        on: (event, callback) => events[event] = callback,
        setWindowOpenHandler: callback => recorded.popup = callback,
      };
    }
    async loadURL(url) {assert.equal(url, 'https://example.test')}
    focus() {recorded.focused = true}
  },
  Menu: {buildFromTemplate: items => items, setApplicationMenu: items => recorded.menu = items},
};
Module._load = function(name, ...args) {
  return name === 'electron' ? electron : original.call(this, name, ...args);
};
const context = {app: {
  commandLine: {hasSwitch: name => {assert.equal(name, 'user-data-dir'); return false}},
  setAppUserModelId: name => assert.equal(name, 'example.desktop'),
  getPath: name => {assert.equal(name, 'appData'); return '/data'},
  setPath: (name, path) => {assert.equal(name, 'userData'); assert.equal(path, '/data/Example')},
}};
(async () => {
  await require(process.argv[1]).main(context);
  assert.equal(recorded.focused, true);
  assert.equal(recorded.check(null, 'camera', 'https://example.test', {}), false);
  recorded.permission(null, 'camera', granted => assert.equal(granted, false));
  for (const url of ['https://example.test', 'https://other.test']) {
    const allowed = url === 'https://example.test';
    let calls = 0;
    recorded.filter({url}, decision => {calls++; assert.deepEqual(decision, {cancel:!allowed})});
    assert.equal(calls, 1);
    for (const event of ['will-navigate', 'will-redirect']) {
      let prevented = false;
      events[event]({preventDefault: () => prevented = true}, url);
      assert.equal(prevented, !allowed);
    }
  }
  let prevented = false;
  events['will-attach-webview']({preventDefault: () => prevented = true});
  assert.equal(prevented, true);
  assert.deepEqual(recorded.popup({url:'https://other.test'}), {action:'deny'});
  recorded.menu[0].submenu[0].click({}, {}, {});
  const response = await recorded.handler(new Request('https://example.test/post', {
    method:'POST', body:'protocol body'}));
  assert.equal(response.status, 201);
  assert.equal(response.headers.get('content-type'), 'text/plain');
  assert.equal(await response.text(), 'protocol body');
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    result = subprocess.run([str(Node().executable), "-e", script, bundle],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "allowed 1 https://example.test", "allowed 2 https://example.test",
        "allowed 3 https://example.test", "allowed 4 https://other.test",
        "allowed 5 https://other.test", "allowed 6 https://other.test",
        "popup https://example.test https://other.test", "account https://example.test",
    ]

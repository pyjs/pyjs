import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pyjs.testing import android_browser as module
from pyjs.testing.android_browser import AndroidBrowser
from pyjs.tooling.android import AndroidDevice


@pytest.fixture(autouse=True)
def lease_directory(tmp_path, monkeypatch, request):
    if "pyjs_android_browser_avd" not in request.fixturenames:
        monkeypatch.setattr(module, 'LEASE_ROOT', tmp_path / 'leases')


def sdk_at(tmp_path, *, running=True):
    other = AndroidDevice('emulator-5554', 'device')
    ours = AndroidDevice('emulator-5558', 'device')
    sdk = Mock(root=tmp_path, adb=Path('adb'))
    sdk.environment.return_value = {}
    sdk.devices.return_value = [other, ours] if running else [other]
    sdk.emulator_name.side_effect = lambda device: 'web-tests' if device == ours else 'native-tests'
    sdk.wait_for_emulator.return_value = ours
    sdk.start_emulator.return_value.poll.return_value = None
    sdk.start_emulator.return_value.wait.return_value = 0
    settings = {('secure', 'default_input_method'): 'test-ime',
                ('secure', 'show_ime_with_hard_keyboard'): 'null',
                ('system', 'user_rotation'): '3', ('system', 'accelerometer_rotation'): '1'}
    forwards, reverse = set(), set()

    def run(command, **kwargs):
        assert command[1:3] == ['-s', ours.identifier], 'touched another device'
        args = command[3:]
        value = ''
        if args[:2] == ['shell', 'settings']:
            action, namespace, key, *values = args[2:]
            if action == 'get':
                value = settings[(namespace, key)]
            else:
                settings[(namespace, key)] = values[0] if action == 'put' else 'null'
        elif args[:3] == ['shell', 'pm', 'path']:
            value = 'package:/system/chrome.apk'
        elif args[0] in ('forward', 'reverse'):
            ports = forwards if args[0] == 'forward' else reverse
            if args[1] == '--remove':
                ports.remove(args[2])
            else:
                value = '45678' if args[0] == 'forward' else '45679'
                ports.add('tcp:' + value)
        return SimpleNamespace(stdout=value)

    sdk.runner.run.side_effect = run
    return sdk, settings, forwards, reverse


@pytest.mark.parametrize('running', [False, True])
@pytest.mark.parametrize('failure', [ValueError, asyncio.CancelledError])
def test_session_releases_only_owned_resources_even_after_body_failure(tmp_path, monkeypatch, running, failure):
    sdk, settings, forwards, reverse = sdk_at(tmp_path, running=running)
    original = settings.copy()
    monkeypatch.setattr(module, 'request_json', lambda url: {'Browser': 'test'})

    async def scenario():
        browser = AndroidBrowser('web-tests', sdk=sdk)
        with pytest.raises(failure, match='application failure'):
            async with browser:
                assert browser.device.identifier == 'emulator-5558'
                assert await browser.reverse(8000) == 'http://127.0.0.1:45679'
                assert forwards and reverse
                raise failure('application failure')
        assert not browser.lease.exists()
        await browser.close()  # Idempotent cleanup must not remove someone else's port.

    asyncio.run(scenario())
    assert settings == original
    assert not forwards and not reverse
    if running:
        sdk.start_emulator.assert_not_called()
    else:
        sdk.start_emulator.return_value.terminate.assert_called_once()
        sdk.start_emulator.return_value.wait.assert_called_once()


def test_boot_failure_stops_started_process_and_releases_lease(tmp_path):
    sdk, _, _, _ = sdk_at(tmp_path, running=False)
    sdk.wait_for_emulator.side_effect = TimeoutError('boot failed')
    browser = AndroidBrowser('web-tests', sdk=sdk)
    with pytest.raises(TimeoutError, match='boot failed'):
        asyncio.run(browser.__aenter__())
    sdk.start_emulator.return_value.terminate.assert_called_once()
    assert not browser.lease.exists()
    sdk.runner.run.assert_not_called()


def test_missing_chrome_restores_settings_and_keeps_original_failure(tmp_path, monkeypatch):
    sdk, settings, _, _ = sdk_at(tmp_path)
    original = settings.copy()
    run = sdk.runner.run.side_effect

    def missing(command, **kwargs):
        if command[3:6] == ['shell', 'pm', 'path']:
            return SimpleNamespace(stdout='')
        return run(command, **kwargs)

    sdk.runner.run.side_effect = missing
    browser = AndroidBrowser('web-tests', sdk=sdk, artifacts=tmp_path)
    monkeypatch.setattr(browser, 'capture_artifacts', AsyncMock(side_effect=OSError('disk full')))
    with pytest.raises(RuntimeError, match='Chrome is missing') as caught:
        asyncio.run(browser.__aenter__())
    assert 'disk full' in str(caught.value.__notes__)
    assert settings == original
    assert not browser.lease.exists()
    sdk.start_emulator.assert_not_called()


def test_active_lease_blocks_second_session_before_any_device_access(tmp_path, monkeypatch):
    sdk, _, _, _ = sdk_at(tmp_path)
    monkeypatch.setattr(module, 'request_json', lambda url: {'Browser': 'test'})

    async def scenario():
        async with AndroidBrowser('web-tests', sdk=sdk) as first:
            sdk.devices.reset_mock()
            with pytest.raises(RuntimeError, match='is leased'):
                async with AndroidBrowser('web-tests', sdk=sdk):
                    pytest.fail('second session entered')
            sdk.devices.assert_not_called()
            assert first.lease.exists()
        assert not first.lease.exists()

    asyncio.run(scenario())


def test_partial_artifacts_preserve_failure_and_browser_diagnostics(tmp_path, monkeypatch):
    sdk, _, _, _ = sdk_at(tmp_path)
    browser = AndroidBrowser('web-tests', sdk=sdk)
    browser.device = AndroidDevice('emulator-5558', 'device')

    async def adb(*args, **kwargs):
        if args[0] == 'exec-out':
            raise OSError('screenshot disconnected')
        return 'device state'

    monkeypatch.setattr(browser, 'adb', adb)
    monkeypatch.setattr(module.AndroidTestSession, 'ui_tree', lambda self: '<hierarchy/>')
    page = SimpleNamespace(inspect=AsyncMock(return_value={'exceptions': ['broken renderer']}),
                           evaluate=AsyncMock(side_effect=[{'height': 240}, '<body>draft</body>']))
    browser.pages.append(page)
    failure = AssertionError('original assertion')

    async def scenario():
        async with browser.artifacts_on_failure(tmp_path, 'case'):
            raise failure

    with pytest.raises(AssertionError) as caught:
        asyncio.run(scenario())
    assert caught.value is failure
    manifest = json.loads((tmp_path / 'case.manifest.json').read_text())
    assert 'screenshot disconnected' in manifest['metadata']['capture_errors']['screen']
    assert {'page-0', 'ui_tree', 'window', 'input_method', 'logcat'} == {
        artifact['name'] for artifact in manifest['artifacts']}
    page_state = json.loads((tmp_path / 'case.page-0.json').read_text())
    assert page_state['exceptions'] == ['broken renderer']
    assert page_state['html'] == '<body>draft</body>'


@pytest.mark.parametrize('close_failure', [ConnectionError, asyncio.CancelledError])
def test_failed_page_initialization_closes_created_target(tmp_path, monkeypatch, close_failure):
    sdk, _, _, _ = sdk_at(tmp_path)
    browser = AndroidBrowser('web-tests', sdk=sdk)
    browser.debug_port = 12345
    monkeypatch.setattr(module, 'request_json', lambda *args: {'id': 'owned', 'webSocketDebuggerUrl': 'ws://test'})
    session = SimpleNamespace(close=AsyncMock(side_effect=close_failure('failed close')), listen=Mock())
    monkeypatch.setattr(module.CDPSession, 'open', AsyncMock(return_value=session))
    monkeypatch.setattr(module.BrowserPage, 'initialize', AsyncMock(side_effect=ValueError('bad page')))
    close = Mock()
    monkeypatch.setattr(module, 'request', close)
    with pytest.raises(ValueError, match='bad page'):
        asyncio.run(browser.new_page())
    close.assert_called_once_with('http://127.0.0.1:12345/json/close/owned')
    session.close.assert_awaited_once()
    assert not browser.targets
    asyncio.run(browser.close())
    assert not browser.pages


@pytest.mark.parametrize('state,expected', [
    ('InsetsSource id=3 type=ime frame=[0,0][720,1280] visible=true', True),
    ('InsetsSource id=3 type=ime visible=true\n'
     'mSource=InsetsSource id=3 type=ime visible=false', None),
    ('InsetsSource id=3 type=ime visible=false\n'
     'mSource=InsetsSource id=3 type=ime visible=true', None),
    ('InsetsSource id=3 type=ime frame=[0,0][0,0] '
     'visibleFrame=[0,624][1280,720] visible=false flags=INVALID\n'
     'InsetsSource id=4 type=navigationBars visible=true\n'
     'mInputShown=false\nmIsInputViewShown=true', False),
])
def test_keyboard_visibility_uses_display_insets(tmp_path, monkeypatch, state, expected):
    sdk, _, _, _ = sdk_at(tmp_path)
    browser = AndroidBrowser('web-tests', sdk=sdk)
    monkeypatch.setattr(browser, 'adb', AsyncMock(return_value=state))
    assert asyncio.run(browser.keyboard_visible()) is expected
    browser.adb.assert_awaited_once_with('shell', 'dumpsys', 'window', 'displays')


def test_unknown_keyboard_state_is_not_silently_accepted_as_hidden(tmp_path, monkeypatch):
    sdk, _, _, _ = sdk_at(tmp_path)
    browser = AndroidBrowser('web-tests', sdk=sdk)
    monkeypatch.setattr(browser, 'adb', AsyncMock(return_value='unrecognized Android output'))
    with pytest.raises(RuntimeError, match='IME visibility'):
        asyncio.run(browser.wait_for_keyboard(False))


def test_real_android_browser_keyboard_and_owned_emulator_cleanup(tmp_path, pyjs_android_browser_avd):
    name = pyjs_android_browser_avd

    async def scenario():
        async with AndroidBrowser(name, artifacts=tmp_path) as browser:
            page = await browser.new_page('data:text/html,<meta name="viewport" '
                'content="width=device-width,initial-scale=1,interactive-widget=resizes-content">'
                '<textarea style="position:fixed;bottom:0;font-size:16px"></textarea>')
            await browser.dismiss_keyboard(page)
            height = await page.evaluate('visualViewport.height')
            await browser.tap(page, 'textarea')
            await browser.wait_for_keyboard()
            await page.wait_for(f'visualViewport.height < {height - 100}', 'IME layout resize')
            await page.session.send('Input.insertText', {'text': 'Draft survives keyboard dismissal'})
            await browser.dismiss_keyboard(page)
            await page.wait_for(f'visualViewport.height >= {height}', 'IME dismissed')
            assert await page.evaluate('document.querySelector("textarea").value') == 'Draft survives keyboard dismissal'
            assert not page.exceptions
            await browser.capture_artifacts(tmp_path, 'accepted')
            process = browser.process
        assert not browser.lease.exists()
        if process is not None:
            assert process.poll() is not None

    asyncio.run(scenario())


@pytest.mark.parametrize('resource', ['forward', 'reverse', 'target'])
@pytest.mark.parametrize('cancel', [False, True])
def test_cancel_during_resource_allocation(tmp_path, monkeypatch, resource, cancel):
    sdk, settings, forwards, reverses = sdk_at(tmp_path)
    original = settings.copy()
    started, release = threading.Event(), threading.Event()
    targets = set()
    original_run = sdk.runner.run.side_effect

    def command(args, **kwargs):
        result = original_run(args, **kwargs)
        if args[3] == resource and args[4] != '--remove':
            started.set()
            assert release.wait(5), 'probe release timeout'
        return result

    sdk.runner.run.side_effect = command

    def request_json(url, *args):
        if '/json/new?' in url:
            targets.add('owned-target')
            if resource == 'target':
                started.set()
                assert release.wait(5), 'probe release timeout'
            return {'id': 'owned-target', 'webSocketDebuggerUrl': 'ws://test'}
        return {'Browser': 'test'}

    def request(url):
        targets.remove(url.rsplit('/', 1)[-1])

    session = SimpleNamespace(close=AsyncMock(), listen=Mock())
    monkeypatch.setattr(module, 'request_json', request_json)
    monkeypatch.setattr(module, 'request', request)
    monkeypatch.setattr(module.CDPSession, 'open', AsyncMock(return_value=session))
    monkeypatch.setattr(module.BrowserPage, 'initialize', AsyncMock())
    monkeypatch.setattr(module.BrowserPage, 'bring_to_front', AsyncMock())
    monkeypatch.setattr(module.BrowserPage, 'wait_for', AsyncMock())

    async def scenario():
        browser = AndroidBrowser('web-tests', sdk=sdk)

        async def operate():
            async with browser:
                if resource == 'reverse':
                    await browser.reverse(8000)
                elif resource == 'target':
                    await browser.new_page()

        task = asyncio.create_task(operate())
        try:
            async with asyncio.timeout(3):
                while not started.is_set():
                    await asyncio.sleep(.001)
            if cancel:
                task.cancel()
                await asyncio.sleep(0)
                assert browser.lease.exists()
                assert not task.done()  # Allocation is still in flight.
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            assert not browser.lease.exists()
            assert settings == original
            assert not forwards and not reverses and not targets
        finally:
            release.set()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await browser.close()

    asyncio.run(scenario())


def test_cancelled_initialization_with_late_cdp_response(tmp_path, monkeypatch):
    sdk, _, _, _ = sdk_at(tmp_path)
    browser = AndroidBrowser('web-tests', sdk=sdk)
    browser.debug_port = 12345
    monkeypatch.setattr(module, 'request_json', lambda *args: {
        'id': 'owned', 'webSocketDebuggerUrl': 'ws://test'})
    close_target = Mock()
    monkeypatch.setattr(module, 'request', close_target)

    async def scenario():
        sent = asyncio.Event()
        responses = asyncio.Queue()

        class Connection:
            def __aiter__(self):
                return self

            async def __anext__(self):
                return await responses.get()

            async def send(self, message):
                self.message = json.loads(message)
                sent.set()

            async def close(self):
                # A server reply can arrive during the close handshake after
                # cancellation has already cancelled the request's future.
                responses.put_nowait(json.dumps({
                    'id': self.message['id'], 'result': {}}))
                await asyncio.sleep(0)

        session = module.CDPSession(Connection())
        monkeypatch.setattr(module.CDPSession, 'open', AsyncMock(return_value=session))
        task = asyncio.create_task(browser.new_page())
        await asyncio.wait_for(sent.wait(), 2)
        task.cancel()
        try:
            await task
        except BaseException as caught:
            assert isinstance(caught, asyncio.CancelledError)
        else:
            pytest.fail('cancel was lost')
        close_target.assert_called_once()

    asyncio.run(scenario())


def test_lease_ignores_sdk_and_temporary_directory(tmp_path, monkeypatch):
    first_sdk, _, _, _ = sdk_at(tmp_path / 'sdk-a')
    second_sdk, _, _, _ = sdk_at(tmp_path / 'sdk-b')
    monkeypatch.setattr(module, 'request_json', lambda url: {'Browser': 'test'})

    async def scenario():
        async with AndroidBrowser('web-tests', sdk=first_sdk) as first:
            monkeypatch.setenv('TMPDIR', str(tmp_path / 'other-temp'))
            second = AndroidBrowser('web-tests', sdk=second_sdk)
            assert second.lease == first.lease
            with pytest.raises(RuntimeError, match='is leased'):
                await second.__aenter__()
            second_sdk.devices.assert_not_called()
            assert first.lease.exists()

    asyncio.run(scenario())


@pytest.mark.parametrize('replacement', [False, True])
def test_lost_lease_preserves_original_error_and_new_owner(tmp_path, monkeypatch, replacement):
    sdk, _, _, _ = sdk_at(tmp_path)
    monkeypatch.setattr(module, 'request_json', lambda url: {'Browser': 'test'})

    async def scenario():
        browser = AndroidBrowser('web-tests', sdk=sdk)
        failure = ValueError('original')
        with pytest.raises(ValueError) as caught:
            async with browser:
                if replacement:
                    (browser.lease / 'owner.json').write_text('{"token":"other-owner"}')
                else:
                    (browser.lease / 'owner.json').unlink()
                    browser.lease.rmdir()
                raise failure
        assert caught.value is failure
        assert browser.lease.exists() == replacement
        if replacement:
            assert json.loads((browser.lease / 'owner.json').read_text())['token'] == 'other-owner'

    asyncio.run(scenario())


def test_failure_is_captured_once_across_nested_contexts(tmp_path, monkeypatch):
    sdk, _, _, _ = sdk_at(tmp_path)
    monkeypatch.setattr(module, 'request_json', lambda url: {'Browser': 'test'})
    browser = AndroidBrowser('web-tests', sdk=sdk, artifacts=tmp_path)
    capture = AsyncMock(return_value=tmp_path / 'manifest.json')
    monkeypatch.setattr(browser, 'capture_artifacts', capture)

    async def scenario():
        async with browser, browser.artifacts_on_failure(tmp_path, 'step'):
            raise ValueError('original')

    with pytest.raises(ValueError, match='original'):
        asyncio.run(scenario())
    capture.assert_awaited_once_with(tmp_path, 'step')


@pytest.mark.parametrize('cancel_count', [1, 2])
def test_cancellation_during_teardown_finishes_all_cleanup(tmp_path, monkeypatch, cancel_count):
    sdk, settings, forwards, reverses = sdk_at(tmp_path, running=False)
    original = settings.copy()
    monkeypatch.setattr(module, 'request_json', lambda url: {'Browser': 'test'})

    async def scenario():
        closing, release = asyncio.Event(), asyncio.Event()
        browser = AndroidBrowser('web-tests', sdk=sdk)

        async def close_session():
            closing.set()
            await release.wait()

        async def operate():
            async with browser:
                browser.pages.append(SimpleNamespace(session=SimpleNamespace(close=close_session)))
                await browser.reverse(8000)

        task = asyncio.create_task(operate())
        try:
            await asyncio.wait_for(closing.wait(), 2)
            for _ in range(cancel_count):
                task.cancel()
                await asyncio.sleep(0)
            assert browser.lease.exists()
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not browser.lease.exists()
            assert settings == original
            assert not forwards and not reverses
            sdk.start_emulator.return_value.terminate.assert_called_once()
        finally:
            release.set()
            await browser.close()

    asyncio.run(scenario())

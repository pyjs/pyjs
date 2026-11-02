import asyncio
import hashlib
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from uuid import uuid4

from pyjs.testing.android import AndroidTestSession
from pyjs.testing.artifacts import Artifact, ArtifactManifest
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.browser import BrowserPage, CDPSession, request, request_json
from pyjs.tooling.command import stop_process

LEASE_ROOT = Path.home() / '.cache' / 'pyjs' / 'android-browser'


async def _finish(awaitable, retain=None):
    # Thread cancellation cannot undo a completed ADB/CDP allocation. Finish
    # the bounded operation and record ownership before propagating cancellation.
    task = asyncio.ensure_future(awaitable)
    cancelled = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise
            cancelled = error
    result = task.result()
    if retain is not None:
        retain(result)
    if cancelled is not None:
        raise cancelled
    return result


class AndroidBrowser:
    """Real Chrome and IME on an explicitly selected, dedicated test AVD.

    Uses BrowserPage for DOM/CDP operations, not Android native view selectors.
    Existing emulator processes survive the session; owned tabs and forwards do
    not. A crashed process leaves a lease that must be inspected before removal.
    """

    def __init__(self, avd: str, *, sdk: AndroidSDK | None = None,
                 headless: bool = True, artifacts: Path | None = None):
        if not avd:
            raise ValueError('An explicit dedicated browser AVD is required')
        self.avd = avd
        self.sdk = sdk or AndroidSDK()
        self.headless = headless
        self.artifact_directory = artifacts
        self.device = None
        self.process = None
        self.pages = []
        self.targets = set()
        self._captured_errors = []
        self.reverse_ports = []
        self.debug_port = None
        self.settings = {}
        self.metadata = {'avd': avd}
        # ADB discovers running emulators by AVD name, independently of which
        # SDK installation or TMPDIR the caller uses. Serialize that same scope.
        digest = hashlib.sha256(avd.encode()).hexdigest()[:24]
        self.lease = LEASE_ROOT / digest
        self.lease_token = uuid4().hex
        self.leased = False

    async def adb(self, *args, text=True):
        if self.device is None:
            raise RuntimeError('Android browser is not connected')
        result = await _finish(asyncio.to_thread(
            self.sdk.runner.run,
            [self.sdk.adb, '-s', self.device.identifier, *args],
            environment=self.sdk.environment(), capture_output=True, text=text,
            timeout=20,
        ))
        return result.stdout.strip() if text else result.stdout

    async def __aenter__(self):
        self.lease.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.lease.mkdir(mode=0o700)
        except FileExistsError:
            raise RuntimeError(
                f'Browser AVD {self.avd!r} is leased: {self.lease}. '
                'Do not remove the lease while its owner is running.'
            ) from None
        self.leased = True
        try:
            (self.lease / 'owner.json').write_text(json.dumps({'pid': os.getpid(), 'avd': self.avd, 'token': self.lease_token}))
            devices = await asyncio.to_thread(self.sdk.devices)
            for device in devices:
                if device.identifier.startswith('emulator-'):
                    name = await asyncio.to_thread(self.sdk.emulator_name, device)
                    if name == self.avd:
                        self.device = device
                        break
            if self.device is None:
                # Retain the Popen before any cancellation point. A cancelled
                # to_thread(start_emulator) could orphan a newly started AVD.
                self.process = self.sdk.start_emulator(self.avd, headless=self.headless)
            self.device = await asyncio.to_thread(
                self.sdk.wait_for_emulator, name=self.avd,
                identifier=self.device.identifier if self.device else None,
            )
            self.metadata['device'] = self.device.identifier
            for key in ('accelerometer_rotation', 'user_rotation', 'show_ime_with_hard_keyboard'):
                namespace = 'secure' if key == 'show_ime_with_hard_keyboard' else 'system'
                self.settings[(namespace, key)] = await self.adb('shell', 'settings', 'get', namespace, key)
            await self.adb('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '1')
            await self.adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
            await self.adb('shell', 'wm', 'dismiss-keyguard')
            package = await self.adb('shell', 'pm', 'path', 'com.android.chrome')
            if not package.startswith('package:'):
                raise RuntimeError('Chrome is missing. Use a dedicated AVD with a Chrome-enabled image.')
            result = await self.adb('shell', 'am', 'start', '-W', '-a',
                                    'android.intent.action.MAIN', '-c',
                                    'android.intent.category.LAUNCHER', '-p', 'com.android.chrome')
            if 'Error:' in result:
                raise RuntimeError(result)
            await _finish(
                self.adb('forward', 'tcp:0', 'localabstract:chrome_devtools_remote'),
                lambda port: setattr(self, 'debug_port', int(port)),
            )
            try:
                async with asyncio.timeout(30):
                    while True:
                        try:
                            version = await asyncio.to_thread(request_json, self.endpoint + '/json/version')
                            break
                        except (OSError, URLError, ValueError):
                            await asyncio.sleep(.2)
            except TimeoutError:
                raise RuntimeError(
                    f'Chrome DevTools is not ready on {self.avd!r}. Complete Chrome first-run '
                    'setup in this test AVD, without signing in, then retry.'
                ) from None
            self.metadata.update(device=self.device.identifier, browser=version,
                                 android_api=await self.adb('shell', 'getprop', 'ro.build.version.sdk'),
                                 ime=await self.adb('shell', 'settings', 'get', 'secure', 'default_input_method'))
            return self
        except BaseException as error:
            await _finish(self._exit(error, "startup"))
            raise

    @property
    def endpoint(self):
        return f'http://127.0.0.1:{self.debug_port}'

    async def reverse(self, host_port: int) -> str:
        """Expose a local HTTP server at an allocated device-loopback port."""
        if not 0 < host_port < 65536:
            raise ValueError('Invalid host port')
        port = int(await _finish(
            self.adb('reverse', 'tcp:0', f'tcp:{host_port}'),
            lambda port: self.reverse_ports.append(int(port)),
        ))
        return f'http://127.0.0.1:{port}'

    async def new_page(self, url='about:blank') -> BrowserPage:
        target = await _finish(
            asyncio.to_thread(request_json, self.endpoint + '/json/new?' + quote(url, safe=''), 'PUT'),
            lambda target: self.targets.add(target['id']),
        )
        page = None

        def retain(session):
            nonlocal page
            page = BrowserPage(session, target['id'])
            self.pages.append(page)

        try:
            # DevTools can accept connections while cold Chrome is still on
            # its Android splash screen and has not started the renderer.
            async with asyncio.timeout(30):
                await _finish(CDPSession.open(target['webSocketDebuggerUrl']), retain)
                await page.initialize()
        except BaseException as error:
            try:
                await _finish(self._failed_page(page, target['id'], error))
            except asyncio.CancelledError:
                pass  # Cleanup finished; preserve the original failure below.
            raise
        await page.bring_to_front()
        await page.wait_for(
            'document.hasFocus() && document.visibilityState === "visible"',
            'Chrome page focus (dismiss native Chrome first-run prompts in the test AVD)',
        )
        return page

    async def _failed_page(self, page, target, error):
        if page is not None:
            try:
                await page.session.close()
            except (Exception, asyncio.CancelledError) as failure:
                error.add_note(f'CDP session cleanup failed: {failure}')
            else:
                self.pages.remove(page)
        try:
            await asyncio.to_thread(request, self.endpoint + '/json/close/' + target)
        except Exception as failure:
            error.add_note(f'Browser target cleanup failed: {failure}')
        else:
            self.targets.discard(target)

    async def tap(self, page: BrowserPage, selector: str):
        """Dispatch a real touch; DOM .click() does not reliably open the IME."""
        await page.evaluate(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"nearest"}})')
        await page.wait_for_frames()
        box = await page._selector_bounds(selector)
        point = {'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2}
        await page.session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [point]})
        await page.session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})

    async def keyboard_visible(self) -> bool | None:
        # Gboard's mIsInputViewShown can remain true after rotation hides its
        # window. WindowManager's IME inset describes what reaches the display.
        state = await self.adb('shell', 'dumpsys', 'window', 'displays')
        values = re.findall(r'\bInsetsSource\b[^\n]*\btype=ime\b[^\n]*\bvisible=(true|false)\b', state)
        if not values:
            raise RuntimeError('Android did not report IME visibility; inspect window artifacts')
        if all(value == 'true' for value in values):
            return True
        if all(value == 'false' for value in values):
            return False
        return None

    async def wait_for_keyboard(self, visible=True, *, timeout=10):
        async with asyncio.timeout(timeout):
            while await self.keyboard_visible() != visible:
                await asyncio.sleep(.1)

    async def dismiss_keyboard(self, page: BrowserPage):
        # A stale IME flag followed by Android Back can close the entire tab.
        # Blurring this owned document cannot navigate another browser page.
        await page.evaluate('document.activeElement?.blur()')
        await self.wait_for_keyboard(False)

    async def rotate(self, page: BrowserPage, *, landscape=False):
        await self.adb('shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0')
        await self.adb('shell', 'settings', 'put', 'system', 'user_rotation', '1' if landscape else '0')
        await page.wait_for(
            '(screen.width > screen.height)' if landscape else '(screen.height > screen.width)',
            'device rotation',
        )

    async def capture_artifacts(self, directory: Path, name: str):
        """Capture each source independently, including the keyboard outside the page."""
        directory.mkdir(parents=True, exist_ok=True)
        prefix = re.sub(r'[^A-Za-z0-9_.-]+', '-', name).strip('-') or 'browser'
        artifacts, errors = [], {}

        async def capture(label, suffix, kind, media_type, read):
            path = directory / f'{prefix}.{suffix}'
            try:
                value = await read()
                if isinstance(value, bytes):
                    path.write_bytes(value)
                else:
                    path.write_text(value, encoding='utf-8')
                artifacts.append(Artifact(label, kind, path.resolve(), media_type))
            except Exception as error:
                errors[label] = f'{type(error).__name__}: {error}'

        await capture('screen', 'png', 'image', 'image/png', lambda: self.adb('exec-out', 'screencap', '-p', text=False))
        for service in ('input_method', 'window'):
            await capture(service, service + '.txt', 'log', 'text/plain',
                          lambda service=service: self.adb('shell', 'dumpsys', service))
        await capture('logcat', 'logcat.txt', 'log', 'text/plain', lambda: self.adb('logcat', '-d', '-t', '400'))
        for index, page in enumerate(self.pages):
            async def inspect(page=page):
                async with asyncio.timeout(10):
                    state = await page.inspect()
                    state['viewport'] = await page.evaluate('({width:innerWidth,height:innerHeight,visual:{width:visualViewport.width,height:visualViewport.height,top:visualViewport.offsetTop},scrollY})')
                    state['html'] = await page.evaluate('document.documentElement.outerHTML')
                    return json.dumps(state, indent=2)
            await capture(f'page-{index}', f'page-{index}.json', 'tree', 'application/json', inspect)
        # UiAutomation can disturb input focus; capture browser state first.
        if self.device:
            native = AndroidTestSession(self.sdk, self.device, 'com.android.chrome', activity='')
            await capture('ui_tree', 'xml', 'tree', 'application/xml', lambda: asyncio.to_thread(native.ui_tree))
        metadata = dict(self.metadata, capture_errors=errors)
        return ArtifactManifest('android-browser', artifacts, metadata).write(directory / f'{prefix}.manifest.json')

    @asynccontextmanager
    async def artifacts_on_failure(self, directory: Path, name: str):
        try:
            yield
        except BaseException as error:
            await self._failure(error, name, directory)
            raise

    async def screenshot(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(await self.adb('exec-out', 'screencap', '-p', text=False))

    async def close(self):
        await _finish(self._close_resources())

    async def _close_resources(self):
        # Cleanup is best effort per resource; one disconnected device must not
        # prevent closing host sessions or releasing the lease.
        async def attempt(action):
            try:
                await action()
            except (Exception, asyncio.CancelledError) as error:
                logging.getLogger(__name__).warning('Android browser cleanup: %s', error)

        for target in self.targets:
            await attempt(lambda target=target: asyncio.to_thread(request, self.endpoint + '/json/close/' + target))
        self.targets.clear()
        for page in self.pages:
            await attempt(page.session.close)
        self.pages.clear()
        if self.device:
            for (namespace, key), value in self.settings.items():
                args = ('delete', namespace, key) if value == 'null' else ('put', namespace, key, value)
                await attempt(lambda args=args: self.adb('shell', 'settings', *args))
            for port in self.reverse_ports:
                await attempt(lambda port=port: self.adb('reverse', '--remove', f'tcp:{port}'))
            if self.debug_port is not None:
                await attempt(lambda: self.adb('forward', '--remove', f'tcp:{self.debug_port}'))
        self.settings.clear()
        self.reverse_ports.clear()
        self.debug_port = None
        if self.process:
            await attempt(lambda: asyncio.to_thread(stop_process, self.process))
            self.process = None
        self.device = None
        if self.leased:
            await attempt(self._release_lease)
            self.leased = False
        self._captured_errors.clear()

    async def _release_lease(self):
        owner = self.lease / 'owner.json'
        try:
            record = json.loads(owner.read_text())
        except FileNotFoundError:
            return
        if record.get('token') != self.lease_token:
            raise RuntimeError('Browser lease ownership changed; leaving it untouched')
        owner.unlink()
        self.lease.rmdir()

    async def _failure(self, error, name, directory=None):
        directory = directory if directory is not None else self.artifact_directory
        if directory is not None and not any(item is error for item in self._captured_errors):
            self._captured_errors.append(error)
            try:
                manifest = await self.capture_artifacts(directory, name)
                error.add_note(f'Android browser artifacts: {manifest}')
            except Exception as capture_error:
                error.add_note(f'Android browser artifact capture failed: {capture_error}')

    async def _exit(self, error, name='failure'):
        try:
            if error is not None:
                await self._failure(error, name)
        finally:
            await self.close()

    async def __aexit__(self, exc_type, error, traceback):
        await _finish(self._exit(error))

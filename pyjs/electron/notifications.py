"""Native main-process notifications; applications own delivery policy."""
from collections.abc import Callable

from pyjs import js
from pyjs.electron import Event


@js.dictionary
class NotificationOptions:
    def __init__(self, title: str, body: str = "", id: str | None = None,
                 groupId: str | None = None, silent: bool = False):
        self.title = title
        self.body = body
        self.silent = silent
        if id is not None:
            self.id = id
        if groupId is not None:
            self.groupId = groupId


@js.native
class NotificationService:
    """Process-isolated native notifications in a packaged Electron app.

    Keys are service-local. show() rejects duplicate live keys and waits for
    native publication, not user viewing. close() revokes clicks immediately
    and waits for native dismissal. A timeout or worker failure rejects pending
    operations and invalidates all handles; the next request starts a worker.
    An uncertain OS alert may remain visible and retries may duplicate it.
    dispose() is final and revokes callbacks without waiting for the OS.
    Native close events release keys. A busy close revokes clicks but retains
    the native handle for a later close retry. Normal app quit waits up to two
    seconds for helper profile cleanup; forced exit may leave temporary files.
    Cleanup reissues app.quit(), so host quit handlers must tolerate repetition.
    """
    async def supported(self) -> bool: ...
    async def show(self, key: str, options: NotificationOptions, clicked: Callable[[], None]) -> None: ...
    async def close(self, key: str) -> None: ...
    def dispose(self) -> None: ...


@js
def notification_service(application_id: str, name: str, timeout_ms: int = 5000,
                         desktop_name: str = "") -> NotificationService:
    """Create a lazy service after app readiness; dispose when no longer needed.

    Requires build --target electron. One helper process serves at most 128
    live notifications. Requests have an event-loop deadline independent of
    native calls. The helper uses an isolated temporary profile, the same
    sandbox settings, and the supplied application identity. OS registration,
    signing and permission requirements still apply. Linux desktop_name defaults
    to application_id + '.desktop'; supply the installed filename if different.
    """
    ...


notification_service.source(r"""
const {app} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 2147483647) {
    throw new RangeError('Notification timeout must be 1..2147483647 milliseconds');
}
if (!application_id || !name || application_id.length > 256 || name.length > 256 || desktop_name.length > 256) {
    throw new Error('Notification application identity is required and must fit 256 characters');
}
let worker = null, ready = false, disposed = false, next = 0;
let quitting = false, quitTimer = null;
const pending = new Map(), items = new Map(), children = new Set();
function unhook() {
    app.removeListener('will-quit', stop);
    process.removeListener('exit', exit);
}
function finishQuit() {
    if (!quitting) return;
    quitting = false;
    clearTimeout(quitTimer);
    unhook();
    app.quit();
}
function fail(error) {
    const child = worker;
    worker = null;
    ready = false;
    items.clear();
    for (const request of pending.values()) {
        clearTimeout(request.timer);
        request.reject(error);
    }
    pending.clear();
    if (child) child.kill('SIGKILL');
}
function send(child, message) {
    try {child.send(message, error => {if (error && child === worker) fail(error)})}
    catch (error) {if (child === worker) fail(error)}
}
function start() {
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'pyjs-notifications-'));
    const args = [app.getAppPath(), '--pyjs-notification-worker', '--user-data-dir=' + profile];
    // Carry test display selection, never debug ports, application arguments,
    // environment-only Node mode, or a sandbox-disabling switch.
    for (const flag of ['ozone-platform', 'ozone-override-screen-size']) {
        if (app.commandLine.hasSwitch(flag)) args.push('--' + flag + '=' + app.commandLine.getSwitchValue(flag));
    }
    const env = {...process.env};
    delete env.ELECTRON_RUN_AS_NODE;
    let child;
    try {
        child = spawn(process.execPath, args, {env, stdio: ['ignore', 'ignore', 'ignore', 'ipc']});
    } catch (error) {
        fs.rmSync(profile, {recursive: true, force: true});
        throw error;
    }
    worker = child;
    children.add(child);
    child.on('error', error => {if (child === worker) fail(error)});
    let cleaning = false;
    const cleanup = () => {
        if (cleaning) return;
        cleaning = true;
        if (child === worker) fail(new Error('Notification worker exited'));
        fs.rm(profile, {recursive: true, force: true, maxRetries: 3, retryDelay: 100}, () => {
            children.delete(child);
            if (disposed && !children.size) {
                unhook();
                finishQuit();
            }
        });
    };
    child.once('exit', cleanup);
    child.once('close', cleanup);
    child.on('message', message => {
        if (child !== worker || !message || typeof message !== 'object') return;
        if (message.event === 'ready') {
            if (ready) return;
            ready = true;
            send(child, {operation: 'identity', application_id, name,
                         desktop_name: desktop_name || application_id + '.desktop'});
            for (const request of pending.values()) send(child, request.message);
        } else if (message.event === 'closed') {
            const item = items.get(message.key);
            if (item && item.id === message.id) items.delete(message.key);
        } else if (message.event === 'click') {
            const item = items.get(message.key);
            if (item && item.id === message.id) item.clicked();
        } else if (message.event === 'reply') {
            const request = pending.get(message.id);
            if (!request) return;
            clearTimeout(request.timer);
            pending.delete(message.id);
            if (message.error) request.reject(new Error(message.error));
            else request.resolve(message.value);
        }
    });
}
function request(operation, key = '', options = null, id = ++next) {
    if (disposed) return Promise.reject(new Error('Notification service is disposed'));
    if (pending.size >= 128) return Promise.reject(new Error('Notification service is busy'));
    return new Promise((resolve, reject) => {
        const message = {operation, key, options, id};
        const timer = setTimeout(() => fail(new Error('Notification request timed out')), timeout_ms);
        pending.set(id, {message, timer, resolve, reject});
        try {
            if (!worker) start();
            else if (ready) send(worker, message);
        } catch (error) {fail(error)}
    });
}
const exit = () => fail(new Error('Application is exiting'));
const stop = event => {
    disposed = true;
    fail(new Error('Application is exiting'));
    if (!children.size) {unhook(); return}
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    quitTimer = setTimeout(finishQuit, 2000);
};
app.on('will-quit', stop);
process.on('exit', exit);
return {
    supported: () => request('support'),
    async show(key, options, clicked) {
        if (typeof key !== 'string' || !key || key.length > 4096) throw new Error('Invalid notification key');
        if (items.has(key)) throw new Error('Notification key is already active');
        if (items.size >= 128) throw new Error('Notification service is full');
        if (JSON.stringify(options).length > 65536) throw new Error('Notification options are too large');
        if (pending.size >= 128) throw new Error('Notification service is busy');
        const id = ++next, item = {id, clicked};
        items.set(key, item);
        try {await request('show', key, options, id)}
        catch (error) {
            if (items.get(key) === item) {
                items.delete(key);
                const child = worker;
                try {await request('close', key)}
                catch (cleanupError) {if (child === worker) fail(cleanupError)}
            }
            throw error;
        }
    },
    async close(key) {
        const item = items.get(key);
        if (!item) return;
        item.clicked = () => {};
        if (pending.size >= 128) throw new Error('Notification service is busy');
        items.delete(key);
        const child = worker;
        try {await request('close', key)}
        catch (error) {if (child === worker) fail(error); throw error}
    },
    dispose() {
        if (disposed) return;
        disposed = true;
        fail(new Error('Notification service is disposed'));
        if (!children.size) unhook();
    },
};
""")


@js.native
class Notification:
    def show(self) -> None: ...
    def close(self) -> None: ...
    def on(self, name: str, callback: Callable[[Event], None]) -> None: ...
    def removeListener(self, name: str, callback: Callable[[Event], None]) -> None: ...


@js.inline("require('electron').Notification.isSupported()")
def is_supported() -> bool:
    """Check native presenter availability, not permission or visible delivery."""
    ...


@js.inline("new (require('electron').Notification)({options})")
def create_notification(options: NotificationOptions) -> Notification:
    """Create after app readiness; retain the object and listen before show().

    IDs and groups apply on macOS and Windows, not Linux. Windows limits each
    to 64 UTF-16 units. OS signing, registration and permission still apply.
    """
    ...


@js.inline("((notification, callback) => {{ const listener = (_event, error) => callback(error); notification.on('failed', listener); return () => notification.removeListener('failed', listener); }})({notification}, {callback})")
def on_failed(notification: Notification, callback: Callable[[str], None]) -> Callable[[], None]:
    """Subscribe to native publication errors and return an owned unsubscriber.

    The native Event is not forwarded. Missing events are not proof of success;
    applications must handle missing asynchronous events and retain retryable work.
    """
    ...


@js
async def show_notification(notification: Notification, timeout_ms: int = 5000) -> None:
    """Wait for native publication, not user viewing; keep the object for clicks.

    Dismiss the object's previous alert before observing a new publication.
    Failure, early close, timeout and synchronous errors reject. Only this
    call's listeners are removed. The caller owns closing an uncertain alert
    after rejection and must not concurrently show the same object.

    The timer bounds event waiting, not synchronous native work. Electron 45
    on Linux publishes through blocking libnotify/D-Bus calls. A slow daemon
    stalls the main event loop; publication can resolve after timeout_ms or
    fail at the native timeout (observed around 25 seconds). This helper
    cannot preempt that call or provide a hard wall-clock deadline.
    """
    ...


show_notification.source("""
if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 2147483647) {
    throw new RangeError('Notification timeout must be 1..2147483647 milliseconds');
}
notification.close();
await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (success, error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        notification.removeListener('show', shown);
        notification.removeListener('failed', failed);
        notification.removeListener('close', closed);
        if (success) resolve(); else reject(error);
    };
    const shown = () => finish(true);
    const failed = (_event, error) => finish(false, new Error(error || 'Notification publication failed'));
    const closed = () => finish(false, new Error('Notification closed before publication'));
    const timer = setTimeout(() => finish(false, new Error('Notification publication timed out')), timeout_ms);
    notification.on('show', shown);
    notification.on('failed', failed);
    notification.on('close', closed);
    try { notification.show(); } catch (error) { finish(false, error); }
});
""")

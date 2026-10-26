"""Exercise compiled host callbacks against Electron-shaped objects."""
from pyjs import js
from pyjs.electron import HostContext, WebPreferences, WindowOptions
from pyjs.electron.session import (
    FetchOptions,
    allow_requests,
    deny_permissions,
    from_partition,
)
from pyjs.electron.window import (
    MenuItem,
    allow_navigation,
    create_window,
    deny_webviews,
    handle_window_requests,
    set_application_menu,
)
from pyjs.web.network import Request, Response


@js
class Controller:
    def __init__(self, origin: str):
        self.origin = origin
        self.count = 0

    def allowed(self, url: str) -> bool:
        self.count += 1
        print("allowed", self.count, url)
        return url == self.origin

    def popup(self, url: str) -> None:
        print("popup", self.origin, url)

    def account(self) -> None:
        print("account", self.origin)

    async def request(self, request: Request) -> Response:
        return Response(await request.text(), status=201,
                        headers={"Content-Type": "text/plain"})


@js
async def main(context: HostContext) -> None:
    context.app.setAppUserModelId("example.desktop")
    if not context.app.commandLine.hasSwitch("user-data-dir"):
        context.app.setPath("userData", context.app.getPath("appData") + "/Example")
    session = from_partition("persist:example")
    deny_permissions(session)
    controller = Controller("https://example.test")
    allow_requests(session, controller.allowed)
    session.protocol.handle("https", controller.request)
    window = create_window(WindowOptions("Example", WebPreferences(partition="persist:example"),
                                         minWidth=400, minHeight=300, backgroundColor="#202124"))
    allow_navigation(window.webContents, controller.allowed)
    deny_webviews(window.webContents)
    handle_window_requests(window.webContents, controller.popup)
    set_application_menu([MenuItem(label="Example", submenu=[MenuItem(
        label="Account", accelerator="CommandOrControl+A", click=controller.account)])])
    controller = Controller("must not replace bound callbacks")
    request = Request("https://example.test/post", method="POST", body="original")
    forwarded = Request(request)
    forwarded.headers.set("X-Desktop", "1")
    response = await session.fetch(forwarded, FetchOptions(
        credentials="include", bypassCustomProtocolHandlers=True))
    assert await response.text() == "accepted"
    await window.loadURL("https://example.test")
    window.focus()

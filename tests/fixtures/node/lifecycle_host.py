from pyjs import js
from pyjs.electron import Event, HostContext, WindowOptions, listen
from pyjs.electron.window import on_close


@js
class Receiver:
    def __init__(self, name: str):
        self.name = name
        print('registered', name)

    def receive(self, message: str) -> None:
        print(self.name, message)


@js
def closing(event: Event) -> None:
    event.preventDefault()


@js
async def main(context: HostContext) -> None:
    window = context.createWindow(WindowOptions('Example'))
    on_close(window, closing)
    first = listen('example:message', Receiver('first').receive)
    second = listen('example:message', Receiver('second').receive)
    window.webContents.send('example:message', 'hello 🐍')
    first()
    first()
    window.webContents.send('example:message', 'still listening')
    second()
    window.webContents.send('example:message', 'disposed')
    window.close()

from pyjs import js
from pyjs.electron import HostContext
from pyjs.electron.notifications import NotificationOptions, notification_service
from pyjs.node import Timer, clear_timeout, set_timeout, sleep


@js
class Check:
    def __init__(self):
        self.beats = 0
        self.clicked = False
        self.timer: Timer | None = None

    def beat(self) -> None:
        self.beats += 1
        self.timer = set_timeout(self.beat, 10)

    def click(self) -> None:
        self.clicked = True

    async def run(self) -> None:
        service = notification_service('org.example.notes', 'Example Notes')
        try:
            assert await service.supported()
            self.beat()
            await service.show('slow', NotificationOptions('Delayed example'), self.click)
            assert self.beats >= 2
            print('isolated-responsive')
            await service.close('slow')
            await service.show('click', NotificationOptions('Native example', 'Body 🐍'), self.click)
            for _ in range(100):
                if self.clicked:
                    break
                await sleep(10)
            assert self.clicked
            print('isolated-clicked')
            await service.close('click')
            try:
                await service.show('failure', NotificationOptions('Failure example'), self.click)
                raise AssertionError('Native failure must reject')
            except Exception as error:
                assert str(error) == 'Notification publication failed'
            assert await service.supported()
            print('isolated-retryable')
        finally:
            clear_timeout(self.timer)
            service.dispose()


@js
async def main(context: HostContext) -> None:
    await Check().run()
    context.app.quit()

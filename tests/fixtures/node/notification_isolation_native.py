from pyjs import js
from pyjs.electron import HostContext
from pyjs.electron.notifications import NotificationOptions, notification_service
from pyjs.node import Timer, clear_timeout, environment, set_timeout, sleep


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
            for title in ['Expired example', 'Dismissed example']:
                await service.show('released', NotificationOptions(title), self.click)
                replaced = False
                for _ in range(300):
                    await sleep(10)
                    try:
                        await service.show('released', NotificationOptions('Delayed example'), self.click)
                        replaced = True
                        break
                    except Exception as error:
                        assert str(error) == 'Notification key is already active'
                assert replaced
                await service.close('released')
            print('native-slots-released')
            try:
                await service.show('failure', NotificationOptions('Failure example'), self.click)
                raise AssertionError('Native failure must reject')
            except Exception as error:
                assert str(error) == 'Notification publication failed'
            assert await service.supported()
            print('isolated-retryable')
        finally:
            clear_timeout(self.timer)
            if environment('PYJS_NOTIFICATION_DISPOSE') == '1':
                service.dispose()


@js
async def main(context: HostContext) -> None:
    await Check().run()
    context.app.quit()

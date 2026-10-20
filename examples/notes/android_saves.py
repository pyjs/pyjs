from pyjs.android.dispatch import Handler, main_looper
from pyjs.java.concurrent import AtomicBoolean, Runnable, Thread
from pyjs.java.errors import SecurityException

from .android_storage import OrderSession, OrderWrite, SaveDriver


class AcknowledgeSave(Runnable):
    def __init__(self, driver: BackgroundSaveDriver, session: OrderSession) -> None:
        self.driver = driver
        self.session = session

    def run(self) -> None:
        self.driver.poll(self.session)


class BackgroundWrite(Runnable):
    def __init__(
        self, write: OrderWrite, handler: Handler, completion: Runnable,
    ) -> None:
        self.write = write
        self.handler = handler
        self.completion = completion
        self.finished = AtomicBoolean(False)

    def run(self) -> None:
        self.write.run()
        # Release/acquire publication also covers a rejected Handler.post:
        # reattachment or retry can consume the result on the main thread.
        self.finished.set(True)
        self.handler.post(self.completion)


class BackgroundSaveDriver(SaveDriver):
    def __init__(self) -> None:
        self.handler = Handler(main_looper())
        self.task: BackgroundWrite | None = None

    def submit(self, session: OrderSession, write: OrderWrite) -> None:
        task = BackgroundWrite(write, self.handler, AcknowledgeSave(self, session))
        self.task = task
        try:
            Thread(task).start()
        except SecurityException:
            self.task = None
            raise

    def poll(self, session: OrderSession) -> None:
        task = self.task
        if task is not None and task.finished.get():
            self.task = None
            session.complete(task.write)

from pyjs.java import format_exception
from pyjs.java.errors import SecurityException
from pyjs.java.io import File, IOException, RandomAccessFile, create_temp_file


class InvalidOrder(ValueError):
    pass


class StorageError(RuntimeError):
    def __init__(self, message: str, path: str = "", operation: str = ""):
        super().__init__(message)
        self.path = path
        self.operation = operation


class Closing:
    def __init__(self, stream: RandomAccessFile) -> None:
        self.stream = stream

    def __enter__(self) -> RandomAccessFile:
        return self.stream

    def __exit__(self, kind: object, error: BaseException | None,
                 trace: object) -> bool:
        if error is None:
            self.stream.close()
        else:
            try:
                self.stream.close()
            except IOException:
                # Keep the original read/write failure when close also fails.
                pass
        return False


class OrderFile:
    def __init__(self, path: str) -> None:
        self.path = path
        self.cleanup_failed = False

    def read(self, expected: list[int]) -> list[int]:
        result: list[int] = []
        file = File(self.path)
        if not file.exists():
            return result
        if file.length() > 1024:
            raise InvalidOrder("Saved order is too large")
        with Closing(RandomAccessFile(self.path, "r")) as stream:
            line = stream.readLine()
            while line is not None:
                value = int(line)
                if str(value) != line or value not in expected or value in result:
                    raise InvalidOrder("Saved order contains an invalid or duplicate note")
                result.append(value)
                line = stream.readLine()
        if len(result) != len(expected):
            raise InvalidOrder("Saved order is incomplete")
        return result

    def write(self, order: list[int]) -> None:
        self.cleanup_failed = False
        destination = File(self.path)
        directory = destination.getParentFile()
        if directory is None:
            raise StorageError("Saved order requires a parent directory", self.path, "create")
        try:
            temporary = create_temp_file("notes-order-", ".tmp", directory)
        except IOException as error:
            raise StorageError(
                "Could not create the saved order: " + str(error), self.path, "create",
            ) from error
        try:
            with Closing(RandomAccessFile(temporary.getPath(), "rw")) as stream:
                for value in order:
                    stream.writeBytes(str(value) + "\n")
                stream.getFD().sync()
            if not temporary.renameTo(destination):
                raise StorageError("Could not replace the saved order", self.path, "replace")
        except IOException as error:
            raise StorageError(
                "Could not write the saved order: " + str(error), self.path, "write",
            ) from error
        finally:
            if temporary.exists():
                self.cleanup_failed = not temporary.delete()


class OrderWrite:
    """A detached snapshot; only its worker writes the result fields."""

    def __init__(self, store: OrderFile, revision: int, order: list[int]) -> None:
        self.store = store
        self.revision = revision
        self.order = list(order)
        self.message = ""
        self.failure_report = ""

    def failed(self, error: BaseException) -> None:
        self.message = "Order not saved. Tap to retry. " + str(error)
        self.failure_report = format_exception(error)

    def run(self) -> None:
        try:
            self.store.write(self.order)
        except (StorageError, SecurityException) as error:
            self.failed(error)
            if self.store.cleanup_failed:
                self.message += " Temporary file cleanup also failed."


class OrderObserver:
    def storage_changed(self) -> None: ...


class SaveDriver:
    def poll(self, session: OrderSession) -> None: ...

    def submit(self, session: OrderSession, write: OrderWrite) -> None:
        write.run()
        session.complete(write)


class OrderSession:
    """Main-thread state; drivers receive detached snapshots, not live lists."""

    def __init__(self, store: OrderFile, driver: SaveDriver | None = None) -> None:
        self.store = store
        self.driver = driver if driver is not None else SaveDriver()
        self.can_save = False
        self.dirty = False
        self.message = ""
        self.failure_report = ""
        self.loaded = False
        self.pending_order: list[int] = []
        self.revision = 0
        self.requested_revision = 0
        self.requested_order: list[int] = []
        self.in_flight: OrderWrite | None = None
        self.observer: OrderObserver | None = None

    def attach(self, observer: OrderObserver) -> None:
        self.observer = observer
        self.driver.poll(self)
        self.notify()

    def detach(self, observer: OrderObserver) -> None:
        if self.observer is observer:
            self.observer = None

    def notify(self) -> None:
        observer = self.observer
        if observer is not None:
            observer.storage_changed()

    def restore(self, expected: list[int]) -> list[int]:
        self.driver.poll(self)
        if not self.loaded:
            order = self.load(expected)
            self.pending_order = order if len(order) > 0 else list(expected)
            self.loaded = True
        return list(self.pending_order)

    def changed(self, order: list[int]) -> None:
        self.pending_order = list(order)
        self.revision += 1
        self.dirty = True

    def load(self, expected: list[int]) -> list[int]:
        self.can_save = False
        try:
            order = self.store.read(expected)
        except (IOException, ValueError, OverflowError, SecurityException) as error:
            self.message = "Could not load saved order: " + str(error)
            self.failure_report = format_exception(error)
            return []
        self.can_save = True
        self.message = ""
        self.failure_report = ""
        return order

    def save(self, order: list[int]) -> None:
        self.driver.poll(self)
        if not self.dirty or not self.can_save:
            return
        self.pending_order = list(order)
        self.requested_order = list(order)
        self.requested_revision = self.revision
        self.start()

    def start(self) -> None:
        if self.in_flight is not None:
            return
        write = OrderWrite(self.store, self.requested_revision, self.requested_order)
        self.in_flight = write
        self.message = "Saving…"
        self.notify()
        try:
            self.driver.submit(self, write)
        except (StorageError, SecurityException) as error:
            write.failed(error)
            self.complete(write)

    def complete(self, write: OrderWrite) -> None:
        # Object identity also rejects a late acknowledgement of a failed
        # attempt after a retry of the same revision has started.
        if self.in_flight is not write:
            return
        self.in_flight = None
        self.message = write.message
        self.failure_report = write.failure_report
        if write.message == "":
            self.dirty = self.revision != write.revision
            if self.requested_revision > write.revision:
                self.start()
        self.notify()

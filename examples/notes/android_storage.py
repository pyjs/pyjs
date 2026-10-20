from pyjs.java import format_exception
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


class OrderSession:
    def __init__(self, store: OrderFile) -> None:
        self.store = store
        self.can_save = False
        self.dirty = False
        self.message = ""
        self.failure_report = ""

    def load(self, expected: list[int]) -> list[int]:
        self.can_save = False
        try:
            order = self.store.read(expected)
        except (IOException, ValueError, OverflowError) as error:
            self.message = "Could not load saved order: " + str(error)
            self.failure_report = format_exception(error)
            return []
        self.can_save = True
        self.message = ""
        self.failure_report = ""
        return order

    def save(self, order: list[int]) -> None:
        if not self.dirty or not self.can_save:
            return
        try:
            self.store.write(order)
        except StorageError as error:
            self.message = "Order not saved. Tap to retry. " + str(error)
            self.failure_report = format_exception(error)
            if self.store.cleanup_failed:
                self.message += " Temporary file cleanup also failed."
            return
        self.dirty = False
        self.message = ""
        self.failure_report = ""

"""JDK UUID values, available unchanged on Android."""
from pyjs import jvm
from pyjs.java import i32


@jvm.native("java/util/UUID")
class UUID:
    def toString(self) -> str: ...
    def version(self) -> i32: ...
    def variant(self) -> i32: ...


@jvm.native("java/util/UUID", name="randomUUID")
def random_uuid() -> UUID:
    """Generate a version-4 UUID using the JDK's cryptographic random source."""
    ...


@jvm.native("java/util/UUID", name="fromString")
def parse_uuid(value: str) -> UUID:
    """Parse using Java's UUID.fromString semantics, not a strict validator."""
    ...

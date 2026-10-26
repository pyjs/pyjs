"""Native UUID values for Java and Android runtimes."""
from pyjs import jvm
from pyjs.java import i32


@jvm.native("java/util/UUID")
class UUID:
    def toString(self) -> str: ...
    def version(self) -> i32: ...
    def variant(self) -> i32: ...


@jvm.native("java/util/UUID", name="randomUUID")
def random_uuid() -> UUID:
    """Generate a version-4 UUID using the platform's cryptographic source."""
    ...


@jvm.native("java/util/UUID", name="fromString")
def parse_uuid(value: str) -> UUID:
    """Use the platform's UUID.fromString rules, not strict validation.

    Acceptance of non-canonical input can differ across Java/Android versions.
    """
    ...

"""Native character decoders for JVM and Android streams."""

from pyjs import jvm


@jvm.native("java/nio/charset/CharsetDecoder")
class CharsetDecoder:
    """A new decoder reports malformed and unmappable input by default."""


@jvm.native("java/nio/charset/Charset")
class Charset:
    def newDecoder(self) -> CharsetDecoder: ...


@jvm.native("java/nio/charset/Charset", name="forName")
def charset_for_name(name: str) -> Charset: ...

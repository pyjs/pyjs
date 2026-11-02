"""Java's basic RFC 4648 Base64 codec (Android API 26+)."""
from pyjs import int8, jvm
from pyjs.java import JVMArray


@jvm.native("java/util/Base64$Encoder")
class Base64Encoder:
    def encodeToString(self, source: JVMArray[int8]) -> str: ...


@jvm.native("java/util/Base64$Decoder")
class Base64Decoder:
    def decode(self, source: str) -> JVMArray[int8]: ...


@jvm.native("java/util/Base64", name="getEncoder")
def base64_encoder() -> Base64Encoder:
    """Encode with the basic alphabet and padding, without line breaks."""
    ...


@jvm.native("java/util/Base64", name="getDecoder")
def base64_decoder() -> Base64Decoder:
    """Decode using Java's rules, which allow omitted final padding.

    This is not a canonical-format validator. Invalid alphabet characters
    raise the native IllegalArgumentException.
    """
    ...

"""Platform message digests for JVM and Android byte streams."""
from pyjs import int8, jvm
from pyjs.java import JVMArray, i32


@jvm.native("java/security/NoSuchAlgorithmException")
class NoSuchAlgorithmException(Exception):
    def getMessage(self) -> str | None: ...


@jvm.native("java/security/MessageDigest")
class MessageDigest:
    def update(self, data: JVMArray[int8]) -> None: ...
    def digest(self) -> JVMArray[int8]: ...
    def reset(self) -> None: ...
    def getDigestLength(self) -> i32: ...


@jvm.native("java/security/MessageDigest", name="getInstance")
def message_digest(algorithm: str) -> MessageDigest:
    """Create a platform digest; unavailable names raise NoSuchAlgorithmException.

    update() accumulates bytes. digest() returns the digest and resets the
    instance; reset() discards pending input without producing a digest.
    Algorithm availability follows the runtime's installed providers.
    """
    ...

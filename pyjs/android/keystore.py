"""Android Keystore key generation parameters (API 23+).

Use provider_key_generator("AES", "AndroidKeyStore") and key_store from
pyjs.java.crypto. Keys are app-scoped and non-exportable; hardware backing
depends on the device. Applications own alias lifetimes and serialize key
creation. Do not regenerate a missing decryption key or back up ciphertext
as though its device-bound key can be restored on another installation.
"""
from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.java import JVMArray, i32
from pyjs.java.crypto import AlgorithmParameterSpec


@jvm.native("android/security/keystore/KeyProperties")
class KeyProperties:
    PURPOSE_ENCRYPT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    PURPOSE_DECRYPT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    BLOCK_MODE_GCM: ClassVar[Annotated[str, jvm.field(writable=False)]] = "GCM"
    ENCRYPTION_PADDING_NONE: ClassVar[Annotated[str, jvm.field(writable=False)]] = "NoPadding"


@jvm.native("android/security/keystore/KeyGenParameterSpec")
class KeyGenParameterSpec(AlgorithmParameterSpec):
    pass


@jvm.native("android/security/keystore/KeyGenParameterSpec$Builder")
class KeyGenParameterSpecBuilder:
    def __init__(self, alias: str, purposes: i32) -> None: ...
    def setKeySize(self, bits: i32) -> KeyGenParameterSpecBuilder: ...
    def setBlockModes(self, modes: JVMArray[str]) -> KeyGenParameterSpecBuilder: ...
    def setEncryptionPaddings(self, paddings: JVMArray[str]) -> KeyGenParameterSpecBuilder: ...
    def build(self) -> KeyGenParameterSpec: ...

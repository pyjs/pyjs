"""Native JCA keys and authenticated ciphers for JVM and Android."""
from typing import Annotated, ClassVar

from pyjs import int8, jvm, uint16
from pyjs.java import JVMArray, i32
from pyjs.java.security import GeneralSecurityException as GeneralSecurityException


@jvm.native("javax/crypto/BadPaddingException")
class BadPaddingException(GeneralSecurityException):
    pass


@jvm.native("javax/crypto/AEADBadTagException")
class AEADBadTagException(BadPaddingException):
    pass


@jvm.native("java/security/Key", interface=True)
class Key:
    def getAlgorithm(self) -> str: ...
    def getEncoded(self) -> JVMArray[int8] | None: ...


@jvm.native("javax/crypto/SecretKey", interface=True)
class SecretKey(Key):
    pass


@jvm.native("java/security/spec/AlgorithmParameterSpec", interface=True)
class AlgorithmParameterSpec:
    pass


@jvm.native("javax/crypto/spec/GCMParameterSpec")
class GCMParameterSpec(AlgorithmParameterSpec):
    def __init__(self, tag_bits: i32, iv: JVMArray[int8]) -> None: ...


@jvm.native("javax/crypto/KeyGenerator")
class KeyGenerator:
    @jvm.native("javax/crypto/KeyGenerator", name="init", invocation="virtual")
    def init_bits(self, bits: i32) -> None: ...

    @jvm.native("javax/crypto/KeyGenerator", name="init", invocation="virtual")
    def init_parameters(self, parameters: AlgorithmParameterSpec) -> None: ...

    def generateKey(self) -> SecretKey: ...


@jvm.native("javax/crypto/KeyGenerator", name="getInstance")
def key_generator(algorithm: str) -> KeyGenerator: ...


@jvm.native("javax/crypto/KeyGenerator", name="getInstance")
def provider_key_generator(algorithm: str, provider: str) -> KeyGenerator: ...


@jvm.native("javax/crypto/Cipher")
class Cipher:
    ENCRYPT_MODE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    DECRYPT_MODE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2

    @jvm.native("javax/crypto/Cipher", name="init", invocation="virtual")
    def init_key(self, mode: i32, key: Key) -> None: ...

    @jvm.native("javax/crypto/Cipher", name="init", invocation="virtual")
    def init_parameters(self, mode: i32, key: Key, parameters: AlgorithmParameterSpec) -> None: ...

    def updateAAD(self, data: JVMArray[int8]) -> None: ...
    def doFinal(self, data: JVMArray[int8]) -> JVMArray[int8]: ...
    def getIV(self) -> JVMArray[int8] | None: ...


@jvm.native("javax/crypto/Cipher", name="getInstance")
def cipher(transformation: str) -> Cipher: ...


@jvm.native("java/security/KeyStore$LoadStoreParameter", interface=True)
class KeyStoreParameter:
    pass


@jvm.native("java/security/KeyStore")
class KeyStore:
    def load(self, parameters: KeyStoreParameter | None) -> None: ...
    def containsAlias(self, alias: str) -> bool: ...
    def getKey(self, alias: str, password: JVMArray[uint16] | None) -> Key | None: ...
    def deleteEntry(self, alias: str) -> None: ...


@jvm.native("java/security/KeyStore", name="getInstance")
def key_store(kind: str) -> KeyStore: ...

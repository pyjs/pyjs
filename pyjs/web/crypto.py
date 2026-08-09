from pyjs import js, js_object
from pyjs.javascript import (
    ArrayBuffer,
    BigInt64Array,
    BigUint64Array,
    DataView,
    Float16Array,
    Float32Array,
    Float64Array,
    Int8Array,
    Int16Array,
    Int32Array,
    Uint8Array,
    Uint8ClampedArray,
    Uint16Array,
    Uint32Array,
)


@js
class Algorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str):
        self.name = name


@js(builtin=True)
class Crypto:
    """WebIDL source: @webref/idl/webcrypto.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Crypto

    Browser support: Chrome 11, Safari 5"""

    def __init__(self):
        self.subtle: SubtleCrypto = None

    def getRandomValues(
        self,
        array: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView,
    ) -> (
        Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
    ): ...

    def randomUUID(self) -> str: ...


crypto = Crypto()
js_object(crypto, builtin=True)


@js(builtin=True)
class CryptoKey:
    """WebIDL source: @webref/idl/webcrypto.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CryptoKey

    Browser support: Chrome 37, Safari 7"""

    def __init__(self):
        self.algorithm: object = None
        self.extractable: bool = False
        self.type: str = ""
        self.usages: object = None


@js
class CryptoKeyPair:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self, privateKey: CryptoKey | None = None, publicKey: CryptoKey | None = None
    ):
        self.privateKey = privateKey
        self.publicKey = publicKey


@js
class EncapsulatedBits:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self, ciphertext: ArrayBuffer | None = None, sharedKey: ArrayBuffer | None = None
    ):
        if ciphertext is not None:
            self.ciphertext = ciphertext
        if sharedKey is not None:
            self.sharedKey = sharedKey


@js
class EncapsulatedKey:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self, ciphertext: ArrayBuffer | None = None, sharedKey: CryptoKey | None = None
    ):
        if ciphertext is not None:
            self.ciphertext = ciphertext
        if sharedKey is not None:
            self.sharedKey = sharedKey


@js
class JsonWebKey:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        alg: str | None = None,
        crv: str | None = None,
        d: str | None = None,
        dp: str | None = None,
        dq: str | None = None,
        e: str | None = None,
        ext: bool | None = None,
        k: str | None = None,
        key_ops: list[str] | None = None,
        kty: str | None = None,
        n: str | None = None,
        oth: list[RsaOtherPrimesInfo] | None = None,
        p: str | None = None,
        q: str | None = None,
        qi: str | None = None,
        use: str | None = None,
        x: str | None = None,
        y: str | None = None,
        *,
        priv: str | None = None,
        pub: str | None = None,
    ):
        self.alg = alg
        self.crv = crv
        self.d = d
        self.dp = dp
        self.dq = dq
        self.e = e
        self.ext = ext
        self.k = k
        self.key_ops = key_ops
        self.kty = kty
        self.n = n
        self.oth = oth
        self.p = p
        self.q = q
        self.qi = qi
        self.use = use
        self.x = x
        self.y = y
        if priv is not None:
            self.priv = priv
        if pub is not None:
            self.pub = pub


@js
class KeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str):
        self.name = name


@js
class RsaOtherPrimesInfo:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, d: str | None = None, r: str | None = None, t: str | None = None):
        self.d = d
        self.r = r
        self.t = t


@js(builtin=True)
class SubtleCrypto:
    """WebIDL source: @webref/idl/webcrypto.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SubtleCrypto

    Browser support: Chrome 37, Safari 11"""

    async def decapsulateBits(
        self,
        decapsulationAlgorithm: object | str,
        decapsulationKey: CryptoKey,
        ciphertext: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ) -> ArrayBuffer: ...

    async def decapsulateKey(
        self,
        decapsulationAlgorithm: object | str,
        decapsulationKey: CryptoKey,
        ciphertext: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        sharedKeyAlgorithm: object | str,
        extractable: bool,
        keyUsages: list[str],
    ) -> CryptoKey: ...

    async def decrypt(
        self,
        algorithm: object | str,
        key: CryptoKey,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ) -> ArrayBuffer: ...

    async def deriveBits(
        self, algorithm: object | str, baseKey: CryptoKey, length: int | None = None
    ) -> ArrayBuffer: ...

    async def deriveKey(
        self,
        algorithm: object | str,
        baseKey: CryptoKey,
        derivedKeyType: object | str,
        extractable: bool,
        keyUsages: list[str],
    ) -> CryptoKey: ...

    async def digest(
        self,
        algorithm: object | str,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ) -> ArrayBuffer: ...

    async def encapsulateBits(
        self, encapsulationAlgorithm: object | str, encapsulationKey: CryptoKey
    ) -> EncapsulatedBits: ...

    async def encapsulateKey(
        self,
        encapsulationAlgorithm: object | str,
        encapsulationKey: CryptoKey,
        sharedKeyAlgorithm: object | str,
        extractable: bool,
        keyUsages: list[str],
    ) -> EncapsulatedKey: ...

    async def encrypt(
        self,
        algorithm: object | str,
        key: CryptoKey,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ) -> ArrayBuffer: ...

    async def exportKey(
        self, format: str, key: CryptoKey
    ) -> ArrayBuffer | JsonWebKey: ...

    async def generateKey(
        self, algorithm: object | str, extractable: bool, keyUsages: list[str]
    ) -> CryptoKey | CryptoKeyPair: ...

    async def getPublicKey(self, key: CryptoKey, keyUsages: list[str]) -> CryptoKey: ...

    async def importKey(
        self,
        format: str,
        keyData: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | JsonWebKey,
        algorithm: object | str,
        extractable: bool,
        keyUsages: list[str],
    ) -> CryptoKey: ...

    async def sign(
        self,
        algorithm: object | str,
        key: CryptoKey,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ) -> ArrayBuffer: ...

    @staticmethod
    def supports(
        operation: str, algorithm: object | str, length: int | None = None
    ) -> bool: ...

    async def unwrapKey(
        self,
        format: str,
        wrappedKey: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        unwrappingKey: CryptoKey,
        unwrapAlgorithm: object | str,
        unwrappedKeyAlgorithm: object | str,
        extractable: bool,
        keyUsages: list[str],
    ) -> CryptoKey: ...

    async def verify(
        self,
        algorithm: object | str,
        key: CryptoKey,
        signature: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ) -> bool: ...

    async def wrapKey(
        self,
        format: str,
        key: CryptoKey,
        wrappingKey: CryptoKey,
        wrapAlgorithm: object | str,
    ) -> ArrayBuffer: ...


@js
class AeadParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self,
        iv: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        name: str,
        additionalData: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
        tagLength: int | None = None,
    ):
        self.iv = iv
        self.name = name
        if additionalData is not None:
            self.additionalData = additionalData
        if tagLength is not None:
            self.tagLength = tagLength


@js
class AesCbcParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        iv: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        name: str,
    ):
        self.iv = iv
        self.name = name


@js
class AesCtrParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        counter: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        length: int,
        name: str,
    ):
        self.counter = counter
        self.length = length
        self.name = name


@js
class AesDerivedKeyParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, length: int, name: str):
        self.length = length
        self.name = name


@js
class AesGcmParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        iv: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        name: str,
        additionalData: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
        tagLength: int | None = None,
    ):
        self.iv = iv
        self.name = name
        if additionalData is not None:
            self.additionalData = additionalData
        if tagLength is not None:
            self.tagLength = tagLength


@js
class AesKeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, length: int, name: str):
        self.length = length
        self.name = name


@js
class AesKeyGenParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, length: int, name: str):
        self.length = length
        self.name = name


@js
class Argon2Params:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self,
        memory: int,
        name: str,
        nonce: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        parallelism: int,
        passes: int,
        associatedData: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
        secretValue: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
        version: int | None = None,
    ):
        self.memory = memory
        self.name = name
        self.nonce = nonce
        self.parallelism = parallelism
        self.passes = passes
        if associatedData is not None:
            self.associatedData = associatedData
        if secretValue is not None:
            self.secretValue = secretValue
        if version is not None:
            self.version = version


@js
class ContextParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self,
        name: str,
        context: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
    ):
        self.name = name
        if context is not None:
            self.context = context


@js
class CShakeParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self,
        name: str,
        outputLength: int,
        customization: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
        functionName: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
    ):
        self.name = name
        self.outputLength = outputLength
        if customization is not None:
            self.customization = customization
        if functionName is not None:
            self.functionName = functionName


@js
class EcdhKeyDeriveParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str, public: CryptoKey):
        self.name = name
        self.public = public


@js
class EcdsaParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, hash: object | str, name: str):
        self.hash = hash
        self.name = name


@js
class EcKeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str, namedCurve: str):
        self.name = name
        self.namedCurve = namedCurve


@js
class EcKeyGenParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str, namedCurve: str):
        self.name = name
        self.namedCurve = namedCurve


@js
class EcKeyImportParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str, namedCurve: str):
        self.name = name
        self.namedCurve = namedCurve


@js
class Ed448Params:
    """WebIDL source: @webref/idl/webcrypto-secure-curves.idl"""

    def __init__(
        self,
        name: str,
        context: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
    ):
        self.name = name
        if context is not None:
            self.context = context


@js
class HkdfParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        hash: object | str,
        info: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
        name: str,
        salt: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ):
        self.hash = hash
        self.info = info
        self.name = name
        self.salt = salt


@js
class HmacImportParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, hash: object | str, name: str, length: int | None = None):
        self.hash = hash
        self.name = name
        if length is not None:
            self.length = length


@js
class HmacKeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, hash: KeyAlgorithm, length: int, name: str):
        self.hash = hash
        self.length = length
        self.name = name


@js
class HmacKeyGenParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, hash: object | str, name: str, length: int | None = None):
        self.hash = hash
        self.name = name
        if length is not None:
            self.length = length


@js
class KangarooTwelveParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self,
        name: str,
        outputLength: int,
        customization: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
    ):
        self.name = name
        self.outputLength = outputLength
        if customization is not None:
            self.customization = customization


@js
class KmacImportParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(self, name: str, length: int | None = None):
        self.name = name
        if length is not None:
            self.length = length


@js
class KmacKeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(self, length: int, name: str):
        self.length = length
        self.name = name


@js
class KmacKeyGenParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(self, name: str, length: int | None = None):
        self.name = name
        if length is not None:
            self.length = length


@js
class KmacParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(
        self,
        name: str,
        outputLength: int,
        customization: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
    ):
        self.name = name
        self.outputLength = outputLength
        if customization is not None:
            self.customization = customization


@js
class Pbkdf2Params:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        hash: object | str,
        iterations: int,
        name: str,
        salt: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer,
    ):
        self.hash = hash
        self.iterations = iterations
        self.name = name
        self.salt = salt


@js
class RsaHashedImportParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, hash: object | str, name: str):
        self.hash = hash
        self.name = name


@js
class RsaKeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, modulusLength: int, name: str, publicExponent: Uint8Array):
        self.modulusLength = modulusLength
        self.name = name
        self.publicExponent = publicExponent


@js
class RsaKeyGenParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, modulusLength: int, name: str, publicExponent: Uint8Array):
        self.modulusLength = modulusLength
        self.name = name
        self.publicExponent = publicExponent


@js
class RsaOaepParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        name: str,
        label: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | None = None,
    ):
        self.name = name
        if label is not None:
            self.label = label


@js
class RsaPssParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(self, name: str, saltLength: int):
        self.name = name
        self.saltLength = saltLength


@js
class TurboShakeParams:
    """WebIDL source: @webref/idl/webcrypto-modern-algos.idl"""

    def __init__(self, name: str, outputLength: int, domainSeparation: int | None = None):
        self.name = name
        self.outputLength = outputLength
        if domainSeparation is not None:
            self.domainSeparation = domainSeparation


@js
class RsaHashedKeyAlgorithm:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        hash: KeyAlgorithm,
        modulusLength: int,
        name: str,
        publicExponent: Uint8Array,
    ):
        self.hash = hash
        self.modulusLength = modulusLength
        self.name = name
        self.publicExponent = publicExponent


@js
class RsaHashedKeyGenParams:
    """WebIDL source: @webref/idl/webcrypto.idl"""

    def __init__(
        self,
        hash: object | str,
        modulusLength: int,
        name: str,
        publicExponent: Uint8Array,
    ):
        self.hash = hash
        self.modulusLength = modulusLength
        self.name = name
        self.publicExponent = publicExponent

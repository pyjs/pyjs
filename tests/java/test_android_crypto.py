import pytest

from pyjs import int8
from pyjs.java import JVMArray
from pyjs.java.base64 import base64_decoder, base64_encoder
from pyjs.java.crypto import (
    AEADBadTagException,
    Cipher,
    GCMParameterSpec,
    GeneralSecurityException,
    cipher,
    key_generator,
    provider_key_generator,
)
from pyjs.java.security import NoSuchAlgorithmException, message_digest

pytestmark = pytest.mark.pyjs_android_jvm


def test_gcm_round_trip_empty_binary_and_associated_data() -> None:
    generator = key_generator("AES")
    generator.init_bits(256)
    key = generator.generateKey()
    assert key.getAlgorithm() == "AES"
    encoded = key.getEncoded()
    assert encoded is not None and len(encoded) == 32
    for value in ["", "AH+A/w==", "8J+agOmbqg=="]:
        data = base64_decoder().decode(value)
        context = base64_decoder().decode("YWNjb3VudA==")
        encrypt = cipher("AES/GCM/NoPadding")
        encrypt.init_key(Cipher.ENCRYPT_MODE, key)
        encrypt.updateAAD(context)
        encrypted = encrypt.doFinal(data)
        iv = encrypt.getIV()
        assert iv is not None and len(iv) == 12
        assert len(encrypted) == len(data) + 16
        decrypt = cipher("AES/GCM/NoPadding")
        decrypt.init_parameters(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, iv))
        decrypt.updateAAD(context)
        assert base64_encoder().encodeToString(decrypt.doFinal(encrypted)) == value


def test_gcm_rejects_changed_ciphertext_iv_context_and_key() -> None:
    generator = key_generator("AES")
    generator.init_bits(256)
    key = generator.generateKey()
    other = generator.generateKey()
    encrypt = cipher("AES/GCM/NoPadding")
    encrypt.init_key(Cipher.ENCRYPT_MODE, key)
    context = base64_decoder().decode("c2NvcGU=")
    encrypt.updateAAD(context)
    encrypted = encrypt.doFinal(base64_decoder().decode("c2VjcmV0"))
    iv = encrypt.getIV()
    assert iv is not None
    for case in range(4):
        data = JVMArray[int8](len(encrypted))
        nonce = JVMArray[int8](len(iv))
        for index in range(len(data)):
            data[index] = encrypted[index]
        for index in range(len(nonce)):
            nonce[index] = iv[index]
        if case == 0:
            data[0] = int8(int(data[0]) ^ 1)
        if case == 1:
            nonce[0] = int8(int(nonce[0]) ^ 1)
        decrypt = cipher("AES/GCM/NoPadding")
        decrypt.init_parameters(Cipher.DECRYPT_MODE, other if case == 3 else key,
                                GCMParameterSpec(128, nonce))
        decrypt.updateAAD(base64_decoder().decode("b3RoZXI=") if case == 2 else context)
        rejected = False
        try:
            decrypt.doFinal(data)
        except AEADBadTagException:
            rejected = True
        assert rejected, "Unauthenticated plaintext must not be returned"


def test_unavailable_crypto_algorithms_and_providers_are_catchable() -> None:
    for case in range(3):
        rejected = False
        try:
            if case == 0:
                cipher("pyjs-missing-cipher")
            elif case == 1:
                key_generator("pyjs-missing-key-generator")
            else:
                provider_key_generator("AES", "pyjs-missing-provider")
        except GeneralSecurityException:
            rejected = True
        assert rejected


def test_digest_failures_use_shared_security_exception_hierarchy() -> None:
    rejected = False
    try:
        message_digest("pyjs-missing-digest")
    except GeneralSecurityException as error:
        assert isinstance(error, NoSuchAlgorithmException)
        assert error.getMessage() is not None
        rejected = True
    assert rejected


def test_invalid_decryption_parameters_are_catchable() -> None:
    generator = key_generator("AES")
    generator.init_bits(256)
    key = generator.generateKey()
    rejected = False
    try:
        decrypt = cipher("AES/GCM/NoPadding")
        decrypt.init_parameters(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, JVMArray[int8](0)))
    except GeneralSecurityException:
        rejected = True
    assert rejected

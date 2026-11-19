import pytest

from pyjs.android.keystore import KeyGenParameterSpecBuilder, KeyProperties
from pyjs.java import JVMArray
from pyjs.java.base64 import base64_decoder, base64_encoder
from pyjs.java.crypto import (
    AEADBadTagException,
    Cipher,
    GCMParameterSpec,
    cipher,
    key_store,
    provider_key_generator,
)
from pyjs.java.uuid import random_uuid

pytestmark = [pytest.mark.pyjs_android_jvm, pytest.mark.pyjs_android_device]


def test_android_key_is_nonexportable_reloadable_and_replacement_cannot_decrypt() -> None:
    alias = "pyjs-test-" + random_uuid().toString()
    store = key_store("AndroidKeyStore")
    store.load(None)
    assert not store.containsAlias(alias)
    assert store.getKey(alias, None) is None
    modes = JVMArray[str](1)
    modes[0] = KeyProperties.BLOCK_MODE_GCM
    paddings = JVMArray[str](1)
    paddings[0] = KeyProperties.ENCRYPTION_PADDING_NONE
    spec = (KeyGenParameterSpecBuilder(alias, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256).setBlockModes(modes).setEncryptionPaddings(paddings).build())
    generator = provider_key_generator("AES", "AndroidKeyStore")
    generator.init_parameters(spec)
    try:
        key = generator.generateKey()
        assert store.containsAlias(alias)
        assert key.getEncoded() is None
        assert key.getAlgorithm() == "AES"
        encrypt = cipher("AES/GCM/NoPadding")
        encrypt.init_key(Cipher.ENCRYPT_MODE, key)
        context = base64_decoder().decode("c2NvcGU=")
        encrypt.updateAAD(context)
        data = encrypt.doFinal(base64_decoder().decode("8J+agOmbqg=="))
        iv = encrypt.getIV()
        assert iv is not None
        loaded = key_store("AndroidKeyStore")
        loaded.load(None)
        restored = loaded.getKey(alias, None)
        assert restored is not None and restored.getEncoded() is None
        decrypt = cipher("AES/GCM/NoPadding")
        decrypt.init_parameters(Cipher.DECRYPT_MODE, restored, GCMParameterSpec(128, iv))
        decrypt.updateAAD(context)
        assert base64_encoder().encodeToString(decrypt.doFinal(data)) == "8J+agOmbqg=="
        loaded.deleteEntry(alias)
        assert loaded.getKey(alias, None) is None
        assert not loaded.containsAlias(alias)
        replacement = generator.generateKey()
        wrong = cipher("AES/GCM/NoPadding")
        wrong.init_parameters(Cipher.DECRYPT_MODE, replacement, GCMParameterSpec(128, iv))
        wrong.updateAAD(context)
        rejected = False
        try:
            wrong.doFinal(data)
        except AEADBadTagException:
            rejected = True
        assert rejected, "Replacing a lost key must not recover old ciphertext"
    finally:
        store.deleteEntry(alias)

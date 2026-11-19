import pytest

from pyjs.android.api import AndroidAPI
from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("case", [
    "gcm_round_trip_empty_binary_and_associated_data",
    "gcm_rejects_changed_ciphertext_iv_context_and_key",
    "unavailable_crypto_algorithms_and_providers_are_catchable",
])
def test_authenticated_ciphers_on_jvm(case, tmp_path):
    result = run_jvm(f'''
from tests.java.test_android_crypto import test_{case}
def main() -> str:
    test_{case}()
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"


def test_crypto_bindings_match_android_sdk():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")
    builder = "Landroid/security/keystore/KeyGenParameterSpec$Builder;"
    expected = {
        "javax/crypto/Cipher": {
            ("getInstance", "(Ljava/lang/String;)Ljavax/crypto/Cipher;"),
            ("init", "(ILjava/security/Key;)V"),
            ("init", "(ILjava/security/Key;Ljava/security/spec/AlgorithmParameterSpec;)V"),
            ("updateAAD", "([B)V"), ("doFinal", "([B)[B"), ("getIV", "()[B"),
        },
        "javax/crypto/KeyGenerator": {
            ("getInstance", "(Ljava/lang/String;)Ljavax/crypto/KeyGenerator;"),
            ("getInstance", "(Ljava/lang/String;Ljava/lang/String;)Ljavax/crypto/KeyGenerator;"),
            ("init", "(I)V"), ("init", "(Ljava/security/spec/AlgorithmParameterSpec;)V"),
            ("generateKey", "()Ljavax/crypto/SecretKey;"),
        },
        "java/security/KeyStore": {
            ("getInstance", "(Ljava/lang/String;)Ljava/security/KeyStore;"),
            ("load", "(Ljava/security/KeyStore$LoadStoreParameter;)V"),
            ("getKey", "(Ljava/lang/String;[C)Ljava/security/Key;"),
            ("containsAlias", "(Ljava/lang/String;)Z"), ("deleteEntry", "(Ljava/lang/String;)V"),
        },
        "java/security/Key": {("getAlgorithm", "()Ljava/lang/String;"), ("getEncoded", "()[B")},
        "javax/crypto/spec/GCMParameterSpec": {("<init>", "(I[B)V")},
        "android/security/keystore/KeyGenParameterSpec$Builder": {
            ("<init>", "(Ljava/lang/String;I)V"), ("setKeySize", f"(I){builder}"),
            ("setBlockModes", f"([Ljava/lang/String;){builder}"),
            ("setEncryptionPaddings", f"([Ljava/lang/String;){builder}"),
            ("build", "()Landroid/security/keystore/KeyGenParameterSpec;"),
        },
    }
    with api:
        for name, methods in expected.items():
            actual = api.require_class(name)
            assert methods <= {(method.name, method.descriptor) for method in actual.methods}, name

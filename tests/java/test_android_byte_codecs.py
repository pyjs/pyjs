import pytest

from pyjs import int8
from pyjs.java import JVMArray
from pyjs.java.base64 import base64_decoder, base64_encoder
from pyjs.java.errors import IllegalArgumentException
from pyjs.java.security import NoSuchAlgorithmException, message_digest

pytestmark = pytest.mark.pyjs_android_jvm


def test_base64_binary_round_trip() -> None:
    encoder = base64_encoder()
    decoder = base64_decoder()
    data = JVMArray[int8](4)
    data[0] = int8(0)
    data[1] = int8(127)
    data[2] = int8(-128)
    data[3] = int8(-1)
    assert encoder.encodeToString(data) == "AH+A/w=="
    restored = decoder.decode("AH+A/w==")
    assert len(restored) == 4
    for index in range(4):
        assert restored[index] == data[index]
    assert encoder.encodeToString(JVMArray[int8](0)) == ""
    assert len(decoder.decode("")) == 0
    assert encoder.encodeToString(decoder.decode("YQ")) == "YQ=="


def test_base64_invalid_input_is_catchable() -> None:
    for value in ["!", "A", "YQ=", "YQ==\n"]:
        rejected = False
        try:
            base64_decoder().decode(value)
        except IllegalArgumentException:
            rejected = True
        assert rejected, value


def test_digest_chunks_reset_and_reuse() -> None:
    encoder = base64_encoder()
    decoder = base64_decoder()
    digest = message_digest("SHA-256")
    assert digest.getDigestLength() == 32
    empty = "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="
    abc = "ungWv48Bz+pBQUDeXa4iI7ADYaOWF3qctBD/YfIAFa0="
    assert encoder.encodeToString(digest.digest()) == empty
    digest.update(decoder.decode("YQ=="))
    digest.update(decoder.decode(""))
    digest.update(decoder.decode("YmM="))
    assert encoder.encodeToString(digest.digest()) == abc
    assert encoder.encodeToString(digest.digest()) == empty
    digest.update(decoder.decode("YQ=="))
    digest.reset()
    assert encoder.encodeToString(digest.digest()) == empty
    digest.update(decoder.decode("YWJj"))
    assert encoder.encodeToString(digest.digest()) == abc
    digest.update(decoder.decode("AH+A/w=="))
    assert encoder.encodeToString(digest.digest()) == "iSc9L3C5MoW7fdtLzuhqU0fKcVk1Ljy90gwj6dHlB9M="


def test_unavailable_digest_is_catchable() -> None:
    rejected = False
    try:
        message_digest("pyjs-nonexistent-digest")
    except NoSuchAlgorithmException:
        rejected = True
    assert rejected

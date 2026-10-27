import pytest

from pyjs.java.errors import IllegalArgumentException
from pyjs.java.uuid import parse_uuid, random_uuid

pytestmark = pytest.mark.pyjs_android_jvm


def test_native_uuid_generation_parsing_and_errors() -> None:
    value = random_uuid()
    assert value.version() == 4 and value.variant() == 2
    text = value.toString()
    assert len(text) == 36
    assert parse_uuid(text).toString() == text
    assert random_uuid().toString() != text
    rejected = False
    try:
        parse_uuid("not-a-uuid")
    except IllegalArgumentException:
        rejected = True
    assert rejected

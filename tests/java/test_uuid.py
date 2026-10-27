"""Native UUID bindings execute on a real JVM and expose platform failures."""
from uuid import UUID

from tests.java.test_exceptions import run_jvm


def test_random_uuid_and_string_round_trip(tmp_path):
    result = run_jvm('''
from pyjs.java.uuid import parse_uuid, random_uuid
def main() -> str:
    first = random_uuid()
    second = random_uuid()
    assert first.version() == 4
    assert first.variant() == 2
    assert parse_uuid(first.toString()).toString() == first.toString()
    return first.toString() + "\\n" + second.toString()
''', tmp_path)
    assert result.returncode == 0, result.stderr
    values = result.stdout.strip().splitlines()
    assert len(values) == 2 and values[0] != values[1]
    for value in values:
        parsed = UUID(value)
        assert str(parsed) == value and parsed.version == 4


def test_invalid_uuid_is_a_catchable_native_exception(tmp_path):
    result = run_jvm('''
from pyjs.java.errors import IllegalArgumentException
from pyjs.java.uuid import parse_uuid
def main() -> str:
    try:
        parse_uuid("not-a-uuid")
    except IllegalArgumentException:
        return "rejected"
    return "unexpected"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "rejected"

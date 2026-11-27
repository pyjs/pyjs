import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import (
    PROPERTY_CAPTURE_CONTRACT,
    PROPERTY_INSTANCE_CAPTURE_CONTRACT,
)
from tests.java.test_exceptions import assert_matches_python


def test_captured_property_results_match_python(tmp_path):
    assert_matches_python(PROPERTY_CAPTURE_CONTRACT.source, tmp_path)


def test_optional_string_isinstance_retains_existing_jvm_boundary():
    with pytest.raises(JVMUnsupported, match="JVM isinstance requires an emitted or native class"):
        transpile_jvm(PROPERTY_INSTANCE_CAPTURE_CONTRACT.source)

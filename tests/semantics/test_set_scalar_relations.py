import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.source import compile_source
from tests.backend_semantics import (
    SCALAR_SET_RELATIONS_CONTRACT,
    SET_CONSTRUCTOR_REPRESENTATION_CONTRACT,
)

from .helpers import assert_semantics, run_python


def test_explicit_set_constructor_preserves_its_item_representation():
    assert_semantics(SET_CONSTRUCTOR_REPRESENTATION_CONTRACT.print_source + "\nmain()\n")


def test_scalar_set_relations_have_an_explicit_javascript_boundary():
    source = SCALAR_SET_RELATIONS_CONTRACT.print_source
    result = run_python(source + "\nmain()\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, "0\n", "")
    with pytest.raises(CompilationError, match="Operator '>' is not supported"):
        with compile_source(source):
            pass

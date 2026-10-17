import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.source import compile_source
from pyjs.native.llvm import transpile_llvm
from tests.backend_semantics import (
    MAPPING_LOOKUP_REPRESENTATION_CONTRACT,
    MAPPING_VIEW_REPRESENTATION_CONTRACT,
    UNION_KEY_REPRESENTATION_CONTRACT,
)

from .helpers import assert_semantics


@pytest.mark.parametrize("name", ["bytes", "str", "float", "Key"])
@pytest.mark.parametrize("native", [False, True])
def test_union_query_scalar_shortcut_does_not_admit_application_namesakes(name, native):
    source = f'''
from pyjs import js, int8
@js
class {name}:
    pass
@js
def main() -> int:
    values: dict[int8 | {name}, int] = {{int8(1): 2}}
    key = {name}()
    return int(key in values)
'''
    with pytest.raises(CompilationError, match="representation"):
        if native:
            transpile_llvm(source)
        else:
            with compile_source(source):
                pass


@pytest.mark.parametrize("contract", [MAPPING_VIEW_REPRESENTATION_CONTRACT, MAPPING_LOOKUP_REPRESENTATION_CONTRACT,
                                     UNION_KEY_REPRESENTATION_CONTRACT])
def test_shared_mapping_representation_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


@pytest.mark.parametrize("expression", ["values[int16(1)]", "int16(1) in values"])
def test_union_queries_reject_conflicting_representations(expression):
    with pytest.raises(CompilationError, match="representation"):
        with compile_source(f'''
from pyjs import js, int8, int16
@js
def main() -> int:
    values: dict[int8 | None, int] = {{int8(1): 2}}
    return int({expression})
'''):
            pass


@pytest.mark.parametrize("query", ["1.0", "True", "1.0 if len(values) else None"])
@pytest.mark.parametrize("key_type,stored", [("int64", "int64(1)"), ("int8", "int8(1)")])
@pytest.mark.parametrize("expression", ["values[query]", "query in values", "values.get(query, 0)"])
def test_union_queries_require_a_matching_represented_member(query, key_type, stored, expression):
    # int64 is BigInt-backed in JS. No corresponding float/bool union arm means
    # that merely finding no conflicting representation cannot justify lookup.
    with pytest.raises(CompilationError, match="incompatible (?:key|item) representation"):
        with compile_source(f'''
from pyjs import js, int8, int64
@js
def main() -> int:
    values: dict[{key_type} | None, int] = {{{stored}: 7}}
    query = {query}
    return int({expression})
'''):
            pass


def test_compound_union_queries_keep_their_existing_diagnostic():
    # The scalar shortcut does not establish value-based compound key equality
    # in JS. Do not silently expose the separate tuple-key runtime limitation.
    with pytest.raises(CompilationError, match="incompatible key representation"):
        with compile_source('''
from pyjs import js, int8
@js
def main() -> int:
    values: dict[tuple[int8, str] | None, int] = {(int8(1), "a"): 5}
    return values[(int8(1), "a")]
'''):
            pass

import pytest

from pyjs import int8, int64
from pyjs.analysis.objects import UnionType
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import TUPLE_ITERATOR_DEFAULT_CONTRACT


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_tuple_iterator_default_result_has_one_shape_and_matching_representation(environment):
    options = {"environment": environment} if environment is not None else {}
    with analyze_source(TUPLE_ITERATOR_DEFAULT_CONTRACT.source, wrap=False, **options) as analysis:
        scope = analysis.entry_point.container.search("tuple_iterator_defaults").scope
        for name, expected in (("present", tuple[int8, ...]), ("absent", tuple[int8, ...]),
                               ("no_items", tuple[int8, ...]), ("fixed_present", tuple[int64, ...]),
                               ("fixed_absent", tuple[int64, ...])):
            value = scope.search(name)
            assert value.cls.tuple_variadic
            assert value.cls.generic_name == "tuple"
            assert value.representation == annotation_representation(expected)


@pytest.mark.parametrize("fallback", ["(True,)", "(1.0,)", "('one',)", "([1],)"])
def test_tuple_iterator_defaults_do_not_merge_different_item_types(fallback):
    with analyze_source(f'''from pyjs import js
@js
def main() -> int:
    rows: list[tuple[int, ...]] = [(1,)]
    result = next(iter(rows), {fallback})
    return 0
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert isinstance(analysis.entry_point.scope.search("result").cls, UnionType)

import ast
import subprocess
import sys
from textwrap import dedent

import pytest

from pyjs import int8
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import at


@pytest.mark.parametrize("backend", ["js", "native", "java", "webassembly"])
def test_explicit_sequence_constructors_keep_declared_representation(backend):
    from pyjs import int64
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
    from tests.backend_semantics import SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT

    environments = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                    "webassembly": WEBASSEMBLY_ENVIRONMENT}
    options = {} if backend == "js" else {"environment": environments[backend]}
    with analyze_source(SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT.source,
                        wrap=False, **options) as analysis:
        scope = analysis.entry_point.container.search("sequence_constructor_representations").scope
        for name, expected in (("source", list[int8]), ("plain", list[int8]),
                               ("nullable", list[int8 | None]), ("variable", tuple[int8, ...]),
                               ("optional", tuple[int8 | None, ...]), ("fixed", tuple[int8, int64]),
                               ("fixed_small", tuple[int8]), ("empty", list[int8]),
                               ("from_cursor", list[int8 | None]),
                               ("literal_list", list[int8]), ("literal_nullable", list[int8 | None]),
                               ("literal_tuple", tuple[int8, ...]), ("literal_fixed", tuple[int8, int8]),
                               ("literal_mixed", tuple[int8, int64]), ("literal_set", set[int8]),
                               ("named_list", list[int8]), ("named_tuple", tuple[int8, int8]),
                               ("annotated", list[int8]), ("matching_spread", list[int8]),
                               ("fresh_spread", list[int8]), ("nested_spread", tuple[int8, ...]),
                               ("empty_spread", list[int8])):
            assert scope.search(name).representation == annotation_representation(expected), name
        assert scope.search("ordinary").representation is None
        parameter = analysis.entry_point.container.search("constructor_parameter").scope.search("value")
        assert parameter.representation is None


@pytest.mark.parametrize("backend", ["js", "native", "java", "webassembly"])
def test_union_storage_conversion_keeps_source_representation(backend):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
    from tests.backend_semantics import UNION_STORAGE_COERCION_CONTRACT

    environments = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                    "webassembly": WEBASSEMBLY_ENVIRONMENT}
    options = {} if backend == "js" else {"environment": environments[backend]}
    with analyze_source(UNION_STORAGE_COERCION_CONTRACT.source,
                        wrap=False, **options) as analysis:
        function = analysis.entry_point.container.search("check_union_storage")
        scope = function.scope
        assert scope.search("value").representation is None
        for name, expected in (("slot", int8 | str | None),
                               ("literal", list[int8 | str | None]),
                               ("copied", list[int8 | str | None]),
                               ("fixed", tuple[int8 | str | None, str])):
            assert scope.search(name).representation == annotation_representation(expected), name


def test_union_storage_conversion_does_not_guess_erased_js_numeric_kind():
    with pytest.raises(CompilationError, match="cannot distinguish int from float"):
        with analyze_source('''from pyjs import js, int8, float32
@js
def convert(value: int | float) -> int8 | float32:
    return value
@js
def main() -> int:
    convert(1)
    return 0
''', wrap=False):
            pass


@pytest.mark.parametrize("backend", ["js", "native", "java", "webassembly"])
@pytest.mark.parametrize("source, target", [
    ("[int8(127)]", "list[int16]"),
    ("[int8(127)]", "list[int]"),
    ("[int8(127)]", "list[int16 | None]"),
    ("[int8(127)]", "list[int | None]"),
    ("[127]", "list[int8 | None]"),
    ("(int8(127),)", "tuple[int16]"),
    ("(int8(127),)", "tuple[int]"),
    ("[[int8(127)]]", "list[list[int] | None]"),
])
def test_explicit_sequence_constructors_cannot_relabel_stored_items(backend, source, target):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environments = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                    "webassembly": WEBASSEMBLY_ENVIRONMENT}
    options = {} if backend == "js" else {"environment": environments[backend]}
    with pytest.raises(CompilationError, match="incompatible .*representation") as caught:
        with analyze_source(f'''from pyjs import js, int8, int16
@js
def main() -> int:
    source = {source}
    result = {target}(source)
    return len(result)
''', wrap=False, **options):
            pass
    assert caught.value.lineno == 5


@pytest.mark.parametrize("backend", ["js", "native", "java", "webassembly"])
@pytest.mark.parametrize("destination", [
    "result = list[int8]((*source, 1))",
    "result = tuple[int8, ...]((0, *source))",
    "result = list[int8]([*source, 1])",
    "result: list[int8] = [*source, 1]",
])
def test_starred_literal_cannot_relabel_existing_iterable(backend, destination):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environments = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                    "webassembly": WEBASSEMBLY_ENVIRONMENT}
    options = {} if backend == "js" else {"environment": environments[backend]}
    with pytest.raises(CompilationError, match="incompatible .*representation") as caught:
        with analyze_source(f'''from pyjs import js, int8
@js
def main() -> int:
    source = [127, 1]
    {destination}
    return len(result)
''', wrap=False, **options):
            pass
    assert caught.value.lineno == 5


@pytest.mark.parametrize("backend", ["js", "native", "java", "webassembly"])
@pytest.mark.parametrize("expression, message", [
    ("tuple[int8, float32]((*(1, 2.0), 3))", "more items"),
    ("tuple[int8, float32]((*(1,),))", "fewer items"),
    ("tuple[int8, str]((*(1, 2),))", "declared type"),
    ("tuple[int8, str]((1, 2))", "declared type"),
    ("tuple[int8, float32]((*source,))", "statically sized tuple spreads"),
    ("tuple[int8, float32]((*pair,))", "incompatible nested representation"),
])
def test_fixed_tuple_spreads_validate_positions_and_existing_storage(backend, expression, message):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environments = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                    "webassembly": WEBASSEMBLY_ENVIRONMENT}
    options = {} if backend == "js" else {"environment": environments[backend]}
    with pytest.raises(CompilationError, match=message) as caught:
        with analyze_source(f'''from pyjs import js, int8, float32
@js
def main() -> int:
    source = [1, 2.0]
    pair = (1, 2.0)
    result = {expression}
    return len(result)
''', wrap=False, **options):
            pass
    assert caught.value.lineno == 6


@pytest.mark.parametrize("backend", ["js", "native", "java", "webassembly"])
def test_explicit_set_constructor_and_copy_keep_declared_representation(backend):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environments = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                    "webassembly": WEBASSEMBLY_ENVIRONMENT}
    options = {} if backend == "js" else {"environment": environments[backend]}
    with analyze_source('''
from pyjs import js, int8
@js
def main() -> int:
    source: list[int8 | None] = [int8(127), None]
    values = set[int8 | None](source)
    copied = values.copy()
    return len(copied)
''', wrap=False, **options) as analysis:
        scope = analysis.entry_point.scope
        assert scope.search("source").representation == annotation_representation(list[int8 | None])
        for name in ("values", "copied"):
            assert scope.search(name).representation == annotation_representation(set[int8 | None])


@pytest.mark.parametrize("base, parameter", [("Box[list[int]]", "T"), ("dict[str, list[int]]", "V")])
def test_nested_generic_base_resolves_dependencies_on_a_cold_js_cache(base, parameter):
    source = f'''
from pyjs import js
@js
class Box[T]:
    pass
@js
class Child({base}):
    pass
@js
def main() -> int:
    return 0
'''
    # Builtin specializations are cached per interpreter. Both first analysis
    # and reuse must resolve the same nested base, without earlier tests warming it.
    script = f'''
from pyjs.analysis.source import analyze_source
for attempt in range(2):
    with analyze_source({source!r}, wrap=False) as analysis:
        child = analysis.entry_point.container.search("Child")
        member = child.super.generic_types[{parameter!r}]
        assert member.generic_name == "list"
        assert member.generic_types["V"].name == "int"
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("name", ["tuple", "Bag"])
@pytest.mark.parametrize("expression", ["consume({name}())", "values.extend({name}())"])
def test_application_tuple_cannot_bypass_iterable_item_constraints(native, name, expression):
    source = f'''
        from collections.abc import Iterable, Iterator
        from pyjs import js
        @js
        class {name}:
            def __iter__(self) -> Iterator[str]:
                return iter(["a", "b"])
        @js
        def consume(items: Iterable[int]) -> int:
            total = 0
            for item in items:
                total += item * 2
            return total
        @js
        def main() -> int:
            values: list[int] = []
            {expression.format(name=name)}
            return 0
    '''
    options = {"environment": NATIVE_ENVIRONMENT} if native else {}
    with pytest.raises(CompilationError, match=r"expects Iterable\[int\]"):
        with analyze_source(source, wrap=False, **options):
            pass


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("parameter", ["int8", "int"])
def test_static_array_sort_key_uses_item_representation(native, parameter):
    source = f'''
        from pyjs import js, StaticArray, int8

        @js
        def key(value: {parameter}) -> {parameter}:
            return value + 1

        @js
        def main() -> int:
            values = StaticArray[int8, 2]([1, 127])
            values.sort(key=key)
            return int(values[0])
    '''
    options = {"environment": NATIVE_ENVIRONMENT} if native else {}
    if parameter == "int8":
        with analyze_source(source, wrap=False, **options) as analysis:
            assert analysis.entry_point.return_type.name == "int"
    else:
        with pytest.raises(CompilationError, match="Sort items and key parameter use incompatible representations") as caught:
            with analyze_source(source, wrap=False, **options):
                pass
        assert caught.value.lineno == 11


@pytest.mark.parametrize("native", [False, True])
def test_empty_iterable_fallbacks_follow_peer_constraints(native):
    source = '''
        from collections.abc import Iterable
        from pyjs import js, int8

        @js
        def choose[T](values: Iterable[T], initial: T) -> T:
            for value in values:
                return value
            return initial

        @js
        def empty():
            return iter(())

        @js
        def main():
            cursor = empty()
            items = list(())
            members = set(())
            return choose((), int8(127)) + int8(1)
    '''
    options = {"environment": NATIVE_ENVIRONMENT} if native else {}
    with analyze_source(source, wrap=False, **options) as analysis:
        module = analysis.entry_point.container
        assert module.search("empty").return_type.name == "Iterator__object"
        assert analysis.entry_point.scope.search("items").cls.name == "list__object"
        assert analysis.entry_point.scope.search("members").cls.name == "set__object"
        assert analysis.entry_point.return_type.name == "int"
        assert analysis.entry_point.return_numeric_format.bits == 8


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("item, parameter", [("int", "int8"), ("int8", "int"),
                                           ("list[int8]", "list[int]")])
def test_in_place_sort_key_requires_matching_item_representation(native, item, parameter):
    source = f'''
        from pyjs import js, int8

        @js
        def key(value: {parameter}) -> int:
            return 0

        @js
        def main(values: list[{item}]) -> None:
            values.sort(key=key)
    '''
    options = {"environment": NATIVE_ENVIRONMENT} if native else {}
    with pytest.raises(CompilationError, match="Sort items and key parameter use incompatible representations") as caught:
        with analyze_source(source, wrap=False, **options):
            pass
    assert caught.value.lineno == 10


def test_mapping_consumer_retains_source_without_a_synthetic_keys_call():
    source = '''
        def main(values: dict[int, str]) -> int:
            return sum(values)
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main(values: dict__int_str) -> int:
                block entry:
                    return sum(values)
        ''').rstrip()
    at(source, '''
        def main(values: dict__int_str) -> int:
            return sum(values)
    ''', '''
        export function main(values) {
            return ((values,total)=>{for(const value of values)total=total+value;return total;})(values.keys(),0);
        }
    ''')


def test_imported_builtin_view_alias_keeps_the_canonical_type():
    with analyze_source('''
        from collections.abc import ItemsView as View

        def make() -> View[str, int]:
            return {"a": 1}.items()

        def main() -> int:
            return len(make())
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def make() -> ItemsView[str, int]:
                block entry:
                    return new[caller] dict[str, int]('a': 1).[dict__str_int]items()

            def main() -> int:
                block entry:
                    return len(make())
        ''').rstrip()


def test_empty_tuple_does_not_acquire_a_nonempty_peer_layout():
    source = '''
        def main() -> bool:
            return (1,) != ()
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> bool:
                block entry:
                    return new[local] tuple[int](1).[tuple__int]__ne__(new[local] tuple__())
        ''').rstrip()
    at(source, '''
        def main() -> bool:
            return (1,).[tuple__int]__ne__!(())
    ''', '''
        import { equal_value as $equal_value } from './pyjs.python.js';

        export function main() {
            return !$equal_value([1],[]);
        }
    ''')


def test_empty_tuple_annotation_remains_a_fixed_zero_field_type():
    source = '''
        @js
        def empty() -> tuple[()]:
            return ()

        def main() -> int:
            return len(empty())
    '''
    with analyze_source("from pyjs import js\n" + dedent(source), wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def empty() -> tuple__:
                block entry:
                    return new[caller] tuple__()

            def main() -> int:
                block entry:
                    return len(empty())
        ''').rstrip()
    at(source, '''
        def empty() -> tuple__:
            return ()

        def main() -> int:
            return empty().[tuple__]__len__!()
    ''', '''
        export function empty() {
            return [];
        }

        export function main() {
            return empty().length;
        }
    ''')


@pytest.mark.parametrize("expression", ["tuple()", "()[::step]", "() * step", "step * ()"])
def test_empty_tuple_local_annotation_retains_its_resolved_class(expression):
    with analyze_source(f'''
        def main() -> int:
            step = 2
            empty = {expression}
            return len(empty)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assignment, = (node for node in ast.walk(analysis.entry_point.node)
                       if isinstance(node, ast.AnnAssign) and node.target.id == "empty")
        value_type = assignment.annotation.obj
        assert value_type.generic_name == "tuple"
        assert value_type.generic_types == {}
        assert not value_type.tuple_variadic

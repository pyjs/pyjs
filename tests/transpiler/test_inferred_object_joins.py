import pytest

from pyjs.analysis.source import analyze_source
from pyjs.analysis.type_relations import is_builtin_class
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import aat, at
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "llvm", "jvm", "wasm"])
def test_opaque_inferred_join_is_target_neutral(environment):
    with analyze_source('''
        def main(value: object, flag: bool):
            return value if flag else "tail"
    ''', wrap=False, environment=environment) as analysis:
        assert is_builtin_class(analysis.entry_point.return_type, "object")


def test_inferred_object_return_and_conditional_keep_the_object_contract():
    at('''
        @js
        def select(value: object, flag: bool):
            if flag:
                return value
            return "tail"

        def main(value: object, flag: bool):
            return select(value, flag) if flag else 7
    ''', '''
        def select(value: object, flag: bool) -> object:
            if flag:
                return value
            return 'tail'

        def main(value: object, flag: bool) -> object:
            return select(value, flag) if flag else 7
    ''', '''
        export function select(value, flag) {
            if (flag) {
                return value;
            }
            return 'tail';
        }

        export function main(value, flag) {
            return flag ? select(value, flag) : 7;
        }
    ''')


def test_erased_inferred_return_preserves_source_numeric_normalization():
    assert_semantics('''
        from pyjs import int8, js

        @js
        def select(value: object, flag: bool):
            if flag:
                return value
            return int8(130)

        @js
        def choose(value: object, flag: bool):
            return "tail" if flag else value

        def main() -> None:
            for flag in [True, False]:
                print(select("head", flag))
                print(choose(7, flag))

        main()
    ''')


def test_explicit_object_union_annotation_is_not_rewritten():
    aat('''
        def main(value: object) -> object | str:
            return value
    ''', '''
        def main(value: object) -> object | str:
            return value
    ''', '''
        export function main(value) {
            return value;
        }
    ''')


def test_next_joins_an_erased_item_with_a_concrete_default():
    at('''
        from collections.abc import Iterator

        def main(values: Iterator[object]):
            return next(values, "fallback")
    ''', '''
        def main(values: Iterator__object) -> object:
            return next(values, 'fallback')
    ''', '''
        import { raise_stop_iteration as $raise_stop_iteration } from './pyjs.python.js';

        export function main(values) {
            return ((result)=>{if(result.done){return 'fallback';}return result.value;})(values.next());
        }
    ''')


def test_erased_next_defaults_preserve_fixed_width_values_in_javascript():
    assert_semantics('''
        from collections.abc import Iterator
        from pyjs import int8, js

        @js
        def values(present: bool) -> Iterator[object]:
            if present:
                yield "item"

        @js
        def main() -> None:
            for present in [False, True]:
                print(next(values(present), int8(130)))
                print(next(values(present), "fallback"))

        main()
    ''')


def test_user_class_named_object_does_not_absorb_other_types():
    at('''
        @js.native
        class object:
            def __init__(self): ...

        def main(value: object, flag: bool):
            return value if flag else "tail"
    ''', '''
        def main(value: object, flag: bool) -> object | str:
            return value if flag else 'tail'
    ''', '''
        export function main(value, flag) {
            return flag ? value : 'tail';
        }
    ''')

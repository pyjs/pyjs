import pytest

from pyjs.testing.helpers import ad, at, diagnostic_text


def test_compound_optional_initialization_preserves_exact_analyzed_and_javascript_source():
    at(
        '''
        def main(value: int | None, refresh: bool) -> int:
            if value is None or refresh:
                value = 7
            return value + 1
        ''',
        '''
        def main(value: int | None, refresh: bool) -> int:
            if value.[object]__is__!(None) or refresh:
                value = 7
            return value.[int]__add__!(1)
        ''',
        '''
        export function main(value, refresh) {
            if (value == null || refresh) {
                value = 7;
            }
            return value + 1;
        }
        ''',
    )


def test_class_receiver_early_exit_preserves_exact_lowering():
    at(
        '''
        @js
        class Registry:
            current: int | None = 7
        @js
        def main() -> int:
            if Registry.current is None:
                return 0
            return Registry.current + 1
        ''',
        '''
        class Registry:
            current: __static__ = 7

        def main() -> int:
            if Registry.current.[object]__is__!(None):
                return 0
            return Registry.current.[int]__add__!(1)
        ''',
        '''
        export class Registry {
            static current = 7;
        }

        export function main() {
            if (Registry.current == null) {
                return 0;
            }
            return Registry.current + 1;
        }
        ''',
    )


def test_call_receiver_early_exit_preserves_exact_lowering():
    at(
        '''
        @js
        class Holder:
            def __init__(self, value: int | None):
                self.value = value
            def current(self) -> Holder:
                return self
        @js
        def main(holder: Holder) -> int:
            if holder.current().value is None:
                return 0
            return holder.current().value + 1
        ''',
        '''
        class Holder:

            def __init__(value: int | None) -> None:
                self.value = value

            def current() -> Holder:
                return self

        def main(holder: Holder) -> int:
            if holder.[Holder]current().value.[object]__is__!(None):
                return 0
            return holder.[Holder]current().value.[int]__add__!(1)
        ''',
        '''
        export class Holder {

            constructor(value) {
                this.value = value;
            }

            current() {
                return this;
            }
        }

        export function main(holder) {
            if (holder.current().value == null) {
                return 0;
            }
            return holder.current().value + 1;
        }
        ''',
    )


def test_compatible_iterable_initialization_preserves_exact_lowering():
    at(
        '''
        from collections.abc import Iterable

        def main(values: Iterable[int] | None) -> int:
            if values is None:
                values = [1, 2]
            total = 0
            for value in values:
                total += value
            return total
        ''',
        '''
        def main(values: Iterable[int] | None) -> int:
            if values.[object]__is__!(None):
                values = [1, 2]
            total: int = 0
            for value: int in values:
                total = total.[int]__add__!(value)
            return total
        ''',
        '''
        export function main(values) {
            if (values == null) {
                values = [1, 2];
            }
            var total = 0;
            for (var value of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)(values)) {
                total = total + value;
            }
            return total;
        }
        ''',
    )


def test_nested_optional_initialization_preserves_exact_lowering():
    at(
        '''
        def main(value: int | None, refresh: bool) -> int:
            if value is None:
                if refresh:
                    value = 7
                else:
                    value = 8
            return value + 1
        ''',
        '''
        def main(value: int | None, refresh: bool) -> int:
            if value.[object]__is__!(None):
                if refresh:
                    value = 7
                else:
                    value = 8
            return value.[int]__add__!(1)
        ''',
        '''
        export function main(value, refresh) {
            if (value == null) {
                if (refresh) {
                    value = 7;
                } else {
                    value = 8;
                }
            }
            return value + 1;
        }
        ''',
    )


@pytest.mark.parametrize("body", [
    "if value is None and refresh:\n        value = 7",
    "if value is None or refresh:\n        value = None",
    "if value is None or refresh:\n        if refresh:\n            value = 7",
    "if value is None or refresh:\n        value = 7\n    else:\n        value = None",
    "if value is None or refresh:\n        value = 7\n        value = None",
    "if value is None:\n        if refresh:\n            value = 7\n        else:\n            value = None",
    "if value is None:\n        if refresh:\n            value = 7\n        else:\n            value = 8\n        value = None",
])
def test_both_live_paths_must_establish_the_postcondition(body):
    source = ("def main(value: int | None, refresh: bool) -> int:\n    " + body
              + "\n    return value + 1\n")
    ad(source, diagnostic_text(
        "guard.py", len(source.splitlines()), "return value + 1", "       ^^^^^^^^^",
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        "of int|NoneType and int [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")


@pytest.mark.parametrize("guard", ["value is None", "value is None or refresh"])
@pytest.mark.parametrize("overwrite", [
    "for value in items:\n            pass",
    "for value, other in [(None, 1)]:\n            pass",
    "if refresh:\n            for value in items:\n                pass",
])
def test_loop_targets_invalidate_initialization_proofs(guard, overwrite):
    source = ("def main(value: int | None, refresh: bool, items: list[int | None]) -> int:\n"
              f"    if {guard}:\n        value = 7\n        {overwrite}\n"
              "    return value + 1\n")
    ad(source, diagnostic_text(
        "guard.py", len(source.splitlines()), "return value + 1", "       ^^^^^^^^^",
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        "of int|NoneType and int [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")


def test_loop_target_replacing_receiver_invalidates_field_proof():
    source = '''from pyjs import js
@js
class Holder:
    def __init__(self, value: int | None):
        self.value = value
@js
def main(holder: Holder, holders: list[Holder], refresh: bool) -> int:
    if holder.value is None or refresh:
        holder.value = 7
        for holder in holders:
            pass
    return holder.value + 1
'''
    ad(source, diagnostic_text(
        "guard.py", 12, "return holder.value + 1", "       ^^^^^^^^^^^^^^^^",
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        "of int|NoneType and int [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")


@pytest.mark.parametrize("kind, assigned", [("float", "1"), ("int", "True")])
def test_assignment_promotion_does_not_prove_numeric_union_arm(kind, assigned):
    source = f'''def main(value: {kind} | str, refresh: bool) -> str:
    if isinstance(value, str) or refresh:
        value = {assigned}
    return str(value)
'''
    ad(source, diagnostic_text(
        "guard.py", 4, "return str(value)", "           ^^^^^",
        f"pyjs.CompilationError: Method '__str__' has incompatible client lowering on {kind} | str [PYJS2001]",
        "help: Narrow the receiver with isinstance() before calling the definition on str.",
    ), filename="guard.py")


@pytest.mark.parametrize("kind, assigned, increment, underline", [
    ("float", "0", "1.5", "       ^^^^^^^^^^^"),
    ("int", "True", "1", "       ^^^^^^^^^"),
])
def test_optional_numeric_defaults_require_the_declared_runtime_kind(kind, assigned, increment, underline):
    source = f'''def main(value: {kind} | None) -> {kind}:
    if value is None:
        value = {assigned}
    return value + {increment}
'''
    ad(source, diagnostic_text(
        "guard.py", 4, f"return value + {increment}", underline,
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        f"of {kind}|NoneType and {kind} [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")


def test_exception_target_rebinding_invalidates_initialization():
    source = '''def main(value: int | None, refresh: bool) -> int:
    if value is None or refresh:
        value = 1
        try:
            raise ValueError("no")
        except ValueError as value:
            pass
    return value + 1
'''
    ad(source, diagnostic_text(
        "guard.py", 8, "return value + 1", "       ^^^^^^^^^",
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        "of int|NoneType and int [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")


@pytest.mark.parametrize("guard", ["load().value is None", "load().value is None or refresh"])
def test_repeated_receiver_calls_do_not_establish_initialization(guard):
    source = f'''from pyjs import js
@js
class Holder:
    def __init__(self, value: int | None):
        self.value = value
@js
def load() -> Holder:
    return Holder(None)
@js
def main(refresh: bool) -> int:
    if {guard}:
        load().value = 1
    return load().value + 1
'''
    ad(source, diagnostic_text(
        "guard.py", 13, "return load().value + 1", "       ^^^^^^^^^^^^^^^^",
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        "of int|NoneType and int [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")

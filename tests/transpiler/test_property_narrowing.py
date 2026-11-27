from textwrap import indent

import pytest

from pyjs.analysis.analyzer import JS_ENVIRONMENT
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import at
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

ENVIRONMENTS = [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT]
GUARDS = ["value is not None", "isinstance(value, str)", "value"]
BODIES = [
    "if GUARD:\n    return VALUE.upper()\nreturn ''",
    "if not (GUARD):\n    return ''\nreturn VALUE.upper()",
    "assert GUARD\nreturn VALUE.upper()",
    "return VALUE.upper() if GUARD else ''",
    "while GUARD:\n    return VALUE.upper()\nreturn ''",
    "if GUARD and VALUE.upper():\n    return 'yes'\nreturn ''",
    "return ''.join([VALUE.upper() for unused in [0] if GUARD])",
]


def source_for(body, inherited=False, nested=False, property_read=True):
    declaration = '''
from pyjs import js
@js
class Box:
    def __init__(self):
        self.stored: str | None = "ready"
    @property
    def value(self) -> str | None:
        result = self.stored
        self.stored = None
        return result
'''
    if not property_read:
        declaration = declaration.replace('self.stored', 'self.value').split('    @property')[0]
    if inherited:
        declaration += '\n@js\nclass Child(Box):\n    pass\n'
    if nested:
        declaration += '''
@js
class Owner:
    @property
    def box(self) -> Box:
        return Box()
'''
    constructor = "Owner()" if nested else "Child()" if inherited else "Box()"
    return declaration + f'\ndef main() -> str:\n    box = {constructor}\n' + indent(body, "    ") + '\n'


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("body", BODIES)
@pytest.mark.parametrize("inherited", [False, True])
def test_property_guards_do_not_narrow_later_reads(environment, guard, body, inherited):
    body = body.replace("GUARD", guard.replace("value", "box.value")).replace("VALUE", "box.value")
    source = source_for(body, inherited)
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member") as caught:
        analyze_source(source, wrap=False, environment=environment, filename="property_guard.py")
    error = caught.value
    assert error.diagnostic.code == "PYJS1003"
    assert error.filename == "property_guard.py"
    assert "box.value.upper()" in source.splitlines()[error.lineno - 1]
    assert error.diagnostic.help == (
        "Property getters may return a different value on each read. "
        "Capture the result in a local variable, then narrow that variable.",
    )


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
def test_field_through_property_receiver_is_not_stable(environment, guard):
    guard = guard.replace("value", "box.box.stored")
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member"):
        analyze_source(source_for(f"if {guard}:\n    return box.box.stored.upper()\nreturn ''", nested=True),
                       wrap=False, environment=environment)


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("body", BODIES)
def test_ordinary_fields_still_narrow(environment, guard, body):
    body = body.replace("GUARD", guard.replace("value", "box.value")).replace("VALUE", "box.value")
    with analyze_source(source_for(body, property_read=False), wrap=False, environment=environment):
        pass


@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("body", BODIES)
def test_consuming_getter_makes_repeated_read_proofs_unsound_in_python(guard, body):
    body = body.replace("GUARD", guard.replace("value", "box.value")).replace("VALUE", "box.value")
    namespace = {}
    exec(compile(source_for(body), "consuming_getter.py", "exec"), namespace)
    with pytest.raises(AttributeError, match="'NoneType' object has no attribute 'upper'"):
        namespace["main"]()


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("body", BODIES)
def test_captured_local_can_narrow_in_all_guard_contexts(environment, guard, body):
    body = "value = box.value\n" + body.replace("GUARD", guard).replace("VALUE", "value")
    with analyze_source(source_for(body, inherited=True), wrap=False, environment=environment):
        pass


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("body", [
    "if isinstance(box.value, str):\n    return box.value.upper()\nreturn ''",
    "if isinstance(box.value, int):\n    return ''\nreturn box.value.upper()",
])
def test_nonoptional_union_property_never_inherits_positive_or_negative_proof(environment, body):
    source = source_for(body).replace("str | None", "str | int").replace("self.stored = None", "self.stored = 42")
    namespace = {}
    exec(compile(source, "changing_getter.py", "exec"), namespace)
    with pytest.raises(AttributeError, match="'int' object has no attribute 'upper'"):
        namespace["main"]()
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member"):
        analyze_source(source, wrap=False, environment=environment)


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("body", [
    "if box.value == 'ready':\n    return box.value.upper()\nreturn ''",
    "if box.value != 'ready':\n    return ''\nreturn box.value.upper()",
    "assert box.value == 'ready'\nreturn box.value.upper()",
])
def test_literal_property_guards_do_not_establish_later_result_identity(environment, body):
    source = "from typing import Literal\n" + source_for(body).replace("str | None", "Literal['ready'] | None")
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member"):
        analyze_source(source, wrap=False, environment=environment)


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
def test_even_a_currently_pure_optional_getter_has_no_implicit_stability_promise(environment, guard):
    guard = guard.replace("value", "box.value")
    source = source_for(f"if {guard}:\n    return box.value.upper()\nreturn ''")
    source = source.replace("        self.stored = None\n", "")
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member"):
        analyze_source(source, wrap=False, environment=environment)


def test_captured_property_keeps_declared_union_and_narrows_only_the_local():
    at('''
        @js
        class Box:
            @property
            def value(self) -> str | None:
                return "ready"
        def main(box: Box) -> str:
            value = box.value
            if isinstance(value, str):
                return value.upper()
            return ""
    ''', '''
        class Box:

            @property
            def value() -> str | None:
                return 'ready'

        def main(box: Box) -> str:
            value: str | None = box.value
            if isinstance(value, str):
                return value.[str]upper!()
            return ''
    ''', '''
        export class Box {

            get value() {
                return 'ready';
            }
        }

        export function main(box) {
            var value = box.value;
            if ((typeof value === 'string')) {
                return value.toUpperCase();
            }
            return '';
        }
    ''')


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
def test_union_receivers_keep_each_getters_declared_result(environment, guard):
    guard = guard.replace("value", "box.value")
    declarations = source_for("").split("def main()")[0]
    source = declarations + f'''
@js
class Other:
    @property
    def value(self) -> str:
        return "ready"
@js
def read(box: Box | Other) -> str:
    if {guard}:
        return box.value.upper()
    return ""
def main() -> str:
    return read(Box()) + read(Other())
'''
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member"):
        analyze_source(source, wrap=False, environment=environment)


@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize("guard", GUARDS)
def test_capture_after_a_property_guard_is_a_fresh_unproved_value(environment, guard):
    guard = guard.replace("value", "box.value")
    source = source_for(f"if {guard}:\n    value = box.value\n    return value.upper()\nreturn ''")
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined on every member"):
        analyze_source(source, wrap=False, environment=environment)

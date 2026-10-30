import textwrap
from dataclasses import replace

import pytest

from pyjs.testing.helpers import aa, aat, ad, at
from pyjs.analysis.analyzer import InferenceVisitor, JS_ENVIRONMENT
from pyjs.analysis.source import analyze_source


def test_simple_assignment():
    aat(
        "a = 9",
        "a: int = 9",
        "var a = 9;"
    )


def test_annotation_only_local_declares_its_type_before_branch_assignment():
    aat(
        """
        def main(flag: bool):
            value: int | str
            if flag:
                value = 1
            else:
                value = "one"
            print(value)
        """,
        """
        def main(flag: bool) -> None:
            value: int | str
            if flag:
                value = 1
            else:
                value = 'one'
            print(value)
        """,
        """
        export function main(flag) {
            var value;
            if (flag) {
                value = 1;
            } else {
                value = 'one';
            }
            console.log(value);
        }
        """,
    )


def test_annotation_only_local_rejects_an_incompatible_redeclaration():
    ad(
        """
        def main():
            value: int
            value: str
        """,
        """
          File "annotation_redeclaration.py", line 4
            value: str
            ^^^^^
        pyjs.CompilationError: Cannot assign str to 'value' of type int [PYJS1103]
        help: Assign a value compatible with int or change the annotation for 'value'.
        """,
        filename="annotation_redeclaration.py",
    )


def test_annotation_only_declaration_rejects_an_instance_attribute():
    ad(
        """
        from pyjs import js

        @js
        class Counter:
            def __init__(self):
                self.value: int
        """,
        """
          File "attribute_declaration.py", line 7
            self.value: int
            ^^^^^^^^^^
        pyjs.CompilationError: Annotation-only declarations require a local name [PYJS2001]
        help: Assign an initial value in __init__(), or declare the type on the class when initialization must happen later.
        """,
        filename="attribute_declaration.py",
    )


def test_unpacking_can_assign_subscript_targets_without_losing_rhs_values():
    at(
        """
        values = [[1], [2]]
        left = 0
        right = 1
        values[left], values[right] = values[right], values[left]
        first, values[right] = values[left], [3]
        """,
        """
        values: list[list[int]] = [[1], [2]]
        left: int = 0
        right: int = 1
        $unpack = ($get_list_item(values, right), $get_list_item(values, left))
        $assignment3: list[int] = $unpack[0]
        $set_list_item(values, left, $assignment3)
        $assignment4: list[int] = $unpack[1]
        $set_list_item(values, right, $assignment4)
        $unpack = ($get_list_item(values, left), [3])
        first: list[int] = $unpack[0]
        $assignment6: list[int] = $unpack[1]
        $set_list_item(values, right, $assignment6)
        """,
        """
        import { get_list_item as $get_list_item, set_list_item as $set_list_item } from './pyjs.python.js';

        var values = [[1], [2]];
        var left = 0;
        var right = 1;
        const $unpack0 = [$get_list_item(values, right), $get_list_item(values, left)];
        var $assignment3 = $unpack0[0];
        $set_list_item(values, left, $assignment3);
        var $assignment4 = $unpack0[1];
        $set_list_item(values, right, $assignment4);
        const $unpack1 = [$get_list_item(values, left), [3]];
        var first = $unpack1[0];
        var $assignment6 = $unpack1[1];
        $set_list_item(values, right, $assignment6);
        """,
    )


def test_simple_reassignment():
    aat(
        """
        a = 9
        a = 10
        b = a
        """,
        """
        a: int = 9
        a = 10
        b: int = a
        """,
        """
        var a = 9;
        a = 10;
        var b = a;
        """
    )


def test_integer_values_are_compatible_with_float_assignments():
    at(
        """
        def main():
            value: float = 1
            value = 2
            value = True
        """,
        """
        def main() -> None:
            value: float = 1
            value = 2
            value = True
        """,
        """
        export function main() {
            var value = 1;
            value = 2;
            value = true;
        }
        """,
    )


def test_reassignment_rejects_an_incompatible_local_type():
    ad(
        """
        def main():
            count = 1
            count = "one"
        """,
        """
          File "local_reassignment.py", line 4
            count = "one"
            ^^^^^
        pyjs.CompilationError: Cannot assign str to 'count' of type int [PYJS1103]
        help: Assign a value compatible with int or change the annotation for 'count'.
        """,
        filename="local_reassignment.py",
    )


def test_unpacking_reassignment_preserves_existing_local_types():
    ad(
        """\
        def main():
            number = 1
            text = "one"
            number, text = ("one", 1)
        """,
        """
          File "unpacking_reassignment.py", line 4
            number, text = ("one", 1)
            ^^^^^^
        pyjs.CompilationError: Cannot assign str to 'number' of type int [PYJS1103]
        help: Assign a value compatible with int or change the annotation for 'number'.
        """,
        filename="unpacking_reassignment.py",
    )


def test_optional_local_assignment_uses_declared_type_after_narrowing():
    at(
        """
        def main():
            value: int | None = 1
            if value is not None:
                print(value + 1)
                value = None
        """,
        """
        def main() -> None:
            value: int | None = 1
            if value.[object]__is_not__!(None):
                print(value.[int]__add__!(1))
                value = None
        """,
        """
        export function main() {
            var value = 1;
            if (value != null) {
                console.log(value + 1);
                value = null;
            }
        }
        """,
    )


def test_optional_locals_narrow_after_assignment_and_missing_value_initialization():
    at(
        """
        @js
        class Item:
            def __init__(self):
                self.label = "ready"

        def main():
            values: dict[str, int] | None = None
            if values is None:
                values = {}
            values["answer"] = 42

            item: Item | None = None
            item = Item()
            print(item.label)
        """,
        """
        class Item:

            def __init__() -> None:
                self.label = 'ready'

        def main() -> None:
            values: dict[str, int] | None = None
            if values.[object]__is__!(None):
                values = {}
            values.[dict__str_int]__setitem__!('answer', 42)
            item: Item | None = None
            item = Item()
            print(item.label)
        """,
        """
        export class Item {

            constructor() {
                this.label = 'ready';
            }
        }

        export function main() {
            var values = null;
            if (values == null) {
                values = new Map([]);
            }
            (values.set('answer', 42), null);
            var item = null;
            item = new Item();
            console.log(item.label);
        }
        """,
    )


def test_conditional_optional_initialization_does_not_narrow_unsafely():
    ad(
        """\
        def main(enabled: bool):
            values: dict[str, int] | None = None
            if values is None:
                if enabled:
                    values = {}
            values["answer"] = 42
        """,
        """
          File "conditional_initialization.py", line 6
            values["answer"] = 42
            ^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Attribute '__setitem__' is not defined on every member of dict[str, int] | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing '__setitem__'.
        """,
        filename="conditional_initialization.py",
    )


def test_optional_join_checks_the_previously_present_branch_too():
    ad(
        '''\
        def main(value: str | None):
            if value is not None:
                value = None
            else:
                value = "found"
            print(value.upper())
        ''',
        '''
          File "optional_join.py", line 6
            print(value.upper())
                  ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
        ''',
        filename="optional_join.py",
    )


@pytest.mark.parametrize("proof", [
    'value = "ready"',
    'if value is None:\n    return',
    'assert isinstance(value, str)',
], ids=["assignment", "guard", "assert"])
@pytest.mark.parametrize("write", [
    'if enabled:\n    value = None',
    'while enabled:\n    value = items[0]\n    enabled = False',
    'for item in items:\n    value = item',
    'for value in items:\n    pass',
    'try:\n    value = items[0]\nexcept ValueError:\n    pass',
    'if enabled:\n    value, unused = items[0], 1',
], ids=["if", "while", "for", "for-target", "try", "unpack"])
def test_compound_writes_invalidate_optional_proofs(proof, write):
    source = (
        "def main(value: str | None, enabled: bool, items: list[str | None]):\n"
        + textwrap.indent(proof + "\n" + write + "\nprint(value.upper())\n", "    ")
    )
    ad(source, f'''
          File "compound_write.py", line {len(source.splitlines())}
            print(value.upper())
                  ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="compound_write.py")


def test_writes_on_exited_branches_keep_optional_proofs():
    at(
        """
        def main(value: str | None, clear: bool) -> str:
            if value is None:
                return "absent"
            if clear:
                value = None
                return "cleared"
            return value.upper()
        """,
        """
        def main(value: str | None, clear: bool) -> str:
            if value.[object]__is__!(None):
                return 'absent'
            if clear:
                value = None
                return 'cleared'
            return value.[str]upper!()
        """,
        """
        export function main(value, clear) {
            if (value == null) {
                return 'absent';
            }
            if (clear) {
                value = null;
                return 'cleared';
            }
            return value.toUpperCase();
        }
        """,
    )


@pytest.mark.parametrize("branch", [
    'if clear:\n    value = None\n    raise ValueError("cleared")',
    'if keep:\n    pass\nelse:\n    value = None\n    return "cleared"',
    'if keep:\n    pass\nelif clear:\n    value = None\n    return "cleared"',
    'if keep:\n    if clear:\n        value = None\n        return "cleared"',
    'if clear:\n    value = None\n    return "cleared"\nelse:\n    return value.lower()',
], ids=["raise", "else", "elif", "nested", "both-exit"])
def test_exited_branch_shapes_keep_optional_proofs(branch):
    source = (
        "def main(value: str | None, clear: bool, keep: bool) -> str:\n"
        "    if value is None:\n"
        '        return "absent"\n'
        + textwrap.indent(branch + "\nreturn value.upper()\n", "    ")
    )
    with analyze_source(source) as analysis:
        assert analysis.entry_point.return_type.name == "str"


@pytest.mark.parametrize("body", [
    'if clear:\n    value = None\n    return ""\nelif keep:\n    value = None',
    'if keep:\n    if clear:\n        value = None\n        return ""\n    value = None',
    'try:\n    if clear:\n        value = None\n        raise ValueError("x")\n'
    'except ValueError:\n    pass',
    'if clear:\n    try:\n        value = None\n        raise ValueError("x")\n'
    '    except ValueError:\n        pass',
    'with Quiet():\n    if clear:\n        value = None\n        raise ValueError("x")',
    'if clear:\n    with Quiet():\n        value = None\n        raise ValueError("x")',
    'while keep:\n    if clear:\n        value = None\n        break\n    keep = False',
], ids=[
    "live-elif", "live-nested", "caught-raise", "caught-in-branch", "suppressed-raise",
    "suppressed-in-branch", "break",
])
def test_writes_reaching_later_code_still_invalidate_optional_proofs(body):
    source = textwrap.dedent("""\
        from pyjs import js

        @js
        class Quiet:
            def __enter__(self) -> None:
                return None

            def __exit__(self, kind: object, error: object, trace: object) -> bool:
                return True

        def main(value: str | None, clear: bool, keep: bool) -> str:
            if value is None:
                return "absent"
    """) + textwrap.indent(body + "\nreturn value.upper()\n", "    ")
    ad(source, f'''
          File "reaching_write.py", line {len(source.splitlines())}
            return value.upper()
                   ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="reaching_write.py")


def test_exited_branch_write_is_invalid_on_loop_backedge():
    ad('''\
        def main(value: str | None, clear: bool, enabled: bool):
            if value is None:
                return
            while enabled:
                print(value.upper())
                if clear:
                    value = None
                    continue
                enabled = False
    ''', '''
          File "exited_backedge.py", line 5
            print(value.upper())
                  ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="exited_backedge.py")


def test_finally_sees_writes_from_exited_branches():
    ad('''\
        def main(value: str | None, clear: bool) -> int:
            if value is None:
                return 0
            try:
                if clear:
                    value = None
                    return 1
            finally:
                print(value.upper())
            return 2
    ''', '''
          File "exited_finally.py", line 9
            print(value.upper())
                  ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="exited_finally.py")


def test_optional_proof_is_invalid_on_loop_backedge():
    ad('''\
        def main(value: str | None, enabled: bool):
            if value is None:
                return
            while enabled:
                print(value.upper())
                value = None
    ''', '''
          File "backedge.py", line 5
            print(value.upper())
                  ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="backedge.py")


def test_independent_loop_widenings_share_one_function_retry():
    attempts = []

    class CountingInference(InferenceVisitor):
        def visit_FunctionDef(self, node):
            if node.name == "main":
                attempts.append(node)
            return super().visit_FunctionDef(node)

    names = [f"value{i}" for i in range(12)]
    source = "def main(flag: bool, " + ", ".join(f"{name}: str | None" for name in names) + ") -> bool:\n"
    source += "".join(f"    if {name} is None:\n        {name} = 'present'\n" for name in names)
    source += "".join(f"    while flag:\n        {name} = None\n        break\n" for name in names)
    source += "    return value0 is None\n"
    environment = replace(JS_ENVIRONMENT, inference_visitor=CountingInference)
    with analyze_source(source, environment=environment) as analysis:
        assert analysis.entry_point.return_type.name == "bool"
    # A traversal bound, not a wall-clock threshold: independent sites must
    # be discovered together, not cause one whole-function retry per loop.
    assert len(attempts) == 2


@pytest.mark.parametrize("region", [
    'try:\n    value = None\n    raise ValueError("fail")\nexcept ValueError:\n    return value.upper()',
    'try:\n    value = None\nfinally:\n    return value.upper()',
    'try:\n    raise ValueError("fail")\nexcept ValueError:\n    value = None\nfinally:\n    return value.upper()',
    'try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    value = None\nfinally:\n    return value.upper()',
    'try:\n    value = None\nexcept ValueError:\n    pass\nelse:\n    return value.upper()',
], ids=["handler", "finally-body", "finally-handler", "finally-else", "else-body"])
@pytest.mark.parametrize("backend", ["js", "llvm"])
def test_exception_entry_invalidates_proofs_from_protected_writes(region, backend):
    from pyjs.native.analysis import NATIVE_ENVIRONMENT

    source = (
        "def main(value: str | None):\n"
        "    if value is None:\n        return\n"
        + textwrap.indent(region + "\n", "    ")
    )
    ad(source, f'''
          File "exception_entry.py", line {len(source.splitlines())}
            return value.upper()
                   ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="exception_entry.py", environment=NATIVE_ENVIRONMENT if backend == "llvm" else None)


@pytest.mark.parametrize("condition", [
    "value", "isinstance(value, str)", "not (value is None)",
    "value is not None and enabled",
])
def test_surviving_branch_checks_writes_for_every_guard(condition):
    ad(f'''\
        def main(value: str | None, enabled: bool):
            if {condition}:
                value = None
            else:
                return
            print(value.upper())
    ''', '''
          File "surviving_branch.py", line 6
            print(value.upper())
                  ^^^^^^^^^^^
        pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]
        help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.
    ''', filename="surviving_branch.py")


def test_unpacking_can_establish_optional_presence():
    at('''
        def main(value: int | None):
            if value is None:
                value = 1
            else:
                value, unused = 2, 3
            print(value + 1)
    ''', '''
        def main(value: int | None) -> None:
            if value.[object]__is__!(None):
                value = 1
            else:
                value, unused = (2, 3)
            print(value.[int]__add__!(1))
    ''', '''
        export function main(value) {
            if (value == null) {
                value = 1;
            } else {
                var [value, unused] = [2, 3];
            }
            console.log(value + 1);
        }
    ''')


def test_concrete_conditional_write_preserves_an_existing_guard():
    at('''
        def main(value: str | None, upper: bool) -> str:
            if value is None:
                return "-"
            if upper:
                value = value.upper()
            return value
    ''', '''
        def main(value: str | None, upper: bool) -> str:
            if value.[object]__is__!(None):
                return '-'
            if upper:
                value = value.[str]upper!()
            return value
    ''', '''
        export function main(value, upper) {
            if (value == null) {
                return '-';
            }
            if (upper) {
                value = value.toUpperCase();
            }
            return value;
        }
    ''')


def test_optional_attribute_assignment_uses_declared_type_after_narrowing():
    at(
        """
        @js
        class Timer:
            def __init__(self):
                self.handle: int | None = None

            def clear(self):
                if self.handle is not None:
                    print(self.handle + 1)
                    self.handle = None

        def main():
            Timer().clear()
        """,
        """
        class Timer:

            def __init__() -> None:
                self.handle: int | None = None

            def clear() -> None:
                if self.handle.[object]__is_not__!(None):
                    print(self.handle.[int]__add__!(1))
                    self.handle = None

        def main() -> None:
            Timer().[Timer]clear()
        """,
        """
        export class Timer {

            constructor() {
                this.handle = null;
            }

            clear() {
                if (this.handle != null) {
                    console.log(this.handle + 1);
                    this.handle = null;
                }
            }
        }

        export function main() {
            new Timer().clear();
        }
        """,
    )


def test_attribute_annotation_remains_authoritative_over_later_assignments():
    at(
        """
        @js
        class Client:
            def initialize(self):
                self.socket: str | None = None

            def connect(self):
                self.socket = "ready"

        def main():
            client = Client()
            client.connect()
            client.initialize()
        """,
        """
        class Client:

            def initialize() -> None:
                self.socket: str | None = None

            def connect() -> None:
                self.socket = 'ready'

        def main() -> None:
            client: Client = Client()
            client.[Client]connect()
            client.[Client]initialize()
        """,
        """
        export class Client {

            initialize() {
                this.socket = null;
            }

            connect() {
                this.socket = 'ready';
            }
        }

        export function main() {
            var client = new Client();
            client.connect();
            client.initialize();
        }
        """,
    )


def test_method_assignment_waits_for_constructor_attribute_type():
    at(
        """
        @js
        class Timer:
            def clear(self):
                self.handle = None

            def __init__(self):
                self.handle: int | None = None

        def main():
            Timer().clear()
        """,
        """
        class Timer:

            def clear() -> None:
                self.handle = None

            def __init__() -> None:
                self.handle: int | None = None

        def main() -> None:
            Timer().[Timer]clear()
        """,
        """
        export class Timer {

            clear() {
                this.handle = null;
            }

            constructor() {
                this.handle = null;
            }
        }

        export function main() {
            new Timer().clear();
        }
        """,
    )


def test_simple_annotated_assignments():
    aa("b: str=''", "b: str = ''")
    aa("c: list[str]=[]", "c: list[str] = []")
    aa("c: list[int|list[int]]=[]", "c: list[int | list[int]] = []")
    aa("d: dict[str,str|int]={}", "d: dict[str, str | int] = {}")


def test_simple_assignments_infer_types():
    aa("b=''", "b: str = ''")
    aa("c=['']", "c: list[str] = ['']")
    aa("c=[9,[10]]", "c: list[int | list[int]] = [9, [10]]")
    aa(
      "d={'foo': 'baz', 'bar': 9}",
      "d: dict[str, str | int] = {'foo': 'baz', 'bar': 9}"
    )


def test_assignment_with_undefined_value():
    ad(
        """\
        def main():
            c = x
        """,
        """
          File "assignment.py", line 2
            c = x
                ^
        pyjs.CompilationError: Name 'x' is not defined [PYJS1001]
        """,
        filename="assignment.py",
    )


def test_assignment_of_indeterminate_type():
    ad(
        """\
        def main():
            values = []
        """,
        """
          File "empty_list.py", line 2
            values = []
            ^^^^^^
        pyjs.CompilationError: Type of 'values' cannot be inferred [PYJS1101]
        help: Add an explicit type annotation for 'values'.
        """,
        filename="empty_list.py",
    )
    ad(
        """\
        def main():
            values = {}
        """,
        """
          File "empty_dict.py", line 2
            values = {}
            ^^^^^^
        pyjs.CompilationError: Type of 'values' cannot be inferred [PYJS1101]
        help: Add an explicit type annotation for 'values'.
        """,
        filename="empty_dict.py",
    )


def test_empty_collection_reassignment_uses_existing_type():
    aat(
        """
        values: list[str] = []
        values = []
        lookup: dict[str, int] = {}
        lookup = {}
        """,
        """
        values: list[str] = []
        values = []
        lookup: dict[str, int] = {}
        lookup = {}
        """,
        """
        var values = [];
        values = [];
        var lookup = new Map([]);
        lookup = new Map([]);
        """,
    )


def test_empty_generic_constructor_reassignment_uses_existing_type():
    at(
        """
        members: set[int] = set[int]()
        members = set()
        """,
        """
        members: set[int] = set__int()
        members = set__int()
        """,
        """
        var members = new Set();
        members = new Set();
        """,
    )


def test_empty_custom_generic_constructor_uses_annotated_assignment_type():
    at(
        """
        @js
        class Box[T]:
            def __init__(self):
                pass

        def main():
            box: Box[str] = Box()
        """,
        """
        class Box__str:

            def __init__() -> None:
                pass

        def main() -> None:
            box: Box[str] = Box__str()
        """,
        """
        export class Box__str {

            constructor() {
            }
        }

        export function main() {
            var box = new Box__str();
        }
        """,
    )


def test_empty_list_instance_attribute_reassignment_uses_declared_type():
    at(
        """
        @js
        class State:
            def __init__(self):
                self.entries: list[str] = []
                self.lookup: dict[str, int] = {}

            @js.keep
            def reset(self):
                self.entries = []
                self.lookup = {}

        def main():
            state = State()
            state.reset()
        """,
        """
        class State:

            def __init__() -> None:
                self.entries: list[str] = []
                self.lookup: dict[str, int] = {}

            def reset() -> None:
                self.entries = []
                self.lookup = {}

        def main() -> None:
            state: State = State()
            state.[State]reset()
        """,
        """
        export class State {

            constructor() {
                this.entries = [];
                this.lookup = new Map([]);
            }

            reset() {
                this.entries = [];
                this.lookup = new Map([]);
            }
        }

        export function main() {
            var state = new State();
            state.reset();
        }
        """,
    )


def test_attribute_assignment_on_subscript_result():
    at(
        """
        @js
        class Item:
            def __init__(self):
                self.value: str | None = None

        def main():
            items = [Item()]
            items[0].value = "ready"
        """,
        """
        class Item:

            def __init__() -> None:
                self.value: str | None = None

        def main() -> None:
            items: list[Item] = [Item()]
            $get_list_item(items, 0).value = 'ready'
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Item {

            constructor() {
                this.value = null;
            }
        }

        export function main() {
            var items = [new Item()];
            $get_list_item(items, 0).value = 'ready';
        }
        """,
    )


def test_subscript_assignment_dispatches_to_collection_protocol():
    at(
        """
        @js
        class Item:
            def __init__(self):
                self.id = "one"

        def main():
            item = Item()
            values: dict[str, str] = {}
            values[item.id] = "value"
        """,
        """
        class Item:

            def __init__() -> None:
                self.id = 'one'

        def main() -> None:
            item: Item = Item()
            values: dict[str, str] = {}
            values.[dict__str_str]__setitem__!(item.id, 'value')
        """,
        """
        export class Item {

            constructor() {
                this.id = 'one';
            }
        }

        export function main() {
            var item = new Item();
            var values = new Map([]);
            (values.set(item.id, 'value'), null);
        }
        """,
    )


def test_slice_assignment_and_deletion_dispatch_to_collection_protocols():
    at(
        """
        def main():
            values = [0, 1, 2, 3]
            selected = values[1:3]
            values[1:3] = [8, 9]
            del values[0]
            mapping = {"one": 1, "two": 2}
            del mapping["one"]
        """,
        """
        def main() -> None:
            values: list[int] = [0, 1, 2, 3]
            selected: list[int] = values.[list__int]__slice__!(1, 3, None)
            $assignment2: list[int] = [8, 9]
            $set_list_slice(values, $assignment2, 1, 3, None)
            $delete_list_item(values, 0)
            mapping: dict[str, int] = {'one': 1, 'two': 2}
            $delete_dict_item(mapping, 'one')
        """,
        """
        import { set_list_slice as $set_list_slice, delete_list_item as $delete_list_item, delete_dict_item as $delete_dict_item } from './pyjs.python.js';

        export function main() {
            var values = [0, 1, 2, 3];
            var selected = values.slice(1,3);
            var $assignment2 = [8, 9];
            $set_list_slice(values, $assignment2, {start: 1, stop: 3, step: null});
            $delete_list_item(values, 0);
            var mapping = new Map([['one', 1], ['two', 2]]);
            $delete_dict_item(mapping, 'one');
        }
        """,
    )


def test_tuple_item_assignment_reports_immutable_sequence():
    ad(
        """\
        def main():
            values = (1, 2)
            values[0] = 3
        """,
        """
          File "tuple_assignment.py", line 3
            values[0] = 3
            ^^^^^^^^^
        pyjs.CompilationError: Cannot assign to tuple items [PYJS2001]
        help: Use a list when items need to be changed.
        """,
        filename="tuple_assignment.py",
    )


def test_tuple_item_deletion_reports_immutable_sequence():
    ad(
        """\
        def main():
            values = (1, 2)
            del values[0]
        """,
        """
          File "tuple_deletion.py", line 3
            del values[0]
                ^^^^^^^^^
        pyjs.CompilationError: Cannot delete tuple items [PYJS2001]
        help: Use a list when items need to be changed.
        """,
        filename="tuple_deletion.py",
    )


def test_local_name_deletion_reports_unsupported_semantics():
    ad(
        """\
        def main():
            temporary = 1
            del temporary
        """,
        """
          File "local_deletion.py", line 3
            del temporary
                ^^^^^^^^^
        pyjs.CompilationError: Deleting local names is not supported [PYJS2001]
        help: Let local values go out of scope instead of deleting them.
        """,
        filename="local_deletion.py",
    )


def test_multi_target_assignment():
    at(
        "a = b = c = c = 9",
        """
        $assignment0: int = 9
        a: int = $assignment0
        b: int = $assignment0
        c: int = $assignment0
        c = $assignment0
        """,
        """
        var $assignment0 = 9;
        var a = $assignment0;
        var b = $assignment0;
        var c = $assignment0;
        c = $assignment0;
        """
    )


def test_multi_target_reassignment():
    at(
        """
        a = 9
        a = b = 10
        """,
        """
        a: int = 9
        $assignment1: int = 10
        a = $assignment1
        b: int = $assignment1
        """,
        """
        var a = 9;
        var $assignment1 = 10;
        a = $assignment1;
        var b = $assignment1;
        """
    )


def test_unpacking_assignment():
    aat(
        "a, b = (1, 2)",
        "a, b = (1, 2)",
        "var [a, b] = [1, 2];"
    )


def test_unpacking_assignment_uses_function_result_types():
    at(
        """
        @js
        def pair() -> tuple[int, str]:
            return 1, "two"

        def main():
            number, text = pair()
            print(number + 1)
            print(text + "!")
        """,
        """
        def pair() -> tuple[int, str]:
            return (1, 'two')

        def main() -> None:
            number, text = pair()
            print(number.[int]__add__!(1))
            print(text.[str]__add__!('!'))
        """,
        """
        export function pair() {
            return [1, 'two'];
        }

        export function main() {
            var [number, text] = pair();
            console.log(number + 1);
            console.log(text + '!');
        }
        """,
    )


def test_nested_and_attribute_unpacking_preserve_types():
    at(
        """
        @js
        class Point:
            def __init__(self):
                self.x = 0.0
                self.y = 0.0

            def move(self, value: tuple[float, float]):
                self.x, self.y = value

        def main():
            index, (name, score) = (1, ("a", 2.0))
            point = Point()
            point.move((3.0, 4.0))
        """,
        """
        class Point:

            def __init__() -> None:
                self.x = 0.0
                self.y = 0.0

            def move(value: tuple__float_float) -> None:
                $unpack = value
                self.x = $unpack[0]
                self.y = $unpack[1]

        def main() -> None:
            index, (name, score) = (1, ('a', 2.0))
            point: Point = Point()
            point.[Point]move((3.0, 4.0))
        """,
        """
        export class Point {

            constructor() {
                this.x = 0.0;
                this.y = 0.0;
            }

            move(value) {
                const $unpack0 = value;
                this.x = $unpack0[0];
                this.y = $unpack0[1];
            }
        }

        export function main() {
            var [index, [name, score]] = [1, ['a', 2.0]];
            var point = new Point();
            point.move([3.0, 4.0]);
        }
        """,
    )


def test_nested_literal_list_unpacking_has_a_statically_known_length():
    at(
        """
        def main():
            first, (second, third) = (1, [2, 3])
            print(first, second, third)
        """,
        """
        def main() -> None:
            first, (second, third) = (1, [2, 3])
            print(first, second, third)
        """,
        """
        export function main() {
            var [first, [second, third]] = [1, [2, 3]];
            console.log(first, second, third);
        }
        """,
    )


def test_list_unpacking_uses_shared_runtime_arity_check():
    at(
        """
        @js
        def values() -> list[int]:
            return [1, 2]

        def main():
            first, second = values()
            print(first + second)
        """,
        """
        def values() -> list[int]:
            return [1, 2]

        def main() -> None:
            first, second = $require_unpack_count(values(), 2)
            print(first.[int]__add__!(second))
        """,
        """
        import { require_unpack_count as $require_unpack_count } from './pyjs.python.js';

        export function values() {
            return [1, 2];
        }

        export function main() {
            var [first, second] = $require_unpack_count(values(), 2);
            console.log(first + second);
        }
        """,
    )


def test_unpacking_assignment_reports_static_arity_mismatch():
    ad(
        """\
        def main():
            first, second = (1, 2, 3)
        """,
        """
          File "unpacking.py", line 2
            first, second = (1, 2, 3)
            ^^^^^^^^^^^^^
        pyjs.CompilationError: cannot unpack 3 values into 2 targets [PYJS1103]
        help: Use one target for each statically known value.
        """,
        filename="unpacking.py",
    )
    ad(
        """\
        def main():
            first, second = [1, 2, 3]
        """,
        """
          File "list_unpacking.py", line 2
            first, second = [1, 2, 3]
            ^^^^^^^^^^^^^
        pyjs.CompilationError: cannot unpack 3 values into 2 targets [PYJS1103]
        help: Use one target for each statically known value.
        """,
        filename="list_unpacking.py",
    )


def test_starred_unpacking_uses_a_typed_runtime_transform():
    at(
        """
        def main():
            first, *middle, last = (1, "two", 3.0, 4)
            selected = middle[0]
            print(first, selected, last)
        """,
        """
        def main() -> None:
            first, middle, last = $unpack_starred((1, 'two', 3.0, 4), 1, 1)
            selected: str | float = $get_list_item(middle, 0)
            print(first, selected, last)
        """,
        """
        import { unpack_starred as $unpack_starred, get_list_item as $get_list_item } from './pyjs.python.js';

        export function main() {
            var [first, middle, last] = $unpack_starred([1, 'two', 3.0, 4], 1, 1);
            var selected = $get_list_item(middle, 0);
            console.log(first, selected, last);
        }
        """,
    )


def test_unpacking_assignment_rejects_chained_targets():
    ad(
        """\
        def main():
            first, second = left, right = (1, 2)
        """,
        """
          File "chained_unpacking.py", line 2
            first, second = left, right = (1, 2)
            ^^^^^^^^^^^^^
        pyjs.CompilationError: chained unpacking assignments are not supported [PYJS2001]
        help: Use a separate unpacking statement for each target group.
        """,
        filename="chained_unpacking.py",
    )


def test_nested_starred_unpacking_has_a_focused_diagnostic():
    ad(
        """\
        def main():
            first, (*middle, last) = (1, (2, 3))
        """,
        """
          File "nested_starred_unpacking.py", line 2
            first, (*middle, last) = (1, (2, 3))
                    ^^^^^^^
        pyjs.CompilationError: starred unpacking targets are not supported [PYJS2001]
        help: Use slicing to collect the remaining values explicitly.
        """,
        filename="nested_starred_unpacking.py",
    )


def test_starred_unpacking_reports_a_static_minimum_arity_mismatch():
    ad(
        """\
        def main():
            first, *middle, last = (1,)
        """,
        """
          File "starred_unpacking_arity.py", line 2
            first, *middle, last = (1,)
            ^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: not enough values to unpack (expected at least 2, got 1) [PYJS1103]
        help: Provide enough values for every non-starred target.
        """,
        filename="starred_unpacking_arity.py",
    )
    ad(
        """\
        def main():
            first, *middle, last = [1]
        """,
        """
          File "starred_list_unpacking_arity.py", line 2
            first, *middle, last = [1]
            ^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: not enough values to unpack (expected at least 2, got 1) [PYJS1103]
        help: Provide enough values for every non-starred target.
        """,
        filename="starred_list_unpacking_arity.py",
    )


def test_unpacking_rejects_dynamic_nested_lists_without_individual_targets():
    ad(
        """\
        from pyjs import js

        @js
        def values() -> tuple[int, list[int]]:
            return (1, [2, 3])

        def main():
            first, (second, third) = values()
        """,
        """
          File "nested_list.py", line 8
            first, (second, third) = values()
                   ^^^^^^^^^^^^^^^
        pyjs.CompilationError: nested list unpacking requires a statically known length [PYJS2001]
        help: Use a tuple for the nested value or unpack it separately.
        """,
        filename="nested_list.py",
    )


def test_unpacking_can_declare_a_local_alongside_an_attribute_store():
    at(
        """
        @js
        class Point:
            def __init__(self):
                self.x = 0

        def main():
            point = Point()
            value, point.x = (1, 2)
        """,
        """
        class Point:

            def __init__() -> None:
                self.x = 0

        def main() -> None:
            point: Point = Point()
            $unpack = (1, 2)
            value: int = $unpack[0]
            point.x = $unpack[1]
        """,
        """
        export class Point {

            constructor() {
                this.x = 0;
            }
        }

        export function main() {
            var point = new Point();
            const $unpack0 = [1, 2];
            var value = $unpack0[0];
            point.x = $unpack0[1];
        }
        """,
    )


@pytest.mark.parametrize("targets", ["box.left, box.right", "items[0], items[1]", "fresh, box.left"])
@pytest.mark.parametrize("values", ["[1]", "[1, 2, 3]"])
def test_literal_list_unpacking_checks_arity_before_individual_stores(targets, values):
    source = f'''\
from pyjs import js
@js
class Box:
    def __init__(self):
        self.left = -1
        self.right = -1
def main():
    box = Box()
    items = [-1, -1]
    {targets} = {values}
'''
    count = 1 if values == "[1]" else 3
    expected = ('  File "literal_unpack.py", line 10\n'
                f'    {targets} = {values}\n'
                f'    {"^" * len(targets)}\n'
                f'pyjs.CompilationError: cannot unpack {count} values into 2 targets [PYJS1103]\n'
                'help: Use one target for each statically known value.\n')
    ad(source, expected, filename="literal_unpack.py")


@pytest.mark.parametrize("assignment, underline, diagnostic", [
    ('other, box.value = (1, "bad")', '       ^^^^^^^^^',
     "Cannot assign str to 'value' of type int [PYJS1103]\n"
     "help: Assign a value compatible with int or change the annotation for 'value'."),
    ('other, box.readonly = (1, 2)', '       ^^^^^^^^^^^^',
     "Property 'readonly' is read-only [PYJS1103]\n"
     "help: Define a client-side setter on Box."),
    ('other, box.small = (1, int16(2))', '',
     'different fixed-width numeric types cannot be assigned implicitly [PYJS1104]\n'
     'help: Convert the value to the destination fixed-width type first.'),
])
def test_unpacking_attribute_stores_preserve_types_setters_and_representations(assignment, underline, diagnostic):
    source = '''from pyjs import js, int8, int16
@js
class Box:
    def __init__(self):
        self.value = 1
        self.small: int8 = int8(1)
    @property
    def readonly(self) -> int:
        return self.value
def main():
    box = Box()
    ''' + assignment + '\n'
    expected = ('  File "unpack_boundary.py", line 12\n'
                f'    {assignment}\n' + (f'    {underline}\n' if underline else '')
                + f'pyjs.CompilationError: {diagnostic}')
    ad(source, expected, filename="unpack_boundary.py")


def test_augmented_assignment():
    at(
        """
        x = 2
        x += 3
        """,
        """
        x: int = 2
        x = x.[int]__add__!(3)
        """,
        """
        var x = 2;
        x = x + 3;
        """
    )


def test_augmented_assignment_with_undefined_value():
    ad(
        """\
        def main():
            c += x
        """,
        """
          File "augmented.py", line 2
            c += x
            ^
        pyjs.CompilationError: Name 'c' is not defined [PYJS1001]
        """,
        filename="augmented.py",
    )


def test_augmented_instance_field_assignment():
    at(
        """
        @js
        class Counter:
            def __init__(self):
                self.value = 1

            def advance(self):
                self.value += 2

        def main():
            counter = Counter()
            counter.advance()
            return counter.value
        """,
        """
        class Counter:

            def __init__() -> None:
                self.value = 1

            def advance() -> None:
                $assignment2: Counter = self
                $assignment2.value = $assignment2.value.[int]__add__!(2)

        def main() -> int:
            counter: Counter = Counter()
            counter.[Counter]advance()
            return counter.value
        """,
        """
        export class Counter {

            constructor() {
                this.value = 1;
            }

            advance() {
                var $assignment2 = this;
                $assignment2.value = $assignment2.value + 2;
            }
        }

        export function main() {
            var counter = new Counter();
            counter.advance();
            return counter.value;
        }
        """,
    )


def test_annotation_only_instance_field_is_readable_before_any_assignment_analysis():
    at(
        """
        @js
        class Deferred:
            value: int

        @js
        def read(value: Deferred) -> int:
            return value.value

        def main():
            item = Deferred()
            item.value = 7
            return read(item)
        """,
        """
        class Deferred:

        def read(value: Deferred) -> int:
            return value.value

        def main() -> int:
            item: Deferred = Deferred()
            item.value = 7
            return read(item)
        """,
        """
        export class Deferred {
        }

        export function read(value) {
            return value.value;
        }

        export function main() {
            var item = new Deferred();
            item.value = 7;
            return read(item);
        }
        """,
    )

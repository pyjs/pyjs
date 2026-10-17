"""Inherited declarations share slots; pointer width alone is not a contract."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM

ITEMS = '''
from typing import Literal
class Item:
    def __init__(self, value: int): self.value = value
class Child(Item):
    def __init__(self, value: int):
        super().__init__(value)
        self.extra = 5
'''


@pytest.mark.parametrize(("base", "derived", "initial", "replacement"), [
    ("Item", "Child", "Item(1)", "Child(2)"),
    ("Child", "Item", "Child(1)", "Item(2)"),
    ("Item | None", "Child | None", "Item(1)", "Child(2)"),
    ("Item | None", "Item", "None", "Item(2)"),
    ("Item", "Item | None", "Item(1)", "None"),
    ("str", "bytes", "'base'", "b'child'"),
    ("Literal['base', 'child']", "Literal['child']", "'base'", "'child'"),
])
def test_inherited_fields_cannot_redeclare_pointer_payloads(base, derived, initial, replacement):
    with pytest.raises(LLVMUnsupported, match="inherited fields require invariant types.*at line"):
        transpile_llvm(ITEMS + f'''
class Base:
    def __init__(self): self.item: {base} = {initial}
class Derived(Base):
    def __init__(self):
        super().__init__()
        self.item: {derived} = {replacement}
def main() -> int:
    box = Derived()
    alias: Base = box
    original: {base} = {initial}
    alias.item = original
    return 0
''')


def inherited_assignment_source(field_type, replacement, method, *, annotated):
    annotation = f": {field_type}" if annotated else ""
    initialize = "super().__init__()" if method == "__init__" else "pass"
    invoke = "instance.reset()" if method == "reset" else "pass"
    return ITEMS + f'''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self): self.item: {field_type} = Item(1)
class Derived(Base):
    def {method}(self):
        {initialize}
        self.item{annotation} = {replacement}
def main() -> int:
    gc_set_threshold(1)
    instance = Derived()
    {invoke}
    alias: Base = instance
    initial = alias.item
    previous = 0 if initial is None else initial.value
    alias.item = Item(8)
    gc_collect()
    item = alias.item
    return previous * 10 + (0 if item is None else item.value)
'''


@pytest.mark.parametrize(("field_type", "replacement"), [("Item", "Child(2)"), ("Item | None", "None")])
@pytest.mark.parametrize("method", ["__init__", "reset"])
@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotated", [False, True], ids=["inherited", "repeated"])
def test_base_annotation_preserves_inherited_assignment_contract(tmp_path, field_type, replacement, method, optimize, annotated):
    # Ordinary writes reuse the base declaration; repeating its annotation is
    # allowed but no longer necessary to avoid inventing narrower storage.
    source = inherited_assignment_source(field_type, replacement, method, annotated=annotated)
    comparison = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"),
    )
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("declaration, parameter, initial", [
    ("item: Item | None", "", "None"),
    ("pass", ", item: Item | None = None", "item"),
], ids=["class-body", "parameter-derived"])
@pytest.mark.parametrize("repeated", [False, True])
def test_other_field_declaration_forms_keep_explicit_storage_boundary(tmp_path, declaration, parameter, initial, repeated):
    source = ITEMS + f'''
class Base:
    {declaration}
    def __init__(self{parameter}): self.item = {initial}
class Derived(Base):
    def reset(self):
        self.item{": Item | None" if repeated else ""} = Child(2)
def main() -> int:
    instance = Derived()
    instance.reset()
    alias: Base = instance
    item = alias.item
    return 0 if item is None else item.value
'''
    if not repeated and parameter:
        with pytest.raises(LLVMUnsupported, match="inherited fields require invariant types"):
            transpile_llvm(source)
    else:
        comparison = LLVM().assert_matches_python(source, directory=tmp_path,
            sanitizers=("address", "undefined"))
        assert comparison.native.stderr == ""


@pytest.mark.parametrize(("base", "derived", "value"), [
    ("Item", "Child", "Item(3)"),
    ("Item | None", "Item", "None"),
    ("object", "Item", "Item(3)"),
    ("str", "bytes", "'hello'"),
    ("str", "object", "'hello'"),
    ("Literal['base', 'child']", "Literal['child']", "'base'"),
])
@pytest.mark.parametrize("binding", ["positional", "keyword"])
def test_override_inputs_accept_the_base_contract_without_adaptation(base, derived, value, binding):
    star = "*, " if binding == "keyword" else ""
    argument = "item=" if binding == "keyword" else ""
    with pytest.raises(LLVMUnsupported, match="overrides require compatible parameter and result types.*at line"):
        transpile_llvm(ITEMS + f'''
class Base:
    def read(self, {star}item: {base}) -> int: return 1
class Derived(Base):
    def read(self, {star}item: {derived}) -> int: return 2
def main() -> int:
    Child(1)
    receiver: Base = Derived()
    return receiver.read({argument}{value})
''')


@pytest.mark.parametrize(("base", "derived", "initial", "result"), [
    ("Child", "Item", "Child(1)", "Item(2)"),
    ("Item", "Item | None", "Item(1)", "None"),
    ("Literal['child']", "Literal['base', 'child']", "'child'", "'base'"),
])
def test_override_results_cannot_publish_incompatible_pointer_payloads(base, derived, initial, result):
    with pytest.raises(LLVMUnsupported, match="overrides require compatible parameter and result types.*at line"):
        transpile_llvm(ITEMS + f'''
class Base:
    def make(self) -> {base}: return {initial}
class Derived(Base):
    def make(self) -> {derived}: return {result}
def main() -> int:
    Child(1)
    receiver: Base = Derived()
    receiver.make()
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_safe_application_declarations_preserve_value_flow(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(ITEMS + '''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self): self.item: Item | None = None
    def read(self, item: Child | None) -> int:
        return 0 if item is None else item.extra
    def make(self) -> Item: return Item(1)
    def erased(self, item: Item) -> int: return item.value
class Derived(Base):
    def __init__(self):
        super().__init__()
        self.item: Item | None = Child(2)
    def read(self, item: Item | None) -> int:
        gc_collect()
        return 3 if item is None else item.value
    def make(self) -> Child: return Child(4)
    def erased(self, item: object) -> int:
        gc_collect()
        return 5 if isinstance(item, Item) else 0
def main() -> str:
    gc_set_threshold(1)
    receiver: Base = Derived()
    receiver.item = Item(8)
    gc_collect()
    return str((receiver.read(Child(6)), receiver.read(None),
                receiver.make().value, receiver.erased(Item(9))))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_declarations_preserve_compatible_refinements(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import Literal
class Base:
    def label(self, value: Literal['input']) -> Literal['left', 'right']: return 'left'
class Derived(Base):
    def label(self, value: Literal['input', 'other']) -> Literal['right']: return 'right'
def main() -> str:
    receiver: Base = Derived()
    return receiver.label('input')
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("base", "derived"), [("int32", "uint32"), ("int", "int64")])
@pytest.mark.parametrize("boundary", ["field", "parameter", "keyword", "result"])
def test_equal_width_declarations_cannot_change_numeric_representation(base, derived, boundary):
    if boundary == "field":
        declaration = "def __init__(self): self.value: TYPE = TYPE(1)"
        use = "return int(receiver.value)"
    elif boundary in {"parameter", "keyword"}:
        star = "*, " if boundary == "keyword" else ""
        declaration = f"def read(self, {star}value: TYPE) -> int: return int(value)"
        use = f"return receiver.read(value={base}(1))"
    else:
        declaration = "def read(self) -> TYPE: return TYPE(1)"
        use = "return int(receiver.read())"
    # Shared analysis checks positional parameters and results. Fields and
    # keyword-only parameters also need the native declaration check.
    native = boundary in {"field", "keyword"}
    error = LLVMUnsupported if native else CompilationError
    message = ("declarations require matching storage representations.*at line" if native
               else "changes the represented storage contract")
    with pytest.raises(error, match=message):
        transpile_llvm(f'''
from pyjs import int32, uint32, int64
class Base:
    {declaration.replace("TYPE", base)}
class Derived(Base):
    {declaration.replace("TYPE", derived)}
def main() -> int:
    Base()
    receiver: Base = Derived()
    {use}
''')

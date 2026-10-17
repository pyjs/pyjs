import ctypes

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import objects
from pyjs.native.runtime.pointers import Pointer
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions, runtime_library


def test_application_vtables_share_the_runtime_ancestry_prefix():
    source = '''
        class Base:
            def value(self) -> int:
                return 1
        class Child(Base):
            def value(self) -> int:
                return 2
        class Leaf(Child):
            pass
        def read(value: Base) -> int:
            return value.value()
        def main() -> int:
            return read(Base()) + read(Child()) + read(Leaf())
    '''
    # Only the immutable tables are the contract here; comparing all runtime
    # scaffolding would obscure the exact header and inherited-slot layout.
    tables = [line for line in transpile_llvm(source).splitlines()
              if line.startswith(("%vtable.", "@vtable."))]
    assert tables == [
        "%vtable.type.Base = type { ptr, ptr, i64 }",
        "@vtable.Base = private constant %vtable.type.Base { ptr null, ptr @fn.Base.value, i64 16 }",
        "@vtable.Child = private constant %vtable.type.Base { ptr @vtable.Base, ptr @fn.Child.value, i64 17 }",
        "@vtable.Leaf = private constant %vtable.type.Base { ptr @vtable.Child, ptr @fn.Child.value, i64 18 }",
    ]
    LLVM().assert_matches_python(source)


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def object_runtime(request, tmp_path_factory):
    operations = {
        "pyjs.runtime.typeof.with.types": objects.type_of,
        "pyjs.runtime.isinstance.with.types": objects.is_instance,
        "pyjs.object.reference.value.with.types": objects.reference_value,
        "pyjs.object.reference.truth.with.types": objects.reference_truth,
        "pyjs.object.scalar.truth.with.types": objects.scalar_truth,
        "pyjs.callable.identity.with.adapters": objects.callable_identity,
    }
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join([
        *objects.compiled_object_runtime(), *objects.compiled_callable_runtime(),
    ]))
    return runtime_functions(operations, library)


def test_callable_identity_unwraps_only_known_adapters(object_runtime):
    adapters = (ctypes.c_void_p * 2)(11, 22)
    table = Pointer(ctypes.addressof(adapters))
    # A callable is a code/context pair. Unknown code must stop traversal before
    # reading the deliberately invalid context, even after a long adapter chain.
    pair = ctypes.c_void_p * 2
    target = pair(99, 1)
    expected = ctypes.addressof(target)
    chain = (pair * 1000)()
    for index, value in enumerate(chain):
        value[0] = adapters[index % 2]
        value[1] = ctypes.addressof(chain[index - 1]) if index else expected
    for head in (0, expected, ctypes.addressof(chain[0]), ctypes.addressof(chain[-1])):
        assert object_runtime("pyjs.callable.identity.with.adapters", Pointer(head), table, 2).address == (
            expected if head else 0)
        assert object_runtime("pyjs.callable.identity.with.adapters", Pointer(head), Pointer(0), 0).address == head
    chain[0][1] = None
    assert object_runtime("pyjs.callable.identity.with.adapters", Pointer(ctypes.addressof(chain[-1])), table, 2).address == 0


def test_type_tables_bound_ancestry_and_preserve_boxed_truth(object_runtime):
    integer = objects._Type()
    boolean = objects._Type(ctypes.addressof(integer))
    floating = objects._Type()
    reference = objects._Type()
    application = objects._Type(ctypes.addressof(reference))
    types = (ctypes.c_void_p * 5)(*[ctypes.addressof(item) for item in
                                  (boolean, integer, floating, reference, application)])
    references = (ctypes.c_void_p * 1)(ctypes.addressof(reference))
    table = Pointer(ctypes.addressof(types))
    refs = Pointer(ctypes.addressof(references))
    boolean_ptr, integer_ptr, floating_ptr, reference_ptr, application_ptr = map(Pointer, types)
    for value, expected in ((0, 0), (1, 1), (-1, 1)):
        box = objects._Scalar(ctypes.addressof(integer), value)
        pointer = Pointer(ctypes.addressof(box))
        assert object_runtime("pyjs.runtime.typeof.with.types", pointer, table, 5).address == integer_ptr.address
        assert object_runtime("pyjs.object.scalar.truth.with.types", pointer,
                              boolean_ptr, integer_ptr, floating_ptr, refs, 1) == bool(expected)
    for value in (0.0, -0.0, 1.5, float("nan"), float("inf")):
        box = objects._Scalar(ctypes.addressof(floating), 0)
        ctypes.c_double.from_address(ctypes.addressof(box) + objects.VALUE_OFFSET).value = value
        assert object_runtime("pyjs.object.scalar.truth.with.types", Pointer(ctypes.addressof(box)),
                              boolean_ptr, integer_ptr, floating_ptr, refs, 1) == bool(value)
    box = objects._Scalar(ctypes.addressof(boolean), 1)
    pointer = Pointer(ctypes.addressof(box))
    assert object_runtime("pyjs.runtime.isinstance.with.types", pointer, integer_ptr, table, 5)
    assert not object_runtime("pyjs.runtime.isinstance.with.types", pointer, floating_ptr, table, 5)
    # Unknown first words must never be followed as parent pointers.
    box.type = 1
    for count in (0, 5):
        assert object_runtime("pyjs.runtime.typeof.with.types", pointer, table, count).address == 0
        assert not object_runtime("pyjs.runtime.isinstance.with.types", pointer, integer_ptr, table, count)
    assert object_runtime("pyjs.runtime.typeof.with.types", Pointer(0), Pointer(0), 5).address == 0
    assert not object_runtime("pyjs.object.scalar.truth.with.types", Pointer(0),
                              boolean_ptr, integer_ptr, floating_ptr, refs, 1)
    for fixed in (-1, 0, 2):
        live = ctypes.c_int64(0)
        box = objects._Reference(reference_ptr.address, ctypes.addressof(live), fixed, 0)
        pointer = Pointer(ctypes.addressof(box))
        for length in (0, 3, 0):
            live.value = length
            assert object_runtime("pyjs.object.reference.value.with.types", pointer, refs, 1).address == ctypes.addressof(live)
            assert object_runtime("pyjs.object.reference.truth.with.types", pointer, refs, 1) == bool(
                fixed if fixed >= 0 else length)
        # An application class inherits the type, not the boxed storage layout.
        box.type = application_ptr.address
        assert object_runtime("pyjs.runtime.isinstance.with.types", pointer, reference_ptr, table, 5)
        assert object_runtime("pyjs.object.reference.value.with.types", pointer, refs, 1).address == pointer.address
        assert object_runtime("pyjs.object.reference.truth.with.types", pointer, refs, 1)

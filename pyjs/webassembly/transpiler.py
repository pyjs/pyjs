"""Emit a small executable WebAssembly module directly from ProgramIR."""

import ast
import struct
import textwrap
from dataclasses import dataclass
from pathlib import Path

from pyjs.analysis.analyzer import analyzed_value_type, iterable_item_type
from pyjs.analysis.ir import (
    Block,
    BlockArgument,
    Branch,
    CollectionNew,
    FieldLoad,
    FieldStore,
    IteratorCreate,
    IteratorNext,
    Jump,
    ListAppend,
    ObjectNew,
    ProgramIR,
    Raise,
    Return,
    build_program_ir,
)
from pyjs.analysis.objects import (
    Class,
    Function,
    Instance,
    TypeVariableClass,
    UnionType,
    UnpackAssignment,
    UnpackItem,
)
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import (
    analyzed_array_format,
    analyzed_numeric_format,
    analyzed_value_object,
)
from pyjs.numeric import NumericFormat
from pyjs.python import native as native_builtins
from pyjs.stdlib.math import cos, hypot, isfinite, radians, sin, sqrt

from . import memory as linear_memory
from .analysis import WEBASSEMBLY_ENVIRONMENT

I32 = 0x7F
I64 = 0x7E
F32 = 0x7D
F64 = 0x7C
EMPTY = 0x40
UNREACHABLE = 0x00
BLOCK = 0x02
LOOP = 0x03
IF = 0x04
ELSE = 0x05
END = 0x0B
BR = 0x0C
BR_IF = 0x0D
RETURN = 0x0F
CALL = 0x10
DROP = 0x1A
LOCAL_GET = 0x20
LOCAL_SET = 0x21
LOCAL_TEE = 0x22
I32_CONST = 0x41
I64_CONST = 0x42
F64_CONST = 0x44
I32_EQZ = 0x45
I32_EQ = 0x46
I32_NE = 0x47
I32_LT_S = 0x48
I32_LT_U = 0x49
I32_GT_S = 0x4A
I64_EQZ = 0x50
I64_EQ = 0x51
I64_LT_S = 0x53
I64_LT_U = 0x54
I64_GT_S = 0x55
I64_GE_S = 0x59
I32_ADD = 0x6A
I32_MUL = 0x6C
I32_AND = 0x71
I32_OR = 0x72
I32_XOR = 0x73
I64_ADD = 0x7C
I64_SUB = 0x7D
I64_MUL = 0x7E
F64_EQ = 0x61
F64_NE = 0x62
F64_LT = 0x63
F64_GT = 0x64
F64_LE = 0x65
F64_GE = 0x66
F64_ABS = 0x99
F64_NEG = 0x9A
F64_SQRT = 0x9F
F64_ADD = 0xA0
F64_SUB = 0xA1
F64_MUL = 0xA2
F64_DIV = 0xA3
I64_DIV_S = 0x7F
I64_DIV_U = 0x80
I64_REM_S = 0x81
I64_REM_U = 0x82
I64_AND = 0x83
I64_OR = 0x84
I64_SHR_U = 0x88
I64_SHL = 0x86
I64_SHR_S = 0x87
I64_XOR = 0x85
I64_LT_U = 0x54
F64_CONVERT_I32_S = 0xB7
F64_CONVERT_I64_S = 0xB9
F64_REINTERPRET_I64 = 0xBF
I64_CLZ = 0x79
I64_TRUNC_F64_S = 0xB0
F32_DEMOTE_F64 = 0xB6
F64_PROMOTE_F32 = 0xBB
I32_WRAP_I64 = 0xA7
I64_EXTEND_I32_S = 0xAC
I64_EXTEND_I32_U = 0xAD
I32_EXTEND8_S = 0xC0
I32_EXTEND16_S = 0xC1
REF_NULL = 0xD0
REF_IS_NULL = 0xD1
I32_LOAD = 0x28
F32_LOAD = 0x2A
F64_LOAD = 0x2B
I32_STORE = 0x36
F32_STORE = 0x38
F64_STORE = 0x39
MEMORY_SIZE = 0x3F
MEMORY_GROW = 0x40
GC_PREFIX = 0xFB
STRUCT_NEW = 0
STRUCT_NEW_DEFAULT = 1
STRUCT_GET = 2
STRUCT_GET_S = 3
STRUCT_GET_U = 4
STRUCT_SET = 5
ARRAY_NEW_DEFAULT = 7
ARRAY_NEW_FIXED = 8
ARRAY_GET = 11
ARRAY_SET = 14
ARRAY_LEN = 15
ARRAY_COPY = 17
RECURSIVE_TYPE = 0x4E
ARRAY_TYPE = 0x5E
STRUCT_TYPE = 0x5F
FUNCTION_TYPE = 0x60
PACKED_I8 = 0x78
PACKED_I16 = 0x77

ValueType = int | bytes


class WebAssemblyUnsupported(Exception):
    """A program uses semantics outside the initial WebAssembly subset."""

    def __init__(self, message: str, node: ast.AST | None = None) -> None:
        location = (
            f" at line {node.lineno}"
            if node is not None and hasattr(node, "lineno")
            else ""
        )
        super().__init__(f"{message}{location}")


def _unsigned(value: int) -> bytes:
    """Encode one unsigned LEB128 integer."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def _signed(value: int) -> bytes:
    """Encode one signed LEB128 integer."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        done = (value == 0 and not byte & 0x40) or (
            value == -1 and bool(byte & 0x40)
        )
        result.append(byte if done else byte | 0x80)
        if done:
            return bytes(result)


def _vector(values: list[bytes]) -> bytes:
    return _unsigned(len(values)) + b"".join(values)


def _encoded_type(value_type: ValueType) -> bytes:
    if isinstance(value_type, int):
        return bytes((value_type,))
    return value_type


def _name(value: str) -> bytes:
    encoded = value.encode()
    return _unsigned(len(encoded)) + encoded


def _section(section: int, payload: bytes) -> bytes:
    return bytes((section,)) + _unsigned(len(payload)) + payload


@dataclass(frozen=True)
class WebAssemblyCompilation:
    """One directly executable WebAssembly binary module."""

    binary: bytes

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.binary)
        return path


@dataclass(frozen=True)
class _ListIterator:
    value_type: Class
    source_slot: str
    index_slot: str
    layout: object


@dataclass(frozen=True)
class _RangeIterator:
    current_slot: str
    stop_slot: str
    step_slot: str
    item_type: Class


@dataclass(frozen=True)
class _EnumerateIterator:
    source: object
    index_slot: str
    item_type: Class


@dataclass(frozen=True)
class _ZipIterator:
    sources: tuple[object, ...]
    item_type: Class
    strict: bool
    availability_slot: str | None


@dataclass(frozen=True)
class _ComprehensionLoop:
    iterable: ast.expr
    iterator: object
    target: ast.expr
    aliases: dict[str, str]
    filters: tuple[ast.expr, ...]


@dataclass(frozen=True)
class _ListComprehension:
    value_type: Class
    result_slot: str
    item_slot: str
    array_slot: str
    capacity_slot: str
    loops: tuple[_ComprehensionLoop, ...]


class WebAssemblyEmitter:
    """Lower typed ProgramIR through a direct binary state-machine CFG."""

    INTEGER_OPERATORS = {
        "__add__": 0x7C,
        "__sub__": 0x7D,
        "__mul__": 0x7E,
        "__and__": 0x83,
        "__or__": 0x84,
        "__xor__": 0x85,
    }
    INTEGER_COMPARISONS = {
        "__eq__": 0x51,
        "__ne__": 0x52,
        "__lt__": 0x53,
        "__gt__": 0x55,
        "__le__": 0x57,
        "__ge__": 0x59,
    }
    BOOLEAN_OPERATORS = {
        "__and__": 0x71,
        "__or__": 0x72,
        "__xor__": 0x73,
    }
    FLOAT_OPERATORS = {
        "__add__": F64_ADD,
        "__sub__": F64_SUB,
        "__mul__": F64_MUL,
    }
    FLOAT_COMPARISONS = {
        "__eq__": F64_EQ,
        "__ne__": F64_NE,
        "__lt__": F64_LT,
        "__gt__": F64_GT,
        "__le__": F64_LE,
        "__ge__": F64_GE,
    }
    LINEAR_MEMORY_FUNCTIONS = frozenset(
        {
            linear_memory.grow_memory,
            linear_memory.load_f32,
            linear_memory.load_f64,
            linear_memory.load_i32,
            linear_memory.memory_byte_length,
            linear_memory.store_f32,
            linear_memory.store_f64,
            linear_memory.store_i32,
        }
    )
    MATH_IMPORTS = ((sin, "sin"), (cos, "cos"))
    MATH_IMPORT_FUNCTIONS = frozenset(
        function for function, _ in MATH_IMPORTS
    )

    def emit(
        self,
        program: ProgramIR,
        exported_functions: tuple[tuple[str, Function], ...] = (),
    ) -> WebAssemblyCompilation:
        application_classes = [
            layout
            for layout in program.classes
            if not getattr(layout.value_type.py_obj, "__builtin__", False)
        ]
        self.classes = {
            layout.value_type: layout for layout in application_classes
        }
        self.class_names = {
            layout.value_type.name: layout.value_type
            for layout in application_classes
        }
        self.class_indices = {
            layout.value_type: index
            for index, layout in enumerate(application_classes)
        }
        self.functions = [
            function
            for function in program.functions
            if (function.cls is None or function.cls in self.classes)
            and function.ir is not None
            and any(isinstance(block, Block) for block in function.ir.blocks)
            and not getattr(function.py_func, "__builtin__", False)
        ]
        self.tuple_types, self.list_types = self.discover_collection_types(
            application_classes,
        )
        first_tuple_index = len(application_classes)
        self.tuple_indices = {
            value_type: first_tuple_index + index
            for index, value_type in enumerate(self.tuple_types)
        }
        first_list_index = first_tuple_index + len(self.tuple_types)
        self.list_indices = {
            value_type: (
                first_list_index + index * 2,
                first_list_index + index * 2 + 1,
            )
            for index, value_type in enumerate(self.list_types)
        }
        gc_type_count = (
            len(application_classes)
            + len(self.tuple_types)
            + len(self.list_types) * 2
        )
        self.prepare_classes(application_classes)
        if program.entry_point not in self.functions:
            raise WebAssemblyUnsupported("the WebAssembly entry point has no scalar body")
        used_math = {
            analyzed_value_object(node.func).py_func
            for function in self.functions
            for block in function.ir.blocks
            for statement in getattr(block, "body", ())
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and isinstance(analyzed_value_object(node.func), Function)
            and analyzed_value_object(node.func).py_func
            in self.MATH_IMPORT_FUNCTIONS
        }
        math_imports = [
            item for item in self.MATH_IMPORTS if item[0] in used_math
        ]
        self.import_indices = {
            function: index
            for index, (function, _) in enumerate(math_imports)
        }
        import_count = len(math_imports)
        self.indices = {
            function: import_count + index
            for index, function in enumerate(self.functions)
        }
        self.uses_linear_memory = any(
            isinstance(node, ast.Call)
            and isinstance(analyzed_value_object(node.func), Function)
            and analyzed_value_object(node.func).py_func
            in self.LINEAR_MEMORY_FUNCTIONS
            for function in self.functions
            for block in function.ir.blocks
            for statement in getattr(block, "body", ())
            for node in ast.walk(statement)
        )
        signatures = [self.signature(function) for function in self.functions]
        if math_imports:
            signatures.append(((F64,), F64))
        unique_signatures = list(dict.fromkeys(signatures))
        signature_indices = {
            signature: gc_type_count + index
            for index, signature in enumerate(unique_signatures)
        }
        type_indices = [signature_indices[value] for value in signatures]

        types = _vector(
            self.gc_type_entries(application_classes)
            + [
                bytes((FUNCTION_TYPE,))
                + _vector([_encoded_type(value) for value in parameters])
                + _vector([_encoded_type(result)] if result is not None else [])
                for parameters, result in unique_signatures
            ]
        )
        function_type_indices = type_indices[: len(self.functions)]
        functions = _vector(
            [_unsigned(index) for index in function_type_indices]
        )
        imports = b""
        if math_imports:
            math_signature_index = signature_indices[((F64,), F64)]
            imports = _vector(
                [
                    _name("math")
                    + _name(name)
                    + b"\x00"
                    + _unsigned(math_signature_index)
                    for _, name in math_imports
                ]
            )
        if not exported_functions:
            exported_functions = (("main", program.entry_point),)
        for name, function in exported_functions:
            if function not in self.indices:
                raise WebAssemblyUnsupported(
                    f"WebAssembly export {name!r} has no executable body"
                )
        export_entries = [
            _name(name) + b"\x00" + _unsigned(self.indices[function])
            for name, function in exported_functions
        ]
        if self.uses_linear_memory:
            export_entries.append(_name("memory") + b"\x02" + _unsigned(0))
        exports = _vector(export_entries)
        code = _vector([self.function(function) for function in self.functions])
        memories = _vector([b"\x00" + _unsigned(1)])
        sections = [_section(1, types)]
        if math_imports:
            sections.append(_section(2, imports))
        sections.append(_section(3, functions))
        if self.uses_linear_memory:
            sections.append(_section(5, memories))
        sections.extend((_section(7, exports), _section(10, code)))
        module = b"\x00asm\x01\x00\x00\x00" + b"".join(sections)
        return WebAssemblyCompilation(module)

    def discover_collection_types(
        self,
        classes,
    ) -> tuple[list[Class], list[Class]]:
        tuples = set()
        lists = set()

        def add(value_type) -> None:
            if isinstance(value_type, UnionType):
                for member in value_type.types:
                    add(member)
                return
            if not isinstance(value_type, Class):
                return
            if value_type.generic_name == "tuple":
                item_types = tuple(value_type.generic_types.values())
                if (
                    value_type in tuples
                    or value_type.tuple_variadic
                    or any(isinstance(item, TypeVariableClass) for item in item_types)
                ):
                    return
                tuples.add(value_type)
                for item_type in item_types:
                    add(item_type)
                return
            if value_type.generic_name != "list" or value_type in lists:
                return
            item_type = self.collection_item_type(value_type)
            if isinstance(item_type, TypeVariableClass):
                return
            lists.add(value_type)
            add(item_type)

        for layout in classes:
            for field in layout.fields:
                add(field.value_type)
        for function in self.functions:
            add(function.return_type)
            for value in function.scope.names.values():
                if isinstance(value, Instance):
                    add(value.cls)
            for block in function.ir.blocks:
                for statement in getattr(block, "body", ()):
                    for node in ast.walk(statement):
                        if isinstance(node, CollectionNew):
                            add(node.value_type)
                        elif isinstance(node, IteratorCreate):
                            add(iterable_item_type(analyzed_value_type(node.iterable)))
                        elif isinstance(node, ast.ListComp):
                            add(analyzed_value_type(node))
                            for generator in node.generators:
                                add(iterable_item_type(analyzed_value_type(generator.iter)))
        return (
            sorted(tuples, key=lambda value_type: value_type.name),
            sorted(lists, key=lambda value_type: value_type.name),
        )

    def prepare_classes(self, classes) -> None:
        self.fields = {}
        self.has_recursive_fields = False
        for layout in classes:
            if layout.base in self.classes:
                raise WebAssemblyUnsupported(
                    "WebAssembly class inheritance is not implemented"
                )
            for index, field in enumerate(layout.fields):
                value_type = self.storage_type(
                    field.value_type,
                    field.numeric_format,
                    packed=True,
                )
                if isinstance(value_type, bytes):
                    self.has_recursive_fields = True
                self.fields[layout.value_type, field.name] = (
                    index,
                    value_type,
                    field.numeric_format,
                )

    def gc_type_entries(self, classes) -> list[bytes]:
        structs = [
            bytes((STRUCT_TYPE,))
            + _vector(
                [
                    _encoded_type(
                        self.storage_type(
                            field.value_type,
                            field.numeric_format,
                            packed=True,
                        )
                    )
                    + b"\x01"
                    for field in layout.fields
                ]
            )
            for layout in classes
        ]
        structs.extend(
            bytes((STRUCT_TYPE,))
            + _vector(
                [
                    _encoded_type(self.value_type(item_type)) + b"\x00"
                    for item_type in tuple_type.generic_types.values()
                ]
            )
            for tuple_type in self.tuple_types
        )
        for list_type in self.list_types:
            array_index, _list_index = self.list_indices[list_type]
            structs.extend(
                (
                    bytes((ARRAY_TYPE,))
                    + _encoded_type(self.value_type(self.collection_item_type(list_type)))
                    + b"\x01",
                    bytes((STRUCT_TYPE,))
                    + _vector(
                        [
                            self.reference_type_index(array_index) + b"\x01",
                            bytes((I32, 0x01)),
                        ]
                    ),
                )
            )
        if self.has_recursive_fields or self.tuple_types or self.list_types:
            # One group lets application objects and collection storage refer
            # to themselves and one another without ordering restrictions.
            return [bytes((RECURSIVE_TYPE,)) + _vector(structs)]
        return structs

    def signature(
        self,
        function: Function,
    ) -> tuple[tuple[ValueType, ...], ValueType | None]:
        if function.cls in self.classes and function.is_static:
            raise WebAssemblyUnsupported(
                "WebAssembly static and class methods are not implemented"
            )
        if function.vararg or function.kwarg or function.kwonlyargs or function.defaults:
            raise WebAssemblyUnsupported(
                "WebAssembly functions require fixed positional parameters"
            )
        parameters = (
            (self.reference_type(function.cls),) if function.cls in self.classes else ()
        ) + tuple(
            self.parameter_storage_type(function, parameter)
            for parameter in function.params
        )
        return parameters, self.function_return_storage_type(function)

    def function(self, function: Function) -> bytes:
        self.current_function = function
        blocks = [block for block in function.ir.blocks if isinstance(block, Block)]
        parameters = (
            [("self", self.reference_type(function.cls))]
            if function.cls in self.classes
            else []
        ) + [
            (parameter.arg, self.parameter_storage_type(function, parameter))
            for parameter in function.params
        ]
        self.local_indices = {
            name: index for index, (name, _value_type) in enumerate(parameters)
        }
        self.local_value_types = dict(parameters)
        self.local_numeric_formats = {
            parameter.arg: analyzed_numeric_format(parameter)
            for parameter in function.params
            if analyzed_numeric_format(parameter) is not None
        }
        self.local_types: list[ValueType] = []
        self.object_argument_slots = {}
        self.object_result_slots = {}
        self.field_scratch = {}
        self.list_append_slots = {}
        self.list_concat_slots = {}
        self.list_copy_slots = {}
        self.list_get_slots = {}
        self.list_set_slots = {}
        self.list_comprehensions = {}
        self.tuple_unpack_slots = {}
        self.unpack_assignment_slots = {}
        self.unpack_item_slots = {}
        self.extreme_slots = {}
        self.hypot_slots = {}
        self.iterators = {}
        self.name_aliases = {}

        def add_local(name: str, value_type: ValueType) -> None:
            if name in self.local_indices:
                if self.local_value_types[name] != value_type:
                    raise WebAssemblyUnsupported(
                        f"WebAssembly local {name} changes type"
                    )
                return
            self.local_indices[name] = len(parameters) + len(self.local_types)
            self.local_value_types[name] = value_type
            self.local_types.append(value_type)

        def add_generated_local(name: str, value_type: ValueType) -> str:
            while name in self.local_indices:
                name += "_"
            add_local(name, value_type)
            return name

        def add_assignment_target(target, value_type, prefix: str) -> None:
            if isinstance(target, (ast.Name, ast.arg, BlockArgument)):
                storage_format = self.local_numeric_format(function, target)
                name = self.target_name(target)
                add_local(
                    name,
                    self.numeric_storage_type(storage_format)
                    if storage_format is not None
                    else self.value_type(value_type),
                )
                if storage_format is not None:
                    self.local_numeric_formats[name] = storage_format
                return
            if not isinstance(target, (ast.List, ast.Tuple)):
                raise WebAssemblyUnsupported(
                    "WebAssembly assignment target is not implemented",
                    target,
                )
            if value_type.generic_name != "tuple":
                raise WebAssemblyUnsupported(
                    "WebAssembly can only unpack fixed tuples",
                    target,
                )
            item_types = tuple(value_type.generic_types.values())
            if len(target.elts) != len(item_types):
                raise WebAssemblyUnsupported(
                    "WebAssembly tuple unpacking length differs",
                    target,
                )
            scratch = add_generated_local(
                f"__pyjs_tuple_{prefix}",
                self.value_type(value_type),
            )
            self.tuple_unpack_slots[target] = (scratch, value_type)
            for index, (element, item_type) in enumerate(
                zip(target.elts, item_types, strict=True)
            ):
                add_assignment_target(element, item_type, f"{prefix}_{index}")

        def create_iterator(iterable: ast.expr, prefix: str):
            if self.is_builtin_call(iterable, "range"):
                return _RangeIterator(
                    add_generated_local(f"{prefix}_current", I64),
                    add_generated_local(f"{prefix}_stop", I64),
                    add_generated_local(f"{prefix}_step", I64),
                    iterable_item_type(analyzed_value_type(iterable)),
                )
            if self.is_builtin_call(iterable, "enumerate"):
                if (
                    not 1 <= len(iterable.args) <= 2
                    or len(iterable.keywords) > 1
                    or iterable.keywords
                    and (
                        len(iterable.args) != 1
                        or iterable.keywords[0].arg != "start"
                    )
                ):
                    raise WebAssemblyUnsupported(
                        "WebAssembly enumerate requires values and an optional start",
                        iterable,
                    )
                item_type = iterable_item_type(analyzed_value_type(iterable))
                return _EnumerateIterator(
                    create_iterator(iterable.args[0], f"{prefix}_source"),
                    add_generated_local(f"{prefix}_index", I64),
                    item_type,
                )
            if self.is_builtin_call(iterable, "zip"):
                if len(iterable.keywords) > 1 or any(
                    keyword.arg != "strict"
                    or not isinstance(keyword.value, ast.Constant)
                    or not isinstance(keyword.value.value, bool)
                    for keyword in iterable.keywords
                ):
                    raise WebAssemblyUnsupported(
                        "WebAssembly zip strict must be a constant bool",
                        iterable,
                    )
                item_type = iterable_item_type(analyzed_value_type(iterable))
                strict = bool(
                    iterable.keywords and iterable.keywords[0].value.value
                )
                sources = tuple(
                    create_iterator(argument, f"{prefix}_source_{index}")
                    for index, argument in enumerate(iterable.args)
                )
                return _ZipIterator(
                    sources,
                    item_type,
                    strict,
                    add_generated_local(f"{prefix}_available", I32)
                    if strict and sources
                    else None,
                )
            list_type = analyzed_value_type(iterable)
            if list_type.generic_name != "list":
                raise WebAssemblyUnsupported(
                    "WebAssembly iteration currently requires a list or range",
                    iterable,
                )
            _array_index, list_index = self.list_indices[list_type]
            return _ListIterator(
                list_type,
                add_generated_local(
                    f"{prefix}_source",
                    self.reference_type_index(list_index),
                ),
                add_generated_local(f"{prefix}_index", I32),
                analyzed_array_format(iterable),
            )

        def create_comprehension_target(
            target: ast.expr,
            value_type: Class,
            prefix: str,
        ) -> dict[str, str]:
            aliases = {}
            for leaf in ast.walk(target):
                if not isinstance(leaf, ast.Name):
                    continue
                alias = f"{prefix}_{leaf.id}"
                while alias in self.local_indices or alias in aliases.values():
                    alias += "_"
                aliases[leaf.id] = alias
            previous = self.name_aliases
            self.name_aliases = aliases
            try:
                add_assignment_target(target, value_type, prefix)
            finally:
                self.name_aliases = previous
            return aliases

        for block in blocks:
            for argument in block.arguments:
                storage_format = analyzed_numeric_format(argument)
                add_local(
                    argument.name,
                    self.numeric_storage_type(storage_format)
                    if storage_format is not None
                    else self.value_type(argument.value_type),
                )
                if storage_format is not None:
                    self.local_numeric_formats[argument.name] = storage_format
            for statement in self.flattened_statements(block.body):
                if isinstance(statement, ast.AnnAssign):
                    storage_format = self.local_numeric_format(
                        function,
                        statement.target,
                    )
                    value_type = (
                        self.numeric_storage_type(storage_format)
                        if storage_format is not None
                        else self.value_type(analyzed_value_type(statement.value))
                        if statement.value is not None
                        else self.annotation(statement.annotation)
                    )
                    add_local(
                        self.target_name(statement.target),
                        value_type,
                    )
                    if storage_format is not None:
                        self.local_numeric_formats[self.target_name(statement.target)] = (
                            storage_format
                        )
                elif isinstance(statement, ast.Assign):
                    value_type = analyzed_value_type(statement.value)
                    for index, target in enumerate(statement.targets):
                        add_assignment_target(target, value_type, f"assign_{index}")
                elif isinstance(statement, IteratorCreate):
                    prefix = f"__pyjs_{statement.name}"
                    self.iterators[statement.name] = create_iterator(
                        statement.iterable,
                        prefix,
                    )

        for block in blocks:
            for statement in block.body:
                if isinstance(statement, IteratorNext):
                    iterator = self.iterators[statement.iterator]
                    add_assignment_target(
                        statement.target,
                        self.iterator_item_type(iterator),
                        statement.iterator,
                    )

        for block in blocks:
            for statement in block.body:
                for node in ast.walk(statement):
                    if isinstance(node, FieldStore):
                        value_type = self.field_value_type(node.target)
                        name = add_generated_local(
                            f"__pyjs_field_{len(self.field_scratch)}",
                            value_type,
                        )
                        self.field_scratch[node] = name
                    elif isinstance(node, ObjectNew):
                        evaluation, _ordered = self.constructor_arguments(node)
                        constructor = self.classes[node.value_type].constructor
                        constructor_parameters = {
                            parameter.arg: parameter
                            for parameter in constructor.params
                        }
                        slots = {}
                        for name, value in evaluation:
                            parameter = constructor_parameters[name]
                            slot = add_generated_local(
                                f"__pyjs_object_{len(self.object_result_slots)}_{name}",
                                self.parameter_storage_type(
                                    constructor,
                                    parameter,
                                )
                                if isinstance(value, ast.Constant)
                                and value.value is None
                                else self.value_type(analyzed_value_type(value)),
                            )
                            slots[name] = slot
                        result = add_generated_local(
                            f"__pyjs_object_{len(self.object_result_slots)}_result",
                            self.reference_type(node.value_type),
                        )
                        self.object_argument_slots[node] = slots
                        self.object_result_slots[node] = result
                    elif isinstance(node, ListAppend):
                        list_type = analyzed_value_type(node.call.func.value)
                        array_index, list_index = self.list_indices[list_type]
                        prefix = f"__pyjs_list_append_{len(self.list_append_slots)}"
                        self.list_append_slots[node] = (
                            add_generated_local(
                                f"{prefix}_list",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(
                                f"{prefix}_item",
                                self.value_type(self.collection_item_type(list_type)),
                            ),
                            add_generated_local(
                                f"{prefix}_array",
                                self.reference_type_index(array_index),
                            ),
                            add_generated_local(f"{prefix}_capacity", I32),
                        )
                    elif isinstance(node, ast.Call) and self.is_list_get(node):
                        list_type = analyzed_value_type(node.func.value)
                        _array_index, list_index = self.list_indices[list_type]
                        prefix = f"__pyjs_list_get_{len(self.list_get_slots)}"
                        self.list_get_slots[node] = (
                            add_generated_local(
                                f"{prefix}_list",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(f"{prefix}_index", I64),
                            add_generated_local(f"{prefix}_actual", I64),
                        )
                    elif isinstance(node, ast.Call) and self.is_list_set(node):
                        list_type = analyzed_value_type(node.func.value)
                        _array_index, list_index = self.list_indices[list_type]
                        prefix = f"__pyjs_list_set_{len(self.list_set_slots)}"
                        self.list_set_slots[node] = (
                            add_generated_local(
                                f"{prefix}_list",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(f"{prefix}_index", I64),
                            add_generated_local(f"{prefix}_actual", I64),
                            add_generated_local(
                                f"{prefix}_item",
                                self.value_type(self.collection_item_type(list_type)),
                            ),
                        )
                    elif isinstance(node, ast.Call) and self.is_list_concat(node):
                        list_type = analyzed_value_type(node)
                        array_index, list_index = self.list_indices[list_type]
                        prefix = f"__pyjs_list_concat_{len(self.list_concat_slots)}"
                        self.list_concat_slots[node] = (
                            add_generated_local(
                                f"{prefix}_left",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(
                                f"{prefix}_right",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(
                                f"{prefix}_array",
                                self.reference_type_index(array_index),
                            ),
                            add_generated_local(f"{prefix}_left_length", I32),
                            add_generated_local(f"{prefix}_length", I32),
                        )
                    elif isinstance(node, ast.Call) and self.is_list_constructor(node):
                        list_type = analyzed_value_type(node)
                        array_index, list_index = self.list_indices[list_type]
                        prefix = f"__pyjs_list_copy_{len(self.list_copy_slots)}"
                        self.list_copy_slots[node] = (
                            add_generated_local(
                                f"{prefix}_source",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(
                                f"{prefix}_array",
                                self.reference_type_index(array_index),
                            ),
                            add_generated_local(f"{prefix}_length", I32),
                        )
                    elif isinstance(node, ast.Call) and self.is_extreme_call(node):
                        value_type = self.value_type(analyzed_value_type(node))
                        prefix = f"__pyjs_extreme_{len(self.extreme_slots)}"
                        self.extreme_slots[node] = (
                            add_generated_local(f"{prefix}_best", value_type),
                            add_generated_local(f"{prefix}_candidate", value_type),
                        )
                    elif (
                        isinstance(node, ast.Call)
                        and isinstance(analyzed_value_object(node.func), Function)
                        and analyzed_value_object(node.func).py_func is hypot
                    ):
                        prefix = f"__pyjs_hypot_{len(self.hypot_slots)}"
                        self.hypot_slots[node] = (
                            tuple(
                                add_generated_local(f"{prefix}_value_{index}", F64)
                                for index in range(len(node.args))
                            ),
                            add_generated_local(f"{prefix}_maximum", F64),
                            add_generated_local(f"{prefix}_total", F64),
                            add_generated_local(f"{prefix}_infinite", I32),
                        )
                    elif isinstance(node, ast.ListComp):
                        value_type = analyzed_value_type(node)
                        array_index, list_index = self.list_indices[value_type]
                        prefix = (
                            f"__pyjs_list_comp_{len(self.list_comprehensions)}"
                        )
                        loops = []
                        for index, generator in enumerate(node.generators):
                            target = (
                                generator.target.source
                                if isinstance(generator.target, CollectionNew)
                                else generator.target
                            )
                            iterator = create_iterator(
                                generator.iter,
                                f"{prefix}_iterator_{index}",
                            )
                            aliases = create_comprehension_target(
                                target,
                                self.iterator_item_type(iterator),
                                f"{prefix}_target_{index}",
                            )
                            loops.append(
                                _ComprehensionLoop(
                                    generator.iter,
                                    iterator,
                                    target,
                                    aliases,
                                    tuple(generator.ifs),
                                )
                            )
                        self.list_comprehensions[node] = _ListComprehension(
                            value_type,
                            add_generated_local(
                                f"{prefix}_result",
                                self.reference_type_index(list_index),
                            ),
                            add_generated_local(
                                f"{prefix}_item",
                                self.value_type(
                                    self.collection_item_type(value_type)
                                ),
                            ),
                            add_generated_local(
                                f"{prefix}_array",
                                self.reference_type_index(array_index),
                            ),
                            add_generated_local(f"{prefix}_capacity", I32),
                            tuple(loops),
                        )
                    elif isinstance(node, UnpackAssignment):
                        value_type = analyzed_value_type(node.value)
                        slot = add_generated_local(
                            f"__pyjs_unpack_{len(self.unpack_assignment_slots)}",
                            self.value_type(value_type),
                        )
                        self.unpack_assignment_slots[node] = (slot, value_type)
                        for assignment in node.assignments:
                            for item in ast.walk(assignment):
                                if isinstance(item, UnpackItem):
                                    self.unpack_item_slots[item] = (slot, value_type)
        state = "__pyjs_block"
        while state in self.local_indices:
            state += "_"
        add_local(state, I32)
        self.float_scratch = "__pyjs_float_scratch"
        while self.float_scratch in self.local_indices:
            self.float_scratch += "_"
        add_local(self.float_scratch, F64)
        self.integer_scratch = "__pyjs_integer_scratch"
        while self.integer_scratch in self.local_indices:
            self.integer_scratch += "_"
        add_local(self.integer_scratch, I64)
        self.integer_scratch_right = "__pyjs_integer_scratch_right"
        while self.integer_scratch_right in self.local_indices:
            self.integer_scratch_right += "_"
        add_local(self.integer_scratch_right, I64)
        self.integer_quotient_scratch = "__pyjs_integer_quotient_scratch"
        while self.integer_quotient_scratch in self.local_indices:
            self.integer_quotient_scratch += "_"
        add_local(self.integer_quotient_scratch, I64)
        self.integer_remainder_scratch = "__pyjs_integer_remainder_scratch"
        while self.integer_remainder_scratch in self.local_indices:
            self.integer_remainder_scratch += "_"
        add_local(self.integer_remainder_scratch, I64)
        uses_integer_true_division = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(getattr(node.func, "obj", None), Function)
            and node.func.obj.name in {"__truediv__", "__rtruediv__"}
            and analyzed_value_type(node.func.value).generic_name == "int"
            for block in blocks
            for statement in block.body
            for node in ast.walk(statement)
        )
        if uses_integer_true_division:
            self.integer_exponent_scratch = "__pyjs_integer_exponent_scratch"
            while self.integer_exponent_scratch in self.local_indices:
                self.integer_exponent_scratch += "_"
            add_local(self.integer_exponent_scratch, I64)
            self.integer_count_scratch = "__pyjs_integer_count_scratch"
            while self.integer_count_scratch in self.local_indices:
                self.integer_count_scratch += "_"
            add_local(self.integer_count_scratch, I64)
            self.integer_significand_scratch = "__pyjs_integer_significand_scratch"
            while self.integer_significand_scratch in self.local_indices:
                self.integer_significand_scratch += "_"
            add_local(self.integer_significand_scratch, I64)
            self.integer_discarded_scratch = "__pyjs_integer_discarded_scratch"
            while self.integer_discarded_scratch in self.local_indices:
                self.integer_discarded_scratch += "_"
            add_local(self.integer_discarded_scratch, I64)
            self.integer_sign_scratch = "__pyjs_integer_sign_scratch"
            while self.integer_sign_scratch in self.local_indices:
                self.integer_sign_scratch += "_"
            add_local(self.integer_sign_scratch, I32)

        # A dispatch loop represents arbitrary reducible or irreducible IR CFG
        # without adding a target-specific restructuring pass to shared IR.
        instructions = bytearray()
        instructions.extend((I32_CONST, 0x00, LOCAL_SET))
        instructions.extend(_unsigned(self.local_indices[state]))
        instructions.extend((BLOCK, EMPTY, LOOP, EMPTY))
        self.block_map = {block.name: block for block in blocks}
        block_indices = {block.name: index for index, block in enumerate(blocks)}
        for index, block in enumerate(blocks):
            instructions.append(LOCAL_GET)
            instructions.extend(_unsigned(self.local_indices[state]))
            instructions.append(I32_CONST)
            instructions.extend(_signed(index))
            instructions.extend((I32_EQ, IF, EMPTY))
            for statement in block.body[:-1]:
                self.statement(instructions, statement)
            self.terminator(
                instructions,
                block.body[-1],
                block_indices,
                state,
            )
            instructions.append(END)
        instructions.extend((UNREACHABLE, END, END, UNREACHABLE, END))
        locals_ = _vector(
            [_unsigned(1) + _encoded_type(value_type) for value_type in self.local_types]
        )
        body = locals_ + instructions
        return _unsigned(len(body)) + body

    def statement(self, code: bytearray, node: ast.stmt) -> None:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            name = self.target_name(node.target)
            self.expression_for_storage(
                code,
                node.value,
                self.local_value_types[name],
                self.local_numeric_formats.get(name),
            )
            self.set_local(code, name)
            return
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, (ast.List, ast.Tuple)):
                value_type = analyzed_value_type(node.value)
                self.expression_as(code, node.value, self.value_type(value_type))
                self.assign_target(code, target)
                return
            name = self.target_name(target)
            self.expression_for_storage(
                code,
                node.value,
                self.local_value_types[name],
                self.local_numeric_formats.get(name),
            )
            self.set_local(code, name)
            return
        if isinstance(node, FieldStore):
            _owner, _index, expected, storage_format = self.field(node.target)
            self.expression_for_storage(
                code,
                node.value,
                self.storage_carrier(expected),
                storage_format,
            )
            self.set_local(code, self.field_scratch[node])
            owner, index, _value_type, _storage_format = self.field(node.target)
            self.expression(code, node.target.value)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[self.field_scratch[node]]))
            code.extend((GC_PREFIX, STRUCT_SET))
            code.extend(_unsigned(self.class_indices[owner]))
            code.extend(_unsigned(index))
            return
        if isinstance(node, ast.Expr):
            result = self.expression(code, node.value)
            if result is not None:
                code.append(DROP)
            return
        if isinstance(node, UnpackAssignment):
            slot, value_type = self.unpack_assignment_slots[node]
            self.expression_as(code, node.value, self.value_type(value_type))
            self.set_local(code, slot)
            for assignment in node.assignments:
                self.statement(code, assignment)
            return
        if isinstance(node, IteratorCreate):
            iterator = self.iterators[node.name]
            self.iterator_create(code, node.iterable, iterator)
            return
        raise WebAssemblyUnsupported(
            f"WebAssembly statement {type(node).__name__} is not implemented",
            node,
        )

    def terminator(
        self,
        code: bytearray,
        node,
        blocks: dict[str, int],
        state: str,
    ) -> None:
        if isinstance(node, Return):
            return_type = self.function_return_storage_type(self.current_function)
            if node.value is not None and return_type is not None:
                self.expression_for_storage(
                    code,
                    node.value,
                    return_type,
                    self.current_function.return_numeric_format,
                )
            code.append(RETURN)
            return
        if isinstance(node, Jump):
            target = blocks[node.target]
            target_block = self.block_map[node.target]
            for value, argument in zip(
                node.arguments,
                target_block.arguments,
                strict=True,
            ):
                storage_format = analyzed_numeric_format(argument)
                self.expression_for_storage(
                    code,
                    value,
                    self.local_value_types[argument.name],
                    storage_format,
                )
            for argument in reversed(target_block.arguments):
                self.set_local(code, argument.name)
            code.append(I32_CONST)
            code.extend(_signed(target))
            self.set_local(code, state)
            code.extend((BR, 0x01))
            return
        if isinstance(node, Branch):
            self.condition(code, node.test)
            code.extend((IF, EMPTY, I32_CONST))
            code.extend(_signed(blocks[node.true]))
            self.set_local(code, state)
            code.extend((ELSE, I32_CONST))
            code.extend(_signed(blocks[node.false]))
            self.set_local(code, state)
            code.extend((END, BR, 0x01))
            return
        if isinstance(node, IteratorNext):
            iterator = self.iterators[node.iterator]
            self.iterator_has_next(code, iterator)
            code.extend((IF, EMPTY))
            actual_type = self.iterator_value(code, iterator, node)
            self.assign_target(code, node.target, actual_type)
            self.iterator_advance(code, iterator)
            code.append(I32_CONST)
            code.extend(_signed(blocks[node.body]))
            self.set_local(code, state)
            code.extend((ELSE, I32_CONST))
            code.extend(_signed(blocks[node.exhausted]))
            self.set_local(code, state)
            code.extend((END, BR, 0x01))
            return
        if isinstance(node, Raise):
            raise WebAssemblyUnsupported("WebAssembly exception raising is not implemented", node)
        raise WebAssemblyUnsupported("invalid WebAssembly terminator", node)

    @classmethod
    def flattened_statements(cls, statements):
        for statement in statements:
            yield statement
            if isinstance(statement, UnpackAssignment):
                yield from cls.flattened_statements(statement.assignments)

    @staticmethod
    def is_builtin_call(node: ast.expr, name: str) -> bool:
        return (
            isinstance(node, ast.Call)
            and analyzed_value_object(node.func)
            is WEBASSEMBLY_ENVIRONMENT.builtins.search(name)
        )

    def iterator_create(
        self,
        code: bytearray,
        iterable: ast.expr,
        iterator,
    ) -> None:
        if isinstance(iterator, _ListIterator):
            self.expression_as(code, iterable, self.value_type(iterator.value_type))
            self.set_local(code, iterator.source_slot)
            code.append(I32_CONST)
            code.extend(_signed(0))
            self.set_local(code, iterator.index_slot)
            return
        if isinstance(iterator, _RangeIterator):
            assert isinstance(iterable, ast.Call)
            arguments = iterable.args
            if iterable.keywords or not 1 <= len(arguments) <= 3:
                raise WebAssemblyUnsupported(
                    "WebAssembly range takes one to three positional arguments",
                    iterable,
                )
            if len(arguments) == 1:
                code.append(I64_CONST)
                code.extend(_signed(0))
                self.set_local(code, iterator.current_slot)
                self.expression_as(code, arguments[0], I64)
                self.set_local(code, iterator.stop_slot)
                code.append(I64_CONST)
                code.extend(_signed(1))
                self.set_local(code, iterator.step_slot)
            else:
                self.expression_as(code, arguments[0], I64)
                self.set_local(code, iterator.current_slot)
                self.expression_as(code, arguments[1], I64)
                self.set_local(code, iterator.stop_slot)
                if len(arguments) == 2:
                    code.append(I64_CONST)
                    code.extend(_signed(1))
                else:
                    self.expression_as(code, arguments[2], I64)
                self.set_local(code, iterator.step_slot)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.step_slot]))
            code.extend((I64_EQZ, IF, EMPTY, UNREACHABLE, END))
            return
        assert isinstance(iterable, ast.Call)
        if isinstance(iterator, _EnumerateIterator):
            self.iterator_create(code, iterable.args[0], iterator.source)
            if len(iterable.args) == 2:
                self.expression_as(code, iterable.args[1], I64)
            elif iterable.keywords:
                self.expression_as(code, iterable.keywords[0].value, I64)
            else:
                code.append(I64_CONST)
                code.extend(_signed(0))
            self.set_local(code, iterator.index_slot)
            return
        assert isinstance(iterator, _ZipIterator)
        for argument, source in zip(iterable.args, iterator.sources, strict=True):
            self.iterator_create(code, argument, source)

    def iterator_has_next(self, code: bytearray, iterator) -> None:
        if isinstance(iterator, _ListIterator):
            _array_index, list_index = self.list_indices[iterator.value_type]
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.index_slot]))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.source_slot]))
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(list_index))
            code.extend(_unsigned(1))
            code.append(I32_LT_U)
            return
        if isinstance(iterator, _RangeIterator):
            current = self.local_indices[iterator.current_slot]
            stop = self.local_indices[iterator.stop_slot]
            step = self.local_indices[iterator.step_slot]
            code.append(LOCAL_GET)
            code.extend(_unsigned(step))
            code.append(I64_CONST)
            code.extend(_signed(0))
            code.extend((I64_GT_S, IF, I32, LOCAL_GET))
            code.extend(_unsigned(current))
            code.append(LOCAL_GET)
            code.extend(_unsigned(stop))
            code.extend((I64_LT_S, ELSE, LOCAL_GET))
            code.extend(_unsigned(current))
            code.append(LOCAL_GET)
            code.extend(_unsigned(stop))
            code.extend((I64_GT_S, END))
            return
        if isinstance(iterator, _EnumerateIterator):
            self.iterator_has_next(code, iterator.source)
            return
        assert isinstance(iterator, _ZipIterator)
        if not iterator.sources:
            code.append(I32_CONST)
            code.extend(_signed(0))
            return
        self.iterator_has_next(code, iterator.sources[0])
        if iterator.strict:
            assert iterator.availability_slot is not None
            self.set_local(code, iterator.availability_slot)
        for source in iterator.sources[1:]:
            self.iterator_has_next(code, source)
            if iterator.strict:
                code.append(LOCAL_GET)
                code.extend(
                    _unsigned(self.local_indices[iterator.availability_slot])
                )
                code.extend((I32_NE, IF, EMPTY, UNREACHABLE, END))
            else:
                code.append(I32_AND)
        if iterator.strict:
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.availability_slot]))

    def iterator_value(
        self,
        code: bytearray,
        iterator,
        node: ast.AST,
    ) -> ValueType:
        if isinstance(iterator, _ListIterator):
            array_index, list_index = self.list_indices[iterator.value_type]
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.source_slot]))
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(list_index))
            code.extend(_unsigned(0))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.index_slot]))
            code.extend((GC_PREFIX, ARRAY_GET))
            code.extend(_unsigned(array_index))
            item_type = self.collection_item_type(iterator.value_type)
            if iterator.layout is not None and iterator.layout.item_numeric is not None:
                storage_type = self.numeric_storage_type(
                    iterator.layout.item_numeric
                )
                self.narrow_numeric(
                    code,
                    self.value_type(item_type),
                    storage_type,
                    iterator.layout.item_numeric,
                    node,
                )
                assert storage_type is not None
                return storage_type
            return self.value_type(item_type)
        if isinstance(iterator, _RangeIterator):
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.current_slot]))
            return I64
        if isinstance(iterator, _EnumerateIterator):
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.index_slot]))
            self.iterator_tuple_item_value(code, iterator.source, node)
            tuple_index = self.tuple_indices[iterator.item_type]
            code.extend((GC_PREFIX, STRUCT_NEW))
            code.extend(_unsigned(tuple_index))
            return self.reference_type_index(tuple_index)
        assert isinstance(iterator, _ZipIterator)
        for source in iterator.sources:
            self.iterator_tuple_item_value(code, source, node)
        tuple_index = self.tuple_indices[iterator.item_type]
        code.extend((GC_PREFIX, STRUCT_NEW))
        code.extend(_unsigned(tuple_index))
        return self.reference_type_index(tuple_index)

    def iterator_tuple_item_value(
        self,
        code: bytearray,
        iterator,
        node: ast.AST,
    ) -> None:
        actual_type = self.iterator_value(code, iterator, node)
        expected_type = self.value_type(self.iterator_item_type(iterator))
        if actual_type == expected_type:
            return
        storage_format = (
            iterator.layout.item_numeric
            if isinstance(iterator, _ListIterator) and iterator.layout is not None
            else None
        )
        widened_type = self.widen_numeric(code, actual_type, storage_format)
        if widened_type != expected_type:
            raise WebAssemblyUnsupported(
                "WebAssembly iterator tuple item conversion is not implemented",
                node,
            )

    def iterator_advance(self, code: bytearray, iterator) -> None:
        if isinstance(iterator, _ListIterator):
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.index_slot]))
            code.append(I32_CONST)
            code.extend(_signed(1))
            code.append(I32_ADD)
            self.set_local(code, iterator.index_slot)
            return
        if isinstance(iterator, _EnumerateIterator):
            self.iterator_advance(code, iterator.source)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.index_slot]))
            code.append(I64_CONST)
            code.extend(_signed(2**63 - 1))
            code.extend((I64_EQ, IF, EMPTY))
            self.iterator_has_next(code, iterator.source)
            code.extend((IF, EMPTY, UNREACHABLE, END, END))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[iterator.index_slot]))
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_ADD)
            self.set_local(code, iterator.index_slot)
            return
        if isinstance(iterator, _ZipIterator):
            for source in iterator.sources:
                self.iterator_advance(code, source)
            return
        assert isinstance(iterator, _RangeIterator)
        current = self.local_indices[iterator.current_slot]
        stop = self.local_indices[iterator.stop_slot]
        step = self.local_indices[iterator.step_slot]
        code.append(LOCAL_GET)
        code.extend(_unsigned(step))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.extend((I64_GT_S, IF, EMPTY, LOCAL_GET))
        code.extend(_unsigned(current))
        code.append(I64_CONST)
        code.extend(_signed(2**63 - 1))
        code.append(LOCAL_GET)
        code.extend(_unsigned(step))
        code.extend((I64_SUB, I64_GT_S, IF, EMPTY, LOCAL_GET))
        code.extend(_unsigned(stop))
        code.append(LOCAL_SET)
        code.extend(_unsigned(current))
        code.extend((ELSE, LOCAL_GET))
        code.extend(_unsigned(current))
        code.append(LOCAL_GET)
        code.extend(_unsigned(step))
        code.extend((I64_ADD, LOCAL_SET))
        code.extend(_unsigned(current))
        code.extend((END, ELSE, LOCAL_GET))
        code.extend(_unsigned(current))
        code.append(I64_CONST)
        code.extend(_signed(-(2**63)))
        code.append(LOCAL_GET)
        code.extend(_unsigned(step))
        code.extend((I64_SUB, I64_LT_S, IF, EMPTY, LOCAL_GET))
        code.extend(_unsigned(stop))
        code.append(LOCAL_SET)
        code.extend(_unsigned(current))
        code.extend((ELSE, LOCAL_GET))
        code.extend(_unsigned(current))
        code.append(LOCAL_GET)
        code.extend(_unsigned(step))
        code.extend((I64_ADD, LOCAL_SET))
        code.extend(_unsigned(current))
        code.append(END)
        code.append(END)

    def expression(self, code: bytearray, node: ast.expr) -> ValueType | None:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                code.append(I32_CONST)
                code.extend(_signed(int(node.value)))
                return I32
            if isinstance(node.value, int):
                if not -(2**63) <= node.value < 2**63:
                    raise WebAssemblyUnsupported(
                        "WebAssembly integers currently require signed i64",
                        node,
                    )
                code.append(I64_CONST)
                code.extend(_signed(node.value))
                return self.normalize_integer_result(code, node)
            if isinstance(node.value, float):
                code.append(F64_CONST)
                code.extend(struct.pack("<d", node.value))
                return self.normalize_float_result(code, node)
            if node.value is None:
                return None
        if isinstance(node, (ast.Name, BlockArgument)):
            if isinstance(node, ast.Name):
                value_obj = analyzed_value_object(node)
                if (
                    isinstance(value_obj, Instance)
                    and value_obj.is_const
                    and value_obj.static_value is not None
                ):
                    return self.expression(code, value_obj.static_value)
            name = (
                self.name_aliases.get(node.id, node.id)
                if isinstance(node, ast.Name)
                else node.name
            )
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[name]))
            return self.widen_numeric(
                code,
                self.local_value_types[name],
                self.local_numeric_formats.get(name),
            )
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                self.condition(code, node.operand)
                code.append(I32_EQZ)
                return I32
            if isinstance(node.op, ast.USub):
                if isinstance(node.operand, ast.Constant) and node.operand.value == 2**63:
                    code.append(I64_CONST)
                    code.extend(_signed(-(2**63)))
                    return I64
                operand_type = self.value_type(analyzed_value_type(node.operand))
                if operand_type == F64:
                    self.expression(code, node.operand)
                    code.append(F64_NEG)
                    return self.normalize_float_result(code, node)
                if operand_type == I64:
                    code.append(I64_CONST)
                    code.extend(_signed(0))
                    self.expression(code, node.operand)
                    code.append(I64_SUB)
                    return self.normalize_integer_result(code, node)
            if isinstance(node.op, ast.UAdd):
                return self.expression(code, node.operand)
            if isinstance(node.op, ast.Invert):
                self.expression(code, node.operand)
                code.append(I64_CONST)
                code.extend(_signed(-1))
                code.append(I64_XOR)
                return self.normalize_integer_result(code, node)
        if isinstance(node, ast.BoolOp):
            if any(analyzed_value_type(value).generic_name != "bool" for value in node.values):
                raise WebAssemblyUnsupported("WebAssembly boolean operators require bool operands", node)
            conjunction = isinstance(node.op, ast.And)
            for value in node.values[:-1]:
                self.expression(code, value)
                code.extend((IF, I32))
                if not conjunction:
                    code.extend((I32_CONST, 1, ELSE))
            self.expression(code, node.values[-1])
            for _value in node.values[:-1]:
                if conjunction:
                    code.extend((ELSE, I32_CONST, 0))
                code.append(END)
            return I32
        if isinstance(node, ast.IfExp):
            self.condition(code, node.test)
            result_type = self.value_type(analyzed_value_type(node))
            code.append(IF)
            code.extend(_encoded_type(result_type))
            self.expression_as(code, node.body, result_type)
            code.append(ELSE)
            self.expression_as(code, node.orelse, result_type)
            code.append(END)
            if result_type == I64:
                return self.normalize_integer_result(code, node)
            if result_type == F64:
                return self.normalize_float_result(code, node)
            return result_type
        if isinstance(node, ast.Call):
            return self.call(code, node)
        if isinstance(node, CollectionNew):
            return self.collection_new(code, node)
        if isinstance(node, ListAppend):
            self.list_append(code, node)
            return None
        if isinstance(node, ObjectNew):
            return self.object_new(code, node)
        if isinstance(node, ast.ListComp):
            return self.list_comprehension(code, node)
        if isinstance(node, UnpackItem):
            return self.unpack_item(code, node)
        if isinstance(node, FieldLoad):
            owner, index, value_type, storage_format = self.field(node.attribute)
            self.expression(code, node.attribute.value)
            code.extend(
                (
                    GC_PREFIX,
                    self.struct_get_operation(value_type, storage_format),
                )
            )
            code.extend(_unsigned(self.class_indices[owner]))
            code.extend(_unsigned(index))
            return self.widen_numeric(
                code,
                self.storage_carrier(value_type),
                storage_format,
            )
        if isinstance(node, ast.Attribute):
            owner, index, value_type, storage_format = self.field(node)
            self.expression(code, node.value)
            code.extend(
                (
                    GC_PREFIX,
                    self.struct_get_operation(value_type, storage_format),
                )
            )
            code.extend(_unsigned(self.class_indices[owner]))
            code.extend(_unsigned(index))
            return self.widen_numeric(
                code,
                self.storage_carrier(value_type),
                storage_format,
            )
        raise WebAssemblyUnsupported(
            f"WebAssembly expression {type(node).__name__} is not implemented",
            node,
        )

    def condition(self, code: bytearray, node: ast.expr) -> None:
        # Shared truth tests leave a bare __len__() call for sized values.
        if self.expression(code, node) == I64:
            code.extend((I64_EQZ, I32_EQZ))

    def call(self, code: bytearray, node: ast.Call) -> ValueType | None:
        target = analyzed_value_object(node.func)
        if isinstance(target, Function) and target.py_func is native_builtins._print:
            raise WebAssemblyUnsupported("WebAssembly print() output is not implemented", node)
        if isinstance(node.func, ast.Name) and node.func.id == "int":
            if not node.args:
                code.append(I64_CONST)
                code.extend(_signed(0))
            elif len(node.args) == 1 and not node.keywords:
                value_type = self.expression(code, node.args[0])
                if value_type == F64:
                    code.append(I64_TRUNC_F64_S)
                elif value_type == I32:
                    code.append(I64_EXTEND_I32_U)
                elif value_type != I64:
                    raise WebAssemblyUnsupported(
                        "fixed-width integer construction requires a number",
                        node,
                    )
            else:
                raise WebAssemblyUnsupported(
                    "fixed-width integer construction accepts one number",
                    node,
                )
            return self.normalize_integer_result(code, node)
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            if not node.args:
                code.append(F64_CONST)
                code.extend(struct.pack("<d", 0.0))
            elif len(node.args) == 1 and not node.keywords:
                value_type = self.expression(code, node.args[0])
                if value_type == I64:
                    code.append(F64_CONVERT_I64_S)
                elif value_type != F64:
                    raise WebAssemblyUnsupported(
                        "fixed-width float construction requires a number",
                        node,
                    )
            else:
                raise WebAssemblyUnsupported(
                    "fixed-width float construction accepts one number",
                    node,
                )
            storage_format = analyzed_numeric_format(node)
            if storage_format is not None and storage_format.bits == 32:
                code.extend((F32_DEMOTE_F64, F64_PROMOTE_F32))
            return F64
        if self.is_extreme_call(node):
            return self.extreme(code, node)
        if isinstance(target, Function) and target.py_func is sqrt:
            if len(node.args) != 1 or node.keywords:
                raise WebAssemblyUnsupported(
                    "WebAssembly math.sqrt takes one positional argument",
                    node,
                )
            self.expression_as(code, node.args[0], F64)
            code.append(LOCAL_TEE)
            code.extend(_unsigned(self.local_indices[self.float_scratch]))
            code.append(F64_CONST)
            code.extend(struct.pack("<d", 0.0))
            code.extend((F64_LT, IF, EMPTY, UNREACHABLE, END))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[self.float_scratch]))
            code.append(F64_SQRT)
            return F64
        if isinstance(target, Function) and target.py_func in self.import_indices:
            if len(node.args) != 1 or node.keywords:
                raise WebAssemblyUnsupported(
                    f"WebAssembly math.{target.name} takes one positional argument",
                    node,
                )
            self.expression_as(code, node.args[0], F64)
            code.append(CALL)
            code.extend(_unsigned(self.import_indices[target.py_func]))
            return F64
        if isinstance(target, Function) and target.py_func is radians:
            if len(node.args) != 1 or node.keywords:
                raise WebAssemblyUnsupported(
                    "WebAssembly math.radians takes one positional argument",
                    node,
                )
            self.expression_as(code, node.args[0], F64)
            code.append(F64_CONST)
            code.extend(struct.pack("<d", 0.017453292519943295))
            code.append(F64_MUL)
            return F64
        if isinstance(target, Function) and target.py_func is hypot:
            return self.hypot(code, node)
        if (
            isinstance(target, Function)
            and target.py_func in self.LINEAR_MEMORY_FUNCTIONS
        ):
            return self.linear_memory_call(code, node, target.py_func)
        if (
            isinstance(target, Function)
            and target.name in {"__is__", "__is_not__"}
            and isinstance(node.func, ast.Attribute)
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value is None
        ):
            actual_type = self.expression(code, node.func.value)
            if not isinstance(actual_type, bytes):
                raise WebAssemblyUnsupported(
                    "WebAssembly None identity requires a reference",
                    node,
                )
            code.append(REF_IS_NULL)
            if target.name == "__is_not__":
                code.append(I32_EQZ)
            return I32
        if self.is_list_constructor(node):
            return self.list_copy(code, node)
        if self.is_list_concat(node):
            return self.list_concat(code, node)
        if (
            isinstance(target, Function)
            and target.name == "__len__"
            and isinstance(node.func, ast.Attribute)
            and analyzed_value_type(node.func.value).generic_name == "list"
        ):
            list_type = analyzed_value_type(node.func.value)
            _array_index, list_index = self.list_indices[list_type]
            self.expression(code, node.func.value)
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(list_index))
            code.extend(_unsigned(1))
            code.append(I64_EXTEND_I32_U)
            return I64
        if self.is_tuple_get(node):
            return self.tuple_get(code, node)
        if self.is_list_get(node):
            return self.list_get(code, node)
        if self.is_list_set(node):
            self.list_set(code, node)
            return None
        if isinstance(target, Function) and target.py_func is native_builtins._len:
            if len(node.args) != 1 or node.keywords:
                raise WebAssemblyUnsupported(
                    "WebAssembly len takes one positional argument",
                    node,
                )
            collection_type = analyzed_value_type(node.args[0])
            if collection_type.generic_name == "tuple":
                code.append(I64_CONST)
                code.extend(_signed(len(collection_type.generic_types)))
                return I64
            if collection_type.generic_name != "list":
                raise WebAssemblyUnsupported(
                    "WebAssembly len currently requires a list or tuple",
                    node,
                )
            _array_index, list_index = self.list_indices[collection_type]
            self.expression(code, node.args[0])
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(list_index))
            code.extend(_unsigned(1))
            code.append(I64_EXTEND_I32_U)
            return I64
        if isinstance(target, Function) and target.py_func is isfinite:
            self.expression_as(code, node.args[0], F64)
            code.append(F64_ABS)
            code.append(F64_CONST)
            code.extend(struct.pack("<d", float("inf")))
            code.append(F64_LT)
            return I32
        if isinstance(target, Function) and target.py_func is native_builtins._abs:
            operand_type = self.value_type(analyzed_value_type(node.args[0]))
            self.expression(code, node.args[0])
            if operand_type == F64:
                code.append(F64_ABS)
                return F64
            if operand_type == I32:
                code.append(I64_EXTEND_I32_U)
                return I64
            if operand_type == I64:
                code.append(LOCAL_TEE)
                code.extend(_unsigned(self.local_indices[self.integer_scratch]))
                code.append(I64_CONST)
                code.extend(_signed(0))
                code.extend((I64_LT_S, IF, I64, I64_CONST))
                code.extend(_signed(0))
                code.append(LOCAL_GET)
                code.extend(_unsigned(self.local_indices[self.integer_scratch]))
                code.append(I64_SUB)
                code.append(ELSE)
                code.append(LOCAL_GET)
                code.extend(_unsigned(self.local_indices[self.integer_scratch]))
                code.append(END)
                return self.normalize_integer_result(code, node)
            raise WebAssemblyUnsupported(
                "WebAssembly abs requires a bool, int, or float",
                node,
            )
        if isinstance(target, Function) and target in self.indices:
            if node.keywords:
                raise WebAssemblyUnsupported(
                    "WebAssembly calls do not support keyword arguments",
                    node,
                )
            if target.cls in self.classes:
                if not isinstance(node.func, ast.Attribute):
                    raise WebAssemblyUnsupported(
                        "WebAssembly instance methods require a receiver",
                        node,
                    )
                self.expression(code, node.func.value)
            if len(node.args) != len(target.params):
                raise WebAssemblyUnsupported(
                    f"WebAssembly call to {target.name} has incompatible arguments",
                    node,
                )
            for argument, parameter in zip(
                node.args,
                target.params,
                strict=True,
            ):
                self.expression_for_storage(
                    code,
                    argument,
                    self.parameter_storage_type(target, parameter),
                    analyzed_numeric_format(parameter),
                )
            code.append(CALL)
            code.extend(_unsigned(self.indices[target]))
            return self.widen_numeric(
                code,
                self.function_return_storage_type(target),
                target.return_numeric_format,
            )
        if (
            isinstance(target, Function)
            and isinstance(node.func, ast.Attribute)
            and len(node.args) <= 1
        ):
            operands = [node.func.value, *node.args]
            reverse = target.name.startswith("__r") and target.name != "__rshift__"
            if reverse:
                operands.reverse()
            operation = target.name.replace("__r", "__", 1) if reverse else target.name
            receiver_type = self.value_type(analyzed_value_type(node.func.value))
            if receiver_type == I32 and operation == "__bool__" and not node.args:
                return self.expression(code, node.func.value)
            if receiver_type == I64 and not node.args:
                self.expression(code, node.func.value)
                if operation == "__neg__":
                    code.append(LOCAL_SET)
                    code.extend(_unsigned(self.local_indices[self.integer_scratch]))
                    code.append(I64_CONST)
                    code.extend(_signed(0))
                    code.append(LOCAL_GET)
                    code.extend(_unsigned(self.local_indices[self.integer_scratch]))
                    code.append(I64_SUB)
                elif operation == "__invert__":
                    code.append(I64_CONST)
                    code.extend(_signed(-1))
                    code.append(I64_XOR)
                elif operation == "__bool__":
                    code.extend((I64_EQZ, I32_EQZ))
                    return I32
                elif operation != "__pos__":
                    raise WebAssemblyUnsupported(
                        f"WebAssembly integer operation {operation} is not implemented",
                        node,
                    )
                return self.normalize_integer_result(code, node)
            if receiver_type == F64:
                if operation == "__truediv__":
                    self.expression_as(code, operands[0], F64)
                    self.expression_as(code, operands[1], F64)
                    storage_format = analyzed_numeric_format(node)
                    if storage_format is not None and storage_format.domain == "wgsl":
                        code.append(F64_DIV)
                        return self.normalize_float_result(code, node)
                    code.append(LOCAL_TEE)
                    code.extend(_unsigned(self.local_indices[self.float_scratch]))
                    code.append(F64_CONST)
                    code.extend(struct.pack("<d", 0.0))
                    code.extend((F64_EQ, IF, EMPTY, UNREACHABLE, END))
                    code.append(LOCAL_GET)
                    code.extend(_unsigned(self.local_indices[self.float_scratch]))
                    code.append(F64_DIV)
                    return self.normalize_float_result(code, node)
                for operand in operands:
                    self.expression_as(code, operand, F64)
                if operation in self.FLOAT_OPERATORS:
                    code.append(self.FLOAT_OPERATORS[operation])
                    return self.normalize_float_result(code, node)
                if operation in self.FLOAT_COMPARISONS:
                    code.append(self.FLOAT_COMPARISONS[operation])
                    return I32
                if target.name == "__bool__":
                    code.append(F64_CONST)
                    code.extend(struct.pack("<d", 0.0))
                    code.extend((F64_EQ, I32_EQZ))
                    return I32
                if target.name == "__abs__":
                    code.append(F64_ABS)
                    return F64
            for operand in operands:
                self.expression(code, operand)
            storage_format = analyzed_numeric_format(node)
            if (
                receiver_type == I64
                and storage_format is not None
                and storage_format.domain == "wgsl"
                and operation in {"__truediv__", "__mod__"}
            ):
                self.wgsl_integer_division(
                    code,
                    storage_format,
                    modulo=operation == "__mod__",
                )
                return self.normalize_integer_result(code, node)
            if receiver_type == I64 and operation == "__truediv__":
                self.integer_true_division(code)
                return F64
            if receiver_type == I64 and operation in {"__floordiv__", "__mod__"}:
                self.python_integer_division(
                    code,
                    modulo=operation == "__mod__",
                    fixed=storage_format is not None,
                )
                return self.normalize_integer_result(code, node)
            if receiver_type == I64 and operation == "__pow__":
                self.integer_power(code)
                return self.normalize_integer_result(code, node)
            if receiver_type == I64 and operation in {"__lshift__", "__rshift__"}:
                receiver_format = analyzed_numeric_format(node.func.value)
                self.integer_shift(
                    code,
                    left=operation == "__lshift__",
                    signed=(
                        storage_format is None
                        or storage_format.signed
                        or receiver_format is None
                    ),
                    bits=(
                        storage_format.bits
                        if storage_format is not None
                        and receiver_format is not None
                        else 64
                    ),
                )
                return self.normalize_integer_result(code, node)
            if receiver_type == I64 and operation in self.INTEGER_OPERATORS:
                code.append(self.INTEGER_OPERATORS[operation])
                return self.normalize_integer_result(code, node)
            if receiver_type == I64 and operation in self.INTEGER_COMPARISONS:
                code.append(self.INTEGER_COMPARISONS[operation])
                return I32
            if receiver_type == I32 and operation in self.BOOLEAN_OPERATORS:
                code.append(self.BOOLEAN_OPERATORS[operation])
                return I32
            if target.name == "__bool__" and receiver_type == I32:
                return I32
            if target.name == "__bool__" and receiver_type == I64:
                code.extend((I64_EQZ, I32_EQZ))
                return I32
        name = getattr(target, "name", type(target).__name__)
        raise WebAssemblyUnsupported(
            f"WebAssembly call target {name} is not implemented",
            node,
        )

    def collection_new(self, code: bytearray, node: CollectionNew) -> bytes:
        if node.value_type.generic_name == "tuple" and isinstance(
            node.source,
            ast.Tuple,
        ):
            item_types = tuple(node.value_type.generic_types.values())
            if len(item_types) != len(node.source.elts):
                raise WebAssemblyUnsupported(
                    "WebAssembly tuple literal changes arity",
                    node,
                )
            for element, item_type in zip(
                node.source.elts,
                item_types,
                strict=True,
            ):
                self.expression_as(code, element, self.value_type(item_type))
            tuple_index = self.tuple_indices[node.value_type]
            code.extend((GC_PREFIX, STRUCT_NEW))
            code.extend(_unsigned(tuple_index))
            return self.reference_type_index(tuple_index)
        if node.value_type.generic_name != "list" or not isinstance(
            node.source,
            ast.List,
        ):
            raise WebAssemblyUnsupported(
                f"WebAssembly {node.value_type.generic_name} allocation "
                "is not implemented",
                node,
            )
        item_type = self.value_type(self.collection_item_type(node.value_type))
        for element in node.source.elts:
            self.expression_as(code, element, item_type)
        array_index, list_index = self.list_indices[node.value_type]
        code.extend((GC_PREFIX, ARRAY_NEW_FIXED))
        code.extend(_unsigned(array_index))
        code.extend(_unsigned(len(node.source.elts)))
        code.append(I32_CONST)
        code.extend(_signed(len(node.source.elts)))
        code.extend((GC_PREFIX, STRUCT_NEW))
        code.extend(_unsigned(list_index))
        return self.reference_type_index(list_index)

    def tuple_get(self, code: bytearray, node: ast.Call) -> ValueType:
        tuple_type = analyzed_value_type(node.func.value)
        item_types = tuple(tuple_type.generic_types.values())
        index = self.constant_tuple_index(node.args[0], len(item_types))
        self.expression(code, node.func.value)
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(self.tuple_indices[tuple_type]))
        code.extend(_unsigned(index))
        return self.value_type(item_types[index])

    def unpack_item(self, code: bytearray, node: UnpackItem) -> ValueType:
        slot, value_type = self.unpack_item_slots[node]
        if value_type.generic_name == "tuple":
            item_types = tuple(value_type.generic_types.values())
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[slot]))
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(self.tuple_indices[value_type]))
            code.extend(_unsigned(node.index))
            return self.value_type(item_types[node.index])
        raise WebAssemblyUnsupported(
            "WebAssembly unpacking requires a fixed tuple",
            node,
        )

    def list_append(self, code: bytearray, node: ListAppend) -> None:
        if len(node.call.args) != 1 or node.call.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly list append takes one positional argument",
                node,
            )
        list_type = analyzed_value_type(node.call.func.value)
        array_index, list_index = self.list_indices[list_type]
        item_type = self.value_type(self.collection_item_type(list_type))
        list_slot, item_slot, array_slot, capacity_slot = self.list_append_slots[
            node
        ]

        # Evaluate the receiver before the item, matching Python call order.
        self.expression(code, node.call.func.value)
        self.set_local(code, list_slot)
        self.expression_as(code, node.call.args[0], item_type)
        self.set_local(code, item_slot)

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.extend((GC_PREFIX, ARRAY_LEN))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.extend((I32_EQ, IF, EMPTY))

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.append(I32_CONST)
        code.extend(_signed(2))
        code.extend((I32_MUL, LOCAL_TEE))
        code.extend(_unsigned(self.local_indices[capacity_slot]))
        code.append(I32_CONST)
        code.extend(_signed(4))
        code.extend((I32_LT_S, IF, I32, I32_CONST))
        code.extend(_signed(4))
        code.append(ELSE)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[capacity_slot]))
        code.append(END)
        code.extend((GC_PREFIX, ARRAY_NEW_DEFAULT))
        code.extend(_unsigned(array_index))
        self.set_local(code, array_slot)

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[array_slot]))
        code.append(I32_CONST)
        code.extend(_signed(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(I32_CONST)
        code.extend(_signed(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.extend((GC_PREFIX, ARRAY_COPY))
        code.extend(_unsigned(array_index))
        code.extend(_unsigned(array_index))

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[array_slot]))
        code.extend((GC_PREFIX, STRUCT_SET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(END)

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[item_slot]))
        code.extend((GC_PREFIX, ARRAY_SET))
        code.extend(_unsigned(array_index))

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.append(I32_CONST)
        code.extend(_signed(1))
        code.extend((I32_ADD, GC_PREFIX, STRUCT_SET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))

    def list_copy(self, code: bytearray, node: ast.Call) -> ValueType:
        if len(node.args) != 1 or node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly list construction requires one list",
                node,
            )
        list_type = analyzed_value_type(node)
        source_type = analyzed_value_type(node.args[0])
        if source_type != list_type:
            raise WebAssemblyUnsupported(
                "WebAssembly list construction currently copies one matching list",
                node,
            )
        array_index, list_index = self.list_indices[list_type]
        source_slot, array_slot, length_slot = self.list_copy_slots[node]
        self.expression(code, node.args[0])
        self.set_local(code, source_slot)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[source_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.append(LOCAL_TEE)
        code.extend(_unsigned(self.local_indices[length_slot]))
        code.extend((GC_PREFIX, ARRAY_NEW_DEFAULT))
        code.extend(_unsigned(array_index))
        self.set_local(code, array_slot)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[array_slot]))
        code.append(I32_CONST)
        code.extend(_signed(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[source_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(I32_CONST)
        code.extend(_signed(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[length_slot]))
        code.extend((GC_PREFIX, ARRAY_COPY))
        code.extend(_unsigned(array_index))
        code.extend(_unsigned(array_index))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[array_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[length_slot]))
        code.extend((GC_PREFIX, STRUCT_NEW))
        code.extend(_unsigned(list_index))
        return self.reference_type_index(list_index)

    def list_concat(self, code: bytearray, node: ast.Call) -> ValueType:
        if len(node.args) != 1 or node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly list concatenation requires two lists",
                node,
            )
        target = analyzed_value_object(node.func)
        assert isinstance(node.func, ast.Attribute)
        if target.name == "__add__":
            left, right = node.func.value, node.args[0]
        else:
            left, right = node.args[0], node.func.value
        list_type = analyzed_value_type(node)
        if analyzed_value_type(left) != list_type or analyzed_value_type(right) != list_type:
            raise WebAssemblyUnsupported(
                "WebAssembly list concatenation requires matching list types",
                node,
            )
        array_index, list_index = self.list_indices[list_type]
        (
            left_slot,
            right_slot,
            array_slot,
            left_length_slot,
            length_slot,
        ) = self.list_concat_slots[node]
        self.expression(code, left)
        self.set_local(code, left_slot)
        self.expression(code, right)
        self.set_local(code, right_slot)
        self.list_length(code, left_slot, list_index)
        self.set_local(code, left_length_slot)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[left_length_slot]))
        self.list_length(code, right_slot, list_index)
        code.append(I32_ADD)
        self.set_local(code, length_slot)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[length_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[left_length_slot]))
        code.extend((I32_LT_U, IF, EMPTY, UNREACHABLE, END, LOCAL_GET))
        code.extend(_unsigned(self.local_indices[length_slot]))
        code.extend((GC_PREFIX, ARRAY_NEW_DEFAULT))
        code.extend(_unsigned(array_index))
        self.set_local(code, array_slot)
        self.copy_list_region(
            code,
            array_slot,
            0,
            left_slot,
            left_length_slot,
            array_index,
            list_index,
        )
        self.copy_list_region(
            code,
            array_slot,
            left_length_slot,
            right_slot,
            None,
            array_index,
            list_index,
        )
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[array_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[length_slot]))
        code.extend((GC_PREFIX, STRUCT_NEW))
        code.extend(_unsigned(list_index))
        return self.reference_type_index(list_index)

    def list_length(self, code: bytearray, slot: str, list_index: int) -> None:
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))

    def copy_list_region(
        self,
        code: bytearray,
        destination_slot: str,
        destination_offset: int | str,
        source_slot: str,
        length_slot: str | None,
        array_index: int,
        list_index: int,
    ) -> None:
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[destination_slot]))
        if isinstance(destination_offset, int):
            code.append(I32_CONST)
            code.extend(_signed(destination_offset))
        else:
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[destination_offset]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[source_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(I32_CONST)
        code.extend(_signed(0))
        if length_slot is None:
            self.list_length(code, source_slot, list_index)
        else:
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[length_slot]))
        code.extend((GC_PREFIX, ARRAY_COPY))
        code.extend(_unsigned(array_index))
        code.extend(_unsigned(array_index))

    def list_comprehension(
        self,
        code: bytearray,
        node: ast.ListComp,
    ) -> ValueType:
        comprehension = self.list_comprehensions[node]
        array_index, list_index = self.list_indices[comprehension.value_type]
        code.append(I32_CONST)
        code.extend(_signed(0))
        code.extend((GC_PREFIX, ARRAY_NEW_DEFAULT))
        code.extend(_unsigned(array_index))
        code.append(I32_CONST)
        code.extend(_signed(0))
        code.extend((GC_PREFIX, STRUCT_NEW))
        code.extend(_unsigned(list_index))
        self.set_local(code, comprehension.result_slot)
        self.list_comprehension_loop(code, node, comprehension, 0)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[comprehension.result_slot]))
        return self.reference_type_index(list_index)

    def list_comprehension_loop(
        self,
        code: bytearray,
        node: ast.ListComp,
        comprehension: _ListComprehension,
        index: int,
    ) -> None:
        loop = comprehension.loops[index]
        previous_aliases = self.name_aliases
        self.name_aliases = {**previous_aliases, **loop.aliases}
        try:
            self.iterator_create(code, loop.iterable, loop.iterator)
            code.extend((BLOCK, EMPTY, LOOP, EMPTY))
            self.iterator_has_next(code, loop.iterator)
            code.extend((I32_EQZ, BR_IF))
            code.extend(_unsigned(1))
            actual_type = self.iterator_value(code, loop.iterator, node)
            self.assign_target(code, loop.target, actual_type)
            self.iterator_advance(code, loop.iterator)
            for condition in loop.filters:
                self.condition(code, condition)
                code.extend((I32_EQZ, BR_IF))
                code.extend(_unsigned(0))
            if index + 1 < len(comprehension.loops):
                self.list_comprehension_loop(
                    code,
                    node,
                    comprehension,
                    index + 1,
                )
            else:
                self.expression_as(
                    code,
                    node.elt,
                    self.value_type(
                        self.collection_item_type(comprehension.value_type)
                    ),
                )
                self.set_local(code, comprehension.item_slot)
                self.append_stored_list_item(code, comprehension)
            code.append(BR)
            code.extend(_unsigned(0))
            code.extend((END, END))
        finally:
            self.name_aliases = previous_aliases

    def append_stored_list_item(
        self,
        code: bytearray,
        comprehension: _ListComprehension,
    ) -> None:
        array_index, list_index = self.list_indices[comprehension.value_type]
        list_slot = comprehension.result_slot
        item_slot = comprehension.item_slot
        array_slot = comprehension.array_slot
        capacity_slot = comprehension.capacity_slot

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.extend((GC_PREFIX, ARRAY_LEN))
        self.list_length(code, list_slot, list_index)
        code.extend((I32_EQ, IF, EMPTY))
        self.list_length(code, list_slot, list_index)
        code.append(I32_CONST)
        code.extend(_signed(2))
        code.extend((I32_MUL, LOCAL_TEE))
        code.extend(_unsigned(self.local_indices[capacity_slot]))
        code.append(I32_CONST)
        code.extend(_signed(4))
        code.extend((I32_LT_S, IF, I32, I32_CONST))
        code.extend(_signed(4))
        code.append(ELSE)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[capacity_slot]))
        code.append(END)
        code.extend((GC_PREFIX, ARRAY_NEW_DEFAULT))
        code.extend(_unsigned(array_index))
        self.set_local(code, array_slot)
        self.copy_list_region(
            code,
            array_slot,
            0,
            list_slot,
            None,
            array_index,
            list_index,
        )
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[array_slot]))
        code.extend((GC_PREFIX, STRUCT_SET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(END)

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        self.list_length(code, list_slot, list_index)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[item_slot]))
        code.extend((GC_PREFIX, ARRAY_SET))
        code.extend(_unsigned(array_index))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        self.list_length(code, list_slot, list_index)
        code.append(I32_CONST)
        code.extend(_signed(1))
        code.extend((I32_ADD, GC_PREFIX, STRUCT_SET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))

    def list_get(self, code: bytearray, node: ast.Call) -> ValueType:
        if len(node.args) != 1 or node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly list indexing takes one positional argument",
                node,
            )
        list_type = analyzed_value_type(node.func.value)
        array_index, list_index = self.list_indices[list_type]
        list_slot, index_slot, actual_slot = self.list_get_slots[node]

        self.expression(code, node.func.value)
        self.set_local(code, list_slot)
        self.expression_as(code, node.args[0], I64)
        self.set_local(code, index_slot)

        self.normalize_list_index(
            code,
            list_slot,
            index_slot,
            actual_slot,
            list_index,
        )

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[actual_slot]))
        code.extend((I32_WRAP_I64, GC_PREFIX, ARRAY_GET))
        code.extend(_unsigned(array_index))
        return self.value_type(self.collection_item_type(list_type))

    def list_set(self, code: bytearray, node: ast.Call) -> None:
        if len(node.args) != 2 or node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly list item assignment requires index and value",
                node,
            )
        list_type = analyzed_value_type(node.func.value)
        array_index, list_index = self.list_indices[list_type]
        list_slot, index_slot, actual_slot, item_slot = self.list_set_slots[node]

        # Assignment evaluates its right-hand value before resolving the
        # receiver and index of its target.
        self.expression_as(
            code,
            node.args[1],
            self.value_type(self.collection_item_type(list_type)),
        )
        self.set_local(code, item_slot)
        self.expression(code, node.func.value)
        self.set_local(code, list_slot)
        self.expression_as(code, node.args[0], I64)
        self.set_local(code, index_slot)

        self.normalize_list_index(
            code,
            list_slot,
            index_slot,
            actual_slot,
            list_index,
        )

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(0))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[actual_slot]))
        code.append(I32_WRAP_I64)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[item_slot]))
        code.extend((GC_PREFIX, ARRAY_SET))
        code.extend(_unsigned(array_index))

    def normalize_list_index(
        self,
        code: bytearray,
        list_slot: str,
        index_slot: str,
        actual_slot: str,
        list_index: int,
    ) -> None:
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[index_slot]))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.extend((I64_LT_S, IF, I64))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[index_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.extend((I64_EXTEND_I32_U, I64_ADD, ELSE, LOCAL_GET))
        code.extend(_unsigned(self.local_indices[index_slot]))
        code.append(END)
        self.set_local(code, actual_slot)

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[actual_slot]))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.extend((I64_LT_S, IF, EMPTY, UNREACHABLE, END))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[actual_slot]))
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[list_slot]))
        code.extend((GC_PREFIX, STRUCT_GET))
        code.extend(_unsigned(list_index))
        code.extend(_unsigned(1))
        code.extend((I64_EXTEND_I32_U, I64_GE_S, IF, EMPTY, UNREACHABLE, END))

    def object_new(self, code: bytearray, node: ObjectNew) -> bytes:
        if node.value_type not in self.classes:
            raise WebAssemblyUnsupported(
                f"WebAssembly cannot allocate class {node.value_type.name}",
                node,
            )
        evaluation, ordered = self.constructor_arguments(node)
        slots = self.object_argument_slots[node]
        constructor = self.classes[node.value_type].constructor
        parameters = {parameter.arg: parameter for parameter in constructor.params}
        for name, argument in evaluation:
            parameter = parameters[name]
            if isinstance(argument, ast.Constant) and argument.value is None:
                self.expression_for_storage(
                    code,
                    argument,
                    self.local_value_types[slots[name]],
                    analyzed_numeric_format(parameter),
                )
            else:
                self.expression(code, argument)
            self.set_local(code, slots[name])
        code.extend((GC_PREFIX, STRUCT_NEW_DEFAULT))
        code.extend(_unsigned(self.class_indices[node.value_type]))
        result = self.object_result_slots[node]
        self.set_local(code, result)
        if constructor in self.indices:
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[result]))
            for name in ordered:
                code.append(LOCAL_GET)
                code.extend(_unsigned(self.local_indices[slots[name]]))
                parameter = parameters[name]
                self.narrow_numeric(
                    code,
                    self.local_value_types[slots[name]],
                    self.parameter_storage_type(constructor, parameter),
                    analyzed_numeric_format(parameter),
                )
            code.append(CALL)
            code.extend(_unsigned(self.indices[constructor]))
        elif evaluation:
            raise WebAssemblyUnsupported(
                f"WebAssembly class {node.value_type.name} has no emitted constructor",
                node,
            )
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[result]))
        return self.reference_type(node.value_type)

    def constructor_arguments(self, node: ObjectNew):
        constructor = self.classes[node.value_type].constructor
        if constructor not in self.indices:
            if node.call.args or node.call.keywords:
                raise WebAssemblyUnsupported(
                    f"WebAssembly class {node.value_type.name} has no emitted constructor",
                    node,
                )
            return [], []
        parameters = [parameter.arg for parameter in constructor.params]
        if len(node.call.args) > len(parameters):
            raise WebAssemblyUnsupported(
                f"WebAssembly constructor for {node.value_type.name} has too many arguments",
                node,
            )
        evaluation = list(zip(parameters, node.call.args, strict=False))
        supplied = {name for name, _value in evaluation}
        for keyword in node.call.keywords:
            if (
                keyword.arg is None
                or keyword.arg not in parameters
                or keyword.arg in supplied
            ):
                raise WebAssemblyUnsupported(
                    f"WebAssembly constructor argument {keyword.arg} is invalid",
                    node,
                )
            supplied.add(keyword.arg)
            evaluation.append((keyword.arg, keyword.value))
        missing = [name for name in parameters if name not in supplied]
        if missing:
            raise WebAssemblyUnsupported(
                "WebAssembly constructor arguments are missing: " + ", ".join(missing),
                node,
            )
        return evaluation, parameters

    def field(
        self,
        attribute,
    ) -> tuple[Class, int, ValueType, NumericFormat | None]:
        owner = analyzed_value_type(attribute.value)
        field = self.fields.get((owner, attribute.attr))
        if field is None:
            raise WebAssemblyUnsupported(
                f"WebAssembly field {owner.name}.{attribute.attr} is not implemented",
                attribute,
            )
        index, value_type, storage_format = field
        return owner, index, value_type, storage_format

    def field_value_type(self, attribute) -> ValueType:
        return self.storage_carrier(self.field(attribute)[2])

    def expression_as(
        self,
        code: bytearray,
        node: ast.expr,
        expected_type: ValueType,
    ) -> ValueType:
        if isinstance(node, ast.Constant) and node.value is None:
            self.null_reference(code, expected_type, node)
            return expected_type
        actual_type = self.expression(code, node)
        if actual_type == expected_type:
            return expected_type
        if expected_type == F64 and actual_type == I64:
            code.append(F64_CONVERT_I64_S)
            return F64
        if expected_type == F64 and actual_type == I32:
            code.append(F64_CONVERT_I32_S)
            return F64
        raise WebAssemblyUnsupported(
            "WebAssembly numeric conversion is not implemented",
            node,
        )

    def expression_for_storage(
        self,
        code: bytearray,
        node: ast.expr,
        storage_type: ValueType,
        storage_format: NumericFormat | None,
    ) -> ValueType:
        if isinstance(node, ast.Constant) and node.value is None:
            self.null_reference(code, storage_type, node)
            return storage_type
        actual_type = self.expression(code, node)
        return self.narrow_numeric(
            code,
            actual_type,
            storage_type,
            storage_format,
            node,
        )

    @staticmethod
    def null_reference(
        code: bytearray,
        expected_type: ValueType,
        node: ast.AST,
    ) -> None:
        if not isinstance(expected_type, bytes) or not expected_type.startswith(b"\x63"):
            raise WebAssemblyUnsupported(
                "WebAssembly None requires a nullable reference type",
                node,
            )
        code.append(REF_NULL)
        code.extend(expected_type[1:])

    def narrow_numeric(
        self,
        code: bytearray,
        actual_type: ValueType | None,
        storage_type: ValueType | None,
        storage_format: NumericFormat | None,
        node: ast.AST | None = None,
    ) -> ValueType:
        if actual_type == storage_type:
            return storage_type
        if storage_format is None:
            raise WebAssemblyUnsupported(
                "WebAssembly storage conversion is not implemented",
                node,
            )
        if actual_type == I64 and storage_type == I32:
            code.append(I32_WRAP_I64)
            self.normalize_i32(code, storage_format)
            return I32
        if actual_type == F64 and storage_type == F32:
            code.append(F32_DEMOTE_F64)
            return F32
        raise WebAssemblyUnsupported(
            "WebAssembly numeric storage conversion is not implemented",
            node,
        )

    def normalize_integer_result(
        self,
        code: bytearray,
        node: ast.expr,
    ) -> ValueType:
        storage_format = analyzed_numeric_format(node)
        if storage_format is None or storage_format.kind != "integer":
            return I64
        storage_type = self.numeric_storage_type(storage_format)
        assert storage_type is not None
        carrier = self.storage_carrier(storage_type)
        narrowed = self.narrow_numeric(
            code,
            I64,
            carrier,
            storage_format,
            node,
        )
        widened = self.widen_numeric(code, narrowed, storage_format)
        assert widened is not None
        return widened

    def wgsl_integer_division(
        self,
        code: bytearray,
        storage_format: NumericFormat,
        *,
        modulo: bool,
    ) -> None:
        left = self.local_indices[self.integer_scratch]
        right = self.local_indices[self.integer_scratch_right]
        code.append(LOCAL_SET)
        code.extend(_unsigned(right))
        code.append(LOCAL_SET)
        code.extend(_unsigned(left))
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.extend((I64_EQZ, IF, I64))
        self.wgsl_integer_division_fallback(code, left, modulo)
        code.append(ELSE)
        if storage_format.signed:
            minimum, _maximum = storage_format.integer_bounds
            code.append(LOCAL_GET)
            code.extend(_unsigned(left))
            code.append(I64_CONST)
            code.extend(_signed(minimum))
            code.extend((I64_EQ, IF, I64))
            code.append(LOCAL_GET)
            code.extend(_unsigned(right))
            code.append(I64_CONST)
            code.extend(_signed(-1))
            code.extend((I64_EQ, IF, I64))
            self.wgsl_integer_division_fallback(code, left, modulo)
            code.append(ELSE)
            self.wgsl_integer_division_operation(code, left, right, True, modulo)
            code.append(END)
            code.append(ELSE)
            self.wgsl_integer_division_operation(code, left, right, True, modulo)
            code.append(END)
        else:
            self.wgsl_integer_division_operation(code, left, right, False, modulo)
        code.append(END)

    def integer_true_division(self, code: bytearray) -> None:
        """Round an i64 ratio once to f64 using integer quotient bits."""
        left = self.local_indices[self.integer_scratch]
        right = self.local_indices[self.integer_scratch_right]
        quotient = self.local_indices[self.integer_quotient_scratch]
        remainder = self.local_indices[self.integer_remainder_scratch]
        exponent = self.local_indices[self.integer_exponent_scratch]
        count = self.local_indices[self.integer_count_scratch]
        significand = self.local_indices[self.integer_significand_scratch]
        discarded = self.local_indices[self.integer_discarded_scratch]
        sign = self.local_indices[self.integer_sign_scratch]

        def get(local: int) -> None:
            code.append(LOCAL_GET)
            code.extend(_unsigned(local))

        def set_(local: int) -> None:
            code.append(LOCAL_SET)
            code.extend(_unsigned(local))

        def increment(local: int) -> None:
            get(local)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_ADD)
            set_(local)

        def round_tie() -> None:
            get(remainder)
            code.extend((I64_EQZ, IF, EMPTY))
            get(significand)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.extend((I64_AND, I64_EQZ, IF, EMPTY, ELSE))
            increment(significand)
            code.append(END)
            code.append(ELSE)
            increment(significand)
            code.append(END)

        def append_fraction_bits() -> None:
            code.extend((BLOCK, EMPTY, LOOP, EMPTY))
            get(count)
            code.extend((I64_EQZ, BR_IF))
            code.extend(_unsigned(1))
            get(remainder)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_SHL)
            set_(remainder)
            get(significand)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_SHL)
            set_(significand)
            get(remainder)
            get(right)
            code.extend((I64_LT_U, IF, EMPTY, ELSE))
            get(remainder)
            get(right)
            code.append(I64_SUB)
            set_(remainder)
            get(significand)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_OR)
            set_(significand)
            code.append(END)
            get(count)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_SUB)
            set_(count)
            code.append(BR)
            code.extend(_unsigned(0))
            code.extend((END, END))

        def round_fraction() -> None:
            get(remainder)
            code.append(I64_CONST)
            code.extend(_signed(1))
            code.append(I64_SHL)
            set_(remainder)
            get(remainder)
            get(right)
            code.extend((I64_LT_U, IF, EMPTY, ELSE))
            get(remainder)
            get(right)
            code.append(I64_SUB)
            set_(remainder)
            round_tie()
            code.append(END)

        code.append(LOCAL_SET)
        code.extend(_unsigned(right))
        code.append(LOCAL_SET)
        code.extend(_unsigned(left))
        get(right)
        code.extend((I64_EQZ, IF, EMPTY, UNREACHABLE, END))
        get(left)
        code.extend((I64_EQZ, IF, F64))
        code.append(F64_CONST)
        code.extend(struct.pack("<d", 0.0))
        code.append(ELSE)

        get(left)
        get(right)
        code.append(I64_XOR)
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.append(I64_LT_S)
        set_(sign)
        for local in (left, right):
            get(local)
            code.append(I64_CONST)
            code.extend(_signed(0))
            code.append(I64_LT_S)
            code.extend((IF, I64))
            code.append(I64_CONST)
            code.extend(_signed(0))
            get(local)
            code.append(I64_SUB)
            code.append(ELSE)
            get(local)
            code.append(END)
            set_(local)

        get(left)
        get(right)
        code.append(I64_DIV_U)
        set_(quotient)
        get(left)
        get(right)
        code.append(I64_REM_U)
        set_(remainder)
        get(quotient)
        code.extend((I64_EQZ, IF, EMPTY))

        code.append(I64_CONST)
        code.extend(_signed(-1))
        set_(exponent)
        code.extend((BLOCK, EMPTY, LOOP, EMPTY))
        get(remainder)
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SHL)
        set_(remainder)
        get(remainder)
        get(right)
        code.extend((I64_LT_U, IF, EMPTY))
        get(exponent)
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SUB)
        set_(exponent)
        code.append(BR)
        code.extend(_unsigned(1))
        code.append(END)
        get(remainder)
        get(right)
        code.append(I64_SUB)
        set_(remainder)
        code.append(I64_CONST)
        code.extend(_signed(1))
        set_(significand)
        code.append(BR)
        code.extend(_unsigned(1))
        code.extend((END, END))
        code.append(I64_CONST)
        code.extend(_signed(52))
        set_(count)
        append_fraction_bits()
        round_fraction()

        code.append(ELSE)
        code.append(I64_CONST)
        code.extend(_signed(63))
        get(quotient)
        code.append(I64_CLZ)
        code.append(I64_SUB)
        set_(exponent)
        code.append(I64_CONST)
        code.extend(_signed(52))
        get(exponent)
        code.append(I64_LT_S)
        code.extend((IF, EMPTY))
        get(exponent)
        code.append(I64_CONST)
        code.extend(_signed(52))
        code.append(I64_SUB)
        set_(count)
        code.append(I64_CONST)
        code.extend(_signed(1))
        get(count)
        code.append(I64_SHL)
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SUB)
        get(quotient)
        code.append(I64_AND)
        set_(discarded)
        get(quotient)
        get(count)
        code.append(I64_SHR_U)
        set_(significand)
        code.append(I64_CONST)
        code.extend(_signed(1))
        get(count)
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SUB)
        code.append(I64_SHL)
        get(discarded)
        code.extend((I64_LT_U, IF, EMPTY))
        increment(significand)
        code.append(ELSE)
        code.append(I64_CONST)
        code.extend(_signed(1))
        get(count)
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SUB)
        code.append(I64_SHL)
        get(discarded)
        code.extend((I64_EQ, IF, EMPTY))
        round_tie()
        code.extend((END, END))
        code.append(ELSE)
        get(quotient)
        set_(significand)
        code.append(I64_CONST)
        code.extend(_signed(52))
        get(exponent)
        code.append(I64_SUB)
        set_(count)
        append_fraction_bits()
        round_fraction()
        code.append(END)
        code.append(END)

        get(significand)
        code.append(I64_CONST)
        code.extend(_signed(1 << 53))
        code.extend((I64_EQ, IF, EMPTY))
        get(significand)
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SHR_U)
        set_(significand)
        increment(exponent)
        code.append(END)
        get(significand)
        code.append(F64_CONVERT_I64_S)
        get(exponent)
        code.append(I64_CONST)
        code.extend(_signed(971))
        code.append(I64_ADD)
        code.append(I64_CONST)
        code.extend(_signed(52))
        code.append(I64_SHL)
        code.append(F64_REINTERPRET_I64)
        code.append(F64_MUL)
        set_(self.local_indices[self.float_scratch])
        get(sign)
        code.extend((IF, F64))
        get(self.local_indices[self.float_scratch])
        code.append(F64_NEG)
        code.append(ELSE)
        get(self.local_indices[self.float_scratch])
        code.extend((END, END))

    def python_integer_division(
        self,
        code: bytearray,
        *,
        modulo: bool,
        fixed: bool,
    ) -> None:
        left = self.local_indices[self.integer_scratch]
        right = self.local_indices[self.integer_scratch_right]
        quotient = self.local_indices[self.integer_quotient_scratch]
        remainder = self.local_indices[self.integer_remainder_scratch]
        code.append(LOCAL_SET)
        code.extend(_unsigned(right))
        code.append(LOCAL_SET)
        code.extend(_unsigned(left))
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.extend((I64_EQZ, IF, EMPTY, UNREACHABLE, END))
        code.append(LOCAL_GET)
        code.extend(_unsigned(left))
        code.append(I64_CONST)
        code.extend(_signed(-(2**63)))
        code.extend((I64_EQ, IF, I64))
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.append(I64_CONST)
        code.extend(_signed(-1))
        code.extend((I64_EQ, IF, I64))
        if fixed:
            self.wgsl_integer_division_fallback(code, left, modulo)
        else:
            code.append(UNREACHABLE)
        code.append(ELSE)
        self.python_integer_division_operation(
            code,
            left,
            right,
            quotient,
            remainder,
            modulo,
        )
        code.append(END)
        code.append(ELSE)
        self.python_integer_division_operation(
            code,
            left,
            right,
            quotient,
            remainder,
            modulo,
        )
        code.append(END)

    @staticmethod
    def python_integer_division_operation(
        code: bytearray,
        left: int,
        right: int,
        quotient: int,
        remainder: int,
        modulo: bool,
    ) -> None:
        code.append(LOCAL_GET)
        code.extend(_unsigned(left))
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.append(I64_REM_S)
        code.append(LOCAL_SET)
        code.extend(_unsigned(remainder))
        code.append(LOCAL_GET)
        code.extend(_unsigned(left))
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.append(I64_DIV_S)
        code.append(LOCAL_SET)
        code.extend(_unsigned(quotient))
        code.append(LOCAL_GET)
        code.extend(_unsigned(remainder))
        code.append(I64_EQZ)
        code.append(I32_EQZ)
        code.append(LOCAL_GET)
        code.extend(_unsigned(remainder))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.append(I64_LT_S)
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.append(I64_LT_S)
        code.extend((I32_XOR, I32_AND, IF, I64))
        code.append(LOCAL_GET)
        code.extend(_unsigned(remainder if modulo else quotient))
        if modulo:
            code.append(LOCAL_GET)
            code.extend(_unsigned(right))
        else:
            code.append(I64_CONST)
            code.extend(_signed(-1))
        code.append(I64_ADD)
        code.append(ELSE)
        code.append(LOCAL_GET)
        code.extend(_unsigned(remainder if modulo else quotient))
        code.append(END)

    def integer_power(self, code: bytearray) -> None:
        base = self.local_indices[self.integer_scratch]
        exponent = self.local_indices[self.integer_scratch_right]
        result = self.local_indices[self.integer_quotient_scratch]
        code.append(LOCAL_SET)
        code.extend(_unsigned(exponent))
        code.append(LOCAL_SET)
        code.extend(_unsigned(base))
        code.append(LOCAL_GET)
        code.extend(_unsigned(exponent))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.extend((I64_LT_S, IF, EMPTY, UNREACHABLE, END))
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(LOCAL_SET)
        code.extend(_unsigned(result))
        code.extend((BLOCK, EMPTY, LOOP, EMPTY))
        code.append(LOCAL_GET)
        code.extend(_unsigned(exponent))
        code.extend((I64_EQZ, BR_IF))
        code.extend(_unsigned(1))
        code.append(LOCAL_GET)
        code.extend(_unsigned(exponent))
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.extend((I64_AND, I64_EQZ, IF, EMPTY))
        code.append(ELSE)
        code.append(LOCAL_GET)
        code.extend(_unsigned(result))
        code.append(LOCAL_GET)
        code.extend(_unsigned(base))
        code.append(I64_MUL)
        code.append(LOCAL_SET)
        code.extend(_unsigned(result))
        code.append(END)
        code.append(LOCAL_GET)
        code.extend(_unsigned(base))
        code.append(LOCAL_GET)
        code.extend(_unsigned(base))
        code.append(I64_MUL)
        code.append(LOCAL_SET)
        code.extend(_unsigned(base))
        code.append(LOCAL_GET)
        code.extend(_unsigned(exponent))
        code.append(I64_CONST)
        code.extend(_signed(1))
        code.append(I64_SHR_U)
        code.append(LOCAL_SET)
        code.extend(_unsigned(exponent))
        code.append(BR)
        code.extend(_unsigned(0))
        code.extend((END, END, LOCAL_GET))
        code.extend(_unsigned(result))

    def integer_shift(
        self,
        code: bytearray,
        *,
        left: bool,
        signed: bool,
        bits: int,
    ) -> None:
        value = self.local_indices[self.integer_scratch]
        count = self.local_indices[self.integer_scratch_right]
        code.append(LOCAL_SET)
        code.extend(_unsigned(count))
        code.append(LOCAL_SET)
        code.extend(_unsigned(value))
        code.append(LOCAL_GET)
        code.extend(_unsigned(count))
        code.append(I64_CONST)
        code.extend(_signed(0))
        code.extend((I64_LT_S, IF, EMPTY, UNREACHABLE, END))
        code.append(LOCAL_GET)
        code.extend(_unsigned(count))
        code.append(I64_CONST)
        code.extend(_signed(bits))
        code.extend((I64_LT_U, IF, I64))
        code.append(LOCAL_GET)
        code.extend(_unsigned(value))
        code.append(LOCAL_GET)
        code.extend(_unsigned(count))
        code.append(
            I64_SHL if left else I64_SHR_S if signed else I64_SHR_U
        )
        code.append(ELSE)
        if left or not signed:
            code.append(I64_CONST)
            code.extend(_signed(0))
        else:
            code.append(LOCAL_GET)
            code.extend(_unsigned(value))
            code.append(I64_CONST)
            code.extend(_signed(bits - 1))
            code.append(I64_SHR_S)
        code.append(END)

    @staticmethod
    def wgsl_integer_division_fallback(
        code: bytearray,
        left: int,
        modulo: bool,
    ) -> None:
        if modulo:
            code.append(I64_CONST)
            code.extend(_signed(0))
        else:
            code.append(LOCAL_GET)
            code.extend(_unsigned(left))

    @staticmethod
    def wgsl_integer_division_operation(
        code: bytearray,
        left: int,
        right: int,
        signed: bool,
        modulo: bool,
    ) -> None:
        code.append(LOCAL_GET)
        code.extend(_unsigned(left))
        code.append(LOCAL_GET)
        code.extend(_unsigned(right))
        code.append(
            I64_REM_S
            if modulo and signed
            else I64_REM_U
            if modulo
            else I64_DIV_S
            if signed
            else I64_DIV_U
        )

    def normalize_float_result(
        self,
        code: bytearray,
        node: ast.expr,
    ) -> ValueType:
        storage_format = analyzed_numeric_format(node)
        if (
            storage_format is not None
            and storage_format.kind == "float"
            and storage_format.bits == 32
        ):
            code.extend((F32_DEMOTE_F64, F64_PROMOTE_F32))
        return F64

    def widen_numeric(
        self,
        code: bytearray,
        storage_type: ValueType | None,
        storage_format: NumericFormat | None,
    ) -> ValueType | None:
        if storage_type is None or storage_format is None:
            return storage_type
        if storage_type == I32 and storage_format.kind == "integer":
            self.normalize_i32(code, storage_format)
            code.append(I64_EXTEND_I32_S if storage_format.signed else I64_EXTEND_I32_U)
            return I64
        if storage_type == F32 and storage_format.kind == "float":
            code.append(F64_PROMOTE_F32)
            return F64
        return storage_type

    @staticmethod
    def normalize_i32(code: bytearray, storage_format: NumericFormat) -> None:
        if storage_format.bits not in {8, 16}:
            return
        if storage_format.signed:
            operation = I32_EXTEND8_S if storage_format.bits == 8 else I32_EXTEND16_S
            code.append(operation)
            return
        code.append(I32_CONST)
        code.extend(_signed(2**storage_format.bits - 1))
        code.append(I32_AND)

    def set_local(self, code: bytearray, name: str) -> None:
        code.append(LOCAL_SET)
        code.extend(_unsigned(self.local_indices[name]))

    def assign_target(
        self,
        code: bytearray,
        target,
        actual_type: ValueType | None = None,
    ) -> None:
        if isinstance(target, (ast.Name, ast.arg, BlockArgument)):
            name = self.target_name(target)
            expected_type = self.local_value_types[name]
            if actual_type is not None and actual_type != expected_type:
                self.narrow_numeric(
                    code,
                    actual_type,
                    expected_type,
                    self.local_numeric_formats.get(name),
                    target,
                )
            self.set_local(code, name)
            return
        scratch, tuple_type = self.tuple_unpack_slots[target]
        self.set_local(code, scratch)
        tuple_index = self.tuple_indices[tuple_type]
        for index, (element, item_type) in enumerate(
            zip(
                target.elts,
                tuple_type.generic_types.values(),
                strict=True,
            )
        ):
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[scratch]))
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(tuple_index))
            code.extend(_unsigned(index))
            self.assign_target(code, element, self.value_type(item_type))

    def target_name(self, target) -> str:
        if isinstance(target, ast.Name):
            return self.name_aliases.get(target.id, target.id)
        if isinstance(target, ast.arg):
            return target.arg
        if isinstance(target, BlockArgument):
            return target.name
        raise WebAssemblyUnsupported(
            "WebAssembly assignment target is not implemented",
            target,
        )

    def reference_type(self, value_type: Class) -> bytes:
        if value_type not in self.class_indices:
            raise WebAssemblyUnsupported(
                f"WebAssembly class {value_type.name} is not implemented"
            )
        return self.reference_type_index(self.class_indices[value_type])

    @staticmethod
    def reference_type_index(index: int) -> bytes:
        return b"\x63" + _signed(index)

    @staticmethod
    def collection_item_type(value_type: Class) -> Class:
        if not value_type.generic_types:
            raise WebAssemblyUnsupported(
                "WebAssembly lists require an inferred item type"
            )
        return next(iter(value_type.generic_types.values()))

    def iterator_item_type(self, iterator) -> Class:
        if isinstance(iterator, _ListIterator):
            return self.collection_item_type(iterator.value_type)
        if isinstance(iterator, _RangeIterator):
            return iterator.item_type
        if isinstance(iterator, (_EnumerateIterator, _ZipIterator)):
            return iterator.item_type
        raise WebAssemblyUnsupported("WebAssembly iterator is not implemented")

    def is_tuple_get(self, node: ast.Call) -> bool:
        target = analyzed_value_object(node.func)
        return (
            isinstance(target, Function)
            and target.name == "__getitem__"
            and isinstance(node.func, ast.Attribute)
            and analyzed_value_type(node.func.value) in self.tuple_indices
            and len(node.args) == 1
            and not node.keywords
        )

    @staticmethod
    def is_extreme_call(node: ast.Call) -> bool:
        target = analyzed_value_object(node.func)
        return isinstance(target, Function) and target.py_func in {
            native_builtins._min,
            native_builtins._max,
        }

    def extreme(self, code: bytearray, node: ast.Call) -> ValueType:
        if len(node.args) < 2 or node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly min and max require two or more positional values",
                node,
            )
        value_type = self.value_type(analyzed_value_type(node))
        if value_type not in {I32, I64, F64}:
            raise WebAssemblyUnsupported(
                "WebAssembly min and max require scalar numeric values",
                node,
            )
        best_slot, candidate_slot = self.extreme_slots[node]
        self.expression_as(code, node.args[0], value_type)
        self.set_local(code, best_slot)
        is_minimum = analyzed_value_object(node.func).py_func is native_builtins._min
        comparisons = {
            I32: I32_LT_S if is_minimum else I32_GT_S,
            I64: I64_LT_S if is_minimum else I64_GT_S,
            F64: F64_LT if is_minimum else F64_GT,
        }
        for argument in node.args[1:]:
            self.expression_as(code, argument, value_type)
            self.set_local(code, candidate_slot)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[candidate_slot]))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[best_slot]))
            code.extend((comparisons[value_type], IF, EMPTY, LOCAL_GET))
            code.extend(_unsigned(self.local_indices[candidate_slot]))
            self.set_local(code, best_slot)
            code.append(END)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[best_slot]))
        if value_type == I64:
            return self.normalize_integer_result(code, node)
        if value_type == F64:
            return self.normalize_float_result(code, node)
        return value_type

    def hypot(self, code: bytearray, node: ast.Call) -> ValueType:
        if node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly math.hypot takes positional arguments",
                node,
            )
        value_slots, maximum_slot, total_slot, infinite_slot = self.hypot_slots[node]
        code.append(F64_CONST)
        code.extend(struct.pack("<d", 0.0))
        self.set_local(code, maximum_slot)
        code.append(I32_CONST)
        code.extend(_signed(0))
        self.set_local(code, infinite_slot)
        for argument, value_slot in zip(node.args, value_slots, strict=True):
            self.expression_as(code, argument, F64)
            code.append(F64_ABS)
            self.set_local(code, value_slot)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[value_slot]))
            code.append(F64_CONST)
            code.extend(struct.pack("<d", float("inf")))
            code.append(F64_EQ)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[infinite_slot]))
            code.append(I32_OR)
            self.set_local(code, infinite_slot)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[value_slot]))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[maximum_slot]))
            code.extend((F64_GT, IF, EMPTY, LOCAL_GET))
            code.extend(_unsigned(self.local_indices[value_slot]))
            self.set_local(code, maximum_slot)
            code.append(END)

        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[infinite_slot]))
        code.extend((IF, F64, F64_CONST))
        code.extend(struct.pack("<d", float("inf")))
        code.extend((ELSE, LOCAL_GET))
        code.extend(_unsigned(self.local_indices[maximum_slot]))
        code.append(F64_CONST)
        code.extend(struct.pack("<d", 0.0))
        code.extend((F64_EQ, IF, F64))
        self.hypot_sum(code, value_slots, None, total_slot)
        code.extend((ELSE,))
        self.hypot_sum(code, value_slots, maximum_slot, total_slot)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[maximum_slot]))
        code.append(F64_MUL)
        code.extend((END, END))
        return F64

    def hypot_sum(
        self,
        code: bytearray,
        value_slots: tuple[str, ...],
        maximum_slot: str | None,
        total_slot: str,
    ) -> None:
        code.append(F64_CONST)
        code.extend(struct.pack("<d", 0.0))
        self.set_local(code, total_slot)
        for value_slot in value_slots:
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[value_slot]))
            if maximum_slot is not None:
                code.append(LOCAL_GET)
                code.extend(_unsigned(self.local_indices[maximum_slot]))
                code.append(F64_DIV)
            code.append(LOCAL_TEE)
            code.extend(_unsigned(self.local_indices[self.float_scratch]))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[self.float_scratch]))
            code.append(F64_MUL)
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[total_slot]))
            code.append(F64_ADD)
            self.set_local(code, total_slot)
        code.append(LOCAL_GET)
        code.extend(_unsigned(self.local_indices[total_slot]))
        code.append(F64_SQRT)

    def linear_memory_call(
        self,
        code: bytearray,
        node: ast.Call,
        function,
    ) -> ValueType | None:
        if node.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly linear-memory operations take positional arguments",
                node,
            )
        if function is linear_memory.memory_byte_length:
            if node.args:
                raise WebAssemblyUnsupported(
                    "memory_byte_length takes no arguments",
                    node,
                )
            code.extend((MEMORY_SIZE, 0x00, I64_EXTEND_I32_U, I64_CONST))
            code.extend(_signed(linear_memory.PAGE_BYTES))
            code.append(I64_MUL)
            return I64
        if function is linear_memory.grow_memory:
            if len(node.args) != 1:
                raise WebAssemblyUnsupported(
                    "grow_memory takes one page count",
                    node,
                )
            self.expression_as(code, node.args[0], I64)
            code.extend((I32_WRAP_I64, MEMORY_GROW, 0x00, I64_EXTEND_I32_S))
            return I64

        loads = {
            linear_memory.load_i32: (I32_LOAD, 2, I64),
            linear_memory.load_f32: (F32_LOAD, 2, F64),
            linear_memory.load_f64: (F64_LOAD, 3, F64),
        }
        if function in loads:
            if len(node.args) != 1:
                raise WebAssemblyUnsupported(
                    "linear-memory loads take one byte offset",
                    node,
                )
            operation, alignment, result_type = loads[function]
            self.expression_as(code, node.args[0], I64)
            code.extend((I32_WRAP_I64, operation))
            code.extend(_unsigned(alignment))
            code.extend(_unsigned(0))
            if function is linear_memory.load_i32:
                code.append(I64_EXTEND_I32_S)
            elif function is linear_memory.load_f32:
                code.append(F64_PROMOTE_F32)
            return result_type

        stores = {
            linear_memory.store_i32: (I32_STORE, 2, I64),
            linear_memory.store_f32: (F32_STORE, 2, F64),
            linear_memory.store_f64: (F64_STORE, 3, F64),
        }
        if function not in stores or len(node.args) != 2:
            raise WebAssemblyUnsupported(
                "linear-memory stores take a byte offset and value",
                node,
            )
        operation, alignment, value_type = stores[function]
        self.expression_as(code, node.args[0], I64)
        code.append(I32_WRAP_I64)
        self.expression_as(code, node.args[1], value_type)
        if function is linear_memory.store_i32:
            code.append(I32_WRAP_I64)
        elif function is linear_memory.store_f32:
            code.append(F32_DEMOTE_F64)
        code.append(operation)
        code.extend(_unsigned(alignment))
        code.extend(_unsigned(0))
        return None

    @staticmethod
    def constant_tuple_index(node: ast.expr, length: int) -> int:
        value = None
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            value = node.value
        elif (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, int)
        ):
            value = -node.operand.value
        if value is None:
            raise WebAssemblyUnsupported(
                "WebAssembly tuple indexing requires a constant integer",
                node,
            )
        actual = value + length if value < 0 else value
        if actual < 0 or actual >= length:
            raise WebAssemblyUnsupported(
                "WebAssembly tuple index is out of range",
                node,
            )
        return actual

    def is_list_get(self, node: ast.Call) -> bool:
        target = analyzed_value_object(node.func)
        if not (
            isinstance(target, Function)
            and target.name == "__getitem__"
            and isinstance(node.func, ast.Attribute)
        ):
            return False
        receiver_type = analyzed_value_type(node.func.value)
        return receiver_type.generic_name == "list" and receiver_type in self.list_indices

    def is_list_constructor(self, node: ast.Call) -> bool:
        target = analyzed_value_object(node.func)
        return (
            isinstance(target, Class)
            and target.generic_name == "list"
            and target in self.list_indices
            and len(node.args) == 1
            and not node.keywords
            and analyzed_value_type(node.args[0]) == target
        )

    @staticmethod
    def is_list_concat(node: ast.Call) -> bool:
        target = analyzed_value_object(node.func)
        return (
            isinstance(target, Function)
            and target.name == "__add__"
            and isinstance(node.func, ast.Attribute)
            and analyzed_value_type(node.func.value).generic_name == "list"
        )

    def is_list_set(self, node: ast.Call) -> bool:
        target = analyzed_value_object(node.func)
        if not (
            isinstance(target, Function)
            and target.name == "__setitem__"
            and isinstance(node.func, ast.Attribute)
        ):
            return False
        receiver_type = analyzed_value_type(node.func.value)
        return receiver_type.generic_name == "list" and receiver_type in self.list_indices

    def value_type(self, value_type) -> ValueType:
        if isinstance(value_type, UnionType):
            return self.value_type(self.nullable_reference_member(value_type))
        if value_type.generic_name == "bool":
            return I32
        if value_type.generic_name == "int":
            return I64
        if value_type.generic_name == "float":
            return F64
        if value_type in self.list_indices:
            return self.reference_type_index(self.list_indices[value_type][1])
        if value_type in self.tuple_indices:
            return self.reference_type_index(self.tuple_indices[value_type])
        if value_type in self.class_indices:
            return self.reference_type(value_type)
        raise WebAssemblyUnsupported(
            f"WebAssembly value type {value_type.name} is not implemented"
        )

    def nullable_reference_member(self, value_type: UnionType) -> Class:
        members = tuple(value_type.types)
        concrete = tuple(
            member for member in members if member.generic_name != "NoneType"
        )
        if (
            len(members) != 2
            or len(concrete) != 1
            or not (
                concrete[0] in self.list_indices
                or concrete[0] in self.tuple_indices
                or concrete[0] in self.class_indices
            )
        ):
            raise WebAssemblyUnsupported(
                "WebAssembly union value storage is not implemented"
            )
        return concrete[0]

    @staticmethod
    def numeric_storage_type(
        storage_format: NumericFormat | None,
        *,
        packed: bool = False,
    ) -> ValueType | None:
        if storage_format is None:
            return None
        if storage_format.kind == "float":
            return F32 if storage_format.bits == 32 else F64
        if storage_format.bits == 64:
            return I64
        if packed and storage_format.bits == 8:
            return PACKED_I8
        if packed and storage_format.bits == 16:
            return PACKED_I16
        return I32

    def storage_type(
        self,
        value_type,
        storage_format: NumericFormat | None,
        *,
        packed: bool = False,
    ) -> ValueType:
        return self.numeric_storage_type(
            storage_format,
            packed=packed,
        ) or self.value_type(value_type)

    @staticmethod
    def storage_carrier(storage_type: ValueType) -> ValueType:
        return I32 if storage_type in {PACKED_I8, PACKED_I16} else storage_type

    @staticmethod
    def struct_get_operation(
        storage_type: ValueType,
        storage_format: NumericFormat | None,
    ) -> int:
        if storage_type not in {PACKED_I8, PACKED_I16}:
            return STRUCT_GET
        return STRUCT_GET_S if storage_format.signed else STRUCT_GET_U

    def annotation(self, node: ast.expr | None) -> ValueType | None:
        if node is None or isinstance(node, ast.Constant) and node.value is None:
            return None
        value_object = getattr(node, "obj", None)
        if isinstance(value_object, UnionType):
            return self.value_type(value_object)
        if isinstance(value_object, Class):
            return self.value_type(value_object)
        if isinstance(node, ast.Name):
            if node.id in {"None", "NoneType"}:
                return None
            if node.id == "bool":
                return I32
            if node.id == "int":
                return I64
            if node.id == "float":
                return F64
            if node.id in self.class_names:
                return self.reference_type(self.class_names[node.id])
        raise WebAssemblyUnsupported(
            "WebAssembly type annotation is not implemented", node
        )

    def function_return_storage_type(
        self,
        function: Function,
    ) -> ValueType | None:
        if getattr(function.return_type, "generic_name", None) == "NoneType":
            return None
        return self.storage_type(
            function.return_type,
            function.return_numeric_format,
        )

    def parameter_type(self, function: Function, parameter: ast.arg) -> ValueType:
        value = function.scope.names.get(parameter.arg)
        if isinstance(value, Instance):
            return self.value_type(value.cls)
        result = self.annotation(parameter.annotation)
        if result is None:
            raise WebAssemblyUnsupported(
                "WebAssembly parameters require a value type",
                parameter,
            )
        return result

    def parameter_storage_type(
        self,
        function: Function,
        parameter: ast.arg,
    ) -> ValueType:
        return self.numeric_storage_type(
            analyzed_numeric_format(parameter),
        ) or self.parameter_type(function, parameter)

    @staticmethod
    def local_numeric_format(
        function: Function,
        target,
    ) -> NumericFormat | None:
        if not isinstance(target, (ast.Name, ast.arg)):
            return None
        name = target.id if isinstance(target, ast.Name) else target.arg
        try:
            value = function.scope.lookup(name)
        except NameError:
            # A loop body that always returns has no binding at the function's
            # exit join. Its analyzed target still owns the physical local.
            value = getattr(target, "obj", None)
        return analyzed_numeric_format(value.storage_declaration) if isinstance(value, Instance) else None


def transpile_webassembly(
    source: str,
    *,
    filename: str = "_pyjs_webassembly_.py",
    module_name: str | None = None,
    exports: tuple[str, ...] = ("main",),
) -> WebAssemblyCompilation:
    """Emit a module exporting the named source functions and reached memory."""
    if not exports:
        raise ValueError("WebAssembly compilation requires at least one export")
    if len(set(exports)) != len(exports):
        raise ValueError("WebAssembly export names must be unique")
    if "memory" in exports:
        raise ValueError("WebAssembly function exports cannot be named memory")

    def select_additional_roots(module):
        return tuple(getattr(module, name) for name in exports[1:])

    with analyze_source(
        textwrap.dedent(source),
        filename=filename,
        module_name=module_name,
        entry_point=exports[0],
        wrap=False,
        root_selector=select_additional_roots,
        environment=WEBASSEMBLY_ENVIRONMENT,
    ) as analysis:
        entry_points = analysis.entry_point.compilation_entry_points
        program = build_program_ir(analysis.entry_point, entry_points[1:])
        return WebAssemblyEmitter().emit(
            program,
            tuple(zip(exports, entry_points, strict=True)),
        )


__all__ = [
    "WebAssemblyCompilation",
    "WebAssemblyUnsupported",
    "transpile_webassembly",
]

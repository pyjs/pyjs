"""Emit a small executable WebAssembly module directly from ProgramIR."""

import ast
import struct
import textwrap
from dataclasses import dataclass
from pathlib import Path

from pyjs.analysis.analyzer import analyzed_value_type
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
from pyjs.analysis.objects import Class, Function, Instance, TypeVariableClass, UnionType
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import (
    analyzed_array_format,
    analyzed_numeric_format,
    analyzed_value_object,
)
from pyjs.numeric import NumericFormat
from pyjs.python import native as native_builtins
from pyjs.stdlib.math import isfinite

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
I32_LT_S = 0x48
I32_LT_U = 0x49
I64_EQZ = 0x50
I64_EQ = 0x51
I64_LT_S = 0x53
I64_LT_U = 0x54
I64_GE_S = 0x59
I32_ADD = 0x6A
I32_MUL = 0x6C
I32_AND = 0x71
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

    def emit(self, program: ProgramIR) -> WebAssemblyCompilation:
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
        self.list_types = self.discover_list_types(program)
        first_list_index = len(application_classes)
        self.list_indices = {
            value_type: (
                first_list_index + index * 2,
                first_list_index + index * 2 + 1,
            )
            for index, value_type in enumerate(self.list_types)
        }
        gc_type_count = len(application_classes) + len(self.list_types) * 2
        self.prepare_classes(application_classes)
        self.functions = [
            function
            for function in program.functions
            if (function.cls is None or function.cls in self.classes)
            and function.ir is not None
            and any(isinstance(block, Block) for block in function.ir.blocks)
            and not getattr(function.py_func, "__builtin__", False)
        ]
        if program.entry_point not in self.functions:
            raise WebAssemblyUnsupported("the WebAssembly entry point has no scalar body")
        self.indices = {function: index for index, function in enumerate(self.functions)}
        signatures = [self.signature(function) for function in self.functions]
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
        functions = _vector([_unsigned(index) for index in type_indices])
        entry_index = self.indices[program.entry_point]
        exports = _vector([_name("main") + b"\x00" + _unsigned(entry_index)])
        code = _vector([self.function(function) for function in self.functions])
        module = b"\x00asm\x01\x00\x00\x00" + b"".join(
            (
                _section(1, types),
                _section(3, functions),
                _section(7, exports),
                _section(10, code),
            )
        )
        return WebAssemblyCompilation(module)

    def discover_list_types(self, program: ProgramIR) -> list[Class]:
        found = set()

        def add(value_type) -> None:
            if not isinstance(value_type, Class):
                return
            if value_type.generic_name != "list":
                return
            item_type = self.list_item_type(value_type)
            if isinstance(item_type, TypeVariableClass):
                return
            if value_type in found:
                return
            found.add(value_type)
            add(item_type)

        for layout in program.classes:
            add(layout.value_type)
            for field in layout.fields:
                add(field.value_type)
        for function in program.functions:
            add(function.return_type)
            for parameter in function.params:
                value = function.scope.names.get(parameter.arg)
                if isinstance(value, Instance):
                    add(value.cls)
            if function.ir is None:
                continue
            for block in function.ir.blocks:
                for statement in getattr(block, "body", ()):
                    for node in ast.walk(statement):
                        if isinstance(node, CollectionNew):
                            add(node.value_type)
        return sorted(found, key=lambda value_type: value_type.name)

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
        for list_type in self.list_types:
            array_index, _list_index = self.list_indices[list_type]
            structs.extend(
                (
                    bytes((ARRAY_TYPE,))
                    + _encoded_type(self.value_type(self.list_item_type(list_type)))
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
        if self.has_recursive_fields or self.list_types:
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
        self.list_get_slots = {}
        self.list_set_slots = {}
        self.iterators = {}

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
            for statement in block.body:
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
                    value_type = self.value_type(analyzed_value_type(statement.value))
                    for target in statement.targets:
                        storage_format = self.local_numeric_format(function, target)
                        name = self.target_name(target)
                        add_local(
                            name,
                            self.numeric_storage_type(storage_format)
                            if storage_format is not None else value_type,
                        )
                        if storage_format is not None:
                            self.local_numeric_formats[name] = storage_format
                elif isinstance(statement, IteratorCreate):
                    list_type = analyzed_value_type(statement.iterable)
                    if list_type.generic_name != "list":
                        raise WebAssemblyUnsupported(
                            "WebAssembly iteration currently requires a list",
                            statement,
                        )
                    _array_index, list_index = self.list_indices[list_type]
                    prefix = f"__pyjs_{statement.name}"
                    self.iterators[statement.name] = (
                        list_type,
                        add_generated_local(
                            f"{prefix}_source",
                            self.reference_type_index(list_index),
                        ),
                        add_generated_local(f"{prefix}_index", I32),
                        analyzed_array_format(statement.iterable),
                    )

        for block in blocks:
            for statement in block.body:
                if isinstance(statement, IteratorNext):
                    list_type, _source, _index, _layout = self.iterators[
                        statement.iterator
                    ]
                    storage_format = self.local_numeric_format(
                        function,
                        statement.target,
                    )
                    add_local(
                        self.target_name(statement.target),
                        self.numeric_storage_type(storage_format)
                        if storage_format is not None
                        else self.value_type(self.list_item_type(list_type)),
                    )
                    if storage_format is not None:
                        self.local_numeric_formats[self.target_name(statement.target)] = (
                            storage_format
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
                        slots = {}
                        for name, value in evaluation:
                            slot = add_generated_local(
                                f"__pyjs_object_{len(self.object_result_slots)}_{name}",
                                self.value_type(analyzed_value_type(value)),
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
                                self.value_type(self.list_item_type(list_type)),
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
                                self.value_type(self.list_item_type(list_type)),
                            ),
                        )
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
            name = self.target_name(node.targets[0])
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
        if isinstance(node, IteratorCreate):
            list_type, source_slot, index_slot, _layout = self.iterators[node.name]
            self.expression_as(code, node.iterable, self.value_type(list_type))
            self.set_local(code, source_slot)
            code.append(I32_CONST)
            code.extend(_signed(0))
            self.set_local(code, index_slot)
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
            if node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None
            ):
                self.expression_for_storage(
                    code,
                    node.value,
                    self.function_return_storage_type(self.current_function),
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
                if storage_format is None:
                    self.expression(code, value)
                else:
                    actual_type = self.expression(code, value)
                    self.narrow_numeric(
                        code,
                        actual_type,
                        self.numeric_storage_type(storage_format),
                        storage_format,
                        value,
                    )
            for argument in reversed(target_block.arguments):
                self.set_local(code, argument.name)
            code.append(I32_CONST)
            code.extend(_signed(target))
            self.set_local(code, state)
            code.extend((BR, 0x01))
            return
        if isinstance(node, Branch):
            self.expression(code, node.test)
            code.extend((IF, EMPTY, I32_CONST))
            code.extend(_signed(blocks[node.true]))
            self.set_local(code, state)
            code.extend((ELSE, I32_CONST))
            code.extend(_signed(blocks[node.false]))
            self.set_local(code, state)
            code.extend((END, BR, 0x01))
            return
        if isinstance(node, IteratorNext):
            list_type, source_slot, index_slot, layout = self.iterators[node.iterator]
            array_index, list_index = self.list_indices[list_type]
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[index_slot]))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[source_slot]))
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(list_index))
            code.extend(_unsigned(1))
            code.extend((I32_LT_U, IF, EMPTY))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[source_slot]))
            code.extend((GC_PREFIX, STRUCT_GET))
            code.extend(_unsigned(list_index))
            code.extend(_unsigned(0))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[index_slot]))
            code.extend((GC_PREFIX, ARRAY_GET))
            code.extend(_unsigned(array_index))
            if layout is not None and layout.item_numeric is not None:
                self.narrow_numeric(
                    code,
                    self.value_type(self.list_item_type(list_type)),
                    self.numeric_storage_type(layout.item_numeric),
                    layout.item_numeric,
                    node,
                )
            self.set_local(code, self.target_name(node.target))
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[index_slot]))
            code.append(I32_CONST)
            code.extend(_signed(1))
            code.append(I32_ADD)
            self.set_local(code, index_slot)
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
            name = node.id if isinstance(node, ast.Name) else node.name
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[name]))
            return self.widen_numeric(
                code,
                self.local_value_types[name],
                self.local_numeric_formats.get(name),
            )
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                self.expression(code, node.operand)
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
            self.expression(code, node.test)
            result_type = self.value_type(analyzed_value_type(node))
            code.append(IF)
            code.extend(_encoded_type(result_type))
            self.expression(code, node.body)
            code.append(ELSE)
            self.expression(code, node.orelse)
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
            list_type = analyzed_value_type(node.args[0])
            if list_type.generic_name != "list":
                raise WebAssemblyUnsupported(
                    "WebAssembly len currently requires a list",
                    node,
                )
            _array_index, list_index = self.list_indices[list_type]
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
            if target.name == "__bool__" and receiver_type == I64:
                code.extend((I64_EQZ, I32_EQZ))
                return I32
        name = getattr(target, "name", type(target).__name__)
        raise WebAssemblyUnsupported(
            f"WebAssembly call target {name} is not implemented",
            node,
        )

    def collection_new(self, code: bytearray, node: CollectionNew) -> bytes:
        if node.value_type.generic_name != "list" or not isinstance(
            node.source,
            ast.List,
        ):
            raise WebAssemblyUnsupported(
                f"WebAssembly {node.value_type.generic_name} allocation "
                "is not implemented",
                node,
            )
        item_type = self.value_type(self.list_item_type(node.value_type))
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

    def list_append(self, code: bytearray, node: ListAppend) -> None:
        if len(node.call.args) != 1 or node.call.keywords:
            raise WebAssemblyUnsupported(
                "WebAssembly list append takes one positional argument",
                node,
            )
        list_type = analyzed_value_type(node.call.func.value)
        array_index, list_index = self.list_indices[list_type]
        item_type = self.value_type(self.list_item_type(list_type))
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
        return self.value_type(self.list_item_type(list_type))

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
            self.value_type(self.list_item_type(list_type)),
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
        for name, argument in evaluation:
            self.expression(code, argument)
            self.set_local(code, slots[name])
        code.extend((GC_PREFIX, STRUCT_NEW_DEFAULT))
        code.extend(_unsigned(self.class_indices[node.value_type]))
        result = self.object_result_slots[node]
        self.set_local(code, result)
        constructor = self.classes[node.value_type].constructor
        if constructor in self.indices:
            code.append(LOCAL_GET)
            code.extend(_unsigned(self.local_indices[result]))
            parameters = {parameter.arg: parameter for parameter in constructor.params}
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
        actual_type = self.expression(code, node)
        return self.narrow_numeric(
            code,
            actual_type,
            storage_type,
            storage_format,
            node,
        )

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

    @staticmethod
    def target_name(target) -> str:
        if isinstance(target, ast.Name):
            return target.id
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
    def list_item_type(value_type: Class) -> Class:
        if not value_type.generic_types:
            raise WebAssemblyUnsupported(
                "WebAssembly lists require an inferred item type"
            )
        return next(iter(value_type.generic_types.values()))

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
            raise WebAssemblyUnsupported("WebAssembly union value storage is not implemented")
        if value_type.generic_name == "bool":
            return I32
        if value_type.generic_name == "int":
            return I64
        if value_type.generic_name == "float":
            return F64
        if value_type in self.list_indices:
            return self.reference_type_index(self.list_indices[value_type][1])
        if value_type in self.class_indices:
            return self.reference_type(value_type)
        raise WebAssemblyUnsupported(
            f"WebAssembly value type {value_type.name} is not implemented"
        )

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
) -> WebAssemblyCompilation:
    """Analyze source and emit a directly executable WebAssembly binary."""
    with analyze_source(
        textwrap.dedent(source),
        filename=filename,
        module_name=module_name,
        wrap=False,
        environment=WEBASSEMBLY_ENVIRONMENT,
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        return WebAssemblyEmitter().emit(program)


__all__ = [
    "WebAssemblyCompilation",
    "WebAssemblyUnsupported",
    "transpile_webassembly",
]

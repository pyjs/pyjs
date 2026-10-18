"""Emit a typed Python subset directly as executable JVM bytecode."""

import annotationlib
import ast
import inspect
import math
import re
import types
import typing
from dataclasses import dataclass
from pathlib import Path

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.ir import (
    Block,
    BlockArgument,
    Branch,
    ClassIR,
    CollectionNew,
    ExceptionCatch,
    ExceptionDispatch,
    ExceptionRaise,
    External,
    FieldLoad,
    FieldStore,
    IteratorCreate,
    IteratorNext,
    Jump,
    ListAppend,
    ObjectNew,
    ProgramIR,
    Return,
    build_program_ir,
)
from pyjs.analysis.objects import (
    Await as AnalyzedAwait,
)
from pyjs.analysis.objects import (
    Class,
    Function,
    GenericClass,
    Instance,
    Module,
    RecursiveTypeAlias,
    StaticCast,
    UnionType,
)
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import (
    analyzed_numeric_format,
    analyzed_representation,
    analyzed_value_object,
)
from pyjs.decorators import JVMField, backend_metadata, is_declaration
from pyjs.numeric import NumericFormat, numeric_format
from pyjs.python import native as native_builtins

from .analysis import JVM_ENVIRONMENT
from .classfile import (
    Annotation,
    Bytecode,
    ClassAnnotationValue,
    ClassFile,
    ExceptionHandler,
    Field,
    Method,
)
from .exceptions import emit_exception_class, exception_type
from .primitives import Reference, run_sync
from .string_runtime import emit_string_helpers


def _is_reference_descriptor(descriptor: str) -> bool:
    return descriptor.startswith(("L", "["))


def _jvm_array_item(annotation) -> object | None:
    value_type, _metadata, _class_variable = _annotation_parts(annotation)
    origin = typing.get_origin(value_type) or value_type
    if not getattr(origin, "__pyjs_jvm_array__", False):
        return None
    arguments = typing.get_args(value_type)
    return arguments[0] if len(arguments) == 1 else None


def _optional_reference_member(annotation) -> object | None:
    value_type, _metadata, _class_variable = _annotation_parts(annotation)
    if typing.get_origin(value_type) not in {typing.Union, types.UnionType}:
        return None
    members = typing.get_args(value_type)
    concrete = tuple(
        member for member in members if member is not None and member is not type(None)
    )
    return concrete[0] if len(concrete) == 1 and len(members) == 2 else None


def _annotation_parts(annotation) -> tuple[object, tuple[object, ...], bool]:
    metadata = []
    class_variable = False
    while True:
        if isinstance(annotation, typing.TypeAliasType):
            annotation = annotation.__value__
            continue
        origin = typing.get_origin(annotation)
        if origin is typing.ClassVar:
            class_variable = True
            annotation = typing.get_args(annotation)[0]
            continue
        if origin is typing.Annotated:
            annotation, *values = typing.get_args(annotation)
            metadata.extend(values)
            continue
        return annotation, tuple(metadata), class_variable


def _abi_descriptor(annotation) -> str | None:
    value_type, metadata, _class_variable = _annotation_parts(annotation)
    if (member := _optional_reference_member(annotation)) is not None:
        descriptor = _abi_descriptor(member) or _native_type_descriptor(member)
        return descriptor if descriptor and _is_reference_descriptor(descriptor) else None
    if (item := _jvm_array_item(annotation)) is not None:
        descriptor = _abi_descriptor(item) or _native_type_descriptor(item)
        return f"[{descriptor}" if descriptor is not None else None
    if (representation := numeric_format(annotation)) is not None:
        return _numeric_descriptor(representation)
    for value in metadata:
        if isinstance(value, Reference):
            return f"L{value.owner};"
    if inspect.isclass(value_type) and is_declaration(value_type, "jvm"):
        return f"L{backend_metadata(value_type, 'jvm', 'owner')};"
    return None


def _numeric_descriptor(value: NumericFormat | None) -> str | None:
    if value is None:
        return None
    return {
        ("integer", 8, True): "B",
        ("integer", 8, False): "B",
        ("integer", 16, True): "S",
        ("integer", 16, False): "C",
        ("integer", 32, True): "I",
        ("integer", 32, False): "I",
        ("integer", 64, True): "J",
        ("float", 32, None): "F",
        ("float", 64, None): "D",
    }.get((value.kind, value.bits, value.signed))


def _native_type_descriptor(annotation) -> str | None:
    value_type, _metadata, _class_variable = _annotation_parts(annotation)
    if (member := _optional_reference_member(annotation)) is not None:
        descriptor = _native_type_descriptor(member) or _abi_descriptor(member)
        return descriptor if descriptor and _is_reference_descriptor(descriptor) else None
    if (item := _jvm_array_item(annotation)) is not None:
        descriptor = _abi_descriptor(item) or _native_type_descriptor(item)
        return f"[{descriptor}" if descriptor is not None else None
    representation = numeric_format(annotation)
    if representation is not None:
        descriptor = _numeric_descriptor(representation)
        if descriptor in {"B", "C", "S", "I", "J"}:
            return "J"
        if descriptor in {"F", "D"}:
            return "D"
    builtin = {
        int: "J",
        float: "D",
        bool: "Z",
        str: "Ljava/lang/String;",
        None: "V",
        type(None): "V",
    }.get(value_type)
    if builtin is not None:
        return builtin
    if inspect.isclass(value_type) and is_declaration(value_type, "jvm"):
        return f"L{backend_metadata(value_type, 'jvm', 'owner')};"
    return None


@dataclass(frozen=True)
class JVMCompilation:
    """The main class and all typed application classes it reaches."""

    main_class: str
    classes: dict[str, bytes]
    tests: tuple[JVMCompiledTest, ...] = ()
    resources: tuple[Path, ...] = ()
    test_modules: tuple[str, ...] = ()

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        for name, content in self.classes.items():
            path = directory / f"{name}.class"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return directory / f"{self.main_class}.class"


@dataclass(frozen=True)
class JVMTest:
    nodeid: str
    module_name: str
    function_name: str


@dataclass(frozen=True)
class JVMCompiledTest:
    nodeid: str
    class_name: str
    method_name: str


@dataclass(frozen=True)
class NativeField:
    owner: str
    name: str
    abi_type: str
    semantic_type: str
    static: bool
    writable: bool
    numeric_format: NumericFormat | None = None


class JVMUnsupported(Exception):
    """A program uses semantics not yet represented by the JVM backend."""

    def __init__(self, message: str, node: ast.AST | None = None) -> None:
        location = (
            f" at line {node.lineno}"
            if node is not None and hasattr(node, "lineno")
            else ""
        )
        super().__init__(f"{message}{location}")


class JVMEmitter:
    """Lower target-neutral ProgramIR directly into JVM class files."""

    INTEGER_OPCODES = {
        "__add__": 0x61,
        "__radd__": 0x61,
        "__sub__": 0x65,
        "__mul__": 0x69,
        "__rmul__": 0x69,
        "__and__": 0x7F,
        "__rand__": 0x7F,
        "__or__": 0x81,
        "__ror__": 0x81,
        "__xor__": 0x83,
        "__rxor__": 0x83,
    }
    INTEGER_COMPARISONS = {
        "__eq__": 0x99,
        "__ne__": 0x9A,
        "__lt__": 0x9B,
        "__ge__": 0x9C,
        "__gt__": 0x9D,
        "__le__": 0x9E,
    }

    def __init__(
        self,
        class_name: str,
        source_file: str,
        tests: tuple[JVMTest, ...] = (),
        test_sdk: int | None = None,
        test_manifest: str | None = None,
    ) -> None:
        identifier = r"[A-Za-z_$][A-Za-z0-9_$]*"
        if re.fullmatch(rf"{identifier}(?:/{identifier})*", class_name) is None:
            raise ValueError("the JVM class name must contain valid identifiers")
        self.source_file = Path(source_file).name
        self.class_file = ClassFile(class_name, source_file=self.source_file)
        self.main_class_name = class_name
        self.class_files = {class_name: self.class_file}
        self.module_classes = {}
        self.functions: set[Function] = set()
        self.native_functions: set[Function] = set()
        self.classes: dict[Class, ClassIR] = {}
        self.native_classes: set[Class] = set()
        self.native_interfaces: set[Class] = set()
        self.native_layouts: dict[Class, ClassIR] = {}
        self.code = Bytecode()
        self.slots = {}
        self.slot_types = {}
        self.object_argument_slots = {}
        self.list_classes = {}
        self.tuple_classes = {}
        self.iterators = {}
        self.next_label = 0
        self.async_call_depth = 0
        self.string_helpers = set()
        self.tests = tests
        self.test_sdk = test_sdk
        self.test_manifest = test_manifest

    def emit(self, program: ProgramIR) -> JVMCompilation:
        module = program.entry_point.container
        self.module_classes[module] = self.main_class_name
        classes = [
            layout
            for layout in program.classes
            if isinstance(layout.value_type.container, Module)
            and layout.value_type.container.name != "pyjs.python.native"
            and not is_declaration(layout.value_type.py_obj, "jvm")
        ]
        self.native_classes = {
            layout.value_type
            for layout in program.classes
            if is_declaration(layout.value_type.py_obj, "jvm")
        }
        self.native_layouts = {
            layout.value_type: layout
            for layout in program.classes
            if layout.value_type in self.native_classes
        }
        self.native_interfaces = {
            value_type
            for value_type in self.native_classes
            if backend_metadata(value_type.py_obj, "jvm", "interface", False)
        }
        self.classes = {layout.value_type: layout for layout in classes}
        functions = [
            function
            for function in program.functions
            if function.ir is not None
            and (
                function.cls in self.classes
                or isinstance(function.container, Module)
                and function.container.name != "pyjs.python.native"
            )
            and not any(isinstance(block, External) for block in function.ir.blocks)
        ]
        self.native_functions = {
            function
            for function in program.functions
            if function.ir is not None
            and any(isinstance(block, External) for block in function.ir.blocks)
            and (
                is_declaration(function.py_func, "jvm")
                or function.cls in self.native_classes
            )
        }
        if program.entry_point not in functions:
            raise JVMUnsupported("the JVM entry point has no analyzable body")
        self.functions = set(functions)
        self.validate_method_contracts(classes, functions)
        for function in functions:
            if function.cls is None:
                self.ensure_module_class(function.container)
        subclassed = {layout.base for layout in classes if layout.base in self.classes}
        for layout in classes:
            base = layout.base
            interface = base if base in self.native_interfaces else None
            super_name = (
                self.class_name(base)
                if base in self.classes
                else self.native_class_name(base)
                if base in self.native_classes and interface is None
                else "java/lang/Object"
            )
            class_file = ClassFile(
                self.class_name(layout.value_type),
                super_name,
                0x0021 if layout.value_type in subclassed else 0x0031,
                source_file=self.module_source_file(layout.value_type.container),
                interfaces=(self.native_class_name(interface),)
                if interface is not None
                else (),
            )
            self.class_files[class_file.name] = class_file
            for field in layout.fields:
                class_file.add_field(
                    Field(
                        0x0001,
                        field.name,
                        _numeric_descriptor(field.numeric_format)
                        or self.value_type(field.value_type, field.representation),
                    )
                )
            initializer = layout.constructor
            if (
                self.has_native_superclass(layout.value_type)
                and initializer in self.functions
            ):
                class_file.add_method(
                    self.native_subclass_constructor(
                        class_file,
                        layout,
                        initializer,
                    )
                )
            else:
                if (
                    base in self.native_classes
                    and base not in self.native_interfaces
                    and self.native_descriptor(self.native_layouts[base].constructor)
                    != "()V"
                ):
                    raise JVMUnsupported(
                        f"JVM subclass {layout.value_type.name} must define an "
                        "initializer for its native superclass constructor"
                    )
                class_file.add_method(self.default_constructor(class_file))
        for function in functions:
            for block in function.ir.blocks:
                if not isinstance(block, Block):
                    continue
                for statement in block.body:
                    for node in ast.walk(statement):
                        value_type = getattr(node, "value_type", None)
                        if (
                            isinstance(node, CollectionNew)
                            and value_type.generic_name == "list"
                        ):
                            self.list_class(value_type)
                        elif (
                            isinstance(node, CollectionNew)
                            and value_type.generic_name == "tuple"
                        ):
                            self.tuple_class(value_type)
        for function in functions:
            self.class_file = self.class_files[self.function_owner(function)]
            try:
                method = self.function(function)
            except JVMUnsupported as error:
                raise JVMUnsupported(
                    f"{error} while compiling "
                    f"{function.py_func.__module__}."
                    f"{function.py_func.__qualname__}"
                ) from error
            self.class_file.add_method(method)
        compiled_tests = self.emit_test_class(functions) if self.tests else ()
        self.class_file = self.class_files[self.main_class_name]
        emit_string_helpers(self.class_file, self.string_helpers)
        self.class_file.add_method(self.main_wrapper(program.entry_point))
        return JVMCompilation(
            self.main_class_name,
            {name: class_file.render() for name, class_file in self.class_files.items()},
            compiled_tests,
            test_modules=tuple(dict.fromkeys(test.module_name for test in self.tests)),
        )

    def emit_test_class(
        self,
        functions: list[Function],
    ) -> tuple[JVMCompiledTest, ...]:
        targets = {
            (function.py_func.__module__, function.name): function
            for function in functions
            if function.cls is None
        }
        class_name = f"{self.main_class_name}$Tests"
        annotations = [
            Annotation(
                "Lorg/junit/runner/RunWith;",
                (
                    (
                        "value",
                        ClassAnnotationValue(
                            "Landroidx/test/ext/junit/runners/AndroidJUnit4;"
                        ),
                    ),
                ),
            ),
        ]
        if self.test_sdk is not None:
            config_values: list[tuple[str, object]] = [("sdk", (self.test_sdk,))]
            if self.test_manifest is not None:
                config_values.append(("manifest", self.test_manifest))
            annotations.append(
                Annotation(
                    "Lorg/robolectric/annotation/Config;",
                    tuple(config_values),
                )
            )
        class_file = ClassFile(
            class_name,
            source_file=self.source_file,
            annotations=tuple(annotations),
        )
        class_file.add_method(self.default_constructor(class_file))
        compiled = []
        for index, test in enumerate(self.tests):
            try:
                target = targets[(test.module_name, test.function_name)]
            except KeyError:
                raise JVMUnsupported(
                    f"JVM test {test.module_name}.{test.function_name} was not reached"
                ) from None
            if target.params or self.function_return_type(target) != "V":
                raise JVMUnsupported(
                    f"JVM test {test.module_name}.{test.function_name} must take no "
                    "arguments and return None"
                )
            method_name = re.sub(
                r"[^A-Za-z0-9_$]",
                "_",
                f"test_{index}_{test.function_name}",
            )
            code = Bytecode()
            reference = class_file.method_reference(
                self.function_owner(target),
                self.function_name(target),
                self.descriptor(target),
            )
            code.emit(0xB8, reference.to_bytes(2, "big"))
            code.emit(0xB1)
            class_file.add_method(
                Method(
                    0x0001,
                    method_name,
                    "()V",
                    code.render(),
                    0,
                    1,
                    annotations=(Annotation("Lorg/junit/Test;"),),
                )
            )
            compiled.append(JVMCompiledTest(test.nodeid, class_name, method_name))
        close = Bytecode()
        reference = class_file.method_reference(
            "org/pyjs/testing/PyjsAndroid",
            "close",
            "()V",
        )
        close.emit(0xB8, reference.to_bytes(2, "big"))
        close.emit(0xB1)
        class_file.add_method(
            Method(
                0x0001,
                "pyjs_close_activity",
                "()V",
                close.render(),
                0,
                1,
                annotations=(Annotation("Lorg/junit/After;"),),
            )
        )
        self.class_files[class_name] = class_file
        return tuple(compiled)

    def validate_method_contracts(
        self,
        classes: list[ClassIR],
        functions: list[Function],
    ) -> None:
        """Reject Python dispatch that cannot be represented by JVM descriptors."""

        methods = {
            (function.cls, function.name): function
            for function in functions
            if function.cls in self.classes and function.name != "__init__"
        }
        for (owner, name), implementation in methods.items():
            base = self.classes[owner].base
            while base in self.classes:
                inherited = methods.get((base, name))
                if inherited is not None:
                    if self.descriptor(implementation) != self.descriptor(inherited):
                        raise JVMUnsupported(
                            f"JVM override {owner.name}.{name} must preserve the "
                            "base method signature"
                        )
                    break
                base = self.classes[base].base

            declaration = self.native_override(implementation)
            if declaration is not None and self.descriptor(
                implementation
            ) != self.native_descriptor(declaration):
                contract = (
                    "interface"
                    if declaration.cls in self.native_interfaces
                    else "native method"
                )
                raise JVMUnsupported(
                    f"JVM implementation {owner.name}.{name} must preserve "
                    f"the {contract} signature"
                )

        for layout in classes:
            interface = layout.base
            if interface not in self.native_interfaces:
                continue
            for declaration in interface.children:
                if (
                    not isinstance(declaration, Function)
                    or declaration.name == "__init__"
                ):
                    continue
                implementation = methods.get((layout.value_type, declaration.name))
                if implementation is None:
                    raise JVMUnsupported(
                        f"JVM class {layout.value_type.name} does not implement "
                        f"{interface.name}.{declaration.name}"
                    )
                if self.descriptor(implementation) != self.native_descriptor(declaration):
                    raise JVMUnsupported(
                        f"JVM implementation {layout.value_type.name}."
                        f"{declaration.name} must preserve the interface signature"
                    )

    def function(self, function: Function) -> Method:
        self.current_function = function
        if function.vararg or function.kwarg or function.kwonlyargs:
            raise JVMUnsupported(
                "JVM functions do not yet support variadic or keyword-only parameters"
            )
        unsupported_default = next(
            (
                default
                for default in function.defaults
                if not self.is_immutable_default(default)
            ),
            None,
        )
        if unsupported_default is not None:
            raise JVMUnsupported(
                "JVM function defaults must be immutable literals",
                unsupported_default,
            )
        blocks = [block for block in function.ir.blocks if isinstance(block, Block)]
        if not blocks:
            raise JVMUnsupported(f"JVM function {function.name} has no blocks")
        parameters = [
            (
                parameter.arg,
                _numeric_descriptor(analyzed_numeric_format(parameter))
                or self.parameter_type(parameter),
            )
            for parameter in function.params
        ]
        if function.cls in self.classes:
            parameters.insert(0, ("self", self.class_descriptor(function.cls)))
        self.prepare_locals(function, parameters)
        self.return_type = self.function_return_type(function)
        self.return_storage_type = (
            _numeric_descriptor(function.return_numeric_format) or self.return_type
        )
        self.code = Bytecode()
        self.line_offset = (function.lineno or 1) - 1
        block_map = {block.name: block for block in blocks}
        protected = []
        for block in blocks:
            self.code.mark(self.block_label(block.name))
            start = len(self.code.code)
            for statement in block.body:
                line = self.source_line(statement)
                self.code.line(line + self.line_offset if line is not None else None)
                self.statement(statement, block_map)
            if block.exception_target is not None and len(self.code.code) > start:
                protected.append((start, len(self.code.code), block.exception_target))
        landings = {}
        for _start, _end, target in protected:
            if target not in landings:
                landings[target] = len(self.code.code)
                self.code.local(0x3A, self.pending_exception_slot)
                self.code.branch(0xA7, self.block_label(target))
        return Method(
            # Reachable module functions live on the root class, but generated
            # application classes call them as siblings rather than JVM nestmates.
            0x0001 if function.cls in self.classes else 0x0009,
            self.function_name(function),
            self.descriptor(function),
            self.code.render(),
            # Version 49 verification accepts a conservative declared maximum.
            # Track exact depth only when a newer class format requires frames.
            0xFFFF,
            self.local_count,
            tuple(self.code.line_numbers),
            exception_handlers=tuple(
                ExceptionHandler(start, end, landings[target])
                for start, end, target in protected
            ),
        )

    def prepare_locals(self, function, parameters) -> None:
        self.slots = {}
        self.slot_types = {}
        self.slot_numeric_formats = {
            parameter.arg: analyzed_numeric_format(parameter)
            for parameter in function.params
            if analyzed_numeric_format(parameter) is not None
        }
        self.object_argument_slots = {}
        self.iterators = {}
        self.local_count = 0
        object_index = 0

        def add(name: str, value_type: str) -> None:
            if name in self.slots:
                current = self.slot_types[name]
                if current == value_type or self.compatible(value_type, current):
                    return
                if self.compatible(current, value_type):
                    self.slot_types[name] = value_type
                    return
                raise JVMUnsupported(f"JVM local {name} changes type")
            self.slots[name] = self.local_count
            self.slot_types[name] = value_type
            self.local_count += 2 if value_type in {"J", "D"} else 1

        for name, value_type in parameters:
            add(name, value_type)
        for block in function.ir.blocks:
            if not isinstance(block, Block):
                continue
            for argument in block.arguments:
                storage_format = analyzed_numeric_format(argument)
                add(
                    argument.name,
                    _numeric_descriptor(storage_format)
                    or self.value_type(
                        argument.value_type, analyzed_representation(argument),
                    ),
                )
                if storage_format is not None:
                    self.slot_numeric_formats[argument.name] = storage_format
            for statement in block.body:
                if isinstance(statement, ExceptionCatch):
                    if statement.target is not None:
                        add(self.target_name(statement.target), "Ljava/lang/Throwable;")
                elif isinstance(statement, ast.AnnAssign):
                    if isinstance(statement.target, ast.Attribute):
                        field = self.native_field(statement.target)
                        if field is not None and field.static:
                            continue
                    value_type = (
                        analyzed_value_type(statement.value)
                        if statement.value is not None
                        else None
                    )
                    semantic = (
                        self.expression_type(statement.value)
                        if value_type is not None
                        and (
                            self.is_jvm_array_type(value_type)
                            or isinstance(value_type, UnionType)
                        )
                        else self.annotation(statement.annotation)
                    )
                    storage_format = self.local_numeric_format(statement.target)
                    add(
                        self.target_name(statement.target),
                        _numeric_descriptor(storage_format) or semantic,
                    )
                    if storage_format is not None:
                        self.slot_numeric_formats[self.target_name(statement.target)] = (
                            storage_format
                        )
                elif isinstance(statement, ast.Assign):
                    value_type = self.expression_type(statement.value)
                    for target in statement.targets:
                        if isinstance(target, ast.Attribute):
                            field = self.native_field(target)
                            if field is not None and field.static:
                                continue
                        name = self.target_name(target)
                        storage_format = self.local_numeric_format(target)
                        add(name, _numeric_descriptor(storage_format) or value_type)
                        if storage_format is not None:
                            self.slot_numeric_formats[name] = storage_format
                elif isinstance(statement, FieldStore):
                    value_type = self.expression_type(statement.value)
                    add(f"__field_{value_type}", value_type)
                elif isinstance(statement, IteratorCreate):
                    descriptor = self.iterator_descriptor(statement)
                    self.iterators[statement.name] = descriptor
                    if descriptor[0] == "range":
                        for part in ("current", "stop", "step"):
                            add(f"{statement.name}.{part}", "J")
                    else:
                        add(f"{statement.name}.source", descriptor[2])
                        add(f"{statement.name}.index", "J")
                elif isinstance(statement, IteratorNext):
                    descriptor = self.iterators[statement.iterator]
                    storage_format = self.local_numeric_format(statement.target)
                    if storage_format is not None and isinstance(
                        statement.target,
                        (ast.Name, ast.arg),
                    ):
                        add(
                            self.target_name(statement.target),
                            _numeric_descriptor(storage_format),
                        )
                    else:
                        self.add_iterator_target(
                            add,
                            statement.target,
                            descriptor[3],
                        )
                    if storage_format is not None:
                        self.slot_numeric_formats[self.target_name(statement.target)] = (
                            storage_format
                        )
                    if isinstance(statement.target, (ast.List, ast.Tuple)):
                        add(f"{statement.iterator}.item", descriptor[1])
                for node in ast.walk(statement):
                    if isinstance(node, ast.Call):
                        target = analyzed_value_object(node.func)
                        if isinstance(target, Function) and target.name in {
                            "__truediv__",
                            "__rtruediv__",
                            "__floordiv__",
                            "__rfloordiv__",
                            "__mod__",
                            "__rmod__",
                        }:
                            add("__integer.dividend", "J")
                            add("__integer.divisor", "J")
                            add("__wgsl.dividend", "J")
                            add("__wgsl.divisor", "J")
                        if isinstance(target, Function) and target.name in {
                            "__pow__",
                            "__rpow__",
                        }:
                            add("__integer.power.base", "J")
                            add("__integer.power.exponent", "J")
                            add("__integer.power.result", "J")
                        if isinstance(target, Function) and target.name in {
                            "__lshift__",
                            "__rshift__",
                        }:
                            add("__integer.shift.value", "J")
                            add("__integer.shift.count", "J")
                    if not isinstance(node, ObjectNew):
                        continue
                    if self.is_jvm_array_type(node.value_type):
                        continue
                    if (
                        node.value_type not in self.classes
                        and node.value_type not in self.native_classes
                    ):
                        continue
                    evaluation, _ordered = self.constructor_arguments(node)
                    slots = {}
                    for name, value in evaluation:
                        slot = f"__object_{object_index}_{name}"
                        add(slot, self.expression_type(value))
                        slots[name] = slot
                    self.object_argument_slots[node] = slots
                    object_index += 1

        self.pending_exception_slot = self.local_count
        if any(block.exception_target is not None for block in function.ir.blocks
               if isinstance(block, Block)):
            self.local_count += 1

    def statement(self, node, blocks) -> None:
        if isinstance(node, ExceptionCatch):
            if node.target is not None:
                self.code.local(0x19, self.pending_exception_slot)
                self.store(self.target_name(node.target), "Ljava/lang/Throwable;")
            return
        if isinstance(node, ExceptionDispatch):
            for types, target in node.handlers:
                if not types:
                    self.code.branch(0xA7, self.block_label(target))
                    return
                for value_type in types:
                    name = self.exception_match_class(value_type, node)
                    self.code.local(0x19, self.pending_exception_slot)
                    index = self.class_file.constants.class_(name)
                    self.code.emit(0xC1, index.to_bytes(2, "big"))
                    self.code.branch(0x9A, self.block_label(target))
            if node.unmatched is not None:
                self.code.branch(0xA7, self.block_label(node.unmatched))
            else:
                self.code.local(0x19, self.pending_exception_slot)
                self.code.emit(0xBF)
            return
        if isinstance(node, ExceptionRaise):
            self.raise_python_exception(node)
            return
        if isinstance(node, Return):
            if node.value is None or (
                isinstance(node.value, ast.Constant) and node.value.value is None
            ):
                if _is_reference_descriptor(self.return_type):
                    self.code.emit(0x01)
                    self.code.emit(0xB0)
                    return
                if self.return_type != "V":
                    raise JVMUnsupported(
                        f"cannot return void from {self.return_type} function",
                        node,
                    )
                self.code.emit(0xB1)
                return
            value_type = self.expression(node.value)
            if not self.compatible(value_type, self.return_type):
                raise JVMUnsupported(
                    f"cannot return {value_type} from {self.return_type} function",
                    node,
                )
            self.convert_native_argument(
                value_type,
                self.return_storage_type,
                node,
            )
            self.code.emit(
                0xAD
                if self.return_storage_type == "J"
                else 0xAF
                if self.return_storage_type == "D"
                else 0xAE
                if self.return_storage_type == "F"
                else 0xAC
                if self.return_storage_type in {"B", "C", "S", "I", "Z"}
                else 0xB0
            )
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                if isinstance(node.target, ast.Attribute) and self.static_field_store(
                    node.target,
                    node.value,
                ):
                    return
                value_type = self.expression(node.value)
                self.store(self.target_name(node.target), value_type)
            return
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Attribute) and self.static_field_store(
                node.targets[0],
                node.value,
            ):
                return
            value_type = self.expression(node.value)
            self.store(self.target_name(node.targets[0]), value_type)
            return
        if isinstance(node, FieldStore):
            value_type = self.expression(node.value)
            scratch = f"__field_{value_type}"
            self.store(scratch, value_type)
            (
                receiver_type,
                owner,
                name,
                field_type,
                _semantic_type,
                writable,
                _numeric_format,
            ) = self.field(node.target)
            if not writable:
                raise JVMUnsupported(f"JVM field {owner}.{name} is read-only", node)
            actual_receiver = self.expression(node.target.value)
            if not self.compatible(actual_receiver, receiver_type):
                if _is_reference_descriptor(actual_receiver) and (
                    _is_reference_descriptor(receiver_type)
                ):
                    self.checkcast(receiver_type)
                else:
                    raise JVMUnsupported(
                        f"JVM field {owner}.{name} receiver {actual_receiver} "
                        f"is incompatible with {receiver_type}",
                        node,
                    )
            self.load(scratch)
            self.convert_native_argument(value_type, field_type, node)
            reference = self.class_file.field_reference(owner, name, field_type)
            self.code.emit(0xB5, reference.to_bytes(2, "big"))
            return
        if isinstance(node, ast.Expr):
            value_type = self.expression(node.value)
            if value_type in {"J", "D"}:
                self.code.emit(0x58)
            elif value_type != "V":
                self.code.emit(0x57)
            return
        if isinstance(node, ListAppend):
            self.list_append(node)
            return
        if isinstance(node, IteratorCreate):
            self.iterator_create(node)
            return
        if isinstance(node, IteratorNext):
            self.iterator_next(node)
            return
        if isinstance(node, Branch):
            if self.expression(node.test) != "Z":
                raise JVMUnsupported("JVM branch conditions must be bool", node.test)
            self.code.branch(0x9A, self.block_label(node.true))
            self.code.branch(0xA7, self.block_label(node.false))
            return
        if isinstance(node, Jump):
            target = blocks[node.target]
            values = [self.expression(value) for value in node.arguments]
            for argument, value_type in reversed(
                list(zip(target.arguments, values, strict=True))
            ):
                self.store(argument.name, value_type)
            self.code.branch(0xA7, self.block_label(node.target))
            return
        raise JVMUnsupported(
            f"unsupported JVM statement {type(node).__name__}",
            node,
        )

    def expression(self, node) -> str:
        if isinstance(node, AnalyzedAwait):
            return self.immediate_async_call(node.value, node)
        if isinstance(node, StaticCast):
            source = self.expression(node.value)
            target = self.expression_type(node)
            if _is_reference_descriptor(source) and _is_reference_descriptor(target):
                cast_target = target[1:-1] if target.startswith("L") else target
                class_index = self.class_file.constants.class_(cast_target)
                self.code.emit(0xC0, class_index.to_bytes(2, "big"))
                return target
            if source == target:
                return target
            raise JVMUnsupported(
                f"JVM cannot cast {source} to {target}",
                node,
            )
        if isinstance(node, ast.Constant):
            if node.value is None:
                self.code.emit(0x01)
                return "N"
            if node.value is True:
                self.code.emit(0x04)
                return "Z"
            if node.value is False:
                self.code.emit(0x03)
                return "Z"
            if isinstance(node.value, int):
                self.long_constant(node.value)
                self.normalize_integer_result(node)
                return "J"
            if isinstance(node.value, float):
                self.double_constant(node.value)
                self.normalize_float_result(node)
                return "D"
            if isinstance(node.value, str):
                self.string_constant(node.value)
                return "Ljava/lang/String;"
            raise JVMUnsupported(f"unsupported JVM constant {node.value!r}", node)
        if isinstance(node, ast.Name):
            target = analyzed_value_object(node)
            if isinstance(target, Function):
                raise JVMUnsupported("JVM function values are not implemented", node)
            if isinstance(target, Class) and target in self.classes:
                index = self.class_file.constants.class_(self.class_name(target))
                if index <= 255:
                    self.code.emit(0x12, index.to_bytes(1, "big"))
                else:
                    self.code.emit(0x13, index.to_bytes(2, "big"))
                return "Ljava/lang/Class;"
            if (
                isinstance(target, Instance)
                and target.static_value is not None
                and isinstance(target.static_value, ast.Constant)
            ):
                return self.expression(target.static_value)
            if isinstance(target, Instance) and isinstance(target.container, Module):
                raise JVMUnsupported("JVM module collection state is not implemented", node)
        if isinstance(node, (ast.Name, BlockArgument)):
            name = node.id if isinstance(node, ast.Name) else node.name
            return self.load(name)
        if isinstance(node, ast.UnaryOp):
            if (
                isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)
                and node.operand.value == 2**63
            ):
                self.long_constant(-(2**63))
                return "J"
            value_type = self.expression(node.operand)
            if isinstance(node.op, ast.UAdd) and value_type == "J":
                return "J"
            if isinstance(node.op, ast.USub) and value_type == "J":
                self.code.emit(0x75)
                self.normalize_integer_result(node)
                return "J"
            if isinstance(node.op, ast.Invert) and value_type == "J":
                self.long_constant(-1)
                self.code.emit(0x83)
                self.normalize_integer_result(node)
                return "J"
            if isinstance(node.op, ast.UAdd) and value_type == "D":
                return "D"
            if isinstance(node.op, ast.USub) and value_type == "D":
                self.code.emit(0x77)
                self.normalize_float_result(node)
                return "D"
            if isinstance(node.op, ast.Not) and value_type == "Z":
                self.code.emit(0x04)
                self.code.emit(0x82)
                return "Z"
            raise JVMUnsupported("unsupported JVM unary operation", node)
        if isinstance(node, ast.IfExp):
            otherwise = self.new_label("conditional.else")
            done = self.new_label("conditional.done")
            if self.expression(node.test) != "Z":
                raise JVMUnsupported("JVM conditional test must be bool", node.test)
            self.code.branch(0x99, otherwise)
            result = self.expression_type(node)
            self.convert_native_argument(self.expression(node.body), result, node.body)
            self.code.branch(0xA7, done)
            self.code.mark(otherwise)
            self.convert_native_argument(self.expression(node.orelse), result, node.orelse)
            self.code.mark(done)
            if result == "J":
                self.normalize_integer_result(node)
            elif result == "D":
                self.normalize_float_result(node)
            return result
        if isinstance(node, ast.BoolOp):
            result_type = self.expression_type(node)
            if result_type == "Ljava/lang/String;":
                matched = self.new_label("bool.string.matched")
                done = self.new_label("bool.string.done")
                is_empty = self.class_file.method_reference(
                    "java/lang/String",
                    "isEmpty",
                    "()Z",
                )
                for value in node.values[:-1]:
                    if self.expression(value) not in {result_type, "N"}:
                        raise JVMUnsupported(
                            "JVM string boolean operator changes type",
                            value,
                        )
                    discard = self.new_label("bool.string.discard")
                    self.code.emit(0x59)
                    self.code.branch(
                        0xC6, matched if isinstance(node.op, ast.And) else discard,
                    )
                    self.code.emit(0x59)
                    self.code.emit(0xB6, is_empty.to_bytes(2, "big"))
                    self.code.branch(
                        0x9A if isinstance(node.op, ast.And) else 0x99,
                        matched,
                    )
                    self.code.mark(discard)
                    self.code.emit(0x57)
                if self.expression(node.values[-1]) not in {result_type, "N"}:
                    raise JVMUnsupported(
                        "JVM string boolean operator changes type",
                        node.values[-1],
                    )
                self.code.branch(0xA7, done)
                self.code.mark(matched)
                self.code.mark(done)
                return result_type
            matched = self.new_label("bool.matched")
            done = self.new_label("bool.done")
            match_opcode = 0x99 if isinstance(node.op, ast.And) else 0x9A
            matched_value = 0 if isinstance(node.op, ast.And) else 1
            for value in node.values:
                if self.expression(value) != "Z":
                    raise JVMUnsupported(
                        "JVM boolean operators require bool operands",
                        value,
                    )
                self.code.branch(match_opcode, matched)
            self.code.emit(0x04 if matched_value == 0 else 0x03)
            self.code.branch(0xA7, done)
            self.code.mark(matched)
            self.code.emit(0x03 if matched_value == 0 else 0x04)
            self.code.mark(done)
            return "Z"
        if isinstance(node, ast.JoinedStr):
            return self.joined_string(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ObjectNew):
            return self.object_new(node)
        if isinstance(node, CollectionNew):
            return self.collection_new(node)
        if isinstance(node, ListAppend):
            self.list_append(node)
            return "V"
        if isinstance(node, FieldLoad):
            (
                receiver_type,
                owner,
                name,
                field_type,
                semantic_type,
                _writable,
                storage_format,
            ) = self.field(node.attribute)
            actual_receiver = self.expression(node.attribute.value)
            if not self.compatible(actual_receiver, receiver_type):
                if _is_reference_descriptor(actual_receiver) and (
                    _is_reference_descriptor(receiver_type)
                ):
                    self.checkcast(receiver_type)
                else:
                    raise JVMUnsupported(
                        f"JVM field {owner}.{name} receiver {actual_receiver} "
                        f"is incompatible with {receiver_type}",
                        node,
                    )
            reference = self.class_file.field_reference(owner, name, field_type)
            self.code.emit(0xB4, reference.to_bytes(2, "big"))
            self.convert_abi_result(field_type, semantic_type, storage_format)
            return semantic_type
        if isinstance(node, ast.Attribute):
            field = self.native_field(node)
            if field is not None and field.static:
                reference = self.class_file.field_reference(
                    field.owner,
                    field.name,
                    field.abi_type,
                )
                self.code.emit(0xB2, reference.to_bytes(2, "big"))
                self.convert_abi_result(
                    field.abi_type,
                    field.semantic_type,
                    field.numeric_format,
                )
                return field.semantic_type
        raise JVMUnsupported(
            f"unsupported JVM expression {type(node).__name__}",
            node,
        )

    def call(self, node: ast.Call) -> str:
        target = getattr(node.func, "obj", None)
        if isinstance(target, Class) and target.py_obj is native_builtins._slice:
            raise JVMUnsupported("JVM first-class slice construction is not implemented", node)
        if isinstance(target, Function) and target.py_func is native_builtins._print:
            raise JVMUnsupported("JVM print() output is not implemented", node)
        if isinstance(target, Function) and target.py_func is run_sync:
            if len(node.args) != 1 or node.keywords:
                raise JVMUnsupported(
                    "JVM run_sync() takes one positional awaitable", node
                )
            return self.immediate_async_call(node.args[0], node)
        if (
            isinstance(target, Function)
            and target.is_async
            and self.async_call_depth == 0
        ):
            raise JVMUnsupported(
                "JVM async calls must be immediately awaited or passed to run_sync()",
                node,
            )
        if isinstance(node.func, ast.Name) and node.func.id == "int":
            if not node.args:
                self.long_constant(0)
            elif len(node.args) == 1 and not node.keywords:
                value_type = self.expression(node.args[0])
                if value_type == "D":
                    self.code.emit(0x8F)
                elif value_type == "Z":
                    self.code.emit(0x85)
                elif value_type == "Ljava/lang/String;":
                    self.string_helpers.add("int")
                    reference = self.class_file.method_reference(
                        self.main_class_name,
                        "pyjs_string_int",
                        "(Ljava/lang/String;)J",
                    )
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                elif value_type != "J":
                    raise JVMUnsupported(
                        "JVM int construction requires a number or string",
                        node,
                    )
            else:
                raise JVMUnsupported(
                    "JVM int construction accepts one number or string",
                    node,
                )
            self.normalize_integer_result(node)
            return "J"
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            if not node.args:
                self.code.emit(0x0E)
            elif len(node.args) == 1 and not node.keywords:
                value_type = self.expression(node.args[0])
                if value_type == "J":
                    self.code.emit(0x8A)
                elif value_type != "D":
                    raise JVMUnsupported(
                        "fixed-width float construction requires a number",
                        node,
                    )
            else:
                raise JVMUnsupported(
                    "fixed-width float construction accepts one number",
                    node,
                )
            self.normalize_float_result(node)
            return "D"
        if isinstance(target, Function) and target.py_func is native_builtins._abs:
            if len(node.args) != 1 or node.keywords:
                raise JVMUnsupported("JVM abs takes one positional argument", node)
            value_type = self.expression(node.args[0])
            if value_type == "Z":
                self.code.emit(0x85)
                return "J"
            descriptors = {"J": "(J)J", "D": "(D)D"}
            descriptor = descriptors.get(value_type)
            if descriptor is None:
                raise JVMUnsupported("JVM abs requires an int or float", node)
            reference = self.class_file.method_reference(
                "java/lang/Math",
                "abs",
                descriptor,
            )
            self.code.emit(0xB8, reference.to_bytes(2, "big"))
            self.normalize_integer_result(node)
            return value_type
        if isinstance(target, Function) and target.py_func is native_builtins._len:
            if len(node.args) != 1 or node.keywords:
                raise JVMUnsupported("JVM len takes one positional argument", node)
            list_type = analyzed_value_type(node.args[0])
            if self.is_jvm_array_type(list_type):
                if not self.expression(node.args[0]).startswith("["):
                    raise JVMUnsupported("JVM len has an incompatible array", node)
                self.code.emit(0xBE)
                self.code.emit(0x85)
                return "J"
            if list_type.generic_name == "dict":
                self.dictionary_types(list_type, node)
                if self.expression(node.args[0]) != "Ljava/util/HashMap;":
                    raise JVMUnsupported("JVM len has an incompatible dictionary", node)
                size = self.class_file.method_reference(
                    "java/util/HashMap",
                    "size",
                    "()I",
                )
                self.code.emit(0xB6, size.to_bytes(2, "big"))
                self.code.emit(0x85)
                return "J"
            if list_type.generic_name == "str":
                if self.expression(node.args[0]) != "Ljava/lang/String;":
                    raise JVMUnsupported("JVM len has an incompatible string", node)
                reference = self.class_file.method_reference(
                    self.main_class_name,
                    "pyjs_string_length",
                    "(Ljava/lang/String;)J",
                )
                self.string_helpers.add("length")
                self.code.emit(0xB8, reference.to_bytes(2, "big"))
                return "J"
            if list_type.generic_name != "list":
                raise JVMUnsupported(
                    "JVM len currently requires a string, list, dictionary, or array",
                    node,
                )
            if self.expression(node.args[0]) != self.value_type(list_type):
                raise JVMUnsupported("JVM len has an incompatible list", node)
            owner = self.list_class_name(list_type)
            length = self.class_file.field_reference(owner, "length", "I")
            self.code.emit(0xB4, length.to_bytes(2, "big"))
            self.code.emit(0x85)
            return "J"
        if isinstance(target, Function) and target.py_func is native_builtins._isinstance:
            if len(node.args) != 2 or node.keywords:
                raise JVMUnsupported(
                    "JVM isinstance takes two positional arguments",
                    node,
                )
            value_type = self.expression(node.args[0])
            if not _is_reference_descriptor(value_type) and value_type != "N":
                raise JVMUnsupported(
                    "JVM isinstance requires a reference value",
                    node.args[0],
                )
            checked = analyzed_value_object(node.args[1])
            if not isinstance(checked, Class):
                raise JVMUnsupported(
                    "JVM isinstance requires one concrete class",
                    node.args[1],
                )
            if exception_type(checked) is not None:
                owner = self.exception_match_class(checked, node)
            elif checked in self.classes:
                owner = self.class_name(checked)
            elif checked in self.native_classes:
                owner = self.native_class_name(checked)
            else:
                raise JVMUnsupported(
                    "JVM isinstance requires an emitted or native class",
                    node.args[1],
                )
            class_index = self.class_file.constants.class_(owner)
            self.code.emit(0xC1, class_index.to_bytes(2, "big"))
            return "Z"
        if isinstance(target, Function) and target.py_func in {
            native_builtins._min,
            native_builtins._max,
        }:
            if len(node.args) != 2 or node.keywords:
                raise JVMUnsupported(
                    "JVM min and max take two positional integer arguments",
                    node,
                )
            argument_types = [self.expression(argument) for argument in node.args]
            if argument_types != ["J", "J"]:
                raise JVMUnsupported(
                    "JVM min and max currently require integer arguments",
                    node,
                )
            name = "min" if target.py_func is native_builtins._min else "max"
            reference = self.class_file.method_reference(
                "java/lang/Math",
                name,
                "(JJ)J",
            )
            self.code.emit(0xB8, reference.to_bytes(2, "big"))
            return "J"
        if isinstance(node.func, ast.Attribute) and isinstance(target, Function):
            if target.is_classmethod:
                raise JVMUnsupported("JVM Python classmethod calls are not implemented", node)
            is_super = self.is_super_call(node.func.value)
            reflected_argument = None
            if target in self.functions and target.cls in self.classes and getattr(node, "reverse", False):
                actual = self.expression(node.args[0])
                reflected_argument = self.allocate_temporary(actual, "reflected.argument")
                self.store(reflected_argument, actual)
            receiver_type = self.expression(node.func.value)
            semantic_receiver = analyzed_value_type(node.func.value)
            if target.name == "__dynamic_bool__":
                raise JVMUnsupported("JVM optional truth tests require narrowing first", node)
            if (
                target.py_func is native_builtins._object.__init__
                and not node.args
                and not node.keywords
            ):
                self.code.emit(0x57)
                return "V"
            if target.name in {"__dynamic_eq__", "__dynamic_ne__"} or target.py_func in {
                native_builtins._object.__eq__, native_builtins._object.__ne__,
            }:
                if len(node.args) != 1 or node.keywords:
                    raise JVMUnsupported(
                        "JVM dynamic equality takes one positional argument",
                        node,
                    )
                self.validate_java_object_semantics(semantic_receiver, node)
                self.validate_java_object_semantics(
                    analyzed_value_type(node.args[0]), node,
                )
                argument_type = self.expression(node.args[0])
                if not (
                    receiver_type == "N" or _is_reference_descriptor(receiver_type)
                ) or not (
                    argument_type == "N" or _is_reference_descriptor(argument_type)
                ):
                    raise JVMUnsupported(
                        "JVM dynamic equality requires reference values",
                        node,
                    )
                reference = self.class_file.method_reference(
                    "java/util/Objects",
                    "equals",
                    "(Ljava/lang/Object;Ljava/lang/Object;)Z",
                )
                self.code.emit(0xB8, reference.to_bytes(2, "big"))
                if target.name in {"__dynamic_ne__", "__ne__"}:
                    self.code.emit(0x04)
                    self.code.emit(0x82)
                return "Z"
            if target.name in {"__is__", "__is_not__"} and len(node.args) == 1:
                argument_type = self.expression(node.args[0])
                if not (
                    receiver_type == "N"
                    or _is_reference_descriptor(receiver_type)
                ) or not (
                    argument_type == "N"
                    or _is_reference_descriptor(argument_type)
                ):
                    raise JVMUnsupported(
                        "JVM identity comparison requires reference values",
                        node,
                    )
                self.comparison(0xA5 if target.name == "__is__" else 0xA6)
                return "Z"
            if self.is_jvm_array_type(semantic_receiver):
                abi, semantic = self.jvm_array_item_types(
                    semantic_receiver,
                    node.func.value,
                )
                if target.name == "__getitem__" and len(node.args) == 1:
                    index = self.expression(node.args[0])
                    if index != "J":
                        raise JVMUnsupported("JVM array index must be an integer", node)
                    self.narrow_array_offset("java/lang/ArrayIndexOutOfBoundsException")
                    self.code.emit(self.array_load_opcode(abi))
                    self.convert_abi_result(abi, semantic, analyzed_numeric_format(node))
                    return semantic
                if target.name == "__setitem__" and len(node.args) == 2:
                    index = self.expression(node.args[0])
                    if index != "J":
                        raise JVMUnsupported("JVM array index must be an integer", node)
                    index_slot = self.allocate_temporary("J", "array.index")
                    self.store(index_slot, index)
                    actual = self.expression(node.args[1])
                    value_slot = self.allocate_temporary(actual, "array.value")
                    self.store(value_slot, actual)
                    self.load(index_slot)
                    self.narrow_array_offset("java/lang/ArrayIndexOutOfBoundsException")
                    self.load(value_slot)
                    self.convert_native_argument(actual, abi, node.args[1])
                    self.code.emit(self.array_store_opcode(abi))
                    return "V"
                raise JVMUnsupported(
                    f"unsupported JVM array operation {target.name}",
                    node,
                )
            if target in self.native_functions and target.cls in self.native_classes:
                owner = backend_metadata(
                    target.py_func,
                    "jvm",
                    "owner",
                    self.native_class_name(target.cls),
                )
                expected_receiver = f"L{owner};"
                if not (
                    owner == "java/lang/Object"
                    and _is_reference_descriptor(receiver_type)
                ) and not self.compatible(receiver_type, expected_receiver):
                    raise JVMUnsupported(
                        f"JVM native call to {target.name} has incompatible arguments",
                        node,
                    )
                if target.name == "__init__" and is_super:
                    # The generated JVM constructor has already initialized the
                    # native superclass before Python's pyjs_init method runs.
                    self.code.emit(0x57)
                    return "V"
                self.native_arguments(node, target)
                name = backend_metadata(
                    target.py_func,
                    "jvm",
                    "name",
                    target.name,
                )
                invocation = backend_metadata(
                    target.py_func,
                    "jvm",
                    "invocation",
                    "virtual",
                )
                interface = any(
                    self.native_class_name(value_type) == owner
                    for value_type in self.native_interfaces
                )
                if invocation != "virtual":
                    raise JVMUnsupported(
                        f"JVM native member invocation {invocation} is invalid",
                        node,
                    )
                descriptor = self.native_descriptor(target)
                if interface:
                    reference = self.class_file.interface_method_reference(
                        owner,
                        name,
                        descriptor,
                    )
                    argument_slots = 1 + sum(
                        2 if value_type in {"J", "D"} else 1
                        for value_type in self.native_parameter_types(target)
                    )
                    self.code.emit(
                        0xB9,
                        reference.to_bytes(2, "big")
                        + argument_slots.to_bytes(1, "big")
                        + b"\x00",
                    )
                else:
                    reference = self.class_file.method_reference(
                        owner,
                        name,
                        descriptor,
                    )
                    self.code.emit(
                        0xB7 if is_super else 0xB6,
                        reference.to_bytes(2, "big"),
                    )
                return self.convert_native_result(target)
            if target in self.functions and target.cls in self.classes:
                arguments = self.application_arguments(node, target)
                expected_receiver = self.class_descriptor(target.cls)
                if not self.compatible(receiver_type, expected_receiver) or len(
                    arguments
                ) != len(target.params):
                    raise JVMUnsupported(
                        f"JVM call to {target.name} has incompatible arguments",
                        node,
                    )
                for argument, parameter in zip(
                    arguments,
                    target.params,
                    strict=True,
                ):
                    actual = self.load(reflected_argument) if reflected_argument is not None else self.expression(argument)
                    semantic = self.parameter_type(parameter)
                    if not self.compatible(actual, semantic):
                        raise JVMUnsupported(
                            f"JVM call to {target.name} has incompatible arguments",
                            node,
                        )
                    storage = (
                        _numeric_descriptor(analyzed_numeric_format(parameter)) or semantic
                    )
                    self.convert_native_argument(actual, storage, argument)
                reference = self.class_file.method_reference(
                    self.class_name(target.cls),
                    self.function_name(target),
                    self.descriptor(target),
                )
                self.code.emit(
                    0xB7 if is_super else 0xB6,
                    reference.to_bytes(2, "big"),
                )
                semantic = self.function_return_type(target)
                storage = _numeric_descriptor(target.return_numeric_format) or semantic
                self.convert_abi_result(
                    storage,
                    semantic,
                    target.return_numeric_format,
                )
                return semantic
            if semantic_receiver.generic_name == "dict":
                return self.dictionary_call(
                    node,
                    target,
                    semantic_receiver,
                    receiver_type,
                )
            argument_types = [self.expression(argument) for argument in node.args]
            if (
                isinstance(semantic_receiver, Class)
                and semantic_receiver.generic_name == "str"
            ):
                if target.name in {"__add__", "__radd__"} and argument_types == [
                    "Ljava/lang/String;"
                ]:
                    if target.name == "__radd__":
                        self.code.emit(0x5F)
                    reference = self.class_file.method_reference(
                        "java/lang/String",
                        "concat",
                        "(Ljava/lang/String;)Ljava/lang/String;",
                    )
                    self.code.emit(0xB6, reference.to_bytes(2, "big"))
                    return "Ljava/lang/String;"
                if target.name in {"__mul__", "__rmul__"} and argument_types == ["J"]:
                    reference = self.class_file.method_reference(
                        self.main_class_name,
                        "pyjs_string_repeat",
                        "(Ljava/lang/String;J)Ljava/lang/String;",
                    )
                    self.string_helpers.add("repeat")
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                    return "Ljava/lang/String;"
                if target.name in {"__eq__", "__ne__"} and argument_types == [
                    "Ljava/lang/String;"
                ]:
                    reference = self.class_file.method_reference(
                        "java/lang/String",
                        "equals",
                        "(Ljava/lang/Object;)Z",
                    )
                    self.code.emit(0xB6, reference.to_bytes(2, "big"))
                    if target.name == "__ne__":
                        self.code.emit(0x04)
                        self.code.emit(0x82)
                    return "Z"
                if target.name == "__bool__" and not argument_types:
                    reference = self.class_file.method_reference(
                        "java/lang/String",
                        "isEmpty",
                        "()Z",
                    )
                    self.code.emit(0xB6, reference.to_bytes(2, "big"))
                    self.code.emit(0x04)
                    self.code.emit(0x82)
                    return "Z"
                if target.name == "__str__" and not argument_types:
                    return "Ljava/lang/String;"
                if target.name in {"lower", "upper"} and not argument_types:
                    locale = self.class_file.field_reference(
                        "java/util/Locale", "ROOT", "Ljava/util/Locale;"
                    )
                    self.code.emit(0xB2, locale.to_bytes(2, "big"))
                    reference = self.class_file.method_reference(
                        "java/lang/String",
                        "toLowerCase" if target.name == "lower" else "toUpperCase",
                        "(Ljava/util/Locale;)Ljava/lang/String;",
                    )
                    self.code.emit(0xB6, reference.to_bytes(2, "big"))
                    return "Ljava/lang/String;"
                if target.name == "__getitem__" and argument_types == ["J"]:
                    reference = self.class_file.method_reference(
                        self.main_class_name,
                        "pyjs_string_getitem",
                        "(Ljava/lang/String;J)Ljava/lang/String;",
                    )
                    self.string_helpers.add("getitem")
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                    return "Ljava/lang/String;"
                if (
                    target.name in {"__contains__", "startswith", "endswith"}
                    and argument_types == ["Ljava/lang/String;"]
                ):
                    helper = "contains" if target.name == "__contains__" else target.name
                    self.string_helpers.add(helper)
                    reference = self.class_file.method_reference(
                        self.main_class_name,
                        f"pyjs_string_{helper}",
                        "(Ljava/lang/String;Ljava/lang/String;)Z",
                    )
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                    return "Z"
                if target.name in {"strip", "rstrip"} and not argument_types:
                    self.string_helpers.add("strip")
                    self.code.emit(0x04 if target.name == "strip" else 0x03)
                    reference = self.class_file.method_reference(
                        self.main_class_name,
                        "pyjs_string_strip",
                        "(Ljava/lang/String;Z)Ljava/lang/String;",
                    )
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                    return "Ljava/lang/String;"
                if target.name == "join" and len(node.args) == 1:
                    values = analyzed_value_type(node.args[0])
                    if (
                        values.generic_name != "list"
                        or self.list_item_type(values) != "Ljava/lang/String;"
                    ):
                        raise JVMUnsupported(
                            "JVM str.join currently requires a list of strings",
                            node,
                        )
                    owner = self.list_class_name(values)
                    if argument_types != [f"L{owner};"]:
                        raise JVMUnsupported(
                            "JVM str.join has an incompatible list",
                            node,
                        )
                    self.code.emit(0x5F)
                    reference = self.class_file.method_reference(
                        owner,
                        "join",
                        "(Ljava/lang/String;)Ljava/lang/String;",
                    )
                    self.code.emit(0xB6, reference.to_bytes(2, "big"))
                    return "Ljava/lang/String;"
            if (
                target.name == "insert"
                and semantic_receiver.generic_name == "list"
                and len(argument_types) == 2
                and argument_types[0] == "J"
            ):
                item_type = self.list_item_type(semantic_receiver)
                if not self.compatible(argument_types[1], item_type):
                    raise JVMUnsupported("JVM list insertion has an incompatible value", node)
                reference = self.class_file.method_reference(
                    self.list_class_name(semantic_receiver), "insert", f"(J{item_type})V"
                )
                self.code.emit(0xB6, reference.to_bytes(2, "big"))
                return "V"
            if (
                target.name == "__getitem__"
                and analyzed_value_type(node.func.value).generic_name == "list"
                and argument_types == ["J"]
            ):
                list_type = analyzed_value_type(node.func.value)
                item_type = self.list_item_type(list_type)
                reference = self.class_file.method_reference(
                    self.list_class_name(list_type),
                    "get",
                    f"(J){item_type}",
                )
                self.code.emit(0xB6, reference.to_bytes(2, "big"))
                return item_type
            if (
                target.name == "__setitem__"
                and analyzed_value_type(node.func.value).generic_name == "list"
                and len(argument_types) == 2
                and argument_types[0] == "J"
            ):
                list_type = analyzed_value_type(node.func.value)
                item_type = self.list_item_type(list_type)
                if not self.compatible(argument_types[1], item_type):
                    raise JVMUnsupported(
                        "JVM list assignment has an incompatible value",
                        node,
                    )
                reference = self.class_file.method_reference(
                    self.list_class_name(list_type),
                    "set",
                    f"(J{item_type})V",
                )
                self.code.emit(0xB6, reference.to_bytes(2, "big"))
                return "V"
            if not argument_types and receiver_type == "J":
                if target.name in {"__pos__", "__neg__", "__invert__"}:
                    if target.name == "__neg__":
                        self.code.emit(0x75)
                    elif target.name == "__invert__":
                        self.long_constant(-1)
                        self.code.emit(0x83)
                    self.normalize_integer_result(node)
                    return "J"
            if receiver_type == "D" and argument_types in (["J"], ["Z"]):
                self.code.emit(0x8A if argument_types == ["J"] else 0x87)
                argument_types = ["D"]
            if len(argument_types) == 1 and receiver_type == argument_types[0] == "J":
                if target.name in {
                    "__truediv__",
                    "__rtruediv__",
                    "__floordiv__",
                    "__rfloordiv__",
                    "__mod__",
                    "__rmod__",
                }:
                    if target.name.startswith("__r"):
                        self.code.emit(0x5E)
                        self.code.emit(0x58)
                    storage_format = analyzed_numeric_format(node)
                    if storage_format is not None and storage_format.domain == "wgsl":
                        self.wgsl_integer_division(
                            modulo=target.name.endswith("mod__"),
                            signed=storage_format.signed,
                        )
                        self.normalize_integer_result(node)
                        return "J"
                    if "truediv" in target.name:
                        self.integer_true_division()
                        return "D"
                    method = "floorMod" if target.name.endswith("mod__") else "floorDiv"
                    reference = self.class_file.method_reference(
                        "java/lang/Math",
                        method,
                        "(JJ)J",
                    )
                    if method == "floorDiv" and storage_format is None:
                        self.checked_integer_division()
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                    if storage_format is not None:
                        self.normalize_integer_result(node)
                    return "J"
                if target.name in self.INTEGER_OPCODES:
                    self.code.emit(self.INTEGER_OPCODES[target.name])
                    self.normalize_integer_result(node)
                    return "J"
                if target.name == "__rsub__":
                    self.code.emit(0x5E)
                    self.code.emit(0x58)
                    self.code.emit(0x65)
                    self.normalize_integer_result(node)
                    return "J"
                if target.name in {"__lshift__", "__rshift__"}:
                    storage_format = analyzed_numeric_format(node)
                    receiver_format = analyzed_numeric_format(node.func.value)
                    self.integer_shift(
                        left=target.name == "__lshift__",
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
                    self.normalize_integer_result(node)
                    return "J"
                if target.name in {"__pow__", "__rpow__"}:
                    if target.name == "__rpow__":
                        self.code.emit(0x5E)
                        self.code.emit(0x58)
                    self.integer_power()
                    self.normalize_integer_result(node)
                    return "J"
                if target.name in self.INTEGER_COMPARISONS:
                    self.code.emit(0x94)
                    self.comparison(self.INTEGER_COMPARISONS[target.name])
                    return "Z"
            if len(argument_types) == 1 and receiver_type == argument_types[0] == "D":
                if target.name in {
                    "__add__",
                    "__radd__",
                    "__sub__",
                    "__rsub__",
                    "__mul__",
                    "__rmul__",
                    "__truediv__",
                    "__rtruediv__",
                }:
                    reverse = target.name.startswith("__r")
                    operation = target.name[3:] if reverse else target.name[2:]
                    if reverse and operation in {"sub__", "truediv__"}:
                        self.code.emit(0x5E)
                        self.code.emit(0x58)
                    if operation == "truediv__":
                        storage_format = analyzed_numeric_format(node)
                        if storage_format is not None and storage_format.domain == "wgsl":
                            self.code.emit(0x6F)
                        else:
                            self.checked_double_division()
                    else:
                        self.code.emit(
                            {
                                "add__": 0x63,
                                "sub__": 0x67,
                                "mul__": 0x6B,
                            }[operation]
                        )
                    self.normalize_float_result(node)
                    return "D"
                if target.name in self.INTEGER_COMPARISONS:
                    self.double_comparison(target.name)
                    return "Z"
            if target.name == "__bool__" and not argument_types and receiver_type == "Z":
                return "Z"
            if target.name == "__bool__" and not argument_types and receiver_type == "J":
                self.long_constant(0)
                self.code.emit(0x94)  # lcmp
                self.comparison(0x9A)
                return "Z"
            if (
                target.name in {"__eq__", "__ne__"}
                and argument_types == ["Z"]
                and receiver_type == "Z"
            ):
                self.code.emit(0x82)
                self.comparison(0x99 if target.name == "__eq__" else 0x9A)
                return "Z"
            if target.name == "__bool__" and not argument_types and receiver_type == "D":
                self.code.emit(0x0E)
                self.code.emit(0x97)
                self.comparison(0x9A)
                return "Z"
            if target.name == "__str__" and not argument_types:
                if receiver_type == "Ljava/lang/Throwable;":
                    self.exception_message()
                    return "Ljava/lang/String;"
                elif receiver_type == "J":
                    owner, descriptor = "java/lang/Long", "(J)Ljava/lang/String;"
                elif receiver_type == "Z":
                    self.bool_string()
                    return "Ljava/lang/String;"
                else:
                    raise JVMUnsupported(
                        f"unsupported JVM scalar operation {target.name}",
                        node,
                    )
                reference = self.class_file.method_reference(
                    owner,
                    "toString",
                    descriptor,
                )
                self.code.emit(0xB8, reference.to_bytes(2, "big"))
                return "Ljava/lang/String;"
            raise JVMUnsupported(f"unsupported JVM scalar operation {target.name}", node)
        if isinstance(target, Function):
            if target in self.native_functions:
                self.native_arguments(node, target)
                owner = backend_metadata(target.py_func, "jvm", "owner")
                name = backend_metadata(target.py_func, "jvm", "name", target.name)
                invocation = backend_metadata(
                    target.py_func,
                    "jvm",
                    "invocation",
                )
                if invocation != "static":
                    raise JVMUnsupported(
                        f"JVM native invocation {invocation} is not implemented",
                        node,
                    )
                reference = self.class_file.method_reference(
                    owner,
                    name,
                    self.native_descriptor(target),
                )
                self.code.emit(0xB8, reference.to_bytes(2, "big"))
                return self.convert_native_result(target)
            if target not in self.functions:
                raise JVMUnsupported(
                    f"JVM call target {target.name} has no emitted definition",
                    node,
                )
            arguments = self.application_arguments(node, target)
            if len(arguments) != len(target.params):
                raise JVMUnsupported(
                    f"JVM call to {target.name} has incompatible arguments",
                    node,
                )
            for argument, parameter in zip(
                arguments,
                target.params,
                strict=True,
            ):
                actual = self.expression(argument)
                semantic = self.parameter_type(parameter)
                if not self.compatible(actual, semantic):
                    raise JVMUnsupported(
                        f"JVM call to {target.name} has incompatible arguments",
                        node,
                    )
                storage = (
                    _numeric_descriptor(analyzed_numeric_format(parameter)) or semantic
                )
                self.convert_native_argument(actual, storage, argument)
            reference = self.class_file.method_reference(
                self.function_owner(target),
                self.function_name(target),
                self.descriptor(target),
            )
            self.code.emit(0xB8, reference.to_bytes(2, "big"))
            semantic = self.function_return_type(target)
            storage = _numeric_descriptor(target.return_numeric_format) or semantic
            self.convert_abi_result(
                storage,
                semantic,
                target.return_numeric_format,
            )
            return semantic
        if isinstance(node.func, ast.Name) and node.func.id == "str":
            if len(node.args) != 1 or node.keywords:
                raise JVMUnsupported("JVM str() takes one argument", node)
            value_type = self.expression(node.args[0])
            if value_type == "Ljava/lang/String;":
                return value_type
            if value_type == "Ljava/lang/Throwable;":
                self.exception_message()
                return "Ljava/lang/String;"
            if value_type == "J":
                owner, descriptor = "java/lang/Long", "(J)Ljava/lang/String;"
            else:
                owner, descriptor = "java/lang/Boolean", "(Z)Ljava/lang/String;"
            if value_type not in {"J", "Z"}:
                raise JVMUnsupported("JVM str() conversion is not implemented", node)
            if value_type == "Z":
                self.bool_string()
                return "Ljava/lang/String;"
            reference = self.class_file.method_reference(owner, "toString", descriptor)
            self.code.emit(0xB8, reference.to_bytes(2, "big"))
            return "Ljava/lang/String;"
        if self.is_super_call(node):
            if node.args or node.keywords:
                raise JVMUnsupported("JVM supports only zero-argument super()", node)
            self.load("self")
            return self.slot_types["self"]
        if isinstance(target, (Class, GenericClass)):
            # Unsupported builtin constructors are class-valued names. Asking
            # for their runtime type would create a late type[T] dependency.
            raise JVMUnsupported(f"JVM constructor {target.name} is not implemented", node)
        target_type = analyzed_value_type(node.func)
        if target_type.generic_name in {"callable", "Callable"}:
            if node.args or node.keywords:
                raise JVMUnsupported(
                    "JVM callbacks currently take no arguments",
                    node,
                )
            receiver = self.expression(node.func)
            if receiver != "Ljava/lang/Runnable;":
                raise JVMUnsupported(
                    "JVM callback has an incompatible runtime type",
                    node,
                )
            reference = self.class_file.interface_method_reference(
                "java/lang/Runnable",
                "run",
                "()V",
            )
            self.code.emit(
                0xB9,
                reference.to_bytes(2, "big") + b"\x01\x00",
            )
            return "V"
        raise JVMUnsupported("JVM indirect calls are not implemented", node)

    def immediate_async_call(self, value: ast.expr, source: ast.AST) -> str:
        if not isinstance(value, ast.Call):
            raise JVMUnsupported(
                "JVM await requires a direct async function or method call",
                source,
            )
        target = analyzed_value_object(value.func)
        if not isinstance(target, Function) or not target.is_async:
            raise JVMUnsupported(
                "JVM await requires a direct async function or method call",
                source,
            )
        if target in self.native_functions:
            raise JVMUnsupported(
                "JVM native async functions are not implemented",
                source,
            )
        self.async_call_depth += 1
        try:
            return self.expression(value)
        finally:
            self.async_call_depth -= 1

    def collection_new(self, node: CollectionNew) -> str:
        if node.value_type.generic_name == "dict" and isinstance(
            node.source,
            ast.Dict,
        ):
            return self.dictionary_new(node)
        if node.value_type.generic_name == "tuple" and isinstance(
            node.source,
            ast.Tuple,
        ):
            return self.tuple_new(node)
        if node.value_type.generic_name != "list" or not isinstance(
            node.source, ast.List
        ):
            raise JVMUnsupported(
                f"JVM {node.value_type.generic_name} allocation is not implemented",
                node,
            )
        owner = self.list_class_name(node.value_type)
        descriptor = f"L{owner};"
        class_index = self.class_file.constants.class_(owner)
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        constructor = self.class_file.method_reference(owner, "<init>", "()V")
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        item_type = self.list_item_type(node.value_type)
        append = self.class_file.method_reference(
            owner,
            "append",
            f"({item_type})V",
        )
        for element in node.source.elts:
            self.code.emit(0x59)
            actual = self.expression(element)
            if not self.compatible(actual, item_type):
                raise JVMUnsupported("JVM list literal changes item type", element)
            self.convert_native_argument(actual, item_type, element)
            self.code.emit(0xB6, append.to_bytes(2, "big"))
        return descriptor

    def dictionary_new(self, node: CollectionNew) -> str:
        key_type, value_type = self.dictionary_types(node.value_type, node)
        owner = "java/util/HashMap"
        class_index = self.class_file.constants.class_(owner)
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        constructor = self.class_file.method_reference(owner, "<init>", "()V")
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        put = self.class_file.method_reference(
            owner,
            "put",
            "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;",
        )
        for key, value in zip(
            node.source.keys,
            node.source.values,
            strict=True,
        ):
            if key is None:
                raise JVMUnsupported("JVM dictionary unpacking is not implemented", node)
            self.code.emit(0x59)
            actual_key = self.expression(key)
            if not self.compatible(actual_key, key_type):
                raise JVMUnsupported("JVM dictionary literal changes key type", key)
            self.convert_native_argument(actual_key, key_type, key)
            actual_value = self.expression(value)
            if not self.compatible(actual_value, value_type):
                raise JVMUnsupported("JVM dictionary literal changes value type", value)
            self.convert_native_argument(actual_value, value_type, value)
            self.code.emit(0xB6, put.to_bytes(2, "big"))
            self.code.emit(0x57)
        return "Ljava/util/HashMap;"

    def dictionary_call(
        self,
        node: ast.Call,
        target: Function,
        value_type: Class,
        receiver_type: str,
    ) -> str:
        if receiver_type != "Ljava/util/HashMap;":
            raise JVMUnsupported("JVM dictionary has an incompatible receiver", node)
        key_type, value_descriptor = self.dictionary_types(value_type, node)
        if target.name == "__len__" and not node.args:
            reference = self.class_file.method_reference(
                "java/util/HashMap",
                "size",
                "()I",
            )
            self.code.emit(0xB6, reference.to_bytes(2, "big"))
            self.code.emit(0x85)
            return "J"
        if target.name == "__setitem__" and len(node.args) == 2:
            if self.expression(node.args[0]) != key_type:
                raise JVMUnsupported("JVM dictionary key has an incompatible type", node)
            if self.expression(node.args[1]) != value_descriptor:
                raise JVMUnsupported(
                    "JVM dictionary value has an incompatible type", node
                )
            reference = self.class_file.method_reference(
                "java/util/HashMap",
                "put",
                "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;",
            )
            self.code.emit(0xB6, reference.to_bytes(2, "big"))
            self.code.emit(0x57)
            return "V"
        if target.name == "__getitem__" and len(node.args) == 1:
            if self.expression(node.args[0]) != key_type:
                raise JVMUnsupported("JVM dictionary key has an incompatible type", node)
            self.code.emit(0x5C)
            contains = self.class_file.method_reference(
                "java/util/HashMap",
                "containsKey",
                "(Ljava/lang/Object;)Z",
            )
            self.code.emit(0xB6, contains.to_bytes(2, "big"))
            present = self.new_label("dict.item.present")
            self.code.branch(0x9A, present)
            self.code.emit(0x58)
            self.throw("java/util/NoSuchElementException")
            self.code.mark(present)
            get = self.class_file.method_reference(
                "java/util/HashMap",
                "get",
                "(Ljava/lang/Object;)Ljava/lang/Object;",
            )
            self.code.emit(0xB6, get.to_bytes(2, "big"))
            self.checkcast(value_descriptor)
            return value_descriptor
        if target.name == "get" and len(node.args) in {1, 2}:
            if self.expression(node.args[0]) != key_type:
                raise JVMUnsupported("JVM dictionary key has an incompatible type", node)
            get = self.class_file.method_reference(
                "java/util/HashMap",
                "get",
                "(Ljava/lang/Object;)Ljava/lang/Object;",
            )
            if len(node.args) == 1:
                self.code.emit(0xB6, get.to_bytes(2, "big"))
                self.checkcast(value_descriptor)
                return value_descriptor
            default_type = self.expression(node.args[1])
            if default_type != "N" and not self.compatible(
                default_type,
                value_descriptor,
            ):
                raise JVMUnsupported(
                    "JVM dictionary default has an incompatible type",
                    node.args[1],
                )
            temporary = self.allocate_temporary(value_descriptor, "dict.default")
            self.store(temporary, default_type)
            self.code.emit(0x5C)
            contains = self.class_file.method_reference(
                "java/util/HashMap",
                "containsKey",
                "(Ljava/lang/Object;)Z",
            )
            self.code.emit(0xB6, contains.to_bytes(2, "big"))
            missing = self.new_label("dict.get.missing")
            done = self.new_label("dict.get.done")
            self.code.branch(0x99, missing)
            self.code.emit(0xB6, get.to_bytes(2, "big"))
            self.checkcast(value_descriptor)
            self.code.branch(0xA7, done)
            self.code.mark(missing)
            self.code.emit(0x58)
            self.load(temporary)
            self.code.mark(done)
            return value_descriptor
        raise JVMUnsupported(
            f"unsupported JVM dictionary operation {target.name}",
            node,
        )

    def tuple_new(self, node: CollectionNew) -> str:
        class_file = self.tuple_class(node.value_type)
        descriptor = f"L{class_file.name};"
        class_index = self.class_file.constants.class_(class_file.name)
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        constructor = self.class_file.method_reference(
            class_file.name,
            "<init>",
            "()V",
        )
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        field_types = tuple(node.value_type.generic_types.values())
        if len(field_types) != len(node.source.elts):
            raise JVMUnsupported("JVM tuple literal changes arity", node)
        for index, (element, field_type) in enumerate(
            zip(node.source.elts, field_types, strict=True)
        ):
            self.code.emit(0x59)
            descriptor = self.value_type(field_type)
            if self.expression(element) != descriptor:
                raise JVMUnsupported("JVM tuple literal changes item type", element)
            reference = self.class_file.field_reference(
                class_file.name,
                f"_{index}",
                descriptor,
            )
            self.code.emit(0xB5, reference.to_bytes(2, "big"))
        return f"L{class_file.name};"

    def list_append(self, node: ListAppend) -> None:
        list_type = analyzed_value_type(node.call.func.value)
        owner = self.list_class_name(list_type)
        descriptor = f"L{owner};"
        if self.expression(node.call.func.value) != descriptor:
            raise JVMUnsupported("JVM list append has incompatible receiver", node)
        item_type = self.list_item_type(list_type)
        if self.expression(node.call.args[0]) != item_type:
            raise JVMUnsupported("JVM list append has incompatible value", node)
        reference = self.class_file.method_reference(
            owner,
            "append",
            f"({item_type})V",
        )
        self.code.emit(0xB6, reference.to_bytes(2, "big"))

    def iterator_descriptor(self, node: IteratorCreate):
        if (
            isinstance(node.iterable, ast.Call)
            and isinstance(node.iterable.func, ast.Name)
            and node.iterable.func.id == "range"
        ):
            return (
                "range",
                "J",
                "",
                JVM_ENVIRONMENT.builtins.search("int"),
            )
        list_type = analyzed_value_type(node.iterable)
        if list_type.generic_name != "list":
            raise JVMUnsupported(
                f"JVM cannot iterate over {list_type.name}",
                node,
            )
        item_value_type = next(iter(list_type.generic_types.values()))
        return (
            "list",
            self.list_item_type(list_type),
            f"L{self.list_class_name(list_type)};",
            item_value_type,
        )

    def add_iterator_target(self, add, target, item_value_type) -> None:
        if isinstance(target, (ast.Name, ast.arg)):
            add(self.target_name(target), self.value_type(item_value_type))
            return
        if not isinstance(target, (ast.List, ast.Tuple)):
            raise JVMUnsupported("unsupported JVM iterator target", target)
        if item_value_type.generic_name != "tuple":
            raise JVMUnsupported("JVM can only unpack tuple items", target)
        item_types = tuple(item_value_type.generic_types.values())
        if len(item_types) != len(target.elts):
            raise JVMUnsupported("JVM tuple unpacking length differs", target)
        for element, element_type in zip(target.elts, item_types, strict=True):
            self.add_iterator_target(add, element, element_type)

    def iterator_create(self, node: IteratorCreate) -> None:
        kind, _item_type, source_type, _semantic_item = self.iterators[node.name]
        if kind == "range":
            arguments = [
                self.expression_type(argument) for argument in node.iterable.args
            ]
            if any(value_type != "J" for value_type in arguments):
                raise JVMUnsupported("JVM range arguments must be int", node)
            if len(arguments) == 1:
                self.long_constant(0)
                self.expression(node.iterable.args[0])
                self.long_constant(1)
            elif len(arguments) == 2:
                self.expression(node.iterable.args[0])
                self.expression(node.iterable.args[1])
                self.long_constant(1)
            elif len(arguments) == 3:
                for argument in node.iterable.args:
                    self.expression(argument)
            else:
                raise JVMUnsupported("JVM range takes one to three arguments", node)
            for part in reversed(("current", "stop", "step")):
                self.store(f"{node.name}.{part}", "J")
            valid = self.new_label("range.valid.step")
            self.load(f"{node.name}.step")
            self.long_constant(0)
            self.code.emit(0x94)
            self.code.branch(0x9A, valid)
            self.throw("java/lang/IllegalArgumentException")
            self.code.mark(valid)
            return
        if self.expression(node.iterable) != source_type:
            raise JVMUnsupported("JVM list iterator has incompatible source", node)
        self.store(f"{node.name}.source", source_type)
        self.long_constant(0)
        self.store(f"{node.name}.index", "J")

    def iterator_next(self, node: IteratorNext) -> None:
        kind, item_type, source_type, semantic_item = self.iterators[node.iterator]
        if kind == "range":
            self.range_iterator_next(node)
        else:
            self.list_iterator_next(node, item_type, source_type, semantic_item)

    def range_iterator_next(self, node: IteratorNext) -> None:
        current = f"{node.iterator}.current"
        stop = f"{node.iterator}.stop"
        step = f"{node.iterator}.step"
        positive = self.new_label("range.positive")
        available = self.new_label("range.available")
        self.load(step)
        self.long_constant(0)
        self.code.emit(0x94)
        self.code.branch(0x9D, positive)
        self.load(current)
        self.load(stop)
        self.code.emit(0x94)
        self.code.branch(0x9D, available)
        self.code.branch(0xA7, self.block_label(node.exhausted))
        self.code.mark(positive)
        self.load(current)
        self.load(stop)
        self.code.emit(0x94)
        self.code.branch(0x9B, available)
        self.code.branch(0xA7, self.block_label(node.exhausted))
        self.code.mark(available)
        self.load(current)
        self.store(self.target_name(node.target), "J")

        positive_advance = self.new_label("range.advance.positive")
        safe_advance = self.new_label("range.advance.safe")
        advanced = self.new_label("range.advanced")
        self.load(step)
        self.long_constant(0)
        self.code.emit(0x94)
        self.code.branch(0x9D, positive_advance)
        self.load(current)
        self.long_constant(-(2**63))
        self.load(step)
        self.code.emit(0x65)
        self.code.emit(0x94)
        self.code.branch(0x9C, safe_advance)
        self.load(stop)
        self.store(current, "J")
        self.code.branch(0xA7, advanced)
        self.code.mark(positive_advance)
        self.load(current)
        self.long_constant(2**63 - 1)
        self.load(step)
        self.code.emit(0x65)
        self.code.emit(0x94)
        self.code.branch(0x9E, safe_advance)
        self.load(stop)
        self.store(current, "J")
        self.code.branch(0xA7, advanced)
        self.code.mark(safe_advance)
        self.load(current)
        self.load(step)
        self.code.emit(0x61)
        self.store(current, "J")
        self.code.mark(advanced)
        self.code.branch(0xA7, self.block_label(node.body))

    def list_iterator_next(
        self,
        node: IteratorNext,
        item_type: str,
        source_type: str,
        semantic_item,
    ) -> None:
        source = f"{node.iterator}.source"
        index = f"{node.iterator}.index"
        self.load(index)
        self.load(source)
        owner = source_type[1:-1]
        length = self.class_file.field_reference(owner, "length", "I")
        self.code.emit(0xB4, length.to_bytes(2, "big"))
        self.code.emit(0x85)
        self.code.emit(0x94)
        item = self.new_label("list.item")
        self.code.branch(0x9B, item)
        self.code.branch(0xA7, self.block_label(node.exhausted))
        self.code.mark(item)
        self.load(source)
        self.load(index)
        get = self.class_file.method_reference(owner, "get", f"(J){item_type}")
        self.code.emit(0xB6, get.to_bytes(2, "big"))
        self.assign_iterator_target(node, item_type, semantic_item)
        self.load(index)
        self.long_constant(1)
        self.code.emit(0x61)
        self.store(index, "J")
        self.code.branch(0xA7, self.block_label(node.body))

    def assign_iterator_target(
        self,
        node: IteratorNext,
        item_type: str,
        semantic_item,
    ) -> None:
        if isinstance(node.target, (ast.Name, ast.arg)):
            self.store(self.target_name(node.target), item_type)
            return
        scratch = f"{node.iterator}.item"
        self.store(scratch, item_type)
        owner = self.tuple_class_name(semantic_item)
        for index, (target, field_type) in enumerate(
            zip(
                node.target.elts,
                semantic_item.generic_types.values(),
                strict=True,
            )
        ):
            self.load(scratch)
            descriptor = self.value_type(field_type)
            reference = self.class_file.field_reference(
                owner,
                f"_{index}",
                descriptor,
            )
            self.code.emit(0xB4, reference.to_bytes(2, "big"))
            self.store(self.target_name(target), descriptor)

    def object_new(self, node: ObjectNew) -> str:
        value_type = node.value_type
        if self.is_jvm_array_type(value_type):
            if len(node.call.args) != 1 or node.call.keywords:
                raise JVMUnsupported(
                    "JVMArray construction requires one positional length",
                    node,
                )
            length_type = self.expression(node.call.args[0])
            if length_type != "J":
                raise JVMUnsupported("JVMArray length must be an integer", node)
            self.narrow_array_offset("java/lang/NegativeArraySizeException")
            abi, _semantic = self.jvm_array_item_types(value_type, node)
            self.new_array(self.code, self.class_file, abi)
            return f"[{abi}"
        if value_type in self.native_classes:
            return self.native_object_new(node)
        if value_type not in self.classes:
            raise JVMUnsupported(
                f"JVM cannot construct external class {value_type.name}",
                node,
            )
        owner = self.class_name(value_type)
        initializer = self.classes[value_type].constructor
        evaluation, ordered = self.constructor_arguments(node)
        slots = self.object_argument_slots[node]
        for name, argument in evaluation:
            argument_type = self.expression(argument)
            self.store(slots[name], argument_type)
        class_index = self.class_file.constants.class_(owner)
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        native_subclass = (
            self.has_native_superclass(value_type) and initializer in self.functions
        )
        constructor_descriptor = (
            self.descriptor(initializer) if native_subclass else "()V"
        )
        if native_subclass:
            for name, parameter in zip(
                ordered,
                initializer.params,
                strict=True,
            ):
                actual = self.load(slots[name])
                storage = _numeric_descriptor(
                    analyzed_numeric_format(parameter)
                ) or self.parameter_type(parameter)
                self.convert_native_argument(actual, storage, node)
        constructor = self.class_file.method_reference(
            owner,
            "<init>",
            constructor_descriptor,
        )
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        if initializer in self.functions:
            self.code.emit(0x59)
            argument_types = []
            for name, parameter in zip(
                ordered,
                initializer.params,
                strict=True,
            ):
                actual = self.load(slots[name])
                argument_types.append(actual)
                storage = _numeric_descriptor(
                    analyzed_numeric_format(parameter)
                ) or self.parameter_type(parameter)
                self.convert_native_argument(actual, storage, node)
            expected = [
                self.parameter_type(parameter) for parameter in initializer.params
            ]
            if len(argument_types) != len(expected) or not all(
                self.compatible(actual, wanted)
                for actual, wanted in zip(argument_types, expected, strict=True)
            ):
                raise JVMUnsupported(
                    f"JVM constructor for {value_type.name} has incompatible arguments",
                    node,
                )
            reference = self.class_file.method_reference(
                owner,
                self.function_name(initializer),
                self.descriptor(initializer),
            )
            self.code.emit(0xB6, reference.to_bytes(2, "big"))
        elif evaluation:
            raise JVMUnsupported(
                f"JVM class {value_type.name} has no emitted constructor",
                node,
            )
        return self.class_descriptor(value_type)

    def native_object_new(self, node: ObjectNew) -> str:
        if node.value_type in self.native_interfaces:
            raise JVMUnsupported(
                f"JVM interface {node.value_type.name} cannot be constructed",
                node,
            )
        owner = self.native_class_name(node.value_type)
        initializer = self.native_layouts[node.value_type].constructor
        evaluation, ordered = self.constructor_arguments(node)
        slots = self.object_argument_slots[node]
        for name, argument in evaluation:
            argument_type = self.expression(argument)
            self.store(slots[name], argument_type)
        class_index = self.class_file.constants.class_(owner)
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        expected = (
            self.native_parameter_types(initializer)
            if initializer in self.native_functions
            else []
        )
        for name, wanted in zip(ordered, expected, strict=True):
            actual = self.load(slots[name])
            self.convert_native_argument(actual, wanted, node)
        descriptor = (
            self.native_descriptor(initializer)
            if initializer in self.native_functions
            else "()V"
        )
        reference = self.class_file.method_reference(owner, "<init>", descriptor)
        self.code.emit(0xB7, reference.to_bytes(2, "big"))
        return f"L{owner};"

    def constructor_arguments(self, node: ObjectNew):
        layout = self.classes.get(node.value_type) or self.native_layouts.get(
            node.value_type
        )
        initializer = layout.constructor if layout is not None else None
        if initializer not in self.functions and initializer not in self.native_functions:
            if node.call.args or node.call.keywords:
                raise JVMUnsupported(
                    f"JVM class {node.value_type.name} has no emitted constructor",
                    node,
                )
            return [], []
        parameters = [parameter.arg for parameter in initializer.params]
        if len(node.call.args) > len(parameters):
            raise JVMUnsupported(
                f"JVM constructor for {node.value_type.name} has too many arguments",
                node,
            )
        evaluation = list(zip(parameters, node.call.args, strict=False))
        supplied = {name for name, _value in evaluation}
        for keyword in node.call.keywords:
            if keyword.arg is None:
                raise JVMUnsupported("JVM constructors do not support **kwargs", node)
            if keyword.arg not in parameters or keyword.arg in supplied:
                raise JVMUnsupported(
                    f"JVM constructor argument {keyword.arg} is invalid",
                    node,
                )
            supplied.add(keyword.arg)
            evaluation.append((keyword.arg, keyword.value))
        missing = [name for name in parameters if name not in supplied]
        first_default = len(parameters) - len(initializer.defaults)
        defaults = dict(
            zip(
                parameters[first_default:],
                initializer.defaults,
                strict=True,
            )
        )
        required = [name for name in missing if name not in defaults]
        if required:
            raise JVMUnsupported(
                f"JVM constructor arguments are missing: {', '.join(required)}",
                node,
            )
        evaluation.extend((name, defaults[name]) for name in missing)
        return evaluation, parameters

    @staticmethod
    def is_immutable_default(node: ast.expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value is None or isinstance(
                node.value,
                (bool, int, float, str),
            )
        return (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
            and not isinstance(node.operand.value, bool)
        )

    def application_arguments(
        self,
        node: ast.Call,
        function: Function,
    ) -> list[ast.expr]:
        if node.keywords:
            raise JVMUnsupported(
                "JVM application calls do not yet support keyword arguments",
                node,
            )
        arguments = list(node.args)
        required = len(function.params) - len(function.defaults)
        default_offset = len(arguments) - required
        if default_offset < 0 or len(arguments) > len(function.params):
            raise JVMUnsupported(
                f"JVM call to {function.name} has incompatible arguments",
                node,
            )
        arguments.extend(function.defaults[default_offset:])
        return arguments

    def exception_class(self, value_type, node):
        value = exception_type(value_type)
        if value is None or value.__module__ != native_builtins.__name__:
            raise JVMUnsupported("JVM exceptions require a supported builtin type", node)
        if value in {native_builtins._KeyError, native_builtins._UnicodeDecodeError}:
            raise JVMUnsupported(
                f"JVM {value_type.name} construction and matching are not implemented", node,
            )
        return emit_exception_class(self.class_files, self.main_class_name, value)

    def exception_match_class(self, value_type, node):
        value = exception_type(value_type)
        if value is native_builtins._BaseException:
            return "java/lang/Throwable"
        if value is native_builtins._Exception:
            return "java/lang/Exception"
        return self.exception_class(value_type, node)

    def exception_message(self):
        reference = self.class_file.method_reference(
            "java/lang/Throwable", "getMessage", "()Ljava/lang/String;",
        )
        self.code.emit(0xB6, reference.to_bytes(2, "big"))
        present = self.new_label("exception.message")
        self.code.emit(0x59)
        self.code.branch(0xC7, present)
        self.code.emit(0x57)
        self.expression(ast.Constant(value=""))
        self.code.mark(present)

    def raise_python_exception(self, node):
        if node.reraised:
            if node.exception is None:
                raise JVMUnsupported("JVM bare raise requires an active handler", node)
            self.expression(node.exception)
            self.code.emit(0xBF)
            return
        name = self.exception_class(node.value_type, node)
        index = self.class_file.constants.class_(name)
        self.code.emit(0xBB, index.to_bytes(2, "big"))
        self.code.emit(0x59)
        message = node.message if node.message is not None else ast.Constant(value="")
        if self.expression(message) != "Ljava/lang/String;":
            raise JVMUnsupported("JVM exception messages must be strings", message)
        constructor = self.class_file.method_reference(name, "<init>", "(Ljava/lang/String;)V")
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        self.code.emit(0xBF)

    def field(
        self, attribute
    ) -> tuple[str, str, str, str, str, bool, NumericFormat | None]:
        receiver_type = analyzed_value_type(attribute.value)
        native = self.native_field(attribute)
        if native is not None:
            if native.static:
                raise JVMUnsupported(
                    f"JVM static field {native.owner}.{native.name} "
                    "requires class access",
                    attribute,
                )
            return (
                f"L{native.owner};",
                native.owner,
                native.name,
                native.abi_type,
                native.semantic_type,
                native.writable,
                native.numeric_format,
            )
        layout = self.classes.get(receiver_type)
        if layout is None:
            raise JVMUnsupported(
                f"JVM cannot resolve field {attribute.attr} on {receiver_type.name}",
                attribute,
            )
        owner = receiver_type
        field = None
        while layout is not None:
            field = next(
                (field for field in layout.fields if field.name == attribute.attr),
                None,
            )
            if field is not None:
                break
            owner = layout.base
            layout = self.classes.get(owner)
        if field is None:
            raise JVMUnsupported(
                f"JVM class {receiver_type.name} has no field {attribute.attr}",
                attribute,
            )
        return (
            self.class_descriptor(receiver_type),
            self.class_name(owner),
            field.name,
            _numeric_descriptor(field.numeric_format)
            or self.value_type(field.value_type, field.representation),
            self.value_type(field.value_type, field.representation),
            True,
            field.numeric_format,
        )

    def native_field(self, attribute: ast.Attribute) -> NativeField | None:
        receiver = analyzed_value_object(attribute.value)
        if isinstance(receiver, Class):
            value_type = receiver
            class_access = True
        elif isinstance(receiver, Instance):
            value_type = receiver.cls
            class_access = False
        else:
            return None
        field_value = getattr(attribute, "obj", None)
        if not isinstance(field_value, Instance):
            return None
        semantic_type = self.value_type(field_value.cls)
        for owner in value_type.py_obj.__mro__:
            annotations = annotationlib.get_annotations(
                owner,
                format=annotationlib.Format.VALUE,
            )
            annotation = annotations.get(attribute.attr)
            if annotation is None:
                continue
            _value, metadata, static = _annotation_parts(annotation)
            declaration = next(
                (value for value in metadata if isinstance(value, JVMField)),
                None,
            )
            if declaration is None:
                return None
            if static != class_access:
                access = "class" if static else "instance"
                raise JVMUnsupported(
                    f"JVM field {attribute.attr} requires {access} access",
                    attribute,
                )
            owner_name = backend_metadata(owner, "jvm", "owner")
            if owner_name is None:
                raise JVMUnsupported(
                    f"JVM field {attribute.attr} has no native owner",
                    attribute,
                )
            abi_type = _abi_descriptor(annotation) or semantic_type
            self.validate_native_primitive(
                semantic_type,
                abi_type,
                f"{value_type.name}.{attribute.attr}",
            )
            return NativeField(
                owner_name,
                declaration.name or attribute.attr,
                abi_type,
                semantic_type,
                static,
                declaration.writable,
                numeric_format(annotation),
            )
        return None

    def static_field_store(self, target: ast.Attribute, value: ast.expr) -> bool:
        field = self.native_field(target)
        if field is None or not field.static:
            return False
        if not field.writable:
            raise JVMUnsupported(
                f"JVM field {field.owner}.{field.name} is read-only",
                target,
            )
        value_type = self.expression(value)
        self.convert_native_argument(value_type, field.abi_type, target)
        reference = self.class_file.field_reference(
            field.owner,
            field.name,
            field.abi_type,
        )
        self.code.emit(0xB3, reference.to_bytes(2, "big"))
        return True

    def comparison(self, opcode: int) -> None:
        true = self.new_label("comparison.true")
        done = self.new_label("comparison.done")
        self.code.branch(opcode, true)
        self.code.emit(0x03)
        self.code.branch(0xA7, done)
        self.code.mark(true)
        self.code.emit(0x04)
        self.code.mark(done)

    def double_comparison(self, operation: str) -> None:
        # dcmpg makes NaN fail < and <=; dcmpl makes it fail > and >=. Equality
        # only needs NaN to compare nonzero, which either instruction provides.
        self.code.emit(0x98 if operation in {"__lt__", "__le__"} else 0x97)
        self.comparison(self.INTEGER_COMPARISONS[operation])

    def checked_double_division(self) -> None:
        valid = self.new_label("double.division.valid")
        self.code.emit(0x5C)
        self.code.emit(0x0E)
        self.code.emit(0x97)
        self.code.branch(0x9A, valid)
        self.code.emit(0x58)
        self.code.emit(0x58)
        self.throw("java/lang/ArithmeticException")
        self.code.mark(valid)
        self.code.emit(0x6F)

    def checked_integer_division(self) -> None:
        valid = self.new_label("integer.division.valid")
        self.store("__integer.divisor", "J")
        self.store("__integer.dividend", "J")
        self.load("__integer.dividend")
        self.long_constant(-(2**63))
        self.code.emit(0x94)
        self.code.branch(0x9A, valid)
        self.load("__integer.divisor")
        self.long_constant(-1)
        self.code.emit(0x94)
        self.code.branch(0x9A, valid)
        self.throw("java/lang/ArithmeticException")
        self.code.mark(valid)
        self.load("__integer.dividend")
        self.load("__integer.divisor")

    def wgsl_integer_division(self, *, modulo: bool, signed: bool) -> None:
        nonzero = self.new_label("wgsl.division.nonzero")
        calculate = self.new_label("wgsl.division.calculate")
        done = self.new_label("wgsl.division.done")
        self.store("__wgsl.divisor", "J")
        self.store("__wgsl.dividend", "J")
        self.load("__wgsl.divisor")
        self.code.emit(0x09)
        self.code.emit(0x94)
        self.code.branch(0x9A, nonzero)
        if modulo:
            self.code.emit(0x09)
        else:
            self.load("__wgsl.dividend")
        self.code.branch(0xA7, done)
        self.code.mark(nonzero)
        if signed:
            self.load("__wgsl.dividend")
            self.long_constant(-(2**31))
            self.code.emit(0x94)
            self.code.branch(0x9A, calculate)
            self.load("__wgsl.divisor")
            self.long_constant(-1)
            self.code.emit(0x94)
            self.code.branch(0x9A, calculate)
            if modulo:
                self.code.emit(0x09)
            else:
                self.load("__wgsl.dividend")
            self.code.branch(0xA7, done)
        self.code.mark(calculate)
        self.load("__wgsl.dividend")
        self.load("__wgsl.divisor")
        self.code.emit(0x71 if modulo else 0x6D)
        self.code.mark(done)

    def integer_true_division(self) -> None:
        valid = self.new_label("integer.true.division.valid")
        self.store("__integer.divisor", "J")
        self.store("__integer.dividend", "J")
        self.load("__integer.divisor")
        self.code.emit(0x09)
        self.code.emit(0x94)
        self.code.branch(0x9A, valid)
        self.throw("java/lang/ArithmeticException")
        self.code.mark(valid)

        owner = "java/math/BigDecimal"
        class_index = self.class_file.constants.class_(owner)
        constructor = self.class_file.method_reference(owner, "<init>", "(J)V")
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        self.load("__integer.dividend")
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        self.code.emit(0xBB, class_index.to_bytes(2, "big"))
        self.code.emit(0x59)
        self.load("__integer.divisor")
        self.code.emit(0xB7, constructor.to_bytes(2, "big"))
        context_owner = "java/math/MathContext"
        context_class = self.class_file.constants.class_(context_owner)
        self.code.emit(0xBB, context_class.to_bytes(2, "big"))
        self.code.emit(0x59)
        # This exceeds the precision needed to round any signed-i64 ratio once.
        self.code.emit(0x10, bytes((80,)))
        context = self.class_file.method_reference(
            context_owner,
            "<init>",
            "(I)V",
        )
        self.code.emit(0xB7, context.to_bytes(2, "big"))
        divide = self.class_file.method_reference(
            owner,
            "divide",
            "(Ljava/math/BigDecimal;Ljava/math/MathContext;)Ljava/math/BigDecimal;",
        )
        self.code.emit(0xB6, divide.to_bytes(2, "big"))
        double_value = self.class_file.method_reference(owner, "doubleValue", "()D")
        self.code.emit(0xB6, double_value.to_bytes(2, "big"))

    def integer_power(self) -> None:
        valid = self.new_label("integer.power.valid")
        loop = self.new_label("integer.power.loop")
        square = self.new_label("integer.power.square")
        done = self.new_label("integer.power.done")
        self.store("__integer.power.exponent", "J")
        self.store("__integer.power.base", "J")
        self.load("__integer.power.exponent")
        self.code.emit(0x09)
        self.code.emit(0x94)
        self.code.branch(0x9C, valid)
        self.throw("java/lang/IllegalArgumentException")
        self.code.mark(valid)
        self.long_constant(1)
        self.store("__integer.power.result", "J")
        self.code.mark(loop)
        self.load("__integer.power.exponent")
        self.code.emit(0x09)
        self.code.emit(0x94)
        self.code.branch(0x99, done)
        self.load("__integer.power.exponent")
        self.long_constant(1)
        self.code.emit(0x7F)
        self.code.emit(0x09)
        self.code.emit(0x94)
        self.code.branch(0x99, square)
        self.load("__integer.power.result")
        self.load("__integer.power.base")
        self.code.emit(0x69)
        self.store("__integer.power.result", "J")
        self.code.mark(square)
        self.load("__integer.power.base")
        self.load("__integer.power.base")
        self.code.emit(0x69)
        self.store("__integer.power.base", "J")
        self.load("__integer.power.exponent")
        self.code.emit(0x04)
        self.code.emit(0x7D)
        self.store("__integer.power.exponent", "J")
        self.code.branch(0xA7, loop)
        self.code.mark(done)
        self.load("__integer.power.result")

    def integer_shift(self, *, left: bool, signed: bool, bits: int) -> None:
        valid = self.new_label("integer.shift.valid")
        fallback = self.new_label("integer.shift.fallback")
        done = self.new_label("integer.shift.done")
        self.store("__integer.shift.count", "J")
        self.store("__integer.shift.value", "J")
        self.load("__integer.shift.count")
        self.code.emit(0x09)
        self.code.emit(0x94)
        self.code.branch(0x9C, valid)
        self.throw("java/lang/ArithmeticException")
        self.code.mark(valid)
        self.load("__integer.shift.count")
        self.long_constant(bits)
        self.code.emit(0x94)
        self.code.branch(0x9C, fallback)
        self.load("__integer.shift.value")
        self.load("__integer.shift.count")
        self.code.emit(0x88)
        self.code.emit(0x79 if left else 0x7B if signed else 0x7D)
        self.code.branch(0xA7, done)
        self.code.mark(fallback)
        if left or not signed:
            self.long_constant(0)
        else:
            self.load("__integer.shift.value")
            self.long_constant(0)
            self.code.emit(0x94)
            nonnegative = self.new_label("integer.shift.nonnegative")
            self.code.branch(0x9C, nonnegative)
            self.long_constant(-1)
            self.code.branch(0xA7, done)
            self.code.mark(nonnegative)
            self.long_constant(0)
        self.code.mark(done)

    def load(self, name: str) -> str:
        value_type = self.slot_types[name]
        opcode = (
            0x16
            if value_type == "J"
            else 0x18
            if value_type == "D"
            else 0x15
            if value_type in {"B", "C", "S", "I", "Z"}
            else 0x17
            if value_type == "F"
            else 0x19
        )
        self.code.local(opcode, self.slots[name])
        semantic = {
            "B": "J",
            "C": "J",
            "S": "J",
            "I": "J",
            "F": "D",
        }.get(value_type, value_type)
        self.convert_abi_result(
            value_type,
            semantic,
            self.slot_numeric_formats.get(name),
        )
        return semantic

    def store(self, name: str, value_type: str) -> None:
        storage_type = self.slot_types[name]
        semantic = {
            "B": "J",
            "C": "J",
            "S": "J",
            "I": "J",
            "F": "D",
        }.get(storage_type, storage_type)
        if not self.compatible(value_type, semantic):
            raise JVMUnsupported(
                f"cannot store {value_type} in {storage_type} local {name}"
            )
        self.convert_native_argument(value_type, storage_type, ast.Name(id=name))
        opcode = (
            0x37
            if storage_type == "J"
            else 0x39
            if storage_type == "D"
            else 0x38
            if storage_type == "F"
            else 0x36
            if storage_type in {"B", "C", "S", "I", "Z"}
            else 0x3A
        )
        self.code.local(opcode, self.slots[name])

    def allocate_temporary(self, value_type: str, base: str) -> str:
        name = self.new_label(base)
        self.slots[name] = self.local_count
        self.slot_types[name] = value_type
        self.local_count += 2 if value_type in {"J", "D"} else 1
        return name

    def checkcast(self, value_type: str) -> None:
        if value_type == "Ljava/lang/Object;":
            return
        if not _is_reference_descriptor(value_type):
            raise JVMUnsupported("JVM checkcast requires a reference type")
        owner = value_type[1:-1] if value_type.startswith("L") else value_type
        class_index = self.class_file.constants.class_(owner)
        self.code.emit(0xC0, class_index.to_bytes(2, "big"))

    def long_constant(self, value: int) -> None:
        if value == 0:
            self.code.emit(0x09)
        elif value == 1:
            self.code.emit(0x0A)
        else:
            index = self.class_file.long_constant(value)
            self.code.emit(0x14, index.to_bytes(2, "big"))

    def double_constant(self, value: float) -> None:
        if value == 0.0 and math.copysign(1.0, value) > 0:
            self.code.emit(0x0E)
        elif value == 1.0:
            self.code.emit(0x0F)
        else:
            index = self.class_file.double_constant(value)
            self.code.emit(0x14, index.to_bytes(2, "big"))

    def string_constant(self, value: str) -> None:
        index = self.class_file.constants.string(value)
        if index <= 255:
            self.code.emit(0x12, index.to_bytes(1, "big"))
        else:
            self.code.emit(0x13, index.to_bytes(2, "big"))

    def bool_string(self) -> None:
        true = self.new_label("bool.string.true")
        done = self.new_label("bool.string.done")
        self.code.branch(0x9A, true)
        self.string_constant("False")
        self.code.branch(0xA7, done)
        self.code.mark(true)
        self.string_constant("True")
        self.code.mark(done)

    def joined_string(self, node: ast.JoinedStr) -> str:
        self.string_constant("")
        concat = self.class_file.method_reference(
            "java/lang/String",
            "concat",
            "(Ljava/lang/String;)Ljava/lang/String;",
        )
        for value in node.values:
            if isinstance(value, ast.Constant):
                self.string_constant(value.value)
            elif isinstance(value, ast.FormattedValue) and value.format_spec is None:
                value_type = self.expression(value.value)
                if value_type == "J":
                    reference = self.class_file.method_reference(
                        "java/lang/Long",
                        "toString",
                        "(J)Ljava/lang/String;",
                    )
                    self.code.emit(0xB8, reference.to_bytes(2, "big"))
                elif value_type == "Z":
                    self.bool_string()
                elif value_type != "Ljava/lang/String;":
                    raise JVMUnsupported("JVM formatted value is not implemented", value)
            else:
                raise JVMUnsupported(
                    "JVM formatted string spec is not implemented", value
                )
            self.code.emit(0xB6, concat.to_bytes(2, "big"))
        return "Ljava/lang/String;"

    def main_wrapper(self, entry_point: Function) -> Method:
        return_type = self.annotation(entry_point.return_type.annotation)
        storage_type = (
            _numeric_descriptor(entry_point.return_numeric_format) or return_type
        )
        if entry_point.params or return_type not in {"J", "Ljava/lang/String;"}:
            raise JVMUnsupported("the JVM executable entry point must return int or str")
        code = Bytecode()
        if return_type == "Ljava/lang/String;":
            output = self.class_file.field_reference(
                "java/lang/System",
                "out",
                "Ljava/io/PrintStream;",
            )
            code.emit(0xB2, output.to_bytes(2, "big"))
        reference = self.class_file.method_reference(
            self.class_file.name,
            self.function_name(entry_point),
            self.descriptor(entry_point),
        )
        code.emit(0xB8, reference.to_bytes(2, "big"))
        if return_type == "J" and storage_type == "J":
            code.emit(0x88)
        if return_type == "J":
            exit_reference = self.class_file.method_reference(
                "java/lang/System",
                "exit",
                "(I)V",
            )
            code.emit(0xB8, exit_reference.to_bytes(2, "big"))
        else:
            # Executable string results are UTF-8 bytes, independent of the
            # console's PrintStream charset (which can be lossy on Windows).
            charset = self.class_file.constants.string("UTF-8")
            code.emit(0x13, charset.to_bytes(2, "big"))
            encode_reference = self.class_file.method_reference(
                "java/lang/String", "getBytes", "(Ljava/lang/String;)[B",
            )
            code.emit(0xB6, encode_reference.to_bytes(2, "big"))
            print_reference = self.class_file.method_reference(
                "java/io/PrintStream",
                "write",
                "([B)V",
            )
            code.emit(0xB6, print_reference.to_bytes(2, "big"))
        code.emit(0xB1)
        return Method(0x0009, "main", "([Ljava/lang/String;)V", code.render(),
                      3 if return_type == "Ljava/lang/String;" else 2, 1)

    def default_constructor(self, class_file: ClassFile) -> Method:
        code = Bytecode()
        code.local(0x19, 0)
        reference = class_file.method_reference(class_file.super_name, "<init>", "()V")
        code.emit(0xB7, reference.to_bytes(2, "big"))
        code.emit(0xB1)
        return Method(0x0001, "<init>", "()V", code.render(), 1, 1)

    def has_native_superclass(self, value_type: Class) -> bool:
        while value_type in self.classes:
            value_type = self.classes[value_type].base
        return (
            value_type in self.native_classes
            and value_type not in self.native_interfaces
        )

    def native_subclass_constructor(
        self,
        class_file: ClassFile,
        layout: ClassIR,
        initializer: Function,
    ) -> Method:
        blocks = [block for block in initializer.ir.blocks if isinstance(block, Block)]
        native_calls = [
            node
            for block in blocks
            for statement in block.body
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__init__"
            and self.is_super_call(node.func.value)
            and isinstance(getattr(node.func, "obj", None), Function)
            and node.func.obj.name == "__init__"
            and (
                node.func.obj in self.native_functions
                or node.func.obj in self.functions
            )
        ]
        inherited = initializer.cls is not layout.value_type
        if inherited:
            native_calls = []
        if len(native_calls) > 1:
            raise JVMUnsupported(
                f"JVM subclass {layout.value_type.name} calls its native "
                "superclass constructor more than once"
            )
        native_call = native_calls[0] if native_calls else None
        if native_call is not None:
            first = blocks[0].body[0] if blocks and blocks[0].body else None
            if not isinstance(first, ast.Expr) or first.value is not native_call:
                raise JVMUnsupported(
                    "JVM native superclass constructor must be the first "
                    "initializer statement",
                    native_call,
                )
        base_layout = self.classes.get(layout.base) or self.native_layouts[layout.base]
        native_initializer = (
            native_call.func.obj
            if native_call is not None
            else base_layout.constructor
        )
        native = native_initializer in self.native_functions
        native_descriptor = (
            self.native_descriptor(native_initializer)
            if native else self.descriptor(native_initializer)
        )
        arguments = native_call.args if native_call is not None else []
        if native_call is not None and native_call.keywords:
            raise JVMUnsupported(
                "JVM native superclass constructors require positional arguments",
                native_call,
            )
        if native_call is None and not inherited and native_descriptor != "()V":
            raise JVMUnsupported(
                f"JVM subclass {layout.value_type.name} must call its native "
                "superclass constructor"
            )
        parameters = {parameter.arg: parameter for parameter in initializer.params}
        forwarded = list(parameters) if inherited else []
        for argument in arguments:
            if not isinstance(argument, ast.Name) or argument.id not in parameters:
                raise JVMUnsupported(
                    "JVM native superclass constructor arguments must be direct "
                    "initializer parameters",
                    argument,
                )
            forwarded.append(argument.id)

        slots = {}
        types = {}
        index = 1
        for parameter in initializer.params:
            value_type = _numeric_descriptor(
                analyzed_numeric_format(parameter)
            ) or self.parameter_type(parameter)
            slots[parameter.arg] = index
            types[parameter.arg] = value_type
            index += 2 if value_type in {"J", "D"} else 1

        code = Bytecode()
        code.local(0x19, 0)
        expected = (
            self.native_parameter_types(native_initializer)
            if native else [
                _numeric_descriptor(analyzed_numeric_format(parameter))
                or self.parameter_type(parameter)
                for parameter in native_initializer.params
            ]
        )
        if len(forwarded) != len(expected):
            raise JVMUnsupported(
                f"JVM native superclass constructor for {layout.value_type.name} "
                "has incompatible arguments"
            )
        for name, wanted in zip(forwarded, expected, strict=True):
            actual = types[name]
            opcode = (
                0x16
                if actual == "J"
                else 0x18
                if actual == "D"
                else 0x17
                if actual == "F"
                else 0x15
                if actual in {"B", "C", "I", "S", "Z"}
                else 0x19
            )
            code.local(opcode, slots[name])
            if actual == "J" and wanted in {"B", "C", "I", "S"}:
                code.emit(0x88)
            elif actual == "D" and wanted == "F":
                code.emit(0x90)
            elif not self.compatible(actual, wanted):
                raise JVMUnsupported(
                    f"JVM native superclass constructor for "
                    f"{layout.value_type.name} has incompatible arguments"
                )
        reference = class_file.method_reference(
            class_file.super_name,
            "<init>",
            native_descriptor,
        )
        code.emit(0xB7, reference.to_bytes(2, "big"))
        code.emit(0xB1)
        return Method(
            0x0001,
            "<init>",
            self.descriptor(initializer),
            code.render(),
            0xFFFF,
            index,
        )

    def list_class(self, value_type) -> ClassFile:
        name = self.list_class_name(value_type)
        existing = self.class_files.get(name)
        if existing is not None:
            self.list_classes[value_type] = existing
            return existing
        item_type = self.list_item_type(value_type)
        class_file = ClassFile(name)
        self.list_classes[value_type] = class_file
        self.class_files[name] = class_file
        array_type = f"[{item_type}"
        class_file.add_field(Field(0x0001, "data", array_type))
        class_file.add_field(Field(0x0001, "length", "I"))
        class_file.add_method(self.list_constructor(class_file, item_type))
        class_file.add_method(self.list_append_method(class_file, item_type))
        class_file.add_method(self.list_get_method(class_file, item_type))
        class_file.add_method(self.list_set_method(class_file, item_type))
        class_file.add_method(self.list_insert_method(class_file, item_type))
        if item_type == "Ljava/lang/String;":
            class_file.add_method(self.string_list_join_method(class_file))
        return class_file

    def tuple_class(self, value_type) -> ClassFile:
        name = self.tuple_class_name(value_type)
        existing = self.class_files.get(name)
        if existing is not None:
            self.tuple_classes[value_type] = existing
            return existing
        class_file = ClassFile(name)
        self.class_files[name] = class_file
        self.tuple_classes[value_type] = class_file
        for index, field_type in enumerate(value_type.generic_types.values()):
            class_file.add_field(Field(0x0001, f"_{index}", self.value_type(field_type)))
        class_file.add_method(self.default_constructor(class_file))
        return class_file

    def list_constructor(self, class_file: ClassFile, item_type: str) -> Method:
        code = Bytecode()
        code.local(0x19, 0)
        parent = class_file.method_reference("java/lang/Object", "<init>", "()V")
        code.emit(0xB7, parent.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.emit(0x07)
        self.new_array(code, class_file, item_type)
        data = class_file.field_reference(class_file.name, "data", f"[{item_type}")
        code.emit(0xB5, data.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.emit(0x03)
        length = class_file.field_reference(class_file.name, "length", "I")
        code.emit(0xB5, length.to_bytes(2, "big"))
        code.emit(0xB1)
        return Method(0x0001, "<init>", "()V", code.render(), 2, 1)

    def list_append_method(self, class_file: ClassFile, item_type: str) -> Method:
        code = Bytecode()
        data = class_file.field_reference(class_file.name, "data", f"[{item_type}")
        length = class_file.field_reference(class_file.name, "length", "I")
        capacity = "capacity"
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.emit(0xBE)
        code.branch(0xA0, capacity)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.emit(0x05)
        code.emit(0x68)
        self.new_array(code, class_file, item_type)
        item_slots = 2 if item_type in {"D", "J"} else 1
        temporary = 1 + item_slots
        code.local(0x3A, temporary)
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.emit(0x03)
        code.local(0x19, temporary)
        code.emit(0x03)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        copy = class_file.method_reference(
            "java/lang/System",
            "arraycopy",
            "(Ljava/lang/Object;ILjava/lang/Object;II)V",
        )
        code.emit(0xB8, copy.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.local(0x19, temporary)
        code.emit(0xB5, data.to_bytes(2, "big"))
        code.mark(capacity)
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.local(
            {"D": 0x18, "J": 0x16, "Z": 0x15}.get(item_type, 0x19),
            1,
        )
        code.emit({"D": 0x52, "J": 0x50, "Z": 0x54}.get(item_type, 0x53))
        code.local(0x19, 0)
        code.emit(0x59)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.emit(0x04)
        code.emit(0x60)
        code.emit(0xB5, length.to_bytes(2, "big"))
        code.emit(0xB1)
        return Method(
            0x0001,
            "append",
            f"({item_type})V",
            code.render(),
            5,
            temporary + 1,
        )

    def list_insert_method(self, class_file: ClassFile, item_type: str) -> Method:
        code = Bytecode()
        length = class_file.field_reference(class_file.name, "length", "I")
        data = class_file.field_reference(class_file.name, "data", f"[{item_type}")
        size_slot = 3 + (2 if item_type in {"J", "D"} else 1)
        load_item = {"D": 0x18, "J": 0x16, "Z": 0x15}.get(item_type, 0x19)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.local(0x36, size_slot)
        code.local(0x16, 1)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9C, "clamp")
        code.local(0x16, 1)
        code.local(0x15, size_slot)
        code.emit(0x85)
        code.emit(0x61)
        code.local(0x37, 1)
        code.mark("clamp")
        code.emit(0x09)
        code.local(0x16, 1)
        code.local(0x15, size_slot)
        code.emit(0x85)
        minimum = class_file.method_reference("java/lang/Math", "min", "(JJ)J")
        maximum = class_file.method_reference("java/lang/Math", "max", "(JJ)J")
        code.emit(0xB8, minimum.to_bytes(2, "big"))
        code.emit(0xB8, maximum.to_bytes(2, "big"))
        code.local(0x37, 1)
        code.local(0x19, 0)
        code.local(load_item, 3)
        append = class_file.method_reference(class_file.name, "append", f"({item_type})V")
        code.emit(0xB6, append.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x16, 1)
        code.emit(0x88)
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x16, 1)
        code.emit(0x88)
        code.emit(0x04)
        code.emit(0x60)
        code.local(0x15, size_slot)
        code.local(0x16, 1)
        code.emit(0x88)
        code.emit(0x64)
        copy = class_file.method_reference(
            "java/lang/System", "arraycopy", "(Ljava/lang/Object;ILjava/lang/Object;II)V"
        )
        code.emit(0xB8, copy.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x16, 1)
        code.emit(0x88)
        code.local(load_item, 3)
        code.emit(self.array_store_opcode(item_type))
        code.emit(0xB1)
        return Method(0x0001, "insert", f"(J{item_type})V", code.render(), 7, size_slot + 1)

    def list_get_method(self, class_file: ClassFile, item_type: str) -> Method:
        code = Bytecode()
        data = class_file.field_reference(class_file.name, "data", f"[{item_type}")
        length = class_file.field_reference(class_file.name, "length", "I")
        positive = "positive"
        validate = "validate"
        valid = "valid"
        invalid = "invalid"
        actual = 3
        code.local(0x16, 1)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9C, positive)
        code.local(0x16, 1)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.emit(0x85)
        code.emit(0x61)
        code.local(0x37, actual)
        code.branch(0xA7, validate)
        code.mark(positive)
        code.local(0x16, 1)
        code.local(0x37, actual)
        code.mark(validate)
        code.local(0x16, actual)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9B, invalid)
        code.local(0x16, actual)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.emit(0x85)
        code.emit(0x94)
        code.branch(0x9B, valid)
        code.mark(invalid)
        self.throw("java/lang/IndexOutOfBoundsException", code, class_file)
        code.mark(valid)
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x16, actual)
        code.emit(0x88)
        code.emit({"D": 0x31, "J": 0x2F, "Z": 0x33}.get(item_type, 0x32))
        code.emit({"D": 0xAF, "J": 0xAD, "Z": 0xAC}.get(item_type, 0xB0))
        return Method(0x0001, "get", f"(J){item_type}", code.render(), 4, 5)

    def list_set_method(self, class_file: ClassFile, item_type: str) -> Method:
        code = Bytecode()
        data = class_file.field_reference(class_file.name, "data", f"[{item_type}")
        length = class_file.field_reference(class_file.name, "length", "I")
        positive = "positive"
        validate = "validate"
        valid = "valid"
        invalid = "invalid"
        value_slot = 3
        actual = value_slot + (2 if item_type in {"D", "J"} else 1)
        code.local(0x16, 1)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9C, positive)
        code.local(0x16, 1)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.emit(0x85)
        code.emit(0x61)
        code.local(0x37, actual)
        code.branch(0xA7, validate)
        code.mark(positive)
        code.local(0x16, 1)
        code.local(0x37, actual)
        code.mark(validate)
        code.local(0x16, actual)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9B, invalid)
        code.local(0x16, actual)
        code.local(0x19, 0)
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.emit(0x85)
        code.emit(0x94)
        code.branch(0x9B, valid)
        code.mark(invalid)
        self.throw("java/lang/IndexOutOfBoundsException", code, class_file)
        code.mark(valid)
        code.local(0x19, 0)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x16, actual)
        code.emit(0x88)
        code.local(
            {"D": 0x18, "J": 0x16, "Z": 0x15}.get(item_type, 0x19),
            value_slot,
        )
        code.emit({"D": 0x52, "J": 0x50, "Z": 0x54}.get(item_type, 0x53))
        code.emit(0xB1)
        return Method(
            0x0001,
            "set",
            f"(J{item_type})V",
            code.render(),
            4,
            actual + 2,
        )

    def string_list_join_method(self, class_file: ClassFile) -> Method:
        code = Bytecode()
        loop = "list.join.loop"
        item = "list.join.item"
        done = "list.join.done"
        builder_class = "java/lang/StringBuilder"
        builder_index = class_file.constants.class_(builder_class)
        code.emit(0xBB, builder_index.to_bytes(2, "big"))
        code.emit(0x59)
        constructor = class_file.method_reference(builder_class, "<init>", "()V")
        code.emit(0xB7, constructor.to_bytes(2, "big"))
        code.local(0x3A, 2)
        code.emit(0x03)
        code.local(0x36, 3)
        code.mark(loop)
        code.local(0x15, 3)
        code.local(0x19, 0)
        length = class_file.field_reference(class_file.name, "length", "I")
        code.emit(0xB4, length.to_bytes(2, "big"))
        code.branch(0xA2, done)
        code.local(0x15, 3)
        code.branch(0x99, item)
        code.local(0x19, 2)
        code.local(0x19, 1)
        append = class_file.method_reference(
            builder_class,
            "append",
            "(Ljava/lang/String;)Ljava/lang/StringBuilder;",
        )
        code.emit(0xB6, append.to_bytes(2, "big"))
        code.emit(0x57)
        code.mark(item)
        code.local(0x19, 2)
        code.local(0x19, 0)
        data = class_file.field_reference(
            class_file.name,
            "data",
            "[Ljava/lang/String;",
        )
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x15, 3)
        code.emit(0x32)
        code.emit(0xB6, append.to_bytes(2, "big"))
        code.emit(0x57)
        code.local(0x15, 3)
        code.emit(0x04)
        code.emit(0x60)
        code.local(0x36, 3)
        code.branch(0xA7, loop)
        code.mark(done)
        code.local(0x19, 2)
        to_string = class_file.method_reference(
            builder_class,
            "toString",
            "()Ljava/lang/String;",
        )
        code.emit(0xB6, to_string.to_bytes(2, "big"))
        code.emit(0xB0)
        return Method(
            0x0001,
            "join",
            "(Ljava/lang/String;)Ljava/lang/String;",
            code.render(),
            4,
            4,
        )

    def new_array(self, code: Bytecode, class_file: ClassFile, item_type: str) -> None:
        primitive = {
            "Z": 4,
            "C": 5,
            "F": 6,
            "D": 7,
            "B": 8,
            "S": 9,
            "I": 10,
            "J": 11,
        }.get(item_type)
        if primitive is not None:
            code.emit(0xBC, bytes((primitive,)))
        elif _is_reference_descriptor(item_type):
            component = class_file.constants.class_(
                item_type[1:-1] if item_type.startswith("L") else item_type
            )
            code.emit(0xBD, component.to_bytes(2, "big"))
        else:
            raise JVMUnsupported(f"JVM array item type {item_type} is not implemented")

    @staticmethod
    def array_load_opcode(item_type: str) -> int:
        opcode = {
            "Z": 0x33,
            "B": 0x33,
            "C": 0x34,
            "S": 0x35,
            "I": 0x2E,
            "J": 0x2F,
            "F": 0x30,
            "D": 0x31,
        }.get(item_type, 0x32 if _is_reference_descriptor(item_type) else None)
        if opcode is None:
            raise JVMUnsupported(f"JVM array item type {item_type} is not implemented")
        return opcode

    @staticmethod
    def array_store_opcode(item_type: str) -> int:
        opcode = {
            "Z": 0x54,
            "B": 0x54,
            "C": 0x55,
            "S": 0x56,
            "I": 0x4F,
            "J": 0x50,
            "F": 0x51,
            "D": 0x52,
        }.get(item_type, 0x53 if _is_reference_descriptor(item_type) else None)
        if opcode is None:
            raise JVMUnsupported(f"JVM array item type {item_type} is not implemented")
        return opcode

    def throw(
        self,
        class_name: str,
        code: Bytecode | None = None,
        class_file: ClassFile | None = None,
    ) -> None:
        code = code or self.code
        class_file = class_file or self.class_file
        code.throw_new(class_file, class_name)

    def descriptor(self, function: Function) -> str:
        parameters = "".join(
            _numeric_descriptor(analyzed_numeric_format(parameter))
            or self.parameter_type(parameter)
            for parameter in function.params
        )
        result = _numeric_descriptor(
            function.return_numeric_format
        ) or self.function_return_type(function)
        return f"({parameters}){result}"

    def parameter_type(self, parameter) -> str:
        value_type = getattr(parameter.annotation, "obj", None)
        if value_type is None and isinstance(getattr(parameter, "obj", None), Instance):
            value_type = parameter.obj.cls
        if isinstance(value_type, (Class, UnionType)):
            return self.value_type(value_type, analyzed_representation(parameter))
        return self.annotation(parameter.annotation)

    def function_return_type(self, function: Function) -> str:
        value_type = (
            function.return_type
            if isinstance(function.return_type, (Class, UnionType))
            else getattr(function.return_type.annotation, "obj", None)
        )
        if value_type is None and isinstance(function.return_type, Instance):
            value_type = function.return_type.cls
        if isinstance(value_type, (Class, UnionType)):
            descriptor = self.value_type(value_type, function.return_representation)
            return "V" if descriptor == "N" else descriptor
        return self.annotation(function.return_type.annotation)

    @staticmethod
    def native_annotations(function: Function) -> dict[str, object]:
        return annotationlib.get_annotations(
            function.py_func,
            format=annotationlib.Format.VALUE,
        )

    def native_parameter_types(self, function: Function) -> list[str]:
        annotations = self.native_annotations(function)
        if not function.params:
            parameters = list(inspect.signature(function.py_func).parameters)
            if function.cls is not None and parameters:
                parameters.pop(0)
            result = []
            for name in parameters:
                annotation = annotations.get(name)
                abi = _abi_descriptor(annotation)
                semantic = _native_type_descriptor(annotation)
                if semantic is None:
                    raise JVMUnsupported(
                        f"JVM native parameter {function.name}.{name} "
                        "has an unsupported annotation"
                    )
                abi = abi or semantic
                self.validate_native_primitive(semantic, abi, function.name)
                result.append(abi)
            return result
        result = []
        for parameter in function.params:
            annotation = annotations.get(parameter.arg)
            abi = _abi_descriptor(annotation)
            semantic = _native_type_descriptor(annotation)
            if semantic is None:
                try:
                    semantic = self.parameter_type(parameter)
                except JVMUnsupported:
                    if abi is None or not _is_reference_descriptor(abi):
                        raise
                    semantic = abi
            abi = abi or semantic
            self.validate_native_primitive(semantic, abi, function.name)
            result.append(abi)
        return result

    def native_return_types(self, function: Function) -> tuple[str, str]:
        if function.name == "__init__":
            return "V", "V"
        annotation = self.native_annotations(function).get("return")
        semantic = _native_type_descriptor(annotation)
        if semantic is None:
            semantic = self.function_return_type(function)
        abi = _abi_descriptor(annotation) or semantic
        self.validate_native_primitive(semantic, abi, function.name)
        return semantic, abi

    def native_descriptor(self, function: Function) -> str:
        parameters = "".join(self.native_parameter_types(function))
        _semantic, result = self.native_return_types(function)
        return f"({parameters}){result}"

    @staticmethod
    def validate_native_primitive(
        semantic: str,
        abi: str,
        context: str,
    ) -> None:
        required = {
            "B": "J",
            "C": "J",
            "S": "J",
            "I": "J",
            "F": "D",
            "D": "D",
        }.get(abi)
        if required is not None and semantic != required:
            raise JVMUnsupported(
                f"JVM native type {abi} on {context} requires {required} "
                f"semantics, not {semantic}"
            )

    def native_arguments(self, call: ast.Call, function: Function) -> None:
        if call.keywords:
            raise JVMUnsupported(
                "JVM native calls do not yet support keyword arguments",
                call,
            )
        arguments = call.args
        expected = self.native_parameter_types(function)
        required = len(expected) - len(function.defaults)
        if not required <= len(arguments) <= len(expected):
            raise JVMUnsupported(
                f"JVM native call to {function.name} has incompatible arguments",
                call,
            )
        default_offset = len(arguments) - required
        values = [*arguments, *function.defaults[default_offset:]]
        for argument, wanted in zip(values, expected, strict=True):
            actual = self.expression(argument)
            self.convert_native_argument(actual, wanted, call)

    def convert_native_argument(
        self,
        actual: str,
        expected: str,
        node: ast.AST,
    ) -> None:
        if actual == "N" and _is_reference_descriptor(expected):
            return
        if actual == "J" and expected in {"B", "C", "S"}:
            self.code.emit(0x88)
            self.code.emit({"B": 0x91, "C": 0x92, "S": 0x93}[expected])
            return
        if actual == "J" and expected == "I":
            self.code.emit(0x88)
            return
        if actual == "D" and expected == "F":
            self.code.emit(0x90)
            return
        if _is_reference_descriptor(actual) and _is_reference_descriptor(expected):
            if actual.startswith("[") or expected.startswith("["):
                if actual != expected:
                    raise JVMUnsupported(
                        f"JVM native argument {actual} cannot cross an {expected} ABI",
                        node,
                    )
            return
        if self.compatible(actual, expected):
            return
        raise JVMUnsupported(
            f"JVM native argument {actual} cannot cross an {expected} ABI",
            node,
        )

    def convert_native_result(self, function: Function) -> str:
        semantic, abi = self.native_return_types(function)
        annotation = self.native_annotations(function).get("return")
        self.convert_abi_result(abi, semantic, numeric_format(annotation))
        return semantic

    def normalize_integer_result(self, node: ast.expr) -> None:
        storage_format = analyzed_numeric_format(node)
        if storage_format is None or storage_format.kind != "integer":
            return
        storage = _numeric_descriptor(storage_format)
        if storage is None or storage == "J":
            return
        self.convert_native_argument("J", storage, node)
        self.convert_abi_result(storage, "J", storage_format)

    def normalize_float_result(self, node: ast.expr) -> None:
        storage_format = analyzed_numeric_format(node)
        if (
            storage_format is not None
            and storage_format.kind == "float"
            and storage_format.bits == 32
        ):
            self.code.emit(0x90)
            self.code.emit(0x8D)

    def convert_abi_result(
        self,
        abi: str,
        semantic: str,
        storage_format: NumericFormat | None = None,
    ) -> None:
        if abi in {"B", "C", "S", "I"} and semantic == "J":
            self.code.emit(0x85)
            if storage_format is not None and storage_format.signed is False:
                mask = 2**storage_format.bits - 1
                self.long_constant(mask)
                self.code.emit(0x7F)
        elif abi == "F" and semantic == "D":
            self.code.emit(0x8D)
        elif abi != semantic:
            raise JVMUnsupported(f"JVM native result {abi} cannot become {semantic}")

    def annotation(self, node) -> str:
        if node is None or isinstance(node, ast.Constant) and node.value is None:
            return "V"
        if isinstance(node, ast.Name):
            if node.id == "int":
                return "J"
            if node.id == "float":
                return "D"
            if node.id == "bool":
                return "Z"
            if node.id == "str":
                return "Ljava/lang/String;"
            if node.id in {"None", "NoneType"}:
                return "V"
            value_type = getattr(node, "obj", None)
            if isinstance(value_type, Class):
                if value_type in self.classes:
                    return self.class_descriptor(value_type)
                if value_type in self.native_classes:
                    return f"L{self.native_class_name(value_type)};"
                if value_type in self.list_classes:
                    return f"L{self.list_class_name(value_type)};"
                if value_type in self.tuple_classes:
                    return f"L{self.tuple_class_name(value_type)};"
                if is_declaration(value_type.py_obj, "jvm"):
                    return f"L{backend_metadata(value_type.py_obj, 'jvm', 'owner')};"
            for value_type in self.classes:
                if value_type.name == node.id:
                    return self.class_descriptor(value_type)
            for value_type in self.native_classes:
                if value_type.name == node.id:
                    return f"L{self.native_class_name(value_type)};"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            members = []

            def add(value):
                if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
                    add(value.left)
                    add(value.right)
                elif not (
                    isinstance(value, ast.Constant)
                    and value.value is None
                    or isinstance(value, ast.Name)
                    and value.id in {"None", "NoneType"}
                ):
                    members.append(value)

            add(node)
            if len(members) == 1:
                descriptor = self.annotation(members[0])
                if _is_reference_descriptor(descriptor):
                    return descriptor
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Optional"
        ):
            descriptor = self.annotation(node.slice)
            if _is_reference_descriptor(descriptor):
                return descriptor
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "JVMArray"
        ):
            item = self.annotation(node.slice)
            return f"[{item}"
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"dict", "list", "tuple"}
        ):
            annotations = (
                node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
            )
            fields = tuple(self.annotation(annotation) for annotation in annotations)
            if node.value.id == "dict":
                if len(fields) != 2 or not all(
                    _is_reference_descriptor(field) for field in fields
                ):
                    raise JVMUnsupported(
                        "JVM dictionaries require reference key and value types",
                        node,
                    )
                return "Ljava/util/HashMap;"
            classes = self.list_classes if node.value.id == "list" else self.tuple_classes
            for value_type in classes:
                actual = tuple(
                    self.value_type(field_type)
                    for field_type in value_type.generic_types.values()
                )
                if actual == fields:
                    name = (
                        self.list_class_name(value_type)
                        if node.value.id == "list"
                        else self.tuple_class_name(value_type)
                    )
                    return f"L{name};"
        raise JVMUnsupported("unsupported JVM type annotation", node)

    def value_type(self, value_type, representation=None) -> str:
        if exception_type(value_type) is not None:
            return "Ljava/lang/Throwable;"
        if (isinstance(value_type, RecursiveTypeAlias)
                or isinstance(value_type, UnionType)
                and any(isinstance(member, RecursiveTypeAlias) for member in value_type._types.values())):
            # The expanded .types view can hide the named edge in T | None.
            # Diagnose before descending into its concrete recursive layout.
            raise JVMUnsupported("JVM recursive value layouts are not implemented")
        if isinstance(value_type, UnionType):
            representations = (
                representation.arguments
                if representation is not None and representation.kind == "union"
                else (None,) * len(value_type.types)
            )
            concrete = [
                member
                for member in value_type.types
                if member.generic_name not in {"None", "NoneType"}
            ]
            descriptors = [
                self.value_type(member, member_representation)
                for member, member_representation in zip(
                    value_type.types, representations, strict=True,
                )
                if member.generic_name not in {"None", "NoneType"}
            ]
            if len(concrete) == 1:
                descriptor = descriptors[0]
                if _is_reference_descriptor(descriptor):
                    return descriptor
            if descriptors and all(
                descriptor == descriptors[0] for descriptor in descriptors
            ):
                return descriptors[0]
            if descriptors and all(
                _is_reference_descriptor(descriptor) for descriptor in descriptors
            ):
                candidates = [descriptors[0]]
                first = concrete[0]
                while first in self.classes or first in self.native_layouts:
                    layout = self.classes.get(first) or self.native_layouts[first]
                    first = layout.base
                    if first in self.classes:
                        candidates.append(self.class_descriptor(first))
                    elif first in self.native_classes:
                        candidates.append(f"L{self.native_class_name(first)};")
                for candidate in candidates:
                    if all(
                        self.compatible(descriptor, candidate)
                        for descriptor in descriptors
                    ):
                        return candidate
                return "Ljava/lang/Object;"
            raise JVMUnsupported("JVM union has incompatible runtime types")
        if self.is_jvm_array_type(value_type):
            abi, _semantic = self.jvm_array_item_types(
                value_type, representation=representation,
            )
            return f"[{abi}"
        if value_type.generic_name == "int":
            return "J"
        if value_type.generic_name == "float":
            return "D"
        if value_type.generic_name == "bool":
            return "Z"
        if value_type.generic_name == "str":
            return "Ljava/lang/String;"
        if value_type.generic_name in {"None", "NoneType"}:
            return "N"
        if value_type.generic_name == "object":
            return "Ljava/lang/Object;"
        if value_type.generic_name in {"callable", "Callable"}:
            return "Ljava/lang/Runnable;"
        if value_type in self.classes:
            return self.class_descriptor(value_type)
        if value_type in self.native_classes:
            return f"L{self.native_class_name(value_type)};"
        if isinstance(value_type, Class) and is_declaration(value_type.py_obj, "jvm"):
            return f"L{backend_metadata(value_type.py_obj, 'jvm', 'owner')};"
        if value_type.generic_name == "list":
            self.list_class(value_type)
            return f"L{self.list_class_name(value_type)};"
        if value_type.generic_name == "dict":
            self.dictionary_types(value_type)
            return "Ljava/util/HashMap;"
        if value_type.generic_name == "tuple":
            self.tuple_class(value_type)
            return f"L{self.tuple_class_name(value_type)};"
        raise JVMUnsupported(f"unsupported JVM value type {value_type.name}")

    def dictionary_types(
        self,
        value_type,
        source: ast.AST | None = None,
    ) -> tuple[str, str]:
        try:
            key = value_type.generic_types["K"]
            value = value_type.generic_types["V"]
        except KeyError:
            raise JVMUnsupported(
                f"JVM dictionary {value_type.name} requires concrete key and value types",
                source,
            ) from None
        self.validate_java_object_semantics(key, source, dictionary_key=True)
        key_type = self.value_type(key)
        value_descriptor = self.value_type(value)
        if not _is_reference_descriptor(key_type) or not _is_reference_descriptor(
            value_descriptor
        ):
            raise JVMUnsupported(
                "JVM dictionaries currently require reference key and value types",
                source,
            )
        return key_type, value_descriptor

    def validate_java_object_semantics(
        self, value_type, source, *, dictionary_key=False,
    ) -> None:
        members = value_type.types if isinstance(value_type, UnionType) else (value_type,)
        for member in members:
            py_type = getattr(member, "py_obj", None)
            if py_type in {
                native_builtins._str, native_builtins._int,
                native_builtins._float, native_builtins._bool,
                native_builtins._NoneType,
            }:
                continue
            if py_type is native_builtins._object:
                py_type = object
            if not isinstance(py_type, type):
                continue
            candidates = [py_type, *(
                cls.py_obj for cls in self.classes
                if isinstance(cls.py_obj, type) and issubclass(cls.py_obj, py_type)
            )]
            for candidate in candidates:
                if candidate in {str, int, float, bool, type(None)}:
                    continue
                equality = getattr(candidate, "__eq__", object.__eq__)
                inequality = getattr(candidate, "__ne__", object.__ne__)
                hashing = getattr(candidate, "__hash__", object.__hash__)
                if equality is not object.__eq__ or (
                    not dictionary_key and inequality is not object.__ne__
                ) or (
                    dictionary_key and hashing is not object.__hash__
                ):
                    context = "dictionary keys" if dictionary_key else "dynamic equality"
                    raise JVMUnsupported(
                        f"JVM {context} cannot yet use Python __eq__/__hash__ "
                        f"semantics for {candidate.__name__}; Java object bridges "
                        "are not implemented",
                        source,
                    )

    def list_item_type(self, value_type) -> str:
        try:
            item_type = next(iter(value_type.generic_types.values()))
        except StopIteration:
            raise JVMUnsupported(
                f"JVM list {value_type.name} has no concrete item type"
            ) from None
        return self.value_type(item_type)

    @staticmethod
    def is_jvm_array_type(value_type) -> bool:
        if isinstance(value_type, UnionType):
            concrete = [member for member in value_type.types
                        if member.generic_name not in {"None", "NoneType"}]
            return len(concrete) == 1 and JVMEmitter.is_jvm_array_type(concrete[0])
        return isinstance(value_type, Class) and getattr(
            value_type.py_obj,
            "__pyjs_jvm_array__",
            False,
        )

    def narrow_array_offset(self, exception: str) -> None:
        valid = self.new_label("array.offset.valid")
        self.code.emit(0x5C)
        self.code.emit(0x5C)
        self.code.emit(0x88)
        self.code.emit(0x85)
        self.code.emit(0x94)
        self.code.branch(0x99, valid)
        self.throw(exception)
        self.code.mark(valid)
        self.code.emit(0x88)

    def jvm_array_item_types(
        self,
        value_type,
        source=None,
        representation=None,
    ) -> tuple[str, str]:
        if representation is None and source is not None:
            representation = analyzed_representation(source)
        if isinstance(value_type, UnionType):
            for index, member in enumerate(value_type.types):
                if self.is_jvm_array_type(member):
                    member_representation = (
                        representation.arguments[index]
                        if representation is not None and representation.kind == "union"
                        else representation
                    )
                    return self.jvm_array_item_types(
                        member, representation=member_representation,
                    )
        try:
            item = next(iter(value_type.generic_types.values()))
        except StopIteration:
            raise JVMUnsupported(
                f"JVM array {value_type.name} has no concrete item type"
            ) from None
        item_representation = (
            representation.arguments[0]
            if representation is not None and representation.arguments
            else None
        )
        if self.is_jvm_array_type(item):
            nested_abi, _nested_semantic = self.jvm_array_item_types(
                item,
                representation=item_representation,
            )
            descriptor = f"[{nested_abi}"
            return descriptor, descriptor
        semantic = self.value_type(item)
        abi = (
            _numeric_descriptor(
                item_representation.numeric if item_representation is not None else None
            )
            or semantic
        )
        return abi, semantic

    def list_class_name(self, value_type) -> str:
        item_type = self.list_item_type(value_type)
        suffix = re.sub(r"[^A-Za-z0-9_$]", "_", item_type)
        return f"{self.main_class_name}$list${suffix}"

    def tuple_class_name(self, value_type) -> str:
        fields = tuple(
            self.value_type(field_type)
            for field_type in value_type.generic_types.values()
        )
        suffix = "$".join(re.sub(r"[^A-Za-z0-9_$]", "_", field) for field in fields)
        return f"{self.main_class_name}$tuple${suffix or 'empty'}"

    def expression_type(self, node) -> str:
        value_type = analyzed_value_type(node)
        return self.value_type(value_type, analyzed_representation(node))

    def local_numeric_format(self, target):
        if not isinstance(target, (ast.Name, ast.arg)):
            return None
        name = target.id if isinstance(target, ast.Name) else target.arg
        try:
            value = self.current_function.scope.lookup(name)
        except NameError:
            return None
        return analyzed_numeric_format(value) if isinstance(value, Instance) else None

    @staticmethod
    def target_name(target) -> str:
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.arg):
            return target.arg
        if isinstance(target, BlockArgument):
            return target.name
        raise JVMUnsupported("unsupported JVM assignment target", target)

    def function_name(self, function: Function) -> str:
        if function.name == "main" and function.cls is None:
            return "pyjs_main"
        if function.name == "__init__":
            return "pyjs_init"
        declaration = self.native_override(function)
        if declaration is not None:
            return backend_metadata(
                declaration.py_func,
                "jvm",
                "name",
                declaration.name,
            )
        return function.name

    def native_override(self, function: Function) -> Function | None:
        layout = self.classes.get(function.cls)
        while layout is not None:
            base = layout.base
            native = self.native_layouts.get(base)
            if native is not None:
                declaration = next(
                    (
                        child
                        for child in native.value_type.children
                        if isinstance(child, Function) and child.name == function.name
                    ),
                    None,
                )
                if declaration is not None:
                    return declaration
            layout = self.classes.get(base) or native
        return None

    def class_name(self, value_type: Class) -> str:
        return f"{self.module_class(value_type.container)}${value_type.name}"

    def class_descriptor(self, value_type: Class) -> str:
        return f"L{self.class_name(value_type)};"

    def function_owner(self, function: Function) -> str:
        if function.cls in self.classes:
            return self.class_name(function.cls)
        return self.module_class(function.container)

    def module_class(self, module) -> str:
        existing = self.module_classes.get(module)
        if existing is not None:
            return existing
        suffix = "$".join(module.name.split("."))
        suffix = re.sub(r"[^A-Za-z0-9_$]", "_", suffix)
        name = f"{self.main_class_name}$module${suffix}"
        self.module_classes[module] = name
        return name

    def ensure_module_class(self, module) -> ClassFile:
        name = self.module_class(module)
        class_file = self.class_files.get(name)
        if class_file is None:
            class_file = ClassFile(name, source_file=self.module_source_file(module))
            self.class_files[name] = class_file
        return class_file

    def module_source_file(self, module) -> str:
        source = getattr(module.py_module, "__file__", None)
        return Path(source).name if source else self.source_file

    @staticmethod
    def native_class_name(value_type: Class) -> str:
        return backend_metadata(value_type.py_obj, "jvm", "owner")

    def compatible(self, actual: str, expected: str) -> bool:
        if actual == expected:
            return True
        if actual == "N" and _is_reference_descriptor(expected):
            return True
        if not _is_reference_descriptor(actual) or not _is_reference_descriptor(expected):
            return False
        if actual.startswith("[") or expected.startswith("["):
            return False
        actual_type = next(
            (
                value_type
                for value_type in (*self.classes, *self.native_classes)
                if (
                    self.class_descriptor(value_type)
                    if value_type in self.classes
                    else f"L{self.native_class_name(value_type)};"
                )
                == actual
            ),
            None,
        )
        while actual_type is not None:
            layout = self.classes.get(actual_type) or self.native_layouts.get(actual_type)
            if layout is None:
                break
            actual_type = layout.base
            if (
                actual_type in self.classes
                and self.class_descriptor(actual_type) == expected
            ):
                return True
            if (
                actual_type in self.native_classes
                and f"L{self.native_class_name(actual_type)};" == expected
            ):
                return True
        return False

    @staticmethod
    def is_super_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "super"
        )

    @staticmethod
    def block_label(name: str) -> str:
        return f"block.{name}"

    def new_label(self, prefix: str) -> str:
        self.next_label += 1
        return f"{prefix}.{self.next_label}"

    @staticmethod
    def source_line(node: ast.AST) -> int | None:
        direct = getattr(node, "lineno", None)
        if direct is not None:
            return direct
        return next(
            (
                child.lineno
                for child in ast.walk(node)
                if getattr(child, "lineno", None) is not None
            ),
            None,
        )


def transpile_jvm(
    source: str,
    *,
    filename: str = "_pyjs_java_.py",
    module_name: str | None = None,
    class_name: str = "PyjsProgram",
    root_names: tuple[str, ...] = (),
    tests: tuple[JVMTest, ...] = (),
    test_sdk: int | None = None,
    test_manifest: str | None = None,
) -> JVMCompilation:
    """Analyze source and emit a directly executable JVM class set."""
    with analyze_source(
        source,
        filename=filename,
        module_name=module_name,
        wrap=False,
        root_selector=(
            (lambda module: tuple(getattr(module, name) for name in root_names))
            if root_names
            else None
        ),
        environment=JVM_ENVIRONMENT,
    ) as analysis:
        for root in analysis.entry_point.compilation_entry_points[1:]:
            analysis.entry_point.compilation_objects.update(root.compilation_objects)
        program = build_program_ir(analysis.entry_point)
        return JVMEmitter(
            class_name,
            filename,
            tests,
            test_sdk,
            test_manifest,
        ).emit(program)

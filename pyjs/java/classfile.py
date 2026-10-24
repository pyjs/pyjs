"""Small dependency-free writer for the JVM class-file subset PyJS emits."""

import struct
from dataclasses import dataclass, field


def _u1(value: int) -> bytes:
    return struct.pack(">B", value)


def _u2(value: int) -> bytes:
    return struct.pack(">H", value)


def _u4(value: int) -> bytes:
    return struct.pack(">I", value)


def _modified_utf8(value: str) -> bytes:
    """Encode the UTF-16 code units used by CONSTANT_Utf8."""
    output = bytearray()
    encoded = value.encode("utf-16-be", errors="surrogatepass")
    for offset in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[offset:offset + 2], "big")
        if 1 <= unit <= 0x7F:
            output.append(unit)
        elif unit <= 0x7FF:
            output.extend((0xC0 | unit >> 6, 0x80 | unit & 0x3F))
        else:
            output.extend(
                (
                    0xE0 | unit >> 12,
                    0x80 | unit >> 6 & 0x3F,
                    0x80 | unit & 0x3F,
                )
            )
    return bytes(output)


class ConstantPool:
    """Deduplicated constants with JVM two-slot handling for wide values."""

    def __init__(self) -> None:
        self.entries: list[bytes | None] = []
        self.indexes = {}

    def add(self, key, value: bytes, *, wide: bool = False) -> int:
        if key in self.indexes:
            return self.indexes[key]
        index = len(self.entries) + 1
        self.entries.append(value)
        if wide:
            self.entries.append(None)
        self.indexes[key] = index
        return index

    def utf8(self, value: str) -> int:
        encoded = _modified_utf8(value)
        if len(encoded) > 65535:
            raise ValueError("a JVM modified UTF-8 constant exceeds 65535 bytes")
        return self.add(("utf8", value), _u1(1) + _u2(len(encoded)) + encoded)

    def string(self, value: str) -> int:
        value_index = self.utf8(value)
        return self.add(("string", value), _u1(8) + _u2(value_index))

    def integer(self, value: int) -> int:
        return self.add(("integer", value), _u1(3) + struct.pack(">i", value))

    def class_(self, name: str) -> int:
        name_index = self.utf8(name)
        return self.add(("class", name), _u1(7) + _u2(name_index))

    def name_and_type(self, name: str, descriptor: str) -> int:
        name_index = self.utf8(name)
        descriptor_index = self.utf8(descriptor)
        return self.add(
            ("name_and_type", name, descriptor),
            _u1(12) + _u2(name_index) + _u2(descriptor_index),
        )

    def method(self, owner: str, name: str, descriptor: str) -> int:
        class_index = self.class_(owner)
        signature_index = self.name_and_type(name, descriptor)
        return self.add(
            ("method", owner, name, descriptor),
            _u1(10) + _u2(class_index) + _u2(signature_index),
        )

    def interface_method(self, owner: str, name: str, descriptor: str) -> int:
        class_index = self.class_(owner)
        signature_index = self.name_and_type(name, descriptor)
        return self.add(
            ("interface_method", owner, name, descriptor),
            _u1(11) + _u2(class_index) + _u2(signature_index),
        )

    def field(self, owner: str, name: str, descriptor: str) -> int:
        class_index = self.class_(owner)
        signature_index = self.name_and_type(name, descriptor)
        return self.add(
            ("field", owner, name, descriptor),
            _u1(9) + _u2(class_index) + _u2(signature_index),
        )

    def long(self, value: int) -> int:
        return self.add(
            ("long", value),
            _u1(5) + struct.pack(">q", value),
            wide=True,
        )

    def double(self, value: float) -> int:
        return self.add(
            ("double", value),
            _u1(6) + struct.pack(">d", value),
            wide=True,
        )

    def render(self) -> bytes:
        output = [_u2(len(self.entries) + 1)]
        output.extend(entry for entry in self.entries if entry is not None)
        return b"".join(output)


class Bytecode:
    """Bytecode buffer with symbolic signed 16-bit branch targets."""

    def __init__(self) -> None:
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.branches: list[tuple[int, str]] = []
        self.line_numbers: list[tuple[int, int]] = []

    def emit(self, opcode: int, operands: bytes = b"") -> None:
        self.code.append(opcode)
        self.code.extend(operands)

    def local(self, opcode: int, index: int) -> None:
        if index <= 255:
            self.emit(opcode, _u1(index))
        else:
            self.emit(0xC4, _u1(opcode) + _u2(index))

    def branch(self, opcode: int, target: str) -> None:
        position = len(self.code)
        self.emit(opcode, b"\x00\x00")
        self.branches.append((position, target))

    def throw_new(self, class_file: ClassFile, class_name: str, *, message: str | None = None) -> None:
        class_index = class_file.constants.class_(class_name)
        self.emit(0xBB, _u2(class_index))
        self.emit(0x59)
        if message is not None:
            value = class_file.constants.string(message)
            self.emit(0x13, _u2(value))
        descriptor = "()V" if message is None else "(Ljava/lang/String;)V"
        constructor = class_file.method_reference(class_name, "<init>", descriptor)
        self.emit(0xB7, _u2(constructor))
        self.emit(0xBF)

    def mark(self, label: str) -> None:
        if label in self.labels:
            raise ValueError(f"duplicate JVM bytecode label: {label}")
        self.labels[label] = len(self.code)

    def line(self, line_number: int | None) -> None:
        if line_number is None or line_number <= 0:
            return
        entry = (len(self.code), line_number)
        if not self.line_numbers or self.line_numbers[-1] != entry:
            self.line_numbers.append(entry)

    def render(self) -> bytes:
        result = bytearray(self.code)
        for position, target in self.branches:
            if target not in self.labels:
                raise ValueError(f"unknown JVM bytecode label: {target}")
            offset = self.labels[target] - position
            result[position + 1:position + 3] = struct.pack(">h", offset)
        return bytes(result)


@dataclass(frozen=True)
class ClassAnnotationValue:
    descriptor: str


@dataclass(frozen=True)
class Annotation:
    descriptor: str
    values: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class TypeAnnotation:
    descriptor: str
    target_type: int
    target_index: int | None = None
    values: tuple[tuple[str, object], ...] = ()
    path: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ExceptionHandler:
    """Half-open protected range and handler bytecode offset."""

    start: int
    end: int
    handler: int
    catch_type: str | None = None


@dataclass(frozen=True)
class Method:
    access: int
    name: str
    descriptor: str
    code: bytes
    max_stack: int
    max_locals: int
    line_numbers: tuple[tuple[int, int], ...] = ()
    annotations: tuple[Annotation, ...] = ()
    type_annotations: tuple[TypeAnnotation, ...] = ()
    exception_handlers: tuple[ExceptionHandler, ...] = ()


@dataclass(frozen=True)
class Field:
    access: int
    name: str
    descriptor: str
    type_annotations: tuple[TypeAnnotation, ...] = ()


@dataclass
class ClassFile:
    name: str
    super_name: str = "java/lang/Object"
    access: int = 0x0031
    source_file: str | None = None
    interfaces: tuple[str, ...] = ()
    annotations: tuple[Annotation, ...] = ()
    constants: ConstantPool = field(default_factory=ConstantPool)
    fields: list[Field] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)

    def method_reference(self, owner: str, name: str, descriptor: str) -> int:
        return self.constants.method(owner, name, descriptor)

    def interface_method_reference(
        self,
        owner: str,
        name: str,
        descriptor: str,
    ) -> int:
        return self.constants.interface_method(owner, name, descriptor)

    def field_reference(self, owner: str, name: str, descriptor: str) -> int:
        return self.constants.field(owner, name, descriptor)

    def long_constant(self, value: int) -> int:
        return self.constants.long(value)

    def double_constant(self, value: float) -> int:
        return self.constants.double(value)

    def add_method(self, method: Method) -> None:
        self.constants.utf8(method.name)
        self.constants.utf8(method.descriptor)
        self.constants.utf8("Code")
        self.methods.append(method)

    def add_field(self, field: Field) -> None:
        self.constants.utf8(field.name)
        self.constants.utf8(field.descriptor)
        self.fields.append(field)

    def render(self) -> bytes:
        this_class = self.constants.class_(self.name)
        super_class = self.constants.class_(self.super_name)
        interfaces = [self.constants.class_(name) for name in self.interfaces]
        rendered_fields = [self.render_field(field) for field in self.fields]
        rendered_methods = [self.render_method(method) for method in self.methods]
        attributes = []
        if self.source_file is not None:
            name = self.constants.utf8("SourceFile")
            source = self.constants.utf8(self.source_file)
            attributes.append(_u2(name) + _u4(2) + _u2(source))
        if self.annotations:
            attributes.append(self.render_annotations(self.annotations))
        return b"".join(
            [
                struct.pack(
                    ">IHH",
                    0xCAFEBABE,
                    0,
                    52
                    if any(field.type_annotations for field in self.fields)
                    or any(method.type_annotations for method in self.methods)
                    else 49,
                ),
                self.constants.render(),
                _u2(self.access),
                _u2(this_class),
                _u2(super_class),
                _u2(len(interfaces)),
                *(_u2(index) for index in interfaces),
                _u2(len(rendered_fields)),
                *rendered_fields,
                _u2(len(rendered_methods)),
                *rendered_methods,
                _u2(len(attributes)),
                *attributes,
            ]
        )

    def render_field(self, field: Field) -> bytes:
        attributes = []
        if field.type_annotations:
            attributes.append(self.render_type_annotations(field.type_annotations))
        return b"".join(
            [
                _u2(field.access),
                _u2(self.constants.utf8(field.name)),
                _u2(self.constants.utf8(field.descriptor)),
                _u2(len(attributes)),
                *attributes,
            ]
        )

    def render_method(self, method: Method) -> bytes:
        code = method.code
        # Valid loops preserve entry depth; each instruction adds at most two
        # slots, and handlers enter with one exception. A byte-length bound
        # avoids reserving 65,535 slots for small methods at JIT transitions,
        # while retaining any tighter maximum supplied by a helper emitter.
        max_stack = min(method.max_stack, 2 * len(code) + 1)
        handlers = []
        for handler in method.exception_handlers:
            if not (
                0 <= handler.start < handler.end <= len(code)
                and 0 <= handler.handler < len(code)
            ):
                raise ValueError("invalid JVM exception handler range")
            catch_type = self.constants.class_(handler.catch_type) if handler.catch_type else 0
            handlers.append(
                _u2(handler.start) + _u2(handler.end)
                + _u2(handler.handler) + _u2(catch_type)
            )
        code_attributes = []
        line_numbers = tuple(
            (offset, line)
            for offset, line in method.line_numbers
            if offset < len(code)
        )
        if line_numbers:
            name = self.constants.utf8("LineNumberTable")
            body = _u2(len(line_numbers)) + b"".join(
                _u2(offset) + _u2(line) for offset, line in line_numbers
            )
            code_attributes.append(_u2(name) + _u4(len(body)) + body)
        code_body = b"".join(
            [
                _u2(max_stack),
                _u2(method.max_locals),
                _u4(len(code)),
                code,
                _u2(len(handlers)),
                *handlers,
                _u2(len(code_attributes)),
                *code_attributes,
            ]
        )
        attributes = [
            _u2(self.constants.utf8("Code"))
            + _u4(len(code_body))
            + code_body
        ]
        if method.annotations:
            attributes.append(self.render_annotations(method.annotations))
        if method.type_annotations:
            attributes.append(self.render_type_annotations(method.type_annotations))
        return b"".join(
            [
                _u2(method.access),
                _u2(self.constants.utf8(method.name)),
                _u2(self.constants.utf8(method.descriptor)),
                _u2(len(attributes)),
                *attributes,
            ]
        )

    def render_annotations(self, annotations: tuple[Annotation, ...]) -> bytes:
        body = _u2(len(annotations)) + b"".join(
            self.render_annotation(annotation) for annotation in annotations
        )
        return (
            _u2(self.constants.utf8("RuntimeVisibleAnnotations"))
            + _u4(len(body))
            + body
        )

    def render_type_annotations(
        self,
        annotations: tuple[TypeAnnotation, ...],
    ) -> bytes:
        body = _u2(len(annotations)) + b"".join(
            self.render_type_annotation(annotation) for annotation in annotations
        )
        return (
            _u2(self.constants.utf8("RuntimeVisibleTypeAnnotations"))
            + _u4(len(body))
            + body
        )

    def render_type_annotation(self, annotation: TypeAnnotation) -> bytes:
        if annotation.target_type in {0x13, 0x14, 0x15}:
            target = b""
        elif annotation.target_type == 0x16 and annotation.target_index is not None:
            target = _u1(annotation.target_index)
        else:
            raise ValueError(
                f"unsupported JVM type-annotation target "
                f"{annotation.target_type:#04x}"
            )
        path = _u1(len(annotation.path)) + b"".join(
            _u1(kind) + _u1(index) for kind, index in annotation.path
        )
        value = Annotation(annotation.descriptor, annotation.values)
        return (
            _u1(annotation.target_type)
            + target
            + path
            + self.render_annotation(value)
        )

    def render_annotation(self, annotation: Annotation) -> bytes:
        values = []
        for name, value in annotation.values:
            rendered = self.render_annotation_value(value)
            values.append(_u2(self.constants.utf8(name)) + rendered)
        return b"".join(
            [
                _u2(self.constants.utf8(annotation.descriptor)),
                _u2(len(values)),
                *values,
            ]
        )

    def render_annotation_value(self, value: object) -> bytes:
        if isinstance(value, ClassAnnotationValue):
            return b"c" + _u2(self.constants.utf8(value.descriptor))
        if isinstance(value, str):
            return b"s" + _u2(self.constants.utf8(value))
        if isinstance(value, int):
            return b"I" + _u2(self.constants.integer(value))
        if isinstance(value, tuple):
            return b"[" + _u2(len(value)) + b"".join(
                self.render_annotation_value(item) for item in value
            )
        raise TypeError(f"unsupported JVM annotation value {value!r}")

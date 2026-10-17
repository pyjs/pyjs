"""Read JVM declarations lazily from class directories and archives."""

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Self


class JVMClassFormatError(ValueError):
    pass


@dataclass(frozen=True)
class JVMAnnotation:
    descriptor: str
    values: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class JVMTypeAnnotation:
    descriptor: str
    values: tuple[tuple[str, object], ...] = ()
    path: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class JVMParameter:
    descriptor: str
    name: str | None = None
    annotations: tuple[JVMAnnotation, ...] = ()
    type_annotations: tuple[JVMTypeAnnotation, ...] = ()


@dataclass(frozen=True)
class JVMField:
    name: str
    descriptor: str
    access: int
    signature: str | None = None
    constant: object | None = None
    annotations: tuple[JVMAnnotation, ...] = ()
    type_annotations: tuple[JVMTypeAnnotation, ...] = ()


@dataclass(frozen=True)
class JVMMethod:
    name: str
    descriptor: str
    access: int
    parameters: tuple[JVMParameter, ...]
    return_descriptor: str
    signature: str | None = None
    exceptions: tuple[str, ...] = ()
    annotations: tuple[JVMAnnotation, ...] = ()
    type_annotations: tuple[JVMTypeAnnotation, ...] = ()


@dataclass(frozen=True)
class JVMClass:
    name: str
    access: int
    super_name: str | None
    interfaces: tuple[str, ...]
    fields: tuple[JVMField, ...]
    methods: tuple[JVMMethod, ...]
    signature: str | None = None
    annotations: tuple[JVMAnnotation, ...] = ()

    def declared_methods(self, name: str) -> tuple[JVMMethod, ...]:
        return tuple(method for method in self.methods if method.name == name)

    def declared_field(self, name: str) -> JVMField | None:
        return next((field for field in self.fields if field.name == name), None)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise JVMClassFormatError("truncated JVM class file")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u1(self) -> int:
        return self.read(1)[0]

    def u2(self) -> int:
        return struct.unpack(">H", self.read(2))[0]

    def u4(self) -> int:
        return struct.unpack(">I", self.read(4))[0]


def _decode_modified_utf8(value: bytes) -> str:
    units = bytearray()
    offset = 0
    while offset < len(value):
        first = value[offset]
        offset += 1
        if first & 0x80 == 0:
            if first == 0:
                raise JVMClassFormatError("invalid null byte in modified UTF-8")
            unit = first
        elif first & 0xE0 == 0xC0:
            if offset >= len(value):
                raise JVMClassFormatError("truncated modified UTF-8 sequence")
            second = value[offset]
            offset += 1
            if second & 0xC0 != 0x80:
                raise JVMClassFormatError("invalid modified UTF-8 continuation")
            unit = (first & 0x1F) << 6 | second & 0x3F
        elif first & 0xF0 == 0xE0:
            if offset + 1 >= len(value):
                raise JVMClassFormatError("truncated modified UTF-8 sequence")
            second, third = value[offset:offset + 2]
            offset += 2
            if second & 0xC0 != 0x80 or third & 0xC0 != 0x80:
                raise JVMClassFormatError("invalid modified UTF-8 continuation")
            unit = (first & 0x0F) << 12 | (second & 0x3F) << 6 | third & 0x3F
        else:
            raise JVMClassFormatError("invalid modified UTF-8 leading byte")
        units.extend(struct.pack(">H", unit))
    return units.decode("utf-16-be", errors="surrogatepass")


class _ConstantPool:
    def __init__(self, reader: _Reader) -> None:
        count = reader.u2()
        self.entries: list[tuple[int, object] | None] = [None] * count
        index = 1
        while index < count:
            tag = reader.u1()
            if tag == 1:
                value: object = _decode_modified_utf8(reader.read(reader.u2()))
            elif tag == 3:
                value = struct.unpack(">i", reader.read(4))[0]
            elif tag == 4:
                value = struct.unpack(">f", reader.read(4))[0]
            elif tag == 5:
                value = struct.unpack(">q", reader.read(8))[0]
            elif tag == 6:
                value = struct.unpack(">d", reader.read(8))[0]
            elif tag in {7, 8, 16, 19, 20}:
                value = reader.u2()
            elif tag in {9, 10, 11, 12, 17, 18}:
                value = (reader.u2(), reader.u2())
            elif tag == 15:
                value = (reader.u1(), reader.u2())
            else:
                raise JVMClassFormatError(f"unknown JVM constant-pool tag {tag}")
            self.entries[index] = (tag, value)
            index += 2 if tag in {5, 6} else 1

    def entry(self, index: int) -> tuple[int, object]:
        if index <= 0 or index >= len(self.entries):
            raise JVMClassFormatError(f"invalid JVM constant-pool index {index}")
        entry = self.entries[index]
        if entry is None:
            raise JVMClassFormatError(f"invalid JVM constant-pool slot {index}")
        return entry

    def utf8(self, index: int) -> str:
        tag, value = self.entry(index)
        if tag != 1 or not isinstance(value, str):
            raise JVMClassFormatError(f"JVM constant {index} is not UTF-8")
        return value

    def class_name(self, index: int) -> str:
        tag, value = self.entry(index)
        if tag != 7 or not isinstance(value, int):
            raise JVMClassFormatError(f"JVM constant {index} is not a class")
        return self.utf8(value)

    def constant(self, index: int) -> object:
        tag, value = self.entry(index)
        if tag in {3, 4, 5, 6}:
            return value
        if tag == 8 and isinstance(value, int):
            return self.utf8(value)
        raise JVMClassFormatError(f"JVM constant {index} is not a literal")


def _attributes(reader: _Reader, pool: _ConstantPool) -> dict[str, list[bytes]]:
    attributes: dict[str, list[bytes]] = {}
    for _ in range(reader.u2()):
        name = pool.utf8(reader.u2())
        attributes.setdefault(name, []).append(reader.read(reader.u4()))
    return attributes


def _single_utf8(
    attributes: dict[str, list[bytes]],
    name: str,
    pool: _ConstantPool,
) -> str | None:
    values = attributes.get(name, ())
    if not values:
        return None
    if len(values) != 1 or len(values[0]) != 2:
        raise JVMClassFormatError(f"invalid JVM {name} attribute")
    return pool.utf8(_Reader(values[0]).u2())


def _annotation_value(reader: _Reader, pool: _ConstantPool) -> object:
    tag = chr(reader.u1())
    if tag in "BCDFIJSZ":
        return pool.constant(reader.u2())
    if tag == "s":
        return pool.utf8(reader.u2())
    if tag == "e":
        return (pool.utf8(reader.u2()), pool.utf8(reader.u2()))
    if tag == "c":
        return pool.utf8(reader.u2())
    if tag == "@":
        return _annotation(reader, pool)
    if tag == "[":
        return tuple(_annotation_value(reader, pool) for _ in range(reader.u2()))
    raise JVMClassFormatError(f"unknown JVM annotation value tag {tag!r}")


def _annotation(reader: _Reader, pool: _ConstantPool) -> JVMAnnotation:
    descriptor = pool.utf8(reader.u2())
    values = tuple(
        (pool.utf8(reader.u2()), _annotation_value(reader, pool))
        for _ in range(reader.u2())
    )
    return JVMAnnotation(descriptor, values)


def _annotations(
    attributes: dict[str, list[bytes]],
    pool: _ConstantPool,
) -> tuple[JVMAnnotation, ...]:
    result = []
    for name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
        for value in attributes.get(name, ()):
            reader = _Reader(value)
            result.extend(_annotation(reader, pool) for _ in range(reader.u2()))
            if reader.offset != len(value):
                raise JVMClassFormatError(f"trailing data in JVM {name} attribute")
    return tuple(result)


def _parameter_annotations(
    attributes: dict[str, list[bytes]],
    pool: _ConstantPool,
) -> list[list[JVMAnnotation]]:
    result: list[list[JVMAnnotation]] = []
    for name in (
        "RuntimeVisibleParameterAnnotations",
        "RuntimeInvisibleParameterAnnotations",
    ):
        for value in attributes.get(name, ()):
            reader = _Reader(value)
            count = reader.u1()
            while len(result) < count:
                result.append([])
            for index in range(count):
                result[index].extend(
                    _annotation(reader, pool) for _ in range(reader.u2())
                )
            if reader.offset != len(value):
                raise JVMClassFormatError(f"trailing data in JVM {name} attribute")
    return result


def _type_annotation_target(reader: _Reader) -> tuple[int, int | None]:
    target_type = reader.u1()
    target_index = None
    if target_type in {0x00, 0x01}:
        reader.u1()
    elif target_type == 0x10:
        reader.u2()
    elif target_type in {0x11, 0x12}:
        reader.read(2)
    elif target_type in {0x13, 0x14, 0x15}:
        pass
    elif target_type == 0x16:
        target_index = reader.u1()
    elif target_type == 0x17:
        reader.u2()
    elif target_type in {0x40, 0x41}:
        reader.read(reader.u2() * 6)
    elif target_type == 0x42:
        reader.u2()
    elif 0x43 <= target_type <= 0x46:
        reader.u2()
    elif 0x47 <= target_type <= 0x4B:
        reader.read(3)
    else:
        raise JVMClassFormatError(
            f"unknown JVM type-annotation target {target_type:#04x}"
        )
    return target_type, target_index


def _type_annotations(
    attributes: dict[str, list[bytes]],
    pool: _ConstantPool,
) -> tuple[tuple[int, int | None, JVMTypeAnnotation], ...]:
    result = []
    for name in (
        "RuntimeVisibleTypeAnnotations",
        "RuntimeInvisibleTypeAnnotations",
    ):
        for value in attributes.get(name, ()):
            reader = _Reader(value)
            for _ in range(reader.u2()):
                target_type, target_index = _type_annotation_target(reader)
                path = tuple((reader.u1(), reader.u1()) for _ in range(reader.u1()))
                annotation = _annotation(reader, pool)
                result.append(
                    (
                        target_type,
                        target_index,
                        JVMTypeAnnotation(
                            annotation.descriptor,
                            annotation.values,
                            path,
                        ),
                    )
                )
            if reader.offset != len(value):
                raise JVMClassFormatError(f"trailing data in JVM {name} attribute")
    return tuple(result)


def parse_jvm_method_descriptor(
    descriptor: str,
) -> tuple[tuple[str, ...], str]:
    """Split one JVM method descriptor into parameters and its result."""
    if not descriptor.startswith("("):
        raise JVMClassFormatError(f"invalid JVM method descriptor {descriptor!r}")

    def consume(offset: int, *, allow_void: bool = False) -> tuple[str, int]:
        start = offset
        while offset < len(descriptor) and descriptor[offset] == "[":
            offset += 1
        if offset >= len(descriptor):
            raise JVMClassFormatError(f"invalid JVM method descriptor {descriptor!r}")
        marker = descriptor[offset]
        if marker == "L":
            end = descriptor.find(";", offset)
            if end < 0:
                raise JVMClassFormatError(f"invalid JVM method descriptor {descriptor!r}")
            offset = end + 1
        elif marker in "BCDFIJSZ" or allow_void and marker == "V" and offset == start:
            offset += 1
        else:
            raise JVMClassFormatError(f"invalid JVM method descriptor {descriptor!r}")
        return descriptor[start:offset], offset

    parameters = []
    offset = 1
    while offset < len(descriptor) and descriptor[offset] != ")":
        parameter, offset = consume(offset)
        parameters.append(parameter)
    if offset >= len(descriptor) or descriptor[offset] != ")":
        raise JVMClassFormatError(f"invalid JVM method descriptor {descriptor!r}")
    result, offset = consume(offset + 1, allow_void=True)
    if offset != len(descriptor):
        raise JVMClassFormatError(f"invalid JVM method descriptor {descriptor!r}")
    return tuple(parameters), result


def _parameter_slots(descriptors: tuple[str, ...], access: int) -> tuple[int, ...]:
    slot = 0 if access & 0x0008 else 1
    result = []
    for descriptor in descriptors:
        result.append(slot)
        slot += 2 if descriptor in {"J", "D"} else 1
    return tuple(result)


def _local_parameter_names(
    attributes: dict[str, list[bytes]],
    pool: _ConstantPool,
) -> dict[int, str]:
    names = {}
    for code in attributes.get("Code", ()):
        reader = _Reader(code)
        reader.read(2 + 2)
        reader.read(reader.u4())
        reader.read(reader.u2() * 8)
        nested = _attributes(reader, pool)
        for table in nested.get("LocalVariableTable", ()):
            table_reader = _Reader(table)
            for _ in range(table_reader.u2()):
                start = table_reader.u2()
                table_reader.read(2)
                name = pool.utf8(table_reader.u2())
                table_reader.read(2)
                slot = table_reader.u2()
                if start == 0 and name != "this":
                    names.setdefault(slot, name)
    return names


def _method_parameters(
    descriptor: str,
    access: int,
    attributes: dict[str, list[bytes]],
    pool: _ConstantPool,
    type_annotations: tuple[tuple[int, int | None, JVMTypeAnnotation], ...],
) -> tuple[JVMParameter, ...]:
    descriptors, _ = parse_jvm_method_descriptor(descriptor)
    names: list[str | None] = [None] * len(descriptors)
    method_parameters = attributes.get("MethodParameters", ())
    if method_parameters:
        if len(method_parameters) != 1:
            raise JVMClassFormatError("duplicate JVM MethodParameters attribute")
        reader = _Reader(method_parameters[0])
        count = reader.u1()
        if count != len(descriptors):
            raise JVMClassFormatError("JVM method parameter count does not match descriptor")
        for index in range(count):
            name_index = reader.u2()
            names[index] = pool.utf8(name_index) if name_index else None
            reader.read(2)
    local_names = _local_parameter_names(attributes, pool)
    for index, slot in enumerate(_parameter_slots(descriptors, access)):
        if names[index] is None:
            names[index] = local_names.get(slot)
    annotations = _parameter_annotations(attributes, pool)
    return tuple(
        JVMParameter(
            descriptor=parameter,
            name=names[index],
            annotations=tuple(annotations[index]) if index < len(annotations) else (),
            type_annotations=tuple(
                annotation
                for target_type, target_index, annotation in type_annotations
                if target_type == 0x16 and target_index == index
            ),
        )
        for index, parameter in enumerate(descriptors)
    )


def _exceptions(
    attributes: dict[str, list[bytes]],
    pool: _ConstantPool,
) -> tuple[str, ...]:
    values = attributes.get("Exceptions", ())
    if not values:
        return ()
    if len(values) != 1:
        raise JVMClassFormatError("duplicate JVM Exceptions attribute")
    reader = _Reader(values[0])
    return tuple(pool.class_name(reader.u2()) for _ in range(reader.u2()))


def read_jvm_class(data: bytes) -> JVMClass:
    reader = _Reader(data)
    if reader.u4() != 0xCAFEBABE:
        raise JVMClassFormatError("invalid JVM class-file magic")
    reader.read(2 + 2)
    pool = _ConstantPool(reader)
    access = reader.u2()
    name = pool.class_name(reader.u2())
    super_index = reader.u2()
    super_name = pool.class_name(super_index) if super_index else None
    interfaces = tuple(pool.class_name(reader.u2()) for _ in range(reader.u2()))

    fields = []
    for _ in range(reader.u2()):
        field_access = reader.u2()
        field_name = pool.utf8(reader.u2())
        descriptor = pool.utf8(reader.u2())
        attributes = _attributes(reader, pool)
        constants = attributes.get("ConstantValue", ())
        if len(constants) > 1:
            raise JVMClassFormatError("duplicate JVM ConstantValue attribute")
        constant = (
            pool.constant(_Reader(constants[0]).u2()) if constants else None
        )
        fields.append(
            JVMField(
                name=field_name,
                descriptor=descriptor,
                access=field_access,
                signature=_single_utf8(attributes, "Signature", pool),
                constant=constant,
                annotations=_annotations(attributes, pool),
                type_annotations=tuple(
                    annotation
                    for target_type, _target_index, annotation in _type_annotations(
                        attributes,
                        pool,
                    )
                    if target_type == 0x13
                ),
            )
        )

    methods = []
    for _ in range(reader.u2()):
        method_access = reader.u2()
        method_name = pool.utf8(reader.u2())
        descriptor = pool.utf8(reader.u2())
        attributes = _attributes(reader, pool)
        type_annotations = _type_annotations(attributes, pool)
        _, return_descriptor = parse_jvm_method_descriptor(descriptor)
        methods.append(
            JVMMethod(
                name=method_name,
                descriptor=descriptor,
                access=method_access,
                parameters=_method_parameters(
                    descriptor,
                    method_access,
                    attributes,
                    pool,
                    type_annotations,
                ),
                return_descriptor=return_descriptor,
                signature=_single_utf8(attributes, "Signature", pool),
                exceptions=_exceptions(attributes, pool),
                annotations=_annotations(attributes, pool),
                type_annotations=tuple(
                    annotation
                    for target_type, _target_index, annotation in type_annotations
                    if target_type == 0x14
                ),
            )
        )

    attributes = _attributes(reader, pool)
    if reader.offset != len(data):
        raise JVMClassFormatError("trailing data after JVM class file")
    return JVMClass(
        name=name,
        access=access,
        super_name=super_name,
        interfaces=interfaces,
        fields=tuple(fields),
        methods=tuple(methods),
        signature=_single_utf8(attributes, "Signature", pool),
        annotations=_annotations(attributes, pool),
    )


class JVMClasspath:
    """Resolve classes lazily from ordered directories and JAR or ZIP files."""

    def __init__(self, *roots: Path) -> None:
        self.roots = tuple(Path(root) for root in roots)
        self._archives: dict[Path, zipfile.ZipFile] = {}
        self._classes: dict[str, JVMClass | None] = {}

    def find_class(self, name: str) -> JVMClass | None:
        internal_name = name.removesuffix(".class").replace(".", "/")
        if internal_name in self._classes:
            return self._classes[internal_name]
        relative = internal_name + ".class"
        data = None
        for root in self.roots:
            if root.is_dir():
                candidate = root / relative
                if candidate.is_file():
                    data = candidate.read_bytes()
                    break
            elif root.is_file():
                archive = self._archives.get(root)
                if archive is None:
                    archive = zipfile.ZipFile(root)
                    self._archives[root] = archive
                try:
                    data = archive.read(relative)
                except KeyError:
                    continue
                break
        value = read_jvm_class(data) if data is not None else None
        self._classes[internal_name] = value
        return value

    def require_class(self, name: str) -> JVMClass:
        value = self.find_class(name)
        if value is None:
            raise LookupError(f"JVM class {name!r} was not found on the classpath")
        return value

    def close(self) -> None:
        for archive in self._archives.values():
            archive.close()
        self._archives.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = [
    "JVMAnnotation",
    "JVMClass",
    "JVMClassFormatError",
    "JVMClasspath",
    "JVMField",
    "JVMMethod",
    "JVMParameter",
    "JVMTypeAnnotation",
    "parse_jvm_method_descriptor",
    "read_jvm_class",
]

"""Generate, compile, execute, and compare direct LLVM programs."""

import ctypes
import errno
import operator
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pyjs.analysis.source import create_module
from pyjs.native.llvm import (
    LLVMABIParameter,
    LLVMABIType,
    transpile_llvm,
    transpile_llvm_module,
)
from pyjs.native.platform import binary_suffix
from pyjs.native.runtime.mappings import _Dict as _LLVMDictionary
from pyjs.native.tagged import TAGS
from pyjs.numeric import NumericFormat

from .command import CommandRunner

# LLVM comments/quoted identifiers can contain keywords and punctuation. Share
# tokenization between the two tooling-only scans instead of matching lines.
_LLVM_TOKENS = re.compile(r';[^\n]*|[@%!$]?"[^"]*":?|[@%!]\d+|[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|i\d+|[@%!$]?[-\w.$]+:?|[^\s]')


def _windows_exported_ir(source: str) -> str:
    """Mark public definitions for export; LLVM owns COFF names/directives."""
    fragments, copied, insertion = [], 0, None
    previous, qualifiers, function = "", set(), False
    prefixes = {"external", "available_externally", "linkonce", "weak", "common",
                "appending", "internal", "private", "extern_weak", "linkonce_odr",
                "weak_odr", "dso_local", "dso_preemptable", "default", "hidden", "protected"}
    # LLVM forbids dllexport on hidden visibility, even with external linkage.
    excluded = {"internal", "private", "hidden", "available_externally", "extern_weak", "appending"}
    for match in _LLVM_TOKENS.finditer(source):
        token = match.group()
        if token.startswith(";"):
            continue
        if insertion is not None:
            if token in prefixes:
                qualifiers.add(token)
                insertion = match.end()
            else:
                declaration = not function and "external" in qualifiers
                if not declaration and not qualifiers & excluded and token not in {"dllimport", "dllexport"}:
                    fragments.extend((source[copied:insertion], " dllexport "))
                    copied = insertion
                insertion = None
        if token == "define" or token == "=" and previous.startswith("@"):
            insertion, qualifiers = match.end(), set()
            function = token == "define"
        previous = token
    fragments.append(source[copied:])
    return "".join(fragments)


def _address_sanitized_ir(source: str) -> str:
    """Clang's IR-input mode links ASan but does not mark function bodies.

    Insert the LLVM function attribute immediately after the parameter list,
    including multiline headers and parameter attributes with parentheses.
    Scan tokens, not lines: LLVM permits a declaration and definition on the
    same line. Quoted identifiers and comments can contain arbitrary keywords
    and parentheses. Declarations stay untouched; no full IR parser is needed.
    """
    fragments, previous = [], 0
    # LLVM quotes end at the next quote: embedded quotes use hex escapes,
    # not Python/C backslash-quote. Numerals and iN integer types end at
    # their last digit and can directly precede a keyword (e.g. i32define).
    # Sigils are prefixes, not identifier characters: void@f is two tokens.
    tokens = _LLVM_TOKENS.finditer(source)
    header, parameters, depth = False, False, 0
    insertion, qualifier = None, 0
    for match in tokens:
        token = match.group()
        if token.startswith(";"):
            continue
        if insertion is not None:
            # Address qualifiers precede function attributes. Consume them
            # with the same lexer, never a regex that can backtrack into a
            # comment and insert the attribute inside that comment.
            if qualifier:
                valid = token == "(" if qualifier == 1 else token.isdecimal() if qualifier == 2 else token == ")"
                if not valid:
                    raise ValueError("cannot locate LLVM function address qualifier for ASan instrumentation")
                qualifier = qualifier + 1 if qualifier < 3 else 0
                insertion = match.end()
                continue
            if token in {"unnamed_addr", "local_unnamed_addr"}:
                insertion = match.end()
                continue
            if token == "addrspace":
                qualifier = 1
                continue
            # ')' is already a token boundary; the inserted word is not.
            # Keep a following glued attribute (e.g. nounwind) separate.
            separator = "" if source[insertion].isspace() else " "
            fragments.extend((source[previous:insertion], " sanitize_address" + separator))
            previous, insertion = insertion, None
        if depth:
            depth += (token == "(") - (token == ")")
            if not depth:
                insertion = match.end()
                header = parameters = False
        elif parameters:
            if token != "(":
                raise ValueError("cannot locate every LLVM function parameter list for ASan instrumentation")
            depth = 1
        elif token == "define":
            if header:
                raise ValueError("cannot locate every LLVM function parameter list for ASan instrumentation")
            header = True
        elif header and token.startswith("@"):
            parameters = True
    # Raw IR is also a public tooling input. An unfamiliar header must fail
    # closed instead of producing an apparently sanitized uninstrumented body.
    if depth:
        raise ValueError("unterminated LLVM function parameters")
    if header:
        raise ValueError("cannot locate every LLVM function parameter list for ASan instrumentation")
    if qualifier:
        raise ValueError("unterminated LLVM function address qualifier")
    if insertion is not None:
        fragments.extend((source[previous:insertion], " sanitize_address"))
        previous = insertion
    fragments.append(source[previous:])
    return "".join(fragments)


@dataclass(frozen=True)
class LLVMExecution:
    """One completed native execution and the IR used to build it."""

    llvm_ir: str
    returncode: int
    stdout: str
    stderr: str
    artifacts: Path | None = None


@dataclass(frozen=True)
class LLVMComparison:
    """The same Python source executed by CPython and native LLVM."""

    python: LLVMExecution
    native: LLVMExecution

    @property
    def matches(self) -> bool:
        return (
            self.native.returncode >= 0
            and self.python.returncode == self.native.returncode
            and self.python.stdout == self.native.stdout
        )


@dataclass(frozen=True)
class LLVMRenderComparison:
    """Text produced by the same arguments under CPython and native LLVM."""

    python: str
    native: str
    library: LLVMLibrary

    @property
    def matches(self) -> bool:
        return self.python == self.native


class _LLVMString(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int64), ("data", ctypes.c_void_p)]


class _LLVMList(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_int64),
        ("capacity", ctypes.c_int64),
        ("data", ctypes.c_void_p),
        ("allocator", ctypes.c_void_p),
        ("allocator_context", ctypes.c_void_p),
        ("hash_cache", ctypes.c_int64),
    ]


class _LLVMOptionalBool(ctypes.Structure):
    _fields_ = [("present", ctypes.c_bool), ("value", ctypes.c_bool)]


class _LLVMOptionalInt(ctypes.Structure):
    _fields_ = [("present", ctypes.c_bool), ("value", ctypes.c_int64)]


class _LLVMOptionalFloat(ctypes.Structure):
    _fields_ = [("present", ctypes.c_bool), ("value", ctypes.c_double)]


class _LLVMTagged(ctypes.Structure):
    _fields_ = [("tag", ctypes.c_int64), ("value", ctypes.c_uint64)]


_OPTIONAL_SCALARS = {"bool": _LLVMOptionalBool, "int": _LLVMOptionalInt, "float": _LLVMOptionalFloat}
_UNION_INPUT_KINDS = (
    (type(None), "NoneType"), (bool, "bool"), (int, "int"), (float, "float"),
    (str, "str"), (bytes, "bytes"), (list, "list"), (tuple, "tuple"),
    (Mapping, "dict"), (set, "set"), (frozenset, "frozenset"),
)


def _llvm_ctype(value_type: LLVMABIType, definitions=()):
    value_type = value_type.resolve(definitions)
    if value_type.kind == "union":
        return _LLVMTagged
    if value_type.kind == "optional":
        return _OPTIONAL_SCALARS.get(value_type.item_type.resolve(definitions).kind, ctypes.c_void_p)
    if value_type.kind == "bool":
        return ctypes.c_bool
    if value_type.kind == "int":
        if value_type.numeric_format is not None:
            return _numeric_ctype(value_type.numeric_format)
        return ctypes.c_int64
    if value_type.kind == "float":
        if value_type.numeric_format is not None:
            return _numeric_ctype(value_type.numeric_format)
        return ctypes.c_double
    return ctypes.c_void_p


def _numeric_ctype(value: NumericFormat):
    if value.kind == "float":
        return ctypes.c_float if value.bits == 32 else ctypes.c_double
    prefix = "c_int" if value.signed else "c_uint"
    return getattr(ctypes, f"{prefix}{value.bits}")


def _llvm_host_class(value_type):
    if isinstance(value_type.host_model, str):
        from datetime import date, datetime, timedelta
        from uuid import UUID
        return {"date": date, "datetime": datetime, "timedelta": timedelta,
                "UUID": UUID}[value_type.host_model]
    return value_type.host_model or value_type.host_class


class _LLVMArguments:
    """Own call-scoped input views until one native renderer call completes."""

    def __init__(
        self,
        structures: dict[LLVMABIType, type[ctypes.Structure]],
        definitions: tuple[LLVMABIType, ...] = (),
    ) -> None:
        self.keepalive = []
        self.structures = structures
        self.definitions = definitions
        self.views = {}

    def marshal(self, value_type: LLVMABIType, value, path: str):
        value_type = value_type.resolve(self.definitions)
        if value_type.kind not in {"str", "bytes", "list", "tuple", "dict", "set", "frozenset", "object"}:
            return self._marshal(value_type, value, path)
        key = (value_type, id(value))
        if key not in self.views:
            # The identity key must not outlive the original object: user
            # properties/iterators can produce otherwise temporary values.
            self.keepalive.append(value)
            self.views[key] = self._marshal(value_type, value, path)
        return self.views[key]

    def shell(self, value_type, value, result):
        """Publish a retained container before descending into its members.

        No native call occurs until the whole graph validates. If a child fails,
        this call-scoped owner discards every partial shell together.
        """
        pointer = ctypes.addressof(result)
        self.views[value_type, id(value)] = pointer
        self.keepalive.append(result)
        return pointer

    def key_value(self, value_type, value):
        """Recover the normalized builtin key, never call a host key override.

        The converted storage is authoritative: portable widths can merge keys,
        and pointer identities are not string equality. Application/tuple key
        inputs are rejected by the ABI before reaching this scalar boundary.
        """
        value_type = value_type.resolve(self.definitions)
        if value_type.kind == "union":
            kind = next(name for name, tag in TAGS.items() if tag == value.tag)
            if kind == "int":
                return ctypes.c_int64(value.value).value
            if kind == "float":
                return struct.unpack("d", struct.pack("Q", value.value))[0]
            if kind == "bool":
                return bool(value.value)
            return self.key_value(LLVMABIType(kind, kind), value.value)
        if value_type.kind == "optional":
            member = value_type.item_type.resolve(self.definitions)
            if member.kind in _OPTIONAL_SCALARS:
                return self.key_value(member, value.value) if value.present else None
            return self.key_value(member, value) if value else None
        if value_type.kind == "NoneType":
            return None
        if value_type.kind in {"str", "bytes"}:
            text = _LLVMString.from_address(value)
            raw = ctypes.string_at(text.data, text.length)
            return raw.decode("utf-8") if value_type.kind == "str" else raw
        return value

    @staticmethod
    def key_hash(value):
        # Run the same Python-authored algorithms that LLVM compiles. Host hash()
        # is randomized for strings and uses object identity for NaN.
        from pyjs.native.runtime import algorithms, hashing

        if value is None:
            return hashing.NONE_HASH
        if isinstance(value, (bool, int)):
            return hashing.integer(int(value))
        if isinstance(value, float):
            return hashing.floating(value)
        return algorithms.bytes_hash(value.encode("utf-8") if isinstance(value, str) else value)

    def _marshal(self, value_type: LLVMABIType, value, path: str):
        if value_type.kind == "union":
            # Select by Python kind, never by conversion or trying each shape:
            # int -> float would change a union's observable runtime tag.
            member = next((item for item in value_type.members
                           if item.kind == "object" and type(value) is _llvm_host_class(item)), None)
            kind = "object" if member else next((name for cls, name in _UNION_INPUT_KINDS if isinstance(value, cls)), None)
            if member is None:
                member = next((item for item in value_type.members if item.kind == kind), None)
            if member is None and kind == "bool" and any(item.kind == "int" for item in value_type.members):
                member = LLVMABIType("bool", "bool")  # int arms admit bool without erasing its tag.
            if member is None:
                expected = " | ".join(item.name if item.kind == "object" else item.kind
                                      for item in value_type.members)
                raise TypeError(f"{path} must match {expected}, not {type(value).__name__}")
            payload = self.marshal(member, value, path)
            if kind == "float":
                payload = struct.unpack("Q", struct.pack("d", payload))[0]
            elif kind == "int":
                payload = int.__and__(payload, (1 << 64) - 1)
            return _LLVMTagged(member.runtime_tag if member.runtime_tag is not None else TAGS[kind], payload or 0)
        if value_type.kind == "NoneType":
            if value is not None:
                raise TypeError(f"{path} must be None, not {type(value).__name__}")
            return None
        if value_type.kind == "optional":
            member = value_type.item_type.resolve(self.definitions)
            scalar = _OPTIONAL_SCALARS.get(member.kind)
            if scalar is not None:
                if value is None:
                    return scalar()
                payload = self.marshal(member, value, path)
                return scalar(True, payload)
            return None if value is None else self.marshal(member, value, path)
        if value_type.kind == "bool":
            if not isinstance(value, bool):
                raise TypeError(f"{path} must be bool, not {type(value).__name__}")
            return value
        if value_type.kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{path} must be int, not {type(value).__name__}")
            if not -(1 << 63) <= value < 1 << 63:
                raise OverflowError(f"{path} does not fit the native signed 64-bit ABI")
            return _numeric_ctype(value_type.normalization_format)(value).value if value_type.normalization_format else value
        if value_type.kind == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{path} must be float, not {type(value).__name__}")
            # Finish ctypes conversion here: an int subclass may run __float__,
            # which must not be deferred until _render holds the library lock.
            ctype = _numeric_ctype(value_type.normalization_format) if value_type.normalization_format else ctypes.c_double
            return ctype(value).value
        if value_type.kind in {"str", "bytes"}:
            expected = str if value_type.kind == "str" else bytes
            if not isinstance(value, expected):
                raise TypeError(f"{path} must be {value_type.kind}, not {type(value).__name__}")
            encoded = str.encode(value, "utf-8") if value_type.kind == "str" else value
            data = ctypes.create_string_buffer(encoded or b"\0")
            result = _LLVMString(len(encoded), ctypes.addressof(data))
            self.keepalive.extend((data, result))
            return ctypes.addressof(result)
        if value_type.kind == "list" or value_type.kind == "tuple" and value_type.item_type is not None:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise TypeError(
                    f"{path} must be a sequence, not {type(value).__name__}"
                )
            assert value_type.item_type is not None
            item_ctype = _llvm_ctype(value_type.item_type, self.definitions)
            items = (item_ctype * len(value))()
            result = _LLVMList(len(value), len(value), ctypes.addressof(items), None, None)
            pointer = self.shell(value_type, value, result)
            self.keepalive.append(items)
            for index, item in enumerate(value):
                items[index] = self.marshal(value_type.item_type, item, f"{path}[{index}]")
            return pointer
        if value_type.kind in {"dict", "set", "frozenset"}:
            mapping = value_type.kind == "dict"
            expected = Mapping if mapping else (set, frozenset)
            if not isinstance(value, expected):
                raise TypeError(f"{path} must be a {value_type.kind}, not {type(value).__name__}")
            key_type = value_type.key_type if mapping else value_type.item_type
            item_type = value_type.item_type if mapping else LLVMABIType("bool", "bool")
            result = _LLVMDictionary()
            pointer = self.shell(value_type, value, result)
            entries = {}
            for index, key in enumerate(value):
                converted_key = self.marshal(key_type, key, f"{path} key {index}")
                converted_value = self.marshal(item_type, value[key], f"{path}[{key!r}]") if mapping else True
                # Representation normalization can merge keys (e.g. 1 and 257
                # under int8). Preserve first position and last value like dict.
                identity = self.key_value(key_type, converted_key)
                previous = entries.get(identity)
                if previous is not None:
                    converted_key = previous[0]
                entries[identity] = (converted_key, converted_value)
            keys = (_llvm_ctype(key_type, self.definitions) * len(entries))(*(item[0] for item in entries.values()))
            values = (_llvm_ctype(item_type, self.definitions) * len(entries))(*(item[1] for item in entries.values()))
            result.length = result.capacity = len(entries)
            result.keys, result.values = ctypes.addressof(keys), ctypes.addressof(values)
            self.keepalive.extend((keys, values))
            if key_type.resolve(self.definitions).kind == "union":
                hashes = (ctypes.c_int64 * len(entries))(*(self.key_hash(key) for key in entries))
                result.hashes = ctypes.addressof(hashes)
                self.keepalive.append(hashes)
            return pointer
        if value_type.kind in {"tuple", "object"}:
            if value_type.host_model is not None:
                from datetime import datetime
                expected = _llvm_host_class(value_type)
                # A structural copy cannot preserve subclass methods or a
                # timezone. Do not silently turn either into a naive value.
                if type(value) is not expected:
                    raise TypeError(f"{path} must be an exact {expected.__name__} value")
                if expected is datetime and value.tzinfo is not None:
                    raise TypeError(f"{path} must be a naive datetime without tzinfo")
            structure = self.structure(value_type)
            if value_type.kind == "tuple":
                if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                    raise TypeError(
                        f"{path} must be a sequence, not {type(value).__name__}"
                    )
                if len(value) != len(value_type.fields):
                    raise TypeError(
                        f"{path} must contain {len(value_type.fields)} values, "
                        f"got {len(value)}"
                    )
                values = value
                paths = tuple(
                    f"{path}[{index}]" for index in range(len(value_type.fields))
                )
            else:
                # Read each field only when its nested conversion is reached.
                # Eager snapshots reorder observable getters and read later
                # fields even when an earlier child fails validation.
                values = (
                    value[field.name]
                    if isinstance(value, Mapping)
                    else getattr(value, field.name)
                    for field in value_type.fields
                )
                paths = tuple(
                    f"{path}.{field.name}" for field in value_type.fields
                )
            result = structure()
            if value_type.kind == "tuple":
                header = _LLVMList(len(value), len(value), ctypes.addressof(result), None, None)
                pointer = self.shell(value_type, value, header)
                self.keepalive.append(result)
            else:
                pointer = self.shell(value_type, value, result)
            for index, (field, item, item_path) in enumerate(zip(value_type.fields, values, paths, strict=True)):
                setattr(result, f"field_{index}", self.marshal(field.value_type, item, item_path))
            return pointer
        raise TypeError(f"unsupported LLVM input type {value_type.kind}")

    def structure(self, value_type: LLVMABIType) -> type[ctypes.Structure]:
        existing = self.structures.get(value_type)
        if existing is not None:
            return existing
        fields = [("identity", ctypes.c_void_p)] if value_type.identity else []
        fields += [
            (f"field_{index}", _llvm_ctype(field.value_type, self.definitions))
            for index, field in enumerate(value_type.fields)
        ]
        result = type(
            f"_{value_type.name.replace('[', '_').replace(']', '_')}",
            (ctypes.Structure,),
            {"_fields_": fields},
        )
        self.structures[value_type] = result
        return result


class LLVMRuntimeError(RuntimeError):
    """An uncaught native exception, copied before request storage is freed."""

    def __init__(self, message: str, native_traceback: str, exception_type: str, exception_module: str):
        super().__init__(message)
        self.native_traceback = native_traceback
        self.exception_type = exception_type
        self.exception_module = exception_module
        self.add_note(native_traceback)

    def __reduce__(self):
        return type(self), (self.args[0], self.native_traceback,
                            self.exception_type, self.exception_module), self.__dict__


class _LLVMExceptionTrace(ctypes.Structure):
    _fields_ = [("frame", ctypes.c_void_p), ("next", ctypes.c_void_p)]


class _LLVMExceptionType(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("module", ctypes.c_void_p)]


_LLVMErrorCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class LLVMLibrary:
    """A loaded native renderer with typed copy-in inputs.

    Close every handle to a path before recompiling there. Windows locks loaded
    DLL files; POSIX loaders reuse the old image while any handle remains open.
    Use distinct output directories for simultaneously loaded revisions.
    """

    def __init__(
        self,
        path: Path,
        llvm_ir: str,
        parameters: tuple[LLVMABIParameter, ...],
        direct: bool,
        managed: bool,
        exceptions: bool,
        type_definitions: tuple[LLVMABIType, ...],
    ) -> None:
        self.path = path
        self.llvm_ir = llvm_ir
        self.parameters = parameters
        self.direct = direct
        self.managed = managed
        self.exceptions = exceptions
        self.type_definitions = type_definitions
        self._structures: dict[LLVMABIType, type[ctypes.Structure]] = {}
        self._library = ctypes.CDLL(str(path))
        self._lock = threading.Lock()
        self._closed = False
        errors = []
        self._errors = errors

        def read_string(pointer):
            value = _LLVMString.from_address(pointer)
            return ctypes.string_at(value.data, value.length).decode("utf-8")

        def report_error(trace, message, exception_type):
            # A ctypes callback cannot raise through C. Copy arena-owned bytes
            # now, and raise only after the native wrapper has finished cleanup.
            try:
                frames = []
                while trace:
                    entry = _LLVMExceptionTrace.from_address(trace)
                    frames.append(read_string(entry.frame))
                    trace = entry.next
                text = read_string(message)
                kind = _LLVMExceptionType.from_address(exception_type)
                errors.append(LLVMRuntimeError(
                    text, "Traceback (native PyJS):\n" + "".join(frames) + text + "\n",
                    read_string(kind.name), read_string(kind.module),
                ))
            except BaseException as error:
                # Do not retain callback frames containing freed ctypes views.
                error.__traceback__ = None
                errors.append(error)

        self._report_error = _LLVMErrorCallback(report_error) if exceptions else None
        self._heap = None
        self._delete_heap = None
        if managed:
            new_heap = self._library.pyjs_gc_new
            new_heap.argtypes = []
            new_heap.restype = ctypes.c_void_p
            self._delete_heap = self._library.pyjs_gc_delete
            self._delete_heap.argtypes = [ctypes.c_void_p]
            self._delete_heap.restype = None
        self._render = self._library.pyjs_render_host_to_fd
        self._render.argtypes = [
            *([ctypes.c_void_p] if managed else []),
            ctypes.c_int,
            *([_LLVMErrorCallback] if exceptions else []),
            *(ctypes.c_void_p if parameter.value_type.resolve(type_definitions).kind in {"optional", "union"}
              else _llvm_ctype(parameter.value_type, type_definitions)
              for parameter in parameters),
        ]
        self._render.restype = ctypes.c_int
        # Validate every required export/signature before acquiring ownership.
        if managed:
            self._heap = new_heap()
            if not self._heap:
                raise MemoryError("native LLVM managed heap allocation failed")

    def render_to_fd(self, descriptor: int, *arguments) -> int:
        if self._closed:
            raise RuntimeError("native LLVM library is closed")
        descriptor = operator.index(descriptor)
        if ctypes.c_int(descriptor).value != descriptor:
            raise OverflowError("Python int too large to convert to C int")
        if len(arguments) != len(self.parameters):
            raise TypeError(
                f"native renderer expects {len(self.parameters)} arguments, "
                f"got {len(arguments)}"
            )
        owner = _LLVMArguments(self._structures, self.type_definitions)
        values = [
            owner.marshal(parameter.value_type, argument, parameter.name)
            for parameter, argument in zip(
                self.parameters,
                arguments,
                strict=True,
            )
        ]
        values = [ctypes.byref(value) if isinstance(value, ctypes.Structure) else value for value in values]
        with self._lock:
            # Host conversion can run arbitrary Python (including close()),
            # and another thread can close while conversion runs outside the lock.
            if self._closed:
                raise RuntimeError("native LLVM library is closed")
            arguments = (
                *((self._heap,) if self.managed else ()), descriptor,
                *((self._report_error,) if self.exceptions else ()), *values,
            )
            self._errors.clear()
            try:
                status = self._render(*arguments)
                if self._errors:
                    raise self._errors[-1]
                return status
            finally:
                self._errors.clear()

    def close(self) -> None:
        """Prevent further calls, release the heap, and unload the library."""
        with self._lock:
            self._closed = True
            if self._heap is not None and self._delete_heap is not None:
                self._delete_heap(self._heap)
                self._heap = None
            if self._library is not None:
                # ctypes does not unload CDLLs automatically. Unlike POSIX,
                # Windows forbids replacing/deleting a loaded library file.
                # POSIX loaders also reuse old code at the same pathname while
                # any handle remains open, even after the file is replaced.
                # No native call can overlap close() under this same lock.
                import _ctypes
                unload = _ctypes.FreeLibrary if sys.platform == "win32" else _ctypes.dlclose
                unload(self._library._handle)
                self._library = self._render = self._delete_heap = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def render(self, *arguments) -> str:
        """Render through a temporary descriptor and decode the UTF-8 result."""
        with tempfile.TemporaryFile() as output:
            status = self.render_to_fd(output.fileno(), *arguments)
            if status:
                raise OSError(status, os.strerror(status))
            output.seek(0)
            return output.read().decode("utf-8")

    def render_to_socket(self, destination, *arguments) -> int:
        """Render to a socket without constructing a Python HTML string.

        POSIX requires a blocking, unwrapped socket and writes directly.
        Windows SOCKET handles are not CRT descriptors; spool to a temporary
        binary file and send bounded chunks there.
        """
        if self._closed:
            raise RuntimeError("native LLVM library is closed")
        descriptor = destination.fileno()
        if sys.platform != "win32":
            return self.render_to_fd(descriptor, *arguments)
        with tempfile.TemporaryFile() as output:
            status = self.render_to_fd(output.fileno(), *arguments)
            if status:
                return status
            output.seek(0)
            try:
                while chunk := output.read(65536):
                    destination.sendall(chunk)
            except OSError as error:
                return (errno.ETIMEDOUT if isinstance(error, TimeoutError)
                        else error.errno or errno.EIO)
        return 0


class LLVM:
    """Small deterministic Clang runner for the direct LLVM backend."""

    def __init__(
        self,
        executable: str | Path | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        configured = executable or os.environ.get("PYJS_CLANG")
        discovered = configured or shutil.which("clang")
        self.executable = Path(discovered).expanduser() if discovered else None
        self.runner = runner or CommandRunner()
        self.version: str | None = None

    def ensure(self) -> Path:
        if self.executable is None or not self.executable.is_file():
            raise RuntimeError(
                "Clang was not found; install it or set PYJS_CLANG to its executable."
            )
        if self.version is None:
            result = self.runner.run(
                [self.executable, "--version"],
                capture_output=True,
            )
            first_line = (result.stdout or "").splitlines()
            if not first_line:
                raise RuntimeError(
                    f"Clang executable {self.executable} returned no version."
                )
            self.version = first_line[0]
        return self.executable

    def compile(
        self,
        llvm_ir: str,
        directory: Path,
        *,
        name: str = "program",
        optimize: int = 2,
        sanitizers: tuple[str, ...] = (),
        shared: bool = False,
    ) -> Path:
        """Compile textual LLVM IR into an executable or shared library."""
        compiler = self.ensure()
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / f"{name}.ll"
        executable = directory / (name + binary_suffix(shared=shared))
        if "address" in sanitizers:
            llvm_ir = _address_sanitized_ir(llvm_ir)
        if shared and sys.platform == "win32":
            llvm_ir = _windows_exported_ir(llvm_ir)
        source.write_text(llvm_ir, encoding="utf-8")
        command: list[str | Path] = [compiler, f"-O{optimize}"]
        if sys.platform == "win32":
            # Share UCRT file descriptors with the Python host. LLVM IR input
            # bypasses Clang's C frontend, which normally emits CRT directives.
            command.extend(("-fms-runtime-lib=dll", "--rtlib=compiler-rt",
                            "-Wl,/NODEFAULTLIB:libcmt,/DEFAULTLIB:msvcrt",
                            "-llegacy_stdio_definitions"))
        if sanitizers:
            command.append(f"-fsanitize={','.join(sanitizers)}")
            command.append("-fno-sanitize-recover=all")
        if shared:
            command.append("-dynamiclib" if sys.platform == "darwin" else "-shared")
            if sys.platform != "win32":
                command.append("-fPIC")
        command.extend((source, "-o", executable))
        if sys.platform != "win32":
            command.append("-lm")
        try:
            self.runner.run(command, capture_output=True)
        except subprocess.CalledProcessError as error:
            # CalledProcessError's string omits captured diagnostics. Keep the
            # generated IR and show a bounded tail in ordinary test tracebacks.
            diagnostics = []
            for stream, content in (("stdout", error.stdout), ("stderr", error.stderr)):
                if content:
                    if isinstance(content, bytes):
                        content = content.decode("utf-8", errors="replace")
                    diagnostics.append(f"Compiler {stream} (last 8000 characters):\n{content[-8000:]}")
            detail = "\n".join(diagnostics) or "(compiler produced no diagnostics)"
            error.add_note(f"LLVM source: {source}\n{detail}")
            raise
        return executable

    def compile_library(
        self,
        source: str,
        directory: Path,
        *,
        filename: str = "_pyjs_native_.py",
        module_name: str | None = None,
        entry_point: str = "main",
        name: str = "pyjs_renderer",
        optimize: int = 2,
        sanitizers: tuple[str, ...] = (),
        direct: bool = False,
    ) -> LLVMLibrary:
        """Compile and load a typed buffered or descriptor renderer."""
        module = transpile_llvm_module(
            source,
            filename=filename,
            module_name=module_name,
            entry_point=entry_point,
            target="library",
            direct=direct,
        )
        library = self.compile(
            module.llvm_ir,
            directory,
            name=name,
            optimize=optimize,
            sanitizers=sanitizers,
            shared=True,
        )
        return LLVMLibrary(
            library,
            module.llvm_ir,
            module.parameters,
            module.direct,
            module.managed,
            module.exceptions,
            module.type_definitions,
        )

    def compare_library_with_python(
        self,
        source: str,
        *arguments,
        directory: Path,
        filename: str = "_pyjs_native_.py",
        module_name: str | None = None,
        entry_point: str = "main",
        name: str = "pyjs_renderer",
        optimize: int = 2,
        sanitizers: tuple[str, ...] = (),
        direct: bool = False,
    ) -> LLVMRenderComparison:
        """Compare renders, transferring library ownership only on success.

        The returned comparison owns an open library even if outputs differ.
        Exceptions close its managed heap before propagating.
        """
        library = self.compile_library(
            source,
            directory,
            filename=filename,
            module_name=module_name,
            entry_point=entry_point,
            name=name,
            optimize=optimize,
            sanitizers=sanitizers,
            direct=direct,
        )
        try:
            python_module_name = f"{module_name or Path(filename).stem}_python"
            was_registered = python_module_name in sys.modules
            previous = sys.modules.get(python_module_name)
            overload_registry = vars(typing).get("_overload_registry")
            previous_overloads = (
                overload_registry.get(python_module_name)
                if isinstance(overload_registry, dict) else None
            )
            try:
                module = create_module(
                    textwrap.dedent(source),
                    filename,
                    module_name=python_module_name,
                )
                function = getattr(module, entry_point)
                if library.direct:
                    with tempfile.TemporaryFile() as output:
                        status = function(*arguments, output.fileno())
                        if status:
                            raise OSError(status, os.strerror(status))
                        output.seek(0)
                        python = output.read().decode("utf-8")
                else:
                    python = function(*arguments)
                    if not isinstance(python, str):
                        raise TypeError(
                            f"{entry_point}() returned {type(python).__name__}, not str"
                        )
            finally:
                # Overload declarations retain their temporary module globals.
                # Restore the registry that create_module replaced along with
                # sys.modules, including an explicit blocked-import None entry.
                if isinstance(overload_registry, dict):
                    overload_registry.pop(python_module_name, None)
                    if previous_overloads is not None:
                        overload_registry[python_module_name] = previous_overloads
                if was_registered:
                    sys.modules[python_module_name] = previous
                else:
                    sys.modules.pop(python_module_name, None)
            return LLVMRenderComparison(python, library.render(*arguments), library)
        except BaseException:
            # A retained exception traceback can keep this frame (and library)
            # alive indefinitely; finalization is not sufficient error cleanup.
            library.close()
            raise

    def assert_library_matches_python(
        self,
        source: str,
        *arguments,
        **options,
    ) -> LLVMRenderComparison:
        """Assert typed renderer parity and retain ordinary compiler artifacts."""
        comparison = self.compare_library_with_python(
            source,
            *arguments,
            **options,
        )
        try:
            if not comparison.matches:
                raise AssertionError(
                    "CPython and native LLVM renders differ:\n"
                    f"CPython: {comparison.python!r}\n"
                    f"LLVM: {comparison.native!r}"
                )
            return comparison
        except BaseException:
            # Host str subclasses can raise from equality, its truth result,
            # or repr while formatting a mismatch. Ownership transfers only
            # after all assertion work has completed successfully.
            comparison.library.close()
            raise

    def run_source(
        self,
        source: str,
        *,
        filename: str = "_pyjs_native_.py",
        module_name: str | None = None,
        directory: Path | None = None,
        name: str = "program",
        optimize: int = 2,
        pass_fds: tuple[int, ...] = (),
        sanitizers: tuple[str, ...] = (),
        timeout: float = 10,
    ) -> LLVMExecution:
        """Generate, compile, and execute one Python source module."""
        llvm_ir = transpile_llvm(
            source,
            filename=filename,
            module_name=module_name,
        )
        if directory is not None:
            return self._run_ir(
                llvm_ir,
                directory,
                name=name,
                optimize=optimize,
                pass_fds=pass_fds,
                sanitizers=sanitizers,
                timeout=timeout,
                artifacts=directory,
            )
        with tempfile.TemporaryDirectory(prefix="pyjs-llvm-") as temporary:
            return self._run_ir(
                llvm_ir,
                Path(temporary),
                name=name,
                optimize=optimize,
                pass_fds=pass_fds,
                sanitizers=sanitizers,
                timeout=timeout,
                artifacts=None,
            )

    def compare_with_python(
        self,
        source: str,
        *,
        filename: str = "_pyjs_native_.py",
        module_name: str | None = None,
        directory: Path | None = None,
        optimize: int = 2,
        sanitizers: tuple[str, ...] = (),
        timeout: float = 10,
    ) -> LLVMComparison:
        """Execute a zero-argument ``main`` with CPython and native LLVM."""
        root_context = (
            tempfile.TemporaryDirectory(prefix="pyjs-llvm-compare-")
            if directory is None
            else None
        )
        root = directory or Path(root_context.name)
        root.mkdir(parents=True, exist_ok=True)
        try:
            python = self._run_python(source, root, timeout=timeout)
            native = self.run_source(
                source,
                filename=filename,
                module_name=module_name,
                directory=root,
                optimize=optimize,
                sanitizers=sanitizers,
                timeout=timeout,
            )
            return LLVMComparison(python, native)
        finally:
            if root_context is not None:
                root_context.cleanup()

    def assert_matches_python(self, source: str, **options) -> LLVMComparison:
        """Raise a useful assertion when CPython and native execution differ."""
        retained = None
        if options.get("directory") is None:
            retained = Path(tempfile.mkdtemp(prefix="pyjs-llvm-comparison-"))
            options["directory"] = retained
        comparison = self.compare_with_python(source, **options)
        if comparison.matches:
            if retained is None:
                return comparison
            shutil.rmtree(retained)
            return LLVMComparison(
                replace(comparison.python, artifacts=None),
                replace(comparison.native, artifacts=None),
            )
        raise AssertionError(
            "CPython and native LLVM differ:\n"
            f"CPython: returncode={comparison.python.returncode}, "
            f"stdout={comparison.python.stdout!r}, "
            f"stderr={comparison.python.stderr!r}\n"
            f"LLVM: returncode={comparison.native.returncode}, "
            f"stdout={comparison.native.stdout!r}, "
            f"stderr={comparison.native.stderr!r}\n"
            f"Artifacts: {comparison.native.artifacts or 'temporary directory removed'}"
        )

    def _run_ir(
        self,
        llvm_ir: str,
        directory: Path,
        *,
        name: str,
        optimize: int,
        pass_fds: tuple[int, ...],
        sanitizers: tuple[str, ...],
        timeout: float,
        artifacts: Path | None,
    ) -> LLVMExecution:
        executable = self.compile(
            llvm_ir,
            directory,
            name=name,
            optimize=optimize,
            sanitizers=sanitizers,
        )
        environment = {}
        if sanitizers:
            # LLVM input may already contain recoverable instrumentation; the
            # compiler flag cannot rewrite those handlers. Make runtime reports
            # fatal too, without changing the caller's process environment.
            inherited = self.runner.env()
            for name in ("ASAN_OPTIONS", "UBSAN_OPTIONS"):
                # Signal termination cannot alias a legitimate scalar main's
                # exit status (including 1), nor an inherited exitcode=0.
                environment[name] = inherited.get(name, "") + ":halt_on_error=1:abort_on_error=1:disable_coredump=1"
        result = self.runner.run(
            [executable],
            capture_output=True,
            check=False,
            pass_fds=pass_fds,
            timeout=timeout,
            environment=environment,
            text=False,
        )
        return LLVMExecution(
            llvm_ir,
            result.returncode,
            result.stdout.decode("utf-8"),
            result.stderr.decode("utf-8"),
            artifacts,
        )

    def _run_python(
        self,
        source: str,
        directory: Path,
        *,
        timeout: float,
    ) -> LLVMExecution:
        python_source = directory / "python_program.py"
        runner_source = directory / "run_python.py"
        python_source.write_text(textwrap.dedent(source), encoding="utf-8")
        runner_source.write_text(
            textwrap.dedent(
                f"""
                import runpy
                import sys

                # Match native UTF-8 output, independent of console encoding
                # and Windows text-stream newline translation.
                sys.stdout.reconfigure(encoding="utf-8", newline="")
                sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace", newline="")

                # Analysis resolves imports in the caller's Python environment.
                # Give the comparison process the same source roots even though
                # its runner lives in a temporary artifact directory.
                sys.path[:0] = {sys.path!r}
                namespace = runpy.run_path({str(python_source)!r})
                result = namespace["main"]()
                if isinstance(result, str):
                    sys.stdout.write(result)
                elif isinstance(result, int):
                    raise SystemExit(result)
                elif result is not None:
                    raise TypeError(
                        "LLVM comparison main() must return str, int or None, "
                        f"not {{type(result).__name__}}"
                    )
                """
            ),
            encoding="utf-8",
        )
        result = self.runner.run(
            [sys.executable, runner_source],
            capture_output=True,
            check=False,
            timeout=timeout,
            text=False,
        )
        return LLVMExecution(
            "",
            result.returncode,
            result.stdout.decode("utf-8"),
            result.stderr.decode("utf-8"),
            directory,
        )


__all__ = [
    "LLVM",
    "LLVMComparison",
    "LLVMExecution",
    "LLVMLibrary",
    "LLVMRenderComparison",
]

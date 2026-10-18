"""Emit typed functions, objects, and control flow as textual LLVM IR."""

import ast
import builtins
import re
import struct
import sys
import textwrap
from copy import copy
from dataclasses import dataclass
from typing import Any, get_args, get_type_hints

from pyjs.analysis.analyzer import (
    _ACTIVE_ENVIRONMENT,
    analyzed_iterable_protocol,
    analyzed_value_type,
    callable_value_type,
)
from pyjs.analysis.ir import (
    Block,
    BlockArgument,
    Branch,
    ClassIR,
    CollectionNew,
    Comprehension,
    ContextExitCall,
    ExceptionCatch,
    ExceptionDispatch,
    ExceptionRaise,
    External,
    FieldIR,
    FieldLoad,
    FieldStore,
    GeneratorInput,
    IteratorCreate,
    IteratorNext,
    Jump,
    ListAppend,
    ObjectNew,
    ProgramIR,
    Return,
    Suspend,
    Terminator,
    build_program_ir,
)
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.objects import (
    CallableClass,
    ChainedCompare,
    Class,
    EvaluateOnce,
    Function,
    GenericClass,
    Instance,
    Module,
    ModuleAlias,
    StaticCast,
    UnionType,
    union_type_key,
)
from pyjs.analysis.source import analyze_source
from pyjs.analysis.type_relations import (
    get_type_members,
    is_return_type_compatible,
    is_subclass,
    same_analyzer_type,
)
from pyjs.analysis.value_representation import (
    analyzed_numeric_format,
    analyzed_representation,
    analyzed_value_object,
    representation_for_member,
)
from pyjs.decorators import get_native_decoration
from pyjs.native.platform import errno_symbol
from pyjs.numeric import NumericFormat, integer_literal
from pyjs.python import native as native_builtins
from pyjs.web.dom import Element as WebElement
from pyjs.web.domx import CustomElement, ProxyElement

from . import (
    callable_adapters,
    callables,
    callback_ops,
    calls,
    class_constants,
    closures,
    collection_ops,
    comparisons,
    comprehensions,
    dom_ops,
    dom_state,
    dom_types,
    enum_ops,
    exception_values,
    gc_layouts,
    generators,
    hashing,
    identity,
    indexing,
    inputs,
    iterable_views,
    iterator_callbacks,
    iterator_ops,
    iterator_views,
    json_ops,
    math_ops,
    nullable,
    object_values,
    partials,
    persistent,
    properties,
    protocols,
    representation,
    slices,
    super_proxy,
    tagged,
    text_search,
)
from .analysis import NATIVE_ENVIRONMENT
from .bindings import local_storage_binding
from .errors import LLVMUnsupported
from .runtime import dom as runtime_dom
from .runtime import memory as runtime_memory
from .runtime import numeric as runtime_numeric
from .runtime import output as runtime_output
from .runtime import ranges as runtime_ranges
from .runtime import text as runtime_text


@dataclass(frozen=True)
class LLVMABIField:
    """One named field in a borrowed native input record."""

    name: str
    value_type: LLVMABIType


@dataclass(frozen=True)
class LLVMABIType:
    """A Python value shape exposed at the generated library boundary."""

    kind: str
    name: str
    fields: tuple[LLVMABIField, ...] = ()
    item_type: LLVMABIType | None = None
    numeric_format: NumericFormat | None = None
    # Semantic normalization may be narrower than physical collection storage.
    normalization_format: NumericFormat | None = None
    key_type: LLVMABIType | None = None
    # Host models have semantic constraints beyond their structural fields.
    # Foreign record classes retain their identity for exact-type copy-in.
    host_model: str | type | None = None
    members: tuple[LLVMABIType, ...] = ()
    # Recursive edges index LLVMModule.type_definitions, never a cyclic Python
    # dataclass graph: ABI shapes remain immutable and structurally hashable.
    reference: int | None = None
    # A headed input reserves its first word; only native promotion installs
    # this library's private vtable. Borrowed snapshots never supply identity.
    identity: str | None = None
    # Application union arms use compiled tags and exact host classes, even
    # when their headerless concrete record API also accepts structural input.
    runtime_tag: int | None = None
    host_class: type | None = None

    def resolve(self, definitions: tuple[LLVMABIType, ...]) -> LLVMABIType:
        value = self
        while value.kind == "alias":
            value = definitions[value.reference]
        return value


@dataclass(frozen=True)
class LLVMABIParameter:
    """One caller-supplied parameter of a generated native library."""

    name: str
    value_type: LLVMABIType


@dataclass(frozen=True)
class LLVMModule:
    """Generated LLVM IR and its typed shared-library boundary."""

    llvm_ir: str
    parameters: tuple[LLVMABIParameter, ...]
    direct: bool
    managed: bool
    exceptions: bool = False
    type_definitions: tuple[LLVMABIType, ...] = ()


class ModuleState:
    """Layouts and discovered requirements shared by emitted functions."""

    def __init__(self, entry_point: str, target: str, direct: bool) -> None:
        if target not in {"executable", "library"}:
            raise ValueError(f"unsupported LLVM output target {target!r}")
        if direct and target != "library":
            raise ValueError("direct output is available only for LLVM libraries")
        self.entry_point = entry_point
        self.target = target
        self.direct = direct
        self.functions: set[Function] = set()
        self.callables: dict[Function, bool] = {}
        self.callable_bindings = {}
        self.callable_arities = set()
        self.callable_adapters = {}
        self.partials = {}
        self.partial_callbacks = {}
        self.uses_callable_adapters = False
        self.iterable_views = {}
        self.uses_iterable_views = False
        self.iterator_views = {}
        self.iterator_signatures = {}
        self.uses_iterator_views = False
        self.lambdas = {}
        self.closures = {}
        self.cells = {}
        self.iterator_steps = {}
        self.application_iterators = set()
        self.generators = {}
        self.classes: dict[Class, ClassIR] = {}
        self.class_names: dict[str, ClassIR] = {}
        self.entry_module: Module | None = None
        self.layout_fields = {}
        self.gc_descriptors = {}
        self.gc_allocators = set()
        self.methods: dict[tuple[Class, str], Function] = {}
        self.vtable_roots: dict[Class, Class] = {}
        self.vtable_slots: dict[Class, tuple[str, ...]] = {}
        self.vtable_entries: dict[Class, tuple[Function | None, ...]] = {}
        self.virtual_methods: dict[Function, tuple[Class, int]] = {}
        self.adapted_virtual_slots: set[tuple[Class, int]] = set()
        self.rebound_virtual_slots: set[tuple[Class, int]] = set()
        self.persistent_values = {}
        self.uses_exceptions = False
        self.uses_not_implemented = False
        self.uses_exception_repr = False
        self.uses_repr = False
        self.uses_format = False
        self.uses_float_format = False
        self.uses_urlencode = False
        self.uses_print = False
        self.exception_types = set()
        self.exception_origins = set()
        self.uses_collections = False
        self.uses_iterators = False
        self.uses_ranges = False
        self.uses_mappings = False
        self.uses_key_callbacks = False
        self.value_comparators = {}
        self.value_comparator_queue = []
        self.uses_sequence_search = False
        self.uses_ordering = False
        self.uses_float_sum = False
        self.uses_strings = False
        self.uses_unicode = False
        self.uses_text_edit = False
        self.uses_text_extra = False
        self.uses_string_split = False
        self.uses_float = False
        self.uses_numeric_text = False
        self.uses_modular_pow = False
        self.tuple_types: dict[tuple[str, ...], str] = {}
        self.string_constants: dict[str | bytes, str] = {}
        self.native_functions: set[Function] = set()
        self.custom_element_types: set[Class] = set()
        self.uses_native = False
        self.uses_dom_references = False
        self.uses_arena = False
        self.uses_gc = False
        self.has_identity_inputs = False
        self.uses_erased_objects = False
        self.uses_exception_values = False
        self.exception_formats = {}
        self.erased_layouts = {}
        self.erased_candidates = {}
        self.erased_formatters = {}
        self.erased_comparisons = {}
        self.erased_dom_builders = {}
        self.erased_subscripts = {}
        self.json_walkers = {}
        self.abi_parameters: tuple[LLVMABIParameter, ...] = ()
        self.abi_aliases = {}
        self.abi_type_definitions = []
        self.library_is_direct = False
        self.library_host_parameters = ()
        self.input_shapes = {}
        self.input_definitions = []
        self.function_names = {}
        self.entry_function = None
        self.literal_namespace = "pyjs"


class FunctionEmitter:
    """Lower target-neutral ProgramIR to a small, executable LLVM module."""


    INTEGER_OPERATORS = {
        "__add__": "add",
        "__radd__": "add",
        "__sub__": "sub",
        "__mul__": "mul",
        "__rmul__": "mul",
        "__and__": "and",
        "__rand__": "and",
        "__or__": "or",
        "__ror__": "or",
        "__xor__": "xor",
        "__rxor__": "xor",
    }
    INTEGER_COMPARISONS = {
        "__eq__": "eq",
        "__ne__": "ne",
        "__lt__": "slt",
        "__le__": "sle",
        "__gt__": "sgt",
        "__ge__": "sge",
    }
    FLOAT_OPERATORS = {
        "__add__": "fadd",
        "__radd__": "fadd",
        "__sub__": "fsub",
        "__rsub__": "fsub",
        "__mul__": "fmul",
        "__rmul__": "fmul",
        "__truediv__": "fdiv",
        "__rtruediv__": "fdiv",
    }
    FLOAT_COMPARISONS = {
        "__eq__": "oeq",
        "__ne__": "une",
        "__lt__": "olt",
        "__le__": "ole",
        "__gt__": "ogt",
        "__ge__": "oge",
    }

    def __init__(self, module: ModuleState) -> None:
        self.module = module
        self.temporary = 0
        self.slots: dict[str, str] = {}
        self.slot_types: dict[str, str] = {}
        self.value_semantics = {}
        self.value_representations = {}
        self.slot_numeric_formats: dict[str, NumericFormat] = {}
        self.lines: list[str] = []
        self.current_function: Function | None = None
        self.iterators = {}
        self.return_type = "void"
        self.return_storage_type = "void"
        self.gc_frame: str | None = None
        self.expression_roots: dict[int, str] = {}
        self.runtime_helper_calls = set()
        self.runtime_primitive_instructions = set()
        self.has_inline_calls = False
        self.stack_allocations = None
        self.exception_target = None
        self.exception_snapshots = {}
        self.cell_flags = {}

    def emit(self, program: ProgramIR) -> str:
        # Analysis restores the caller's environment before emission. Structural
        # type relations used by adapters still need this target's builtins,
        # including during helper discovery and recursively nested conversions.
        with _ACTIVE_ENVIRONMENT.set(NATIVE_ENVIRONMENT):
            return self._emit(program)

    def _emit(self, program: ProgramIR) -> str:
        from . import models

        module = program.entry_point.container
        assert isinstance(module, Module)
        self.module.entry_module = module
        self.module.entry_function = program.entry_point
        classes = [
            layout
            for layout in program.classes
            if (self.is_application_module(layout.value_type.container)
                or models.is_model(layout.value_type.py_obj)
                or self.is_custom_element_type(layout.value_type)
                or self.is_proxy_element_type(layout.value_type))
            and not self.is_exception_type(layout.value_type)
            and not enum_ops.scalar_name(layout.value_type)
        ]
        self.module.classes = {layout.value_type: layout for layout in classes}
        self.module.class_names = {layout.value_type.name: layout for layout in classes}
        functions = [
            function
            for function in program.functions
            if (
                self.is_runtime_helper(function)
                or function.cls in self.module.classes
                or isinstance(function.container, Module)
                # Reached ordinary Python helpers are source even when shipped
                # by pyjs (Badge, require_element, etc.). Runtime declarations
                # are filtered below; package spelling is not a body policy.
                and not function.container.scope.is_builtins
            )
            and function.ir is not None
            and not any(isinstance(block, External) for block in function.ir.blocks)
        ]
        if program.entry_point not in functions:
            raise LLVMUnsupported("the LLVM entry point has no analyzable body")
        self.module.functions = set(functions)
        self.prepare_native(program)
        uses_math = any(function.py_func.__module__ == "pyjs.native.runtime.math_calls"
                        for function in self.module.native_functions)
        uses_fsum = any(get_native_decoration(function.py_func).operation == "math.fsum"
                        for function in self.module.native_functions)
        uses_norm = any(get_native_decoration(function.py_func).operation in {"math.dist", "math.hypot"}
                       for function in self.module.native_functions)
        uses_json = any(get_native_decoration(function.py_func).operation == "json.dumps"
                        for function in self.module.native_functions)
        self.module.uses_float |= uses_math or uses_fsum or uses_json or uses_norm
        self.module.uses_collections |= uses_norm or uses_fsum
        self.module.uses_erased_objects = object_values.needed(classes, functions)
        callable_signatures = callable_adapters.prepare(self, functions, classes)
        # A payload must be boxed even when its value property is never read.
        self.module.exception_formats = exception_values.formats(functions)
        self.module.uses_exception_values = bool(self.module.exception_formats)
        self.module.uses_erased_objects |= self.module.uses_exception_values
        self.module.uses_repr |= self.module.uses_exception_values
        self.module.uses_collections |= self.module.uses_erased_objects
        self.prepare_object_layouts(classes, functions)
        persistent.prepare(self, functions, program.entry_point.compilation_objects)
        closures.prepare(self, functions)
        partials.prepare(self, functions)
        iterator_callbacks.prepare(self, functions)
        protocols.prepare(self, functions)
        generators.prepare(self, functions)
        callables.prepare(self, functions)
        callable_adapters.reserve(self, callable_signatures)
        self.prepare_collections(functions)
        iterator_views.reserve(self)
        if self.module.uses_repr:
            # All representation consumers, including implicit KeyError key
            # text, need the same output/Unicode helpers. Resolve this once
            # before string/runtime preparation rather than at each call site.
            self.module.uses_native = self.module.uses_unicode = self.module.uses_text_extra = True
        if self.module.uses_repr and any(getattr(cls.py_obj, "__repr__", None) is object.__repr__
                                         for cls in self.module.classes):
            self.module.uses_format = True  # Default object addresses reuse integer base formatting.
        self.module.uses_ordering |= uses_json
        self.prepare_strings(classes, functions)
        self.prepare_exceptions(functions)
        self.module.uses_float |= any(
            nullable.contains(field.value_type, "float")
            for layout in classes
            for field in layout.fields
        ) or any(
            nullable.contains(function.return_type, "float")
            or any(
                nullable.contains(getattr(parameter.annotation, "obj", None), "float")
                for parameter in calls.parameters(function)
            )
            or any(
                nullable.contains(getattr(value, "cls", None), "float")
                for value in function.scope.names.values()
            )
            or any(
                (isinstance(node, ast.Constant) and isinstance(node.value, float))
                # Class/union attribute literals are not children of the read
                # node. Their declared result still requires float helpers.
                or (isinstance(getattr(node, "obj", None), Instance)
                    and nullable.contains(node.obj.cls, "float"))
                or (isinstance(node, StaticCast) and nullable.contains(analyzed_value_type(node), "float"))
                for block in function.ir.blocks
                for statement in getattr(block, "body", ())
                for node in ast.walk(statement)
            )
            for function in functions
        )
        if self.module.target == "library":
            self.prepare_library_abi(program.entry_point)
        self.module.uses_arena = bool(classes) or self.module.uses_collections or self.module.uses_strings
        # Aggregate scratch must be reclaimable between calls in long loops,
        # even when no user allocation otherwise requires the managed heap.
        # Identity-bearing host inputs also require promotion: their reserved
        # header words are initialized only on native-owned copies.
        self.module.uses_gc = self.module.uses_iterator_views or self.module.uses_iterable_views or self.module.uses_callable_adapters or bool(self.module.partials) or self.module.has_identity_inputs or bool(self.module.persistent_values) or self.module.uses_repr or uses_norm or uses_fsum or bool(self.module.lambdas or self.module.iterator_steps or self.module.generators) or any(self.module.callables.values()) or any(
            self.requires_managed_heap(node)
            for function in functions
            for block in function.ir.blocks
            for statement in getattr(block, "body", ())
            for node in ast.walk(statement)
        )

        output = [
            "; Generated by PyJS from typed ProgramIR.",
            "; Integers currently use fixed-width i64 rather than Python big integers.",
            'source_filename = "pyjs"',
            "",
        ]
        type_insertion = len(output)
        if self.module.uses_exceptions:
            output.extend([
                "%pyjs.string = type { i64, ptr }",
                "%pyjs.exception = type { i1, ptr, ptr, ptr, ptr, ptr, i1 }",
                "%pyjs.trace = type { ptr, ptr }",
            ])
        uses_integer_true_division = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(getattr(node.func, "obj", None), Function)
            and node.func.obj.name in {"__truediv__", "__rtruediv__"}
            and enum_ops.storage_name(analyzed_value_type(node.func.value)) in {"int", "bool"}
            for function in functions
            for block in function.ir.blocks
            for statement in getattr(block, "body", ())
            for node in ast.walk(statement)
        )
        self.module.uses_float |= uses_integer_true_division
        output.extend(self.integer_runtime(uses_integer_true_division, include_modular_pow=self.module.uses_modular_pow))
        if self.module.uses_key_callbacks or any(
                function.py_func in {native_builtins._hash, native_builtins._object.__hash__}
                for function in program.functions):
            from .hashing import runtime
            output.extend(runtime())
        output.append("")
        if self.module.uses_float:
            output.extend(self.float_runtime(declare_formatting=not self.module.uses_strings))
            output.append("")
        if uses_math:
            output.extend(math_ops.declarations())
        if uses_norm:
            from .runtime import norm

            if not uses_math:
                output.extend(["declare double @fma(double, double, double)",
                               "declare double @llvm.sqrt.f64(double)"])
            output.extend(norm.compiled_runtime())
        if uses_fsum:
            from .runtime import accurate_sum

            output.extend(accurate_sum.compiled_runtime())
        for layout in classes:
            output.append(self.class_definition(layout))
        if self.module.uses_collections:
            output.extend(self.collection_type_definitions())
        if self.module.uses_strings and not self.module.uses_exceptions:
            output.extend(self.string_definitions())
        if self.module.uses_native:
            output.extend(self.dom_type_definitions())
            output.extend(dom_ops.identity_definitions(self))
        if classes or self.module.uses_collections or self.module.uses_strings:
            output.append("")
        if self.module.uses_collections or self.module.uses_strings:
            output.extend(
                [
                    "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)",
                    "",
                ]
            )
        if self.module.uses_collections:
            output.extend(
                [
                    "declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)",
                    "",
                ]
            )
        if classes:
            output.extend(self.vtable_definitions(classes))
            if self.module.vtable_slots:
                output.append("")
        if self.module.uses_arena:
            output.extend(runtime_memory.arena_runtime())
            output.append("")
        if self.module.uses_gc:
            output.extend(runtime_memory.gc_runtime())
            output.append("")
            if self.module.target == "library" and any(
                inputs.needs_copy(parameter.value_type, self.module.abi_type_definitions)
                for parameter in self.module.abi_parameters
            ):
                from .runtime import inputs as runtime_inputs

                inputs.prepare(self)
                output.extend(runtime_inputs.compiled_runtime())
                output.extend(self.module.input_definitions)
        if uses_json or self.module.input_shapes:
            output.extend(runtime_memory.identity_map_runtime())
        if uses_json:
            from .runtime import json_state
            output.extend(json_state.compiled_runtime())
        if self.module.uses_iterators:
            output.extend(iterator_ops.runtime.compiled_runtime())
            state = iterator_ops.runtime
            output.extend(gc_layouts.owned_header(self, "iterator", f"[{state.SIZE} x i8]",
                                                  tuple((offset,) for offset in state.REFERENCE_OFFSETS)))
            if self.module.uses_gc:
                output.append("@pyjs.gc.descriptor.group = private constant %pyjs.gc.descriptor "
                              "{ i64 4, ptr @pyjs.iterator.group.trace }")
            output.extend(gc_layouts.owned_header(self, "group", None, (),
                                                  trace="@pyjs.gc.descriptor.group"))
        if self.module.uses_float_sum:
            from .runtime.summation import compiled_runtime
            output.extend(compiled_runtime())
        if self.module.uses_urlencode:
            from .runtime.url import compiled_runtime
            output.extend(compiled_runtime())
        if self.module.uses_ranges:
            output.extend(runtime_ranges.compiled_range_runtime())
        if self.module.uses_strings:
            output.extend(self.string_runtime())
            if self.module.uses_float:
                output.extend(runtime_numeric.float_string_runtime())
            output.append("")
        if self.module.uses_unicode:
            output.extend(runtime_text.unicode_definitions())
            output.extend(runtime_text.compiled_utf8_runtime())
            output.extend(runtime_text.compiled_case_runtime())
        if self.module.uses_text_edit:
            output.extend(runtime_text.compiled_edit_runtime(self.module.uses_string_split))
        if self.module.uses_text_extra:
            output.extend(runtime_text.compiled_extra_runtime())
        if self.module.uses_numeric_text:
            output.extend(runtime_numeric.integer_string_runtime())
            if self.module.uses_float:
                output.extend(runtime_numeric.float_string_parser_runtime())
        if self.module.uses_native:
            output.extend(self.dom_runtime())
            output.append("")
        if uses_json or self.module.uses_repr:
            from .runtime import formatting

            output.extend(formatting.compiled_runtime())
        if self.module.uses_format:
            from .runtime import text_format
            output.extend(text_format.compiled_runtime(
                include_ascii=self.module.uses_repr, include_float=self.module.uses_float_format))
        if self.module.uses_exceptions:
            if not self.module.uses_native:
                output.extend(runtime_output.write_all_runtime())
            output.extend(runtime_output.exception_runtime())
            if self.module.uses_exception_repr:
                output.extend(runtime_output.exception_message_runtime())
        if self.module.uses_print:
            if not self.module.uses_native and not self.module.uses_exceptions:
                output.extend(runtime_output.write_all_runtime())
            output.extend(runtime_output.compiled_print_runtime())
        output.extend(object_values.definitions(self))
        if any(function.py_func is native_builtins._dataclass_missing for function in program.functions):
            output.append("@pyjs.dataclass.missing = private constant { ptr } zeroinitializer")
        if self.module.callables or self.module.lambdas or self.module.partials or self.module.uses_callable_adapters:
            output.append("%pyjs.callable = type { ptr, ptr }")
        for function in functions:
            output.extend(FunctionEmitter(self.module).function(function))
            output.append("")
        emitted_views = set()
        output.extend(self.view_definitions(emitted_views))
        # Body and adapter emission record the typed invocation arities. Do not
        # lower unused omission wrappers (which may have unsupported defaults).
        output.extend(callables.definitions(self))
        output.extend(self.view_definitions(emitted_views))
        output.extend(partials.definitions(self))
        output.extend(callable_adapters.definitions(self))
        output.extend(slices.definitions(self))
        output.extend(self.view_definitions(emitted_views))
        from . import erased_comparison, erased_dom, erased_repr
        output.extend(exception_values.definition(self))
        if self.module.erased_comparisons:
            # Comparisons can box nested members; formatters called from their
            # callbacks must recognize those layouts too.
            erased_comparison.register_members(self)
        output.extend(erased_repr.definitions(self))
        output.extend(json_ops.definitions(self))
        output.extend(erased_dom.definitions(self))
        # Typed recursive edges and erased comparisons can discover each
        # other. Drain reached helper keys, not the whole analyzed graph.
        emitted_erased, emitted_values = set(), set()
        while (len(emitted_erased) < len(self.module.erased_comparisons)
               or len(emitted_values) < len(self.module.value_comparators)):
            output.extend(erased_comparison.definitions(self, emitted_erased))
            output.extend(comparisons.definitions(self, emitted_values))
        if self.module.target == "library":
            output.extend(self.library_wrapper(program.entry_point))
        else:
            output.extend(self.main_wrapper(program.entry_point))
        # Formatting/comparisons can need mapping helpers without constructors
        # (including nested/erased optional results). Select this runtime after
        # consumers and outlined formatters/comparators have emitted.
        if self.module.uses_ordering:
            from .runtime.ordering import compiled_runtime
            output.extend(compiled_runtime())
        if self.module.uses_collections:
            output.extend(self.collection_runtime(self.module.uses_mappings, self.module.uses_sequence_search))
            output.append("")
        if self.module.uses_strings or self.module.uses_mappings:
            output.extend(gc_layouts.scalar_allocator(self.module.uses_gc))
        if self.module.uses_exceptions:
            output.extend(self.exception_definitions())
            output.extend(self.string_definitions()[1:])
        if self.module.uses_not_implemented:
            # Address identity is semantic: do not merge this token with other
            # constants. It is immortal, not an arena or managed allocation.
            if not self.module.uses_erased_objects:
                output.append("@pyjs.object.type.NotImplementedType = private constant { ptr } { ptr null }")
            output.append("@pyjs.not_implemented = private constant { ptr } { ptr @pyjs.object.type.NotImplementedType }")
        # Outlined comparisons can discover tuple layouts with no constructor
        # call (for example an empty mapping annotated with nested tuple keys).
        # Collect after emission, but place sized types before their GEP uses.
        output[type_insertion:type_insertion] = [
            f"%{name} = type {{ {', '.join(types)} }}"
            for types, name in self.module.tuple_types.items()
        ]
        output.extend(gc_layouts.definitions(self))
        return "\n".join(output) + "\n"

    def view_definitions(self, emitted):
        # A yielded callable, a callback returning a cursor, or an Iterable
        # acquisition can discover another typed view. Drain reached helpers
        # together, without rescanning the source graph or emitting unused pairs.
        result = []
        while True:
            partials.prepare_definitions(self)
            functions = [*self.module.callable_bindings.values(), *self.module.callable_adapters.values(),
                         *self.module.iterator_views.values(), *self.module.partial_callbacks.values(),
                         *(function for pair in self.module.iterable_views.values() for function in pair)]
            pending = [function for function in functions if function not in emitted]
            if not pending:
                return result
            for function in pending:
                emitted.add(function)
                result.extend(FunctionEmitter(self.module).function(function))

    def prepare_exceptions(self, functions):
        # Application allocation and conversions can fail even without an
        # explicit handler. Raw runtime helpers retain their status-return ABI.
        self.module.uses_exceptions |= bool(
            self.module.classes or self.module.uses_collections
            or self.module.uses_strings or self.module.uses_native
        )
        checked_methods = {
            "__truediv__", "__rtruediv__", "__floordiv__", "__rfloordiv__",
            "__mod__", "__rmod__", "divmod", "__lshift__", "__rshift__",
            "__getitem__", "__setitem__", "__delitem__", "pop", "index",
            "remove", "__slice__", "split", "rsplit", "__len__", "round", "pow", "hash",
        }
        for function in functions:
            for block in function.ir.blocks:
                for statement in getattr(block, "body", ()):
                    for node in ast.walk(statement):
                        if isinstance(node, (ExceptionRaise, ExceptionDispatch)):
                            self.module.uses_exceptions = True
                            value_type = getattr(node, "value_type", None)
                            if value_type is not None:
                                self.module.exception_types.add(value_type)
                                self.module.uses_exception_repr |= is_subclass(
                                    value_type, NATIVE_ENVIRONMENT.builtins.search("KeyError"),
                                )
                        elif isinstance(node, ast.Constant) and node.value is NotImplemented:
                            # Its truth conversion raises even in otherwise
                            # allocation-free scalar code.
                            self.module.uses_exceptions = True
                        elif isinstance(node, IteratorCreate):
                            self.module.uses_exceptions |= analyzed_value_type(node.iterable).generic_name in {"dict", "set", "frozenset"}
                        elif isinstance(node, ast.Call):
                            target = getattr(node.func, "obj", None)
                            if getattr(target, "py_func", None) is native_builtins._Generator.throw:
                                raised = generators.thrown_exception(node)
                                self.module.uses_exceptions = True
                                if raised.value_type is not None:
                                    self.module.exception_types.add(raised.value_type)
                                    self.module.uses_exception_repr |= is_subclass(
                                        raised.value_type, NATIVE_ENVIRONMENT.builtins.search("KeyError"))
                            if isinstance(target, Class):
                                self.module.uses_exceptions |= target.generic_name in {"range", "int", "float"}
                                self.module.uses_exception_repr |= (
                                    target.generic_name in {"int", "float"} and bool(node.args)
                                    and any(enum_ops.storage_name(member) == "str"
                                            for member in get_type_members(analyzed_value_type(node.args[0])))
                                )
                            elif isinstance(target, Function):
                                self.module.uses_exceptions |= target.name in checked_methods
                                self.module.uses_exception_repr |= (
                                    getattr(target.cls, "generic_name", None) in {"dict", "set", "frozenset"}
                                    and target.name in {"__getitem__", "__delitem__", "pop", "remove"}
                                )
        if self.module.uses_exceptions:
            self.module.uses_strings = True
            self.module.uses_unicode |= self.module.uses_exception_repr
            # Dispatch is emitted before every possible raise site is visited.
            # Register implicit runtime types before generating any handler.
            self.module.exception_types.update(
                NATIVE_ENVIRONMENT.builtins.search(name) for name in
                ("ZeroDivisionError", "ValueError", "OverflowError", "IndexError",
                 "KeyError", "TypeError", "RuntimeError", "MemoryError", "OSError", "UnicodeDecodeError", "StopIteration",
                 "NameError", "UnboundLocalError", "RecursionError", "GeneratorExit", "AttributeError")
            )
            if self.module.uses_print:
                self.module.exception_types.add(NATIVE_ENVIRONMENT.builtins.search("BrokenPipeError"))

    @staticmethod
    def requires_managed_heap(node: ast.AST) -> bool:
        if (
            isinstance(node, (CollectionNew, ObjectNew))
            and node.lifetime is not None
            and node.lifetime.boundary is LifetimeBoundary.EXTERNAL
        ):
            return True
        if not isinstance(node, ast.Call):
            return False
        target = getattr(node.func, "obj", None)
        if not isinstance(target, Function):
            return False
        decoration = get_native_decoration(target.py_func)
        return (
            decoration is not None
            and decoration.operation is not None
            and decoration.operation.startswith("runtime.gc_")
        )

    def prepare_collections(self, functions: list[Function]) -> None:
        try:
            self.prepare_collection_layouts(functions)
        except LLVMUnsupported as error:
            # Preparation can reject before function() installs its diagnostic
            # context. The layout walk already tracks the function being visited.
            error.add_function_context(self.current_function)
            raise

    def prepare_collection_layouts(self, functions: list[Function]) -> None:
        for function in functions:
            # Preparation must see the same local layout as emission. A loop
            # can refine a union-backed local to int without guard metadata.
            self.current_function = function
            self.slot_types = {}
            self.iterators = {}
            slots = self.local_types(function, [
                (argument.arg, self.annotation_storage_type(argument.annotation, analyzed_numeric_format(argument)))
                for argument in calls.parameters(function)
            ])
            if function.vararg or function.kwarg:
                self.module.uses_collections = True
            if function.kwarg:
                self.module.uses_mappings = self.module.uses_strings = True
            for default in (*function.defaults, *function.kw_defaults):
                if isinstance(default, ast.Constant) and isinstance(
                    default.value,
                    str,
                ):
                    self.string_constant(default.value)
                    self.module.uses_strings = True
            for block in function.ir.blocks:
                if not isinstance(block, Block):
                    continue
                for statement in block.body:
                    for node in ast.walk(statement):
                        if isinstance(node, ast.JoinedStr):
                            self.module.uses_format = self.module.uses_strings = True
                        enum_ops.prepare(self, node)
                        if isinstance(node, ast.Call):
                            target = getattr(node.func, "obj", None)
                            if isinstance(target, Function) and target.py_func in {native_builtins._ord, native_builtins._chr}:
                                self.module.uses_unicode = self.module.uses_strings = True
                            if isinstance(target, Function) and target.py_func in {native_builtins._bin, native_builtins._oct, native_builtins._hex}:
                                self.module.uses_format = self.module.uses_strings = True
                            if isinstance(target, Function) and target.py_func in {native_builtins._format, native_builtins._ascii}:
                                self.module.uses_format = self.module.uses_strings = True
                                # Runtime roots are selected before function emission.
                                # Integer/bool values may also use floating format codes.
                                if (target.py_func is native_builtins._format and len(node.args) > 1
                                        and (nullable.is_object(analyzed_value_type(node.args[0]))
                                             or any(enum_ops.storage_name(member) in {"int", "bool", "float"}
                                                    for member in get_type_members(analyzed_value_type(node.args[0]))))
                                        and isinstance(node.args[1], ast.Constant)
                                        and isinstance(node.args[1].value, str)
                                        and node.args[1].value[-1:] in {"e", "E", "f", "F", "g", "G", "%"}):
                                    self.module.uses_float_format = True
                                # Scalar padding needs neither DOM output buffers
                                # nor a managed heap. Containers/custom callbacks
                                # retain the representation writer's safe boundary.
                                if target.py_func is native_builtins._ascii or representation.requires_buffer(target, node, slots, self.module.functions, scope=function.scope):
                                    self.module.uses_repr = True
                                elif getattr(analyzed_value_type(node.args[0]), "generic_name", None) == "bytes":
                                    self.module.uses_text_extra = True
                            if ((isinstance(target, Function) and
                                    (target.py_func is native_builtins._repr or target.name in {"__str__", "__repr__"})
                                    or isinstance(target, Class) and target.py_obj is native_builtins._str)
                                    and representation.requires_buffer(target, node, slots, self.module.functions, scope=function.scope)):
                                self.module.uses_repr = True
                            decoration = get_native_decoration(target.py_func) if isinstance(target, Function) else None
                            if isinstance(target, Function) and target.py_func is native_builtins._print:
                                self.module.uses_print = self.module.uses_strings = True
                                for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                                    json_ops.reject_class_values(argument, node, "print")
                                for argument in node.args:
                                    semantic = analyzed_value_type(argument)
                                    name = getattr(semantic, "generic_name", None)
                                    if name == "bytes":
                                        self.module.uses_text_extra = True
                                    elif tagged.narrowed_integer(argument, slots, self.module.functions, scope=function.scope) or name not in {"str", "int", "float", "bool", "NoneType"}:
                                        self.module.uses_repr = True
                            if decoration is not None and decoration.operation == "urllib.parse.urlencode":
                                self.module.uses_urlencode = self.module.uses_strings = True
                            if decoration is not None and decoration.operation == "json.dumps":
                                # Validate before collection preparation asks for
                                # first-class layouts of unsupported JSON values.
                                json_ops.validate_call(node)
                        collection_ops.prepare(self, node)
                        iterator_ops.prepare(self, node)
                        if isinstance(node, ast.Call) and calls.expands_arguments(node):
                            self.module.uses_collections = True
                            self.module.uses_mappings = True
                            self.module.uses_strings = True
                            self.module.uses_text_edit = True
                        if isinstance(node, ast.Call) and getattr(
                            getattr(node.func, "obj", None), "py_obj", None
                        ) in {native_builtins._range, native_builtins._slice}:
                            self.module.uses_ranges = True
                            self.module.uses_collections = True
                        if isinstance(node, ast.Call) and getattr(
                            getattr(node.func, "obj", None), "py_func", None
                        ) is native_builtins._divmod:
                            self.module.uses_collections = True
                            self.tuple_type(analyzed_value_type(node), node)
                        if isinstance(
                            node,
                            (CollectionNew, IteratorCreate, IteratorNext, ListAppend),
                        ):
                            self.module.uses_collections = True
                        if isinstance(node, CollectionNew) and isinstance(
                            node.source,
                            (ast.Dict, ast.Set),
                        ):
                            # The generic mapping comparator supports string
                            # keys as well as scalar keys.
                            self.module.uses_mappings = True
                            self.module.uses_strings = True
                        if isinstance(node, CollectionNew) and isinstance(
                            node.source,
                            ast.Tuple,
                        ):
                            if not node.value_type.tuple_variadic:
                                self.tuple_type(node.value_type, node.source)

    def prepare_native(self, program: ProgramIR) -> None:
        from .attribute_queries import validate_getattr
        validate_getattr(self)
        self.module.native_functions = {
            function
            for function in program.functions
            if function.ir is not None
            and any(isinstance(block, External) for block in function.ir.blocks)
            and get_native_decoration(function.py_func) is not None
        }
        self.module.custom_element_types = {
            layout.value_type
            for layout in program.classes
            if self.is_custom_element_type(layout.value_type)
        }
        erased_methods = [(function, *call) for function in self.module.functions
                          for call in getattr(function, "native_erased_methods", ())]
        if erased_methods:
            # An erased factory/getter can be the only place constructing an
            # overriding class. Check materialized classes from this analysis,
            # not just emitted layouts, without resolving unused declarations
            # or retaining the erased receiver/callback bodies in the program.
            known_classes = set(self.module.classes) | {
                value for module in self.module.entry_module.container.values()
                for value in module.scope.names.values()
                if isinstance(value, Class) and not value.container.scope.is_builtins
            }
            for function, target, receiver, node in erased_methods:
                builtin_listener = target.py_func is native_builtins._WebElement.addEventListener
                implementation = WebElement.addEventListener if builtin_listener else target.py_func
                overriding_types = {
                    value for value in known_classes
                    if collection_ops.is_layout_subclass(value, target.cls)
                    and getattr(value.py_obj, target.name, None) is not implementation
                }
                semantic = analyzed_value_type(receiver)
                if builtin_listener:
                    dom_ops.check_dispatch(self, semantic, target.name, node,
                                           candidates=overriding_types)
                elif any(collection_ops.is_layout_subclass(value, member)
                         for value in overriding_types for member in get_type_members(semantic)):
                    raise LLVMUnsupported(
                        f"LLVM erased {target.name} overrides require a concrete application method call", node)
                if overriding_types and dom_ops.requires_checked_receiver(receiver, function):
                    detail = (f"; copy narrowed local {receiver.id!r} to a new local"
                              if isinstance(receiver, ast.Name) else "")
                    raise LLVMUnsupported(
                        ("erased listener" if builtin_listener else f"erased {target.name}")
                        + " receiver requires a proven type; bind the checked receiver first" + detail,
                        node)
        self.module.uses_native = (
            bool(self.module.native_functions)
            or bool(self.module.custom_element_types)
            or any(
                layout.value_type.container.name == "pyjs.native"
                for layout in program.classes
            )
        )
        if self.module.uses_native:
            self.module.uses_collections = True
            self.module.uses_strings = True
            for value in ("class", "div", "p", "span"):
                self.string_constant(value)
            for value_type in self.module.custom_element_types:
                if name := value_type.py_obj.__pyjs_ssr_tag_name__:
                    self.string_constant(name)
                if any(item.value_type in {int, float} for item in dom_state.fields(value_type).values()):
                    # Descriptor reads parse attribute text without an AST int/
                    # float call for the ordinary dependency scan to discover.
                    self.module.uses_numeric_text = self.module.uses_unicode = self.module.uses_exception_repr = True
            if self.module.custom_element_types:
                self.string_constant("data-self-id")
                self.string_constant("ce")
            for function in self.module.native_functions:
                decoration = get_native_decoration(function.py_func)
                if decoration is None:
                    continue
                if decoration.operation == "element" and decoration.constant is not None:
                    self.string_constant(decoration.constant)
                elif decoration.operation == "class_attribute":
                    self.module.uses_mappings = True
                elif decoration.operation == "reference":
                    self.module.uses_dom_references = True
                elif decoration.operation == "render_document":
                    self.string_constant("<!doctype html>\n")

    def prepare_strings(
        self,
        classes: list[ClassIR],
        functions: list[Function],
    ) -> None:
        def annotation_is_string(annotation) -> bool:
            return isinstance(annotation, ast.Name) and annotation.id in {"str", "bytes"}

        self.module.uses_strings = (
            self.module.uses_strings
            or any(
                getattr(nullable.member(field.value_type) or field.value_type, "generic_name", None) in {"str", "bytes"}
                for layout in classes
                for field in layout.fields
            )
            or any(
                annotation_is_string(function.return_type.annotation)
                or any(
                    annotation_is_string(argument.annotation)
                    for argument in function.params
                )
                for function in functions
            )
        )
        for function in functions:
            for block in function.ir.blocks:
                if not isinstance(block, Block):
                    continue
                for statement in block.body:
                    for node in ast.walk(statement):
                        # Module constants are inlined during emission; their
                        # initializer is not a child of the referring Name or
                        # Attribute, so ast.walk alone cannot see its string.
                        static = getattr(getattr(node, "obj", None), "static_value", None)
                        if isinstance(static, ast.Constant) and isinstance(static.value, (str, bytes)):
                            self.string_constant(static.value)
                            self.module.uses_strings = True
                        if isinstance(node, ast.Call):
                            target = getattr(node.func, "obj", None)
                            if isinstance(target, Class) and target.py_obj is native_builtins._bytes:
                                self.module.uses_text_extra = True
                            if (isinstance(target, Function) and
                                    (target.py_func is native_builtins._repr or target.name in {"__str__", "__repr__"})
                                    or isinstance(target, Class) and target.py_obj is native_builtins._str):
                                source = representation.argument(target, node)
                                if source is not None and getattr(analyzed_value_type(source), "generic_name", None) == "bytes":
                                    self.module.uses_text_extra = True
                            if (isinstance(target, Function) and target.name in {"partition", "rpartition"}
                                    and getattr(target.cls, "py_obj", None) in {native_builtins._str, native_builtins._bytes}):
                                self.tuple_type(analyzed_value_type(node))
                            if isinstance(target, Function) and target.py_func is native_builtins._pow:
                                self.module.uses_modular_pow |= len(node.args) == 3
                            if isinstance(target, Class) and target.py_obj in {native_builtins._int, native_builtins._float}:
                                self.module.uses_float |= target.generic_name == "float"
                                argument_type = analyzed_value_type(node.args[0]) if node.args else None
                                argument_types = get_type_members(argument_type) if argument_type is not None else ()
                                argument_storage = {enum_ops.storage_name(member) for member in argument_types}
                                if argument_storage & {"str", "bytes"}:
                                    self.module.uses_numeric_text = True
                                    self.module.uses_unicode = True
                                    self.module.uses_strings = True
                                    self.module.uses_text_extra |= "bytes" in argument_storage
                                    self.string_constant(runtime_numeric.WHITESPACE)
                        if isinstance(node, ast.Attribute):
                            owner = getattr(getattr(node, "obj", None), "cls", None)
                            if getattr(owner, "generic_name", None) == "list" and node.attr in {
                                "__contains__", "count", "index", "remove",
                            }:
                                self.module.uses_sequence_search = True
                                self.module.uses_strings = True
                            if getattr(owner, "py_obj", None) in {native_builtins._str, native_builtins._bytes}:
                                binary = owner.py_obj is native_builtins._bytes
                                self.module.uses_unicode |= not binary and node.attr in runtime_text.UNICODE_METHODS
                                self.module.uses_text_edit |= node.attr in runtime_text.EDIT_METHODS
                                self.module.uses_text_extra |= binary or node.attr in runtime_text.EXTRA_METHODS
                                if node.attr in {"strip", "lstrip", "rstrip", "split", "rsplit"}:
                                    self.string_constant(runtime_text.BYTE_WHITESPACE if binary else runtime_text.WHITESPACE)
                                if node.attr in {"split", "rsplit"}:
                                    self.module.uses_collections = True
                                    self.module.uses_string_split = True
                        if isinstance(node, ast.Constant) and isinstance(
                            node.value,
                            (str, bytes),
                        ):
                            self.string_constant(node.value)
                            self.module.uses_strings = True
        if self.module.uses_text_extra:
            self.module.uses_text_edit = True
            self.module.uses_strings = True
            self.module.uses_collections = True
        if self.module.uses_strings:
            for value in ("", "True", "False"):
                self.string_constant(value)

    def collection_type_definitions(self) -> list[str]:
        output = [
            "%pyjs.list = type { i64, i64, ptr, ptr, ptr, i64 }",
            "%pyjs.dict = type { i64, i64, ptr, ptr, ptr, ptr, ptr, i64, ptr, ptr }",
            "%pyjs.set = type { i64, i64, ptr, ptr, ptr, ptr }",
            "%pyjs.mapping.view = type { ptr }",
            "%pyjs.sequence.iterator = type { ptr, i64 }",
            "%pyjs.range.iterator = type { i64, i64, i64 }",
            "%pyjs.range = type { i64, i64, i64 }",
        ]
        return output

    def string_definitions(self) -> list[str]:
        output = ["%pyjs.string = type { i64, ptr }"]
        for value, name in self.module.string_constants.items():
            encoded = value if isinstance(value, bytes) else value.encode()
            stored = encoded or b"\0"
            output.append(
                f"@{name}.data = private constant [{len(stored)} x i8] "
                f'c"{self.llvm_bytes(stored)}"'
            )
            output.append(
                f"@{name} = private constant %pyjs.string "
                f"{{ i64 {len(encoded)}, ptr @{name}.data }}"
            )
        output.append('@pyjs.string.int.format = private constant [5 x i8] c"%lld\\00"')
        return output

    def class_definition(self, layout: ClassIR) -> str:
        fields = self.class_storage(layout.value_type)
        return f"%{self.class_name(layout.value_type)} = type {{ {', '.join(fields)} }}"

    def class_storage(self, value_type):
        """One field sequence for emitted layouts and their GC descriptors."""
        fields = []
        if value_type in self.module.vtable_roots:
            fields.append("ptr")
        if value_type in self.module.custom_element_types:
            fields.extend(("ptr", "i64"))  # DOM node and initialization phase.
        if self.module.uses_dom_references and self.is_proxy_element_type(value_type):
            fields.append("i64")  # Wrapper-owned hydration marker, not a DOM marker.
        fields.extend(
            self.storage_type(field.value_type, field.numeric_format)
            for field in self.module.layout_fields[value_type]
        )
        return tuple(fields)

    def prepare_object_layouts(
        self,
        classes: list[ClassIR],
        functions: list[Function],
    ) -> None:
        visiting = set()

        def field_source(layout, name):
            declaration = layout.value_type.field_declaration_nodes.get(name)
            if declaration is not None:
                return declaration
            # Instance annotations usually live in __init__, not in the
            # class declaration map. Only scan when validating an override.
            constructor = layout.constructor
            if constructor is not None and constructor.original_node is not None:
                source = constructor.original_node
                positional = source.args.posonlyargs + source.args.args
                if positional:
                    receiver = positional[0].arg
                    for node in ast.walk(source):
                        if (isinstance(node, ast.Attribute) and node.attr == name
                                and isinstance(node.ctx, ast.Store)
                                and isinstance(node.value, ast.Name) and node.value.id == receiver):
                            return node
            return layout.value_type.annotation

        def inherited_fields(value_type: Class):
            if self.is_proxy_element_type(value_type):
                python_type = value_type.py_obj
                if (any("__pyjs_ref__" in owner.__dict__ for owner in python_type.__mro__)
                        or any(field.name == "__pyjs_ref__" for field in self.module.classes[value_type].fields)):
                    raise LLVMUnsupported("LLVM proxy reference markers must be managed by ref(), not declared or accessed directly",
                                          value_type.annotation)
                if (any("element" in owner.__dict__ for owner in python_type.__mro__)
                        or python_type.__getattribute__ is not object.__getattribute__
                        or python_type.__setattr__ is not object.__setattr__
                        or hasattr(python_type, "__getattr__")):
                    raise LLVMUnsupported("LLVM proxy element requires an ordinary instance field, not class defaults or custom attribute access",
                                          value_type.annotation)
            if value_type.generic_name == "NoneType":
                # Null lowering still has name-based paths beyond formatting.
                # Do not partially accept this name and emit invalid void values.
                raise LLVMUnsupported("LLVM application classes named NoneType are not supported; rename the class",
                                      value_type.annotation)
            existing = self.module.layout_fields.get(value_type)
            if existing is not None:
                return existing
            if value_type in visiting:
                raise LLVMUnsupported("LLVM class inheritance contains a cycle")
            visiting.add(value_type)
            layout = self.module.classes[value_type]
            fields = []
            if dom_types.is_browser_declaration(layout.base):
                raise LLVMUnsupported("LLVM cannot inherit browser-only declarations", value_type.annotation)
            if getattr(layout.base, "py_obj", None) is native_builtins._WebTokenList:
                # A token view is one arena-owned DOM pointer, not an ordinary
                # application layout. Inherited native accessors cannot read
                # a subclass payload as that view, even if it has no fields.
                raise LLVMUnsupported("LLVM DOMTokenList subclasses are not supported; obtain a view from element.classList",
                                      value_type.annotation)
            if (layout.base is not None and layout.base.container.scope.is_builtins
                    and layout.base.generic_name in {"list", "dict", "tuple", "str", "bytes", "set", "frozenset"}):
                # Application field layouts do not embed builtin collection
                # headers. Silently inheriting their methods would read the
                # wrong storage, even for an empty subclass with no fields.
                raise LLVMUnsupported("LLVM subclasses of builtin containers are not supported",
                                      value_type.annotation)
            if layout.base in self.module.classes:
                fields.extend(inherited_fields(layout.base))
            elif (
                layout.base is not None
                and self.is_application_module(layout.base.container)
            ):
                raise LLVMUnsupported(
                    f"LLVM cannot resolve base class {layout.base.name}"
                )
            indexes = {field.name: index for index, field in enumerate(fields)}
            for field in layout.fields:
                if dom_state.field(self, value_type, field.name) is not None:
                    continue  # The descriptor reads DOM attributes, not a shadow slot.
                index = indexes.get(field.name)
                if index is None:
                    indexes[field.name] = len(fields)
                    fields.append(field)
                elif self.storage_type(
                    fields[index].value_type,
                    fields[index].numeric_format,
                ) != self.storage_type(field.value_type, field.numeric_format):
                    raise LLVMUnsupported(
                        f"LLVM field {value_type.name}.{field.name} changes type",
                        field_source(layout, field.name),
                    )
                else:
                    # Both declarations can write this slot. Equal ABI width
                    # and a one-way payload upcast do not establish invariance.
                    collection_ops.require_declaration_layout(
                        field.value_type, fields[index].value_type,
                        field_source(layout, field.name),
                        invariant=True, actual_representation=field.representation,
                        expected_representation=fields[index].representation,
                    )
            visiting.remove(value_type)
            if self.is_proxy_element_type(value_type):
                element = next(field for field in fields if field.name == "element")
                if not self.is_web_element_type(element.value_type):
                    raise LLVMUnsupported("LLVM proxy element must be a non-optional Element field",
                                          value_type.annotation)
            result = tuple(fields)
            self.module.layout_fields[value_type] = result
            return result

        for layout in classes:
            if (self.is_web_element_type(layout.value_type)
                    and not self.is_opaque_web_element_type(layout.value_type)
                    and layout.value_type not in self.module.custom_element_types):
                raise LLVMUnsupported("LLVM application DOM subclasses must derive from CustomElement",
                                      layout.value_type.annotation)
            if layout.value_type in self.module.custom_element_types:
                try:
                    dom_state.validate(self, layout.value_type)
                except LLVMUnsupported as error:
                    error.add_class_context(layout.value_type)
                    raise
            inherited_fields(layout.value_type)

        self.module.methods = {
            (function.cls, properties.dispatch_name(function)): function
            for function in functions
            if function.cls in self.module.classes
            and function.name != "__init__"
            and not function.is_static
        }
        virtual_names: dict[Class, set[str]] = {}
        for value_type in self.module.custom_element_types:
            # Element views can retain this wrapper without its static class.
            # The known identity header distinguishes it from a plain DOM node.
            virtual_names.setdefault(self.hierarchy_root(value_type), set())
        retained_payloads = any(collection_ops.builtin_name(domain) != "NoneType"
                                for domains in self.module.exception_formats.values() for domain in domains)
        if self.module.uses_erased_objects and (retained_payloads or object_values.needs_headers(functions)):
            # An object-typed pointer has no static layout. Give application
            # leaves the same identity header as polymorphic families; never
            # read a payload field (or a one-byte empty instance) as a type.
            # Retained exception messages are implicit object-erasure consumers.
            for value_type in self.module.classes:
                virtual_names.setdefault(self.hierarchy_root(value_type), set())
        # A polymorphic family needs runtime identity even without overridden
        # methods (for isinstance and widening a base pointer into a union).
        # Reuse the dispatch header; unrelated leaf records keep their ABI.
        for value_type, layout in self.module.classes.items():
            if layout.base in self.module.classes:
                virtual_names.setdefault(self.hierarchy_root(value_type), set())
        # Protocol compatibility can cross nominal roots (e.g. Sized[bool] and
        # Sized[int]). Use runtime_protocol's selectors AND grouping: default
        # truth/hash can share one implementation across several classes and
        # must not acquire an unnecessary header that breaks host-record ABI.
        # Erased receivers with a builtin fallback already have headers above.
        from . import numeric_protocols
        selectors = {
            ("__bool__", "__len__"): self.truth_method,
            ("__len__",): self.length_method,
            ("__hash__",): lambda candidate, node: hashing.method(self, candidate, node),
            ("__index__",): lambda candidate, node: calls.implicit_method(candidate, "__index__", node),
            ("__round__",): lambda candidate, node: calls.implicit_method(candidate, "__round__", node),
            ("__int__", "__index__"): lambda candidate, node: numeric_protocols.select(candidate, False, node),
            ("__float__", "__index__"): lambda candidate, node: numeric_protocols.select(candidate, True, node),
            ("__bytes__", "__index__", "__iter__"): lambda candidate, node: candidate,
        }
        for receiver, names in self.module.entry_function.runtime_dunder_dependencies:
            if receiver is not None and names == ("close",):
                # Delegation selects optional close from an open cursor view.
                # Even a single implementation needs identity: another source
                # may omit close, and a plain leaf otherwise has no header.
                for candidate in protocols.cursor_types(self.module):
                    if any(protocols.compatible_source(self, candidate, member)
                           for member in get_type_members(receiver)):
                        virtual_names.setdefault(self.hierarchy_root(candidate), set())
            select = selectors.get(names)
            if receiver is None or select is None:
                continue
            if names in {("__bytes__", "__index__", "__iter__"), ("__hash__",)} and any(
                    iterable_views.is_view(member) or iterator_ops.is_iterator(member)
                    for member in get_type_members(receiver)):
                # Handles form an open runtime domain: even a single known
                # protocol arm must verify the source's identity. Give
                # every reachable application cursor a safe identity header.
                for candidate in protocols.cursor_types(self.module):
                    virtual_names.setdefault(self.hierarchy_root(candidate), set())
            for member in get_type_members(receiver):
                try:
                    compatible = is_subclass
                    if names in {("__bytes__", "__index__", "__iter__"), ("__hash__",)}:
                        from .protocols import compatible_source
                        def compatible(candidate, target):
                            return compatible_source(self, candidate, target)
                    groups = calls.protocol_groups(self, member,
                                                   lambda candidate, select=select: select(candidate, candidate.annotation),
                                                   compatible=compatible)
                except LLVMUnsupported:
                    # Reachability can retain unused protocols (e.g. hash for
                    # an empty typed set). Emission validates actual consumers
                    # with their source location; an unsupported dispatch will
                    # fail there before it can use a missing identity header.
                    continue
                if len(groups) > 1:
                    for candidates in groups.values():
                        for candidate in candidates:
                            virtual_names.setdefault(self.hierarchy_root(candidate), set())
        for value_type, name in self.module.methods:
            base = self.module.classes[value_type].base
            if (base in self.module.classes and value_type in self.module.custom_element_types
                    and name in {"textContent", "textContent.setter"}):
                # The DOM default has no emitted function/virtual slot. A
                # wrapper-typed base can still select an introduced accessor
                # by runtime class; properties.access uses this identity header.
                virtual_names.setdefault(self.hierarchy_root(value_type), set())
            if (name in comparisons.REFLECTED or name in {"__repr__", "__str__", "__format__"}) and any(
                    other is not value_type and is_subclass(other, self.hierarchy_root(value_type))
                    for other in self.module.classes):
                # Comparisons and object.__str__ fallback depend on the runtime
                # class, even when a subclass inherits the implementation.
                virtual_names.setdefault(self.hierarchy_root(value_type), set()).add(name)
            while base in self.module.classes:
                inherited = self.module.methods.get((base, name))
                if inherited is not None:
                    implementation = self.module.methods[value_type, name]
                    # Declaration validation below checks result covariance
                    # and storage together, including supported fixed/variadic
                    # tuple views that nominal return compatibility rejects.
                    # Shared named slots retain their invariant ABI. Renamed
                    # or reordered slots bind only after selecting the body;
                    # their actual supplied values are checked at that call.
                    same_parameters = (tuple(item.arg for item in calls.parameters(implementation)) ==
                                       tuple(item.arg for item in calls.parameters(inherited)))
                    if (same_parameters and self.method_signature(implementation)[0] != self.method_signature(inherited)[0]
                            or not same_analyzer_type(implementation.return_type, inherited.return_type)
                            and callable_adapters.plain_builtin(implementation.return_type)
                            and callable_adapters.plain_builtin(inherited.return_type)):
                        raise LLVMUnsupported(
                            f"LLVM override {value_type.name}.{name} must preserve "
                            "the base method signature"
                        )
                    for actual, expected in (zip(
                        calls.parameters(implementation), calls.parameters(inherited),
                        strict=True,
                    ) if same_parameters else ()):
                        dom_ops.require_matching_abi(self, actual.annotation.obj, expected.annotation.obj,
                                                     implementation.original_node)
                        # Base-bound arguments flow into the implementation:
                        # parameter layouts are checked opposite to results.
                        collection_ops.require_declaration_layout(
                            expected.annotation.obj, actual.annotation.obj,
                            implementation.original_node,
                            actual_representation=analyzed_representation(expected),
                            expected_representation=analyzed_representation(actual),
                        )
                    dom_ops.require_matching_abi(self, implementation.return_type, inherited.return_type,
                                                 implementation.original_node)
                    actual_callback = nullable.member(implementation.return_type) or implementation.return_type
                    expected_callback = nullable.member(inherited.return_type) or inherited.return_type
                    if nullable.is_object(inherited.return_type):
                        # Selected virtual results can box their concrete value;
                        # fields and base-bound parameters cannot change storage.
                        collection_ops.require_matching_layout(
                            implementation.return_type, inherited.return_type,
                            implementation.original_node)
                    elif (callable_adapters.compatible(actual_callback, expected_callback)
                          and is_return_type_compatible(inherited.return_type, implementation.return_type)):
                        # A selected result can wrap a returned callable; the
                        # base and derived bodies need not expose identical
                        # descriptor call ABIs. Fields/parameters stay invariant.
                        callable_adapters.check_view(actual_callback, expected_callback, implementation.original_node)
                    else:
                        collection_ops.require_declaration_layout(
                            implementation.return_type, inherited.return_type,
                            implementation.original_node,
                            actual_representation=implementation.return_representation,
                            expected_representation=inherited.return_representation,
                        )
                    virtual_names.setdefault(self.hierarchy_root(value_type), set()).add(
                        name
                    )
                    break
                base = self.module.classes[base].base

        for root, names in virtual_names.items():
            slots = tuple(sorted(names))
            self.module.vtable_slots[root] = slots
            for value_type in self.module.classes:
                if self.hierarchy_root(value_type) is root:
                    self.module.vtable_roots[value_type] = root
                    entries = tuple(
                        self.resolve_method(value_type, name) for name in slots
                    )
                    self.module.vtable_entries[value_type] = entries
                    for index, implementation in enumerate(entries):
                        if implementation is not None:
                            self.module.virtual_methods[implementation] = (root, index)
            for index in range(len(slots)):
                # A builtin reference and an erased box are both ptr, but have
                # different semantics. Select the body before boxing either
                # scalar or reference results into an object declaration.
                # Callable descriptors also share ptr but can expose different
                # parameter/result ABIs, requiring a selected-result adapter.
                results = {(self.method_signature(entries[index])[1],
                            nullable.is_object(entries[index].return_type),
                            union_type_key(entries[index].return_type)
                            if isinstance(nullable.member(entries[index].return_type) or entries[index].return_type,
                                          CallableClass) else None)
                           for value_type, entries in self.module.vtable_entries.items()
                           if self.module.vtable_roots[value_type] is root and entries[index] is not None}
                if len(results) > 1:
                    self.module.adapted_virtual_slots.add((root, index))
                bindings = {calls.binding_signature(entries[index])
                            for value_type, entries in self.module.vtable_entries.items()
                            if self.module.vtable_roots[value_type] is root and entries[index] is not None}
                if len(bindings) > 1:
                    # These slots are identities, not a shared raw call ABI.
                    # Every call must select and bind the concrete declaration.
                    self.module.rebound_virtual_slots.add((root, index))

    def method_signature(self, function: Function) -> tuple[tuple[str, ...], str]:
        return (
            tuple(
                self.annotation_storage_type(
                    parameter.annotation,
                    analyzed_numeric_format(parameter),
                )
                for parameter in calls.parameters(function)
            ),
            self.result_storage_type(
                function.return_type,
                function.return_numeric_format,
            ),
        )

    def hierarchy_root(self, value_type: Class) -> Class:
        root = value_type
        while self.module.classes[root].base in self.module.classes:
            root = self.module.classes[root].base
        return root

    def resolve_method(
        self,
        value_type: Class,
        name: str,
    ) -> Function | None:
        current = value_type
        while current in self.module.classes:
            implementation = self.module.methods.get((current, name))
            if implementation is not None:
                return implementation
            current = self.module.classes[current].base
        return None

    def vtable_definitions(
        self,
        classes: list[ClassIR],
    ) -> list[str]:
        output = []
        for root, slots in self.module.vtable_slots.items():
            # The first word is a parent type identity, followed by method
            # slots and the closed-union tag. Erased-object ancestry can reuse
            # this table without adding a second header to every instance.
            fields = ", ".join(["ptr", *("ptr" for _slot in slots), "i64"])
            output.append(f"%{self.vtable_type(root)} = type {{ {fields} }}")
            for layout in classes:
                value_type = layout.value_type
                if self.module.vtable_roots.get(value_type) is not root:
                    continue
                parent = layout.base
                values = [f"ptr @{self.vtable_name(parent)}" if parent in self.module.vtable_roots else "ptr null"]
                values.extend(
                    (
                        "ptr null"
                        if implementation is None
                        else f"ptr @{self.function_name(implementation)}"
                    )
                    for implementation in self.module.vtable_entries[value_type]
                )
                # A distinct class tag makes even an empty method table carry
                # address-significant storage and permits constant-time tagging.
                values.append(f"i64 {tagged.tag(self, value_type)}")
                output.append(
                    f"@{self.vtable_name(value_type)} = private constant "
                    f"%{self.vtable_type(root)} "
                    f"{{ {', '.join(values)} }}"
                )
        return output

    @staticmethod
    def is_runtime_helper(function: Function) -> bool:
        decoration = get_native_decoration(function.py_func)
        return decoration is not None and decoration.kind == "runtime"

    def function(self, function: Function) -> list[str]:
        try:
            return self.function_definition(function)
        except LLVMUnsupported as error:
            error.add_function_context(function)
            raise

    def function_definition(self, function: Function) -> list[str]:
        if self.is_runtime_helper(function):
            from .runtime.compiler import validate_runtime_helper

            validate_runtime_helper(function, self)
            module = copy(self.module)
            module.uses_arena = module.uses_gc = module.uses_exceptions = False
            emitter = FunctionEmitter(module)
            try:
                lines = emitter.function_implementation(function)
            except LLVMUnsupported as error:
                raise LLVMUnsupported(
                    f"runtime helper {function.name}: {error}",
                    function.original_node,
                ) from error
            except KeyError as error:
                if error.args[0] not in {"__arena", "__heap", "__exception"}:
                    raise
                raise LLVMUnsupported(
                    "runtime helpers cannot allocate, collect or raise",
                    function.original_node,
                ) from error
            validate_runtime_helper(function, emitter, lines)
            self.runtime_helper_calls.update(emitter.runtime_helper_calls)
            return lines
        if function in self.module.generators:
            factory = self.function_implementation(function)
            return [generators.definition(self.module.generators[function]), *factory,
                    *FunctionEmitter(self.module).function_implementation(function, resume=True)]
        return self.function_implementation(function)

    def function_implementation(self, function: Function, *, resume=False) -> list[str]:
        self.current_function = function
        self.has_inline_calls = False
        self.generator_frame = self.module.generators.get(function) if resume else None
        factory = function in self.module.generators and not resume
        self.stack_allocations = []
        if function.is_async:
            raise LLVMUnsupported("LLVM async functions are not implemented")

        blocks = [block for block in function.ir.blocks if isinstance(block, Block)]
        if not blocks:
            raise LLVMUnsupported(f"LLVM function {function.name} has no blocks")
        if factory:
            blocks = generators.factory_blocks(function)
        return_type = self.result_storage_type(function.return_type, None)
        self.return_type = return_type
        self.return_storage_type = self.result_storage_type(
            function.return_type,
            function.return_numeric_format,
        )
        parameters = []
        if self.module.uses_arena:
            parameters.append(("__arena", "ptr"))
        if self.module.uses_gc:
            parameters.append(("__heap", "ptr"))
        if self.module.uses_exceptions:
            parameters.append(("__exception", "ptr"))
        if function in self.module.closures:
            parameters.append(("__closure.context", "ptr"))
        if function.cls in self.module.classes and not function.is_static:
            parameters.append(("self", "ptr"))
        parameters.extend(
            (
                argument.arg,
                self.annotation_storage_type(
                    argument.annotation,
                    analyzed_numeric_format(argument),
                ),
            )
            for argument in calls.parameters(function)
        )
        local_parameters = parameters
        if resume:
            self.return_type = self.return_storage_type = "i64"
            parameters = [item for item in parameters if item[0] in {"__arena", "__heap", "__exception"}]
            parameters += [("__generator.state", "ptr"), ("__generator.output", "ptr")]
            local_parameters = [*local_parameters, *parameters[-2:]]
        signature = ", ".join(
            f"{value_type} %{self.name(name, 'arg')}" for name, value_type in parameters
        )

        self.temporary = 0
        self.lines = []
        self.iterators = {}
        self.value_semantics = {}
        self.value_representations = {}
        self.slot_types = self.local_types(function, local_parameters)
        if factory:
            generators.layout(self)
        elif resume:
            self.slot_types["__generator.input"] = self.value_type(self.generator_frame.input_type)
        expression_root_names = {}
        exception_roots = {block.exception_target: set() for block in blocks if block.exception_target}
        has_expanded_calls = False
        if self.module.uses_gc:
            for block in blocks:
                for statement in block.body:
                    inlined_range = self.inline_range_constructor(statement) if isinstance(statement, IteratorCreate) else None
                    for node in closures.walk(statement):
                        if isinstance(node, ast.Call) and calls.expands_arguments(node):
                            has_expanded_calls = True
                        # Iterator emission consumes this constructor's bounds
                        # directly, not a range object. Still visit every bound:
                        # index callbacks and their arguments can need roots.
                        if node is inlined_range:
                            continue
                        # Loaded pointers also outlive their source: a later
                        # argument can replace the field and collect its old value.
                        if isinstance(node, (ast.expr, BlockArgument)) and (
                            id(node) not in expression_root_names
                        ):
                            if not hasattr(node, "obj"):
                                continue
                            value_type = analyzed_value_object(node)
                            if isinstance(value_type, Function):
                                if not isinstance(node, (ast.Name, ast.Attribute)) or value_type not in self.module.callables:
                                    continue
                                value_type = callable_value_type(node)
                            elif isinstance(value_type, Instance):
                                value_type = value_type.cls
                            elif not isinstance(value_type, (Class, UnionType)) or (
                                isinstance(value_type, Class) and isinstance(node, (ast.Name, ast.Attribute))
                            ):
                                # Type references have no runtime value;
                                # don't instantiate type[T] during emission.
                                # A union-valued property is already its result
                                # type, not a class declaration, and needs a root.
                                continue
                            try:
                                value_type = self.value_type(value_type)
                            except LLVMUnsupported:
                                # Actual unsupported values still fail during
                                # expression emission, not this metadata walk.
                                continue
                            if value_type not in {"ptr", tagged.STORAGE}:
                                continue
                            name = f"__expression_{len(expression_root_names)}"
                            expression_root_names[id(node)] = name
                            self.slot_types[name] = "ptr"
                        if block.exception_target and (name := expression_root_names.get(id(node))) is not None:
                            exception_roots[block.exception_target].add(name)
        self.slots = {name: f"%{self.name(name, 'slot')}" for name in self.slot_types}
        self.expression_roots = {
            node_id: self.slots[name]
            for node_id, name in expression_root_names.items()
        }
        self.gc_frame = None
        catches = [node for block in blocks for node in block.body if isinstance(node, ExceptionCatch)]
        self.exception_snapshots = {}
        block_map = {block.name: block for block in blocks}
        dead_iterators = iterator_ops.dead_roots(blocks) if self.module.uses_gc else {}
        result = [
            f"define {self.return_storage_type} "
            f"@{self.function_name(function)}{'.resume' if resume else ''}({signature}) {{"
        ]
        for index, block in enumerate(blocks):
            result.append("generator.entry:" if resume and index == 0 else f"{self.name(block.name, 'block')}:")
            self.lines = []
            self.exception_target = block.exception_target
            if index and block.name in exception_roots:
                self.restore_gc_frame()
                # A failed statement cannot resume its operands. Saved locals
                # and the exception record own values needed by the handler.
                # Completed statements already clear their own roots. Only
                # protected blocks can leave operands here; clearing the whole
                # function at each handler creates quadratic generated code.
                for name in sorted(exception_roots[block.name]):
                    self.emit_line(f"store ptr null, ptr {self.slots[name]}")
            if index == 0:
                # Keeping mutable values in slots maps CFG edges directly and lets
                # LLVM's mem2reg pass form SSA without a second PyJS graph traversal.
                parameter_names = {name for name, _ in parameters}
                for name, value_type in self.slot_types.items():
                    if value_type == "void":
                        continue
                    if resume and (name in self.generator_frame.fields or name in closures.bindings(self)):
                        continue
                    self.emit_line(f"{self.slots[name]} = alloca {value_type}")
                    # Every pointer slot is visible to the conservative collector.
                    # Initialize it before a safe point can inspect locals that have
                    # not yet been assigned on the current control-flow path.
                    # Incoming arguments are assigned below before any safe
                    # point. Do not first zero their slots: ASan recognizes
                    # argument stores and hoists them, which would leave the
                    # redundant zero store overwriting the actual argument.
                    if name not in parameter_names and (value_type in {"ptr", tagged.STORAGE} or factory):
                        initial = "null" if value_type == "ptr" else "zeroinitializer"
                        self.emit_line(f"store {value_type} {initial}, ptr {self.slots[name]}")
                for name, value_type in parameters:
                    self.emit_line(
                        f"store {value_type} %{self.name(name, 'arg')}, "
                        f"ptr {self.slots[name]}"
                    )
                for catch in (() if resume else catches):
                    snapshot = self.emit_value("alloca %pyjs.exception")
                    self.emit_line(f"store %pyjs.exception zeroinitializer, ptr {snapshot}")
                    self.exception_snapshots[id(catch)] = snapshot
                if resume:
                    generators.enter(self)
                if self.module.uses_gc:
                    roots = [
                        tagged.root_slot(self, self.slot_types[name], slot)
                        for name, slot in self.slots.items()
                        if self.slot_types[name] in {"ptr", tagged.STORAGE}
                        and name not in {"__arena", "__heap", "__exception"}
                    ]
                    if self.module.uses_exceptions:
                        roots.extend(self.exception_field(index) for index in (3, 5))
                        roots.extend(self.exception_field(index, snapshot)
                                     for snapshot in self.exception_snapshots.values() for index in (3, 5))
                    # Even without ordinary roots, binding failures must unwind
                    # temporary argument frames to a permanent function frame.
                    if roots or has_expanded_calls:
                        root_slots = self.new_temporary()
                        self.gc_frame = self.new_temporary()
                        self.emit_line(f"{root_slots} = alloca [{len(roots)} x ptr]")
                        for root_index, root in enumerate(roots):
                            root_slot = self.new_temporary()
                            self.emit_line(
                                f"{root_slot} = getelementptr [{len(roots)} x ptr], "
                                f"ptr {root_slots}, i32 0, i32 {root_index}"
                            )
                            self.emit_line(f"store ptr {root}, ptr {root_slot}")
                        self.emit_line(f"{self.gc_frame} = alloca %pyjs.gc.frame")
                        self.emit_line(
                            "call void @pyjs.gc.frame.push("
                            f"ptr {self.load_local('__heap')}, "
                            f"ptr {self.gc_frame}, ptr {root_slots}, "
                            f"i64 {len(roots)})"
                        )
                if resume:
                    generators.dispatch(self, block.name)
                else:
                    closures.initialize(self, parameters)
            for name in dead_iterators.get(block.name, ()):
                self.emit_line(f"store ptr null, ptr {self.slots[name]}")
            for statement in block.body:
                if self.module.uses_gc:
                    self.emit_line(
                        "call void @pyjs.gc.maybe.collect("
                        f"ptr {self.load_local('__heap')})"
                    )
                self.statement(statement, block_map)
                if self.expression_roots and not isinstance(statement, Terminator) and self.lines[-1] != "unreachable":
                    self.clear_expression_roots(statement)
            result.extend(f"  {line}" for line in self.lines)
        if self.module.uses_exceptions:
            result.append("pyjs.exception.return:")
            self.lines = []
            self.restore_gc_frame()
            if resume:
                generators.failed(self)
            self.pop_gc_frame()
            default = "null" if self.return_storage_type == "ptr" else "0.0" if self.return_storage_type in {"double", "float"} else "0"
            if nullable.payload_kind(self.return_storage_type) or self.return_storage_type == tagged.STORAGE:
                default = "zeroinitializer"
            default = getattr(function, "exception_result", default)
            if resume:
                default = str(iterator_ops.runtime.CALLBACK_ERROR)
            if default == str(iterator_ops.runtime.CALLBACK_ERROR):
                # Iterator adapters need to distinguish a pending StopIteration
                # from other checked-ABI failures without erasing its payload.
                default = iterator_callbacks.failure_status(self)
            self.emit_line("ret void" if self.return_storage_type == "void" else f"ret {self.return_storage_type} {default}")
            result.extend(f"  {line}" for line in self.lines)
        result[2:2] = [f"  {line}" for line in self.stack_allocations]
        self.stack_allocations = None
        result.append("}")
        if self.module.uses_gc and not resume and not self.has_inline_calls:
            result = self.omit_leaf_gc_polls(result)
        return result

    @staticmethod
    def omit_leaf_gc_polls(lines: list[str]) -> list[str]:
        # Inspect the lowered body, not the Python signature: even scalar
        # operations can invoke user code. This local scan needs no extra
        # call-graph pass. Unknown/indirect calls and assembly keep all polls.
        body = "\n".join(lines)
        noncollecting_call = re.compile(
            r"call void @(?:pyjs\.gc\.(?:maybe\.collect|frame\.(?:push|pop))\(|llvm\.trap\(\))"
        )
        if any(noncollecting_call.match(body, call.start()) is None
               for call in re.finditer(r"\b(?:call|invoke|callbr)\b", body)):
            return lines
        # Preserve roots and the hidden ABI. The caller still polls; no
        # allocation within this leaf can increase collection debt.
        return [line for line in lines if not line.startswith("  call void @pyjs.gc.maybe.collect(")]

    def local_types(
        self,
        function: Function,
        parameters: list[tuple[str, str]],
    ) -> dict[str, str]:
        result = dict(parameters)
        # Seed declared layouts, then propagate tagged inferred views over all
        # writes and joins before emission, including forward copies/backedges.
        self.slot_types = result
        self.slot_numeric_formats = {
            parameter.arg: analyzed_numeric_format(parameter)
            for parameter in calls.parameters(function)
            if analyzed_numeric_format(parameter) is not None
        }

        def add_target(target, value_type: str) -> None:
            if isinstance(target, (ast.Name, ast.arg)):
                name = target.id if isinstance(target, ast.Name) else target.arg
                local = self.local_storage_binding(target)
                if isinstance(local, Instance) and (nullable.is_object(local.cls) or nullable.member(local.cls) or (
                    tagged.members(local.cls) and not self.is_runtime_helper(function)
                )):
                    # Raw runtime helpers use branch-local borrowed bytes and
                    # Pointer views with the same ptr ABI. Their scalar-only
                    # contract does not introduce managed union storage.
                    value_type = self.value_type(local.cls)
                result.setdefault(
                    name,
                    value_type,
                )
            elif isinstance(target, (ast.List, ast.Tuple)):
                raise LLVMUnsupported("LLVM unpacking is not implemented", target)
            elif isinstance(target, ast.Attribute) and getattr(target, "property_setters", ()):
                return  # Accessor calls do not introduce a local storage slot.
            else:
                raise LLVMUnsupported("unsupported LLVM assignment target", target)

        for block in function.ir.blocks:
            if not isinstance(block, Block):
                continue
            for argument in block.arguments:
                storage_format = analyzed_numeric_format(argument)
                result.setdefault(
                    argument.name,
                    self.storage_type(argument.value_type, storage_format),
                )
                if storage_format is not None:
                    self.slot_numeric_formats[argument.name] = storage_format
            for statement in block.body:
                if isinstance(statement, ast.AnnAssign):
                    if isinstance(statement.value, CollectionNew):
                        # Use the resolved allocation type: the synthesized
                        # tuple__ annotation has no corresponding source name.
                        self.require_concrete_allocation(statement.value)
                    storage_format = self.local_numeric_format(statement.target)
                    # Resolved declarations survive builtin/type-name shadowing;
                    # synthesized annotation spellings need not be in scope.
                    # Raw helper unions retain branch-local pointer views;
                    # concrete inferred types (including private i128) still
                    # use the binding when their spelling is not in scope.
                    binding = (self.local_storage_binding(statement.target)
                               if isinstance(statement.target, ast.Name) else None)
                    if (self.is_runtime_helper(function) and isinstance(binding, Instance)
                            and isinstance(binding.cls, UnionType)):
                        binding = None
                    add_target(
                        statement.target,
                        self.storage_type(statement.value.value_type, storage_format)
                        if isinstance(statement.value, CollectionNew)
                        else self.storage_type(binding.cls, storage_format)
                        if isinstance(binding, Instance)
                        else self.annotation_storage_type(
                            statement.annotation,
                            storage_format,
                        ),
                    )
                    if storage_format is not None:
                        self.slot_numeric_formats[self.target_name(statement.target)] = (
                            storage_format
                        )
                elif isinstance(statement, ast.Assign):
                    value_type = self.expression_type(statement.value)
                    for target in statement.targets:
                        if isinstance(target, (ast.List, ast.Tuple)):
                            self.add_iterator_target(result, target, analyzed_value_type(statement.value))
                        else:
                            add_target(target, value_type)
                elif isinstance(statement, ExceptionCatch):
                    add_target(statement.target, "ptr")
                elif isinstance(statement, IteratorCreate):
                    result[statement.name] = "ptr"
                    self.iterators[statement.name] = self.iterator_descriptor(statement)
                    if self.iterators[statement.name][0] in {"dictionary", "set", *collection_ops.VIEWS}:
                        result[f"{statement.name}.length"] = "i64"
                elif isinstance(statement, IteratorNext):
                    descriptor = self.iterators[statement.iterator]
                    storage_format = self.local_numeric_format(statement.target)
                    if storage_format is not None and isinstance(
                        statement.target,
                        (ast.Name, ast.arg),
                    ):
                        result[self.target_name(statement.target)] = (
                            self.numeric_storage_type(storage_format)
                        )
                    else:
                        self.add_iterator_target(
                            result,
                            statement.target,
                            descriptor[1],
                        )
                    if storage_format is not None:
                        self.slot_numeric_formats[self.target_name(statement.target)] = (
                            storage_format
                        )
        closures.prepare_locals(self)
        tagged.infer_local_storage(self, function, result)
        closures.record_storage(self)
        return result

    def iterator_descriptor(self, node: IteratorCreate):
        value_type = analyzed_value_type(node.iterable)
        if not isinstance(value_type, Class):
            raise LLVMUnsupported("LLVM iteration requires a concrete iterable type; narrow unions before use", node)
        if (iterator_ops.is_iterator(value_type) or iterable_views.is_view(value_type) or getattr(value_type, "tuple_variadic", False)
                or value_type in self.module.classes):
            return "lazy", collection_ops.item_type(value_type)
        if value_type.generic_name in collection_ops.VIEWS | {"str", "bytes", "tuple"}:
            if value_type.generic_name == "tuple":
                # The analyzer types an empty loop target as object. Retain
                # that declaration, but never emit a load or assignment for it.
                member = (collection_ops.item_type(value_type) if value_type.generic_types
                          else NATIVE_ENVIRONMENT.builtins.search("object"))
                return "tuple", member, value_type
            return value_type.generic_name, collection_ops.item_type(value_type)
        if analyzed_value_type(node.iterable).generic_name == "range":
            return "range", NATIVE_ENVIRONMENT.builtins.search("int")
        if (
            isinstance(node.iterable, ast.Call)
            and isinstance(node.iterable.func, ast.Attribute)
            and isinstance(getattr(node.iterable.func, "obj", None), Function)
            and node.iterable.func.obj.name == "keys"
        ):
            dictionary_type = analyzed_value_type(node.iterable.func.value)
            if dictionary_type.generic_name == "dict":
                key_type, _value_type = self.dictionary_types(dictionary_type)
                return "dictionary", key_type
        iterable_type = analyzed_value_type(node.iterable)
        if iterable_type.generic_name == "dict":
            key_type, _value_type = self.dictionary_types(iterable_type)
            return "dictionary", key_type
        if iterable_type.generic_name in {"set", "frozenset"}:
            return "set", self.set_item_type(iterable_type)
        if iterable_type.generic_name != "list":
            raise LLVMUnsupported(
                f"LLVM cannot iterate over {iterable_type.name}",
                node,
            )
        try:
            item_type = next(iter(iterable_type.generic_types.values()))
        except StopIteration:
            raise LLVMUnsupported("LLVM list item type is not concrete", node) from None
        return "sequence", item_type

    def add_iterator_target(self, result, target, item_type) -> None:
        if isinstance(target, (ast.Name, ast.arg)):
            name = self.target_name(target)
            declared = self.local_storage_binding(target)
            storage = self.value_type(declared.cls if isinstance(declared, Instance)
                                      and declared.has_declared_type else item_type)
            # Inferred names share one physical slot across loops. Reserve a
            # tag and payload if any loop needs them, even if the first loop
            # only writes a scalar or pointer. Reads retain each loop's type.
            if storage == tagged.STORAGE:
                result[name] = storage
            else:
                result.setdefault(name, storage)
            return
        if not isinstance(target, (ast.List, ast.Tuple)):
            raise LLVMUnsupported("unsupported LLVM iterator target", target)
        if item_type.generic_name != "tuple":
            raise LLVMUnsupported("LLVM can only unpack tuple items", target)
        item_types = tuple(item_type.generic_types.values())
        if len(item_types) != len(target.elts):
            raise LLVMUnsupported("LLVM tuple unpacking length differs", target)
        for element, element_type in zip(target.elts, item_types, strict=True):
            self.add_iterator_target(result, element, element_type)

    def statement(self, node: ast.stmt, blocks: dict[str, Block]) -> None:
        self.allocation_node = node
        if isinstance(node, Suspend):
            generators.suspend(self, node)
            return
        if isinstance(node, Return) and self.generator_frame is not None:
            generators.complete(self, node)
            return
        if isinstance(node, (ExceptionRaise, ExceptionDispatch, ExceptionCatch)):
            self.exception_statement(node)
            return
        if isinstance(node, Return):
            if node.value is None or (
                isinstance(node.value, ast.Constant) and node.value.value is None
            ):
                if self.module.uses_exceptions and not is_return_type_compatible(
                    self.current_function.return_type,
                    NATIVE_ENVIRONMENT.builtins.search("NoneType"),
                ):
                    # Nominal return inference intentionally does not infer
                    # exception effects. A manager may nevertheless suppress a
                    # throwing return expression and reach this implicit None.
                    # Enforce the result contract on that executed path, before
                    # callers can interpret a null as a non-optional reference.
                    # Unchecked runtime kernels retain their raw status/null ABI.
                    source = node if hasattr(node, "lineno") else self.current_function.original_node
                    self.raise_error(source, "TypeError",
                                     f"{self.current_function.name} returned None through a non-optional result contract")
                    return
                if self.return_type in {"ptr", tagged.STORAGE} or nullable.payload_kind(self.return_type):
                    self.pop_gc_frame()
                    self.emit_line(f"ret {self.return_type} zeroinitializer")
                    return
                if self.return_type != "void":
                    raise LLVMUnsupported(
                        f"cannot return void from {self.return_type} function",
                        node,
                    )
                self.pop_gc_frame()
                self.emit_line("ret void")
            else:
                value_type, value = self.expression(node.value)
                if self.return_type == "void":
                    self.pop_gc_frame()
                    self.emit_line("ret void")
                    return
                collection_ops.require_matching_layout(self.runtime_value_type(node.value), self.current_function.return_type, node.value)
                value_type, value = self.coerce_value(value_type, value, self.return_type, node.value,
                                                      semantic=self.current_function.return_type,
                                                      representation=self.current_function.return_representation)
                stored_type, stored = self.narrow_numeric(
                    value_type,
                    value,
                    self.return_storage_type,
                    node.value,
                )
                self.pop_gc_frame()
                self.emit_line(f"ret {stored_type} {stored}")
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.require_target_layout(node.target, self.runtime_value_type(node.value))
                self.store(node.target, *self.expression(node.value))
            return
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], (ast.List, ast.Tuple)):
                self.assign_iterator_target(node.targets[0], analyzed_value_type(node.value), self.expression(node.value)[1])
                return
            self.require_target_layout(node.targets[0], self.runtime_value_type(node.value))
            self.store(node.targets[0], *self.expression(node.value))
            return
        if isinstance(node, FieldStore):
            # Python evaluates the value before resolving an assignment target.
            collection_ops.require_matching_layout(analyzed_value_type(node.value), analyzed_value_type(node.target), node)
            value_type, value = self.expression(node.value)
            if properties.reject_super_write(self, node.target):
                return
            if tagged.members(analyzed_value_type(node.target.value)):
                tagged.field_access(self, node.target, (value_type, value), analyzed_value_type(node.value))
                return
            receiver_type = analyzed_value_type(node.target.value)
            receiver_kind, receiver = self.expression(node.target.value)
            if receiver_kind != "ptr":
                raise LLVMUnsupported("LLVM field receiver is not an object", node.target)
            if descriptor := dom_state.field(self, receiver_type, node.target.attr):
                dom_state.write(self, receiver_type, receiver, descriptor, (value_type, value), node.target)
                return
            field_type, declared, field = self.field_pointer(node.target, (receiver_type, receiver))
            dom_ops.bind_reference(self, receiver_type, receiver, node.target.attr,
                                   (value_type, value), node.target)
            declared_type = declared.value_type
            semantic_type = self.value_type(declared_type)
            value_type, value = self.coerce_value(value_type, value, semantic_type, node, semantic=declared_type,
                                                 representation=declared.representation)
            stored_type, stored = self.narrow_numeric(
                value_type,
                value,
                field_type,
                node,
            )
            self.emit_line(f"store {stored_type} {stored}, ptr {field}")
            return
        if isinstance(node, ast.Expr):
            self.expression(node.value)
            return
        if isinstance(node, ListAppend):
            self.list_append(node)
            return
        if isinstance(node, IteratorCreate):
            self.iterator_create(node)
            return
        if isinstance(node, Branch):
            value_type, value = self.expression(node.test)
            # The analyzed truth protocol may use __len__, yielding an integer.
            if (isinstance(node.test, ast.Call)
                    and getattr(analyzed_value_object(node.test.func), "name", None) == "__len__"):
                if value_type not in {"i1", "i64"}:
                    raise LLVMUnsupported("LLVM length-based conditions require an integer result", node.test)
                if value_type == "i64":
                    self.guard_exception(node.test, self.emit_value(f"icmp sge i64 {value}, 0"),
                                         "ValueError", "__len__() should return >= 0")
                value = self.truth_value(node.test, value_type, value)
            elif value_type != "i1":
                # __bool__ results must not undergo another truth conversion.
                raise LLVMUnsupported("LLVM branch conditions require bool; __bool__ must return bool", node.test)
            self.clear_expression_roots(node)
            self.emit_line(
                f"br i1 {value}, label %{self.name(node.true, 'block')}, "
                f"label %{self.name(node.false, 'block')}"
            )
            return
        if isinstance(node, Jump):
            target = blocks[node.target]
            for argument, value in zip(
                target.arguments,
                node.arguments,
                strict=True,
            ):
                self.store(argument, *self.expression(value))
            self.clear_expression_roots(node)
            self.emit_line(f"br label %{self.name(node.target, 'block')}")
            return
        if isinstance(node, IteratorNext):
            self.iterator_next(node)
            return
        raise LLVMUnsupported(
            f"unsupported LLVM statement {type(node).__name__}",
            node,
        )

    def pop_gc_frame(self) -> None:
        if self.gc_frame is not None:
            self.emit_line(
                "call void @pyjs.gc.frame.pop("
                f"ptr {self.load_local('__heap')}, ptr {self.gc_frame})"
            )

    def require_target_layout(self, target, value_type) -> None:
        if isinstance(target, (ast.Name, ast.arg)):
            local = self.local_storage_binding(target)
            expected = local.cls if isinstance(local, Instance) else None
        elif hasattr(target, "obj"):
            expected = analyzed_value_type(target)
        else:
            return
        if expected is not None:
            collection_ops.require_matching_layout(value_type, expected, target)

    def store(self, target: ast.expr, value_type: str, value: str) -> None:
        if isinstance(target, ast.Attribute) and getattr(target, "property_setters", ()):
            properties.access(self, target, (value_type, value))
            return
        name = self.target_name(target)
        expected = self.slot_types[name]
        if value_type == expected == "void":
            closures.mark_initialized(self, name)
            return
        semantic_type = self.semantic_storage_type(
            expected,
            self.slot_numeric_formats.get(name),
        )
        declared = self.local_storage_binding(target)
        destination = getattr(declared, "cls", None)
        if destination is None and hasattr(target, "obj"):
            # Lowered branch joins are block arguments rather than authored
            # locals. Their semantic storage still determines object boxing.
            destination = analyzed_value_type(target)
        value_type, value = self.coerce_value(value_type, value, semantic_type, target,
                                             semantic=destination,
                                             representation=analyzed_representation(declared or target))
        stored_type, stored = self.narrow_numeric(
            value_type,
            value,
            expected,
            target,
        )
        self.emit_line(f"store {stored_type} {stored}, ptr {self.slots[name]}")
        closures.mark_initialized(self, name)

    def expression(self, node: ast.expr, *, check_layout=True) -> tuple[str, str]:
        # Kind-only consumers inspect a common header, never element storage.
        # This applies only to the requested value; nested calls and explicit
        # casts retain their ordinary complete layout checks.
        previous = getattr(self, "allocation_node", None)
        self.allocation_node = node
        try:
            value_type, value = self.expression_value(node, check_layout=check_layout)
            # Runtime binary and union-method arms already convert each callee
            # before joining. The first arm's declaration is not the joined
            # result: reapplying it would reinterpret or reject a valid box.
            project_call = (isinstance(node, ast.Call) and not getattr(node, "binary_methods", None)
                            and not getattr(node.func, "class_lookup", False)
                            and not getattr(node.func, "union_functions", ())
                            and calls.static_receiver(node, self.module.functions) is None)
            if project_call:
                value_type, value = calls.project_result(
                    self, getattr(node.func, "obj", None), value_type, value, node, check_layout=check_layout)
            if value_type == tagged.STORAGE:
                from . import type_queries
                if type_queries.proven_integer(node, self.current_function.scope):
                    actual, bits = tagged.parts(self, value)
                    exact = self.emit_value(f"icmp eq i64 {actual}, {tagged.TAGS['int']}")
                    self.guard_exception(node, exact, "TypeError", "value changed after exact type narrowing")
                    value_type, value = "i64", bits
            tagged.remember(self, node, value_type, value)
            if value_type == "ptr" and getattr(self.value_semantics.get((value_type, value)), "generic_name", None) == "NoneType":
                # None-valued expressions need no operand. Typed storage and
                # direct callback consumers materialize the null slot instead.
                value_type, value = "void", ""
            root = self.expression_roots.get(id(node))
            if root is not None:
                if value_type == "ptr":
                    self.emit_line(f"store ptr {value}, ptr {root}")
                elif value_type == tagged.STORAGE:
                    bits = self.emit_value(f"extractvalue {tagged.STORAGE} {value}, 1")
                    pointer = self.emit_value(f"inttoptr i64 {bits} to ptr")
                    self.emit_line(f"store ptr {pointer}, ptr {root}")
            return value_type, value
        finally:
            self.allocation_node = previous

    def clear_expression_roots(self, statement):
        # The result now belongs to a local, field, iterator or block argument.
        # Scratch roots protect operand evaluation, not the rest of the frame.
        if self.expression_roots:
            for node in ast.walk(statement):
                root = self.expression_roots.get(id(node))
                if root is not None:
                    self.emit_line(f"store ptr null, ptr {root}")

    def expression_value(self, node: ast.expr, *, check_layout=True) -> tuple[str, str]:
        if isinstance(node, callables.BindMethod):
            return "ptr", callables.select_bound(self, node.reference, node.source, self.load_local("receiver"))
        if isinstance(node, callables.ReferenceInvoke):
            return callables.invoke_reference(self, node)
        if isinstance(node, callable_adapters.Invoke):
            return callable_adapters.invoke(self, node)
        if isinstance(node, partials.Invoke):
            return partials.invoke(self, node)
        if isinstance(node, iterator_views.Operation):
            return iterator_views.operation(self, node)
        if isinstance(node, iterable_views.Operation):
            return iterable_views.operation(self, node)
        if isinstance(node, slices.Assignment):
            return slices.assignment(self, node)
        if result := enum_ops.member(self, node):
            return result
        if isinstance(node, object_values.ResultProjection):
            _, value = self.expression(node.value)
            return object_values.project(self, value, analyzed_value_type(node), node)
        if isinstance(node, (ast.Name, ast.Attribute)):
            if entry := self.module.persistent_values.get(getattr(node, "obj", None)):
                return persistent.load(self, entry, node)
        if isinstance(node, tagged.Value):
            return node.kind, node.value
        if isinstance(node, StaticCast):
            object_values.check_static_cast(node, classes=self.module.classes)
            kind, value = self.expression(node.value)
            expected = analyzed_value_type(node)
            actual = analyzed_value_type(node.value)
            if nullable.is_object(actual):
                return object_values.narrow(self, value, expected, node)
            if isinstance(actual, UnionType):
                return calls.project_value(
                    self, actual, analyzed_representation(node.value),
                    kind, value, node, description="cast")
            # DOM upcasts use wrapper-to-node conversion, not application
            # pointer identity; validation above does not perform conversion.
            return self.coerce_value(kind, value, self.value_type(expected), node.value, semantic=expected,
                                     representation=analyzed_representation(node))
        if isinstance(node, ChainedCompare):
            return self.chained_comparison(node)
        if isinstance(node, generators.Create):
            return generators.create(self, node)
        if isinstance(node, GeneratorInput):
            return generators.receive(self, node)
        if isinstance(node, iterator_callbacks.Advance):
            return iterator_callbacks.advance(self, node)
        if isinstance(node, protocols.Advance):
            return protocols.advance(self, node)
        if isinstance(node, Comprehension):
            return comprehensions.expression(self, node)
        if isinstance(node, ast.Lambda):
            return closures.reference(self, node)
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(getattr(node, "obj", None), Function):
            return callables.reference(self, node)
        attribute = node.attribute if isinstance(node, FieldLoad) else node
        if result := enum_ops.attribute(self, attribute):
            return result
        if result := class_constants.read(self, attribute):
            return result
        if (isinstance(attribute, ast.Attribute)
                and collection_ops.builtin_name(analyzed_value_type(attribute.value)) == "slice"
                and attribute.attr in slices.FIELDS):
            _, receiver = self.expression(attribute.value)
            return tagged.STORAGE, slices.field(self, receiver, slices.FIELDS.index(attribute.attr))
        if (isinstance(attribute, ast.Attribute) and attribute.attr == "value"
                and all(isinstance(member, Class)
                        and is_subclass(member, NATIVE_ENVIRONMENT.builtins.search("StopIteration"))
                        for member in get_type_members(analyzed_value_type(attribute.value)))):
            _, receiver = self.expression(attribute.value)
            if getattr(attribute, "native_typed_completion", False):
                value = self.emit_value(f"load ptr, ptr {self.exception_field(5, receiver)}")
            else:
                value = exception_values.erased_payload(self, receiver, node,
                    "StopIteration.value cannot erase represented scalar arithmetic; "
                    "convert the completion explicitly or use typed delegation")
            # The snapshot always stores an object, even when flow analysis
            # narrowed this repeated attribute read to a concrete payload.
            return object_values.narrow(self, value, analyzed_value_type(node), node, check_layout=check_layout)
        if (isinstance(attribute, ast.Attribute)
                and getattr(analyzed_value_type(attribute.value), "generic_name", None) == "range"
                and attribute.attr in {"start", "stop", "step"}):
            _, receiver = self.expression(attribute.value)
            return "i64", self.range_values(receiver)[("start", "stop", "step").index(attribute.attr)]
        if isinstance(node, ast.Constant):
            if node.value is NotImplemented:
                self.module.uses_not_implemented = True
                return "ptr", "@pyjs.not_implemented"
            if node.value is None:
                return "void", ""
            if node.value is True:
                return "i1", "1"
            if node.value is False:
                return "i1", "0"
            if isinstance(node.value, int):
                return self.normalize_integer_result(str(node.value), node)
            if isinstance(node.value, float):
                value = f"0x{struct.pack('>d', node.value).hex().upper()}"
                return self.normalize_float_result(value, node)
            if isinstance(node.value, (str, bytes)):
                return "ptr", f"@{self.string_constant(node.value)}"
            raise LLVMUnsupported(
                f"unsupported LLVM constant {node.value!r}",
                node,
            )
        if isinstance(node, (ast.Name, BlockArgument)):
            name = node.id if isinstance(node, ast.Name) else node.name
            value = getattr(node, "obj", None)
            if isinstance(value, Class) and self.is_exception_type(value):
                self.module.exception_types.add(value)
                return "ptr", f"@{self.exception_token_name(value)}"
            if isinstance(value, (Class, GenericClass)):
                raise LLVMUnsupported("LLVM class objects are not runtime values", node)
            if (
                name not in self.slots and isinstance(value, Instance)
                and isinstance(value.container, Module)
                and isinstance(value.static_value, ast.Constant)
            ):
                return self.expression(value.static_value)
            kind, loaded = self.load(name)
            narrowed = analyzed_value_type(node)
            if kind == tagged.STORAGE and not tagged.members(narrowed):
                return tagged.narrow(self, loaded, narrowed, node)
            if kind == tagged.STORAGE:
                declared = self.local_storage_binding(node)
                if converted := dom_ops.read(self, getattr(declared, "cls", None), narrowed, kind, loaded, node):
                    return converted
            if kind == "ptr" or nullable.payload_kind(kind):
                declared = self.local_storage_binding(node)
                declared_type = getattr(declared, "cls", None)
                closure = self.module.closures.get(self.current_function)
                if closure is not None and name in closure.captures:
                    # The live outer scope can be rebound while typing cleanup
                    # paths. Capture metadata owns the cell's storage contract.
                    declared_type = closure.captures[name].value_type
                if converted := callable_adapters.read(self, declared_type, narrowed, kind, loaded, node):
                    return converted
                if converted := iterator_views.read(self, declared_type, narrowed, kind, loaded, node,
                                                    representation=analyzed_representation(declared)):
                    return converted
                if converted := iterable_views.read(self, declared_type, narrowed, kind, loaded, node,
                                                    representation=analyzed_representation(declared)):
                    return converted
            if not nullable.member(narrowed) and (kind == "ptr" or nullable.payload_kind(kind)):
                if nullable.is_object(declared_type):
                    return object_values.narrow(self, loaded, narrowed, node, check_layout=check_layout)
                if nullable.payload_kind(kind) or nullable.member(declared_type):
                    # Locals can be changed through captured cells as well as direct
                    # writes. Retain a checked boundary even after flow analysis.
                    nullable.check_narrowing(self, kind, loaded, narrowed, node, f"local {name}")
                if converted := dom_ops.read(self, declared_type, narrowed, kind, loaded, node):
                    return converted
            if getattr(narrowed, "generic_name", None) == "NoneType":
                return "void", ""
            if nullable.payload_kind(kind):
                return self.coerce_value(kind, loaded, self.value_type(narrowed), node)
            return kind, loaded
        if isinstance(node, ast.Attribute):
            if getattr(node, "property_getters", ()):
                return properties.access(self, node, check_layout=check_layout)
            value = getattr(node, "obj", None)
            if (isinstance(value, Instance) and isinstance(value.container, Module)
                    and isinstance(value.static_value, ast.Constant)):
                return self.expression(value.static_value)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, EvaluateOnce):
            return self.evaluate_once(node)
        if isinstance(node, ast.BoolOp):
            return self.boolean_operation(node)
        if isinstance(node, ast.IfExp):
            return self.conditional_expression(node)
        if isinstance(node, ast.UnaryOp):
            value_type, value = self.expression(node.operand)
            if not isinstance(node.op, ast.Not):
                value_type, value = tagged.numeric(self, node.operand, value_type, value)
            if isinstance(node.op, ast.UAdd) and value_type in {"i64", "double"}:
                return value_type, value
            if isinstance(node.op, ast.USub) and value_type == "i64":
                result = self.new_temporary()
                self.emit_line(f"{result} = sub i64 0, {value}")
                return self.normalize_integer_result(result, node)
            if isinstance(node.op, ast.Invert) and value_type == "i64":
                result = self.new_temporary()
                self.emit_line(f"{result} = xor i64 {value}, -1")
                return self.normalize_integer_result(result, node)
            if isinstance(node.op, ast.USub) and value_type == "double":
                result = self.new_temporary()
                self.emit_line(f"{result} = fneg double {value}")
                return self.normalize_float_result(result, node)
            if isinstance(node.op, ast.Not) and value_type == "i1":
                result = self.new_temporary()
                self.emit_line(f"{result} = xor i1 {value}, true")
                return "i1", result
            raise LLVMUnsupported("unsupported LLVM unary operation", node)
        if isinstance(node, ast.JoinedStr):
            return self.joined_string(node)
        if isinstance(node, ObjectNew):
            return self.object_new(node)
        if isinstance(node, CollectionNew):
            return self.collection_new(node)
        if isinstance(node, ListAppend):
            self.list_append(node)
            return "void", ""
        if isinstance(node, FieldLoad):
            if tagged.members(analyzed_value_type(node.attribute.value)):
                return tagged.field_access(self, node.attribute)
            semantic = analyzed_value_type(node.attribute.value)
            if descriptor := dom_state.field(self, semantic, node.attribute.attr):
                _, receiver = self.expression(node.attribute.value)
                return dom_state.read(self, semantic, receiver, descriptor, node.attribute)
            properties.check_super_field_read(self, node.attribute)
            field_type, declared, field = self.field_pointer(node.attribute)
            declared_type = declared.value_type
            result = self.new_temporary()
            self.emit_line(f"{result} = load {field_type}, ptr {field}")
            dom_ops.check_proxy_field(self, semantic, node.attribute.attr, result, node.attribute)
            kind, result = self.widen_numeric(field_type, result, declared.numeric_format)
            narrowed = analyzed_value_type(node)
            if kind == tagged.STORAGE and not tagged.members(narrowed):
                return tagged.narrow(self, result, narrowed, node)
            if nullable.member(declared_type) and not nullable.member(narrowed):
                # Attribute narrowing is not a lifetime proof: an intervening
                # call or alias can change the field. Never unbox/dereference
                # stale storage on the strength of the analyzer's flow type.
                nullable.check_narrowing(self, kind, result, narrowed, node.attribute,
                                         f"field {node.attribute.attr}")
            if nullable.is_object(declared_type):
                return object_values.narrow(self, result, narrowed, node, check_layout=check_layout)
            if converted := iterator_views.read(self, declared_type, narrowed, kind, result, node,
                                                representation=declared.representation):
                return converted
            if converted := dom_ops.read(self, declared_type, narrowed, kind, result, node):
                return converted
            if getattr(analyzed_value_type(node), "generic_name", None) == "NoneType":
                return "void", ""
            if nullable.payload_kind(kind):
                return self.coerce_value(kind, result, self.value_type(analyzed_value_type(node)), node)
            return kind, result
        raise LLVMUnsupported(
            f"unsupported LLVM expression {type(node).__name__}",
            node,
        )

    def chained_comparison(self, node):
        kinds = [self.expression_type(value) for value in node.operands]
        if "void" in kinds:
            raise LLVMUnsupported("LLVM chained comparisons require concrete operand values", node)
        slots, frame = calls.value_slots(self, kinds)
        previous_slots, previous_types = self.slots.copy(), self.slot_types.copy()
        previous_formats = self.slot_numeric_formats.copy()
        result = self.emit_value("alloca i1")
        self.emit_line(f"store i1 false, ptr {result}")
        done = self.new_label("compare.done")
        try:
            # Analyzer temporaries are lexical to this expression. Nested
            # chains can reuse their names; retain values and roots separately.
            for temporary, slot, kind in zip(node.temporaries, slots, kinds, strict=True):
                self.slots[temporary.id] = slot
                self.slot_types[temporary.id] = kind
                self.slot_numeric_formats.pop(temporary.id, None)
            for index, operand in enumerate(node.operands):
                kind, value = self.expression(operand)
                if kind == "void":
                    kind, value = self.coerce_value(kind, value, kinds[index], operand)
                self.emit_line(f"store {kind} {value}, ptr {slots[index]}")
                if index:
                    kind, matched = self.expression(node.comparisons[index - 1])
                    if kind != "i1":
                        raise LLVMUnsupported("LLVM chained comparisons must return bool", node)
                    following = self.new_label("compare.next")
                    self.emit_line(f"br i1 {matched}, label %{following}, label %{done}")
                    self.emit_line(f"{following}:")
            self.emit_line(f"store i1 true, ptr {result}")
            self.emit_line(f"br label %{done}")
            self.emit_line(f"{done}:")
            calls.pop_roots(self, frame)
            return "i1", self.emit_value(f"load i1, ptr {result}")
        finally:
            self.slots, self.slot_types = previous_slots, previous_types
            self.slot_numeric_formats = previous_formats

    def evaluate_once(self, node: EvaluateOnce) -> tuple[str, str]:
        kind, value = self.expression(node.value)
        if kind == "void":
            kind, value = self.coerce_value(kind, value, self.expression_type(node.value), node.value)
        slots, frame = calls.value_slots(self, [kind])
        self.emit_line(f"store {kind} {value}, ptr {slots[0]}")
        name = node.parameter
        previous = self.slots.get(name), self.slot_types.get(name)
        self.slots[name], self.slot_types[name] = slots[0], kind
        try:
            # A lexical binding, not a function local: nested short-circuit
            # expressions may reuse the same synthesized parameter name.
            # Its root spans the truth callback and only the selected arm.
            return self.expression(node.body)
        finally:
            if previous[1] is None:
                self.slots.pop(name)
                self.slot_types.pop(name)
            else:
                self.slots[name], self.slot_types[name] = previous
            calls.pop_roots(self, frame)

    def boolean_operation(self, node: ast.BoolOp) -> tuple[str, str]:
        """Lower Python's value-returning, short-circuit boolean operators."""
        if len(node.values) < 2:
            raise LLVMUnsupported("LLVM boolean operation has too few values", node)
        # Analyzer-generated boolean trees (notably tuple-form isinstance)
        # deliberately carry their type on each operand rather than the
        # synthetic BoolOp itself. Source BoolOps retain their merged type.
        result_value_type = (
            analyzed_value_type(node)
            if hasattr(node, "obj")
            else analyzed_value_type(node.values[0])
        )
        result_type = (tagged.STORAGE if hasattr(node, "obj")
                       and tagged.narrowed_integer(node, self.slot_types, self.module.functions, scope=self.current_function.scope)
                       else self.value_type(result_value_type))
        result_slot = self.new_temporary()
        done = self.new_label("boolean.done")
        self.emit_line(f"{result_slot} = alloca {result_type}")
        for index, value_node in enumerate(node.values):
            value_type, value = self.expression(value_node)
            truth = (
                self.truth_value(value_node, value_type, value)
                if index != len(node.values) - 1
                else None
            )
            stored_type, stored = self.coerce_numeric(
                value_type,
                value,
                result_type,
                value_node,
            )
            self.emit_line(f"store {stored_type} {stored}, ptr {result_slot}")
            if index == len(node.values) - 1:
                self.emit_line(f"br label %{done}")
                break
            assert truth is not None
            next_value = self.new_label("boolean.next")
            if isinstance(node.op, ast.And):
                self.emit_line(
                    f"br i1 {truth}, label %{next_value}, label %{done}"
                )
            else:
                self.emit_line(
                    f"br i1 {truth}, label %{done}, label %{next_value}"
                )
            self.emit_line(f"{next_value}:")
        self.emit_line(f"{done}:")
        result = self.emit_value(f"load {result_type}, ptr {result_slot}")
        return result_type, result

    def conditional_expression(self, node: ast.IfExp) -> tuple[str, str]:
        """Lower a value-producing conditional without evaluating both arms."""
        test_type, test = self.expression(node.test)
        if test_type != "i1":
            raise LLVMUnsupported("LLVM conditional test must be bool", node.test)
        result_type = self.expression_type(node)
        result_slot = self.new_temporary()
        body = self.new_label("conditional.body")
        orelse = self.new_label("conditional.else")
        done = self.new_label("conditional.done")
        if result_type != "void":
            self.emit_line(f"{result_slot} = alloca {result_type}")
        self.emit_line(f"br i1 {test}, label %{body}, label %{orelse}")
        self.emit_line(f"{body}:")
        body_type, body_value = self.coerce_numeric(
            *self.expression(node.body),
            result_type,
            node.body,
            semantic=analyzed_value_type(node),
        )
        if result_type != "void":
            self.emit_line(f"store {body_type} {body_value}, ptr {result_slot}")
        self.emit_line(f"br label %{done}")
        self.emit_line(f"{orelse}:")
        else_type, else_value = self.coerce_numeric(
            *self.expression(node.orelse),
            result_type,
            node.orelse,
            semantic=analyzed_value_type(node),
        )
        if result_type != "void":
            self.emit_line(f"store {else_type} {else_value}, ptr {result_slot}")
        self.emit_line(f"br label %{done}")
        self.emit_line(f"{done}:")
        if result_type == "void":
            return "void", ""
        result = self.emit_value(f"load {result_type}, ptr {result_slot}")
        if result_type == "i64":
            return self.normalize_integer_result(result, node)
        if result_type == "double":
            return self.normalize_float_result(result, node)
        return result_type, result

    def truth_value(self, node: ast.expr, value_type: str, value: str) -> str:
        semantic = tagged.effective_type(analyzed_value_type(node), value_type)
        if nullable.is_object(semantic):
            return object_values.truth(self, value, node)
        if value_type == tagged.STORAGE:
            return tagged.dispatch(self, semantic, value, "i1",
                                   lambda member, kind, payload: self.truth_value(nullable.typed_node(node, member), kind, payload))
        if nullable.member(semantic) is not None:
            return nullable.dispatch(self, semantic, value_type, value, "i1", "false",
                                     lambda member, kind, payload: self.truth_value(nullable.typed_node(node, member), kind, payload))
        if value_type == "void" or getattr(semantic, "generic_name", None) == "NoneType":
            return "false"
        if collection_ops.builtin_name(semantic) == "NotImplementedType":
            self.guard_exception(node, "false", "TypeError", "NotImplemented should not be used in a boolean context")
            return "false"
        if value_type == "i1":
            return value
        if value_type == "i64":
            return self.emit_value(f"icmp ne i64 {value}, 0")
        if value_type == "double":
            return self.emit_value(f"fcmp une double {value}, 0.0")
        if value_type == "ptr" and semantic in self.module.classes:
            # Keep application dispatch ahead of all builtin header shortcuts:
            # names such as range/tuple do not imply a builtin physical layout.
            return calls.runtime_protocol(self, semantic, value, "i1", lambda candidate: self.truth_method(candidate, node),
                                          lambda method: self.application_truth(method, value, node), node)
        if value_type == "ptr" and iterable_views.is_view(semantic):
            return iterable_views.invoke(self, value, node, operation="truth")
        if value_type == "ptr" and analyzed_value_type(node).generic_name == "range":
            arguments = ", ".join(f"i64 {value}" for value in self.range_values(value))
            length = self.emit_value(f"call i128 @pyjs.range.length.i128({arguments})")
            return self.emit_value(f"icmp ne i128 {length}, 0")
        if value_type == "ptr" and analyzed_value_type(node).generic_name == "tuple":
            length = self.emit_value(f"load i64, ptr {value}")
            return self.emit_value(f"icmp ne i64 {length}, 0")
        if value_type == "ptr" and iterator_ops.is_iterator(analyzed_value_type(node)):
            return "true"
        if value_type == "ptr" and collection_ops.builtin_name(semantic) == "slice":
            return "true"
        if value_type == "ptr" and getattr(semantic, "py_obj", None) is native_builtins._WebTokenList:
            return "true"  # DOMTokenList.length is a property, not __len__.
        if value_type == "ptr" and analyzed_value_type(node).generic_name in collection_ops.VIEWS:
            source = self.emit_value(f"load ptr, ptr {value}")
            length = self.emit_value(f"load i64, ptr {source}")
            return self.emit_value(f"icmp ne i64 {length}, 0")
        if value_type == "ptr" and enum_ops.storage_name(analyzed_value_type(node)) in {
            "str", "bytes", "list", "dict", "set", "frozenset",
        }:
            # These headers all begin with the logical length.
            length = self.emit_value(f"load i64, ptr {value}")
            return self.emit_value(f"icmp ne i64 {length}, 0")
        raise LLVMUnsupported("LLVM truth conversion is not implemented for this type", node)

    def truth_method(self, candidate, node):
        for name in ("__bool__", "__len__"):
            declared = candidate.find_attrs(name)
            if isinstance(declared, Function) and declared.cls in self.module.classes:
                if declared.is_static:
                    raise LLVMUnsupported("LLVM truth conversion requires instance special methods", node)
                break  # __bool__ takes precedence over __len__.
        return next((method for name in ("__bool__", "__len__")
                       if (method := self.resolve_method(candidate, name)) is not None), None)

    def application_truth(self, method, value, node):
        if method is None:
            return "true"
        invocation = ast.copy_location(ast.Call(func=ast.Name(id=method.name), args=[], keywords=[]), node)
        with calls.bind(self, method, invocation) as arguments:
            kind, result = calls.invoke(self, method, arguments, node, receiver=value)
        if method.name == "__bool__":
            if kind != "i1":
                raise LLVMUnsupported("LLVM __bool__ must return bool", node)
            return result
        length = self.checked_length(kind, result, node)
        return self.emit_value(f"icmp ne i64 {length}, 0")

    def checked_length(self, kind, result, node):
        if kind not in {"i1", "i64"}:
            raise LLVMUnsupported("LLVM __len__ must return an integer", node)
        if kind == "i1":
            result = self.emit_value(f"zext i1 {result} to i64")
        self.guard_exception(node, self.emit_value(f"icmp sge i64 {result}, 0"),
                             "ValueError", "__len__() should return >= 0")
        return result

    def length_method(self, candidate, node):
        # A disabled override hides an inherited method even when that base
        # implementation is reached elsewhere in the program.
        if getattr(candidate.py_obj, "__len__", None) is None:
            return candidate
        declared = candidate.find_attrs("__len__")
        if not isinstance(declared, Function) or declared.is_static or declared.is_property:
            raise LLVMUnsupported("LLVM len requires an instance __len__ method", node)
        method = self.resolve_method(candidate, "__len__")
        if method is None:
            raise LLVMUnsupported("LLVM len requires a reached instance __len__ implementation", node)
        return method

    def application_length(self, method, value, node):
        if isinstance(method, Class):
            # Keep missing/disabled classes separate in protocol grouping so
            # their checked errors retain Python's concrete type information.
            message = ("'NoneType' object is not callable" if hasattr(method.py_obj, "__len__") else
                       f"object of type '{method.py_obj.__name__}' has no len()")
            self.guard_exception(node, "false", "TypeError", message)
            return "0"
        invocation = ast.copy_location(ast.Call(func=ast.Name(id=method.name), args=[], keywords=[]), node)
        with calls.bind(self, method, invocation) as arguments:
            kind, result = calls.invoke(self, method, arguments, node, receiver=value)
        return self.checked_length(kind, result, node)

    def coerce_value(self, kind: str, value: str, expected: str, node: ast.AST,
                     *, semantic=None, representation=None) -> tuple[str, str]:
        # Source layout lives with the SSA value; a declared destination has
        # its own representation, needed by bidirectional generator adapters.
        enum_ops.check_conversion(self, kind, value, semantic, node)
        if converted := callable_adapters.convert(self, kind, value, semantic, node):
            return converted
        if converted := iterator_views.convert(self, kind, value, semantic, node, representation=representation):
            return converted
        if converted := dom_ops.convert(self, kind, value, semantic, node):
            return converted
        if converted := protocols.convert(self, kind, value, semantic, node):
            return converted
        if converted := iterable_views.convert(self, kind, value, semantic, node, representation=representation):
            return converted
        if getattr(self.value_semantics.get((kind, value)), "generic_name", None) == "NoneType":
            # Loads can carry null-pointer storage while literal/void-call
            # expressions carry no operand. Both denote the same Python None.
            kind, value = "void", ""
        if converted := object_values.convert(self, kind, value, semantic, node):
            return converted
        if converted := tagged.convert(self, kind, value, expected, node, semantic):
            return converted
        if converted := nullable.convert(self, kind, value, expected, node):
            return converted
        if kind == tagged.STORAGE and expected == "i64":
            raise LLVMUnsupported(tagged.INTEGER_BOUNDARY, node)
        raise LLVMUnsupported(f"cannot convert {kind} to {expected}; use an explicit numeric conversion", node)

    def index_integer(self, kind, value, node, description):
        kind, value = tagged.numeric(self, node, kind, value)
        if kind == "i1":
            return self.emit_value(f"zext i1 {value} to i64")
        if kind != "i64":
            raise LLVMUnsupported(description, node)
        return value

    def coerce_numeric(self, kind: str, value: str, expected: str, node: ast.AST,
                       *, semantic=None) -> tuple[str, str]:
        # Arithmetic has explicit promotion rules; annotations/storage do not.
        if kind == "i64" and expected == "double":
            return expected, self.emit_value(f"sitofp i64 {value} to double")
        return self.coerce_value(kind, value, expected, node, semantic=semantic)

    def call(self, node: ast.Call) -> tuple[str, str]:
        if getattr(node.func, "class_lookup", False):
            return calls.class_instance(self, node, analyzed_value_type(node.func.value))
        if getattr(node, "inplace_method", None) is not None:
            from . import inplace
            return inplace.emit(self, node)
        if getattr(node, "binary_methods", None) is not None:
            from . import binary
            return binary.emit(self, node)
        target = getattr(node.func, "obj", None)
        if (len(node.args) == 1 and not node.keywords
                and (isinstance(target, Class) and target.py_obj in {native_builtins._int, native_builtins._float}
                     or isinstance(target, Function) and target.py_func is native_builtins._len)
                and isinstance(self.runtime_value_type(node.args[0]), UnionType)):
            return tagged.builtin_call(self, node)
        if not isinstance(target, Function):
            signature = analyzed_value_object(node.func)
            if isinstance(signature, Instance):
                signature = signature.cls
            if isinstance(signature, CallableClass):
                return callables.invoke(self, node, signature)
        if isinstance(node, ContextExitCall):
            _, receiver = self.expression(node.func.value)
            exception = self.expression(node.exception)[1] if node.exceptional else "null"
            if node.exceptional:
                token = self.emit_value(f"load ptr, ptr {self.exception_field(1, exception)}")
                trace = self.emit_value(f"load ptr, ptr {self.exception_field(2, exception)}")
            else:
                token = trace = "null"
            arguments = calls.BoundCall([("ptr", token), ("ptr", exception), ("ptr", trace)], [None] * 3)
            if target in self.module.virtual_methods:
                return calls.virtual(self, target, receiver, arguments, node)
            return calls.invoke(self, target, arguments, node, receiver=receiver)
        if (isinstance(target, Function) and target.name in {"__is__", "__is_not__"}
                and isinstance(node.func, ast.Attribute) and len(node.args) == 1):
            left_kind, left = self.expression(node.func.value)
            right_kind, right = self.expression(node.args[0])
            # Class tokens are not instances. Do not lazily analyze type[T]
            # during emission just to decide whether DOM unwrapping applies.
            left_type = object_values.instance_type(node.func.value)
            right_type = object_values.instance_type(node.args[0])
            if any(enum_ops.scalar_name(nullable.member(t) or t) for t in (left_type, right_type)):
                same = enum_ops.identity(self, left_type, left_kind, left, right_type, right_kind, right)
                return "i1", self.emit_value(f"xor i1 {same}, true") if target.name == "__is_not__" else same
            if (dom_ops.is_element(self, left_type) or dom_ops.is_element(self, right_type)
                    or self.module.custom_element_types and nullable.is_object(left_type) and nullable.is_object(right_type)):
                left = dom_ops.identity_pointer(self, left_type, left_kind, left, node)
                right = dom_ops.identity_pointer(self, right_type, right_kind, right, node)
                operation = "eq" if target.name == "__is__" else "ne"
                return "i1", self.emit_value(f"icmp {operation} ptr {left}, {right}")
            if tagged.STORAGE in {left_kind, right_kind}:
                # A declaration token cannot be any instance in a tagged
                # union. Both operands were evaluated above; no type[T] or
                # artificial runtime tag is needed for this comparison.
                same = ("false" if left_type is None or right_type is None else
                        tagged.identity(self, (left_kind, left), (right_kind, right), node))
                return "i1", self.emit_value(f"xor i1 {same}, true") if target.name == "__is_not__" else same
            if left_kind == "void" or right_kind == "void":
                present = nullable.present(self, right_kind, right) if left_kind == "void" else nullable.present(self, left_kind, left)
                return "i1", self.emit_value(f"xor i1 {present}, true") if target.name == "__is__" else present
            if {left_kind, right_kind} <= {"i1", nullable.pair("i1")}:
                result = nullable.compare(self, analyzed_value_type(node.func.value), left, analyzed_value_type(node.args[0]), right, node)
                return "i1", self.emit_value(f"xor i1 {result}, true") if target.name == "__is_not__" else result
            for semantic, value, other_type, other_kind, other, source in (
                    (left_type, left, right_type, right_kind, right, node.args[0]),
                    (right_type, right, left_type, left_kind, left, node.func.value)):
                if (nullable.is_object(semantic)
                        and collection_ops.builtin_name(nullable.member(other_type) or other_type) == "bool"):
                    # Boolean boxes are canonical singletons, so this is
                    # allocation-free even for an optional Boolean operand.
                    _, boxed = object_values.convert(self, other_kind, other, semantic, source, actual=other_type)
                    operation = "eq" if target.name == "__is__" else "ne"
                    return "i1", self.emit_value(f"icmp {operation} ptr {value}, {boxed}")
            if left_kind not in {"ptr", "void"} or right_kind not in {"ptr", "void"}:
                raise LLVMUnsupported("native identity requires reference values", node)
            operation = "eq" if target.name == "__is__" else "ne"
            left = identity.pointer(self, left_type, left_kind, left, node.func.value)
            right = identity.pointer(self, right_type, right_kind, right, node.args[0])
            return "i1", self.emit_value(f"icmp {operation} ptr {left if left_kind == 'ptr' else 'null'}, {right if right_kind == 'ptr' else 'null'}")
        if (isinstance(node.func, ast.Attribute) and isinstance(target, Function)
                and target.name == "__str__" and self.is_exception_type(target.cls)):
            _, exception = self.expression(node.func.value)
            return "ptr", exception_values.text(self, exception, node)
        if isinstance(target, Class) and target.py_obj is native_builtins._range:
            return "ptr", self.range_new(self.range_arguments(node))
        if isinstance(target, Class) and target.py_obj is native_builtins._slice:
            return slices.construct(self, node)
        if isinstance(target, Class) and target.py_obj is native_builtins._bytes:
            from .bytes_construction import construct
            return construct(self, node)
        if isinstance(target, Function):
            if target.py_func is native_builtins._hasattr:
                from .attribute_queries import hasattr_call
                return hasattr_call(self, node)
            if target.py_func is native_builtins._dataclass_missing:
                return "ptr", "@pyjs.dataclass.missing"
            if target.py_func is native_builtins._same_dataclass_type:
                left = self.expression(node.args[0])[1]
                right = self.expression(node.args[1])[1]
                return "i1", object_values.same_type(self, left, right)
            if target.py_func is native_builtins._type_is:
                from . import type_queries
                return type_queries.call(self, node)
            if ((decoration := get_native_decoration(target.py_func)) is not None
                    and decoration.operation == "query.callable"):
                from . import type_queries
                return type_queries.callable_call(self, node)
            if target.py_func is native_builtins._hash:
                from .hashing import call
                return call(self, node)
            if target.py_func is native_builtins._id:
                if len(node.args) != 1 or node.keywords:
                    raise LLVMUnsupported("LLVM id takes one positional argument", node)
                source = node.args[0]
                if isinstance(analyzed_value_object(source), (Module, ModuleAlias)):
                    raise LLVMUnsupported("LLVM id does not support module values", source)
                kind, value = self.expression(source)
                semantic = object_values.instance_type(source)
                value = identity.pointer(self, semantic, kind, value, source)
                return "i64", self.emit_value(f"ptrtoint ptr {value} to i64")
            if target.py_func is native_builtins._print:
                from .output_ops import print_call
                return print_call(self, node)
            if target.py_func in {native_builtins._format, native_builtins._ascii}:
                from . import format_ops
                return format_ops.call(self, target, node)
            if target.py_func in {native_builtins._bin, native_builtins._oct, native_builtins._hex}:
                from . import format_ops
                return format_ops.base_string(self, target, node)
            if target.py_func is native_builtins._repr:
                if calls.expands_arguments(node) or len(node.args) != 1 or node.keywords:
                    raise LLVMUnsupported("LLVM repr() takes one positional argument", node)
                source = node.args[0]
                if (empty := representation.empty_literal(source)) is not None:
                    return "ptr", "@" + self.string_constant(empty)
                kind, value = self.expression(source)
                return representation.render(self, analyzed_value_type(source), kind, value, node)
            if target.py_func is native_builtins._isinstance:
                expected = analyzed_value_object(node.args[1])
                if not isinstance(expected, (Class, GenericClass)):
                    raise LLVMUnsupported("LLVM isinstance requires a concrete class", node)
                dom_ops.check_type_query(self, analyzed_value_type(node.args[0]), expected, node)
                kind, value = self.expression(node.args[0], check_layout=False)
                if kind == tagged.STORAGE:
                    if (matched := dom_ops.instancecheck(self, kind, value, expected)) is not None:
                        return "i1", matched
                    actual, _ = tagged.parts(self, value)
                    return "i1", tagged.matches(self, actual, expected)
                return "i1", nullable.instancecheck(self, analyzed_value_type(node.args[0]), kind, value, expected, node)
            if target.py_func in iterator_ops.BUILTINS:
                return iterator_ops.builtin(self, target, node)
            if target.py_func is native_builtins._round:
                return self.builtin_round(node)
            if target.py_func is native_builtins._divmod:
                return self.builtin_divmod(node)
            if target.py_func is native_builtins._pow:
                return self.builtin_modular_pow(node)
        if (isinstance(target, Function) and target.name in {"__str__", "__repr__"}
                and isinstance(node.func, ast.Attribute) and not node.args and not node.keywords
                and not self.is_exception_type(target.cls)):
            source = node.func.value
            if (empty := representation.empty_literal(source)) is not None:
                return "ptr", "@" + self.string_constant(empty)
            kind, value = self.expression(source)
            return representation.render(self, analyzed_value_type(source), kind, value, node,
                                         representation=target.name == "__repr__")
        if isinstance(target, Class) and target.generic_name in {"set", "frozenset", "dict", "list", "tuple"}:
            return collection_ops.construct(self, node)
        if isinstance(target, Function) and target.py_func in {
            native_builtins._sum, native_builtins._all, native_builtins._any,
            native_builtins._min, native_builtins._max, native_builtins._sorted,
        }:
            return collection_ops.builtin(self, target.name, node)
        if isinstance(target, Class) and target.generic_name == "bool":
            if not node.args and not node.keywords:
                return "i1", "false"
            if len(node.args) != 1 or node.keywords:
                raise LLVMUnsupported("LLVM bool() takes one positional argument", node)
            return "i1", self.truth_value(node.args[0], *self.expression(node.args[0], check_layout=False))
        if isinstance(target, Class) and target.py_obj is native_builtins._int:
            if node.args and enum_ops.storage_name(analyzed_value_type(node.args[0])) in {"str", "bytes"}:
                return self.numeric_from_string(node, floating=False)
            if (node.args and isinstance(analyzed_value_type(node.args[0]), UnionType)
                    and (len(node.args) > 1 or any(keyword.arg == "base" for keyword in node.keywords))):
                raise LLVMUnsupported("LLVM int() with an explicit base requires narrowing its union input to str or bytes",
                                      node)
            if node.keywords:
                raise LLVMUnsupported("LLVM int() requires positional numeric arguments", node)
            if not node.args:
                value_type, value = "i64", "0"
            elif len(node.args) == 1 and not node.keywords:
                value_type, value = self.expression(node.args[0])
                semantic = analyzed_value_type(node.args[0])
                if semantic in self.module.classes and enum_ops.scalar_name(semantic) is None:
                    from .numeric_protocols import application
                    value_type, value = application(self, semantic, value, node, floating=False)
                value_type, value = tagged.numeric(self, node.args[0], value_type, value)
            else:
                raise LLVMUnsupported(
                    "fixed-width integer construction accepts one number",
                    node,
                )
            if value_type == "double":
                self.guard_float_to_integer(node, value)
                converted = self.new_temporary()
                self.emit_line(f"{converted} = fptosi double {value} to i64")
                value_type, value = "i64", converted
            elif value_type == "i1":
                converted = self.new_temporary()
                self.emit_line(f"{converted} = zext i1 {value} to i64")
                value_type, value = "i64", converted
            if value_type != "i64":
                raise LLVMUnsupported(
                    "fixed-width integer construction requires a number",
                    node,
                )
            return self.normalize_integer_result(value, node)
        if isinstance(target, Class) and target.py_obj is native_builtins._float:
            if node.args and enum_ops.storage_name(analyzed_value_type(node.args[0])) in {"str", "bytes"}:
                return self.numeric_from_string(node, floating=True)
            if node.keywords:
                raise LLVMUnsupported("LLVM float() requires a positional argument", node)
            if not node.args:
                value_type, value = "double", "0.0"
            elif len(node.args) == 1 and not node.keywords:
                value_type, value = self.expression(node.args[0])
                semantic = analyzed_value_type(node.args[0])
                if semantic in self.module.classes and enum_ops.scalar_name(semantic) is None:
                    from .numeric_protocols import application
                    value_type, value = application(self, semantic, value, node, floating=True)
                value_type, value = tagged.numeric(self, node.args[0], value_type, value)
            else:
                raise LLVMUnsupported(
                    "fixed-width float construction accepts one number",
                    node,
                )
            if value_type == "i1":
                value = self.emit_value(f"zext i1 {value} to i64")
                value_type = "i64"
            if value_type == "i64":
                converted = self.new_temporary()
                self.emit_line(f"{converted} = sitofp i64 {value} to double")
                value_type, value = "double", converted
            if value_type != "double":
                raise LLVMUnsupported(
                    "fixed-width float construction requires a number",
                    node,
                )
            return self.normalize_float_result(value, node)
        if isinstance(target, Function) and target.py_func is native_builtins._chr:
            from .text_ops import character
            return character(self, node)
        if isinstance(target, Function) and target.py_func is native_builtins._ord:
            _, value = self.expression(node.args[0])
            length = self.emit_value(f"call i64 @pyjs.string.length(ptr {value})")
            valid = self.emit_value(f"icmp eq i64 {length}, 1")
            accepted, invalid = self.new_label("ord.accepted"), self.new_label("ord.invalid")
            self.emit_line(f"br i1 {valid}, label %{accepted}, label %{invalid}")
            self.emit_line(f"{invalid}:")
            message = self.string_concat(
                f"@{self.string_constant('ord() expected a character, but string of length ')}",
                self.string_from_int(length))
            message = self.string_concat(message, f"@{self.string_constant(' found')}")
            self.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("TypeError"), message)
            self.branch_to_exception_target()
            self.emit_line(f"{accepted}:")
            field = self.emit_value(f"getelementptr %pyjs.string, ptr {value}, i32 0, i32 1")
            data = self.emit_value(f"load ptr, ptr {field}")
            decoded = self.emit_value(f"call i64 @pyjs.utf8.decode.scalar(ptr {data}, i64 0)")
            return "i64", self.emit_value(f"lshr i64 {decoded}, 3")
        if isinstance(target, Function) and target.py_func is native_builtins._abs:
            if len(node.args) != 1 or node.keywords:
                raise LLVMUnsupported("LLVM abs takes one positional argument", node)
            value_type, value = self.expression(node.args[0])
            value_type, value = tagged.numeric(self, node.args[0], value_type, value)
            return self.scalar_abs(value_type, value, node)
        if isinstance(target, Function) and target.py_func is native_builtins._len:
            if len(node.args) != 1 or node.keywords:
                raise LLVMUnsupported("LLVM len takes one positional argument", node)
            collection_type = analyzed_value_type(node.args[0])
            collection_type = enum_ops.underlying(tagged.runtime_type(collection_type))
            if collection_type in self.module.classes:
                value_type, value = self.expression(node.args[0])
                if value_type != "ptr":
                    raise LLVMUnsupported("LLVM application len requires a reference value", node)
                return "i64", calls.runtime_protocol(
                    self, collection_type, value, "i64", lambda candidate: self.length_method(candidate, node),
                    lambda method: self.application_length(method, value, node), node)
            if collection_ops.builtin_name(collection_type) is None:
                raise LLVMUnsupported("LLVM len requires a concrete builtin collection or application class", node)
            value_type, value = self.expression(node.args[0], check_layout=False)
            if collection_type.generic_name in collection_ops.VIEWS:
                source = self.emit_value(f"load ptr, ptr {value}")
                return "i64", self.emit_value(f"load i64, ptr {source}")
            if collection_type.generic_name == "tuple":
                return "i64", self.emit_value(f"load i64, ptr {value}")
            if collection_type.generic_name == "range":
                return self.range_call("__len__", value, [], node)
            if value_type != "ptr" or collection_type.generic_name not in {
                "bytes",
                "dict",
                "list",
                "set",
                "frozenset",
                "str",
                "tuple",
            }:
                raise LLVMUnsupported(
                    "LLVM len requires a concrete builtin collection or application class",
                    node,
                )
            pointer = self.new_temporary()
            result = self.new_temporary()
            if collection_type.generic_name == "str":
                self.emit_line(f"{result} = call i64 @pyjs.string.length(ptr {value})")
                return "i64", result
            structure = (
                "%pyjs.string"
                if collection_type.generic_name in {"str", "bytes"}
                else f"%pyjs.{collection_ops.sequence_name(collection_type)}"
            )
            self.emit_line(
                f"{pointer} = getelementptr {structure}, ptr {value}, i32 0, i32 0"
            )
            self.emit_line(f"{result} = load i64, ptr {pointer}")
            return "i64", result
        if (isinstance(target, Function) and target.cls is None
                and target in self.module.native_functions):
            return self.native_call(target, None, node)
        if (isinstance(target, Function) and target.cls is None
                and target in self.module.functions):
            with calls.bind(self, target, node) as arguments:
                return calls.invoke(self, target, arguments, node)
        if isinstance(node.func, ast.Attribute) and isinstance(target, Function):
            if target.is_classmethod and target.cls.py_obj is native_builtins._dict and target.name == "fromkeys":
                return collection_ops.fromkeys(self, node)
            if target.cls in self.module.classes and target.is_classmethod:
                if analyzed_value_object(node.func.value) is not target.cls:
                    raise LLVMUnsupported("LLVM inherited or instance class methods require dynamic class identity", node)
                # The shared analyzer binds cls to this concrete class; there
                # is no instance receiver or runtime class object to pass.
                with calls.bind(self, target, node) as arguments:
                    return calls.invoke(self, target, arguments, node)
            if (target.cls in self.module.classes and target.is_staticmethod
                    and not getattr(node.func, "union_functions", ())):
                if (semantic := calls.static_receiver(node, self.module.functions)) is not None:
                    return calls.class_instance(self, node, semantic)
                if object_values.instance_type(node.func.value) is not None:
                    _, receiver = self.expression(node.func.value)
                    if target.name == "__hash__":
                        from .hashing import guard_disabled_method
                        # Instance-static dispatch returned above; this is a
                        # lexical super() receiver, not dynamic child lookup.
                        node = guard_disabled_method(self, analyzed_value_type(node.func.value),
                                                     receiver, node, dynamic=False)
                elif target.name == "__hash__":
                    from .hashing import guard_disabled_method
                    # Class-qualified selection is lexical too: a declaration
                    # found in an ancestor must not bypass this class's None.
                    node = guard_disabled_method(self, analyzed_value_object(node.func.value),
                                                 "null", node, dynamic=False)
                with calls.bind(self, target, node) as arguments:
                    return calls.invoke(self, target, arguments, node)
            is_super = self.is_super_call(node.func.value)
            # Arithmetic lowering also synthesizes class-qualified builtin
            # calls. Restrict this source-call boundary to DOM/application
            # methods; those require an actual receiver, not a runtime class.
            # Result projections carry a Class as type metadata too; only
            # class-valued names/attributes denote unbound method selection.
            if (target.cls is not None
                    and (target.cls in self.module.classes or self.is_opaque_web_element_type(target.cls))
                    and not target.is_classmethod and not target.is_staticmethod
                    and object_values.instance_type(node.func.value) is None):
                raise LLVMUnsupported(
                    "LLVM instance methods require an instance or super() call; unbound calls are unsupported", node)
            semantic_receiver = analyzed_value_type(node.func.value)
            builtin_receiver = isinstance(semantic_receiver, Class) and semantic_receiver.container.scope.is_builtins
            if (target.name in {"__eq__", "__ne__", "__dynamic_eq__", "__dynamic_ne__"} and len(node.args) == 1
                    and (getattr(node, "operator", None) is not None or target.cls not in self.module.classes)):
                comparisons.check_representations(self, node,
                    (semantic_receiver, analyzed_representation(node.func.value)),
                    (analyzed_value_type(node.args[0]), analyzed_representation(node.args[0])),
                    inequality=node.func.attr in {"__ne__", "__dynamic_ne__"})
            if (builtin_receiver and semantic_receiver.generic_name in collection_ops.CONTAINERS
                    and node.keywords and target.name != "sort"):
                raise LLVMUnsupported("LLVM collection methods require positional arguments", node)
            if (builtin_receiver and semantic_receiver.generic_name == "list" and target.name == "__add__"
                    and collection_ops.builtin_name(analyzed_value_type(node.args[0])) != "list"):
                raise LLVMUnsupported("LLVM list addition requires a concrete list", node)
            leading_index = None
            object_comparison = (isinstance(getattr(node, "operator", None), (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                                 and target.name in comparisons.REFLECTED and len(node.args) == 1
                                 and (semantic_receiver in self.module.classes
                                      or analyzed_value_type(node.args[0]) in self.module.classes)
                                 and target.return_type is NATIVE_ENVIRONMENT.builtins.search("bool"))
            if ((object_comparison or isinstance(semantic_receiver, CallableClass)
                    or builtin_receiver and semantic_receiver.generic_name in {"bool", "int", "float"}
                    or getattr(semantic_receiver, "generic_name", None) in {"list", "str", "bytes", "dict", "set", "frozenset", "range", "slice", "tuple", *collection_ops.VIEWS})
                    and (getattr(node, "reverse", False)
                         or isinstance(getattr(node, "operator", None), (ast.In, ast.NotIn)))):
                # Syntax lowers the right operand to the receiver. Evaluate the
                # original left operand first, retaining its normal GC root.
                # Explicit dunder calls have no operator/reverse metadata.
                leading_index = 0
            leading_value = (
                self.expression(node.args[leading_index])
                if leading_index is not None else None
            )
            # Application operators also evaluate the source left operand before
            # the receiver. Reuse any value already lowered by the builtin path;
            # a colliding class name must not evaluate that expression twice.
            source_positional = (
                [leading_value if index == leading_index else self.expression(argument)
                 for index, argument in enumerate(node.args)]
                if target in self.module.functions and not object_comparison
                and (getattr(node, "reverse", False)
                     or isinstance(getattr(node, "operator", None), (ast.In, ast.NotIn))) else None
            )
            receiver_type, receiver = self.expression(node.func.value,
                check_layout=target.name not in {"__len__", "__bool__", "__dynamic_bool__"})
            if (isinstance(semantic_receiver, UnionType) or iterable_views.is_view(semantic_receiver)
                    or collection_ops.builtin_name(semantic_receiver) == "NotImplementedType") and target.name in {"__bool__", "__dynamic_bool__"}:
                return "i1", self.truth_value(node.func.value, receiver_type, receiver)
            semantic_receiver, receiver_type, receiver = tagged.untag_single_member(
                self, semantic_receiver, receiver_type, receiver, node)
            if nullable.member(semantic_receiver) is not None and target.name == "__str__" and not node.args:
                return "ptr", nullable.string(self, semantic_receiver, receiver_type, receiver, node)
            # Explicit authored dunders are ordinary calls, even with object
            # arguments. Only comparison syntax uses bilateral dispatch.
            if (target.name in {"__eq__", "__ne__"} and len(node.args) == 1
                    and getattr(node, "operator", None) is None and target.cls not in self.module.classes):
                other_type = analyzed_value_type(node.args[0])
                if isinstance(semantic_receiver, CallableClass) or isinstance(other_type, CallableClass):
                    # Callable storage erases the function/method distinction;
                    # explicit dunders may return NotImplemented, not False.
                    raise LLVMUnsupported("LLVM explicit callable comparison dunders may return NotImplemented; use comparison syntax", node)
                if nullable.is_object(semantic_receiver) or nullable.is_object(other_type):
                    raise LLVMUnsupported("LLVM erased comparison dunder calls require NotImplemented support", node)
                receiver_name = collection_ops.builtin_name(semantic_receiver)
                if receiver_name in {"list", "tuple", "dict", "set", "frozenset"}:
                    accepted = {"set", "frozenset"} if receiver_name in {"set", "frozenset"} else {receiver_name}
                    unlike = any(collection_ops.builtin_name(member) not in accepted for member in get_type_members(other_type))
                else:
                    unlike = isinstance(other_type, UnionType) or other_type in self.module.classes and builtin_receiver
                if isinstance(semantic_receiver, UnionType) or unlike:
                    # Check before union dispatch too: even a builtin-only arm
                    # can return NotImplemented rather than a boolean result.
                    raise LLVMUnsupported("LLVM explicit builtin comparison dunders may return NotImplemented; use comparison syntax", node)
            if (target.name in {"__eq__", "__ne__", "__dynamic_eq__", "__dynamic_ne__"} and len(node.args) == 1
                    and (getattr(node, "operator", None) is not None or target.cls not in self.module.classes)) and (
                    target.name in {"__dynamic_eq__", "__dynamic_ne__"}
                    or isinstance(semantic_receiver, CallableClass)
                    or isinstance(analyzed_value_type(node.args[0]), CallableClass)
                    or (dom_ops.is_element(self, semantic_receiver)
                        and dom_ops.is_element(self, analyzed_value_type(node.args[0])))
                    or getattr(semantic_receiver, "py_obj", None) is native_builtins._WebTokenList
                    or isinstance(semantic_receiver, UnionType) or isinstance(analyzed_value_type(node.args[0]), UnionType)
                    or nullable.is_object(semantic_receiver) or nullable.is_object(analyzed_value_type(node.args[0]))
                    or collection_ops.builtin_name(semantic_receiver) == "NotImplementedType"
                    or getattr(semantic_receiver, "generic_name", None)
                    == getattr(analyzed_value_type(node.args[0]), "generic_name", None) == "NoneType"):
                other = leading_value if leading_value is not None else self.expression(node.args[0])
                return "i1", comparisons.compare_value(
                    self, tagged.effective_type(semantic_receiver, receiver_type), receiver,
                    tagged.effective_type(analyzed_value_type(node.args[0]), other[0]), other[1], node,
                    operation="__ne__" if target.name.endswith("ne__") else "__eq__")
            if target.py_func is native_builtins._object.__hash__:
                return hashing.explicit_default(self, semantic_receiver, receiver_type, receiver, node,
                                                base_implementation=is_super)
            if isinstance(semantic_receiver, UnionType):
                if receiver_type == tagged.STORAGE and getattr(node.func, "union_functions", ()):
                    return tagged.method_call(self, node, semantic_receiver, receiver, positional=source_positional)
                raise LLVMUnsupported(f"LLVM union values must be narrowed before {target.name}", node)
            if object_comparison:
                other = leading_value if leading_value is not None else self.expression(node.args[0])
                operands = (semantic_receiver, receiver, analyzed_value_type(node.args[0]), other[1])
                operation = target.name
                if getattr(node, "reverse", False):
                    # Static reflection determines evaluation order, not runtime
                    # priority: both operands can actually be the same subclass.
                    operands = (*operands[2:], *operands[:2])
                    operation = comparisons.REFLECTED[operation]
                return "i1", comparisons.object_compare(self, *operands, node,
                                                         operation=operation, identity=False)
            if target.name == "__iter__" and (iterator_ops.is_iterator(semantic_receiver)
                    or iterable_views.is_view(semantic_receiver)
                    or (semantic_receiver.container.scope.is_builtins
                        and semantic_receiver.generic_name in collection_ops.CONTAINERS | {"range", "str", "bytes"})):
                if node.args or node.keywords:
                    raise LLVMUnsupported("LLVM __iter__ takes no arguments", node)
                return "ptr", iterator_ops.create(self, semantic_receiver, receiver, node)
            if target.name == "__next__" and iterator_ops.is_iterator(semantic_receiver):
                if node.args or node.keywords:
                    raise LLVMUnsupported("LLVM __next__ takes no arguments", node)
                return iterator_ops.next_value(self, receiver, collection_ops.item_type(semantic_receiver), node)
            if iterator_ops.is_iterator(semantic_receiver) and semantic_receiver.generic_name == "Generator":
                if target.name == "close":
                    return generators.close(self, receiver, semantic_receiver, node)
                if target.name == "send":
                    return generators.send(self, receiver, semantic_receiver, node)
                if target.name == "throw":
                    return generators.throw(self, receiver, semantic_receiver, node)
            if target in self.module.native_functions:
                return self.native_call(target, receiver, node)
            if target in self.module.functions:
                if receiver_type != "ptr":
                    raise LLVMUnsupported(f"LLVM method {target.name} requires an object receiver", node)
                return calls.bind_method(self, target, receiver, node, semantic=semantic_receiver,
                                         positional=source_positional, dynamic=not is_super)
            if self.is_opaque_web_element_type(target.cls):
                # super() selects a base implementation but still carries the
                # current application's wrapper, not an opaque DOM pointer.
                storage = self.current_function.cls if is_super else semantic_receiver
                return dom_ops.method_call(self, target, storage, receiver, node,
                                           base_implementation=is_super)
            if getattr(target.cls, "py_obj", None) is native_builtins._WebTokenList:
                return dom_ops.token_call(self, target, receiver, node)
            # Inherited object methods can still have an application receiver
            # here; its spelling does not imply a builtin storage layout.
            receiver_name = enum_ops.storage_name(semantic_receiver)
            if receiver_name in {"str", "bytes"}:
                from . import text_counts
                if target.name in text_counts.PARAMETERS:
                    return text_counts.emit(self, target, receiver, node, binary=receiver_name == "bytes")
                if target.name in {"encode", "decode"}:
                    return self.codec_call(target.name, receiver, node)
                if node.keywords:
                    raise LLVMUnsupported("LLVM string methods require positional arguments", node)
                if target.name == "join":
                    values = node.args[0]
                    if (
                        isinstance(values, CollectionNew)
                        and isinstance(values.source, ast.List)
                        and not values.source.elts
                    ):
                        # An empty literal needs no item layout. Evaluate the
                        # separator above even though the result is constant.
                        return "ptr", f"@{self.string_constant('')}"
                    values_type = analyzed_value_type(values)
                    if collection_ops.builtin_name(values_type) == "tuple" and not values_type.generic_types:
                        self.expression(values)
                        return "ptr", f"@{self.string_constant('')}"
                    member = collection_ops.item_type(values_type)
                    alternatives = tagged.members(member)
                    text_member = alternatives[0] if len(alternatives) == 1 else tagged.runtime_type(member)
                    if enum_ops.storage_name(text_member) != receiver_name:
                        raise LLVMUnsupported(f"LLVM {semantic_receiver.name}.join requires matching text items", node)
                    if (collection_ops.builtin_name(values_type) not in {"list", "tuple", "dict", "set", "frozenset"}
                            or self.value_type(member) != self.value_type(text_member)):
                        # A Literal union's list stores tagged pairs, not text
                        # pointers. Materialize through ordinary item coercion.
                        _, source = self.expression(values)
                        target_type = NATIVE_ENVIRONMENT.builtins.search("list")(text_member)
                        materialized = collection_ops.materialize(self, target_type, values_type, source, node)
                        return self.string_edit_call("join", receiver, [("ptr", materialized)], node,
                                                     binary=receiver_name == "bytes")
                    # These concrete containers share length + dense pointer
                    # storage at the list item offset (mapping/set keys). Join
                    # has no callbacks between measuring and copying, so borrow
                    # it directly. Protocol views and tagged items still stage.
            arguments = [leading_value if index == leading_index else self.expression(argument)
                         for index, argument in enumerate(node.args)]
            syntactic_slice = (receiver_name in {"list", "tuple", "str", "bytes", "range"}
                               and target.name in {"__slice__", "__setslice__", "__delslice__"})
            if syntactic_slice:
                # Match the untagged storage identity used by dispatch (including
                # StrEnum). Convert callback bounds before borrowing kernel data.
                arguments = slices.syntax_arguments(self, target.name, arguments, node)
            if (target.name in {"__getitem__", "__setitem__", "__delitem__"} and node.args
                    and collection_ops.builtin_name(analyzed_value_type(node.args[0])) == "slice"):
                return slices.subscript(self, target.name, semantic_receiver, receiver, arguments, node)
            if receiver_name in {"list", "tuple", "str", "bytes", "range"}:
                if result := slices.dynamic_subscript(self, semantic_receiver, receiver, arguments, node):
                    return result
            for position in indexing.sequence_positions(node):
                semantic = analyzed_value_type(node.args[position])
                if (target.name in {"__mul__", "__rmul__", "__imul__"}
                        and getattr(node, "operator", None) is not None
                        and (nullable.is_object(semantic) or isinstance(semantic, UnionType)
                             and any(nullable.is_object(member) or member in self.module.classes
                                     for member in get_type_members(semantic)))):
                    # A hidden application numeric slot takes priority over
                    # repetition. The concrete binary dispatcher handles that;
                    # an erased/union count cannot silently skip reflection.
                    raise LLVMUnsupported("LLVM ambiguous repetition counts require narrowing before use", node)
                # Run once after all expressions, before any length/storage
                # reads. A callback can resize the receiver, collect or raise;
                # scalar kernels must never repeat it or use a stale buffer.
                arguments[position] = ("i64", indexing.integer(self, semantic, *arguments[position], node))
            if receiver_name in {"str", "bytes"} and target.name != "__contains__" and not syntactic_slice:
                # Literal alternatives share one text layout even when the
                # analyzer keeps their conditional result as a tagged union.
                arguments = [tagged.untag_single_member(self, analyzed_value_type(argument), *value, argument)[1:]
                             for argument, value in zip(node.args, arguments, strict=True)]
            if receiver_name in {"int", "bool", "float"}:
                if (target.name in {"__and__", "__or__", "__xor__", "__rand__", "__ror__", "__rxor__"}
                        and arguments and tagged.STORAGE in {receiver_type, arguments[0][0]}
                        and {receiver_type, arguments[0][0]} <= {"i1", tagged.STORAGE}):
                    raise LLVMUnsupported("convert narrowed integers explicitly before mixed bool bitwise operations", node)
                receiver_type, receiver = tagged.numeric(self, node.func.value, receiver_type, receiver)
                arguments = [tagged.numeric(self, argument, *value)
                             for argument, value in zip(node.args, arguments, strict=True)]
                if len(arguments) == 1 and {receiver_type, arguments[0][0]} == {"i1", "i64"}:
                    receiver_type, receiver = "i64", self.index_integer(receiver_type, receiver, node, "expected integer")
                    arguments = [("i64", self.index_integer(*arguments[0], node, "expected integer"))]
            result = collection_ops.method(self, target.name, semantic_receiver, receiver, arguments, node)
            if result is not None:
                return result
            if (semantic_receiver in self.module.classes and target.name in {"__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
                    and collection_ops.builtin_name(target.cls) == "object" and len(arguments) == 1):
                operator = {"__ne__": "!=", "__lt__": "<", "__le__": "<=", "__gt__": ">", "__ge__": ">="}[target.name]
                raise LLVMUnsupported(f"LLVM explicit object.{target.name} may return NotImplemented; use {operator} with typed objects", node)
            if receiver_name == "range":
                return self.range_call(target.name, receiver, arguments, node)
            if receiver_name == "slice":
                return slices.method(self, target.name, receiver, arguments, node)
            if (
                is_super
                and target.name == "__init__"
                and self.current_function is not None
                and self.current_function.cls in self.module.custom_element_types
                and target.cls is not None
                and target.cls.py_obj
                in {native_builtins._object, native_builtins._WebElement}
            ):
                dom_ops.initialize_identity(self, self.current_function.cls, receiver)
                return "void", ""
            if receiver_name in {"str", "bytes"}:
                if target.name in runtime_text.EXTRA_METHODS:
                    return self.text_extra_call(target.name, receiver, arguments, node, binary=receiver_name == "bytes")
                if receiver_name == "bytes" and target.name in {"__len__", "__getitem__", "__contains__"}:
                    return self.bytes_call(target.name, receiver, arguments, node)
                if target.name in runtime_text.EDIT_METHODS:
                    return self.string_edit_call(target.name, receiver, arguments, node, binary=receiver_name == "bytes")
                if target.name in runtime_text.CASE_METHODS and not arguments:
                    mapping, mode = runtime_text.CASE_METHODS[target.name]
                    allocator = "@pyjs.gc.alloc.adapter" if self.module.uses_gc else "null"
                    context = self.load_local("__heap") if self.module.uses_gc else "null"
                    result = self.allocated_value(
                        "call ptr @pyjs.unicode.change.case("
                        f"ptr {self.load_local('__arena')}, ptr {allocator}, ptr {context}, "
                        f"ptr {receiver}, ptr @pyjs.unicode.{mapping}.mapping, "
                        f"ptr @pyjs.unicode.context, i64 {mode})"
                    )
                    return "ptr", result
                if target.name in runtime_text.PROPERTY_METHODS and not arguments:
                    table, count = runtime_text.PROPERTY_METHODS[target.name]
                    operation = "cased" if target.name in {"islower", "isupper"} else "all"
                    result = self.emit_value(
                        f"call i1 @pyjs.string.{operation}.codepoints.in.ranges("
                        f"ptr {receiver}, ptr @pyjs.unicode.{table}, i64 {count})"
                    )
                    if target.name == "isprintable":
                        length = self.emit_value(f"load i64, ptr {receiver}")
                        empty = self.emit_value(f"icmp eq i64 {length}, 0")
                        result = self.emit_value(f"or i1 {result}, {empty}")
                    return "i1", result
                if target.name in {"isascii", "istitle", "isidentifier", "__len__"} and not arguments:
                    operation = {"isascii": "is.ascii", "istitle": "is.title",
                                 "isidentifier": "is.identifier", "__len__": "length"}[target.name]
                    kind = "i64" if target.name == "__len__" else "i1"
                    return kind, self.emit_value(f"call {kind} @pyjs.string.{operation}(ptr {receiver})")
                if target.name == "__contains__" and len(arguments) == 1:
                    return text_search.contains(self, receiver, arguments[0], node, binary=False)
                if target.name in {"__lt__", "__le__", "__gt__", "__ge__"} and len(arguments) == 1:
                    left, right = receiver, arguments[0][1]
                    if target.name in {"__le__", "__gt__"}:
                        left, right = right, left
                    result = self.emit_value(f"call i1 @pyjs.string.less(ptr {left}, ptr {right})")
                    if target.name in {"__le__", "__ge__"}:
                        result = self.emit_value(f"xor i1 {result}, true")
                    return "i1", result
                if target.name in {"__add__", "__radd__"} and len(arguments) == 1:
                    if arguments[0][0] != "ptr":
                        raise LLVMUnsupported("LLVM string addition requires str", node)
                    left, right = (
                        (arguments[0][1], receiver)
                        if target.name == "__radd__"
                        else (receiver, arguments[0][1])
                    )
                    return "ptr", self.string_concat(left, right)
                if target.name in {"__eq__", "__ne__"} and len(arguments) == 1:
                    if arguments[0][0] != "ptr":
                        raise LLVMUnsupported("LLVM string comparison requires str", node)
                    result = self.new_temporary()
                    self.emit_line(
                        f"{result} = call i1 @pyjs.string.equal(ptr {receiver}, "
                        f"ptr {arguments[0][1]})"
                    )
                    if target.name == "__ne__":
                        inverted = self.new_temporary()
                        self.emit_line(f"{inverted} = xor i1 {result}, true")
                        result = inverted
                    return "i1", result
                if target.name == "__bool__" and not arguments:
                    result = self.new_temporary()
                    self.emit_line(
                        f"{result} = call i1 @pyjs.string.bool(ptr {receiver})"
                    )
                    return "i1", result
                if target.name == "__str__" and not arguments:
                    if receiver_name == "bytes":
                        return self.owned_text_call("pyjs.text.repr_bytes", [f"ptr {receiver}"])
                    return "ptr", receiver
            if receiver_name == "list":
                return self.sequence_call(target.name, semantic_receiver, receiver, arguments, node)
            if (
                target.name == "__getitem__"
                and receiver_name == "tuple"
                and len(node.args) == 1
                and (index := integer_literal(getattr(node.args[0], "python_node", node.args[0]), allow_bool=True)) is not None
            ):
                item_types = tuple(semantic_receiver.generic_types.values())
                if index < 0:
                    index += len(item_types)
                if not 0 <= index < len(item_types):
                    raise LLVMUnsupported("LLVM tuple index is out of range", node)
                tuple_type = self.tuple_type(semantic_receiver)
                length = self.emit_value(f"load i64, ptr {receiver}")
                self.guard_exception(node, self.emit_value(f"icmp ugt i64 {length}, {index}"),
                                     "IndexError", "tuple index out of range")
                receiver = collection_ops.storage(self, receiver, 2)
                item_type = self.value_type(item_types[index])
                slot = self.new_temporary()
                result = self.new_temporary()
                self.emit_line(
                    f"{slot} = getelementptr %{tuple_type}, ptr {receiver}, "
                    f"i32 0, i32 {index}"
                )
                self.emit_line(f"{result} = load {item_type}, ptr {slot}")
                return item_type, result
            if receiver_name == "dict":
                member = self.dictionary_types(semantic_receiver)[1]
                roots = None
                if (len(arguments) == 2 and target.name in {"get", "setdefault", "pop", "__setitem__"}
                        and iterator_ops.is_iterator(nullable.member(member) or member)):
                    # A cursor-to-interface conversion allocates a new handle.
                    # Root it across key hash/equality callbacks before storage
                    # (or before choosing a default from a failed lookup).
                    receiver_representation = analyzed_representation(node.func.value)
                    arguments[1] = self.coerce_value(*arguments[1], self.value_type(member),
                                                     node.args[1], semantic=member,
                                                     representation=receiver_representation.arguments[1]
                                                     if receiver_representation else None)
                    roots = calls.root_values(self, arguments[1][1])
                result = self.dictionary_call(
                    target.name,
                    semantic_receiver,
                    receiver,
                    arguments,
                    node,
                )
                calls.pop_roots(self, roots)
                return result
            if receiver_name in {"set", "frozenset"}:
                if receiver_name == "frozenset" and target.name == "copy" and not arguments:
                    return "ptr", receiver
                return self.set_call(
                    target.name,
                    semantic_receiver,
                    receiver,
                    arguments,
                    node,
                )
            if (not arguments and receiver_name in {"int", "bool"}
                    and target.name in {"bit_count", "bit_length"}):
                if receiver_type == "i1":
                    widened = self.new_temporary()
                    self.emit_line(f"{widened} = zext i1 {receiver} to i64")
                    receiver = widened
                result = self.new_temporary()
                self.emit_line(f"{result} = call i64 @pyjs.int.{target.name}(i64 {receiver})")
                return "i64", result
            if not arguments and receiver_type in {"i1", "i64"}:
                if target.name in {"__pos__", "__neg__", "__invert__"}:
                    if receiver_type == "i1":
                        widened = self.new_temporary()
                        self.emit_line(f"{widened} = zext i1 {receiver} to i64")
                        receiver = widened
                    if target.name == "__pos__":
                        result = receiver
                    else:
                        result = self.new_temporary()
                        operation = (
                            "sub i64 0," if target.name == "__neg__" else "xor i64 -1,"
                        )
                        self.emit_line(f"{result} = {operation} {receiver}")
                    return self.normalize_integer_result(result, node)
            if (
                len(arguments) == 1
                and receiver_type == "double"
                and arguments[0][0] in {"i1", "i64"}
            ):
                argument_type, argument = arguments[0]
                if target.name in self.FLOAT_COMPARISONS:
                    # Arithmetic may round the integer to binary64; comparison
                    # may not. Reuse the exact comparator used by container
                    # members, including NaN and signed-i64 boundary handling.
                    other = NATIVE_ENVIRONMENT.builtins.search("bool" if argument_type == "i1" else "int")
                    operands = (semantic_receiver, receiver, other, argument, node)
                    if target.name in {"__eq__", "__ne__"}:
                        return "i1", comparisons.compare_value(self, *operands, operation=target.name)
                    return "i1", comparisons.order_value(self, target.name, *operands)
                converted = self.new_temporary()
                conversion = "uitofp" if argument_type == "i1" else "sitofp"
                self.emit_line(
                    f"{converted} = {conversion} {argument_type} "
                    f"{argument} to double"
                )
                arguments = [("double", converted)]
            if (len(arguments) == 1 and receiver_type == arguments[0][0] == "i1"
                    and target.name in {"__eq__", "__ne__"}):
                predicate = "eq" if target.name == "__eq__" else "ne"
                return "i1", self.emit_value(f"icmp {predicate} i1 {receiver}, {arguments[0][1]}")
            if len(arguments) == 1 and receiver_type == arguments[0][0] == "i1":
                argument = arguments[0][1]
                operation = self.INTEGER_OPERATORS.get(target.name)
                if (operation in {"and", "or", "xor"}
                        and analyzed_value_type(node) is NATIVE_ENVIRONMENT.builtins.search("bool")):
                    return "i1", self.emit_value(f"{operation} i1 {receiver}, {argument}")
                # bool is an integer operand, but its i1 storage must widen
                # unsigned (True is 1, not -1). Only bool/bool bitwise results
                # retain Boolean identity; arithmetic uses the integer paths.
                receiver_type, receiver = "i64", self.emit_value(f"zext i1 {receiver} to i64")
                arguments = [("i64", self.emit_value(f"zext i1 {argument} to i64"))]
            if len(arguments) == 1 and receiver_type == arguments[0][0] == "i64":
                argument = arguments[0][1]
                storage_format = analyzed_numeric_format(node)
                if target.name in {
                    "__truediv__",
                    "__rtruediv__",
                    "__floordiv__",
                    "__rfloordiv__",
                    "__mod__",
                    "__rmod__",
                }:
                    left, right = (
                        (argument, receiver)
                        if target.name.startswith("__r")
                        else (receiver, argument)
                    )
                    if storage_format is not None and storage_format.domain == "wgsl":
                        result = self.wgsl_integer_division(
                            left,
                            right,
                            storage_format,
                            modulo=target.name.endswith("mod__"),
                        )
                        return self.normalize_integer_result(result, node)
                    self.guard_nonzero(node, "i64", right, "division by zero")
                    if "truediv" in target.name:
                        result = self.new_temporary()
                        self.emit_line(
                            f"{result} = call double @pyjs.int.true.divide("
                            f"i64 {left}, i64 {right})"
                        )
                        return "double", result
                    pair = self.new_temporary()
                    result = self.new_temporary()
                    index = 1 if target.name.endswith("mod__") else 0
                    runtime = (
                        "pyjs.fixed.int.divmod"
                        if storage_format is not None or index == 1
                        else "pyjs.int.divmod"
                    )
                    if storage_format is None and index == 0:
                        self.guard_division_overflow(node, left, right)
                    self.emit_line(
                        f"{pair} = call {{ i64, i64 }} @{runtime}("
                        f"i64 {left}, i64 {right})"
                    )
                    self.emit_line(
                        f"{result} = extractvalue {{ i64, i64 }} {pair}, {index}"
                    )
                    return self.normalize_integer_result(result, node)
                if target.name in self.INTEGER_OPERATORS:
                    left, right = (
                        (argument, receiver)
                        if target.name == "__rsub__"
                        else (receiver, argument)
                    )
                    result = self.new_temporary()
                    self.emit_line(
                        f"{result} = {self.INTEGER_OPERATORS[target.name]} i64 "
                        f"{left}, {right}"
                    )
                    return self.normalize_integer_result(result, node)
                if target.name == "__rsub__":
                    result = self.new_temporary()
                    self.emit_line(f"{result} = sub i64 {argument}, {receiver}")
                    return self.normalize_integer_result(result, node)
                if target.name in {"__lshift__", "__rshift__"}:
                    receiver_format = analyzed_numeric_format(node.func.value)
                    result = self.integer_shift(
                        receiver,
                        argument,
                        left=target.name == "__lshift__",
                        signed=(
                            storage_format is None
                            or storage_format.signed
                            or receiver_format is None
                        ),
                        node=node,
                        bits=(
                            storage_format.bits
                            if storage_format is not None
                            and receiver_format is not None
                            else 64
                        ),
                    )
                    return self.normalize_integer_result(result, node)
                if target.name in {"__pow__", "__rpow__"}:
                    left, right = (
                        (argument, receiver)
                        if target.name == "__rpow__"
                        else (receiver, argument)
                    )
                    result = self.new_temporary()
                    self.emit_line(
                        f"{result} = call i64 @pyjs.int.pow(i64 {left}, i64 {right})"
                    )
                    return self.normalize_integer_result(result, node)
                if target.name in self.INTEGER_COMPARISONS:
                    result = self.new_temporary()
                    self.emit_line(
                        f"{result} = icmp {self.INTEGER_COMPARISONS[target.name]} "
                        f"i64 {receiver}, {argument}"
                    )
                    return "i1", result
            if len(arguments) == 1 and receiver_type == arguments[0][0] == "double":
                argument = arguments[0][1]
                left, right = (
                    (argument, receiver)
                    if target.name.startswith("__r")
                    else (receiver, argument)
                )
                if target.name in {"__floordiv__", "__rfloordiv__", "__mod__", "__rmod__"}:
                    self.guard_nonzero(node, "double", right, "division by zero")
                    pair = self.emit_value(
                        f"call {{ double, double }} @pyjs.float.divmod(double {left}, double {right})"
                    )
                    index = 1 if target.name.endswith("mod__") else 0
                    value = self.emit_value(f"extractvalue {{ double, double }} {pair}, {index}")
                    return self.normalize_float_result(value, node)
                if target.name in self.FLOAT_OPERATORS:
                    result = self.new_temporary()
                    if target.name in {"__truediv__", "__rtruediv__"}:
                        storage_format = analyzed_numeric_format(node)
                        if storage_format is not None and storage_format.domain == "wgsl":
                            self.emit_line(f"{result} = fdiv double {left}, {right}")
                        else:
                            self.guard_nonzero(node, "double", right, "division by zero")
                            self.emit_line(
                                f"{result} = call double @pyjs.float.divide("
                                f"double {left}, double {right})"
                            )
                    else:
                        self.emit_line(
                            f"{result} = {self.FLOAT_OPERATORS[target.name]} "
                            f"double {left}, {right}"
                        )
                    return self.normalize_float_result(result, node)
                if target.name in self.FLOAT_COMPARISONS:
                    result = self.new_temporary()
                    self.emit_line(
                        f"{result} = fcmp {self.FLOAT_COMPARISONS[target.name]} "
                        f"double {left}, {right}"
                    )
                    return "i1", result
            if target.name == "__abs__" and not arguments:
                return self.scalar_abs(receiver_type, receiver, node)
            if target.name == "__bool__" and not arguments and receiver_type == "i1":
                return "i1", receiver
            if target.name == "__bool__" and not arguments and receiver_type == "i64":
                return "i1", self.emit_value(f"icmp ne i64 {receiver}, 0")
            if target.name == "__bool__" and not arguments and receiver_type == "double":
                result = self.new_temporary()
                self.emit_line(f"{result} = fcmp une double {receiver}, 0.0")
                return "i1", result
            if target.name == "__str__" and not arguments:
                if receiver_type == "i1":
                    return "ptr", self.string_from_bool(receiver)
                if receiver_type == "i64":
                    return "ptr", self.string_from_int(receiver)
                if receiver_type == "double":
                    return "ptr", self.string_from_float(receiver)
            raise LLVMUnsupported(
                f"unsupported LLVM scalar operation {target.name}",
                node,
            )
        if isinstance(target, Function):
            if target in self.module.native_functions:
                return self.native_call(target, None, node)
            if target not in self.module.functions:
                raise LLVMUnsupported(
                    f"LLVM call target {target.name} has no emitted definition",
                    node,
                )
            with calls.bind(self, target, node) as bound:
                return calls.invoke(self, target, bound, node)
        if isinstance(target, Class) and target.py_obj is native_builtins._str:
            if not node.args and not node.keywords:
                return "ptr", "@" + self.string_constant("")
            if len(node.args) != 1 or node.keywords:
                raise LLVMUnsupported("LLVM str() takes zero or one argument", node)
            if (empty := representation.empty_literal(node.args[0])) is not None:
                return "ptr", "@" + self.string_constant(empty)
            value_type, value = self.expression(node.args[0])
            semantic = analyzed_value_type(node.args[0])
            if self.is_exception_type(semantic):
                return "ptr", exception_values.text(self, value, node)
            return representation.render(self, semantic, value_type, value, node, representation=False)
        if self.is_super_call(node):
            if node.args or node.keywords:
                raise LLVMUnsupported(
                    "LLVM supports only zero-argument super()",
                    node,
                )
            if self.current_function is None or self.current_function.cls is None:
                raise LLVMUnsupported("LLVM super() requires an instance method", node)
            return "ptr", self.load_local("self")
        raise LLVMUnsupported("LLVM indirect calls are not implemented", node)

    def range_arguments(self, node: ast.Call) -> tuple[str, str, str]:
        from .indexing import integer
        if not 1 <= len(node.args) <= 3 or node.keywords:
            raise LLVMUnsupported("LLVM range takes one to three positional integers", node)
        # All source expressions run before the first __index__ callback.
        # Keep their ordinary expression roots alive across conversion/GC.
        arguments = [self.expression(argument) for argument in node.args]
        values = [integer(self, analyzed_value_type(argument), *value, node)
                  for argument, value in zip(node.args, arguments, strict=True)]
        start, stop, step = (("0", values[0], "1") if len(values) == 1 else
                             (*values, "1") if len(values) == 2 else values)
        self.guard_exception(node, self.emit_value(f"icmp ne i64 {step}, 0"),
                             "ValueError", "range() arg 3 must not be zero")
        return start, stop, step

    def range_new(self, values) -> str:
        result = gc_layouts.allocate(self, ("i64", "i64", "i64"), layout="%pyjs.range")
        for index, value in enumerate(values):
            slot = self.emit_value(f"getelementptr i64, ptr {result}, i64 {index}")
            self.emit_line(f"store i64 {value}, ptr {slot}")
        return result

    def range_values(self, value: str) -> tuple[str, str, str]:
        values = []
        for index in range(3):
            slot = self.emit_value(f"getelementptr i64, ptr {value}, i64 {index}")
            values.append(self.emit_value(f"load i64, ptr {slot}"))
        return tuple(values)

    def range_call(self, operation, receiver, arguments, node):
        if node.keywords:
            raise LLVMUnsupported("LLVM range methods require positional arguments", node)
        values = self.range_values(receiver)
        parameters = [f"i64 {value}" for value in values]
        if operation in {"__eq__", "__ne__"}:
            if analyzed_value_type(node.args[0]).generic_name != "range":
                raise LLVMUnsupported("LLVM range comparison requires another range", node)
            parameters.extend(f"i64 {value}" for value in self.range_values(arguments[0][1]))
            result = self.emit_value(f"call i1 @pyjs.range.equal({', '.join(parameters)})")
            return "i1", self.emit_value(f"xor i1 {result}, true") if operation == "__ne__" else result
        if operation == "__slice__":
            selected = [slices.bound(self, arguments[index] if index < len(arguments) else ("void", ""),
                                     node, 1 if index == 2 else 0) for index in range(3)]
            self.guard_exception(node, self.emit_value(f"icmp ne i64 {selected[2][0]}, 0"),
                                 "ValueError", "slice step cannot be zero")
            for value, present in selected:
                parameters.extend((f"i64 {value}", f"i1 {present}"))
            result = gc_layouts.allocate(self, ("i64", "i64", "i64"), layout="%pyjs.range")
            valid = self.emit_value(f"call i1 @pyjs.range.slice.into({', '.join(parameters)}, ptr {result})")
            self.guard_exception(node, valid, "OverflowError", "range slice exceeds native i64 limits")
            return "ptr", result
        if operation in {"__contains__", "count", "index"}:
            kind, value = arguments[0]
            floating = kind == "double"
            if not floating:
                value = self.index_integer(kind, value, node, "LLVM range lookup requires an integer or float")
            parameters.append(f"{'double' if floating else 'i64'} {value}")
            symbol = "contains.float" if floating else "contains"
            present = self.emit_value(f"call i1 @pyjs.range.{symbol}({', '.join(parameters)})")
            if operation == "__contains__":
                return "i1", present
            if operation == "count":
                return "i64", self.emit_value(f"zext i1 {present} to i64")
            message = "sequence.index(x): x not in sequence" if floating else "range.index(x): x not in range"
            self.guard_exception(node, present, "ValueError", message)
            if floating:
                # Membership proves this conversion exact, finite and in i64.
                value = self.emit_value(f"fptosi double {value} to i64")
                parameters[-1] = f"i64 {value}"
            wide = self.emit_value(f"call i128 @pyjs.range.index.i128({', '.join(parameters)})")
            return "i64", self.checked_narrow_integer(node, wide, "range index exceeds native i64 limits")
        if arguments:
            value = self.index_integer(*arguments[0], node, "LLVM range lookup requires an integer")
            parameters.append(f"i64 {value}")
        if operation in {"__len__", "__getitem__"}:
            count = self.emit_value(f"call i128 @pyjs.range.length.i128({', '.join(parameters[:3])})")
            if operation == "__len__":
                valid = self.emit_value(f"icmp ule i128 {count}, 9223372036854775807")
                self.guard_exception(node, valid, "OverflowError", "Python int too large to convert to C ssize_t")
            elif operation == "__getitem__":
                index = self.emit_value(f"sext i64 {value} to i128")
                negative = self.emit_value(f"icmp slt i128 {index}, 0")
                offset = self.emit_value(f"add i128 {index}, {count}")
                actual = self.emit_value(f"select i1 {negative}, i128 {offset}, i128 {index}")
                valid = self.emit_value(f"icmp ult i128 {actual}, {count}")
                self.guard_exception(node, valid, "IndexError", "range object index out of range")
        symbols = {"__len__": ("i64", "length"), "__getitem__": ("i64", "get"),
                   "__bool__": ("i128", "length.i128")}
        if operation not in symbols:
            raise LLVMUnsupported(f"LLVM range operation {operation} is not implemented", node)
        kind, symbol = symbols[operation]
        result = self.emit_value(f"call {kind} @pyjs.range.{symbol}({', '.join(parameters)})")
        if operation == "__bool__":
            return "i1", self.emit_value(f"icmp ne i128 {result}, 0")
        return kind, result

    def trap_unless(self, condition: str) -> None:
        valid = self.new_label("checked.valid")
        invalid = self.new_label("checked.invalid")
        self.emit_line(f"br i1 {condition}, label %{valid}, label %{invalid}")
        self.emit_line(f"{invalid}:")
        self.emit_line("call void @llvm.trap()")
        self.emit_line("unreachable")
        self.emit_line(f"{valid}:")

    def guard_float_to_integer(self, node: ast.AST, value: str) -> None:
        # fptosi is poison for NaN, infinity, and values outside signed i64.
        ordered = self.emit_value(f"fcmp ord double {value}, {value}")
        self.guard_exception(node, ordered, "ValueError", "cannot convert float NaN to integer")
        absolute = self.emit_value(f"call double @llvm.fabs.f64(double {value})")
        finite = self.emit_value(f"fcmp one double {absolute}, 0x7FF0000000000000")
        self.guard_exception(node, finite, "OverflowError", "cannot convert float infinity to integer")
        lower = self.emit_value(f"fcmp oge double {value}, 0xC3E0000000000000")
        upper = self.emit_value(f"fcmp olt double {value}, 0x43E0000000000000")
        self.guard_exception(node, self.emit_value(f"and i1 {lower}, {upper}"),
                             "OverflowError", "float is outside native signed i64 range")

    def numeric_from_string(self, node: ast.Call, *, floating: bool) -> tuple[str, str]:
        if not 1 <= len(node.args) <= (1 if floating else 2) or any(
            keyword.arg != "base" or floating for keyword in node.keywords
        ) or len(node.keywords) > 1 or (len(node.args) == 2 and node.keywords):
            raise LLVMUnsupported("LLVM numeric text conversion has invalid arguments", node)
        _, source = self.expression(node.args[0])
        base = "10"
        if not floating:
            base_node = node.args[1] if len(node.args) == 2 else (
                node.keywords[0].value if node.keywords else None
            )
            base_kind, base = self.expression(base_node) if base_node is not None else ("i64", "10")
            base = self.index_integer(base_kind, base, base_node or node, "LLVM int() base must be an integer")
            zero = self.emit_value(f"icmp eq i64 {base}, 0")
            low = self.emit_value(f"icmp sge i64 {base}, 2")
            high = self.emit_value(f"icmp sle i64 {base}, 36")
            valid_base = self.emit_value(f"and i1 {low}, {high}")
            self.guard_exception(node, self.emit_value(f"or i1 {zero}, {valid_base}"),
                                 "ValueError", "int() base must be >= 2 and <= 36, or 0")
        binary = enum_ops.storage_name(analyzed_value_type(node.args[0])) == "bytes"
        return self.parse_numeric_text(node, source, floating=floating, base=base, binary=binary)

    def parse_numeric_text(self, node, source, *, floating, base="10", binary=False):
        """Shared checked conversion for int/float calls and DOM state reads."""
        whitespace = f"@{self.string_constant(runtime_numeric.WHITESPACE)}"
        kind = "double" if floating else "i64"
        arguments = (f"ptr {self.load_local('__arena')}, ptr {source}, ptr {whitespace}" if floating
                     else f"ptr {source}, i64 {base}, ptr {whitespace}")
        symbol = "float" if floating else "int"
        if binary:
            # Numeric bytes accept ASCII only, unlike Unicode decimal digits
            # and whitespace in str. Skip the Unicode parser on arbitrary bytes;
            # use its invalid status without introducing a loop-local alloca.
            ascii_input = self.emit_value(f"call i1 @pyjs.string.is.ascii(ptr {source})")
            parse, invalid, done = (self.new_label("numeric.bytes." + label)
                                    for label in ("parse", "invalid", "done"))
            self.emit_line(f"br i1 {ascii_input}, label %{parse}, label %{invalid}")
            self.emit_line(f"{invalid}:")
            self.emit_line(f"br label %{done}")
            self.emit_line(f"{parse}:")
        pair = self.emit_value(f"call {{ i8, {kind} }} @pyjs.{symbol}.from.string({arguments})")
        if binary:
            self.emit_line(f"br label %{done}")
            self.emit_line(f"{done}:")
            pair = self.emit_value(f"phi {{ i8, {kind} }} [ {pair}, %{parse} ], [ zeroinitializer, %{invalid} ]")
        status = self.emit_value(f"extractvalue {{ i8, {kind} }} {pair}, 0")
        if floating:
            self.guard_exception(node, self.emit_value(f"icmp ne i8 {status}, 2"),
                                 "MemoryError", "native float parsing allocation failed")
        else:
            self.guard_exception(node, self.emit_value(f"icmp ne i8 {status}, 3"),
                                 "ValueError", "integer value is outside native signed i64 range")
        valid = self.emit_value(f"icmp eq i8 {status}, 1")
        if self.module.uses_exceptions:
            passed, failed = self.new_label("numeric.valid"), self.new_label("numeric.invalid")
            self.emit_line(f"br i1 {valid}, label %{passed}, label %{failed}")
            self.emit_line(f"{failed}:")
            if floating:
                message = f"@{self.string_constant('could not convert string to float: ')}"
            else:
                message = self.string_concat(f"@{self.string_constant('invalid literal for int() with base ')}",
                                             self.string_from_int(base))
                message = self.string_concat(message, f"@{self.string_constant(': ')}")
            rendered = (representation.render(self, NATIVE_ENVIRONMENT.builtins.search("bytes"),
                                              "ptr", source, node)[1] if binary else self.key_message("ptr", source))
            if binary and not floating:
                # CPython limits int's offending literal repr to 200 characters;
                # bytes repr is ASCII even for arbitrary non-ASCII input.
                rendered = self.owned_text_call("pyjs.string.slice", [
                    f"ptr {rendered}", "i64 0", "i1 false", "i64 200", "i1 true", "i64 1", "i1 true",
                ])[1]
            message = self.string_concat(message, rendered)
            self.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("ValueError"), message)
            self.branch_to_exception_target()
            self.emit_line(f"{passed}:")
        else:
            self.trap_unless(valid)
        value = self.emit_value(f"extractvalue {{ i8, {kind} }} {pair}, 1")
        return (self.normalize_float_result(value, node) if floating
                else self.normalize_integer_result(value, node))

    def builtin_round(self, node: ast.Call) -> tuple[str, str]:
        with calls.bind(self, node.func.obj, node) as bound:
            number, digits = [tagged.numeric(self, source, *value)
                              for source, value in zip(bound.sources, bound.values, strict=True)]
            kind, value = number
            if digits[0] == "i1":
                digits = "i64", self.emit_value(f"zext i1 {digits[1]} to i64")
            if digits[0] not in {"void", "i64"}:
                raise LLVMUnsupported("LLVM round ndigits must be int or literal None", node)
            if kind == "i1":
                kind, value = "i64", self.emit_value(f"zext i1 {value} to i64")
            if kind == "i64":
                if digits[0] != "void":
                    wide = self.emit_value(f"call i128 @pyjs.int.round.wide(i64 {value}, i64 {digits[1]})")
                    value = (self.emit_value(f"trunc i128 {wide} to i64") if analyzed_numeric_format(node) is not None
                             else self.checked_narrow_integer(node, wide, "rounded integer exceeds native i64 limits"))
                return self.normalize_integer_result(value, node)
            if kind != "double":
                raise LLVMUnsupported("LLVM round requires a number", node)
            if digits[0] != "void":
                result = self.emit_value(f"call double @pyjs.float.round.digits(double {value}, i64 {digits[1]})")
                original_abs = self.emit_value(f"call double @llvm.fabs.f64(double {value})")
                result_abs = self.emit_value(f"call double @llvm.fabs.f64(double {result})")
                original_inf = self.emit_value(f"fcmp oeq double {original_abs}, 0x7FF0000000000000")
                finite_result = self.emit_value(f"fcmp une double {result_abs}, 0x7FF0000000000000")
                self.guard_exception(node, self.emit_value(f"or i1 {original_inf}, {finite_result}"),
                                     "OverflowError", "rounded value too large to represent")
                return self.normalize_float_result(result, node)
            value = self.emit_value(f"call double @llvm.roundeven.f64(double {value})")
            self.guard_float_to_integer(node, value)
            return "i64", self.emit_value(f"fptosi double {value} to i64")

    def builtin_divmod(self, node: ast.Call) -> tuple[str, str]:
        if len(node.args) != 2 or node.keywords:
            raise LLVMUnsupported("LLVM divmod takes two positional arguments", node)
        arguments = [tagged.numeric(self, argument, *self.expression(argument)) for argument in node.args]
        floating = any(kind == "double" for kind, _ in arguments)
        kind = "double" if floating else "i64"
        values = []
        for actual, value in arguments:
            if actual == "i1":
                actual, value = "i64", self.emit_value(f"zext i1 {value} to i64")
            _, value = self.coerce_numeric(actual, value, kind, node)
            values.append(value)
        representation = analyzed_representation(node)
        item = representation.item_representation if representation is not None else None
        numeric = item.numeric if item is not None else None
        represented = next((arg for arg in node.args if numeric is not None and analyzed_numeric_format(arg) == numeric), None)
        symbol = "float" if floating else "fixed.int" if represented is not None else "int"
        self.guard_nonzero(node, kind, values[1], "division by zero")
        if not floating and represented is None:
            self.guard_division_overflow(node, *values)
        pair = self.emit_value(
            f"call {{ {kind}, {kind} }} @pyjs.{symbol}.divmod("
            f"{kind} {values[0]}, {kind} {values[1]})"
        )
        values = []
        for index in range(2):
            value = self.emit_value(f"extractvalue {{ {kind}, {kind} }} {pair}, {index}")
            if represented is not None:
                _, value = (self.normalize_float_result(value, represented) if floating
                            else self.normalize_integer_result(value, represented))
            values.append((kind, value))
        return "ptr", collection_ops.new_tuple(self, analyzed_value_type(node), values)

    def builtin_modular_pow(self, node: ast.Call) -> tuple[str, str]:
        if len(node.args) != 3 or node.keywords:
            raise LLVMUnsupported("LLVM modular pow takes three positional arguments", node)
        values = []
        for arg in node.args:
            value = self.index_integer(*self.expression(arg), arg, "LLVM modular pow requires integers")
            values.append(f"i64 {value}")
        if analyzed_numeric_format(node) is not None:
            # Fixed-width power rejects negative exponents even with a modulus.
            # Check after evaluating every argument, before modulus validation.
            self.guard_exception(node, self.emit_value(f"icmp sge {values[1]}, 0"),
                                 "ValueError", "negative exponent is not supported for fixed-width integers")
        self.guard_exception(node, self.emit_value(f"icmp ne {values[2]}, 0"),
                             "ValueError", "pow() 3rd argument cannot be 0")
        pair = self.emit_value(f"call {{ i1, i64 }} @pyjs.int.pow.modular({', '.join(values)})")
        self.guard_exception(node, self.emit_value(f"extractvalue {{ i1, i64 }} {pair}, 0"),
                             "ValueError", "base is not invertible for the given modulus")
        result = self.emit_value(f"extractvalue {{ i1, i64 }} {pair}, 1")
        return self.normalize_integer_result(result, node)

    def native_call(
        self,
        target: Function,
        receiver: str | None,
        node: ast.Call,
    ) -> tuple[str, str]:
        decoration = get_native_decoration(target.py_func)
        operation = decoration.operation if decoration is not None else target.name
        if operation in {"delegation.close", "delegation.throw", "delegation.completion"}:
            from . import delegation_ops
            return getattr(delegation_ops, operation.removeprefix("delegation."))(self, node)
        if operation == "operator.index":
            if len(node.args) != 1 or node.keywords or calls.expands_arguments(node):
                raise LLVMUnsupported("LLVM operator.index takes one positional argument", node)
            source = node.args[0]
            kind, value = self.expression(source)
            return "i64", indexing.integer(self, analyzed_value_type(source), kind, value, node)
        if operation == "reference":
            with calls.bind(self, target, node) as arguments:
                kind, value = arguments.values[0]
                dom_ops.mark_reference(self, analyzed_value_type(node), kind, value, node)
                return kind, value
        if operation == "json.dumps":
            return json_ops.dumps(self, target, node)
        if operation == "urllib.parse.urlencode":
            if len(node.args) != 1 or node.keywords or calls.expands_arguments(node):
                raise LLVMUnsupported("LLVM urlencode takes one positional string mapping", node)
            semantic = analyzed_value_type(node.args[0])
            if (getattr(semantic, "generic_name", None) != "dict" or len(semantic.generic_types) != 2
                    or any(getattr(member, "generic_name", None) != "str" for member in semantic.generic_types.values())):
                raise LLVMUnsupported("LLVM urlencode requires dict[str, str]", node)
            _, value = self.expression(node.args[0])
            root = calls.root_values(self, value)
            result = self.allocated_value(f"call ptr @pyjs.urlencode({collection_ops.owner(self)}, ptr {value})")
            calls.pop_roots(self, root)
            return "ptr", result
        if operation == "functools.reduce":
            return callback_ops.reduce(self, node)
        if operation == "functools.partial":
            return partials.create(self, node)
        if operation is not None and operation.startswith("itertools."):
            from . import itertools_ops
            return itertools_ops.call(self, operation, node)
        if operation in {"math.ldexp", "math.frexp", "math.modf", "math.fsum", "math.hypot", "math.dist"}:
            return math_ops.call(self, target, operation, node)
        if operation == "memory.null":
            return "ptr", "null"
        if operation is not None and (
            operation.startswith("memory.") or operation in {
                "system.write", "system.errno", "system.strtod", "system.format.float",
            }
        ):
            with calls.bind(self, target, node) as bound:
                arguments = bound.values
                values = [value for _, value in arguments]
                if operation in {"memory.bytes.data", "memory.byte_at", "memory.compare_bytes"}:
                    data = self.emit_value(f"getelementptr i64, ptr {values[0]}, i64 1")
                    data = self.emit_value(f"load ptr, ptr {data}")
                    if operation == "memory.bytes.data":
                        return "ptr", data
                    if operation == "memory.byte_at":
                        slot = self.emit_value(f"getelementptr i8, ptr {data}, i64 {values[1]}")
                        byte = self.emit_value(f"load i8, ptr {slot}")
                        return "i64", self.emit_value(f"zext i8 {byte} to i64")
                    other = self.emit_value(f"getelementptr i64, ptr {values[1]}, i64 1")
                    other = self.emit_value(f"load ptr, ptr {other}")
                    left = self.emit_value(f"getelementptr i8, ptr {data}, i64 {values[2]}")
                    right = self.emit_value(f"getelementptr i8, ptr {other}, i64 {values[3]}")
                    result = self.emit_value(f"call i32 @memcmp(ptr {left}, ptr {right}, i64 {values[4]})")
                    return "i64", self.emit_value(f"sext i32 {result} to i64")
                if operation == "system.write":
                    _, descriptor = self.narrow_numeric(*arguments[0], "i32", node)
                    instruction = f"call i64 @write(i32 {descriptor}, ptr {values[1]}, i64 {values[2]})"
                    result_type = "i64"
                elif operation == "system.errno":
                    instruction = f"call ptr @{errno_symbol()}()"
                    self.runtime_primitive_instructions.add(instruction)
                    address = self.emit_value(instruction)
                    value = self.emit_value(f"load i32, ptr {address}")
                    return self.widen_numeric("i32", value, target.return_numeric_format)
                elif operation == "system.strtod":
                    instruction = f"call double @strtod(ptr {values[0]}, ptr {values[1]})"
                    result_type = "double"
                elif operation == "system.format.float":
                    _, precision = self.narrow_numeric(*arguments[3], "i32", node)
                    instruction = (
                        "call i32 (ptr, i64, ptr, ...) @snprintf("
                        f"ptr {values[0]}, i64 {values[1]}, ptr {values[2]}, i32 {precision}, double {values[4]})"
                    )
                    result_type = "i32"
                elif operation == "memory.trap":
                    instruction, result_type = "call void @llvm.trap()", "void"
                elif operation == "memory.store":
                    parameter = target.params[1]
                    kind, value = self.narrow_numeric(
                        *arguments[1],
                        self.annotation_storage_type(parameter.annotation, analyzed_numeric_format(parameter)),
                        node,
                    )
                    instruction, result_type = f"store {kind} {value}, ptr {values[0]}", "void"
                    if kind == "i128":
                        instruction += ", align 1"
                elif operation in {"memory.copy", "memory.move"}:
                    intrinsic = "memcpy" if operation == "memory.copy" else "memmove"
                    instruction = (
                        f"call void @llvm.{intrinsic}.p0.p0.i64(ptr {values[0]}, "
                        f"ptr {values[1]}, i64 {values[2]}, i1 false)"
                    )
                    result_type = "void"
                elif operation == "memory.fill":
                    _, value = self.narrow_numeric(*arguments[1], "i8", node)
                    instruction = f"call void @llvm.memset.p0.i64(ptr {values[0]}, i8 {value}, i64 {values[2]}, i1 false)"
                    result_type = "void"
                elif operation == "memory.allocate.zeroed":
                    instruction, result_type = f"call ptr @calloc(i64 1, i64 {values[0]})", "ptr"
                elif operation in {"memory.collection.header", "memory.iterator.header", "memory.mapping.header",
                                   "memory.tuple.header", "memory.group.header"}:
                    rendered = ", ".join(f"{kind} {value}" for kind, value in arguments)
                    family = operation.split(".")[1]
                    instruction, result_type = f"call ptr @pyjs.{family}.allocate.header({rendered})", "ptr"
                elif operation == "memory.scalar.allocator":
                    instruction, result_type = f"call ptr @pyjs.collection.scalar.allocator(ptr {values[0]})", "ptr"
                elif operation == "memory.sort.addresses":
                    instruction = f"call void @qsort(ptr {values[0]}, i64 {values[1]}, i64 8, ptr @pyjs.gc.index.compare)"
                    result_type = "void"
                elif operation in {"memory.invoke", "memory.trace"}:
                    converted = [
                        self.narrow_numeric(
                            *argument,
                            self.annotation_storage_type(parameter.annotation, analyzed_numeric_format(parameter)),
                            node,
                        )
                        for parameter, argument in zip(target.params[1:], arguments[1:], strict=True)
                    ]
                    rendered = ", ".join(f"{kind} {value}" for kind, value in converted)
                    result_type = self.result_storage_type(target.return_type, target.return_numeric_format)
                    instruction = f"call {result_type} {values[0]}({rendered})"
                elif operation in {"memory.allocate", "memory.reallocate", "memory.free"}:
                    symbol = {"memory.allocate": "malloc", "memory.reallocate": "realloc", "memory.free": "free"}[operation]
                    result_type = "void" if operation == "memory.free" else "ptr"
                    rendered = ", ".join(f"{kind} {value}" for kind, value in arguments)
                    instruction = f"call {result_type} @{symbol}({rendered})"
                else:
                    raise LLVMUnsupported(f"unsupported unmanaged operation {operation}", node)
                # Only typed, explicit unmanaged primitives may write borrowed memory
                # or allocate outside managed contexts. Inline strings are not trusted.
                self.runtime_primitive_instructions.add(instruction)
                if result_type == "void":
                    self.emit_line(instruction)
                    return "void", ""
                return self.widen_numeric(result_type, self.emit_value(instruction), target.return_numeric_format)
        if decoration is not None and decoration.kind == "inline":
            if target.vararg is not None or target.kwarg is not None:
                raise LLVMUnsupported("LLVM inline declarations cannot use variadic parameters", node)
            template = decoration.template
            if template == "":
                if getattr(target.return_type, "generic_name", None) != "NoneType":
                    raise LLVMUnsupported("empty LLVM inline requires a None return", node)
                return "void", ""
            with calls.bind(self, target, node) as bound:
                parameters = calls.parameters(target)
                # Templates cross the same declared boundary as ordinary
                # calls: an application DOM wrapper is not a DOM pointer, and
                # erased objects/iterable views can require fresh adapters.
                # Keep those adapters alive through later conversions and an
                # inline instruction that may itself invoke the collector.
                roots, frame = calls.object_argument_roots(self, (p.annotation.obj for p in parameters))
                converted = calls.convert(self, target, bound, node, box=True, roots=roots)

                def finish(result):
                    calls.pop_roots(self, frame)
                    return result

                arguments = list(converted)
                names = [parameter.arg for parameter in parameters]
                if receiver is not None:
                    names.insert(0, "self")
                    arguments.insert(0, ("ptr", receiver))
                values = dict(zip(names, arguments, strict=True))
                result_type = self.result_storage_type(target.return_type, target.return_numeric_format)
                forwarded = next(((name, value) for name, value in values.items() if template == "{" + name + "}"), None)
                if forwarded is not None:
                    if result_type == "void":
                        return finish(("void", ""))
                    name, forwarded = forwarded
                    if receiver is not None and name == "self":
                        operand_type = target.cls
                    else:
                        parameter = next(parameter for parameter in parameters if parameter.arg == name)
                        operand_type = parameter.annotation.obj
                        forwarded = self.widen_numeric(*forwarded, analyzed_numeric_format(parameter))
                    collection_ops.require_matching_layout(operand_type, target.return_type, node)
                    semantic = self.value_type(target.return_type)
                    if forwarded[0] != semantic:
                        raise LLVMUnsupported("LLVM inline operand does not match its return storage type", node)
                    return finish(self.widen_numeric(
                        *self.narrow_numeric(*forwarded, result_type, node), target.return_numeric_format,
                    ))
                if receiver is not None:
                    converted.insert(0, ("ptr", receiver))
                rendered = template.format_map({
                    name: value for name, (_, value) in zip(names, converted, strict=True)
                })
                # Caller-authored polls are observable instructions, even if
                # their spelling matches a compiler-inserted GC poll.
                if re.search(r"\b(?:call|invoke|callbr)\b", rendered):
                    self.has_inline_calls = True
                if result_type == "void":
                    self.emit_line(rendered, hoist_alloca=False)
                    return finish(("void", ""))
                return finish(self.widen_numeric(
                    result_type, self.emit_value(rendered, hoist_alloca=False),
                    target.return_numeric_format,
                ))
        arena = self.load_local("__arena")
        if operation in {
            "runtime.gc_collect",
            "runtime.gc_count",
            "runtime.gc_disable",
            "runtime.gc_enable",
            "runtime.gc_is_enabled",
            "runtime.gc_pin",
            "runtime.gc_set_threshold",
            "runtime.gc_unpin",
        }:
            heap = self.load_local("__heap")
            if operation in {"runtime.gc_pin", "runtime.gc_unpin"}:
                if len(node.args) != 1 or node.keywords:
                    raise LLVMUnsupported(
                        f"LLVM {operation} takes one positional value",
                        node,
                    )
                value_type, value = self.expression(node.args[0])
                if value_type != "ptr":
                    raise LLVMUnsupported(
                        f"LLVM {operation} requires a managed object",
                        node,
                    )
                function = operation.removeprefix("runtime.gc_")
                if function == "pin":
                    found = self.emit_value(f"call ptr @pyjs.gc.find(ptr {heap}, ptr {value})")
                    self.guard_exception(node, self.emit_value(f"icmp ne ptr {found}, null"),
                                         "ValueError", "gc_pin requires a managed object")
                    pinned = self.emit_value(f"call i1 @pyjs.gc.try.pin(ptr {heap}, ptr {value})")
                    self.guard_exception(node, pinned, "MemoryError", "native pin allocation failed")
                else:
                    self.emit_line(f"call void @pyjs.gc.unpin(ptr {heap}, ptr {value})")
                return "void", ""
            if operation == "runtime.gc_set_threshold":
                # Bind once in Python evaluation order, then validate both
                # budgets before publishing either of them to the heap.
                with calls.bind(self, target, node) as arguments:
                    values = [self.index_integer(kind, value, node, "LLVM gc_set_threshold requires integer budgets")
                              for kind, value in arguments.values]
                    for value, message in zip(values, (
                            "GC threshold must be positive", "GC byte threshold must be positive"), strict=True):
                        self.guard_exception(node, self.emit_value(f"icmp sgt i64 {value}, 0"), "ValueError", message)
                    self.emit_line(
                        f"call void @pyjs.gc.set.threshold(ptr {heap}, i64 {values[0]}, i64 {values[1]})"
                    )
                return "void", ""
            if node.args or node.keywords:
                raise LLVMUnsupported(f"LLVM {operation} takes no arguments", node)
            if operation == "runtime.gc_collect":
                collected = self.emit_value(f"call i1 @pyjs.gc.try.collect(ptr {heap})")
                self.guard_exception(node, collected, "MemoryError", "native collection allocation failed")
                return "void", ""
            if operation in {"runtime.gc_disable", "runtime.gc_enable"}:
                function = operation.removeprefix("runtime.gc_")
                self.emit_line(
                    f"call void @pyjs.gc.{function}(ptr {heap})"
                )
                return "void", ""
            if operation == "runtime.gc_is_enabled":
                result = self.new_temporary()
                self.emit_line(
                    f"{result} = call i1 @pyjs.gc.is.enabled(ptr {heap})"
                )
                return "i1", result
            result = self.new_temporary()
            self.emit_line(f"{result} = call i64 @pyjs.gc.count(ptr {heap})")
            return "i64", result
        if operation in {"render_html", "render_document"} and receiver is None:
            if len(node.args) != 1 or node.keywords:
                raise LLVMUnsupported(
                    f"LLVM native {operation} takes one element",
                    node,
                )
            root = dom_ops.root(self, node.args[0])
            result = self.new_temporary()
            self.emit_line(
                f"{result} = call ptr @pyjs.native.document.render("
                f"ptr {arena}, ptr null, ptr {root})"
            )
            self.require_allocation(result)
            if operation == "render_document":
                result = self.string_concat(
                    f"@{self.string_constant('<!doctype html>\n')}",
                    result,
                )
            return "ptr", result
        if operation == "write_html_fd" and receiver is None:
            if len(node.args) != 2 or node.keywords:
                raise LLVMUnsupported(
                    "LLVM native write_html_fd takes an element and descriptor",
                    node,
                )
            root = dom_ops.root(self, node.args[0])
            descriptor_type, descriptor = self.expression(node.args[1])
            descriptor = self.index_integer(descriptor_type, descriptor, node.args[1],
                                            "LLVM native write_html_fd requires an integer descriptor")
            self.guard_c_int(node, descriptor)
            result = self.new_temporary()
            self.emit_line(
                f"{result} = call i64 @pyjs.native.document.write("
                f"ptr {arena}, ptr null, ptr {root}, i64 {descriptor})"
            )
            return "i64", result
        if operation == "class_attribute" and receiver is None:
            with calls.bind(self, target, node) as arguments:
                _, value = arguments.values[0]
                # A first-class tw() result is an actual dict, not an Attribute
                # pointer that only happens to work as a direct builder argument.
                string = NATIVE_ENVIRONMENT.builtins.search("str")
                result = collection_ops.new_mapping(self, string, string)
                slot = self.dictionary_set_slot(result, string, "ptr", f"@{self.string_constant('class')}", "8", node)
                self.emit_line(f"store ptr {value}, ptr {slot}")
                return "ptr", result
        if operation == "element" and receiver is None:
            if node.keywords or decoration is None or decoration.constant is None:
                raise LLVMUnsupported("LLVM native element arguments are invalid", node)
            name = f"@{self.string_constant(decoration.constant)}"
            arguments = self.native_argument_pack(node.args, allow_erased=True)
            return "ptr", self.native_element(arena, "null", name, arguments)
        if operation == "tag" and receiver is None:
            if not node.args or node.keywords:
                raise LLVMUnsupported("LLVM native tag requires a name", node)
            name_type, name = self.expression(node.args[0])
            semantic_name = analyzed_value_type(node.args[0])
            if name_type != "ptr":
                raise LLVMUnsupported(
                    "LLVM native tag requires a string or element",
                    node,
                )
            if semantic_name.generic_name != "str":
                if not self.is_web_element_type(semantic_name):
                    raise LLVMUnsupported(
                        "LLVM native tag requires a string or element",
                        node,
                    )
                name = dom_ops.argument(self, node.args[0], name)
                additions = self.native_argument_pack(node.args[1:], builder_receiver=semantic_name,
                                                      builder_target=name, allow_erased=True)
                dom_ops.extend(self, name, additions, node)
                return "ptr", name
            arguments = self.native_argument_pack(node.args[1:], allow_erased=True)
            return "ptr", self.native_element(arena, "null", name, arguments)
        if target.name == "render" and receiver is not None:
            if len(node.args) != 1 or node.keywords:
                raise LLVMUnsupported("LLVM Document.render takes one root", node)
            root = dom_ops.root(self, node.args[0])
            result = self.new_temporary()
            self.emit_line(
                f"{result} = call ptr @pyjs.native.document.render("
                f"ptr {arena}, ptr {receiver}, ptr {root})"
            )
            self.require_allocation(result)
            return "ptr", result
        if target.name == "write" and receiver is not None:
            if len(node.args) != 2 or node.keywords:
                raise LLVMUnsupported(
                    "LLVM Document.write takes one root and descriptor",
                    node,
                )
            root = dom_ops.root(self, node.args[0])
            descriptor_type, descriptor = self.expression(node.args[1])
            descriptor = self.index_integer(descriptor_type, descriptor, node.args[1],
                                            "LLVM Document.write requires an integer descriptor")
            self.guard_c_int(node, descriptor)
            result = self.new_temporary()
            self.emit_line(
                f"{result} = call i64 @pyjs.native.document.write("
                f"ptr {arena}, ptr {receiver}, ptr {root}, i64 {descriptor})"
            )
            return "i64", result
        if target.name in {"attr", "cls"} and receiver is None:
            expected = 2 if target.name == "attr" else 1
            if len(node.args) != expected or node.keywords:
                raise LLVMUnsupported(
                    f"LLVM native {target.name} has incompatible arguments",
                    node,
                )
            if target.name == "attr":
                name_type, name = self.expression(node.args[0])
                value_type, value = self.expression(node.args[1])
            else:
                name_type, name = "ptr", f"@{self.string_constant('class')}"
                value_type, value = self.expression(node.args[0])
            if name_type != "ptr" or value_type != "ptr":
                raise LLVMUnsupported("LLVM native attributes require strings", node)
            return "ptr", self.native_attribute(arena, name, value)
        tag_names = {"div": "div", "paragraph": "p", "span": "span"}
        if target.name in tag_names and receiver is None:
            if not node.args:
                raise LLVMUnsupported("LLVM native element requires Document", node)
            document_type, document = self.expression(node.args[0])
            if document_type != "ptr":
                raise LLVMUnsupported("LLVM native element requires Document", node)
            name = f"@{self.string_constant(tag_names[target.name])}"
            arguments = self.native_argument_pack(node.args[1:])
            return "ptr", self.native_element(arena, document, name, arguments)
        if target.name == "tag" and receiver is None:
            if len(node.args) < 2:
                raise LLVMUnsupported("LLVM native tag requires name", node)
            document_type, document = self.expression(node.args[0])
            name_type, name = self.expression(node.args[1])
            if document_type != "ptr" or name_type != "ptr":
                raise LLVMUnsupported("LLVM native tag arguments are invalid", node)
            arguments = self.native_argument_pack(node.args[2:])
            return "ptr", self.native_element(arena, document, name, arguments)
        if target.name == "element" and receiver is not None:
            if not node.args:
                raise LLVMUnsupported("LLVM Document.element requires name", node)
            name_type, name = self.expression(node.args[0])
            if name_type != "ptr":
                raise LLVMUnsupported("LLVM Document.element name must be str", node)
            arguments = self.native_argument_pack(node.args[1:])
            return "ptr", self.native_element(arena, receiver, name, arguments)
        raise LLVMUnsupported(
            f"LLVM native declaration {target.name} is not implemented",
            node,
        )

    def native_attribute(self, arena: str, name: str, value: str) -> str:
        name = self.arena_string(arena, name)
        value = self.arena_string(arena, value)
        result = self.new_temporary()
        self.emit_line(
            f"{result} = call ptr @pyjs.native.attribute.new("
            f"ptr {arena}, ptr {name}, ptr {value})"
        )
        self.require_allocation(result)
        return result

    def native_element(
        self,
        arena: str,
        document: str,
        name: str,
        arguments: str,
    ) -> str:
        # Every caller supplies a fresh native_argument_pack. Transfer that
        # list to the element so later appends can grow it without alias writes.
        name = self.arena_string(arena, name)
        result = self.new_temporary()
        self.emit_line(
            f"{result} = call ptr @pyjs.native.element.new.owned(ptr {arena}, "
            f"ptr {document}, ptr {name}, ptr {arguments})"
        )
        self.require_allocation(result)
        return result

    def native_element_arguments(self, element: str) -> str:
        pointer = self.new_temporary()
        result = self.new_temporary()
        self.emit_line(
            f"{pointer} = getelementptr %pyjs.native.element, ptr {element}, i32 0, i32 1"
        )
        self.emit_line(f"{result} = load ptr, ptr {pointer}")
        return result

    @staticmethod
    def native_argument_needs_staging(argument):
        # A literal dict or immediate tw() creates a fresh private dictionary:
        # later arguments cannot mutate it. Other dictionaries (also within
        # expansions/unions) must be read only after argument evaluation ends.
        # Proxy children likewise read .element after later arguments may have
        # replaced it; staging retains the wrapper, not an early node snapshot.
        # Nullable arguments can fail inside the builder; that must not skip
        # evaluation (or exception priority) of any later call argument.
        if isinstance(getattr(argument, "source", argument), ast.Dict):
            return False
        if isinstance(argument, ast.Call):
            target = analyzed_value_object(argument.func)
            decoration = get_native_decoration(target.py_func) if isinstance(target, Function) else None
            if decoration is not None and decoration.operation == "class_attribute":
                return False
        source = argument.value if isinstance(argument, ast.Starred) else argument
        semantic = analyzed_value_type(source)
        if isinstance(argument, ast.Starred):
            members = (semantic.generic_types.values() if collection_ops.is_fixed_tuple(semantic)
                       else (collection_ops.item_type(semantic),))
        else:
            members = (semantic,)
        return any(collection_ops.builtin_name(member) in {"dict", "NoneType"}
                   or nullable.is_object(member)
                   or FunctionEmitter.is_proxy_element_type(member)
                   for item in members for member in get_type_members(item))

    def native_argument_pack(
        self,
        arguments: list[ast.expr],
        *,
        builder_receiver=None,
        builder_target=None,
        allow_erased=False,
    ) -> str:
        # Builders evaluate all arguments before entering their bodies.
        # Later arguments may mutate earlier dictionaries or replace the target
        # DOM pack. Keep values rooted, then stage into a private argument pack.
        evaluated = None
        if builder_receiver is not None or any(self.native_argument_needs_staging(arg) for arg in arguments):
            evaluated = []
            for arg in arguments:
                source = arg.value if isinstance(arg, ast.Starred) else arg
                kind, value = self.expression(source)
                semantic = analyzed_value_type(source)
                if isinstance(arg, ast.Starred) and not collection_ops.is_fixed_tuple(semantic):
                    member = collection_ops.item_type(semantic)
                    snapshot = collection_ops.new_list(self, member)
                    frame = calls.root_values(self, snapshot)
                    collection_ops.loop(self, semantic, value,
                        lambda actual, item, snapshot=snapshot, member=member, arg=arg:
                            collection_ops.append(self, snapshot, member, actual, item, arg), arg)
                    calls.pop_roots(self, frame)
                    value = snapshot
                    if self.module.uses_gc:
                        # The expanded snapshot replaces this expression's
                        # iterable result; retain it across later callbacks.
                        root = self.expression_roots.get(id(source))
                        if root is None:
                            raise LLVMUnsupported("LLVM DOM expansion requires a rooted iterable", arg)
                        self.emit_line(f"store ptr {value}, ptr {root}")
                evaluated.append((kind, value, semantic))
        item_size = self.llvm_size("ptr")
        arena = self.load_local("__arena")
        result = self.new_temporary()
        self.emit_line(
            f"{result} = call ptr @pyjs.list.new(ptr {arena}, i64 {item_size}, i64 0)"
        )
        self.require_allocation(result)
        for index, argument in enumerate(arguments):
            dictionary = (
                argument.source
                if isinstance(argument, CollectionNew)
                and isinstance(argument.source, ast.Dict)
                else argument
                if isinstance(argument, ast.Dict)
                else None
            )
            if evaluated is None and dictionary is not None:
                for key, item in zip(
                    dictionary.keys,
                    dictionary.values,
                    strict=True,
                ):
                    if key is None:
                        raise LLVMUnsupported(
                            "LLVM native attributes do not support dictionary unpacking",
                            argument,
                        )
                    name_type, name = self.expression(key)
                    value_type, value = self.expression(item)
                    if name_type != "ptr" or value_type != "ptr":
                        raise LLVMUnsupported(
                            "LLVM native attribute names and values must be strings",
                            argument,
                        )
                    attribute = self.native_attribute(arena, name, value)
                    self.append_native_argument(
                        arena,
                        result,
                        item_size,
                        1,
                        attribute,
                    )
                continue
            if isinstance(argument, ast.Starred):
                if evaluated is None:
                    value_type, value = self.expression(argument.value)
                    semantic_type = analyzed_value_type(argument.value)
                else:
                    value_type, value, semantic_type = evaluated[index]
                if value_type != "ptr":
                    raise LLVMUnsupported("LLVM starred native argument must be iterable", argument)
                if collection_ops.is_fixed_tuple(semantic_type):
                    # Fixed tuple slots are immutable, so the rooted tuple is
                    # already a snapshot. Read each slot using its own layout;
                    # a heterogeneous tuple has no homogeneous iteration stride.
                    for member, element in collection_ops.tuple_items(self, semantic_type, value):
                        dom_ops.append(self, result, member, self.value_type(member), element, argument,
                                       builder_receiver=builder_receiver, builder_target=builder_target,
                                       allow_erased=allow_erased)
                    continue
                item_type = collection_ops.item_type(semantic_type)
                if evaluated is not None:
                    collection_ops.loop_storage(self, "list", item_type, value,
                        lambda member, element, argument=argument:
                            dom_ops.append(self, result, member, self.value_type(member), element, argument,
                                           builder_receiver=builder_receiver,
                                           builder_target=builder_target, allow_erased=allow_erased), argument)
                elif (semantic_type.generic_name == "list" and not isinstance(item_type, UnionType)
                        and dom_ops.is_element(self, item_type)
                        and item_type not in self.module.custom_element_types
                        and not self.module.custom_element_types):
                    success = self.emit_value(
                        f"call i1 @pyjs.native.arguments.extend.elements("
                        f"ptr {arena}, ptr {result}, ptr {value})"
                    )
                    self.guard_exception(argument, success, "MemoryError", "native argument allocation failed")
                else:
                    collection_ops.loop(self, semantic_type, value,
                                        lambda member, element, argument=argument:
                                            dom_ops.append(self, result, member, self.value_type(member), element, argument,
                                                           builder_receiver=builder_receiver,
                                                           builder_target=builder_target, allow_erased=allow_erased),
                                        argument)
                continue
            target = (
                analyzed_value_object(argument.func)
                if isinstance(argument, ast.Call)
                else None
            )
            decoration = (
                get_native_decoration(target.py_func)
                if isinstance(target, Function)
                else None
            )
            if evaluated is None and decoration is not None and decoration.operation == "class_attribute":
                # Inline the one-entry dictionary only at its immediate DOM
                # consumer; elsewhere native_call preserves tw()'s dict ABI.
                with calls.bind(self, target, argument) as bound:
                    _, value = bound.values[0]
                    attribute = self.native_attribute(arena, f"@{self.string_constant('class')}", value)
                    self.append_native_argument(arena, result, item_size, 1, attribute)
                continue
            if evaluated is None:
                value_type, value = self.expression(argument)
                semantic_type = analyzed_value_type(argument)
            else:
                value_type, value, semantic_type = evaluated[index]
            dom_ops.append(self, result, semantic_type, value_type, value, argument,
                           builder_receiver=builder_receiver, builder_target=builder_target,
                           allow_erased=allow_erased)
        return result

    def append_native_argument(
        self,
        arena: str,
        arguments: str,
        item_size: int,
        tag: int,
        value: str,
    ) -> None:
        if tag == 3:
            value = self.arena_string(arena, value)
        native_argument = self.new_temporary()
        self.emit_line(
            f"{native_argument} = call ptr @pyjs.native.argument.new("
            f"ptr {arena}, i8 {tag}, ptr {value})"
        )
        self.require_allocation(native_argument)
        slot = self.new_temporary()
        self.emit_line(
            f"{slot} = call ptr @pyjs.list.append.slot(ptr {arena}, "
            f"ptr {arguments}, i64 {item_size})"
        )
        self.require_allocation(slot)
        self.emit_line(f"store ptr {native_argument}, ptr {slot}")

    @staticmethod
    def is_super_call(node: ast.AST) -> bool:
        return super_proxy.is_receiver(node)

    def context_arguments(self) -> list[tuple[str, str]]:
        values = []
        if self.module.uses_arena:
            values.append(("ptr", self.load_local("__arena")))
        if self.module.uses_gc:
            values.append(("ptr", self.load_local("__heap")))
        if self.module.uses_exceptions:
            values.append(("ptr", self.load_local("__exception")))
        return values

    def object_new(self, node: ObjectNew) -> tuple[str, str]:
        if enum_ops.scalar_name(node.value_type):
            return enum_ops.construct(self, node)
        layout = self.module.classes.get(node.value_type)
        if layout is None and node.value_type.container.name != "pyjs.native":
            # Unsupported first-class exception instances have neither an
            # application layout nor generic collection members to trace.
            raise LLVMUnsupported(
                f"LLVM cannot allocate class {node.value_type.name}",
                node,
            )
        managed = self.prepare_allocation(node)
        if layout is None:
            return self.native_object_new(node, managed)
        constructor = layout.constructor
        arguments = None
        if constructor is not None and (
            constructor in self.module.functions
            or constructor.py_func is native_builtins._object.__init__
        ):
            # The implicit constructor has a binding contract even though its
            # empty body is not emitted. Expansion may produce zero arguments.
            arguments = calls.bind(self, constructor, node.call)
        elif node.call.args or node.call.keywords:
            raise LLVMUnsupported(f"LLVM class {node.value_type.name} has no emitted constructor", node)
        with arguments if arguments is not None else calls.BoundCall([], []):
            if node.value_type in self.module.custom_element_types:
                return dom_ops.construct(self, node, layout, arguments)
            result = self.allocate_instance(node.value_type, managed)
            self.invoke_constructor(node, layout, result, arguments)
            return "ptr", result

    def allocate_instance(self, value_type, managed):
        """Allocate the common application layout, including any private prefix."""
        class_name = self.class_name(value_type)
        # Empty instances still need a markable, pinnable identity.
        size = self.llvm_size(f"%{class_name}") if (
            self.module.layout_fields[value_type] or value_type in self.module.vtable_roots
            or value_type in self.module.custom_element_types
        ) else "1"
        result = gc_layouts.allocate(self, self.class_storage(value_type),
                                    layout=f"%{class_name}", managed=managed, size=size)
        if value_type in self.module.vtable_roots:
            self.emit_line(f"store ptr @{self.vtable_name(value_type)}, ptr {result}")
        if self.is_proxy_element_type(value_type):
            if self.module.uses_dom_references:
                self.emit_line(f"store i64 0, ptr {dom_ops.slot(self, value_type, result, 0)}")
            attribute = ast.Attribute(value=ast.Name(id="__proxy", ctx=ast.Load()), attr="element", ctx=ast.Store())
            _, _, address = self.field_pointer(attribute, (value_type, result))
            self.emit_line(f"store ptr null, ptr {address}")
        return result

    def invoke_constructor(
        self,
        node: ObjectNew,
        layout: ClassIR,
        result: str,
        arguments: calls.BoundCall | None,
    ) -> None:
        constructor = layout.constructor
        if constructor is not None and constructor in self.module.functions:
            calls.invoke(self, constructor, arguments, node.call, receiver=result)

    def native_object_new(
        self,
        node: ObjectNew,
        managed: bool,
    ) -> tuple[str, str]:
        if node.value_type.name != "Document" or node.call.args or node.call.keywords:
            raise LLVMUnsupported(
                f"LLVM native construction of {node.value_type.name} is not implemented",
                node,
            )
        result = self.new_temporary()
        if managed:
            heap = self.load_local("__heap")
            self.emit_line(
                f"{result} = call ptr @pyjs.gc.alloc(ptr {heap}, i64 1)"
            )
            self.require_allocation(result)
        else:
            arena = self.load_local("__arena")
            self.emit_line(
                f"{result} = call ptr @pyjs.native.document.new(ptr {arena})"
            )
            self.require_allocation(result)
        return "ptr", result

    def collection_new(self, node: CollectionNew) -> tuple[str, str]:
        representation = analyzed_representation(node)
        parts = representation.arguments if representation else ()
        if isinstance(node.source, ast.List):
            item_type = self.collection_item_type(node.value_type)
        managed = self.prepare_allocation(node)
        if isinstance(node.source, ast.List):
            llvm_item_type = self.value_type(item_type)
            with object_values.converted_values(self, ((item, item_type) for item in node.source.elts),
                    (parts or (None,)) * len(node.source.elts)) as values:
                item_size = self.llvm_size(llvm_item_type)
                arena = self.load_local("__arena")
                result = self.new_temporary()
                if managed:
                    self.emit_line(
                        f"{result} = call ptr @pyjs.list.new.owned("
                        f"ptr {arena}, ptr {gc_layouts.item_allocator(llvm_item_type)}, "
                        f"ptr {self.load_local('__heap')}, "
                        f"i64 {item_size}, i64 {len(values)})"
                    )
                    self.require_allocation(result)
                else:
                    self.emit_line(
                        f"{result} = call ptr @pyjs.list.new(ptr {arena}, "
                        f"i64 {item_size}, i64 {len(values)})"
                    )
                    self.require_allocation(result)
                data_pointer = self.new_temporary()
                data = self.new_temporary()
                self.emit_line(
                    f"{data_pointer} = getelementptr %pyjs.list, ptr {result}, i32 0, i32 2"
                )
                self.emit_line(f"{data} = load ptr, ptr {data_pointer}")
                for index, (_value_type, value) in enumerate(values):
                    slot = self.new_temporary()
                    self.emit_line(
                        f"{slot} = getelementptr {llvm_item_type}, ptr {data}, i64 {index}"
                    )
                    self.emit_line(f"store {llvm_item_type} {value}, ptr {slot}")
                return "ptr", result
        if isinstance(node.source, ast.Dict):
            if any(key is None for key in node.source.keys):
                raise LLVMUnsupported(
                    "LLVM dictionary unpacking is not implemented",
                    node,
                )
            key_type, value_type = self.dictionary_types(node.value_type)
            llvm_key_type = self.value_type(key_type)
            llvm_value_type = self.value_type(value_type)
            items = (item for key, value in zip(node.source.keys, node.source.values, strict=True)
                     for item in ((key, key_type), (value, value_type)))
            with object_values.converted_values(self, items,
                    (parts or (None, None)) * len(node.source.keys)) as values:
                pairs = zip(values[::2], values[1::2], strict=True)
                key_size = self.llvm_size(llvm_key_type)
                value_size = self.llvm_size(llvm_value_type)
                arena = self.load_local("__arena")
                result = self.new_temporary()
                if managed:
                    self.emit_line(
                        f"{result} = call ptr @pyjs.dict.new.typed("
                        f"{collection_ops.mapping_owner(self, llvm_key_type, llvm_value_type)}, "
                        f"i64 {key_size}, i64 {value_size})"
                    )
                    self.require_allocation(result)
                else:
                    self.emit_line(
                        f"{result} = call ptr @pyjs.dict.new(ptr {arena}, "
                        f"i64 {key_size}, i64 {value_size})"
                    )
                    self.require_allocation(result)
                for (actual_key_type, key), (actual_value_type, value) in pairs:
                    slot = self.dictionary_set_slot(
                        result,
                        key_type,
                        actual_key_type,
                        key,
                        value_size,
                        node,
                    )
                    self.emit_line(f"store {actual_value_type} {value}, ptr {slot}")
                return "ptr", result
        if isinstance(node.source, ast.Set):
            item_type = self.set_item_type(node.value_type)
            llvm_item_type = self.value_type(item_type)
            with object_values.converted_values(self, ((item, item_type) for item in node.source.elts),
                    (parts or (None,)) * len(node.source.elts)) as values:
                key_size = self.llvm_size(llvm_item_type)
                result = self.allocated_value(
                    f"call ptr @pyjs.dict.new.typed({collection_ops.mapping_owner(self, llvm_item_type, 'i1', managed)}, "
                    f"i64 {key_size}, i64 1)")
                for actual_type, value in values:
                    slot = self.dictionary_set_slot(result, item_type, actual_type, value, "1", node)
                    self.emit_line(f"store i1 true, ptr {slot}")
                return "ptr", result
        if isinstance(node.source, ast.Tuple):
            members = ([collection_ops.item_type(node.value_type)] * len(node.source.elts) if node.value_type.tuple_variadic
                       else node.value_type.generic_types.values())
            # Iterable context can describe a fixed literal with one generic
            # item, while variadic context may retain per-position metadata.
            # Repeat a homogeneous contract, never an existing slot vector.
            homogeneous = node.value_type.tuple_variadic or representation is not None and representation.kind == "generic"
            representations = (parts * len(node.source.elts) if homogeneous and len(parts) == 1
                               else parts or (None,) * len(node.source.elts))
            with object_values.converted_values(self, zip(node.source.elts, members, strict=True), representations) as values:
                if node.value_type.tuple_variadic:
                    member = collection_ops.item_type(node.value_type)
                    result = collection_ops.new_list(self, member)
                    for _kind, value in values:
                        collection_ops.append(self, result, member, member, value, node)
                    return "ptr", result
                return "ptr", collection_ops.new_tuple(self, node.value_type, values, managed=managed)
        raise LLVMUnsupported(
            f"LLVM {node.value_type.generic_name} allocation is not implemented",
            node,
        )

    def list_append(self, node: ListAppend) -> None:
        list_type = analyzed_value_type(node.call.func.value)
        receiver_type, receiver = self.expression(node.call.func.value)
        list_type, receiver_type, receiver = tagged.untag_single_member(
            self, list_type, receiver_type, receiver, node)
        item_type = self.value_type(self.collection_item_type(list_type))
        value_type, value = self.expression(node.call.args[0])
        representation = analyzed_representation(node.call.func.value)
        value_type, value = self.coerce_value(value_type, value, item_type, node.call.args[0],
                                             semantic=self.collection_item_type(list_type),
                                             representation=representation.item_representation if representation else None)
        if receiver_type != "ptr" or value_type != item_type:
            raise LLVMUnsupported("LLVM list append has incompatible value", node)
        item_size = self.llvm_size(item_type)
        roots = calls.root_values(self, value) if item_type == "ptr" else None
        arena = self.load_local("__arena")
        slot = self.new_temporary()
        self.emit_line(
            f"{slot} = call ptr @pyjs.list.append.slot(ptr {arena}, "
            f"ptr {receiver}, i64 {item_size})"
        )
        self.require_allocation(slot)
        self.emit_line(f"store {item_type} {value}, ptr {slot}")
        calls.pop_roots(self, roots)

    def inline_range_constructor(self, node: IteratorCreate):
        if (self.iterators[node.name][0] == "range" and isinstance(node.iterable, ast.Call)
                and getattr(node.iterable.func, "obj", None) is NATIVE_ENVIRONMENT.builtins.search("range")):
            return node.iterable
        return None

    def iterator_create(self, node: IteratorCreate) -> None:
        kind = self.iterators[node.name][0]
        if kind == "lazy":
            _, iterator = self.expression(node.iterable)
            value_type = analyzed_value_type(node.iterable)
            if not node.acquired:
                iterator = iterator_ops.create(self, value_type, iterator, node)
            self.emit_line(f"store ptr {iterator}, ptr {self.slots[node.name]}")
            return
        if kind == "range":
            if constructor := self.inline_range_constructor(node):
                start, stop, step = self.range_arguments(constructor)
            else:
                _, value = self.expression(node.iterable)
                start, stop, step = self.range_values(value)
            iterator = self.arena_allocate("pyjs.range.iterator")
            for index, value in enumerate((start, stop, step)):
                field = self.new_temporary()
                self.emit_line(
                    f"{field} = getelementptr %pyjs.range.iterator, "
                    f"ptr {iterator}, i32 0, i32 {index}"
                )
                self.emit_line(f"store i64 {value}, ptr {field}")
        else:
            iterable_type, iterable = self.expression(node.iterable)
            if kind in collection_ops.VIEWS:
                iterable = self.emit_value(f"load ptr, ptr {iterable}")
            if iterable_type != "ptr":
                raise LLVMUnsupported("LLVM sequence iterator requires a list", node)
            # The iterator outlives evaluation of its source expression. Its
            # slot must trace that collection after scratch roots are cleared.
            iterator = (gc_layouts.allocate(self, ("ptr", "i64"), layout="%pyjs.sequence.iterator")
                        if self.module.uses_gc else self.arena_allocate("pyjs.sequence.iterator"))
            source = self.new_temporary()
            index = self.new_temporary()
            self.emit_line(
                f"{source} = getelementptr %pyjs.sequence.iterator, "
                f"ptr {iterator}, i32 0, i32 0"
            )
            self.emit_line(f"store ptr {iterable}, ptr {source}")
            self.emit_line(
                f"{index} = getelementptr %pyjs.sequence.iterator, "
                f"ptr {iterator}, i32 0, i32 1"
            )
            self.emit_line(f"store i64 0, ptr {index}")
            if kind in {"dictionary", "set", *collection_ops.VIEWS}:
                length = self.emit_value(f"load i64, ptr {iterable}")
                self.emit_line(f"store i64 {length}, ptr {self.slots[node.name + '.length']}")
        self.emit_line(f"store ptr {iterator}, ptr {self.slots[node.name]}")

    def iterator_next(self, node: IteratorNext) -> None:
        kind, item_type = self.iterators[node.iterator][:2]
        iterator = self.load_local(node.iterator)
        if kind == "lazy":
            iterator_ops.advance_loop(self, node, iterator, item_type)
        elif kind in collection_ops.VIEWS | {"str", "bytes", "tuple"}:
            collection_ops.iterator_next(self, node, iterator, kind, item_type)
        elif kind == "range":
            self.range_iterator_next(node, iterator, item_type)
        elif kind in {"dictionary", "set"}:
            self.dictionary_iterator_next(node, iterator, item_type)
        else:
            self.sequence_iterator_next(node, iterator, item_type)

    def range_iterator_next(self, node, iterator: str, item_type) -> None:
        values = []
        pointers = []
        for index in range(3):
            pointer = self.new_temporary()
            value = self.new_temporary()
            self.emit_line(
                f"{pointer} = getelementptr %pyjs.range.iterator, "
                f"ptr {iterator}, i32 0, i32 {index}"
            )
            self.emit_line(f"{value} = load i64, ptr {pointer}")
            pointers.append(pointer)
            values.append(value)
        current, stop, step = values
        positive = self.new_temporary()
        below = self.new_temporary()
        above = self.new_temporary()
        available = self.new_temporary()
        self.emit_line(f"{positive} = icmp sgt i64 {step}, 0")
        self.emit_line(f"{below} = icmp slt i64 {current}, {stop}")
        self.emit_line(f"{above} = icmp sgt i64 {current}, {stop}")
        self.emit_line(f"{available} = select i1 {positive}, i1 {below}, i1 {above}")
        edge = self.new_label("range.item")
        self.emit_line(
            f"br i1 {available}, label %{edge}, "
            f"label %{self.name(node.exhausted, 'block')}"
        )
        self.emit_line(f"{edge}:")
        self.assign_iterator_target(node.target, item_type, current)
        result = self.new_temporary()
        following = self.new_temporary()
        overflow = self.new_temporary()
        next_value = self.new_temporary()
        self.emit_line(
            f"{result} = call {{ i64, i1 }} @llvm.sadd.with.overflow.i64("
            f"i64 {current}, i64 {step})"
        )
        self.emit_line(f"{following} = extractvalue {{ i64, i1 }} {result}, 0")
        self.emit_line(f"{overflow} = extractvalue {{ i64, i1 }} {result}, 1")
        self.emit_line(
            f"{next_value} = select i1 {overflow}, i64 {stop}, i64 {following}"
        )
        self.emit_line(f"store i64 {next_value}, ptr {pointers[0]}")
        self.emit_line(f"br label %{self.name(node.body, 'block')}")

    def sequence_iterator_next(self, node, iterator: str, item_type) -> None:
        source_pointer = self.new_temporary()
        source = self.new_temporary()
        index_pointer = self.new_temporary()
        index = self.new_temporary()
        self.emit_line(
            f"{source_pointer} = getelementptr %pyjs.sequence.iterator, "
            f"ptr {iterator}, i32 0, i32 0"
        )
        self.emit_line(f"{source} = load ptr, ptr {source_pointer}")
        self.emit_line(
            f"{index_pointer} = getelementptr %pyjs.sequence.iterator, "
            f"ptr {iterator}, i32 0, i32 1"
        )
        self.emit_line(f"{index} = load i64, ptr {index_pointer}")
        length_pointer = self.new_temporary()
        length = self.new_temporary()
        available = self.new_temporary()
        self.emit_line(
            f"{length_pointer} = getelementptr %pyjs.list, ptr {source}, i32 0, i32 0"
        )
        self.emit_line(f"{length} = load i64, ptr {length_pointer}")
        self.emit_line(f"{available} = icmp ult i64 {index}, {length}")
        edge = self.new_label("sequence.item")
        self.emit_line(
            f"br i1 {available}, label %{edge}, "
            f"label %{self.name(node.exhausted, 'block')}"
        )
        self.emit_line(f"{edge}:")
        data_pointer = self.new_temporary()
        data = self.new_temporary()
        llvm_item_type = self.value_type(item_type)
        item_pointer = self.new_temporary()
        item = self.new_temporary()
        self.emit_line(
            f"{data_pointer} = getelementptr %pyjs.list, ptr {source}, i32 0, i32 2"
        )
        self.emit_line(f"{data} = load ptr, ptr {data_pointer}")
        self.emit_line(
            f"{item_pointer} = getelementptr {llvm_item_type}, ptr {data}, i64 {index}"
        )
        self.emit_line(f"{item} = load {llvm_item_type}, ptr {item_pointer}")
        self.assign_iterator_target(node.target, item_type, item)
        following = self.new_temporary()
        self.emit_line(f"{following} = add i64 {index}, 1")
        self.emit_line(f"store i64 {following}, ptr {index_pointer}")
        self.emit_line(f"br label %{self.name(node.body, 'block')}")

    def dictionary_iterator_next(self, node, iterator: str, key_type) -> None:
        source_pointer = self.new_temporary()
        source = self.new_temporary()
        index_pointer = self.new_temporary()
        index = self.new_temporary()
        self.emit_line(
            f"{source_pointer} = getelementptr %pyjs.sequence.iterator, "
            f"ptr {iterator}, i32 0, i32 0"
        )
        self.emit_line(f"{source} = load ptr, ptr {source_pointer}")
        self.emit_line(
            f"{index_pointer} = getelementptr %pyjs.sequence.iterator, "
            f"ptr {iterator}, i32 0, i32 1"
        )
        self.emit_line(f"{index} = load i64, ptr {index_pointer}")
        length_pointer = self.new_temporary()
        length = self.new_temporary()
        available = self.new_temporary()
        self.emit_line(
            f"{length_pointer} = getelementptr %pyjs.dict, "
            f"ptr {source}, i32 0, i32 0"
        )
        self.emit_line(f"{length} = load i64, ptr {length_pointer}")
        self.emit_line(f"{available} = icmp ult i64 {index}, {length}")
        edge = self.new_label("dictionary.item")
        expected = self.load_local(node.iterator + ".length")
        unchanged = self.emit_value(f"icmp eq i64 {length}, {expected}")
        collection = "Set" if self.iterators[node.iterator][0] == "set" else "dictionary"
        self.guard_exception(node, unchanged, "RuntimeError", f"{collection} changed size during iteration")
        self.emit_line(
            f"br i1 {available}, label %{edge}, "
            f"label %{self.name(node.exhausted, 'block')}"
        )
        self.emit_line(f"{edge}:")
        keys_pointer = self.new_temporary()
        keys = self.new_temporary()
        llvm_key_type = self.value_type(key_type)
        key_pointer = self.new_temporary()
        key = self.new_temporary()
        self.emit_line(
            f"{keys_pointer} = getelementptr %pyjs.dict, "
            f"ptr {source}, i32 0, i32 2"
        )
        self.emit_line(f"{keys} = load ptr, ptr {keys_pointer}")
        self.emit_line(
            f"{key_pointer} = getelementptr {llvm_key_type}, "
            f"ptr {keys}, i64 {index}"
        )
        self.emit_line(f"{key} = load {llvm_key_type}, ptr {key_pointer}")
        self.assign_iterator_target(node.target, key_type, key)
        following = self.new_temporary()
        self.emit_line(f"{following} = add i64 {index}, 1")
        self.emit_line(f"store i64 {following}, ptr {index_pointer}")
        self.emit_line(f"br label %{self.name(node.body, 'block')}")

    def assign_iterator_target(self, target, item_type, value: str) -> None:
        if isinstance(target, (ast.Name, ast.arg)):
            self.require_target_layout(target, item_type)
            kind = self.value_type(item_type)
            self.value_semantics[kind, value] = item_type
            if isinstance(target, ast.arg):
                # Loop bindings describe the yielded item, not the eventual
                # local slot. Boxing into a reused object slot needs its layout.
                self.value_representations[kind, value] = analyzed_representation(target)
            self.store(target, kind, value)
            return
        item_types = tuple(item_type.generic_types.values())
        tuple_type = self.tuple_type(item_type)
        length = self.emit_value(f"load i64, ptr {value}")
        self.guard_exception(target, self.emit_value(f"icmp eq i64 {length}, {len(item_types)}"),
                             "ValueError", "tuple unpacking length mismatch")
        value = collection_ops.storage(self, value, 2)
        for index, (element, element_type) in enumerate(
            zip(target.elts, item_types, strict=True)
        ):
            field = self.new_temporary()
            loaded = self.new_temporary()
            llvm_type = self.value_type(element_type)
            self.emit_line(
                f"{field} = getelementptr %{tuple_type}, ptr {value}, i32 0, i32 {index}"
            )
            self.emit_line(f"{loaded} = load {llvm_type}, ptr {field}")
            self.assign_iterator_target(element, element_type, loaded)

    def arena_allocate(self, type_name: str) -> str:
        size = self.llvm_size(f"%{type_name}")
        arena = self.load_local("__arena")
        result = self.new_temporary()
        self.emit_line(
            f"{result} = call ptr @pyjs.arena.try.alloc(ptr {arena}, i64 {size}, i64 8)"
        )
        self.require_allocation(result)
        return result

    @staticmethod
    def require_concrete_allocation(node: ObjectNew | CollectionNew) -> None:
        value_type = node.value_type
        if not isinstance(value_type, Class):
            raise LLVMUnsupported(
                f"LLVM {value_type.name} allocation requires a concrete type", node,
            )

    def prepare_allocation(self, node: ObjectNew | CollectionNew) -> bool:
        self.require_concrete_allocation(node)
        value_type = node.value_type
        lifetime = node.lifetime
        if lifetime is None:
            raise LLVMUnsupported("LLVM allocation has no lifetime summary", node)
        self.emit_line(
            f"; pyjs allocation {lifetime.site}: {lifetime.boundary.value}"
        )
        if not self.module.uses_gc:
            return False
        if lifetime.boundary in {LifetimeBoundary.CALLER, LifetimeBoundary.EXTERNAL}:
            return True
        # Dynamic strings have no allocation node in the lifetime summary.
        # Even a local holder must be traced if it can contain heap pointers.
        # Non-generic native holders such as Document have no member schema.
        members = (
            (field.value_type for field in self.module.layout_fields[value_type])
            if value_type in self.module.classes
            else (value_type.generic_types or {}).values()
        )
        return any(self.value_type(member) in {"ptr", tagged.STORAGE} for member in members)

    def arena_string(self, arena: str, value: str) -> str:
        if not self.module.uses_gc or value.startswith("@"):
            return value
        # The native DOM is request-arena owned and not traced. Copy text at
        # this boundary so it cannot hide the only reference to a GC string.
        return self.allocated_value(
            f"call ptr @pyjs.string.concat(ptr {arena}, "
            f"ptr @{self.string_constant('')}, ptr {value})"
        )

    def llvm_size(self, llvm_type: str) -> str:
        pointer = self.new_temporary()
        size = self.new_temporary()
        self.emit_line(f"{pointer} = getelementptr {llvm_type}, ptr null, i32 1")
        self.emit_line(f"{size} = ptrtoint ptr {pointer} to i64")
        return size

    def joined_string(self, node: ast.JoinedStr) -> tuple[str, str]:
        parts = []
        slots, frame = calls.value_slots(self, ["ptr"] * len(node.values))
        for value, slot in zip(node.values, slots, strict=True):
            if isinstance(value, ast.Constant):
                parts.append(f"@{self.string_constant(value.value)}")
                continue
            if (not isinstance(value, ast.FormattedValue) or value.format_spec is not None
                    or value.conversion != -1):
                raise LLVMUnsupported("LLVM f-string fields require analyzed format() calls", value)
            value_type, rendered = self.expression(value.value)
            semantic_type = analyzed_value_type(value.value).generic_name
            if value_type != "ptr" or semantic_type != "str":
                raise LLVMUnsupported("LLVM analyzed f-string fields must return str", value)
            parts.append(rendered)
            # A later formatting callback may collect; retain earlier
            # formatted parts until the final concatenation is complete.
            self.emit_line(f"store ptr {parts[-1]}, ptr {slot}")
        # Join once rather than allocating each growing prefix. All parts
        # remain rooted across both later callbacks and the final allocation.
        fragments = self.emit_value(f"alloca [{len(parts)} x ptr]")
        for index, part in enumerate(parts):
            address = self.emit_value(f"getelementptr ptr, ptr {fragments}, i64 {index}")
            self.emit_line(f"store ptr {part}, ptr {address}")
        result = self.allocated_value(f"call ptr @pyjs.format.join({collection_ops.owner(self)}, ptr {fragments}, i64 {len(parts)})")
        calls.pop_roots(self, frame)
        return "ptr", result

    def string_edit_call(self, operation, receiver, arguments, node, *, binary):
        # The caller has normalized Literal/union/enum receivers. The source
        # AST still describes that richer type, not the selected text layout.
        binary_flag = f"i1 {str(binary).lower()}"
        whitespace_characters = runtime_text.BYTE_WHITESPACE if binary else runtime_text.WHITESPACE

        def integer(index, default):
            if index >= len(arguments) or arguments[index][0] == "void":
                return str(default)
            return self.index_integer(*arguments[index], node, "LLVM text bounds require int or literal None")

        def present(index):
            return "true" if index < len(arguments) and arguments[index][0] != "void" else "false"

        if operation in {"startswith", "endswith", "find", "rfind", "count", "index", "rindex"}:
            return text_search.emit(self, operation, receiver, arguments, node, binary=binary)

        parameters = [f"ptr {receiver}"]
        if operation == "__slice__":
            selected = [slices.bound(self, arguments[index] if index < len(arguments) else ("void", ""),
                                     node, 1 if index == 2 else 0) for index in range(3)]
            self.guard_exception(node, self.emit_value(f"icmp ne i64 {selected[2][0]}, 0"),
                                 "ValueError", "slice step cannot be zero")
            symbol = "slice"
            parameters += [f"i64 {selected[0][0]}", f"i1 {selected[0][1]}",
                           f"i64 {selected[1][0]}", f"i1 {selected[1][1]}", f"i64 {selected[2][0]}", binary_flag]
        elif operation == "__getitem__":
            length = self.emit_value(f"call i64 @pyjs.string.length(ptr {receiver})")
            self.guard_index(node, integer(0, 0), length, "string index out of range")
            symbol = "get.character"
            parameters.append(f"i64 {integer(0, 0)}")
        elif operation in {"__mul__", "__rmul__"}:
            symbol = "repeat"
            count = integer(0, 0)
            fits = self.emit_value(f"call i1 @pyjs.string.repeat.fits(ptr {receiver}, i64 {count}, {binary_flag})")
            self.guard_exception(node, fits, "OverflowError",
                                 "repeated bytes are too long" if binary else "repeated string is too long")
            parameters.append(f"i64 {count}")
        elif operation == "replace":
            symbol = "replace"
            parameters += [f"ptr {arguments[0][1]}", f"ptr {arguments[1][1]}", f"i64 {integer(2, -1)}", binary_flag]
        elif operation == "join":
            symbol = "join"
            parameters.append(f"ptr {arguments[0][1]}")
        elif operation in {"split", "rsplit"}:
            symbol = "split"
            whitespace = "true"
            separator = f"@{self.string_constant(whitespace_characters)}"
            if arguments and arguments[0][0] != "void":
                # Optional separators use null for None. Select a valid buffer
                # before reading its length; the kernel distinguishes whitespace
                # splitting from an explicitly supplied separator.
                value = arguments[0][1]
                whitespace = self.emit_value(f"icmp eq ptr {value}, null")
                separator = self.emit_value(f"select i1 {whitespace}, ptr {separator}, ptr {value}")
                length = self.emit_value(f"load i64, ptr {separator}")
                self.guard_exception(node, self.emit_value(f"icmp ne i64 {length}, 0"),
                                     "ValueError", "empty separator")
            parameters += [f"ptr {separator}", f"i64 {integer(1, -1)}",
                           f"i1 {str(operation == 'rsplit').lower()}", f"i1 {whitespace}", binary_flag]
        else:
            symbol = "trim"
            characters = f"@{self.string_constant(whitespace_characters)}"
            if arguments and arguments[0][0] == "ptr":
                value = arguments[0][1]
                absent = self.emit_value(f"icmp eq ptr {value}, null")
                characters = self.emit_value(f"select i1 {absent}, ptr {characters}, ptr {value}")
            parameters += [f"ptr {characters}", f"i1 {str(operation != 'rstrip').lower()}",
                           f"i1 {str(operation != 'lstrip').lower()}", binary_flag]
        return self.owned_text_call(f"pyjs.string.{symbol}", parameters)

    def owned_text_call(self, symbol, arguments):
        # A kernel may also allocate reference-bearing containers. The text
        # allocation leaf selects atomic storage only for its own payloads.
        parameters = [collection_ops.owner(self), *arguments]
        return "ptr", self.allocated_value(f"call ptr @{symbol}({', '.join(parameters)})")

    def bytes_call(self, operation, receiver, arguments, node):
        if operation == "__len__":
            return "i64", self.emit_value(f"load i64, ptr {receiver}")
        if operation == "__contains__":
            return text_search.contains(self, receiver, arguments[0], node, binary=True)
        kind, value = tagged.numeric(self, node.args[0], *arguments[0])
        if kind == "i1":
            value = self.emit_value(f"zext i1 {value} to i64")
            kind = "i64"
        value = self.index_integer(kind, value, node.args[0], "LLVM bytes index requires an integer")
        length = self.emit_value(f"load i64, ptr {receiver}")
        self.guard_index(node, value, length, "index out of range")
        return "i64", self.emit_value(f"call i64 @pyjs.text.get_byte(ptr {receiver}, i64 {value})")

    def codec_call(self, operation, receiver, node):
        values = dict(zip(("encoding", "errors"), node.args, strict=False))
        for keyword in node.keywords:
            if keyword.arg in values or keyword.arg not in {"encoding", "errors"}:
                raise LLVMUnsupported("LLVM codec arguments must specify encoding/errors once", node)
            values[keyword.arg] = keyword.value
        allowed = {"encoding": {"utf-8", "utf8", "utf_8"}, "errors": {"strict"}}
        for name, value in values.items():
            if (not isinstance(value, ast.Constant) or not isinstance(value.value, str)
                    or (value.value.lower() if name == "encoding" else value.value) not in allowed[name]):
                raise LLVMUnsupported("LLVM codecs require literal UTF-8 encoding and strict errors", node)
        if operation == "decode":
            valid = self.emit_value(f"call i1 @pyjs.bytes.valid.utf8(ptr {receiver})")
            self.guard_exception(node, valid, "UnicodeDecodeError", "invalid UTF-8 data")
        length = self.emit_value(f"load i64, ptr {receiver}")
        return self.owned_text_call("pyjs.string.copy.span", [f"ptr {receiver}", "i64 0", f"i64 {length}"])

    def text_extra_call(self, operation, receiver, arguments, node, *, binary):
        parameters = [f"ptr {receiver}"]
        if arguments and operation in {"ljust", "rjust", "center", "zfill", "expandtabs"}:
            width = self.index_integer(*arguments[0], node.args[0], "LLVM text width requires an integer")
            arguments = [("i64", width), *arguments[1:]]
        if operation in {"partition", "rpartition"}:
            symbol = "partition"
            length = self.emit_value(f"load i64, ptr {arguments[0][1]}")
            self.guard_exception(node, self.emit_value(f"icmp ne i64 {length}, 0"), "ValueError", "empty separator")
            parameters += [f"ptr {arguments[0][1]}", f"i1 {str(operation == 'rpartition').lower()}"]
        elif operation in {"removeprefix", "removesuffix"}:
            symbol = "remove_affix"
            parameters += [f"ptr {arguments[0][1]}", f"i1 {str(operation == 'removesuffix').lower()}"]
        elif operation == "splitlines":
            symbol = "splitlines"
            keepends = self.truth_value(node.args[0], *arguments[0]) if arguments else "false"
            parameters += [f"i1 {keepends}", f"i1 {str(binary).lower()}"]
        elif operation in {"ljust", "rjust", "center"}:
            symbol = "pad"
            fillchar = arguments[1][1] if len(arguments) > 1 else f"@{self.string_constant(' ')}"
            length = self.emit_value(f"call i64 @pyjs.string.length(ptr {fillchar})")
            self.guard_exception(node, self.emit_value(f"icmp eq i64 {length}, 1"),
                                 "TypeError", "The fill character must be exactly one character long")
            parameters += [f"i64 {arguments[0][1]}", f"ptr {fillchar}", f"i64 {('ljust', 'rjust', 'center').index(operation)}"]
        elif operation in {"zfill", "expandtabs"}:
            symbol = operation
            parameters += [f"i64 {arguments[0][1] if arguments else '8'}"]
        elif operation == "hex":
            symbol = "hex_bytes"
        else:
            raise LLVMUnsupported(f"unsupported LLVM text operation {operation}", node)
        return self.owned_text_call(f"pyjs.text.{symbol}", parameters)

    def string_concat(self, left: str, right: str) -> str:
        arena = self.load_local("__arena")
        result = self.new_temporary()
        if self.module.uses_gc:
            self.emit_line(
                f"{result} = call ptr @pyjs.string.concat.owned("
                f"ptr {arena}, ptr @pyjs.gc.alloc.atomic.adapter, "
                f"ptr {self.load_local('__heap')}, ptr {left}, ptr {right})"
            )
            self.require_allocation(result)
        else:
            self.emit_line(
                f"{result} = call ptr @pyjs.string.concat(ptr {arena}, "
                f"ptr {left}, ptr {right})"
            )
            self.require_allocation(result)
        return result

    def string_from_int(self, value: str) -> str:
        arena = self.load_local("__arena")
        result = self.new_temporary()
        if self.module.uses_gc:
            self.emit_line(
                f"{result} = call ptr @pyjs.string.from.i64.owned("
                f"ptr {arena}, ptr @pyjs.gc.alloc.atomic.adapter, "
                f"ptr {self.load_local('__heap')}, i64 {value})"
            )
            self.require_allocation(result)
        else:
            self.emit_line(
                f"{result} = call ptr @pyjs.string.from.i64("
                f"ptr {arena}, i64 {value})"
            )
            self.require_allocation(result)
        return result

    def string_from_float(self, value: str) -> str:
        allocator = "@pyjs.gc.alloc.atomic.adapter" if self.module.uses_gc else "null"
        context = self.load_local("__heap") if self.module.uses_gc else "null"
        return self.allocated_value(
            f"call ptr @pyjs.string.from.f64(ptr {self.load_local('__arena')}, "
            f"ptr {allocator}, ptr {context}, double {value})"
        )

    def string_from_bool(self, value: str) -> str:
        result = self.new_temporary()
        self.emit_line(
            f"{result} = select i1 {value}, "
            f"ptr @{self.string_constant('True')}, "
            f"ptr @{self.string_constant('False')}"
        )
        return result

    def field_pointer(
        self,
        attribute,
        receiver=None,
    ) -> tuple[str, FieldIR, str]:
        # Retain the complete declaration: erased joins need nested container
        # representations as well as the scalar storage width.
        receiver_type = receiver[0] if receiver is not None else analyzed_value_type(attribute.value)
        layout = self.module.classes.get(receiver_type)
        if layout is None:
            raise LLVMUnsupported(
                f"LLVM cannot resolve field {attribute.attr} on {receiver_type.name}",
                attribute,
            )
        try:
            field_index, field = next(
                (index, field)
                for index, field in enumerate(self.module.layout_fields[receiver_type])
                if field.name == attribute.attr
            )
        except StopIteration:
            raise LLVMUnsupported(
                f"LLVM class {receiver_type.name} has no field {attribute.attr}",
                attribute,
            ) from None
        if receiver is None:
            pointer_type, value = self.expression(attribute.value)
            if pointer_type != "ptr":
                raise LLVMUnsupported("LLVM field receiver is not an object", attribute)
        else:
            value = receiver[1]
        pointer = self.new_temporary()
        index = field_index + (1 if receiver_type in self.module.vtable_roots else 0)
        if receiver_type in self.module.custom_element_types:
            index += 2
        if self.module.uses_dom_references and self.is_proxy_element_type(receiver_type):
            index += 1
        self.emit_line(
            f"{pointer} = getelementptr %{self.class_name(receiver_type)}, "
            f"ptr {value}, i32 0, i32 {index}"
        )
        return (
            self.storage_type(field.value_type, field.numeric_format),
            field,
            pointer,
        )

    def expression_type(self, node: ast.expr) -> str:
        if tagged.narrowed_integer(node, self.slot_types, self.module.functions, scope=self.current_function.scope):
            return tagged.STORAGE
        semantic = self.runtime_value_type(node)
        return "ptr" if semantic is None else self.value_type(semantic)

    def runtime_value_type(self, node):
        # Querying a bare class value can lazily request an unanalyzed type[T]
        # after reachability has finished. Reject that unsupported storage
        # before the query; exception class tokens have an existing native ABI.
        value = analyzed_value_object(node)
        if (isinstance(node, (ast.Name, ast.Attribute)) and isinstance(value, (Class, GenericClass))
                and not self.is_exception_type(value)):
            raise LLVMUnsupported("LLVM runtime values do not support class objects", node)
        if isinstance(value, Function):
            return callable_value_type(node)
        return object_values.instance_type(node)

    @staticmethod
    def _scalar_type(value_type) -> str | None:
        name = enum_ops.storage_name(value_type)
        if name == "bool":
            return "i1"
        if name == "int":
            return "i64"
        if name == "float":
            return "double"
        return None

    @staticmethod
    def numeric_storage_type(value: NumericFormat | None) -> str | None:
        if value is None:
            return None
        if value.kind == "integer":
            return f"i{value.bits}"
        return "float" if value.bits == 32 else "double"

    def storage_type(self, value_type, storage_format: NumericFormat | None) -> str:
        if nullable.member(value_type):
            return self.value_type(value_type)
        return self.numeric_storage_type(storage_format) or self.value_type(value_type)

    def result_storage_type(self, value_type, storage_format: NumericFormat | None) -> str:
        # None is a storable null pointer, but a function returning only None
        # has no return payload. Keep that ABI distinct from fields/parameters.
        if getattr(value_type, "generic_name", None) == "NoneType":
            return "void"
        return self.storage_type(value_type, storage_format)

    def annotation_storage_type(
        self,
        annotation: ast.expr | None,
        storage_format: NumericFormat | None,
    ) -> str:
        return self.numeric_storage_type(storage_format) or self.annotation(annotation)

    @staticmethod
    def semantic_storage_type(
        storage_type: str,
        storage_format: NumericFormat | None,
    ) -> str:
        if storage_format is None or nullable.payload_kind(storage_type):
            return storage_type
        return "i64" if storage_format.kind == "integer" else "double"

    def narrow_numeric(
        self,
        value_type: str,
        value: str,
        storage_type: str,
        node: ast.AST | None,
    ) -> tuple[str, str]:
        if value_type == storage_type:
            return storage_type, value
        operation = None
        if value_type == "i64" and storage_type in {"i8", "i16", "i32"}:
            operation = "trunc"
        elif value_type == "double" and storage_type == "float":
            operation = "fptrunc"
        if operation is None:
            raise LLVMUnsupported(
                f"cannot lower {value_type} to {storage_type} storage",
                node,
            )
        result = self.new_temporary()
        self.emit_line(f"{result} = {operation} {value_type} {value} to {storage_type}")
        return storage_type, result

    def normalize_integer_result(
        self,
        value: str,
        node: ast.expr,
    ) -> tuple[str, str]:
        storage_format = analyzed_numeric_format(node)
        if storage_format is None or storage_format.kind != "integer":
            return "i64", value
        storage_type = self.numeric_storage_type(storage_format)
        assert storage_type is not None
        narrowed_type, narrowed = self.narrow_numeric(
            "i64",
            value,
            storage_type,
            node,
        )
        return self.widen_numeric(narrowed_type, narrowed, storage_format)

    def wgsl_integer_division(
        self,
        left: str,
        right: str,
        storage_format: NumericFormat,
        *,
        modulo: bool,
    ) -> str:
        zero = self.new_temporary()
        self.emit_line(f"{zero} = icmp eq i64 {right}, 0")
        exceptional = zero
        if storage_format.signed:
            minimum, _maximum = storage_format.integer_bounds
            minimum_left = self.new_temporary()
            negative_one = self.new_temporary()
            overflow = self.new_temporary()
            exceptional = self.new_temporary()
            self.emit_line(f"{minimum_left} = icmp eq i64 {left}, {minimum}")
            self.emit_line(f"{negative_one} = icmp eq i64 {right}, -1")
            self.emit_line(f"{overflow} = and i1 {minimum_left}, {negative_one}")
            self.emit_line(f"{exceptional} = or i1 {zero}, {overflow}")
        safe_right = self.new_temporary()
        self.emit_line(f"{safe_right} = select i1 {exceptional}, i64 1, i64 {right}")
        operation = (
            "srem"
            if modulo and storage_format.signed
            else "urem"
            if modulo
            else "sdiv"
            if storage_format.signed
            else "udiv"
        )
        calculated = self.new_temporary()
        self.emit_line(f"{calculated} = {operation} i64 {left}, {safe_right}")
        result = self.new_temporary()
        fallback = "0" if modulo else left
        self.emit_line(
            f"{result} = select i1 {exceptional}, i64 {fallback}, i64 {calculated}"
        )
        return result

    def integer_shift(
        self,
        value: str,
        count: str,
        *,
        left: bool,
        signed: bool,
        bits: int,
        node: ast.AST,
    ) -> str:
        negative = self.new_temporary()
        self.emit_line(f"{negative} = icmp slt i64 {count}, 0")
        self.guard_exception(node, self.emit_value(f"xor i1 {negative}, true"),
                             "ValueError", "negative shift count")
        valid = self.new_temporary()
        self.emit_line(f"{valid} = icmp ult i64 {count}, {bits}")
        safe_count = self.new_temporary()
        self.emit_line(f"{safe_count} = select i1 {valid}, i64 {count}, i64 0")
        shifted = self.new_temporary()
        operation = "shl" if left else "ashr" if signed else "lshr"
        self.emit_line(f"{shifted} = {operation} i64 {value}, {safe_count}")
        fallback = "0"
        if not left and signed:
            value_negative = self.new_temporary()
            self.emit_line(f"{value_negative} = icmp slt i64 {value}, 0")
            fallback_value = self.new_temporary()
            self.emit_line(
                f"{fallback_value} = select i1 {value_negative}, i64 -1, i64 0"
            )
            fallback = fallback_value
        result = self.new_temporary()
        self.emit_line(f"{result} = select i1 {valid}, i64 {shifted}, i64 {fallback}")
        return result

    def normalize_float_result(
        self,
        value: str,
        node: ast.expr,
    ) -> tuple[str, str]:
        storage_format = analyzed_numeric_format(node)
        if (
            storage_format is None
            or storage_format.kind != "float"
            or storage_format.bits == 64
        ):
            return "double", value
        narrowed_type, narrowed = self.narrow_numeric(
            "double",
            value,
            "float",
            node,
        )
        return self.widen_numeric(narrowed_type, narrowed, storage_format)

    def widen_numeric(
        self,
        storage_type: str,
        value: str,
        storage_format: NumericFormat | None,
    ) -> tuple[str, str]:
        semantic_type = self.semantic_storage_type(storage_type, storage_format)
        if storage_type == semantic_type:
            return semantic_type, value
        if storage_format is None:
            raise LLVMUnsupported(f"cannot interpret {storage_type} as {semantic_type}")
        if storage_format.kind == "integer":
            operation = "sext" if storage_format.signed else "zext"
        else:
            operation = "fpext"
        result = self.new_temporary()
        self.emit_line(
            f"{result} = {operation} {storage_type} {value} to {semantic_type}"
        )
        return semantic_type, result

    def value_type(self, value_type, node=None) -> str:
        value_type = tagged.runtime_type(value_type)
        if nullable.is_object(value_type):
            return "ptr"
        if isinstance(value_type, CallableClass):
            return "ptr"
        if self.is_exception_type(value_type):
            return "ptr"
        if isinstance(value_type, UnionType):
            if member := nullable.member(value_type):
                kind = self.value_type(member, node)
                if kind in nullable.SCALARS:
                    return nullable.pair(kind)
                if kind == "ptr":
                    return kind
            members = [member for member in value_type.types if member.generic_name != "NoneType"]
            if len(members) < len(value_type.types) and all(self.is_exception_type(member) or self.is_exception_token_type(member)
                                                          or nullable.is_object(member) for member in members):
                return "ptr"
            tagged.validate(self, value_type, node or getattr(self.current_function, "original_node", None))
            return tagged.STORAGE
        if nullable.is_object(value_type) or self.is_exception_token_type(value_type):
            return "ptr"
        if value_type.generic_name == "NoneType":
            return "ptr"
        if collection_ops.builtin_name(value_type) == "NotImplementedType":
            return "ptr"
        scalar = self._scalar_type(value_type)
        if scalar is not None:
            return scalar
        if value_type in self.module.classes:
            return "ptr"
        decoration = get_native_decoration(getattr(value_type, "py_obj", None))
        if decoration is not None and decoration.operation == "memory.pointer":
            return "ptr"
        if decoration is not None and decoration.operation == "memory.wide.integer":
            return "i128"
        if value_type.container.name == "pyjs.native":
            return "ptr"
        if self.is_web_element_type(value_type) or getattr(value_type, "py_obj", None) is native_builtins._WebTokenList:
            return "ptr"
        if dom_types.is_browser_declaration(value_type):
            # SSR components may declare browser collaborators but leave them
            # absent. Storage does not grant a layout, constructor or host ABI.
            return "ptr"
        if value_type.generic_name in {"dict", "list", "set", "frozenset", "tuple", "range", "slice", "Iterable", "Iterator", "Generator", *collection_ops.VIEWS}:
            return "ptr"
        if enum_ops.storage_name(value_type) in {"str", "bytes"}:
            return "ptr"
        raise LLVMUnsupported(f"unsupported LLVM value type {value_type.name}")

    is_opaque_web_element_type = staticmethod(dom_types.is_opaque_type)

    @staticmethod
    def is_web_element_type(value_type) -> bool:
        py_type = getattr(value_type, "py_obj", None)
        return FunctionEmitter.is_opaque_web_element_type(value_type) or (
            isinstance(py_type, type) and issubclass(py_type, WebElement)
        )

    @staticmethod
    def is_proxy_element_type(value_type) -> bool:
        python_type = getattr(value_type, "py_obj", None)
        return isinstance(python_type, type) and issubclass(python_type, ProxyElement)

    @staticmethod
    def is_custom_element_type(value_type) -> bool:
        py_type = getattr(value_type, "py_obj", None)
        return (
            isinstance(py_type, type)
            and py_type is not CustomElement
            and issubclass(py_type, CustomElement)
        )

    def abi_type(
        self,
        value_type,
        ancestors=(),
        numeric_format: NumericFormat | None = None,
        *, representation=None, node=None, host_annotation=None,
    ) -> LLVMABIType:
        """Describe the existing LLVM layout without retaining analyzer objects."""
        from . import models
        if isinstance(value_type, UnionType):
            # Optional normalization can expose concrete recursive targets
            # without a named alias edge. Publish every union schema first.
            # Equal semantic types may still have different portable storage.
            # Analysis intentionally merges equivalent generic arguments. Host
            # Pydantic specializations can still differ (notably union order),
            # so their nominal schemas must not share this cache entry.
            key = value_type, numeric_format, representation, models.host_identity(host_annotation)
            if cached := self.module.abi_aliases.get(key):
                return cached
            index = len(self.module.abi_type_definitions)
            reference = LLVMABIType("alias", value_type.name, reference=index)
            self.module.abi_aliases[key] = reference
            self.module.abi_type_definitions.append(None)
            # Publish the edge first, but describe the alias itself, not
            # its target: a singleton named union still has tagged storage.
            self.module.abi_type_definitions[index] = self._abi_type(
                value_type, ancestors, numeric_format, representation=representation, node=node,
                host_annotation=host_annotation)
            return reference
        return self._abi_type(value_type, ancestors, numeric_format, representation=representation, node=node,
                              host_annotation=host_annotation)

    def _abi_type(self, value_type, ancestors, numeric_format=None, *, representation=None, node=None,
                  host_annotation=None):
        from . import models
        host_annotation = models.host_annotation(host_annotation)
        host_args = get_args(host_annotation)
        value_type = tagged.runtime_type(value_type)
        if getattr(value_type, "py_obj", None) is Any:
            # typing.Any has a Python class identity, but is not an empty
            # application record. Copying it as one silently discards its value.
            raise LLVMUnsupported("LLVM library inputs require a concrete type, not typing.Any", node)
        if enum_ops.scalar_name(value_type):
            raise LLVMUnsupported("LLVM library enum values require scalar inputs/outputs and explicit conversion", node)
        if member := nullable.member(value_type):
            selected = representation_for_member(value_type, representation, member)
            numeric = selected.numeric if selected is not None else None
            return LLVMABIType("optional", value_type.name,
                               item_type=self.abi_type(member, ancestors, numeric, representation=selected, node=node,
                                                       host_annotation=models.union_member(host_annotation,
                                                           getattr(builtins, collection_ops.builtin_name(member) or "", member.py_obj), member)))
        if isinstance(value_type, UnionType):
            tagged.validate(self, value_type, node)
            members = tagged.members(value_type)
            # A base arm admits reached subclasses with their own layouts/tags.
            # Discover from the compiled graph, never from arbitrary host input.
            members = tuple(dict.fromkeys((*members, *(
                child for member in members if member in self.module.classes
                for child in self.module.classes
                if collection_ops.is_layout_subclass(child, member)
            ))))
            schemas = tuple(
                self.abi_type(member, ancestors, node=node,
                              host_annotation=models.union_member(host_annotation,
                                  getattr(builtins, collection_ops.builtin_name(member) or "", member.py_obj), member),
                              representation=representation_for_member(value_type, representation, member))
                for member in members)
            host_classes = [member.host_model or member.host_class for member in schemas if member.kind == "object"]
            if len(set(host_classes)) != len(host_classes):
                # Ordinary Python generic instances do not encode their type
                # arguments in type(value). Never guess a storage specialization.
                names = sorted({cls.__qualname__ for cls in host_classes if host_classes.count(cls) > 1})
                raise LLVMUnsupported("LLVM library union inputs cannot distinguish specializations of the same host class: "
                                      + ", ".join(names), node)
            return LLVMABIType("union", value_type.name, members=schemas)
        name = collection_ops.builtin_name(value_type)
        if name in {"bool", "int", "float", "str", "bytes", "NoneType"}:
            if name in {"str", "bytes"}:
                self.module.uses_strings = True
            return LLVMABIType(name, name, numeric_format=numeric_format,
                               normalization_format=representation.numeric if representation else numeric_format)
        if name == "list":
            self.module.uses_collections = True
            return LLVMABIType(
                "list",
                value_type.name,
                item_type=self.abi_type(self.collection_item_type(value_type), ancestors,
                                        representation=representation.item_representation if representation else None, node=node,
                                        host_annotation=host_args[0] if host_args else None),
            )
        if name in {"dict", "set", "frozenset"}:
            self.module.uses_collections = self.module.uses_mappings = True
            key, member = self.dictionary_types(value_type) if name == "dict" else (self.set_item_type(value_type), None)
            from .mapping_keys import uses_callbacks
            scalar_union = bool(tagged.members(key)) and all(
                collection_ops.builtin_name(item) in {"bool", "int", "float", "str", "bytes", "NoneType"}
                for item in tagged.members(key))
            if uses_callbacks(key) and not scalar_union:
                raise LLVMUnsupported("LLVM reference-key inputs require native hash initialization", node)
            if not scalar_union:
                self.dictionary_key_kind(key)
            representations = representation.arguments if representation else ()
            key_abi = self.abi_type(key, ancestors, representation=representations[0] if representations else None, node=node,
                                    host_annotation=host_args[0] if host_args else None)
            return LLVMABIType(name, value_type.name, key_type=key_abi if member else None,
                               item_type=self.abi_type(member, ancestors, representation=representations[1] if representations else None,
                                                       node=node, host_annotation=host_args[1] if host_args else None) if member else key_abi)
        if name == "tuple":
            self.module.uses_collections = True
            if value_type.tuple_variadic:
                return LLVMABIType("tuple", value_type.name,
                                   item_type=self.abi_type(collection_ops.item_type(value_type), ancestors,
                                                          representation=representation.item_representation if representation else None, node=node,
                                                          host_annotation=host_args[0] if host_args else None))
            self.tuple_type(value_type, node)
            return LLVMABIType(
                "tuple",
                value_type.name,
                fields=tuple(
                    LLVMABIField(str(index), self.abi_type(item, ancestors,
                                 representation=representation.arguments[index] if representation else None, node=node,
                                 host_annotation=host_args[index] if host_args else None))
                    for index, item in enumerate(value_type.generic_types.values())
                ),
            )
        if value_type in self.module.classes:
            if value_type in self.module.custom_element_types:
                raise LLVMUnsupported("LLVM custom elements must be constructed in compiled code, not marshalled as input records", node)
            if self.is_proxy_element_type(value_type):
                raise LLVMUnsupported("LLVM proxy wrappers must be constructed in compiled code, not marshalled as input records", node)
            if value_type.py_obj.__module__ == "pyjs.native.pathlib":
                raise LLVMUnsupported("LLVM path inputs require text; construct a PurePosixPath in compiled code", node)
            if value_type in ancestors:
                raise LLVMUnsupported(
                    f"LLVM library inputs cannot contain recursive {value_type.name}", node,
                )
            identity = self.vtable_name(value_type) if value_type in self.module.vtable_roots else None
            self.module.has_identity_inputs |= identity is not None
            nested = (*ancestors, value_type)
            # These stdlib models use private slots behind read-only public
            # properties. Host date/UUID objects expose the public names; ABI
            # field names describe input access, not the compiled slot spelling.
            public_inputs = value_type.py_obj.__module__ in {"pyjs.native.datetime", "pyjs.native.uuid"}
            model = host_annotation if models.is_model(host_annotation) else value_type.py_obj
            if models.is_model(model) and model.__pydantic_generic_metadata__["parameters"]:
                # Inferred constructor fields lack the original host annotation.
                # Rebuilding it from canonicalized types could change nominal
                # specialization (for example Page[str | int] vs Page[int | str]).
                raise LLVMUnsupported(
                    "LLVM generic model inputs need a concrete host annotation; "
                    "declare the containing record field at class level", node)
            host_fields = (
                {name: field.rebuild_annotation() for name, field in model.model_fields.items()}
                if models.is_model(model) else get_type_hints(model, include_extras=True)
            )
            fields = []
            for field in self.module.layout_fields[value_type]:
                try:
                    field_type = self.abi_type(
                        field.value_type, nested, field.numeric_format,
                        representation=field.representation, node=node,
                        host_annotation=host_fields.get(field.name),
                    )
                except LLVMUnsupported as error:
                    error.add_note(f"while preparing library input field {value_type.name}.{field.name}")
                    raise
                fields.append(LLVMABIField(
                    field.name.removeprefix("_") if public_inputs else field.name, field_type))
            return LLVMABIType(
                "object",
                value_type.name,
                identity=identity,
                runtime_tag=tagged.tag(self, value_type),
                host_class=None if public_inputs else model,
                host_model=(value_type.py_obj.__name__ if public_inputs else
                            model if identity or models.is_model(model) else None),
                fields=tuple(fields),
            )
        raise LLVMUnsupported(
            f"LLVM library input type {value_type.name} is not supported"
        )

    def prepare_library_abi(self, entry_point: Function) -> None:
        if entry_point.vararg or entry_point.kwarg or entry_point.kwonlyargs:
            raise LLVMUnsupported(
                "LLVM library entry points cannot take variadic or keyword-only parameters",
                entry_point.original_node,
            )
        annotation = entry_point.return_type.annotation
        buffered = isinstance(annotation, ast.Name) and annotation.id == "str"
        direct_signature = (
            bool(entry_point.params)
            and isinstance(entry_point.params[-1].annotation, ast.Name)
            and entry_point.params[-1].annotation.id == "int"
            and isinstance(annotation, ast.Name)
            and annotation.id == "int"
            and analyzed_numeric_format(entry_point.params[-1]) is None
            and entry_point.return_numeric_format is None
        )
        if self.module.direct and not direct_signature:
            raise LLVMUnsupported(
                "a direct LLVM library entry point must accept a final int "
                "descriptor and return int"
            )
        if not self.module.direct and not buffered:
            raise LLVMUnsupported(
                "a buffered LLVM library entry point must return str; pass "
                "direct=True to compile a descriptor-writing entry point"
            )
        host_parameters = entry_point.params[:-1] if self.module.direct else entry_point.params
        host_annotations = get_type_hints(entry_point.py_func, include_extras=True)
        self.module.abi_parameters = tuple(
            LLVMABIParameter(
                parameter.arg,
                self.abi_type(
                    parameter.annotation.obj,
                    numeric_format=analyzed_numeric_format(parameter),
                    representation=analyzed_representation(parameter),
                    node=entry_point.original_node,
                    host_annotation=host_annotations.get(parameter.arg),
                ),
            )
            for parameter in host_parameters
        )
        inputs.validate_record_cycles(self.module.abi_parameters, self.module.abi_type_definitions,
                                      entry_point.original_node)
        self.module.library_is_direct = self.module.direct
        self.module.library_host_parameters = host_parameters

    def collection_item_type(self, value_type):
        if not isinstance(value_type, Class):
            raise LLVMUnsupported(
                f"LLVM list {value_type.name} has no concrete item type"
            )
        if value_type.generic_name != "list":
            raise LLVMUnsupported(f"LLVM expected list, received {value_type.name}")
        try:
            return next(iter(value_type.generic_types.values()))
        except StopIteration:
            raise LLVMUnsupported(
                f"LLVM list {value_type.name} has no concrete item type"
            ) from None

    @staticmethod
    def dictionary_types(value_type):
        if not isinstance(value_type, Class):
            raise LLVMUnsupported(
                f"LLVM dict {value_type.name} has no concrete key/value types"
            )
        if value_type.generic_name != "dict":
            raise LLVMUnsupported(f"LLVM expected dict, received {value_type.name}")
        try:
            return value_type.generic_types["K"], value_type.generic_types["V"]
        except KeyError:
            values = tuple(value_type.generic_types.values())
            if len(values) == 2:
                return values
            raise LLVMUnsupported(
                f"LLVM dict {value_type.name} has no concrete key/value types"
            ) from None

    @staticmethod
    def set_item_type(value_type):
        if not isinstance(value_type, Class):
            raise LLVMUnsupported(
                f"LLVM set {value_type.name} has no concrete item type"
            )
        if value_type.generic_name not in {"set", "frozenset"}:
            raise LLVMUnsupported(f"LLVM expected set, received {value_type.name}")
        try:
            return next(iter(value_type.generic_types.values()))
        except StopIteration:
            raise LLVMUnsupported(
                f"LLVM set {value_type.name} has no concrete item type"
            ) from None

    @staticmethod
    def dictionary_key_kind(key_type) -> int:
        key_type = tagged.runtime_type(key_type)
        concrete = nullable.member(key_type)
        if isinstance(key_type, UnionType) and concrete is None:
            raise LLVMUnsupported("LLVM union dictionary keys require supported optional scalar types")
        if concrete is not None:
            concrete = tagged.runtime_type(concrete)
            name = collection_ops.builtin_name(concrete)
            if name in {"bool", "int", "float"}:
                return {"bool": 5, "int": 6, "float": 10}[name]
            if name in {"str", "bytes"}:
                key_type = concrete
        try:
            return {"bool": 1, "int": 2, "str": 3, "bytes": 4, "float": 9, "NoneType": 2}[collection_ops.builtin_name(key_type)]
        except KeyError:
            raise LLVMUnsupported(
                "LLVM dictionary keys currently require bool, int, float, str, bytes, None, or their optional forms"
            ) from None

    def dictionary_key_pointer(
        self,
        key_type,
        actual_type: str,
        value: str,
        node: ast.AST,
        *,
        for_lookup: bool = False,
        source_type=None,
    ) -> tuple[str, str]:
        # Searches (including removal) observe equality, not key identity.
        # Insertion keeps its stricter storage contract and the caller retains
        # the original argument for a possible KeyError.
        if nullable.is_object(source_type):
            # A box and a string both lower to ptr. Physical type agreement is
            # not permission to read a box as text, including on the error path.
            raise LLVMUnsupported("LLVM erased object keys require narrowing before lookup", node)
        if for_lookup and collection_ops.builtin_name(key_type) == "int":
            actual_type, value = "i64", self.index_integer(
                actual_type, value, node, "LLVM dictionary lookup requires an integer key")
        expected_type = self.value_type(key_type)
        if actual_type != expected_type and (nullable.member(key_type) or key_type.generic_name == "NoneType"):
            converted = nullable.convert(self, actual_type, value, expected_type, node)
            if converted is not None:
                actual_type, value = converted
        if actual_type != expected_type:
            raise LLVMUnsupported("LLVM dictionary key has incompatible type", node)
        pointer = self.emit_value(f"alloca {expected_type}")
        self.emit_line(f"store {expected_type} {value}, ptr {pointer}")
        return pointer, self.llvm_size(expected_type)

    def dictionary_lookup(
        self,
        receiver: str,
        dictionary_type,
        actual_key_type: str,
        key: str,
        node: ast.AST,
        *,
        source_type,
    ) -> tuple[str, str]:
        # The diagnostic node may be an enclosing call (e.g. **kwargs), not
        # the key expression. Callers supply the semantic type of the actual
        # key, including keys loaded directly from checked collection storage.
        self.module.uses_mappings = True
        if dictionary_type.generic_name in {"set", "frozenset"}:
            key_type = next(iter(dictionary_type.generic_types.values()))
            llvm_value_type = "i1"
        elif dictionary_type.generic_name == "ItemsView":
            key_type, value_type = dictionary_type.generic_types.values()
            llvm_value_type = self.value_type(value_type)
        else:
            key_type, value_type = self.dictionary_types(dictionary_type)
            llvm_value_type = self.value_type(value_type)
        from . import mapping_keys
        index = self.dictionary_index(receiver, key_type, actual_key_type, key, node, source_type=source_type)
        present = self.emit_value(f"icmp sge i64 {index}, 0")
        # value_slot uses a non-inbounds GEP. A missing key may compute an
        # unused address, but only a valid, correctly-strided slot is published.
        slot = mapping_keys.value_slot(self, receiver, index, self.llvm_size(llvm_value_type))
        return self.emit_value(f"select i1 {present}, ptr {slot}, ptr null"), llvm_value_type

    def dictionary_index(self, receiver, key_type, actual_key_type, key, node, *, source_type):
        """Find a key without assuming that its caller knows the value layout."""
        from . import mapping_keys
        self.module.uses_mappings = True
        if mapping_keys.uses_callbacks(key_type):
            tuple_query = mapping_keys.is_tuple_query(key_type, source_type)
            if not (same_analyzer_type(source_type, key_type)
                    or tuple_query
                    or tagged.members(key_type) and is_return_type_compatible(key_type, source_type)
                    or source_type in self.module.classes and key_type in self.module.classes
                    and is_subclass(source_type, key_type)):
                raise LLVMUnsupported("LLVM reference mapping lookup requires its declared key type", node)
            self.value_semantics[(actual_key_type, key)] = source_type
            return mapping_keys.find(self, receiver, key_type, actual_key_type, key,
                                     node, query_type=source_type if tuple_query else None)[0]
        key_pointer, key_size = self.dictionary_key_pointer(
            key_type,
            actual_key_type,
            key,
            node,
            for_lookup=True,
            source_type=source_type,
        )
        return self.emit_value(f"call i64 @pyjs.dict.find(ptr {receiver}, ptr {key_pointer}, "
                               f"i64 {key_size}, i8 {self.dictionary_key_kind(key_type)})")

    def dictionary_set_slot(
        self,
        receiver: str,
        key_type,
        actual_key_type: str,
        key: str,
        value_size: str,
        node: ast.AST,
    ) -> str:
        # Keys supplied here have already crossed their semantic storage
        # boundary: converted literals/items, or checked mutation arguments.
        # Do not infer nominal types from pooled LLVM scalar values here.
        from . import mapping_keys
        if mapping_keys.uses_callbacks(key_type):
            return mapping_keys.lookup(self, receiver, key_type, actual_key_type, key, value_size, node, insert=True)
        key_pointer, key_size = self.dictionary_key_pointer(
            key_type,
            actual_key_type,
            key,
            node,
        )
        arena = self.load_local("__arena")
        result = self.new_temporary()
        self.emit_line(
            f"{result} = call ptr @pyjs.dict.set.slot(ptr {arena}, "
            f"ptr {receiver}, ptr {key_pointer}, i64 {key_size}, "
            f"i64 {value_size}, i8 {self.dictionary_key_kind(key_type)})"
        )
        self.require_allocation(result)
        return result

    def sequence_call(self, operation, sequence_type, receiver, arguments, node):
        item_type = collection_ops.item_type(sequence_type)
        representation = representation_for_member(analyzed_value_type(node.func.value),
                                                   analyzed_representation(node.func.value), sequence_type)
        item_representation = representation.item_representation if representation else None
        name = sequence_type.generic_name
        kind = self.value_type(item_type)
        size = self.llvm_size(kind)
        arena = self.load_local("__arena")
        # List buffers and coallocated tuple payloads share the item contract;
        # their runtime factories select the appropriate header descriptor.
        allocator = gc_layouts.item_allocator(kind)
        allocator = allocator if self.module.uses_gc else "null"
        context = self.load_local("__heap") if self.module.uses_gc else "null"
        owner = f"ptr {arena}, ptr {allocator}, ptr {context}"

        def integer(index, default):
            if index >= len(arguments) or arguments[index][0] == "void":
                return str(default)
            if operation in {"__slice__", "__setslice__", "__delslice__"}:
                return slices.bound(self, arguments[index], node, default)[0]
            return self.index_integer(*arguments[index], node, f"LLVM {name} bounds require int or literal None")

        def bounds(offset=0):
            parts = []
            for index in range(offset, offset + 3):
                value, present = slices.bound(self, arguments[index] if index < len(arguments) else ("void", ""), node)
                parts.extend((f"i64 {value}", f"i1 {present}"))
            return ", ".join(parts)

        def success(instruction, error="MemoryError", message="native collection allocation failed"):
            result = self.emit_value(instruction)
            self.guard_exception(node, result, error, message)

        if operation in {"__getitem__", "__setitem__", "pop", "__delitem__"}:
            length = self.emit_value(f"load i64, ptr {receiver}")
            message = f"{name} index out of range"
            if operation == "pop":
                self.guard_exception(node, self.emit_value(f"icmp ne i64 {length}, 0"),
                                     "IndexError", "pop from empty list")
                message = "pop index out of range"
            elif operation in {"__setitem__", "__delitem__"}:
                message = "list assignment index out of range"
            self.guard_index(node, integer(0, -1), length, message)
            slot = self.emit_value(f"call ptr @pyjs.list.get(ptr {receiver}, i64 {integer(0, -1)}, i64 {size})")
            if operation == "__setitem__":
                arguments[1] = self.coerce_value(*arguments[1], kind, node.args[1], semantic=item_type,
                                                representation=item_representation)
                self.emit_line(f"store {kind} {arguments[1][1]}, ptr {slot}")
                return "void", ""
            result = self.emit_value(f"load {kind}, ptr {slot}") if operation != "__delitem__" else ""
            if operation != "__getitem__":
                success(f"call i1 @pyjs.list.remove(ptr {receiver}, i64 {integer(0, -1)}, i64 {size})")
            return ("void", "") if operation == "__delitem__" else (kind, result)
        if operation == "insert":
            arguments[1] = self.coerce_value(*arguments[1], kind, node.args[1], semantic=item_type,
                                            representation=item_representation)
            value = self.emit_value(f"alloca {kind}")
            self.emit_line(f"store {kind} {arguments[1][1]}, ptr {value}")
            roots = calls.push_roots(self, [value]) if kind == "ptr" else None
            success(f"call i1 @pyjs.list.try.insert(ptr {arena}, ptr {receiver}, i64 {integer(0, 0)}, ptr {value}, i64 {size})")
            calls.pop_roots(self, roots)
            return "void", ""
        if operation in {"__contains__", "index", "count", "remove"}:
            source_type = object_values.instance_type(node.args[0])
            if source_type is None:
                # A supported class token cannot equal a primitive item. Do
                # not hand its opaque pointer to a string-layout comparator.
                if operation == "__contains__" and collection_ops.builtin_name(item_type) in {"int", "bool", "float", "str", "bytes"}:
                    return "i1", "false"
                raise LLVMUnsupported("LLVM class-token search requires primitive items", node)
            if (collection_ops.builtin_name(item_type) not in {"int", "bool", "str"}
                    or arguments[0][0] == tagged.STORAGE
                    or nullable.is_object(source_type)):
                return comparisons.search(self, operation, sequence_type, receiver, arguments, node)
            if arguments[0][0] != kind:
                raise LLVMUnsupported("LLVM list search requires the same item representation", node)
            item = self.emit_value(f"alloca {kind}")
            self.emit_line(f"store {kind} {arguments[0][1]}, ptr {item}")
            key_kind = self.dictionary_key_kind(item_type)
            result = self.emit_value(
                f"call i64 @pyjs.list.search(ptr {receiver}, ptr {item}, i64 {size}, "
                f"i8 {key_kind}, i64 {integer(1, 0)}, i64 {integer(2, 9223372036854775807)}, "
                f"i1 {str(operation == 'count').lower()})"
            )
            if operation == "__contains__":
                return "i1", self.emit_value(f"icmp sge i64 {result}, 0")
            if operation != "count":
                success(f"icmp sge i64 {result}, 0", "ValueError", f"{name}.{operation}(x): x not in {name}")
            if operation == "remove":
                success(f"call i1 @pyjs.list.remove(ptr {receiver}, i64 {result}, i64 {size})")
                return "void", ""
            return "i64", result
        if operation in {"clear", "reverse"}:
            parameters = f"ptr {receiver}, " + ("i64 0, " if operation == "clear" else "") + f"i64 {size}"
            symbol = "truncate" if operation == "clear" else "reverse"
            self.emit_line(f"call void @pyjs.list.{symbol}({parameters})")
            return "void", ""
        if operation in {"copy", "__slice__", "__add__"}:
            if operation == "__add__":
                result_type = analyzed_value_type(node)
                other_type = analyzed_value_type(node.args[0])
                if sequence_type is not result_type or other_type is not result_type:
                    # Concatenation owns new slots: convert each copied item,
                    # never reinterpret an aliased source's payload stride.
                    result = collection_ops.materialize(self, result_type, sequence_type, receiver, node)
                    frame = calls.root_values(self, result)
                    expected = collection_ops.item_type(result_type)
                    collection_ops.loop(self, other_type, arguments[0][1],
                        lambda actual, value: collection_ops.append(self, result, expected, actual, value, node), node)
                    calls.pop_roots(self, frame)
                    return "ptr", result
                return "ptr", self.allocated_value(
                    f"call ptr @pyjs.list.concat({owner}, ptr {receiver}, ptr {arguments[0][1]}, i64 {size})")
            if operation == "__slice__":
                self.guard_exception(node, self.emit_value(f"icmp ne i64 {integer(2, 1)}, 0"),
                                     "ValueError", "slice step cannot be zero")
            selected = bounds() if operation == "__slice__" else "i64 0, i1 false, i64 0, i1 false, i64 0, i1 false"
            prefix = "tuple" if name == "tuple" else "list"
            result = self.allocated_value(f"call ptr @pyjs.{prefix}.slice({owner}, ptr {receiver}, i64 {size}, {selected})")
            return "ptr", result
        if operation in {"extend", "__iadd__"}:
            other = arguments[0][1]
            success(f"call i1 @pyjs.list.try.extend(ptr {arena}, ptr {receiver}, ptr {other}, i64 {size})")
            return ("ptr", receiver) if operation == "__iadd__" else ("void", "")
        if operation in {"__mul__", "__rmul__", "__imul__"}:
            if name == "tuple":
                return "ptr", self.allocated_value(f"call ptr @pyjs.tuple.repeat({owner}, ptr {receiver}, i64 {size}, i64 {integer(0, 0)})")
            inplace = str(operation == "__imul__").lower()
            return "ptr", self.allocated_value(f"call ptr @pyjs.list.repeat({owner}, ptr {receiver}, i64 {size}, i64 {integer(0, 0)}, i1 {inplace})")
        if operation == "__setslice__":
            other = arguments[0][1]
            step = integer(3, 1)
            self.guard_exception(node, self.emit_value(f"icmp ne i64 {step}, 0"),
                                 "ValueError", "slice step cannot be zero")
            source = node.args[1 if node.func.obj.name == "__setitem__" else 0]
            source_type = analyzed_value_type(source)
            if isinstance(source_type, UnionType):
                raise LLVMUnsupported("LLVM slice replacement requires a concrete iterable type; narrow unions before assignment", node)
            frame = None
            if source_type is not sequence_type:
                # Iteration can mutate the destination or fail. Finish staging
                # before reading its length, and publish only through the existing
                # checked alias-safe kernel. Exact lists retain their fast path.
                protocol = analyzed_iterable_protocol(source)
                other = collection_ops.materialize(self, sequence_type, source_type, other, node,
                    reiterate=True, item_representation=protocol.item_representation if protocol else None)
                frame = calls.root_values(self, other)
            length = self.emit_value(f"load i64, ptr {receiver}")
            count = self.emit_value(f"call i64 @pyjs.list.slice.length(i64 {length}, {bounds(1)})")
            replacement = self.emit_value(f"load i64, ptr {other}")
            contiguous = self.emit_value(f"icmp eq i64 {step}, 1")
            matches = self.emit_value(f"icmp eq i64 {count}, {replacement}")
            valid = self.emit_value(f"or i1 {contiguous}, {matches}")
            passed, failed = self.new_label("slice.shape.ok"), self.new_label("slice.shape.error")
            self.emit_line(f"br i1 {valid}, label %{passed}, label %{failed}")
            self.emit_line(f"{failed}:")
            message = self.string_concat(f"@{self.string_constant('attempt to assign sequence of size ')}", self.string_from_int(replacement))
            message = self.string_concat(message, f"@{self.string_constant(' to extended slice of size ')}")
            message = self.string_concat(message, self.string_from_int(count))
            self.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("ValueError"), message)
            self.branch_to_exception_target()
            self.emit_line(f"{passed}:")
            success(f"call i1 @pyjs.list.try.assign.slice(ptr {arena}, ptr {receiver}, ptr {other}, i64 {size}, {bounds(1)})")
            calls.pop_roots(self, frame)
            return "void", ""
        if operation == "__delslice__":
            self.guard_exception(node, self.emit_value(f"icmp ne i64 {integer(2, 1)}, 0"),
                                 "ValueError", "slice step cannot be zero")
            success(f"call i1 @pyjs.list.remove.slice(ptr {receiver}, i64 {size}, {bounds()})")
            return "void", ""
        if operation in {"__len__", "__bool__"}:
            length = self.emit_value(f"load i64, ptr {receiver}")
            return ("i64", length) if operation == "__len__" else ("i1", self.emit_value(f"icmp ne i64 {length}, 0"))
        raise LLVMUnsupported(f"LLVM list operation {operation} is not implemented", node)

    def dictionary_call(
        self,
        operation: str,
        dictionary_type,
        receiver: str,
        arguments: list[tuple[str, str]],
        node: ast.Call,
    ) -> tuple[str, str]:
        key_type, value_type = self.dictionary_types(dictionary_type)
        representation = representation_for_member(analyzed_value_type(node.func.value),
                                                   analyzed_representation(node.func.value), dictionary_type)
        value_representation = representation.arguments[1] if representation else None
        if operation in {"__setitem__", "setdefault"} and arguments:
            # Lookup observes equality, but possible insertion preserves the
            # original key. Check the source, not its pooled scalar payload.
            enum_ops.check_type_conversion(object_values.instance_type(node.args[0]), key_type, node.args[0])
        llvm_value_type = self.value_type(value_type)
        result_semantic = analyzed_value_type(node) if operation in {"get", "setdefault"} else None
        narrow_result = (operation in {"get", "setdefault"} and llvm_value_type == tagged.STORAGE
                         and tagged.members(value_type) == (result_semantic,))
        if (operation in {"get", "setdefault"} and llvm_value_type == tagged.STORAGE
                and self.value_type(result_semantic) != tagged.STORAGE and not narrow_result):
            # Lookup lowering below transports the stored value directly.
            # An optional/erased result needs a separate projection, not a
            # pointer reinterpretation of the tag word at a formatter call.
            raise LLVMUnsupported("LLVM dictionary lookup requires matching tagged result storage", node)
        if node.keywords:
            raise LLVMUnsupported("LLVM dictionary methods require positional arguments", node)
        if operation in {"clear", "copy", "update", "pop", "__delitem__"}:
            return self.mapping_mutation(operation, dictionary_type, key_type,
                                         llvm_value_type, receiver, arguments, node)
        if operation == "__bool__" and not arguments:
            length_pointer = self.new_temporary()
            length = self.new_temporary()
            result = self.new_temporary()
            self.emit_line(
                f"{length_pointer} = getelementptr %pyjs.dict, "
                f"ptr {receiver}, i32 0, i32 0"
            )
            self.emit_line(f"{length} = load i64, ptr {length_pointer}")
            self.emit_line(f"{result} = icmp ne i64 {length}, 0")
            return "i1", result
        if operation == "keys" and not arguments:
            return "ptr", receiver
        if operation in {"__getitem__", "__contains__", "get", "setdefault"} and arguments:
            source_type = object_values.instance_type(node.args[0])
            if source_type is None:
                # Current mapping keys are primitives; class-token equality
                # is impossible and their pointers are not string storage.
                if operation == "__contains__":
                    return "i1", "false"
                raise LLVMUnsupported("LLVM dictionary keys do not support class tokens", node)
            if (operation == "setdefault" and not nullable.member(value_type) and not nullable.is_object(value_type)
                    and getattr(value_type, "generic_name", None) != "NoneType"
                    and (len(arguments) == 1 or arguments[1][0] == "void")):
                # Reference payloads also use ptr, but that does not permit a
                # null insertion into a semantically non-optional dictionary.
                raise LLVMUnsupported(
                    "LLVM dict.setdefault without a concrete default requires optional dictionary values",
                    node,
                )
            from . import mapping_keys
            if operation == "setdefault" and mapping_keys.uses_callbacks(key_type):
                fallback = arguments[1] if len(arguments) == 2 else ("void", "")
                fallback = self.coerce_value(*fallback, llvm_value_type, node, semantic=value_type,
                                             representation=value_representation)
                slot = mapping_keys.lookup(self, receiver, key_type, *arguments[0], self.llvm_size(llvm_value_type),
                                           node, insert=True, default=fallback)
                result = self.emit_value(f"load {llvm_value_type}, ptr {slot}")
                return (tagged.narrow(self, result, result_semantic, node) if narrow_result
                        else (llvm_value_type, result))
            slot, result_type = self.dictionary_lookup(
                receiver,
                dictionary_type,
                arguments[0][0],
                arguments[0][1],
                node,
                source_type=source_type,
            )
            if operation == "__contains__" and len(arguments) == 1:
                result = self.new_temporary()
                self.emit_line(f"{result} = icmp ne ptr {slot}, null")
                return "i1", result
            if operation in {"get", "setdefault"} and (nullable.member(analyzed_value_type(node)) or nullable.is_object(value_type)
                                                       or operation == "get" and tagged.members(result_semantic)
                                                       and dom_ops.has_element(self, result_semantic)
                                                       or getattr(value_type, "generic_name", None) == "NoneType"):
                result_kind = self.value_type(analyzed_value_type(node))
                fallback = arguments[1] if len(arguments) == 2 else ("void", "")
                fallback = self.coerce_value(*fallback, result_kind, node, semantic=result_semantic)
                output = self.emit_value(f"alloca {result_kind}")
                self.emit_line(f"store {result_kind} {fallback[1]}, ptr {output}")
                yes, done = self.new_label("dict.present"), self.new_label("dict.optional.done")
                found = self.emit_value(f"icmp ne ptr {slot}, null")
                self.emit_line(f"br i1 {found}, label %{yes}, label %{done}")
                self.emit_line(f"{yes}:")
                value = self.emit_value(f"load {result_type}, ptr {slot}")
                self.value_semantics[result_type, value] = value_type
                _, value = self.coerce_value(result_type, value, result_kind, node, semantic=result_semantic)
                self.emit_line(f"store {result_kind} {value}, ptr {output}")
                self.emit_line(f"br label %{done}")
                self.emit_line(f"{done}:")
                value = self.emit_value(f"load {result_kind}, ptr {output}")
                if operation == "setdefault":
                    if result_kind != llvm_value_type:
                        raise LLVMUnsupported("LLVM setdefault requires matching optional value storage", node)
                    roots = calls.push_roots(self, [output]) if nullable.is_object(value_type) else None
                    destination = self.dictionary_set_slot(receiver, key_type, *arguments[0], self.llvm_size(result_kind), node)
                    self.emit_line(f"store {result_kind} {value}, ptr {destination}")
                    calls.pop_roots(self, roots)
                return result_kind, value
            if operation in {"get", "setdefault"} and len(arguments) == 2:
                try:
                    arguments[1] = self.coerce_value(*arguments[1], result_type, node.args[1], semantic=value_type,
                                                    representation=value_representation)
                except LLVMUnsupported as error:
                    raise LLVMUnsupported(f"LLVM dict.{operation} default has incompatible type", node.args[1]) from error
                fallback = self.new_temporary()
                self.emit_line(f"{fallback} = alloca {result_type}")
                self.emit_line(
                    f"store {result_type} {arguments[1][1]}, ptr {fallback}"
                )
                present = self.new_temporary()
                self.emit_line(f"{present} = icmp ne ptr {slot}, null")
                selected = self.new_temporary()
                self.emit_line(
                    f"{selected} = select i1 {present}, ptr {slot}, ptr {fallback}"
                )
                slot = selected
            elif operation == "__getitem__" and len(arguments) == 1:
                self.guard_key(node, self.emit_value(f"icmp ne ptr {slot}, null"), *arguments[0])
            elif operation == "get" and len(arguments) == 1:
                raise LLVMUnsupported(
                    "LLVM dict.get currently requires an explicit same-type default", node,
                )
            else:
                raise LLVMUnsupported(
                    f"LLVM dictionary operation {operation} has invalid arguments",
                    node,
                )
            result = self.new_temporary()
            self.emit_line(f"{result} = load {result_type}, ptr {slot}")
            if operation == "setdefault":
                roots = calls.root_values(self, result) if result_type == "ptr" else None
                destination = self.dictionary_set_slot(
                    receiver, key_type, *arguments[0], self.llvm_size(result_type), node,
                )
                self.emit_line(f"store {result_type} {result}, ptr {destination}")
                calls.pop_roots(self, roots)
            # Analysis may expose a singleton alias's identical concrete
            # target. Unpack its checked payload, never reinterpret its tag.
            return (tagged.narrow(self, result, result_semantic, node) if narrow_result
                    else (result_type, result))
        if operation == "__setitem__" and len(arguments) == 2:
            arguments[1] = self.coerce_value(*arguments[1], llvm_value_type, node, semantic=value_type,
                                            representation=value_representation)
            value_size = self.llvm_size(llvm_value_type)
            roots = calls.root_values(self, arguments[1][1]) if llvm_value_type == "ptr" else None
            slot = self.dictionary_set_slot(
                receiver,
                key_type,
                arguments[0][0],
                arguments[0][1],
                value_size,
                node,
            )
            self.emit_line(
                f"store {llvm_value_type} {arguments[1][1]}, ptr {slot}"
            )
            calls.pop_roots(self, roots)
            return "void", ""
        raise LLVMUnsupported(
            f"LLVM dictionary operation {operation} is not implemented",
            node,
        )

    def mapping_mutation(self, operation, mapping_type, key_type, value_kind,
                         receiver, arguments, node, *, source_type=None):
        key_size = self.llvm_size(self.value_type(key_type))
        value_size = self.llvm_size(value_kind)
        sizes = f"i64 {key_size}, i64 {value_size}"
        from . import mapping_keys
        custom = mapping_keys.uses_callbacks(key_type)
        key_kind = 0 if custom else self.dictionary_key_kind(key_type)
        arena = self.load_local("__arena")
        if operation == "clear":
            self.emit_line(f"call void @pyjs.dict.clear(ptr {receiver}, {sizes})")
            return "void", ""
        if operation == "copy":
            owner = collection_ops.mapping_owner(self, self.value_type(key_type), value_kind)
            return "ptr", self.allocated_value(
                f"call ptr @pyjs.dict.copy.typed({owner}, "
                f"ptr {receiver}, {sizes}, i8 {key_kind})"
            )
        if operation == "update":
            if (source_type or analyzed_value_type(node.args[0])) is not mapping_type:
                raise LLVMUnsupported("LLVM update requires the same concrete collection type", node)
            if custom:
                return mapping_keys.update(self, receiver, arguments[0][1], key_type, value_size, node)
            success = self.emit_value(f"call i1 @pyjs.dict.update(ptr {arena}, ptr {receiver}, ptr {arguments[0][1]}, {sizes}, i8 {key_kind})")
            self.guard_exception(node, success, "MemoryError", "native mapping allocation failed")
            return "void", ""
        if operation == "pop" and len(arguments) == 2:
            member = self.dictionary_types(mapping_type)[1]
            arguments[1] = self.coerce_value(*arguments[1], value_kind, node.args[1], semantic=member)
        if custom:
            return mapping_keys.remove(self, receiver, key_type, arguments, value_kind, value_size, operation, node)
        key, _ = self.dictionary_key_pointer(key_type, *arguments[0], node, for_lookup=True,
                                             source_type=analyzed_value_type(node.args[0]))
        output = "null"
        if operation == "pop":
            output = self.emit_value(f"alloca {value_kind}")
            if len(arguments) == 2:
                self.emit_line(f"store {value_kind} {arguments[1][1]}, ptr {output}")
        removed = self.emit_value(f"call i1 @pyjs.dict.pop.into(ptr {receiver}, ptr {key}, {sizes}, i8 {key_kind}, ptr {output})")
        if operation != "discard" and not (operation == "pop" and len(arguments) == 2):
            self.guard_key(node, removed, *arguments[0])
        return (value_kind, self.emit_value(f"load {value_kind}, ptr {output}")) if operation == "pop" else ("void", "")

    def set_call(
        self,
        operation: str,
        set_type,
        receiver: str,
        arguments: list[tuple[str, str]],
        node: ast.Call,
    ) -> tuple[str, str]:
        item_type = self.set_item_type(set_type)
        if node.keywords:
            raise LLVMUnsupported("LLVM set methods require positional arguments", node)
        if operation in {"clear", "copy", "update", "remove", "discard"}:
            return self.mapping_mutation(operation, set_type, item_type,
                                         "i1", receiver, arguments, node)
        if operation == "__bool__" and not arguments:
            length_pointer = self.new_temporary()
            length = self.new_temporary()
            result = self.new_temporary()
            self.emit_line(
                f"{length_pointer} = getelementptr %pyjs.set, "
                f"ptr {receiver}, i32 0, i32 0"
            )
            self.emit_line(f"{length} = load i64, ptr {length_pointer}")
            self.emit_line(f"{result} = icmp ne i64 {length}, 0")
            return "i1", result
        if operation == "__contains__" and len(arguments) == 1:
            source_type = object_values.instance_type(node.args[0])
            if source_type is None:
                return "i1", "false"
            slot, _value_type = self.dictionary_lookup(
                receiver,
                set_type,
                arguments[0][0],
                arguments[0][1],
                node,
                source_type=source_type,
            )
            result = self.new_temporary()
            self.emit_line(f"{result} = icmp ne ptr {slot}, null")
            return "i1", result
        if operation == "add" and len(arguments) == 1:
            enum_ops.check_type_conversion(object_values.instance_type(node.args[0]), item_type, node.args[0])
            slot = self.dictionary_set_slot(
                receiver,
                item_type,
                arguments[0][0],
                arguments[0][1],
                "1",
                node,
            )
            self.emit_line(f"store i1 true, ptr {slot}")
            return "void", ""
        raise LLVMUnsupported(
            f"LLVM set operation {operation} is not implemented",
            node,
        )

    def tuple_type(self, value_type, node=None) -> str:
        """Describe a fixed tuple's payload, behind its sequence header."""
        if getattr(value_type, "tuple_variadic", False):
            raise LLVMUnsupported("variable-length tuples use sequence storage, not a fixed tuple layout", node)
        if value_type.generic_name != "tuple":
            raise LLVMUnsupported(f"LLVM expected tuple, received {value_type.name}")
        self.value_type(value_type, node)
        fields = tuple(
            self.value_type(field_type)
            for field_type in value_type.generic_types.values()
        )
        name = self.module.tuple_types.get(fields)
        if name is None:
            suffix = ".".join(value.removeprefix("%") for value in fields)
            name = self.name(suffix or "empty", "pyjs.tuple")
            self.module.tuple_types[fields] = name
        return name

    def scalar_abs(self, kind, value, node):
        if kind == "i1":
            return "i64", self.emit_value(f"zext i1 {value} to i64")
        if kind == "double":
            result = self.emit_value(f"call double @llvm.fabs.f64(double {value})")
            return self.normalize_float_result(result, node)
        if kind != "i64":
            raise LLVMUnsupported("LLVM abs requires a number", node)
        negative = self.emit_value(f"icmp slt i64 {value}, 0")
        inverted = self.emit_value(f"sub i64 0, {value}")
        result = self.emit_value(f"select i1 {negative}, i64 {inverted}, i64 {value}")
        return self.normalize_integer_result(result, node)

    def annotation(self, node: ast.expr | None) -> str:
        if isinstance(getattr(node, "obj", None), UnionType):
            return self.value_type(node.obj, node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # Raw annotations have no analyzed union yet. None now has ptr
            # storage, so its syntax/semantic type, not the ABI, identifies it.
            for missing, present in ((node.left, node.right), (node.right, node.left)):
                if (getattr(getattr(missing, "obj", None), "generic_name", None) == "NoneType"
                        or isinstance(missing, ast.Constant) and missing.value is None
                        or isinstance(missing, ast.Name) and missing.id in {"None", "NoneType"}):
                    kind = self.annotation(present)
                    if kind == "ptr":
                        return kind
                    if kind in nullable.SCALARS:
                        return nullable.pair(kind)
            return tagged.STORAGE
        value_type = getattr(node, "obj", None)
        if value_type is None and isinstance(node, ast.Name) and self.current_function is not None:
            try:
                value_type = self.current_function.scope.search(node.id)
            except NameError:
                pass
        if isinstance(value_type, (Class, UnionType)):
            return self.value_type(value_type)
        if node is None or (
            isinstance(node, ast.Constant) and node.value is None
        ):
            return "ptr"
        if isinstance(node, ast.Name):
            if node.id in {"None", "NoneType"}:
                return "ptr"
            if node.id == "bool":
                return "i1"
            if node.id == "int":
                return "i64"
            if node.id == "float":
                return "double"
            if node.id in {"str", "bytes", "range"}:
                return "ptr"
            if node.id in {"Attribute", "Document", "Element", "WebElement", "_WebElement"}:
                return "ptr"
            if node.id in self.module.class_names:
                return "ptr"
            value_type = getattr(node, "obj", None)
            if isinstance(value_type, Class):
                return self.value_type(value_type)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"list", "tuple", "Callable", "Iterator", "Generator", *collection_ops.VIEWS}
        ):
            return "ptr"
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "dict"
        ):
            return "ptr"
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"set", "frozenset"}
        ):
            return "ptr"
        raise LLVMUnsupported("unsupported LLVM type annotation", node)

    @staticmethod
    def is_exception_type(value_type):
        if isinstance(value_type, UnionType):
            return all(FunctionEmitter.is_exception_type(member) for member in value_type.types)
        return isinstance(value_type, Class) and is_subclass(
            value_type, NATIVE_ENVIRONMENT.builtins.search("BaseException"),
        )

    @staticmethod
    def is_exception_token_type(value_type):
        return (isinstance(value_type, Class) and value_type.generic_name == "type"
                and bool(value_type.generic_types)
                and all(FunctionEmitter.is_exception_type(member) for member in value_type.generic_types.values()))

    def exception_token_name(self, value_type):
        return self.name(f"{value_type.container.name}.{value_type.name}", "exception.type")

    def guard_c_int(self, node, value):
        # Python APIs such as os.write and expandtabs narrow index results to
        # C int before calling their lower-level, independently checked kernels.
        low = self.emit_value(f"icmp sge i64 {value}, -2147483648")
        high = self.emit_value(f"icmp sle i64 {value}, 2147483647")
        self.guard_exception(node, self.emit_value(f"and i1 {low}, {high}"),
                             "OverflowError", "Python int too large to convert to C int")

    def exception_field(self, index, context=None):
        context = context or self.load_local("__exception")
        return self.emit_value(f"getelementptr %pyjs.exception, ptr {context}, i32 0, i32 {index}")

    def raise_error(self, node, name, message):
        value_type = NATIVE_ENVIRONMENT.builtins.search(name)
        self.activate_error(node, value_type, f"@{self.string_constant(message)}")
        self.branch_to_exception_target()

    def guard_nonzero(self, node, kind, value, message):
        comparison = f"fcmp une double {value}, 0.0" if kind == "double" else f"icmp ne {kind} {value}, 0"
        self.guard_exception(node, self.emit_value(comparison), "ZeroDivisionError", message)

    def guard_division_overflow(self, node, left, right):
        minimum = self.emit_value(f"icmp eq i64 {left}, -9223372036854775808")
        negative = self.emit_value(f"icmp eq i64 {right}, -1")
        overflow = self.emit_value(f"and i1 {minimum}, {negative}")
        self.guard_exception(node, self.emit_value(f"xor i1 {overflow}, true"),
                             "OverflowError", "integer quotient exceeds native i64 limits")

    def checked_narrow_integer(self, node, value, message):
        low = self.emit_value(f"icmp sge i128 {value}, -9223372036854775808")
        high = self.emit_value(f"icmp sle i128 {value}, 9223372036854775807")
        self.guard_exception(node, self.emit_value(f"and i1 {low}, {high}"), "OverflowError", message)
        return self.emit_value(f"trunc i128 {value} to i64")

    def guard_index(self, node, index, length, message):
        negative = self.emit_value(f"icmp slt i64 {index}, 0")
        offset = self.emit_value(f"add i64 {index}, {length}")
        actual = self.emit_value(f"select i1 {negative}, i64 {offset}, i64 {index}")
        valid = self.emit_value(f"icmp ult i64 {actual}, {length}")
        self.guard_exception(node, valid, "IndexError", message)

    def guard_exception(self, node, valid, name, message):
        if not self.module.uses_exceptions:
            self.trap_unless(valid)
            return
        passed, failed = self.new_label("checked"), self.new_label("error")
        self.emit_line(f"br i1 {valid}, label %{passed}, label %{failed}")
        self.emit_line(f"{failed}:")
        self.raise_error(node, name, message)
        self.emit_line(f"{passed}:")

    def require_allocation(self, value):
        self.guard_exception(
            getattr(self, "allocation_node", None) or self.current_function.original_node,
            self.emit_value(f"icmp ne ptr {value}, null"),
            "MemoryError", "native allocation failed",
        )
        return value

    def allocated_value(self, instruction):
        return self.require_allocation(self.emit_value(instruction))

    def key_message(self, kind, value, semantic=None):
        from . import mapping_keys
        if mapping_keys.uses_callbacks(semantic):
            return representation.render(self, semantic, kind, value, self.allocation_node)[1]
        scalar = nullable.payload_kind(kind)
        if scalar is not None or (kind == "ptr" and nullable.member(semantic)):
            result = self.emit_value("alloca ptr")
            self.emit_line(f"store ptr @{self.string_constant('None')}, ptr {result}")
            present, done = self.new_label("key.payload"), self.new_label("key.repr.done")
            self.emit_line(f"br i1 {nullable.present(self, kind, value)}, label %{present}, label %{done}")
            self.emit_line(f"{present}:")
            payload = self.emit_value(f"extractvalue {kind} {value}, 1") if scalar else value
            message = self.key_message(scalar or kind, payload, nullable.member(semantic))
            self.emit_line(f"store ptr {message}, ptr {result}")
            self.emit_line(f"br label %{done}")
            self.emit_line(f"{done}:")
            return self.emit_value(f"load ptr, ptr {result}")
        if kind == "void" or getattr(semantic, "generic_name", None) == "NoneType":
            return f"@{self.string_constant('None')}"
        if kind == "double":
            return self.string_from_float(value)
        if kind == tagged.STORAGE:
            # Integer-key lookup can consume a Boolean-tagged integer. The
            # KeyError still displays the original key, not its numeric payload.
            semantic = tagged.effective_type(NATIVE_ENVIRONMENT.builtins.search("int"), kind)
            return tagged.dispatch(self, semantic, value, "ptr",
                                   lambda member, storage, item: self.key_message(storage, item))
        if kind == "ptr":
            if getattr(semantic, "generic_name", None) == "bytes":
                return self.owned_text_call("pyjs.text.repr_bytes", [f"ptr {value}"])[1]
            return self.allocated_value(
                f"call ptr @pyjs.exception.key.repr(ptr {self.load_local('__arena')}, "
                f"ptr {value}, ptr @pyjs.unicode.printable, i64 {len(runtime_text.PRINTABLE_RANGES)})"
            )
        return self.string_from_bool(value) if kind == "i1" else self.string_from_int(value)

    def guard_key(self, node, valid, kind, key):
        if not self.module.uses_exceptions:
            self.trap_unless(valid)
            return
        passed, failed = self.new_label("key.present"), self.new_label("key.missing")
        self.emit_line(f"br i1 {valid}, label %{passed}, label %{failed}")
        self.emit_line(f"{failed}:")
        semantic = analyzed_value_type(node.args[0]) if isinstance(node, ast.Call) and node.args else None
        self.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("KeyError"), self.key_message(kind, key, semantic))
        self.branch_to_exception_target()
        self.emit_line(f"{passed}:")

    def activate_error(self, node, value_type, message, *, include_frame=True, retained="null"):
        self.module.exception_types.add(value_type)
        frame = self.traceback_frame(self.current_function, node) if include_frame else ""
        prefix = self.string_constant(frame + f"{value_type.name}: ")
        self.module.exception_origins.add(prefix)
        for index, kind, value in (
            (0, "i1", "true"), (1, "ptr", f"@{self.exception_token_name(value_type)}"),
            (2, "ptr", f"@{prefix}.trace"), (3, "ptr", message),
            (4, "ptr", f"@{prefix}.truncated"),
            (5, "ptr", retained),
            (6, "i1", "false"),
        ):
            self.emit_line(f"store {kind} {value}, ptr {self.exception_field(index)}")

    def branch_to_exception_target(self):
        target = self.name(self.exception_target, "block") if self.exception_target else "pyjs.exception.return"
        self.emit_line(f"br label %{target}")

    def prepend_exception_frame(self, node):
        frame = self.string_constant(self.traceback_frame(self.current_function, node))
        self.emit_line(f"call void @pyjs.exception.prepend(ptr {self.load_local('__arena')}, ptr {self.load_local('__exception')}, ptr @{frame})")

    def check_active_exception(self, node):
        if not self.module.uses_exceptions:
            return
        active = self.emit_value(f"load i1, ptr {self.exception_field(0)}")
        failed, continued = self.new_label("exception.failed"), self.new_label("exception.continue")
        self.emit_line(f"br i1 {active}, label %{failed}, label %{continued}")
        self.emit_line(f"{failed}:")
        self.prepend_exception_frame(node)
        self.branch_to_exception_target()
        self.emit_line(f"{continued}:")

    def exception_dispatch(self, node):
        token = self.emit_value(f"load ptr, ptr {self.exception_field(1)}")
        for caught_types, target in node.handlers:
            matched = self.exception_matches(token, caught_types)
            following = self.new_label("exception.next")
            self.emit_line(f"br i1 {matched}, label %{self.name(target, 'block')}, label %{following}")
            self.emit_line(f"{following}:")
        target = self.name(node.unmatched, "block") if node.unmatched else "pyjs.exception.return"
        self.emit_line(f"br label %{target}")

    def exception_matches(self, token, caught_types):
        matching = sorted((value for value in self.module.exception_types
                           if not caught_types or any(is_subclass(value, caught) for caught in caught_types)),
                          key=self.exception_token_name)
        matched = "false"
        for value_type in matching:
            comparison = self.emit_value(f"icmp eq ptr {token}, @{self.exception_token_name(value_type)}")
            matched = self.emit_value(f"or i1 {matched}, {comparison}")
        return matched

    def exception_statement(self, node):
        if isinstance(node, ExceptionDispatch):
            self.exception_dispatch(node)
        elif isinstance(node, ExceptionCatch):
            self.restore_gc_frame()
            snapshot = self.exception_snapshots[id(node)]
            value = self.emit_value(f"load %pyjs.exception, ptr {self.load_local('__exception')}")
            self.emit_line(f"store %pyjs.exception {value}, ptr {snapshot}")
            self.store(node.target, "ptr", snapshot)
            self.emit_line(f"store i1 false, ptr {self.exception_field(0)}")
        elif isinstance(node, ExceptionRaise):
            self.activate_exception(node)
            self.branch_to_exception_target()

    def exception_payload(self, node):
        if node.reraised:
            if node.exception is None:
                raise LLVMUnsupported("bare raise requires a saved exception", node)
            return self.expression(node.exception)[1]
        for base in getattr(node.value_type.py_obj, "__mro__", ()):
            if base.__module__ not in {"builtins", "pyjs.python.native"} and "value" in vars(base):
                raise LLVMUnsupported("LLVM exception subclasses cannot override the value property", node)
            if base.__module__ not in {"builtins", "pyjs.python.native"} and (
                any(name in vars(base) for name in ("__new__", "__init__", "__str__"))
            ):
                raise LLVMUnsupported("LLVM exception subclasses cannot override construction or __str__ yet", node)
        if exception_values.retains(node.value_type, node.message):
            retained, _ = exception_values.payload(self, node)
            return "null", retained
        return self.exception_message(node), "null"

    def activate_exception(self, node, payload=None, *, include_frame=True):
        payload = self.exception_payload(node) if payload is None else payload
        if node.reraised:
            value = self.emit_value(f"load %pyjs.exception, ptr {payload}")
            self.emit_line(f"store %pyjs.exception {value}, ptr {self.load_local('__exception')}")
            self.emit_line(f"store i1 true, ptr {self.exception_field(0)}")
            if node.append_trace:
                self.prepend_exception_frame(node)
        else:
            message, retained = payload
            self.activate_error(node, node.value_type, message, include_frame=include_frame, retained=retained)

    def exception_message(self, node):
        if node.message is None:
            # SyntaxError.msg defaults to None, unlike BaseException's empty
            # args. This path also handles inherited and generator-thrown errors.
            syntax = is_subclass(node.value_type, NATIVE_ENVIRONMENT.builtins.search("SyntaxError"))
            return f"@{self.string_constant('None' if syntax else '')}"
        semantic = analyzed_value_type(node.message)
        if any(collection_ops.builtin_name(member) not in {"str", "int", "bool", "float", "NoneType"}
               for member in get_type_members(semantic)):
            raise LLVMUnsupported("LLVM exception messages require str, int, bool, float, None, or unions of them", node)
        kind, value = self.expression(node.message)
        quoted = is_subclass(node.value_type, NATIVE_ENVIRONMENT.builtins.search("KeyError"))

        def render(member, storage, payload):
            if storage == tagged.STORAGE:
                return tagged.dispatch(self, tagged.effective_type(member, storage), payload, "ptr", render)
            if nullable.member(member):
                return nullable.dispatch(self, member, storage, payload, "ptr",
                                         f"@{self.string_constant('None')}", render)
            if collection_ops.builtin_name(member) == "NoneType":
                return f"@{self.string_constant('None')}"
            if quoted and collection_ops.builtin_name(member) == "str":
                return self.key_message(storage, payload)
            return nullable.string(self, member, storage, payload, node)

        return render(semantic, kind, value)

    def exception_definitions(self):
        marker = self.string_constant("  [native traceback truncated: allocation failed]\n")
        result = []
        for value_type in sorted(self.module.exception_types, key=self.exception_token_name):
            name = self.string_constant(value_type.name)
            module = self.string_constant(
                "builtins" if value_type.container.scope.is_builtins else value_type.py_cls.__module__
            )
            # Keep the name first for native formatting; host reports also
            # copy module identity without importing application classes.
            result.append(f"@{self.exception_token_name(value_type)} = private constant "
                          f"{{ ptr, ptr }} {{ ptr @{name}, ptr @{module} }}")
        for name in sorted(self.module.exception_origins):
            result.extend([
                f"@{name}.trace = private constant %pyjs.trace {{ ptr @{name}, ptr null }}",
                f"@{name}.truncated = private constant %pyjs.trace {{ ptr @{marker}, ptr @{name}.trace }}",
            ])
        return result

    def wrapper_exception_check(self, result):
        if self.module.uses_exceptions:
            result.extend([
                "  %exception.active = load i1, ptr %exception",
                "  br i1 %exception.active, label %exception.failure, label %exception.success",
                "exception.success:",
            ])

    def wrapper_exception_failure(self, result, library=False):
        if not self.module.uses_exceptions:
            return
        result.extend([
            "exception.failure:",
            "  %trace.slot = getelementptr %pyjs.exception, ptr %exception, i32 0, i32 2",
            "  %trace = load ptr, ptr %trace.slot",
            "  %message.slot = getelementptr %pyjs.exception, ptr %exception, i32 0, i32 3",
        ])
        if self.module.uses_exception_values:
            result.extend([
                # Reporting must not overwrite the original type/trace if its
                # payload formatter raises or cannot allocate.
                "  %format.error = alloca %pyjs.exception",
                "  store %pyjs.exception zeroinitializer, ptr %format.error",
                "  %formatted = call ptr @pyjs.exception.text(ptr %arena, ptr %heap, ptr %format.error, ptr %exception)",
                "  %format.failed = icmp eq ptr %formatted, null",
                f"  %message = select i1 %format.failed, ptr @{self.string_constant('<exception str() failed>')}, ptr %formatted",
            ])
        else:
            result.append("  %message = load ptr, ptr %message.slot")
        if library:
            result.extend([
                "  %type.slot = getelementptr %pyjs.exception, ptr %exception, i32 0, i32 1",
                "  %type = load ptr, ptr %type.slot",
                "  call void %report_error(ptr %trace, ptr %message, ptr %type)",
                "  call void @pyjs.arena.destroy(ptr %arena)",
                "  ret i32 -1",
            ])
        else:
            result.extend([
                "  call void @pyjs.exception.write.trace(i32 2, ptr %trace, ptr %message, "
                f"ptr @{self.string_constant('Traceback (native PyJS):' + chr(10))}, "
                f"ptr @{self.string_constant(chr(10))})",
                "  call void @llvm.trap()",
                "  unreachable",
            ])

    @staticmethod
    def traceback_frame(function: Function, node: ast.AST) -> str:
        if function is None or function.py_func in (callable_adapters._adapter, iterator_views._adapter,
                                                    callables._callback, partials._partial, slices._dynamic_assignment):
            # Callable/default wrappers have no Python frame of their own. Other
            # outlined bodies (e.g. iterator steps) retain their source frames.
            return ""
        if isinstance(node, ObjectNew):
            node = node.call
        elif isinstance(node, IteratorCreate):
            node = node.iterable
        elif isinstance(node, IteratorNext) and not hasattr(node, "lineno"):
            node = node.target
        module = (
            function.cls.container
            if function.cls is not None
            else function.container
        )
        assert isinstance(module, Module)
        fragment = module.source_fragment
        filename = (
            fragment.source.filename if fragment is not None else module.name
        )
        # Function bodies are analyzed from their own source fragments, so a
        # lowered node's line is relative to the function definition. Restore
        # the module coordinate before applying an enclosing fragment offset.
        line = (
            (function.lineno or 1)
            + getattr(node, "lineno", 1)
            - 1
            + (fragment.line_delta if fragment is not None else 0)
        )
        return (
            f'  File "{filename}", line {line}, in {function.name}\n'
        )

    def restore_gc_frame(self):
        # Error edges may bypass a temporary argument-root frame's normal pop.
        # Restore the function's permanent frame before handling or unwinding.
        calls.restore_roots(self, self.gc_frame)

    def main_wrapper(self, entry_point: Function) -> list[str]:
        if calls.parameters(entry_point):
            raise LLVMUnsupported("the LLVM executable entry point cannot take arguments",
                                  entry_point.original_node)
        return_type = self.value_type(entry_point.return_type)
        return_storage_type = self.result_storage_type(
            entry_point.return_type,
            entry_point.return_numeric_format,
        )
        returns_string = collection_ops.builtin_name(entry_point.return_type) == "str"
        returns_none = return_storage_type == "void"
        if return_type != "i64" and not returns_string and not returns_none:
            raise LLVMUnsupported(
                "the LLVM executable entry point must return int, str or None"
            )
        result = []
        if returns_string and not self.module.uses_native and not self.module.uses_exceptions and not self.module.uses_print:
            result.extend(runtime_output.write_all_runtime())
            result.append("")
        # Configure standalone startup only, never a library caller's process.
        # POSIX SIGPIPE is ignored so descriptor failures become catchable.
        # Windows CRT streams need binary mode to preserve the emitted bytes.
        if sys.platform == "win32":
            uses_output = returns_string or self.module.uses_native or self.module.uses_exceptions or self.module.uses_print
            if uses_output:
                result.append("declare i32 @_setmode(i32, i32)")
            result.extend(["define i32 @main() {", "entry:"])
            if uses_output:
                # The output runtime supplies this scoped handler. Closed
                # streams must produce write errors, not CRT process aborts.
                result.extend([
                    "  %handler.previous = call ptr @_set_thread_local_invalid_parameter_handler(ptr @pyjs.write.invalid)",
                    "  %stdout.mode = call i32 @_setmode(i32 1, i32 32768)",
                    "  %stderr.mode = call i32 @_setmode(i32 2, i32 32768)",
                    "  %handler.ignored = call ptr @_set_thread_local_invalid_parameter_handler(ptr %handler.previous)",
                ])
        else:
            result.extend(["declare ptr @signal(i32, ptr)", "define i32 @main() {", "entry:",
                           "  %sigpipe.previous = call ptr @signal(i32 13, ptr inttoptr (i64 1 to ptr))"])
        arguments = ""
        hidden_arguments = []
        if self.module.uses_arena:
            result.extend(
                [
                    "  %arena = alloca %pyjs.arena",
                    "  call void @pyjs.arena.init(ptr %arena)",
                ]
            )
            hidden_arguments.append("ptr %arena")
        if self.module.uses_gc:
            result.extend(
                [
                    "  %heap = alloca %pyjs.gc",
                    "  call void @pyjs.gc.init(ptr %heap)",
                ]
            )
            hidden_arguments.append("ptr %heap")
        if self.module.uses_exceptions:
            result.extend(["  %exception = alloca %pyjs.exception", "  store %pyjs.exception zeroinitializer, ptr %exception"])
            hidden_arguments.append("ptr %exception")
        arguments = ", ".join(hidden_arguments)
        result.extend(
            [
                f"  {'' if returns_none else '%result = '}call {return_storage_type} "
                f"@{self.function_name(entry_point)}"
                f"({arguments})",
            ]
        )
        self.wrapper_exception_check(result)
        if returns_string:
            result.extend(
                [
                    "  %length.pointer = getelementptr %pyjs.string, "
                    "ptr %result, i32 0, i32 0",
                    "  %length = load i64, ptr %length.pointer",
                    "  %data.pointer = getelementptr %pyjs.string, "
                    "ptr %result, i32 0, i32 1",
                    "  %data = load ptr, ptr %data.pointer",
                    "  %write.status = call i32 @pyjs.write.all("
                    "i32 1, ptr %data, i64 %length)",
                ]
            )
        if self.module.uses_arena:
            result.append("  call void @pyjs.arena.destroy(ptr %arena)")
        if self.module.uses_gc:
            result.append("  call void @pyjs.gc.destroy(ptr %heap)")
        if returns_string or returns_none:
            result.append("  ret i32 " + ("%write.status" if returns_string else "0"))
            self.wrapper_exception_failure(result)
            result.append("}")
            return result
        if return_storage_type == "i64":
            result.append("  %exit = trunc i64 %result to i32")
            exit_value = "%exit"
        elif return_storage_type in {"i8", "i16"}:
            operation = "sext" if entry_point.return_numeric_format.signed else "zext"
            result.append(f"  %exit = {operation} {return_storage_type} %result to i32")
            exit_value = "%exit"
        else:
            exit_value = "%result"
        result.append(f"  ret i32 {exit_value}")
        self.wrapper_exception_failure(result)
        result.append("}")
        return result

    def library_wrapper(self, entry_point: Function) -> list[str]:
        """Expose a typed buffered or direct renderer through a descriptor ABI."""
        if not self.module.uses_arena:
            raise LLVMUnsupported("the LLVM renderer library requires arena storage")
        direct = self.module.library_is_direct
        host_parameters = self.module.library_host_parameters
        host_arguments = tuple(
            f"{self.annotation_storage_type(parameter.annotation, analyzed_numeric_format(parameter))} "
            f"%{self.name(parameter.arg, 'input')}"
            for parameter in host_parameters
        )
        # Optional scalar pairs and tagged unions cross the C ABI by address;
        # by-value aggregates would rely on platform-specific struct ABI rules.
        aggregate_inputs = {
            index: kind for index, parameter in enumerate(host_parameters)
            if nullable.payload_kind(kind := self.annotation(parameter.annotation)) or kind == tagged.STORAGE
        }
        exported_arguments = [f"ptr %{self.name(parameter.arg, 'input')}" if index in aggregate_inputs else argument
                              for index, (parameter, argument) in enumerate(zip(host_parameters, host_arguments, strict=True))]
        exported_parameters = (
            *(("ptr %heap",) if self.module.uses_gc else ()),
            "i32 %descriptor",
            *(("ptr %report_error",) if self.module.uses_exceptions else ()),
            *exported_arguments,
        )
        result = []
        if not self.module.uses_native and not self.module.uses_exceptions and not self.module.uses_print:
            result.extend(runtime_output.write_all_runtime())
            result.append("")
        if self.module.uses_gc:
            result.extend(
                [
                    "define ptr @pyjs_gc_new() {",
                    "entry:",
                    "  %heap = call ptr @pyjs.gc.try.new()",
                    "  ret ptr %heap",
                    "}",
                    "",
                    "define void @pyjs_gc_delete(ptr %heap) {",
                    "entry:",
                    "  call void @pyjs.gc.delete(ptr %heap)",
                    "  ret void",
                    "}",
                    "",
                ]
            )
        # CPython's marshaller creates exclusively borrowed headers. Keep its
        # copy cost independent of the retained heap size, while raw callers
        # retain the mixed borrowed/already-owned input contract. Both thin
        # entry points share one renderer implementation and failure path.
        for name, check_owned in (("pyjs_render_to_fd", "true"), ("pyjs_render_host_to_fd", "false")):
            result.extend([
                f"define i32 @{name}(" + ", ".join(exported_parameters) + ") {",
                "entry:",
                "  %status = call i32 @pyjs.render.entry(" + ", ".join((*exported_parameters, f"i1 {check_owned}")) + ")",
                "  ret i32 %status",
                "}",
                "",
            ])
        result.extend(
            [
                "define private i32 @pyjs.render.entry("
                + ", ".join((*exported_parameters, "i1 %check.owned"))
                + ") {",
                "entry:",
                "  %arena = alloca %pyjs.arena",
                "  call void @pyjs.arena.init(ptr %arena)",
            ]
        )
        call_arguments = ["ptr %arena", *host_arguments]
        for index, kind in aggregate_inputs.items():
            argument = self.name(host_parameters[index].arg, "input")
            result.append(f"  %{argument}.value = load {kind}, ptr %{argument}")
            call_arguments[index + 1] = f"{kind} %{argument}.value"
        if self.module.uses_gc:
            call_arguments.insert(1, "ptr %heap")
        if self.module.uses_exceptions:
            result.extend(["  %exception = alloca %pyjs.exception", "  store %pyjs.exception zeroinitializer, ptr %exception"])
            call_arguments.insert(2 if self.module.uses_gc else 1, "ptr %exception")
        promoted = inputs.enter(self, result, call_arguments)
        if direct:
            call_arguments.append("i64 %descriptor.i64")
            result.extend(
                [
                    "  %descriptor.i64 = sext i32 %descriptor to i64",
                    f"  %result.i64 = call i64 @{self.function_name(entry_point)}("
                    + ", ".join(call_arguments)
                    + ")",
                ]
            )
            self.wrapper_exception_check(result)
            result.append("  %status = trunc i64 %result.i64 to i32")
        else:
            result.append(
                f"  %result = call ptr @{self.function_name(entry_point)}("
                + ", ".join(call_arguments) + ")"
            )
            self.wrapper_exception_check(result)
            result.extend(
                [
                    "  %length.pointer = getelementptr %pyjs.string, "
                    "ptr %result, i32 0, i32 0",
                    "  %length = load i64, ptr %length.pointer",
                    "  %data.pointer = getelementptr %pyjs.string, "
                    "ptr %result, i32 0, i32 1",
                    "  %data = load ptr, ptr %data.pointer",
                    "  %status = call i32 @pyjs.write.all("
                    "i32 %descriptor, ptr %data, i64 %length)",
                ]
            )
        result.extend(["  call void @pyjs.arena.destroy(ptr %arena)", "  ret i32 %status"])
        if promoted:
            result.extend(["pyjs.exception.return:", "  br label %exception.failure"])
        self.wrapper_exception_failure(result, library=True)
        result.append("}")
        return result

    def emit_value(self, instruction: str, *, hoist_alloca: bool = True) -> str:
        result = self.new_temporary()
        self.emit_line(f"{result} = {instruction}", hoist_alloca=hoist_alloca)
        return result

    def string_literal_definitions(self) -> list[str]:
        return self.string_definitions()[1:-1] if self.module.string_constants else []

    def new_temporary(self) -> str:
        self.temporary += 1
        return f"%v{self.temporary}"

    def new_label(self, prefix: str) -> str:
        self.temporary += 1
        return self.name(str(self.temporary), prefix)

    def emit_line(self, line: str, *, hoist_alloca: bool = True) -> None:
        allocation = line.partition(" = alloca ")[2] if hoist_alloca else ""
        # Scratch slots in loop expressions must not grow the native stack per
        # iteration. Counted allocations may need body SSA values, and explicit
        # inline LLVM retains caller-authored placement.
        if (
            self.stack_allocations is not None and allocation
            and re.search(r",\s*i\d+\s+(?:%|\d)", allocation) is None
        ):
            self.stack_allocations.append(line)
        else:
            self.lines.append(line)

    def load_local(self, name: str) -> str:
        value_type = self.slot_types[name]
        result = self.new_temporary()
        self.emit_line(f"{result} = load {value_type}, ptr {self.slots[name]}")
        return result

    def load(self, name: str) -> tuple[str, str]:
        closures.check_initialized(self, name)
        if self.slot_types[name] == "void":
            return "void", ""
        storage_type = self.slot_types[name]
        result = self.load_local(name)
        return self.widen_numeric(
            storage_type,
            result,
            self.slot_numeric_formats.get(name),
        )

    def local_storage_binding(self, target):
        return local_storage_binding(self.current_function, target)

    def local_numeric_format(self, target) -> NumericFormat | None:
        if self.current_function is None or not isinstance(
            target,
            (ast.Name, ast.arg),
        ):
            return None
        return analyzed_numeric_format(self.local_storage_binding(target))

    @staticmethod
    def target_name(target: ast.expr) -> str:
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.arg):
            return target.arg
        if isinstance(target, BlockArgument):
            return target.name
        raise LLVMUnsupported("unsupported LLVM assignment target", target)

    @staticmethod
    def name(value: str, prefix: str) -> str:
        return f"{prefix}.{re.sub(r'[^A-Za-z0-9_$.-]', '_', value)}"

    def is_application_module(self, module: Module) -> bool:
        """Keep reached application and semantic-library Python bodies."""
        return module.name in {"pyjs.native.math", "pyjs.native.uuid", "pyjs.native.pathlib",
                               "pyjs.native.datetime"} or module is self.module.entry_module or (
            not module.scope.is_builtins
            and module.name != "pyjs"
            and not module.name.startswith("pyjs.")
        )

    def symbol_module(self, value: Class | Function) -> str:
        """Qualify imported symbols without changing established entry-module IR."""
        module = value.container if isinstance(value.container, Module) else None
        if isinstance(value, Function) and value.cls is not None:
            module = value.cls.container
        assert isinstance(module, Module)
        return "" if module is self.module.entry_module else f"{module.name}."

    def function_name(self, function: Function) -> str:
        if function in self.module.function_names:
            return self.module.function_names[function]
        if (
            function.name == self.module.entry_point
            and function.cls is None
            and function.container is self.module.entry_module
        ):
            name = "pyjs_main"
        elif function.cls in self.module.classes:
            name = (
                f"{self.symbol_module(function)}"
                f"{function.cls.name}.{properties.dispatch_name(function)}"
            )
        else:
            name = f"{self.symbol_module(function)}{function.name}"
        return self.name(name, "fn")

    def class_name(self, value_type: Class) -> str:
        return self.name(
            f"{self.symbol_module(value_type)}{value_type.name}",
            "class",
        )

    def vtable_type(self, value_type: Class) -> str:
        return self.name(
            f"{self.symbol_module(value_type)}{value_type.name}",
            "vtable.type",
        )

    def vtable_name(self, value_type: Class) -> str:
        return self.name(
            f"{self.symbol_module(value_type)}{value_type.name}",
            "vtable",
        )

    def string_constant(self, value: str | bytes) -> str:
        name = self.module.string_constants.get(value)
        if name is None:
            try:
                if isinstance(value, str):
                    value.encode("utf-8")
            except UnicodeEncodeError:
                raise LLVMUnsupported("LLVM strings do not support lone surrogates") from None
            name = f"{self.module.literal_namespace}.str.{len(self.module.string_constants)}"
            self.module.string_constants[value] = name
        return name

    @staticmethod
    def llvm_bytes(value: bytes) -> str:
        return "".join(
            chr(byte) if 32 <= byte <= 126 and byte not in {34, 92} else f"\\{byte:02X}"
            for byte in value
        )

    integer_runtime = staticmethod(runtime_numeric.integer_runtime)
    float_runtime = staticmethod(runtime_numeric.float_runtime)

    @staticmethod
    def string_runtime() -> list[str]:
        return [
            *runtime_text.compiled_owned_text_runtime(),
            *runtime_text.compiled_text_runtime(),
            "declare i32 @memcmp(ptr, ptr, i64)",
            "declare i32 @snprintf(ptr, i64, ptr, ...)",
            "",
            "define ptr @pyjs.string.new(ptr %arena, i64 %length) {",
            "entry:",
            "  %string = call ptr @pyjs.string.new.owned(ptr %arena, ptr null, ptr null, i64 %length)",
            "  ret ptr %string",
            "}",
            "",
            "define ptr @pyjs.string.concat(ptr %arena, ptr %left, ptr %right) {",
            "entry:",
            "  %result = call ptr @pyjs.string.concat.owned(ptr %arena, ptr null, ptr null, ptr %left, ptr %right)",
            "  ret ptr %result",
            "}",
            "",
            "define ptr @pyjs.string.from.i64(ptr %arena, i64 %value) {",
            "entry:",
            "  %result = call ptr @pyjs.string.from.i64.owned(ptr %arena, ptr null, ptr null, i64 %value)",
            "  ret ptr %result",
            "}",
            "",
            "define ptr @pyjs.string.from.i64.owned(ptr %arena, ptr %allocator, ptr %context, i64 %value) {",
            "entry:",
            "  %buffer = alloca [32 x i8]",
            "  %count.i32 = call i32 (ptr, i64, ptr, ...) @snprintf(ptr %buffer, i64 32, ptr @pyjs.string.int.format, i64 %value)",
            "  %count = sext i32 %count.i32 to i64",
            "  %result = call ptr @pyjs.string.new.owned(ptr %arena, ptr %allocator, ptr %context, i64 %count)",
            "  %failed = icmp eq ptr %result, null",
            "  br i1 %failed, label %done, label %copy",
            "copy:",
            "  %data.pointer = getelementptr %pyjs.string, ptr %result, i32 0, i32 1",
            "  %data = load ptr, ptr %data.pointer",
            "  call void @llvm.memcpy.p0.p0.i64(ptr %data, ptr %buffer, i64 %count, i1 false)",
            "  br label %done",
            "done:",
            "  ret ptr %result",
            "}",
        ]

    @staticmethod
    def dom_type_definitions() -> list[str]:
        return [
            "%pyjs.native.attribute = type { ptr, ptr }",
            "%pyjs.native.argument = type { i8, ptr }",
            "%pyjs.native.element = type { ptr, ptr, i8, ptr }",
        ]

    @staticmethod
    def dom_runtime() -> list[str]:
        return [
            *runtime_output.write_all_runtime(),
            *runtime_output.output_runtime(),
            *runtime_dom.compiled_runtime(),
        ]

    def collection_runtime(self, include_mappings: bool = False, include_search: bool = False) -> list[str]:
        from .runtime import mappings, sequences

        wrappers = """
            define ptr @pyjs.list.new(ptr %arena, i64 %item.size, i64 %length) {
            entry:
              %list = call ptr @pyjs.list.new.owned(ptr %arena, ptr null, ptr null, i64 %item.size, i64 %length)
              ret ptr %list
            }
        """
        mapping_owners = []
        if include_mappings:
            wrappers += """
                define ptr @pyjs.dict.new(ptr %arena, i64 %key.size, i64 %value.size) {
                entry:
                  %dict = call ptr @pyjs.dict.new.owned(ptr %arena, ptr null, ptr null, i64 %key.size, i64 %value.size)
                  ret ptr %dict
                }

                define ptr @pyjs.dict.require(ptr %slot) {
                entry:
                  %value = call ptr @pyjs.collection.require(ptr %slot)
                  ret ptr %value
                }
            """
            mapping_owners = [
                *gc_layouts.owned_header(self, "mapping", "%pyjs.dict", ((2,), (3,), (6,), (8,))),
            ]
        return [
            *sequences.compiled_runtime(include_search),
            *gc_layouts.owned_header(self, "collection", "%pyjs.list", ((2,),)),
            *(["@pyjs.gc.descriptor.tuple = private constant %pyjs.gc.descriptor { i64 -1, ptr @pyjs.tuple.trace }"]
              if self.module.uses_gc else ()),
            *gc_layouts.owned_header(self, "tuple", "%pyjs.list", (),
                                    trace="@pyjs.gc.descriptor.tuple", atomic_payload=True),
            *(mappings.compiled_runtime() if include_mappings else ()),
            *mapping_owners,
            *textwrap.dedent(wrappers).strip().splitlines(),
        ]


class LLVMEmitter(FunctionEmitter):
    """Module entry point; functions share only explicit module state."""

    def __init__(self, entry_point: str, target: str = "executable", *, direct: bool = False) -> None:
        super().__init__(ModuleState(entry_point, target, direct))


def transpile_llvm(
    source: str,
    *,
    filename: str = "_pyjs_native_.py",
    module_name: str | None = None,
    entry_point: str = "main",
    target: str = "executable",
    direct: bool = False,
    wrap: bool | None = False,
) -> str:
    """Analyze source and emit an executable or shared-library LLVM module."""
    return transpile_llvm_module(
        source,
        filename=filename,
        module_name=module_name,
        entry_point=entry_point,
        target=target,
        direct=direct,
        wrap=wrap,
    ).llvm_ir


def transpile_llvm_module(
    source: str,
    *,
    filename: str = "_pyjs_native_.py",
    module_name: str | None = None,
    entry_point: str = "main",
    target: str = "executable",
    direct: bool = False,
    wrap: bool | None = False,
) -> LLVMModule:
    """Analyze source and retain the generated library's typed ABI."""
    source = textwrap.dedent(source)
    with analyze_source(
        source,
        filename=filename,
        module_name=module_name,
        entry_point=entry_point,
        wrap=wrap,
        environment=NATIVE_ENVIRONMENT,
    ) as analysis:
        emitter = LLVMEmitter(entry_point, target, direct=direct)
        llvm_ir = emitter.emit(build_program_ir(analysis.entry_point))
        return LLVMModule(
            llvm_ir,
            emitter.module.abi_parameters,
            emitter.module.library_is_direct,
            emitter.module.uses_gc,
            emitter.module.uses_exceptions,
            tuple(emitter.module.abi_type_definitions),
        )

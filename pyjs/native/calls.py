"""Bind Python calls once, then lower their values to the native ABI."""

import ast
import inspect
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from types import SimpleNamespace

from pyjs.analysis.analyzer import (
    analyzed_iterable_protocol,
    analyzed_value_type,
    declared_protocol_method,
)
from pyjs.analysis.generic_inference import substitute_representation_variables
from pyjs.analysis.ir import CollectionNew
from pyjs.analysis.objects import (
    CallableClass,
    Class,
    Function,
    TypeVariableClass,
    UnionType,
)
from pyjs.analysis.representation import apply_representation
from pyjs.analysis.type_relations import (
    get_type_members,
    is_return_type_compatible,
    is_subclass,
    same_analyzer_type,
    substitute_type_variables,
)
from pyjs.analysis.value_representation import (
    analyzed_numeric_format,
    analyzed_representation,
    representation_for_member,
    representations_conflict,
    set_analyzed_representation,
)

from . import collection_ops, nullable, persistent, super_proxy, tagged
from . import dataclasses as dataclass_ops
from .analysis import (
    NATIVE_ENVIRONMENT,
    expands_arguments,
    generator_representation_compatible,
)
from .errors import LLVMUnsupported


@contextmanager
def recursion_scope(e, node, message):
    """Bound reentrant runtime protocols and unwind the depth on exceptions."""
    depth = e.emit_value("alloca %pyjs.repr.frame")
    arena = e.load_local("__arena")
    entered = e.emit_value(f"call i8 @pyjs.repr.enter(ptr {arena}, ptr {depth}, ptr null)")
    e.guard_exception(node, e.emit_value(f"icmp ne i8 {entered}, 2"), "RecursionError", message)
    outer, cleanup = e.exception_target, e.new_label("protocol.cleanup")
    e.exception_target = cleanup
    try:
        yield
    finally:
        e.exception_target = outer
    e.emit_line(f"call void @pyjs.repr.leave(ptr {arena}, ptr {depth})")
    done = e.new_label("protocol.done")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{e.name(cleanup, 'block')}:")
    e.emit_line(f"call void @pyjs.repr.leave(ptr {arena}, ptr {depth})")
    e.branch_to_exception_target()
    e.emit_line(f"{done}:")


@dataclass(frozen=True)
class BoundCall:
    values: list[tuple[str, str]]
    sources: list[ast.expr | None]
    emitter: object = None
    frame: str | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        # Binding may allocate packs or boxed values before a constructor or
        # callback runs. Retain those roots through the entire consumer, not
        # just until argument collection finishes.
        if self.frame is not None:
            pop_roots(self.emitter, self.frame)


def push_roots(emitter, slots):
    if not emitter.module.uses_gc:
        return None
    pointers = emitter.emit_value(f"alloca [{len(slots)} x ptr]")
    for index, slot in enumerate(slots):
        address = emitter.emit_value(f"getelementptr ptr, ptr {pointers}, i64 {index}")
        emitter.emit_line(f"store ptr {slot}, ptr {address}")
    frame = emitter.emit_value("alloca %pyjs.gc.frame")
    emitter.emit_line(f"call void @pyjs.gc.frame.push(ptr {emitter.load_local('__heap')}, "
                      f"ptr {frame}, ptr {pointers}, i64 {len(slots)})")
    return frame


def pop_roots(emitter, frame):
    if frame is not None:
        emitter.emit_line(f"call void @pyjs.gc.frame.pop(ptr {emitter.load_local('__heap')}, ptr {frame})")


def restore_roots(emitter, frame):
    if frame is not None:
        roots = emitter.emit_value(f"getelementptr %pyjs.gc, ptr {emitter.load_local('__heap')}, i32 0, i32 2")
        emitter.emit_line(f"store ptr {frame}, ptr {roots}")


def value_slots(emitter, kinds):
    slots = []
    for kind in kinds:
        slot = emitter.emit_value(f"alloca {kind}")
        emitter.emit_line(f"store {kind} zeroinitializer, ptr {slot}")
        slots.append(slot)
    frame = push_roots(emitter, [tagged.root_slot(emitter, kind, slot)
                                for kind, slot in zip(kinds, slots, strict=True)
                                if kind in {"ptr", tagged.STORAGE}])
    return slots, frame


def root_values(emitter, *values):
    """Root intermediate pointers before their surrounding AST value exists."""
    if not emitter.module.uses_gc:
        return None
    slots, frame = value_slots(emitter, ["ptr"] * len(values))
    for slot, value in zip(slots, values, strict=True):
        emitter.emit_line(f"store ptr {value}, ptr {slot}")
    return frame


def object_argument_roots(emitter, types):
    """Keep boxed/adapted arguments alive while later conversions allocate."""
    roots = {}
    from .iterable_views import is_view
    from .iterator_ops import is_iterator
    if emitter.module.uses_gc:
        for index, semantic in enumerate(types):
            if (nullable.is_object(semantic) or is_view(nullable.member(semantic) or semantic)
                    or is_iterator(nullable.member(semantic) or semantic)
                    or isinstance(nullable.member(semantic) or semantic, CallableClass)):
                roots[index] = emitter.emit_value("alloca ptr")
                emitter.emit_line(f"store ptr null, ptr {roots[index]}")
    return roots, push_roots(emitter, list(roots.values())) if roots else None


def parameters(function):
    return tuple(parameter for parameter in (
        *function.params, function.vararg, *function.kwonlyargs, function.kwarg,
    ) if parameter is not None)


def parameter_defaults(function):
    return (
        *zip(function.params[len(function.params) - len(function.defaults):], function.defaults, strict=True),
        *zip(function.kwonlyargs, function.kw_defaults, strict=True),
    )


def immutable_default(function, parameter, value):
    if dataclass_ops.is_missing(value):
        return value
    if constant := persistent.scalar_literal(value):
        return constant
    raise LLVMUnsupported(
        f"LLVM default {function.name}.{parameter} must be an immutable "
        "constant or a supported literal collection", value)


def default_value(emitter, function, parameter, value, origin):
    entry = emitter.module.persistent_values.get((function, parameter))
    if entry is not None:
        return persistent.load(emitter, entry, origin)
    return emitter.expression(immutable_default(function, parameter, value))


def binding_signature(function):
    return (
        tuple(parameter.arg for parameter in function.params),
        function.posonly_count,
        tuple(parameter.arg for parameter in function.kwonlyargs),
        function.vararg.arg if function.vararg is not None else None,
        function.kwarg.arg if function.kwarg is not None else None,
        len(function.defaults),
        tuple(default is None for default in function.kw_defaults),
    )


def bind_keywords(emitter, parameter, node, *, representation=None):
    """Collect a builtin's keyword tail with ordinary duplicate checks/roots."""
    # A constructor's inferred collection representation belongs to this call,
    # not to its reusable generic __init__ declaration.
    parameter = copy(parameter)
    apply_representation(parameter, representation)
    signature = SimpleNamespace(name="keyword arguments", params=(), defaults=(),
                                kwonlyargs=(), kw_defaults=(), posonly_count=0,
                                vararg=None, kwarg=parameter)
    call = ast.copy_location(ast.Call(func=node.func, args=[], keywords=node.keywords), node)
    return bind(emitter, signature, call)


def bind(emitter, target, node, *, positional=None, load_default=None, vararg_type=None,
         runtime_errors=False, project_argument=None):
    # A projection returns typed storage or None to use normal validation. In
    # expanded runtime calls it must defer kind failures through on_mismatch;
    # raising while collecting would skip later operands and binding errors.
    # A checked native consumer may decode erased items itself. Override only
    # its temporary pack layout, never the analyzed signature or ordinary calls.
    if expands_arguments(node):
        return ExpandedCall(emitter, target, node, vararg_type=vararg_type,
                            runtime_errors=runtime_errors,
                            project_argument=project_argument).bind(load_default=load_default)
    if positional is None:
        positional = [emitter.expression(argument) for argument in node.args]
    keywords = [(keyword.arg, emitter.expression(keyword.value)) for keyword in node.keywords]

    def invalid(message, detail):
        if runtime_errors:
            # A union-selected signature may reject a call that another arm
            # accepts. Operands already ran; no defaults/packs or body may run.
            emitter.guard_exception(node, "false", "TypeError", detail)
            return None
        raise LLVMUnsupported(f"LLVM call to {target.name} {message}", node)

    if len(positional) > len(target.params) and target.vararg is None:
        return invalid("has too many positional arguments", "too many positional arguments")
    bound = {parameter.arg: value for parameter, value in zip(target.params, positional, strict=False)}
    sources = {parameter.arg: source for parameter, source in zip(target.params, node.args, strict=False)}
    keyword_sources = {keyword.arg: keyword.value for keyword in node.keywords}
    positional_only = {parameter.arg for parameter in target.params[:target.posonly_count]}
    allowed = {parameter.arg for parameter in (*target.params, *target.kwonlyargs)} - positional_only
    extra_keywords = []
    for name, value in keywords:
        if name not in allowed:
            if target.kwarg is not None:
                extra_keywords.append((name, value))
                continue
            return invalid(f"does not accept keyword {name}", "unexpected keyword argument")
        if name in bound:
            return invalid(f"gives {name} more than once", f"multiple values for argument '{name}'")
        bound[name] = value
        sources[name] = keyword_sources[name]
    defaults = parameter_defaults(target)
    supplied = bound.keys() | {parameter.arg for parameter, default in defaults if default is not None}
    missing = [parameter.arg for parameter in (*target.params, *target.kwonlyargs) if parameter.arg not in supplied]
    if missing:
        return invalid(f"is missing {', '.join(missing)}", f"missing required argument '{missing[0]}'")
    if project_argument is not None:
        # Runtime-selected protocols may recover a typed value from erased
        # transport. Do so after operand evaluation and signature checks, and
        # relabel only these temporary values, never the caller's AST/storage.
        def project(source, value, expected, representation):
            result = project_argument(emitter.runtime_value_type(source), expected, value[1], None)
            if result is None:
                return source, value
            source = tagged.Value(source, expected, *result)
            set_analyzed_representation(source, representation)
            return source, result

        for parameter in (*target.params, *target.kwonlyargs):
            if parameter.arg in bound:
                sources[parameter.arg], bound[parameter.arg] = project(
                    sources[parameter.arg], bound[parameter.arg], parameter.annotation.obj,
                    analyzed_representation(parameter))
        if target.vararg is not None:
            node = copy(node)
            node.args = list(node.args)
            positional = list(positional)
            member = vararg_type or collection_ops.item_type(target.vararg.annotation.obj)
            for index in range(len(target.params), len(node.args)):
                node.args[index], positional[index] = project(
                    node.args[index], positional[index], member, ExpandedCall.member_representation(target.vararg, 0))
        if target.kwarg is not None:
            _, member = emitter.dictionary_types(target.kwarg.annotation.obj)
            for index, (name, value) in enumerate(extra_keywords):
                keyword_sources[name], value = project(
                    keyword_sources[name], value, member, ExpandedCall.member_representation(target.kwarg, 1))
                extra_keywords[index] = name, value
    if runtime_errors:
        # The analyzer checked the statically visible signature, not this
        # runtime-selected override. Validate every supplied value before
        # loading defaults or allocating packs: equal pointer widths do not
        # make unrelated classes (or their container members) compatible.
        checks = [(sources[p.arg], p.annotation.obj, analyzed_representation(p))
                  for p in (*target.params, *target.kwonlyargs) if p.arg in bound]
        if target.vararg is not None:
            member = vararg_type or collection_ops.item_type(target.vararg.annotation.obj)
            checks.extend((source, member, ExpandedCall.member_representation(target.vararg, 0))
                          for source in node.args[len(target.params):])
        if target.kwarg is not None:
            _, member = emitter.dictionary_types(target.kwarg.annotation.obj)
            checks.extend((keyword_sources[name], member, ExpandedCall.member_representation(target.kwarg, 1))
                          for name, _ in extra_keywords)
        for source, expected, representation in checks:
            actual = emitter.runtime_value_type(source)
            try:
                validate_storage(emitter, actual, expected, source)
            except LLVMUnsupported:
                # A typing-valid conversion unsupported by this backend is
                # still a compile-time limitation, not a Python TypeError.
                # In particular, union receivers use this binder too; merely
                # selecting an arm must not hide their numeric-conversion
                # diagnostic behind a catchable runtime failure.
                if is_return_type_compatible(expected, actual):
                    raise
                return invalid("has incompatible arguments", "incompatible argument type")
            if (not nullable.is_object(expected) and representations_conflict((
                    (actual, analyzed_representation(source)), (expected, representation)))):
                return invalid("has incompatible arguments", "incompatible argument representation")
    for parameter, default in defaults:
        if parameter.arg not in bound and default is not None:
            bound[parameter.arg] = (load_default(parameter) if load_default is not None else
                                    default_value(emitter, target, parameter.arg, default, node))
            sources[parameter.arg] = None if load_default is not None else default
    packs = [parameter for parameter in (target.vararg, target.kwarg) if parameter is not None]
    slots, frame = value_slots(emitter, ["ptr"] * len(packs)) if packs else ([], None)
    pack_slots = dict(zip((parameter.arg for parameter in packs), slots, strict=True))
    # Packs survive later boxing, constructor allocation and callee callbacks.
    # Their lifetime belongs to the binding's with block, like expanded slots.
    # Each fresh converted handle must also survive allocation of its pack slot.
    if target.vararg is not None:
        member = vararg_type or collection_ops.item_type(target.vararg.annotation.obj)
        result = collection_ops.new_list(emitter, member)
        emitter.emit_line(f"store ptr {result}, ptr {pack_slots[target.vararg.arg]}")
        for source, (kind, value) in zip(node.args[len(target.params):], positional[len(target.params):], strict=True):
            collection_ops.require_matching_layout(analyzed_value_type(source), member, source)
            kind, value = emitter.coerce_value(kind, value, emitter.value_type(member), source, semantic=member,
                                              representation=ExpandedCall.member_representation(target.vararg, 0))
            converted_root = root_values(emitter, value) if kind == "ptr" else None
            collection_ops.append(emitter, result, member, member, value, node)
            pop_roots(emitter, converted_root)
        bound[target.vararg.arg] = "ptr", result
    if target.kwarg is not None:
        key, member = emitter.dictionary_types(target.kwarg.annotation.obj)
        result = collection_ops.new_mapping(emitter, key, member)
        emitter.emit_line(f"store ptr {result}, ptr {pack_slots[target.kwarg.arg]}")
        for name, (kind, value) in extra_keywords:
            collection_ops.require_matching_layout(analyzed_value_type(keyword_sources[name]), member, keyword_sources[name])
            kind, value = emitter.coerce_value(kind, value, emitter.value_type(member), keyword_sources[name], semantic=member,
                                              representation=ExpandedCall.member_representation(target.kwarg, 1))
            converted_root = root_values(emitter, value) if kind == "ptr" else None
            slot = emitter.dictionary_set_slot(result, key, "ptr", f"@{emitter.string_constant(name)}",
                                                emitter.llvm_size(kind), node)
            emitter.emit_line(f"store {kind} {value}, ptr {slot}")
            pop_roots(emitter, converted_root)
        bound[target.kwarg.arg] = "ptr", result
    ordered = parameters(target)
    return BoundCall([bound[parameter.arg] for parameter in ordered],
                     [sources.get(parameter.arg) for parameter in ordered], emitter, frame)


def validate_storage(emitter, actual, expected, node, *, member=False, allow_subclass=False):
    """Check dynamic destinations before storing or reinterpreting a payload."""
    if not member and nullable.is_object(expected):
        return
    if isinstance(actual, UnionType) or isinstance(expected, UnionType):
        if member:
            # No recursive container conversion occurs here. Aliased item
            # storage remains invariant, including the set of runtime tags.
            if not same_analyzer_type(actual, expected):
                raise LLVMUnsupported("LLVM stored collection items require identical union layouts", node)
            return
        if isinstance(actual, UnionType):
            for alternative in actual.types:
                validate_storage(emitter, alternative, expected, node)
            return
        for alternative in expected.types:
            try:
                validate_storage(emitter, actual, alternative, node)
            except LLVMUnsupported:
                continue
            return
        raise LLVMUnsupported("LLVM call argument requires a declared union member's storage; use an explicit conversion", node)
    if not isinstance(actual, Class) or not isinstance(expected, Class):
        raise LLVMUnsupported("LLVM call arguments require concrete parameter types", node)
    from .iterable_views import is_view
    from .iterator_ops import is_iterator
    if not member and (is_view(expected) or is_iterator(actual) and is_iterator(expected)):
        # These views adapt values when read, rather than reinterpreting
        # stored members. Their ordinary adapter checks item conversions;
        # treating yields as invariant container slots rejects valid boxing.
        collection_ops.require_matching_layout(actual, expected, node)
        return
    if emitter.value_type(actual) != emitter.value_type(expected) or (
        actual.py_cls is not expected.py_cls and ((member and not allow_subclass) or not is_subclass(actual, expected))
    ):
        raise LLVMUnsupported("LLVM call argument requires its declared type and storage; use an explicit conversion", node)
    collection_ops.require_matching_layout(actual, expected, node)
    left, right = tuple((actual.generic_types or {}).values()), tuple((expected.generic_types or {}).values())
    if actual.generic_name == expected.generic_name == "tuple" and (actual.tuple_variadic or expected.tuple_variadic):
        pairs = ((a, b) for a in left for b in right)
    else:
        pairs = zip(left, right, strict=False)
    # Immutable tuple slots can expose an existing derived object through its
    # base layout. A mutable enclosing alias must retain invariance, even when
    # one of its own members is immutable. No member boxing/adaptation occurs.
    covariant = (not member or allow_subclass) and collection_ops.builtin_name(actual) in {"tuple", "frozenset"}
    for a, b in pairs:
        validate_storage(emitter, a, b, node, member=True, allow_subclass=covariant)


class ExpandedCall:
    """Collect arguments in Python order into typed, temporarily rooted slots."""

    def __init__(self, emitter, target, node, *, vararg_type=None, runtime_errors=False, project_argument=None):
        self.emitter, self.target, self.node = emitter, target, node
        self.runtime_errors = runtime_errors
        self.project_argument = project_argument
        self.fixed = (*target.params, *target.kwonlyargs)
        self.slots = {parameter.arg: self.slot(emitter.annotation(parameter.annotation))
                      for parameter in self.fixed}
        self.positional = {parameter.arg: self.slot("i1") for parameter in self.fixed}
        self.named = {parameter.arg: self.slot("i1") for parameter in self.fixed}
        self.count = self.slot("i64")
        self.unexpected = self.slot("i1")
        # A checked projector also needs deferred rejection on an exact target:
        # consume the remaining operands before rejecting an erased payload.
        self.incompatible = self.slot("i1") if runtime_errors or project_argument is not None else None
        self.packs = {parameter.arg: self.slot("ptr") for parameter in (target.vararg, target.kwarg)
                      if parameter is not None}
        self.seen_slot = self.slot("ptr")
        roots = [tagged.root_slot(emitter, emitter.annotation(p.annotation), self.slots[p.arg])
                 for p in self.fixed if emitter.annotation(p.annotation) in {"ptr", tagged.STORAGE}]
        roots.extend((*self.packs.values(), self.seen_slot))
        self.frame = push_roots(emitter, roots)
        self.text = NATIVE_ENVIRONMENT.builtins.search("str")
        boolean = NATIVE_ENVIRONMENT.builtins.search("bool")
        self.seen = collection_ops.new_mapping(emitter, self.text, boolean)
        emitter.emit_line(f"store ptr {self.seen}, ptr {self.seen_slot}")
        if target.vararg is not None:
            self.vararg_type = vararg_type or collection_ops.item_type(target.vararg.annotation.obj)
            self.vararg = collection_ops.new_list(emitter, self.vararg_type)
            emitter.emit_line(f"store ptr {self.vararg}, ptr {self.packs[target.vararg.arg]}")
        if target.kwarg is not None:
            _, self.kwarg_type = emitter.dictionary_types(target.kwarg.annotation.obj)
            self.kwarg = collection_ops.new_mapping(emitter, self.text, self.kwarg_type)
            emitter.emit_line(f"store ptr {self.kwarg}, ptr {self.packs[target.kwarg.arg]}")
        self.static_position = 0
        self.minimum_position = 0

    def slot(self, kind):
        if kind == "void":
            raise LLVMUnsupported("expanded calls cannot bind None-valued parameters yet", self.node)
        result = self.emitter.emit_value(f"alloca {kind}")
        self.emitter.emit_line(f"store {kind} zeroinitializer, ptr {result}")
        return result

    def convert(self, actual, representation, expected, declared, value):
        if self.project_argument is not None:
            result = self.project_argument(actual, expected, value,
                lambda: self.emitter.emit_line(f"store i1 true, ptr {self.incompatible}"))
            if result is not None:
                return result
        try:
            if (representation != declared and not nullable.is_object(expected)
                    and not generator_representation_compatible(actual, expected, representation, declared)):
                raise LLVMUnsupported("expanded call items require matching parameter representations", self.node)
            validate_storage(self.emitter, actual, expected, self.node)
        except LLVMUnsupported:
            if not self.runtime_errors:
                raise
            # A runtime-selected signature can reject an otherwise valid base
            # call. Continue evaluating all caller operands before reporting it;
            # duplicate/missing argument errors also take precedence. Never
            # reinterpret the incompatible payload in the destination slot.
            self.emitter.emit_line(f"store i1 true, ptr {self.incompatible}")
            return self.emitter.value_type(expected), "zeroinitializer"
        kind = self.emitter.value_type(actual)
        # Expanded items need the same concrete provenance as AST expressions
        # when they are packed into a tagged argument slot.
        self.emitter.value_semantics[kind, value] = actual
        self.emitter.value_representations[kind, value] = representation
        return self.emitter.coerce_value(kind, value, self.emitter.value_type(expected), self.node,
                                         semantic=expected, representation=declared)

    def store(self, parameter, actual, representation, value, *, named=False):
        kind, value = self.convert(actual, representation, parameter.annotation.obj,
                                   analyzed_representation(parameter), value)
        self.emitter.emit_line(f"store {kind} {value}, ptr {self.slots[parameter.arg]}")
        flags = self.named if named else self.positional
        self.emitter.emit_line(f"store i1 true, ptr {flags[parameter.arg]}")

    @staticmethod
    def member_representation(parameter, index):
        representation = analyzed_representation(parameter)
        return representation.arguments[index] if representation is not None and representation.arguments else None

    def positional_item(self, actual, value, representation=None, *, repeated=False):
        emitter = self.emitter
        count = emitter.emit_value(f"load i64, ptr {self.count}")
        done = emitter.new_label("bind.positional.done")
        candidates = range(self.minimum_position, len(self.target.params))
        if self.static_position is not None:
            candidates = (self.static_position,) if self.static_position < len(self.target.params) else ()
        for index in candidates:
            take, skip = emitter.new_label("bind.positional.take"), emitter.new_label("bind.positional.skip")
            matches = emitter.emit_value(f"icmp eq i64 {count}, {index}")
            emitter.emit_line(f"br i1 {matches}, label %{take}, label %{skip}")
            emitter.emit_line(f"{take}:")
            self.store(self.target.params[index], actual, representation, value)
            emitter.emit_line(f"br label %{done}")
            emitter.emit_line(f"{skip}:")
        if self.target.vararg is not None and (self.static_position is None or self.static_position >= len(self.target.params)):
            _, converted = self.convert(actual, representation, self.vararg_type,
                                        self.member_representation(self.target.vararg, 0), value)
            collection_ops.append(emitter, self.vararg, self.vararg_type, self.vararg_type, converted, self.node)
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")
        following = emitter.emit_value(f"add i64 {count}, 1")
        emitter.emit_line(f"store i64 {following}, ptr {self.count}")
        if self.static_position is not None:
            self.static_position += 1
        if not repeated:
            self.minimum_position += 1

    def keyword_item(self, key, actual, value, representation=None, *, name=None):
        emitter = self.emitter
        key_pointer, key_size = emitter.dictionary_key_pointer(self.text, "ptr", key, self.node)
        previous = emitter.emit_value(f"call ptr @pyjs.dict.lookup(ptr {self.seen}, ptr {key_pointer}, "
                                      f"i64 {key_size}, i64 1, i8 {emitter.dictionary_key_kind(self.text)})")
        fresh = emitter.emit_value(f"icmp eq ptr {previous}, null")
        emitter.guard_exception(self.node, fresh, "TypeError", "multiple values for keyword argument")
        slot = emitter.dictionary_set_slot(self.seen, self.text, "ptr", key, "1", self.node)
        emitter.emit_line(f"store i1 true, ptr {slot}")
        done = emitter.new_label("bind.keyword.done")
        accepted = (*self.target.params[self.target.posonly_count:], *self.target.kwonlyargs)
        for parameter in accepted:
            if name is not None and name != parameter.arg:
                continue
            take, skip = emitter.new_label("bind.keyword.take"), emitter.new_label("bind.keyword.skip")
            expected = f"@{emitter.string_constant(parameter.arg)}"
            matches = emitter.emit_value(f"call i1 @pyjs.string.equal(ptr {key}, ptr {expected})")
            emitter.emit_line(f"br i1 {matches}, label %{take}, label %{skip}")
            emitter.emit_line(f"{take}:")
            self.store(parameter, actual, representation, value, named=True)
            emitter.emit_line(f"br label %{done}")
            emitter.emit_line(f"{skip}:")
        if name is not None and any(parameter.arg == name for parameter in accepted):
            pass
        elif self.target.kwarg is not None:
            kind, converted = self.convert(actual, representation, self.kwarg_type,
                                          self.member_representation(self.target.kwarg, 1), value)
            slot = emitter.dictionary_set_slot(self.kwarg, self.text, "ptr", key, emitter.llvm_size(kind), self.node)
            emitter.emit_line(f"store {kind} {converted}, ptr {slot}")
        else:
            emitter.emit_line(f"store i1 true, ptr {self.unexpected}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")

    def expand_positional(self, source, value):
        value_type = analyzed_value_type(source)
        representation = analyzed_representation(source)
        if isinstance(value_type, UnionType):
            # The source was evaluated before keyword operands, but a lone
            # *source is consumed afterward. Dispatch that saved value without
            # evaluating it again or materializing a snapshot prematurely.
            initial = self.static_position, self.minimum_position
            positions = []

            def expand(member, kind, item):
                self.static_position, self.minimum_position = initial
                selected = tagged.Value(source, member, kind, item)
                set_analyzed_representation(selected, representation_for_member(value_type, representation, member))
                self.expand_positional(selected, item)
                positions.append((self.static_position, self.minimum_position))

            tagged.dispatch(self.emitter, value_type, value, "void", expand)
            # Compile-time binding proofs belong to each arm. Only their
            # common position/lower bound survives at the following argument.
            self.static_position = positions[0][0] if all(p[0] == positions[0][0] for p in positions) else None
            self.minimum_position = min(p[1] for p in positions)
            return
        if collection_ops.builtin_name(value_type) == "tuple" and not value_type.tuple_variadic and (
            collection_ops.sequence_name(value_type) == "tuple" or isinstance(source, CollectionNew)
        ):
            for index, (actual, item) in enumerate(collection_ops.tuple_items(self.emitter, value_type, value)):
                member = representation.arguments[index] if representation is not None and representation.arguments else None
                self.positional_item(actual, item, member)
        else:
            self.static_position = None
            protocol = analyzed_iterable_protocol(source)
            # ItemsView has K/V fields; its iterator yields one represented
            # tuple. All iterable consumers must use that item contract.
            member = protocol.item_representation
            if protocol.representation_conflict:
                raise LLVMUnsupported("expanded tuple items require a uniform representation", self.node)
            collection_ops.loop(self.emitter, value_type, value,
                                lambda actual, item: self.positional_item(actual, item, member, repeated=True), self.node)

    def bind(self, *, load_default=None):
        emitter, target, node = self.emitter, self.target, self.node
        # CALL_FUNCTION_EX materializes a lone *source after keyword merging.
        # BUILD_LIST/LIST_EXTEND materializes each source immediately when
        # there are additional positional operands. Mutation makes this visible.
        deferred = None
        for argument in node.args:
            if isinstance(argument, ast.Starred):
                if (isinstance(argument.value, CollectionNew)
                        and isinstance(argument.value.source, (ast.List, ast.Tuple))
                        and not argument.value.source.elts):
                    continue
                value = emitter.expression(argument.value)[1]
                if len(node.args) == 1:
                    deferred = argument.value, value
                else:
                    self.expand_positional(argument.value, value)
            else:
                self.positional_item(analyzed_value_type(argument), emitter.expression(argument)[1],
                                     analyzed_representation(argument))
        index = 0
        while index < len(node.keywords):
            keyword = node.keywords[index]
            if keyword.arg is not None:
                batch = []
                while index < len(node.keywords) and node.keywords[index].arg is not None:
                    item = node.keywords[index]
                    batch.append((item, emitter.expression(item.value)[1]))
                    index += 1
                for item, value in batch:
                    self.keyword_item(f"@{emitter.string_constant(item.arg)}", analyzed_value_type(item.value), value,
                                      analyzed_representation(item.value), name=item.arg)
                continue
            value_type = analyzed_value_type(keyword.value)
            literal = keyword.value.source if isinstance(keyword.value, CollectionNew) else None
            if isinstance(literal, ast.Dict) and all(isinstance(key, ast.Constant) and isinstance(key.value, str)
                                                     for key in literal.keys):
                # A literal dictionary evaluates all values and keeps the last
                # value for repeated keys before ** merges it with prior names.
                batch = {}
                for key, item in zip(literal.keys, literal.values, strict=True):
                    batch[key.value] = item, emitter.expression(item)[1]
                for name, (item, value) in batch.items():
                    self.keyword_item(f"@{emitter.string_constant(name)}", analyzed_value_type(item), value,
                                      analyzed_representation(item), name=name)
                index += 1
                continue
            if value_type.generic_name != "dict" or value_type.generic_types["K"].generic_name != "str":
                raise LLVMUnsupported("LLVM ** expansion requires a concrete string-keyed dict", keyword.value)
            source = emitter.expression(keyword.value)[1]
            member = value_type.generic_types["V"]
            representation = self.member_representation(keyword.value, 1)

            def visit(key_type, key, source=source, value_type=value_type, member=member, representation=representation):
                slot, kind = emitter.dictionary_lookup(source, value_type, "ptr", key, node,
                                                        source_type=key_type)
                value = emitter.emit_value(f"load {kind}, ptr {slot}")
                self.keyword_item(key, member, value, representation)

            collection_ops.loop(emitter, value_type, source, visit, node)
            index += 1
        if deferred is not None:
            self.expand_positional(*deferred)
        for parameter in self.fixed:
            positional = emitter.emit_value(f"load i1, ptr {self.positional[parameter.arg]}")
            named = emitter.emit_value(f"load i1, ptr {self.named[parameter.arg]}")
            duplicate = emitter.emit_value(f"and i1 {positional}, {named}")
            emitter.guard_exception(node, emitter.emit_value(f"xor i1 {duplicate}, true"),
                                    "TypeError", f"multiple values for argument '{parameter.arg}'")
        unexpected = emitter.emit_value(f"load i1, ptr {self.unexpected}")
        emitter.guard_exception(node, emitter.emit_value(f"xor i1 {unexpected}, true"),
                                "TypeError", "unexpected keyword argument")
        if target.vararg is None:
            count = emitter.emit_value(f"load i64, ptr {self.count}")
            emitter.guard_exception(node, emitter.emit_value(f"icmp ule i64 {count}, {len(target.params)}"),
                                    "TypeError", "too many positional arguments")
        defaults = dict(parameter_defaults(target))
        for parameter in self.fixed:
            positional = emitter.emit_value(f"load i1, ptr {self.positional[parameter.arg]}")
            named = emitter.emit_value(f"load i1, ptr {self.named[parameter.arg]}")
            present = emitter.emit_value(f"or i1 {positional}, {named}")
            default = defaults.get(parameter)
            if default is None:
                emitter.guard_exception(node, present, "TypeError", f"missing required argument '{parameter.arg}'")
        if self.incompatible is not None:
            invalid = emitter.emit_value(f"load i1, ptr {self.incompatible}")
            emitter.guard_exception(node, emitter.emit_value(f"xor i1 {invalid}, true"),
                                    "TypeError", "selected method argument has incompatible native type")
        for parameter, default in defaults.items():
            if default is not None:
                positional = emitter.emit_value(f"load i1, ptr {self.positional[parameter.arg]}")
                named = emitter.emit_value(f"load i1, ptr {self.named[parameter.arg]}")
                present = emitter.emit_value(f"or i1 {positional}, {named}")
                use, done = emitter.new_label("bind.default"), emitter.new_label("bind.default.done")
                emitter.emit_line(f"br i1 {present}, label %{done}, label %{use}")
                emitter.emit_line(f"{use}:")
                if load_default is None:
                    kind, value = default_value(emitter, target, parameter.arg, default, node)
                    kind, value = emitter.coerce_value(kind, value, emitter.annotation(parameter.annotation), default,
                                                      semantic=parameter.annotation.obj)
                else:
                    # Selected defaults already have the parameter's storage.
                    # Reusing the base default AST here would mislabel boxed SSA
                    # values with that literal's original, unboxed type.
                    kind, value = load_default(parameter)
                emitter.emit_line(f"store {kind} {value}, ptr {self.slots[parameter.arg]}")
                emitter.emit_line(f"br label %{done}")
                emitter.emit_line(f"{done}:")
        values = [(emitter.annotation(parameter.annotation), emitter.emit_value(
            f"load {emitter.annotation(parameter.annotation)}, ptr {self.slots.get(parameter.arg, self.packs.get(parameter.arg))}"))
            for parameter in parameters(target)]
        for parameter, (kind, value) in zip(parameters(target), values, strict=True):
            emitter.value_semantics[kind, value] = parameter.annotation.obj
            emitter.value_representations[kind, value] = analyzed_representation(parameter)
        return BoundCall(values, [None] * len(values), emitter, self.frame)


def opaque_iterable_signature(emitter, target, node, semantic, representation):
    """Instantiate an opaque iterable boundary, not the generic function body.

    The body can retain/forward a cursor without knowing its item layout. Item
    reads still require a concrete T and fail through ordinary value lowering.
    Callers adapt to the inferred item ABI before passing the opaque handle.
    """
    if (isinstance(target, Function) and target in emitter.module.functions
            and target.cls is None and target.type_parameters and not target.overloads
            and collection_ops.builtin_name(semantic) in {"Iterator", "Iterable"}
            and isinstance(item := collection_ops.item_type(semantic), TypeVariableClass)):
        bindings = getattr(node, "type_bindings", {})
        if item not in bindings:
            raise LLVMUnsupported("LLVM generic iterable boundaries require a direct, inferred call", node)
        return (substitute_type_variables(semantic, bindings),
                substitute_representation_variables(semantic, representation,
                                                     getattr(node, "representation_bindings", {})))
    return semantic, representation


def convert(emitter, target, arguments, node, *, box=False, roots=None):
    expected = parameters(target)
    if len(expected) != len(arguments.values):
        raise LLVMUnsupported(f"LLVM call to {target.name} has incompatible arguments", node)
    # Compiler-bound arguments have storage/SSA metadata but no expression.
    # Keep the call location for diagnostics without borrowing its result type
    # as the argument's type (notably borrowed __exit__ exception pointers).
    origin = ast.copy_location(ast.expr(), node) if node is not None else None
    result = []
    for index, (parameter, (kind, value), source) in enumerate(zip(expected, arguments.values, arguments.sources, strict=True)):
        # Storage narrowing is not Python coercion. Any semantic conversion
        # must already be explicit in the analyzed expression, including for
        # native declarations; annotations alone do not cast Python values.
        expected_type, expected_representation = opaque_iterable_signature(
            emitter, target, node, parameter.annotation.obj, analyzed_representation(parameter))
        semantic = emitter.annotation(parameter.annotation)
        kind, value = emitter.coerce_value(kind, value, semantic, source if source is not None else origin,
                                           semantic=expected_type if box else None,
                                           representation=expected_representation)
        if roots is not None and index in roots:
            emitter.emit_line(f"store ptr {value}, ptr {roots[index]}")
        if source is not None:
            collection_ops.require_matching_layout(emitter.runtime_value_type(source), expected_type, source)
        storage = emitter.annotation_storage_type(parameter.annotation, analyzed_numeric_format(parameter))
        result.append(emitter.narrow_numeric(kind, value, storage, node))
    return result


def checked(emitter, return_type, return_numeric, implementation, arguments, node, *, check=True):
    storage = emitter.result_storage_type(return_type, return_numeric)
    rendered = ", ".join(f"{kind} {value}" for kind, value in arguments)
    instruction = f"call {storage} {implementation}({rendered})"
    if storage == "void":
        emitter.emit_line(instruction)
        result = None
    else:
        result = emitter.emit_value(instruction)
    if check:
        emitter.check_active_exception(node)
    if result is None:
        return "void", ""
    return emitter.widen_numeric(storage, result, return_numeric)


def invoke(emitter, target, arguments, node=None, *, receiver=None, implementation=None):
    helper = emitter.is_runtime_helper(target)
    if helper:
        emitter.runtime_helper_calls.add(emitter.function_name(target))
    values = [] if helper else emitter.context_arguments()
    if target.cls in emitter.module.classes and not target.is_static:
        if receiver is None:
            raise LLVMUnsupported(f"LLVM call to {target.name} is missing its receiver", node)
        values.append(("ptr", receiver))
    # Boxing is itself an allocation. Root each converted object parameter
    # before converting the next, and retain it through the checked call.
    roots, frame = object_argument_roots(emitter, (parameter.annotation.obj for parameter in parameters(target)))
    values.extend(convert(emitter, target, arguments, node, box=True, roots=roots))
    result = checked(emitter, target.return_type, target.return_numeric_format,
                     implementation or f"@{emitter.function_name(target)}", values, node, check=not helper)
    from . import binary
    binary.check_result(emitter, target, result, node)
    pop_roots(emitter, frame)
    return result


def project_result(e, target, value_type, value, node, *, check_layout=True):
    """Validate and adapt a body's result before its selected call-site use."""
    known = target in e.module.functions or isinstance(target, CallableClass)
    semantic = target.return_type if known else None
    representation = target.return_representation if known else None
    if known and isinstance(target, Function):
        semantic, representation = opaque_iterable_signature(e, target, node, semantic, representation)
        if (collection_ops.builtin_name(analyzed_value_type(node)) == "Generator"
                and (signature := getattr(target, "native_generator_signature", None))):
            # Recover the concrete frame only for a Generator consumer. Ordinary
            # Iterator calls must still check their public item representation;
            # changing the outer type would hide incompatible overload formats.
            semantic, representation = signature
    return project_value(e, semantic, representation,
                         value_type, value, node, check_layout=check_layout)


def project_value(e, actual, representation, value_type, value, node, *,
                  check_layout=True, description="call result"):
    """Check a stored ABI value before exposing a narrower compiler-known view.

    Overload results and captured callback inputs share the same tag, presence,
    representation and nominal-class checks. This does not retype stored data.
    """
    from . import callable_adapters, object_values

    expected = analyzed_value_type(node)
    known = actual is not None
    if known and nullable.is_object(expected):
        # Erasure keeps a reference's own payload layout/representation inside
        # its box; it does not require that metadata to match plain object.
        # This also handles None. Do not subsequently run an optional-to-concrete
        # presence check on the successfully boxed result. Scalar representation
        # erasure remains rejected by the ordinary boxing boundary.
        e.value_semantics[value_type, value] = actual
        e.value_representations[value_type, value] = representation
        return e.coerce_value(value_type, value, "ptr", node, semantic=expected)
    if known and (
            not same_analyzer_type(actual, expected)
            or representation != analyzed_representation(node)):
        # Narrowing cannot reinterpret an existing payload,
        # whether its stored ABI uses a tag, optional or pointer.
        # Check each arm: optional targets unwrap to a concrete layout.
        for member in get_type_members(actual):
            # None has no payload to reinterpret, including optional
            # callable results; tag/presence checks own that arm.
            if collection_ops.builtin_name(member) != "NoneType" and collection_ops.builtin_name(expected) != "NoneType":
                # A callable crosses a direct value boundary here, not an
                # aliased container slot. Compatible signatures use the same
                # adapter as an ordinary assignment below; never just relabel
                # their code pointer with the destination calling convention.
                adapt = callable_adapters.compatible(member, nullable.member(expected) or expected)
                collection_ops.require_matching_layout(member, expected, node, adapt_value=adapt)
        if representations_conflict(((actual, representation),
                                     (expected, analyzed_representation(node)))):
            raise LLVMUnsupported(f"LLVM {description} projection requires matching representations", node)
        concrete = nullable.member(actual) or actual
        selected = nullable.member(expected) or expected
        if (value_type != tagged.STORAGE and not nullable.is_object(actual)
                and not is_return_type_compatible(expected, concrete)):
            if (selected in e.module.classes and concrete in e.module.classes
                    and collection_ops.is_layout_subclass(selected, concrete)):
                # A shared application hierarchy has runtime identity;
                # overloads and Self may select a subclass of the body's
                # return declaration. Check before exposing its fields.
                valid = nullable.instancecheck(e, actual, value_type, value, selected, node)
                if nullable.member(expected):
                    absent = e.emit_value(f"xor i1 {nullable.present(e, value_type, value)}, true")
                    valid = e.emit_value(f"or i1 {valid}, {absent}")
                e.guard_exception(node, valid, "TypeError", f"{description} has a different runtime class")
            elif not (collection_ops.builtin_name(expected) == "NoneType"
                      and nullable.member(actual)):
                # Optional-to-None has a presence check below. Other
                # unrelated untagged kinds cannot prove their payload.
                raise LLVMUnsupported(f"LLVM {description} projection requires compatible concrete types", node)
        # The stored ABI is independent of this expression's proof.
        # Preserve its source semantics while constructing
        # tagged/erased/optional transport; labelling the old SSA
        # value with the selected type would reinterpret its bits.
        e.value_semantics[value_type, value] = actual
        e.value_representations[value_type, value] = representation
        if (not nullable.is_object(actual)
                and value_type != tagged.STORAGE and (
                    e.expression_type(node) == tagged.STORAGE or nullable.member(expected)
                    or not nullable.member(actual))):
            value_type, value = e.coerce_value(
                value_type, value, e.expression_type(node), node, semantic=expected)
    if (known and nullable.is_object(actual)
            and object_values.needs_result_check(actual, expected)):
        value_type, value = object_values.narrow(e, value, expected, node, check_layout=check_layout)
    # An overload narrows the static result, not the implementation's
    # union return ABI. Check its tag/presence before exposing the
    # payload, including direct consumers without an intervening local.
    if value_type == tagged.STORAGE and (not isinstance(expected, UnionType)
            or known and (
                not same_analyzer_type(actual, expected)
                or representation != analyzed_representation(node))):
        if isinstance(expected, UnionType) and nullable.is_object(expected):
            raise LLVMUnsupported("LLVM union result projection requires closed union storage", node)
        value_type, value = tagged.narrow(e, value, expected, node)
    elif not isinstance(expected, UnionType) and (nullable.payload_kind(value_type) or known
          and nullable.member(actual)):
        nullable.check_narrowing(e, value_type, value, expected, node, description)
        value_type, value = (("void", "") if expected.generic_name == "NoneType" else
                            e.coerce_value(value_type, value, e.value_type(expected), node))
    return value_type, value


def join_result(e, target, kind, value, node):
    """Project one runtime-selected body before joining its call-site result."""
    kind, value = project_result(e, target, kind, value, node)
    expected = analyzed_value_type(node)
    e.value_semantics[kind, value] = expected if target in e.module.functions else target.return_type
    e.value_representations[kind, value] = (
        analyzed_representation(node) if target in e.module.functions else target.return_representation)
    # Equal pointer layouts do not imply equal Python representations: a typed
    # reference joining an object arm still needs its erased box.
    return e.coerce_value(kind, value, e.expression_type(node), node, semantic=expected)


def static_receiver(node, functions):
    """Return an instance receiver whose static declaration can be overridden."""
    from .object_values import instance_type
    reference = node.func if isinstance(node, ast.Call) else node
    if not isinstance(reference, ast.Attribute):
        return None
    target = getattr(reference, "obj", None)
    if (not isinstance(target, Function) or target not in functions or target.cls is None
            or not target.is_staticmethod or getattr(reference, "union_functions", ())):
        return None
    source = reference.value
    semantic = instance_type(source)
    if semantic is None:
        return None  # A class-qualified call selects that declaration.
    if super_proxy.is_receiver(source):
        return None  # super() selects a lexical base, not the runtime override.
    return semantic


def implicit_method(semantic, name, node=None):
    # Inspect without invoking descriptors or reading instance fields. An
    # unmodeled callable is an unsupported boundary, not a non-callable value.
    declaration = inspect.getattr_static(semantic.py_obj, name, None)
    if method := declared_protocol_method(semantic, name, declaration):
        return method
    if callable(declaration) or hasattr(type(declaration), "__get__"):
        raise LLVMUnsupported(f"native {name} requires a modeled class method; "
                              "callable aliases and descriptors are unsupported", node)
    return None


def class_instance(e, node, semantic):
    """Class-selected methods, including implicit protocols and static methods.

    Select the runtime class before binding defaults. Unlike an ordinary virtual
    slot, a special method may be explicitly disabled in a reached subclass.
    """
    _, receiver = e.expression(node.func.value)
    kind = e.expression_type(node)
    implicit = getattr(node.func, "class_lookup", False)
    if not implicit and node.func.attr == "__hash__":
        from .hashing import guard_disabled_method
        # Static declarations still use instance attribute lookup. A disabled
        # runtime subclass must not fall back to the analyzed ancestor body.
        node = guard_disabled_method(e, semantic, receiver, node, dynamic=True)

    def select(candidate):
        return (implicit_method(candidate, node.func.attr, node) if implicit else
                candidate.find_attrs(node.func.attr))

    if implicit and node.func.attr == "__call__":
        # Direct object calls use the ordinary method ABI, not a callback
        # descriptor. Refuse disabled/static overrides rather than silently
        # calling the inherited vtable slot. Binding stays outside dispatch so
        # nested caller expressions are emitted once, including expanded packs.
        methods = protocol_groups(e, semantic, select, compatible=collection_ops.is_layout_subclass)
        if not methods or any(not isinstance(method, Function) or method.is_static
                              or method.is_property or method not in e.module.functions for method in methods):
            raise LLVMUnsupported("LLVM callable objects require ordinary instance __call__ methods "
                                  "throughout the reached hierarchy", node)
        target = node.func.obj
        actual, value = bind_method(e, target, receiver, node, semantic=semantic)
        return project_result(e, target, actual, value, node)

    def invoke_member(target, receiver=receiver):
        if not isinstance(target, Function) and implicit:
            e.guard_exception(node, "false", "TypeError", f"{node.func.attr} is not callable")
            return "zeroinitializer"
        if (not isinstance(target, Function) or target.is_classmethod or target.is_property
                or target not in e.module.functions):
            raise LLVMUnsupported("LLVM class-selected dispatch requires reached instance or static methods", node)
        with bind(e, target, node) as arguments:
            actual, value = invoke(e, target, arguments, node, receiver=receiver)
        return join_result(e, target, actual, value, node)[1]

    if tagged.members(semantic):
        value = tagged.dispatch(e, semantic, receiver, kind,
            lambda member, storage, payload: invoke_member(select(member), payload),
            runtime_classes=True)
    else:
        value = runtime_protocol(e, semantic, receiver, kind,
            select, invoke_member, node,
            compatible=collection_ops.is_layout_subclass)
    return kind, value if kind != "void" else ""


def vtable_slot(emitter, table, root, index):
    # One ancestry pointer precedes the method region. Its one-past-last index
    # is the runtime class tag. Keep all dispatch/tag consumers on this layout.
    return f"getelementptr %{emitter.vtable_type(root)}, ptr {table}, i32 0, i32 {index + 1}"


def virtual(emitter, target, receiver, arguments, node):
    root, index = emitter.module.virtual_methods[target]
    if (root, index) in emitter.module.rebound_virtual_slots:
        # Protocol consumers (__iter__/__next__/__exit__) supply evaluated
        # positional operands directly, rather than going through bind_method.
        # They must not call a nonuniform raw vtable slot either.
        sources = []
        for parameter, (kind, value) in zip(parameters(target), arguments.values, strict=False):
            source = tagged.Value(node, parameter.annotation.obj, kind, value)
            source.representation = analyzed_representation(parameter)
            sources.append(source)
        call = ast.copy_location(ast.Call(func=ast.Name(id=target.name, ctx=ast.Load()),
                                         args=sources, keywords=[]), node)
        call.obj = target.return_type
        return bind_selected_method(emitter, target, receiver, call, semantic=target.cls)
    if (root, index) in emitter.module.adapted_virtual_slots:
        from .properties import dispatch_name

        # Raw slots retain each body's actual ABI. For covariant returns with
        # different storage, select that body before calling and convert its
        # result to the static declaration. Ordinary uniform slots stay direct.
        kind = emitter.value_type(target.return_type)
        view = tagged.Value(node, target.return_type, kind, "")
        view.representation = target.return_representation

        def selected(implementation):
            actual, value = invoke(emitter, implementation, arguments, node, receiver=receiver)
            actual, value = project_result(emitter, implementation, actual, value, view)
            return emitter.coerce_value(actual, value, kind, view, semantic=target.return_type)[1]

        value = runtime_protocol(emitter, target.cls, receiver, kind,
            lambda candidate: emitter.resolve_method(candidate, dispatch_name(target)), selected, node,
            compatible=collection_ops.is_layout_subclass)
        emitter.value_semantics[kind, value] = target.return_type
        emitter.value_representations[kind, value] = target.return_representation
        return kind, value if kind != "void" else ""
    vtable = emitter.emit_value(f"load ptr, ptr {receiver}")
    slot = emitter.emit_value(vtable_slot(emitter, vtable, root, index))
    implementation = emitter.emit_value(f"load ptr, ptr {slot}")
    return invoke(emitter, target, arguments, node, receiver=receiver, implementation=implementation)


def bind_method(e, target, receiver, node, *, semantic, positional=None, dynamic=True):
    """Bind caller operands once, retaining the uniform-signature fast path.

    Nonuniform signatures use selected binding. Uniform calls, properties and
    formatting share the default loader below. Binding base
    defaults and only then selecting an override would initialize the wrong
    persistent objects. Conversely, binding the entire call inside each override
    arm duplicates caller subtrees exponentially for nested virtual calls.
    The ordinary binder owns argument ordering, expansion and roots; a selected
    default loader owns only the omitted values. Invocation stays on the vtable.
    """
    from . import dom_ops

    if target.name == "__hash__" and semantic in e.module.classes:
        from .hashing import guard_disabled_method
        captured = guard_disabled_method(e, semantic, receiver, node,
                                         dynamic=dynamic, positional=positional)
        if captured is not node:
            node, positional = captured, None

    virtual_target = dynamic and target in e.module.virtual_methods
    if virtual_target and e.module.virtual_methods[target] in e.module.rebound_virtual_slots:
        return bind_selected_method(e, target, receiver, node, semantic=semantic, positional=positional)
    load_default = None
    default_frame = None
    if virtual_target and (target.defaults or target.kwonlyargs):
        from .properties import dispatch_name

        # A selected object default can be boxed before another default or pack
        # allocates. Allocate these roots outside expanded-call presence branches
        # so the frame is balanced whether an argument is supplied or omitted.
        roots, default_frame = object_argument_roots(e, (item.annotation.obj for item in parameters(target)))
        default_roots = {parameters(target)[index].arg: slot for index, slot in roots.items()}

        def load_default(parameter):
            kind = e.annotation(parameter.annotation)

            def selected(implementation):
                value_node = next(value for item, value in parameter_defaults(implementation)
                                  if item.arg == parameter.arg)
                actual, value = default_value(e, implementation, parameter.arg, value_node, node)
                return e.coerce_value(actual, value, kind, value_node, semantic=parameter.annotation.obj)[1]

            value = runtime_protocol(e, semantic, receiver, kind,
                lambda candidate: e.resolve_method(candidate, dispatch_name(target)), selected, node,
                compatible=collection_ops.is_layout_subclass)
            e.value_semantics[kind, value] = parameter.annotation.obj
            e.value_representations[kind, value] = analyzed_representation(parameter)
            if parameter.arg in default_roots:
                e.emit_line(f"store ptr {value}, ptr {default_roots[parameter.arg]}")
            return kind, value

    with bind(e, target, node, positional=positional, load_default=load_default,
              project_argument=dom_ops.child_argument_projector(e, target, node)) as arguments:
        result = (virtual(e, target, receiver, arguments, node) if virtual_target else
                  invoke(e, target, arguments, node, receiver=receiver))
    pop_roots(e, default_frame)
    return result


def capture_operands(e, node, positional=None):
    """Save caller subtrees once before selecting a method implementation.

    Expanded operands are already saved by NativeExpressionLowering, including
    mixed-star materialization and keyword-group snapshots. Ordinary expression
    roots retain pointers/unions across later operands, defaults and binding.
    """
    if expands_arguments(node):
        return node

    def capture(source, value=None):
        kind, value = e.expression(source) if value is None else value
        saved = tagged.Value(source, e.runtime_value_type(source), kind, value)
        saved.representation = analyzed_representation(source)
        return saved

    captured = ast.Call(func=node.func, args=[], keywords=[])
    captured.__dict__.update(vars(node))
    captured.obj = analyzed_value_type(node)
    captured.args = [capture(source, positional[index] if positional is not None else None)
                     for index, source in enumerate(node.args)]
    captured.keywords = [ast.keyword(arg=item.arg, value=capture(item.value)) for item in node.keywords]
    return captured


def bind_selected_method(e, target, receiver, node, *, semantic, positional=None):
    """Bind a nonuniform override before entering its concrete call ABI."""
    from . import dom_ops
    from .properties import dispatch_name

    captured = capture_operands(e, node, positional)
    if captured is not node:
        positional = None
    kind = e.value_type(target.return_type)
    view = tagged.Value(node, target.return_type, kind, "")
    view.representation = target.return_representation

    def selected(implementation):
        binding = bind(e, implementation, captured, positional=positional, runtime_errors=True,
                       project_argument=dom_ops.child_argument_projector(e, implementation, node))
        if binding is None:
            return "zeroinitializer" if kind != "void" else ""
        with binding as arguments:
            actual, value = invoke(e, implementation, arguments, node, receiver=receiver)
        actual, value = project_result(e, implementation, actual, value, view)
        return e.coerce_value(actual, value, kind, view, semantic=target.return_type)[1]

    value = runtime_protocol(e, semantic, receiver, kind,
        lambda candidate: e.resolve_method(candidate, dispatch_name(target)), selected, node,
        compatible=collection_ops.is_layout_subclass)
    e.value_semantics[kind, value] = target.return_type
    e.value_representations[kind, value] = target.return_representation
    return kind, value if kind != "void" else ""


def protocol_groups(e, semantic, select, *, compatible=is_subclass):
    """Share implementation grouping between layout preparation and emission."""
    groups = {}
    for candidate in sorted(e.module.classes, key=e.class_name):
        if compatible(candidate, semantic):
            groups.setdefault(select(candidate), []).append(candidate)
    return groups


def runtime_protocol(e, semantic, receiver, kind, select, emit, node, *, identity=None, fallback=None,
                     compatible=is_subclass):
    """Select a protocol by concrete class, grouping identical implementations.

    Unlike a virtual method slot, a protocol may be absent or disabled on one
    class and introduced by a subclass. select/emit are compiler callbacks.
    Layout-bound protocols can supply nominal compatibility; ordinary numeric
    protocols keep analyzer covariance and their prepared identity headers.
    """
    groups = protocol_groups(e, semantic, select, compatible=compatible)
    if not groups and fallback is not None:
        return fallback()
    if len(groups) == 1 and fallback is None:
        return emit(next(iter(groups)))
    table = identity if identity is not None else e.emit_value(f"load ptr, ptr {receiver}")
    result = e.emit_value(f"alloca {kind}") if kind != "void" else None
    done = e.new_label("protocol.done")
    for implementation, classes in groups.items():
        matches = "false"
        for candidate in classes:
            equal = e.emit_value(f"icmp eq ptr {table}, @{e.vtable_name(candidate)}")
            matches = equal if matches == "false" else e.emit_value(f"or i1 {matches}, {equal}")
        selected, following = e.new_label("protocol.class"), e.new_label("protocol.next")
        e.emit_line(f"br i1 {matches}, label %{selected}, label %{following}")
        e.emit_line(f"{selected}:")
        value = emit(implementation)
        if result is not None:
            e.emit_line(f"store {kind} {value}, ptr {result}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{following}:")
    if fallback is None:
        e.guard_exception(node, "false", "TypeError", "unknown application runtime protocol")
    value = "zeroinitializer" if fallback is None else fallback()
    if result is not None:
        e.emit_line(f"store {kind} {value}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load {kind}, ptr {result}") if result is not None else None

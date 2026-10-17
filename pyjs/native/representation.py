"""Python representations over concrete native layouts and checked callbacks.

Types drive emission; values drive traversal. Erased edges outline checked
runtime dispatch while sharing the current output buffer and recursion scope.
"""

import ast

from pyjs.analysis.analyzer import analyzed_value_type, runtime_dunder_methods
from pyjs.analysis.objects import Class, Function, UnionType
from pyjs.analysis.type_relations import is_subclass

from . import calls, enum_ops, nullable, tagged
from . import collection_ops as collections
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .output_ops import Buffer
from .runtime import text


def method_scope(e, node):
    """Share checked recursion depth across __str__, __repr__ and __format__."""
    return calls.recursion_scope(e, node, "maximum recursion depth exceeded while formatting an object")


def methods(semantic, representation=True, seen=None):
    return tuple(method for receiver, names in protocols(semantic, representation, seen)
                 for method in runtime_dunder_methods(receiver, *names))


def protocols(semantic, representation=True, seen=None):
    """Retain formatting only for receivers reachable through this value."""
    seen = set() if seen is None else seen
    # The same type needs __str__ at the root and __repr__ inside a container.
    # A type-only key suppresses the nested callback through recursive edges.
    if (semantic, representation) in seen:
        return ()
    seen.add((semantic, representation))
    if isinstance(semantic, UnionType):
        members = semantic.types
        nested_representation = representation
    elif semantic.container.scope.is_builtins and semantic.generic_name in collections.CONTAINERS | collections.VIEWS:
        members = semantic.generic_types.values()
        nested_representation = True
    else:
        name = "__repr__" if representation else "__str__"
        method = semantic.find_attrs(name)
        if name == "__str__" and collections.builtin_name(getattr(method, "cls", None)) == "object":
            # Retain __str__ overrides too: the static base may inherit
            # object.__str__ while its runtime subclass supplies a method.
            return ((semantic, ("__str__", "__repr__")),)
        return ((semantic, (name,)),)
    return tuple(protocol for member in members for protocol in protocols(member, nested_representation, seen))


def argument(target, node):
    return (node.func.value if getattr(target, "cls", None) is not None and isinstance(node.func, ast.Attribute)
            else node.args[0] if node.args else None)


def requires_buffer(target, node, slots=None, functions=(), *, scope=None):
    """Do not make ordinary scalar str conversions pull in a managed formatter."""
    source = argument(target, node)
    if source is None:
        return False
    from .json_ops import reject_class_values
    reject_class_values(source, node, "repr")
    semantic = analyzed_value_type(source)
    if tagged.narrowed_integer(source, slots, functions, scope=scope):
        return True
    optional = nullable.member(semantic)
    if optional is not None and is_subclass(optional, NATIVE_ENVIRONMENT.builtins.search("BaseException")):
        raise LLVMUnsupported("narrow an optional exception before formatting its message", node)
    name = collections.builtin_name(semantic)
    if name in {"int", "float", "bool", "NoneType", "bytes"}:
        return False
    return name != "str" or target.name in {"repr", "__repr__"}


def empty_literal(source):
    source = getattr(source, "source", source)
    if isinstance(source, (ast.List, ast.Tuple)) and not source.elts:
        return "[]" if isinstance(source, ast.List) else "()"
    if isinstance(source, ast.Dict) and not source.keys:
        return "{}"
    return None


def render(e, semantic, kind, value, node, *, representation=True, outline=True):
    semantic = tagged.runtime_type(semantic)
    # Preserve scalar str's allocation-free identity and existing numeric
    # conversions. Containers/quoted strings need the growing output buffer.
    semantic = tagged.effective_type(semantic, kind)
    if outline and (nullable.member(semantic) or kind == tagged.STORAGE):
        # Share the entire root conversion, including its scalar fast paths.
        # Inlining each container/class arm here multiplies IR at every use.
        from . import erased_repr
        return "ptr", erased_repr.call(e, semantic, kind, value, representation, node, standalone=True)
    # Dispatch before constructing a buffer: None/bool stay allocation-free,
    # and str(str) preserves the existing string through optional/union views.
    # Nested container members still share their parent's Formatter below.
    if nullable.member(semantic):
        return "ptr", nullable.dispatch(e, semantic, kind, value, "ptr", "@" + e.string_constant("None"),
            lambda member, storage, item: render(e, member, storage, item, node, representation=representation)[1])
    if kind == tagged.STORAGE:
        return "ptr", tagged.dispatch(e, semantic, value, "ptr",
            lambda member, storage, item: render(e, member, storage, item, node, representation=representation)[1])
    if enum_ops.scalar_name(semantic):
        return "ptr", enum_ops.select(e, semantic, value, repr if representation else str)
    name = collections.builtin_name(semantic)
    if name == "str" and not representation:
        return "ptr", value
    if name in {"int", "float", "bool"}:
        return "ptr", getattr(e, "string_from_" + name)(value)
    if name == "NoneType":
        return "ptr", "@" + e.string_constant("None")
    if name == "NotImplementedType":
        return "ptr", "@" + e.string_constant("NotImplemented")
    if name == "bytes":
        return e.owned_text_call("pyjs.text.repr_bytes", [f"ptr {value}"])
    formatter = Formatter(e, node)
    roots = (value,) if kind == "ptr" else ()
    return "ptr", formatter.render(lambda: formatter.value(semantic, kind, value, representation), *roots)


class Formatter(Buffer):
    def default_object(self, semantic, value):
        e = self.e
        output = Buffer(e, self.node)

        def write():
            output.append(output.literal(f"<{semantic.name} object at "))
            address = e.emit_value(f"ptrtoint ptr {value} to i64")
            text = e.allocated_value(f"call ptr @pyjs.format.integer({collections.owner(e)}, "
                                     f"i64 {address}, i64 16, i64 0, i1 true, i1 false)")
            output.append(text)
            output.append(output.literal(">"))

        return output.render(write, value)

    def invoke_method(self, semantic, value, representation):
        e = self.e

        def resolve(cls):
            method = cls.find_attrs("__repr__" if representation else "__str__")
            if collections.builtin_name(getattr(method, "cls", None)) == "object" and not representation:
                method = cls.find_attrs("__repr__")
            if collections.builtin_name(getattr(method, "cls", None)) == "object":
                return cls  # Builtin object repr uses the runtime class name/address.
            if not isinstance(method, Function) or method not in e.module.functions:
                required = "__repr__" if representation else "__str__ or __repr__"
                raise LLVMUnsupported(f"LLVM {cls.name} formatting requires a reached explicit {required} method", self.node)
            if collections.builtin_name(method.return_type) != "str":
                raise LLVMUnsupported("LLVM representation methods must return str", self.node)
            return method

        empty_call = ast.copy_location(ast.Call(func=self.node.func, args=[], keywords=[]), self.node)

        def invoke(method):
            if isinstance(method, Class):
                return self.default_object(method, value)
            with calls.bind(e, method, empty_call) as bound:
                return calls.invoke(e, method, bound, self.node, receiver=value)[1]

        method = resolve(semantic)
        if isinstance(self.node.func, ast.Attribute) and e.is_super_call(self.node.func.value):
            target = self.node.func.obj
            if target in e.module.functions:
                return invoke(target)
            if target.name == "__repr__" and collections.builtin_name(target.cls) == "object":
                raise LLVMUnsupported("LLVM explicit object.__repr__ requires default object formatting", self.node)
            # Explicit object.__str__ still dispatches the runtime repr,
            # but must not reenter the subclass's __str__ override.
            if target.name == "__str__":
                representation = True
                method = resolve(semantic)
        if semantic in e.module.vtable_roots:
            # object.__str__ falls back to the runtime class's repr, not the
            # static base's. Different selected methods may have different
            # defaulted parameters; bind each actual method, not a shared ABI.
            table = e.emit_value(f"load ptr, ptr {value}")
            result = e.emit_value("alloca ptr")
            done = e.new_label("repr.dispatch.done")
            for cls in e.module.classes:
                if cls is semantic or not is_subclass(cls, semantic):
                    continue
                concrete = resolve(cls)
                if concrete is method:
                    continue
                matches = e.emit_value(f"icmp eq ptr {table}, @{e.vtable_name(cls)}")
                yes, no = e.new_label("repr.dispatch.call"), e.new_label("repr.dispatch.next")
                e.emit_line(f"br i1 {matches}, label %{yes}, label %{no}")
                e.emit_line(f"{yes}:")
                e.emit_line(f"store ptr {invoke(concrete)}, ptr {result}")
                e.emit_line(f"br label %{done}")
                e.emit_line(f"{no}:")
            e.emit_line(f"store ptr {invoke(method)}, ptr {result}")
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{done}:")
            return e.emit_value(f"load ptr, ptr {result}")
        return invoke(method)

    def value(self, semantic, kind, value, representation=True, *, outline=True):
        e = self.e
        if outline and isinstance(semantic, UnionType):
            # Normalization can expand named aliases inside optional unions.
            # Outline every union edge, not just named aliases or repeated
            # paths, to bound both compiler recursion and branching code size.
            # Only the helper's root expands inline; its children reuse helpers.
            from . import erased_repr
            erased_repr.call(e, semantic, kind, value, representation, self.node, output=self.output)
            return
        if nullable.is_object(semantic):
            from . import erased_repr
            if isinstance(self.node.func, ast.Attribute) and e.is_super_call(self.node.func.value):
                if self.node.func.attr != "__str__":
                    raise LLVMUnsupported("LLVM explicit object.__repr__ requires default object formatting", self.node)
                # object.__str__ delegates to the runtime repr, not back to the
                # subclass str override. super() is an implicit erased upcast.
                e.module.erased_candidates[e.current_function.cls, None] = None
                representation = True
            erased_repr.call(e, semantic, kind, value, representation, self.node, output=self.output)
            return
        if member := nullable.member(semantic):
            yes, no, done = (e.new_label("repr.optional." + label) for label in ("yes", "no", "done"))
            e.emit_line(f"br i1 {nullable.present(e, kind, value)}, label %{yes}, label %{no}")
            e.emit_line(f"{no}:")
            self.append(self.literal("None"))
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{yes}:")
            payload = value if kind == "ptr" else e.emit_value(f"extractvalue {kind} {value}, 1")
            self.value(member, e.value_type(member), payload, representation)
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{done}:")
            return
        if isinstance(semantic, UnionType):
            tagged.dispatch(e, semantic, value, "void",
                            lambda member, storage, payload: self.value(member, storage, payload, representation))
            return
        if enum_ops.scalar_name(semantic):
            self.append(enum_ops.select(e, semantic, value, repr if representation else str))
            return
        name = None if semantic in e.module.classes else semantic.generic_name
        if name == "NoneType":
            self.append(self.literal("None"))
        elif collections.builtin_name(semantic) == "NotImplementedType":
            self.append(self.literal("NotImplemented"))
        elif name == "str":
            if representation:
                e.emit_line(f"call void @pyjs.repr.write.string(ptr {self.output}, ptr {value}, "
                            f"ptr @pyjs.unicode.printable, i64 {len(text.PRINTABLE_RANGES)})")
                self.check_output()
            else:
                self.append(value)
        elif name == "bytes":
            self.append(e.owned_text_call("pyjs.text.repr_bytes", [f"ptr {value}"])[1])
        elif name == "bool":
            self.append(e.string_from_bool(value))
        elif name == "int":
            self.append(e.string_from_int(value))
        elif name == "float":
            self.append(e.string_from_float(value))
        elif name == "slice":
            from . import slices
            self.append(self.literal("slice("))
            for index in range(3):
                if index:
                    self.append(self.literal(", "))
                self.value(slices.bound_type(), tagged.STORAGE, slices.field(e, value, index), True)
            self.append(self.literal(")"))
        elif name == "range":
            start, stop, step = e.range_values(value)
            self.append(self.literal("range("))
            self.append(e.string_from_int(start))
            self.append(self.literal(", "))
            self.append(e.string_from_int(stop))
            more, done = e.new_label("repr.range.step"), e.new_label("repr.range.done")
            e.emit_line(f"br i1 {e.emit_value(f'icmp ne i64 {step}, 1')}, label %{more}, label %{done}")
            e.emit_line(f"{more}:")
            self.append(self.literal(", "))
            self.append(e.string_from_int(step))
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{done}:")
            self.append(self.literal(")"))
        elif name in collections.CONTAINERS | collections.VIEWS:
            self.container(semantic, value)
        elif semantic in e.module.classes:
            frame = calls.root_values(e, value)
            with method_scope(e, self.node):
                self.append(self.invoke_method(semantic, value, representation))
            calls.pop_roots(e, frame)
        else:
            raise LLVMUnsupported(f"LLVM repr requires a concrete supported type, got {semantic.name}", self.node)

    def container(self, semantic, value):
        e, name = self.e, semantic.generic_name
        roots = calls.root_values(e, value)
        frame = e.emit_value("alloca %pyjs.repr.frame")
        arena = e.load_local("__arena")
        cycle, body, done = (e.new_label("repr." + label) for label in ("cycle", "body", "done"))
        # CPython bypasses reentry detection for a list cleared by __repr__.
        if name == "list":
            empty, check = e.new_label("repr.empty"), e.new_label("repr.check")
            length = e.emit_value(f"load i64, ptr {value}")
            e.emit_line(f"br i1 {e.emit_value(f'icmp eq i64 {length}, 0')}, label %{empty}, label %{check}")
            e.emit_line(f"{empty}:")
            self.append(self.literal("[]"))
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{check}:")
        entered = e.emit_value(f"call i8 @pyjs.repr.enter(ptr {arena}, ptr {frame}, ptr {value})")
        e.guard_exception(self.node, e.emit_value(f"icmp ne i8 {entered}, 2"), "RecursionError",
                          "maximum recursion depth exceeded while getting the repr of an object")
        e.emit_line(f"br i1 {e.emit_value(f'icmp eq i8 {entered}, 0')}, label %{cycle}, label %{body}")
        e.emit_line(f"{cycle}:")
        placeholder = {"list": "[...]", "dict": "{...}", "tuple": "(...)", "set": "set(...)", "frozenset": "frozenset(...)"}.get(name, "...")
        self.append(self.literal(placeholder))
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{body}:")
        outer, cleanup = e.exception_target, e.new_label("repr.cleanup")
        e.exception_target = cleanup
        try:
            self.items(semantic, value)
        finally:
            e.exception_target = outer
        e.emit_line(f"call void @pyjs.repr.leave(ptr {arena}, ptr {frame})")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{e.name(cleanup, 'block')}:")
        e.emit_line(f"call void @pyjs.repr.leave(ptr {arena}, ptr {frame})")
        e.branch_to_exception_target()
        e.emit_line(f"{done}:")
        calls.pop_roots(e, roots)

    def items(self, semantic, value):
        e, name = self.e, semantic.generic_name
        snapshot_frame = None
        source_type = semantic
        if name in collections.VIEWS | {"set", "frozenset"}:
            # CPython snapshots sets/views BEFORE any member callback. Iterate
            # the private list with the source's already analyzed item layout.
            member = collections.item_type(semantic)
            snapshot = collections.new_list(e, member)
            snapshot_frame = calls.root_values(e, snapshot)
            collections.loop(e, semantic, value,
                             lambda t, v: collections.append(e, snapshot, member, t, v, self.node), self.node)
            value = snapshot
        opening, closing = {"list": ("[", "]"), "tuple": ("(", ")"), "dict": ("{", "}"), "set": ("{", "}"),
                            "frozenset": ("frozenset({", "})"),
                            "KeysView": ("dict_keys([", "])"), "ValuesView": ("dict_values([", "])"),
                            "ItemsView": ("dict_items([", "])")}[name]
        finish = e.new_label("repr.items.done")
        if name in {"set", "frozenset"}:
            empty, nonempty = e.new_label("repr.set.empty"), e.new_label("repr.set.nonempty")
            length = e.emit_value(f"load i64, ptr {value}")
            e.emit_line(f"br i1 {e.emit_value(f'icmp eq i64 {length}, 0')}, label %{empty}, label %{nonempty}")
            e.emit_line(f"{empty}:")
            self.append(self.literal(name + "()"))
            e.emit_line(f"br label %{finish}")
            e.emit_line(f"{nonempty}:")
        first = e.emit_value("alloca i1")
        e.emit_line(f"store i1 true, ptr {first}")
        self.append(self.literal(opening))

        def item(member, current):
            separator, body = e.new_label("repr.separator"), e.new_label("repr.item")
            initial = e.emit_value(f"load i1, ptr {first}")
            e.emit_line(f"br i1 {initial}, label %{body}, label %{separator}")
            e.emit_line(f"{separator}:")
            self.append(self.literal(", "))
            e.emit_line(f"br label %{body}")
            e.emit_line(f"{body}:")
            e.emit_line(f"store i1 false, ptr {first}")
            self.value(member, e.value_type(member), current)

        if name == "dict":
            e.module.uses_mappings = True
            # Capture BOTH members before calling key.__repr__, which may
            # delete entries, replace a value, resize vectors, or collect.
            key, member = e.dictionary_types(semantic)
            key_kind, kind = e.value_type(key), e.value_type(member)
            tracked = e.emit_value(f"call i1 @pyjs.dict.track.order(ptr {e.load_local('__arena')}, ptr {value})")
            e.guard_exception(self.node, tracked, "MemoryError", "native representation allocation failed")
            index = e.emit_value("alloca i64")
            e.emit_line(f"store i64 0, ptr {index}")
            check, body, done = (e.new_label("repr.dict." + label) for label in ("check", "body", "done"))
            e.emit_line(f"br label %{check}")
            e.emit_line(f"{check}:")
            cursor = e.emit_value(f"load i64, ptr {index}")
            offset = e.emit_value(f"call i64 @pyjs.dict.repr.index(ptr {value}, i64 {cursor})")
            length = e.emit_value(f"load i64, ptr {value}")
            e.emit_line(f"br i1 {e.emit_value(f'icmp ult i64 {offset}, {length}')}, label %{body}, label %{done}")
            e.emit_line(f"{body}:")
            pair = []
            for storage, field in ((key_kind, 2), (kind, 3)):
                data = collections.storage(e, value, field)
                slot = e.emit_value(f"getelementptr {storage}, ptr {data}, i64 {offset}")
                pair.append(e.emit_value(f"load {storage}, ptr {slot}"))
            a, b = pair
            order = collections.storage(e, value, 6)
            ordinal_slot = e.emit_value(f"getelementptr i64, ptr {order}, i64 {offset}")
            ordinal = e.emit_value(f"load i64, ptr {ordinal_slot}")
            following = e.emit_value(f"add i64 {ordinal}, 1")
            # A recursive union can carry a pointer in its tagged payload.
            # Keep BOTH captured members alive if key.__repr__ deletes them
            # from the dictionary and then collects before the value is read.
            slots, roots = calls.value_slots(e, [key_kind, kind])
            for slot, storage, current in zip(slots, (key_kind, kind), (a, b), strict=True):
                e.emit_line(f"store {storage} {current}, ptr {slot}")
            item(key, a)
            self.append(self.literal(": "))
            self.value(member, kind, b)
            calls.pop_roots(e, roots)
            e.emit_line(f"store i64 {following}, ptr {index}")
            e.emit_line(f"br label %{check}")
            e.emit_line(f"{done}:")
        elif name in collections.VIEWS | {"set", "frozenset"}:
            # A snapshot has a list header but carries the view/set member
            # type. No synthetic analyzer specialization during emission.
            member = collections.item_type(source_type)
            index = e.emit_value("alloca i64")
            e.emit_line(f"store i64 0, ptr {index}")
            check, body, done = (e.new_label("repr.snapshot." + label) for label in ("check", "body", "done"))
            e.emit_line(f"br label %{check}")
            e.emit_line(f"{check}:")
            offset = e.emit_value(f"load i64, ptr {index}")
            length = e.emit_value(f"load i64, ptr {value}")
            e.emit_line(f"br i1 {e.emit_value(f'icmp ult i64 {offset}, {length}')}, label %{body}, label %{done}")
            e.emit_line(f"{body}:")
            kind = e.value_type(member)
            slot = e.emit_value(f"getelementptr {kind}, ptr {collections.storage(e, value, 2)}, i64 {offset}")
            item(member, e.emit_value(f"load {kind}, ptr {slot}"))
            e.emit_line(f"store i64 {e.emit_value(f'add i64 {offset}, 1')}, ptr {index}")
            e.emit_line(f"br label %{check}")
            e.emit_line(f"{done}:")
        else:
            collections.loop(e, semantic, value, item, self.node)
        if name == "tuple":
            length = e.emit_value(f"load i64, ptr {value}")
            comma, done = e.new_label("repr.tuple.comma"), e.new_label("repr.tuple.done")
            e.emit_line(f"br i1 {e.emit_value(f'icmp eq i64 {length}, 1')}, label %{comma}, label %{done}")
            e.emit_line(f"{comma}:")
            self.append(self.literal(","))
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{done}:")
        self.append(self.literal(closing))
        e.emit_line(f"br label %{finish}")
        e.emit_line(f"{finish}:")
        calls.pop_roots(e, snapshot_frame)

"""JSON output over concrete analyzed shapes and the shared buffered sink.

Container helpers emit one item at a time over an explicit runtime stack.
Recursive types therefore produce finite code, without recursive native calls.
"""

import ast
import ctypes

from pyjs.analysis.analyzer import (
    analyzed_value_object,
    analyzed_value_type,
    runtime_dunder_methods,
)
from pyjs.analysis.ir import CollectionNew
from pyjs.analysis.objects import Class, GenericClass, UnionType
from pyjs.analysis.type_relations import is_subclass

from . import callback_ops, calls, comparisons, enum_ops, mapping_keys, nullable, tagged
from . import collection_ops as collections
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .output_ops import Buffer
from .runtime import json_state
from .runtime.arena import _Arena


def retain_sort_callbacks(node):
    """Expose nested key comparisons to normal reachability/lifetime analysis."""
    from .mapping_keys import protocols

    ordered = next((item.value for item in node.keywords if item.arg == "sort_keys"), None)
    if ordered is None or isinstance(ordered, ast.Constant) and ordered.value is False:
        return
    source = node.args[0] if node.args else next(item.value for item in node.keywords if item.arg == "obj")
    pending, visited, callbacks, methods = [analyzed_value_type(source)], set(), [], []
    while pending:
        semantic = tagged.runtime_type(pending.pop())
        if semantic in visited:
            continue
        visited.add(semantic)
        if isinstance(semantic, UnionType):
            pending.extend(semantic.types)
            continue
        name = collections.builtin_name(semantic)
        if name == "dict":
            key = semantic.generic_types["K"]
            if enum_ops.scalar_name(key) is None:
                callbacks.extend(protocols(key, ("__eq__", "__lt__", "__gt__")))
                if protocols(key, ("__eq__",)):
                    # Equal application keys compare values before skipkeys
                    # omits their entries. Reuse ordinary recursive comparison
                    # reachability, including contained and virtual methods.
                    methods.extend(runtime_dunder_methods(
                        semantic.generic_types["V"], "__eq__", "__lt__", "__gt__"))
            pending.append(semantic.generic_types["V"])
        elif name in {"list", "tuple"}:
            pending.extend(semantic.generic_types.values())
    node.runtime_protocols = (*node.runtime_protocols, *dict.fromkeys(callbacks))
    node.runtime_methods = tuple(dict.fromkeys((*node.runtime_methods, *methods)))
    node.runtime_member_callbacks = True


def validate_call(node):
    if calls.expands_arguments(node):
        raise LLVMUnsupported("LLVM json.dumps requires statically bound arguments", node)
    # Reject callback/class values before trying to lower their unsupported
    # first-class native representation; diagnostics must not become KeyErrors.
    for keyword in node.keywords:
        if keyword.arg in {"cls", "default"} and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is None):
            raise LLVMUnsupported(f"LLVM json.dumps does not support {keyword.arg}= callbacks", keyword.value)
    source = node.args[0] if node.args else next(keyword.value for keyword in node.keywords if keyword.arg == "obj")
    reject_class_values(source, node)
    validate_shape(analyzed_value_type(source), node, literal_container=isinstance(source, CollectionNew))


def dumps(emitter, target, node):
    validate_call(node)
    with calls.bind(emitter, target, node) as arguments:
        options = {parameter.arg: (source, value) for parameter, source, value in
                   zip(calls.parameters(target), arguments.sources, arguments.values, strict=True)}
        encoder = Encoder(emitter, node, options)
        source, (kind, value) = options["obj"]
        semantic = tagged.effective_type(analyzed_value_type(source), kind)
        return "ptr", encoder.render(lambda: encoder.value(semantic, value),
                                     *((value,) if kind == "ptr" else ()))


def reject_class_values(value, node, label="JSON"):
    # Class-as-value queries can instantiate new analyzer type specializations
    # and raise DependencyError during emission. Check literal value positions
    # before asking for their type; constructor calls such as int(1) are fine.
    if isinstance(value, (ast.Name, ast.Attribute)) and isinstance(analyzed_value_object(value), (Class, GenericClass)):
        raise LLVMUnsupported(f"LLVM {label} does not support class objects", node)
    if isinstance(value, CollectionNew):
        value = value.source
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        members = value.elts
    elif isinstance(value, ast.Dict):
        members = [*value.keys, *value.values]
    else:
        return
    for member in members:
        reject_class_values(member, node, label)


def validate_shape(semantic, node, ancestors=(), *, literal_container=False):
    """Reject unsupported storage before argument construction emits invalid IR."""
    if isinstance(semantic, UnionType):
        if semantic in ancestors:
            return
        if member := nullable.member(semantic):
            return validate_shape(member, node, (*ancestors, semantic))
        for member in semantic.types:
            if collections.builtin_name(member) != "NoneType":
                validate_shape(member, node, (*ancestors, semantic))
        return
    name = enum_ops.storage_name(semantic)
    if name in {"str", "int", "float", "bool", "NoneType"}:
        return
    if name not in {"list", "tuple", "dict"}:
        if name == "object" and (ancestors or literal_container):
            raise LLVMUnsupported("LLVM JSON requires a concrete element type; annotate the container", node)
        if name in {"bytes", "set", "frozenset"} or (
                isinstance(semantic, Class) and not semantic.container.scope.is_builtins):
            # A representable concrete value can fail when visited. Rejecting
            # its annotation here would also reject empty/omitted containers
            # and reorder earlier key, cycle or nonfinite-number failures.
            return
        raise LLVMUnsupported(f"LLVM JSON does not support {semantic.name}", node)
    if semantic in ancestors:
        return
    if name == "dict":
        if collections.builtin_name(semantic.generic_types["K"]) == "object":
            raise LLVMUnsupported("LLVM JSON requires concrete key/value types; annotate the container", node)
        # Unsupported concrete key kinds are rejected or skipped when visited;
        # an empty mapping must not fail merely because of its declared key type.
        members = (semantic.generic_types["V"],)
    else:
        members = semantic.generic_types.values()
    for member in members:
        validate_shape(member, node, (*ancestors, semantic))


class Encoder(Buffer):
    def __init__(self, emitter, node, options=None, *, output=None, state=None, pretty=False, sorted_keys=False, callbacks=False):
        super().__init__(emitter, node, output=output)
        self.options = options
        self.state = state
        if state is not None:
            self.pretty, self.sorted_keys = pretty, sorted_keys
            self.callbacks = callbacks
            self.indent = self.state_value("indent", "ptr")
            self.count = self.state_value("indent_count", "i64")
            self.item_separator = self.state_value("item_separator", "ptr")
            self.key_separator = self.state_value("key_separator", "ptr")
            return
        self.pretty = collections.builtin_name(analyzed_value_type(options["indent"][0])) != "NoneType"

        def indentation(semantic, kind, value):
            name = collections.builtin_name(semantic)
            if name == "str":
                token, count = value, "1"
            elif name in {"int", "bool"}:
                if kind == "i1":
                    value = emitter.emit_value(f"zext i1 {value} to i64")
                positive = emitter.emit_value(f"icmp sgt i64 {value}, 0")
                token, count = self.literal(" "), emitter.emit_value(f"select i1 {positive}, i64 {value}, i64 0")
            else:
                raise LLVMUnsupported("LLVM json.dumps indent requires int, str or None", options["indent"][0])
            result = emitter.emit_value(f"insertvalue {{ ptr, i64 }} zeroinitializer, ptr {token}, 0")
            return emitter.emit_value(f"insertvalue {{ ptr, i64 }} {result}, i64 {count}, 1")

        # A null token means indent=None; an empty token still emits newlines.
        # Resolve option unions once per call, not once per visited container.
        indent = self.option("indent", "{ ptr, i64 }", "zeroinitializer", indentation)
        self.indent = emitter.emit_value(f"extractvalue {{ ptr, i64 }} {indent}, 0")
        self.count = emitter.emit_value(f"extractvalue {{ ptr, i64 }} {indent}, 1")
        pretty = emitter.emit_value(f"icmp ne ptr {self.indent}, null")
        item_separator = emitter.emit_value(f"select i1 {pretty}, ptr {self.literal(',')}, ptr {self.literal(', ')}")
        defaults = emitter.emit_value(f"insertvalue {{ ptr, ptr }} zeroinitializer, ptr {item_separator}, 0")
        defaults = emitter.emit_value(f"insertvalue {{ ptr, ptr }} {defaults}, ptr {self.literal(': ')}, 1")

        def separators(semantic, kind, value):
            if (collections.builtin_name(semantic) != "tuple" or semantic.tuple_variadic
                    or len(semantic.generic_types) != 2
                    or any(collections.builtin_name(item) != "str" for item in semantic.generic_types.values())):
                raise LLVMUnsupported("LLVM json.dumps separators requires a pair of strings or None", options["separators"][0])
            data = collections.storage(emitter, value, 2)
            layout = emitter.tuple_type(semantic, options["separators"][0])
            result = "zeroinitializer"
            for index in range(2):
                item = emitter.emit_value(f"load ptr, ptr {collections.field(emitter, data, layout, index)}")
                result = emitter.emit_value(f"insertvalue {{ ptr, ptr }} {result}, ptr {item}, {index}")
            return result

        pair = self.option("separators", "{ ptr, ptr }", defaults, separators)
        self.item_separator = emitter.emit_value(f"extractvalue {{ ptr, ptr }} {pair}, 0")
        self.key_separator = emitter.emit_value(f"extractvalue {{ ptr, ptr }} {pair}, 1")
        sort_source = options["sort_keys"][0]
        self.sorted_keys = not (isinstance(sort_source, ast.Constant) and sort_source.value is False)
        self.callbacks = bool(node.runtime_protocols or node.runtime_methods)
        self.state = emitter.emit_value(f"alloca [{json_state.STATE_SIZE} x i8], align 8")
        emitter.emit_line(f"store [{json_state.STATE_SIZE} x i8] zeroinitializer, ptr {self.state}")
        self.scratch = emitter.emit_value(f"alloca [{ctypes.sizeof(_Arena)} x i8], align 8")
        # Raw pointer slots use the collector's ordinary conservative tracing;
        # the Python-authored driver pushes/pops two slots per pending frame.
        self.roots = (emitter.allocated_value(f"call ptr @pyjs.list.new.owned({collections.owner(emitter)}, i64 8, i64 0)")
                      if emitter.module.uses_gc else "null")
        for name, kind, value in (
                ("scratch", "ptr", self.scratch), ("roots", "ptr", self.roots), ("indent", "ptr", self.indent),
                ("indent_count", "i64", self.count), ("item_separator", "ptr", self.item_separator),
                ("key_separator", "ptr", self.key_separator),
                *((name, "i1", self.flag(name)) for name in
                  ("ensure_ascii", "allow_nan", "check_circular", "sort_keys", "skipkeys"))):
            emitter.emit_line(f"store {kind} {value}, ptr {self.state_field(name)}")

    def option(self, name, result_kind, default, callback):
        source, (kind, value) = self.options[name]

        def visit(semantic, kind, value):
            if tagged.members(semantic):
                return tagged.dispatch(self.e, semantic, value, result_kind, visit)
            if nullable.member(semantic):
                return nullable.dispatch(self.e, semantic, kind, value, result_kind, default, visit)
            if collections.builtin_name(semantic) == "NoneType":
                return default
            return callback(semantic, kind, value)

        return visit(tagged.effective_type(analyzed_value_type(source), kind), kind, value)

    def state_field(self, name):
        offset = getattr(json_state._State, name).offset
        return self.e.emit_value(f"getelementptr i8, ptr {self.state}, i64 {offset}")

    def state_value(self, name, kind):
        return self.e.emit_value(f"load {kind}, ptr {self.state_field(name)}")

    def render(self, write, *roots):
        def traverse():
            e = self.e
            e.emit_line(f"call void @pyjs.arena.init(ptr {self.scratch})")
            outer, cleanup, done = e.exception_target, e.new_label("json.cleanup"), e.new_label("json.done")
            e.exception_target = cleanup
            try:
                active = e.allocated_value(f"call ptr @pyjs.identity.try.new(ptr {self.scratch})")
                e.emit_line(f"store ptr {active}, ptr {self.state_field('active')}")
                write()
                heap = e.load_local("__heap") if e.module.uses_gc else "null"
                e.emit_line(f"call void @pyjs.json.run(ptr {e.load_local('__arena')}, ptr {heap}, "
                            f"ptr {e.load_local('__exception')}, ptr {self.output}, ptr {self.state})")
                e.check_active_exception(self.node)
            finally:
                e.exception_target = outer
            e.emit_line(f"call void @pyjs.arena.destroy(ptr {self.scratch})")
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{e.name(cleanup, 'block')}:")
            e.emit_line(f"call void @pyjs.arena.destroy(ptr {self.scratch})")
            e.branch_to_exception_target()
            e.emit_line(f"{done}:")
        return super().render(traverse, *roots, self.roots)

    def flag(self, name):
        if self.options is None:
            return self.state_value(name, "i1")
        kind, value = self.options[name][1]
        if kind != "i1":
            raise LLVMUnsupported(f"LLVM json.dumps requires boolean {name}", self.options[name][0])
        return value

    def quoted(self, value):
        self.e.emit_line(f"call void @pyjs.json.write.string(ptr {self.output}, ptr {value}, i1 {self.flag('ensure_ascii')})")
        self.check_output()

    def newline(self, depth):
        if self.pretty:
            self.e.emit_line(f"call void @pyjs.json.indent(ptr {self.output}, ptr {self.indent}, i64 {self.count}, i64 {depth})")
            self.check_output()

    def value(self, semantic, value, depth=0):
        e = self.e
        if tagged.members(semantic):
            tagged.dispatch(e, semantic, value, "void",
                            lambda member, kind, payload: self.value(member, payload, depth))
            return
        if nullable.member(semantic):
            present = nullable.present(e, e.value_type(semantic), value)
            yes, no, done = (e.new_label("json.optional." + label) for label in ("present", "null", "done"))
            e.emit_line(f"br i1 {present}, label %{yes}, label %{no}")
            e.emit_line(f"{no}:")
            self.append(self.literal("null"))
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{yes}:")
            kind = e.value_type(semantic)
            payload = value if kind == "ptr" else e.emit_value(f"extractvalue {kind} {value}, 1")
            self.value(nullable.member(semantic), payload, depth)
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{done}:")
            return
        name = enum_ops.storage_name(semantic)
        if name == "str":
            self.quoted(value)
        elif name == "NoneType":
            self.append(self.literal("null"))
        elif name == "bool":
            self.append(e.emit_value(f"select i1 {value}, ptr {self.literal('true')}, ptr {self.literal('false')}"))
        elif name == "int":
            self.append(self.number(value, "int"))
        elif name == "float":
            self.append(self.floating(value))
        elif name in {"list", "tuple", "dict"}:
            self.container(semantic, value, depth)
        else:
            if semantic in e.module.vtable_roots:
                # Error text names the runtime class, even through a base-typed
                # container. No user method or string conversion is invoked.
                table = e.emit_value(f"load ptr, ptr {value}")
                for cls in e.module.classes:
                    if cls is not semantic and is_subclass(cls, semantic):
                        different = e.emit_value(f"icmp ne ptr {table}, @{e.vtable_name(cls)}")
                        e.guard_exception(self.node, different, "TypeError",
                                          f"Object of type {cls.generic_name} is not JSON serializable")
            e.guard_exception(self.node, "false", "TypeError",
                              f"Object of type {semantic.generic_name} is not JSON serializable")

    def number(self, value, kind):
        # A walker consumes each token before returning or formatting its next
        # number. Stack-backed text also works for keys (quoted before values),
        # without retaining one heap/arena allocation per numeric item. These
        # allocas are hoisted to function entry, not executed inside a loop.
        e = self.e
        buffer = e.emit_value("alloca [64 x i8]")
        text = e.emit_value("alloca %pyjs.string")
        if kind == "int":
            count = e.emit_value(f"call i32 (ptr, i64, ptr, ...) @snprintf(ptr {buffer}, i64 64, "
                                 f"ptr @pyjs.string.int.format, i64 {value})")
            count = e.emit_value(f"sext i32 {count} to i64")
        else:
            count = e.emit_value(f"call i64 @pyjs.string.format.f64(ptr {buffer}, double {value})")
        positive = e.emit_value(f"icmp sgt i64 {count}, 0")
        fits = e.emit_value(f"icmp slt i64 {count}, 64")
        e.guard_exception(self.node, e.emit_value(f"and i1 {positive}, {fits}"),
                          "MemoryError", "native JSON number formatting failed")
        e.emit_line(f"store i64 {count}, ptr {text}")
        data = e.emit_value(f"getelementptr %pyjs.string, ptr {text}, i32 0, i32 1")
        e.emit_line(f"store ptr {buffer}, ptr {data}")
        return text

    def floating(self, value):
        e = self.e
        positive = e.emit_value(f"fcmp oeq double {value}, 0x7FF0000000000000")
        negative = e.emit_value(f"fcmp oeq double {value}, 0xFFF0000000000000")
        nan = e.emit_value(f"fcmp uno double {value}, {value}")
        infinite = e.emit_value(f"or i1 {positive}, {negative}")
        special = e.emit_value(f"or i1 {infinite}, {nan}")
        finite = e.emit_value(f"xor i1 {special}, true")
        allowed = e.emit_value(f"or i1 {finite}, {self.flag('allow_nan')}")
        valid, invalid = e.new_label("json.float.allowed"), e.new_label("json.float.rejected")
        e.emit_line(f"br i1 {allowed}, label %{valid}, label %{invalid}")
        e.emit_line(f"{invalid}:")
        prefix = "Out of range float values are not JSON compliant: "
        message = e.emit_value(f"select i1 {negative}, ptr {self.literal(prefix + '-inf')}, ptr {self.literal(prefix + 'inf')}")
        message = e.emit_value(f"select i1 {nan}, ptr {self.literal(prefix + 'nan')}, ptr {message}")
        e.activate_error(self.node, NATIVE_ENVIRONMENT.builtins.search("ValueError"), message)
        e.branch_to_exception_target()
        e.emit_line(f"{valid}:")
        slot = e.emit_value("alloca ptr")
        ordinary, unusual, done = (e.new_label("json.float." + label) for label in ("finite", "special", "done"))
        e.emit_line(f"br i1 {special}, label %{unusual}, label %{ordinary}")
        e.emit_line(f"{unusual}:")
        text = e.emit_value(f"select i1 {negative}, ptr {self.literal('-Infinity')}, ptr {self.literal('Infinity')}")
        text = e.emit_value(f"select i1 {nan}, ptr {self.literal('NaN')}, ptr {text}")
        e.emit_line(f"store ptr {text}, ptr {slot}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{ordinary}:")
        text = self.number(value, "float")
        e.emit_line(f"store ptr {text}, ptr {slot}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
        return e.emit_value(f"load ptr, ptr {slot}")

    def key(self, semantic, value):
        """Return unquoted key text, or null to omit the entire entry."""
        e = self.e
        if tagged.members(semantic):
            return tagged.dispatch(e, semantic, value, "ptr",
                                   lambda member, kind, payload: self.key(member, payload))
        if nullable.member(semantic):
            return nullable.dispatch(e, semantic, e.value_type(semantic), value, "ptr", self.literal("null"),
                                     lambda member, kind, payload: self.key(member, payload))
        name = enum_ops.storage_name(semantic)
        if name == "str":
            return value
        if name == "NoneType":
            return self.literal("null")
        if name == "int":
            return self.number(value, "int")
        if name == "float":
            return self.floating(value)
        if name == "bool":
            return e.emit_value(f"select i1 {value}, ptr {self.literal('true')}, ptr {self.literal('false')}")
        e.guard_exception(self.node, self.flag("skipkeys"), "TypeError",
                          "keys must be str, int, float, bool or None, not " + (name or semantic.generic_name))
        return "null"

    def container(self, semantic, value, depth):
        e = self.e
        key = semantic, self.pretty, self.sorted_keys, self.callbacks
        if key not in e.module.json_walkers:
            e.module.json_walkers[key] = f"pyjs.json.item.{len(e.module.json_walkers)}", self.node
        symbol, _ = e.module.json_walkers[key]
        status = e.emit_value(f"call i8 @pyjs.json.push(ptr {self.state}, ptr @{symbol}, ptr {value}, i64 {depth})")
        for code, error, message in ((1, "ValueError", "Circular reference detected"),
                                      (2, "RecursionError", "maximum recursion depth exceeded while encoding a JSON object"),
                                      (3, "MemoryError", "native JSON traversal allocation failed")):
            e.guard_exception(self.node, e.emit_value(f"icmp ne i8 {status}, {code}"), error, message)
        self.append(self.literal("{" if collections.builtin_name(semantic) == "dict" else "["))

    def step(self, semantic):
        e = self.e

        def field(name):
            return e.emit_value(f"getelementptr i8, ptr %frame, i64 {getattr(json_state._Frame, name).offset}")

        value = e.emit_value(f"load ptr, ptr {field('value')}")
        mapping = collections.builtin_name(semantic) == "dict"
        scalar_sort = (mapping and self.sorted_keys and not self.callbacks
                       and enum_ops.storage_name(collections.item_type(semantic)) in {"int", "bool", "float", "str", "bytes"})
        snapshot_sort = mapping and self.sorted_keys and not scalar_sort
        if snapshot_sort:
            snapshot = e.emit_value(f"load ptr, ptr {field('snapshot')}")
            present = e.emit_value(f"icmp ne ptr {snapshot}, null")
            value = e.emit_value(f"select i1 {present}, ptr {snapshot}, ptr {value}")
        index_slot = field("index")
        index = e.emit_value(f"load i64, ptr {index_slot}")
        written_slot = field("written")
        written = e.emit_value(f"load i64, ptr {written_slot}")
        depth = e.emit_value(f"load i64, ptr {field('depth')}")
        length = e.emit_value(f"load i64, ptr {value}")
        close, item, done = (e.new_label("json." + name) for name in ("close", "item", "step.done"))
        # A nested comparator can shrink an ancestor list while its frame is
        # suspended. Match list iteration: stop at or beyond its current end.
        e.emit_line(f"br i1 {e.emit_value(f'icmp uge i64 {index}, {length}')}, label %{close}, label %{item}")
        e.emit_line(f"{close}:")
        newline, closing = e.new_label("json.close.newline"), e.new_label("json.close.token")
        e.emit_line(f"br i1 {e.emit_value(f'icmp ne i64 {written}, 0')}, label %{newline}, label %{closing}")
        e.emit_line(f"{newline}:")
        self.newline(depth)
        e.emit_line(f"br label %{closing}")
        e.emit_line(f"{closing}:")
        self.append(self.literal("}" if mapping else "]"))
        e.emit_line(f"call void @pyjs.json.pop(ptr {self.state})")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{item}:")
        child_depth = e.emit_value(f"add i64 {depth}, 1")
        e.emit_line(f"store i64 {e.emit_value(f'add i64 {index}, 1')}, ptr {index_slot}")

        def prefix():
            # Input position and emitted position differ when keys are skipped.
            # Do not emit punctuation or visit the value of an omitted entry.
            separator, body = e.new_label("json.separator"), e.new_label("json.body")
            e.emit_line(f"br i1 {e.emit_value(f'icmp ne i64 {written}, 0')}, label %{separator}, label %{body}")
            e.emit_line(f"{separator}:")
            self.append(self.item_separator)
            e.emit_line(f"br label %{body}")
            e.emit_line(f"{body}:")
            self.newline(child_depth)
            e.emit_line(f"store i64 {e.emit_value(f'add i64 {written}, 1')}, ptr {written_slot}")

        position = index
        if scalar_sort:
            # No user comparison can run anywhere in this encoding. Pending
            # inputs cannot mutate, so reuse frame-local scalar scratch instead
            # of allocating entry snapshots/key vectors for every sibling.
            member = collections.item_type(semantic)
            keys = collections.storage(e, value, 2)
            size = e.llvm_size(e.value_type(member))
            kind = collections.scalar_kind(member, self.node)
            position = e.emit_value(f"call i64 @pyjs.json.scalar.index(ptr {self.state}, ptr %frame, ptr {keys}, "
                                    f"i64 {length}, i64 {size}, i8 {kind}, i64 {index}, i1 {self.flag('sort_keys')})")
            e.guard_exception(self.node, e.emit_value(f"icmp sge i64 {position}, 0"),
                              "MemoryError", "native JSON sorting scratch allocation failed")
        if snapshot_sort:
            e.module.uses_mappings = True
            index_slot = field("indices")
            prepare, ready = e.new_label("json.sort.prepare"), e.new_label("json.sort.ready")
            e.emit_line(f"br i1 {e.emit_value(f'icmp eq i64 {index}, 0')}, label %{prepare}, label %{ready}")
            e.emit_line(f"{prepare}:")
            member = collections.item_type(semantic)
            integer = NATIVE_ENVIRONMENT.builtins.search("int")
            # Keep source positions, not keys to be looked up again: NaN keys
            # are not equal to themselves. Indices contain no references and
            # belong to call-local scratch: they survive nested callbacks and
            # are reclaimed at call exit without waiting for managed collection.
            scratch = self.state_value("scratch", "ptr")
            allocator = "@pyjs.gc.alloc.adapter" if e.module.uses_gc else "null"
            heap = e.load_local("__heap") if e.module.uses_gc else "null"
            key_size = e.llvm_size(e.value_type(member))
            value_size = e.llvm_size(e.value_type(semantic.generic_types["V"]))
            snapshot = e.allocated_value(f"call ptr @pyjs.dict.copy(ptr {scratch}, ptr {allocator}, ptr {heap}, "
                                         f"ptr {value}, i64 {key_size}, i64 {value_size}, i8 0)")
            e.emit_line(f"store ptr {snapshot}, ptr {field('snapshot')}")
            if e.module.uses_gc:
                pending = self.state_value("roots", "ptr")
                last = e.emit_value(f"sub i64 {e.emit_value(f'load i64, ptr {pending}')}, 1")
                slot = e.emit_value(f"getelementptr ptr, ptr {collections.storage(e, pending, 2)}, i64 {last}")
                e.emit_line(f"store ptr {snapshot}, ptr {slot}")
            entry_pairs = enum_ops.scalar_name(member) is None and mapping_keys.protocols(member, ("__eq__",))
            # Entry-pair comparison reads the snapshot directly; only the
            # ordinary scalar/structural keyed sorter needs a parallel vector.
            keys = None if entry_pairs else collections.new_list(e, member)
            indices = e.allocated_value(f"call ptr @pyjs.list.new.owned(ptr {scratch}, ptr null, ptr null, i64 8, i64 {length})")
            index_data = collections.storage(e, indices, 2)
            # Capacity is already reserved. Publish only initialized positions
            # as we fill the vector, without append growth or a second counter.
            e.emit_line(f"store i64 0, ptr {indices}")
            roots = calls.root_values(e, keys) if keys is not None else None

            def remember(actual, item):
                offset = e.emit_value(f"load i64, ptr {indices}")
                slot = e.emit_value(f"getelementptr i64, ptr {index_data}, i64 {offset}")
                e.emit_line(f"store i64 {offset}, ptr {slot}")
                e.emit_line(f"store i64 {e.emit_value(f'add i64 {offset}, 1')}, ptr {indices}")
                if keys is not None:
                    collections.append(e, keys, member, actual, item, self.node)

            collections.loop(e, semantic, snapshot, remember, self.node)
            e.emit_line(f"store ptr {indices}, ptr {index_slot}")
            sort, prepared = e.new_label("json.sort"), e.new_label("json.sort.prepared")
            e.emit_line(f"br i1 {self.flag('sort_keys')}, label %{sort}, label %{prepared}")
            e.emit_line(f"{sort}:")
            if entry_pairs:
                # CPython sorts items(), not keys: application equality runs
                # before ordering and equal keys fall through to their values.
                callback_ops.sort_structural(e, indices, integer, "false", self.node,
                    less=lambda left, right: self.entry_less(semantic, snapshot, left, right))
            else:
                collections.sort_prepared(e, indices, integer, keys, member, "false", self.node)
            e.emit_line(f"br label %{prepared}")
            e.emit_line(f"{prepared}:")
            calls.pop_roots(e, roots)
            e.emit_line(f"br label %{ready}")
            e.emit_line(f"{ready}:")
            value = e.emit_value(f"load ptr, ptr {field('snapshot')}")
            indices = e.emit_value(f"load ptr, ptr {index_slot}")
            slots = collections.storage(e, indices, 2)
            position = e.emit_value(f"load i64, ptr {e.emit_value(f'getelementptr i64, ptr {slots}, i64 {index}')}")
        data = collections.storage(e, value, 2)
        if collections.builtin_name(semantic) == "tuple" and not semantic.tuple_variadic:
            prefix()
            cases = [e.new_label("json.tuple.item") for _ in semantic.generic_types]
            invalid = e.new_label("json.tuple.invalid")
            e.emit_line(f"switch i64 {index}, label %{invalid} [" + " ".join(
                f"i64 {position}, label %{label}" for position, label in enumerate(cases)) + "]")
            e.emit_line(f"{invalid}:")
            e.emit_line("unreachable")
            layout = e.tuple_type(semantic, self.node)
            for position, (member, label) in enumerate(zip(semantic.generic_types.values(), cases, strict=True)):
                e.emit_line(f"{label}:")
                address = collections.field(e, data, layout, position)
                current = e.emit_value(f"load {e.value_type(member)}, ptr {address}")
                self.value(member, current, child_depth)
                e.emit_line(f"br label %{done}")
        else:
            member = collections.item_type(semantic)
            kind = e.value_type(member)
            address = e.emit_value(f"getelementptr {kind}, ptr {data}, i64 {position}")
            current = e.emit_value(f"load {kind}, ptr {address}")
            if mapping:
                key = self.key(member, current)
                include = e.new_label("json.key.include")
                e.emit_line(f"br i1 {e.emit_value(f'icmp ne ptr {key}, null')}, label %{include}, label %{done}")
                e.emit_line(f"{include}:")
                prefix()
                self.quoted(key)
                self.append(self.key_separator)
                kind = e.value_type(semantic.generic_types["V"])
                address = e.emit_value(f"getelementptr {kind}, ptr {collections.storage(e, value, 3)}, i64 {position}")
                current = e.emit_value(f"load {kind}, ptr {address}")
                member = semantic.generic_types["V"]
            else:
                prefix()
            self.value(member, current, child_depth)
            e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")

    def entry_less(self, semantic, snapshot, left, right):
        """Lexicographic (key, value) ordering without allocating tuple wrappers."""
        e = self.e
        result = e.emit_value("alloca i1")
        e.emit_line(f"store i1 false, ptr {result}")
        done = e.new_label("json.entries.compared")
        for field, member in zip((2, 3), semantic.generic_types.values(), strict=True):
            kind, data = e.value_type(member), collections.storage(e, snapshot, field)
            a, b = (e.emit_value(f"load {kind}, ptr {e.emit_value(f'getelementptr {kind}, ptr {data}, i64 {index}')}")
                    for index in (left, right))
            equal = comparisons.equal_value(e, member, a, member, b, self.node)
            same, different = e.new_label("json.entries.same"), e.new_label("json.entries.different")
            e.emit_line(f"br i1 {equal}, label %{same}, label %{different}")
            e.emit_line(f"{different}:")
            less = comparisons.order_value(e, "__lt__", member, a, member, b, self.node)
            e.emit_line(f"store i1 {less}, ptr {result}")
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{same}:")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
        return e.emit_value(f"load i1, ptr {result}")


def definitions(parent):
    from .llvm import FunctionEmitter

    output, emitted = [], set()
    while pending := [key for key in parent.module.json_walkers if key not in emitted]:
        for key in pending:
            emitted.add(key)
            semantic, pretty, sorted_keys, callbacks = key
            symbol, node = parent.module.json_walkers[key]
            e = FunctionEmitter(parent.module)
            e.stack_allocations = []
            e.allocation_node = node
            e.return_type = e.return_storage_type = "void"
            parameters = ("__arena", "__heap", "__exception", "output", "state", "frame")
            for name in parameters[:3]:
                e.slots[name], e.slot_types[name] = f"%slot.{name}", "ptr"
                e.emit_line(f"%slot.{name} = alloca ptr")
                e.emit_line(f"store ptr %{name}, ptr %slot.{name}")
            e.gc_frame = calls.push_roots(e, []) if e.module.uses_gc else None
            Encoder(e, node, output="%output", state="%state", pretty=pretty,
                    sorted_keys=sorted_keys, callbacks=callbacks).step(semantic)
            calls.pop_roots(e, e.gc_frame)
            e.emit_line("ret void")
            e.emit_line("pyjs.exception.return:")
            e.restore_gc_frame()
            calls.pop_roots(e, e.gc_frame)
            e.emit_line("ret void")
            signature = ", ".join(f"ptr %{name}" for name in parameters)
            output.extend([f"define private void @{symbol}({signature}) {{", "entry:",
                           *(f"  {line}" for line in (*e.stack_allocations, *e.lines)), "}"])
    return output

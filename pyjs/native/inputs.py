"""Concrete host ABI layouts and entry-point input promotion."""

from dataclasses import replace

from . import gc_layouts, tagged
from .errors import LLVMUnsupported


def validate_record_cycles(parameters, definitions, node):
    """Check completed schemas, independent of alias memoization order.

    A completed alias can still lead back through a pending mutual alias while
    schemas are being built. Inspecting only pending cache hits misses those
    record cycles. The small ABI graph is finite; walk it by node identity, not
    display name or structural equality. Only records that reach themselves
    are forbidden: a finite record pointing into a container cycle is valid.
    """
    shapes, edges = {}, {}
    pending = [parameter.value_type for parameter in parameters]
    while pending:
        shape = pending.pop().resolve(definitions)
        key = id(shape)
        if key in shapes:
            continue
        shapes[key] = shape
        children = [*shape.members, *(field.value_type for field in shape.fields),
                    *(item for item in (shape.item_type, shape.key_type) if item is not None)]
        edges[key] = [id(child.resolve(definitions)) for child in children]
        pending.extend(children)
    for key, shape in shapes.items():
        if shape.kind != "object":
            continue
        pending, seen = list(edges[key]), set()
        while pending:
            child = pending.pop()
            if child == key:
                raise LLVMUnsupported(f"LLVM library inputs cannot contain recursive {shape.name}", node)
            if child not in seen:
                seen.add(child)
                pending.extend(edges[child])


def storage(value, definitions=()):
    value = value.resolve(definitions)
    if value.kind == "union":
        return tagged.STORAGE
    if value.kind == "optional":
        # Optional scalar payloads retain the common wide representation even
        # when the present value is normalized to a portable numeric width.
        member = {"bool": "i1", "int": "i64", "float": "double"}.get(value.item_type.resolve(definitions).kind, "ptr")
        return "ptr" if member == "ptr" else "{ i1, " + member + " }"
    if value.numeric_format is not None:
        number = value.numeric_format
        return ("float" if number.bits == 32 else "double") if number.kind == "float" else f"i{number.bits}"
    return {"bool": "i1", "int": "i64", "float": "double"}.get(value.kind, "ptr")


def needs_copy(value, definitions=()):
    """Only reference-bearing inputs need promotion or an ownership snapshot."""
    value = value.resolve(definitions)
    if value.kind == "union":
        return any(needs_copy(member, definitions) for member in value.members)
    if value.kind == "optional":
        return needs_copy(value.item_type, definitions)
    return storage(value, definitions) == "ptr" and value.kind != "NoneType"


def prepare(emitter):
    """Use LLVM constant layout expressions, never duplicate ABI alignment."""
    module = emitter.module
    definitions = module.abi_type_definitions
    module.input_shapes = {}
    module.input_definitions = [
        "%pyjs.input.shape = type { i64, i64, ptr, i64, i1, ptr, i64, ptr, ptr, ptr, i1 }",
        "%pyjs.input.field = type { i64, ptr, i64, i64, i1, i64, ptr }",
    ]

    def size(layout):
        return f"ptrtoint (ptr getelementptr ({layout}, ptr null, i32 1) to i64)"

    def shape(value):
        value = value.resolve(definitions)
        if not needs_copy(value, definitions):
            return "null"
        if value.kind == "optional":
            return shape(value.item_type)
        if value in module.input_shapes:
            return module.input_shapes[value]
        name = f"@pyjs.input.shape.{len(module.input_shapes)}"
        module.input_shapes[value] = name
        fields = []
        references = []
        allocator = "-1"
        extra_allocator = "0"
        item_allocator = extra_item_allocator = "null"
        text = value.kind in {"str", "bytes"}

        def offset(layout, index):
            return f"ptrtoint (ptr getelementptr ({layout}, ptr null, i32 0, i32 {index}) to i64)"

        def field(layout, index, child, *, count="-1", stride="0", optional=False, tag=0, kind="ptr"):
            # The copy plan already identifies every reference-bearing field.
            # An inline tagged slot traces its payload, not the discriminator.
            references.append((index, 1) if count == "-1" and kind == tagged.STORAGE else (index,))
            buffer_trace = ("@pyjs.gc.descriptor.references" if gc_layouts.reference_paths((kind,))
                            else "@pyjs.gc.descriptor.atomic")
            fields.append("%pyjs.input.field { "
                          f"i64 {offset(layout, index)}, ptr {child}, i64 {count}, "
                          f"i64 {stride}, i1 {str(optional).lower()}, i64 {tag}, ptr {buffer_trace}" + " }")

        if value.kind == "union":
            layout = tagged.STORAGE
            for member in value.members:
                child = shape(member)
                if child != "null":
                    field(layout, 1, child, tag=(member.runtime_tag if member.runtime_tag is not None
                                                else tagged.TAGS[member.kind]))
        elif value.kind in {"str", "bytes"}:
            layout = "%pyjs.string"
            # Immutable bytes are coallocated with their header. The data
            # pointer is internal, not a separately owned field to copy/trace.
        elif value.kind in {"list", "tuple"}:
            layout = "%pyjs.list"
            allocator = offset(layout, 3)
            if value.item_type is not None:
                kind = storage(value.item_type, definitions)
                item_allocator = gc_layouts.item_allocator(kind)
                field(layout, 2, shape(value.item_type), count="0", stride=size(kind), kind=kind)
            else:
                field(layout, 2, shape(replace(value, kind="object")))
        elif value.kind in {"dict", "set", "frozenset"}:
            layout = "%pyjs.dict"
            allocator = offset(layout, 4)
            extra_allocator = offset(layout, 9)
            key = value.key_type if value.kind == "dict" else value.item_type
            key_kind = storage(key, definitions)
            value_kind = storage(value.item_type, definitions) if value.kind == "dict" else "i1"
            item_allocator = gc_layouts.item_allocator(key_kind)
            extra_item_allocator = gc_layouts.item_allocator(value_kind)
            field(layout, 2, shape(key), count="0", stride=size(key_kind), kind=key_kind)
            field(layout, 3, shape(value.item_type) if value.kind == "dict" else "null",
                  count="0", stride=size(value_kind), kind=value_kind)
            # Raw ABI callers can supply mappings whose repr has enabled
            # logical insertion positions. That mutable buffer is owned too.
            field(layout, 6, "null", count="0", stride="8", optional=True, kind="i64")
            field(layout, 8, "null", count="0", stride="8", optional=True, kind="i64")
        else:
            prefix = ["ptr"] if value.identity else []
            layout = "{ " + ", ".join([*prefix, *(storage(item.value_type, definitions) for item in value.fields)]) + " }"
            for index, item in enumerate(value.fields):
                child = shape(item.value_type)
                if child != "null":
                    field(layout, index + len(prefix), child, kind=storage(item.value_type, definitions))
        trace = gc_layouts.descriptor(emitter, layout, tuple(dict.fromkeys(references)))
        field_name = name + ".fields"
        module.input_definitions += [
            f"{field_name} = private constant [{len(fields)} x %pyjs.input.field] [" + ", ".join(fields) + "]",
            f"{name} = private constant %pyjs.input.shape {{ i64 {size(layout)}, i64 {len(fields)}, "
            f"ptr {field_name}, i64 {allocator}, i1 {str(value.kind == 'union').lower()}, "
            f"ptr {'@' + value.identity if value.identity else 'null'}, i64 {extra_allocator}, "
            f"ptr {trace}, ptr {item_allocator}, ptr {extra_item_allocator}, i1 {str(text).lower()} }}",
        ]
        return name

    for parameter in module.abi_parameters:
        shape(parameter.value_type)


def enter(wrapper, result, call_arguments):
    """Copy at the host boundary, not on internal/recursive application calls.

    No safe point occurs during copying. The callee installs its normal roots
    before collecting, so this wrapper needs neither a second frame nor a second
    version of the application's function body. Failure skips user handlers.
    """
    module = wrapper.module
    definitions = module.abi_type_definitions
    if not module.uses_gc:
        return False
    parameters = [(index, parameter) for index, parameter in enumerate(module.abi_parameters)
                  if needs_copy(parameter.value_type, definitions)]
    if not parameters:
        return False
    from .llvm import FunctionEmitter

    emitter = FunctionEmitter(module)
    emitter.current_function = module.entry_function
    for name in ("arena", "heap", "exception"):
        slot = f"%input.{name}.slot"
        emitter.slots["__" + name] = slot
        emitter.slot_types["__" + name] = "ptr"
        emitter.emit_line(f"{slot} = alloca ptr")
        emitter.emit_line(f"store ptr %{name}, ptr {slot}")
    arena, heap = emitter.load_local("__arena"), emitter.load_local("__heap")
    memo = emitter.allocated_value(f"call ptr @pyjs.identity.try.new(ptr {arena})")
    snapshot = emitter.allocated_value(f"call ptr @pyjs.input.try.ownership(ptr {arena}, ptr {heap}, i1 %check.owned)")
    owned = emitter.emit_value(f"select i1 %check.owned, ptr {snapshot}, ptr null")
    offset = len(call_arguments) - len(module.abi_parameters)
    for index, parameter in parameters:
        value = parameter.value_type.resolve(definitions)
        shape = module.input_shapes[value.item_type.resolve(definitions) if value.kind == "optional" else value]
        kind = storage(value, definitions)
        original = call_arguments[offset + index].removeprefix(kind + " ")
        if kind == tagged.STORAGE:
            slot = emitter.emit_value(f"alloca {kind}")
            emitter.emit_line(f"store {kind} {original}, ptr {slot}")
            original = slot
        promoted = emitter.emit_value(f"call ptr @pyjs.input.try.copy(ptr {arena}, ptr {heap}, ptr {memo}, ptr {original}, ptr {shape}, ptr @pyjs.gc.alloc.adapter, ptr {owned})")
        valid = emitter.emit_value(f"icmp ne ptr {promoted}, null")
        if value.kind == "optional":
            absent = emitter.emit_value(f"icmp eq ptr {original}, null")
            valid = emitter.emit_value(f"or i1 {valid}, {absent}")
        emitter.guard_exception(emitter.current_function.original_node, valid, "MemoryError", "native input promotion failed")
        if kind == tagged.STORAGE:
            promoted = emitter.emit_value(f"load {kind}, ptr {promoted}")
        call_arguments[offset + index] = f"{kind} {promoted}"
    # The wrapper's arena contains only promotion scratch so far. Every
    # published copy is heap-owned; release memo/index storage before the body
    # can collect and need a second heap-sized index. Failure uses the wrapper's
    # ordinary arena cleanup instead. Reinitialize for the application's use.
    emitter.emit_line(f"call void @pyjs.arena.destroy(ptr {arena})")
    emitter.emit_line(f"call void @pyjs.arena.init(ptr {arena})")
    result.extend(f"  {line}" for line in emitter.lines)
    return True

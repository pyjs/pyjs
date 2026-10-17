"""Trace managed aggregate fields using the same storage as their LLVM layout.

Descriptors are registered while emitting allocations, then rendered after
all bodies and adapters. Numeric lanes are not pointer candidates; tagged
payloads retain the collector's conservative address validation.
"""

from . import tagged


def reference_paths(fields):
    paths = []
    for index, kind in enumerate(fields):
        if kind == "ptr":
            paths.append((index,))
        elif kind == tagged.STORAGE:
            paths.append((index, 1))
        elif kind == "%pyjs.exception":
            # Generator handlers embed snapshots, not pointers to stack records.
            # Trace pointer lanes, including lazy payload/message references;
            # exception type/origin tokens are immortal and harmless to visit.
            paths.extend((index, field) for field in range(1, 6))
    return tuple(paths)


def descriptor(emitter, layout, references):
    if not references:
        return "@pyjs.gc.descriptor.atomic"
    key = layout, references
    descriptors = emitter.module.gc_descriptors
    if key not in descriptors:
        descriptors[key] = f"pyjs.gc.layout.{len(descriptors)}"
    return "@" + descriptors[key]


def allocate(emitter, fields, *, layout=None, managed=True, size=None):
    layout = layout or "{ " + ", ".join(fields) + " }"
    size = size or emitter.llvm_size(layout)
    if managed and emitter.module.uses_gc:
        trace = descriptor(emitter, layout, reference_paths(fields))
        return emitter.allocated_value(
            f"call ptr @pyjs.gc.alloc.described(ptr {emitter.load_local('__heap')}, "
            f"i64 {size}, ptr {trace})")
    return emitter.allocated_value(
        f"call ptr @pyjs.arena.try.alloc(ptr {emitter.load_local('__arena')}, "
        f"i64 {size}, i64 8)")


def allocator(emitter, layout, references):
    """Adapt a fixed descriptor to the runtime's owned-allocation callback."""
    trace = descriptor(emitter, layout, references)
    if trace == "@pyjs.gc.descriptor.atomic":
        return "@pyjs.gc.alloc.atomic.adapter"
    emitter.module.gc_allocators.add(trace)
    return trace + ".allocate"


def item_allocator(kind):
    """Homogeneous backing buffers contain either reference lanes or scalars."""
    return "@pyjs.gc.alloc.references.adapter" if reference_paths((kind,)) else "@pyjs.gc.alloc.atomic.adapter"


def _managed_allocator():
    return [
        "  %generic = icmp eq ptr %allocator, @pyjs.gc.alloc.adapter",
        "  %atomic = icmp eq ptr %allocator, @pyjs.gc.alloc.atomic.adapter",
        "  %references = icmp eq ptr %allocator, @pyjs.gc.alloc.references.adapter",
        "  %typed = or i1 %atomic, %references",
        "  %managed = or i1 %generic, %typed",
    ]


def scalar_allocator(managed):
    lines = ["define ptr @pyjs.collection.scalar.allocator(ptr %allocator) {", "entry:"]
    if managed:
        lines.extend(_managed_allocator())
        lines.extend([
            "  %result = select i1 %managed, ptr @pyjs.gc.alloc.atomic.adapter, ptr %allocator",
            "  ret ptr %result",
        ])
    else:
        lines.append("  ret ptr %allocator")
    return [*lines, "}"]


def owned_header(emitter, name, layout, references, *, trace=None, atomic_payload=False):
    # A header's stored callback allocates *payloads*, including future growth.
    # Do not interpret arbitrary callback contexts as heaps: only our three
    # known GC callbacks select this descriptor. Foreign/arena owners pass on.
    lines = [
        f"define ptr @pyjs.{name}.allocate.header(ptr %arena, ptr %allocator, ptr %context, i64 %size) {{",
        "entry:",
    ]
    if emitter.module.uses_gc:
        trace = trace or descriptor(emitter, layout, references)
        lines.extend([
            *_managed_allocator(),
            "  br i1 %managed, label %heap, label %fallback",
            "heap:",
        ])
        if atomic_payload:
            # Coallocated immutable payloads have no external header references.
            # A scalar owner can skip tracing the whole allocation; reference
            # owners scan payload lanes without treating header metadata as data.
            lines.append(f"  %trace = select i1 %atomic, ptr @pyjs.gc.descriptor.atomic, ptr {trace}")
            trace = "%trace"
        lines.extend([
            f"  %managed.result = call ptr @pyjs.gc.alloc.described(ptr %context, i64 %size, ptr {trace})",
            "  ret ptr %managed.result",
            "fallback:",
        ])
    lines.extend([
        "  %result = call ptr @pyjs.collection.try.alloc(ptr %arena, ptr %allocator, ptr %context, i64 %size)",
        "  ret ptr %result",
        "}",
    ])
    return lines


def definitions(emitter):
    output = []
    for (layout, references), name in emitter.module.gc_descriptors.items():
        cases = " ".join(f"i64 {index}, label %field.{index}" for index in range(len(references)))
        output.extend([
            f"@{name} = private constant %pyjs.gc.descriptor {{ i64 {len(references)}, ptr @{name}.trace }}",
            f"define private ptr @{name}.trace(ptr %object, i64 %index) {{",
            "entry:",
            f"  switch i64 %index, label %invalid [ {cases} ]",
        ])
        for index, path in enumerate(references):
            indices = ", ".join(f"i32 {field}" for field in (0, *path))
            output.extend([
                f"field.{index}:",
                f"  %slot.{index} = getelementptr {layout}, ptr %object, {indices}",
                f"  %value.{index} = load ptr, ptr %slot.{index}",
                f"  ret ptr %value.{index}",
            ])
        output.extend(["invalid:", "  call void @llvm.trap()", "  unreachable", "}"])
        if "@" + name in emitter.module.gc_allocators:
            output.extend([
                f"define private ptr @{name}.allocate(ptr %heap, i64 %size) {{",
                "entry:",
                f"  %value = call ptr @pyjs.gc.alloc.described(ptr %heap, i64 %size, ptr @{name})",
                "  ret ptr %value",
                "}",
            ])
    return output

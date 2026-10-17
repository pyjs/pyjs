"""Arena-owned native DOM construction and iterative HTML serialization."""

import ctypes

from pyjs import int8, int32

from .algorithms import _runtime, _utf8_bytes, bytes_equal
from .arena import allocate_in_arena
from .buffers import (
    ERROR_OFFSET,
    append_bytes,
    append_string,
    finish_memory,
    flush,
    new_output,
)
from .escaping import write_html
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    bytes_data,
    copy,
    is_null,
    load_int8,
    load_int32,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    store_int8,
    store_int32,
    store_integer,
    store_pointer,
)
from .sequences import ITEMS_OFFSET, append_slot, reserve, try_new_list
from .text_operations import STRING_DATA_OFFSET, new_owned


class _Attribute(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("value", ctypes.c_void_p)]


class _Argument(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int8), ("payload", ctypes.c_void_p)]


class _Element(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("arguments", ctypes.c_void_p),
                ("reference", ctypes.c_int8), ("form_value", ctypes.c_void_p)]


PAYLOAD_OFFSET = _Argument.payload.offset
VALUE_OFFSET = _Attribute.value.offset
ARGUMENTS_OFFSET = _Element.arguments.offset
REFERENCE_OFFSET = _Element.reference.offset
FORM_VALUE_OFFSET = _Element.form_value.offset
POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)
ARGUMENT_SIZE = ctypes.sizeof(_Argument)
ATTRIBUTE_SIZE = ctypes.sizeof(_Attribute)
ELEMENT_SIZE = ctypes.sizeof(_Element)


@_runtime
def new_attribute(arena: Pointer, name: Pointer, value: Pointer) -> Pointer:
    attribute = allocate_in_arena(arena, ATTRIBUTE_SIZE, 8)
    if is_null(attribute):
        return null()
    store_pointer(attribute, name)
    store_pointer(byte_offset(attribute, VALUE_OFFSET), value)
    return attribute


@_runtime
def new_argument(arena: Pointer, kind: int8, payload: Pointer) -> Pointer:
    argument = allocate_in_arena(arena, ARGUMENT_SIZE, 8)
    if is_null(argument):
        return null()
    store_int8(argument, kind)
    store_pointer(byte_offset(argument, PAYLOAD_OFFSET), payload)
    return argument


@_runtime
def new_element(arena: Pointer, document: Pointer, name: Pointer, arguments: Pointer) -> Pointer:
    """Copy a borrowed pack; immutable records and payloads remain shared."""
    length = load_integer(arguments)
    owned = try_new_list(arena, null(), null(), POINTER_SIZE, length)
    if is_null(owned):
        return null()
    copy(load_pointer(byte_offset(owned, ITEMS_OFFSET)),
         load_pointer(byte_offset(arguments, ITEMS_OFFSET)), length * POINTER_SIZE)
    return new_element_owned(arena, document, name, owned)


@_runtime
def new_element_owned(arena: Pointer, document: Pointer, name: Pointer, arguments: Pointer) -> Pointer:
    """Adopt a fresh arena pack. The caller must relinquish mutation/sharing.

    Generated builders already create a private pack, so adoption avoids a
    redundant copy. Only the list header/buffer is exclusive; its immutable
    argument records, strings and child identities may belong to other packs.
    """
    element = allocate_in_arena(arena, ELEMENT_SIZE, 8)
    if is_null(element):
        return null()
    store_pointer(element, name)
    store_pointer(byte_offset(element, ARGUMENTS_OFFSET), arguments)
    store_int8(byte_offset(element, REFERENCE_OFFSET), int8(0))
    store_pointer(byte_offset(element, FORM_VALUE_OFFSET), null())
    return element


@_runtime
def form_value(element: Pointer) -> Pointer:
    """A null slot means the control's initial empty value, not its attribute."""
    return load_pointer(byte_offset(element, FORM_VALUE_OFFSET))


@_runtime
def set_form_value(element: Pointer, value: Pointer) -> None:
    """Publish already arena-owned text; serializers ignore this live state."""
    store_pointer(byte_offset(element, FORM_VALUE_OFFSET), value)


@_runtime
def mark_reference(element: Pointer) -> None:
    if not is_null(element):
        store_int8(byte_offset(element, REFERENCE_OFFSET), int8(1))


@_runtime
def bind_reference(arena: Pointer, owner: Pointer, element: Pointer, name: Pointer,
                   id_name: Pointer, identity_name: Pointer) -> int8:
    """Assign a hydration id before the application field/setter is published.

    Return 0 on success, 1 for an existing id, and 2 on allocation failure.
    The marker belongs to the node, not its incoming expression or wrapper.
    """
    if is_null(element) or load_int8(byte_offset(element, REFERENCE_OFFSET)) == int8(0):
        return int8(0)
    return assign_reference(arena, owner, element, name, id_name, identity_name)


@_runtime
def assign_reference(arena: Pointer, owner: Pointer, element: Pointer, name: Pointer,
                     id_name: Pointer, identity_name: Pointer) -> int8:
    """Assign a checked id after either the DOM or proxy marker was tested."""
    if not is_null(attribute_get(load_pointer(byte_offset(element, ARGUMENTS_OFFSET)), id_name)):
        return int8(1)
    identity = attribute_get(load_pointer(byte_offset(owner, ARGUMENTS_OFFSET)), identity_name)
    prefix = _utf8_bytes("None") if is_null(identity) else borrow_bytes(identity)
    suffix = borrow_bytes(name)
    first = len(prefix)
    second = len(suffix)
    if first > 9223372036854775806 - second:
        return int8(2)
    # IDs are usually tiny and remain live with the DOM. A rendering output
    # would retain its minimum 4 KiB buffer for each id until arena destruction.
    value = new_owned(arena, null(), null(), first + 1 + second)
    if is_null(value):
        return int8(2)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    copy(data, bytes_data(prefix), first)
    store_int8(byte_offset(data, first), int8(45))
    copy(byte_offset(data, first + 1), bytes_data(suffix), second)
    attribute = new_attribute(arena, id_name, value)
    if is_null(attribute) or not change_attribute(arena, element, id_name, attribute):
        return int8(2)
    return int8(0)


@_runtime
def extend_elements(arena: Pointer, arguments: Pointer, elements: Pointer) -> bool:
    index = 0
    while index < load_integer(elements):
        element = load_pointer(pointer_slot(load_pointer(byte_offset(elements, ITEMS_OFFSET)), index))
        argument = new_argument(arena, int8(2), element)
        if is_null(argument):
            return False
        slot = append_slot(arena, arguments, POINTER_SIZE)
        if is_null(slot):
            return False
        store_pointer(slot, argument)
        index += 1
    return True


@_runtime
def is_void(name: bytes) -> bool:
    # Kept in sync with the canonical SSR tags by the raw runtime test. Scalar
    # comparisons avoid constructing a managed tuple/set inside the renderer.
    length = len(name)
    if length == 2:
        return bytes_equal(name, _utf8_bytes("br")) or bytes_equal(name, _utf8_bytes("hr"))
    if length == 3:
        return (bytes_equal(name, _utf8_bytes("col")) or
                bytes_equal(name, _utf8_bytes("img")) or
                bytes_equal(name, _utf8_bytes("wbr")))
    if length == 4:
        return (bytes_equal(name, _utf8_bytes("area")) or bytes_equal(name, _utf8_bytes("base")) or
                bytes_equal(name, _utf8_bytes("link")) or bytes_equal(name, _utf8_bytes("meta")))
    if length == 5:
        return (bytes_equal(name, _utf8_bytes("embed")) or
                bytes_equal(name, _utf8_bytes("input")) or
                bytes_equal(name, _utf8_bytes("param")) or
                bytes_equal(name, _utf8_bytes("track")))
    return length == 6 and bytes_equal(name, _utf8_bytes("source"))


@_runtime
def work_push(arena: Pointer, work: Pointer, kind: int8, payload: Pointer) -> bool:
    slot = append_slot(arena, work, ARGUMENT_SIZE)
    if is_null(slot):
        return False
    store_int8(slot, kind)
    store_pointer(byte_offset(slot, PAYLOAD_OFFSET), payload)
    return True


@_runtime
def _literal(output: Pointer, value: bytes) -> None:
    append_bytes(output, bytes_data(value), len(value))


@_runtime
def write_element(output: Pointer, root: Pointer) -> None:
    error = byte_offset(output, ERROR_OFFSET)
    if load_int32(error) != int32(0):
        return
    arena = load_pointer(output)
    work = try_new_list(arena, null(), null(), ARGUMENT_SIZE, 0)
    if is_null(work) or not work_push(arena, work, int8(2), root):
        store_int32(error, int32(12))
        return
    # Explicit LIFO avoids native-stack recursion on adversarially deep DOMs.
    # Its arena is private and cannot collect; popped slots need no GC clearing.
    while load_integer(work) > 0 and load_int32(error) == int32(0):
        index = load_integer(work) - 1
        slot = byte_offset(load_pointer(byte_offset(work, ITEMS_OFFSET)), index * ARGUMENT_SIZE)
        kind = load_int8(slot)
        payload = load_pointer(byte_offset(slot, PAYLOAD_OFFSET))
        store_integer(work, index)
        if kind == int8(3):
            write_html(output, payload, False)
        elif kind == int8(4):
            _literal(output, _utf8_bytes("</"))
            append_string(output, load_pointer(payload))
            _literal(output, _utf8_bytes(">"))
        elif kind == int8(2):
            name = load_pointer(payload)
            arguments = load_pointer(byte_offset(payload, ARGUMENTS_OFFSET))
            length = load_integer(arguments)
            data = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
            _literal(output, _utf8_bytes("<"))
            append_string(output, name)
            has_children = False
            index = 0
            while index < length and load_int32(error) == int32(0):
                argument = load_pointer(pointer_slot(data, index))
                if load_int8(argument) != int8(1):
                    has_children = True
                else:
                    attribute = load_pointer(byte_offset(argument, PAYLOAD_OFFSET))
                    attribute_name = load_pointer(attribute)
                    previous = 0
                    duplicate = False
                    while previous < index and not duplicate:
                        prior = load_pointer(pointer_slot(data, previous))
                        if load_int8(prior) == int8(1):
                            prior_attribute = load_pointer(byte_offset(prior, PAYLOAD_OFFSET))
                            duplicate = bytes_equal(borrow_bytes(load_pointer(prior_attribute)), borrow_bytes(attribute_name))
                        previous += 1
                    if not duplicate:
                        # Emit the last value at the first attribute's
                        # position, without modifying shared argument packs.
                        value = attribute_get(arguments, attribute_name)
                        _literal(output, _utf8_bytes(" "))
                        append_string(output, attribute_name)
                        _literal(output, _utf8_bytes('="'))
                        write_html(output, value, True)
                        _literal(output, _utf8_bytes('"'))
                index += 1
            if load_int32(error) != int32(0):
                return
            if not has_children and is_void(borrow_bytes(name)):
                _literal(output, _utf8_bytes("/>"))
                continue
            _literal(output, _utf8_bytes(">"))
            if load_int32(error) != int32(0):
                return
            if not work_push(arena, work, int8(4), payload):
                store_int32(error, int32(12))
                return
            # Reverse pushes preserve source order when this LIFO is popped.
            index = length
            while index > 0:
                index -= 1
                argument = load_pointer(pointer_slot(data, index))
                child_kind = load_int8(argument)
                if child_kind == int8(2) or child_kind == int8(3):
                    child = load_pointer(byte_offset(argument, PAYLOAD_OFFSET))
                    if not work_push(arena, work, child_kind, child):
                        store_int32(error, int32(12))
                        return


@_runtime
def attribute_get(arguments: Pointer, name: Pointer) -> Pointer:
    data = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
    index = load_integer(arguments)
    while index > 0:
        index -= 1
        argument = load_pointer(pointer_slot(data, index))
        if load_int8(argument) == int8(1):
            payload = load_pointer(byte_offset(argument, PAYLOAD_OFFSET))
            if bytes_equal(borrow_bytes(load_pointer(payload)), borrow_bytes(name)):
                return load_pointer(byte_offset(payload, VALUE_OFFSET))
    return null()


@_runtime
def change_attribute(arena: Pointer, element: Pointer, name: Pointer, attribute: Pointer) -> bool:
    """Update owned pointer slots; a null attribute removes every match.

    Construction may share argument records. Never mutate those records
    in place, and leave the existing element untouched on allocation failure.
    Names/values in a replacement attribute already belong to the DOM arena.
    """
    arguments = load_pointer(byte_offset(element, ARGUMENTS_OFFSET))
    remove = is_null(attribute)
    present = not is_null(attribute_get(arguments, name))
    if remove and not present:
        return True
    length = load_integer(arguments)
    replacement = null() if remove else new_argument(arena, int8(1), attribute)
    if not remove and is_null(replacement):
        return False
    if not remove and not present:
        if length == 9223372036854775807 or not reserve(arena, arguments, length + 1, POINTER_SIZE):
            return False
    # Allocation is finished. Compact/update the exclusive pointer list, not
    # its shared records. Copying all children for every attribute change would
    # make mixed append/update loops retain quadratic arena memory again.
    data = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
    index = 0
    count = 0
    inserted = False
    while index < length:
        argument = load_pointer(pointer_slot(data, index))
        matching = False
        if load_int8(argument) == int8(1):
            current = load_pointer(byte_offset(argument, PAYLOAD_OFFSET))
            matching = bytes_equal(borrow_bytes(load_pointer(current)), borrow_bytes(name))
        if not matching:
            store_pointer(pointer_slot(data, count), argument)
            count += 1
        elif not remove and not inserted:
            store_pointer(pointer_slot(data, count), replacement)
            count += 1
            inserted = True
        index += 1
    if not remove and not inserted:
        store_pointer(pointer_slot(data, count), replacement)
        count += 1
    store_integer(arguments, count)
    return True


@_runtime
def extend_arguments(arena: Pointer, element: Pointer, additions: Pointer) -> bool:
    """Append staged arguments with amortized linear arena allocation."""
    extra = load_integer(additions)
    if extra == 0:
        return True
    arguments = load_pointer(byte_offset(element, ARGUMENTS_OFFSET))
    length = load_integer(arguments)
    if extra > 9223372036854775807 - length:
        return False
    # Each element owns its mutable list. Reserve grows geometrically: copying
    # the whole pack per append would retain quadratic bytes in this arena.
    # On failure reserve changes nothing; after it succeeds only infallible
    # copies/stores remain, with no callbacks or partially published children.
    if not reserve(arena, arguments, length + extra, POINTER_SIZE):
        return False
    output = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
    # Reload after reserve even for raw self-extension (additions == arguments).
    copy(byte_offset(output, length * POINTER_SIZE),
         load_pointer(byte_offset(additions, ITEMS_OFFSET)), extra * POINTER_SIZE)
    store_integer(arguments, length + extra)
    return True


@_runtime
def clear_children(element: Pointer) -> None:
    # Each element owns its pointer list, but can share the argument records.
    # Compact only those slots; attributes and other elements remain untouched.
    arguments = load_pointer(byte_offset(element, ARGUMENTS_OFFSET))
    data = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
    length = load_integer(arguments)
    index = 0
    retained = 0
    while index < length:
        argument = load_pointer(pointer_slot(data, index))
        if load_int8(argument) == int8(1):
            store_pointer(pointer_slot(data, retained), argument)
            retained += 1
        index += 1
    store_integer(arguments, retained)


@_runtime
def replace_children(arena: Pointer, element: Pointer, additions: Pointer) -> bool:
    """Replace children without changing attributes or publishing a partial pack."""
    extra = load_integer(additions)
    if extra == 0:
        clear_children(element)
        return True
    arguments = load_pointer(byte_offset(element, ARGUMENTS_OFFSET))
    length = load_integer(arguments)
    data = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
    retained = 0
    index = 0
    while index < length:
        argument = load_pointer(pointer_slot(data, index))
        if load_int8(argument) == int8(1):
            retained += 1
        index += 1
    if extra > 9223372036854775807 - retained:
        return False
    result = try_new_list(arena, null(), null(), POINTER_SIZE, retained + extra)
    if is_null(result):
        return False
    output = load_pointer(byte_offset(result, ITEMS_OFFSET))
    index = 0
    count = 0
    while index < length:
        argument = load_pointer(pointer_slot(data, index))
        if load_int8(argument) == int8(1):
            store_pointer(pointer_slot(output, count), argument)
            count += 1
        index += 1
    copy(byte_offset(output, retained * POINTER_SIZE),
         load_pointer(byte_offset(additions, ITEMS_OFFSET)), extra * POINTER_SIZE)
    store_pointer(byte_offset(element, ARGUMENTS_OFFSET), result)
    return True


@_runtime
def new_document(arena: Pointer) -> Pointer:
    return allocate_in_arena(arena, 1, 1)


@_runtime
def render_document(arena: Pointer, document: Pointer, root: Pointer) -> Pointer:
    output = new_output(arena, int32(-1))
    if is_null(output):
        return null()
    write_element(output, root)
    return finish_memory(output)


@_runtime
def text_content(arena: Pointer, root: Pointer) -> Pointer:
    """Collect descendant text iteratively, without markup or HTML escaping."""
    output = new_output(arena, int32(-1))
    if is_null(output):
        return null()
    work = try_new_list(arena, null(), null(), ARGUMENT_SIZE, 0)
    if is_null(work) or not work_push(arena, work, int8(2), root):
        store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
        return finish_memory(output)
    while load_integer(work) > 0 and load_int32(byte_offset(output, ERROR_OFFSET)) == int32(0):
        index = load_integer(work) - 1
        slot = byte_offset(load_pointer(byte_offset(work, ITEMS_OFFSET)), index * ARGUMENT_SIZE)
        kind = load_int8(slot)
        payload = load_pointer(byte_offset(slot, PAYLOAD_OFFSET))
        store_integer(work, index)
        if kind == int8(3):
            append_string(output, payload)
        else:
            arguments = load_pointer(byte_offset(payload, ARGUMENTS_OFFSET))
            data = load_pointer(byte_offset(arguments, ITEMS_OFFSET))
            index = load_integer(arguments)
            while index > 0:
                index -= 1
                argument = load_pointer(pointer_slot(data, index))
                kind = load_int8(argument)
                if kind == int8(2) or kind == int8(3):
                    child = load_pointer(byte_offset(argument, PAYLOAD_OFFSET))
                    if not work_push(arena, work, kind, child):
                        store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
                        return finish_memory(output)
    return finish_memory(output)


@_runtime
def set_text_content(arena: Pointer, element: Pointer, value: Pointer) -> bool:
    """The caller supplies arena-owned text; empty text removes all children."""
    if load_integer(value) == 0:
        clear_children(element)
        return True
    additions = try_new_list(arena, null(), null(), POINTER_SIZE, 1)
    if is_null(additions):
        return False
    argument = new_argument(arena, int8(3), value)
    if is_null(argument):
        return False
    store_pointer(load_pointer(byte_offset(additions, ITEMS_OFFSET)), argument)
    return replace_children(arena, element, additions)


@_runtime
def write_document(arena: Pointer, document: Pointer, root: Pointer, descriptor: int) -> int:
    # Reject before narrowing: otherwise an oversized descriptor could write
    # to an unrelated open file after truncation to the system-call ABI.
    if descriptor < 0 or descriptor > 2147483647:
        return 9
    output = new_output(arena, int32(descriptor))
    if is_null(output):
        return 12
    write_element(output, root)
    return int(flush(output))

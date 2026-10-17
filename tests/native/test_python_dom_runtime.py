import ctypes
import html
import tempfile

import pytest

from pyjs import int8, int32
from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import arena, buffers, dom_tokens, escaping, sequences
from pyjs.native.runtime import dom_storage as dom
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.pointers import Pointer, borrow_bytes, store_pointer
from pyjs.native.runtime.text import WHITESPACE
from pyjs.tooling.llvm import LLVM
from pyjs.web.ssr import VOID_ELEMENTS
from tests.native.runtime_failure import reject_native_allocations
from tests.native.runtime_support import runtime_functions, runtime_library, string

SOURCE = '''
    from pyjs.web.domx import div
    from pyjs.web.ssr import render_html

    def main() -> str:
        return render_html(div("hello"))
'''


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def dom_runtime(request, tmp_path_factory):
    # HTML escaping is a private compiled dependency, not a public runtime ABI.
    # Export a test-only entry to exercise its raw buffer/error contract.
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm(SOURCE) + "\n" + "\n".join(
        compile_runtime({"test.write.html": escaping.write_html}, dependencies={
            "pyjs.native.output.append.bytes": buffers.append_bytes})))
    return runtime_functions({
        "test.write.html": escaping.write_html,
        "pyjs.native.document.new": dom.new_document,
        "pyjs.native.attribute.new": dom.new_attribute,
        "pyjs.native.attribute.get": dom.attribute_get,
        "pyjs.native.attribute.change": dom.change_attribute,
        "pyjs.native.element.extend": dom.extend_arguments,
        "pyjs.native.element.replace.children": dom.replace_children,
        "pyjs.native.element.text": dom.text_content,
        "pyjs.native.element.text.set": dom.set_text_content,
        "pyjs.native.element.value": dom.form_value,
        "pyjs.native.element.value.set": dom.set_form_value,
        "pyjs.native.class.query": dom_tokens.class_query,
        "pyjs.native.class.mutate": dom_tokens.class_mutate,
        "pyjs.native.argument.new": dom.new_argument,
        "pyjs.native.element.new": dom.new_element,
        "pyjs.native.element.new.owned": dom.new_element_owned,
        "pyjs.native.element.ref": dom.mark_reference,
        "pyjs.native.element.bind.ref": dom.bind_reference,
        "pyjs.native.document.render": dom.render_document,
        "pyjs.native.document.write": dom.write_document,
        "pyjs.list.new.owned": sequences.new_list,
        "pyjs.list.try.append.slot": sequences.append_slot,
    }, library)


@pytest.fixture
def owner():
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    try:
        yield pointer
    finally:
        arena.destroy_arena(pointer)


def pointer(value):
    return Pointer(ctypes.addressof(value))


def test_html_escaping_preserves_prefix_and_prior_failure(dom_runtime, owner):
    values = ["", "'\"&<>\\", "".join(map(chr, range(128))),
              "é雪🙂é\u2028\U0010ffff", "<plain é>" * 1000]
    for value in values:
        source = string(value.encode())
        for attribute in (False, True):
            target = buffers.new_output(owner, int32(-1))
            prefix = ctypes.create_string_buffer(b"prefix:")
            assert buffers.append_bytes(target, pointer(prefix), 7) == 0
            assert dom_runtime("test.write.html", target, pointer(source), attribute) == 0
            output = buffers._Output.from_address(target.address)
            assert ctypes.string_at(output.data, output.length) == (
                b"prefix:" + html.escape(value, quote=attribute).encode())
            before = (output.data, output.length, output.capacity, output.owner)
            output.error = 9
            # Sticky failure must be observed before inspecting absent input.
            assert dom_runtime("test.write.html", target, Pointer(0), attribute) == 9
            assert (output.data, output.length, output.capacity, output.owner) == before
            assert buffers.flush(target) == 9


def argument_list(invoke, owner, records):
    arguments = invoke("pyjs.list.new.owned", owner, Pointer(0), Pointer(0), 8, 0)
    for record in records:
        slot = invoke("pyjs.list.try.append.slot", owner, arguments, 8)
        assert slot.address
        store_pointer(slot, record)
    return arguments


def test_class_token_kernel_matches_cpython_and_compiled_runtime(dom_runtime, owner):
    invoke = dom_runtime
    strings = [string(value.encode()) for value in ("div", "class", "  a\u2003b a\0x a ", WHITESPACE, "")]
    name, class_name, initial, whitespace, empty = [pointer(value) for value in strings]
    attribute = invoke("pyjs.native.attribute.new", owner, class_name, initial)
    argument = invoke("pyjs.native.argument.new", owner, int8(1), attribute)
    arguments = argument_list(invoke, owner, [argument])
    element = invoke("pyjs.native.element.new.owned", owner, Pointer(0), name, arguments)
    assert invoke("pyjs.native.class.query", element, Pointer(0), class_name, whitespace) == 4
    tokens = [string(value) for value in (b"a", b"a\0x", b"", b"a b")]
    for expected, token in zip((0, 2, -1, -1), tokens, strict=True):
        assert invoke("pyjs.native.class.query", element, pointer(token), class_name, whitespace) == expected
    values = (ctypes.c_void_p * len(tokens))(*(pointer(token).address for token in tokens))
    assert invoke("pyjs.native.class.mutate", owner, element, pointer(values), len(tokens), False,
                  class_name, whitespace, empty)
    current = invoke("pyjs.native.attribute.get", arguments, class_name)
    assert borrow_bytes(current) == b"a b a\0x a  a b"
    assert invoke("pyjs.native.class.mutate", owner, element, pointer(values), 2, True,
                  class_name, whitespace, empty)
    current = invoke("pyjs.native.attribute.get", arguments, class_name)
    assert borrow_bytes(current) == b"b a a b"


def test_live_form_slot_does_not_change_argument_storage(dom_runtime, owner):
    invoke = dom_runtime
    name, attribute_name, attribute_value, live = [
        string(value) for value in (b"input", b"value", b"attribute", b"live")
    ]
    attribute = invoke("pyjs.native.attribute.new", owner, pointer(attribute_name), pointer(attribute_value))
    argument = invoke("pyjs.native.argument.new", owner, int8(1), attribute)
    arguments = argument_list(invoke, owner, [argument])
    control = invoke("pyjs.native.element.new.owned", owner, Pointer(0), pointer(name), arguments)
    assert invoke("pyjs.native.element.value", control).address == 0
    invoke("pyjs.native.element.value.set", control, pointer(live))
    assert borrow_bytes(invoke("pyjs.native.element.value", control)) == b"live"
    assert dom._Element.from_address(control.address).arguments == arguments.address
    assert borrow_bytes(invoke("pyjs.native.attribute.get", arguments, pointer(attribute_name))) == b"attribute"
    assert dom._Element.from_address(control.address).reference == 0


@pytest.mark.parametrize("identity", [None, b"", "chosen<&ø".encode(), b"x" * 5000])
def test_reference_marker_and_binding_share_one_dom_identity(dom_runtime, owner, identity):
    invoke = dom_runtime
    names = [string(value) for value in (b"div", b"output", b"id", b"data-self-id")]
    name, field, id_name, identity_name = [pointer(value) for value in names]
    parent = invoke("pyjs.native.element.new.owned", owner, Pointer(0), name,
                    argument_list(invoke, owner, []))
    child = invoke("pyjs.native.element.new.owned", owner, Pointer(0), name,
                   argument_list(invoke, owner, []))
    if identity is not None:
        identity_value = string(identity)
        record = invoke("pyjs.native.attribute.new", owner, identity_name, pointer(identity_value))
        assert invoke("pyjs.native.attribute.change", owner, parent, identity_name, record)

    def bind(value):
        return invoke("pyjs.native.element.bind.ref", owner, parent, value, field, id_name, identity_name)

    assert bind(Pointer(0)) == 0
    invoke("pyjs.native.element.ref", Pointer(0))
    assert bind(child) == 0
    assert dom._Element.from_address(child.address).reference == 0
    invoke("pyjs.native.element.ref", child)
    assert dom._Element.from_address(child.address).reference == 1
    state = arena._Arena.from_address(owner.address)
    head = state.chunks
    chunk = arena._Chunk.from_address(head)
    before = chunk.used
    assert bind(child) == 0
    attributes = Pointer(dom._Element.from_address(child.address).arguments)
    text = invoke("pyjs.native.attribute.get", attributes, id_name)
    expected = (b"None" if identity is None else identity) + b"-output"
    assert borrow_bytes(text) == expected
    # Tiny IDs must not retain a rendering output's 4 KiB growable buffer.
    # This fixture stays in one arena chunk; measure payload plus small record
    # overhead rather than noisy whole-process RSS or allocator call counts.
    assert state.chunks == head
    assert chunk.used - before < len(expected) + 256
    assert state.buffers is None
    assert bind(child) == 1
    assert invoke("pyjs.native.attribute.get", attributes, id_name).address == text.address
    assert invoke("pyjs.native.attribute.change", owner, child, id_name, Pointer(0))
    assert bind(child) == 0  # Removing the id does not clear the marker.


def test_render_and_write_preserve_shared_arguments_and_output_lifetimes(dom_runtime, owner):
    invoke = dom_runtime
    document = invoke("pyjs.native.document.new", owner)
    value = '<&>"\' café 😀\x00'
    names = [string(item.encode()) for item in ("div", "x", "xy")]
    values = [string(item.encode()) for item in ("first", "other", value)]
    records = []
    for name, text in zip((names[1], names[2], names[1]), values, strict=True):
        attribute = invoke("pyjs.native.attribute.new", owner, pointer(name), pointer(text))
        records.append(invoke("pyjs.native.argument.new", owner, int8(1), attribute))
    records.insert(1, invoke("pyjs.native.argument.new", owner, int8(3), pointer(values[2])))
    arguments = argument_list(invoke, owner, records)
    before = [ctypes.string_at(record.address, dom.ARGUMENT_SIZE) for record in records]
    root = invoke("pyjs.native.element.new", owner, document, pointer(names[0]), arguments)
    expected = ('<div x="' + html.escape(value, quote=True) + '" xy="other">' +
                html.escape(value, quote=False) + '</div>').encode()
    first = invoke("pyjs.native.document.render", owner, document, root)
    second = invoke("pyjs.native.document.render", owner, document, root)
    assert borrow_bytes(first) == borrow_bytes(second) == expected
    assert [ctypes.string_at(record.address, dom.ARGUMENT_SIZE) for record in records] == before
    with tempfile.TemporaryFile() as destination:
        assert invoke("pyjs.native.document.write", owner, document, root, destination.fileno()) == 0
        # Truncating this descriptor would select the same open file.
        assert invoke("pyjs.native.document.write", owner, document, root,
                      destination.fileno() + 2**32) == 9
        destination.seek(0)
        assert destination.read() == expected
    for invalid in (-1, 2**31, 2**63 - 1):
        assert invoke("pyjs.native.document.write", owner, document, root, invalid) == 9
    assert borrow_bytes(first) == expected


def test_void_tags_and_explicit_empty_children_match_shared_ssr(dom_runtime, owner):
    invoke = dom_runtime
    document = invoke("pyjs.native.document.new", owner)
    empty = string(b"")
    text = invoke("pyjs.native.argument.new", owner, int8(3), pointer(empty))
    for name in sorted(VOID_ELEMENTS | {"", "div", "BR", "brx", "image", "sources", "custom-panel"}):
        tag = string(name.encode())
        for children in ([], [text]):
            arguments = argument_list(invoke, owner, children)
            root = invoke("pyjs.native.element.new", owner, document, pointer(tag), arguments)
            rendered = invoke("pyjs.native.document.render", owner, document, root)
            expected = f"<{name}/>" if name in VOID_ELEMENTS and not children else f"<{name}></{name}>"
            assert borrow_bytes(rendered) == expected.encode()


def test_attribute_changes_do_not_mutate_shared_argument_packs(dom_runtime, owner):
    invoke = dom_runtime
    document = invoke("pyjs.native.document.new", owner)
    name, value, replacement, tag = [string(text) for text in (b"x", b"old", b"new", b"div")]
    old = invoke("pyjs.native.attribute.new", owner, pointer(name), pointer(value))
    record = invoke("pyjs.native.argument.new", owner, int8(1), old)
    arguments = argument_list(invoke, owner, [record, record])
    first, second = [invoke("pyjs.native.element.new", owner, document, pointer(tag), arguments)
                     for _ in range(2)]
    second_pack = dom._Element.from_address(second.address).arguments
    retained = invoke("pyjs.native.attribute.get", arguments, pointer(name))
    new = invoke("pyjs.native.attribute.new", owner, pointer(name), pointer(replacement))
    assert invoke("pyjs.native.attribute.change", owner, first, pointer(name), new)
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, first)) == b'<div x="new"></div>'
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, second)) == b'<div x="old"></div>'
    assert borrow_bytes(retained) == b"old"
    assert invoke("pyjs.native.attribute.change", owner, first, pointer(name), Pointer(0))
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, first)) == b"<div></div>"
    assert dom._Element.from_address(second.address).arguments == second_pack
    addition = invoke("pyjs.native.argument.new", owner, int8(3), pointer(replacement))
    additions = argument_list(invoke, owner, [addition])
    assert invoke("pyjs.native.element.extend", owner, first, additions)
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, first)) == b"<div>new</div>"
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, second)) == b'<div x="old"></div>'


def test_replacing_children_preserves_shared_packs_and_attribute_order(dom_runtime, owner):
    invoke = dom_runtime
    document = invoke("pyjs.native.document.new", owner)
    name, x, xy = [string(text) for text in (b"div", b"x", b"xy")]
    old, other, last, new = [string(text) for text in (b"old", b"other", b"last", b"new<&")]
    records = []
    for key, value in ((x, old), (xy, other), (x, last)):
        attribute = invoke("pyjs.native.attribute.new", owner, pointer(key), pointer(value))
        records.append(invoke("pyjs.native.argument.new", owner, int8(1), attribute))
    records.insert(1, invoke("pyjs.native.argument.new", owner, int8(3), pointer(old)))
    arguments = argument_list(invoke, owner, records)
    first = invoke("pyjs.native.element.new", owner, document, pointer(name), arguments)
    second = invoke("pyjs.native.element.new", owner, document, pointer(name), arguments)
    second_pack = dom._Element.from_address(second.address).arguments
    addition = invoke("pyjs.native.argument.new", owner, int8(3), pointer(new))
    additions = argument_list(invoke, owner, [addition])
    before = invoke("pyjs.native.document.render", owner, document, first)
    assert invoke("pyjs.native.element.replace.children", owner, first, additions)
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, first)) == (
        b'<div x="last" xy="other">new&lt;&amp;</div>')
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, second)) == borrow_bytes(before)
    assert dom._Element.from_address(second.address).arguments == second_pack
    empty = argument_list(invoke, owner, [])
    first_pack = dom._Element.from_address(first.address).arguments
    assert invoke("pyjs.native.element.replace.children", owner, first, empty)
    assert dom._Element.from_address(first.address).arguments == first_pack
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, first)) == (
        b'<div x="last" xy="other"></div>')
    empty_text = string(b"")
    assert invoke("pyjs.native.element.text.set", owner, second, pointer(empty_text))
    assert dom._Element.from_address(second.address).arguments == second_pack
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, document, second)) == (
        b'<div x="last" xy="other"></div>')
    assert sequences._List.from_address(arguments.address).length == len(records)
    assert borrow_bytes(before) == b'<div x="last" xy="other">old</div>'


def test_element_pack_ownership_and_self_extension(dom_runtime, owner):
    invoke = dom_runtime
    name, text = string(b"div"), string(b"x")
    record = invoke("pyjs.native.argument.new", owner, int8(3), pointer(text))
    arguments = argument_list(invoke, owner, [record] * 4)
    first = invoke("pyjs.native.element.new.owned", owner, Pointer(0), pointer(name), arguments)
    assert dom._Element.from_address(first.address).arguments == arguments.address
    # Borrow an already published pack: the new element must not acquire its
    # mutable list. Argument records and child identities are still shared.
    second = invoke("pyjs.native.element.new", owner, Pointer(0), pointer(name), arguments)
    second_pack = dom._Element.from_address(second.address).arguments
    assert second_pack != arguments.address
    assert invoke("pyjs.native.element.extend", owner, first, arguments)
    assert invoke("pyjs.native.element.extend", owner, second, arguments)
    assert sequences._List.from_address(arguments.address).length == 8
    assert sequences._List.from_address(second_pack).length == 12
    for root, expected in ((first, b"<div>xxxxxxxx</div>"), (second, b"<div>xxxxxxxxxxxx</div>")):
        assert borrow_bytes(invoke("pyjs.native.document.render", owner, Pointer(0), root)) == expected


def test_text_content_preserves_attributes_and_prior_output(dom_runtime, owner):
    invoke = dom_runtime
    tag, name, old, new, empty = [string(value) for value in (b"div", b"title", b"old<&", b"new<&", b"")]
    attribute = invoke("pyjs.native.attribute.new", owner, pointer(name), pointer(old))
    records = [invoke("pyjs.native.argument.new", owner, int8(1), attribute),
               invoke("pyjs.native.argument.new", owner, int8(3), pointer(old))]
    arguments = argument_list(invoke, owner, records)
    root = invoke("pyjs.native.element.new", owner, Pointer(0), pointer(tag), arguments)
    retained = invoke("pyjs.native.element.text", owner, root)
    assert borrow_bytes(retained) == b"old<&"
    assert invoke("pyjs.native.element.text.set", owner, root, pointer(new))
    assert borrow_bytes(invoke("pyjs.native.element.text", owner, root)) == b"new<&"
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, Pointer(0), root)) == (
        b'<div title="old&lt;&amp;">new&lt;&amp;</div>')
    assert invoke("pyjs.native.element.text.set", owner, root, pointer(empty))
    assert borrow_bytes(invoke("pyjs.native.element.text", owner, root)) == b""
    assert borrow_bytes(retained) == b"old<&"


@pytest.mark.parametrize("attributes", [False, True], ids=["append", "mixed-attributes"])
def test_incremental_append_retains_linear_arena_capacity(dom_runtime, owner, attributes):
    invoke = dom_runtime
    name, text = string(b"div"), string(b"x")
    record = invoke("pyjs.native.argument.new", owner, int8(3), pointer(text))
    additions = argument_list(invoke, owner, [record])
    arguments = argument_list(invoke, owner, [])
    root = invoke("pyjs.native.element.new.owned", owner, Pointer(0), pointer(name), arguments)
    key = string(b"data-index")
    attribute = invoke("pyjs.native.attribute.new", owner, pointer(key), pointer(text))
    # Attribute lookup/compaction scans the pack; bound CPython's probe work
    # while still crossing the old quadratic allocation limit several times.
    total = 1024 if attributes else 4096
    for count in range(1, total + 1):
        assert invoke("pyjs.native.element.extend", owner, root, additions)
        if attributes:
            assert invoke("pyjs.native.attribute.change", owner, root, pointer(key), attribute)
            if count % 2 == 0:
                assert invoke("pyjs.native.attribute.change", owner, root, pointer(key), Pointer(0))
        if count % 128 == 0:
            capacity = 0
            address = arena._Arena.from_address(owner.address).chunks
            while address:
                chunk = arena._Chunk.from_address(address)
                capacity += chunk.capacity
                address = chunk.next
            # Measure retained allocations, not noisy wall time/RSS. Geometric
            # pointer buffers plus chunk slack fit this generous linear bound.
            # Check throughout so a quadratic regression fails below 1 MiB.
            assert capacity <= 2 * 65536 + count * 64, (count, capacity)
    assert dom._Element.from_address(root.address).arguments == arguments.address
    assert borrow_bytes(invoke("pyjs.native.document.render", owner, Pointer(0), root)) == (
        b"<div>" + b"x" * total + b"</div>")


@pytest.mark.parametrize("optimize", [0, 2])
def test_attribute_allocation_failure_preserves_old_pack_and_can_recover(tmp_path, optimize, owner):
    library = ctypes.CDLL(str(LLVM().compile(
        reject_native_allocations(transpile_llvm(SOURCE)), tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({"pyjs.native.attribute.change": dom.change_attribute}, library)
    name, missing, old, new = [string(text) for text in (b"x", b"absent", b"old", b"new")]
    # The low-level helper borrows records/strings, so stack-built fixtures
    # isolate its allocation failure contract from the public caller's copies.
    attribute = dom._Attribute(pointer(name).address, pointer(old).address)
    argument = dom._Argument(1, pointer(attribute).address)
    python_runtime = runtime_functions({
        "pyjs.list.new.owned": sequences.new_list,
        "pyjs.list.try.append.slot": sequences.append_slot,
    })
    arguments = argument_list(python_runtime, owner, [pointer(argument)])
    element = dom._Element(0, arguments.address)
    replacement = dom._Attribute(pointer(name).address, pointer(new).address)
    addition = dom._Attribute(pointer(missing).address, pointer(new).address)
    header = sequences._List.from_address(arguments.address)
    header.capacity = header.length
    state = arena._Arena.from_address(owner.address)
    chunk = arena._Chunk.from_address(state.chunks)
    before = bytes(header)
    # Fail the replacement record, then a new attribute's capacity growth.
    # Only unpublished scratch allocations occupy this end of the chunk.
    for available, key, value in ((0, name, replacement), (dom.ARGUMENT_SIZE, missing, addition)):
        chunk.used = chunk.capacity - available
        assert not invoke("pyjs.native.attribute.change", owner, pointer(element), pointer(key), pointer(value))
        assert element.arguments == arguments.address
        assert bytes(header) == before
        assert borrow_bytes(dom.attribute_get(arguments, pointer(name))) == b"old"
    chunk.used = chunk.capacity
    # With exclusive list ownership, removal needs no allocation even when the
    # attribute exists. No previously shared immutable record is overwritten.
    assert invoke("pyjs.native.attribute.change", owner, pointer(element), pointer(missing), Pointer(0))
    assert invoke("pyjs.native.attribute.change", owner, pointer(element), pointer(name), Pointer(0))
    assert header.length == 0
    assert attribute.value == pointer(old).address
    assert element.arguments == arguments.address
    ctypes.c_bool.in_dll(library, "test_deny_allocations").value = False
    assert invoke("pyjs.native.attribute.change", owner, pointer(element), pointer(name), pointer(replacement))
    assert borrow_bytes(dom.attribute_get(Pointer(element.arguments), pointer(name))) == b"new"


@pytest.mark.parametrize("optimize", [0, 2])
def test_dom_layout_constants_match_emitter_abi(tmp_path, optimize):
    source = transpile_llvm(SOURCE)
    checks = []
    for name, structure in (
        ("pyjs.native.attribute", dom._Attribute), ("pyjs.native.argument", dom._Argument),
        ("pyjs.native.element", dom._Element), ("pyjs.native.output", buffers._Output),
    ):
        checks.append((name, "i32 1", ctypes.sizeof(structure)))
        for index, (field, _) in enumerate(structure._fields_):
            checks.append((name, f"i32 0, i32 {index}", getattr(structure, field).offset))
    for index, (name, indices, _) in enumerate(checks):
        source += f'''
            define i64 @test.layout.{index}() {{
              %address = getelementptr %{name}, ptr null, {indices}
              %offset = ptrtoint ptr %address to i64
              ret i64 %offset
            }}
        '''
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    for index, (name, indices, expected) in enumerate(checks):
        function = getattr(library, f"test.layout.{index}")
        function.argtypes, function.restype = [], ctypes.c_int64
        assert function() == expected, (name, indices)


@pytest.mark.parametrize("optimize", [0, 2])
def test_public_dom_deep_tree_and_streamed_escaping_match_cpython(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html

        def main() -> str:
            root = div({"title": "café & < > \\" '"}, "😀 & < > \\" '")
            for index in range(20000):
                root = div(root)
            return render_html(root)
    ''', directory=tmp_path, optimize=optimize)
    assert comparison.native.stdout.count("<div") == 20001


@pytest.mark.parametrize("optimize", [0, 2])
def test_output_and_traversal_allocation_failures_are_sticky_and_do_not_corrupt_state(tmp_path, optimize, owner):
    source = reject_native_allocations(transpile_llvm(SOURCE))
    source = source.replace("call ptr @realloc(", "call ptr @test.realloc(")
    source += '''
        define internal ptr @test.realloc(ptr %old, i64 %size) {
            %deny = load i1, ptr @test_deny_allocations
            br i1 %deny, label %failed, label %allocate
        failed:
            ret ptr null
        allocate:
            %value = call ptr @realloc(ptr %old, i64 %size) nobuiltin
            ret ptr %value
        }
    '''
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({
        "pyjs.native.output.try.new": buffers.new_output,
        "pyjs.native.output.append.string": buffers.append_string,
        "pyjs.native.output.try.finish.memory": buffers.finish_memory,
        "pyjs.native.element.write": dom.write_element,
        "pyjs.native.document.write": dom.write_document,
    }, library)
    denied = ctypes.c_bool.in_dll(library, "test_deny_allocations")
    assert invoke("pyjs.native.output.try.new", owner, int32(-1)).address == 0
    assert invoke("pyjs.native.document.write", owner, Pointer(0), Pointer(0), 1) == 12
    state = arena._Arena.from_address(owner.address)
    assert state.chunks is None and state.buffers is None
    denied.value = False
    target = invoke("pyjs.native.output.try.new", owner, int32(-1))
    text = string(b"retained")
    assert invoke("pyjs.native.output.append.string", target, pointer(text)) == 0
    output = buffers._Output.from_address(target.address)
    before = (output.data, output.length, output.capacity, output.owner)
    denied.value = True
    large = string(b"x" * 9000)
    assert invoke("pyjs.native.output.append.string", target, pointer(large)) == 12
    assert (output.data, output.length, output.capacity, output.owner) == before
    assert ctypes.string_at(output.data, output.length) == b"retained"
    assert invoke("pyjs.native.output.try.finish.memory", target).address == 0
    denied.value = False
    # A fresh output is usable; the failed one must retain its first error.
    assert invoke("pyjs.native.output.append.string", target, pointer(text)) == 12
    target = invoke("pyjs.native.output.try.new", owner, int32(-1))
    assert target.address
    chunk = arena._Chunk.from_address(state.chunks)
    chunk.used = chunk.capacity
    denied.value = True
    # Exhaustion before creating the work stack must return without touching
    # the root, not trap or dereference the deliberately null sentinel.
    invoke("pyjs.native.element.write", target, Pointer(0))
    output = buffers._Output.from_address(target.address)
    assert output.error == 12 and output.length == 0
    assert invoke("pyjs.native.output.try.finish.memory", target).address == 0

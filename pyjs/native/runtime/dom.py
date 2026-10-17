"""Link the Python-authored native DOM to the existing emitter ABI."""

from functools import cache


@cache
def compiled_runtime() -> tuple[str, ...]:
    from . import arena, buffers, dom_storage, dom_tokens, objects, sequences
    from .algorithms import bytes_equal
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.native.document.new": dom_storage.new_document,
        "pyjs.native.element.unwrap": objects.reference_value,
        "pyjs.native.element.type": objects.type_of,
        "pyjs.native.element.isinstance": objects.is_instance,
        "pyjs.native.attribute.new": dom_storage.new_attribute,
        "pyjs.native.argument.new": dom_storage.new_argument,
        "pyjs.native.element.new": dom_storage.new_element,
        "pyjs.native.element.new.owned": dom_storage.new_element_owned,
        "pyjs.native.element.ref": dom_storage.mark_reference,
        "pyjs.native.element.bind.ref": dom_storage.bind_reference,
        "pyjs.native.element.assign.ref": dom_storage.assign_reference,
        "pyjs.native.arguments.extend.elements": dom_storage.extend_elements,
        "pyjs.native.attribute.get": dom_storage.attribute_get,
        "pyjs.native.attribute.change": dom_storage.change_attribute,
        "pyjs.native.element.extend": dom_storage.extend_arguments,
        "pyjs.native.element.replace.children": dom_storage.replace_children,
        "pyjs.native.element.text": dom_storage.text_content,
        "pyjs.native.element.text.set": dom_storage.set_text_content,
        "pyjs.native.element.value": dom_storage.form_value,
        "pyjs.native.element.value.set": dom_storage.set_form_value,
        "pyjs.native.class.query": dom_tokens.class_query,
        "pyjs.native.class.mutate": dom_tokens.class_mutate,
        "pyjs.native.element.write": dom_storage.write_element,
        "pyjs.native.document.render": dom_storage.render_document,
        "pyjs.native.document.write": dom_storage.write_document,
    }, dependencies={
        "pyjs.arena.try.alloc": arena.allocate_in_arena,
        "pyjs.list.try.new.owned": sequences.try_new_list,
        "pyjs.list.try.append.slot": sequences.append_slot,
        "pyjs.list.try.reserve": sequences.reserve,
        "pyjs.string.equal": bytes_equal,
        "pyjs.native.output.try.new": buffers.new_output,
        "pyjs.native.output.append.bytes": buffers.append_bytes,
        "pyjs.native.output.append.string": buffers.append_string,
        "pyjs.native.output.try.finish.memory": buffers.finish_memory,
        "pyjs.native.output.flush": buffers.flush,
    })

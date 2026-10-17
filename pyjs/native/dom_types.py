"""Opaque DOM declarations and safe joins of freshly allocated literals."""

import ast

from pyjs.analysis.analyzer import (
    BUILTINS,
    analyzed_value_type,
    contextual_collection_type,
)
from pyjs.analysis.objects import Dict, List, Name, Tuple, UnionType
from pyjs.analysis.representation import tuple_representation
from pyjs.analysis.type_relations import (
    is_subclass,
    merge_conditional_types,
    same_analyzer_type,
)
from pyjs.analysis.value_representation import (
    analyzed_representation,
    compound_representation,
    merged_representation,
    set_analyzed_representation,
)
from pyjs.decorators import is_native_for
from pyjs.python import native as native_builtins
from pyjs.web.domx import tag


def is_opaque_type(semantic):
    return getattr(semantic, "py_obj", None) in {
        native_builtins._WebElement, native_builtins._WebCustomElement, native_builtins._WebFormControl,
    }


def is_browser_declaration(semantic):
    """Foreign browser declarations can name dormant SSR slots, not layouts."""
    value = getattr(semantic, "py_obj", None)
    return (isinstance(value, type) and value.__module__.startswith("pyjs.web.")
            and is_native_for(value, "js"))


def refine_tag_result(value):
    """Keep known form-control results without permitting unchecked DOM casts."""
    target = getattr(getattr(value, "func", None), "obj", None)
    # svg_tag shares the native "tag" operation, not the HTML namespace.
    # Native analysis retains the public Python callable, not its JS client
    # replacement. Identity also survives import aliases without admitting SVG.
    if getattr(target, "py_obj", None) is not tag or not value.args:
        return
    name = value.args[0]
    if (isinstance(name, ast.Constant) and isinstance(name.value, str)
            and name.value in {"input", "textarea", "button", "select"}):
        # tag("select") creates the concrete control in CPython. Preserve that
        # known shape so cast(HTMLSelectElement, tag("select")) is an identity
        # cast; unknown/dynamic tag names still have only the common DOM API.
        value.obj = value.value_obj = BUILTINS.search("WebFormControl")


def common_base(types):
    common = types[0]
    while not all(is_subclass(item, common) for item in types):
        common = common.super
    return common


def contextual_list_type(actual, expected):
    """Choose a fresh list's allocation type, never an existing list's view."""
    actual = contextual_collection_type(actual, "list")
    expected = contextual_collection_type(expected, "list")
    if actual is None or expected is None:
        return None
    source, target = actual.generic_types["V"], expected.generic_types["V"]
    members = source.types if isinstance(source, UnionType) else (source,)
    if (same_analyzer_type(source, target)
            or is_opaque_type(target) and all(is_opaque_type(item) and is_subclass(item, target) for item in members)):
        return expected
    return None


def apply_fresh_type(visitor, value, expected_type):
    """Propagate a late DOM destination through fresh syntax, never aliases."""
    if not contains_opaque(expected_type):
        return None
    if isinstance(value, ast.IfExp):
        for branch in (value.body, value.orelse):
            visitor.apply_literal_type(branch, expected_type)
        return refresh_conditional_type(value)
    expected = contextual_collection_type(expected_type, "list")
    if expected is None:
        return None
    constructor = (isinstance(value, ast.Call)
                   and getattr(getattr(value.func, "obj", None), "py_obj", None) is native_builtins._list)
    actual = analyzed_value_type(value)
    if isinstance(value, ast.ListComp):
        visitor.apply_literal_type(value.elt, expected.generic_types["V"])
        actual = BUILTINS.search("list")(analyzed_value_type(value.elt))
        # Retyping a child can replace a union layout. Rebuild its enclosing
        # representation from that child, not the destination's numeric leaves.
        set_analyzed_representation(value, compound_representation(
            arguments=(analyzed_representation(value.elt),)))
    elif constructor:
        if value.args:
            source = value.args[0]
            apply_iterable_item_type(visitor, source, expected.generic_types["V"])
            protocol = visitor.require_iterable(source, source)
            actual = BUILTINS.search("list")(protocol.item_type)
            set_analyzed_representation(value, compound_representation(
                arguments=(protocol.item_representation,)))
    else:
        return None
    expected = contextual_list_type(actual, expected)
    if expected is not None:
        value.obj = expected
        if constructor:
            value.value_obj = expected
            value.func = ast.copy_location(Name(expected), value.func)
    return expected


def refresh_conditional_type(value):
    branches = value.body, value.orelse
    types = tuple(analyzed_value_type(branch) for branch in branches)
    value.obj = value.value_obj = merge_conditional_types(*types)
    set_analyzed_representation(value, merged_representation(value.obj, tuple(
        (semantic, analyzed_representation(branch))
        for semantic, branch in zip(types, branches, strict=True))))
    return value.obj


def apply_iterable_item_type(visitor, source, item_type):
    """Type fresh source items without imposing the consuming list's shape."""
    if isinstance(source, ast.IfExp):
        # Either branch can construct a different iterable shape. Keep runtime
        # branch selection lazy and derive the join from the actual fresh arms.
        for branch in (source.body, source.orelse):
            apply_iterable_item_type(visitor, branch, item_type)
        refresh_conditional_type(source)
    elif isinstance(source, ast.GeneratorExp):
        visitor.apply_literal_type(source.elt, item_type)
        none = BUILTINS.search("NoneType")
        source.obj = BUILTINS.search("Generator")(analyzed_value_type(source.elt), none, none)
        set_analyzed_representation(source, compound_representation(
            arguments=(analyzed_representation(source.elt), None, None)))
    elif type(source) is Tuple and not any(isinstance(item, ast.Starred) for item in source.elts):
        items = (item_type,) * len(source.elts)
        apply_literal_type(visitor, source, BUILTINS.search("tuple")(*items))
    else:
        # List literals/comprehensions/constructors can allocate fresh storage;
        # names and existing records remain unchanged under literal typing.
        visitor.apply_literal_type(source, BUILTINS.search("list")(item_type))


def contains_opaque(semantic, seen=None):
    # Type aliases may be recursive even when the source literal is finite.
    if seen is None:
        seen = set()
    if id(semantic) in seen:
        return False
    seen.add(id(semantic))
    if isinstance(semantic, UnionType):
        return any(contains_opaque(item, seen) for item in semantic.types)
    return (is_opaque_type(semantic) or
            getattr(semantic, "generic_name", None) in {"list", "dict", "tuple"}
            and semantic.container.scope.is_builtins
            and any(contains_opaque(item, seen) for item in semantic.generic_types.values()))


def literal_groups(value):
    """Only fresh, fixed literal structure can receive a wider item layout."""
    if type(value) is List and not any(isinstance(item, ast.Starred) for item in value.elts):
        return "list", (value.elts,)
    if type(value) is Tuple and not any(isinstance(item, ast.Starred) for item in value.elts):
        return "tuple", tuple([item] for item in value.elts)
    if type(value) is Dict and all(key is not None for key in value.keys):
        return "dict", (value.keys, value.values)
    return None


def common_literal_type(values):
    """Join DOM bases recursively only where a fresh literal can own the layout."""
    if not values:
        return None
    types = [analyzed_value_type(value) for value in values]
    if all(same_analyzer_type(item, types[0]) for item in types):
        return types[0]
    leaves = [member for item in types for member in (item.types if isinstance(item, UnionType) else (item,))]
    if all(is_opaque_type(item) for item in leaves):
        return common_base(leaves)
    shapes = [literal_groups(value) for value in values]
    if any(shape is None or shape[0] != shapes[0][0] or len(shape[1]) != len(shapes[0][1])
           for shape in shapes):
        return None
    arguments = [common_literal_type([item for _, groups in shapes for item in groups[index]])
                 for index in range(len(shapes[0][1]))]
    if any(argument is None for argument in arguments):
        return None
    return BUILTINS.search(shapes[0][0])(*arguments)


def join_values(visitor, values):
    # Never recursively widen a name, call or other alias of a container.
    # Fresh literals can be allocated with the common layout from the outset;
    # existing list[FormControl] values must retain their mutation contract.
    types = [analyzed_value_type(value) for value in values]
    if (not any(contains_opaque(item) for item in types)
            or all(same_analyzer_type(item, types[0]) for item in types)):
        return None
    common = common_literal_type(values)
    if common is not None:
        for value in values:
            apply_literal_type(visitor, value, common)


def apply_literal_type(visitor, value, common):
    visitor.apply_literal_type(value, common)
    refresh_representation(visitor, value)


def refresh_representation(visitor, value):
    # Retyping a nested union to one tuple/list layout must also replace its
    # union-shaped representation metadata. Recompute from the unchanged leaf
    # representations, preserving fixed-width fields and detecting conflicts.
    shape = literal_groups(value)
    if shape is None:
        return
    name, groups = shape
    semantic = analyzed_value_type(value)
    original = analyzed_representation(value)
    if (getattr(semantic, "generic_name", None) != name
            or original is not None and original.array is not None):
        return
    for group in groups:
        for child in group:
            refresh_representation(visitor, child)
    if name == "tuple":
        representation = tuple_representation(tuple(analyzed_representation(item) for item in value.elts))
    else:
        types = tuple(semantic.generic_types.values())
        representation = compound_representation(arguments=tuple(
            visitor.merge_expression_representations(value, item_type, group, "DOM literal items")
            for item_type, group in zip(types, groups, strict=True)))
    set_analyzed_representation(value, representation)


def infer_literal(visitor, value):
    if not contains_opaque(analyzed_value_type(value)):
        return
    shape = literal_groups(value)
    if shape is None:
        return
    name, groups = shape
    arguments = [common_literal_type(group) for group in groups]
    if arguments and all(argument is not None for argument in arguments):
        apply_literal_type(visitor, value, BUILTINS.search(name)(*arguments))

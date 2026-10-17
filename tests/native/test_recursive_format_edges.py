"""Independent formatting consumers and bounded alias-graph specialization."""

import re

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("recursive", [False, True])
@pytest.mark.parametrize("consumer", ["str(value)", "format(value)", 'f"{value}"', "print(value)"])
def test_root_str_and_nested_repr_are_both_reached(tmp_path, optimize, recursive, consumer):
    # Each compilation has only ONE consumer. An unrelated repr(Item()) would
    # retain the missing callback and mask a reachability regression.
    body = 'print(value)\n    return ""' if consumer == "print(value)" else "return " + consumer
    source = f'''
from pyjs.native import gc_collect
class Item:
    def __str__(self) -> str:
        gc_collect()
        return "S"
    def __repr__(self) -> str:
        gc_collect()
        return "R"
type Value = Item | list[{"Value" if recursive else "Item"}]
def render(value: Value) -> str:
    {body}
def main() -> str:
    return render(Item()) + "|" + render({"[[Item()]]" if recursive else "[Item()]"})
'''
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                               sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_single_alias_truthiness_before_and_after_receiver_mutation(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        type Node = list[Node]
        def describe(value: Node) -> str:
            return str((bool(value), not value, 1 if value else 0, len(value)))
        def main() -> str:
            value: Node = []
            result = describe(value)
            value.append([])
            if value:
                result += describe(value)
            while value:
                value.pop()
            return result + describe(value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def aliases(count, optional=False):
    suffix = " | None" if optional else ""
    return "\n".join(f"type A{i} = int | list[A{(i + 1) % count}{suffix}] | dict[str, A{(i + 1) % count}{suffix}]"
                     for i in range(count)) + "\n"


@pytest.mark.parametrize("operation", ["get", "setdefault"])
def test_single_alias_dictionary_lookup_rejects_incompatible_result_storage(operation):
    with pytest.raises(LLVMUnsupported, match="dictionary lookup requires matching tagged result storage.*at line"):
        transpile_llvm(f'''
            type Node = dict[str, Node]
            def main() -> int:
                value: Node = {{}}
                print(value.{operation}("missing", value))
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("shape,value", [
    ("tuple[int, T | None]", "(1, (2, (3, None)))"),
    ("list[T | None]", "[None, [None, []]]"),
    ("int | list[T | None]", "[1, None, [2, None]]"),
    ("dict[str, T | None]", '{"a": None, "b": {"c": None}}'),
])
def test_optional_recursive_edges_outline_expanded_targets(tmp_path, optimize, shape, value):
    comparison = LLVM().assert_matches_python(f'''
        type T = {shape}
        def main() -> str:
            value: T = {value}
            return repr(value) + str(value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["get", "setdefault"])
@pytest.mark.parametrize("consumer", [
    'return str(len(found)) + str(len(missing))',
    'return repr(found) + repr(missing)',
    'found.append([])\n    missing.append([])\n    return repr(values) + repr(fallback)',
])
def test_dictionary_lookup_projects_identical_single_alias_member(tmp_path, optimize, operation, consumer):
    source = f'''
type Node = list[Node]
def main() -> str:
    values: dict[str, Node] = {{"present": [[], []]}}
    fallback: Node = []
    found = values.{operation}("present", fallback)
    missing = values.{operation}("missing", fallback)
    {consumer}
'''
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                               sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optional", [False, True])
def test_recursive_formatter_specialization_is_linear_not_path_expansion(optional):
    sizes = []
    for count in (2, 4):
        for sites in (1, 4):
            source = aliases(count, optional) + "def render(value: A0) -> str:\n    return "
            source += " + ".join(["repr(value)"] * sites)
            source += "\ndef main() -> str:\n    return render(1)\n"
            emitted = transpile_llvm(source)
            # Whole-module IR contains unrelated runtimes. The specialization
            # contract is one helper per union edge, plus one standalone root
            # conversion. Equivalent normalized optionals share their helper
            # rather than each receiving an identity-keyed duplicate. The root
            # returns text; nested edges share its buffer. All sites reuse both.
            helpers = re.findall(r"^define private void @pyjs\.object\.format\.[^\n]+\n.*?^}",
                                 emitted, re.M | re.S)
            roots = re.findall(r"^define private ptr @pyjs\.object\.format\.", emitted, re.M)
            assert len(roots) == 1
            assert len(helpers) == count
            sizes.append(sum(len(helper.splitlines()) for helper in helpers))
    assert sizes[0] == sizes[1]
    assert sizes[2] == sizes[3]
    assert sizes[2] < 2.5 * sizes[0]


@pytest.mark.parametrize("shape", ["list[int] | None", "int | str | float | list[int] | dict[str, list[int]] | None"])
def test_top_level_union_formatters_are_shared_without_inline_buffers(shape):
    sizes = []
    for sites in (1, 4):
        source = f"def render(value: {shape}) -> str:\n    return "
        source += " + ".join(["str(value) + repr(value)"] * sites)
        source += "\ndef main() -> str:\n    return render([1])\n"
        emitted = transpile_llvm(source)
        body = re.search(r"^define ptr @fn\.render\([^\n]+\n(.*?)^}", emitted, re.M | re.S).group(1)
        # Each site calls the same standalone str/repr roots. Buffer lifecycle
        # and member traversal belong to those helpers, never the caller.
        assert len(re.findall(r"call ptr @pyjs\.object\.format\.", body)) == 2 * sites
        assert "@pyjs.text.output.initialize(" not in body
        helpers = re.findall(r"^define private (?:ptr|void) @pyjs\.object\.format\.[^\n]+\n.*?^}",
                             emitted, re.M | re.S)
        sizes.append((len(helpers), sum(len(helper.splitlines()) for helper in helpers)))
    assert sizes[0] == sizes[1]


def narrowed_integer_source(sites, optional):
    expression = " + ".join(["str(value) + repr(value)"] * sites)
    return f'''
def describe(value: int | str{" | None" if optional else ""}) -> str:
    if not isinstance(value, str):
        return {expression}
    return value
def plain(value: int | None) -> str:
    return str(value) + repr(value)
def main() -> str:
    return describe(True) + describe(-7) + describe("s") + describe({"None" if optional else "2"}) + plain(None) + plain(3)
'''


@pytest.mark.parametrize("optional", [False, True])
def test_narrowed_integer_format_helpers_are_shared_across_sites(optional):
    sizes = []
    for sites in (1, 4):
        emitted = transpile_llvm(narrowed_integer_source(sites, optional))
        # Inspect just formatter bodies, not unrelated runtime scaffolding.
        helpers = re.findall(r"^define private (?:ptr|void) @pyjs\.object\.format\.[^\n]+\n.*?^}",
                             emitted, re.M | re.S)
        sizes.append((len(helpers), sum(len(helper.splitlines()) for helper in helpers)))
    assert sizes[0] == sizes[1]


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("optional", [False, True])
def test_shared_narrowed_integer_formatters_preserve_bool_and_optional_storage(tmp_path, optimize, optional):
    comparison = LLVM().assert_matches_python(narrowed_integer_source(4, optional),
        directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("optional", [False, True])
def test_branching_mutual_alias_depth_is_checked_without_stack_overflow(tmp_path, optimize, optional):
    source = aliases(4, optional) + '''
def main() -> int:
    value: A0 = 1
    for step in range(250):
        value = [[[[value]]]]
    if len(repr(value)) != 2001:
        return 1
    value = [[[[value]]]]
    try:
        repr(value)
        return 2
    except RecursionError:
        pass
    return 0 if repr([1, 2]) == "[1, 2]" else 3
'''
    result = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert result.returncode == 0, result.stderr
    assert not result.stderr

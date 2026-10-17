import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("location", ["module", "default"])
def test_cold_persistent_frozensets_prepare_their_own_storage(optimize, location):
    source = ('values: frozenset[str] = frozenset({"cold"})\ndef main() -> int:\n'
              if location == "module" else
              'def count(values: frozenset[str] = frozenset({"cold"})) -> int:\n')
    source += '    return len(values) + int("cold" in values)\n'
    if location == "default":
        source += 'def main() -> int:\n    return count()\n'
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_module_and_default_frozensets_preserve_identity_and_nested_values(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        import tests.native.persistent_values as imported
        from tests.native.persistent_values import FROZEN, FROZEN_ALIAS
        EMPTY: frozenset[str] = frozenset()
        VALUES: frozenset[int] = frozenset([1, 2, 1, -3])
        ALIAS = VALUES
        NESTED: tuple[list[int], frozenset[str]] = ([1], frozenset({"ship", "master"}))
        DEEP: dict[str, frozenset[int]] = {"values": frozenset({7, 8})}
        def defaults(items: frozenset[str] = frozenset({"a", "b"}),
                     *, empty: frozenset[int] = frozenset[int]()) -> frozenset[str]:
            gc_collect()
            return items
        def main() -> str:
            gc_set_threshold(1)
            first = defaults()
            NESTED[0].append(2)
            gc_collect()
            return repr((first is defaults(), sorted(first), ALIAS is VALUES,
                         sorted(VALUES), len(EMPTY), NESTED[0], sorted(NESTED[1]),
                         sorted(DEEP["values"]), FROZEN is imported.FROZEN,
                         FROZEN_ALIAS is FROZEN, sorted(FROZEN)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_defaults_inside_tuples_and_dynamic_calls(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        def values(pair: tuple[list[int], frozenset[str]] = ([1], frozenset(["x", "y"]))) -> str:
            pair[0].append(len(pair[0]))
            gc_collect()
            return repr((pair[0], sorted(pair[1])))
        def main() -> str:
            positional: list[tuple[list[int], frozenset[str]]] = []
            named: dict[str, tuple[list[int], frozenset[str]]] = {}
            return values(*positional, **named) + values()
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("declaration, message", [
    ('values: frozenset[int] = frozenset({len("x")})', "requires a literal initializer"),
    ('from builtins import frozenset as Frozen\nvalues: Frozen[int] = Frozen({1})', "requires a literal initializer"),
    ('from builtins import frozenset as Frozen\ndef frozenset(items: set[int]) -> Frozen[int]:\n    return Frozen({9})\nvalues: Frozen[int] = frozenset({1})', "requires a literal initializer"),
    ('values: frozenset[int] = frozenset({1})\nglobals()["values"] = frozenset({2})', "changed during import"),
    ('values: frozenset[int] = frozenset({1})\nglobals()["values"] = frozenset({True})', "changed during import"),
])
def test_persistent_frozensets_do_not_replay_effects_or_changed_values(declaration, message):
    with pytest.raises(CompilationError, match=message):
        transpile_llvm(declaration + "\ndef main() -> int:\n    return len(values)\n")


@pytest.mark.parametrize("keyword", [False, True])
def test_frozenset_default_replacement_is_not_silently_reconstructed(keyword):
    parameter = "*, " if keyword else ""
    replacement = '__kwdefaults__ = {"items": frozenset({2})}' if keyword else '__defaults__ = (frozenset({2}),)'
    with pytest.raises(LLVMUnsupported, match="literal default changed during import"):
        transpile_llvm(f'''
            def values({parameter}items: frozenset[int] = frozenset({{1}})) -> int:
                return len(items)
            values.{replacement}
            def main() -> int:
                return values()
        ''')


@pytest.mark.parametrize("source", [
    '''
    first: frozenset[int] = frozenset({1})
    second: frozenset[int] = frozenset({1})
    globals()["second"] = first
    def main() -> int:
        return int(first is second)
    ''',
    '''
    def first(items: frozenset[int] = frozenset({1})) -> frozenset[int]:
        return items
    def second(items: frozenset[int] = frozenset({1})) -> frozenset[int]:
        return items
    second.__defaults__ = first.__defaults__
    def main() -> int:
        return int(first() is second())
    ''',
])
def test_import_time_frozenset_aliasing_is_not_replaced_by_equal_copies(source):
    with pytest.raises(LLVMUnsupported, match="during import"):
        transpile_llvm(source)


@pytest.mark.parametrize("declaration, message", [
    ("values: list[frozenset[int] | None] = [frozenset({1})]", "require a concrete frozenset annotation"),
    ("values: frozenset[int8] = frozenset({int8(1)})", "requires a literal initializer"),
])
def test_unmodeled_persistent_frozenset_forms_have_located_diagnostics(declaration, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm("from pyjs import int8\n" + declaration
                       + "\ndef main() -> int:\n    return len(values)\n")
    assert caught.value.lineno is not None


@pytest.mark.parametrize("declaration", [
    "values: frozenset[int] = {1, 2}",
    "values: list[frozenset[int]] = [{1}]",
    "values: tuple[frozenset[int]] = ({1},)",
    'values: dict[str, frozenset[int]] = {"a": {1}}',
])
def test_set_displays_are_not_implicitly_frozen_by_module_annotations(declaration):
    with pytest.raises(CompilationError, match="frozenset literals require the frozenset constructor") as caught:
        transpile_llvm(declaration + "\ndef main() -> int:\n    return len(values)\n")
    assert caught.value.lineno == 1


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("location", ["module", "default"])
@pytest.mark.parametrize("annotation, literal", [
    ("frozenset[tuple[int, int]]", "frozenset({(1, 2)})"),
    ("frozenset[int | str]", 'frozenset({1, "x"})'),
    ("frozenset[frozenset[int]]", "frozenset({frozenset({1, 2})})"),
    ("set[int | str]", '{1, "x"}'),
])
def test_cold_persistent_callback_keys_prepare_hashing(optimize, location, annotation, literal):
    source = (f"values: {annotation} = {literal}\ndef size() -> int:\n"
              if location == "module" else f"def size(values: {annotation} = {literal}) -> int:\n")
    source += "    return len(values)\ndef main() -> int:\n    return size()\n"
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr

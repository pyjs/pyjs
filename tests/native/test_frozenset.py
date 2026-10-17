import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_uses_shared_set_storage_without_mutation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def classify(value: set[int] | frozenset[int]) -> str:
            if isinstance(value, frozenset):
                return "frozen"
            return "mutable"

        def matches(left: frozenset[int], other: frozenset[int] | str) -> bool:
            return left == other

        def main() -> str:
            gc_set_threshold(1)
            left = frozenset([1, 2, 3, 2])
            right = frozenset([3, 4])
            joined = left | right
            intersection = left & right
            difference = left - right
            exclusive = left ^ right
            mutable = {1, 2} | right
            mutable.add(9)
            mutable &= frozenset([2, 3, 9])
            mutable ^= frozenset([2, 8])
            mutable -= frozenset([9])
            gc_collect()
            return str((sorted(left), len(left), bool(left), 3 in left,
                        sorted(joined), sorted(intersection), sorted(difference), sorted(exclusive),
                        left.copy() is left, frozenset(left) is left, left == {1, 2, 3},
                        repr(frozenset[int]()), left.issubset([1, 2, 3, 4]),
                        sorted(mutable), {1, 2} < left, left > {1, 2},
                        sorted(left.union([4], range(5, 7))),
                        sorted(left.intersection([2, 4], (1, 2))),
                        sorted(left.difference([1], (2,))),
                        sorted(left.symmetric_difference([3, 4])),
                        left.isdisjoint([8, 9]), left.issuperset([1, 2]),
                        [1, 2] == (1, 2), left == [1, 2, 3], left == (1, 2, 3),
                        classify(left), classify(mutable),
                        [left] == [frozenset([3, 2, 1])], [left] < [left | {4}],
                        {"key": left} == {"key": frozenset([1, 2, 3])},
                        (left, 1) == ({1, 2, 3}, 1),
                        matches(left, left), matches(left, "different")))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_frozenset_inputs_retain_aliases_and_normalize_members(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def retain(values: frozenset[str], saved: list[frozenset[str]] = []) -> list[frozenset[str]]:
            saved.append(values)
            return saved

        def render(values: frozenset[str], same: frozenset[str], numbers: frozenset[int8]) -> str:
            gc_set_threshold(1)
            saved = retain(values)
            gc_collect()
            return str((values is same, [sorted(item) for item in saved], sorted(numbers)))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        labels = frozenset(["first", "second"])
        assert library.render(labels, labels, frozenset([1, 257, -1])) == "(True, [['first', 'second']], [-1, 1])"
        labels = frozenset(["third"])
        assert library.render(labels, labels, frozenset()) == "(True, [['first', 'second'], ['third']], [])"
        with pytest.raises(TypeError, match="must be str"):
            library.render(frozenset([3]), labels, frozenset())
        assert library.render(labels, labels, frozenset()) == "(True, [['first', 'second'], ['third'], ['third']], [])"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_owns_text_and_survives_tagged_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def display(value: frozenset[str] | str) -> str:
            if isinstance(value, str):
                return value
            return ",".join(sorted(value))

        def main() -> str:
            gc_set_threshold(1)
            parts = ["alpha", "beta"]
            values = frozenset(part + "-item" for part in parts)
            gc_collect()
            copied = values.union(reversed(["gamma-item"]))
            copies: list[frozenset[str] | str] = [values, copied, "done"]
            gc_collect()
            return str(([display(item) for item in copies],
                        "alpha-item" in values, "gamma-item" not in values,
                        repr(frozenset(["single"])), frozenset("aba") == {"a", "b"}))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_augmented_assignment_preserves_immutable_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values = frozenset([int8(1), int8(-1), int8(1)])
            original = values
            values |= {int8(2)}
            values &= frozenset([int8(1), int8(2)])
            values ^= frozenset([int8(1), int8(3)])
            values -= {int8(2)}
            gc_collect()
            optional: frozenset[int8] | None = original
            if optional is None:
                return "missing"
            return str((sorted(original), sorted(values), original is values,
                        sum(optional, int8(0)), bool(frozenset[int]()),
                        sorted(set(original)), sorted(list(original))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_keys_use_order_independent_value_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            first = frozenset([1, 2])
            values = {first: 2, frozenset([3]): 4}
            values[frozenset([2, 1])] = 7
            copied = values.copy()
            gc_collect()
            return str((len(values), copied[frozenset([1, 2])],
                        values.pop(frozenset([3])), list(copied.keys())[0] is first))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("kind", ["set", "frozenset"])
@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
def test_explicit_set_comparison_does_not_replace_notimplemented_with_a_boolean(kind, method):
    with pytest.raises(LLVMUnsupported, match="explicit set comparison.*NotImplemented.*at line"):
        transpile_llvm(f'''
            def compare(left: {kind}[int], other: {kind}[int] | str) -> bool:
                return left.{method}(other)
            def main() -> bool:
                return compare({kind}([1]), "different")
        ''')


@pytest.mark.parametrize("backend", ["llvm", "jvm", "webassembly"])
def test_frozenset_models_reject_mutation_on_every_native_backend(backend):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java import transpile_jvm
    from pyjs.webassembly import transpile_webassembly

    compile = {"llvm": transpile_llvm, "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    with pytest.raises(CompilationError, match="Attribute 'add' is not defined") as caught:
        compile("def main() -> int:\n    values = frozenset([1])\n    values.add(2)\n    return len(values)\n")
    assert caught.value.lineno == 3


@pytest.mark.parametrize("backend", ["jvm", "webassembly"])
def test_frozenset_models_reach_other_backends_explicit_storage_boundaries(backend):
    from pyjs.java import JVMUnsupported, transpile_jvm
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    compile, error = {"jvm": (transpile_jvm, JVMUnsupported),
                      "webassembly": (transpile_webassembly, WebAssemblyUnsupported)}[backend]
    with pytest.raises(error, match="len currently requires.*at line 2"):
        compile("def main() -> int:\n    return len(frozenset([1, 2]))\n")

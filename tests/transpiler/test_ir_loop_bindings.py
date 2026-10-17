import ast

import pytest

from pyjs.analysis.analyzer import analyzed_value_type, literal_iterable_is_nonempty
from pyjs.analysis.ir import IteratorNext, build_program_ir, validate_program_ir
from pyjs.analysis.objects import AnalyzedExpression, UnionType
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.numeric import NumericFormat
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("source, expected", [
    ("[(2, 3)]", True), ("((2, 3),)", True), ("{(2, 3)}", True),
    ("{(2, 3): 1}", True), ("[]", False), ("()", False),
    ("{}", False), ("[*rows]", False), ("{**rows}", False), ("rows", False),
])
def test_analyzed_splice_preserves_literal_nonempty_proof(source, expected):
    original = ast.parse(source, mode="eval").body
    # Typed replacement syntax need not resemble the source. A starred-only
    # source must not acquire a proof from an expanded/analyzed list either.
    replacement = ast.parse("[(9, 9)]", mode="eval").body
    replacement.python_node = original
    assert literal_iterable_is_nonempty(AnalyzedExpression(replacement)) is expected


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
def test_nonempty_fixed_rows_refine_existing_optional_targets(environment):
    with analyze_source('''
        def main() -> int:
            left: int | None = None
            for left, right in [(2, 3)]:
                pass
            return left + right
    ''', wrap=False, environment=environment) as analysis:
        assert analysis.entry_point.scope.lookup("left").cls.name == "int"
        if environment is not None:
            validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
def test_loop_else_keeps_exhaustion_declarations(environment):
    with analyze_source('''
        def main() -> int:
            for item in [7]:
                body_value = 9
            else:
                pass
            return item + body_value
    ''', wrap=False, environment=environment) as analysis:
        for name in ("item", "body_value"):
            assert analysis.entry_point.scope.lookup(name).cls.name == "int"
        if environment is not None:
            validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["native", "java", "webassembly"])
def test_reused_loop_name_keeps_each_targets_own_binding(environment):
    with analyze_source('''
        def main() -> int:
            count = 0
            for values in [["first"]]:
                count += len(values[0])
            for values in [[2]]:
                count += values[0]
            return count
    ''', wrap=False, environment=environment) as analysis:
        targets = [node.target for block in analysis.entry_point.ir.blocks
                   for node in block.body if isinstance(node, IteratorNext)]
        assert [analyzed_value_type(target).name for target in targets] == ["list__str", "list__int"]
        assert targets[0].obj is not targets[1].obj
        validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["native", "java", "webassembly"])
def test_loop_value_binding_retains_annotated_storage_separately(environment):
    with analyze_source('''
        from pyjs import int8

        def main(count: int) -> int:
            values = [int8(127)]
            first: object = None
            first = values
            other: object = values
            for other in [[int8(125)]][:count]:
                pass
            for other in [[int8(126)]][:count]:
                pass
            return 0
    ''', wrap=False, environment=environment) as analysis:
        targets = [node.target for block in analysis.entry_point.ir.blocks
                   for node in block.body if isinstance(node, IteratorNext)]
        first, second = (target.obj for target in targets)
        assert first is not second
        assert first.cls.name == second.cls.name == "list__int"
        storage = first.storage_binding
        assert storage is second.storage_binding
        assert storage.cls.name == "object" and storage.has_declared_type
        assert first.representation == second.representation
        assert first.representation.arguments[0].numeric == NumericFormat("integer", 8, True)
        validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["native", "java", "webassembly"])
def test_optional_loop_exit_does_not_inherit_the_item_proof(environment):
    with analyze_source('''
        def main(count: int) -> int | None:
            found: int | None = None
            for found in [1, 2][:count]:
                if found == 1:
                    break
            return found
    ''', wrap=False, environment=environment) as analysis:
        binding = analysis.entry_point.scope.lookup("found")
        assert isinstance(binding.cls, UnionType)
        assert {member.name for member in binding.cls.types} == {"int", "NoneType"}
        assert binding.storage_declaration.has_declared_type
        assert set(binding.storage_declaration.cls.types) == set(binding.cls.types)
        validate_program_ir(build_program_ir(analysis.entry_point))

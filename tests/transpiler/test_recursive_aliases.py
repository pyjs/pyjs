"""Named recursion stays finite in shared typing; backend support is separate."""

import ast
import gc
import sys
import weakref

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.objects import RecursiveTypeAlias, same_analyzer_type, union_type_key
from pyjs.analysis.representation import annotation_representation, type_alias_value
from pyjs.analysis.source import analyze_source, create_module
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import assert_transpile
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import (
    RECURSIVE_EQUALITY_CONTRACT,
    RECURSIVE_OPTIONAL_CONTRACT,
    RECURSIVE_TREE_CONTRACT,
    RECURSIVE_UNION_CONTRACT,
)
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("operation", ["get", "setdefault"])
def test_recursive_mapping_alias_value_uses_bound_signature(environment, operation):
    with analyze_source(f'''
        type Node = dict[str, Node]
        def main() -> int:
            value: Node = {{}}
            found = value.{operation}('missing', value)
            return 0
    ''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        call = next(node for node in ast.walk(function.node)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute))
        assert call.func.obj.cls.generic_types["V"] is function.scope.names["value"].cls


@pytest.mark.parametrize("operation, expression", [
    ("get", "((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(value,'missing',value)"),
    ("setdefault", "((mapping,key,value)=>{if(!mapping.has(key))mapping.set(key,value);return mapping.get(key);})(value,'missing',value)"),
])
def test_recursive_mapping_alias_value_emits_javascript(operation, expression):
    assert_transpile(f'''
        type Node = dict[str, Node]
        def main() -> int:
            value: Node = {{}}
            found = value.{operation}('missing', value)
            return 0
    ''', f'''
        export function main() {{
            var value = new Map([]);
            var found = {expression};
            return 0;
        }}
    ''')


@pytest.mark.parametrize("contract", [RECURSIVE_TREE_CONTRACT, RECURSIVE_UNION_CONTRACT,
                                     RECURSIVE_OPTIONAL_CONTRACT, RECURSIVE_EQUALITY_CONTRACT])
def test_shared_recursive_tree_contract_matches_javascript(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
def test_recursive_alias_keeps_one_named_backedge(environment):
    with analyze_source('''
        type Tree = int | list[Tree]
        def main(first: Tree, second: Tree) -> int:
            return 1
    ''', wrap=False, environment=environment) as analysis:
        first, second = (parameter.annotation.obj for parameter in analysis.entry_point.params)
        assert isinstance(first, RecursiveTypeAlias)
        assert first is second
        assert first.to_annotation_str() == "Tree"
        integer, sequence = first.types
        assert integer.name == "int"
        assert sequence.generic_name == "list"
        assert list(sequence.generic_types.values()) == [first]
        assert same_analyzer_type(first, second)
        assert union_type_key(first) == union_type_key(second)
        body = "    return 1" if environment is None else "    block entry:\n        return 1"
        assert analysis.types == "def main(first: Tree, second: Tree) -> int:\n" + body
        if environment is not None:
            validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("declarations, message", [
    ("type Bad = Bad", "has no concrete member"),
    ("type Bad = Other\ntype Other = Bad", "has no concrete member"),
    ("type Bad = int | Other\ntype Other = str | Bad", "must pass through a container"),
    ("from pyjs import int8\ntype Bad = int8 | list[Bad]", "numeric or array representations"),
    ("from pyjs import int8\ntype Bad = int8 | list['Bad']", "numeric or array representations"),
    ("type Bad[T] = T | list[Bad[T]]", "Generic type aliases are not supported"),
])
def test_invalid_or_unrepresented_alias_cycles_have_located_diagnostics(declarations, message):
    source = declarations + "\ndef main(value: Bad) -> int:\n    return 1\n"
    with pytest.raises(CompilationError, match=message) as caught:
        analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT)
    assert caught.value.lineno == len(declarations.splitlines()) + 1


def test_mutual_aliases_preserve_the_container_cycle():
    with analyze_source('''
        type Tree = str | list[Branch]
        type Branch = int | dict[str, Tree]
        def main(value: Tree, branch: Branch) -> int:
            return 1
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        tree, branch = (parameter.annotation.obj for parameter in analysis.entry_point.params)
        branch_in_list = next(iter(list(tree.types)[1].generic_types.values()))
        assert same_analyzer_type(branch_in_list, branch)
        mapping = list(branch.types)[1]
        assert mapping.generic_types["V"] is tree
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_recursive_alias_body_narrows_and_iterates():
    with analyze_source('''
        type Tree = int | list[Tree]
        def main(value: Tree) -> int:
            if isinstance(value, int):
                return value
            total = 0
            for item in value:
                total += main(item)
            return total
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.entry_point.return_type.name == "int"
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_imported_namesake_aliases_keep_identity_and_specializations():
    module_names = ("_pyjs_recursive_int_tree", "_pyjs_recursive_str_tree")
    try:
        for name, leaf in zip(module_names, ("int", "str"), strict=True):
            create_module(f"type Tree = {leaf} | list[Tree]\n", f"{name}.py", name)
        with analyze_source('''
            from _pyjs_recursive_int_tree import Tree as IntTree
            from _pyjs_recursive_str_tree import Tree as StrTree
            def main(left: IntTree, right: StrTree) -> int:
                return 1
        ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
            left, right = (parameter.annotation.obj for parameter in analysis.entry_point.params)
            assert left is not right
            assert not same_analyzer_type(left, right)
            assert union_type_key(left) != union_type_key(right)
            left_list, right_list = list(left.types)[1], list(right.types)[1]
            assert left_list is not right_list and left_list.name != right_list.name
            assert list(left_list.generic_types.values()) == [left]
            assert list(right_list.generic_types.values()) == [right]
    finally:
        for name in module_names:
            sys.modules.pop(name, None)


def test_recursive_analysis_is_collectible_after_release():
    def compile_tree():
        with analyze_source('''
            type Tree = int | list[Tree]
            def main(value: Tree) -> int:
                return 1
        ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
            return weakref.ref(analysis.entry_point.params[0].annotation.obj)
    reference = compile_tree()
    gc.collect()
    assert reference() is None


@pytest.mark.parametrize("parameters", ["tree: Tree, maybe: MaybeTree", "maybe: MaybeTree, tree: Tree"])
def test_completed_recursive_alias_expands_in_outer_unions(parameters):
    with analyze_source(f'''
        type Tree = int | list[Tree]
        type MaybeTree = Tree | None
        def main({parameters}) -> int:
            return 1
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        params = {parameter.arg: parameter.annotation.obj for parameter in analysis.entry_point.params}
        tree, maybe = params["tree"], params["maybe"]
        assert list(maybe.types)[:-1] == list(tree.types)
        assert list(maybe.types)[-1].name == "NoneType"
        assert all(not isinstance(member, RecursiveTypeAlias) for member in maybe.types)
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_finite_represented_sibling_of_an_ordinary_cycle_is_preserved():
    with analyze_source('''
        from pyjs import int8
        type Tree = int | list[Tree]
        type Record = tuple[int8, Tree]
        def main(record: Record) -> int:
            return 1
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        representation = analysis.entry_point.params[0].representation
        assert representation.kind == "tuple"
        assert representation.arguments[0].numeric.bits == 8
        assert representation.arguments[1] is None


@pytest.mark.parametrize("parameters", ["a: A, b: B", "b: B, a: A"])
@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT])
def test_mutual_outer_union_flattens_after_binding(parameters, environment):
    with analyze_source(f'''
        type A = int | list[B]
        type B = A | None
        def main({parameters}) -> int:
            if b is None:
                return 0
            if isinstance(b, int):
                return int(b)
            return len(b)
    ''', wrap=False, environment=environment) as analysis:
        params = {parameter.arg: parameter.annotation.obj for parameter in analysis.entry_point.params}
        assert [member.generic_name for member in params["b"].types] == ["int", "list", "NoneType"]
        if environment is not None:
            validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("parameters", ["a: A, b: B", "b: B, a: A"])
@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_mutually_recursive_alias_accepts_explicit_union_member(parameters, environment):
    with analyze_source(f'''
        from pyjs import js
        type A = int | list[B]
        type B = A | None
        @js
        def use(value: B) -> int:
            return 1
        @js
        def main({parameters}) -> int:
            return use(a)
    ''', wrap=False, environment=environment) as analysis:
        if environment is not None:
            validate_program_ir(build_program_ir(analysis.entry_point))


@pytest.mark.parametrize("shadow", ["", "type Tree = str | list[Tree]"])
@pytest.mark.parametrize("reference", ["ImportedTree", "trees.Tree"])
def test_alias_values_resolve_imported_declarations_by_identity(shadow, reference):
    name = "_pyjs_nested_alias_tree"
    try:
        create_module("type Tree = int | list[Tree]\n", f"{name}.py", name)
        with analyze_source(f'''
            from {name} import Tree as ImportedTree
            import {name} as trees
            {shadow}
            type Forest = list[{reference}]
            def main(forest: Forest, tree: ImportedTree) -> int:
                return 1
        ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
            forest, tree = (parameter.annotation.obj for parameter in analysis.entry_point.params)
            assert next(iter(forest.generic_types.values())) is tree
            assert tree.alias.container.name == name
            assert list(tree.types)[0].generic_name == "int"
    finally:
        sys.modules.pop(name, None)


def test_represented_recursive_field_has_a_located_diagnostic():
    source = "from pyjs import int8\nfrom dataclasses import dataclass\ntype Bad = int8 | list[Bad]\n@dataclass\nclass Node:\n    value: Bad\ndef main(node: Node) -> int:\n    return 1\n"
    with pytest.raises(CompilationError, match="numeric or array representations") as caught:
        analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT)
    assert caught.value.lineno == 6


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_distinct_recursive_declarations_reject_without_structural_recursion(environment):
    with pytest.raises(CompilationError, match="expects A, got B") as caught:
        analyze_source('''
            from pyjs import js
            type A = int | list[A]
            type B = int | list[B]
            @js
            def use(value: A) -> int:
                return 1
            @js
            def main(value: B) -> int:
                return use(value)
        ''', wrap=False, environment=environment)
    assert caught.value.lineno == 10


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT])
@pytest.mark.parametrize("declaration", ["Value = make_alias('Value', int | None)", "Value = Holder.Inner"])
def test_imported_alias_not_bound_in_its_declaring_module(environment, declaration):
    name = "_pyjs_alias_factory"
    try:
        create_module('''from typing import TypeAliasType
def make_alias(name, value):
    return TypeAliasType(name, value)
class Holder:
    type Inner = int | None
''', f"{name}.py", name)
        with analyze_source(f'''
            from {name} import make_alias, Holder
            {declaration}
            def main(value: Value) -> int:
                if value is None:
                    return 0
                return int(value)
        ''', wrap=False, environment=environment) as analysis:
            members = analysis.entry_point.params[0].annotation.obj.types
            assert [member.generic_name for member in members] == ["int", "NoneType"]
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("represented", [False, True])
@pytest.mark.parametrize("shadow", ["", "type Tree = str"])
@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_wrapped_recursive_import_keeps_its_annotation_owner(represented, shadow, environment):
    name = "_pyjs_wrapped_recursive_alias"
    try:
        leaf = "int8" if represented else "int"
        create_module(f"from pyjs import int8\ntype Tree = {leaf} | list['Tree']\n", f"{name}.py", name)
        source = f'''
            from typing import Annotated
            from {name} import Tree as Imported
            {shadow}
            type Outer = Annotated[Imported, 'marker']
            def main(value: Outer) -> int:
                return 1
        '''
        if represented:
            with pytest.raises(CompilationError, match="numeric or array representations"):
                analyze_source(source, wrap=False, environment=environment)
        else:
            with analyze_source(source, wrap=False, environment=environment) as analysis:
                parameter = analysis.entry_point.params[0]
                assert parameter.annotation.obj.alias.container.name == name
                assert parameter.representation is None
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("represented", [False, True])
def test_field_wrapper_metadata_keeps_imported_alias_owner(represented):
    modules = ("_pyjs_field_alias_owner", "_pyjs_field_alias_consumer")
    try:
        leaf = "int8" if represented else "int"
        create_module(f"from pyjs import int8\ntype Tree = {leaf} | list['Tree']\n",
                      f"{modules[0]}.py", modules[0])
        consumer = create_module(f'''from typing import Annotated, Final
from {modules[0]} import Tree as Imported
type Tree = str
type Outer = Final[Annotated[Imported, 'marker']]
''', f"{modules[1]}.py", modules[1])
        # Final is field metadata, not a supported function-parameter annotation.
        if represented:
            with pytest.raises(TypeError, match="numeric or array representations"):
                annotation_representation(consumer.Outer)
        else:
            assert annotation_representation(consumer.Outer) is None
    finally:
        for name in modules:
            sys.modules.pop(name, None)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("shadow", ["", "from pyjs import int8\nT = int8"])
@pytest.mark.parametrize("build_class", [False, True])
def test_quoted_class_alias_cannot_use_module_namesake(environment, shadow, build_class):
    name = "_pyjs_quoted_class_alias"
    try:
        create_module(f"from pyjs import js\n@js\nclass Holder:\n    type T = int | list['T']\n{shadow}\n",
                      f"{name}.py", name)
        parameters = "holder: Holder, value: Alias" if build_class else "value: Alias"
        with pytest.raises(CompilationError, match="Quoted references require a type statement"):
            analyze_source(f'''
                from {name} import Holder
                Alias = Holder.T
                def main({parameters}) -> int:
                    return 1
            ''', wrap=False, environment=environment)
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("reverse", [False, True])
def test_recursive_inclusion_through_finite_intermediate_alias(environment, reverse):
    declarations = ["type A = int | list[A]", "type B = A | None", "type C = B | list[C]"]
    if reverse:
        declarations.reverse()
    source = "from pyjs import js\n" + "\n".join(declarations) + '''
@js
def use(value: C) -> int:
    return 1
@js
def main(value: A) -> int:
    return use(value)
'''
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        if environment is not None:
            validate_program_ir(build_program_ir(analysis.entry_point))


def test_nonmodule_alias_literal_strings_are_not_quoted_type_references():
    name = "_pyjs_alias_string_values"
    try:
        module = create_module('''from typing import Annotated, Callable, Literal
class Holder:
    type Label = Literal['T']
    type Metadata = Annotated[int, 'T']
    type Callback = Callable[['T'], int]
''', f"{name}.py", name)
        assert annotation_representation(module.Holder.Label) is None
        assert annotation_representation(module.Holder.Metadata) is None
        with pytest.raises(TypeError, match="Quoted references require a type statement"):
            type_alias_value(module.Holder.Callback)
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("creation", ["constructor", "exec-namesake", "exec-no-module"])
def test_dynamic_quoted_alias_cannot_guess_its_defining_namespace(environment, creation):
    name = "_pyjs_dynamic_quoted_alias"
    declaration = {
        "constructor": "from typing import TypeAliasType\nAlias = TypeAliasType('T', int | list['T'])",
        "exec-namesake": "ns = {'__name__': __name__}\nexec(\"type T = int | list['T']\", ns)\nAlias = ns['T']",
        "exec-no-module": "ns = {}\nexec(\"type T = int | list['T']\", ns)\nAlias = ns['T']",
    }[creation]
    try:
        module = create_module("from pyjs import int8\nT = int8\n" + declaration,
                               f"{name}.py", name)
        with pytest.raises(TypeError, match="Quoted references require a type statement"):
            type_alias_value(module.Alias)
        message = ("importable defining module" if creation == "exec-no-module"
                   else "Quoted references require a type statement")
        with pytest.raises(CompilationError, match=message):
            analyze_source(f'''
                from {name} import Alias
                def main(value: Alias) -> int:
                    return 1
            ''', wrap=False, environment=environment)
    finally:
        sys.modules.pop(name, None)

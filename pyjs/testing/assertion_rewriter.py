import ast
from collections.abc import Iterable

from pyjs.testing.client.assertions import assert_compare, assert_condition
from pyjs.transpiler import CompilationExtension

ASSERT_ALIAS = "__pyjs_test_assert__"
COMPARE_ALIAS = "__pyjs_test_assert_compare__"
OPERATORS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}


def empty_arguments() -> ast.arguments:
    return ast.arguments(
        posonlyargs=[],
        args=[],
        kwonlyargs=[],
        kw_defaults=[],
        defaults=[],
    )


def deferred(value: ast.expr) -> ast.Lambda:
    return ast.Lambda(args=empty_arguments(), body=value)


class AssertionRewriter(ast.NodeTransformer):
    def __init__(self, source: str):
        self.source = source

    def expression_text(self, node: ast.AST) -> str:
        return ast.get_source_segment(self.source, node) or ast.unparse(node)

    def message(self, node: ast.Assert) -> ast.expr:
        if node.msg is None:
            return ast.Constant(value=None)
        return deferred(node.msg)

    def visit_Assert(self, node: ast.Assert):
        if (
            isinstance(node.test, ast.Call)
            and isinstance(node.test.func, ast.Name)
            and node.test.func.id == "isinstance"
        ):
            return [node, self.rewrite_condition(node)]

        if isinstance(node.test, ast.Compare) and len(node.test.ops) == 1:
            return self.rewrite_comparison(node)

        return self.rewrite_condition(node)

    def rewrite_condition(self, node: ast.Assert) -> ast.Expr:
        replacement = ast.Expr(
            value=ast.Call(
                func=ast.Name(id=ASSERT_ALIAS, ctx=ast.Load()),
                args=[
                    node.test,
                    ast.Constant(value=self.expression_text(node.test)),
                    self.message(node),
                ],
                keywords=[],
            )
        )
        return ast.copy_location(replacement, node)

    def rewrite_comparison(self, node: ast.Assert) -> list[ast.stmt]:
        comparison = node.test
        left_name = f"__pyjs_assert_left_{node.lineno}_{node.col_offset}"
        right_name = f"__pyjs_assert_right_{node.lineno}_{node.col_offset}"
        left = ast.Assign(
            targets=[ast.Name(id=left_name, ctx=ast.Store())],
            value=comparison.left,
        )
        right = ast.Assign(
            targets=[ast.Name(id=right_name, ctx=ast.Store())],
            value=comparison.comparators[0],
        )
        condition = ast.Compare(
            left=ast.Name(id=left_name, ctx=ast.Load()),
            ops=comparison.ops,
            comparators=[ast.Name(id=right_name, ctx=ast.Load())],
        )
        call = ast.Expr(
            value=ast.Call(
                func=ast.Name(id=COMPARE_ALIAS, ctx=ast.Load()),
                args=[
                    condition,
                    ast.Name(id=left_name, ctx=ast.Load()),
                    ast.Constant(value=self.expression_text(comparison.left)),
                    ast.Constant(value=OPERATORS[type(comparison.ops[0])]),
                    ast.Name(id=right_name, ctx=ast.Load()),
                    ast.Constant(value=self.expression_text(comparison.comparators[0])),
                    self.message(node),
                ],
                keywords=[],
            )
        )
        return [ast.copy_location(statement, node) for statement in (left, right, call)]


class TestingAssertions(CompilationExtension):
    def __init__(self, selected_tests: Iterable[object]):
        self.selected_functions = {
            (selected.module_name, selected.function_name) for selected in selected_tests
        }

    def transform_function(self, function, node, source):
        if (function.__module__, function.__name__) not in self.selected_functions:
            return node, {}
        rewritten = AssertionRewriter(source).visit(node)
        assert isinstance(rewritten, (ast.FunctionDef, ast.AsyncFunctionDef))
        return rewritten, {
            ASSERT_ALIAS: assert_condition,
            COMPARE_ALIAS: assert_compare,
        }

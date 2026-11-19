import ast

import pytest

from pyjs.analysis.ir import Block, Branch, ExceptionCatch, IteratorNext, Jump, Return
from pyjs.java import transpile_jvm
from pyjs.java.local_state import checked_locals
from tests.java.test_context_managers import MANAGER
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize(("kind", "value"), [
    ("str", '"copy"'), ("int", "42"), ("float", "1.25"),
    ("bool", "True"), ("list[int]", "[42]"), ("None", "None"),
    ("int8", "int8(42)"), ("int64", "int64(42)"),
    ("float32", "float32(1.25)"), ("float64", "float64(1.25)"),
])
def test_suppressed_assignment_does_not_return_a_default(tmp_path, kind, value):
    assert_matches_python('from pyjs import int8, int64, float32, float64\n' + MANAGER + f'''
def produce(fail: bool) -> {kind}:
    if fail:
        raise ValueError("before assignment")
    return {value}

def read(fail: bool) -> {kind}:
    events: list[str] = []
    with Scope(events, "copy", True):
        copied = produce(fail)
    return copied

def main() -> int:
    assert read(False) == {value}
    try:
        read(True)
    except UnboundLocalError as error:
        assert str(error) == "cannot access local variable 'copied' where it is not associated with a value"
        return 42
    return 1
''', tmp_path)


def test_conditionally_assigned_literal_is_not_folded_past_its_check(tmp_path):
    assert_matches_python('''
        def read(flag: bool) -> int:
            if flag:
                copied = 42
            return copied

        def main() -> int:
            assert read(True) == 42
            try:
                read(False)
            except UnboundLocalError:
                return 42
            return 1
    ''', tmp_path)


def test_empty_loop_target_is_unbound(tmp_path):
    assert_matches_python('''
        def last(values: list[str]) -> str:
            for value in values:
                pass
            return value

        def main() -> int:
            assert last(["first", "last"]) == "last"
            try:
                last([])
            except UnboundLocalError:
                return 42
            return 1
    ''', tmp_path)


def test_loop_assignment_survives_continue_and_empty_iteration(tmp_path):
    assert_matches_python('''
        def last(values: list[int]) -> int:
            for value in values:
                if value < 0:
                    continue
                copied = value + 1
            return copied

        def main() -> int:
            assert last([4]) == 5
            assert last([4, -1]) == 5
            assert last([-1, 4, 7]) == 8
            caught = 0
            for values in [[], [-1]]:
                try:
                    last(values)
                except NameError:
                    caught += 1
            return 42 if caught == 2 else 1
    ''', tmp_path)


def test_failed_reassignment_keeps_the_previous_value(tmp_path):
    assert_matches_python(MANAGER + '''
def produce(fail: bool) -> str:
    if fail:
        raise ValueError("failed")
    return "saved"

def main() -> int:
    events: list[str] = []
    for fail in [False, True]:
        with Scope(events, "copy", True):
            copied = produce(fail)
    return 42 if copied == "saved" else 1
''', tmp_path)


def test_definitely_assigned_locals_do_not_emit_unbound_runtime():
    compilation = transpile_jvm('''
        def choose(flag: bool) -> int:
            if flag:
                result = 41
            else:
                result = 42
            return result

        def main() -> int:
            return choose(False)
    ''')
    assert not any("UnboundLocalError" in name for name in compilation.classes)


def test_handler_reads_preserve_successful_stores_and_exception_context(tmp_path):
    assert_matches_python('''
        def read(fail: bool) -> str:
            copied: str
            try:
                if fail:
                    raise ValueError("before")
                copied = "kept"
                raise ValueError("after")
            except ValueError:
                return copied

        def main() -> int:
            assert read(False) == "kept"
            try:
                read(True)
            except UnboundLocalError as error:
                assert isinstance(error.__context__, ValueError)
                assert str(error.__context__) == "before"
                return 42
            return 1
    ''', tmp_path)


def block(name, *statements, handler=None):
    result = Block(name, exception_target=handler)
    result.body = list(statements)
    return result


def assign(name):
    return ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=ast.Constant(42))


def read(name):
    return Return(ast.Name(id=name, ctx=ast.Load()))


def test_checks_only_reads_not_assigned_on_every_incoming_path():
    blocks = [
        block("entry", Branch(ast.Constant(True), "left", "right")),
        block("left", assign("both"), assign("left_only"), Jump("join")),
        block("right", assign("both"), Jump("join")),
        block("join", ast.Expr(ast.Name(id="both", ctx=ast.Load())), read("left_only")),
    ]
    assert checked_locals(blocks, (), {"both", "left_only"}) == {"left_only"}


def test_exception_edge_does_not_assume_a_store_completed():
    blocks = [
        block("entry", assign("prior"), Jump("body")),
        block("body", assign("copied"), Jump("join"), handler="handler"),
        block("handler", ExceptionCatch(ast.Name(id="error", ctx=ast.Store())),
              ast.Expr(ast.Name(id="error", ctx=ast.Load())), Jump("join")),
        block("join", ast.Expr(ast.Name(id="prior", ctx=ast.Load())), read("copied")),
    ]
    assert checked_locals(blocks, (), {"prior", "copied", "error"}) == {"copied"}


def test_iterator_target_is_bound_only_on_the_body_edge():
    blocks = [
        block("entry", Jump("next")),
        block("next", IteratorNext("items", ast.Name(id="item", ctx=ast.Store()),
                                   "body", "done")),
        block("body", ast.Expr(ast.Name(id="item", ctx=ast.Load())), Jump("next")),
        block("done", read("item")),
    ]
    assert checked_locals(blocks, (), {"item"}) == {"item"}
    assert checked_locals(blocks, {"item"}, {"item"}) == set()

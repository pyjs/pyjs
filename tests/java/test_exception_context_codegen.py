import ast
from collections import Counter
from textwrap import indent

import pytest

from pyjs.analysis.ir import (
    Block,
    Branch,
    ExceptionDispatch,
    IteratorNext,
    Jump,
    Return,
)
from pyjs.java import transpile_jvm
from pyjs.java.exceptions import UNKNOWN_CONTEXT, exception_entry_contexts
from pyjs.java.transpiler import JVMEmitter


@pytest.mark.parametrize("terminator", [
    Jump("join"),
    Branch(ast.Constant(True), "join", "join"),
    IteratorNext("values", ast.Name("item"), "join", "join"),
    ExceptionDispatch((((), "join"),), "join"),
])
def test_normal_edges_preserve_known_context_but_exception_edges_do_not(terminator):
    handled = ast.Name("saved")
    terminator.handled_exception = handled
    entry = Block("entry", exception_target="dispatch")
    entry.body = [terminator]
    join = Block("join")
    join.body = [Return(ast.Constant(42))]
    dispatch = Block("dispatch")
    dispatch.body = [Jump("join")]
    dispatch.body[0].handled_exception = handled
    assert exception_entry_contexts([entry, join, dispatch]) == {
        "entry": None, "join": handled, "dispatch": UNKNOWN_CONTEXT,
    }
    dispatch.body[0].handled_exception = None
    assert exception_entry_contexts([entry, join, dispatch])["join"] is UNKNOWN_CONTEXT


def test_loop_backedge_preserves_handler_state_without_confusing_entry():
    handled = ast.Name("saved")
    entry = Block("entry")
    entry.body = [Jump("loop")]
    entry.body[0].handled_exception = handled
    loop = Block("loop")
    loop.body = [Branch(ast.Constant(True), "loop", "exit")]
    loop.body[0].handled_exception = handled
    exit_ = Block("exit")
    exit_.body = [Return(ast.Constant(0))]
    assert exception_entry_contexts([entry, loop, exit_]) == {
        "entry": None, "loop": handled, "exit": handled,
    }
    loop.body[0].false = "entry"
    assert exception_entry_contexts([entry, loop, exit_])["entry"] is UNKNOWN_CONTEXT


@pytest.mark.parametrize("placement", ["before-handler", "in-handler"])
def test_branching_loops_add_no_thread_local_updates(monkeypatch, placement):
    calls = Counter()
    original = JVMEmitter.context_call

    def record(self, name, *args, **kwargs):
        if self.current_function.name == "work":
            calls[name] += 1
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(JVMEmitter, "context_call", record)
    bodies = ["total += count", '''
for index in range(count):
    if index % 2 == 0:
        total += index
    else:
        total -= 1
'''.strip()]
    observed = []
    for body in bodies:
        body = indent(body, "    " if placement == "before-handler" else "        ")
        before = body if placement == "before-handler" else ""
        inside = body if placement == "in-handler" else "        total = 0"
        calls.clear()
        transpile_jvm(f'''
def work(count: int) -> int:
    total = 0
{before}
    try:
        if count < 0:
            raise ValueError("negative")
    except ValueError:
{inside}
    return total

def main() -> int:
    return work(5)
''')
        observed.append(dict(calls))
    assert observed[0]["activate"] > 0
    assert observed[0] == observed[1]

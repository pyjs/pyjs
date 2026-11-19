"""Find local reads that need Python's unbound-variable check on the JVM."""

import ast
from collections import deque

from pyjs.analysis.ir import (
    BlockArgument,
    Branch,
    ExceptionCatch,
    ExceptionDispatch,
    IteratorNext,
    Jump,
)


def bound_names(target):
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.arg):
        return {target.arg}
    if isinstance(target, BlockArgument):
        return {target.name}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(bound_names(item) for item in target.elts))
    return set()


def local_accesses(statement):
    writes = set()
    expressions = [statement]
    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        expressions = [statement.value] if statement.value is not None else []
        for target in targets:
            if statement.value is not None:
                writes.update(bound_names(target))
            if isinstance(target, (ast.Attribute, ast.Subscript)):
                expressions.append(target)
    elif isinstance(statement, ExceptionCatch):
        writes = bound_names(statement.target)
        expressions = []
    elif isinstance(statement, IteratorNext):
        # The target becomes bound only on the successful iteration edge.
        expressions = []
    reads = set()
    for expression in expressions:
        for node in ast.walk(expression):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                reads.add(node.id)
            elif isinstance(node, BlockArgument):
                reads.add(node.name)
    return reads, writes


def checked_locals(blocks, parameters, locals_):
    blocks = {block.name: block for block in blocks}
    accesses = {name: [local_accesses(node) for node in block.body]
                for name, block in blocks.items()}
    entry = next(iter(blocks))
    incoming = {entry: set(parameters)}
    pending = deque([entry])

    def propagate(target, assigned):
        previous = incoming.get(target)
        merged = assigned if previous is None else previous & assigned
        if previous != merged:
            incoming[target] = merged.copy()
            pending.append(target)

    while pending:
        name = pending.popleft()
        block = blocks[name]
        assigned = incoming[name].copy()
        if block.exception_target is not None:
            # JVM handlers cover the whole block, including before its first
            # store. Do not assume an assignment completed before a throw.
            propagate(block.exception_target, assigned)
        for _reads, writes in accesses[name]:
            assigned.update(writes)
        terminal = block.body[-1]
        if isinstance(terminal, Jump):
            assigned.update(argument.name for argument in blocks[terminal.target].arguments)
            propagate(terminal.target, assigned)
        elif isinstance(terminal, Branch):
            propagate(terminal.true, assigned)
            propagate(terminal.false, assigned)
        elif isinstance(terminal, IteratorNext):
            propagate(terminal.body, assigned | bound_names(terminal.target))
            propagate(terminal.exhausted, assigned)
        elif isinstance(terminal, ExceptionDispatch):
            for _types, target in terminal.handlers:
                propagate(target, assigned)
            if terminal.unmatched is not None:
                propagate(terminal.unmatched, assigned)

    checked = set()
    for name, assigned in incoming.items():
        assigned = assigned.copy()
        for reads, writes in accesses[name]:
            checked.update(reads - assigned)
            assigned.update(writes)
    return checked & set(locals_)

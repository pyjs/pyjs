"""Keep lexical super lookup when its raw receiver is held in a local alias."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.ir import Block, BlockArgument, Jump
from pyjs.analysis.lifetime import lambda_captures
from pyjs.analysis.type_relations import is_builtin_class, same_analyzer_type

from .errors import LLVMUnsupported


def is_receiver(node):
    return (getattr(node, "native_super_receiver", False)
            or isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "super")


def prepare(function):
    # Native super() currently carries self, not an allocated Python proxy.
    # Preserve lexical lookup for monomorphic local aliases; a mixed/escaping
    # proxy would need a distinct runtime representation, not a vtable guess.
    if function.cls is None:
        return  # Zero-argument super() is scoped to a method.
    blocks = {block.name: block for block in function.ir.blocks if isinstance(block, Block)}
    nodes = []
    pending = [statement for block in blocks.values() for statement in block.body]
    while pending:
        node = pending.pop()
        nodes.append(node)
        if not isinstance(node, ast.Lambda):
            pending.extend(ast.iter_child_nodes(node))
    if not any(is_receiver(node) for node in nodes):
        return
    writes = []
    tracked_stores = set()
    for block in blocks.values():
        for statement in block.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                tracked_stores.add(id(statement.target))
                if statement.value is not None:
                    writes.append((statement.target.id, statement.value))
            elif isinstance(statement, ast.Assign):
                tracked_stores.update(id(target) for target in statement.targets if isinstance(target, ast.Name))
                writes.extend((target.id, statement.value) for target in statement.targets
                              if isinstance(target, ast.Name))
            elif isinstance(statement, Jump):
                writes.extend((argument.name, value) for argument, value in zip(
                    blocks[statement.target].arguments, statement.arguments, strict=True))
    names = set()

    def proxy(value, *, every_arm=False):
        if isinstance(value, ast.IfExp):
            combine = all if every_arm else any
            return combine(proxy(arm, every_arm=every_arm) for arm in (value.body, value.orelse))
        return (is_receiver(value) or isinstance(value, ast.Name) and value.id in names
                or isinstance(value, BlockArgument) and value.name in names)

    # Each alias enters once. This handles forward copies/backedges without
    # pretending that all writes to a mixed slot have the same lookup policy.
    changed = True
    while changed:
        changed = False
        for name, value in writes:
            if name not in names and proxy(value):
                names.add(name)
                changed = True
    # Lowered loop targets are ast.arg (including unpacked leaves), not Store
    # Names. Catch targets and other stores also bind locals without an Assign.
    # Only the explicitly tracked copies/jumps can establish proxy provenance.
    for node in nodes:
        binding = (node.arg if isinstance(node, ast.arg) else
                   node.id if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) else None)
        if binding in names and id(node) not in tracked_stores:
            raise LLVMUnsupported("LLVM cannot mix super() proxies and other local bindings", node)
    for name, value in writes:
        if name in names and not proxy(value, every_arm=True):
            raise LLVMUnsupported("LLVM cannot mix super() proxies and ordinary values in one local", value)
    parameters = {parameter.arg for parameter in (*function.params, *function.kwonlyargs)}
    if not function.is_static:
        parameters.add("self")
    for name, value in writes:
        if name in names & parameters:
            raise LLVMUnsupported("LLVM cannot replace a parameter with a super() proxy", value)
    allowed = set()

    def allow(value):
        if not proxy(value, every_arm=True):
            raise LLVMUnsupported("LLVM cannot mix super() proxies and ordinary values in one expression", value)
        # A wider annotation changes the analyzer's attribute lookup. The raw
        # self pointer has no proxy class to restore that lexical information.
        if not same_analyzer_type(analyzed_value_type(value), function.cls.super):
            raise LLVMUnsupported("LLVM super() aliases must retain their lexical parent type", value)
        allowed.add(id(value))
        if isinstance(value, ast.IfExp):
            # The condition is an ordinary expression; only its result arms
            # carry lexical lookup. Do not mark/reinterpret condition reads.
            allow(value.body)
            allow(value.orelse)

    for name, value in writes:
        if name in names:
            allow(value)
    for node in nodes:
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and proxy(node.func.value) and node.func.attr == "__str__"
                and is_builtin_class(getattr(node.func.obj, "cls", None), "object")):
            # object.__str__ bypasses the subclass's str override but still
            # invokes its repr. An ordered str/repr fallback stops too soon.
            node.runtime_protocols = (*node.runtime_protocols, (function.cls, ("__repr__",)))
        if isinstance(node, ast.Lambda) and names.intersection(lambda_captures(node)):
            raise LLVMUnsupported("LLVM super() proxies cannot escape into closures", node)
        if isinstance(node, ast.Attribute) and proxy(node.value):
            allow(node.value)
            node.value.native_super_receiver = True
        elif isinstance(node, ast.Expr) and proxy(node.value):
            allow(node.value)  # Evaluated and discarded.
    for node in nodes:
        if (proxy(node) and not isinstance(getattr(node, "ctx", None), ast.Store)
                and id(node) not in allowed):
            raise LLVMUnsupported("LLVM super() proxies support local aliases and attribute lookup, not escape", node)

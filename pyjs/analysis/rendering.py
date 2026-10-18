"""Readable Python-shaped output for the analyzed object graph."""

import ast
from _ast_unparse import Unparser as _Unparser
from _ast_unparse import _Precedence

from .ir import (
    Block,
    BlockArgument,
    Branch,
    CollectionNew,
    ExceptionCatch,
    ExceptionDispatch,
    ExceptionRaise,
    External,
    FieldLoad,
    FieldStore,
    IteratorCreate,
    IteratorNext,
    Jump,
    ListAppend,
    ObjectNew,
    Return,
)
from .objects import Function, RuntimeFunctionReference


class TypeWriter(_Unparser):
    def visit_ModuleDef(self, node):
        self.visit_Module(node)

    def visit_Name(self, node):
        if node.id == "NoneType":
            self.write("None")
            return
        super().visit_Name(node)

    def visit_Attribute(self, node):
        self.set_precedence(_Precedence.ATOM, node.value)
        self.traverse(node.value)
        self.write(".")
        obj = getattr(node, "obj", None)
        if isinstance(obj, Function) and obj.cls is not None:
            self.write(f"[{obj.cls.name}]")
        self.write(node.attr)
        if isinstance(obj, Function) and obj.inline_decorator:
            self.write("!")

    def visit_RuntimeFunctionReference(self, node: RuntimeFunctionReference):
        self.write(node.alias)
        if node.receiver is not None:
            self.write(".bind(None, ")
            self.traverse(node.receiver)
            self.write(")")

    def visit_StaticCast(self, node):
        self.traverse(node.value)

    def visit_ResultProjection(self, node):
        self.write("project_result[")
        self.traverse(node.obj.annotation)
        self.write("](")
        self.traverse(node.value)
        self.write(")")

    def visit_EvaluateOnce(self, node):
        self.write("$evaluate_once(")
        self.traverse(node.value)
        self.write("; ")
        self.traverse(node.body)
        self.write(")")

    def visit_UnpackAssignment(self, node):
        self.fill("$unpack = ")
        self.traverse(node.value)
        self.traverse(node.assignments)

    def visit_UnpackItem(self, node):
        self.write(f"$unpack[{node.index}]")

    def visit_Block(self, node: Block):
        self.fill(f"block {node.name}")
        if node.arguments:
            with self.delimit("(", ")"):
                def write_argument(argument):
                    self.write(f"{argument.name}: ")
                    self.traverse(argument.value_type.annotation)

                self.interleave(
                    lambda: self.write(", "),
                    write_argument,
                    node.arguments,
                )
        if node.exception_target is not None:
            self.write(f" except -> {node.exception_target}")
        with self.block():
            self.traverse(node.body)

    def visit_Lambda(self, node):
        if not hasattr(node, "blocks"):
            return super().visit_Lambda(node)
        self.write("lambda ")
        self.traverse(node.args)
        with self.block():
            self.traverse(node.blocks)

    def visit_Comprehension(self, node):
        lazy = getattr(node.function, "is_generator", False)
        kind = "generator" if lazy else "comprehension"
        self.write(f"{kind}({node.function.args.args[0].arg}=")
        if lazy:
            self.write("iter(")
        self.traverse(node.source)
        if lazy:
            self.write(")")
        self.write(")")
        with self.block():
            self.traverse(node.function.blocks)

    def visit_ExceptionRaise(self, node: ExceptionRaise):
        if not node.reraised and node.exception is not None:
            self.fill("raise ")
            self.traverse(node.exception)
        else:
            self.fill(("raise " if node.append_trace else "reraise ")
                      if node.reraised else f"raise {node.value_type.name}")
            if node.reraised:
                self.traverse(node.exception)
            elif node.message is not None:
                with self.delimit("(", ")"):
                    self.traverse(node.message)
        if node.cause is not None:
            self.write(" from ")
            self.traverse(node.cause)

    def visit_ExceptionDispatch(self, node: ExceptionDispatch):
        self.fill("dispatch_exception")
        with self.block():
            for types, target in node.handlers:
                names = " | ".join(value.name for value in types) or "*"
                self.fill(f"{names} -> {target}")
            self.fill(f"unmatched -> {node.unmatched or 'caller'}")

    def visit_ExceptionCatch(self, node: ExceptionCatch):
        self.fill("catch ")
        self.traverse(node.target)

    def visit_ContextExitCall(self, node):
        self.traverse(node.func)
        with self.delimit("(", ")"):
            if node.exceptional:
                self.write("exception_details=")
                self.traverse(node.exception)
            else:
                self.write("None, None, None")

    def visit_BlockArgument(self, node: BlockArgument):
        self.write(node.name)

    def visit_Branch(self, node: Branch):
        self.fill("branch ")
        self.traverse(node.test)
        with self.block():
            self.fill(f"true -> {node.true}")
            self.fill(f"false -> {node.false}")

    def visit_External(self, node: External):
        self.fill("external")

    def visit_Jump(self, node: Jump):
        self.fill(f"jump {node.target}")
        if node.arguments:
            with self.delimit("(", ")"):
                self.interleave(
                    lambda: self.write(", "),
                    self.traverse,
                    node.arguments,
                )

    def visit_Return(self, node: Return):
        self.fill("return")
        if node.value is not None:
            self.write(" ")
            self.traverse(node.value)

    def visit_Suspend(self, node):
        self.fill("yield ")
        self.traverse(node.value)
        self.write(f" -> {node.resume}")

    def visit_GeneratorInput(self, node):
        self.write("discard_resume_input()" if node.discard else "resume_input()")

    def visit_IteratorCreate(self, node: IteratorCreate):
        self.fill(f"{node.name} = {'bind_iterator' if node.acquired else 'iter'}(")
        self.traverse(node.iterable)
        self.write(")")

    def visit_IteratorNext(self, node: IteratorNext):
        self.fill(f"branch_next {node.iterator}")
        with self.block():
            self.fill("item ")
            self.traverse(node.target)
            self.write(f" -> {node.body}")
            self.fill(f"done -> {node.exhausted}")

    def write_allocation(self, node):
        # Independent lambda scopes receive lifetime summaries when lifted.
        boundary = node.lifetime.boundary.value if node.lifetime is not None else "unresolved"
        self.write(f"new[{boundary}] ")

    def visit_ObjectNew(self, node: ObjectNew):
        self.write_allocation(node)
        self.traverse(node.call)

    def visit_CollectionNew(self, node: CollectionNew):
        self.write_allocation(node)
        self.traverse(node.value_type.annotation)
        with self.delimit("(", ")"):
            if isinstance(node.source, ast.Dict):
                def write_item(item):
                    key, value = item
                    if key is None:
                        self.write("**")
                    else:
                        self.traverse(key)
                        self.write(": ")
                    self.traverse(value)

                self.interleave(
                    lambda: self.write(", "),
                    write_item,
                    zip(node.source.keys, node.source.values, strict=True),
                )
            else:
                self.interleave(
                    lambda: self.write(", "),
                    self.traverse,
                    node.source.elts,
                )

    def visit_FieldLoad(self, node: FieldLoad):
        self.write("load_field(")
        self.traverse(node.attribute.value)
        self.write(f", {node.attribute.attr})")

    def visit_FieldStore(self, node: FieldStore):
        self.fill("store_field(")
        self.traverse(node.target.value)
        self.write(f", {node.target.attr}, ")
        self.traverse(node.value)
        self.write(")")

    def visit_ListAppend(self, node: ListAppend):
        self.write("list_append(")
        self.traverse(node.call.func.value)
        self.write(", ")
        self.traverse(node.call.args[0])
        self.write(")")

    def visit_ChainedCompare(self, node):
        self.write("$chained_compare(")
        self.items_view(self.traverse, node.operands)
        self.write("; ")
        self.interleave(
            lambda: self.write(" and "),
            self.traverse,
            node.comparisons,
        )
        self.write(")")


def write_types(ast_obj):
    return TypeWriter().visit(ast_obj)

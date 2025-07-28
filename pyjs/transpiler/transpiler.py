import textwrap
from contextlib import contextmanager, nullcontext

from .analyzer import *


def transpile(entry_point):
    module = from_entry_point(entry_point)
    src = Transpiler(module).visit(module.node)
    return src


class Transpiler(ast._Unparser):

    def __init__(self, entry_point: Function):
        super().__init__()
        self.entry_point = entry_point

    def isolated_visit(self, node):
        return Transpiler(self.entry_point).visit(node)

    @contextmanager
    def block(self, *, extra = None):
        self.write(" {")
        self._indent += 1
        yield
        self._indent -= 1
        self.fill(f"}}")

    def visit_ModuleDef(self, node: ModuleDef):
        self.write(f"// {node.obj.name}")
        module = node.obj
        #for node in module.imports.values():
        #    self.transpile(node)
        for n in node.body:
            if should_include(n.obj):
                self.traverse(n)

    def visit_ClassDef(self, node):
        self.maybe_newline()
        self.fill("class " + node.name)
        if node.bases:
            assert len(node.bases) == 1
            self.write(" extends ")
            self.traverse(node.bases[0])
        with self.block():
            self.traverse(node.body)

    def visit_FunctionDef(self, node):
        self._function_helper(node, "function")

    def visit_AsyncFunctionDef(self, node):
        self._function_helper(node, "async def")

    def _function_helper(self, node, fill_suffix):
        self.maybe_newline()
        func = node.obj
        if node.name == "__init__":
            def_str = "constructor"
        elif func.is_method:
            def_str = ""
            if func.is_static:
                def_str = "static "
            def_str += node.name
        else:
            if hasattr(func.py_func, "__js_export__"):
                fill_suffix = "export "+fill_suffix
            def_str = fill_suffix + " " + node.name
        self.fill(def_str)
        with self.delimit("(", ")"):
            self.traverse(node.args)
        with self.block():
            if func.has_source_decorator:
                func_src = func.get_predefined_source()
                func_lines = textwrap.dedent(func_src).splitlines()
                for line in func_lines:
                    if line:
                        self.fill(line)
            else:
                self.traverse(node.body)

    def visit_arguments(self, node):
        first = True
        started_kw = False
        # normal arguments
        all_args = node.posonlyargs + node.args
        defaults = [None] * (len(all_args) - len(node.defaults)) + node.defaults
        for index, elements in enumerate(zip(all_args, defaults), 1):
            a, d = elements
            if first:
                first = False
            else:
                self.write(", ")
            if d and not started_kw:
                started_kw = True
                self.write("{ ")
            self.traverse(a)
            if d:
                self.write("=")
                self.traverse(d)
            if index == len(all_args) and started_kw:
                self.write("} = {}")

        if node.vararg:
            if not first:
                self.write(", ")
            self.write("...")
            self.write(node.vararg.arg)

    def visit_arg(self, node):
        self.write(node.arg)

    def visit_Call(self, node: Call):
        self.set_precedence(ast._Precedence.ATOM, node.func)

        if node.func.obj.has_inline_decorator:
            src = node.func.obj.rewrite_call(
                [self.isolated_visit(arg) for arg in node.args],
                [arg.obj if isinstance(arg.obj, (GenericClass, Class)) else arg.obj.cls for arg in node.args],
                self.isolated_visit(node.func.value) if isinstance(node.func, Attribute) else None,
            )
            self.write(src)
            return

        super_call = (
            isinstance(node.func, ast.Attribute) and
            isinstance(node.func.value, ast.Call) and
            isinstance(node.func.value.func, ast.Name) and
            node.func.value.func.id == "super"
        )

        if super_call:
            if node.func.attr == "__init__":
                self.write("super")
            else:
                self.write("super.")
                self.write(node.func.attr)
        elif isinstance(node.func.obj, Class):
            self.write("new ")
            self.traverse(node.func)
        else:
            self.traverse(node.func)

        with self.delimit("(", ")"):
            first = True
            for e in node.args:
                if not first:
                    self.write(", ")
                self.visit_call_arg(e)
                first = False
            if node.keywords:
                if not first:
                    self.write(", ")
                first = True
                with self.delimit("{", "}"):
                    for e in node.keywords:
                        if not first:
                            self.write(", ")
                        self.visit_call_arg(e)
                        first = False

    def visit_call_arg(self, node):
        self.traverse(node)
        if isinstance(node, Attribute) and isinstance(node.obj, Function):
            self.write(".bind")
            with self.delimit("(", ")"):
                self.traverse(node.value)

    def visit_keyword(self, node):
        self.write(node.arg)
        self.write(": ")
        self.traverse(node.value)

    def visit_Lambda(self, node):
        with self.require_parens(ast._Precedence.TEST, node):
            with self.delimit("(", ")"):
                self.traverse(node.args)
            self.write(" => ")
            self.set_precedence(ast._Precedence.TEST, node.body)
            self.traverse(node.body)

    def visit_Expr(self, node: ast.Expr):
        self.fill()
        self.set_precedence(ast._Precedence.YIELD, node.value)
        self.traverse(node.value)
        self.write(";")

    def visit_IfExp(self, node: ast.IfExp):
        with self.require_parens(ast._Precedence.TEST, node):
            self.set_precedence(ast._Precedence.TEST.next(), node.body, node.test)
            self.traverse(node.test)
            self.write(" ? ")
            self.traverse(node.body)
            self.write(" : ")
            self.set_precedence(ast._Precedence.TEST, node.orelse)
            self.traverse(node.orelse)

    def visit_ListComp(self, node):
        iter_node = node.generators[0]
        self.traverse(iter_node.iter)
        self.write(".map")
        with self.delimit("(", ")"):
            self.traverse(iter_node.target)
            self.write(" => ")
            self.traverse(node.elt)

    def visit_Assign(self, node):
        self.fill()
        assert len(node.targets) == 1
        target = node.targets[0]
        self.set_precedence(ast._Precedence.TUPLE, target)
        self.traverse(target)
        self.write(" = ")
        self.traverse(node.value)
        self.write(";")

    def visit_AnnAssign(self, node):
        self.fill()
        if isinstance(node.annotation, ast.Name) and node.annotation.id == "__static__":
            self.write("static ")
        else:
            self.write("var ")
        with self.delimit_if("(", ")", not node.simple and isinstance(node.target, ast.Name)):
            self.traverse(node.target)
        self.write(" = ")
        self.traverse(node.value)
        self.write(";")

    def visit_Name(self, node):
        if node.id == "self" and isinstance(node.obj, Instance):
            self.write("this")
        else:
            self.write(node.id)

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, tuple):
            with self.delimit("(", ")"):
                self.items_view(self._write_constant, value)
        elif value is ...:
            self.write("...")
        elif isinstance(node.value, bool):
            self.write(repr(node.value).lower())
        else:
            if node.kind == "u":
                self.write("u")
            self._write_constant(node.value)

    def visit_Dict(self, node: ast.Dict):
        def write_key_value_pair(k, v):
            with self.delimit("[", "]"):
                self.traverse(k)
                self.write(", ")
                self.traverse(v)

        def write_item(item):
            k, v = item
            if k is None:
                # for dictionary unpacking operator in dicts {**{'y': 2}}
                # see PEP 448 for details
                self.write("**")
                self.traverse(v)
            else:
                write_key_value_pair(k, v)

        with self.delimit("new Map([", "])"):
            self.interleave(
                lambda: self.write(", "), write_item, zip(node.keys, node.values)
            )

    def visit_If(self, node):
        self.fill("if ")
        with self.delimit("(", ")"):
            self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        while node.orelse and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
            self.write(" else if ")
            with self.delimit("(", ")"):
                self.traverse(node.test)
            with self.block():
                self.traverse(node.body)
        if node.orelse:
            self.write(" else")
            with self.block():
                self.traverse(node.orelse)

    def _for_helper(self, fill, node):
        self.fill(fill)
        self.set_precedence(ast._Precedence.TUPLE, node.target)
        with self.delimit("(", ")"):
            self.write("var ")
            if isinstance(node.target, ast.Tuple):
                with self.delimit("[","]"):
                    self.traverse(node.target)
            else:
                self.traverse(node.target)
            self.write(" of ")
            self.traverse(node.iter)
        with self.block():
            self.traverse(node.body)
        if node.orelse:
            self.fill("else")
            with self.block():
                self.traverse(node.orelse)

    def visit_Return(self, node: ast.Return):
        self.fill("return")
        if node.value:
            self.write(" ")
            self.traverse(node.value)
        self.write(";")

    def visit_Raise(self, node: ast.Raise):
        self.fill("throw ")
        if node.exc:
            self.write(repr(node.exc.id))
        else:
            self.write("undefined")
        self.write(";")

    unop = {"Invert": "~", "Not": "!", "UAdd": "+", "USub": "-"}
    def visit_UnaryOp(self, node):
        operator = self.unop[node.op.__class__.__name__]
        with self.require_parens(ast._Precedence.FACTOR, node):
            self.write(operator)
            self.set_precedence(ast._Precedence.FACTOR, node.operand)
            self.traverse(node.operand)

    def visit_Starred(self, node):
        self.write("...")
        self.set_precedence(ast._Precedence.EXPR, node.value)
        self.traverse(node.value)

    def visit_JoinedStr(self, node):
        for i, value in enumerate(node.values):
            self.traverse(value)
            if len(node.values) > 1 and i < (len(node.values)-1):
                self.write("+")

    def visit_FormattedValue(self, node: ast.FormattedValue):
        self.traverse(node.value)

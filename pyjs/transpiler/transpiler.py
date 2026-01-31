import textwrap
from itertools import chain
from contextlib import contextmanager

from pyjs.domx import CustomElement, HTMLElement, ProxyElement, ContextProxy
from .analyzer import *
from .utils import TailwindCSS


def transpile_module(module, importer=None, exporter=None):
    return Transpiler(module, importer, exporter).visit(module.node)


def generate_css(tailwind_classes: set):
    return TailwindCSS().get_css(tailwind_classes)


def prepare_bundle(entry_point_py_func, importer=None, exporter=None, include_main=False):
    entry_point, tailwind_classes = from_entry_point(entry_point_py_func)
    if include_main:
        entry_point.py_func.__js_include__ = True
    module = entry_point.container
    package = {}
    css = ""
    if tailwind_classes:
        css = generate_css(tailwind_classes)
    for module_name, module_obj in module.container.items():
        package[module_name] = transpile_module(module_obj, importer, exporter)
    return package, entry_point, css


def bundle(entry_point_py_func, include_main=False):
    package, entry_point, css = prepare_bundle(
        entry_point_py_func,
        lambda module, names: f"const {{{', '.join(names)}}} = __import_js__({repr(module)});",
        lambda name: f"__export_js__.{name} = {name};",
        include_main=include_main
    )
    source = []
    w = source.append
    w(textwrap.dedent("""\
    const modules = new Map();
    const define = (name, moduleFactory) => {
      modules.set(name, moduleFactory);
    };
    const moduleCache = new Map();
    const importModule = (name) => {
      if (moduleCache.has(name)) {
        return moduleCache.get(name).exports;
      }
      if (!modules.has(name)) {
        throw new Error(`Module '${name}' does not exist.`);
      }
      const moduleFactory = modules.get(name);
      const module = {exports: {}};
      moduleCache.set(name, module);
      moduleFactory(module.exports, importModule);
      return module.exports;
    };
    """))
    for module_name, module_js in package.items():
        if module_js:
            w(f"define({repr(module_name)}, function (__export_js__, __import_js__) {{\n")
            w(module_js)
            w("\n});\n")
    w(f"importModule({repr(entry_point.container.name)})")
    if entry_point.has_include_decorator:
        w(f".{entry_point.name}()")
    w(";\n")
    return "".join(source), css


class Transpiler(ast._Unparser):

    def __init__(self, entry_point: Function, importer=None, exporter=None):
        super().__init__()
        self.entry_point = entry_point
        self.importer = importer
        self.exporter = exporter

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
        module = node.obj
        for imported_module, imported_objs in module.imported.items():
            imported_names = [o.name for o in imported_objs if should_include(o)]
            if imported_names:
                if self.importer is not None:
                    self.fill(self.importer(imported_module, imported_names))
                else:
                    self.fill(f"import {{ {", ".join(imported_names)} }} from './{imported_module}.js';")
        for n in node.body:
            if should_include(n.obj) and n.obj.container.name == module.name:
                self.traverse(n)

    def visit_ClassDef(self, node):
        self.maybe_newline()
        export = "export " if self.exporter is None else ""
        self.fill(f"{export}class {node.name}")
        if node.bases:
            assert len(node.bases) == 1
            self.write(" extends ")
            self.traverse(node.bases[0])
        with self.block():
            self.traverse(node.body)
        if js_append := getattr(node.obj.py_cls, '__js_append__', None):
            self.fill(js_append())
        if self.exporter is not None:
            self.fill(self.exporter(node.name))

    def visit_FunctionDef(self, node):
        self._function_helper(node, "function")

    def visit_AsyncFunctionDef(self, node):
        self._function_helper(node, "async def")

    def _function_helper(self, node, fill_suffix):
        self.maybe_newline()
        func = node.obj
        is_custom_element_init = (
            func.name == "__init__" and
            func.is_method and
            issubclass(func.cls.py_obj, (CustomElement, ProxyElement)) and
            func.cls.py_obj != CustomElement
        )
        if is_custom_element_init:
            def_str = "_create"
        elif node.name == "__init__":
            def_str = "constructor"
        elif func.is_method:
            def_str = ""
            if func.is_static:
                def_str = "static "
            def_str += node.name
        else:
            if self.exporter is None and isinstance(func.container, Module):
                fill_suffix = "export " + fill_suffix
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
                if is_custom_element_init:
                    self.fill("return this;")
        if is_custom_element_init and issubclass(func.cls.py_obj, CustomElement):
            self.generate_bind_method(func)
        if self.exporter is not None and isinstance(func.container, Module):
            self.fill(self.exporter(node.name))

    def generate_bind_method(self, func):
        self.maybe_newline()
        self.fill("_hydrate()")
        with self.block():
            generator = HydrateGenerator(func, self)
            for line in func.body:
                generator.visit(line)

    def visit_arguments(self, node):
        first = True
        started_kw = False
        defaults = [None] * (len(node.args) - len(node.defaults)) + node.defaults
        for index, (arg, default) in enumerate(zip(node.args, defaults), 1):
            if first:
                first = False
            else:
                self.write(", ")
            if default and not started_kw:
                started_kw = True
                self.write("{ ")
            self.traverse(arg)
            if default:
                self.write("=")
                self.traverse(default)
            if index == len(node.args) and started_kw:
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

        if decorator_func := node.func.obj.inline_decorator:
            self_ = None
            if isinstance(node.func, Attribute):
                self_ = self.isolated_visit(node.func.value)
            elif isinstance(node.func.obj, Class):
                self_ = node.func.obj._self
            src = decorator_func.rewrite_call(
                [self.isolated_visit(arg) for arg in node.args],
                [arg.obj if isinstance(arg.obj, (GenericClass, Class)) else arg.obj.cls for arg in node.args],
                self_,
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
                if issubclass(node.func.value.obj.py_obj, CustomElement):
                    self.write("._create")
            else:
                self.write("super.")
                self.write(node.func.attr)
        elif isinstance(node.func.obj, Class):
            self.write("new ")
            self.traverse(node.func)
            if issubclass(node.func.obj.py_obj, CustomElement):
                self.write("()._create")
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
        elif isinstance(node.annotation, ast.Name) and node.annotation.id == "__const__":
            self.write("export const ")
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
        elif isinstance(node.value, type(None)):
            self.write("null")
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

    def visit_While(self, node):
        self.fill("while ")
        with self.delimit("(", ")"):
            self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        if node.orelse:
            raise NotImplementedError

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

    def visit_Pass(self, node: ast.Pass):
        pass

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


class HydrateGenerator(ast.NodeVisitor):

    def __init__(self, func: Function, transpiler: Transpiler):
        self.func = func
        self.transpiler = transpiler
        self.fill = transpiler.fill
        self.write = transpiler.write
        self.elements = set()
        self.self_id_set = False

    def add_self_id(self, self_):
        if not self.self_id_set:
            self.self_id_set = True
            self.fill("const self_id = this.get_data('self-id');")

    def visit_Assign(self, node: ast.Assign):
        targets = []
        for target in node.targets:
            if (isinstance(target, ast.Attribute) and
                isinstance(target.value, Name) and
                target.value.id == "self" and
                issubclass(node.value.obj.py_cls, (HTMLElement, ProxyElement))
            ):
                assert len(node.targets) == 1
                self.elements.add(target.obj)
                targets.append(target)
        if targets:
            target = targets[0]
            self.add_self_id(target.value)
            self.fill()
            self.transpiler.traverse(target)
            if issubclass(node.value.obj.py_cls, HTMLElement):
                self.write(f" = document.getElementById(self_id+'-{target.attr}');")
            elif issubclass(node.value.obj.py_cls, ProxyElement):
                self.write(f" = new {node.value.obj.name}()._hydrate(document.getElementById(self_id+'-{target.attr}'));")
            elif issubclass(node.value.obj.py_cls, ContextProxy):
                self.write(f" = document.getElementById(self_id+'-{target.attr}');")

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Call):
            func = node.value.func
            # TODO: this should probably just only allow addEventListener,
            #       a general customizable solution would be even better
            if isinstance(func, Attribute) and (func.value.obj in self.elements or func.attr == "addEventListener"):
                self.transpiler.traverse(node)
import textwrap
from _ast_unparse import Unparser as _Unparser
from _ast_unparse import _Precedence
from contextlib import contextmanager

from pyjs.web.domx import ContextProxy, CustomElement, HTMLElement, ProxyElement

from .analyzer import *
from .utils import TailwindCSS


def transpile_module(module, importer=None, exporter=None):
    return Transpiler(module, importer, exporter).visit(module.node)


def generate_css(tailwind_classes: set):
    return TailwindCSS().get_css(tailwind_classes)


def prepare_bundle(
    entry_point_py_func,
    importer=None,
    exporter=None,
    include_main=False,
    extensions: tuple[CompilationExtension, ...] = (),
    include_css=True,
):
    entry_point, tailwind_classes = from_entry_point(entry_point_py_func, extensions)
    if include_main:
        entry_point.py_func.__js_include__ = True
    module = entry_point.container
    package = {}
    css = ""
    if include_css and tailwind_classes:
        css = generate_css(tailwind_classes)
    for module_name, module_obj in module.container.items():
        package[module_name] = transpile_module(module_obj, importer, exporter)
    return package, entry_point, css


def bundle_import(module, names):
    imported_names = ", ".join(
        source if source == local else f"{source}: {local}" for source, local in names
    )
    return f"const {{{imported_names}}} = __import_js__({module!r});"


def bundle(
    entry_point_py_func,
    include_main=False,
    extensions: tuple[CompilationExtension, ...] = (),
    include_css=True,
    *,
    call_main: bool | None = None,
    expose_entry: bool = False,
):
    if call_main is None:
        call_main = include_main
    if call_main and not include_main:
        raise ValueError("call_main=True requires include_main=True")
    package, entry_point, css = prepare_bundle(
        entry_point_py_func,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_main=include_main,
        extensions=extensions,
        include_css=include_css,
    )
    source = _write_bundle(
        package, entry_point, call_main=call_main, expose_entry=expose_entry
    )
    return source, css


def _write_bundle(package, entry_point, *, call_main, expose_entry):
    source = []
    w = source.append
    w(
        textwrap.dedent("""\
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
    const __pyjsAssert__ = (condition, message) => {
      if (condition) {
        return;
      }
      throw new Error(message === undefined ? "Assertion failed" : String(message));
    };
    """)
    )
    for module_name, module_js in package.items():
        if module_js:
            w(f"define({repr(module_name)}, function (__export_js__, __import_js__) {{\n")
            w(module_js)
            w("\n});\n")
    if expose_entry:
        w("const __pyjsEntry__ = ")
    w(f"importModule({repr(entry_point.container.name)})")
    if call_main and entry_point.has_include_decorator:
        w(f".{entry_point.name}()")
    w(";\n")
    return "".join(source)


class Transpiler(_Unparser):
    def __init__(self, entry_point: Function, importer=None, exporter=None):
        super().__init__()
        self.entry_point = entry_point
        self.importer = importer
        self.exporter = exporter

    def isolated_visit(self, node, precedence=None):
        transpiler = Transpiler(self.entry_point)
        if isinstance(node, ast.IfExp):
            precedence = _Precedence.ATOM
        if precedence is not None:
            transpiler.set_precedence(precedence, node)
        return transpiler.visit(node)

    @staticmethod
    def operator_precedence(node):
        if isinstance(node.operator, ast.cmpop):
            operand_precedence = _Precedence.CMP.next()
            return _Precedence.CMP, operand_precedence, operand_precedence
        if isinstance(node.operator, ast.operator):
            operator = _Unparser.binop[type(node.operator).__name__]
            precedence = _Unparser.binop_precedence[operator]
            if operator in _Unparser.binop_rassoc:
                left_precedence, right_precedence = precedence.next(), precedence
            else:
                left_precedence, right_precedence = precedence, precedence.next()
            if node.reverse:
                left_precedence, right_precedence = right_precedence, left_precedence
            return precedence, left_precedence, right_precedence
        return None

    @contextmanager
    def block(self, *, extra=None):
        self.write(" {")
        self._indent += 1
        yield
        self._indent -= 1
        self.fill("}")

    def visit_ModuleDef(self, node: ModuleDef):
        module = node.obj
        for imported_module, imported_values in module.imported.items():
            imported_names = [
                (obj.name, local_name)
                for obj, local_name in imported_values
                if should_include(obj)
            ]
            if imported_names:
                if self.importer is not None:
                    self.fill(self.importer(imported_module, imported_names))
                else:
                    names = ", ".join(
                        source if source == local else f"{source} as {local}"
                        for source, local in imported_names
                    )
                    self.fill(f"import {{ {names} }} from './{imported_module}.js';")
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
        if js_append := getattr(node.obj.py_cls, "__js_append__", None):
            self.fill(js_append())
        if self.exporter is not None:
            self.fill(self.exporter(node.name))

    def visit_FunctionDef(self, node):
        self._function_helper(node, is_async=False)

    def visit_AsyncFunctionDef(self, node):
        self._function_helper(node, is_async=True)

    def _function_helper(self, node, is_async):
        self.maybe_newline()
        func = node.obj
        is_custom_element_init = (
            func.name == "__init__"
            and func.is_method
            and issubclass(func.cls.py_obj, (CustomElement, ProxyElement))
            and func.cls.py_obj != CustomElement
        )
        if is_custom_element_init:
            if is_async:
                raise NotImplementedError("custom element initialization cannot be async")
            def_str = "_create"
        elif node.name == "__init__":
            if is_async:
                raise NotImplementedError("constructors cannot be async")
            def_str = "constructor"
        elif func.is_method:
            def_str = ""
            if func.is_static:
                def_str = "static "
            if is_async:
                def_str += "async "
            def_str += node.name
        else:
            fill_suffix = "async function" if is_async else "function"
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
        required_count = len(node.args) - len(node.defaults)
        for arg in node.args[:required_count]:
            if first:
                first = False
            else:
                self.write(", ")
            self.traverse(arg)

        option_args = node.args[required_count:] + node.kwonlyargs
        option_defaults = node.defaults + node.kw_defaults
        if option_args:
            if not first:
                self.write(", ")
            self.write("{ ")
            for index, (arg, default) in enumerate(
                zip(option_args, option_defaults, strict=True)
            ):
                if index:
                    self.write(", ")
                self.traverse(arg)
                if default is not None:
                    self.write("=")
                    self.traverse(default)
            self.write("} = {}")
            first = False

        if node.vararg:
            if not first:
                self.write(", ")
            self.write("...")
            self.write(node.vararg.arg)

    def visit_arg(self, node):
        self.write(node.arg)

    def visit_Call(self, node: Call):
        self.set_precedence(_Precedence.ATOM, node.func)

        if decorator_func := getattr(node.func.obj, "inline_decorator", None):
            operator_rule = self.operator_precedence(node)
            if operator_rule is None:
                operator_precedence = None
                self_precedence = argument_precedence = None
            else:
                operator_precedence, self_precedence, argument_precedence = operator_rule
            self_ = None
            if isinstance(node.func, Attribute):
                self_ = self.isolated_visit(node.func.value, self_precedence)
            elif isinstance(node.func.obj, Class):
                self_ = node.func.obj._self
            src = decorator_func.rewrite_call(
                [self.isolated_visit(arg, argument_precedence) for arg in node.args],
                [
                    arg.obj if isinstance(arg.obj, (GenericClass, Class)) else arg.obj.cls
                    for arg in node.args
                ],
                self_,
                keyword_strs={
                    keyword.arg: self.isolated_visit(keyword.value)
                    for keyword in node.keywords
                    if keyword.arg is not None
                },
            )
            if operator_precedence is None:
                self.write(src)
            else:
                with self.require_parens(operator_precedence, node):
                    self.write(src)
            return

        super_call = (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        )

        if super_call:
            if node.func.attr == "__init__":
                self.write("super")
                if issubclass(node.func.value.obj.py_obj, (CustomElement, ProxyElement)):
                    self.write("._create")
            else:
                self.write("super.")
                self.write(node.func.attr)
        elif isinstance(node.func.obj, Class):
            cls = node.func.obj
            while cls is not None and cls.name != "Exception":
                cls = cls.super
            self.write("new ")
            if cls is not None:
                self.write("Error")
            else:
                self.traverse(node.func)
            if issubclass(node.func.obj.py_obj, (CustomElement, ProxyElement)):
                self.write("()._create")
        else:
            self.traverse(node.func)

        args = node.args
        trailing_args = []
        keywords = node.keywords
        called_function = node.func.obj
        is_builtin = False
        if isinstance(called_function, Class):
            is_builtin = called_function.py_obj.__dict__.get("__builtin__", False)
        elif isinstance(called_function, Function):
            is_builtin = getattr(called_function.py_obj, "__builtin__", False) or (
                called_function.cls is not None
                and called_function.cls.py_obj.__dict__.get("__builtin__", False)
            )
        if isinstance(called_function, Class):
            called_function = called_function.find("__init__")
        needs_empty_options = False
        if not is_builtin and isinstance(called_function, Function):
            lowered_default_args = False
            if called_function.defaults:
                first_default = len(called_function.params) - len(
                    called_function.defaults
                )
                default_args = args[first_default : len(called_function.params)]
                if default_args:
                    lowered_default_args = True
                    keywords = [
                        ast.keyword(arg=called_function.params[index].arg, value=value)
                        for index, value in enumerate(default_args, first_default)
                    ] + keywords
                    trailing_args = args[len(called_function.params) :]
                    args = args[:first_default]
            has_keyword_only_varargs = called_function.vararg is not None and bool(
                called_function.kwonlyargs
            )
            if has_keyword_only_varargs and not lowered_default_args:
                trailing_args = args[len(called_function.params) :]
                args = args[: len(called_function.params)]
            if has_keyword_only_varargs:
                needs_empty_options = bool(trailing_args) and not keywords

        with self.delimit("(", ")"):
            first = True
            for e in args:
                if not first:
                    self.write(", ")
                self.visit_call_arg(e)
                first = False
            if keywords or needs_empty_options:
                if not first:
                    self.write(", ")
                with self.delimit("{", "}"):
                    first_keyword = True
                    for e in keywords:
                        if not first_keyword:
                            self.write(", ")
                        self.visit_call_arg(e)
                        first_keyword = False
                first = False
            for e in trailing_args:
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
        with self.require_parens(_Precedence.TEST, node):
            with self.delimit("(", ")"):
                self.traverse(node.args)
            self.write(" => ")
            self.set_precedence(_Precedence.TEST, node.body)
            self.traverse(node.body)

    def visit_Expr(self, node: ast.Expr):
        self.fill()
        self.set_precedence(_Precedence.YIELD, node.value)
        self.traverse(node.value)
        self.write(";")

    def visit_IfExp(self, node: ast.IfExp):
        with self.require_parens(_Precedence.TEST, node):
            self.set_precedence(_Precedence.TEST.next(), node.body, node.test)
            self.traverse(node.test)
            self.write(" ? ")
            self.traverse(node.body)
            self.write(" : ")
            self.set_precedence(_Precedence.TEST, node.orelse)
            self.traverse(node.orelse)

    boolops = {"And": "&&", "Or": "||"}
    boolop_precedence = {"&&": _Precedence.AND, "||": _Precedence.OR}

    def visit_BoolOp(self, node):
        operator = self.boolops[node.op.__class__.__name__]
        operator_precedence = self.boolop_precedence[operator]

        def increasing_level_traverse(value):
            nonlocal operator_precedence
            operator_precedence = operator_precedence.next()
            self.set_precedence(operator_precedence, value)
            self.traverse(value)

        with self.require_parens(operator_precedence, node):
            separator = f" {operator} "
            self.interleave(
                lambda: self.write(separator), increasing_level_traverse, node.values
            )

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
        self.set_precedence(_Precedence.TUPLE, target)
        self.traverse(target)
        self.write(" = ")
        self.traverse(node.value)
        self.write(";")

    def visit_AnnAssign(self, node):
        self.fill()
        annotation_id = (
            node.annotation.id if isinstance(node.annotation, ast.Name) else None
        )
        if isinstance(node.target, ast.Attribute):
            pass
        elif annotation_id == "__static__":
            self.write("static ")
        elif annotation_id == "__const__":
            self.write("export const ")
        else:
            self.write("var ")
        with self.delimit_if(
            "(", ")", not node.simple and isinstance(node.target, ast.Name)
        ):
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
                lambda: self.write(", "),
                write_item,
                zip(node.keys, node.values, strict=True),
            )

    def visit_If(self, node):
        self.fill("if ")
        with self.delimit("(", ")"):
            self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        while (
            node.orelse and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
        ):
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

    def visit_Try(self, node: ast.Try):
        self.fill("try")
        with self.block():
            self.traverse(node.body)
        if node.handlers:
            handler = node.handlers[0]
            self.write(f" catch ({handler.name or '_error'})")
            with self.block():
                self.traverse(handler.body)
        if node.finalbody:
            self.write(" finally")
            with self.block():
                self.traverse(node.finalbody)

    def _for_helper(self, fill, node):
        self.fill(fill)
        self.set_precedence(_Precedence.TUPLE, node.target)
        with self.delimit("(", ")"):
            self.write("var ")
            if isinstance(node.target, ast.Tuple):
                with self.delimit("[", "]"):
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

    def visit_Await(self, node: ast.Await):
        self.write("await ")
        self.traverse(node.value)

    def visit_Pass(self, node: ast.Pass):
        pass

    def visit_Raise(self, node: ast.Raise):
        self.fill("throw ")
        if node.exc:
            self.traverse(node.exc)
        else:
            self.write("undefined")
        self.write(";")

    unop = {"Invert": "~", "Not": "!", "UAdd": "+", "USub": "-"}

    def visit_UnaryOp(self, node):
        operator = self.unop[node.op.__class__.__name__]
        with self.require_parens(_Precedence.FACTOR, node):
            self.write(operator)
            inline_call = (
                isinstance(node.operand, Call)
                and isinstance(node.operand.func.obj, Function)
                and node.operand.func.obj.inline_decorator
            )
            if inline_call:
                with self.delimit("(", ")"):
                    self.traverse(node.operand)
            else:
                self.set_precedence(_Precedence.FACTOR, node.operand)
                self.traverse(node.operand)

    def visit_Starred(self, node):
        self.write("...")
        self.set_precedence(_Precedence.EXPR, node.value)
        self.traverse(node.value)

    def visit_JoinedStr(self, node):
        for i, value in enumerate(node.values):
            self.traverse(value)
            if len(node.values) > 1 and i < (len(node.values) - 1):
                self.write("+")

    def visit_FormattedValue(self, node: ast.FormattedValue):
        self.traverse(node.value)

    def visit_Assert(self, node: ast.Assert):
        self.fill("__pyjsAssert__(")
        self.traverse(node.test)
        if node.msg:
            self.write(", ")
            self.traverse(node.msg)
        self.write(");")


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
        if not (isinstance(node.value, Call) and getattr(node.value, "is_ref", False)):
            return

        targets = []
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, Name)
                and target.value.id == "self"
                and issubclass(node.value.obj.py_cls, (HTMLElement, ProxyElement))
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
                self.write(
                    f" = new {node.value.obj.name}()._hydrate(document.getElementById(self_id+'-{target.attr}'));"
                )
            elif issubclass(node.value.obj.py_cls, ContextProxy):
                self.write(f" = document.getElementById(self_id+'-{target.attr}');")

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, Attribute)
                and func.attr == "__init__"
                and isinstance(func.value, Call)
                and isinstance(func.value.func, Name)
                and func.value.func.id == "super"
            ):
                self.fill("super._hydrate();")
                return
            # TODO: this should probably just only allow addEventListener,
            #       a general customizable solution would be even better
            if isinstance(func, Attribute) and (
                func.value.obj in self.elements or func.attr == "addEventListener"
            ):
                self.transpiler.traverse(node)

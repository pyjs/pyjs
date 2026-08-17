import re
import textwrap
from _ast_unparse import Unparser as _Unparser
from _ast_unparse import _Precedence
from contextlib import contextmanager

from pyjs.web.domx import ContextProxy, CustomElement, HTMLElement, ProxyElement

from .analyzer import *
from .utils import TailwindCSS

FORMAT_SPEC = re.compile(
    r"(?P<zero>0)?(?P<width>\d+)?(?:\.(?P<precision>\d+))?(?P<type>[df%])"
)

BUILTIN_EXCEPTION_NAMES = {
    "Exception": "Error",
    "TypeError": "TypeError",
    "ValueError": "RangeError",
}

JAVASCRIPT_RESERVED_IDENTIFIERS = {
    "arguments",
    "await",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "eval",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "function",
    "if",
    "implements",
    "import",
    "in",
    "instanceof",
    "interface",
    "let",
    "new",
    "null",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "static",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "var",
    "void",
    "while",
    "with",
    "yield",
}


def javascript_identifier(name: str) -> str:
    if name in JAVASCRIPT_RESERVED_IDENTIFIERS:
        return f"$${name}"
    return name


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
    additional_entry_points: tuple[callable, ...] = (),
):
    entry_point, tailwind_classes = from_entry_point(
        entry_point_py_func,
        extensions,
        additional_entry_points,
    )
    try:
        if include_main:
            entry_point.py_func.__js_keep__ = True
        module = entry_point.container
        package = {}
        css = ""
        if include_css and tailwind_classes:
            css = generate_css(tailwind_classes)
        for module_name, module_obj in module.container.items():
            package[module_name] = transpile_module(module_obj, importer, exporter)
        return package, entry_point, css
    except BaseException:
        release_compilation(entry_point)
        raise


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
    additional_entry_points: tuple[callable, ...] = (),
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
        additional_entry_points=additional_entry_points,
    )
    try:
        source = _write_bundle(
            package, entry_point, call_main=call_main, expose_entry=expose_entry
        )
        return source, css
    finally:
        release_compilation(entry_point)


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
    const __pyjsAssert__ = (condition, message, AssertionError) => {
      if (condition) {
        return;
      }
      throw new AssertionError(message === undefined ? "" : String(message()));
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
    if call_main and entry_point.has_keep_decorator:
        w(f".{javascript_identifier(entry_point.name)}()")
    w(";\n")
    return "".join(source)


class Transpiler(_Unparser):
    def __init__(self, entry_point: Function, importer=None, exporter=None):
        super().__init__()
        self.entry_point = entry_point
        self.importer = importer
        self.exporter = exporter
        self.temporary_index = 0

    def temporary_name(self, prefix: str) -> str:
        name = f"${prefix}{self.temporary_index}"
        self.temporary_index += 1
        return name

    @staticmethod
    def builtin_exception_name(value) -> str | None:
        if not isinstance(value, Class) or not value.container.scope.is_builtins:
            return None
        return BUILTIN_EXCEPTION_NAMES.get(value.name)

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
            imported_names = []
            for obj, local_name in imported_values:
                if isinstance(obj, GenericClass):
                    imported_names.extend(
                        (
                            javascript_identifier(concrete.name),
                            javascript_identifier(concrete.name),
                        )
                        for concrete in obj.concrete_classes.values()
                        if should_include(concrete)
                    )
                elif should_include(obj):
                    imported_names.append(
                        (
                            javascript_identifier(obj.name),
                            javascript_identifier(local_name),
                        )
                    )
            if imported_names:
                if self.importer is not None:
                    self.fill(self.importer(imported_module, imported_names))
                else:
                    names = ", ".join(
                        source if source == local else f"{source} as {local}"
                        for source, local in imported_names
                    )
                    self.fill(f"import {{ {names} }} from './{imported_module}.js';")
        for dependency, alias in module.inline_dependencies.items():
            if dependency.container is module and should_include(dependency):
                self.fill(
                    f"const {alias} = {javascript_identifier(dependency.name)};"
                )
        for n in node.body:
            if should_include(n.obj) and n.obj.container.name == module.name:
                self.traverse(n)

    def visit_ClassDef(self, node):
        self.maybe_newline()
        export = "export " if self.exporter is None else ""
        class_name = javascript_identifier(node.name)
        self.fill(f"{export}class {class_name}")
        if node.bases:
            assert len(node.bases) == 1
            self.write(" extends ")
            if node.obj.runtime_super_dependency is not None:
                self.traverse(node.bases[0])
            elif exception_name := self.builtin_exception_name(node.obj.super):
                self.write(exception_name)
            else:
                self.traverse(node.bases[0])
        with self.block():
            self.traverse(node.body)
        if node.obj.client_defaults:
            self.fill(f"{class_name}.__pyjs_defaults__ = ")
            self.traverse(
                ast.Dict(
                    keys=[
                        ast.Constant(value=name)
                        for name in node.obj.client_defaults
                    ],
                    values=list(node.obj.client_defaults.values()),
                )
            )
            self.write(";")
        if node.obj.client_required:
            self.fill(f"{class_name}.__pyjs_required__ = ")
            self.traverse(
                ast.List(
                    elts=[
                        ast.Constant(value=name)
                        for name in node.obj.client_required
                    ],
                    ctx=ast.Load(),
                )
            )
            self.write(";")
        if node.obj.client_fields:
            self.fill(f"{class_name}.__pyjs_fields__ = new Map(")
            with self.delimit("[", "]"):
                for index, (name, value_type) in enumerate(
                    node.obj.client_fields.items()
                ):
                    if index:
                        self.write(", ")
                    with self.delimit("[", "]"):
                        self.traverse(ast.Constant(value=name))
                        self.write(", ")
                        self.write_client_field_descriptor(node.obj, value_type)
            self.write(");")
        if js_append := getattr(node.obj.py_cls, "__js_append__", None):
            included_members = {
                name
                for name, member in node.obj._self.attrs.items()
                if should_include(member)
            }
            self.fill(js_append(included_members))
        if self.exporter is not None:
            self.fill(self.exporter(class_name))

    def write_client_field_descriptor(self, owner, value_type):
        if isinstance(value_type, UnionType):
            with self.delimit("[", "]"):
                self.traverse(ast.Constant(value="union"))
                for member in value_type.types:
                    self.write(", ")
                    self.write_client_field_descriptor(owner, member)
            return
        if isinstance(value_type, LiteralClass):
            with self.delimit("[", "]"):
                self.traverse(ast.Constant(value="literal"))
                for value in value_type.values:
                    self.write(", ")
                    self.traverse(ast.Constant(value=value))
            return
        if is_client_model_type(value_type):
            self.write(
                javascript_identifier(
                    owner.client_model_aliases.get(value_type, value_type.name)
                )
            )
            return
        type_name = value_type.generic_name or value_type.name
        if type_name in {"dict", "list", "set", "tuple"}:
            with self.delimit("[", "]"):
                self.traverse(ast.Constant(value=type_name))
                for member in value_type.generic_types.values():
                    self.write(", ")
                    self.write_client_field_descriptor(owner, member)
            return
        self.traverse(ast.Constant(value=type_name))

    def visit_FunctionDef(self, node):
        self._function_helper(node, is_async=False)

    def visit_AsyncFunctionDef(self, node):
        self._function_helper(node, is_async=True)

    def visit_StaticCast(self, node):
        self.traverse(node.value)

    def _function_helper(self, node, is_async):
        self.maybe_newline()
        func = node.obj
        assert not (func.is_generator and is_async)
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
            if func.is_property:
                def_str = "get "
            elif func.is_property_setter:
                def_str = "set "
            else:
                def_str = ""
            if func.is_static:
                def_str = "static "
            if is_async:
                def_str += "async "
            if func.is_generator:
                def_str += "*"
            def_str += node.name
        else:
            if is_async:
                fill_suffix = "async function"
            elif func.is_generator:
                fill_suffix = "function*"
            else:
                fill_suffix = "function"
            if self.exporter is None and isinstance(func.container, Module):
                fill_suffix = "export " + fill_suffix
            def_str = fill_suffix + " " + javascript_identifier(node.name)
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
            self.fill(self.exporter(javascript_identifier(node.name)))

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
                emitted_name = javascript_identifier(arg.arg)
                if emitted_name != arg.arg:
                    self.write(f"{arg.arg}: ")
                self.write(emitted_name)
                if default is not None:
                    self.write("=")
                    self.traverse(default)
            self.write("} = {}")
            first = False

        if node.vararg:
            if not first:
                self.write(", ")
            self.write("...")
            self.write(javascript_identifier(node.vararg.arg))

    def visit_arg(self, node):
        self.write(javascript_identifier(node.arg))

    def visit_RuntimeFunctionReference(self, node: RuntimeFunctionReference):
        self.write(node.alias)
        if node.receiver is not None:
            self.write(".bind(null, ")
            self.traverse(node.receiver)
            self.write(")")

    def visit_BoundGetattr(self, node: BoundGetattr):
        self.write(f"((obj,fallback)=>obj.{node.obj.name}.bind(obj))(")
        self.traverse(node.receiver)
        self.write(",")
        self.traverse(node.default)
        self.write(")")

    def visit_Call(self, node: Call):
        self.set_precedence(_Precedence.ATOM, node.func)
        call_target = (
            node.func.value_obj
            if isinstance(node.func, (Call, Subscript))
            else node.func.obj
        )

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
                    arg.obj
                    if isinstance(arg.obj, (GenericClass, Class, UnionType))
                    else arg.obj.cls
                    for arg in node.args
                ],
                self_,
                keyword_strs={
                    keyword.arg: self.isolated_visit(keyword.value)
                    for keyword in node.keywords
                    if keyword.arg is not None
                },
                inline_dependencies=node.inline_dependencies,
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
        elif isinstance(call_target, Class):
            self.write("new ")
            self.traverse(node.func)
            if issubclass(call_target.py_obj, (CustomElement, ProxyElement)):
                self.write("()._create")
        else:
            self.traverse(node.func)

        args = node.args
        trailing_args = []
        keywords = node.keywords
        called_function = call_target
        is_builtin = False
        if isinstance(called_function, Class):
            base = called_function
            while base is not None and base.name != "Exception":
                base = base.super
            is_builtin = (
                base is not None
                or called_function.py_obj.__dict__.get("__builtin__", False)
            )
        elif isinstance(called_function, Function):
            is_builtin = getattr(called_function.py_obj, "__builtin__", False) or (
                called_function.cls is not None
                and called_function.cls.py_obj.__dict__.get("__builtin__", False)
            )
        elif isinstance(called_function, Instance):
            called_function = called_function.find("__call__")
        if isinstance(called_function, Class):
            called_function = called_function.find("__init__")
        needs_empty_options = False
        if not is_builtin and isinstance(called_function, Function):
            required_count = len(called_function.params) - len(
                called_function.defaults
            )
            if len(args) < required_count:
                keyword_values = {
                    keyword.arg: keyword.value for keyword in keywords
                }
                lowered_names = set()
                for param in called_function.params[len(args) : required_count]:
                    if param.arg not in keyword_values:
                        break
                    args.append(keyword_values[param.arg])
                    lowered_names.add(param.arg)
                keywords = [
                    keyword
                    for keyword in keywords
                    if keyword.arg not in lowered_names
                ]

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
        if isinstance(node, Attribute) and isinstance(node.obj, Function):
            receiver = self.isolated_visit(node.value)
            source = self.isolated_visit(node)
            bind_source = getattr(node.obj.py_func, "__js_bind_source__", None)
            if bind_source is not None:
                source = bind_source(source, receiver)
            else:
                source += f".bind({receiver})"
            self.write(source)
            return
        self.traverse(node)

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
        if len(node.generators) > 1 or not isinstance(
            node.generators[0].target, ast.Name
        ):
            self.visit_expanded_comprehension(node, "[]", "push")
            return
        iter_node = node.generators[0]
        self.write("Array.from(")
        self.traverse(iter_node.iter)
        self.write(")")
        for condition in iter_node.ifs:
            self.write(".filter")
            with self.delimit("(", ")"):
                self.traverse(iter_node.target)
                self.write(" => ")
                self.traverse(condition)
        self.write(".map")
        with self.delimit("(", ")"):
            self.traverse(iter_node.target)
            self.write(" => ")
            self.traverse(node.elt)

    def visit_DictComp(self, node):
        self.visit_expanded_comprehension(node, "new Map()", "set")

    def visit_SetComp(self, node):
        self.visit_expanded_comprehension(node, "new Set()", "add")

    def visit_GeneratorExp(self, node):
        self.write("(($iterator)=>(function*(){")
        self.visit_comprehension_loops(node, outer_iter="$iterator")
        self.write("})())((")
        self.traverse(node.generators[0].iter)
        self.write(")[Symbol.iterator]())")

    def visit_expanded_comprehension(self, node, initializer, method):
        self.write(f"(()=>{{const $result={initializer};")
        self.visit_comprehension_loops(node, method)
        self.write("return $result;})()")

    def visit_comprehension_loops(self, node, method=None, outer_iter=None):
        condition_counts = []
        for index, generator in enumerate(node.generators):
            self.write("for(const ")
            self.traverse(generator.target)
            self.write(" of ")
            if index == 0 and outer_iter is not None:
                self.write(outer_iter)
            else:
                self.traverse(generator.iter)
            self.write("){")
            for condition in generator.ifs:
                self.write("if(")
                self.traverse(condition)
                self.write("){")
            condition_counts.append(len(generator.ifs))
        self.write("yield " if method is None else f"$result.{method}(")
        if isinstance(node, ast.DictComp):
            self.traverse(node.key)
            self.write(",")
            self.traverse(node.value)
        else:
            self.traverse(node.elt)
        self.write(";" if method is None else ");")
        for condition_count in reversed(condition_counts):
            self.write("}" * (condition_count + 1))

    def visit_Subscript(self, node):
        receiver_obj = (
            node.value.value_obj
            if isinstance(node.value, (Call, Subscript))
            else node.value.obj
        )
        receiver_type = (
            receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
        )
        negative_index = (
            isinstance(node.slice, UnaryOp)
            and isinstance(node.slice.op, ast.USub)
            and isinstance(node.slice.operand, Constant)
            and isinstance(node.slice.operand.value, int)
        )
        if negative_index and getattr(receiver_type, "generic_name", None) in {
            "list",
            "str",
            "tuple",
        }:
            self.traverse(node.value)
            self.write(".at(")
            self.traverse(node.slice)
            self.write(")")
            return
        super().visit_Subscript(node)

    def visit_Assign(self, node):
        self.fill()
        assert len(node.targets) == 1
        target = node.targets[0]
        if isinstance(target, (ast.Tuple, ast.List)) and getattr(
            node, "declares_name", False
        ):
            self.write("var ")
        self.set_precedence(_Precedence.TUPLE, target)
        self.traverse(target)
        self.write(" = ")
        self.traverse(node.value)
        self.write(";")

    def visit_UnpackAssignment(self, node):
        temporary = self.temporary_name("unpack")
        self.fill(f"const {temporary} = ")
        self.traverse(node.value)
        self.write(";")
        for assignment in node.assignments:
            for child in ast.walk(assignment):
                if isinstance(child, UnpackItem):
                    child.temporary = temporary
        self.traverse(node.assignments)

    def visit_UnpackItem(self, node):
        self.write(f"{node.temporary}[{node.index}]")

    def visit_Delete(self, node):
        for target in node.targets:
            self.fill()
            if isinstance(target, ast.Name):
                self.traverse(target)
                self.write(" = undefined;")
            else:
                self.write("delete ")
                self.traverse(target)
                self.write(";")

    def visit_AnnAssign(self, node):
        self.fill()
        annotation_id = (
            node.annotation.id if isinstance(node.annotation, ast.Name) else None
        )
        is_module_binding = annotation_id in {"__const__", "__module__"}
        if isinstance(node.target, ast.Attribute):
            pass
        elif annotation_id == "__static__":
            self.write("static ")
        elif annotation_id == "__const__":
            self.write("export const " if self.exporter is None else "const ")
        elif annotation_id == "__module__":
            self.write("export let " if self.exporter is None else "let ")
        else:
            self.write("var ")
        with self.delimit_if(
            "(", ")", not node.simple and isinstance(node.target, ast.Name)
        ):
            self.traverse(node.target)
        self.write(" = ")
        self.traverse(node.value)
        self.write(";")
        if is_module_binding and self.exporter is not None:
            self.fill(self.exporter(javascript_identifier(node.target.id)))

    def visit_Name(self, node):
        value = getattr(node, "obj", None)
        if node.id == "self" and isinstance(value, Instance):
            self.write("this")
        elif getattr(node, "runtime_dependency", None) is not None:
            self.write(getattr(node, "runtime_alias", node.id))
        elif exception_name := self.builtin_exception_name(value):
            self.write(exception_name)
        elif node.id in {"super", "this"} and isinstance(value, Class):
            self.write(node.id)
        else:
            self.write(javascript_identifier(node.id))

    def visit_Attribute(self, node):
        if getattr(node, "module_import_alias", None) is not None:
            self.write(javascript_identifier(node.module_import_alias))
            return
        super().visit_Attribute(node)

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, tuple):
            with self.delimit("[", "]"):
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
        if isinstance(getattr(node, "obj", None), TypedDictClass):
            def write_object_item(item):
                key, value = item
                if key is None:
                    self.write("...")
                    self.traverse(value)
                    return
                self.traverse(key)
                self.write(": ")
                self.traverse(value)

            with self.delimit("{", "}"):
                self.interleave(
                    lambda: self.write(", "),
                    write_object_item,
                    zip(node.keys, node.values, strict=True),
                )
            return

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

    def visit_Set(self, node: ast.Set):
        with self.delimit("new Set([", "])"):
            self.interleave(lambda: self.write(", "), self.traverse, node.elts)

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
        if node.orelse and node.finalbody:
            self.fill("try")
            with self.block():
                self._write_try_with_else(node)
            self.write(" finally")
            with self.block():
                self.traverse(node.finalbody)
            return
        if node.orelse:
            self._write_try_with_else(node)
            return
        self.fill("try")
        with self.block():
            self.traverse(node.body)
        if node.handlers:
            self._write_except_handlers(node.handlers)
        if node.finalbody:
            self.write(" finally")
            with self.block():
                self.traverse(node.finalbody)

    def _write_try_with_else(self, node: ast.Try) -> None:
        succeeded = self.temporary_name("try")
        self.fill(f"let {succeeded} = true;")
        self.fill("try")
        with self.block():
            self.traverse(node.body)
        self._write_except_handlers(node.handlers, failed_flag=succeeded)
        self.fill(f"if ({succeeded})")
        with self.block():
            self.traverse(node.orelse)

    def _write_except_handlers(
        self,
        handlers: list[ast.ExceptHandler],
        *,
        failed_flag: str | None = None,
    ) -> None:
        for index, handler in enumerate(handlers):
            if self._is_catch_all(handler):
                handlers = handlers[: index + 1]
                break
        if len(handlers) == 1 and self._is_catch_all(handlers[0]):
            handler = handlers[0]
            name = javascript_identifier(handler.name) if handler.name else "_error"
            self.write(f" catch ({name})")
            with self.block():
                if failed_flag is not None:
                    self.fill(f"{failed_flag} = false;")
                self.traverse(handler.body)
            return

        error = self.temporary_name("error")
        self.write(f" catch ({error})")
        with self.block():
            if failed_flag is not None:
                self.fill(f"{failed_flag} = false;")
            has_catch_all = False
            for index, handler in enumerate(handlers):
                catch_all = self._is_catch_all(handler)
                if catch_all:
                    self.write(" else")
                elif index:
                    self.write(" else if (")
                    self._write_exception_test(handler.type, error)
                    self.write(")")
                else:
                    self.fill("if (")
                    self._write_exception_test(handler.type, error)
                    self.write(")")
                with self.block():
                    if handler.name is not None:
                        self.fill(
                            f"let {javascript_identifier(handler.name)} = {error};"
                        )
                    self.traverse(handler.body)
                if catch_all:
                    has_catch_all = True
                    break
            if not has_catch_all:
                self.write(" else")
                with self.block():
                    self.fill(f"throw {error};")

    @staticmethod
    def _is_catch_all(handler: ast.ExceptHandler) -> bool:
        return handler.type is None or (
            isinstance(handler.type, Name)
            and isinstance(handler.type.obj, Class)
            and handler.type.obj.name == "Exception"
        )

    def _write_exception_test(self, type_node: ast.expr, error: str) -> None:
        types = type_node.elts if isinstance(type_node, ast.Tuple) else [type_node]
        for index, exception_type in enumerate(types):
            if index:
                self.write(" || ")
            self.write(f"{error} instanceof ")
            self.traverse(exception_type)

    def visit_With(self, node: ast.With) -> None:
        item = node.items[0]
        manager = self.temporary_name("manager")
        entered = self.temporary_name("entered")
        caught = self.temporary_name("caught")
        failed = self.temporary_name("failed")
        self.fill(f"const {manager} = ")
        self.traverse(item.context_expr)
        self.write(";")
        self.fill(f"const {entered} = {manager}.__enter__();")
        self.fill(f"let {failed} = false;")
        self.fill("try")
        with self.block():
            if item.optional_vars is not None:
                self.fill("var " if node.declares_target else "")
                self.traverse(item.optional_vars)
                self.write(f" = {entered};")
            self.traverse(node.body)
        self.write(f" catch ({caught})")
        with self.block():
            self.fill(f"{failed} = true;")
            self.fill(
                f"if (!{manager}.__exit__("
                f"{caught}.constructor, {caught}, null))"
            )
            with self.block():
                self.fill(f"throw {caught};")
        self.write(" finally")
        with self.block():
            self.fill(f"if (!{failed})")
            with self.block():
                self.fill(f"{manager}.__exit__(null, null, null);")

    def _for_helper(self, fill, node):
        self.fill(fill)
        self.set_precedence(_Precedence.TUPLE, node.target)
        with self.delimit("(", ")"):
            self.write("var ")
            if isinstance(node.target, ast.Tuple):
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

    def visit_Tuple(self, node: ast.Tuple):
        with self.delimit("[", "]"):
            self.interleave(lambda: self.write(", "), self.traverse, node.elts)

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
        value = self.isolated_visit(node.value, _Precedence.ATOM)
        spec = self.constant_format_spec(node.format_spec)
        match = FORMAT_SPEC.fullmatch(spec) if spec is not None else None
        if match is None:
            self.write(value)
            return

        number_type = match.group("type")
        precision = match.group("precision")
        if number_type == "d":
            formatted = f"String(Math.trunc({value}))"
            absolute = "String(Math.abs(Math.trunc(value)))"
        else:
            precision = precision or "6"
            number = f"Number({value})"
            absolute_number = "Math.abs(Number(value))"
            if number_type == "%":
                number = f"({number} * 100)"
                absolute_number = f"({absolute_number} * 100)"
            suffix = " + '%'" if number_type == "%" else ""
            formatted = f"{number}.toFixed({precision}){suffix}"
            absolute = f"{absolute_number}.toFixed({precision}){suffix}"

        width = match.group("width")
        if width is None:
            self.write(formatted)
        elif match.group("zero"):
            self.write(
                "((value) => (value < 0 ? '-' : '') + "
                f"({absolute}).padStart({width} - (value < 0 ? 1 : 0), '0'))"
                f"({value})"
            )
        else:
            self.write(f"({formatted}).padStart({width}, ' ')")

    @staticmethod
    def constant_format_spec(node: ast.JoinedStr | None) -> str | None:
        if node is None or not all(
            isinstance(value, ast.Constant) and isinstance(value.value, str)
            for value in node.values
        ):
            return None
        return "".join(value.value for value in node.values)

    def visit_Assert(self, node: ast.Assert):
        self.fill("__pyjsAssert__(")
        self.traverse(node.test)
        if node.msg:
            self.write(", () => ")
            self.traverse(node.msg)
        else:
            self.write(", undefined")
        self.write(", ")
        self.write(node.runtime_alias)
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
                    " = new "
                    f"{javascript_identifier(node.value.obj.name)}()"
                    f"._hydrate(document.getElementById(self_id+'-{target.attr}'));"
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

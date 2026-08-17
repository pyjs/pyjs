import annotationlib
import ast
import dataclasses
import importlib.util
import inspect
import sys
import types
import typing
import weakref
from collections.abc import Callable, Iterable
from functools import partial
from typing import Generic

from pyjs.decorators import *

from .diagnostics import CompilationContext, DiagnosticCode, SourceFragment
from .libraries import (
    library_class_info,
    resolve_library_import,
    stdlib_import_target,
)

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
JS_MODULE_VALUE_TYPES = (bool, int, float, str, list, dict, type(None))


def _contains_yield(node: FunctionNode) -> bool:
    pending = list(ast.iter_child_nodes(node))
    while pending:
        child = pending.pop()
        if isinstance(child, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(
            child,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
        ):
            continue
        pending.extend(ast.iter_child_nodes(child))
    return False


def py_to_ast(value):
    if isinstance(value, (bool, int, float, str, type(None))):
        return ast.Constant(value=value)
    elif isinstance(value, (list, tuple, set)):
        return {list: ast.List, tuple: ast.Tuple, set: ast.Set}[type(value)](
            elts=[py_to_ast(v) for v in value]
        )
    elif isinstance(value, dict):
        return ast.Dict(
            keys=[py_to_ast(k) for k in value.keys()],
            values=[py_to_ast(v) for v in value.values()],
        )
    else:
        raise TypeError(f"Unsupported type: {type(value)}")


def _annotation_source(annotation) -> str:
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, annotationlib.ForwardRef):
        return annotation.__forward_arg__
    if annotation is None or annotation is type(None):
        return "None"
    if annotation is Ellipsis:
        return "..."
    origin = typing.get_origin(annotation)
    if origin in (types.UnionType, typing.Union):
        return " | ".join(
            _annotation_source(arg) for arg in typing.get_args(annotation)
        )
    if origin is typing.Literal:
        values = ", ".join(repr(arg) for arg in typing.get_args(annotation))
        return f"Literal[{values}]"
    if origin is not None:
        name = getattr(origin, "__name__", str(origin))
        args = ", ".join(
            _annotation_source(arg) for arg in typing.get_args(annotation)
        )
        return f"{name}[{args}]"
    return annotation.__name__


def _evaluate_class_annotation(annotation, cls: type):
    if isinstance(annotation, str):
        annotation = annotationlib.ForwardRef(annotation, owner=cls)
    if not isinstance(annotation, annotationlib.ForwardRef):
        return annotation
    annotate = cls.__annotate__
    globals_ = annotate.__globals__ if annotate is not None else {}
    return annotation.evaluate(
        globals=globals_,
        locals={cls.__name__: cls},
        owner=cls,
    )


def _dataclass_default_source(field: dataclasses.Field) -> str | None:
    if field.default is not dataclasses.MISSING:
        return ast.unparse(py_to_ast(field.default))
    if field.default_factory is dataclasses.MISSING:
        return None
    factory_name = getattr(field.default_factory, "__name__", "")
    if not factory_name.isidentifier():
        raise TypeError(
            f"Default factory for dataclass field {field.name!r} must be a "
            "named function or class."
        )
    return {
        "list": "[]",
        "dict": "{}",
        "tuple": "()",
    }.get(factory_name, f"{factory_name}()")


def _dataclass_init_source(
    cls: type, fields: tuple[dataclasses.Field, ...]
) -> str:
    positional = []
    keyword_only = []
    body = ["super().__init__()"] if dataclasses.is_dataclass(cls.__base__) else []
    for field in fields:
        annotation = _annotation_source(field.type)
        default = _dataclass_default_source(field)
        has_factory = field.default_factory is not dataclasses.MISSING
        if field.init:
            parameter = f"{field.name}: {annotation}"
            if has_factory:
                parameter += " = dataclass_missing()"
            elif default is not None:
                parameter += f" = {default}"
            (keyword_only if field.kw_only else positional).append(parameter)
            if has_factory:
                body.extend(
                    (
                        f"if {field.name} is dataclass_missing():",
                        f"    self.{field.name}: {annotation} = {default}",
                        "else:",
                        f"    self.{field.name}: {annotation} = {field.name}",
                    )
                )
            else:
                body.append(f"self.{field.name}: {annotation} = {field.name}")
        elif default is not None:
            body.append(f"self.{field.name}: {annotation} = {default}")
    parameters = ["self", *positional]
    if keyword_only:
        parameters.extend(("*", *keyword_only))
    if "__post_init__" in vars(cls):
        body.append("self.__post_init__()")
    body = body or ["pass"]
    indented_body = "\n".join(f"        {line}" for line in body)
    return f"    def __init__({', '.join(parameters)}):\n{indented_body}\n"


def _dataclass_eq_source(cls: type, fields: tuple[dataclasses.Field, ...]) -> str:
    comparisons = [
        f"self.{field.name} == other.{field.name}"
        for field in fields
        if field.compare
    ]
    equality = " and ".join(comparisons) or "True"
    return (
        "    def __eq__(self, other: object) -> bool:\n"
        f"        if not isinstance(other, {cls.__name__}):\n"
        "            return False\n"
        "        if not same_dataclass_type(self, other):\n"
        "            return False\n"
        f"        return {equality}\n"
    )


def _dataclass_repr_source(cls: type, fields: tuple[dataclasses.Field, ...]) -> str:
    parts = [
        f"{field.name}=\" + repr(self.{field.name}) + \""
        for field in fields
        if field.repr
    ]
    values = ", ".join(parts)
    return (
        "    def __repr__(self) -> str:\n"
        f'        return "{cls.__name__}({values})"\n'
    )


def _is_generated_dataclass_method(cls: type, name: str) -> bool:
    method = vars(cls).get(name)
    method = getattr(method, "__wrapped__", method)
    code = getattr(method, "__code__", None)
    return code is not None and code.co_filename == "<string>"


class CompilationExtension:
    def transform_function(
        self,
        function: callable,
        node: FunctionNode,
        source: str,
    ) -> tuple[FunctionNode, dict[str, object]]:
        return node, {}


IGNORE_NAMES = {
    # module
    "__name__",
    "__doc__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__cached__",
    "__builtins__",
    # class
    "__module__",
    "__dict__",
    "__weakref__",
    "__annotate_func__",
    "__type_params__",
    "__orig_bases__",
    "__parameters__",
    "",
    # pyjs
    "__js_runtime__",
    "__pyjs_django_model__",
    "__pyjs_model__",
} | DECORATIONS


def unwrap_js_annotation(annotation) -> tuple[object, bool] | None:
    is_final = typing.get_origin(annotation) is typing.Final
    if is_final:
        annotation = typing.get_args(annotation)[0]

    if annotation is JS:
        return None, is_final

    origin = typing.get_origin(annotation)
    if origin is JS:
        return typing.get_args(annotation)[0], is_final
    if origin is typing.Annotated:
        value_type, *metadata = typing.get_args(annotation)
        if js in metadata:
            return value_type, is_final
    return None


def union_annotations(annotations):
    values = iter(dict.fromkeys(annotations))
    annotation = next(values)
    for value in values:
        annotation |= value
    return annotation


def infer_js_annotation(value):
    if isinstance(value, (bool, int, float, str, type(None))):
        return type(value)
    if isinstance(value, list):
        if not value:
            raise TypeError(
                "Cannot infer the item type of an empty JS module list; "
                "use JS[list[T]]."
            )
        return list[union_annotations(infer_js_annotation(item) for item in value)]
    if isinstance(value, dict):
        if not value:
            raise TypeError(
                "Cannot infer the key and value types of an empty JS module dict; "
                "use JS[dict[K, V]]."
            )
        key_type = union_annotations(infer_js_annotation(key) for key in value)
        value_type = union_annotations(
            infer_js_annotation(item) for item in value.values()
        )
        return dict[key_type, value_type]
    raise TypeError(f"Cannot infer a JS module type from `{type(value).__name__}`.")


def module_js_annotations(module) -> dict[str, tuple[object, bool]]:
    annotations = annotationlib.get_annotations(
        module,
        format=annotationlib.Format.FORWARDREF,
    )
    return {
        name: js_annotation
        for name, annotation in annotations.items()
        if (js_annotation := unwrap_js_annotation(annotation)) is not None
    }


def resolve_imported(
    obj: object,
    current_module: Module,
    fallback_name: str | None = None,
):
    module_name = obj.__module__
    package = current_module.container
    if module_name not in package:
        package[module_name] = Module(
            inspect.getmodule(obj),
            package,
            extensions=current_module.extensions,
            context=current_module.context,
        ).build()
    imported_module = package[module_name]
    imported_name = getattr(obj, "__name__", None)
    if imported_name is None:
        imported_name = next(
            (
                name
                for name, value in vars(imported_module.py_module).items()
                if value is obj
            ),
            fallback_name,
        )
    if imported_name is None:
        raise NameError(f"Cannot find imported object {obj!r} in {module_name}.")
    return imported_module.search(imported_name)


def traverse_imported(obj_name: str, obj: object, current_module: Module):
    if existing := current_module.scope.names.get(obj_name):
        if existing.py_obj is not obj:
            raise NameError(f"Imported object conflicts with existing `{obj_name}`.")
        return
    imported_object = resolve_imported(obj, current_module, obj_name)
    current_module.scope.add(imported_object, obj_name)
    current_module.imported.setdefault(obj.__module__, []).append(
        (imported_object, obj_name)
    )


def apply_partial_client(func_def, client: partial, module):
    """Replace a function body with a call through its partial client implementation."""
    target = client.func
    target_name = target.__name__
    try:
        target_obj = module.search(target_name)
    except NameError:
        traverse_imported(target_name, target, module)
    else:
        target_implementation = getattr(target, "__js_client__", target)
        if (
            target_obj.py_obj is not target
            and target_obj.py_obj is not target_implementation
        ):
            raise NameError(
                f"Client partial target conflicts with existing `{target_name}`."
            )

    args = [py_to_ast(value) for value in client.args]
    args.extend(
        ast.Name(id=arg.arg, ctx=ast.Load())
        for arg in func_def.args.posonlyargs + func_def.args.args
    )
    if func_def.args.vararg is not None:
        args.append(
            ast.Starred(
                value=ast.Name(id=func_def.args.vararg.arg, ctx=ast.Load()),
                ctx=ast.Load(),
            )
        )

    keywords = [
        ast.keyword(arg=name, value=py_to_ast(value))
        for name, value in (client.keywords or {}).items()
    ]
    keywords.extend(
        ast.keyword(arg=arg.arg, value=ast.Name(id=arg.arg, ctx=ast.Load()))
        for arg in func_def.args.kwonlyargs
    )
    if func_def.args.kwarg is not None:
        keywords.append(
            ast.keyword(
                arg=None,
                value=ast.Name(id=func_def.args.kwarg.arg, ctx=ast.Load()),
            )
        )

    replacement = ast.Return(
        value=ast.Call(
            func=ast.Name(id=target_name, ctx=ast.Load()),
            args=args,
            keywords=keywords,
        )
    )
    if func_def.body:
        ast.copy_location(replacement, func_def.body[0])
    func_def.body = [replacement]


class Scope:
    def __init__(self, parent=None):
        self.parent: Scope = parent
        self.names = {}

    def search(self, name: str) -> Object:
        if value := self.names.get(name):
            return value
        return self.parent.search(name)

    def add(self, thing: Object, name: str = None) -> Object:
        self.names[name or thing.name] = thing
        return thing


class ModuleScope(Scope):
    BUILTINS: Module

    def __init__(self, is_builtins: bool):
        super().__init__()
        self.is_builtins = is_builtins

    def search(self, name):
        if value := self.names.get(name):
            return value
        if not self.is_builtins and (value := self.BUILTINS.scope.search(name)):
            return value
        raise NameError(f"Searching scopes for `{name}` did not yield results.")


class ClassScope(Scope):
    pass


class LocalScope(Scope):
    def lookup(self, name: str) -> Object:
        if value := self.names.get(name):
            return value
        if not isinstance(self.parent, LocalScope):
            raise NameError(f"Searching local scopes for `{name}` did not yield results.")
        return self.parent.lookup(name)


class FunctionScope(LocalScope):
    pass


class Object:
    def __init__(self, name: str, scope: Scope, container: Object = None):
        self.name = name
        self.scope = scope
        self.container = container
        # Shared analyzer objects must not own compilation entry points. Source
        # and server compilation APIs may intentionally retain their result,
        # but discarding that result must make the entire graph collectible.
        self.visited = weakref.WeakSet()

    @property
    def py_obj(self):
        raise NotImplementedError

    @property
    def type(self):
        raise NotImplementedError

    def add(self, other: Object):
        self.scope.add(other)

    def find(self, name):
        """Vertical. Find attributes of this object, following any inheritance rules."""
        raise NotImplementedError

    def search(self, name):
        """Horizontal. Search in scopes, finally checking builtins after all scopes exhausted."""
        return self.scope.search(name)

    def build(
        self,
        namespace,
        container: Object,
        propagate_js=False,
        source_overrides: dict[str, str] | None = None,
        skip_names: set[str] | None = None,
    ):
        source_overrides = source_overrides or {}
        skip_names = skip_names or set()
        for name, py_obj in vars(namespace).items():
            original_py_obj = py_obj
            builtin_name = None
            if isinstance(container, Module) and container.scope.is_builtins:
                if not name.startswith("_") or name.startswith("__"):
                    continue
                builtin_name = name[1:]
            if name in IGNORE_NAMES or name in skip_names:
                continue

            if inspect.isbuiltin(py_obj):
                continue

            py_obj = resolve_library_import(py_obj)
            if isinstance(py_obj, types.ModuleType) and py_obj is not original_py_obj:
                assert isinstance(container, Module)
                container.add(ModuleAlias(name, py_obj, container))
                continue

            type_alias_type = getattr(typing, "TypeAliasType", ())
            if isinstance(py_obj, type_alias_type):
                py_obj = py_obj.__value__
            if (
                isinstance(container, Module)
                and typing.get_origin(py_obj) is not None
                and typing.get_args(py_obj)
            ):
                container.add(TypeAliasValue(name, py_obj, container.scope, container))
                continue

            js_module_binding = (
                container.js_annotations.get(name)
                if isinstance(container, Module)
                else None
            )
            is_typed_dict = typing.is_typeddict(py_obj)
            js_attr = getattr(py_obj, "__js__", None)
            if js_attr is False or (
                js_attr is None
                and not propagate_js
                and not is_typed_dict
                and js_module_binding is None
            ):
                continue

            if isinstance(container, Module) and getattr(
                py_obj, "__module__", None
            ) not in (
                container.name,
                None,
            ):
                traverse_imported(name, py_obj, container)
            elif is_typed_dict:
                TypedDictClass.from_py_cls(py_obj, container)
            elif inspect.isclass(py_obj):
                assert isinstance(container, Module), (
                    "Classes are only allowed in modules."
                )
                if Class.is_generic(py_obj):
                    GenericClass.from_py_cls(
                        py_obj, container, emitted_name=builtin_name
                    )
                else:
                    Class.from_py_cls(
                        py_obj, container, emitted_name=builtin_name
                    ).build()
            elif isinstance(py_obj, property):
                if py_obj.fget is None or (
                    getattr(py_obj.fget, "__js__", None) is False
                ):
                    continue
                getter = Function.from_py_func(
                    py_obj.fget,
                    container,
                    emitted_name=name,
                )
                getter.is_property = True
                if py_obj.fset is not None and (
                    getattr(py_obj.fset, "__js__", None) is not False
                ):
                    setter = Function.from_py_func(
                        py_obj.fset,
                        container,
                        emitted_name=name,
                        register=False,
                    )
                    setter.is_property_setter = True
                    getter.property_setter = setter
                    container.internal_scope.add(setter, f"$setter${name}")
            elif callable(py_obj) or isinstance(py_obj, (classmethod, staticmethod)):
                Function.from_py_func(
                    py_obj,
                    container,
                    emitted_name=builtin_name,
                    source_override=source_overrides.get(name),
                )
            elif js_module_binding is not None:
                if not isinstance(py_obj, JS_MODULE_VALUE_TYPES):
                    raise TypeError(
                        f"JS module binding `{name}` has unsupported value type "
                        f"`{type(py_obj).__name__}`."
                    )
                annotation, is_final = js_module_binding
                if annotation is None:
                    annotation = infer_js_annotation(py_obj)
                while True:
                    try:
                        value_type = resolve_python_annotation(
                            annotation, container.scope
                        )
                        break
                    except DependencyError as dependency:
                        if dependency.class_or_func not in container.type_dependencies:
                            container.type_dependencies.append(dependency.class_or_func)
                container.add(
                    value_type(
                        name,
                        container.scope,
                        container,
                        py_to_ast(py_obj),
                        py_obj,
                        is_const=is_final,
                    )
                )
            elif (
                propagate_js
                and isinstance(container, Class)
                and not name.startswith("__")
                and isinstance(py_obj, (bool, int, float, str))
            ):
                container.add(Instance.from_static_value(name, py_obj, container))
            else:
                if getattr(py_obj, "__js__", False):
                    container.add(Instance.from_static_value(name, py_obj, container))


class TypeAliasValue(Object):
    def __init__(self, name: str, annotation, scope: Scope, container: Object):
        super().__init__(name, scope, container)
        self.annotation = annotation

    @property
    def py_obj(self):
        return self.annotation

    @property
    def type(self):
        return self

    @property
    def node(self):
        return []


class Module(Object):
    scope: ModuleScope

    def __init__(
        self,
        module,
        package,
        is_builtins: bool = False,
        extensions: tuple[CompilationExtension, ...] = (),
        context: CompilationContext | None = None,
    ):
        super().__init__(module.__name__, ModuleScope(is_builtins), package)
        self.py_module = module
        self.imported: dict[str, list[tuple[Object, str]]] = {}
        self.inline_dependencies: dict[Object, str] = {}
        self.runtime_implementations: dict[callable, Function] = {}
        self.extensions = extensions
        self.context = context or CompilationContext()
        self.type_dependencies: list[Class] = []
        filename = getattr(module, "__file__", None)
        if filename is not None:
            self.context.sources.register(
                filename,
                getattr(module, "__pyjs_source__", None),
            )
        self.js_annotations = module_js_annotations(module)

    def register_inline_dependency(self, dependency_obj: Object) -> str:
        if alias := self.inline_dependencies.get(dependency_obj):
            return alias

        base = f"${dependency_obj.name.lstrip('_')}"
        aliases = set(self.inline_dependencies.values())
        alias = base
        suffix = 2
        while alias in aliases:
            alias = f"{base}{suffix}"
            suffix += 1

        self.inline_dependencies[dependency_obj] = alias
        if dependency_obj.container is not self:
            imported = self.imported.setdefault(dependency_obj.container.name, [])
            binding = (dependency_obj, alias)
            if binding not in imported:
                imported.append(binding)
        return alias

    @property
    def py_obj(self):
        return self.py_module

    @property
    def node(self) -> ModuleDef:
        body = []
        # module name comment
        # imports
        for obj in self.scope.names.values():
            if should_include(obj):
                node = obj.node
                if isinstance(node, list):
                    body.extend(node)
                else:
                    body.append(node)
        for obj in self.runtime_implementations.values():
            if should_include(obj):
                body.append(obj.node)
        return ModuleDef(self, body=body, type_ignores=[])

    @property
    def children(self):
        return [
            *self.scope.names.values(),
            *self.runtime_implementations.values(),
        ]

    def value_implementation(self, interface: Function) -> Function:
        py_interface = interface.py_func
        if implementation := self.runtime_implementations.get(py_interface):
            return implementation

        py_implementation = getattr(py_interface, "__js_value__", None)
        source = getattr(py_interface, "__js_value_source__", None)
        if py_implementation is None and source is None:
            raise ValueError(f"{interface.name!r} does not have a value implementation")

        py_func = py_implementation or py_interface
        implementation = Function.from_py_func(
            py_func,
            self,
            emitted_name=interface.name,
            register=False,
        )
        implementation.is_runtime_implementation = True
        implementation.runtime_source = source
        self.runtime_implementations[py_interface] = implementation
        return implementation

    def build(self, *args, **kwargs):
        self.build_imported_js_bindings()
        super().build(self.py_module, self)
        return self

    def build_imported_js_bindings(self):
        source = inspect.getsource(self.py_module)
        for node in ast.parse(source).body:
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            module_name = node.module
            if node.level:
                module_name = importlib.util.resolve_name(
                    f"{'.' * node.level}{module_name}", self.py_module.__package__
                )
            imported_module = sys.modules.get(module_name)
            if imported_module is None:
                continue
            js_annotations = module_js_annotations(imported_module)
            for alias in node.names:
                target = stdlib_import_target(module_name, alias.name)
                if target is not None:
                    replacement_module, replacement_name = target
                    assert replacement_name is not None
                    self.add_imported_js_binding(
                        importlib.import_module(replacement_module),
                        replacement_name,
                        alias.asname or alias.name,
                    )
                elif alias.name not in js_annotations:
                    continue
                else:
                    self.add_imported_js_binding(
                        imported_module,
                        alias.name,
                        alias.asname or alias.name,
                    )

    def add_imported_js_binding(self, module, source_name: str, local_name: str):
        if module.__name__ not in self.container:
            self.container[module.__name__] = Module(
                module,
                self.container,
                extensions=self.extensions,
                context=self.context,
            ).build()
        imported = self.container[module.__name__].search(source_name)
        self.scope.add(imported, local_name)
        self.imported.setdefault(module.__name__, []).append((imported, local_name))


class ModuleAlias(Object):
    def __init__(self, name: str, target: types.ModuleType, container: Module):
        super().__init__(name, container.scope, container)
        package = container.container
        if target.__name__ not in package:
            package[target.__name__] = Module(
                target,
                package,
                extensions=container.extensions,
                context=container.context,
            ).build()
        self.target = package[target.__name__]
        self.member_aliases: dict[Object, str] = {}

    @property
    def py_obj(self):
        return self.target.py_obj

    @property
    def type(self):
        return self

    @property
    def node(self):
        return []

    def find(self, name):
        if member := self.target.scope.names.get(name):
            return member
        raise NameError(f"Can't find {name} in module {self.target.name}.")

    def import_member(self, member: Object) -> str:
        if alias := self.member_aliases.get(member):
            return alias
        alias = f"${self.name}${member.name}"
        self.member_aliases[member] = alias
        self.container.imported.setdefault(self.target.name, []).append(
            (member, alias)
        )
        return alias


class UnionType:
    def __init__(self, name: str = None, types: Iterable[Class] = None):
        self.name = name
        self._types: dict[object, Class] = {}
        for value_type in types or ():
            self.add(value_type)

    def __call__(
        self,
        name,
        scope,
        container,
        ast_value=None,
        value=None,
        is_const=False,
    ):
        new = Instance(
            name,
            self,
            scope,
            container,
            static_value=ast_value,
            py_obj=value,
            is_const=is_const,
        )
        return new

    @property
    def types(self):
        return self._types.values()

    @property
    def first(self):
        return next(iter(self.types))

    @property
    def type(self):
        if len(self._types) == 1:
            return self.first
        return self

    def add(self, cls: Class | UnionType):
        if isinstance(cls, UnionType):
            for member in cls.types:
                self.add(member)
            return
        self._types.setdefault(union_type_key(cls), cls)

    def reassign(self, name, *args, **kwargs):
        return UnionType(name, self.types)

    def to_annotation_str(self, delim="|"):
        return delim.join(t.to_annotation_str() for t in self.types)

    @property
    def annotation(self):
        or_ = None
        for t in self.types:
            if or_ is None:
                or_ = t.annotation
            else:
                or_ = ast.BinOp(left=or_, op=ast.BitOr(), right=t.annotation)
        assert or_, "UnionType is empty"
        return or_


class Class(Object):
    scope: ClassScope

    def __init__(
        self,
        cls: type,
        container: Module,
        assigned_types: dict[str, Class] = None,
        name: str = None,
    ):
        super().__init__(name or cls.__name__, ClassScope(container.scope), container)
        self.generic_types = assigned_types
        self.generic_name = cls.__name__
        if container.scope.is_builtins:
            self.generic_name = self.generic_name.removeprefix("_")
        if assigned_types:
            for type_name, type_cls in assigned_types.items():
                self.scope.add(type_cls, type_name)
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = cls
        self.is_dataclass = dataclasses.is_dataclass(cls)
        self.is_frozen_dataclass = bool(
            self.is_dataclass and cls.__dataclass_params__.frozen
        )
        self._self = Instance("self", self, self.scope, self)
        self.client_defaults: dict[str, ast.expr] = {}
        self.client_required: tuple[str, ...] = ()
        self.client_fields: dict[str, Class | UnionType] = {}
        self.client_model_dependencies: set[Class] = set()
        self.client_model_aliases: dict[Class, str] = {}
        self.subclasses = []
        self.runtime_super_dependency: Class | None = None
        self.runtime_super_alias: str | None = None
        if self.name == "object" and getattr(cls, "__builtin__", False):
            self.super = None
        elif cls.__base__ is Generic:
            self.super = None
        else:
            base_name = cls.__base__.__name__
            if container.scope.is_builtins:
                base_name = base_name.removeprefix("_")
            self.super = self.search(base_name)
            if isinstance(self.super, GenericClass):
                generic_base = next(
                    (
                        base
                        for base in getattr(cls, "__orig_bases__", ())
                        if getattr(base, "__origin__", None) is cls.__base__
                    ),
                    None,
                )
                assert generic_base is not None, (
                    f"Subclass {cls.__name__} must provide type arguments for "
                    f"{cls.__base__.__name__}."
                )
                generic_types = [self.search(arg.__name__) for arg in generic_base.__args__]
                assert all(
                    isinstance(arg, (Class, UnionType)) for arg in generic_types
                )
                try:
                    self.super = self.super(*generic_types)
                except DependencyError as dependency:
                    self.super = dependency.class_or_func
            assert isinstance(self.super, Class)
            if not self.super.container.scope.is_builtins:
                self.super.subclasses.append(self)
        for state_name, state_field in getattr(cls, "__pyjs_state_fields__", {}).items():
            state_type = self.search(state_field.value_type.__name__)
            self._self.add(
                state_type(state_name, self.scope, self._self),
                state_name,
            )

    def __call__(self, name, scope, container, ast_value=None, value=None, is_const=None):
        return self._self.reassign(
            name, scope, container, ast_value=ast_value, value=value, is_const=is_const
        )

    @property
    def init(self) -> Function:
        return self.internal_scope.names.get("__init__", None)

    @property
    def py_obj(self):
        return self.py_cls

    @property
    def type(self):
        return self

    @property
    def node(self) -> ast.ClassDef:
        body = [o.node for o in self.internal_scope.names.values() if should_include(o)]
        if self.runtime_super_dependency is not None:
            base = Name(
                self.super,
                runtime_dependency=self.runtime_super_dependency,
            )
            base.runtime_alias = self.runtime_super_alias
        else:
            base = self.super.annotation if self.super is not None else None
        return ClassDef(
            self,
            bases=[base] if base is not None and self.super.name != "object" else [],
            body=body,
            keywords=[],
            decorator_list=[],
        )

    @property
    def annotation(self):
        if self.generic_types:
            elts = [t.annotation for t in self.generic_types.values()]
            slice = ast.Tuple(elts=elts) if len(elts) > 1 else elts[0]
            return ast.Subscript(value=ast.Name(id=self.generic_name), slice=slice)
        else:
            return ast.Name(id=self.name)

    def to_annotation_str(self, *args, **kwargs):
        return self.name

    @staticmethod
    def is_generic(py_cls):
        return bool(py_cls.__type_params__)

    @property
    def inline_decorator(self):
        return self.find("__init__").inline_decorator

    @classmethod
    def from_py_cls(
        cls,
        py_cls: type,
        container: Module,
        *,
        emitted_name: str | None = None,
    ):
        if len(py_cls.__bases__) > 1:
            container.context.definition_error(
                py_cls,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Multiple inheritance is not supported for {py_cls.__name__!r}",
                help="Use one base class and compose the remaining behavior.",
            )
        if emitted_name is None:
            cls_ = cls(py_cls, container)
        else:
            cls_ = cls(py_cls, container, name=emitted_name)
        container.scope.add(cls_)
        return cls_

    def build(self, *args, **kwargs):
        annotations = dict(
            getattr(self.py_cls, "__pyjs_instance_annotations__", {})
        )
        source_overrides = {}
        skip_names = set()
        if dataclasses.is_dataclass(self.py_cls):
            fields = tuple(dataclasses.fields(self.py_cls))
            for field in fields:
                annotations.setdefault(
                    field.name,
                    _evaluate_class_annotation(field.type, self.py_cls),
                )
            params = self.py_cls.__dataclass_params__
            if params.init and _is_generated_dataclass_method(
                self.py_cls, "__init__"
            ):
                source_overrides["__init__"] = _dataclass_init_source(
                    self.py_cls, fields
                )
            if params.eq and _is_generated_dataclass_method(self.py_cls, "__eq__"):
                source_overrides["__eq__"] = _dataclass_eq_source(
                    self.py_cls, fields
                )
            if params.repr and _is_generated_dataclass_method(
                self.py_cls, "__repr__"
            ):
                source_overrides["__repr__"] = _dataclass_repr_source(
                    self.py_cls, fields
                )
            skip_names.add("__replace__")
            if _is_generated_dataclass_method(self.py_cls, "__hash__"):
                skip_names.add("__hash__")
            if params.frozen:
                for method_name in ("__setattr__", "__delattr__"):
                    if _is_generated_dataclass_method(self.py_cls, method_name):
                        skip_names.add(method_name)
        super().build(
            self.py_cls,
            self,
            propagate_js=True,
            source_overrides=source_overrides,
            skip_names=skip_names,
        )
        info = library_class_info(self.py_cls)
        if info is not None:
            annotations.update(info.annotations)
        for name, annotation in annotations.items():
            ensure_annotation_dependencies(annotation, self.container)
            while True:
                try:
                    value_type = resolve_python_annotation(annotation, self.scope)
                    break
                except DependencyError as dependency:
                    if dependency.class_or_func not in self.container.type_dependencies:
                        self.container.type_dependencies.append(dependency.class_or_func)
                except UnsupportedLiteralError as error:
                    self.container.context.definition_error(
                        self.py_cls,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        str(error),
                        help=(
                            "Use one or more string values, such as "
                            "Literal['open', 'closed']."
                        ),
                    )
            if (
                info is not None
                and name in info.annotations
                and not is_supported_client_field_type(value_type)
            ):
                raise TypeError(
                    f"{self.py_cls.__name__}.{name} uses unsupported client "
                    f"field type {value_type.to_annotation_str()}."
                )
            value = value_type(name, self.scope, self._self)
            if info is not None and name in info.annotations:
                self.client_fields[name] = value_type
                self.client_model_dependencies.update(
                    client_model_types(value_type)
                )
            dependency = getattr(
                self.py_cls,
                "__js_member_dependencies__",
                {},
            ).get(name)
            if dependency is not None:
                value.member_dependency = value_type
            self._self.add(value, name)
        if info is not None:
            self.client_defaults = {
                name: py_to_ast(value) for name, value in info.defaults.items()
            }
            self.client_required = info.required

    @property
    def children(self):
        return self.internal_scope.names.values()

    def add(self, other: Object):
        self.internal_scope.add(other)

    def find(self, name):
        if value := self.find_attrs(name):
            return value
        raise NameError(f"Can't find {name} on {self.name} class.")

    def find_attrs(self, name, search_bases=True):
        if value := self.internal_scope.names.get(name):
            return value
        if search_bases:
            return self.find_bases(name)

    def find_bases(self, name):
        if self.super is not None:
            return self.super.find_attrs(name)


class CallableClass(Class):
    def __init__(
        self,
        parameter_types: tuple[Class | UnionType, ...] | None,
        return_type: Class | UnionType,
        base: Class,
    ):
        Object.__init__(self, "callable", ClassScope(base.scope), base.container)
        self.parameter_types = parameter_types
        self.return_type = return_type
        self.generic_types = None
        self.generic_name = "Callable"
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = base.py_cls
        self._self = Instance("self", self, self.scope, self)
        self.super = base
        self.subclasses = []
        self.runtime_super_dependency = None
        self.runtime_super_alias = None

    @property
    def annotation(self):
        parameters: ast.expr
        if self.parameter_types is None:
            parameters = ast.Constant(value=Ellipsis)
        else:
            parameters = ast.List(
                elts=[value.annotation for value in self.parameter_types],
                ctx=ast.Load(),
            )
        return ast.Subscript(
            value=ast.Name(id="Callable"),
            slice=ast.Tuple(
                elts=[parameters, self.return_type.annotation],
                ctx=ast.Load(),
            ),
            ctx=ast.Load(),
        )

    def to_annotation_str(self, *args, **kwargs):
        parameters = "..."
        if self.parameter_types is not None:
            parameters = ", ".join(
                value.to_annotation_str() for value in self.parameter_types
            )
            parameters = f"[{parameters}]"
        return f"Callable[{parameters}, {self.return_type.to_annotation_str()}]"


class TypeVariableClass(Class):
    def __init__(self, parameter: typing.TypeVar, base: Class):
        Object.__init__(self, parameter.__name__, ClassScope(base.scope), base.container)
        self.parameter = parameter
        self.generic_types = None
        self.generic_name = parameter.__name__
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = object
        self._self = Instance("self", self, self.scope, self)
        self.super = base
        self.subclasses = []
        self.runtime_super_dependency = None
        self.runtime_super_alias = None
        self.bound: Class | UnionType | None = None

    @property
    def annotation(self):
        return ast.Name(id=self.name)

    def to_annotation_str(self, *args, **kwargs):
        return self.name


class UnsupportedLiteralError(TypeError):
    pass


class LiteralClass(Class):
    def __init__(self, values: tuple[str, ...], base: Class):
        Object.__init__(self, "str", ClassScope(base.scope), base.container)
        self.values = values
        self.generic_types = None
        self.generic_name = "Literal"
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = base.py_cls
        self._self = Instance("self", self, self.scope, self)
        self.super = base
        self.subclasses = []
        self.runtime_super_dependency = None
        self.runtime_super_alias = None

    @property
    def annotation(self):
        values = [ast.Constant(value=value) for value in self.values]
        return ast.Subscript(
            value=ast.Name(id="Literal"),
            slice=ast.Tuple(elts=values) if len(values) > 1 else values[0],
        )

    def to_annotation_str(self, *args, **kwargs):
        values = ", ".join(repr(value) for value in self.values)
        return f"Literal[{values}]"


_LITERAL_TYPES = weakref.WeakValueDictionary()


def literal_type(values, scope: Scope) -> LiteralClass:
    values = tuple(values)
    if not values or any(not isinstance(value, str) for value in values):
        raise UnsupportedLiteralError(
            "Literal annotations currently support one or more string values."
        )
    values = tuple(dict.fromkeys(values))
    base = scope.search("str")
    assert isinstance(base, Class)
    key = (id(base), values)
    value_type = _LITERAL_TYPES.get(key)
    if value_type is None:
        value_type = LiteralClass(values, base)
        _LITERAL_TYPES[key] = value_type
    return value_type


def union_type_key(value_type: Class | UnionType):
    if isinstance(value_type, UnionType):
        return "Union", frozenset(union_type_key(member) for member in value_type.types)
    if isinstance(value_type, LiteralClass):
        return "Literal", value_type.values
    if isinstance(value_type, CallableClass):
        return (
            "Callable",
            None
            if value_type.parameter_types is None
            else tuple(union_type_key(value) for value in value_type.parameter_types),
            union_type_key(value_type.return_type),
        )
    if isinstance(value_type, TypeVariableClass):
        return "TypeVar", id(value_type)
    return value_type.name


def specialization_cache_key(value_type: Class | UnionType):
    if isinstance(value_type, UnionType):
        return (
            "Union",
            frozenset(
                specialization_cache_key(member) for member in value_type.types
            ),
        )
    if isinstance(value_type, CallableClass):
        return (
            "Callable",
            None
            if value_type.parameter_types is None
            else tuple(
                specialization_cache_key(parameter)
                for parameter in value_type.parameter_types
            ),
            specialization_cache_key(value_type.return_type),
        )
    return id(value_type)


def specialization_type_name(value_type: Class | UnionType) -> str:
    if isinstance(value_type, LiteralClass):
        values = "_".join(
            value.encode().hex() or "empty" for value in value_type.values
        )
        return f"Literal__{values}"
    if isinstance(value_type, CallableClass):
        parameters = "any"
        if value_type.parameter_types is not None:
            parameters = "_".join(
                specialization_type_name(parameter)
                for parameter in value_type.parameter_types
            ) or "none"
        result = specialization_type_name(value_type.return_type)
        return f"Callable__{parameters}__{result}"
    if isinstance(value_type, TypeVariableClass):
        return value_type.name
    return value_type.to_annotation_str("U")


def ensure_annotation_dependencies(annotation, module: Module):
    origin = typing.get_origin(annotation)
    if origin is not None:
        if origin is Callable:
            parameters, return_annotation = typing.get_args(annotation)
            if parameters is not Ellipsis:
                for parameter in parameters:
                    ensure_annotation_dependencies(parameter, module)
            ensure_annotation_dependencies(return_annotation, module)
            return
        if origin not in (types.UnionType, typing.Union):
            ensure_annotation_dependencies(origin, module)
        for value in typing.get_args(annotation):
            ensure_annotation_dependencies(value, module)
        return
    if not isinstance(annotation, type):
        return
    try:
        module.scope.search(annotation.__name__)
    except NameError:
        traverse_imported(annotation.__name__, annotation, module)


def resolve_python_annotation(annotation, scope: Scope):
    if isinstance(annotation, str):
        resolved = scope.search(annotation)
        if isinstance(resolved, TypeAliasValue):
            return resolve_python_annotation(resolved.annotation, resolved.scope)
        return resolved
    if isinstance(annotation, annotationlib.ForwardRef):
        return resolve_python_annotation(annotation.__forward_arg__, scope)
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return literal_type(typing.get_args(annotation), scope)
    if origin is not None and getattr(origin, "__name__", "") in {
        "NotRequired",
        "ReadOnly",
        "Required",
    }:
        return resolve_python_annotation(typing.get_args(annotation)[0], scope)
    if origin in (types.UnionType, typing.Union):
        return UnionType(
            types=[
                resolve_python_annotation(value, scope)
                for value in typing.get_args(annotation)
            ]
        ).type
    if origin is Callable:
        parameters, return_annotation = typing.get_args(annotation)
        parameter_types = None
        if parameters is not Ellipsis:
            parameter_types = tuple(
                resolve_python_annotation(value, scope) for value in parameters
            )
        base = scope.search("callable")
        assert isinstance(base, Class)
        return CallableClass(
            parameter_types,
            resolve_python_annotation(return_annotation, scope),
            base,
        )
    if origin is not None:
        generic = scope.search(origin.__name__)
        assert isinstance(generic, GenericClass)
        args = typing.get_args(annotation)
        if origin is tuple and args[-1:] == (Ellipsis,):
            args = args[:-1]
        return generic(
            *[
                resolve_python_annotation(value, scope)
                for value in args
            ]
        )
    resolved = scope.search(annotation.__name__)
    if isinstance(resolved, TypeAliasValue):
        return resolve_python_annotation(resolved.annotation, resolved.scope)
    return resolved


class TypedDictClass(Class):
    def __init__(self, cls: type, container: Module):
        Object.__init__(self, cls.__name__, ClassScope(container.scope), container)
        self.generic_types = None
        self.generic_name = cls.__name__
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = cls
        self._self = Instance("self", self, self.scope, self)
        self.subclasses = []
        self.super = self.search("typed_dict")
        assert isinstance(self.super, Class)
        self.annotations = typing.get_type_hints(cls, include_extras=True)
        self.required_keys = cls.__required_keys__
        self._field_types = {}

    @property
    def node(self):
        return []

    @property
    def children(self):
        return ()

    def build(self, *args, **kwargs):
        return self

    def field_type(self, key: str):
        try:
            annotation = self.annotations[key]
        except KeyError:
            raise TypeError(f"{self.name} has no key {key!r}.") from None
        if key not in self._field_types:
            self._field_types[key] = resolve_python_annotation(annotation, self.scope)
        return self._field_types[key]


def same_analyzer_type(left, right) -> bool:
    if isinstance(left, UnionType) and isinstance(right, UnionType):
        left_types = list(left.types)
        right_types = list(right.types)
        return len(left_types) == len(right_types) and all(
            any(
                same_analyzer_type(left_type, right_type)
                for right_type in right_types
            )
            for left_type in left_types
        )
    if isinstance(left, Class) and isinstance(right, Class):
        if isinstance(left, CallableClass) or isinstance(right, CallableClass):
            return (
                isinstance(left, CallableClass)
                and isinstance(right, CallableClass)
                and union_type_key(left) == union_type_key(right)
            )
        if isinstance(left, LiteralClass) or isinstance(right, LiteralClass):
            return (
                isinstance(left, LiteralClass)
                and isinstance(right, LiteralClass)
                and left.values == right.values
            )
        if left is right:
            return True
        if left.generic_name != right.generic_name:
            return False
        if left.generic_types is None or right.generic_types is None:
            return False
        if left.generic_types.keys() != right.generic_types.keys():
            return False
        return all(
            same_analyzer_type(left.generic_types[name], right.generic_types[name])
            for name in left.generic_types
        )
    return left is right


def is_client_model_type(value_type: Class) -> bool:
    current = value_type
    while current is not None:
        if (
            current.name == "BaseModel"
            and current.py_cls.__module__ == "pyjs.lib.pydantic.v2"
        ):
            return True
        current = current.super
    return False


def client_model_types(value_type: Class | UnionType) -> set[Class]:
    if isinstance(value_type, UnionType):
        dependencies = set()
        for member in value_type.types:
            dependencies.update(client_model_types(member))
        return dependencies
    if is_client_model_type(value_type):
        return {value_type}
    dependencies = set()
    for member in (value_type.generic_types or {}).values():
        dependencies.update(client_model_types(member))
    return dependencies


def is_supported_client_field_type(value_type: Class | UnionType) -> bool:
    if isinstance(value_type, UnionType):
        return all(
            is_supported_client_field_type(member)
            for member in value_type.types
        )
    if is_client_model_type(value_type):
        return True
    if isinstance(value_type, LiteralClass):
        return True
    type_name = value_type.generic_name or value_type.name
    if type_name in {
        "Date",
        "NoneType",
        "bool",
        "float",
        "int",
        "object",
        "str",
    }:
        return True
    if type_name not in {"dict", "list", "set", "tuple"}:
        return False
    return all(
        is_supported_client_field_type(member)
        for member in value_type.generic_types.values()
    )


class GenericClass(Object):
    def __init__(
        self,
        cls: type,
        container: Module,
        name: str | None = None,
    ):
        super().__init__(name or cls.__name__, ClassScope(container.scope), container)
        self.py_cls = cls
        self.init_params = None
        if cls_init := getattr(cls, "__init__", None):
            self.init_params = inspect.signature(cls_init).parameters
        self.generic_params = [type_param.__name__ for type_param in cls.__type_params__]
        # Built-in generic classes outlive individual compilations. Concrete
        # specializations are also referenced by the compilation that uses
        # them, so this cache must not keep discarded package graphs alive.
        self.concrete_classes = weakref.WeakValueDictionary()

    @property
    def node(self):
        return [
            concrete.node
            for concrete in self.concrete_classes.values()
            if should_include(concrete)
        ]

    @property
    def py_obj(self):
        return self.py_cls

    @classmethod
    def from_py_cls(
        cls,
        py_cls: type,
        container: Module,
        *,
        emitted_name: str | None = None,
    ):
        cls_ = cls(py_cls, container, name=emitted_name)
        container.scope.add(cls_)
        return cls_

    def build(self, *args, **kwargs):
        raise TypeError("A GenericClass cannot be built.")

    def __call__(self, *args: list[UnionType]) -> Class:
        params = self.generic_params
        if self.name == "tuple":
            params = [f"T{i + 1}" for i in range(len(args))]
        assert len(args) == len(params)
        concrete_name = (
            f"{self.name}__{'_'.join(specialization_type_name(arg) for arg in args)}"
        )

        generics = {}
        for name, arg in zip(params, args, strict=True):
            if isinstance(arg, UnionType):
                generics[name] = UnionType(name, arg.types)
            else:
                assert isinstance(arg, Class)
                generics[name] = arg

        cache_key = tuple(specialization_cache_key(arg) for arg in args)
        concrete_class = self.concrete_classes.get(cache_key)
        if concrete_class is not None:
            return concrete_class

        concrete_class = Class(
            self.py_cls, self.container, assigned_types=generics, name=concrete_name
        )
        self.concrete_classes[cache_key] = concrete_class
        concrete_class.build()
        raise DependencyError(concrete_class)

    def from_call(self, arg_types):
        # TODO: handle different arg schemes other than positional
        assert self.init_params
        if self.name == "dict":
            if len(arg_types) != 1:
                raise TypeError(
                    "Concrete dict type could not be determined; "
                    "use dict[K, V]() for an empty dict."
                )
            source_type = arg_types[0]
            if isinstance(source_type, Instance):
                source_type = source_type.cls
            assert isinstance(source_type, Class)
            if isinstance(source_type, TypedDictClass):
                key_type = self.search("str")
                value_types = UnionType()
                for field_name in source_type.annotations:
                    value_types.add(source_type.field_type(field_name))
                value_type = (
                    value_types.type if value_types.types else self.search("object")
                )
                return self(key_type, value_type)
            if source_type.generic_name == "dict":
                return self(
                    source_type.generic_types["K"],
                    source_type.generic_types["V"],
                )
            item_type = next(iter((source_type.generic_types or {}).values()), None)
            if item_type is not None and item_type.generic_name == "tuple":
                pair_types = list(item_type.generic_types.values())
                if len(pair_types) == 2:
                    return self(*pair_types)
            raise TypeError(f"Cannot infer dict item types from {source_type.name}.")
        if self.name in {"list", "set", "tuple"}:
            if len(arg_types) != 1:
                hint = (
                    f"use {self.name}[T]() for an empty {self.name}."
                    if self.name != "tuple"
                    else "use an explicit tuple annotation for an empty tuple."
                )
                raise TypeError(
                    f"Concrete {self.name} type could not be determined; "
                    + hint
                )
            iterable_type = arg_types[0]
            if isinstance(iterable_type, Instance):
                iterable_type = iterable_type.cls
            assert isinstance(iterable_type, Class)
            if iterable_type.name == "str":
                item_type = iterable_type
            elif isinstance(iterable_type, TypedDictClass):
                item_type = self.search("str")
            elif iterable_type.generic_name == "dict":
                item_type = iterable_type.generic_types["K"]
            elif iterable_type.generic_name == "tuple":
                item_type = UnionType()
                for value_type in iterable_type.generic_types.values():
                    item_type.add(value_type)
                item_type = item_type.type
            elif len(iterable_type.generic_types) == 1:
                item_type = next(iter(iterable_type.generic_types.values()))
            else:
                raise TypeError(
                    f"Cannot infer {self.name} item type from {iterable_type.name}."
                )
            return self(item_type)
        param_args = {}
        for arg, param in zip(
            arg_types, list(self.init_params.values())[1:], strict=False
        ):
            param_args[param.annotation.__name__] = arg
        generic_args = [param_args.get(p, None) for p in self.generic_params]
        if not all(generic_args):
            raise TypeError(
                "Concrete type could not be determined from type annotation or value."
            )
        return self(*generic_args)


class Function(Object):
    scope: FunctionScope

    def __init__(self, func: callable, container: Object):
        super().__init__(func.__name__, FunctionScope(container.scope), container)
        self.py_func = func
        self.cls = container if isinstance(container, Class) else None
        if self.cls is not None:
            self.scope.add(self.cls.super, "super")
        object_type = self.scope.search("object")
        assert isinstance(object_type, Class)
        type_parameter_owner = getattr(func, "__func__", func)
        self.type_parameters = {
            parameter.__name__: TypeVariableClass(parameter, object_type)
            for parameter in getattr(type_parameter_owner, "__type_params__", ())
        }
        for parameter in self.type_parameters.values():
            self.scope.add(parameter)
        self.return_type = None
        self.declared_return_type = None
        self.inferred_return_type = None
        self.signature_analyzed = False
        self.returns_self = False

        self.is_analyzed = False
        self.params = []
        self.defaults = []
        self.vararg = None
        self.kwonlyargs = []
        self.kw_defaults = []
        self.kwarg = None
        self.body = []
        self.lineno: int = None
        self.original_node: FunctionNode | None = None
        self.source_fragment: SourceFragment | None = None
        self.is_async = False
        self.is_generator = False
        self.yield_type: Class | UnionType | None = None
        self.is_partial_client = False
        self.virtual_visited = weakref.WeakSet()
        self.compilation_entry_points: tuple[Function, ...] = ()
        self.compilation_objects: set[Object] = set()
        self.runtime_dunder_dependencies: set[str] = set()
        self.is_runtime_implementation = False
        self.runtime_source: str | None = None
        self.is_property = False
        self.is_property_setter = False
        self.property_setter: Function | None = None
        self.overloads: tuple[Function, ...] = ()

    def reset(self):
        self.is_analyzed = False
        self.signature_analyzed = False
        self.scope.names = {}
        if self.cls is not None:
            self.scope.add(self.cls.super, "super")
        for parameter in self.type_parameters.values():
            self.scope.add(parameter)
        self.params = []
        self.defaults = []
        self.vararg = None
        self.kwonlyargs = []
        self.kw_defaults = []
        self.kwarg = None
        self.body = []
        self.return_type = None
        self.declared_return_type = None
        self.inferred_return_type = None
        self.yield_type = None
        self.returns_self = False

    @property
    def py_obj(self):
        return self.py_func

    def decoration(self, name: str):
        py_func = getattr(self.py_func, "__func__", self.py_func)
        return getattr(py_func, name, None)

    @property
    def analysis(self):
        return self.decoration("__js_analysis__")

    @property
    def runtime_dunders(self):
        return self.decoration("__js_runtime_dunders__")

    @property
    def type(self):
        return self.return_type

    @classmethod
    def from_py_func(
        cls,
        py_func: callable,
        container: Module | Class,
        *,
        emitted_name: str | None = None,
        register: bool = True,
        source_override: str | None = None,
        load_overloads: bool = True,
    ):
        client_implementation = getattr(py_func, "__js_client__", None)
        client_partial = (
            client_implementation if isinstance(client_implementation, partial) else None
        )
        source_func = (
            py_func if client_partial is not None else client_implementation or py_func
        )
        if source_override is None:
            lines, lineno = inspect.getsourcelines(source_func)
            source = "".join(lines)
        else:
            source = source_override
            owner = container.py_cls if isinstance(container, Class) else source_func
            _, lineno = inspect.getsourcelines(owner)
        is_method = isinstance(container, Class)

        if is_method:
            # to preserve indentation for sourcemap and still make the function parseable
            source = f"class {container.name}:\n{source}"
            lineno -= 1  # we need to subtract the dummy line from total line offset

        module = ast.parse(source)
        assert isinstance(module, ast.Module)

        if is_method:
            module = module.body[0]
            assert isinstance(module, ast.ClassDef)

        func_def = module.body[0]
        assert isinstance(func_def, (ast.FunctionDef, ast.AsyncFunctionDef))

        module_obj = container if isinstance(container, Module) else container.container
        if client_partial is not None:
            apply_partial_client(func_def, client_partial, module_obj)
        for extension in module_obj.extensions:
            func_def, imports = extension.transform_function(
                source_func, func_def, source
            )
            for import_name, imported in imports.items():
                traverse_imported(import_name, imported, module_obj)
        ast.fix_missing_locations(func_def)

        func = cls(py_func if client_partial is not None else source_func, container)
        func.name = emitted_name or py_func.__name__
        func.is_partial_client = client_partial is not None
        func.lineno = lineno
        func.original_node = func_def
        simple_wrapper = (
            source_func is getattr(module_obj.py_module, "main", None)
            and getattr(module_obj.py_module, "__pyjs_simple_wrapper__", False)
        )
        fragment_owner = (
            container.py_cls
            if source_override is not None and isinstance(container, Class)
            else source_func
        )
        func.source_fragment = SourceFragment(
            module_obj.context.sources.fragment_for(fragment_owner).source,
            lineno - 2 if simple_wrapper else lineno - 1,
            -4 if simple_wrapper else 0,
        )
        func.is_async = isinstance(func_def, ast.AsyncFunctionDef)
        func.is_generator = _contains_yield(func_def)
        if load_overloads:
            overloads = []
            for overloaded in typing.get_overloads(source_func):
                overload = cls.from_py_func(
                    overloaded,
                    container,
                    register=False,
                    load_overloads=False,
                )
                overload.name = func.name
                overloads.append(overload)
            func.overloads = tuple(overloads)

        if register:
            container.add(func)
        return func

    @property
    def node(self) -> FunctionNode:
        assert self.is_analyzed, (
            "Attempting to create function AST but haven't analyzed yet."
        )
        node_type = AsyncFunctionDef if self.is_async else FunctionDef
        return node_type(
            self,
            args=ast.arguments(
                args=self.params,
                vararg=self.vararg,
                kwarg=self.kwarg,
                posonlyargs=[],
                kwonlyargs=self.kwonlyargs,
                defaults=self.defaults,
                kw_defaults=self.kw_defaults,
            ),
            body=self.body,
            returns=None if self.return_type is None else self.return_type.annotation,
            type_params=[],
            decorator_list=(
                [ast.Name(id="property")]
                if self.is_property
                else [
                    ast.Attribute(
                        value=ast.Name(id=self.name, ctx=ast.Load()),
                        attr="setter",
                        ctx=ast.Load(),
                    )
                ]
                if self.is_property_setter
                else []
            ),
            lineno=self.lineno,
            col_offset=self.original_node.col_offset,
        )

    def lookup(self, name):
        """Find a name restricted to the current scope."""
        return self.scope.lookup(name)

    @property
    def is_method(self):
        return self.cls is not None

    @property
    def is_static(self):
        return self.is_classmethod or self.is_staticmethod

    @property
    def is_classmethod(self):
        return isinstance(self.py_func, classmethod)

    @property
    def is_staticmethod(self):
        return isinstance(self.py_func, staticmethod)

    @property
    def inline_decorator(self):
        if self.is_runtime_implementation:
            return None
        if has_inline_decorator(self.py_func):
            return self

    @property
    def inline_call(self):
        return self.decoration("__js_inline_call__")

    @property
    def has_source_decorator(self):
        return self.runtime_source is not None or getattr(
            self.py_func,
            "__js_source__",
            False,
        )

    @property
    def has_keep_decorator(self):
        return has_keep_decorator(self.py_func)

    def get_predefined_source(self):
        if self.runtime_source is not None:
            return self.runtime_source
        source = self.py_func.__js_source__
        return source() if callable(source) else source

    def rewrite_call(
        self,
        arg_strs: list[str],
        arg_types: list[Class | UnionType],
        self_=None,
        *,
        keyword_strs: dict[str, str] | None = None,
        inline_dependencies: dict[str, str] | None = None,
    ):
        rewrite = self.decoration("__js_inline__")
        assert rewrite is not None, "Forwarded inline calls must be lowered by analysis."
        args_joined = ", ".join(arg_strs)
        args = {
            "_arg_strs": list(arg_strs),
            "_arg_types": list(arg_types),
            "_keyword_strs": keyword_strs or {},
            "_args_joined": args_joined,
            "_args_suffix": f", {args_joined}" if args_joined else "",
        }
        if params := self.params:
            if self.is_method and self.params[0].arg == "self":
                params = params[1:]
            if self.is_static and self.params[0].arg == "cls":
                params = params[1:]
            for arg_str, param in zip(arg_strs, params, strict=False):
                args[param.arg] = arg_str
        args.update(keyword_strs or {})
        args.update(inline_dependencies or {})
        if self.is_method:
            args["self"] = self_
        return rewrite(**args)

    def add_cls(self):
        assert self.is_method
        self.scope.add(self.cls, "cls")
        return self.cls

    def add_self(self):
        assert self.is_method
        return self.scope.add(self.cls._self)


class DependencyError(Exception):
    def __init__(self, class_or_func: Class | Function):
        self.class_or_func = class_or_func


class Instance(Object):
    def __init__(
        self,
        name: str,
        cls: Class,
        scope: Scope,
        container: Object,
        static_value: ast.expr = None,
        py_obj=None,
        is_const=False,
    ):
        super().__init__(name, scope, container)
        self.cls = cls
        self.attrs = {}
        assert static_value is None or isinstance(static_value, ast.expr)
        self.static_value: ast.expr = static_value
        self.py_value = py_obj
        self.is_const = is_const
        self.member_dependency: Class | None = None

    def find(self, name):
        if value := self.find_attrs(name):
            return value
        return self.cls.find(name)

    def find_attrs(self, name):
        if value := self.attrs.get(name):
            return value
        return self.find_super_instances(name)

    def find_super_instances(self, name):
        if self.cls.super is not None:
            return self.cls.super._self.find_attrs(name)

    def reassign(
        self,
        name: str,
        scope: Scope,
        container: Object,
        ast_value=None,
        value=None,
        is_const=None,
    ):
        new = Instance(
            name,
            self.cls,
            scope,
            container,
            static_value=ast_value,
            py_obj=value,
            is_const=is_const,
        )
        new.attrs = self.attrs
        return new

    def add(self, obj: Object, name: str = None):
        self.attrs[name or obj.name] = obj

    @property
    def py_obj(self):
        return self.py_value

    @property
    def type(self):
        return self.cls

    @property
    def node(self) -> ast.AnnAssign:
        assert self.static_value is not None
        if isinstance(self.container, Module):
            declaration = "__const__" if self.is_const else "__module__"
        else:
            declaration = "__static__"
        assign = ast.AnnAssign(
            target=Name(self),
            annotation=ast.Name(id=declaration),
            value=self.static_value,
            simple=True,
        )
        assign.obj = self
        return assign

    @classmethod
    def from_static_value(cls, name, value, container, is_const=None):
        value_type_name = type(value).__name__
        value_type = container.search(value_type_name)
        assert isinstance(value_type, Class), "Can't determine type."
        value_ast = None
        if not getattr(value, "__builtin__", False):
            try:
                value_ast = py_to_ast(value)
            except TypeError:
                args = []
                for arg in getattr(value, "__static_args__", []):
                    args.append(py_to_ast(arg))
                value_ast = Call(
                    value_type, func=Name(value_type), args=args, keywords=[]
                )
        return value_type(
            name,
            container.scope,
            container,
            value_ast,
            value,
            is_const=isinstance(container, Module) if is_const is None else is_const,
        )


class ModuleDef(ast.Module):
    def __init__(self, obj: Module, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Module)
        super().__init__(**kwargs)


class ClassDef(ast.ClassDef):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs, name=obj.name)


class FunctionDef(ast.FunctionDef):
    def __init__(self, obj: Function, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Function)
        super().__init__(**kwargs, name=obj.name)


class AsyncFunctionDef(ast.AsyncFunctionDef):
    def __init__(self, obj: Function, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Function)
        super().__init__(**kwargs, name=obj.name)


class Call(ast.Call):
    def __init__(
        self,
        obj: Class | Function | UnionType,
        value_obj: Object | UnionType = None,
        operator: ast.operator | ast.cmpop | None = None,
        reverse: bool = False,
        inline_dependencies: dict[str, str] | None = None,
        dependency_objects: dict[str, Function] | None = None,
        runtime_methods: tuple[Function, ...] = (),
        **kwargs,
    ):
        self.obj = obj
        assert isinstance(self.obj, (Class, Function, UnionType, type(None))), (
            f"{self.obj} is not a Class, Function, or UnionType"
        )
        self.value_obj = value_obj if value_obj is not None else obj
        assert isinstance(self.value_obj, (Object, UnionType, type(None))), (
            f"{self.value_obj} is not an Object or UnionType"
        )
        self.operator = operator
        self.reverse = reverse
        self.inline_dependencies = inline_dependencies or {}
        self.dependency_objects = dependency_objects or {}
        self.runtime_methods = runtime_methods
        super().__init__(**kwargs)


class UnpackItem(ast.expr):
    _fields = ()

    def __init__(self, obj: Object, index: int, **kwargs):
        self.obj = obj
        self.index = index
        super().__init__(**kwargs)


class UnpackAssignment(ast.stmt):
    _fields = ("value", "assignments")

    def __init__(self, value: ast.expr, assignments: list[ast.stmt], **kwargs):
        self.value = value
        self.assignments = assignments
        super().__init__(**kwargs)


class Name(ast.Name):
    def __init__(
        self,
        obj: Object,
        runtime_dependency: Function | Class | None = None,
        **kwargs,
    ):
        self.obj = obj
        self.runtime_dependency = runtime_dependency
        assert isinstance(self.obj, (Object, UnionType)), f"{self.obj} is not an Object"
        super().__init__(**{"id": obj.name, **kwargs})


class RuntimeFunctionReference(ast.expr):
    _fields = ("receiver",)

    def __init__(
        self,
        obj: Function,
        runtime_dependency: Function,
        receiver: ast.expr | None,
        **kwargs,
    ):
        self.obj = obj
        self.runtime_dependency = runtime_dependency
        self.receiver = receiver
        self.alias = runtime_dependency.name
        super().__init__(**kwargs)


class BoundGetattr(ast.expr):
    _fields = ("receiver", "default")

    def __init__(
        self,
        obj: Function,
        receiver: ast.expr,
        default: ast.expr,
        **kwargs,
    ):
        self.obj = obj
        self.receiver = receiver
        self.default = default
        super().__init__(**kwargs)


class StaticCast(ast.expr):
    _fields = ("value",)

    def __init__(self, obj: Object | UnionType, value: ast.expr, **kwargs):
        self.obj = obj
        self.value = value
        super().__init__(**kwargs)


class Attribute(ast.Attribute):
    def __init__(
        self,
        obj: Object,
        union_fields: tuple[Instance, ...] = (),
        union_functions: tuple[Function, ...] = (),
        union_return_type: Class | UnionType | None = None,
        property_setters: tuple[Function, ...] = (),
        property_setter_types: tuple[Class | UnionType, ...] = (),
        module_import_alias: str | None = None,
        **kwargs,
    ):
        self.obj = obj
        assert isinstance(self.obj, (Object, UnionType)), f"{self.obj} is not an Object"
        self.union_fields = union_fields
        self.union_functions = union_functions
        self.union_return_type = union_return_type
        self.property_setters = property_setters
        self.property_setter_types = property_setter_types
        self.module_import_alias = module_import_alias
        super().__init__(**kwargs)


class Tuple(ast.Tuple):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (GenericClass, Class))
        super().__init__(**kwargs)


class List(ast.List):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (GenericClass, Class))
        super().__init__(**kwargs)


class Dict(ast.Dict):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (GenericClass, Class))
        super().__init__(**kwargs)


class Set(ast.Set):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (GenericClass, Class))
        super().__init__(**kwargs)


class Constant(ast.Constant):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class BinOp(ast.BinOp):
    def __init__(self, obj: Function | UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        super().__init__(**kwargs)


class UnaryOp(ast.UnaryOp):
    def __init__(self, obj: Function | UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        super().__init__(**kwargs)


class BoolOp(ast.BoolOp):
    def __init__(self, obj: Class | UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        super().__init__(**kwargs)


class JoinedStr(ast.JoinedStr):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class Subscript(ast.Subscript):
    def __init__(
        self, obj: Class | UnionType, value_obj: Object | UnionType = None, **kwargs
    ):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        self.value_obj = value_obj if value_obj is not None else obj
        assert isinstance(self.value_obj, (Object, UnionType, type(None))), (
            f"{self.value_obj} is not an Object or UnionType"
        )
        super().__init__(**kwargs)


class Starred(ast.Starred):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class Await(ast.Await):
    def __init__(
        self, obj: Class | UnionType, value_obj: Object | UnionType = None, **kwargs
    ):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        self.value_obj = value_obj if value_obj is not None else obj
        assert isinstance(self.value_obj, (Object, UnionType))
        super().__init__(**kwargs)


class IfExp(ast.IfExp):
    def __init__(self, obj: Class | UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        super().__init__(**kwargs)


class ListComp(ast.ListComp):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class DictComp(ast.DictComp):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class SetComp(ast.SetComp):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class GeneratorExp(ast.GeneratorExp):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)

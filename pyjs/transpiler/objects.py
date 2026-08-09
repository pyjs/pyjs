import annotationlib
import ast
import importlib.util
import inspect
import sys
import types
import typing
from collections.abc import Iterable
from functools import partial
from typing import Generic

from pyjs.decorators import *

from .diagnostics import CompilationContext, SourceFragment

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
JS_MODULE_VALUE_TYPES = (bool, int, float, str, type(None))


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
} | DECORATIONS


def py_to_ast(value):
    import ast

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


def unwrap_js_annotation(annotation) -> tuple[object, bool] | None:
    is_final = typing.get_origin(annotation) is typing.Final
    if is_final:
        annotation = typing.get_args(annotation)[0]

    origin = typing.get_origin(annotation)
    if origin is JS:
        return typing.get_args(annotation)[0], is_final
    if origin is typing.Annotated:
        value_type, *metadata = typing.get_args(annotation)
        if js in metadata:
            return value_type, is_final
    return None


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
        target_implementation = getattr(target, "__js_replace__", target)
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
        self.visited = set()

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

    def build(self, namespace, container: Object, propagate_js=False):
        for name, py_obj in vars(namespace).items():
            if name in IGNORE_NAMES:
                continue

            if inspect.isbuiltin(py_obj):
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
                    GenericClass.from_py_cls(py_obj, container)
                else:
                    Class.from_py_cls(py_obj, container).build()
            elif callable(py_obj) or isinstance(py_obj, (classmethod, staticmethod)):
                Function.from_py_func(py_obj, container)
            elif js_module_binding is not None:
                if not isinstance(py_obj, JS_MODULE_VALUE_TYPES):
                    raise TypeError(
                        f"JS module binding `{name}` has unsupported value type "
                        f"`{type(py_obj).__name__}`."
                    )
                annotation, is_final = js_module_binding
                if annotation is None:
                    annotation = type(None)
                value_type = resolve_python_annotation(annotation, container.scope)
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
        self.extensions = extensions
        self.context = context or CompilationContext()
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
        return ModuleDef(self, body=body, type_ignores=[])

    @property
    def children(self):
        return list(self.scope.names.values())

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
                if alias.name not in js_annotations:
                    continue
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


class UnionType:
    def __init__(self, name: str = None, types: Iterable[Class] = None):
        self.name = name
        self._types: dict[str, Class] = {cls.name: cls for cls in types} if types else {}

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

    def add(self, cls: Class):
        self._types.setdefault(cls.name, cls)

    def reassign(self, name, *args, **kwargs):
        return UnionType(name, self.types)

    def to_annotation_str(self, delim="|"):
        return delim.join(t.name for t in self.types)

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
        if assigned_types:
            for type_name, type_cls in assigned_types.items():
                self.scope.add(type_cls, type_name)
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = cls
        self._self = Instance("self", self, self.scope, self)
        self.subclasses = []
        if self.name == "object" and getattr(cls, "__builtin__", False):
            self.super = None
        elif cls.__base__ is Generic:
            self.super = None
        else:
            self.super = self.search(cls.__base__.__name__)
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
                assert all(isinstance(arg, Class) for arg in generic_types)
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
        return ClassDef(
            self,
            bases=[self.super.annotation]
            if (self.super and self.super.name != "object")
            else [],
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
    def from_py_cls(cls, py_cls: type, container: Module):
        cls_ = cls(py_cls, container)
        container.scope.add(cls_)
        return cls_

    def build(self, *args, **kwargs):
        super().build(self.py_cls, self, propagate_js=True)

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


def resolve_python_annotation(annotation, scope: Scope):
    origin = typing.get_origin(annotation)
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
    if origin is not None:
        generic = scope.search(origin.__name__)
        assert isinstance(generic, GenericClass)
        return generic(
            *[
                resolve_python_annotation(value, scope)
                for value in typing.get_args(annotation)
            ]
        )
    return scope.search(annotation.__name__)


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
            left_type is right_type
            for left_type, right_type in zip(left_types, right_types, strict=True)
        )
    return left is right


class GenericClass(Object):
    def __init__(self, cls: type, container: Module):
        super().__init__(cls.__name__, ClassScope(container.scope), container)
        self.py_cls = cls
        self.init_params = None
        if cls_init := getattr(cls, "__init__", None):
            self.init_params = inspect.signature(cls_init).parameters
        self.generic_params = [type_param.__name__ for type_param in cls.__type_params__]
        self.concrete_classes = {}

    @property
    def node(self):
        return [c.node for c in self.concrete_classes.values()]

    @property
    def py_obj(self):
        return self.py_cls

    @classmethod
    def from_py_cls(cls, py_cls: type, container: Module):
        cls_ = cls(py_cls, container)
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
            f"{self.name}__{'_'.join([arg.to_annotation_str('U') for arg in args])}"
        )

        generics = {}
        for name, arg in zip(params, args, strict=True):
            if isinstance(arg, UnionType):
                generics[name] = UnionType(name, arg.types)
            else:
                assert isinstance(arg, Class)
                generics[name] = arg

        concrete_class = self.concrete_classes.get(concrete_name)
        if concrete_class is not None and all(
            same_analyzer_type(concrete_class.generic_types[name], generic_type)
            for name, generic_type in generics.items()
        ):
            return concrete_class

        concrete_class = Class(
            self.py_cls, self.container, assigned_types=generics, name=concrete_name
        )
        self.concrete_classes[concrete_name] = concrete_class
        concrete_class.build()
        raise DependencyError(concrete_class)

    def from_call(self, arg_types):
        # TODO: handle different arg schemes other than positional
        assert self.init_params
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
        self.return_type = None
        self.declared_return_type = None
        self.inferred_return_type = None

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
        self.is_partial_client = False
        self.virtual_visited = set()

    def reset(self):
        self.is_analyzed = False
        self.scope.names = {}
        if self.cls is not None:
            self.scope.add(self.cls.super, "super")
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

    @property
    def py_obj(self):
        return self.py_func

    @property
    def type(self):
        return self.return_type

    @classmethod
    def from_py_func(cls, py_func: callable, container: Module | Class):
        client_implementation = getattr(py_func, "__js_replace__", None)
        client_partial = (
            client_implementation if isinstance(client_implementation, partial) else None
        )
        source_func = (
            py_func if client_partial is not None else client_implementation or py_func
        )
        lines, lineno = inspect.getsourcelines(source_func)
        is_method = isinstance(container, Class)

        if is_method:
            # to preserve indentation for sourcemap and still make the function parseable
            lines.insert(0, f"class {container.name}:\n")
            lineno -= 1  # we need to subtract the dummy line from total line offset

        source = "".join(lines)
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
            for name, imported in imports.items():
                traverse_imported(name, imported, module_obj)
        ast.fix_missing_locations(func_def)

        func = cls(py_func if client_partial is not None else source_func, container)
        func.name = py_func.__name__
        func.is_partial_client = client_partial is not None
        func.lineno = lineno
        func.original_node = func_def
        simple_wrapper = (
            source_func is getattr(module_obj.py_module, "main", None)
            and getattr(module_obj.py_module, "__pyjs_simple_wrapper__", False)
        )
        func.source_fragment = SourceFragment(
            module_obj.context.sources.fragment_for(source_func).source,
            lineno - 2 if simple_wrapper else lineno - 1,
            -4 if simple_wrapper else 0,
        )
        func.is_async = isinstance(func_def, ast.AsyncFunctionDef)

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
            decorator_list=[],
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
        if has_inline_decorator(self.py_func):
            return self

    @property
    def has_source_decorator(self):
        return getattr(self.py_func, "__js_rewrite_func__", False)

    @property
    def has_include_decorator(self):
        return has_include_decorator(self.py_func)

    def get_predefined_source(self):
        return self.py_func.__js_rewrite_func__()

    def rewrite_call(
        self,
        arg_strs: list[str],
        arg_types: list[Class],
        self_=None,
        *,
        keyword_strs: dict[str, str] | None = None,
        inline_dependencies: dict[str, str] | None = None,
    ):
        rewrite = self.py_func.__js_rewrite_call_site__
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
        super().__init__(**kwargs)


class Name(ast.Name):
    def __init__(self, obj: Object, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Object, UnionType)), f"{self.obj} is not an Object"
        super().__init__(**{"id": obj.name, **kwargs})


class Attribute(ast.Attribute):
    def __init__(self, obj: Object, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Object, UnionType)), f"{self.obj} is not an Object"
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
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class ListComp(ast.ListComp):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)

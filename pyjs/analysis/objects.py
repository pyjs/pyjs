import annotationlib
import ast
import builtins
import dataclasses
import enum
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
from pyjs.numeric import array_format, array_item, numeric_format

from .diagnostics import CompilationContext, DiagnosticCode, SourceFragment
from .libraries import LibraryClassInfo, LibraryCompatibilityError, LibraryMappings
from .representation import (
    ValueRepresentation,
    annotation_representation,
    apply_representation,
    type_alias_value,
)

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
JS_MODULE_VALUE_TYPES = (bool, int, float, str, list, tuple, dict, type(None))
GENERIC_TYPE_ALIASES = {
    "Mapping": "dict",
    "MutableMapping": "dict",
}
_FUNCTION_SOURCES = weakref.WeakKeyDictionary()


def _function_source(function: callable) -> tuple[str, int]:
    function = getattr(function, "__func__", function)
    function = inspect.unwrap(function)
    if cached := _FUNCTION_SOURCES.get(function):
        return cached
    lines, lineno = inspect.getsourcelines(function)
    result = "".join(lines), lineno
    _FUNCTION_SOURCES[function] = result
    return result


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


def py_to_ast(value, value_type=None):
    if isinstance(value, (bool, int, float, str, bytes, type(None))):
        return ast.Constant(value=value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        if type(value) is set and getattr(value_type, "generic_name", None) == "frozenset":
            raise TypeError("frozenset literals require the frozenset constructor, not a set display")
        members = [None] * len(value)
        if isinstance(value_type, Class):
            types = list(value_type.generic_types.values())
            expected = types if type(value) is tuple and not value_type.tuple_variadic else types * len(value)
            if len(expected) == len(value):
                members = expected  # Let the backend diagnose malformed tuple lengths.
        elements = [py_to_ast(item, member) for item, member in zip(value, members, strict=True)]
        if type(value) is frozenset:
            if not isinstance(value_type, Class) or value_type.generic_name != "frozenset":
                raise TypeError("frozenset literals require a concrete frozenset annotation")
            # Module literals enter reachability without a second inference
            # pass. Keep constructor metadata typed, as ordinary calls are.
            return Call(value_type, func=Name(value_type), args=[ast.Set(elts=elements)], keywords=[])
        return {list: ast.List, tuple: ast.Tuple, set: ast.Set}[type(value)](
            elts=elements
        )
    elif isinstance(value, dict):
        key_type, item_type = (value_type.generic_types.values()
                              if isinstance(value_type, Class) and value_type.generic_name == "dict" else (None, None))
        return ast.Dict(
            keys=[py_to_ast(k, key_type) for k in value.keys()],
            values=[py_to_ast(v, item_type) for v in value.values()],
        )
    else:
        raise TypeError(f"Unsupported type: {type(value)}")


def _module_assignment_values(body: list[ast.stmt]) -> dict[str, ast.expr]:
    values = {}
    for node in body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            values[node.targets[0].id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            values[node.target.id] = node.value
    return values


def _literal_value(node, names=None):
    """Read effect-free literal syntax, including genuine builtin frozenset().

    Never evaluate user code: constructor arguments recursively contain only
    literals, and module callers supply their namespace to reject shadowing.
    """
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        constructor = {"set": set, "frozenset": frozenset}.get(name)
        if (constructor is None or node.keywords or len(node.args) > (name == "frozenset")
                or (names is not None and names.get(name, constructor) is not constructor)):
            raise ValueError("nonliteral call")
        return constructor(*[_literal_value(arg, names) for arg in node.args])
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        constructor = {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)]
        return constructor(_literal_value(item, names) for item in node.elts)
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise ValueError("literal unpacking")
        return {_literal_value(key, names): _literal_value(value, names)
                for key, value in zip(node.keys, node.values, strict=True)}
    return ast.literal_eval(node)


def _literal_state(value, seen=None):
    """Compare imported literal graphs without user equality or lost dict order.

    Literal syntax cannot introduce mutable aliases or cycles, nor share two
    separate frozenset constructor results. Equal contents do not imply that
    reconstructing fresh objects preserves identity.
    """
    seen = set() if seen is None else seen
    kind = type(value)
    if kind is float:
        return kind, value.hex()  # Equality alone loses the sign of zero.
    if kind in {str, bytes, int, bool, type(None)}:
        return kind, value
    if kind not in {list, tuple, dict, set, frozenset}:
        raise ValueError("nonliteral value")
    if kind is not tuple:
        if id(value) in seen:
            raise ValueError("aliased or recursive literal")
        seen.add(id(value))
    if kind is dict:
        content = tuple((_literal_state(key, seen), _literal_state(item, seen))
                        for key, item in value.items())
    else:
        items = (_literal_state(item, seen) for item in value)
        content = frozenset(items) if kind in {set, frozenset} else tuple(items)
    return kind, content


def _class_field_nodes(
    node: ast.ClassDef | None,
) -> tuple[dict[str, ast.expr], dict[str, ast.expr]]:
    declarations = {}
    values = {}
    if node is None:
        return declarations, values
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            declarations[statement.target.id] = statement.annotation
            if statement.value is not None:
                values[statement.target.id] = statement.value
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = statement.value
    return declarations, values


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
    if origin is Callable:
        parameters, result = typing.get_args(annotation)
        if parameters is Ellipsis:
            parameter_source = "..."
        else:
            parameter_source = "[" + ", ".join(
                _annotation_source(parameter) for parameter in parameters
            ) + "]"
        return f"Callable[{parameter_source}, {_annotation_source(result)}]"
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
    # Postponed annotations (including slots dataclasses) can have no annotate
    # function. Their string types still resolve in the defining module.
    globals_ = (annotate.__globals__ if annotate is not None
                else vars(sys.modules[cls.__module__]))
    return annotation.evaluate(
        globals=globals_,
        locals={cls.__name__: cls},
        owner=cls,
    )


def _dataclass_default_source(field: dataclasses.Field) -> str | None:
    if field.default is not dataclasses.MISSING:
        value = py_to_ast(field.default)
        if any(isinstance(node, ast.Constant) and isinstance(node.value, enum.Enum)
               for node in ast.walk(value)):
            raise TypeError(f"Enum default for dataclass field {field.name!r} is not supported; pass the member explicitly")
        return ast.unparse(value)
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
        "        if self is other:\n"
        "            return True\n"
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
    # Python 3.14 synthesizes this function for deferred module annotations.
    # It has no authored function body for a compiler backend to analyze.
    "__annotate__",
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
    "__pyjs_django_model__",
    "__pyjs_model__",
} | DECORATIONS


def has_keep_decorator(obj) -> bool:
    return bool(js_metadata(obj, "keep", False))


def is_inline_class(obj) -> bool:
    return (
        inspect.isclass(obj)
        and is_inline_for(obj, "js")
        and not getattr(obj, "__builtin__", False)
    )


def should_include(obj) -> bool:
    runtime_implementation = getattr(obj, "is_runtime_implementation", False)
    kept = has_keep_decorator(obj.py_obj)
    if is_inline_for(obj.py_obj, "js") and not kept and not runtime_implementation:
        return False
    is_builtin = getattr(obj.py_obj, "__dict__", {}).get("__builtin__", False)
    if is_builtin and not runtime_implementation:
        return False
    return kept or bool(obj.visited)


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
    if isinstance(value, tuple):
        if not value:
            raise TypeError(
                "Cannot infer the item types of an empty JS module tuple; "
                "use JS[tuple[T, ...]]."
            )
        return tuple[tuple(infer_js_annotation(item) for item in value)]
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
    if obj is typing.Literal or obj is typing.Callable or obj is Callable:
        return TypeAliasValue(fallback_name or obj.__name__, obj, current_module.scope, current_module)
    module_name = obj.__module__
    if module_name == current_module.py_module.__name__:
        existing = current_module.scope.names.get(getattr(obj, "__name__", None))
        if existing is not None and existing.py_obj is obj:
            if isinstance(existing, DeferredDefinition):
                return existing.resolve()
            return existing
    if isinstance(obj, typing.TypeAliasType) and inspect.getmodule(obj) is None:
        raise TypeError("Type aliases require an importable defining module")
    builtin_module = current_module.scope.BUILTINS
    name = getattr(obj, "__name__", "").removeprefix("_")
    declaration = builtin_module.scope.names.get(name)
    if declaration is not None and (
        declaration.py_obj is obj or getattr(builtins, name, None) is obj
    ):
        # Library mappings may resolve public APIs to builtin declarations.
        # Rebuilding them as application classes loses their canonical type.
        return declaration
    package = current_module.container
    if module_name not in package:
        package[module_name] = Module(
            inspect.getmodule(obj),
            package,
            extensions=current_module.extensions,
            context=current_module.context,
            defer_unselected_imports=current_module.defer_unselected_imports,
            definition_filter=current_module.definition_filter,
            library_mappings=current_module.library_mappings,
            backend=current_module.backend,
        ).build()
    imported_module = package[module_name]
    if isinstance(obj, typing.TypeAliasType):
        alias = imported_module.type_aliases.get(obj)
        if alias is None:
            # A factory or class body can create an alias without binding it
            # in its __module__'s globals. Keep its identity without inventing
            # a public module binding that could shadow another declaration.
            alias = TypeAliasValue(obj.__name__, obj, imported_module.scope, imported_module)
            imported_module.type_aliases[obj] = alias
        return alias
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
        if (existing.py_obj is not obj
                and resolve_imported(obj, current_module, obj_name) is not existing):
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
        target_implementation = js_metadata(target, "client", target)
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
    module: Module

    def __init__(self, is_builtins: bool):
        super().__init__()
        self.is_builtins = is_builtins

    def search(self, name):
        if value := self.names.get(name):
            if isinstance(value, (DeferredImport, DeferredDefinition, DeferredValue)):
                return value.resolve()
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
        module = (
            container
            if isinstance(container, Module)
            else container.container
        )
        for name, py_obj in vars(namespace).items():
            original_py_obj = py_obj
            builtin_name = None
            if isinstance(container, Module) and container.scope.is_builtins:
                if not name.startswith("_") or name.startswith("__"):
                    continue
                builtin_name = name[1:]
            if name in IGNORE_NAMES or name in skip_names:
                continue

            if (isinstance(container, Module) and not container.scope.is_builtins
                    and isinstance(py_obj, type) and getattr(builtins, py_obj.__name__, None) is py_obj):
                # An aliased Python builtin still denotes the active backend's
                # canonical model, even when the application shadows its name.
                declaration = container.scope.BUILTINS.scope.names.get(py_obj.__name__)
                if declaration is not None:
                    container.scope.add(declaration, name)
                    continue

            binding = container.scope.names.get(name)
            if isinstance(binding, DeferredImport) and binding.error is not None:
                continue  # Keep an unsupported from-import lazy, including constants.
            try:
                py_obj = module.library_mappings.resolve(py_obj)
            except LibraryCompatibilityError as error:
                if isinstance(container, Class):
                    node = container.field_value_nodes.get(name)
                    if node is not None and module.source_fragment is not None:
                        module.context.error(module.source_fragment, node,
                                             DiagnosticCode.UNSUPPORTED_SYNTAX, str(error))
                    module.context.definition_error(container.py_cls,
                                                    DiagnosticCode.UNSUPPORTED_SYNTAX, str(error))
                if not isinstance(container, Module) or not container.defer_unselected_imports:
                    raise
                container.add(DeferredImport(name, py_obj, container, error=str(error)))
                continue
            # A backend may model a C-implemented host function with a typed
            # Python declaration, including through a module-qualified import.
            if inspect.isbuiltin(py_obj):
                continue

            if isinstance(container, Module) and (
                py_obj is Callable or py_obj is typing.Callable or py_obj is typing.Literal
            ):
                # These are annotation constructors, not reachable Python
                # implementations of collections.abc's subscription machinery.
                container.add(TypeAliasValue(name, py_obj, container.scope, container))
                continue
            if isinstance(py_obj, types.ModuleType) and (
                py_obj is not original_py_obj
                or isinstance(container, Module)
                and container.defer_unselected_imports
            ):
                assert isinstance(container, Module)
                container.add(ModuleAlias(name, py_obj, container))
                continue

            type_alias_type = getattr(typing, "TypeAliasType", ())
            if isinstance(py_obj, type_alias_type):
                # Register imported aliases without building their module until
                # they are reached. Backend libraries also import annotation-only
                # aliases from modules whose implementation is not compilable.
                alias = module.type_aliases.get(py_obj)
                if alias is None:
                    alias = TypeAliasValue(name, py_obj, container.scope, container)
                    module.type_aliases[py_obj] = alias
                container.scope.add(alias, name)
                continue
            declared_numeric_format = getattr(
                py_obj,
                "__pyjs_numeric_format__",
                None,
            )
            if isinstance(container, Module) and declared_numeric_format is not None:
                numeric_base = int if declared_numeric_format.kind == "integer" else float
                container.add(
                    TypeAliasValue(
                        name,
                        typing.Annotated[numeric_base, declared_numeric_format],
                        container.scope,
                        container,
                    )
                )
                continue
            if isinstance(container, Module) and array_format(py_obj) is not None:
                container.add(TypeAliasValue(name, py_obj, container.scope, container))
                continue
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
            target_selected = False
            if isinstance(container, Module) and container.definition_filter is not None:
                target_selected = container.definition_filter(name, py_obj, container)
                if not target_selected:
                    if container.defer_unselected_imports and (
                        inspect.isfunction(py_obj) or inspect.isclass(py_obj)
                    ):
                        if getattr(py_obj, "__module__", None) in {container.name, None}:
                            container.add(DeferredDefinition(
                                name, py_obj, container, source_overrides.get(name),
                            ))
                        else:
                            container.add(DeferredImport(name, py_obj, container))
                    continue
            is_typed_dict = typing.is_typeddict(py_obj)
            if target_selected and js_module_binding is None and isinstance(py_obj, (list, tuple, dict, set, frozenset)):
                container.add(DeferredValue(name, py_obj, container))
                continue
            js_attr = is_js_enabled(py_obj)
            if not target_selected and (
                js_attr is False
                or (
                    js_attr is None
                    and not propagate_js
                    and not is_typed_dict
                    and js_module_binding is None
                )
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
                if not isinstance(container, Module):
                    message = f"Class-valued attribute {name!r} is not supported"
                    node = container.field_value_nodes.get(name)
                    if node is not None and module.source_fragment is not None:
                        module.context.error(module.source_fragment, node,
                                             DiagnosticCode.UNSUPPORTED_SYNTAX, message)
                    module.context.definition_error(container.py_cls,
                                                    DiagnosticCode.UNSUPPORTED_SYNTAX, message)
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
                    is_js_enabled(py_obj.fget) is False
                ):
                    continue
                getter = Function.from_py_func(
                    py_obj.fget,
                    container,
                    emitted_name=name,
                )
                getter.is_property = True
                if py_obj.fset is not None and (
                    is_js_enabled(py_obj.fset) is not False
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
                    container.binding_error(
                        name,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        f"JS module binding `{name}` has unsupported value type "
                        f"`{type(py_obj).__name__}`",
                        help=(
                            "Use a literal bool, int, float, str, list, tuple, "
                            "dict, or None value."
                        ),
                    )
                annotation, is_final = js_module_binding
                if annotation is None:
                    try:
                        annotation = infer_js_annotation(py_obj)
                    except TypeError as error:
                        container.binding_error(
                            name,
                            DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                            str(error),
                            help=(
                                "Specialize JS with the complete client type, "
                                "such as JS[list[str]]."
                            ),
                        )
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
                if target_selected and isinstance(py_obj, (bool, int, float, str)):
                    value = Instance.from_static_value(name, py_obj, container)
                    # Native constants use their evaluated host value, including
                    # layout sizes calculated by ctypes during module import.
                    value.static_value = py_to_ast(py_obj)
                    container.add(value)
                elif is_js_enabled(py_obj) is True:
                    container.add(Instance.from_static_value(name, py_obj, container))


class DeferredImport(Object):
    """Materialize an ordinary imported definition only when it is reached."""

    def __init__(self, name: str, imported: object, container: Module, *,
                 error: str | None = None, import_node: ast.AST | None = None):
        super().__init__(name, container.scope, container)
        self.imported = imported
        self.error = error
        self.import_node = import_node

    @property
    def py_obj(self):
        return self.imported

    @property
    def type(self):
        return self.resolve().type

    @property
    def node(self):
        return []

    def resolve(self) -> Object:
        if self.error is not None:
            if self.import_node is not None and self.container.source_fragment is not None:
                self.container.context.error(self.container.source_fragment, self.import_node,
                                             DiagnosticCode.UNSUPPORTED_SYNTAX, self.error)
            self.container.binding_error(self.name, DiagnosticCode.UNSUPPORTED_SYNTAX, self.error,
                                         help="Use a supported library API or keep this import unreachable.")
        current = self.container.scope.names.get(self.name)
        if current is not self:
            return current
        if inspect.isclass(self.imported) and hasattr(
            self.imported,
            "__pyjs_array_domain__",
        ):
            imported = GenericClass(
                self.imported,
                self.container,
                name=self.name,
            )
            self.container.scope.add(imported, self.name)
            return imported
        imported = resolve_imported(self.imported, self.container, self.name)
        self.container.scope.add(imported, self.name)
        binding = (imported, self.name)
        bindings = self.container.imported.setdefault(
            self.imported.__module__,
            [],
        )
        if binding not in bindings:
            bindings.append(binding)
        return imported


class DeferredDefinition(Object):
    """Materialize an ordinary module definition only when it is reached."""

    def __init__(
        self,
        name: str,
        definition: object,
        container: Module,
        source_override: str | None,
    ):
        super().__init__(name, container.scope, container)
        self.definition = definition
        self.source_override = source_override

    @property
    def py_obj(self):
        return self.definition

    @property
    def type(self):
        return self.resolve().type

    @property
    def node(self):
        return []

    def resolve(self) -> Object:
        current = self.container.scope.names.get(self.name)
        if current is not self:
            return current
        definition = self.definition
        # Module aliases must share the canonical analysis object. Rebuilding
        # a class through an alias leaves that alias deferred and continually
        # invalidates the call graph as its methods acquire new identities.
        canonical = self.container.scope.names.get(definition.__name__)
        if canonical is not None and canonical is not self:
            if canonical.py_obj is definition:
                if isinstance(canonical, DeferredDefinition):
                    canonical = canonical.resolve()
                self.container.scope.add(canonical, self.name)
                return canonical
        if typing.is_typeddict(definition):
            analyzed = TypedDictClass.from_py_cls(definition, self.container)
        elif inspect.isclass(definition):
            if Class.is_generic(definition):
                analyzed = GenericClass.from_py_cls(definition, self.container)
            else:
                analyzed = Class.from_py_cls(definition, self.container)
                self.container.scope.add(analyzed, self.name)
                analyzed.build()
        else:
            analyzed = Function.from_py_func(
                definition,
                self.container,
                source_override=self.source_override,
            )
        self.container.scope.add(analyzed, self.name)
        return analyzed


class DeferredValue(Object):
    """A target-selected module literal, typed only when reachable."""

    def __init__(self, name, value, container):
        super().__init__(name, container.scope, container)
        self.value = value
        self.resolving = False

    @property
    def py_obj(self):
        return self.value

    @property
    def type(self):
        return self.resolve().type

    @property
    def node(self):
        return []

    def resolve(self):
        current = self.container.scope.names.get(self.name)
        if current is not self:
            return current
        if self.resolving:
            self.container.binding_error(self.name, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                         f"Module literal alias {self.name!r} is cyclic",
                                         help="Keep one direct literal initializer for each collection.")
        self.resolving = True
        try:
            return self.container.materialize_static_value(self.name, self.value)
        finally:
            self.resolving = False


class TypeAliasValue(Object):
    def __init__(self, name: str, annotation, scope: Scope, container: Object):
        super().__init__(name, scope, container)
        self.annotation = annotation
        self.resolved_type = None
        self.recursive_type = None
        self.resolving = False
        self.pending_aliases = []

    @property
    def py_obj(self):
        return self.annotation

    @property
    def type(self):
        return self

    @property
    def node(self):
        return []

    def resolve_type(self):
        if self.resolved_type is not None:
            # A sibling may have suspended on a generic method dependency after
            # this alias cached its named edge. Finish that sibling on retry,
            # unless it is currently using our edge to resolve the same cycle.
            for edge in self.pending_aliases:
                if edge.target is None and not edge.alias.resolving:
                    edge.alias.resolve_type()
            self.pending_aliases = [edge for edge in self.pending_aliases if edge.target is None]
            return self.resolved_type
        module = self.container if isinstance(self.container, Module) else self.container.container
        if (isinstance(self.annotation, typing.TypeAliasType)
                and self.annotation.__module__ != module.name):
            self.resolved_type = resolve_imported(self.annotation, module).resolve_type()
            return self.resolved_type
        if self.resolving:
            if self.recursive_type is None:
                self.recursive_type = RecursiveTypeAlias(self)
            return self.recursive_type
        self.resolving = True
        try:
            annotation = self.annotation
            if isinstance(annotation, typing.TypeAliasType):
                if annotation.__type_params__:
                    raise TypeError("Generic type aliases are not supported")
                annotation = type_alias_value(annotation)
            resolved = resolve_python_annotation(annotation, self.scope)
        finally:
            # Generic construction may suspend analysis with DependencyError.
            # Keep the cycle edge for the retry, but never cache a partial type.
            self.resolving = False
        if self.recursive_type is None:
            # Every alias on a cycle needs a named edge, not only the alias
            # first re-entered. Otherwise a cached outer union becomes a
            # structurally recursive generic key once that first edge binds.
            pending, seen = [resolved], set()
            while pending:
                member = pending.pop()
                if id(member) in seen:
                    continue
                seen.add(id(member))
                if isinstance(member, RecursiveTypeAlias) and member.target is None:
                    self.pending_aliases.append(member)
                    continue
                if isinstance(member, UnionType):
                    pending.extend(member.types)
                elif isinstance(member, Class):
                    pending.extend((member.generic_types or {}).values())
            if self.pending_aliases:
                self.recursive_type = RecursiveTypeAlias(self)
        if self.recursive_type is not None:
            self.recursive_type.bind(resolved)
            resolved = self.recursive_type
        self.resolved_type = resolved
        return resolved

class Module(Object):
    scope: ModuleScope

    def __init__(
        self,
        module,
        package,
        is_builtins: bool = False,
        extensions: tuple[CompilationExtension, ...] = (),
        context: CompilationContext | None = None,
        defer_unselected_imports: bool = False,
        definition_filter=None,
        library_mappings: LibraryMappings | None = None,
        backend: str = "js",
    ):
        super().__init__(module.__name__, ModuleScope(is_builtins), package)
        self.scope.module = self
        self.type_aliases: dict[typing.TypeAliasType, TypeAliasValue] = {}
        self.py_module = module
        self.imported: dict[str, list[tuple[Object, str]]] = {}
        self.inline_dependencies: dict[Object, str] = {}
        self.inline_dependency_roots: dict[Object, weakref.WeakSet[Function]] = {}
        self.side_effect_dependencies: set[Object] = set()
        self.runtime_implementations: dict[callable, Function] = {}
        self.extensions = extensions
        self.context = context or CompilationContext()
        self.defer_unselected_imports = defer_unselected_imports
        self.definition_filter = definition_filter
        self.backend = backend
        self.library_mappings = (
            library_mappings
            if library_mappings is not None
            else LibraryMappings()
        )
        self.type_dependencies: list[Class] = []
        filename = getattr(module, "__file__", None)
        if filename is not None:
            source_file = self.context.sources.register(
                filename,
                getattr(module, "__pyjs_source__", None),
            )
            self.source_fragment = SourceFragment(source_file)
        else:
            self.source_fragment = None
        self.js_annotations = module_js_annotations(module)
        self.static_initializers: dict[str, ast.expr] = {}
        self.imported_value_bindings = {}
        self.class_definitions: dict[str, ast.ClassDef] = {}
        self.preserved_static_initializers: set[str] = set()

    def register_inline_dependency(
        self,
        dependency_obj: Object,
        entry_point: Function,
    ) -> str:
        roots = self.inline_dependency_roots.setdefault(
            dependency_obj,
            weakref.WeakSet(),
        )
        roots.add(entry_point)
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

    def binding_error(
        self,
        name: str,
        code: DiagnosticCode,
        message: str,
        *,
        help: str,
    ) -> typing.Never:
        initializer = self.static_initializers.get(name)
        if self.source_fragment is None:
            raise TypeError(message)
        if initializer is None:
            # A dynamically created binding has no initializer to underline.
            # Anchor its diagnostic at the module instead of leaking an AST
            # traversal failure (or pretending there is a source expression).
            initializer = ast.Constant(value=None, lineno=1, col_offset=0)
        self.context.error(
            self.source_fragment,
            initializer,
            code,
            message,
            help=help,
        )

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

        value = js_metadata(py_interface, "value")
        if value is None:
            raise ValueError(f"{interface.name!r} does not have a value implementation")

        py_implementation = value.value if value.kind == "function" else None
        source = value.value if value.kind == "source" else None
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
        module_node = ast.parse(inspect.getsource(self.py_module))
        self.static_initializers = _module_assignment_values(module_node.body)
        self.class_definitions = {
            node.name: node
            for node in module_node.body
            if isinstance(node, ast.ClassDef)
        }
        self.build_imported_js_bindings(module_node.body)
        super().build(self.py_module, self)
        return self

    def materialize_static_value(self, name, py_obj):
        if binding := self.imported_value_bindings.get(name):
            self.add_imported_js_binding(*binding, name)
            return self.scope.search(name)
        initializer = self.static_initializers.get(name)
        if initializer is None:
            self.binding_error(name, DiagnosticCode.UNSUPPORTED_SYNTAX,
                               f"Module value {name!r} requires a direct literal initializer",
                               help="Declare its literal at module scope, outside conditionals or dynamic initialization.")
        if isinstance(initializer, ast.Name):
            alias = self.scope.search(initializer.id)
            if alias.py_obj is py_obj:
                return self.scope.add(alias, name)
        annotation = annotationlib.get_annotations(
            self.py_module, format=annotationlib.Format.FORWARDREF,
        ).get(name)
        if isinstance(annotation, str):
            annotation = annotationlib.ForwardRef(annotation, owner=self.py_module)
        if isinstance(annotation, annotationlib.ForwardRef):
            annotation = annotation.evaluate(owner=self.py_module)
        if annotation is None:
            try:
                annotation = infer_js_annotation(py_obj)
            except TypeError:
                self.binding_error(name, DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                                   f"Module literal {name!r} needs a complete collection annotation",
                                   help="Declare its item types, for example list[int] or set[str].")
        while True:
            try:
                value_type = resolve_python_annotation(annotation, self.scope)
                break
            except DependencyError as dependency:
                if dependency.class_or_func not in self.type_dependencies:
                    self.type_dependencies.append(dependency.class_or_func)
        if not isinstance(value_type, Class) or value_type.generic_name not in {"list", "tuple", "dict", "set", "frozenset"}:
            self.binding_error(name, DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                               f"Module literal {name!r} needs one concrete collection type",
                               help="Use a complete list, tuple, dict, set or frozenset annotation.")
        try:
            # Keep import-time calls out of reachability. Only effect-free
            # literals may be reconstructed lazily in a backend-owned heap.
            literal = _literal_value(initializer, vars(self.py_module))
        except (ValueError, TypeError, SyntaxError):
            self.binding_error(name, DiagnosticCode.UNSUPPORTED_SYNTAX,
                               f"Module value {name!r} requires a literal initializer",
                               help="Use nested literal collections without calls or unpacking.")
        try:
            source = py_to_ast(literal, value_type)
        except (ValueError, TypeError) as error:
            self.binding_error(name, DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                               f"Module literal {name!r}: {error}",
                               help="Use a concrete collection annotation matching each literal's kind.")
        try:
            unchanged = _literal_state(literal) == _literal_state(py_obj)
        except ValueError:
            unchanged = False
        if not unchanged:
            self.binding_error(name, DiagnosticCode.UNSUPPORTED_SYNTAX,
                               f"Module literal {name!r} changed during import",
                               help="Move initialization mutations into a reached function; import-time effects are not compiled.")
        ast.copy_location(source, initializer)
        value = value_type(name, self.scope, self, source, py_obj, is_const=False)
        apply_representation(value, annotation_representation(annotation))
        self.add(value)
        return value

    def build_imported_js_bindings(self, body: list[ast.stmt]):
        for node in body:
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
                target = self.library_mappings.stdlib_target(
                    module_name,
                    alias.name,
                )
                if target is not None:
                    if alias.name == "*":
                        message = "Star imports from mapped libraries are not supported"
                        if self.source_fragment is not None:
                            self.context.error(self.source_fragment, node,
                                               DiagnosticCode.UNSUPPORTED_SYNTAX, message)
                        raise LibraryCompatibilityError(message)
                    replacement_module, replacement_name = target
                    assert replacement_name is not None
                    replacement = importlib.import_module(replacement_module)
                    if self.defer_unselected_imports and not hasattr(replacement, replacement_name):
                        local_name = alias.asname or alias.name
                        imported = getattr(imported_module, alias.name)
                        if getattr(self.py_module, local_name, None) is not imported:
                            continue  # A later module assignment replaced this import.
                        self.add(DeferredImport(
                            local_name, imported, self,
                            error=f"{module_name}.{alias.name} is not supported by {replacement_module}",
                            import_node=alias,
                        ))
                        continue
                    self.add_imported_js_binding(
                        replacement,
                        replacement_name,
                        alias.asname or alias.name,
                    )
                elif alias.name not in js_annotations:
                    local_name = alias.asname or alias.name
                    value = getattr(imported_module, alias.name, None)
                    if (self.defer_unselected_imports and self.definition_filter is not None
                            and local_name not in self.static_initializers
                            and isinstance(value, (list, tuple, dict, set, frozenset))
                            and self.definition_filter(local_name, value, self)):
                        self.imported_value_bindings[local_name] = imported_module, alias.name
                else:
                    self.add_imported_js_binding(
                        imported_module,
                        alias.name,
                        alias.asname or alias.name,
                    )

    def resolve_static_initializer(self, name: str) -> ast.expr | None:
        initializer = self.static_initializers.get(name)
        if initializer is None:
            return None
        self.preserved_static_initializers.add(name)
        return initializer

    def add_imported_js_binding(self, module, source_name: str, local_name: str):
        if module.__name__ not in self.container:
            self.container[module.__name__] = Module(
                module,
                self.container,
                extensions=self.extensions,
                context=self.context,
                defer_unselected_imports=self.defer_unselected_imports,
                definition_filter=self.definition_filter,
                library_mappings=self.library_mappings,
                backend=self.backend,
            ).build()
        imported = self.container[module.__name__].search(source_name)
        self.scope.add(imported, local_name)
        self.imported.setdefault(module.__name__, []).append((imported, local_name))


class ModuleAlias(Object):
    def __init__(self, name: str, target: types.ModuleType, container: Module):
        super().__init__(name, container.scope, container)
        self.py_module = target
        self._target = container.container.get(target.__name__)
        if self._target is None and not container.defer_unselected_imports:
            self._target = self.resolve_target()
        self.member_aliases: dict[Object, str] = {}

    def resolve_target(self) -> Module:
        if self._target is not None:
            return self._target
        container = self.container
        if self.py_module is builtins:
            # The host C module has no Python source to analyze. Qualified
            # access uses the selected backend's canonical builtin declarations,
            # independent of same-named application definitions.
            self._target = container.scope.BUILTINS.module
            return self._target
        package = container.container
        # A from-import may have materialized this module since the lazy
        # alias was created. Reuse its objects and state instead of rebuilding.
        if target := package.get(self.py_module.__name__):
            self._target = target
            return target
        target = Module(
            self.py_module,
            package,
            extensions=container.extensions,
            context=container.context,
            defer_unselected_imports=container.defer_unselected_imports,
            definition_filter=container.definition_filter,
            library_mappings=container.library_mappings,
            backend=container.backend,
        ).build()
        package[self.py_module.__name__] = target
        self._target = target
        return target

    @property
    def target(self) -> Module:
        return self.resolve_target()

    @property
    def py_obj(self):
        return self.py_module

    @property
    def type(self):
        return self

    @property
    def node(self):
        return []

    def find(self, name):
        if self.py_module is builtins and not hasattr(builtins, name):
            # Backend-only declarations are not public members of builtins.
            raise NameError(f"Can't find {name} in module builtins.")
        if member := self.target.scope.names.get(name):
            if isinstance(member, (DeferredImport, DeferredDefinition, DeferredValue)):
                return member.resolve()
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
        self._recursive_members = False
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
        if self._recursive_members:
            # Expand named members for semantic consumers without discarding
            # declared edges needed by identity and explicit union inclusion.
            pending = list(reversed(tuple(self._types.values())))
            flattened, seen = {}, set()
            while pending:
                member = pending.pop()
                if isinstance(member, RecursiveTypeAlias) and member.target is not None:
                    if member in seen:
                        continue
                    seen.add(member)
                    pending.extend(reversed(tuple(member.types)))
                else:
                    flattened.setdefault(union_type_key(member), member)
            return tuple(flattened.values())
        return self._types.values()

    @property
    def first(self):
        return next(iter(self.types))

    @property
    def type(self):
        if len(self.types) == 1:
            return self.first
        return self

    def add(self, cls: Class | UnionType):
        if isinstance(cls, RecursiveTypeAlias):
            # Keep explicit inclusion even after binding (B = A | None).
            # Semantic consumers expand through types, while identity and
            # annotation spelling retain the declared edge in either order.
            self._types.setdefault(union_type_key(cls), cls)
            self._recursive_members = True
            return
        if isinstance(cls, UnionType):
            for member in cls._types.values():
                self.add(member)
            return
        self._types.setdefault(union_type_key(cls), cls)

    def reassign(self, name, *args, **kwargs):
        return UnionType(name, self.types)

    def to_annotation_str(self, delim="|"):
        return delim.join(t.to_annotation_str() for t in self._types.values())

    @property
    def annotation(self):
        or_ = None
        for t in self._types.values():
            if or_ is None:
                or_ = t.annotation
            else:
                or_ = ast.BinOp(left=or_, op=ast.BitOr(), right=t.annotation)
        assert or_, "UnionType is empty"
        return or_


class RecursiveTypeAlias(UnionType):
    """Named cycle edge; type identity and spelling remain finite after binding."""

    def __init__(self, alias: TypeAliasValue):
        super().__init__(alias.name)
        self.alias = alias
        self.target = None

    def bind(self, target):
        pending, seen = [target], set()
        while pending:
            member = pending.pop()
            if member is self:
                raise TypeError(f"Recursive type alias {self.name!r} must pass through a container")
            if isinstance(member, UnionType) and id(member) not in seen:
                seen.add(id(member))
                if isinstance(member, RecursiveTypeAlias):
                    if member.target is not None:
                        pending.append(member.target)
                else:
                    pending.extend(member._types.values())
        self.target = target

    @property
    def types(self):
        if self.target is None:
            return ()
        return self.target.types if isinstance(self.target, UnionType) else (self.target,)

    @property
    def type(self):
        return self

    @property
    def py_obj(self):
        return self.alias.py_obj

    def to_annotation_str(self, delim="|"):
        return self.name

    @property
    def annotation(self):
        return Name(self, ctx=ast.Load())


def inline_call_arguments(
    arg_strs: list[str],
    arg_types: list[object],
    arg_formats: list[object],
    keyword_strs: dict[str, str] | None,
    inline_dependencies: dict[str, str] | None,
    self_format=None,
    result_format=None,
    arg_representations=None,
    arg_item_representations=None,
    arg_item_formats=None,
) -> dict[str, object]:
    args_joined = ", ".join(arg_strs)
    args = {
        "_arg_strs": list(arg_strs),
        "_arg_types": list(arg_types),
        "_arg_formats": list(arg_formats),
        "_arg_representations": list(arg_representations or ()),
        "_arg_item_representations": list(arg_item_representations or ()),
        "_arg_item_formats": list(arg_item_formats or ()),
        "_keyword_strs": keyword_strs or {},
        "_args_joined": args_joined,
        "_args_suffix": f", {args_joined}" if args_joined else "",
        "_self_format": self_format,
        "_result_format": result_format,
    }
    args.update(keyword_strs or {})
    args.update(inline_dependencies or {})
    return args


class Class(Object):
    scope: ClassScope
    library_info: LibraryClassInfo | None = None

    def __init__(
        self,
        cls: type,
        container: Module,
        assigned_types: dict[str, Class] = None,
        name: str = None,
        tuple_variadic: bool = False,
    ):
        super().__init__(name or cls.__name__, ClassScope(container.scope), container)
        self.generic_types = assigned_types
        self.generic_name = cls.__name__
        self.tuple_variadic = tuple_variadic
        if container.scope.is_builtins:
            self.generic_name = self.generic_name.removeprefix("_")
        if assigned_types:
            for type_name, type_cls in assigned_types.items():
                self.scope.add(type_cls, type_name)
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = cls
        # Resolve library policy only for reached classes, before looking up
        # bases: foreign parameterized bases may have no Python scope name.
        try:
            self.library_info = container.library_mappings.class_info(cls)
        except TypeError as error:
            container.context.definition_error(
                cls, DiagnosticCode.UNSUPPORTED_SYNTAX, str(error),
            )
        self.is_dataclass = dataclasses.is_dataclass(cls)
        self.is_frozen_dataclass = bool(
            self.is_dataclass and cls.__dataclass_params__.frozen
        )
        self._self = Instance("self", self, self.scope, self)
        self.client_defaults: dict[str, ast.expr] = {}
        self.client_required: tuple[str, ...] = ()
        self.client_fields: dict[str, Class | UnionType] = {}
        self.client_model_dependencies: set[Class] = set()
        self.client_model_registry_required = False
        self.field_declarations: dict[str, Class | UnionType] = {}
        self.field_representations = {}
        self.field_declaration_nodes: dict[str, ast.expr] = {}
        self.field_value_nodes: dict[str, ast.expr] = {}
        self.field_initializer_types: dict[str, Class | UnionType] = {}
        self.field_initializer_representations: dict[
            str,
            ValueRepresentation | None,
        ] = {}
        self.static_initializers: dict[str, ast.expr] = {}
        self.subclasses = []
        self.runtime_super_dependency: Class | None = None
        self.runtime_super_alias: str | None = None
        if self.name == "object" and getattr(cls, "__builtin__", False):
            self.super = None
        elif not container.scope.is_builtins and (cls.__base__ is builtins.object or cls.__base__ is Generic):
            # An implicit Python base is canonical, not a lookup of the name
            # "object" in an application that may itself define that class.
            self.super = ModuleScope.BUILTINS.scope.search("object")
        elif cls.__base__ is Generic:
            self.super = self.search("object")
        else:
            base_name = cls.__base__.__name__
            if container.scope.is_builtins:
                base_name = base_name.removeprefix("_")
            mapped_base = container.library_mappings.resolve(cls.__base__)
            if mapped_base is not cls.__base__:
                # A module-qualified/aliased library base need not have its
                # original name in this module. Resolve the mapped declaration
                # by identity rather than accidentally selecting a namesake.
                self.super = resolve_imported(mapped_base, container, base_name)
            else:
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
                # The base is already mapped to the active backend; only its
                # arguments need annotation resolution, including nesting and
                # tuple's Ellipsis marker (which is not itself a type).
                arguments = generic_base.__args__
                variadic = self.super.name == "tuple" and arguments[-1:] == (Ellipsis,)
                if variadic:
                    arguments = arguments[:-1]
                while True:
                    try:
                        generic_types = [resolve_python_annotation(arg, self.scope) for arg in arguments]
                        break
                    except DependencyError as dependency:
                        if dependency.class_or_func not in container.type_dependencies:
                            container.type_dependencies.append(dependency.class_or_func)
                try:
                    self.super = self.super(*generic_types, tuple_variadic=variadic)
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
        elif self.super is not None and self.super.generic_types:
            base = Name(self.super)
        else:
            base = self.super.annotation if self.super is not None else None
        return ClassDef(
            self,
            bases=[base] if base is not None and not (
                self.super.name == "object" and self.super.container.scope.is_builtins
            ) else [],
            body=body,
            keywords=[],
            decorator_list=[],
        )

    @property
    def annotation(self):
        if self.generic_types:
            elts = [t.annotation for t in self.generic_types.values()]
            if self.generic_name == "tuple" and self.tuple_variadic:
                elts.append(ast.Constant(value=Ellipsis))
            slice = ast.Tuple(elts=elts) if len(elts) > 1 else elts[0]
            return ast.Subscript(value=ast.Name(id=self.generic_name), slice=slice)
        elif self.generic_types is not None:
            # A zero-parameter specialization (tuple__) has no source name
            # to resolve. Retain its class just as other typed references do.
            return Name(self)
        else:
            return ast.Name(id=self.name)

    def to_annotation_str(self, *args, **kwargs):
        return ast.unparse(self.annotation)

    @staticmethod
    def is_generic(py_cls):
        return bool(py_cls.__type_params__)

    @property
    def inline_decorator(self):
        if is_inline_class(self.py_cls):
            return self
        return self.find("__init__").inline_decorator

    @property
    def inline_constructor(self) -> Function | None:
        constructor = self.find_attrs("__init__", search_bases=False)
        return constructor if isinstance(constructor, Function) else None

    def rewrite_call(
        self,
        arg_strs: list[str],
        arg_types: list[Class | UnionType],
        arg_formats: list[object],
        self_=None,
        *,
        keyword_strs: dict[str, str] | None = None,
        inline_dependencies: dict[str, str] | None = None,
        self_format=None,
        result_format=None,
        arg_representations=None,
        arg_item_representations=None,
        arg_item_formats=None,
    ):
        implementation = own_js_metadata(self.py_cls, "implementation")
        rewrite = implementation.value if implementation is not None else None
        assert rewrite is not None
        if self.inline_constructor is not None:
            return self.inline_constructor.rewrite_call(
                arg_strs,
                arg_types,
                arg_formats,
                self_,
                keyword_strs=keyword_strs,
                inline_dependencies=inline_dependencies,
                self_format=self_format,
                result_format=result_format,
                arg_representations=arg_representations,
                arg_item_representations=arg_item_representations,
                arg_item_formats=arg_item_formats,
                rewrite=rewrite,
            )
        args = inline_call_arguments(
            arg_strs,
            arg_types,
            arg_formats,
            keyword_strs,
            inline_dependencies,
            self_format,
            result_format,
            arg_representations,
            arg_item_representations,
            arg_item_formats,
        )
        return rewrite(**args)

    @classmethod
    def from_py_cls(
        cls,
        py_cls: type,
        container: Module,
        *,
        emitted_name: str | None = None,
    ):
        runtime_bases = tuple(
            base for base in py_cls.__bases__ if base is not Generic
        )
        inline_bases = tuple(
            base for base in runtime_bases if is_inline_class(base)
        )
        if inline_bases:
            names = ", ".join(base.__name__ for base in inline_bases)
            container.context.definition_error(
                py_cls,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Class {py_cls.__name__!r} cannot inherit from inline class "
                f"{names!r}",
                help=(
                    "Use composition, or make the base an ordinary class with "
                    "runtime JavaScript identity."
                ),
            )
        if len(runtime_bases) > 1:
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
        class_node = self.container.class_definitions.get(self.py_cls.__name__)
        info = self.library_info
        if info is not None:
            for name, imported in info.imports.items():
                imported = self.container.library_mappings.resolve(imported)
                traverse_imported(name, imported, self.container)
        (
            self.field_declaration_nodes,
            self.field_value_nodes,
        ) = _class_field_nodes(class_node)
        local_annotations = annotationlib.get_annotations(
            self.py_cls,
            format=annotationlib.Format.FORWARDREF,
        )
        if info is not None and info.opaque:
            local_annotations = info.annotations
            self.field_value_nodes = {}
        native_class_fields = {}
        annotations = {} if info is not None and info.opaque else dict(
            getattr(self.py_cls, "__pyjs_instance_annotations__", {})
        )
        for name, annotation in local_annotations.items():
            annotation = _evaluate_class_annotation(annotation, self.py_cls)
            class_variable = typing.get_origin(annotation) is typing.ClassVar
            if class_variable:
                annotation = typing.get_args(annotation)[0]
            try:
                self.field_declarations[name] = self.resolve_field_annotation(annotation)
                self.field_representations[name] = annotation_representation(annotation)
            except TypeError as error:
                node = self.field_declaration_nodes.get(name)
                if node is not None and self.container.source_fragment is not None:
                    self.container.context.error(self.container.source_fragment, node,
                                                 DiagnosticCode.UNSUPPORTED_SYNTAX, str(error))
                self.container.context.definition_error(self.py_cls, DiagnosticCode.UNSUPPORTED_SYNTAX, str(error))
            metadata = (
                typing.get_args(annotation)[1:]
                if typing.get_origin(annotation) is typing.Annotated
                else ()
            )
            if class_variable and any(isinstance(value, JVMField) for value in metadata):
                native_class_fields[name] = self.field_declarations[name]
            if not class_variable and (
                name not in self.field_value_nodes
                or any(isinstance(value, JVMField) for value in metadata)
            ):
                annotations.setdefault(name, annotation)

        source_overrides = {}
        skip_names = set(vars(self.py_cls)) if info is not None and info.opaque else set()
        if issubclass(self.py_cls, enum.Enum):
            source_names = set(self.field_value_nodes)
            if class_node is not None:
                source_names.update(statement.name for statement in class_node.body
                                    if isinstance(statement, FunctionNode))
            # EnumType injects CPython bookkeeping and scalar dunders absent
            # from the source. Analyze the user's declarations, not those
            # metaclass internals; backend enum models supply their semantics.
            skip_names.update(vars(self.py_cls).keys() - source_names)
            # An explicit alias of the inherited scalar descriptor is not a
            # new method. Let the mapped base supply it, just as for the
            # EnumType-injected alias, rather than analyzing a C descriptor.
            skip_names.update(name for name, value in vars(self.py_cls).items()
                              if inspect.ismethoddescriptor(value)
                              and value is getattr(self.py_cls.__base__, name, None))
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
                try:
                    source_overrides["__init__"] = _dataclass_init_source(self.py_cls, fields)
                except TypeError as error:
                    self.container.context.definition_error(
                        self.py_cls, DiagnosticCode.UNSUPPORTED_SYNTAX, str(error))
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
            # Frozen slots dataclasses install CPython pickle helpers, not
            # application methods. Preserve explicitly authored replacements.
            for method_name in ("__getstate__", "__setstate__"):
                method = vars(self.py_cls).get(method_name)
                if getattr(method, "__module__", None) == "dataclasses":
                    skip_names.add(method_name)
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
        for name, value_type in native_class_fields.items():
            if self.find_attrs(name, search_bases=False) is None:
                # Reference-valued native constants have no meaningful Python
                # placeholder (generated declarations use None). Their type is
                # the explicit field annotation, not the placeholder's type.
                self.add(value_type(name, self.scope, self, py_to_ast(None), None))
        if info is not None:
            for name, source in info.methods.items():
                Function.from_py_func(
                    inspect.getattr_static(self.py_cls, name), self, emitted_name=name,
                    source_override=source, load_overloads=False,
                )
        for name, initializer in self.field_value_nodes.items():
            field = self.find_attrs(name, search_bases=False)
            if not isinstance(field, Instance) or field.static_value is None:
                continue
            self.field_initializer_types[name] = field.cls
            self.field_initializer_representations[name] = field.representation
            representation = self.field_representations.get(name)
            if name in self.field_declarations:
                field.cls = self.field_declarations[name]
                apply_representation(field, representation)
            try:
                py_to_ast(field.py_value)
            except TypeError:
                field.static_value = initializer
                self.static_initializers[name] = initializer
            else:
                if representation is not None:
                    field.static_value = initializer
                    self.static_initializers[name] = initializer
        if info is not None:
            annotations.update(info.annotations)
        for name, annotation in annotations.items():
            value_type = self.resolve_field_annotation(annotation)
            if (
                info is not None
                and not info.opaque
                and name in info.annotations
                and not is_supported_client_field_type(value_type)
            ):
                raise TypeError(
                    f"{self.py_cls.__name__}.{name} uses unsupported client "
                    f"field type {value_type.to_annotation_str()}."
                )
            value = value_type(name, self.scope, self._self)
            # A class-body instance annotation owns the same shared storage
            # contract as self.field: T in __init__, including subclass writes.
            value.has_declared_type = True
            apply_representation(value, annotation_representation(annotation))
            if info is not None and not info.opaque and name in info.annotations:
                self.client_fields[name] = value_type
                self.client_model_dependencies.update(client_model_types(value_type))
            dependency = js_metadata(
                self.py_cls,
                "member_dependencies",
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

    def resolve_field_annotation(self, annotation) -> Class | UnionType:
        ensure_annotation_dependencies(annotation, self.container)
        while True:
            try:
                value_type = resolve_python_annotation(annotation, self.scope)
                assert isinstance(value_type, (Class, UnionType))
                return value_type
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
        parameter_representations: tuple[ValueRepresentation | None, ...] | None = None,
        return_representation: ValueRepresentation | None = None,
        *,
        minimum_arguments: int | None = None,
        required_keywords: tuple[str, ...] = (),
    ):
        Object.__init__(self, "callable", ClassScope(base.scope), base.container)
        self.parameter_types = parameter_types
        self.return_type = return_type
        self.parameter_representations = parameter_representations
        self.return_representation = return_representation
        self.minimum_arguments = len(parameter_types or ()) if minimum_arguments is None else minimum_arguments
        self.required_keywords = required_keywords
        self.generic_types = None
        self.generic_name = "Callable"
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = base.py_cls
        self._self = Instance("self", self, self.scope, self)
        self.super = base
        self.subclasses = []
        self.runtime_super_dependency = None
        self.runtime_super_alias = None

    def accepts_arity(self, count: int) -> bool:
        return not self.required_keywords and (
            self.parameter_types is None
            or self.minimum_arguments <= count <= len(self.parameter_types)
        )

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
    if isinstance(value_type, RecursiveTypeAlias):
        return "RecursiveAlias", id(value_type.alias)
    if isinstance(value_type, UnionType):
        # Structural keys keep named edges; semantic member expansion may
        # revisit this very union through a container (list[Tree | None]).
        return "Union", frozenset(union_type_key(member) for member in value_type._types.values())
    if isinstance(value_type, LiteralClass):
        return "Literal", value_type.values
    if isinstance(value_type, CallableClass):
        return (
            "Callable",
            None
            if value_type.parameter_types is None
            else tuple(union_type_key(value) for value in value_type.parameter_types),
            union_type_key(value_type.return_type),
            value_type.parameter_representations,
            value_type.return_representation,
            value_type.minimum_arguments,
            value_type.required_keywords,
        )
    if isinstance(value_type, TypeVariableClass):
        return "TypeVar", id(value_type)
    # Names are presentation, not nominal identity: unrelated declarations can
    # share a spelling, including an application class and a builtin model.
    arguments = getattr(value_type, "generic_types", None)
    return ("Class", value_type.py_cls,
            None if arguments is None else frozenset((name, union_type_key(member))
                                                     for name, member in arguments.items()),
            getattr(value_type, "tuple_variadic", False))


def specialization_cache_key(value_type: Class | UnionType):
    if isinstance(value_type, RecursiveTypeAlias):
        return "RecursiveAlias", id(value_type.alias)
    if isinstance(value_type, UnionType):
        # Specializations retain ordered type arguments beside positional
        # representation metadata. Unlike semantic union identity, this cache
        # must not substitute a differently ordered union from an earlier use.
        return (
            "Union",
            tuple(
                specialization_cache_key(member) for member in value_type._types.values()
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
            value_type.parameter_representations,
            value_type.return_representation,
            value_type.minimum_arguments,
            value_type.required_keywords,
        )
    return id(value_type)


def specialization_type_name(value_type: Class | UnionType) -> str:
    if isinstance(value_type, RecursiveTypeAlias):
        return f"{value_type.alias.container.name.replace('.', '_')}__{value_type.name}"
    if isinstance(value_type, UnionType):
        return "U".join(specialization_type_name(member) for member in value_type._types.values())
    if isinstance(value_type, LiteralClass):
        values = "_".join(value.encode().hex() or "empty" for value in value_type.values)
        return f"Literal__{values}"
    if isinstance(value_type, CallableClass):
        parameters = "any"
        if value_type.parameter_types is not None:
            parameters = (
                "_".join(
                    specialization_type_name(parameter)
                    for parameter in value_type.parameter_types
                )
                or "none"
            )
        result = specialization_type_name(value_type.return_type)
        name = f"Callable__{parameters}__{result}"
        if value_type.parameter_types is not None and value_type.minimum_arguments != len(value_type.parameter_types):
            name += f"__min{value_type.minimum_arguments}"
        if value_type.required_keywords:
            name += "__kw_" + "_".join(value_type.required_keywords)
        return name
    if isinstance(value_type, TypeVariableClass):
        return value_type.name
    if (not value_type.container.scope.is_builtins
            and value_type.generic_name in value_type.container.scope.BUILTINS.scope.names):
        # Box[application int] and Box[builtin int] are different layouts.
        # Keep familiar builtin spellings, qualifying their application
        # namesakes so generated class/method symbols cannot alias them.
        return f"{value_type.container.name.replace('.', '_')}__{value_type.name}"
    return value_type.name


def ensure_annotation_dependencies(annotation, module: Module):
    if annotation is typing.Any:
        return
    if numeric_format(annotation) is not None:
        return
    if (item := array_item(annotation)) is not None:
        ensure_annotation_dependencies(item, module)
        return
    pydantic_generic = getattr(annotation, "__pydantic_generic_metadata__", None)
    if pydantic_generic and pydantic_generic.get("origin") is not None:
        ensure_annotation_dependencies(pydantic_generic["origin"], module)
        for value in pydantic_generic["args"]:
            ensure_annotation_dependencies(value, module)
        return
    origin = typing.get_origin(annotation)
    if origin is not None:
        if origin is Callable:
            parameters, return_annotation = typing.get_args(annotation)
            if parameters is not Ellipsis:
                for parameter in parameters:
                    ensure_annotation_dependencies(parameter, module)
            ensure_annotation_dependencies(return_annotation, module)
            return
        if (
            origin not in (types.UnionType, typing.Union)
            and origin.__name__ not in GENERIC_TYPE_ALIASES
        ):
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
    if annotation is None or annotation is type(None):
        return scope.search("NoneType")
    if annotation is typing.Any:
        return scope.search("object")
    if isinstance(annotation, typing.TypeAliasType):
        while scope.parent is not None:
            scope = scope.parent
        module = scope.module
        alias = module.type_aliases.get(annotation)
        if alias is None:
            alias = resolve_imported(annotation, module)
        return alias.resolve_type()
    if (representation := numeric_format(annotation)) is not None:
        return scope.search("int" if representation.kind == "integer" else "float")
    if (item := array_item(annotation)) is not None:
        generic = scope.search("list")
        assert isinstance(generic, GenericClass)
        return generic(resolve_python_annotation(item, scope))
    if isinstance(annotation, str):
        resolved = scope.search(annotation)
        if isinstance(resolved, TypeAliasValue):
            return resolved.resolve_type()
        return resolved
    if isinstance(annotation, annotationlib.ForwardRef):
        return resolve_python_annotation(annotation.__forward_arg__, scope)
    pydantic_generic = getattr(annotation, "__pydantic_generic_metadata__", None)
    if pydantic_generic and pydantic_generic.get("origin") is not None:
        generic = scope.search(pydantic_generic["origin"].__name__)
        assert isinstance(generic, GenericClass)
        return generic(
            *[
                resolve_python_annotation(value, scope)
                for value in pydantic_generic["args"]
            ]
        )
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return literal_type(typing.get_args(annotation), scope)
    if origin is typing.Annotated:
        return resolve_python_annotation(typing.get_args(annotation)[0], scope)
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
        parameter_representations = None
        if parameters is not Ellipsis:
            parameter_types = tuple(
                resolve_python_annotation(value, scope) for value in parameters
            )
            parameter_representations = tuple(
                annotation_representation(value) for value in parameters
            )
        base = scope.search("callable")
        assert isinstance(base, Class)
        return CallableClass(
            parameter_types,
            resolve_python_annotation(return_annotation, scope),
            base,
            parameter_representations,
            annotation_representation(return_annotation),
        )
    if origin is not None:
        generic_name = GENERIC_TYPE_ALIASES.get(origin.__name__, origin.__name__)
        # Evaluated builtin annotations retain object identity even when the
        # source module shadows their spelling (for example Set = set).
        annotation_scope = ModuleScope.BUILTINS.scope if origin.__module__ == "builtins" else scope
        generic = annotation_scope.search(generic_name)
        assert isinstance(generic, GenericClass)
        args = typing.get_args(annotation)
        tuple_variadic = origin is tuple and args[-1:] == (Ellipsis,)
        if tuple_variadic:
            args = args[:-1]
        return generic(
            *[
                resolve_python_annotation(value, scope)
                for value in args
            ],
            tuple_variadic=tuple_variadic,
        )
    annotation_scope = ModuleScope.BUILTINS.scope if annotation.__module__ == "builtins" else scope
    resolved = annotation_scope.search(annotation.__name__)
    if isinstance(resolved, TypeAliasValue):
        return resolved.resolve_type()
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
    if isinstance(left, RecursiveTypeAlias) or isinstance(right, RecursiveTypeAlias):
        return left is right
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
        if left.py_cls is not right.py_cls or left.generic_name != right.generic_name:
            return False
        if (
            left.generic_name == "tuple"
            and left.tuple_variadic != right.tuple_variadic
        ):
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


def client_type_descriptor(value_type: Class | UnionType):
    if isinstance(value_type, UnionType):
        return [
            "union",
            *(client_type_descriptor(member) for member in value_type.types),
        ]
    if isinstance(value_type, LiteralClass):
        return ["literal", *value_type.values]
    if is_client_model_type(value_type):
        return ["model", f"{value_type.container.name}.{value_type.name}"]
    type_name = value_type.generic_name or value_type.name
    if type_name in {"dict", "list", "set", "tuple"}:
        return [
            type_name,
            *(
                client_type_descriptor(member)
                for member in value_type.generic_types.values()
            ),
        ]
    return type_name


def is_supported_client_field_type(value_type: Class | UnionType) -> bool:
    if isinstance(value_type, UnionType):
        return all(
            is_supported_client_field_type(member)
            for member in value_type.types
        )
    if isinstance(value_type, TypeVariableClass):
        return True
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


def client_result_requires_decoding(value_type: Class | UnionType) -> bool:
    if isinstance(value_type, UnionType):
        return any(
            client_result_requires_decoding(member) for member in value_type.types
        )
    if is_client_model_type(value_type):
        return True
    type_name = value_type.generic_name or value_type.name
    if type_name in {"Date", "dict", "set"}:
        return True
    if type_name not in {"list", "tuple"}:
        return False
    return any(
        client_result_requires_decoding(member)
        for member in value_type.generic_types.values()
    )


def is_supported_client_dict_key_type(value_type: Class | UnionType) -> bool:
    if isinstance(value_type, LiteralClass):
        return all(isinstance(value, str) for value in value_type.values)
    if isinstance(value_type, UnionType):
        return False
    if isinstance(value_type, TypeVariableClass):
        return False
    type_name = value_type.generic_name or value_type.name
    return type_name in {"bool", "float", "int", "str"}


def is_supported_client_result_type(value_type: Class | UnionType) -> bool:
    if isinstance(value_type, UnionType):
        if not all(
            is_supported_client_result_type(member) for member in value_type.types
        ):
            return False
        decoded = [
            member
            for member in value_type.types
            if client_result_requires_decoding(member)
        ]
        if not decoded:
            return True
        non_null = [
            member for member in value_type.types if member.name != "NoneType"
        ]
        return len(non_null) == 1 and len(non_null) < len(value_type.types)
    if not is_supported_client_field_type(value_type):
        return False
    if isinstance(value_type, TypeVariableClass):
        return False
    if is_client_model_type(value_type) or isinstance(value_type, LiteralClass):
        return True
    type_name = value_type.generic_name or value_type.name
    if type_name not in {"dict", "list", "set", "tuple"}:
        return True
    members = tuple(value_type.generic_types.values())
    if type_name == "dict":
        if len(members) != 2 or not is_supported_client_dict_key_type(members[0]):
            return False
    elif not members:
        return False
    return all(is_supported_client_result_type(member) for member in members)


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
        builtin_scope = container.scope if container.scope.is_builtins else ModuleScope.BUILTINS.scope
        object_type = builtin_scope.search("object")
        assert isinstance(object_type, Class)
        self.type_parameters = {
            parameter.__name__: TypeVariableClass(parameter, object_type)
            for parameter in cls.__type_params__
        }
        for parameter in self.type_parameters.values():
            self.scope.add(parameter)
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

    def __call__(
        self,
        *args: list[UnionType],
        tuple_variadic: bool = False,
    ) -> Class:
        builtin_tuple = self.name == "tuple" and self.container.scope.is_builtins
        if tuple_variadic and not builtin_tuple:
            raise TypeError("only tuple types can be variadic")
        params = self.generic_params
        if builtin_tuple:
            params = [f"T{i + 1}" for i in range(len(args))]
        assert len(args) == len(params)
        concrete_name = (
            f"{self.name}__{'_'.join(specialization_type_name(arg) for arg in args)}"
        )
        if tuple_variadic:
            concrete_name += "__variadic"

        generics = {}
        for name, arg in zip(params, args, strict=True):
            if isinstance(arg, RecursiveTypeAlias):
                generics[name] = arg
            elif isinstance(arg, UnionType):
                generics[name] = UnionType(name, arg.types)
            else:
                assert isinstance(arg, Class)
                generics[name] = arg

        # Builtin interfaces carry positional representation metadata, so each
        # annotation order needs its own view. Application generics reject
        # represented arguments: equivalent arguments must retain one nominal
        # class (and hence one constructor, method graph and emitted identity).
        # Recurse through nested arguments rather than keying container views
        # by identity, which would split Box[list[int | str]] as well.
        argument_key = (
            specialization_cache_key
            if self.container.scope.is_builtins
            or getattr(self.py_cls, "__pyjs_allow_represented_generics__", False)
            else union_type_key
        )
        cache_key = (
            tuple_variadic,
            *(argument_key(arg) for arg in args),
        )
        concrete_class = self.concrete_classes.get(cache_key)
        if concrete_class is not None:
            return concrete_class

        concrete_class = Class(
            self.py_cls,
            self.container,
            assigned_types=generics,
            name=concrete_name,
            tuple_variadic=tuple_variadic,
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
            if self.name == "tuple" and not arg_types:
                return self()
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
                if self.name == "tuple":
                    return iterable_type
                item_type = UnionType()
                for value_type in iterable_type.generic_types.values():
                    item_type.add(value_type)
                item_type = item_type.type
            elif iterable_type.generic_types and len(iterable_type.generic_types) == 1:
                item_type = next(iter(iterable_type.generic_types.values()))
            else:
                from .iterable_protocol import resolve_iterable_protocol

                protocol = resolve_iterable_protocol(iterable_type, None, self.scope)
                if protocol is None:
                    raise TypeError(
                        f"Cannot infer {self.name} item type from {iterable_type.name}."
                    )
                item_type = protocol.item_type
            return self(
                item_type,
                tuple_variadic=self.name == "tuple",
            )
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
        # staticmethod and classmethod descriptors do not expose __name__.
        named = func.__func__ if isinstance(func, (staticmethod, classmethod)) else func
        super().__init__(named.__name__, FunctionScope(container.scope), container)
        self.py_func = func
        self.cls = container if isinstance(container, Class) else None
        if self.cls is not None:
            self.scope.add(self.cls.super, "super")
        module = container if isinstance(container, Module) else container.container
        builtin_scope = module.scope if module.scope.is_builtins else ModuleScope.BUILTINS.scope
        object_type = builtin_scope.search("object")
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
        self.inferred_return_values = []
        self.set_return_representation(None)
        self.signature_analyzed = False
        self.returns_self = False

        self.is_analyzed = False
        self.params = []
        self.posonly_count = 0
        self.defaults = []
        self.vararg = None
        self.kwonlyargs = []
        self.kw_defaults = []
        self.kwarg = None
        self.body = []
        self.lineno: int = None
        self.original_node: FunctionNode | None = None
        self.source_fragment: SourceFragment | None = None
        self.has_synthetic_source = False
        self.is_async = False
        self.is_generator = False
        self.yield_type: Class | UnionType | None = None
        self.yield_representation: ValueRepresentation | None = None
        self.yield_values = []
        self.send_type: Class | UnionType | None = None
        self.send_representation: ValueRepresentation | None = None
        self.is_partial_client = False
        self.virtual_visited = weakref.WeakSet()
        self.render_visited = weakref.WeakSet()
        self.render_classes: set[Class] = set()
        self.render_virtual_dependencies: set[Function] = set()
        self.hydrate_visited = weakref.WeakSet()
        self.compilation_entry_points: tuple[Function, ...] = ()
        self.compilation_objects: set[Object] = set()
        self.compilation_cleanup: Callable[[], None] | None = None
        self.runtime_dunder_dependencies: set[tuple[Class | UnionType | None, tuple[str, ...]]] = set()
        self.virtual_receiver_dependencies: set[tuple[Function, Class | UnionType]] = set()
        self.runtime_view_sources: set[tuple[Class, Class]] = set()
        self.is_runtime_implementation = False
        self.runtime_source: str | None = None
        self.ir = None
        self.is_property = False
        self.is_property_setter = False
        self.property_setter: Function | None = None
        self.overloads: tuple[Function, ...] = ()

    def set_return_representation(
        self,
        representation: ValueRepresentation | None,
    ) -> None:
        self.return_representation = representation

    @property
    def return_numeric_format(self):
        representation = self.return_representation
        return representation.numeric if representation is not None else None

    @property
    def return_array_format(self):
        representation = self.return_representation
        return representation.array if representation is not None else None

    def reset(self):
        self.is_analyzed = False
        self.signature_analyzed = False
        self.scope.names = {}
        if self.cls is not None:
            self.scope.add(self.cls.super, "super")
        for parameter in self.type_parameters.values():
            self.scope.add(parameter)
        self.params = []
        self.posonly_count = 0
        self.defaults = []
        self.vararg = None
        self.kwonlyargs = []
        self.kw_defaults = []
        self.kwarg = None
        self.body = []
        self.return_type = None
        self.declared_return_type = None
        self.inferred_return_type = None
        self.inferred_return_values = []
        self.set_return_representation(None)
        self.yield_type = None
        self.yield_representation = None
        self.yield_values = []
        self.send_type = None
        self.send_representation = None
        self.returns_self = False
        self.ir = None

    @property
    def py_obj(self):
        return self.py_func

    @property
    def analysis(self):
        return js_metadata(self.py_func, "analysis")

    @property
    def runtime_dunders(self):
        return js_metadata(self.py_func, "runtime_dunders")

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
        module_obj = container if isinstance(container, Module) else container.container
        # A JavaScript client replacement must not replace the Python body
        # when the same function is reached by another compilation target.
        client_implementation = js_metadata(py_func, "client") if module_obj.backend == "js" else None
        client_partial = (
            client_implementation if isinstance(client_implementation, partial) else None
        )
        source_func = (
            py_func if client_partial is not None else client_implementation or py_func
        )
        if source_override is None:
            source, lineno = _function_source(source_func)
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

        if client_partial is not None:
            apply_partial_client(func_def, client_partial, module_obj)
        for extension in module_obj.extensions:
            func_def, imports = extension.transform_function(
                source_func, func_def, source
            )
            for import_name, imported in imports.items():
                traverse_imported(import_name, imported, module_obj)
        if client_partial is not None or module_obj.extensions:
            ast.fix_missing_locations(func_def)

        func = cls(py_func if client_partial is not None else source_func, container)
        public = (
            py_func.__func__
            if isinstance(py_func, (staticmethod, classmethod))
            else py_func
        )
        func.name = emitted_name or public.__name__
        func.is_partial_client = client_partial is not None
        func.has_synthetic_source = source_override is not None
        func.lineno = lineno
        func.original_node = func_def
        wrapper_name = getattr(
            module_obj.py_module,
            "__pyjs_simple_wrapper__",
            None,
        )
        simple_wrapper = source_func is getattr(
            module_obj.py_module,
            wrapper_name or "",
            None,
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
        if (
            source_override is None
            and client_partial is None
            and not module_obj.extensions
        ):
            inspected_func = getattr(source_func, "__func__", source_func)
            func.is_generator = inspect.isgeneratorfunction(
                inspected_func
            ) or inspect.isasyncgenfunction(inspected_func)
        else:
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
            f"Attempting to create function AST for {self.name!r} before it "
            "has been analyzed."
        )
        node_type = AsyncFunctionDef if self.is_async else FunctionDef
        return node_type(
            self,
            args=ast.arguments(
                posonlyargs=self.params[: self.posonly_count],
                args=self.params[self.posonly_count :],
                vararg=self.vararg,
                kwarg=self.kwarg,
                kwonlyargs=self.kwonlyargs,
                defaults=self.defaults,
                kw_defaults=self.kw_defaults,
            ),
            body=self.ir.blocks if self.ir is not None else self.body,
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
        if is_inline_for(self.py_func, "js"):
            return self

    @property
    def inline_call(self):
        implementation = own_js_metadata(self.py_func, "implementation")
        if implementation is not None and implementation.kind == "call":
            return implementation.value

    @property
    def has_source_decorator(self):
        if self.has_synthetic_source:
            return False  # Explicit target source supersedes host JS replacements.
        implementation = own_js_metadata(self.py_func, "implementation")
        return self.runtime_source is not None or (
            implementation is not None and implementation.kind == "source"
        )

    @property
    def has_keep_decorator(self):
        return has_keep_decorator(self.py_func)

    def get_predefined_source(self):
        if self.runtime_source is not None:
            return self.runtime_source
        source = own_js_metadata(self.py_func, "implementation").value
        return source(self) if callable(source) else source

    def rewrite_call(
        self,
        arg_strs: list[str],
        arg_types: list[Class | UnionType],
        arg_formats: list[object],
        self_=None,
        *,
        keyword_strs: dict[str, str] | None = None,
        inline_dependencies: dict[str, str] | None = None,
        rewrite=None,
        self_format=None,
        result_format=None,
        arg_representations=None,
        arg_item_representations=None,
        arg_item_formats=None,
    ):
        implementation = own_js_metadata(self.py_func, "implementation")
        rewrite = rewrite or (
            implementation.value if implementation is not None else None
        )
        assert rewrite is not None, "Forwarded inline calls must be lowered by analysis."
        args = inline_call_arguments(
            arg_strs,
            arg_types,
            arg_formats,
            keyword_strs,
            inline_dependencies,
            self_format,
            result_format,
            arg_representations,
            arg_item_representations,
            arg_item_formats,
        )
        if params := self.params:
            if self.is_method and self.params[0].arg == "self":
                params = params[1:]
            if self.is_static and self.params[0].arg == "cls":
                params = params[1:]
            for arg_str, param in zip(arg_strs, params, strict=False):
                args[param.arg] = arg_str
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
        self.has_declared_type = False
        # A loop may refine the value without changing an existing local's slot.
        # Unlike narrowed_from, this is not a control-flow type proof.
        self.storage_binding = None
        apply_representation(self, None)
        self.member_dependency: Class | None = None
        self.virtual_visited = weakref.WeakSet()

    @property
    def storage_declaration(self):
        """The original physical declaration behind flow-specific bindings."""
        value = self
        while original := (getattr(value, "storage_binding", None)
                           or getattr(value, "narrowed_from", None)):
            value = original
        return value

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
        new.has_declared_type = self.has_declared_type
        new.storage_binding = self.storage_binding
        new.narrowed_from = getattr(self, "narrowed_from", None)
        apply_representation(new, self.representation)
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
        value_numeric = numeric_format(type(value))
        if value_numeric is not None:
            value_type_name = "int" if value_numeric.kind == "integer" else "float"
        value_type = container.search(value_type_name)
        assert isinstance(value_type, Class), "Can't determine type."
        value_ast = None
        if not getattr(value, "__builtin__", False):
            if isinstance(container, Module):
                prepare = getattr(value_type.py_cls, "__pyjs_prepare_client__", None)
                if prepare is not None:
                    prepare()
                value_ast = container.resolve_static_initializer(name)
            if value_ast is None:
                try:
                    value_ast = py_to_ast(value)
                except TypeError:
                    value_ast = Call(
                        value_type, func=Name(value_type), args=[], keywords=[]
                    )
        result = value_type(
            name,
            container.scope,
            container,
            value_ast,
            value,
            is_const=isinstance(container, Module) if is_const is None else is_const,
        )
        apply_representation(result, annotation_representation(type(value)))
        return result


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
        dependency_objects: dict[str, Class | Function] | None = None,
        runtime_methods: tuple[Function, ...] = (),
        runtime_protocols: tuple[tuple[Class | UnionType, tuple[str, ...]], ...] = (),
        generated_methods: tuple[Function, ...] = (),
        generated_virtual_methods: tuple[Function, ...] = (),
        dictionary_keys: tuple[str, ...] | None = None,
        dictionary_optional: frozenset[str] = frozenset(),
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
        self.runtime_protocols = runtime_protocols
        self.generated_methods = generated_methods
        self.generated_virtual_methods = generated_virtual_methods
        self.dictionary_keys = dictionary_keys
        self.dictionary_optional = dictionary_optional
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
        obj: Object | UnionType,
        runtime_dependency: Function | Class | None = None,
        **kwargs,
    ):
        self.obj = obj
        assert isinstance(obj, (Object, UnionType))
        self.runtime_dependency = runtime_dependency
        assert isinstance(self.obj, (Object, UnionType)), f"{self.obj} is not an Object"
        super().__init__(**{"id": obj.name, **kwargs})


def is_lexical_super_call(node: ast.AST, function: Function | None) -> bool:
    """Distinguish the analyzed base binding from a callable named super."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, Name)
            and node.func.id == "super"):
        return False
    while isinstance(function, Function):
        if function.cls is not None:
            return node.func.obj is function.cls.super
        function = function.container
    return False


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


class AnalyzedExpression(ast.expr):
    """Analysis-only splice for a value already visited in this inference pass.

    Syntax-dependent hooks can inspect a receiver and reuse its typed expression
    without recursively analyzing it again. This wrapper never reaches output.
    Unlike EvaluateOnce, it does not introduce a runtime binding.
    """

    # Source-shape walks must not re-enter the already analyzed subtree either.
    _fields = ()

    def __init__(self, value):
        self.value = value
        self.python_node = getattr(value, "python_node", value)
        ast.copy_location(self, value)


class EvaluateOnce(ast.expr):
    _fields = ("value", "body")

    def __init__(
        self,
        obj: Object,
        value: ast.expr,
        body: ast.expr,
        parameter: str,
        **kwargs,
    ):
        self.obj = obj
        self.value = value
        self.body = body
        self.parameter = parameter
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
        property_setter_representations: tuple[object | None, ...] = (),
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
        self.property_setter_representations = property_setter_representations
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


class ChainedCompare(ast.expr):
    _fields = ("operands", "comparisons", "temporaries")

    def __init__(
        self,
        obj: Class,
        operands: list[ast.expr],
        comparisons: list[ast.expr],
        temporaries: list[Name],
        **kwargs,
    ):
        self.obj = obj
        self.operands = operands
        self.comparisons = comparisons
        self.temporaries = temporaries
        assert self.obj.name == "bool"
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
    def __init__(self, obj: Class | UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
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
    def __init__(
        self,
        obj: Class | UnionType,
        value_obj: Object | UnionType,
        **kwargs,
    ):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        self.value_obj = value_obj
        assert isinstance(self.value_obj, (Object, UnionType))
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

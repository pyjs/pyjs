"""Native adaptation of shared synthetic dataclass constructors."""

import ast
import builtins as python_builtins
import dataclasses
import inspect

from pyjs.analysis.objects import Name, resolve_imported
from pyjs.decorators import configure_js, native_operation
from pyjs.python import native as builtins

from .errors import LLVMUnsupported


@native_operation("dataclasses.replace")
def replace[T](obj: T, /, **changes: object) -> T:
    return dataclasses.replace(obj, **changes)


def is_generated_equality(function):
    return (function.name == "__eq__" and function.has_synthetic_source
            and function.cls is not None and dataclasses.is_dataclass(function.cls.py_obj))


def _analyze_replace(call):
    from pyjs.analysis.analyzer import analyzed_value_type
    from pyjs.analysis.objects import Call
    from pyjs.analysis.value_representation import analyzed_representation

    checked = call.dataclass(replace=True)
    record = analyzed_value_type(checked.args[0])
    values = [checked.args[0], *(keyword.value for keyword in checked.keywords)]
    names = [f"__replace{index}" for index in range(len(values))]
    changes = {keyword.arg: names[index + 1] for index, keyword in enumerate(checked.keywords)}
    # An immediately invoked typed lambda evaluates the source and all changes
    # before reading unchanged fields. Its ordinary constructor call supplies
    # reachability, lifetime/rooting, conversions and exception unwinding; there
    # is deliberately no second native allocation or field-copy implementation.
    # replace starts with the caller's changes dict, then appends unchanged
    # fields. An authored **kwargs initializer can observe this ordering.
    keywords = [ast.keyword(arg=name, value=ast.Name(id=value, ctx=ast.Load()))
                for name, value in changes.items()]
    keywords.extend(ast.keyword(arg=field.name, value=ast.Attribute(
        value=ast.Name(id=names[0], ctx=ast.Load()), attr=field.name, ctx=ast.Load()))
        for field in dataclasses.fields(record.py_obj) if field.init and field.name not in changes)
    source = ast.Lambda(
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=name) for name in names],
                           vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=ast.Call(func=Name(record), args=[], keywords=keywords),
    )
    ast.fix_missing_locations(ast.copy_location(source, call.node))
    function = call.visitor.visit_contextual_lambda(
        source, tuple(analyzed_value_type(value) for value in values),
        tuple(analyzed_representation(value) for value in values),
    )
    function.native_replaced_record = record
    result = record("__call_result__", call.visitor.scope, call.visitor.func)
    return ast.copy_location(Call(record, value_obj=result, func=function, args=values, keywords=[]), call.node)


configure_js(replace, analysis=_analyze_replace)


def is_missing(value):
    return (isinstance(value, ast.Call)
            and getattr(getattr(value.func, "obj", None), "py_func", None) is builtins._dataclass_missing
            and not value.args and not value.keywords)


def prepare_initializer(function, node):
    from pyjs.analysis.analyzer import BUILTINS

    if not (node.name == "__init__" and function.has_synthetic_source
            and function.cls is not None and dataclasses.is_dataclass(function.cls.py_obj)):
        return
    # Shared generated source initializes JS `this` through super(). Native
    # allocation already creates the whole object; Python dataclass initializers
    # assign inherited fields without invoking the base initializer.
    match node.body:
        case [ast.Expr(value=ast.Call(
            func=ast.Attribute(value=ast.Call(func=ast.Name(id="super"), args=[], keywords=[]),
                               attr="__init__"), args=[], keywords=[])), *body]:
            node.body = body
    cls = function.cls.py_obj
    for field in dataclasses.fields(cls):
        if (field.init and field.default_factory is not dataclasses.MISSING
                and getattr(function.cls._self.find(field.name).cls, "generic_name", None)
                in {"int", "float", "bool"}):
            raise LLVMUnsupported("native dataclass default factories require reference-valued fields", node)
    factories = {field.name: field.default_factory for field in dataclasses.fields(cls)
                 if field.default_factory is not dataclasses.MISSING}
    for assignment in ast.walk(node):
        if (isinstance(assignment, ast.AnnAssign) and isinstance(assignment.target, ast.Attribute)
                and assignment.target.attr in factories
                and not (isinstance(assignment.value, ast.Name)
                         and assignment.value.id == assignment.target.attr)):
            # A factory's spelling may be shadowed by its field parameter or
            # imported under an alias. The shared generator also uses literals
            # for list/dict/tuple by name; only their actual builtins qualify.
            factory = factories[assignment.target.attr]
            # Within the declaring class body, field(default_factory=method)
            # receives the raw callable descriptor instead of attribute access's
            # unwrapped function. Resolve both spellings by the same identity.
            if isinstance(factory, staticmethod):
                factory = factory.__func__
            if factory in (list, dict, tuple):
                continue
            name = getattr(factory, "__name__", "")
            owner = inspect.getmodule(factory)
            for part in getattr(factory, "__qualname__", "").split(".")[:-1]:
                owner = getattr(owner, part, None)
            declaration = inspect.getattr_static(owner, name, None) if isinstance(owner, type) else None
            if inspect.ismethod(factory) and isinstance(factory.__self__, type):
                # Retain the bound class (including an inheriting subclass),
                # then let ordinary class-attribute analysis supply cls.
                owner = resolve_imported(factory.__self__, function.cls.container)
                factory = ast.Attribute(value=Name(owner), attr=name, ctx=ast.Load())
            elif isinstance(declaration, staticmethod) and declaration.__func__ is factory:
                # A static factory belongs to its class, not a module-level
                # function (or builtin) with the same name.
                factory = Name(resolve_imported(owner, function.cls.container).find_attrs(name))
            else:
                factory = (BUILTINS.search(name)
                           if getattr(python_builtins, name, None) is factory
                           else resolve_imported(factory, function.cls.container))
                factory = Name(factory)
            assignment.value = ast.copy_location(ast.Call(func=factory, args=[], keywords=[]),
                                                  assignment.value)
            ast.fix_missing_locations(assignment.value)
    if "__post_init__" not in vars(cls) and hasattr(cls, "__post_init__"):
        # JS relies on the base constructor for inherited post-init. Native
        # invokes it once after all fields. Inference may revisit this source,
        # so recognize the appended call structurally rather than append again.
        match node.body:
            case [*_, ast.Expr(value=ast.Call(
                func=ast.Attribute(value=ast.Name(id="self"), attr="__post_init__"),
                args=[], keywords=[]))]:
                return
        post_init = ast.Expr(value=ast.Call(
            func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()),
                               attr="__post_init__", ctx=ast.Load()), args=[], keywords=[]))
        node.body.append(ast.fix_missing_locations(ast.copy_location(post_init, node)))

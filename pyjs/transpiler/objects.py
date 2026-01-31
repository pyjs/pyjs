import ast
from typing import Iterable, Generic

from pyjs.decorators import *


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
   "__type_params__",
   "__orig_bases__",
   "__parameters__",
   ""
   # pyjs
} | DECORATIONS


def py_to_ast(value):
    import ast
    if isinstance(value, (bool, int, float, str, js_str, type(None))):
        return ast.Constant(value=value)
    elif isinstance(value, (list, tuple, set)):
        return {
            list: ast.List,
            tuple: ast.Tuple,
            set: ast.Set
        }[type(value)](elts=[py_to_ast(v) for v in value])
    elif isinstance(value, dict):
        return ast.Dict(
            keys=[py_to_ast(k) for k in value.keys()],
            values=[py_to_ast(v) for v in value.values()]
        )
    else:
        raise TypeError(f"Unsupported type: {type(value)}")


def traverse_imported(obj_name: str, obj: object, current_module: 'Module'):
    module_name = obj.__module__
    package = current_module.container
    if module_name not in package:
        package[module_name] = Module(inspect.getmodule(obj), package).build()
    imported_module = package[module_name]
    imported_object = imported_module.search(obj_name)
    current_module.scope.add(imported_object, obj_name)
    current_module.imported.setdefault(module_name, []).append(imported_object)


class Scope:

    def __init__(self, parent=None):
        self.parent: Scope = parent
        self.names = {}

    def search(self, name: str) -> 'Object':
        if value := self.names.get(name):
            return value
        return self.parent.search(name)

    def add(self, thing: 'Object', name: str = None) -> 'Object':
        self.names[name or thing.name] = thing
        return thing


class ModuleScope(Scope):

    BUILTINS: 'Module'

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
    def lookup(self, name: str) -> 'Object':
        if value := self.names.get(name):
            return value
        if not isinstance(self.parent, LocalScope):
            raise NameError(f"Searching local scopes for `{name}` did not yield results.")
        return self.parent.lookup(name)


class FunctionScope(LocalScope):
    pass


class Object:

    def __init__(self, name: str, scope: Scope, container: 'Object' = None):
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

    def add(self, other: 'Object'):
        self.scope.add(other)

    def find(self, name):
        """ Vertical. Find attributes of this object, following any inheritance rules. """
        raise NotImplementedError

    def search(self, name):
        """ Horizontal. Search in scopes, finally checking builtins after all scopes exhausted. """
        return self.scope.search(name)

    def build(self, namespace, container: 'Object', propagate_js=False):
        for name, py_obj in vars(namespace).items():

            if name in IGNORE_NAMES:
                continue

            if inspect.isbuiltin(py_obj):
                continue

            js_attr = getattr(py_obj, "__js__", None)
            if js_attr is False or (js_attr is None and not propagate_js):
                continue

            if isinstance(container, Module) and getattr(py_obj, "__module__", None) not in (container.name, None):
                traverse_imported(name, py_obj, container)
            elif inspect.isclass(py_obj):
                assert isinstance(container, Module), "Classes are only allowed in modules."
                if Class.is_generic(py_obj):
                    GenericClass.from_py_cls(py_obj, container)
                else:
                    Class.from_py_cls(py_obj, container).build()
            elif callable(py_obj) or isinstance(py_obj, (classmethod, staticmethod)):
                Function.from_py_func(py_obj, container)
            else:
                if getattr(py_obj, '__js__', False):
                    container.add(Instance.from_static_value(name, py_obj, container))


class Module(Object):

    scope: ModuleScope

    def __init__(self, module, package, is_builtins: bool=False):
        super().__init__(module.__name__, ModuleScope(is_builtins), package)
        self.py_module = module
        self.imported = {}

    @property
    def py_obj(self):
        return self.py_module

    @property
    def node(self) -> 'ModuleDef':
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
        super().build(self.py_module, self)
        return self


class UnionType:
    def __init__(self, name: str = None, types: Iterable['Class'] = None):
        self.name = name
        self._types: dict[str,Class] = {cls.name:cls for cls in types} if types else {}

    def __call__(self, name, scope, container):
        new = Instance(name, self, scope, container)
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

    def add(self, cls: 'Class'):
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

    def __init__(self, cls: type, container: Module, assigned_types: dict[str,'Class'] = None, name: str = None):
        super().__init__(name or cls.__name__, ClassScope(container.scope), container)
        self.generic_types = assigned_types
        self.generic_name = cls.__name__
        if assigned_types:
            for type_name, type_cls in assigned_types.items():
                self.scope.add(type_cls, type_name)
        self.internal_scope = ClassScope(self.scope)
        self.py_cls = cls
        self._self = Instance("self", self, self.scope, self)
        if self.name == "object" and getattr(cls, "__builtin__", False):
            self.super = None
        elif cls.__base__ is Generic:
            self.super = None
        else:
            self.super: Class = self.search(cls.__base__.__name__)
            assert isinstance(self.super, Class)

    def __call__(self, name, scope, container, ast_value=None, value=None, is_const=None):
        return self._self.reassign(name, scope, container, ast_value=ast_value, value=value, is_const=is_const)

    @property
    def init(self) -> 'Function':
        return self.internal_scope.names.get("__init__", None)

    @property
    def py_obj(self):
        return self.py_cls

    @property
    def type(self):
        return self

    @property
    def node(self) -> ast.ClassDef:
        body = [
            o.node for o in self.internal_scope.names.values()
            if should_include(o)
        ]
        return ClassDef(
            self,
            bases=[self.super.annotation] if (self.super and self.super.name != "object") else [],
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


class GenericClass(Object):
    def __init__(self, cls: type, container: Module):
        super().__init__(cls.__name__, ClassScope(container.scope), container)
        self.py_cls = cls
        self.init_params = None
        if cls_init := getattr(cls, '__init__', None):
            self.init_params = inspect.signature(cls_init).parameters
        self.generic_params = [type_param.__name__ for type_param in cls.__type_params__]
        self.concrete_classes = {}

    @property
    def node(self):
        return [c.node for c in self.concrete_classes.values()]

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
            params = [f"T{i+1}" for i in range(len(args))]
        assert len(args) == len(params)
        concrete_name = f"{self.name}__{'_'.join([arg.to_annotation_str('U') for arg in args])}"

        if concrete_class := self.concrete_classes.get(concrete_name, None):
            return concrete_class

        generics = {}
        for name, arg in zip(params, args):
            if isinstance(arg, UnionType):
                generics[name] = UnionType(name, arg.types)
            else:
                assert isinstance(arg, Class)
                generics[name] = arg

        concrete_class = Class(self.py_cls, self.container, assigned_types=generics, name=concrete_name)
        self.concrete_classes[concrete_name] = concrete_class
        concrete_class.build()
        raise DependencyError(concrete_class)

    def from_call(self, arg_types):
        # TODO: handle different arg schemes other than positional
        assert self.init_params
        param_args = {}
        for arg, param in zip(arg_types, list(self.init_params.values())[1:]):
            param_args[param.annotation.__name__] = arg
        generic_args = [param_args.get(p, None) for p in self.generic_params]
        if not all(generic_args):
            raise TypeError("Concrete type could not be determined from type annotation or value.")
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

        self.is_analyzed = False
        self.params = []
        self.defaults = []
        self.vararg = None
        self.kwarg = None
        self.body = []
        self.lineno: int = None
        self.original_node: ast.FunctionDef = None

    def reset(self):
        self.is_analyzed = False
        self.scope.names = {}
        if self.cls is not None:
            self.scope.add(self.cls.super, "super")
        self.params = []
        self.defaults = []
        self.vararg = None
        self.kwarg = None
        self.body = []
        self.return_type = None

    @property
    def py_obj(self):
        return self.py_func

    @property
    def type(self):
        return self.return_type

    @classmethod
    def from_py_func(cls, py_func: callable, container: Module | Class):
        py_func = getattr(py_func, "__js_replace__", py_func)
        lines, lineno = inspect.getsourcelines(py_func)
        is_method = isinstance(container, Class)

        if is_method:
            # to preserve indentation for sourcemap and still make the function parseable
            lines.insert(0, f"class {container.name}:\n")
            lineno -= 1  # we need to subtract the dummy line from total line offset

        module = ast.parse(''.join(lines))
        assert isinstance(module, ast.Module)

        if is_method:
            module = module.body[0]
            assert isinstance(module, ast.ClassDef)

        func_def = module.body[0]
        assert isinstance(func_def, ast.FunctionDef)

        func = cls(py_func, container)
        func.lineno = lineno
        func.original_node = func_def

        container.add(func)
        return func

    @property
    def node(self) -> ast.FunctionDef:
        assert self.is_analyzed, "Attempting to create ast.FunctionDef but haven't analyzed yet."
        return FunctionDef(
            self,
            args=ast.arguments(
                args=self.params,
                vararg=self.vararg,
                kwarg=self.kwarg,
                posonlyargs=[],
                kwonlyargs=[],
                defaults=self.defaults
            ),
            body=self.body,
            returns=None if self.return_type is None else self.return_type.annotation,
            type_params=[],
            decorator_list=[],
            lineno=self.lineno,
            col_offset=self.original_node.col_offset,
        )

    def lookup(self, name):
        """ Find a name restricted to the current scope. """
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

    def rewrite_call(self, arg_strs: list[str], arg_types: list[Class], self_=None):
        rewrite = self.py_func.__js_rewrite_call_site__
        args = {
            "_arg_strs": [],
            "_arg_types": [],
        }
        if params := self.params:
            if self.is_method and self.params[0].arg == "self":
                params = params[1:]
            if self.is_static and self.params[0].arg == "cls":
                params = params[1:]
            for arg_str, arg_type, param in zip(arg_strs, arg_types, params):
                args["_arg_strs"].append(arg_str)
                args["_arg_types"].append(arg_type)
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
    def __init__(self, class_or_func: Class|Function):
        self.class_or_func = class_or_func


class Instance(Object):

    def __init__(
        self, name: str, cls: Class, scope: Scope,
        container: Object, static_value: ast.expr = None,
        py_obj = None, is_const = False
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

    def reassign(self, name: str, scope: Scope, container: Object, ast_value=None, value=None, is_const=None):
        new = Instance(name, self.cls, scope, container, static_value=ast_value, py_obj=value, is_const=is_const)
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
        assign = ast.AnnAssign(
            target=Name(self),
            annotation=ast.Name(id="__const__" if self.is_const else "__static__"),
            value=self.static_value,
            simple=True,
        )
        assign.obj = self
        return assign

    @classmethod
    def from_static_value(cls, name, value, container):
        value_type_name = type(value).__name__
        if type(value) is js_str:
            value_type_name = "str"
        value_type = container.search(value_type_name)
        assert isinstance(value_type, Class), "Can't determine type."
        value_ast = None
        if not getattr(value, '__builtin__', False):
            try:
                value_ast = py_to_ast(value)
            except TypeError:
                args = []
                for arg in getattr(value, "__static_args__", []):
                    args.append(py_to_ast(arg))
                value_ast = Call(
                    value_type,
                    func=Name(value_type),
                    args=args,
                    keywords=[]
                )
        return value_type(
            name, container.scope, container, value_ast, value, is_const=isinstance(container, Module)
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


class Call(ast.Call):
    def __init__(self, obj: Class|Function, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, Function, type(None))), f"{self.obj} is not a Class or Function"
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
    def __init__(self, obj: Function|UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        super().__init__(**kwargs)


class UnaryOp(ast.BinOp):
    def __init__(self, obj: Function|UnionType, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, (Class, UnionType))
        super().__init__(**kwargs)


class JoinedStr(ast.JoinedStr):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class Subscript(ast.Subscript):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
        super().__init__(**kwargs)


class Starred(ast.Starred):
    def __init__(self, obj: Class, **kwargs):
        self.obj = obj
        assert isinstance(self.obj, Class)
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


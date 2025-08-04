from typing import Iterator
from graphlib import TopologicalSorter

from .objects import *


class InferenceVisitor(ast.NodeVisitor):

    def __init__(self, func: Function, scope: LocalScope = None):
        self.func = func
        self.scope = scope or func.scope

    def narrow(self):
        return type(self)(self.func, LocalScope(self.scope))

    def visit_body(self, statements):
        body = []
        narrow_visitor = self
        for statement in statements:
            stmt = narrow_visitor.visit(statement)
            if isinstance(stmt, ast.Assert):
                test = stmt.test
                if (
                    isinstance(test, ast.Call) and
                    isinstance(test.func, ast.Name) and
                    test.func.id == "isinstance"
                ):
                    args = test.args
                    assert len(args) == 2
                    assert all(isinstance(a, ast.Name) for a in args)
                    value_name = args[0].id
                    value_type = args[1].obj
                    assert isinstance(value_type, Class)
                    narrow_visitor = self.narrow()
                    narrow_visitor.scope.add(
                        value_type(value_name, narrow_visitor.scope, self.func)
                    )
            elif isinstance(stmt, list):
                body.extend(stmt)
            else:
                body.append(stmt)
        return body

    # region assignment & lookup

    def make_assignment(self, target, value_type: Class, value):
        if isinstance(target, ast.Attribute):
            try:
                target = self.visit(target)
            except (NameError, DependencyError) as e:
                parent = self.visit(target.value)
                assert isinstance(parent.obj, Instance)
                if parent.obj.name == "self":
                    attr = value_type(target.attr, parent.obj.scope, parent.obj)
                    parent.obj.add(attr)
                    target = Attribute(
                        attr,
                        value=parent,
                        attr=target.attr,
                        lineno=target.lineno
                    )
                else:
                    raise e
            if target.obj.cls is not value_type:
                # check if the attribute was found on a super()
                # instead of in the current instance self, child
                # class should be able to redefine an attribute
                # with a different type, otherwise raise error
                current_self = target.value.obj
                other_self = target.obj.container
                assert isinstance(current_self, Instance) and isinstance(other_self, Instance)
                assert current_self.name == "self", "Somehow not operating on self."
                if current_self is not other_self:
                    attr = value_type(target.attr, current_self.scope, current_self)
                    current_self.add(attr)
                    target = Attribute(
                        attr,
                        value=target.value,
                        attr=target.attr,
                        lineno=target.lineno
                    )
                else:
                    raise TypeError(f"Existing type of {target.id} does not match.")
            return ast.Assign(
                targets=[target],
                value=value,
                type_comment=None,
                lineno=target.lineno
            )
        elif isinstance(target, ast.Name):
            try:
                self.scope.lookup(target.id)
                # TODO: validate that looked up existing value type matches new value type
                types_match = True
                if not types_match:
                    raise TypeError(f"Existing type of {target.id} does not match.")
                # TODO ^
                return ast.Assign(
                    targets=[target],
                    value=value,
                    type_comment=None,
                    lineno=target.lineno
                )
            except NameError:
                if not value_type:
                    raise TypeError(
                        "Concrete type could not be determined from type annotation or value."
                    )
                self.scope.add(value_type(target.id, self.scope, self.func))
                return ast.AnnAssign(
                    target=target,
                    annotation=value_type.annotation,
                    value=value,
                    simple=isinstance(target, ast.Name),
                    lineno=target.lineno
                )
        elif isinstance(target, ast.Subscript):
            target = ast.Subscript(
                slice=target.slice,
                value=self.visit(target.value),
                lineno=target.lineno
            )
            return ast.Assign(
                targets=[target],
                value=value,
                type_comment=None,
                lineno=target.lineno
            )
        else:
            raise NotImplementedError

    def assign_name_value(self, targets, value_ast, annotation_ast):
        annotation = None
        if annotation_ast:
            annotation = self.visit_type_annotation(annotation_ast).obj
        value = self.visit(value_ast)
        if isinstance(annotation, Class):
            # validate that annotation_value_type and value_type match
            pass
        elif isinstance(value.obj, Class):
            annotation = value.obj
        elif isinstance(value.obj, (Instance, Function)):
            annotation = value.obj.cls

        assignments = [self.make_assignment(targets[-1], annotation, value)]
        if len(targets) > 1:
            target_names = reversed(targets[:-1])
            value_names = reversed(targets[1:])
            for target, value in zip(target_names, value_names):
                assignments.append(self.make_assignment(target, annotation, value))
        return assignments

    def visit_Assign(self, node: ast.Assign):
        return self.assign_name_value(node.targets, node.value, None)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        return self.assign_name_value([node.target], node.value, node.annotation)

    def visit_AugAssign(self, node: ast.AugAssign):
        bin_op_value = ast.BinOp(
            left=node.target,
            op=node.op,
            right=node.value,
        )
        return self.assign_name_value([node.target], bin_op_value, None)

    def visit_Attribute(self, node: ast.Attribute):
        value = self.visit(node.value)
        try:
            maybe_narrowed_attr = ast.unparse(node)
            attr = self.scope.lookup(maybe_narrowed_attr)
        except NameError:
            try:
                attr = value.obj.find(node.attr)
            except NameError:
                value_init = value.obj.cls.init
                if value_init and not value_init.is_analyzed:
                    raise DependencyError(value_init)
                raise

        return Attribute(
            attr,
            value=value,
            attr=node.attr,
            lineno=node.lineno,
        )

    def visit_Name(self, node: ast.Name):
        value = self.scope.search(node.id)
        if node.id == "super":
            return Name(value, id="super")
        elif node.id == "cls" and self.func.cls == value:
            return Name(value, id="this")
        return Name(value)

    def visit_Starred(self, node: ast.Starred):
        value = self.visit(node.value)
        item_type = next(iter(value.obj.cls.generic_types.values()))
        return Starred(item_type, value=value)

    def visit_Subscript(self, node: ast.Subscript):
        slice = self.visit(node.slice)
        value = self.visit(node.value)
        getitem = value.obj.find("__getitem__")
        assert isinstance(getitem.return_type, (Class, UnionType))
        # TODO: replace value with Attribute Call
        # result = next(iter(value.obj.cls.generic_types.values()))
        return Subscript(getitem.return_type, slice=slice, value=value)

    # endregion

    # region functions

    def visit_Call(self, node: ast.Call):
        """
        Instantiating a class in Python is an ast.Call, for generic class instantiation
        there are two ways to determine the corresponding concrete type to create:
        1. annotation is provided after class name (eg. Foo[int]() )
        2. infer class type arguments if all of them happen to be referenced in the __init__
           parameter list and this ast.Call includes arguments for those parameters
        In case of both 1 and 2 being provided, 1 takes precedence and enforces that 2 matches.
        """

        if isinstance(node.func, ast.Subscript):
            func = self.visit(node.func.value)
            if isinstance(func.obj, GenericClass):
                # types are passed, create concrete class
                func = self.visit_type_annotation(node.func)
            else:
                raise NotImplementedError("slicing a dict which returns function and calling it")
        else:
            func = self.visit(node.func)

        assert isinstance(func.obj, (GenericClass, Class, Function))
        if isinstance(func.obj, Function) and not func.obj.is_analyzed:
            raise DependencyError(func.obj)

        args = [self.visit(arg) for arg in node.args]
        keywords = [
            ast.keyword(arg=kw.arg, value=self.visit(kw.value))
            for kw in node.keywords
        ]

        if isinstance(func.obj, Function):
            return_type = func.obj.return_type
        elif isinstance(func.obj, Class):
            return_type = func.obj
        elif isinstance(func.obj, GenericClass):
            # types were not passed, try creating from args
            return_type = func.obj.from_call([a.obj for a in args])
            func = Name(return_type)
        else:
            raise NotImplementedError(f"Don't know how to handle {func.obj} call.")
        # TODO: validate that func parameters and the provided arguments are compatible
        return Call(return_type, func=func, args=args, keywords=keywords)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.func.params = []
        self.func.vararg = None
        self.func.kwarg = None
        self.func.defaults = defaults = [
            self.visit(default) for default in node.args.defaults
        ]

        pos_params = list(node.args.args)
        if node.args.vararg: pos_params.append(node.args.vararg)
        if node.args.kwarg: pos_params.append(node.args.kwarg)
        no_defaults = len(pos_params) - len(defaults)
        pos_defaults = [None] * no_defaults + defaults

        if self.func.is_method:
            if self.func.is_classmethod:
                assert pos_params[0].arg == "cls", "First parameter in classmethod should be cls."
            elif self.func.is_staticmethod:
                pass
            else:
                assert pos_params[0].arg == "self", "First parameter in method should be self."

        for i, (param, default) in enumerate(zip(pos_params, pos_defaults)):
            if i==0 and param.arg == "self" and self.func.is_method:
                self.func.add_self()
                continue
            if i==0 and param.arg == "cls" and self.func.is_classmethod:
                self.func.add_cls()
                continue
            default_value_type = None
            if default is not None:
                default_value_type = default.obj
                assert isinstance(default_value_type, Class)
            annotation_type = None
            if param.annotation is not None:
                annotation_type = self.visit_type_annotation(param.annotation).obj
                assert isinstance(annotation_type, (Class, UnionType))
            if default_value_type and annotation_type:
                # TODO: check that default value type is in one of annotation_types
                pass
            if param == node.args.vararg:
                if annotation_type is None:
                    annotation_type = BUILTINS.search("object")
                arg_type = BUILTINS.search("tuple")(annotation_type)
                self.func.vararg = ast.arg(arg=node.args.vararg.arg, annotation=Name(arg_type))
            elif param == node.args.kwarg:
                key_type = BUILTINS.search("str")
                value_type = annotation_type
                if value_type is None:
                    value_type = BUILTINS.search("object")
                arg_type = BUILTINS.search("dict")(key_type, value_type)
                self.func.kwarg = ast.arg(arg=node.args.kwarg.arg, annotation=Name(arg_type))
            else:
                arg_type = annotation_type or default_value_type
                if not arg_type:
                    raise TypeError(
                        "Concrete type could not be determined from type annotation or value."
                    )
                self.func.params.append(ast.arg(arg=param.arg, annotation=Name(arg_type)))
            self.func.scope.add(arg_type(param.arg, self.func.scope, self.func))
        if should_analyze_func_body(self.func.py_func):
            self.func.body = self.visit_body(node.body)
        else:
            if not self.func.name == "__init__":
                assert node.returns, "Return type annotation required for @js.source and @js.inline"
            else:
                self.func.return_type = self.func.cls

        if node.returns:
            if isinstance(node.returns, ast.Constant) and node.returns.value is None:
                # make sure inferred type is also None
                return
            elif isinstance(node.returns, ast.Subscript):
                returns = self.visit_type_annotation(node.returns)
            else:
                returns = self.visit(node.returns)
            assert isinstance(returns.obj, (Class, UnionType))
            # check that return_type matches inferred type
            self.func.return_type = returns.obj

    def visit_type_annotation(self, node):
        if isinstance(node, ast.Subscript):
            value = self.visit(node.value)
            if isinstance(node.slice, ast.Tuple):
                item_types = [self.visit_type_annotation(elt).obj for elt in node.slice.elts]
            elif isinstance(node.slice, (ast.Name, ast.BinOp, ast.Subscript)):
                item_types = [self.visit_type_annotation(node.slice).obj]
            else:
                raise NotImplementedError()
            assert isinstance(value.obj, GenericClass)
            return Name(value.obj(*item_types))  # generic class -> concrete class
        elif isinstance(node, ast.BinOp):
            types: list[Class] = []
            binop = node
            while True:
                right = self.visit_type_annotation(binop.right).obj
                assert isinstance(right, Class)
                types.append(right)
                if isinstance(binop.left, ast.BinOp):
                    binop = binop.left
                else:
                    left = self.visit_type_annotation(binop.left).obj
                    assert isinstance(left, Class)
                    types.append(left)
                    break
            return BinOp(
                UnionType(types=reversed(types)), left=node.left, op=node.op, right=node.right
            )
        else:
            assert isinstance(node, ast.Name)
            return self.visit(node)

    def visit_Pass(self, node: ast.Pass):
        return node

    def visit_Return(self, node: ast.Return):
        if (value := node.value) is not None:
            value = self.visit(value)
            if isinstance(value.obj, (Class, UnionType)):
                return_type = value.obj
            else:
                assert isinstance(value.obj, Instance)
                return_type = value.obj.cls
            assert self.func.return_type is None or self.func.return_type == return_type
            self.func.return_type = return_type
        return ast.Return(value=value)

    def visit_Lambda(self, node: ast.Lambda):
        return ast.Lambda(args=node.args, body=self.visit(node.body))

    # endregion

    # region expressions & operators

    def visit_Expr(self, node: ast.Expr):
        return ast.Expr(value=self.visit(node.value))

    def visit_JoinedStr(self, node: ast.JoinedStr):
        return JoinedStr(
            BUILTINS.search("str"),
            values=[self.visit(part) for part in node.values]
        )

    def visit_FormattedValue(self, node: ast.FormattedValue):
        return ast.FormattedValue(
            value=self.visit(node.value),
            conversion=node.conversion,
            format_spec=node.format_spec,
        )

    COMPARE_OPS = {
        ast.Is: ("__is__", "__is__"),  # pyjs hack, there is no __is__ in Python
        ast.IsNot: ("__is_not__", "__is_not__"),# there is no __is_not__ in Python

        ast.Lt: ("__lt__", "__gt__"),
        ast.LtE: ("__le__", "__ge__"),
        ast.Gt: ("__gt__", "__lt__"),
        ast.GtE: ("__ge__", "__le__"),
        ast.Eq: ("__eq__", "__eq__"),
        ast.NotEq: ("__ne__", "__ne__"),

        ast.In: ("__contains__", None),
        ast.NotIn: ("__contains__", None),
    }

    def visit_Compare(self, node: ast.Compare):
        assert len(node.ops) == len(node.comparators) == 1

        left = self.visit(node.left)
        left_self = left.obj if isinstance(left.obj, Instance) else left.obj._self
        right = self.visit(node.comparators[0])
        right_self = right.obj if isinstance(right.obj, Instance) else right.obj._self
        if isinstance(node.ops[0], (ast.In, ast.NotIn)):
            left, right = right, left

        left_op_method, right_op_method = self.COMPARE_OPS[type(node.ops[0])]

        try:
            func = left_self.find(left_op_method)
            assert isinstance(func, Function)
            if func.cls.name == "object":
                # for __eq__, __ne__, etc, Python checks the
                # right side before falling back to object
                raise NameError
        except NameError as e:
            if isinstance(node.ops[0], (ast.In, ast.NotIn)):
                raise e
            func = right_self.find(right_op_method)
            if func.cls.name != "object":
                left, right = right, left
        return Call(
            func.return_type,
            func=Attribute(
                func,
                value=left,
                attr=func.name
            ),
            args=[right],
            keywords=[]
        )

    BIN_OPS = {
        ast.Add: ("__add__", "__radd__"),
        ast.Sub: ("__sub__", "__rsub__"),
        ast.Mult: ("__mul__", "__rmul__"),
        ast.Div: ("__truediv__", "__rtruediv__"),
        ast.FloorDiv: ("__floordiv__", "__rfloordiv__"),
        ast.Pow: ("__mod__", "__rmod__"),
    }

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        left_self = left.obj if isinstance(left.obj, Instance) else left.obj._self
        right = self.visit(node.right)
        right_self = right.obj if isinstance(right.obj, Instance) else right.obj._self
        left_op_method, right_op_method = self.BIN_OPS[type(node.op)]
        try:
            func = left_self.find(left_op_method)
            assert isinstance(func, Function)
            if func.params[0].annotation.id != right_self.cls.name:
                # this is the equivalent of the op function returning NotImplemented
                raise NameError
        except NameError:
            func = right_self.find(right_op_method)
            left, right = right, left
        return Call(
            func.return_type,
            func=Attribute(
                func,
                value=left,
                attr=func.name
            ),
            args=[right],
            keywords=[]
        )

    UNARY_OPS = {
        ast.UAdd: "__pos__",
        ast.USub: "__neg__",
        ast.Invert: "__invert__",
        ast.Not: "__bool__",
    }

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        op_method = self.UNARY_OPS[type(node.op)]
        if isinstance(node.op, ast.Not):
            if isinstance(operand, Call) and operand.obj.name == "bool":
                return UnaryOp(
                    operand.func.obj.return_type,
                    op=node.op,
                    operand=operand,
                )
            elif isinstance(operand, Attribute) and operand.obj.cls.name == "bool":
                return UnaryOp(
                    operand.obj.cls,
                    op=node.op,
                    operand=operand,
                )
            else:
                func = operand.obj.find(op_method)
                assert func.return_type.name == "bool"
                return UnaryOp(
                    func.return_type,
                    op=node.op,
                    operand=Call(
                        func.return_type,
                        func=Attribute(
                            func,
                            value=operand,
                            attr=func.name
                        ),
                        args=[],
                        keywords=[]
                    )
                )
        raise NotImplementedError

    # endregion

    # region constants

    def visit_Constant(self, node: ast.Constant):
        type_name = type(node.value).__name__
        type_cls = BUILTINS.search(type_name)
        assert isinstance(type_cls, Class)
        return Constant(type_cls, value=node.value)

    def visit_Tuple(self, node: ast.Tuple):
        generic_tuple = BUILTINS.search('tuple')
        assert isinstance(generic_tuple, GenericClass)
        elts = []
        types = []
        for item in node.elts:
            elt = self.visit(item)
            elts.append(elt)
            types.append(elt.obj.type)
        tuple_type = generic_tuple(*types)
        return Tuple(tuple_type, elts=elts)

    def visit_List(self, node: ast.List):
        generic_list = BUILTINS.search('list')
        assert isinstance(generic_list, GenericClass)
        V = UnionType()
        elts = []
        for item in node.elts:
            elt = self.visit(item)
            elts.append(elt)
            V.add(elt.obj.type)
        list_type = generic_list(V.type) if V.types else generic_list
        return List(list_type, elts=elts)

    def visit_Dict(self, node: ast.Dict):
        generic_dict = BUILTINS.search("dict")
        assert isinstance(generic_dict, GenericClass)
        K, keys, V, values = UnionType(), [], UnionType(), []
        for key, value in zip(node.keys, node.values):
            keys.append(self.visit(key))
            K.add(keys[-1].obj)
            values.append(self.visit(value))
            V.add(values[-1].obj.type)
        dict_type = generic_dict(K.type, V.type) if K.types and V.types else generic_dict
        return Dict(dict_type, keys=keys, values=values)

    # endregion

    # region looping

    def visit_For(self, node: ast.For):
        node_iter = self.visit(node.iter)

        if isinstance(node.target, ast.Name):
            iter_cls = node_iter.obj.type
            assert len(iter_cls.generic_types) == 1
            item_type = next(iter(iter_cls.generic_types.values()))
            assert isinstance(iter_cls, (UnionType, Class))
            self.scope.add(item_type(node.target.id, self.scope, self.func))
            target = ast.arg(arg=node.target.id, annotation=item_type.annotation)
        elif isinstance(node.target, ast.Tuple):
            iter_type = node_iter.obj.type
            assert iter_type.generic_name in ("Iterable", "list")
            types = list(iter_type.generic_types["V"].generic_types.values())
            assert len(node.target.elts) == len(types)
            elts = []
            for val, val_type in zip(node.target.elts, types):
                elts.append(ast.arg(arg=val.id, annotation=val_type.annotation))
                self.scope.add(val_type(val.id, self.scope, self.func))
            target = ast.Tuple(elts=elts)
        else:
            raise NotImplementedError

        body = self.visit_body(node.body)
        orelse = self.visit(node.orelse) if node.orelse else node.orelse
        return ast.For(
            target=target,
            iter=node_iter,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )

    def visit_ListComp(self, node: ast.ListComp):
        gen = node.generators[0]
        gen.iter = self.visit(gen.iter)
        if isinstance(gen.target, ast.Name):
            iter_cls = gen.iter.obj
            if isinstance(iter_cls, Instance):
                iter_cls = iter_cls.cls
            item_type = next(iter(iter_cls.generic_types.values()))
            if isinstance(item_type, UnionType):
                # TODO: don't just pick the first type here
                item_type = next(iter(item_type.types))
            self.scope.add(
                item_type(gen.target.id, self.scope, self.func)
            )
        else:
            raise NotImplementedError
        target = self.visit(gen.target)
        elt = self.visit(node.elt)
        return ListComp(
            BUILTINS.search("list")(item_type),
            elt=elt,
            target=target,
            generators=node.generators,
        )

    # endregion

    # region conditionals

    def visit_If(self, node: ast.If):
        test = self.visit(node.test)
        if isinstance(test.obj, Instance):
            test_type = test.obj.cls
        elif isinstance(test.obj, Class):
            test_type = test.obj
        else:
            raise NotImplementedError
        if test_type.name != "bool":
            func = test_type.find("__bool__")
            test = Call(
                func.return_type,
                func=Attribute(
                    func,
                    value=test,
                    attr=func.name
                ),
                args=[],
                keywords=[]
            )
        if (
            isinstance(test, Call) and
            isinstance(test.func, Name) and
            test.func.id == "isinstance"
        ):
            args = test.args
            assert len(args) == 2
            if isinstance(args[0], ast.Attribute):
                value_name = ast.unparse(args[0])
            else:
                assert isinstance(args[0], ast.Name)
                value_name = args[0].id
            assert isinstance(args[1], ast.Name)
            value_type = args[1].obj
            assert isinstance(value_type, (Class, GenericClass))
            if isinstance(value_type, GenericClass):
                obj_type = BUILTINS.search("object")
                if value_type.name == "dict":
                    value_type = BUILTINS.search("dict")(obj_type, obj_type)
                elif value_type.name == "list":
                    value_type = BUILTINS.search("list")(obj_type)
                else:
                    raise NotImplementedError
            narrowed = self.narrow()
            narrowed.scope.add(
                value_type(value_name, narrowed.scope, self.func)
            )
            body = narrowed.visit_body(node.body)
        else:
            body = self.visit_body(node.body)
        orelse = [self.visit(orelse) for orelse in node.orelse]
        return ast.If(
            test=test,
            body=body,
            orelse=orelse
        )

    def visit_IfExp(self, node: ast.IfExp):
        test = self.visit(node.test)
        if isinstance(test.obj, Instance):
            test_type = test.obj.cls
        elif isinstance(test.obj, Class):
            test_type = test.obj
        else:
            raise NotImplementedError
        if test_type.name != "bool":
            func = test_type.find("__bool__")
            test = Call(
                func.return_type,
                func=Attribute(
                    func,
                    value=node.test,
                    attr=func.name
                ),
                args=[],
                keywords=[]
            )
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        assert body.obj == orelse.obj
        return IfExp(
            body.obj,
            test=test,
            body=body,
            orelse=orelse
        )

    def visit_Assert(self, node: ast.Assert):
        test = self.visit(node.test)
        return ast.Assert(test=test, msg=node.msg)

    def visit_Raise(self, node: ast.Raise):
        return node

    # endregion


class CallGraphVisitor(ast.NodeVisitor):

    def __init__(self, func: Function, entry_point: Function):
        self.func = func
        self.entry_point = entry_point

    @classmethod
    def start(cls, func: Function):
        cls(func, func).enter(func)

    def enter(self, func: Function):
        if func.cls is not None:
            self.enter_class(func.cls)
        self.isolated_visit(func)

    def enter_class(self, cls: Class):
        while cls is not None:
            if self.entry_point not in cls.visited:
                cls.visited.add(self.entry_point)
                for attr in cls.children:
                    if has_include_decorator(attr.py_obj) or self.parent_has_include(attr):
                        self.isolated_visit(attr)
            cls = cls.super

    def parent_has_include(self, obj):
        if isinstance(obj, Function):
            parent = obj.cls.super
            while parent is not None:
                parent_func = parent.find_attrs(obj.name, search_bases=False)
                if parent_func and has_include_decorator(parent_func.py_obj):
                    return True
                parent = parent.super
        return False

    def isolated_visit(self, func: Function):
        assert isinstance(func, Function)
        if not has_source_decorator(func.py_func) and self.entry_point not in func.visited:
            type(self)(func, self.entry_point).visit(func.node)

    def visit_FunctionDef(self, node: FunctionDef):
        node.obj.visited.add(self.entry_point)
        for arg in node.args.args:
            self.visit(arg)
        for stmt in node.body:
            self.visit(stmt)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, Name) and node.func.id == "tw":
            self.entry_point.tailwind_classes.update(
                set(node.args[0].value.split(" "))
            )
        func = node.func.obj
        if isinstance(func, Function):
            self.enter(func)
        elif isinstance(func, Class):
            self.enter_class(func)
            self.enter(func.find("__init__"))
        else:
            raise NotImplementedError(f"Can't call {node.func}.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.obj, Function):
            self.enter(node.obj)
        elif isinstance(node.obj, Instance):
            node.obj.visited.add(self.entry_point)
        self.generic_visit(node)

    def visit_Name(self, node: Name):
        if hasattr(node, 'obj'):
            if isinstance(node.obj, Class):
                self.enter_class(node.obj)
                self.enter(node.obj.find("__init__"))
            elif isinstance(node.obj, Function):
                self.enter(node.obj)
            elif isinstance(node.obj, UnionType):
                for obj_type in node.obj.types:
                    self.enter_class(obj_type)
                    self.enter(obj_type.find("__init__"))
            else:
                node.obj.visited.add(self.entry_point)


def from_entry_point(entry_point: callable):
    entry_point.__js__ = True
    py_module = inspect.getmodule(entry_point)
    return analyze_module(py_module, entry_point)


def analyze_module(py_module, entry_point=None):
    if entry_point is None:
        assert hasattr(py_module, "main"), "No entry_point specified and no main() function found."
        py_module.main.__js__ = True
        entry_point = py_module.main
    package = {}
    module = Module(py_module, package).build()
    package[module.name] = module
    for imported in package.values():
        annotate_types(imported)
    annotate_types(module)
    entry_point_function, tailwind_classes = visit_entry_point(module, entry_point)
    entry_point_function.visited.clear()
    return entry_point_function, tailwind_classes


def visit_entry_point(module: Module, py_func):
    entry_point_func = module.search(py_func.__name__)
    assert isinstance(entry_point_func, Function)
    entry_point_func.tailwind_classes = set()
    CallGraphVisitor.start(entry_point_func)
    return entry_point_func, entry_point_func.tailwind_classes


def flatten_objects(parent: Object) -> Iterator[Function]:
    if isinstance(parent, (Module, Class)):
        for obj in parent.children:
            yield from flatten_objects(obj)
    elif isinstance(parent, Function):
        yield parent


def annotate_types(parent: Object):
    functions = flatten_objects(parent)
    while True:
        dependencies = TopologicalSorter()
        added = False
        for func in functions:
            try:
                func.reset()
                InferenceVisitor(func).visit(func.original_node)
                func.is_analyzed = True
            except DependencyError as e:
                if isinstance(e.class_or_func, Class):
                    dependencies.add(func, *flatten_objects(e.class_or_func))
                elif isinstance(e.class_or_func, Function):
                    dependencies.add(func, e.class_or_func)
                else:
                    raise TypeError(f"Cannot handle dependency of type {type(e.class_or_func)}.")
                added = True
        if not added:
            break
        functions = dependencies.static_order()


def load_builtins():
    from . import _builtins
    for name, value in list(vars(_builtins).items()):
        if name.startswith("_") and not name.startswith("__"):
            value.__js__ = True
            value.__builtin__ = True
            value.__name__ = name[1:]
            value.__qualname__ = name[1:]
            setattr(_builtins, name[1:], value)
            delattr(_builtins, name)
        else:
            # re-add others too to keep the keys in dict the same order
            # very hacky, should fix sometime
            delattr(_builtins, name)
            setattr(_builtins, name, value)
    return Module(_builtins, {}, is_builtins=True).build()


ModuleScope.BUILTINS = BUILTINS = load_builtins()
annotate_types(BUILTINS)

from collections.abc import Iterator
from dataclasses import dataclass
from graphlib import TopologicalSorter

from .diagnostics import CompilationContext, DiagnosticCode, Label
from .objects import *


@dataclass
class AssignmentValue:
    node: ast.expr
    declared_type: Class | UnionType | None
    inferred_type: Class | UnionType | None

    @property
    def storage_type(self):
        return self.declared_type or self.inferred_type


def analyzed_annotation(value_type: Class | UnionType) -> ast.expr:
    if isinstance(value_type, Class):
        return Name(value_type)
    annotation = value_type.annotation
    annotation.obj = value_type
    return annotation


def get_none_type():
    none_type = BUILTINS.search("NoneType")
    assert isinstance(none_type, Class)
    return none_type


def get_type_members(type_):
    if isinstance(type_, UnionType):
        return list(type_.types)
    return [type_]


def is_return_type_compatible(expected, actual):
    if expected is None:
        return True
    if expected == actual:
        return True
    expected_types = get_type_members(expected)
    return all(
        any(is_subclass(actual_type, expected_type) for expected_type in expected_types)
        for actual_type in get_type_members(actual)
    )


def is_subclass(actual, expected):
    while actual is not None:
        if actual.name == expected.name:
            return True
        actual = actual.super
    return False


def merge_return_types(left, right):
    if left is None:
        return right
    if left == right:
        return left
    merged = UnionType()
    for type_ in get_type_members(left):
        merged.add(type_)
    for type_ in get_type_members(right):
        merged.add(type_)
    return merged.type


def json_function_name(function):
    if (
        isinstance(function, Function)
        and function.cls is not None
        and function.cls.name == "JSON"
        and function.py_func.__module__ == "pyjs.javascript"
    ):
        return function.name
    return None


def is_json_parse_call(node):
    return (
        isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and json_function_name(node.func.obj) == "parse"
    )


def contains_python_dict(value_type, seen=None):
    if seen is None:
        seen = set()
    if id(value_type) in seen:
        return False
    seen.add(id(value_type))
    if isinstance(value_type, UnionType):
        return any(contains_python_dict(member, seen) for member in value_type.types)
    if isinstance(value_type, TypedDictClass):
        return any(
            contains_python_dict(value_type.field_type(key), seen)
            for key in value_type.annotations
        )
    if not isinstance(value_type, Class):
        return False
    if value_type.generic_name == "dict":
        return True
    return any(
        contains_python_dict(member, seen)
        for member in (value_type.generic_types or {}).values()
    )


def validate_json_result_type(result_type, seen=None):
    if seen is None:
        seen = set()
    if id(result_type) in seen:
        return
    seen.add(id(result_type))
    if isinstance(result_type, UnionType):
        for member in result_type.types:
            validate_json_result_type(member, seen)
        return
    if isinstance(result_type, TypedDictClass):
        for key in result_type.annotations:
            validate_json_result_type(result_type.field_type(key), seen)
        return
    if isinstance(result_type, Class):
        if result_type.generic_name == "dict":
            raise TypeError(
                "JSON.parse() cannot return dict; describe JSON objects with TypedDict."
            )
        if result_type.generic_name == "list":
            validate_json_result_type(result_type.generic_types["V"], seen)
            return
        if result_type.name in {"bool", "float", "int", "NoneType", "str"}:
            return
    raise TypeError(
        "JSON.parse() requires a JSON primitive, list, or TypedDict result annotation."
    )


def apply_typed_dict_literal(value, expected_type):
    if isinstance(expected_type, TypedDictClass) and isinstance(value, Dict):
        value.obj = expected_type
        for key, item in zip(value.keys, value.values, strict=True):
            if not isinstance(key, Constant) or not isinstance(key.value, str):
                raise TypeError("TypedDict literal keys must be strings.")
            apply_typed_dict_literal(item, expected_type.field_type(key.value))
    elif (
        isinstance(expected_type, Class)
        and expected_type.generic_name == "list"
        and isinstance(value, List)
    ):
        item_type = expected_type.generic_types["V"]
        for item in value.elts:
            apply_typed_dict_literal(item, item_type)


def body_can_fall_through(statements: list[ast.stmt]):
    for statement in statements:
        if statement_always_exits(statement):
            return False
    return True


def statement_always_exits(statement: ast.stmt):
    if isinstance(statement, (ast.Return, ast.Raise)):
        return True
    if isinstance(statement, ast.If):
        return (
            bool(statement.orelse)
            and not body_can_fall_through(statement.body)
            and not body_can_fall_through(statement.orelse)
        )
    if isinstance(statement, ast.Match):
        return bool(statement.cases) and all(
            not body_can_fall_through(case.body) for case in statement.cases
        )
    if isinstance(statement, ast.While):
        if (
            statement.orelse
            and not body_can_fall_through(statement.body)
            and not body_can_fall_through(statement.orelse)
        ):
            return True
        return (
            isinstance(statement.test, ast.Constant)
            and bool(statement.test.value)
            and not statement.orelse
            and not body_can_fall_through(statement.body)
        )
    if isinstance(statement, ast.Try):
        if statement.finalbody and not body_can_fall_through(statement.finalbody):
            return True
        return (
            bool(statement.handlers)
            and not body_can_fall_through(statement.body)
            and all(
                not body_can_fall_through(handler.body) for handler in statement.handlers
            )
        )
    return False


def is_interface_stub_body(statements: list[ast.stmt]):
    if len(statements) != 1:
        return False
    statement = statements[0]
    if isinstance(statement, ast.Raise):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


class InferenceVisitor(ast.NodeVisitor):
    def __init__(self, func: Function, scope: LocalScope = None):
        self.func = func
        self.scope = scope or func.scope
        self.assignment_target: ast.AST | None = None

    @property
    def module(self) -> Module:
        return self.func.cls.container if self.func.is_method else self.func.container

    def fail(
        self,
        node: ast.AST,
        code: DiagnosticCode,
        message: str,
        *,
        label: str | None = None,
        help: str | None = None,
        secondary: tuple[Label, ...] = (),
    ):
        self.module.context.error(
            self.func.source_fragment,
            node,
            code,
            message,
            label=label,
            help=help,
            secondary=secondary,
        )

    def visible_names(self) -> set[str]:
        names = set()
        scope = self.scope
        while scope is not None:
            names.update(scope.names)
            scope = scope.parent
        names.update(self.module.scope.names)
        return names

    @staticmethod
    def attribute_names(value: Instance) -> set[str]:
        names = set(value.attrs)
        cls = value.cls
        while cls is not None:
            names.update(cls.internal_scope.names)
            names.update(cls._self.attrs)
            cls = cls.super
        return names

    def fail_name_lookup(self, node: ast.Name):
        self.module.context.name_lookup_error(
            self.func.source_fragment,
            node,
            self.module.py_module,
            self.visible_names(),
        )

    def narrow(self, value_node, value_type):
        narrowed = type(self)(self.func, LocalScope(self.scope))
        value_name = ast.unparse(value_node)
        narrowed.scope.add(value_type(value_name, narrowed.scope, self.func))
        return narrowed

    def get_none_identity_narrowing(self, test):
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], (ast.Is, ast.IsNot))
        ):
            return None
        left = test.left
        right = test.comparators[0]
        if isinstance(left, ast.Constant) and left.value is None:
            value_node = right
        elif isinstance(right, ast.Constant) and right.value is None:
            value_node = left
        else:
            return None
        if not isinstance(value_node, (ast.Name, ast.Attribute)):
            return None
        value = self.visit(value_node)
        if not isinstance(value.obj, Instance):
            return None
        value_types = get_type_members(value.obj.cls)
        if len(value_types) != 2:
            return None
        non_none_types = [type_ for type_ in value_types if type_.name != "NoneType"]
        if len(non_none_types) != 1:
            return None
        return value_node, non_none_types[0], isinstance(test.ops[0], ast.IsNot)

    def inline_dependencies(self, function: Function, node: ast.AST):
        objects = {}
        dependencies = getattr(
            function.py_func,
            "__js_inline_dependencies__",
            {},
        )
        for name, dependency in dependencies.items():
            if not getattr(dependency, "__js__", False):
                definition = self.module.context.sources.definition_span(dependency)
                secondary = (
                    (
                        Label(
                            definition,
                            "defined here without client compilation enabled",
                        ),
                    )
                    if definition is not None
                    else ()
                )
                if getattr(dependency, "__js__", None) is False:
                    help_text = (
                        f"Remove @nojs from {dependency.__name__!r} if it should "
                        "run on the client."
                    )
                else:
                    help_text = f"Decorate {dependency.__name__!r} with @js."
                self.fail(
                    node,
                    DiagnosticCode.MISSING_JS_DECORATOR,
                    f"Inline dependency {name!r} of {function.name!r} is not "
                    "available to client code",
                    help=help_text,
                    secondary=secondary,
                )
            dependency_obj = resolve_imported(dependency, self.module)
            if not isinstance(dependency_obj, Function):
                self.fail(
                    node,
                    DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                    f"Inline dependency {name!r} of {function.name!r} must be a "
                    "function",
                )
            if dependency_obj.inline_decorator:
                definition = self.module.context.sources.definition_span(dependency)
                secondary = (
                    (Label(definition, "inline dependency defined here"),)
                    if definition is not None
                    else ()
                )
                self.fail(
                    node,
                    DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                    f"Inline dependency {name!r} of {function.name!r} does not "
                    "emit a runtime function",
                    help=(
                        f"Remove inline= from @js on {dependency.__name__!r}, or "
                        "reference a runtime function."
                    ),
                    secondary=secondary,
                )
            objects[name] = dependency_obj
        return objects

    def get_none_narrowings(self, test, when_true):
        narrowing = self.get_none_identity_narrowing(test)
        if narrowing is not None:
            value_node, value_type, non_none_when_true = narrowing
            if non_none_when_true == when_true:
                return [(value_node, value_type)]
            return []
        if not isinstance(test, ast.BoolOp):
            return []
        if isinstance(test.op, ast.And):
            all_values_are_known = when_true
        else:
            assert isinstance(test.op, ast.Or)
            all_values_are_known = not when_true
        if not all_values_are_known:
            return []
        narrowings = []
        for value in test.values:
            narrowings.extend(self.get_none_narrowings(value, when_true))
        return narrowings

    def narrow_for_condition(self, test, when_true):
        visitor = self
        for value_node, value_type in self.get_none_narrowings(test, when_true):
            visitor = visitor.narrow(value_node, value_type)
        return visitor

    def visit_body(self, statements):
        body = []
        narrow_visitor = self
        for statement in statements:
            stmt = narrow_visitor.visit(statement)

            if isinstance(stmt, ast.Assert):
                test = stmt.test
                if (
                    isinstance(test, ast.Call)
                    and isinstance(test.func, ast.Name)
                    and test.func.id == "isinstance"
                ):
                    args = test.args
                    assert len(args) == 2
                    assert all(isinstance(a, ast.Name) for a in args)
                    value_type = args[1].obj
                    assert isinstance(value_type, Class)
                    narrow_visitor = narrow_visitor.narrow(args[0], value_type)
                    continue

            if (
                isinstance(statement, ast.If)
                and not stmt.orelse
                and not body_can_fall_through(stmt.body)
            ):
                narrow_visitor = narrow_visitor.narrow_for_condition(
                    statement.test, False
                )

            if isinstance(stmt, list):
                body.extend(stmt)
            else:
                body.append(stmt)
        return body

    # region assignment & lookup

    def analyze_assignment_value(self, value_node, annotation_node=None):
        declared_type = None
        if annotation_node:
            annotation = self.visit_type_annotation(annotation_node).obj
            if isinstance(annotation, (Class, UnionType)):
                declared_type = annotation

        value = self.visit(value_node)
        if is_json_parse_call(value):
            if declared_type is None:
                self.fail(
                    value_node,
                    DiagnosticCode.JSON_RESULT_TYPE_REQUIRED,
                    "JSON.parse() requires an explicit result annotation",
                    help="Annotate the assignment with a TypedDict result type.",
                )
            validate_json_result_type(declared_type)
        if declared_type is not None:
            apply_typed_dict_literal(value, declared_type)

        inferred_type = None
        if isinstance(value.obj, (Class, UnionType)):
            inferred_type = value.obj
        elif isinstance(value.obj, (Instance, Function)):
            inferred_type = value.obj.cls

        builtin_class = (
            self.func.cls is not None
            and self.func.cls.py_obj.__dict__.get("__builtin__", False)
        )
        if (
            declared_type is not None
            and inferred_type is not None
            and not builtin_class
            and not isinstance(value_node, (ast.Name, ast.Attribute, ast.Call))
            and not is_json_parse_call(value)
            and not is_return_type_compatible(declared_type, inferred_type)
        ):
            expected = declared_type.to_annotation_str()
            actual = inferred_type.to_annotation_str()
            self.fail(
                value_node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"Cannot assign {actual} to a value of type {expected}",
                help=f"Assign a value compatible with {expected}.",
            )

        return AssignmentValue(value, declared_type, inferred_type)

    def apply_contextual_collection_type(self, assignment_value, target_node):
        if assignment_value.storage_type is not None:
            return
        value = assignment_value.node
        if not isinstance(value, (List, Dict)) or not isinstance(value.obj, GenericClass):
            return
        if not isinstance(target_node, (ast.Name, ast.Attribute)):
            return
        try:
            if isinstance(target_node, ast.Name):
                target_obj = self.scope.lookup(target_node.id)
            else:
                self.assignment_target = target_node
                try:
                    target_obj = self.visit(target_node).obj
                finally:
                    self.assignment_target = None
        except NameError:
            return
        if not isinstance(target_obj, Instance):
            return
        target_type = target_obj.cls
        if isinstance(target_type, Class) and target_type.generic_name == value.obj.name:
            value.obj = target_type
            assignment_value.inferred_type = target_type

    def resolve_assignment_target(self, target, value_type: Class | UnionType):
        if isinstance(target, ast.Attribute):
            source_target = target
            try:
                self.assignment_target = target
                try:
                    target = self.visit(target)
                finally:
                    self.assignment_target = None
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
                        lineno=target.lineno,
                    )
                else:
                    raise e
            if target.obj.cls is not value_type:
                current_self = target.value.obj
                other_self = target.obj.container
                inherited = (
                    isinstance(current_self, Instance)
                    and isinstance(other_self, Instance)
                    and current_self.name == "self"
                    and current_self is not other_self
                )
                if inherited:
                    attr = value_type(target.attr, current_self.scope, current_self)
                    current_self.add(attr)
                    target = Attribute(
                        attr,
                        value=target.value,
                        attr=target.attr,
                        lineno=target.lineno,
                    )
                elif not is_return_type_compatible(target.obj.cls, value_type):
                    expected = target.obj.cls.to_annotation_str()
                    actual = value_type.to_annotation_str()
                    self.fail(
                        source_target,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot assign {actual} to {target.attr!r} of type {expected}",
                        help=(
                            f"Assign a value compatible with {expected} or change the "
                            f"annotation for {target.attr!r}."
                        ),
                    )
            return target, False
        elif isinstance(target, ast.Name):
            try:
                self.scope.lookup(target.id)
                # TODO: validate that looked up existing value type matches new value type
                types_match = True
                if not types_match:
                    raise TypeError(f"Existing type of {target.id} does not match.")
                # TODO ^
                return target, False
            except NameError:
                if not value_type:
                    self.fail(
                        target,
                        DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                        f"Type of {target.id!r} cannot be inferred",
                        help=f"Add an explicit type annotation for {target.id!r}.",
                    )
                self.scope.add(value_type(target.id, self.scope, self.func))
                return target, True
        elif isinstance(target, ast.Subscript):
            target = ast.Subscript(
                slice=target.slice,
                value=self.visit(target.value),
                lineno=target.lineno,
            )
            return target, False
        else:
            raise NotImplementedError

    def visit_Assign(self, node: ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
            target = node.targets[0]
            if isinstance(target.slice, ast.Slice):
                method_name = "__setslice__"
                args = [node.value, *self.slice_parts(target.slice)]
            else:
                method_name = "__setitem__"
                args = [target.slice, node.value]
            method = ast.copy_location(
                ast.Attribute(value=target.value, attr=method_name, ctx=ast.Load()),
                target,
            )
            call = ast.copy_location(
                ast.Call(func=method, args=args, keywords=[]),
                node,
            )
            return ast.Expr(value=self.visit(call))

        assignment_value = self.analyze_assignment_value(node.value)
        if len(node.targets) == 1:
            self.apply_contextual_collection_type(assignment_value, node.targets[0])
        target_values = [(node.targets[-1], assignment_value.node)]
        target_values.extend(
            zip(reversed(node.targets[:-1]), reversed(node.targets[1:]), strict=True)
        )

        assignments = []
        for target_node, value in target_values:
            target, is_new_name = self.resolve_assignment_target(
                target_node, assignment_value.storage_type
            )
            if is_new_name:
                assignments.append(
                    ast.AnnAssign(
                        target=target,
                        annotation=assignment_value.storage_type.annotation,
                        value=value,
                        simple=True,
                        lineno=target.lineno,
                    )
                )
            else:
                assignments.append(
                    ast.Assign(
                        targets=[target],
                        value=value,
                        type_comment=None,
                        lineno=target.lineno,
                    )
                )
        return assignments

    def visit_AnnAssign(self, node: ast.AnnAssign):
        assignment_value = self.analyze_assignment_value(node.value, node.annotation)
        target, is_new_name = self.resolve_assignment_target(
            node.target, assignment_value.storage_type
        )
        if isinstance(node.target, ast.Attribute):
            return ast.AnnAssign(
                target=target,
                annotation=target.obj.cls.annotation,
                value=assignment_value.node,
                simple=False,
                lineno=target.lineno,
            )
        if is_new_name:
            return ast.AnnAssign(
                target=target,
                annotation=assignment_value.storage_type.annotation,
                value=assignment_value.node,
                simple=True,
                lineno=target.lineno,
            )
        return ast.Assign(
            targets=[target],
            value=assignment_value.node,
            type_comment=None,
            lineno=target.lineno,
        )

    def visit_AugAssign(self, node: ast.AugAssign):
        bin_op_value = ast.BinOp(
            left=node.target,
            op=node.op,
            right=node.value,
        )
        return self.visit_Assign(ast.Assign(targets=[node.target], value=bin_op_value))

    @staticmethod
    def slice_parts(node: ast.Slice):
        return [
            part if part is not None else ast.Constant(value=None)
            for part in (node.lower, node.upper, node.step)
        ]

    def visit_Slice(self, node: ast.Slice):
        lower, upper, step = self.slice_parts(node)
        return ast.Slice(
            lower=self.visit(lower),
            upper=self.visit(upper),
            step=self.visit(step),
        )

    def visit_Delete(self, node: ast.Delete):
        statements = []
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                if isinstance(target.slice, ast.Slice):
                    method_name = "__delslice__"
                    args = self.slice_parts(target.slice)
                else:
                    method_name = "__delitem__"
                    args = [target.slice]
                method = ast.copy_location(
                    ast.Attribute(
                        value=target.value,
                        attr=method_name,
                        ctx=ast.Load(),
                    ),
                    target,
                )
                call = ast.copy_location(
                    ast.Call(func=method, args=args, keywords=[]),
                    target,
                )
                statements.append(ast.Expr(value=self.visit(call)))
            else:
                statements.append(ast.Delete(targets=[self.visit(target)]))
        return statements

    def visit_Attribute(self, node: ast.Attribute):
        value = self.visit(node.value)
        value_obj = value.value_obj if isinstance(value, (Call, Subscript)) else value.obj
        try:
            maybe_narrowed_attr = ast.unparse(node)
            attr = self.scope.lookup(maybe_narrowed_attr)
        except NameError:
            try:
                attr = value_obj.find(node.attr)
            except NameError:
                value_init = None
                if isinstance(value_obj, Instance):
                    value_init = value_obj.cls.init
                elif isinstance(value_obj, Class):
                    value_init = value_obj.init
                if (
                    value_init
                    and value_init is not self.func
                    and not value_init.is_analyzed
                ):
                    raise DependencyError(value_init) from None
                if node is self.assignment_target:
                    raise
                if isinstance(value_obj, Instance) and value_obj.name == "self":
                    self.module.context.attribute_lookup_error(
                        self.func.source_fragment,
                        node,
                        value_obj.cls.name,
                        self.attribute_names(value_obj),
                        value_init.py_func if value_init is not None else None,
                    )
                raise

        return Attribute(
            attr,
            value=value,
            attr=node.attr,
            lineno=node.lineno,
        )

    def visit_Name(self, node: ast.Name):
        try:
            value = self.scope.search(node.id)
        except NameError:
            self.fail_name_lookup(node)
        if node.id == "super":
            return Name(value, id="super")
        elif node.id == "cls" and self.func.cls == value:
            return Name(value, id="this")
        elif node.id != value.name and not getattr(value.py_obj, "__builtin__", False):
            module = (
                self.func.cls.container if self.func.is_method else self.func.container
            )
            if any(
                imported is value and local_name == node.id
                for imported_values in module.imported.values()
                for imported, local_name in imported_values
            ):
                return Name(value, id=node.id)
        return Name(value)

    def visit_Starred(self, node: ast.Starred):
        value = self.visit(node.value)
        item_type = next(iter(value.obj.cls.generic_types.values()))
        return Starred(item_type, value=value)

    def visit_Subscript(self, node: ast.Subscript):
        slice = self.visit(node.slice)
        value = self.visit(node.value)
        receiver_obj = (
            value.value_obj if isinstance(value, (Call, Subscript)) else value.obj
        )
        receiver_type = (
            receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
        )
        if isinstance(slice, ast.Slice):
            method = receiver_obj.find("__slice__")
            if not method.is_analyzed:
                raise DependencyError(method)
            assert isinstance(method.return_type, (Class, UnionType))
            value_obj = method.return_type
            if isinstance(method.return_type, Class):
                value_obj = method.return_type(
                    "__slice_result__", self.scope, self.func
                )
            simple_step = (
                isinstance(slice.step, Constant)
                and slice.step.value in (None, 1)
            )
            if simple_step:
                dependency_objects = {}
            else:
                dependency_objects = self.inline_dependencies(method, node)
            return Call(
                method.return_type,
                value_obj=value_obj,
                func=Attribute(method, value=value, attr="__slice__"),
                args=[slice.lower, slice.upper, slice.step],
                keywords=[],
                dependency_objects=dependency_objects,
            )
        if isinstance(receiver_type, TypedDictClass):
            if not isinstance(slice, Constant) or not isinstance(slice.value, str):
                raise TypeError("TypedDict keys must be string literals.")
            value_type = receiver_type.field_type(slice.value)
            value_obj = value_type
            if isinstance(value_type, Class):
                value_obj = value_type("__subscript_result__", self.scope, self.func)
            return Subscript(
                value_type,
                value_obj=value_obj,
                slice=slice,
                value=value,
            )
        if isinstance(receiver_type, Class) and receiver_type.generic_name == "tuple":
            item_types = list(receiver_type.generic_types.values())
            if isinstance(slice, Constant) and isinstance(slice.value, int):
                value_type = item_types[slice.value]
            else:
                value_type = UnionType(types=item_types).type
            value_obj = value_type
            if isinstance(value_type, Class):
                value_obj = value_type("__subscript_result__", self.scope, self.func)
            return Subscript(
                value_type,
                value_obj=value_obj,
                slice=slice,
                value=value,
            )
        getitem = receiver_obj.find("__getitem__")
        if not getitem.is_analyzed:
            raise DependencyError(getitem)
        assert isinstance(getitem.return_type, (Class, UnionType))
        value_obj = getitem.return_type
        if isinstance(getitem.return_type, Class):
            value_obj = getitem.return_type("__subscript_result__", self.scope, self.func)
        if isinstance(receiver_obj, Instance) and receiver_obj.cls.generic_name == "dict":
            return Call(
                getitem.return_type,
                value_obj=value_obj,
                func=Attribute(getitem, value=value, attr="__getitem__"),
                args=[slice],
                keywords=[],
            )
        return Subscript(
            getitem.return_type,
            value_obj=value_obj,
            slice=slice,
            value=value,
        )

    # endregion

    # region functions

    def dispatch_dunder_call(self, builtin, method_name, args, keywords):
        if not args:
            raise TypeError(f"{builtin.name}() requires an argument")
        receiver_node = args[0]
        receiver_obj = receiver_node.obj
        if isinstance(receiver_obj, Class):
            receiver_obj = receiver_obj._self
        if not isinstance(receiver_obj, Instance) or isinstance(
            receiver_obj.cls, UnionType
        ):
            raise TypeError(f"Cannot dispatch {builtin.name}() on {receiver_obj}.")
        try:
            method = receiver_obj.find(method_name)
        except NameError:
            raise TypeError(
                f"{builtin.name}() is not supported for {receiver_obj.cls.name}."
            ) from None
        assert isinstance(method, Function)
        if not method.is_analyzed:
            raise DependencyError(method)
        expected_type = builtin.return_type if isinstance(builtin, Function) else builtin
        if not is_return_type_compatible(expected_type, method.return_type):
            raise TypeError(
                f"{receiver_obj.cls.name}.{method_name}() returns "
                f"{method.return_type.to_annotation_str()}, expected "
                f"{expected_type.to_annotation_str()}."
            )
        value_obj = method.return_type
        if isinstance(method.return_type, Class):
            value_obj = method.return_type("__call_result__", self.scope, self.func)
        return Call(
            method.return_type,
            value_obj=value_obj,
            func=Attribute(method, value=receiver_node, attr=method_name),
            args=args[1:],
            keywords=keywords,
        )

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
                raise NotImplementedError(
                    "slicing a dict which returns function and calling it"
                )
        else:
            func = self.visit(node.func)

        called_function = None
        if isinstance(func.obj, Instance):
            called_function = func.obj.find("__call__")
            assert isinstance(called_function, Function)
        else:
            assert isinstance(func.obj, (GenericClass, Class, Function))
            if isinstance(func.obj, Function):
                called_function = func.obj
        if (
            called_function is not None
            and not called_function.is_analyzed
            and called_function.declared_return_type is None
        ):
            raise DependencyError(called_function)

        args = [self.visit(arg) for arg in node.args]
        keywords = [
            ast.keyword(arg=kw.arg, value=self.visit(kw.value)) for kw in node.keywords
        ]

        if json_function_name(called_function) == "stringify" and args:
            argument_type = args[0].obj.type
            if contains_python_dict(argument_type):
                raise TypeError(
                    "JSON.stringify() cannot serialize dict; "
                    "use TypedDict for JSON objects."
                )

        dunder_builtin = called_function
        if dunder_builtin is None and isinstance(func.obj, Class) and args:
            dunder_builtin = func.obj
        if dunder_builtin is not None and (
            method_name := getattr(
                dunder_builtin.py_obj, "__js_dunder_dispatch__", None
            )
        ):
            return self.dispatch_dunder_call(
                dunder_builtin, method_name, args, keywords
            )

        if (
            isinstance(func.obj, Function)
            and func.obj.py_func.__name__ == "ref"
            and func.obj.py_func.__module__ == "pyjs.web.domx"
        ):
            assert len(args) == 1 and not keywords, (
                "ref() accepts exactly one positional argument"
            )
            ref_obj = args[0].obj
            ref_type = ref_obj.type
            assert isinstance(ref_type, Class)
            call = Call(
                ref_type,
                value_obj=ref_obj,
                func=func,
                args=args,
                keywords=keywords,
            )
            call.is_ref = True
            return call

        if isinstance(func.obj, Instance):
            return_type = (
                called_function.return_type or called_function.declared_return_type
            )
        elif isinstance(func.obj, Function):
            return_type = func.obj.return_type or func.obj.declared_return_type
        elif isinstance(func.obj, Class):
            return_type = func.obj
        elif isinstance(func.obj, GenericClass):
            # types were not passed, try creating from args
            return_type = func.obj.from_call([a.obj for a in args])
            func = Name(return_type)
        else:
            raise NotImplementedError(f"Don't know how to handle {func.obj} call.")
        if (
            isinstance(func, Attribute)
            and called_function is not None
            and called_function.name == "get"
        ):
            receiver_obj = func.value.obj
            receiver_type = (
                receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
            )
            if isinstance(receiver_type, TypedDictClass) and args:
                key = args[0]
                if isinstance(key, Constant) and isinstance(key.value, str):
                    return_type = receiver_type.field_type(key.value)
                    if key.value not in receiver_type.required_keys:
                        default_type = (
                            args[1].obj.type if len(args) > 1 else get_none_type()
                        )
                        return_type = merge_return_types(return_type, default_type)
        if called_function is not None and called_function.is_async:
            awaitable = BUILTINS.search("Awaitable")
            assert isinstance(awaitable, GenericClass)
            return_type = awaitable(return_type)

        dependency_objects = {}
        if called_function is not None:
            dependency_objects = self.inline_dependencies(called_function, node)
        # TODO: validate that func parameters and the provided arguments are compatible
        value_obj = return_type
        if isinstance(return_type, Class):
            value_obj = return_type("__call_result__", self.scope, self.func)
        return Call(
            return_type,
            value_obj=value_obj,
            func=func,
            args=args,
            keywords=keywords,
            dependency_objects=dependency_objects,
        )

    def infer_parameter_type(self, param, default=None, fallback=None):
        default_type = None
        if default is not None:
            default_type = default.obj
            assert isinstance(default_type, Class)
        annotation_type = None
        if param.annotation is not None:
            annotation_type = self.visit_type_annotation(param.annotation).obj
            assert isinstance(annotation_type, (Class, UnionType))
        arg_type = annotation_type or default_type or fallback
        if arg_type is None:
            self.fail(
                param,
                DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                f"Parameter {param.arg!r} requires a type annotation",
                help=(
                    f"Annotate {param.arg!r} with the value type expected by "
                    "this function."
                ),
            )
        return arg_type

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.func.params = []
        self.func.vararg = None
        self.func.kwonlyargs = []
        self.func.kwarg = None
        self.func.defaults = defaults = [
            self.visit(default) for default in node.args.defaults
        ]
        self.func.kw_defaults = kw_defaults = [
            self.visit(default) if default is not None else None
            for default in node.args.kw_defaults
        ]
        if node.returns is None:
            declared_return_type = None
        elif isinstance(node.returns, ast.Constant) and node.returns.value is None:
            declared_return_type = get_none_type()
        elif isinstance(node.returns, (ast.Subscript, ast.BinOp)) or (
            isinstance(node.returns, ast.Constant)
            and isinstance(node.returns.value, str)
        ):
            declared_return_type = self.visit_type_annotation(node.returns).obj
        else:
            declared_return_type = self.visit(node.returns).obj
        assert declared_return_type is None or isinstance(
            declared_return_type, (Class, UnionType)
        )
        self.func.declared_return_type = declared_return_type
        self.func.inferred_return_type = None
        self.func.return_type = None

        pos_params = node.args.args
        no_defaults = len(pos_params) - len(defaults)
        pos_defaults = [None] * no_defaults + defaults

        if self.func.is_method:
            if self.func.is_classmethod:
                assert pos_params[0].arg == "cls", (
                    "First parameter in classmethod should be cls."
                )
            elif self.func.is_staticmethod:
                pass
            else:
                assert pos_params[0].arg == "self", (
                    "First parameter in method should be self."
                )

        for i, (param, default) in enumerate(zip(pos_params, pos_defaults, strict=True)):
            if i == 0 and param.arg == "self" and self.func.is_method:
                self.func.add_self()
                continue
            if i == 0 and param.arg == "cls" and self.func.is_classmethod:
                self.func.add_cls()
                continue
            arg_type = self.infer_parameter_type(param, default)
            self.func.params.append(
                ast.arg(arg=param.arg, annotation=analyzed_annotation(arg_type))
            )
            self.func.scope.add(arg_type(param.arg, self.func.scope, self.func))

        if node.args.vararg is not None:
            item_type = self.infer_parameter_type(
                node.args.vararg,
                fallback=BUILTINS.search("object"),
            )
            arg_type = BUILTINS.search("tuple")(item_type)
            self.func.vararg = ast.arg(
                arg=node.args.vararg.arg,
                annotation=analyzed_annotation(arg_type),
            )
            self.func.scope.add(
                arg_type(node.args.vararg.arg, self.func.scope, self.func)
            )

        for param, default in zip(node.args.kwonlyargs, kw_defaults, strict=True):
            arg_type = self.infer_parameter_type(param, default)
            self.func.kwonlyargs.append(
                ast.arg(arg=param.arg, annotation=analyzed_annotation(arg_type))
            )
            self.func.scope.add(arg_type(param.arg, self.func.scope, self.func))

        if node.args.kwarg is not None:
            value_type = self.infer_parameter_type(
                node.args.kwarg,
                fallback=BUILTINS.search("object"),
            )
            arg_type = BUILTINS.search("dict")(BUILTINS.search("str"), value_type)
            self.func.kwarg = ast.arg(
                arg=node.args.kwarg.arg,
                annotation=analyzed_annotation(arg_type),
            )
            self.func.scope.add(arg_type(node.args.kwarg.arg, self.func.scope, self.func))
        if should_analyze_func_body(self.func.py_func):
            self.func.body = self.visit_body(node.body)
            final_return_type = self.func.inferred_return_type
            if body_can_fall_through(self.func.body):
                final_return_type = merge_return_types(final_return_type, get_none_type())
            final_return_type = final_return_type or get_none_type()
            if declared_return_type is not None and not is_interface_stub_body(node.body):
                assert is_return_type_compatible(declared_return_type, final_return_type)
            self.func.return_type = declared_return_type or final_return_type
        else:
            if not self.func.name == "__init__":
                assert node.returns, (
                    "Return type annotation required for @js.source and @js.inline"
                )
                self.func.return_type = declared_return_type
            else:
                self.func.return_type = self.func.cls

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self.visit_FunctionDef(node)

    def visit_Await(self, node: ast.Await):
        value = self.visit(node.value)
        awaitable_type = value.obj
        if (
            not isinstance(awaitable_type, Class)
            or awaitable_type.generic_name != "Awaitable"
        ):
            raise TypeError("await requires an async function call")
        awaited_type = awaitable_type.generic_types["T"]
        value_obj = awaited_type
        if isinstance(awaited_type, Class):
            value_obj = awaited_type("__await_result__", self.scope, self.func)
        return Await(
            awaited_type,
            value_obj=value_obj,
            value=value,
        )

    def visit_type_annotation(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            annotation = ast.parse(node.value, mode="eval").body
            ast.copy_location(annotation, node)
            return self.visit_type_annotation(annotation)
        if isinstance(node, ast.Subscript):
            value = self.visit(node.value)
            if isinstance(node.slice, ast.Tuple):
                item_types = [
                    self.visit_type_annotation(elt).obj for elt in node.slice.elts
                ]
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
                UnionType(types=reversed(types)),
                left=node.left,
                op=node.op,
                right=node.right,
            )
        elif isinstance(node, ast.Constant) and node.value is None:
            return self.visit(node)
        else:
            assert isinstance(node, ast.Name)
            return self.visit(node)

    def visit_Pass(self, node: ast.Pass):
        return node

    def visit_Break(self, node: ast.Break):
        return node

    def visit_Continue(self, node: ast.Continue):
        return node

    def visit_Return(self, node: ast.Return):
        value = node.value
        if value is None:
            return_type = get_none_type()
        else:
            value = self.visit(value)
            if isinstance(value.obj, (Class, UnionType)):
                return_type = value.obj
            else:
                assert isinstance(value.obj, Instance)
                return_type = value.obj.cls
        # A partial can specialize a broadly annotated target, such as tag() returning a div.
        if self.func.is_partial_client and self.func.declared_return_type is not None:
            return_type = self.func.declared_return_type
        self.func.inferred_return_type = merge_return_types(
            self.func.inferred_return_type, return_type
        )
        if self.func.declared_return_type is not None:
            assert is_return_type_compatible(self.func.declared_return_type, return_type)
        return ast.Return(value=value)

    def visit_Lambda(self, node: ast.Lambda):
        return ast.Lambda(args=node.args, body=self.visit(node.body))

    # endregion

    # region expressions & operators

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Constant) and node.value.value is Ellipsis:
            return ast.Pass(lineno=node.lineno)
        return ast.Expr(value=self.visit(node.value))

    def visit_JoinedStr(self, node: ast.JoinedStr):
        return JoinedStr(
            BUILTINS.search("str"),
            values=[self.visit(part) for part in node.values],
        )

    def visit_FormattedValue(self, node: ast.FormattedValue):
        value = self.visit(node.value)
        conversion = node.conversion
        if node.format_spec is None and conversion in {-1, ord("r"), ord("s")}:
            method_name = "__repr__" if conversion == ord("r") else "__str__"
            value = self.dispatch_dunder_call(
                BUILTINS.search("str"), method_name, [value], []
            )
            conversion = -1
        return ast.FormattedValue(
            value=value,
            conversion=conversion,
            format_spec=node.format_spec,
        )

    COMPARE_OPS = {
        ast.Is: ("__is__", "__is__"),  # pyjs hack, there is no __is__ in Python
        ast.IsNot: ("__is_not__", "__is_not__"),  # there is no __is_not__ in Python
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
        # TODO: needs cleanup and refactoring
        left = self.visit(node.left)
        if isinstance(left.obj, Instance):
            if isinstance(left.obj.cls, UnionType):
                left_self = left.obj.cls.first._self
            else:
                left_self = left.obj
        elif isinstance(left.obj, UnionType):
            left_self = left.obj.first._self
        else:
            left_self = left.obj._self
        right = self.visit(node.comparators[0])
        if isinstance(right.obj, Instance):
            if isinstance(right.obj.cls, UnionType):
                right_self = right.obj.cls.first._self
            else:
                right_self = right.obj
        elif isinstance(right.obj, UnionType):
            right_self = right.obj.first._self
        else:
            right_self = right.obj._self
        if isinstance(node.ops[0], (ast.In, ast.NotIn)):
            left_self, right_self = right_self, left_self
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
        comparison = Call(
            func.return_type,
            func=Attribute(func, value=left, attr=func.name),
            args=[right],
            keywords=[],
            operator=node.ops[0],
        )
        if isinstance(node.ops[0], ast.NotIn):
            return UnaryOp(func.return_type, op=ast.Not(), operand=comparison)
        return comparison

    BIN_OPS = {
        ast.Add: ("__add__", "__radd__"),
        ast.Sub: ("__sub__", "__rsub__"),
        ast.Mult: ("__mul__", "__rmul__"),
        ast.Div: ("__truediv__", "__rtruediv__"),
        ast.FloorDiv: ("__floordiv__", "__rfloordiv__"),
        ast.Mod: ("__mod__", "__rmod__"),
        ast.Pow: ("__pow__", "__rpow__"),
        ast.BitOr: ("__or__", "__ror__"),
    }

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        left_self = left.obj if isinstance(left.obj, Instance) else left.obj._self
        right = self.visit(node.right)
        right_self = right.obj if isinstance(right.obj, Instance) else right.obj._self
        left_op_method, right_op_method = self.BIN_OPS[type(node.op)]
        reverse = False
        try:
            func = left_self.find(left_op_method)
            assert isinstance(func, Function)
            if right_self.cls not in get_type_members(func.params[0].annotation.obj):
                # this is the equivalent of the op function returning NotImplemented
                raise NameError
        except NameError:
            func = right_self.find(right_op_method)
            left, right = right, left
            reverse = True
        return Call(
            func.return_type,
            func=Attribute(func, value=left, attr=func.name),
            args=[right],
            keywords=[],
            operator=node.op,
            reverse=reverse,
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
        operand_type = (
            operand.obj.cls if isinstance(operand.obj, Instance) else operand.obj
        )
        if isinstance(node.op, (ast.UAdd, ast.USub)) and operand_type.name in (
            "int",
            "float",
        ):
            return UnaryOp(operand_type, op=node.op, operand=operand)
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
                        func=Attribute(func, value=operand, attr=func.name),
                        args=[],
                        keywords=[],
                    ),
                )
        raise NotImplementedError

    def visit_BoolOp(self, node: ast.BoolOp):
        values = []
        visitor = self
        evaluate_next_when_true = isinstance(node.op, ast.And)
        for value in node.values:
            values.append(visitor.visit(value))
            visitor = visitor.narrow_for_condition(value, evaluate_next_when_true)
        value_types = UnionType()
        for index, value in enumerate(values):
            obj_type = value.obj.type
            types = obj_type.types if isinstance(obj_type, UnionType) else [obj_type]
            for type_ in types:
                assert isinstance(type_, Class)
                if (
                    isinstance(node.op, ast.Or)
                    and index < len(values) - 1
                    and type_.name == "NoneType"
                ):
                    continue
                value_types.add(type_)
        return BoolOp(value_types.type, op=node.op, values=values)

    # endregion

    # region constants

    def visit_Constant(self, node: ast.Constant):
        type_name = type(node.value).__name__
        type_cls = BUILTINS.search(type_name)
        assert isinstance(type_cls, Class)
        return Constant(type_cls, value=node.value)

    def visit_Tuple(self, node: ast.Tuple):
        generic_tuple = BUILTINS.search("tuple")
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
        generic_list = BUILTINS.search("list")
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
        for key, value in zip(node.keys, node.values, strict=True):
            keys.append(self.visit(key))
            K.add(keys[-1].obj)
            values.append(self.visit(value))
            V.add(values[-1].obj.type)
        dict_type = generic_dict(K.type, V.type) if K.types and V.types else generic_dict
        return Dict(dict_type, keys=keys, values=values)

    # endregion

    # region looping

    def visit_While(self, node: ast.While):
        test = self.visit(node.test)
        body = self.visit_body(node.body)
        orelse = self.visit(node.orelse) if node.orelse else node.orelse
        return ast.While(
            test=test,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )

    def visit_For(self, node: ast.For):
        node_iter = self.visit(node.iter)

        iter_obj = node_iter.value_obj if isinstance(node_iter, Call) else node_iter.obj
        iter_type = iter_obj.cls if isinstance(iter_obj, Instance) else iter_obj
        if isinstance(iter_type, TypedDictClass):
            keys = iter_obj.find("keys")
            node_iter = Call(
                keys.return_type,
                func=Attribute(keys, value=node_iter, attr="keys"),
                args=[],
                keywords=[],
            )

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
            for val, val_type in zip(node.target.elts, types, strict=True):
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

    def visit_Try(self, node: ast.Try):
        if node.orelse:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "try/else is not supported",
                help="Move the else body after the try statement or use explicit state.",
            )
        if len(node.handlers) > 1:
            self.fail(
                node.handlers[1],
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "multiple except handlers are not supported",
                help="Combine the exception handling into one except block.",
            )
        handlers = []
        for handler in node.handlers:
            handler_type = None
            if handler.type is None:
                if handler.name is not None:
                    raise NotImplementedError("bare except cannot bind an exception")
            elif not isinstance(handler.type, ast.Name) or handler.type.id != "Exception":
                self.fail(
                    handler,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "only bare except or except Exception is supported",
                    help="Catch Exception and inspect the value inside the handler.",
                )
            else:
                handler_type = self.visit(handler.type)
            if handler.name is not None:
                exception_type = handler_type.obj
                assert isinstance(exception_type, Class)
                self.scope.add(exception_type(handler.name, self.scope, self.func))
            handlers.append(
                ast.ExceptHandler(
                    type=handler_type,
                    name=handler.name,
                    body=self.visit_body(handler.body),
                )
            )
        return ast.Try(
            body=self.visit_body(node.body),
            handlers=handlers,
            orelse=[],
            finalbody=self.visit_body(node.finalbody),
            lineno=node.lineno,
        )

    def visit_ListComp(self, node: ast.ListComp):
        gen = node.generators[0]
        iter_node = self.visit(gen.iter)
        visitor = type(self)(self.func, LocalScope(self.scope))
        if isinstance(gen.target, ast.Name):
            iter_cls = iter_node.obj
            if isinstance(iter_cls, Instance):
                iter_cls = iter_cls.cls
            item_type = next(iter(iter_cls.generic_types.values()))
            if isinstance(item_type, UnionType):
                # TODO: don't just pick the first type here
                item_type = next(iter(item_type.types))
            visitor.scope.add(
                item_type(gen.target.id, visitor.scope, self.func)
            )
        else:
            raise NotImplementedError
        target = visitor.visit(gen.target)
        conditions = [visitor.visit(condition) for condition in gen.ifs]
        elt = visitor.visit(node.elt)
        generator = ast.comprehension(
            target=target,
            iter=iter_node,
            ifs=conditions,
            is_async=gen.is_async,
        )
        return ListComp(
            BUILTINS.search("list")(item_type),
            elt=elt,
            generators=[generator],
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
                func=Attribute(func, value=test, attr=func.name),
                args=[],
                keywords=[],
            )
        body_visitor = self.narrow_for_condition(node.test, True)
        orelse_visitor = self.narrow_for_condition(node.test, False)
        if (
            isinstance(test, Call)
            and isinstance(test.func, Name)
            and test.func.id == "isinstance"
        ):
            args = test.args
            assert len(args) == 2
            assert isinstance(args[0], (ast.Name, ast.Attribute))
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
            body_visitor = self.narrow(args[0], value_type)
        body = body_visitor.visit_body(node.body)
        orelse = orelse_visitor.visit_body(node.orelse)
        return ast.If(
            test=test,
            body=body,
            orelse=orelse,
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
                func=Attribute(func, value=node.test, attr=func.name),
                args=[],
                keywords=[],
            )
        body_visitor = self.narrow_for_condition(node.test, True)
        orelse_visitor = self.narrow_for_condition(node.test, False)
        body = body_visitor.visit(node.body)
        orelse = orelse_visitor.visit(node.orelse)
        result_type = body.obj.type
        assert result_type == orelse.obj.type
        return IfExp(
            result_type,
            test=test,
            body=body,
            orelse=orelse,
        )

    def visit_Assert(self, node: ast.Assert):
        test = self.visit(node.test)
        return ast.Assert(test=test, msg=node.msg)

    def visit_Raise(self, node: ast.Raise):
        exc = self.visit(node.exc) if node.exc is not None else None
        return ast.Raise(exc=exc, cause=node.cause)

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

    def enter_virtual(self, func: Function):
        self.enter(func)
        if self.entry_point in func.virtual_visited:
            return
        func.virtual_visited.add(self.entry_point)
        self.enter_overrides(func, func.cls)

    def enter_overrides(self, func: Function, cls: Class):
        for subclass in cls.subclasses:
            if self.entry_point not in subclass.visited:
                continue
            override = subclass.find_attrs(func.name, search_bases=False)
            if isinstance(override, Function):
                self.enter_virtual(override)
            else:
                self.enter_overrides(func, subclass)

    def enter_class(self, cls: Class):
        while cls is not None:
            if self.entry_point not in cls.visited:
                cls.visited.add(self.entry_point)
                for attr in cls.children:
                    if not isinstance(attr, Function):
                        continue
                    if has_include_decorator(attr.py_obj) or self.parent_has_include(
                        attr
                    ):
                        self.isolated_visit(attr)
                    elif self.parent_is_virtual(attr):
                        self.enter_virtual(attr)
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

    def parent_is_virtual(self, obj):
        if isinstance(obj, Function):
            parent = obj.cls.super
            while parent is not None:
                parent_func = parent.find_attrs(obj.name, search_bases=False)
                if (
                    parent_func is not None
                    and self.entry_point in parent_func.virtual_visited
                ):
                    return True
                parent = parent.super
        return False

    @staticmethod
    def is_virtual_method_reference(node):
        if not isinstance(node, ast.Attribute) or not node.obj.is_method:
            return False
        receiver = node.value
        if isinstance(receiver, Name) and isinstance(receiver.obj, Class):
            return False
        if isinstance(receiver, Call):
            if isinstance(receiver.func, Name) and receiver.func.id == "super":
                return False
            if isinstance(receiver.func.obj, Class):
                return False
        return True

    def isolated_visit(self, func: Function):
        assert isinstance(func, Function)
        if (
            not has_source_decorator(func.py_func)
            and self.entry_point not in func.visited
        ):
            type(self)(func, self.entry_point).visit(func.node)

    def visit_FunctionDef(self, node: FunctionDef):
        node.obj.visited.add(self.entry_point)
        for arg in node.args.args:
            self.visit(arg)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, Name) and node.func.id == "tw":
            self.entry_point.tailwind_classes.update(
                set(node.args[0].value.split(" ")),
            )
        func = node.func.obj
        module = self.func.cls.container if self.func.is_method else self.func.container
        for name, dependency in getattr(node, "dependency_objects", {}).items():
            node.inline_dependencies[name] = module.register_inline_dependency(
                dependency
            )
            self.enter(dependency)
        if isinstance(func, Function):
            self.enter(func)
        elif isinstance(func, Instance):
            pass
        elif isinstance(func, Class):
            self.enter_class(func)
            self.enter(func.find("__init__"))
        else:
            raise NotImplementedError(f"Can't call {node.func}.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.obj, Function):
            if self.is_virtual_method_reference(node):
                self.enter_virtual(node.obj)
            else:
                self.enter(node.obj)
        elif isinstance(node.obj, Instance):
            node.obj.visited.add(self.entry_point)
        self.generic_visit(node)

    def visit_Name(self, node: Name):
        if hasattr(node, "obj"):
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


def from_entry_point(
    entry_point: callable,
    extensions: tuple[CompilationExtension, ...] = (),
    additional_entry_points: tuple[callable, ...] = (),
):
    entry_point.__js__ = True
    for additional_entry_point in additional_entry_points:
        additional_entry_point.__js__ = True
    py_module = inspect.getmodule(entry_point)
    return analyze_module(
        py_module,
        entry_point,
        extensions=extensions,
        additional_entry_points=additional_entry_points,
    )


def analyze_module(
    py_module,
    entry_point=None,
    extensions: tuple[CompilationExtension, ...] = (),
    additional_entry_points: tuple[callable, ...] = (),
):
    if entry_point is None:
        assert hasattr(py_module, "main"), (
            "No entry_point specified and no main() function found."
        )
        py_module.main.__js__ = True
        entry_point = py_module.main
    package = {}
    context = CompilationContext()
    module = Module(
        py_module,
        package,
        extensions=extensions,
        context=context,
    ).build()
    package[module.name] = module
    annotated = set()
    while pending := [value for value in package.values() if value not in annotated]:
        for imported in pending:
            annotate_types(imported)
            annotated.add(imported)
    entry_point_function, tailwind_classes = visit_entry_point(module, entry_point)
    for additional_entry_point in additional_entry_points:
        additional_entry_point_function, additional_tailwind_classes = visit_entry_point(
            module,
            additional_entry_point,
        )
        additional_entry_point_function.visited.discard(
            additional_entry_point_function
        )
        tailwind_classes.update(additional_tailwind_classes)
    entry_point_function.visited.discard(entry_point_function)
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
                    raise TypeError(
                        f"Cannot handle dependency of type {type(e.class_or_func)}."
                    ) from e
                added = True
        if not added:
            break
        functions = dependencies.static_order()


def load_builtins():
    from . import _builtins

    for name, value in list(vars(_builtins).items()):
        if (
            name.startswith("_")
            and not name.startswith("__")
            and is_cls_or_func(value)
        ):
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

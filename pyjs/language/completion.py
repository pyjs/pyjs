"""Cursor queries over the compiler's lexical scopes and inferred receivers."""

import ast
import io
import tokenize
import unicodedata
from dataclasses import replace
from functools import cache
from pathlib import Path

from pyjs.analysis.analyzer import (
    JS_ENVIRONMENT,
    JavaScriptInferenceVisitor,
    analyzed_value_object,
    release_compilation,
)
from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.analysis.objects import (
    Class,
    DependencyError,
    Function,
    Instance,
    ModuleAlias,
    UnionType,
)
from pyjs.language.queries import analyze_cursor
from pyjs.language.snapshots import type_text


class CompletionFound(BaseException):
    def __init__(self, items, truncated):
        self.result = {"items": items, "truncated": truncated}


def completion_environment(path: Path, source: str, line: int, column: int, replacement=None):
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    lines = source.split('\n')
    token = next((item for item in tokenize.generate_tokens(io.StringIO(source).readline)
                  if item.type == tokenize.NAME and item.start[0] == line
                  and item.start[1] <= column <= item.end[1]), None)

    captured = {}

    @cache
    def selected_file(filename):
        return Path(filename).resolve() == path

    class CompletionVisitor(JavaScriptInferenceVisitor):
        def visit_FunctionDef(self, node):
            fragment = self.func.source_fragment
            if fragment is None or not selected_file(fragment.source.filename):
                return super().visit_FunctionDef(node)
            # A provisional traversal can narrow a loop receiver incorrectly.
            # Publish only after the compiler has applied all flow widenings.
            captured[self.func] = []
            result = super().visit_FunctionDef(node)
            answers = captured[self.func]
            if answers and not self.pending_flow_widenings:
                common = set.intersection(*(set(items) for items, _ in answers))
                items = []
                for name in sorted(common):
                    variants = [answer[name] for answer, _ in answers]
                    item = variants[0].copy()
                    item['detail'] = ' | '.join(dict.fromkeys(value['detail'] for value in variants))
                    items.append(item)
                raise CompletionFound(items, any(truncated for _, truncated in answers))
            return result

        def selected(self, node):
            fragment = self.func.source_fragment
            if (self.func not in captured or token is None or fragment is None
                    or not hasattr(node, 'end_lineno')):
                return False
            row = node.end_lineno + fragment.line_delta
            if row != token.end[0]:
                return False
            end = len(lines[row - 1].encode()[:node.end_col_offset + fragment.column_delta].decode())
            return end == token.end[1]

        def answer(self, values):
            prefix = unicodedata.normalize('NFKC', lines[line - 1][token.start[1]:column])
            names = sorted(name for name in values if name.isidentifier()
                           and name.startswith(prefix) and name != '__pyjs_editor_entry__'
                           and (not name.startswith('_') or prefix.startswith('_')))
            items = []
            for name in names[:256]:
                variants = values[name] if isinstance(values[name], tuple) else (values[name],)
                descriptions = [self.describe(name, value) for value in variants]
                kinds = {kind for kind, _ in descriptions}
                kind = next(iter(kinds)) if len(kinds) == 1 else 'variable'
                detail = ' | '.join(dict.fromkeys(detail for _, detail in descriptions))
                items.append({'label': name, 'kind': kind, 'detail': detail, 'text': name,
                              'startColumn': token.start[1], 'endColumn': token.end[1]})
            captured[self.func].append(({item['label']: item for item in items}, len(names) > 256))

        def describe(self, name, value):
            kind = ('class' if isinstance(value, Class) else
                    'property' if isinstance(value, Function) and value.is_property else
                    'function' if isinstance(value, Function) else 'variable')
            if isinstance(value, Function):
                if value is not self.func and (not value.signature_analyzed
                        or value.return_type is None and value.declared_return_type is None):
                    raise DependencyError(value)
                result = type_text(value.return_type or value.declared_return_type)
                if value.is_property:
                    return kind, name + ': ' + result
                parameters = [ast.unparse(parameter) for parameter in value.params]
                return kind, name + '(' + ', '.join(parameters) + ') -> ' + result
            try:
                return kind, name + ': ' + type_text(value if isinstance(value, Class) else value.type)
            except (AttributeError, TypeError, ValueError):
                return kind, name

        def query_value(self, node):
            if isinstance(node, ast.Attribute):
                receiver = self.visit(node.value)
                self.answer(self.members(analyzed_value_object(receiver)))
                return receiver
            values = {}
            scope = self.scope
            while scope is not None:
                for name, value in scope.names.items():
                    values.setdefault(name, value)
                scope = scope.parent
            for name, value in self.module.scope.BUILTINS.scope.names.items():
                values.setdefault(name, value)
            self.answer(values)
            return self.visit(ast.Constant(value=None))

        def query_expression(self, node):
            # Discard a partial expression's result only when no later binding
            # can depend on it. Receiver/argument analysis still feeds flow;
            # these temporary nodes must never reach a compiled application.
            if replacement is not None:
                return None
            target = node.func if isinstance(node, ast.Call) else node
            if not isinstance(target, (ast.Name, ast.Attribute)) or not self.selected(target):
                return None
            value = self.query_value(target)
            if isinstance(node, ast.Call):
                arguments = [self.visit(argument) for argument in node.args]
                arguments.extend(self.visit(keyword.value) for keyword in node.keywords)
                return ast.Tuple(elts=[value, *arguments], ctx=ast.Load())
            return value

        def visit_Name(self, node):
            if self.selected(node) and isinstance(node.ctx, ast.Load):
                self.query_value(node)
                if replacement is not None:
                    original = node.id
                    node.id = replacement
                    try:
                        return super().visit_Name(node)
                    finally:
                        node.id = original
            return super().visit_Name(node)

        def visit_Attribute(self, node):
            if self.selected(node) and isinstance(node.ctx, ast.Load):
                self.query_value(node)
                if replacement is not None:
                    original = node.attr
                    node.attr = replacement
                    try:
                        return super().visit_Attribute(node)
                    finally:
                        node.attr = original
            return super().visit_Attribute(node)

        def visit_Expr(self, node):
            value = self.query_expression(node.value)
            if value is not None:
                return ast.Expr(value=value)
            return super().visit_Expr(node)

        def visit_Return(self, node):
            if self.func.is_generator:
                return super().visit_Return(node)
            value = self.query_expression(node.value)
            if value is not None:
                return ast.Return(value=value)
            return super().visit_Return(node)

        def members(self, value):
            union = value if isinstance(value, UnionType) else self.receiver_union(value)
            if union is not None:
                members = [self.members(member._self) for member in union.types]
                common = set.intersection(*(set(item) for item in members)) if members else set()
                return {name: tuple(item[name] for item in members) for name in common}
            if isinstance(value, ModuleAlias):
                return value.target.scope.names
            if not isinstance(value, (Class, Instance)):
                return {}
            if isinstance(value, Instance):
                for name in ('__init__', 'initialize'):
                    initializer = value.cls.find_attrs(name)
                    if (isinstance(initializer, Function) and initializer is not self.func
                            and not initializer.is_analyzed):
                        raise DependencyError(initializer)
            values = {}
            for name in self.attribute_names(value):
                try:
                    values[name] = value.find(name)
                except NameError:
                    continue
            return values

    return replace(JS_ENVIRONMENT, inference_visitor=CompletionVisitor), captured


def complete_module(module, entry_point, path: Path, source: str, line: int, column: int):
    environment, captured = completion_environment(path, source, line, column)
    try:
        entry, _ = analyze_cursor(module, entry_point, environment, path, line)
    except CompletionFound as completion:
        return completion.result
    except CompilationError as error:
        if (error.diagnostic.code not in (DiagnosticCode.UNDEFINED_NAME, DiagnosticCode.UNDEFINED_ATTRIBUTE)
                or Path(error.filename).resolve() != path or not error.lineno <= line <= error.end_lineno
                or (line == error.lineno and column < error.offset - 1)
                or (line == error.end_lineno and column > error.end_offset - 1)):
            raise
        candidates = {}
        truncated = False
        for answers in captured.values():
            for items, limited in answers:
                candidates.update(items)
                truncated = truncated or limited
        if not captured:
            raise
        verified = []
        # A candidate may change a later binding's type or a loop proof. Analyze
        # each alternative normally, without rerunning module initialization.
        for name in sorted(candidates):
            candidate_environment, _ = completion_environment(path, source, line, column, name)
            try:
                entry, _ = analyze_cursor(module, entry_point, candidate_environment, path, line)
            except CompletionFound as completion:
                verified.extend(item for item in completion.result['items'] if item['label'] == name)
            except CompilationError:
                continue
            else:
                release_compilation(entry)
        return {'items': verified, 'truncated': truncated}
    else:
        release_compilation(entry)
        return {'items': [], 'truncated': False,
                'message': 'Place the cursor in a name or member in a compiled function'}

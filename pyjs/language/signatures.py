"""Call signatures from resolved compiler calls in a valid source generation."""

import ast
import inspect
from dataclasses import replace
from functools import cache
from pathlib import Path

from pyjs.analysis.analyzer import (
    JS_ENVIRONMENT,
    JavaScriptInferenceVisitor,
    analyzed_value_object,
    release_compilation,
    substitute_type_variables,
)
from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.analysis.objects import Class
from pyjs.analysis.type_relations import contains_type_variable, merge_return_types
from pyjs.language.queries import analyze_cursor
from pyjs.language.snapshots import type_text


class SignaturesFound(BaseException):
    def __init__(self, signatures):
        self.result = {'signatures': signatures[:20], 'truncated': len(signatures) > 20}


def signatures_module(module, entry_point, path: Path, source: str, line: int, column: int):
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    lines = source.split('\n')
    cursor = (line, column)

    def position(node, end=False, fragment=None):
        row = node.end_lineno if end else node.lineno
        byte = node.end_col_offset if end else node.col_offset
        if fragment is not None:
            row += fragment.line_delta
            byte += fragment.column_delta
        return row, len(lines[row - 1].encode()[:byte].decode())

    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
             and position(node.func, True) <= cursor < position(node, True)]
    if not calls:
        return {'signatures': []}
    selected = max(calls, key=position)
    call_span = (position(selected), position(selected, True))
    collected = {}
    declarations_only = False

    @cache
    def selected_file(filename):
        return Path(filename).resolve() == path

    class SignatureVisitor(JavaScriptInferenceVisitor):
        def visit_FunctionDef(self, node):
            fragment = self.func.source_fragment
            if fragment is None or not selected_file(fragment.source.filename):
                return super().visit_FunctionDef(node)
            collected[self.func] = []
            result = super().visit_FunctionDef(node)
            if collected[self.func] and not self.pending_flow_widenings:
                unique = {item['label']: item for item in collected[self.func]}
                raise SignaturesFound(list(unique.values()))
            return result

        def query_expression(self, node, *, consumed=False):
            if not declarations_only or not isinstance(node, ast.Call) or not self.matches(node):
                return None
            target = self.visit_call_function(node)
            call_target = analyzed_value_object(target)
            function, signature = self.resolve_called_function(node, target, call_target)
            self.ensure_call_signature_ready(node, function)
            return_type = None
            if signature is not None:
                self.capture_callable(signature, signature.return_type, {})
                return_type = signature.return_type
            elif function is not None:
                overloads, _, _ = self.initial_call_signature(node, function)
                alternatives = getattr(target, 'union_functions', ()) or overloads or (function,)
                for alternative in alternatives:
                    self.ensure_call_signature_ready(node, alternative)
                    result = call_target if isinstance(call_target, Class) else (
                        alternative.return_type or alternative.declared_return_type)
                    self.capture(alternative, result, {})
                    return_type = result if return_type is None else merge_return_types(return_type, result)
            arguments = [self.visit(argument.value if isinstance(argument, ast.Starred) else argument)
                         for argument in node.args]
            keywords = [ast.keyword(arg=keyword.arg, value=self.visit(keyword.value))
                        for keyword in node.keywords]
            if return_type is not None and not contains_type_variable(return_type):
                result, representation = self.apply_call_result_modifiers(target, function, return_type, None)
                return self.build_call_node(node, func=target, call_target=call_target,
                    callable_signature=signature, signature_function=function, called_function=function,
                    return_type=result, return_representation=representation, args=arguments,
                    keywords=keywords, runtime_methods=(), is_super_method_call=False)
            if consumed:
                return None
            # Only discard a queried call when no later binding consumes it.
            # The second traversal still resolves loop and exception flow.
            return ast.Tuple(elts=[target, *arguments, *(keyword.value for keyword in keywords)], ctx=ast.Load())

        def visit_Call(self, node):
            value = self.query_expression(node, consumed=True)
            return value if value is not None else super().visit_Call(node)

        def visit_Expr(self, node):
            value = self.query_expression(node.value)
            return ast.Expr(value=value) if value is not None else super().visit_Expr(node)

        def visit_Return(self, node):
            if self.func.is_generator:
                return super().visit_Return(node)
            value = self.query_expression(node.value)
            return ast.Return(value=value) if value is not None else super().visit_Return(node)

        def matches(self, node):
            fragment = self.func.source_fragment
            return (self.func in collected and fragment is not None and hasattr(node, 'end_lineno')
                    and (position(node, fragment=fragment), position(node, True, fragment)) == call_span)

        def resolve_call_return_type(self, node, func, call_target, callable_signature,
                                     signature_function, called_function, args, keywords,
                                     type_bindings):
            result = super().resolve_call_return_type(node, func, call_target, callable_signature,
                signature_function, called_function, args, keywords, type_bindings)
            if self.matches(node):
                function = result[2] or signature_function or called_function
                if callable_signature is not None:
                    self.capture_callable(callable_signature, result[1], type_bindings)
                elif getattr(func, 'union_functions', ()):
                    for alternative in func.union_functions:
                        self.capture(alternative, substitute_type_variables(
                            alternative.return_type or alternative.declared_return_type, type_bindings),
                            type_bindings)
                elif function is not None:
                    self.capture(function, result[1], type_bindings)
            return result

        def capture_callable(self, signature, return_type, bindings):
            if signature.parameter_types is None:
                names, labels, vararg_index = ['args'], ['*args: object'], 0
            else:
                names = [f'arg{index}' for index in range(len(signature.parameter_types))]
                labels = [name + ': ' + type_text(substitute_type_variables(value, bindings))
                          for name, value in zip(names, signature.parameter_types, strict=True)]
                vararg_index = None
            self.publish(names, labels, labels, len(names), vararg_index, None, return_type, '')

        def capture(self, function, return_type, bindings):
            original = function.original_node.args
            positional = [*original.posonlyargs, *original.args]
            defaults = {parameter.arg: ast.unparse(default) for parameter, default in
                        zip(positional[len(positional) - len(original.defaults):], original.defaults, strict=True)}
            defaults.update({parameter.arg: ast.unparse(default) for parameter, default in
                zip(original.kwonlyargs, original.kw_defaults, strict=True) if default is not None})
            labels, names, display = [], [], []

            def parameter(argument, prefix=''):
                value = function.scope.search(argument.arg).type
                if prefix == '*':
                    value = next(iter(value.generic_types.values()))
                elif prefix == '**':
                    value = value.generic_types['V']
                value = substitute_type_variables(value, bindings)
                label = prefix + argument.arg + ': ' + type_text(value)
                if argument.arg in defaults:
                    label += ' = ' + defaults[argument.arg]
                names.append(argument.arg)
                labels.append(label)
                display.append(label)

            for index, argument in enumerate(function.params):
                parameter(argument)
                if index + 1 == function.posonly_count:
                    display.append('/')
            vararg_index = None
            if function.vararg is not None:
                vararg_index = len(labels)
                parameter(function.vararg, '*')
            elif function.kwonlyargs:
                display.append('*')
            for argument in function.kwonlyargs:
                parameter(argument)
            kwarg_index = None
            if function.kwarg is not None:
                kwarg_index = len(labels)
                parameter(function.kwarg, '**')
            self.publish(names, labels, display, len(function.params), vararg_index, kwarg_index,
                return_type, (inspect.getdoc(function.py_func) or '')[:2000])

        def publish(self, names, labels, display, positional_count, vararg_index, kwarg_index,
                    return_type, documentation):
            def width(arguments):
                count = 0
                for argument in arguments:
                    if isinstance(argument, ast.Starred):
                        if not isinstance(argument.value, (ast.Tuple, ast.List)):
                            return None
                        size = width(argument.value.elts)
                        if size is None:
                            return None
                        count += size
                    else:
                        count += 1
                return count

            def positional(index):
                if index is None:
                    return None
                if vararg_index is not None:
                    return min(index, vararg_index)
                return index if index < positional_count else None

            active = None
            supplied = sorted([*selected.args, *selected.keywords], key=position)
            argument = next((item for item in supplied if cursor <= position(item, True)), None)
            if isinstance(argument, ast.keyword):
                active = names.index(argument.arg) if argument.arg in names else kwarg_index
            elif argument is not None and not isinstance(argument, ast.Starred):
                active = positional(width(selected.args[:selected.args.index(argument)]))
            elif argument is None and not selected.keywords:
                active = positional(width(selected.args))
            label = ast.unparse(selected.func) + '(' + ', '.join(display) + ') -> ' + type_text(return_type)
            collected[self.func].append({'label': label, 'parameters': labels,
                'activeParameter': active, 'documentation': documentation})

    environment = replace(JS_ENVIRONMENT, inference_visitor=SignatureVisitor)
    for declarations_only in (False, True):
        try:
            entry, _ = analyze_cursor(module, entry_point, environment, path, line)
        except SignaturesFound as signatures:
            return signatures.result
        except CompilationError as error:
            if (declarations_only or error.diagnostic.code != DiagnosticCode.INCOMPATIBLE_ARGUMENT
                    or Path(error.filename).resolve() != path
                    or not selected.lineno <= error.lineno <= selected.end_lineno):
                raise
            collected.clear()
        else:
            release_compilation(entry)
            return {'signatures': []}

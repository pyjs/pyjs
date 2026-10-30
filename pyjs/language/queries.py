"""Analyze a cursor's function and its compiler dependencies."""

from dataclasses import replace
from functools import cache
from pathlib import Path

from pyjs.analysis.analyzer import analyze_module, annotate_types, flatten_objects


def analyze_cursor(module, entry_point, environment, path, line):
    @cache
    def selected_file(filename):
        return Path(filename).resolve() == path

    class CursorVisitor(environment.inference_visitor):
        def visit_FunctionDef(self, node):
            if self.func.py_func is entry_point:
                candidates = []
                for function in flatten_objects(self.module):
                    code = getattr(function.py_func, '__code__', None)
                    if code is None or not selected_file(code.co_filename):
                        continue
                    original = function.original_node
                    fragment = function.source_fragment
                    if fragment is None:
                        continue
                    start = original.lineno + fragment.line_delta
                    end = original.end_lineno + fragment.line_delta
                    if start <= line <= end:
                        candidates.append((end - start, function))
                if candidates:
                    annotate_types(min(candidates, key=lambda item: item[0])[1])
            return super().visit_FunctionDef(node)

    return analyze_module(module, entry_point=entry_point, environment=replace(
        environment, analyze_all_definitions=False, inference_visitor=CursorVisitor))

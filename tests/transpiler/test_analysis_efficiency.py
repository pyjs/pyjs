"""Traversal bounds and source fidelity for cold inference."""

import ast
import gc
import weakref
from dataclasses import replace

import pytest

from pyjs import int8
from pyjs.analysis.analyzer import JS_ENVIRONMENT, InferenceVisitor
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.objects import Class, Function, Instance, Object, Scope
from pyjs.analysis.representation import annotation_representation
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.javascript.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


def test_first_field_assignment_retains_its_complete_source_span():
    source = ("from pyjs import js\n@js\nclass Item:\n"
              "    def __init__(self):\n        self.value = 42\n"
              "def main():\n    return Item().value\n")
    with analyze_source(source) as analysis:
        cls = analysis.entry_point.container.scope.names["Item"]
        target = cls.init.node.body[0].targets[0]
        fragment = cls.init.source_fragment
        assert (target.lineno + fragment.line_delta, target.col_offset + fragment.column_delta,
                target.end_lineno + fragment.line_delta, target.end_col_offset + fragment.column_delta) == (5, 8, 5, 18)
        assert target.obj.cls.name == "int"


def test_write_summary_preserves_scope_boundaries_and_receiver_writes(monkeypatch):
    visited = []
    statement = ast.parse('''
if enabled:
    receiver.child.value = 1
    receiver = replacement
    del old.value
    while (current := next_value()):
        total += current
    values = [item for item in source]
    def deferred():
        hidden = 1
''').body[0]
    original = ast.iter_child_nodes

    def children(node):
        visited.append(node)
        return original(node)

    visitor = object.__new__(InferenceVisitor)
    visitor.written_names = {}
    monkeypatch.setattr(ast, "iter_child_nodes", children)
    expected = frozenset(("receiver.child.value", "receiver", "old.value", "current", "total", "values"))
    assert visitor.statement_writes(statement) == expected
    scans = len(visited)
    assert visitor.statement_writes(statement) == expected
    assert len(visited) == scans
    # A separate inference attempt gets a fresh summary for changed source.
    other = object.__new__(InferenceVisitor)
    other.written_names = {}
    assert other.statement_writes(ast.parse("different = 1").body[0]) == frozenset(("different",))


@pytest.mark.parametrize("annotation", ["int | str | None", "Union[int, str, None]", "Optional[Union[int, str]]"])
def test_unrepresented_unions_do_not_repeat_member_type_analysis(annotation):
    repeated = []

    class CountingInference(InferenceVisitor):
        checking_representation = False

        def union_annotation_representation(self, elements, **kwargs):
            previous = self.checking_representation
            self.checking_representation = True
            try:
                return super().union_annotation_representation(elements, **kwargs)
            finally:
                self.checking_representation = previous

        def visit_type_annotation(self, node):
            if self.checking_representation:
                repeated.append(ast.unparse(node))
            return super().visit_type_annotation(node)

    with analyze_source(
        f"from typing import Optional, Union\ndef main(value: {annotation}) -> int:\n    return 1\n",
        environment=replace(JS_ENVIRONMENT, inference_visitor=CountingInference),
    ) as analysis:
        assert analysis.types == "def main(value: int | str | None) -> int:\n    return 1"
        assert analysis.javascript == "export function main(value) {\n    return 1;\n}"
        assert analysis.entry_point.params[0].representation is None
    assert repeated == []


@pytest.mark.parametrize("annotation", ["int | missing", "Union[int, missing]", "Optional[missing]"])
def test_unrepresented_union_still_reports_invalid_member_annotations(annotation):
    with pytest.raises((CompilationError, NameError), match="missing"):
        with analyze_source(
            f"from typing import Optional, Union\ndef main(value: {annotation}) -> int:\n    return 1\n"
        ):
            pass


@pytest.mark.parametrize("environment, annotation", [
    pytest.param(JS_ENVIRONMENT, "str | ByteOrNone | str", id="javascript"),
    pytest.param(JS_ENVIRONMENT, "Union[str, ByteOrNone, str]", id="javascript-typing-union"),
    pytest.param(NATIVE_ENVIRONMENT, "str | ByteOrNone | str", id="llvm"),
    pytest.param(JVM_ENVIRONMENT, "str | ByteOrNone | str", id="jvm"),
    pytest.param(WEBASSEMBLY_ENVIRONMENT, "str | ByteOrNone | str", id="wasm"),
])
def test_represented_union_keeps_flattened_member_positions(environment, annotation):
    with analyze_source(
        "from pyjs import int8\nfrom typing import Union\ntype ByteOrNone = int8 | None\n"
        f"def main(value: {annotation}) -> int:\n    return 1\n",
        environment=environment,
    ) as analysis:
        representation = analysis.entry_point.params[0].representation
        assert representation.kind == "union"
        assert representation.arguments == (None, annotation_representation(int8), None)
        body = "    return 1" if environment is JS_ENVIRONMENT else "    block entry:\n        return 1"
        assert analysis.types == "def main(value: str | int | None) -> int:\n" + body
        if environment is JS_ENVIRONMENT:
            assert analysis.javascript == "export function main(value) {\n    return 1;\n}"


@pytest.mark.parametrize("hook", ["annotation_numeric_format", "annotation_array_format"])
def test_named_annotation_fast_path_preserves_backend_validation(hook):
    class BackendInference(InferenceVisitor):
        pass

    def validate(self, node):
        raise ValueError("backend validation")

    setattr(BackendInference, hook, validate)
    ordinary_type = object.__new__(Class)
    ordinary_type.py_cls = int
    visitor = object.__new__(BackendInference)
    visitor.scope = Scope(None)
    visitor.scope.names["int"] = ordinary_type
    with pytest.raises(ValueError, match="backend validation"):
        visitor.annotation_representation(ast.Name(id="int"))


def test_unused_reachability_marks_are_lazy_independent_and_weak():
    class Root:
        pass

    with analyze_source("def main() -> int:\n    return 1\n") as analysis:
        function = analysis.entry_point
        objects = [
            (Object("unused", Scope()), ("visited",)),
            (Instance("unused", function.return_type, Scope(), None), ("visited", "virtual_visited")),
            (Function(function.py_func, function.container),
             ("visited", "virtual_visited", "render_visited", "hydrate_visited")),
        ]
        root = Root()
        root_ref = weakref.ref(root)
        marks = []
        for obj, attributes in objects:
            assert not any(name in vars(obj) for name in attributes)
            for name in attributes:
                mark = getattr(obj, name)
                assert mark is getattr(obj, name)
                assert isinstance(mark, weakref.WeakSet)
                assert not mark
                mark.add(root)
                marks.append(mark)
        assert len({id(mark) for mark in marks}) == len(marks)
        del root
        gc.collect()
        assert root_ref() is None
        assert not any(marks)

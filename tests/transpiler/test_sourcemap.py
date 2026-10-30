import json

import pytest

from pyjs.analysis.diagnostics import SourceFile
from pyjs.analysis.source import create_module
from pyjs.javascript.source import analyze_source
from pyjs.javascript.sourcemap import (
    SourceMap,
    SourceMapping,
    SourceScope,
    encode_scopes,
    encode_unsigned_vlq,
    map_stack_trace,
)
from pyjs.javascript.transpiler import (
    bundle_with_source_map,
    transpile_module_with_source_map,
)
from pyjs.tooling.node import Node


def test_source_map_encodes_standard_v3_fields():
    source = SourceFile.from_text("example.py", "answer = 42\n")
    source_map = SourceMap(
        (
            SourceMapping(0, 0, source, 0, 0, "answer"),
            SourceMapping(1, 2, source, 0, 7),
        ),
        "example.js",
    )

    assert source_map.to_dict() == {
        "version": 3,
        "sources": ["example.py"],
        "sourcesContent": ["answer = 42\n"],
        "names": ["answer"],
        "mappings": "AAAAA;EAAO",
        "file": "example.js",
    }


def test_source_map_emits_portable_source_paths():
    source = SourceFile.from_text(
        r"D:\checkout\examples\calculator.py",
        "answer = 42\n",
    )
    source_map = SourceMap((SourceMapping(0, 0, source, 0, 0),))

    assert source_map.to_dict() == {
        "version": 3,
        "sources": ["D:/checkout/examples/calculator.py"],
        "sourcesContent": ["answer = 42\n"],
        "names": [],
        "mappings": "AAAA",
    }


def test_transpiler_maps_generated_statements_to_python_source():
    analysis = analyze_source(
        """
def main():
    value = 42
    raise ValueError(value)
""".lstrip(),
        filename="example.py",
        wrap=False,
    )
    try:
        generated = transpile_module_with_source_map(
            analysis.entry_point.container,
        )
    finally:
        analysis.close()

    lines = generated.javascript.splitlines()
    assignment_line = lines.index("    var value = 42;")
    raise_line = lines.index("    throw new RangeError(value);")

    assignment = generated.source_map.lookup(assignment_line, 4)
    raised = generated.source_map.lookup(raise_line, 4)

    assert assignment is not None
    assert (
        assignment.source.filename,
        assignment.original_line,
        assignment.original_column,
    ) == ("example.py", 1, 4)
    assert raised is not None
    assert (
        raised.source.filename,
        raised.original_line,
        raised.original_column,
    ) == ("example.py", 2, 4)


@pytest.mark.parametrize(
    "declaration, statement",
    [
        ("def", "return result"),
        ("async def", "return result"),
        ("def", "yield result"),
    ],
)
def test_function_name_mapping_does_not_rename_parameters_or_locals(
    declaration, statement
):
    analysis = analyze_source(
        f"{declaration} main(left: int, right: int = 2):\n"
        f"    result = left + right\n    {statement}\n",
        filename="bindings.py",
        wrap=False,
    )
    try:
        generated = transpile_module_with_source_map(
            analysis.entry_point.container,
        )
    finally:
        analysis.close()

    source_map = SourceMap.from_json(generated.source_map.to_json())
    lines = generated.javascript.splitlines()
    named = [mapping for mapping in source_map.mappings if mapping.name]
    assert len(named) == 1
    function = named[0]
    assert function.name == "main"
    declaration = lines[function.generated_line]
    opening_paren = declaration.index("(")
    assert function.generated_column == opening_paren
    assert source_map.lookup(function.generated_line, opening_paren + 1).name is None
    for line, text in enumerate(lines):
        for identifier in ("left", "right", "result"):
            if identifier in text:
                mapping = source_map.lookup(line, text.index(identifier))
                assert mapping is not None and mapping.name is None
    assert generated.source_map.scopes[0].name == "main"
    assert generated.source_map.scopes[0].variables == ("left", "right", "result")


def test_source_map_columns_use_utf16_code_units():
    analysis = analyze_source(
        'def main():\n    message = "🦒"; raise ValueError(message)\n',
        filename="unicode_example.py",
        wrap=False,
    )
    try:
        generated = transpile_module_with_source_map(
            analysis.entry_point.container,
        )
    finally:
        analysis.close()

    raise_line = generated.javascript.splitlines().index(
        "    throw new RangeError(message);"
    )
    mapping = generated.source_map.lookup(raise_line, 4)

    assert mapping is not None
    assert mapping.original_line == 1
    assert mapping.original_column == 20


def test_source_map_binds_python_self_to_javascript_this():
    source = """\
from pyjs import js
@js
class Counter:
    def add(self, amount: int) -> int:
        result = amount + 1
        return result
@js
def main():
    print(Counter().add(2))
"""
    analysis = analyze_source(source, filename="counter.py", wrap=False)
    try:
        generated = transpile_module_with_source_map(
            analysis.entry_point.container,
        )
    finally:
        analysis.close()

    source_map = generated.source_map.to_dict()

    assert source_map["names"] == [
        "add",
        "main",
        "Global",
        "Function",
        "self",
        "amount",
        "result",
        "this",
    ]
    assert source_map["scopes"] == (
        "BCAAE,BHDEAC,DICC,CCV,BHCACA,CBb,CAA,EHCEC,GIGH,FDF,EHDAC,FCB"
    )
    method = generated.source_map.generated_scopes[0]
    assert method.scope.variables == ("self", "amount", "result")
    assert method.values == ("this", "amount", "result")
    assert generated.javascript.splitlines()[method.start_line] == "    add(amount) {"


def test_scope_name_deltas_continue_across_sources():
    first = SourceFile.from_text("first.py", "def first(left):\n    return left\n")
    second = SourceFile.from_text("second.py", "def second(right):\n    return right\n")
    names = []
    encoded = encode_scopes(
        ["first.py", "empty.py", "second.py"],
        names,
        (
            SourceScope(first, 0, 0, 1, 15, "first", ("left",)),
            SourceScope(second, 0, 0, 1, 16, "second", ("right",)),
        ),
        (),
    )

    assert names == ["Global", "first", "Function", "left", "second", "right"]
    # The second file resets positions, while kind/name/variable indices
    # continue from Function/first/left, even across an empty source.
    assert encoded == "BCAAA,BHAACE,DG,CBP,CAA,A,BCAAF,BHAAGE,DE,CBQ,CAA"


def test_source_map_omits_scopes_for_synthetic_dataclass_methods():
    source = """\
from dataclasses import dataclass
from pyjs import js

@js
@dataclass
class Record:
    value: int

    def __init__(self, value: int):
        self.value = value

@js
def main():
    print(Record(1) == Record(1))
"""
    analysis = analyze_source(source, filename="record.py", wrap=False)
    try:
        generated = transpile_module_with_source_map(
            analysis.entry_point.container,
        )
        source_map = generated.source_map.to_dict()
    finally:
        analysis.close()

    assert "__eq__(other)" in generated.javascript
    assert [scope.name for scope in generated.source_map.scopes] == [
        "__init__",
        "main",
    ]
    assert source_map["scopes"]


def test_bundle_offsets_module_mappings_below_runtime_scaffolding():
    module = create_module(
        """
from pyjs import js

@js
def main():
    value = 42
    raise ValueError(value)
""".lstrip(),
        "bundle_example.py",
        "bundle_example",
    )

    generated, css = bundle_with_source_map(module.main, include_main=True)
    lines = generated.javascript.splitlines()
    raise_line = lines.index("    throw new RangeError(value);")
    mapping = generated.source_map.lookup(raise_line, 4)

    assert css == ""
    assert mapping is not None
    assert (
        mapping.source.filename,
        mapping.original_line,
        mapping.original_column,
    ) == ("bundle_example.py", 5, 4)
    assert generated.with_source_mapping_url("bundle.js.map").endswith(
        "//# sourceMappingURL=bundle.js.map\n"
    )


def test_stack_trace_replaces_generated_locations_with_python_locations():
    source = SourceFile.from_text(
        "tests/test_example.py",
        "def test_failure():\n    raise ValueError('boom')\n",
    )
    source_map = SourceMap(
        (SourceMapping(3, 4, source, 1, 4),),
        "bundle.js",
    )

    mapped = map_stack_trace(
        "RangeError: boom\n"
        "    at test_failure (/bundle.js:4:9)\n"
        "    at eval (/bundle.js:8:1)",
        source_map,
    )

    assert mapped == (
        "RangeError: boom\n"
        "    at test_failure (tests/test_example.py:2:5)\n"
        "    at eval (/bundle.js:8:1)"
    )


def test_stack_trace_maps_browser_urls_with_cache_queries():
    source = SourceFile.from_text("tests/test_example.py", "raise ValueError()\n")
    source_map = SourceMap(
        (SourceMapping(2, 4, source, 0, 0),),
        "bundle.js",
    )

    mapped = map_stack_trace(
        "RangeError: boom\n"
        "    at main (http://127.0.0.1:8765/bundle.js?run_id=one:3:9)",
        source_map,
    )

    assert mapped == (
        "RangeError: boom\n"
        "    at main (tests/test_example.py:1:1)"
    )


def test_source_map_round_trips_ordinary_mappings():
    first = SourceFile.from_text(
        "first.py",
        "def first():\n    return 1\n",
    )
    second = SourceFile.from_text(
        "second.py",
        "def second():\n    return 2\n",
    )
    source_map = SourceMap(
        (
            SourceMapping(1, 4, first, 1, 4, "first"),
            SourceMapping(3, 8, second, 1, 4, "second"),
        ),
        "bundle.mjs",
    )

    loaded = SourceMap.from_json(source_map.to_json())

    assert loaded == source_map


def test_source_map_loader_rejects_malformed_vlq_segments():
    with pytest.raises(ValueError) as caught:
        SourceMap.from_dict(
            {
                "version": 3,
                "sources": ["example.py"],
                "names": [],
                "mappings": "!",
            }
        )

    assert str(caught.value) == "Invalid base64 VLQ character '!'."


def test_unsigned_vlq_rejects_negative_values():
    with pytest.raises(ValueError) as caught:
        encode_unsigned_vlq(-1)

    assert str(caught.value) == "Unsigned VLQ values cannot be negative."


def test_dataclass_generated_methods_do_not_emit_authored_function_scopes():
    module = create_module(
        """
from dataclasses import dataclass
from pyjs import js

@js
@dataclass
class First:
    value: int

@js
@dataclass
class Second:
    value: int

@js
def main():
    print(First(1) == Second(1))
""".lstrip(),
        "dataclass_scopes.py",
        "dataclass_scopes",
    )

    generated, _ = bundle_with_source_map(module.main, include_main=True)
    source_map = generated.source_map

    assert [scope.name for scope in source_map.scopes] == ["main"]
    assert json.loads(source_map.to_json())["version"] == 3


def test_source_map_loader_rejects_indexed_maps_explicitly():
    with pytest.raises(ValueError) as caught:
        SourceMap.from_dict(
            {
                "version": 3,
                "sections": [],
            }
        )

    assert str(caught.value) == "Indexed source maps are not supported."


def test_loaded_webpack_map_maps_android_file_urls():
    source_map = SourceMap.from_dict(
        {
            "version": 3,
            "file": "bundle.mjs",
            "sources": ["example/mobile.py"],
            "sourcesContent": ["def save():\n    raise ValueError('failed')\n"],
            "names": ["save"],
            "mappings": ";;IAEIA",
        }
    )

    mapped = map_stack_trace(
        "TypeError: failed\n"
        "    at save (file:///data/user/0/app/files/app/bundle.mjs:3:5)",
        source_map,
    )

    assert mapped == (
        "TypeError: failed\n"
        "    at save (example/mobile.py:3:5)"
    )


def test_node_reads_the_emitted_standard_source_map(tmp_path):
    python_source = tmp_path / "mapped_example.py"
    python_source.write_text(
        """
from pyjs import js

@js
def main():
    raise ValueError("mapped failure")
""".lstrip(),
        encoding="utf-8",
    )
    module = create_module(
        python_source.read_text(encoding="utf-8"),
        str(python_source),
        "mapped_example",
    )
    generated, _ = bundle_with_source_map(module.main, include_main=True)
    javascript = tmp_path / "bundle.mjs"
    source_map = tmp_path / "bundle.mjs.map"
    javascript.write_text(
        generated.with_source_mapping_url(source_map.name),
        encoding="utf-8",
    )
    source_map.write_text(generated.source_map.to_json(), encoding="utf-8")
    node = Node()
    node.ensure()

    result = node.runner.run(
        [node.executable, "--enable-source-maps", javascript],
        environment=node.environment(),
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    # Node's surrounding internal frames differ by release. The authored frame
    # is the stable contract this integration test is intended to verify.
    assert f"{python_source}:5" in result.stderr

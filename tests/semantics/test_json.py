import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source

from .helpers import assert_semantics


@pytest.mark.parametrize("value", [
    '""', '"quotes \\\" and newline \\n"', "True", "False", "None",
    "0", "-42", "2.5", '["", "first", "second"]',
    '[True, False, None, 0, 2.5, "text"]',
])
def test_json_stringify_scalars_and_arrays(value):
    assert_semantics(f'''
        from pyjs.javascript import JSON

        def main():
            print(JSON.stringify({value}))

        main()
    ''')


def test_json_stringify_unicode_round_trip():
    # JSON escape spellings need not match between runtimes; decoded text must.
    assert_semantics('''
        from pyjs.javascript import JSON, JSONObject

        class Record(JSONObject):
            value: list[str]

        def main():
            values = ["é", "🛳", "", "quotes \\\" and newline \\n"]
            source = '{"value":' + JSON.stringify(values) + '}'
            decoded: Record = JSON.parse(source)
            print(decoded["value"] == values)

        main()
    ''')


@pytest.mark.parametrize("annotation", ["dict[str, str]", "list[dict[str, str]]", "set[str]"])
def test_json_stringify_rejects_non_json_containers(annotation):
    with pytest.raises(CompilationError, match="JSON.stringify expects"):
        analyze_source(f'''
from pyjs.javascript import JSON
def main(value: {annotation}) -> str:
    return JSON.stringify(value)
''')

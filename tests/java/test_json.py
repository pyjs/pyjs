import json
import subprocess

import pytest

from pyjs.java import json as java_json
from pyjs.java import transpile_jvm
from pyjs.java.json import JSONReader, quote
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm
from tests.java.test_jvm import java

STRINGS = [
    "", "plain text", 'quote: " and slash: \\ /', "\b\f\n\r\t\0\x1f\x7f",
    "é雪😀", "a😀b😀c", "\ud800", "\udfff", "\ud800\ud801\udc00",
    "".join(chr(code) for code in range(128)), "ascii\uffffascii\U0010ffffend",
]
STRING_TOKENS = [json.dumps(value) for value in STRINGS] + [
    json.dumps("é雪😀", ensure_ascii=False), '"\ud800"', '"\udfff"',
    '"\\/"', '"\\u00aF"', '"\\u09Af"',
    '"\\uD83D\\uDE00"', '"\\ud800x"', '"\\ud800\\u0061"',
]
NUMBERS = ["0", "-0", "10", "-123", "0.1", "1e10", "-0.25E-2", "1E+3",
           "9223372036854775808", "1e999"]
DOCUMENTS = STRING_TOKENS + NUMBERS + [
    "true", "false", "null", "{}", "[]", '{"a":1,"a":2}',
    ' {"nested": [null, true, false, {}, [], {"title": "雪😀"}]} \t\r\n',
]
INVALID = [
    "", " ", "true false", "nullx", "True", "NaN", "Infinity", "-Infinity",
    "+1", "01", "-01", "1.", ".1", "1e", "1e+", "--1", "-", "1_0",
    "١", "1٢", "１２", "1０", "1e٢", "nul", "tru", "fals",
    "[", "[1,]", "[1 2]", "[,1]", "{", '{"a"}', '{"a":}', '{"a":1,}',
    '{"a":1 "b":2}', '{1:2}', "[1}", '{"a":1]',
    '"unterminated', '"raw\nline"', '"\\"', '"\\q"', '"\\u123"',
    '"\\uXX00"', '"\\ud800\\uXX00"', '"\0"', '\ufeff{}', '\xa0null',
    '"\x1f"', '"\\u00/0"', '"\\u00:0"', '"\\u00@0"', '"\\u00G0"',
    '"\\u00`0"', '"\\u00g0"', '"\\u', '"\\u1', '"\\u12', '"\\u123',
]


@pytest.mark.parametrize("value", STRINGS)
def test_quote_matches_standard_json(value):
    assert quote(value) == json.dumps(value)


@pytest.mark.parametrize("token", STRING_TOKENS)
def test_string_decoder_matches_standard_json(token):
    reader = JSONReader(" \t" + token + "\r\n")
    assert reader.string() == json.loads(token)
    reader.finish()


@pytest.mark.parametrize("value", ["", "plain text", "é雪😀", "\ud800", "\udfff"])
def test_unescaped_strings_do_not_allocate_a_builder(monkeypatch, value):
    def unexpected_builder():
        raise AssertionError("Unescaped JSON strings do not need a builder")

    monkeypatch.setattr(java_json, "StringBuilder", unexpected_builder)
    reader = JSONReader(" \t" + json.dumps(value, ensure_ascii=False) + " true")
    assert reader.string() == value
    assert reader.boolean()
    reader.finish()


@pytest.mark.parametrize("token", ['"\\n"', '"prefix\\n\\u96ea suffix"', '"\\ud83d\\ude00"'])
def test_escaped_strings_share_one_builder(monkeypatch, token):
    original = java_json.StringBuilder
    builders = []

    def builder():
        result = original()
        builders.append(result)
        return result

    monkeypatch.setattr(java_json, "StringBuilder", builder)
    reader = JSONReader(token)
    assert reader.string() == json.loads(token)
    reader.finish()
    assert len(builders) == 1


@pytest.mark.parametrize("token", NUMBERS)
def test_number_tokens_keep_range_and_precision_for_schema_validation(token):
    reader = JSONReader(token)
    assert reader.number() == token
    reader.finish()


def test_punctuation_lookahead_and_digit_scanning_do_not_allocate_strings(monkeypatch):
    def unexpected_string(*args):
        raise AssertionError("Scalar token scanning must not construct strings")

    monkeypatch.setattr(java_json, "chr", unexpected_string, raising=False)
    monkeypatch.setattr(java_json._UTF16, "slice", unexpected_string)
    reader = JSONReader(" \t{ ]\r\n")
    assert reader.take("{") and reader.position == 3
    assert not reader.take("}") and reader.position == 4
    assert reader.take("]") and reader.position == 5
    reader.finish()
    assert not reader.take("]")
    reader = JSONReader("12345!")
    reader._digits()
    assert reader.position == 5


TAKE_BOUNDARIES = '''
from pyjs.java.json import JSONReader
def main() -> str:
    reader = JSONReader(" \\t{雪😀null}\\r\\n")
    assert reader.take("{") and reader.position == 3
    assert not reader.take("x") and reader.position == 3
    assert reader.take("雪") and reader.position == 4
    assert not reader.take("😀x") and reader.position == 4
    assert reader.take("😀") and reader.position == 6
    assert not reader.take("nullable") and reader.position == 6
    assert reader.take("null") and reader.position == 10
    assert reader.take("}") and reader.position == 11
    assert not reader.take("}") and reader.position == 13
    try:
        reader.take("")
    except ValueError as error:
        assert str(error) == "JSON token must not be empty"
        return "ok"
    return "empty token accepted"
'''


def test_token_lookahead_keeps_utf16_positions_and_failed_match_semantics(tmp_path):
    assert_text_matches_python(TAKE_BOUNDARIES, tmp_path)


@pytest.mark.parametrize("document", DOCUMENTS)
def test_skip_accepts_standard_documents(document):
    json.loads(document)
    reader = JSONReader(document)
    reader.skip()
    reader.finish()


@pytest.mark.parametrize("document", INVALID)
def test_skip_rejects_invalid_documents(document):
    reader = JSONReader(document)
    with pytest.raises(ValueError):
        reader.skip()
        reader.finish()


def test_skip_validates_strings_without_building_decoded_values(monkeypatch):
    def unexpected_builder():
        raise AssertionError("Skipping JSON must not construct decoded strings")

    monkeypatch.setattr(java_json, "StringBuilder", unexpected_builder)
    for document in DOCUMENTS:
        reader = JSONReader(document)
        reader.skip()
        reader.finish()
    for document in INVALID:
        reader = JSONReader(document)
        with pytest.raises(ValueError):
            reader.skip()
            reader.finish()


@pytest.mark.parametrize("token", [token for token in INVALID if token.startswith('"')])
def test_skipped_string_errors_keep_decoding_diagnostics_and_positions(token):
    decoded = JSONReader(token)
    skipped = JSONReader(token)
    with pytest.raises(ValueError) as expected:
        decoded.string()
    with pytest.raises(ValueError) as actual:
        skipped.skip()
    assert str(actual.value) == str(expected.value)
    assert skipped.position == decoded.position


def test_jvm_json_corpus_matches_python(tmp_path):
    # One compilation runs the complete corpus instead of one JVM per token.
    checks = []
    for value in STRINGS:
        checks.append(f"    assert quote({value!r}) == {json.dumps(value)!r}")
    for token in STRING_TOKENS:
        checks += [
            f"    reader = JSONReader({token!r})",
            f"    assert quote(reader.string()) == {json.dumps(json.loads(token))!r}",
            "    reader.finish()",
            f"    reader = JSONReader({(token + ' true')!r})",
            "    reader.skip()",
            "    assert reader.boolean()",
            "    reader.finish()",
        ]
    for token in NUMBERS:
        checks += [f"    reader = JSONReader({token!r})",
                   f"    assert reader.number() == {token!r}", "    reader.finish()"]
    checks += [
        f"    for document in {DOCUMENTS!r}:",
        "        reader = JSONReader(document)",
        "        reader.skip()",
        "        reader.finish()",
        f"    for document in {INVALID!r}:",
        "        reader = JSONReader(document)",
        "        try:",
        "            reader.skip()",
        "            reader.finish()",
        "        except ValueError:",
        "            continue",
        '        return "accepted invalid JSON: " + document',
    ]
    assert_text_matches_python(
        "from pyjs.java.json import JSONReader, quote\n\ndef main() -> str:\n"
        + "\n".join(checks) + '\n    return "matched"\n', tmp_path,
    )


BOUNDARIES = '''
from pyjs.java.json import JSONReader, quote

def main() -> str:
    for document in ["[[[0]]]", "[[[]]]", '{"a":{"b":[null]}}', '{"a":{"b":{}}}']:
        allowed = JSONReader(document)
        allowed.skip(3)
        allowed.finish()
        try:
            JSONReader(document).skip(2)
        except ValueError as error:
            assert str(error) == "JSON nesting limit exceeded"
        else:
            return "depth not bounded"
    reader = JSONReader('{"name":"snow", "count":42, "enabled":true, "extra":[null]}')
    reader.expect("{")
    assert reader.string() == "name"
    reader.expect(":")
    assert reader.string() == "snow"
    reader.expect(",")
    assert reader.string() == "count"
    reader.expect(":")
    assert reader.number() == "42"
    reader.expect(",")
    assert reader.string() == "enabled"
    reader.expect(":")
    assert reader.boolean()
    reader.expect(",")
    assert reader.string() == "extra"
    reader.expect(":")
    reader.skip()
    reader.expect("}")
    reader.finish()
    assert not JSONReader("false").boolean()
    scalar = JSONReader("0")
    scalar.skip(0)
    scalar.finish()
    unicode = JSONReader("😀")
    unicode.expect("😀")
    unicode.finish()
    for value in ["0", "null", '"true"']:
        try:
            JSONReader(value).boolean()
        except ValueError:
            continue
        return "boolean accepted a different type"
    return "matched"
'''


def test_typed_reader_boundaries_match_python(tmp_path):
    assert_text_matches_python(BOUNDARIES, tmp_path)


def test_json_reader_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(BOUNDARIES, tmp_path)


def test_large_plain_and_escaped_strings(tmp_path):
    source = '''
from pyjs.java.json import JSONReader, quote
def main() -> str:
    text = "prefix " * 10000 + "雪😀" * 1000
    for document in [quote(text), '"' + text + '"']:
        reader = JSONReader(document)
        assert reader.string() == text
        reader.finish()
    return "matched"
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "matched"


def test_non_ascii_encoding_does_not_retain_per_character_fragments(tmp_path):
    source = '''
from pyjs.java.json import quote
def main() -> str:
    result = quote("雪😀" * 200000)
    assert result == '"' + "\\\\u96ea\\\\ud83d\\\\ude00" * 200000 + '"'
    return "matched"
'''
    assert_bounded_string_memory(source, tmp_path)


def test_escaped_string_decoding_does_not_retain_per_character_fragments(tmp_path):
    source = '''
from pyjs.java.json import JSONReader
def main() -> str:
    reader = JSONReader('"' + "\\\\u96ea\\\\ud83d\\\\ude00" * 300000 + '"')
    assert reader.string() == "雪😀" * 300000
    reader.finish()
    return "matched"
'''
    assert_bounded_string_memory(source, tmp_path)


def assert_bounded_string_memory(source, tmp_path):
    transpile_jvm(source).write(tmp_path)
    result = subprocess.run(
        [java(), "-Xmx32m", "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "matched"


TYPED_NUMBERS = '''
from pyjs.java import double_to_string
from pyjs.java.json import JSONReader
def main() -> str:
    for token in ["0", "-0", "42", "-123", "9007199254740993",
                  "9223372036854775807", "-9223372036854775808"]:
        reader = JSONReader(" " + token + " ")
        assert reader.integer() == int(token)
        reader.finish()
    for token in ["9223372036854775808", "-9223372036854775809",
                  "9" * 5000, "1.0", "1e0", "-2.1", "true", "null"]:
        try:
            JSONReader(token).integer()
        except ValueError:
            continue
        return "accepted invalid integer: " + token
    for token in ["0", "-0", "1", "1.25", "-3.125e1", "1.7976931348623157e308",
                  "-1.7976931348623157e308", "5e-324", "1e-999"]:
        reader = JSONReader(token)
        value = reader.floating()
        reader.finish()
        assert value <= 1.7976931348623157e308
    assert JSONReader("1.25").floating() == 1.25
    assert JSONReader("-3.125e1").floating() == -31.25
    assert JSONReader("5e-324").floating() > 0.0
    assert JSONReader("1e-999").floating() == 0.0
    assert double_to_string(JSONReader("-1e-999").floating()) == "-0.0"
    assert double_to_string(JSONReader("-0").floating()) == "-0.0"
    for token in ["1.7976931348623159e308", "-1e309", "NaN", "Infinity", "null", "true"]:
        try:
            JSONReader(token).floating()
        except ValueError:
            continue
        return "accepted invalid float: " + token
    return "matched"
'''


def test_typed_json_numbers_match_python(tmp_path):
    assert_text_matches_python(TYPED_NUMBERS, tmp_path)


def test_typed_json_numbers_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(TYPED_NUMBERS, tmp_path)

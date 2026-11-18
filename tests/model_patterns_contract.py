from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter

from pyjs import js

PATTERN_CASES = [
    (r"^#[0-9a-fA-F]{6}$", ["#aB09fF", "#abcdef\n", "#abc", "#abcxyz", "x#abcdef"]),
    ("", ["", "anything", "\n"]),
    ("^$", ["", "\n", "x"]),
    ("^a{0}[x-z]{0}$", ["", "a", "x"]),
    ("^[a-zA-Za-zabc]{1,3}$", ["aZ", "abc", "abcd", "0"]),
    ("a$", ["a", "ba", "a\n"]),
    ("^a", ["a", "ab", "ba"]),
    ("^.$", ["\r", "\n", "😀", "ab"]),
    ("^[^x]*$", ["", "\n", "😀", "x", "ax"]),
    ("^😀+é?$", ["", "😀", "😀😀é", "😀éé"]),
    ("[😀-😃]{1,3}", ["😁", "😄", "x😀😀x"]),
    ("^a{2,}b{0}c{0,2}$", ["a", "aa", "aaa", "aab", "aaacc", "aaaccc"]),
    (r"^\[a\]\+\?\.$", ["[a]+?.", "a", "[a]+?.\n"]),
    (r"^[\-\]\n\r\t]+$", ["-]\n\r\t", "", "x"]),
    ("^a*a*a*a*a*b$", ["b", "a" * 2000, "a" * 2000 + "b"]),
]


def accepted(pattern, value):
    try:
        TypeAdapter(Annotated[str, Field(pattern=pattern)]).validate_python(value)
        return True
    except ValueError:
        return False


def matcher_source():
    from pyjs.lib.pydantic.patterns import compile_pattern

    lines = ["from pyjs import js", "from pyjs.lib.pydantic.patterns import matches_pattern",
             "@js", "def main() -> str:"]
    for pattern, values in PATTERN_CASES:
        lines.append(f"    program = {compile_pattern(pattern)!r}")
        for index, value in enumerate(values):
            lines.append(f"    assert matches_pattern({value!r}, program) == {accepted(pattern, value)!r}, "
                         f"{(pattern + ' input ' + str(index))!r}")
    lines.append("    return 'validated'")
    return "\n".join(lines)


@js
class Badge(BaseModel):
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    code: str = Field(pattern=r"[A-Z]{2,4}[0-9]+")
    caption: str | None = Field(default=None, pattern=r"^😀+é?$", max_length=4)
    unchecked_default: str = Field(default="invalid", pattern="^valid$")


@js
class InheritedBadge(Badge):
    color: str = Field(pattern="^blue$")


@js
class UnrestrictedBadge(Badge):
    color: str


@js
class Badges(BaseModel):
    badges: list[Badge]


@js
class Identifier(BaseModel):
    value: str = Field(pattern=r"^[A-Za-z0-9._%+\-]{1,255}$")


@js
class ShortCode(BaseModel):
    value: Annotated[str, StringConstraints(min_length=2, max_length=3, pattern="^x")]


@js
def check_large_and_grouped_patterns() -> str:
    assert Identifier.model_validate_json('{"value":"a.b+c"}').value == "a.b+c"
    assert ShortCode.model_validate_json('{"value":"xy"}').value == "xy"
    longest = ""
    for _ in range(255):
        longest += "a"
    assert Identifier.model_validate_json('{"value":"' + longest + '"}').value == longest
    for value in ["", "a b", longest + "a"]:
        try:
            Identifier.model_validate_json('{"value":"' + value + '"}')
        except ValueError:
            continue
        return "accepted invalid identifier"
    for value in ["x", "xxxx", "yy"]:
        try:
            ShortCode.model_validate_json('{"value":"' + value + '"}')
        except ValueError:
            continue
        return "ignored grouped length or pattern"
    return "validated"


@js
def check_patterns() -> str:
    valid = '{"color":"#aB09fF","code":"prefix AB123 suffix","caption":"😀😀é"}'
    badge = Badge.model_validate_json(valid)
    assert badge.color == "#aB09fF" and badge.caption == "😀😀é"
    assert badge.unchecked_default == "invalid"
    assert Badge.model_validate_json(valid.replace('"😀😀é"', 'null')).caption is None
    assert UnrestrictedBadge.model_validate_json(valid.replace('#aB09fF', 'anything')).color == "anything"
    assert InheritedBadge.model_validate_json(valid.replace('#aB09fF', 'blue')).color == "blue"
    assert Badges.model_validate_json('{"badges":[' + valid + ']}').badges[0].color == "#aB09fF"
    invalid = [valid.replace('#aB09fF', '#12345'), valid.replace('#aB09fF', '#1234567'),
               valid.replace('#aB09fF', '#zzzzzz'), valid.replace('#aB09fF', '#aB09fF\\n'),
               valid.replace('#aB09fF', 'x#aB09fF'), valid.replace('AB123', 'A1'),
               valid.replace('😀😀é', '😀é😀'), valid.replace('😀😀é', '😀😀😀😀😀'),
               valid.replace('😀😀é', ''), valid.replace('😀😀é', '😀\\n'),
               valid.replace('"caption":', '"unchecked_default":"invalid","caption":')]
    for document in invalid:
        try:
            Badges.model_validate_json('{"badges":[' + document + ']}')
        except ValueError:
            continue
        return "accepted invalid pattern: " + document
    try:
        InheritedBadge.model_validate_json(valid)
    except ValueError:
        return "validated"
    return "ignored inherited pattern"

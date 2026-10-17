"""Generate compact Unicode tables used by the standalone native runtime."""

import argparse
import unicodedata
from pathlib import Path
from urllib.request import urlopen

VERSION = "16.0.0"
DERIVED_PROPERTIES = (
    f"https://www.unicode.org/Public/{VERSION}/ucd/"
    "DerivedCoreProperties.txt"
)
OUTPUT = Path(__file__).parents[1] / "pyjs" / "native" / "unicode_data.py"


def property_ranges(source: str, name: str):
    result = []
    for line in source.splitlines():
        fields = line.split("#", 1)[0].split(";")
        if len(fields) != 2 or fields[1].strip() != name:
            continue
        bounds = fields[0].strip().split("..")
        start = int(bounds[0], 16)
        result.append((start, int(bounds[-1], 16)))
    return result


def case_ranges(operation: str):
    pairs = []
    special = []
    for codepoint in range(0x110000):
        converted = getattr(chr(codepoint), operation)()
        if converted == chr(codepoint):
            continue
        if len(converted) == 1:
            pairs.append((codepoint, ord(converted) - codepoint))
        else:
            special.append((codepoint, tuple(map(ord, converted))))

    ranges = []
    for codepoint, delta in pairs:
        if not ranges:
            ranges.append([codepoint, codepoint, 0, delta])
            continue
        previous = ranges[-1]
        stride = codepoint - previous[1]
        if (
            delta == previous[3]
            and stride <= 2
            and (previous[2] == 0 or stride == previous[2])
        ):
            previous[1] = codepoint
            previous[2] = stride
        else:
            ranges.append([codepoint, codepoint, 0, delta])
    return ranges, special


def predicate_ranges(operation: str, *, prefix: str = ""):
    ranges = []
    start = None
    for codepoint in range(0x110000):
        matches = getattr(prefix + chr(codepoint), operation)()
        if matches and start is None:
            start = codepoint
        elif not matches and start is not None:
            ranges.append((start, codepoint - 1))
            start = None
    if start is not None:
        ranges.append((start, 0x10FFFF))
    return ranges


def render_table(name: str, values) -> list[str]:
    return [f"{name} = (", *(f"    {tuple(value)!r}," for value in values), ")", ""]


def generate(properties: str) -> str:
    if not properties.startswith(f"# DerivedCoreProperties-{VERSION}.txt"):
        raise ValueError(f"Expected DerivedCoreProperties-{VERSION}.txt")
    if unicodedata.unidata_version != VERSION:
        raise ValueError(
            f"Generation requires Python Unicode {VERSION}, "
            f"not {unicodedata.unidata_version}"
        )
    lowercase, lowercase_special = case_ranges("lower")
    uppercase, uppercase_special = case_ranges("upper")
    titlecase, titlecase_special = case_ranges("title")
    casefold, casefold_special = case_ranges("casefold")
    swapcase, swapcase_special = case_ranges("swapcase")
    lines = [
        '"""Generated Unicode data for the standalone native runtime."""',
        "# Unicode data is distributed under UNICODE-LICENSE.txt in this package.",
        "",
        f'UNICODE_VERSION = "{VERSION}"',
        "",
        *render_table("LOWERCASE_RANGES", lowercase),
        *render_table("LOWERCASE_SPECIAL", lowercase_special),
        *render_table("UPPERCASE_RANGES", uppercase),
        *render_table("UPPERCASE_SPECIAL", uppercase_special),
        *render_table("TITLECASE_RANGES", titlecase),
        *render_table("TITLECASE_SPECIAL", titlecase_special),
        *render_table("CASEFOLD_RANGES", casefold),
        *render_table("CASEFOLD_SPECIAL", casefold_special),
        *render_table("SWAPCASE_RANGES", swapcase),
        *render_table("SWAPCASE_SPECIAL", swapcase_special),
        *render_table("ALPHA_RANGES", predicate_ranges("isalpha")),
        *render_table("ALNUM_RANGES", predicate_ranges("isalnum")),
        *render_table("DECIMAL_RANGES", predicate_ranges("isdecimal")),
        *render_table("DIGIT_RANGES", predicate_ranges("isdigit")),
        *render_table("NUMERIC_RANGES", predicate_ranges("isnumeric")),
        *render_table("LOWER_RANGES", predicate_ranges("islower")),
        *render_table("UPPER_RANGES", predicate_ranges("isupper")),
        *render_table("TITLE_RANGES", predicate_ranges("istitle")),
        *render_table("PRINTABLE_RANGES", predicate_ranges("isprintable")),
        *render_table(
            "IDENTIFIER_START_RANGES",
            predicate_ranges("isidentifier"),
        ),
        *render_table(
            "IDENTIFIER_CONTINUE_RANGES",
            predicate_ranges("isidentifier", prefix="A"),
        ),
        *render_table("CASED_RANGES", property_ranges(properties, "Cased")),
        *render_table(
            "CASE_IGNORABLE_RANGES",
            property_ranges(properties, "Case_Ignorable"),
        ),
    ]
    return "\n".join(lines)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without changing the checked-in tables")
    parser.add_argument("--properties", type=Path, help="Use a local DerivedCoreProperties.txt")
    arguments = parser.parse_args(argv)
    if arguments.properties:
        properties = arguments.properties.read_text(encoding="utf-8")
    else:
        with urlopen(DERIVED_PROPERTIES, timeout=30) as response:
            properties = response.read().decode("utf-8")
    try:
        content = generate(properties)
    except ValueError as error:
        parser.error(str(error))
    if arguments.check:
        if OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit(f"{OUTPUT} is stale; regenerate with this script")
        print(f"Verified Unicode {VERSION} tables")
    else:
        OUTPUT.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()

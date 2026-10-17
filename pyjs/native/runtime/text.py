"""Unicode, byte, and string LLVM runtime."""

import textwrap
from functools import cache

from .. import unicode_data
from ..unicode_data import (
    ALNUM_RANGES,
    ALPHA_RANGES,
    CASE_IGNORABLE_RANGES,
    CASED_RANGES,
    DECIMAL_RANGES,
    DIGIT_RANGES,
    IDENTIFIER_CONTINUE_RANGES,
    IDENTIFIER_START_RANGES,
    LOWER_RANGES,
    LOWERCASE_RANGES,
    LOWERCASE_SPECIAL,
    NUMERIC_RANGES,
    PRINTABLE_RANGES,
    TITLE_RANGES,
    UPPER_RANGES,
)

BYTE_WHITESPACE = b" \t\n\r\v\f"
WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def _character_ranges(characters: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    for codepoint in sorted(set(map(ord, characters))):
        if ranges and codepoint == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], codepoint)
        else:
            ranges.append((codepoint, codepoint))
    return tuple(ranges)


# Reuse strip/split membership; coalesce runs for the linear range scanner.
SPACE_RANGES = _character_ranges(WHITESPACE)

CASE_METHODS = {
    "lower": ("lower", 0), "upper": ("upper", 1),
    "casefold": ("casefold", 1), "swapcase": ("swapcase", 2),
    "title": ("titlecase", 3), "capitalize": ("titlecase", 4),
}
PROPERTY_METHODS = {
    "isalnum": ("alnum", len(ALNUM_RANGES)),
    "isalpha": ("alpha", len(ALPHA_RANGES)),
    "isdecimal": ("decimal", len(DECIMAL_RANGES)),
    "isdigit": ("digit", len(DIGIT_RANGES)),
    "isnumeric": ("numeric", len(NUMERIC_RANGES)),
    "isprintable": ("printable", len(PRINTABLE_RANGES)),
    "isspace": ("space", len(SPACE_RANGES)),
    "islower": ("lower", len(LOWER_RANGES)),
    "isupper": ("upper", len(UPPER_RANGES)),
}
UNICODE_METHODS = CASE_METHODS.keys() | PROPERTY_METHODS.keys() | {"istitle", "isidentifier"}
EDIT_METHODS = {"__slice__", "__getitem__", "__mul__", "__rmul__", "replace",
                "join", "strip", "lstrip", "rstrip", "find", "rfind", "count",
                "startswith", "endswith", "split", "rsplit", "index", "rindex"}
EXTRA_METHODS = {"partition", "rpartition", "removeprefix", "removesuffix",
                 "splitlines", "ljust", "rjust", "center", "zfill", "expandtabs",
                 "encode", "decode", "hex"}


@cache
def compiled_edit_runtime(include_split: bool = False) -> tuple[str, ...]:
    from .algorithms import character_width, string_length
    from .compiler import compile_runtime
    from .sequences import new_list
    from .text_edit import (
        affix,
        copy_span,
        get_character,
        join,
        repeat,
        repeat_fits,
        replace,
        search,
        search_byte,
        slice_text,
        trim,
    )
    from .text_operations import new_owned
    from .text_split import split

    roots = {
        "pyjs.string.get.character": get_character,
        "pyjs.string.character.width": character_width,
        "pyjs.string.join": join, "pyjs.string.repeat": repeat,
        "pyjs.string.repeat.fits": repeat_fits,
        "pyjs.string.replace": replace, "pyjs.string.search": search,
        "pyjs.string.affix": affix, "pyjs.string.search.byte": search_byte,
        "pyjs.string.slice": slice_text, "pyjs.string.trim": trim,
        "pyjs.string.copy.span": copy_span,
    }
    dependencies = {"pyjs.string.new.owned": new_owned, "pyjs.string.length": string_length}
    if include_split:
        roots["pyjs.string.split"] = split
        dependencies["pyjs.list.new.owned"] = new_list
    return compile_runtime(roots, dependencies=dependencies)


@cache
def compiled_extra_runtime() -> tuple[str, ...]:
    from . import text_extra as extra
    from .algorithms import contains_byte, valid_utf8
    from .arena import allocate_collection
    from .compiler import compile_runtime
    from .sequences import new_list, new_tuple
    from .text_edit import copy_span
    from .text_operations import new_owned

    roots = {"pyjs.text." + name: getattr(extra, name) for name in (
        "valid_byte_items", "new_bytes", "get_byte", "hex_bytes", "partition",
        "remove_affix", "splitlines", "pad", "zfill", "expandtabs", "repr_bytes",
    )}
    roots.update({"pyjs.bytes.valid.utf8": valid_utf8,
                  "pyjs.bytes.contains.byte": contains_byte})
    return compile_runtime(roots, dependencies={
        "pyjs.collection.try.alloc": allocate_collection,
        "pyjs.string.new.owned": new_owned, "pyjs.string.copy.span": copy_span,
        "pyjs.list.new.owned": new_list,
        "pyjs.tuple.new": new_tuple,
    })


def unicode_definitions() -> list[str]:
    result = string_lower_definitions() + string_property_definitions()
    for name, table in (("upper", "UPPERCASE"), ("casefold", "CASEFOLD"),
                        ("swapcase", "SWAPCASE"), ("titlecase", "TITLECASE")):
        result.extend(string_expanded_case_definitions(
            name, getattr(unicode_data, table + "_RANGES"),
            getattr(unicode_data, table + "_SPECIAL"),
        ))
    return result


@cache
def compiled_owned_text_runtime() -> tuple[str, ...]:
    from .arena import allocate_collection
    from .compiler import compile_runtime
    from .text_operations import concat_owned, new_owned

    return compile_runtime({
        "pyjs.string.new.owned": new_owned,
        "pyjs.string.concat.owned": concat_owned,
    }, dependencies={"pyjs.collection.try.alloc": allocate_collection})


@cache
def compiled_text_runtime() -> tuple[str, ...]:
    from . import algorithms as a
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.string.count": a.count_string,
        "pyjs.string.equal": a.bytes_equal,
        "pyjs.string.less": a.bytes_less,
        "pyjs.string.bool": a.bytes_bool,
        "pyjs.string.hash": a.bytes_hash,
        "pyjs.string.length": a.string_length,
        "pyjs.string.is.ascii": a.is_ascii,
        "pyjs.string.starts.with": a.starts_with,
        "pyjs.string.ends.with": a.ends_with,
        "pyjs.string.contains": a.contains,
        "pyjs.string.find": a.find_string,
        "pyjs.string.rfind": a.rfind_string,
    })


@cache
def compiled_utf8_runtime() -> tuple[str, ...]:
    from .algorithms import decode_utf8, encode_utf8, encode_utf8_at
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.utf8.decode.scalar": decode_utf8,
        "pyjs.utf8.encode": encode_utf8,
        "pyjs.utf8.encode.at": encode_utf8_at,
    })


@cache
def compiled_case_runtime() -> tuple[str, ...]:
    from .algorithms import decode_utf8, encode_utf8_at
    from .compiler import compile_runtime
    from .text_operations import new_owned
    from .unicode import (
        all_in_ranges,
        cased_in_ranges,
        change_case,
        in_ranges,
        is_identifier,
        is_title,
        write_case,
    )

    return compile_runtime({
        "pyjs.unicode.in.ranges": in_ranges,
        "pyjs.unicode.write.case": write_case,
        "pyjs.unicode.change.case": change_case,
        "pyjs.string.all.codepoints.in.ranges": all_in_ranges,
        "pyjs.unicode.cased.in.ranges": cased_in_ranges,
        "pyjs.unicode.is.identifier": is_identifier,
        "pyjs.unicode.is.title": is_title,
    }, dependencies={
        "pyjs.utf8.decode.scalar": decode_utf8,
        "pyjs.utf8.encode.at": encode_utf8_at,
        "pyjs.string.new.owned": new_owned,
    })


def unicode_integers(name: str, values: list[int]) -> str:
    rendered = ", ".join(f"i32 {value}" for value in values)
    return (
        f"@pyjs.unicode.{name} = private constant "
        f"[{len(values)} x i32] [{rendered}]"
    )


def unicode_ranges(name: str, values: tuple[tuple[int, int], ...]) -> str:
    rendered = ", ".join(
        f"%pyjs.unicode.range {{ i32 {start}, i32 {stop} }}"
        for start, stop in values
    )
    return (
        f"@pyjs.unicode.{name} = private constant "
        f"[{len(values)} x %pyjs.unicode.range] [{rendered}]"
    )


def string_lower_definitions() -> list[str]:
    assert LOWERCASE_SPECIAL == ((304, (105, 775)),)
    mappings = [
        (codepoint, codepoint + delta)
        for start, stop, stride, delta in LOWERCASE_RANGES
        for codepoint in range(start, stop + 1, stride or 1)
    ]
    mappings.sort()

    return [
        "%pyjs.unicode.range = type { i32, i32 }",
        "%pyjs.unicode.mapping = type { ptr, ptr, ptr, i64 }",
        "%pyjs.unicode.context = type { ptr, ptr, i64, ptr, i64 }",
        unicode_integers("lower.keys", [source for source, _target in mappings]),
        unicode_integers("lower.values", [target for _source, target in mappings]),
        unicode_ranges("cased", CASED_RANGES),
        unicode_ranges("case.ignorable", CASE_IGNORABLE_RANGES),
        "@pyjs.unicode.lower.mapping = private constant %pyjs.unicode.mapping "
        f"{{ ptr @pyjs.unicode.lower.keys, ptr null, ptr @pyjs.unicode.lower.values, i64 {len(mappings)} }}",
        "@pyjs.unicode.context = private constant %pyjs.unicode.context "
        "{ ptr @pyjs.unicode.lower.mapping, ptr @pyjs.unicode.cased, "
        f"i64 {len(CASED_RANGES)}, ptr @pyjs.unicode.case.ignorable, i64 {len(CASE_IGNORABLE_RANGES)} }}",
    ]


def string_expanded_case_definitions(
    name,
    ranges,
    special,
) -> list[str]:
    mappings = {
        codepoint: (codepoint + delta,)
        for start, stop, stride, delta in ranges
        for codepoint in range(start, stop + 1, stride or 1)
    }
    mappings.update(dict(special))
    keys = sorted(mappings)
    offsets = [0]
    values = []
    for key in keys:
        values.extend(mappings[key])
        offsets.append(len(values))

    return [
        unicode_integers(f"{name}.keys", keys),
        unicode_integers(f"{name}.offsets", offsets),
        unicode_integers(f"{name}.values", values),
        f"@pyjs.unicode.{name}.mapping = private constant %pyjs.unicode.mapping "
        f"{{ ptr @pyjs.unicode.{name}.keys, ptr @pyjs.unicode.{name}.offsets, "
        f"ptr @pyjs.unicode.{name}.values, i64 {len(keys)} }}",
    ]


def string_property_definitions() -> list[str]:
    return [
        unicode_ranges("alnum", ALNUM_RANGES),
        unicode_ranges("alpha", ALPHA_RANGES),
        unicode_ranges("decimal", DECIMAL_RANGES),
        unicode_ranges("digit", DIGIT_RANGES),
        unicode_ranges("identifier.continue", IDENTIFIER_CONTINUE_RANGES),
        unicode_ranges("identifier.start", IDENTIFIER_START_RANGES),
        unicode_ranges("lower", LOWER_RANGES),
        unicode_ranges("numeric", NUMERIC_RANGES),
        unicode_ranges("printable", PRINTABLE_RANGES),
        unicode_ranges("space", SPACE_RANGES),
        unicode_ranges("title", TITLE_RANGES),
        unicode_ranges("upper", UPPER_RANGES),
        textwrap.dedent(f"""
            define i1 @pyjs.string.cased.codepoints.in.ranges(ptr %value, ptr %ranges, i64 %count) {{
              %result = call i1 @pyjs.unicode.cased.in.ranges(
                  ptr %value, ptr %ranges, i64 %count, ptr @pyjs.unicode.context)
              ret i1 %result
            }}

            define i1 @pyjs.string.is.identifier(ptr %value) {{
              %result = call i1 @pyjs.unicode.is.identifier(
                  ptr %value, ptr @pyjs.unicode.identifier.start,
                  i64 {len(IDENTIFIER_START_RANGES)},
                  ptr @pyjs.unicode.identifier.continue,
                  i64 {len(IDENTIFIER_CONTINUE_RANGES)})
              ret i1 %result
            }}

            define i1 @pyjs.string.is.title(ptr %value) {{
              %result = call i1 @pyjs.unicode.is.title(
                  ptr %value, ptr @pyjs.unicode.title, i64 {len(TITLE_RANGES)},
                  ptr @pyjs.unicode.lower, i64 {len(LOWER_RANGES)},
                  ptr @pyjs.unicode.context)
              ret i1 %result
            }}
        """).strip(),
    ]

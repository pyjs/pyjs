from pyjs.testing.helpers import at

from .helpers import assert_semantics


def test_unicode_length_and_strip_operations_match_python():
    assert_semantics(
        """\
        print(len("😀"), len("A😀B"))
        print(min(["😀😀", "abc"], key=len))

        whitespace = "\\x1c\\tone \\x1f"
        print(whitespace.strip() == "one")
        print(whitespace.lstrip() == "one \\x1f")
        print(whitespace.rstrip() == "\\x1c\\tone")

        bom = "\\ufeffone\\ufeff"
        print(bom.strip() == bom)

        decorated = "xy😀value😀yx"
        print(decorated.strip("xy😀"))
        print(decorated.lstrip("xy😀"))
        print(decorated.rstrip("xy😀"))
        print(repr("value".strip("")))
        """
    )


def test_unicode_length_and_strip_operations_have_explicit_lowering():
    at(
        """\
        def main(value: str, chars: str):
            length = len(value)
            stripped = value.strip()
            selected = value.strip(chars)
            left = value.lstrip(chars)
            right = value.rstrip(chars)
        """,
        """
        def main(value: str, chars: str) -> None:
            length: int = value.[str]__len__!()
            stripped: str = value.[str]strip!()
            selected: str = value.[str]strip!(chars)
            left: str = value.[str]lstrip!(chars)
            right: str = value.[str]rstrip!(chars)
        """,
        """
        import { strip_string as $strip_string } from './pyjs.python.js';

        export function main(value, chars) {
            var length = [...value].length;
            var stripped = $strip_string(value,null,true,true);
            var selected = $strip_string(value,chars,true,true);
            var left = $strip_string(value,chars,true,false);
            var right = $strip_string(value,chars,false,true);
        }
        """,
    )


def test_string_count_matches_python_bounds_and_unicode_semantics():
    assert_semantics(
        """\
        print("banana".count("an"), "aaaa".count("aa"))
        print("A😀😀B😀".count("😀"), "A😀😀B😀".count("😀😀"))
        print("banana".count("an", 2), "banana".count("an", 2, 5))
        print("banana".count("an", -5, -1))
        print("abc".count(""), "abc".count("", 3), "abc".count("", 4))
        print("abc".count("", 3, 2), "abc".count("a", 3, 2))
        """
    )


def test_string_count_has_explicit_runtime_lowering():
    at(
        """\
        def main(value: str, sub: str, start: int, end: int):
            whole = value.count(sub)
            bounded = value.count(sub, start, end)
        """,
        """
        def main(value: str, sub: str, start: int, end: int) -> None:
            whole: int = value.[str]count!(sub)
            bounded: int = value.[str]count!(sub, start, end)
        """,
        """
        import { search_string as $search_string } from './pyjs.python.js';

        export function main(value, sub, start, end) {
            var whole = $search_string(value,sub,0,null,'count');
            var bounded = $search_string(value,sub,start,end,'count');
        }
        """,
    )


def test_string_find_and_index_match_python_bounds_and_unicode_indexes():
    assert_semantics(
        """\
        value = "A😀B😀C"
        print(value.find("😀"), value.rfind("😀"))
        print(value.find("😀", 2), value.rfind("😀", 0, 3))
        print(value.find("missing"), value.rfind("missing"))
        print(value.find("", 5), value.find("", 6))
        print(value.rfind("", 0, 4), value.rfind("", 4, 3))
        print(value.index("B"), value.rindex("😀"))

        for reverse in (False, True):
            try:
                if reverse:
                    value.rindex("missing")
                else:
                    value.index("missing")
            except ValueError as error:
                print(str(error))
        """
    )


def test_string_find_and_index_have_shared_explicit_lowering():
    at(
        """\
        def main(value: str, sub: str, start: int, end: int):
            first = value.find(sub)
            last = value.rfind(sub, start, end)
            required = value.index(sub)
            required_last = value.rindex(sub, start, end)
        """,
        """
        def main(value: str, sub: str, start: int, end: int) -> None:
            first: int = value.[str]find!(sub)
            last: int = value.[str]rfind!(sub, start, end)
            required: int = value.[str]index!(sub)
            required_last: int = value.[str]rindex!(sub, start, end)
        """,
        """
        import { search_string as $search_string } from './pyjs.python.js';

        export function main(value, sub, start, end) {
            var first = $search_string(value,sub,0,null,'forward');
            var last = $search_string(value,sub,start,end,'reverse');
            var required = ((index)=>{if(index<0)throw new RangeError('substring not found');return index;})($search_string(value,sub,0,null,'forward'));
            var required_last = ((index)=>{if(index<0)throw new RangeError('substring not found');return index;})($search_string(value,sub,start,end,'reverse'));
        }
        """,
    )


def test_string_rsplit_matches_explicit_and_whitespace_semantics():
    assert_semantics(
        """\
        value = "one,two,three"
        print(repr(value.rsplit(",")))
        print(repr(value.rsplit(",", 0)))
        print(repr(value.rsplit(",", 1)))
        print(repr(value.rsplit(",", 2)))
        print(repr(value.rsplit(sep=",", maxsplit=1)))
        print(repr("aaa".rsplit("aa", 2)))
        print(repr("aaaaa".rsplit("aa", 3)))

        whitespace = "  one  two   three  "
        print(repr(whitespace.rsplit()))
        print(repr(whitespace.rsplit(None, 0)))
        print(repr(whitespace.rsplit(None, 1)))
        print(repr(whitespace.rsplit(None, 2)))
        print(repr("A😀B😀C".rsplit("😀", 1)))

        try:
            value.rsplit("")
        except ValueError as error:
            print(str(error))
        """
    )


def test_string_rsplit_has_explicit_shared_lowering():
    at(
        """\
        def main(value: str, separator: str, limit: int):
            all_parts = value.rsplit()
            selected = value.rsplit(separator, limit)
        """,
        """
        def main(value: str, separator: str, limit: int) -> None:
            all_parts: list[str] = value.[str]rsplit!()
            selected: list[str] = value.[str]rsplit!(separator, limit)
        """,
        """
        import { split_string as $split_string } from './pyjs.python.js';

        export function main(value, separator, limit) {
            var all_parts = $split_string(value,{separator:null,maxsplit:-1,reverse:true});
            var selected = $split_string(value,{separator:separator,maxsplit:limit,reverse:true});
        }
        """,
    )


def test_string_padding_matches_python_sign_unicode_and_fill_rules():
    assert_semantics(
        """\
        print("42".zfill(5), "-42".zfill(5), "+42".zfill(5))
        print("😀".zfill(5), "already".zfill(3))
        print(repr("abc".ljust(6, ".")))
        print(repr("abc".rjust(6, ".")))
        print(repr("abc".center(6, ".")), repr("abc".center(4, ".")))
        print("abc".center(5, "😀"))

        for method in ("left", "right", "center"):
            try:
                if method == "left":
                    "abc".ljust(2, "xx")
                elif method == "right":
                    "abc".rjust(2, "xx")
                else:
                    "abc".center(2, "xx")
            except TypeError as error:
                print(str(error))
        """
    )


def test_string_padding_has_explicit_lowering():
    at(
        """\
        def main(value: str, width: int, fill: str):
            zeroed = value.zfill(width)
            left = value.ljust(width)
            right = value.rjust(width, fill)
            centered = value.center(width, fill)
        """,
        """
        def main(value: str, width: int, fill: str) -> None:
            zeroed: str = value.[str]zfill!(width)
            left: str = value.[str]ljust!(width)
            right: str = value.[str]rjust!(width, fill)
            centered: str = value.[str]center!(width, fill)
        """,
        """
        import { justify_string as $justify_string } from './pyjs.python.js';

        export function main(value, width, fill) {
            var zeroed = ((value,width)=>{const padding=width-Array.from(value).length;if(padding<=0)return value;const sign=/^[+-]/.test(value)?value[0]:'';const digits=sign?value.slice(1):value;return sign+'0'.repeat(padding)+digits;})(value,width);
            var left = $justify_string(value,width,' ','left');
            var right = $justify_string(value,width,fill,'right');
            var centered = $justify_string(value,width,fill,'center');
        }
        """,
    )


def test_string_partition_matches_python_first_last_and_missing_rules():
    assert_semantics(
        """\
        value = "name=value=extra"
        print(repr(value.partition("=")))
        print(repr(value.rpartition("=")))
        print(repr(value.partition("missing")))
        print(repr(value.rpartition("missing")))
        print(repr("A😀B😀C".partition("😀")))
        print(repr("A😀B😀C".rpartition("😀")))

        for reverse in (False, True):
            try:
                if reverse:
                    value.rpartition("")
                else:
                    value.partition("")
            except ValueError as error:
                print(str(error))
        """
    )


def test_string_partition_has_explicit_shared_lowering():
    at(
        """\
        def main(value: str, separator: str):
            first = value.partition(separator)
            last = value.rpartition(separator)
        """,
        """
        def main(value: str, separator: str) -> None:
            first: tuple[str, str, str] = value.[str]partition!(separator)
            last: tuple[str, str, str] = value.[str]rpartition!(separator)
        """,
        """
        import { partition_string as $partition_string } from './pyjs.python.js';

        export function main(value, separator) {
            var first = $partition_string(value,separator,false);
            var last = $partition_string(value,separator,true);
        }
        """,
    )


def test_ord_and_chr_match_python_unicode_and_failure_semantics():
    assert_semantics(
        """\
        print(ord("A"), ord("😀"))
        print(chr(65), chr(0x1F600))
        print(ord(chr(0x10FFFF)))

        for value in ("", "ab"):
            try:
                ord(value)
            except TypeError as error:
                print(str(error))

        for value in (-1, 0x110000):
            try:
                chr(value)
            except ValueError as error:
                print(str(error))
        """
    )


def test_ord_and_chr_have_explicit_inline_lowering():
    at(
        """\
        def main(character: str, codepoint: int):
            value = ord(character)
            text = chr(codepoint)
        """,
        """
        def main(character: str, codepoint: int) -> None:
            value: int = ord(character)
            text: str = chr(codepoint)
        """,
        """
        export function main(character, codepoint) {
            var value = ((characters)=>{if(characters.length!==1)throw new TypeError(`ord() expected a character, but string of length ${characters.length} found`);return characters[0].codePointAt(0);})(Array.from(character));
            var text = ((value)=>{if(value<0||value>0x10ffff)throw new RangeError('chr() arg not in range(0x110000)');return String.fromCodePoint(value);})(codepoint);
        }
        """,
    )


def test_string_splitlines_matches_python_line_boundaries_and_endings():
    assert_semantics(
        """\
        print(repr("".splitlines()))
        print(repr("a\\n".splitlines()))
        print(repr("a\\n\\n".splitlines()))
        print(repr("\\r\\n".splitlines()), repr("\\r\\n".splitlines(True)))
        value = "a\\x1cb\\x85c\\u2028d\\u2029e"
        print(repr(value.splitlines()))
        print(len(value.splitlines(keepends=True)))
        print(value.splitlines(True)[0] == "a\\x1c")
        print(value.splitlines(True)[1] == "b\\x85")
        print(value.splitlines(True)[2] == "c\\u2028")
        """
    )


def test_string_splitlines_has_explicit_runtime_lowering():
    at(
        """\
        def main(value: str, keepends: bool):
            plain = value.splitlines()
            retained = value.splitlines(keepends=keepends)
        """,
        """
        def main(value: str, keepends: bool) -> None:
            plain: list[str] = value.[str]splitlines!()
            retained: list[str] = value.[str]splitlines!(keepends=keepends)
        """,
        """
        import { split_lines as $split_lines } from './pyjs.python.js';

        export function main(value, keepends) {
            var plain = $split_lines(value,false);
            var retained = $split_lines(value,keepends);
        }
        """,
    )


def test_string_prefix_and_suffix_checks_match_bounds_and_tuple_choices():
    assert_semantics(
        """\
        value = "A😀middle😀Z"
        print(value.startswith("A😀"), value.endswith("😀Z"))
        print(value.startswith("middle", 2), value.endswith("middle", 0, 8))
        print(value.startswith(("missing", "A")))
        print(value.endswith(("missing", "Z")))
        print(value.startswith(()), value.endswith(()))
        print(value.startswith("", len(value)), value.startswith("", 20))
        print(value.endswith("", len(value)), value.endswith("", 20))
        print(value.startswith("", 3, 2), value.endswith("", 3, 2))
        """
    )


def test_string_prefix_and_suffix_keep_simple_calls_concise():
    at(
        """\
        def main(value: str, prefix: str, choices: tuple[str, ...], start: int):
            simple = value.startswith(prefix)
            bounded = value.endswith(choices, start)
        """,
        """
        def main(value: str, prefix: str, choices: tuple__str__variadic, start: int) -> None:
            simple: bool = value.[str]startswith!(prefix)
            bounded: bool = value.[str]endswith!(choices, start)
        """,
        """
        export function main(value, prefix, choices, start) {
            var simple = value.startsWith(prefix);
            var bounded = ((value,affix,start,end,suffix)=>{const values=Array.from(value);const length=values.length;let first=start;if(first<0)first=Math.max(length+first,0);else if(first>length)return false;let last=end===null?length:end;if(last<0)last=Math.max(length+last,0);else last=Math.min(last,length);if(last<first)return false;const selected=values.slice(first,last).join('');const choices=Array.isArray(affix)?affix:[affix];return choices.some(choice=>suffix?selected.endsWith(choice):selected.startsWith(choice));})(value,choices,start,null,true);
        }
        """,
    )


def test_string_character_class_checks_match_python_unicode_semantics():
    assert_semantics(
        """\
        print("letters".isalpha(), "éΩ漢".isalpha(), "Ⅻ".isalpha())
        print("abc123".isalnum(), "Ⅻ²".isalnum(), "abc-123".isalnum())
        print("".isalpha(), "".isalnum())
        print("ASCII\\x1f".isascii(), "".isascii(), "é".isascii())
        print(" \\t\\u2003\\x1c".isspace(), "".isspace(), "\\ufeff".isspace())
        """
    )


def test_string_character_class_checks_have_explicit_lowering():
    at(
        """\
        def main(value: str):
            alpha = value.isalpha()
            alphanumeric = value.isalnum()
            ascii_only = value.isascii()
            whitespace = value.isspace()
        """,
        """
        def main(value: str) -> None:
            alpha: bool = value.[str]isalpha!()
            alphanumeric: bool = value.[str]isalnum!()
            ascii_only: bool = value.[str]isascii!()
            whitespace: bool = value.[str]isspace!()
        """,
        r"""
        export function main(value) {
            var alpha = /^\p{L}+$/u.test(value);
            var alphanumeric = /^[\p{L}\p{N}]+$/u.test(value);
            var ascii_only = /^[\x00-\x7f]*$/.test(value);
            var whitespace = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/u.test(value);
        }
        """,
    )


def test_string_repetition_handles_zero_and_negative_counts():
    assert_semantics(
        """\
        print(repr("ab" * 3), repr(2 * "ab"))
        print(repr("ab" * 0), repr("ab" * -2), repr(-2 * "ab"))
        """
    )


def test_string_repetition_has_explicit_nonpositive_lowering():
    at(
        """\
        def main(value: str, count: int):
            right = value * count
            left = count * value
        """,
        """
        def main(value: str, count: int) -> None:
            right: str = value.[str]__mul__!(count)
            left: str = value.[str]__rmul__!(count)
        """,
        """
        export function main(value, count) {
            var right = (count <= 0 ? '' : value.repeat(count));
            var left = (count <= 0 ? '' : value.repeat(count));
        }
        """,
    )


def test_string_join_accepts_lazy_and_custom_iterables():
    assert_semantics(
        """\
        from collections.abc import Iterator

        from pyjs import js

        @js
        class Words:
            def __iter__(self) -> Iterator[str]:
                return iter(["alpha", "beta"])

        print("|".join([]))
        print("|".join(["single"]))
        print("|".join(word.upper() for word in Words()))
        print("😀".join(Words()))
        """
    )

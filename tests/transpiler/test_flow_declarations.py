from pyjs.testing.helpers import ad, at, diagnostic_text


def test_guarded_loop_declaration_remains_visible_after_loop():
    at('''
        def main(values: list[int | None]) -> int:
            for value in values:
                if value is None:
                    continue
                copied = value + 1
            return copied
    ''', '''
        def main(values: list__intUNoneType) -> int:
            for value: int | None in values:
                if value.[object]__is__!(None):
                    continue
                copied: int = value.[int]__add__!(1)
            return copied
    ''', '''
        export function main(values) {
            for (var value of values) {
                if (value == null) {
                    continue
                }
                var copied = value + 1;
            }
            return copied;
        }
    ''')


def test_guarded_branches_cannot_hide_numeric_representation_conflicts():
    ad('''\
        from pyjs import int8

        def main(flag: bool, value: int | None) -> int:
            if flag:
                if value is None:
                    return 0
                copied = int8(100)
            else:
                copied = 100
            return copied + 100
    ''', diagnostic_text(
        "guarded_width.py", 4, "if flag:", "^^^^^^^^",
        "pyjs.CompilationError: Branches assign incompatible numeric representations to 'copied' [PYJS1103]",
        "help: Use an explicit fixed-width annotation to convert every branch, or keep every branch as an ordinary Python number.",
    ), filename="guarded_width.py")


def test_guarded_branches_retain_both_union_members():
    ad('''\
        def main(flag: bool, value: int | None) -> str:
            if flag:
                if value is None:
                    return "empty"
                copied = value + 1
            else:
                copied = "text"
            return copied.upper()
    ''', diagnostic_text(
        "guarded_union.py", 8, "return copied.upper()", "       ^^^^^^^^^^^^",
        "pyjs.CompilationError: Attribute 'upper' is not defined on every member of int | str [PYJS1003]",
        "help: Missing from int. Narrow the value with isinstance() before accessing 'upper'.",
    ), filename="guarded_union.py")


def test_guarded_declaration_remains_visible_after_finally():
    at('''
        def main(value: int | None) -> int:
            try:
                if value is None:
                    raise ValueError("missing")
                copied = value + 1
            finally:
                value = None
            return copied
    ''', '''
        def main(value: int | None) -> int:
            try:
                if value.[object]__is__!(None):
                    raise ValueError('missing')
                copied: int = value.[int]__add__!(1)
            finally:
                value = None
            return copied
    ''', '''
        export function main(value) {
            try {
                if (value == null) {
                    throw new RangeError('missing');
                }
                var copied = value + 1;
            } finally {
                value = null;
            }
            return copied;
        }
    ''')


def test_retaining_new_locals_does_not_export_a_conditional_field_proof():
    ad('''\
        from pyjs import js

        @js
        class Holder:
            value: str | None
            def __init__(self):
                self.value = None

        def main(holder: Holder, flag: bool):
            if flag:
                if holder.value is None:
                    return
                copied = holder.value
            return holder.value.upper()
    ''', diagnostic_text(
        "conditional_field.py", 14, "return holder.value.upper()",
        "       ^^^^^^^^^^^^^^^^^^",
        "pyjs.CompilationError: Attribute 'upper' is not defined on every member of str | NoneType [PYJS1003]",
        "help: Missing from NoneType. Narrow the value with isinstance() before accessing 'upper'.",
    ), filename="conditional_field.py")

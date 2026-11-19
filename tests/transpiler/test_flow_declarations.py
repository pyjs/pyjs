from pyjs.testing.helpers import ad, at, diagnostic_text


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

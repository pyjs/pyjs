import textwrap

import pytest

from pyjs.cli import main


def diagnostic(*lines):
    return "\n".join(lines) + "\n"


def test_supported_newcomer_program_runs_with_python_semantics(capsys):
    source = textwrap.dedent(
        """\
        from pyjs import JS, js

        LIMIT: JS = 3

        @js
        class Add:
            def __call__(self, value: int) -> int:
                return value + 1

        first = {"a": 1, "shared": 2}
        second = {**first, "b": 3, "shared": 4}
        print(Add()(LIMIT), second["a"], second["b"], second["shared"])
        """
    )

    assert main(["-c", source]) == 0

    captured = capsys.readouterr()
    assert captured.out == "4 1 3 4\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "total = 3\nprint(ttoal)",
            diagnostic(
                '  File "<string>", line 2',
                "    print(ttoal)",
                "          ^^^^^",
                "pyjs.CompilationError: Name 'ttoal' is not defined "
                "[PYJS1001]",
                "help: Did you mean 'total'?",
            ),
        ),
        (
            "class Helper:\n    pass\n\nprint(Helper())",
            diagnostic(
                '  File "<string>", line 5',
                "    print(Helper())",
                "          ^^^^^^",
                "pyjs.CompilationError: Class 'Helper' is not available to "
                "client code [PYJS1002]",
                "note: <string>:1:7: defined here without client compilation "
                "enabled",
                "help: Import js from pyjs and decorate 'Helper' with @js.",
            ),
        ),
        (
            textwrap.dedent(
                """\
                from pyjs import js

                LIMIT = 3

                @js
                def current() -> int:
                    return LIMIT

                print(current())
                """
            ),
            diagnostic(
                '  File "<string>", line 5',
                "    return LIMIT",
                "           ^^^^^",
                "pyjs.CompilationError: Name 'LIMIT' is a Python value, not a "
                "client value [PYJS1004]",
                "help: Import JS from pyjs and declare it as a client value: "
                "LIMIT: JS = 3.",
            ),
        ),
        (
            textwrap.dedent(
                """\
                from pyjs import js

                @js
                class Card:
                    def __init__(self):
                        pass

                    def title(self) -> str:
                        return self.label

                print(Card().title())
                """
            ),
            diagnostic(
                '  File "<string>", line 10',
                "    return self.label",
                "           ^^^^^^^^^^",
                "pyjs.CompilationError: Attribute 'label' is not defined on "
                "'Card' [PYJS1003]",
                "note: <string>:6:9: initialize instance attributes here",
                "help: Define self.label in Card.__init__().",
            ),
        ),
        (
            "from pathlib import Path\n\nprint(Path('.').name)",
            diagnostic(
                '  File "<string>", line 4',
                "    print(Path('.').name)",
                "          ^^^^",
                "pyjs.CompilationError: Class 'Path' is not available to "
                "client code [PYJS1002]",
                "help: 'Path' comes from external module 'pathlib'. Use a "
                "supported PyJS API or add a client binding for that library.",
            ),
        ),
        (
            'print(b"abc")',
            diagnostic(
                '  File "<string>", line 1',
                '    print(b"abc")',
                "          ^^^^^^",
                "pyjs.CompilationError: bytes literals are not supported "
                "[PYJS2001]",
                "help: Use str for text or a supported typed-array API for "
                "binary data.",
            ),
        ),
        (
            "print(1 + 2j)",
            diagnostic(
                '  File "<string>", line 1',
                "    print(1 + 2j)",
                "              ^^",
                "pyjs.CompilationError: complex number literals are not "
                "supported [PYJS2001]",
                "help: Represent the real and imaginary components explicitly.",
            ),
        ),
        (
            "print(...)",
            diagnostic(
                '  File "<string>", line 1',
                "    print(...)",
                "          ^^^",
                "pyjs.CompilationError: ellipsis values are not supported "
                "[PYJS2001]",
                "help: Use None or an explicit client-side sentinel value.",
            ),
        ),
        (
            textwrap.dedent(
                """\
                from pyjs import js

                @js
                class One:
                    one: str

                @js
                class Two:
                    two: str

                @js
                def label(value: One | Two) -> str:
                    return value.one

                print(label(One()))
                """
            ),
            diagnostic(
                '  File "<string>", line 13',
                "    return value.one",
                "           ^^^^^^^^^",
                "pyjs.CompilationError: Attribute 'one' is not defined on every "
                "member of One | Two [PYJS1003]",
                "help: Missing from Two. Narrow the value with isinstance() "
                "before accessing 'one'.",
            ),
        ),
        (
            textwrap.dedent(
                """\
                from pyjs import js

                @js
                class Left:
                    pass

                @js
                class Right:
                    pass

                @js
                class Child(Left, Right):
                    pass

                print(Child())
                """
            ),
            diagnostic(
                '  File "<string>", line 12',
                "    class Child(Left, Right):",
                "          ^^^^^",
                "pyjs.CompilationError: Multiple inheritance is not supported "
                "for 'Child' [PYJS2001]",
                "help: Use one base class and compose the remaining behavior.",
            ),
        ),
    ],
)
def test_common_mistakes_have_complete_actionable_diagnostics(
    source,
    expected,
    capsys,
):
    assert main(["-c", source]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == expected

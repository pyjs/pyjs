import pytest

from pyjs.testing.helpers import ad, at


@pytest.mark.parametrize("imported", ["Literal", "Choice"])
def test_string_literal_aliases_validate_calls_returns_and_containers(imported):
    at(
        """
        from typing import Literal as IMPORTED

        type Mode = IMPORTED["open", "closed"]

        @js
        def normalize(mode: Mode) -> Mode:
            if mode == "open":
                return "open"
            return "closed"

        def main():
            modes: list[IMPORTED["open", "closed"]] = ["open", "closed"]
            print(normalize(modes[0]))
        """.replace("IMPORTED", imported),
        """
        def normalize(mode: Literal['open', 'closed']) -> Literal['open', 'closed']:
            if mode.[object]__eq__!('open'):
                return 'open'
            return 'closed'

        def main() -> None:
            modes: list[Literal['open', 'closed']] = ['open', 'closed']
            print(normalize($get_list_item(modes, 0)))
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function normalize(mode) {
            if (mode === 'open') {
                return 'open';
            }
            return 'closed';
        }

        export function main() {
            var modes = ['open', 'closed'];
            console.log(normalize($get_list_item(modes, 0)));
        }
        """,
    )


def test_literal_equality_narrows_true_false_and_elif_branches():
    at(
        """
        from typing import Literal

        type Mode = Literal["open", "closed", "archived"]

        @js
        def open_mode(value: Literal["open"]):
            pass

        @js
        def closed_mode(value: Literal["closed"]):
            pass

        @js
        def archived_mode(value: Literal["archived"]):
            pass

        @js
        def route(mode: Mode):
            if mode == "open":
                open_mode(mode)
            elif mode != "archived":
                closed_mode(mode)
            else:
                archived_mode(mode)

        def main(mode: Mode):
            route(mode)
        """,
        """
        def open_mode(value: Literal['open']) -> None:
            pass

        def closed_mode(value: Literal['closed']) -> None:
            pass

        def archived_mode(value: Literal['archived']) -> None:
            pass

        def route(mode: Literal['open', 'closed', 'archived']) -> None:
            if mode.[object]__eq__!('open'):
                open_mode(mode)
            elif mode.[object]__ne__!('archived'):
                closed_mode(mode)
            else:
                archived_mode(mode)

        def main(mode: Literal['open', 'closed', 'archived']) -> None:
            route(mode)
        """,
        """
        export function open_mode(value) {
        }

        export function closed_mode(value) {
        }

        export function archived_mode(value) {
        }

        export function route(mode) {
            if (mode === 'open') {
                open_mode(mode);
            } else if (mode !== 'archived') {
                closed_mode(mode);
            } else {
                archived_mode(mode);
            }
        }

        export function main(mode) {
            route(mode);
        }
        """,
    )


def test_dataclass_fields_preserve_literal_annotations():
    at(
        """
        from dataclasses import dataclass
        from typing import Literal

        @js
        @dataclass(repr=False, eq=False)
        class Panel:
            mode: Literal["open", "closed"]

        def main():
            panel = Panel("open")
            print(panel.mode)
        """,
        """
        class Panel:

            def __init__(mode: Literal['open', 'closed']) -> None:
                self.mode: Literal['open', 'closed'] = mode

        def main() -> None:
            panel: Panel = Panel('open')
            print(panel.mode)
        """,
        """
        export class Panel {

            constructor(mode) {
                this.mode = mode;
            }
        }

        export function main() {
            var panel = new Panel('open');
            console.log(panel.mode);
        }
        """,
    )


def test_dataclass_fields_accept_literal_defaults():
    at(
        """
        from dataclasses import dataclass
        from typing import Literal

        @js
        @dataclass(repr=False, eq=False)
        class Panel:
            mode: Literal["open", "closed"] = "open"

        def main():
            panel = Panel()
            print(panel.mode)
        """,
        """
        class Panel:

            def __init__(mode: Literal['open', 'closed']='open') -> None:
                self.mode: Literal['open', 'closed'] = mode

        def main() -> None:
            panel: Panel = Panel()
            print(panel.mode)
        """,
        """
        export class Panel {

            constructor({ mode='open'} = {}) {
                this.mode = mode;
            }
        }

        export function main() {
            var panel = new Panel();
            console.log(panel.mode);
        }
        """,
    )


def test_literal_mismatches_have_focused_diagnostics():
    ad(
        """
        from typing import Literal
        from pyjs import js

        @js
        def select(mode: Literal["open", "closed"]):
            pass

        def main():
            select("missing")
        """,
        """
          File "literal_call.py", line 10
            select("missing")
                   ^^^^^^^^^
        pyjs.CompilationError: Argument 'mode' to select expects Literal['open', 'closed'], got str [PYJS1104]
        help: Pass a value compatible with Literal['open', 'closed'].
        """,
        filename="literal_call.py",
    )
    ad(
        """
        from typing import Literal
        from pyjs import js

        @js
        def main():
            mode: Literal["open", "closed"] = "missing"
        """,
        """
          File "literal_assignment.py", line 7
            mode: Literal["open", "closed"] = "missing"
                                              ^^^^^^^^^
        pyjs.CompilationError: Cannot assign str to a value of type Literal['open', 'closed'] [PYJS1103]
        help: Assign a value compatible with Literal['open', 'closed'].
        """,
        filename="literal_assignment.py",
    )
    ad(
        """
        from typing import Literal
        from pyjs import js

        @js
        class Panel:
            mode: Literal["open", "closed"] = "missing"

        def main():
            print(Panel().mode)
        """,
        """
          File "literal_field.py", line 7
            mode: Literal["open", "closed"] = "missing"
                                              ^^^^^^^^^
        pyjs.CompilationError: Cannot assign str to class field 'Panel.mode' of type Literal['open', 'closed'] [PYJS1103]
        help: Assign a value compatible with Literal['open', 'closed'] or change the declaration of Panel.mode.
        """,
        filename="literal_field.py",
    )


def test_non_string_literals_have_a_located_diagnostic():
    ad(
        """
        from typing import Literal
        from pyjs import js

        @js
        def choose(value: Literal[1, 2]):
            pass
        """,
        """
          File "literal_kind.py", line 5
            def choose(value: Literal[1, 2]):
                                      ^^^^
        pyjs.CompilationError: Literal annotations require string values [PYJS2001]
        help: Use one or more string values, such as Literal['open', 'closed'].
        """,
        filename="literal_kind.py",
    )

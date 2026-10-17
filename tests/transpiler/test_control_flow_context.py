from pyjs.testing.helpers import ad, at, diagnostic_text


def test_context_manager_calls_enter_and_exit_around_the_body():
    at(
        """
        from pyjs import js

        @js
        class Scope:
            def __enter__(self) -> str:
                print("enter")
                return "value"

            def __exit__(
                self,
                exc_type: type | None,
                exc: Exception | None,
                traceback: object | None,
            ) -> bool:
                print("exit")
                return False

        def main():
            with Scope() as value:
                print(value)
        """,
        """
        class Scope:

            def __enter__() -> str:
                print('enter')
                return 'value'

            def __exit__(exc_type: type[object] | None, exc: Exception | None, traceback: object | None) -> bool:
                print('exit')
                return False

        def main() -> None:
            with Scope() as value:
                print(value)
        """,
        """
        export class Scope {

            __enter__() {
                console.log('enter');
                return 'value';
            }

            __exit__(exc_type, exc, traceback) {
                console.log('exit');
                return false;
            }
        }

        export function main() {
            const $manager0 = new Scope();
            const $entered1 = $manager0.__enter__();
            let $failed3 = false;
            try {
                var value = $entered1;
                console.log(value);
            } catch ($caught2) {
                $failed3 = true;
                if (!$manager0.__exit__($caught2.constructor, $caught2, null)) {
                    throw $caught2;
                }
            } finally {
                if (!$failed3) {
                    $manager0.__exit__(null, null, null);
                }
            }
        }
        """,
    )


def test_context_manager_requires_both_protocol_methods():
    ad(
        """\
        from pyjs import js

        @js
        class IncompleteScope:
            def __enter__(self) -> str:
                return "value"

        def main():
            with IncompleteScope():
                print("body")
        """,
        diagnostic_text(
            "context.py",
            9,
            "with IncompleteScope():",
            "     ^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Context manager 'IncompleteScope' has no "
            "__exit__ method [PYJS1003]",
            "help: Define both __enter__() and __exit__() on the context manager.",
        ),
        filename="context.py",
    )

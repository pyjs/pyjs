from .helpers import assert_semantics


def test_context_managers_handle_normal_exception_and_suppressed_paths():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Scope:
            def __init__(self, name: str, suppress: bool = False):
                self.name = name
                self.suppress = suppress

            def __enter__(self) -> str:
                print("enter " + self.name)
                return self.name

            def __exit__(
                self,
                exc_type: type | None,
                exc: Exception | None,
                traceback: object | None,
            ) -> bool:
                print("exit " + self.name)
                print(exc is not None)
                return self.suppress

        with Scope("normal") as value:
            print(value)
        try:
            with Scope("rethrow"):
                raise ValueError("failed")
        except ValueError:
            print("caught")
        with Scope("suppress", True):
            raise ValueError("suppressed")
        print("continued")
        """
    )


def test_context_managers_unwind_in_reverse_and_exit_on_return():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Scope:
            def __init__(self, name: str):
                self.name = name

            def __enter__(self) -> str:
                print("enter " + self.name)
                return self.name

            def __exit__(
                self,
                exc_type: type | None,
                exc: Exception | None,
                traceback: object | None,
            ) -> bool:
                print("exit " + self.name)
                return False

        @js
        def run() -> str:
            with Scope("outer") as outer, Scope("inner") as inner:
                print(outer + " " + inner)
                return "done"

        print(run())
        """
    )


def test_enter_failure_does_not_call_its_own_exit():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class BrokenScope:
            def __enter__(self) -> str:
                print("enter")
                raise ValueError("broken")

            def __exit__(
                self,
                exc_type: type | None,
                exc: Exception | None,
                traceback: object | None,
            ) -> bool:
                print("unexpected exit")
                return False

        try:
            with BrokenScope():
                print("unreachable")
        except ValueError:
            print("caught")
        """
    )


def test_context_manager_calls_retain_reachable_overrides():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class BaseScope:
            def __enter__(self) -> str:
                return "base"

            def __exit__(
                self,
                exc_type: type | None,
                exc: Exception | None,
                traceback: object | None,
            ) -> bool:
                print("base exit")
                return False

        @js
        class ChildScope(BaseScope):
            def __enter__(self) -> str:
                return "child"

            def __exit__(
                self,
                exc_type: type | None,
                exc: Exception | None,
                traceback: object | None,
            ) -> bool:
                print("child exit")
                return False

        @js
        def run(scope: BaseScope):
            with scope as value:
                print(value)

        run(ChildScope())
        """
    )

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize('operation', [
    'saved.append(error)',
    'saved = [error]',
    'saved = [error for index in range(1)]',
    'alias = error; saved.append(alias)',
    'holder.error = error',
    'saved[0] = error',
    'return [error]',
    'forward(error)',
    'message = error.args',
    'callback = lambda: str(error)',
    'saved = (error is None for index in range(1))',
    'saved = (index for index in range(1) if error is not None)',
    'saved = (item for index in range(1) for item in [str(error)])',
    'saved = (item for item in (str(error) for index in range(1)))',
])
def test_caught_snapshots_cannot_escape(operation):
    with pytest.raises(CompilationError, match='exception details are borrowed') as caught:
        transpile_llvm(f'''
class Holder:
    def __init__(self):
        self.error: ValueError | None = None
def forward(error: ValueError) -> None:
    pass
def main() -> list[ValueError]:
    holder = Holder()
    saved: list[ValueError] = []
    for index in range(2):
        try:
            raise ValueError(str(index))
        except ValueError as error:
            {operation}
    return saved
''')
    assert caught.value.lineno is not None


@pytest.mark.parametrize('operation', ['is', 'is not'])
@pytest.mark.parametrize('context', [False, True])
def test_reraised_snapshot_identity_is_rejected(operation, context):
    statement = 'with Scope():\n                raise outer' if context else 'raise outer'
    with pytest.raises(CompilationError, match='exception identity comparisons require None') as caught:
        transpile_llvm(f'''
class Scope:
    def __enter__(self) -> None:
        pass
    def __exit__(self, kind: object, value: object, traceback: object) -> None:
        pass
def main() -> bool:
    try:
        raise ValueError("same")
    except ValueError as outer:
        try:
            {statement}
        except ValueError as inner:
            return outer {operation} inner
    return False
''')
    assert caught.value.lineno is not None
    assert '__exit__ type token' not in str(caught.value)


def test_shadowed_str_cannot_receive_a_caught_snapshot():
    with pytest.raises(CompilationError, match='not a shadowed callable'):
        transpile_llvm('''
from typing import Callable
def keep(value: ValueError) -> str:
    return "not a message copy"
def main() -> str:
    str: Callable[[ValueError], str] = keep
    try:
        raise ValueError("message")
    except ValueError as error:
        return str(error)
    return "missing"
''')


def test_authored_completion_helper_call_cannot_receive_a_caught_snapshot():
    # Only compiler-generated delegation is allowed to borrow the record for
    # provenance checking; importing its helper does not grant an escape hatch.
    with pytest.raises(CompilationError, match='exception details are borrowed'):
        transpile_llvm('''
from pyjs.native.delegation import completion_cursor
def main() -> str:
    try:
        raise StopIteration(1)
    except StopIteration as error:
        return str(completion_cursor(error))
    return "missing"
''')


@pytest.mark.parametrize('optimize', [0, 2])
def test_caught_messages_can_be_copied_across_catches_and_gc(tmp_path, optimize):
    LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def main() -> str:
    gc_set_threshold(1)
    messages: list[str] = []
    for index in range(2):
        try:
            try:
                raise ValueError(str(index))
            except ValueError as error:
                assert error is not None
                messages.append(str(error))
                raise error
        except ValueError as reraised:
            gc_collect()
            messages.append(str(reraised))
    gc_collect()
    return ":".join(messages)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_eager_exception_copies_can_feed_deferred_iteration(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
def main() -> str:
    try:
        raise ValueError("copied")
    except ValueError as error:
        eager = [str(error) for index in range(2)]
        saved = (item for item in [str(error)])
    gc_collect()
    return ":".join(eager) + ":" + next(saved)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""

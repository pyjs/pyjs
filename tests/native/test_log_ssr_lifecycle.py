import errno
from pathlib import Path

import pytest

from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.native.logs_source import logs, render_logs


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("direct", [False, True], ids=["buffered", "descriptor"])
def test_managed_log_renderer_reclaims_requests_and_recovers(tmp_path, optimize, direct):
    source = Path(__file__).with_name("logs_source.py").read_text() + '''

from pyjs.native import gc_collect, gc_count, gc_set_threshold

def request_page(values: list[LogEntry], fail_after: int) -> Element:
    gc_collect()
    if gc_count() != 0:
        raise RuntimeError("previous request is still rooted")
    gc_set_threshold(64, byte_limit=4096)
    rows: list[Element] = []
    for value in values:
        rows.append(log_row(value))
        if len(rows) == fail_after:
            raise ValueError("interrupted after " + str(fail_after) + " rows")
        gc_collect()
    page = div(tw("log-explorer"), {"data-log-count": str(len(values))}, *rows)
    gc_collect()
    return page

def render_request(values: list[LogEntry], fail_after: int) -> str:
    result = render_html(request_page(values, fail_after))
    gc_collect()
    return result

def write_request(values: list[LogEntry], fail_after: int, descriptor: int) -> int:
    return write_html_fd(request_page(values, fail_after), descriptor)
'''
    entries = logs(128)
    expected = render_logs(entries)
    assert len(expected.encode()) > 100_000
    library = LLVM().compile_library(
        source, tmp_path, optimize=optimize,
        entry_point="write_request" if direct else "render_request", direct=direct,
    )
    try:
        assert library.managed
        for _ in range(3):
            for batch in (entries, [], entries[:7]):
                assert library.render(batch, -1) == render_logs(batch)
            with pytest.raises(LLVMRuntimeError, match="interrupted after 48 rows") as caught:
                library.render(entries, 48)
            assert caught.value.exception_type == "ValueError"
            assert library.render(entries, -1) == expected
            # A valid native render can still fail at the OS output boundary.
            # Both paths must drop their request roots before the next call.
            assert library.render_to_fd(-1, entries, -1) == errno.EBADF
            assert library.render(entries, -1) == expected
    finally:
        library.close()

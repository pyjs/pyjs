from types import SimpleNamespace

import pytest

from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
def test_binary_log_rows_render_through_the_host_abi_and_recover(tmp_path, optimize):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

class Log:
    def __init__(self, payload: bytes):
        self.payload = payload

def render_logs(values: list[Log], reject: bool) -> str:
    gc_set_threshold(1)
    rows: list[Element] = []
    for item in values:
        try:
            text = item.payload.decode()
            for line in text.splitlines():
                rows.append(div(line.expandtabs(4)))
        except UnicodeDecodeError:
            if reject:
                raise
            rows.append(div("binary:" + item.payload.hex()))
        finally:
            gc_collect()
    return render_html(div(*rows))
'''
    values = [SimpleNamespace(payload=payload) for payload in (
        b"<start>\tready\r\n", b"\xff\x00", "é😀\n\0done".encode(),
    )]
    comparison = LLVM().assert_library_matches_python(
        source, values, False, directory=tmp_path, entry_point="render_logs", optimize=optimize,
    )
    library = comparison.library
    try:
        for _ in range(3):
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(values, True)
            assert caught.value.exception_type == "UnicodeDecodeError"
            assert library.render(values, False) == comparison.python
        with pytest.raises(TypeError, match=r"values\[0\].payload must be bytes"):
            library.render([{"payload": "not bytes"}], False)
    finally:
        library.close()

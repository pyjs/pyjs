from pathlib import Path

import pytest

from pyjs.tooling.llvm import LLVM
from tests.native.logs_source import logs


@pytest.mark.parametrize("direct", [False, True], ids=["buffered", "descriptor"])
def test_log_ssr_formats_shared_recursive_context_and_escapes_output(tmp_path, direct):
    source = Path(__file__).with_name("logs_source.py").read_text() + '''

from pyjs.native import gc_collect

type Context = str | int | bool | list[Context] | dict[str, Context] | None

def context_page(values: list[LogEntry], context: Context) -> Element:
    page = div(
        logs_page(values),
        tag("pre", {"data-context": ""}, repr(context)),
    )
    gc_collect()
    return page

def render_context(values: list[LogEntry], context: Context) -> str:
    return render_html(context_page(values, context))

def write_context(values: list[LogEntry], context: Context, descriptor: int) -> int:
    return write_html_fd(context_page(values, context), descriptor)
'''
    entries = logs(32)
    shared = ["café 🙂 <payload> & \"quoted\"", 7, True, None]
    context = {"left": shared, "right": shared}
    context["self"] = context
    context["payload"] = "<script>not executable</script> & café 🙂\n" * 5000
    comparison = LLVM().compare_library_with_python(
        source, entries, context, directory=tmp_path,
        entry_point="write_context" if direct else "render_context",
        direct=direct,
    )
    try:
        assert comparison.matches
        output = comparison.native
        assert len(output.encode()) > 256 * 1024
        assert output.count("<article") == len(entries)
        assert output.count("<pre data-context=") == 1
        assert "<script>" not in output
        assert "&lt;script&gt;not executable&lt;/script&gt;" in output
        assert "{...}" in output
        # A borrowed cyclic context must not leave native formatting state in
        # the next call, nor may collection mutate the original Python graph.
        assert comparison.library.render(entries, context) == output
        assert context["left"] is context["right"] is shared
        assert context["self"] is context
    finally:
        comparison.library.close()

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("keyword", [False, True])
def test_dynamic_tw_calls_match_python_in_all_builder_paths(tmp_path, optimize, keyword):
    argument = 'classes=label(events)' if keyword else 'label(events)'
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import div, tag, tw
from pyjs.web.ssr import render_html

def label(events: list[str]) -> str:
    events.append(str(len(events)))
    gc_collect()
    return "dynamic-" + str(len(events)) + "<&"

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    direct = div(tw({argument}), "direct")
    stored = tw({argument})
    staged = div(stored, tw({argument}), "staged")
    tag(staged, tw({argument}))
    return render_html(div(direct, staged)) + stored["class"] + ",".join(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""

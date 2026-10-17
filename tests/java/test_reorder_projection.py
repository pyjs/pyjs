from pyjs.ui.reorderable import ReorderItem, project_reorder
from tests.java.test_native_boundaries import run_jvm


def test_subtree_projection_runs_on_jvm(tmp_path):
    source = '''
from pyjs.ui.reorderable import ReorderItem, project_reorder

def main() -> str:
    items = [ReorderItem("parent", 0), ReorderItem("child", 1),
             ReorderItem("grandchild", 2), ReorderItem("other", 0)]
    moved = project_reorder(items, 0, 1, 2, 2)
    if moved is None:
        return "missing"
    result = ""
    for item in moved.committed_items:
        result += item.id + ":" + str(item.depth) + ";"
    return result
'''
    items = [ReorderItem("parent", 0), ReorderItem("child", 1),
             ReorderItem("grandchild", 2), ReorderItem("other", 0)]
    expected = project_reorder(items, 0, 1, 2, 2)
    assert expected is not None
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "".join(f"{item.id}:{item.depth};" for item in expected.committed_items)
    assert result.stdout == "other:0;parent:0;child:1;grandchild:2;"

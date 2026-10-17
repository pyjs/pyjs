from .helpers import RuntimeResult, format_semantics_failure


def test_semantics_failure_shows_results_diff_and_generated_javascript():
    message = format_semantics_failure(
        RuntimeResult(0, "expected\n", ""),
        RuntimeResult(1, "actual\n", "problem\n"),
        "console.log('actual');",
    )
    assert message == """\
Runtime results differ:
--- CPython
+++ JavaScript
@@ -1,3 +1,3 @@
-returncode: 0
-stdout: 'expected\\n'
-stderr: ''
+returncode: 1
+stdout: 'actual\\n'
+stderr: 'problem\\n'

Generated JavaScript:
console.log('actual');"""

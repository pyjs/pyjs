"""Unsupported JVM representation diagnostics shared by analysis and emission."""

import ast


class JVMUnsupported(Exception):
    """A program uses semantics not yet represented by the JVM backend."""

    def __init__(self, message: str, node: ast.AST | None = None, *, fragment=None) -> None:
        location = (
            f" at line {node.lineno + (fragment.line_delta if fragment is not None else 0)}"
            if node is not None and hasattr(node, "lineno")
            else ""
        )
        super().__init__(f"{message}{location}")

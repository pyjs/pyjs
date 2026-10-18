"""Unsupported JVM representation diagnostics shared by analysis and emission."""

import ast


class JVMUnsupported(Exception):
    """A program uses semantics not yet represented by the JVM backend."""

    def __init__(self, message: str, node: ast.AST | None = None) -> None:
        location = (
            f" at line {node.lineno}"
            if node is not None and hasattr(node, "lineno")
            else ""
        )
        super().__init__(f"{message}{location}")

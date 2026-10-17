"""Diagnostics shared by native lowering modules."""

import ast


class LLVMUnsupported(Exception):
    """A program uses semantics not yet represented by the LLVM backend."""

    def __init__(self, message: str, node: ast.AST | None = None) -> None:
        # Lowered allocation/field nodes retain their source expression rather
        # than copying source coordinates. Report that expression's location.
        while node is not None and not hasattr(node, "lineno"):
            source = next((getattr(node, name) for name in ("call", "source", "attribute", "target")
                           if isinstance(getattr(node, name, None), ast.AST)), None)
            if source is node:
                break
            node = source
        location = f" at line {node.lineno}" if node is not None and hasattr(node, "lineno") else ""
        self.node = node
        super().__init__(f"{message}{location}")

    def add_function_context(self, function) -> None:
        # Analysis uses function-relative coordinates, including in preparation
        # passes that can reject a value before its function body is emitted.
        if function.source_fragment is not None and self.node is not None:
            span = function.source_fragment.span(self.node)
            position = span.start_position
            column = span.source.character_column(position.line + 1, position.column) + 1
            self.add_note(f"Source location: {span.source.filename}:{position.line + 1}:{column} "
                          f"({function.name}; reported line above is function-relative)")

    def add_class_context(self, semantic) -> None:
        # Layout validation precedes function emission. Class annotations are
        # synthesized type expressions, not locations in the application's file.
        module = semantic.container
        node = module.class_definitions.get(semantic.py_cls.__name__)
        if node is not None and module.source_fragment is not None:
            span = module.source_fragment.span(node)
            position = span.start_position
            column = span.source.character_column(position.line + 1, position.column) + 1
            self.add_note(f"Source location: {span.source.filename}:{position.line + 1}:{column} "
                          f"({semantic.name} class)")

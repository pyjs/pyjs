import ast
import subprocess
from io import StringIO

from .objects import Function


class SourceWriter(StringIO):
    def __init__(self):
        super().__init__()
        self.indent_level = 0

    def indent(self, depth=1):
        self.indent_level += depth

    def dedent(self, depth=1):
        self.indent_level -= depth

    def write_space(self):
        self.write("  "*self.indent_level)

    def write_line(self, line):
        self.write_space()
        self.write(line)
        self.write("\n")


class TypeWriter(ast._Unparser):

    def visit_ModuleDef(self, node):
        self.visit_Module(node)

    def visit_Attribute(self, node):
        self.set_precedence(ast._Precedence.ATOM, node.value)
        self.traverse(node.value)
        self.write(".")
        if isinstance(node.obj, Function):
            self.write(f"[{node.obj.cls.name}]")
        self.write(node.attr)
        if isinstance(node.obj, Function) and node.obj.inline_decorator:
            self.write("!")


def write_types(ast_obj):
    return TypeWriter().visit(ast_obj)


class TailwindCSS:

    def __init__(self, tailwindcss="tailwindcss"):
        self.tailwindcss = tailwindcss

    def get_css(self, classes: set):
        html = f'<div class="{" ".join(classes)}"></div>'
        try:
            process = subprocess.run(
                [self.tailwindcss, "--content", "-"],
                input=html.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            return process.stdout.decode()
        except subprocess.CalledProcessError as e:
            print("Tailwind CLI failed:", e.stderr.decode())

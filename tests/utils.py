import difflib
import textwrap
import linecache
from io import StringIO
from pathlib import Path
from unittest import TestCase
from importlib import import_module

from types import SimpleNamespace
from pyjs.analyze import Module, analyze_module
from pyjs.transpile import Transpiler, transpile
from pyjs.utils import write_types


WIDTH = 80
TESTS_DIR = Path(__file__).parent


def diff_side_by_side(msg, first, second):
    out = StringIO()
    out.write(msg+"\n")
    differ = difflib.Differ()
    for line in differ.compare(first, second):
        padded_line = f"{line[2:]:<{WIDTH//2}}"
        if line.startswith(' '):
            out.write(f"{padded_line} | {padded_line}\n")
        elif line.startswith('-'):
            out.write(f"\033[94m{padded_line}\033[0m |\n")
        elif line.startswith('+'):
            out.write(f"{'':<{WIDTH//2}} | \033[93m{padded_line}\033[0m\n")
        elif line.startswith('?'):
            pass
    return out.getvalue()


def create_module(src, filename="_test_.py"):
    linecache.cache[filename] = (
        len(src),  # size
        None,  # mtime
        [line + '\n' for line in src.splitlines()],
        filename
    )
    compiled = compile(src, filename, 'exec')
    name = filename.split('.')[0]
    namespace = {
        "__name__": name,
        "__module__": name,
    }
    exec(compiled, namespace)
    return SimpleNamespace(**namespace)


def module_from_src(line_or_lines):
    if '\n' in line_or_lines:
        src = f"from pyjs import js\n{textwrap.dedent(line_or_lines)}"
    else:
        src = textwrap.dedent(
            f"""\
        def main():
            {line_or_lines}
        main.__js__ = True
        main.__js_export__ = True
        """
        )
    return create_module(src)


class BaseTestCase(TestCase):

    def setUp(self):
        super().setUp()

    def analyze_line(self, line):
        module = analyze_module(module_from_src(line))
        type_info = write_types(module.node)
        if '\n' in line:
            return type_info
        else:
            return '\n'.join([l.strip() for l in type_info.splitlines()[1:]])

    def transpile_line(self, line):
        module = analyze_module(module_from_src(line))
        js_src = Transpiler(module.scope.search("main")).visit(module.node)
        if '\n' in line:
            return js_src
        else:
            return '\n'.join([l.strip() for l in js_src.splitlines()[1:]])

    def analyze_file(self, module_name, write=False, no_assert=False):
        module = analyze_module(import_module(f"tests.cases.{module_name}"))
        actual = write_types(module.node).splitlines()

        if no_assert:
            print(f"Transpiled {module_name}.run:")
            print("-"*WIDTH)
            for line in actual:
                print(line)
            print("-"*WIDTH)
            raise self.failureException(
                "no_assert=True, just printing the output."
            )

        js_file = TESTS_DIR / "cases" / f"{module_name}.types"
        expected = []
        if js_file.exists():
            with js_file.open() as js_src:
                expected = js_src.read().splitlines()

        if expected != actual:
            if write:
                with js_file.open('w') as js_src:
                    js_src.write("\n".join(actual)+"\n")
                    return
            raise self.failureException(
                diff_side_by_side("Type trees do not match:", expected, actual)
            )
        if expected == actual and write:
            raise self.failureException(
                "Assertion is correct but remember to remove write=True argument."
            )

    def transpile_file(self, module_name, write=False, no_assert=False):
        module = analyze_module(import_module(f"tests.cases.{module_name}"))
        actual = Transpiler(module.scope.search("main")).visit(module.node).splitlines()

        if no_assert:
            print(f"Transpiled {module_name}.run:")
            print("-"*WIDTH)
            for line in actual:
                print(line)
            print("-"*WIDTH)
            raise self.failureException(
                "no_assert=True, just printing the output."
            )

        js_file = TESTS_DIR / "cases" / f"{module_name}.js"
        expected = []
        if js_file.exists():
            with js_file.open() as js_src:
                expected = js_src.read().splitlines()

        if expected != actual:
            if write:
                with js_file.open('w') as js_src:
                    js_src.write("\n".join(actual)+"\n")
                    return
            raise self.failureException(
                diff_side_by_side("Type trees do not match:", expected, actual)
            )
        if expected == actual and write:
            raise self.failureException(
                "Assertion is correct but remember to remove write=True argument."
            )

    def a(self, py, expected):
        """ assert analysis of expression """
        actual = self.analyze_line(py)
        self.assertEqual(textwrap.dedent(expected).strip(), actual)

    def t(self, py, expected):
        """ assert transpilation of expression """
        actual = self.transpile_line(py)
        self.assertEqual(textwrap.dedent(expected).strip(), actual)

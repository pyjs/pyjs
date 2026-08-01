import os
import platform
import subprocess
import urllib.request
from _ast_unparse import Unparser as _Unparser
from _ast_unparse import _Precedence
from io import StringIO
from pathlib import Path

from .objects import Function


class SourceWriter(StringIO):
    def __init__(self, indent_char="  "):
        super().__init__()
        self.indent_char = indent_char
        self.indent_level = 0

    def indent(self, depth=1):
        self.indent_level += depth

    def dedent(self, depth=1):
        self.indent_level -= depth

    def write_space(self):
        self.write(self.indent_char * self.indent_level)

    def write_line(self, line):
        self.write_space()
        self.write(line)
        self.write("\n")


class TypeWriter(_Unparser):
    def visit_ModuleDef(self, node):
        self.visit_Module(node)

    def visit_Name(self, node):
        if node.id == "NoneType":
            self.write("None")
            return
        super().visit_Name(node)

    def visit_Attribute(self, node):
        self.set_precedence(_Precedence.ATOM, node.value)
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
    VERSION = "4.3.3"

    def __init__(self, tailwindcss="tailwindcss", cache_directory=None):
        self.tailwindcss = tailwindcss
        if cache_directory is None:
            cache_directory = self.default_cache_directory()
        self.cache_directory = Path(cache_directory)

    @staticmethod
    def default_cache_directory():
        cache_root = os.environ.get("XDG_CACHE_HOME")
        if cache_root is None:
            cache_root = Path.home() / ".cache"
        return Path(cache_root) / "pyjs" / "tailwindcss"

    @staticmethod
    def platform_asset():
        system = platform.system().lower()
        if system == "darwin":
            system = "macos"
        elif system == "windows":
            system = "windows"
        elif system != "linux":
            raise RuntimeError(f"Tailwind CSS is not available for {platform.system()}.")

        machine = platform.machine().lower()
        if system == "windows":
            architecture = "x64"
        elif machine in ("amd64", "x86_64"):
            architecture = "x64"
        elif machine in ("aarch64", "arm64"):
            architecture = "arm64"
        else:
            raise RuntimeError(f"Tailwind CSS is not available for {platform.machine()}.")

        variant = ""
        if system == "linux" and platform.libc_ver()[0].lower() == "musl":
            variant = "-musl"
        suffix = ".exe" if system == "windows" else ""
        return f"tailwindcss-{system}-{architecture}{variant}{suffix}"

    def install(self):
        asset = self.platform_asset()
        executable = self.cache_directory / self.VERSION / asset
        if executable.exists():
            return executable

        executable.parent.mkdir(parents=True, exist_ok=True)
        temporary = executable.with_suffix(f"{executable.suffix}.download")
        url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{self.VERSION}/{asset}"
        print(f"Downloading Tailwind CSS {self.VERSION} for {platform.system()}...")
        try:
            urllib.request.urlretrieve(url, temporary)
            temporary.chmod(0o755)
            temporary.replace(executable)
        finally:
            temporary.unlink(missing_ok=True)
        return executable

    def run(self, arguments, **kwargs):
        command = [self.tailwindcss, *arguments]
        try:
            return subprocess.run(command, check=True, **kwargs)
        except FileNotFoundError:
            if self.tailwindcss != "tailwindcss":
                raise
            self.tailwindcss = str(self.install())
            return subprocess.run([self.tailwindcss, *arguments], check=True, **kwargs)

    def get_css(self, classes: set):
        candidates = " ".join(sorted(classes)).replace("\\", "\\\\").replace('"', '\\"')
        source = f'@import "tailwindcss" source(none);\n@source inline("{candidates}");\n'
        try:
            process = self.run(
                ["-i", "-"],
                input=source.encode(),
                capture_output=True,
            )
            return process.stdout.decode()
        except subprocess.CalledProcessError as e:
            print("Tailwind CLI failed:", e.stderr.decode())

    def build(self, input_path, output_path, *, minify=False, cwd=None):
        input_path = Path(input_path).resolve()
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["-i", str(input_path), "-o", str(output_path)]
        if minify:
            arguments.append("--minify")
        self.run(arguments, cwd=cwd)
        return output_path

import os
import subprocess
from pathlib import Path


class TailwindBuildError(RuntimeError):
    def __init__(self, error: subprocess.CalledProcessError):
        self.command = tuple(error.cmd)
        self.exit_code = error.returncode
        self.stderr = (error.stderr or b"").decode(errors="replace").strip()
        message = f"Tailwind CSS compilation failed with exit code {self.exit_code}"
        if self.stderr:
            message += f": {self.stderr}"
        super().__init__(message)


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

    def install(self):
        from sdkmgr import Manager, SDKError

        try:
            return Manager(self.cache_directory, interactive=False).ensure(
                "tailwindcss", version=self.VERSION,
            ).executable()
        except SDKError as error:
            raise RuntimeError(str(error)) from error

    def run(self, arguments, **kwargs):
        if self.tailwindcss == "tailwindcss":
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
        except subprocess.CalledProcessError as error:
            raise TailwindBuildError(error) from error

    def build(self, input_path, output_path, *, minify=False, cwd=None):
        input_path = Path(input_path).resolve()
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["-i", str(input_path), "-o", str(output_path)]
        if minify:
            arguments.append("--minify")
        self.run(arguments, cwd=cwd)
        return output_path

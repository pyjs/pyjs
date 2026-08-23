from dataclasses import dataclass


def _format_size(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    if size < 1_000_000:
        return f"{size / 1000:.1f} kB"
    return f"{size / 1_000_000:.1f} MB"


@dataclass(frozen=True)
class BuildStats:
    duration: float
    javascript_files: int
    javascript_bytes: int
    css_bytes: int

    def __str__(self) -> str:
        return (
            f"Build completed in {self.duration:.2f}s "
            f"({self.javascript_files} JS files, "
            f"{_format_size(self.javascript_bytes)} JS, "
            f"{_format_size(self.css_bytes)} CSS)"
        )

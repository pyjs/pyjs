"""Native-compatible lexical POSIX paths."""


def _normalize(segments: tuple[str | PurePosixPath, ...]) -> str:
    combined = ""
    for value in segments:
        segment = str(value)
        if segment.startswith("/"):
            combined = segment
        elif not combined or combined == ".":
            combined = segment
        elif segment and segment != ".":
            if not combined.endswith("/"):
                combined += "/"
            combined += segment
    root = ""
    if combined.startswith("//") and not combined.startswith("///"):
        root = "//"
    elif combined.startswith("/"):
        root = "/"
    parts: list[str] = []
    for part in combined.split("/"):
        if part and part != ".":
            parts.append(part)
    body = "/".join(parts)
    if root:
        return root + body
    return body or "."


class PurePosixPath:
    _path: str

    def __init__(self, *pathsegments: str | PurePosixPath) -> None:
        self._path = _normalize(pathsegments)

    def __str__(self) -> str:
        return self._path

    def __repr__(self) -> str:
        return f"PurePosixPath({self._path!r})"

    def as_posix(self) -> str:
        return self._path

    def __fspath__(self) -> str:
        return self._path

    def __hash__(self) -> int:
        return hash(self._path)

    def __eq__(self, other: PurePosixPath) -> bool:
        return self._path == other._path

    def __lt__(self, other: PurePosixPath) -> bool:
        # Ordering uses split path text, not public parts: an absolute anchor
        # contributes an empty component, and '.' is not an empty tuple.
        return self._path.split("/") < other._path.split("/")

    def __le__(self, other: PurePosixPath) -> bool:
        return not other < self

    def __gt__(self, other: PurePosixPath) -> bool:
        return other < self

    def __ge__(self, other: PurePosixPath) -> bool:
        return not self < other

    @property
    def drive(self) -> str:
        return ""

    @property
    def root(self) -> str:
        if self._path.startswith("//"):
            return "//"
        if self._path.startswith("/"):
            return "/"
        return ""

    @property
    def anchor(self) -> str:
        return self.root

    @property
    def parts(self) -> tuple[str, ...]:
        if self._path == ".":
            return ()
        root = self.root
        remainder = self._path[len(root) :]
        values: list[str] = remainder.split("/") if remainder else []
        if root:
            values.insert(0, root)
        return tuple(values)

    @property
    def name(self) -> str:
        values = self.parts
        if not values or values[-1] == self.root:
            return ""
        return values[-1]

    @property
    def suffix(self) -> str:
        name = self.name.lstrip(".")
        index = name.rfind(".")
        if index < 0:
            return ""
        return name[index:]

    @property
    def suffixes(self) -> list[str]:
        values = self.name.lstrip(".").split(".")
        return ["." + value for value in values[1:]]

    @property
    def stem(self) -> str:
        suffix = self.suffix
        return self.name[: -len(suffix)] if suffix else self.name

    @property
    def parent(self) -> PurePosixPath:
        values = self.parts
        root = self.root
        if not values or values == (root,):
            return PurePosixPath(self._path)
        stop = len(values) - 1
        return PurePosixPath(*values[:stop])

    def is_absolute(self) -> bool:
        return bool(self.root)

    @property
    def parents(self) -> tuple[PurePosixPath, ...]:
        result: list[PurePosixPath] = []
        current = self
        while True:
            parent = current.parent
            if parent == current:
                return tuple(result)
            result.append(parent)
            current = parent

    def is_relative_to(self, other: str | PurePosixPath) -> bool:
        base = PurePosixPath(other)
        if self.root != base.root:
            return False
        left = self.parts
        right = base.parts
        if len(right) > len(left):
            return False
        for first, second in zip(left, right, strict=False):
            if first != second:
                return False
        return True

    def relative_to(
        self, other: str | PurePosixPath, *, walk_up: bool = False,
    ) -> PurePosixPath:
        base = PurePosixPath(other)
        current = base
        steps = 0
        while not self.is_relative_to(current):
            if not walk_up:
                raise ValueError(
                    f"{str(self)!r} is not in the subpath of {str(base)!r}"
                )
            if current.name == "..":
                raise ValueError(f"'..' segment in {str(base)!r} cannot be walked")
            parent = current.parent
            if parent == current:
                raise ValueError(
                    f"{str(self)!r} and {str(base)!r} have different anchors"
                )
            current = parent
            steps += 1
        parts = [".."] * steps
        parts.extend(self.parts[len(current.parts):])
        return PurePosixPath(*parts)

    def joinpath(self, *pathsegments: str | PurePosixPath) -> PurePosixPath:
        return PurePosixPath(self._path, *pathsegments)

    def __truediv__(self, key: str | PurePosixPath) -> PurePosixPath:
        return self.joinpath(key)

    def __rtruediv__(self, key: str | PurePosixPath) -> PurePosixPath:
        return PurePosixPath(key, self)

    def with_name(self, name: str) -> PurePosixPath:
        if not name or "/" in name or name == ".":
            raise ValueError(f"Invalid name {name!r}")
        if not self.name:
            raise ValueError(f"PurePosixPath({self._path!r}) has an empty name")
        return self.parent / name

    def with_stem(self, stem: str) -> PurePosixPath:
        if self.suffix and not stem:
            raise ValueError(f"{self!r} has a non-empty suffix")
        return self.with_name(stem + self.suffix)

    def with_suffix(self, suffix: str) -> PurePosixPath:
        stem = self.stem
        if not stem:
            raise ValueError(f"PurePosixPath({self._path!r}) has an empty name")
        if suffix and not suffix.startswith("."):
            raise ValueError(f"Invalid suffix {suffix!r}")
        return self.with_name(stem + suffix)


PurePath = PurePosixPath

__all__ = ["PurePath", "PurePosixPath"]

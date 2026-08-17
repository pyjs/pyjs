import importlib
import re
from dataclasses import dataclass
from importlib import metadata
from types import ModuleType


class LibraryCompatibilityError(TypeError):
    pass


@dataclass(frozen=True)
class LibraryClassInfo:
    annotations: dict[str, object]
    defaults: dict[str, object]
    required: tuple[str, ...]


@dataclass(frozen=True)
class LibraryImplementation:
    module: str
    minimum: tuple[int, int]
    maximum: tuple[int, int]
    imports: dict[tuple[str, str], str]

    @property
    def supported_range(self) -> str:
        minimum = ".".join(str(part) for part in self.minimum)
        maximum = ".".join(str(part) for part in self.maximum)
        return f">={minimum},<{maximum}"

    def supports(self, release: tuple[int, int]) -> bool:
        return self.minimum <= release < self.maximum

    def replacement_name(self, value: object) -> str | None:
        key = (getattr(value, "__module__", ""), getattr(value, "__name__", ""))
        return self.imports.get(key)


@dataclass(frozen=True)
class LibrarySpec:
    distribution: str
    implementations: tuple[LibraryImplementation, ...]

    def installed_version(self) -> tuple[str, tuple[int, int]]:
        installed = metadata.version(self.distribution)
        match = re.match(r"^(\d+)(?:\.(\d+))?", installed)
        if match is None:
            raise LibraryCompatibilityError(
                f"Cannot determine the installed {self.distribution} version "
                f"from {installed!r}."
            )
        return installed, (int(match.group(1)), int(match.group(2) or 0))

    def implementation_for(self, value: object) -> LibraryImplementation | None:
        candidates = [
            implementation
            for implementation in self.implementations
            if implementation.replacement_name(value) is not None
        ]
        if not candidates:
            return None

        installed, release = self.installed_version()
        for implementation in candidates:
            if implementation.supports(release):
                return implementation

        supported = ", ".join(
            implementation.supported_range for implementation in candidates
        )
        raise LibraryCompatibilityError(
            f"PyJS supports {self.distribution} {supported}, "
            f"but found {self.distribution}=={installed}."
        )

    def replacement(self, value: object) -> object | None:
        implementation = self.implementation_for(value)
        if implementation is None:
            return None
        replacement_name = implementation.replacement_name(value)
        module = importlib.import_module(implementation.module)
        return getattr(module, replacement_name)

    def class_info(self, cls: type) -> LibraryClassInfo | None:
        for base in cls.__mro__[1:]:
            implementation = self.implementation_for(base)
            if implementation is not None:
                module = importlib.import_module(implementation.module)
                annotations, defaults, required = module._class_info(cls)
                return LibraryClassInfo(annotations, defaults, required)
        return None


LIBRARIES = (
    LibrarySpec(
        distribution="pydantic",
        implementations=(
            LibraryImplementation(
                module="pyjs.lib.pydantic.v2",
                minimum=(2, 0),
                maximum=(3, 0),
                imports={
                    ("pydantic.main", "BaseModel"): "BaseModel",
                },
            ),
        ),
    ),
)

STDLIB_IMPORTS = {
    ("datetime", "date"): ("pyjs.javascript", "Date"),
    ("dataclasses", "asdict"): ("pyjs.stdlib.dataclasses", "asdict"),
    ("dataclasses", "replace"): ("pyjs.stdlib.dataclasses", "replace"),
    ("math", None): ("pyjs.stdlib.math", None),
    ("typing", None): ("pyjs.stdlib.typing", None),
    ("typing", "cast"): ("pyjs.stdlib.typing", "cast"),
    **{
        ("math", name): ("pyjs.stdlib.math", name)
        for name in (
            "asin",
            "atan",
            "atan2",
            "ceil",
            "cos",
            "dist",
            "hypot",
            "inf",
            "isclose",
            "isfinite",
            "pi",
            "radians",
            "sin",
            "sqrt",
            "tan",
            "tau",
        )
    },
}


def stdlib_import_target(
    module: str,
    name: str | None,
) -> tuple[str, str | None] | None:
    return STDLIB_IMPORTS.get((module, name))


def resolve_stdlib_import(module: str, name: str | None) -> object | None:
    replacement = stdlib_import_target(module, name)
    if replacement is None:
        return None
    module_name, replacement_name = replacement
    replacement_module = importlib.import_module(module_name)
    if replacement_name is None:
        return replacement_module
    return getattr(replacement_module, replacement_name)


def resolve_library_import(value: object) -> object:
    if isinstance(value, ModuleType):
        stdlib = resolve_stdlib_import(value.__name__, None)
    else:
        stdlib = resolve_stdlib_import(
            getattr(value, "__module__", ""),
            getattr(value, "__name__", ""),
        )
    if stdlib is not None:
        return stdlib
    for library in LIBRARIES:
        replacement = library.replacement(value)
        if replacement is not None:
            return replacement
    return value


def library_class_info(cls: type) -> LibraryClassInfo | None:
    for library in LIBRARIES:
        info = library.class_info(cls)
        if info is not None:
            return info
    return None

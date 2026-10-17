from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiTypePart:
    text: str
    target: str = ""


@dataclass(frozen=True)
class ApiType:
    parts: tuple[ApiTypePart, ...]

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts)


@dataclass(frozen=True)
class ApiParameter:
    name: str
    kind: str
    annotation: ApiType | None = None
    default: str | None = None


@dataclass(frozen=True)
class ApiTypeParameter:
    name: str
    kind: str
    bound: ApiType | None = None
    default: ApiType | None = None


@dataclass(frozen=True)
class ApiSignature:
    parameters: tuple[ApiParameter, ...] = ()
    returns: ApiType | None = None
    type_parameters: tuple[ApiTypeParameter, ...] = ()
    asynchronous: bool = False


@dataclass(frozen=True)
class ApiDocItem:
    name: str
    description: str
    annotation: ApiType | None = None


@dataclass(frozen=True)
class ApiDocSection:
    kind: str
    title: str = ""
    text: str = ""
    items: tuple[ApiDocItem, ...] = ()


@dataclass(frozen=True)
class ApiObject:
    name: str
    path: str
    canonical_path: str
    kind: str
    source_path: Path | None
    line: int
    end_line: int
    signature: ApiSignature | None = None
    annotation: ApiType | None = None
    value: str | None = None
    bases: tuple[ApiType, ...] = ()
    doc: tuple[ApiDocSection, ...] = ()
    members: tuple[ApiObject, ...] = ()


@dataclass(frozen=True)
class ApiModule:
    name: str
    source_path: Path
    line: int
    end_line: int
    doc: tuple[ApiDocSection, ...]
    members: tuple[ApiObject, ...]


@dataclass(frozen=True)
class ApiReference:
    modules: tuple[ApiModule, ...]


@dataclass(frozen=True)
class ApiCoverage:
    modules: int
    symbols: int
    documented: int
    undocumented: tuple[str, ...]

from collections.abc import Callable
from dataclasses import dataclass

EntryPoint = Callable[..., object]
SectionEntryPoint = Callable[[object], object]


@dataclass(frozen=True, eq=False)
class ApplicationPage:
    name: str
    entry_point: EntryPoint

    def __call__(self, *args, **kwargs):
        return ApplicationContent(self, self.entry_point(*args, **kwargs))


@dataclass(frozen=True, eq=False)
class ApplicationSection:
    name: str
    entry_point: SectionEntryPoint
    children: tuple[ApplicationSection | ApplicationPage, ...] = ()


@dataclass(frozen=True)
class ApplicationContent:
    page: ApplicationPage
    content: object


type ApplicationNode = ApplicationSection | ApplicationPage

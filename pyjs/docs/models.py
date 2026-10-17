from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Heading:
    id: str
    title: str
    level: int


@dataclass(frozen=True)
class SearchEntry:
    title: str
    section: str
    fragment: str
    text: str


@dataclass
class Page:
    source_path: Path
    relative_path: Path
    output_path: Path
    route: str
    title: str
    description: str
    order: float
    hidden: bool
    html: str
    headings: list[Heading]
    search_entries: tuple[SearchEntry, ...] = ()
    previous: Page | None = None
    next: Page | None = None


@dataclass
class NavNode:
    title: str
    order: float = 1000
    page: Page | None = None
    children: list[NavNode] = field(default_factory=list)

    def sort(self):
        self.children.sort(key=lambda node: (node.order, node.title.lower()))
        for child in self.children:
            child.sort()

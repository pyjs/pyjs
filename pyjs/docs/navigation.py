from pathlib import Path

from .models import NavNode, Page


def humanize(value: str) -> str:
    words = value.replace("-", " ").replace("_", " ").strip().split()
    names = {"api": "API", "js": "JS", "pyjs": "PyJS"}
    return " ".join(names.get(word.lower(), word.title()) for word in words)


def build_navigation(pages: list[Page]) -> NavNode:
    root = NavNode("")
    directories: dict[tuple[str, ...], NavNode] = {(): root}
    for page in pages:
        if page.hidden:
            continue
        parts = page.relative_path.with_suffix("").parts
        directory_parts = parts[:-1]
        parent = root
        for depth in range(1, len(directory_parts) + 1):
            key = directory_parts[:depth]
            if key not in directories:
                directories[key] = NavNode(humanize(key[-1]))
                parent.children.append(directories[key])
            parent = directories[key]
        if parts[-1] == "index":
            if parent is root:
                root.children.append(NavNode(page.title, page.order, page))
                continue
            parent.title = page.title
            parent.page = page
            parent.order = page.order
        else:
            parent.children.append(NavNode(page.title, page.order, page))
            if parent.page is None:
                parent.order = min(parent.order, page.order)
    root.sort()
    return root


def navigation_pages(root: NavNode) -> list[Page]:
    pages = []

    def visit(node: NavNode):
        if node.page is not None:
            pages.append(node.page)
        for child in node.children:
            visit(child)

    for child in root.children:
        visit(child)
    return pages


def route_for(relative_path: Path) -> str:
    path = relative_path.with_suffix("")
    parts = path.parts
    if parts == ("index",):
        return "/"
    if parts[-1] == "index":
        parts = parts[:-1]
    return "/" + "/".join(parts) + "/"

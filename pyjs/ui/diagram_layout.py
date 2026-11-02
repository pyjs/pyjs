"""Explicit, deterministic layout for directed trees and forests."""
from math import isfinite

from pyjs import js
from pyjs.ui.diagram import Diagram, DiagramIndex, Node, moved, validate


@js
def tree_layout(graph: Diagram, horizontal: bool = False, gap: float = 40.0,
                level_gap: float = 64.0) -> Diagram:
    """Arrange variable-sized trees without changing IDs or connections.

    Sibling order follows node order. Cycles and multiple parents are rejected,
    never silently dropped. Call explicitly: manual positions are otherwise
    authoritative. The caller commits the result as one undoable operation.
    """
    validate(graph)
    if not isfinite(gap) or not isfinite(level_gap) or gap < 0.0 or level_gap < 0.0:
        raise ValueError("Layout gaps must be finite and nonnegative")
    if not graph.nodes:
        return graph
    index = DiagramIndex(graph)
    children: dict[str, list[str]] = {}
    for node in graph.nodes:
        children[node.id] = []
    parents: dict[str, str] = {}
    for edge in graph.edges:
        if not edge.directed:
            raise ValueError("Tree layout requires directed edges")
        if edge.target in parents:
            raise ValueError("Tree layout requires at most one parent per node")
        parents[edge.target] = edge.source
    roots: list[str] = []
    for node in graph.nodes:
        parent = parents.get(node.id)
        if parent is None:
            roots.append(node.id)
        else:
            children[parent].append(node.id)
    order = list(roots)
    depths: dict[str, int] = {}
    for root in roots:
        depths[root] = 0
    level_sizes: list[float] = []
    position = 0
    while position < len(order):
        id = order[position]
        depth = depths[id]
        node = index.nodes[id]
        size = node.width if horizontal else node.height
        if depth == len(level_sizes):
            level_sizes.append(size)
        else:
            level_sizes[depth] = max(level_sizes[depth], size)
        for child in children[id]:
            depths[child] = depth + 1
            order.append(child)
        position += 1
    if len(order) != len(graph.nodes):
        raise ValueError("Tree layout does not accept cycles")
    spans: dict[str, float] = {}
    for i in range(len(order) - 1, -1, -1):
        id = order[i]
        node = index.nodes[id]
        child_span = 0.0
        for child in children[id]:
            child_span += spans[child] + gap
        if children[id]:
            child_span -= gap
        spans[id] = max(node.height if horizontal else node.width, child_span)
    levels: list[float] = []
    offset = 0.0
    for size in level_sizes:
        levels.append(offset)
        offset += size + level_gap
    offsets: dict[str, float] = {}
    offset = 0.0
    for root in roots:
        offsets[root] = offset
        offset += spans[root] + gap
    placed: dict[str, Node] = {}
    for id in order:
        node = index.nodes[id]
        cross = offsets[id] + (spans[id] - (node.height if horizontal else node.width)) / 2.0
        along = levels[depths[id]]
        x, y = (along, cross) if horizontal else (cross, along)
        if not isfinite(x + node.width) or not isfinite(y + node.height):
            raise ValueError("Layout exceeds finite coordinate range")
        placed[id] = moved(node, x, y)
        total = gap * max(0, len(children[id]) - 1)
        for child in children[id]:
            total += spans[child]
        child_offset = offsets[id] + (spans[id] - total) / 2.0
        for child in children[id]:
            offsets[child] = child_offset
            child_offset += spans[child] + gap
    result: list[Node] = []
    changed = False
    for node in graph.nodes:
        next_node = placed[node.id]
        if next_node.x != node.x or next_node.y != node.y:
            changed = True
        result.append(next_node)
    return Diagram(nodes=result, edges=graph.edges, ports=graph.ports) if changed else graph

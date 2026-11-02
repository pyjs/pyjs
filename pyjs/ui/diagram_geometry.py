"""Drawing geometry shared by static documentation and interactive diagrams."""
from dataclasses import dataclass
from math import sqrt

from pyjs import js


@js
@dataclass(frozen=True, repr=False)
class Point:
    x: float
    y: float


@js
def boundary_point(center: Point, width: float, height: float, toward: Point,
                   diamond: bool = False) -> Point:
    """Intersect a ray from the center with a rectangle or diamond boundary.

    Width and height must be positive. A coincident target returns the center.
    """
    dx, dy = toward.x - center.x, toward.y - center.y
    horizontal, vertical = abs(dx) / (width / 2.0), abs(dy) / (height / 2.0)
    divisor = horizontal + vertical if diamond else max(horizontal, vertical)
    if divisor == 0.0:
        return center
    return Point(center.x + dx / divisor, center.y + dy / divisor)


@js
def arrow_points(path: list[Point], size: float = 9.0,
                 half_width: float = 4.5) -> list[Point]:
    """An open arrowhead at the last nonzero segment; empty for a point path."""
    if len(path) < 2:
        return []
    tip = path[-1]
    for i in range(len(path) - 2, -1, -1):
        previous = path[i]
        dx, dy = tip.x - previous.x, tip.y - previous.y
        length = sqrt(dx * dx + dy * dy)
        if length > 0.0:
            dx, dy = dx / length, dy / length
            return [Point(tip.x - size * dx + half_width * dy,
                          tip.y - size * dy - half_width * dx), tip,
                    Point(tip.x - size * dx - half_width * dy,
                          tip.y - size * dy + half_width * dx)]
    return []

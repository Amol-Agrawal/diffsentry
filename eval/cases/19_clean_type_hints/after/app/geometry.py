import math

Point = tuple[float, float]


def distance(a: Point, b: Point) -> float:
    """Euclidean distance between two points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def midpoint(a: Point, b: Point) -> Point:
    """Point halfway between a and b."""
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

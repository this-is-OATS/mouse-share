"""Screen-edge math shared by the server. Pure Python so it can be unit tested."""

from dataclasses import dataclass

SIDES = ("left", "right", "top", "bottom")
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self):
        return self.x + self.w - 1

    @property
    def y2(self):
        return self.y + self.h - 1

    def as_list(self):
        return [self.x, self.y, self.w, self.h]

    @classmethod
    def from_list(cls, values):
        x, y, w, h = (int(v) for v in values)
        return cls(x, y, w, h)


def _clamp(value, low, high):
    return max(low, min(high, value))


def at_edge(rect, side, x, y):
    """True when (x, y) is touching the given edge of rect."""
    if side == "left":
        return x <= rect.x
    if side == "right":
        return x >= rect.x2
    if side == "top":
        return y <= rect.y
    return y >= rect.y2


def edge_ratio(rect, side, x, y):
    """Position along an edge as 0.0-1.0, so screens of different sizes line up."""
    if side in ("left", "right"):
        return _clamp((y - rect.y) / max(1, rect.h - 1), 0.0, 1.0)
    return _clamp((x - rect.x) / max(1, rect.w - 1), 0.0, 1.0)


def point_on_edge(rect, side, ratio, inset=0):
    """The point `ratio` of the way along an edge, moved `inset` pixels inward."""
    ratio = _clamp(ratio, 0.0, 1.0)
    along_x = rect.x + round(ratio * (rect.w - 1))
    along_y = rect.y + round(ratio * (rect.h - 1))
    if side == "left":
        return rect.x + inset, along_y
    if side == "right":
        return rect.x2 - inset, along_y
    if side == "top":
        return along_x, rect.y + inset
    return along_x, rect.y2 - inset


class VirtualCursor:
    """The cursor on the client screen, driven by relative motion from the server.

    `return_side` is the client edge that leads back to the server screen.
    """

    def __init__(self, rect, return_side, ratio):
        self.rect = rect
        self.return_side = return_side
        self.x, self.y = point_on_edge(rect, return_side, ratio, inset=1)

    def move(self, dx, dy):
        """Apply a delta. Returns True if the cursor crossed back to the server."""
        r = self.rect
        nx, ny = self.x + dx, self.y + dy
        side = self.return_side
        exited = (
            (side == "left" and nx < r.x)
            or (side == "right" and nx > r.x2)
            or (side == "top" and ny < r.y)
            or (side == "bottom" and ny > r.y2)
        )
        self.x = _clamp(nx, r.x, r.x2)
        self.y = _clamp(ny, r.y, r.y2)
        return exited

    def ratio(self):
        return edge_ratio(self.rect, self.return_side, self.x, self.y)

from dataclasses import dataclass

from pyjs import js


@js
@dataclass(frozen=True, repr=False)
class InteractionSample:
    phase: str
    x: float = 0
    y: float = 0
    pointer_id: int = 0
    elapsed_ms: float = 0
    delta_x: float = 0
    delta_y: float = 0


@js
@dataclass(frozen=True, repr=False)
class InteractionMeasurement:
    item_id: str
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    clipped: bool = False


@js
@dataclass(frozen=True, repr=False)
class InteractionViewport:
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    scroll_x: float = 0
    scroll_y: float = 0
    content_width: float = 0
    content_height: float = 0


@js
@dataclass(frozen=True, repr=False)
class InteractionProjection:
    item_id: str
    translate_x: float = 0
    translate_y: float = 0
    visible: bool = True
    clip_x: float = 0
    clip_y: float = 0
    clip_width: float = 0
    clip_height: float = 0


@js
class InteractionSampler:
    """Convert platform timestamps and coordinates into portable samples."""

    def __init__(self, pointer_id: int = 1):
        self.pointer_id = pointer_id
        self.started_at = 0.0
        self.last_elapsed = 0.0
        self.x = 0.0
        self.y = 0.0
        self.active = False

    def begin(self, x: float, y: float, timestamp_ms: float) -> InteractionSample:
        if self.active:
            raise ValueError("The interaction pointer is already active.")
        self.started_at = timestamp_ms
        self.last_elapsed = 0.0
        self.x = x
        self.y = y
        self.active = True
        return InteractionSample("down", x, y, self.pointer_id)

    def sample(
        self,
        phase: str,
        x: float,
        y: float,
        timestamp_ms: float,
    ) -> InteractionSample:
        if not self.active:
            raise ValueError("The interaction pointer is not active.")
        if phase == "down":
            raise ValueError("Use begin() to start an interaction pointer.")
        elapsed_ms = timestamp_ms - self.started_at
        if elapsed_ms < self.last_elapsed:
            elapsed_ms = self.last_elapsed
        result = InteractionSample(
            phase,
            x,
            y,
            self.pointer_id,
            elapsed_ms,
            x - self.x,
            y - self.y,
        )
        self.last_elapsed = elapsed_ms
        self.x = x
        self.y = y
        if phase == "up" or phase == "cancel":
            self.active = False
        return result


__all__ = [
    "InteractionMeasurement",
    "InteractionProjection",
    "InteractionSample",
    "InteractionSampler",
    "InteractionViewport",
]

from pyjs import js
from pyjs.ui.interaction import InteractionSample


@js
class InteractionClock:
    """A manually advanced clock for deterministic interaction tests."""

    def __init__(self, elapsed_ms: float = 0):
        self.elapsed_ms = max(0.0, elapsed_ms)
        self.frozen = False
        self.active_phases: set[str] = set()

    def now(self) -> float:
        return self.elapsed_ms

    def freeze(self) -> None:
        self.frozen = True

    def resume(self) -> None:
        self.frozen = False

    def tick(self, duration_ms: float) -> float:
        if not self.frozen:
            self.advance(duration_ms)
        return self.elapsed_ms

    def advance(self, duration_ms: float) -> float:
        self.elapsed_ms += max(0.0, duration_ms)
        return self.elapsed_ms

    def seek(self, elapsed_ms: float) -> float:
        self.elapsed_ms = max(0.0, elapsed_ms)
        return self.elapsed_ms

    def begin_phase(self, name: str) -> None:
        self.active_phases.add(name)

    def settle_phase(self, name: str) -> None:
        self.active_phases.discard(name)

    def is_settled(self, name: str) -> bool:
        return name not in self.active_phases

    def require_settled(self, name: str) -> None:
        if not self.is_settled(name):
            raise ValueError("Interaction phase '" + name + "' has not settled.")


@js
class GesturePoint:
    def __init__(self, x: float, y: float, duration_ms: float = 0):
        self.x = x
        self.y = y
        self.duration_ms = max(0.0, duration_ms)


@js
class GestureScript:
    """A target-neutral sequence of timed pointer samples."""

    def __init__(self, pointer_id: int = 1):
        self.pointer_id = pointer_id
        self.clock = InteractionClock()
        self.samples: list[InteractionSample] = []
        self.x = 0.0
        self.y = 0.0
        self.active = False

    def _append(self, phase: str, x: float, y: float) -> None:
        delta_x = 0.0
        delta_y = 0.0
        if self.active:
            delta_x = x - self.x
            delta_y = y - self.y
        self.x = x
        self.y = y
        self.samples.append(
            InteractionSample(
                phase,
                x,
                y,
                self.pointer_id,
                self.clock.now(),
                delta_x,
                delta_y,
            )
        )

    def press(self, x: float, y: float) -> GestureScript:
        if self.active:
            raise ValueError("The gesture pointer is already pressed.")
        self._append("down", x, y)
        self.active = True
        return self

    def hold(self, duration_ms: float) -> GestureScript:
        self._require_active()
        self.clock.advance(duration_ms)
        self._append("hold", self.x, self.y)
        return self

    def move_to(
        self,
        x: float,
        y: float,
        duration_ms: float = 0,
    ) -> GestureScript:
        self._require_active()
        self.clock.advance(duration_ms)
        self._append("move", x, y)
        return self

    def path(self, points: list[GesturePoint]) -> GestureScript:
        for point in points:
            self.move_to(point.x, point.y, point.duration_ms)
        return self

    def release(self, duration_ms: float = 0) -> GestureScript:
        self._require_active()
        self.clock.advance(duration_ms)
        self._append("up", self.x, self.y)
        self.active = False
        return self

    def cancel(self, duration_ms: float = 0) -> GestureScript:
        self._require_active()
        self.clock.advance(duration_ms)
        self._append("cancel", self.x, self.y)
        self.active = False
        return self

    def long_press(self, x: float, y: float, duration_ms: float) -> GestureScript:
        return self.press(x, y).hold(duration_ms)

    def _require_active(self) -> None:
        if not self.active:
            raise ValueError("The gesture pointer is not pressed.")


@js
def replay_gesture(
    script: GestureScript,
    receiver: callable,
    clock: InteractionClock | None = None,
) -> None:
    start = 0.0
    if clock is not None:
        start = clock.now()
    for sample in script.samples:
        if clock is not None:
            clock.seek(start + sample.elapsed_ms)
        receiver(sample)


__all__ = [
    "GesturePoint",
    "GestureScript",
    "InteractionClock",
    "replay_gesture",
]

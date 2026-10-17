from pyjs import js
from pyjs.testing.interaction.gesture import (
    GesturePoint,
    GestureScript,
    InteractionClock,
    replay_gesture,
)
from pyjs.testing.interaction.reorder import (
    replay_reorder_gesture,
)
from pyjs.ui.interaction import InteractionSample, InteractionSampler
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderItem,
    ReorderRow,
    ReorderSession,
)


@js
class SampleReceiver:
    def __init__(self, clock: InteractionClock):
        self.clock = clock
        self.phases: list[str] = []
        self.elapsed: list[float] = []
        self.last: InteractionSample | None = None

    def receive(self, sample: InteractionSample) -> None:
        self.phases.append(sample.phase)
        self.elapsed.append(self.clock.now())
        self.last = sample


@js
def assert_gesture_scenarios():
    clock = InteractionClock(10)
    clock.freeze()
    assert clock.tick(20) == 10
    assert clock.advance(5) == 15
    clock.resume()
    assert clock.tick(5) == 20

    clock.begin_phase("layout")
    assert not clock.is_settled("layout")
    clock.settle_phase("layout")
    assert clock.is_settled("layout")
    clock.require_settled("layout")

    script = GestureScript(pointer_id=4)
    script.long_press(10, 20, 500)
    script.path(
        [
            GesturePoint(14, 26, 50),
            GesturePoint(30, 40, 25),
        ]
    )
    script.release(10)

    assert len(script.samples) == 5
    assert script.samples[0].phase == "down"
    assert script.samples[1].phase == "hold"
    assert script.samples[1].elapsed_ms == 500
    assert script.samples[2].delta_x == 4
    assert script.samples[2].delta_y == 6
    assert script.samples[3].elapsed_ms == 575
    assert script.samples[4].phase == "up"
    assert script.samples[4].elapsed_ms == 585
    assert script.samples[4].pointer_id == 4

    line = GestureScript().press(0, 0).line_to(12, 6, 30, steps=3).release()
    assert [(sample.x, sample.y) for sample in line.samples[1:4]] == [
        (4, 2),
        (8, 4),
        (12, 6),
    ]
    assert [sample.elapsed_ms for sample in line.samples] == [0, 10, 20, 30, 30]
    try:
        GestureScript().press(0, 0).line_to(1, 1, steps=0)
        raise AssertionError("Expected an invalid gesture step count")
    except ValueError:
        pass

    replay_clock = InteractionClock(100)
    receiver = SampleReceiver(replay_clock)
    replay_gesture(script, receiver.receive, replay_clock)
    assert receiver.phases == ["down", "hold", "move", "move", "up"]
    assert receiver.elapsed == [100, 600, 650, 675, 685]
    last = receiver.last
    if last is None:
        raise ValueError("Expected a replayed sample")
    assert last.x == 30
    assert last.y == 40

    sampler = InteractionSampler(pointer_id=7)
    down = sampler.begin(10, 20, 1_000)
    move = sampler.sample("move", 14, 26, 1_016)
    held = sampler.sample("hold", 14, 26, 1_010)
    up = sampler.sample("up", 14, 30, 1_032)
    assert down.phase == "down"
    assert down.elapsed_ms == 0
    assert move.delta_x == 4
    assert move.delta_y == 6
    assert held.elapsed_ms == 16
    assert up.elapsed_ms == 32
    assert up.delta_y == 4
    assert up.pointer_id == 7
    assert not sampler.active

    session = HierarchicalReorder(max_depth=2, indent_step=36).begin(
        [
            ReorderItem("source", 0),
            ReorderItem("short", 0),
            ReorderItem("tall", 0),
            ReorderItem("last", 0),
        ],
        0,
    )
    assert isinstance(session, ReorderSession)
    decisions = replay_reorder_gesture(
        session,
        [
            ReorderRow("short", 0, 40),
            ReorderRow("tall", 40, 160),
            ReorderRow("last", 200, 64),
        ],
        GestureScript()
        .long_press(0, 20, 500)
        .move_to(0, 121, 16)
        .move_to(36, 400, 16)
        .release(),
    )
    assert len(decisions) == 3
    assert decisions[0].insertion_index == 0
    assert decisions[1].insertion_index == 2
    assert decisions[2].insertion_index == 3
    assert decisions[2].target_depth == 1

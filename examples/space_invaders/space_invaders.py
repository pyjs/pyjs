from pyjs import js
from pyjs.web.dom import document
from pyjs.web.domx import canvas, ref, tag, tw
from pyjs.web.events import KeyboardEvent
from pyjs.web.html import HTMLCanvasElement
from pyjs.web.timers import requestAnimationFrame
from pyjs.web.ui import Widget
from pyjs.web.webgpu import (
    Float32Array,
    GPUBuffer,
    GPUBufferDescriptor,
    GPUBufferUsage,
    GPUCanvasConfiguration,
    GPUCanvasContext,
    GPUColor,
    GPUColorTargetState,
    GPUDepthStencilState,
    GPUDevice,
    GPUExtent3D,
    GPUFragmentState,
    GPUPrimitiveState,
    GPURenderPassColorAttachment,
    GPURenderPassDepthStencilAttachment,
    GPURenderPassDescriptor,
    GPURenderPipeline,
    GPURenderPipelineDescriptor,
    GPUShaderModuleDescriptor,
    GPUTexture,
    GPUTextureDescriptor,
    GPUTextureUsage,
    GPUVertexAttribute,
    GPUVertexBufferLayout,
    GPUVertexState,
    get_webgpu_context,
    navigator,
)


@js
class Invader:
    def __init__(self, x: float, y: float, column: int):
        self.x = x
        self.y = y
        self.width = 7.0
        self.height = 6.0
        self.column = column
        self.active = True


@js
class Projectile:
    def __init__(self, x: float, y: float, velocity: float, owner: str):
        self.x = x
        self.y = y
        self.width = 0.8
        self.height = 3.0
        self.velocity = velocity
        self.owner = owner
        self.active = True


@js
def overlaps(
    left_x: float,
    left_y: float,
    left_width: float,
    left_height: float,
    right_x: float,
    right_y: float,
    right_width: float,
    right_height: float,
) -> bool:
    return (
        left_x < right_x + right_width
        and left_x + left_width > right_x
        and left_y < right_y + right_height
        and left_y + left_height > right_y
    )


@js
class GameState:
    def __init__(self):
        self.width = 100.0
        self.height = 75.0
        self.player_width = 9.0
        self.player_height = 4.0
        self.player_y = 67.0
        self.player_x = 45.5
        self.player_direction = 1.0
        self.player_speed = 42.0
        self.moving_left = False
        self.moving_right = False
        self.invaders: list[Invader] = []
        self.projectiles: list[Projectile] = []
        self.formation_direction = 1.0
        self.formation_speed = 7.0
        self.enemy_fire_elapsed = 0.0
        self.enemy_fire_interval = 1.25
        self.enemy_shot_column = 0
        self.score = 0
        self.lives = 3
        self.wave = 1
        self.status = "playing"
        self.spawn_wave()

    def spawn_wave(self):
        self.invaders = []
        row = 0
        while row < 3:
            column = 0
            while column < 8:
                self.invaders.append(
                    Invader(
                        12.0 + float(column) * 9.5,
                        9.0 + float(row) * 8.0,
                        column,
                    )
                )
                column = column + 1
            row = row + 1
        self.formation_direction = 1.0
        self.enemy_fire_elapsed = 0.0

    def restart(self):
        self.player_x = 45.5
        self.player_direction = 1.0
        self.moving_left = False
        self.moving_right = False
        self.projectiles = []
        self.formation_speed = 7.0
        self.enemy_fire_interval = 1.25
        self.enemy_shot_column = 0
        self.score = 0
        self.lives = 3
        self.wave = 1
        self.status = "playing"
        self.spawn_wave()

    def active_invader_count(self) -> int:
        count = 0
        for invader in self.invaders:
            if invader.active:
                count = count + 1
        return count

    def active_projectile_count(self, owner: str) -> int:
        count = 0
        for projectile in self.projectiles:
            if projectile.active and projectile.owner == owner:
                count = count + 1
        return count

    def set_moving_left(self, active: bool):
        self.moving_left = active

    def set_moving_right(self, active: bool):
        self.moving_right = active

    def fire(self):
        if self.status != "playing" or self.active_projectile_count("player") > 0:
            return
        self.projectiles.append(
            Projectile(
                self.player_x + self.player_width / 2.0 - 0.4,
                self.player_y - 3.0,
                -48.0,
                "player",
            )
        )

    def fire_enemy(self):
        if self.status != "playing":
            return
        wanted_column = self.enemy_shot_column % 8
        self.enemy_shot_column = self.enemy_shot_column + 3
        shooter_x = 0.0
        shooter_y = 0.0
        shooter_width = 0.0
        found_shooter = False
        for invader in self.invaders:
            if invader.active and invader.column == wanted_column:
                if not found_shooter or invader.y > shooter_y:
                    shooter_x = invader.x
                    shooter_y = invader.y
                    shooter_width = invader.width
                    found_shooter = True
        if not found_shooter:
            return
        self.projectiles.append(
            Projectile(
                shooter_x + shooter_width / 2.0 - 0.4,
                shooter_y + 6.0,
                22.0 + float(self.wave),
                "enemy",
            )
        )

    def move_player(self, elapsed: float):
        direction = 0.0
        if self.moving_left:
            direction = direction - 1.0
        if self.moving_right:
            direction = direction + 1.0
        if direction != 0.0:
            self.player_direction = direction
        self.player_x = self.player_x + direction * self.player_speed * elapsed
        if self.player_x < 2.0:
            self.player_x = 2.0
        right_limit = self.width - self.player_width - 2.0
        if self.player_x > right_limit:
            self.player_x = right_limit

    def move_invaders(self, elapsed: float):
        distance = self.formation_direction * self.formation_speed * elapsed
        at_edge = False
        for invader in self.invaders:
            if invader.active:
                next_x = invader.x + distance
                if next_x < 3.0 or next_x + invader.width > self.width - 3.0:
                    at_edge = True
        if at_edge:
            self.formation_direction = 0.0 - self.formation_direction
            for invader in self.invaders:
                if invader.active:
                    invader.y = invader.y + 2.5
                    if invader.y + invader.height >= self.player_y:
                        self.status = "game-over"
        else:
            for invader in self.invaders:
                if invader.active:
                    invader.x = invader.x + distance

    def hit_player(self):
        self.lives = self.lives - 1
        self.player_x = 45.5
        for projectile in self.projectiles:
            projectile.active = False
        if self.lives <= 0:
            self.status = "game-over"

    def move_projectiles(self, elapsed: float):
        for projectile in self.projectiles:
            if projectile.active:
                projectile.y = projectile.y + projectile.velocity * elapsed
                outside_playfield = (
                    projectile.y + projectile.height < 0.0 or projectile.y > self.height
                )
                if outside_playfield:
                    projectile.active = False
                elif projectile.owner == "player":
                    for invader in self.invaders:
                        if invader.active and overlaps(
                            projectile.x,
                            projectile.y,
                            projectile.width,
                            projectile.height,
                            invader.x,
                            invader.y,
                            invader.width,
                            invader.height,
                        ):
                            projectile.active = False
                            invader.active = False
                            self.score = self.score + 100
                            break
                elif overlaps(
                    projectile.x,
                    projectile.y,
                    projectile.width,
                    projectile.height,
                    self.player_x,
                    self.player_y,
                    self.player_width,
                    self.player_height,
                ):
                    projectile.active = False
                    self.hit_player()

        active_projectiles: list[Projectile] = []
        for projectile in self.projectiles:
            if projectile.active:
                active_projectiles.append(projectile)
        self.projectiles = active_projectiles

    def step(self, elapsed: float):
        if self.status != "playing":
            return
        self.move_player(elapsed)
        self.move_invaders(elapsed)
        self.move_projectiles(elapsed)
        if self.status != "playing":
            return

        self.enemy_fire_elapsed = self.enemy_fire_elapsed + elapsed
        if self.enemy_fire_elapsed >= self.enemy_fire_interval:
            self.enemy_fire_elapsed = self.enemy_fire_elapsed - self.enemy_fire_interval
            self.fire_enemy()

        if self.active_invader_count() == 0:
            self.wave = self.wave + 1
            self.formation_speed = self.formation_speed + 1.5
            if self.enemy_fire_interval > 0.45:
                self.enemy_fire_interval = self.enemy_fire_interval - 0.1
            self.projectiles = []
            self.spawn_wave()


@js
def append_vertex(
    values: list[float],
    x: float,
    y: float,
    depth: float,
    red: float,
    green: float,
    blue: float,
):
    values.extend([x / 50.0 - 1.0, 1.0 - y / 37.5, depth, red, green, blue])


@js
def append_quad(values: list[float], points: list[float], red: float, green: float, blue: float):
    indices = [0, 1, 2, 0, 2, 3]
    for index in indices:
        offset = index * 3
        append_vertex(
            values,
            points[offset],
            points[offset + 1],
            points[offset + 2],
            red,
            green,
            blue,
        )


@js
def append_triangle(
    values: list[float], points: list[float], red: float, green: float, blue: float
):
    index = 0
    while index < 3:
        offset = index * 3
        append_vertex(
            values,
            points[offset],
            points[offset + 1],
            points[offset + 2],
            red,
            green,
            blue,
        )
        index = index + 1


@js
def append_rectangle(
    values: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    depth: float,
    red: float,
    green: float,
    blue: float,
):
    append_quad(
        values,
        [
            x,
            y,
            depth,
            x + width,
            y,
            depth,
            x + width,
            y + height,
            depth,
            x,
            y + height,
            depth,
        ],
        red,
        green,
        blue,
    )


@js
def append_box(
    values: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    depth: float,
    red: float,
    green: float,
    blue: float,
    direction: float = 1.0,
    extrusion: float = 0.65,
):
    horizontal_offset = (0.0 - extrusion) * direction
    vertical_offset = 0.0 - extrusion
    back_depth = depth + extrusion / 4.0
    append_quad(
        values,
        [
            x,
            y,
            depth,
            x + horizontal_offset,
            y + vertical_offset,
            back_depth,
            x + width + horizontal_offset,
            y + vertical_offset,
            back_depth,
            x + width,
            y,
            depth,
        ],
        red * 1.15,
        green * 1.15,
        blue * 1.15,
    )
    side_x = x
    if direction < 0.0:
        side_x = x + width
    append_quad(
        values,
        [
            side_x,
            y,
            depth,
            side_x + horizontal_offset,
            y + vertical_offset,
            back_depth,
            side_x + horizontal_offset,
            y + height + vertical_offset,
            back_depth,
            side_x,
            y + height,
            depth,
        ],
        red * 0.5,
        green * 0.5,
        blue * 0.5,
    )
    append_rectangle(values, x, y, width, height, depth, red, green, blue)


@js
def append_triangle_prism(
    values: list[float],
    points: list[float],
    depth: float,
    red: float,
    green: float,
    blue: float,
    direction: float,
    extrusion: float = 0.35,
):
    horizontal_offset = (0.0 - extrusion) * direction
    vertical_offset = 0.0 - extrusion
    back_depth = depth + extrusion / 4.0
    append_triangle(
        values,
        [
            points[0],
            points[1],
            depth,
            points[2],
            points[3],
            depth,
            points[4],
            points[5],
            depth,
        ],
        red,
        green,
        blue,
    )
    index = 0
    while index < 3:
        next_index = index + 1
        if next_index == 3:
            next_index = 0
        offset = index * 2
        next_offset = next_index * 2
        append_quad(
            values,
            [
                points[offset],
                points[offset + 1],
                depth,
                points[offset] + horizontal_offset,
                points[offset + 1] + vertical_offset,
                back_depth,
                points[next_offset] + horizontal_offset,
                points[next_offset + 1] + vertical_offset,
                back_depth,
                points[next_offset],
                points[next_offset + 1],
                depth,
            ],
            red * 0.55,
            green * 0.55,
            blue * 0.55,
        )
        index = index + 1


@js
class GameRenderer:
    def __init__(
        self,
        device: GPUDevice,
        context: GPUCanvasContext,
        pipeline: GPURenderPipeline,
        vertex_buffer: GPUBuffer,
        depth_texture: GPUTexture,
    ):
        self.device = device
        self.context = context
        self.pipeline = pipeline
        self.vertex_buffer = vertex_buffer
        self.depth_texture = depth_texture
        self.lastVertexCount = 0

    def append_stars(self, values: list[float]):
        index = 0
        while index < 38:
            x_seed = index * 37 + 11
            y_seed = index * 19 + 7
            x = float(x_seed % 100)
            y = float(y_seed % 72)
            brightness = 0.25 + float(index % 4) * 0.08
            size = 0.18 + float(index % 3) * 0.08
            depth = 0.88 + float(index % 3) * 0.025
            append_rectangle(values, x, y, size, size, depth, brightness, brightness, 0.55)
            index = index + 1

    def append_floor(self, values: list[float]):
        append_quad(
            values,
            [0.0, 54.0, 0.96, 100.0, 54.0, 0.96, 100.0, 75.0, 0.96, 0.0, 75.0, 0.96],
            0.015,
            0.045,
            0.09,
        )
        line_y = 56.0
        while line_y < 75.0:
            append_rectangle(values, 0.0, line_y, 100.0, 0.16, 0.9, 0.03, 0.24, 0.32)
            line_y = line_y + (line_y - 52.0) * 0.55
        bottom_x = 0.0
        while bottom_x <= 100.0:
            horizon_x = 50.0 + (bottom_x - 50.0) * 0.08
            append_quad(
                values,
                [
                    horizon_x - 0.06,
                    54.0,
                    0.9,
                    horizon_x + 0.06,
                    54.0,
                    0.9,
                    bottom_x + 0.12,
                    75.0,
                    0.9,
                    bottom_x - 0.12,
                    75.0,
                    0.9,
                ],
                0.03,
                0.2,
                0.3,
            )
            bottom_x = bottom_x + 10.0

    def append_invader(self, values: list[float], invader: Invader, direction: float):
        append_box(
            values,
            invader.x + 1.0,
            invader.y,
            5.0,
            1.2,
            0.42,
            0.2,
            0.95,
            0.75,
            direction,
        )
        append_box(
            values,
            invader.x,
            invader.y + 1.2,
            7.0,
            3.5,
            0.42,
            0.1,
            0.8,
            0.75,
            direction,
        )
        append_box(
            values,
            invader.x + 1.0,
            invader.y + 4.7,
            1.4,
            1.3,
            0.42,
            0.1,
            0.8,
            0.75,
            direction,
        )
        append_box(
            values,
            invader.x + 4.6,
            invader.y + 4.7,
            1.4,
            1.3,
            0.42,
            0.1,
            0.8,
            0.75,
            direction,
        )
        append_box(
            values,
            invader.x + 0.2,
            invader.y + 0.2,
            0.55,
            1.0,
            0.43,
            0.1,
            0.8,
            0.75,
            direction,
        )
        append_box(
            values,
            invader.x + 6.25,
            invader.y + 0.2,
            0.55,
            1.0,
            0.43,
            0.1,
            0.8,
            0.75,
            direction,
        )
        append_rectangle(values, invader.x + 1.4, invader.y + 2.0, 1.1, 0.9, 0.25, 0.03, 0.05, 0.12)
        append_rectangle(values, invader.x + 4.5, invader.y + 2.0, 1.1, 0.9, 0.25, 0.03, 0.05, 0.12)

    def append_player(self, values: list[float], state: GameState):
        x = state.player_x
        y = state.player_y
        direction = state.player_direction
        append_rectangle(values, x + 3.85, y + 4.1, 0.55, 0.9, 0.52, 0.3, 0.5, 1.0)
        append_rectangle(values, x + 4.6, y + 4.1, 0.55, 0.9, 0.52, 0.3, 0.5, 1.0)
        append_triangle_prism(
            values,
            [
                x + 3.85,
                y + 1.4,
                x + 3.85,
                y + 4.4,
                x + 0.25,
                y + 4.4,
            ],
            0.36,
            0.18,
            0.62,
            1.0,
            direction,
        )
        append_triangle_prism(
            values,
            [
                x + 5.15,
                y + 1.4,
                x + 8.75,
                y + 4.4,
                x + 5.15,
                y + 4.4,
            ],
            0.36,
            0.18,
            0.62,
            1.0,
            direction,
        )
        append_box(
            values,
            x + 3.65,
            y + 0.65,
            1.7,
            3.9,
            0.3,
            0.22,
            0.72,
            1.0,
            direction,
            0.35,
        )
        append_triangle_prism(
            values,
            [
                x + 4.5,
                y - 1.0,
                x + 3.65,
                y + 1.0,
                x + 5.35,
                y + 1.0,
            ],
            0.27,
            0.55,
            0.9,
            1.0,
            direction,
            0.35,
        )
        append_box(
            values,
            x + 4.05,
            y + 0.75,
            0.9,
            1.35,
            0.22,
            0.7,
            0.95,
            1.0,
            direction,
            0.22,
        )

    def build_vertices(self, state: GameState) -> Float32Array:
        values: list[float] = []
        self.append_stars(values)
        self.append_floor(values)
        for invader in state.invaders:
            if invader.active:
                self.append_invader(values, invader, state.formation_direction)
        self.append_player(values, state)
        for projectile in state.projectiles:
            if projectile.owner == "player":
                append_box(
                    values,
                    projectile.x,
                    projectile.y,
                    projectile.width,
                    projectile.height,
                    0.2,
                    1.0,
                    0.85,
                    0.25,
                )
            else:
                append_box(
                    values,
                    projectile.x,
                    projectile.y,
                    projectile.width,
                    projectile.height,
                    0.2,
                    1.0,
                    0.25,
                    0.45,
                )
        self.lastVertexCount = len(values) // 6
        return Float32Array(values)

    def render(self, state: GameState):
        vertices = self.build_vertices(state)
        self.device.queue.writeBuffer(self.vertex_buffer, 0, vertices)
        encoder = self.device.createCommandEncoder()
        render_pass = encoder.beginRenderPass(
            GPURenderPassDescriptor(
                [
                    GPURenderPassColorAttachment(
                        self.context.getCurrentTexture().createView(),
                        GPUColor(0.015, 0.025, 0.07),
                    )
                ],
                GPURenderPassDepthStencilAttachment(
                    self.depth_texture.createView(),
                    depth_load_op="clear",
                    depth_store_op="discard",
                ),
            )
        )
        render_pass.setPipeline(self.pipeline)
        render_pass.setVertexBuffer(0, self.vertex_buffer)
        render_pass.draw(self.lastVertexCount)
        render_pass.end()
        self.device.queue.submit([encoder.finish()])


@js
async def create_renderer(canvas_element: HTMLCanvasElement) -> GameRenderer | None:
    adapter = await navigator.gpu.requestAdapter()
    if adapter is None:
        return None
    device = await adapter.requestDevice()
    context = get_webgpu_context(canvas_element)
    canvas_format = navigator.gpu.getPreferredCanvasFormat()
    context.configure(GPUCanvasConfiguration(device, canvas_format))
    shader = device.createShaderModule(
        GPUShaderModuleDescriptor(
            "struct VertexInput { @location(0) position: vec3f, "
            "@location(1) color: vec3f }; "
            "struct VertexOutput { @builtin(position) position: vec4f, "
            "@location(0) color: vec3f }; "
            "@vertex fn vertex_main(input: VertexInput) -> VertexOutput { "
            "var output: VertexOutput; "
            "output.position = vec4f(input.position, 1.0); "
            "output.color = input.color; return output; } "
            "@fragment fn fragment_main(input: VertexOutput) -> @location(0) vec4f { "
            "return vec4f(input.color, 1.0); }"
        )
    )
    pipeline = await device.createRenderPipelineAsync(
        GPURenderPipelineDescriptor(
            GPUVertexState(
                shader,
                "vertex_main",
                [
                    GPUVertexBufferLayout(
                        24,
                        [
                            GPUVertexAttribute("float32x3", 0, 0),
                            GPUVertexAttribute("float32x3", 12, 1),
                        ],
                    )
                ],
            ),
            GPUFragmentState(
                shader,
                "fragment_main",
                [GPUColorTargetState(canvas_format)],
            ),
            GPUPrimitiveState(cull_mode="none"),
            GPUDepthStencilState(),
        )
    )
    vertex_buffer = device.createBuffer(
        GPUBufferDescriptor(
            262144,
            GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
            label="space invaders vertices",
        )
    )
    depth_texture = device.createTexture(
        GPUTextureDescriptor(
            GPUExtent3D(canvas_element.width, canvas_element.height),
            "depth24plus",
            GPUTextureUsage.RENDER_ATTACHMENT,
        )
    )
    return GameRenderer(device, context, pipeline, vertex_buffer, depth_texture)


@js
class GameKeyboardListener:
    def __init__(self, app: SpaceInvadersApp, pressed: bool):
        self.app = app
        self.pressed = pressed

    @js(include=True)
    def handleEvent(self, event: KeyboardEvent):
        if event.key == "ArrowLeft" or event.key == "a" or event.key == "A":
            event.preventDefault()
            self.app.game.set_moving_left(self.pressed)
        elif event.key == "ArrowRight" or event.key == "d" or event.key == "D":
            event.preventDefault()
            self.app.game.set_moving_right(self.pressed)
        elif self.pressed and (event.key == " " or event.key == "Space"):
            event.preventDefault()
            self.app.game.fire()
        elif self.pressed and event.key == "Enter" and self.app.game.status == "game-over":
            self.app.game.restart()
            self.app.sync_hud()


@js
class SpaceInvadersApp(Widget):
    def __init__(self):
        super().__init__()
        self.score_text = ref(tag("span", "0"))
        self.lives_text = ref(tag("span", "3"))
        self.wave_text = ref(tag("span", "1"))
        self.status_text = ref(
            tag(
                "div",
                tw(
                    "pointer-events-none absolute inset-0 hidden items-center justify-center "
                    "bg-slate-950/80 text-center"
                ),
                tag(
                    "div",
                    tw("rounded-2xl border border-cyan-400/30 bg-slate-950 p-8 shadow-2xl"),
                    tag("p", tw("font-mono text-3xl font-bold text-cyan-300"), "GAME OVER"),
                    tag(
                        "p",
                        tw("mt-3 font-mono text-sm uppercase tracking-widest text-slate-300"),
                        "Press Enter to restart",
                    ),
                ),
            )
        )
        self.game_canvas = ref(canvas())
        self.game_canvas.setAttribute("width", "768")
        self.game_canvas.setAttribute("height", "576")
        self.game_canvas.setAttribute(
            "class",
            "block aspect-[4/3] w-full rounded-xl border border-cyan-400/20 bg-slate-950",
        )
        self.game_canvas.setAttribute("aria-label", "Space Invaders game field")
        self.setAttribute("score", "0")
        self.setAttribute("lives", "3")
        self.setAttribute("wave", "1")
        self.setAttribute("status", "loading")
        hud = tag(
            "header",
            tw(
                "mb-3 flex items-center justify-between rounded-xl border border-slate-700 "
                "bg-slate-900/90 px-4 py-3 font-mono text-sm uppercase tracking-wider"
            ),
            tag("span", tw("text-cyan-300"), "Score ", self.score_text),
            tag("span", tw("text-violet-300"), "Wave ", self.wave_text),
            tag("span", tw("text-rose-300"), "Lives ", self.lives_text),
        )
        game_frame = tag(
            "div",
            tw("relative overflow-hidden rounded-xl shadow-2xl shadow-cyan-950/60"),
            self.game_canvas,
            self.status_text,
        )
        instructions = tag(
            "p",
            tw("mt-4 text-center font-mono text-xs uppercase tracking-widest text-slate-400"),
            "Move: ← → or A D   ·   Fire: Space",
        )
        self.add(
            tw(
                "box-border flex min-h-screen items-center justify-center bg-slate-950 "
                "p-4 text-white"
            ),
            tag(
                "main",
                tw("w-full max-w-4xl"),
                tag(
                    "h1",
                    tw(
                        "mb-5 text-center font-mono text-3xl font-black uppercase "
                        "tracking-[0.28em] text-cyan-300"
                    ),
                    "Void Patrol",
                ),
                hud,
                game_frame,
                instructions,
            ),
        )

    async def initialize(self):
        self.game = GameState()
        self.renderer: GameRenderer | None = None
        self.last_timestamp = 0.0
        self.keydown_listener = GameKeyboardListener(self, True)
        self.keyup_listener = GameKeyboardListener(self, False)
        document.addEventListener("keydown", self.keydown_listener)
        document.addEventListener("keyup", self.keyup_listener)
        self.renderer = await create_renderer(self.game_canvas)
        if self.renderer is None:
            self.setAttribute("status", "unsupported")
            self.status_text.textContent = "WebGPU is not available in this browser"
            self.status_text.style.display = "flex"
            return
        self.setAttribute("status", "playing")
        self.sync_hud()
        self.renderer.render(self.game)
        requestAnimationFrame(self.frame)

    def sync_hud(self):
        self.score_text.textContent = str(self.game.score)
        self.lives_text.textContent = str(self.game.lives)
        self.wave_text.textContent = str(self.game.wave)
        self.setAttribute("score", str(self.game.score))
        self.setAttribute("lives", str(self.game.lives))
        self.setAttribute("wave", str(self.game.wave))
        self.setAttribute("status", self.game.status)
        if self.game.status == "game-over":
            self.status_text.style.display = "flex"
        else:
            self.status_text.style.display = "none"

    def frame(self, timestamp: float):
        renderer = self.renderer
        if renderer is None:
            return
        if self.last_timestamp == 0.0:
            elapsed = 0.0
        else:
            elapsed = (timestamp - self.last_timestamp) / 1000.0
        self.last_timestamp = timestamp
        if elapsed > 0.05:
            elapsed = 0.05
        self.game.step(elapsed)
        self.sync_hud()
        renderer.render(self.game)
        requestAnimationFrame(self.frame)


def main():
    return SpaceInvadersApp()


if __name__ == "__main__":
    from pyjs.server import serve

    serve("space_invaders")

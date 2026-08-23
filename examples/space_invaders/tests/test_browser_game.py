import pytest
from pyjs import js
from pyjs.testing.webgpu import assert_webgpu_render
from pyjs.web.dom import document
from pyjs.web.domx import canvas
from pyjs.web.events import KeyboardEvent
from pyjs.web.webgpu import navigator
from pyjs_examples.space_invaders.space_invaders import (
    GameState,
    Projectile,
    SpaceInvadersApp,
    create_renderer,
)

pytestmark = pytest.mark.pyjs_web


@js
def test_hud_reflects_observable_game_state():
    app = SpaceInvadersApp()
    app.game = GameState()
    app.game.score = 1200
    app.game.lives = 2
    app.game.wave = 3

    app.sync_hud()

    assert app.getAttribute("score") == "1200"
    assert app.getAttribute("lives") == "2"
    assert app.getAttribute("wave") == "3"
    assert app.score_text.textContent == "1200"


@js
def test_compatibility_panel_distinguishes_api_and_adapter_failures():
    app = SpaceInvadersApp()

    app.show_compatibility("unsupported")

    assert app.getAttribute("status") == "unsupported"
    assert app.status_title.textContent == "WebGPU unavailable"
    assert "does not expose WebGPU" in app.status_detail.textContent
    assert app.status_action.style.display == "inline-flex"
    assert app.status_text.style.display == "flex"

    app.show_compatibility("adapter-unavailable")

    assert app.getAttribute("status") == "adapter-unavailable"
    assert app.status_title.textContent == "No GPU adapter"
    assert "compatible graphics adapter" in app.status_detail.textContent


@js
async def test_keyboard_controls_drive_the_initialized_app():
    if navigator.gpu is None:
        raise RuntimeError("WebGPU API is unavailable in this browser")
    app = SpaceInvadersApp()
    await app.initialize()
    starting_x = app.game.player_x

    document.dispatchEvent(KeyboardEvent("keydown", key="ArrowRight"))
    app.game.step(0.25)
    document.dispatchEvent(KeyboardEvent("keyup", key="ArrowRight"))
    document.dispatchEvent(KeyboardEvent("keydown", key=" "))
    app.sync_hud()

    assert app.renderer is not None
    assert app.game.player_x > starting_x
    assert app.game.active_projectile_count("player") == 1
    assert app.getAttribute("status") == "playing"
    app.renderer = None


@js
async def test_initial_wave_render():
    game_canvas = canvas()
    game_canvas.setAttribute("width", "768")
    game_canvas.setAttribute("height", "576")
    document.body.setAttribute("style", "margin:0; background:#020617")
    document.body.append(game_canvas)
    if navigator.gpu is None:
        raise RuntimeError("WebGPU API is unavailable in this browser")
    renderer = await create_renderer(game_canvas)
    if renderer is None:
        raise RuntimeError(
            "WebGPU adapter acquisition failed: requestAdapter() returned None"
        )
    game = GameState()

    renderer.render(game)

    assert game.active_invader_count() == 24
    initial_vertex_count = renderer.lastVertexCount
    assert initial_vertex_count > 3000
    await assert_webgpu_render(renderer.device, game_canvas, "initial_wave")

    index = 0
    while index < 5:
        game.invaders[index].active = False
        index = index + 1
    game.player_x = 68.0
    game.player_direction = -1.0
    game.formation_direction = -1.0
    game.projectiles.append(Projectile(50.0, 45.0, -48.0, "player"))
    game.projectiles.append(Projectile(60.0, 35.0, 22.0, "enemy"))
    renderer.render(game)

    assert game.active_invader_count() == 19
    assert game.player_direction == game.formation_direction
    assert renderer.lastVertexCount < initial_vertex_count
    await assert_webgpu_render(renderer.device, game_canvas, "action_scene")

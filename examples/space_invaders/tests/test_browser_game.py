import pytest
from pyjs import js
from pyjs.testing.webgpu import assert_webgpu_render
from pyjs.web.dom import document
from pyjs.web.domx import canvas
from pyjs.web.events import KeyboardEvent
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
async def test_keyboard_controls_drive_the_initialized_app():
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
    renderer = await create_renderer(game_canvas)
    if renderer is None:
        assert renderer is not None, "This browser does not provide WebGPU"
        return
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

from pyjs import js
from pyjs_examples.space_invaders.space_invaders import GameState, Projectile


@js
def test_player_movement_is_clamped_to_the_playfield():
    game = GameState()
    game.set_moving_left(True)
    game.step(10.0)
    assert game.player_x == 2.0
    assert game.player_direction == -1.0

    game.set_moving_left(False)
    game.step(0.1)
    assert game.player_direction == -1.0

    game.set_moving_right(True)
    game.step(10.0)
    assert game.player_x == 89.0
    assert game.player_direction == 1.0


@js
def test_player_can_only_have_one_shot_in_flight():
    game = GameState()

    game.fire()
    game.fire()

    assert game.active_projectile_count("player") == 1


@js
def test_player_projectile_destroys_an_invader_and_scores():
    game = GameState()
    target = game.invaders[0]
    game.projectiles.append(Projectile(target.x + 2.0, target.y + 2.0, 0.0, "player"))

    game.step(0.0)

    assert not target.active
    assert game.score == 100
    assert game.active_invader_count() == 23


@js
def test_enemy_projectile_costs_a_life_and_clears_projectiles():
    game = GameState()
    game.projectiles.append(Projectile(game.player_x + 2.0, game.player_y + 1.0, 0.0, "enemy"))

    game.step(0.0)

    assert game.lives == 2
    assert len(game.projectiles) == 0


@js
def test_clearing_a_wave_spawns_a_faster_wave():
    game = GameState()
    for invader in game.invaders:
        invader.active = False

    game.step(0.0)

    assert game.wave == 2
    assert game.active_invader_count() == 24
    assert game.formation_speed == 8.5


@js
def test_game_over_can_be_restarted():
    game = GameState()
    game.score = 900
    game.lives = 0
    game.status = "game-over"

    game.restart()

    assert game.status == "playing"
    assert game.score == 0
    assert game.lives == 3
    assert game.wave == 1
    assert game.active_invader_count() == 24

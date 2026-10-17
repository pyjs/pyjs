from tests.reorder_scenarios import mixed_height_cross_axis_scenario


def test_reorder_scenario_runs_against_the_pure_state_machine():
    scenario = mixed_height_cross_axis_scenario()
    scenario.assert_decision(scenario.replay())

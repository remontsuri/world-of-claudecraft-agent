from reward import outcome_reward


def _state(**overrides):
    state = {
        "kills": 0,
        "xp": 0,
        "copper": 0,
        "quests_done": 0,
        "inv_slots": 0,
        "deaths": 0,
        "quest_progress": 0,
        "distance_to_giver": 10.0,
        "hp_frac": 1.0,
    }
    state.update(overrides)
    return state


def test_kill_has_meaningful_positive_reward():
    reward = outcome_reward(_state(), _state(kills=1, xp=10), "SUCCESS")
    assert reward >= 1.0


def test_no_kill_no_kill_bonus():
    assert outcome_reward(_state(), _state(), "INCONCLUSIVE") == 0.0

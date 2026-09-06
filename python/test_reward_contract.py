from reward import outcome_reward

def test_kill_is_positive_without_hp_loss():
    before = {"kills": 0, "deaths": 0, "hp_frac": 1.0, "distance_to_giver": 10}
    after = {"kills": 1, "deaths": 0, "hp_frac": 1.0, "distance_to_giver": 10}
    assert outcome_reward(before, after, "SUCCESS") > 0

def test_death_penalty_dominates_kill_signal():
    before = {"kills": 0, "deaths": 0, "hp_frac": 1.0, "distance_to_giver": 10}
    after = {"kills": 1, "deaths": 1, "hp_frac": 0.0, "distance_to_giver": 10}
    assert outcome_reward(before, after, "SUCCESS") < 0

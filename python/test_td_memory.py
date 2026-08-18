"""Unit test for the TD memory upgrade (memory.py).

Proves:
1. update() now uses next_state (TD bootstrap), not just (reward - w).
2. A negative-reward first step into a VALUABLE next state still raises Q
   (sequential learning: "X led to S' which is good -> X was a good first step").
3. Backward-compat: without next_state it degrades to bandit-style (no crash).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from memory import ExperienceStore, _bucket

def ws(hp=1.0, mob=False, corpse=False, junk=False, qs="NONE", far=False, danger=False, combat=False, dist=0.0):
    return {
        "hp_frac": hp, "has_mob": mob, "has_corpse": corpse, "has_junk": junk,
        "quest_status": qs, "distance_to_giver": dist, "danger": danger, "in_combat": combat,
    }

def main():
    mem = ExperienceStore(lr=0.5, decay=1.0, gamma=0.9, path=":memory:")
    # S = far from giver, quest active, hp full, mob nearby
    S = ws(hp=1.0, mob=True, qs="ACTIVE", far=True, dist=120.0)
    Sbucket = _bucket(S)
    # S' = arrived at giver, quest ready to turn in (a GOOD state)
    Sp = ws(hp=1.0, qs="READY_TO_TURN_IN", far=False, dist=4.0)
    Spbucket = _bucket(Sp)

    # First: make S' valuable by giving turn_in a high Q there
    mem.update(Sp, "turn_in_quest", +5.0, next_state=None)  # bootstrapless seed
    q_turnin_at_Sp = mem.value(Spbucket, "turn_in_quest")
    print(f"[seed] Q({Spbucket}, turn_in_quest) = {q_turnin_at_Sp:.3f}")

    # Now: a 'bad' first action from S that LEADS to Sp (the good state).
    # reward is negative (-1) but next_state is valuable.
    before = mem.value(Sbucket, "farm")
    mem.update(S, "farm", -1.0, next_state=Sp)
    after = mem.value(Sbucket, "farm")
    target = -1.0 + mem.gamma * max(
        (mem.value(Spbucket, a) for a in mem.ACTIONS), default=0.0)
    print(f"[TD] Q({Sbucket}, farm) before={before:.3f} after={after:.3f}  (target should be {target:.3f})")

    assert abs(after - (before + mem.lr * (target - before))) < 1e-6, "TD update math wrong"
    # The key sequential-learning check: even with negative reward, Q(S, farm) moved
    # toward a POSITIVE target (because S' is good) -> it went UP, not down.
    assert after > before, "sequential bootstrap did not raise Q despite negative reward"
    print("[OK] sequential learning: negative first step into valuable S' raised Q(S, action)")

    # Backward-compat: no next_state -> bandit fallback, no crash, target = reward only
    b2 = mem.value(Sbucket, "loot")
    mem.update(S, "loot", -2.0, next_state=None)
    a2 = mem.value(Sbucket, "loot")
    assert abs(a2 - (b2 + mem.lr * (-2.0 - b2))) < 1e-6, "bandit fallback wrong"
    print("[OK] backward-compat: update without next_state degrades to bandit, no crash")

    # experiences log must carry next_bucket
    assert mem.experiences and len(mem.experiences[-1]) == 5, "experience tuple shape changed"
    print("[OK] experience log carries (bucket, action, reward, next_bucket, outcome_kind)")

    print("\nALL TD MEMORY TESTS PASSED")

if __name__ == "__main__":
    main()

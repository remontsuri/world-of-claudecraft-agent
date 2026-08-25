from pathlib import Path


def test_trainer_uses_canonical_skill_universe():
    path = Path(__file__).with_name("retrain_from_replay.py")
    text = path.read_text(encoding="utf-8")
    assert "from hierarchical_env import SKILLS" in text
    assert "mem.ACTIONS = list(SKILLS)" in text


def test_trainer_does_not_promote_stale_memory_in_place():
    path = Path(__file__).with_name("retrain_from_replay.py")
    text = path.read_text(encoding="utf-8")
    assert 'default=os.path.join(base, "experience_retrained.json")' in text
    assert "mem.weights = defaultdict(float)" in text

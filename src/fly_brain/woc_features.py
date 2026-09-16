"""woc_features.py — engineered WoC observation features for fly-brain.

Pattern from Fly Dino v2: 8 structured game features mapped to visual cell types.
For WoC we use 8 features covering: HP, mob distance, mob count, level, attack readiness,
last reward, stuck indicator, loot proximity.
"""
import numpy as np


def extract_features(obs, info=None):
    """Extract 8 engineered features from WoC observation.

    obs: raw observation vector from WoC (or dict with keys)
    info: game info dict (optional, for richer features)

    Returns: np.ndarray (8,) float32
    """
    if info is None:
        info = {}

    player = info.get('player', {})
    nearby = info.get('nearby', [])

    # Feature 0: HP (normalized 0-1)
    hp = player.get('hp', 100)
    f_hp = np.clip(hp / 100.0, 0.0, 1.0)

    # Feature 1: Distance to nearest hostile mob (normalized, 1=close 0=far)
    mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
    hostile = [e for e in mobs if e.get('hostile')]
    targets = hostile if hostile else mobs
    if targets:
        nearest = min(targets, key=lambda e: e.get('dist', 999))
        dist = nearest.get('dist', 100)
        f_mob_dist = 1.0 - np.clip(dist / 100.0, 0.0, 1.0)
    else:
        f_mob_dist = 0.0

    # Feature 2: Mob count (normalized)
    f_mob_count = np.clip(len(mobs) / 10.0, 0.0, 1.0)

    # Feature 3: Player level (normalized)
    level = info.get('level', 1)
    f_level = np.clip(level / 50.0, 0.0, 1.0)

    # Feature 4: Attack readiness (1 if attack ready, 0 otherwise)
    f_attack_ready = 1.0 if player.get('attack_ready', False) else 0.0

    # Feature 5: Last reward (tanh normalized)
    last_reward = info.get('last_reward', 0.0)
    f_reward = np.tanh(last_reward / 10.0)

    # Feature 6: Stuck indicator (1 if position unchanged)
    f_stuck = 1.0 if info.get('stuck', False) else 0.0

    # Feature 7: Loot proximity (1=close, 0=far)
    loot = [e for e in nearby if e.get('kind') == 'loot']
    if loot:
        nearest_loot = min(loot, key=lambda e: e.get('dist', 999))
        loot_dist = nearest_loot.get('dist', 100)
        f_loot = 1.0 - np.clip(loot_dist / 100.0, 0.0, 1.0)
    else:
        f_loot = 0.0

    return np.array([
        f_hp, f_mob_dist, f_mob_count, f_level,
        f_attack_ready, f_reward, f_stuck, f_loot
    ], dtype=np.float32)


# Mapping to visual cell types (arbitrary, for biological flavor)
# Pattern from Fly Dino: each feature drives a different visual projection type
FEATURE_CELL_TYPES = {
    0: 'LC4',    # HP -> proximity
    1: 'LC11',   # Mob distance -> width
    2: 'LC9',    # Mob count -> height
    3: 'LC15',   # Level -> altitude
    4: 'LC16',   # Attack ready -> speed
    5: 'LC17',   # Reward -> player height
    6: 'LC21',   # Stuck -> vertical velocity
    7: 'LPLC2',  # Loot -> ground contact
}

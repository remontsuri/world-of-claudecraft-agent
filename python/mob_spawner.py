"""MobSpawner: reads quest mob spawn areas from game source."""
import json
import re
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
EXPORT_PATH = SCRIPT_DIR / "game_agent_export.json"
ZONE_PATH = Path(r"D:\woc-game\src\sim\content\zone1.ts")


def _load_export() -> dict:
    with open(EXPORT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_zone() -> str:
    with open(ZONE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _parse_spawn_zones(text: str) -> list[dict]:
    """Parse { mobId: 'x', center: { x, z }, radius, count } from zone1.ts."""
    zones = []
    # Pattern: { mobId: '...', center: { x: NUM, z: NUM }, radius: NUM, count: NUM }
    pattern = re.compile(
        r"\{\s*mobId:\s*['\"](\w+)['\"]\s*,\s*"
        r"center:\s*\{\s*x:\s*(-?\d+\.?\d*)\s*,\s*z:\s*(-?\d+\.?\d*)\s*\}\s*,\s*"
        r"radius:\s*(-?\d+\.?\d*)\s*,\s*"
        r"count:\s*(-?\d+)\s*\}",
    )
    for m in pattern.finditer(text):
        zones.append({
            "mob_id": m.group(1),
            "x": float(m.group(2)),
            "z": float(m.group(3)),
            "radius": float(m.group(4)),
            "count": int(m.group(5)),
        })
    return zones


def load_spawns() -> dict[str, list[dict]]:
    """Return {quest_id: [{x, z, radius, count, mob_id}]}."""
    data = _load_export()
    zone_text = _load_zone()
    zones = _parse_spawn_zones(zone_text)

    # Build mob_id -> spawn_zones mapping
    mob_zones: dict[str, list[dict]] = {}
    for z in zones:
        mob_zones.setdefault(z["mob_id"], []).append(z)

    # Map quest_id -> spawn zones via quest_objectives
    result = {}
    objectives = data.get("quest_objectives", {})
    quests = data.get("quests", {})

    for quest_id, quest_data in quests.items():
        q_obj = objectives.get(quest_id, [])
        if not q_obj:
            # Try quest_data.objectives directly
            q_obj = quest_data.get("objectives", [])

        quest_spawns = []
        for obj in q_obj:
            if obj.get("type") == "kill":
                target_mob = obj.get("targetMobId", "")
                if target_mob in mob_zones:
                    for z in mob_zones[target_mob]:
                        quest_spawns.append({**z, "quest_id": quest_id})

        if quest_spawns:
            result[quest_id] = quest_spawns

    return result


def nearest_spawn(quest_id: str, x: float, z: float) -> tuple[float, float] | tuple[None, None]:
    """Return (x, z) of the closest spawn zone for quest_id, or (None, None)."""
    spawns = load_spawns()
    zones = spawns.get(quest_id)
    if not zones:
        return (None, None)

    best = None
    best_dist = float("inf")
    for zone in zones:
        dx = zone["x"] - x
        dz = zone["z"] - z
        dist = (dx * dx + dz * dz) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best = (zone["x"], zone["z"])

    return best


def nearest_spawns(quest_id: str, x: float, z: float) -> list[dict]:
    """Return all spawn zones sorted by distance from (x, z)."""
    spawns = load_spawns()
    zones = spawns.get(quest_id, [])

    for zone in zones:
        dx = zone["x"] - x
        dz = zone["z"] - z
        zone["distance"] = (dx * dx + dz * dz) ** 0.5

    return sorted(zones, key=lambda z: z["distance"])


if __name__ == "__main__":
    spawns = load_spawns()
    print(f"Loaded spawns for {len(spawns)} quests")
    for qid, zones in list(spawns.items())[:3]:
        print(f"  {qid}: {len(zones)} zones — {zones[0]}")

    # Test nearest
    near = nearest_spawn("q_wolves", 0, 0)
    print(f"\nnearest_spawn('q_wolves', 0, 0) = {near}")

"""C-quest probe: any quest-giver NPC in nearby at spawn? accept_quest needs one."""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=500)
obs, info = env.reset(seed=42)
near = info.get("nearby") or []
quest_npcs = []
for e in near:
    if e.get("kind") == "npc" or e.get("type") == "npc":
        flags = {k: e.get(k) for k in ("quest", "questId", "quests", "offersQuest", "hasQuest")}
        if any(v for v in flags.values()):
            quest_npcs.append((e.get("id"), flags))
print(f"npcs total={sum(1 for e in near if (e.get('kind')=='npc' or e.get('type')=='npc'))}")
print(f"quest-flagged npcs={len(quest_npcs)}")
for nid, fl in quest_npcs[:10]:
    print(f"  npc {nid}: {fl}")
# also dump one npc's full keys to see quest signal shape
for e in near:
    if e.get("kind") == "npc":
        print("sample npc keys:", sorted(e.keys()))
        break
env.close()

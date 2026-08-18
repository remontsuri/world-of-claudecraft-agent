"""Exploration probe: do vendor/node/quest-giver entities become visible if we
MOVE (not just observe at spawn)? Tests the reframe claim: "SKIP is world-context
absence, not capability absence — navigate to find them" (like mobs ~46u away).

Bounded manual step loop (C1-style, no PPO) to avoid server crash. Logs every
distinct entity kind/type/id seen across roaming, especially vendor/object/node
with questIds.
"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT, ACT_TURN_RIGHT

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)

seen_kinds = {}
vendor_like = []
node_like = []
quest_npcs = []
positions_log = []

def classify(near):
    for e in near:
        k = e.get("kind") or e.get("type") or "?"
        seen_kinds[k] = seen_kinds.get(k, 0) + 1
        if e.get("vendorItems") is not None or (e.get("kind") == "npc" and (e.get("vendorItems") or [])):
            vendor_like.append((e.get("id"), e.get("vendorItems")))
        if e.get("harvestable") or (e.get("kind") in ("node", "object") and e.get("materialId")):
            node_like.append((e.get("id"), e.get("kind"), e.get("materialId"), e.get("harvestable")))
        if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId")):
            quest_npcs.append((e.get("id"), e.get("questIds") or e.get("questId")))

classify(info.get("nearby") or [])
positions_log.append(("spawn", info.get("player_pos") or (info.get("px"), info.get("pz"))))

# roam: forward bursts + turns, observe after each
for i in range(20):
    # move forward 10 low-level steps
    for _ in range(10):
        env.base.step(ACT_FORWARD)
    env.base.step(ACT_TURN_LEFT if i % 2 == 0 else ACT_TURN_RIGHT)
    # re-observe via a noop-ish high step? use base step to refresh nearby
    _, _, _, _, iinfo = env.base.step(ACT_FORWARD)
    classify(iinfo.get("nearby") or [])
    if (i + 1) % 5 == 0:
        positions_log.append((f"step{i}", iinfo.get("player_pos") or (iinfo.get("px"), iinfo.get("pz"))))

print("DISTINCT ENTITY KINDS SEEN:")
for k, c in sorted(seen_kinds.items(), key=lambda x: -x[1]):
    print(f"  {k}: {c}")
print(f"\nVENDOR-LIKE: {len(vendor_like)} -> {vendor_like[:5]}")
print(f"NODE-LIKE:   {len(node_like)} -> {node_like[:5]}")
print(f"QUEST NPCS:  {len(quest_npcs)} -> {quest_npcs[:5]}")
print(f"\nPOSITIONS: {positions_log}")
env.close()

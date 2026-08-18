"""READ-ONLY: bucket-key mismatch between decide() and learn().

Suspicion from code reading:
  policy.GoalManager._world_state(info) -> {hp_frac, quest_status, has_mob,
      has_corpse, has_junk, danger}                 # NO distance_to_giver, NO in_combat
  agent._world_state_dict(info)         -> {hp_frac, ..., quest_status,
      distance_to_giver, in_combat}                 # NO has_mob/corpse/junk/danger

memory._bucket() consumes BOTH. So:
  - the bucket used to READ values in decide()  always has far=0, combat=0
  - the bucket used to WRITE values in learn()  always has mob=0, corpse=0,
    junk=0, danger=0

If the two strings differ for the same world moment, every lesson is filed under
a key the decision path never looks up -> learning cannot influence behaviour,
and P(return|far) can never move for the far bucket. Measure it on real info.
"""

import sys

from hierarchical_env import HierarchicalWoWEnv
from policy import GoalManager
from memory import ExperienceStore, _bucket
from agent import _world_state_dict

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42

env = HierarchicalWoWEnv(player_class="warrior", max_steps=3000, seed=SEED)
env.reset(seed=SEED)
mem = ExperienceStore(path="/tmp/_probe_bucket.json")
gm = GoalManager(mem, seed=1)

info = env._last_info
ws_policy = gm._world_state(info)
ws_agent = _world_state_dict(info)

b_policy = _bucket(ws_policy)
b_agent = _world_state_dict and _bucket(ws_agent)

print(f"=== BUCKET MISMATCH PROBE seed={SEED} ===")
print(f"policy._world_state keys : {sorted(ws_policy.keys())}")
print(f"agent._world_state_dict  : {sorted(ws_agent.keys())}")
print()
print(f"bucket used by decide() : {b_policy}")
print(f"bucket used by learn()  : {b_agent}")
print(f">> IDENTICAL: {b_policy == b_agent}")

missing_in_policy = [k for k in ("distance_to_giver", "in_combat") if k not in ws_policy]
missing_in_agent = [k for k in ("has_mob", "has_corpse", "has_junk", "danger")
                    if k not in ws_agent]
print(f"\npolicy state missing (forces far=0/combat=0): {missing_in_policy}")
print(f"agent state missing (forces mob/corpse/junk/danger=0): {missing_in_agent}")

# Now simulate the actual consequence: teach a lesson the agent-side way,
# then ask the policy-side path whether it can see it.
print("\n--- consequence: write a lesson via learn(), read it via decide() path ---")
ws_far = dict(ws_agent)
ws_far["distance_to_giver"] = 300.0     # genuinely far
mem.update(ws_far, "farm", -5.0, next_state=ws_far)      # strong negative lesson
wb = _bucket(ws_far)
print(f"  lesson written under : {wb}")
print(f"  value(farm) there    : {mem.value(wb, 'farm'):+.4f}")

ws_far_policy = dict(ws_policy)          # policy has no distance field at all
rb = _bucket(ws_far_policy)
print(f"  decide() would read  : {rb}")
print(f"  value(farm) there    : {mem.value(rb, 'farm'):+.4f}")
print(f"  >> lesson VISIBLE to decide(): {abs(mem.value(rb, 'farm')) > 1e-9}")

env.close()

import os
if os.path.exists("/tmp/_probe_bucket.json"):
    os.remove("/tmp/_probe_bucket.json")
print("\n=== END ===")

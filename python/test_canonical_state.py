"""test_canonical_state.py — Task 1: canonical WorldState.

Every field in ws MUST come from the game snapshot (info dict built by the
bridge from sim.player / sim.entities / sim.questLog / sim.inventory).
No static NPC / gather-tool / quest tables in world_state.py.

Audit of world_state.py BEFORE this task (2026-08-26):
  FROM GAME  : hp, maxHp, nearby entities, inventory, bagCapacity, mana,
               maxMana, abilities, recipes_known, stations, quests.active/
               ready/done, kills, xp, copper, deaths, in_combat, player_pos
  HARDCODED  : _gather_tool_needed.TOOLS  {mining: copper_mining_pick,
               logging: handaxe, herbalism: gathering_sickle}
               _gather_tool_needed.NODE_PROF {ore: mining, wood: logging,
               herb: herbalism}
               bag_capacity fallback 16, has_junk = False (constant)
  MISSING    : player_class, player_facing, mana/max_mana raw, quest.objectives,
               inventory.free_slots, inventory.quest_items, world.nearby_mobs,
               world.gather_nodes, world.vendors
"""
import world_state as W


def _info(**over):
    info = {
        "player": {"hp": 40, "maxHp": 80, "level": 4, "mana": 30, "maxMana": 60,
                   "facing": 1.75, "dead": False},
        "player_pos": [10.0, 20.0],
        "nearby": [],
        "inventory": [],
        "quests": {"active": [], "ready": [], "done": []},
    }
    info.update(over)
    return info


# ---------- player_class from entities (kind='player' -> templateId) ----------

def test_player_class_from_player_entity_template_id():
    ws = W.build_world_state(_info(nearby=[
        {"kind": "player", "templateId": "mage", "self": True, "x": 10, "z": 20},
    ]))
    assert ws["player_class"] == "mage"


def test_player_class_unknown_when_no_player_entity():
    ws = W.build_world_state(_info())
    assert ws["player_class"] is None


# ---------- player facing / mana raw ----------

def test_player_facing_from_game():
    ws = W.build_world_state(_info())
    assert ws["player_facing"] == 1.75


def test_mana_and_max_mana_raw_from_player():
    ws = W.build_world_state(_info())
    assert ws["mana"] == 30
    assert ws["max_mana"] == 60


def test_mana_none_when_game_has_no_mana():
    info = _info()
    info["player"].pop("mana")
    info["player"].pop("maxMana")
    ws = W.build_world_state(info)
    assert ws["mana"] is None and ws["max_mana"] is None
    assert ws["mana_frac"] == -1.0


# ---------- quest.objectives ----------

def test_quest_objectives_carry_type_target_current_required():
    q = {"id": "q_kill", "state": "active", "turnInNpc": {"id": 7, "x": 12, "z": 20},
         "objectives": [{"type": "kill", "targetMobId": "greyjaw_wolf",
                         "current": 2, "required": 5}]}
    ws = W.build_world_state(_info(quests={"active": [q], "ready": [], "done": []}))
    objs = ws["quest"]["objectives"]
    assert objs == [{"type": "kill", "targetMobId": "greyjaw_wolf",
                     "itemId": None, "nodeType": None,
                     "current": 2, "required": 5}]


def test_quest_objectives_empty_list_when_no_quest():
    ws = W.build_world_state(_info())
    assert ws["quest"]["objectives"] == []


# ---------- inventory block ----------

def test_inventory_free_slots_from_bag_capacity():
    inv = [{"itemId": "wolf_pelt", "count": 3}, {"itemId": "copper_ore", "count": 1}]
    ws = W.build_world_state(_info(inventory=inv, bagCapacity=16))
    assert ws["inventory"]["free_slots"] == 14
    assert ws["inventory"]["used_slots"] == 2
    assert ws["inventory"]["capacity"] == 16


def test_inventory_quest_items_from_quest_objectives():
    q = {"id": "q_collect", "state": "active",
         "objectives": [{"type": "collect", "itemId": "wolf_pelt",
                         "current": 1, "required": 4}]}
    inv = [{"itemId": "wolf_pelt", "count": 1}, {"itemId": "junk_rock", "count": 2}]
    ws = W.build_world_state(_info(inventory=inv,
                                   quests={"active": [q], "ready": [], "done": []}))
    assert ws["inventory"]["quest_items"] == {"wolf_pelt": 1}


# ---------- world block ----------

def test_world_nearby_mobs_gather_nodes_vendors_from_entities():
    nearby = [
        {"kind": "mob", "id": 1, "templateId": "greyjaw_wolf", "hp": 20,
         "maxHp": 20, "x": 11, "z": 20},
        {"kind": "node", "id": 2, "nodeType": "ore", "templateId": "copper_vein",
         "x": 14, "z": 20},
        {"kind": "npc", "id": 3, "templateId": "trader_wilkes", "vendor": True,
         "x": 10, "z": 21},
        {"kind": "npc", "id": 4, "templateId": "guard_bob", "x": 10, "z": 22},
    ]
    ws = W.build_world_state(_info(nearby=nearby))
    world = ws["world"]
    assert [m["id"] for m in world["nearby_mobs"]] == [1]
    assert world["nearby_mobs"][0]["templateId"] == "greyjaw_wolf"
    assert [n["id"] for n in world["gather_nodes"]] == [2]
    assert world["gather_nodes"][0]["nodeType"] == "ore"
    assert [v["id"] for v in world["vendors"]] == [3]


def test_world_blocks_empty_without_entities():
    ws = W.build_world_state(_info())
    assert ws["world"] == {"nearby_mobs": [], "gather_nodes": [], "vendors": []}


# ---------- no hardcoded tables ----------

def test_no_static_tool_or_node_tables_in_module():
    src = open(W.__file__, encoding="utf-8").read()
    for banned in ("copper_mining_pick", "gathering_sickle", "handaxe",
                   "NODE_PROF", "TOOLS ="):
        assert banned not in src, f"hardcoded table leftover: {banned}"


def test_needs_tool_comes_from_game_objective():
    q = {"id": "q_gather", "state": "active",
         "objectives": [{"type": "gather", "nodeType": "ore",
                         "toolItemId": "copper_mining_pick",
                         "current": 0, "required": 5}]}
    ws = W.build_world_state(_info(quests={"active": [q], "ready": [], "done": []}))
    assert ws["needs_tool"] == "copper_mining_pick"


def test_needs_tool_none_when_tool_already_in_inventory():
    q = {"id": "q_gather", "state": "active",
         "objectives": [{"type": "gather", "nodeType": "ore",
                         "toolItemId": "copper_mining_pick",
                         "current": 0, "required": 5}]}
    ws = W.build_world_state(_info(
        inventory=[{"itemId": "copper_mining_pick", "count": 1}],
        quests={"active": [q], "ready": [], "done": []}))
    assert ws["needs_tool"] is None


def test_needs_tool_none_when_game_gives_no_tool_id():
    q = {"id": "q_gather", "state": "active",
         "objectives": [{"type": "gather", "nodeType": "ore",
                         "current": 0, "required": 5}]}
    ws = W.build_world_state(_info(quests={"active": [q], "ready": [], "done": []}))
    assert ws["needs_tool"] is None


# ---------- regression: existing consumers keep their fields ----------

def test_existing_bucket_fields_preserved():
    ws = W.build_world_state(_info())
    for k in ("hp_frac", "quest_status", "has_mob", "has_corpse", "has_junk",
              "danger", "distance_to_giver", "in_combat", "quest_progress",
              "inv_slots", "bag_capacity", "bag_full", "abilities"):
        assert k in ws, f"missing legacy field {k}"

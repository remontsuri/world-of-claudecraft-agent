"""Schema contract на ОФИЦИАЛЬНОЙ границе canonical WS -> observation.

Граница взята из кода, а не придумана (autonomy.py):

    ws  = build_world_state(info)
    obs = encode_observation(ws, info)      # <- adapter
      ├── check_preconditions(obs)
      ├── detect_progress(obs_before, obs_after)
      └── verify_postconditions(...)

Тест НЕ требует, чтобы progress/skill_contracts понимали WorldState напрямую.
Он запрещает ДРУГОЕ: незаметную потерю факта при переходе через adapter.

Главный инвариант (ловит повторение бага inv_by_id/inventory_by_id):

    canonical ws содержит факт X
    raw info НЕ содержит X
            -> encode_observation(ws, {}) обязан сохранить X

Именно так heal «работал» до 829822d10: факт жил только в raw info из моста,
и любой путь без мостового поля терял навык целиком.

Список проверяемых полей взят из фактических чтений skill_contracts.py:
  obs.*   craftable_now inventory player quest target world
  inv.*   buy_item_available buy_item_price equippable_item free_slots
          items junk_count missing_tool
  world.* corpse_distance corpses gather_nodes nearby_mobs node_distance
          quest_available quest_givers vendor_distance vendors
  quest.* giver_distance ready
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observation import encode_observation
from world_state import build_world_state


def rich_snapshot():
    """Снапшот, в котором ЕСТЬ каждый факт, читаемый контрактами.

    Все id предметов и quality — реальные, из woc-game/src/sim/content/items.ts.
    """
    return {
        "player": {"hp": 60, "maxHp": 100, "level": 5, "dead": False},
        "player_pos": [10.0, 20.0],
        "player_class": "mage",
        "mana": 80, "maxMana": 100,
        "abilities": [
            {"id": "frostbolt", "ready": True, "cost": 25, "range": 30},
            {"id": "fireball", "ready": True, "cost": 30, "range": 30},
        ],
        "nearby": [
            # слабый моб рядом
            {"id": 11, "kind": "mob", "type": "mob", "name": "Forest Wolf",
             "templateId": "forest_wolf", "hp": 30, "maxHp": 30,
             "x": 13.0, "z": 20.0, "dead": False, "lootable": False,
             "hostile": True},
            # труп моба (loot-цель)
            {"id": 12, "kind": "mob", "type": "mob", "name": "Dead Wolf",
             "templateId": "forest_wolf", "hp": 0, "maxHp": 30,
             "x": 12.0, "z": 21.0, "dead": True, "lootable": True,
             "componentTags": ["hide"]},
            # узел добычи
            {"id": 13, "kind": "node", "name": "Copper Vein",
             "nodeType": "mining", "x": 14.0, "z": 20.0},
            # вендор
            {"id": 14, "kind": "npc", "name": "Trader",
             "vendorItems": [{"itemId": "handaxe", "price": 20}],
             "x": 11.0, "z": 20.0},
            # квестовый гивер
            {"id": 15, "kind": "npc", "name": "Elder", "questGiver": True,
             "questIds": ["q_wolves"], "x": 16.0, "z": 20.0},
        ],
        "inventory": [
            {"itemId": "rough_hide", "count": 2, "quality": "common"},
            {"itemId": "tangled_weed", "count": 3, "quality": "poor"},
            {"itemId": "handaxe", "count": 1, "quality": "common"},
        ],
        "inventory_by_id": {"rough_hide": 2, "tangled_weed": 3, "handaxe": 1},
        "equipment": {"mainHand": "rusty_axe"},
        "vendor_offers": {"npcId": 14,
                          "items": [{"itemId": "handaxe", "price": 20}]},
        "quests": {
            "active": [{"id": "q_wolves", "state": "active",
                        "objectives": [{"type": "kill",
                                        "targetMobId": "forest_wolf",
                                        "current": 3, "required": 8}],
                        "turnInNpc": {"x": 16.0, "z": 20.0}}],
            "ready": [], "done": [],
        },
        "quests_done": 0, "kills": 3, "deaths": 1, "copper": 150,
        "in_combat": False, "bagCapacity": 16,
    }


def facts_of(obs):
    """Плоская выжимка фактов observation, которые читают контракты."""
    inv = obs.get("inventory") or {}
    world = obs.get("world") or {}
    quest = obs.get("quest") or {}
    player = obs.get("player") or {}
    return {
        "inv.items": inv.get("items"),
        "inv.equipment": inv.get("equipment"),
        "inv.junk_count": inv.get("junk_count"),
        "inv.free_slots": inv.get("free_slots"),
        "inv.missing_tool": inv.get("missing_tool"),
        "world.nearby_mobs": world.get("nearby_mobs"),
        "world.corpses": world.get("corpses"),
        "world.gather_nodes": world.get("gather_nodes"),
        "world.vendors": world.get("vendors"),
        "world.quest_givers": world.get("quest_givers"),
        "quest.next_objective": quest.get("next_objective"),
        "player.mana": player.get("mana"),
        "player.level": player.get("level"),
    }


class TestInventoryFactsSurvive(unittest.TestCase):
    """Инвентарные факты обязаны переживать переход (это уже работает)."""

    def setUp(self):
        self.snap = rich_snapshot()
        self.ws = build_world_state(self.snap)

    def test_items_survive_without_raw_info(self):
        obs = encode_observation(self.ws, {})
        self.assertEqual(
            (obs.get("inventory") or {}).get("items"),
            {"rough_hide": 2, "tangled_weed": 3, "handaxe": 1},
            "inventory.items потерян при пустом raw info — ровно так heal "
            "жил только благодаря мосту (баг inv_by_id/inventory_by_id)",
        )

    def test_equipment_survives_without_raw_info(self):
        obs = encode_observation(self.ws, {})
        self.assertEqual(
            (obs.get("inventory") or {}).get("equipment"),
            {"mainHand": "rusty_axe"},
            "equipment потерян — контракт equip -> equipment_changed ослепнет",
        )

    def test_junk_count_survives_without_raw_info(self):
        obs = encode_observation(self.ws, {})
        self.assertEqual(
            (obs.get("inventory") or {}).get("junk_count"), 1,
            "junk_count потерян — sell_junk заблокируется (см. P0.1)",
        )


class TestWorldEntityFactsSurvive(unittest.TestCase):
    """Сущности мира обязаны переживать переход так же, как инвентарь.

    Замер на 829822d10: с raw info все пять фактов = 1, без raw info = 0.
    Значит adapter берёт сущности ТОЛЬКО из info, хотя canonical ws их несёт
    (ws["world"]["nearby_mobs"] / gather_nodes / vendors). Это та же
    конструкция, что дала баг heal: факт есть в WS, но теряется на границе.
    """

    def setUp(self):
        self.snap = rich_snapshot()
        self.ws = build_world_state(self.snap)
        self.obs_full = encode_observation(self.ws, self.snap)
        self.obs_bare = encode_observation(self.ws, {})

    def _count(self, obs, key):
        v = (obs.get("world") or {}).get(key)
        if isinstance(v, (list, tuple)):
            return len(v)
        return int(v or 0)

    def test_nearby_mobs_survive(self):
        self.assertEqual(self._count(self.obs_full, "nearby_mobs"), 1,
                         "предусловие: с raw info моб виден")
        self.assertEqual(
            self._count(self.obs_bare, "nearby_mobs"), 1,
            "моб есть в canonical ws, но исчез без raw info -> farm станет "
            "недоступен на любом пути, который не тащит info из моста",
        )

    def test_corpses_survive(self):
        self.assertEqual(self._count(self.obs_full, "corpses"), 1)
        self.assertEqual(
            self._count(self.obs_bare, "corpses"), 1,
            "труп потерян -> loot заблокирован (повтор истории с P0.8)",
        )

    def test_gather_nodes_survive(self):
        self.assertEqual(self._count(self.obs_full, "gather_nodes"), 1)
        self.assertEqual(
            self._count(self.obs_bare, "gather_nodes"), 1,
            "узел добычи потерян -> gather заблокирован",
        )

    def test_vendors_survive(self):
        self.assertEqual(self._count(self.obs_full, "vendors"), 1)
        self.assertEqual(
            self._count(self.obs_bare, "vendors"), 1,
            "вендор потерян -> buy и sell_junk заблокированы",
        )

    def test_quest_givers_survive(self):
        self.assertEqual(self._count(self.obs_full, "quest_givers"), 1)
        self.assertEqual(
            self._count(self.obs_bare, "quest_givers"), 1,
            "гивер потерян -> accept_quest/turn_in_quest заблокированы",
        )


class TestQuestFactsSurvive(unittest.TestCase):
    """Квестовая цель обязана переживать переход."""

    def setUp(self):
        self.snap = rich_snapshot()
        self.ws = build_world_state(self.snap)

    def test_next_objective_survives(self):
        nxt = (encode_observation(self.ws, self.snap).get("quest")
               or {}).get("next_objective")
        self.assertIsNotNone(nxt, "предусловие: цель видна с raw info")
        bare = (encode_observation(self.ws, {}).get("quest")
                or {}).get("next_objective")
        self.assertIsNotNone(
            bare,
            "next_objective потерян без raw info -> planner не увидит цель "
            "и агент перестанет доводить квесты",
        )
        self.assertEqual(bare.get("target_mob_id"), "forest_wolf")
        self.assertEqual(bare.get("required"), 8)


class TestPlayerFactsSurvive(unittest.TestCase):
    """Игрок: уровень и мана — вход в классовые предикаты."""

    def setUp(self):
        self.snap = rich_snapshot()
        self.ws = build_world_state(self.snap)

    def test_level_survives(self):
        obs = encode_observation(self.ws, {})
        self.assertEqual(
            (obs.get("player") or {}).get("level"), 5,
            "level сброшен в 1 без raw info, хотя ws.player_level=5",
        )

    def test_mana_survives(self):
        obs = encode_observation(self.ws, self.snap)
        self.assertEqual(
            (obs.get("player") or {}).get("mana"), 80,
            "мана=%r при snapshot mana=80 — классовые спеллы мага "
            "не получат ресурс" % ((obs.get("player") or {}).get("mana"),),
        )


class TestNoSilentDrop(unittest.TestCase):
    """Обобщение: ни один факт не должен молча исчезать на границе."""

    def test_no_fact_present_with_info_disappears_without_it(self):
        snap = rich_snapshot()
        ws = build_world_state(snap)
        full = facts_of(encode_observation(ws, snap))
        bare = facts_of(encode_observation(ws, {}))

        def truthy(v):
            if isinstance(v, (list, tuple, dict)):
                return len(v) > 0
            return bool(v)

        lost = sorted(k for k in full
                      if truthy(full[k]) and not truthy(bare[k]))
        self.assertEqual(
            lost, [],
            "Факты, живущие только в raw info: %s. Каждый — потенциальный "
            "мёртвый навык на любом пути, где info неполон (recovery, "
            "planner, replay)." % (lost,),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

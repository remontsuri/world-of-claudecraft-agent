"""P0.10 — inventory_by_id vs inv_by_id: имя поля разъехалось между слоями.

Найдено при systematic-debugging пяти падавших тестов (Phase 1).

Root cause: policy._has_healing() читает `inventory_by_id`, а world_state
кладёт тот же словарь под именем `inv_by_id`:

    ws["inv_by_id"]       = {"minor_healing_potion": 2}   <- данные ЗДЕСЬ
    ws["inventory_by_id"] = None                          <- читает _has_healing
    _has_healing(info, ws) -> False                       -> "лечиться нечем"

Сейчас heal работает ТОЛЬКО потому, что мост (snapshot.cjs) кладёт
`inventory_by_id` прямо в info. Любой вызов, где info без этого поля —
внутренний планировщик, recovery-ветка, replay, тест — теряет heal
полностью. Та же болезнь, что P0.1 (junk): разъехавшееся имя поля
превращает предикат в вечный False, и навык блокируется навсегда.

Тесты идут ОТ world_state, а не от info: это и есть проверка границы
canonical -> consumers.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = {
    "player": {"hp": 60, "maxHp": 100, "dead": False},
    "player_pos": [0.0, 0.0],
    "player_class": "warrior",
    "nearby": [],
    "quests": {"active": [], "ready": [], "done": []},
    "quests_done": 0, "kills": 0, "deaths": 0, "copper": 50,
    "in_combat": False, "bagCapacity": 16,
}


def _snap(inventory):
    snap = dict(BASE)
    snap["inventory"] = list(inventory)
    return snap


class TestByIdFieldName(unittest.TestCase):
    """Canonical WorldState обязан отдавать инвентарь по стабильному имени."""

    def test_world_state_exposes_inventory_by_id(self):
        """Имя, которое читают потребители, должно существовать в ws."""
        from world_state import build_world_state

        ws = build_world_state(_snap(
            [{"itemId": "minor_healing_potion", "count": 2,
              "quality": "common"}]))
        got = ws.get("inventory_by_id")
        self.assertIsInstance(
            got, dict,
            "ws['inventory_by_id'] отсутствует (%r). Данные лежат в "
            "ws['inv_by_id']=%r — потребители читают первое имя, "
            "world_state пишет второе."
            % (got, ws.get("inv_by_id")),
        )
        self.assertEqual(got.get("minor_healing_potion"), 2)

    def test_both_names_agree(self):
        """Пока живут оба имени, они обязаны совпадать, а не расходиться."""
        from world_state import build_world_state

        ws = build_world_state(_snap(
            [{"itemId": "rough_hide", "count": 3, "quality": "common"}]))
        self.assertEqual(
            ws.get("inventory_by_id"), ws.get("inv_by_id"),
            "два имени одного словаря разошлись — ровно так ломается "
            "предикат, который читает 'не то' имя",
        )


class TestHasHealingFromCanonicalState(unittest.TestCase):
    """_has_healing обязан работать от canonical ws без помощи моста."""

    def test_healing_detected_without_bridge_field(self):
        from policy import _has_healing
        from world_state import build_world_state

        snap = _snap([{"itemId": "minor_healing_potion", "count": 2,
                       "quality": "common"}])
        snap.pop("inventory_by_id", None)   # мост поле НЕ положил
        ws = build_world_state(snap)
        self.assertTrue(
            _has_healing(snap, ws),
            "зелье в сумке есть, но _has_healing=False, потому что читается "
            "имя, которого в ws нет. Убери поле из моста — heal умрёт "
            "полностью, как sell_junk в P0.1",
        )

    def test_no_healing_when_bag_has_only_crafting_material(self):
        """Обратная сторона: сырьё профессий лечением НЕ является."""
        from policy import _has_healing
        from world_state import build_world_state

        snap = _snap([{"itemId": "rough_hide", "count": 5, "quality": "common"},
                      {"itemId": "curved_tusk", "count": 1, "quality": "common"}])
        ws = build_world_state(snap)
        self.assertFalse(
            _has_healing(snap, ws),
            "rough_hide/curved_tusk — сырьё, heal на них no-op",
        )

    def test_empty_bag_has_no_healing(self):
        from policy import _has_healing
        from world_state import build_world_state

        snap = _snap([])
        ws = build_world_state(snap)
        self.assertFalse(_has_healing(snap, ws),
                         "пустая сумка — лечиться нечем (fail-closed)")

    def test_heal_is_offered_when_hurt_and_potion_present(self):
        """Сквозная проверка: раненый + зелье -> heal среди кандидатов."""
        from memory import ExperienceStore
        from policy import GoalManager

        gm = GoalManager(ExperienceStore(), reflection_hints={})
        snap = _snap([{"itemId": "minor_healing_potion", "count": 2,
                       "quality": "common"}])
        snap.pop("inventory_by_id", None)
        ws = gm._world_state(snap)
        cands = gm._candidates(snap, ws, goal="DO_OBJECTIVE")
        self.assertIn(
            "heal", cands,
            "hp=60/100 и зелье в сумке, а heal не предложен: %r" % (cands,),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

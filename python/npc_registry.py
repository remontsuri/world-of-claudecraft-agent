"""npc_registry.py — Canonical NPC registry.

P0-A: единый runtime слой для NPC, объединяющий:
  - worldContent.npcs (static content)
  - sim.entities (runtime entities)
  - WorldMemory (persisted knowledge)
  - snapshot (live bridge data)

Приоритет источников:
  runtime entity position > worldContent static position > memory > unknown

Критически важно: unknown position ≠ NPC absent.
"""

from typing import Any, Dict, List, Optional


class NpcRegistry:
    """Canonical NPC registry — единый источник истины об NPC."""

    def __init__(self):
        self._npcs: Dict[str, Dict[str, Any]] = {}

    def reset(self):
        self._npcs.clear()

    def update_from_world_content(self, npcs: Dict[str, Any]):
        """Обновить из worldContent.npcs (static content)."""
        for npc_id, npc_def in npcs.items():
            if not isinstance(npc_def, dict):
                continue
            existing = self._npcs.get(npc_id) or {}
            existing.update({
                "id": npc_id,
                "name": npc_def.get("name") or existing.get("name"),
                "template_id": npc_def.get("templateId") or npc_id,
                "quest_ids": npc_def.get("questIds") or existing.get("quest_ids", []),
                "vendor_items": npc_def.get("vendorItems") or existing.get("vendor_items", []),
                "roles": self._roles_from_def(npc_def),
                "source": "world_content",
            })
            # Обновляем позицию только если она валидна
            pos = npc_def.get("pos")
            if pos and pos.get("x") is not None:
                existing["x"] = pos["x"]
                existing["z"] = pos["z"]
            self._npcs[npc_id] = existing

    def update_from_runtime_entities(self, entities: List[Dict[str, Any]]):
        """Обновить из sim.entities (runtime) — высший приоритет позиции."""
        for e in entities:
            if not isinstance(e, dict):
                continue
            template_id = e.get("templateId") or e.get("id")
            if not template_id:
                continue
            existing = self._npcs.get(template_id) or {}
            # Runtime entity имеет приоритет по позиции
            if e.get("pos") and e["pos"].get("x") is not None:
                existing["x"] = e["pos"]["x"]
                existing["z"] = e["pos"]["z"]
                existing["source"] = "runtime_entity"
            # Обновляем признаки, если их ещё нет
            if not existing.get("name") and e.get("name"):
                existing["name"] = e["name"]
            if not existing.get("template_id"):
                existing["template_id"] = template_id
            if e.get("questIds"):
                existing["quest_ids"] = e["questIds"]
            if e.get("vendorItems"):
                existing["vendor_items"] = e["vendorItems"]
            self._npcs[template_id] = existing

    def update_from_memory(self, memory: Any):
        """Обновить из WorldMemory (persisted) — низший приоритет."""
        if memory is None:
            return
        # Giver positions
        for quest_id, rec in (memory.givers or {}).items():
            if not isinstance(rec, dict):
                continue
            giver_id = rec.get("giver_id")
            giver_pos = rec.get("giver_pos")
            if giver_id and giver_pos and giver_pos.get("x") is not None:
                existing = self._npcs.get(giver_id) or {}
                if "x" not in existing:  # Не перезаписываем более приоритетные
                    existing["x"] = giver_pos["x"]
                    existing["z"] = giver_pos["z"]
                    existing["source"] = "memory"
                if not existing.get("name"):
                    existing["name"] = rec.get("name")
                self._npcs[giver_id] = existing

    def update_from_snapshot(self, nearby: List[Dict[str, Any]]):
        """Обновить из snapshot (live bridge data) — средний приоритет."""
        for e in nearby:
            if not isinstance(e, dict):
                continue
            kind = e.get("kind") or e.get("type")
            if kind != "npc":
                continue
            npc_id = e.get("id") or e.get("templateId")
            if not npc_id:
                continue
            existing = self._npcs.get(npc_id) or {}
            # Позиция из snapshot — приоритет выше memory, но ниже runtime
            if e.get("x") is not None:
                existing["x"] = e["x"]
                existing["z"] = e["z"]
                existing["source"] = "snapshot"
            if not existing.get("name") and e.get("name"):
                existing["name"] = e["name"]
            if e.get("questIds"):
                existing["quest_ids"] = e["questIds"]
            if e.get("vendorItems"):
                existing["vendor_items"] = e["vendorItems"]
            self._npcs[npc_id] = existing

    def get(self, npc_id: str) -> Optional[Dict[str, Any]]:
        """Получить NPC по ID."""
        return self._npcs.get(npc_id)

    def get_by_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Получить NPC по templateId."""
        # Сначала прямой поиск
        if template_id in self._npcs:
            return self._npcs[template_id]
        # Поиск по template_id
        for npc in self._npcs.values():
            if npc.get("template_id") == template_id:
                return npc
        return None

    def find_giver_for_quest(self, quest_id: str) -> Optional[Dict[str, Any]]:
        """Найти гивера для квеста."""
        for npc in self._npcs.values():
            if quest_id in (npc.get("quest_ids") or []):
                return npc
        return None

    def get_npc_position(self, npc_id: str) -> Optional[Dict[str, float]]:
        """Получить позицию NPC по ID."""
        npc = self.get(npc_id) or self.get_by_template(npc_id)
        if npc and npc.get("x") is not None:
            return {"x": npc["x"], "z": npc["z"]}
        return None

    def get_giver_position_for_quest(self, quest_id: str) -> Optional[Dict[str, float]]:
        """Получить позицию гивера для квеста."""
        giver = self.find_giver_for_quest(quest_id)
        if giver and giver.get("x") is not None:
            return {"x": giver["x"], "z": giver["z"]}
        return None

    def find_all_givers(self) -> List[Dict[str, Any]]:
        """Все гиверы (NPC с quest_ids)."""
        return [n for n in self._npcs.values() if n.get("quest_ids")]

    def find_all_vendors(self) -> List[Dict[str, Any]]:
        """Все вендоры."""
        return [n for n in self._npcs.values() if n.get("vendor_items")]

    def all(self) -> Dict[str, Dict[str, Any]]:
        """Все NPC."""
        return dict(self._npcs)

    @staticmethod
    def _roles_from_def(npc_def: Dict[str, Any]) -> List[str]:
        """Извлечь роли из определения NPC."""
        roles = []
        if npc_def.get("questIds"):
            roles.append("giver")
        if npc_def.get("vendorItems"):
            roles.append("vendor")
        if npc_def.get("banker"):
            roles.append("banker")
        if npc_def.get("market"):
            roles.append("auctioneer")
        return roles

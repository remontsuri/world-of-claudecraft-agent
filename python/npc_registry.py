"""npc_registry.py — Canonical NPC registry.

P0-A: единый runtime слой для NPC, объединяющий:
  - worldContent.npcs (static content)
  - sim.entities (runtime entities)
  - WorldMemory (persisted knowledge)
  - snapshot (live bridge data)

Приоритет источников (FIX #2, 2026-08-27):
  runtime_entity > world_content > snapshot > memory

FIX #3 (2026-08-27): canonical npc_id отдельный от entity_id/template_id.
  Ключ реестра = npc_id (строковый, из worldContent или templateId).
  entity_id = числовой id из runtime (для bridge actions).
  template_id = строковый templateId (для сопоставления с quest.giverNpcId).

Критически важно: unknown position ≠ NPC absent.
"""

from typing import Any, Dict, List, Optional


# Source priority: higher = more authoritative (FIX #2)
SOURCE_PRIORITY = {
    "memory": 0,
    "snapshot": 1,
    "world_content": 2,
    "runtime_entity": 3,
}


class NpcRegistry:
    """Canonical NPC registry — единый источник истины об NPC."""

    def __init__(self):
        self._npcs: Dict[str, Dict[str, Any]] = {}

    def reset(self):
        self._npcs.clear()

    def _resolve_key(self, npc_id: str = None, template_id: str = None,
                     name: str = None, entity_id: int = None) -> Optional[str]:
        """Resolve canonical registry key.

        Priority: npc_id > template_id > name. Never use entity_id as key
        (FIX #3: entity_id is numeric, npc_id is canonical string).
        """
        if npc_id and isinstance(npc_id, str):
            return npc_id
        if template_id and isinstance(template_id, str):
            return template_id
        if name and isinstance(name, str):
            return name
        return None

    def _should_update_position(self, existing: Dict[str, Any], new_source: str) -> bool:
        """Check if new source can update position (FIX #2).

        If no position exists yet, any source can set it.
        If position exists, only higher-or-equal priority can override.
        """
        if existing.get("x") is None:
            return True
        existing_priority = SOURCE_PRIORITY.get(existing.get("source", ""), -1)
        new_priority = SOURCE_PRIORITY.get(new_source, -1)
        return new_priority >= existing_priority

    def update_from_world_content(self, npcs: Dict[str, Any]):
        """Обновить из worldContent.npcs (static content)."""
        for npc_id, npc_def in npcs.items():
            if not isinstance(npc_def, dict):
                continue
            existing = self._npcs.get(npc_id) or {}
            existing.update({
                "npc_id": npc_id,
                "name": npc_def.get("name") or existing.get("name"),
                "template_id": npc_def.get("templateId") or npc_id,
                "quest_ids": npc_def.get("questIds") or existing.get("quest_ids", []),
                "vendor_items": npc_def.get("vendorItems") or existing.get("vendor_items", []),
                "roles": self._roles_from_def(npc_def),
                "source": "world_content",
            })
            # Обновляем позицию только если источник имеет приоритет (FIX #2)
            pos = npc_def.get("pos")
            if pos and pos.get("x") is not None:
                if self._should_update_position(existing, "world_content"):
                    existing["x"] = pos["x"]
                    existing["z"] = pos["z"]
            self._npcs[npc_id] = existing

    def update_from_runtime_entities(self, entities: List[Dict[str, Any]]):
        """Обновить из sim.entities (runtime) — высший приоритет позиции.

        FIX #3: ключ = templateId (строковый), НЕ entity.id (числовой).
        Сохраняем entity_id отдельно для bridge actions.
        """
        for e in entities:
            if not isinstance(e, dict):
                continue
            # FIX #3: canonical key is templateId, not entity.id
            template_id = e.get("templateId")
            npc_id = self._resolve_key(
                template_id=template_id,
                name=e.get("name"),
            )
            if not npc_id:
                continue
            existing = self._npcs.get(npc_id) or {}
            # Runtime entity имеет приоритет по позиции (FIX #2)
            if e.get("pos") and e["pos"].get("x") is not None:
                if self._should_update_position(existing, "runtime_entity"):
                    existing["x"] = e["pos"]["x"]
                    existing["z"] = e["pos"]["z"]
                    existing["source"] = "runtime_entity"
            # Сохраняем entity_id отдельно (для bridge actions)
            if e.get("id") is not None:
                existing["entity_id"] = e["id"]
            # Обновляем признаки, если их ещё нет
            if not existing.get("name") and e.get("name"):
                existing["name"] = e["name"]
            if not existing.get("npc_id"):
                existing["npc_id"] = npc_id
            if not existing.get("template_id") and template_id:
                existing["template_id"] = template_id
            if e.get("questIds"):
                existing["quest_ids"] = e["questIds"]
            if e.get("vendorItems"):
                existing["vendor_items"] = e["vendorItems"]
            self._npcs[npc_id] = existing

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
                # FIX #2: не перезаписываем более приоритетные источники
                if self._should_update_position(existing, "memory"):
                    existing["x"] = giver_pos["x"]
                    existing["z"] = giver_pos["z"]
                    existing["source"] = "memory"
                if not existing.get("name"):
                    existing["name"] = rec.get("name")
                if not existing.get("npc_id"):
                    existing["npc_id"] = giver_id
                self._npcs[giver_id] = existing

    def update_from_snapshot(self, nearby: List[Dict[str, Any]]):
        """Обновить из snapshot (live bridge data) — средний приоритет.

        FIX #3: ключ = templateId (строковый), НЕ entity.id (числовой).
        """
        for e in nearby:
            if not isinstance(e, dict):
                continue
            kind = e.get("kind") or e.get("type")
            if kind != "npc":
                continue
            # FIX #3: canonical key is templateId, not entity.id
            npc_id = self._resolve_key(
                template_id=e.get("templateId"),
                name=e.get("name"),
            )
            if not npc_id:
                continue
            existing = self._npcs.get(npc_id) or {}
            # FIX #2: позиция из snapshot — приоритет выше memory, но ниже runtime/world_content
            if e.get("x") is not None:
                if self._should_update_position(existing, "snapshot"):
                    existing["x"] = e["x"]
                    existing["z"] = e["z"]
                    existing["source"] = "snapshot"
            # Сохраняем entity_id отдельно (FIX #3)
            if e.get("id") is not None:
                existing["entity_id"] = e["id"]
            if not existing.get("name") and e.get("name"):
                existing["name"] = e["name"]
            if not existing.get("npc_id"):
                existing["npc_id"] = npc_id
            if e.get("questIds"):
                existing["quest_ids"] = e["questIds"]
            if e.get("vendorItems"):
                existing["vendor_items"] = e["vendorItems"]
            self._npcs[npc_id] = existing

    def get(self, npc_id: str) -> Optional[Dict[str, Any]]:
        """Получить NPC по canonical ID."""
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

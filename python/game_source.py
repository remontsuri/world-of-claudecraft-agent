#!/usr/bin/env python3
"""Dynamic game source adapter — reads game data directly from running WoC instance.

This is the authoritative source of truth for the agent. No static JSON files,
no manual copies. All data comes from window.__game via CDP.

Usage:
    from game_source import GameSource
    gs = GameSource()
    gs.connect()
    npcs = gs.get_npcs()
    quests = gs.get_quests()
    mobs = gs.get_mobs()
"""
import json
import threading
import asyncio
import urllib.request
from typing import Any, Dict, List, Optional

try:
    import websockets
except ImportError:
    websockets = None


class GameSource:
    """Connects to running WoC game via CDP and provides live access to game data."""
    
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222", game_url: str = "http://127.0.0.1:5173/"):
        self.cdp_url = cdp_url
        self.game_url = game_url
        self._ws_url = None
        self._connected = False
    
    def connect(self) -> bool:
        """Connect to the game tab via CDP."""
        if websockets is None:
            raise RuntimeError("websockets package required: pip install websockets")
        
        try:
            data = urllib.request.urlopen(f"{self.cdp_url}/json/list").read()
            tabs = json.loads(data)
            for t in tabs:
                if '127.0.0.1:5173' in t.get('url', ''):
                    self._ws_url = t['webSocketDebuggerUrl']
                    break
            
            if not self._ws_url:
                return False
            
            self._connected = True
            return True
        except Exception as e:
            print(f"[GameSource] Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Close CDP connection."""
        self._ws_url = None
        self._connected = False
    
    def _evaluate(self, expr: str, timeout: int = 10) -> Any:
        """Evaluate JS expression in the game tab."""
        if not self._connected or not self._ws_url:
            raise RuntimeError("Not connected to game")
        
        # Run in separate thread to avoid event loop issues
        result = {'value': None, 'error': None}
        
        def run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def async_eval():
                    async with websockets.connect(self._ws_url, max_size=50*1024*1024) as ws:
                        msg_id = hash(expr) % 100000
                        await ws.send(json.dumps({
                            "id": msg_id,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": expr,
                                "returnByValue": True,
                                "awaitPromise": True,
                                "timeout": timeout * 1000,
                            }
                        }))
                        
                        while True:
                            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout + 5))
                            if resp.get("id") == msg_id:
                                res = resp.get("result", {}).get("result", {})
                                if res.get("type") == "undefined":
                                    return None
                                return res.get("value")
                
                result['value'] = loop.run_until_complete(async_eval())
            except Exception as e:
                result['error'] = e
            finally:
                loop.close()
        
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout + 10)
        
        if thread.is_alive():
            raise TimeoutError(f"Evaluation timed out after {timeout}s")
        
        if result['error']:
            raise result['error']
        
        return result['value']
    
    def _get_json(self, expr: str) -> Optional[dict]:
        """Evaluate and parse JSON result."""
        val = self._evaluate(expr)
        if val is None:
            return None
        if isinstance(val, str):
            return json.loads(val)
        return val
    
    # --- NPC ---
    
    def get_npcs(self) -> Dict[str, dict]:
        """Get all NPC definitions from the game."""
        return self._get_json("JSON.stringify(window.__game.sim.worldContent.npcs)") or {}
    
    def get_npc(self, npc_id: str) -> Optional[dict]:
        """Get specific NPC by ID."""
        return self._get_json(f"JSON.stringify(window.__game.sim.worldContent.npcs['{npc_id}'])")
    
    def get_npcs_with_quests(self) -> Dict[str, dict]:
        """Get only NPCs that offer quests."""
        npcs = self.get_npcs()
        return {k: v for k, v in npcs.items() if v.get("questIds")}
    
    def get_quest_givers(self) -> Dict[str, dict]:
        """Get NPCs that are quest givers (alias for get_npcs_with_quests)."""
        return self.get_npcs_with_quests()
    
    # --- Quests ---
    
    def get_quests(self) -> Dict[str, dict]:
        """Get all quest definitions from the game."""
        quests = self._get_json("JSON.stringify(window.__game.sim.worldContent.quests)")
        if quests:
            return quests
        quests = self._get_json("JSON.stringify(window.__game.QUESTS)")
        if quests:
            return quests
        quests = self._get_json("JSON.stringify(window.__game.sim.quests)")
        return quests or {}
    
    def get_quest(self, quest_id: str) -> Optional[dict]:
        """Get specific quest by ID."""
        return self._get_json(f"JSON.stringify(window.__game.sim.worldContent.quests['{quest_id}'])")
    
    def get_quest_log(self) -> Dict[str, dict]:
        """Get player's current quest log."""
        return self._get_json("JSON.stringify(window.__game.sim.questLog)") or {}
    
    def get_quest_state(self, quest_id: str) -> Optional[str]:
        """Get state of a specific quest."""
        return self._evaluate(f"window.__game.sim.questState('{quest_id}')")
    
    # --- Mobs ---
    
    def get_mobs(self) -> Dict[str, dict]:
        """Get all mob templates from the game."""
        return self._get_json("JSON.stringify(window.__game.MOBS)") or {}
    
    def get_mob(self, mob_id: str) -> Optional[dict]:
        """Get specific mob template by ID."""
        return self._get_json(f"JSON.stringify(window.__game.MOBS['{mob_id}'])")
    
    # --- Zones ---
    
    def get_zones(self) -> Dict[str, dict]:
        """Get all zone definitions."""
        return self._get_json("JSON.stringify(window.__game.sim.worldContent.zones)") or {}
    
    def get_zone(self, zone_id: str) -> Optional[dict]:
        """Get specific zone by ID."""
        return self._get_json(f"JSON.stringify(window.__game.sim.worldContent.zones['{zone_id}'])")
    
    # --- Camps (spawn points) ---
    
    def get_camps(self) -> List[dict]:
        """Get all camp/spawn point definitions."""
        return self._get_json("JSON.stringify(window.__game.sim.worldContent.camps)") or []
    
    def get_camps_for_mob(self, mob_id: str) -> List[dict]:
        """Get camps that spawn a specific mob."""
        camps = self.get_camps()
        return [c for c in camps if c.get("mobId") == mob_id]
    
    # --- Items ---
    
    def get_items(self) -> Dict[str, dict]:
        """Get all item definitions."""
        items = self._get_json("JSON.stringify(window.__game.ITEMS)")
        if items:
            return items
        items = self._get_json("JSON.stringify(window.__game.sim.worldContent.items)")
        return items or {}
    
    # --- Abilities ---
    
    def get_abilities(self) -> Dict[str, dict]:
        """Get all ability definitions."""
        abilities = self._get_json("JSON.stringify(window.__game.ABILITIES)")
        if abilities:
            return abilities
        abilities = self._get_json("JSON.stringify(window.__game.sim.worldContent.abilities)")
        return abilities or {}
    
    # --- Classes ---
    
    def get_classes(self) -> Dict[str, dict]:
        """Get all class definitions."""
        classes = self._get_json("JSON.stringify(window.__game.CLASSES)")
        if classes:
            return classes
        classes = self._get_json("JSON.stringify(window.__game.sim.worldContent.classes)")
        return classes or {}
    
    # --- Gather Nodes ---
    
    def get_gather_nodes(self) -> Dict[str, dict]:
        """Get all gather node definitions."""
        nodes = self._get_json("JSON.stringify(window.__game.sim.worldContent.gatherNodes)")
        if nodes:
            return nodes
        nodes = self._get_json("JSON.stringify(window.__game.GATHER_NODES)")
        return nodes or {}
    
    # --- Services (stations, etc.) ---
    
    def get_services(self) -> dict:
        """Get world services (stations, etc.)."""
        return self._get_json("JSON.stringify(window.__game.sim.worldContent.services)") or {}
    
    # --- Player ---
    
    def get_player_pos(self) -> Optional[List[float]]:
        """Get current player position [x, z]."""
        return self._evaluate("[window.__game.sim.player.pos.x, window.__game.sim.player.pos.z]")
    
    def get_player_facing(self) -> Optional[float]:
        """Get current player facing."""
        return self._evaluate("window.__game.sim.player.facing")
    
    def get_player_hp(self) -> Optional[float]:
        """Get current player HP fraction."""
        return self._evaluate("window.__game.sim.player.hpFrac")
    
    def is_player_dead(self) -> Optional[bool]:
        """Check if player is dead."""
        return self._evaluate("window.__game.sim.player.dead")
    
    # --- Entities ---
    
    def get_nearby_entities(self, radius: float = 50.0) -> List[dict]:
        """Get entities within radius of player."""
        expr = f"""
        (() => {{
            const sim = window.__game.sim;
            const p = sim.player;
            const ents = [];
            for (const e of sim.entities.values()) {{
                if (!e || !e.pos) continue;
                const dx = e.pos.x - p.pos.x;
                const dz = e.pos.z - p.pos.z;
                const d = Math.sqrt(dx*dx + dz*dz);
                if (d <= {radius}) {{
                    ents.push({{
                        id: e.id,
                        kind: e.kind,
                        type: e.type,
                        name: e.name,
                        x: e.pos.x,
                        z: e.pos.z,
                        dist: Math.round(d * 10) / 10,
                        hpFrac: e.hpFrac,
                        dead: e.dead,
                        templateId: e.templateId,
                        questIds: e.questIds || e.questId || null,
                        vendor: e.kind === 'npc' && Array.isArray(e.vendorItems) && e.vendorItems.length > 0
                    }});
                }}
            }}
            return JSON.stringify(ents);
        }})()
        """
        val = self._evaluate(expr)
        return json.loads(val) if val else []
    
    def get_nearby_npcs(self, radius: float = 50.0) -> List[dict]:
        """Get NPCs within radius of player."""
        nearby = self.get_nearby_entities(radius)
        return [e for e in nearby if e.get("kind") == "npc"]
    
    def get_nearby_mobs(self, radius: float = 50.0) -> List[dict]:
        """Get mobs within radius of player."""
        nearby = self.get_nearby_entities(radius)
        return [e for e in nearby if e.get("kind") == "mob"]
    
    # --- Utility ---
    
    def get_giver_for_quest(self, quest_id: str) -> Optional[dict]:
        """Find the NPC that gives a specific quest."""
        npcs = self.get_npcs_with_quests()
        for npc_id, npc in npcs.items():
            quest_ids = npc.get("questIds", [])
            if quest_id in quest_ids:
                return {"id": npc_id, **npc}
        return None

    def get_giver_pos_for_quest(self, quest_id: str) -> Optional[tuple]:
        """Return (x, z) for the NPC that gives a specific quest, or None."""
        npc = self.get_giver_for_quest(quest_id)
        if npc and npc.get("pos"):
            return (npc["pos"].get("x"), npc["pos"].get("z"))
        return None
    
    def get_quest_objectives(self, quest_id: str) -> Optional[list]:
        """Get objectives for a specific quest."""
        quest = self.get_quest(quest_id)
        if quest:
            return quest.get("objectives") or quest.get("objective")
        return None


# Singleton instance
_game_source: Optional[GameSource] = None


def get_game_source() -> GameSource:
    """Get or create the singleton GameSource instance."""
    global _game_source
    if _game_source is None:
        _game_source = GameSource()
    return _game_source


if __name__ == "__main__":
    # Quick test
    gs = GameSource()
    if gs.connect():
        print("[+] Connected to game")
        
        npcs = gs.get_npcs()
        print(f"NPCs: {len(npcs)}")
        
        quest_givers = gs.get_npcs_with_quests()
        print(f"Quest Givers: {len(quest_givers)}")
        
        mobs = gs.get_mobs()
        print(f"Mobs: {len(mobs)}")
        
        zones = gs.get_zones()
        print(f"Zones: {len(zones)}")
        
        camps = gs.get_camps()
        print(f"Camps: {len(camps)}")
        
        player_pos = gs.get_player_pos()
        print(f"Player pos: {player_pos}")
        
        nearby = gs.get_nearby_npcs(30)
        print(f"Nearby NPCs: {len(nearby)}")
        for npc in nearby[:5]:
            print(f"  - {npc.get('name')} at {npc.get('x')},{npc.get('z')} (dist={npc.get('dist')})")
        
        gs.disconnect()
    else:
        print("[-] Failed to connect")

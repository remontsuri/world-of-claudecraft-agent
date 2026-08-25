"""browser_env.py — online WoC environment adapter for the Python Agent.

Implements the SAME interface HierarchicalWoWEnv exposes to Agent/quest_skill:
  - reset(seed)              -> sets self._last_info
  - step(idx)                -> apply one low-level skill action, refresh _last_info
  - _last_info               -> flat info dict (build_world_state-compatible)
  - _navigate_to_coord(x,z)  -> walk to a world coord (used by return_to_giver)
  - close()

The actual world is the LIVE browser tab driven by browser_bridge.cjs over CDP.
This module is pure I/O: it posts actions to the bridge and reads observations
back. All learning (policy/memory/reward) stays in agent.py / memory.py / reward.py.

No reward logic, no Sim edits, no PPO here.
"""

import json
import socket
from urllib.parse import urlparse

BRIDGE_URL = "http://127.0.0.1:8791"


class BrowserBridgeError(RuntimeError):
    """Infrastructure failure: the bridge/CDP/HTTP transport is down or rejected
    the request. This is NOT a game outcome and must NOT be confused with a
    programming error (NameError/KeyError/TypeError in policy/skill/reward).
    Agent catches this as ENV_ERROR (no false lesson, wait for recovery); any
    other Exception is a real bug and must crash loudly."""

# skill indices MUST match hierarchical_env.SKILLS order so Agent's SKILL_INDEX
# mapping stays valid:
# 0 farm, 1 loot, 2 accept_quest, 3 turn_in_quest, 4 sell_junk,
# 5 gather, 6 craft, 7 heal, 8 equip, 9 buy
ACT_FORWARD = 1
ACT_TURN_LEFT = 3
ACT_TURN_RIGHT = 4


class BrowserEnv:
    """Online world proxy. One instance = one live character session."""

    def __init__(self, player_class: str = "warrior", max_steps: int = 100000, seed: int = 0):
        self.player_class = player_class
        self.max_steps = max_steps
        self.seed = seed
        self._last_info = None
        self._step = 0
        self.last_giver = None  # surfaced by bridge on accept_quest (see step())
        self.base = BrowserBase(self)  # quest_skill uses env.base.step(ACT_FORWARD) for explore
        # prime: fetch an initial observation so _last_info is never None
        self._last_info = self._require({"action": "snapshot"}).get("info", {})

    # ---- bridge I/O ----
    def _post(self, payload: dict, timeout: float = 30.0) -> dict:
        """Bounded one-shot HTTP RPC. No background reader thread is used.

        The bridge sends Content-Length + Connection: close, so the body can be
        framed without waiting for an ambiguous EOF. select() enforces a monotonic
        deadline around every blocking read, preventing the old reader-thread hang.
        """
        import select
        import time
        parsed = urlparse(BRIDGE_URL)
        host, port = parsed.hostname or "127.0.0.1", parsed.port or 8791
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = (f"POST {parsed.path or '/'} HTTP/1.1\r\n"
               f"Host: {host}:{port}\r\n"
               "Content-Type: application/json\r\n"
               f"Content-Length: {len(data)}\r\n"
               "Connection: close\r\n\r\n").encode("ascii") + data
        sock = None
        deadline = time.monotonic() + float(timeout)
        try:
            sock = socket.create_connection((host, port), timeout=min(5.0, max(0.1, float(timeout))))
            sock.setblocking(False)
            sock.sendall(req)
            buf = bytearray()
            header_end = -1
            content_length = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserBridgeError(f"bridge POST {payload.get('action')} timed out")
                readable, _, _ = select.select([sock], [], [], min(remaining, 1.0))
                if not readable:
                    continue
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > 5_000_000:
                    raise BrowserBridgeError("bridge response exceeds 5MB")
                if header_end < 0:
                    header_end = buf.find(b"\r\n\r\n")
                    if header_end >= 0:
                        headers = bytes(buf[:header_end]).decode("latin-1")
                        for line in headers.split("\r\n"):
                            if line.lower().startswith("content-length:"):
                                try: content_length = int(line.split(":",1)[1].strip())
                                except ValueError: content_length = None
                                break
                if header_end >= 0 and content_length is not None and len(buf)-(header_end+4) >= content_length:
                    break
            if header_end < 0:
                raise BrowserBridgeError(f"bridge POST {payload.get('action')} returned no HTTP headers")
            headers = bytes(buf[:header_end]).decode("latin-1")
            body = bytes(buf[header_end+4:])
            if "transfer-encoding:" in headers.lower() and "chunked" in headers.lower():
                body = self._decode_chunked(body)
            elif content_length is not None:
                if len(body) < content_length:
                    raise BrowserBridgeError(f"bridge POST {payload.get('action')} truncated body {len(body)}/{content_length}")
                body = body[:content_length]
            try:
                return json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise BrowserBridgeError(f"bridge POST {payload.get('action')} invalid JSON: {e}") from e
        except BrowserBridgeError:
            raise
        except (socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as e:
            raise BrowserBridgeError(f"bridge POST {payload.get('action')} failed: {type(e).__name__}: {e}") from e
        finally:
            if sock is not None:
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: sock.close()
                except OSError: pass

    def health(self, timeout: float = 3.0) -> dict:
        """Fetch real bridge health; never use stale game state for recovery."""
        import select
        import time
        parsed = urlparse(BRIDGE_URL)
        host, port = parsed.hostname or "127.0.0.1", parsed.port or 8791
        req = f"GET /health HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n".encode("ascii")
        sock = None
        deadline = time.monotonic() + float(timeout)
        try:
            sock = socket.create_connection((host, port), timeout=min(1.5, max(0.1,float(timeout))))
            sock.setblocking(False)
            sock.sendall(req)
            buf = bytearray(); header_end = -1; content_length = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise BrowserBridgeError("bridge health timeout")
                readable, _, _ = select.select([sock], [], [], min(remaining, 0.5))
                if not readable: continue
                chunk = sock.recv(65536)
                if not chunk: break
                buf.extend(chunk)
                if header_end < 0:
                    header_end = buf.find(b"\r\n\r\n")
                    if header_end >= 0:
                        headers = bytes(buf[:header_end]).decode("latin-1")
                        for line in headers.split("\r\n"):
                            if line.lower().startswith("content-length:"):
                                try: content_length = int(line.split(":",1)[1].strip())
                                except ValueError: content_length = None
                                break
                if header_end >= 0 and content_length is not None and len(buf)-(header_end+4) >= content_length:
                    break
            if header_end < 0: raise BrowserBridgeError("bridge health returned no headers")
            body = bytes(buf[header_end+4:])
            if content_length is not None: body = body[:content_length]
            return json.loads(body.decode("utf-8"))
        except BrowserBridgeError: raise
        except (socket.timeout, TimeoutError, ConnectionError, OSError, ValueError, json.JSONDecodeError) as e:
            raise BrowserBridgeError(f"bridge health failed: {type(e).__name__}: {e}") from e
        finally:
            if sock is not None:
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: sock.close()
                except OSError: pass

    @staticmethod
    def _decode_chunked(body: bytes) -> bytes:
        """Decode a Transfer-Encoding: chunked body into the raw payload."""
        CRLF = bytes([13, 10])
        out = b""
        i = 0
        while i < len(body):
            crlf = body.find(CRLF, i)
            if crlf == -1:
                break
            size_line = body[i:crlf].split(b";")[0].strip()
            try:
                size = int(size_line, 16)
            except ValueError:
                break
            if size == 0:
                break
            start = crlf + 2
            end = start + size
            out += body[start:end]
            i = end + 2
        return out

    def _require(self, payload: dict, timeout: float = 30.0) -> dict:
        """POST and raise BrowserBridgeError on ok:false so the Agent records
        ENV_ERROR (reward 0, memory untouched) instead of learning from an empty
        snapshot. Used by every read/write path — no silent stop()/empty-info
        fallback."""
        resp = self._post(payload, timeout=timeout)
        if not resp.get("ok", False):
            raise BrowserBridgeError(f"bridge {payload.get('action')} failed: {resp.get('error')}")
        return resp

    # ---- gym-style interface used by Agent ----
    def reset(self, seed: int = None):
        if seed is not None:
            self.seed = seed
        # if the character is dead on entry, respawn so the loop can start clean
        resp = self._post({"action": "snapshot"})
        if not resp.get("ok", False):
            raise BrowserBridgeError(f"bridge reset failed: {resp.get('error')}")
        info = resp.get("info", {})
        if info.get("player", {}).get("dead"):
            self._require({"action": "respawn"}, timeout=90.0)
            resp = self._require({"action": "snapshot"})
            if not resp.get("ok", False):
                raise BrowserBridgeError(f"bridge respawn+snapshot failed: {resp.get('error')}")
            info = self._last_info = resp.get("info", {})
        else:
            self._last_info = info
        self._step = 0
        return None, info

    def step(self, idx: int, ctx: dict = None):
        """Apply one skill action (idx). Returns (obs, reward, done, truncated, info)
        like gym, but Agent only uses _last_info + the returned info.

        `ctx` (e.g. {"quest": {"id": "q_fs_..."}}) is forwarded to the bridge so
        accept_quest / turn_in_quest call the real sim.acceptQuest(questId) API
        instead of a bare interact().

        An `ok:false` from the bridge is an infrastructure failure, NOT a game
        outcome — raise so the Agent records ENV_ERROR (reward 0, memory untouched)
        instead of treating the empty `info` as a real world state and learning a
        false lesson.
        """
        payload = {"action": "step", "idx": int(idx)}
        if ctx:
            # For accept_quest the questId MUST be the NPC's own questId (set by
            # policy.decide as ctx["questId"]), NOT ctx["quest"]["id"] (which is
            # the first active quest and may belong to a different NPC). Give
            # ctx["questId"] priority, falling back to the quest object's id.
            q = ctx.get("quest") or {}
            qid = ctx.get("questId") or q.get("id")
            if qid:
                payload["questId"] = qid
            # 2026-08-25 (таргетинг): квестовый моб для farm. Берём ПЕРВУЮ
            # неполную kill-цель активного квеста — policy кладёт её в ctx.
            if ctx.get("targetMobId"):
                payload["targetMobId"] = str(ctx["targetMobId"])
            # giver id (NPC entity id) — the bridge returns its live position so
            # Python can persist it in WorldMemory as the turn-in location.
            npc = ctx.get("npc") or {}
            nid = ctx.get("npcId") or npc.get("id")
            if nid:
                payload["npcId"] = str(nid)
            # economy loop: craft_item carries the chosen recipe id
            if ctx.get("recipeId"):
                payload["recipeId"] = ctx["recipeId"]
        resp = self._post(payload)
        if not resp.get("ok", False):
            raise BrowserBridgeError(f"bridge step failed: {resp.get('error')}")
        info = resp.get("info", {})
        self._last_info = info
        # giver metadata surfaced by the bridge on accept_quest (questId/giverId/
        # giverPos) — Agent persists it in WorldMemory. Stored on the env so the
        # caller can read it after the step without re-parsing the response.
        self.last_giver = resp.get("giver")
        self._step += 1
        done = bool(info.get("player", {}).get("dead"))
        return None, 0.0, done, False, info

    def _navigate_to_coord(self, tx: float, tz: float, max_steps: int = 80, timeout: float = 90.0) -> bool:
        """Walk to (tx,tz). Returns True if arrived. Used by return_to_giver.

        `timeout` must exceed max_steps*0.22s (bridge sleeps TICK_MS per step and
        answers only AFTER the full walk loop — it blocks the HTTP response)."""
        resp = self._require({"action": "navigate", "x": tx, "z": tz, "max_steps": max_steps}, timeout=timeout)
        info = resp.get("info", {})
        self._last_info = info
        return bool(resp.get("arrived"))

    def _raw_move(self, kind: str):
        """Send a single raw movement through the bridge (forward/back/turnLeft/
        turnRight/stop). Used by BrowserBase for explore/ACT_* actions."""
        resp = self._require({"action": "raw_move", "kind": kind})
        info = resp.get("info", {})
        self._last_info = info
        return info

    def respawn(self):
        """Release spirit + resurrect at healer (online-safe glue; does NOT mutate
        the model). Call when the character is dead so the loop can continue.

        Returns (info, revived): `revived` is the bridge's REAL confirmation that
        the player is alive again (dead:false AND hp>0), NOT a blind ok:true. The
        caller must check `revived` and stop the cycle if resurrection failed —
        otherwise the agent farms/loots on a corpse forever (the old bug)."""
        resp = self._require({"action": "respawn"}, timeout=90.0)
        info = resp.get("info", {})
        self._last_info = info
        revived = bool(resp.get("revived", False))
        return info, revived

    def explore_walk(self, steps: int = 10):
        """Sustained exploration: walk toward nearest mob/NPC (or forward) for
        `steps` ticks. Lets the agent actually traverse the world instead of
        jittering in place. Used by Agent for the `explore` skill."""
        resp = self._require({"action": "explore", "steps": steps})
        info = resp.get("info", {})
        self._last_info = info
        return bool(resp.get("arrived"))

    def close(self):
        # bridge (node process) keeps running; nothing to tear down here.
        pass

    # compatibility shims used by some diagnostic scripts / quest_skill
    def base_step(self, idx: int):
        return self.step(idx)


class BrowserBase:
    """Low-level action interface (ACT_* indices) for quest_skill.explore.

    quest_skill calls env.base.step(ACT_FORWARD) — that is a raw movement
    action (ACT_FORWARD=1), NOT a high-level skill. We map ACT_* here so explore
    actually walks forward instead of being interpreted as the 'loot' skill.
    """

    def __init__(self, env: "BrowserEnv"):
        self.env = env

    def step(self, idx: int):
        # ACT_* from hierarchical_env: 0 noop, 1 forward, 2 back, 3 turn_left,
        # 4 turn_right, 6 strafe_right, 8 target_nearest, 9 attack
        if idx == 1:      # forward
            self.env._raw_move("forward")
        elif idx == 2:    # back
            self.env._raw_move("back")
        elif idx == 3:    # turn_left
            self.env._raw_move("turnLeft")
        elif idx == 4:    # turn_right
            self.env._raw_move("turnRight")
        else:
            self.env._raw_move("stop")
        return None, 0.0, False, False, self.env._last_info

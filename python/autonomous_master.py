"""
World of ClaudeCraft — MASTER AUTONOMOUS LEARNER

This is the single entrypoint for the CURRENT agent architecture.

It does not replace the existing modules. Instead it wires the complete stack
already present in the repository into one long-running process:

    browser bridge
          ↓
    BrowserEnv / live snapshot
          ↓
    WorldState + WorldMemory
          ↓
    GoalFSM + Planner
          ↓
    AutonomyLoop
          ↓
    candidate masking / navigation / recovery
          ↓
    learned GoalManager (Q-learning)
          ↓
    Agent skill execution
          ↓
    verifier
          ↓
    reward
          ↓
    ExperienceStore / Replay / reflection
          ↓
       repeat forever

Extra safety added here:
- hard death recovery before another learning action;
- low-HP + combat retreat before the heal decision;
- re-snapshot after recovery/navigation;
- singleton lock;
- durable JSONL telemetry;
- infinite run by default.

IMPORTANT:
This file intentionally reuses the repository's existing Agent, Planner,
AutonomyLoop, GoalFSM, reward, verifier and memory modules. It is therefore
"one file to RUN everything", not a second fork of the learning algorithms.

Put it at:
    D:\\world-of-claudecraft-agent\\python\\autonomous_master.py

Run:
    python autonomous_master.py

Environment:
    AUTONOMOUS_MAX_STEPS=0        # 0 = infinite
    AUTONOMOUS_SEED=4242
    MASTER_SAVE_EVERY=25
    MASTER_PRINT_EVERY=1
    MASTER_RETREAT_DISTANCE=45
"""

from __future__ import annotations

import atexit
import json
import math
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent import Agent
from autonomy import AutonomyLoop
from browser_env import BrowserEnv, BrowserBridgeError
from goal_fsm import GoalFSM
from memory import ExperienceStore, WorldMemory
from world_state import build_world_state

ROOT = Path(__file__).resolve().parent

EXP_PATH = ROOT / "experience_autonomous.json"
LOG_PATH = ROOT / "master_autonomous.jsonl"
LOCK_PATH = ROOT / "autonomous_master.lock"
PID_PATH = ROOT / "autonomous_master.pid"
FSM_PATH = ROOT / "goal_fsm_state.json"

SEED = int(os.environ.get("AUTONOMOUS_SEED", "4242"))
MAX_STEPS = int(os.environ.get("AUTONOMOUS_MAX_STEPS", "0"))  # 0 = infinite
SAVE_EVERY = max(1, int(os.environ.get("MASTER_SAVE_EVERY", "25")))
PRINT_EVERY = max(1, int(os.environ.get("MASTER_PRINT_EVERY", "1")))
RETREAT_DISTANCE = float(os.environ.get("MASTER_RETREAT_DISTANCE", "45.0"))

# Navigation substeps must not consume the entire learning run.
NAV_SUBSTEPS_BUDGET = max(1, int(os.environ.get("MASTER_NAV_SUBSTEPS_BUDGET", "3")))


def _write_log(row: Dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _lock() -> None:
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except Exception:
            old_pid = None

        if old_pid:
            try:
                os.kill(old_pid, 0)
                raise SystemExit(
                    f"[master] another instance is already alive: PID {old_pid}"
                )
            except ProcessLookupError:
                pass
            except PermissionError:
                raise SystemExit(
                    f"[master] cannot inspect existing PID {old_pid}; refusing duplicate"
                )
            except OSError:
                pass

        try:
            LOCK_PATH.unlink()
        except OSError:
            pass

    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def _unlock() -> None:
    for path in (LOCK_PATH, PID_PATH):
        try:
            if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink()
        except Exception:
            pass


def _signals() -> None:
    def _stop(signum, frame):
        raise KeyboardInterrupt

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            try:
                signal.signal(sig, _stop)
            except Exception:
                pass


def _player(info: Dict[str, Any]) -> Dict[str, Any]:
    return (info or {}).get("player") or {}


def _player_pos(info: Dict[str, Any]) -> Tuple[float, float]:
    p = _player(info)
    pos = p.get("pos") or {}
    if pos.get("x") is not None and pos.get("z") is not None:
        return float(pos["x"]), float(pos["z"])

    pp = (info or {}).get("player_pos")
    if isinstance(pp, (list, tuple)) and len(pp) >= 2:
        # player_pos is normally [x,z] in the browser bridge.
        return float(pp[0]), float(pp[-1])

    return 0.0, 0.0


def _live_mobs(info: Dict[str, Any]) -> list[Tuple[float, float, float]]:
    px, pz = _player_pos(info)
    mobs: list[Tuple[float, float, float]] = []

    for ent in ((info or {}).get("nearby") or []):
        if not isinstance(ent, dict):
            continue
        if ent.get("kind") != "mob" and ent.get("type") != "mob":
            continue
        if ent.get("dead") or ent.get("lootable"):
            continue

        hp = ent.get("hp")
        if hp is not None:
            try:
                if float(hp) <= 0:
                    continue
            except (TypeError, ValueError):
                continue

        pos = ent.get("pos") or {}
        x = ent.get("x", pos.get("x"))
        z = ent.get("z", pos.get("z"))
        if x is None or z is None:
            continue

        x = float(x)
        z = float(z)
        d = math.hypot(x - px, z - pz)
        mobs.append((d, x, z))

    mobs.sort(key=lambda row: row[0])
    return mobs


def _retreat_target(info: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    Compute a point away from the nearest visible hostile mobs.

    This is NOT a learning rule and does not write to the Q-table.
    It only guarantees a survivable state before a low-HP heal attempt.
    """
    mobs = _live_mobs(info)
    if not mobs:
        return None

    px, pz = _player_pos(info)
    vx = 0.0
    vz = 0.0

    for d, mx, mz in mobs[:5]:
        dx = px - mx
        dz = pz - mz
        dist = math.hypot(dx, dz)
        if dist < 1e-6:
            continue
        w = 1.0 / max(dist, 1.0)
        vx += (dx / dist) * w
        vz += (dz / dist) * w

    norm = math.hypot(vx, vz)
    if norm < 1e-6:
        return None

    return (
        px + (vx / norm) * RETREAT_DISTANCE,
        pz + (vz / norm) * RETREAT_DISTANCE,
    )


def _hp_frac(ws: Dict[str, Any], info: Dict[str, Any]) -> float:
    hp = ws.get("hp_frac")
    if hp is not None:
        try:
            return float(hp)
        except (TypeError, ValueError):
            pass

    p = _player(info)
    try:
        cur = float(p.get("hp") or 0.0)
        mx = float(p.get("maxHp") or p.get("hpMax") or 1.0)
        return cur / mx if mx > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _in_combat(ws: Dict[str, Any], info: Dict[str, Any]) -> bool:
    if ws.get("in_combat") is not None:
        return bool(ws.get("in_combat"))
    return bool(_player(info).get("inCombat"))


def _dead(info: Dict[str, Any], ws: Dict[str, Any]) -> bool:
    if _player(info).get("dead"):
        return True
    return bool(ws.get("dead"))


def _recover_death(
    env: BrowserEnv,
    fsm: GoalFSM,
    world_mem: WorldMemory,
) -> bool:
    info = getattr(env, "_last_info", None) or {}
    ws = build_world_state(info, world_mem)

    if not _dead(info, ws) and _hp_frac(ws, info) > 0:
        return False

    print("[master] DEATH -> enter_dead -> respawn", flush=True)

    # Preserve quest/giver context across death.
    try:
        fsm.enter_dead()
    except Exception:
        traceback.print_exc()

    try:
        env.respawn()
    except BrowserBridgeError:
        raise

    # Always obtain a fresh authoritative snapshot.
    fresh = env._require({"action": "snapshot"}, timeout=30.0).get("info", {}) or {}
    env._last_info = fresh

    alive = not _player(fresh).get("dead") and float(_player(fresh).get("hp") or 0) > 0
    print(
        f"[master] respawn={'OK' if alive else 'FAILED'} "
        f"hp={_player(fresh).get('hp')} pos={_player_pos(fresh)}",
        flush=True,
    )

    if alive:
        try:
            # Prefer the explicit restore path. The FSM implementation in the
            # current repository preserves active_quest / quest_giver.
            fsm.resume_from_dead()
        except Exception:
            traceback.print_exc()

    return True


def _retreat_if_needed(
    env: BrowserEnv,
    ws: Dict[str, Any],
    info: Dict[str, Any],
) -> bool:
    hp = _hp_frac(ws, info)
    if hp >= 0.35:
        return False
    if not _in_combat(ws, info):
        return False

    target = _retreat_target(info)
    if target is None:
        return False

    tx, tz = target
    print(
        f"[master] LOW_HP_COMBAT hp={hp:.3f} -> retreat "
        f"({tx:.1f},{tz:.1f}) before heal",
        flush=True,
    )

    try:
        env._navigate_to_coord(
            tx,
            tz,
            max_steps=80,
            timeout=90.0,
        )
    except BrowserBridgeError:
        raise

    # Fresh state after movement is mandatory; do not trust the pre-retreat
    # inCombat flag.
    after = env._require({"action": "snapshot"}, timeout=30.0).get("info", {}) or {}
    env._last_info = after
    after_ws = build_world_state(after)

    print(
        f"[master] after-retreat hp={_hp_frac(after_ws, after):.3f} "
        f"inCombat={_in_combat(after_ws, after)} pos={_player_pos(after)}",
        flush=True,
    )
    return True


def _sync_fsm(fsm: GoalFSM, ws: Dict[str, Any]) -> None:
    """
    Sync only the phase from observed facts.

    GoalFSM.decide() is intentionally NOT used here because the live decision
    path is GoalManager + AutonomyLoop + Agent._cycle().
    """
    fsm.update_from_world(ws)


def main() -> None:
    _lock()
    atexit.register(_unlock)
    _signals()

    print("=" * 78)
    print("WORLD OF CLAUDECRAFT — MASTER AUTONOMOUS LEARNER")
    print(f"PID: {os.getpid()}")
    print(f"SEED: {SEED}")
    print(f"MAX STEPS: {'INFINITE' if MAX_STEPS == 0 else MAX_STEPS}")
    print(f"EXPERIENCE: {EXP_PATH}")
    print(f"LOG: {LOG_PATH}")
    print("=" * 78, flush=True)

    mem = ExperienceStore(path=str(EXP_PATH))
    world_mem = WorldMemory()
    fsm = GoalFSM(memory_path=str(FSM_PATH))
    autonomy = AutonomyLoop()

    env = BrowserEnv(
        player_class="warrior",
        max_steps=100000,
        seed=SEED,
    )
    env.reset(seed=SEED)

    # Wire the SAME WorldMemory + FSM into the real learning Agent.
    agent = Agent(
        env,
        mem,
        seed=SEED * 3 + 7,
        world_mem=world_mem,
        fsm=fsm,
    )

    learning_steps = 0
    nav_substeps = 0
    deaths = 0
    started = time.time()

    try:
        # Prime FSM from actual state.
        info = getattr(env, "_last_info", None) or {}
        ws = build_world_state(info, world_mem)
        _sync_fsm(fsm, ws)

        while MAX_STEPS == 0 or learning_steps < MAX_STEPS:
            # --------------------------------------------------------------
            # 1. Authoritative state + death recovery
            # --------------------------------------------------------------
            info = getattr(env, "_last_info", None) or {}
            ws = build_world_state(info, world_mem)

            if _dead(info, ws):
                _recover_death(env, fsm, world_mem)
                deaths += 1

                info = getattr(env, "_last_info", None) or {}
                ws = build_world_state(info, world_mem)
                _sync_fsm(fsm, ws)

            # --------------------------------------------------------------
            # 2. FSM phase is derived from facts.
            # --------------------------------------------------------------
            _sync_fsm(fsm, ws)

            # --------------------------------------------------------------
            # 3. SURVIVAL RECOVERY — physically leave combat before heal.
            # --------------------------------------------------------------
            if _retreat_if_needed(env, ws, info):
                info = getattr(env, "_last_info", None) or {}
                ws = build_world_state(info, world_mem)
                _sync_fsm(fsm, ws)

            # --------------------------------------------------------------
            # 4. AutonomyLoop builds subgoal, masks impossible actions,
            #    and may emit a real navigation command.
            # --------------------------------------------------------------
            candidates = agent.policy._candidates(
                info,
                ws,
                goal=fsm.goal,
            )

            pre = autonomy.before_action(info, ws, candidates)

            nav_command = pre.get("nav_command")

            if nav_command and nav_substeps < NAV_SUBSTEPS_BUDGET:
                # Execute actual navigation now. This is a world transition,
                # not a Q-learning transition.
                env.raw_call(nav_command)
                nav_substeps += 1

                info_after_nav = getattr(env, "_last_info", None) or {}
                ws_after_nav = build_world_state(info_after_nav, world_mem)

                try:
                    autonomy.after_action(
                        "explore",
                        info_after_nav,
                        ws_after_nav,
                        reward=0.0,
                        goal=fsm.goal,
                    )
                except Exception:
                    traceback.print_exc()

                # Do not spend the learning step on navigation.
                _write_log({
                    "ts": time.time(),
                    "kind": "navigation",
                    "learning_step": learning_steps,
                    "nav_substep": nav_substeps,
                    "command": nav_command,
                    "nav_status": pre.get("nav_status"),
                    "subgoal": pre.get("subgoal"),
                    "pos": _player_pos(info_after_nav),
                    "hp_frac": _hp_frac(ws_after_nav, info_after_nav),
                })
                continue

            # After the budget, force a real learning step.
            nav_substeps = 0

            # Give the learned policy exactly the autonomous mask/context.
            masked = pre.get("candidates")
            if masked and isinstance(getattr(agent.policy, "hints", None), dict):
                agent.policy.hints["masked_candidates"] = masked

            decision_ctx = pre.get("decision_context")
            if decision_ctx is not None:
                agent.policy._ctx = decision_ctx
            else:
                agent.policy._ctx = None

            # --------------------------------------------------------------
            # 5. REAL LEARNING STEP
            #
            # Agent._cycle:
            #   policy.decide
            #   -> CRITICAL_HP override (af2cad1)
            #   -> skill
            #   -> verifier
            #   -> reward
            #   -> Q-learning / replay
            # --------------------------------------------------------------
            rec = agent.step()
            learning_steps += 1

            info_after = getattr(env, "_last_info", None) or {}
            ws_after = rec.get("ws_after") or build_world_state(info_after, world_mem)

            # Feed the ACTUAL action/result into the autonomy verifier.
            try:
                post = autonomy.after_action(
                    rec.get("action") or "noop",
                    info_after,
                    ws_after,
                    reward=float(rec.get("reward") or 0.0),
                    goal=fsm.goal,
                )
            except Exception:
                traceback.print_exc()
                post = {}

            _write_log({
                "ts": time.time(),
                "kind": "learning",
                "learning_step": learning_steps,
                "action": rec.get("action"),
                "verdict": rec.get("verdict"),
                "outcome_kind": rec.get("outcome_kind"),
                "reward": rec.get("reward"),
                "fsm_state": fsm.state.name,
                "fsm_goal": fsm.goal,
                "subgoal": pre.get("subgoal"),
                "forced_skill": pre.get("forced_skill"),
                "hp_before": _hp_frac(ws, info),
                "hp_after": _hp_frac(ws_after, info_after),
                "quest_status": ws_after.get("quest_status"),
                "quest_progress": ws_after.get("quest_progress"),
                "distance_to_giver": ws_after.get("distance_to_giver"),
                "kills": info_after.get("kills"),
                "deaths": info_after.get("deaths"),
                "autonomy_result": post.get("skill_result") if isinstance(post, dict) else None,
            })

            if learning_steps % PRINT_EVERY == 0:
                print(
                    f"[{learning_steps}] "
                    f"action={str(rec.get('action')):16s} "
                    f"v={str(rec.get('verdict')):12s} "
                    f"r={float(rec.get('reward') or 0):+6.2f} "
                    f"hp={_hp_frac(ws_after, info_after):.2f} "
                    f"q={ws_after.get('quest_status')} "
                    f"qprog={ws_after.get('quest_progress')} "
                    f"dist={float(ws_after.get('distance_to_giver') or 0):.1f} "
                    f"fsm={fsm.state.name}",
                    flush=True,
                )

            if learning_steps % SAVE_EVERY == 0:
                elapsed = max(0.001, time.time() - started)
                try:
                    world_mem.save()
                except Exception:
                    traceback.print_exc()
                try:
                    fsm.save()
                except Exception:
                    traceback.print_exc()

                print(
                    f"[master] checkpoint "
                    f"steps={learning_steps} "
                    f"rate={learning_steps/elapsed:.3f}/s "
                    f"deaths={deaths}",
                    flush=True,
                )

    except KeyboardInterrupt:
        print("[master] stopped by operator", flush=True)
    except BrowserBridgeError as exc:
        print(
            f"[master] BRIDGE/INFRA FAILURE: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise
    except Exception:
        # Programming errors MUST remain visible. Do not turn them into fake
        # ENV_ERROR lessons.
        traceback.print_exc()
        raise
    finally:
        try:
            env.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

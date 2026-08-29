"""play_autonomous.py — persistent autonomous game session (Level 3).

NOT a diagnostic benchmark. This is the real target: an agent that observes the
online WoC world, chooses its OWN goals/actions from learned policy + exploration,
acts, gets consequences, remembers, and keeps playing — without any
`if quest: farm()` / `if far: return()` script steering it.

Design:
- reset -> observe -> decide -> act -> observe -> learn -> repeat, for N steps.
- NO forcing functions (no force_far / force_to_band). The agent walks where it
  decides. We just feed it the world.
- Memory persists every SAVE_EVERY steps (survives crashes / restarts).
- Metrics track BEHAVIOUR DEVELOPMENT, not P(return):
    steps, kills, quests_accepted, quests_done, deaths, xp, copper,
    unique_npcs, unique_areas (by position cell), exploration_cells,
    repeated_mistakes (same bad action in same bucket 2x+), recovery
    (after a negative lesson, a different action chosen next).
- One-line-per-step log to autonomous_log.jsonl (append), periodic summary to
  stdout. No chat spam.

No reward change. No Sim change. No PPO. Policy already chooses; this just lets
it live.
"""

import json
import os
import sys
import time
import atexit
import traceback
from collections import Counter, defaultdict

from browser_env import BrowserEnv, BrowserBridgeError

# NOTE: agent / memory / world_state are imported lazily INSIDE main(), AFTER
# _acquire_lock(). They pull in numpy/gymnasium (slow + heavy import) and the
# ExperienceStore load can take ~90s. If we imported them at module top, a second
# launcher-spawned process would not reach _acquire_lock() until after that
# import finished, so the launcher could spawn 5+ agents in the window before the
# first one acquires the lock -> multiple agents driving one character. Lazy
# import makes the lock check happen in <1s, so duplicates exit(2) immediately.

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_autonomous.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "autonomous_log.jsonl")
LOCK_PATH = os.path.join(os.path.dirname(__file__), "play_autonomous.lock")
N_STEPS = int(os.environ.get("AUTONOMOUS_STEPS", "3000"))
SAVE_EVERY = int(os.environ.get("SAVE_EVERY", "200"))
WINDOW = int(os.environ.get("AUTONOMOUS_WINDOW", "500"))  # Level-4 windowed metrics
# Frozen-eval cadence: every MEASURE_EVERY steps, run a MEASUREMENT step
# (exploration_weight=0 -> no exploration bonus, learn=False -> no weight update).
# This measures the CURRENT policy's choice probabilities without contaminating
# them, so BEFORE/AFTER comparisons are valid (user audit 2026-08-20: the
# exploration_weight=0 path existed in agent.step_no_learn but was never called).
MEASURE_EVERY = int(os.environ.get("MEASURE_EVERY", "0"))  # 0 = disabled
SEED = int(os.environ.get("AUTONOMOUS_SEED", "4242"))


def _acquire_lock():
    """Guarantee exactly ONE live play_autonomous drives the character.

    Uses an ATOMIC file creation (O_CREAT | O_EXCL) as a real mutual-exclusion
    primitive. The OS serialises this: the first process wins, every later
    process gets FileExistsError immediately — there is no read-then-write race
    window (which is exactly how 5 agents once spawned at once: each read a
    missing/stale lock and all wrote themselves). PID-files are NOT a mutex;
    this is.

    The lock file holds our PID as diagnostics only; the exclusivity comes from
    the file EXISTING, not from its contents. Released via atexit/_release_lock
    on any exit so a dead agent never blocks a restart.
    """
    pid = os.getpid()
    try:
        # Atomic: fails if the file already exists. No TOCTOU race.
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(pid))
    except FileExistsError:
        # Someone holds the lock. Distinguish "another live agent" from "stale
        # lock left by a crashed process whose PID is now gone" — but DO NOT
        # trust a PID check alone; just refuse. The launcher's job is to restart
        # only after the holder is truly dead (it kills by PID / checks health).
        try:
            with open(LOCK_PATH) as f:
                holder = f.read().strip()
        except OSError:
            holder = "?"
        sys.stderr.write(
            f"[autonomous] refusing to start: lock held (holder PID {holder}) at {LOCK_PATH}\n")
        sys.exit(2)
    except OSError as e:
        sys.stderr.write(f"[autonomous] lock error: {e}\n")
        sys.exit(2)
    return pid


def _release_lock():
    """Remove the singleton lock only if this process still owns it."""
    try:
        with open(LOCK_PATH, "r", encoding="utf-8") as f:
            holder = f.read().strip()
        if holder != str(os.getpid()):
            return
        os.remove(LOCK_PATH)
    except (OSError, ValueError):
        pass


def cell_of(pos, size=20.0):
    """Coarse position cell for exploration tracking."""
    if not pos:
        return "none"
    return f"{int(pos[0]//size)}_{int(pos[1]//size)}"


def main():
    # --- crash telemetry: on ANY uncaught exception, write the FULL traceback to
    # agent_crash.log (not just the live terminal, which the launcher hides in a
    # /min window). This is what makes a silent agent death debuggable. ---
    import traceback as _tb
    _crash_path = os.path.join(os.path.dirname(__file__), "agent_crash.log")
    def _excepthook(etype, evalue, etb):
        try:
            with open(_crash_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== AGENT CRASH {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                _tb.print_exception(etype, evalue, etb, file=f)
        except OSError:
            pass
        # also echo to stderr so the launcher log captures it
        _tb.print_exception(etype, evalue, etb)
        # lifecycle: record the crash as a STOP with the exception type
        try:
            _log_lifecycle("AGENT_STOP", reason=f"crash:{etype.__name__}")
        except Exception:
            pass
    sys.excepthook = _excepthook
    try:
        import faulthandler as _fh
        # DUMP ONLY: if the agent ever hangs (no step for 15s) we get a traceback
        # in agent_crash.log so the deadlock is diagnosable. exit=False is
        # CRITICAL — exit=True calls _exit(1) and kills this process 15s after
        # every boot, which makes the .bat launcher restart it forever (the
        # "farm -> python closes -> heal -> closes -> farm" loop). Death/respawn/
        # bridge blips are now handled IN-PROCESS; nothing here should self-kill.
        _fh.dump_traceback_later(900, exit=False, file=open(_crash_path, "a", encoding="utf-8"))
    except Exception:
        pass

    _acquire_lock()  # refuse to run if another instance already drives the char
    # Register immediately so a heavy-import failure cannot strand our lock.
    atexit.register(_release_lock)

    # --- lifecycle logging: one line per START/STOP so a single log makes the
    # continuous-episode invariant auditable (PID constant across deaths). ---
    _ppid = os.getppid()
    def _log_lifecycle(event, **kv):
        parts = " ".join(f"{k}={v}" for k, v in kv.items())
        line = f"{event} pid={os.getpid()} parent_pid={_ppid} {parts}\n"
        try:
            with open(os.path.join(os.path.dirname(__file__), "agent_lifecycle.log"), "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
    _log_lifecycle("AGENT_START")
    atexit.register(_log_lifecycle, "AGENT_STOP", reason="normal_exit")

    # LAZY heavy import: must come AFTER _acquire_lock() so duplicate launcher
    # spawns hit the lock in <1s and exit(2) instead of piling up (see header
    # note). These pull in numpy/gymnasium + load ExperienceStore (~90s).
    from agent import Agent
    from memory import ExperienceStore, _bucket, WorldMemory
    from world_state import build_world_state
    from goal_fsm import GoalFSM
    from replay_buffer import ReplayBuffer
    from strategy_memory import StrategyMemory

    # --- АВТОНОМНЫЙ КОНТУР (Task 11) ---
    # Fail-closed (P0.4): при WOC_AUTONOMY!=0 провал контракта ОСТАНАВЛИВАЕТ
    # процесс. Раньше здесь стоял `autonomy = None` — агент продолжал работу
    # БЕЗ автономного контура, лог говорил "agent running", а замер измерял
    # совсем не то, что собирались измерять. Единственный законный путь к
    # legacy-режиму — явный WOC_AUTONOMY=0.
    autonomy = None
    _autonomy_requested = os.environ.get("WOC_AUTONOMY", "1") != "0"
    if _autonomy_requested:
        try:
            from autonomy import AutonomyLoop
            from skill_contracts import assert_predicates_implemented
            from skill_index_contract import assert_skill_indices_match
            assert_predicates_implemented()
            assert_skill_indices_match()
            autonomy = AutonomyLoop(min_dwell=20)
            print("[autonomy] loop enabled (contracts verified)", flush=True)
        except Exception:
            traceback.print_exc()
            print("[autonomy] FATAL: contract check failed. "
                  "Отказываюсь стартовать с испорченными контрактами — "
                  "5000 шагов записали бы мусорный replay. "
                  "Запусти с WOC_AUTONOMY=0, если legacy-режим нужен намеренно.",
                  flush=True)
            raise SystemExit(3)
    else:
        print("[autonomy] disabled by WOC_AUTONOMY=0 (legacy mode, explicit)",
              flush=True)
    # Record our live PID so the launcher's singleton check (agent.pid) tracks
    # the real long-lived process. (Previously the launcher wrote this via a
    # python -c wrapper; now the module records it directly and reliably.)
    try:
        with open(os.path.join(os.path.dirname(__file__), "agent.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    print(f"[BOOT] pid={os.getpid()} autonomous run starting (single long-lived process)", flush=True)

    # P0.4 / P0.7 — учёт того, что реально произошло за прогон.
    # _learning_steps: шаги, прошедшие полную цепочку agent.step()
    #                  (policy -> skill -> verifier -> reward -> memory).
    # _nav_substeps:   навигационные подшаги (env.raw_call), которые НЕ дают
    #                  обучающего перехода. "N шагов" != "N переходов".
    # _autonomy_errors: сбои контура; порог валит процесс, а не прячет их.
    _learning_steps = 0
    _nav_substeps = 0
    _nav_substeps_since_learning = 0  # nav budget counter (resets after each learning step)
    _autonomy_errors = 0
    _AUTONOMY_MAX_ERRORS = int(os.environ.get("WOC_AUTONOMY_MAX_ERRORS", "5"))
    # V0 baseline: пошаговая трасса (skill/result/failure_reason + состояние
    # ресурсов). Пишется в WOC_TRACE_OUT, по умолчанию рядом с логом.
    _step_trace = []
    _TRACE_OUT = os.environ.get(
        "WOC_TRACE_OUT",
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "step_trace.json"))
    if os.path.exists(EXP_PATH):
        # resume: keep learned memory across runs
        print(f"[autonomous] resuming from {EXP_PATH}")
    mem = ExperienceStore(path=EXP_PATH)
    try:
        env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED)
        env.reset(seed=SEED)
    except Exception as e:
        # The bridge is down (CDP/HTTP transport rejected) or the game tab is
        # not ready. Previously this threw at import time with __file__ undefined
        # (launcher used exec(open().read())) and died silently with an empty
        # agent_run.log. Now we log it honestly and exit so the launcher's 10s
        # loop restarts us cleanly once the bridge is up.
        sys.stderr.write(
            f"[autonomous] FATAL: cannot init BrowserEnv (bridge up? game tab ready?): {type(e).__name__}: {e}\n"
        )
        sys.exit(3)
    # WorldMemory (persistent quest-giver / vendor knowledge) — used to attribute
    # return/turn-in navigation to a remembered giver vs a fallback.
    world_mem = WorldMemory()
    # GoalFSM: explicit current_goal, persisted to goal_state.json so an
    # infrastructure restart does NOT wipe an in-progress quest.
    goal_fsm = GoalFSM()
    # ReplayBuffer: store transitions with rare-event priority (10k-50k).
    replay = ReplayBuffer(cap=20000)
    # StrategyMemory: which strategies worked (per quest/goal keys).
    strat_mem = StrategyMemory()
    # ШАГ 4: раньше StrategyMemory была write-only (preference() читался
    # только в смоук-тесте). Передаём её политике, чтобы доказанные
    # стратегии реально влияли на выбор действия.
    try:
        agent.policy.strategy_memory = strat_mem
    except Exception:
        pass
    # SelfReflection: the 'делал выводы' loop — reviews recent steps every
    # SAVE_EVERY, draws conclusions (death clusters, action saturation, quest
    # stalls), persists them to self_reflection.json.
    from self_reflection import SelfReflection
    refl = SelfReflection()

    # LLM brain (spec 2026-08-23): off by default, WOC_BRAIN=on enables it.
    # Failure of the brain at ANY point degrades to the plain FSM+Q behavior.
    from episodic import EpisodicLog
    episodes = EpisodicLog()
    # Шаг #3 (Q6): домашний якорь рабочей зоны. Агент уходил на [-13, 275],
    # где нет ни мобов, ни трупов, ни гиверов, и тратил там шаги впустую.
    from work_anchor import WorkAnchor
    anchor = WorkAnchor()
    # ШАГ 3 спеки (2026-08-24): Event Bus был мёртв — 9 типов событий не
    # доходили ни до награды, ни до рефлексии. Теперь события каждого шага
    # питают рефлексию, а завершения квестов — StrategyMemory.
    from event_bus import EventBus
    ebus = EventBus(spawn_points=[[0.0, 0.0]])
    # Failure Analyzer (план 2026-08-24, п.4): структурированные причины неудач
    from failure_analyzer import FailureAnalyzer
    fail_analyzer = FailureAnalyzer()
    # Navigation Memory (план 2026-08-24, п.5): статистика маршрутов A->B
    from nav_memory import NavMemory
    nav_memory = NavMemory()
    brain = None
    # 2026-08-24 (аудит: HARMFUL): вызов LLM в горячем цикле замедлял шаг в 6
    # раз (0.30с -> 1.80с; 75 мин чистой латентности на 3000 шагов), а её цели
    # всё равно затирались фактами. Режимы теперь:
    #   off      — по умолчанию, LLM не вызывается вовсе;
    #   advisory — вызывается РЕДКО (BRAIN_EVERY шагов), пишет только СОВЕТ;
    #   on       — устаревший синоним advisory (запись цели всё равно отключена).
    BRAIN_EVERY = int(os.environ.get("WOC_BRAIN_EVERY", "200"))
    _brain_mode = os.environ.get("WOC_BRAIN", "off").lower()
    if _brain_mode in ("on", "advisory"):
        try:
            from llm_brain import LLMBrain
            from brain_glue import build_brain_payload, apply_decision
            brain = LLMBrain()
            print("[brain] enabled (WOC_BRAIN=on)", flush=True)
        except Exception:
            traceback.print_exc()
    brain_last_goal = None
    brain_fail_streak = 0

    # CRITICAL: pass world_mem INTO the Agent so quest_skill.return_to_giver can
    # read remembered giver positions. Previously the Agent was created WITHOUT
    # world_mem (defaulting to an empty WorldMemory inside), while this local
    # world_mem was never wired in — so return_to_giver always fell back to the
    # snapshot's turnInNpc and never used persisted giver_pos.
    agent = Agent(env, mem, seed=SEED * 3 + 7, world_mem=world_mem,
                  fsm=goal_fsm, replay=replay, strat_mem=strat_mem)

    # metrics — extended per user audit (2026-08-20). These separate real
    # long-horizon autonomy from short-loop survival, and are the acceptance
    # criteria for the self-learning stage (esp. quest_turnin_rate).
    m = {
        "steps": 0, "kills": 0, "quests_accepted": 0, "quests_done": 0,
        "deaths": 0, "xp": 0, "copper": 0,
        "unique_npcs": set(), "explored_cells": set(),
        "action_counts": Counter(), "env_errors": 0,
        "neg_lessons": 0, "recovery_after_neg": 0,
        "repeated_mistakes": 0,
        "win_reward": 0.0, "win_deaths": 0, "win_repeat": 0,
        "win_actions": Counter(), "win_steps": 0, "deaths_prev": 0,
        # --- extended autonomy metrics ---
        "quests_completed": 0,        # objectives done, awaiting turn-in
        "quests_turned_in": 0,        # actually turned in (verifier SUCCESS)
        "quest_turnin_failures": 0,    # turn_in attempted but FAILURE/INCONCLUSIVE
        "giver_memory_hits": 0,       # return/turn-in used a remembered giver
        "giver_memory_misses": 0,      # return/turn-in had no remembered giver (fallback)
        "vendors_found": 0,            # distinct vendor NPCs ever seen
        "vendor_navigation_success": 0,
        "items_sold": 0,               # sell_junk SUCCESS (inventory shrank)
        "sell_failures": 0,
        "navigation_success": 0,       # return/turn_in arrived (SUCCESS)
        "navigation_stuck": 0,         # return/turn_in PARTIAL repeatedly (no progress)
        "navigation_recovery": 0,      # stuck -> later arrived
        "programming_errors": 0,       # FATAL crash from a code bug (should be 0)
        "bridge_errors": 0,            # ENV_ERROR recoveries (infra)
        "goal_switches": 0,            # policy changed action category vs prev step
        "goal_completed": 0,           # a goal (quest) reached DONE
        "episodes": 1,                 # restarts count as new episodes
        "respawns": 0,
        "reward_mean": 0.0,            # running mean over steps
        "reward_window": 0.0,          # last-window sum (alias of win_reward)
        "prev_goal": None,
        "_last_turnin_partial": False,
    }
    # track per-bucket last action + whether it was negative, to measure recovery
    last_bucket_action = {}
    last_bucket_neg = {}
    # (bucket, action) pairs that already yielded a negative lesson — used to
    # detect REPEATED mistakes (same bad action chosen again in the same bucket).
    neg_state_action = set()

    logf = open(LOG_PATH, "a", encoding="utf-8")

    def snap(info):
        ws = build_world_state(info, world_mem=world_mem)
        return ws

    # INIT RESPAWN: if the character is already dead (ghost / hp depleted) at
    # startup, revive BEFORE the first step so the agent never begins a learning
    # episode from a broken state. Without this the agent would call explore on a
    # dead body, the bridge exploreWalk may stall, and faulthandler would kill it
    # before the in-loop respawn-glue (which only runs AFTER a completed step).
    try:
        _p0 = (env._last_info or {}).get("player", {}) or {}
        if _p0.get("dead") or _p0.get("hp", 1) <= 0:
            print("[autonomous] init: character dead at startup -> respawning")
            _, alive = env.respawn()
            if alive:
                m["respawns"] += 1
            else:
                # Could not revive at init (e.g. healer not reachable). Do NOT
                # inflate the counter; let the in-loop recovery handle it.
                print("[autonomous] init respawn not confirmed (revived=false); continuing", flush=True)
    except Exception as e:
        # respawn failure at init is infra, not a programming bug; log and continue
        sys.stderr.write(f"[autonomous] init respawn failed (continuing): {type(e).__name__}: {e}\n")

    def _bridge_recovered() -> bool:
        try:
            h = env.health(timeout=3.0)
            return bool(h.get("ok") and h.get("bridge") and h.get("page") and h.get("game"))
        except BrowserBridgeError:
            return False

    prev = snap(env._last_info)
    start = time.time()

    # FSM: sync the explicit goal with the observed world at the top of each
    # step (death handling is done separately below via enter_dead/resume).
    goal_fsm.update_from_world(prev)

    for i in range(N_STEPS):
        # Singleton self-check: if another instance now holds the lock (our lock
        # file was removed/recreated by a newer instance, or we are an orphaned
        # duplicate spawned before the lock existed), stand down silently. This
        # cleans up multiboxing without an external kill (which is blocked across
        # sessions on this host). Runs every step — cheap (one stat + one read).
        if os.path.exists(LOCK_PATH):
            try:
                holder = int(open(LOCK_PATH).read().strip())
            except (ValueError, OSError):
                holder = None
            if holder is not None and holder != os.getpid():
                # another live instance is the real one; we are a duplicate
                sys.stderr.write(
                    f"[autonomous] duplicate detected (lock holder {holder} != us {os.getpid()}) -> exiting\n")
                _log_lifecycle("AGENT_STOP", reason="duplicate_yield")
                return
        try:
            if MEASURE_EVERY > 0 and i > 0 and i % MEASURE_EVERY == 0:
                # FROZEN EVAL: measure current policy WITHOUT learning (exploration
                # bonus off, no weight update). The resulting verdict/reward still
                # flow into metrics, but memory is untouched -> BEFORE/AFTER valid.
                rec = agent.step_no_learn(exploration_weight=0.0)
                rec = dict(rec)
                rec["verdict"] = (rec.get("verdict") or "") + " [MEASURE]"
            else:
                # Шаг #3 (Q6): якорь рабочей зоны — наблюдаем и, если вокруг
                # пусто, возвращаемся в последнюю точку, где были объекты
                # действия. Без этого агент стоит в пустоте и жжёт шаги.
                #
                # ВАЖНО: при активном автономном контуре якорь только НАБЛЮДАЕТ.
                # Иначе два водителя тянут персонажа в разные стороны: контур
                # ведёт к цели АКТИВНОГО КВЕСТА (FIND_MOB -> спиральный поиск),
                # а якорь — в одну запомненную точку, и движение взаимно
                # гасится (живой замер: "[anchor] пусто вокруг" 6 раз подряд
                # при работающем FIND_MOB). Квестовая цель важнее памяти о
                # старой зоне, поэтому решение остаётся за контуром.
                try:
                    _live = getattr(env, "_last_info", None) or {}
                    anchor.observe(_live)
                    if autonomy is None and anchor.needs_return(_live):
                        tgt = anchor.return_target(_live)
                        if tgt:
                            print(f"[anchor] пусто вокруг -> возврат к {tgt}", flush=True)
                            env._navigate_to_coord(tgt[0], tgt[1], max_steps=60)
                            anchor.save()
                except Exception:
                    traceback.print_exc()
                # LLM brain (spec 2026-08-23): consult on transitions only. The brain
                # PROPOSES a goal; survival gates in policy still veto everything.
                if brain is not None and goal_fsm is not None:
                    try:
                        new_qid = goal_fsm.quest_id
                        # Только редкие консультации: раз в BRAIN_EVERY шагов.
                        # Это и есть «убрать из горячего цикла» — латентность
                        # 1-7с платится 15 раз на 3000 шагов, а не постоянно.
                        if i > 0 and i % BRAIN_EVERY == 0:
                            from world_state import build_world_state as _bws
                            _live_info = getattr(env, "_last_info", None) or {}
                            _live_ws = _bws(_live_info)
                            world_payload = build_brain_payload(_live_ws, _live_info, new_qid)
                            fails = episodes.recent_failures(n=3)
                            lessons = [c.get("detail") for c in refl.journal[-5:]]
                            decision = brain.decide(world_payload, fails, lessons)
                            if apply_decision(goal_fsm, decision):
                                print(f"[brain] goal={decision['goal']} reason={decision['reason']}", flush=True)
                                brain_last_goal = decision["goal"]
                        brain._last_qid = new_qid
                    except Exception:
                        traceback.print_exc()
                # --- АВТОНОМНЫЙ КОНТУР (Task 11) ---
                # Planner/маска/навигация/recovery оборачивают шаг агента.
                # Контур ПРЕДЛАГАЕТ действие, agent.step() исполняет и учится.
                # P0.4: сбои контура НЕ проглатываются молча. Каждый учитывается
                # в _autonomy_errors; при WOC_AUTONOMY!=0 и превышении порога
                # процесс останавливается, иначе можно намерить 5000 шагов
                # "автономной архитектуры", которая на деле была отключена.
                _pre = None
                _NAV_SUBSTEPS_BUDGET = 3  # max nav substeps before forcing a learning step
                if autonomy is not None:
                    try:
                        _live_info = getattr(env, "_last_info", None) or {}
                        if _live_info:
                            from world_state import build_world_state as _bws2
                            _live_ws = _bws2(_live_info)
                            # кандидаты берём у САМОЙ политики (её интерфейс —
                            # _candidates/decide, у неё нет .actions)
                            try:
                                _cands = list(agent.policy._candidates(
                                    _live_info, _live_ws) or [])
                            except Exception:
                                _cands = []
                            _pre = autonomy.before_action(
                                _live_info, _live_ws, _cands)
                            # навигация исполняется прямо здесь: у agent.step()
                            # нет канала для координат
                            _cmd = _pre.get("nav_command")
                            # NAV BUDGET: if we've spent too many substeps navigating,
                            # force a learning step so policy can choose differently
                            # (e.g. accept_quest if giver already in range)
                            if _cmd and _nav_substeps_since_learning < _NAV_SUBSTEPS_BUDGET:
                                env.raw_call(_cmd)
                                _nav_after = getattr(env, "_last_info", None) or {}
                                autonomy.after_action(
                                    "explore", _nav_after, _bws2(_nav_after))
                                _nav_substeps += 1
                                _nav_substeps_since_learning += 1
                                continue
                            # подсказка политике через её же hints-канал
                            # (legacy — будет удалён после полного перехода на DecisionContext)
                            _forced = _pre.get("forced_skill")
                            if _forced and isinstance(
                                    getattr(agent.policy, "hints", None), dict):
                                agent.policy.hints["autonomy_subgoal"] = {
                                    "key": "autonomy_subgoal", "skill": _forced}
                            # Explicit decision context — основной канал
                            _ctx = _pre.get("decision_context")
                            if _ctx is not None:
                                agent.policy._ctx = _ctx
                            else:
                                agent.policy._ctx = None
                            # передать masked (автономная маска) в политику
                            _masked = _pre.get("candidates")
                            if _masked and isinstance(
                                    getattr(agent.policy, "hints", None), dict):
                                agent.policy.hints["masked_candidates"] = _masked
                    except Exception:
                        traceback.print_exc()
                        _autonomy_errors += 1
                        print("[autonomy] before_action failed (%d/%d)"
                              % (_autonomy_errors, _AUTONOMY_MAX_ERRORS),
                              flush=True)
                        if (_autonomy_requested
                                and _autonomy_errors >= _AUTONOMY_MAX_ERRORS):
                            print("[autonomy] FATAL: контур сбоил %d раз — "
                                  "останавливаюсь. Дальнейший прогон измерял бы "
                                  "агента БЕЗ автономного контура и был бы "
                                  "выдан за baseline автономности."
                                  % (_autonomy_errors,), flush=True)
                            raise SystemExit(4)
                rec = agent.step()
                _learning_steps += 1
                _nav_substeps_since_learning = 0  # reset nav budget after learning
                if autonomy is not None and _pre is not None:
                    try:
                        _after = getattr(env, "_last_info", None) or {}
                        if _after:
                            from world_state import build_world_state as _bws3
                            _ares = autonomy.after_action(
                                (rec or {}).get("action") or "noop",
                                _after, _bws3(_after),
                                reward=float((rec or {}).get("reward") or 0.0))
                            # V0 baseline: причина КАЖДОГО не-успеха. Раньше
                            # возврат after_action отбрасывался, поэтому после
                            # прогона была видна только цифра "heal failure=N"
                            # без ответа, ГДЕ агент теряет автономность.
                            # Пишем и состояние ресурсов на момент шага, чтобы
                            # отличить "ресурс был -> heal провалился" от
                            # "ресурс кончился -> heal не должен был вызываться".
                            if isinstance(_ares, dict):
                                _inv_now = (_after.get("inventory_by_id")
                                            if isinstance(_after, dict) else None)
                                _pl_now = ((_after.get("player") or {})
                                           if isinstance(_after, dict) else {})
                                _step_trace.append({
                                    "step": i,
                                    "skill": _ares.get("skill"),
                                    "result": _ares.get("skill_result"),
                                    "failure_reason": _ares.get("failure_reason"),
                                    "subgoal": _ares.get("subgoal"),
                                    "goal": _ares.get("goal"),
                                    "reward": _ares.get("reward"),
                                    "hp": _pl_now.get("hp"),
                                    "max_hp": _pl_now.get("maxHp"),
                                    "in_combat": (_after.get("in_combat")
                                                  if isinstance(_after, dict) else None),
                                    "inventory_count": (len(_inv_now)
                                                        if isinstance(_inv_now, dict) else None),
                                    "inventory": _inv_now,
                                    "recovery": ((_ares.get("recovery") or {}).get("recovery_action")
                                                 if isinstance(_ares.get("recovery"), dict) else None),
                                })
                                # Прогон может быть прерван (kill/крэш/мост).
                                # Периодический дамп: незавершённый V0 всё
                                # равно останется анализируемым, а не пропадёт.
                                if len(_step_trace) % 50 == 0:
                                    try:
                                        with open(_TRACE_OUT, "w", encoding="utf-8") as _pf:
                                            json.dump({
                                                "accounting": {
                                                    "environment_steps": i,
                                                    "learning_steps": _learning_steps,
                                                    "nav_substeps": _nav_substeps,
                                                    "autonomy_errors": _autonomy_errors,
                                                    "skill_attempts": len(_step_trace),
                                                    "partial": True,
                                                },
                                                "steps": _step_trace,
                                            }, _pf, ensure_ascii=False,
                                                default=str)
                                    except Exception:
                                        pass
                    except Exception:
                        traceback.print_exc()
                        _autonomy_errors += 1
                        print("[autonomy] after_action failed (%d/%d)"
                              % (_autonomy_errors, _AUTONOMY_MAX_ERRORS),
                              flush=True)
                        if (_autonomy_requested
                                and _autonomy_errors >= _AUTONOMY_MAX_ERRORS):
                            print("[autonomy] FATAL: контур сбоил %d раз — "
                                  "останавливаюсь (см. выше)."
                                  % (_autonomy_errors,), flush=True)
                            raise SystemExit(4)
        except BrowserBridgeError as e:
            # Infra failure (bridge/CDP/HTTP down). RECOVER IN-PROCESS — do NOT
            # re-create BrowserEnv/Agent. That re-init itself calls snapshot/
            # respawn, which raises AGAIN while the bridge is down, escaping as
            # an uncaught exception that kills the process and forces the .bat
            # launcher to restart it with a NEW pid + NEW RNG seed + NEW
            # in-memory policy. That severs the continuous learning episode
            # (the "farm -> python closes -> heal -> closes -> farm" loop the
            # user observed). The env/agent we already hold are stateless across
            # calls (each _post opens a fresh socket), so just log and let the
            # next iteration retry. Death/respawn/heal are ACTIONS inside this
            # one process, never a process restart.
            m["env_errors"] += 1
            m["bridge_errors"] += 1
            # NOTE: do NOT increment m["episodes"] here — a transient blip is not
            # a new episode; the step counter must stay continuous.
            print(f"[AGENT] pid={os.getpid()} bridge error at step {i}, retrying in-process: {type(e).__name__}: {e}", flush=True)
            _last = snap(env._last_info)
            rec = {"action": "RESTART", "verdict": "ENV_ERROR", "outcome_kind": "ENV_ERROR",
                   "reward": 0.0, "ws_before": _last, "ws_after": _last}
        except Exception:
            # PROGRAMMING BUG (NameError/KeyError/TypeError/AssertionError/...).
            # Must NOT be masked as a silent restart — crash loudly with traceback
            # so the broken code is found (acceptance test #3). Flush the loop.
            m["programming_errors"] += 1
            traceback.print_exc()
            sys.stderr.write(
                f"[autonomous] FATAL programming error at step {i}: aborting run "
                f"(memory saved at {EXP_PATH})\n"
            )
            mem.save()
            sys.exit(1)

        if rec.get("outcome_kind") == "ENV_ERROR":
            # Never use stale world state as proof of transport recovery. Poll the
            # real bridge /health endpoint while keeping the SAME Python PID alive.
            waited = 0
            while waited < 120 and not _bridge_recovered():
                time.sleep(2.0)
                waited += 2

        # respawn glue: if the character died (hp depleted OR stuck as a ghost
        # with dead:true but full hp), release spirit + revive so the loop keeps
        # collecting honest signal (does NOT mutate the model). The game reports
        # dead:true with hp refilled after death, so hp_frac<=0 alone misses it.
        _ws = rec.get("ws_after", {}) or {}
        _dead = _ws.get("dead") or (env._last_info.get("player", {}) or {}).get("dead")
        if (rec.get("outcome_kind") != "ENV_ERROR" and
            (_ws.get("hp_frac", 1.0) <= 0.0 or _dead or _ws.get("deaths", 0) > m["deaths"])):
            try:
                # GoalFSM: record the pre-death goal so respawn resumes the SAME
                # quest (death does NOT destroy the goal). enter_dead() preserves
                # self.pre_death_goal; resume_after_respawn() restores it.
                if goal_fsm is not None:
                    goal_fsm.enter_dead()
                _, alive = env.respawn()
                if not alive:
                    # RESPAWN_FAILED inside the in-loop glue: do NOT inflate
                    # respawns/counters or resume goals as if alive. The next
                    # cycle will re-attempt and eventually pause as ENV_ERROR.
                    m["bridge_errors"] += 1
                    print("[autonomous] respawn not confirmed (revived=false); will retry next cycle", flush=True)
                else:
                    m["respawns"] += 1
                    # after respawn, return to the goal we had before death
                    if goal_fsm is not None:
                        goal_fsm.resume_after_respawn()
                        # tag RESPAWN_SUCCESS in the replay buffer (rare event)
                        if replay is not None:
                            replay.add({
                                "state": "respawn", "action": "respawn",
                                "reward": 0.0, "next_state": "alive",
                                "done": False, "goal": goal_fsm.goal,
                                "skill": "respawn", "event": "RESPAWN_SUCCESS",
                            })
                rec["ws_after"] = snap(env._last_info)
            except BrowserBridgeError as e:
                # respawn can fail if the bridge is mid-reconnect or the game
                # tab is not ready. Do NOT crash the whole process, and do NOT
                # re-init the env here (BrowserEnv.__init__/reset also calls
                # respawn and would just re-raise). Record a bridge_error and
                # leave rec["ws_after"] as-is; the next loop iteration will
                # retry respawn. This keeps the process alive across transient
                # respawn failures instead of triggering the launcher restart.
                m["bridge_errors"] += 1
                print("respawn bridge_error (will retry next step): %s" % e, flush=True)

        ws = rec["ws_after"]
        info = env._last_info
        # FSM sync each step: the explicit current_goal must reflect the LATEST
        # observed world, not just the boot-time snapshot. (agent._cycle already
        # calls fsm.update_from_world on ws_before; this keeps goal_state.json
        # current for infra-restart resume.)
        if goal_fsm is not None:
            try:
                goal_fsm.update_from_world(ws)
            except Exception:
                pass
        a = rec["action"]
        m["steps"] += 1
        m["action_counts"][a] += 1
        m["xp"] = ws.get("xp", m["xp"])
        m["copper"] = ws.get("copper", m["copper"])
        m["deaths"] = ws.get("deaths", m["deaths"])
        m["kills"] = ws.get("kills", m["kills"])
        # --- LIVE per-step stdout (real-time window output) ---
        # Prints one compact line per step so the launcher window reflects what
        # the agent is doing instead of only the ~20s periodic summary.
        qstat = rec.get("ws_after", {}).get("quest_status") or (rec.get("ws_before", {}) or {}).get("quest_status") or "?"
        qp = rec.get("qprog")
        qps = f" qprog={qp}" if qp is not None else ""
        v = rec.get("verdict")
        print(f"[step {i}] {a} -> {v} | qs={qstat}{qps} | dist={ws.get('distance_to_giver')} hp={ws.get('hp_frac'):.2f} kills={m['kills']}", flush=True)
        # quests
        active = info.get("quests", {}).get("active") or []
        ready = info.get("quests", {}).get("ready") or []
        done = info.get("quests", {}).get("done") or []
        m["quests_done"] = max(m["quests_done"], len(done))
        m["quests_completed"] = max(m["quests_completed"], len(ready) + len(done))
        # vendors: distinct vendor NPCs ever seen nearby
        for e in (info.get("nearby") or []):
            if (e.get("kind") == "npc" or e.get("type") == "npc") and \
               (e.get("vendor") or e.get("vendorItems") or e.get("isVendor")):
                m["unique_npcs"].add("vendor:" + str(e.get("id") or e.get("name")))
        m["vendors_found"] = len([u for u in m["unique_npcs"] if str(u).startswith("vendor:")])
        # --- event counters from this step's action/verdict ---
        verdict = rec["verdict"]
        prev_inv = (rec["ws_before"] or {}).get("inv_slots", 0)
        cur_inv = ws.get("inv_slots", 0)
        if a == "accept_quest" and verdict in ("SUCCESS", "INCONCLUSIVE"):
            m["quests_accepted"] += 1  # явный инкремент (P1: исправление подсчёта)
        if a == "turn_in_quest":
            if verdict == "SUCCESS":
                m["quests_turned_in"] += 1
                m["navigation_success"] += 1
            elif verdict in ("FAILURE", "INCONCLUSIVE"):
                m["quest_turnin_failures"] += 1
                if verdict == "INCONCLUSIVE":
                    m["navigation_stuck"] += 1
                m["_last_turnin_partial"] = (verdict == "INCONCLUSIVE")
            # attribute to remembered giver (WorldMemory) vs fallback
            qid = (rec.get("ws_after", {}) or {}).get("quest_status")
            if world_mem.giver_pos(str((active + ready + done and (active + ready + done)[0].get("id", "")) or "")):
                m["giver_memory_hits"] += 1
            else:
                m["giver_memory_misses"] += 1
        if a == "return_to_giver":
            # Navigation Memory: маршрут «текущая позиция -> гивер»
            try:
                _ppos = env._last_info.get("player_pos") or [0, 0]
                _gpos = (ws.get("quest") or {}).get("giver_id")
                _gt = world_mem.giver_pos(str(_gpos)) if _gpos else None
                if not _gt and ws.get("distance_to_giver", 999) < 999:
                    # цель неизвестна точно — используем направление как ячейку
                    _gt = {"x": _ppos[0], "z": _ppos[1]}
                if _gt and _gt.get("x") is not None:
                    if m.get("_nav_route_key") is None:
                        m["_nav_route_key"] = nav_memory.record_attempt(_ppos, [_gt["x"], _gt["z"]])
                    _d0 = m.get("_nav_dist0")
                    _d1 = ws.get("distance_to_giver")
                    if _d0 is None:
                        m["_nav_dist0"] = _d1
                    progress = (_d0 - _d1) if (_d0 is not None and _d1 is not None) else 0.0
                    if verdict in ("SUCCESS", "FAILURE"):
                        nav_memory.record_result(m["_nav_route_key"],
                                                 success=(verdict == "SUCCESS"),
                                                 dist_progress=progress or 0.0)
                        m["_nav_route_key"] = None
                        m["_nav_dist0"] = None
                        if i % SAVE_EVERY == 0:
                            nav_memory.save()
            except Exception:
                traceback.print_exc()
            if verdict == "SUCCESS":
                m["navigation_success"] += 1
                if m["_last_turnin_partial"]:
                    m["navigation_recovery"] += 1
            elif verdict == "PARTIAL":
                m["navigation_stuck"] += 1
            if world_mem.giver_pos(str((active + ready + done and (active + ready + done)[0].get("id", "")) or "")):
                m["giver_memory_hits"] += 1
            else:
                m["giver_memory_misses"] += 1
        if a == "sell_junk":
            if verdict == "SUCCESS":
                m["items_sold"] += 1
                m["vendor_navigation_success"] += 1
            elif verdict in ("FAILURE", "INCONCLUSIVE"):
                m["sell_failures"] += 1
        # goal switch: policy changed high-level intent vs previous step
        goal_cat = a
        if m["prev_goal"] is not None and goal_cat != m["prev_goal"]:
            m["goal_switches"] += 1
        m["prev_goal"] = goal_cat
        # goal completed: a quest reached DONE this step
        if len(done) > m.get("_done_prev", 0):
            m["goal_completed"] += (len(done) - m.get("_done_prev", 0))
        m["_done_prev"] = len(done)
        # running reward mean
        m["reward_mean"] = (m["reward_mean"] * (m["steps"] - 1) + rec["reward"]) / m["steps"]
        # exploration
        cell = cell_of(info.get("player_pos"))
        m["explored_cells"].add(cell)
        for e in (info.get("nearby") or []):
            if e.get("kind") == "npc":
                m["unique_npcs"].add(e.get("id") or e.get("name") or str(e.get("x"))+","+str(e.get("z")))
        # --- long-horizon learning telemetry (user audit 2026-08-18) ---
        # Measure the ACTUAL causal chain, not just "got a negative reward":
        #   negative experience -> same/similar state -> SAME action (repeated_mistake)
        #                          -> DIFFERENT action (recovery)
        # Uses the exact bucket key the policy reads (memory._bucket over the
        # shared WorldState). Previously `bucket` was hardcoded to None, so these
        # metrics were never computed and neg_lessons could NOT prove learning.
        bucket = None
        bucket_after = None
        neg = rec["reward"] < -0.1
        was_repeat = False
        if rec["outcome_kind"] != "ENV_ERROR":
            bucket = _bucket(rec["ws_before"])
            bucket_after = _bucket(rec["ws_after"])
        if neg:
            m["neg_lessons"] += 1
        if bucket is not None:
            prev_act = last_bucket_action.get(bucket)
            prev_neg = last_bucket_neg.get(bucket, False)
            # recovery: previous step in THIS bucket was negative, now a
            # DIFFERENT action chosen -> behaviour adapted to experience.
            if prev_neg and prev_act is not None and prev_act != a:
                m["recovery_after_neg"] += 1
            # repeated mistake: this (bucket, action) already produced a negative
            # lesson before, and we chose it AGAIN in the same bucket.
            if (bucket, a) in neg_state_action:
                m["repeated_mistakes"] += 1
                was_repeat = True
            if neg:
                neg_state_action.add((bucket, a))
            last_bucket_action[bucket] = a
            last_bucket_neg[bucket] = neg
        # windowed Level-4 metrics (trend across windows of WINDOW steps)
        m["win_reward"] += rec["reward"]
        m["win_steps"] += 1
        m["win_actions"][a] += 1
        dnew = ws.get("deaths", 0)
        dold = m["deaths_prev"]  # сохраняем старое значение для проверки
        if dnew > dold:
            m["win_deaths"] += (dnew - dold)
            m["deaths_prev"] = dnew
        if was_repeat:
            m["win_repeat"] += 1
        # --- replay buffer + strategy memory (user 2026-08-20) ---
        # Build a transition record and store it. Rare events get sampling boost.
        _q = ws.get("quest") or {}
        _event = None
        if a == "accept_quest" and verdict == "SUCCESS":
            _event = "QUEST_ACCEPT_SUCCESS"
        elif a == "turn_in_quest" and verdict == "SUCCESS":
            _event = "QUEST_TURNIN_SUCCESS"
        elif a == "return_to_giver" and verdict == "SUCCESS":
            _event = "OBJECTIVE_PROGRESS"  # arrived at giver = navigation progress
        elif a == "sell_junk" and verdict == "SUCCESS":
            _event = "VENDOR_SUCCESS"
        elif rec["outcome_kind"] != "ENV_ERROR" and dnew > dold:  # используем dold (старое значение)
            _event = "DEATH"
        # navigation success on return/turn_in already counted; tag as progress
        if a in ("return_to_giver", "turn_in_quest") and verdict == "SUCCESS":
            _event = "OBJECTIVE_PROGRESS" if _event is None else _event
        if a == "turn_in_quest" and verdict == "FAILURE":
            _event = "QUEST_FAIL"
        replay.add({
            "state": rec.get("ws_before"),
            "action": a,
            "reward": rec["reward"],
            "next_state": rec.get("ws_after"),
            "done": (rec.get("outcome_kind") == "ENV_ERROR"),
            "goal": goal_fsm.goal,
            "skill": a,
            "event": _event,
        })
        # strategy memory: record per-quest outcomes
        if _q.get("id"):
            # шаговая статистика (НЕ определяет стратегию — именно смешение
            # этих двух вещей дало 12024 ложных «успеха» у q_greyjaw)
            strat_mem.record_step(f"quest:{_q['id']}", a, verdict == "SUCCESS")

        # ШАГИ 3-4 спеки (2026-08-24): события мира -> рефлексия -> хинты, и
        # ФАКТ завершения квеста -> StrategyMemory (а не вердикт шага).
        try:
            _events = ebus.observe(env._last_info or {})
            if _events:
                refl.observe_events(_events)
                for _ev in _events:
                    if _ev.get("type") == "QuestCompleted":
                        _qid = _ev.get("quest_id")
                        if _qid:
                            # успех приписываем действию, которым дошли до сдачи
                            strat_mem.record_completion(f"quest:{_qid}", a)
                            strat_mem.save()
                            print(f"[learn] квест {_qid} сдан навыком {a} -> стратегия сохранена",
                                  flush=True)
                # выводы из событий сразу становятся хинтами политики
                _ev_hints = refl.event_conclusions()
                if _ev_hints:
                    for _h in _ev_hints:
                        agent.policy.hints[_h["key"]] = _h
        except Exception:
            traceback.print_exc()
        # R2 FIX (2026-08-23): observe EVERY step. Previously observe() lived
        # inside `if i % SAVE_EVERY == 0`, so the 30-entry window needed ~3000
        # steps and the journal was never written in a 3000-step run — hints
        # never existed. reflect() stays on the SAVE_EVERY cadence.
        try:
            refl.observe(rec)
        except Exception:
            traceback.print_exc()
        # Failure Analyzer (план 2026-08-24, п.4): каждая FAILURE ->
        # структурированная причина {failure, cause, fix, retry}.
        try:
            _fa_rec = fail_analyzer.observe_step({
                "step": i, "action": a, "verdict": rec["verdict"],
                "kind": rec["outcome_kind"], "hp": ws.get("hp_frac"),
                "dist": ws.get("distance_to_giver"), "goal": goal_fsm.goal,
                "quest_status": ws.get("quest_status"),
                "cell": cell, "deaths": ws.get("deaths"),
                "error": rec.get("error") or "",
            })
            if i % SAVE_EVERY == 0:
                fail_analyzer.save()
            if _fa_rec and i % 500 == 0:
                print(f"[failures] {_fa_rec['action']}: {_fa_rec['cause']} -> {_fa_rec['fix']}",
                      flush=True)
        except Exception:
            traceback.print_exc()
        # periodic replay buffer flush (cheap, atomic) + training pass
        if i % SAVE_EVERY == 0:
            replay.save()
            strat_mem.save()
            # SELF-REFLECTION (the 'делал выводы' step): review the recent window,
            # draw conclusions, persist them to the journal. Conclusions carry
            # machine hints consumed via reflector.hints() by the policy layer.
            try:
                conclusions = refl.reflect()
                for c in conclusions:
                    print(f"[reflect] {c['kind']}: {c['detail']}", flush=True)
                # R4 FIX: push fresh journal hints into the live policy —
                # without this the loop was closed in tests only.
                if agent.refresh_hints():
                    print(f"[reflect] hints active: "
                          f"{sorted(agent.policy.hints)}", flush=True)
            except Exception:
                traceback.print_exc()
            # Rare-event training pass: replay stored transitions (accept/turn_in/
            # progress/death weighted higher) so 1000 explore steps cannot drown
            # one useful turn_in. This is the actual "learn from buffer, not just
            # the last transition" fix.
            try:
                trained = mem.train_from_replay(replay, batch=64)
                if trained:
                    print(f"[replay] trained {trained} transitions (buf={len(replay)})",
                          flush=True)
            except Exception:
                traceback.print_exc()
        # log one line
        row = {
            "step": i, "pid": os.getpid(), "t": round(time.time() - start, 1),
            "action": a, "verdict": rec["verdict"], "kind": rec["outcome_kind"],
            "reward": round(rec["reward"], 3),
            "bucket_before": bucket, "bucket_after": bucket_after,
            "hp": round(ws.get("hp_frac", 0), 2),
            "quest_status": ws.get("quest_status"),
            "goal": goal_fsm.goal,
            "dist": round(ws.get("distance_to_giver", 0), 1),
            "kills": ws.get("kills"), "xp": ws.get("xp"),
            "qprog": ws.get("quest_progress"), "cell": cell,
            "deaths": ws.get("deaths"),
        }
        logf.write(json.dumps(row, ensure_ascii=False) + "\n")
        logf.flush()  # ensure per-step progress lands on disk even if the process is killed
        # episodic memory (spec 2026-08-23): every attempt recorded for the LLM brain
        episodes.append({
            "t": time.time(), "quest": goal_fsm.quest_id, "step": i,
            "action": a, "result": rec["verdict"],
            "reason": rec.get("outcome_kind"), "hp_frac": ws.get("hp_frac"),
            "phase": goal_fsm.goal,
        })
        brain_fail_streak = brain_fail_streak + 1 if rec["verdict"] == "FAILURE" else 0
        if i % SAVE_EVERY == 0:
            mem.save()
            _summary(m, i, start, logf, fail_analyzer=fail_analyzer)
        if (i + 1) % WINDOW == 0:
            _window_summary(m, i, logf)
            m["win_reward"] = 0.0
            m["win_deaths"] = 0
            m["win_repeat"] = 0
            m["win_actions"] = Counter()
            m["win_steps"] = 0

    mem.save()
    logf.close()
    env.close()
    _summary(m, m["steps"], start, None, final=True, fail_analyzer=fail_analyzer)
    # P0.7: честный учёт — сколько шагов дали ОБУЧАЮЩИЙ переход, а сколько
    # были навигационными подшагами в обход agent.step(). Без этой строки
    # "прогнали 5000 шагов" читается как "собрали 5000 переходов", что неверно.
    print("[accounting] learning_steps=%d nav_substeps=%d autonomy_errors=%d "
          "(autonomy=%s)"
          % (_learning_steps, _nav_substeps, _autonomy_errors,
             "on" if autonomy is not None else "OFF"), flush=True)
    # V0 baseline: сохраняем трассу + сводку контура одним файлом.
    try:
        _payload = {
            "accounting": {
                "environment_steps": m.get("steps"),
                "learning_steps": _learning_steps,
                "nav_substeps": _nav_substeps,
                "autonomy_errors": _autonomy_errors,
                "skill_attempts": len(_step_trace),
                "autonomy_enabled": autonomy is not None,
            },
            "autonomy_stats": (autonomy.summary()
                               if autonomy is not None
                               and hasattr(autonomy, "summary") else None),
            "steps": _step_trace,
        }
        with open(_TRACE_OUT, "w", encoding="utf-8") as _tf:
            json.dump(_payload, _tf, ensure_ascii=False, indent=1, default=str)
        print("[trace] %d шагов -> %s" % (len(_step_trace), _TRACE_OUT),
              flush=True)
    except Exception:
        traceback.print_exc()
    print(f"\n[autonomous] done. log -> {LOG_PATH}, memory -> {EXP_PATH}")
    # release the single-instance lock so a future launch can start cleanly
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


def _summary(m, i, start, logf, final=False, fail_analyzer=None):
    el = time.time() - start
    # главный показатель долгосрочной автономности
    qtr = (m["quests_turned_in"] / m["quests_completed"]) if m["quests_completed"] else 0.0
    gm_hit = m["giver_memory_hits"]
    gm_miss = m["giver_memory_misses"]
    gm_rate = (gm_hit / (gm_hit + gm_miss)) if (gm_hit + gm_miss) else 0.0
    msg = (f"\n=== {'FINAL' if final else f'step {i}'} autonomous summary "
           f"(t={el:.0f}s, {m['steps']} steps) ===\n"
           f"  kills={m['kills']} quests_accepted={m['quests_accepted']} "
           f"quests_completed={m['quests_completed']} quests_turned_in={m['quests_turned_in']}\n"
           f"  QUEST_TURNIN_RATE={qtr:.2%}  goal_completed={m['goal_completed']} deaths={m['deaths']} respawns={m['respawns']}\n"
           f"  xp={m['xp']} copper={m['copper']} explored_cells={len(m['explored_cells'])} "
           f"unique_npcs={len(m['unique_npcs'])} env_errors={m['env_errors']}\n"
           f"  giver_memory: hits={gm_hit} misses={gm_miss} rate={gm_rate:.0%}\n"
           f"  vendors_found={m['vendors_found']} items_sold={m['items_sold']} sell_failures={m['sell_failures']}\n"
           f"  nav_success={m['navigation_success']} nav_stuck={m['navigation_stuck']} nav_recovery={m['navigation_recovery']}\n"
           f"  quest_turnin_failures={m['quest_turnin_failures']} programming_errors={m['programming_errors']} bridge_errors={m['bridge_errors']} episodes={m['episodes']}\n"
           f"  neg_lessons={m['neg_lessons']} repeated_mistakes={m['repeated_mistakes']} "
           f"recovery_after_neg={m['recovery_after_neg']} goal_switches={m['goal_switches']}\n"
           f"  {(fail_analyzer.summary_line() if fail_analyzer else 'failures=n/a')}"
           f" | top_fixes={(dict(fail_analyzer.fixes.most_common(3)) if fail_analyzer else {})}\n"
           f"  reward_mean={m['reward_mean']:+.3f} actions={dict(m['action_counts'])}\n")
    print(msg)
    if logf is not None:
        logf.write(msg + "\n")
    if final:
        _window_summary(m, i, logf)


def _window_summary(m, i, logf):
    ws_ = m["win_steps"] or 1
    dist = {k: f"{v/ws_*100:.1f}%" for k, v in m["win_actions"].items()}
    msg = (f"\n--- window ending step {i} (last {m['win_steps']} steps) ---\n"
           f"  reward/100steps = {m['win_reward']/ws_*100:.2f}\n"
           f"  death/100steps  = {m['win_deaths']/ws_*100:.2f}\n"
           f"  repeated_error_rate = {m['win_repeat']/ws_*100:.2f}%\n"
           f"  action_dist = {dist}\n")
    print(msg)
    if logf is not None:
        logf.write(msg + "\n")


if __name__ == "__main__":
    sys.exit(main())

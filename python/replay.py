"""Extended Replay Buffer — full autonomy context per transition.

Task 8 (ARCHITECTURE §10 intent): a replay transition must carry not just
(state, action, reward) but the WHOLE autonomy context so training and
analysis can see *why* an action succeeded or failed:

    state, action, next_state, reward,
    goal, subgoal, skill,
    skill_result   (SUCCESS / FAILURE / NO_OP),
    failure_reason,
    progress_delta (detect_progress output),
    episode_id, timestamp

We deliberately REUSE the existing detectors instead of reimplementing them:
  - progress.py:  detect_progress(before_obs, after_obs) -> delta dict
                  classify_outcome(progress) -> SUCCESS/FAILURE/NO_OP
  - skill_contracts.py: verify_postconditions(skill, progress) -> missing postconditions

`ExtendedReplayBuffer` subclasses the battle-tested `ReplayBuffer`
(replay_buffer.py) so it keeps the bounded deque (maxlen eviction) and the
rare-event-prioritized `sample()` used by ExperienceStore.train_from_replay.
Each stored transition is a drop-in for the legacy replay format (it still
has state/action/reward/next_state), so no caller changes are required.
"""

import os
import time
import json
import tempfile
import traceback
from typing import Dict, List, Optional

from progress import detect_progress, classify_outcome
from skill_contracts import verify_postconditions
from replay_buffer import (
    ReplayBuffer,
    EVENT_SAMPLE_WEIGHT,
    COMMON_WEIGHT,
    set_to_list,
)


def create_transition(state, action, next_state, reward,
                      goal=None, subgoal=None, skill=None,
                      before_obs=None, after_obs=None,
                      skill_result=None, failure_reason=None,
                      episode_id=None, timestamp=None) -> Dict:
    """Build one extended transition dict from raw step data.

    `before_obs` / `after_obs` are the raw WorldState observations bracketing
    the action; detect_progress() turns them into `progress_delta`, and
    classify_outcome() derives `skill_result` when the caller does not pass it
    explicitly. When a skill FAILED and no reason was supplied, we enrich
    `failure_reason` with the postconditions (skill_contracts.verify_postconditions)
    that the action did not satisfy, so the recovery manager has actionable info.
    """
    before_obs = before_obs or {}
    after_obs = after_obs or {}
    progress = detect_progress(before_obs, after_obs)

    if skill_result is None:
        skill_result = classify_outcome(progress)

    if failure_reason is None and skill is not None and skill_result == "FAILURE":
        missing = verify_postconditions(skill, progress).get("missing", [])
        failure_reason = ",".join(missing) if missing else None

    if timestamp is None:
        timestamp = time.time()

    return {
        "state": state,
        "action": action,
        "next_state": next_state,
        "reward": reward,
        "goal": goal,
        "subgoal": subgoal,
        "skill": skill,
        "skill_result": skill_result,
        "failure_reason": failure_reason,
        "progress_delta": progress,
        "episode_id": episode_id,
        "timestamp": timestamp,
    }


class ExtendedReplayBuffer(ReplayBuffer):
    """ReplayBuffer whose transitions carry the full autonomy context.

    Adds: episode tracking (start_episode), a convenience add_transition()
    that stamps the current episode_id, and the query helpers
    last_failures(skill) / success_rate(skill).
    """

    def __init__(self, cap: int = 20000, path: Optional[str] = None,
                 rare_boost: float = 4.0):
        # episode counter must exist before super().__init__() calls _load(),
        # which may restore it from disk.
        self._episode_seq = 0
        self.episode_id = None
        super().__init__(cap=cap, path=path, rare_boost=rare_boost)

    # ---- episode management ------------------------------------------------
    def start_episode(self) -> str:
        """Begin a new episode; subsequent transitions get a fresh episode_id."""
        self._episode_seq += 1
        self.episode_id = "ep%d" % self._episode_seq
        return self.episode_id

    # ---- ingest ------------------------------------------------------------
    def add(self, transition: Dict):
        """Store a transition, stamping the current episode_id if absent.

        Sampling weight: FAILURE transitions are treated as rare events
        (boosted, like QUEST_FAIL) so the learning loop keeps seeing why
        skills go wrong instead of drowning them in SUCCESS steps.
        """
        item = dict(transition)
        if item.get("episode_id") is None:
            item["episode_id"] = self.episode_id
        sr = item.get("skill_result")
        if sr == "FAILURE":
            w = EVENT_SAMPLE_WEIGHT.get("QUEST_FAIL", 5.0) * self.rare_boost
        else:
            w = COMMON_WEIGHT
        item["_w"] = w
        self.buffer.append(item)

    def add_transition(self, state, action, next_state, reward, goal=None,
                       subgoal=None, skill=None, before_obs=None, after_obs=None,
                       skill_result=None, failure_reason=None, episode_id=None,
                       timestamp=None) -> Dict:
        """Build (create_transition) + store in one call, stamping the episode."""
        episode_id = self.episode_id if episode_id is None else episode_id
        t = create_transition(
            state=state, action=action, next_state=next_state, reward=reward,
            goal=goal, subgoal=subgoal, skill=skill,
            before_obs=before_obs, after_obs=after_obs,
            skill_result=skill_result, failure_reason=failure_reason,
            episode_id=episode_id, timestamp=timestamp,
        )
        self.add(t)
        return t

    # ---- query helpers -----------------------------------------------------
    def last_failures(self, skill, limit: int = 20) -> List[Dict]:
        """Most recent FAILURE transitions for `skill`, newest first (max `limit`)."""
        fails = [t for t in self.buffer
                 if t.get("skill") == skill and t.get("skill_result") == "FAILURE"]
        return list(reversed(fails[-limit:]))

    def success_rate(self, skill) -> float:
        """Fraction of stored transitions for `skill` that are SUCCESS.

        Returns 0.0 when the skill has no transitions (not a divide-by-zero
        crash), so it is safe to call for unseen skills.
        """
        rows = [t for t in self.buffer if t.get("skill") == skill]
        if not rows:
            return 0.0
        succ = sum(1 for t in rows if t.get("skill_result") == "SUCCESS")
        return succ / len(rows)

    # ---- persistence (override to carry episode_seq) -----------------------
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("buffer") or []
            for it in items[-self.cap:]:
                self.buffer.append(it)
            self._episode_seq = int(data.get("episode_seq", 0) or 0)
        except Exception:
            return

    def save(self):
        try:
            d = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".rbx_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # Bounded tail as the legacy buffer; the deque is the runtime
                # source of truth. default=set_to_list keeps any set-valued
                # transition fields (e.g. keepIds) JSON-safe.
                json.dump(
                    {"buffer": list(self.buffer)[-5000:],
                     "episode_seq": self._episode_seq},
                    f, ensure_ascii=False, indent=0, default=set_to_list,
                )
            os.replace(tmp, self.path)
        except Exception:
            traceback.print_exc()

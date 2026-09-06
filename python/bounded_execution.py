"""bounded_execution.py — bounded execution guarantees for autonomous agent.

Ensures the agent cannot run forever, loop infinitely, or die repeatedly
without making progress. On any bound breach, the main loop should stop
and trigger graceful shutdown (save state, log reason, exit cleanly).

Bounds:
- wall_clock_limit: max seconds to run (default 3600 = 60 min)
- max_decisions: max learning steps (default 10000)
- max_repeated_action: same action N times consecutively (default 100)
- max_recovery_streak: consecutive recovery actions (default 50)
- max_dead_streak: consecutive deaths without progress (default 10)

Environment variables:
- WOC_WALL_CLOCK_LIMIT: override wall_clock_limit (seconds)
- WOC_MAX_DECISIONS: override max_decisions
- WOC_MAX_REPEATED_ACTION: override max_repeated_action
- WOC_MAX_RECOVERY_STREAK: override max_recovery_streak
- WOC_MAX_DEAD_STREAK: override max_dead_streak
- WOC_BOUNDED: set to "0" to disable bounded execution
"""

import os
import time
import signal
import sys
from typing import Optional, Tuple

# Default bounds — can be overridden via environment variables
DEFAULT_WALL_CLOCK_LIMIT = int(os.environ.get("WOC_WALL_CLOCK_LIMIT", "3600"))
DEFAULT_MAX_DECISIONS = int(os.environ.get("WOC_MAX_DECISIONS", "10000"))
DEFAULT_MAX_REPEATED_ACTION = int(os.environ.get("WOC_MAX_REPEATED_ACTION", "100"))
DEFAULT_MAX_RECOVERY_STREAK = int(os.environ.get("WOC_MAX_RECOVERY_STREAK", "50"))
DEFAULT_MAX_DEAD_STREAK = int(os.environ.get("WOC_MAX_DEAD_STREAK", "10"))


class BoundedExecution:
    """Track all execution bounds and detect breaches.

    Usage:
        bounds = BoundedExecution(wall_clock_limit=3600)
        bounds.install_signal_handler()

        for i in range(N):
            should_stop, reason = bounds.check(decisions=learning_steps)
            if should_stop:
                break

            # ... do step, get action, outcome ...

            bounds.record_step(action=a, is_recovery=is_recovery,
                               is_death=is_death, is_progress=is_progress)
    """

    def __init__(self,
                 wall_clock_limit: float = DEFAULT_WALL_CLOCK_LIMIT,
                 max_decisions: int = DEFAULT_MAX_DECISIONS,
                 max_repeated_action: int = DEFAULT_MAX_REPEATED_ACTION,
                 max_recovery_streak: int = DEFAULT_MAX_RECOVERY_STREAK,
                 max_dead_streak: int = DEFAULT_MAX_DEAD_STREAK):
        self.wall_clock_limit = wall_clock_limit
        self.max_decisions = max_decisions
        self.max_repeated_action = max_repeated_action
        self.max_recovery_streak = max_recovery_streak
        self.max_dead_streak = max_dead_streak

        self.start_time = time.time()
        self._signal_received = False

        # State tracking
        self.last_action: Optional[str] = None
        self.repeated_action_count: int = 0
        self.recovery_streak: int = 0
        self.dead_streak: int = 0

    def install_signal_handler(self):
        """Install SIGTERM/SIGINT handler to trigger graceful shutdown."""
        def handler(signum, frame):
            self._signal_received = True
        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def check(self, decisions: int = 0) -> Tuple[bool, Optional[str]]:
        """Check all bounds. Returns (should_stop, reason).

        Call this at the TOP of every loop iteration (before any work).
        """

        # Signal received (SIGTERM / SIGINT)
        if self._signal_received:
            return True, "signal_received"

        # Wall clock limit
        elapsed = time.time() - self.start_time
        if elapsed >= self.wall_clock_limit:
            return True, f"wall_clock_limit ({elapsed:.0f}s >= {self.wall_clock_limit:.0f}s)"

        # Max decisions (learning steps)
        if decisions >= self.max_decisions:
            return True, f"max_decisions ({decisions} >= {self.max_decisions})"

        # Max repeated action (consecutive same action)
        if self.repeated_action_count >= self.max_repeated_action:
            return True, (f"max_repeated_action ({self.repeated_action_count}x "
                          f"{self.last_action})")

        # Max recovery streak (consecutive recovery actions)
        if self.recovery_streak >= self.max_recovery_streak:
            return True, f"max_recovery_streak ({self.recovery_streak})"

        # Max dead streak (consecutive deaths without progress)
        if self.dead_streak >= self.max_dead_streak:
            return True, f"max_dead_streak ({self.dead_streak})"

        return False, None

    def record_step(self, action: str, is_recovery: bool = False,
                    is_death: bool = False, is_progress: bool = False):
        """Record a step's outcome. Call this AFTER each learning step.

        Args:
            action: the action taken
            is_recovery: True if this step was a recovery action
            is_death: True if the agent died this step
            is_progress: True if meaningful progress was made (kill, quest turn-in, etc.)
        """
        # Track consecutive same action
        if action == self.last_action:
            self.repeated_action_count += 1
        else:
            self.last_action = action
            self.repeated_action_count = 1

        # Track recovery streak
        if is_recovery:
            self.recovery_streak += 1
        else:
            self.recovery_streak = 0

        # Track dead streak
        if is_death:
            self.dead_streak += 1
        if is_progress:
            self.dead_streak = 0

    def elapsed(self) -> float:
        """Seconds since start."""
        return time.time() - self.start_time

    def summary(self) -> dict:
        """Return current bound status for logging."""
        return {
            "elapsed_s": round(self.elapsed(), 1),
            "repeated_action_count": self.repeated_action_count,
            "last_action": self.last_action,
            "recovery_streak": self.recovery_streak,
            "dead_streak": self.dead_streak,
        }

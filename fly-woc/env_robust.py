"""env_robust.py — make long WoC training runs survive a dying env server.

Why this exists (the crash we hit on Windows):

  WoWClassicEnv spawns the node server with ``stderr=subprocess.DEVNULL``, so when
  the server dies the reason is discarded, and the next request then fails with
  ``OSError: [Errno 22] Invalid argument`` from ``stdin.write`` (write to a broken
  pipe) - *before* the friendly "env server died" check. With ``--envs 8`` a single
  dead server killed the whole run, with no clue why.

What this adds:

  * the server is spawned with stderr captured into a ring buffer, so the real
    cause (node OOM, uncaught throw, stale bundle) is reported with a traceback;
  * ``EnvServerDied`` carries the exit code and the last stderr lines;
  * a dead server is restarted in place - ``reset``/``info`` retry transparently,
    while ``step`` never does (replaying a step into a fresh world would silently
    fabricate a transition);
  * the game checkout is NOT modified: this is a subclass.

Usage:
    WOC_PYTHON_PATH=/path/to/world-of-claudecraft/python python train.py --envs 4
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import threading
from typing import Any

sys.path.insert(0, os.environ.get("WOC_PYTHON_PATH", ""))


class EnvServerDied(RuntimeError):
    """The node env server exited (or its pipe broke) mid-request."""


try:                                    # the base env lives in the game checkout
    from wow_env import WoWClassicEnv as _Base  # noqa: E402
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:                # pragma: no cover - reported by train.py
    _Base = object  # type: ignore[assignment,misc]
    _IMPORT_ERROR = exc


class RobustWoWEnv(_Base):  # type: ignore[misc,valid-type]
    """WoWClassicEnv + stderr capture, crash diagnostics and auto-restart."""

    def __init__(self, *args, max_restarts: int = 200, keep_stderr: int = 80, **kwargs):
        if _Base is object:
            raise ImportError(
                "wow_env not importable; set WOC_PYTHON_PATH to the game's python/ dir"
            ) from _IMPORT_ERROR
        self._max_restarts = max_restarts
        self._restarts = 0
        self._stderr_ring: collections.deque[str] = collections.deque(maxlen=keep_stderr)
        self._respawning = False
        # remember how to respawn: the base class keeps these as locals only
        self._node_binary = kwargs.get("node_binary", "node")
        server_path = kwargs.get("server_path")
        self._server_path = os.path.abspath(server_path) if server_path else None
        super().__init__(*args, **kwargs)       # spawns its own (devnull-stderr) proc
        self._upgrade_proc()

    # ---------------------------------------------------------------- spawning
    def _spawn(self):
        from wow_env import _DEFAULT_SERVER  # type: ignore[attr-defined]
        server = self._server_path or os.path.abspath(_DEFAULT_SERVER)
        proc = subprocess.Popen(
            [self._node_binary, server],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Windows: no console window flash per env process
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()
        return proc

    def _drain_stderr(self, proc) -> None:
        try:
            for line in proc.stderr:            # type: ignore[union-attr]
                line = line.rstrip()
                if line:
                    self._stderr_ring.append(line)
        except (ValueError, OSError):
            pass

    def _upgrade_proc(self) -> None:
        """Swap the base class's stderr-devnull process for a monitored one."""
        old = getattr(self, "_proc", None)
        self._proc = self._spawn()
        if old is not None:
            try:
                old.kill()
                old.wait(timeout=5)
            except Exception:
                pass
        self._request({"cmd": "info"})          # warm up + refresh metadata

    # ---------------------------------------------------------------- requests
    def _crash_report(self, exc: BaseException) -> str:
        code = None
        try:
            code = self._proc.poll()
        except Exception:
            pass
        tail = list(self._stderr_ring)[-12:]
        shown = "\n".join(f"      {ln}" for ln in tail) if tail else "      (node wrote nothing to stderr)"
        return (f"env server died: {type(exc).__name__}: {exc}\n"
                f"    exit code: {code}, restarts so far: {self._restarts}\n"
                f"    last stderr from node:\n{shown}")

    @staticmethod
    def _is_death(exc: BaseException) -> bool:
        if isinstance(exc, (BrokenPipeError, OSError, ValueError)):
            return True
        return isinstance(exc, RuntimeError) and "env server died" in str(exc)

    def _request(self, msg: dict[str, Any], _allow_retry: bool | None = None):  # type: ignore[override]
        """Retry policy is per command, not per call site.

        ``step`` must never be retried: replaying it into a freshly restarted
        server would either fabricate a transition or (as the real server does)
        answer ``call reset first``, which then looks like a game error. ``close``
        is not retried either - there is nothing to talk to afterwards.
        """
        if _allow_retry is None:
            _allow_retry = msg.get("cmd") not in ("step", "close")
        try:
            return super()._request(msg)
        except Exception as exc:                # noqa: BLE001 - classified right here
            if not self._is_death(exc):
                raise                            # {"error": ...} - a real game error, keep it
            report = self._crash_report(exc)
            if not _allow_retry:
                raise EnvServerDied(report) from exc
            self.restart()
            print(f"[env_robust] {report}\n    -> restarted server #{self._restarts}", file=sys.stderr)
            return super()._request(msg)

    # ------------------------------------------------------------------ public
    @property
    def restarts(self) -> int:
        return self._restarts

    def restart(self) -> None:
        """Respawn the server. Sim state is gone: the caller must reset()."""
        if self._respawning:
            return
        if self._restarts >= self._max_restarts:
            raise EnvServerDied(
                f"env server died {self._restarts} times (limit {self._max_restarts}); "
                "last stderr:\n" + "\n".join(f"  {ln}" for ln in list(self._stderr_ring)[-20:]))
        self._respawning = True
        try:
            old = self._proc
            self._proc = self._spawn()
            self._restarts += 1
            try:
                if old.poll() is None:
                    old.kill()
                old.wait(timeout=5)
            except Exception:
                pass
            self._request({"cmd": "info"}, _allow_retry=False)
        finally:
            self._respawning = False

    def step(self, action):                     # type: ignore[override]
        """Base step() semantics (the 5-tuple), never retried transparently.

        A replayed step would apply an action to a fresh world and fabricate a
        transition, so a dead server raises EnvServerDied and the caller decides
        (EnvBatch restarts the server and resets that env).
        """
        try:
            return super().step(action)
        except Exception as exc:                # noqa: BLE001
            if not self._is_death(exc):
                raise
            raise EnvServerDied(self._crash_report(exc)) from exc

    def reset(self, **kwargs):                  # type: ignore[override]
        # safe to retry: the caller asked for a fresh episode anyway
        try:
            return super().reset(**kwargs)
        except Exception as exc:                # noqa: BLE001
            if not self._is_death(exc):
                raise
            self.restart()
            return super().reset(**kwargs)

    def close(self):                            # type: ignore[override]
        try:
            super().close()
        finally:
            self._respawning = True             # stop any further respawn attempts

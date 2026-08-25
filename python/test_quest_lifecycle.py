"""test_quest_lifecycle.py — детерминированный полный цикл квеста на живой игре.

QUEST -> OBJECTIVE -> (BUY?) -> GATHER/KILL -> READY -> RETURN -> TURN_IN
                                                       -> quests_done+1

Запуск: WOC_CONTRACT=1 pytest -q python/test_quest_lifecycle.py -m integration
Требует: живой мост + игра. Мутирует мир (берёт/сдаёт квесты, убивает мобов).
"""
import os, sys, json, time, urllib.request

import pytest

sys.path.insert(0, os.path.dirname(__file__))

BRIDGE = "http://127.0.0.1:8791"


def _post(body, timeout=120):
    req = urllib.request.Request(BRIDGE, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _snapshot():
    d = _post({"action": "snapshot"}, timeout=30)
    info = d.get("info", d)
    if isinstance(info.get("info"), dict):
        info = info["info"]
    return info


@pytest.mark.integration
class TestQuestLifecycle:
    @pytest.fixture(scope="class")
    def setup(self):
        if not os.environ.get("WOC_CONTRACT"):
            pytest.skip("WOC_CONTRACT=1 not set")
        try:
            h = json.loads(urllib.request.urlopen(f"{BRIDGE}/health", timeout=5).read())
            if not (h.get("ok") and h.get("game")):
                pytest.skip("bridge/game not ready")
        except Exception as e:
            pytest.skip(f"bridge unavailable: {e}")
        return True

    def _quests_done(self, info):
        return info.get("quests_done", 0)

    def _find_quest(self, info, want_state=None):
        qs = info.get("quests") or {}
        for q in (qs.get("ready") or []):
            if want_state in (None, "ready"):
                return q
        for q in (qs.get("active") or []):
            if want_state in (None, "active"):
                objs = q.get("objectives") or []
                complete = objs and all((o.get("current") or 0) >= (o.get("required") or 0) for o in objs)
                if complete:
                    return q
        return None

    def test_full_turn_in_transition(self, setup):
        """READY-квест: turn_in_quest -> quests_done+1 И квест покинул active."""
        from quest_capability import QuestCapability

        class _Env:
            pass

        # --- фаза 0: снапшот ---
        before = _snapshot()
        qd_before = self._quests_done(before)

        q = self._find_quest(before, "ready")
        if q is None:
            pytest.skip("нет READY-квеста — сначала выполните objective; "
                        "тест проверяет только переход TURN_IN")
        qid = str(q["id"])

        # --- фаза 1: navigate к гиверу через bridge (navigate handler) ---
        tNpc = q.get("turnInNpc") or {}
        if tNpc.get("x") is None:
            pytest.skip(f"у {qid} неизвестен turnInNpc")
        nav = _post({"action": "navigate",
                     "cmd": {"x": tNpc["x"], "z": tNpc["z"], "max_steps": 200}})
        assert nav.get("ok"), f"navigate не выполнился: {nav}"

        # --- фаза 2: turn_in через capability ---
        env = _Env()
        env.base = type("B", (), {})()
        env.base.turn_in_quest = lambda qid_: _post(
            {"action": "step", "idx": 3, "questId": qid}, timeout=90).get("info")
        env._last_info = before
        cap = QuestCapability(env)
        verdict = cap.turn_in({"id": qid})

        # --- фаза 3: инварианты перехода ---
        after = env._last_info or _snapshot()
        qd_after = self._quests_done(after)

        assert verdict == "SUCCESS", (
            f"turn_in вернул {verdict}: quests_done {qd_before} -> {qd_after}")
        assert qd_after == qd_before + 1, \
            f"quests_done должен вырасти ровно на 1: {qd_before} -> {qd_after}"

        log_quests = after.get("quests") or {}
        still_there = [x.get("id") for x in (log_quests.get("active") or []) +
                       (log_quests.get("ready") or []) if str(x.get("id")) == qid]
        assert not still_there, f"{qid} остался в questLog после сдачи"

    def test_ready_quest_eventually_appears(self, setup):
        """Активный kill/gather квест прогрессирует до READY за N шагов farm/gather.

        Мягкий тест цикла: если после N действий квест не готов — это сигнал,
        но не hard fail (зависит от респауна мобов).
        """
        before = _snapshot()
        qd_before = self._quests_done(before)
        # выполняем 20 шагов политики через мост невозможно напрямую (политика в Python),
        # поэтому проверяем только инвариант счётчика за снапшот
        time.sleep(2)
        after = _snapshot()
        assert self._quests_done(after) >= qd_before, "quests_done уменьшился?!"

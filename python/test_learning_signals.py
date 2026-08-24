import os, sys
sys.path.insert(0, os.path.dirname(__file__))


# ---------- Шаг 1: сигнал сдачи квеста доходит до награды ----------

def _info(quests_done=0, done_ids=(), xp=100, copper=50, kills=0):
    return {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0],
        "nearby": [], "inventory": [],
        "quests_done": quests_done,
        "xp": xp, "copper": copper, "kills": kills,
        "quests": {"active": [], "ready": [],
                   "done": [{"id": q, "state": "done"} for q in done_ids]},
    }


def test_world_state_uses_honest_quests_done():
    """Шаг 1. Найдено со-аудитором: world_state брал quests_done из поля,
    которое в онлайне всегда было 0, поэтому дельта награды за сдачу — всегда 0,
    и вся история обучения получала ложный сигнал «сдавать бесполезно».
    Мост теперь отдаёт честное число (из online.questsDone, Set)."""
    from world_state import build_world_state
    ws = build_world_state(_info(quests_done=7))
    assert ws["quests_done"] == 7, f"получили {ws['quests_done']}"


def test_world_state_falls_back_to_done_bucket_offline():
    """Офлайн-сим (headless) кладёт квесты в ведро done и не заполняет поле."""
    from world_state import build_world_state
    info = _info(quests_done=0, done_ids=["q_a", "q_b"])
    ws = build_world_state(info)
    assert ws["quests_done"] == 2, f"офлайн-фоллбек не сработал: {ws['quests_done']}"


def test_quest_completion_pays_at_least_five():
    """Приёмка A1: завершение квеста обязано давать ≥ +5.0."""
    from reward import outcome_reward
    from world_state import build_world_state
    before = build_world_state(_info(quests_done=6))
    after = build_world_state(_info(quests_done=7))
    r = outcome_reward(before, after, "SUCCESS")
    assert r >= 5.0, f"сдача квеста дала всего {r:.2f}"


# ---------- Шаг 2: нет наградного тредмилла ----------

def test_success_without_world_delta_pays_nothing():
    """Приёмка A4. Найдено со-аудитором: success_bonus=0.5 платился за ЛЮБОЙ
    вердикт SUCCESS без прогресса мира. Расчёт: 200 из 226 очков за 1000 шагов
    (88%) приходили именно оттуда — сдача квеста стоила 2.2% от рутины."""
    from reward import outcome_reward
    from world_state import build_world_state
    same = _info(quests_done=3, xp=100, copper=50, kills=5)
    before = build_world_state(same)
    after = build_world_state(same)          # мир НЕ изменился
    r = outcome_reward(before, after, "SUCCESS")
    assert abs(r) < 0.01, f"тредмилл: пустой SUCCESS дал {r:+.3f}"


def test_success_with_world_delta_still_rewarded():
    """Обратная сторона: реальный прогресс мира по-прежнему оплачивается."""
    from reward import outcome_reward
    from world_state import build_world_state
    before = build_world_state(_info(kills=5, xp=100))
    after = build_world_state(_info(kills=6, xp=140))
    r = outcome_reward(before, after, "SUCCESS")
    assert r > 0.2, f"реальный прогресс должен оплачиваться, дали {r:+.3f}"


def test_failure_penalty_survives():
    """Провал остаётся наказуемым независимо от дельты мира."""
    from reward import outcome_reward
    from world_state import build_world_state
    same = _info(quests_done=3)
    r = outcome_reward(build_world_state(same), build_world_state(same),
                       "FAILURE")
    assert r < 0, f"провал должен наказываться, дали {r:+.3f}"

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from verifiers_py import verify_quest_turn_in


def _snap(qdone=0, active=(), ready=(), done_ids=()):
    return {
        "quests_done": qdone,
        "quests": {
            "active": [{"id": q, "state": "active",
                        "objectives": [{"current": 1, "required": 2}]} for q in active],
            "ready": [{"id": q, "state": "ready",
                       "objectives": [{"current": 2, "required": 2}]} for q in ready],
            "done": [{"id": q, "state": "done"} for q in done_ids],
        },
    }


def test_success_by_quests_done_counter_growth():
    """Согласовано с со-диагностом (D4): в ОНЛАЙНЕ ведро done всегда пусто —
    завершённый квест УДАЛЯЕТСЯ из questLog (quest_commands.ts:432-433), а
    единственный носитель истины это online.questsDone (Set), который мост
    теперь отдаёт числом. Значит рост счётчика = честный успех."""
    c = {"before": _snap(qdone=6, ready=["q_loom"]),
         "after": _snap(qdone=7),
         "handle": "q_loom"}
    assert verify_quest_turn_in(c) == "success"


def test_disappeared_without_counter_growth_is_failure():
    """Квест ушёл из лога, но счётчик не вырос -> сервер отклонил (или ресинк).
    Это НЕ успех и НЕ 'inconclusive': агент должен получить отрицательный сигнал,
    иначе он будет бесконечно дёргать сдачу."""
    c = {"before": _snap(qdone=6, ready=["q_loom"]),
         "after": _snap(qdone=6),
         "handle": "q_loom"}
    assert verify_quest_turn_in(c) == "failure"


def test_still_ready_is_failure_not_inconclusive():
    """Квест остался в ready -> сдача не состоялась (сервер молча отказал:
    далеко от гивера / сумки полны / кулдаун)."""
    c = {"before": _snap(qdone=6, ready=["q_loom"]),
         "after": _snap(qdone=6, ready=["q_loom"]),
         "handle": "q_loom"}
    assert verify_quest_turn_in(c) == "failure"


def test_offline_done_bucket_still_works():
    """Офлайн-путь (headless-сим) кладёт квест в done — старое поведение живо."""
    c = {"before": _snap(qdone=0, ready=["q_loom"]),
         "after": _snap(qdone=1, done_ids=["q_loom"]),
         "handle": "q_loom"}
    assert verify_quest_turn_in(c) == "success"


def test_counter_growth_without_handle_still_success():
    """Даже без известного quest_id рост счётчика — доказательство сдачи."""
    c = {"before": _snap(qdone=3), "after": _snap(qdone=4), "handle": None}
    assert verify_quest_turn_in(c) == "success"


def test_no_quest_no_counter_change_is_failure():
    c = {"before": _snap(qdone=3), "after": _snap(qdone=3), "handle": None}
    assert verify_quest_turn_in(c) == "failure"

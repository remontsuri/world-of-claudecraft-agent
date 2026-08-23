import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from verifiers_py import verify_gather


def _snap(inv=None, nodes=None):
    return {
        "inventory": [{"itemId": k, "count": v} for k, v in (inv or {}).items()],
        "nearby": nodes or [],
    }


def test_gather_success_when_material_gained():
    c = {"before": _snap({"spider_silk": 5}), "after": _snap({"spider_silk": 6}),
         "handle": {"materialId": "spider_silk"}}
    assert verify_gather(c) == "success"


def test_gather_no_object_is_failure_not_inconclusive():
    """Найдено измерением 2026-08-24: 25 подряд gather при ПОЛНОМ отсутствии
    трупов/узлов в радиусе дали 'inconclusive' -> reward≈0 -> Q не учится и
    агент может бить в пустоту бесконечно. Отсутствие объекта действия — это
    честный провал решения (выбрал скилл, которому нечего делать), а не
    неопределённый исход."""
    c = {"before": _snap({"spider_silk": 5}), "after": _snap({"spider_silk": 5}),
         "handle": {"materialId": "spider_silk", "noTarget": True}}
    assert verify_gather(c) == "failure"


def test_gather_inconclusive_when_target_existed_but_no_gain():
    """Если объект БЫЛ (мост его нашёл), но предмет не выпал — это честный
    inconclusive: решение было разумным, результат вероятностный."""
    c = {"before": _snap({"spider_silk": 5}), "after": _snap({"spider_silk": 5}),
         "handle": {"materialId": "spider_silk", "noTarget": False}}
    assert verify_gather(c) == "inconclusive"


def test_gather_missing_flag_defaults_to_inconclusive():
    """Обратная совместимость: старые handle без флага noTarget ведут себя
    как раньше (inconclusive), чтобы не переобучать историю задним числом."""
    c = {"before": _snap({"spider_silk": 5}), "after": _snap({"spider_silk": 5}),
         "handle": {"materialId": "spider_silk"}}
    assert verify_gather(c) == "inconclusive"

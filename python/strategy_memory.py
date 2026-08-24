"""StrategyMemory — какие стратегии РЕАЛЬНО завершали квесты.

Переписано 2026-08-24 по итогам аудита обучающего контура.

ЧТО БЫЛО СЛОМАНО (измерено):
  1. Семантика. record_outcome инкрементил success на КАЖДЫЙ SUCCESS-вердикт
     отдельного шага. Итог: у q_greyjaw накопилось 12024 «успеха» при НУЛЕ
     сдач, а лучшим навыком для квеста «убей волка» стал sell_junk — просто
     потому, что он часто возвращает SUCCESS.
  2. Мёртвое чтение. preference() возвращала best_skill только при
     success > fail; у q_greyjaw 12024 < 22237, то есть None. Даже если бы
     политика её читала, толку не было бы.
  3. Никто не читал. Единственный вызов preference() жил в смоук-тесте —
     модуль был write-only балластом.

ЧТО ТЕПЕРЬ:
  * успех = ФАКТ завершения квеста (record_completion), а не вердикт шага;
  * шаговые вердикты пишутся отдельно (record_step) только как статистика и
    НИКОГДА не определяют стратегию;
  * preference() требует доказательств (хотя бы одно завершение), а не
    большинства;
  * boost() отдаёт множитель веса для политики — она умножает Q-значение
    доказанного скилла, но не подменяет решение (мягкий prior, не override).

Персистится в strategy_memory.json (атомарная запись, живёт между запусками).
"""
import json
import os
import tempfile
import time
from typing import Optional

# Множитель веса для доказанного скилла. Мягкий prior: политика по-прежнему
# может выбрать другое действие, если Q сильно против.
STRATEGY_BOOST = 1.8


class StrategyMemory:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(os.path.dirname(__file__), "strategy_memory.json")
        self.strategies = {}
        self._load()

    # ---- персистентность ----

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.strategies = data.get("strategies") or {}
        except Exception:
            self.strategies = {}

    def save(self):
        try:
            d = os.path.dirname(os.path.abspath(self.path))
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"strategies": self.strategies}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)          # атомарно на Windows
        except Exception:
            pass

    def _rec(self, key: str) -> dict:
        rec = self.strategies.get(key)
        if rec is None:
            rec = {"completions": {}, "steps": {"success": 0, "fail": 0},
                   "last_updated": 0.0}
            self.strategies[key] = rec
        # миграция старого формата (success/fail на верхнем уровне)
        rec.setdefault("completions", {})
        rec.setdefault("steps", {"success": 0, "fail": 0})
        return rec

    # ---- запись ----

    def record_completion(self, key: str, skill: str):
        """ЕДИНСТВЕННЫЙ источник стратегического знания: квест завершён, и
        последним содержательным навыком был `skill`."""
        rec = self._rec(key)
        comp = rec["completions"]
        comp[skill] = int(comp.get(skill, 0)) + 1
        rec["last_updated"] = time.time()

    def record_step(self, key: str, skill: str, success: bool):
        """Статистика шагов. НЕ влияет на preference/boost — именно смешение
        этих двух вещей и породило 12024 ложных «успеха»."""
        rec = self._rec(key)
        rec["steps"]["success" if success else "fail"] += 1
        rec["last_updated"] = time.time()

    # ---- чтение (то, чего раньше не было) ----

    def preference(self, key: str) -> Optional[str]:
        """Навык с наибольшим числом ДОКАЗАННЫХ завершений, иначе None."""
        rec = self.strategies.get(key) or {}
        comp = rec.get("completions") or {}
        if not comp:
            return None
        return max(comp.items(), key=lambda kv: kv[1])[0]

    def boost(self, key: str, skill: str) -> float:
        """Множитель веса для политики: >1.0 только для доказанного навыка."""
        return STRATEGY_BOOST if self.preference(key) == skill else 1.0

    # ---- обратная совместимость со старым вызовом ----

    def record_outcome(self, key: str, skill: str, success: bool):
        """Устаревшее имя: раньше писало стратегию из вердиктов шага. Теперь
        это просто статистика шагов (см. record_step)."""
        self.record_step(key, skill, success)

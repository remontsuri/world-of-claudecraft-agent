"""P0 hot-path defects — RED tests.

Четыре дефекта, подтверждённых живым замером (_audit_schema.py) и сверкой
с исходниками игры (woc-game/src/sim/content/items.ts):

  P0.1  junk-детект мёртв. `quality` в игре — СТРОКА ('poor' 8 предметов,
        'common' 80, 'uncommon' 65, 'rare' 42, 'epic' 7), а observation.py
        сравнивал её с нулём: `_num(it.get("quality"), 1.0) == 0`. Строка
        никогда не равна 0 -> junk_count всегда 0 -> предикат has_junk
        всегда False -> sell_junk заблокирован НАВСЕГДА при полной сумке
        хлама и вендоре в двух шагах. world_state.has_junk был прибит к False
        с комментарием "поле quality отсутствует" — замер был неверный,
        поле есть, оно строковое.

  P0.2  ExperienceStore.update() вызывает save() ВНУТРИ каждого update.
        5000 переходов = 28.8 МБ JSON, переписываемых на каждом шаге.

  P0.3  Agent._cycle() делает 4 синхронных open()+write()+close() в _cycle.log
        на КАЖДОМ шаге, безусловно, без env-гейта.

  P0.4  play_autonomous: startup contract failure -> autonomy=None и агент
        продолжает БЕЗ автономного контура. Комментарий в коде обещает
        обратное ("Startup-ассерты валят процесс ЗДЕСЬ").
"""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


# Реальные junk-предметы игры (quality: 'poor' в items.ts).
SNAP = {
    "player": {"hp": 80, "maxHp": 100, "level": 3, "dead": False},
    "player_pos": [10.0, 20.0],
    "player_class": "warrior",
    "nearby": [
        {"id": 7, "kind": "npc", "name": "Trader",
         "vendorItems": [{"itemId": "handaxe"}], "x": 11.0, "z": 20.0},
    ],
    "inventory": [
        {"itemId": "rough_hide", "count": 2, "quality": "common"},
        {"itemId": "tangled_weed", "count": 3, "quality": "poor"},
        {"itemId": "soggy_boot", "count": 1, "quality": "poor"},
    ],
    "inventory_by_id": {"rough_hide": 2, "tangled_weed": 3, "soggy_boot": 1},
    "equipment": {"mainHand": "rusty_axe"},
    "quests": {"active": [], "done": []},
    "quests_done": 0, "kills": 0, "deaths": 0, "copper": 100,
    "in_combat": False, "bagCapacity": 16,
}


class TestJunkCountP01(unittest.TestCase):
    """P0.1: junk = quality 'poor' (реальный контракт игры)."""

    def test_junk_count_counts_poor_quality_items(self):
        from world_state import build_world_state
        from observation import encode_observation

        ws = build_world_state(SNAP)
        obs = encode_observation(ws, SNAP)
        junk = obs["inventory"]["junk_count"]
        self.assertEqual(
            junk, 2,
            "junk_count=%r, ожидалось 2 (tangled_weed, soggy_boot — quality "
            "'poor' в items.ts). Сравнение строки с нулём никогда не истинно."
            % (junk,),
        )

    def test_junk_count_zero_when_no_junk(self):
        from world_state import build_world_state
        from observation import encode_observation

        snap = dict(SNAP)
        snap["inventory"] = [{"itemId": "rough_hide", "count": 2,
                              "quality": "common"}]
        snap["inventory_by_id"] = {"rough_hide": 2}
        obs = encode_observation(build_world_state(snap), snap)
        self.assertEqual(obs["inventory"]["junk_count"], 0,
                         "common/uncommon/rare/epic — это НЕ хлам")

    def test_null_quality_is_not_junk(self):
        """Мост отдаёт quality: null когда данных нет — это не повод продавать."""
        from world_state import build_world_state
        from observation import encode_observation

        snap = dict(SNAP)
        snap["inventory"] = [{"itemId": "mystery_thing", "count": 1,
                              "quality": None}]
        snap["inventory_by_id"] = {"mystery_thing": 1}
        obs = encode_observation(build_world_state(snap), snap)
        self.assertEqual(obs["inventory"]["junk_count"], 0,
                         "quality=null (нет данных) не должно считаться хламом")

    def test_has_junk_agrees_with_junk_count(self):
        """world_state.has_junk и observation.junk_count не должны расходиться."""
        from world_state import build_world_state
        from observation import encode_observation

        ws = build_world_state(SNAP)
        obs = encode_observation(ws, SNAP)
        self.assertEqual(
            bool(ws.get("has_junk")), bool(obs["inventory"]["junk_count"]),
            "has_junk=%r но junk_count=%r — два слоя видят инвентарь по-разному"
            % (ws.get("has_junk"), obs["inventory"]["junk_count"]),
        )

    def test_sell_junk_is_not_blocked_forever(self):
        """Главное следствие: с хламом и вендором рядом sell_junk обязан пройти."""
        from world_state import build_world_state
        from observation import encode_observation
        from skill_contracts import check_preconditions

        ws = build_world_state(SNAP)
        obs = encode_observation(ws, SNAP)
        res = check_preconditions("sell_junk", obs)
        self.assertNotIn(
            "has_junk", res.get("failed") or [],
            "4 предмета quality='poor' в сумке, вендор в 1 ярде — и sell_junk "
            "заблокирован предикатом has_junk. Экономика мертва: %r" % (res,),
        )



class TestNoDiskWriteInUpdateP02(unittest.TestCase):
    """P0.2: update() не должен писать на диск."""

    def test_update_does_not_call_save(self):
        src = _read("memory.py")
        m = re.search(r"\n    def update\(.*?(?=\n    def |\nclass |\Z)", src, re.S)
        self.assertIsNotNone(m, "ExperienceStore.update() не найден в memory.py")
        # Комментарии не код: вырезаем их, иначе объяснение фикса само
        # выглядит как нарушение.
        body = "\n".join(
            re.sub(r"#.*$", "", ln) for ln in m.group(0).splitlines())
        self.assertNotRegex(
            body, r"self\.save\(\)",
            "update() вызывает save() внутри: полная сериализация Q-table + "
            "experiences[-500:] на КАЖДОМ шаге. save() должен вызываться "
            "пачкой раз в N шагов, а не из update().",
        )

    def test_update_is_actually_cheap(self):
        """Поведенческая проверка: 200 update() не должны писать файл."""
        import tempfile
        from memory import ExperienceStore

        # update() ждёт WorldState-dict (внутри вызывает _bucket(state)).
        st_a = {"hp_frac": 1.0, "quest_status": "none", "has_mob": True,
                "has_corpse": False, "has_junk": False, "in_combat": False}
        st_b = dict(st_a, has_mob=False, has_corpse=True)

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "exp.json")
            store = ExperienceStore(path=path)
            for _ in range(200):
                store.update(st_a, "farm", 1.0,
                             next_state=st_b, outcome_kind="SUCCESS")
            self.assertFalse(
                os.path.exists(path),
                "200 update() создали файл на диске — update() пишет синхронно. "
                "Ожидается: запись только по явному save().",
            )
            self.assertTrue(store.has_unsaved(),
                            "после 200 update() должен быть признак "
                            "несохранённых изменений")
            store.save()
            self.assertTrue(os.path.exists(path),
                            "явный save() обязан создать файл")
            self.assertFalse(store.has_unsaved(),
                             "save() обязан сбросить признак грязного состояния")

    def test_save_writes_no_side_log(self):
        """save() не должен писать _mem.log рядом (тоже синхронный I/O)."""
        import tempfile
        from memory import ExperienceStore

        st = {"hp_frac": 1.0, "quest_status": "none", "has_mob": True,
              "has_corpse": False, "has_junk": False, "in_combat": False}
        with tempfile.TemporaryDirectory() as td:
            store = ExperienceStore(path=os.path.join(td, "exp.json"))
            store.update(st, "farm", 1.0, next_state=st)
            store.save()
            self.assertFalse(
                os.path.exists(os.path.join(td, "_mem.log")),
                "save() создал _mem.log — лишний синхронный файловый I/O",
            )


class TestNoHotLoopLogP03(unittest.TestCase):
    """P0.3: _cycle.log I/O в горячем цикле должен быть за env-гейтом."""

    def test_cycle_log_is_gated(self):
        src = _read("agent.py")
        raw_opens = re.findall(r'open\(\s*["\'][^"\']*_cycle\.log', src)
        if not raw_opens:
            return  # уже убрано
        gated = re.search(r"WOC_TRACE|_TRACE_ON|_trace\(", src)
        self.assertIsNotNone(
            gated,
            "Найдено %d безусловных open() в _cycle.log внутри горячего цикла "
            "и ни одного env-гейта. На 296 шагов/сек это %d синхронных "
            "открытий файла в секунду." % (len(raw_opens), len(raw_opens) * 296),
        )

    def test_no_unconditional_open_per_step(self):
        """Ни один open() лог-файла не должен вызываться без проверки флага."""
        src = _read("agent.py")
        lines = src.splitlines()
        offenders = []
        for i, line in enumerate(lines):
            # ищем именно ОТКРЫТИЕ файла в этой же строке, а не любое
            # упоминание пути (определение _TRACE_PATH — не нарушение)
            if not re.search(r"open\(\s*[^)]*_cycle\.log", line):
                continue
            window = "\n".join(lines[max(0, i - 8):i])
            if not re.search(r"WOC_TRACE|_TRACE_ON|if\s+.*trace", window, re.I):
                offenders.append(i + 1)
        self.assertEqual(
            offenders, [],
            "Строки %s открывают _cycle.log без гейта трассировки" % offenders,
        )

    def test_trace_is_off_by_default(self):
        """Поведенческая: без WOC_TRACE вызов _trace() не создаёт файл."""
        import importlib
        import tempfile

        old = os.environ.pop("WOC_TRACE", None)
        try:
            import agent as agent_mod
            importlib.reload(agent_mod)
            self.assertFalse(
                agent_mod._TRACE_ON,
                "трассировка включена по умолчанию — на 296 шагов/сек это "
                "лишний синхронный I/O в каждом шаге",
            )
            with tempfile.TemporaryDirectory() as td:
                probe = os.path.join(td, "_cycle.log")
                agent_mod._TRACE_PATH = probe
                agent_mod._trace("SHOULD_NOT_APPEAR")
                self.assertFalse(os.path.exists(probe),
                                 "_trace() записал файл при выключённом гейте")
        finally:
            if old is not None:
                os.environ["WOC_TRACE"] = old

    def test_trace_works_when_enabled(self):
        """Обратная сторона: с WOC_TRACE=1 трассировка обязана писать."""
        import importlib
        import tempfile

        old = os.environ.get("WOC_TRACE")
        os.environ["WOC_TRACE"] = "1"
        try:
            import agent as agent_mod
            importlib.reload(agent_mod)
            self.assertTrue(agent_mod._TRACE_ON)
            with tempfile.TemporaryDirectory() as td:
                probe = os.path.join(td, "_cycle.log")
                agent_mod._TRACE_PATH = probe
                agent_mod._trace_fh = None
                agent_mod._trace("HELLO_TRACE")
                self.assertTrue(os.path.exists(probe),
                                "WOC_TRACE=1, а файл не создан")
                with open(probe, encoding="utf-8") as f:
                    self.assertIn("HELLO_TRACE", f.read())
                if agent_mod._trace_fh:
                    agent_mod._trace_fh.close()
                    agent_mod._trace_fh = None
        finally:
            if old is None:
                os.environ.pop("WOC_TRACE", None)
            else:
                os.environ["WOC_TRACE"] = old


class TestAutonomyFailClosedP04(unittest.TestCase):
    """P0.4: сломанный контракт при WOC_AUTONOMY=1 обязан остановить процесс."""

    def test_contract_failure_does_not_silently_disable(self):
        src = _read("play_autonomous.py")
        # startup-блок: от объявления autonomy до записи agent.pid
        block = re.search(
            r"autonomy = None.*?assert_skill_indices_match\(\).*?(?=\n    # Record|\n    try:\s*\n        with open)",
            src, re.S)
        self.assertIsNotNone(block, "startup-блок autonomy не найден")
        body = block.group(0)
        has_silent_disable = re.search(
            r"except Exception:(?:(?!raise|sys\.exit|SystemExit).)*?"
            r"autonomy\s*=\s*None", body, re.S)
        has_hard_stop = re.search(r"raise SystemExit|sys\.exit|os\._exit", body)
        self.assertIsNotNone(
            has_hard_stop,
            "При WOC_AUTONOMY!=0 провал контракта обязан остановить процесс. "
            "Иначе agent продолжает БЕЗ автономного контура — лог скажет "
            "'agent running', а замер будет не того, что измеряли.",
        )
        self.assertIsNone(
            has_silent_disable,
            "в except всё ещё есть путь 'autonomy = None' без остановки",
        )

    def test_explicit_opt_out_still_allowed(self):
        """WOC_AUTONOMY=0 — единственный законный путь к legacy-режиму."""
        src = _read("play_autonomous.py")
        self.assertRegex(
            src, r"WOC_AUTONOMY",
            "должен остаться явный env-переключатель для legacy-режима")

    def test_hot_loop_errors_are_not_swallowed(self):
        """Сбой контура в горячем цикле обязан считаться, а не тонуть в traceback."""
        src = _read("play_autonomous.py")
        self.assertRegex(
            src, r"_autonomy_errors\s*\+=\s*1",
            "except в контуре только печатает traceback и продолжает: можно "
            "намерить 5000 шагов 'автономной архитектуры' при мёртвом контуре",
        )
        self.assertRegex(
            src, r"_AUTONOMY_MAX_ERRORS",
            "нужен порог, после которого прогон останавливается",
        )

    def test_nav_substeps_are_accounted_separately(self):
        """nav_command обходит agent.step() — такие шаги нельзя звать переходами."""
        src = _read("play_autonomous.py")
        self.assertRegex(
            src, r"_nav_substeps\s*\+=\s*1",
            "навигационный подшаг делает `continue` до agent.step(), значит не "
            "даёт обучающего перехода — его надо считать отдельно",
        )
        self.assertRegex(
            src, r"_learning_steps\s*\+=\s*1",
            "нужен отдельный счётчик реальных обучающих шагов",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

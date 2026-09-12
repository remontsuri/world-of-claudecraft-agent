# WoC Agent — Standing Rules

Этот файл загружается автоматически при работе в директории D:\world-of-claudecraft.
Следуй этим правилам ВСЕГДА, даже если они конфликтуют с предыдущими инструкциями.

---

## 📌 ПЕРВЫМ ДЕЛОМ: ЧИТАТЬ ГРАФ

Перед любыми правками кода агента или моста — прочитай:

1. `graphify-out/GRAPH_REPORT.md` — highlights, key concepts, communities
2. `graphify-out/graph.html` — интерактивный граф (открыть в браузере)
3. `graphify-out/graph.json` — полный граф для запросов

Граф строится автоматически через `graphify hook install` (post-commit, post-checkout).
Если граф не обновлялся после последнего коммита — запусти вручную:

```bash
cd D:/world-of-claudecraft
graphify extract . --code-only
graphify cluster-only .
```

**Graph Freshness**: проверяй `graphify-out/manifest.json` → `git_commit` vs `git rev-parse HEAD`.

---

## Working Directories

| Путь | Назначение | Использовать? |
|------|-----------|--------------|
| D:\world-of-claudecraft | Основная рабочая папка (игра + агент) | ✅ ВСЕГДА |
| D:\world-of-claudecraft-agent | Устаревшая папка агента | ❌ Никогда |
| D:\woc | Официальный источник игры (source of truth) | ✅ Для reference |

---

## Git Rules (CRITICAL)

- **Ветка**: ТОЛЬКО backup
- **Remote**: ТОЛЬКО origin backup (remontsuri/world-of-claudecraft-agent)
- **Запрещено**: release/*, main, master, levy-street для push

---

## Process Kill Protocol (CRITICAL)

Перед kill: `wmic process where "name='node.exe'" get ProcessId,CommandLine`

Разрешено убивать: browser_bridge.cjs, python/play_autonomous.py
Запрещено: hermes-agent, hermes-gateway, любой node.exe с hermes в CommandLine

---

## Game & Bridge

- Game: http://localhost:5173
- CDP: http://127.0.0.1:9222
- Bridge: http://127.0.0.1:8791
- Python: C:/Users/vladc/AppData/Local/Programs/Python/Python312/python.exe
- Args: -I -u -X faulthandler PYTHONPATH=D:/world-of-claudecraft/python

Запрещено: window.location.reload() через CDP, перезапуск игры

---

## Decision Owner Chain (Production)

play_autonomous → agent.Agent → arbitration.ArbitrationLayer → policy → skill

arbitration_layer.py — МЁРТВЫЙ код, не трогать

---

## Key Files

- python/agent.py — главный агент
- python/policy.py — decision gates
- python/play_autonomous.py — runner
- python/world_state.py — canonical world state
- python/arbitration.py — REAL owner
- src/bridge/actions.cjs — bridge actions
- browser_bridge.cjs — bridge endpoint

---

## What to Never Do

1. ❌ Kill hermes-agent/hermes-gateway processes
2. ❌ Reload game via CDP
3. ❌ Push to non-backup remotes
4. ❌ Work in D:\world-of-claudecraft-agent
5. ❌ Modify arbitration_layer.py (dead code)
6. ❌ Restart bridge/agent after code edits
7. ❌ Start game if user already logged in
8. ❌ Custom revive logic (built-in exists)
9. ❌ Ask "what to do next" — follow document TODO in order
10. ❌ Repeat git status endlessly — execute next TODO item
11. ❌ Править код без чтения GRAPH_REPORT.md и graph.json

---

## Before Every Action

1. `cd D:/world-of-claudecraft` — убедись что в правильной папке
2. `git status` — нет ли uncommitted изменений
3. Прочитай `graphify-out/GRAPH_REPORT.md` — найди relevant communities
4. Проверь процессы перед kill
5. Выполни следующий TODO item

---

## User Preferences

- Language: Russian
- Tone: Direct, no filler, no "great question!"
- Verification: Real game behavior > tests
- Workflow: Phase-1 root-cause → TDD → live verification
- Reporting: Tables LAYER|EXPECTED|ACTUAL|STATUS

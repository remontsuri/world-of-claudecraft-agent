#!/usr/bin/env bash
# Хук старта сессии: напомнить цель, инварианты и что реально не закрыто.
# Контракт и регистрация: hermes/hooks/README.md
set -uo pipefail

ROOT="${WOC_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT" 2>/dev/null || { echo '{"continue": true, "message": "репозиторий не найден"}'; exit 0; }

declare -a parts=()
add() { parts+=("$1"); }

trunc() {  # обрезка по СИМВОЛАМ: cut -c режет байты и превращает кириллицу в мусор
  T="$1" N="${2:-140}" python3 -c 'import os; t=os.environ["T"]; n=int(os.environ["N"]); print(t if len(t)<=n else t[:n-1]+"…")' 2>/dev/null || printf '%s' "$1"
}


add "ГЛАВНОЕ: автономный Java-бот проходит квесты в WoC и умеет доказывать это против контролей (rewired/er/MLP/silenced/untrained)."
add "Инварианты: игру и её исходники не трогаем; браузер через CDP не перезагружаем; hermes-agent/hermes-gateway не убиваем; force-push запрещён; молчаливых фолбэков нет; пороги метрик не двигаем после замера."

# Ветка и её реальное состояние (истина — remote, а не память)
if git rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  head=$(git log --oneline -1 2>/dev/null | cut -c1-60)
  add "Git: ветка $branch, HEAD: $head"
  dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  [ "$dirty" != "0" ] && add "Git: незакоммиченных изменений — $dirty файлов (не забыть перед пушем)."
else
  add "Git: это не репозиторий (или .git недоступен) — перед пушем переклонировать."
fi

# Порты: свои инструменты или чужие процессы
if command -v ss >/dev/null 2>&1; then
  busy=$(ss -ltn 2>/dev/null | grep -oE ':(5173|8791|8792|9231|9232)\b' | sort -u | tr '\n' ' ')
  [ -n "$busy" ] && add "Порты заняты: $busy(5173 — игра, 8791 — мост, 8792 — MCP/тест, 9231/9232 — фейковый CDP)."
fi

# Что не закрыто в роадмапе — по активной линии
roadmap="$ROOT/woof-agent/ROADMAP.md"
if [ -f "$roadmap" ]; then
  open_lines=$(grep -E '^\| (J|H)[0-9]+ .*⬜' "$roadmap" | head -5 | sed 's/|/ /g' | tr -s ' ' | sed 's/^ //')
  if [ -n "$open_lines" ]; then
    add "Не закрыто (woof-agent/ROADMAP.md):"
    while IFS= read -r line; do add "  • $(trunc "$line" 150)"; done <<< "$open_lines"
  fi
fi

# Состояние проверок: последняя известная приёмка
last_e2e=""
[ -f /tmp/e2e_agent_java.log ] && last_e2e=$(grep -h '\[Agent\] SUMMARY' /tmp/e2e_agent_java.log 2>/dev/null | tail -1)
[ -n "$last_e2e" ] && add "Последняя приёмка e2e: $last_e2e"

msg=$(printf '%s\n' "${parts[@]}")
MSG="$msg" python3 -c 'import json,os; print(json.dumps({"continue": True, "message": os.environ["MSG"]}, ensure_ascii=False))' 2>/dev/null \
  || printf '{"continue": true, "message": "%s"}\n' "$(printf '%s' "$msg" | tr '\n' ' ' | sed 's/"/\\"/g')"

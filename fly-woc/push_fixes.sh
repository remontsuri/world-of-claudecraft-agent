#!/usr/bin/env bash
# push_fixes.sh — пуш исправлений оракула/раскладки в репозиторий агента.
#
#   GH_TOKEN=<pat> bash /home/user/fly-woc/push_fixes.sh [ветка]
#   ветка по умолчанию — backup (правило репозитория; в master — только по явному указанию)
#
# Токен передаётся git через inline credential helper: он не попадает ни в
# .git/config, ни в argv, ни в историю. Ничего не сохраняется.
#
# Что делает: перепроверяет, что чужих коммитов сверху нет (fast-forward),
# пушит без force, затем СВЕРЯЕТ по ls-remote, что записалось ровно то, что нужно.
set -uo pipefail

REPO="${REPO:-/tmp/pushrepo}"
REMOTE="${REMOTE:-https://github.com/remontsuri/world-of-claudecraft-agent.git}"
BRANCH="${1:-backup}"
BASE="${BASE:-88469d2}"

[ -d "$REPO/.git" ] || { echo "нет репозитория $REPO (собери: git clone --branch backup $REMOTE $REPO)"; exit 1; }
cd "$REPO"

CREDS=(-c "credential.helper=!f() { echo username=x-access-token; echo password=\"\$GH_TOKEN\"; }; f")

echo "== что пушим (поверх $BASE)"
git log --oneline "$BASE"..HEAD || exit 1
echo "дерево: $(git rev-parse HEAD^{tree})"
[ -n "$(git status --porcelain)" ] && { echo "ВНИМАНИЕ: рабочее дерево не чистое"; git status --short | head; }

echo "== состояние remote (на момент проверки)"
: "${GH_TOKEN:?GH_TOKEN is not set — нужен PAT с правом contents:write}"
remote_head=$(git "${CREDS[@]}" ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
[ -z "$remote_head" ] && { echo "не удалось прочитать refs (проверь токен)"; exit 1; }
echo "remote/$BRANCH = ${remote_head:0:12}"
if [ "$remote_head" != "$(git rev-parse "$BASE")" ]; then
  echo "СТОП: голова $BRANCH сдвинулась ($remote_head). Нужен rebase, force не делаем."
  exit 1
fi
echo "fast-forward подтверждён"

echo "== push"
git "${CREDS[@]}" push "$REMOTE" "HEAD:refs/heads/$BRANCH" || { echo "ПУШ НЕ ПРОШЁЛ"; exit 1; }

echo "== проверка на remote (истина — remote, а не локальный вывод)"
after=$(git "${CREDS[@]}" ls-remote "$REMOTE" "refs/heads/$BRANCH" | cut -f1)
if [ "$after" = "$(git rev-parse HEAD)" ]; then
  echo "OK: refs/heads/$BRANCH = ${after:0:12} (совпадает с локальным HEAD)"
  git "${CREDS[@]}" ls-remote "$REMOTE" refs/heads/backup refs/heads/master | sed "s|$REMOTE|<remote>|"
else
  echo "РАСХОЖДЕНИЕ: remote=${after:0:12}, локально=$(git rev-parse --short HEAD)"; exit 1
fi

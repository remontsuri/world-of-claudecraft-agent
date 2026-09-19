#!/usr/bin/env bash
# Собрать headless env server игры (upstream) НАШИМ esbuild.
#
# Зачем своей сборкой, а не `npm run env` в дереве игры: установка зависимостей
# игры тянет весь фронтенд (vite/react/полный dev-набор), а env-серверу нужны
# только src/sim + headless — esbuild бандлит их за секунды. Дерево игры при этом
# остаётся read-only: артефакт кладём в СВОЙ dist-env/, ничего в игру не пишем.
#
#   bash tools/build_env.sh            # собрать
#   ENV_SERVER=/path/to.cjs ...        # использовать уже собранный (переменная WOOF_ENV_SERVER)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_DIR="${GAME_DIR:-$HOME/woc-game}"
ENTRY="$GAME_DIR/headless/env_server.ts"
OUT="${WOOF_ENV_SERVER:-$ROOT/dist-env/env_server.cjs}"
ESBUILD="$ROOT/node_modules/.bin/esbuild"

[ -f "$ENTRY" ] || { echo "ПРОВАЛ: нет $ENTRY — клон игры неполный (нужен паттерн /headless/**, см. tools/setup_game.sh)"; exit 1; }
[ -x "$ESBUILD" ] || { echo "ПРОВАЛ: нет $ESBUILD — сначала bash tools/setup_game.sh"; exit 1; }

mkdir -p "$(dirname "$OUT")"
"$ESBUILD" "$ENTRY" --bundle --platform=node --format=cjs --outfile="$OUT" --log-level=warning
echo "[build_env] готово: $OUT ($(du -h "$OUT" | cut -f1))"
echo "[build_env] пример запуска через бридж: node dist/run.mjs --transport ndjson --seed 42 --steps 120 --quiet"

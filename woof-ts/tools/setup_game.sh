#!/usr/bin/env bash
# Подготовка рабочего места линии woof-ts.
#
# Почему именно скрипт, а не разовые команды:
#  1) node_modules в песочнице не переживает смену хода (стирается), поэтому
#     установка — часть КАЖДОГО запуска, а не разовое действие;
#  2) дерево игры НЕ вендорится и не копируется руками: все игровые факты агент
#     берёт импортом из upstream-репозитория levy-street/world-of-claudecraft.
#     game/ — симлинк на клон; нет клона — скрипт его делает (sparse, только нужное).
#
# Переменные:
#   GAME_REPO   источник игры (по умолчанию upstream)
#   GAME_REF    ветка/тег (по умолчанию main)
#   GAME_DIR    куда класть клон (по умолчанию ~/woc-game)
#   GAME_FULL=1 дотянуть ещё src/world_api/** и server/** — нужно для живого
#               бриджа (WebSocket-клиент авторитетного сервера), для стенда не нужно
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_REPO="${GAME_REPO:-https://github.com/levy-street/world-of-claudecraft.git}"
GAME_REF="${GAME_REF:-main}"
GAME_DIR="${GAME_DIR:-$HOME/woc-game}"

cd "$ROOT"

# 1) дерево игры ---------------------------------------------------------------
# Три случая: дерева нет (клонируем), дерево есть и это git-репозиторий
# (обновляем sparse-набор), дерево есть но без .git (песочница стирает .git между
# ходами) — используем как есть и честно предупреждаем, что версия непроверяема.
if [ ! -d "$GAME_DIR/src/sim" ]; then
  if [ -d "$GAME_DIR/.git" ]; then
    echo "[setup] клон игры есть, обновляю sparse-набор"
  else
    echo "[setup] клонирую игру (sparse, blobless) в $GAME_DIR"
    git clone --depth 1 --filter=blob:none --no-checkout --branch "$GAME_REF" "$GAME_REPO" "$GAME_DIR"
  fi
  git -C "$GAME_DIR" sparse-checkout init --no-cone
  # /src/world_api/** — только типы-фасеты IWorld: без них tsc спотыкается о
  # незакрытые импорты в дереве игры, и гейт типов тонет в чужих ошибках.
  PATTERNS=('/src/sim/**' '/src/world_api.ts' '/src/world_api/**' '/headless/**' '/python/**' '/package.json' '/CLAUDE.md' '/README.md')
  if [ "${GAME_FULL:-0}" = "1" ]; then
    PATTERNS+=('/server/**' '/src/net/**' '/src/client/**' '/tests/**')
  fi
  git -C "$GAME_DIR" sparse-checkout set --no-cone "${PATTERNS[@]}"
  git -C "$GAME_DIR" read-tree -mu HEAD
elif [ ! -d "$GAME_DIR/.git" ]; then
  echo "[setup] ВНИМАНИЕ: $GAME_DIR без .git — дерево игры используем как есть,"
  echo "[setup] но его версия непроверяема. Для воспроизводимости нужен свежий клон:"
  echo "[setup]   rm -rf $GAME_DIR && bash tools/setup_game.sh"
fi
ln -sfn "$GAME_DIR" "$ROOT/game"
[ -d "$ROOT/game/src/sim" ] || { echo "ПРОВАЛ: в $GAME_DIR нет src/sim — дерево игры неполное"; exit 1; }

# 2) зависимости ----------------------------------------------------------------
if [ ! -x node_modules/.bin/esbuild ] || [ ! -x node_modules/.bin/vitest ]; then
  echo "[setup] npm install"
  npm install --no-audit --no-fund
fi

# 3) сборка ---------------------------------------------------------------------
npm run build

echo "[setup] готово: game -> $(readlink -f "$ROOT/game")"
echo "[setup] факты игры берутся импортом из этого дерева; руками ничего не переписывается"

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
#   GAME_REF    ветка/тег. По умолчанию ТЕГ, на котором измерены эталоны приёмки
#               (v0.43.2), а не main: дерево игры — часть воспроизводимости прогона.
#               Переезд на новую версию игры — отдельная задача (ROADMAP A5), потому
#               что вместе с ней едут контракты фактов (obsSize, словарь действий,
#               типы целей квестов) и все эталонные числа.
#   GAME_DIR    куда класть клон (по умолчанию ~/woc-game)
#   GAME_FULL=1 дотянуть ещё src/world_api/** и server/** — нужно для живого
#               бриджа (WebSocket-клиент авторитетного сервера), для стенда не нужно
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_REPO="${GAME_REPO:-https://github.com/levy-street/world-of-claudecraft.git}"
GAME_REF="${GAME_REF:-v0.43.2}"
GAME_EXPECTED_VERSION="${GAME_EXPECTED_VERSION:-0.43.2}"
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

# 1b) версия дерева игры обязана совпасть с той, на которой измерены эталоны.
# Без этой проверки расхождение версии выглядит как мистика: «obs стал 587»,
# «тип farm исчез», «тесты красные» — хотя причина в другом дереве игры.
GAME_VERSION="$(node -e 'process.stdout.write(String(require("'"$ROOT"'/game/package.json").version ?? "?"))' 2>/dev/null || echo '?')"
if [ "$GAME_VERSION" != "$GAME_EXPECTED_VERSION" ]; then
  echo "ПРОВАЛ: дерево игры $GAME_DIR имеет версию $GAME_VERSION, а эталоны линии измерены на $GAME_EXPECTED_VERSION (GAME_REF=$GAME_REF)."
  echo "  Что делать: привести дерево к pinned-версии —"
  echo "    git -C $GAME_DIR fetch --tags && git -C $GAME_DIR checkout $GAME_REF"
  echo "  или переклонировать: rm -rf $GAME_DIR && bash tools/setup_game.sh"
  echo "  Осознанный переезд на другую версию: GAME_REF=<тег> GAME_EXPECTED_VERSION=<версия> bash tools/setup_game.sh"
  echo "  и дальше — по ROADMAP A5 (пересчёт контрактов фактов и эталонов)."
  exit 1
fi
echo "[setup] дерево игры: версия $GAME_VERSION (совпадает с ожидаемой), ref=$GAME_REF"

# 1c) собранный вывод в дереве игры — тоже причина «сборка зелёная, тесты красные»
STRAY_JS="$(find "$ROOT/game/src/sim" "$ROOT/game/headless" \( -name '*.js' -o -name '*.cjs' -o -name '*.mjs' \) -not -path '*/node_modules/*' 2>/dev/null | head -5)"
if [ -n "$STRAY_JS" ]; then
  echo "ПРОВАЛ: в дереве игры есть собранный вывод (.js/.cjs/.mjs) — в upstream там только .ts:"
  echo "$STRAY_JS" | sed 's/^/    /'
  echo "  Vite/vitest резолвит .js РАНЬШЕ .ts, поэтому факты молча берутся из сборки."
  echo "  Что делать: git -C $GAME_DIR clean -xd src headless   (или переклонировать дерево)"
  exit 1
fi

# 2) зависимости ----------------------------------------------------------------
if [ ! -x node_modules/.bin/esbuild ] || [ ! -x node_modules/.bin/vitest ]; then
  echo "[setup] npm install"
  npm install --no-audit --no-fund
fi

# 3) сборка ---------------------------------------------------------------------
npm run build

echo "[setup] готово: game -> $(readlink -f "$ROOT/game")"
echo "[setup] факты игры берутся импортом из этого дерева; руками ничего не переписывается"

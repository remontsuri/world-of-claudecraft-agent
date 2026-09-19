#!/usr/bin/env bash
# A1.1 — поднять ЖИВОЙ мир игры: Postgres + авторитетный сервер на :8787.
#
# Схема A (решение владельца, 2026-09-18): человек держит мир в браузере
# (http://localhost:8787), агент подключается ОТДЕЛЬНЫМ WS-клиентом со СВОИМ
# персонажем. Иначе нельзя: один персонаж = один сеанс, server/linkdead.ts planJoin
# отвечает reject 'character already in world', а повторный вход — только явным
# takeover (POST /api/characters/:id/takeover), который выбросит сеанс человека.
#
# ПОЧЕМУ нужен полный чекаут игры, а не наше дерево фактов:
#   docker-compose.yml собирает образ из контекста репозитория (build: context: .),
#   готового публичного образа upstream не публикует, а sparse-клон из
#   tools/setup_game.sh содержит только src/sim, src/world_api*, headless, python
#   (при GAME_FULL=1 ещё server, src/net, src/client, tests) — для сборки образа мало.
#
# Поднимаются только нужные сервисы: `postgres` и `game`. Остальные (discord-bot,
# mediawiki/mariadb) требуют своих токенов и БД и для нашей задачи не нужны.
#
# Переменные:
#   WORLD_DIR              куда клонировать мир          (по умолчанию ~/woc-world)
#   WORLD_URL              адрес сервера                 (http://127.0.0.1:8787)
#   GAME_REPO / GAME_REF / GAME_EXPECTED_VERSION — те же пины, что в setup_game.sh
#   READY_TIMEOUT          сколько ждать готовности, с   (900)
# Флаги:
#   --clone        клонировать полный чекаут, если его нет (без флага — только инструкция)
#   --no-build     docker compose up -d без --build (образ уже собран)
#   --link-game    перевести симлинк woof-ts/game на этот чекаут: WS-транспорт
#                  импортирует src/net/**, которого нет в лёгком дереве фактов
#   --print-only   напечатать команды, ничего не запуская (проверка на машине без docker)
#   --logs         показать журнал сервиса game и выйти
#   --down         остановить мир (данные Postgres остаются в volume)
#
# ПРОВЕРЕНО: статически (bash -n, shellcheck). Docker в песочнице разработки
# отсутствует, поэтому исполнение проверяется на машине владельца; статус — в
# PROGRESS-2026-09-18.md (пункт «A1.1: не проверено исполнением»).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_REPO="${GAME_REPO:-https://github.com/levy-street/world-of-claudecraft.git}"
GAME_REF="${GAME_REF:-v0.43.2}"
GAME_EXPECTED_VERSION="${GAME_EXPECTED_VERSION:-0.43.2}"
WORLD_DIR="${WORLD_DIR:-$HOME/woc-world}"
WORLD_URL="${WORLD_URL:-http://127.0.0.1:8787}"
READY_TIMEOUT="${READY_TIMEOUT:-900}"

CLONE=0; NO_BUILD=0; LINK_GAME=0; PRINT_ONLY=0; LOGS=0; DOWN=0
for arg in "$@"; do
  case "$arg" in
    --clone) CLONE=1 ;;
    --no-build) NO_BUILD=1 ;;
    --link-game) LINK_GAME=1 ;;
    --print-only) PRINT_ONLY=1 ;;
    --logs) LOGS=1 ;;
    --down) DOWN=1 ;;
    *) echo "ПРОВАЛ: неизвестный флаг '$arg' (есть --clone --no-build --link-game --print-only --logs --down)" >&2; exit 1 ;;
  esac
done

fail() { echo "ПРОВАЛ: $*" >&2; exit 1; }
note() { echo "[мир] $*"; }
# В --print-only ничего не исполняем, но команды показываем дословно.
run() { if [ "$PRINT_ONLY" = 1 ]; then echo "  \$ $*"; else "$@"; fi; }

compose() {
  # В --print-only каталога мира может не быть вовсе (флаг затем и нужен, чтобы
  # посмотреть команды до клона) — поэтому показываем команду вместе с cd, не входя в него.
  if [ "$PRINT_ONLY" = 1 ]; then echo "  \$ (cd $WORLD_DIR && docker compose $*)";
  else ( cd "$WORLD_DIR" && docker compose "$@" ); fi
}

# --- журналы / остановка: короткие пути -------------------------------------
if [ "$LOGS" = 1 ]; then
  [ -d "$WORLD_DIR" ] || fail "нет дерева мира $WORLD_DIR"
  cd "$WORLD_DIR" && docker compose logs --tail 120 game
  exit 0
fi
if [ "$DOWN" = 1 ]; then
  [ -d "$WORLD_DIR" ] || fail "нет дерева мира $WORLD_DIR"
  compose down
  note "мир остановлен; данные персонажей остались в volume eastbrook_pgdata"
  exit 0
fi

# --- docker -----------------------------------------------------------------
# --print-only затем и нужен, чтобы команды можно было посмотреть на машине БЕЗ
# docker (и в песочнице разработки): проверка docker в этом режиме пропускается.
if [ "$PRINT_ONLY" = 0 ]; then
  command -v docker >/dev/null 2>&1 || fail "нет docker. Windows: Docker Desktop (WSL2 backend); Linux: docker engine + плагин compose"
  docker compose version >/dev/null 2>&1 || fail "нет docker compose v2 (плагин). Проверь: docker compose version"
  docker info >/dev/null 2>&1 || fail "демон docker не запущен или нет прав. Windows: запусти Docker Desktop; Linux: systemctl start docker"
fi
command -v node >/dev/null 2>&1 || fail "нет node — им нечем сверить версию дерева мира"
command -v curl >/dev/null 2>&1 || [ "$PRINT_ONLY" = 1 ] || fail "нет curl — нечем проверить готовность сервера"

# --- дерево мира ------------------------------------------------------------
if [ ! -f "$WORLD_DIR/docker-compose.yml" ]; then
  if [ "$CLONE" = 1 ]; then
    note "клонирую полный чекаут игры в $WORLD_DIR (это несколько ГБ: образ собирается из контекста репозитория)"
    run git clone "$GAME_REPO" "$WORLD_DIR"
    run git -C "$WORLD_DIR" checkout "$GAME_REF"
  else
    fail "в $WORLD_DIR нет docker-compose.yml. Полный чекаут мира:
  git clone $GAME_REPO $WORLD_DIR && git -C $WORLD_DIR checkout $GAME_REF
или запусти этот скрипт с флагом --clone.
Лёгкое дерево фактов (~/woc-game) для хостинга мира НЕ годится: compose собирает образ из всего репозитория."
  fi
fi
[ -f "$WORLD_DIR/docker-compose.yml" ] || [ "$PRINT_ONLY" = 1 ] || fail "после клонирования в $WORLD_DIR всё ещё нет docker-compose.yml"

# пин версии: мир и дерево фактов обязаны быть одной версии, иначе «эталон»
# сравнивает разные игры
WORLD_VERSION="$(node -p "require('$WORLD_DIR/package.json').version" 2>/dev/null || echo '')"
if [ "$PRINT_ONLY" = 0 ] && [ "$WORLD_VERSION" != "$GAME_EXPECTED_VERSION" ]; then
  fail "дерево мира $WORLD_DIR: версия '$WORLD_VERSION', ожидаем '$GAME_EXPECTED_VERSION'.
  git -C $WORLD_DIR fetch --tags && git -C $WORLD_DIR checkout $GAME_REF
Мир другой версии и дерево фактов другой версии — это две разные игры: эталоны прогона становятся бессмысленными."
fi
note "дерево мира: $WORLD_DIR, версия ${WORLD_VERSION:-<в --print-only не проверяется>}, ref=$GAME_REF"

# --- .env и пароль Postgres -------------------------------------------------
if [ ! -f "$WORLD_DIR/.env" ]; then
  note "создаю .env из .env.example"
  run cp "$WORLD_DIR/.env.example" "$WORLD_DIR/.env"
fi
if [ -f "$WORLD_DIR/.env" ]; then
  PG_PASS="$(grep -E '^POSTGRES_PASSWORD=' "$WORLD_DIR/.env" | tail -1 | cut -d= -f2- || true)"
  if [ -z "$PG_PASS" ] || [ "$PG_PASS" = "change-me" ]; then
    if command -v openssl >/dev/null 2>&1; then
      NEW_PASS="$(openssl rand -hex 32)"
      # пароль остаётся в .env и в журнал НЕ печатается
      run sed -i.bak "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${NEW_PASS}|" "$WORLD_DIR/.env"
      run sed -i.bak "s|^DATABASE_URL=.*|DATABASE_URL=postgres://eastbrook:${NEW_PASS}@127.0.0.1:5433/eastbrook|" "$WORLD_DIR/.env"
      rm -f "$WORLD_DIR/.env.bak"
      note "POSTGRES_PASSWORD сгенерирован и записан в .env (в журнал не выводится)"
    else
      fail "в $WORLD_DIR/.env пароль Postgres не задан (POSTGRES_PASSWORD=change-me), а openssl нет.
Задай длинный случайный пароль руками в POSTGRES_PASSWORD и в DATABASE_URL
(формат: postgres://eastbrook:<пароль>@127.0.0.1:5433/eastbrook)."
    fi
  else
    note "POSTGRES_PASSWORD в .env задан (значение не печатаем)"
  fi
  if grep -qE '^ALLOW_DEV_COMMANDS=1' "$WORLD_DIR/.env"; then
    note "ВНИМАНИЕ: ALLOW_DEV_COMMANDS=1 — включён набор /dev-читов (level, teleport, выдача предметов, спавн мобов)."
    note "Прогон с читами — ПРИВИЛЕГИРОВАННЫЙ: он обязан быть объявлен в evidence и не считается переносимым."
    note "Типизированный путь команд агента dev-токены не выпускает вовсе (DISPATCH_ONLY_COMMANDS)."
  fi
fi

# --- подъём мира ------------------------------------------------------------
if [ "$NO_BUILD" = 1 ]; then
  compose up -d postgres game
else
  note "собираю образ и поднимаю postgres + game (первая сборка — минуты)"
  compose up -d --build postgres game
fi

# --- готовность -------------------------------------------------------------
if [ "$PRINT_ONLY" = 1 ]; then
  echo "  \$ curl -sf $WORLD_URL/api/status   # в цикле до ${READY_TIMEOUT} с"
else
  note "жду готовности $WORLD_URL/api/status (до ${READY_TIMEOUT} с)"
  deadline=$(( $(date +%s) + READY_TIMEOUT )); ok=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -sf "$WORLD_URL/api/status" >/dev/null 2>&1; then ok=1; break; fi
    sleep 5
  done
  if [ "$ok" != 1 ]; then
    ( cd "$WORLD_DIR" && docker compose logs --tail 80 game ) || true
    fail "сервер не ответил на $WORLD_URL/api/status за ${READY_TIMEOUT} с. Журнал выше; частые причины: образ не собрался, занят порт 8787, Postgres не поднялся."
  fi
  note "мир готов: $WORLD_URL"
fi

# --- симлинк для WS-транспорта ---------------------------------------------
if [ "$LINK_GAME" = 1 ]; then
  [ -d "$WORLD_DIR/src/net" ] || fail "в $WORLD_DIR нет src/net — WS-транспорт не скомпилируется (нужен полный чекаут)"
  [ -d "$WORLD_DIR/src/sim" ] || fail "в $WORLD_DIR нет src/sim — дерево мира неполное"
  note "перевожу симлинк woof-ts/game на $WORLD_DIR (WS-транспорт импортирует src/net/**)"
  if ! ln -sfn "$WORLD_DIR" "$ROOT/game" 2>/dev/null; then
    note "ln не сработал (Windows без прав на симлинки). Сделай ссылку сам:"
    note "  cmd /c mklink /D \"$ROOT\\game\" \"$(cygpath -w "$WORLD_DIR" 2>/dev/null || echo "$WORLD_DIR")\""
  fi
  note "после этого: npm run typecheck && bash tools/check_all.sh (дерево полное — tsc дольше)"
fi

cat <<NEXT

Что дальше:
  1. Открой в браузере $WORLD_URL — создай аккаунт и персонажа (это твой мир, ты в нём играешь).
  2. Агент подключается отдельным WS-клиентом: у него СВОЙ аккаунт и СВОЙ персонаж
     (иначе сервер ответит 'character already in world'). Провод и кадры уже описаны
     в src/bridge/ws_protocol.ts, сокет — в src/bridge/ws_socket.ts.
  3. Следующие шаги A1.2/A1.3 (REST-вход агента и мир поверх сокета) — в ONLINE-WORLD.md и ROADMAP.md.
  4. Остановить мир: bash tools/run_world.sh --down     Журнал: bash tools/run_world.sh --logs

NEXT
note "готово"

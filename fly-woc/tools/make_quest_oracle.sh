#!/usr/bin/env bash
# make_quest_oracle.sh — таблица оракула из игрового кода КОНКРЕТНОЙ сборки.
#
#   bash tools/make_quest_oracle.sh v0.40.0 data/quest_oracle_214.json
#   bash tools/make_quest_oracle.sh /path/to/game-clone data/quest_oracle_214.json
#
# Почему так, а не «взять готовый файл»: порядок квестов в obs — это QUEST_ORDER
# сборки. Таблица от другой версии даёт ЧУЖИЕ координаты, причём молча:
# у v0.42.2 (224) порядок расходится с v0.40.0 (214) уже со второй позиции.
# Полный tarball игры весит ~780 МБ, поэтому клон разреженный (--filter=blob:none
# --sparse): тянется только src/sim.
set -euo pipefail
TAG_OR_DIR="${1:?нет аргумента: тег игры (v0.40.0) или путь к клону}"
OUT="${2:?нет аргумента: куда писать таблицу}"
case "$OUT" in /*) ;; *) OUT="$(pwd)/$OUT" ;; esac   # путь считаем от места вызова, не от клона игры ;;
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${QUEST_ORACLE_WORK:-/tmp/quest-oracle-build}"
mkdir -p "$WORK"

if [ -d "$TAG_OR_DIR/src/sim" ]; then
  GAME="$TAG_OR_DIR"
else
  GAME="$WORK/$TAG_OR_DIR"
  if [ ! -d "$GAME/src/sim" ]; then
    git clone -q --depth 1 --branch "$TAG_OR_DIR" --filter=blob:none --sparse \
      https://github.com/levy-street/world-of-claudecraft "$GAME"
    (cd "$GAME" && git sparse-checkout set src/sim >/dev/null)
  fi
fi

cp "$HERE/dump_quest_oracle.ts" "$GAME/"
(cd "$GAME" && npx --yes esbuild dump_quest_oracle.ts --bundle --platform=node \
   --format=cjs --outfile="$WORK/dump.$$.cjs" >/dev/null && node "$WORK/dump.$$.cjs" > "$OUT")
rm -f "$WORK/dump.$$.cjs"

python3 - "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
g = d["game"]
# obs.ts: obs = 63 (self+target+mobs+interact+хвост 3) + 2*слоты + 2*квесты
expect = (g["obs_size"] - 63 - 2 * g["ability_slots"]) / 2
assert expect == g["quests_count"], f"obs={g['obs_size']} не согласуется с {g['quests_count']} квестами (ожидалось {expect})"
assert g["base_actions"] + g["ability_slots"] == g["actions"], "базовые+способности != actions"
assert len(d["order"]) == g["quests_count"] == len(d["quests"]), "order/quests не совпадают с quests_count"
print(f"ok: {sys.argv[1]} — {g['quests_count']} квестов, obs={g['obs_size']}, "
      f"actions={g['actions']} ({g['base_actions']}+{g['ability_slots']})")
PY

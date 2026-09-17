#!/usr/bin/env bash
# Хук-предохранитель: блокирует то, что в этом проекте делать нельзя.
# Контракт: hermes/hooks/README.md. Вход — JSON на stdin, выход — JSON с continue/message.
set -uo pipefail

event=$(cat 2>/dev/null || echo '{}')

read_field() {
  EVENT="$event" FIELD="$1" python3 -c '
import json, os, sys
try:
    d = json.loads(os.environ.get("EVENT") or "{}")
except Exception:
    sys.exit(0)
v = d.get(os.environ["FIELD"], "")
if isinstance(v, list):
    print(" ".join(str(x) for x in v))
elif v is None:
    print("")
else:
    print(v)
' 2>/dev/null || echo ""
}

command=$(read_field command)
paths=$(read_field paths)
tool=$(read_field tool)
blob="$command $paths"

deny() {
  printf '{"continue": false, "message": "%s"}\n' "$(printf '%s' "$1" | sed 's/"/\\"/g')"
  exit 1
}
allow() {
  [ -n "${1:-}" ] && printf '{"continue": true, "message": "%s"}\n' "$(printf '%s' "$1" | sed 's/"/\\"/g')" \
                  || printf '{"continue": true}\n'
  exit 0
}

case "$blob" in
  *"push --force"*|*"push -f"*|*"push --mirror"*)
    deny "force/mirror push запрещён: только fast-forward в разрешённые ветки. Если пуш отклонён — сначала свежий клон и merge-base, потом разбор (у нас локальная история уже расходилась с remote)." ;;
esac

case "$blob" in
  *hermes-agent*|*hermes-gateway*)
    case "$blob" in
      *kill*|*pkill*|*taskkill*|*"stop-process"*|*Stop-Process*)
        deny "hermes-agent / hermes-gateway убивать запрещено — они чужие для этого проекта. Если мешает занятый порт, разбираемся, чей процесс, и сообщаем пользователю." ;;
    esac ;;
esac

case "$blob" in
  *"D:\\woc"*|*"D:/woc"*|*world-of-claudecraft/src/sim/*|*world-of-claudecraft/src/*)
    deny "исходники игры менять нельзя. Работаем только с мостом и агентом; игру считаем чужой системой." ;;
esac

case "$blob" in
  *connectome-weights.feather*|*".git/lfs"*)
    deny "тяжёлые артефакты (connectome-weights.feather и подобное) в коммит не кладём: LFS исчерпан, файлы >100 МБ — только в Releases." ;;
esac

case "$blob" in
  *quest_oracle*.json*|*circuit.json*)
    case "$blob" in
      *rm\ *|*"rm -"*|*del\ *|*Remove-Item*)
        deny "удалять таблицы оракула и схему нельзя: circuit.json и data/quest_oracle*.json - это воспроизводимость. Если нужна новая версия, клади рядом и указывай sha старой." ;;
    esac ;;
esac

case "$blob" in
  *male-cns*|*gsutil*|*build_full_circuit*|*"211K"*|*"full-connectome"*)
    deny "полные данные MaleCNS и полномасштабная сборка/тренировка запускаются ТОЛЬКО с явного подтверждения пользователя (LFS исчерпан, в песочнице нет ни места, ни GPU)." ;;
esac

case "$blob" in
  *".feather"*)
    case "$blob" in
      *"git add"*|*"git commit"*) deny "feather-файлы (веса/аннотации коннектома) в коммит не кладём: >100 МБ идут в Releases." ;;
    esac ;;
esac

case "$blob" in
  *WOC_BRAIN_BACKEND=edge*|*WOC_BRAIN_BACKEND=sparse*)
    case "$blob" in
      *cpu*|*--device\ cpu*)
        allow "ВНИМАНИЕ: edge/sparse на CPU в ~13 раз медленнее scipy (843 мс против 62 мс на шаг, B=4). Для CPU-прогона оставь auto/scipy." ;;
    esac ;;
esac

case "$blob" in
  *"git push"*)
    case "$blob" in
      *master*|*main*|*release*|*levy-street*)
        allow "ВНИМАНИЕ: push в защищённую ветку. Разрешено только по явной команде пользователя и только fast-forward." ;;
      *)
        allow "push — ок. Перед ним: свежий клон + merge-base --is-ancestor, потом сверка diffstat." ;;
    esac ;;
esac

case "$blob" in
  *"pnpm run dev"*|*"npm run dev"*|*"reload"*"CDP"*|*Page.reload*)
    allow "ВНИМАНИЕ: запуск/перезагрузка игры и браузера — только по явной команде пользователя (он может быть в игре)." ;;
esac

case "$blob" in
  *run_tests.sh*|*run_e2e.sh*|*gpu_check.py*|*accel_m1_m3.sh*)
    allow "Это проверка — правильно. Ожидаемый результат сверяем со строкой из hermes/TOOLS.md." ;;
esac

allow

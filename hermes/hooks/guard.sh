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
  *"D:\\woc"*|*"D:/woc"*|*world-of-claudecraft/src/sim/*|*world-of-claudecraft/src/*|*archive/fly-line/src-fly_brain/*)
    deny "исходники игры менять нельзя. Работаем только с мостом и агентом; игру считаем чужой системой." ;;
esac

case "$blob" in
  *connectome-weights.feather*|*".git/lfs"*)
    deny "тяжёлые артефакты (connectome-weights.feather и подобное) в коммит не кладём: LFS исчерпан, файлы >100 МБ — только в Releases." ;;
esac

case "$blob" in
  *archive/*)
    case "$blob" in
      *rm\ *|*"rm -"*|*del\ *|*Remove-Item*|*"git rm"*)
        deny "archive/ удалять нельзя: там итоги fly-линии, включая отрицательные (M3 = 0 квестов). Знание не удаляется. Архив мешает — скажи пользователю, решение его." ;;
      *"git mv"*|*mv\ *)
        deny "из archive/ ничего не переносим и не переименовываем без явной задачи «разморозить fly-линию». Архив заморожен 2026-09-18." ;;
      *"git commit"*|*"git add"*)
        allow "ВНИМАНИЕ: правка в archive/. Архив заморожен: итоги задним числом не переписываем. Новый факт про архив — отдельной строкой с датой в archive/fly-line/README.md." ;;
    esac ;;
esac

case "$blob" in
  *circuit*.json*|*quest_oracle*.json*|*params_*.pt*)
    case "$blob" in
      *rm\ *|*"rm -"*|*del\ *|*Remove-Item*)
        deny "схемы, таблицы квестов и чек-инты — это воспроизводимость (лежат в archive/fly-line/). Удалять нельзя: новая версия кладётся рядом, с sha старой." ;;
    esac ;;
esac

case "$blob" in
  *male-cns*|*gsutil*|*build_full_circuit*|*"211K"*|*"full-connectome"*|*".feather"*)
    deny "тяжёлые данные коннектома (MaleCNS, .feather, полномасштабная сборка/тренировка) — ТОЛЬКО с явного подтверждения пользователя: линия в архиве, LFS исчерпан, файлы >100 МБ в репозиторий не кладутся." ;;
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
  *run_tests.sh*|*run_e2e.sh*|*build.sh*|*selftest.sh*)
    allow "Это проверка — правильно. Ожидаемый результат сверяем со строкой из hermes/TOOLS.md." ;;
  *archive/fly-line/*run_checks.sh*|*gpu_check.py*|*accel_m1_m3.sh*)
    allow "ВНИМАНИЕ: это проверка АРХИВНОЙ fly-линии (нужен torch, пути с archive/fly-line/). Активная линия — woof-agent; запускаем только при задаче «разморозить муху»." ;;
esac

allow

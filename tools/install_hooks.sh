#!/usr/bin/env bash
# Включить хуки репозитория: git config core.hooksPath .githooks
# В песочнице .git между ходами стирается, поэтому скрипт не падает молча,
# а прямо говорит, что поставить хуки некуда — и что делать на своей машине.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

chmod +x .githooks/* tools/*.sh woof-ts/tools/*.sh 2>/dev/null || true

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "нет .git в $ROOT — хуки не включить."
  echo "На своей машине: git clone <repo> && cd <repo> && bash tools/install_hooks.sh"
  exit 1
fi

git config core.hooksPath .githooks
echo "хуки включены: core.hooksPath=$(git config core.hooksPath)"
echo "проверка: git commit --allow-empty -m test  (должен пройти пре-коммит)"

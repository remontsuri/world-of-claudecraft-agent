#!/usr/bin/env bash
# Сборка без Maven: javac + libs/*.jar
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/classes}"
[ -n "$(ls -1 "$ROOT"/libs/*.jar 2>/dev/null)" ] || bash "$ROOT/tools/fetch_libs.sh"
mkdir -p "$OUT"
find "$ROOT/src" -name '*.java' > "$OUT/sources.txt"
javac -encoding UTF-8 -cp "$ROOT/libs/*" -d "$OUT" @"$OUT/sources.txt"
echo "build ok -> $OUT ($(find "$ROOT/src" -name '*.java' | wc -l) files)"

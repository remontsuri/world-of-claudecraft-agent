#!/usr/bin/env bash
# Скачать Java-зависимости без Maven (в песочнице mvn нет).
set -euo pipefail
cd "$(dirname "$0")/../libs"
BASE=https://repo1.maven.org/maven2
for p in \
  com/fasterxml/jackson/core/jackson-databind/2.15.2/jackson-databind-2.15.2.jar \
  com/fasterxml/jackson/core/jackson-core/2.15.2/jackson-core-2.15.2.jar \
  com/fasterxml/jackson/core/jackson-annotations/2.15.2/jackson-annotations-2.15.2.jar \
  org/java-websocket/Java-WebSocket/1.5.3/Java-WebSocket-1.5.3.jar \
  org/slf4j/slf4j-api/2.0.9/slf4j-api-2.0.9.jar \
  org/slf4j/slf4j-simple/2.0.9/slf4j-simple-2.0.9.jar ; do
  f=$(basename "$p")
  if [ -s "$f" ]; then echo "ok        $f"; else curl -sfL -o "$f" "$BASE/$p" && echo "downloaded $f"; fi
done
echo "libs: $(ls -1 *.jar 2>/dev/null | wc -l) jar"

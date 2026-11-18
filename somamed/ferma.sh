#!/bin/bash
# Spegne interfaccia, servizio dati e database (i dati restano nel volume Docker).
. "$(dirname "$0")/_comune.sh"
for f in registro/interfaccia.pid registro/servizio.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
usa_docker && docker info >/dev/null 2>&1 && $COMPOSE stop >/dev/null && echo "Database spento."
echo "Fatto."

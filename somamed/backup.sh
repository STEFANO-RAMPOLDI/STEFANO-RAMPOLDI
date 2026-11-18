#!/bin/bash
# Copia di sicurezza completa del database.  Uso: bash backup.sh  → backup/somamed_crm_AAAA-MM-GG_HHMM.sql.gz
. "$(dirname "$0")/_comune.sh"
set -o pipefail
mkdir -p backup
F="backup/somamed_crm_$(date +%Y-%m-%d_%H%M).sql.gz"
if usa_docker; then
  docker exec somamed-crm-db pg_dump -U crm -d somamed_crm --clean --if-exists | gzip > "$F"
else
  pg_dump "$CRM_DSN" --clean --if-exists | gzip > "$F"
fi
ESITO=$?
[ "$ESITO" = "0" ] && [ -s "$F" ] && gzip -t "$F" && echo "   copia salvata in $F" || { echo "Copia NON riuscita"; rm -f "$F"; exit 1; }
ls -1t backup/somamed_crm_*.sql.gz 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null   # tiene le ultime 30

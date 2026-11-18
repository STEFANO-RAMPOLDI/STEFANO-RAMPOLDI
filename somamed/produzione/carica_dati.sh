#!/bin/bash
# DAL MAC: porta sul server i dati del CRM locale (una volta, quando passi all'online).
#   bash produzione/carica_dati.sh utente@indirizzo-del-server
# Il database online viene SOSTITUITO dalla copia del Mac (prima ne viene fatta una copia sul server).
set -e
cd "$(dirname "$0")/.."
S="$1"; [ -n "$S" ] || { echo "Uso: bash produzione/carica_dati.sh utente@indirizzo-del-server"; exit 1; }
echo "1/3  Copia dei dati del Mac..."
bash backup.sh
F=$(ls -1t backup/somamed_crm_*.sql.gz | head -1)
echo "2/3  Invio $F al server..."
scp -q "$F" "$S":somamed/produzione/backup/dal-mac.sql.gz
echo "3/3  Sul server: copia di sicurezza del database online, poi sostituzione..."
ssh -t "$S" 'cd ~/somamed/produzione &&
  docker compose exec -T db pg_dump -U crm -d somamed_crm --clean --if-exists | gzip > backup/somamed_$(date +%F_%H%M)_prima-del-mac.sql.gz &&
  bash ripristina_server.sh backup/dal-mac.sql.gz'

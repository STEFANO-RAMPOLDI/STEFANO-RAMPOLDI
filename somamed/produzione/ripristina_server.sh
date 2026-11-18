#!/bin/bash
# Rimette nel database online una copia.  Sul server:  bash ripristina_server.sh backup/<file>.sql.gz
# Tutto o niente: se qualcosa va storto il database resta com'era.
cd "$(dirname "$0")"
[ -f "$1" ] || { echo "Indica il file: bash ripristina_server.sh backup/<file>.sql.gz"; ls -1t backup | head; exit 1; }
gzip -t "$1" || { echo "Il file è danneggiato."; exit 1; }
gunzip -c "$1" | tail -5 | grep -q "PostgreSQL database dump complete" || { echo "La copia è incompleta o vuota: non la uso."; exit 1; }
read -r -p "Il database online verrà sostituito da $1. Scrivi SI per continuare: " ok
[ "$ok" = "SI" ] || { echo "Annullato."; exit 1; }
if gunzip -c "$1" | docker compose exec -T db psql -q -v ON_ERROR_STOP=1 --single-transaction -U crm -d somamed_crm >/dev/null; then
  docker compose restart servizio >/dev/null
  echo "Copia ripristinata."
else
  echo "Ripristino NON riuscito: il database è rimasto com'era."; exit 1
fi

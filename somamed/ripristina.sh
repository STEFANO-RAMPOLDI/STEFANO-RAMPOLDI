#!/bin/bash
# Rimette nel database una copia fatta con backup.sh.  Uso: bash ripristina.sh backup/nome-del-file.sql.gz
. "$(dirname "$0")/_comune.sh"
[ -f "$1" ] || { echo "Indica il file: bash ripristina.sh backup/nome-del-file.sql.gz"; exit 1; }
gzip -t "$1" || { echo "Il file è danneggiato."; exit 1; }
gunzip -c "$1" | tail -5 | grep -q "PostgreSQL database dump complete" || { echo "La copia è incompleta o vuota: non la uso."; exit 1; }
read -p "Il database attuale verrà sostituito dalla copia $1. Scrivi SI per continuare: " ok
[ "$ok" = "SI" ] || { echo "Annullato."; exit 1; }
if usa_docker; then
  gunzip -c "$1" | docker exec -i somamed-crm-db psql -q -v ON_ERROR_STOP=1 --single-transaction -U crm -d somamed_crm
else
  gunzip -c "$1" | psql -q -v ON_ERROR_STOP=1 --single-transaction "$CRM_DSN"
fi && echo "Copia ripristinata." || echo "Ripristino NON riuscito: il database è rimasto com'era."

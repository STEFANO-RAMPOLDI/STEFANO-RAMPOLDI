#!/bin/sh
# Gira dentro il contenitore "backup": una copia completa del database appena acceso e poi ogni notte alle 2.
# Le copie vanno in produzione/backup sul server; si tengono quelle degli ultimi 14 giorni.
copia() {
  f="/backup/somamed_$(date +%F_%H%M).sql.gz"
  if pg_dump -h db -U crm -d somamed_crm --clean --if-exists | gzip > "$f" && gzip -t "$f" \
     && gunzip -c "$f" | tail -5 | grep -q "PostgreSQL database dump complete"; then
    echo "$(date '+%F %T') copia salvata: $f"
  else
    echo "$(date '+%F %T') COPIA NON RIUSCITA"
    mv "$f" "$f.difettosa" 2>/dev/null
  fi
  find /backup -name 'somamed_*.sql.gz*' -mtime +14 -delete
}
sleep 120   # il servizio intanto crea o aggiorna lo schema
copia
while true; do
  h=$(date +%-H); m=$(date +%-M)                       # minuti che mancano alle 2 di notte
  attesa=$(( (26 * 60 - (h * 60 + m)) % (24 * 60) ))
  [ "$attesa" -lt 1 ] && attesa=1440
  sleep $(( attesa * 60 ))
  copia
done

#!/bin/bash
# Dopo aver caricato i file nuovi (pubblica.sh dal Mac):  sul server  cd ~/somamed/produzione && bash aggiorna_server.sh
# Fa una copia di sicurezza, ricostruisce il servizio e lo riavvia; il database si aggiorna da solo.
set -e
cd "$(dirname "$0")"
mkdir -p backup
F="backup/somamed_$(date +%F_%H%M)_prima-di-aggiornare.sql.gz"
echo "1/3  Copia di sicurezza: $F"
docker compose exec -T db pg_dump -U crm -d somamed_crm --clean --if-exists | gzip > "$F"
gzip -t "$F" && gunzip -c "$F" | tail -5 | grep -q "PostgreSQL database dump complete" || { echo "Copia di sicurezza NON riuscita: non aggiorno."; exit 1; }
echo "2/3  Ricostruisco e riavvio..."
docker compose up -d --build
echo "3/3  Controllo..."
set -a; . ./.env; set +a
for i in $(seq 1 30); do curl -sf "https://$DOMINIO/api/salute" >/dev/null 2>&1 && break; sleep 3; done
curl -s "https://$DOMINIO/api/salute"; echo
docker image prune -f >/dev/null

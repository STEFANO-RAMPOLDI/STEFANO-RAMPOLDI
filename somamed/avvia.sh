#!/bin/bash
# Accende database, servizio dati e interfaccia, e apre il browser.  Ctrl+C (o bash ferma.sh) per chiudere.
. "$(dirname "$0")/_comune.sh"
[ -x "$PY" ] || { echo "Prima lancia: bash installa.sh"; exit 1; }

echo "1/3  Database..."
accendi_database

echo "2/3  Servizio dati  → http://$CRM_HOST:$CRM_PORT/api/salute"
(cd servizio && exec "$PY" -m crm.web) >> registro/servizio.log 2>&1 &
echo $! > registro/servizio.pid
for i in $(seq 1 40); do curl -sf "http://127.0.0.1:$CRM_PORT/api/salute" >/dev/null 2>&1 && break; sleep 0.5; done
curl -sf "http://127.0.0.1:$CRM_PORT/api/salute" >/dev/null 2>&1 || { echo "   il servizio non parte: guarda registro/servizio.log"; tail -20 registro/servizio.log; kill "$(cat registro/servizio.pid)" 2>/dev/null; exit 1; }

echo "3/3  Interfaccia    → http://127.0.0.1:$CRM_UI_PORT"
"$PY" interfaccia/server.py "$CRM_UI_PORT" "${CRM_UI_HOST:-127.0.0.1}" >> registro/interfaccia.log 2>&1 &
echo $! > registro/interfaccia.pid

chiudi() { kill "$(cat registro/interfaccia.pid 2>/dev/null)" "$(cat registro/servizio.pid 2>/dev/null)" 2>/dev/null
           rm -f registro/*.pid; echo; echo "Interfaccia e servizio chiusi (il database resta acceso: bash ferma.sh per spegnerlo)."; exit 0; }
trap chiudi INT TERM
sleep 1; apri "http://127.0.0.1:$CRM_UI_PORT"
echo ""
echo "CRM acceso. Lascia aperta questa finestra; Ctrl+C per chiudere."
wait

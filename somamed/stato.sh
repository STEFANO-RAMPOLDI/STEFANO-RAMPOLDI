#!/bin/bash
# Dice se database, servizio dati e interfaccia funzionano.
. "$(dirname "$0")/_comune.sh"
echo "Servizio dati: $(curl -s "http://127.0.0.1:$CRM_PORT/api/salute" || echo 'spento')"
curl -sf -o /dev/null "http://127.0.0.1:$CRM_UI_PORT/" && echo "Interfaccia:   accesa (http://127.0.0.1:$CRM_UI_PORT)" || echo "Interfaccia:   spenta"
if usa_docker; then echo "Database:      $(docker inspect -f '{{.State.Health.Status}}' somamed-crm-db 2>/dev/null || echo 'spento')"; fi

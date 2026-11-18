#!/bin/bash
# Avviato da Claude Desktop (vedi collega_claude.sh): apre il tunnel SSH verso il database online e avvia il ponte MCP.
# Non scrivere nulla sullo standard output: è il canale tra Claude e il CRM.
D="$(cd "$(dirname "$0")/.." && pwd)"
. "$D/produzione/remoto.env"
PORTA=5434
if ! (echo > /dev/tcp/127.0.0.1/$PORTA) 2>/dev/null; then
  ssh -f -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -L "$PORTA:127.0.0.1:5432" "$SERVER" </dev/null >/dev/null 2>&1 \
    || echo "Tunnel SSH verso $SERVER non riuscito" >&2
fi
export CRM_DSN="postgresql://crm:${DB_PASSWORD}@127.0.0.1:${PORTA}/somamed_crm" PYTHONPATH="$D/servizio" CRM_CONFIG=/dev/null
exec "$D/servizio/.venv/bin/python" -m crm.server

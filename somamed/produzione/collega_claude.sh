#!/bin/bash
# DAL MAC: Claude Desktop lavora sul database ONLINE invece che su quello del Mac.
#   bash produzione/collega_claude.sh utente@indirizzo-del-server
# Il database online non è aperto a Internet: Claude ci arriva con un tunnel SSH cifrato, aperto da solo
# quando Claude Desktop parte. Serve l'accesso SSH con chiave (senza password) al server.
# Per tornare al database del Mac:  bash installa.sh
set -e
cd "$(dirname "$0")/.."
RADICE="$(pwd)"; S="$1"
[ -n "$S" ] || { echo "Uso: bash produzione/collega_claude.sh utente@indirizzo-del-server"; exit 1; }
[ -x servizio/.venv/bin/python ] || { echo "Prima lancia bash installa.sh (serve l'ambiente Python sul Mac)."; exit 1; }

echo "1/3  Provo l'accesso SSH con chiave..."
ssh -o BatchMode=yes -o ConnectTimeout=10 "$S" true \
  || { echo "   Non entro senza password. Esegui prima:  ssh-copy-id $S"; exit 1; }

echo "2/3  Leggo dal server la password del database..."
P=$(ssh -o BatchMode=yes "$S" "grep '^DB_PASSWORD=' ~/somamed/produzione/.env | cut -d= -f2-")
[ -n "$P" ] || { echo "   Non trovo ~/somamed/produzione/.env sul server: hai lanciato installa_server.sh?"; exit 1; }
umask 077
printf 'SERVER=%s\nDB_PASSWORD=%s\n' "$S" "$P" > produzione/remoto.env

echo "3/3  Collego Claude Desktop..."
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
[ -d "$HOME/Library" ] || CFG="$HOME/.config/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CFG")"
[ -f "$CFG" ] && cp "$CFG" "$CFG.backup-$(date +%Y%m%d%H%M%S)"
servizio/.venv/bin/python - "$CFG" "$RADICE" <<'PYEOF'
import json, os, sys
cfg, d = sys.argv[1], sys.argv[2]
data = json.load(open(cfg)) if os.path.exists(cfg) and os.path.getsize(cfg) else {}
data.setdefault("mcpServers", {})["somamed-crm"] = {"command": "/bin/bash", "args": [f"{d}/produzione/mcp_remoto.sh"]}
json.dump(data, open(cfg, "w"), indent=2)
PYEOF
echo ""
echo "Fatto. Chiudi Claude Desktop (Cmd+Q) e riaprilo: somamed-crm ora legge e scrive sul CRM online."

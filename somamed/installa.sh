#!/bin/bash
# Installazione del CRM SomaMed (una volta sola):  bash installa.sh
set -e
. "$(dirname "$0")/_comune.sh"

echo "1/5  Controllo Python..."
P=$(command -v python3.14 || command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
"$P" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)' \
  || { echo "Serve Python dalla 3.10 alla 3.14 (consigliata 3.14, da python.org; la 3.15 non è ancora supportata dai pacchetti). Trovato: $("$P" --version 2>&1)"; exit 1; }

"$P" -c "import socket; socket.getaddrinfo('pypi.org', 443)" 2>/dev/null \
  || { echo "Il Mac non raggiunge pypi.org (dove si scaricano i pacchetti): controlla internet, spegni la VPN o prova un'altra rete, poi rilancia."; exit 1; }

echo "2/5  Ambiente Python del servizio dati..."
if [ -x "$PY" ] && ! "$PY" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)' 2>/dev/null; then
  echo "   l'ambiente esistente usa $("$PY" --version 2>&1): lo ricreo con $("$P" --version)"
  mv servizio/.venv "servizio/.venv-vecchio-$(date +%s)"
fi
[ -x "$PY" ] || "$P" -m venv servizio/.venv
servizio/.venv/bin/pip install -q --upgrade pip
servizio/.venv/bin/pip install -q -r servizio/requirements.txt

echo "3/5  Database (PostgreSQL + pgvector in Docker)..."
accendi_database
(cd servizio && "$PY" -c "from crm import core; n = core.migra(); print('   struttura del database:', ', '.join(n) if n else 'già aggiornata')")

echo "4/5  Modello per la ricerca per significato (una volta sola, ~250 MB)..."
(cd servizio && "$PY" -c "from crm.embed import embed; embed('prova'); print('   modello pronto')")

echo "5/5  Collego il CRM a Claude Desktop..."
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
[ -d "$HOME/Library" ] || CFG="$HOME/.config/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CFG")"
[ -f "$CFG" ] && cp "$CFG" "$CFG.backup-$(date +%Y%m%d%H%M%S)"
"$PY" - "$CFG" "$RADICE" <<'PYEOF'
import json, os, sys
cfg, d = sys.argv[1], sys.argv[2]
data = json.load(open(cfg)) if os.path.exists(cfg) and os.path.getsize(cfg) else {}
data.setdefault("mcpServers", {})["somamed-crm"] = {
    "command": f"{d}/servizio/.venv/bin/python",
    "args": ["-m", "crm.server"],
    "env": {"PYTHONPATH": f"{d}/servizio", "CRM_CONFIG": f"{d}/config.env"},
}
json.dump(data, open(cfg, "w"), indent=2)
PYEOF

echo ""
echo "Fatto. Chiudi Claude Desktop (Cmd+Q) e riaprilo: comparirà somamed-crm."
echo "Per l'interfaccia:  bash avvia.sh"

#!/bin/bash
# Aggiorna un CRM già installato (i dati restano nel database).  Uso: bash aggiorna.sh
set -e
. "$(dirname "$0")/_comune.sh"
[ -x "$PY" ] || { echo "Non trovo l'installazione: lancia prima bash installa.sh"; exit 1; }
echo "1/3  Copia di sicurezza prima di aggiornare..."
accendi_database
bash backup.sh
echo "2/3  Pacchetti Python..."
servizio/.venv/bin/pip install -q -r servizio/requirements.txt
echo "3/3  Struttura del database..."
(cd servizio && "$PY" -c "from crm import core; n = core.migra(); print('   applicati:', ', '.join(n) if n else 'nessuno, già aggiornata')")
echo "Fatto. Riapri Claude Desktop (Cmd+Q) e rilancia bash avvia.sh"

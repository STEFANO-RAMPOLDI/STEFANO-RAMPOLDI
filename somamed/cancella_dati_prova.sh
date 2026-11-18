#!/bin/bash
# Cancella i dati inventati per le prove.  Uso: bash cancella_dati_prova.sh   (aggiungi "tutto" per TUTTI i dati di lavoro)
. "$(dirname "$0")/_comune.sh"
COSA="${1:-prova}"
read -p "Cancello i dati ($COSA). Scrivi CANCELLA per continuare: " ok
[ "$ok" = "CANCELLA" ] || { echo "Annullato."; exit 1; }
(cd servizio && "$PY" -m crm.dati "$COSA")

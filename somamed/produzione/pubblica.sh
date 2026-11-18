#!/bin/bash
# DAL MAC: copia (o aggiorna) il programma sul server, senza toccare dati, password e utenti del server.
#   bash produzione/pubblica.sh utente@indirizzo-del-server
set -e
cd "$(dirname "$0")/.."
[ -n "$1" ] || { echo "Uso: bash produzione/pubblica.sh utente@indirizzo-del-server"; exit 1; }
rsync -az \
  --exclude '.venv/' --exclude '__pycache__/' --exclude 'registro/' --exclude '/backup/' --exclude 'config.env' \
  --exclude 'produzione/.env' --exclude 'produzione/remoto.env' --exclude 'produzione/utenti.caddy' --exclude 'produzione/backup/' \
  ./ "$1":somamed/
echo ""
echo "Programma copiato in ~/somamed sul server."
echo "Prima volta:   ssh $1   poi   cd ~/somamed/produzione && sudo bash installa_server.sh"
echo "Aggiornamento: ssh $1   poi   cd ~/somamed/produzione && bash aggiorna_server.sh"

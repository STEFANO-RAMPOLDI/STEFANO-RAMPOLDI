#!/bin/bash
# Chi può entrare nel CRM online.  Sul server, in ~/somamed/produzione:
#   bash utente.sh aggiungi [nome]    nuovo utente (o nuova password per uno esistente)
#   bash utente.sh togli nome         toglie l'accesso
#   bash utente.sh elenco
cd "$(dirname "$0")"
touch utenti.caddy
CADDY_IMG="caddy:2.10-alpine"

ricarica() {   # applica subito, senza spegnere nulla (se il CRM è acceso)
  if docker compose ps --status running web 2>/dev/null | grep -q web; then
    docker compose exec -T web caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
      && echo "   accessi aggiornati" || echo "   ATTENZIONE: Caddy non ha accettato la modifica: docker compose logs web"
  fi
}
senza() {      # utenti.caddy senza la riga di $1 — riscritto sul posto (il file è montato nel contenitore)
  local tmp; tmp=$(grep -v "^$1 " utenti.caddy || true)
  printf "%s\n" "$tmp" | sed '/^$/d' > utenti.caddy.nuovo
  cat utenti.caddy.nuovo > utenti.caddy
  : > utenti.caddy.nuovo
}

case "$1" in
  aggiungi)
    nome="$2"; [ -n "$nome" ] || read -r -p "   Nome utente (es. stefano, senza spazi): " nome
    [[ "$nome" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "   Solo lettere, numeri, punto, trattino."; exit 1; }
    read -r -s -p "   Password per $nome (almeno 12 caratteri): " pw; echo
    read -r -s -p "   Ripeti la password: " pw2; echo
    [ "$pw" = "$pw2" ] || { echo "   Le password non coincidono."; exit 1; }
    [ ${#pw} -ge 12 ] || { echo "   Troppo corta: almeno 12 caratteri."; exit 1; }
    hash=$(printf '%s\n' "$pw" | docker run --rm -i "$CADDY_IMG" caddy hash-password) || { echo "   Errore nel calcolo della password."; exit 1; }
    senza "$nome"
    echo "$nome $hash" >> utenti.caddy
    echo "   utente $nome pronto"; ricarica ;;
  togli)
    [ -n "$2" ] || { echo "Uso: bash utente.sh togli nome"; exit 1; }
    [ "$(grep -vc "^$2 " utenti.caddy)" -ge 1 ] || { echo "   Non tolgo l'ultimo utente: nessuno potrebbe più entrare."; exit 1; }
    senza "$2"; echo "   accesso di $2 tolto"; ricarica ;;
  elenco)
    cut -d' ' -f1 utenti.caddy ;;
  *)
    echo "Uso: bash utente.sh aggiungi [nome] | togli nome | elenco" ;;
esac

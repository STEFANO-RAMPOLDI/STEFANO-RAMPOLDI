#!/bin/bash
# Installazione del CRM SomaMed su un server Linux (Ubuntu/Debian). Si lancia SUL SERVER, una volta:
#   cd ~/somamed/produzione && sudo bash installa_server.sh
set -e
cd "$(dirname "$0")"
[ "$(id -u)" = "0" ] || { echo "Lancialo con sudo:  sudo bash installa_server.sh"; exit 1; }
PROPRIETARIO="${SUDO_USER:-root}"

echo "1/6  Docker..."
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
[ "$PROPRIETARIO" != "root" ] && usermod -aG docker "$PROPRIETARIO" || true

echo "2/6  Firewall: aperti solo SSH, HTTP e HTTPS..."
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

echo "3/6  Impostazioni (produzione/.env)..."
if [ ! -f .env ]; then
  read -r -p "   Indirizzo del CRM (es. crm.somamed.it): " DOM
  {
    echo "DOMINIO=$DOM"
    echo "DB_PASSWORD=$(openssl rand -hex 24)"
    echo "CRM_TOKEN=$(openssl rand -hex 32)"
    echo "ANTHROPIC_API_KEY="
  } > .env
  echo "   password del database e chiave interna generate"
fi
chmod 600 .env; chown "$PROPRIETARIO" .env
set -a; . ./.env; set +a

echo "4/6  Controllo che $DOMINIO punti a questo server..."
IP_SERVER=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
IP_DNS=$(getent ahostsv4 "$DOMINIO" | awk 'NR==1{print $1}')
if [ -z "$IP_DNS" ]; then
  echo "   ATTENZIONE: $DOMINIO non esiste ancora nel DNS. Crea il record A verso $IP_SERVER e rilancia."; exit 1
elif [ "$IP_DNS" != "$IP_SERVER" ]; then
  echo "   ATTENZIONE: $DOMINIO punta a $IP_DNS, questo server è $IP_SERVER."
  read -r -p "   Continuo lo stesso? (s/N) " ok; [ "$ok" = "s" ] || exit 1
else
  echo "   ok ($IP_SERVER)"
fi

echo "5/6  Utenti che possono entrare..."
mkdir -p backup; touch utenti.caddy; chown "$PROPRIETARIO" utenti.caddy backup
[ -s utenti.caddy ] || bash utente.sh aggiungi

echo "6/6  Avvio (la prima volta qualche minuto: si scarica il modello semantico)..."
docker compose up -d --build
printf "   attendo"
for i in $(seq 1 90); do
  if curl -sf "https://$DOMINIO/api/salute" >/dev/null 2>&1; then echo " — pronto"; break; fi
  printf "."; sleep 4
done
echo
curl -s "https://$DOMINIO/api/salute" || { echo "Non risponde ancora: guarda  docker compose logs --tail 50"; exit 1; }
echo
echo "Fatto. Apri  https://$DOMINIO  ed entra con l'utente appena creato."
echo "Altri utenti:   bash utente.sh aggiungi        Copie di sicurezza: produzione/backup (ogni notte)"
echo "IMPORTANTE: esci (exit) e rientra con ssh, così puoi usare docker senza sudo."

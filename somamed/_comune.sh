# Funzioni comuni agli script del CRM SomaMed (non si lancia da solo).
cd "$(dirname "$0")"
RADICE="$(pwd)"
[ -f config.env ] || cp config.env.esempio config.env
set -a; . ./config.env; set +a          # impostazioni: dove stanno i dati, porte, chiave
CRM_PORT="${CRM_PORT:-8080}"; CRM_UI_PORT="${CRM_UI_PORT:-8081}"; CRM_HOST="${CRM_HOST:-127.0.0.1}"
PY="$RADICE/servizio/.venv/bin/python"
COMPOSE="docker compose -f $RADICE/database/docker-compose.yml"
mkdir -p "$RADICE/registro"

usa_docker() {   # il database è quello in Docker se CRM_DSN punta alla porta 5433 di questo computer
  [ "${CRM_DB_DOCKER:-}" = "0" ] && return 1     # database già acceso in altro modo (server, Postgres installato)
  case "${CRM_DSN:-}" in *localhost:5433*|*127.0.0.1:5433*|"") return 0;; *) return 1;; esac
}

accendi_database() {
  usa_docker || { echo "   database esterno: ${CRM_DSN#*@}"; return 0; }
  command -v docker >/dev/null || { echo "Manca Docker Desktop: scaricalo da docker.com, aprilo e rilancia."; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Docker non è acceso: apri Docker Desktop e rilancia."; exit 1; }
  $COMPOSE up -d >/dev/null
  printf "   attendo il database"
  for i in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' somamed-crm-db 2>/dev/null)" = "healthy" ] && { echo " — pronto"; return 0; }
    printf "."; sleep 2
  done
  echo; echo "Il database non risponde. Guarda: docker logs somamed-crm-db"; exit 1
}

apri() { (command -v open >/dev/null && open "$1") || (command -v xdg-open >/dev/null && xdg-open "$1") || true; }

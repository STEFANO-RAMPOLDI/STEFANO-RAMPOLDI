"""Configurazione: separa i dati (database) dal servizio e dall'interfaccia.

Legge config.env nella cartella principale di SomaMed (o il file indicato da CRM_CONFIG).
Le variabili già impostate nell'ambiente hanno la precedenza."""
import os
from pathlib import Path

SERVIZIO = Path(__file__).resolve().parent.parent          # somamed/servizio
RADICE = SERVIZIO.parent                                   # somamed/
FILE = Path(os.environ.get("CRM_CONFIG") or RADICE / "config.env")

if FILE.exists():
    for riga in FILE.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        k, v = riga.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _int(nome, predefinito):
    try:
        return int(os.environ.get(nome, "") or predefinito)
    except ValueError:
        return predefinito


# --- database ---
DSN = os.environ.get("CRM_DSN", "postgresql://crm:crm@localhost:5433/somamed_crm")
TZ = os.environ.get("CRM_TZ", "Europe/Rome")
MIGRAZIONI = Path(os.environ.get("CRM_MIGRAZIONI") or RADICE / "database" / "migrazioni")
POOL_MIN = _int("CRM_POOL_MIN", 1)              # connessioni tenute sempre aperte
POOL_MAX = _int("CRM_POOL_MAX", 10)             # massimo di connessioni contemporanee
POOL_ATTESA = _int("CRM_POOL_ATTESA_S", 15)     # secondi di attesa di una connessione libera
TIMEOUT_QUERY_MS = _int("CRM_TIMEOUT_QUERY_MS", 30000)  # una query più lunga viene interrotta

# --- servizio dati (API) ---
HOST = os.environ.get("CRM_HOST", "127.0.0.1")
PORT = _int("CRM_PORT", 8080)
TOKEN = os.environ.get("CRM_TOKEN", "").strip()

# --- interfaccia (pagina web, servita a parte) ---
UI_HOST = os.environ.get("CRM_UI_HOST", HOST)
UI_PORT = _int("CRM_UI_PORT", 8081)

# Indirizzi da cui un'interfaccia può leggere i dati. L'interfaccia locale è sempre ammessa.
ORIGINI = [x.strip() for x in os.environ.get("CRM_ORIGINI", "").split(",") if x.strip()]
for _h in {"127.0.0.1", "localhost", UI_HOST}:
    _o = f"http://{_h}:{UI_PORT}"
    if _h != "0.0.0.0" and _o not in ORIGINI:
        ORIGINI.append(_o)

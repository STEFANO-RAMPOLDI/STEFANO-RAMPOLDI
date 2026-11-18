# Architettura del CRM SomaMed

## 1. Tre strati separati

```
 ┌──────────────────────┐   HTTP/JSON (config.js)   ┌───────────────────────────┐   SQL (CRM_DSN)   ┌──────────────────────────┐
 │  INTERFACCIA          │ ───────────────────────▶ │  SERVIZIO DATI             │ ────────────────▶ │  DATABASE                 │
 │  interfaccia/         │      porta 8081 → 8080    │  servizio/crm              │   porta 5433      │  database/                │
 │  index.html, mappa    │                           │  web.py   API REST         │                   │  PostgreSQL 16 + pgvector │
 │  nessun dato          │                           │  server.py Claude (MCP)    │                   │  dati + vettori           │
 └──────────────────────┘                           │  core.py  logica, pool     │                   │  migrazioni/ 001…014      │
                         Claude Desktop ──stdio──▶  └───────────────────────────┘                   └──────────────────────────┘
```

| Strato | Contiene | Conosce solo | Si sposta cambiando |
|---|---|---|---|
| Database | tutti i dati, gli indici, i vettori | — | `CRM_DSN` nel servizio |
| Servizio dati | regole del CRM, controlli, accesso unico ai dati | `CRM_DSN` | l'indirizzo in `interfaccia/config.js` |
| Interfaccia | solo presentazione (HTML/JS statici) | l'URL del servizio | nulla: è una cartella di file statici |

Regole che mantengono la separazione:
- l'interfaccia non parla mai con il database; Claude nemmeno (passa da `server.py`, che usa lo stesso `core.py` dell'API);
- la struttura del database si cambia **solo** con un nuovo file `database/migrazioni/0NN_*.sql`
  (idempotente, applicato una volta, in transazione, registrato in `versioni_schema`);
- i file dell'interfaccia sono statici: in produzione si pubblicano con nginx/Caddy o un CDN senza toccare il servizio.

## 2. Il database vettoriale: perché PostgreSQL + pgvector

Requisito: un database vettoriale open source di riferimento, locale, adatto a un CRM che domani sarà multi-utente.

| | **pgvector** (PostgreSQL) | Qdrant | Milvus | Weaviate | Chroma |
|---|---|---|---|---|---|
| Licenza | PostgreSQL (open source) | Apache 2.0 | Apache 2.0 | BSD-3 | Apache 2.0 |
| Dati relazionali + vettori insieme | **sì, stessa tabella** | no (solo vettori + payload) | no | parziale | no |
| Transazioni ACID, chiavi esterne | **sì** | no | no | no | no |
| Filtri complessi (regione, centro, stato) + similarità in una query | **SQL con JOIN** | filtri sul payload | filtri sugli attributi | GraphQL | filtri semplici |
| Utenti, permessi, Row-Level Security | **sì, nativi** | API key | RBAC | API key / OIDC | minimi |
| Backup | un solo `pg_dump` | snapshot separati | separati | separati | file |
| Componenti da gestire | 1 | 2 (+ un DB relazionale) | 3+ (etcd, MinIO) | 2 | 2 |
| Scala adatta | fino a decine di milioni di vettori | centinaia di milioni | miliardi | centinaia di milioni | piccola |

**Scelta: PostgreSQL 16 + pgvector 0.8** (immagine `pgvector/pgvector:0.8.0-pg16`, fissata).

- Un CRM è prima di tutto relazionale (centri → persone → iniziative → attività → esiti). Con pgvector
  la nota e il suo vettore stanno nella stessa riga: niente sincronizzazione fra due database, niente
  vettori "orfani" quando si cancella un centro, un solo backup coerente.
- Le ricerche reali sono ibride ("chi mi ha parlato di sicurezza degli ecografi **in Lombardia**"): in SQL è una
  query sola, con indice HNSW per la similarità e indici B-tree per i filtri. Da pgvector 0.8 l'*iterative scan*
  (attivato dal servizio) garantisce risultati completi anche con filtri molto selettivi.
- Il multi-utente (login, permessi per responsabile, accessi concorrenti) lo dà PostgreSQL di serie.
- Volume previsto: decine di migliaia di note e attività → ampiamente nel campo ideale di pgvector (latenza di
  pochi millisecondi). **Quando ripensarci**: oltre ~10-50 milioni di vettori o con ricerca semantica come
  prodotto a sé; in quel caso Qdrant è l'alternativa naturale, affiancato (non sostituito) a PostgreSQL.

Il calcolo dei vettori resta locale (`fastembed`, modello multilingue MiniLM, 384 dimensioni): i testi non escono
dal computer per questa operazione.

## 3. Prestazioni e resilienza (cosa fa il codice)

| Dove | Cosa | Perché |
|---|---|---|
| `core.connect()` | pool `psycopg_pool` (1–10 connessioni), verifica prima dell'uso, rientrante per thread | niente apertura/chiusura a ogni richiesta; riconnessione automatica; niente blocchi tra funzioni annidate |
| `core.transazione()` | scritture atomiche | offerte, importazioni, cancellazioni, migrazioni |
| connessione | `statement_timeout` 30 s, `connect_timeout` 5 s | una query sbagliata non blocca il servizio |
| errori | `CRMError` → 400, `DatabaseNonRaggiungibile` → 503 | messaggi leggibili invece di errori 500 |
| avvio (`web.py`) | parte anche col database spento, migra appena risponde; `/api/salute` | ordine di accensione non importante |
| `embed.py` | modello caricato una volta (lucchetto), precaricato, cache LRU, calcolo a blocchi | prima ricerca immediata, domande ripetute istantanee |
| `014_prestazioni.sql` | 30 indici su chiavi esterne e filtri, vista `v_iniziative` riscritta | da 32 s a 1,4 s sul carico di prova |
| API | compressione gzip, endpoint asincroni non bloccanti | liste grandi più leggere, nessuna richiesta ferma le altre |
| interfaccia | letture ritentate (rete o 503) | brevi interruzioni invisibili |

## 4. Verso l'uso da più utenti contemporanei — passi proposti

L'architettura attuale è già pronta per i passi seguenti; ognuno è indipendente e si può fare in quest'ordine.

1. **Servizio in rete locale** (subito possibile): `CRM_HOST=0.0.0.0`, `CRM_TOKEN` lunga e casuale,
   `interfaccia/config.js` con l'indirizzo del computer. Va bene per un ufficio, non per Internet.
2. **Utenti veri e login**: tabella `utenti` già presente → password (hash argon2) o accesso con Google/Microsoft
   (OIDC); sessioni con token JWT a scadenza al posto della chiave unica; ogni scrittura registra *chi* l'ha fatta.
3. **Permessi**: ruoli (amministratore, commerciale, sola lettura) e, se serve, Row-Level Security di PostgreSQL
   (ognuno vede i propri centri/attività).
4. **Concorrenza sulle modifiche**: colonna `aggiornato_il` + controllo "qualcun altro ha modificato questa scheda"
   (optimistic locking) e numerazione offerte tramite sequenza.
5. **Server**: database su un server (o PostgreSQL gestito con pgvector), servizio in container dietro HTTPS
   (Caddy/nginx), più processi `uvicorn`/`gunicorn` (il pool regge già più connessioni), interfaccia come file statici.
   Backup automatici giornalieri con `pg_dump` + copia esterna.
6. **Aggiornamenti in tempo reale** (facoltativo): notifiche `LISTEN/NOTIFY` di PostgreSQL → WebSocket, così le
   schermate di più utenti si aggiornano da sole.

## 5. Budget strategico (migrazione 015, `servizio/crm/budget.py`)

```
prodotti ──< prodotti_voci (prezzo, costo, canone/anni, stima per posto letto, quantità fissa)
aziende (+ posti_letto) ──< centri_voci (quantità per voce, fonte: censita / dichiarata / stimata)
budget (prodotto, area, anno, sconto) ──< budget_centri (solo le scelte: incluso, probabilità, strategia, pianificato)
budget.iniziativa_id ──> trattative (iniziativa macro) ──< attivita (+ voce_id: operazione su uno strumento)
```

Valori, fasce, probabilità e strategie **non sono salvati**: si ricalcolano a ogni lettura dai dati correnti, così un
nuovo censimento o un nuovo prezzo aggiornano subito il budget; in tabella restano solo le decisioni dell'utente.
Il venduto si legge da iniziative vinte, esiti «vendita» e offerte accettate (righe del prodotto).

## 6. Collaudi

```bash
# su un database di PROVA (i collaudi si rifiutano di girare su somamed_crm)
cd servizio
export CRM_DSN=postgresql://crm:crm@localhost:5433/somamed_test CRM_EMBEDDER=hash PYTHONPATH=.
for t in tests/test_*.py; do .venv/bin/python "$t" | tail -1; done
```

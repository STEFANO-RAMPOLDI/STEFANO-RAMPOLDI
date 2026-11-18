"""Logica del CRM SomaMed: lettura e scrittura sul database.

Accesso ai dati:
- un *pool* di connessioni riusate (prima ogni richiesta apriva e chiudeva una connessione);
- ogni connessione viene verificata prima dell'uso: se il database è stato riavviato il servizio
  si ricollega da solo, senza essere rilanciato;
- dentro lo stesso thread ``connect()`` è rientrante: le funzioni che si chiamano a vicenda
  usano la stessa connessione invece di prenderne un'altra dal pool (niente blocchi a catena);
- ``transazione()`` per le scritture che devono riuscire tutte o nessuna.
"""
import atexit
import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector

from .embed import embed

from . import config as _config
DSN = _config.DSN
log = logging.getLogger("crm")


class CRMError(Exception):
    """Errore comprensibile da restituire a Claude."""


class DatabaseNonRaggiungibile(CRMError):
    """Il database non risponde (spento, riavvio in corso, rete)."""


ERRORI_CONNESSIONE = (psycopg.OperationalError, psycopg.InterfaceError)

_pool = None
_pool_lock = threading.Lock()
_locale = threading.local()


def _prepara(conn):
    """Impostazioni di ogni nuova connessione del pool."""
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # database nuovo: l'estensione pgvector non è ancora installata → la si crea
        for ext in ("vector", "pg_trgm"):
            try:
                conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
            except psycopg.errors.UniqueViolation:
                pass   # un'altra connessione l'ha appena creata
        register_vector(conn)
    try:   # pgvector >= 0.8: le ricerche per significato con filtri restituiscono sempre abbastanza risultati
        conn.execute("SET hnsw.iterative_scan = relaxed_order")
    except psycopg.Error:
        pass


def _nuovo_pool():
    from psycopg_pool import ConnectionPool
    return ConnectionPool(
        DSN, min_size=_config.POOL_MIN, max_size=max(_config.POOL_MAX, _config.POOL_MIN),
        timeout=_config.POOL_ATTESA, max_idle=300, max_lifetime=3600, reconnect_timeout=0,
        check=ConnectionPool.check_connection, configure=_prepara, open=False, name="crm",
        kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 5,
                "options": f"-c timezone={_config.TZ} -c statement_timeout={_config.TIMEOUT_QUERY_MS}",
                "application_name": "somamed-crm"})


def pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                p = _nuovo_pool()
                p.open(wait=False)   # non blocca l'avvio se il database non è ancora acceso
                _pool = p
                atexit.register(chiudi_pool)
    return _pool


def chiudi_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def connect():
    """Connessione al database presa dal pool (rientrante nello stesso thread)."""
    gia = getattr(_locale, "conn", None)
    if gia is not None and not gia.closed:
        yield gia
        return
    from psycopg_pool import PoolTimeout
    try:
        with pool().connection() as conn:
            _locale.conn = conn
            try:
                yield conn
            finally:
                _locale.conn = None
    except psycopg.errors.QueryCanceled as e:
        raise CRMError("Operazione troppo lunga: interrotta. Restringi la ricerca e riprova.") from e
    except (PoolTimeout, *ERRORI_CONNESSIONE) as e:
        raise DatabaseNonRaggiungibile(
            "Il database non risponde: controlla che sia acceso (bash avvia.sh) e riprova.") from e


@contextmanager
def transazione():
    """Scritture atomiche: o riescono tutte o il database resta com'era."""
    with connect() as conn, conn.transaction():
        yield conn


def salute():
    """Verifica veloce del database, per il controllo del servizio."""
    with connect() as conn:
        r = conn.execute("SELECT now() ora, (SELECT extversion FROM pg_extension WHERE extname='vector') pgvector").fetchone()
        return {"database": "ok", "pgvector": r["pgvector"], "ora": r["ora"].isoformat(timespec="seconds")}


CARTELLA_DB = _config.MIGRAZIONI


def migra():
    """Applica da solo gli aggiornamenti del database (database/migrazioni/0*.sql) non ancora applicati.
    Ogni aggiornamento gira in una transazione: se fallisce a metà, non lascia il database a metà."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_lock(4242)")
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS versioni_schema (
                              file TEXT PRIMARY KEY, applicato_il TIMESTAMPTZ NOT NULL DEFAULT now())""")
            fatti = {r["file"] for r in conn.execute("SELECT file FROM versioni_schema")}
            if fatti and "001_schema.sql" not in fatti:
                # database installato con la versione precedente: lo schema base c'è già (l'ha creato Docker)
                conn.execute("INSERT INTO versioni_schema (file) VALUES ('001_schema.sql') ON CONFLICT DO NOTHING")
                fatti.add("001_schema.sql")
            nuovi = []
            for f in sorted(CARTELLA_DB.glob("0*.sql")):
                if f.name in fatti:
                    continue
                with conn.transaction():
                    conn.execute(f.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO versioni_schema (file) VALUES (%s)", (f.name,))
                nuovi.append(f.name)
                log.info("database aggiornato: %s", f.name)
            return nuovi
        finally:
            conn.execute("SELECT pg_advisory_unlock(4242)")


def _clean(row):
    """Rende i risultati leggibili (date in testo, numeri semplici)."""
    if row is None:
        return None
    out = {}
    for k, v in row.items():
        if k == "embedding" or v is None:
            continue
        if isinstance(v, datetime):
            v = v.isoformat(timespec="minutes")
        elif isinstance(v, date):
            v = v.isoformat()
        elif isinstance(v, Decimal):
            v = float(v)
        out[k] = v
    return out


def _rows(cur):
    return [_clean(r) for r in cur.fetchall()]


def _vec(text):
    import numpy as np
    return np.asarray(embed(text), dtype=np.float32)


# ---------- risoluzione dei nomi ----------

def risolvi_azienda(conn, nome, crea_se_manca=False):
    if not nome:
        return None
    r = conn.execute("SELECT id, nome FROM aziende WHERE lower(nome)=lower(%s)", (nome,)).fetchone()
    if r:
        return r["id"]
    if str(nome).lstrip("#").isdigit():
        return int(str(nome).lstrip("#"))
    cand = conn.execute(
        """SELECT id, nome, similarity(nome, %s) s FROM aziende
           WHERE nome ILIKE '%%' || %s || '%%' OR similarity(nome, %s) > 0.3
           ORDER BY s DESC LIMIT 5""", (nome, nome, nome)).fetchall()
    if len(cand) == 1:
        return cand[0]["id"]
    if len(cand) > 1:
        raise CRMError(f"Azienda '{nome}' ambigua. Possibili: "
                       + ", ".join(c["nome"] for c in cand) + ". Indica il nome esatto.")
    if crea_se_manca:
        return conn.execute("INSERT INTO aziende (nome) VALUES (%s) RETURNING id", (nome,)).fetchone()["id"]
    raise CRMError(f"Azienda '{nome}' non trovata. Creala prima con crea_azienda.")


def risolvi_contatto(conn, nome, azienda_id=None):
    if not nome:
        return None
    if str(nome).lstrip("#").isdigit():
        return int(str(nome).lstrip("#"))
    q = """SELECT c.id, c.nome, c.cognome, a.nome azienda,
                  similarity(coalesce(c.nome,'')||' '||coalesce(c.cognome,''), %s) s
           FROM contatti c LEFT JOIN aziende a ON a.id=c.azienda_id
           WHERE ((coalesce(c.nome,'')||' '||coalesce(c.cognome,'')) ILIKE '%%' || %s || '%%'
                  OR coalesce(c.cognome,'') ILIKE %s
                  OR similarity(coalesce(c.nome,'')||' '||coalesce(c.cognome,''), %s) > 0.3)"""
    params = [nome, nome, nome, nome]
    if azienda_id:
        q += " AND c.azienda_id=%s"
        params.append(azienda_id)
    cand = conn.execute(q + " ORDER BY s DESC LIMIT 5", params).fetchall()
    if len(cand) == 1:
        return cand[0]["id"]
    if len(cand) > 1:
        exact = [c for c in cand if f"{c['nome']} {c['cognome'] or ''}".strip().lower() == nome.lower()]
        if len(exact) == 1:
            return exact[0]["id"]
        raise CRMError(f"Contatto '{nome}' ambiguo. Possibili: " + ", ".join(
            f"n. {c['id']} {c['nome']} {c['cognome'] or ''} ({c['azienda'] or '-'})".strip() for c in cand)
            + ". Indica il numero (es. #12).")
    raise CRMError(f"Contatto '{nome}' non trovato. Crealo prima con crea_contatto.")


def risolvi_trattativa(conn, titolo_o_id):
    if titolo_o_id in (None, ""):
        return None
    if str(titolo_o_id).isdigit():
        return int(titolo_o_id)
    cand = conn.execute(
        """SELECT id, titolo FROM trattative
           WHERE titolo ILIKE '%%' || %s || '%%' OR similarity(titolo, %s) > 0.3
           ORDER BY similarity(titolo, %s) DESC LIMIT 5""",
        (titolo_o_id, titolo_o_id, titolo_o_id)).fetchall()
    if len(cand) == 1:
        return cand[0]["id"]
    if len(cand) > 1:
        raise CRMError("Trattativa ambigua. Possibili: "
                       + ", ".join(f"#{c['id']} {c['titolo']}" for c in cand))
    raise CRMError(f"Trattativa '{titolo_o_id}' non trovata.")


def risolvi_prodotto(conn, nome):
    if nome in (None, ""):
        return None
    if str(nome).isdigit():
        return int(nome)
    cand = conn.execute(
        """SELECT id, nome FROM prodotti
           WHERE nome ILIKE '%%' || %s || '%%' OR similarity(nome, %s) > 0.3
           ORDER BY similarity(nome, %s) DESC LIMIT 5""", (nome, nome, nome)).fetchall()
    if len(cand) == 1:
        return cand[0]["id"]
    if len(cand) > 1:
        exact = [c for c in cand if c["nome"].lower() == str(nome).lower()]
        if exact:
            return exact[0]["id"]
        raise CRMError("Prodotto ambiguo. Possibili: " + ", ".join(c["nome"] for c in cand))
    raise CRMError(f"Prodotto '{nome}' non trovato. Crealo con crea_prodotto o vedi catalogo.")


def risolvi_standard(conn, valore):
    """Accetta il codice (STD-070) o il nome ('Offerta') di un'attività standard."""
    if not valore:
        return None
    r = conn.execute(
        """SELECT codice FROM catalogo_attivita
           WHERE upper(codice)=upper(%s) OR lower(nome)=lower(%s)""", (valore, valore)).fetchone()
    if r:
        return r["codice"]
    cand = conn.execute(
        """SELECT codice, nome FROM catalogo_attivita
           WHERE nome ILIKE '%%' || %s || '%%' OR similarity(nome, %s) > 0.3
           ORDER BY similarity(nome, %s) DESC""", (valore, valore, valore)).fetchall()
    if len(cand) == 1:
        return cand[0]["codice"]
    raise CRMError(f"Attività standard '{valore}' non riconosciuta. Scegli tra: " + ", ".join(
        f"{c['codice']} {c['nome']}" for c in conn.execute(
            "SELECT codice, nome FROM catalogo_attivita ORDER BY ordine").fetchall()))


# ---------- aziende e contatti ----------

CAMPI_AZIENDA = ["tipo", "citta", "regione", "provincia", "indirizzo", "cap", "natura", "dimensione",
                 "telefono", "email", "sito", "ats", "relazione", "strategicita", "note", "notion_url"]


def crea_azienda(nome, tipo="altro", citta=None, regione=None, sito=None, tag=None, note=None,
                 provincia=None, natura=None, dimensione=None, indirizzo=None, telefono=None,
                 email=None, cap=None, ats=None, relazione=None, strategicita=None, notion_url=None):
    """Crea un centro o, se esiste già con lo stesso nome, ne completa i dati."""
    v = dict(tipo=tipo, citta=citta, regione=regione, provincia=(provincia or "").upper() or None,
             indirizzo=indirizzo, cap=cap, natura=natura, dimensione=dimensione, telefono=telefono,
             email=email, sito=sito, ats=ats, relazione=relazione, strategicita=strategicita,
             note=note, notion_url=notion_url)
    with connect() as conn:
        if v["provincia"] and not v["regione"]:
            r = conn.execute("SELECT regione FROM province WHERE sigla=%s", (v["provincia"],)).fetchone()
            v["regione"] = r["regione"] if r else None
        cols = ", ".join(CAMPI_AZIENDA)
        ph = ", ".join(["%s"] * len(CAMPI_AZIENDA))
        upd = ", ".join(f"{c}=coalesce(EXCLUDED.{c}, aziende.{c})" for c in CAMPI_AZIENDA if c != "tipo")
        r = conn.execute(
            f"""INSERT INTO aziende (nome, tag, {cols}) VALUES (%s, %s, {ph})
                ON CONFLICT (nome) DO UPDATE SET
                  tipo=CASE WHEN EXCLUDED.tipo IS NULL OR EXCLUDED.tipo='altro' THEN aziende.tipo ELSE EXCLUDED.tipo END,
                  tag=(SELECT coalesce(array_agg(DISTINCT t), '{{}}') FROM unnest(aziende.tag || EXCLUDED.tag) t),
                  {upd}
                RETURNING id""",
            [nome, tag or []] + [v[c] for c in CAMPI_AZIENDA]).fetchone()
        return _clean(conn.execute("SELECT * FROM v_aziende WHERE id=%s", (r["id"],)).fetchone())


CAMPI_CONTATTO = ["nome", "cognome", "ruolo", "email", "telefono", "note", "professionalita",
                  "email_privata", "cellulare", "telefono_privato", "linkedin", "esperienze",
                  "conosciuto_personalmente", "notion_url"]


def crea_contatto(nome, cognome=None, azienda=None, ruolo=None, email=None,
                  telefono=None, tag=None, note=None, professionalita=None, email_privata=None,
                  cellulare=None, telefono_privato=None, linkedin=None, esperienze=None,
                  conosciuto_personalmente=False, business=None, notion_url=None, chiave_import=None):
    with connect() as conn:
        az = risolvi_azienda(conn, azienda, crea_se_manca=True) if azienda else None
        v = dict(nome=nome, cognome=cognome, ruolo=ruolo, email=email, telefono=telefono, note=note,
                 professionalita=professionalita, email_privata=email_privata, cellulare=cellulare,
                 telefono_privato=telefono_privato, linkedin=linkedin, esperienze=esperienze,
                 conosciuto_personalmente=bool(conosciuto_personalmente), notion_url=notion_url)
        cols = ", ".join(CAMPI_CONTATTO)
        ph = ", ".join(["%s"] * len(CAMPI_CONTATTO))
        if chiave_import:
            upd = ", ".join(f"{c}=coalesce(EXCLUDED.{c}, contatti.{c})" for c in CAMPI_CONTATTO
                            if c != "conosciuto_personalmente")
            r = conn.execute(
                f"""INSERT INTO contatti (azienda_id, tag, business, chiave_import, {cols})
                    VALUES (%s, %s, %s, %s, {ph})
                    ON CONFLICT (chiave_import) DO UPDATE SET
                      azienda_id=coalesce(EXCLUDED.azienda_id, contatti.azienda_id), {upd}
                    RETURNING id""",
                [az, tag or [], business or [], chiave_import] + [v[c] for c in CAMPI_CONTATTO]).fetchone()
        else:
            r = conn.execute(
                f"""INSERT INTO contatti (azienda_id, tag, business, {cols}) VALUES (%s, %s, %s, {ph})
                    RETURNING id""", [az, tag or [], business or []] + [v[c] for c in CAMPI_CONTATTO]).fetchone()
        return _clean(conn.execute("SELECT * FROM contatti WHERE id=%s", (r["id"],)).fetchone())


def aggiorna_contatto(contatto, **campi):
    """Aggiorna i dati di una persona (solo i campi indicati)."""
    ammessi = set(CAMPI_CONTATTO) - {"notion_url"}
    campi = {k: v for k, v in campi.items() if k in ammessi and v is not None}
    with connect() as conn:
        cid = int(contatto) if str(contatto).isdigit() else risolvi_contatto(conn, contatto)
        if "azienda" in campi:
            pass
        if campi:
            sets = ", ".join(f"{k}=%s" for k in campi)
            conn.execute(f"UPDATE contatti SET {sets} WHERE id=%s", list(campi.values()) + [cid])
        return _clean(conn.execute("SELECT * FROM contatti WHERE id=%s", (cid,)).fetchone())


def collega_contatti(contatto_a, contatto_b, tipo="amicizia", note=None):
    """Registra un'amicizia o conoscenza tra due persone."""
    with connect() as conn:
        a = int(contatto_a) if str(contatto_a).isdigit() else risolvi_contatto(conn, contatto_a)
        b = int(contatto_b) if str(contatto_b).isdigit() else risolvi_contatto(conn, contatto_b)
        if a == b:
            raise CRMError("Una persona non può essere collegata a se stessa.")
        r = conn.execute(
            """INSERT INTO relazioni_contatti (contatto_a, contatto_b, tipo, note) VALUES (%s,%s,%s,%s)
               ON CONFLICT (least(contatto_a, contatto_b), greatest(contatto_a, contatto_b), tipo)
               DO UPDATE SET note=coalesce(EXCLUDED.note, relazioni_contatti.note) RETURNING *""",
            (a, b, tipo, note)).fetchone()
        return _clean(r)


def relazioni_di(conn, cid):
    return _rows(conn.execute(
        """SELECT r.id rel_id, r.tipo, r.note, c.id, trim(c.nome||' '||coalesce(c.cognome,'')) nome,
                  c.ruolo, c.conosciuto_personalmente, a.id azienda_id, a.nome azienda
           FROM relazioni_contatti r
           JOIN contatti c ON c.id = CASE WHEN r.contatto_a=%s THEN r.contatto_b ELSE r.contatto_a END
           LEFT JOIN aziende a ON a.id=c.azienda_id
           WHERE %s IN (r.contatto_a, r.contatto_b) ORDER BY nome""", (cid, cid)))


def scrivi_diario(testo, giorno=None, azienda=None, contatto=None):
    """Aggiunge una voce al diario della giornata (oggi se non indicato)."""
    with connect() as conn:
        az = (int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)) if azienda else None
        ct = (int(contatto) if str(contatto).isdigit() else risolvi_contatto(conn, contatto, az)) if contatto else None
        if ct and not az:
            az = conn.execute("SELECT azienda_id FROM contatti WHERE id=%s", (ct,)).fetchone()["azienda_id"]
        r = conn.execute(
            """INSERT INTO diario (giorno, testo, azienda_id, contatto_id, embedding)
               VALUES (coalesce(%s::date, current_date), %s, %s, %s, %s) RETURNING id""",
            (giorno, testo, az, ct, _vec(testo))).fetchone()
        return _clean(conn.execute(
            "SELECT genere,id,testo,giorno,azienda,provincia,regione,contatto FROM v_note WHERE genere='diario' AND id=%s",
            (r["id"],)).fetchone())


def _lista(v):
    if not v: return []
    if isinstance(v, (list, tuple)): return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def filtro_luoghi(conn, regione=None, provincia=None, col_prov="provincia", col_reg="regione"):
    """Filtro per più regioni e più province (testo separato da virgole).
    Una regione senza province scelte vale tutta la regione."""
    regs, provs = _lista(regione), [x.upper() for x in _lista(provincia)]
    if not regs and not provs:
        return [], []
    reg_di = {r["sigla"]: r["regione"] for r in conn.execute(
        "SELECT sigla, regione FROM province WHERE sigla = ANY(%s)", (provs,)).fetchall()} if provs else {}
    piene = [r.lower() for r in regs if r not in reg_di.values()]
    parti, p = [], []
    if provs:
        parti.append(f"upper({col_prov}) = ANY(%s)"); p.append(provs)
    if piene:
        parti.append(f"lower({col_reg}) = ANY(%s)"); p.append(piene)
    return ["(" + " OR ".join(parti) + ")"], p


def cerca_note(domanda=None, azienda=None, provincia=None, regione=None, dal=None, al=None,
               genere=None, limite=30):
    """Note e diario filtrati per centro, provincia, regione, periodo; con domanda: per significato."""
    with connect() as conn:
        w, p = ["true"], []
        if azienda:
            w.append("azienda_id=%s"); p.append(int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda))
        fw, fp = filtro_luoghi(conn, regione, provincia, "provincia", "regione"); w += fw; p += fp
        if dal:
            w.append("giorno >= %s::date"); p.append(dal)
        if al:
            w.append("giorno <= %s::date"); p.append(al)
        if genere:
            w.append("genere=%s"); p.append(genere)
        cols = "genere, id, testo, fonte, giorno, azienda_id, azienda, provincia, regione, contatto_id, contatto"
        if domanda:
            v = _vec(domanda)
            q = f"""SELECT {cols}, round((1-(embedding <=> %s))::numeric,3) somiglianza FROM v_note
                    WHERE {' AND '.join(w)} AND embedding IS NOT NULL ORDER BY embedding <=> %s LIMIT %s"""
            return _rows(conn.execute(q, [v] + p + [v, limite]))
        q = f"SELECT {cols} FROM v_note WHERE {' AND '.join(w)} ORDER BY giorno DESC, id DESC LIMIT %s"
        return _rows(conn.execute(q, p + [limite]))


def trova(testo, limite=10):
    """Cerca aziende e contatti per nome (anche con errori di battitura)."""
    with connect() as conn:
        az = conn.execute(
            """SELECT id, nome, tipo, citta, tag FROM aziende
               WHERE nome ILIKE '%%'||%s||'%%' OR similarity(nome,%s)>0.25
               ORDER BY similarity(nome,%s) DESC LIMIT %s""", (testo, testo, testo, limite))
        aziende = _rows(az)
        ct = conn.execute(
            """SELECT c.id, c.nome, c.cognome, c.ruolo, c.email, c.telefono, a.nome azienda
               FROM contatti c LEFT JOIN aziende a ON a.id=c.azienda_id
               WHERE (c.nome||' '||coalesce(c.cognome,'')) ILIKE '%%'||%s||'%%'
                  OR similarity(c.nome||' '||coalesce(c.cognome,''),%s)>0.25
                  OR a.nome ILIKE '%%'||%s||'%%'
               ORDER BY similarity(c.nome||' '||coalesce(c.cognome,''),%s) DESC LIMIT %s""",
            (testo, testo, testo, testo, limite))
        return {"aziende": aziende, "contatti": _rows(ct)}


def crea_prodotto(nome, divisione="Altro", produttore=None, descrizione=None, tipologie_clienti=None,
                  descrizione_clienti=None):
    with connect() as conn:
        r = conn.execute(
            """INSERT INTO prodotti (nome, divisione, produttore, descrizione, tipologie_clienti, descrizione_clienti)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (nome) DO UPDATE SET divisione=EXCLUDED.divisione,
                 produttore=coalesce(EXCLUDED.produttore, prodotti.produttore),
                 descrizione=coalesce(EXCLUDED.descrizione, prodotti.descrizione),
                 tipologie_clienti=CASE WHEN cardinality(EXCLUDED.tipologie_clienti)>0 THEN EXCLUDED.tipologie_clienti ELSE prodotti.tipologie_clienti END,
                 descrizione_clienti=coalesce(EXCLUDED.descrizione_clienti, prodotti.descrizione_clienti)
               RETURNING *""", (nome, divisione, produttore, descrizione, tipologie_clienti or [], descrizione_clienti)).fetchone()
        return _clean(r)


def catalogo():
    """Attività standard, prodotti e divisioni disponibili."""
    with connect() as conn:
        return {
            "attivita_standard": _rows(conn.execute(
                "SELECT codice, nome, descrizione FROM catalogo_attivita ORDER BY ordine")),
            "prodotti": _rows(conn.execute("SELECT id, nome, divisione, produttore, prezzo_listino, costo, unita, aliquota_iva FROM prodotti ORDER BY divisione, nome")),
            "divisioni": _rows(conn.execute("SELECT nome, descrizione FROM divisioni ORDER BY nome")),
            "professionalita_in_uso": [r["professionalita"] for r in conn.execute(
                "SELECT DISTINCT professionalita FROM contatti WHERE professionalita IS NOT NULL ORDER BY 1")],
        }


# ---------- trattative ----------

def crea_trattativa(titolo, azienda=None, divisione=None, fase="primo contatto", contatto=None,
                    valore_eur=None, probabilita=None, chiusura_prevista=None, prossimo_passo=None,
                    prodotto=None, obiettivo=None, storia=None, genere="commerciale"):
    """Iniziativa (di norma commerciale) con un centro principale."""
    with connect() as conn:
        az = risolvi_azienda(conn, azienda, crea_se_manca=True) if azienda else None
        ct = risolvi_contatto(conn, contatto, az) if contatto else None
        pr = risolvi_prodotto(conn, prodotto) if prodotto else None
        if not divisione:
            divisione = (conn.execute("SELECT divisione FROM prodotti WHERE id=%s", (pr,)).fetchone()
                         or {"divisione": "Altro"})["divisione"] if pr else "Altro"
        r = conn.execute(
            """INSERT INTO trattative (titolo, azienda_id, contatto_id, divisione, fase, valore_eur,
                   probabilita, chiusura_prevista, prossimo_passo, prodotto_id, embedding)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (titolo, az, ct, divisione, fase, valore_eur, probabilita, chiusura_prevista,
             prossimo_passo, pr, _vec(f"{titolo}. {prossimo_passo or ''}"))).fetchone()
        ob = risolvi_obiettivo(conn, obiettivo) if obiettivo else None
        conn.execute("UPDATE trattative SET obiettivo_id=%s, storia=%s, genere=%s WHERE id=%s",
                     (ob, storia, _genere(genere), r["id"]))
        return _clean(conn.execute("SELECT * FROM v_iniziative WHERE id=%s", (r["id"],)).fetchone())


def aggiorna_trattativa(trattativa, fase=None, valore_eur=None, probabilita=None,
                        chiusura_prevista=None, prossimo_passo=None):
    with connect() as conn:
        tid = risolvi_trattativa(conn, trattativa)
        r = conn.execute(
            """UPDATE trattative SET
                 fase=coalesce(%s,fase), valore_eur=coalesce(%s,valore_eur),
                 probabilita=coalesce(%s,probabilita),
                 chiusura_prevista=coalesce(%s,chiusura_prevista),
                 prossimo_passo=coalesce(%s,prossimo_passo), aggiornata_il=now()
               WHERE id=%s RETURNING *""",
            (fase, valore_eur, probabilita, chiusura_prevista, prossimo_passo, tid)).fetchone()
        if not r:
            raise CRMError(f"Trattativa {trattativa} non trovata.")
        conn.execute("UPDATE trattative SET embedding=%s WHERE id=%s",
                     (_vec(f"{r['titolo']}. {r['prossimo_passo'] or ''}"), tid))
        return _clean(r)


def pipeline(divisione=None, includi_chiuse=False):
    with connect() as conn:
        q = """SELECT t.id, t.titolo, a.nome azienda, t.divisione, t.fase, t.valore_eur,
                      t.probabilita, t.chiusura_prevista, t.prossimo_passo
               FROM trattative t LEFT JOIN aziende a ON a.id=t.azienda_id WHERE true"""
        p = []
        if divisione:
            q += " AND t.divisione=%s"
            p.append(divisione)
        if not includi_chiuse:
            q += " AND t.fase NOT IN ('vinta','persa')"
        trat = _rows(conn.execute(q + " ORDER BY t.divisione, t.fase, t.chiusura_prevista NULLS LAST", p))
        tot = {}
        for t in trat:
            d = tot.setdefault(t["divisione"], {"trattative": 0, "valore_eur": 0.0, "valore_pesato_eur": 0.0})
            d["trattative"] += 1
            v = t.get("valore_eur") or 0
            d["valore_eur"] += v
            d["valore_pesato_eur"] += v * (t.get("probabilita") or 0) / 100
        return {"riepilogo": tot, "trattative": trat}


# ---------- attività ----------

def inserisci_attivita(conn, descrizione, tipo="compito", scadenza=None, priorita="media",
                       azienda_id=None, contatto_id=None, trattativa_id=None, prodotto_id=None,
                       codice_standard=None, precedente_id=None, responsabile="Stefano"):
    """Inserisce un'attività già risolta in id. Completa i collegamenti mancanti e la sequenza."""
    if contatto_id and not azienda_id:
        azienda_id = conn.execute("SELECT azienda_id FROM contatti WHERE id=%s", (contatto_id,)).fetchone()["azienda_id"]
    if trattativa_id:
        t = conn.execute("SELECT azienda_id, prodotto_id, contatto_id FROM trattative WHERE id=%s",
                         (trattativa_id,)).fetchone()
        if not t:
            raise CRMError(f"Trattativa {trattativa_id} non trovata.")
        azienda_id = azienda_id or t["azienda_id"]
        prodotto_id = prodotto_id or t["prodotto_id"]
        contatto_id = contatto_id or t["contatto_id"]
    if precedente_id is None:
        # Sequenza automatica: l'ultima attività della stessa trattativa,
        # oppure dello stesso centro sullo stesso prodotto.
        prev = None
        if trattativa_id:
            # dentro una campagna/opportunità la sequenza è per singolo centro
            prev = conn.execute("""SELECT id FROM attivita WHERE trattativa_id=%s
                                     AND azienda_id IS NOT DISTINCT FROM %s
                                   ORDER BY coalesce(scadenza, creata_il) DESC, id DESC LIMIT 1""",
                                (trattativa_id, azienda_id)).fetchone()
        elif azienda_id and prodotto_id:
            prev = conn.execute("""SELECT id FROM attivita WHERE azienda_id=%s AND prodotto_id=%s
                                   ORDER BY coalesce(scadenza, creata_il) DESC, id DESC LIMIT 1""",
                                (azienda_id, prodotto_id)).fetchone()
        precedente_id = prev["id"] if prev else None
    elif precedente_id == 0:
        precedente_id = None
    r = conn.execute(
        """INSERT INTO attivita (tipo, descrizione, scadenza, priorita, azienda_id, contatto_id,
               trattativa_id, prodotto_id, codice_standard, precedente_id, responsabile, embedding)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (tipo, descrizione, scadenza, priorita, azienda_id, contatto_id, trattativa_id, prodotto_id,
         codice_standard, precedente_id, responsabile, _vec(descrizione))).fetchone()
    out = _clean(conn.execute("SELECT * FROM v_attivita WHERE id=%s", (r["id"],)).fetchone())
    if contatto_id:
        av = avvisi_contatto(conn, contatto_id, trattativa_id, escludi=r["id"])
        if av:
            out["attenzione"] = av
    return out


def crea_attivita(descrizione, tipo="compito", scadenza=None, priorita="media", azienda=None,
                  contatto=None, trattativa=None, responsabile="Stefano", attivita_standard=None,
                  prodotto=None, precedente_id=None):
    with connect() as conn:
        az = risolvi_azienda(conn, azienda, crea_se_manca=True) if azienda else None
        ct = risolvi_contatto(conn, contatto, az) if contatto else None
        tr = risolvi_trattativa(conn, trattativa) if trattativa else None
        pr = risolvi_prodotto(conn, prodotto) if prodotto else None
        std = risolvi_standard(conn, attivita_standard) if attivita_standard else None
        return inserisci_attivita(conn, descrizione, tipo, scadenza, priorita, az, ct, tr, pr,
                                  std, precedente_id, responsabile)


def completa_attivita(attivita_id, esito=None, stato="fatta"):
    with connect() as conn:
        r = conn.execute(
            """UPDATE attivita SET stato=%s, esito=coalesce(%s,esito),
                   completata_il=CASE WHEN %s='fatta' THEN now() ELSE completata_il END
               WHERE id=%s RETURNING *""", (stato, esito, stato, attivita_id)).fetchone()
        if not r:
            raise CRMError(f"Attività {attivita_id} non trovata.")
        if esito:
            conn.execute("UPDATE attivita SET embedding=%s WHERE id=%s",
                         (_vec(f"{r['descrizione']}. Esito: {esito}"), attivita_id))
        return _clean(r)


def elenco_attivita(dal=None, al=None, stato="da fare", azienda=None, divisione=None,
                    solo_scadute=False, responsabile=None, limite=50, area=None,
                    professionalita=None, prodotto=None, attivita_standard=None, contatto=None):
    with connect() as conn:
        q = "SELECT * FROM v_attivita WHERE true"
        p = []
        if stato:
            q += " AND stato=%s"; p.append(stato)
        if dal:
            q += " AND scadenza >= %s"; p.append(dal)
        if al:
            q += " AND scadenza < (%s::date + 1)"; p.append(al)
        if solo_scadute:
            q += " AND scaduta"
        if azienda:
            q += " AND azienda_id=%s"; p.append(risolvi_azienda(conn, azienda))
        if contatto:
            q += " AND contatto_id=%s"; p.append(risolvi_contatto(conn, contatto))
        if divisione:
            q += " AND bu=%s"; p.append(divisione)
        if area:
            q += " AND area=%s"; p.append(area)
        if professionalita:
            q += " AND professionalita ILIKE %s"; p.append(professionalita)
        if prodotto:
            q += " AND prodotto_id=%s"; p.append(risolvi_prodotto(conn, prodotto))
        if attivita_standard:
            q += " AND codice_standard=%s"; p.append(risolvi_standard(conn, attivita_standard))
        if responsabile:
            q += " AND responsabile ILIKE %s"; p.append(responsabile)
        q += """ ORDER BY scadenza NULLS LAST,
                 CASE priorita WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END LIMIT %s"""
        p.append(limite)
        return _rows(conn.execute(q, p))


# ---------- note e ricerca semantica ----------

def aggiungi_nota(testo, fonte="chat", azienda=None, contatto=None, trattativa=None):
    with connect() as conn:
        az = risolvi_azienda(conn, azienda, crea_se_manca=True) if azienda else None
        ct = risolvi_contatto(conn, contatto, az) if contatto else None
        tr = risolvi_trattativa(conn, trattativa) if trattativa else None
        r = conn.execute(
            """INSERT INTO note (testo, fonte, azienda_id, contatto_id, trattativa_id, embedding)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (testo, fonte, az, ct, tr, _vec(testo))).fetchone()
        return _clean(r)


def ricerca_semantica(domanda, limite=8):
    """Cerca per significato in note, attività e trattative."""
    v = _vec(domanda)
    with connect() as conn:
        rows = conn.execute(
            """(SELECT 'nota' tipo, n.id, n.testo, n.creata_il data, a.nome azienda,
                       1 - (n.embedding <=> %(v)s) somiglianza
                FROM note n LEFT JOIN aziende a ON a.id=n.azienda_id)
               UNION ALL
               (SELECT 'attività', at.id,
                       at.descrizione || coalesce(' — esito: '||at.esito,''), at.creata_il, a.nome,
                       1 - (at.embedding <=> %(v)s)
                FROM attivita at LEFT JOIN aziende a ON a.id=at.azienda_id)
               UNION ALL
               (SELECT 'trattativa', t.id,
                       t.titolo || coalesce(' — '||t.prossimo_passo,''), t.creata_il, a.nome,
                       1 - (t.embedding <=> %(v)s)
                FROM trattative t LEFT JOIN aziende a ON a.id=t.azienda_id)
               ORDER BY somiglianza DESC LIMIT %(l)s""", {"v": v, "l": limite}).fetchall()
        out = []
        for r in rows:
            r = _clean(r)
            r["somiglianza"] = round(r.get("somiglianza", 0), 3)
            out.append(r)
        return out


def scheda_azienda(nome):
    """Tutto su un'azienda: dati, contatti, trattative, attività aperte, ultime note."""
    with connect() as conn:
        az = risolvi_azienda(conn, nome)
        return {
            "azienda": _clean(conn.execute("SELECT * FROM v_aziende WHERE id=%s", (az,)).fetchone()),
            "contatti": _rows(conn.execute(
                """SELECT id,nome,cognome,ruolo,professionalita,email,telefono,cellulare,
                          conosciuto_personalmente,esperienze FROM contatti WHERE azienda_id=%s
                   ORDER BY conosciuto_personalmente DESC, cognome""", (az,))),
            "diario": _rows(conn.execute(
                "SELECT id,giorno,testo,contatto FROM v_note WHERE genere='diario' AND azienda_id=%s ORDER BY giorno DESC LIMIT 10", (az,))),
            "trattative": _rows(conn.execute(
                """SELECT id,titolo,divisione,fase,valore_eur,probabilita,chiusura_prevista,prossimo_passo
                   FROM trattative WHERE azienda_id=%s ORDER BY aggiornata_il DESC""", (az,))),
            "attivita_aperte": _rows(conn.execute(
                """SELECT id,codice_standard,standard,tipo,descrizione,scadenza,priorita,contatto,prodotto
                   FROM v_attivita WHERE azienda_id=%s AND stato='da fare'
                   ORDER BY scadenza NULLS LAST""", (az,))),
            "ultime_attivita_fatte": _rows(conn.execute(
                """SELECT id,tipo,descrizione,esito,completata_il FROM attivita
                   WHERE azienda_id=%s AND stato='fatta' ORDER BY completata_il DESC LIMIT 5""", (az,))),
            "ultime_note": _rows(conn.execute(
                """SELECT id,testo,fonte,creata_il FROM note WHERE azienda_id=%s
                   ORDER BY creata_il DESC LIMIT 10""", (az,))),
            "operazioni": situazione_centro(conn, az),
        }


def situazione_centro(conn, az):
    """Per un centro: ogni operazione (iniziativa o filone di attività) con stato, esito,
    prodotto, valore, persone con cui è stata gestita, ultima e prossima attività."""
    att = _rows(conn.execute(
        """SELECT id, trattativa_id, prodotto_id, prodotto, contatto_id, contatto, ruolo, conosciuto,
                  codice_standard, standard, descrizione, stato, completata_il, scadenza
           FROM v_attivita WHERE azienda_id=%s
           ORDER BY coalesce(completata_il, scadenza, creata_il)""", (az,)))
    tr = {r["id"]: r for r in _rows(conn.execute(
        """SELECT t.id, t.titolo, t.genere, t.fase, t.valore_eur, t.esito, t.concorrente, t.azienda_id,
                  t.prodotto_id, p.nome prodotto, e.esito esito_centro, e.concorrente concorrente_centro, e.data data_esito
           FROM trattative t LEFT JOIN prodotti p ON p.id=t.prodotto_id
           LEFT JOIN esiti_centro e ON e.trattativa_id=t.id AND e.azienda_id=%s
           WHERE t.azienda_id=%s OR t.id IN (SELECT trattativa_id FROM attivita WHERE azienda_id=%s)
              OR t.id IN (SELECT trattativa_id FROM esiti_centro WHERE azienda_id=%s)""", (az, az, az, az)))}
    gruppi = {}
    for t in tr.values():
        gruppi[("t", t["id"])] = {"trattativa": t, "attivita": []}
    for a in att:
        k = ("t", a.get("trattativa_id")) if a.get("trattativa_id") else ("p", a.get("prodotto_id") or 0)
        g = gruppi.setdefault(k, {"trattativa": None, "prodotto": a.get("prodotto"), "prodotto_id": a.get("prodotto_id"), "attivita": []})
        g["attivita"].append(a)
    out = []
    for k, g in gruppi.items():
        t, A = g.get("trattativa"), g.get("attivita")
        esito = None; concorrente = None; data_esito = None
        if t:
            esito = t.get("esito_centro") or (t.get("esito") if t.get("azienda_id") == az else None)
            concorrente = t.get("concorrente_centro") or (t.get("concorrente") if t.get("azienda_id") == az else None)
            data_esito = t.get("data_esito")
            if not esito and t.get("fase") == "vinta" and t.get("azienda_id") == az: esito = "vendita"
            if not esito and t.get("fase") == "persa" and t.get("azienda_id") == az: esito = "rifiuto"
        aperte = [a for a in A if a.get("stato") == "da fare"]
        fatte = [a for a in A if a.get("stato") == "fatta"]
        if esito: stato = {"vendita": "venduto", "rifiuto": "rifiutato", "scelto altro": "scelto altro",
                           "sospesa": "sospeso"}.get(esito, esito)
        elif aperte or not A: stato = "in corso"
        else: stato = "ferma"
        persone = {}
        for a in A:
            if a.get("contatto_id"):
                p = persone.setdefault(a.get("contatto_id"), {"id": a.get("contatto_id"), "nome": a.get("contatto"), "ruolo": a.get("ruolo"),
                                                          "conosciuto": a.get("conosciuto"), "n": 0})
                p["n"] += 1
        ultima = fatte[-1] if fatte else None
        out.append({
            "trattativa_id": t["id"] if t else None,
            "titolo": t.get("titolo") if t else ("Attività su " + (g.get("prodotto") or "temi generali")),
            "genere": t.get("genere") if t else None,
            "prodotto_id": (t.get("prodotto_id") if t else None) or g.get("prodotto_id") or next((a.get("prodotto_id") for a in A if a.get("prodotto_id")), None),
            "prodotto": (t.get("prodotto") if t else None) or g.get("prodotto") or next((a.get("prodotto") for a in A if a.get("prodotto")), None),
            "valore_eur": t.get("valore_eur") if t and t.get("azienda_id") == az else None,
            "stato": stato, "esito": esito, "concorrente": concorrente, "data_esito": data_esito,
            "persone": sorted(persone.values(), key=lambda p: -p["n"]),
            "n_fatte": len(fatte), "n_aperte": len(aperte),
            "ultima": {k2: ultima.get(k2) for k2 in ("id", "standard", "descrizione", "completata_il", "contatto")} if ultima else None,
            "prossima": {k2: aperte[0].get(k2) for k2 in ("id", "standard", "descrizione", "scadenza", "contatto")} if aperte else None,
        })
    ordine = {"in corso": 0, "ferma": 1, "sospeso": 2, "venduto": 3, "scelto altro": 4, "rifiutato": 5}
    out.sort(key=lambda o: (ordine.get(o["stato"], 9), o["titolo"]))
    return out


def divisioni():
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM divisioni ORDER BY nome"))


# ---------- obiettivi, campagne, esiti ----------

import json as _json

ESITI = ("vendita", "rifiuto", "scelto altro", "sospesa")


def risolvi_obiettivo(conn, valore):
    if valore in (None, ""):
        return None
    if str(valore).isdigit():
        return int(valore)
    cand = conn.execute("""SELECT id, titolo FROM obiettivi WHERE titolo ILIKE '%%'||%s||'%%' OR similarity(titolo,%s)>0.3
                           ORDER BY similarity(titolo,%s) DESC LIMIT 5""", (valore, valore, valore)).fetchall()
    if len(cand) == 1:
        return cand[0]["id"]
    if cand:
        raise CRMError("Obiettivo ambiguo: " + ", ".join(f"#{c['id']} {c['titolo']}" for c in cand))
    raise CRMError(f"Obiettivo '{valore}' non trovato. Crealo con crea_obiettivo.")


def _norm_luoghi(conn, regioni, province):
    regioni = [r for r in (regioni or []) if r]
    province = [p.upper() for p in (province or []) if p]
    # le province portano con sé la loro regione
    for p in province:
        r = conn.execute("SELECT regione FROM province WHERE sigla=%s", (p,)).fetchone()
        if not r:
            raise CRMError(f"Provincia '{p}' sconosciuta: usa la sigla (MI, CO, BS…).")
        if r["regione"] not in regioni:
            regioni.append(r["regione"])
    return regioni, province


def crea_obiettivo(titolo, descrizione=None, scadenza=None, valore_eur=None, tipo="area", ambito=None,
                   padre=None, regioni=None, province=None, target_centri=None, data_inizio=None):
    """Obiettivo (o sotto-obiettivo se c'è il padre) di area o di budget, con regioni e province.
    target_centri: quanti centri conquistare (per gli obiettivi di area)."""
    if tipo not in ("area", "budget"):
        raise CRMError("Tipo obiettivo: area o budget.")
    with connect() as conn:
        pid = risolvi_obiettivo(conn, padre) if padre else None
        regioni, province = _norm_luoghi(conn, regioni, province)
        if pid:
            pa = conn.execute("SELECT regioni, province FROM obiettivi WHERE id=%s", (pid,)).fetchone()
            fuori = [r for r in regioni if pa["regioni"] and r not in pa["regioni"]]
            if fuori:
                raise CRMError("Il sotto-obiettivo esce dalle regioni dell'obiettivo padre: " + ", ".join(fuori))
        r = conn.execute(
            """INSERT INTO obiettivi (titolo, descrizione, scadenza, valore_eur, tipo, ambito, padre_id, regioni, province,
                                     target_centri, data_inizio)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,coalesce(%s::date,current_date)) RETURNING id""",
            (titolo, descrizione, scadenza, valore_eur, tipo, ambito, pid, regioni, province,
             target_centri, data_inizio)).fetchone()
        return _clean(conn.execute("SELECT * FROM v_obiettivi WHERE id=%s", (r["id"],)).fetchone())


def albero_obiettivi():
    """Obiettivi con sotto-obiettivi e iniziative, annidati."""
    with connect() as conn:
        ob = _rows(conn.execute("SELECT * FROM v_obiettivi ORDER BY scadenza NULLS LAST, id"))
        ini = _rows(conn.execute(
            """SELECT id, titolo, genere, fase, esito, obiettivo_id, prodotto, valore_eur, n_centri, n_aperte, n_vendite, target
               FROM v_iniziative WHERE obiettivo_id IS NOT NULL ORDER BY genere, titolo"""))
    per_padre, per_ob = {}, {}
    for o in ob:
        per_padre.setdefault(o.get("padre_id"), []).append(o)
    for i in ini:
        per_ob.setdefault(i["obiettivo_id"], []).append(i)
    def nodo(o):
        o["sotto"] = [nodo(f) for f in per_padre.get(o["id"], [])]
        o["iniziative"] = per_ob.get(o["id"], [])
        return o
    return [nodo(o) for o in per_padre.get(None, [])]


# ---------- verifica del raggiungimento degli obiettivi ----------

FASI = [  # (nome, ordine minimo dello standard, probabilità di chiusura)
    ("Primo contatto", 10, 0.05), ("Esigenza e presentazione", 20, 0.15), ("Demo, sopralluogo, dati", 40, 0.30),
    ("Offerta", 70, 0.50), ("Negoziazione e gara", 90, 0.70), ("Ordine e consegna", 110, 0.95),
]


def _fase(ordine):
    if not ordine:
        return None, 0.02
    nome, pr = FASI[0][0], FASI[0][2]
    for n, o, p in FASI:
        if ordine >= o:
            nome, pr = n, p
    return nome, pr


def avanzamento_obiettivo(obiettivo):
    """Verifica del raggiungimento di un obiettivo (con i suoi sotto-obiettivi) sulla base delle attività:
    raggiunto, quanto manca, copertura delle trattative aperte, previsione, ritmo necessario, centri per fase."""
    from datetime import date
    with connect() as conn:
        oid = risolvi_obiettivo(conn, obiettivo)
        o = _clean(conn.execute("SELECT * FROM v_obiettivi WHERE id=%s", (oid,)).fetchone())
        ids = [r["id"] for r in conn.execute(
            """WITH RECURSIVE t AS (SELECT id FROM obiettivi WHERE id=%s
                 UNION ALL SELECT o.id FROM obiettivi o JOIN t ON o.padre_id=t.id) SELECT id FROM t""", (oid,)).fetchall()]
        ini = _rows(conn.execute(
            """SELECT t.id, t.titolo, t.genere, t.fase, t.esito, t.valore_eur, t.azienda_id
               FROM trattative t WHERE t.obiettivo_id = ANY(%s)""", (ids,)))
        tids = [i["id"] for i in ini]
        att = _rows(conn.execute(
            """SELECT id, trattativa_id, azienda_id, azienda, provincia, contatto, codice_standard, standard, ordine_standard,
                      stato, scaduta, completata_il, scadenza
               FROM v_attivita WHERE trattativa_id = ANY(%s)""", (tids,))) if tids else []
        esiti = {(e["trattativa_id"], e["azienda_id"]): e for e in _rows(conn.execute(
            "SELECT trattativa_id, azienda_id, esito, concorrente FROM esiti_centro WHERE trattativa_id = ANY(%s)", (tids,)))} if tids else {}
        nomi_az = {r["id"]: r for r in _rows(conn.execute(
            "SELECT id, nome, upper(provincia) provincia FROM aziende WHERE id = ANY(%s)",
            (list({a["azienda_id"] for a in att if a.get("azienda_id")} | {i["azienda_id"] for i in ini if i.get("azienda_id")}),)))}

    oggi = date.today()
    # ---- centri: una riga per (iniziativa, centro)
    righe = {}
    for i in ini:
        if i.get("azienda_id"):
            righe[(i["id"], i["azienda_id"])] = {"trattativa_id": i["id"], "azienda_id": i["azienda_id"], "att": []}
    for a in att:
        if a.get("azienda_id"):
            righe.setdefault((a["trattativa_id"], a["azienda_id"]), {"trattativa_id": a["trattativa_id"], "azienda_id": a["azienda_id"], "att": []})["att"].append(a)
    per_ini = {i["id"]: i for i in ini}
    centri = []
    for (tid, az), r in righe.items():
        i = per_ini[tid]; A = r["att"]
        fatte = [a for a in A if a.get("stato") == "fatta"]
        aperte = [a for a in A if a.get("stato") == "da fare"]
        ordine = max([a.get("ordine_standard") or 0 for a in fatte] or [0])
        e = esiti.get((tid, az))
        esito = e["esito"] if e else (i.get("esito") if i.get("azienda_id") == az else None)
        if not esito and i.get("azienda_id") == az and i.get("fase") == "vinta": esito = "vendita"
        if not esito and i.get("azienda_id") == az and i.get("fase") == "persa": esito = "rifiuto"
        fase, prob = _fase(ordine)
        ultima = max([a.get("completata_il") or "" for a in fatte] or [""]) or None
        prossima = min(aperte, key=lambda a: a.get("scadenza") or "9999") if aperte else None
        giorni_fermo = None
        if ultima:
            try: giorni_fermo = (oggi - date.fromisoformat(str(ultima)[:10])).days
            except Exception: pass
        centri.append({
            "azienda_id": az, "azienda": (nomi_az.get(az) or {}).get("nome"), "provincia": (nomi_az.get(az) or {}).get("provincia"),
            "trattativa_id": tid, "trattativa": i.get("titolo"), "genere": i.get("genere"),
            "fase": "Venduto" if esito == "vendita" else fase or "Da contattare", "probabilita": 1.0 if esito == "vendita" else (0 if esito in ("rifiuto", "scelto altro") else prob),
            "esito": esito, "concorrente": (e or {}).get("concorrente"),
            "fatte": len(fatte), "aperte": len(aperte), "scadute": sum(1 for a in aperte if a.get("scaduta")),
            "ultima": ultima, "giorni_fermo": giorni_fermo,
            "prossima": {"id": prossima["id"], "standard": prossima.get("standard"), "scadenza": prossima.get("scadenza")} if prossima else None,
        })

    # ---- valori
    budget = float(o.get("valore_eur") or o.get("budget_sotto") or 0)
    venduto = float(o.get("valore_vinto") or 0)
    aperto = float(o.get("valore_aperto") or 0)
    previsto_aperto = 0.0
    for i in ini:
        chiusa = i.get("fase") in ("vinta", "persa") or i.get("esito") or any(
            c["esito"] == "vendita" for c in centri if c["trattativa_id"] == i["id"])
        if chiusa or not i.get("valore_eur"):
            continue
        cs = [c for c in centri if c["trattativa_id"] == i["id"] and not c["esito"]]
        pr = max([c["probabilita"] for c in cs] or [0.02])
        previsto_aperto += float(i["valore_eur"]) * pr
    mancante = max(0.0, budget - venduto) if budget else None
    scoperto = max(0.0, budget - venduto - aperto) if budget else None
    previsione = venduto + previsto_aperto

    # ---- tempo
    inizio = o.get("data_inizio") or (str(o.get("creato_il"))[:10] if o.get("creato_il") else None)
    fine = o.get("scadenza")
    pct_tempo = mesi_rimasti = giorni_rimasti = None
    try:
        d0, d1 = date.fromisoformat(str(inizio)[:10]), date.fromisoformat(str(fine)[:10])
        tot = max(1, (d1 - d0).days); pct_tempo = max(0.0, min(100.0, (oggi - d0).days / tot * 100))
        giorni_rimasti = (d1 - oggi).days; mesi_rimasti = max(giorni_rimasti / 30.44, 0)
    except Exception:
        pass

    # ---- centri: obiettivo di area
    target = o.get("target_centri")
    venduti = len({c["azienda_id"] for c in centri if c["esito"] == "vendita"})
    in_corso = len({c["azienda_id"] for c in centri if not c["esito"]})
    pct = (venduto / budget * 100) if budget else ((venduti / target * 100) if target else None)

    if pct is None:
        stato, giudizio = "senza misura", "Manca un budget o un numero di centri da raggiungere: inseriscili per misurare l'avanzamento."
    elif pct >= 100:
        stato, giudizio = "raggiunto", "Obiettivo raggiunto."
    elif pct_tempo is not None and giorni_rimasti is not None and giorni_rimasti < 0:
        stato, giudizio = "scaduto", f"Scadenza passata con il {pct:.0f}% raggiunto."
    elif pct_tempo is not None and pct + 10 < pct_tempo:
        stato, giudizio = "in ritardo", f"Raggiunto il {pct:.0f}% con il {pct_tempo:.0f}% del tempo trascorso."
    else:
        stato, giudizio = "in linea", f"Raggiunto il {pct:.0f}%" + (f" con il {pct_tempo:.0f}% del tempo trascorso." if pct_tempo is not None else ".")

    consigli = []
    if budget and scoperto and scoperto > 0:
        consigli.append(f"Le trattative aperte non bastano: mancano {scoperto:,.0f} € di nuove opportunità da creare.".replace(",", "."))
    if budget and mancante and mesi_rimasti:
        consigli.append(f"Per arrivare in tempo servono circa {mancante / max(mesi_rimasti, 1):,.0f} € di vendite al mese.".replace(",", "."))
    if target and venduti < target:
        manca_c = target - venduti
        consigli.append(f"Mancano {manca_c} centri su {target}; ne hai {in_corso} in trattativa"
                        + (": servono altri centri da contattare." if in_corso < manca_c else "."))
    fermi = [c for c in centri if not c["esito"] and not c["aperte"]]
    if fermi:
        consigli.append(f"{len(fermi)} centri senza una prossima attività: pianifica il passo successivo.")
    scad = sum(c["scadute"] for c in centri)
    if scad:
        consigli.append(f"{scad} attività scadute da recuperare.")

    imbuto = [{"fase": n, "n": sum(1 for c in centri if c["fase"] == n and not c["esito"])} for n, _, _ in FASI]
    imbuto = [{"fase": "Da contattare", "n": sum(1 for c in centri if c["fase"] == "Da contattare" and not c["esito"])}] + imbuto
    chiusi = {k: sum(1 for c in centri if c["esito"] == k) for k in ("vendita", "rifiuto", "scelto altro", "sospesa")}
    centri.sort(key=lambda c: (c["esito"] is not None, -c["probabilita"], c["azienda"] or ""))
    return {
        "obiettivo_id": oid, "titolo": o.get("titolo"), "tipo": o.get("tipo"), "inizio": inizio, "scadenza": fine,
        "budget": budget or None, "venduto": venduto, "aperto": aperto, "mancante": mancante, "scoperto": scoperto,
        "previsione": round(previsione), "previsto_aperto": round(previsto_aperto),
        "percentuale": round(pct, 1) if pct is not None else None, "percentuale_tempo": round(pct_tempo, 1) if pct_tempo is not None else None,
        "giorni_rimasti": giorni_rimasti, "stato": stato, "giudizio": giudizio, "consigli": consigli,
        "target_centri": target, "centri_venduti": venduti, "centri_in_corso": in_corso,
        "attivita": {"fatte": sum(1 for a in att if a.get("stato") == "fatta"), "aperte": sum(1 for a in att if a.get("stato") == "da fare"),
                     "scadute": sum(1 for a in att if a.get("stato") == "da fare" and a.get("scaduta")),
                     "ultimi_30_giorni": sum(1 for a in att if a.get("stato") == "fatta" and a.get("completata_il")
                                             and (oggi - date.fromisoformat(str(a["completata_il"])[:10])).days <= 30)},
        "imbuto": imbuto, "chiusi": chiusi, "centri": centri, "n_iniziative": len(ini), "n_sotto": len(ids) - 1,
    }


def avanzamento_obiettivi():
    """Sintesi di tutti gli obiettivi principali."""
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM obiettivi WHERE padre_id IS NULL ORDER BY scadenza NULLS LAST, id").fetchall()]
    out = []
    for i in ids:
        a = avanzamento_obiettivo(str(i))
        out.append({k: a[k] for k in ("obiettivo_id", "titolo", "budget", "venduto", "aperto", "mancante", "scoperto", "previsione",
                                      "percentuale", "percentuale_tempo", "stato", "giudizio", "consigli", "scadenza",
                                      "target_centri", "centri_venduti", "centri_in_corso")})
    return out


GENERI = ("marketing", "commerciale")
# nomi usati prima: restano accettati e vengono tradotti
ALIAS_GENERE = {"campagna": "marketing", "challenge": "marketing", "opportunita": "commerciale", "opportunità": "commerciale",
                "sales": "commerciale", "vendita": "commerciale", "commerciali": "commerciale"}
NOME_GENERE = {"marketing": "iniziativa di marketing", "commerciale": "iniziativa commerciale"}


def _genere(g):
    g = (g or "commerciale").strip().lower()
    return ALIAS_GENERE.get(g, g)


def crea_campagna(titolo, prodotto=None, obiettivo=None, storia=None, target=None, data_inizio=None,
                  data_fine=None, divisione=None, valore_eur=None, genere="marketing", azienda=None):
    """Campagna: contenitore di attività su più centri e persone, con target e storia da raccontare.
    target: {"natura": "pubblico", "dimensione": "grande", "regioni": [...], "province": [...],
             "tipi": [...], "professionalita": [...]}"""
    genere = _genere(genere)
    if genere not in GENERI:
        raise CRMError("Tipo di iniziativa: marketing o commerciale.")
    with connect() as conn:
        pr = risolvi_prodotto(conn, prodotto) if prodotto else None
        if not divisione:
            divisione = conn.execute("SELECT divisione FROM prodotti WHERE id=%s", (pr,)).fetchone()["divisione"] if pr else "Altro"
        ob = risolvi_obiettivo(conn, obiettivo) if obiettivo else None
        az = (int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda, crea_se_manca=True)) if azienda else None
        target = dict(target or {})
        if ob and not target.get("regioni") and not target.get("province"):
            o = conn.execute("SELECT regioni, province FROM obiettivi WHERE id=%s", (ob,)).fetchone()
            if o["regioni"]:
                target["regioni"] = o["regioni"]
            if o["province"]:
                target["province"] = o["province"]
        r = conn.execute(
            """INSERT INTO trattative (titolo, genere, azienda_id, divisione, fase, prodotto_id, obiettivo_id, storia, target,
                   data_inizio, chiusura_prevista, valore_eur, embedding)
               VALUES (%s,%s,%s,%s,'primo contatto',%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (titolo, genere, az, divisione, pr, ob, storia, _json.dumps(target or {}), data_inizio, data_fine, valore_eur,
             _vec(f"{titolo}. {storia or ''}"))).fetchone()
        return _clean(conn.execute("SELECT * FROM v_iniziative WHERE id=%s", (r["id"],)).fetchone())


def registra_esito(iniziativa, azienda, esito, concorrente=None, note=None, data=None):
    """Chiude il ramo di un centro: vendita, rifiuto, scelto altro (concorrente), sospesa."""
    if esito not in ESITI:
        raise CRMError("Esito non valido: usa " + ", ".join(ESITI))
    with connect() as conn:
        tid = risolvi_trattativa(conn, iniziativa)
        az = int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)
        r = conn.execute(
            """INSERT INTO esiti_centro (trattativa_id, azienda_id, esito, concorrente, note, data)
               VALUES (%s,%s,%s,%s,%s,coalesce(%s::date,current_date))
               ON CONFLICT (trattativa_id, azienda_id) DO UPDATE SET esito=EXCLUDED.esito,
                 concorrente=EXCLUDED.concorrente, note=EXCLUDED.note, data=EXCLUDED.data RETURNING *""",
            (tid, az, esito, concorrente, note, data)).fetchone()
        t = conn.execute("SELECT genere, azienda_id FROM trattative WHERE id=%s", (tid,)).fetchone()
        if t["azienda_id"] == az or (t["azienda_id"] is None and t["genere"] == "commerciale"):
            fase = {"vendita": "vinta", "rifiuto": "persa", "scelto altro": "persa", "sospesa": "sospesa"}[esito]
            conn.execute("UPDATE trattative SET esito=%s, concorrente=%s, fase=%s, aggiornata_il=now() WHERE id=%s",
                         (esito, concorrente, fase, tid))
        return _clean(r)


def candidati_target(conn, tid, limite=200):
    """Persone che corrispondono al target della campagna e non sono ancora coinvolte."""
    t = conn.execute("SELECT target FROM trattative WHERE id=%s", (tid,)).fetchone()
    tg = (t or {}).get("target") or {}
    w, p = ["c.id NOT IN (SELECT contatto_id FROM attivita WHERE trattativa_id=%s AND contatto_id IS NOT NULL)"], [tid]
    if tg.get("natura"):
        w.append("a.natura=%s"); p.append(tg["natura"])
    if tg.get("dimensione"):
        w.append("a.dimensione=%s"); p.append(tg["dimensione"])
    if tg.get("regioni"):
        w.append("a.regione_eff = ANY(%s)"); p.append(list(tg["regioni"]))
    if tg.get("province"):
        w.append("upper(a.provincia) = ANY(%s)"); p.append([x.upper() for x in tg["province"]])
    if tg.get("tipi"):
        w.append("a.tipo = ANY(%s)"); p.append(list(tg["tipi"]))
    if tg.get("professionalita"):
        w.append("(" + " OR ".join(["c.professionalita ILIKE '%%'||%s||'%%' OR c.ruolo ILIKE '%%'||%s||'%%'"] * len(tg["professionalita"])) + ")")
        for x in tg["professionalita"]:
            p += [x, x]
    if len(w) == 1:
        return []   # nessun target definito: nessun suggerimento
    return _rows(conn.execute(
        f"""SELECT c.id, trim(c.nome||' '||coalesce(c.cognome,'')) nome, c.ruolo, c.professionalita,
                   c.conosciuto_personalmente, c.email, c.cellulare, a.id azienda_id, a.nome azienda,
                   upper(a.provincia) provincia, a.regione_eff regione,
                   s.n_contatti, s.ultimo_contatto, s.n_aperte
            FROM contatti c JOIN v_aziende a ON a.id=c.azienda_id
            LEFT JOIN v_storico_contatti s ON s.contatto_id=c.id WHERE {' AND '.join(w)}
            ORDER BY c.conosciuto_personalmente DESC, a.nome, c.cognome LIMIT %s""", p + [limite]))


def persone_da_contattare(iniziativa=None, provincia=None, solo_conosciuti=False, limite=300, regione=None):
    """Chi contattare e perché: le attività da fare con una persona, con il motivo scritto nell'attività."""
    with connect() as conn:
        w, p = ["v.stato='da fare'", "v.contatto_id IS NOT NULL"], []
        if iniziativa:
            w.append("v.trattativa_id=%s"); p.append(risolvi_trattativa(conn, iniziativa))
        fw, fp = filtro_luoghi(conn, regione, provincia, "v.provincia", "v.regione"); w += fw; p += fp
        if solo_conosciuti:
            w.append("v.conosciuto")
        return _rows(conn.execute(
            f"""SELECT v.id attivita_id, v.codice_standard, v.standard, v.descrizione AS perche, v.tipo, v.scadenza,
                       v.scaduta, v.priorita, v.contatto_id, v.contatto, v.ruolo, v.professionalita, v.conosciuto,
                       v.azienda_id, v.azienda, v.provincia, v.trattativa_id, v.trattativa, t.genere,
                       c.email, c.cellulare, c.telefono, s.n_contatti, s.ultimo_contatto, s.n_aperte,
                       (SELECT count(*) FROM attivita x WHERE x.contatto_id=v.contatto_id AND x.stato='da fare'
                          AND x.trattativa_id IS DISTINCT FROM v.trattativa_id) AS aperte_altrove
                FROM v_attivita v LEFT JOIN trattative t ON t.id=v.trattativa_id
                LEFT JOIN contatti c ON c.id=v.contatto_id
                LEFT JOIN v_storico_contatti s ON s.contatto_id=v.contatto_id
                WHERE {' AND '.join(w)} ORDER BY v.scadenza NULLS LAST LIMIT %s""", p + [limite]))


def grafo(obiettivo=None, iniziativa=None, solo_aperte=False):
    """Struttura a corsie: obiettivi → contenitori → centri → attività in sequenza → esito."""
    with connect() as conn:
        w, p = ["true"], []
        if iniziativa:
            w.append("t.id=%s"); p.append(risolvi_trattativa(conn, iniziativa))
        elif obiettivo:
            w.append("t.obiettivo_id=%s"); p.append(risolvi_obiettivo(conn, obiettivo))
        if solo_aperte:
            w.append("coalesce(t.fase,'') NOT IN ('vinta','persa')")
        conts = _rows(conn.execute(
            f"""SELECT t.id, t.titolo, t.genere, t.fase, t.esito, t.concorrente, t.obiettivo_id, t.obiettivo,
                       t.prodotto, t.divisione, t.valore_eur, t.azienda_id
                FROM v_iniziative t WHERE {' AND '.join(w)} ORDER BY t.obiettivo_id NULLS LAST, t.genere, t.titolo""", p))
        ids = [c["id"] for c in conts] or [0]
        att = _rows(conn.execute(
            """SELECT id, trattativa_id, azienda_id, azienda, provincia, contatto_id, contatto, codice_standard,
                      standard, descrizione, stato, scaduta, scadenza, precedente_id, esito
               FROM v_attivita WHERE trattativa_id = ANY(%s)
               ORDER BY coalesce(scadenza, creata_il), id""", (ids,)))
        esiti = _rows(conn.execute(
            """SELECT e.*, a.nome azienda FROM esiti_centro e JOIN aziende a ON a.id=e.azienda_id
               WHERE trattativa_id = ANY(%s)""", (ids,)))
        nomi_az = {r["id"]: r["nome"] for r in conn.execute(
            "SELECT id, nome FROM aziende WHERE id = ANY(%s)", ([c.get("azienda_id") for c in conts if c.get("azienda_id")] or [0],))}
        obiettivi = {r["id"]: _clean(r) for r in conn.execute("SELECT * FROM obiettivi")}
    per_cont = {}
    for a in att:
        per_cont.setdefault(a["trattativa_id"], {}).setdefault(a.get("azienda_id"), []).append(a)
    es = {(e["trattativa_id"], e.get("azienda_id")): e for e in esiti}
    out = {}
    for c in conts:
        righe = per_cont.get(c["id"], {})
        if c.get("azienda_id") and c["azienda_id"] not in righe:
            righe[c["azienda_id"]] = []
        corsie = []
        for az_id, lista in righe.items():
            nome = (lista[0]["azienda"] if lista else nomi_az.get(az_id)) or "Senza centro"
            e = es.get((c["id"], az_id))
            if not e and c.get("esito") and (c.get("azienda_id") == az_id or (not c.get("azienda_id") and c["genere"] == "commerciale")):
                e = {"esito": c["esito"], "concorrente": c.get("concorrente")}
            corsie.append({"azienda_id": az_id, "azienda": nome, "provincia": lista[0].get("provincia") if lista else None,
                           "attivita": lista, "esito": e})
        corsie.sort(key=lambda x: (x["esito"] is not None, x["azienda"] or ""))
        c["corsie"] = corsie
        out.setdefault(c.get("obiettivo_id"), []).append(c)
    return [{"obiettivo": obiettivi.get(k) if k else None, "contenitori": v} for k, v in out.items()]


# ---------- storico, avvisi "già contattato", allerte ----------

def storico_contatto(conn, cid, escludi=None):
    return _rows(conn.execute(
        """SELECT v.id, v.codice_standard, v.standard, v.descrizione, v.stato, v.scadenza, v.completata_il, v.esito,
                  v.trattativa_id, v.trattativa, t.genere
           FROM v_attivita v LEFT JOIN trattative t ON t.id=v.trattativa_id
           WHERE v.contatto_id=%s AND v.id IS DISTINCT FROM %s
           ORDER BY coalesce(v.completata_il, v.scadenza, v.creata_il) DESC""", (cid, escludi)))


def avvisi_contatto(conn, cid, trattativa_id=None, escludi=None):
    """Messaggi di attenzione: la persona è già stata contattata o ha attività aperte altrove."""
    st = storico_contatto(conn, cid, escludi)
    out = []
    fatte = [a for a in st if a["stato"] == "fatta"]
    if fatte:
        u = fatte[0]
        q = (u.get("completata_il") or u.get("scadenza") or "")[:10]
        quando = f"{q[8:10]}/{q[5:7]}/{q[:4]}" if len(q) == 10 else q
        dove = f" — {u['trattativa']}" if u.get("trattativa") else ""
        out.append(f"Già contattata {len(fatte)} volt{'a' if len(fatte) == 1 else 'e'}; l'ultima il {quando} "
                   f"({u.get('codice_standard') or ''} {u.get('standard') or u['descrizione']}{dove}).")
    aperte = [a for a in st if a["stato"] == "da fare"]
    stessa = [a for a in aperte if trattativa_id and a.get("trattativa_id") == trattativa_id]
    altrove = [a for a in aperte if a not in stessa]
    if altrove:
        dove = sorted({a.get("trattativa") or "attività fuori da iniziative" for a in altrove})
        out.append(f"Ha già {len(altrove)} attività apert{'a' if len(altrove) == 1 else 'e'} in: " + "; ".join(dove) + ".")
    if stessa:
        out.append(f"In questa stessa iniziativa ha già {len(stessa)} attività apert{'a' if len(stessa) == 1 else 'e'}.")
    return out


def imposta_allerta(data, messaggio, tipo="sollecito", contatto=None, azienda=None, iniziativa=None,
                    attivita_id=None):
    """Allerta di sollecito, riattivazione o promemoria per una data."""
    if tipo not in ("sollecito", "riattivazione", "promemoria"):
        raise CRMError("Tipo allerta: sollecito, riattivazione o promemoria.")
    with connect() as conn:
        ct = (int(contatto) if str(contatto).isdigit() else risolvi_contatto(conn, contatto)) if contatto else None
        az = (int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)) if azienda else None
        tr = risolvi_trattativa(conn, iniziativa) if iniziativa else None
        if attivita_id and not (ct or az or tr):
            a = conn.execute("SELECT contatto_id, azienda_id, trattativa_id FROM attivita WHERE id=%s", (attivita_id,)).fetchone()
            if a:
                ct, az, tr = a["contatto_id"], a["azienda_id"], a["trattativa_id"]
        if ct and not az:
            az = conn.execute("SELECT azienda_id FROM contatti WHERE id=%s", (ct,)).fetchone()["azienda_id"]
        r = conn.execute(
            """INSERT INTO allerte (tipo, data, messaggio, contatto_id, azienda_id, trattativa_id, attivita_id)
               VALUES (%s,%s::date,%s,%s,%s,%s,%s) RETURNING id""",
            (tipo, data, messaggio, ct, az, tr, attivita_id)).fetchone()
        return _clean(conn.execute(Q_ALLERTE + " WHERE al.id=%s", (r["id"],)).fetchone())


Q_ALLERTE = """SELECT al.*, (al.data < current_date) AS scaduta, (al.data = current_date) AS oggi,
                      trim(coalesce(c.nome,'')||' '||coalesce(c.cognome,'')) AS contatto, c.cellulare, c.email,
                      c.conosciuto_personalmente, a.nome AS azienda, upper(a.provincia) AS provincia,
                      t.titolo AS trattativa, t.genere
               FROM allerte al LEFT JOIN contatti c ON c.id=al.contatto_id
               LEFT JOIN aziende a ON a.id=al.azienda_id LEFT JOIN trattative t ON t.id=al.trattativa_id"""


def elenco_allerte(stato="attiva", entro_giorni=None, contatto=None, azienda=None, iniziativa=None):
    with connect() as conn:
        w, p = ["true"], []
        if stato:
            w.append("al.stato=%s"); p.append(stato)
        if entro_giorni is not None:
            w.append("al.data <= current_date + %s::int"); p.append(int(entro_giorni))
        if contatto:
            w.append("al.contatto_id=%s"); p.append(int(contatto) if str(contatto).isdigit() else risolvi_contatto(conn, contatto))
        if azienda:
            w.append("al.azienda_id=%s"); p.append(int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda))
        if iniziativa:
            w.append("al.trattativa_id=%s"); p.append(risolvi_trattativa(conn, iniziativa))
        return _rows(conn.execute(Q_ALLERTE + f" WHERE {' AND '.join(w)} ORDER BY al.data, al.id", p))


def aggiorna_allerta(allerta_id, stato=None, nuova_data=None):
    with connect() as conn:
        if nuova_data:
            conn.execute("UPDATE allerte SET data=%s::date, stato='attiva' WHERE id=%s", (nuova_data, allerta_id))
        if stato:
            conn.execute("""UPDATE allerte SET stato=%s, chiusa_il=CASE WHEN %s<>'attiva' THEN now() END
                            WHERE id=%s""", (stato, stato, allerta_id))
        r = conn.execute(Q_ALLERTE + " WHERE al.id=%s", (allerta_id,)).fetchone()
        if not r:
            raise CRMError(f"Allerta {allerta_id} non trovata.")
        return _clean(r)


def da_riattivare(giorni=90, limite=200):
    """Persone contattate in passato ma ferme da più di N giorni, senza attività aperte né allerte attive."""
    with connect() as conn:
        return _rows(conn.execute(
            """SELECT c.id, trim(c.nome||' '||coalesce(c.cognome,'')) nome, c.ruolo, c.conosciuto_personalmente,
                      c.cellulare, c.email, a.id azienda_id, a.nome azienda, upper(a.provincia) provincia,
                      s.n_contatti, s.ultimo_contatto, (current_date - s.ultimo_contatto::date) giorni_fermo
               FROM v_storico_contatti s JOIN contatti c ON c.id=s.contatto_id LEFT JOIN aziende a ON a.id=c.azienda_id
               WHERE s.n_contatti > 0 AND s.n_aperte = 0
                 AND s.ultimo_contatto < now() - make_interval(days => %s)
                 AND NOT EXISTS (SELECT 1 FROM allerte al WHERE al.contatto_id=c.id AND al.stato='attiva')
               ORDER BY c.conosciuto_personalmente DESC, s.ultimo_contatto LIMIT %s""", (giorni, limite)))


# ---------- modifica diretta di centri e contatti (tabelle) ----------

MODIFICABILI = {
    "utenti": {"cognome", "email", "ruolo", "attivo"},
    "prodotti": {"nome", "divisione", "produttore", "descrizione", "attivo", "tipologie_clienti", "descrizione_clienti", "prezzo_listino", "costo", "unita", "aliquota_iva"},
    "obiettivi": {"titolo", "descrizione", "scadenza", "valore_eur", "tipo", "ambito", "stato", "regioni", "province",
                  "target_centri", "data_inizio"},
    "aziende": {"nome", "tipo", "natura", "dimensione", "citta", "provincia", "regione", "indirizzo", "cap",
                "telefono", "email", "sito", "ats", "relazione", "strategicita", "note"},
    "contatti": {"nome", "cognome", "ruolo", "professionalita", "email", "email_privata", "cellulare", "telefono",
                 "telefono_privato", "linkedin", "esperienze", "note", "conosciuto_personalmente", "azienda_id"},
}


def modifica(tabella, oid, campi):
    ammessi = MODIFICABILI[tabella]
    campi = {k: (v if v != "" else None) for k, v in campi.items() if k in ammessi}
    for k in ("tipologie_clienti", "regioni", "province"):
        if k in campi and isinstance(campi[k], str):
            campi[k] = [x.strip() for x in campi[k].split(",") if x.strip()]
        elif k in campi and campi[k] is None:
            campi[k] = []
    if "provincia" in campi and campi["provincia"]:
        campi["provincia"] = campi["provincia"].upper()
    if not campi:
        raise CRMError("Nessun campo modificabile.")
    with connect() as conn:
        if tabella == "aziende" and campi.get("provincia"):
            r = conn.execute("SELECT regione FROM province WHERE sigla=%s", (campi["provincia"],)).fetchone()
            if r:
                campi["regione"] = r["regione"]
        sets = ", ".join(f"{k}=%s" for k in campi)
        conn.execute(f"UPDATE {tabella} SET {sets} WHERE id=%s", list(campi.values()) + [oid])
        return _clean(conn.execute(f"SELECT * FROM {tabella} WHERE id=%s", (oid,)).fetchone())


# ---------- diario per giorno (voci + attività svolte) ----------

def giornate(dal=None, al=None, azienda=None, provincia=None, regione=None, q=None, limite_giorni=60):
    with connect() as conn:
        voci = cerca_note(q, azienda, provincia, regione, dal, al, "diario", 500) if True else []
        w, p = ["v.stato='fatta'", "v.completata_il IS NOT NULL"], []
        if dal:
            w.append("v.completata_il::date >= %s::date"); p.append(dal)
        if al:
            w.append("v.completata_il::date <= %s::date"); p.append(al)
        if azienda:
            w.append("v.azienda_id=%s"); p.append(int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda))
        fw, fp = filtro_luoghi(conn, regione, provincia, "v.provincia", "v.regione"); w += fw; p += fp
        fatte = [] if q else _rows(conn.execute(
            f"""SELECT v.id, v.completata_il::date AS giorno, v.codice_standard, v.standard, v.descrizione, v.tipo, v.esito,
                       a.resoconto, v.azienda_id, v.azienda, v.provincia, v.contatto_id, v.contatto, v.trattativa_id, v.trattativa
                FROM v_attivita v JOIN attivita a ON a.id=v.id WHERE {' AND '.join(w)} ORDER BY v.completata_il DESC LIMIT 500""", p))
    giorni = {}
    for v in voci:
        giorni.setdefault(v["giorno"], {"giorno": v["giorno"], "voci": [], "svolte": []})["voci"].append(v)
    for a in fatte:
        giorni.setdefault(a["giorno"], {"giorno": a["giorno"], "voci": [], "svolte": []})["svolte"].append(a)
    return sorted(giorni.values(), key=lambda g: g["giorno"], reverse=True)[:limite_giorni]


def da_compiere(azienda=None, provincia=None, regione=None, q=None, giorni=60):
    """Attività in programma (da fare): scadute, di oggi, dei prossimi giorni e senza data, con persona e recapiti."""
    with connect() as conn:
        w, p = ["v.stato='da fare'", "(v.scadenza IS NULL OR v.scadenza::date <= current_date + %s::int)"], [int(giorni)]
        if azienda:
            w.append("v.azienda_id=%s"); p.append(int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda))
        fw, fp = filtro_luoghi(conn, regione, provincia, "v.provincia", "v.regione"); w += fw; p += fp
        if q:
            w.append("(v.descrizione ILIKE '%%'||%s||'%%' OR v.standard ILIKE '%%'||%s||'%%' OR v.contatto ILIKE '%%'||%s||'%%' OR v.azienda ILIKE '%%'||%s||'%%')")
            p += [q] * 4
        return _rows(conn.execute(
            f"""SELECT v.id, v.scadenza, v.scadenza::date AS giorno, (v.scadenza::date < current_date) AS scaduta,
                       v.codice_standard, v.standard, v.ordine_standard, v.descrizione, v.tipo, v.priorita,
                       v.azienda_id, v.azienda, v.provincia, v.contatto_id, v.contatto, v.ruolo, v.conosciuto,
                       v.trattativa_id, v.trattativa, t.genere, a.pianificata_il, a.rimandi, a.preparazione IS NOT NULL AS preparata,
                       c.cellulare, c.telefono, c.email,
                       (SELECT ca.codice FROM catalogo_attivita ca WHERE ca.ordine > coalesce(v.ordine_standard,0) ORDER BY ca.ordine LIMIT 1) AS passo_successivo_codice
                FROM v_attivita v JOIN attivita a ON a.id=v.id LEFT JOIN contatti c ON c.id=v.contatto_id
                LEFT JOIN trattative t ON t.id=v.trattativa_id
                WHERE {' AND '.join(w)} ORDER BY v.scadenza NULLS LAST, v.id""", p))


# ---------- mappa mentale ----------

def _nodo(tipo, id_, label, sub=None, extra=None):
    d = {"tipo": tipo, "id": id_, "label": label, "sub": sub}
    if extra:
        d.update(extra)
    return d


def mappa_mentale(tipo=None, oid=None):
    """Mappa mentale centrata su un oggetto: rami con un'etichetta che dice il legame."""
    with connect() as conn:
        R = lambda sql, *a: _rows(conn.execute(sql, a))
        O = lambda sql, *a: _clean(conn.execute(sql, a).fetchone())
        dt = lambda x: (x or "")[:10] and f"{x[8:10]}/{x[5:7]}" if x else ""
        rami = []
        if not tipo:
            centro = _nodo("radice", 0, "SomaMed", "obiettivi e iniziative")
            for o in R("SELECT * FROM v_obiettivi WHERE padre_id IS NULL ORDER BY id"):
                figli = [{"label": "si articola nel sotto-obiettivo" + (f" · {', '.join(f2['province'] or f2['regioni'])}" if (f2.get('province') or f2.get('regioni')) else ""),
                          "nodo": _nodo("obiettivo", f2["id"], f2["titolo"], f"{f2.get('tipo')} · {int(f2.get('valore_eur') or 0):,} €".replace(",", "."))}
                         for f2 in R("SELECT * FROM obiettivi WHERE padre_id=%s ORDER BY id", o["id"])]
                figli += [{"label": "si persegue con l'" + NOME_GENERE.get(t['genere'], 'iniziativa'), "nodo": _nodo("trattativa", t["id"], t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa"))}
                          for t in R("SELECT id, titolo, genere FROM trattative WHERE obiettivo_id=%s ORDER BY id", o["id"])]
                rami.append({"label": f"obiettivo di {o.get('tipo','area')}" + (f" · {o['ambito']}" if o.get("ambito") else ""),
                             "nodo": _nodo("obiettivo", o["id"], o["titolo"], f"{o['n_vendite']} vendite"), "figli": figli})
            senza = R("SELECT id, titolo, genere FROM trattative WHERE obiettivo_id IS NULL ORDER BY id")
            for t in senza:
                rami.append({"label": NOME_GENERE.get(t['genere'], 'iniziativa') + " senza obiettivo", "nodo": _nodo("trattativa", t["id"], t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa")), "figli": []})
            return {"centro": centro, "rami": rami}
        if tipo == "obiettivo":
            o = O("SELECT * FROM v_obiettivi WHERE id=%s", oid)
            centro = _nodo("obiettivo", oid, o["titolo"], f"obiettivo di {o.get('tipo','area')}")
            if o.get("padre_id"):
                rami.append({"label": "è un sotto-obiettivo di", "nodo": _nodo("obiettivo", o["padre_id"], o["padre"]), "figli": []})
            for f2 in R("SELECT * FROM obiettivi WHERE padre_id=%s ORDER BY id", oid):
                ff = [{"label": "si persegue con l'" + NOME_GENERE.get(t['genere'], 'iniziativa'), "nodo": _nodo("trattativa", t["id"], t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa"))}
                      for t in R("SELECT id, titolo, genere FROM trattative WHERE obiettivo_id=%s", f2["id"])]
                rami.append({"label": "si articola nel sotto-obiettivo" + (f" · {', '.join(f2['province'] or f2['regioni'])}" if (f2.get('province') or f2.get('regioni')) else ""),
                             "nodo": _nodo("obiettivo", f2["id"], f2["titolo"], f"budget {int(f2.get('valore_eur') or 0):,} €".replace(",", ".")), "figli": ff})
            for t in R("SELECT id, titolo, genere FROM trattative WHERE obiettivo_id=%s ORDER BY id", oid):
                figli = _centri_iniziativa(R, t["id"])
                rami.append({"label": "si persegue con l'" + NOME_GENERE.get(t['genere'], 'iniziativa'), "nodo": _nodo("trattativa", t["id"], t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa")), "figli": figli})
            return {"centro": centro, "rami": rami}
        if tipo == "trattativa":
            t = O("SELECT * FROM v_iniziative WHERE id=%s", oid)
            centro = _nodo("trattativa", oid, t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa"))
            if t.get("obiettivo_id"):
                rami.append({"label": "contribuisce all'obiettivo", "nodo": _nodo("obiettivo", t["obiettivo_id"], t["obiettivo"]), "figli": []})
            if t.get("prodotto_id"):
                rami.append({"label": "propone il prodotto", "nodo": _nodo("prodotto", t["prodotto_id"], t["prodotto"]), "figli": []})
            for f in _centri_iniziativa(R, oid):
                persone = R("""SELECT DISTINCT ON (contatto_id) contatto_id, contatto, codice_standard, standard, stato, scadenza
                               FROM v_attivita WHERE trattativa_id=%s AND azienda_id=%s AND contatto_id IS NOT NULL
                               ORDER BY contatto_id, coalesce(scadenza, creata_il) DESC""", oid, f["nodo"]["id"])
                f["figli"] = [{"label": f"{'ha fatto' if p['stato']=='fatta' else 'deve fare'} {p.get('standard') or 'attività'}"
                                        + (f" · {dt(p.get('scadenza'))}" if p.get("scadenza") else ""),
                               "nodo": _nodo("contatto", p["contatto_id"], p["contatto"])} for p in persone]
                rami.append(f)
            return {"centro": centro, "rami": rami}
        if tipo == "azienda":
            a = O("SELECT * FROM v_aziende WHERE id=%s", oid)
            centro = _nodo("azienda", oid, a["nome"], " · ".join(x for x in (a.get("tipo"), a.get("provincia")) if x))
            for c in R("""SELECT c.id, trim(c.nome||' '||coalesce(c.cognome,'')) nome, c.ruolo, c.conosciuto_personalmente
                          FROM contatti c WHERE azienda_id=%s ORDER BY c.conosciuto_personalmente DESC, c.cognome""", oid):
                amici = R("""SELECT r.tipo, c2.id, trim(c2.nome||' '||coalesce(c2.cognome,'')) nome, a2.nome azienda
                             FROM relazioni_contatti r JOIN contatti c2 ON c2.id = CASE WHEN r.contatto_a=%s THEN r.contatto_b ELSE r.contatto_a END
                             LEFT JOIN aziende a2 ON a2.id=c2.azienda_id WHERE %s IN (r.contatto_a, r.contatto_b)""", c["id"], c["id"])
                rami.append({"label": ("lavora qui · lo conosci" if c["conosciuto_personalmente"] else "lavora qui") + (f" · {c['ruolo']}" if c.get("ruolo") else ""),
                             "nodo": _nodo("contatto", c["id"], c["nome"], c.get("ruolo"), {"conosciuto": c["conosciuto_personalmente"]}),
                             "figli": [{"label": f"{x['tipo']} di", "nodo": _nodo("contatto", x["id"], x["nome"], x.get("azienda"))} for x in amici]})
            for t in R("""SELECT DISTINCT t.id, t.titolo, t.genere, e.esito, e.concorrente FROM trattative t
                          LEFT JOIN esiti_centro e ON e.trattativa_id=t.id AND e.azienda_id=%s
                          WHERE t.azienda_id=%s OR t.id IN (SELECT trattativa_id FROM attivita WHERE azienda_id=%s)""", oid, oid, oid):
                esito = t.get("esito")
                rami.append({"label": "coinvolto nell'" + NOME_GENERE.get(t['genere'], 'iniziativa') + (f" → {esito}" + (f" ({t['concorrente']})" if t.get("concorrente") else "") if esito else " · in corso"),
                             "nodo": _nodo("trattativa", t["id"], t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa"), {"esito": esito}), "figli": []})
            return {"centro": centro, "rami": rami}
        if tipo == "contatto":
            c = O("""SELECT c.*, a.nome azienda FROM contatti c LEFT JOIN aziende a ON a.id=c.azienda_id WHERE c.id=%s""", oid)
            centro = _nodo("contatto", oid, f"{c['nome']} {c.get('cognome') or ''}".strip(), c.get("ruolo"),
                           {"conosciuto": c.get("conosciuto_personalmente")})
            if c.get("azienda_id"):
                rami.append({"label": "lavora in", "nodo": _nodo("azienda", c["azienda_id"], c["azienda"]), "figli": []})
            for x in relazioni_di(conn, oid):
                rami.append({"label": f"{x['tipo']} di" + (f" · {x['note']}" if x.get("note") else ""),
                             "nodo": _nodo("contatto", x["id"], x["nome"], x.get("azienda"), {"conosciuto": x.get("conosciuto_personalmente")}), "figli": []})
            per_ini = {}
            for a in R("""SELECT id, codice_standard, standard, descrizione, stato, scadenza, completata_il, trattativa_id, trattativa
                          FROM v_attivita WHERE contatto_id=%s ORDER BY coalesce(scadenza, creata_il)""", oid):
                per_ini.setdefault((a.get("trattativa_id"), a.get("trattativa")), []).append(a)
            for (tid, tit), atts in per_ini.items():
                figli = [{"label": f"{'fatto' if a['stato']=='fatta' else 'da fare'} · {dt(a.get('completata_il') or a.get('scadenza'))}",
                          "nodo": _nodo("attivita", a["id"], a.get("standard") or a["descrizione"], a["descrizione"], {"stato": a["stato"]})} for a in atts]
                if tid:
                    rami.append({"label": "contattata nella iniziativa", "nodo": _nodo("trattativa", tid, tit), "figli": figli})
                else:
                    rami.extend({"label": f["label"], "nodo": f["nodo"], "figli": []} for f in figli)
            return {"centro": centro, "rami": rami}
        if tipo == "prodotto":
            p = O("SELECT * FROM prodotti WHERE id=%s", oid)
            centro = _nodo("prodotto", oid, p["nome"], p.get("divisione"))
            for t in R("SELECT id, titolo, genere FROM trattative WHERE prodotto_id=%s", oid):
                rami.append({"label": "proposto nell'" + NOME_GENERE.get(t['genere'], 'iniziativa'), "nodo": _nodo("trattativa", t["id"], t["titolo"], NOME_GENERE.get(t["genere"], "iniziativa")),
                             "figli": _centri_iniziativa(R, t["id"])})
            return {"centro": centro, "rami": rami}
        raise CRMError("Tipo non gestito nella mappa mentale.")


def _centri_iniziativa(R, tid):
    righe = R("""SELECT a.id, a.nome, e.esito, e.concorrente FROM aziende a
                 LEFT JOIN esiti_centro e ON e.trattativa_id=%s AND e.azienda_id=a.id
                 WHERE a.id IN (SELECT azienda_id FROM attivita WHERE trattativa_id=%s)
                    OR a.id=(SELECT azienda_id FROM trattative WHERE id=%s)""", tid, tid, tid)
    return [{"label": "coinvolge" + (f" → {r['esito']}" + (f" ({r['concorrente']})" if r.get("concorrente") else "") if r.get("esito") else " · in corso"),
             "nodo": _nodo("azienda", r["id"], r["nome"], None, {"esito": r.get("esito")}), "figli": []} for r in righe]


# ---------- utenti ----------

def utenti(solo_attivi=False):
    with connect() as conn:
        return _rows(conn.execute(
            """SELECT u.*, (SELECT count(*) FROM attivita a WHERE a.responsabile=u.nome AND a.stato='da fare') aperte,
                      (SELECT count(*) FROM attivita a WHERE a.responsabile=u.nome AND a.stato='fatta') fatte
               FROM utenti u """ + ("WHERE attivo " if solo_attivi else "") + "ORDER BY attivo DESC, nome"))


def crea_utente(nome, cognome=None, email=None, ruolo=None):
    nome = (nome or "").strip()
    if not nome:
        raise CRMError("Scrivi il nome dell'utente.")
    with connect() as conn:
        r = conn.execute("""INSERT INTO utenti (nome, cognome, email, ruolo) VALUES (%s,%s,%s,%s)
                            ON CONFLICT (nome) DO UPDATE SET attivo=true, cognome=coalesce(EXCLUDED.cognome, utenti.cognome),
                              email=coalesce(EXCLUDED.email, utenti.email), ruolo=coalesce(EXCLUDED.ruolo, utenti.ruolo)
                            RETURNING *""", (nome, cognome or None, email or None, ruolo or None)).fetchone()
        return _clean(r)

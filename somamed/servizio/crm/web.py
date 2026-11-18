"""Servizio dati del CRM SomaMed: solo API (JSON). L'interfaccia è separata (cartella interfaccia/).

Avvio: bash avvia.sh  (oppure: python -m crm.web)

Resilienza:
- se il database non è ancora acceso, il servizio parte lo stesso e si collega appena risponde
  (gli aggiornamenti dello schema vengono applicati in quel momento);
- errori del CRM → 400 con messaggio leggibile; database spento → 503; nessun errore 500 muto;
- /api/salute dice in ogni momento se servizio, database e modello semantico funzionano.
"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from . import config, core, piano, dati, pianifica, offerte
from .embed import precarica

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crm.web")

_schema = {"pronto": False, "errore": None}
_schema_lock = threading.Lock()


def _assicura_schema():
    """Applica gli aggiornamenti dello schema una volta sola, appena il database risponde."""
    if _schema["pronto"]:
        return True
    with _schema_lock:
        if _schema["pronto"]:
            return True
        try:
            nuovi = core.migra()
            if nuovi:
                log.info("Database aggiornato: %s", ", ".join(nuovi))
            _schema.update(pronto=True, errore=None)
        except core.DatabaseNonRaggiungibile as e:
            _schema["errore"] = str(e)
        except Exception as e:   # aggiornamento fallito: resta annullato (transazione), lo si vede in /api/salute
            log.exception("aggiornamento dello schema non riuscito")
            _schema["errore"] = f"Aggiornamento del database non riuscito: {e}"
    return _schema["pronto"]


def _attendi_database():
    for tentativo in range(60):   # circa 2 minuti, poi riprova alla prima richiesta
        if _assicura_schema():
            return
        if tentativo == 0:
            log.warning("Database non ancora raggiungibile, riprovo...")
        time.sleep(2)


@asynccontextmanager
async def _vita(app):
    core.pool()
    threading.Thread(target=_attendi_database, name="attendi-db", daemon=True).start()
    precarica()
    yield
    core.chiudi_pool()


app = FastAPI(title="SomaMed CRM — servizio dati", lifespan=_vita)
app.add_middleware(GZipMiddleware, minimum_size=1024)
# L'interfaccia sta su un'altra porta (o su un altro server): le si permette di leggere i dati
app.add_middleware(CORSMiddleware, allow_origins=config.ORIGINI, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(core.CRMError)
async def _errore_crm(request: Request, e: core.CRMError):
    codice = 503 if isinstance(e, core.DatabaseNonRaggiungibile) else 400
    return JSONResponse({"detail": str(e)}, status_code=codice)


@app.middleware("http")
async def _chiave(request: Request, call_next):
    """Se in config.env c'è CRM_TOKEN, ogni richiesta ai dati deve portare la chiave."""
    p = request.url.path
    if config.TOKEN and p.startswith("/api/") and p != "/api/salute" and request.method != "OPTIONS":
        k = request.headers.get("x-crm-token") or request.query_params.get("token")
        if k != config.TOKEN:
            return JSONResponse({"detail": "Chiave di accesso mancante o errata (Strumenti → Dati e collegamento)."}, status_code=401)
    if p.startswith("/api/") and p != "/api/salute" and not _schema["pronto"]:
        await run_in_threadpool(_assicura_schema)
    return await call_next(request)


@app.get("/api/salute")
def api_salute():
    """Controllo di salute: servizio, database, schema, modello semantico."""
    from . import embed as _e
    out = {"servizio": "ok", "schema_aggiornato": _schema["pronto"],
           "modello_semantico": "hash (prova)" if _e._usa_hash() else ("pronto" if _e._model else "in caricamento")}
    try:
        out.update(core.salute())
    except core.CRMError as e:
        return JSONResponse({**out, "database": "non raggiungibile", "errore": str(e)}, status_code=503)
    if _schema["errore"]:
        out["errore"] = _schema["errore"]
    return out


@app.get("/api/stato")
def api_stato():
    try:
        return {"servizio": "ok", "chiave_richiesta": bool(config.TOKEN), **dati.stato()}
    except core.CRMError:
        raise
    except Exception as e:
        raise HTTPException(503, f"Database non raggiungibile: {e}")


@app.get("/api/esporta")
def api_esporta():
    from datetime import date
    return JSONResponse(dati.esporta(), headers={"Content-Disposition": f'attachment; filename="somamed-crm-{date.today()}.json"'})


class Svuota(BaseModel):
    cosa: str = "prova"
    conferma: str = ""
    centri: Optional[list[int]] = None


@app.post("/api/svuota")
def api_svuota(v: Svuota):
    return dati.svuota(v.cosa, v.conferma, v.centri)


@app.get("/")
def index():
    """Il servizio dati non contiene l'interfaccia: rimanda alla pagina servita a parte."""
    from fastapi.responses import RedirectResponse
    host = "127.0.0.1" if config.UI_HOST in ("0.0.0.0", "") else config.UI_HOST
    return RedirectResponse(f"http://{host}:{config.UI_PORT}/")


# Dimensioni di analisi: chiave -> (colonna id, colonna etichetta, tipo oggetto collegato)
DIMENSIONI = {
    "centro":          ("azienda_id", "azienda", "azienda"),
    "area":            ("area", "area", None),
    "professionalita": ("professionalita", "professionalita", None),
    "bu":              ("bu", "bu", None),
    "prodotto":        ("prodotto_id", "prodotto", "prodotto"),
    "standard":        ("codice_standard", "standard", None),
    "contatto":        ("contatto_id", "contatto", "contatto"),
    "regione":         ("regione", "regione", None),
    "provincia":       ("provincia", "provincia", None),
    "natura":          ("natura", "natura", None),
    "dimensione":      ("dimensione", "dimensione", None),
}
FILTRI = ["centro", "area", "professionalita", "bu", "prodotto", "standard", "contatto",
          "regione", "provincia", "natura", "dimensione"]


def _filtri(f: dict):
    q, p = [], []
    for dim, val in f.items():
        if val in (None, "") or dim not in DIMENSIONI:
            continue
        col = DIMENSIONI[dim][0]
        if val == "__nessuno__":
            q.append(f"{col} IS NULL")
        elif dim in ("regione", "provincia") and "," in str(val):
            q.append(f"{col}::text = ANY(%s)"); p.append([x.strip() for x in str(val).split(",") if x.strip()])
        else:
            q.append(f"{col}::text = %s")
            p.append(val)
    return q, p


def _stato(stato):
    return {"aperte": ["stato='da fare'"], "scadute": ["scaduta"],
            "fatte": ["stato='fatta'"]}.get(stato, [])


@app.get("/api/meta")
def meta():
    with core.connect() as conn:
        # tutti i conteggi in un solo giro verso il database (prima erano 8 query)
        k = conn.execute("""SELECT
                (SELECT count(*) FROM aziende) centri,
                (SELECT count(*) FROM contatti) contatti,
                (SELECT count(*) FROM prodotti) prodotti,
                (SELECT count(*) FROM trattative WHERE fase NOT IN ('vinta','persa')) trattative_aperte,
                (SELECT count(*) FROM attivita WHERE stato='da fare') attivita_aperte,
                (SELECT count(*) FROM attivita WHERE stato='da fare' AND scadenza < now()) scadute,
                (SELECT coalesce(sum(valore_eur),0) FROM trattative WHERE coalesce(fase,'') NOT IN ('vinta','persa')) pipeline_eur,
                (SELECT count(*) FROM allerte WHERE stato='attiva' AND data <= current_date) allerte_dovute""").fetchone()
        return {
            "conteggi": {**k, "pipeline_eur": float(k["pipeline_eur"])},
            "standard": core._rows(conn.execute("SELECT codice, nome, ordine FROM catalogo_attivita ORDER BY ordine")),
            "aziende": core._rows(conn.execute("SELECT id, nome, upper(provincia) provincia, regione_eff regione FROM v_aziende ORDER BY nome")),
            "province": core._rows(conn.execute("SELECT sigla, nome, regione FROM province ORDER BY nome")),
            "contatti": core._rows(conn.execute(
                """SELECT c.id, trim(c.nome||' '||coalesce(c.cognome,'')) nome, c.azienda_id
                   FROM contatti c ORDER BY 2""")),
            "prodotti": core._rows(conn.execute(
                "SELECT id, nome, divisione, prezzo_listino, costo, unita, aliquota_iva FROM prodotti ORDER BY nome")),
            "utenti": [r["nome"] for r in conn.execute("SELECT nome FROM utenti WHERE attivo ORDER BY nome").fetchall()],
            "trattative": core._rows(conn.execute(
                "SELECT id, titolo, azienda_id, contatto_id, genere FROM trattative WHERE coalesce(fase,'') NOT IN ('vinta','persa') ORDER BY genere, titolo")),
            "obiettivi": core._rows(conn.execute(
                """SELECT o.id, o.titolo, o.padre_id, o.regioni, o.province, p.titolo padre FROM obiettivi o
                   LEFT JOIN obiettivi p ON p.id=o.padre_id ORDER BY coalesce(o.padre_id, o.id), o.padre_id NULLS FIRST, o.id""")),
        }


@app.get("/api/pivot/{dim}")
def pivot(dim: str, request: Request, stato: str = "aperte"):
    if dim not in DIMENSIONI:
        raise HTTPException(404, "dimensione sconosciuta")
    idcol, labcol, tipo = DIMENSIONI[dim]
    f = {k: request.query_params.get(k) for k in FILTRI}
    f.pop(dim)
    w, p = _filtri(f)
    w += _stato(stato)
    order = "min(ordine_standard)" if dim == "standard" else "totale DESC, etichetta"
    sql = f"""SELECT {idcol}::text AS chiave, coalesce({labcol}, 'Non indicato') AS etichetta,
                     count(*) AS totale,
                     count(*) FILTER (WHERE stato='da fare') AS aperte,
                     count(*) FILTER (WHERE scaduta) AS scadute,
                     count(*) FILTER (WHERE stato='fatta') AS fatte
              FROM v_attivita {'WHERE ' + ' AND '.join(w) if w else ''}
              GROUP BY 1, 2 ORDER BY {order}"""
    with core.connect() as conn:
        return {"dimensione": dim, "tipo_oggetto": tipo, "righe": core._rows(conn.execute(sql, p))}


@app.get("/api/attivita")
def attivita(request: Request, stato: str = "aperte", limite: int = 300):
    w, p = _filtri({k: request.query_params.get(k) for k in FILTRI})
    w += _stato(stato)
    sql = f"""SELECT * FROM v_attivita {'WHERE ' + ' AND '.join(w) if w else ''}
              ORDER BY (stato='da fare') DESC, scadenza NULLS LAST LIMIT %s"""
    with core.connect() as conn:
        return core._rows(conn.execute(sql, p + [limite]))


def _catena(conn, aid):
    """Tutta la sequenza di cui fa parte un'attività, dalla prima all'ultima."""
    radice = conn.execute(
        """WITH RECURSIVE su AS (
               SELECT id, precedente_id, 0 d FROM attivita WHERE id=%s
               UNION ALL SELECT a.id, a.precedente_id, su.d+1 FROM attivita a JOIN su ON a.id=su.precedente_id
               WHERE su.d < 200)
           SELECT id FROM su ORDER BY d DESC LIMIT 1""", (aid,)).fetchone()["id"]
    return core._rows(conn.execute(
        """WITH RECURSIVE giu AS (
               SELECT id, 0 d FROM attivita WHERE id=%s
               UNION ALL SELECT a.id, giu.d+1 FROM attivita a JOIN giu ON a.precedente_id=giu.id
               WHERE giu.d < 200)
           SELECT v.*, giu.d passo FROM giu JOIN v_attivita v ON v.id=giu.id ORDER BY giu.d, v.id""",
        (radice,)))


def _sequenze(conn, where, params):
    """Le sequenze di attività legate a un oggetto, raggruppate."""
    teste = conn.execute(
        f"""SELECT DISTINCT ON (coalesce(trattativa_id, -id)) id FROM v_attivita
            WHERE {where} ORDER BY coalesce(trattativa_id, -id), id""", params).fetchall()
    viste, out = set(), []
    for t in teste:
        cat = _catena(conn, t["id"])
        chiave = tuple(a["id"] for a in cat)
        if chiave and chiave not in viste and not (set(chiave) & {i for k in viste for i in k}):
            viste.add(chiave)
            out.append(cat)
    return out


@app.get("/api/piano")
def piano_api(giorno: Optional[str] = None, ore: Optional[float] = None, inizio: Optional[str] = None,
              responsabile: Optional[str] = None):
    try:
        return piano.piano_giorno(giorno or None, ore, inizio or None, responsabile or None)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class Resoconto(BaseModel):
    come: str = "fatta"
    resoconto: Optional[str] = None
    processo: Optional[str] = None
    prossimo_codice: Optional[str] = None
    prossimo_giorni: int = 7
    prossimo_descrizione: Optional[str] = None
    giorni: Optional[int] = None
    data: Optional[str] = None
    prossima_data: Optional[str] = None


@app.post("/api/piano/{aid}/resoconto")
def piano_resoconto(aid: int, r: Resoconto):
    try:
        return piano.registra_resoconto(aid, r.come, r.resoconto or None, r.processo or None, r.prossimo_codice or None,
                                        r.prossimo_giorni, r.prossimo_descrizione or None, r.giorni, r.data or None,
                                        r.prossima_data or None)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class Preparazione(BaseModel):
    testo: str
    durata_min: Optional[int] = None


@app.post("/api/piano/{aid}/preparazione")
def piano_preparazione(aid: int, p: Preparazione):
    try:
        return piano.salva_preparazione(aid, p.testo, p.durata_min)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.post("/api/piano/{aid}/oggi")
def piano_oggi(aid: int, giorno: Optional[str] = None):
    return piano.pianifica_oggi(aid, giorno)


@app.get("/api/utenti")
def api_utenti():
    return core.utenti()


class NuovoUtente(BaseModel):
    nome: str
    cognome: Optional[str] = None
    email: Optional[str] = None
    ruolo: Optional[str] = None


@app.post("/api/utenti")
def api_nuovo_utente(u: NuovoUtente):
    try:
        return core.crea_utente(u.nome, u.cognome, u.email, u.ruolo)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/obiettivo/{oid}/piano")
def api_piano_obiettivo(oid: int):
    try:
        return pianifica.piano_obiettivo(str(oid))
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class PianoOb(BaseModel):
    risposte: dict
    applica: bool = False


@app.post("/api/obiettivo/{oid}/piano")
def api_salva_piano(oid: int, p: PianoOb):
    try:
        return pianifica.salva_piano(str(oid), p.risposte, None, p.applica)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.post("/api/obiettivo/{oid}/piano/ai")
def api_piano_ai(oid: int, p: PianoOb):
    try:
        return pianifica.chiedi_ai(str(oid), p.risposte)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/offerte")
def api_offerte(stato: Optional[str] = None, centro: Optional[str] = None, iniziativa: Optional[str] = None, q: Optional[str] = None):
    return offerte.elenco_offerte(stato or None, centro or None, iniziativa or None, q or None)


@app.get("/api/offerta/{oid}")
def api_offerta(oid: int):
    try:
        o = offerte.offerta(oid)
        o["premessa_base"] = offerte.premessa_base(o)
        return o
    except core.CRMError as e:
        raise HTTPException(404, str(e))


class NuovaOfferta(BaseModel):
    oggetto: str
    azienda_id: Optional[int] = None
    contatto_id: Optional[int] = None
    trattativa_id: Optional[int] = None
    righe: Optional[list[dict]] = None


@app.post("/api/offerte")
def api_nuova_offerta(n: NuovaOfferta):
    try:
        return offerte.crea_offerta(n.oggetto, str(n.azienda_id) if n.azienda_id else None,
                                    str(n.contatto_id) if n.contatto_id else None,
                                    str(n.trattativa_id) if n.trattativa_id else None, n.righe)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class ModOfferta(BaseModel):
    campi: Optional[dict] = None
    righe: Optional[list[dict]] = None


@app.post("/api/offerta/{oid}")
def api_mod_offerta(oid: int, m: ModOfferta):
    try:
        return offerte.aggiorna_offerta(oid, m.campi, m.righe)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class StatoOfferta(BaseModel):
    stato: str
    note: Optional[str] = None
    concorrente: Optional[str] = None
    giorni_followup: int = 7


@app.post("/api/offerta/{oid}/stato")
def api_stato_offerta(oid: int, s: StatoOfferta):
    try:
        return offerte.cambia_stato(oid, s.stato, s.note or None, s.concorrente or None, s.giorni_followup)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.post("/api/offerta/{oid}/revisione")
def api_rev_offerta(oid: int):
    try:
        return offerte.revisione(oid)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/calendario")
def api_calendario(dal: str, al: str, responsabile: Optional[str] = None):
    return piano.calendario(dal, al, responsabile or None)


class Sposta(BaseModel):
    quando: str
    durata_min: Optional[int] = None


@app.post("/api/attivita/{aid}/sposta")
def api_sposta(aid: int, s: Sposta):
    try:
        return piano.sposta(aid, s.quando, s.durata_min)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/calendario.ics")
def api_ics(dal: str, al: str, responsabile: Optional[str] = None):
    from fastapi.responses import Response
    return Response(piano.ics(dal, al, responsabile or None), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="crm-somamed-{dal}-{al}.ics"'})


@app.get("/api/plancia")
def plancia():
    """Plancia di comando: tutto quello che serve per decidere cosa fare adesso."""
    with core.connect() as conn:
        R = lambda sql, *a: core._rows(conn.execute(sql, a))
        one = lambda sql, *a: (conn.execute(sql, a).fetchone() or {}).get("n") or 0
        chiusa = "(coalesce(t.fase,'') IN ('vinta','persa') OR t.esito IS NOT NULL)"
        kpi = {
            "scadute": one("SELECT count(*) n FROM attivita WHERE stato='da fare' AND scadenza < date_trunc('day', now())"),
            "oggi": one("SELECT count(*) n FROM attivita WHERE stato='da fare' AND scadenza::date = current_date"),
            "settimana": one("SELECT count(*) n FROM attivita WHERE stato='da fare' AND scadenza::date > current_date AND scadenza::date <= current_date + 7"),
            "allerte": one("SELECT count(*) n FROM allerte WHERE stato='attiva' AND data <= current_date"),
            "iniziative": one(f"SELECT count(*) n FROM trattative t WHERE NOT {chiusa}"),
            "valore_aperto": float(one(f"SELECT sum(valore_eur) n FROM trattative t WHERE NOT {chiusa}")),
            "venduto": float(one("""SELECT sum(valore_eur) n FROM trattative t WHERE t.esito='vendita' OR t.fase='vinta'""")),
            "vendite": one("""SELECT count(*) n FROM (SELECT trattativa_id, azienda_id FROM esiti_centro WHERE esito='vendita'
                              UNION SELECT id, azienda_id FROM trattative WHERE esito='vendita' OR fase='vinta') x"""),
            "centri": one("SELECT count(*) n FROM aziende"),
            "persone": one("SELECT count(*) n FROM contatti"),
        }
        agenda = R("""SELECT id, codice_standard, standard, descrizione, scadenza, priorita, tipo,
                             azienda_id, azienda, contatto_id, contatto, trattativa_id, trattativa,
                             (scadenza < date_trunc('day', now())) scaduta, (scadenza::date = current_date) oggi
                      FROM v_attivita WHERE stato='da fare' AND (scadenza IS NULL OR scadenza::date <= current_date + 7)
                      ORDER BY scadenza NULLS LAST, id LIMIT 40""")
        allerte = R(core.Q_ALLERTE + " WHERE al.stato='attiva' AND al.data <= current_date + 7 ORDER BY al.data, al.id LIMIT 20")
        obiettivi = R("""SELECT id, titolo, tipo, scadenza, valore_eur, valore_vinto, valore_aperto, n_iniziative, n_vendite, n_sotto
                         FROM v_obiettivi WHERE padre_id IS NULL ORDER BY scadenza NULLS LAST, id""")
        iniziative = R(f"""SELECT v.id, v.titolo, v.genere, v.valore_eur, v.n_centri, v.n_persone, v.n_aperte, v.n_vendite, v.azienda,
                                 v.prodotto, v.chiusura_prevista
                          FROM v_iniziative v JOIN trattative t ON t.id=v.id WHERE NOT {chiusa}
                          ORDER BY v.n_aperte DESC, v.valore_eur DESC NULLS LAST LIMIT 8""")
        risultati = R("""SELECT * FROM (
                           SELECT e.esito, e.concorrente, e.data, a.id azienda_id, a.nome azienda, t.id trattativa_id, t.titolo trattativa,
                                  p.nome prodotto, CASE WHEN t.azienda_id=a.id THEN t.valore_eur END valore_eur
                           FROM esiti_centro e JOIN aziende a ON a.id=e.azienda_id JOIN trattative t ON t.id=e.trattativa_id
                           LEFT JOIN prodotti p ON p.id=t.prodotto_id
                           UNION
                           SELECT CASE WHEN t.fase='vinta' THEN 'vendita' WHEN t.fase='persa' AND t.esito IS NULL THEN 'rifiuto' ELSE t.esito END,
                                  t.concorrente, t.aggiornata_il::date, a.id, a.nome, t.id, t.titolo, p.nome, t.valore_eur
                           FROM trattative t JOIN aziende a ON a.id=t.azienda_id LEFT JOIN prodotti p ON p.id=t.prodotto_id
                           WHERE (t.esito IS NOT NULL OR t.fase IN ('vinta','persa'))
                             AND NOT EXISTS (SELECT 1 FROM esiti_centro e WHERE e.trattativa_id=t.id AND e.azienda_id=t.azienda_id)
                         ) x ORDER BY data DESC NULLS LAST LIMIT 10""")
        return {"kpi": kpi, "agenda": agenda, "allerte": allerte, "obiettivi": obiettivi, "verifica": core.avanzamento_obiettivi(),
                "iniziative": iniziative, "risultati": risultati}


@app.get("/api/oggetto/{tipo}/{oid}")
def oggetto(tipo: str, oid: int):
    with core.connect() as conn:
        R = lambda sql, *a: core._rows(conn.execute(sql, a))
        O = lambda sql, *a: core._clean(conn.execute(sql, a).fetchone())
        if tipo == "azienda":
            obj = O("SELECT * FROM v_aziende WHERE id=%s", oid)
            if not obj:
                raise HTTPException(404)
            return {"tipo": tipo, "oggetto": obj,
                    "contatti": R("""SELECT id, trim(nome||' '||coalesce(cognome,'')) nome, ruolo, professionalita, email,
                                         email_privata, telefono, cellulare, linkedin, esperienze, conosciuto_personalmente
                                  FROM contatti WHERE azienda_id=%s ORDER BY conosciuto_personalmente DESC, cognome, nome""", oid),
                    "da_fare": R("SELECT * FROM v_attivita WHERE azienda_id=%s AND stato='da fare' ORDER BY scadenza NULLS LAST", oid),
                    "fatte": R("SELECT * FROM v_attivita WHERE azienda_id=%s AND stato<>'da fare' ORDER BY coalesce(completata_il, scadenza) DESC NULLS LAST", oid),
                    "diario": R("SELECT id, giorno, testo, contatto_id, contatto FROM v_note WHERE genere='diario' AND azienda_id=%s ORDER BY giorno DESC, id DESC", oid),
                    "prodotti": R("SELECT DISTINCT prodotto_id id, prodotto nome, bu FROM v_attivita WHERE azienda_id=%s AND prodotto_id IS NOT NULL", oid),
                    "trattative": R("SELECT t.id, t.titolo, t.fase, t.valore_eur, t.probabilita, t.divisione FROM trattative t WHERE azienda_id=%s ORDER BY aggiornata_il DESC", oid),
                    "sequenze": _sequenze(conn, "azienda_id=%s", [oid]),
                    "operazioni": core.situazione_centro(conn, oid),
                    "note": R("SELECT id, testo, fonte, creata_il FROM note WHERE azienda_id=%s ORDER BY creata_il DESC", oid)}
        if tipo == "contatto":
            obj = O("""SELECT c.*, a.nome azienda, upper(a.provincia) provincia, a.regione_eff regione
                       FROM contatti c LEFT JOIN v_aziende a ON a.id=c.azienda_id WHERE c.id=%s""", oid)
            if not obj:
                raise HTTPException(404)
            return {"tipo": tipo, "oggetto": obj,
                    "aziende": R("SELECT id, nome, tipo, provincia FROM v_aziende WHERE id=(SELECT azienda_id FROM contatti WHERE id=%s)", oid),
                    "relazioni": core.relazioni_di(conn, oid),
                    "da_fare": R("SELECT * FROM v_attivita WHERE contatto_id=%s AND stato='da fare' ORDER BY scadenza NULLS LAST", oid),
                    "fatte": R("SELECT * FROM v_attivita WHERE contatto_id=%s AND stato<>'da fare' ORDER BY coalesce(completata_il, scadenza) DESC NULLS LAST", oid),
                    "diario": R("SELECT id, giorno, testo, azienda_id, azienda FROM v_note WHERE genere='diario' AND contatto_id=%s ORDER BY giorno DESC", oid),
                    "prodotti": R("SELECT DISTINCT prodotto_id id, prodotto nome, bu FROM v_attivita WHERE contatto_id=%s AND prodotto_id IS NOT NULL", oid),
                    "trattative": R("SELECT DISTINCT t.id, t.titolo, t.fase, t.valore_eur FROM trattative t LEFT JOIN attivita a ON a.trattativa_id=t.id WHERE t.contatto_id=%s OR a.contatto_id=%s", oid, oid),
                    "sequenze": _sequenze(conn, "contatto_id=%s", [oid]),
                    "note": R("SELECT id, testo, fonte, creata_il FROM note WHERE contatto_id=%s ORDER BY creata_il DESC", oid)}
        if tipo == "prodotto":
            obj = O("SELECT * FROM prodotti WHERE id=%s", oid)
            if not obj:
                raise HTTPException(404)
            return {"tipo": tipo, "oggetto": obj,
                    "aziende": R("SELECT DISTINCT azienda_id id, azienda nome, area FROM v_attivita WHERE prodotto_id=%s AND azienda_id IS NOT NULL", oid),
                    "contatti": R("SELECT DISTINCT contatto_id id, contatto nome, professionalita, azienda FROM v_attivita WHERE prodotto_id=%s AND contatto_id IS NOT NULL", oid),
                    "trattative": R("SELECT t.id, t.titolo, t.fase, t.valore_eur, t.probabilita, a.nome azienda FROM trattative t LEFT JOIN aziende a ON a.id=t.azienda_id WHERE prodotto_id=%s", oid),
                    "sequenze": _sequenze(conn, "prodotto_id=%s", [oid]), "note": []}
        if tipo == "trattativa":
            obj = O("SELECT * FROM v_iniziative WHERE id=%s", oid)
            if not obj:
                raise HTTPException(404)
            return {"tipo": tipo, "oggetto": obj,
                    "aziende": R("""SELECT DISTINCT a.id, a.nome, a.tipo, upper(a.provincia) provincia FROM v_aziende a
                                    WHERE a.id IN (SELECT azienda_id FROM attivita WHERE trattativa_id=%s)
                                       OR a.id=(SELECT azienda_id FROM trattative WHERE id=%s)""", oid, oid),
                    "contatti": R("SELECT DISTINCT contatto_id id, contatto nome, professionalita FROM v_attivita WHERE trattativa_id=%s AND contatto_id IS NOT NULL", oid),
                    "prodotti": R("SELECT id, nome, divisione bu FROM prodotti WHERE id=(SELECT prodotto_id FROM trattative WHERE id=%s)", oid),
                    "grafo": core.grafo(iniziativa=str(oid)),
                    "da_contattare": core.persone_da_contattare(str(oid)),
                    "candidati": core.candidati_target(conn, oid),
                    "esiti": R("""SELECT e.*, a.nome azienda, upper(a.provincia) provincia FROM esiti_centro e
                                  JOIN v_aziende a ON a.id=e.azienda_id WHERE trattativa_id=%s ORDER BY data DESC""", oid),
                    "province_centri": R("""SELECT DISTINCT upper(a.provincia) provincia, a.id azienda_id FROM v_aziende a
                                            WHERE a.provincia IS NOT NULL AND (a.id IN (SELECT azienda_id FROM attivita WHERE trattativa_id=%s)
                                               OR a.id=(SELECT azienda_id FROM trattative WHERE id=%s))""", oid, oid),
                    "sequenze": [],
                    "note": R("SELECT id, testo, fonte, creata_il FROM note WHERE trattativa_id=%s ORDER BY creata_il DESC", oid)}
        if tipo == "obiettivo":
            obj = O("SELECT * FROM v_obiettivi WHERE id=%s", oid)
            if not obj:
                raise HTTPException(404)
            return {"tipo": tipo, "oggetto": obj, "grafo": core.grafo(obiettivo=str(oid)),
                    "sotto": R("SELECT * FROM v_obiettivi WHERE padre_id=%s ORDER BY id", oid),
                    "trattative": R("SELECT id, titolo, genere, fase, valore_eur, n_centri, n_vendite FROM v_iniziative WHERE obiettivo_id=%s", oid),
                    "avanzamento": core.avanzamento_obiettivo(str(oid)),
                    "piano": pianifica.piano_obiettivo(str(oid))}
        if tipo == "attivita":
            obj = O("SELECT * FROM v_attivita WHERE id=%s", oid)
            if not obj:
                raise HTTPException(404)
            simili = []
            try:
                emb = conn.execute("SELECT embedding FROM attivita WHERE id=%s", (oid,)).fetchone()["embedding"]
                if emb is not None:
                    simili = R("""SELECT v.id, v.codice_standard, v.descrizione, v.azienda, v.stato,
                                         round((1 - (a.embedding <=> %s))::numeric, 3) somiglianza
                                  FROM attivita a JOIN v_attivita v ON v.id=a.id
                                  WHERE a.id<>%s ORDER BY a.embedding <=> %s LIMIT 5""", emb, oid, emb)
            except Exception:
                simili = []
            return {"tipo": tipo, "oggetto": obj, "catena": _catena(conn, oid), "simili": simili}
    raise HTTPException(404, "tipo sconosciuto")


@app.get("/api/cerca")
def cerca(q: str):
    nomi = core.trova(q, 8)
    with core.connect() as conn:
        prodotti = core._rows(conn.execute(
            "SELECT id, nome, divisione FROM prodotti WHERE nome ILIKE '%%'||%s||'%%' OR similarity(nome,%s)>0.25 LIMIT 8", (q, q)))
    return {"aziende": nomi["aziende"], "contatti": nomi["contatti"], "prodotti": prodotti,
            "semantica": core.ricerca_semantica(q, 8)}


class NuovaAttivita(BaseModel):
    descrizione: str
    codice_standard: Optional[str] = None
    tipo: str = "compito"
    scadenza: Optional[str] = None
    priorita: str = "media"
    azienda_id: Optional[int] = None
    contatto_id: Optional[int] = None
    prodotto_id: Optional[int] = None
    trattativa_id: Optional[int] = None
    precedente_id: Optional[int] = None
    responsabile: str = "Stefano"


@app.post("/api/attivita")
def nuova(a: NuovaAttivita):
    try:
        with core.connect() as conn:
            return core.inserisci_attivita(conn, a.descrizione, a.tipo, a.scadenza or None, a.priorita,
                                           a.azienda_id, a.contatto_id, a.trattativa_id, a.prodotto_id,
                                           a.codice_standard or None, a.precedente_id, a.responsabile)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class Esito(BaseModel):
    esito: Optional[str] = None
    stato: str = "fatta"


@app.post("/api/attivita/{aid}/completa")
def completa(aid: int, e: Esito):
    try:
        return core.completa_attivita(aid, e.esito, e.stato)
    except core.CRMError as err:
        raise HTTPException(400, str(err))


# ---------- centri, mappa, contatti ----------

def _filtri_centri(q):
    w, p = ["true"], []
    if q.get("regione") or q.get("provincia"):
        with core.connect() as _c:
            fw, fp = core.filtro_luoghi(_c, q.get("regione"), q.get("provincia"), "provincia", "regione_eff")
        w += fw; p += fp
    if q.get("natura"):
        w.append("natura=%s" if q["natura"] != "__nessuno__" else "natura IS NULL")
        if q["natura"] != "__nessuno__": p.append(q["natura"])
    if q.get("dimensione"):
        w.append("dimensione=%s" if q["dimensione"] != "__nessuno__" else "dimensione IS NULL")
        if q["dimensione"] != "__nessuno__": p.append(q["dimensione"])
    if q.get("q"):
        w.append("(nome ILIKE '%%'||%s||'%%' OR citta ILIKE '%%'||%s||'%%')"); p += [q["q"], q["q"]]
    if q.get("conosciuti") == "1":
        w.append("n_conosciuti > 0")
    if q.get("tipo"):
        w.append("tipo=%s"); p.append(q["tipo"])
    return " AND ".join(w), p


@app.get("/api/centri")
def centri(request: Request):
    q = dict(request.query_params)
    w, p = _filtri_centri(q)
    geo_q = {k: v for k, v in q.items() if k not in ("regione", "provincia")}
    wg, pg = _filtri_centri(geo_q)
    with core.connect() as conn:
        R = lambda sql, a: core._rows(conn.execute(sql, a))
        return {
            "centri": R(f"""SELECT id, nome, tipo, natura, dimensione, citta, upper(provincia) provincia, regione_eff regione,
                                   telefono, email, n_contatti, n_conosciuti, n_aperte, relazione,
                                   (SELECT max(coalesce(t.completata_il, t.scadenza)) FROM attivita t
                                    WHERE t.azienda_id=v_aziende.id AND t.stato='fatta') ultimo_contatto
                            FROM v_aziende WHERE {w} ORDER BY nome LIMIT 2000""", p),
            "tipi": [r["tipo"] for r in conn.execute("SELECT DISTINCT tipo FROM aziende WHERE tipo IS NOT NULL ORDER BY 1")],
            "per_regione": R(f"SELECT regione_eff chiave, count(*) n FROM v_aziende WHERE {wg} AND regione_eff IS NOT NULL GROUP BY 1", pg),
            "per_provincia": R(f"SELECT upper(provincia) chiave, count(*) n FROM v_aziende WHERE {wg} AND provincia IS NOT NULL GROUP BY 1", pg),
            "senza_luogo": conn.execute(f"SELECT count(*) n FROM v_aziende WHERE {wg} AND regione_eff IS NULL", pg).fetchone()["n"],
        }


@app.get("/api/contatti")
def contatti(request: Request):
    q = dict(request.query_params)
    w, p = ["true"], []
    if q.get("centro"):
        w.append("a.id=%s"); p.append(int(q["centro"]))
    if q.get("regione") or q.get("provincia"):
        with core.connect() as _c:
            fw, fp = core.filtro_luoghi(_c, q.get("regione"), q.get("provincia"), "a.provincia", "a.regione_eff")
        w += fw; p += fp
    if q.get("conosciuti") == "1":
        w.append("c.conosciuto_personalmente")
    if q.get("q"):
        w.append("""(c.nome||' '||coalesce(c.cognome,'') ILIKE '%%'||%s||'%%' OR c.ruolo ILIKE '%%'||%s||'%%'
                     OR c.professionalita ILIKE '%%'||%s||'%%' OR a.nome ILIKE '%%'||%s||'%%')"""); p += [q["q"]] * 4
    with core.connect() as conn:
        return core._rows(conn.execute(
            f"""SELECT c.id, trim(c.nome||' '||coalesce(c.cognome,'')) nome, c.ruolo, c.professionalita, c.email,
                       c.cellulare, c.telefono, c.conosciuto_personalmente, c.esperienze,
                       a.id azienda_id, a.nome azienda, upper(a.provincia) provincia, a.regione_eff regione, a.tipo tipo_centro,
                       (SELECT count(*) FROM relazioni_contatti r WHERE c.id IN (r.contatto_a, r.contatto_b)) n_relazioni,
                       s.n_contatti, s.ultimo_contatto, s.n_aperte, s.n_iniziative
                FROM contatti c LEFT JOIN v_aziende a ON a.id=c.azienda_id
                LEFT JOIN v_storico_contatti s ON s.contatto_id=c.id WHERE {' AND '.join(w)}
                ORDER BY c.conosciuto_personalmente DESC, c.cognome, c.nome LIMIT 1000""", p))


class Conosciuto(BaseModel):
    valore: bool


@app.post("/api/contatto/{cid}/conosciuto")
def conosciuto(cid: int, c: Conosciuto):
    return core.aggiorna_contatto(cid, conosciuto_personalmente=c.valore)


class Relazione(BaseModel):
    contatto_a: int
    contatto_b: int
    tipo: str = "amicizia"
    note: Optional[str] = None


@app.post("/api/relazioni")
def nuova_relazione(r: Relazione):
    try:
        return core.collega_contatti(r.contatto_a, r.contatto_b, r.tipo, r.note)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.post("/api/relazioni/{rid}/elimina")
def elimina_relazione(rid: int):
    with core.connect() as conn:
        conn.execute("DELETE FROM relazioni_contatti WHERE id=%s", (rid,))
    return {"ok": True}


# ---------- diario e note ----------

@app.get("/api/note")
def note(q: Optional[str] = None, centro: Optional[str] = None, provincia: Optional[str] = None,
         regione: Optional[str] = None, dal: Optional[str] = None, al: Optional[str] = None,
         genere: Optional[str] = None, limite: int = 100):
    return core.cerca_note(q or None, centro or None, provincia or None, regione or None,
                           dal or None, al or None, genere or None, limite)


class VoceDiario(BaseModel):
    testo: str
    giorno: Optional[str] = None
    azienda_id: Optional[int] = None
    contatto_id: Optional[int] = None


@app.post("/api/diario")
def nuovo_diario(v: VoceDiario):
    if not v.testo.strip():
        raise HTTPException(400, "Scrivi il testo.")
    return core.scrivi_diario(v.testo.strip(), v.giorno or None,
                              str(v.azienda_id) if v.azienda_id else None, str(v.contatto_id) if v.contatto_id else None)


# ---------- importazione da Notion ----------

@app.post("/api/importa")
async def importa(request: Request, nome: str):
    from . import importa_notion
    dati = await request.body()
    if not dati:
        raise HTTPException(400, "File vuoto.")
    try:
        return await run_in_threadpool(importa_notion.importa, [(nome, dati)])
    except Exception as e:
        raise HTTPException(400, f"Non riesco a leggere {nome}: {e}")


# ---------- obiettivi, campagne, opportunità, esiti ----------

@app.get("/api/grafo")
def api_grafo(obiettivo: Optional[str] = None, iniziativa: Optional[str] = None, aperte: str = ""):
    return core.grafo(obiettivo or None, iniziativa or None, aperte == "1")


@app.get("/api/iniziative")
def iniziative(genere: Optional[str] = None, obiettivo: Optional[str] = None):
    w, p = ["true"], []
    if genere:
        w.append("genere=%s"); p.append(core._genere(genere))
    if obiettivo:
        w.append("obiettivo_id=%s"); p.append(int(obiettivo))
    with core.connect() as conn:
        return core._rows(conn.execute(
            f"""SELECT id, titolo, genere, fase, esito, concorrente, obiettivo_id, obiettivo, prodotto, divisione,
                       azienda_id, azienda, data_inizio, chiusura_prevista, valore_eur, n_centri, n_persone,
                       n_attivita, n_aperte, n_vendite, n_rifiuti, n_scelto_altro, n_sospese, target
                FROM v_iniziative WHERE {' AND '.join(w)}
                ORDER BY (coalesce(fase,'') IN ('vinta','persa')), obiettivo_id NULLS LAST, titolo""", p))


class NuovoObiettivo(BaseModel):
    padre_id: Optional[int] = None
    regioni: list[str] = []
    province: list[str] = []
    tipo: str = "area"
    ambito: Optional[str] = None
    titolo: str
    descrizione: Optional[str] = None
    scadenza: Optional[str] = None
    valore_eur: Optional[float] = None
    target_centri: Optional[int] = None
    data_inizio: Optional[str] = None


@app.post("/api/obiettivi")
def nuovo_obiettivo(o: NuovoObiettivo):
    if not o.titolo.strip():
        raise HTTPException(400, "Scrivi il titolo.")
    try:
        return core.crea_obiettivo(o.titolo.strip(), o.descrizione, o.scadenza or None, o.valore_eur, o.tipo,
                                   o.ambito or None, str(o.padre_id) if o.padre_id else None, o.regioni, o.province,
                                   o.target_centri, o.data_inizio or None)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class NuovaIniziativa(BaseModel):
    genere: str = "commerciale"
    titolo: str
    obiettivo_id: Optional[int] = None
    prodotto_id: Optional[int] = None
    azienda_id: Optional[int] = None
    storia: Optional[str] = None
    target: dict = {}
    data_inizio: Optional[str] = None
    data_fine: Optional[str] = None
    valore_eur: Optional[float] = None


@app.post("/api/iniziative")
def nuova_iniziativa(n: NuovaIniziativa):
    if not n.titolo.strip():
        raise HTTPException(400, "Scrivi il titolo.")
    try:
        if True:
            return core.crea_campagna(n.titolo.strip(), str(n.prodotto_id) if n.prodotto_id else None,
                                      str(n.obiettivo_id) if n.obiettivo_id else None, n.storia, n.target,
                                      n.data_inizio or None, n.data_fine or None, None, n.valore_eur,
                                      n.genere, str(n.azienda_id) if n.azienda_id else None)
        with core.connect() as conn:
            az = conn.execute("SELECT nome FROM aziende WHERE id=%s", (n.azienda_id,)).fetchone() if n.azienda_id else None
        r = core.crea_trattativa(n.titolo.strip(), az["nome"] if az else None, None, "primo contatto", None,
                                 n.valore_eur, None, n.data_fine or None, None,
                                 str(n.prodotto_id) if n.prodotto_id else None,
                                 str(n.obiettivo_id) if n.obiettivo_id else None, n.storia)
        with core.connect() as conn:
            conn.execute("UPDATE trattative SET target=%s, data_inizio=%s WHERE id=%s",
                         (core._json.dumps(n.target or {}), n.data_inizio or None, r["id"]))
        return r
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class EsitoCentro(BaseModel):
    trattativa_id: int
    azienda_id: int
    esito: str
    concorrente: Optional[str] = None
    note: Optional[str] = None


@app.post("/api/esiti")
def nuovo_esito(e: EsitoCentro):
    try:
        return core.registra_esito(str(e.trattativa_id), str(e.azienda_id), e.esito, e.concorrente or None, e.note or None)
    except core.CRMError as err:
        raise HTTPException(400, str(err))


@app.get("/api/dacontattare")
def dacontattare(iniziativa: Optional[str] = None, provincia: Optional[str] = None, conosciuti: str = "",
                 regione: Optional[str] = None):
    return core.persone_da_contattare(iniziativa or None, provincia or None, conosciuti == "1", 300, regione or None)


# ---------- storico, allerte, riattivazione ----------

@app.get("/api/contatto/{cid}/storico")
def storico(cid: int, trattativa: Optional[int] = None):
    with core.connect() as conn:
        return {"storico": core.storico_contatto(conn, cid), "avvisi": core.avvisi_contatto(conn, cid, trattativa)}


@app.get("/api/allerte")
def allerte(stato: str = "attiva", entro: Optional[int] = None, contatto: Optional[str] = None,
            azienda: Optional[str] = None, iniziativa: Optional[str] = None):
    return core.elenco_allerte(stato or None, entro, contatto or None, azienda or None, iniziativa or None)


class NuovaAllerta(BaseModel):
    data: str
    messaggio: str
    tipo: str = "sollecito"
    contatto_id: Optional[int] = None
    azienda_id: Optional[int] = None
    trattativa_id: Optional[int] = None
    attivita_id: Optional[int] = None


@app.post("/api/allerte")
def nuova_allerta(a: NuovaAllerta):
    if not a.messaggio.strip():
        raise HTTPException(400, "Scrivi il messaggio.")
    try:
        return core.imposta_allerta(a.data, a.messaggio.strip(), a.tipo,
                                    str(a.contatto_id) if a.contatto_id else None,
                                    str(a.azienda_id) if a.azienda_id else None,
                                    str(a.trattativa_id) if a.trattativa_id else None, a.attivita_id)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


class CambioAllerta(BaseModel):
    stato: Optional[str] = None
    data: Optional[str] = None


@app.post("/api/allerte/{aid}")
def cambia_allerta(aid: int, c: CambioAllerta):
    try:
        return core.aggiorna_allerta(aid, c.stato, c.data)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/riattivare")
def riattivare(giorni: int = 90):
    return core.da_riattivare(giorni)


# ---------- tabelle: modifica e nuove righe ----------

@app.post("/api/modifica/{tabella}/{oid}")
async def modifica(tabella: str, oid: int, request: Request):
    if tabella not in core.MODIFICABILI:
        raise HTTPException(404)
    try:
        return await run_in_threadpool(core.modifica, tabella, oid, await request.json())
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.post("/api/nuovo/azienda")
async def nuovo_centro(request: Request):
    d = await request.json()
    if not (d.get("nome") or "").strip():
        raise HTTPException(400, "Scrivi il nome del centro.")
    return await run_in_threadpool(core.crea_azienda, d["nome"].strip(), d.get("tipo") or "altro", d.get("citta") or None, None, None, None, None,
                             d.get("provincia") or None, d.get("natura") or None, d.get("dimensione") or None,
                             None, d.get("telefono") or None, d.get("email") or None)


@app.post("/api/nuovo/contatto")
async def nuovo_contatto(request: Request):
    d = await request.json()
    if not (d.get("nome") or "").strip():
        raise HTTPException(400, "Scrivi il nome.")
    return await run_in_threadpool(_nuovo_contatto, d)


def _nuovo_contatto(d):
    with core.connect() as conn:
        az = conn.execute("SELECT nome FROM aziende WHERE id=%s", (d.get("azienda_id"),)).fetchone() if d.get("azienda_id") else None
    return core.crea_contatto(d["nome"].strip(), d.get("cognome") or None, az["nome"] if az else None, d.get("ruolo") or None,
                              d.get("email") or None, d.get("telefono") or None, None, None, d.get("professionalita") or None,
                              None, d.get("cellulare") or None, None, None, None, bool(d.get("conosciuto_personalmente")))


@app.get("/api/obiettivi/albero")
def obiettivi_albero():
    return core.albero_obiettivi()


@app.get("/api/avanzamento")
def avanzamento(obiettivo: Optional[str] = None):
    try:
        return core.avanzamento_obiettivo(obiettivo) if obiettivo else core.avanzamento_obiettivi()
    except core.CRMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/obiettivi")
def obiettivi():
    with core.connect() as conn:
        return core._rows(conn.execute("SELECT * FROM v_obiettivi ORDER BY stato, scadenza NULLS LAST, id"))


@app.get("/api/prodotti")
def prodotti():
    with core.connect() as conn:
        return core._rows(conn.execute(
            """SELECT p.*, (SELECT count(*) FROM trattative t WHERE t.prodotto_id=p.id) n_iniziative,
                      (SELECT count(*) FROM attivita a WHERE a.prodotto_id=p.id OR a.trattativa_id IN
                         (SELECT id FROM trattative WHERE prodotto_id=p.id)) n_attivita,
                      (SELECT count(*) FROM esiti_centro e JOIN trattative t ON t.id=e.trattativa_id
                        WHERE t.prodotto_id=p.id AND e.esito='vendita') n_vendite
               FROM prodotti p ORDER BY p.divisione, p.nome"""))


@app.post("/api/nuovo/prodotto")
async def nuovo_prodotto(request: Request):
    d = await request.json()
    if not (d.get("nome") or "").strip():
        raise HTTPException(400, "Scrivi il nome del prodotto.")
    tip = d.get("tipologie_clienti") or []
    if isinstance(tip, str):
        tip = [x.strip() for x in tip.split(",") if x.strip()]
    return await run_in_threadpool(core.crea_prodotto, d["nome"].strip(), d.get("divisione") or "Altro", d.get("produttore") or None,
                              d.get("descrizione") or None, tip, d.get("descrizione_clienti") or None)


@app.get("/api/dacompiere")
def api_dacompiere(centro: Optional[str] = None, provincia: Optional[str] = None, regione: Optional[str] = None,
                   q: Optional[str] = None, giorni: int = 60):
    return core.da_compiere(centro or None, provincia or None, regione or None, q or None, giorni)


@app.get("/api/giornate")
def api_giornate(dal: Optional[str] = None, al: Optional[str] = None, centro: Optional[str] = None,
                 provincia: Optional[str] = None, regione: Optional[str] = None, q: Optional[str] = None):
    return core.giornate(dal or None, al or None, centro or None, provincia or None, regione or None, q or None)


@app.get("/api/mappa-mentale")
def api_mappa(tipo: Optional[str] = None, id: Optional[int] = None):
    try:
        return core.mappa_mentale(tipo or None, id)
    except core.CRMError as e:
        raise HTTPException(400, str(e))


def main():
    import uvicorn
    if config.HOST not in ("127.0.0.1", "localhost") and not config.TOKEN:
        log.warning("Il servizio è raggiungibile dalla rete (CRM_HOST=%s) senza CRM_TOKEN: imposta una chiave in config.env!", config.HOST)
    uvicorn.run(app, host=config.HOST, port=config.PORT, timeout_keep_alive=30, log_level="info")


if __name__ == "__main__":
    main()

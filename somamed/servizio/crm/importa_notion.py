"""Importa nel CRM l'esportazione di Notion (Markdown e CSV): 3_STRUTTURE, 4_CONTATTI, ATTIVITA.

Accetta file .zip (anche zip dentro zip) o .csv. Si può reimportare: i dati già presenti
vengono aggiornati, non duplicati.
Uso da Terminale:  .venv/bin/python -m crm.importa_notion file1.zip file2.zip ...
"""
import csv
import io
import re
import sys
import unicodedata
import zipfile
from datetime import datetime

from . import core

MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
        "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
        "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9,
        "ott": 10, "nov": 11, "dic": 12, "jan": 1, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "dec": 12}

# Classificazione Notion -> (canale CRM, attività standard)
CLASSIFICAZIONE = {
    "call": ("chiamata", "STD-010"), "email": ("email", "STD-010"), "meeting": ("riunione", "STD-030"),
    "demo": ("demo", "STD-040"), "visita": ("visita", "STD-050"),
    "preparazione offerta": ("offerta", "STD-070"), "ricerca / analisi": ("compito", "STD-020"),
    "invio materiale": ("email", "STD-030"), "networking": ("riunione", "STD-010"),
    "reminder": ("follow-up", "STD-080"),
}
ESITO_FATTO = {"successo", "parziale", "fallita"}
PRIORITA = {"critica": "alta", "alta": "alta", "media": "media", "bassa": "bassa"}
DIMENSIONE = {"enterprise": "grande", "mid-market": "medio", "smb": "piccolo", "startup": "piccolo"}


# ---------- utilità di lettura ----------

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _senza_emoji(s):
    return re.sub(r"^[^\w(]+", "", (s or "").strip()).strip()


def _v(row, *chiavi):
    for k in chiavi:
        v = row.get(k)
        if v not in (None, ""):
            return v.strip()
    return None


def _lista(v):
    """Valori multipli o relazioni Notion -> elenco di titoli."""
    if not v:
        return []
    trovati = re.findall(r"\s*([^,]+?)\s*\((?:https?://[^)]*|[^)]*\.md)\)", v)
    if trovati:
        return [t.strip() for t in trovati if t.strip()]
    return [x.strip() for x in v.split(",") if x.strip()]


def _data(v):
    if not v:
        return None
    v = v.split("→")[0].strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M",
                "%m/%d/%Y", "%m/%d/%Y %I:%M %p", "%B %d, %Y", "%B %d, %Y %I:%M %p", "%B %d, %Y %H:%M"):
        try:
            return datetime.strptime(v, fmt).isoformat(timespec="minutes")
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})\s+([a-zA-Zàé]+)\.?\s+(\d{4})(?:\s+(\d{1,2})[:.](\d{2}))?", v)
    if m and m.group(2).lower() in MESI:
        d = datetime(int(m.group(3)), MESI[m.group(2).lower()], int(m.group(1)),
                     int(m.group(4) or 0), int(m.group(5) or 0))
        return d.isoformat(timespec="minutes")
    m = re.match(r"([a-zA-Z]+)\s+(\d{1,2}),\s+(\d{4})", v)
    if m and m.group(1).lower() in MESI:
        return datetime(int(m.group(3)), MESI[m.group(1).lower()], int(m.group(2))).isoformat(timespec="minutes")
    return None


def _csv_righe(testo):
    testo = testo.lstrip("﻿")
    r = csv.DictReader(io.StringIO(testo))
    return [{(k or "").strip(): (v or "") for k, v in row.items()} for row in r]


def raccogli(nome, dati, csvs, mds):
    """Estrae CSV e pagine .md, entrando anche negli zip annidati."""
    low = nome.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(dati)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                raccogli(info.filename, z.read(info), csvs, mds)
    elif low.endswith(".csv"):
        csvs.append((nome, dati.decode("utf-8-sig", errors="replace")))
    elif low.endswith(".md"):
        mds.append((nome, dati.decode("utf-8", errors="replace")))


def _tipo_csv(intestazioni):
    h = set(intestazioni)
    if "Nome Struttura" in h:
        return "strutture"
    if "Descrizione della task" in h or "Classificazione" in h:
        return "attivita"
    if "Name" in h and ({"Email (Work)", "Ruolo", "Aziende", "Phone (Mobile)"} & h):
        return "contatti"
    return None


# ---------- import delle tre tabelle ----------

def importa_strutture(righe, rep):
    for r in righe:
        nome = _v(r, "Nome Struttura", "Denominazione Struttura")
        if not nome:
            continue
        privata = (_v(r, "Privata") or "").lower()
        dim = (_v(r, "Dimensione") or "").lower()
        natura = "privato" if privata.startswith("s") else "pubblico" if privata == "no" or "pubblic" in dim else None
        dimensione = next((v for k, v in DIMENSIONE.items() if dim.startswith(k)), None)
        tipi = _lista(_v(r, "Tipo Struttura"))
        settori = _lista(_v(r, "Settore"))
        note = "\n".join(f"{k}: {r[k].strip()}" for k in
                         ("COS'E", "Note Strategiche", "Opportunità Identificate", "Strategia di Ingresso",
                          "Leva Commerciale", "Interessi Comuni", "Rischi", "Prossima Azione")
                         if r.get(k, "").strip())
        prov = (_v(r, "Provincia", "Provincia 1") or "")[:2].upper() or None
        core.crea_azienda(
            nome, tipo=_tipo_centro(_v(r, "Tipo Struttura 1"), tipi), citta=_v(r, "Località", "Sede Legale: Località"),
            regione=_regione(_v(r, "Area Geografica")), provincia=prov, natura=natura, dimensione=dimensione,
            indirizzo=_v(r, "Indirizzo", "Sede Legale: Indirizzo"), telefono=_v(r, "Telefono", "TEL"),
            email=_v(r, "Email Principale"), sito=_v(r, "Sito Web", "URL"), cap=_v(r, "CAP"),
            ats=_v(r, "ATS"), relazione=(_v(r, "Forza Relazione") or "").lower() or None,
            strategicita=_v(r, "Strategicità"), tag=tipi + settori, note=note or None)
        if note:
            _nota(f"notion:struttura:{_norm(nome)}", f"Dati strategici da Notion — {nome}\n{note}",
                  "documento", azienda=nome)
        rep["centri"] += 1


def _tipo_centro(t1, tipi):
    t1 = (t1 or "").lower()
    if "ricovero" in t1:
        return "clinica privata"
    if any(x in tipi for x in ("Distributore", "Possibilità Distribuzione")):
        return "distributore"
    if "Partner Strategico" in tipi:
        return "partner"
    if "Fornitore" in tipi:
        return "fornitore"
    if "KOL / Università" in tipi:
        return "università"
    return "altro"


def _regione(area):
    if not area:
        return None
    a = _norm(area)
    for nome in ("Lombardia", "Piemonte", "Veneto", "Lazio", "Toscana", "Campania", "Emilia-Romagna", "Liguria",
                 "Puglia", "Sicilia", "Sardegna", "Marche", "Umbria", "Abruzzo", "Molise", "Basilicata", "Calabria",
                 "Friuli-Venezia Giulia", "Trentino-Alto Adige", "Valle d'Aosta"):
        if _norm(nome).split()[0] in a:
            return nome
    return None


def importa_contatti(righe, rep):
    for r in righe:
        pieno = _v(r, "Name")
        if not pieno:
            continue
        parti = pieno.split()
        aziende = _lista(_v(r, "Aziende"))
        prof = (_v(r, "Prof. Contact") or "").lower()
        core.crea_contatto(
            parti[0], " ".join(parti[1:]) or None, azienda=aziende[0] if aziende else None,
            ruolo=_v(r, "Ruolo"), email=_v(r, "Email (Work)"), telefono=_v(r, "Phone (Work)"),
            cellulare=_v(r, "Phone (Mobile)", "Phone  (Mobile)"), telefono_privato=_v(r, "Phone (Private)"),
            email_privata=_v(r, "Email (Private)"), linkedin=_v(r, "LinkedIn"), esperienze=_v(r, "Expertise"),
            note=_v(r, "Important Notes"), business=_lista(_v(r, "PER QUALE BUISNESS")),
            tag=["contatto personale"] if prof in ("no", "false") else [],
            chiave_import=f"notion:contatto:{_norm(pieno)}")
        if _v(r, "Important Notes"):
            _nota(f"notion:contatto-note:{_norm(pieno)}", f"{pieno}: {_v(r, 'Important Notes')}", "documento",
                  azienda=aziende[0] if aziende else None, contatto_id=_id_contatto(pieno))
        rep["contatti"] += 1


def _id_contatto(pieno):
    with core.connect() as conn:
        r = conn.execute("SELECT id FROM contatti WHERE chiave_import=%s",
                         (f"notion:contatto:{_norm(pieno)}",)).fetchone()
        return r["id"] if r else None


def importa_attivita(righe, rep):
    for r in righe:
        titolo = _senza_emoji(_v(r, "Descrizione della task"))
        if not titolo:
            continue
        cls = _norm(_senza_emoji(_v(r, "Classificazione")))
        canale, std = next(((c, s) for k, (c, s) in CLASSIFICAZIONE.items() if _norm(k) == cls), ("compito", None))
        esito = _norm(_senza_emoji(_v(r, "Esito")))
        stato = "fatta" if esito in ESITO_FATTO else "da fare"
        prio = PRIORITA.get(_norm(_senza_emoji(_v(r, "Priorità"))), "media")
        scad = _data(_v(r, "Data inizio")) or _data(_v(r, "Data Fine"))
        persone = _lista(_v(r, "Cliente Contattato"))
        cid = _id_contatto(persone[0]) if persone else None
        prodotto = _v(r, "Prodotto")
        chiave = f"notion:attivita:{_norm(titolo)}:{scad or ''}"
        with core.connect() as conn:
            if conn.execute("SELECT 1 FROM attivita WHERE chiave_import=%s", (chiave,)).fetchone():
                rep["attivita_gia_presenti"] += 1
                continue
            pid = None
            if prodotto:
                try:
                    pid = core.risolvi_prodotto(conn, "Schermatura RM" if prodotto.lower() == "itel" else prodotto)
                except core.CRMError:
                    pid = None
            a = core.inserisci_attivita(conn, titolo, canale, scad, prio, None, cid, None, pid, std, None)
            esito_txt = "; ".join(x for x in (_senza_emoji(_v(r, "Esito")),
                                              f"Prossimo passo: {_v(r, 'next step')}" if _v(r, "next step") else None) if x)
            conn.execute("""UPDATE attivita SET stato=%s, esito=nullif(%s,''), chiave_import=%s,
                              completata_il=CASE WHEN %s='fatta' THEN coalesce(scadenza, now()) END WHERE id=%s""",
                         (stato, esito_txt, chiave, stato, a["id"]))
        rep["attivita"] += 1


def _nota(chiave, testo, fonte, azienda=None, contatto_id=None):
    with core.connect() as conn:
        if conn.execute("SELECT 1 FROM note WHERE chiave_import=%s", (chiave,)).fetchone():
            conn.execute("UPDATE note SET testo=%s, embedding=%s WHERE chiave_import=%s",
                         (testo, core._vec(testo[:4000]), chiave))
            return
        az = core.risolvi_azienda(conn, azienda, crea_se_manca=True) if azienda else None
        if contatto_id and not az:
            az = conn.execute("SELECT azienda_id FROM contatti WHERE id=%s", (contatto_id,)).fetchone()["azienda_id"]
        conn.execute("""INSERT INTO note (testo, fonte, azienda_id, contatto_id, embedding, chiave_import)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                     (testo, fonte, az, contatto_id, core._vec(testo[:4000]), chiave))


def importa_pagine(mds, rep):
    """Il testo delle pagine Notion (sotto le proprietà) diventa una nota del centro o della persona."""
    with core.connect() as conn:
        centri = {_norm(r["nome"]): r["nome"] for r in conn.execute("SELECT nome FROM aziende")}
        persone = {k.split(":", 2)[2]: i for k, i in
                   ((r["chiave_import"], r["id"]) for r in conn.execute(
                       "SELECT id, chiave_import FROM contatti WHERE chiave_import LIKE 'notion:contatto:%%'"))}
    for nome, testo in mds:
        righe = testo.splitlines()
        if not righe or not righe[0].startswith("# "):
            continue
        titolo = righe[0][2:].strip()
        i = 1
        while i < len(righe) and (not righe[i].strip() or re.match(r"^[^:\n]{1,60}:\s", righe[i])):
            i += 1
        corpo = "\n".join(righe[i:]).strip()
        if len(corpo) < 20:
            continue
        k = _norm(titolo)
        chiave = f"notion:pagina:{_norm(nome)}"
        if k in persone:
            _nota(chiave, f"{titolo}\n{corpo}", "documento", contatto_id=persone[k])
        elif k in centri:
            _nota(chiave, f"{titolo}\n{corpo}", "documento", azienda=centri[k])
        else:
            continue
        rep["pagine"] += 1


def importa(file):
    """file: elenco di (nome, bytes). Restituisce un riepilogo."""
    core.migra()
    csvs, mds = [], []
    for nome, dati in file:
        raccogli(nome, dati, csvs, mds)
    rep = {"centri": 0, "contatti": 0, "attivita": 0, "attivita_gia_presenti": 0, "pagine": 0,
           "file_csv": [], "file_ignorati": []}
    gruppi = {"strutture": [], "contatti": [], "attivita": []}
    visti = set()
    for nome, testo in sorted(csvs, key=lambda x: ("_all" not in x[0], x[0])):
        righe = _csv_righe(testo)
        tipo = _tipo_csv(righe[0].keys()) if righe else None
        base = re.sub(r"(_all)?\.csv$", "", nome.lower())
        if not tipo or base in visti:
            rep["file_ignorati"].append(nome.split("/")[-1])
            continue
        visti.add(base)
        gruppi[tipo].extend(righe)
        rep["file_csv"].append(f"{nome.split('/')[-1]} → {tipo} ({len(righe)} righe)")
    # un'unica transazione: se un file è difettoso non resta un'importazione a metà
    with core.transazione():
        importa_strutture(gruppi["strutture"], rep)
        importa_contatti(gruppi["contatti"], rep)
        importa_attivita(gruppi["attivita"], rep)
        importa_pagine(mds, rep)
    return rep


if __name__ == "__main__":
    elenco = [(p, open(p, "rb").read()) for p in sys.argv[1:]]
    print(importa(elenco))

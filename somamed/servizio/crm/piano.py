"""Piano del giorno: sceglie e ordina le attività da fare in base alle ore disponibili,
prepara la traccia di chiamata o il testo della mail, raccoglie com'è andata e propone
miglioramenti dei processi. La preparazione può essere riscritta da Claude (salva_preparazione)."""
from datetime import date, datetime, timedelta, time
import math
from . import core
from .core import connect, _rows, _clean, CRMError

DURATA = {"chiamata": 20, "email": 15, "follow-up": 15, "riunione": 60, "demo": 60, "visita": 120,
          "offerta": 90, "compito": 30}
CANALE = {"chiamata": "Chiamata", "email": "Email", "follow-up": "Follow-up", "riunione": "Riunione",
          "demo": "Demo", "visita": "Visita", "offerta": "Offerta", "compito": "Compito"}

DOMANDE = {
    "STD-010": ["Chi segue oggi questo tema nel vostro centro?", "Qual è oggi la priorità più urgente su questo fronte?",
                "Ha senso fissare 20 minuti per mostrarvi come lavoriamo?"],
    "STD-020": ["Come gestite oggi questa attività? Con quali strumenti e persone?", "Cosa non funziona o costa troppo?",
                "Chi decide e chi deve essere coinvolto?", "Ci sono scadenze, gare o fondi già previsti?"],
    "STD-030": ["Cosa vi è sembrato più utile?", "Quali dubbi restano?", "Chi altro dovrebbe vederlo?"],
    "STD-040": ["Su quali casi reali volete provarlo?", "Chi partecipa alla prova e per quanto tempo?",
                "Come misuriamo insieme il risultato?"],
    "STD-050": ["Quali vincoli tecnici ci sono (spazi, impianti, reti)?", "Chi è il riferimento tecnico in sede?"],
    "STD-060": ["Quali dati possiamo avere e in che formato?", "Entro quando?"],
    "STD-070": ["L'offerta corrisponde a quanto discusso?", "Chi deve approvarla e con che tempi?"],
    "STD-080": ["Ha avuto modo di vedere l'offerta?", "Ci sono punti da chiarire o da rivedere?",
                "Qual è il prossimo passaggio interno e quando?"],
    "STD-090": ["Cosa serve per chiudere?", "Su quale punto c'è margine?", "Data realistica per l'ordine?"],
    "STD-100": ["Qual è lo stato della procedura?", "Ci sono chiarimenti da presentare?"],
}


def _quando(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _nome(c):
    return (c or "").split(" ")[0] if c else ""


def prepara(v):
    """Traccia standard (senza AI) di chiamata, mail o incontro, a partire dai dati del CRM."""
    nome = _nome(v.get("contatto")) or "…"
    std = v.get("standard") or "attività"
    perche = v.get("descrizione") or ""
    storia = (v.get("storia") or "").strip()
    prod = v.get("prodotto") or ""
    desc_p = (v.get("prodotto_descrizione") or "").strip()
    ult = v.get("ultima_interazione")
    ripresa = (f"ci eravamo sentiti il {ult['quando']} ({ult['cosa']})" if ult else "")
    messaggio = storia.split(". ")[0].rstrip(".") + "." if storia else (desc_p.split(". ")[0].rstrip(".") + "." if desc_p else "")
    domande = DOMANDE.get(v.get("codice_standard") or "", ["Qual è la situazione oggi?", "Cosa vi servirebbe?", "Qual è il prossimo passo?"])
    dopo = v.get("passo_successivo") or "il prossimo passo"
    if v.get("tipo") == "email" or (v.get("tipo") == "follow-up" and not v.get("cellulare") and not v.get("telefono")):
        oggetto = f"{prod or 'SomaMed'} — {std.lower()}" + (f" per {v.get('azienda')}" if v.get("azienda") else "")
        corpo = (f"Gentile {nome},\n\n"
                 + (f"riprendo il contatto: {ripresa}.\n\n" if ripresa else "")
                 + (f"{perche}\n\n" if perche else "")
                 + (f"{messaggio}\n\n" if messaggio else "")
                 + f"Le propongo come {dopo.lower()} un breve incontro di 20 minuti: le andrebbe bene una data nei prossimi giorni?\n\n"
                 + "Un cordiale saluto,\nStefano Rampoldi\nSomaMed")
        return f"OGGETTO: {oggetto}\n\n{corpo}"
    righe = [f"OBIETTIVO: {std}" + (f" — {perche}" if perche else "")]
    righe.append(f"APERTURA: «Buongiorno {nome}, sono Stefano Rampoldi di SomaMed" + (f"; {ripresa}" if ripresa else "") + ".»")
    if messaggio:
        righe.append(f"MESSAGGIO CHIAVE: {messaggio}")
    righe.append("DOMANDE:\n" + "\n".join(f"  • {d}" for d in domande))
    righe.append(f"CHIUSURA: fissare {dopo.lower()} con una data precisa.")
    if v.get("tipo") in ("riunione", "demo", "visita"):
        righe.append("DA PORTARE: presentazione di " + (prod or "prodotto") + ", un caso simile, la proposta dei prossimi passi.")
    return "\n".join(righe)


def _priorita(v, oggi):
    s, motivo = 0.0, []
    sc = _quando(v.get("scadenza"))
    if v.get("pianificata_il") and str(v["pianificata_il"])[:10] == oggi.isoformat():
        s += 200; motivo.append("messa in piano per oggi")
    if sc:
        d = (sc.date() - oggi).days
        if d < 0:
            s += 100 + min(30, -d * 2); motivo.append(f"scaduta da {-d} giorni")
        elif d == 0:
            s += 80; motivo.append("in scadenza oggi")
        elif d <= 3:
            s += 40; motivo.append(f"scade tra {d} giorni")
        elif d <= 7:
            s += 20; motivo.append("scade questa settimana")
    else:
        s += 5; motivo.append("senza data")
    s += {"alta": 30, "media": 0, "bassa": -10}.get(v.get("priorita"), 0)
    if v.get("priorita") == "alta":
        motivo.append("priorità alta")
    if v.get("valore_eur"):
        s += min(20, math.log10(float(v["valore_eur"]) + 1) * 3)
    if v.get("allerta"):
        s += 50; motivo.append("allerta: " + v["allerta"])
    if v.get("conosciuto"):
        s += 3
    return s, motivo


def _carica(conn, oggi, responsabile=None):
    att = _rows(conn.execute(
        """SELECT v.id, v.tipo, v.codice_standard, v.standard, v.ordine_standard, v.descrizione, v.scadenza, v.priorita,
                  v.azienda_id, v.azienda, v.provincia, v.contatto_id, v.contatto, v.ruolo, v.conosciuto,
                  v.trattativa_id, v.trattativa, v.prodotto_id, v.prodotto,
                  a.durata_min, a.preparazione, a.pianificata_il, a.rimandi,
                  c.cellulare, c.telefono, c.email,
                  t.genere, t.storia, t.valore_eur,
                  coalesce(p.descrizione, tp.descrizione) prodotto_descrizione, coalesce(p.nome, tp.nome) prodotto_nome
           FROM v_attivita v JOIN attivita a ON a.id=v.id
           LEFT JOIN contatti c ON c.id=v.contatto_id
           LEFT JOIN trattative t ON t.id=v.trattativa_id
           LEFT JOIN prodotti p ON p.id=v.prodotto_id
           LEFT JOIN prodotti tp ON tp.id=t.prodotto_id
           WHERE v.stato='da fare' AND (%s::text IS NULL OR v.responsabile = %s)""", (responsabile, responsabile)))
    allerte = _rows(conn.execute(
        "SELECT id, tipo, messaggio, contatto_id, azienda_id, attivita_id FROM allerte WHERE stato='attiva' AND data <= %s",
        (oggi,)))
    per_att = {a["attivita_id"]: a for a in allerte if a.get("attivita_id")}
    per_ct = {}
    for a in allerte:
        if a.get("contatto_id"):
            per_ct.setdefault(a["contatto_id"], a)
    ultime = {}
    ids = [a["contatto_id"] for a in att if a.get("contatto_id")]
    if ids:
        for r in _rows(conn.execute(
                """SELECT DISTINCT ON (v.contatto_id) v.contatto_id, v.standard, v.descrizione, v.esito, a.resoconto, v.completata_il
                   FROM v_attivita v JOIN attivita a ON a.id=v.id WHERE v.stato='fatta' AND v.contatto_id = ANY(%s)
                   ORDER BY v.contatto_id, v.completata_il DESC NULLS LAST""", (ids,))):
            q = _quando(r.get("completata_il"))
            ultime[r["contatto_id"]] = {"quando": q.strftime("%d/%m") if q else "", "cosa": r.get("standard") or "contatto",
                                        "esito": r.get("resoconto") or r.get("esito")}
    std = _rows(conn.execute("SELECT codice, nome, ordine FROM catalogo_attivita ORDER BY ordine"))
    for a in att:
        al = per_att.get(a["id"]) or per_ct.get(a.get("contatto_id"))
        if al:
            a["allerta"] = al["messaggio"]
        a["ultima_interazione"] = ultime.get(a.get("contatto_id"))
        nx = next((s for s in std if s["ordine"] > (a.get("ordine_standard") or 0)), None)
        a["passo_successivo"] = nx["nome"] if nx else None
        a["passo_successivo_codice"] = nx["codice"] if nx else None
        a["prodotto"] = a.get("prodotto") or a.get("prodotto_nome")
    return att


def piano_giorno(giorno=None, ore=None, inizio=None, responsabile=None):
    """Piano del giorno: attività ordinate per urgenza fino a riempire le ore disponibili,
    con orario, persona, recapiti, motivo e preparazione (traccia di chiamata o testo della mail)."""
    oggi = date.fromisoformat(giorno) if giorno else date.today()
    with connect() as conn:
        pg = conn.execute("SELECT ore, inizio FROM piano_giorni WHERE giorno=%s", (oggi,)).fetchone()
        if ore is not None:
            conn.execute("""INSERT INTO piano_giorni (giorno, ore, inizio) VALUES (%s,%s,coalesce(%s::time,'09:00'))
                            ON CONFLICT (giorno) DO UPDATE SET ore=EXCLUDED.ore,
                            inizio=coalesce(%s::time, piano_giorni.inizio)""", (oggi, ore, inizio, inizio))
        ore = float(ore if ore is not None else (pg["ore"] if pg else 6))
        ini = inizio or (str(pg["inizio"])[:5] if pg else "09:00")
        att = _carica(conn, oggi, responsabile)
        senza_passo = _rows(conn.execute(
            """SELECT DISTINCT ON (a.azienda_id, a.trattativa_id) a.azienda_id, z.nome azienda, a.trattativa_id, t.titolo trattativa,
                      a.contatto_id, trim(coalesce(c.nome,'')||' '||coalesce(c.cognome,'')) contatto,
                      a.codice_standard, ca.nome standard, ca.ordine, a.completata_il
               FROM attivita a JOIN aziende z ON z.id=a.azienda_id JOIN trattative t ON t.id=a.trattativa_id
               LEFT JOIN contatti c ON c.id=a.contatto_id LEFT JOIN catalogo_attivita ca ON ca.codice=a.codice_standard
               WHERE a.stato='fatta' AND t.esito IS NULL AND coalesce(t.fase,'') NOT IN ('vinta','persa')
                 AND NOT EXISTS (SELECT 1 FROM attivita x WHERE x.azienda_id=a.azienda_id AND x.trattativa_id=a.trattativa_id AND x.stato='da fare')
                 AND NOT EXISTS (SELECT 1 FROM esiti_centro e WHERE e.azienda_id=a.azienda_id AND e.trattativa_id=a.trattativa_id)
               ORDER BY a.azienda_id, a.trattativa_id, a.completata_il DESC"""))
        std = _rows(conn.execute("SELECT codice, nome, ordine FROM catalogo_attivita ORDER BY ordine"))
    for a in att:
        a["punteggio"], a["motivi"] = _priorita(a, oggi)
        a["durata"] = int(a.get("durata_min") or DURATA.get(a.get("tipo"), 30))
        a["canale"] = CANALE.get(a.get("tipo"), "Attività")
    att.sort(key=lambda a: -a["punteggio"])
    disponibili = int(ore * 60)
    h, m = (int(x) for x in ini.split(":")[:2])
    t = datetime.combine(oggi, time(h, m))
    usati, voci, fuori = 0, [], []
    for a in att:
        dovuta = a["punteggio"] >= 80 or not a.get("scadenza") or (_quando(a["scadenza"]) and _quando(a["scadenza"]).date() <= oggi + timedelta(days=7))
        if usati + a["durata"] <= disponibili and dovuta:
            a["inizio"], a["fine"] = t.strftime("%H:%M"), (t + timedelta(minutes=a["durata"])).strftime("%H:%M")
            t += timedelta(minutes=a["durata"] + 5); usati += a["durata"] + 5
            a["preparazione_ai"] = bool(a.get("preparazione"))
            a["preparazione"] = a.get("preparazione") or prepara(a)
            voci.append(a)
        else:
            fuori.append({k: a.get(k) for k in ("id", "standard", "descrizione", "azienda_id", "azienda", "contatto_id",
                                                "contatto", "scadenza", "durata", "motivi", "canale", "trattativa_id", "trattativa")})
    proposte = []
    for r in senza_passo:
        nx = next((s for s in std if s["ordine"] > (r.get("ordine") or 0)), None)
        if nx:
            proposte.append({**r, "proposta_codice": nx["codice"], "proposta": nx["nome"]})
    for v in voci:
        for k in ("prodotto_nome",):
            v.pop(k, None)
    return {"giorno": oggi.isoformat(), "ore": ore, "inizio": ini, "minuti_disponibili": disponibili,
            "minuti_pianificati": usati, "voci": voci, "fuori": fuori[:30], "senza_prossimo_passo": proposte[:20],
            "suggerimenti": suggerimenti_processo()}


def salva_preparazione(attivita_id, testo, durata_min=None):
    """Salva la traccia di chiamata o il testo della mail preparati (anche da Claude) per un'attività."""
    with connect() as conn:
        r = conn.execute("UPDATE attivita SET preparazione=%s, durata_min=coalesce(%s,durata_min) WHERE id=%s RETURNING id, preparazione",
                         (testo, durata_min, int(attivita_id))).fetchone()
        if not r:
            raise CRMError(f"Attività {attivita_id} non trovata.")
        return _clean(r)


def registra_resoconto(attivita_id, come="fatta", resoconto=None, processo=None, prossimo_codice=None,
                       prossimo_giorni=7, prossimo_descrizione=None, giorni=None, data=None, prossima_data=None):
    """Com'è andata un'attività.
    come: fatta (operazione eseguita) · non risponde · rimanda · annullata.
    - fatta: i commenti finiscono, riassunti, nel diario del giorno; si può creare subito il passo successivo
      (prossima_data AAAA-MM-GG, oppure tra prossimo_giorni giorni).
    - non risponde / rimanda: l'attività viene riproposta nel giorno indicato (data AAAA-MM-GG[ HH:MM], oppure tra 'giorni').
    - annullata: serve il perché (resoconto).
    processo: idea per migliorare il processo (resta tra i suggerimenti)."""
    aid = int(attivita_id)
    with connect() as conn:
        a = _clean(conn.execute(
            """SELECT a.*, ca.nome standard, z.nome azienda, trim(coalesce(c.nome,'')||' '||coalesce(c.cognome,'')) contatto
               FROM attivita a LEFT JOIN catalogo_attivita ca ON ca.codice=a.codice_standard
               LEFT JOIN aziende z ON z.id=a.azienda_id LEFT JOIN contatti c ON c.id=a.contatto_id WHERE a.id=%s""", (aid,)).fetchone())
        if not a:
            raise CRMError(f"Attività {aid} non trovata.")
        cosa = a.get("standard") or a.get("descrizione") or "Attività"
        con = " con " + a["contatto"] if a.get("contatto") else ""
        dove = f" ({a['azienda']})" if a.get("azienda") else ""
        out = {"attivita_id": aid, "come": come}
        diario = None
        if come == "fatta":
            conn.execute("""UPDATE attivita SET stato='fatta', completata_il=now(), resoconto=%s,
                            esito=coalesce(%s, esito) WHERE id=%s""", (resoconto, (resoconto or "")[:200] or None, aid))
            diario = f"✓ {cosa}{con}{dove}" + (f": {resoconto.strip()}" if resoconto and resoconto.strip() else ".")
        elif come in ("non risponde", "rimanda"):
            if data:
                quando = str(data).strip()
                quando = quando if len(quando) > 10 else quando[:10] + " " + (str(a.get("scadenza") or "")[11:16] or "09:00")
            else:
                quando = (date.today() + timedelta(days=int(giorni or (2 if come == "non risponde" else 1)))).isoformat() + " 09:00"
            conn.execute("""UPDATE attivita SET scadenza = %s::timestamp, rimandi = rimandi + 1, pianificata_il = %s::date,
                            resoconto = trim(coalesce(resoconto,'') || %s) WHERE id=%s""",
                         (quando, quando[:10], f"\n{date.today().strftime('%d/%m')}: {come}" + (f" — {resoconto}" if resoconto else ""), aid))
            out["nuova_data"] = quando[:10]
            nd = date.fromisoformat(quando[:10]).strftime("%d/%m")
            diario = (f"☎ {cosa}{con}{dove}: non risponde, riprovo il {nd}" if come == "non risponde"
                      else f"↷ {cosa}{con}{dove}: rimandata al {nd}") + (f" — {resoconto.strip()}" if resoconto and resoconto.strip() else "")
        elif come == "annullata":
            if not (resoconto or "").strip():
                raise CRMError("Scrivi perché annulli l'attività.")
            conn.execute("UPDATE attivita SET stato='annullata', resoconto=%s, esito=%s WHERE id=%s",
                         (resoconto, "Annullata: " + resoconto[:180], aid))
            diario = f"✕ {cosa}{con}{dove} annullata: {resoconto.strip()}"
        else:
            raise CRMError("Usa: fatta, non risponde, rimanda, annullata.")
        if processo:
            conn.execute("INSERT INTO note (testo, fonte, tipo, azienda_id, contatto_id, trattativa_id) VALUES (%s,'chat','processo',%s,%s,%s)",
                         (processo, a["azienda_id"], a.get("contatto_id"), a.get("trattativa_id")))
        if come == "fatta" and prossimo_codice:
            nome = conn.execute("SELECT nome FROM catalogo_attivita WHERE codice=%s", (prossimo_codice,)).fetchone()
            tipo = {"STD-010": "chiamata", "STD-020": "chiamata", "STD-030": "riunione", "STD-040": "demo",
                    "STD-050": "visita", "STD-070": "offerta", "STD-080": "follow-up"}.get(prossimo_codice, "compito")
            quando = (prossima_data[:10] if prossima_data else (date.today() + timedelta(days=int(prossimo_giorni or 7))).isoformat()) + " 09:00"
            n = core.inserisci_attivita(conn, prossimo_descrizione or (nome["nome"] if nome else "Passo successivo"), tipo,
                                        quando, "media", a.get("azienda_id"), a.get("contatto_id"), a.get("trattativa_id"), None,
                                        prossimo_codice, aid, a.get("responsabile") or "Stefano")
            out["prossima"] = n
            diario += f" Prossimo passo: {nome['nome'] if nome else 'passo successivo'} il {date.fromisoformat(quando[:10]).strftime('%d/%m')}."
    if diario:
        core.scrivi_diario(diario, None, str(a["azienda_id"]) if a.get("azienda_id") else None,
                           str(a["contatto_id"]) if a.get("contatto_id") else None)
    return out


# ---------- calendario: slot pianificati nel periodo ----------

def calendario(dal, al, responsabile=None):
    """Attività del periodo come slot (inizio, durata), con prodotto, iniziativa, centro e persona;
    più le ore disponibili per giorno, per vedere il carico e spostare la pianificazione."""
    with connect() as conn:
        att = _rows(conn.execute(
            """SELECT v.id, v.tipo, v.codice_standard, v.standard, v.descrizione, v.stato, v.scadenza, v.completata_il,
                      v.azienda_id, v.azienda, v.contatto_id, v.contatto, v.trattativa_id, v.trattativa, t.genere,
                      coalesce(v.prodotto_id, t.prodotto_id) prodotto_id, coalesce(v.prodotto, p.nome) prodotto,
                      a.durata_min, a.responsabile, (v.stato='da fare' AND v.scadenza < now()) scaduta,
                      to_char(coalesce(v.scadenza, v.completata_il) AT TIME ZONE 'Europe/Rome', 'YYYY-MM-DD') giorno,
                      to_char(coalesce(v.scadenza, v.completata_il) AT TIME ZONE 'Europe/Rome', 'HH24:MI') ora
               FROM v_attivita v JOIN attivita a ON a.id=v.id LEFT JOIN trattative t ON t.id=v.trattativa_id
               LEFT JOIN prodotti p ON p.id=t.prodotto_id
               WHERE v.stato IN ('da fare','fatta') AND coalesce(v.scadenza, v.completata_il) IS NOT NULL
                 AND coalesce(v.scadenza, v.completata_il)::date BETWEEN %s::date AND %s::date
                 AND (%s::text IS NULL OR a.responsabile = %s)
               ORDER BY coalesce(v.scadenza, v.completata_il)""", (dal, al, responsabile, responsabile)))
        ore = {str(r["giorno"]): float(r["ore"]) for r in conn.execute(
            "SELECT giorno, ore FROM piano_giorni WHERE giorno BETWEEN %s AND %s", (dal, al)).fetchall()}
    for a in att:
        a["durata"] = int(a.get("durata_min") or DURATA.get(a.get("tipo"), 30))
        a["inizio"] = a.get("scadenza") or a.get("completata_il")
        a["senza_ora"] = a.get("ora") == "00:00"
    return {"dal": dal, "al": al, "attivita": att, "ore_giorno": ore, "ore_predefinite": 6, "durate": DURATA}


def sposta(attivita_id, quando, durata_min=None):
    """Sposta un'attività (trascinandola nel calendario): quando = AAAA-MM-GG HH:MM."""
    with connect() as conn:
        r = conn.execute("""UPDATE attivita SET scadenza=%s::timestamp, pianificata_il=%s::date,
                            durata_min=coalesce(%s, durata_min) WHERE id=%s AND stato='da fare' RETURNING id""",
                         (quando, str(quando)[:10], durata_min, int(attivita_id))).fetchone()
        if not r:
            raise CRMError("Si possono spostare solo le attività ancora da fare.")
    return {"attivita_id": int(attivita_id), "quando": quando}


def ics(dal, al, responsabile=None):
    """Il periodo in formato calendario (.ics), da importare in Google Calendar, Outlook o Apple Calendar."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    roma = ZoneInfo("Europe/Rome")
    c = calendario(dal, al, responsabile)
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SomaMed//CRM//IT", "CALSCALE:GREGORIAN", "X-WR-CALNAME:CRM SomaMed"]
    adesso = _dt.utcnow().strftime("%Y%m%dT%H%M%SZ")
    pulisci = lambda t: str(t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    for a in c["attivita"]:
        try:
            ini = _dt.fromisoformat(str(a["inizio"]).replace("Z", "+00:00"))
        except Exception:
            continue
        ini = ini.astimezone(roma) if ini.tzinfo else ini
        fine = ini + timedelta(minutes=a["durata"])
        tit = f"{a.get('standard') or a.get('descrizione') or 'Attività'}" + (f" · {a['contatto']}" if a.get("contatto") else "") + (f" · {a['azienda']}" if a.get("azienda") else "")
        det = "\n".join(x for x in [a.get("descrizione"), a.get("trattativa") and "Iniziativa: " + a["trattativa"],
                                    a.get("prodotto") and "Prodotto: " + a["prodotto"]] if x)
        righe += ["BEGIN:VEVENT", f"UID:crm-attivita-{a['id']}@somamed", f"DTSTAMP:{adesso}",
                  f"DTSTART;TZID=Europe/Rome:{ini.strftime('%Y%m%dT%H%M%S')}",
                  f"DTEND;TZID=Europe/Rome:{fine.strftime('%Y%m%dT%H%M%S')}",
                  f"SUMMARY:{pulisci(tit)}", f"DESCRIPTION:{pulisci(det)}", "END:VEVENT"]
    righe.append("END:VCALENDAR")
    return "\r\n".join(righe) + "\r\n"


def pianifica_oggi(attivita_id, giorno=None):
    """Mette un'attività nel piano di un giorno (oggi se non indicato)."""
    with connect() as conn:
        g = giorno or date.today().isoformat()
        conn.execute("UPDATE attivita SET pianificata_il=%s, scadenza=coalesce(scadenza, %s::date + time '09:00') WHERE id=%s",
                     (g, g, int(attivita_id)))
    return {"attivita_id": int(attivita_id), "giorno": g}


def suggerimenti_processo():
    """Suggerimenti per migliorare i processi, ricavati dai dati: attività rimandate, follow-up senza risposta,
    passaggi lenti, centri fermi, concorrenti ricorrenti, dove si perde; più le idee annotate dall'utente."""
    out = []
    with connect() as conn:
        R = lambda sql, *p: _rows(conn.execute(sql, p))
        for r in R("""SELECT v.codice_standard, v.standard, count(*) n FROM v_attivita v JOIN attivita a ON a.id=v.id
                      WHERE v.stato='da fare' AND a.rimandi >= 2 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 3"""):
            out.append({"tipo": "attenzione", "titolo": f"«{r['standard']}» rimandata più volte ({r['n']})",
                        "azione": "Spezzala in un passo più piccolo o cambia canale (una chiamata breve al posto della mail)."})
        r = R("""SELECT count(*) n FROM attivita a WHERE a.tipo IN ('email','follow-up') AND a.stato='fatta'
                   AND a.completata_il > now() - interval '60 days'
                   AND EXISTS (SELECT 1 FROM attivita b WHERE b.contatto_id=a.contatto_id AND b.tipo IN ('email','follow-up')
                               AND b.id<>a.id AND b.completata_il BETWEEN a.completata_il AND a.completata_il + interval '15 days')""")
        if r and r[0]["n"] >= 2:
            out.append({"tipo": "attenzione", "titolo": f"{r[0]['n']} mail di sollecito di fila alle stesse persone",
                        "azione": "Dopo una mail senza risposta, il passo successivo sia una telefonata."})
        lenti = R("""SELECT a.codice_standard, ca.nome, round(avg(extract(epoch FROM (b.completata_il - a.completata_il))/86400)) giorni, count(*) n
                     FROM attivita a JOIN attivita b ON b.precedente_id=a.id JOIN catalogo_attivita ca ON ca.codice=a.codice_standard
                     WHERE a.stato='fatta' AND b.stato='fatta' GROUP BY 1,2 HAVING count(*)>=1 ORDER BY 3 DESC LIMIT 1""")
        if lenti and lenti[0]["giorni"] and float(lenti[0]["giorni"]) >= 10:
            out.append({"tipo": "info", "titolo": f"Dopo «{lenti[0]['nome']}» passano in media {int(lenti[0]['giorni'])} giorni",
                        "azione": "Fissa il passo successivo già durante l'attività, con una data."})
        fermi = R("""SELECT count(*) n FROM (SELECT a.azienda_id, a.trattativa_id FROM attivita a JOIN trattative t ON t.id=a.trattativa_id
                     WHERE t.esito IS NULL AND coalesce(t.fase,'') NOT IN ('vinta','persa') AND a.azienda_id IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM esiti_centro e WHERE e.trattativa_id=a.trattativa_id AND e.azienda_id=a.azienda_id)
                     GROUP BY 1,2 HAVING max(coalesce(a.completata_il, a.creata_il)) < now() - interval '30 days') x""")
        if fermi and fermi[0]["n"]:
            out.append({"tipo": "attenzione", "titolo": f"{fermi[0]['n']} centri senza attività da più di 30 giorni",
                        "azione": "Decidi: riattivare con una chiamata o chiudere con un esito."})
        for r in R("""SELECT concorrente, count(*) n FROM esiti_centro WHERE esito='scelto altro' AND concorrente IS NOT NULL
                      GROUP BY 1 HAVING count(*) >= 1 ORDER BY 2 DESC LIMIT 2"""):
            out.append({"tipo": "no", "titolo": (f"Perso 1 centro" if r['n'] == 1 else f"Persi {r['n']} centri") + f" a favore di {r['concorrente']}",
                        "azione": f"Prepara una scheda di confronto con {r['concorrente']} da usare già alla presentazione."})
        for r in R("""SELECT ca.nome, count(*) n FROM esiti_centro e
                      JOIN LATERAL (SELECT max(ca.ordine) o FROM attivita a JOIN catalogo_attivita ca ON ca.codice=a.codice_standard
                                    WHERE a.trattativa_id=e.trattativa_id AND a.azienda_id=e.azienda_id AND a.stato='fatta') x ON true
                      JOIN catalogo_attivita ca ON ca.ordine=x.o
                      WHERE e.esito IN ('rifiuto','scelto altro') GROUP BY 1 ORDER BY 2 DESC LIMIT 1"""):
            out.append({"tipo": "no", "titolo": f"Le trattative perse si fermano più spesso dopo «{r['nome']}»",
                        "azione": "Rivedi come si svolge questo passaggio: cosa manca al cliente per andare avanti?"})
        for r in R("""SELECT n.id, n.testo, n.creata_il, z.nome azienda FROM note n LEFT JOIN aziende z ON z.id=n.azienda_id
                      WHERE n.tipo='processo' ORDER BY n.creata_il DESC LIMIT 8"""):
            out.append({"tipo": "idea", "titolo": r["testo"], "azione": ("annotata su " + r["azienda"]) if r.get("azienda") else "idea annotata",
                        "nota_id": r["id"]})
    return out

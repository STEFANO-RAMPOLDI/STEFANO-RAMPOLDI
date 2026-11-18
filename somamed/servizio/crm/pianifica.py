"""Assistente per gli obiettivi: domande precise → piano misurabile.
Dalle risposte calcola quanti centri contattare, quante presentazioni e offerte servono, il ritmo
settimanale, le ore di lavoro, i costi, il margine e il ritorno; segnala le ipotesi deboli.
Se in config.env c'è ANTHROPIC_API_KEY, un modello AI commenta il piano e propone altre domande;
altrimenti lo stesso lavoro lo fa Claude in chat con gli strumenti piano_obiettivo / salva_piano_obiettivo."""
import json
import math
import os
import urllib.request
from datetime import date
from .core import connect, _clean, _rows, risolvi_obiettivo, CRMError

TIPI_CENTRO = ["ospedale pubblico", "ospedale privato", "clinica privata", "gruppo sanitario", "centro medico",
               "RSA", "laboratorio"]

# Le domande: una sola fonte per interfaccia e Claude. "perche" spiega a cosa serve la risposta.
DOMANDE = [
    {"gruppo": "Risultato", "chiave": "risultato", "tipo": "testo",
     "domanda": "Cosa vuoi ottenere, detto in una frase che si possa misurare?",
     "perche": "Un obiettivo misurabile dice quanto, dove e entro quando: es. «6 ospedali lombardi con Asimily entro giugno 2027»."},
    {"gruppo": "Risultato", "chiave": "ricavo", "tipo": "euro", "domanda": "Quanto fatturato deve portare (€)?",
     "perche": "È il numero da cui si ricavano quante vendite servono."},
    {"gruppo": "Risultato", "chiave": "centri_obiettivo", "tipo": "numero",
     "domanda": "Quanti centri clienti vuoi avere alla fine (se conta più il numero di clienti che il fatturato)?",
     "perche": "Per gli obiettivi di area conta la diffusione: il piano usa il valore più alto tra fatturato e numero di centri."},
    {"gruppo": "Risultato", "chiave": "scadenza", "tipo": "data", "domanda": "Entro quando?",
     "perche": "Con la durata della vendita dice entro quando devi aver iniziato a contattare."},

    {"gruppo": "Mercato", "chiave": "tipi_centro", "tipo": "scelte", "opzioni": TIPI_CENTRO,
     "domanda": "A quali tipi di centro ti rivolgi?", "perche": "Decide quanti centri ci sono davvero da contattare."},
    {"gruppo": "Mercato", "chiave": "centri_disponibili", "tipo": "numero",
     "domanda": "Quanti centri di questo tipo ci sono nell'area dell'obiettivo?",
     "perche": "Se per arrivare al risultato servono più contatti dei centri esistenti, l'obiettivo va rivisto. "
               "Il CRM propone quanti ne conosce già: aggiungi quelli che non hai ancora inserito."},
    {"gruppo": "Mercato", "chiave": "valore_medio", "tipo": "euro", "domanda": "Quanto vale in media una vendita a un centro (€)?",
     "perche": "Fatturato ÷ valore medio = numero di vendite necessarie."},
    {"gruppo": "Mercato", "chiave": "margine", "tipo": "percento", "domanda": "Che margine lordo resta su una vendita (%)?",
     "perche": "Serve per capire se l'impegno commerciale si ripaga."},

    {"gruppo": "Come si vende", "chiave": "conv_contatto", "tipo": "percento",
     "domanda": "Su 10 centri che contatti, quanti accettano un incontro o una presentazione (%)?",
     "perche": "Primo passaggio dell'imbuto: dice quanti centri contattare."},
    {"gruppo": "Come si vende", "chiave": "conv_offerta", "tipo": "percento",
     "domanda": "Su 10 presentazioni, quante arrivano a un'offerta (%)?", "perche": "Secondo passaggio dell'imbuto."},
    {"gruppo": "Come si vende", "chiave": "conv_ordine", "tipo": "percento",
     "domanda": "Su 10 offerte, quante diventano un ordine (%)?", "perche": "Ultimo passaggio: dice quante offerte servono."},
    {"gruppo": "Come si vende", "chiave": "ciclo_mesi", "tipo": "numero",
     "domanda": "Quanti mesi passano in media dalla prima chiamata all'ordine?",
     "perche": "Nel pubblico, con le gare, il ciclo è più lungo: l'ultimo contatto utile è scadenza meno ciclo."},
    {"gruppo": "Come si vende", "chiave": "ore_vinto", "tipo": "numero",
     "domanda": "Quante ore di lavoro servono per un centro che arriva all'ordine (chiamate, incontri, demo, offerta, viaggi)?",
     "perche": "Con le ore dei centri che si fermano prima, dà l'impegno totale di lavoro."},
    {"gruppo": "Come si vende", "chiave": "ore_contatto", "tipo": "numero",
     "domanda": "Quante ore per un centro che si ferma al primo contatto (ricerca della persona, chiamata, mail)?",
     "perche": "Sono tanti centri con poche ore ciascuno: spesso è la parte più sottovalutata."},

    {"gruppo": "Risorse", "chiave": "persone", "tipo": "numero", "domanda": "Quante persone ci lavorano?",
     "perche": "Insieme alle ore settimanali dà le ore disponibili."},
    {"gruppo": "Risorse", "chiave": "ore_settimana", "tipo": "numero",
     "domanda": "Quante ore a settimana ciascuna dedica a questo obiettivo?",
     "perche": "Ore disponibili contro ore necessarie: se non bastano, il piano lo dice subito."},
    {"gruppo": "Risorse", "chiave": "costo_orario", "tipo": "euro", "domanda": "Quanto costa un'ora di lavoro commerciale (€/h)?",
     "perche": "Costo del personale = ore necessarie × costo orario."},
    {"gruppo": "Risorse", "chiave": "provvigione", "tipo": "percento", "domanda": "C'è una provvigione sul venduto (%)?",
     "perche": "Costo variabile che cresce con il fatturato."},
    {"gruppo": "Risorse", "chiave": "marketing", "tipo": "euro",
     "domanda": "Quanto prevedi di spendere in marketing (eventi, materiali, campagne) (€)?", "perche": "Costo fisso del piano."},
    {"gruppo": "Risorse", "chiave": "costo_presentazione", "tipo": "euro",
     "domanda": "Quanto costa in media una presentazione o demo (viaggi, materiali, prove) (€)?",
     "perche": "Si moltiplica per il numero di presentazioni necessarie."},
]

PREDEFINITI = {"conv_contatto": 30, "conv_offerta": 50, "conv_ordine": 35, "ciclo_mesi": 6, "ore_vinto": 30,
               "ore_contatto": 1.5, "persone": 1, "ore_settimana": 10, "costo_orario": 50, "provvigione": 0,
               "marketing": 0, "costo_presentazione": 150, "margine": 40}


def _n(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def calcola(r, oggi=None):
    """Piano misurabile dalle risposte. Stesse formule dell'interfaccia (calcolaPiano in index.html)."""
    oggi = oggi or date.today()
    R = {**PREDEFINITI, **{k: v for k, v in (r or {}).items() if v not in (None, "")}}
    ricavo, valore = _n(R.get("ricavo")), _n(R.get("valore_medio"))
    c1, c2, c3 = (max(0.01, _n(R.get(k)) / 100) for k in ("conv_contatto", "conv_offerta", "conv_ordine"))
    vendite = max(math.ceil(ricavo / valore) if ricavo and valore else 0, int(_n(R.get("centri_obiettivo"))))
    offerte = math.ceil(vendite / c3)
    presentazioni = math.ceil(offerte / c2)
    contatti = math.ceil(presentazioni / c1)
    ricavo_atteso = ricavo if ricavo else vendite * valore
    # tempo
    mesi = ciclo = None
    try:
        fine = date.fromisoformat(str(R.get("scadenza"))[:10])
        mesi = max(0.0, (fine - oggi).days / 30.44)
    except Exception:
        fine = None
    ciclo = _n(R.get("ciclo_mesi"), 6)
    mesi_contatto = max(0.0, (mesi or 0) - ciclo) if mesi is not None else None
    settimane = max(1.0, (mesi_contatto if mesi_contatto else (mesi or 12)) * 4.33)
    # ore
    ore_vinto, ore_contatto = _n(R.get("ore_vinto"), 30), _n(R.get("ore_contatto"), 1.5)
    ore = vendite * ore_vinto + (presentazioni - vendite) * ore_vinto * 0.4 + (contatti - presentazioni) * ore_contatto
    ore_disp = _n(R.get("persone"), 1) * _n(R.get("ore_settimana"), 10) * (mesi or 12) * 4.33
    # economia
    personale = ore * _n(R.get("costo_orario"), 50)
    provv = ricavo_atteso * _n(R.get("provvigione")) / 100
    mkt = _n(R.get("marketing"))
    pres = presentazioni * _n(R.get("costo_presentazione"), 150)
    costi = personale + provv + mkt + pres
    margine = ricavo_atteso * _n(R.get("margine"), 40) / 100
    risultato = margine - costi
    unit = valore * _n(R.get("margine"), 40) / 100 if valore else 0
    pareggio = math.ceil(costi / unit) if unit else None
    disp = int(_n(R.get("centri_disponibili")))

    kpi = [
        {"misura": "Centri da contattare", "valore": contatti, "ritmo": f"{contatti / settimane:.1f} a settimana"},
        {"misura": "Presentazioni / demo", "valore": presentazioni, "ritmo": f"{presentazioni / max(1.0, mesi or 12):.1f} al mese"},
        {"misura": "Offerte", "valore": offerte, "ritmo": f"{offerte / max(1.0, mesi or 12):.1f} al mese"},
        {"misura": "Ordini", "valore": vendite, "ritmo": f"entro {fine.strftime('%d/%m/%Y')}" if fine else ""},
        {"misura": "Offerte aperte da tenere in gioco (€)", "valore": round(offerte * valore) if valore else None,
         "ritmo": "pipeline necessaria"},
    ]
    avvisi = []
    if not vendite:
        avvisi.append(("no", "Manca la misura: indica il fatturato con il valore medio di una vendita, oppure il numero di centri."))
    if disp and contatti > disp:
        avvisi.append(("no", f"Servono {contatti} centri da contattare ma nell'area ce ne sono {disp}: allarga l'area o i tipi di centro, "
                             f"oppure migliora le percentuali di conversione."))
    elif disp and contatti > disp * 0.6:
        avvisi.append(("att", f"Devi contattare {round(contatti / disp * 100)}% dei centri dell'area: margine di errore piccolo."))
    if mesi is not None and mesi_contatto is not None and mesi_contatto <= 0:
        avvisi.append(("no", f"La vendita dura circa {ciclo:g} mesi ma alla scadenza ne mancano {mesi:.1f}: i nuovi contatti non chiuderanno in tempo."))
    elif mesi_contatto is not None and mesi_contatto < 2:
        avvisi.append(("att", f"Restano solo {mesi_contatto:.1f} mesi per fare i primi contatti: vanno concentrati subito."))
    if ore_disp and ore > ore_disp:
        avvisi.append(("no", f"Servono circa {round(ore)} ore di lavoro ma ne avete {round(ore_disp)}: "
                             f"mancano {round(ore - ore_disp)} ore, circa {math.ceil((ore - ore_disp) / max(1, (mesi or 12) * 4.33))} ore a settimana in più."))
    elif ore_disp and ore > ore_disp * 0.8:
        avvisi.append(("att", "Le ore disponibili bastano appena: nessun margine per imprevisti."))
    if risultato < 0:
        avvisi.append(("no", f"Il piano costa più del margine che porta ({round(-risultato):,} € di perdita): rivedi prezzo, margine o costi.".replace(",", ".")))
    if _n(R.get("conv_ordine")) > 50:
        avvisi.append(("att", "Più di 1 offerta su 2 trasformata in ordine è un'ipotesi ottimista: verificala sullo storico."))
    if not avvisi:
        avvisi.append(("ok", "Le ipotesi stanno in piedi: tempi, ore e costi sono compatibili con il risultato."))

    return {
        "risposte": R, "vendite": vendite, "offerte": offerte, "presentazioni": presentazioni, "contatti": contatti,
        "ricavo_atteso": round(ricavo_atteso), "mesi": round(mesi, 1) if mesi is not None else None,
        "mesi_per_contattare": round(mesi_contatto, 1) if mesi_contatto is not None else None,
        "ore_necessarie": round(ore), "ore_disponibili": round(ore_disp), "ore_settimana_necessarie": round(ore / max(1, (mesi or 12) * 4.33), 1),
        "economia": {"personale": round(personale), "provvigioni": round(provv), "marketing": round(mkt),
                     "presentazioni": round(pres), "costi": round(costi), "margine_lordo": round(margine),
                     "risultato": round(risultato), "roi": round(risultato / costi * 100) if costi else None,
                     "costo_per_ordine": round(costi / vendite) if vendite else None, "ordini_pareggio": pareggio},
        "kpi": kpi, "avvisi": [{"tipo": t, "testo": x} for t, x in avvisi],
    }


def proposte(oid):
    """Valori che il CRM sa già: dall'obiettivo e dai dati."""
    with connect() as conn:
        o = _clean(conn.execute("SELECT * FROM obiettivi WHERE id=%s", (oid,)).fetchone())
        regs, provs = o.get("regioni") or [], o.get("province") or []
        n = conn.execute(
            """SELECT count(*) n FROM v_aziende WHERE (cardinality(%s::text[])=0 AND cardinality(%s::text[])=0)
                  OR upper(provincia) = ANY(%s) OR regione = ANY(%s)""", (regs, provs, [p.upper() for p in provs], regs)).fetchone()["n"]
        storico = conn.execute(
            """SELECT count(*) FILTER (WHERE esito='vendita') v, count(*) n FROM esiti_centro""").fetchone()
    p = {"risultato": o.get("titolo"), "ricavo": float(o["valore_eur"]) if o.get("valore_eur") else None,
         "centri_obiettivo": o.get("target_centri"), "scadenza": str(o["scadenza"])[:10] if o.get("scadenza") else None,
         "centri_disponibili": n or None}
    if storico and storico["n"] >= 5:
        p["_nota_storico"] = f"Nel CRM {storico['v']} vendite su {storico['n']} centri chiusi ({round(storico['v'] / storico['n'] * 100)}%)."
    return {k: v for k, v in p.items() if v is not None}


def piano_obiettivo(obiettivo):
    with connect() as conn:
        oid = risolvi_obiettivo(conn, obiettivo)
        o = _clean(conn.execute("SELECT id, titolo, piano FROM obiettivi WHERE id=%s", (oid,)).fetchone())
    salvato = o.get("piano") or {}
    risposte = {**proposte(oid), **(salvato.get("risposte") or {})}
    return {"obiettivo_id": oid, "titolo": o.get("titolo"), "domande": DOMANDE, "risposte": risposte,
            "calcolo": calcola(risposte), "indicazioni_ai": salvato.get("ai"), "salvato_il": salvato.get("salvato_il")}


def salva_piano(obiettivo, risposte, indicazioni=None, applica=False):
    """Salva risposte e piano calcolato nell'obiettivo; con applica=True aggiorna budget, numero di centri e scadenza."""
    with connect() as conn:
        oid = risolvi_obiettivo(conn, obiettivo)
        vecchio = (_clean(conn.execute("SELECT piano FROM obiettivi WHERE id=%s", (oid,)).fetchone()) or {}).get("piano") or {}
        r = {k: v for k, v in (risposte or {}).items() if not k.startswith("_")}
        c = calcola(r)
        piano = {"risposte": r, "calcolo": c, "ai": indicazioni or vecchio.get("ai"),
                 "salvato_il": date.today().isoformat()}
        conn.execute("UPDATE obiettivi SET piano=%s WHERE id=%s", (json.dumps(piano, default=str), oid))
        if applica:
            conn.execute("""UPDATE obiettivi SET valore_eur=coalesce(%s, valore_eur), target_centri=coalesce(%s, target_centri),
                            scadenza=coalesce(%s::date, scadenza) WHERE id=%s""",
                         (c["ricavo_atteso"] or None, c["vendite"] or None, r.get("scadenza") or None, oid))
    return {"obiettivo_id": oid, **piano}


def chiedi_ai(obiettivo, risposte=None):
    """Commento del modello AI sul piano: ipotesi deboli, rischi, domande mancanti, indicazioni operative."""
    chiave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not chiave:
        raise CRMError("Per il commento automatico aggiungi ANTHROPIC_API_KEY nel file config.env. "
                       "Intanto puoi chiedere a Claude in chat: «analizza il piano dell'obiettivo» — usa gli stessi dati.")
    p = piano_obiettivo(obiettivo)
    r = {**p["risposte"], **(risposte or {})}
    c = calcola(r)
    testo = (
        "Sei un consulente commerciale per un'azienda italiana di tecnologie per la sanità (SomaMed). "
        "Ti do le risposte del responsabile e il piano calcolato per un obiettivo. Scrivi in italiano semplice, "
        "massimo 250 parole, con quattro parti brevi: 1) Ipotesi da verificare (quali numeri sembrano ottimisti o deboli e perché); "
        "2) Rischi principali; 3) Domande che mancano per rendere il piano misurabile (massimo 4, precise); "
        "4) Prime tre azioni della prossima settimana. Non inventare dati che non ci sono.\n\n"
        f"OBIETTIVO: {p['titolo']}\nRISPOSTE: {json.dumps(r, ensure_ascii=False, default=str)}\n"
        f"PIANO CALCOLATO: {json.dumps({k: c[k] for k in ('vendite', 'offerte', 'presentazioni', 'contatti', 'mesi', 'mesi_per_contattare', 'ore_necessarie', 'ore_disponibili', 'economia', 'avvisi')}, ensure_ascii=False)}")
    corpo = json.dumps({"model": os.environ.get("CRM_AI_MODELLO", "claude-sonnet-5-5"), "max_tokens": 900,
                        "messages": [{"role": "user", "content": testo}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=corpo, method="POST", headers={
        "x-api-key": chiave, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as risp:
            dati = json.loads(risp.read())
    except Exception as e:
        raise CRMError(f"Il modello AI non ha risposto: {e}")
    out = "".join(b.get("text", "") for b in dati.get("content", []) if b.get("type") == "text").strip()
    salva_piano(obiettivo, {k: v for k, v in r.items() if not str(k).startswith("_")}, out)
    return {"indicazioni_ai": out}

"""Budget strategico e piano tattico, a partire dalle voci (item) che generano il valore di un prodotto.

1. VOCI DEL PRODOTTO — cosa si vende e a quanto: es. Asimily → «dispositivi medicali connessi»,
   € per dispositivo all'anno, contratto di 3 anni.
2. CENSIMENTO DEL CENTRO — quante unità di ogni voce ha ciascun centro: censite, dichiarate dal centro
   o, in mancanza, stimate dai posti letto (o dalla dimensione del centro).
3. BUDGET STRATEGICO — per prodotto e area: valore potenziale e margine di ogni centro, probabilità di
   chiusura (relazione, persone conosciute, già cliente, pubblico/privato), valore atteso, fascia A/B/C
   (Pareto sul valore) e la strategia proposta per aggredirlo.
4. PIANO TATTICO — un'iniziativa "macro" che raccoglie, per ogni centro scelto, la sequenza di attività
   della sua strategia, comprese le operazioni sulle singole voci (censire, verificare, quotare gli strumenti).
5. VERIFICA — budget contro venduto e in corso, centro per centro.

Il calcolo è sempre fatto sui dati aggiornati: in tabella si salvano solo le scelte dell'utente
(centro escluso, probabilità o strategia diverse da quelle proposte).
"""
from datetime import date, timedelta

from . import core
from .core import connect, transazione, _rows, _clean, CRMError, risolvi_prodotto, risolvi_azienda

# Posti letto ipotizzati quando il centro non li ha indicati: stima grossolana, solo per ordinare i centri.
# Va sostituita appena possibile con i posti letto reali o con il censimento delle voci.
POSTI_LETTO_STIMATI = {"piccolo": 80, "medio": 250, "grande": 600}
ESCLUSI = ("distributore", "partner", "fornitore")

# Strategie: come si aggredisce un centro. Ogni passo: (codice standard, tipo, giorni dall'inizio, testo).
# "{voci}" diventa un'attività per ogni voce del prodotto (operazioni sugli strumenti).
STRATEGIE = {
    "attacco": {
        "nome": "Attacco diretto",
        "quando": "centro di alto valore dove abbiamo già accesso (persone conosciute, relazione, già cliente)",
        "passi": [("STD-030", "riunione", 0, "Presentazione di {prodotto} al decisore: valore stimato {valore} ({dettaglio})"),
                  ("STD-060", "compito", 10, "{voci}"),
                  ("STD-040", "demo", 21, "Assessment / demo sul parco strumenti del centro"),
                  ("STD-070", "offerta", 35, "Offerta {prodotto} sulle quantità verificate ({dettaglio})")],
    },
    "accesso": {
        "nome": "Costruire l'accesso",
        "quando": "centro di alto valore dove non conosciamo nessuno",
        "passi": [("STD-010", "chiamata", 0, "Mappare i decisori (ingegneria clinica, IT/sicurezza, direzione) e cercare chi può presentarci"),
                  ("STD-020", "riunione", 14, "Qualifica: bisogno, budget, tempi, chi decide — valore in gioco {valore}"),
                  ("STD-060", "compito", 21, "{voci}"),
                  ("STD-030", "riunione", 30, "Presentazione di {prodotto} con i numeri del centro ({dettaglio})")],
    },
    "sviluppo": {
        "nome": "Sviluppo mirato",
        "quando": "centro di valore medio: contatto mirato, poi qualifica",
        "passi": [("STD-010", "email", 0, "Primo contatto mirato su {prodotto}: valore stimato {valore}"),
                  ("STD-020", "chiamata", 10, "Qualifica esigenza e tempi"),
                  ("STD-060", "compito", 20, "{voci}")],
    },
    "presidio": {
        "nome": "Presidio marketing",
        "quando": "centro di valore basso: comunicazione a basso costo, si passa al commerciale se mostra interesse",
        "passi": [("STD-010", "email", 0, "Inserire nel presidio marketing di {prodotto} (newsletter, webinar, casi d'uso)")],
    },
    "censire": {
        "nome": "Censire prima",
        "quando": "mancano i dati per stimare il valore (posti letto o quantità delle voci)",
        "passi": [("STD-060", "compito", 0, "Raccogliere posti letto e {voci_elenco} per valutare il centro")],
    },
}
PASSO_GARA = ("STD-100", "compito", 50, "Percorso pubblico: consultazione preliminare di mercato / capitolato per {prodotto}")
PRIORITA_FASCIA = {"A": "alta", "B": "media", "C": "bassa"}
RITARDO_FASCIA = {"A": 0, "B": 14, "C": 28}        # le fasce partono scaglionate


def _eur(v):
    return f"{v:,.0f} €".replace(",", ".") if v else "—"


def _q(v):
    return f"{v:,.0f}".replace(",", ".") if v == int(v) else f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _f(v):
    return float(v) if v is not None else None


# ---------- voci dei prodotti ----------

CAMPI_VOCE = ["nome", "unita", "prezzo_unitario", "costo_unitario", "ricorrente", "anni",
              "stima_per_posto_letto", "quantita_fissa", "ordine", "note"]


def voci(prodotto):
    with connect() as conn:
        pid = risolvi_prodotto(conn, prodotto)
        p = conn.execute("SELECT id, nome, divisione FROM prodotti WHERE id=%s", (pid,)).fetchone()
        if not p:
            raise CRMError("Prodotto non trovato.")
        return {"prodotto": _clean(p), "voci": _rows(conn.execute(
            "SELECT * FROM prodotti_voci WHERE prodotto_id=%s ORDER BY ordine, id", (pid,)))}


def salva_voce(prodotto, nome, voce_id=None, **campi):
    """Crea o aggiorna una voce di prezzo del prodotto (solo i campi indicati)."""
    campi = {k: v for k, v in campi.items() if k in CAMPI_VOCE and v is not None}
    for k in ("prezzo_unitario", "costo_unitario", "stima_per_posto_letto", "quantita_fissa"):
        if k in campi:
            campi[k] = None if campi[k] == "" else float(str(campi[k]).replace(",", "."))
            if campi[k] is not None and campi[k] < 0:
                raise CRMError("I valori non possono essere negativi.")
    if "ricorrente" in campi:
        campi["ricorrente"] = str(campi["ricorrente"]).lower() in ("1", "true", "si", "sì", "canone", "yes")
    with connect() as conn:
        if voce_id:
            if nome:
                campi["nome"] = nome
            if campi:
                sets = ", ".join(f"{k}=%s" for k in campi)
                conn.execute(f"UPDATE prodotti_voci SET {sets} WHERE id=%s", list(campi.values()) + [int(voce_id)])
            r = conn.execute("SELECT * FROM prodotti_voci WHERE id=%s", (int(voce_id),)).fetchone()
            if not r:
                raise CRMError("Voce non trovata.")
            return _clean(r)
        if not (nome or "").strip():
            raise CRMError("Scrivi il nome della voce (es. dispositivi medicali connessi).")
        pid = risolvi_prodotto(conn, prodotto)
        campi["nome"] = nome.strip()
        cols = ", ".join(campi)
        upd = ", ".join(f"{k}=EXCLUDED.{k}" for k in campi if k != "nome") or "nome=EXCLUDED.nome"
        r = conn.execute(f"""INSERT INTO prodotti_voci (prodotto_id, {cols}) VALUES (%s, {', '.join(['%s'] * len(campi))})
                             ON CONFLICT (prodotto_id, nome) DO UPDATE SET {upd} RETURNING *""",
                         [pid] + list(campi.values())).fetchone()
        return _clean(r)


def elimina_voce(voce_id):
    with connect() as conn:
        n = conn.execute("DELETE FROM prodotti_voci WHERE id=%s", (int(voce_id),)).rowcount
        return {"eliminata": bool(n)}


# ---------- censimento dei centri ----------

def censisci(azienda, voce_id, quantita, fonte="dichiarata", note=None):
    """Quante unità di una voce ha il centro. quantita vuota = togli il dato (torna la stima)."""
    if fonte not in ("stimata", "dichiarata", "censita"):
        raise CRMError("Fonte: stimata, dichiarata o censita.")
    with connect() as conn:
        az = int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)
        if quantita in (None, ""):
            conn.execute("DELETE FROM centri_voci WHERE azienda_id=%s AND voce_id=%s", (az, int(voce_id)))
            return {"azienda_id": az, "voce_id": int(voce_id), "quantita": None}
        q = float(str(quantita).replace(",", "."))
        if q < 0:
            raise CRMError("La quantità non può essere negativa.")
        r = conn.execute("""INSERT INTO centri_voci (azienda_id, voce_id, quantita, fonte, note) VALUES (%s,%s,%s,%s,%s)
                            ON CONFLICT (azienda_id, voce_id) DO UPDATE SET quantita=EXCLUDED.quantita, fonte=EXCLUDED.fonte,
                              note=coalesce(EXCLUDED.note, centri_voci.note), aggiornato_il=now() RETURNING *""",
                         (az, int(voce_id), q, fonte, note)).fetchone()
        return _clean(r)


def imposta_posti_letto(azienda, posti_letto):
    with connect() as conn:
        az = int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)
        v = None if posti_letto in (None, "") else int(float(str(posti_letto).replace(",", ".")))
        if v is not None and v < 0:
            raise CRMError("I posti letto non possono essere negativi.")
        conn.execute("UPDATE aziende SET posti_letto=%s WHERE id=%s", (v, az))
        return {"azienda_id": az, "posti_letto": v}


def valore_centro(voci_prodotto, censimento, posti_letto, dimensione, sconto=0.0):
    """Valore potenziale e margine di un centro per un prodotto, voce per voce."""
    pl, pl_fonte = (posti_letto, "posti letto") if posti_letto else (POSTI_LETTO_STIMATI.get(dimensione), "dimensione")
    f_sc = 1 - (sconto or 0) / 100
    righe, valore, margine, certo = [], 0.0, 0.0, 0.0
    for v in voci_prodotto:
        c = censimento.get(v["id"])
        if c:
            q, fonte = float(c["quantita"]), c["fonte"]
        elif v.get("quantita_fissa") is not None:
            q, fonte = float(v["quantita_fissa"]), "fissa"
        elif v.get("stima_per_posto_letto") is not None and pl:
            q, fonte = round(float(v["stima_per_posto_letto"]) * pl, 1), f"stimata da {pl_fonte}"
        else:
            q, fonte = None, "mancante"
        anni = int(v.get("anni") or 1) if v.get("ricorrente") else 1
        prezzo, costo = float(v.get("prezzo_unitario") or 0), float(v.get("costo_unitario") or 0)
        val = q * prezzo * anni * f_sc if q is not None else 0.0
        mar = q * (prezzo * f_sc - costo) * anni if q is not None else 0.0
        valore += val
        margine += mar
        if fonte in ("censita", "dichiarata", "fissa"):
            certo += val
        righe.append({"voce_id": v["id"], "voce": v["nome"], "unita": v.get("unita"), "quantita": q, "fonte": fonte,
                      "valore": round(val, 2), "margine": round(mar, 2)})
    return {"voci": righe, "valore": round(valore, 2), "margine": round(margine, 2),
            "affidabilita": round(certo / valore * 100) if valore else 0}


def probabilita_centro(c):
    """Probabilità di chiusura proposta, con il perché (l'utente può sempre cambiarla)."""
    p, perche = 20, ["base 20%"]
    if c.get("perso_prodotto"):
        return 5, ["ha già rifiutato o scelto un concorrente per questo prodotto"]
    if c.get("n_conosciuti"):
        p += 20; perche.append("+20 persone conosciute personalmente")
    elif c.get("n_contatti"):
        p += 5; perche.append("+5 contatti presenti")
    rel = (c.get("relazione") or "").lower()
    if rel == "forte":
        p += 10; perche.append("+10 relazione forte")
    elif rel == "media":
        p += 5; perche.append("+5 relazione media")
    elif rel == "debole":
        p -= 5; perche.append("−5 relazione debole")
    if c.get("vendite_precedenti"):
        p += 10; perche.append("+10 già cliente")
    if (c.get("natura") or "").lower() == "pubblico":
        p -= 5; perche.append("−5 pubblico: serve una procedura")
    return max(5, min(70, p)), perche


def _accessibile(c):
    return bool(c.get("n_conosciuti") or c.get("vendite_precedenti")
                or (c.get("relazione") or "").lower() in ("forte", "media"))


def strategia_proposta(fascia, c):
    if fascia == "—":
        return "censire"
    if fascia == "A":
        return "attacco" if _accessibile(c) else "accesso"
    if fascia == "B":
        return "attacco" if _accessibile(c) and c.get("n_conosciuti") else "sviluppo"
    return "presidio"


# ---------- budget strategico ----------

def crea_budget(titolo, prodotto, obiettivo=None, anno=None, regioni=None, province=None, tipi=None,
                sconto_medio=0, note=None):
    from .core import _lista, risolvi_obiettivo
    if not (titolo or "").strip():
        raise CRMError("Scrivi il titolo del budget.")
    with connect() as conn:
        pid = risolvi_prodotto(conn, prodotto)
        ob = risolvi_obiettivo(conn, obiettivo) if obiettivo else None
        regs, provs = _lista(regioni), [x.upper() for x in _lista(province)]
        if ob and not regs and not provs:   # eredita l'area dell'obiettivo
            o = conn.execute("SELECT regioni, province FROM obiettivi WHERE id=%s", (ob,)).fetchone()
            regs, provs = list(o["regioni"] or []), list(o["province"] or [])
        r = conn.execute("""INSERT INTO budget (titolo, prodotto_id, obiettivo_id, anno, regioni, province, tipi, sconto_medio, note)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                         (titolo.strip(), pid, ob, anno or date.today().year, regs, provs, _lista(tipi),
                          float(sconto_medio or 0), note)).fetchone()
        return budget(r["id"])


def modifica_budget(budget_id, **campi):
    from .core import _lista
    ammessi = {"titolo", "anno", "regioni", "province", "tipi", "sconto_medio", "stato", "note", "obiettivo_id"}
    campi = {k: v for k, v in campi.items() if k in ammessi and v is not None}
    for k in ("regioni", "tipi"):
        if k in campi:
            campi[k] = _lista(campi[k])
    if "province" in campi:
        campi["province"] = [x.upper() for x in _lista(campi["province"])]
    if campi:
        with connect() as conn:
            sets = ", ".join(f"{k}=%s" for k in campi)
            conn.execute(f"UPDATE budget SET {sets}, aggiornato_il=now() WHERE id=%s", list(campi.values()) + [int(budget_id)])
    return budget(budget_id)


def imposta_centro(budget_id, azienda, incluso=None, probabilita=None, strategia=None, note=None):
    """Scelte dell'utente su un centro del budget. probabilita/strategia vuote = torna alla proposta del CRM."""
    if strategia not in (None, "", *STRATEGIE):
        raise CRMError("Strategia: " + ", ".join(STRATEGIE))
    with connect() as conn:
        az = int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)
        conn.execute("INSERT INTO budget_centri (budget_id, azienda_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (int(budget_id), az))
        sets, par = [], []
        if incluso is not None:
            sets.append("incluso=%s"); par.append(str(incluso).lower() in ("1", "true", "si", "sì", "yes"))
        if probabilita is not None:
            pr = None if probabilita == "" else int(float(probabilita))
            if pr is not None and not 0 <= pr <= 100:
                raise CRMError("La probabilità va da 0 a 100.")
            sets.append("probabilita=%s"); par.append(pr)
        if strategia is not None:
            sets.append("strategia=%s"); par.append(strategia or None)
        if note is not None:
            sets.append("note=%s"); par.append(note or None)
        if sets:
            conn.execute(f"UPDATE budget_centri SET {', '.join(sets)} WHERE budget_id=%s AND azienda_id=%s",
                         par + [int(budget_id), az])
    return {"ok": True}


def _carica(conn, budget_id):
    b = conn.execute("""SELECT b.*, p.nome prodotto, p.divisione, p.tipologie_clienti, o.titolo obiettivo,
                               t.titolo iniziativa
                        FROM budget b JOIN prodotti p ON p.id=b.prodotto_id
                        LEFT JOIN obiettivi o ON o.id=b.obiettivo_id LEFT JOIN trattative t ON t.id=b.iniziativa_id
                        WHERE b.id=%s""", (int(budget_id),)).fetchone()
    if not b:
        raise CRMError(f"Budget {budget_id} non trovato.")
    return b


def _centri(conn, b):
    """Centri candidati con tutti i dati che servono a valutarli (una query sola)."""
    w, p = [f"a.tipo NOT IN {ESCLUSI!r}"], []
    fw, fp = core.filtro_luoghi(conn, ",".join(b["regioni"] or []), ",".join(b["province"] or []), "a.provincia", "a.regione_eff")
    w += fw; p += fp
    tipi = b["tipi"] or b["tipologie_clienti"] or []
    if tipi:
        w.append("a.tipo = ANY(%s)"); p.append(list(tipi))
    pid = b["prodotto_id"]
    sql = f"""
      SELECT a.id, a.nome, a.tipo, a.natura, a.dimensione, az.posti_letto, upper(a.provincia) provincia,
             a.regione_eff regione, a.relazione, a.strategicita, a.n_contatti, a.n_conosciuti,
             bc.incluso, bc.probabilita prob_utente, bc.strategia strategia_utente, bc.note, bc.pianificato_il,
             (SELECT count(*) FROM esiti_centro e WHERE e.azienda_id=a.id AND e.esito='vendita')
               + (SELECT count(*) FROM trattative t WHERE t.azienda_id=a.id AND (t.fase='vinta' OR t.esito='vendita')) vendite_precedenti,
             EXISTS (SELECT 1 FROM esiti_centro e JOIN trattative t ON t.id=e.trattativa_id
                     WHERE e.azienda_id=a.id AND t.prodotto_id=%s AND e.esito IN ('rifiuto','scelto altro'))
               OR EXISTS (SELECT 1 FROM trattative t WHERE t.azienda_id=a.id AND t.prodotto_id=%s
                          AND (t.fase='persa' OR t.esito IN ('rifiuto','scelto altro'))) perso_prodotto,
             EXISTS (SELECT 1 FROM esiti_centro e JOIN trattative t ON t.id=e.trattativa_id
                     WHERE e.azienda_id=a.id AND t.prodotto_id=%s AND e.esito='vendita')
               OR EXISTS (SELECT 1 FROM trattative t WHERE t.azienda_id=a.id AND t.prodotto_id=%s
                          AND (t.fase='vinta' OR t.esito='vendita')) venduto_prodotto,
             coalesce((SELECT sum(t.valore_eur) FROM trattative t WHERE t.azienda_id=a.id AND t.prodotto_id=%s
                        AND (t.fase='vinta' OR t.esito='vendita')), 0) valore_trattative_vinte,
             coalesce((SELECT sum(r.quantita*r.prezzo*(1-r.sconto/100)*(1-o.sconto_globale/100))
                       FROM offerte o JOIN offerte_righe r ON r.offerta_id=o.id
                       WHERE o.azienda_id=a.id AND o.stato='accettata' AND r.prodotto_id=%s), 0) valore_offerte_accettate,
             coalesce((SELECT sum(r.quantita*r.prezzo*(1-r.sconto/100)*(1-o.sconto_globale/100))
                       FROM offerte o JOIN offerte_righe r ON r.offerta_id=o.id
                       WHERE o.azienda_id=a.id AND o.stato='inviata' AND r.prodotto_id=%s), 0) valore_offerte_aperte,
             (SELECT count(*) FROM attivita t WHERE t.azienda_id=a.id AND t.stato='da fare'
                AND (t.prodotto_id=%s OR t.trattativa_id=%s)) attivita_aperte
      FROM v_aziende a JOIN aziende az ON az.id = a.id
      LEFT JOIN budget_centri bc ON bc.budget_id=%s AND bc.azienda_id=a.id
      WHERE ({' AND '.join(w)}) OR bc.azienda_id IS NOT NULL
      ORDER BY a.nome"""
    pp = [pid, pid, pid, pid, pid, pid, pid, pid, b["iniziativa_id"], b["id"]] + p
    return conn.execute(sql, pp).fetchall()


def _calcola(conn, b):
    voci_p = _rows(conn.execute("SELECT * FROM prodotti_voci WHERE prodotto_id=%s ORDER BY ordine, id", (b["prodotto_id"],)))
    centri = _centri(conn, b)
    ids = [c["id"] for c in centri]
    cens = {}
    if ids and voci_p:
        for r in conn.execute("""SELECT azienda_id, voce_id, quantita, fonte FROM centri_voci
                                 WHERE azienda_id = ANY(%s) AND voce_id = ANY(%s)""", (ids, [v["id"] for v in voci_p])):
            cens.setdefault(r["azienda_id"], {})[r["voce_id"]] = r
    out = []
    for c in centri:
        c = dict(c)
        val = valore_centro(voci_p, cens.get(c["id"], {}), c["posti_letto"], c["dimensione"], float(b["sconto_medio"] or 0))
        prob, perche = probabilita_centro(c)
        if c["prob_utente"] is not None:
            prob, perche = c["prob_utente"], ["impostata da te"]
        vinto = (c["venduto_prodotto"] or float(c["valore_offerte_accettate"]) > 0)
        venduto = max(float(c["valore_trattative_vinte"]), float(c["valore_offerte_accettate"]))
        if vinto and not venduto:
            venduto = val["valore"]    # venduto senza importo registrato: vale il potenziale stimato
        stato = ("vinto" if vinto else "perso" if c["perso_prodotto"]
                 else "in corso" if (c["attivita_aperte"] or float(c["valore_offerte_aperte"]) > 0) else "da avviare")
        out.append({
            "azienda_id": c["id"], "centro": c["nome"], "tipo": c["tipo"], "natura": c["natura"], "dimensione": c["dimensione"],
            "posti_letto": c["posti_letto"], "provincia": c["provincia"], "regione": c["regione"], "relazione": c["relazione"],
            "n_contatti": c["n_contatti"], "n_conosciuti": c["n_conosciuti"], "gia_cliente": bool(c["vendite_precedenti"]),
            "incluso": c["incluso"] is not False, "voci": val["voci"], "valore_potenziale": val["valore"],
            "margine_potenziale": val["margine"], "affidabilita": val["affidabilita"],
            "probabilita": prob, "perche_probabilita": perche,
            "valore_atteso": round(val["valore"] * prob / 100, 2),
            "strategia_utente": c["strategia_utente"], "note": c["note"],
            "pianificato": c["pianificato_il"] is not None,
            "stato": stato, "venduto": round(venduto, 2), "in_offerta": float(c["valore_offerte_aperte"]),
            "_c": c,
        })
    # fasce A/B/C (Pareto sul valore potenziale dei centri inclusi)
    valutati = sorted([x for x in out if x["incluso"] and x["valore_potenziale"] > 0], key=lambda x: -x["valore_potenziale"])
    tot = sum(x["valore_potenziale"] for x in valutati) or 1
    cum = 0.0
    for x in valutati:
        quota_prima = cum / tot
        cum += x["valore_potenziale"]
        x["fascia"] = "A" if quota_prima < 0.70 else "B" if quota_prima < 0.90 else "C"
    # i centri esclusi ricevono la fascia che avrebbero rispetto alle soglie dei centri inclusi
    soglia = {f: min((x["valore_potenziale"] for x in valutati if x["fascia"] == f), default=None) for f in ("A", "B")}
    for x in out:
        if "fascia" not in x:
            v = x["valore_potenziale"]
            x["fascia"] = ("—" if v <= 0 else "A" if soglia["A"] is not None and v >= soglia["A"]
                           else "B" if soglia["B"] is not None and v >= soglia["B"] else "C")
        prop = strategia_proposta(x["fascia"], x["_c"])
        x["strategia_proposta"] = prop
        x["strategia"] = x["strategia_utente"] or prop
        x["strategia_nome"] = STRATEGIE[x["strategia"]]["nome"]
        x["gara"] = (x["natura"] or "").lower() == "pubblico" and x["strategia"] in ("attacco", "accesso", "sviluppo")
        x["accessibile"] = _accessibile(x.pop("_c"))
    ordine = {"A": 0, "B": 1, "C": 2, "—": 3}
    out.sort(key=lambda x: (not x["incluso"], ordine[x["fascia"]], -x["valore_atteso"], x["centro"]))
    return voci_p, out


def _riepilogo(b, voci_p, centri):
    inc = [c for c in centri if c["incluso"]]
    s = lambda k, arr=inc: round(sum(c[k] for c in arr), 2)
    fasce = {f: {"centri": len(x := [c for c in inc if c["fascia"] == f]), "valore_potenziale": s("valore_potenziale", x),
                 "valore_atteso": s("valore_atteso", x)} for f in ("A", "B", "C", "—")}
    matrice = {f"{'alto' if c_f in ('A', 'B') else 'basso'}_{'accessibile' if acc else 'da_aprire'}": 0
               for c_f in ("A", "C") for acc in (True, False)}
    for c in inc:
        if c["fascia"] == "—":
            continue
        k = f"{'alto' if c['fascia'] in ('A', 'B') else 'basso'}_{'accessibile' if c['accessibile'] else 'da_aprire'}"
        matrice[k] += 1
    stati = {st: len([c for c in inc if c["stato"] == st]) for st in ("da avviare", "in corso", "vinto", "perso")}
    venduto = s("venduto")
    atteso = s("valore_atteso")
    avvisi = []
    if not voci_p:
        avvisi.append(f"Il prodotto non ha voci di prezzo: aggiungile (es. unità monitorate, € per unità) per calcolare il valore dei centri.")
    elif not any(float(v.get("prezzo_unitario") or 0) for v in voci_p):
        avvisi.append("Le voci del prodotto hanno prezzo 0: imposta i prezzi unitari.")
    if fasce["—"]["centri"]:
        avvisi.append(f"{fasce['—']['centri']} centri senza dati sufficienti (posti letto o quantità): strategia «Censire prima».")
    pot = s("valore_potenziale")
    if pot and s("valore_potenziale", [c for c in inc if c["affidabilita"] < 50]) > pot / 2:
        avvisi.append("Più di metà del valore potenziale è stimata: censisci le quantità nei centri di fascia A per un budget affidabile.")
    return {"centri": len(centri), "inclusi": len(inc), "valore_potenziale": pot, "margine_potenziale": s("margine_potenziale"),
            "valore_atteso": atteso, "venduto": venduto, "in_offerta": s("in_offerta"),
            "da_trovare": round(max(0.0, atteso - venduto), 2), "fasce": fasce, "matrice": matrice, "stati": stati,
            "avvisi": avvisi}


def budget(budget_id):
    """Budget strategico completo: voci, centri valutati e ordinati, riepilogo per fascia, verifica."""
    with connect() as conn:
        b = _carica(conn, budget_id)
        voci_p, centri = _calcola(conn, b)
        return {"budget": _clean(b), "voci": voci_p, "riepilogo": _riepilogo(b, voci_p, centri), "centri": centri,
                "strategie": {k: {"nome": v["nome"], "quando": v["quando"]} for k, v in STRATEGIE.items()}}


def elenco_budget():
    with connect() as conn:
        out = []
        for b in conn.execute("SELECT id FROM budget ORDER BY stato='chiuso', anno DESC NULLS LAST, id DESC").fetchall():
            bb = _carica(conn, b["id"])
            voci_p, centri = _calcola(conn, bb)
            r = _riepilogo(bb, voci_p, centri)
            out.append({**_clean(bb), **{k: r[k] for k in ("inclusi", "valore_potenziale", "valore_atteso", "venduto", "in_offerta", "stati")},
                        "fascia_A": r["fasce"]["A"]["centri"]})
        return out


# ---------- piano tattico ----------

def _testo(t, ctx):
    return t.format(**ctx)


def genera_piano_tattico(budget_id, fasce=("A", "B"), data_inizio=None, responsabile="Stefano", centri_a_settimana=3):
    """Crea (o completa) l'iniziativa macro del budget e, per ogni centro incluso delle fasce scelte e non ancora
    pianificato, la sequenza di attività della sua strategia — con un'operazione per ogni voce del prodotto."""
    fasce = [f.strip().upper() for f in (fasce.split(",") if isinstance(fasce, str) else fasce)]
    inizio = date.fromisoformat(str(data_inizio)) if data_inizio else date.today() + timedelta(days=1)
    with transazione() as conn:
        b = _carica(conn, budget_id)
        voci_p, centri = _calcola(conn, b)
        scelti = [c for c in centri if c["incluso"] and c["fascia"] in fasce and not c["pianificato"]
                  and c["stato"] not in ("vinto", "perso")]
        if not scelti:
            raise CRMError("Nessun centro da pianificare nelle fasce scelte (già pianificati, chiusi o esclusi).")
        if not b["iniziativa_id"]:
            storia = (f"Piano tattico del budget «{b['titolo']}»: {len([c for c in centri if c['incluso']])} centri valutati, "
                      f"valore potenziale {_eur(sum(c['valore_potenziale'] for c in centri if c['incluso']))}. "
                      "Ogni centro ha la sua strategia (attacco diretto, costruire l'accesso, sviluppo, presidio) "
                      "e le operazioni sulle voci del prodotto.")
            ini = core.crea_campagna(f"Budget {b['anno'] or ''} · {b['titolo']}".replace("  ", " "), prodotto=str(b["prodotto_id"]),
                                     obiettivo=str(b["obiettivo_id"]) if b["obiettivo_id"] else None, storia=storia,
                                     target={"regioni": b["regioni"], "province": b["province"], "tipi": b["tipi"]},
                                     data_inizio=inizio.isoformat(), genere="commerciale")
            conn.execute("UPDATE budget SET iniziativa_id=%s, stato='approvato', aggiornato_il=now() WHERE id=%s", (ini["id"], b["id"]))
            iniziativa_id = ini["id"]
        else:
            iniziativa_id = b["iniziativa_id"]
        creati, per_fascia = [], {}
        for c in scelti:
            n = per_fascia.get(c["fascia"], 0); per_fascia[c["fascia"]] = n + 1
            base = inizio + timedelta(days=RITARDO_FASCIA.get(c["fascia"], 0) + (n // max(1, int(centri_a_settimana))) * 7)
            ct = conn.execute("""SELECT id FROM contatti WHERE azienda_id=%s
                                 ORDER BY conosciuto_personalmente DESC, id LIMIT 1""", (c["azienda_id"],)).fetchone()
            dettaglio = ", ".join(f"{_q(v['quantita'])} {v['voce']}" + (" (stima)" if v["fonte"].startswith("stimata") else "")
                                  for v in c["voci"] if v["quantita"]) or "quantità da censire"
            ctx = {"prodotto": b["prodotto"], "valore": _eur(c["valore_potenziale"]), "dettaglio": dettaglio,
                   "voci_elenco": ", ".join(v["nome"] for v in voci_p) or "le quantità"}
            passi = list(STRATEGIE[c["strategia"]]["passi"]) + ([PASSO_GARA] if c["gara"] else [])
            ids = []
            for codice, tipo, giorni, testo in passi:
                quando = (base + timedelta(days=giorni)).isoformat() + "T09:00"
                if testo == "{voci}":   # un'operazione per voce: verificare/censire lo strumento
                    for v in c["voci"]:
                        stato_q = (f"oggi {_q(v['quantita'])} {v['unita'] or ''}, {v['fonte']}" if v["quantita"] is not None
                                   else "dato mancante")
                        a = core.inserisci_attivita(conn, f"{v['voce']}: verificare quantità e situazione nel centro ({stato_q})",
                                                    tipo, quando, PRIORITA_FASCIA.get(c["fascia"], "media"), c["azienda_id"],
                                                    ct["id"] if ct else None, iniziativa_id, b["prodotto_id"], codice, None, responsabile)
                        conn.execute("UPDATE attivita SET voce_id=%s WHERE id=%s", (v["voce_id"], a["id"]))
                        ids.append(a["id"])
                    continue
                a = core.inserisci_attivita(conn, _testo(testo, ctx), tipo, quando, PRIORITA_FASCIA.get(c["fascia"], "media"),
                                            c["azienda_id"], ct["id"] if ct else None, iniziativa_id, b["prodotto_id"],
                                            codice, None, responsabile)
                ids.append(a["id"])
            conn.execute("""INSERT INTO budget_centri (budget_id, azienda_id, pianificato_il) VALUES (%s,%s,now())
                            ON CONFLICT (budget_id, azienda_id) DO UPDATE SET pianificato_il=now()""", (b["id"], c["azienda_id"]))
            creati.append({"centro": c["centro"], "fascia": c["fascia"], "strategia": c["strategia_nome"], "attivita": len(ids),
                           "dal": base.isoformat()})
        atteso = sum(c["valore_atteso"] for c in centri if c["incluso"])
        conn.execute("UPDATE trattative SET valore_eur=%s, aggiornata_il=now() WHERE id=%s", (round(atteso, 2), iniziativa_id))
        return {"iniziativa_id": iniziativa_id, "centri_pianificati": len(creati),
                "attivita_create": sum(x["attivita"] for x in creati), "dettaglio": creati}

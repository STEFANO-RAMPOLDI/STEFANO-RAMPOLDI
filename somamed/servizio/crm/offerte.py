"""Offerte economiche: righe con prodotti, sconti e IVA, totali e margine, condizioni, revisioni,
invio (con attività e follow-up) ed esito (vendita o rifiuto sul centro dell'iniziativa)."""
from datetime import date, timedelta
from . import core
from .core import connect, transazione, _rows, _clean, CRMError, risolvi_azienda, risolvi_contatto, risolvi_trattativa

STATI = ("bozza", "inviata", "accettata", "rifiutata", "annullata", "superata")
CAMPI = {"oggetto", "premessa", "data", "validita_giorni", "pagamento", "consegna", "garanzia", "note",
         "sconto_globale", "azienda_id", "contatto_id", "trattativa_id", "responsabile"}


def _n(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def calcola(righe, sconto_globale=0):
    """Totali dell'offerta: stesse regole dell'interfaccia (calcolaOfferta in index.html)."""
    imp = iva = costo = 0.0
    out = []
    for r in righe:
        riga = round(_n(r.get("quantita"), 1) * _n(r.get("prezzo")) * (1 - _n(r.get("sconto")) / 100), 2)
        out.append({**r, "importo": riga})
        imp += riga
        iva += riga * (1 - _n(sconto_globale) / 100) * _n(r.get("aliquota_iva"), 22) / 100
        costo += _n(r.get("quantita"), 1) * _n(r.get("costo"))
    imp_netto = round(imp * (1 - _n(sconto_globale) / 100), 2)
    return {"righe": out, "lordo": round(imp, 2), "imponibile": imp_netto, "iva": round(iva, 2),
            "totale": round(imp_netto + iva, 2), "costo_totale": round(costo, 2),
            "margine": round(imp_netto - costo, 2) if costo else None,
            "margine_pct": round((imp_netto - costo) / imp_netto * 100, 1) if costo and imp_netto else None}


def _numero(conn):
    anno = date.today().year
    n = conn.execute("SELECT count(DISTINCT numero) n FROM offerte WHERE numero LIKE %s", (f"OFF-{anno}-%",)).fetchone()["n"]
    return f"OFF-{anno}-{n + 1:03d}"


def _salva_righe(conn, oid, righe, sconto_globale):
    conn.execute("DELETE FROM offerte_righe WHERE offerta_id=%s", (oid,))
    for i, r in enumerate(righe or []):
        pid = r.get("prodotto_id") or None
        if not pid and r.get("prodotto"):
            pid = core.risolvi_prodotto(conn, r["prodotto"])
        p = _clean(conn.execute("SELECT * FROM prodotti WHERE id=%s", (pid,)).fetchone()) if pid else {}
        conn.execute(
            """INSERT INTO offerte_righe (offerta_id, ordine, prodotto_id, descrizione, quantita, unita, prezzo, sconto, aliquota_iva, costo)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (oid, i, pid, r.get("descrizione") or p.get("nome") or "Voce", _n(r.get("quantita"), 1),
             r.get("unita") or p.get("unita") or "pz", _n(r.get("prezzo"), _n(p.get("prezzo_listino"))), _n(r.get("sconto")),
             _n(r.get("aliquota_iva"), _n(p.get("aliquota_iva"), 22)),
             r.get("costo") if r.get("costo") not in (None, "") else p.get("costo")))
    righe_db = _rows(conn.execute("SELECT * FROM offerte_righe WHERE offerta_id=%s ORDER BY ordine", (oid,)))
    t = calcola(righe_db, sconto_globale)
    conn.execute("""UPDATE offerte SET imponibile=%s, iva=%s, totale=%s, costo_totale=%s, aggiornata_il=now() WHERE id=%s""",
                 (t["imponibile"], t["iva"], t["totale"], t["costo_totale"], oid))


def crea_offerta(oggetto, azienda=None, contatto=None, iniziativa=None, righe=None, premessa=None,
                 validita_giorni=60, pagamento=None, consegna=None, garanzia=None, note=None, sconto_globale=0,
                 responsabile=None):
    """Nuova offerta in bozza. righe: [{prodotto o prodotto_id, descrizione, quantita, prezzo, sconto, aliquota_iva, costo}].
    Se manca il prezzo si usa il listino del prodotto."""
    with transazione() as conn:   # testata e righe: tutto o niente
        tid = risolvi_trattativa(conn, iniziativa) if iniziativa else None
        t = _clean(conn.execute("SELECT azienda_id, contatto_id, prodotto_id FROM trattative WHERE id=%s", (tid,)).fetchone()) if tid else {}
        az = (int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda)) if azienda else t.get("azienda_id")
        ct = (int(contatto) if str(contatto).isdigit() else risolvi_contatto(conn, contatto, az)) if contatto else t.get("contatto_id")
        if not righe and t.get("prodotto_id"):
            righe = [{"prodotto_id": t["prodotto_id"]}]
        cols = {"numero": _numero(conn), "oggetto": oggetto, "premessa": premessa, "azienda_id": az, "contatto_id": ct,
                "trattativa_id": tid, "validita_giorni": validita_giorni or 60, "note": note, "sconto_globale": sconto_globale or 0,
                "responsabile": responsabile}
        for k, v in (("pagamento", pagamento), ("consegna", consegna), ("garanzia", garanzia)):
            if v:
                cols[k] = v
        r = conn.execute(f"INSERT INTO offerte ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                         list(cols.values())).fetchone()
        _salva_righe(conn, r["id"], righe or [], sconto_globale or 0)
    return offerta(r["id"])


def aggiorna_offerta(oid, campi=None, righe=None):
    """Modifica testata e/o righe di un'offerta in bozza."""
    with transazione() as conn:   # testata e righe: tutto o niente
        o = conn.execute("SELECT stato, sconto_globale FROM offerte WHERE id=%s", (int(oid),)).fetchone()
        if not o:
            raise CRMError(f"Offerta {oid} non trovata.")
        if o["stato"] != "bozza":
            raise CRMError("L'offerta non è più in bozza: crea una revisione per modificarla.")
        c = {k: (v if v != "" else None) for k, v in (campi or {}).items() if k in CAMPI}
        if c:
            conn.execute(f"UPDATE offerte SET {', '.join(f'{k}=%s' for k in c)}, aggiornata_il=now() WHERE id=%s",
                         list(c.values()) + [int(oid)])
        sg = c.get("sconto_globale", o["sconto_globale"]) or 0
        if righe is not None:
            _salva_righe(conn, int(oid), righe, sg)
        elif "sconto_globale" in c:
            _salva_righe(conn, int(oid), _rows(conn.execute("SELECT * FROM offerte_righe WHERE offerta_id=%s ORDER BY ordine", (int(oid),))), sg)
    return offerta(oid)


def offerta(oid):
    with connect() as conn:
        o = _clean(conn.execute(
            """SELECT o.*, a.nome azienda, a.citta, a.indirizzo, a.cap, upper(a.provincia) provincia,
                      trim(coalesce(c.nome,'')||' '||coalesce(c.cognome,'')) contatto, c.ruolo, c.email,
                      t.titolo trattativa, t.genere,
                      (o.data + o.validita_giorni) AS valida_fino
               FROM offerte o LEFT JOIN aziende a ON a.id=o.azienda_id LEFT JOIN contatti c ON c.id=o.contatto_id
               LEFT JOIN trattative t ON t.id=o.trattativa_id WHERE o.id=%s""", (int(oid),)).fetchone())
        if not o:
            raise CRMError(f"Offerta {oid} non trovata.")
        righe = _rows(conn.execute(
            """SELECT r.*, p.nome prodotto FROM offerte_righe r LEFT JOIN prodotti p ON p.id=r.prodotto_id
               WHERE offerta_id=%s ORDER BY ordine""", (int(oid),)))
        versioni = _rows(conn.execute("SELECT id, revisione, stato, data, totale FROM offerte WHERE numero=%s ORDER BY revisione",
                                      (o["numero"],)))
    t = calcola(righe, o.get("sconto_globale") or 0)
    o["righe"] = t["righe"]
    o.update({k: t[k] for k in ("lordo", "margine", "margine_pct")})
    o["versioni"] = versioni
    o["scaduta"] = o["stato"] == "inviata" and o.get("valida_fino") and str(o["valida_fino"]) < date.today().isoformat()
    o["sigla"] = o["numero"] + (f" rev.{o['revisione']}" if o.get("revisione") else "")
    return o


def elenco_offerte(stato=None, azienda=None, iniziativa=None, q=None):
    with connect() as conn:
        w, p = ["true"], []
        if stato == "aperte":
            w.append("o.stato IN ('bozza','inviata')")
        elif stato:
            w.append("o.stato=%s"); p.append(stato)
        if azienda:
            w.append("o.azienda_id=%s"); p.append(int(azienda) if str(azienda).isdigit() else risolvi_azienda(conn, azienda))
        if iniziativa:
            w.append("o.trattativa_id=%s"); p.append(risolvi_trattativa(conn, iniziativa))
        if q:
            w.append("(o.oggetto ILIKE '%%'||%s||'%%' OR a.nome ILIKE '%%'||%s||'%%' OR o.numero ILIKE '%%'||%s||'%%')"); p += [q, q, q]
        return _rows(conn.execute(
            f"""SELECT o.id, o.numero, o.revisione, o.stato, o.data, o.oggetto, o.imponibile, o.totale, o.costo_totale,
                       (o.data + o.validita_giorni) valida_fino, o.inviata_il, o.azienda_id, a.nome azienda, o.contatto_id,
                       trim(coalesce(c.nome,'')||' '||coalesce(c.cognome,'')) contatto, o.trattativa_id, t.titolo trattativa,
                       (o.stato='inviata' AND o.data + o.validita_giorni < current_date) scaduta
                FROM offerte o LEFT JOIN aziende a ON a.id=o.azienda_id LEFT JOIN contatti c ON c.id=o.contatto_id
                LEFT JOIN trattative t ON t.id=o.trattativa_id
                WHERE {' AND '.join(w)} AND o.stato <> 'superata' ORDER BY o.data DESC, o.id DESC""", p))


def cambia_stato(oid, stato, note=None, concorrente=None, giorni_followup=7):
    """inviata: registra l'invio (attività Offerta fatta) e fissa il follow-up; accettata: vendita sul centro
    dell'iniziativa; rifiutata: rifiuto (o scelto altro se c'è il concorrente); annullata."""
    if stato not in ("inviata", "accettata", "rifiutata", "annullata"):
        raise CRMError("Stato: inviata, accettata, rifiutata, annullata.")
    o = offerta(oid)
    with transazione() as conn:   # testata e righe: tutto o niente
        if stato == "inviata":
            conn.execute("UPDATE offerte SET stato='inviata', inviata_il=current_date, aggiornata_il=now() WHERE id=%s", (o["id"],))
            if o.get("trattativa_id") and o.get("azienda_id"):
                conn.execute("""UPDATE trattative SET valore_eur=%s, fase=CASE WHEN coalesce(fase,'') IN ('vinta','persa') THEN fase ELSE 'offerta' END
                                WHERE id=%s AND (azienda_id=%s OR azienda_id IS NULL)""", (o["imponibile"], o["trattativa_id"], o["azienda_id"]))
            a = core.inserisci_attivita(conn, f"Inviata offerta {o['sigla']}: {o['oggetto']} ({o['imponibile']:,.0f} € + IVA)".replace(",", "."),
                                        "email", date.today().isoformat(), "media", o.get("azienda_id"), o.get("contatto_id"),
                                        o.get("trattativa_id"), None, "STD-070", None, o.get("responsabile") or "Stefano")
            aid = a.get("id") if isinstance(a, dict) else None
            if aid:
                conn.execute("UPDATE attivita SET stato='fatta', completata_il=now() WHERE id=%s", (aid,))
            core.inserisci_attivita(conn, f"Follow-up offerta {o['sigla']}", "chiamata",
                                    (date.today() + timedelta(days=int(giorni_followup or 7))).isoformat() + " 09:00", "alta",
                                    o.get("azienda_id"), o.get("contatto_id"), o.get("trattativa_id"), None, "STD-080", aid,
                                    o.get("responsabile") or "Stefano")
        else:
            conn.execute("""UPDATE offerte SET stato=%s, chiusa_il=current_date, esito_note=%s, concorrente=%s, aggiornata_il=now()
                            WHERE id=%s""", (stato, note, concorrente, o["id"]))
            # le attività di follow-up ancora aperte di questa offerta non servono più
            conn.execute("""UPDATE attivita SET stato='fatta', completata_il=now(), esito=%s
                            WHERE stato='da fare' AND codice_standard='STD-080' AND descrizione LIKE %s""",
                         (f"Offerta {stato}", f"Follow-up offerta {o['numero']}%"))
    if stato in ("accettata", "rifiutata") and o.get("trattativa_id") and o.get("azienda_id"):
        esito = "vendita" if stato == "accettata" else ("scelto altro" if concorrente else "rifiuto")
        try:
            core.registra_esito(str(o["trattativa_id"]), str(o["azienda_id"]), esito, concorrente,
                                note or f"Offerta {o['sigla']} {stato}")
        except CRMError:
            pass
    return offerta(oid)


def revisione(oid):
    """Nuova revisione modificabile (copia di righe e condizioni); la precedente diventa 'superata'."""
    o = offerta(oid)
    with transazione() as conn:   # testata e righe: tutto o niente
        n = conn.execute("SELECT max(revisione) m FROM offerte WHERE numero=%s", (o["numero"],)).fetchone()["m"] + 1
        r = conn.execute(
            """INSERT INTO offerte (numero, revisione, origine_id, oggetto, premessa, azienda_id, contatto_id, trattativa_id,
                                    validita_giorni, pagamento, consegna, garanzia, note, sconto_globale, responsabile)
               SELECT numero, %s, id, oggetto, premessa, azienda_id, contatto_id, trattativa_id, validita_giorni,
                      pagamento, consegna, garanzia, note, sconto_globale, responsabile FROM offerte WHERE id=%s RETURNING id""",
            (n, o["id"])).fetchone()
        if o["stato"] in ("bozza", "inviata"):
            conn.execute("UPDATE offerte SET stato='superata' WHERE id=%s", (o["id"],))
        _salva_righe(conn, r["id"], [{k: x.get(k) for k in ("prodotto_id", "descrizione", "quantita", "unita", "prezzo", "sconto",
                                                         "aliquota_iva", "costo")} for x in o["righe"]], o.get("sconto_globale") or 0)
    return offerta(r["id"])


def _minuscola(t):
    # solo la prima lettera, e solo se la seconda non è maiuscola (es. "RM", "IT" restano)
    return t[:1].lower() + t[1:] if len(t) > 1 and not t[1].isupper() else t


def premessa_base(o):
    """Lettera di accompagnamento di base (Claude può riscriverla)."""
    nome = (o.get("contatto") or "").split(" ")[0]
    return (f"Gentile {nome or 'Cliente'},\n\nfacendo seguito ai nostri colloqui, Le inviamo la nostra migliore offerta per "
            f"{_minuscola((o.get('oggetto') or '').strip().rstrip('.'))}. Restiamo a disposizione per ogni chiarimento e per "
            "concordare insieme i tempi di avvio.\n\nCordiali saluti,\nStefano Rampoldi\nSomaMed S.r.l.")

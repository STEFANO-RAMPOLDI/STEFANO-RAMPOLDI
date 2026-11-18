"""Gestione dei dati, separata dall'interfaccia: stato del database, esportazione completa,
cancellazione dei dati di prova o di tutti i dati di lavoro."""
import json
from datetime import datetime
from .core import connect, transazione, _rows, CRMError

# tabelle con i dati di lavoro (le tabelle di riferimento — regioni, province, catalogo
# delle attività, prodotti, divisioni, utenti — restano)
LAVORO = ["offerte_righe", "offerte", "piano_giorni", "allerte", "esiti_centro", "diario", "note", "attivita", "relazioni_contatti",
          "trattative", "obiettivi", "contatti", "aziende"]
TUTTE = LAVORO + ["prodotti", "utenti", "divisioni", "catalogo_attivita"]

# nomi dei dati inventati usati per le prove e le anteprime
CENTRI_PROVA = ["ASST Valle Olona", "Azienda Ospedaliera Euganea", "Azienda Ospedaliera di Padova", "Casa di Cura Santa Lucia", "Centro Diagnostico Adige", "Centro Diagnostico Emilia", "Centro Medico Lario", "Centro Prova Piano", "Clinica Mediterranea", "Clinica Villa Aurora", "GVM Care & Research", "Gruppo Lifenet", "Gruppo Salus Nord", "Laboratorio Analisi Brianza", "Lifenet", "Ospedale Maggiore del Piemonte", "Ospedale San Martino Brianza", "Policlinico Città di Bergamo", "Policlinico Gemelli", "Policlinico Tiberino", "RSA Il Glicine", "RSA San Giuseppe", "Spedali Civili di Brescia"]
# nomi reali usati anche nelle prove: proposti ma NON selezionati, potrebbero essere centri veri
REALI = {"Gruppo Lifenet", "Lifenet", "Spedali Civili di Brescia", "GVM Care & Research", "Policlinico Gemelli",
         "Azienda Ospedaliera di Padova"}
OBIETTIVI_PROVA = ["Asimily in 10 ospedali del Nord entro giugno 2027", "Asimily Lombardia: 6 ospedali",
                   "Asimily Piemonte e Veneto: 4 ospedali", "ReDots: 120.000 € di contratti nel 2027",
                   "Schermature RM: 600.000 € nel 2027", "Schermature RM Lombardia", "Schermature RM Veneto"]


def stato():
    with connect() as conn:
        v = conn.execute("SELECT version() v").fetchone()["v"]
        mig = [r["file"] for r in conn.execute("SELECT file FROM versioni_schema ORDER BY file").fetchall()]
        conteggi = conn.execute("SELECT " + ", ".join(f"(SELECT count(*) FROM {t}) AS {t}" for t in TUTTE)).fetchone()
    return {"database": v.split(",")[0], "aggiornamenti": mig, "conteggi": dict(conteggi), "candidati_prova": candidati_prova()}


def candidati_prova():
    """Centri che sembrano inventati per le prove, da confermare uno per uno prima di cancellarli."""
    with connect() as conn:
        return _rows(conn.execute(
            """SELECT a.id, a.nome, a.citta, (SELECT count(*) FROM contatti c WHERE c.azienda_id=a.id) persone,
                      (SELECT count(*) FROM attivita t WHERE t.azienda_id=a.id) attivita,
                      NOT (a.nome = ANY(%s)) AS proposto
               FROM aziende a WHERE a.nome = ANY(%s)
                  OR a.id IN (SELECT azienda_id FROM contatti WHERE email ILIKE '%%@demo.it')
               ORDER BY proposto DESC, a.nome""", (list(REALI), CENTRI_PROVA)))


def esporta():
    """Tutti i dati in un unico JSON (senza i vettori semantici, che si ricalcolano)."""
    out = {"esportato_il": datetime.now().isoformat(timespec="seconds"), "tabelle": {}}
    with connect() as conn:
        for t in TUTTE:
            righe = _rows(conn.execute(f"SELECT * FROM {t}"))
            for r in righe:
                r.pop("embedding", None)
            out["tabelle"][t] = righe
    return out


def svuota(cosa="prova", conferma="", centri=None):
    """cosa='prova': cancella i centri, le persone, le iniziative, gli obiettivi e le attività inventati per le prove.
    cosa='tutto': cancella tutti i dati di lavoro (restano prodotti, utenti, catalogo, regioni e province).
    Serve conferma='CANCELLA'."""
    if conferma != "CANCELLA":
        raise CRMError("Per sicurezza scrivi CANCELLA nel campo di conferma.")
    with transazione() as conn:   # cancellazione completa o nessuna
        if cosa == "tutto":
            conn.execute("TRUNCATE " + ", ".join(LAVORO) + " RESTART IDENTITY CASCADE")
            return {"cancellato": "tutti i dati di lavoro"}
        if cosa != "prova":
            raise CRMError("Scegli: prova oppure tutto.")
        if centri is None:   # senza scelta esplicita: solo quelli sicuramente inventati
            centri = [c["id"] for c in candidati_prova() if c["proposto"]]
        az = [int(x) for x in centri]
        ct = [r["id"] for r in conn.execute("SELECT id FROM contatti WHERE azienda_id = ANY(%s)", (az,)).fetchall()]
        tr = [r["id"] for r in conn.execute(
            """SELECT id FROM trattative WHERE azienda_id = ANY(%s)
               OR (obiettivo_id IN (SELECT id FROM obiettivi WHERE titolo = ANY(%s)) AND %s)
               OR id IN (SELECT trattativa_id FROM attivita WHERE azienda_id = ANY(%s) OR contatto_id = ANY(%s))""",
            (az, OBIETTIVI_PROVA, bool(az), az, ct)).fetchall()]
        n = {}
        n["offerte"] = conn.execute("DELETE FROM offerte WHERE azienda_id = ANY(%s) OR trattativa_id = ANY(%s)", (az, tr)).rowcount
        n["attività"] = conn.execute("DELETE FROM attivita WHERE azienda_id = ANY(%s) OR contatto_id = ANY(%s) OR trattativa_id = ANY(%s)",
                                     (az, ct, tr)).rowcount
        n["note e diario"] = conn.execute("DELETE FROM note WHERE azienda_id = ANY(%s) OR contatto_id = ANY(%s) OR trattativa_id = ANY(%s)",
                                          (az, ct, tr)).rowcount
        n["note e diario"] += conn.execute("DELETE FROM diario WHERE azienda_id = ANY(%s) OR contatto_id = ANY(%s)", (az, ct)).rowcount
        n["allerte"] = conn.execute("DELETE FROM allerte WHERE azienda_id = ANY(%s) OR contatto_id = ANY(%s) OR trattativa_id = ANY(%s)",
                                    (az, ct, tr)).rowcount
        n["iniziative"] = conn.execute("DELETE FROM trattative WHERE id = ANY(%s)", (tr,)).rowcount
        n["obiettivi"] = conn.execute("""DELETE FROM obiettivi WHERE titolo = ANY(%s)
                                         AND NOT EXISTS (SELECT 1 FROM trattative t WHERE t.obiettivo_id=obiettivi.id)""",
                                      (OBIETTIVI_PROVA,)).rowcount
        conn.execute("DELETE FROM relazioni_contatti WHERE contatto_a = ANY(%s) OR contatto_b = ANY(%s)", (ct, ct))
        n["persone"] = conn.execute("DELETE FROM contatti WHERE id = ANY(%s)", (ct,)).rowcount
        n["centri"] = conn.execute("DELETE FROM aziende WHERE id = ANY(%s)", (az,)).rowcount
        return {"cancellato": n}


if __name__ == "__main__":
    import sys
    cosa = sys.argv[1] if len(sys.argv) > 1 else "prova"
    if cosa == "prova":
        cand = candidati_prova()
        print("Centri di prova trovati:")
        for c in cand:
            print(f"  [{'x' if c['proposto'] else ' '}] {c['nome']} ({c['persone']} persone, {c['attivita']} attività)")
        print("Cancello solo quelli segnati [x]; quelli con nome reale si cancellano dall'interfaccia (Strumenti → Dati e collegamento).")
    print(json.dumps(svuota(cosa, "CANCELLA"), ensure_ascii=False, indent=2))

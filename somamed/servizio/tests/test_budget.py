"""Collaudo del budget strategico: voci del prodotto → censimento → valore dei centri → fasce → piano tattico → verifica."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import guardia  # noqa
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import json
from crm import core, budget as bg

core.migra()
P = "Prodotto collaudo budget"
core.crea_prodotto(P, "Asimily", "Asimily", tipologie_clienti=["ospedale pubblico", "ospedale privato"])
v1 = bg.salva_voce(P, "Dispositivi medicali connessi", unita="dispositivo", prezzo_unitario=40, costo_unitario=15,
                   ricorrente=True, anni=3, stima_per_posto_letto=2.5)
v2 = bg.salva_voce(P, "Installazione appliance", unita="sito", prezzo_unitario=8000, costo_unitario=3000, quantita_fissa=1)
assert v1["ricorrente"] and float(v1["stima_per_posto_letto"]) == 2.5, v1

# centri di prova (regione inventata per isolare il collaudo)
R = "Lombardia"
grande = core.crea_azienda("BG Ospedale Grande Prova", "ospedale pubblico", regione=R, provincia="MI", natura="pubblico", dimensione="grande")
medio = core.crea_azienda("BG Clinica Media Prova", "ospedale privato", regione=R, provincia="BG", natura="privato", dimensione="medio")
piccolo = core.crea_azienda("BG Ospedale Piccolo Prova", "ospedale privato", regione=R, provincia="CO", natura="privato", dimensione="piccolo")
ignoto = core.crea_azienda("BG Centro Senza Dati Prova", "ospedale privato", regione=R, provincia="VA")
core.crea_azienda("BG Distributore Prova", "distributore", regione=R)        # escluso: non è un cliente finale
bg.imposta_posti_letto(medio["id"], 300)
bg.censisci(grande["id"], v1["id"], 2200, "censita")                      # censimento vero sul grande
c = core.crea_contatto("Paola", "Conosciuta", azienda="BG Clinica Media Prova", ruolo="Ingegnere clinico",
                       conosciuto_personalmente=True)

b = bg.crea_budget("Asimily Lombardia 2027", P, anno=2027, regioni=R, sconto_medio=10)
d = bg.budget(b["budget"]["id"])
cent = {x["centro"]: x for x in d["centri"]}
print(json.dumps(d["riepilogo"], ensure_ascii=False, indent=1)[:900])
assert "BG Distributore Prova" not in cent, "i distributori non vanno nel budget"
g, m, p, n = (cent[k] for k in ("BG Ospedale Grande Prova", "BG Clinica Media Prova", "BG Ospedale Piccolo Prova", "BG Centro Senza Dati Prova"))
# grande: 2200 censiti × 40 € × 3 anni × 0,9 + 8000 × 0,9
assert abs(g["valore_potenziale"] - (2200 * 40 * 3 * 0.9 + 8000 * 0.9)) < 1, g["valore_potenziale"]
assert g["voci"][0]["fonte"] == "censita" and m["voci"][0]["fonte"].startswith("stimata da posti letto")
assert m["voci"][0]["quantita"] == 750, m["voci"]                        # 300 posti letto × 2,5
assert p["voci"][0]["fonte"] == "stimata da dimensione"                  # 80 posti × 2,5
assert n["fascia"] == "—" or n["valore_potenziale"] == 8000 * 0.9         # senza dati: solo l'installazione fissa
assert g["fascia"] == "A" and g["strategia"] == "accesso" and g["gara"], g   # alto valore, nessun accesso, pubblico
assert m["probabilita"] > g["probabilita"], (m["probabilita"], g["probabilita"])   # persona conosciuta
assert g["margine_potenziale"] < g["valore_potenziale"]

# scelte dell'utente: escludo il piccolo, alzo la probabilità del grande
bg.imposta_centro(b["budget"]["id"], p["azienda_id"], incluso=False)
bg.imposta_centro(b["budget"]["id"], g["azienda_id"], probabilita=40, strategia="attacco")
d = bg.budget(b["budget"]["id"])
cent = {x["centro"]: x for x in d["centri"]}
assert not cent["BG Ospedale Piccolo Prova"]["incluso"]
assert cent["BG Ospedale Grande Prova"]["probabilita"] == 40 and cent["BG Ospedale Grande Prova"]["strategia"] == "attacco"

# piano tattico sulle fasce A e B
t = bg.genera_piano_tattico(b["budget"]["id"], "A,B", "2027-01-11", centri_a_settimana=2)
print(json.dumps(t, ensure_ascii=False))
assert t["centri_pianificati"] >= 1 and t["attivita_create"] >= 4, t
with core.connect() as conn:
    att = conn.execute("""SELECT a.descrizione, a.codice_standard, a.voce_id, a.scadenza::date d, a.priorita
                          FROM attivita a WHERE trattativa_id=%s AND azienda_id=%s ORDER BY scadenza, id""",
                       (t["iniziativa_id"], g["azienda_id"])).fetchall()
for a in att:
    print("  ", a["d"], a["codice_standard"], a["priorita"], a["voce_id"] or "", a["descrizione"][:90])
assert any(a["voce_id"] == v1["id"] for a in att), "manca l'operazione sulla voce"
assert any(a["codice_standard"] == "STD-100" for a in att), "manca il passo di gara per il pubblico"
# rigenerare non duplica
try:
    bg.genera_piano_tattico(b["budget"]["id"], "A,B")
    raise AssertionError("doveva rifiutare: tutti già pianificati")
except core.CRMError:
    pass

# verifica: vendita registrata sul grande → venduto
core.registra_esito(str(t["iniziativa_id"]), g["azienda_id"], "vendita")
d = bg.budget(b["budget"]["id"])
cent = {x["centro"]: x for x in d["centri"]}
assert cent["BG Ospedale Grande Prova"]["stato"] == "vinto" and d["riepilogo"]["venduto"] > 0, d["riepilogo"]
assert cent["BG Clinica Media Prova"]["stato"] == "in corso"
print("riepilogo finale:", {k: d["riepilogo"][k] for k in ("valore_potenziale", "valore_atteso", "venduto", "stati")})
print("elenco:", [(x["titolo"], x["valore_atteso"]) for x in bg.elenco_budget()])
print("COLLAUDO BUDGET OK")

"""Collaudo del piano del giorno (database di prova)."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import guardia  # noqa
from datetime import date, timedelta
from crm import core, piano

core.migra()
a = core.crea_attivita("Chiamare per fissare la demo", "chiamata", (date.today() - timedelta(days=1)).isoformat(),
                       "alta", "Centro Prova Piano", None, None, attivita_standard="STD-020")
b = core.crea_attivita("Mandare la presentazione", "email", date.today().isoformat(), "media", "Centro Prova Piano",
                       attivita_standard="STD-030")
p = piano.piano_giorno(ore=1)
ids = [v["id"] for v in p["voci"]]
aid = a.get("id") or a["attivita"]["id"]
assert aid in ids, ids
v = next(v for v in p["voci"] if v["id"] == aid)
assert "scaduta" in " ".join(v["motivi"]) and v["preparazione"].startswith("OBIETTIVO")
piano.salva_preparazione(aid, "Traccia scritta da Claude")
assert next(x for x in piano.piano_giorno(ore=1)["voci"] if x["id"] == aid)["preparazione_ai"]
r = piano.registra_resoconto(aid, "fatta", "Demo fissata per giovedì", "Mandare l'agenda prima", "STD-040", 3)
assert r.get("prossima")
assert any(s["tipo"] == "idea" for s in piano.suggerimenti_processo())
bid = b.get("id") or b["attivita"]["id"]
r = piano.registra_resoconto(bid, "non risponde", data=(date.today()+timedelta(days=5)).isoformat())
assert r["nuova_data"] == (date.today()+timedelta(days=5)).isoformat()
try:
    piano.registra_resoconto(bid, "annullata"); assert False, "annulla senza motivo"
except core.CRMError:
    pass
c = piano.calendario(date.today().isoformat(), (date.today()+timedelta(days=10)).isoformat())
assert any(x["id"] == bid for x in c["attivita"])
piano.sposta(bid, (date.today()+timedelta(days=3)).isoformat() + " 15:30")
assert "BEGIN:VEVENT" in piano.ics(date.today().isoformat(), (date.today()+timedelta(days=10)).isoformat())
from crm import pianifica
ob = core.crea_obiettivo("Prova piano misurabile", None, "2027-12-31", 300000, "budget")
p = pianifica.piano_obiettivo(str(ob["id"]))
assert p["risposte"]["ricavo"] == 300000 and len(p["domande"]) >= 15
s = pianifica.salva_piano(str(ob["id"]), {**p["risposte"], "valore_medio": 30000, "conv_contatto": 25}, "Commento di prova", True)
c = s["calcolo"]
assert c["vendite"] == 10 and c["contatti"] >= c["presentazioni"] >= c["offerte"] >= c["vendite"]
assert pianifica.piano_obiettivo(str(ob["id"]))["indicazioni_ai"] == "Commento di prova"
print("COLLAUDO PIANO OK")

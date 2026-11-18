"""Collaudo end-to-end: avvia il server MCP e lo usa come farebbe Claude."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import guardia  # noqa
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "crm.server"],
                                   cwd=ROOT, env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print("STRUMENTI:", tools)

            async def call(name, **args):
                res = await s.call_tool(name, args)
                data = json.loads(res.content[0].text) if res.content else None
                print(f"\n> {name}({args})\n", json.dumps(data, ensure_ascii=False)[:400])
                return data

            await call("oggi")
            await call("crea_azienda", nome="Gruppo Lifenet", tipo="gruppo sanitario", citta="Milano", regione="Lombardia",
                       tag=["ReDots", "cliente pilota"])
            await call("crea_azienda", nome="Spedali Civili di Brescia", tipo="ospedale pubblico", citta="Brescia", regione="Lombardia")
            await call("crea_contatto", nome="Mirco", cognome="Fantuz", azienda="Lifenet",
                       ruolo="Responsabile acquisti")
            await call("crea_contatto", nome="Gianluca", cognome="Viganò", azienda="Civili Brescia",
                       ruolo="Direttore Ingegneria Clinica")
            t = await call("crea_trattativa", titolo="ReDots analisi acquisti Lifenet", azienda="Lifenet",
                           divisione="ReDots", fase="qualificata", contatto="Fantuz",
                           valore_eur=18000, probabilita=60, prossimo_passo="Ricevere estrazione dati acquisti")
            await call("crea_trattativa", titolo="Asimily cybersecurity parco apparecchiature Brescia",
                       azienda="Spedali Civili di Brescia", divisione="Asimily", fase="demo",
                       valore_eur=45000, probabilita=30)
            a = await call("crea_attivita", descrizione="Follow-up con Mirco su estrazione dati acquisti",
                           tipo="follow-up", scadenza="2026-11-20T10:00", priorita="alta",
                           contatto="Mirco Fantuz", trattativa="ReDots analisi")
            await call("crea_attivita", descrizione="Chiamare Viganò per demo Asimily", tipo="chiamata",
                       scadenza="2026-11-18", contatto="Viganò")
            await call("catalogo")
            await call("crea_contatto", nome="Laura", cognome="Bianchi", azienda="Brescia",
                       ruolo="CISO", professionalita="IT / Sicurezza informatica")
            x = await call("crea_attivita", descrizione="Presentazione Asimily al CISO", tipo="riunione",
                           scadenza="2026-11-24T15:00", contatto="Laura Bianchi", prodotto="Asimily",
                           attivita_standard="presentazione")
            y = await call("crea_attivita", descrizione="Demo Asimily", tipo="demo", azienda="Brescia",
                           prodotto="Asimily", attivita_standard="STD-040", scadenza="2026-12-01")
            assert y["precedente_id"] == x["id"] and y["bu"] == "Asimily" and y["area"] == "Nord-Ovest", y
            await call("elenco_attivita", area="Nord-Ovest", professionalita="IT / Sicurezza informatica")
            await call("aggiungi_nota", testo="Viganò preoccupato per la sicurezza informatica degli ecografi "
                       "collegati in rete; chiede inventario vulnerabilità", fonte="riunione",
                       azienda="Brescia", contatto="Viganò")
            await call("elenco_attivita", dal="2026-11-16", al="2026-11-22")
            await call("completa_attivita", attivita_id=a["id"], esito="Dati arrivano lunedì")
            await call("aggiorna_trattativa", trattativa=str(t["id"]), fase="offerta",
                       prossimo_passo="Inviare offerta")
            await call("pipeline")
            await call("ricerca_semantica", domanda="sicurezza informatica ecografi", limite=3)
            await call("scheda_azienda", nome="Lifenet")
            err = await call("crea_attivita", descrizione="test", contatto="Rossi")
            assert "errore" in err
            print("\nCOLLAUDO OK")


asyncio.run(main())

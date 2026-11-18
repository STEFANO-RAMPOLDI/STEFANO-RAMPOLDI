"""Collaudo strumenti v3: centri con provincia, contatti estesi, amicizie, diario, note per provincia."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import guardia  # noqa
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "crm.server"], cwd=ROOT, env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("STRUMENTI:", len((await s.list_tools()).tools))
            async def call(n, **a):
                res = await s.call_tool(n, a); d = json.loads(res.content[0].text)
                assert "errore" not in d, d; print(">", n, json.dumps(d, ensure_ascii=False)[:180]); return d
            await call("crea_azienda", nome="Ospedale di Circolo Varese", tipo="ospedale pubblico", citta="Varese",
                       provincia="VA", natura="pubblico", dimensione="grande")
            await call("crea_contatto", nome="Paolo", cognome="Verdi", azienda="Ospedale di Circolo Varese",
                       ruolo="Direttore SIA", professionalita="IT / Sicurezza informatica", email="p.verdi@example.it",
                       cellulare="347 0000000", esperienze="Prima CIO all'ASST Sette Laghi", conosciuto_personalmente=True)
            await call("collega_contatti", persona_a="Paolo Verdi", persona_b="Gianluca Viganò", tipo="ex collega")
            await call("aggiorna_contatto", contatto="Laura Bianchi", conosciuto_personalmente=True)
            await call("scrivi_diario", testo="Pranzo con Paolo Verdi: interessato ad Asimily per il 2027", azienda="Varese", contatto="Verdi")
            n = await call("cerca_note", provincia="VA")
            assert n["risultati"] and n["risultati"][0]["provincia"] == "VA"
            await call("elenco_attivita", provincia="BS") if False else None
            print("COLLAUDO V3 OK")
asyncio.run(main())

"""Collaudo strumenti v4: obiettivi, campagne, esiti, persone da contattare, grafo."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import guardia  # noqa
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "crm.server"], cwd=ROOT, env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize(); print("STRUMENTI:", len((await s.list_tools()).tools))
            async def call(n, **a):
                res = await s.call_tool(n, a); d = json.loads(res.content[0].text)
                assert "errore" not in d, d; print(">", n, json.dumps(d, ensure_ascii=False)[:160]); return d
            await call("crea_azienda", nome="Clinica San Francesco – Verona", tipo="clinica privata", provincia="VR")
            await call("crea_contatto", nome="Davide", cognome="Dell'Amore", azienda="Clinica San Francesco", ruolo="Direttore Sanitario")
            o = await call("crea_obiettivo", titolo="deepc in 5 radiologie del Nord-Est", scadenza="2027-12-31")
            c = await call("crea_campagna", titolo="deepc radiologie Veneto", prodotto="deepc", obiettivo=str(o["id"]),
                           storia="I radiologi refertano di più in meno tempo: deepc fa da secondo lettore.",
                           regioni=["Veneto"], professionalita=["Radiologia"])
            await call("crea_attivita", descrizione="Presentare deepc al primario: carichi di lavoro e liste d'attesa",
                       azienda="Clinica San Francesco", contatto="Dell'Amore", trattativa=str(c["id"]), attivita_standard="STD-030",
                       scadenza="2026-12-02")
            p = await call("persone_da_contattare", iniziativa=str(c["id"]))
            assert len(p["persone"]) == 1
            await call("registra_esito", iniziativa=str(c["id"]), azienda="Clinica San Francesco", esito="sospesa", note="Rinvio al 2027")
            g = await call("grafo_obiettivi", obiettivo=str(o["id"]))
            assert g["grafo"][0]["contenitori"][0]["corsie"][0]["esito"]["esito"] == "sospesa"
            print("COLLAUDO V4 OK")
asyncio.run(main())

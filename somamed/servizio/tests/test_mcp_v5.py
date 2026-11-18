"""Collaudo v5: avviso già contattato, allerte, riattivazione, storico."""
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
                assert "errore" not in d, d; print(">", n, json.dumps(d, ensure_ascii=False)[:220]); return d
            await call("crea_azienda", nome="RSA Villa Serena Como", tipo="RSA", provincia="CO", natura="privato", dimensione="piccolo")
            a = await call("crea_attivita", descrizione="Seconda campagna: proporre ReDots a Viganò", contatto="Viganò",
                           attivita_standard="STD-010", scadenza="2026-12-01")
            assert a.get("attenzione"), "manca l'avviso"
            al = await call("imposta_allerta", data="2026-11-16", messaggio="Sollecitare Viganò sull'offerta", contatto="Viganò")
            d = await call("elenco_allerte", entro_giorni=0)
            assert any(x["id"] == al["id"] for x in d["allerte"])
            await call("aggiorna_allerta", allerta_id=al["id"], nuova_data="2026-11-23")
            await call("da_riattivare", giorni=90)
            await call("storico_contatto", contatto="Viganò")
            print("COLLAUDO V5 OK")
asyncio.run(main())

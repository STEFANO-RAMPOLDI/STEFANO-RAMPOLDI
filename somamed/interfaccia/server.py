"""Server dell'interfaccia del CRM SomaMed: pubblica solo i file di questa cartella (nessun dato).

Non richiede pacchetti: basta Python 3.  Uso:  python3 server.py [porta] [indirizzo]
I dati vengono letti dal servizio dati indicato in config.js (di solito http://127.0.0.1:8080).
In produzione questa cartella si può pubblicare con qualsiasi server web (nginx, Caddy, …).
"""
import functools
import http.server
import os
import sys
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
PUBBLICI = {"index.html", "config.js", "mappa.json"}


class Gestore(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript; charset=utf-8", ".json": "application/json",
                      ".html": "text/html; charset=utf-8"}

    def do_GET(self):
        nome = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        if nome not in PUBBLICI:          # niente elenco della cartella, niente file di servizio
            self.send_error(404)
            return
        self.path = "/" + nome
        super().do_GET()

    def end_headers(self):
        # pagina e configurazione sempre fresche; la mappa può restare in cache un giorno
        self.send_header("Cache-Control", "max-age=86400" if self.path.endswith("mappa.json") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass   # silenzioso: gli errori dei dati li registra il servizio dati


def main():
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("CRM_UI_PORT", "8081"))
    host = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("CRM_UI_HOST", "127.0.0.1")
    srv = http.server.ThreadingHTTPServer((host, porta), functools.partial(Gestore, directory=str(CARTELLA)))
    print(f"Interfaccia su http://{host}:{porta}  (dati da: vedi config.js)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

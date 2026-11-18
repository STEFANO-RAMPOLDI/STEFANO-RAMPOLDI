# Immagine del SERVIZIO DATI del CRM SomaMed (API + logica). Si costruisce dalla cartella somamed:
#   cd produzione && docker compose build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/modelli CRM_HOST=0.0.0.0 CRM_PORT=8080 CRM_TZ=Europe/Rome
WORKDIR /app

COPY servizio/requirements.txt servizio/requirements.txt
RUN pip install -r servizio/requirements.txt

# il modello per la ricerca per significato viene scaricato una volta, dentro l'immagine
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY database/migrazioni database/migrazioni
COPY servizio/crm servizio/crm

RUN useradd --system --no-create-home crm && chown -R crm /modelli
USER crm
WORKDIR /app/servizio
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/salute', timeout=4).status==200 else 1)"
CMD ["python", "-m", "crm.web"]

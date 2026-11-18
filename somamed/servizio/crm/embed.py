"""Calcolo dei vettori (embedding) per la ricerca semantica.

Il modello gira in locale sul computer: i testi non escono dalla macchina.
Modello predefinito: paraphrase-multilingual-MiniLM-L12-v2 (384 dimensioni, italiano incluso).
Per i test senza modello: CRM_EMBEDDER=hash (vettori lessicali semplici).

Rispetto alla versione precedente:
- il modello si carica una volta sola anche con più richieste contemporanee (lucchetto);
- ``precarica()`` lo scalda all'avvio del servizio, così la prima ricerca non aspetta;
- le domande ripetute (ricerche, filtri) non vengono ricalcolate (cache in memoria);
- ``embed_molti()`` calcola molti testi in un colpo solo (importazioni).
"""
import hashlib
import logging
import math
import os
import re
import threading
from functools import lru_cache

DIM = 384
MAX_CARATTERI = 4000          # oltre, il modello taglierebbe comunque il testo
_model = None
_lock = threading.RLock()   # rientrante: _embed_cache → _modello
log = logging.getLogger("crm.embed")


def _usa_hash():
    return os.environ.get("CRM_EMBEDDER", "fastembed") == "hash"


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"\w+", text.lower()):
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _modello():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding
                nome = os.environ.get("CRM_EMBED_MODEL",
                                      "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
                _model = TextEmbedding(nome)
                log.info("modello semantico pronto: %s", nome)
    return _model


def _prepara(text) -> str:
    return " ".join(str(text or "").split())[:MAX_CARATTERI]


@lru_cache(maxsize=1024)
def _embed_cache(text: str) -> tuple:
    if _usa_hash():
        return tuple(_hash_embed(text))
    with _lock:   # il modello ONNX usa già tutti i core: una chiamata alla volta è più stabile
        return tuple(float(x) for x in next(iter(_modello().embed([text]))))


def embed(text: str) -> list[float]:
    return list(_embed_cache(_prepara(text)))


def embed_molti(testi: list[str], blocco: int = 64) -> list[list[float]]:
    """Molti testi in un colpo solo: molto più veloce di uno alla volta."""
    testi = [_prepara(t) for t in testi]
    if _usa_hash():
        return [_hash_embed(t) for t in testi]
    m = _modello()
    with _lock:
        return [[float(x) for x in v] for v in m.embed(testi, batch_size=blocco)]


def precarica():
    """Carica il modello in anticipo (in un thread a parte, non blocca l'avvio)."""
    if _usa_hash():
        return
    def _vai():
        try:
            embed("prova")
        except Exception as e:   # il servizio funziona comunque; la ricerca semantica riproverà
            log.warning("modello semantico non caricato: %s", e)
    threading.Thread(target=_vai, name="precarica-modello", daemon=True).start()

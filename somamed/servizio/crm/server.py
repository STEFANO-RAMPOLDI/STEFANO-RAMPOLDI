"""Server MCP: il "ponte" che permette a Claude di leggere e scrivere nel CRM SomaMed."""
import functools
from datetime import datetime
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP

from . import core, piano, pianifica, offerte, budget as bg

mcp = FastMCP(
    "somamed-crm",
    instructions=(
        "CRM di SomaMed. Usa questi strumenti quando l'utente detta attività, contatti, "
        "trattative o note commerciali. Converti le date relative (es. 'venerdì') in formato "
        "ISO (AAAA-MM-GG o AAAA-MM-GGTHH:MM) partendo dalla data di oggi, che puoi chiedere "
        "con lo strumento oggi. Se un nome è ambiguo, chiedi all'utente quale intende. "
        "Prima di rispondere su un cliente, consulta scheda_azienda. "
        "Ogni attività va classificata con un'attività standard del catalogo (es. STD-070 Offerta) "
        "più una descrizione libera; collegala a centro, contatto, prodotto e trattativa quando noti. "
        "Per le aziende indica sempre la regione (serve per l'area geografica) e per i contatti "
        "la professionalità (es. Ingegneria clinica, Acquisti, Direzione sanitaria, Radiologia, IT). "
        "Per i centri indica provincia (sigla), natura (pubblico/privato/privato accreditato) e dimensione "
        "(piccolo/medio/grande). Quando l'utente racconta la sua giornata usa scrivi_diario; quando dice "
        "di conoscere qualcuno personalmente usa aggiorna_contatto; per amicizie tra persone collega_contatti. "
        "Le iniziative sono tutte della stessa famiglia e si distinguono solo per il tipo di attività: "
        "marketing oppure commerciale. Raccolgono attività su uno o più centri e persone e si collegano a un obiettivo. "
        "Non usare le parole campagna, opportunità o challenge come tipi. Ogni attività di un'iniziativa va scritta con il 'perché' "
        "(descrizione) e collegata a centro e persona. Ogni ramo centro si chiude con registra_esito "
        "(vendita, rifiuto, scelto altro + concorrente, sospesa). Se crea_attivita restituisce 'attenzione' "
        "(persona già contattata o con attività aperte altrove) riferiscilo sempre all'utente. "
        "Per solleciti e riattivazioni usa imposta_allerta; all'inizio della giornata controlla elenco_allerte. "
        "Quando l'utente chiede cosa fare oggi o il piano della giornata usa piano_del_giorno con le ore che ha a disposizione; "
        "poi, per ogni voce, scrivi una preparazione personalizzata (traccia della chiamata con apertura, messaggio, domande "
        "e chiusura, oppure oggetto e testo della mail) usando storia dell'iniziativa, prodotto, ultima interazione e perché "
        "dell'attività, e salvala con salva_preparazione. Quando l'utente racconta com'è andata un'attività usa "
        "registra_resoconto (fatta / non risponde / rimanda / annullata) e proponi il passo successivo. "
        "Per migliorare il metodo di lavoro usa suggerimenti_processo e commenta i dati. "
        "Quando l'utente crea o rivede un obiettivo, proponi di costruire il piano misurabile con piano_obiettivo: "
        "una domanda alla volta, poi salva_piano_obiettivo con le tue indicazioni. "
        "Per preparare un'offerta economica usa crea_offerta collegandola all'iniziativa, con le righe dei prodotti e una "
        "premessa breve e personale; ricorda all'utente di rivederla e stamparla dalla sezione Offerte. "
        "BUDGET STRATEGICO: il valore di un centro nasce dalle voci del prodotto (es. Asimily: dispositivi monitorati × "
        "€/dispositivo/anno × anni). Prima di un budget controlla le voci con voci_prodotto e, se mancano, chiedile all'utente "
        "(imposta_voce_prodotto). Quando l'utente dà dati di un centro (posti letto, quante apparecchiature) usa censisci_centro. "
        "Con crea_budget_strategico valuti i centri di un'area: valore potenziale, margine, probabilità, fascia A/B/C, "
        "strategia proposta; commentali con budget_strategico (quali centri valgono di più, dove abbiamo accesso, cosa manca). "
        "Le scelte sui centri (escludere, probabilità, strategia) con scelta_centro_budget; poi genera_piano_tattico crea "
        "l'iniziativa macro con le attività per centro e per voce. Dichiara sempre quali valori sono stimati."
    ),
)

TipoAzienda = Literal["ospedale pubblico", "ospedale privato", "clinica privata", "centro medico", "RSA",
                      "gruppo sanitario", "laboratorio", "distributore", "partner", "fornitore", "università", "altro"]
Fase = Literal["primo contatto", "qualificata", "demo", "offerta", "negoziazione", "gara",
               "vinta", "persa", "sospesa"]
TipoAttivita = Literal["chiamata", "email", "riunione", "follow-up", "offerta", "demo", "visita", "compito"]
Priorita = Literal["alta", "media", "bassa"]
Fonte = Literal["chat", "email", "riunione", "telefonata", "fiera", "documento", "altro"]


_schema_ok = False


def _assicura_schema():
    """Se all'avvio il database era spento, lo schema si aggiorna alla prima chiamata utile."""
    global _schema_ok
    if not _schema_ok:
        try:
            core.migra()
            _schema_ok = True
        except core.DatabaseNonRaggiungibile:
            pass


def safe(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            _assicura_schema()
            return fn(*a, **k)
        except core.CRMError as e:
            return {"errore": str(e)}
        except Exception as e:  # errori del database ecc.
            return {"errore": f"{type(e).__name__}: {e}"}
    return wrapper


@mcp.tool()
def oggi() -> dict:
    """Data e ora attuali, per calcolare scadenze come 'domani' o 'venerdì prossimo'."""
    now = datetime.now()
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    return {"oggi": now.date().isoformat(), "giorno": giorni[now.weekday()], "ora": now.strftime("%H:%M")}


Natura = Literal["pubblico", "privato", "privato accreditato"]
Dimensione = Literal["piccolo", "medio", "grande"]


@mcp.tool()
@safe
def crea_azienda(nome: str, tipo: TipoAzienda = "altro", citta: Optional[str] = None,
                 provincia: Optional[str] = None, regione: Optional[str] = None,
                 natura: Optional[Natura] = None, dimensione: Optional[Dimensione] = None,
                 indirizzo: Optional[str] = None, telefono: Optional[str] = None, email: Optional[str] = None,
                 sito: Optional[str] = None, tag: Optional[list[str]] = None, note: Optional[str] = None) -> dict:
    """Crea (o completa se esiste già) un centro: ospedale, clinica, distributore, partner.
    provincia = sigla (MI, CO, BS…); la regione si ricava dalla provincia."""
    return core.crea_azienda(nome, tipo, citta, regione, sito, tag, note, provincia, natura, dimensione,
                             indirizzo, telefono, email)


@mcp.tool()
@safe
def crea_contatto(nome: str, cognome: Optional[str] = None, azienda: Optional[str] = None,
                  ruolo: Optional[str] = None, professionalita: Optional[str] = None,
                  email: Optional[str] = None, cellulare: Optional[str] = None, telefono: Optional[str] = None,
                  email_privata: Optional[str] = None, linkedin: Optional[str] = None,
                  esperienze: Optional[str] = None, conosciuto_personalmente: bool = False,
                  note: Optional[str] = None, tag: Optional[list[str]] = None) -> dict:
    """Crea una persona collegata al suo centro. esperienze = incarichi e lavori passati.
    conosciuto_personalmente = true se l'utente la conosce di persona."""
    return core.crea_contatto(nome, cognome, azienda, ruolo, email, telefono, tag, note, professionalita,
                              email_privata, cellulare, None, linkedin, esperienze, conosciuto_personalmente)


@mcp.tool()
@safe
def aggiorna_contatto(contatto: str, ruolo: Optional[str] = None, professionalita: Optional[str] = None,
                      email: Optional[str] = None, cellulare: Optional[str] = None, telefono: Optional[str] = None,
                      email_privata: Optional[str] = None, linkedin: Optional[str] = None,
                      esperienze: Optional[str] = None, conosciuto_personalmente: Optional[bool] = None,
                      note: Optional[str] = None) -> dict:
    """Aggiorna i dati di una persona (nome o numero). Solo i campi indicati vengono cambiati."""
    return core.aggiorna_contatto(contatto, ruolo=ruolo, professionalita=professionalita, email=email,
                                  cellulare=cellulare, telefono=telefono, email_privata=email_privata,
                                  linkedin=linkedin, esperienze=esperienze,
                                  conosciuto_personalmente=conosciuto_personalmente, note=note)


@mcp.tool()
@safe
def collega_contatti(persona_a: str, persona_b: str,
                     tipo: Literal["amicizia", "ex collega", "collega", "conoscenza", "parente"] = "amicizia",
                     note: Optional[str] = None) -> dict:
    """Registra un'amicizia o conoscenza tra due persone del CRM."""
    return core.collega_contatti(persona_a, persona_b, tipo, note)


@mcp.tool()
@safe
def scrivi_diario(testo: str, giorno: Optional[str] = None, azienda: Optional[str] = None,
                  contatto: Optional[str] = None) -> dict:
    """Aggiunge una voce al diario delle giornate (giorno ISO, oggi se omesso), collegata a centro/persona."""
    return core.scrivi_diario(testo, giorno, azienda, contatto)


@mcp.tool()
@safe
def cerca_note(domanda: Optional[str] = None, azienda: Optional[str] = None, provincia: Optional[str] = None,
               regione: Optional[str] = None, dal: Optional[str] = None, al: Optional[str] = None,
               genere: Optional[Literal["nota", "diario"]] = None, limite: int = 30) -> dict:
    """Interroga note e diario per centro, provincia (sigla), regione e periodo.
    Con 'domanda' cerca per significato; senza, elenca dalle più recenti."""
    return {"risultati": core.cerca_note(domanda, azienda, provincia, regione, dal, al, genere, limite)}


@mcp.tool()
@safe
def trova(testo: str, limite: int = 10) -> dict:
    """Cerca aziende e contatti per nome, anche con nomi scritti male."""
    return core.trova(testo, limite)


@mcp.tool()
@safe
def scheda_azienda(nome: str) -> dict:
    """Tutto su un'azienda: contatti, trattative, attività aperte e fatte, ultime note."""
    return core.scheda_azienda(nome)


@mcp.tool()
@safe
def crea_trattativa(titolo: str, azienda: Optional[str] = None, divisione: Optional[str] = None, fase: Fase = "primo contatto",
                    contatto: Optional[str] = None, valore_eur: Optional[float] = None,
                    probabilita: Optional[int] = None, chiusura_prevista: Optional[str] = None,
                    prossimo_passo: Optional[str] = None, prodotto: Optional[str] = None,
                    obiettivo: Optional[str] = None, storia: Optional[str] = None,
                    genere: Literal["marketing", "commerciale"] = "commerciale") -> dict:
    """Apre un'iniziativa con un centro principale (di norma commerciale), collegabile a un obiettivo."""
    return core.crea_trattativa(titolo, azienda, divisione, fase, contatto, valore_eur,
                                probabilita, chiusura_prevista, prossimo_passo, prodotto, obiettivo, storia, genere)


@mcp.tool()
@safe
def aggiorna_trattativa(trattativa: str, fase: Optional[Fase] = None, valore_eur: Optional[float] = None,
                        probabilita: Optional[int] = None, chiusura_prevista: Optional[str] = None,
                        prossimo_passo: Optional[str] = None) -> dict:
    """Aggiorna una trattativa (indicata per numero o titolo): fase, valore, probabilità, prossimo passo."""
    return core.aggiorna_trattativa(trattativa, fase, valore_eur, probabilita,
                                    chiusura_prevista, prossimo_passo)


@mcp.tool()
@safe
def pipeline(divisione: Optional[str] = None, includi_chiuse: bool = False) -> dict:
    """Situazione delle trattative aperte, con totali e valore pesato per divisione."""
    return core.pipeline(divisione, includi_chiuse)


@mcp.tool()
@safe
def crea_attivita(descrizione: str, tipo: TipoAttivita = "compito", scadenza: Optional[str] = None,
                  priorita: Priorita = "media", azienda: Optional[str] = None,
                  contatto: Optional[str] = None, trattativa: Optional[str] = None,
                  responsabile: str = "Stefano", attivita_standard: Optional[str] = None,
                  prodotto: Optional[str] = None, precedente_id: Optional[int] = None) -> dict:
    """Registra un'attività. attivita_standard: codice o nome dal catalogo (STD-010 Primo contatto …
    STD-140 Assistenza). tipo = canale (chiamata, email, riunione…). scadenza in ISO.
    La sequenza è automatica (si aggancia all'ultima attività della stessa trattativa o dello
    stesso centro+prodotto); precedente_id la forza, 0 la interrompe."""
    return core.crea_attivita(descrizione, tipo, scadenza, priorita, azienda, contatto,
                              trattativa, responsabile, attivita_standard, prodotto, precedente_id)


@mcp.tool()
@safe
def completa_attivita(attivita_id: int, esito: Optional[str] = None,
                      stato: Literal["fatta", "annullata"] = "fatta") -> dict:
    """Segna un'attività come fatta (o annullata) e ne registra l'esito."""
    return core.completa_attivita(attivita_id, esito, stato)


@mcp.tool()
@safe
def elenco_attivita(dal: Optional[str] = None, al: Optional[str] = None,
                    stato: Optional[Literal["da fare", "fatta", "annullata"]] = "da fare",
                    azienda: Optional[str] = None, divisione: Optional[str] = None,
                    solo_scadute: bool = False, responsabile: Optional[str] = None,
                    limite: int = 50, area: Optional[str] = None, professionalita: Optional[str] = None,
                    prodotto: Optional[str] = None, attivita_standard: Optional[str] = None,
                    contatto: Optional[str] = None) -> dict:
    """Elenca le attività filtrando per periodo, stato, centro, contatto, business unit (divisione),
    area geografica (Nord-Ovest, Nord-Est, Centro, Sud, Isole), professionalità, prodotto, standard."""
    r = core.elenco_attivita(dal, al, stato, azienda, divisione, solo_scadute, responsabile, limite,
                             area, professionalita, prodotto, attivita_standard, contatto)
    return {"totale": len(r), "attivita": r}


@mcp.tool()
@safe
def aggiungi_nota(testo: str, fonte: Fonte = "chat", azienda: Optional[str] = None,
                  contatto: Optional[str] = None, trattativa: Optional[str] = None) -> dict:
    """Salva una nota libera (verbale, sintesi di una mail, appunto) ricercabile per significato."""
    return core.aggiungi_nota(testo, fonte, azienda, contatto, trattativa)


@mcp.tool()
@safe
def ricerca_semantica(domanda: str, limite: int = 8) -> dict:
    """Cerca per significato in note, attività e trattative (es. 'chi era interessato alla cybersecurity?')."""
    return {"risultati": core.ricerca_semantica(domanda, limite)}


@mcp.tool()
@safe
def catalogo() -> dict:
    """Catalogo: attività standard, prodotti con business unit, divisioni, professionalità in uso."""
    return core.catalogo()


@mcp.tool()
@safe
def crea_prodotto(nome: str, divisione: str = "Altro", produttore: Optional[str] = None,
                  descrizione: Optional[str] = None, tipologie_clienti: Optional[list[str]] = None,
                  descrizione_clienti: Optional[str] = None) -> dict:
    """Aggiunge (o aggiorna) un prodotto: business unit, descrizione e tipologie di clienti a cui si rivolge."""
    return core.crea_prodotto(nome, divisione, produttore, descrizione, tipologie_clienti, descrizione_clienti)


@mcp.tool()
@safe
def crea_obiettivo(titolo: str, tipo: Literal["area", "budget"] = "area", ambito: Optional[str] = None,
                   descrizione: Optional[str] = None, scadenza: Optional[str] = None,
                   valore_eur: Optional[float] = None, padre: Optional[str] = None,
                   regioni: Optional[list[str]] = None, province: Optional[list[str]] = None,
                   target_centri: Optional[int] = None, data_inizio: Optional[str] = None) -> dict:
    """Crea un obiettivo o un sotto-obiettivo (indicando il padre) di area o di budget, con budget (valore_eur),
    regioni e province (sigle), numero di centri da conquistare (target_centri) e data di inizio.
    Le iniziative create sotto un obiettivo ne ereditano regioni e province."""
    return core.crea_obiettivo(titolo, descrizione, scadenza, valore_eur, tipo, ambito, padre, regioni, province,
                               target_centri, data_inizio)


@mcp.tool()
@safe
def avanzamento_obiettivo(obiettivo: Optional[str] = None) -> dict:
    """Verifica il raggiungimento degli obiettivi sulla base delle attività: quanto è stato venduto, quanto manca,
    quanto è coperto dalle trattative aperte, previsione ponderata per la fase raggiunta nei centri, confronto con
    il tempo trascorso, ritmo necessario, centri per fase e consigli. Senza obiettivo: sintesi di tutti."""
    if obiettivo:
        return core.avanzamento_obiettivo(obiettivo)
    return {"obiettivi": core.avanzamento_obiettivi()}


@mcp.tool()
@safe
def albero_obiettivi() -> dict:
    """Obiettivi con i sotto-obiettivi e le iniziative di ciascuno, con budget e risultati."""
    return {"obiettivi": core.albero_obiettivi()}


@mcp.tool()
@safe
def mappa_mentale(tipo: Optional[Literal["obiettivo", "trattativa", "azienda", "contatto", "prodotto"]] = None,
                  id: Optional[int] = None) -> dict:
    """Legami di un oggetto come mappa mentale (rami con il tipo di legame). Senza argomenti: tutta SomaMed."""
    return core.mappa_mentale(tipo, id)


@mcp.tool()
@safe
def diario_giornate(dal: Optional[str] = None, al: Optional[str] = None, azienda: Optional[str] = None,
                    provincia: Optional[str] = None) -> dict:
    """Diario per giorno: annotazioni e attività svolte, più le attività in programma da compiere
    (scadute, di oggi, dei prossimi giorni, senza data)."""
    return {"da_compiere": core.da_compiere(azienda, provincia), "giornate": core.giornate(dal, al, azienda, provincia)}


@mcp.tool()
@safe
def crea_campagna(titolo: str, genere: Literal["marketing", "commerciale"] = "marketing",
                  prodotto: Optional[str] = None, obiettivo: Optional[str] = None, azienda: Optional[str] = None,
                  storia: Optional[str] = None, natura: Optional[str] = None, dimensione: Optional[str] = None,
                  regioni: Optional[list[str]] = None, province: Optional[list[str]] = None,
                  professionalita: Optional[list[str]] = None, data_inizio: Optional[str] = None,
                  data_fine: Optional[str] = None, valore_eur: Optional[float] = None) -> dict:
    """Crea un'iniziativa di marketing o commerciale: contenitore di attività su
    uno o più centri e persone, con target (natura, dimensione, regioni, province, professionalità), storia da
    raccontare e, se c'è, un centro principale."""
    target = {k: v for k, v in dict(natura=natura, dimensione=dimensione, regioni=regioni, province=province,
                                    professionalita=professionalita).items() if v}
    return core.crea_campagna(titolo, prodotto, obiettivo, storia, target, data_inizio, data_fine, None, valore_eur,
                              genere, azienda)


@mcp.tool()
@safe
def registra_esito(iniziativa: str, azienda: str,
                   esito: Literal["vendita", "rifiuto", "scelto altro", "sospesa"],
                   concorrente: Optional[str] = None, note: Optional[str] = None) -> dict:
    """Chiude il ramo di un centro in un'iniziativa (per numero o nome): vendita, rifiuto,
    scelto altro (indicare il concorrente) o sospesa."""
    return core.registra_esito(iniziativa, azienda, esito, concorrente, note)


@mcp.tool()
@safe
def persone_da_contattare(iniziativa: Optional[str] = None, provincia: Optional[str] = None,
                          solo_conosciuti: bool = False) -> dict:
    """Chi contattare e perché (dalle attività da fare), per iniziativa o provincia."""
    return {"persone": core.persone_da_contattare(iniziativa, provincia, solo_conosciuti)}


@mcp.tool()
@safe
def grafo_obiettivi(obiettivo: Optional[str] = None, iniziativa: Optional[str] = None) -> dict:
    """Situazione a grafo: obiettivi → iniziative → centri → attività → esito."""
    return {"grafo": core.grafo(obiettivo, iniziativa)}


@mcp.tool()
@safe
def imposta_allerta(data: str, messaggio: str,
                    tipo: Literal["sollecito", "riattivazione", "promemoria"] = "sollecito",
                    contatto: Optional[str] = None, azienda: Optional[str] = None,
                    iniziativa: Optional[str] = None, attivita_id: Optional[int] = None) -> dict:
    """Fissa un'allerta di sollecito, riattivazione o promemoria per una data (ISO), su persona/centro/campagna."""
    return core.imposta_allerta(data, messaggio, tipo, contatto, azienda, iniziativa, attivita_id)


@mcp.tool()
@safe
def elenco_allerte(entro_giorni: Optional[int] = 0, contatto: Optional[str] = None,
                   azienda: Optional[str] = None, iniziativa: Optional[str] = None) -> dict:
    """Allerte attive: entro_giorni=0 → scadute e di oggi; None → tutte."""
    return {"allerte": core.elenco_allerte("attiva", entro_giorni, contatto, azienda, iniziativa)}


@mcp.tool()
@safe
def aggiorna_allerta(allerta_id: int, stato: Optional[Literal["fatta", "annullata", "attiva"]] = None,
                     nuova_data: Optional[str] = None) -> dict:
    """Segna un'allerta come fatta/annullata oppure la rimanda a una nuova data."""
    return core.aggiorna_allerta(allerta_id, stato, nuova_data)


@mcp.tool()
@safe
def da_riattivare(giorni: int = 90) -> dict:
    """Persone contattate in passato ma ferme da più di N giorni, senza attività aperte né allerte."""
    return {"persone": core.da_riattivare(giorni)}


@mcp.tool()
@safe
def storico_contatto(contatto: str) -> dict:
    """Tutte le volte che una persona è stata contattata (e in quali campagne), con gli avvisi."""
    with core.connect() as conn:
        cid = int(contatto) if str(contatto).isdigit() else core.risolvi_contatto(conn, contatto)
        return {"storico": core.storico_contatto(conn, cid), "avvisi": core.avvisi_contatto(conn, cid)}



@mcp.tool()
@safe
def piano_del_giorno(ore: Optional[float] = None, giorno: Optional[str] = None, inizio: Optional[str] = None,
                     responsabile: Optional[str] = None) -> dict:
    """Piano della giornata: con le ore disponibili (es. 5) sceglie e ordina le attività da fare (scadute, di oggi,
    allerte, priorità, valore), con orario, persona, recapiti, motivo e una preparazione di base. Restituisce anche le
    attività rimaste fuori, i centri senza prossimo passo e i suggerimenti sui processi. giorno: AAAA-MM-GG, inizio: HH:MM."""
    return piano.piano_giorno(giorno, ore, inizio, responsabile)


@mcp.tool()
@safe
def salva_preparazione(attivita_id: int, testo: str, durata_min: Optional[int] = None) -> dict:
    """Salva per un'attività la traccia della chiamata o il testo della mail (oggetto + corpo), che l'utente vedrà
    nel Piano del giorno. Scrivila in italiano semplice, breve, con il nome della persona e il motivo concreto."""
    return piano.salva_preparazione(attivita_id, testo, durata_min)


@mcp.tool()
@safe
def registra_resoconto(attivita_id: int, come: Literal["fatta", "non risponde", "rimanda", "annullata"] = "fatta",
                       resoconto: Optional[str] = None, processo: Optional[str] = None,
                       prossimo_codice: Optional[str] = None, prossimo_giorni: int = 7,
                       prossimo_descrizione: Optional[str] = None, giorni: Optional[int] = None,
                       data: Optional[str] = None, prossima_data: Optional[str] = None) -> dict:
    """Com'è andata un'attività. 'fatta' chiude l'attività, scrive il resoconto nel diario e (con prossimo_codice,
    es. STD-030) crea subito il passo successivo tra prossimo_giorni giorni. 'non risponde' la sposta di 2 giorni,
    'rimanda' la ripropongono nel giorno 'data' (AAAA-MM-GG) o tra 'giorni'; 'annullata' richiede il perché nel resoconto.
    Ogni esito viene riassunto in una riga del diario del giorno. processo: idea per migliorare il modo di lavorare."""
    return piano.registra_resoconto(attivita_id, come, resoconto, processo, prossimo_codice, prossimo_giorni,
                                    prossimo_descrizione, giorni, data, prossima_data)


@mcp.tool()
@safe
def calendario(dal: str, al: str, responsabile: Optional[str] = None) -> dict:
    """Attività pianificate nel periodo (AAAA-MM-GG), con orario, durata, prodotto, iniziativa, centro e persona,
    e le ore disponibili per giorno. Per portarle in Google Calendar usa il connettore Google Calendar dell'utente
    (crea un evento per ogni attività, con titolo «attività · persona · centro»), solo se l'utente lo chiede."""
    return piano.calendario(dal, al, responsabile)


@mcp.tool()
@safe
def sposta_attivita(attivita_id: int, quando: str, durata_min: Optional[int] = None) -> dict:
    """Sposta un'attività ancora da fare a un altro giorno e ora (AAAA-MM-GG HH:MM)."""
    return piano.sposta(attivita_id, quando, durata_min)


@mcp.tool()
@safe
def piano_obiettivo(obiettivo: str) -> dict:
    """Assistente per gli obiettivi: restituisce le domande per costruire un piano misurabile, le risposte già
    note (dall'obiettivo e dal CRM) e il calcolo: centri da contattare, presentazioni, offerte e ordini necessari,
    ritmo settimanale, ore di lavoro contro ore disponibili, costi, margine, ritorno e avvisi.
    Usalo così: fai all'utente UNA domanda alla volta tra quelle senza risposta (spiegando in breve il perché),
    metti in dubbio le ipotesi ottimiste con i dati del CRM, poi salva con salva_piano_obiettivo."""
    return pianifica.piano_obiettivo(obiettivo)


@mcp.tool()
@safe
def salva_piano_obiettivo(obiettivo: str, risposte: dict, indicazioni: Optional[str] = None, applica: bool = False) -> dict:
    """Salva le risposte del piano di un obiettivo (chiavi come in piano_obiettivo) e ricalcola il piano.
    indicazioni: il tuo commento per l'utente (ipotesi da verificare, rischi, domande mancanti, prime azioni),
    che comparirà nella scheda dell'obiettivo. applica=True aggiorna budget, numero di centri e scadenza dell'obiettivo."""
    return pianifica.salva_piano(obiettivo, risposte, indicazioni, applica)


@mcp.tool()
@safe
def crea_offerta(oggetto: str, centro: Optional[str] = None, persona: Optional[str] = None, iniziativa: Optional[str] = None,
                 righe: Optional[list[dict]] = None, premessa: Optional[str] = None, validita_giorni: int = 60,
                 pagamento: Optional[str] = None, consegna: Optional[str] = None, garanzia: Optional[str] = None,
                 note: Optional[str] = None, sconto_globale: float = 0) -> dict:
    """Crea un'offerta economica in bozza. righe: lista di voci {prodotto (nome) o prodotto_id, descrizione, quantita,
    prezzo (unitario IVA esclusa; se manca si usa il listino), sconto (%), aliquota_iva, costo}. premessa: lettera di
    accompagnamento (scrivila tu, breve e personale). Se indichi l'iniziativa, centro e persona si prendono da lì.
    L'utente la rivede e la stampa nell'interfaccia (Offerte)."""
    return offerte.crea_offerta(oggetto, centro, persona, iniziativa, righe, premessa, validita_giorni, pagamento,
                                consegna, garanzia, note, sconto_globale)


@mcp.tool()
@safe
def modifica_offerta(offerta_id: int, campi: Optional[dict] = None, righe: Optional[list[dict]] = None) -> dict:
    """Modifica un'offerta in bozza: campi (oggetto, premessa, validita_giorni, pagamento, consegna, garanzia, note,
    sconto_globale) e/o tutte le righe (sostituite)."""
    return offerte.aggiorna_offerta(offerta_id, campi, righe)


@mcp.tool()
@safe
def elenco_offerte(stato: Optional[str] = None, centro: Optional[str] = None, iniziativa: Optional[str] = None) -> dict:
    """Offerte: stato bozza / inviata / accettata / rifiutata / annullata, oppure 'aperte' (bozza e inviate)."""
    return {"offerte": offerte.elenco_offerte(stato, centro, iniziativa)}


@mcp.tool()
@safe
def esito_offerta(offerta_id: int, stato: Literal["inviata", "accettata", "rifiutata", "annullata"],
                  note: Optional[str] = None, concorrente: Optional[str] = None, giorni_followup: int = 7) -> dict:
    """Cambia lo stato di un'offerta. 'inviata' registra l'invio e fissa il follow-up; 'accettata' registra la vendita
    sul centro dell'iniziativa; 'rifiutata' il rifiuto (o 'scelto altro' se indichi il concorrente)."""
    return offerte.cambia_stato(offerta_id, stato, note, concorrente, giorni_followup)


@mcp.tool()
@safe
def utenti() -> dict:
    """Utenti del CRM (chi lavora le attività: il nome è quello da usare come responsabile)."""
    return {"utenti": core.utenti()}


@mcp.tool()
@safe
def crea_utente(nome: str, cognome: Optional[str] = None, email: Optional[str] = None, ruolo: Optional[str] = None) -> dict:
    """Aggiunge un utente del CRM (es. un collaboratore a cui assegnare attività come responsabile)."""
    return core.crea_utente(nome, cognome, email, ruolo)


@mcp.tool()
@safe
def suggerimenti_processo() -> dict:
    """Suggerimenti per migliorare i processi commerciali e di marketing, ricavati dalle attività e dagli esiti,
    più le idee annotate dall'utente."""
    return {"suggerimenti": piano.suggerimenti_processo()}


# ---------- budget strategico ----------

Strategia = Literal["attacco", "accesso", "sviluppo", "presidio", "censire"]
Fonte_q = Literal["dichiarata", "censita", "stimata"]


@mcp.tool()
@safe
def voci_prodotto(prodotto: str) -> dict:
    """Voci di prezzo di un prodotto: gli item che generano il valore (es. dispositivi monitorati, € per unità, canone)."""
    return bg.voci(prodotto)


@mcp.tool()
@safe
def imposta_voce_prodotto(prodotto: str, nome: str, prezzo_unitario: Optional[float] = None, unita: Optional[str] = None,
                          costo_unitario: Optional[float] = None, ricorrente: Optional[bool] = None, anni: Optional[int] = None,
                          stima_per_posto_letto: Optional[float] = None, quantita_fissa: Optional[float] = None,
                          note: Optional[str] = None) -> dict:
    """Crea o aggiorna una voce di prezzo. ricorrente=True se è un canone annuo (valore = quantità × prezzo × anni).
    stima_per_posto_letto: unità tipiche per posto letto, per stimare i centri non ancora censiti.
    quantita_fissa: quantità uguale per ogni centro (es. 1 installazione)."""
    return bg.salva_voce(prodotto, nome, None, prezzo_unitario=prezzo_unitario, unita=unita, costo_unitario=costo_unitario,
                         ricorrente=ricorrente, anni=anni, stima_per_posto_letto=stima_per_posto_letto,
                         quantita_fissa=quantita_fissa, note=note)


@mcp.tool()
@safe
def censisci_centro(centro: str, posti_letto: Optional[int] = None, prodotto: Optional[str] = None,
                    quantita: Optional[dict] = None, fonte: Fonte_q = "dichiarata") -> dict:
    """Dati dell'organizzazione di un centro: posti letto e quante unità ha di ogni voce del prodotto.
    quantita: {nome della voce: numero}, es. {"Dispositivi medicali connessi": 1800}."""
    out = {}
    if posti_letto is not None:
        out["posti_letto"] = bg.imposta_posti_letto(centro, posti_letto)
    if quantita:
        if not prodotto:
            raise core.CRMError("Indica il prodotto a cui appartengono le voci.")
        vv = {v["nome"].lower(): v for v in bg.voci(prodotto)["voci"]}
        out["voci"] = []
        for nome, q in quantita.items():
            v = vv.get(str(nome).lower()) or next((x for k, x in vv.items() if str(nome).lower() in k), None)
            if not v:
                raise core.CRMError(f"Voce '{nome}' non trovata. Voci del prodotto: " + ", ".join(x["nome"] for x in vv.values()))
            out["voci"].append(bg.censisci(centro, v["id"], q, fonte))
    return out


@mcp.tool()
@safe
def crea_budget_strategico(titolo: str, prodotto: str, regioni: Optional[str] = None, province: Optional[str] = None,
                           tipi_centro: Optional[list[str]] = None, obiettivo: Optional[str] = None,
                           anno: Optional[int] = None, sconto_medio: float = 0) -> dict:
    """Budget strategico di un prodotto su un'area: valuta tutti i centri (valore potenziale dalle voci, margine,
    probabilità, valore atteso, fascia A/B/C, strategia proposta). Se c'è l'obiettivo ne eredita l'area."""
    return _sintesi_budget(bg.crea_budget(titolo, prodotto, obiettivo, anno, regioni, province, tipi_centro, sconto_medio))


def _sintesi_budget(d, max_centri=40):
    tieni = ("azienda_id", "centro", "provincia", "natura", "fascia", "valore_potenziale", "margine_potenziale",
             "affidabilita", "probabilita", "valore_atteso", "strategia_nome", "gara", "stato", "venduto", "incluso")
    return {"budget": d["budget"], "riepilogo": d["riepilogo"],
            "centri": [{**{k: c[k] for k in tieni},
                        "voci": [f"{v['quantita']} {v['voce']} ({v['fonte']})" for v in c["voci"]]} for c in d["centri"][:max_centri]],
            "altri_centri": max(0, len(d["centri"]) - max_centri), "strategie": d["strategie"]}


@mcp.tool()
@safe
def budget_strategico(budget_id: Optional[int] = None) -> dict:
    """Senza id: elenco dei budget con potenziale, atteso e venduto. Con id: centri ordinati per fascia e valore,
    voci per centro (censite o stimate), strategia, stato (da avviare, in corso, vinto, perso) e avvisi."""
    return {"budget": bg.elenco_budget()} if budget_id is None else _sintesi_budget(bg.budget(budget_id))


@mcp.tool()
@safe
def scelta_centro_budget(budget_id: int, centro: str, incluso: Optional[bool] = None, probabilita: Optional[int] = None,
                         strategia: Optional[Strategia] = None, note: Optional[str] = None) -> dict:
    """Scelte su un centro del budget: escluderlo, cambiare probabilità o strategia (attacco diretto, costruire
    l'accesso, sviluppo mirato, presidio marketing, censire prima)."""
    return bg.imposta_centro(budget_id, centro, incluso, probabilita, strategia, note)


@mcp.tool()
@safe
def genera_piano_tattico(budget_id: int, fasce: str = "A,B", data_inizio: Optional[str] = None,
                         responsabile: str = "Stefano", centri_a_settimana: int = 3) -> dict:
    """Dal budget al piano: crea l'iniziativa macro e, per ogni centro delle fasce scelte, le attività della sua
    strategia (con un'operazione per ogni voce del prodotto), scaglionate per fascia e per settimana."""
    return bg.genera_piano_tattico(budget_id, fasce, data_inizio, responsabile, centri_a_settimana)


def main():
    _assicura_schema()   # se il database non è ancora acceso, riprova alla prima chiamata
    try:
        mcp.run()
    finally:
        core.chiudi_pool()


if __name__ == "__main__":
    main()

# CRM SomaMed — versione locale a tre strati

È un CRM che vive sul tuo computer e che Claude sa usare. Tu detti a Claude attività, contatti e trattative,
Claude li scrive nel database; tu li vedi e li modifichi dall'interfaccia web.

## Com'è fatto: tre parti separate

```
somamed/
├── database/      ← DATI: PostgreSQL 16 + pgvector (Docker). L'unico posto dove stanno i dati.
│   ├── docker-compose.yml
│   └── migrazioni/   001…015 *.sql — la struttura del database, applicata da sola
├── servizio/      ← SERVIZIO DATI: l'unica porta d'accesso ai dati (API web + ponte con Claude)
│   ├── crm/          web.py (API, porta 8080) · server.py (Claude/MCP) · core.py (logica) · budget.py
│   └── tests/
├── interfaccia/   ← INTERFACCIA: solo la pagina web (porta 8081), nessun dato
│   ├── index.html · mappa.json
│   └── config.js     dice a quale servizio dati collegarsi
├── config.env     ← le tue impostazioni (creato all'installazione da config.env.esempio)
└── installa.sh · avvia.sh · ferma.sh · stato.sh · aggiorna.sh · backup.sh · ripristina.sh
```

- **Database** e **servizio dati** si parlano solo tramite `CRM_DSN` (in `config.env`).
- **Interfaccia** e **servizio dati** si parlano solo tramite l'indirizzo in `interfaccia/config.js`.
- Ognuna delle tre parti si può spostare su un'altra macchina cambiando una riga. I dettagli,
  la scelta del database vettoriale e i passi per l'uso da più utenti sono in **ARCHITETTURA.md**.

## Installazione (una volta sola, circa 10 minuti)

1. Installa e apri **Docker Desktop** (docker.com).
2. Verifica di avere **Python 3.10 o più recente** (Terminale: `python3 --version`; altrimenti `brew install python@3.12`).
3. Metti la cartella `somamed` dove vuoi tenerla, ad esempio nella tua cartella utente (`~/somamed`). **Non spostarla dopo l'installazione** (Claude Desktop la cerca lì).
4. Nel Terminale: `cd ~/somamed` e poi `bash installa.sh`
5. Chiudi Claude Desktop con Cmd+Q e riaprilo: nei connettori deve comparire **somamed-crm**.

### Se avevi già la versione precedente (`~/somamed-crm`)

I dati **restano**: stanno nel volume Docker `somamed-crm_crm_dati`, che la nuova versione riusa così com'è.

1. Ferma la vecchia interfaccia (Ctrl+C nella sua finestra del Terminale).
2. Se avevi modificato `~/somamed-crm/config.env`, copia i tuoi valori nel nuovo `config.env` dopo l'installazione.
3. `cd ~/somamed` e `bash installa.sh` — aggiorna anche il collegamento con Claude Desktop.
4. Al primo avvio il database riceve l'aggiornamento **014** (indici e vista più veloce) e l'estensione pgvector passa alla 0.8. Prima di farlo, per prudenza: `bash backup.sh`.
5. Quando tutto funziona puoi cancellare la vecchia cartella `~/somamed-crm`.

## Uso quotidiano

| Comando | Cosa fa |
|---|---|
| `bash avvia.sh` | accende database, servizio dati e interfaccia; apre http://127.0.0.1:8081 — Ctrl+C per chiudere |
| `bash stato.sh` | dice se database, servizio e interfaccia funzionano |
| `bash ferma.sh` | spegne tutto (i dati restano) |
| `bash backup.sh` | copia completa in `backup/` (tiene le ultime 30) |
| `bash ripristina.sh backup/<file>` | rimette una copia (tutto o niente: se fallisce il database resta com'era) |
| `bash aggiorna.sh` | dopo aver copiato i file nuovi: backup, pacchetti, struttura del database |
| `bash cancella_dati_prova.sh` | toglie i dati inventati per le prove |

- **Controllo di salute**: http://127.0.0.1:8080/api/salute (database, versione pgvector, modello semantico).
- **Registri**: `registro/servizio.log` se qualcosa non va.
- **Se il database si spegne** mentre lavori, l'interfaccia mostra «Il database non risponde» e riprende da sola appena torna: non serve riavviare nulla.
- **Riservatezza**: database, servizio e interfaccia ascoltano solo su questo computer (127.0.0.1). Il calcolo dei vettori per la ricerca per significato avviene sul computer. Quando lavori in chat, però, i testi che detti a Claude passano dai server di Anthropic.

## Cosa è cambiato in questa versione (prestazioni e resilienza)

Misurato su un database di prova con 3.000 centri, 8.000 persone, 2.000 iniziative, 30.000 attività e 15.000 note,
50 richieste con 8 utenti contemporanei:

| | prima | ora |
|---|---|---|
| tempo totale | 32,0 s | 1,4 s (circa 22 volte più veloce) |
| Centri e mappa | 26,0 s | 0,2 s |
| Plancia di comando | 11,4 s | 0,2 s |

- **Indici** su tutti i collegamenti (centro, persona, iniziativa…): prima ogni conteggio leggeva tabelle intere.
- **Vista delle iniziative** riscritta: prima il tempo cresceva col quadrato del numero di iniziative.
- **Pool di connessioni**: le connessioni al database si riusano; ognuna viene verificata prima dell'uso, così dopo un riavvio del database il servizio si ricollega da solo.
- **Errori chiari**: database spento → «Il database non risponde» (503); dati mancanti o sbagliati → messaggio leggibile (400); query bloccate interrotte dopo 30 s.
- **Scritture atomiche**: offerte (testata + righe), importazioni da CSV/Notion, cancellazioni e aggiornamenti dello schema riescono per intero o non lasciano traccia.
- **Avvio robusto**: il servizio parte anche se il database non è ancora acceso e si aggiorna appena risponde; su un database nuovo crea da sé le estensioni.
- **Ricerca per significato**: modello caricato una volta sola e in anticipo, domande ripetute dalla cache, calcolo a blocchi per le importazioni; con pgvector 0.8 le ricerche filtrate (per centro, regione…) restituiscono sempre abbastanza risultati.
- **Interfaccia**: compressione delle risposte, letture ritentate da sole se il servizio è momentaneamente irraggiungibile.

## Budget strategico: quanto vale ogni centro e come aggredirlo

OPERATIONAL → **Budget strategico**. Prima di partire sai quali centri valgono di più, perché, e con quale strategia attaccarli.

1. **Voci di prezzo del prodotto** — gli item che generano il valore. Esempio Asimily:
   «Dispositivi medicali connessi», 40 €/dispositivo, canone per 3 anni, stima 2,5 dispositivi per posto letto;
   «Installazione», 8.000 € a sito, quantità fissa 1. (Valori di esempio: metti i tuoi prezzi e costi reali.)
2. **Organizzazione del centro** — posti letto e quante unità ha di ogni voce (scritte nella cella della tabella:
   dichiarate dal centro o censite). Dove non ci sono, il CRM stima dai posti letto o, in mancanza, dalla dimensione
   (piccolo 80, medio 250, grande 600 posti: stima grossolana, segnata in corsivo grigio). La colonna **Dati certi**
   dice quanta parte del valore poggia su dati veri.
3. **Valore di ogni centro** = Σ quantità × prezzo × anni (per i canoni) − sconto medio, e il **margine** dai costi.
4. **Fasce A/B/C** (Pareto): A = i centri che fanno il 70% del valore, B = il successivo 20%, C = il resto.
5. **Probabilità** proposta (base 20%, + persone conosciute, + relazione, + già cliente, − pubblico/gara, 5% se ha già
   rifiutato) e **valore atteso** = valore × probabilità. Puoi cambiarla centro per centro.
6. **Strategia** dalla matrice valore × accesso: *Attacco diretto* (alto valore, abbiamo accesso), *Costruire l'accesso*
   (alto valore, non conosciamo nessuno), *Sviluppo mirato* (valore medio), *Presidio marketing* (valore basso),
   *Censire prima* (mancano i dati). Nei centri pubblici si aggiunge il **percorso di gara**.
7. **Piano tattico** — un clic crea l'**iniziativa macro** del budget e, per ogni centro delle fasce scelte, la sequenza
   di attività della sua strategia, con **un'operazione per ogni voce** (verificare quantità e situazione degli
   strumenti), scaglionate (A subito, B dopo 2 settimane, C dopo 4; N centri a settimana). Rilanciarlo non duplica.
8. **Verifica** — per ogni centro: da avviare, in corso, vinto (dalle iniziative vinte, dagli esiti o dalle offerte
   accettate), perso; in alto venduto, in offerta e quanto resta da trovare rispetto al budget atteso.

A Claude: «crea il budget Asimily per la Lombardia», «lo Spedali Civili ha 1.500 posti letto e 2.600 dispositivi
connessi», «quali sono i 5 centri che valgono di più e dove non abbiamo accesso?», «genera il piano tattico per la fascia A».

## Obiettivi e sotto-obiettivi

Obiettivi → sotto-obiettivi (quanti livelli vuoi) → iniziative (campagne, opportunità, challenge) → attività.
Ogni obiettivo e sotto-obiettivo ha budget, scadenza, regioni e province, scelte cliccando sulla mappa.
Un sotto-obiettivo resta dentro le regioni del padre; le iniziative create sotto un obiettivo ne ereditano l'area.
Nella pagina Obiettivi ogni iniziativa ha il pulsante «＋ attività». Tutte le mappe si ingrandiscono con la rotella,
si spostano trascinando, e hanno i pulsanti ＋ / － / ⤢.

## Come è organizzata l'interfaccia

- **PLANCIA DI COMANDO** (pagina iniziale): numeri chiave (scadute, oggi, allerte, iniziative aperte, venduto), agenda delle attività da fare con il tasto ✓ FATTA, allerte, ultimi esiti, avanzamento degli obiettivi, iniziative attive.
- **DIARIO E AGENDA**: in cima le attività **da compiere** (da recuperare, oggi, domani, entro una settimana, più avanti, senza data) con persona, centro, telefono e mail; con «✓ Com'è andata» scrivi il resoconto, che finisce nel diario del giorno, e crei il passo successivo; «→ domani» la sposta. Sotto: annotazioni libere e la cronologia delle giornate con le attività svolte e com'è andata.
- **ESITO DI UN'ATTIVITÀ** (Piano del giorno e Diario): quattro scelte. **Operazione eseguita** apre lo spazio per i commenti (finiscono riassunti nel diario di oggi) e per il passo successivo con la sua data; **Non risponde** e **Rimanda** ripropongono l'attività nel giorno che scegli (domani, tra 3 giorni, tra una o due settimane, o una data e un'ora); **Annulla** chiede il perché, che resta nel diario.
- **CALENDARIO E CARICO**: settimana o mese con le attività pianificate come slot colorati per prodotto o per campagna/iniziativa; quanto tempo è dedicato a ciascuno nel periodo; la barra di carico di ogni giorno contro le ore disponibili (rossa se troppo pieno). Trascina un'attività per spostarla di giorno e ora. Ogni attività ha «Aggiungi a Google Calendar»; «Esporta per Google Calendar» scarica il periodo in un file .ics da importare (Google Calendar → Impostazioni → Importa). Con il connettore Google Calendar puoi chiedere a Claude di creare gli eventi.
- **PIANO DEL GIORNO** (tasto O): indichi le ore che hai a disposizione e da che ora inizi; il CRM sceglie e ordina le attività (scadute, di oggi, allerte, priorità, valore) e per ognuna mostra orario, persona con ruolo, centro, iniziativa, il perché, l'ultima volta che vi siete sentiti, il pulsante per chiamare o scrivere la mail e la **preparazione** (traccia della chiamata o testo della mail). Sotto scrivi com'è andata: ✓ Fatta (finisce nel diario e crea il passo successivo), Non risponde (richiamo tra 2 giorni), Rimanda (a domani, tra 3 giorni, una o due settimane), Annulla (con conferma). Puoi annotare cosa cambieresti nel modo di lavorare: compare tra i suggerimenti, insieme a quelli ricavati dai dati. Dì a Claude «prepara il piano di oggi, ho 5 ore»: sceglie le attività e scrive per ognuna una preparazione personalizzata.
- **OPERATIONAL**: + Nuova attività · Obiettivi (di area e di budget) · Iniziative (di marketing o commerciali) · Diario giornaliero · Persone da contattare · Allerte
- **DATI**: Contatti · Centri e mappa · Prodotti
- **VISTE**: Mappa mentale · Percorsi delle iniziative · Esplora le attività per…
- **STRUMENTI**: Importa da CSV (centri, contatti e attività, anche esportati da Notion o da Excel) · Utenti (aggiungi i collaboratori e scegli con chi stai lavorando: le nuove attività hanno lui come responsabile e il Piano del giorno mostra le sue) · Aspetto: sfondo nero o sfondo bianco · Legenda e stato
- **Offerte economiche** (OPERATIONAL → Offerte economiche; anche dalla scheda del centro e dell'iniziativa con «＋ offerta»): intestazione, lettera di accompagnamento, voci con prodotto (prezzo di listino, unità, IVA e costo presi dalla scheda prodotto), quantità, sconto per voce e sul totale; totali, IVA e margine calcolati subito (il costo non compare in stampa); condizioni di pagamento, consegna e garanzia; anteprima di stampa su carta intestata e PDF. «Segna come inviata» registra l'invio sull'iniziativa e fissa il follow-up; «Accettata» registra la vendita sul centro, «Rifiutata» il rifiuto o il concorrente scelto; «Nuova revisione» crea rev.1, rev.2… Numerazione automatica OFF-anno-progressivo. Prezzi e costi si impostano in DATI → Prodotti. A Claude: «prepara un'offerta per … con …».
- **Piano misurabile degli obiettivi** (scheda di ogni obiettivo; si apre da solo quando crei un obiettivo): un assistente fa domande precise in quattro passi — risultato, mercato, come si vende, risorse — e calcola subito quanti centri contattare, quante presentazioni, offerte e ordini servono, il ritmo settimanale, le ore di lavoro contro quelle disponibili, il costo del piano, il margine, il risultato, il costo per ordine e quanti ordini servono per andare in pari, con gli avvisi sulle ipotesi che non stanno in piedi. Con ANTHROPIC_API_KEY in config.env il pulsante «Chiedi indicazioni all'AI» fa commentare il piano a un modello AI (ipotesi da verificare, rischi, domande mancanti, prime azioni); senza chiave lo fa Claude in chat («costruiamo il piano misurabile dell'obiettivo …»).
- **Verifica degli obiettivi** (pagina Obiettivi, scheda di ogni obiettivo e Plancia): quanto è stato venduto, quanto manca, quanto è coperto dalle trattative aperte, quanto resta da trovare, previsione ponderata sulla fase raggiunta in ogni centro, confronto con il tempo trascorso (in linea / in ritardo), ritmo di vendita necessario, centri per fase e consigli. Per gli obiettivi di area si può indicare il numero di centri da conquistare. A Claude: "a che punto siamo con gli obiettivi?".
- **Scheda del centro**: riquadro "Situazione del centro" con operazioni in corso, cosa è stato venduto e con quali persone.
- **Legenda unica** (stessa forma e stesso colore in tutte le pagine e in tutti i grafi): obiettivo ▲ rosa · iniziativa ➤ blu · centro ■ azzurro · persona ● viola · prodotto ◆ argento · attività ▬ grigio. Colori di stato: verde = venduto/raggiunto, rosso = non andato (rifiuto, scelto altro), giallo = attenzione (scadute, allerte, sospeso), blu = in corso.
- **Iniziative**: non c'è più la distinzione campagna / opportunità / challenge. Sono tutte iniziative, di **marketing** o **commerciali**, a seconda delle attività che contengono. All'aggiornamento: campagne → marketing, opportunità → commerciali, challenge → commerciali se hanno un centro principale, altrimenti marketing.
- **Tasti rapidi**: N nuova attività · D diario · I nuova iniziativa · / cerca · H torna alla plancia · ESC chiude.

## Novità: avvisi, allerte, tabelle

- **"Già contattato"**: una persona può stare in più campagne. Quando crei un'attività per lei, il CRM (e Claude) ti avvisa se è già stata contattata, quando, e se ha attività aperte in altre campagne. Lo vedi anche nelle liste "Persone da contattare" e "Candidati dal target".
- **Allerte** (⏰ in alto, con il numero di quelle di oggi e scadute): sollecito, riattivazione, promemoria. Le imposti dalla scheda di persona, centro, attività o campagna (+3g, +7g, +1 mese…) o con "⏰ +7g" dalla lista da contattare. Nella vista Allerte: fatto, rimanda, trasforma in attività; a destra le persone **da riattivare** (ferme da 30–365 giorni).
- **Tabelle**: centri e contatti sono tabelle ordinabili (clic sull'intestazione) e modificabili (clic sulla cella, Invio per salvare), con riga per aggiungere e pulsante CSV per Excel. Tipi di centro: ospedale pubblico/privato, clinica, **centro medico**, **RSA**, gruppo sanitario, laboratorio…

## Come è organizzato il lavoro commerciale

**Obiettivo** → **iniziative: Iniziative di marketing e commerciali** (stessa famiglia, stesso livello: contenitori di attività su più centri e persone) → **attività** in sequenza, ognuna con il suo "perché" → **esito per ogni centro**: ✓ vendita, ✕ rifiuto, ↪ scelto un altro fornitore (con il nome), ⏸ sospesa.

- **Obiettivi e grafo** (pagina iniziale): il grafo a corsie da sinistra a destra. Ogni riga è un centro con le sue attività in fila e l'esito finale colorato. Tutto è cliccabile.
- **Iniziative** — Iniziative di marketing e commerciali sono la stessa famiglia (contenitori paritetici): elenco con numeri ed esiti; da qui crei iniziative e obiettivi. Una campagna ha **target** (pubblico/privato, dimensione, regione, province, professionalità) e **storia da raccontare**.
- **Scheda campagna**: storia, target, mappa degli esiti per provincia, grafo, persone da contattare, **candidati dal target** (con "+ primo contatto"), esiti per centro ("Chiudi ramo").
- **Persone da contattare**: chi chiamare, perché (la descrizione dell'attività), quando, recapiti, pulsante "✓ fatto".

## Novità della versione precedente

- **Centri e mappa**: mappa dell'Italia; clic su una regione → si vedono le province; clic su una provincia → elenco dei centri. Filtri pubblico/privato, piccolo/medio/grande, "solo dove conosco qualcuno".
- **Contatti**: nominativi, email, telefoni, esperienze passate, amicizie tra persone e il segno ★ "lo conosco personalmente". Dalla scheda di un centro vedi tutti i suoi contatti.
- **Attività**: nella scheda di centro e persona, separate in "da fare" e "fatte", con codice standard.
- **Diario delle giornate**: scrivi cosa è successo, collegato a centro e persona.
- **Note e ricerca**: note e diario si interrogano per centro, provincia, regione o con una domanda.
- **Importa da Notion**: dall'interfaccia, senza Terminale.
- **Il database si aggiorna da solo** all'avvio: niente più comandi di aggiornamento.

## Esempi di cosa dire a Claude

- "Registra un follow-up offerta con Mirco Fantuz venerdì alle 10, priorità alta, sulla trattativa ReDots Lifenet."
- "Quali attività aperte ho nel Nord-Est con l'ingegneria clinica?"
- "Crea l'azienda Spedali Civili di Brescia, ospedale pubblico, e il contatto Gianluca Viganò, direttore ingegneria clinica."
- "Apri una trattativa Asimily con Brescia, 45.000 €, fase demo, probabilità 30%."
- "Salva questa nota della riunione di oggi con Viganò: …"
- "Cosa ho da fare questa settimana?" / "Quali attività sono scadute?"
- "Fammi la pipeline ReDots."
- "Chi mi aveva parlato di sicurezza degli ecografi?"
- "Fammi la scheda di Lifenet."

## Gli strumenti

| Strumento | A cosa serve |
|---|---|
| oggi | data di oggi, per calcolare "venerdì", "tra due settimane" |
| crea_azienda / crea_contatto | anagrafiche |
| trova | cerca aziende e persone per nome, anche scritto male |
| scheda_azienda | tutto su un cliente in un colpo |
| crea_trattativa / aggiorna_trattativa / pipeline | opportunità per divisione |
| crea_attivita / completa_attivita / elenco_attivita | agenda commerciale |
| aggiungi_nota / ricerca_semantica | appunti e ricerca per significato |
| catalogo / crea_prodotto | attività standard, prodotti e business unit |
| aggiorna_contatto | recapiti, esperienze, "lo conosco personalmente" |
| collega_contatti | amicizie, ex colleghi, conoscenze tra persone |
| scrivi_diario / cerca_note | diario delle giornate; note per centro, provincia, regione o per significato |
| crea_obiettivo / crea_campagna | obiettivi; campagne con target e storia da raccontare |
| registra_esito | chiude il ramo di un centro: vendita, rifiuto, scelto altro, sospesa |
| persone_da_contattare / grafo_obiettivi | chi contattare e perché; situazione a grafo |
| imposta_allerta / elenco_allerte / aggiorna_allerta | solleciti, riattivazioni, promemoria |
| da_riattivare / storico_contatto | chi è fermo da tempo; tutte le volte che una persona è stata contattata |
| voci_prodotto / imposta_voce_prodotto | gli item che generano il valore di un prodotto (prezzo, costo, canone, stima per posto letto) |
| censisci_centro | posti letto e quantità delle voci in un centro |
| crea_budget_strategico / budget_strategico | valore, margine, probabilità, fascia e strategia di ogni centro di un'area |
| scelta_centro_budget / genera_piano_tattico | scelte sul singolo centro; dal budget all'iniziativa macro con le attività |

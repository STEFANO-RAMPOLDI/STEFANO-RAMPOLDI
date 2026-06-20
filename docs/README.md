# REDOTS Procurement — Sito Web

Sito marketing **multi-pagina** per **REDOTS Procurement by SomaMed**, la piattaforma
AI on-premise per il procurement sanitario.

La struttura (homepage con hero + pilastri di valore, pagine dedicate Soluzioni /
Piattaforma / Settori / Risultati, footer multi-colonna) si ispira alle migliori
pratiche dei siti enterprise di procurement come Ivalua, riadattata con contenuti
originali REDOTS e focalizzata sull'**esaltazione dei punti di forza** della soluzione.

## Struttura

```
site/
├── index.html         # Homepage: hero, punti di forza, pilastri, due lati, KPI, AI teaser
├── soluzioni.html     # Acquisti vs Vendita: problemi risolti, use case, configurazioni
├── piattaforma.html   # Come funziona, 13 agenti AI, moduli, sicurezza, compliance, roadmap
├── settori.html       # Organizzazioni e ruoli target, eventi di settore
├── risultati.html     # KPI, 4 dimensioni di valore, posizionamento
├── contatti.html      # Form richiesta demo + percorso commerciale + riferimenti
├── css/styles.css     # Design system completo (token, componenti, responsive)
├── js/layout.js       # Header/footer condivisi, nav mobile, form, animazioni scroll
└── assets/            # Spazio per immagini/logo
```

## Punti di forza esaltati

1. **AI 100% on-premise** — zero data out, GDPR Art. 9 by design, NIS2
2. **Una piattaforma, due lati** — stesso motore per chi compra e chi vende
3. **13 agenti AI specializzati** — un esperto per ogni famiglia di prodotto
4. **Normalizzazione cross-standard** — CND/EMDN/GMDN/ATC/AIC/NDC FDA
5. **Compliance built-in** — D.lgs 36/2023, MDR, NIS2, audit trail immutabile
6. **Conoscenza di dominio nativa** — ereditata dalle 4 divisioni SomaMed

## Architettura tecnica del sito

- **Statico** (HTML/CSS/JS), nessuna build necessaria.
- Header e footer sono iniettati da `js/layout.js` tramite i placeholder
  `<div data-layout="header"></div>` / `<div data-layout="footer"></div>`,
  così la navigazione resta DRY e coerente su tutte le pagine.
- La pagina attiva nel menu è determinata dall'attributo `data-page` sul `<body>`.
- Animazioni reveal-on-scroll applicate agli elementi con classe `.reveal`.

## Avvio in locale

```bash
cd site
python3 -m http.server 8080
# poi apri http://localhost:8080
```

## Note

- Form demo: validazione lato client. Per la produzione collegare un endpoint
  (invio email o creazione lead nel CRM Notion SomaMed).
- Contenuti tratti dalla scheda prodotto CRM REDOTS Procurement (SomaMed).

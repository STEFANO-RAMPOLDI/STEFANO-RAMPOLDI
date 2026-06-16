# REDOTS Procurement — Sito Web

Sito marketing one-page per **REDOTS Procurement by SomaMed**, la piattaforma AI
on-premise per il procurement sanitario.

La struttura della pagina (hero → pilastri di valore → moduli soluzione → credibilità →
call-to-action → footer multi-colonna) si ispira alle migliori pratiche dei siti
enterprise di procurement come Ivalua, riadattata con i contenuti originali REDOTS.

## Struttura

```
site/
├── index.html        # pagina unica con tutte le sezioni
├── css/styles.css    # design system (token, layout, responsive)
├── js/script.js      # nav mobile, validazione form, animazioni scroll
└── assets/           # spazio per immagini/logo
```

## Sezioni

1. **Hero** — frase sintetica di vendita + badge differenzianti
2. **Trust strip** — codifiche e standard normativi
3. **Pilastri di valore** — i 6 modi per trasformare il procurement
4. **Piattaforma a due lati** — acquisti vs vendita con motore AI condiviso
5. **Moduli** — 5 core + 8 operativi
6. **AI Agents** — 13 agenti specializzati + codifiche cross-standard
7. **Risultati** — KPI / numeri chiave per il pitch
8. **Settori / Utenti target** — ruoli lato acquisti e lato vendita
9. **Configurazioni commerciali** — Starter / Professional / Enterprise
10. **Roadmap** — implementazione in 3 fasi
11. **Differenziazione** — cosa REDOTS è / non è + stack tecnologico
12. **CTA / Contatti** — form richiesta demo
13. **Footer** — link, riferimenti SomaMed, compliance

## Avvio in locale

Nessuna build necessaria — è HTML/CSS/JS statico.

```bash
cd site
python3 -m http.server 8080
# poi apri http://localhost:8080
```

## Note

- Form demo: validazione lato client. Per andare in produzione collegare un
  endpoint (es. invio email o CRM Notion SomaMed).
- Contenuti tratti dalla scheda prodotto CRM REDOTS Procurement (SomaMed).

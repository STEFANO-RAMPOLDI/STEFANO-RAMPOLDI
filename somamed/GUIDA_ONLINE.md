# Mettere il CRM SomaMed online — guida passo passo

Risultato: il CRM risponde su un indirizzo tuo (es. `https://crm.somamed.it`), protetto da HTTPS e da utente e
password per ogni collaboratore. Database, servizio dati e interfaccia girano su un server; il database e il
servizio **non** sono raggiungibili da Internet, solo la porta d'ingresso (Caddy).

```
Internet ──HTTPS + utente/password──▶ Caddy ──▶ interfaccia (pagina)  e  /api ──▶ servizio ──▶ database
                                                                                   ▲
Claude Desktop sul Mac ───────────── tunnel SSH cifrato ──────────────────────────┘
```

Tempo: circa un'ora la prima volta. Costo: un server virtuale da pochi euro al mese più il dominio, se non l'hai.

---

## Passo 1 — Prendi un server (VPS)

- **Dove**: un fornitore con data center **nell'Unione europea** (i dati sono di professionisti sanitari: GDPR).
  Per esempio Hetzner (Germania/Finlandia), OVHcloud (Francia), Aruba Cloud (Italia). Firma con il fornitore
  l'accordo sul trattamento dei dati (DPA), di solito si accetta dal pannello.
- **Sistema**: **Ubuntu 24.04 LTS**.
- **Dimensione minima**: 2 vCPU, **4 GB di RAM**, 40 GB di disco (il modello per la ricerca per significato
  e PostgreSQL stanno comodi).
- Alla creazione aggiungi la tua **chiave SSH** (vedi passo 2) invece della password, se il pannello lo permette.
- Annota l'**indirizzo IP** del server (es. `203.0.113.10`).

## Passo 2 — Chiave SSH sul Mac (una volta sola)

Serve per entrare nel server senza password e, più avanti, per collegare Claude Desktop.

1. Terminale del Mac: `ls ~/.ssh/id_ed25519.pub` — se il file esiste, salta al punto 3.
2. Altrimenti: `ssh-keygen -t ed25519` (Invio alle domande; una passphrase è consigliata).
3. Se non l'hai data al fornitore: `ssh-copy-id root@203.0.113.10` (con l'IP del tuo server).
4. Prova: `ssh root@203.0.113.10` — devi entrare. Esci con `exit`.

**Consigliato**: crea sul server un utente tuo e lavora con quello invece che con `root`:
```
ssh root@203.0.113.10
adduser stefano            # scegli una password
usermod -aG sudo stefano
rsync -a ~/.ssh /home/stefano/ && chown -R stefano:stefano /home/stefano/.ssh
exit
```
Da qui in poi `stefano@203.0.113.10` (sostituisci con il tuo nome utente e il tuo IP).

## Passo 3 — L'indirizzo (DNS)

Nel pannello del tuo dominio crea un record:

| Tipo | Nome | Valore |
|---|---|---|
| A | `crm` | `203.0.113.10` (IP del server) |

Dopo qualche minuto `crm.tuodominio.it` punta al server. Verifica dal Mac: `ping crm.tuodominio.it` deve mostrare l'IP.

## Passo 4 — Copia il programma sul server (dal Mac)

```
cd ~/somamed
bash produzione/pubblica.sh stefano@203.0.113.10
```
Copia la cartella `somamed` nella home del server (senza le tue impostazioni locali né i dati del Mac).

## Passo 5 — Installa sul server

```
ssh stefano@203.0.113.10
cd ~/somamed/produzione
sudo bash installa_server.sh
```
Lo script:
1. installa Docker;
2. accende il firewall lasciando aperti solo SSH, HTTP e HTTPS;
3. chiede l'indirizzo (es. `crm.tuodominio.it`) e **genera da solo** la password del database e la chiave interna (in `produzione/.env`, leggibile solo da te);
4. controlla che il DNS punti a questo server;
5. ti fa creare il **primo utente** (nome e password di almeno 12 caratteri);
6. avvia tutto e ottiene il certificato HTTPS (Let's Encrypt).

Alla fine scrive l'indirizzo. La prima volta ci vogliono alcuni minuti (si costruisce il servizio e si scarica il modello semantico).
Poi **esci (`exit`) e rientra con ssh**: da lì in avanti i comandi `docker` e gli script funzionano senza `sudo`.

## Passo 6 — Prova

Apri `https://crm.tuodominio.it`: il browser chiede utente e password, poi compare la Plancia (vuota).
Controllo tecnico: `https://crm.tuodominio.it/api/salute` deve dire `"database":"ok"` e `"pgvector":"0.8.7"`.

## Passo 7 — Porta i dati del Mac online (una volta)

Sul Mac, con il CRM locale acceso (Docker Desktop aperto):
```
cd ~/somamed
bash produzione/carica_dati.sh stefano@203.0.113.10
```
Fa una copia dei dati del Mac, la invia al server, salva una copia del database online e lo sostituisce
(scrivi `SI` quando lo chiede). Da questo momento **lavora solo online**: le modifiche fatte sul Mac non si
sincronizzano più.

## Passo 8 — Aggiungi i collaboratori

Sul server:
```
cd ~/somamed/produzione
bash utente.sh aggiungi mario       # chiede la password
bash utente.sh elenco
bash utente.sh togli mario          # toglie l'accesso subito
```
Le modifiche valgono subito, senza spegnere niente. Ognuno ha il suo nome e la sua password: non condividerle.
Nell'interfaccia (Strumenti → Utenti) ogni collaboratore sceglie il proprio nome, così le attività gli vengono assegnate.

## Passo 9 — Claude Desktop sul CRM online (facoltativo)

Sul Mac:
```
cd ~/somamed
bash produzione/collega_claude.sh stefano@203.0.113.10
```
Chiudi Claude Desktop (Cmd+Q) e riaprilo. Claude raggiunge il database online con un tunnel SSH cifrato che si
apre da solo; il database resta chiuso verso Internet. Per tornare al database del Mac: `bash installa.sh`.

---

## Uso quotidiano

| Cosa | Dove | Comando |
|---|---|---|
| Aggiornare il programma | Mac, poi server | `bash produzione/pubblica.sh stefano@IP` → sul server `cd ~/somamed/produzione && bash aggiorna_server.sh` |
| Copie di sicurezza | server | automatiche ogni notte alle 2 in `~/somamed/produzione/backup` (14 giorni) |
| Rimettere una copia | server | `bash ripristina_server.sh backup/<file>.sql.gz` |
| Vedere se tutto va | ovunque | `https://crm.tuodominio.it/api/salute` |
| Registri | server | `cd ~/somamed/produzione && docker compose logs --tail 100` |
| Spegnere / riaccendere | server | `docker compose stop` / `docker compose up -d` |

**Copia fuori dal server** (consigliata, una volta a settimana dal Mac):
`scp "stefano@203.0.113.10:somamed/produzione/backup/somamed_*.sql.gz" ~/Documents/backup-crm/`
Se il server si guasta, le copie che stanno solo lì si perdono con lui. Attiva anche gli snapshot del fornitore, se li offre.

## Sicurezza: cosa c'è e cosa manca

C'è:
- HTTPS obbligatorio (HTTP viene rimandato su HTTPS) con certificato rinnovato da solo;
- utente e password per ognuno; senza credenziali non si vede nemmeno la pagina;
- servizio dati e database non esposti; il servizio accetta solo richieste che passano da Caddy (chiave interna);
- firewall con solo SSH/HTTP/HTTPS; password generate casualmente; copie notturne verificate.

Manca ancora (prossimi passi, vedi ARCHITETTURA.md §4):
- **permessi per ruolo**: oggi chi entra vede e modifica tutto, compreso «Cancella dati» in Strumenti;
- **registro di chi ha fatto cosa** (Caddy già passa il nome dell'utente al servizio, va solo registrato);
- accesso con Google/Microsoft e autenticazione a due fattori.

Finché mancano, dai l'accesso solo a persone di fiducia.

## Se qualcosa non va

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| Il browser dice che il sito non è sicuro | certificato non ancora ottenuto | DNS non pronto o porte 80/443 chiuse dal fornitore: `docker compose logs web` |
| `installa_server.sh` si ferma sul DNS | record A non ancora propagato | aspetta 10–30 minuti e rilancia |
| «Il database non risponde» | database fermo | `docker compose ps`, poi `docker compose up -d` |
| Claude Desktop non vede il CRM | tunnel SSH | prova `ssh -o BatchMode=yes stefano@IP true`; se chiede la password rifai il passo 2 |
| `pubblica.sh` dice «rsync: command not found» | manca rsync sul server | sul server `sudo apt-get install -y rsync` |
| Password dimenticata | — | sul server `bash utente.sh aggiungi <nome>` (la sostituisce) |

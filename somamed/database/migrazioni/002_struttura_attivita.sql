-- Aggiornamento 002: attività standardizzate, prodotti, aree geografiche, professionalità.
-- Si può lanciare più volte senza danni.

-- Regioni e macro-aree
CREATE TABLE IF NOT EXISTS regioni (
    nome TEXT PRIMARY KEY,
    area TEXT NOT NULL
);
INSERT INTO regioni (nome, area) VALUES
    ('Piemonte','Nord-Ovest'),('Valle d''Aosta','Nord-Ovest'),('Lombardia','Nord-Ovest'),('Liguria','Nord-Ovest'),
    ('Trentino-Alto Adige','Nord-Est'),('Veneto','Nord-Est'),('Friuli-Venezia Giulia','Nord-Est'),('Emilia-Romagna','Nord-Est'),
    ('Toscana','Centro'),('Umbria','Centro'),('Marche','Centro'),('Lazio','Centro'),
    ('Abruzzo','Sud'),('Molise','Sud'),('Campania','Sud'),('Puglia','Sud'),('Basilicata','Sud'),('Calabria','Sud'),
    ('Sicilia','Isole'),('Sardegna','Isole'),
    ('Estero','Estero')
ON CONFLICT DO NOTHING;

-- Catalogo delle attività standard, in ordine di sequenza commerciale
CREATE TABLE IF NOT EXISTS catalogo_attivita (
    codice      TEXT PRIMARY KEY,
    nome        TEXT NOT NULL UNIQUE,
    ordine      INT  NOT NULL,
    descrizione TEXT
);
INSERT INTO catalogo_attivita (codice, nome, ordine, descrizione) VALUES
    ('STD-010','Primo contatto',            10,'Primo approccio con il centro o la persona'),
    ('STD-020','Qualifica esigenza',        20,'Capire bisogno, budget, tempi, chi decide'),
    ('STD-030','Presentazione prodotto',    30,'Presentazione della soluzione'),
    ('STD-040','Demo / prova',              40,'Dimostrazione o prova sul campo'),
    ('STD-050','Sopralluogo tecnico',       50,'Visita tecnica al sito'),
    ('STD-060','Raccolta dati',             60,'Raccolta dati, documenti, estrazioni'),
    ('STD-070','Offerta',                   70,'Preparazione e invio offerta'),
    ('STD-080','Follow-up offerta',         80,'Verifica dell''offerta inviata'),
    ('STD-090','Negoziazione',              90,'Trattativa su prezzo e condizioni'),
    ('STD-100','Gara / procedura pubblica',100,'Partecipazione a gara o procedura'),
    ('STD-110','Ordine / contratto',       110,'Firma ordine o contratto'),
    ('STD-120','Consegna / installazione', 120,'Consegna, installazione, avvio'),
    ('STD-130','Formazione',               130,'Formazione degli utenti'),
    ('STD-140','Assistenza / post-vendita',140,'Supporto e manutenzione dopo la vendita')
ON CONFLICT DO NOTHING;

-- Prodotti, ognuno appartiene a una business unit (divisione)
CREATE TABLE IF NOT EXISTS prodotti (
    id          BIGSERIAL PRIMARY KEY,
    nome        TEXT NOT NULL UNIQUE,
    divisione   TEXT NOT NULL DEFAULT 'Altro' REFERENCES divisioni(nome),
    produttore  TEXT,
    descrizione TEXT,
    creato_il   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS prodotti_nome_trgm ON prodotti USING gin (nome gin_trgm_ops);
INSERT INTO prodotti (nome, divisione, produttore) VALUES
    ('ReDots Procurement Intelligence','ReDots','SomaMed'),
    ('Asimily cybersecurity dispositivi medici','Asimily','Asimily'),
    ('deepc AI radiologia','deepc','deepc'),
    ('Lepu AI-ECG','Lepu','Lepu Medical'),
    ('Airdoc AI retina','Airdoc','Airdoc'),
    ('Percorso i-LARI','i-LARI','i-LARI'),
    ('Schermatura RM','ITEL','ITEL'),
    ('Radiofarmacia / medicina nucleare','ITEL','ITEL')
ON CONFLICT DO NOTHING;

-- Nuovi campi
ALTER TABLE contatti   ADD COLUMN IF NOT EXISTS professionalita TEXT;
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS prodotto_id BIGINT REFERENCES prodotti(id) ON DELETE SET NULL;
ALTER TABLE attivita   ADD COLUMN IF NOT EXISTS codice_standard TEXT REFERENCES catalogo_attivita(codice);
ALTER TABLE attivita   ADD COLUMN IF NOT EXISTS prodotto_id BIGINT REFERENCES prodotti(id) ON DELETE SET NULL;
ALTER TABLE attivita   ADD COLUMN IF NOT EXISTS precedente_id BIGINT REFERENCES attivita(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS attivita_precedente ON attivita (precedente_id);

-- Vista unica: ogni attività con tutti i suoi collegamenti
DROP VIEW IF EXISTS v_attivita CASCADE;
CREATE VIEW v_attivita AS
SELECT at.id, at.tipo, at.codice_standard, ca.nome AS standard, ca.ordine AS ordine_standard,
       at.descrizione, at.scadenza, at.stato, at.priorita, at.responsabile, at.esito,
       at.completata_il, at.creata_il, at.precedente_id,
       (SELECT s.id FROM attivita s WHERE s.precedente_id = at.id ORDER BY s.id LIMIT 1) AS successiva_id,
       (at.stato = 'da fare' AND at.scadenza < now()) AS scaduta,
       a.id AS azienda_id, a.nome AS azienda, a.tipo AS tipo_centro, a.citta, a.regione,
       coalesce(r.area, 'Non indicata') AS area,
       c.id AS contatto_id, nullif(trim(coalesce(c.nome,'') || ' ' || coalesce(c.cognome,'')), '') AS contatto,
       c.ruolo, coalesce(c.professionalita, 'Non indicata') AS professionalita,
       p.id AS prodotto_id, p.nome AS prodotto,
       t.id AS trattativa_id, t.titolo AS trattativa, t.fase AS fase_trattativa,
       coalesce(p.divisione, tp.divisione, t.divisione, 'Non indicata') AS bu
FROM attivita at
LEFT JOIN catalogo_attivita ca ON ca.codice = at.codice_standard
LEFT JOIN aziende a   ON a.id = at.azienda_id
LEFT JOIN regioni r   ON lower(r.nome) = lower(a.regione)
LEFT JOIN contatti c  ON c.id = at.contatto_id
LEFT JOIN prodotti p  ON p.id = at.prodotto_id
LEFT JOIN trattative t ON t.id = at.trattativa_id
LEFT JOIN prodotti tp ON tp.id = t.prodotto_id;

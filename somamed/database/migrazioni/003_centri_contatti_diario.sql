-- Aggiornamento 003: province, centri pubblici/privati e dimensione, contatti estesi,
-- amicizie tra contatti, diario delle giornate. Si può lanciare più volte.

CREATE TABLE IF NOT EXISTS province (
    sigla   TEXT PRIMARY KEY,
    nome    TEXT NOT NULL,
    regione TEXT NOT NULL
);
INSERT INTO province (sigla, nome, regione) VALUES
    ('TO','Torino','Piemonte'),
    ('VC','Vercelli','Piemonte'),
    ('NO','Novara','Piemonte'),
    ('CN','Cuneo','Piemonte'),
    ('AT','Asti','Piemonte'),
    ('AL','Alessandria','Piemonte'),
    ('AO','Valle d''Aosta/Vallée d''Aoste','Valle d''Aosta'),
    ('IM','Imperia','Liguria'),
    ('SV','Savona','Liguria'),
    ('GE','Genova','Liguria'),
    ('SP','La Spezia','Liguria'),
    ('VA','Varese','Lombardia'),
    ('CO','Como','Lombardia'),
    ('SO','Sondrio','Lombardia'),
    ('MI','Milano','Lombardia'),
    ('BG','Bergamo','Lombardia'),
    ('BS','Brescia','Lombardia'),
    ('PV','Pavia','Lombardia'),
    ('CR','Cremona','Lombardia'),
    ('MN','Mantova','Lombardia'),
    ('BZ','Bolzano/Bozen','Trentino-Alto Adige'),
    ('TN','Trento','Trentino-Alto Adige'),
    ('VR','Verona','Veneto'),
    ('VI','Vicenza','Veneto'),
    ('BL','Belluno','Veneto'),
    ('TV','Treviso','Veneto'),
    ('VE','Venezia','Veneto'),
    ('PD','Padova','Veneto'),
    ('RO','Rovigo','Veneto'),
    ('UD','Udine','Friuli-Venezia Giulia'),
    ('GO','Gorizia','Friuli-Venezia Giulia'),
    ('TS','Trieste','Friuli-Venezia Giulia'),
    ('PC','Piacenza','Emilia-Romagna'),
    ('PR','Parma','Emilia-Romagna'),
    ('RE','Reggio nell''Emilia','Emilia-Romagna'),
    ('MO','Modena','Emilia-Romagna'),
    ('BO','Bologna','Emilia-Romagna'),
    ('FE','Ferrara','Emilia-Romagna'),
    ('RA','Ravenna','Emilia-Romagna'),
    ('FC','Forlì-Cesena','Emilia-Romagna'),
    ('PU','Pesaro e Urbino','Marche'),
    ('AN','Ancona','Marche'),
    ('MC','Macerata','Marche'),
    ('AP','Ascoli Piceno','Marche'),
    ('MS','Massa-Carrara','Toscana'),
    ('LU','Lucca','Toscana'),
    ('PT','Pistoia','Toscana'),
    ('FI','Firenze','Toscana'),
    ('LI','Livorno','Toscana'),
    ('PI','Pisa','Toscana'),
    ('AR','Arezzo','Toscana'),
    ('SI','Siena','Toscana'),
    ('GR','Grosseto','Toscana'),
    ('PG','Perugia','Umbria'),
    ('TR','Terni','Umbria'),
    ('VT','Viterbo','Lazio'),
    ('RI','Rieti','Lazio'),
    ('RM','Roma','Lazio'),
    ('LT','Latina','Lazio'),
    ('FR','Frosinone','Lazio'),
    ('CE','Caserta','Campania'),
    ('BN','Benevento','Campania'),
    ('NA','Napoli','Campania'),
    ('AV','Avellino','Campania'),
    ('SA','Salerno','Campania'),
    ('AQ','L''Aquila','Abruzzo'),
    ('TE','Teramo','Abruzzo'),
    ('PE','Pescara','Abruzzo'),
    ('CH','Chieti','Abruzzo'),
    ('CB','Campobasso','Molise'),
    ('FG','Foggia','Puglia'),
    ('BA','Bari','Puglia'),
    ('TA','Taranto','Puglia'),
    ('BR','Brindisi','Puglia'),
    ('LE','Lecce','Puglia'),
    ('PZ','Potenza','Basilicata'),
    ('MT','Matera','Basilicata'),
    ('CS','Cosenza','Calabria'),
    ('CZ','Catanzaro','Calabria'),
    ('RC','Reggio Calabria','Calabria'),
    ('TP','Trapani','Sicilia'),
    ('PA','Palermo','Sicilia'),
    ('ME','Messina','Sicilia'),
    ('AG','Agrigento','Sicilia'),
    ('CL','Caltanissetta','Sicilia'),
    ('EN','Enna','Sicilia'),
    ('CT','Catania','Sicilia'),
    ('RG','Ragusa','Sicilia'),
    ('SR','Siracusa','Sicilia'),
    ('PN','Pordenone','Friuli-Venezia Giulia'),
    ('IS','Isernia','Molise'),
    ('BI','Biella','Piemonte'),
    ('LC','Lecco','Lombardia'),
    ('LO','Lodi','Lombardia'),
    ('RN','Rimini','Emilia-Romagna'),
    ('PO','Prato','Toscana'),
    ('KR','Crotone','Calabria'),
    ('VV','Vibo Valentia','Calabria'),
    ('VB','Verbano-Cusio-Ossola','Piemonte'),
    ('MB','Monza e della Brianza','Lombardia'),
    ('FM','Fermo','Marche'),
    ('BT','Barletta-Andria-Trani','Puglia'),
    ('SS','Sassari','Sardegna'),
    ('OT','Gallura Nord-Est Sardegna','Sardegna'),
    ('NU','Nuoro','Sardegna'),
    ('OR','Oristano','Sardegna'),
    ('OG','Ogliastra','Sardegna'),
    ('VS','Medio Campidano','Sardegna'),
    ('CA','Cagliari','Sardegna'),
    ('CI','Sulcis Iglesiente','Sardegna')
ON CONFLICT DO NOTHING;

-- Centri
ALTER TABLE aziende DROP CONSTRAINT IF EXISTS aziende_tipo_check;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS provincia TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS indirizzo TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS cap TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS natura TEXT;        -- pubblico / privato / privato accreditato
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS dimensione TEXT;    -- piccolo / medio / grande
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS telefono TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS ats TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS relazione TEXT;     -- forza relazione: forte / media / debole / da costruire
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS strategicita TEXT;
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS notion_url TEXT;
CREATE INDEX IF NOT EXISTS aziende_provincia ON aziende (upper(provincia));

-- Contatti
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS email_privata TEXT;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS cellulare TEXT;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS telefono_privato TEXT;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS linkedin TEXT;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS esperienze TEXT;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS conosciuto_personalmente BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS business TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS notion_url TEXT;
ALTER TABLE contatti ADD COLUMN IF NOT EXISTS chiave_import TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS contatti_chiave_import ON contatti (chiave_import);

-- Amicizie / conoscenze tra persone
CREATE TABLE IF NOT EXISTS relazioni_contatti (
    id          BIGSERIAL PRIMARY KEY,
    contatto_a  BIGINT NOT NULL REFERENCES contatti(id) ON DELETE CASCADE,
    contatto_b  BIGINT NOT NULL REFERENCES contatti(id) ON DELETE CASCADE,
    tipo        TEXT NOT NULL DEFAULT 'amicizia',   -- amicizia / ex collega / collega / conoscenza / parente
    note        TEXT,
    creata_il   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (contatto_a <> contatto_b)
);
CREATE UNIQUE INDEX IF NOT EXISTS relazioni_coppia
    ON relazioni_contatti (least(contatto_a, contatto_b), greatest(contatto_a, contatto_b), tipo);

-- Diario delle giornate
CREATE TABLE IF NOT EXISTS diario (
    id          BIGSERIAL PRIMARY KEY,
    giorno      DATE NOT NULL DEFAULT current_date,
    testo       TEXT NOT NULL,
    azienda_id  BIGINT REFERENCES aziende(id) ON DELETE SET NULL,
    contatto_id BIGINT REFERENCES contatti(id) ON DELETE SET NULL,
    embedding   vector(384),
    creato_il   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS diario_giorno ON diario (giorno DESC);
CREATE INDEX IF NOT EXISTS diario_emb ON diario USING hnsw (embedding vector_cosine_ops);

-- Attività importate
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS notion_url TEXT;
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS chiave_import TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS attivita_chiave_import ON attivita (chiave_import);
ALTER TABLE note ADD COLUMN IF NOT EXISTS chiave_import TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS note_chiave_import ON note (chiave_import);

-- Centri con provincia, regione e area
DROP VIEW IF EXISTS v_note CASCADE;
DROP VIEW IF EXISTS v_attivita CASCADE;
DROP VIEW IF EXISTS v_aziende CASCADE;
CREATE VIEW v_aziende AS
SELECT a.*, pv.nome AS provincia_nome,
       coalesce(pv.regione, a.regione) AS regione_eff,
       coalesce(r.area, 'Non indicata') AS area,
       (SELECT count(*) FROM contatti c WHERE c.azienda_id = a.id) AS n_contatti,
       (SELECT count(*) FROM contatti c WHERE c.azienda_id = a.id AND c.conosciuto_personalmente) AS n_conosciuti,
       (SELECT count(*) FROM attivita t WHERE t.azienda_id = a.id AND t.stato = 'da fare') AS n_aperte
FROM aziende a
LEFT JOIN province pv ON upper(pv.sigla) = upper(a.provincia)
LEFT JOIN regioni r ON lower(r.nome) = lower(coalesce(pv.regione, a.regione));

-- Attività con tutti i collegamenti (ora anche provincia e regione)
DROP VIEW IF EXISTS v_attivita;
CREATE VIEW v_attivita AS
SELECT at.id, at.tipo, at.codice_standard, ca.nome AS standard, ca.ordine AS ordine_standard,
       at.descrizione, at.scadenza, at.stato, at.priorita, at.responsabile, at.esito,
       at.completata_il, at.creata_il, at.precedente_id,
       (SELECT s.id FROM attivita s WHERE s.precedente_id = at.id ORDER BY s.id LIMIT 1) AS successiva_id,
       (at.stato = 'da fare' AND at.scadenza < now()) AS scaduta,
       a.id AS azienda_id, a.nome AS azienda, a.tipo AS tipo_centro, a.citta,
       coalesce(a.regione_eff, 'Non indicata') AS regione, coalesce(upper(a.provincia), 'Non indicata') AS provincia,
       coalesce(a.natura, 'Non indicata') AS natura, coalesce(a.dimensione, 'Non indicata') AS dimensione,
       coalesce(a.area, 'Non indicata') AS area,
       c.id AS contatto_id, nullif(trim(coalesce(c.nome,'') || ' ' || coalesce(c.cognome,'')), '') AS contatto,
       c.ruolo, coalesce(c.professionalita, 'Non indicata') AS professionalita,
       coalesce(c.conosciuto_personalmente, false) AS conosciuto,
       p.id AS prodotto_id, p.nome AS prodotto,
       t.id AS trattativa_id, t.titolo AS trattativa, t.fase AS fase_trattativa,
       coalesce(p.divisione, tp.divisione, t.divisione, 'Non indicata') AS bu
FROM attivita at
LEFT JOIN catalogo_attivita ca ON ca.codice = at.codice_standard
LEFT JOIN v_aziende a  ON a.id = at.azienda_id
LEFT JOIN contatti c   ON c.id = at.contatto_id
LEFT JOIN prodotti p   ON p.id = at.prodotto_id
LEFT JOIN trattative t ON t.id = at.trattativa_id
LEFT JOIN prodotti tp  ON tp.id = t.prodotto_id;

-- Note e diario insieme, interrogabili per centro, provincia, regione
CREATE VIEW v_note AS
SELECT 'nota'::text AS genere, n.id, n.testo, n.fonte, n.creata_il::date AS giorno, n.creata_il,
       n.azienda_id, a.nome AS azienda, upper(a.provincia) AS provincia, a.regione_eff AS regione,
       n.contatto_id, nullif(trim(coalesce(c.nome,'') || ' ' || coalesce(c.cognome,'')), '') AS contatto,
       n.embedding
FROM note n LEFT JOIN v_aziende a ON a.id = n.azienda_id LEFT JOIN contatti c ON c.id = n.contatto_id
UNION ALL
SELECT 'diario', d.id, d.testo, 'diario', d.giorno, d.creato_il,
       d.azienda_id, a.nome, upper(a.provincia), a.regione_eff,
       d.contatto_id, nullif(trim(coalesce(c.nome,'') || ' ' || coalesce(c.cognome,'')), ''),
       d.embedding
FROM diario d LEFT JOIN v_aziende a ON a.id = d.azienda_id LEFT JOIN contatti c ON c.id = d.contatto_id;

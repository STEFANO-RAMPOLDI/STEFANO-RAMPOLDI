-- Aggiornamento 004: obiettivi; campagne e opportunità come contenitori di attività su più
-- centri e persone; target e "storia da raccontare"; esito finale per ogni centro.
-- Si può lanciare più volte.

CREATE TABLE IF NOT EXISTS obiettivi (
    id            BIGSERIAL PRIMARY KEY,
    titolo        TEXT NOT NULL,
    descrizione   TEXT,
    scadenza      DATE,
    valore_eur    NUMERIC(14,2),
    stato         TEXT NOT NULL DEFAULT 'attivo',      -- attivo / raggiunto / abbandonato
    creato_il     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Le "trattative" diventano i contenitori: genere = campagna oppure opportunità
ALTER TABLE trattative DROP CONSTRAINT IF EXISTS trattative_fase_check;
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS genere TEXT NOT NULL DEFAULT 'opportunita';
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS obiettivo_id BIGINT REFERENCES obiettivi(id) ON DELETE SET NULL;
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS storia TEXT;              -- la storia da raccontare
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS target JSONB NOT NULL DEFAULT '{}';
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS data_inizio DATE;
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS esito TEXT;               -- vendita / rifiuto / scelto altro / sospesa
ALTER TABLE trattative ADD COLUMN IF NOT EXISTS concorrente TEXT;

-- Esito finale di ogni centro dentro una campagna o opportunità
CREATE TABLE IF NOT EXISTS esiti_centro (
    id            BIGSERIAL PRIMARY KEY,
    trattativa_id BIGINT NOT NULL REFERENCES trattative(id) ON DELETE CASCADE,
    azienda_id    BIGINT NOT NULL REFERENCES aziende(id) ON DELETE CASCADE,
    esito         TEXT NOT NULL CHECK (esito IN ('vendita','rifiuto','scelto altro','sospesa')),
    concorrente   TEXT,
    note          TEXT,
    data          DATE NOT NULL DEFAULT current_date,
    UNIQUE (trattativa_id, azienda_id)
);

-- Contenitori con i loro numeri
CREATE OR REPLACE VIEW v_iniziative AS
WITH coinvolti AS (
    SELECT t.id, a.azienda_id, a.contatto_id, a.stato
    FROM trattative t JOIN attivita a ON a.trattativa_id = t.id
)
SELECT t.*, o.titolo AS obiettivo, p.nome AS prodotto, az.nome AS azienda,
       (SELECT count(DISTINCT x) FROM (SELECT c.azienda_id x FROM coinvolti c WHERE c.id = t.id
                                       UNION SELECT t.azienda_id WHERE t.azienda_id IS NOT NULL) u WHERE x IS NOT NULL) AS n_centri,
       (SELECT count(DISTINCT c.contatto_id) FROM coinvolti c WHERE c.id = t.id) AS n_persone,
       (SELECT count(*) FROM coinvolti c WHERE c.id = t.id) AS n_attivita,
       (SELECT count(*) FROM coinvolti c WHERE c.id = t.id AND c.stato = 'da fare') AS n_aperte,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'vendita') AS n_vendite,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'rifiuto') AS n_rifiuti,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'scelto altro') AS n_scelto_altro,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'sospesa') AS n_sospese
FROM trattative t
LEFT JOIN obiettivi o ON o.id = t.obiettivo_id
LEFT JOIN prodotti p ON p.id = t.prodotto_id
LEFT JOIN aziende az ON az.id = t.azienda_id;

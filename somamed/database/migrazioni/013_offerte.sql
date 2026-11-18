-- Aggiornamento 013: offerte economiche. Si può lanciare più volte.
ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS prezzo_listino NUMERIC(14,2);   -- prezzo di vendita IVA esclusa
ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS costo NUMERIC(14,2);            -- costo d'acquisto, per il margine
ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS unita TEXT DEFAULT 'pz';        -- pz, licenza/anno, giornata, mq …
ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS aliquota_iva NUMERIC(5,2) DEFAULT 22;

CREATE TABLE IF NOT EXISTS offerte (
    id              BIGSERIAL PRIMARY KEY,
    numero          TEXT NOT NULL,                 -- OFF-2026-001
    revisione       INTEGER NOT NULL DEFAULT 0,
    origine_id      BIGINT REFERENCES offerte(id) ON DELETE SET NULL,   -- revisione di…
    stato           TEXT NOT NULL DEFAULT 'bozza'
                    CHECK (stato IN ('bozza','inviata','accettata','rifiutata','annullata','superata')),
    data            DATE NOT NULL DEFAULT current_date,
    validita_giorni INTEGER NOT NULL DEFAULT 60,
    oggetto         TEXT NOT NULL,
    premessa        TEXT,                          -- lettera di accompagnamento
    azienda_id      BIGINT REFERENCES aziende(id) ON DELETE SET NULL,
    contatto_id     BIGINT REFERENCES contatti(id) ON DELETE SET NULL,
    trattativa_id   BIGINT REFERENCES trattative(id) ON DELETE SET NULL,
    pagamento       TEXT DEFAULT 'Bonifico bancario 60 giorni data fattura fine mese',
    consegna        TEXT DEFAULT 'Da concordare alla conferma d''ordine',
    garanzia        TEXT DEFAULT '12 mesi dalla data di installazione',
    note            TEXT,
    sconto_globale  NUMERIC(5,2) NOT NULL DEFAULT 0,
    imponibile      NUMERIC(14,2) NOT NULL DEFAULT 0,
    iva             NUMERIC(14,2) NOT NULL DEFAULT 0,
    totale          NUMERIC(14,2) NOT NULL DEFAULT 0,
    costo_totale    NUMERIC(14,2) NOT NULL DEFAULT 0,
    responsabile    TEXT,
    inviata_il      DATE,
    chiusa_il       DATE,
    esito_note      TEXT,
    concorrente     TEXT,
    creata_il       TIMESTAMPTZ NOT NULL DEFAULT now(),
    aggiornata_il   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS offerte_numero_rev ON offerte(numero, revisione);
CREATE INDEX IF NOT EXISTS offerte_azienda ON offerte(azienda_id);
CREATE INDEX IF NOT EXISTS offerte_trattativa ON offerte(trattativa_id);

CREATE TABLE IF NOT EXISTS offerte_righe (
    id            BIGSERIAL PRIMARY KEY,
    offerta_id    BIGINT NOT NULL REFERENCES offerte(id) ON DELETE CASCADE,
    ordine        INTEGER NOT NULL DEFAULT 0,
    prodotto_id   BIGINT REFERENCES prodotti(id) ON DELETE SET NULL,
    descrizione   TEXT NOT NULL,
    quantita      NUMERIC(12,2) NOT NULL DEFAULT 1,
    unita         TEXT DEFAULT 'pz',
    prezzo        NUMERIC(14,2) NOT NULL DEFAULT 0,     -- prezzo unitario IVA esclusa
    sconto        NUMERIC(5,2) NOT NULL DEFAULT 0,      -- %
    aliquota_iva  NUMERIC(5,2) NOT NULL DEFAULT 22,
    costo         NUMERIC(14,2)                          -- costo unitario, non stampato
);

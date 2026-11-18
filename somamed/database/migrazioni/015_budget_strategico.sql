-- Aggiornamento 015: budget strategico per centro, calcolato dalle voci (item) che generano il valore del prodotto.
--
--   prodotto ──< voci di prezzo (es. Asimily: dispositivi medicali connessi, € per dispositivo/anno)
--   centro   ──< censimento: quante unità di ogni voce ha il centro (dichiarate, censite o stimate dai posti letto)
--   budget strategico (prodotto + area) ──< centri del budget: valore potenziale, margine, probabilità, fascia, strategia
--   piano tattico: un'iniziativa "macro" del budget che raccoglie le attività su centri e strumenti
-- Si può lanciare più volte.

-- organizzazione del centro: serve a stimare le quantità quando non sono ancora censite
ALTER TABLE aziende ADD COLUMN IF NOT EXISTS posti_letto INT CHECK (posti_letto IS NULL OR posti_letto >= 0);

-- voci di prezzo di un prodotto
CREATE TABLE IF NOT EXISTS prodotti_voci (
    id                    BIGSERIAL PRIMARY KEY,
    prodotto_id           BIGINT NOT NULL REFERENCES prodotti(id) ON DELETE CASCADE,
    nome                  TEXT NOT NULL,
    unita                 TEXT NOT NULL DEFAULT 'pz',
    prezzo_unitario       NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (prezzo_unitario >= 0),
    costo_unitario        NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (costo_unitario >= 0),
    ricorrente            BOOLEAN NOT NULL DEFAULT false,        -- canone (per anno) o una tantum
    anni                  INT NOT NULL DEFAULT 1 CHECK (anni BETWEEN 1 AND 10),  -- durata contratto per i canoni
    stima_per_posto_letto NUMERIC(10,3),                         -- unità per posto letto, per stimare
    quantita_fissa        NUMERIC(12,2),                         -- es. 1 installazione per centro
    ordine                INT NOT NULL DEFAULT 0,
    note                  TEXT,
    creata_il             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prodotto_id, nome)
);

-- censimento: quante unità di ogni voce ha ciascun centro
CREATE TABLE IF NOT EXISTS centri_voci (
    azienda_id     BIGINT NOT NULL REFERENCES aziende(id) ON DELETE CASCADE,
    voce_id        BIGINT NOT NULL REFERENCES prodotti_voci(id) ON DELETE CASCADE,
    quantita       NUMERIC(12,2) NOT NULL CHECK (quantita >= 0),
    fonte          TEXT NOT NULL DEFAULT 'dichiarata' CHECK (fonte IN ('stimata','dichiarata','censita')),
    note           TEXT,
    aggiornato_il  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (azienda_id, voce_id)
);
CREATE INDEX IF NOT EXISTS centri_voci_voce ON centri_voci (voce_id);

-- budget strategico
CREATE TABLE IF NOT EXISTS budget (
    id            BIGSERIAL PRIMARY KEY,
    titolo        TEXT NOT NULL,
    prodotto_id   BIGINT NOT NULL REFERENCES prodotti(id) ON DELETE RESTRICT,
    obiettivo_id  BIGINT REFERENCES obiettivi(id) ON DELETE SET NULL,
    anno          INT,
    regioni       TEXT[] NOT NULL DEFAULT '{}',
    province      TEXT[] NOT NULL DEFAULT '{}',
    tipi          TEXT[] NOT NULL DEFAULT '{}',   -- tipi di centro; vuoto = tipologie clienti del prodotto
    sconto_medio  NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (sconto_medio BETWEEN 0 AND 90),
    stato         TEXT NOT NULL DEFAULT 'bozza' CHECK (stato IN ('bozza','approvato','chiuso')),
    iniziativa_id BIGINT REFERENCES trattative(id) ON DELETE SET NULL,   -- la macro-attività del piano tattico
    note          TEXT,
    creato_il     TIMESTAMPTZ NOT NULL DEFAULT now(),
    aggiornato_il TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS budget_prodotto ON budget (prodotto_id);

-- scelte fatte sul singolo centro del budget (il resto si calcola sempre dai dati aggiornati)
CREATE TABLE IF NOT EXISTS budget_centri (
    budget_id    BIGINT NOT NULL REFERENCES budget(id) ON DELETE CASCADE,
    azienda_id   BIGINT NOT NULL REFERENCES aziende(id) ON DELETE CASCADE,
    incluso      BOOLEAN NOT NULL DEFAULT true,
    probabilita  INT CHECK (probabilita BETWEEN 0 AND 100),   -- NULL = calcolata
    strategia    TEXT,                                        -- NULL = proposta dal CRM
    note         TEXT,
    pianificato_il TIMESTAMPTZ,                               -- attività del piano tattico già create
    PRIMARY KEY (budget_id, azienda_id)
);
CREATE INDEX IF NOT EXISTS budget_centri_azienda ON budget_centri (azienda_id);

-- le operazioni possono riferirsi a una voce (es. "censire gli ecografi", "installare sonde sui 40 monitor")
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS voce_id BIGINT REFERENCES prodotti_voci(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS attivita_voce ON attivita (voce_id);

-- Aggiornamento 010: piano del giorno. Si può lanciare più volte.
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS durata_min INTEGER;          -- durata prevista
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS preparazione TEXT;           -- traccia della chiamata / testo della mail
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS resoconto TEXT;              -- com'è andata
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS pianificata_il DATE;         -- giorno in cui è stata messa in piano
ALTER TABLE attivita ADD COLUMN IF NOT EXISTS rimandi INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS piano_giorni (
    giorno  DATE PRIMARY KEY,
    ore     NUMERIC(4,1) NOT NULL DEFAULT 6,
    inizio  TIME NOT NULL DEFAULT '09:00'
);
ALTER TABLE note ADD COLUMN IF NOT EXISTS tipo TEXT;                       -- es. 'processo' per le idee di miglioramento

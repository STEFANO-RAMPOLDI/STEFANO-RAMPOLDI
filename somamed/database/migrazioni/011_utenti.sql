-- Aggiornamento 011: utenti del CRM (chi lavora le attività). Si può lanciare più volte.
CREATE TABLE IF NOT EXISTS utenti (
    id        BIGSERIAL PRIMARY KEY,
    nome      TEXT NOT NULL UNIQUE,            -- nome breve, è quello scritto come "responsabile" delle attività
    cognome   TEXT,
    email     TEXT,
    ruolo     TEXT,
    attivo    BOOLEAN NOT NULL DEFAULT true,
    creato_il TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO utenti (nome, cognome, ruolo) VALUES ('Stefano', 'Rampoldi', 'CEO') ON CONFLICT (nome) DO NOTHING;
-- chi è già indicato come responsabile diventa un utente
INSERT INTO utenti (nome) SELECT DISTINCT responsabile FROM attivita WHERE responsabile IS NOT NULL ON CONFLICT (nome) DO NOTHING;

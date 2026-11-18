-- SomaMed CRM — schema del database
-- PostgreSQL 16 + pgvector (vettori) + pg_trgm (ricerca nomi "simili")

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Divisioni / linee di prodotto di SomaMed (si possono aggiungere)
CREATE TABLE IF NOT EXISTS divisioni (
    nome        TEXT PRIMARY KEY,
    descrizione TEXT
);
INSERT INTO divisioni (nome, descrizione) VALUES
    ('ReDots',  'Procurement intelligence'),
    ('Asimily', 'Cybersecurity dispositivi medici'),
    ('deepc',   'AI radiologia'),
    ('Lepu',    'AI-ECG'),
    ('Airdoc',  'AI retina'),
    ('i-LARI',  'Piattaforma i-LARI / VITA'),
    ('ITEL',    'Schermature RM, radiofarmacia, infrastrutture'),
    ('Lab',     'Distribuzione dispositivi e laboratorio'),
    ('Altro',   'Altro')
ON CONFLICT DO NOTHING;

-- Aziende: ospedali, cliniche, distributori, partner, fornitori
CREATE TABLE IF NOT EXISTS aziende (
    id          BIGSERIAL PRIMARY KEY,
    nome        TEXT NOT NULL UNIQUE,
    tipo        TEXT NOT NULL DEFAULT 'altro'
                CHECK (tipo IN ('ospedale pubblico','ospedale privato','clinica privata',
                                'gruppo sanitario','distributore','partner','fornitore',
                                'università','altro')),
    citta       TEXT,
    regione     TEXT,
    sito        TEXT,
    tag         TEXT[] NOT NULL DEFAULT '{}',
    note        TEXT,
    creata_il   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aziende_nome_trgm ON aziende USING gin (nome gin_trgm_ops);

-- Persone di riferimento
CREATE TABLE IF NOT EXISTS contatti (
    id          BIGSERIAL PRIMARY KEY,
    azienda_id  BIGINT REFERENCES aziende(id) ON DELETE SET NULL,
    nome        TEXT NOT NULL,
    cognome     TEXT,
    ruolo       TEXT,
    email       TEXT,
    telefono    TEXT,
    tag         TEXT[] NOT NULL DEFAULT '{}',
    note        TEXT,
    creato_il   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS contatti_nome_trgm
    ON contatti USING gin ((coalesce(nome,'') || ' ' || coalesce(cognome,'')) gin_trgm_ops);

-- Trattative (opportunità) per divisione
CREATE TABLE IF NOT EXISTS trattative (
    id              BIGSERIAL PRIMARY KEY,
    titolo          TEXT NOT NULL,
    azienda_id      BIGINT REFERENCES aziende(id) ON DELETE SET NULL,
    contatto_id     BIGINT REFERENCES contatti(id) ON DELETE SET NULL,
    divisione       TEXT NOT NULL DEFAULT 'Altro' REFERENCES divisioni(nome),
    fase            TEXT NOT NULL DEFAULT 'primo contatto'
                    CHECK (fase IN ('primo contatto','qualificata','demo','offerta',
                                    'negoziazione','gara','vinta','persa','sospesa')),
    valore_eur      NUMERIC(14,2),
    probabilita     INT CHECK (probabilita BETWEEN 0 AND 100),
    chiusura_prevista DATE,
    prossimo_passo  TEXT,
    embedding       vector(384),
    creata_il       TIMESTAMPTZ NOT NULL DEFAULT now(),
    aggiornata_il   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Attività: chiamate, mail, riunioni, follow-up, compiti
CREATE TABLE IF NOT EXISTS attivita (
    id            BIGSERIAL PRIMARY KEY,
    tipo          TEXT NOT NULL DEFAULT 'compito'
                  CHECK (tipo IN ('chiamata','email','riunione','follow-up','offerta',
                                  'demo','visita','compito')),
    descrizione   TEXT NOT NULL,
    scadenza      TIMESTAMPTZ,
    stato         TEXT NOT NULL DEFAULT 'da fare'
                  CHECK (stato IN ('da fare','fatta','annullata')),
    priorita      TEXT NOT NULL DEFAULT 'media' CHECK (priorita IN ('alta','media','bassa')),
    azienda_id    BIGINT REFERENCES aziende(id) ON DELETE SET NULL,
    contatto_id   BIGINT REFERENCES contatti(id) ON DELETE SET NULL,
    trattativa_id BIGINT REFERENCES trattative(id) ON DELETE SET NULL,
    responsabile  TEXT NOT NULL DEFAULT 'Stefano',
    esito         TEXT,
    completata_il TIMESTAMPTZ,
    embedding     vector(384),
    creata_il     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS attivita_scadenza ON attivita (stato, scadenza);

-- Note libere (verbali, sintesi mail, appunti): la parte "vettoriale"
CREATE TABLE IF NOT EXISTS note (
    id            BIGSERIAL PRIMARY KEY,
    testo         TEXT NOT NULL,
    fonte         TEXT NOT NULL DEFAULT 'chat'
                  CHECK (fonte IN ('chat','email','riunione','telefonata','fiera','documento','altro')),
    azienda_id    BIGINT REFERENCES aziende(id) ON DELETE SET NULL,
    contatto_id   BIGINT REFERENCES contatti(id) ON DELETE SET NULL,
    trattativa_id BIGINT REFERENCES trattative(id) ON DELETE SET NULL,
    embedding     vector(384),
    creata_il     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indici vettoriali (similarità coseno)
CREATE INDEX IF NOT EXISTS note_emb       ON note       USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS attivita_emb   ON attivita   USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS trattative_emb ON trattative USING hnsw (embedding vector_cosine_ops);

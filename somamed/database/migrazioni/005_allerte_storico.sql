-- Aggiornamento 005: allerte di sollecito e riattivazione; storico dei contatti con ogni persona.
-- Si può lanciare più volte.

CREATE TABLE IF NOT EXISTS allerte (
    id            BIGSERIAL PRIMARY KEY,
    tipo          TEXT NOT NULL DEFAULT 'sollecito'
                  CHECK (tipo IN ('sollecito','riattivazione','promemoria')),
    data          DATE NOT NULL,
    messaggio     TEXT NOT NULL,
    stato         TEXT NOT NULL DEFAULT 'attiva' CHECK (stato IN ('attiva','fatta','annullata')),
    contatto_id   BIGINT REFERENCES contatti(id) ON DELETE CASCADE,
    azienda_id    BIGINT REFERENCES aziende(id) ON DELETE CASCADE,
    trattativa_id BIGINT REFERENCES trattative(id) ON DELETE CASCADE,
    attivita_id   BIGINT REFERENCES attivita(id) ON DELETE CASCADE,
    creata_il     TIMESTAMPTZ NOT NULL DEFAULT now(),
    chiusa_il     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS allerte_data ON allerte (stato, data);

-- Per ogni persona: quante volte è stata contattata, quando l'ultima, quante attività aperte
CREATE OR REPLACE VIEW v_storico_contatti AS
SELECT c.id AS contatto_id,
       count(a.id) FILTER (WHERE a.stato = 'fatta')                       AS n_contatti,
       max(coalesce(a.completata_il, a.scadenza)) FILTER (WHERE a.stato = 'fatta') AS ultimo_contatto,
       count(a.id) FILTER (WHERE a.stato = 'da fare')                     AS n_aperte,
       count(DISTINCT a.trattativa_id)                                    AS n_iniziative
FROM contatti c LEFT JOIN attivita a ON a.contatto_id = c.id
GROUP BY c.id;

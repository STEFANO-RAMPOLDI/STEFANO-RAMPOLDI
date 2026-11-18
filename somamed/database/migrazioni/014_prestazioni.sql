-- Aggiornamento 014: indici per le prestazioni.
-- Le chiavi esterne (azienda_id, contatto_id, trattativa_id…) non avevano indici: ogni conteggio
-- "quante persone / attività ha questo centro" leggeva l'intera tabella. Si può lanciare più volte.

-- porta l'estensione vettoriale alla versione installata nell'immagine Docker (0.8: ricerca filtrata migliore)
ALTER EXTENSION vector UPDATE;
CREATE INDEX IF NOT EXISTS contatti_azienda        ON contatti (azienda_id);
CREATE INDEX IF NOT EXISTS contatti_conosciuti     ON contatti (azienda_id) WHERE conosciuto_personalmente;
CREATE INDEX IF NOT EXISTS attivita_azienda_stato  ON attivita (azienda_id, stato);
CREATE INDEX IF NOT EXISTS attivita_contatto_stato ON attivita (contatto_id, stato);
CREATE INDEX IF NOT EXISTS attivita_trattativa     ON attivita (trattativa_id);
CREATE INDEX IF NOT EXISTS attivita_prodotto       ON attivita (prodotto_id);
CREATE INDEX IF NOT EXISTS attivita_responsabile   ON attivita (responsabile, stato);
CREATE INDEX IF NOT EXISTS attivita_da_fare        ON attivita (scadenza) WHERE stato = 'da fare';
CREATE INDEX IF NOT EXISTS trattative_azienda      ON trattative (azienda_id);
CREATE INDEX IF NOT EXISTS trattative_contatto     ON trattative (contatto_id);
CREATE INDEX IF NOT EXISTS trattative_prodotto     ON trattative (prodotto_id);
CREATE INDEX IF NOT EXISTS trattative_obiettivo    ON trattative (obiettivo_id);
CREATE INDEX IF NOT EXISTS note_azienda            ON note (azienda_id);
CREATE INDEX IF NOT EXISTS note_contatto           ON note (contatto_id);
CREATE INDEX IF NOT EXISTS note_trattativa         ON note (trattativa_id);
CREATE INDEX IF NOT EXISTS diario_azienda          ON diario (azienda_id);
CREATE INDEX IF NOT EXISTS diario_contatto         ON diario (contatto_id);
CREATE INDEX IF NOT EXISTS esiti_trattativa        ON esiti_centro (trattativa_id);
CREATE INDEX IF NOT EXISTS esiti_azienda           ON esiti_centro (azienda_id);
CREATE INDEX IF NOT EXISTS allerte_contatto        ON allerte (contatto_id);
CREATE INDEX IF NOT EXISTS allerte_azienda         ON allerte (azienda_id);
CREATE INDEX IF NOT EXISTS allerte_trattativa      ON allerte (trattativa_id);
CREATE INDEX IF NOT EXISTS allerte_attivita        ON allerte (attivita_id);
CREATE INDEX IF NOT EXISTS offerte_contatto        ON offerte (contatto_id);
CREATE INDEX IF NOT EXISTS offerte_origine         ON offerte (origine_id);
CREATE INDEX IF NOT EXISTS offerte_righe_offerta   ON offerte_righe (offerta_id);
CREATE INDEX IF NOT EXISTS offerte_righe_prodotto  ON offerte_righe (prodotto_id);
CREATE INDEX IF NOT EXISTS relazioni_b             ON relazioni_contatti (contatto_b);
-- join su espressioni usate dalle viste (v_aziende: upper(provincia), lower(regione))
CREATE INDEX IF NOT EXISTS province_sigla_upper    ON province (upper(sigla));
CREATE INDEX IF NOT EXISTS regioni_nome_lower      ON regioni (lower(nome));

-- v_iniziative: la versione precedente materializzava una CTE (tutte le attività di tutte le
-- iniziative) e la rileggeva per intero per ogni riga → tempo quadratico (≈6 s con 2.000 iniziative).
-- Ora ogni conteggio usa l'indice attivita_trattativa. Stesse colonne, stesso ordine.
CREATE OR REPLACE VIEW v_iniziative AS
SELECT t.*, o.titolo AS obiettivo, p.nome AS prodotto, az.nome AS azienda,
       (SELECT count(DISTINCT x) FROM (SELECT a.azienda_id x FROM attivita a WHERE a.trattativa_id = t.id
                                       UNION SELECT t.azienda_id) u WHERE x IS NOT NULL) AS n_centri,
       (SELECT count(DISTINCT a.contatto_id) FROM attivita a WHERE a.trattativa_id = t.id) AS n_persone,
       (SELECT count(*) FROM attivita a WHERE a.trattativa_id = t.id) AS n_attivita,
       (SELECT count(*) FROM attivita a WHERE a.trattativa_id = t.id AND a.stato = 'da fare') AS n_aperte,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'vendita') AS n_vendite,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'rifiuto') AS n_rifiuti,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'scelto altro') AS n_scelto_altro,
       (SELECT count(*) FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'sospesa') AS n_sospese
FROM trattative t
LEFT JOIN obiettivi o ON o.id = t.obiettivo_id
LEFT JOIN prodotti p ON p.id = t.prodotto_id
LEFT JOIN aziende az ON az.id = t.azienda_id;

ANALYZE;

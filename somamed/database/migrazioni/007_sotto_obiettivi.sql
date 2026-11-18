-- Aggiornamento 007: sotto-obiettivi con budget, regioni e province; tipologie di clienti dei prodotti.
-- Si può lanciare più volte.
ALTER TABLE obiettivi ADD COLUMN IF NOT EXISTS padre_id BIGINT REFERENCES obiettivi(id) ON DELETE CASCADE;
ALTER TABLE obiettivi ADD COLUMN IF NOT EXISTS regioni  TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE obiettivi ADD COLUMN IF NOT EXISTS province TEXT[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS obiettivi_padre ON obiettivi (padre_id);

ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS tipologie_clienti TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS descrizione_clienti TEXT;

-- Ogni obiettivo con i numeri suoi e di tutti i suoi sotto-obiettivi
DROP VIEW IF EXISTS v_obiettivi;
CREATE VIEW v_obiettivi AS
WITH RECURSIVE albero AS (
    SELECT id AS radice, id FROM obiettivi
    UNION ALL
    SELECT a.radice, o.id FROM albero a JOIN obiettivi o ON o.padre_id = a.id
),
ini AS (
    SELECT a.radice, t.id, t.valore_eur, t.fase,
           EXISTS (SELECT 1 FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'vendita') AS venduta
    FROM albero a JOIN trattative t ON t.obiettivo_id = a.id
)
SELECT o.*, p.titolo AS padre,
       (SELECT count(*) FROM obiettivi f WHERE f.padre_id = o.id) AS n_sotto,
       (SELECT coalesce(sum(f.valore_eur), 0) FROM obiettivi f WHERE f.padre_id = o.id) AS budget_sotto,
       (SELECT count(*) FROM ini WHERE ini.radice = o.id) AS n_iniziative,
       (SELECT count(*) FROM esiti_centro e JOIN ini ON ini.id = e.trattativa_id
         WHERE ini.radice = o.id AND e.esito = 'vendita') AS n_vendite,
       (SELECT coalesce(sum(valore_eur), 0) FROM ini WHERE ini.radice = o.id AND (fase = 'vinta' OR venduta)) AS valore_vinto,
       (SELECT coalesce(sum(valore_eur), 0) FROM ini WHERE ini.radice = o.id
          AND coalesce(fase,'') NOT IN ('vinta','persa') AND NOT venduta) AS valore_aperto
FROM obiettivi o LEFT JOIN obiettivi p ON p.id = o.padre_id;

-- Aggiornamento 006: obiettivi di area e di budget. Si può lanciare più volte.
ALTER TABLE obiettivi ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'area';   -- area / budget
ALTER TABLE obiettivi ADD COLUMN IF NOT EXISTS ambito TEXT;                          -- es. Lombardia, BU Asimily
ALTER TABLE prodotti  ADD COLUMN IF NOT EXISTS attivo BOOLEAN NOT NULL DEFAULT true;

CREATE OR REPLACE VIEW v_obiettivi AS
SELECT o.*,
       (SELECT count(*) FROM trattative t WHERE t.obiettivo_id = o.id) AS n_iniziative,
       (SELECT count(*) FROM esiti_centro e JOIN trattative t ON t.id = e.trattativa_id
         WHERE t.obiettivo_id = o.id AND e.esito = 'vendita') AS n_vendite,
       (SELECT coalesce(sum(t.valore_eur), 0) FROM trattative t
         WHERE t.obiettivo_id = o.id AND (t.fase = 'vinta' OR EXISTS
               (SELECT 1 FROM esiti_centro e WHERE e.trattativa_id = t.id AND e.esito = 'vendita'))) AS valore_vinto,
       (SELECT coalesce(sum(t.valore_eur), 0) FROM trattative t
         WHERE t.obiettivo_id = o.id AND coalesce(t.fase,'') NOT IN ('vinta','persa')) AS valore_aperto
FROM obiettivi o;

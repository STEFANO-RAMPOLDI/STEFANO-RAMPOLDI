-- Aggiornamento 009: le iniziative non si distinguono più in campagna / opportunità / challenge,
-- ma solo per natura delle attività: marketing oppure commerciale. Si può lanciare più volte.
UPDATE trattative SET genere = CASE
    WHEN genere = 'opportunita' THEN 'commerciale'
    WHEN genere = 'campagna' THEN 'marketing'
    WHEN genere = 'challenge' AND azienda_id IS NOT NULL THEN 'commerciale'
    WHEN genere = 'challenge' THEN 'marketing'
    ELSE genere END
WHERE genere IN ('opportunita', 'campagna', 'challenge');
ALTER TABLE trattative ALTER COLUMN genere SET DEFAULT 'commerciale';

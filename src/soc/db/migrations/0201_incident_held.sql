ALTER TABLE incidents DROP CONSTRAINT incidents_status_check;

ALTER TABLE incidents ADD CONSTRAINT incidents_status_check CHECK (
    status IN ('analyzing', 'awaiting_review', 'confirmed', 'human_handling', 'dismissed', 'held')
);

UPDATE incidents
SET details = details #- '{l2_analyze,stopped}'
WHERE details->'l2_analyze'->>'stopped' = 'round_limit';

CREATE TABLE l1_attempts (
    subject_id text PRIMARY KEY,
    subject_type text NOT NULL CHECK (subject_type IN ('alert', 'ticket')),
    failures integer NOT NULL CHECK (failures BETWEEN 1 AND 3)
);

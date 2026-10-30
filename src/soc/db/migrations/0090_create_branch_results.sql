-- Boxes 10-13 (#69): C21 BranchResult, the path each alert (later: ticket) took.
-- A subject is branched once, so "a row exists" means "this subject is done".
-- seq is the save order; L1 entity lookup reads one path by it. record holds the
-- whole C21; the other columns are copies for lookup.

CREATE TABLE branch_results (
    seq bigserial PRIMARY KEY,
    branch_id text NOT NULL UNIQUE CHECK (branch_id LIKE 'br\_%'),
    subject_type text NOT NULL CHECK (subject_type IN ('alert', 'ticket')),
    subject_id text NOT NULL,
    path text NOT NULL,
    created_at bigint NOT NULL,
    record jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    UNIQUE (subject_type, subject_id)
);

CREATE INDEX branch_results_path_seq ON branch_results (path, seq);

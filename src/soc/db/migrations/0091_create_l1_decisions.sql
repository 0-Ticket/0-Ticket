-- Boxes 15, 20 (#69): C23 L1DecisionRecord, promotions, holds and Ticket verdicts.
-- A subject may have several records; the latest is created_at, then seq, highest.
-- record holds the whole C23; the other columns are copies for filters and order.

CREATE TABLE l1_decisions (
    seq bigserial PRIMARY KEY,
    decision_id text NOT NULL UNIQUE CHECK (decision_id LIKE 'ld\_%'),
    subject_type text NOT NULL CHECK (subject_type IN ('alert', 'ticket')),
    subject_id text NOT NULL,
    decision text NOT NULL,
    reason text,
    created_at bigint NOT NULL,
    record jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object')
);

CREATE INDEX l1_decisions_subject ON l1_decisions
    (subject_type, subject_id, created_at DESC, seq DESC);
CREATE INDEX l1_decisions_newest ON l1_decisions (created_at DESC, seq DESC);

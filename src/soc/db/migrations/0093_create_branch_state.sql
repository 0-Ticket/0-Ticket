-- Box 25 (#69): how far alert branching has read, and which alert each duplicate joined.
-- Both live outside the contracts: C5 and C21 stay as they are.

-- The last source_records.seq of an alert that branching has read. One row.
CREATE TABLE branch_position (
    id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_seq bigint NOT NULL,
    updated_at bigint NOT NULL
);

-- A duplicate alert is merged into its first alert once: the primary key makes a
-- second merge of the same duplicate a no-op, so running branching again does not
-- raise the first alert's count twice.
CREATE TABLE alert_dedup_merges (
    duplicate_alert_id text PRIMARY KEY REFERENCES alert_records (alert_id) ON DELETE RESTRICT,
    target_alert_id text NOT NULL REFERENCES alert_records (alert_id) ON DELETE RESTRICT,
    merged_at bigint NOT NULL,
    CHECK (duplicate_alert_id <> target_alert_id)
);

CREATE INDEX alert_dedup_merges_target ON alert_dedup_merges (target_alert_id);

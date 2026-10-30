-- Box 6 (#59): normalization failures (C12) and how far each kind has been read.
-- A source record gets at most one outcome: a result (C5 or C13) or a failure.

-- C12 NormalizeFailure, one per source record. record holds the C12 as json; it
-- carries reasons and field names, never log text.
CREATE TABLE normalize_failures (
    source_record_id text PRIMARY KEY,
    source_kind text NOT NULL CHECK (source_kind IN ('alert', 'event')),
    reason text NOT NULL CHECK (reason IN ('unknown_scenario', 'missing_required', 'bad_value')),
    failed_at bigint NOT NULL,
    record json NOT NULL,
    -- RESTRICT: retention keeps a failed source so it can be normalized again later.
    FOREIGN KEY (source_record_id, source_kind)
        REFERENCES source_records (source_record_id, kind) ON DELETE RESTRICT
);

CREATE INDEX normalize_failures_reason_failed_at ON normalize_failures (reason, failed_at);

-- The last source_records.seq normalized per kind. Saved with the batch it ends.
CREATE TABLE normalize_positions (
    kind text PRIMARY KEY CHECK (kind IN ('alert', 'event')),
    last_seq bigint NOT NULL,
    updated_at bigint NOT NULL
);

-- One normalized result per source record.
DROP INDEX alert_records_source;
CREATE UNIQUE INDEX alert_records_source ON alert_records (source_record_id);
DROP INDEX event_records_source;
CREATE UNIQUE INDEX event_records_source ON event_records (source_record_id);

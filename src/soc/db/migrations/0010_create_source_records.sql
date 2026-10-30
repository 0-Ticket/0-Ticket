-- Boxes 4, 5 (#50): C2 SiemAlert as it came from the SIEM connector. Never updated.
-- content holds kind, source_record_id, scenario, raw_ids and fields. It is json,
-- not jsonb, so the text is kept as written, \u0000 included.
CREATE TABLE source_records (
    source_record_id text PRIMARY KEY CHECK (source_record_id LIKE 'src\_%'),
    kind text NOT NULL CHECK (kind IN ('alert', 'event')),
    content json NOT NULL,
    -- When it was stored (UTC epoch ms). Retention counts from here.
    ingested_at bigint NOT NULL,
    -- Arrival order, for normalization (box 6) to read in pages.
    seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    -- Target of the normalized results' (source_record_id, kind) foreign keys.
    UNIQUE (source_record_id, kind)
);

CREATE INDEX source_records_kind_seq ON source_records (kind, seq);
CREATE INDEX source_records_ingested_at ON source_records (ingested_at);

CREATE FUNCTION source_records_reject_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'source_records rows are immutable';
END
$$;

CREATE TRIGGER source_records_immutable
BEFORE UPDATE ON source_records
FOR EACH ROW EXECUTE FUNCTION source_records_reject_update();

-- The connector cursor after the last stored batch, one per cursor key (the SIEM adapter).
CREATE TABLE ingest_cursors (
    cursor_key text PRIMARY KEY,
    cursor text,
    updated_at bigint NOT NULL
);

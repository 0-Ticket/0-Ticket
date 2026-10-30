-- Boxes 8, 9 (#50): normalized results, apart from the source rows they point at.
-- C5 AlertRecord and C13 EventRecord are kept whole in record; the entity and time
-- columns are copies for lookup. Later boxes may update these rows, unlike sources.
-- source_kind is fixed per table, so an alert result cannot point at an event source.
-- A source with results cannot be deleted (RESTRICT): retention skips it.

CREATE TABLE alert_records (
    alert_id text PRIMARY KEY CHECK (alert_id LIKE 'al\_%'),
    source_record_id text NOT NULL,
    source_kind text NOT NULL DEFAULT 'alert' CHECK (source_kind = 'alert'),
    time bigint NOT NULL,
    src_ip text,
    dst_ip text,
    host text,
    record json NOT NULL,
    FOREIGN KEY (source_record_id, source_kind)
        REFERENCES source_records (source_record_id, kind) ON DELETE RESTRICT
);

CREATE INDEX alert_records_source ON alert_records (source_record_id);
CREATE INDEX alert_records_time ON alert_records (time);
CREATE INDEX alert_records_src_ip_time ON alert_records (src_ip, time);
CREATE INDEX alert_records_dst_ip_time ON alert_records (dst_ip, time);
CREATE INDEX alert_records_host_time ON alert_records (host, time);

CREATE TABLE event_records (
    event_id text PRIMARY KEY CHECK (event_id LIKE 'ev\_%'),
    source_record_id text NOT NULL,
    source_kind text NOT NULL DEFAULT 'event' CHECK (source_kind = 'event'),
    time bigint NOT NULL,
    src_ip text,
    dst_ip text,
    host text,
    record json NOT NULL,
    FOREIGN KEY (source_record_id, source_kind)
        REFERENCES source_records (source_record_id, kind) ON DELETE RESTRICT
);

CREATE INDEX event_records_source ON event_records (source_record_id);
CREATE INDEX event_records_time ON event_records (time);
CREATE INDEX event_records_src_ip_time ON event_records (src_ip, time);
CREATE INDEX event_records_dst_ip_time ON event_records (dst_ip, time);
CREATE INDEX event_records_host_time ON event_records (host, time);

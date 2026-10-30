-- Boxes 10-13 (#87): the duplicate representatives, so finding an alert's first alert is
-- one indexed lookup instead of reading every recent alert of the same IP.
-- Outside the contracts like alert_dedup_merges: C5 and C21 stay as they are.

-- One row per representative alert (an alert branched on any path but
-- deduplicated). dedup_key is the hash of the rule_id and the entity set
-- (soc.branch.dedup.dedup_key); first_seen starts the representative's window.
-- A database branched before this migration starts with an empty table: branch
-- it again from an empty database (docs/milestone-l1.md).
CREATE TABLE alert_dedup_representatives (
    alert_id text PRIMARY KEY REFERENCES alert_records (alert_id) ON DELETE RESTRICT,
    dedup_key text NOT NULL,
    first_seen bigint NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX alert_dedup_representatives_key
    ON alert_dedup_representatives (dedup_key, first_seen, alert_id);

CREATE TABLE tickets (
    ticket_id text PRIMARY KEY,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE ticket_entities (
    ticket_id text NOT NULL REFERENCES tickets (ticket_id) ON DELETE CASCADE,
    entity_type text NOT NULL,
    entity_value text NOT NULL,
    PRIMARY KEY (ticket_id, entity_type, entity_value)
);

CREATE INDEX ticket_entities_lookup_idx
    ON ticket_entities (entity_type, entity_value, ticket_id);

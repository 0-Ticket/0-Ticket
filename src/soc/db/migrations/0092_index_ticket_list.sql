-- Box 18 (#69): Ticket list in GET /api/tickets order and its filters.
-- Order: priority descending, created_at, ticket_id in code-point order (COLLATE "C").

CREATE INDEX tickets_list_order ON tickets (
    ((payload ->> 'priority')::bigint) DESC,
    ((payload ->> 'created_at')::bigint),
    ticket_id COLLATE "C"
);
CREATE INDEX tickets_status ON tickets ((payload ->> 'status'));
CREATE INDEX tickets_origin ON tickets ((payload ->> 'origin'));

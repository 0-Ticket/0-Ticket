-- L2 분류용 Ticket 색인 대기. PostgreSQL이 버전과 소속의 원본이다.
CREATE TABLE l2_ticket_index_jobs (
    ticket_id text PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    indexed_revision bigint NOT NULL DEFAULT 0 CHECK (indexed_revision >= 0),
    failed_revision bigint,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO l2_ticket_index_jobs (ticket_id)
SELECT id FROM tickets;

-- Evidence request queue (box 26, D-034). payload is the C22 EvidenceRequest.
-- seq is arrival order. agent is outside C22: whose MCP allowlist the request uses.
-- status and requester are copied out of payload for the queue's indexes.
CREATE TABLE evidence_requests (
    seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    request_id text PRIMARY KEY,
    agent text NOT NULL CHECK (agent <> ''),
    status text NOT NULL,
    requester_type text NOT NULL,
    requester_id text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (payload ->> 'request_id' = request_id),
    CHECK (payload ->> 'status' = status),
    CHECK (payload ->> 'requester_type' = requester_type),
    CHECK (payload ->> 'requester_id' = requester_id)
);

CREATE INDEX evidence_requests_pending_idx
    ON evidence_requests (seq) WHERE status = 'pending';

CREATE INDEX evidence_requests_requester_idx
    ON evidence_requests (requester_type, requester_id, seq);

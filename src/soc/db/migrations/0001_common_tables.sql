-- 공통 테이블(#192). 단계끼리 주고받는 데이터 7가지를 담는다.
-- 컬럼 이름은 contracts/의 최상위 필드 이름과 같다. 시각은 timestamptz, 객체는 jsonb.
-- CHECK는 최상위 컬럼의 목록 값·숫자 범위, triage의 모양과 status, jsonb 칸의 모양(객체·목록)까지 확인한다.
-- jsonb 칸의 안쪽 필드(entities[].type, verdict.decision 등)는 validate_contract()가 검사한다.
-- jsonb 컬럼은 JSON null('null'::jsonb)을 거부한다. null이 될 수 있는 컬럼(triage, verdict, output)은
-- SQL NULL로 넣는다. psycopg의 Jsonb(None)은 JSON null이 되어 IS NULL 조회에 걸리지 않기 때문이다.
-- agent_logs.input만 예외다. 계약상 JSON 값 전체(null 포함)를 받고, NOT NULL이라 null은 JSON null로만 담긴다.
-- agent_logs.input·output은 모든 JSON 값을 받으므로 모양 제약이 없다. 객체·목록 칸은 모양 검사가 JSON null도 거부한다.

CREATE TABLE raw_records (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('alert', 'event')),
    siem_profile text NOT NULL,
    siem_ref text NOT NULL,
    fetched_at timestamptz NOT NULL,
    original jsonb NOT NULL CHECK (jsonb_typeof(original) = 'object'),
    -- 같은 SIEM 문서를 두 번 저장하지 않는다
    UNIQUE (siem_profile, siem_ref)
);

-- raw_id 외래 키의 삭제 동작은 기본(삭제를 막음)이다.
-- 원본 보관 기간(D-008)이 지나 지우는 기능을 만드는 이슈가 이 동작을 정한다.
CREATE TABLE alerts (
    id text PRIMARY KEY,
    raw_id text NOT NULL REFERENCES raw_records (id),
    time timestamptz NOT NULL,
    severity smallint NOT NULL CHECK (severity BETWEEN 0 AND 6),
    title text NOT NULL,
    rule_id text,
    entities jsonb NOT NULL CHECK (jsonb_typeof(entities) = 'array'),
    assets jsonb NOT NULL CHECK (jsonb_typeof(assets) = 'array'),
    triage jsonb
        CHECK (triage IS NULL OR jsonb_typeof(triage) <> 'null')
        -- 객체이고 status가 목록 값이어야 한다. status가 없거나 null이면 IN의 결과가 NULL이고
        -- CHECK는 NULL을 통과로 보므로, IS TRUE로 감싸 거짓으로 만든다.
        CHECK (
            triage IS NULL
            OR (
                jsonb_typeof(triage) = 'object'
                AND (triage ->> 'status' IN ('pending', 'promoted', 'held')) IS TRUE
            )
        ),
    ocsf jsonb NOT NULL CHECK (jsonb_typeof(ocsf) = 'object'),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX alerts_raw_id_idx ON alerts (raw_id);
CREATE INDEX alerts_rule_id_idx ON alerts (rule_id);
-- L1이 1차 판정 대기(triage.status = pending) 알럿을 찾는다
CREATE INDEX alerts_triage_status_idx ON alerts ((triage ->> 'status'));

CREATE TABLE events (
    id text PRIMARY KEY,
    raw_id text NOT NULL REFERENCES raw_records (id),
    time timestamptz NOT NULL,
    ocsf_class integer NOT NULL CHECK (ocsf_class >= 0),
    summary text NOT NULL,
    entities jsonb NOT NULL CHECK (jsonb_typeof(entities) = 'array'),
    assets jsonb NOT NULL CHECK (jsonb_typeof(assets) = 'array'),
    ocsf jsonb NOT NULL CHECK (jsonb_typeof(ocsf) = 'object'),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX events_raw_id_idx ON events (raw_id);

CREATE TABLE tickets (
    id text PRIMARY KEY,
    origin text NOT NULL CHECK (origin IN ('auto', 'scenario', 'l1', 'l3')),
    status text NOT NULL CHECK (status IN ('new', 'closed', 'held', 'escalated', 'linked')),
    alert_ids text[] NOT NULL,
    entities jsonb NOT NULL CHECK (jsonb_typeof(entities) = 'array'),
    verdict jsonb CHECK (verdict IS NULL OR jsonb_typeof(verdict) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX tickets_status_idx ON tickets (status);
CREATE INDEX tickets_alert_ids_idx ON tickets USING gin (alert_ids);

CREATE TABLE incidents (
    id text PRIMARY KEY,
    title text NOT NULL,
    summary text,
    status text NOT NULL CHECK (
        status IN ('analyzing', 'awaiting_review', 'confirmed', 'human_handling', 'dismissed')
    ),
    ticket_ids text[] NOT NULL,
    entities jsonb NOT NULL CHECK (jsonb_typeof(entities) = 'array'),
    severity smallint NOT NULL CHECK (severity BETWEEN 0 AND 6),
    assessed_severity smallint CHECK (assessed_severity BETWEEN 0 AND 6),
    analysis_round integer NOT NULL CHECK (analysis_round >= 0),
    review_round integer NOT NULL CHECK (review_round >= 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX incidents_status_idx ON incidents (status);
CREATE INDEX incidents_ticket_ids_idx ON incidents USING gin (ticket_ids);

CREATE TABLE cases (
    id text PRIMARY KEY,
    -- Incident 하나에 Case 하나
    incident_id text NOT NULL UNIQUE REFERENCES incidents (id),
    title text NOT NULL,
    summary text,
    severity smallint NOT NULL CHECK (severity BETWEEN 0 AND 6),
    entities jsonb NOT NULL CHECK (jsonb_typeof(entities) = 'array'),
    confirmed_by text NOT NULL,
    confirmed_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('open', 'in_progress', 'resolved')),
    assignee text,
    resolved_at timestamptz,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE TABLE agent_logs (
    id text PRIMARY KEY,
    run_id text NOT NULL,
    stage text NOT NULL CHECK (stage IN ('l1', 'l2', 'l3')),
    subject_type text NOT NULL CHECK (subject_type IN ('alert', 'ticket', 'incident', 'hunt')),
    subject_id text NOT NULL,
    seq integer NOT NULL CHECK (seq >= 1),
    kind text NOT NULL CHECK (kind IN ('model', 'tool')),
    name text NOT NULL,
    input jsonb NOT NULL,
    output jsonb CHECK (output IS NULL OR jsonb_typeof(output) <> 'null'),
    outcome text NOT NULL CHECK (outcome IN ('ok', 'error')),
    tokens_in integer CHECK (tokens_in >= 0),
    tokens_out integer CHECK (tokens_out >= 0),
    started_at timestamptz NOT NULL,
    duration_ms integer NOT NULL CHECK (duration_ms >= 0),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX agent_logs_subject_idx ON agent_logs (subject_type, subject_id);
-- 같은 작업 안에서 순번이 겹치지 않는다
CREATE UNIQUE INDEX agent_logs_run_seq_idx ON agent_logs (run_id, seq);

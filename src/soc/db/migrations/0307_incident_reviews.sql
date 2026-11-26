-- Incident 검토 이력(#375, D-082). 승인·반려 한 건마다 한 행을 쌓는다. 지우거나 고치지 않는다.
--
-- id는 자동 증가 정수이고 ID 접두사가 없다(ids.PREFIXES는 계약의 ID 정의와 같아야 한다).
-- review_round는 이 결정으로 올라간 incidents.review_round이고, analysis_round는 결정 당시의
-- incidents.analysis_round다. L2 재분석 입력(반려 사유 전달)과 분석 이력 화면의 배치가 쓴다.
-- reason은 사람이 쓴 문장이다. 반려에만 있고 1~500자(코드포인트)이며 없으면 NULL이다.
--
-- soc_agent_reader에는 아무 권한도 주지 않는다. 에이전트 도구가 사람이 쓴 사유를 읽지 못하게 한다.
-- 옛 데이터는 채우지 않는다. 이미 처리된 Incident는 행이 없다.

CREATE TABLE incident_reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    incident_id text NOT NULL REFERENCES incidents (id),
    decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
    reason text CHECK (reason IS NULL OR char_length(reason) BETWEEN 1 AND 500),
    decided_by text NOT NULL,
    review_round integer NOT NULL CHECK (review_round >= 1),
    analysis_round integer NOT NULL CHECK (analysis_round >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (decision = 'reject' OR reason IS NULL),
    UNIQUE (incident_id, review_round)
);

CREATE INDEX incident_reviews_incident_idx ON incident_reviews (incident_id, id);

-- 승인된 Case 색인 대기(#391, D-084). Case 한 건마다 한 행이고 PostgreSQL이 색인 여부의 원본이다.
--
-- indexed_at이 NULL이면 대기다. 실패하면 attempts를 올리고 last_error에 예외 클래스 이름만 남기며
-- next_attempt_at을 뒤로 민다(백오프는 코드가 정한다). 포기하는 상태는 없다.
-- Case는 승인 시점 복사본이라 갱신이 없어서 revision을 두지 않는다.
--
-- soc_agent_reader에는 아무 권한도 주지 않는다. 검색 도구(#392)는 이 표가 아니라 Qdrant와
-- cases·incident_artifacts를 읽는다.
--
-- 이 파일 번호는 D-035의 대역(L2 0200대)이 아니라 현재 가장 큰 번호 다음이다(0303~0309도 03xx를
-- 이어 썼다). 번호가 더 작은 파일은 이미 0309까지 적용한 DB에서 경고를 낸다.

CREATE TABLE case_index_jobs (
    case_id text PRIMARY KEY REFERENCES cases (id) ON DELETE CASCADE,
    indexed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error text,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 워커가 대기이면서 시각이 된 행만 집는다
CREATE INDEX case_index_jobs_pending_idx ON case_index_jobs (created_at, case_id)
    WHERE indexed_at IS NULL;

-- 기존 Case를 워커가 채우게 한다(0306이 기존 Ticket에 한 방식)
INSERT INTO case_index_jobs (case_id)
SELECT id FROM cases;

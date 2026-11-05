-- 수집 실행 이력(#218). 체크포인트의 last_error를 없애고, 조회 대상 하나를 실행할 때마다 한 행을 쌓는다.
-- 컬럼 이름은 contracts/ingest_run.schema.json의 필드 이름과 같다. 성공이면 outcome = 'ok', 실패면
-- 실패 종류 코드다. 대상의 현재 상태는 그 대상의 가장 최근 행(started_at이 가장 늦은 행)으로 읽는다.
-- 행은 soc.ingest.store.record_run()이 쓴다. 원본·체크포인트와 다른 트랜잭션이라 이력 쓰기가 실패해도
-- 수집 결과는 그대로다. CHECK 기준은 0001·0100과 같다. 0100의 ingest_checkpoints만 고치고
-- 다른 번호의 테이블은 참조하지 않는다.

ALTER TABLE ingest_checkpoints DROP COLUMN last_error;

CREATE TABLE ingest_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    siem_profile text NOT NULL CHECK (siem_profile <> ''),
    source_kind text NOT NULL CHECK (source_kind IN ('alert', 'event')),
    source_key text NOT NULL CHECK (source_key <> ''),
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    -- 'ok' 또는 실패 원인의 종류 코드. 원문과 비밀은 넣지 않는다
    outcome text NOT NULL CHECK (outcome ~ '^[a-z][a-z0-9_]*$'),
    pages integer NOT NULL CHECK (pages >= 0),
    inserted integer NOT NULL CHECK (inserted >= 0),
    CHECK (finished_at >= started_at)
);

-- 대상별 최근 실행 조회용
CREATE INDEX ingest_runs_source_started_at_idx
    ON ingest_runs (siem_profile, source_kind, source_key, started_at DESC);

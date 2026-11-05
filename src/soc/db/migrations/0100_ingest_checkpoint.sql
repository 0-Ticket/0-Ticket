-- 수집 체크포인트(#218). 수집 대상 하나(siem_profile, source_kind, source_key)마다 다음 실행이 이어서
-- 조회할 위치를 한 행으로 둔다. 컬럼 이름은 contracts/ingest_checkpoint.schema.json의 필드 이름과 같다.
-- 페이지의 raw_records와 이 행은 soc.ingest.store.save_page()가 한 트랜잭션으로 쓴다.
-- CHECK 기준(행 하나만 봐도 깨진 레코드인지 알 수 있는 것)은 0001과 같다. cursor 안쪽 모양은 수집기가
-- 정하므로 객체인지만 본다. 다른 번호의 테이블은 참조하지 않는다.

CREATE TABLE ingest_checkpoints (
    siem_profile text NOT NULL CHECK (siem_profile <> ''),
    source_kind text NOT NULL CHECK (source_kind IN ('alert', 'event')),
    -- 설정의 조회 대상(alias 또는 인덱스·데이터 스트림 패턴). 바꾸면 처음부터 다시 조회한다
    source_key text NOT NULL CHECK (source_key <> ''),
    cursor jsonb NOT NULL CHECK (jsonb_typeof(cursor) = 'object'),
    updated_at timestamptz NOT NULL,
    -- 실패 원인의 종류 코드. 성공하면 NULL. 원문과 비밀은 넣지 않는다
    last_error text CHECK (last_error ~ '^[a-z][a-z0-9_]*$'),
    PRIMARY KEY (siem_profile, source_kind, source_key)
);

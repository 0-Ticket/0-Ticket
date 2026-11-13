-- 문서 단위 격리와 실행별 격리 수(#294).
-- RawRecord·격리 행·체크포인트는 soc.ingest.store.save_page()가 페이지마다 한 트랜잭션으로 쓴다.

ALTER TABLE ingest_runs
    ADD COLUMN quarantined integer NOT NULL DEFAULT 0 CHECK (quarantined >= 0);

CREATE TABLE ingest_quarantine (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    siem_profile text NOT NULL CHECK (siem_profile <> ''),
    source_kind text NOT NULL CHECK (source_kind IN ('alert', 'event')),
    source_key text NOT NULL CHECK (source_key <> ''),
    siem_ref text NOT NULL,
    reason_code text NOT NULL CHECK (reason_code ~ '^[a-z][a-z0-9_]*$'),
    original_text text NOT NULL,
    seen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (siem_profile, siem_ref)
);

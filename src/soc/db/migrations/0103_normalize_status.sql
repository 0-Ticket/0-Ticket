-- 정규화 상태(#234). raw_records 한 건마다 행 하나를 두고, 정규화 대상 선택·임대·결과 위치를 담는다.
-- 원본 한 건당 결과 한 건은 이 행의 기본 키와 잠금, result_id 유일 제약이 보장한다.
-- alerts와 events는 바꾸지 않는다.

CREATE TABLE normalize_status (
    raw_id text PRIMARY KEY REFERENCES raw_records (id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed')),
    error_code text,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_attempt_at timestamptz,
    lease_owner text,
    lease_expires_at timestamptz,
    result_kind text CHECK (result_kind IN ('alert', 'event')),
    result_id text UNIQUE,
    CHECK ((result_kind IS NULL) = (result_id IS NULL)),
    CHECK ((status = 'succeeded') = (result_id IS NOT NULL))
);

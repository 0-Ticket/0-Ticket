-- Hunt 테이블과 Ticket의 Hunt 연결(#217). 컬럼 이름은 contracts/hunt.schema.json의 최상위 필드 이름과 같다.
-- CHECK 기준은 0001과 같다: 행 하나만 봐도 깨진 레코드인지 알 수 있는 것만 막는다.
-- hunts는 status 목록 값, attempts·confidence 범위, ID·기법 목록(evidence_ids, attack_techniques)의 NULL
-- 원소, jsonb 칸의 모양까지 확인한다. 상태와 다른 칸이 맞는지(pending·failed → confidence·reason·
-- verified_at null, confirmed → Alert·Event 근거, rejected → 근거 1개 이상, pending이 아니면 attempts
-- 1 이상)는 validate_contract()와 L3 코드가 확인한다. 상태 규칙은 단계 담당자가 바꿀 수 있어서 DB에 두지 않는다.
-- tickets는 origin ↔ hunt_id를 막는다(origin ↔ alert_ids와 같은 기준). 가리키는 Hunt가 confirmed인지는
-- 다른 행을 봐야 하므로 L3 코드가 확인한다.
-- 0001 헤더의 jsonb 규칙(JSON null 거부, null이 될 수 있는 칸은 SQL NULL)도 그대로다. hunts에는 null이 될 수
-- 있는 jsonb 칸이 없다.

CREATE TABLE hunts (
    id text PRIMARY KEY,
    hunt_run_id text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('pending', 'confirmed', 'rejected', 'inconclusive', 'failed')
    ),
    hypothesis text NOT NULL,
    attack_techniques text[] NOT NULL CHECK (array_position(attack_techniques, NULL) IS NULL),
    confidence double precision CHECK (confidence BETWEEN 0 AND 1),
    reason text,
    evidence_ids text[] NOT NULL CHECK (array_position(evidence_ids, NULL) IS NULL),
    entities jsonb NOT NULL CHECK (jsonb_typeof(entities) = 'array'),
    attempts integer NOT NULL CHECK (attempts >= 0),
    verified_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX hunts_status_idx ON hunts (status);
-- 같은 가설 생성 실행에서 나온 Hunt를 모아 본다
CREATE INDEX hunts_hunt_run_id_idx ON hunts (hunt_run_id);

-- hunt_id 외래 키의 삭제 동작은 기본(삭제를 막음)이다. alerts.raw_id와 같다.
-- UNIQUE: Hunt 하나에서 Ticket은 하나만 만든다. NULL끼리는 겹쳐도 막지 않는다.
-- origin = l3인 Ticket이 이미 있는 DB에서는 CHECK 추가가 실패한다. 그런 개발 DB는 다시 만든다.
ALTER TABLE tickets
    ADD COLUMN hunt_id text UNIQUE REFERENCES hunts (id),
    ADD CONSTRAINT tickets_origin_hunt_id_check CHECK ((origin = 'l3') = (hunt_id IS NOT NULL));

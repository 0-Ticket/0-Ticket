-- L3 가설 재료(#221): 보안 뉴스·CISA KEV(threat_news)와 MITRE ATT&CK 기법 목록(attack_techniques).
-- L3만 읽는 테이블이고 공통 계약이 아니다. 에이전트에게는 L3 헌팅 코드가 AgentTask.data로만 넘긴다.
-- 에이전트 DB 읽기 역할(#211)에는 이 두 테이블의 권한을 주지 않는다.
-- 컬럼 모양(목록 text[], 시각 timestamptz)과 CHECK 기준(행 하나만 봐도 깨진 레코드인지 알 수 있는 것)은
-- 0001·0002와 같다. 다른 번호의 테이블은 참조하지 않는다.

CREATE TABLE threat_news (
    -- L3 안에서만 쓰는 일련번호. Hunt details가 뉴스를 가리킬 때 쓴다. 손으로 넣지 못한다.
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- 설정의 출처 이름. 바꾸면 같은 기사가 새로 저장된다
    source text NOT NULL CHECK (source <> ''),
    kind text NOT NULL CHECK (kind IN ('rss', 'cisa_kev')),
    -- RSS는 guid(없으면 link), KEV는 CVE ID
    source_ref text NOT NULL CHECK (source_ref <> ''),
    -- 제목·요약·링크는 밖에서 온 문자열이다. 지시로 해석하지 않고, 화면에서 링크로 바꾸지 않는다
    title text NOT NULL CHECK (title <> ''),
    summary text NOT NULL,
    link text,
    published_at timestamptz,
    -- 처음 받은 시각. 다시 받아도 바꾸지 않는다
    fetched_at timestamptz NOT NULL,
    -- 제목·요약·링크·발행 시각이 마지막으로 바뀐 시각. 처음에는 fetched_at과 같다
    updated_at timestamptz NOT NULL,
    UNIQUE (source, source_ref)
);

-- 버전마다 쌓는다. 쓰는 쪽이 설정 버전으로 고른다. 한 버전은 트랜잭션 하나로 모두 넣는다.
CREATE TABLE attack_techniques (
    attack_version text NOT NULL CHECK (attack_version <> ''),
    -- Hunt 계약의 attack_techniques 원소와 같은 모양. PostgreSQL 정규식의 $는 문자열 끝에만 맞아
    -- 끝에 \n이 붙은 값도 거부한다
    technique_id text NOT NULL CHECK (technique_id ~ '^T[0-9]{4}(\.[0-9]{3})?$'),
    name text NOT NULL CHECK (name <> ''),
    tactics text[] NOT NULL CHECK (array_position(tactics, NULL) IS NULL),
    PRIMARY KEY (attack_version, technique_id)
);

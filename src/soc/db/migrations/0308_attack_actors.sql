-- ATT&CK 그룹·악성코드·캠페인과 기법의 uses 관계(#389, D-040). L3 가설 생성의 조회 도구
-- get_attack_actor(D-052)가 읽는다. 0300·0301은 고치지 않고 더하기만 한다.
-- 폐기·대체된 행위자·기법·관계와 도구(tool)는 저장하지 않는다. 열 모양과 CHECK 기준은 0300과 같다
-- (행 하나만 봐도 깨진 레코드인지 알 수 있는 것). 이름·별칭은 밖에서 온 문자열이다.

CREATE TABLE attack_actors (
    attack_version text NOT NULL CHECK (attack_version <> ''),
    -- ATT&CK ID. 끝에 \n이 붙은 값도 거부한다(PostgreSQL 정규식의 $는 문자열 끝에만 맞는다)
    actor_id text NOT NULL CHECK (actor_id ~ '^[GSC][0-9]{4}$'),
    kind text NOT NULL CHECK (kind IN ('group', 'malware', 'campaign')),
    name text NOT NULL CHECK (name <> ''),
    -- 이름 자신은 뺀 별칭. 도구가 이름과 함께 대소문자만 무시해 맞춘다
    aliases text[] NOT NULL DEFAULT '{}' CHECK (array_position(aliases, NULL) IS NULL),
    -- 이 버전의 행위자·관계를 마지막으로 받은 시각
    collected_at timestamptz NOT NULL,
    PRIMARY KEY (attack_version, actor_id),
    CHECK (
        (kind = 'group' AND actor_id ~ '^G')
        OR (kind = 'malware' AND actor_id ~ '^S')
        OR (kind = 'campaign' AND actor_id ~ '^C')
    )
);

CREATE TABLE attack_actor_techniques (
    attack_version text NOT NULL,
    actor_id text NOT NULL,
    technique_id text NOT NULL CHECK (technique_id ~ '^T[0-9]{4}(\.[0-9]{3})?$'),
    PRIMARY KEY (attack_version, actor_id, technique_id),
    FOREIGN KEY (attack_version, actor_id) REFERENCES attack_actors ON DELETE CASCADE,
    FOREIGN KEY (attack_version, technique_id) REFERENCES attack_techniques
);

-- 자산 조회 테이블(#241). 자산 행을 채우고 고치는 코드는 이 파일의 범위가 아니다.
-- 에이전트 DB 읽기 역할(0003)에는 권한을 주지 않는다. 자산 조회는 정규화가 쓰는 연결로 한다.

CREATE TABLE assets (
    asset_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text,
    criticality smallint CHECK (criticality BETWEEN 1 AND 5),
    owner text
);

-- entity_value는 soc.entities.normalize_entity_value로 정규화한 값을 넣는다
CREATE TABLE asset_identifiers (
    asset_id bigint NOT NULL REFERENCES assets (asset_id),
    entity_type text NOT NULL
        CHECK (entity_type IN ('ip', 'host', 'user', 'domain', 'url', 'file_hash', 'process')),
    entity_value text NOT NULL CHECK (entity_value <> ''),
    UNIQUE (entity_type, entity_value)
);

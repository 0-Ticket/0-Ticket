-- 알럿 원본과 그 알럿이 가리키는 원본 이벤트의 연결(#218 후속, raw_links 초안).
-- 한 알럿이 여러 이벤트를 가리킬 수 있고 한 이벤트가 여러 알럿에 쓰일 수 있어 외래 키 칸이 아니라 연결 행으로 둔다.
-- raw_id는 알럿 원본, source_raw_id는 그 알럿이 가리키는 이벤트 원본이다. 두 칸 모두 raw_records를 가리키므로
-- 연결 전에 두 원본이 먼저 저장돼 있어야 한다. 연결 행에는 식별자만 넣고 원본 내용은 넣지 않는다.
-- 연결 키를 어느 알럿 필드에서 읽는지는 아직 확인되지 않았다(docs/plans/218-elk-rawrecord.md).

CREATE TABLE raw_links (
    raw_id text NOT NULL REFERENCES raw_records (id),
    source_raw_id text NOT NULL REFERENCES raw_records (id),
    PRIMARY KEY (raw_id, source_raw_id),
    -- 자기 자신을 가리키는 연결은 만들지 않는다
    CHECK (raw_id <> source_raw_id)
);

-- 이벤트 쪽에서 그 이벤트를 가리키는 알럿을 찾는 조회용
CREATE INDEX raw_links_source_raw_id_idx ON raw_links (source_raw_id);

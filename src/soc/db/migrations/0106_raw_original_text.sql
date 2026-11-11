-- 원본 보관 형식 변경(#277, D-049). raw_records.original(jsonb)을 JSON 글자(original_text text)로 바꾼다.
-- jsonb는 \u0000을 받지 않아 NUL이 든 ELK 문서 하나가 페이지 저장 전체를 실패시켰다.
-- original_text는 json.dumps(hit, ensure_ascii=True)로 만든 글자이고, 읽는 쪽이 json.loads로 되살린다.
-- 전제: raw_records가 비어 있어야 한다. 데이터 이전은 범위 밖이라, 비어 있지 않으면 여기서 멈춘다.
-- 확인: SELECT count(*) FROM raw_records; 결과가 0이어야 한다.
-- 유일 제약 (siem_profile, siem_ref)은 그대로 둔다. siem_ref는 이스케이프한 값이라 같은 규칙으로 중복을 막는다.

-- 쓰기 트랜잭션이 검사 뒤에 커밋하지 못하도록 막고, 그 트랜잭션이 끝난 뒤 검사한다.
LOCK TABLE raw_records IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM raw_records) THEN
        RAISE EXCEPTION 'raw_records가 비어 있지 않아 0106을 적용하지 않는다. 데이터 이전은 범위 밖이다';
    END IF;
END
$$;

ALTER TABLE raw_records DROP COLUMN original;
-- 객체로 시작하는 JSON 글자만 받는다. ensure_ascii 직렬화의 객체는 항상 {로 시작한다
ALTER TABLE raw_records
    ADD COLUMN original_text text NOT NULL CHECK (left(original_text, 1) = '{');

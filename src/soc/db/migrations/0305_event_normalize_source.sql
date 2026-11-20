-- 이벤트 정규화 품질 기록(#351). normalize_status.source의 CHECK를 결과 종류별로 나눈다.
-- 알럿과 결과 종류가 없는 행은 기존 허용 목록 또는 NULL이고, 이벤트는 소스 표 이름(소문자·숫자·밑줄),
-- class_4002·class_6003, unknown 꼴이다. 이벤트 이름이 로더가 확인한 표 이름이라는 조건은 로더와 코드가 지킨다.
-- result_kind가 NULL이어도 CHECK가 NULL로 통과하지 않도록 COALESCE를 쓴다.
-- 기존 행의 값은 바꾸지 않는다. 품질이 없는 이벤트 행은 재처리 전까지 NULL이다.

ALTER TABLE normalize_status DROP CONSTRAINT normalize_status_source_check;

ALTER TABLE normalize_status
    ADD CONSTRAINT normalize_status_source_check CHECK (
        source IS NULL
        OR (COALESCE(result_kind, '') = 'event' AND source ~ '^[a-z][a-z0-9_]{0,63}$')
        OR (
            COALESCE(result_kind, '') <> 'event'
            AND source IN ('suricata', 'modsecurity', 'guardduty', 'unknown')
        )
    );

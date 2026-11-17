-- 정규화 결과 품질 기록(#326). Alert만 채우고 기존 행과 Event 행은 NULL로 둔다(거짓 ok를 만들지 않는다).
-- status의 의미와 CHECK는 바꾸지 않는다. 사유 코드는 기존 error_code를 쓴다.

ALTER TABLE normalize_status
    ADD COLUMN outcome text CHECK (outcome IN ('ok', 'partial', 'fallback')),
    ADD COLUMN missing_fields text[] NOT NULL DEFAULT '{}',
    ADD COLUMN source text CHECK (source IN ('suricata', 'modsecurity', 'guardduty', 'unknown'));

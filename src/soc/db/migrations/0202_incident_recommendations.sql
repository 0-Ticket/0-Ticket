-- 권고 조치(#344, D-072). incident_proposals를 recommendations 한 목록의 행으로 바꾼다.
--
-- kind: detection_rule → detection, response_action → response. body → detail.
-- priority·rationale은 옛 행에 값이 없어 NULL로 둔다(지어서 채우지 않는다).
-- title은 본문(detail) 첫 줄을 soc.ticketing.clean_title과 같은 규칙으로 정리한 값이다:
--   앞쪽 공백 8종(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)을 떼고 첫 줄바꿈(CR·LF) 앞까지 자른 뒤,
--   공백 연속을 한 칸으로 줄이고 앞뒤 한 칸을 떼며, 200자(코드포인트)를 넘으면 앞 199자 + '…',
--   공백 밖 글자가 없으면 '(제목 없음)'. 0109(Ticket 제목)와 같은 정규식 목록·자르기이다.
--   파이썬과 SQL의 결과가 같은지는 tests/test_incident_recommendations_db.py가 같은 입력으로 비교한다.
-- seq: 한 Artifact의 목록 전체 순서(1..n). 옛 행은 이전 API 정렬(kind, seq)대로 탐지 → 대응 순으로 다시 매긴다.
--   그래서 유일 제약을 (artifact_id, kind, seq)에서 (artifact_id, seq)로 바꾼다.
--
-- 행이 0건이어도 통과한다(집합 연산뿐이다).

ALTER TABLE incident_proposals DROP CONSTRAINT incident_proposals_kind_check;
UPDATE incident_proposals
SET kind = CASE kind WHEN 'detection_rule' THEN 'detection' ELSE 'response' END;
ALTER TABLE incident_proposals
    ADD CONSTRAINT incident_proposals_kind_check CHECK (kind IN ('response', 'detection'));

ALTER TABLE incident_proposals RENAME COLUMN body TO detail;
ALTER TABLE incident_proposals
    RENAME CONSTRAINT incident_proposals_body_check TO incident_proposals_detail_check;

ALTER TABLE incident_proposals
    ADD COLUMN priority text CHECK (priority IN ('high', 'medium', 'low')),
    ADD COLUMN rationale text,
    ADD COLUMN title text;

ALTER TABLE incident_proposals DROP CONSTRAINT incident_proposals_artifact_id_kind_seq_key;
UPDATE incident_proposals AS p
SET seq = n.new_seq
FROM (
    SELECT id,
           row_number() OVER (
               PARTITION BY artifact_id
               ORDER BY CASE kind WHEN 'detection' THEN 0 ELSE 1 END, seq
           ) AS new_seq
    FROM incident_proposals
) AS n
WHERE n.id = p.id;
ALTER TABLE incident_proposals
    ADD CONSTRAINT incident_proposals_artifact_id_seq_key UNIQUE (artifact_id, seq);

WITH first_line AS (
    SELECT
        id,
        regexp_replace(
            regexp_replace(detail, E'^[\\t\\n\\u000b\\f\\r \\u00a0\\u3000]+', ''),
            E'[\\r\\n].*$', ''
        ) AS raw
    FROM incident_proposals
),
normalized AS (
    SELECT
        id,
        regexp_replace(
            regexp_replace(raw, E'[\\t\\n\\u000b\\f\\r \\u00a0\\u3000]+', ' ', 'g'),
            '^ | $', '', 'g'
        ) AS text
    FROM first_line
)
UPDATE incident_proposals AS p
SET title = CASE
    WHEN n.text !~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]' THEN '(제목 없음)'
    WHEN char_length(n.text) > 200 THEN left(n.text, 199) || '…'
    ELSE n.text
END
FROM normalized AS n
WHERE n.id = p.id;

ALTER TABLE incident_proposals
    ALTER COLUMN title SET NOT NULL,
    ADD CONSTRAINT incident_proposals_title_check
        CHECK (title ~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]');

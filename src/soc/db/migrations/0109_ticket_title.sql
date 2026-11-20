-- Ticket 제목(#343, D-067). tickets.title을 더하고 기존 행을 채운다.
--
-- 제목 규칙은 soc.ticketing의 clean_title·ticket_title과 같다: 공백 8종(탭·LF·VT·FF·CR·공백·
-- U+00A0·U+3000)의 연속을 한 칸으로 줄이고 앞뒤 한 칸을 떼며, 200자(코드포인트)를 넘으면
-- 앞 199자 + '…', 공백 밖 글자가 없으면 '(제목 없음)'이다. 계약 pattern·CHECK가 같은 목록이다.
-- 파이썬과 SQL의 결과가 같은지는 tests/test_ticket_title_db.py가 같은 입력으로 비교한다.
--
-- 채우는 값: auto·scenario·l1은 소속 alert(심각도 내림차순 → time → id 순 첫 번째)의 제목,
-- l3는 hunts.hypothesis. 가리키는 alert가 없거나 제목을 만들 수 없는 행은 '(제목 없음)'이다.

ALTER TABLE tickets ADD COLUMN title text;

WITH source AS (
    SELECT
        t.id,
        CASE
            WHEN t.origin = 'l3' THEN (SELECT h.hypothesis FROM hunts AS h WHERE h.id = t.hunt_id)
            ELSE (
                SELECT a.title
                FROM alerts AS a
                WHERE a.id = ANY (t.alert_ids)
                ORDER BY a.severity DESC, a.time, a.id
                LIMIT 1
            )
        END AS raw
    FROM tickets AS t
),
normalized AS (
    SELECT
        id,
        regexp_replace(
            regexp_replace(raw, E'[\\t\\n\\u000b\\f\\r \\u00a0\\u3000]+', ' ', 'g'),
            '^ | $', '', 'g'
        ) AS text
    FROM source
)
UPDATE tickets AS t
SET title = CASE
    WHEN n.text IS NULL OR n.text !~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]' THEN '(제목 없음)'
    WHEN char_length(n.text) > 200 THEN left(n.text, 199) || '…'
    ELSE n.text
END
FROM normalized AS n
WHERE n.id = t.id;

ALTER TABLE tickets
    ALTER COLUMN title SET NOT NULL,
    ADD CONSTRAINT tickets_title_check CHECK (title ~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]');

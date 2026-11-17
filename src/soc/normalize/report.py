"""소스별 정규화 채움률 점검(#326). normalize_status만 읽고 건수만 낸다(원문 없음)."""

import psycopg

_OUTCOMES = """
SELECT source, outcome, count(*) FROM normalize_status
WHERE status = 'succeeded' AND outcome IS NOT NULL
GROUP BY source, outcome ORDER BY source, outcome
"""
_MISSING = """
SELECT s.source, f.field, count(*) FROM normalize_status s, unnest(s.missing_fields) AS f(field)
WHERE s.status = 'succeeded' AND s.outcome IS NOT NULL
GROUP BY s.source, f.field ORDER BY s.source, f.field
"""


def report_lines(conn: psycopg.Connection) -> list[str]:
    """소스별 총 건수·outcome별 건수와 얻지 못한 필드별 건수를 줄로 돌려준다.

    Alert 결과만 센다. 기록 전 행과 Event 행은 outcome이 NULL이라 빠진다.

    Args:
        conn: DB 연결.
    """
    counts: dict[str, dict[str, int]] = {}
    for source, outcome, number in conn.execute(_OUTCOMES).fetchall():
        counts.setdefault(source, {})[outcome] = number
    lines = []
    for source, by_outcome in counts.items():
        total = sum(by_outcome.values())
        parts = " ".join(f"{o}={by_outcome.get(o, 0)}" for o in ("ok", "partial", "fallback"))
        lines.append(f"{source} total={total} {parts}")
        lines.extend(
            f"{source} missing {field}={number}/{total}"
            for found, field, number in conn.execute(_MISSING).fetchall()
            if found == source
        )
    return lines or ["기록된 Alert 정규화 결과가 없다"]
